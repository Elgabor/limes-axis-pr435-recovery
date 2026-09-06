import json
from dataclasses import replace
from pathlib import Path
from runpy import run_path

import pytest
from pydantic import SecretStr

from axis_sdk.connector_authoring import (
    Checkpoint,
    ErrorCode,
    OperationContext,
    ProtocolRange,
    ReadBatch,
    ReadLimits,
    ReadRequest,
)
from axis_sdk.connector_authoring.conformance import (
    ConformanceProfile,
    ReadExpectation,
    ReadFixture,
    records_digest,
    run_conformance,
)
from axis_sdk.connector_authoring.fixtures import reference_failure_fixtures
from axis_sdk.connector_authoring.reference import ReferenceAsset, ReferenceConnector

ASSETS = tuple(ReferenceAsset(asset_id=str(i), asset_name=f"Synthetic asset {i}") for i in range(3))


def context():
    return OperationContext(
        tenant_id="tenant-fixture",
        connector_id=ReferenceConnector.descriptor.connector_id,
        actor_id="fixture-author",
        operation_id="fixture-run",
    )


def source():
    return ReferenceConnector(context().tenant_id, assets=ASSETS)


def profile(**changes):
    values = dict(
        resource_id="assets",
        expected_records=len(ASSETS),
        expected_digest=records_digest(asset.model_dump() for asset in ASSETS),
        read_limits=ReadLimits(max_records=1),
    )
    return ConformanceProfile(**(values | changes))


def check(report, name):
    return next(item for item in report.checks if item.check_id == name)


@pytest.mark.parametrize("page_size", [1, 2, 3])
def test_reference_conformance_and_all_four_failure_fixtures(page_size):
    connector = source()
    report = run_conformance(
        connector,
        context(),
        profile(read_limits=ReadLimits(max_records=page_size)),
        failures=reference_failure_fixtures(context(), source=connector),
    )
    assert report.passed
    assert len(report.checks) == 8
    assert check(report, "credentials").pages == 1
    assert check(report, "schema_drift").pages == 1
    assert check(report, "read").records == 3
    assert check(report, "read").pages == (3 + page_size - 1) // page_size
    assert report == type(report).model_validate_json(report.model_dump_json())
    payload = report.model_dump_json()
    assert "Synthetic asset" not in payload
    assert "cursor" not in json.loads(payload)


def test_missing_failure_fixtures_cannot_be_a_full_pass():
    report = run_conformance(source(), context(), profile())
    assert check(report, "read").status == "pass"
    assert not report.passed
    assert {item.check_id for item in report.checks if item.status == "not_run"} == {
        "credentials",
        "schema_drift",
        "throttling",
        "partial_data",
    }
    assert not report.model_copy(update={"checks": ()}).passed
    assert not report.model_copy(update={"checks": report.checks[:4] * 2}).passed


def test_unsupported_protocol_does_not_call_adapter_methods():
    class Unsupported(ReferenceConnector):
        descriptor = ReferenceConnector.descriptor.model_copy(
            update={"protocol": ProtocolRange(major=2)}
        )

        def discover(self, request):
            raise AssertionError("No fixture call before negotiation")

        def health(self, request):
            raise AssertionError("No fixture call before negotiation")

        def read(self, request):
            raise AssertionError("No fixture call before negotiation")

    report = run_conformance(Unsupported(context().tenant_id), context(), profile())
    assert check(report, "negotiation").error == ErrorCode.INCOMPATIBLE_PROTOCOL
    assert all(item.status == "not_run" for item in report.checks[1:])
    assert not report.passed


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"expected_records": 4}, "unexpected_records"),
        ({"expected_digest": "0" * 64}, "digest_mismatch"),
        ({"max_pages": 1}, "page_budget_exceeded"),
        ({"resource_id": "missing"}, "resource_not_found"),
    ],
)
def test_golden_fixture_and_page_budget_failures(change, reason):
    report = run_conformance(source(), context(), profile(**change))
    assert any(item.reason == reason and item.status == "fail" for item in report.checks)
    assert not report.passed


def test_empty_source_completes_honestly():
    connector = ReferenceConnector(context().tenant_id, assets=())
    report = run_conformance(
        connector,
        context(),
        profile(
            expected_records=0,
            expected_digest=records_digest(()),
        ),
    )
    result = check(report, "read")
    assert (result.status, result.pages, result.records) == ("pass", 1, 0)


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("cycle", "checkpoint_cycle"),
        ("endless", "page_budget_exceeded"),
    ],
)
def test_empty_pages_cannot_cycle_or_run_without_a_page_bound(mode, expected):
    class Cycling(ReferenceConnector):
        calls = 0

        def read(self, request):
            self.calls += 1
            token = self.calls % 2 if mode == "cycle" else self.calls
            return ReadBatch(
                records=(),
                completion="more",
                checkpoint=Checkpoint(
                    tenant_id=request.context.tenant_id,
                    connector_id=request.context.connector_id,
                    protocol=request.context.protocol,
                    resource=request.resource,
                    cursor=SecretStr(f"private-cursor-{token}"),
                ),
            )

    connector = Cycling(context().tenant_id)
    report = run_conformance(
        connector,
        context(),
        profile(
            expected_records=0,
            expected_digest=records_digest(()),
            max_pages=3,
        ),
    )
    assert check(report, "read").reason == expected
    assert connector.calls == 3
    assert "private-cursor" not in report.model_dump_json()


