from copy import deepcopy
from pathlib import Path
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.connector_manifests import (
    ConnectorManifestCreateRequest,
    ConnectorManifestLifecycleRequest,
    record_demo_connector_manifest,
    transition_demo_connector_manifest_lifecycle,
)
from axis_api.connector_manual_imports import (
    ConnectorManualImportCreateRequest,
    ConnectorManualImportDecisionRequest,
    ConnectorManualImportQuery,
    ConnectorManualImportValidationError,
    build_connector_manual_import_registry,
    record_demo_connector_manual_import,
    record_demo_connector_manual_import_decision,
)
from axis_api.connector_reference import ConnectorReferenceRecordNotFound
from axis_api.db import session_scope
from axis_api.demo import ApprovalDecision
from axis_api.main import create_app
from axis_api.models import ApprovalRecord, AuditEvent, Base, ConnectorManualImportRequest
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorManualImportRequestCreate,
    DemoReferenceRecordCreate,
)
from axis_api.workflow_runtime import (
    WorkflowConnectorManualImportSignalRequest,
    WorkflowSignalError,
    WorkflowSignalResult,
)


class RecordingManualImportWorkflowRuntime:
    def __init__(self) -> None:
        self.requests: list[WorkflowConnectorManualImportSignalRequest] = []

    async def signal_connector_manual_import(
        self,
        request: WorkflowConnectorManualImportSignalRequest,
    ) -> WorkflowSignalResult:
        self.requests.append(request)
        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="manual_import_signal_requested",
            adapter="axis-test-workflow-adapter",
            signal_name=request.signal_name,
            payload=request.audit_payload,
        )


class FailingManualImportWorkflowRuntime:
    async def signal_connector_manual_import(
        self,
        request: WorkflowConnectorManualImportSignalRequest,
    ) -> WorkflowSignalResult:
        raise WorkflowSignalError("synthetic_manual_import_runtime_down")


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


def connector_registry_payload() -> dict:
    migration = run_path("migrations/versions/0023_connector_registry_reference.py")
    return deepcopy(migration["CONNECTOR_REGISTRY_PAYLOAD"])


def seed_connector_registry_reference(
    factory: sessionmaker[Session],
    payload: dict | None = None,
) -> None:
    registry_payload = deepcopy(payload or connector_registry_payload())
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id="tenant_demo_manufacturing",
                surface="connectors",
                reference_id="manufacturing-connector-registry",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=registry_payload,
            )
        )


def manual_import_payload() -> dict:
    return {
        "tenant_id": "tenant_demo_manufacturing",
        "connector_id": "file_csv_manufacturing_assets",
        "import_id": "import_assets_manual_20260622",
        "idempotency_key": "manual-import-assets-20260622",
        "import_mode": "manual_import_request",
        "requested_by": "plant-operations-owner-role",
        "owner_role": "plant-operations-owner",
        "risk_level": "high",
        "approval_id": "appr_connector_import_assets_20260622",
        "workflow_id": "wf_connector_manual_import_review",
        "proposal_ids": ["proposal_asset_line_2_packaging"],
        "import_summary": {
            "proposal_count": "1",
            "mapping_profile": "manufacturing_asset_v1",
        },
        "controls": [
            "approval_required",
            "workflow_signal_required",
            "idempotency_enforced",
        ],
        "notes": ["Manual import request only; graph mutation is not applied."],
    }


def connector_manual_import_request() -> ConnectorManualImportCreateRequest:
    return ConnectorManualImportCreateRequest(**manual_import_payload())


def connector_manifest_request(
    connector_id: str,
    payload: dict | None = None,
) -> ConnectorManifestCreateRequest:
    registry_payload = deepcopy(payload or connector_registry_payload())
    connector = next(
        item
        for item in registry_payload["connectors"]
        if item["manifest"]["connector_id"] == connector_id
    )
    return ConnectorManifestCreateRequest(
        tenant_id="tenant_demo_manufacturing",
        registered_by="platform-connector-owner-role",
        manifest=connector["manifest"],
        runtime_policy=connector["runtime_policy"],
        preview_sample=connector["preview_sample"],
        notes=["Manifest is registered without enabling live sync."],
    )


def seed_registered_connector_manifest(
    repository: AxisPersistenceRepository,
    connector_id: str = "file_csv_manufacturing_assets",
    payload: dict | None = None,
) -> None:
    record_demo_connector_manifest(repository, connector_manifest_request(connector_id, payload))


