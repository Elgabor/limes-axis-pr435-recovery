"""Executable authoring examples and contract failures, without external source I/O."""

import json
from pathlib import Path
from runpy import run_path
from typing import get_args

import pytest
from pydantic import SecretStr, ValidationError

from axis_sdk.connector_authoring import (
    CURRENT_PROTOCOL,
    Capability,
    Checkpoint,
    ConnectorError,
    DiscoveryRequest,
    DiscoveryResult,
    ErrorCode,
    HealthResult,
    OperationContext,
    ProtocolRange,
    ProtocolVersion,
    ReadBatch,
    ReadLimits,
    ReadRequest,
    ResourceSelection,
    SourceConnector,
    SourceDescriptor,
    WritebackOperation,
    WritebackRequest,
    WritebackResult,
    batch_byte_size,
    negotiate_protocol,
)
from axis_sdk.connector_authoring.reference import ReferenceAsset, ReferenceConnector


def context(**overrides) -> OperationContext:
    return OperationContext(
        **{
            "tenant_id": "tenant-a",
            "connector_id": ReferenceConnector.descriptor.connector_id,
            "actor_id": "operator-a",
            "operation_id": "run-a",
            **overrides,
        }
    )


def selection(source: SourceConnector) -> ResourceSelection:
    discovered = source.discover(DiscoveryRequest(context=context())).resources[0]
    return discovered.selection()


def request(source: SourceConnector, **overrides) -> ReadRequest:
    return ReadRequest(**{"context": context(), "resource": selection(source), **overrides})


def test_negotiation_selects_highest_explicit_common_version() -> None:
    source = SourceDescriptor(
        connector_id="example", protocol=ProtocolRange(min_minor=1, max_minor=3),
        capabilities=frozenset({"read"}),
    )
    selected = negotiate_protocol(
        source,
        supported=(
            CURRENT_PROTOCOL, ProtocolVersion(major=1, minor=2), ProtocolVersion(major=2, minor=0),
        ),
        required=frozenset({"read"}),
    )
    assert selected == ProtocolVersion(major=1, minor=2)


@pytest.mark.parametrize(
    "protocol", [ProtocolRange(major=2), ProtocolRange(min_minor=1, max_minor=2)],
)
def test_negotiation_refuses_missing_common_version(protocol: ProtocolRange) -> None:
    source = SourceDescriptor(connector_id="example", protocol=protocol, capabilities=frozenset())
    with pytest.raises(ConnectorError, match="^incompatible_protocol$"):
        negotiate_protocol(source)


def test_optional_writeback_is_not_inferred_from_a_method_or_manifest() -> None:
    with pytest.raises(ConnectorError, match="^unsupported_capability$"):
        negotiate_protocol(ReferenceConnector.descriptor, required=frozenset({"writeback"}))
    assert not hasattr(ReferenceConnector("tenant-a"), "writeback")
    assert negotiate_protocol(
        ReferenceConnector.descriptor, required=frozenset({"discovery", "read", "health"}),
    ) == CURRENT_PROTOCOL


@pytest.mark.parametrize("payload", [
    {"major": True}, {"major": 0}, {"min_minor": 2, "max_minor": 1}, {"unknown": "field"},
])
def test_invalid_version_ranges_fail_closed(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ProtocolRange.model_validate(payload)


def test_unknown_capabilities_and_credentials_are_not_untyped_extension_bags() -> None:
    assert set(get_args(Capability)) == {
        "discovery", "read", "health", "writeback", "event_ingress",
    }
    with pytest.raises(ValidationError):
        SourceDescriptor(connector_id="example", capabilities=frozenset({"execute_arbitrary"}))
    with pytest.raises(ValidationError) as error:
        context(password="must-not-appear-in-error")
    assert "must-not-appear-in-error" not in str(error.value)


def test_reference_discovery_health_and_paginated_resume() -> None:
    source: SourceConnector = ReferenceConnector("tenant-a")
    assert source.health(context()) == HealthResult(status="ready")
    discovered = source.discover(DiscoveryRequest(context=context(), max_resources=1))
    assert len(discovered.resources) == 1 and not discovered.truncated
    first_request = request(source, limits=ReadLimits(max_records=2))
    first = source.read(first_request)
    first.validate_for(first_request)
    assert [row["asset_id"] for row in first.records] == ["press-1", "press-2"]
    assert first.completion == "more"
    # The host persists only after committing the batch. Its next run restores the same binding.
    committed = Checkpoint.model_validate(first.checkpoint.storage_record())
    next_request = request(
        source, context=context(operation_id="run-b"), checkpoint=committed,
    )
    final = source.read(next_request)
    assert [row["asset_id"] for row in final.records] == ["line-1"]
    assert final.completion == "complete"
    assert source.read(first_request) == first  # Retry before checkpoint commit is deterministic.


@pytest.mark.parametrize("overrides,code", [
    ({"tenant_id": "tenant-b"}, "context_mismatch"),
    ({"connector_id": "other-connector"}, "context_mismatch"),
    ({"protocol": ProtocolVersion(major=2, minor=0)}, "incompatible_protocol"),
])
@pytest.mark.parametrize("operation", ["discover", "read", "health"])
def test_reference_checks_context_before_every_operation(overrides, code, operation) -> None:
    source = ReferenceConnector("tenant-a")
    foreign = context(**overrides)
    with pytest.raises(ConnectorError, match=f"^{code}$"):
        if operation == "discover":
            source.discover(DiscoveryRequest(context=foreign))
        elif operation == "read":
            source.read(request(source, context=foreign))
        else:
            source.health(foreign)


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "tenant-b"),
    ("connector_id", "other-connector"),
    ("protocol", {"major": 2, "minor": 0}),
    ("resource", {"resource_id": "other", "schema_fingerprint": "a" * 64,
                  "source_revision": "b" * 64}),
])
def test_checkpoint_cannot_cross_tenant_source_schema_or_protocol(field, value) -> None:
    source = ReferenceConnector("tenant-a")
    checkpoint = source.read(request(source)).checkpoint
    checkpoint = Checkpoint.model_validate({**checkpoint.storage_record(), field: value})
    with pytest.raises(ValidationError, match="Checkpoint does not match"):
        request(source, checkpoint=checkpoint)


