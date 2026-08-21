import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.identity import OidcPrincipal
from axis_api.main import create_app
from axis_api.models import AuditEvent, Base, DataAssetResourceObservation
from axis_api.persistence import (
    AxisPersistenceRepository,
    DemoReferenceRecordCreate,
    TenantCreate,
)

TENANT_A = "tenant_demo_manufacturing"
TENANT_B = "tenant_other_plant"
ASSET_A = "source:file_csv_manufacturing_assets:default"
PREVIEW_PATH = "/operations/connectors/file-csv/preview"


def reference_registry_payload() -> dict:
    return {
        "tenant_id": TENANT_A,
        "plant_name": "Ravenna Works",
        "scenario": "Resource Discovery Fixture",
        "registry_status": "ready",
        "metrics": [
            {
                "label": "Persisted Connector Registry",
                "value": "1",
                "detail": "Loaded from demo_reference_records.",
                "status": "ready",
            }
        ],
        "connectors": [
            {
                "connector_status": "ready",
                "manifest": {
                    "connector_id": "file_csv_manufacturing_assets",
                    "display_name": "Manufacturing assets CSV",
                    "connector_type": "file_csv",
                    "version": "2026-08-21",
                    "source_type": "file",
                    "sync_modes": ["preview"],
                    "runtime_boundary": "axis-connector-sandbox",
                    "required_permissions": ["connectors:read"],
                    "credential_requirements": {
                        "storage": "none",
                        "required_secret_refs": [],
                        "notes": [],
                    },
                    "schema_fields": [
                        {
                            "source_column": "asset_id",
                            "target_field": "node_id",
                            "ontology_target": "manufacturing_asset",
                            "data_type": "string",
                            "required": True,
                            "description": "Asset identifier.",
                        },
                        {
                            "source_column": "station",
                            "target_field": "station",
                            "ontology_target": "manufacturing_station",
                            "data_type": "string",
                            "required": False,
                            "description": "Station.",
                        },
                    ],
                    "mapping_notes": [],
                },
                "runtime_policy": {
                    "allowed_operations": ["schema_validate", "metadata_preview"],
                    "blocked_operations": ["live_sync"],
                    "egress_policy": "no-external-egress",
                    "max_file_size_mb": 5,
                    "row_limit": 500,
                    "payload_policy": "metadata-only",
                },
            }
        ],
        "connector_notes": [],
    }


class StaticIdentityVerifier:
    def __init__(self, principal: OidcPrincipal) -> None:
        self.principal = principal

    def verify_authorization_header(self, authorization: str | None) -> OidcPrincipal:
        assert authorization == "Bearer valid-token"
        return self.principal


@pytest.fixture
def session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.create_tenant(
            TenantCreate(
                tenant_id=TENANT_A,
                display_name="Ravenna Works",
                description="Plant Operations Cockpit",
                created_by="test",
            )
        )
        repository.create_tenant(
            TenantCreate(
                tenant_id=TENANT_B,
                display_name="Other Plant",
                description="Second tenant",
                created_by="test",
            )
        )
        repository.upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id=TENANT_A,
                surface="connectors",
                reference_id="manufacturing-connector-registry",
                status="active",
                source="bootstrap",
                version="2026-08-21",
                payload=reference_registry_payload(),
            )
        )
    yield factory
    engine.dispose()


def build_client(session_factory: sessionmaker) -> TestClient:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    return TestClient(app)


