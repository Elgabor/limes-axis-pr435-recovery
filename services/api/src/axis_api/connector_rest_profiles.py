"""Offline REST source profiles; construction neither authorizes nor performs I/O."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Annotated, Literal

from axis_sdk.connector_authoring.contracts import (
    CURRENT_PROTOCOL,
    Checkpoint,
    ConnectorError,
    ContractModel,
    Digest,
    ErrorCode,
    Identifier,
    OperationContext,
    ReadLimits,
    ReadRequest,
    ResourceSelection,
)
from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator

Name = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")]
MemberPath = Annotated[tuple[Name, ...], Field(min_length=1, max_length=8)]
ParameterValue = str | int | bool
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_SEGMENT = re.compile(r"[A-Za-z0-9._~-]+")


class RestParameter(ContractModel):
    name: Name
    value_type: Literal["string", "integer", "boolean"]
    required: bool = Field(default=False, strict=True)


class OpaqueCursorPagination(ContractModel):
    kind: Literal["opaque_cursor"] = "opaque_cursor"
    parameter: Name
    next_path: MemberPath


class NextLinkPagination(ContractModel):
    kind: Literal["next_link"] = "next_link"
    next_path: MemberPath
    destination_policy: Literal["same_endpoint"] = "same_endpoint"


class RestSourceLimits(ContractModel):
    page: ReadLimits = Field(default_factory=ReadLimits)
    max_pages: int = Field(default=100, ge=1, le=1_000, strict=True)
    max_wire_bytes: int = Field(default=1_048_576, ge=2, le=8_388_608, strict=True)
    max_decoded_bytes: int = Field(default=1_048_576, ge=2, le=8_388_608, strict=True)


class _RestCursor(ContractModel):
    version: Literal["1.0"] = "1.0"
    profile_digest: Digest
    selection_digest: Digest
    token: SecretStr = Field(min_length=1, max_length=3_000)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _path_parameters(template: str) -> tuple[str, ...]:
    names: list[str] = []
    if not template.startswith("/") or len(template) > 1_024:
        raise ValueError("Invalid REST path template")
    for segment in template[1:].split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            name = segment[1:-1]
            if not _NAME.fullmatch(name) or name in names:
                raise ValueError("Invalid REST path parameter")
            names.append(name)
        elif not _SEGMENT.fullmatch(segment) or segment in {".", ".."}:
            raise ValueError("Invalid REST path segment")
    return tuple(names)


class RestSourceProfile(ContractModel):
    """One declared collection. Endpoint and credential authority stays in the host."""

    version: Literal["1.0"] = "1.0"
    endpoint_profile_id: Identifier
    endpoint_profile_revision: Digest
    collection_id: Identifier
    method: Literal["GET"] = "GET"
    path_template: str = Field(min_length=1, max_length=1_024)
    query_parameters: tuple[RestParameter, ...] = Field(default=(), max_length=32)
    records_path: MemberPath
    schema_strategy: Literal["declared"] = "declared"
    schema_fingerprint: Digest
    consistency: Literal["mutable_traversal"] = "mutable_traversal"
    pagination: Annotated[
        OpaqueCursorPagination | NextLinkPagination, Field(discriminator="kind")
    ]
    limits: RestSourceLimits = Field(default_factory=RestSourceLimits)

    @field_validator("path_template")
    @classmethod
    def bounded_path(cls, value: str) -> str:
        _path_parameters(value)
        return value

    @model_validator(mode="after")
    def distinct_parameters(self) -> RestSourceProfile:
        names = [parameter.name for parameter in self.query_parameters]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate REST query parameter")
        if (
            isinstance(self.pagination, OpaqueCursorPagination)
            and self.pagination.parameter in names
        ):
            raise ValueError("Pagination parameter is reserved for the adapter")
        return self

    def digest(self) -> str:
        return _digest(self.model_dump(mode="json"))

    def selection_digest(
        self,
        *,
        path_values: Mapping[str, str],
        query_values: Mapping[str, ParameterValue],
    ) -> str:
        """Bind traversal inputs without placing their values in checkpoint evidence."""
        path_parameters = _path_parameters(self.path_template)
        if len(path_values) != len(path_parameters) or set(path_values) != set(path_parameters):
            raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)
        if any(
            type(value) is not str
            or len(value) > 1_024
            or not _SEGMENT.fullmatch(value)
            or value in {".", ".."}
            for value in path_values.values()
        ):
            raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)
        parameters = {parameter.name: parameter for parameter in self.query_parameters}
        if len(query_values) > len(parameters) or not set(query_values) <= parameters.keys():
            raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)
        expected_types = {"string": str, "integer": int, "boolean": bool}
        for name, parameter in parameters.items():
            if name not in query_values:
                if parameter.required:
                    raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)
                continue
            value = query_values[name]
            # bool is an int subclass, but accepting it changes the declared query meaning.
            if type(value) is not expected_types[parameter.value_type]:
                raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)
            if isinstance(value, str) and len(value) > 1_024:
                raise ConnectorError(ErrorCode.LIMIT_EXCEEDED)
            if type(value) is int and not -(2**63) <= value < 2**63:
                raise ConnectorError(ErrorCode.LIMIT_EXCEEDED)
        try:
            return _digest({"path": dict(path_values), "query": dict(query_values)})
        except UnicodeError:
            raise ConnectorError(ErrorCode.RESOURCE_MISMATCH) from None

    def _validate_selection(self, context: OperationContext, resource: ResourceSelection) -> None:
        if context.protocol != CURRENT_PROTOCOL:
            raise ConnectorError(ErrorCode.INCOMPATIBLE_PROTOCOL)
        if (
            resource.resource_id != self.collection_id
            or resource.schema_fingerprint != self.schema_fingerprint
        ):
            raise ConnectorError(ErrorCode.RESOURCE_MISMATCH)

    def checkpoint(
        self,
        context: OperationContext,
        resource: ResourceSelection,
        token: SecretStr,
        *,
        path_values: Mapping[str, str],
        query_values: Mapping[str, ParameterValue],
    ) -> Checkpoint:
        """Return a candidate only; the existing host commits it after durable acceptance."""
        self._validate_selection(context, resource)
        selection_digest = self.selection_digest(path_values=path_values, query_values=query_values)
        try:
            cursor = _RestCursor(
                profile_digest=self.digest(), selection_digest=selection_digest, token=token
            )
            # Only this protected envelope and Checkpoint.storage_record() expose cursor bytes.
            encoded = json.dumps(
                {**cursor.model_dump(mode="json"), "token": cursor.token.get_secret_value()},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            return Checkpoint(
                tenant_id=context.tenant_id,
                connector_id=context.connector_id,
                protocol=context.protocol,
                resource=resource,
                cursor=SecretStr(encoded),
            )
        except ValueError:
            raise ConnectorError(ErrorCode.INVALID_CHECKPOINT) from None

    def resume_cursor(
        self,
        request: ReadRequest,
        *,
        path_values: Mapping[str, str],
        query_values: Mapping[str, ParameterValue],
    ) -> SecretStr | None:
        """Validate bindings before a future reader obtains the sensitive provider token."""
        self._validate_selection(request.context, request.resource)
        selection_digest = self.selection_digest(path_values=path_values, query_values=query_values)
        checkpoint = request.checkpoint
        if checkpoint is None:
            return None
        if not checkpoint.matches(request.context, request.resource):
            raise ConnectorError(ErrorCode.INVALID_CHECKPOINT)
        try:
            cursor = _RestCursor.model_validate_json(checkpoint.cursor.get_secret_value())
        except ValueError:
            raise ConnectorError(ErrorCode.INVALID_CHECKPOINT) from None
        if cursor.profile_digest != self.digest() or cursor.selection_digest != selection_digest:
            raise ConnectorError(ErrorCode.INVALID_CHECKPOINT)
        return cursor.token


def parse_rest_source_profile(value: object) -> RestSourceProfile:
    """Map untrusted configuration errors to one safe code, including unknown field names."""
    try:
        return RestSourceProfile.model_validate(value)
    except ValidationError:
        raise ConnectorError(ErrorCode.RESOURCE_MISMATCH) from None
