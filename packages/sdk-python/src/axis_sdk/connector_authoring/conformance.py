"""Reusable fixture-driven checks. Reports contain metadata and grant no certification."""

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Literal

from pydantic import Field, JsonValue, ValidationError, model_validator

from axis_sdk.connector_authoring.contracts import (
    ConnectorError,
    ContractModel,
    Digest,
    DiscoveryRequest,
    DiscoveryResult,
    ErrorCode,
    HealthResult,
    Identifier,
    OperationContext,
    ProtocolVersion,
    ReadBatch,
    ReadLimits,
    ReadPort,
    ReadRequest,
    SourceConnector,
    negotiate_protocol,
)

FailureCase = Literal["credentials", "schema_drift", "throttling", "partial_data"]
CheckId = Literal[
    "negotiation",
    "discovery",
    "health",
    "read",
    "credentials",
    "schema_drift",
    "throttling",
    "partial_data",
]
_CHECK_IDS: tuple[CheckId, ...] = (
    "negotiation",
    "discovery",
    "health",
    "read",
    "credentials",
    "schema_drift",
    "throttling",
    "partial_data",
)
_FAILURE_IDS: tuple[FailureCase, ...] = (
    "credentials",
    "schema_drift",
    "throttling",
    "partial_data",
)


def _record_bytes(record: dict[str, JsonValue]) -> bytes:
    return (
        json.dumps(
            record,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def records_digest(records: Iterable[dict[str, JsonValue]]) -> str:
    """Digest a known fixture's ordered records independently of page boundaries."""

    digest = hashlib.sha256()
    for record in records:
        digest.update(_record_bytes(record))
    return digest.hexdigest()


class ConformanceProfile(ContractModel):
    resource_id: Identifier
    expected_records: int = Field(ge=0, strict=True)
    expected_digest: Digest
    read_limits: ReadLimits = Field(default_factory=lambda: ReadLimits(max_records=2))
    max_pages: int = Field(default=100, ge=1, le=1_000, strict=True)
    max_resources: int = Field(default=100, ge=1, le=1_000, strict=True)


class ReadExpectation(ContractModel):
    error: ErrorCode | None = None
    completion: Literal["more", "complete", "truncated"] | None = None
    records: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def one_outcome(self):
        if self.error is not None:
            if self.completion is not None or self.records is not None:
                raise ValueError("Failure expectation cannot also expect a batch")
        elif self.completion is None or self.records is None:
            raise ValueError("Successful expectation requires completion and record count")
        return self


@dataclass(frozen=True)
class ReadFixture:
    """Author-owned adapter with an injected local source failure and its request."""

    reader: ReadPort
    request: ReadRequest
    expected: ReadExpectation


class ConformanceCheck(ContractModel):
    check_id: CheckId
    status: Literal["pass", "fail", "not_run"]
    reason: Literal[
        "verified",
        "prerequisite_failed",
        "missing_fixture",
        "context_mismatch",
        "unexpected_error",
        "invalid_result",
        "not_ready",
        "resource_not_found",
        "unexpected_completion",
        "unexpected_records",
        "unexpected_error_code",
        "digest_mismatch",
        "checkpoint_cycle",
        "page_budget_exceeded",
        "invalid_fixture",
    ]
    error: ErrorCode | None = None
    pages: int = Field(default=0, ge=0)
    records: int = Field(default=0, ge=0)


class ConformanceReport(ContractModel):
    connector_id: Identifier
    protocol: ProtocolVersion
    profile: ConformanceProfile
    checks: tuple[ConformanceCheck, ...]

    @property
    def passed(self) -> bool:
        return (
            len(self.checks) == len(_CHECK_IDS)
            and {check.check_id for check in self.checks} == set(_CHECK_IDS)
            and all(check.status == "pass" for check in self.checks)
        )


def _checked_batch(
    reader: ReadPort,
    request: ReadRequest,
    clock: Callable[[], float],
) -> ReadBatch:
    started = clock()
    result = reader.read(request)
    if clock() - started > request.limits.time_budget_seconds:
        raise ConnectorError(ErrorCode.TIME_BUDGET_EXCEEDED)
    if not isinstance(result, ReadBatch):
        raise TypeError("Invalid result type")
    # Revalidate model_construct/model_copy outputs as well as normal instances.
    result = ReadBatch.model_validate(result.model_dump())
    result.validate_for(request)
    return result


def _check_fixture(check_id: FailureCase, fixture: ReadFixture) -> ConformanceCheck:
    required_error = {
        "credentials": ErrorCode.SOURCE_UNAVAILABLE,
        "schema_drift": ErrorCode.RESOURCE_MISMATCH,
        "throttling": ErrorCode.RATE_LIMITED,
    }.get(check_id)
    if (required_error is not None and fixture.expected.error != required_error) or (
        check_id == "partial_data"
        and (fixture.expected.completion != "truncated" or not fixture.expected.records)
    ):
        return ConformanceCheck(check_id=check_id, status="fail", reason="invalid_fixture")
    try:
        result = fixture.reader.read(fixture.request)
    except ConnectorError as error:
        matches = error.code == fixture.expected.error
        return ConformanceCheck(
            check_id=check_id,
            status="pass" if matches else "fail",
            reason="verified" if matches else "unexpected_error_code",
            error=error.code,
            pages=1,
        )
    except Exception:
        return ConformanceCheck(
            check_id=check_id, status="fail", reason="unexpected_error", pages=1
        )
    try:
        if not isinstance(result, ReadBatch):
            raise TypeError("Invalid result type")
        result = ReadBatch.model_validate(result.model_dump())
        result.validate_for(fixture.request)
    except (ConnectorError, ValidationError, TypeError, ValueError):
        return ConformanceCheck(check_id=check_id, status="fail", reason="invalid_result", pages=1)
    # A malformed returned batch must never count as an expected adapter refusal.
    matches = (
        fixture.expected.error is None
        and result.completion == fixture.expected.completion
        and len(result.records) == fixture.expected.records
    )
    return ConformanceCheck(
        check_id=check_id,
        status="pass" if matches else "fail",
        reason="verified" if matches else "unexpected_completion",
        pages=1,
        records=len(result.records),
    )


def _check_stream(
    reader: ReadPort,
    request: ReadRequest,
    profile: ConformanceProfile,
    clock: Callable[[], float],
) -> ConformanceCheck:
    count = 0
    seen_cursors = set()
    digest = hashlib.sha256()
    for page in range(1, profile.max_pages + 1):
        try:
            batch = _checked_batch(reader, request, clock)
        except ConnectorError as error:
            return ConformanceCheck(
                check_id="read",
                status="fail",
                reason="invalid_result",
                error=error.code,
                pages=page,
                records=count,
            )
        except Exception:
            return ConformanceCheck(
                check_id="read",
                status="fail",
                reason="unexpected_error",
                pages=page,
                records=count,
            )
        count += len(batch.records)
        for record in batch.records:
            digest.update(_record_bytes(record))
        reason = None
        if count > profile.expected_records:
            reason = "unexpected_records"
        elif batch.completion == "truncated":
            reason = "unexpected_completion"
        elif batch.completion == "complete":
            if count != profile.expected_records:
                reason = "unexpected_records"
            elif digest.hexdigest() != profile.expected_digest:
                reason = "digest_mismatch"
            else:
                return ConformanceCheck(
                    check_id="read",
                    status="pass",
                    reason="verified",
                    pages=page,
                    records=count,
                )
        elif batch.checkpoint.cursor in seen_cursors:
            reason = "checkpoint_cycle"
        if reason:
            return ConformanceCheck(
                check_id="read",
                status="fail",
                reason=reason,
                pages=page,
                records=count,
            )
        seen_cursors.add(batch.checkpoint.cursor)
        request = ReadRequest(
            context=request.context,
            resource=request.resource,
            limits=request.limits,
            checkpoint=batch.checkpoint,
        )
    return ConformanceCheck(
        check_id="read",
        status="fail",
        reason="page_budget_exceeded",
        pages=profile.max_pages,
        records=count,
    )


def run_conformance(
    source: SourceConnector,
    context: OperationContext,
    profile: ConformanceProfile,
    *,
    failures: Mapping[FailureCase, ReadFixture] | None = None,
    clock: Callable[[], float] = monotonic,
) -> ConformanceReport:
    """Exercise an author's explicit fixture clients, without retries or checkpoint commits.

    Supply trusted, isolated fixture adapters. Synchronous calls cannot be
    preempted by this harness; real clients must retain their driver timeouts.
    """

    context = OperationContext.model_validate(context.model_dump())
    profile = ConformanceProfile.model_validate(profile.model_dump())
    checks: dict[CheckId, ConformanceCheck] = {}
    selection = None
    try:
        descriptor = source.descriptor
        version = negotiate_protocol(
            descriptor,
            required=frozenset({"discovery", "read", "health"}),
        )
        if context.connector_id != descriptor.connector_id or context.protocol != version:
            raise ConnectorError(ErrorCode.CONTEXT_MISMATCH)
        checks["negotiation"] = ConformanceCheck(
            check_id="negotiation",
            status="pass",
            reason="verified",
        )
    except ConnectorError as error:
        checks["negotiation"] = ConformanceCheck(
            check_id="negotiation",
            status="fail",
            reason="unexpected_error",
            error=error.code,
        )
    except Exception:
        checks["negotiation"] = ConformanceCheck(
            check_id="negotiation",
            status="fail",
            reason="unexpected_error",
        )
    if checks["negotiation"].status == "pass":
        try:
            request = DiscoveryRequest(context=context, max_resources=profile.max_resources)
            result = source.discover(request)
            if not isinstance(result, DiscoveryResult):
                raise TypeError("Invalid discovery type")
            result = DiscoveryResult.model_validate(result.model_dump())
            result.validate_for(request)
            if len({resource.resource_id for resource in result.resources}) != len(
                result.resources
            ):
                raise ValueError("Duplicate resource identity")
            selection = next(
                (
                    resource.selection()
                    for resource in result.resources
                    if resource.resource_id == profile.resource_id
                ),
                None,
            )
            checks["discovery"] = ConformanceCheck(
                check_id="discovery",
                status="pass" if selection else "fail",
                reason="verified" if selection else "resource_not_found",
            )
        except Exception:
            checks["discovery"] = ConformanceCheck(
                check_id="discovery",
                status="fail",
                reason="invalid_result",
            )
        try:
            health = source.health(context)
            if not isinstance(health, HealthResult):
                raise TypeError("Invalid health type")
            health = HealthResult.model_validate(health.model_dump())
            checks["health"] = ConformanceCheck(
                check_id="health",
                status="pass" if health.status == "ready" else "fail",
                reason="verified" if health.status == "ready" else "not_ready",
                error=health.reason,
            )
        except Exception:
            checks["health"] = ConformanceCheck(
                check_id="health",
                status="fail",
                reason="invalid_result",
            )
        if selection is not None:
            checks["read"] = _check_stream(
                source,
                ReadRequest(
                    context=context,
                    resource=selection,
                    limits=profile.read_limits,
                ),
                profile,
                clock,
            )
        for name in _FAILURE_IDS:
            fixture = (failures or {}).get(name)
            if fixture is None:
                checks[name] = ConformanceCheck(
                    check_id=name,
                    status="not_run",
                    reason="missing_fixture",
                )
            elif (
                fixture.request.context.tenant_id != context.tenant_id
                or fixture.request.context.connector_id != context.connector_id
                or fixture.request.context.protocol != context.protocol
                or fixture.request.resource.resource_id != profile.resource_id
            ):
                checks[name] = ConformanceCheck(
                    check_id=name,
                    status="fail",
                    reason="context_mismatch",
                )
            else:
                checks[name] = _check_fixture(name, fixture)
    return ConformanceReport(
        connector_id=context.connector_id,
        protocol=context.protocol,
        profile=profile,
        checks=tuple(
            checks.get(
                name,
                ConformanceCheck(
                    check_id=name,
                    status="not_run",
                    reason="prerequisite_failed",
                ),
            )
            for name in _CHECK_IDS
        ),
    )
