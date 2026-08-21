from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.connector_credential_handles import (
    ConnectorCredentialHandleCreateRequest,
    ConnectorCredentialHandleQuery,
    ConnectorCredentialHandleValidationError,
    build_connector_credential_handle_registry,
    record_demo_connector_credential_handle,
)
from axis_api.connector_manifests import (
    ConnectorManifestCreateRequest,
    ConnectorManifestLifecycleRequest,
    record_demo_connector_manifest,
    transition_demo_connector_manifest_lifecycle,
)
from axis_api.connector_reference import ConnectorReferenceRecordNotFound
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import Base
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorCredentialHandleCreate,
    ConnectorCredentialRotationCreate,
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


def connector_manifest_request(
    connector_id: str = "file_csv_manufacturing_assets",
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
            transition_reason="Validated for tenant connector credential handle tests.",
            evidence_refs=["test://connector-credential-handle-active-manifest"],
        ),
    )


def seed_connector_credential_handles(repository: AxisPersistenceRepository) -> None:
    last_rotated_at = datetime.now(UTC) - timedelta(days=7)
    next_rotation_due_at = last_rotated_at + timedelta(days=30)
    repository.create_connector_credential_handle(
        ConnectorCredentialHandleCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            handle_id="cred_file_csv_readonly",
            display_name="File CSV readonly vault reference",
            status="active",
            secret_provider="external_vault",
            secret_ref="vault://axis/demo/connectors/file-csv-readonly",
            purpose="preview_import_readonly",
            rotation_interval_days=30,
            last_rotated_at=last_rotated_at,
            next_rotation_due_at=next_rotation_due_at,
            created_by="plant-operations-owner-role",
            labels={"environment": "demo"},
            notes=["Metadata-only handle; no raw credential value is stored."],
        )
    )
    repository.record_connector_credential_rotation(
        ConnectorCredentialRotationCreate(
            tenant_id="tenant_demo_manufacturing",
            handle_id="cred_file_csv_readonly",
            rotated_by="security-operations-role",
            rotated_at=last_rotated_at,
            evidence_ref="change-window-2026-06-22",
            status="rotated",
            notes=["Reference rotated in external vault; Axis stored metadata only."],
        )
    )
    repository.create_connector_credential_handle(
        ConnectorCredentialHandleCreate(
            tenant_id="tenant_other",
            connector_id="file_csv_manufacturing_assets",
            handle_id="cred_other",
            display_name="Other tenant handle",
            status="active",
            secret_provider="external_vault",
            secret_ref="vault://axis/demo/connectors/other",
            purpose="preview_import_readonly",
            rotation_interval_days=30,
            last_rotated_at=last_rotated_at,
            next_rotation_due_at=next_rotation_due_at,
            created_by="other-owner-role",
        )
    )


def connector_credential_handle_request(
    connector_id: str = "file_csv_manufacturing_assets",
) -> ConnectorCredentialHandleCreateRequest:
    return ConnectorCredentialHandleCreateRequest(
        tenant_id="tenant_demo_manufacturing",
        connector_id=connector_id,
        handle_id="cred_file_csv_readonly",
        display_name="File CSV readonly vault reference",
        secret_provider="external_vault",
        secret_ref="vault://axis/demo/connectors/file-csv-readonly",
        purpose="preview_import_readonly",
        rotation_interval_days=30,
        created_by="plant-operations-owner-role",
        labels={"environment": "demo"},
        notes=["Metadata-only handle."],
    )


def test_connector_credential_handle_path_does_not_load_demo_connector_registry_seed() -> None:
    source = Path("src/axis_api/connector_credential_handles.py").read_text()

    assert "get_manufacturing_connector_registry" not in source


