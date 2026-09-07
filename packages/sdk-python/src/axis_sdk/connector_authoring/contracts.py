"""Connector authoring protocol v1. These contracts convey data, never authority."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=200)]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Capability = Literal["discovery", "read", "health", "writeback", "event_ingress"]


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True, allow_inf_nan=False,
    )


class ProtocolVersion(ContractModel):
    major: int = Field(ge=1, strict=True)
    minor: int = Field(ge=0, strict=True)


CURRENT_PROTOCOL = ProtocolVersion(major=1, minor=0)
SUPPORTED_PROTOCOLS = (CURRENT_PROTOCOL,)


class ProtocolRange(ContractModel):
    """Inclusive minor range in one major; there is no implicit major fallback."""

    major: int = Field(default=1, ge=1, strict=True)
    min_minor: int = Field(default=0, ge=0, strict=True)
    max_minor: int = Field(default=0, ge=0, strict=True)

    @model_validator(mode="after")
    def ordered_range(self) -> ProtocolRange:
        if self.min_minor > self.max_minor:
            raise ValueError("Protocol minor range is reversed")
        return self


class SourceDescriptor(ContractModel):
    connector_id: Identifier
    protocol: ProtocolRange = Field(default_factory=ProtocolRange)
    capabilities: frozenset[Capability]

    @model_validator(mode="after")
    def versioned_event_capability(self) -> SourceDescriptor:
        if (
            "event_ingress" in self.capabilities
            and self.protocol.major == 1
            and self.protocol.min_minor < 1
        ):
            raise ValueError("Event ingress requires protocol 1.1 or later")
        return self


class ErrorCode(StrEnum):
    INCOMPATIBLE_PROTOCOL = "incompatible_protocol"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    CONTEXT_MISMATCH = "context_mismatch"
    RESOURCE_MISMATCH = "resource_mismatch"
    INVALID_CHECKPOINT = "invalid_checkpoint"
    LIMIT_EXCEEDED = "limit_exceeded"
    RECORD_TOO_LARGE = "record_too_large"
    NO_PROGRESS = "no_progress"
    SOURCE_UNAVAILABLE = "source_unavailable"
    RATE_LIMITED = "rate_limited"
    TIME_BUDGET_EXCEEDED = "time_budget_exceeded"


class ConnectorError(Exception):
    """Fixed public-safe code; provider exceptions and payloads must not be attached."""

    def __init__(self, code: ErrorCode) -> None:
        self.code = ErrorCode(code)
        super().__init__(self.code.value)

    @property
    def retryable(self) -> bool:
        return self.code in {
            ErrorCode.SOURCE_UNAVAILABLE, ErrorCode.RATE_LIMITED, ErrorCode.TIME_BUDGET_EXCEEDED,
        }


def negotiate_protocol(
    source: SourceDescriptor,
    *,
    supported: tuple[ProtocolVersion, ...] = SUPPORTED_PROTOCOLS,
    required: frozenset[Capability] = frozenset(),
) -> ProtocolVersion:
    """Select an explicitly implemented common version before invoking an adapter."""

    if not required <= source.capabilities:
        raise ConnectorError(ErrorCode.UNSUPPORTED_CAPABILITY)
    candidates = [
        version for version in supported
        if version.major == source.protocol.major
        and source.protocol.min_minor <= version.minor <= source.protocol.max_minor
    ]
    if not candidates:
        raise ConnectorError(ErrorCode.INCOMPATIBLE_PROTOCOL)
    return max(candidates, key=lambda version: version.minor)


class OperationContext(ContractModel):
    """Host-bound identifiers. Constructing this model does not authorize a call."""

    tenant_id: Identifier
    connector_id: Identifier
    actor_id: Identifier
    operation_id: Identifier
    protocol: ProtocolVersion = CURRENT_PROTOCOL
    credential_lease_id: Identifier | None = None
    egress_policy_id: Identifier | None = None


class ResourceSelection(ContractModel):
    resource_id: Identifier
    schema_fingerprint: Digest
    source_revision: Digest


class SourceField(ContractModel):
    name: Identifier
    value_type: Literal["string", "integer", "number", "boolean", "object", "array"]
    nullable: bool = False


class DiscoveredResource(ResourceSelection):
    fields: tuple[SourceField, ...]

    def selection(self) -> ResourceSelection:
        return ResourceSelection(
            resource_id=self.resource_id,
            schema_fingerprint=self.schema_fingerprint,
            source_revision=self.source_revision,
        )


class DiscoveryRequest(ContractModel):
    context: OperationContext
    max_resources: int = Field(default=100, ge=1, le=1_000, strict=True)


class DiscoveryResult(ContractModel):
    resources: tuple[DiscoveredResource, ...]
    truncated: bool = False

    def validate_for(self, request: DiscoveryRequest) -> None:
        if len(self.resources) > request.max_resources:
            raise ConnectorError(ErrorCode.LIMIT_EXCEEDED)


class Checkpoint(ContractModel):
    """A candidate position. Only the host may commit it after durable batch success."""

    tenant_id: Identifier
    connector_id: Identifier
    protocol: ProtocolVersion
    resource: ResourceSelection
    cursor: SecretStr = Field(min_length=1, max_length=4_096)

    def matches(self, context: OperationContext, resource: ResourceSelection) -> bool:
        return (
            self.tenant_id == context.tenant_id
            and self.connector_id == context.connector_id
            and self.protocol == context.protocol
            and self.resource == resource
        )

    def storage_record(self) -> dict[str, JsonValue]:
        """Reveal the cursor only for the host's tenant-scoped checkpoint store, never audit."""

        return {**self.model_dump(mode="json"), "cursor": self.cursor.get_secret_value()}


