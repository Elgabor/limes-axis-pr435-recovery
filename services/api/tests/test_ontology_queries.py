from pathlib import Path
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.demo import ManufacturingOntology
from axis_api.identity import OidcPrincipal
from axis_api.main import create_app
from axis_api.models import Base
from axis_api.ontology.queries import (
    DeferredOntologyQueryRuntime,
    OntologyGraphQueryMetadata,
    OntologyGraphQueryRequest,
    TypeDBOntologyQueryConfig,
    TypeDBOntologyQueryRuntime,
    query_manufacturing_ontology_graph,
)
from axis_api.permissions import PermissionDecision
from axis_api.persistence import AxisPersistenceRepository, DemoReferenceRecordCreate

MIGRATIONS_DIR = Path(__file__).parents[1] / "migrations" / "versions"


@pytest.fixture
def ontology_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    seed_ontology_reference(factory)
    yield factory
    engine.dispose()


def ontology_bootstrap_payload() -> dict:
    migration = run_path(str(MIGRATIONS_DIR / "0030_ontology_reference.py"))
    return migration["ONTOLOGY_PAYLOAD"]


def ontology_bootstrap_model() -> ManufacturingOntology:
    return ManufacturingOntology.model_validate(ontology_bootstrap_payload())


def seed_ontology_reference(factory: sessionmaker[Session]) -> None:
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id="tenant_demo_manufacturing",
                surface="ontology",
                reference_id="manufacturing-ontology",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=ontology_bootstrap_payload(),
            )
        )


class StaticIdentityVerifier:
    def __init__(self, principal: OidcPrincipal) -> None:
        self.principal = principal

    def verify_authorization_header(self, authorization: str | None) -> OidcPrincipal:
        assert authorization == "Bearer valid-token"
        return self.principal


class RecordingOntologyQueryRuntime:
    adapter_name = "axis-recording-ontology-query-adapter"

    def __init__(self) -> None:
        self.requests: list[OntologyGraphQueryRequest] = []

    def query_manufacturing_graph(
        self,
        request: OntologyGraphQueryRequest,
        ontology: ManufacturingOntology,
    ) -> ManufacturingOntology:
        self.requests.append(request)
        return ontology.model_copy(
            update={
                "graph_query": OntologyGraphQueryMetadata(
                    adapter=self.adapter_name,
                    source="recording-test-runtime",
                    query_mode="permission_filtered",
                    tenant_id=request.tenant_id,
                    actor_id=request.actor_id,
                    permission_decision=PermissionDecision(
                        allowed=True,
                        reason="recording_runtime_allowed",
                    ),
                    requested_scopes=request.actor_scopes,
                    applied_relationship_scopes=["operations:read"],
                    denied_relationship_count=0,
                    returned_node_count=len(ontology.nodes),
                    returned_relationship_count=len(ontology.relationships),
                    typeql=request.typeql,
                    notes=["Recording runtime used by API test."],
                )
            }
        )


class StructuredTypeDBClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def execute_read(self, query_text: str) -> list[dict[str, object]]:
        self.queries.append(query_text)
        return [
            {
                "kind": "node",
                "node_id": "typedb_asset_line_7",
                "label": "Line 7 Finishing",
                "node_type": "asset",
                "domain": "Production",
                "status": "ready",
                "source_system": "TypeDB",
                "summary": "Asset row mapped from the TypeDB read boundary.",
            },
            {
                "kind": "node",
                "node_id": "typedb_process_quality_release",
                "label": "Quality Release",
                "node_type": "process",
                "domain": "Quality",
                "status": "watch",
                "source_system": "TypeDB",
                "summary": "Process row mapped from the TypeDB read boundary.",
            },
            {
                "kind": "relationship",
                "relationship_id": "typedb_rel_line_requires_release",
                "source_id": "typedb_asset_line_7",
                "target_id": "typedb_process_quality_release",
                "relation_type": "requires_release",
                "summary": "Line 7 requires quality release before shipment.",
                "permission_scope": "quality:read",
                "metadata": {
                    "owner_role": "Quality Steward",
                    "source_adapter": "typedb-read-boundary",
                    "confidence": 0.98,
                    "evidence_refs": ["typedb:quality_release:line_7"],
                    "valid_from": "2026-06-30T09:00:00+02:00",
                    "valid_to": None,
                    "last_verified_at": "2026-06-30T09:10:00+02:00",
                    "verification_status": "typedb_verified",
                },
            },
        ]


def test_typedb_ontology_query_runtime_maps_structured_rows() -> None:
    client = StructuredTypeDBClient()
    runtime = TypeDBOntologyQueryRuntime(
        TypeDBOntologyQueryConfig(),
        client=client,
    )

    ontology = query_manufacturing_ontology_graph(
        runtime,
        OntologyGraphQueryRequest(
            tenant_id="tenant_demo_manufacturing",
            actor_id="quality-reader",
            actor_scopes=["quality:read"],
            enforce_relationship_scopes=True,
        ),
        ontology_bootstrap_model(),
    )

    assert client.queries == [
        "match\n  $entity isa $entity_type, has axis_id $axis_id;\nlimit 200;"
    ]
    assert ontology.graph_query.adapter == "axis-typedb-ontology-query-adapter"
    assert ontology.graph_query.source == "typedb-read-boundary"
    assert ontology.graph_query.query_mode == "permission_filtered"
    assert ontology.graph_query.returned_node_count == 2
    assert ontology.graph_query.returned_relationship_count == 1
    assert [node.node_id for node in ontology.nodes] == [
        "typedb_asset_line_7",
        "typedb_process_quality_release",
    ]
    assert [relationship.relationship_id for relationship in ontology.relationships] == [
        "typedb_rel_line_requires_release"
    ]
    assert ontology.relationships[0].metadata.owner_role == "Quality Steward"
    assert ontology.relationships[0].metadata.evidence_refs == [
        "typedb:quality_release:line_7"
    ]
    assert ontology.relationships[0].metadata.source_adapter == "typedb-read-boundary"
    assert ontology.source_systems == ["TypeDB"]


