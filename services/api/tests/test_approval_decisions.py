from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.approval_decisions import (
    ApprovalDecisionConflict,
    ApprovalDecisionRequest,
    record_demo_approval_decision,
)
from axis_api.approval_reference import (
    derived_queue_status,
    get_persisted_manufacturing_approval_inbox,
    reconcile_inbox_with_decision_records,
)
from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.demo import ApprovalDecision, ApprovalInboxItem, OverviewStatus
from axis_api.identity import OidcPrincipal
from axis_api.main import create_app
from axis_api.models import ActionRun, ApprovalRecord, AuditEvent, Base, WorkflowRunRecord
from axis_api.persistence import (
    ActionRunCreate,
    ApprovalDecisionRecord,
    ApprovalRecordCreate,
    AxisPersistenceRepository,
    DemoReferenceRecordCreate,
    WorkflowRunCreate,
    WorkflowTimelineEventCreate,
)
from axis_api.workflow_queries import WorkflowRunQuery, query_persisted_workflow_runs
from axis_api.workflow_runtime import (
    WorkflowSignalError,
    WorkflowSignalRequest,
    WorkflowSignalResult,
)

MIGRATIONS_DIR = Path(__file__).parents[1] / "migrations" / "versions"


class RecordingWorkflowRuntime:
    def __init__(self) -> None:
        self.requests: list[WorkflowSignalRequest] = []

    async def signal_approval_decision(
        self,
        request: WorkflowSignalRequest,
    ) -> WorkflowSignalResult:
        self.requests.append(request)
        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="approval_signaled",
            adapter="axis-test-workflow-adapter",
            signal_name=request.signal_name,
            payload={
                "approval_id": request.approval_id,
                "approved": request.approved,
                "decision": request.decision.value,
            },
        )


class FailingWorkflowRuntime:
    async def signal_approval_decision(
        self,
        request: WorkflowSignalRequest,
    ) -> WorkflowSignalResult:
        raise WorkflowSignalError("synthetic_runtime_down")


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
    seed_approval_inbox_reference(factory, approval_inbox_bootstrap_payload())
    yield factory
    engine.dispose()


@pytest.fixture
def empty_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


def approval_inbox_bootstrap_payload() -> dict:
    migration = run_path(str(MIGRATIONS_DIR / "0027_approval_inbox_reference.py"))
    return deepcopy(migration["APPROVAL_INBOX_PAYLOAD"])


def persisted_approval_inbox_payload() -> dict:
    return {
        "tenant_id": "tenant_demo_manufacturing",
        "plant_name": "Persisted Ravenna Works",
        "scenario": "Persisted Approval Inbox",
        "as_of": "2026-06-22T11:15:00+02:00",
        "queue_status": "action_required",
        "policy_notes": ["Persisted approval inbox reference."],
        "approvals": [
            {
                "approval_id": "appr_persisted_operations_review",
                "action": "Review persisted operations proposal",
                "risk_level": "medium",
                "status": "pending",
                "requested_by": "agent_persisted_daily_brief",
                "owner_role": "plant-operations-owner",
                "due": "Today 14:00",
                "workflow_id": "wf_persisted_reference",
                "domain": "Operations",
                "summary": "Persisted approval reference used by the API.",
                "evidence": ["Persisted approval evidence"],
                "data_accessed": ["Axis Audit: persisted approval reference"],
                "risks": ["Approving without persisted evidence would violate policy."],
                "alternatives": ["Request changes before approval."],
                "estimated_cost": "No direct spend",
                "model_policy": "local-only",
                "required_permission": "approvals:operations:decide",
                "audit_event_preview": {
                    "event": "approval.decision.recorded",
                    "actor_role": "plant-operations-owner",
                    "scope": "wf_persisted_reference",
                    "result": "workflow_signal_ready",
                },
                "decision_options": [
                    {
                        "decision": "approve",
                        "label": "Approve",
                        "consequence": "Signal persisted workflow approval.",
                    },
                    {
                        "decision": "reject",
                        "label": "Reject",
                        "consequence": "Record denial in persisted approval flow.",
                    },
                    {
                        "decision": "request_changes",
                        "label": "Request changes",
                        "consequence": "Return persisted proposal for revision.",
                    },
                ],
            }
        ],
    }


