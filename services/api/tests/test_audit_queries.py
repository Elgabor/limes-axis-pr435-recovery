from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.audit_queries import (
    AuditEventQuery,
    AuditExportQuery,
    AuditExportWormEnforcementError,
    AuditLegalHoldCreateRequest,
    AuditLegalHoldPermissionDenied,
    AuditLegalHoldReleaseRequest,
    AuditObjectLegalHoldRequest,
    AuditRetentionDeletionRequest,
    apply_object_legal_hold,
    create_audit_legal_hold,
    execute_audit_retention_deletion,
    export_persisted_audit_events,
    query_persisted_audit_events,
    release_audit_legal_hold,
    release_object_legal_hold,
)
from axis_api.audit_signing import (
    SelfHostedAuditLedgerSigner,
    verify_audit_ledger_signature,
)
from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.identity import OidcPrincipal
from axis_api.main import connector_export_object_store, create_app
from axis_api.models import AuditEvent, Base
from axis_api.object_storage import ObjectLockCapability
from axis_api.persistence import AxisPersistenceRepository, TenantCreate


class StaticIdentityVerifier:
    def __init__(self, principal: OidcPrincipal) -> None:
        self.principal = principal

    def verify_authorization_header(self, authorization: str | None) -> OidcPrincipal:
        assert authorization == "Bearer valid-token"
        return self.principal


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).create_tenant(
            TenantCreate(
                tenant_id="tenant_demo_manufacturing",
                display_name="Ravenna Works",
                description="Plant Operations Cockpit",
                created_by="test",
            )
        )
    yield factory
    engine.dispose()


def seed_audit_events(repository: AxisPersistenceRepository) -> None:
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="agent_supply_risk",
            event_type="action.proposal.created",
            payload={
                "action_id": "request_supplier_expedite",
                "action_run_id": "act_run_supply_1",
                "workflow_id": "wf_supplier_delay_review",
                "approval_id": "appr_expedite_supplier_batch",
                "status": "approval_required",
                "execution_mode": "approval_gated_dry_run",
                "risk_level": "high",
                "approval_required": True,
                "permission_decision": {"allowed": True, "reason": "allowed"},
                "payload_field_names": ["supplier_batch_id", "target_arrival"],
                "credential_secret": "never-export-this-value",
            },
        )
    )
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="plant-operations-owner-role",
            event_type="approval.decision.recorded",
            payload={
                "approval_id": "appr_expedite_supplier_batch",
                "workflow_id": "wf_supplier_delay_review",
                "action_id": "request_supplier_expedite",
                "decision": "approve",
                "required_permission": "approvals:supply:decide",
                "permission_decision": {"allowed": True, "reason": "allowed"},
                "workflow_signal": {
                    "status": "approval_signaled",
                    "adapter": "axis-temporal-adapter",
                },
            },
        )
    )
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_other",
            actor_id="other-actor",
            event_type="approval.decision.recorded",
            payload={"approval_id": "appr_other", "decision": "approve"},
        )
    )


def seed_retention_window_events(repository: AxisPersistenceRepository) -> None:
    current_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="plant-operations-owner-role",
            event_type="approval.decision.recorded",
            payload={
                "approval_id": "appr_recent",
                "workflow_id": "wf_recent_quality_hold",
                "decision": "approve",
                "required_permission": "approvals:quality:decide",
            },
        )
    )
    current_event.created_at = datetime.now(UTC) - timedelta(days=3)

    expired_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="agent_quality_risk",
            event_type="action.proposal.created",
            payload={
                "action_id": "hold_quality_batch",
                "workflow_id": "wf_expired_quality_hold",
                "approval_id": "appr_expired",
                "status": "approval_required",
                "approval_required": True,
            },
        )
    )
    expired_event.created_at = datetime.now(UTC) - timedelta(days=90)