def test_checkpoint_does_not_resume_a_changed_source_snapshot() -> None:
    original = ReferenceConnector("tenant-a")
    first_request = request(original, limits=ReadLimits(max_records=1))
    checkpoint = original.read(first_request).checkpoint
    changed = ReferenceConnector("tenant-a", assets=(
        ReferenceAsset(asset_id="press-1", asset_name="Changed source"),
    ))
    with pytest.raises(ConnectorError, match="^resource_mismatch$"):
        changed.read(first_request)
    with pytest.raises(ValidationError, match="Checkpoint does not match"):
        request(changed, checkpoint=checkpoint)


@pytest.mark.parametrize("token", ["-1", "1.0", "01", "4", "999999999999999", "１", "secret-token"])
def test_reference_rejects_invalid_cursors_without_echoing_them(token: str) -> None:
    source = ReferenceConnector("tenant-a")
    checkpoint = source.read(request(source)).checkpoint
    invalid = Checkpoint.model_validate({**checkpoint.storage_record(), "cursor": token})
    with pytest.raises(ConnectorError) as error:
        source.read(request(source, checkpoint=invalid))
    assert str(error.value) == "invalid_checkpoint"
    assert not error.value.retryable


def test_empty_source_and_exact_final_page_report_complete() -> None:
    source = ReferenceConnector("tenant-a", assets=())
    empty = source.read(request(source))
    assert empty.records == () and empty.completion == "complete"
    source = ReferenceConnector("tenant-a")
    final = source.read(request(source, limits=ReadLimits(max_records=3)))
    assert len(final.records) == 3 and final.completion == "complete"
    after = source.read(request(source, checkpoint=final.checkpoint))
    assert after.records == () and after.completion == "complete"


def test_byte_budget_counts_utf8_json_and_yields_a_resumable_page() -> None:
    row = ReferenceAsset(asset_id="à", asset_name="Pressa è")
    source = ReferenceConnector("tenant-a", assets=(row, row))
    exact_bytes = batch_byte_size((row.model_dump(),))
    first = source.read(request(source, limits=ReadLimits(max_bytes=exact_bytes)))
    assert first.records == (row.model_dump(),) and first.completion == "more"
    assert first.evidence().byte_size == exact_bytes
    with pytest.raises(ConnectorError, match="^record_too_large$"):
        source.read(request(source, limits=ReadLimits(max_bytes=exact_bytes - 1)))


def test_reference_honors_time_budget_and_can_resume_partial_progress() -> None:
    ticks = iter([0, 0, 2])
    source = ReferenceConnector("tenant-a", clock=lambda: next(ticks))
    partial = source.read(request(source, limits=ReadLimits(time_budget_seconds=1)))
    assert len(partial.records) == 1 and partial.completion == "more"
    ticks = iter([0, 2])
    with pytest.raises(ConnectorError, match="^time_budget_exceeded$") as error:
        source.read(request(source, limits=ReadLimits(time_budget_seconds=1)))
    assert error.value.retryable