def seed_approval_inbox_reference(
    factory: sessionmaker[Session],
    payload: dict | None = None,
    tenant_id: str = "tenant_demo_manufacturing",
) -> None:
    inbox_payload = deepcopy(payload or approval_inbox_bootstrap_payload())
    inbox_payload["tenant_id"] = tenant_id
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=tenant_id,
                surface="approvals",
                reference_id="manufacturing-approval-inbox",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=inbox_payload,
            )
        )


def seed_action_registry_reference(
    factory: sessionmaker[Session],
    tenant_id: str,
) -> None:
    migration = run_path(str(MIGRATIONS_DIR / "0025_action_registry_reference.py"))
    payload = deepcopy(migration["ACTION_REGISTRY_PAYLOAD"])
    payload["tenant_id"] = tenant_id
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=tenant_id,
                surface="actions",
                reference_id="manufacturing-action-registry",
                status="active",
                source="bootstrap",
                version=payload["schema_version"],
                payload=payload,
            )
        )


def seed_supplier_delay_workflow(repository: AxisPersistenceRepository) -> None:
    started_at = datetime(2026, 6, 21, 14, 5, tzinfo=UTC)
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


async def test_record_demo_approval_decision_reads_persisted_approval_inbox_reference(
    session_factory: sessionmaker[Session],
) -> None:
    seed_approval_inbox_reference(session_factory, persisted_approval_inbox_payload())
    workflow_runtime = RecordingWorkflowRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        result = await record_demo_approval_decision(
            repository,
            "appr_persisted_operations_review",
            ApprovalDecisionRequest(
                decision=ApprovalDecision.APPROVE,
                actor_id="plant-operations-owner-role",
                actor_scopes=["approvals:operations:decide"],
                note="Approved persisted reference.",
            ),
            workflow_runtime,
        )

    with session_factory() as session:
        approval = session.scalars(select(ApprovalRecord)).one()
        audit_event = session.scalars(select(AuditEvent)).one()

    assert result.approval_id == "appr_persisted_operations_review"
    assert result.workflow_id == "wf_persisted_reference"
    assert result.action_id == "appr_persisted_operations_review"
    assert approval.workflow_id == "wf_persisted_reference"
    assert audit_event.payload["required_permission"] == "approvals:operations:decide"
    assert workflow_runtime.requests[0].workflow_id == "wf_persisted_reference"


async def test_record_approval_decision_uses_explicit_tenant_references_and_persistence(
    session_factory: sessionmaker[Session],
) -> None:
    tenant_id = "tenant_beta"
    seed_approval_inbox_reference(session_factory, tenant_id=tenant_id)
    seed_action_registry_reference(session_factory, tenant_id)
    workflow_runtime = RecordingWorkflowRuntime()

    with session_scope(session_factory) as session:
        result = await record_demo_approval_decision(
            AxisPersistenceRepository(session),
            "appr_expedite_supplier_batch",
            ApprovalDecisionRequest(
                decision=ApprovalDecision.REJECT,
                actor_id="plant-operations-owner-role",
                actor_scopes=["approvals:supply:decide"],
                note="Tenant beta rejected the proposal.",
            ),
            workflow_runtime,
            tenant_id=tenant_id,
        )

    with session_factory() as session:
        approval = session.scalars(
            select(ApprovalRecord).where(ApprovalRecord.tenant_id == tenant_id)
        ).one()
        audit_event = session.scalars(
            select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
        ).one()

    assert result.tenant_id == tenant_id
    assert result.action_id == "request_supplier_expedite"
    assert approval.tenant_id == tenant_id
    assert audit_event.tenant_id == tenant_id
    assert workflow_runtime.requests[0].tenant_id == tenant_id


