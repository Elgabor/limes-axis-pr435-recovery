from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    TenantCreate,
    WorkflowRunCreate,
    WorkflowTimelineEventCreate,
)
from axis_api.workflow_queries import WorkflowRunQuery, query_persisted_workflow_runs


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


def seed_workflow_runs(repository: AxisPersistenceRepository) -> None:
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
    repository.append_workflow_timeline_event(
        WorkflowTimelineEventCreate(
            tenant_id="tenant_demo_manufacturing",
            workflow_id="wf_supplier_delay_review",
            sequence=2,
            event="workflow.signal.awaiting",
            occurred_at=datetime(2026, 6, 21, 14, 18, tzinfo=UTC),
            actor="axis-temporal-adapter",
            result="waiting_for_approval",
            summary="Workflow paused at the human approval gate.",
        )
    )
    repository.create_workflow_run(
        WorkflowRunCreate(
            tenant_id="tenant_demo_manufacturing",
            workflow_id="wf_quality_hold_review",
            name="Quality Hold Review",
            domain="Quality",
            state="investigating",
            status="watch",
            owner_role="quality-owner",
            runtime="Temporal OSS",
            adapter="axis-temporal-adapter",
            autonomy_level="L2",
            started_at=datetime(2026, 6, 21, 13, 35, tzinfo=UTC),
            eta="Today 16:45",
            blocker="Quality owner must choose hold or manual review",
            objective="Decide whether Batch Q-1842 needs a quality hold.",
            current_step="Evidence review",
            related_risk="risk_quality_drift",
            related_assets=["asset_batch_q_1842"],
            inputs=["QMS sample inspection variance"],
            proposed_outputs=["Quality hold recommendation"],
            pending_signals=[
                {
                    "signal": "quality.owner.review",
                    "required_role": "quality-owner",
                    "status": "waiting",
                    "approval_id": "appr_quality_hold_batch",
                }
            ],
            controls=["approvals:quality:decide", "no-external-egress"],
            audit_scope="wf_quality_hold_review",
            replay_ready=False,
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
            started_at=datetime(2026, 6, 21, 12, 0, tzinfo=UTC),
            eta="Today 17:00",
            blocker=None,
            objective="Other tenant objective",
            current_step="Other step",
            related_risk="risk_other",
            related_assets=["asset_other"],
            inputs=["Other input"],
            proposed_outputs=["Other output"],
            pending_signals=[
                {
                    "signal": "other.signal",
                    "required_role": "other-owner",
                    "status": "waiting",
                    "approval_id": None,
                }
            ],
            controls=["other:decide"],
            audit_scope="wf_other",
            replay_ready=False,
        )
    )


def test_repository_lists_workflow_runs_and_history_tenant_scoped(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_workflow_runs(repository)
        runs = repository.list_workflow_runs("tenant_demo_manufacturing")
        history = repository.list_workflow_timeline_events(
            "tenant_demo_manufacturing",
            "wf_supplier_delay_review",
        )

    assert [run.workflow_id for run in runs] == [
        "wf_supplier_delay_review",
        "wf_quality_hold_review",
    ]
    assert [event.event for event in history] == [
        "workflow.started",
        "workflow.signal.awaiting",
    ]


def test_query_persisted_workflow_runs_maps_records_to_console(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_workflow_runs(repository)
        console = query_persisted_workflow_runs(
            repository,
            WorkflowRunQuery(tenant_id="tenant_demo_manufacturing"),
        )

    assert console.tenant_id == "tenant_demo_manufacturing"
    assert console.runtime_status == "ready"
    assert console.metrics[0].label == "Persisted Runs"
    assert console.metrics[0].value == "2"
    assert [run.workflow_id for run in console.workflow_runs] == [
        "wf_supplier_delay_review",
        "wf_quality_hold_review",
    ]
    assert console.workflow_runs[0].timeline[0].event == "workflow.started"
    assert console.workflow_runs[0].pending_signals[0].approval_id == (
        "appr_expedite_supplier_batch"
    )
    assert "tenant_other" not in console.model_dump_json()
    assert "password" not in console.model_dump_json().lower()
    assert "secret" not in console.model_dump_json().lower()


def test_query_persisted_workflow_runs_filters_by_state(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_workflow_runs(repository)
        console = query_persisted_workflow_runs(
            repository,
            WorkflowRunQuery(
                tenant_id="tenant_demo_manufacturing",
                state="waiting_for_approval",
            ),
        )

    assert [run.workflow_id for run in console.workflow_runs] == ["wf_supplier_delay_review"]
    assert console.workflow_runs[0].state == "waiting_for_approval"


def test_persisted_workflow_runs_endpoint_returns_tenant_scoped_history(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_workflow_runs(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/workflows/runs",
        params={"tenant_id": "tenant_demo_manufacturing", "limit": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["provenance"] == "live"
    assert body["metrics"][0]["value"] == "2"
    assert body["workflow_runs"][0]["workflow_id"] == "wf_supplier_delay_review"
    assert body["workflow_runs"][0]["timeline"][1]["event"] == "workflow.signal.awaiting"
    assert "tenant_other" not in str(body)


def test_persisted_workflow_runs_endpoint_returns_empty_console_for_empty_query(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/workflows/runs",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provenance"] == "empty"
    assert body["workflow_runs"] == []
    assert body["runtime_status"] == "watch"
    assert body["metrics"][0]["value"] == "0"


def test_openapi_exposes_persisted_workflow_runs_endpoint(openapi_schema: dict) -> None:
    assert "/demo/manufacturing/workflows/runs" in openapi_schema["paths"]