def test_query_persisted_audit_events_maps_records_to_public_explorer(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_audit_events(repository)
        explorer = query_persisted_audit_events(
            repository,
            AuditEventQuery(tenant_id="tenant_demo_manufacturing"),
        )

    assert explorer.tenant_id == "tenant_demo_manufacturing"
    assert explorer.ledger_status == "ready"
    assert explorer.metrics[0].label == "Persisted Events"
    assert explorer.metrics[0].value == "2"
    assert len(explorer.events) == 2
    assert {event.tenant_id for event in explorer.events} == {"tenant_demo_manufacturing"}
    assert "approval.decision.recorded" in explorer.filter_options.event_types
    assert "agent_supply_risk" in explorer.filter_options.actors
    assert "wf_supplier_delay_review" in explorer.filter_options.scopes
    first = explorer.events[0]
    assert first.audit_event_id
    assert first.data_classification == "public-demo"
    assert first.payload_preview
    assert "password" not in explorer.model_dump_json().lower()
    assert "secret" not in explorer.model_dump_json().lower()


def test_query_persisted_audit_events_exposes_connector_snapshot_link_fields(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.append_audit_event(
            AuditEventCreate(
                tenant_id="tenant_demo_manufacturing",
                actor_id="connector-security-reviewer-role",
                event_type="connector.evidence_invariants.snapshot_persisted",
                payload={
                    "snapshot_id": "snap_connector_evidence_20260627_1000",
                    "connector_id": "external_db_operational_mirror",
                    "idempotency_key": "idem_connector_evidence_snapshot_20260627_1000",
                    "report_digest_sha256": "a" * 64,
                    "subject_ids": ["chk_evidence_report_1"],
                    "credential_secret": "never-export-this-value",
                },
            )
        )
        explorer = query_persisted_audit_events(
            repository,
            AuditEventQuery(
                tenant_id="tenant_demo_manufacturing",
                event_type="connector.evidence_invariants.snapshot_persisted",
            ),
        )

    assert len(explorer.events) == 1
    event = explorer.events[0]
    assert event.payload_preview["snapshot_id"] == "snap_connector_evidence_20260627_1000"
    assert event.payload_preview["connector_id"] == "external_db_operational_mirror"
    assert event.payload_preview["idempotency_key"] == (
        "idem_connector_evidence_snapshot_20260627_1000"
    )
    assert "report_digest_sha256" not in event.payload_preview
    assert "credential_secret" not in event.payload_preview
    assert "never-export-this-value" not in explorer.model_dump_json()


def test_query_persisted_audit_events_filters_by_event_actor_and_scope(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_audit_events(repository)
        by_event = query_persisted_audit_events(
            repository,
            AuditEventQuery(
                tenant_id="tenant_demo_manufacturing",
                event_type="action.proposal.created",
            ),
        )
        by_actor = query_persisted_audit_events(
            repository,
            AuditEventQuery(
                tenant_id="tenant_demo_manufacturing",
                actor_id="plant-operations-owner-role",
            ),
        )
        by_scope = query_persisted_audit_events(
            repository,
            AuditEventQuery(
                tenant_id="tenant_demo_manufacturing",
                scope="wf_supplier_delay_review",
            ),
        )
        empty = query_persisted_audit_events(
            repository,
            AuditEventQuery(
                tenant_id="tenant_demo_manufacturing",
                scope="missing-scope",
            ),
        )

    assert [event.event_type for event in by_event.events] == ["action.proposal.created"]
    assert [event.actor_id for event in by_actor.events] == ["plant-operations-owner-role"]
    assert len(by_scope.events) == 2
    assert empty.events == []
    assert empty.filter_options.tenants == ["tenant_demo_manufacturing"]


def test_persisted_audit_events_endpoint_returns_tenant_scoped_query(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_audit_events(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/audit/events",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "event_type": "approval.decision.recorded",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["provenance"] == "live"
    assert body["metrics"][0]["value"] == "1"
    assert body["events"][0]["event_type"] == "approval.decision.recorded"
    assert body["events"][0]["related_approval_id"] == "appr_expedite_supplier_batch"
    assert "tenant_other" not in str(body)


def test_persisted_audit_events_endpoint_returns_empty_result_for_empty_query(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/audit/events",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provenance"] == "empty"
    assert body["events"] == []
    assert body["filter_options"]["tenants"] == ["tenant_demo_manufacturing"]
    assert body["ledger_status"] == "watch"


def test_persisted_audit_events_uses_non_demo_tenant_metadata_when_empty(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        AxisPersistenceRepository(session).create_tenant(
            TenantCreate(
                tenant_id="tenant_customer_audit",
                display_name="Turin Operations",
                description="",
                created_by="test",
            )
        )
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    response = TestClient(app).get(
        "/demo/manufacturing/audit/events",
        params={"tenant_id": "tenant_customer_audit"},
    )

    assert response.status_code == 200
    assert response.json()["plant_name"] == "Turin Operations"
    assert response.json()["scenario"] is None
    assert response.json()["provenance"] == "empty"
    assert response.json()["events"] == []
    assert "Ravenna" not in response.text


def test_persisted_audit_events_reports_unknown_tenant(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    response = TestClient(app).get(
        "/demo/manufacturing/audit/events",
        params={"tenant_id": "tenant_unknown"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "TENANT_NOT_FOUND"


def test_persisted_audit_events_endpoint_requires_oidc_when_configured(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/audit/events",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_persisted_audit_events_endpoint_requires_audit_read_scope_when_oidc_configured(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="plant-operations-owner-role",
            tenant_id="tenant_demo_manufacturing",
            scopes=["workflows:read"],
        )
    )
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/audit/events",
        headers={"Authorization": "Bearer valid-token"},
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "PERMISSION_DENIED",
        "message": "The actor cannot read persisted audit events.",
        "required_permission": "audit:read",
        "reason": "missing_required_scope",
        "permission_reason": "missing_scope:audit:read",
    }


def test_persisted_audit_events_endpoint_rejects_oidc_tenant_mismatch(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="plant-operations-owner-role",
            tenant_id="tenant_other",
            scopes=["audit:read"],
        )
    )
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/audit/events",
        headers={"Authorization": "Bearer valid-token"},
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "tenant_mismatch"


def test_persisted_audit_events_endpoint_binds_read_scope_from_oidc_token(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="plant-operations-owner-role",
            tenant_id="tenant_demo_manufacturing",
            scopes=["audit:read"],
        )
    )
    with session_scope(session_factory) as session:
        seed_audit_events(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/audit/events",
        headers={"Authorization": "Bearer valid-token"},
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert len(body["events"]) == 2
    assert "tenant_other" not in str(body)


def test_openapi_exposes_persisted_audit_events_endpoint() -> None:
    client = TestClient(create_app())
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/demo/manufacturing/audit/events" in response.json()["paths"]


def test_export_persisted_audit_events_returns_manifest_and_retention_controls(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_audit_events(repository)
        export = export_persisted_audit_events(
            repository,
            AuditExportQuery(
                tenant_id="tenant_demo_manufacturing",
                export_reason="security-review",
            ),
        )

    assert export.tenant_id == "tenant_demo_manufacturing"
    assert export.format == "json"
    assert export.export_reason == "security-review"
    assert export.manifest.tenant_id == "tenant_demo_manufacturing"
    assert export.manifest.record_count == 2
    assert export.manifest.redaction_policy == "payload-preview-only"
    assert export.retention_policy.policy_id == "axis-demo-audit-standard"
    assert export.retention_policy.retention_days == 365
    assert export.retention_policy.legal_hold is False
    assert export.retention_policy.export_requires_review is True
    assert len(export.events) == 2
    assert {event.tenant_id for event in export.events} == {"tenant_demo_manufacturing"}
    assert "tenant_other" not in export.model_dump_json()
    assert "credential_secret" not in export.model_dump_json()
    assert "never-export-this-value" not in export.model_dump_json()


def test_export_persisted_audit_events_enforces_retention_window(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_retention_window_events(repository)
        export = export_persisted_audit_events(
            repository,
            AuditExportQuery(
                tenant_id="tenant_demo_manufacturing",
                retention_days=30,
                export_reason="retention-review",
            ),
        )

    assert export.manifest.record_count == 1
    assert export.manifest.retention_enforced is True
    assert export.manifest.excluded_record_count == 1
    assert export.retention_policy.disposal_action == "enforced_exclusion"
    assert [event.related_workflow_id for event in export.events] == [
        "wf_recent_quality_hold"
    ]
    assert "wf_expired_quality_hold" not in export.model_dump_json()
    assert any("excluded 1 expired event" in note for note in export.retention_notes)


def test_export_persisted_audit_events_preserves_expired_events_under_legal_hold(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_retention_window_events(repository)
        export = export_persisted_audit_events(
            repository,
            AuditExportQuery(
                tenant_id="tenant_demo_manufacturing",
                retention_days=30,
                legal_hold=True,
                export_reason="legal-hold-review",
            ),
        )

    assert export.manifest.record_count == 2
    assert export.manifest.retention_enforced is False
    assert export.manifest.excluded_record_count == 0
    assert export.retention_policy.legal_hold is True
    assert export.retention_policy.disposal_action == "retain_legal_hold"
    assert {event.related_workflow_id for event in export.events} == {
        "wf_recent_quality_hold",
        "wf_expired_quality_hold",
    }
    assert any("legal hold" in note.lower() for note in export.retention_notes)


def test_audit_retention_deletion_dry_run_keeps_expired_events(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_retention_window_events(repository)
        result = execute_audit_retention_deletion(
            repository,
            AuditRetentionDeletionRequest(
                tenant_id="tenant_demo_manufacturing",
                actor_id="audit-retention-operator",
                actor_scopes=["audit:retention:delete"],
                retention_days=30,
                dry_run=True,
            ),
        )

    with session_factory() as session:
        events = list(session.scalars(select(AuditEvent)))

    assert result.status == "dry_run"
    assert result.candidate_count == 1
    assert result.deleted_count == 0
    assert result.audit_event_id is None
    assert len(events) == 2


def test_audit_retention_deletion_blocks_physical_delete_under_legal_hold(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_retention_window_events(repository)
        result = execute_audit_retention_deletion(
            repository,
            AuditRetentionDeletionRequest(
                tenant_id="tenant_demo_manufacturing",
                actor_id="audit-retention-operator",
                actor_scopes=["audit:retention:delete"],
                retention_days=30,
                legal_hold=True,
                dry_run=False,
            ),
        )

    with session_factory() as session:
        events = list(session.scalars(select(AuditEvent)))

    assert result.status == "blocked_legal_hold"
    assert result.candidate_count == 1
    assert result.deleted_count == 0
    assert len(events) == 2


def test_audit_retention_deletion_blocks_matching_persisted_legal_hold(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_retention_window_events(repository)
        hold = create_audit_legal_hold(
            repository,
            AuditLegalHoldCreateRequest(
                tenant_id="tenant_demo_manufacturing",
                hold_id="hold-quality-proposals",
                actor_id="legal-ops-controller",
                actor_scopes=["audit:legal_hold:write"],
                reason="Litigation hold for quality proposal evidence.",
                event_type="action.proposal.created",
                approved_by="legal-reviewer-role",
            ),
        )
        result = execute_audit_retention_deletion(
            repository,
            AuditRetentionDeletionRequest(
                tenant_id="tenant_demo_manufacturing",
                actor_id="audit-retention-operator",
                actor_scopes=["audit:retention:delete"],
                retention_days=30,
                dry_run=False,
                event_type="action.proposal.created",
            ),
        )

    with session_factory() as session:
        events = list(session.scalars(select(AuditEvent)))

    assert hold.status == "active"
    assert hold.audit_event_type == "audit.legal_hold.activated"
    assert result.status == "blocked_legal_hold"
    assert result.legal_hold is True
    assert result.candidate_count == 1
    assert result.deleted_count == 0
    assert any("hold-quality-proposals" in note for note in result.notes)
    assert {event.event_type for event in events} == {
        "approval.decision.recorded",
        "action.proposal.created",
        "audit.legal_hold.activated",
    }


def test_audit_retention_deletion_executes_after_persisted_legal_hold_release(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_retention_window_events(repository)
        create_audit_legal_hold(
            repository,
            AuditLegalHoldCreateRequest(
                tenant_id="tenant_demo_manufacturing",
                hold_id="hold-release-quality-proposals",
                actor_id="legal-ops-controller",
                actor_scopes=["audit:legal_hold:write"],
                reason="Temporary legal hold for quality proposal evidence.",
                event_type="action.proposal.created",
                approved_by="legal-reviewer-role",
            ),
        )
        release = release_audit_legal_hold(
            repository,
            AuditLegalHoldReleaseRequest(
                tenant_id="tenant_demo_manufacturing",
                hold_id="hold-release-quality-proposals",
                actor_id="legal-ops-controller",
                actor_scopes=["audit:legal_hold:write"],
                release_reason="Legal review completed.",
            ),
        )
        result = execute_audit_retention_deletion(
            repository,
            AuditRetentionDeletionRequest(
                tenant_id="tenant_demo_manufacturing",
                actor_id="audit-retention-operator",
                actor_scopes=["audit:retention:delete"],
                retention_days=30,
                dry_run=False,
                event_type="action.proposal.created",
            ),
        )

    with session_factory() as session:
        events = list(session.scalars(select(AuditEvent)))

    assert release.status == "released"
    assert release.release_audit_event_type == "audit.legal_hold.released"
    assert result.status == "executed"
    assert result.deleted_count == 1
    assert {event.event_type for event in events} == {
        "approval.decision.recorded",
        "audit.legal_hold.activated",
        "audit.legal_hold.released",
        "audit.retention_deletion.executed",
    }


def test_audit_retention_deletion_removes_only_expired_tenant_events_and_records_evidence(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_retention_window_events(repository)
        other_tenant_expired = repository.append_audit_event(
            AuditEventCreate(
                tenant_id="tenant_other",
                actor_id="other-actor",
                event_type="action.proposal.created",
                payload={"workflow_id": "wf_other"},
            )
        )
        other_tenant_expired.created_at = datetime.now(UTC) - timedelta(days=90)
        result = execute_audit_retention_deletion(
            repository,
            AuditRetentionDeletionRequest(
                tenant_id="tenant_demo_manufacturing",
                actor_id="audit-retention-operator",
                actor_scopes=["audit:retention:delete"],
                retention_days=30,
                dry_run=False,
                reason="scheduled-retention-window",
            ),
        )

    with session_factory() as session:
        events = list(session.scalars(select(AuditEvent).order_by(AuditEvent.created_at.asc())))

    assert result.status == "executed"
    assert result.candidate_count == 1
    assert result.deleted_count == 1
    assert len(result.deleted_event_hashes) == 1
    assert result.audit_event_type == "audit.retention_deletion.executed"
    assert {event.tenant_id for event in events} == {
        "tenant_demo_manufacturing",
        "tenant_other",
    }
    assert {event.event_type for event in events} == {
        "approval.decision.recorded",
        "action.proposal.created",
        "audit.retention_deletion.executed",
    }
    evidence = [
        event for event in events if event.event_type == "audit.retention_deletion.executed"
    ][0]
    assert evidence.payload["deleted_count"] == 1
    assert evidence.payload["raw_payload_exported"] is False
    assert "wf_expired_quality_hold" not in str(evidence.payload)


def test_audit_retention_deletion_endpoint_denies_missing_scope(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/audit/retention/delete",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "actor_id": "audit-retention-operator",
            "actor_scopes": ["audit:read"],
            "retention_days": 30,
            "dry_run": True,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["required_permissions"] == [
        "audit:retention:delete"
    ]


def test_audit_retention_deletion_endpoint_requires_oidc_when_configured(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/audit/retention/delete",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "actor_id": "audit-retention-operator",
            "actor_scopes": ["audit:retention:delete"],
            "retention_days": 30,
            "dry_run": True,
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_audit_retention_deletion_endpoint_binds_actor_and_scopes_from_oidc_token(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="audit-retention-operator",
            tenant_id="tenant_demo_manufacturing",
            scopes=["audit:retention:delete"],
        )
    )
    with session_scope(session_factory) as session:
        seed_retention_window_events(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/audit/retention/delete",
        headers={"Authorization": "Bearer valid-token"},
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "actor_id": "audit-retention-operator",
            "actor_scopes": [],
            "retention_days": 30,
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "executed"
    assert body["permission_decision"] == {"allowed": True, "reason": "allowed"}
    with session_factory() as session:
        audit_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "audit.retention_deletion.executed"
            )
        ).one()
    assert audit_event.actor_id == "audit-retention-operator"


def test_audit_retention_deletion_endpoint_rejects_oidc_actor_impersonation(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="audit-retention-operator",
            tenant_id="tenant_demo_manufacturing",
            scopes=["audit:retention:delete"],
        )
    )
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/audit/retention/delete",
        headers={"Authorization": "Bearer valid-token"},
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "actor_id": "other-actor",
            "actor_scopes": ["audit:retention:delete"],
            "retention_days": 30,
            "dry_run": True,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "actor_mismatch"


def test_audit_retention_deletion_endpoint_rejects_oidc_tenant_mismatch(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="audit-retention-operator",
            tenant_id="tenant_demo_manufacturing",
            scopes=["audit:retention:delete"],
        )
    )
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/audit/retention/delete",
        headers={"Authorization": "Bearer valid-token"},
        json={
            "tenant_id": "tenant_other",
            "actor_id": "audit-retention-operator",
            "actor_scopes": ["audit:retention:delete"],
            "retention_days": 30,
            "dry_run": True,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "tenant_mismatch"


def test_audit_retention_deletion_endpoint_executes_dry_run(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_retention_window_events(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/audit/retention/delete",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "actor_id": "audit-retention-operator",
            "actor_scopes": ["audit:retention:delete"],
            "retention_days": 30,
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dry_run"
    assert body["candidate_count"] == 1
    assert body["deleted_count"] == 0


def test_audit_export_endpoint_requires_audit_read_scope_when_oidc_configured(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="plant-operations-owner-role",
            tenant_id="tenant_demo_manufacturing",
            scopes=["workflows:read"],
        )
    )
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/audit/export",
        headers={"Authorization": "Bearer valid-token"},
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["required_permission"] == "audit:read"


def test_audit_export_endpoint_binds_tenant_to_oidc_principal(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="plant-operations-owner-role",
            tenant_id="tenant_demo_manufacturing",
            scopes=["audit:read"],
        )
    )
    with session_scope(session_factory) as session:
        seed_audit_events(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/audit/export",
        headers={"Authorization": "Bearer valid-token"},
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert {event["tenant_id"] for event in body["events"]} == {
        "tenant_demo_manufacturing"
    }


def test_audit_legal_hold_endpoint_creates_lists_and_releases_hold(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    create_response = client.post(
        "/demo/manufacturing/audit/legal-holds",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "hold_id": "hold-api-quality-proposals",
            "actor_id": "legal-ops-controller",
            "actor_scopes": ["audit:legal_hold:write"],
            "reason": "Regulatory review hold.",
            "event_type": "action.proposal.created",
            "approved_by": "legal-reviewer-role",
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["status"] == "active"
    assert created["audit_event_type"] == "audit.legal_hold.activated"

    list_response = client.get(
        "/demo/manufacturing/audit/legal-holds",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )
    assert list_response.status_code == 200
    assert [hold["hold_id"] for hold in list_response.json()] == [
        "hold-api-quality-proposals"
    ]

    release_response = client.post(
        "/demo/manufacturing/audit/legal-holds/hold-api-quality-proposals/release",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "hold_id": "hold-api-quality-proposals",
            "actor_id": "legal-ops-controller",
            "actor_scopes": ["audit:legal_hold:write"],
            "release_reason": "Regulatory review completed.",
        },
    )

    assert release_response.status_code == 200
    released = release_response.json()
    assert released["status"] == "released"
    assert released["release_audit_event_type"] == "audit.legal_hold.released"

    active_response = client.get(
        "/demo/manufacturing/audit/legal-holds",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )
    assert active_response.status_code == 200
    assert active_response.json() == []


def test_audit_legal_hold_endpoint_denies_missing_write_scope(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/audit/legal-holds",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "hold_id": "hold-denied",
            "actor_id": "legal-ops-controller",
            "actor_scopes": ["audit:read"],
            "reason": "Regulatory review hold.",
            "approved_by": "legal-reviewer-role",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["required_permissions"] == [
        "audit:legal_hold:write"
    ]


def test_audit_legal_hold_endpoints_require_oidc_when_configured(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    client = TestClient(app)

    list_response = client.get("/demo/manufacturing/audit/legal-holds")
    create_response = client.post(
        "/demo/manufacturing/audit/legal-holds",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "hold_id": "hold-requires-oidc",
            "actor_id": "legal-ops-controller",
            "actor_scopes": ["audit:legal_hold:write"],
            "reason": "Regulatory review hold.",
            "approved_by": "legal-reviewer-role",
        },
    )

    assert list_response.status_code == 401
    assert create_response.status_code == 401


def test_audit_legal_hold_list_requires_write_scope_when_oidc_configured(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="legal-ops-controller",
            tenant_id="tenant_demo_manufacturing",
            scopes=["audit:read"],
        )
    )
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/audit/legal-holds",
        headers={"Authorization": "Bearer valid-token"},
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "PERMISSION_DENIED",
        "message": "The actor cannot read audit legal holds.",
        "required_permission": "audit:legal_hold:write",
        "reason": "missing_required_scope",
        "permission_reason": "missing_scope:audit:legal_hold:write",
    }


def test_audit_legal_hold_list_rejects_oidc_tenant_mismatch(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="legal-ops-controller",
            tenant_id="tenant_other",
            scopes=["audit:legal_hold:write"],
        )
    )
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/audit/legal-holds",
        headers={"Authorization": "Bearer valid-token"},
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "tenant_mismatch"


def test_audit_legal_hold_endpoint_binds_actor_and_scopes_from_oidc_token(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="legal-ops-controller",
            tenant_id="tenant_demo_manufacturing",
            scopes=["audit:legal_hold:write"],
        )
    )
    client = TestClient(app)

    create_response = client.post(
        "/demo/manufacturing/audit/legal-holds",
        headers={"Authorization": "Bearer valid-token"},
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "hold_id": "hold-oidc-bound",
            "actor_id": "legal-ops-controller",
            "actor_scopes": [],
            "reason": "Regulatory review hold.",
            "approved_by": "legal-reviewer-role",
        },
    )
    release_response = client.post(
        "/demo/manufacturing/audit/legal-holds/hold-oidc-bound/release",
        headers={"Authorization": "Bearer valid-token"},
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "hold_id": "hold-oidc-bound",
            "actor_id": "legal-ops-controller",
            "actor_scopes": [],
            "release_reason": "Regulatory review completed.",
        },
    )

    assert create_response.status_code == 201
    assert release_response.status_code == 200
    with session_factory() as session:
        events = session.scalars(select(AuditEvent).order_by(AuditEvent.event_type)).all()
    assert {event.actor_id for event in events} == {"legal-ops-controller"}
    assert {event.event_type for event in events} == {
        "audit.legal_hold.activated",
        "audit.legal_hold.released",
    }


def test_audit_legal_hold_endpoint_rejects_oidc_actor_impersonation(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="legal-ops-controller",
            tenant_id="tenant_demo_manufacturing",
            scopes=["audit:legal_hold:write"],
        )
    )
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/audit/legal-holds",
        headers={"Authorization": "Bearer valid-token"},
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "hold_id": "hold-impersonation",
            "actor_id": "other-actor",
            "actor_scopes": ["audit:legal_hold:write"],
            "reason": "Regulatory review hold.",
            "approved_by": "legal-reviewer-role",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "actor_mismatch"


def test_export_persisted_audit_events_includes_hash_chain_integrity_proof(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_audit_events(repository)
        export = export_persisted_audit_events(
            repository,
            AuditExportQuery(tenant_id="tenant_demo_manufacturing"),
        )

    assert export.integrity_proof.algorithm == "sha256-hash-chain-v1"
    assert export.integrity_proof.verification_status == "verified"
    assert export.integrity_proof.record_count == export.manifest.record_count
    assert len(export.integrity_proof.chain_tip_sha256) == 64
    assert len(export.integrity_proof.event_hashes) == export.manifest.record_count
    assert export.manifest.integrity_chain_tip_sha256 == (
        export.integrity_proof.chain_tip_sha256
    )


def test_export_persisted_audit_events_includes_verifiable_ledger_signature(
    session_factory: sessionmaker[Session],
) -> None:
    signer = SelfHostedAuditLedgerSigner(
        key_id="axis-local-test-key",
        secret_key="local-test-signing-secret",
    )
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_audit_events(repository)
        export = export_persisted_audit_events(
            repository,
            AuditExportQuery(tenant_id="tenant_demo_manufacturing"),
            ledger_signer=signer,
        )

    assert export.ledger_signature.algorithm == "hmac-sha256"
    assert export.ledger_signature.key_id == "axis-local-test-key"
    assert export.ledger_signature.verification_status == "verified"
    assert export.ledger_signature.signature
    assert len(export.ledger_signature.signed_payload_sha256) == 64
    assert verify_audit_ledger_signature(
        export.manifest,
        export.integrity_proof,
        export.ledger_signature,
        secret_key="local-test-signing-secret",
    )

    tampered_manifest = export.manifest.model_copy(
        update={"checksum_sha256": "0" * 64}
    )
    assert not verify_audit_ledger_signature(
        tampered_manifest,
        export.integrity_proof,
        export.ledger_signature,
        secret_key="local-test-signing-secret",
    )


def test_export_persisted_audit_events_applies_event_actor_scope_and_limit_filters(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_audit_events(repository)
        export = export_persisted_audit_events(
            repository,
            AuditExportQuery(
                tenant_id="tenant_demo_manufacturing",
                event_type="approval.decision.recorded",
                actor_id="plant-operations-owner-role",
                scope="wf_supplier_delay_review",
                limit=1,
            ),
        )

    assert export.manifest.record_count == 1
    assert export.filters.event_type == "approval.decision.recorded"
    assert export.filters.actor_id == "plant-operations-owner-role"
    assert export.filters.scope == "wf_supplier_delay_review"
    assert export.filters.limit == 1
    assert [event.event_type for event in export.events] == ["approval.decision.recorded"]


def test_persisted_audit_export_endpoint_returns_tenant_scoped_redacted_bundle(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_audit_events(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/audit/export",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "event_type": "action.proposal.created",
            "export_reason": "incident-review",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["export_reason"] == "incident-review"
    assert body["manifest"]["record_count"] == 1
    assert body["retention_policy"]["retention_days"] == 365
    assert body["events"][0]["event_type"] == "action.proposal.created"
    assert "tenant_other" not in str(body)
    assert "credential_secret" not in str(body)
    assert "never-export-this-value" not in str(body)


def test_persisted_audit_export_endpoint_uses_configured_ledger_signer(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            audit_ledger_signing_key_id="axis-api-test-key",
            audit_ledger_signing_secret="api-test-signing-secret",
        )
    )
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_audit_events(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.get("/demo/manufacturing/audit/export")

    assert response.status_code == 200
    body = response.json()
    assert body["ledger_signature"]["algorithm"] == "hmac-sha256"
    assert body["ledger_signature"]["key_id"] == "axis-api-test-key"
    assert body["ledger_signature"]["verification_status"] == "verified"
    assert "api-test-signing-secret" not in str(body)


def test_openapi_exposes_persisted_audit_export_endpoint() -> None:
    client = TestClient(create_app())
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/demo/manufacturing/audit/export" in response.json()["paths"]


# --- Object-store WORM / object-lock enforcement -------------------------------


def _worm_capability(*, enforceable: bool) -> ObjectLockCapability:
    return ObjectLockCapability(
        adapter="s3_compatible",
        checked=True,
        bucket_object_lock_enabled=enforceable,
        default_retention_mode="COMPLIANCE" if enforceable else None,
        compliance_enforceable=enforceable,
        reason="enabled" if enforceable else "bucket_object_lock_probe_failed",
    )


def test_export_marks_worm_enforced_when_object_lock_verified(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_audit_events(repository)
        export = export_persisted_audit_events(
            repository,
            AuditExportQuery(
                tenant_id="tenant_demo_manufacturing",
                retention_days=365,
            ),
            object_lock_capability=_worm_capability(enforceable=True),
            require_worm_compliance=True,
        )

    assert export.manifest.worm_retention_enforced is True
    assert export.manifest.worm_retention_mode == "COMPLIANCE"
    # The export-response path attests capability; it does not itself lock the
    # returned payload under object-lock.
    assert export.manifest.worm_status == "capability_attested"
    # RetainUntilDate is explicit and derived from retention_days.
    generated = datetime.fromisoformat(export.manifest.generated_at)
    retain_until = datetime.fromisoformat(export.manifest.worm_retain_until)
    assert (retain_until - generated).days == 365
    assert any(
        "Object-store WORM capability is attested" in note
        for note in export.retention_notes
    )


def test_export_fails_closed_when_compliance_required_but_not_enforceable(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_audit_events(repository)
        with pytest.raises(AuditExportWormEnforcementError, match="probe_failed"):
            export_persisted_audit_events(
                repository,
                AuditExportQuery(tenant_id="tenant_demo_manufacturing"),
                object_lock_capability=_worm_capability(enforceable=False),
                require_worm_compliance=True,
            )


def test_export_worm_not_optimistic_without_capability(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_audit_events(repository)
        export = export_persisted_audit_events(
            repository,
            AuditExportQuery(tenant_id="tenant_demo_manufacturing"),
        )

    # GOVERNANCE / no-capability path never claims WORM enforcement.
    assert export.manifest.worm_retention_enforced is False
    assert export.manifest.worm_retention_mode == "none"
    assert export.manifest.worm_status == "none"
    assert export.manifest.worm_retain_until is None


def test_compliance_export_endpoint_fails_closed_without_object_lock(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            connector_export_object_store_adapter="s3_compatible",
            connector_export_s3_endpoint="https://minio.internal:9443",
            connector_export_s3_bucket="axis-evidence",
            connector_export_s3_access_key="axis-service-account",
            connector_export_s3_secret_key="axis-secret-key",
            connector_export_s3_object_lock_enabled=True,
            connector_export_s3_retention_mode="COMPLIANCE",
            connector_export_s3_retention_days=365,
        )
    )
    app.state.session_factory = session_factory
    # Pin a fail-closed capability (bucket lacks object-lock).
    app.state.audit_export_object_lock_capability_override = _worm_capability(
        enforceable=False
    )
    with session_scope(session_factory) as session:
        seed_audit_events(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.get("/demo/manufacturing/audit/export")

    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["code"] == "CONNECTOR_UNAVAILABLE"
    assert "probe_failed" in body["detail"]["reason"]


def test_compliance_export_endpoint_succeeds_with_verified_object_lock(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            connector_export_object_store_adapter="s3_compatible",
            connector_export_s3_endpoint="https://minio.internal:9443",
            connector_export_s3_bucket="axis-evidence",
            connector_export_s3_access_key="axis-service-account",
            connector_export_s3_secret_key="axis-secret-key",
            connector_export_s3_object_lock_enabled=True,
            connector_export_s3_retention_mode="COMPLIANCE",
            connector_export_s3_retention_days=365,
        )
    )
    app.state.session_factory = session_factory
    app.state.audit_export_object_lock_capability_override = _worm_capability(
        enforceable=True
    )
    with session_scope(session_factory) as session:
        seed_audit_events(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.get("/demo/manufacturing/audit/export")

    assert response.status_code == 200
    body = response.json()
    assert body["manifest"]["worm_retention_enforced"] is True
    assert body["manifest"]["worm_retention_mode"] == "COMPLIANCE"
    assert body["manifest"]["worm_status"] == "capability_attested"


def test_object_lock_capability_negative_result_is_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from axis_api import main as main_module

    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            connector_export_object_store_adapter="s3_compatible",
            connector_export_s3_endpoint="https://minio.internal:9443",
            connector_export_s3_bucket="axis-evidence",
            connector_export_s3_access_key="axis-service-account",
            connector_export_s3_secret_key="axis-secret-key",
            connector_export_s3_object_lock_enabled=True,
            connector_export_s3_retention_mode="COMPLIANCE",
            connector_export_s3_retention_days=365,
        )
    )

    results = iter(
        [_worm_capability(enforceable=False), _worm_capability(enforceable=True)]
    )
    monkeypatch.setattr(
        main_module, "probe_object_lock_capability", lambda _settings: next(results)
    )

    # First probe fails (transient bucket outage): not enforceable, not cached.
    first = main_module._audit_export_object_lock_capability(app)
    assert first.compliance_enforceable is False

    # Second probe (bucket recovered) re-runs and restores capability without a
    # restart; the positive result is now cached.
    second = main_module._audit_export_object_lock_capability(app)
    assert second.compliance_enforceable is True
    assert (
        app.state.audit_export_object_lock_capability.compliance_enforceable is True
    )


class _FakeLegalHoldStore:
    adapter_name = "s3_compatible"

    def __init__(self) -> None:
        self.holds: dict[str, bool] = {}

    def apply_legal_hold(self, key: str) -> None:
        self.holds[key] = True

    def release_legal_hold(self, key: str) -> None:
        self.holds[key] = False


def test_object_legal_hold_apply_and_release_are_audited(
    session_factory: sessionmaker[Session],
) -> None:
    store = _FakeLegalHoldStore()
    key = "tenant_demo_manufacturing/exports/audit-export-abc.json"
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        applied = apply_object_legal_hold(
            repository,
            store,
            AuditObjectLegalHoldRequest(
                tenant_id="tenant_demo_manufacturing",
                actor_id="legal-ops-controller",
                actor_scopes=["audit:legal_hold:write"],
                storage_key=key,
                reason="Litigation hold on export bundle.",
                hold_id="hold-export-abc",
            ),
        )
        assert applied.status == "applied"
        assert applied.audit_event_type == "audit.object_legal_hold.applied"
        assert store.holds[key] is True

        released = release_object_legal_hold(
            repository,
            store,
            AuditObjectLegalHoldRequest(
                tenant_id="tenant_demo_manufacturing",
                actor_id="legal-ops-controller",
                actor_scopes=["audit:legal_hold:write"],
                storage_key=key,
                reason="Litigation concluded.",
                hold_id="hold-export-abc",
            ),
        )
        assert released.status == "released"
        assert released.audit_event_type == "audit.object_legal_hold.released"
        assert store.holds[key] is False

        events = session.execute(
            select(AuditEvent).where(
                AuditEvent.event_type.in_(
                    [
                        "audit.object_legal_hold.applied",
                        "audit.object_legal_hold.released",
                    ]
                )
            )
        ).scalars().all()
    assert len(events) == 2


def test_object_legal_hold_denied_without_write_scope(
    session_factory: sessionmaker[Session],
) -> None:
    store = _FakeLegalHoldStore()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(AuditLegalHoldPermissionDenied):
            apply_object_legal_hold(
                repository,
                store,
                AuditObjectLegalHoldRequest(
                    tenant_id="tenant_demo_manufacturing",
                    actor_id="unauthorized-actor",
                    actor_scopes=[],
                    storage_key="tenant_demo_manufacturing/exports/x.json",
                    reason="No scope.",
                ),
            )
    assert store.holds == {}


def test_object_legal_hold_endpoint_applies_and_releases(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    store = _FakeLegalHoldStore()
    app.dependency_overrides[connector_export_object_store] = lambda: store
    client = TestClient(app)

    apply_response = client.post(
        "/demo/manufacturing/audit/object-legal-holds",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "actor_id": "legal-ops-controller",
            "actor_scopes": ["audit:legal_hold:write"],
            "storage_key": "tenant_demo_manufacturing/exports/audit-export-abc.json",
            "reason": "Litigation hold.",
        },
    )

    assert apply_response.status_code == 201
    assert apply_response.json()["status"] == "applied"

    release_response = client.post(
        "/demo/manufacturing/audit/object-legal-holds/release",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "actor_id": "legal-ops-controller",
            "actor_scopes": ["audit:legal_hold:write"],
            "storage_key": "tenant_demo_manufacturing/exports/audit-export-abc.json",
            "reason": "Concluded.",
        },
    )

    assert release_response.status_code == 200
    assert release_response.json()["status"] == "released"


def test_object_legal_hold_endpoint_503_when_store_cannot_hold(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    # Default local_filesystem store has no legal-hold surface.
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/audit/object-legal-holds",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "actor_id": "legal-ops-controller",
            "actor_scopes": ["audit:legal_hold:write"],
            "storage_key": "tenant_demo_manufacturing/exports/audit-export-abc.json",
            "reason": "Litigation hold.",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CONNECTOR_UNAVAILABLE"
