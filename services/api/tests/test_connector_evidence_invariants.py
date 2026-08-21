from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import ApprovalRecord, Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorCredentialLeaseCreate,
    ConnectorEgressPolicyCreate,
    ConnectorSyncCheckpointClaimCreate,
    ConnectorSyncCheckpointCreate,
    TenantCreate,
)
from axis_api.workflow_runtime import WorkflowSignalResult


class RecordingSnapshotExportWorkflowRuntime:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def signal_connector_evidence_snapshot_export(
        self,
        request: object,
    ) -> WorkflowSignalResult:
        self.requests.append(request)
        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="export_request_signal_requested",
            adapter="axis-test-workflow-adapter",
            signal_name=request.signal_name,
            payload=request.audit_payload,
        )


def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def seed_mismatched_connector_evidence(repository: AxisPersistenceRepository) -> None:
    if repository.get_tenant("tenant_demo_manufacturing") is None:
        repository.create_tenant(
            TenantCreate(
                tenant_id="tenant_demo_manufacturing",
                display_name="Ravenna Works",
                description="Plant Operations Cockpit",
                created_by="test",
            )
        )
    checkpoint_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="axis-sync-worker-role",
            event_type="connector.run.sync_execution_completed",
            payload={
                "connector_id": "external_db_operational_mirror",
                "run_id": "run_evidence_report_20260627",
                "checkpoint_id": "chk_other",
                "external_query_started": False,
                "credential_material_returned": False,
                "graph_mutation_started": False,
            },
        )
    )
    repository.create_connector_sync_checkpoint(
        ConnectorSyncCheckpointCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            run_id="run_evidence_report_20260627",
            checkpoint_id="chk_evidence_report_1",
            checkpoint_type="sync_execution",
            status="sync_execution_completed",
            sequence=1,
            runtime_boundary="axis-workflow-runtime-adapter",
            adapter="axis-postgres-external-db-sync-executor",
            cursor={"high_watermark_kind": "timestamp"},
            result_summary={
                "external_query_started": "false",
                "credential_material_returned": "false",
                "graph_mutation_started": "false",
            },
            evidence_refs=[str(checkpoint_event.id)],
            audit_event_id=checkpoint_event.id,
            audit_event_type="connector.run.sync_execution_completed",
            notes=["Checkpoint seeded with mismatched audit payload."],
        )
    )

    claim_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="axis-sync-worker-role",
            event_type="connector.run.sync_checkpoint_claimed",
            payload={
                "connector_id": "external_db_operational_mirror",
                "run_id": "run_evidence_report_20260627",
                "checkpoint_id": "chk_evidence_report_1",
                "claim_id": "claim_evidence_report_1",
                "claimed_by": "axis-sync-worker-other-role",
                "external_sync_started": False,
                "secret_material_returned": False,
                "worker_claim_only": True,
            },
        )
    )
    repository.create_connector_sync_checkpoint_claim(
        ConnectorSyncCheckpointClaimCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            run_id="run_evidence_report_20260627",
            checkpoint_id="chk_evidence_report_1",
            claim_id="claim_evidence_report_1",
            status="claimed",
            claimed_by="axis-sync-worker-role",
            idempotency_key="idem_claim_evidence_report_1",
            lease_duration_seconds=900,
            lease_expires_at=datetime(2026, 6, 27, 10, 15, tzinfo=UTC),
            claim_result={
                "external_sync_started": False,
                "secret_material_returned": False,
                "worker_claim_only": True,
            },
            audit_event_id=claim_event.id,
            audit_event_type="connector.run.sync_checkpoint_claimed",
            notes=["Claim seeded with mismatched audit payload."],
        )
    )

    lease_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="axis-connector-runtime-role",
            event_type="connector.credential_lease.requested",
            payload={
                "connector_id": "external_db_operational_mirror",
                "handle_id": "cred_external_db_readonly",
                "lease_id": "lease_other",
                "secret_material_returned": "false",
                "external_secret_read": "false",
            },
        )
    )
    repository.create_connector_credential_lease(
        ConnectorCredentialLeaseCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            handle_id="cred_external_db_readonly",
            lease_id="lease_evidence_report_1",
            requested_by="axis-connector-runtime-role",
            lease_purpose="scheduled_sync_preflight",
            secret_provider="external_vault",
            secret_ref="vault://axis/demo/connectors/external-db-readonly",
            vault_kms_policy={"provider_mode": "self_hosted_vault"},
            permission_decision={"allowed": True, "reason": "all_required_scopes_present"},
            lease_result={
                "adapter": "axis-deferred-vault-kms-lease-adapter",
                "status": "lease_deferred",
                "external_secret_read": "false",
                "secret_material_returned": "false",
                "provider_mode": "deferred",
                "provider_lease_ref": "deferred-lease://tenant/lease_evidence_report_1",
            },
            granted_at=datetime(2026, 6, 27, 10, 0, tzinfo=UTC),
            expires_at=datetime(2026, 6, 27, 10, 15, tzinfo=UTC),
            renewal_due_at=datetime(2026, 6, 27, 10, 10, tzinfo=UTC),
            audit_event_id=lease_event.id,
            audit_event_type="connector.credential_lease.requested",
            notes=["Lease seeded with mismatched audit payload."],
        )
    )

    policy_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="network-policy-owner-role",
            event_type="connector.egress_policy.registered",
            payload={
                "connector_id": "external_db_operational_mirror",
                "policy_id": "egress_policy_other",
                "connection_profile_id": "profile_postgres_ops_readonly",
                "external_query_started": False,
                "credential_material_returned": False,
            },
        )
    )
    repository.create_connector_egress_policy(
        ConnectorEgressPolicyCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            policy_id="egress_policy_evidence_report_1",
            display_name="External DB private endpoint",
            status="active",
            connection_profile_id="profile_postgres_ops_readonly",
            egress_boundary="approved_private_endpoint",
            policy_mode="approved_private_endpoint",
            runtime_boundary="axis-egress-policy-enforcer",
            private_endpoint_ref="private-endpoint://tenant/external-db-readonly",
            created_by="network-policy-owner-role",
            policy_document={"transport": "private_endpoint"},
            evidence_refs=[str(policy_event.id)],
            audit_event_id=policy_event.id,
            audit_event_type="connector.egress_policy.registered",
            notes=["Policy seeded with mismatched audit payload."],
        )
    )


