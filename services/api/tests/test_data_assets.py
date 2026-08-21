from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.identity import OidcPrincipal
from axis_api.main import create_app
from axis_api.models import Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorRunCreate,
    DemoReferenceRecordCreate,
    TenantCreate,
)

TENANT_A = "tenant_demo_manufacturing"
TENANT_B = "tenant_other_plant"

SECRET_MARKER = "TOP-SECRET-ROW-VALUE"


def reference_registry_payload() -> dict:
    return {
        "tenant_id": TENANT_A,
        "plant_name": "Ravenna Works",
        "scenario": "Data Asset Catalog Fixture",
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
                    "sync_modes": ["preview", "manual_import"],
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
                            "source_column": "risk_level",
                            "target_field": "riskLevel",
                            "ontology_target": "manufacturing_risk",
                            "data_type": "string",
                            "required": False,
                            "description": "Asset risk level.",
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
                "preview_sample": {
                    "file_name": "assets.csv",
                    "record_count": 1,
                    "headers": ["asset_id"],
                    "sample_rows": [{"asset_id": SECRET_MARKER}],
                },
            },
            {
                "connector_status": "watch",
                "manifest": {
                    "connector_id": "external_db_operational_mirror",
                    "display_name": "Operational DB mirror",
                    "connector_type": "external_db",
                    "version": "2026-08-21",
                    "source_type": "database",
                    "sync_modes": ["schema_preview"],
                    "runtime_boundary": "axis-connector-sandbox",
                    "required_permissions": ["connectors:read"],
                    "credential_requirements": {
                        "storage": "external_reference",
                        "required_secret_refs": ["cred_external_db_readonly"],
                        "notes": [],
                    },
                    "schema_fields": [],
                    "mapping_notes": [],
                },
                "runtime_policy": {
                    "allowed_operations": ["schema_validate"],
                    "blocked_operations": ["live_query"],
                    "egress_policy": "no-external-egress",
                    "max_file_size_mb": 5,
                    "row_limit": 500,
                    "payload_policy": "metadata-only",
                },
            },
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


def seed_completed_run(factory: sessionmaker, *, connector_id: str, run_id: str) -> None:
    with session_scope(factory) as session:
        run = AxisPersistenceRepository(session).create_connector_run(
            ConnectorRunCreate(
                tenant_id=TENANT_A,
                connector_id=connector_id,
                run_id=run_id,
                status="sync_execution_completed",
                execution_mode="scheduled_sync_plan",
                runtime_boundary="axis-connector-sandbox",
                requested_by="axis-sync-worker-role",
                result_summary={"records_read": "42"},
            )
        )
        run.updated_at = datetime.now(UTC)
        repository_session = session
        repository_session.flush()


def test_data_asset_catalog_projects_reference_connectors(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    response = client.get("/data/assets", params={"tenant_id": TENANT_A})

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == TENANT_A
    assert body["provenance"] == "reference_scenario"
    assert [asset["asset_id"] for asset in body["assets"]] == [
        "source:file_csv_manufacturing_assets:default",
        "source:external_db_operational_mirror:default",
    ]
    csv_asset = body["assets"][0]
    assert csv_asset["kind"] == "default"
    assert csv_asset["evidence"] == "preview_only"
    assert csv_asset["governance"] == "partial"
    assert csv_asset["ontology_targets"] == ["manufacturing_asset", "manufacturing_risk"]
    assert csv_asset["payload_policy"] == "metadata-only"
    assert csv_asset["last_successful_sync"] is None
    db_asset = body["assets"][1]
    assert db_asset["evidence"] == "declared_only"
    assert db_asset["governance"] == "not_declared"
    labels = [metric["label"] for metric in body["metrics"]]
    assert labels == [
        "Data Assets",
        "Sync Observed",
        "Semantic Targets",
        "Stewardship Gaps",
    ]


def test_data_asset_catalog_marks_sync_observed_after_completed_run(
    session_factory: sessionmaker,
) -> None:
    seed_completed_run(
        session_factory,
        connector_id="file_csv_manufacturing_assets",
        run_id="run_catalog_001",
    )
    client = build_client(session_factory)

    response = client.get("/data/assets", params={"tenant_id": TENANT_A})

    assert response.status_code == 200
    asset = response.json()["assets"][0]
    assert asset["evidence"] == "sync_observed"
    assert asset["last_successful_sync"]["run_id"] == "run_catalog_001"
    assert asset["last_successful_sync"]["records_read"] == 42


def test_data_asset_catalog_ignores_failed_runs_for_evidence(
    session_factory: sessionmaker,
) -> None:
    with session_scope(factory=session_factory) as session:
        AxisPersistenceRepository(session).create_connector_run(
            ConnectorRunCreate(
                tenant_id=TENANT_A,
                connector_id="file_csv_manufacturing_assets",
                run_id="run_catalog_failed",
                status="sync_execution_failed",
                execution_mode="scheduled_sync_plan",
                runtime_boundary="axis-connector-sandbox",
                requested_by="axis-sync-worker-role",
                result_summary={"records_read": "0"},
            )
        )
    client = build_client(session_factory)

    response = client.get("/data/assets", params={"tenant_id": TENANT_A})

    assert response.status_code == 200
    asset = response.json()["assets"][0]
    assert asset["evidence"] == "preview_only"
    assert asset["last_successful_sync"] is None


def test_data_asset_catalog_never_leaks_preview_rows(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    response = client.get("/data/assets", params={"tenant_id": TENANT_A})

    assert response.status_code == 200
    serialized = response.text
    assert SECRET_MARKER not in serialized
    assert "sample_rows" not in serialized
    for asset in response.json()["assets"]:
        assert set(asset.keys()).isdisjoint({"preview_sample", "sample_rows"})


def test_data_asset_catalog_is_tenant_scoped(session_factory: sessionmaker) -> None:
    client = build_client(session_factory)

    other = client.get("/data/assets", params={"tenant_id": TENANT_B})

    assert other.status_code == 200
    body = other.json()
    assert body["provenance"] == "empty"
    assert body["assets"] == []
    assert "file_csv_manufacturing_assets" not in other.text


def test_data_asset_catalog_rejects_cross_tenant_principal(
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
        "/data/assets",
        params={"tenant_id": TENANT_A},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "tenant_mismatch"


def test_data_asset_catalog_unknown_tenant_returns_structured_404(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    response = client.get("/data/assets", params={"tenant_id": "tenant_unknown"})

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "TENANT_NOT_FOUND"


def test_data_asset_catalog_has_no_legacy_demo_alias(
    session_factory: sessionmaker,
) -> None:
    client = build_client(session_factory)

    response = client.get(
        "/demo/manufacturing/data/assets",
        params={"tenant_id": TENANT_A},
    )

    assert response.status_code == 404
