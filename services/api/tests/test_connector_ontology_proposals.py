from copy import deepcopy
from pathlib import Path
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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
from axis_api.connector_ontology_proposals import (
    ConnectorOntologyProposalCreateRequest,
    ConnectorOntologyProposalEntity,
    ConnectorOntologyProposalQuery,
    ConnectorOntologyProposalValidationError,
    build_connector_ontology_proposal_registry,
    record_demo_connector_ontology_proposals,
)
from axis_api.connector_reference import ConnectorReferenceRecordNotFound
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorOntologyProposalCreate,
    DemoReferenceRecordCreate,
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


def seed_connector_ontology_proposals(repository: AxisPersistenceRepository) -> None:
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id="tenant_demo_manufacturing",
            actor_id="connector-preview-service",
            event_type="connector.ontology_proposals.recorded",
            payload={
                "connector_id": "file_csv_manufacturing_assets",
                "proposal_count": 1,
                "write_mode": "proposal_only",
            },
        )
    )
    repository.create_connector_ontology_proposal(
        ConnectorOntologyProposalCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            proposal_id="proposal_asset_line_2_packaging",
            source_run_id="run_file_csv_assets_preview_20260622",
            source_file_name="manufacturing-assets-demo.csv",
            mapping_profile="manufacturing_asset_v1",
            status="proposed_from_preview",
            write_mode="proposal_only",
            graph_mutation_status="not_applied",
            proposed_by="plant-operations-owner-role",
            node_id="asset_line_2_packaging",
            node_type="asset",
            ontology_type="manufacturing_asset",
            field_summary={
                "asset_name": "Line 2 Packaging",
                "domain": "Operations",
                "station": "Line 2",
                "risk_level": "high",
            },
            evidence_refs=["manufacturing-assets-demo.csv", "asset_line_2_packaging"],
            audit_event_id=audit_event.id,
            notes=["Proposal persisted for review; graph mutation is not applied."],
        )
    )
    repository.create_connector_ontology_proposal(
        ConnectorOntologyProposalCreate(
            tenant_id="tenant_other",
            connector_id="file_csv_manufacturing_assets",
            proposal_id="proposal_other",
            source_file_name="other.csv",
            mapping_profile="manufacturing_asset_v1",
            proposed_by="other-owner-role",
            node_id="asset_other",
            node_type="asset",
            ontology_type="manufacturing_asset",
            field_summary={"asset_name": "Other"},
            evidence_refs=["other.csv", "asset_other"],
            audit_event_id=audit_event.id,
        )
    )


def connector_ontology_proposal_request() -> ConnectorOntologyProposalCreateRequest:
    return ConnectorOntologyProposalCreateRequest(
        tenant_id="tenant_demo_manufacturing",
        connector_id="file_csv_manufacturing_assets",
        source_run_id="run_file_csv_assets_preview_20260622",
        source_file_name="manufacturing-assets-demo.csv",
        mapping_profile="manufacturing_asset_v1",
        write_mode="proposal_only",
        proposed_by="plant-operations-owner-role",
        proposed_entities=[
            ConnectorOntologyProposalEntity(
                proposal_id="proposal_asset_line_2_packaging",
                node_id="asset_line_2_packaging",
                node_type="asset",
                ontology_type="manufacturing_asset",
                field_summary={
                    "asset_name": "Line 2 Packaging",
                    "domain": "Operations",
                    "station": "Line 2",
                    "risk_level": "high",
                },
                evidence_refs=[
                    "manufacturing-assets-demo.csv",
                    "asset_line_2_packaging",
                ],
            )
        ],
        notes=["Persist preview proposal only; do not mutate the graph."],
    )


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
            transition_reason="Validated for tenant connector ontology proposal tests.",
            evidence_refs=["test://connector-ontology-proposal-active-manifest"],
        ),
    )


