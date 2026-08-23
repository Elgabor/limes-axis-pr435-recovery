from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.connector_execution import (
    LIVE_SYNC_BATCH_FAILED_STATUS,
    LIVE_SYNC_BATCH_READ_STATUS,
    LIVE_SYNC_PLAN_BLOCKED_STATUS,
    LIVE_SYNC_PLAN_FAILED_STATUS,
    LIVE_SYNC_PLAN_READY_STATUS,
    ConnectorLiveSyncBatchRequest,
    ConnectorLiveSyncBatchResult,
    ConnectorLiveSyncFieldMapping,
    ConnectorLiveSyncPlan,
    ConnectorLiveSyncPlanRequest,
    ConnectorLiveSyncRecord,
    ExternalPostgresLiveQueryProfile,
    FileCsvLiveSyncProfile,
    SelfHostedConnectorLiveSyncRuntime,
    postgres_endpoint_target_sha256,
)
from axis_api.connector_manifests import (
    ConnectorManifestCreateRequest,
    ConnectorManifestLifecycleRequest,
    record_demo_connector_manifest,
    transition_demo_connector_manifest_lifecycle,
)
from axis_api.connector_runs import (
    LIVE_SYNC_MAX_BATCHES_PER_EXECUTION,
    ConnectorRunCreateRequest,
    ConnectorRunDispatchRequest,
    ConnectorRunNotFound,
    ConnectorRunSyncExecutionConflict,
    ConnectorRunSyncExecutionRequest,
    ConnectorRunValidationError,
    ConnectorSyncCheckpointClaimConflict,
    ConnectorSyncCheckpointClaimRequest,
    _sync_checkpoint_result_is_public_safe,
    claim_connector_sync_checkpoint,
    dispatch_demo_connector_sync,
    execute_demo_connector_sync,
    record_demo_connector_run,
)
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import Base, utc_now
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorCredentialHandleCreate,
    ConnectorCredentialLeaseCreate,
    ConnectorEgressPolicyCreate,
    ConnectorSyncCheckpointCreate,
    DemoReferenceRecordCreate,
    TenantQuotaUpsert,
)
from axis_api.platform_tenants import TenantQuotaKey

TENANT_ID = "tenant_demo_manufacturing"
FILE_CSV_CONNECTOR_ID = "file_csv_manufacturing_assets"
EXTERNAL_DB_CONNECTOR_ID = "external_db_operational_mirror"
FILE_CSV_LEASE_ID = "lease_file_csv_readonly_20260622"
EXTERNAL_DB_LEASE_ID = "lease_external_db_readonly_20260622"
APPROVED_DSN = "postgresql://readonly.local/axis_external"
UNAPPROVED_DSN = "postgresql://unapproved.local/axis_external"
PRIVATE_ENDPOINT_REF = (
    "private-endpoint://tenant_demo_manufacturing/persisted-operations-postgres-readonly"
)
DROPZONE_CSV_CONTENT = (
    "asset_id,asset_name,domain,station,risk_level\n"
    "asset_press_1,Press 1,Operations,Line 1,low\n"
    "asset_press_2,Press 2,Operations,Line 1,medium\n"
    "asset_press_3,Press 3,Maintenance,Line 2,low\n"
    "asset_press_4,Press 4,Maintenance,Line 2,high\n"
    "asset_press_5,Press 5,Quality,Line 3,low\n"
)


class ScriptedLiveSyncRuntime:
    adapter_name = "axis-scripted-live-sync-runtime"

    def __init__(
        self,
        plan_result: ConnectorLiveSyncPlan,
        batches: list[ConnectorLiveSyncBatchResult],
        on_read_batch=None,
    ) -> None:
        self.plan_result = plan_result
        self.batches = list(batches)
        self.plan_requests: list[ConnectorLiveSyncPlanRequest] = []
        self.batch_requests: list[ConnectorLiveSyncBatchRequest] = []
        self.on_read_batch = on_read_batch

    def plan(self, request: ConnectorLiveSyncPlanRequest) -> ConnectorLiveSyncPlan:
        self.plan_requests.append(request)
        return self.plan_result

    def read_batch(
        self,
        request: ConnectorLiveSyncBatchRequest,
    ) -> ConnectorLiveSyncBatchResult:
        self.batch_requests.append(request)
        if self.on_read_batch is not None:
            self.on_read_batch(request)
        return self.batches.pop(0)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    seed_connector_registry_reference(factory)
    yield factory
    engine.dispose()


def connector_registry_payload() -> dict:
    migration = run_path("migrations/versions/0023_connector_registry_reference.py")
    return deepcopy(migration["CONNECTOR_REGISTRY_PAYLOAD"])


def live_capable_registry_payload(connector_id: str) -> dict:
    payload = connector_registry_payload()
    connector = next(
        item
        for item in payload["connectors"]
        if item["manifest"]["connector_id"] == connector_id
    )
    connector["manifest"]["sync_modes"] = [
        *connector["manifest"]["sync_modes"],
        "live_sync",
    ]
    connector["runtime_policy"]["allowed_operations"] = [
        *connector["runtime_policy"]["allowed_operations"],
        "live_query",
        "external_egress",
    ]
    connector["runtime_policy"]["blocked_operations"] = [
        "live_write",
        "credential_capture",
    ]
    connector["runtime_policy"]["egress_policy"] = "approved-live-sync-boundary"
    return payload


def seed_connector_registry_reference(
    factory: sessionmaker[Session],
    payload: dict | None = None,
) -> None:
    registry_payload = deepcopy(payload or connector_registry_payload())
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=TENANT_ID,
                surface="connectors",
                reference_id="manufacturing-connector-registry",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=registry_payload,
            )
        )


def seed_manifest(
    repository: AxisPersistenceRepository,
    connector_id: str,
    payload: dict,
    *,
    target_status: str = "active_live",
) -> None:
    connector = next(
        item
        for item in payload["connectors"]
        if item["manifest"]["connector_id"] == connector_id
    )
    record_demo_connector_manifest(
        repository,
        ConnectorManifestCreateRequest(
            tenant_id=TENANT_ID,
            registered_by="platform-connector-owner-role",
            manifest=connector["manifest"],
            runtime_policy=connector["runtime_policy"],
            preview_sample=connector["preview_sample"],
            notes=["Manifest registered for live sync tests."],
        ),
    )
    transition_demo_connector_manifest_lifecycle(
        repository,
        connector_id,
        ConnectorManifestLifecycleRequest(
            tenant_id=TENANT_ID,
            transitioned_by="platform-connector-owner-role",
            target_status="active_preview",
            actor_scopes=["connectors:manifest:lifecycle"],
            transition_reason="Validated for live sync tests.",
            evidence_refs=["approval:connector-live-sync-preview"],
        ),
    )
    if target_status != "active_live":
        return
    transition_demo_connector_manifest_lifecycle(
        repository,
        connector_id,
        ConnectorManifestLifecycleRequest(
            tenant_id=TENANT_ID,
            transitioned_by="platform-connector-owner-role",
            target_status="active_live",
            actor_scopes=[
                "connectors:manifest:lifecycle",
                "connectors:manifest:enable_live",
            ],
            transition_reason="Governed live sync execution gate for tests.",
            evidence_refs=[
                "approval:connector-live-sync-enable",
                "policy:live-sync-boundary-reviewed",
                "credential:live-sync-readonly-lease-policy",
            ],
        ),
    )


def seed_credentials(
    repository: AxisPersistenceRepository,
    *,
    connector_id: str,
    handle_id: str,
    lease_id: str,
) -> None:
    now = utc_now()
    repository.create_connector_credential_handle(
        ConnectorCredentialHandleCreate(
            tenant_id=TENANT_ID,
            connector_id=connector_id,
            handle_id=handle_id,
            display_name="Read-only live sync handle",
            status="active",
            secret_provider="vault-dev",
            secret_ref=f"vault://axis/demo/{handle_id}",
            purpose="read_only_connector_execution",
            rotation_interval_days=30,
            last_rotated_at=now,
            next_rotation_due_at=now,
            created_by="security-owner-role",
            labels={"environment": "demo"},
            notes=["Metadata-only credential handle."],
        )
    )
    repository.create_connector_credential_lease(
        ConnectorCredentialLeaseCreate(
            tenant_id=TENANT_ID,
            connector_id=connector_id,
            handle_id=handle_id,
            lease_id=lease_id,
            status="active",
            lease_mode="self_hosted_vault_kms_lease",
            runtime_boundary="axis-credential-lease-broker",
            requested_by="axis-connector-runtime-role",
            lease_purpose="scheduled_connector_sync",
            secret_provider="vault-dev",
            secret_ref=f"vault://axis/demo/{handle_id}",
            vault_kms_policy={"ttl_seconds": "900", "max_ttl_seconds": "1800"},
            permission_decision={
                "allowed": True,
                "reason": "all_required_scopes_present",
            },
            lease_result={
                "adapter": "axis-self-hosted-vault-kms-lease-adapter",
                "status": "lease_executed",
                "provider_lease_ref": (
                    f"self-hosted-vault-kms://{TENANT_ID}/{lease_id}"
                ),
                "secret_material_returned": "false",
            },
            granted_at=now,
            expires_at=now.replace(year=now.year + 1),
            renewal_due_at=now,
            notes=["Active lease for live sync tests."],
        )
    )