def seed_active_connector_manifest(
    repository: AxisPersistenceRepository,
    connector_id: str = "file_csv_manufacturing_assets",
    payload: dict | None = None,
) -> None:
    seed_registered_connector_manifest(repository, connector_id, payload)
    transition_demo_connector_manifest_lifecycle(
        repository,
        connector_id,
        ConnectorManifestLifecycleRequest(
            tenant_id="tenant_demo_manufacturing",
            transitioned_by="platform-connector-owner-role",
            target_status="active_preview",
            actor_scopes=["connectors:manifest:lifecycle"],
            transition_reason="Validated for tenant connector manual import tests.",
            evidence_refs=["test://connector-manual-import-active-manifest"],
        ),
    )


def seed_connector_manual_imports(repository: AxisPersistenceRepository) -> None:
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="plant-operations-owner-role",
            event_type="connector.manual_import.requested",
            payload={
                "connector_id": "file_csv_manufacturing_assets",
                "import_id": "import_assets_manual_20260622",
                "idempotency_key": "manual-import-assets-20260622",
                "proposal_ids": ["proposal_asset_line_2_packaging"],
                "graph_mutation_status": "not_applied",
            },
        )
    )
    repository.create_connector_manual_import_request(
        ConnectorManualImportRequestCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            import_id="import_assets_manual_20260622",
            idempotency_key="manual-import-assets-20260622",
            status="approval_required",
            import_mode="manual_import_request",
            requested_by="plant-operations-owner-role",
            owner_role="plant-operations-owner",
            risk_level="high",
            approval_id="appr_connector_import_assets_20260622",
            workflow_id="wf_connector_manual_import_review",
            proposal_ids=["proposal_asset_line_2_packaging"],
            import_summary={
                "proposal_count": "1",
                "mapping_profile": "manufacturing_asset_v1",
            },
            controls=[
                "approval_required",
                "workflow_signal_required",
                "idempotency_enforced",
            ],
            graph_mutation_status="not_applied",
            workflow_signal_status="pending_approval_decision",
            audit_event_id=audit_event.id,
            audit_event_type="connector.manual_import.requested",
            notes=["Manual import request only; graph mutation is not applied."],
        )
    )
    repository.create_connector_manual_import_request(
        ConnectorManualImportRequestCreate(
            tenant_id="tenant_other",
            connector_id="file_csv_manufacturing_assets",
            import_id="import_other",
            idempotency_key="manual-import-other",
            status="approval_required",
            import_mode="manual_import_request",
            requested_by="other-owner-role",
            owner_role="other-owner",
            risk_level="medium",
            approval_id="appr_other",
            workflow_id="wf_other",
            proposal_ids=["proposal_other"],
            import_summary={"proposal_count": "1"},
            audit_event_id=audit_event.id,
        )
    )