def test_connector_ontology_proposal_path_does_not_load_demo_connector_registry_seed() -> None:
    source = Path("src/axis_api/connector_ontology_proposals.py").read_text()

    assert "get_manufacturing_connector_registry" not in source


def test_record_demo_connector_ontology_proposals_requires_persisted_connector_registry(
    empty_session_factory: sessionmaker[Session],
) -> None:
    with session_scope(empty_session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(ConnectorReferenceRecordNotFound):
            record_demo_connector_ontology_proposals(
                repository,
                connector_ontology_proposal_request(),
            )


def test_record_demo_connector_ontology_proposals_uses_persisted_connector_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    payload = connector_registry_payload()
    payload["connectors"][0]["manifest"]["runtime_boundary"] = (
        "persisted-proposal-runtime-boundary"
    )
    seed_connector_registry_reference(session_factory, payload)

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_connector_manifest(repository, payload=payload)
        record_demo_connector_ontology_proposals(
            repository,
            connector_ontology_proposal_request(),
        )
        events = repository.list_audit_events(
            "tenant_demo_manufacturing",
            event_type="connector.ontology_proposals.recorded",
        )

    assert events[0].payload["runtime_boundary"] == "persisted-proposal-runtime-boundary"


def test_record_demo_connector_ontology_proposals_requires_active_preview_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_registered_connector_manifest(repository)

        with pytest.raises(ConnectorOntologyProposalValidationError) as exc_info:
            record_demo_connector_ontology_proposals(
                repository,
                connector_ontology_proposal_request(),
            )

    assert exc_info.value.reason == "connector_manifest_not_active_preview"


def test_build_connector_ontology_proposal_registry_maps_persisted_proposals(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_connector_ontology_proposals(repository)
        registry = build_connector_ontology_proposal_registry(
            repository,
            ConnectorOntologyProposalQuery(tenant_id="tenant_demo_manufacturing"),
        )

    assert registry.tenant_id == "tenant_demo_manufacturing"
    assert registry.metrics[0].label == "Ontology Proposals"
    assert registry.metrics[0].value == "1"
    assert registry.metrics[1].label == "Pending Review"
    assert registry.metrics[1].value == "1"
    assert registry.metrics[2].label == "Graph Mutations"
    assert registry.metrics[2].value == "0"
    assert registry.proposals[0].proposal_id == "proposal_asset_line_2_packaging"
    assert registry.proposals[0].graph_mutation_status == "not_applied"
    assert registry.proposals[0].audit_event_type == "connector.ontology_proposals.recorded"
    assert "tenant_other" not in registry.model_dump_json()
    assert "csv_content" not in registry.model_dump_json().lower()
    assert "password" not in registry.model_dump_json().lower()
    assert "credential_value" not in registry.model_dump_json().lower()


def test_connector_ontology_proposals_endpoint_returns_tenant_scoped_records(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_connector_ontology_proposals(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/connectors/ontology-proposals",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["metrics"][0]["value"] == "1"
    assert body["metrics"][2]["value"] == "0"
    assert body["proposals"][0]["proposal_id"] == "proposal_asset_line_2_packaging"
    assert body["proposals"][0]["write_mode"] == "proposal_only"
    assert body["proposals"][0]["graph_mutation_status"] == "not_applied"
    assert "tenant_other" not in str(body)
    assert "csv_content" not in str(body).lower()
    assert "password" not in str(body).lower()
    assert "credential_value" not in str(body).lower()


def test_create_connector_ontology_proposals_records_audit_event(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_active_connector_manifest(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "file_csv_manufacturing_assets",
            "source_run_id": "run_file_csv_assets_preview_20260622",
            "source_file_name": "manufacturing-assets-demo.csv",
            "mapping_profile": "manufacturing_asset_v1",
            "write_mode": "proposal_only",
            "proposed_by": "plant-operations-owner-role",
            "proposed_entities": [
                {
                    "proposal_id": "proposal_asset_line_2_packaging",
                    "node_id": "asset_line_2_packaging",
                    "node_type": "asset",
                    "ontology_type": "manufacturing_asset",
                    "field_summary": {
                        "asset_name": "Line 2 Packaging",
                        "domain": "Operations",
                        "station": "Line 2",
                        "risk_level": "high",
                    },
                    "evidence_refs": [
                        "manufacturing-assets-demo.csv",
                        "asset_line_2_packaging",
                    ],
                }
            ],
            "notes": ["Persist preview proposal only; do not mutate the graph."],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["metrics"][0]["value"] == "1"
    assert body["metrics"][2]["value"] == "0"
    proposal = body["proposals"][0]
    assert proposal["proposal_id"] == "proposal_asset_line_2_packaging"
    assert proposal["status"] == "proposed_from_preview"
    assert proposal["write_mode"] == "proposal_only"
    assert proposal["graph_mutation_status"] == "not_applied"
    assert proposal["audit_event_type"] == "connector.ontology_proposals.recorded"
    assert proposal["audit_event_id"]
    assert "csv_content" not in str(body).lower()
    assert "password" not in str(body).lower()
    assert "credential_value" not in str(body).lower()

    with session_scope(session_factory) as session:
        events = AxisPersistenceRepository(session).list_audit_events(
            "tenant_demo_manufacturing",
            event_type="connector.ontology_proposals.recorded",
        )

    assert len(events) == 1
    assert events[0].payload["proposal_ids"] == ["proposal_asset_line_2_packaging"]
    assert events[0].payload["write_mode"] == "proposal_only"
    assert events[0].payload["graph_mutation_status"] == "not_applied"
    assert "csv_content" not in str(events[0].payload).lower()


def test_create_connector_ontology_proposals_endpoint_requires_active_preview_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_registered_connector_manifest(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals",
        json=connector_ontology_proposal_request().model_dump(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "connector_manifest_not_active_preview"


def test_create_connector_ontology_proposals_endpoint_reports_missing_connector_registry(
    empty_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = empty_session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals",
        json=connector_ontology_proposal_request().model_dump(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "NOT_FOUND",
        "message": "Manufacturing connector registry reference record not found.",
        "surface": "connectors",
    }


def test_create_connector_ontology_proposals_rejects_raw_payload_fields(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "file_csv_manufacturing_assets",
            "source_file_name": "manufacturing-assets-demo.csv",
            "mapping_profile": "manufacturing_asset_v1",
            "write_mode": "proposal_only",
            "proposed_by": "plant-operations-owner-role",
            "proposed_entities": [
                {
                    "proposal_id": "proposal_asset_line_2_packaging",
                    "node_id": "asset_line_2_packaging",
                    "node_type": "asset",
                    "ontology_type": "manufacturing_asset",
                    "field_summary": {
                        "asset_name": "Line 2 Packaging",
                        "csv_content": "asset_id,asset_name",
                    },
                    "evidence_refs": ["manufacturing-assets-demo.csv"],
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "raw_payload_field"


def test_create_connector_ontology_proposals_rejects_graph_write_mode(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/ontology-proposals",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "file_csv_manufacturing_assets",
            "source_file_name": "manufacturing-assets-demo.csv",
            "mapping_profile": "manufacturing_asset_v1",
            "write_mode": "graph_write",
            "proposed_by": "plant-operations-owner-role",
            "proposed_entities": [
                {
                    "proposal_id": "proposal_asset_line_2_packaging",
                    "node_id": "asset_line_2_packaging",
                    "node_type": "asset",
                    "ontology_type": "manufacturing_asset",
                    "field_summary": {"asset_name": "Line 2 Packaging"},
                    "evidence_refs": ["manufacturing-assets-demo.csv"],
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "unsupported_write_mode"


def test_openapi_exposes_connector_ontology_proposal_endpoints(openapi_schema: dict) -> None:
    paths = openapi_schema["paths"]
    assert "/demo/manufacturing/connectors/ontology-proposals" in paths