def test_typedb_ontology_query_runtime_filters_unscoped_relationships() -> None:
    runtime = TypeDBOntologyQueryRuntime(
        TypeDBOntologyQueryConfig(),
        client=StructuredTypeDBClient(),
    )

    ontology = query_manufacturing_ontology_graph(
        runtime,
        OntologyGraphQueryRequest(
            tenant_id="tenant_demo_manufacturing",
            actor_id="operations-reader",
            actor_scopes=["operations:read"],
            enforce_relationship_scopes=True,
        ),
        ontology_bootstrap_model(),
    )

    assert ontology.graph_query.source == "typedb-read-boundary"
    assert ontology.graph_query.query_mode == "permission_filtered"
    assert ontology.relationships == []
    assert ontology.nodes == []
    assert ontology.graph_query.denied_relationship_count == 1
    assert "quality:read" not in ontology.graph_query.applied_relationship_scopes


def test_deferred_ontology_query_runtime_denies_all_relationships_for_empty_scopes() -> None:
    runtime = DeferredOntologyQueryRuntime()
    ontology = ontology_bootstrap_model()

    filtered = query_manufacturing_ontology_graph(
        runtime,
        OntologyGraphQueryRequest(
            tenant_id="tenant_demo_manufacturing",
            actor_id="no-scope-reader",
            actor_scopes=[],
            enforce_relationship_scopes=True,
        ),
        ontology,
    )

    assert filtered.relationships == []
    assert filtered.nodes == []
    assert filtered.graph_query.denied_relationship_count == len(ontology.relationships)
    assert filtered.graph_query.applied_relationship_scopes == []


def test_deferred_ontology_query_runtime_filters_relationships_by_scope() -> None:
    runtime = DeferredOntologyQueryRuntime()

    ontology = query_manufacturing_ontology_graph(
        runtime,
        OntologyGraphQueryRequest(
            tenant_id="tenant_demo_manufacturing",
            actor_id="operations-reader",
            actor_scopes=["operations:read"],
            enforce_relationship_scopes=True,
        ),
        ontology_bootstrap_model(),
    )

    assert ontology.graph_query.adapter == "axis-deferred-ontology-query-adapter"
    assert ontology.graph_query.query_mode == "permission_filtered"
    assert ontology.graph_query.permission_decision.allowed is True
    assert ontology.graph_query.applied_relationship_scopes == ["operations:read"]
    assert ontology.graph_query.denied_relationship_count > 0
    assert {relationship.permission_scope for relationship in ontology.relationships} == {
        "operations:read"
    }
    assert "rel_supplier_batch_impacts_line" not in {
        relationship.relationship_id for relationship in ontology.relationships
    }
    assert "asset_line_2_packaging" in {node.node_id for node in ontology.nodes}
    assert "asset_motors_batch" not in {node.node_id for node in ontology.nodes}


def test_ontology_endpoint_uses_query_runtime_and_oidc_principal(
    ontology_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = ontology_session_factory
    runtime = RecordingOntologyQueryRuntime()
    app.state.ontology_query_runtime = runtime
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="operations-reader",
            tenant_id="tenant_demo_manufacturing",
            scopes=["operations:read"],
        )
    )
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/ontology",
        headers={"Authorization": "Bearer valid-token"},
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["graph_query"]["adapter"] == "axis-recording-ontology-query-adapter"
    assert body["graph_query"]["actor_id"] == "operations-reader"
    assert body["graph_query"]["requested_scopes"] == ["operations:read"]
    assert runtime.requests[0].enforce_relationship_scopes is True
    assert runtime.requests[0].actor_scopes == ["operations:read"]


def test_ontology_endpoint_filters_graph_when_oidc_auth_required(
    ontology_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = ontology_session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="operations-reader",
            tenant_id="tenant_demo_manufacturing",
            scopes=["operations:read"],
        )
    )
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/ontology",
        headers={"Authorization": "Bearer valid-token"},
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["graph_query"]["query_mode"] == "permission_filtered"
    assert body["graph_query"]["denied_relationship_count"] > 0
    assert {relationship["permission_scope"] for relationship in body["relationships"]} == {
        "operations:read"
    }
    assert "asset_motors_batch" not in str(body)


def test_ontology_endpoint_rejects_tenant_mismatch(
    ontology_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = ontology_session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="operations-reader",
            tenant_id="tenant_demo_manufacturing",
            scopes=["operations:read"],
        )
    )
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/ontology?tenant_id=tenant_other",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "tenant_mismatch"


def test_ontology_endpoint_allows_empty_filtered_graph(
    ontology_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = ontology_session_factory
    app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="no-graph-scope-reader",
            tenant_id="tenant_demo_manufacturing",
            scopes=["profile:read"],
        )
    )
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/ontology",
        headers={"Authorization": "Bearer valid-token"},
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["nodes"] == []
    assert body["relationships"] == []
    assert body["graph_query"]["denied_relationship_count"] == 14


def test_ontology_openapi_allows_empty_filtered_graph_lists() -> None:
    app = create_app(Settings())
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    components = response.json()["components"]["schemas"]
    schema = components["ManufacturingOntology"]
    assert "minItems" not in schema["properties"]["nodes"]
    assert "minItems" not in schema["properties"]["relationships"]
    relationship_schema = components["OntologyRelationship"]
    assert "metadata" in relationship_schema["properties"]
    assert "OntologyRelationshipMetadata" in str(
        relationship_schema["properties"]["metadata"]
    )