def seed_external_db_egress_policy(repository: AxisPersistenceRepository) -> None:
    approved_endpoint_target_sha256 = postgres_endpoint_target_sha256(APPROVED_DSN)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=TENANT_ID,
            actor_id="network-policy-owner-role",
            event_type="connector.egress_policy.registered",
            payload={
                "connector_id": EXTERNAL_DB_CONNECTOR_ID,
                "policy_id": "egress_policy_private_endpoint_ops",
                "connection_profile_id": "profile_postgres_ops_readonly",
                "egress_boundary": "approved_private_endpoint",
                "private_endpoint_ref": PRIVATE_ENDPOINT_REF,
                "approved_endpoint_target_sha256": approved_endpoint_target_sha256,
            },
        )
    )
    repository.create_connector_egress_policy(
        ConnectorEgressPolicyCreate(
            tenant_id=TENANT_ID,
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
            policy_id="egress_policy_private_endpoint_ops",
            display_name="Operations Postgres private endpoint policy",
            status="active",
            connection_profile_id="profile_postgres_ops_readonly",
            egress_boundary="approved_private_endpoint",
            policy_mode="approved_private_endpoint",
            runtime_boundary="axis-egress-policy-enforcer",
            private_endpoint_ref=PRIVATE_ENDPOINT_REF,
            created_by="network-policy-owner-role",
            policy_document={
                "approved_endpoint_target_sha256": approved_endpoint_target_sha256,
                "transport": "private_endpoint",
                "live_query_mode": "read_only_snapshot",
            },
            evidence_refs=[str(audit_event.id)],
            audit_event_id=audit_event.id,
            notes=["Persisted egress policy for external DB live sync tests."],
        )
    )


def create_dispatched_live_sync_run(
    repository: AxisPersistenceRepository,
    *,
    run_id: str,
    connector_id: str = FILE_CSV_CONNECTOR_ID,
    handle_id: str = "cred_file_csv_readonly",
    lease_id: str = FILE_CSV_LEASE_ID,
    input_summary: dict[str, str],
) -> None:
    record_demo_connector_run(
        repository,
        ConnectorRunCreateRequest(
            tenant_id=TENANT_ID,
            connector_id=connector_id,
            run_id=run_id,
            execution_mode="scheduled_sync_plan",
            requested_by="plant-operations-owner-role",
            credential_handle_ids=[handle_id],
            credential_lease_id=lease_id,
            schedule_id="schedule_live_sync_hourly",
            schedule_cadence="hourly",
            schedule_timezone="Europe/Rome",
            next_run_at=datetime(2026, 6, 22, 14, 0),
            input_summary=input_summary,
        ),
    )
    dispatch_demo_connector_sync(
        repository,
        run_id,
        ConnectorRunDispatchRequest(
            tenant_id=TENANT_ID,
            dispatch_id=f"dispatch_{run_id}",
            dispatched_by="axis-scheduler-role",
            actor_scopes=["connectors:sync:dispatch"],
            credential_lease_id=lease_id,
            idempotency_key=f"idem_dispatch_{run_id}",
        ),
    )


def sync_execution_request(
    *,
    execution_id: str,
    idempotency_key: str,
    lease_id: str = FILE_CSV_LEASE_ID,
    checkpoint_claim_id: str | None = None,
    executed_by: str = "axis-sync-worker-role",
    tenant_id: str = TENANT_ID,
) -> ConnectorRunSyncExecutionRequest:
    return ConnectorRunSyncExecutionRequest(
        tenant_id=tenant_id,
        execution_id=execution_id,
        executed_by=executed_by,
        actor_scopes=["connectors:sync:execute"],
        credential_lease_id=lease_id,
        checkpoint_claim_id=checkpoint_claim_id,
        idempotency_key=idempotency_key,
    )


def file_csv_live_sync_input_summary(file_name: str = "dropzone-assets.csv") -> dict[str, str]:
    return {
        "live_sync_requested": "true",
        "source_file_name": file_name,
    }


def file_csv_field_mappings() -> list[ConnectorLiveSyncFieldMapping]:
    return [
        ConnectorLiveSyncFieldMapping(
            source_column="asset_id",
            target_field="node_id",
            ontology_target="manufacturing_asset",
        ),
        ConnectorLiveSyncFieldMapping(
            source_column="asset_name",
            target_field="display_name",
            ontology_target="manufacturing_asset",
        ),
        ConnectorLiveSyncFieldMapping(
            source_column="risk_level",
            target_field="risk_level",
            ontology_target="manufacturing_asset",
        ),
    ]


def scripted_plan(
    *,
    source_mode: str = "file_csv_live_sync",
    source_ref: str = "scripted-assets.csv",
    batch_size: int = 2,
    max_records: int = 10,
    external_query_required: bool = False,
) -> ConnectorLiveSyncPlan:
    return ConnectorLiveSyncPlan(
        adapter=ScriptedLiveSyncRuntime.adapter_name,
        status=LIVE_SYNC_PLAN_READY_STATUS,
        source_mode=source_mode,
        source_ref=source_ref,
        batch_size=batch_size,
        max_records=max_records,
        external_query_required=external_query_required,
    )


def scripted_record(index: int) -> ConnectorLiveSyncRecord:
    return ConnectorLiveSyncRecord(
        node_id=f"asset_live_{index}",
        node_type="asset",
        ontology_type="manufacturing_asset",
        field_summary={
            "asset_name": f"Asset {index}",
            "domain": "Operations",
            "station": f"Line {index}",
            "risk_level": "low",
        },
    )


def scripted_batch(
    *,
    records: list[ConnectorLiveSyncRecord],
    next_offset: int,
    source_exhausted: bool,
) -> ConnectorLiveSyncBatchResult:
    return ConnectorLiveSyncBatchResult(
        adapter=ScriptedLiveSyncRuntime.adapter_name,
        status=LIVE_SYNC_BATCH_READ_STATUS,
        records=records,
        next_offset=next_offset,
        source_exhausted=source_exhausted,
    )


def failed_scripted_batch(error_code: str) -> ConnectorLiveSyncBatchResult:
    return ConnectorLiveSyncBatchResult(
        adapter=ScriptedLiveSyncRuntime.adapter_name,
        status=LIVE_SYNC_BATCH_FAILED_STATUS,
        error_code=error_code,
    )


def file_csv_live_sync_runtime(tmp_path: Path) -> SelfHostedConnectorLiveSyncRuntime:
    return SelfHostedConnectorLiveSyncRuntime(
        file_csv_profile=FileCsvLiveSyncProfile(
            profile_id="profile_file_csv_local_dropzone",
            source_root=str(tmp_path),
            max_rows=10,
            batch_size=2,
        ),
    )


def external_postgres_live_sync_runtime(
    *,
    enabled: bool = True,
    batch_size: int = 2,
) -> SelfHostedConnectorLiveSyncRuntime:
    return SelfHostedConnectorLiveSyncRuntime(
        external_db_live_sync_enabled=enabled,
        external_postgres_profile=ExternalPostgresLiveQueryProfile(
            profile_id="profile_postgres_ops_readonly",
            dsn=APPROVED_DSN,
            schema_name="operations",
            table_name="production_orders",
            allowed_columns=["order_id", "asset_id", "work_center", "status", "risk_level"],
            private_endpoint_ref=PRIVATE_ENDPOINT_REF,
            endpoint_target_sha256=postgres_endpoint_target_sha256(APPROVED_DSN),
            row_limit=10,
        ),
        external_db_batch_size=batch_size,
    )