async def test_record_demo_approval_decision_updates_persisted_workflow_state(
    session_factory: sessionmaker[Session],
) -> None:
    workflow_runtime = RecordingWorkflowRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_supplier_delay_workflow(repository)
        result = await record_demo_approval_decision(
            repository,
            "appr_expedite_supplier_batch",
            ApprovalDecisionRequest(
                decision=ApprovalDecision.APPROVE,
                actor_id="plant-operations-owner-role",
                actor_scopes=["approvals:supply:decide"],
                note="Approved persisted workflow state update.",
            ),
            workflow_runtime,
        )
        console = query_persisted_workflow_runs(
            repository,
            WorkflowRunQuery(tenant_id="tenant_demo_manufacturing"),
        )

    with session_factory() as session:
        workflow_run = session.scalars(select(WorkflowRunRecord)).one()
        audit_event = session.scalars(select(AuditEvent)).one()

    assert result.workflow_state_updated is True
    assert result.workflow_state == "approval_approved"
    assert result.workflow_status == "ready"
    assert workflow_run.state == "approval_approved"
    assert workflow_run.status == "ready"
    assert workflow_run.current_step == "Approval approved"
    assert workflow_run.blocker is None
    assert workflow_run.replay_ready is True
    assert workflow_run.pending_signals == [
        {
            "signal": "approval.decision",
            "required_role": "plant-operations-owner",
            "status": "approved",
            "approval_id": "appr_expedite_supplier_batch",
            "decision": "approve",
            "decided_by": "plant-operations-owner-role",
        }
    ]
    assert console.workflow_runs[0].state == "approval_approved"
    assert console.workflow_runs[0].timeline[-1].event == ("workflow.approval_decision.recorded")
    assert console.workflow_runs[0].timeline[-1].result == "approved"
    assert audit_event.payload["workflow_state_updated"] is True
    assert audit_event.payload["workflow_state"] == "approval_approved"
    assert audit_event.payload["workflow_status"] == "ready"


async def test_record_demo_approval_decision_transitions_existing_action_run(
    session_factory: sessionmaker[Session],
) -> None:
    workflow_runtime = RecordingWorkflowRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        existing_run = repository.create_action_run(
            ActionRunCreate(
                tenant_id="tenant_demo_manufacturing",
                action_id="request_supplier_expedite",
                idempotency_key="agent-proposal-before-approval",
                execution_mode="approval_gated_dry_run",
                requested_by="supply-risk-agent",
                approval_id="appr_expedite_supplier_batch",
                workflow_id="wf_supplier_delay_review",
                payload={
                    "input": {
                        "supplier_batch_id": "asset_motors_batch",
                        "target_arrival": "2026-06-22T08:00:00+02:00",
                        "reason": "Line 2 packaging risk",
                        "cost_ceiling_eur": "1200",
                    },
                    "schema_version": "test",
                    "dry_run": True,
                },
                status="approval_required",
            )
        )
        result = await record_demo_approval_decision(
            repository,
            "appr_expedite_supplier_batch",
            ApprovalDecisionRequest(
                decision=ApprovalDecision.APPROVE,
                actor_id="plant-operations-owner-role",
                actor_scopes=["approvals:supply:decide"],
                note="Action proposal approved for governed execution.",
            ),
            workflow_runtime,
        )

    with session_factory() as session:
        action_run = session.scalars(select(ActionRun)).one()
        audit_event = session.scalars(select(AuditEvent)).one()

    assert result.action_run_recorded is True
    assert result.action_run_idempotent_replay is False
    assert result.action_run_id == existing_run.id
    assert result.action_run_status == "approved_for_execution"
    assert result.action_run_idempotency_key == "agent-proposal-before-approval"
    assert action_run.id == existing_run.id
    assert action_run.status == "approved_for_execution"
    assert action_run.result_payload == {
        "source": "approval_decision",
        "approval_id": "appr_expedite_supplier_batch",
        "workflow_id": "wf_supplier_delay_review",
        "action_id": "request_supplier_expedite",
        "decision": "approve",
        "decision_actor_id": "plant-operations-owner-role",
        "decision_note_recorded": "true",
        "workflow_signal_status": "approval_signaled",
        "workflow_state_updated": False,
        "workflow_state": None,
        "workflow_status": None,
    }
    assert audit_event.payload["action_run"] == {
        "action_run_id": str(existing_run.id),
        "idempotency_key": "agent-proposal-before-approval",
        "status": "approved_for_execution",
        "execution_mode": "approval_gated_dry_run",
        "recorded": True,
        "idempotent_replay": False,
    }