def test_connector_evidence_invariants_endpoint_aggregates_public_safe_records() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/connectors/evidence-invariants",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "external_db_operational_mirror",
            "actor_id": "connector-evidence-report-reader",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["metrics"][0] == {
        "label": "Evidence Invariants",
        "value": "4",
        "detail": (
            "Public-safe connector evidence issues across checkpoints, claims, "
            "leases and policies"
        ),
        "status": "watch",
    }
    assert [item["evidence_type"] for item in body["invariants"]] == [
        "checkpoint",
        "checkpoint_claim",
        "credential_lease",
        "egress_policy",
    ]
    assert [item["reason"] for item in body["invariants"]] == [
        "checkpoint_audit_event_payload_mismatch",
        "claim_audit_event_payload_mismatch",
        "lease_audit_event_payload_mismatch",
        "egress_policy_audit_event_payload_mismatch",
    ]
    assert body["invariant_counts"] == {
        "checkpoint": 1,
        "checkpoint_claim": 1,
        "credential_lease": 1,
        "egress_policy": 1,
    }
    serialized = str(body).lower()
    assert "private-endpoint://" not in serialized
    assert "vault://" not in serialized
    assert "postgres://" not in serialized
    assert "password" not in serialized
    assert "credential_value" not in serialized

    with session_scope(factory) as session:
        events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_invariants_read",
            limit=10,
        )

    assert len(events) == 1
    event = events[0]
    assert event.actor_id == "connector-evidence-report-reader"
    assert event.payload == {
        "connector_id": "external_db_operational_mirror",
        "limit": 100,
        "returned_invariant_count": 4,
        "invariant_counts": {
            "checkpoint": 1,
            "checkpoint_claim": 1,
            "credential_lease": 1,
            "egress_policy": 1,
        },
        "subject_ids": [
            "chk_evidence_report_1",
            "claim_evidence_report_1",
            "lease_evidence_report_1",
            "egress_policy_evidence_report_1",
        ],
    }
    assert "private-endpoint://" not in str(event.payload).lower()
    assert "vault://" not in str(event.payload).lower()
    assert "credential_value" not in str(event.payload).lower()


def snapshot_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "tenant_id": "tenant_demo_manufacturing",
        "snapshot_id": "snap_connector_evidence_20260627_1000",
        "connector_id": "external_db_operational_mirror",
        "requested_by": "connector-security-reviewer-role",
        "actor_scopes": ["connectors:evidence:snapshot"],
        "idempotency_key": "idem_connector_evidence_snapshot_20260627_1000",
        "reason": "security-review",
    }
    payload.update(overrides)
    return payload