def external_db_live_sync_plan_request(
    *,
    endpoint_target_sha256: str,
    credential_access_mode: str = "lease_scoped_secret_ref",
    selected_columns: str = "order_id,asset_id,work_center,status,risk_level",
) -> ConnectorLiveSyncPlanRequest:
    return ConnectorLiveSyncPlanRequest(
        tenant_id=TENANT_ID,
        connector_id=EXTERNAL_DB_CONNECTOR_ID,
        run_id="run_external_db_live_sync",
        execution_id="sync_exec_external_db_live_sync",
        executed_by="axis-sync-worker-role",
        credential_lease_id=EXTERNAL_DB_LEASE_ID,
        credential_lease_result={
            "status": "lease_executed",
            "provider_lease_ref": (
                f"self-hosted-vault-kms://{TENANT_ID}/{EXTERNAL_DB_LEASE_ID}"
            ),
            "secret_material_returned": "false",
        },
        egress_policy_evidence={
            "egress_policy_evidence_status": "validated",
            "egress_policy_result_status": "egress_policy_approved",
            "egress_policy_mode": "approved_private_endpoint",
            "egress_policy_private_endpoint_ref": PRIVATE_ENDPOINT_REF,
            "egress_policy_endpoint_target_sha256": endpoint_target_sha256,
        },
        field_mappings=[
            ConnectorLiveSyncFieldMapping(
                source_column="order_id",
                target_field="node_id",
                ontology_target="production_order",
            ),
        ],
        input_summary={
            "live_sync_requested": "true",
            "connection_profile_id": "profile_postgres_ops_readonly",
            "schema_name": "operations",
            "table_name": "production_orders",
            "selected_columns": selected_columns,
            "query_mode": "read_only_snapshot",
            "egress_policy_id": "egress_policy_private_endpoint_ops",
            "egress_boundary": "approved_private_endpoint",
            "credential_access_mode": credential_access_mode,
        },
    )


def test_file_csv_live_sync_runtime_reads_batches_from_dropzone(tmp_path: Path) -> None:
    (tmp_path / "dropzone-assets.csv").write_text(DROPZONE_CSV_CONTENT)
    runtime = file_csv_live_sync_runtime(tmp_path)
    plan = runtime.plan(
        ConnectorLiveSyncPlanRequest(
            tenant_id=TENANT_ID,
            connector_id=FILE_CSV_CONNECTOR_ID,
            run_id="run_file_csv_live_sync",
            execution_id="sync_exec_file_csv_live_sync",
            executed_by="axis-sync-worker-role",
            credential_lease_id=FILE_CSV_LEASE_ID,
            field_mappings=file_csv_field_mappings(),
            input_summary=file_csv_live_sync_input_summary(),
        )
    )

    assert plan.status == LIVE_SYNC_PLAN_READY_STATUS
    assert plan.source_mode == "file_csv_live_sync"
    assert plan.external_query_required is False
    assert plan.batch_size == 2

    first_batch = runtime.read_batch(
        ConnectorLiveSyncBatchRequest(
            tenant_id=TENANT_ID,
            connector_id=FILE_CSV_CONNECTOR_ID,
            run_id="run_file_csv_live_sync",
            execution_id="sync_exec_file_csv_live_sync",
            offset=0,
            batch_size=2,
            field_mappings=file_csv_field_mappings(),
            input_summary=file_csv_live_sync_input_summary(),
        )
    )
    last_batch = runtime.read_batch(
        ConnectorLiveSyncBatchRequest(
            tenant_id=TENANT_ID,
            connector_id=FILE_CSV_CONNECTOR_ID,
            run_id="run_file_csv_live_sync",
            execution_id="sync_exec_file_csv_live_sync",
            offset=4,
            batch_size=2,
            field_mappings=file_csv_field_mappings(),
            input_summary=file_csv_live_sync_input_summary(),
        )
    )

    assert first_batch.status == LIVE_SYNC_BATCH_READ_STATUS
    assert [record.node_id for record in first_batch.records] == [
        "asset_press_1",
        "asset_press_2",
    ]
    assert first_batch.records[0].node_type == "asset"
    assert first_batch.records[0].ontology_type == "manufacturing_asset"
    assert first_batch.records[0].field_summary == {
        "asset_name": "Press 1",
        "risk_level": "low",
    }
    assert first_batch.next_offset == 2
    assert first_batch.source_exhausted is False
    assert last_batch.next_offset == 5
    assert last_batch.source_exhausted is True


def test_file_csv_live_sync_plan_blocks_traversal_file_reference(tmp_path: Path) -> None:
    runtime = file_csv_live_sync_runtime(tmp_path)

    plan = runtime.plan(
        ConnectorLiveSyncPlanRequest(
            tenant_id=TENANT_ID,
            connector_id=FILE_CSV_CONNECTOR_ID,
            run_id="run_file_csv_live_sync",
            execution_id="sync_exec_file_csv_live_sync",
            executed_by="axis-sync-worker-role",
            credential_lease_id=FILE_CSV_LEASE_ID,
            field_mappings=file_csv_field_mappings(),
            input_summary=file_csv_live_sync_input_summary("../outside.csv"),
        )
    )

    assert plan.status == LIVE_SYNC_PLAN_BLOCKED_STATUS
    assert plan.block_reason == "source_file_ref_invalid"


def test_file_csv_live_sync_plan_fails_unavailable_source_file(tmp_path: Path) -> None:
    runtime = file_csv_live_sync_runtime(tmp_path)

    plan = runtime.plan(
        ConnectorLiveSyncPlanRequest(
            tenant_id=TENANT_ID,
            connector_id=FILE_CSV_CONNECTOR_ID,
            run_id="run_file_csv_live_sync",
            execution_id="sync_exec_file_csv_live_sync",
            executed_by="axis-sync-worker-role",
            credential_lease_id=FILE_CSV_LEASE_ID,
            field_mappings=file_csv_field_mappings(),
            input_summary=file_csv_live_sync_input_summary("missing.csv"),
        )
    )

    assert plan.status == LIVE_SYNC_PLAN_FAILED_STATUS
    assert plan.error_code == "connector_unavailable"


def test_file_csv_live_sync_batch_fails_on_schema_mismatch(tmp_path: Path) -> None:
    (tmp_path / "dropzone-assets.csv").write_text("order_id,status\npo-1,open\n")
    runtime = file_csv_live_sync_runtime(tmp_path)

    batch = runtime.read_batch(
        ConnectorLiveSyncBatchRequest(
            tenant_id=TENANT_ID,
            connector_id=FILE_CSV_CONNECTOR_ID,
            run_id="run_file_csv_live_sync",
            execution_id="sync_exec_file_csv_live_sync",
            offset=0,
            batch_size=2,
            field_mappings=file_csv_field_mappings(),
            input_summary=file_csv_live_sync_input_summary(),
        )
    )

    assert batch.status == LIVE_SYNC_BATCH_FAILED_STATUS
    assert batch.error_code == "source_schema_mismatch"


def test_external_db_live_sync_plan_blocks_when_execution_disabled() -> None:
    runtime = external_postgres_live_sync_runtime(enabled=False)

    plan = runtime.plan(
        external_db_live_sync_plan_request(
            endpoint_target_sha256=postgres_endpoint_target_sha256(APPROVED_DSN),
        )
    )

    assert plan.status == LIVE_SYNC_PLAN_BLOCKED_STATUS
    assert plan.block_reason == "live_sync_execution_disabled"


def test_external_db_live_sync_plan_blocks_endpoint_target_mismatch() -> None:
    runtime = external_postgres_live_sync_runtime()

    plan = runtime.plan(
        external_db_live_sync_plan_request(
            endpoint_target_sha256=postgres_endpoint_target_sha256(UNAPPROVED_DSN),
        )
    )

    assert plan.status == LIVE_SYNC_PLAN_BLOCKED_STATUS
    assert plan.block_reason == "endpoint_target_mismatch"
    assert "dsn" not in str(plan.model_dump(mode="json")).lower()


def test_external_db_live_sync_plan_blocks_unallowlisted_columns() -> None:
    runtime = external_postgres_live_sync_runtime()

    plan = runtime.plan(
        external_db_live_sync_plan_request(
            endpoint_target_sha256=postgres_endpoint_target_sha256(APPROVED_DSN),
            selected_columns="order_id,internal_notes",
        )
    )

    assert plan.status == LIVE_SYNC_PLAN_BLOCKED_STATUS
    assert plan.block_reason == "selected_columns_not_allowlisted"


def test_external_db_live_sync_plan_blocks_unsupported_credential_access_mode() -> None:
    runtime = external_postgres_live_sync_runtime()

    plan = runtime.plan(
        external_db_live_sync_plan_request(
            endpoint_target_sha256=postgres_endpoint_target_sha256(APPROVED_DSN),
            credential_access_mode="raw_secret_value",
        )
    )

    assert plan.status == LIVE_SYNC_PLAN_BLOCKED_STATUS
    assert plan.block_reason == "unsupported_credential_access_mode"


def test_external_db_live_sync_plan_ready_uses_bounded_batches() -> None:
    runtime = external_postgres_live_sync_runtime(batch_size=100)

    plan = runtime.plan(
        external_db_live_sync_plan_request(
            endpoint_target_sha256=postgres_endpoint_target_sha256(APPROVED_DSN),
        )
    )

    assert plan.status == LIVE_SYNC_PLAN_READY_STATUS
    assert plan.source_mode == "external_db_live_sync"
    assert plan.source_ref == "operations.production_orders"
    assert plan.external_query_required is True
    assert plan.batch_size == 10
    assert plan.max_records == 10


