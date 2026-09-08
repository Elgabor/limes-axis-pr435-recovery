"""Conformance at the real live-sync planner/reader boundary, offline only."""

from pathlib import Path

import pytest
from test_connector_live_sync import (
    APPROVED_DSN,
    DROPZONE_CSV_CONTENT,
    FILE_CSV_CONNECTOR_ID,
    FILE_CSV_LEASE_ID,
    TENANT_ID,
    external_db_live_sync_plan_request,
    external_postgres_live_sync_runtime,
    file_csv_field_mappings,
    file_csv_live_sync_input_summary,
    file_csv_live_sync_runtime,
)

from axis_api.connector_execution import (
    ConnectorLiveSyncPlanRequest,
    postgres_endpoint_target_sha256,
)


@pytest.fixture(params=["csv", "postgres"])
def source(request, tmp_path: Path):
    if request.param == "csv":
        (tmp_path / "dropzone-assets.csv").write_text(DROPZONE_CSV_CONTENT)
        return (
            file_csv_live_sync_runtime(tmp_path),
            ConnectorLiveSyncPlanRequest(
                tenant_id=TENANT_ID,
                connector_id=FILE_CSV_CONNECTOR_ID,
                run_id="run_contract",
                execution_id="execution_contract",
                executed_by="axis-sync-worker-role",
                credential_lease_id=FILE_CSV_LEASE_ID,
                field_mappings=file_csv_field_mappings(),
                input_summary=file_csv_live_sync_input_summary(),
            ),
            "csv_dropzone",
        )
    return (
        external_postgres_live_sync_runtime(),
        external_db_live_sync_plan_request(
            endpoint_target_sha256=postgres_endpoint_target_sha256(APPROVED_DSN),
        ),
        "postgresql",
    )


def test_real_planner_selects_a_versioned_bounded_proposal_reader(source):
    runtime, request, source_kind = source

    plan = runtime.plan(request)

    assert plan.status == "live_sync_plan_ready"
    assert plan.contract_version == "0.1"
    assert plan.descriptor.source_kind == source_kind
    assert plan.descriptor.output_shape == "legacy_proposals"
    assert plan.descriptor.read_modes == ("snapshot_bounded",)
    assert plan.descriptor.incremental is False
    assert plan.descriptor.cdc is False
    assert plan.descriptor.source_writeback is False
    assert plan.descriptor.durable_resume == "not_verified"
    assert plan.descriptor.completion_evidence == "bounded_or_unknown"
    assert plan.max_records > 0
    assert 0 < plan.batch_size <= plan.max_records