def snapshot_export_request_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "tenant_id": "tenant_demo_manufacturing",
        "export_request_id": "export_req_connector_evidence_20260627_1000",
        "idempotency_key": "idem_connector_evidence_export_request_20260627_1000",
        "requested_by": "connector-compliance-reviewer-role",
        "actor_scopes": ["connectors:evidence:snapshot:export:request"],
        "owner_role": "connector-governance-owner",
        "risk_level": "high",
        "approval_id": "appr_connector_evidence_export_20260627_1000",
        "workflow_id": "wf_connector_evidence_export_review",
        "connector_id": "external_db_operational_mirror",
        "snapshot_id": "snap_connector_evidence_export_request_match",
        "export_reason": "regulated-evidence-review",
        "format": "json",
        "limit": 20,
        "controls": [
            "approval_required",
            "workflow_signal_required",
            "idempotency_enforced",
            "public_safe_bundle_only",
        ],
        "notes": ["Governed export request only; object storage is not written."],
    }
    payload.update(overrides)
    return payload


def snapshot_export_request_decision_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "decision": "approve",
        "actor_id": "connector-compliance-owner-role",
        "actor_scopes": ["approvals:connectors:export:decide"],
        "note": "Approved for regulated evidence review.",
    }
    payload.update(overrides)
    return payload


def snapshot_export_materialization_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "materialization_id": "mat_connector_evidence_export_20260627_1000",
        "idempotency_key": "idem_connector_evidence_export_materialization_20260627_1000",
        "actor_id": "connector-compliance-owner-role",
        "actor_scopes": ["connectors:evidence:snapshot:export:materialize"],
        "reason": "approved-regulated-evidence-export",
    }
    payload.update(overrides)
    return payload


def test_connector_evidence_invariant_snapshot_persists_public_safe_audit_artifact() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["snapshot_id"] == "snap_connector_evidence_20260627_1000"
    assert body["status"] == "persisted"
    assert body["connector_id"] == "external_db_operational_mirror"
    assert body["requested_by"] == "connector-security-reviewer-role"
    assert body["idempotent_replay"] is False
    assert body["permission_decision"] == {
        "allowed": True,
        "reason": "allowed",
    }
    assert body["invariant_count"] == 4
    assert body["invariant_counts"] == {
        "checkpoint": 1,
        "checkpoint_claim": 1,
        "credential_lease": 1,
        "egress_policy": 1,
    }
    assert body["subject_ids"] == [
        "chk_evidence_report_1",
        "claim_evidence_report_1",
        "lease_evidence_report_1",
        "egress_policy_evidence_report_1",
    ]
    assert body["report_hash_algorithm"] == "sha256-canonical-json-v1"
    assert len(body["report_digest_sha256"]) == 64
    assert body["audit_event_type"] == "connector.evidence_invariants.snapshot_persisted"

    with session_scope(factory) as session:
        events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_invariants.snapshot_persisted",
            limit=10,
        )

    assert len(events) == 1
    event = events[0]
    assert event.actor_id == "connector-security-reviewer-role"
    assert event.payload["snapshot_id"] == "snap_connector_evidence_20260627_1000"
    assert event.payload["idempotency_key"] == (
        "idem_connector_evidence_snapshot_20260627_1000"
    )
    assert event.payload["report_digest_sha256"] == body["report_digest_sha256"]
    assert event.payload["subject_ids"] == body["subject_ids"]
    serialized_body = str(body).lower()
    serialized_event = str(event.payload).lower()
    assert "private-endpoint://" not in serialized_body
    assert "private-endpoint://" not in serialized_event
    assert "vault://" not in serialized_body
    assert "vault://" not in serialized_event
    assert "postgres://" not in serialized_event
    assert "password" not in serialized_event
    assert "credential_value" not in serialized_event


def test_connector_evidence_invariant_snapshot_replays_idempotently() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)
    payload = snapshot_payload()

    first_response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=payload,
    )
    second_response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=payload,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    first_body = first_response.json()
    second_body = second_response.json()
    assert second_body["idempotent_replay"] is True
    assert second_body["audit_event_id"] == first_body["audit_event_id"]
    assert second_body["report_digest_sha256"] == first_body["report_digest_sha256"]
    with session_scope(factory) as session:
        events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_invariants.snapshot_persisted",
            limit=10,
        )
    assert len(events) == 1


