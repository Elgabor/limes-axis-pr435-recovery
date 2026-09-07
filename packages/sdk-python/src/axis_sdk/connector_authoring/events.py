"""Opt-in event ingress protocol 1.1. Candidates and observations convey no authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import AwareDatetime, Field, JsonValue, SecretBytes, model_validator

from axis_sdk.connector_authoring.contracts import (
    ContractModel,
    Digest,
    Identifier,
    OperationContext,
    ProtocolVersion,
    ResourceSelection,
)

EVENT_PROTOCOL = ProtocolVersion(major=1, minor=1)
EVENT_SUPPORTED_PROTOCOLS = (EVENT_PROTOCOL,)
Ordering = Literal["unordered", "contiguous", "monotonic"]


class EventErrorCode(StrEnum):
    INCOMPATIBLE_PROTOCOL = "incompatible_protocol"
    CONTEXT_MISMATCH = "context_mismatch"
    ADMISSION_DENIED = "admission_denied"
    AUTHENTICATION_FAILED = "authentication_failed"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    INVALID_ENVELOPE = "invalid_envelope"
    SCHEMA_MISMATCH = "schema_mismatch"
    PARTITION_MISMATCH = "partition_mismatch"
    DUPLICATE_CONFLICT = "duplicate_conflict"
    POSITION_GAP = "position_gap"
    POSITION_REWIND = "position_rewind"
    HISTORY_UNAVAILABLE = "history_unavailable"
    RATE_LIMITED = "rate_limited"
    BACKPRESSURE = "backpressure"
    HOST_UNAVAILABLE = "host_unavailable"


class EventError(Exception):
    def __init__(self, code: EventErrorCode) -> None:
        self.code = EventErrorCode(code)
        super().__init__(self.code.value)

    @property
    def retryable(self) -> bool:
        return self.code in {
            EventErrorCode.POSITION_GAP,
            EventErrorCode.HISTORY_UNAVAILABLE,
            EventErrorCode.RATE_LIMITED,
            EventErrorCode.BACKPRESSURE,
            EventErrorCode.HOST_UNAVAILABLE,
        }


class EventEnvelope(ContractModel):
    """Untrusted publisher data. No tenant, actor, credential or approval fields."""

    event_id: Identifier = Field(repr=False)
    resource_id: Identifier = Field(repr=False)
    source_revision: Digest
    schema_fingerprint: Digest
    partition: Identifier = Field(repr=False)
    position: int | None = Field(default=None, ge=0, strict=True)
    occurred_at: AwareDatetime
    event_type: Identifier
    data: dict[str, JsonValue] = Field(repr=False)

    @model_validator(mode="after")
    def normalize_time(self) -> EventEnvelope:
        # One timestamp spelling for the semantic content digest, regardless of input offset.
        try:
            normalized = self.occurred_at.astimezone(UTC)
        except OverflowError:
            raise ValueError("Event time is outside the supported UTC range") from None
        object.__setattr__(self, "occurred_at", normalized)
        return self


def canonical_event_bytes(event: EventEnvelope) -> bytes:
    return json.dumps(
        event.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _fingerprint(values: tuple[str, ...]) -> str:
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


class EventEvidence(ContractModel):
    content_sha256: Digest
    byte_size: int = Field(ge=0, strict=True)
    position_present: bool


class EventCandidate(ContractModel):
    """Validated data for the host's sink. Never serialize this model into audit."""

    context: OperationContext
    resource: ResourceSelection
    event_bytes: SecretBytes = Field(repr=False, min_length=1, max_length=1_048_576)

    @classmethod
    def from_envelope(
        cls, *, context: OperationContext, resource: ResourceSelection, envelope: EventEnvelope,
    ) -> EventCandidate:
        return cls(
            context=context,
            resource=resource,
            event_bytes=SecretBytes(canonical_event_bytes(envelope)),
        )

    @property
    def envelope(self) -> EventEnvelope:
        # Each access yields a detached model; nested JSON mutation cannot change signed data.
        return EventEnvelope.model_validate_json(self.event_bytes.get_secret_value())

    @model_validator(mode="after")
    def bound_resource(self) -> EventCandidate:
        envelope = self.envelope
        if self.event_bytes.get_secret_value() != canonical_event_bytes(envelope):
            raise ValueError("Candidate event bytes must be canonical")
        if self.context.protocol != EVENT_PROTOCOL:
            raise ValueError("Event ingress requires explicitly negotiated protocol 1.1")
        if (
            envelope.resource_id != self.resource.resource_id
            or envelope.source_revision != self.resource.source_revision
            or envelope.schema_fingerprint != self.resource.schema_fingerprint
        ):
            raise ValueError("Event does not match its host-bound resource")
        return self

    @property
    def event_key(self) -> str:
        return _fingerprint(
            (
                self.context.tenant_id,
                self.context.connector_id,
                self.resource.resource_id,
                self.resource.source_revision,
                self.envelope.event_id,
            )
        )

    @property
    def partition_key(self) -> str:
        return _fingerprint(
            (
                self.context.tenant_id,
                self.context.connector_id,
                self.resource.resource_id,
                self.resource.source_revision,
                self.envelope.partition,
            )
        )

    def evidence(self) -> EventEvidence:
        data = self.event_bytes.get_secret_value()
        return EventEvidence(
            content_sha256=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            position_present=self.envelope.position is not None,
        )