@pytest.mark.parametrize(
    "mode,code",
    [
        ("rows", ErrorCode.LIMIT_EXCEEDED),
        ("bytes", ErrorCode.LIMIT_EXCEEDED),
        ("checkpoint", ErrorCode.INVALID_CHECKPOINT),
        ("no_progress", ErrorCode.NO_PROGRESS),
    ],
)
def test_invalid_batches_fail_validation_before_progress(mode, code):
    class Broken(ReferenceConnector):
        def read(self, request):
            if mode == "rows":
                return ReadBatch(records=({"a": 1}, {"a": 2}), completion="complete")
            if mode == "bytes":
                return ReadBatch(records=({"a": "private-row" * 100},), completion="complete")
            if mode == "no_progress":
                return ReadBatch(records=(), completion="more")
            return ReadBatch(
                records=(),
                completion="complete",
                checkpoint=Checkpoint(
                    tenant_id="other-tenant",
                    connector_id=request.context.connector_id,
                    protocol=request.context.protocol,
                    resource=request.resource,
                    cursor=SecretStr("opaque"),
                ),
            )

    report = run_conformance(
        Broken(context().tenant_id),
        context(),
        profile(
            read_limits=ReadLimits(max_records=1, max_bytes=200),
        ),
    )
    assert check(report, "read").error == code
    assert check(report, "read").status == "fail"
    assert "private-row" not in report.model_dump_json()


def test_partial_result_is_not_a_completed_golden_fixture():
    class Partial(ReferenceConnector):
        def read(self, request):
            batch = super().read(request)
            return ReadBatch(records=batch.records, completion="truncated")

    report = run_conformance(Partial(context().tenant_id, assets=ASSETS), context(), profile())
    assert check(report, "read").reason == "unexpected_completion"


def test_elapsed_budget_is_checked_without_claiming_to_preempt_the_driver():
    times = iter((0.0, 31.0))
    report = run_conformance(source(), context(), profile(), clock=lambda: next(times))
    assert check(report, "read").error == ErrorCode.TIME_BUDGET_EXCEEDED


def test_raw_provider_errors_are_not_reported_or_retried():
    class Exploding(ReferenceConnector):
        calls = 0

        def read(self, request):
            self.calls += 1
            raise RuntimeError("private-password=must-never-be-reported")

    connector = Exploding(context().tenant_id)
    report = run_conformance(connector, context(), profile())
    assert connector.calls == 1
    assert check(report, "read").reason == "unexpected_error"
    assert "private-password" not in report.model_dump_json()


def test_fixture_must_exercise_the_declared_failure_outcome():
    connector = source()
    failures = reference_failure_fixtures(context(), source=connector)
    failures["credentials"] = replace(
        failures["credentials"],
        expected=ReadExpectation(
            completion="complete",
            records=3,
        ),
    )
    report = run_conformance(connector, context(), profile(), failures=failures)
    assert check(report, "credentials").reason == "invalid_fixture"
    assert not report.passed


def test_invalid_return_is_not_mistaken_for_expected_adapter_error():
    class InvalidReader:
        def read(self, request):
            return ReadBatch(records=({"a": 1}, {"a": 2}), completion="complete")

    connector = source()
    failures = reference_failure_fixtures(context(), source=connector)
    failures["credentials"] = replace(failures["credentials"], reader=InvalidReader())
    report = run_conformance(connector, context(), profile(), failures=failures)
    assert check(report, "credentials").reason == "invalid_result"
    assert not report.passed


def test_failure_fixture_from_another_tenant_is_not_called():
    class Reader:
        def read(self, request):
            raise AssertionError("Mismatched fixture must not execute")

    connector = source()
    failures = reference_failure_fixtures(context(), source=connector)
    original = failures["credentials"]
    request = ReadRequest(
        context=context().model_copy(update={"tenant_id": "other-tenant"}),
        resource=original.request.resource,
    )
    failures["credentials"] = ReadFixture(Reader(), request, original.expected)
    report = run_conformance(connector, context(), profile(), failures=failures)
    assert check(report, "credentials").reason == "context_mismatch"


def test_discovery_limit_and_duplicate_identity_are_rejected():
    class Duplicate(ReferenceConnector):
        def discover(self, request):
            result = super().discover(request)
            return result.model_copy(update={"resources": result.resources * 2})

    for max_resources in (1, 3):
        report = run_conformance(
            Duplicate(context().tenant_id),
            context(),
            profile(
                max_resources=max_resources,
            ),
        )
        assert check(report, "discovery").reason == "invalid_result"
        assert check(report, "read").status == "not_run"


def test_model_construct_cannot_bypass_result_validation():
    class InvalidHealth(ReferenceConnector):
        def health(self, request):
            from axis_sdk.connector_authoring import HealthResult

            return HealthResult.model_construct(status="ready", reason=ErrorCode.SOURCE_UNAVAILABLE)

    report = run_conformance(InvalidHealth(context().tenant_id), context(), profile())
    assert check(report, "health").reason == "invalid_result"
    assert not report.passed


def test_executable_example_runs_without_source_io(capsys):
    namespace = run_path(
        str(Path(__file__).resolve().parents[1] / "examples/connector_conformance.py")
    )
    namespace["main"]()
    output = capsys.readouterr().out
    assert '"status": "pass"' in output
    assert '"status": "ready"' in output
    assert "Synthetic press" not in output


def test_malformed_read_expectations_are_rejected():
    from pydantic import ValidationError

    for payload in ({}, {"error": ErrorCode.RATE_LIMITED, "completion": "truncated"}):
        with pytest.raises(ValidationError):
            ReadExpectation(**payload)
