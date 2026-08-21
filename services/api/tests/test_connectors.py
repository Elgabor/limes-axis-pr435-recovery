from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.connector_manifests import (
    ConnectorManifestCreateRequest,
    record_demo_connector_manifest,
)
from axis_api.connector_reference import get_persisted_manufacturing_connector_registry
from axis_api.connectors import (
    ConnectorCsvPreviewRequest,
    ConnectorExternalDbPreviewRequest,
    ManufacturingConnectorRegistry,
    preview_external_db_connector,
    preview_file_csv_connector,
)
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorRunCreate,
    DemoReferenceRecordCreate,
    TenantCreate,
)


def persisted_connector_registry_payload() -> dict:
    return {
        "tenant_id": "tenant_demo_manufacturing",
        "plant_name": "Persisted Ravenna Works",
        "scenario": "Persisted Connector Cockpit",
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
                    "connector_id": "persisted_file_csv_assets",
                    "display_name": "Persisted manufacturing assets CSV",
                    "connector_type": "file_csv",
                    "version": "2026-06-22",
                    "source_type": "file",
                    "sync_modes": ["preview"],
                    "runtime_boundary": "axis-connector-sandbox",
                    "required_permissions": ["connectors:read"],
                    "credential_requirements": {
                        "storage": "none",
                        "required_secret_refs": [],
                        "notes": ["No credential material required."],
                    },
                    "schema_fields": [
                        {
                            "source_column": "asset_id",
                            "target_field": "node_id",
                            "ontology_target": "manufacturing_asset",
                            "data_type": "string",
                            "required": True,
                            "description": "Persisted asset identifier.",
                        }
                    ],
                    "mapping_notes": ["Persisted test fixture."],
                },
                "runtime_policy": {
                    "allowed_operations": ["schema_validate"],
                    "blocked_operations": ["live_sync"],
                    "egress_policy": "no-external-egress",
                    "max_file_size_mb": 5,
                    "row_limit": 500,
                    "payload_policy": "metadata-only",
                },
                "preview_sample": {
                    "file_name": "persisted-assets.csv",
                    "record_count": 0,
                    "headers": ["asset_id"],
                    "sample_rows": [],
                },
            }
        ],
        "connector_notes": ["Persisted connector registry reference."],
    }


def connector_registry_payload() -> dict:
    migration = run_path("migrations/versions/0023_connector_registry_reference.py")
    return deepcopy(migration["CONNECTOR_REGISTRY_PAYLOAD"])


def bootstrap_connector_registry() -> ManufacturingConnectorRegistry:
    return ManufacturingConnectorRegistry.model_validate(connector_registry_payload())


def test_connector_registry_rejects_persisted_origin_without_metadata() -> None:
    payload = connector_registry_payload()
    payload["connectors"][0]["registry_origin"] = "persisted_manifest"

    with pytest.raises(ValueError, match="require persistence metadata"):
        ManufacturingConnectorRegistry.model_validate(payload)


def seed_connector_registry_reference(
    factory: sessionmaker[Session],
    payload: dict | None = None,
) -> None:
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id="tenant_demo_manufacturing",
                surface="connectors",
                reference_id="manufacturing-connector-registry",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=payload or connector_registry_payload(),
            )
        )


def preview_registry_with_connector_ids(
    *,
    file_csv_connector_id: str = "file_csv_manufacturing_assets",
    external_db_connector_id: str = "external_db_operational_mirror",
) -> ManufacturingConnectorRegistry:
    payload = connector_registry_payload()
    payload["connectors"][0]["manifest"]["connector_id"] = file_csv_connector_id
    payload["connectors"][1]["manifest"]["connector_id"] = external_db_connector_id
    return ManufacturingConnectorRegistry.model_validate(payload)


def create_connector_run(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str = "tenant_demo_manufacturing",
    connector_id: str = "persisted_file_csv_assets",
    run_id: str,
    status: str,
    records_read: str,
    updated_at: datetime,
) -> None:
    run = repository.create_connector_run(
        ConnectorRunCreate(
            tenant_id=tenant_id,
            connector_id=connector_id,
            run_id=run_id,
            status=status,
            execution_mode="scheduled_sync_plan",
            runtime_boundary="axis-connector-sandbox",
            requested_by="axis-sync-worker-role",
            result_summary={"records_read": records_read},
        )
    )
    run.updated_at = updated_at
    repository.session.flush()


@pytest.fixture
def connector_session_factory() -> sessionmaker[Session]:
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


def test_connector_runtime_module_does_not_define_registry_seed() -> None:
    source = Path("src/axis_api/connectors.py").read_text()

    assert "def get_manufacturing_connector_registry" not in source