def test_connector_evidence_invariant_snapshot_requires_scope_before_replay() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    first_response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(),
    )
    replay_without_scope = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(actor_scopes=[]),
    )

    assert first_response.status_code == 201
    assert replay_without_scope.status_code == 403
    assert replay_without_scope.json()["detail"]["required_scope"] == (
        "connectors:evidence:snapshot"
    )
    with session_scope(factory) as session:
        events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_invariants.snapshot_persisted",
            limit=10,
        )
    assert len(events) == 1


def test_connector_evidence_invariant_snapshot_rejects_idempotency_conflict() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    first_response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(),
    )
    conflict_response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(snapshot_id="snap_connector_evidence_conflict"),
    )

    assert first_response.status_code == 201
    assert conflict_response.status_code == 409
    assert conflict_response.json()["detail"]["reason"] == "idempotency_conflict"


def test_connector_evidence_invariant_snapshot_history_lists_audit_artifacts() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    first_response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(snapshot_id="snap_connector_evidence_history_a"),
    )
    second_response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(
            snapshot_id="snap_connector_evidence_history_b",
            connector_id=None,
            idempotency_key="idem_connector_evidence_snapshot_history_b",
        ),
    )
    history_response = client.get(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "actor_id": "connector-evidence-history-reader",
            "actor_scopes": "connectors:evidence:snapshot:read",
        },
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert history_response.status_code == 200
    body = history_response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["history_status"] == "ready"
    assert body["metrics"][0] == {
        "label": "Evidence Snapshots",
        "value": "2",
        "detail": "Persisted connector evidence snapshot audit artifacts",
        "status": "ready",
    }
    assert [snapshot["snapshot_id"] for snapshot in body["snapshots"]] == [
        "snap_connector_evidence_history_b",
        "snap_connector_evidence_history_a",
    ]
    assert body["snapshots"][0]["connector_id"] is None
    assert body["snapshots"][1]["connector_id"] == "external_db_operational_mirror"
    assert all(len(snapshot["report_digest_sha256"]) == 64 for snapshot in body["snapshots"])
    assert body["history_notes"] == [
        "Snapshot history is read from append-only audit events.",
        "History reads return public-safe snapshot metadata only.",
    ]

    with session_scope(factory) as session:
        read_events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_invariant_snapshots_read",
            limit=10,
        )

    assert len(read_events) == 1
    assert read_events[0].actor_id == "connector-evidence-history-reader"
    assert read_events[0].payload == {
        "connector_id": None,
        "snapshot_id": None,
        "idempotency_key": None,
        "limit": 100,
        "returned_snapshot_count": 2,
        "snapshot_ids": [
            "snap_connector_evidence_history_b",
            "snap_connector_evidence_history_a",
        ],
    }
    serialized = str(body).lower() + str(read_events[0].payload).lower()
    assert "private-endpoint://" not in serialized
    assert "vault://" not in serialized
    assert "postgres://" not in serialized
    assert "password" not in serialized
    assert "credential_value" not in serialized


def test_connector_evidence_invariant_snapshot_history_filters_connector() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(snapshot_id="snap_connector_evidence_filter_match"),
    )
    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(
            snapshot_id="snap_connector_evidence_filter_global",
            connector_id=None,
            idempotency_key="idem_connector_evidence_snapshot_filter_global",
        ),
    )

    response = client.get(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "external_db_operational_mirror",
            "actor_id": "connector-evidence-history-reader",
            "actor_scopes": "connectors:evidence:snapshot:read",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [snapshot["snapshot_id"] for snapshot in body["snapshots"]] == [
        "snap_connector_evidence_filter_match"
    ]
    assert body["metrics"][0]["value"] == "1"


def test_connector_evidence_invariant_snapshot_history_requires_read_scope() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(),
    )
    response = client.get(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "actor_id": "connector-evidence-history-reader",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["required_scope"] == (
        "connectors:evidence:snapshot:read"
    )
    with session_scope(factory) as session:
        read_events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_invariant_snapshots_read",
            limit=10,
        )
    assert read_events == []


