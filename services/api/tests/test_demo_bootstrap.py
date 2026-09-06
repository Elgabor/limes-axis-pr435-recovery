from copy import deepcopy
from pathlib import Path
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.demo_bootstrap import (
    BOOTSTRAP_SURFACES,
    CANONICAL_DEMO_TENANT_ID,
    DEMO_BOOTSTRAP_AUDIT_EVENT_TYPE,
    DEMO_BOOTSTRAP_SCOPE,
)
from axis_api.main import create_app
from axis_api.models import AuditEvent, Base, DemoReferenceRecord
from axis_api.persistence import AxisPersistenceRepository, DemoReferenceRecordCreate

MIGRATIONS_DIR = Path(__file__).parents[1] / "migrations" / "versions"

CANONICAL_PAYLOAD_MIGRATIONS = {
    "overview": ("0022_demo_reference_records.py", "MANUFACTURING_OVERVIEW_PAYLOAD"),
    "connectors": ("0023_connector_registry_reference.py", "CONNECTOR_REGISTRY_PAYLOAD"),
    "agents": ("0024_agent_registry_reference.py", "AGENT_REGISTRY_PAYLOAD"),
    "actions": ("0025_action_registry_reference.py", "ACTION_REGISTRY_PAYLOAD"),
    "workflows": ("0026_workflow_console_reference.py", "WORKFLOW_CONSOLE_PAYLOAD"),
    "approvals": ("0027_approval_inbox_reference.py", "APPROVAL_INBOX_PAYLOAD"),
    "audit": ("0028_audit_explorer_reference.py", "AUDIT_EXPLORER_PAYLOAD"),
    "model-routing": ("0029_model_routing_reference.py", "MODEL_ROUTING_PAYLOAD"),
    "ontology": ("0030_ontology_reference.py", "ONTOLOGY_PAYLOAD"),
}

REFERENCE_ID_BY_SURFACE = dict(BOOTSTRAP_SURFACES)


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


def canonical_payload(surface: str) -> dict:
    file_name, symbol = CANONICAL_PAYLOAD_MIGRATIONS[surface]
    migration = run_path(str(MIGRATIONS_DIR / file_name))
    return deepcopy(migration[symbol])


def seed_canonical_reference_records(
    factory: sessionmaker[Session],
    surfaces: tuple[str, ...] | None = None,
) -> None:
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        for surface in surfaces or tuple(CANONICAL_PAYLOAD_MIGRATIONS):
            repository.upsert_demo_reference_record(
                DemoReferenceRecordCreate(
                    tenant_id=CANONICAL_DEMO_TENANT_ID,
                    surface=surface,
                    reference_id=REFERENCE_ID_BY_SURFACE[surface],
                    status="active",
                    source="bootstrap",
                    version="2026-06-22",
                    payload=canonical_payload(surface),
                )
            )


def bootstrap_request_payload(tenant_id: str = "tenant_fresh_plant") -> dict:
    return {
        "tenant_id": tenant_id,
        "requested_by": "platform-onboarding-operator",
        "actor_scopes": [DEMO_BOOTSTRAP_SCOPE],
    }


def build_client(session_factory: sessionmaker[Session]) -> TestClient:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    return TestClient(app)


@pytest.mark.parametrize("endpoint", ["/demo/bootstrap", "/demo/manufacturing/bootstrap"])
def test_bootstrap_creates_scenario_records_for_fresh_tenant(
    session_factory: sessionmaker[Session],
    endpoint: str,
) -> None:
    seed_canonical_reference_records(session_factory)
    client = build_client(session_factory)

    response = client.post(
        endpoint,
        json=bootstrap_request_payload(),
    )

    with session_factory() as session:
        tenant_records = session.scalars(
            select(DemoReferenceRecord).where(
                DemoReferenceRecord.tenant_id == "tenant_fresh_plant"
            )
        ).all()
        audit_event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == DEMO_BOOTSTRAP_AUDIT_EVENT_TYPE
            )
        ).one()

    client.close()
    assert response.status_code == 201
    assert ("Deprecation" in response.headers) == (endpoint != "/demo/bootstrap")
    body = response.json()
    assert body["tenant_id"] == "tenant_fresh_plant"
    assert body["bootstrapped"] is True
    assert body["scenario"] == "Plant Operations Cockpit"
    assert body["source_tenant_id"] == CANONICAL_DEMO_TENANT_ID
    assert body["audit_event_id"] == str(audit_event.id)
    assert body["audit_event_type"] == DEMO_BOOTSTRAP_AUDIT_EVENT_TYPE
    assert body["idempotent_replay"] is False
    assert {surface["surface"] for surface in body["surfaces"]} == set(
        CANONICAL_PAYLOAD_MIGRATIONS
    )
    assert all(surface["state"] == "created" for surface in body["surfaces"])
    assert audit_event.tenant_id == "tenant_fresh_plant"
    assert audit_event.actor_id == "platform-onboarding-operator"
    assert audit_event.payload["required_scope"] == DEMO_BOOTSTRAP_SCOPE
    # Nine scenario surfaces plus the bootstrap marker record.
    assert len(tenant_records) == len(CANONICAL_PAYLOAD_MIGRATIONS) + 1
    seeded = {record.surface: record for record in tenant_records}
    assert seeded["overview"].payload["tenant_id"] == "tenant_fresh_plant"
    assert seeded["audit"].payload["filter_options"]["tenants"] == ["tenant_fresh_plant"]
    assert all(
        event["tenant_id"] == "tenant_fresh_plant"
        for event in seeded["audit"].payload["events"]
    )