def test_manufacturing_connector_registry_exposes_file_csv_manifest() -> None:
    registry = bootstrap_connector_registry()

    assert registry.tenant_id == "tenant_demo_manufacturing"
    assert registry.registry_status == "watch"
    assert registry.metrics[0].label == "Connector Manifests"
    assert registry.metrics[0].value == "2"
    assert len(registry.connectors) == 2

    connector = registry.connectors[0]
    assert connector.manifest.connector_id == "file_csv_manufacturing_assets"
    assert connector.manifest.connector_type == "file_csv"
    assert connector.manifest.sync_modes == ["preview", "manual_import"]
    assert connector.manifest.runtime_boundary == "axis-connector-sandbox"
    assert connector.manifest.required_permissions == [
        "connectors:read",
        "connectors:file_csv:preview",
    ]
    assert connector.manifest.credential_requirements.storage == "none"
    assert connector.manifest.credential_requirements.required_secret_refs == []
    assert [field.source_column for field in connector.manifest.schema_fields] == [
        "asset_id",
        "asset_name",
        "domain",
        "station",
        "risk_level",
    ]
    assert connector.preview_sample.record_count == 3
    assert "password" not in registry.model_dump_json().lower()
    assert "api_key" not in registry.model_dump_json().lower()
    assert "credential_value" not in registry.model_dump_json().lower()


def test_manufacturing_connector_registry_exposes_external_db_manifest() -> None:
    registry = bootstrap_connector_registry()

    connector = registry.connectors[1]
    assert connector.manifest.connector_id == "external_db_operational_mirror"
    assert connector.manifest.connector_type == "external_db"
    assert connector.manifest.source_type == "database"
    assert connector.manifest.sync_modes == ["schema_preview", "manual_import"]
    assert connector.manifest.runtime_boundary == "axis-connector-sandbox"
    assert connector.manifest.required_permissions == [
        "connectors:read",
        "connectors:external_db:preview",
    ]
    assert connector.manifest.credential_requirements.storage == "external_reference"
    assert connector.manifest.credential_requirements.required_secret_refs == [
        "cred_external_db_readonly"
    ]
    assert connector.runtime_policy.allowed_operations == [
        "schema_validate",
        "metadata_preview",
        "dry_run_diff",
    ]
    assert "live_query" in connector.runtime_policy.blocked_operations
    assert [field.source_column for field in connector.manifest.schema_fields] == [
        "order_id",
        "asset_id",
        "work_center",
        "status",
        "risk_level",
    ]
    serialized = registry.model_dump_json().lower()
    assert "connection_string" not in serialized
    assert "postgres://" not in serialized
    assert "password" not in serialized


def test_connector_registry_reference_contract_is_valid_and_actionable() -> None:
    registry = ManufacturingConnectorRegistry.model_validate(persisted_connector_registry_payload())

    assert registry.tenant_id == "tenant_demo_manufacturing"
    assert registry.scenario == "Persisted Connector Cockpit"
    assert registry.metrics[0].label == "Persisted Connector Registry"
    assert registry.connectors[0].manifest.connector_id == "persisted_file_csv_assets"


def test_connector_registry_bootstrap_payload_matches_contract() -> None:
    registry = bootstrap_connector_registry()

    assert registry.tenant_id == "tenant_demo_manufacturing"
    assert registry.scenario == "Plant Operations Cockpit"
    assert len(registry.connectors) == 2
    assert registry.connectors[0].manifest.connector_id == "file_csv_manufacturing_assets"
    assert registry.connectors[1].manifest.connector_id == "external_db_operational_mirror"
    serialized = registry.model_dump_json().lower()
    assert "password" not in serialized
    assert "api_key" not in serialized
    assert "credential_value" not in serialized


def test_connector_registry_endpoint_is_not_defined_as_runtime_seed() -> None:
    source = Path("src/axis_api/main.py").read_text()

    assert "return get_manufacturing_connector_registry()" not in source