@pytest.mark.parametrize(
    ("requirements", "reason"),
    [
        ({"versions": ["0.2", "1.0"]}, "contract_version_unsupported"),
        ({"versions": []}, "contract_version_unsupported"),
        ({"read_mode": "incremental"}, "unsupported_mode"),
        ({"read_mode": "cdc"}, "unsupported_mode"),
        ({"output_shape": "raw_envelope"}, "unsupported_output_shape"),
        ({"required_extensions": ["vendor.unknown"]}, "required_extension_unsupported"),
    ],
)
def test_incompatible_contract_is_refused_before_source_access(
    source,
    monkeypatch,
    requirements,
    reason,
):
    from axis_api.connector_execution import ConnectorLiveSyncBatchRequest

    runtime, request, _ = source
    request = ConnectorLiveSyncPlanRequest.model_validate(
        {
            **request.model_dump(),
            "contract": requirements,
        }
    )

    def forbidden(*args, **kwargs):
        pytest.fail("incompatible contract accessed the source")

    monkeypatch.setattr(Path, "is_file", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    runtime.lease_scoped_secret_resolution_enabled = True
    runtime.secret_resolver = type("ForbiddenResolver", (), {"resolve": forbidden})()
    monkeypatch.setattr("psycopg.connect", forbidden)

    plan = runtime.plan(request)
    batch = runtime.read_batch(
        ConnectorLiveSyncBatchRequest.model_validate(
            {
                **request.model_dump(),
                "offset": 0,
                "batch_size": 2,
            }
        )
    )

    assert plan.status == "live_sync_plan_blocked"
    assert plan.block_reason == reason
    assert batch.status == "live_sync_batch_failed"
    assert batch.error_code == reason
    assert batch.records == []


class SyntheticPostgres:
    """Driver boundary only: execute real adapter SQL against canned rows."""

    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self

    def execute(self, statement):
        self.statements.append(statement)

    def fetchall(self):
        return self.rows


@pytest.mark.parametrize(
    ("offset", "size", "expected_reason"),
    [
        (0, 2, "unknown_legacy"),
        (4, 2, "unknown_legacy"),
        (5, 2, "unknown_legacy"),
        (9, 1, "row_limit"),
        (10, 1, "row_limit"),
    ],
)
def test_real_readers_preserve_unknown_or_limited_completion(
    source,
    tmp_path,
    monkeypatch,
    offset,
    size,
    expected_reason,
):
    from axis_api.connector_execution import ConnectorLiveSyncBatchRequest

    runtime, request, source_kind = source
    if source_kind == "csv_dropzone" and offset >= 9:
        # Twelve rows with a ten-row profile cap: the bounded stop is not EOF.
        (tmp_path / "dropzone-assets.csv").write_text(
            "asset_id,asset_name,risk_level\n"
            + "".join(f"asset_{i},Synthetic {i},low\n" for i in range(12))
        )
    rows = [("order_synthetic", "asset_synthetic", "test", "open", "low")] * size
    if offset == 4:
        rows = rows[:1]
    if offset == 5:
        rows = []
    driver = SyntheticPostgres(rows)
    monkeypatch.setattr("psycopg.connect", lambda *args, **kwargs: driver)

    batch = runtime.read_batch(
        ConnectorLiveSyncBatchRequest.model_validate(
            {
                **request.model_dump(),
                "offset": offset,
                "batch_size": size,
            }
        )
    )

    assert batch.status == "live_sync_batch_read"
    assert batch.output_shape == "legacy_proposals"
    assert batch.completion_evidence == "bounded_or_unknown"
    assert batch.completion_reason == expected_reason
    if offset >= 9:
        assert batch.source_exhausted is True  # Preserve the legacy stop signal.
    if source_kind == "postgresql" and offset < 10:
        assert driver.statements[0] == "SET TRANSACTION READ ONLY"


def test_legacy_result_cannot_imply_verified_completion():
    from axis_api.connector_execution import ConnectorLiveSyncBatchResult

    batch = ConnectorLiveSyncBatchResult(
        adapter="legacy-fixture",
        status="live_sync_batch_read",
        source_exhausted=True,
    )

    assert batch.completion_reason == "unknown_legacy"
    assert batch.completion_evidence == "bounded_or_unknown"


def test_optional_extensions_and_explicit_version_intersection_do_not_enable_features(source):
    runtime, request, _ = source
    request = ConnectorLiveSyncPlanRequest.model_validate(
        {
            **request.model_dump(),
            "contract": {"versions": ["1.0", "0.1"], "optional_extensions": ["vendor.future"]},
        }
    )

    plan = runtime.plan(request)

    assert plan.status == "live_sync_plan_ready"
    assert plan.contract_version == "0.1"
    assert plan.descriptor.source_writeback is False


def test_unregistered_reader_is_refused_even_with_a_supported_contract(source, monkeypatch):
    from axis_api.connector_execution import ConnectorLiveSyncBatchRequest

    runtime, request, _ = source
    request.connector_id = "registered_manifest_without_reader"

    def forbidden(*args, **kwargs):
        pytest.fail("unknown connector accessed the source")

    monkeypatch.setattr(Path, "is_file", forbidden)
    monkeypatch.setattr("psycopg.connect", forbidden)
    plan = runtime.plan(request)
    batch = runtime.read_batch(
        ConnectorLiveSyncBatchRequest.model_validate(
            {
                **request.model_dump(),
                "offset": 0,
                "batch_size": 2,
            }
        )
    )

    assert plan.block_reason == "live_sync_unsupported_connector"
    assert plan.descriptor is None
    assert batch.error_code == "live_sync_unsupported_connector"
    assert batch.completion_reason == "failed"


def test_source_failure_retains_safe_failed_evidence(source, monkeypatch):
    import psycopg

    from axis_api.connector_execution import ConnectorLiveSyncBatchRequest

    runtime, request, _ = source

    def unavailable(*args, **kwargs):
        raise psycopg.OperationalError("private driver diagnostic")

    monkeypatch.setattr(Path, "is_file", lambda *args: False)
    monkeypatch.setattr("psycopg.connect", unavailable)
    batch = runtime.read_batch(
        ConnectorLiveSyncBatchRequest.model_validate(
            {
                **request.model_dump(),
                "offset": 0,
                "batch_size": 2,
            }
        )
    )

    assert batch.error_code == "connector_unavailable"
    assert batch.completion_reason == "failed"
    assert batch.completion_evidence == "bounded_or_unknown"
    assert "private driver diagnostic" not in batch.model_dump_json()


@pytest.mark.parametrize("capability", ["incremental", "cdc", "source_writeback", "delete_capture"])
def test_descriptor_rejects_unimplemented_capability_claims(capability):
    from pydantic import ValidationError

    from axis_api.connector_execution import ConnectorLiveSyncDescriptor

    with pytest.raises(ValidationError):
        ConnectorLiveSyncDescriptor.model_validate({"source_kind": "postgresql", capability: True})