def test_connector_evidence_invariant_snapshot_export_returns_signed_public_safe_bundle() -> None:
    factory = session_factory()
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            audit_ledger_signing_key_id="axis-connector-evidence-test-key",
            audit_ledger_signing_secret="connector-evidence-export-secret",
        )
    )
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(snapshot_id="snap_connector_evidence_export_match"),
    )
    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(
            snapshot_id="snap_connector_evidence_export_tenant",
            connector_id=None,
            idempotency_key="idem_connector_evidence_snapshot_export_tenant",
        ),
    )

    response = client.get(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "external_db_operational_mirror",
            "actor_id": "connector-evidence-exporter-role",
            "actor_scopes": "connectors:evidence:snapshot:read",
            "export_reason": "design-partner-review",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["export_reason"] == "design-partner-review"
    assert body["format"] == "json"
    assert body["filters"]["connector_id"] == "external_db_operational_mirror"
    assert body["manifest"]["record_count"] == 1
    assert body["manifest"]["redaction_policy"] == "connector-snapshot-public-safe"
    assert body["manifest"]["checksum_sha256"]
    assert body["integrity_proof"]["algorithm"] == "sha256-hash-chain-v1"
    assert body["integrity_proof"]["record_count"] == 1
    assert body["ledger_signature"]["algorithm"] == "hmac-sha256"
    assert body["ledger_signature"]["key_id"] == "axis-connector-evidence-test-key"
    assert body["ledger_signature"]["verification_status"] == "verified"
    assert [snapshot["snapshot_id"] for snapshot in body["snapshots"]] == [
        "snap_connector_evidence_export_match"
    ]
    serialized = str(body).lower()
    assert "connector-evidence-export-secret" not in serialized
    assert "private-endpoint://" not in serialized
    assert "vault://" not in serialized
    assert "postgres://" not in serialized
    assert "password" not in serialized
    assert "credential_value" not in serialized

    with session_scope(factory) as session:
        export_events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_invariant_snapshots_exported",
            limit=10,
        )

    assert len(export_events) == 1
    assert export_events[0].actor_id == "connector-evidence-exporter-role"
    assert export_events[0].payload["exported_snapshot_count"] == 1
    assert export_events[0].payload["snapshot_ids"] == [
        "snap_connector_evidence_export_match"
    ]
    assert "connector-evidence-export-secret" not in str(export_events[0].payload)


def test_connector_evidence_invariant_snapshot_export_requires_read_scope() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(),
    )
    response = client.get(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "actor_id": "connector-evidence-exporter-role",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["required_scope"] == (
        "connectors:evidence:snapshot:read"
    )
    with session_scope(factory) as session:
        export_events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_invariant_snapshots_exported",
            limit=10,
        )
    assert export_events == []


def test_connector_evidence_invariant_snapshot_export_request_records_governed_metadata() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(
            snapshot_id="snap_connector_evidence_export_request_match",
            idempotency_key="idem_connector_evidence_snapshot_export_request_match",
        ),
    )
    response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests",
        json=snapshot_export_request_payload(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["export_request_id"] == "export_req_connector_evidence_20260627_1000"
    assert body["status"] == "approval_required"
    assert body["export_status"] == "not_exported"
    assert body["storage_status"] == "not_written"
    assert body["workflow_signal_status"] == "pending_approval_decision"
    assert body["approval_id"] == "appr_connector_evidence_export_20260627_1000"
    assert body["workflow_id"] == "wf_connector_evidence_export_review"
    assert body["snapshot_filter"] == {
        "connector_id": "external_db_operational_mirror",
        "snapshot_id": "snap_connector_evidence_export_request_match",
        "idempotency_key": None,
        "limit": 20,
    }
    assert body["requested_snapshot_count"] == 1
    assert len(body["snapshot_checksum_sha256"]) == 64
    assert body["format"] == "json"
    assert body["redaction_policy"] == "connector-snapshot-public-safe"
    assert body["permission_decision"] == {"allowed": True, "reason": "allowed"}
    assert body["audit_event_type"] == "connector.evidence_snapshot_export.requested"
    assert body["idempotent_replay"] is False
    assert "public_safe_bundle_only" in body["controls"]
    serialized = str(body).lower()
    assert "private-endpoint://" not in serialized
    assert "vault://" not in serialized
    assert "postgres://" not in serialized
    assert "password" not in serialized
    assert "credential_value" not in serialized

    with session_scope(factory) as session:
        events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_snapshot_export.requested",
            limit=10,
        )
        approval = session.execute(
            select(ApprovalRecord).where(
                ApprovalRecord.tenant_id == "tenant_demo_manufacturing",
                ApprovalRecord.approval_id == "appr_connector_evidence_export_20260627_1000",
            )
        ).scalar_one()
        row = session.execute(
            text(
                "select export_request_id, requested_snapshot_count, storage_status "
                "from connector_evidence_snapshot_export_requests "
                "where tenant_id = :tenant_id and export_request_id = :export_request_id"
            ),
            {
                "tenant_id": "tenant_demo_manufacturing",
                "export_request_id": "export_req_connector_evidence_20260627_1000",
            },
        ).one()

    assert len(events) == 1
    event = events[0]
    assert event.actor_id == "connector-compliance-reviewer-role"
    assert event.payload["export_request_id"] == "export_req_connector_evidence_20260627_1000"
    assert event.payload["approval_id"] == "appr_connector_evidence_export_20260627_1000"
    assert event.payload["workflow_id"] == "wf_connector_evidence_export_review"
    assert event.payload["requested_snapshot_count"] == 1
    assert event.payload["storage_status"] == "not_written"
    assert "private-endpoint://" not in str(event.payload).lower()
    assert approval.status == "pending"
    assert approval.workflow_id == "wf_connector_evidence_export_review"
    assert approval.action_id == "connector_evidence_snapshot_export:external_db_operational_mirror"
    assert approval.payload["export_request_id"] == "export_req_connector_evidence_20260627_1000"
    assert row.requested_snapshot_count == 1
    assert row.storage_status == "not_written"