def test_batch_validation_refuses_overproduction_and_nonprogress() -> None:
    source = ReferenceConnector("tenant-a")
    first = source.read(request(source, limits=ReadLimits(max_records=1)))
    with pytest.raises(ConnectorError, match="^limit_exceeded$"):
        source.read(request(source)).validate_for(request(source, limits=ReadLimits(max_records=1)))
    with pytest.raises(ConnectorError, match="^limit_exceeded$"):
        first.validate_for(request(source, limits=ReadLimits(max_bytes=2)))
    with pytest.raises(ConnectorError, match="^no_progress$"):
        first.validate_for(request(source, checkpoint=first.checkpoint))
    with pytest.raises(ConnectorError, match="^no_progress$"):
        ReadBatch(records=(), completion="more").validate_for(request(source))
    foreign = Checkpoint.model_validate({**first.checkpoint.storage_record(), "tenant_id": "other"})
    with pytest.raises(ConnectorError, match="^invalid_checkpoint$"):
        ReadBatch(records=first.records, completion="more", checkpoint=foreign).validate_for(
            request(source),
        )


def test_audit_projection_contains_no_rows_or_cursor_values() -> None:
    source = ReferenceConnector("tenant-a", assets=(
        ReferenceAsset(asset_id="private-key", asset_name="private-value"),
    ))
    batch = source.read(request(source))
    assert batch.evidence().model_dump() == {
        "completion": "complete", "records_read": 1,
        "byte_size": batch_byte_size(batch.records), "checkpoint_present": True,
    }
    assert "private-key" not in repr(batch) and "private-value" not in repr(batch)
    checkpoint = Checkpoint.model_validate({
        **batch.checkpoint.storage_record(), "cursor": "private-cursor",
    })
    assert "private-cursor" not in checkpoint.model_dump_json()
    assert "private-cursor" not in repr(checkpoint)
    assert checkpoint.storage_record()["cursor"] == "private-cursor"


def test_truncation_is_explicit_and_does_not_claim_a_resumable_position() -> None:
    source = ReferenceConnector("tenant-a")
    truncated = ReadBatch(records=(), completion="truncated")
    truncated.validate_for(request(source))
    assert truncated.evidence().completion == "truncated"
    with pytest.raises(ValidationError, match="cannot advertise a checkpoint"):
        ReadBatch(
            records=(), completion="truncated", checkpoint=source.read(request(source)).checkpoint,
        )


def test_discovery_enforces_requested_bound_and_health_does_not_hide_failure() -> None:
    source = ReferenceConnector("tenant-a")
    discovery = DiscoveryRequest(context=context(), max_resources=1)
    resource = source.discover(discovery).resources[0]
    with pytest.raises(ConnectorError, match="^limit_exceeded$"):
        DiscoveryResult(resources=(resource, resource)).validate_for(discovery)
    with pytest.raises(ValidationError, match="cannot include a failure"):
        HealthResult(status="ready", reason=ErrorCode.SOURCE_UNAVAILABLE)


def test_writeback_requires_explicit_approval_identity_and_bounded_operations() -> None:
    source = ReferenceConnector("tenant-a")
    payload = {
        "context": context(), "resource": selection(source),
        "approval_id": "approval-1", "idempotency_key": "operation-1",
        "operations": (WritebackOperation(kind="upsert", record_key="key", values={"value": 1}),),
    }
    write = WritebackRequest(**payload)
    result = WritebackResult(applied_count=1, source_receipt=SecretStr("private-receipt"))
    result.validate_for(write)
    with pytest.raises(ConnectorError, match="^limit_exceeded$"):
        WritebackResult(applied_count=2).validate_for(write)
    with pytest.raises(ValidationError):
        WritebackRequest(**{key: value for key, value in payload.items() if key != "approval_id"})
    with pytest.raises(ValidationError, match="exceed the byte limit"):
        WritebackRequest(**payload, max_bytes=2)
    with pytest.raises(ValidationError, match="cannot contain replacement"):
        WritebackOperation(kind="delete", record_key="key", values={"unexpected": 1})


def test_non_json_numbers_are_refused() -> None:
    with pytest.raises(ValidationError):
        ReadBatch(records=({"value": float("nan")},), completion="complete")


def test_documented_offline_example_runs_and_prints_only_batch_evidence(capsys) -> None:
    example = Path(__file__).resolve().parents[1] / "examples/connector_authoring.py"
    run_path(str(example), run_name="__main__")
    evidence = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [batch["completion"] for batch in evidence] == ["more", "complete"]
    assert sum(batch["records_read"] for batch in evidence) == 3
    assert all(set(batch) == {
        "completion", "records_read", "byte_size", "checkpoint_present",
    } for batch in evidence)


def test_discovered_selection_and_durable_checkpoint_round_trip_json() -> None:
    source = ReferenceConnector("tenant-a")
    original = request(source, limits=ReadLimits(max_records=1))
    decoded = ReadRequest.model_validate_json(original.model_dump_json())
    assert source.read(decoded) == source.read(original)
    checkpoint = source.read(decoded).checkpoint
    stored_json = json.dumps(checkpoint.storage_record())
    restored = Checkpoint.model_validate_json(stored_json)
    assert source.read(request(source, checkpoint=restored)).records[0]["asset_id"] == "press-2"