class EventObservation(ContractModel):
    """Host ledger facts read under its transaction/claim fence, not authorization flags."""

    event_key: Digest
    partition_key: Digest
    known_content_sha256: Digest | None = None
    committed_position: int | None = Field(default=None, ge=0, strict=True)
    history_complete: bool = False
    capacity_available: bool = False


class EventOrderPolicy(ContractModel):
    ordering: Ordering
    first_position: int = Field(default=0, ge=0, strict=True)


class EventDecision(ContractModel):
    disposition: Literal["new", "duplicate"]
    next_position: int | None = Field(default=None, ge=0, strict=True)


def classify_event(
    candidate: EventCandidate,
    observation: EventObservation,
    policy: EventOrderPolicy,
) -> EventDecision:
    """Pure decision only. The host must atomically recheck, persist and commit it."""

    if (observation.event_key, observation.partition_key) != (
        candidate.event_key,
        candidate.partition_key,
    ):
        raise EventError(EventErrorCode.CONTEXT_MISMATCH)
    if observation.known_content_sha256 is not None:
        if observation.known_content_sha256 != candidate.evidence().content_sha256:
            raise EventError(EventErrorCode.DUPLICATE_CONFLICT)
        return EventDecision(disposition="duplicate", next_position=observation.committed_position)
    if not observation.history_complete:
        raise EventError(EventErrorCode.HISTORY_UNAVAILABLE)
    position = candidate.envelope.position
    if policy.ordering == "unordered":
        if position is not None or observation.committed_position is not None:
            raise EventError(EventErrorCode.INVALID_ENVELOPE)
    else:
        if position is None:
            raise EventError(EventErrorCode.INVALID_ENVELOPE)
        floor = (
            policy.first_position
            if observation.committed_position is None
            else observation.committed_position + 1
        )
        if position < floor:
            raise EventError(EventErrorCode.POSITION_REWIND)
        if policy.ordering == "contiguous" and position > floor:
            raise EventError(EventErrorCode.POSITION_GAP)
    if not observation.capacity_available:
        raise EventError(EventErrorCode.BACKPRESSURE)
    return EventDecision(disposition="new", next_position=position)


class EventAdmissionPort(Protocol):
    def admit(
        self,
        context: OperationContext,
        resource: ResourceSelection,
        *,
        payload_bytes: int,
    ) -> None:
        """Require current host identity/tenant, scope, lease, binding, rate and capacity gates.

        Raise EventError on refusal. Implementations belong to the existing API/worker
        host; a permissive implementation is only valid as an explicitly offline fixture.
        """
        ...