def test_connector_evidence_invariant_snapshot_export_request_replays_idempotently() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(
            snapshot_id="snap_connector_evidence_export_request_match",
            idempotency_key="idem_connector_evidence_snapshot_export_request_match",
        ),
    )
    first = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests",
        json=snapshot_export_request_payload(),
    )
    replay = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests",
        json=snapshot_export_request_payload(),
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["audit_event_id"] == first.json()["audit_event_id"]
    with session_scope(factory) as session:
        events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_snapshot_export.requested",
            limit=10,
        )
    assert len(events) == 1


def test_connector_evidence_invariant_snapshot_export_request_rejects_conflicting_idempotency(
) -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(
            snapshot_id="snap_connector_evidence_export_request_match",
            idempotency_key="idem_connector_evidence_snapshot_export_request_match",
        ),
    )
    first = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests",
        json=snapshot_export_request_payload(),
    )
    conflict = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests",
        json=snapshot_export_request_payload(export_reason="different-review-purpose"),
    )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason"] == "idempotency_conflict"


def test_connector_evidence_invariant_snapshot_export_request_requires_request_scope() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests",
        json=snapshot_export_request_payload(actor_scopes=[]),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["required_scope"] == (
        "connectors:evidence:snapshot:export:request"
    )
    with session_scope(factory) as session:
        export_request_events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_snapshot_export.requested",
            limit=10,
        )
    assert export_request_events == []


def test_connector_evidence_invariant_snapshot_export_request_decision_signals_workflow() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    workflow_runtime = RecordingSnapshotExportWorkflowRuntime()
    app.state.workflow_runtime = workflow_runtime
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(
            snapshot_id="snap_connector_evidence_export_request_match",
            idempotency_key="idem_connector_evidence_snapshot_export_request_match",
        ),
    )
    request_response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests",
        json=snapshot_export_request_payload(),
    )
    response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/"
        "export-requests/export_req_connector_evidence_20260627_1000/decision",
        json=snapshot_export_request_decision_payload(),
    )

    assert request_response.status_code == 201
    assert response.status_code == 201
    body = response.json()
    assert body["export_request"]["status"] == "approval_approved"
    assert body["export_request"]["decision"] == "approve"
    assert body["export_request"]["export_status"] == "approved_not_exported"
    assert body["export_request"]["storage_status"] == "not_written"
    assert body["export_request"]["workflow_signal_status"] == (
        "export_request_signal_requested"
    )
    assert body["workflow_signal"]["signal_name"] == (
        "connector_evidence_snapshot_export_decided"
    )
    assert body["workflow_signal"]["payload"]["export_request_id"] == (
        "export_req_connector_evidence_20260627_1000"
    )
    assert body["workflow_signal"]["payload"]["storage_status"] == "not_written"
    assert body["audit_event_type"] == "connector.evidence_snapshot_export.decision_recorded"
    assert workflow_runtime.requests[0].runtime_payload["approved"] is True
    serialized = str(body).lower()
    assert "private-endpoint://" not in serialized
    assert "vault://" not in serialized
    assert "postgres://" not in serialized
    assert "password" not in serialized
    assert "credential_value" not in serialized

    with session_scope(factory) as session:
        decision_events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_snapshot_export.decision_recorded",
            limit=10,
        )
        row = session.execute(
            text(
                "select status, export_status, storage_status, workflow_signal_status "
                "from connector_evidence_snapshot_export_requests "
                "where tenant_id = :tenant_id and export_request_id = :export_request_id"
            ),
            {
                "tenant_id": "tenant_demo_manufacturing",
                "export_request_id": "export_req_connector_evidence_20260627_1000",
            },
        ).one()
    assert len(decision_events) == 1
    assert decision_events[0].payload["decision"] == "approve"
    assert decision_events[0].payload["export_status"] == "approved_not_exported"
    assert row.status == "approval_approved"
    assert row.export_status == "approved_not_exported"
    assert row.storage_status == "not_written"
    assert row.workflow_signal_status == "export_request_signal_requested"


