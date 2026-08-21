from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.action_reference import ActionReferenceRecordNotFound
from axis_api.action_runs import (
    ActionPayloadValidationError,
    ActionPermissionDenied,
    ActionRunIdempotencyConflict,
    ActionRunOutcomeConflict,
    ActionRunOutcomePermissionDenied,
    ActionRunOutcomeRequest,
    ActionRunOutcomeValidationError,
    ActionRunRequest,
    DemoActionRunNotFound,
    record_demo_action_run,
    record_demo_action_run_outcome,
)
from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.identity import OidcPrincipal
from axis_api.main import create_app
from axis_api.models import ActionRun, AuditEvent, Base, WorkflowRunRecord, WorkflowTimelineRecord
from axis_api.ontology_reference import OntologyReferenceRecordNotFound
from axis_api.persistence import (
    ActionRunCreate,
    ActionRunResultRecord,
    AxisPersistenceRepository,
    DemoReferenceRecordCreate,
    WorkflowRunCreate,
    WorkflowTimelineEventCreate,
)
from axis_api.workflow_runtime import WorkflowSignalError, WorkflowSignalResult


class RecordingActionWorkflowRuntime:
    def __init__(self) -> None:
        self.requests: list[object] = []

    async def signal_action_run(self, request: object) -> WorkflowSignalResult:
        self.requests.append(request)
        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="action_signal_requested",
            adapter="axis-test-action-workflow-adapter",
            signal_name=request.signal_name,
            payload={
                "action_id": request.action_id,
                "action_run_id": str(request.action_run_id),
                "idempotency_key": request.idempotency_key,
                "approval_id": request.approval_id,
                "payload_field_names": sorted(request.payload.keys()),
            },
        )


class FailingActionWorkflowRuntime:
    async def signal_action_run(self, request: object) -> WorkflowSignalResult:
        raise WorkflowSignalError("synthetic_action_runtime_down")


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
    seed_action_registry_reference(factory)
    seed_ontology_reference(factory)
    yield factory
    engine.dispose()


@pytest.fixture
def action_registry_only_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    seed_action_registry_reference(factory)
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


def action_registry_payload() -> dict:
    migration = run_path("migrations/versions/0025_action_registry_reference.py")
    return deepcopy(migration["ACTION_REGISTRY_PAYLOAD"])


def ontology_reference_payload() -> dict:
    migration = run_path("migrations/versions/0030_ontology_reference.py")
    return deepcopy(migration["ONTOLOGY_PAYLOAD"])


def persisted_only_action_registry_payload() -> dict:
    payload = action_registry_payload()
    action = deepcopy(payload["actions"][0])
    action["definition"]["action_id"] = "persisted_custom_daily_brief"
    action["definition"]["display_name"] = "Persisted custom daily brief"
    action["definition"]["required_permissions"] = ["actions:read"]
    action["connected_agents"] = ["agent_persisted_daily_brief"]
    action["workflow_bindings"] = []
    action["approval_refs"] = []
    payload["scenario"] = "Persisted action run registry"
    payload["schema_version"] = "persisted-test-version"
    payload["actions"] = [action]
    payload["filter_options"] = {
        "domains": ["Operations"],
        "risk_levels": ["low"],
        "approval_modes": ["not_required"],
        "statuses": ["available_for_preview"],
    }
    return payload


def seed_action_registry_reference(
    factory: sessionmaker[Session],
    payload: dict | None = None,
    tenant_id: str = "tenant_demo_manufacturing",
) -> None:
    registry_payload = deepcopy(payload or action_registry_payload())
    registry_payload["tenant_id"] = tenant_id
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=tenant_id,
                surface="actions",
                reference_id="manufacturing-action-registry",
                status="active",
                source="bootstrap",
                version=registry_payload["schema_version"],
                payload=registry_payload,
            )
        )


def seed_ontology_reference(
    factory: sessionmaker[Session],
    payload: dict | None = None,
) -> None:
    ontology_payload = deepcopy(payload or ontology_reference_payload())
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id="tenant_demo_manufacturing",
                surface="ontology",
                reference_id="manufacturing-ontology",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=ontology_payload,
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


def seed_approved_supplier_action_run(
    repository: AxisPersistenceRepository,
    *,
    idempotency_key: str = "supplier-expedite-approved-run",
    action_id: str = "request_supplier_expedite",
    status: str = "approved_for_execution",
) -> ActionRun:
    return repository.create_action_run(
        ActionRunCreate(
            tenant_id="tenant_demo_manufacturing",
            action_id=action_id,
            idempotency_key=idempotency_key,
            execution_mode="approval_gated_dry_run",
            requested_by="agent_supply_risk",
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
            status=status,
        )
    )


def supplier_action_request(
    *,
    idempotency_key: str = "tenant_demo_manufacturing:request_supplier_expedite:test",
    reason: str = "Line 2 packaging risk",
) -> ActionRunRequest:
    return ActionRunRequest(
        actor_id="agent_supply_risk",
        actor_scopes=["supply:read", "approvals:supply:request"],
        idempotency_key=idempotency_key,
        payload={
            "supplier_batch_id": "asset_motors_batch",
            "target_arrival": "2026-06-22T08:00:00+02:00",
            "reason": reason,
            "cost_ceiling_eur": "1200",
        },
    )