def test_live_sync_public_safety_rejects_row_payload_fields() -> None:
    summary = {
        "runtime_status": "sync_execution_completed",
        "external_query_started": "true",
        "credential_material_returned": "false",
        "graph_mutation_started": "false",
        "source_mode": "external_db_live_sync",
        "live_sync_execution_status": "completed",
        "rows": [{"order_id": "po-1001"}],
    }

    assert _sync_checkpoint_result_is_public_safe(summary) is False


def test_live_sync_public_safety_allows_completed_external_db_summary() -> None:
    summary = {
        "runtime_status": "sync_execution_completed",
        "connector_id": EXTERNAL_DB_CONNECTOR_ID,
        "schedule_id": "schedule_live_sync_hourly",
        "dispatch_id": "dispatch_run",
        "execution_id": "sync_exec_run",
        "live_sync_requested": "true",
        "live_sync_execution_status": "completed",
        "records_read": "3",
        "records_accepted": "3",
        "records_rejected": "0",
        "sync_batches_committed": "2",
        "resume_offset": "0",
        "next_offset": "3",
        "proposals_recorded": "3",
        "proposal_write_mode": "proposal_only",
        "external_sync_started": "true",
        "external_query_started": "true",
        "credential_material_returned": "false",
        "graph_mutation_started": "false",
        "source_mode": "external_db_live_sync",
        "source_ref": "operations.production_orders",
    }

    assert _sync_checkpoint_result_is_public_safe(summary) is True


def test_execute_live_sync_completes_with_batches_proposals_and_stage_audit(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    runtime = ScriptedLiveSyncRuntime(
        scripted_plan(),
        [
            scripted_batch(
                records=[scripted_record(0), scripted_record(1)],
                next_offset=2,
                source_exhausted=False,
            ),
            scripted_batch(
                records=[scripted_record(2)],
                next_offset=3,
                source_exhausted=True,
            ),
        ],
    )

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, FILE_CSV_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_file_csv_live_sync_happy",
            input_summary=file_csv_live_sync_input_summary(),
        )

        run = execute_demo_connector_sync(
            repository,
            "run_file_csv_live_sync_happy",
            sync_execution_request(
                execution_id="sync_exec_live_happy",
                idempotency_key="idem_sync_exec_live_happy",
            ),
            live_sync_runtime=runtime,
        )

        checkpoints = repository.list_connector_sync_checkpoints(
            TENANT_ID,
            run_id="run_file_csv_live_sync_happy",
        )
        proposals = repository.list_connector_ontology_proposals(
            tenant_id=TENANT_ID,
            connector_id=FILE_CSV_CONNECTOR_ID,
        )
        started_events = repository.list_audit_events(
            TENANT_ID,
            event_type="connector.run.sync_execution_started",
        )
        batch_events = repository.list_audit_events(
            TENANT_ID,
            event_type="connector.run.sync_batch_committed",
        )
        completed_events = repository.list_audit_events(
            TENANT_ID,
            event_type="connector.run.sync_execution_completed",
        )
        proposal_events = repository.list_audit_events(
            TENANT_ID,
            event_type="connector.ontology_proposals.recorded",
        )

    assert run.status == "sync_execution_completed"
    assert run.audit_event_type == "connector.run.sync_execution_completed"
    summary = run.sync_execution_result.result_summary
    assert summary["records_read"] == "3"
    assert summary["records_accepted"] == "3"
    assert summary["sync_batches_committed"] == "2"
    assert summary["proposals_recorded"] == "3"
    assert summary["resume_offset"] == "0"
    assert summary["next_offset"] == "3"
    assert summary["live_sync_execution_status"] == "completed"
    assert summary["source_mode"] == "file_csv_live_sync"
    assert summary["external_query_started"] == "false"
    assert summary["credential_material_returned"] == "false"
    assert summary["graph_mutation_started"] == "false"
    assert run.sync_execution_result.external_sync_started is False

    batch_checkpoints = [
        checkpoint
        for checkpoint in checkpoints
        if checkpoint.checkpoint_type == "sync_batch"
    ]
    assert [checkpoint.checkpoint_id for checkpoint in batch_checkpoints] == [
        "chk_run_file_csv_live_sync_happy_batch_1",
        "chk_run_file_csv_live_sync_happy_batch_2",
    ]
    assert all(
        checkpoint.status == "sync_batch_committed" for checkpoint in batch_checkpoints
    )
    assert batch_checkpoints[0].cursor["next_offset"] == "2"
    assert batch_checkpoints[1].cursor["next_offset"] == "3"
    terminal_checkpoints = [
        checkpoint
        for checkpoint in checkpoints
        if checkpoint.checkpoint_type == "sync_execution"
    ]
    assert len(terminal_checkpoints) == 1
    assert terminal_checkpoints[0].status == "sync_execution_completed"

    assert len(started_events) == 1
    assert started_events[0].payload["resume_offset"] == "0"
    assert len(batch_events) == 2
    assert len(completed_events) == 1
    assert len(proposal_events) == 2

    assert sorted(proposal.proposal_id for proposal in proposals) == [
        "prop_run_file_csv_live_sync_happy_r0",
        "prop_run_file_csv_live_sync_happy_r1",
        "prop_run_file_csv_live_sync_happy_r2",
    ]
    assert all(proposal.status == "proposed_from_preview" for proposal in proposals)
    assert all(
        proposal.graph_mutation_status == "not_applied" for proposal in proposals
    )
    assert all(proposal.write_mode == "proposal_only" for proposal in proposals)
    assert all(
        proposal.source_run_id == "run_file_csv_live_sync_happy"
        for proposal in proposals
    )
    first_proposal = next(
        proposal
        for proposal in proposals
        if proposal.proposal_id == "prop_run_file_csv_live_sync_happy_r0"
    )
    assert first_proposal.field_summary["asset_name"] == "Asset 0"
    # Row payloads live only in review-only proposals, never in run/checkpoint evidence.
    assert "Asset 0" not in str(summary)
    assert "Asset 0" not in str(batch_checkpoints[0].result_summary)
    assert "Asset 0" not in str(batch_checkpoints[0].cursor)


