"""In-memory authoring example. It is never registered or enabled by the Axis API."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from time import monotonic

from pydantic import Field, SecretStr, TypeAdapter

from axis_sdk.connector_authoring.contracts import (
    CURRENT_PROTOCOL,
    Checkpoint,
    ConnectorError,
    ContractModel,
    DiscoveredResource,
    DiscoveryRequest,
    DiscoveryResult,
    ErrorCode,
    HealthResult,
    Identifier,
    OperationContext,
    ReadBatch,
    ReadRequest,
    SourceDescriptor,
    SourceField,
    batch_byte_size,
)


class ReferenceAsset(ContractModel):
    asset_id: str = Field(min_length=1, max_length=200)
    asset_name: str = Field(min_length=1, max_length=200)


_DEFAULT_ASSETS = (
    ReferenceAsset(asset_id="press-1", asset_name="Press 1"),
    ReferenceAsset(asset_id="press-2", asset_name="Press 2"),
    ReferenceAsset(asset_id="line-1", asset_name="Assembly line"),
)


class ReferenceConnector:
    """A tenant-bound, immutable snapshot with offset cursors and no side effects."""

    descriptor = SourceDescriptor(
        connector_id="authoring_reference_assets",
        capabilities=frozenset({"discovery", "read", "health"}),
    )

    def __init__(
        self,
        tenant_id: str,
        *,
        assets: tuple[ReferenceAsset, ...] = _DEFAULT_ASSETS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._tenant_id = TypeAdapter(Identifier).validate_python(tenant_id)
        self._assets = tuple(assets)
        self._clock = clock
        fields = (
            SourceField(name="asset_id", value_type="string"),
            SourceField(name="asset_name", value_type="string"),
        )
        self._resource = DiscoveredResource(
            resource_id="assets",
            fields=fields,
            schema_fingerprint=hashlib.sha256(json.dumps(
                [field.model_dump() for field in fields], sort_keys=True,
            ).encode()).hexdigest(),
            source_revision=hashlib.sha256(json.dumps(
                [asset.model_dump() for asset in self._assets], sort_keys=True,
            ).encode()).hexdigest(),
        )

    def _require_context(self, context: OperationContext) -> None:
        if context.protocol != CURRENT_PROTOCOL:
            raise ConnectorError(ErrorCode.INCOMPATIBLE_PROTOCOL)
        if (
            context.tenant_id != self._tenant_id
            or context.connector_id != self.descriptor.connector_id
        ):
            raise ConnectorError(ErrorCode.CONTEXT_MISMATCH)

    def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        self._require_context(request.context)
        result = DiscoveryResult(resources=(self._resource,))
        result.validate_for(request)
        return result

    def health(self, context: OperationContext) -> HealthResult:
        self._require_context(context)
        return HealthResult(status="ready")

    def read(self, request: ReadRequest) -> ReadBatch:
        self._require_context(request.context)
        resource = self._resource.selection()
        if request.resource != resource:
            raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)
        offset = 0
        if request.checkpoint is not None:
            token = request.checkpoint.cursor.get_secret_value()
            if not token.isascii() or not token.isdecimal() or len(token) > 10:
                raise ConnectorError(ErrorCode.INVALID_CHECKPOINT)
            offset = int(token)
            if str(offset) != token or offset > len(self._assets):
                raise ConnectorError(ErrorCode.INVALID_CHECKPOINT)

        rows = []
        byte_size = 2  # JSON array brackets, also for an empty batch.
        deadline = self._clock() + request.limits.time_budget_seconds
        for asset in self._assets[offset:offset + request.limits.max_records]:
            if self._clock() >= deadline:
                if not rows:
                    raise ConnectorError(ErrorCode.TIME_BUDGET_EXCEEDED)
                break
            row = asset.model_dump()
            added_bytes = batch_byte_size((row,)) - 2 + bool(rows)
            if byte_size + added_bytes > request.limits.max_bytes:
                if not rows:
                    raise ConnectorError(ErrorCode.RECORD_TOO_LARGE)
                break
            rows.append(row)
            byte_size += added_bytes

        next_offset = offset + len(rows)
        result = ReadBatch(
            records=tuple(rows),
            completion="complete" if next_offset == len(self._assets) else "more",
            checkpoint=Checkpoint(
                tenant_id=request.context.tenant_id,
                connector_id=request.context.connector_id,
                protocol=request.context.protocol,
                resource=resource,
                cursor=SecretStr(str(next_offset)),
            ),
        )
        result.validate_for(request)
        return result
