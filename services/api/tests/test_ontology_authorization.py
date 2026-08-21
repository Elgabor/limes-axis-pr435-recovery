from pathlib import Path
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.identity import OidcPrincipal
from axis_api.main import create_app
from axis_api.models import AuditEvent, Base
from axis_api.ontology_authorization import (
    ONTOLOGY_ENTITY_READ_DENIED_EVENT_TYPE,
    ONTOLOGY_GRAPH_READ_DENIED_EVENT_TYPE,
    OntologyReadPermissionDenied,
    authorize_ontology_graph_read,
    get_authorized_manufacturing_ontology_entity_detail,
)
from axis_api.ontology_reference import OntologyReferenceRecordInvalid
from axis_api.persistence import AxisPersistenceRepository, DemoReferenceRecordCreate

MIGRATIONS_DIR = Path(__file__).parents[1] / "migrations" / "versions"
DEMO_TENANT_ID = "tenant_demo_manufacturing"
SCOPED_NODE_ID = "asset_line_2_packaging"


@pytest.fixture
def authorization_session_factory() -> sessionmaker[Session]:
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


def seed_ontology_reference(
    factory: sessionmaker[Session],
    payload: dict | None = None,
) -> None:
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=DEMO_TENANT_ID,
                surface="ontology",
                reference_id="manufacturing-ontology",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=payload or ontology_bootstrap_payload(),
            )
        )


def make_principal(
    scopes: list[str],
    tenant_id: str = DEMO_TENANT_ID,
    actor_id: str = "ontology-reader",
) -> OidcPrincipal:
    return OidcPrincipal(actor_id=actor_id, tenant_id=tenant_id, scopes=scopes)


def denied_audit_events(
    factory: sessionmaker[Session],
    event_type: str,
) -> list[AuditEvent]:
    with factory() as session:
        return list(
            session.scalars(select(AuditEvent).where(AuditEvent.event_type == event_type))
        )


class StaticIdentityVerifier:
    def __init__(self, principal: OidcPrincipal) -> None:
        self.principal = principal

    def verify_authorization_header(self, authorization: str | None) -> OidcPrincipal:
        assert authorization == "Bearer valid-token"
        return self.principal


def build_client(
    authorization_session_factory: sessionmaker[Session],
    principal: OidcPrincipal | None = None,
) -> TestClient:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://", oidc_auth_required=True))
    app.state.session_factory = authorization_session_factory
    if principal is not None:
        app.state.identity_verifier = StaticIdentityVerifier(principal)
    return TestClient(app)