def test_execute_live_sync_caps_rows_at_tenant_quota(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    runtime = ScriptedLiveSyncRuntime(
        scripted_plan(batch_size=2, max_records=10),
        [
            scripted_batch(
                records=[scripted_record(0), scripted_record(1)],
                next_offset=2,
                source_exhausted=False,
            ),
            scripted_batch(
                records=[scripted_record(2)],
                next_offset=3,
                source_exhausted=False,
            ),
        ],
    )

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.upsert_tenant_quota(
            TenantQuotaUpsert(
                tenant_id=TENANT_ID,
                quota_key=TenantQuotaKey.MAX_CONNECTOR_SYNC_ROWS_PER_RUN.value,
                quota_value=3,
                updated_by="axis-platform-operator-role",
            )
        )
        seed_manifest(repository, FILE_CSV_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_file_csv_live_sync_quota_cap",
            input_summary=file_csv_live_sync_input_summary(),
        )

        run = execute_demo_connector_sync(
            repository,
            "run_file_csv_live_sync_quota_cap",
            sync_execution_request(
                execution_id="sync_exec_live_quota_cap",
                idempotency_key="idem_sync_exec_live_quota_cap",
            ),
            live_sync_runtime=runtime,
        )

        started_events = repository.list_audit_events(
            TENANT_ID,
            event_type="connector.run.sync_execution_started",
        )

    assert run.status == "sync_execution_completed"
    summary = run.sync_execution_result.result_summary
    assert summary["records_read"] == "3"
    assert summary["sync_batches_committed"] == "2"
    assert summary["next_offset"] == "3"
    # The quota (3) caps the plan row limit (10) and bounds every batch read.
    assert started_events[0].payload["max_records"] == "3"
    assert [request.batch_size for request in runtime.batch_requests] == [2, 1]
    assert all(request.batch_size <= 3 for request in runtime.batch_requests)


def test_execute_live_sync_ignores_tenant_row_quota_at_or_above_plan_limit(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    runtime = ScriptedLiveSyncRuntime(
        scripted_plan(batch_size=2, max_records=10),
        [
            scripted_batch(
                records=[scripted_record(0), scripted_record(1)],
                next_offset=2,
                source_exhausted=True,
            ),
        ],
    )

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.upsert_tenant_quota(
            TenantQuotaUpsert(
                tenant_id=TENANT_ID,
                quota_key=TenantQuotaKey.MAX_CONNECTOR_SYNC_ROWS_PER_RUN.value,
                quota_value=500,
                updated_by="axis-platform-operator-role",
            )
        )
        seed_manifest(repository, FILE_CSV_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_file_csv_live_sync_quota_high",
            input_summary=file_csv_live_sync_input_summary(),
        )

        run = execute_demo_connector_sync(
            repository,
            "run_file_csv_live_sync_quota_high",
            sync_execution_request(
                execution_id="sync_exec_live_quota_high",
                idempotency_key="idem_sync_exec_live_quota_high",
            ),
            live_sync_runtime=runtime,
        )

        started_events = repository.list_audit_events(
            TENANT_ID,
            event_type="connector.run.sync_execution_started",
        )

    assert run.status == "sync_execution_completed"
    # A quota at or above the plan row limit leaves the profile bound in place.
    assert started_events[0].payload["max_records"] == "10"
    assert [request.batch_size for request in runtime.batch_requests] == [2]


def test_execute_live_sync_requires_active_live_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    runtime = ScriptedLiveSyncRuntime(scripted_plan(), [])

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(
            repository,
            FILE_CSV_CONNECTOR_ID,
            payload,
            target_status="active_preview",
        )
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_file_csv_live_sync_gate",
            input_summary=file_csv_live_sync_input_summary(),
        )

        with pytest.raises(ConnectorRunValidationError) as exc_info:
            execute_demo_connector_sync(
                repository,
                "run_file_csv_live_sync_gate",
                sync_execution_request(
                    execution_id="sync_exec_live_gate",
                    idempotency_key="idem_sync_exec_live_gate",
                ),
                live_sync_runtime=runtime,
            )

    assert exc_info.value.reason == "connector_manifest_not_active_live"
    assert runtime.batch_requests == []


def test_execute_live_sync_persists_failed_run_when_source_unavailable(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    runtime = file_csv_live_sync_runtime(tmp_path)

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, FILE_CSV_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_file_csv_live_sync_unavailable",
            input_summary=file_csv_live_sync_input_summary("missing.csv"),
        )

        run = execute_demo_connector_sync(
            repository,
            "run_file_csv_live_sync_unavailable",
            sync_execution_request(
                execution_id="sync_exec_live_unavailable",
                idempotency_key="idem_sync_exec_live_unavailable",
            ),
            live_sync_runtime=runtime,
        )
        failed_events = repository.list_audit_events(
            TENANT_ID,
            event_type="connector.run.sync_execution_failed",
        )
        proposals = repository.list_connector_ontology_proposals(
            tenant_id=TENANT_ID,
            connector_id=FILE_CSV_CONNECTOR_ID,
        )

    assert run.status == "sync_execution_failed"
    assert run.audit_event_type == "connector.run.sync_execution_failed"
    summary = run.sync_execution_result.result_summary
    assert summary["sync_error_code"] == "connector_unavailable"
    assert summary["live_sync_execution_status"] == "failed"
    assert summary["records_read"] == "0"
    assert summary["external_query_started"] == "false"
    assert len(failed_events) == 1
    assert proposals == []


def test_execute_live_sync_fails_closed_on_lease_expiry_mid_run(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, FILE_CSV_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_file_csv_live_sync_lease",
            input_summary=file_csv_live_sync_input_summary(),
        )

        def expire_lease(_request: ConnectorLiveSyncBatchRequest) -> None:
            lease = repository.get_connector_credential_lease(
                TENANT_ID,
                FILE_CSV_LEASE_ID,
            )
            lease.expires_at = utc_now() - timedelta(minutes=1)

        runtime = ScriptedLiveSyncRuntime(
            scripted_plan(),
            [
                scripted_batch(
                    records=[scripted_record(0), scripted_record(1)],
                    next_offset=2,
                    source_exhausted=False,
                ),
            ],
            on_read_batch=expire_lease,
        )

        run = execute_demo_connector_sync(
            repository,
            "run_file_csv_live_sync_lease",
            sync_execution_request(
                execution_id="sync_exec_live_lease",
                idempotency_key="idem_sync_exec_live_lease",
            ),
            live_sync_runtime=runtime,
        )
        checkpoints = repository.list_connector_sync_checkpoints(
            TENANT_ID,
            run_id="run_file_csv_live_sync_lease",
            status="sync_batch_committed",
        )

    assert run.status == "sync_execution_failed"
    summary = run.sync_execution_result.result_summary
    assert summary["sync_error_code"] == "credential_lease_expired_mid_run"
    assert summary["sync_batches_committed"] == "1"
    assert summary["records_read"] == "2"
    assert len(checkpoints) == 1
    assert checkpoints[0].cursor["next_offset"] == "2"
    assert len(runtime.batch_requests) == 1


def test_execute_live_sync_resumes_from_last_committed_checkpoint(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    first_runtime = ScriptedLiveSyncRuntime(
        scripted_plan(),
        [
            scripted_batch(
                records=[scripted_record(0), scripted_record(1)],
                next_offset=2,
                source_exhausted=False,
            ),
            failed_scripted_batch("connector_unavailable"),
        ],
    )
    resume_runtime = ScriptedLiveSyncRuntime(
        scripted_plan(),
        [
            scripted_batch(
                records=[scripted_record(2)],
                next_offset=3,
                source_exhausted=True,
            ),
        ],
    )

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, FILE_CSV_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_file_csv_live_sync_resume",
            input_summary=file_csv_live_sync_input_summary(),
        )

        failed_run = execute_demo_connector_sync(
            repository,
            "run_file_csv_live_sync_resume",
            sync_execution_request(
                execution_id="sync_exec_live_resume_1",
                idempotency_key="idem_sync_exec_live_resume_1",
            ),
            live_sync_runtime=first_runtime,
        )
        assert failed_run.status == "sync_execution_failed"

        claim, created = claim_connector_sync_checkpoint(
            repository,
            "chk_run_file_csv_live_sync_resume_batch_1",
            ConnectorSyncCheckpointClaimRequest(
                tenant_id=TENANT_ID,
                claim_id="claim_live_sync_resume",
                claimed_by="axis-sync-worker-role",
                actor_scopes=["connectors:sync:checkpoint:claim"],
                idempotency_key="idem_claim_live_sync_resume",
            ),
        )
        assert created is True

        resumed_run = execute_demo_connector_sync(
            repository,
            "run_file_csv_live_sync_resume",
            sync_execution_request(
                execution_id="sync_exec_live_resume_2",
                idempotency_key="idem_sync_exec_live_resume_2",
                checkpoint_claim_id=claim.claim_id,
            ),
            live_sync_runtime=resume_runtime,
        )
        proposals = repository.list_connector_ontology_proposals(
            tenant_id=TENANT_ID,
            connector_id=FILE_CSV_CONNECTOR_ID,
        )

    assert resume_runtime.batch_requests[0].offset == 2
    assert resumed_run.status == "sync_execution_completed"
    summary = resumed_run.sync_execution_result.result_summary
    assert summary["resume_offset"] == "2"
    assert summary["next_offset"] == "3"
    assert summary["records_read"] == "3"
    assert summary["sync_batches_committed"] == "2"
    assert summary["proposals_recorded"] == "3"
    assert summary["checkpoint_claim_id"] == "claim_live_sync_resume"
    assert summary["checkpoint_claim_checkpoint_id"] == (
        "chk_run_file_csv_live_sync_resume_batch_1"
    )
    assert sorted(proposal.proposal_id for proposal in proposals) == [
        "prop_run_file_csv_live_sync_resume_r0",
        "prop_run_file_csv_live_sync_resume_r1",
        "prop_run_file_csv_live_sync_resume_r2",
    ]


def test_execute_live_sync_resume_requires_checkpoint_claim(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    first_runtime = ScriptedLiveSyncRuntime(
        scripted_plan(),
        [
            scripted_batch(
                records=[scripted_record(0)],
                next_offset=1,
                source_exhausted=False,
            ),
            failed_scripted_batch("connector_unavailable"),
        ],
    )
    resume_runtime = ScriptedLiveSyncRuntime(scripted_plan(), [])

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, FILE_CSV_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_file_csv_live_sync_claimless",
            input_summary=file_csv_live_sync_input_summary(),
        )
        execute_demo_connector_sync(
            repository,
            "run_file_csv_live_sync_claimless",
            sync_execution_request(
                execution_id="sync_exec_live_claimless_1",
                idempotency_key="idem_sync_exec_live_claimless_1",
            ),
            live_sync_runtime=first_runtime,
        )

        with pytest.raises(ConnectorRunValidationError) as exc_info:
            execute_demo_connector_sync(
                repository,
                "run_file_csv_live_sync_claimless",
                sync_execution_request(
                    execution_id="sync_exec_live_claimless_2",
                    idempotency_key="idem_sync_exec_live_claimless_2",
                ),
                live_sync_runtime=resume_runtime,
            )

    assert exc_info.value.reason == "checkpoint_claim_id_required_for_live_sync_resume"
    assert resume_runtime.batch_requests == []


def test_execute_live_sync_resume_rejects_other_worker_claim(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    first_runtime = ScriptedLiveSyncRuntime(
        scripted_plan(),
        [
            scripted_batch(
                records=[scripted_record(0)],
                next_offset=1,
                source_exhausted=False,
            ),
            failed_scripted_batch("connector_unavailable"),
        ],
    )
    resume_runtime = ScriptedLiveSyncRuntime(scripted_plan(), [])

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, FILE_CSV_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_file_csv_live_sync_worker",
            input_summary=file_csv_live_sync_input_summary(),
        )
        execute_demo_connector_sync(
            repository,
            "run_file_csv_live_sync_worker",
            sync_execution_request(
                execution_id="sync_exec_live_worker_1",
                idempotency_key="idem_sync_exec_live_worker_1",
            ),
            live_sync_runtime=first_runtime,
        )
        claim, _ = claim_connector_sync_checkpoint(
            repository,
            "chk_run_file_csv_live_sync_worker_batch_1",
            ConnectorSyncCheckpointClaimRequest(
                tenant_id=TENANT_ID,
                claim_id="claim_live_sync_other_worker",
                claimed_by="axis-other-worker-role",
                actor_scopes=["connectors:sync:checkpoint:claim"],
                idempotency_key="idem_claim_live_sync_other_worker",
            ),
        )

        with pytest.raises(ConnectorRunValidationError) as exc_info:
            execute_demo_connector_sync(
                repository,
                "run_file_csv_live_sync_worker",
                sync_execution_request(
                    execution_id="sync_exec_live_worker_2",
                    idempotency_key="idem_sync_exec_live_worker_2",
                    checkpoint_claim_id=claim.claim_id,
                ),
                live_sync_runtime=resume_runtime,
            )

    assert exc_info.value.reason == "live_sync_resume_claim_worker_mismatch"
    assert resume_runtime.batch_requests == []


def test_live_sync_batch_checkpoint_rejects_second_active_worker_claim(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    first_runtime = ScriptedLiveSyncRuntime(
        scripted_plan(),
        [
            scripted_batch(
                records=[scripted_record(0)],
                next_offset=1,
                source_exhausted=False,
            ),
            failed_scripted_batch("connector_unavailable"),
        ],
    )

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, FILE_CSV_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_file_csv_live_sync_conflict",
            input_summary=file_csv_live_sync_input_summary(),
        )
        execute_demo_connector_sync(
            repository,
            "run_file_csv_live_sync_conflict",
            sync_execution_request(
                execution_id="sync_exec_live_conflict_1",
                idempotency_key="idem_sync_exec_live_conflict_1",
            ),
            live_sync_runtime=first_runtime,
        )
        claim_connector_sync_checkpoint(
            repository,
            "chk_run_file_csv_live_sync_conflict_batch_1",
            ConnectorSyncCheckpointClaimRequest(
                tenant_id=TENANT_ID,
                claim_id="claim_live_sync_first_worker",
                claimed_by="axis-sync-worker-role",
                actor_scopes=["connectors:sync:checkpoint:claim"],
                idempotency_key="idem_claim_live_sync_first_worker",
            ),
        )

        with pytest.raises(ConnectorSyncCheckpointClaimConflict) as exc_info:
            claim_connector_sync_checkpoint(
                repository,
                "chk_run_file_csv_live_sync_conflict_batch_1",
                ConnectorSyncCheckpointClaimRequest(
                    tenant_id=TENANT_ID,
                    claim_id="claim_live_sync_second_worker",
                    claimed_by="axis-other-worker-role",
                    actor_scopes=["connectors:sync:checkpoint:claim"],
                    idempotency_key="idem_claim_live_sync_second_worker",
                ),
            )

    assert exc_info.value.reason == "active_checkpoint_claim_exists"
    assert exc_info.value.active_claim_id == "claim_live_sync_first_worker"


def test_execute_live_sync_blocks_external_db_without_egress_policy(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(EXTERNAL_DB_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    runtime = external_postgres_live_sync_runtime()

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, EXTERNAL_DB_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
            handle_id="cred_external_db_readonly",
            lease_id=EXTERNAL_DB_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_external_db_live_sync_blocked",
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
            handle_id="cred_external_db_readonly",
            lease_id=EXTERNAL_DB_LEASE_ID,
            input_summary={
                "live_sync_requested": "true",
                "connection_profile_id": "profile_postgres_ops_readonly",
                "schema_name": "operations",
                "table_name": "production_orders",
                "selected_columns": "order_id,asset_id,work_center,status,risk_level",
                "query_mode": "read_only_snapshot",
                "egress_policy_id": "egress_policy_private_endpoint_ops",
                "egress_boundary": "approved_private_endpoint",
                "credential_access_mode": "lease_scoped_secret_ref",
            },
        )

        run = execute_demo_connector_sync(
            repository,
            "run_external_db_live_sync_blocked",
            sync_execution_request(
                execution_id="sync_exec_external_db_live_sync_blocked",
                idempotency_key="idem_sync_exec_external_db_live_sync_blocked",
                lease_id=EXTERNAL_DB_LEASE_ID,
            ),
            live_sync_runtime=runtime,
        )
        blocked_events = repository.list_audit_events(
            TENANT_ID,
            event_type="connector.run.sync_execution_live_sync_blocked",
        )
        proposals = repository.list_connector_ontology_proposals(
            tenant_id=TENANT_ID,
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
        )

    assert run.status == "sync_execution_live_sync_blocked"
    assert run.audit_event_type == "connector.run.sync_execution_live_sync_blocked"
    summary = run.sync_execution_result.result_summary
    assert summary["live_sync_execution_status"] == "blocked_egress_policy_not_approved"
    assert summary["records_read"] == "0"
    assert summary["external_query_started"] == "false"
    assert len(blocked_events) == 1
    assert proposals == []
    assert "dsn" not in str(run.result_summary).lower()
    assert "postgresql://" not in str(run.result_summary).lower()


def test_execute_live_sync_replays_completed_execution_idempotently(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    runtime = ScriptedLiveSyncRuntime(
        scripted_plan(),
        [
            scripted_batch(
                records=[scripted_record(0)],
                next_offset=1,
                source_exhausted=True,
            ),
        ],
    )

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, FILE_CSV_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_file_csv_live_sync_idem",
            input_summary=file_csv_live_sync_input_summary(),
        )
        execute_demo_connector_sync(
            repository,
            "run_file_csv_live_sync_idem",
            sync_execution_request(
                execution_id="sync_exec_live_idem",
                idempotency_key="idem_sync_exec_live_idem",
            ),
            live_sync_runtime=runtime,
        )

        replayed = execute_demo_connector_sync(
            repository,
            "run_file_csv_live_sync_idem",
            sync_execution_request(
                execution_id="sync_exec_live_idem",
                idempotency_key="idem_sync_exec_live_idem",
            ),
            live_sync_runtime=runtime,
        )
        completed_events = repository.list_audit_events(
            TENANT_ID,
            event_type="connector.run.sync_execution_completed",
        )

        with pytest.raises(ConnectorRunSyncExecutionConflict) as exc_info:
            execute_demo_connector_sync(
                repository,
                "run_file_csv_live_sync_idem",
                sync_execution_request(
                    execution_id="sync_exec_live_idem_other",
                    idempotency_key="idem_sync_exec_live_idem_other",
                ),
                live_sync_runtime=runtime,
            )

    assert replayed.status == "sync_execution_completed"
    assert len(completed_events) == 1
    assert len(runtime.batch_requests) == 1
    assert exc_info.value.reason == "sync_execution_idempotency_conflict"


def test_execute_live_sync_is_tenant_scoped(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    runtime = ScriptedLiveSyncRuntime(scripted_plan(), [])

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, FILE_CSV_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_file_csv_live_sync_tenant",
            input_summary=file_csv_live_sync_input_summary(),
        )

        with pytest.raises(ConnectorRunNotFound):
            execute_demo_connector_sync(
                repository,
                "run_file_csv_live_sync_tenant",
                sync_execution_request(
                    execution_id="sync_exec_live_tenant",
                    idempotency_key="idem_sync_exec_live_tenant",
                    tenant_id="tenant_other",
                ),
                live_sync_runtime=runtime,
            )
        other_tenant_proposals = repository.list_connector_ontology_proposals(
            tenant_id="tenant_other",
            connector_id=FILE_CSV_CONNECTOR_ID,
        )

    assert runtime.plan_requests == []
    assert other_tenant_proposals == []


def build_live_sync_app(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    **settings_overrides,
) -> TestClient:
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            file_csv_live_sync_root=str(tmp_path),
            file_csv_live_sync_batch_size=2,
            file_csv_live_sync_max_rows=10,
            **settings_overrides,
        )
    )
    app.state.session_factory = session_factory
    return TestClient(app)