def test_connector_registry_endpoint_returns_persisted_reference_data(
    connector_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    with session_scope(connector_session_factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id="tenant_demo_manufacturing",
                surface="connectors",
                reference_id="manufacturing-connector-registry",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=persisted_connector_registry_payload(),
            )
        )
    client = TestClient(app)
    response = client.get(
        "/demo/manufacturing/connectors",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["provenance"] == "reference_scenario"
    assert body["scenario"] == "Persisted Connector Cockpit"
    assert body["connectors"][0]["manifest"]["connector_id"] == "persisted_file_csv_assets"
    assert body["connectors"][0]["last_successful_sync"] is None
    assert "password" not in str(body).lower()


def test_connector_registry_reports_no_sync_observation_for_failed_runs(
    connector_session_factory: sessionmaker[Session],
) -> None:
    seed_connector_registry_reference(
        connector_session_factory,
        persisted_connector_registry_payload(),
    )
    with session_scope(connector_session_factory) as session:
        create_connector_run(
            AxisPersistenceRepository(session),
            run_id="run_failed",
            status="sync_execution_failed",
            records_read="11",
            updated_at=datetime(2026, 7, 24, 9, 0, tzinfo=UTC),
        )
    with session_scope(connector_session_factory) as session:
        registry = get_persisted_manufacturing_connector_registry(
            AxisPersistenceRepository(session),
            "tenant_demo_manufacturing",
        )

    assert registry.connectors[0].last_successful_sync is None


def test_connector_registry_reports_successful_sync_count_and_identity(
    connector_session_factory: sessionmaker[Session],
) -> None:
    seed_connector_registry_reference(
        connector_session_factory,
        persisted_connector_registry_payload(),
    )
    completed_at = datetime(2026, 7, 24, 10, 30, tzinfo=UTC)
    with session_scope(connector_session_factory) as session:
        create_connector_run(
            AxisPersistenceRepository(session),
            run_id="run_success",
            status="sync_execution_completed",
            records_read="37",
            updated_at=completed_at,
        )
    with session_scope(connector_session_factory) as session:
        registry = get_persisted_manufacturing_connector_registry(
            AxisPersistenceRepository(session),
            "tenant_demo_manufacturing",
        )

    observation = registry.connectors[0].last_successful_sync
    assert observation is not None
    assert observation.run_id == "run_success"
    assert observation.completed_at == completed_at
    assert observation.records_read == 37


def test_connector_registry_observes_success_for_manifest_only_connector(
    connector_session_factory: sessionmaker[Session],
) -> None:
    registry_payload = connector_registry_payload()
    seed_connector_registry_reference(connector_session_factory, registry_payload)
    template = registry_payload["connectors"][1]
    manifest = {
        **template["manifest"],
        "connector_id": "external_db_declarative_sampleless",
        "display_name": "Declarative sampleless database",
    }
    with session_scope(connector_session_factory) as session:
        repository = AxisPersistenceRepository(session)
        record_demo_connector_manifest(
            repository,
            ConnectorManifestCreateRequest(
                registered_by="platform-connector-owner-role",
                manifest=manifest,
                runtime_policy=template["runtime_policy"],
            ),
        )
        create_connector_run(
            repository,
            connector_id="external_db_declarative_sampleless",
            run_id="run_manifest_only_success",
            status="sync_execution_completed",
            records_read="29",
            updated_at=datetime(2026, 7, 24, 11, 0, tzinfo=UTC),
        )
        registry = get_persisted_manufacturing_connector_registry(
            repository,
            "tenant_demo_manufacturing",
        )

    connector = next(
        connector
        for connector in registry.connectors
        if connector.manifest.connector_id == "external_db_declarative_sampleless"
    )
    assert connector.preview_sample is None
    assert connector.last_successful_sync is not None
    assert connector.last_successful_sync.run_id == "run_manifest_only_success"
    assert connector.last_successful_sync.records_read == 29
    assert connector.registry_origin == "persisted_manifest"
    assert connector.persisted_manifest is not None
    assert connector.persisted_manifest.status == "registered_preview_only"


def test_connector_registry_uses_most_recent_successful_sync_completion(
    connector_session_factory: sessionmaker[Session],
) -> None:
    seed_connector_registry_reference(
        connector_session_factory,
        persisted_connector_registry_payload(),
    )
    with session_scope(connector_session_factory) as session:
        repository = AxisPersistenceRepository(session)
        create_connector_run(
            repository,
            run_id="run_completed_later",
            status="sync_execution_completed",
            records_read="41",
            updated_at=datetime(2026, 7, 24, 12, 0, tzinfo=UTC),
        )
        create_connector_run(
            repository,
            run_id="run_completed_earlier",
            status="sync_execution_completed",
            records_read="19",
            updated_at=datetime(2026, 7, 24, 11, 0, tzinfo=UTC),
        )
    with session_scope(connector_session_factory) as session:
        registry = get_persisted_manufacturing_connector_registry(
            AxisPersistenceRepository(session),
            "tenant_demo_manufacturing",
        )

    observation = registry.connectors[0].last_successful_sync
    assert observation is not None
    assert observation.run_id == "run_completed_later"
    assert observation.records_read == 41


def test_connector_registry_sync_observation_is_derived_without_manifest_write(
    connector_session_factory: sessionmaker[Session],
) -> None:
    payload = persisted_connector_registry_payload()
    seed_connector_registry_reference(
        connector_session_factory,
        payload,
    )
    with session_scope(connector_session_factory) as session:
        repository = AxisPersistenceRepository(session)
        connector = payload["connectors"][0]
        record_demo_connector_manifest(
            repository,
            ConnectorManifestCreateRequest(
                registered_by="platform-connector-owner-role",
                manifest=connector["manifest"],
                runtime_policy=connector["runtime_policy"],
            ),
        )
        manifest_before = repository.get_connector_manifest(
            "tenant_demo_manufacturing",
            "persisted_file_csv_assets",
        )
        registry_before = get_persisted_manufacturing_connector_registry(
            repository,
            "tenant_demo_manufacturing",
        )
        assert manifest_before is not None
        manifest_state_before = {
            "manifest_payload": deepcopy(manifest_before.manifest_payload),
            "runtime_policy": deepcopy(manifest_before.runtime_policy),
            "preview_sample": deepcopy(manifest_before.preview_sample),
            "updated_at": manifest_before.updated_at,
        }
        assert registry_before.connectors[0].last_successful_sync is None
        assert registry_before.connectors[0].registry_origin == "reference"
        assert registry_before.connectors[0].persisted_manifest is not None

        create_connector_run(
            repository,
            run_id="run_added_after_registry_read",
            status="sync_execution_completed",
            records_read="23",
            updated_at=datetime(2026, 7, 24, 13, 0, tzinfo=UTC),
        )
        registry_after = get_persisted_manufacturing_connector_registry(
            repository,
            "tenant_demo_manufacturing",
        )
        manifest_after = repository.get_connector_manifest(
            "tenant_demo_manufacturing",
            "persisted_file_csv_assets",
        )

    assert registry_after.connectors[0].last_successful_sync is not None
    assert registry_after.connectors[0].last_successful_sync.records_read == 23
    assert manifest_after is not None
    assert {
        "manifest_payload": manifest_after.manifest_payload,
        "runtime_policy": manifest_after.runtime_policy,
        "preview_sample": manifest_after.preview_sample,
        "updated_at": manifest_after.updated_at,
    } == manifest_state_before
    assert "last_successful_sync" not in manifest_after.manifest_payload


def test_connector_registry_endpoint_returns_empty_payload_without_reference_record(
    connector_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    client = TestClient(app)
    response = client.get(
        "/demo/manufacturing/connectors",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    assert response.json()["provenance"] == "empty"
    assert response.json()["connectors"] == []


def test_connector_registry_endpoint_composes_live_manifest_without_reference_record(
    connector_session_factory: sessionmaker[Session],
) -> None:
    connector = connector_registry_payload()["connectors"][0]
    with session_scope(connector_session_factory) as session:
        record_demo_connector_manifest(
            AxisPersistenceRepository(session),
            ConnectorManifestCreateRequest(
                registered_by="platform-connector-owner-role",
                manifest=connector["manifest"],
                runtime_policy=connector["runtime_policy"],
                preview_sample=connector["preview_sample"],
            ),
        )

    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    client = TestClient(app)

    response = client.get(
        "/operations/connectors",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )
    manifest_response = client.get(
        "/operations/connectors/manifests",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    assert manifest_response.status_code == 200
    manifest_body = manifest_response.json()
    body = response.json()
    assert body["provenance"] == "live"
    assert body["registry_status"] == "ready"
    assert body["metrics"] == [
        {
            "label": "Persisted Manifests",
            "value": "1",
            "detail": "Tenant-scoped connector manifest records",
            "status": "ready",
        }
    ]
    assert [item["manifest"]["connector_id"] for item in body["connectors"]] == [
        "file_csv_manufacturing_assets"
    ]
    assert body["connectors"][0]["connector_status"] == "watch"
    assert body["connectors"][0]["last_successful_sync"] is None
    assert body["connectors"][0]["registry_origin"] == "persisted_manifest"
    assert body["connectors"][0]["persisted_manifest"] == {
        "manifest_id": manifest_body["manifests"][0]["manifest_id"],
        "revision_number": 1,
        "status": "registered_preview_only",
        "registered_by": "platform-connector-owner-role",
        "registered_at": manifest_body["manifests"][0]["created_at"],
        "notes": [],
    }

    assert [item["connector_id"] for item in manifest_body["manifests"]] == [
        "file_csv_manufacturing_assets"
    ]
    assert "password" not in str(body).lower()
    assert "credential_value" not in str(body).lower()


def test_connector_registry_materializes_full_tenant_view_in_constant_queries(
    connector_session_factory: sessionmaker[Session],
) -> None:
    seed_connector_registry_reference(connector_session_factory)
    template = connector_registry_payload()["connectors"][0]
    oldest_connector_id = "file_csv_scale_000"
    other_tenant_connector_id = "file_csv_other_tenant"
    with session_scope(connector_session_factory) as session:
        repository = AxisPersistenceRepository(session)
        for index in range(101):
            connector_id = f"file_csv_scale_{index:03d}"
            manifest = deepcopy(template["manifest"])
            manifest.update(
                connector_id=connector_id,
                display_name=f"Scale fixture {index:03d}",
            )
            record_demo_connector_manifest(
                repository,
                ConnectorManifestCreateRequest(
                    registered_by="platform-connector-owner-role",
                    manifest=manifest,
                    runtime_policy=template["runtime_policy"],
                    preview_sample=template["preview_sample"],
                ),
            )

        other_tenant_manifest = deepcopy(template["manifest"])
        other_tenant_manifest.update(
            connector_id=other_tenant_connector_id,
            display_name="Other tenant scale fixture",
        )
        record_demo_connector_manifest(
            repository,
            ConnectorManifestCreateRequest(
                tenant_id="tenant_other",
                registered_by="platform-connector-owner-role",
                manifest=other_tenant_manifest,
                runtime_policy=template["runtime_policy"],
                preview_sample=template["preview_sample"],
            ),
        )
        create_connector_run(
            repository,
            connector_id=oldest_connector_id,
            run_id="run_scale_oldest",
            status="sync_execution_completed",
            records_read="17",
            updated_at=datetime(2026, 7, 24, 9, 0, tzinfo=UTC),
        )
        create_connector_run(
            repository,
            connector_id="file_csv_scale_100",
            run_id="run_scale_newest",
            status="sync_execution_completed",
            records_read="31",
            updated_at=datetime(2026, 7, 24, 10, 0, tzinfo=UTC),
        )
        create_connector_run(
            repository,
            tenant_id="tenant_other",
            connector_id=oldest_connector_id,
            run_id="run_scale_other_tenant",
            status="sync_execution_completed",
            records_read="999",
            updated_at=datetime(2026, 7, 24, 11, 0, tzinfo=UTC),
        )

    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    client = TestClient(app)
    engine = connector_session_factory.kw["bind"]
    query_counts = {"connector_manifests": 0, "connector_runs": 0}

    def count_registry_queries(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized_statement = statement.lower()
        for table_name in query_counts:
            if f"from {table_name}" in normalized_statement:
                query_counts[table_name] += 1

    event.listen(engine, "before_cursor_execute", count_registry_queries)
    try:
        response = client.get(
            "/operations/connectors",
            params={"tenant_id": "tenant_demo_manufacturing"},
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_registry_queries)

    assert response.status_code == 200
    assert query_counts == {"connector_manifests": 1, "connector_runs": 1}
    body = response.json()
    connectors_by_id = {
        connector["manifest"]["connector_id"]: connector
        for connector in body["connectors"]
    }
    assert len(connectors_by_id) == 103
    assert oldest_connector_id in connectors_by_id
    assert other_tenant_connector_id not in connectors_by_id
    reference_connector_id = template["manifest"]["connector_id"]
    assert connectors_by_id[reference_connector_id]["registry_origin"] == "reference"
    assert connectors_by_id[reference_connector_id]["persisted_manifest"] is None
    assert connectors_by_id[oldest_connector_id]["registry_origin"] == (
        "persisted_manifest"
    )
    oldest_persistence = connectors_by_id[oldest_connector_id]["persisted_manifest"]
    assert oldest_persistence["manifest_id"]
    assert oldest_persistence["registered_at"]
    assert oldest_persistence["revision_number"] == 1
    assert oldest_persistence["status"] == "registered_preview_only"
    assert oldest_persistence["registered_by"] == "platform-connector-owner-role"
    assert oldest_persistence["notes"] == []
    assert connectors_by_id[oldest_connector_id]["last_successful_sync"] == {
        "run_id": "run_scale_oldest",
        "completed_at": "2026-07-24T09:00:00Z",
        "records_read": 17,
    }
    assert connectors_by_id["file_csv_scale_100"]["last_successful_sync"] == {
        "run_id": "run_scale_newest",
        "completed_at": "2026-07-24T10:00:00Z",
        "records_read": 31,
    }
    persisted_metric = next(
        metric for metric in body["metrics"] if metric["label"] == "Persisted Manifests"
    )
    assert persisted_metric["value"] == "101"
    connector_metric = next(
        metric for metric in body["metrics"] if metric["label"] == "Connector Manifests"
    )
    assert connector_metric["value"] == "103"

    with session_scope(connector_session_factory) as session:
        registry = get_persisted_manufacturing_connector_registry(
            AxisPersistenceRepository(session),
            "tenant_demo_manufacturing",
        )
    preview_sample = template["preview_sample"]
    csv_content = "\n".join(
        [
            ",".join(preview_sample["headers"]),
            ",".join(
                preview_sample["sample_rows"][0].get(header, "")
                for header in preview_sample["headers"]
            ),
        ]
    )
    preview = preview_file_csv_connector(
        registry,
        ConnectorCsvPreviewRequest(
            tenant_id="tenant_demo_manufacturing",
            connector_id=oldest_connector_id,
            file_name="scale-fixture.csv",
            csv_content=csv_content,
        ),
    )

    assert preview.preview_status == "ready"
    assert preview.accepted_record_count == 1


def test_connector_registry_endpoint_rejects_invalid_reference_payload(
    connector_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    with session_scope(connector_session_factory) as session:
        payload = persisted_connector_registry_payload()
        payload["tenant_id"] = "tenant_wrong"
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id="tenant_demo_manufacturing",
                surface="connectors",
                reference_id="manufacturing-connector-registry",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=payload,
            )
        )
    client = TestClient(app)
    response = client.get(
        "/demo/manufacturing/connectors",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_FAILED"


def test_file_csv_connector_preview_maps_rows_to_ontology_entities() -> None:
    preview = preview_file_csv_connector(
        bootstrap_connector_registry(),
        ConnectorCsvPreviewRequest(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            file_name="assets.csv",
            csv_content=(
                "asset_id,asset_name,domain,station,risk_level\n"
                "asset_line_2_packaging,Line 2 Packaging,Operations,Line 2,high\n"
                "asset_press_4,Press 4,Maintenance,Press 4,medium\n"
            ),
        ),
    )

    assert preview.connector_id == "file_csv_manufacturing_assets"
    assert preview.preview_status == "ready"
    assert preview.sync_mode == "preview_only"
    assert preview.record_count == 2
    assert preview.accepted_record_count == 2
    assert preview.rejected_record_count == 0
    assert preview.validation_issues == []
    assert [entity.node_id for entity in preview.proposed_entities] == [
        "asset_line_2_packaging",
        "asset_press_4",
    ]
    assert preview.proposed_entities[0].node_type == "asset"
    assert preview.proposed_entities[0].ontology_type == "manufacturing_asset"
    assert preview.proposed_entities[0].field_summary == {
        "asset_name": "Line 2 Packaging",
        "domain": "Operations",
        "station": "Line 2",
        "risk_level": "high",
    }
    assert preview.audit_event_preview.event_type == "connector.preview.generated"
    assert preview.audit_event_preview.scope == "file_csv_manufacturing_assets"
    assert "assets.csv" in preview.audit_event_preview.evidence_refs
    assert "csv_content" not in preview.model_dump_json()


def test_file_csv_connector_preview_blocks_missing_required_columns() -> None:
    preview = preview_file_csv_connector(
        bootstrap_connector_registry(),
        ConnectorCsvPreviewRequest(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            file_name="assets.csv",
            csv_content=(
                "asset_id,asset_name,domain,risk_level\n"
                "asset_line_2_packaging,Line 2 Packaging,Operations,high\n"
            ),
        ),
    )

    assert preview.preview_status == "blocked"
    assert preview.record_count == 1
    assert preview.accepted_record_count == 0
    assert preview.rejected_record_count == 1
    assert preview.proposed_entities == []
    assert preview.validation_issues == [
        "Missing required column: station",
    ]


def test_file_csv_connector_preview_blocks_empty_required_values() -> None:
    preview = preview_file_csv_connector(
        bootstrap_connector_registry(),
        ConnectorCsvPreviewRequest(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            file_name="assets.csv",
            csv_content=(
                "asset_id,asset_name,domain,station,risk_level\n"
                ",Line 2 Packaging,Operations,Line 2,high\n"
            ),
        ),
    )

    assert preview.preview_status == "blocked"
    assert preview.proposed_entities == []
    assert preview.validation_issues == [
        "Row 2 has an empty required value: asset_id",
    ]


def test_file_csv_connector_preview_blocks_duplicate_node_ids() -> None:
    preview = preview_file_csv_connector(
        bootstrap_connector_registry(),
        ConnectorCsvPreviewRequest(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            file_name="assets.csv",
            csv_content=(
                "asset_id,asset_name,domain,station,risk_level\n"
                "asset_line_2,Line 2 Packaging,Operations,Line 2,high\n"
                "asset_line_2,Line 2 Packaging,Operations,Line 2,high\n"
            ),
        ),
    )

    assert preview.preview_status == "blocked"
    assert preview.proposed_entities == []
    assert preview.validation_issues == [
        "Row 3 has a duplicate node id: asset_line_2",
    ]


def test_file_csv_connector_preview_blocks_unsupported_connector_ids() -> None:
    preview = preview_file_csv_connector(
        bootstrap_connector_registry(),
        ConnectorCsvPreviewRequest(
            tenant_id="tenant_demo_manufacturing",
            connector_id="unknown_connector",
            file_name="assets.csv",
            csv_content=(
                "asset_id,asset_name,domain,station,risk_level\n"
                "asset_line_2_packaging,Line 2 Packaging,Operations,Line 2,high\n"
            ),
        ),
    )

    assert preview.preview_status == "blocked"
    assert preview.accepted_record_count == 0
    assert preview.rejected_record_count == 1
    assert preview.proposed_entities == []
    assert preview.validation_issues == [
        "Unsupported connector_id: unknown_connector",
    ]


def test_file_csv_connector_preview_accepts_persisted_manifest_connector_id() -> None:
    preview = preview_file_csv_connector(
        preview_registry_with_connector_ids(file_csv_connector_id="persisted_file_csv_preview"),
        ConnectorCsvPreviewRequest(
            tenant_id="tenant_demo_manufacturing",
            connector_id="persisted_file_csv_preview",
            file_name="assets.csv",
            csv_content=(
                "asset_id,asset_name,domain,station,risk_level\n"
                "asset_line_2_packaging,Line 2 Packaging,Operations,Line 2,high\n"
            ),
        ),
    )

    assert preview.connector_id == "persisted_file_csv_preview"
    assert preview.preview_status == "ready"
    assert preview.accepted_record_count == 1


def test_external_db_connector_preview_returns_metadata_only_mapping() -> None:
    preview = preview_external_db_connector(
        bootstrap_connector_registry(),
        ConnectorExternalDbPreviewRequest(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            connection_profile_id="profile_postgres_ops_readonly",
            schema_name="operations",
            table_name="production_orders",
            selected_columns=[
                "order_id",
                "asset_id",
                "work_center",
                "status",
                "risk_level",
            ],
            sample_limit=2,
            credential_handle_id="cred_external_db_readonly",
        ),
    )

    assert preview.connector_id == "external_db_operational_mirror"
    assert preview.preview_status == "ready"
    assert preview.sync_mode == "schema_preview_only"
    assert preview.live_query_executed is False
    assert preview.inspected_table.schema_name == "operations"
    assert preview.inspected_table.table_name == "production_orders"
    assert preview.inspected_table.sample_limit == 2
    assert [column.source_column for column in preview.inspected_table.columns] == [
        "order_id",
        "asset_id",
        "work_center",
        "status",
        "risk_level",
    ]
    assert preview.proposed_entities[0].ontology_type == "production_order"
    assert preview.audit_event_preview.event_type == "connector.external_db.previewed"
    assert preview.audit_event_preview.scope == "external_db_operational_mirror"
    assert preview.audit_event_preview.payload_preview == {
        "connection_profile_id": "profile_postgres_ops_readonly",
        "table_ref": "operations.production_orders",
        "live_query_executed": "false",
        "credential_handle_id": "cred_external_db_readonly",
    }
    serialized = preview.model_dump_json().lower()
    assert "connection_string" not in serialized
    assert "postgres://" not in serialized
    assert "password" not in serialized
    assert "raw_sql" not in serialized


def test_external_db_connector_preview_blocks_raw_connection_and_query_material() -> None:
    preview = preview_external_db_connector(
        bootstrap_connector_registry(),
        ConnectorExternalDbPreviewRequest(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            connection_profile_id="profile_postgres_ops_readonly",
            schema_name="operations",
            table_name="production_orders",
            selected_columns=["order_id"],
            sample_limit=1,
            credential_handle_id="cred_external_db_readonly",
            metadata={
                "connection_string": "postgres://user:password@example.local/db",
                "raw_sql": "select * from production_orders",
            },
        ),
    )

    assert preview.preview_status == "blocked"
    assert preview.live_query_executed is False
    assert preview.proposed_entities == []
    assert preview.validation_issues == [
        "Raw connection material is not accepted in external DB preview.",
        "Raw SQL or query text is not accepted in external DB preview.",
    ]
    assert preview.audit_event_preview.result == "blocked"
    serialized = preview.model_dump_json().lower()
    assert "postgres://" not in serialized
    assert "select *" not in serialized
    assert "password" not in serialized


def test_external_db_connector_preview_accepts_persisted_manifest_connector_id() -> None:
    preview = preview_external_db_connector(
        preview_registry_with_connector_ids(
            external_db_connector_id="persisted_external_db_preview"
        ),
        ConnectorExternalDbPreviewRequest(
            tenant_id="tenant_demo_manufacturing",
            connector_id="persisted_external_db_preview",
            connection_profile_id="profile_postgres_ops_readonly",
            schema_name="operations",
            table_name="production_orders",
            selected_columns=["order_id", "asset_id", "status"],
            sample_limit=2,
            credential_handle_id="cred_external_db_readonly",
        ),
    )

    assert preview.connector_id == "persisted_external_db_preview"
    assert preview.preview_status == "ready"
    assert preview.live_query_executed is False
    assert [column.source_column for column in preview.inspected_table.columns] == [
        "order_id",
        "asset_id",
        "status",
    ]


def test_external_db_connector_preview_states_when_sample_was_never_recorded() -> None:
    payload = connector_registry_payload()
    payload["connectors"][1]["preview_sample"] = None
    registry = ManufacturingConnectorRegistry.model_validate(payload)

    preview = preview_external_db_connector(
        registry,
        ConnectorExternalDbPreviewRequest(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            connection_profile_id="profile_postgres_ops_readonly",
            schema_name="operations",
            table_name="production_orders",
            selected_columns=["order_id", "asset_id", "status"],
            sample_limit=2,
            credential_handle_id="cred_external_db_readonly",
        ),
    )

    assert preview.preview_status == "blocked"
    assert preview.validation_issues == [
        "No preview sample has been recorded for this connector."
    ]
    assert preview.inspected_table.sample_rows == []
    assert preview.proposed_entities == []


def test_connector_registry_endpoint_returns_bootstrap_public_manifest(
    connector_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    seed_connector_registry_reference(connector_session_factory)
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/connectors",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["connectors"][0]["manifest"]["connector_id"] == ("file_csv_manufacturing_assets")
    assert body["connectors"][0]["manifest"]["credential_requirements"]["storage"] == "none"
    assert body["connectors"][1]["manifest"]["connector_id"] == ("external_db_operational_mirror")
    assert "password" not in str(body).lower()
    assert "api_key" not in str(body).lower()
    assert "credential_value" not in str(body).lower()


def test_connector_file_csv_preview_endpoint_returns_redacted_mapping_preview(
    connector_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    seed_connector_registry_reference(connector_session_factory)
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/file-csv/preview",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "file_csv_manufacturing_assets",
            "file_name": "assets.csv",
            "csv_content": (
                "asset_id,asset_name,domain,station,risk_level\n"
                "asset_line_2_packaging,Line 2 Packaging,Operations,Line 2,high\n"
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["preview_status"] == "ready"
    assert body["record_count"] == 1
    assert body["proposed_entities"][0]["node_id"] == "asset_line_2_packaging"
    assert body["audit_event_preview"]["event_type"] == "connector.preview.generated"
    assert "csv_content" not in str(body)


def test_connector_file_csv_preview_endpoint_reports_missing_registry_reference(
    connector_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/file-csv/preview",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "file_csv_manufacturing_assets",
            "file_name": "assets.csv",
            "csv_content": (
                "asset_id,asset_name,domain,station,risk_level\n"
                "asset_line_2_packaging,Line 2 Packaging,Operations,Line 2,high\n"
            ),
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "NOT_FOUND",
        "message": "Manufacturing connector registry reference record not found.",
        "surface": "connectors",
    }


def test_connector_file_csv_preview_endpoint_uses_persisted_registry_reference(
    connector_session_factory: sessionmaker[Session],
) -> None:
    payload = connector_registry_payload()
    payload["connectors"][0]["manifest"]["connector_id"] = "persisted_file_csv_preview"
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    seed_connector_registry_reference(connector_session_factory, payload)
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/file-csv/preview",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "persisted_file_csv_preview",
            "file_name": "assets.csv",
            "csv_content": (
                "asset_id,asset_name,domain,station,risk_level\n"
                "asset_line_2_packaging,Line 2 Packaging,Operations,Line 2,high\n"
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["preview_status"] == "ready"


def test_connector_external_db_preview_endpoint_returns_metadata_only_preview(
    connector_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    seed_connector_registry_reference(connector_session_factory)
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/external-db/preview",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "external_db_operational_mirror",
            "connection_profile_id": "profile_postgres_ops_readonly",
            "schema_name": "operations",
            "table_name": "production_orders",
            "selected_columns": ["order_id", "asset_id", "status"],
            "sample_limit": 2,
            "credential_handle_id": "cred_external_db_readonly",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["preview_status"] == "ready"
    assert body["live_query_executed"] is False
    assert body["audit_event_preview"]["event_type"] == "connector.external_db.previewed"
    assert body["inspected_table"]["columns"][0]["source_column"] == "order_id"
    assert "connection_string" not in str(body).lower()
    assert "postgres://" not in str(body).lower()
    assert "password" not in str(body).lower()


def test_connector_external_db_preview_endpoint_states_never_sampled_reason(
    connector_session_factory: sessionmaker[Session],
) -> None:
    payload = connector_registry_payload()
    payload["connectors"][1]["preview_sample"] = None
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    seed_connector_registry_reference(connector_session_factory, payload)
    client = TestClient(app)

    response = client.post(
        "/operations/connectors/external-db/preview",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "external_db_operational_mirror",
            "connection_profile_id": "profile_postgres_ops_readonly",
            "schema_name": "operations",
            "table_name": "production_orders",
            "selected_columns": ["order_id", "asset_id", "status"],
            "sample_limit": 2,
            "credential_handle_id": "cred_external_db_readonly",
        },
    )

    assert response.status_code == 200
    assert response.json()["preview_status"] == "blocked"
    assert response.json()["validation_issues"] == [
        "No preview sample has been recorded for this connector."
    ]
    assert response.json()["inspected_table"]["sample_rows"] == []


def test_connector_external_db_preview_endpoint_uses_sampleless_registered_manifest(
    connector_session_factory: sessionmaker[Session],
) -> None:
    registry_payload = connector_registry_payload()
    template = registry_payload["connectors"][1]
    manifest = {
        **template["manifest"],
        "connector_id": "external_db_declarative_sampleless",
        "display_name": "Declarative sampleless database",
    }
    with session_scope(connector_session_factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.upsert_demo_reference_record(
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
        record_demo_connector_manifest(
            repository,
            ConnectorManifestCreateRequest(
                registered_by="platform-connector-owner-role",
                manifest=manifest,
                runtime_policy=template["runtime_policy"],
            ),
        )
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    client = TestClient(app)

    response = client.post(
        "/operations/connectors/external-db/preview",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "external_db_declarative_sampleless",
            "connection_profile_id": "profile_postgres_ops_readonly",
            "schema_name": "operations",
            "table_name": "production_orders",
            "selected_columns": ["order_id", "asset_id", "status"],
            "sample_limit": 2,
            "credential_handle_id": "cred_external_db_readonly",
        },
    )

    assert response.status_code == 200
    assert response.json()["validation_issues"] == [
        "No preview sample has been recorded for this connector."
    ]
    assert response.json()["inspected_table"]["sample_rows"] == []


def test_connector_external_db_preview_endpoint_reports_missing_registry_reference(
    connector_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/external-db/preview",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "external_db_operational_mirror",
            "connection_profile_id": "profile_postgres_ops_readonly",
            "schema_name": "operations",
            "table_name": "production_orders",
            "selected_columns": ["order_id", "asset_id", "status"],
            "sample_limit": 2,
            "credential_handle_id": "cred_external_db_readonly",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "NOT_FOUND",
        "message": "Manufacturing connector registry reference record not found.",
        "surface": "connectors",
    }


def test_connector_external_db_preview_endpoint_uses_persisted_registry_reference(
    connector_session_factory: sessionmaker[Session],
) -> None:
    payload = connector_registry_payload()
    payload["connectors"][1]["manifest"]["connector_id"] = "persisted_external_db_preview"
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = connector_session_factory
    seed_connector_registry_reference(connector_session_factory, payload)
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/external-db/preview",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "persisted_external_db_preview",
            "connection_profile_id": "profile_postgres_ops_readonly",
            "schema_name": "operations",
            "table_name": "production_orders",
            "selected_columns": ["order_id", "asset_id", "status"],
            "sample_limit": 2,
            "credential_handle_id": "cred_external_db_readonly",
        },
    )

    assert response.status_code == 200
    assert response.json()["preview_status"] == "ready"


def test_openapi_exposes_connector_endpoints() -> None:
    client = TestClient(create_app())
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/demo/manufacturing/connectors" in paths
    assert "/demo/manufacturing/connectors/file-csv/preview" in paths
    assert "/demo/manufacturing/connectors/external-db/preview" in paths