def supplier_outcome_request(
    *,
    idempotency_key: str = "supplier-expedite-outcome-1",
    result_summary: str = "Supplier expedite dry-run package generated.",
) -> ActionRunOutcomeRequest:
    return ActionRunOutcomeRequest(
        actor_id="workflow-runtime",
        actor_scopes=["actions:result:record"],
        idempotency_key=idempotency_key,
        status="dry_run_completed",
        result_summary=result_summary,
        evidence_refs=["audit_supplier_expedite_preview"],
        metrics={"external_mutations": 0, "records_written": 0},
    )


def persisted_only_action_request() -> ActionRunRequest:
    return ActionRunRequest(
        actor_id="agent_persisted_daily_brief",
        actor_scopes=["actions:read"],
        payload={
            "tenant_id": "tenant_demo_manufacturing",
            "scope": "daily_operations",
            "evidence_refs": ["audit_persisted_reference"],
        },
    )


def test_action_run_path_does_not_load_demo_action_registry_seed() -> None:
    source = Path("src/axis_api/action_runs.py").read_text()

    assert "get_manufacturing_action_registry" not in source


def test_action_run_path_does_not_load_demo_ontology_seed() -> None:
    source = Path("src/axis_api/action_runs.py").read_text()

    assert "get_manufacturing_ontology" not in source


async def test_record_demo_action_run_reads_persisted_action_registry_reference(
    session_factory: sessionmaker[Session],
) -> None:
    seed_action_registry_reference(session_factory, persisted_only_action_registry_payload())

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        result = await record_demo_action_run(
            repository,
            "persisted_custom_daily_brief",
            persisted_only_action_request(),
        )

    with session_factory() as session:
        action_run = session.scalars(select(ActionRun)).one()

    assert result.action_id == "persisted_custom_daily_brief"
    assert result.status == "preview_generated"
    assert action_run.payload["schema_version"] == "persisted-test-version"
    assert action_run.payload["input"]["evidence_refs"] == ["audit_persisted_reference"]


async def test_record_action_run_uses_the_explicit_tenant_registry_and_persistence_scope(
    session_factory: sessionmaker[Session],
) -> None:
    tenant_id = "tenant_beta"
    seed_action_registry_reference(
        session_factory,
        persisted_only_action_registry_payload(),
        tenant_id=tenant_id,
    )
    request = persisted_only_action_request().model_copy(
        update={"payload": {**persisted_only_action_request().payload, "tenant_id": tenant_id}}
    )

    with session_scope(session_factory) as session:
        result = await record_demo_action_run(
            AxisPersistenceRepository(session),
            "persisted_custom_daily_brief",
            request,
            tenant_id=tenant_id,
        )

    with session_factory() as session:
        action_run = session.scalars(
            select(ActionRun).where(ActionRun.tenant_id == tenant_id)
        ).one()
        audit_event = session.scalars(
            select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
        ).one()

    assert result.tenant_id == tenant_id
    assert action_run.tenant_id == tenant_id
    assert audit_event.tenant_id == tenant_id


async def test_record_action_run_rejects_payload_tenant_mismatch_without_side_effects(
    session_factory: sessionmaker[Session],
) -> None:
    tenant_id = "tenant_beta"
    seed_action_registry_reference(
        session_factory,
        persisted_only_action_registry_payload(),
        tenant_id=tenant_id,
    )

    with session_scope(session_factory) as session:
        with pytest.raises(ActionPayloadValidationError) as caught:
            await record_demo_action_run(
                AxisPersistenceRepository(session),
                "persisted_custom_daily_brief",
                persisted_only_action_request(),
                tenant_id=tenant_id,
            )
        assert caught.value.issues == ["tenant_mismatch:tenant_id"]

    with session_factory() as session:
        assert session.scalars(
            select(ActionRun).where(ActionRun.tenant_id == tenant_id)
        ).all() == []
        assert session.scalars(
            select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
        ).all() == []


