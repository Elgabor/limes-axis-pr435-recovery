from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import AuditEvent, Base, ReplaySimulationOutput
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorPromotionPolicyCreate,
    ConnectorPromotionPolicySetCreate,
    WorkflowRunCreate,
    WorkflowTimelineEventCreate,
)
from axis_api.replay_simulation import (
    ReplayPolicySetDiffDisabled,
    ReplayPolicySetDiffValidationError,
    ReplaySimulationQuery,
    build_replay_simulation,
)


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


def seed_replay_history(repository: AxisPersistenceRepository) -> None:
    started_at = datetime.now(UTC) - timedelta(days=1)
    repository.create_workflow_run(
        WorkflowRunCreate(
            tenant_id="tenant_demo_manufacturing",
            workflow_id="wf_supplier_delay_review",
            name="Supplier Delay Review",
            domain="Supply",
            state="waiting_for_approval",
            status="action_required",
            owner_role="plant-operations-owner",
            runtime="Temporal OSS",
            adapter="axis-temporal-adapter",
            autonomy_level="L2",
            started_at=started_at,
            eta="Today 18:00",
            blocker="Approve expedite action or adjust production schedule",
            objective="Resolve a delayed supplier batch before it blocks Line 2.",
            current_step="Approval gate",
            related_risk="risk_supplier_delay",
            related_assets=["asset_motors_batch", "asset_line_2_packaging"],
            inputs=["Supplier portal delay signal", "Line 2 packaging schedule"],
            proposed_outputs=["Expedite supplier batch action payload"],
            pending_signals=[
                {
                    "signal": "approval.decision",
                    "required_role": "plant-operations-owner",
                    "status": "waiting",
                    "approval_id": "appr_expedite_supplier_batch",
                }
            ],
            controls=["approvals:supply:decide", "append-only-audit-required"],
            audit_scope="wf_supplier_delay_review",
            replay_ready=False,
        )
    )
    repository.append_workflow_timeline_event(
        WorkflowTimelineEventCreate(
            tenant_id="tenant_demo_manufacturing",
            workflow_id="wf_supplier_delay_review",
            sequence=1,
            event="workflow.started",
            occurred_at=started_at,
            actor="workflow-runtime",
            result="started",
            summary="Supplier delay workflow created from the supply risk signal.",
        )
    )
    repository.append_workflow_timeline_event(
        WorkflowTimelineEventCreate(
            tenant_id="tenant_demo_manufacturing",
            workflow_id="wf_supplier_delay_review",
            sequence=2,
            event="workflow.signal.awaiting",
            occurred_at=started_at + timedelta(minutes=13),
            actor="axis-temporal-adapter",
            result="waiting_for_approval",
            summary="Workflow paused at the human approval gate.",
        )
    )
    repository.create_workflow_run(
        WorkflowRunCreate(
            tenant_id="tenant_other",
            workflow_id="wf_other",
            name="Other Tenant Workflow",
            domain="Other",
            state="waiting_for_approval",
            status="action_required",
            owner_role="other-owner",
            runtime="Temporal OSS",
            adapter="axis-temporal-adapter",
            autonomy_level="L1",
            started_at=started_at - timedelta(hours=2),
            eta="Today 17:00",
            blocker=None,
            objective="Other tenant objective",
            current_step="Other step",
            related_risk="risk_other",
            related_assets=["asset_other"],
            inputs=["Other input"],
            proposed_outputs=["Other output"],
            pending_signals=[],
            controls=["other:decide"],
            audit_scope="wf_other",
            replay_ready=False,
        )
    )
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="agent_supply_risk",
            event_type="action.proposal.created",
            payload={
                "action_id": "request_supplier_expedite",
                "workflow_id": "wf_supplier_delay_review",
                "approval_id": "appr_expedite_supplier_batch",
                "status": "approval_required",
                "approval_required": True,
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
                "workflow_id": "wf_supplier_delay_review",
                "approval_id": "appr_expedite_supplier_batch",
                "decision": "approve",
                "required_permission": "approvals:supply:decide",
            },
        )
    )
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_other",
            actor_id="other-actor",
            event_type="approval.decision.recorded",
            payload={"workflow_id": "wf_other", "decision": "approve"},
        )
    )


