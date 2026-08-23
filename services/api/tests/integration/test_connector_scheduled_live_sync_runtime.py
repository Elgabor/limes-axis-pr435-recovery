"""Scheduled live-sync runtime integration test (opt-in, Docker Postgres).

Modeled on ``test_connector_live_postgres_runtime.py``: the local Docker
Postgres plays the EXTERNAL operational system while Axis persistence runs on
SQLite. The external DSN is never configured statically — it is resolved per
batch through the ``env://`` lease-scoped secret resolver under an active
lease, with runtime egress enforcement pinning the actual connect target.

The test runs two scheduled batches split across two executions (the first is
bounded to a single batch, like a worker tick that stops mid-run), claims the
committed batch checkpoint and resumes deterministically, then asserts that
zero secret material (DSN, credentials, ``postgresql`` markers) exists in any
persisted record or audit payload.

Skips cleanly unless ``AXIS_RUN_INTEGRATION=1`` with the Docker runtime up.
"""

import json
import os
from copy import deepcopy
from datetime import datetime
from runpy import run_path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.connector_execution import (
    LEASE_SCOPED_RESOLUTION_DSN_SENTINEL,
    ExternalPostgresLiveQueryProfile,
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
    ConnectorRunCreateRequest,
    ConnectorRunDispatchRequest,
    ConnectorRunSyncExecutionRequest,
    ConnectorSyncCheckpointClaimRequest,
    claim_connector_sync_checkpoint,
    dispatch_demo_connector_sync,
    execute_demo_connector_sync,
    record_demo_connector_run,
)
from axis_api.connector_secret_resolution import EnvLeaseScopedSecretResolver
from axis_api.db import session_scope
from axis_api.models import AuditEvent, Base, utc_now
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorCredentialHandleCreate,
    ConnectorCredentialLeaseCreate,
    ConnectorEgressPolicyCreate,
    DemoReferenceRecordCreate,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("AXIS_RUN_INTEGRATION") != "1",
        reason="set AXIS_RUN_INTEGRATION=1 with the local Docker runtime running",
    ),
]

TENANT_ID = "tenant_demo_manufacturing"
EXTERNAL_DB_CONNECTOR_ID = "external_db_operational_mirror"
EXTERNAL_DB_LEASE_ID = "lease_external_db_readonly_20260710"
RUN_ID = "run_scheduled_live_sync_integration"
ENV_SECRET_VAR = "AXIS_INTEGRATION_SCHEDULED_LIVE_SYNC_DSN"
EXTERNAL_SCHEMA = "axis_scheduled_live_sync_test"
PRIVATE_ENDPOINT_REF = (
    "private-endpoint://tenant_demo_manufacturing/persisted-operations-postgres-readonly"
)
WORKER_ACTOR = "axis-sync-worker-role"
INPUT_SUMMARY = {
    "live_sync_requested": "true",
    "connection_profile_id": "profile_postgres_ops_readonly",
    "schema_name": EXTERNAL_SCHEMA,
    "table_name": "production_orders",
    "selected_columns": "order_id,asset_id,work_center,status,risk_level",
    "query_mode": "read_only_snapshot",
    "egress_policy_id": "egress_policy_private_endpoint_ops",
    "egress_boundary": "approved_private_endpoint",
    "credential_access_mode": "lease_scoped_secret_ref",
}


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


