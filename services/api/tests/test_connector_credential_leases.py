from copy import deepcopy
from datetime import UTC, datetime
from runpy import run_path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.connector_credential_leases import (
    ConnectorCredentialLeaseQuery,
    ConnectorCredentialLeaseRequest,
    ConnectorCredentialLeaseValidationError,
    CredentialLeaseRuntimeRequest,
    ProviderSpecificVaultKmsLeaseRuntime,
    SelfHostedVaultKmsLeaseRuntime,
    build_connector_credential_lease_registry,
    record_demo_connector_credential_lease,
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
    ConnectorCredentialLeaseCreate,
    DemoReferenceRecordCreate,
    TenantCreate,
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
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).create_tenant(
            TenantCreate(
                tenant_id="tenant_demo_manufacturing",
                display_name="Ravenna Works",
                description="Plant Operations Cockpit",
                created_by="test",
            )
        )
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
            transition_reason="Validated for tenant connector credential lease tests.",
            evidence_refs=["test://connector-credential-lease-active-manifest"],
        ),
    )


def seed_active_handle(
    repository: AxisPersistenceRepository,
    *,
    manifest_status: str | None = "active_preview",
) -> None:
    if manifest_status == "active_preview":
        seed_active_connector_manifest(repository)
    elif manifest_status == "registered_preview_only":
        seed_registered_connector_manifest(repository)
    elif manifest_status is not None:
        raise ValueError(f"Unsupported test manifest_status: {manifest_status}")

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
            labels={"environment": "demo"},
            notes=["Metadata-only handle; no raw credential value is stored."],
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
            created_by="other-owner-role",
        )
    )


def lease_request() -> ConnectorCredentialLeaseRequest:
    return ConnectorCredentialLeaseRequest(
        tenant_id="tenant_demo_manufacturing",
        connector_id="file_csv_manufacturing_assets",
        handle_id="cred_file_csv_readonly",
        lease_id="lease_file_csv_readonly_20260622",
        requested_by="axis-connector-runtime-role",
        actor_scopes=["connectors:credential_lease:request"],
        lease_purpose="governed_dry_run",
        requested_at=datetime(2026, 6, 22, 9, 30, tzinfo=UTC),
        lease_duration_seconds=900,
        renewal_window_seconds=300,
        vault_kms_policy={
            "provider_mode": "self_hosted_vault",
            "lease_path": "axis/demo/connectors/file-csv-readonly",
            "kms_key_ref": "kms://axis/demo/connectors",
        },
        notes=["Lease grants metadata-only access; secret values are never returned."],
    )