def seed_promotion_policy(
    repository: AxisPersistenceRepository,
    policy_id: str,
    required_manual_import_status: str,
    tenant_id: str = "tenant_demo_manufacturing",
) -> None:
    repository.create_connector_promotion_policy(
        ConnectorPromotionPolicyCreate(
            tenant_id=tenant_id,
            connector_id="file_csv_manufacturing_assets",
            policy_id=policy_id,
            policy_version="2026-06-22.1",
            status="enabled",
            enforcement_mode="required",
            created_by="connector-governance-owner-role",
            required_scopes=["connectors:ontology:promote"],
            required_manual_import_status=required_manual_import_status,
            required_workflow_signal_status="manual_import_signal_requested",
            allowed_risk_levels=["high", "medium"],
            allowed_ontology_types=["manufacturing_asset"],
            review_window_hours=24,
        )
    )


def seed_promotion_policy_set(
    repository: AxisPersistenceRepository,
    policy_set_id: str,
    policy_set_version: str,
    policy_ids: list[str],
    tenant_id: str = "tenant_demo_manufacturing",
    connector_id: str = "file_csv_manufacturing_assets",
) -> None:
    repository.create_connector_promotion_policy_set(
        ConnectorPromotionPolicySetCreate(
            tenant_id=tenant_id,
            connector_id=connector_id,
            policy_set_id=policy_set_id,
            policy_set_version=policy_set_version,
            status="active",
            activated_by="connector-governance-owner-role",
            policy_ids=policy_ids,
            activation_reason="Seed policy set for arbitrary replay comparison tests.",
        )
    )


def seed_policy_set_comparison_fixtures(repository: AxisPersistenceRepository) -> None:
    seed_promotion_policy(
        repository,
        "policy_gate_status_approval_required",
        "approval_required",
    )
    seed_promotion_policy(
        repository,
        "policy_gate_status_approval_required_v2",
        "approval_required",
    )
    seed_promotion_policy(
        repository,
        "policy_gate_status_approval_approved",
        "approval_approved",
    )
    seed_promotion_policy_set(
        repository,
        "policy_set_replay_baseline",
        "2026-06-22.1",
        ["policy_gate_status_approval_required"],
    )
    seed_promotion_policy_set(
        repository,
        "policy_set_replay_baseline_clone",
        "2026-06-22.2",
        ["policy_gate_status_approval_required_v2"],
    )
    seed_promotion_policy_set(
        repository,
        "policy_set_replay_candidate",
        "2026-06-22.3",
        ["policy_gate_status_approval_approved"],
    )


def arbitrary_diff_query(**overrides) -> ReplaySimulationQuery:
    params = {
        "tenant_id": "tenant_demo_manufacturing",
        "baseline_policy_set_id": "policy_set_replay_baseline",
        "candidate_policy_set_id": "policy_set_replay_candidate",
        "connector_id": "file_csv_manufacturing_assets",
    }
    params.update(overrides)
    return ReplaySimulationQuery(**params)


def replay_output_payload() -> dict:
    return {
        "tenant_id": "tenant_demo_manufacturing",
        "workflow_id": "wf_supplier_delay_review",
        "simulation_output_id": "replay_output_supplier_delay_review_20260622",
        "idempotency_key": "idem_replay_output_supplier_delay_review_20260622",
        "requested_by": "simulation-governance-owner-role",
        "actor_scopes": ["simulation:replay:persist"],
        "reason": "Persist replay output for governance review.",
        "retention_window_days": 30,
        "notes": ["Governed replay output retained for design partner review."],
    }