def _live_capable_registry_payload() -> dict:
    migration = run_path("migrations/versions/0023_connector_registry_reference.py")
    payload = deepcopy(migration["CONNECTOR_REGISTRY_PAYLOAD"])
    connector = next(
        item
        for item in payload["connectors"]
        if item["manifest"]["connector_id"] == EXTERNAL_DB_CONNECTOR_ID
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


def _seed_axis_state(
    repository: AxisPersistenceRepository,
    payload: dict,
    *,
    endpoint_target_sha256: str,
) -> None:
    repository.upsert_demo_reference_record(
        DemoReferenceRecordCreate(
            tenant_id=TENANT_ID,
            surface="connectors",
            reference_id="manufacturing-connector-registry",
            status="active",
            source="bootstrap",
            version="2026-06-22",
            payload=payload,
        )
    )
    connector = next(
        item
        for item in payload["connectors"]
        if item["manifest"]["connector_id"] == EXTERNAL_DB_CONNECTOR_ID
    )
    record_demo_connector_manifest(
        repository,
        ConnectorManifestCreateRequest(
            tenant_id=TENANT_ID,
            registered_by="platform-connector-owner-role",
            manifest=connector["manifest"],
            runtime_policy=connector["runtime_policy"],
            preview_sample=connector["preview_sample"],
            notes=["Manifest registered for scheduled live sync integration."],
        ),
    )
    for target_status, scopes, evidence in (
        (
            "active_preview",
            ["connectors:manifest:lifecycle"],
            ["approval:connector-live-sync-preview"],
        ),
        (
            "active_live",
            ["connectors:manifest:lifecycle", "connectors:manifest:enable_live"],
            [
                "approval:connector-live-sync-enable",
                "policy:live-sync-boundary-reviewed",
                "credential:live-sync-readonly-lease-policy",
            ],
        ),
    ):
        transition_demo_connector_manifest_lifecycle(
            repository,
            EXTERNAL_DB_CONNECTOR_ID,
            ConnectorManifestLifecycleRequest(
                tenant_id=TENANT_ID,
                transitioned_by="platform-connector-owner-role",
                target_status=target_status,
                actor_scopes=scopes,
                transition_reason="Scheduled live sync integration gate.",
                evidence_refs=evidence,
            ),
        )
    now = utc_now()
    repository.create_connector_credential_handle(
        ConnectorCredentialHandleCreate(
            tenant_id=TENANT_ID,
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
            handle_id="cred_external_db_readonly",
            display_name="Read-only env-resolved integration handle",
            status="active",
            secret_provider="env_dev",
            secret_ref=f"env://{ENV_SECRET_VAR}",
            purpose="read_only_connector_execution",
            rotation_interval_days=30,
            last_rotated_at=now,
            next_rotation_due_at=now,
            created_by="security-owner-role",
            labels={"environment": "integration"},
            notes=["Metadata-only credential handle for lease-scoped resolution."],
        )
    )
    repository.create_connector_credential_lease(
        ConnectorCredentialLeaseCreate(
            tenant_id=TENANT_ID,
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
            handle_id="cred_external_db_readonly",
            lease_id=EXTERNAL_DB_LEASE_ID,
            status="active",
            lease_mode="provider_specific_vault_kms_lease",
            runtime_boundary="axis-credential-lease-broker",
            requested_by="axis-connector-runtime-role",
            lease_purpose="scheduled_connector_sync",
            secret_provider="env_dev",
            secret_ref=f"env://{ENV_SECRET_VAR}",
            vault_kms_policy={"ttl_seconds": "900", "max_ttl_seconds": "1800"},
            permission_decision={
                "allowed": True,
                "reason": "all_required_scopes_present",
            },
            lease_result={
                "adapter": "axis-provider-specific-vault-kms-lease-adapter",
                "status": "lease_executed",
                "provider_lease_ref": (
                    f"env://axis/leases/{TENANT_ID}/{EXTERNAL_DB_LEASE_ID}"
                ),
                "secret_material_returned": "false",
            },
            granted_at=now,
            expires_at=now.replace(year=now.year + 1),
            renewal_due_at=now,
            notes=["Active env-resolved lease for the integration run."],
        )
    )
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
                "approved_endpoint_target_sha256": endpoint_target_sha256,
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
                "approved_endpoint_target_sha256": endpoint_target_sha256,
                "transport": "private_endpoint",
                "live_query_mode": "read_only_snapshot",
            },
            evidence_refs=[str(audit_event.id)],
            audit_event_id=audit_event.id,
            notes=["Persisted egress policy for the scheduled live sync integration."],
        )
    )
    record_demo_connector_run(
        repository,
        ConnectorRunCreateRequest(
            tenant_id=TENANT_ID,
            connector_id=EXTERNAL_DB_CONNECTOR_ID,
            run_id=RUN_ID,
            execution_mode="scheduled_sync_plan",
            requested_by="plant-operations-owner-role",
            credential_handle_ids=["cred_external_db_readonly"],
            credential_lease_id=EXTERNAL_DB_LEASE_ID,
            schedule_id="schedule_external_db_orders_hourly",
            schedule_cadence="hourly",
            schedule_timezone="Europe/Rome",
            next_run_at=datetime(2026, 7, 10, 14, 0),
            input_summary=INPUT_SUMMARY,
        ),
    )
    dispatch_demo_connector_sync(
        repository,
        RUN_ID,
        ConnectorRunDispatchRequest(
            tenant_id=TENANT_ID,
            dispatch_id=f"dispatch_{RUN_ID}",
            dispatched_by="axis-scheduler-role",
            actor_scopes=["connectors:sync:dispatch"],
            credential_lease_id=EXTERNAL_DB_LEASE_ID,
            idempotency_key=f"idem_dispatch_{RUN_ID}",
        ),
    )


