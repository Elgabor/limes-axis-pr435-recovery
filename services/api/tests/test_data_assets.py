from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
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
    DataAssetStewardshipCreate,
    DataResourceObservationCreate,
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


# --- Catalog read bounding (issue #363) ---

CATALOG_ASSET_IDS = (
    "source:file_csv_manufacturing_assets:default",
    "source:external_db_operational_mirror:default",
)
OFF_CATALOG_ASSET_IDS = tuple(f"source:retired_connector_{n}:default" for n in range(1, 6))


@contextmanager
def captured_sql(session_factory: sessionmaker):
    """Record every statement the endpoint actually sends to the database."""

    engine = session_factory.kw["bind"]
    statements: list[str] = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)


def seed_stewardship_and_observations(
    session_factory: sessionmaker,
    asset_ids: tuple[str, ...],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        for asset_id in asset_ids:
            repository.create_data_asset_stewardship_record(
                DataAssetStewardshipCreate(
                    tenant_id=TENANT_A,
                    asset_id=asset_id,
                    revision_number=1,
                    owner="plant-operations",
                    classification="internal",
                    residency="eu",
                    retention="P5Y",
                    declared_by="test",
                )
            )
            repository.create_data_resource_observation(
                DataResourceObservationCreate(
                    tenant_id=TENANT_A,
                    connector_id=asset_id.split(":")[1],
                    asset_id=asset_id,
                    resource_name="line_events",
                    drift_state="added",
                    observed_by="test",
                )
            )


def test_catalog_reads_are_bounded_to_the_returned_assets(
    session_factory: sessionmaker,
) -> None:
    """The supporting reads must scale with the response, not with the tenant.

    Both reads used to be tenant-wide: one materialized every current
    stewardship row and the other grouped every observation the tenant had,
    while the response only ever uses the assets the registry returns.
    """

    seed_stewardship_and_observations(session_factory, CATALOG_ASSET_IDS)
    seed_stewardship_and_observations(session_factory, OFF_CATALOG_ASSET_IDS)
    client = build_client(session_factory)

    with captured_sql(session_factory) as statements:
        response = client.get("/data/assets", params={"tenant_id": TENANT_A})

    assert response.status_code == 200
    stewardship_reads = [s for s in statements if "FROM data_asset_stewardship_records" in s]
    observation_reads = [s for s in statements if "FROM data_asset_resource_observations" in s]
    assert stewardship_reads, "the catalog must still read stewardship"
    assert observation_reads, "the catalog must still read observations"
    assert all("asset_id IN" in statement for statement in stewardship_reads)
    assert all("asset_id IN" in statement for statement in observation_reads)


def test_off_catalog_rows_do_not_change_the_catalog_response(
    session_factory: sessionmaker,
) -> None:
    """Scoping the reads is behaviour-preserving.

    Rows for assets outside the registry were already ignored by the projection;
    they were simply read first. The response must be identical either way.
    """

    seed_stewardship_and_observations(session_factory, CATALOG_ASSET_IDS)
    client = build_client(session_factory)
    without_noise = client.get("/data/assets", params={"tenant_id": TENANT_A}).json()

    seed_stewardship_and_observations(session_factory, OFF_CATALOG_ASSET_IDS)
    with_noise = client.get("/data/assets", params={"tenant_id": TENANT_A}).json()

    assert with_noise == without_noise
    # Guard the other direction too: the scope must still cover every asset the
    # response returns, so under-scoping cannot pass by making both sides equal.
    assert [asset["asset_id"] for asset in with_noise["assets"]] == list(CATALOG_ASSET_IDS)
    assert all(asset["stewardship"] is not None for asset in with_noise["assets"])
    assert all(asset["observed_resource_count"] == 1 for asset in with_noise["assets"])


def test_scoped_reads_return_nothing_without_asset_ids(
    session_factory: sessionmaker,
) -> None:
    """An empty catalog short-circuits instead of issuing a tenant-wide read."""

    seed_stewardship_and_observations(session_factory, CATALOG_ASSET_IDS)

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with captured_sql(session_factory) as statements:
            assert repository.list_current_data_asset_stewardship(TENANT_A, []) == []
            assert repository.count_data_resource_observations_by_asset(TENANT_A, []) == {}

    assert statements == []


def test_scoped_reads_stay_within_the_tenant(session_factory: sessionmaker) -> None:
    """Asset ids are not a cross-tenant lookup key."""

    seed_stewardship_and_observations(session_factory, CATALOG_ASSET_IDS)

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        assert repository.list_current_data_asset_stewardship(TENANT_B, CATALOG_ASSET_IDS) == []
        assert (
            repository.count_data_resource_observations_by_asset(TENANT_B, CATALOG_ASSET_IDS)
            == {}
        )


def test_large_catalog_reads_preserve_all_assets_with_a_database_parameter_limit(
    session_factory: sessionmaker,
) -> None:
    # SQLite supports an enforced connection-level bind-parameter budget. This
    # exercises the actual database error boundary rather than mocking SQL.
    import sqlite3

    asset_ids = tuple(f"source:large_catalog_{n:04d}:default" for n in range(1001))
    seed_stewardship_and_observations(session_factory, asset_ids)
    with session_scope(session_factory) as session:
        connection = session.connection().connection.driver_connection
        previous_limit = connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
        try:
            repository = AxisPersistenceRepository(session)
            # Duplicate, unsorted input must not duplicate rows or lose global
            # ordering when it crosses a query-batch boundary.
            requested_ids = [*reversed(asset_ids), *asset_ids[:5]]
            stewardship = repository.list_current_data_asset_stewardship(
                TENANT_A, requested_ids,
            )
            counts = repository.count_data_resource_observations_by_asset(
                TENANT_A, requested_ids,
            )
            assert [row.asset_id for row in stewardship] == list(asset_ids)
            assert counts == dict.fromkeys(asset_ids, 1)
        finally:
            connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, previous_limit)