def test_build_replay_simulation_creates_tenant_scoped_artifacts(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        simulation = build_replay_simulation(
            repository,
            ReplaySimulationQuery(tenant_id="tenant_demo_manufacturing"),
        )

    assert simulation.tenant_id == "tenant_demo_manufacturing"
    assert simulation.simulation_status == "ready"
    assert simulation.metrics[0].label == "Replay Artifacts"
    assert simulation.metrics[0].value == "1"
    assert len(simulation.artifacts) == 1
    artifact = simulation.artifacts[0]
    assert artifact.artifact_id.startswith("replay-wf_supplier_delay_review-")
    assert artifact.workflow_id == "wf_supplier_delay_review"
    assert artifact.audit_scope == "wf_supplier_delay_review"
    assert artifact.timeline_event_count == 2
    assert artifact.audit_event_count == 2
    assert artifact.replay_mode == "governance-preview"
    assert artifact.determinism_status == "preview_only"
    assert artifact.policy_results[0].policy_id == "human-approval-required"
    assert artifact.policy_results[0].simulated_decision == "blocked_until_human_approval"
    assert artifact.policy_set_diffs[0].candidate_policy_set_id == (
        "policy_set_connector_asset_required_20260622_rollback"
    )
    assert "tenant_other" not in simulation.model_dump_json()
    assert "credential_secret" not in simulation.model_dump_json()
    assert "never-export-this-value" not in simulation.model_dump_json()


def test_build_replay_simulation_includes_policy_set_version_diff_preview(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        simulation = build_replay_simulation(
            repository,
            ReplaySimulationQuery(tenant_id="tenant_demo_manufacturing"),
        )

    diff_metric = next(
        metric for metric in simulation.metrics if metric.label == "Policy Set Diffs"
    )
    assert diff_metric.value == "1"
    artifact = simulation.artifacts[0]
    diff = artifact.policy_set_diffs[0]
    assert diff.diff_id.startswith("policy-set-diff-wf_supplier_delay_review-")
    assert diff.connector_id == "file_csv_manufacturing_assets"
    assert diff.baseline_policy_set_id == "policy_set_connector_asset_required_20260622_v2"
    assert diff.baseline_policy_set_version == "2026-06-22.2"
    assert diff.candidate_policy_set_id == (
        "policy_set_connector_asset_required_20260622_rollback"
    )
    assert diff.candidate_policy_set_version == "2026-06-22.3"
    assert diff.historical_event_count == 4
    assert diff.changed_policy_ids == ["connector.asset.required"]
    assert diff.changed_outcome is True
    assert diff.diff_status == "changed_outcome_detected"
    assert diff.audit_event_type == "connector.promotion_policy_set.simulated_diff"
    assert "appr_expedite_supplier_batch" in diff.evidence_refs
    assert "credential_secret" not in diff.model_dump_json()


def test_build_replay_simulation_enforces_retention_window(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        repository.append_workflow_timeline_event(
            WorkflowTimelineEventCreate(
                tenant_id="tenant_demo_manufacturing",
                workflow_id="wf_supplier_delay_review",
                sequence=3,
                event="workflow.legacy_checkpoint",
                occurred_at=datetime.now(UTC) - timedelta(days=90),
                actor="axis-temporal-adapter",
                result="expired_checkpoint",
                summary="Legacy checkpoint outside replay retention.",
            )
        )
        old_audit = repository.append_audit_event(
            AuditEventCreate(
                tenant_id="tenant_demo_manufacturing",
                actor_id="workflow-runtime",
                event_type="workflow.legacy_checkpoint.recorded",
                payload={
                    "workflow_id": "wf_supplier_delay_review",
                    "status": "expired_checkpoint",
                },
            )
        )
        old_audit.created_at = datetime.now(UTC) - timedelta(days=90)
        simulation = build_replay_simulation(
            repository,
            ReplaySimulationQuery(
                tenant_id="tenant_demo_manufacturing",
                retention_days=30,
            ),
        )

    artifact = simulation.artifacts[0]
    assert artifact.timeline_event_count == 2
    assert artifact.audit_event_count == 2
    assert simulation.retention_window.retention_days == 30
    assert simulation.retention_window.retention_enforced is True
    assert simulation.retention_window.excluded_timeline_event_count == 1
    assert simulation.retention_window.excluded_audit_event_count == 1
    assert simulation.retention_window.excluded_output_count == 0
    assert "workflow.legacy_checkpoint" not in simulation.model_dump_json()
    assert next(
        metric for metric in simulation.metrics if metric.label == "Retention Excluded"
    ).value == "2"


def test_replay_simulation_output_endpoint_persists_artifact_and_audit(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_replay_history(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/simulation/replay/outputs",
        json=replay_output_payload(),
    )

    with session_factory() as session:
        output = session.scalars(select(ReplaySimulationOutput)).one()
        audit_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "simulation.replay_output.persisted"
            )
        ).one()

    client.close()
    assert response.status_code == 201
    body = response.json()
    assert body["simulation_output_id"] == "replay_output_supplier_delay_review_20260622"
    assert body["workflow_id"] == "wf_supplier_delay_review"
    assert body["artifact"]["workflow_id"] == "wf_supplier_delay_review"
    assert body["artifact_id"] == body["artifact"]["artifact_id"]
    assert body["status"] == "persisted"
    assert body["retention_window_days"] == 30
    assert body["permission_decision"] == {"allowed": True, "reason": "allowed"}
    assert body["audit_event_type"] == "simulation.replay_output.persisted"
    assert body["audit_event_id"] == str(audit_event.id)
    assert body["idempotent_replay"] is False
    assert len(body["output_hash"]) == 64
    assert output.audit_event_id == audit_event.id
    assert output.artifact_payload["workflow_id"] == "wf_supplier_delay_review"
    assert output.artifact_payload["policy_set_diffs"][0]["diff_status"] == (
        "changed_outcome_detected"
    )
    assert audit_event.payload["simulation_output_id"] == (
        "replay_output_supplier_delay_review_20260622"
    )
    assert "credential_secret" not in str(body)
    assert "never-export-this-value" not in str(body)
    assert "credential_secret" not in str(audit_event.payload)


def test_replay_simulation_output_endpoint_is_idempotent(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_replay_history(AxisPersistenceRepository(session))
    client = TestClient(app)
    payload = replay_output_payload()

    first_response = client.post(
        "/demo/manufacturing/simulation/replay/outputs",
        json=payload,
    )
    replay_response = client.post(
        "/demo/manufacturing/simulation/replay/outputs",
        json=payload,
    )

    with session_factory() as session:
        outputs = session.scalars(select(ReplaySimulationOutput)).all()
        audit_events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "simulation.replay_output.persisted"
            )
        ).all()

    client.close()
    assert first_response.status_code == 201
    assert replay_response.status_code == 200
    assert replay_response.json()["idempotent_replay"] is True
    assert len(outputs) == 1
    assert len(audit_events) == 1


def test_replay_simulation_output_endpoint_rejects_missing_permission(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_replay_history(AxisPersistenceRepository(session))
    client = TestClient(app)
    payload = replay_output_payload()
    payload["actor_scopes"] = []

    response = client.post(
        "/demo/manufacturing/simulation/replay/outputs",
        json=payload,
    )

    client.close()
    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "missing_required_scope"
    assert response.json()["detail"]["required_permission"] == "simulation:replay:persist"


def test_replay_simulation_endpoint_includes_persisted_outputs(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_replay_history(AxisPersistenceRepository(session))
    client = TestClient(app)

    assert client.post(
        "/demo/manufacturing/simulation/replay/outputs",
        json=replay_output_payload(),
    ).status_code == 201
    response = client.get(
        "/demo/manufacturing/simulation/replay",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    client.close()
    assert response.status_code == 200
    body = response.json()
    assert body["persisted_outputs"][0]["simulation_output_id"] == (
        "replay_output_supplier_delay_review_20260622"
    )
    assert body["persisted_outputs"][0]["artifact"]["workflow_id"] == (
        "wf_supplier_delay_review"
    )
    assert next(metric for metric in body["metrics"] if metric["label"] == "Persisted Outputs")[
        "value"
    ] == "1"
    assert body["retention_window"]["retention_enforced"] is True
    assert body["retention_window"]["excluded_output_count"] == 0


def test_replay_simulation_endpoint_excludes_expired_persisted_outputs(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_replay_history(AxisPersistenceRepository(session))
    client = TestClient(app)

    assert client.post(
        "/demo/manufacturing/simulation/replay/outputs",
        json=replay_output_payload(),
    ).status_code == 201
    with session_factory() as session:
        output = session.scalars(select(ReplaySimulationOutput)).one()
        output.created_at = datetime.now(UTC) - timedelta(days=90)
        session.commit()

    response = client.get(
        "/demo/manufacturing/simulation/replay",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "retention_days": 30,
        },
    )

    client.close()
    assert response.status_code == 200
    body = response.json()
    assert body["persisted_outputs"] == []
    assert body["retention_window"]["retention_days"] == 30
    assert body["retention_window"]["retention_enforced"] is True
    assert body["retention_window"]["excluded_output_count"] == 1
    assert next(
        metric for metric in body["metrics"] if metric["label"] == "Retention Excluded"
    )["value"] == "1"


def test_replay_simulation_endpoint_keeps_expired_outputs_under_legal_hold(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_replay_history(AxisPersistenceRepository(session))
    client = TestClient(app)

    assert client.post(
        "/demo/manufacturing/simulation/replay/outputs",
        json=replay_output_payload(),
    ).status_code == 201
    with session_factory() as session:
        output = session.scalars(select(ReplaySimulationOutput)).one()
        output.created_at = datetime.now(UTC) - timedelta(days=90)
        session.commit()

    response = client.get(
        "/demo/manufacturing/simulation/replay",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "retention_days": 30,
            "legal_hold": True,
        },
    )

    client.close()
    assert response.status_code == 200
    body = response.json()
    assert len(body["persisted_outputs"]) == 1
    assert body["retention_window"]["retention_enforced"] is False
    assert body["retention_window"]["excluded_output_count"] == 0
    assert body["retention_window"]["legal_hold"] is True


def test_replay_simulation_endpoint_rejects_invalid_legal_hold(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/simulation/replay",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "legal_hold": "not-a-boolean",
        },
    )

    client.close()
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "legal_hold"]


def test_build_replay_simulation_filters_by_workflow_id(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        simulation = build_replay_simulation(
            repository,
            ReplaySimulationQuery(
                tenant_id="tenant_demo_manufacturing",
                workflow_id="missing_workflow",
            ),
        )

    assert simulation.artifacts == []
    assert simulation.simulation_status == "watch"
    assert simulation.metrics[0].value == "0"


def test_replay_simulation_endpoint_returns_artifact(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_replay_history(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/simulation/replay",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "workflow_id": "wf_supplier_delay_review",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["artifacts"][0]["workflow_id"] == "wf_supplier_delay_review"
    assert body["artifacts"][0]["policy_results"][0]["policy_id"] == "human-approval-required"
    assert body["artifacts"][0]["policy_set_diffs"][0]["audit_event_type"] == (
        "connector.promotion_policy_set.simulated_diff"
    )
    assert "tenant_other" not in str(body)


def test_openapi_exposes_replay_simulation_endpoint(openapi_schema: dict) -> None:
    assert "/demo/manufacturing/simulation/replay" in openapi_schema["paths"]
    assert "/demo/manufacturing/simulation/replay/outputs" in openapi_schema["paths"]


def test_replay_arbitrary_policy_set_diff_reports_changed_outcomes(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        seed_policy_set_comparison_fixtures(repository)
        simulation = build_replay_simulation(
            repository,
            arbitrary_diff_query(),
            arbitrary_policy_set_diff_enabled=True,
        )

    artifact = simulation.artifacts[0]
    assert len(artifact.policy_set_diffs) == 1
    diff = artifact.policy_set_diffs[0]
    assert diff.diff_id.startswith("policy-set-diff-wf_supplier_delay_review-")
    assert diff.connector_id == "file_csv_manufacturing_assets"
    assert diff.baseline_policy_set_id == "policy_set_replay_baseline"
    assert diff.baseline_policy_set_version == "2026-06-22.1"
    assert diff.candidate_policy_set_id == "policy_set_replay_candidate"
    assert diff.candidate_policy_set_version == "2026-06-22.3"
    assert diff.historical_event_count == 4
    assert diff.events_evaluated == 4
    assert diff.changed_outcome_event_count == 1
    assert diff.changed_outcome is True
    assert diff.diff_status == "changed_outcome_detected"
    assert diff.audit_event_type == "connector.promotion_policy_set.simulated_diff"
    assert diff.changed_policy_ids == [
        "policy_gate_status_approval_approved",
        "policy_gate_status_approval_required",
    ]
    assert diff.baseline_decision == "block_until_required_policy_gate"
    assert diff.candidate_decision == "block_until_required_policy_gate"
    assert len(diff.event_decisions) == 4
    changed_decisions = [
        decision for decision in diff.event_decisions if decision.changed_outcome
    ]
    assert len(changed_decisions) == 1
    assert changed_decisions[0].event_kind == "audit"
    assert changed_decisions[0].baseline_decision == "allow_historical_event"
    assert changed_decisions[0].candidate_decision == "block_until_required_policy_gate"
    timeline_decisions = [
        decision for decision in diff.event_decisions if decision.event_kind == "timeline"
    ]
    assert len(timeline_decisions) == 2
    assert all(not decision.changed_outcome for decision in timeline_decisions)
    assert "credential_secret" not in diff.model_dump_json()


def test_replay_arbitrary_policy_set_diff_reports_no_outcome_change(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        seed_policy_set_comparison_fixtures(repository)
        simulation = build_replay_simulation(
            repository,
            arbitrary_diff_query(
                candidate_policy_set_id="policy_set_replay_baseline_clone",
            ),
            arbitrary_policy_set_diff_enabled=True,
        )

    diff = simulation.artifacts[0].policy_set_diffs[0]
    assert diff.baseline_policy_set_id == "policy_set_replay_baseline"
    assert diff.candidate_policy_set_id == "policy_set_replay_baseline_clone"
    assert diff.events_evaluated == 4
    assert diff.changed_outcome_event_count == 0
    assert diff.changed_outcome is False
    assert diff.diff_status == "no_outcome_change"
    assert diff.changed_policy_ids == [
        "policy_gate_status_approval_required",
        "policy_gate_status_approval_required_v2",
    ]
    assert all(not decision.changed_outcome for decision in diff.event_decisions)


def test_replay_arbitrary_policy_set_diff_rejects_unknown_baseline(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        seed_policy_set_comparison_fixtures(repository)
        with pytest.raises(ReplayPolicySetDiffValidationError) as excinfo:
            build_replay_simulation(
                repository,
                arbitrary_diff_query(baseline_policy_set_id="policy_set_missing"),
                arbitrary_policy_set_diff_enabled=True,
            )

    assert excinfo.value.reason == "policy_set_diff_baseline_not_found"


def test_replay_arbitrary_policy_set_diff_rejects_unknown_candidate(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        seed_policy_set_comparison_fixtures(repository)
        with pytest.raises(ReplayPolicySetDiffValidationError) as excinfo:
            build_replay_simulation(
                repository,
                arbitrary_diff_query(candidate_policy_set_id="policy_set_missing"),
                arbitrary_policy_set_diff_enabled=True,
            )

    assert excinfo.value.reason == "policy_set_diff_candidate_not_found"


def test_replay_arbitrary_policy_set_diff_rejects_partial_params(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        seed_policy_set_comparison_fixtures(repository)
        with pytest.raises(ReplayPolicySetDiffValidationError) as baseline_only:
            build_replay_simulation(
                repository,
                arbitrary_diff_query(candidate_policy_set_id=None, connector_id=None),
                arbitrary_policy_set_diff_enabled=True,
            )
        with pytest.raises(ReplayPolicySetDiffValidationError) as connector_only:
            build_replay_simulation(
                repository,
                arbitrary_diff_query(
                    baseline_policy_set_id=None,
                    candidate_policy_set_id=None,
                ),
                arbitrary_policy_set_diff_enabled=True,
            )

    assert baseline_only.value.reason == "policy_set_diff_pair_required"
    assert connector_only.value.reason == "policy_set_diff_pair_required"


def test_replay_arbitrary_policy_set_diff_rejects_identical_ids(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        seed_policy_set_comparison_fixtures(repository)
        with pytest.raises(ReplayPolicySetDiffValidationError) as excinfo:
            build_replay_simulation(
                repository,
                arbitrary_diff_query(
                    candidate_policy_set_id="policy_set_replay_baseline",
                ),
                arbitrary_policy_set_diff_enabled=True,
            )

    assert excinfo.value.reason == "policy_set_diff_identical_policy_sets"


def test_replay_arbitrary_policy_set_diff_rejects_cross_tenant_policy_set(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        seed_policy_set_comparison_fixtures(repository)
        seed_promotion_policy(
            repository,
            "policy_gate_other_tenant",
            "approval_required",
            tenant_id="tenant_other",
        )
        seed_promotion_policy_set(
            repository,
            "policy_set_other_tenant",
            "2026-06-22.9",
            ["policy_gate_other_tenant"],
            tenant_id="tenant_other",
        )
        with pytest.raises(ReplayPolicySetDiffValidationError) as excinfo:
            build_replay_simulation(
                repository,
                arbitrary_diff_query(baseline_policy_set_id="policy_set_other_tenant"),
                arbitrary_policy_set_diff_enabled=True,
            )

    assert excinfo.value.reason == "policy_set_diff_baseline_not_found"


def test_replay_arbitrary_policy_set_diff_requires_flag(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        seed_policy_set_comparison_fixtures(repository)
        with pytest.raises(ReplayPolicySetDiffDisabled) as excinfo:
            build_replay_simulation(repository, arbitrary_diff_query())

    assert excinfo.value.reason == "arbitrary_policy_set_diff_disabled"


def test_replay_simulation_endpoint_rejects_arbitrary_diff_when_flag_disabled(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        seed_policy_set_comparison_fixtures(repository)
    client = TestClient(app)

    get_response = client.get(
        "/demo/manufacturing/simulation/replay",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "baseline_policy_set_id": "policy_set_replay_baseline",
            "candidate_policy_set_id": "policy_set_replay_candidate",
        },
    )
    output_payload = replay_output_payload()
    output_payload["baseline_policy_set_id"] = "policy_set_replay_baseline"
    output_payload["candidate_policy_set_id"] = "policy_set_replay_candidate"
    post_response = client.post(
        "/demo/manufacturing/simulation/replay/outputs",
        json=output_payload,
    )

    client.close()
    assert get_response.status_code == 403
    assert get_response.json()["detail"]["code"] == "PERMISSION_DENIED"
    assert get_response.json()["detail"]["reason"] == "arbitrary_policy_set_diff_disabled"
    assert post_response.status_code == 403
    assert post_response.json()["detail"]["reason"] == "arbitrary_policy_set_diff_disabled"


def test_replay_arbitrary_policy_set_diff_id_is_deterministic(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        seed_policy_set_comparison_fixtures(repository)
        first = build_replay_simulation(
            repository,
            arbitrary_diff_query(),
            arbitrary_policy_set_diff_enabled=True,
        )
        second = build_replay_simulation(
            repository,
            arbitrary_diff_query(),
            arbitrary_policy_set_diff_enabled=True,
        )

    first_diff = first.artifacts[0].policy_set_diffs[0]
    second_diff = second.artifacts[0].policy_set_diffs[0]
    assert first_diff.diff_id == second_diff.diff_id
    assert first_diff.model_dump() == second_diff.model_dump()


def test_replay_arbitrary_policy_set_diff_respects_retention_window(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        seed_policy_set_comparison_fixtures(repository)
        repository.append_workflow_timeline_event(
            WorkflowTimelineEventCreate(
                tenant_id="tenant_demo_manufacturing",
                workflow_id="wf_supplier_delay_review",
                sequence=3,
                event="workflow.legacy_checkpoint",
                occurred_at=datetime.now(UTC) - timedelta(days=90),
                actor="axis-temporal-adapter",
                result="expired_checkpoint",
                summary="Legacy checkpoint outside replay retention.",
            )
        )
        old_audit = repository.append_audit_event(
            AuditEventCreate(
                tenant_id="tenant_demo_manufacturing",
                actor_id="workflow-runtime",
                event_type="workflow.legacy_checkpoint.recorded",
                payload={
                    "workflow_id": "wf_supplier_delay_review",
                    "status": "expired_checkpoint",
                },
            )
        )
        old_audit.created_at = datetime.now(UTC) - timedelta(days=90)
        simulation = build_replay_simulation(
            repository,
            arbitrary_diff_query(retention_days=30),
            arbitrary_policy_set_diff_enabled=True,
        )

    diff = simulation.artifacts[0].policy_set_diffs[0]
    assert diff.events_evaluated == 4
    assert diff.historical_event_count == 4
    assert simulation.retention_window.excluded_timeline_event_count == 1
    assert simulation.retention_window.excluded_audit_event_count == 1
    assert all(
        "workflow.legacy_checkpoint" not in decision.event_ref
        for decision in diff.event_decisions
    )


def test_replay_simulation_endpoint_returns_arbitrary_policy_set_diff(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            replay_arbitrary_policy_set_diff_enabled=True,
        )
    )
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        seed_policy_set_comparison_fixtures(repository)
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/simulation/replay",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "baseline_policy_set_id": "policy_set_replay_baseline",
            "candidate_policy_set_id": "policy_set_replay_candidate",
            "connector_id": "file_csv_manufacturing_assets",
        },
    )

    client.close()
    assert response.status_code == 200
    body = response.json()
    diff = body["artifacts"][0]["policy_set_diffs"][0]
    assert diff["baseline_policy_set_id"] == "policy_set_replay_baseline"
    assert diff["candidate_policy_set_id"] == "policy_set_replay_candidate"
    assert diff["events_evaluated"] == 4
    assert diff["changed_outcome_event_count"] == 1
    assert diff["diff_status"] == "changed_outcome_detected"
    assert "tenant_other" not in str(body)


def test_replay_simulation_output_round_trips_arbitrary_policy_set_diff(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            replay_arbitrary_policy_set_diff_enabled=True,
        )
    )
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_replay_history(repository)
        seed_policy_set_comparison_fixtures(repository)
    client = TestClient(app)

    payload = replay_output_payload()
    payload["baseline_policy_set_id"] = "policy_set_replay_baseline"
    payload["candidate_policy_set_id"] = "policy_set_replay_candidate"
    payload["connector_id"] = "file_csv_manufacturing_assets"
    create_response = client.post(
        "/demo/manufacturing/simulation/replay/outputs",
        json=payload,
    )
    read_response = client.get(
        "/demo/manufacturing/simulation/replay",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    client.close()
    assert create_response.status_code == 201
    created_diff = create_response.json()["artifact"]["policy_set_diffs"][0]
    assert created_diff["baseline_policy_set_id"] == "policy_set_replay_baseline"
    assert created_diff["candidate_policy_set_id"] == "policy_set_replay_candidate"
    assert read_response.status_code == 200
    persisted_diff = read_response.json()["persisted_outputs"][0]["artifact"][
        "policy_set_diffs"
    ][0]
    assert persisted_diff == created_diff
    assert persisted_diff["events_evaluated"] == 4
    assert persisted_diff["changed_outcome_event_count"] == 1
    assert persisted_diff["changed_outcome"] is True
    assert len(persisted_diff["event_decisions"]) == 4