def run_ready_preview(client: TestClient, csv_content: str, file_name: str) -> dict:
    response = client.post(
        PREVIEW_PATH,
        json={
            "tenant_id": TENANT_A,
            "connector_id": "file_csv_manufacturing_assets",
            "file_name": file_name,
            "csv_content": csv_content,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def observation_count(factory: sessionmaker) -> int:
    with session_scope(factory) as session:
        return len(
            list(session.scalars(select(DataAssetResourceObservation)).all())
        )


def test_ready_preview_observes_resource_as_added(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    body = run_ready_preview(
        client,
        "asset_id,station\nA-1,line-1\n",
        "assets-day-1.csv",
    )

    assert body["preview_status"] == "ready"
    assert body["observed_schema"]["columns"] == ["asset_id", "station"]
    assert len(body["observed_schema"]["fingerprint"]) == 64

    resources = client.get(
        f"/data/assets/{ASSET_A}/resources",
        params={"tenant_id": TENANT_A},
    )
    assert resources.status_code == 200
    listed = resources.json()["resources"]
    assert len(listed) == 1
    assert listed[0]["resource_name"] == "assets-day-1.csv"
    assert listed[0]["drift_state"] == "added"
    assert listed[0]["observation_count"] == 1
    assert audit_count(session_factory, "data.resource.observed") == 1


def audit_count(factory: sessionmaker, event_type: str) -> int:
    with session_scope(factory) as session:
        return len(
            session.scalars(
                select(AuditEvent).where(AuditEvent.event_type == event_type)
            ).all()
        )


def test_repeat_preview_with_same_schema_is_unchanged(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    run_ready_preview(client, "asset_id,station\nA-1,line-1\n", "assets.csv")

    second = run_ready_preview(client, "asset_id,station\nA-2,line-2\n", "assets.csv")

    assert second["observed_schema"]["fingerprint"] == run_ready_preview(
        client,
        "asset_id,station\nA-3,line-3\n",
        "assets.csv",
    )["observed_schema"]["fingerprint"]
    resources = client.get(
        f"/data/assets/{ASSET_A}/resources",
        params={"tenant_id": TENANT_A},
    )
    listed = resources.json()["resources"]
    assert listed[0]["drift_state"] == "unchanged"
    assert listed[0]["observation_count"] == 3
    assert listed[0]["first_seen_at"] == listed[0]["last_seen_at"] or (
        listed[0]["last_seen_at"] >= listed[0]["first_seen_at"]
    )


def test_changed_headers_produce_changed_drift(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    first_fingerprint = run_ready_preview(
        client,
        "asset_id,station\nA-1,line-1\n",
        "assets.csv",
    )["observed_schema"]["fingerprint"]

    changed = run_ready_preview(
        client,
        "asset_id,machine_zone\nA-1,zone-9\n",
        "assets.csv",
    )

    assert changed["observed_schema"]["columns"] == ["asset_id", "machine_zone"]
    resources = client.get(
        f"/data/assets/{ASSET_A}/resources",
        params={"tenant_id": TENANT_A},
    )
    listed = resources.json()["resources"]
    assert listed[0]["drift_state"] == "changed"
    assert listed[0]["previous_fingerprint"] == first_fingerprint
    assert listed[0]["schema_fingerprint"] != first_fingerprint


def test_blocked_preview_records_no_observation(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    blocked = client.post(
        PREVIEW_PATH,
        json={
            "tenant_id": TENANT_A,
            "connector_id": "file_csv_manufacturing_assets",
            "file_name": "broken.csv",
            "csv_content": "unrelated_header\nx\n",
        },
    )

    assert blocked.json()["preview_status"] == "blocked"
    assert observation_count(session_factory) == 0
    assert audit_count(session_factory, "data.resource.observed") == 0


def test_resources_endpoint_fails_closed_on_unknown_asset(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    response = client.get(
        "/data/assets/source:not_a_real_asset:default/resources",
        params={"tenant_id": TENANT_A},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["surface"] == "data"


def test_resources_endpoint_rejects_cross_tenant_principal(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="actor-b",
            tenant_id=TENANT_B,
            scopes=["connectors:read"],
        )
    )

    response = client.get(
        f"/data/assets/{ASSET_A}/resources",
        params={"tenant_id": TENANT_A},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "tenant_mismatch"


def test_catalog_exposes_observed_resource_count(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    before = client.get("/data/assets", params={"tenant_id": TENANT_A})
    assert before.json()["assets"][0]["observed_resource_count"] is None

    run_ready_preview(client, "asset_id,station\nA-1,line-1\n", "one.csv")
    run_ready_preview(client, "asset_id,station\nB-1,line-2\n", "two.csv")

    after = client.get("/data/assets", params={"tenant_id": TENANT_A})
    assert after.json()["assets"][0]["observed_resource_count"] == 2


def test_observations_are_tenant_scoped(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)
    run_ready_preview(client, "asset_id,station\nA-1,line-1\n", "only-a.csv")

    other = client.get("/data/assets", params={"tenant_id": TENANT_B})

    assert other.status_code == 200
    assert other.json()["provenance"] == "empty"
    assert "only-a.csv" not in other.text
