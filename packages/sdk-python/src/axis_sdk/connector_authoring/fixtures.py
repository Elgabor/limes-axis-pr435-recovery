"""Synthetic failure fixtures for the in-memory reference, not production certification.

Adapter authors must inject equivalent failures through their own fixture source
client. Reusing these readers does not exercise another adapter's error handling.
"""

from dataclasses import dataclass

from axis_sdk.connector_authoring.conformance import FailureCase, ReadExpectation, ReadFixture
from axis_sdk.connector_authoring.contracts import (
    ConnectorError,
    DiscoveryRequest,
    ErrorCode,
    OperationContext,
    ReadBatch,
    ReadLimits,
    ReadRequest,
)
from axis_sdk.connector_authoring.reference import ReferenceConnector


@dataclass(frozen=True)
class UnavailableFixture:
    error: ErrorCode

    def read(self, request: ReadRequest) -> ReadBatch:
        # Deliberately no credential values, raw provider errors, I/O or retry.
        raise ConnectorError(self.error)


class PartialDataFixture:
    def __init__(self, source: ReferenceConnector):
        self.source = source

    def read(self, request: ReadRequest) -> ReadBatch:
        page = self.source.read(request)
        return ReadBatch(records=page.records, completion="truncated")


def reference_failure_fixtures(
    context: OperationContext,
    *,
    source: ReferenceConnector | None = None,
) -> dict[FailureCase, ReadFixture]:
    source = source or ReferenceConnector(context.tenant_id)
    resource = source.discover(DiscoveryRequest(context=context)).resources[0].selection()
    request = ReadRequest(context=context, resource=resource, limits=ReadLimits(max_records=1))
    drift = resource.model_copy(update={"schema_fingerprint": "0" * 64})
    return {
        # Protocol 1.0 reports source unavailability; host credential gating and
        # retry policy remain separate. No credential resolver is simulated here.
        "credentials": ReadFixture(
            reader=UnavailableFixture(ErrorCode.SOURCE_UNAVAILABLE),
            request=request,
            expected=ReadExpectation(error=ErrorCode.SOURCE_UNAVAILABLE),
        ),
        "schema_drift": ReadFixture(
            reader=source,
            request=ReadRequest(context=context, resource=drift),
            expected=ReadExpectation(error=ErrorCode.RESOURCE_MISMATCH),
        ),
        "throttling": ReadFixture(
            reader=UnavailableFixture(ErrorCode.RATE_LIMITED),
            request=request,
            expected=ReadExpectation(error=ErrorCode.RATE_LIMITED),
        ),
        "partial_data": ReadFixture(
            reader=PartialDataFixture(source),
            request=request,
            expected=ReadExpectation(completion="truncated", records=1),
        ),
    }