async def test_record_demo_action_run_requires_persisted_action_registry_reference(
    empty_session_factory: sessionmaker[Session],
) -> None:
    with session_scope(empty_session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(ActionReferenceRecordNotFound):
            await record_demo_action_run(
                repository,
                "request_supplier_expedite",
                supplier_action_request(),
            )


async def test_record_demo_action_run_requires_persisted_ontology_reference(
    action_registry_only_session_factory: sessionmaker[Session],
) -> None:
    with session_scope(action_registry_only_session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(OntologyReferenceRecordNotFound):
            await record_demo_action_run(
                repository,
                "request_supplier_expedite",
                supplier_action_request(),
            )


async def test_record_demo_action_run_persists_run_and_audit_event(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        result = await record_demo_action_run(
            repository,
            "request_supplier_expedite",
            supplier_action_request(),
        )

    with session_factory() as session:
        action_run = session.scalars(select(ActionRun)).one()
        audit_event = session.scalars(select(AuditEvent)).one()

    assert result.persisted is True
    assert result.idempotent_replay is False
    assert result.action_run_id == action_run.id
    assert result.action_id == "request_supplier_expedite"
    assert result.status == "approval_required"
    assert result.execution_mode == "approval_gated_dry_run"
    assert result.requested_by == "agent_supply_risk"
    assert result.approval_required is True
    assert result.approval_id == "appr_expedite_supplier_batch"
    assert result.workflow_id == "wf_supplier_delay_review"
    assert result.permission_decision.allowed is True
    assert result.audit_event_id == audit_event.id
    assert result.audit_event_type == "action.proposal.created"
    assert action_run.payload["input"]["supplier_batch_id"] == "asset_motors_batch"
    assert audit_event.event_type == "action.proposal.created"
    assert audit_event.payload["action_run_id"] == str(action_run.id)
    assert audit_event.payload["permission_decision"] == {"allowed": True, "reason": "allowed"}
    assert audit_event.payload["payload_field_names"] == [
        "cost_ceiling_eur",
        "reason",
        "supplier_batch_id",
        "target_arrival",
    ]


async def test_record_demo_action_run_uses_persisted_ontology_relationship_scopes(
    session_factory: sessionmaker[Session],
) -> None:
    ontology_payload = ontology_reference_payload()
    for relationship in ontology_payload["relationships"]:
        if relationship["relationship_id"] == "rel_supplier_batch_impacts_line":
            relationship["permission_scope"] = "persisted:supply:read"
    seed_ontology_reference(session_factory, ontology_payload)
    request = supplier_action_request()
    request.actor_scopes = [
        "supply:read",
        "persisted:supply:read",
        "approvals:supply:request",
    ]
    request.idempotency_key = "persisted-ontology-scope"

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        result = await record_demo_action_run(
            repository,
            "request_supplier_expedite",
            request,
        )

    with session_factory() as session:
        audit_event = session.scalars(select(AuditEvent)).one()

    assert result.permission_decision.allowed is True
    assert audit_event.payload["relationship_scopes"] == ["persisted:supply:read"]


async def test_record_demo_action_run_signals_bound_workflow_after_persistence(
    session_factory: sessionmaker[Session],
) -> None:
    workflow_runtime = RecordingActionWorkflowRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        result = await record_demo_action_run(
            repository,
            "request_supplier_expedite",
            supplier_action_request(),
            workflow_runtime,
        )

    with session_factory() as session:
        action_run = session.scalars(select(ActionRun)).one()
        audit_event = session.scalars(select(AuditEvent)).one()

    assert result.workflow_signal_status == "action_signal_requested"
    assert result.workflow_signal is not None
    assert result.workflow_signal.payload == {
        "action_id": "request_supplier_expedite",
        "action_run_id": str(action_run.id),
        "idempotency_key": "tenant_demo_manufacturing:request_supplier_expedite:test",
        "approval_id": "appr_expedite_supplier_batch",
        "payload_field_names": [
            "cost_ceiling_eur",
            "reason",
            "supplier_batch_id",
            "target_arrival",
        ],
    }
    assert workflow_runtime.requests[0].workflow_id == "wf_supplier_delay_review"
    assert workflow_runtime.requests[0].action_id == "request_supplier_expedite"
    assert workflow_runtime.requests[0].action_run_id == action_run.id
    assert workflow_runtime.requests[0].approval_id == "appr_expedite_supplier_batch"
    assert workflow_runtime.requests[0].payload["supplier_batch_id"] == "asset_motors_batch"
    assert audit_event.payload["workflow_signal"]["status"] == "action_signal_requested"
    assert audit_event.payload["workflow_signal"]["payload"]["payload_field_names"] == [
        "cost_ceiling_eur",
        "reason",
        "supplier_batch_id",
        "target_arrival",
    ]
    assert "payload" not in audit_event.payload["workflow_signal"]["payload"]


async def test_record_demo_action_run_updates_persisted_workflow_history(
    session_factory: sessionmaker[Session],
) -> None:
    workflow_runtime = RecordingActionWorkflowRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_supplier_delay_workflow(repository)
        result = await record_demo_action_run(
            repository,
            "request_supplier_expedite",
            supplier_action_request(),
            workflow_runtime,
        )

    with session_factory() as session:
        workflow_run = session.scalars(select(WorkflowRunRecord)).one()
        timeline = list(
            session.scalars(
                select(WorkflowTimelineRecord).order_by(WorkflowTimelineRecord.sequence)
            )
        )

    assert result.workflow_state_updated is True
    assert result.workflow_state == "action_proposed"
    assert result.workflow_status == "action_required"
    assert workflow_run.state == "action_proposed"
    assert workflow_run.status == "action_required"
    assert workflow_run.current_step == "Action proposal recorded"
    assert workflow_run.replay_ready is True
    assert workflow_run.pending_signals[-1] == {
        "signal": "action.requested",
        "status": "action_signal_requested",
        "action_id": "request_supplier_expedite",
        "action_run_id": str(result.action_run_id),
        "approval_id": "appr_expedite_supplier_batch",
        "idempotency_key": "tenant_demo_manufacturing:request_supplier_expedite:test",
    }
    assert timeline[-1].sequence == 2
    assert timeline[-1].event == "workflow.action_run.recorded"
    assert timeline[-1].actor == "agent_supply_risk"
    assert timeline[-1].result == "action_signal_requested"
    assert str(result.action_run_id) in timeline[-1].summary


async def test_record_demo_action_run_records_signal_failure_without_blocking_persistence(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        result = await record_demo_action_run(
            repository,
            "request_supplier_expedite",
            supplier_action_request(),
            FailingActionWorkflowRuntime(),
        )

    with session_factory() as session:
        action_run = session.scalars(select(ActionRun)).one()
        audit_event = session.scalars(select(AuditEvent)).one()

    assert action_run.status == "approval_required"
    assert result.workflow_signal_status == "runtime_signal_unavailable"
    assert result.workflow_signal is not None
    assert result.workflow_signal.payload["reason"] == "synthetic_action_runtime_down"
    assert audit_event.payload["workflow_signal"]["status"] == "runtime_signal_unavailable"


async def test_record_demo_action_run_outcome_persists_audit_and_workflow_history(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_supplier_delay_workflow(repository)
        action_run = seed_approved_supplier_action_run(repository)
        result = await record_demo_action_run_outcome(
            repository,
            action_run.id,
            supplier_outcome_request(),
        )

    with session_factory() as session:
        persisted_action_run = session.scalars(select(ActionRun)).one()
        audit_event = session.scalars(select(AuditEvent)).one()
        workflow_run = session.scalars(select(WorkflowRunRecord)).one()
        timeline = list(
            session.scalars(
                select(WorkflowTimelineRecord).order_by(WorkflowTimelineRecord.sequence)
            )
        )

    assert result.persisted is True
    assert result.idempotent_replay is False
    assert result.action_run_id == action_run.id
    assert result.status == "dry_run_completed"
    assert result.workflow_state_updated is True
    assert result.workflow_state == "action_completed"
    assert result.workflow_status == "ready"
    assert result.audit_event_id == audit_event.id
    assert persisted_action_run.status == "dry_run_completed"
    assert persisted_action_run.result_payload == {
        "source": "action_run_outcome",
        "outcome_idempotency_key": "supplier-expedite-outcome-1",
        "status": "dry_run_completed",
        "result_summary": "Supplier expedite dry-run package generated.",
        "evidence_refs": ["audit_supplier_expedite_preview"],
        "metrics": {"external_mutations": 0, "records_written": 0},
        "external_mutation_started": False,
        "recorded_by": "workflow-runtime",
    }
    assert audit_event.event_type == "action.run.outcome.recorded"
    assert audit_event.payload["action_run_id"] == str(action_run.id)
    assert audit_event.payload["status"] == "dry_run_completed"
    assert audit_event.payload["result_summary"] == (
        "Supplier expedite dry-run package generated."
    )
    assert audit_event.payload["external_mutation_started"] is False
    assert workflow_run.state == "action_completed"
    assert workflow_run.status == "ready"
    assert workflow_run.current_step == "Action outcome recorded"
    assert workflow_run.blocker is None
    assert workflow_run.pending_signals[-1] == {
        "signal": "action.outcome",
        "status": "dry_run_completed",
        "action_id": "request_supplier_expedite",
        "action_run_id": str(action_run.id),
        "idempotency_key": "supplier-expedite-outcome-1",
    }
    assert timeline[-1].event == "workflow.action_run.completed"
    assert timeline[-1].actor == "workflow-runtime"
    assert timeline[-1].result == "dry_run_completed"
    assert str(action_run.id) in timeline[-1].summary


async def test_record_demo_action_run_outcome_is_idempotent_without_duplicate_audit(
    session_factory: sessionmaker[Session],
) -> None:
    request = supplier_outcome_request()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        action_run = seed_approved_supplier_action_run(repository)
        first = await record_demo_action_run_outcome(repository, action_run.id, request)
        second = await record_demo_action_run_outcome(repository, action_run.id, request)

    with session_factory() as session:
        audit_events = list(session.scalars(select(AuditEvent)))
        action_runs = list(session.scalars(select(ActionRun)))

    assert first.action_run_id == second.action_run_id
    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert second.audit_event_id is None
    assert len(audit_events) == 1
    assert len(action_runs) == 1


async def test_record_demo_action_run_outcome_rejects_conflicting_or_unsafe_results(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        action_run = seed_approved_supplier_action_run(repository)
        await record_demo_action_run_outcome(
            repository,
            action_run.id,
            supplier_outcome_request(result_summary="First result."),
        )
        with pytest.raises(ActionRunOutcomeConflict):
            await record_demo_action_run_outcome(
                repository,
                action_run.id,
                supplier_outcome_request(result_summary="Changed result."),
            )
        unsafe_request = supplier_outcome_request(idempotency_key="unsafe-outcome")
        unsafe_request.external_mutation_started = True
        with pytest.raises(ActionRunOutcomeValidationError):
            await record_demo_action_run_outcome(repository, action_run.id, unsafe_request)


async def test_record_demo_action_run_outcome_requires_permission_and_existing_run(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        action_run = seed_approved_supplier_action_run(repository)
        denied_request = supplier_outcome_request()
        denied_request.actor_scopes = []
        with pytest.raises(ActionRunOutcomePermissionDenied):
            await record_demo_action_run_outcome(repository, action_run.id, denied_request)

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(DemoActionRunNotFound):
            await record_demo_action_run_outcome(
                repository,
                "00000000-0000-0000-0000-000000000000",
                supplier_outcome_request(idempotency_key="missing-run"),
            )


async def test_record_demo_action_run_replays_same_idempotency_key_without_duplicate_audit(
    session_factory: sessionmaker[Session],
) -> None:
    request = supplier_action_request()
    workflow_runtime = RecordingActionWorkflowRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        first = await record_demo_action_run(
            repository,
            "request_supplier_expedite",
            request,
            workflow_runtime,
        )
        second = await record_demo_action_run(
            repository,
            "request_supplier_expedite",
            request,
            workflow_runtime,
        )

    with session_factory() as session:
        action_runs = list(session.scalars(select(ActionRun)))
        audit_events = list(session.scalars(select(AuditEvent)))

    assert first.action_run_id == second.action_run_id
    assert second.idempotent_replay is True
    assert second.workflow_signal_status == "idempotent_replay"
    assert second.audit_event_id is None
    assert len(workflow_runtime.requests) == 1
    assert len(action_runs) == 1
    assert len(audit_events) == 1


async def test_record_demo_action_run_rejects_same_idempotency_key_with_different_payload(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        await record_demo_action_run(
            repository,
            "request_supplier_expedite",
            supplier_action_request(reason="Line 2 packaging risk"),
        )
        with pytest.raises(ActionRunIdempotencyConflict):
            await record_demo_action_run(
                repository,
                "request_supplier_expedite",
                supplier_action_request(reason="Changed payload"),
            )

    with session_factory() as session:
        assert len(list(session.scalars(select(ActionRun)))) == 1
        assert len(list(session.scalars(select(AuditEvent)))) == 1


async def test_record_demo_action_run_denies_actor_without_required_scope(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(ActionPermissionDenied, match="missing_scope:approvals:supply:request"):
            await record_demo_action_run(
                repository,
                "request_supplier_expedite",
                ActionRunRequest(
                    actor_id="agent_quality_risk",
                    actor_scopes=["supply:read"],
                    idempotency_key="denied-key",
                    payload=supplier_action_request().payload,
                ),
            )

    with session_factory() as session:
        assert list(session.scalars(select(ActionRun))) == []
        assert list(session.scalars(select(AuditEvent))) == []


async def test_record_demo_action_run_denies_cross_domain_payload_relationship(
    session_factory: sessionmaker[Session],
) -> None:
    payload = supplier_action_request().payload | {"supplier_batch_id": "asset_batch_q_1842"}
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(
            ActionPermissionDenied,
            match="missing_relationship_scope:quality:read",
        ):
            await record_demo_action_run(
                repository,
                "request_supplier_expedite",
                ActionRunRequest(
                    actor_id="agent_supply_risk",
                    actor_scopes=["supply:read", "approvals:supply:request"],
                    idempotency_key="cross-domain-payload",
                    payload=payload,
                ),
            )

    with session_factory() as session:
        assert list(session.scalars(select(ActionRun))) == []
        assert list(session.scalars(select(AuditEvent))) == []


async def test_record_demo_action_run_validates_typed_payload_before_persistence(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(ActionPayloadValidationError) as exc_info:
            await record_demo_action_run(
                repository,
                "request_supplier_expedite",
                ActionRunRequest(
                    actor_id="agent_supply_risk",
                    actor_scopes=["supply:read", "approvals:supply:request"],
                    idempotency_key="invalid-payload",
                    payload={"supplier_batch_id": "asset_motors_batch"},
                ),
            )

    assert "missing_required:target_arrival" in exc_info.value.issues
    with session_factory() as session:
        assert list(session.scalars(select(ActionRun))) == []
        assert list(session.scalars(select(AuditEvent))) == []


async def test_record_demo_action_run_derives_optional_idempotency_for_preview_action(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        result = await record_demo_action_run(
            repository,
            "generate_daily_plant_brief",
            ActionRunRequest(
                actor_id="agent_daily_brief",
                actor_scopes=["briefs:generate", "audit:read", "workflows:read"],
                payload={
                    "tenant_id": "tenant_demo_manufacturing",
                    "scope": "daily_operations",
                    "evidence_refs": [
                        "wf_supplier_delay_review",
                        "audit_20260621_154000_ontology_read",
                    ],
                },
            ),
        )

    assert result.status == "preview_generated"
    assert result.approval_required is False
    assert result.idempotency_key == (
        "tenant_demo_manufacturing:generate_daily_plant_brief:agent_daily_brief:preview"
    )
    assert result.audit_event_type == "action.preview.generated"


def test_action_run_endpoint_returns_created_then_idempotent_replay(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.workflow_runtime = RecordingActionWorkflowRuntime()
    client = TestClient(app)
    payload = supplier_action_request().model_dump()

    first = client.post(
        "/demo/manufacturing/actions/request_supplier_expedite/runs",
        json=payload,
    )
    second = client.post(
        "/demo/manufacturing/actions/request_supplier_expedite/runs",
        json=payload,
    )

    assert first.status_code == 201
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["action_run_id"] == second_body["action_run_id"]
    assert first_body["idempotent_replay"] is False
    assert first_body["workflow_signal_status"] == "action_signal_requested"
    assert first_body["workflow_signal"]["signal_name"] == "action_requested"
    assert second_body["idempotent_replay"] is True
    assert second_body["workflow_signal_status"] == "idempotent_replay"
    assert second_body["workflow_signal"] is None
    assert second_body["audit_event_id"] is None
    assert len(app.state.workflow_runtime.requests) == 1


def test_action_run_endpoint_binds_actor_and_scopes_from_oidc_token(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.workflow_runtime = RecordingActionWorkflowRuntime()
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="agent_supply_risk",
            tenant_id="tenant_demo_manufacturing",
            scopes=["supply:read", "approvals:supply:request"],
        )
    )
    client = TestClient(app)
    payload = supplier_action_request().model_dump()
    payload["actor_scopes"] = []

    response = client.post(
        "/demo/manufacturing/actions/request_supplier_expedite/runs",
        headers={"Authorization": "Bearer valid-token"},
        json=payload,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["requested_by"] == "agent_supply_risk"
    assert body["permission_decision"] == {"allowed": True, "reason": "allowed"}
    with session_factory() as session:
        audit_event = session.scalars(select(AuditEvent)).one()
    assert audit_event.actor_id == "agent_supply_risk"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/demo/manufacturing/actions/request_supplier_expedite/runs",
            supplier_action_request().model_dump(),
        ),
        (
            "/demo/manufacturing/actions/runs/00000000-0000-0000-0000-000000000001/outcome",
            supplier_outcome_request().model_dump(),
        ),
        (
            "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
            {
                "decision": "approve",
                "actor_id": "plant-operations-owner-role",
                "actor_scopes": ["approvals:supply:decide"],
            },
        ),
    ],
)
def test_governed_write_endpoints_require_authentication_for_non_demo_tenants(
    session_factory: sessionmaker[Session],
    path: str,
    payload: dict,
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory

    response = TestClient(app).post(f"{path}?tenant_id=tenant_beta", json=payload)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"
    with session_factory() as session:
        assert session.scalars(select(AuditEvent)).all() == []


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/demo/manufacturing/actions/request_supplier_expedite/runs",
            supplier_action_request().model_dump(),
        ),
        (
            "/demo/manufacturing/actions/runs/00000000-0000-0000-0000-000000000001/outcome",
            supplier_outcome_request().model_dump(),
        ),
        (
            "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
            {
                "decision": "approve",
                "actor_id": "agent_supply_risk",
                "actor_scopes": ["approvals:supply:decide"],
            },
        ),
    ],
)
def test_governed_write_endpoints_reject_cross_tenant_principals(
    session_factory: sessionmaker[Session],
    path: str,
    payload: dict,
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="agent_supply_risk",
            tenant_id="tenant_alpha",
            scopes=["approvals:supply:decide", "actions:result:record"],
        )
    )

    response = TestClient(app).post(
        f"{path}?tenant_id=tenant_beta",
        headers={"Authorization": "Bearer valid-token"},
        json=payload,
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "tenant_mismatch"
    with session_factory() as session:
        assert session.scalars(select(AuditEvent)).all() == []


def test_action_run_endpoint_reports_missing_action_registry_reference(
    empty_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = empty_session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/actions/request_supplier_expedite/runs",
        json=supplier_action_request().model_dump(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "NOT_FOUND",
        "message": "Manufacturing action registry reference record not found.",
        "surface": "actions",
    }


def test_action_run_endpoint_reports_missing_ontology_reference(
    action_registry_only_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = action_registry_only_session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/actions/request_supplier_expedite/runs",
        json=supplier_action_request().model_dump(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "NOT_FOUND",
        "message": "Manufacturing ontology reference record not found.",
        "surface": "ontology",
    }


def test_action_run_endpoint_returns_validation_and_permission_errors(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    invalid_payload = client.post(
        "/demo/manufacturing/actions/request_supplier_expedite/runs",
        json={
            "actor_id": "agent_supply_risk",
            "actor_scopes": ["supply:read", "approvals:supply:request"],
            "idempotency_key": "invalid-payload",
            "payload": {"supplier_batch_id": "asset_motors_batch"},
        },
    )
    denied = client.post(
        "/demo/manufacturing/actions/request_supplier_expedite/runs",
        json={
            "actor_id": "agent_quality_risk",
            "actor_scopes": ["quality:read"],
            "idempotency_key": "denied-key",
            "payload": supplier_action_request().payload,
        },
    )
    missing = client.post(
        "/demo/manufacturing/actions/missing/runs",
        json=supplier_action_request(idempotency_key="missing-action").model_dump(),
    )

    assert invalid_payload.status_code == 422
    assert invalid_payload.json()["detail"]["code"] == "VALIDATION_FAILED"
    assert "missing_required:target_arrival" in invalid_payload.json()["detail"]["issues"]
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "PERMISSION_DENIED"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Action not found"


def typed_fields_action_registry_payload() -> dict:
    payload = action_registry_payload()
    for action in payload["actions"]:
        if action["definition"]["action_id"] == "generate_daily_plant_brief":
            properties = action["definition"]["input_schema"]["properties"]
            properties["requested_amount"] = {"type": "number"}
            properties["retry_count"] = {"type": "integer"}
            properties["dry_run"] = {"type": "boolean"}
    return payload


def _daily_brief_run_body(idempotency_key: str, payload_fields: dict) -> dict:
    return {
        "actor_id": "agent_daily_brief",
        "actor_scopes": ["briefs:generate", "audit:read", "workflows:read"],
        "idempotency_key": idempotency_key,
        "payload": {
            "tenant_id": "tenant_demo_manufacturing",
            "scope": "daily_operations",
            "evidence_refs": ["wf_supplier_delay_review"],
            **payload_fields,
        },
    }


def test_action_run_endpoint_rejects_wrong_typed_number_integer_boolean_fields(
    session_factory: sessionmaker[Session],
) -> None:
    seed_action_registry_reference(session_factory, typed_fields_action_registry_payload())
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    cases = {
        "number-string": {"requested_amount": "not-a-number"},
        "number-numeric-string": {"requested_amount": "1500"},
        "number-bool": {"requested_amount": True},
        "integer-float": {"retry_count": 1.5},
        "integer-bool": {"retry_count": True},
        "boolean-string": {"dry_run": "yes"},
    }
    for label, fields in cases.items():
        response = client.post(
            "/demo/manufacturing/actions/generate_daily_plant_brief/runs",
            json=_daily_brief_run_body(f"daily-brief-typed-{label}", fields),
        )
        assert response.status_code == 422, label
        detail = response.json()["detail"]
        assert detail["code"] == "VALIDATION_FAILED", label
        field_name = next(iter(fields))
        assert any(
            issue.startswith(f"invalid_type:{field_name}:") for issue in detail["issues"]
        ), label


def test_action_run_endpoint_accepts_well_typed_number_integer_boolean_fields(
    session_factory: sessionmaker[Session],
) -> None:
    seed_action_registry_reference(session_factory, typed_fields_action_registry_payload())
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/actions/generate_daily_plant_brief/runs",
        json=_daily_brief_run_body(
            "daily-brief-typed-valid",
            {"requested_amount": 1500.5, "retry_count": 3, "dry_run": True},
        ),
    )

    assert response.status_code == 201
    assert response.json()["status"] == "preview_generated"


def test_field_type_matches_rejects_non_finite_numbers() -> None:
    from axis_api.action_runs import _field_type_matches

    assert _field_type_matches(1500, "number") is True
    assert _field_type_matches(1500.5, "number") is True
    assert _field_type_matches(float("nan"), "number") is False
    assert _field_type_matches(float("inf"), "number") is False
    assert _field_type_matches(True, "number") is False
    assert _field_type_matches("1500", "number") is False
    assert _field_type_matches(3, "integer") is True
    assert _field_type_matches(3.0, "integer") is False
    assert _field_type_matches(True, "integer") is False
    assert _field_type_matches(False, "boolean") is True
    assert _field_type_matches({"nested": "value"}, "object") is True
    assert _field_type_matches(["nested"], "object") is False


def test_action_run_endpoint_returns_idempotency_conflict(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    first = client.post(
        "/demo/manufacturing/actions/request_supplier_expedite/runs",
        json=supplier_action_request(reason="Line 2 packaging risk").model_dump(),
    )
    conflict = client.post(
        "/demo/manufacturing/actions/request_supplier_expedite/runs",
        json=supplier_action_request(reason="Changed payload").model_dump(),
    )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "POLICY_VIOLATION"
    assert conflict.json()["detail"]["action_run_id"] == first.json()["action_run_id"]


def test_action_run_outcome_endpoint_persists_result(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    with session_scope(session_factory) as session:
        action_run = seed_approved_supplier_action_run(AxisPersistenceRepository(session))

    first = client.post(
        f"/demo/manufacturing/actions/runs/{action_run.id}/outcome",
        json=supplier_outcome_request().model_dump(),
    )
    second = client.post(
        f"/demo/manufacturing/actions/runs/{action_run.id}/outcome",
        json=supplier_outcome_request().model_dump(),
    )

    assert first.status_code == 201
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    assert first_body["action_run_id"] == str(action_run.id)
    assert first_body["status"] == "dry_run_completed"
    assert first_body["audit_event_type"] == "action.run.outcome.recorded"
    assert first_body["permission_decision"] == {"allowed": True, "reason": "allowed"}
    assert second_body["idempotent_replay"] is True
    assert second_body["audit_event_id"] is None


def test_action_run_list_endpoint_orders_filters_and_bounds_limit(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    observed_at = datetime.now(UTC)
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        oldest = seed_approved_supplier_action_run(
            repository,
            idempotency_key="listed-oldest",
            status="execution_completed",
        )
        middle = seed_approved_supplier_action_run(
            repository,
            idempotency_key="listed-middle",
            action_id="shift_maintenance_window",
        )
        newest = seed_approved_supplier_action_run(
            repository,
            idempotency_key="listed-newest",
        )
        other_tenant = repository.create_action_run(
            ActionRunCreate(
                tenant_id="tenant_other",
                action_id="request_supplier_expedite",
                idempotency_key="listed-other-tenant",
                execution_mode="approval_gated_dry_run",
                requested_by="other-tenant-agent",
                status="approved_for_execution",
            )
        )
        oldest.created_at = observed_at - timedelta(hours=3)
        middle.created_at = observed_at - timedelta(hours=2)
        newest.created_at = observed_at - timedelta(hours=1)
        other_tenant.created_at = observed_at

    listed = client.get(
        "/operations/actions/runs",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )
    approved = client.get(
        "/operations/actions/runs",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "status": "approved_for_execution",
        },
    )
    action_filtered = client.get(
        "/operations/actions/runs",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "action_id": "request_supplier_expedite",
        },
    )
    limited = client.get(
        "/operations/actions/runs",
        params={"tenant_id": "tenant_demo_manufacturing", "limit": 1},
    )

    assert listed.status_code == 200
    assert [run["action_run_id"] for run in listed.json()["runs"]] == [
        str(newest.id),
        str(middle.id),
        str(oldest.id),
    ]
    assert [run["action_run_id"] for run in approved.json()["runs"]] == [
        str(newest.id),
        str(middle.id),
    ]
    assert [run["action_run_id"] for run in action_filtered.json()["runs"]] == [
        str(newest.id),
        str(oldest.id),
    ]
    assert [run["action_run_id"] for run in limited.json()["runs"]] == [str(newest.id)]
    assert client.get("/operations/actions/runs", params={"limit": 0}).status_code == 422
    assert client.get("/operations/actions/runs", params={"limit": 201}).status_code == 422


def test_action_run_list_endpoint_reports_outcome_and_derived_waiting_duration(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    observed_at = datetime.now(UTC)
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        pending = seed_approved_supplier_action_run(
            repository,
            idempotency_key="listed-pending-outcome",
        )
        completed = seed_approved_supplier_action_run(
            repository,
            idempotency_key="listed-reported-outcome",
        )
        pending.created_at = observed_at - timedelta(hours=1)
        completed.created_at = observed_at - timedelta(hours=2)
        repository.record_action_run_result(
            ActionRunResultRecord(
                tenant_id="tenant_demo_manufacturing",
                action_run_id=completed.id,
                status="execution_completed",
                result_payload={
                    "source": "action_run_outcome",
                    "result_summary": "External executor completed the approved action.",
                    "evidence_refs": ["audit_external_executor_completion"],
                },
            )
        )

    before_request = datetime.now(UTC)
    response = client.get(
        "/operations/actions/runs",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )
    after_request = datetime.now(UTC)

    assert response.status_code == 200
    runs_by_id = {run["action_run_id"]: run for run in response.json()["runs"]}
    pending_record = runs_by_id[str(pending.id)]
    completed_record = runs_by_id[str(completed.id)]
    assert pending_record["outcome"] is None
    assert int((before_request - pending.created_at).total_seconds()) <= pending_record[
        "waiting_duration_seconds"
    ] <= int((after_request - pending.created_at).total_seconds())
    assert completed_record["outcome"] == {
        "result_summary": "External executor completed the approved action.",
        "evidence_refs": ["audit_external_executor_completion"],
    }
    assert pending_record["approval_id"] == "appr_expedite_supplier_batch"
    assert pending_record["workflow_id"] == "wf_supplier_delay_review"
    assert pending_record["created_at"]
    assert pending_record["updated_at"]


def test_openapi_exposes_action_run_endpoint() -> None:
    client = TestClient(create_app())
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/demo/manufacturing/actions/{action_id}/runs" in response.json()["paths"]
    assert "/demo/manufacturing/actions/runs/{action_run_id}/outcome" in response.json()[
        "paths"
    ]
    assert "/operations/actions/runs" in response.json()["paths"]