def seed_live_file_csv_tenant_state(
    session_factory: sessionmaker[Session],
    payload: dict,
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, FILE_CSV_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )


def create_dispatched_live_sync_run_via_api(client: TestClient, run_id: str) -> None:
    create_response = client.post(
        "/demo/manufacturing/connectors/runs",
        json={
            "tenant_id": TENANT_ID,
            "connector_id": FILE_CSV_CONNECTOR_ID,
            "run_id": run_id,
            "execution_mode": "scheduled_sync_plan",
            "requested_by": "plant-operations-owner-role",
            "credential_handle_ids": ["cred_file_csv_readonly"],
            "credential_lease_id": FILE_CSV_LEASE_ID,
            "schedule_id": "schedule_live_sync_hourly",
            "schedule_cadence": "hourly",
            "schedule_timezone": "Europe/Rome",
            "next_run_at": "2026-06-22T14:00:00Z",
            "input_summary": file_csv_live_sync_input_summary(),
            "result_summary": {},
        },
    )
    assert create_response.status_code == 201
    dispatch_response = client.post(
        f"/demo/manufacturing/connectors/runs/{run_id}/dispatch",
        json={
            "tenant_id": TENANT_ID,
            "dispatch_id": f"dispatch_{run_id}",
            "dispatched_by": "axis-scheduler-role",
            "actor_scopes": ["connectors:sync:dispatch"],
            "credential_lease_id": FILE_CSV_LEASE_ID,
            "idempotency_key": f"idem_dispatch_{run_id}",
        },
    )
    assert dispatch_response.status_code == 200