def test_entity_detail_read_allows_actor_with_relationship_scopes(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    with session_scope(authorization_session_factory) as session:
        detail = get_authorized_manufacturing_ontology_entity_detail(
            AxisPersistenceRepository(session),
            SCOPED_NODE_ID,
            tenant_id=DEMO_TENANT_ID,
            principal=make_principal(["operations:read", "supply:read"]),
        )

    assert detail is not None
    assert detail.node.node_id == SCOPED_NODE_ID
    assert denied_audit_events(
        authorization_session_factory,
        ONTOLOGY_ENTITY_READ_DENIED_EVENT_TYPE,
    ) == []


def test_entity_detail_read_denies_missing_relationship_scope_and_records_audit(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    with (
        session_scope(authorization_session_factory) as session,
        pytest.raises(OntologyReadPermissionDenied) as exc_info,
    ):
        get_authorized_manufacturing_ontology_entity_detail(
            AxisPersistenceRepository(session),
            SCOPED_NODE_ID,
            tenant_id=DEMO_TENANT_ID,
            principal=make_principal(["operations:read"]),
        )

    denial = exc_info.value
    assert denial.decision.allowed is False
    assert denial.decision.reason == "missing_relationship_scope:supply:read"
    assert denial.required_permissions == ["operations:read", "supply:read"]
    assert denial.audit_event_type == ONTOLOGY_ENTITY_READ_DENIED_EVENT_TYPE

    audit_event = denied_audit_events(
        authorization_session_factory,
        ONTOLOGY_ENTITY_READ_DENIED_EVENT_TYPE,
    )[0]
    assert audit_event.id == denial.audit_event_id
    assert audit_event.tenant_id == DEMO_TENANT_ID
    assert audit_event.actor_id == "ontology-reader"
    assert audit_event.payload["resource"] == "ontology_entity_detail"
    assert audit_event.payload["node_id"] == SCOPED_NODE_ID
    assert audit_event.payload["reason"] == "missing_relationship_scope:supply:read"
    assert audit_event.payload["required_permissions"] == ["operations:read", "supply:read"]
    assert "actor_scopes" not in audit_event.payload
    assert "password" not in str(audit_event.payload).lower()
    assert "secret" not in str(audit_event.payload).lower()


def test_entity_detail_read_denies_empty_scopes(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    with (
        session_scope(authorization_session_factory) as session,
        pytest.raises(OntologyReadPermissionDenied) as exc_info,
    ):
        get_authorized_manufacturing_ontology_entity_detail(
            AxisPersistenceRepository(session),
            SCOPED_NODE_ID,
            tenant_id=DEMO_TENANT_ID,
            principal=make_principal([]),
        )

    assert exc_info.value.decision.reason == "missing_relationship_scope:operations:read"
    assert (
        len(
            denied_audit_events(
                authorization_session_factory,
                ONTOLOGY_ENTITY_READ_DENIED_EVENT_TYPE,
            )
        )
        == 1
    )


def test_entity_detail_read_denies_tenant_mismatch_in_actor_tenant_scope(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    with (
        session_scope(authorization_session_factory) as session,
        pytest.raises(OntologyReadPermissionDenied) as exc_info,
    ):
        get_authorized_manufacturing_ontology_entity_detail(
            AxisPersistenceRepository(session),
            SCOPED_NODE_ID,
            tenant_id="tenant_other",
            principal=make_principal(["operations:read", "supply:read"]),
        )

    assert exc_info.value.decision.reason == "tenant_mismatch"
    assert exc_info.value.required_permissions == []

    audit_event = denied_audit_events(
        authorization_session_factory,
        ONTOLOGY_ENTITY_READ_DENIED_EVENT_TYPE,
    )[0]
    assert audit_event.tenant_id == DEMO_TENANT_ID
    assert audit_event.payload["requested_tenant_id"] == "tenant_other"


def test_entity_detail_read_returns_none_for_unknown_node_without_audit(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    with session_scope(authorization_session_factory) as session:
        detail = get_authorized_manufacturing_ontology_entity_detail(
            AxisPersistenceRepository(session),
            "missing-node",
            tenant_id=DEMO_TENANT_ID,
            principal=make_principal(["operations:read", "supply:read"]),
        )

    assert detail is None
    assert denied_audit_events(
        authorization_session_factory,
        ONTOLOGY_ENTITY_READ_DENIED_EVENT_TYPE,
    ) == []


def test_entity_detail_read_skips_enforcement_for_public_reader(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    with session_scope(authorization_session_factory) as session:
        detail = get_authorized_manufacturing_ontology_entity_detail(
            AxisPersistenceRepository(session),
            SCOPED_NODE_ID,
            tenant_id=DEMO_TENANT_ID,
            principal=None,
        )

    assert detail is not None
    assert denied_audit_events(
        authorization_session_factory,
        ONTOLOGY_ENTITY_READ_DENIED_EVENT_TYPE,
    ) == []


def test_entity_detail_read_rejects_malformed_permission_payload(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    payload = ontology_bootstrap_payload()
    payload["relationships"][0]["permission_scope"] = ""
    seed_ontology_reference(authorization_session_factory, payload)

    with (
        session_scope(authorization_session_factory) as session,
        pytest.raises(OntologyReferenceRecordInvalid),
    ):
        get_authorized_manufacturing_ontology_entity_detail(
            AxisPersistenceRepository(session),
            SCOPED_NODE_ID,
            tenant_id=DEMO_TENANT_ID,
            principal=make_principal(["operations:read", "supply:read"]),
        )


def test_graph_read_allows_matching_tenant_without_audit(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    with session_scope(authorization_session_factory) as session:
        authorize_ontology_graph_read(
            AxisPersistenceRepository(session),
            tenant_id=DEMO_TENANT_ID,
            principal=make_principal(["operations:read"]),
        )

    assert denied_audit_events(
        authorization_session_factory,
        ONTOLOGY_GRAPH_READ_DENIED_EVENT_TYPE,
    ) == []


def test_graph_read_denies_tenant_mismatch_and_records_audit(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    with (
        session_scope(authorization_session_factory) as session,
        pytest.raises(OntologyReadPermissionDenied) as exc_info,
    ):
        authorize_ontology_graph_read(
            AxisPersistenceRepository(session),
            tenant_id="tenant_other",
            principal=make_principal(["operations:read"]),
        )

    assert exc_info.value.decision.reason == "tenant_mismatch"
    assert exc_info.value.audit_event_type == ONTOLOGY_GRAPH_READ_DENIED_EVENT_TYPE

    audit_event = denied_audit_events(
        authorization_session_factory,
        ONTOLOGY_GRAPH_READ_DENIED_EVENT_TYPE,
    )[0]
    assert audit_event.tenant_id == DEMO_TENANT_ID
    assert audit_event.actor_id == "ontology-reader"
    assert audit_event.payload["resource"] == "ontology_graph"
    assert audit_event.payload["requested_tenant_id"] == "tenant_other"
    assert "node_id" not in audit_event.payload


def test_ontology_graph_endpoint_requires_oidc_authentication(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    client = build_client(authorization_session_factory)

    response = client.get("/demo/manufacturing/ontology")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_ontology_entity_endpoint_requires_oidc_authentication(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    client = build_client(authorization_session_factory)

    response = client.get(f"/demo/manufacturing/ontology/entities/{SCOPED_NODE_ID}")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_ontology_graph_endpoint_allows_fully_scoped_actor(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    payload = ontology_bootstrap_payload()
    all_relationship_scopes = sorted(
        {relationship["permission_scope"] for relationship in payload["relationships"]}
    )
    client = build_client(
        authorization_session_factory,
        make_principal(all_relationship_scopes),
    )

    response = client.get(
        "/demo/manufacturing/ontology",
        headers={"Authorization": "Bearer valid-token"},
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert {"nodes", "relationships", "source_systems", "graph_query"} <= set(body)
    assert body["tenant_id"] == DEMO_TENANT_ID
    assert len(body["relationships"]) == len(payload["relationships"])
    assert len(body["nodes"]) > 0
    assert body["graph_query"]["query_mode"] == "permission_filtered"
    assert body["graph_query"]["denied_relationship_count"] == 0
    assert body["graph_query"]["actor_id"] == "ontology-reader"
    assert body["graph_query"]["applied_relationship_scopes"] == all_relationship_scopes
    assert denied_audit_events(
        authorization_session_factory,
        ONTOLOGY_GRAPH_READ_DENIED_EVENT_TYPE,
    ) == []


def test_ontology_graph_endpoint_tenant_mismatch_appends_audit_event(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    client = build_client(
        authorization_session_factory,
        make_principal(["operations:read"]),
    )

    response = client.get(
        "/demo/manufacturing/ontology?tenant_id=tenant_other",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "PERMISSION_DENIED",
        "message": "The actor cannot read ontology graph data for this tenant.",
        "reason": "tenant_mismatch",
    }
    audit_event = denied_audit_events(
        authorization_session_factory,
        ONTOLOGY_GRAPH_READ_DENIED_EVENT_TYPE,
    )[0]
    assert audit_event.tenant_id == DEMO_TENANT_ID
    assert audit_event.payload["requested_tenant_id"] == "tenant_other"


def test_ontology_entity_endpoint_scope_denial_appends_audit_event(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    client = build_client(
        authorization_session_factory,
        make_principal(["operations:read"]),
    )

    response = client.get(
        f"/demo/manufacturing/ontology/entities/{SCOPED_NODE_ID}",
        headers={"Authorization": "Bearer valid-token"},
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "PERMISSION_DENIED",
        "message": "The actor cannot read this ontology entity relationship context.",
        "required_permissions": ["operations:read", "supply:read"],
        "reason": "missing_relationship_scope:supply:read",
    }
    audit_event = denied_audit_events(
        authorization_session_factory,
        ONTOLOGY_ENTITY_READ_DENIED_EVENT_TYPE,
    )[0]
    assert audit_event.actor_id == "ontology-reader"
    assert audit_event.payload["node_id"] == SCOPED_NODE_ID


def test_ontology_entity_endpoint_cross_tenant_denial_appends_audit_event(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    client = build_client(
        authorization_session_factory,
        make_principal(["operations:read", "supply:read"]),
    )

    response = client.get(
        f"/demo/manufacturing/ontology/entities/{SCOPED_NODE_ID}?tenant_id=tenant_other",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "tenant_mismatch"
    audit_event = denied_audit_events(
        authorization_session_factory,
        ONTOLOGY_ENTITY_READ_DENIED_EVENT_TYPE,
    )[0]
    assert audit_event.tenant_id == DEMO_TENANT_ID
    assert audit_event.payload["requested_tenant_id"] == "tenant_other"


def test_ontology_entity_endpoint_rejects_malformed_permission_payload(
    authorization_session_factory: sessionmaker[Session],
) -> None:
    payload = ontology_bootstrap_payload()
    payload["relationships"][0]["permission_scope"] = ""
    seed_ontology_reference(authorization_session_factory, payload)
    client = build_client(
        authorization_session_factory,
        make_principal(["operations:read", "supply:read"]),
    )

    response = client.get(
        f"/demo/manufacturing/ontology/entities/{SCOPED_NODE_ID}",
        headers={"Authorization": "Bearer valid-token"},
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_FAILED"