def test_build_connector_manual_import_registry_maps_persisted_requests(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_connector_manual_imports(repository)
        registry = build_connector_manual_import_registry(
            repository,
            ConnectorManualImportQuery(tenant_id="tenant_demo_manufacturing"),
        )

    assert registry.tenant_id == "tenant_demo_manufacturing"
    assert registry.metrics[0].label == "Manual Imports"
    assert registry.metrics[0].value == "1"
    assert registry.metrics[1].label == "Approval Required"
    assert registry.metrics[1].value == "1"
    assert registry.metrics[2].label == "Workflow Signals"
    assert registry.metrics[2].value == "0"
    assert registry.metrics[3].label == "Graph Mutations"
    assert registry.metrics[3].value == "0"
    assert registry.imports[0].import_id == "import_assets_manual_20260622"
    assert registry.imports[0].proposal_ids == ["proposal_asset_line_2_packaging"]
    assert registry.imports[0].graph_mutation_status == "not_applied"
    assert registry.imports[0].workflow_signal_status == "pending_approval_decision"
    assert registry.imports[0].decision is None
    assert registry.imports[0].workflow_signal is None
    assert registry.imports[0].audit_event_type == "connector.manual_import.requested"
    assert "tenant_other" not in registry.model_dump_json()
    assert "csv_content" not in registry.model_dump_json().lower()
    assert "password" not in registry.model_dump_json().lower()
    assert "credential_value" not in registry.model_dump_json().lower()


def test_connector_manual_imports_endpoint_returns_tenant_scoped_records(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_connector_manual_imports(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/connectors/manual-imports",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["metrics"][0]["value"] == "1"
    assert body["metrics"][3]["value"] == "0"
    assert body["imports"][0]["import_id"] == "import_assets_manual_20260622"
    assert body["imports"][0]["approval_id"] == "appr_connector_import_assets_20260622"
    assert body["imports"][0]["workflow_id"] == "wf_connector_manual_import_review"
    assert body["imports"][0]["graph_mutation_status"] == "not_applied"
    assert "tenant_other" not in str(body)
    assert "csv_content" not in str(body).lower()
    assert "password" not in str(body).lower()
    assert "credential_value" not in str(body).lower()


def test_connector_manual_import_path_does_not_load_demo_connector_registry_seed() -> None:
    source = Path("src/axis_api/connector_manual_imports.py").read_text()

    assert "get_manufacturing_connector_registry" not in source


def test_record_demo_connector_manual_import_requires_persisted_connector_registry(
    empty_session_factory: sessionmaker[Session],
) -> None:
    with session_scope(empty_session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(ConnectorReferenceRecordNotFound):
            record_demo_connector_manual_import(repository, connector_manual_import_request())


def test_record_demo_connector_manual_import_uses_persisted_connector_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    payload = connector_registry_payload()
    payload["connectors"][0]["manifest"]["runtime_boundary"] = (
        "persisted-manual-import-runtime-boundary"
    )
    seed_connector_registry_reference(session_factory, payload)

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_connector_manifest(repository, payload=payload)
        record = record_demo_connector_manual_import(repository, connector_manual_import_request())
        events = repository.list_audit_events(
            "tenant_demo_manufacturing",
            event_type="connector.manual_import.requested",
        )

    assert record.import_id == "import_assets_manual_20260622"
    assert events[0].payload["runtime_boundary"] == "persisted-manual-import-runtime-boundary"


def test_record_demo_connector_manual_import_requires_active_preview_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_registered_connector_manifest(repository)

        with pytest.raises(ConnectorManualImportValidationError) as exc_info:
            record_demo_connector_manual_import(repository, connector_manual_import_request())

    assert exc_info.value.reason == "connector_manifest_not_active_preview"


def test_record_demo_connector_manual_import_accepts_active_live_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    # active_live is stricter than active_preview; approval evidence for
    # live-sync proposals must stay recordable so they can be promoted.
    payload = connector_registry_payload()
    connector = next(
        item
        for item in payload["connectors"]
        if item["manifest"]["connector_id"] == "file_csv_manufacturing_assets"
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

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_connector_manifest(repository, payload=payload)
        transition_demo_connector_manifest_lifecycle(
            repository,
            "file_csv_manufacturing_assets",
            ConnectorManifestLifecycleRequest(
                tenant_id="tenant_demo_manufacturing",
                transitioned_by="platform-connector-owner-role",
                target_status="active_live",
                actor_scopes=[
                    "connectors:manifest:lifecycle",
                    "connectors:manifest:enable_live",
                ],
                transition_reason="Governed live sync enabled for manual import tests.",
                evidence_refs=[
                    "approval:connector-live-sync-enable",
                    "policy:live-sync-boundary-reviewed",
                    "credential:live-sync-readonly-lease-policy",
                ],
            ),
        )
        record = record_demo_connector_manual_import(
            repository, connector_manual_import_request()
        )

    assert record.import_id == "import_assets_manual_20260622"
    assert record.status == "approval_required"


def test_create_connector_manual_import_records_audit_event(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_active_connector_manifest(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/manual-imports",
        json=manual_import_payload(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["import_id"] == "import_assets_manual_20260622"
    assert body["status"] == "approval_required"
    assert body["import_mode"] == "manual_import_request"
    assert body["approval_id"] == "appr_connector_import_assets_20260622"
    assert body["workflow_id"] == "wf_connector_manual_import_review"
    assert body["workflow_signal_status"] == "pending_approval_decision"
    assert body["graph_mutation_status"] == "not_applied"
    assert body["audit_event_type"] == "connector.manual_import.requested"
    assert body["audit_event_id"]
    assert body["idempotent_replay"] is False
    assert "csv_content" not in str(body).lower()
    assert "password" not in str(body).lower()
    assert "credential_value" not in str(body).lower()

    with session_scope(session_factory) as session:
        events = AxisPersistenceRepository(session).list_audit_events(
            "tenant_demo_manufacturing",
            event_type="connector.manual_import.requested",
        )

    assert len(events) == 1
    assert events[0].payload["import_id"] == "import_assets_manual_20260622"
    assert events[0].payload["idempotency_key"] == "manual-import-assets-20260622"
    assert events[0].payload["proposal_ids"] == ["proposal_asset_line_2_packaging"]
    assert events[0].payload["graph_mutation_status"] == "not_applied"
    assert events[0].payload["workflow_signal_status"] == "pending_approval_decision"
    assert "csv_content" not in str(events[0].payload).lower()


def test_create_connector_manual_import_endpoint_requires_active_preview_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_registered_connector_manifest(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/manual-imports",
        json=manual_import_payload(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "connector_manifest_not_active_preview"


def test_create_connector_manual_import_endpoint_reports_missing_connector_registry(
    empty_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = empty_session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/manual-imports",
        json=manual_import_payload(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "NOT_FOUND",
        "message": "Manufacturing connector registry reference record not found.",
        "surface": "connectors",
    }


async def test_record_connector_manual_import_decision_signals_workflow_and_updates_request(
    session_factory: sessionmaker[Session],
) -> None:
    workflow_runtime = RecordingManualImportWorkflowRuntime()
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_connector_manual_imports(repository)
        result = await record_demo_connector_manual_import_decision(
            repository,
            "import_assets_manual_20260622",
            ConnectorManualImportDecisionRequest(
                decision=ApprovalDecision.APPROVE,
                actor_id="plant-operations-owner-role",
                actor_scopes=["approvals:connectors:decide"],
                note="Approved import request; graph mutation remains gated.",
            ),
            workflow_runtime,
        )

    with session_factory() as session:
        approval = session.scalars(select(ApprovalRecord)).one()
        manual_import = session.scalars(
            select(ConnectorManualImportRequest).where(
                ConnectorManualImportRequest.import_id == "import_assets_manual_20260622"
            )
        ).one()
        decision_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.manual_import.decision_recorded"
            )
        ).one()

    assert result.manual_import.import_id == "import_assets_manual_20260622"
    assert result.manual_import.status == "approval_approved"
    assert result.manual_import.decision == "approve"
    assert result.manual_import.decision_actor_id == "plant-operations-owner-role"
    assert result.manual_import.workflow_signal_status == "manual_import_signal_requested"
    assert result.manual_import.graph_mutation_status == "not_applied"
    assert result.workflow_signal.status == "manual_import_signal_requested"
    assert result.workflow_signal.payload["import_id"] == "import_assets_manual_20260622"
    assert result.workflow_signal.payload["idempotency_key"] == "manual-import-assets-20260622"
    assert result.workflow_signal.payload["approval_id"] == "appr_connector_import_assets_20260622"
    assert result.workflow_signal.payload["decision"] == "approve"
    assert result.workflow_signal.payload["graph_mutation_status"] == "not_applied"
    assert result.permission_decision.model_dump() == {"allowed": True, "reason": "allowed"}
    assert result.audit_event_type == "connector.manual_import.decision_recorded"
    assert approval.approval_id == "appr_connector_import_assets_20260622"
    assert approval.action_id == "connector_manual_import:file_csv_manufacturing_assets"
    assert approval.status == "approve"
    assert approval.decision_actor_id == "plant-operations-owner-role"
    assert manual_import.status == "approval_approved"
    assert manual_import.decision == "approve"
    assert manual_import.workflow_signal_status == "manual_import_signal_requested"
    assert manual_import.workflow_signal["status"] == "manual_import_signal_requested"
    assert decision_event.payload["import_id"] == "import_assets_manual_20260622"
    assert decision_event.payload["decision"] == "approve"
    assert decision_event.payload["workflow_signal"]["status"] == "manual_import_signal_requested"
    assert decision_event.payload["graph_mutation_status"] == "not_applied"
    assert workflow_runtime.requests[0].signal_name == "connector_manual_import_decided"
    assert workflow_runtime.requests[0].runtime_payload["proposal_ids"] == [
        "proposal_asset_line_2_packaging"
    ]


def test_connector_manual_import_decision_endpoint_signals_workflow(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.workflow_runtime = RecordingManualImportWorkflowRuntime()
    with session_scope(session_factory) as session:
        seed_connector_manual_imports(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/manual-imports/import_assets_manual_20260622/decision",
        json={
            "decision": "approve",
            "actor_id": "plant-operations-owner-role",
            "actor_scopes": ["approvals:connectors:decide"],
            "note": "Approved inside endpoint test.",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["manual_import"]["status"] == "approval_approved"
    assert body["manual_import"]["decision"] == "approve"
    assert body["manual_import"]["workflow_signal_status"] == "manual_import_signal_requested"
    assert body["workflow_signal"]["signal_name"] == "connector_manual_import_decided"
    assert body["workflow_signal"]["payload"]["graph_mutation_status"] == "not_applied"
    assert body["audit_event_type"] == "connector.manual_import.decision_recorded"


def test_connector_manual_import_decision_endpoint_rejects_missing_permission(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_connector_manual_imports(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/manual-imports/import_assets_manual_20260622/decision",
        json={
            "decision": "approve",
            "actor_id": "plant-operations-owner-role",
            "actor_scopes": [],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "missing_required_scope"


def test_connector_manual_import_decision_endpoint_returns_runtime_unavailable_status(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    app.state.workflow_runtime = FailingManualImportWorkflowRuntime()
    with session_scope(session_factory) as session:
        seed_connector_manual_imports(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/manual-imports/import_assets_manual_20260622/decision",
        json={
            "decision": "approve",
            "actor_id": "plant-operations-owner-role",
            "actor_scopes": ["approvals:connectors:decide"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["workflow_signal_status"] == "runtime_signal_unavailable"
    assert body["manual_import"]["workflow_signal_status"] == "runtime_signal_unavailable"
    assert body["workflow_signal"]["payload"]["reason"] == "synthetic_manual_import_runtime_down"


def test_connector_manual_import_decision_endpoint_handles_missing_import(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_active_connector_manifest(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/manual-imports/missing_import/decision",
        json={
            "decision": "approve",
            "actor_id": "plant-operations-owner-role",
            "actor_scopes": ["approvals:connectors:decide"],
        },
    )

    assert response.status_code == 404


def test_create_connector_manual_import_is_idempotent_for_same_payload(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_active_connector_manifest(AxisPersistenceRepository(session))
    client = TestClient(app)

    first_response = client.post(
        "/demo/manufacturing/connectors/manual-imports",
        json=manual_import_payload(),
    )
    second_response = client.post(
        "/demo/manufacturing/connectors/manual-imports",
        json=manual_import_payload(),
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert second_response.json()["idempotent_replay"] is True
    assert second_response.json()["audit_event_id"] == first_response.json()["audit_event_id"]

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        requests = repository.list_connector_manual_import_requests("tenant_demo_manufacturing")
        events = repository.list_audit_events(
            "tenant_demo_manufacturing",
            event_type="connector.manual_import.requested",
        )

    assert len(requests) == 1
    assert len(events) == 1


def test_create_connector_manual_import_rejects_idempotency_conflict(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_active_connector_manifest(AxisPersistenceRepository(session))
    client = TestClient(app)
    conflicting_payload = manual_import_payload()
    conflicting_payload["import_id"] = "import_assets_manual_other"

    assert client.post(
        "/demo/manufacturing/connectors/manual-imports",
        json=manual_import_payload(),
    ).status_code == 201

    response = client.post(
        "/demo/manufacturing/connectors/manual-imports",
        json=conflicting_payload,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "idempotency_conflict"


def test_create_connector_manual_import_rejects_raw_summary_fields(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    payload = manual_import_payload()
    payload["import_summary"] = {"csv_content": "asset_id,asset_name"}

    response = client.post(
        "/demo/manufacturing/connectors/manual-imports",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "raw_payload_field"


def test_create_connector_manual_import_rejects_direct_graph_write_mode(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    payload = manual_import_payload()
    payload["import_mode"] = "direct_graph_write"

    response = client.post(
        "/demo/manufacturing/connectors/manual-imports",
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "unsupported_import_mode"


def test_openapi_exposes_connector_manual_import_endpoints(openapi_schema: dict) -> None:
    paths = openapi_schema["paths"]
    assert "/demo/manufacturing/connectors/manual-imports" in paths
    assert "/demo/manufacturing/connectors/manual-imports/{import_id}/decision" in paths