async def test_record_demo_approval_decision_creates_idempotent_gate_action_run(
    session_factory: sessionmaker[Session],
) -> None:
    workflow_runtime = RecordingWorkflowRuntime()
    request = ApprovalDecisionRequest(
        decision=ApprovalDecision.APPROVE,
        actor_id="plant-operations-owner-role",
        actor_scopes=["approvals:supply:decide"],
    )
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        first = await record_demo_approval_decision(
            repository,
            "appr_expedite_supplier_batch",
            request,
            workflow_runtime,
        )
        second = await record_demo_approval_decision(
            repository,
            "appr_expedite_supplier_batch",
            request,
            workflow_runtime,
        )

    with session_factory() as session:
        action_runs = list(session.scalars(select(ActionRun)))
        audit_events = list(session.scalars(select(AuditEvent)))

    assert first.action_run_recorded is True
    assert second.action_run_recorded is True
    assert first.action_run_id == second.action_run_id
    assert first.audit_event_id == second.audit_event_id
    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert first.action_run_idempotent_replay is False
    # The stored action transition is returned unchanged; no second transition ran.
    assert second.action_run_idempotent_replay is False
    assert first.action_run_idempotency_key == (
        "tenant_demo_manufacturing:request_supplier_expedite:"
        "appr_expedite_supplier_batch:approval-gate"
    )
    assert len(action_runs) == 1
    assert action_runs[0].status == "approved_for_execution"
    assert action_runs[0].payload["source"] == "approval_decision_gate"
    assert action_runs[0].payload["approval_id"] == "appr_expedite_supplier_batch"
    assert len(audit_events) == 1
    assert len(workflow_runtime.requests) == 1


def test_approval_decision_endpoint_reports_missing_approval_reference_record(
    empty_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = empty_session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        json={
            "decision": "approve",
            "actor_id": "plant-operations-owner-role",
            "actor_scopes": ["approvals:supply:decide"],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "NOT_FOUND",
        "message": "Manufacturing approval inbox reference record not found.",
        "surface": "approvals",
    }


async def test_record_demo_approval_decision_persists_approval_and_audit_event(
    session_factory: sessionmaker[Session],
) -> None:
    workflow_runtime = RecordingWorkflowRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        result = await record_demo_approval_decision(
            repository,
            "appr_expedite_supplier_batch",
            ApprovalDecisionRequest(
                decision=ApprovalDecision.APPROVE,
                actor_id="plant-operations-owner-role",
                actor_scopes=["approvals:supply:decide"],
                note="Approved in synthetic test scope.",
            ),
            workflow_runtime,
        )

    with session_factory() as session:
        approval = session.scalars(select(ApprovalRecord)).one()
        audit_event = session.scalars(select(AuditEvent)).one()

    assert result.persisted is True
    assert result.permission_decision.allowed is True
    assert result.permission_decision.reason == "allowed"
    assert result.workflow_signal_status == "approval_signaled"
    assert result.workflow_signal.payload == {
        "approval_id": "appr_expedite_supplier_batch",
        "approved": True,
        "decision": "approve",
    }
    assert result.action_id == "request_supplier_expedite"
    assert result.audit_event_id == audit_event.id
    assert approval.status == "approve"
    assert approval.decision_actor_id == "plant-operations-owner-role"
    assert approval.decided_at is not None
    assert audit_event.event_type == "approval.decision.recorded"
    assert audit_event.payload["approval_id"] == "appr_expedite_supplier_batch"
    assert audit_event.payload["decision"] == "approve"
    assert audit_event.payload["permission_decision"] == {
        "allowed": True,
        "reason": "allowed",
    }
    assert audit_event.payload["workflow_signal"]["status"] == "approval_signaled"
    assert audit_event.payload["decision_note_recorded"] == "true"
    assert workflow_runtime.requests[0].workflow_id == "wf_supplier_delay_review"
    assert workflow_runtime.requests[0].approved is True


async def test_record_demo_approval_decision_rejects_terminal_overwrite(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        await record_demo_approval_decision(
            repository,
            "appr_quality_hold_batch",
            ApprovalDecisionRequest(
                decision=ApprovalDecision.REQUEST_CHANGES,
                actor_id="quality-owner-role",
                actor_scopes=["approvals:quality:decide"],
            ),
            RecordingWorkflowRuntime(),
        )
        with pytest.raises(ApprovalDecisionConflict) as exc_info:
            await record_demo_approval_decision(
                repository,
                "appr_quality_hold_batch",
                ApprovalDecisionRequest(
                    decision=ApprovalDecision.REJECT,
                    actor_id="quality-owner-role",
                    actor_scopes=["approvals:quality:decide"],
                ),
                RecordingWorkflowRuntime(),
            )
        assert exc_info.value.reason == "approval_decision_conflict"

    with session_factory() as session:
        approvals = list(session.scalars(select(ApprovalRecord)))
        audit_events = list(session.scalars(select(AuditEvent)))

    assert len(approvals) == 1
    assert approvals[0].status == "request_changes"
    assert len(audit_events) == 1


def test_approval_decision_endpoint_replays_exact_request_and_rejects_conflict(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    runtime = RecordingWorkflowRuntime()
    app.state.workflow_runtime = runtime
    client = TestClient(app)
    payload = {
        "decision": "approve",
        "actor_id": "plant-operations-owner-role",
        "actor_scopes": ["approvals:supply:decide"],
        "note": "Approved once.",
    }

    first = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        json=payload,
    )
    replay = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        json=payload,
    )
    conflict = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        json={**payload, "decision": "reject"},
    )
    changed_note = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        json={**payload, "note": "Changed after terminalization."},
    )
    changed_actor = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        json={
            **payload,
            "actor_id": "backup-plant-operations-owner",
            "actor_scopes": ["approvals:supply:decide"],
        },
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["audit_event_id"] == first.json()["audit_event_id"]
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason"] == "approval_decision_conflict"
    assert changed_note.status_code == 409
    assert changed_actor.status_code == 409
    assert len(runtime.requests) == 1
    with session_factory() as session:
        assert len(session.scalars(select(AuditEvent)).all()) == 1