class ReadLimits(ContractModel):
    max_records: int = Field(default=100, ge=1, le=1_000, strict=True)
    max_bytes: int = Field(default=1_048_576, ge=2, le=8_388_608, strict=True)
    time_budget_seconds: int = Field(default=30, ge=1, le=300, strict=True)


class ReadRequest(ContractModel):
    context: OperationContext
    resource: ResourceSelection
    limits: ReadLimits = Field(default_factory=ReadLimits)
    checkpoint: Checkpoint | None = None

    @model_validator(mode="after")
    def bound_checkpoint(self) -> ReadRequest:
        if self.checkpoint and not self.checkpoint.matches(self.context, self.resource):
            raise ValueError("Checkpoint does not match the operation and resource")
        return self


class ReadEvidence(ContractModel):
    completion: Literal["more", "complete", "truncated"]
    records_read: int = Field(ge=0)
    byte_size: int = Field(ge=0)
    checkpoint_present: bool


def batch_byte_size(records: tuple[dict[str, JsonValue], ...]) -> int:
    """Canonical UTF-8 JSON array bytes, including brackets and separators."""

    return len(json.dumps(
        records, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
    ).encode("utf-8"))


class ReadBatch(ContractModel):
    records: tuple[dict[str, JsonValue], ...] = Field(repr=False)
    completion: Literal["more", "complete", "truncated"]
    checkpoint: Checkpoint | None = None

    @model_validator(mode="after")
    def honest_truncation(self) -> ReadBatch:
        if self.completion == "truncated" and self.checkpoint is not None:
            raise ValueError("A truncated non-resumable result cannot advertise a checkpoint")
        return self

    def validate_for(self, request: ReadRequest) -> None:
        if (
            len(self.records) > request.limits.max_records
            or batch_byte_size(self.records) > request.limits.max_bytes
        ):
            raise ConnectorError(ErrorCode.LIMIT_EXCEEDED)
        if self.checkpoint and not self.checkpoint.matches(request.context, request.resource):
            raise ConnectorError(ErrorCode.INVALID_CHECKPOINT)
        if self.completion == "more" and (
            self.checkpoint is None
            or (request.checkpoint and self.checkpoint.cursor == request.checkpoint.cursor)
        ):
            raise ConnectorError(ErrorCode.NO_PROGRESS)

    def evidence(self) -> ReadEvidence:
        """Explicit metadata projection; never serialize a ReadBatch into audit."""

        return ReadEvidence(
            completion=self.completion,
            records_read=len(self.records),
            byte_size=batch_byte_size(self.records),
            checkpoint_present=self.checkpoint is not None,
        )


class HealthResult(ContractModel):
    status: Literal["ready", "degraded", "unavailable", "unknown"]
    reason: ErrorCode | None = None

    @model_validator(mode="after")
    def coherent_health(self) -> HealthResult:
        if self.status == "ready" and self.reason is not None:
            raise ValueError("Ready health cannot include a failure reason")
        return self


class WritebackOperation(ContractModel):
    kind: Literal["upsert", "delete"]
    record_key: Identifier = Field(repr=False)
    values: dict[str, JsonValue] = Field(default_factory=dict, repr=False)

    @model_validator(mode="after")
    def delete_has_no_values(self) -> WritebackOperation:
        if self.kind == "delete" and self.values:
            raise ValueError("Delete operations cannot contain replacement values")
        return self


class WritebackRequest(ContractModel):
    context: OperationContext
    resource: ResourceSelection
    approval_id: Identifier
    idempotency_key: Identifier
    operations: tuple[WritebackOperation, ...] = Field(min_length=1, max_length=100, repr=False)
    max_bytes: int = Field(default=1_048_576, ge=2, le=8_388_608, strict=True)
    time_budget_seconds: int = Field(default=30, ge=1, le=300, strict=True)

    @model_validator(mode="after")
    def bounded_operations(self) -> WritebackRequest:
        if batch_byte_size(tuple(op.model_dump() for op in self.operations)) > self.max_bytes:
            raise ValueError("Writeback operations exceed the byte limit")
        return self


class WritebackResult(ContractModel):
    applied_count: int = Field(ge=0)
    source_receipt: SecretStr | None = Field(default=None, min_length=1, max_length=4_096)

    def validate_for(self, request: WritebackRequest) -> None:
        if self.applied_count > len(request.operations):
            raise ConnectorError(ErrorCode.LIMIT_EXCEEDED)


class SourcePort(Protocol):
    @property
    def descriptor(self) -> SourceDescriptor: ...


class DiscoveryPort(Protocol):
    def discover(self, request: DiscoveryRequest) -> DiscoveryResult: ...


class ReadPort(Protocol):
    def read(self, request: ReadRequest) -> ReadBatch: ...


class HealthPort(Protocol):
    def health(self, context: OperationContext) -> HealthResult: ...


class SourceConnector(SourcePort, DiscoveryPort, ReadPort, HealthPort, Protocol):
    """The read-only reference surface; writeback is a separate opt-in port."""


class WritebackPort(Protocol):
    def writeback(self, request: WritebackRequest) -> WritebackResult: ...
