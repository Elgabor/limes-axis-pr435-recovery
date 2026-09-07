"""Offline webhook validation reference. No listener, registration, persistence or ACK."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime

from pydantic import Field, SecretBytes, SecretStr

from axis_sdk.connector_authoring.contracts import (
    ContractModel,
    Identifier,
    OperationContext,
    ProtocolRange,
    ResourceSelection,
    SourceDescriptor,
)
from axis_sdk.connector_authoring.events import (
    EVENT_PROTOCOL,
    EventAdmissionPort,
    EventCandidate,
    EventEnvelope,
    EventError,
    EventErrorCode,
)
from axis_sdk.connector_authoring.reference import ReferenceAsset


class WebhookLimits(ContractModel):
    max_body_bytes: int = Field(default=65_536, ge=1, le=1_048_576, strict=True)
    signature_max_age_seconds: int = Field(default=300, ge=1, le=300, strict=True)
    signature_future_skew_seconds: int = Field(default=30, ge=0, le=30, strict=True)


class WebhookBinding(ContractModel):
    tenant_id: Identifier
    actor_id: Identifier
    connector_id: Identifier
    resource: ResourceSelection
    partition: Identifier


def signature_input(binding: WebhookBinding, timestamp: str, body: bytes) -> bytes:
    scope = hashlib.sha256(
        json.dumps(
            binding.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return b"axis-event/1.1\n" + scope.encode() + b"\n" + timestamp.encode("ascii") + b"\n" + body


def sign_reference_webhook(
    binding: WebhookBinding,
    *,
    timestamp: str,
    body: bytes,
    key: SecretBytes,
) -> SecretStr:
    """Synthetic producer helper for this Axis-specific profile, not a provider standard."""

    if len(key.get_secret_value()) < 32 or re.fullmatch(r"[0-9]{1,12}", timestamp) is None:
        raise EventError(EventErrorCode.AUTHENTICATION_FAILED)
    return SecretStr(
        "sha256="
        + hmac.digest(
            key.get_secret_value(),
            signature_input(binding, timestamp, body),
            "sha256",
        ).hex()
    )


def reference_schema_fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(
            ReferenceAsset.model_json_schema(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class ReferenceWebhookAdapter:
    """Validate one signed synthetic asset event, then return a host-side candidate."""

    def __init__(self, binding: WebhookBinding, *, limits: WebhookLimits | None = None) -> None:
        self.binding = binding
        self.limits = limits or WebhookLimits()
        self.descriptor = SourceDescriptor(
            connector_id=binding.connector_id,
            protocol=ProtocolRange(min_minor=1, max_minor=1),
            capabilities=frozenset({"event_ingress"}),
        )
        if binding.resource.schema_fingerprint != reference_schema_fingerprint():
            raise EventError(EventErrorCode.SCHEMA_MISMATCH)

    def validate(
        self,
        *,
        context: OperationContext,
        body: bytes,
        timestamp: str,
        signature: SecretStr,
        key: SecretBytes,
        now: datetime,
        admission: EventAdmissionPort,
        content_type: str = "application/json",
        content_encoding: str = "identity",
    ) -> EventCandidate:
        if context.protocol != EVENT_PROTOCOL:
            raise EventError(EventErrorCode.INCOMPATIBLE_PROTOCOL)
        if (context.tenant_id, context.actor_id, context.connector_id) != (
            self.binding.tenant_id,
            self.binding.actor_id,
            self.binding.connector_id,
        ) or context.credential_lease_id is None:
            raise EventError(EventErrorCode.CONTEXT_MISMATCH)
        if not isinstance(body, bytes) or len(body) > self.limits.max_body_bytes:
            raise EventError(EventErrorCode.PAYLOAD_TOO_LARGE)
        if content_type != "application/json" or content_encoding != "identity":
            raise EventError(EventErrorCode.INVALID_ENVELOPE)
        if now.tzinfo is None or now.utcoffset() is None:
            raise EventError(EventErrorCode.AUTHENTICATION_FAILED)
        if not isinstance(timestamp, str) or re.fullmatch(r"[0-9]{1,12}", timestamp) is None:
            raise EventError(EventErrorCode.AUTHENTICATION_FAILED)
        age = now.timestamp() - int(timestamp)
        if (
            not -self.limits.signature_future_skew_seconds
            <= age
            <= (self.limits.signature_max_age_seconds)
        ):
            raise EventError(EventErrorCode.AUTHENTICATION_FAILED)
        if re.fullmatch(r"sha256=[0-9a-f]{64}", signature.get_secret_value()) is None:
            raise EventError(EventErrorCode.AUTHENTICATION_FAILED)
        if not hmac.compare_digest(
            sign_reference_webhook(
                self.binding, timestamp=timestamp, body=body, key=key
            ).get_secret_value(),
            signature.get_secret_value(),
        ):
            raise EventError(EventErrorCode.AUTHENTICATION_FAILED)
        try:
            result = admission.admit(context, self.binding.resource, payload_bytes=len(body))
            if result is not None:
                raise EventError(EventErrorCode.ADMISSION_DENIED)
        except EventError:
            raise
        except Exception:
            raise EventError(EventErrorCode.HOST_UNAVAILABLE) from None
        try:
            # Reject duplicate keys instead of accepting different parser interpretations.
            def unique(pairs):
                value = {}
                for name, item in pairs:
                    if name in value:
                        raise ValueError("Duplicate field")
                    value[name] = item
                return value

            parsed = json.loads(body.decode("utf-8"), object_pairs_hook=unique)
            event = EventEnvelope.model_validate(parsed)
            if event.event_type != "asset.updated":
                raise EventError(EventErrorCode.INVALID_ENVELOPE)
            ReferenceAsset.model_validate(event.data)
            if event.partition != self.binding.partition:
                raise EventError(EventErrorCode.PARTITION_MISMATCH)
            if (
                event.resource_id != self.binding.resource.resource_id
                or event.source_revision != self.binding.resource.source_revision
                or event.schema_fingerprint != self.binding.resource.schema_fingerprint
            ):
                raise EventError(EventErrorCode.SCHEMA_MISMATCH)
            return EventCandidate.from_envelope(
                context=context,
                resource=self.binding.resource,
                envelope=event,
            )
        except (ValueError, RecursionError):
            raise EventError(EventErrorCode.INVALID_ENVELOPE) from None