def test_connector_evidence_invariant_snapshot_export_request_decision_requires_scope() -> None:
    factory = session_factory()
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    app.state.workflow_runtime = RecordingSnapshotExportWorkflowRuntime()
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(
            snapshot_id="snap_connector_evidence_export_request_match",
            idempotency_key="idem_connector_evidence_snapshot_export_request_match",
        ),
    )
    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests",
        json=snapshot_export_request_payload(),
    )
    response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/"
        "export-requests/export_req_connector_evidence_20260627_1000/decision",
        json=snapshot_export_request_decision_payload(actor_scopes=[]),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["required_scope"] == (
        "approvals:connectors:export:decide"
    )
    with session_scope(factory) as session:
        decision_events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_snapshot_export.decision_recorded",
            limit=10,
        )
    assert decision_events == []


def test_connector_evidence_invariant_snapshot_export_materialization_writes_local_artifact(
    tmp_path: Path,
) -> None:
    factory = session_factory()
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            connector_export_object_store_root=str(tmp_path),
        )
    )
    app.state.session_factory = factory
    app.state.workflow_runtime = RecordingSnapshotExportWorkflowRuntime()
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(
            snapshot_id="snap_connector_evidence_export_request_match",
            idempotency_key="idem_connector_evidence_snapshot_export_request_match",
        ),
    )
    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests",
        json=snapshot_export_request_payload(),
    )
    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/"
        "export-requests/export_req_connector_evidence_20260627_1000/decision",
        json=snapshot_export_request_decision_payload(),
    )
    response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/"
        "export-requests/export_req_connector_evidence_20260627_1000/materializations",
        json=snapshot_export_materialization_payload(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["export_request_id"] == "export_req_connector_evidence_20260627_1000"
    assert body["materialization_id"] == "mat_connector_evidence_export_20260627_1000"
    assert body["status"] == "materialized"
    assert body["export_status"] == "materialized"
    assert body["storage_status"] == "written_local_object_store"
    assert body["storage_adapter"] == "local_filesystem"
    assert body["storage_uri"].startswith("axis-local-object-store://")
    assert body["storage_key"].endswith(".json")
    assert ".." not in body["storage_key"]
    assert len(body["artifact_checksum_sha256"]) == 64
    assert body["artifact_size_bytes"] > 0
    assert body["export_request"]["storage_status"] == "written_local_object_store"
    assert body["export_request"]["export_status"] == "materialized"
    assert body["audit_event_type"] == "connector.evidence_snapshot_export.materialized"
    artifact_path = tmp_path / body["storage_key"]
    assert artifact_path.exists()
    artifact_payload = artifact_path.read_text(encoding="utf-8")
    assert "connector-evidence-snapshot-export" in artifact_payload
    serialized = str(body).lower() + artifact_payload.lower()
    assert "private-endpoint://" not in serialized
    assert "vault://" not in serialized
    assert "postgres://" not in serialized
    assert "password" not in serialized
    assert "credential_value" not in serialized

    with session_scope(factory) as session:
        events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_snapshot_export.materialized",
            limit=10,
        )
        row = session.execute(
            text(
                "select export_status, storage_status, storage_key, "
                "artifact_checksum_sha256 "
                "from connector_evidence_snapshot_export_requests "
                "where tenant_id = :tenant_id and export_request_id = :export_request_id"
            ),
            {
                "tenant_id": "tenant_demo_manufacturing",
                "export_request_id": "export_req_connector_evidence_20260627_1000",
            },
        ).one()
    assert len(events) == 1
    assert events[0].payload["storage_status"] == "written_local_object_store"
    assert events[0].payload["storage_uri"].startswith("axis-local-object-store://")
    assert row.export_status == "materialized"
    assert row.storage_status == "written_local_object_store"
    assert row.storage_key == body["storage_key"]
    assert row.artifact_checksum_sha256 == body["artifact_checksum_sha256"]