def test_bootstrap_makes_reference_reads_serve_the_new_tenant(
    session_factory: sessionmaker[Session],
) -> None:
    seed_canonical_reference_records(session_factory)
    client = build_client(session_factory)

    assert client.post(
        "/demo/manufacturing/bootstrap",
        json=bootstrap_request_payload(),
    ).status_code == 201

    overview_response = client.get(
        "/demo/manufacturing/overview",
        params={"tenant_id": "tenant_fresh_plant"},
    )

    client.close()
    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["tenant_id"] == "tenant_fresh_plant"
    assert overview["scenario"] == "Plant Operations Cockpit"
    assert overview["plant_name"] == "Ravenna Works"


def test_bootstrap_replay_returns_existing_record_without_duplicates(
    session_factory: sessionmaker[Session],
) -> None:
    seed_canonical_reference_records(session_factory)
    client = build_client(session_factory)
    payload = bootstrap_request_payload()

    first_response = client.post("/demo/manufacturing/bootstrap", json=payload)
    replay_response = client.post("/demo/bootstrap", json=payload)

    with session_factory() as session:
        tenant_records = session.scalars(
            select(DemoReferenceRecord).where(
                DemoReferenceRecord.tenant_id == "tenant_fresh_plant"
            )
        ).all()
        audit_events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == DEMO_BOOTSTRAP_AUDIT_EVENT_TYPE
            )
        ).all()

    client.close()
    assert first_response.status_code == 201
    assert replay_response.status_code == 200
    assert "Deprecation" in first_response.headers
    assert "Deprecation" not in replay_response.headers
    replay_body = replay_response.json()
    assert replay_body["idempotent_replay"] is True
    assert replay_body["bootstrapped"] is True
    assert replay_body["tenant_id"] == "tenant_fresh_plant"
    assert replay_body["scenario"] == "Plant Operations Cockpit"
    assert replay_body["audit_event_id"] == first_response.json()["audit_event_id"]
    assert len(audit_events) == 1
    assert len(tenant_records) == len(CANONICAL_PAYLOAD_MIGRATIONS) + 1


def test_bootstrap_preserves_existing_tenant_surface_records(
    session_factory: sessionmaker[Session],
) -> None:
    seed_canonical_reference_records(session_factory)
    existing_overview = canonical_payload("overview")
    existing_overview["tenant_id"] = "tenant_fresh_plant"
    existing_overview["plant_name"] = "Pre-existing Plant"
    with session_scope(session_factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id="tenant_fresh_plant",
                surface="overview",
                reference_id="manufacturing-overview",
                status="active",
                source="tenant-authored",
                version="2026-07-01",
                payload=existing_overview,
            )
        )
    client = build_client(session_factory)

    response = client.post(
        "/demo/manufacturing/bootstrap",
        json=bootstrap_request_payload(),
    )

    with session_factory() as session:
        overview_record = session.scalars(
            select(DemoReferenceRecord).where(
                DemoReferenceRecord.tenant_id == "tenant_fresh_plant",
                DemoReferenceRecord.surface == "overview",
            )
        ).one()

    client.close()
    assert response.status_code == 201
    surfaces = {item["surface"]: item["state"] for item in response.json()["surfaces"]}
    assert surfaces["overview"] == "existing"
    assert surfaces["workflows"] == "created"
    assert overview_record.payload["plant_name"] == "Pre-existing Plant"
    assert overview_record.source == "tenant-authored"


def test_bootstrap_rejects_missing_scope(
    session_factory: sessionmaker[Session],
) -> None:
    seed_canonical_reference_records(session_factory, surfaces=("overview",))
    client = build_client(session_factory)
    payload = bootstrap_request_payload()
    payload["actor_scopes"] = []

    response = client.post("/demo/manufacturing/bootstrap", json=payload)

    with session_factory() as session:
        tenant_records = session.scalars(
            select(DemoReferenceRecord).where(
                DemoReferenceRecord.tenant_id == "tenant_fresh_plant"
            )
        ).all()

    client.close()
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["reason"] == "missing_required_scope"
    assert detail["required_permission"] == DEMO_BOOTSTRAP_SCOPE
    assert tenant_records == []


def test_bootstrap_requires_canonical_scenario_records(
    session_factory: sessionmaker[Session],
) -> None:
    client = build_client(session_factory)

    response = client.post(
        "/demo/manufacturing/bootstrap",
        json=bootstrap_request_payload(),
    )

    client.close()
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "demo_scenario_reference_missing"


def test_bootstrap_registers_the_tenant_in_the_platform_registry(
    session_factory: sessionmaker[Session],
) -> None:
    """A bootstrapped tenant must exist to the rest of the platform.

    Seeding reference records alone left the tenant invisible to
    /platform/tenants and to every registry-backed resource (vocabulary,
    quotas, usage), so a bootstrapped tenant could not be administered like any
    other.
    """
    seed_canonical_reference_records(session_factory)
    client = build_client(session_factory)

    response = client.post(
        "/demo/manufacturing/bootstrap",
        json=bootstrap_request_payload("tenant_bootstrap_registry"),
    )
    assert response.status_code in (200, 201), response.text

    with session_scope(session_factory) as session:
        tenant = AxisPersistenceRepository(session).get_tenant("tenant_bootstrap_registry")
        assert tenant is not None
        # `conftest` back-fills a Tenant row for any reference record a test
        # inserts, using the tenant id as the name — so a bare "row exists"
        # assertion passes even without bootstrap registering anything. The
        # scenario's own plant name is what only bootstrap can supply.
        assert tenant.name != "tenant_bootstrap_registry"
        assert tenant.name == "Ravenna Works"
    client.close()