def test_record_demo_connector_credential_handle_requires_persisted_connector_registry(
    empty_session_factory: sessionmaker[Session],
) -> None:
    with session_scope(empty_session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(ConnectorReferenceRecordNotFound):
            record_demo_connector_credential_handle(
                repository,
                connector_credential_handle_request(),
            )


def test_record_demo_connector_credential_handle_uses_persisted_connector_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    payload = connector_registry_payload()
    payload["connectors"][0]["manifest"]["connector_id"] = "persisted_credential_handle_connector"
    seed_connector_registry_reference(session_factory, payload)

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_connector_manifest(
            repository,
            "persisted_credential_handle_connector",
            payload,
        )
        handle = record_demo_connector_credential_handle(
            repository,
            connector_credential_handle_request(
                connector_id="persisted_credential_handle_connector"
            ),
        )

    assert handle.connector_id == "persisted_credential_handle_connector"


def test_record_demo_connector_credential_handle_requires_active_preview_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_registered_connector_manifest(repository)
        with pytest.raises(ConnectorCredentialHandleValidationError) as exc_info:
            record_demo_connector_credential_handle(
                repository,
                connector_credential_handle_request(),
            )

    assert exc_info.value.reason == "connector_manifest_not_active_preview"


def test_build_connector_credential_handle_registry_maps_persisted_handles(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_connector_credential_handles(repository)
        registry = build_connector_credential_handle_registry(
            repository,
            ConnectorCredentialHandleQuery(tenant_id="tenant_demo_manufacturing"),
        )

    assert registry.tenant_id == "tenant_demo_manufacturing"
    assert registry.metrics[0].label == "Credential Handles"
    assert registry.metrics[0].value == "1"
    assert registry.handles[0].handle_id == "cred_file_csv_readonly"
    assert registry.handles[0].secret_provider == "external_vault"
    assert registry.handles[0].secret_ref == "vault://axis/demo/connectors/file-csv-readonly"
    assert registry.handles[0].rotation_status == "healthy"
    assert registry.handles[0].rotation_count == 1
    assert "tenant_other" not in registry.model_dump_json()
    assert "password" not in registry.model_dump_json().lower()
    assert "api_key" not in registry.model_dump_json().lower()
    assert "credential_value" not in registry.model_dump_json().lower()


def test_connector_credential_handles_endpoint_returns_tenant_scoped_records(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_connector_credential_handles(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/connectors/credential-handles",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["metrics"][0]["value"] == "1"
    assert body["handles"][0]["handle_id"] == "cred_file_csv_readonly"
    assert body["handles"][0]["rotation_status"] == "healthy"
    assert body["handles"][0]["rotation_count"] == 1
    assert "tenant_other" not in str(body)
    assert "password" not in str(body).lower()
    assert "api_key" not in str(body).lower()
    assert "credential_value" not in str(body).lower()


def test_create_connector_credential_handle_rejects_inline_secret_values(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/credential-handles",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "file_csv_manufacturing_assets",
            "handle_id": "cred_file_csv_readonly",
            "display_name": "File CSV readonly vault reference",
            "secret_provider": "external_vault",
            "secret_ref": "literal-password-value",
            "purpose": "preview_import_readonly",
            "rotation_interval_days": 30,
            "created_by": "plant-operations-owner-role",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "invalid_secret_ref"


def test_create_connector_credential_handle_persists_external_reference_only(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_active_connector_manifest(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/credential-handles",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "file_csv_manufacturing_assets",
            "handle_id": "cred_file_csv_readonly",
            "display_name": "File CSV readonly vault reference",
            "secret_provider": "external_vault",
            "secret_ref": "vault://axis/demo/connectors/file-csv-readonly",
            "purpose": "preview_import_readonly",
            "rotation_interval_days": 30,
            "created_by": "plant-operations-owner-role",
            "labels": {"environment": "demo"},
            "notes": ["Metadata-only handle."],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["handle_id"] == "cred_file_csv_readonly"
    assert body["secret_ref"] == "vault://axis/demo/connectors/file-csv-readonly"
    assert body["rotation_status"] == "healthy"
    assert body["rotation_count"] == 0
    assert "password" not in str(body).lower()
    assert "api_key" not in str(body).lower()
    assert "credential_value" not in str(body).lower()


def test_create_connector_credential_handle_requires_active_preview_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_registered_connector_manifest(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/credential-handles",
        json=connector_credential_handle_request().model_dump(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "connector_manifest_not_active_preview"


def test_create_connector_credential_handle_endpoint_reports_missing_connector_registry(
    empty_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = empty_session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/credential-handles",
        json=connector_credential_handle_request().model_dump(),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "NOT_FOUND",
        "message": "Manufacturing connector registry reference record not found.",
        "surface": "connectors",
    }


def test_rotate_connector_credential_handle_records_rotation_history(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.create_connector_credential_handle(
            ConnectorCredentialHandleCreate(
                tenant_id="tenant_demo_manufacturing",
                connector_id="file_csv_manufacturing_assets",
                handle_id="cred_file_csv_readonly",
                display_name="File CSV readonly vault reference",
                status="active",
                secret_provider="external_vault",
                secret_ref="vault://axis/demo/connectors/file-csv-readonly",
                purpose="preview_import_readonly",
                rotation_interval_days=30,
                last_rotated_at=datetime(2026, 6, 1, tzinfo=UTC),
                next_rotation_due_at=datetime(2026, 7, 1, tzinfo=UTC),
                created_by="plant-operations-owner-role",
            )
        )
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/credential-handles/cred_file_csv_readonly/rotations",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "rotated_by": "security-operations-role",
            "rotated_at": "2026-06-22T00:00:00Z",
            "evidence_ref": "change-window-2026-06-22",
            "notes": ["Reference rotated in external vault."],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["handle_id"] == "cred_file_csv_readonly"
    assert body["rotation_count"] == 1
    assert body["last_rotation"]["evidence_ref"] == "change-window-2026-06-22"
    assert body["last_rotated_at"] == "2026-06-22T00:00:00Z"
    assert body["next_rotation_due_at"] == "2026-07-22T00:00:00Z"


def test_openapi_exposes_connector_credential_handle_endpoints() -> None:
    client = TestClient(create_app())
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/demo/manufacturing/connectors/credential-handles" in paths
    assert "/demo/manufacturing/connectors/credential-handles/{handle_id}/rotations" in paths