def _sync_execution_request(attempt: int) -> ConnectorRunSyncExecutionRequest:
    return ConnectorRunSyncExecutionRequest(
        tenant_id=TENANT_ID,
        execution_id=f"sched_exec_integration_{attempt}",
        executed_by=WORKER_ACTOR,
        actor_scopes=["connectors:sync:execute"],
        credential_lease_id=EXTERNAL_DB_LEASE_ID,
        checkpoint_claim_id=(None if attempt == 1 else "claim_sched_integration"),
        idempotency_key=f"idem_sched_exec_integration_{attempt}",
    )


def _scan_for_secret_material(session: Session, markers: tuple[str, ...]) -> list[str]:
    leaks: list[str] = []
    repository = AxisPersistenceRepository(session)
    for event in session.scalars(select(AuditEvent)):
        serialized = json.dumps(event.payload, default=str)
        leaks.extend(
            f"audit:{event.event_type}:{marker}"
            for marker in markers
            if marker in serialized
        )
    for run in repository.list_connector_runs(TENANT_ID, limit=200):
        serialized = json.dumps(run.result_summary, default=str) + json.dumps(
            run.input_summary, default=str
        )
        leaks.extend(f"run:{run.run_id}:{marker}" for marker in markers if marker in serialized)
    for checkpoint in repository.list_connector_sync_checkpoints(TENANT_ID):
        serialized = json.dumps(checkpoint.result_summary, default=str) + json.dumps(
            checkpoint.cursor, default=str
        )
        leaks.extend(
            f"checkpoint:{checkpoint.checkpoint_id}:{marker}"
            for marker in markers
            if marker in serialized
        )
    for proposal in repository.list_connector_ontology_proposals(
        tenant_id=TENANT_ID,
        connector_id=EXTERNAL_DB_CONNECTOR_ID,
        limit=200,
    ):
        serialized = json.dumps(proposal.field_summary, default=str)
        leaks.extend(
            f"proposal:{proposal.proposal_id}:{marker}"
            for marker in markers
            if marker in serialized
        )
    return leaks