@pytest.mark.parametrize("payload", [{}, {"decision_result": {}}])
async def test_legacy_or_invalid_terminal_replay_snapshot_fails_closed(
    session_factory: sessionmaker[Session],
    payload: dict,
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.create_approval_record(
            ApprovalRecordCreate(
                tenant_id="tenant_demo_manufacturing",
                approval_id="appr_quality_hold_batch",
                workflow_id="wf_quality_hold_review",
                action_id="place_quality_hold",
                requested_by="quality-agent",
                owner_role="quality-owner",
                risk_level="high",
                payload=payload,
            )
        )
        repository.record_approval_decision(
            ApprovalDecisionRecord(
                tenant_id="tenant_demo_manufacturing",
                approval_id="appr_quality_hold_batch",
                decision="reject",
                decision_actor_id="quality-owner-role",
            )
        )

        with pytest.raises(ApprovalDecisionConflict) as exc_info:
            await record_demo_approval_decision(
                repository,
                "appr_quality_hold_batch",
                ApprovalDecisionRequest(
                    decision=ApprovalDecision.REJECT,
                    actor_id="quality-owner-role",
                    actor_scopes=["approvals:quality:decide"],
                ),
                RecordingWorkflowRuntime(),
            )
        assert exc_info.value.reason == "approval_replay_unavailable"


def test_approval_decision_endpoint_persists_result(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.workflow_runtime = RecordingWorkflowRuntime()
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/approvals/appr_shift_maintenance_window/decision",
        json={
            "decision": "approve",
            "actor_id": "maintenance-owner-role",
            "actor_scopes": ["approvals:maintenance:decide"],
            "note": "Approved in synthetic endpoint test.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["approval_id"] == "appr_shift_maintenance_window"
    assert body["action_id"] == "shift_maintenance_window"
    assert body["audit_event_type"] == "approval.decision.recorded"
    assert body["permission_decision"] == {"allowed": True, "reason": "allowed"}
    assert body["workflow_signal_status"] == "approval_signaled"
    assert body["workflow_signal"]["payload"] == {
        "approval_id": "appr_shift_maintenance_window",
        "approved": True,
        "decision": "approve",
    }

    with session_factory() as session:
        approval = session.scalars(select(ApprovalRecord)).one()
        audit_event = session.scalars(select(AuditEvent)).one()

    assert approval.status == "approve"
    assert approval.decision_actor_id == "maintenance-owner-role"
    assert audit_event.actor_id == "maintenance-owner-role"


def test_approval_decision_action_run_appears_in_action_run_list(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.workflow_runtime = RecordingWorkflowRuntime()
    client = TestClient(app)

    decision = client.post(
        "/operations/approvals/appr_quality_hold_batch/decision",
        json={
            "decision": "approve",
            "actor_id": "quality-owner-role",
            "actor_scopes": ["approvals:quality:decide"],
        },
    )
    listed = client.get(
        "/operations/actions/runs",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert decision.status_code == 201
    assert decision.json()["action_run_status"] == "approved_for_execution"
    assert listed.status_code == 200
    assert listed.json()["runs"] == [
        {
            "action_run_id": decision.json()["action_run_id"],
            "action_id": "place_quality_hold",
            "status": "approved_for_execution",
            "approval_id": "appr_quality_hold_batch",
            "workflow_id": "wf_quality_hold_review",
            "created_at": listed.json()["runs"][0]["created_at"],
            "updated_at": listed.json()["runs"][0]["updated_at"],
            "waiting_duration_seconds": listed.json()["runs"][0]["waiting_duration_seconds"],
            "outcome": None,
        }
    ]


def test_approval_decision_endpoint_binds_actor_and_scopes_from_oidc_token(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.workflow_runtime = RecordingWorkflowRuntime()
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="plant-operations-owner-role",
            tenant_id="tenant_demo_manufacturing",
            scopes=["approvals:supply:decide"],
        )
    )
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        headers={"Authorization": "Bearer valid-token"},
        json={
            "decision": "approve",
            "actor_id": "plant-operations-owner-role",
            "actor_scopes": [],
            "note": "Approved with token-derived scopes.",
        },
    )

    assert response.status_code == 201
    assert response.json()["actor_id"] == "plant-operations-owner-role"
    assert response.json()["permission_decision"] == {"allowed": True, "reason": "allowed"}
    with session_factory() as session:
        audit_event = session.scalars(select(AuditEvent)).one()
    assert audit_event.actor_id == "plant-operations-owner-role"


def test_approval_decision_endpoint_requires_oidc_when_configured(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        json={
            "decision": "approve",
            "actor_id": "plant-operations-owner-role",
            "actor_scopes": ["approvals:supply:decide"],
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_approval_decision_endpoint_rejects_oidc_actor_impersonation(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="plant-operations-owner-role",
            tenant_id="tenant_demo_manufacturing",
            scopes=["approvals:supply:decide"],
        )
    )
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        headers={"Authorization": "Bearer valid-token"},
        json={
            "decision": "approve",
            "actor_id": "quality-owner-role",
            "actor_scopes": ["approvals:supply:decide"],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "PERMISSION_DENIED",
        "message": "The request actor does not match the authenticated OIDC actor.",
        "reason": "actor_mismatch",
    }


def test_approval_decision_endpoint_rejects_oidc_tenant_mismatch(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="plant-operations-owner-role",
            tenant_id="tenant_other",
            scopes=["approvals:supply:decide"],
        )
    )
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        headers={"Authorization": "Bearer valid-token"},
        json={
            "decision": "approve",
            "actor_id": "plant-operations-owner-role",
            "actor_scopes": ["approvals:supply:decide"],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "PERMISSION_DENIED",
        "message": "The authenticated OIDC tenant cannot access this tenant scope.",
        "reason": "tenant_mismatch",
    }
    with session_factory() as session:
        assert session.scalars(select(AuditEvent)).all() == []


async def test_approval_decision_records_signal_failure_without_blocking_persistence(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        result = await record_demo_approval_decision(
            repository,
            "appr_quality_hold_batch",
            ApprovalDecisionRequest(
                decision=ApprovalDecision.REJECT,
                actor_id="quality-owner-role",
                actor_scopes=["approvals:quality:decide"],
            ),
            FailingWorkflowRuntime(),
        )

    with session_factory() as session:
        approval = session.scalars(select(ApprovalRecord)).one()
        audit_event = session.scalars(select(AuditEvent)).one()

    assert approval.status == "reject"
    assert result.workflow_signal_status == "runtime_signal_unavailable"
    assert result.workflow_signal.payload["reason"] == "synthetic_runtime_down"
    assert audit_event.payload["workflow_signal"]["status"] == "runtime_signal_unavailable"


def test_approval_decision_endpoint_handles_missing_approval(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/approvals/missing/decision",
        json={"decision": "approve", "actor_id": "plant-operations-owner-role"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Approval not found"


def test_approval_decision_endpoint_denies_actor_without_required_scope(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        json={
            "decision": "approve",
            "actor_id": "quality-owner-role",
            "actor_scopes": ["approvals:quality:decide"],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "PERMISSION_DENIED",
        "message": "The actor cannot decide this approval.",
        "required_permission": "approvals:supply:decide",
        "reason": "missing_scope:approvals:supply:decide",
    }

    with session_factory() as session:
        assert list(session.scalars(select(ApprovalRecord))) == []
        assert list(session.scalars(select(AuditEvent))) == []


def test_openapi_exposes_approval_decision_endpoint() -> None:
    client = TestClient(create_app())
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/demo/manufacturing/approvals/{approval_id}/decision" in response.json()["paths"]


async def test_inbox_reconciliation_marks_recorded_decisions_as_decided(
    session_factory: sessionmaker[Session],
) -> None:
    """The queue must tell the truth about what is still actionable.

    The inbox reference payload is static; once a terminal decision is
    persisted for an approval, the inbox may no longer present it as pending,
    or operators are invited to submit a decision that can only fail with a
    409 conflict.
    """
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        await record_demo_approval_decision(
            repository,
            "appr_expedite_supplier_batch",
            ApprovalDecisionRequest(
                decision=ApprovalDecision.APPROVE,
                actor_id="plant-operations-owner-role",
                actor_scopes=["approvals:supply:decide"],
                note="Approved through the governed flow.",
            ),
        )

    with session_scope(session_factory) as session:
        inbox = get_persisted_manufacturing_approval_inbox(
            AxisPersistenceRepository(session),
            "tenant_demo_manufacturing",
        )

    statuses = {item.approval_id: item.status for item in inbox.approvals}
    assert statuses["appr_expedite_supplier_batch"] == "decided"
    assert statuses["appr_quality_hold_batch"] == "pending"
    assert statuses["appr_shift_maintenance_window"] == "pending"


async def test_inbox_reconciliation_builds_decision_history_from_persisted_records(
    session_factory: sessionmaker[Session],
) -> None:
    """Decided work leaves the actionable queue but stays visible as history.

    History entries are derived from the persisted approval records and their
    stored result snapshots; fields those records do not carry stay ``None``
    instead of being invented.
    """
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        await record_demo_approval_decision(
            repository,
            "appr_expedite_supplier_batch",
            ApprovalDecisionRequest(
                decision=ApprovalDecision.APPROVE,
                actor_id="plant-operations-owner-role",
                actor_scopes=["approvals:supply:decide"],
                note="Approved through the governed flow.",
            ),
        )

    with session_scope(session_factory) as session:
        inbox = get_persisted_manufacturing_approval_inbox(
            AxisPersistenceRepository(session),
            "tenant_demo_manufacturing",
        )

    history = {
        entry.approval_id: entry for entry in inbox.decision_history
    }
    entry = history["appr_expedite_supplier_batch"]
    assert entry.decision == "approve"
    assert entry.decided_by == "plant-operations-owner-role"
    assert entry.decided_at is not None
    assert entry.rationale == "Approved through the governed flow."
    assert entry.audit_event_id is not None
    assert entry.action == "Expedite supplier batch"
    # Only the decided approval appears in history.
    assert set(history) == {"appr_expedite_supplier_batch"}
    # Pending items are untouched by the history projection.
    assert all(
        item.status != "decided" or item.approval_id in history
        for item in inbox.approvals
    )


async def test_inbox_reconciliation_derives_queue_status_from_reconciled_items(
    session_factory: sessionmaker[Session],
) -> None:
    """``queue_status`` is a projection of the item list, never stored state.

    A static status next to reconciled items would let the console show
    "action required" over a fully decided queue, or "ready" over pending
    high-risk work. The derivation must also be idempotent: replaying it over
    an already-reconciled inbox changes nothing.
    """
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        for approval_id, scope in [
            ("appr_expedite_supplier_batch", "approvals:supply:decide"),
            ("appr_quality_hold_batch", "approvals:quality:decide"),
            ("appr_shift_maintenance_window", "approvals:maintenance:decide"),
        ]:
            await record_demo_approval_decision(
                repository,
                approval_id,
                ApprovalDecisionRequest(
                    decision=ApprovalDecision.APPROVE,
                    actor_id="plant-operations-owner-role",
                    actor_scopes=[scope],
                    note="Approved through the governed flow.",
                ),
            )

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        first = get_persisted_manufacturing_approval_inbox(repository, "tenant_demo_manufacturing")
        replayed = reconcile_inbox_with_decision_records(
            repository,
            "tenant_demo_manufacturing",
            first,
        )

    assert first.queue_status == OverviewStatus.READY
    assert replayed.queue_status == OverviewStatus.READY
    assert all(item.status == "decided" for item in replayed.approvals)


def test_derived_queue_status_covers_pending_high_risk_watch_and_ready() -> None:
    def item(approval_id: str, risk_level: str, status: str) -> ApprovalInboxItem:
        return ApprovalInboxItem(
            approval_id=approval_id,
            action="Review proposal",
            risk_level=risk_level,
            status=status,
            requested_by="supply-risk-agent",
            owner_role="plant-operations-owner",
            due="Today 17:30",
            workflow_id="wf_supplier_delay_review",
            domain="Supply",
            summary="Reference summary.",
            evidence=["Evidence"],
            data_accessed=["MES: schedule"],
            risks=["Budget overrun."],
            alternatives=["Hold the order."],
            estimated_cost="No direct spend",
            model_policy="local-only",
            required_permission="approvals:supply:decide",
            audit_event_preview={
                "event": "approval.decision.recorded",
                "actor_role": "plant-operations-owner",
                "scope": "wf_supplier_delay_review",
                "result": "workflow_signal_ready",
            },
            decision_options=[
                {
                    "decision": "approve",
                    "label": "Approve",
                    "consequence": "Signal workflow approval.",
                },
            ],
        )

    assert (
        derived_queue_status([item("a", "high", "pending"), item("b", "low", "decided")])
        == OverviewStatus.ACTION_REQUIRED
    )
    assert (
        derived_queue_status([item("a", "medium", "pending"), item("b", "high", "decided")])
        == OverviewStatus.WATCH
    )
    assert derived_queue_status([item("a", "high", "decided")]) == OverviewStatus.READY
    assert derived_queue_status([]) == OverviewStatus.READY


async def test_inbox_queue_status_survives_a_stale_stored_projection(
    session_factory: sessionmaker[Session],
) -> None:
    """A stored ``queue_status`` that contradicts its items cannot surface.

    If a payload was persisted while decisions existed (or with a hand-edited
    projection), reading the inbox must still report what the items say.
    """
    payload = approval_inbox_bootstrap_payload()
    payload["queue_status"] = "ready"  # Stale: the seeded items are pending/high risk.
    seed_approval_inbox_reference(session_factory, payload)

    with session_scope(session_factory) as session:
        inbox = get_persisted_manufacturing_approval_inbox(
            AxisPersistenceRepository(session),
            "tenant_demo_manufacturing",
        )

    assert inbox.queue_status == OverviewStatus.ACTION_REQUIRED
    assert any(
        item.risk_level == "high" and item.status == "pending"
        for item in inbox.approvals
    )