def test_connector_evidence_invariant_snapshot_export_materialization_requires_approval(
    tmp_path: Path,
) -> None:
    factory = session_factory()
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            connector_export_object_store_root=str(tmp_path),
        )
    )
    app.state.session_factory = factory
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(
            snapshot_id="snap_connector_evidence_export_request_match",
            idempotency_key="idem_connector_evidence_snapshot_export_request_match",
        ),
    )
    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests",
        json=snapshot_export_request_payload(),
    )
    response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/"
        "export-requests/export_req_connector_evidence_20260627_1000/materializations",
        json=snapshot_export_materialization_payload(),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "export_request_not_approved"
    assert list(tmp_path.rglob("*.json")) == []


def test_connector_evidence_invariant_snapshot_export_materialization_requires_scope(
    tmp_path: Path,
) -> None:
    factory = session_factory()
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            connector_export_object_store_root=str(tmp_path),
        )
    )
    app.state.session_factory = factory
    app.state.workflow_runtime = RecordingSnapshotExportWorkflowRuntime()
    with session_scope(factory) as session:
        seed_mismatched_connector_evidence(AxisPersistenceRepository(session))
    client = TestClient(app)

    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots",
        json=snapshot_payload(
            snapshot_id="snap_connector_evidence_export_request_match",
            idempotency_key="idem_connector_evidence_snapshot_export_request_match",
        ),
    )
    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests",
        json=snapshot_export_request_payload(),
    )
    client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/"
        "export-requests/export_req_connector_evidence_20260627_1000/decision",
        json=snapshot_export_request_decision_payload(),
    )
    response = client.post(
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/"
        "export-requests/export_req_connector_evidence_20260627_1000/materializations",
        json=snapshot_export_materialization_payload(actor_scopes=[]),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["required_scope"] == (
        "connectors:evidence:snapshot:export:materialize"
    )
    assert list(tmp_path.rglob("*.json")) == []
    with session_scope(factory) as session:
        events = AxisPersistenceRepository(session).list_audit_events(
            tenant_id="tenant_demo_manufacturing",
            event_type="connector.evidence_snapshot_export.materialized",
            limit=10,
        )
    assert events == []


def test_openapi_exposes_connector_evidence_invariants_endpoint() -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))

    paths = app.openapi()["paths"]
    report_path = paths["/demo/manufacturing/connectors/evidence-invariants"]
    snapshot_path = paths["/demo/manufacturing/connectors/evidence-invariants/snapshots"]
    snapshot_export_path = paths[
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export"
    ]
    snapshot_export_request_path = paths[
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/export-requests"
    ]
    snapshot_export_request_decision_path = paths[
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/"
        "export-requests/{export_request_id}/decision"
    ]
    snapshot_export_request_materialization_path = paths[
        "/demo/manufacturing/connectors/evidence-invariants/snapshots/"
        "export-requests/{export_request_id}/materializations"
    ]

    assert "get" in report_path
    assert (
        report_path["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ManufacturingConnectorEvidenceInvariantReport"
    )
    assert "post" in snapshot_path
    assert "get" in snapshot_path
    assert (
        snapshot_path["post"]["responses"]["201"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ConnectorEvidenceInvariantSnapshotRecord"
    )
    assert (
        snapshot_path["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ConnectorEvidenceInvariantSnapshotHistory"
    )
    assert "get" in snapshot_export_path
    assert (
        snapshot_export_path["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/ConnectorEvidenceInvariantSnapshotExportBundle"
    )
    assert "post" in snapshot_export_request_path
    assert (
        snapshot_export_request_path["post"]["responses"]["201"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/ConnectorEvidenceInvariantSnapshotExportRequestRecord"
    )
    assert "post" in snapshot_export_request_decision_path
    assert (
        snapshot_export_request_decision_path["post"]["responses"]["201"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/ConnectorEvidenceInvariantSnapshotExportDecisionResult"
    )
    assert "post" in snapshot_export_request_materialization_path
    assert (
        snapshot_export_request_materialization_path["post"]["responses"]["201"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/ConnectorEvidenceInvariantSnapshotExportMaterializationResult"
    )