def test_scheduled_live_sync_resolves_env_secret_and_resumes_deterministically(
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    settings = Settings()
    external_dsn = settings.postgres_dsn
    endpoint_target_sha256 = postgres_endpoint_target_sha256(external_dsn)
    monkeypatch.setenv(ENV_SECRET_VAR, external_dsn)
    # Bound the first execution to a single committed batch: it plays the
    # "first scheduled tick" that stops mid-run and must resume via the claim.
    monkeypatch.setattr(
        "axis_api.connector_runs.LIVE_SYNC_MAX_BATCHES_PER_EXECUTION",
        1,
    )
    runtime = SelfHostedConnectorLiveSyncRuntime(
        external_db_live_sync_enabled=True,
        external_postgres_profile=ExternalPostgresLiveQueryProfile(
            profile_id="profile_postgres_ops_readonly",
            dsn=LEASE_SCOPED_RESOLUTION_DSN_SENTINEL,
            schema_name=EXTERNAL_SCHEMA,
            table_name="production_orders",
            allowed_columns=["order_id", "asset_id", "work_center", "status", "risk_level"],
            private_endpoint_ref=PRIVATE_ENDPOINT_REF,
            endpoint_target_sha256=endpoint_target_sha256,
            row_limit=10,
        ),
        external_db_batch_size=2,
        lease_scoped_secret_resolution_enabled=True,
        runtime_egress_enforcement_enabled=True,
        secret_resolver=EnvLeaseScopedSecretResolver(),
    )
    external_engine = create_engine(external_dsn)
    payload = _live_capable_registry_payload()
    try:
        with external_engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {EXTERNAL_SCHEMA} CASCADE"))
            connection.execute(text(f"CREATE SCHEMA {EXTERNAL_SCHEMA}"))
            connection.execute(
                text(
                    f"CREATE TABLE {EXTERNAL_SCHEMA}.production_orders ("
                    "order_id text PRIMARY KEY, "
                    "asset_id text NOT NULL, "
                    "work_center text NOT NULL, "
                    "status text NOT NULL, "
                    "risk_level text NOT NULL"
                    ")"
                )
            )
            connection.execute(
                text(
                    f"INSERT INTO {EXTERNAL_SCHEMA}.production_orders "
                    "(order_id, asset_id, work_center, status, risk_level) VALUES "
                    "('po-1001', 'asset-7', 'line-a', 'scheduled', 'low'), "
                    "('po-1002', 'asset-9', 'line-b', 'blocked', 'high'), "
                    "('po-1003', 'asset-11', 'line-c', 'running', 'medium')"
                )
            )

        with session_scope(session_factory) as session:
            repository = AxisPersistenceRepository(session)
            _seed_axis_state(
                repository,
                payload,
                endpoint_target_sha256=endpoint_target_sha256,
            )

            first_run = execute_demo_connector_sync(
                repository,
                RUN_ID,
                _sync_execution_request(1),
                live_sync_runtime=runtime,
            )
            assert first_run.status == "sync_execution_failed"
            first_summary = first_run.sync_execution_result.result_summary
            assert first_summary["sync_error_code"] == "sync_batch_limit_exceeded"
            assert first_summary["sync_batches_committed"] == "1"
            assert first_summary["next_offset"] == "2"

            claim, created = claim_connector_sync_checkpoint(
                repository,
                f"chk_{RUN_ID}_batch_1",
                ConnectorSyncCheckpointClaimRequest(
                    tenant_id=TENANT_ID,
                    claim_id="claim_sched_integration",
                    claimed_by=WORKER_ACTOR,
                    actor_scopes=["connectors:sync:checkpoint:claim"],
                    idempotency_key="idem_claim_sched_integration",
                ),
            )
            assert created is True

            resumed_run = execute_demo_connector_sync(
                repository,
                RUN_ID,
                _sync_execution_request(2),
                live_sync_runtime=runtime,
            )
            proposals = repository.list_connector_ontology_proposals(
                tenant_id=TENANT_ID,
                connector_id=EXTERNAL_DB_CONNECTOR_ID,
                limit=200,
            )
            checkpoints = repository.list_connector_sync_checkpoints(
                TENANT_ID,
                run_id=RUN_ID,
                status="sync_batch_committed",
            )
            leaks = _scan_for_secret_material(
                session,
                markers=(external_dsn, "postgresql://", "axis:axis"),
            )
    finally:
        with external_engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {EXTERNAL_SCHEMA} CASCADE"))
        external_engine.dispose()

    assert resumed_run.status == "sync_execution_completed"
    summary = resumed_run.sync_execution_result.result_summary
    # Checkpoint resume determinism: the second scheduled execution starts at
    # exactly the committed offset and completes the remaining row once.
    assert summary["resume_offset"] == "2"
    assert summary["next_offset"] == "3"
    assert summary["records_read"] == "3"
    assert summary["sync_batches_committed"] == "2"
    assert summary["proposals_recorded"] == "3"
    assert summary["secret_retrieval_decision"] == "resolved_lease_scoped_secret"
    assert summary["runtime_egress_enforcement"] == "enforced_target_match"
    assert summary["checkpoint_claim_id"] == "claim_sched_integration"
    assert [proposal.node_id for proposal in sorted(
        proposals, key=lambda item: item.proposal_id
    )] == ["po-1001", "po-1002", "po-1003"]
    assert len({proposal.proposal_id for proposal in proposals}) == 3
    assert len(checkpoints) == 2
    # Zero secret material in any persisted record or audit payload.
    assert leaks == []