def execute_sync_via_api(client: TestClient, run_id: str, execution_id: str) -> dict:
    response = client.post(
        f"/demo/manufacturing/connectors/runs/{run_id}/execute-sync",
        json={
            "tenant_id": TENANT_ID,
            "execution_id": execution_id,
            "executed_by": "axis-sync-worker-role",
            "actor_scopes": ["connectors:sync:execute"],
            "credential_lease_id": FILE_CSV_LEASE_ID,
            "idempotency_key": f"idem_{execution_id}",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_execute_sync_endpoint_runs_file_csv_live_sync_end_to_end(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    seed_live_file_csv_tenant_state(session_factory, payload)
    (tmp_path / "dropzone-assets.csv").write_text(DROPZONE_CSV_CONTENT)
    client = build_live_sync_app(
        session_factory,
        tmp_path,
        connector_sync_execution_enabled=True,
        connector_live_sync_execution_enabled=True,
    )
    create_dispatched_live_sync_run_via_api(client, "run_file_csv_live_sync_api")

    body = execute_sync_via_api(
        client,
        "run_file_csv_live_sync_api",
        "sync_exec_live_api",
    )

    assert body["status"] == "sync_execution_completed"
    assert body["audit_event_type"] == "connector.run.sync_execution_completed"
    result = body["sync_execution_result"]
    assert result["adapter"] == "axis-file-csv-live-sync-executor"
    assert result["external_sync_started"] is False
    summary = result["result_summary"]
    assert summary["records_read"] == "5"
    assert summary["sync_batches_committed"] == "3"
    assert summary["proposals_recorded"] == "5"
    assert summary["source_mode"] == "file_csv_live_sync"
    assert summary["source_ref"] == "dropzone-assets.csv"
    assert summary["live_sync_execution_status"] == "completed"
    assert summary["graph_mutation_started"] == "false"
    assert "Press 1" not in str(body)
    assert "vault://" not in str(body).lower()

    proposals_response = client.get(
        "/demo/manufacturing/connectors/ontology-proposals",
        params={"tenant_id": TENANT_ID, "connector_id": FILE_CSV_CONNECTOR_ID},
    )
    assert proposals_response.status_code == 200
    proposals = proposals_response.json()["proposals"]
    assert len(proposals) == 5
    assert {proposal["node_id"] for proposal in proposals} == {
        "asset_press_1",
        "asset_press_2",
        "asset_press_3",
        "asset_press_4",
        "asset_press_5",
    }
    assert all(
        proposal["graph_mutation_status"] == "not_applied" for proposal in proposals
    )
    assert proposals[0]["source_run_id"] == "run_file_csv_live_sync_api"

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        batch_checkpoints = repository.list_connector_sync_checkpoints(
            TENANT_ID,
            run_id="run_file_csv_live_sync_api",
            status="sync_batch_committed",
        )
        started_events = repository.list_audit_events(
            TENANT_ID,
            event_type="connector.run.sync_execution_started",
        )

    assert len(batch_checkpoints) == 3
    assert len(started_events) == 1


def test_execute_sync_endpoint_defers_live_sync_when_flags_disabled(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    seed_live_file_csv_tenant_state(session_factory, payload)
    (tmp_path / "dropzone-assets.csv").write_text(DROPZONE_CSV_CONTENT)
    client = build_live_sync_app(session_factory, tmp_path)
    create_dispatched_live_sync_run_via_api(client, "run_file_csv_live_sync_deferred")

    body = execute_sync_via_api(
        client,
        "run_file_csv_live_sync_deferred",
        "sync_exec_live_deferred",
    )

    assert body["status"] == "sync_execution_deferred"
    assert body["sync_execution_result"]["adapter"] == (
        "axis-deferred-connector-sync-executor"
    )
    assert body["sync_execution_result"]["external_sync_started"] is False

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        batch_checkpoints = repository.list_connector_sync_checkpoints(
            TENANT_ID,
            run_id="run_file_csv_live_sync_deferred",
            status="sync_batch_committed",
        )
        proposals = repository.list_connector_ontology_proposals(
            tenant_id=TENANT_ID,
            connector_id=FILE_CSV_CONNECTOR_ID,
        )

    assert batch_checkpoints == []
    assert proposals == []


def test_execute_sync_endpoint_keeps_legacy_path_when_live_sync_flag_off(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    seed_live_file_csv_tenant_state(session_factory, payload)
    (tmp_path / "dropzone-assets.csv").write_text(DROPZONE_CSV_CONTENT)
    client = build_live_sync_app(
        session_factory,
        tmp_path,
        connector_sync_execution_enabled=True,
    )
    create_dispatched_live_sync_run_via_api(client, "run_file_csv_live_sync_legacy")

    body = execute_sync_via_api(
        client,
        "run_file_csv_live_sync_legacy",
        "sync_exec_live_legacy",
    )

    assert body["status"] == "sync_execution_completed"
    result = body["sync_execution_result"]
    assert result["adapter"] == "axis-self-hosted-connector-sync-executor"
    assert result["result_summary"]["source_mode"] == "self_hosted_demo"

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        batch_checkpoints = repository.list_connector_sync_checkpoints(
            TENANT_ID,
            run_id="run_file_csv_live_sync_legacy",
            status="sync_batch_committed",
        )
        proposals = repository.list_connector_ontology_proposals(
            tenant_id=TENANT_ID,
            connector_id=FILE_CSV_CONNECTOR_ID,
        )

    assert batch_checkpoints == []
    assert proposals == []


class GeneratedLiveSyncRuntime:
    """Live sync runtime that generates batches deterministically per offset.

    Used to exercise the per-execution batch bound without materializing a
    hand-written batch list. ``source_mode``/``external_query_required`` are
    configurable so the same runtime can stand in for the external DB seam.
    """

    adapter_name = "axis-generated-live-sync-runtime"

    def __init__(
        self,
        *,
        source_mode: str = "file_csv_live_sync",
        external_query_required: bool = False,
        batch_size: int = 1,
        exhaust_at_offset: int | None = None,
    ) -> None:
        self.source_mode = source_mode
        self.external_query_required = external_query_required
        self.batch_size = batch_size
        self.exhaust_at_offset = exhaust_at_offset
        self.batch_requests: list[ConnectorLiveSyncBatchRequest] = []

    def plan(self, request: ConnectorLiveSyncPlanRequest) -> ConnectorLiveSyncPlan:
        return ConnectorLiveSyncPlan(
            adapter=self.adapter_name,
            status=LIVE_SYNC_PLAN_READY_STATUS,
            source_mode=self.source_mode,
            source_ref="generated-source",
            batch_size=self.batch_size,
            max_records=10_000,
            external_query_required=self.external_query_required,
        )

    def read_batch(
        self,
        request: ConnectorLiveSyncBatchRequest,
    ) -> ConnectorLiveSyncBatchResult:
        self.batch_requests.append(request)
        next_offset = request.offset + self.batch_size
        exhausted = (
            self.exhaust_at_offset is not None and next_offset >= self.exhaust_at_offset
        )
        records = [
            ConnectorLiveSyncRecord(
                node_id=f"node_{request.offset + index}",
                node_type="work_order",
                ontology_type="production_order",
                field_summary={"status": "scheduled"},
            )
            for index in range(self.batch_size)
        ]
        return ConnectorLiveSyncBatchResult(
            adapter=self.adapter_name,
            status=LIVE_SYNC_BATCH_READ_STATUS,
            records=records,
            next_offset=next_offset,
            source_exhausted=exhausted,
        )


def test_execute_live_sync_bounds_batches_per_execution(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    # Never exhausts, so the per-execution bound is what stops the loop.
    runtime = GeneratedLiveSyncRuntime(batch_size=1, exhaust_at_offset=None)

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, FILE_CSV_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=FILE_CSV_CONNECTOR_ID,
            handle_id="cred_file_csv_readonly",
            lease_id=FILE_CSV_LEASE_ID,
        )
        create_dispatched_live_sync_run(
            repository,
            run_id="run_file_csv_live_sync_bound",
            input_summary=file_csv_live_sync_input_summary(),
        )

        run = execute_demo_connector_sync(
            repository,
            "run_file_csv_live_sync_bound",
            sync_execution_request(
                execution_id="sync_exec_live_bound",
                idempotency_key="idem_sync_exec_live_bound",
            ),
            live_sync_runtime=runtime,
        )
        batch_checkpoints = repository.list_connector_sync_checkpoints(
            TENANT_ID,
            run_id="run_file_csv_live_sync_bound",
            status="sync_batch_committed",
        )
        failed_events = repository.list_audit_events(
            TENANT_ID,
            event_type="connector.run.sync_execution_failed",
        )

    assert run.status == "sync_execution_failed"
    summary = run.sync_execution_result.result_summary
    assert summary["sync_error_code"] == "sync_batch_limit_exceeded"
    assert summary["sync_batches_committed"] == str(LIVE_SYNC_MAX_BATCHES_PER_EXECUTION)
    assert len(runtime.batch_requests) == LIVE_SYNC_MAX_BATCHES_PER_EXECUTION
    assert len(batch_checkpoints) == LIVE_SYNC_MAX_BATCHES_PER_EXECUTION
    assert len(failed_events) == 1


def test_execute_external_db_live_sync_resumes_after_batch_bound(
    session_factory: sessionmaker[Session],
) -> None:
    payload = live_capable_registry_payload(EXTERNAL_DB_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    external_input_summary = {
        "live_sync_requested": "true",
        "connection_profile_id": "profile_postgres_ops_readonly",
        "schema_name": "operations",
        "table_name": "production_orders",
        "selected_columns": "order_id,asset_id,work_center,status,risk_level",
        "query_mode": "read_only_snapshot",
        "egress_policy_id": "egress_policy_private_endpoint_ops",
        "egress_boundary": "approved_private_endpoint",
        "credential_access_mode": "lease_scoped_secret_ref",
    }
    first_runtime = GeneratedLiveSyncRuntime(
        source_mode="external_db_live_sync",
        external_query_required=True,
        batch_size=1,
        exhaust_at_offset=None,
    )
    resume_runtime = GeneratedLiveSyncRuntime(
        source_mode="external_db_live_sync",
        external_query_required=True,
        batch_size=1,
        exhaust_at_offset=LIVE_SYNC_MAX_BATCHES_PER_EXECUTION + 1,
    )

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_manifest(repository, EXTERNAL_DB_CONNECTOR_ID, payload)
        seed_credentials(
            repository,
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
            handle_id="cred_external_db_readonly",
            lease_id=EXTERNAL_DB_LEASE_ID,
        )
        # Persist the egress policy so external-DB egress evidence validates.
        seed_external_db_egress_policy(repository)
        create_dispatched_live_sync_run(
            repository,
            run_id="run_external_db_live_sync_resume",
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
            handle_id="cred_external_db_readonly",
            lease_id=EXTERNAL_DB_LEASE_ID,
            input_summary=external_input_summary,
        )

        failed_run = execute_demo_connector_sync(
            repository,
            "run_external_db_live_sync_resume",
            sync_execution_request(
                execution_id="sync_exec_external_db_resume_1",
                idempotency_key="idem_sync_exec_external_db_resume_1",
                lease_id=EXTERNAL_DB_LEASE_ID,
            ),
            live_sync_runtime=first_runtime,
        )
        assert failed_run.status == "sync_execution_failed"
        assert failed_run.sync_execution_result.result_summary["sync_error_code"] == (
            "sync_batch_limit_exceeded"
        )

        last_batch = LIVE_SYNC_MAX_BATCHES_PER_EXECUTION
        claim, created = claim_connector_sync_checkpoint(
            repository,
            f"chk_run_external_db_live_sync_resume_batch_{last_batch}",
            ConnectorSyncCheckpointClaimRequest(
                tenant_id=TENANT_ID,
                claim_id="claim_external_db_resume",
                claimed_by="axis-sync-worker-role",
                actor_scopes=["connectors:sync:checkpoint:claim"],
                idempotency_key="idem_claim_external_db_resume",
            ),
        )
        assert created is True

        resumed_run = execute_demo_connector_sync(
            repository,
            "run_external_db_live_sync_resume",
            sync_execution_request(
                execution_id="sync_exec_external_db_resume_2",
                idempotency_key="idem_sync_exec_external_db_resume_2",
                lease_id=EXTERNAL_DB_LEASE_ID,
                checkpoint_claim_id=claim.claim_id,
            ),
            live_sync_runtime=resume_runtime,
        )
        proposals = repository.list_connector_ontology_proposals(
            tenant_id=TENANT_ID,
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
            limit=200,
        )

    # Resume picks up exactly at the last committed batch offset, not backwards.
    assert resume_runtime.batch_requests[0].offset == LIVE_SYNC_MAX_BATCHES_PER_EXECUTION
    assert resumed_run.status == "sync_execution_completed"
    summary = resumed_run.sync_execution_result.result_summary
    assert summary["resume_offset"] == str(LIVE_SYNC_MAX_BATCHES_PER_EXECUTION)
    assert summary["records_read"] == str(LIVE_SYNC_MAX_BATCHES_PER_EXECUTION + 1)
    assert summary["sync_batches_committed"] == str(LIVE_SYNC_MAX_BATCHES_PER_EXECUTION + 1)
    assert summary["proposals_recorded"] == str(LIVE_SYNC_MAX_BATCHES_PER_EXECUTION + 1)
    assert summary["external_query_started"] == "true"
    assert summary["source_mode"] == "external_db_live_sync"
    # No proposal_id collision despite the batch bound + resume overlap boundary.
    assert len(proposals) == LIVE_SYNC_MAX_BATCHES_PER_EXECUTION + 1
    assert len({proposal.proposal_id for proposal in proposals}) == len(proposals)


def test_claim_endpoint_rejects_concurrent_active_claim(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
) -> None:
    payload = live_capable_registry_payload(FILE_CSV_CONNECTOR_ID)
    seed_connector_registry_reference(session_factory, payload)
    seed_live_file_csv_tenant_state(session_factory, payload)
    (tmp_path / "dropzone-assets.csv").write_text(DROPZONE_CSV_CONTENT)
    client = build_live_sync_app(session_factory, tmp_path)

    checkpoint_id = "chk_run_claim_endpoint_batch_1"
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        checkpoint_event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=TENANT_ID,
                actor_id="axis-sync-worker-role",
                event_type="connector.run.sync_execution_preflight_passed",
                payload={
                    "connector_id": FILE_CSV_CONNECTOR_ID,
                    "run_id": "run_claim_endpoint",
                    "checkpoint_id": checkpoint_id,
                },
            )
        )
        repository.create_connector_sync_checkpoint(
            ConnectorSyncCheckpointCreate(
                tenant_id=TENANT_ID,
                connector_id=FILE_CSV_CONNECTOR_ID,
                run_id="run_claim_endpoint",
                checkpoint_id=checkpoint_id,
                checkpoint_type="sync_batch",
                status="sync_batch_committed",
                sequence=1,
                runtime_boundary="axis-connector-sandbox",
                adapter="axis-file-csv-live-sync-executor",
                cursor={"next_offset": "2"},
                result_summary={"external_query_started": "false"},
                evidence_refs=[str(checkpoint_event.id)],
                audit_event_id=checkpoint_event.id,
                audit_event_type="connector.run.sync_batch_committed",
                notes=["Batch checkpoint for concurrent-claim endpoint test."],
            )
        )

    def claim_body(claim_id: str, idempotency_key: str) -> dict:
        return {
            "tenant_id": TENANT_ID,
            "claim_id": claim_id,
            "claimed_by": "axis-sync-worker-role",
            "actor_scopes": ["connectors:sync:checkpoint:claim"],
            "idempotency_key": idempotency_key,
        }

    first = client.post(
        f"/demo/manufacturing/connectors/runs/checkpoints/{checkpoint_id}/claims",
        json=claim_body("claim_endpoint_a", "idem_endpoint_a"),
    )
    second = client.post(
        f"/demo/manufacturing/connectors/runs/checkpoints/{checkpoint_id}/claims",
        json=claim_body("claim_endpoint_b", "idem_endpoint_b"),
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"]["reason"] == "active_checkpoint_claim_exists"

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        active_claims = repository.list_connector_sync_checkpoint_claims(
            TENANT_ID,
            checkpoint_id=checkpoint_id,
            status="claimed",
        )

    assert len(active_claims) == 1
    assert active_claims[0].claim_id == "claim_endpoint_a"