def test_build_connector_credential_lease_registry_maps_persisted_records(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_handle(repository)
        created = record_demo_connector_credential_lease(repository, lease_request())
        registry = build_connector_credential_lease_registry(
            repository,
            ConnectorCredentialLeaseQuery(tenant_id="tenant_demo_manufacturing"),
        )

    assert registry.tenant_id == "tenant_demo_manufacturing"
    assert registry.provenance == "live"
    assert registry.metrics[0].label == "Credential Leases"
    assert registry.metrics[0].value == "1"
    assert registry.leases[0].lease_id == created.lease_id
    assert registry.leases[0].status == "active"
    assert registry.leases[0].lease_mode == "deferred_vault_kms_lease"
    assert registry.leases[0].lease_result["secret_material_returned"] == "false"
    assert registry.leases[0].audit_event_type == "connector.credential_lease.requested"
    serialized = registry.model_dump_json().lower()
    assert "tenant_other" not in serialized
    assert "password" not in serialized
    assert "api_key" not in serialized
    assert "credential_value" not in serialized
    assert "secret_value" not in serialized


def test_empty_connector_credential_lease_registry_uses_tenant_metadata(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.create_tenant(
            TenantCreate(
                tenant_id="tenant_customer_leases",
                display_name="Genoa Logistics",
                description="",
                created_by="test",
            )
        )
        registry = build_connector_credential_lease_registry(
            repository,
            ConnectorCredentialLeaseQuery(tenant_id="tenant_customer_leases"),
        )

    assert registry.plant_name == "Genoa Logistics"
    assert registry.scenario is None
    assert registry.provenance == "empty"
    assert registry.leases == []
    assert "Ravenna" not in registry.model_dump_json()


def test_connector_credential_leases_endpoint_returns_tenant_scoped_records(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_handle(repository)
        record_demo_connector_credential_lease(repository, lease_request())
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/connectors/credential-leases",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["provenance"] == "live"
    assert body["metrics"][0]["value"] == "1"
    assert body["leases"][0]["lease_id"] == "lease_file_csv_readonly_20260622"
    assert body["leases"][0]["renewal_due_at"] == "2026-06-22T09:40:00Z"
    assert body["leases"][0]["audit_event_type"] == "connector.credential_lease.requested"
    assert "tenant_other" not in str(body)
    assert "password" not in str(body).lower()
    assert "api_key" not in str(body).lower()
    assert "credential_value" not in str(body).lower()


def test_connector_credential_leases_endpoint_writes_read_audit_event(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_handle(repository)
        record_demo_connector_credential_lease(repository, lease_request())
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/connectors/credential-leases",
        params={
            "tenant_id": "tenant_demo_manufacturing",
            "connector_id": "file_csv_manufacturing_assets",
            "actor_id": "connector-credential-lease-reader",
        },
    )

    assert response.status_code == 200
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        events = [
            event
            for event in repository.list_audit_events(
                tenant_id="tenant_demo_manufacturing",
                event_type="connector.credential_leases_read",
                limit=10,
            )
        ]

    assert len(events) == 1
    event = events[0]
    assert event.actor_id == "connector-credential-lease-reader"
    assert event.payload == {
        "connector_id": "file_csv_manufacturing_assets",
        "handle_id": None,
        "status": None,
        "limit": 100,
        "returned_lease_count": 1,
        "lease_evidence_invariant_count": 0,
        "lease_ids": ["lease_file_csv_readonly_20260622"],
    }
    assert "vault://" not in str(event.payload).lower()
    assert "credential_value" not in str(event.payload).lower()
    assert "password" not in str(event.payload).lower()


def test_connector_credential_leases_endpoint_reports_audit_payload_invariants(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_handle(repository)
        lease_audit_event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id="tenant_demo_manufacturing",
                actor_id="axis-connector-runtime-role",
                event_type="connector.credential_lease.requested",
                payload={
                    "connector_id": "file_csv_manufacturing_assets",
                    "handle_id": "cred_file_csv_readonly",
                    "lease_id": "lease_payload_mismatch_other",
                    "lease_mode": "deferred_vault_kms_lease",
                    "lease_purpose": "governed_dry_run",
                    "runtime_boundary": "axis-credential-lease-broker",
                    "secret_provider": "external_vault",
                    "secret_material_returned": "false",
                    "adapter": "axis-deferred-vault-kms-lease-adapter",
                },
            )
        )
        repository.create_connector_credential_lease(
            ConnectorCredentialLeaseCreate(
                tenant_id="tenant_demo_manufacturing",
                connector_id="file_csv_manufacturing_assets",
                handle_id="cred_file_csv_readonly",
                lease_id="lease_payload_mismatch_target",
                requested_by="axis-connector-runtime-role",
                lease_purpose="governed_dry_run",
                secret_provider="external_vault",
                secret_ref="vault://axis/demo/connectors/file-csv-readonly",
                vault_kms_policy={
                    "provider_mode": "self_hosted_vault",
                    "lease_path": "axis/demo/connectors/file-csv-readonly",
                },
                permission_decision={"allowed": True, "reason": "all_required_scopes_present"},
                lease_result={
                    "adapter": "axis-deferred-vault-kms-lease-adapter",
                    "status": "lease_deferred",
                    "external_secret_read": "false",
                    "secret_material_returned": "false",
                    "provider_mode": "deferred",
                    "provider_lease_ref": (
                        "deferred-lease://tenant_demo_manufacturing/lease_payload_mismatch_target"
                    ),
                },
                granted_at=datetime(2026, 6, 27, 10, 0, tzinfo=UTC),
                expires_at=datetime(2026, 6, 27, 10, 15, tzinfo=UTC),
                renewal_due_at=datetime(2026, 6, 27, 10, 10, tzinfo=UTC),
                audit_event_id=lease_audit_event.id,
                audit_event_type="connector.credential_lease.requested",
                notes=["Lease seeded with mismatched audit payload."],
            )
        )
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/connectors/credential-leases",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["metrics"][2]["label"] == "Lease Evidence Invariants"
    assert body["metrics"][2]["value"] == "1"
    assert body["metrics"][2]["status"] == "watch"
    assert body["lease_evidence_invariants"] == [
        {
            "lease_id": "lease_payload_mismatch_target",
            "audit_event_id": str(lease_audit_event.id),
            "reason": "lease_audit_event_payload_mismatch",
            "detail": (
                "Lease audit event payload must match connector_id, handle_id and lease_id."
            ),
        }
    ]
    assert "password" not in str(body).lower()
    assert "credential_value" not in str(body).lower()


def test_request_connector_credential_lease_requires_scope(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_active_handle(AxisPersistenceRepository(session))
    client = TestClient(app)
    request = lease_request().model_dump(mode="json")
    request["actor_scopes"] = []

    response = client.post("/demo/manufacturing/connectors/credential-leases", json=request)

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "missing_required_scope"
    assert response.json()["detail"]["required_permission"] == (
        "connectors:credential_lease:request"
    )


def test_request_connector_credential_lease_rejects_raw_secret_material(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_active_handle(AxisPersistenceRepository(session))
    client = TestClient(app)
    request = lease_request().model_dump(mode="json")
    request["vault_kms_policy"]["inline_secret"] = "secret_value=abc123"

    response = client.post("/demo/manufacturing/connectors/credential-leases", json=request)

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "raw_secret_material"


def test_record_demo_connector_credential_lease_requires_persisted_connector_registry(
    empty_session_factory: sessionmaker[Session],
) -> None:
    with session_scope(empty_session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_handle(repository, manifest_status=None)
        with pytest.raises(ConnectorReferenceRecordNotFound):
            record_demo_connector_credential_lease(repository, lease_request())


def test_record_demo_connector_credential_lease_requires_active_preview_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_handle(repository, manifest_status="registered_preview_only")
        with pytest.raises(ConnectorCredentialLeaseValidationError) as exc_info:
            record_demo_connector_credential_lease(repository, lease_request())

    assert exc_info.value.reason == "connector_manifest_not_active_preview"


def test_request_connector_credential_lease_persists_deferred_lease(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_active_handle(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/credential-leases",
        json=lease_request().model_dump(mode="json"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["lease_id"] == "lease_file_csv_readonly_20260622"
    assert body["handle_id"] == "cred_file_csv_readonly"
    assert body["status"] == "active"
    assert body["lease_mode"] == "deferred_vault_kms_lease"
    assert body["expires_at"] == "2026-06-22T09:45:00Z"
    assert body["renewal_due_at"] == "2026-06-22T09:40:00Z"
    assert body["permission_decision"]["allowed"] is True
    assert body["lease_result"]["adapter"] == "axis-deferred-vault-kms-lease-adapter"
    assert body["lease_result"]["external_secret_read"] == "false"
    assert body["lease_result"]["secret_material_returned"] == "false"
    assert body["audit_event_type"] == "connector.credential_lease.requested"
    assert "password" not in str(body).lower()
    assert "credential_value" not in str(body).lower()


def test_request_connector_credential_lease_requires_active_preview_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_active_handle(
            AxisPersistenceRepository(session),
            manifest_status="registered_preview_only",
        )
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/credential-leases",
        json=lease_request().model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "connector_manifest_not_active_preview"


def test_request_connector_credential_lease_endpoint_reports_missing_connector_registry(
    empty_session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = empty_session_factory
    with session_scope(empty_session_factory) as session:
        seed_active_handle(AxisPersistenceRepository(session), manifest_status=None)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/demo/manufacturing/connectors/credential-leases",
        json=lease_request().model_dump(mode="json"),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "NOT_FOUND",
        "message": "Manufacturing connector registry reference record not found.",
        "surface": "connectors",
    }


def test_self_hosted_vault_kms_runtime_executes_lease_without_secret_material() -> None:
    runtime = SelfHostedVaultKmsLeaseRuntime()

    result = runtime.request_lease(
        CredentialLeaseRuntimeRequest(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            handle_id="cred_file_csv_readonly",
            lease_id="lease_file_csv_readonly_20260622",
            action="request",
            secret_provider="external_vault",
            secret_ref="vault://axis/demo/connectors/file-csv-readonly",
            vault_kms_policy={
                "provider_mode": "self_hosted_vault",
                "lease_path": "axis/demo/connectors/file-csv-readonly",
                "kms_key_ref": "kms://axis/demo/connectors",
            },
            evidence_ref="lease:lease_file_csv_readonly_20260622",
        )
    )

    assert result.adapter == "axis-self-hosted-vault-kms-lease-adapter"
    assert result.status == "lease_executed"
    assert result.provider_mode == "self_hosted_vault"
    assert result.provider_lease_ref == (
        "vault-lease://tenant_demo_manufacturing/lease_file_csv_readonly_20260622"
    )
    assert result.external_secret_read == "false"
    assert result.secret_material_returned == "false"
    serialized = result.model_dump_json().lower()
    assert "password" not in serialized
    assert "credential_value" not in serialized
    assert "secret_value" not in serialized


def test_provider_specific_vault_kms_runtime_attests_vault_without_secret_material() -> None:
    runtime = ProviderSpecificVaultKmsLeaseRuntime()

    result = runtime.request_lease(
        CredentialLeaseRuntimeRequest(
            tenant_id="tenant_demo_manufacturing",
            connector_id="file_csv_manufacturing_assets",
            handle_id="cred_file_csv_readonly",
            lease_id="lease_file_csv_readonly_20260622",
            action="request",
            secret_provider="external_vault",
            secret_ref="vault://axis/demo/connectors/file-csv-readonly",
            vault_kms_policy={
                "provider_mode": "hashicorp_vault",
                "lease_path": "axis/demo/connectors/file-csv-readonly",
                "kms_key_ref": "kms://axis/demo/connectors",
            },
            evidence_ref="lease:lease_file_csv_readonly_20260622",
        )
    )

    assert result.adapter == "axis-provider-specific-vault-kms-lease-adapter"
    assert result.status == "lease_executed"
    assert result.provider_mode == "hashicorp_vault"
    assert result.provider_lease_ref == (
        "vault://axis/leases/tenant_demo_manufacturing/lease_file_csv_readonly_20260622"
    )
    assert result.external_secret_read == "false"
    assert result.secret_material_returned == "false"
    serialized = result.model_dump_json().lower()
    assert "password" not in serialized
    assert "credential_value" not in serialized
    assert "secret_value" not in serialized


def test_provider_specific_vault_kms_runtime_rejects_provider_ref_mismatch() -> None:
    runtime = ProviderSpecificVaultKmsLeaseRuntime()

    with pytest.raises(ConnectorCredentialLeaseValidationError) as exc:
        runtime.request_lease(
            CredentialLeaseRuntimeRequest(
                tenant_id="tenant_demo_manufacturing",
                connector_id="file_csv_manufacturing_assets",
                handle_id="cred_file_csv_readonly",
                lease_id="lease_file_csv_readonly_20260622",
                action="request",
                secret_provider="external_vault",
                secret_ref="aws-secrets-manager://axis/demo/connectors/file-csv-readonly",
                vault_kms_policy={
                    "provider_mode": "hashicorp_vault",
                    "lease_path": "axis/demo/connectors/file-csv-readonly",
                    "kms_key_ref": "kms://axis/demo/connectors",
                },
                evidence_ref="lease:lease_file_csv_readonly_20260622",
            )
        )

    assert exc.value.reason == "provider_secret_ref_mismatch"


def test_request_connector_credential_lease_uses_live_runtime_when_enabled(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            credential_lease_execution_enabled=True,
        )
    )
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_active_handle(AxisPersistenceRepository(session))
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/credential-leases",
        json=lease_request().model_dump(mode="json"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["lease_mode"] == "self_hosted_vault_kms_lease"
    assert body["lease_result"]["adapter"] == "axis-self-hosted-vault-kms-lease-adapter"
    assert body["lease_result"]["status"] == "lease_executed"
    assert body["lease_result"]["provider_mode"] == "self_hosted_vault"
    assert body["lease_result"]["external_secret_read"] == "false"
    assert body["lease_result"]["secret_material_returned"] == "false"


def test_request_connector_credential_lease_uses_provider_specific_runtime_when_enabled(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            credential_lease_provider_adapters_enabled=True,
        )
    )
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        seed_active_handle(AxisPersistenceRepository(session))
    client = TestClient(app)
    request = lease_request().model_dump(mode="json")
    request["lease_id"] = "lease_file_csv_provider_vault_20260622"
    request["vault_kms_policy"]["provider_mode"] = "hashicorp_vault"

    response = client.post(
        "/demo/manufacturing/connectors/credential-leases",
        json=request,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["lease_mode"] == "provider_specific_vault_kms_lease"
    assert body["lease_result"]["adapter"] == ("axis-provider-specific-vault-kms-lease-adapter")
    assert body["lease_result"]["status"] == "lease_executed"
    assert body["lease_result"]["provider_mode"] == "hashicorp_vault"
    assert body["lease_result"]["provider_lease_ref"] == (
        "vault://axis/leases/tenant_demo_manufacturing/lease_file_csv_provider_vault_20260622"
    )
    assert body["lease_result"]["external_secret_read"] == "false"
    assert body["lease_result"]["secret_material_returned"] == "false"


def test_renew_connector_credential_lease_extends_expiry_with_audit(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_handle(repository)
        record_demo_connector_credential_lease(repository, lease_request())
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/credential-leases/lease_file_csv_readonly_20260622/renew",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "renewed_by": "axis-connector-runtime-role",
            "actor_scopes": ["connectors:credential_lease:renew"],
            "renewed_at": "2026-06-22T09:42:00Z",
            "extend_seconds": 900,
            "renewal_reason": "dry-run still executing",
            "evidence_ref": "workflow:wf_connector_runtime:signal-lease-renewal",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert body["renewal_count"] == 1
    assert body["renewed_by"] == "axis-connector-runtime-role"
    assert body["expires_at"] == "2026-06-22T09:57:00Z"
    assert body["renewal_due_at"] == "2026-06-22T09:52:00Z"
    assert body["audit_event_type"] == "connector.credential_lease.renewed"


def test_renew_connector_credential_lease_uses_live_runtime_when_enabled(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            credential_lease_execution_enabled=True,
        )
    )
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_handle(repository)
        record_demo_connector_credential_lease(repository, lease_request())
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/credential-leases/lease_file_csv_readonly_20260622/renew",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "renewed_by": "axis-connector-runtime-role",
            "actor_scopes": ["connectors:credential_lease:renew"],
            "renewed_at": "2026-06-22T09:42:00Z",
            "extend_seconds": 900,
            "renewal_reason": "dry-run still executing",
            "evidence_ref": "workflow:wf_connector_runtime:signal-lease-renewal",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["lease_result"]["adapter"] == "axis-self-hosted-vault-kms-lease-adapter"
    assert body["lease_result"]["status"] == "lease_renewed"
    assert body["lease_result"]["provider_lease_ref"] == (
        "vault-lease://tenant_demo_manufacturing/lease_file_csv_readonly_20260622"
    )


def test_revoke_connector_credential_lease_closes_lease_with_audit(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_handle(repository)
        record_demo_connector_credential_lease(repository, lease_request())
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/credential-leases/lease_file_csv_readonly_20260622/revoke",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "revoked_by": "security-operations-role",
            "actor_scopes": ["connectors:credential_lease:revoke"],
            "revoked_at": "2026-06-22T09:44:00Z",
            "revocation_reason": "workflow completed",
            "evidence_ref": "workflow:wf_connector_runtime:completed",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "revoked"
    assert body["revoked_by"] == "security-operations-role"
    assert body["revoked_at"] == "2026-06-22T09:44:00Z"
    assert body["audit_event_type"] == "connector.credential_lease.revoked"


def test_revoke_connector_credential_lease_uses_live_runtime_when_enabled(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            credential_lease_execution_enabled=True,
        )
    )
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        seed_active_handle(repository)
        record_demo_connector_credential_lease(repository, lease_request())
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/credential-leases/lease_file_csv_readonly_20260622/revoke",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "revoked_by": "security-operations-role",
            "actor_scopes": ["connectors:credential_lease:revoke"],
            "revoked_at": "2026-06-22T09:44:00Z",
            "revocation_reason": "workflow completed",
            "evidence_ref": "workflow:wf_connector_runtime:completed",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["lease_result"]["adapter"] == "axis-self-hosted-vault-kms-lease-adapter"
    assert body["lease_result"]["status"] == "lease_revoked"
    assert body["lease_result"]["secret_material_returned"] == "false"


def test_openapi_exposes_connector_credential_lease_endpoints(openapi_schema: dict) -> None:
    paths = openapi_schema["paths"]
    assert "/demo/manufacturing/connectors/credential-leases" in paths
    assert "get" in paths["/demo/manufacturing/connectors/credential-leases"]
    assert "post" in paths["/demo/manufacturing/connectors/credential-leases"]
    assert "/demo/manufacturing/connectors/credential-leases/{lease_id}/renew" in paths
    assert "/demo/manufacturing/connectors/credential-leases/{lease_id}/revoke" in paths


def test_lease_create_rejects_non_string_runtime_result_values() -> None:
    """The persisted lease_result is public-safe string evidence.

    A boolean here used to persist silently and then fail the whole lease
    registry read model at query time; the write boundary must reject it.
    """
    with pytest.raises(ValidationError, match="secret_material_returned"):
        ConnectorCredentialLeaseCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            handle_id="cred_external_db_readonly",
            lease_id="lease_invalid_bool_result",
            requested_by="axis-connector-runtime-role",
            lease_purpose="governed_dry_run",
            secret_provider="external_vault",
            secret_ref="vault://axis/demo/connectors/external-db-readonly",
            permission_decision={
                "allowed": True,
                "reason": "all_required_scopes_present",
            },
            lease_result={
                "adapter": "axis-self-hosted-vault-kms-lease-adapter",
                "status": "lease_executed",
                "provider_lease_ref": "self-hosted-vault-kms://tenant/lease_x",
                "secret_material_returned": False,
            },
            granted_at=datetime(2026, 8, 23, 10, 0, tzinfo=UTC),
            expires_at=datetime(2026, 8, 23, 10, 15, tzinfo=UTC),
            renewal_due_at=datetime(2026, 8, 23, 10, 10, tzinfo=UTC),
        )


def test_lease_create_requires_complete_permission_decision() -> None:
    """A decision without its reason is not governance evidence.

    Console contracts render `allowed` + `reason`; a partial decision passed
    raw repository writes once and then failed every registry parse. The
    Create model is the boundary that keeps persisted rows readable.
    """
    with pytest.raises(ValidationError):
        ConnectorCredentialLeaseCreate(
            tenant_id="tenant_demo_manufacturing",
            connector_id="external_db_operational_mirror",
            handle_id="cred_external_db_readonly",
            lease_id="lease_missing_reason",
            requested_by="axis-connector-runtime-role",
            lease_purpose="governed_dry_run",
            secret_provider="external_vault",
            secret_ref="vault://axis/demo/connectors/external-db-readonly",
            permission_decision={"allowed": True},
            granted_at=datetime(2026, 8, 23, 10, 0, tzinfo=UTC),
            expires_at=datetime(2026, 8, 23, 10, 15, tzinfo=UTC),
            renewal_due_at=datetime(2026, 8, 23, 10, 10, tzinfo=UTC),
        )
