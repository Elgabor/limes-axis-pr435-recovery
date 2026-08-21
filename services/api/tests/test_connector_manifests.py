from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.connector_manifests import (
    MANIFEST_VALIDATION_BATCH_LIMIT,
    ConnectorManifestCreateRequest,
    ConnectorManifestLifecycleRequest,
    ConnectorManifestLifecycleValidationError,
    ConnectorManifestQuery,
    build_connector_manifest_registry,
    record_demo_connector_manifest,
    transition_demo_connector_manifest_lifecycle,
)
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import AuditEvent, Base, ConnectorManifestRecord
from axis_api.persistence import AxisPersistenceRepository


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


def external_db_manifest_request() -> ConnectorManifestCreateRequest:
    return ConnectorManifestCreateRequest(
        tenant_id="tenant_demo_manufacturing",
        registered_by="platform-connector-owner-role",
        manifest={
            "connector_id": "external_db_shift_orders",
            "display_name": "Shift orders database mirror",
            "connector_type": "external_db",
            "version": "2026-06-22",
            "source_type": "database",
            "sync_modes": ["schema_preview", "manual_import"],
            "runtime_boundary": "axis-connector-sandbox",
            "required_permissions": [
                "connectors:read",
                "connectors:external_db:preview",
            ],
            "credential_requirements": {
                "storage": "external_reference",
                "required_secret_refs": ["cred_external_db_readonly"],
                "notes": ["Metadata-only credential handle reference."],
            },
            "schema_fields": [
                {
                    "source_column": "order_id",
                    "target_field": "node_id",
                    "ontology_target": "production_order",
                    "data_type": "string",
                    "required": True,
                    "description": "Stable production order identifier.",
                }
            ],
            "mapping_notes": ["Registered as a preview-only manifest."],
        },
        runtime_policy={
            "allowed_operations": ["schema_validate", "metadata_preview"],
            "blocked_operations": [
                "live_query",
                "live_write",
                "credential_capture",
                "external_egress",
            ],
            "egress_policy": "no-external-egress",
            "max_file_size_mb": 5,
            "row_limit": 100,
            "payload_policy": "metadata-only-redacted-preview",
        },
        preview_sample={
            "file_name": "profile_postgres_ops_readonly:operations.shift_orders",
            "record_count": 1,
            "headers": ["order_id"],
            "sample_rows": [{"order_id": "order_shift_100"}],
        },
        notes=["Manifest is registered without enabling live sync."],
    )


def live_capable_external_db_manifest_request() -> ConnectorManifestCreateRequest:
    request_payload = external_db_manifest_request().model_dump()
    request_payload["manifest"]["sync_modes"] = [
        "schema_preview",
        "manual_import",
        "live_query",
    ]
    request_payload["manifest"]["mapping_notes"] = [
        "Registered with live query capability behind a separate lifecycle gate."
    ]
    request_payload["runtime_policy"]["allowed_operations"] = [
        "schema_validate",
        "metadata_preview",
        "live_query",
        "external_egress",
    ]
    request_payload["runtime_policy"]["blocked_operations"] = [
        "live_write",
        "credential_capture",
    ]
    request_payload["runtime_policy"]["egress_policy"] = (
        "allowlisted-private-egress-with-policy-evidence"
    )
    request_payload["runtime_policy"]["payload_policy"] = (
        "metadata-and-row-digest-redacted-live-query"
    )
    request_payload["notes"] = [
        "Manifest is registered live-capable but not live-enabled until lifecycle approval."
    ]
    return ConnectorManifestCreateRequest.model_validate(request_payload)


def manifest_validation_document(
    request: ConnectorManifestCreateRequest,
) -> dict:
    payload = request.model_dump()
    payload.pop("tenant_id")
    payload.pop("registered_by")
    return payload


def sampleless_external_db_manifest_payload(
    *, connector_id: str = "external_db_sampleless_orders"
) -> dict:
    payload = external_db_manifest_request().model_dump()
    payload["manifest"]["connector_id"] = connector_id
    payload["manifest"]["display_name"] = "Sampleless orders database mirror"
    payload.pop("preview_sample")
    return payload


def manifest_validation_request(
    *requests: ConnectorManifestCreateRequest,
) -> dict:
    return {
        "tenant_id": "tenant_demo_manufacturing",
        "registered_by": "platform-connector-owner-role",
        "manifests": [
            manifest_validation_document(request)
            for request in requests
        ],
    }


def manifest_replacement_payload(
    request: ConnectorManifestCreateRequest,
    *,
    idempotency_key: str,
    version: str | None = None,
    expected_revision_number: int | None = None,
) -> dict:
    payload = request.model_dump()
    payload["idempotency_key"] = idempotency_key
    if version is not None:
        payload["manifest"]["version"] = version
    if expected_revision_number is not None:
        payload["expected_revision_number"] = expected_revision_number
    return payload


def test_build_connector_manifest_registry_maps_persisted_records(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        created = record_demo_connector_manifest(repository, external_db_manifest_request())
        registry = build_connector_manifest_registry(
            repository,
            ConnectorManifestQuery(tenant_id="tenant_demo_manufacturing"),
        )

    assert registry.tenant_id == "tenant_demo_manufacturing"
    assert registry.registry_status == "ready"
    assert registry.metrics[0].label == "Persisted Manifests"
    assert registry.metrics[0].value == "1"
    assert len(registry.manifests) == 1
    manifest = registry.manifests[0]
    assert manifest.manifest_id == created.manifest_id
    assert manifest.connector_id == "external_db_shift_orders"
    assert manifest.status == "registered_preview_only"
    assert manifest.audit_event_type == "connector.manifest.registered"
    assert manifest.manifest["connector_id"] == "external_db_shift_orders"
    assert manifest.runtime_policy["blocked_operations"] == [
        "live_query",
        "live_write",
        "credential_capture",
        "external_egress",
    ]
    serialized = registry.model_dump_json().lower()
    assert "connection_string" not in serialized
    assert "postgres://" not in serialized
    assert "password" not in serialized


def test_connector_manifests_endpoint_returns_tenant_scoped_records(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        record_demo_connector_manifest(
            AxisPersistenceRepository(session),
            external_db_manifest_request(),
        )
    client = TestClient(app)

    response = client.get(
        "/demo/manufacturing/connectors/manifests",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["metrics"][0]["value"] == "1"
    assert body["manifests"][0]["connector_id"] == "external_db_shift_orders"
    assert body["manifests"][0]["audit_event_type"] == "connector.manifest.registered"
    assert "postgres://" not in str(body).lower()
    assert "password" not in str(body).lower()


def test_create_connector_manifest_endpoint_rejects_raw_connection_material(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = external_db_manifest_request().model_dump()
    request["manifest"]["connection_string"] = "postgres://user:password@example.local/db"

    response = client.post("/demo/manufacturing/connectors/manifests", json=request)

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "raw_connection_field"


def test_create_connector_manifest_endpoint_rejects_invalid_manifest_payload(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = external_db_manifest_request().model_dump()
    request["manifest"].pop("connector_id")

    response = client.post("/demo/manufacturing/connectors/manifests", json=request)

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "invalid_manifest_payload"


def test_create_connector_manifest_endpoint_persists_public_safe_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/manifests",
        json=external_db_manifest_request().model_dump(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["connector_id"] == "external_db_shift_orders"
    assert body["revision_number"] == 1
    assert body["status"] == "registered_preview_only"
    assert body["audit_event_id"] is not None
    assert body["audit_event_type"] == "connector.manifest.registered"
    assert body["manifest"]["connector_id"] == "external_db_shift_orders"


def test_create_connector_manifest_without_sample_records_never_sampled_state(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = sampleless_external_db_manifest_payload()

    created = client.post("/operations/connectors/manifests", json=request)
    registry = client.get(
        "/operations/connectors/manifests",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )
    detail = client.get(
        "/operations/connectors/manifests/external_db_sampleless_orders",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert created.status_code == 201
    assert created.json()["preview_sample"] is None
    assert registry.status_code == 200
    assert registry.json()["manifests"][0]["preview_sample"] is None
    assert detail.status_code == 200
    assert detail.json()["current_revision"]["preview_sample"] is None


def test_create_connector_manifest_with_zero_rows_keeps_recorded_sample(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = external_db_manifest_request().model_dump()
    request["preview_sample"] = {
        "file_name": "operations.empty_orders",
        "record_count": 0,
        "headers": ["order_id"],
        "sample_rows": [],
    }

    response = client.post("/operations/connectors/manifests", json=request)

    assert response.status_code == 201
    assert response.json()["preview_sample"] == request["preview_sample"]


def test_replace_connector_manifest_without_sample_preserves_recorded_sample(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = external_db_manifest_request()
    client.post("/operations/connectors/manifests", json=request.model_dump())
    replacement = manifest_replacement_payload(
        request,
        idempotency_key="preserve-recorded-preview-sample",
        version="2026-07-25",
    )
    replacement.pop("preview_sample")

    response = client.put(
        "/operations/connectors/manifests/external_db_shift_orders",
        json=replacement,
    )
    with session_scope(session_factory) as session:
        audit_event = session.get(AuditEvent, UUID(response.json()["audit_event_id"]))

    assert response.status_code == 200
    assert response.json()["preview_sample"] == request.preview_sample.model_dump()
    assert audit_event is not None
    assert audit_event.payload["preview_sample_action"] == "preserved"


def test_replace_connector_manifest_with_null_sample_clears_recorded_sample(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = external_db_manifest_request()
    client.post("/operations/connectors/manifests", json=request.model_dump())
    replacement = manifest_replacement_payload(
        request,
        idempotency_key="clear-recorded-preview-sample",
        version="2026-07-25",
    )
    replacement["preview_sample"] = None

    response = client.put(
        "/operations/connectors/manifests/external_db_shift_orders",
        json=replacement,
    )

    assert response.status_code == 200
    assert response.json()["preview_sample"] is None


def test_create_connector_manifest_endpoint_rejects_duplicate_manifest(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = external_db_manifest_request().model_dump()

    first = client.post("/demo/manufacturing/connectors/manifests", json=request)
    second = client.post("/demo/manufacturing/connectors/manifests", json=request)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"]["reason"] == "manifest_already_exists"
    assert second.json()["detail"]["connector_id"] == "external_db_shift_orders"


def test_replace_connector_manifest_increments_revision_and_retains_ordered_history(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = external_db_manifest_request()
    assert client.post(
        "/operations/connectors/manifests",
        json=request.model_dump(),
    ).status_code == 201

    second = client.put(
        "/operations/connectors/manifests/external_db_shift_orders",
        json=manifest_replacement_payload(
            request,
            idempotency_key="manifest-revision-2",
            version="2026-07-01",
        ),
    )
    third = client.put(
        "/operations/connectors/manifests/external_db_shift_orders",
        json=manifest_replacement_payload(
            request,
            idempotency_key="manifest-revision-3",
            version="2026-07-02",
        ),
    )
    history = client.get(
        "/operations/connectors/manifests/external_db_shift_orders",
        params={"tenant_id": "tenant_demo_manufacturing"},
    )

    assert second.status_code == 200
    assert second.json()["revision_number"] == 2
    assert second.json()["revises_revision_number"] == 1
    assert third.status_code == 200
    assert third.json()["revision_number"] == 3
    assert history.status_code == 200
    body = history.json()
    assert body["current_revision"]["revision_number"] == 3
    assert [revision["revision_number"] for revision in body["revisions"]] == [1, 2, 3]
    assert [revision["version"] for revision in body["revisions"]] == [
        "2026-06-22",
        "2026-07-01",
        "2026-07-02",
    ]
    assert [revision["replaced_by_revision_number"] for revision in body["revisions"]] == [
        2,
        3,
        None,
    ]


def test_replace_connector_manifest_identical_document_is_unchanged(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = external_db_manifest_request()
    client.post("/operations/connectors/manifests", json=request.model_dump())

    response = client.put(
        "/operations/connectors/manifests/external_db_shift_orders",
        json=manifest_replacement_payload(
            request,
            idempotency_key="identical-manifest",
        ),
    )

    assert response.status_code == 200
    assert response.json()["revision_number"] == 1
    assert response.json()["unchanged"] is True
    with session_scope(session_factory) as session:
        assert session.scalar(
            select(func.count()).select_from(ConnectorManifestRecord)
        ) == 1
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_replace_connector_manifest_idempotent_replay_returns_stored_revision(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = external_db_manifest_request()
    client.post("/operations/connectors/manifests", json=request.model_dump())
    replacement = manifest_replacement_payload(
        request,
        idempotency_key="replay-manifest-revision",
        version="2026-07-01",
    )

    first = client.put(
        "/operations/connectors/manifests/external_db_shift_orders",
        json=replacement,
    )
    replay = client.put(
        "/operations/connectors/manifests/external_db_shift_orders",
        json=replacement,
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["manifest_id"] == first.json()["manifest_id"]
    assert replay.json()["revision_number"] == 2
    assert replay.json()["idempotent_replay"] is True
    with session_scope(session_factory) as session:
        assert session.scalar(
            select(func.count()).select_from(ConnectorManifestRecord)
        ) == 2


def test_replace_connector_manifest_rejects_conflicting_idempotency_replay(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = external_db_manifest_request()
    client.post("/operations/connectors/manifests", json=request.model_dump())
    client.put(
        "/operations/connectors/manifests/external_db_shift_orders",
        json=manifest_replacement_payload(
            request,
            idempotency_key="conflicting-manifest-revision",
            version="2026-07-01",
        ),
    )

    response = client.put(
        "/operations/connectors/manifests/external_db_shift_orders",
        json=manifest_replacement_payload(
            request,
            idempotency_key="conflicting-manifest-revision",
            version="2026-07-02",
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "revision_idempotency_conflict"


def test_replace_connector_manifest_expected_revision_guard(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = external_db_manifest_request()
    client.post("/operations/connectors/manifests", json=request.model_dump())

    mismatch = client.put(
        "/operations/connectors/manifests/external_db_shift_orders",
        json=manifest_replacement_payload(
            request,
            idempotency_key="revision-guard-mismatch",
            version="2026-07-01",
            expected_revision_number=2,
        ),
    )
    match = client.put(
        "/operations/connectors/manifests/external_db_shift_orders",
        json=manifest_replacement_payload(
            request,
            idempotency_key="revision-guard-match",
            version="2026-07-01",
            expected_revision_number=1,
        ),
    )

    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["reason"] == "expected_revision_mismatch"
    assert mismatch.json()["detail"]["current_revision_number"] == 1
    assert match.status_code == 200
    assert match.json()["revision_number"] == 2


def test_replace_connector_manifest_unknown_id_is_not_found(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = external_db_manifest_request().model_dump()
    request["manifest"]["connector_id"] = "unknown_connector"
    request["idempotency_key"] = "unknown-manifest-revision"

    response = client.put(
        "/operations/connectors/manifests/unknown_connector",
        json=request,
    )

    assert response.status_code == 404
    assert response.json()["detail"]["connector_id"] == "unknown_connector"


def test_replace_connector_manifest_records_revision_audit_evidence(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = external_db_manifest_request()
    client.post("/operations/connectors/manifests", json=request.model_dump())

    response = client.put(
        "/operations/connectors/manifests/external_db_shift_orders",
        json=manifest_replacement_payload(
            request,
            idempotency_key="audited-manifest-revision",
            version="2026-07-01",
        ),
    )
    with session_scope(session_factory) as session:
        audit_event = session.get(AuditEvent, UUID(response.json()["audit_event_id"]))

    assert response.status_code == 200
    assert audit_event is not None
    assert audit_event.event_type == "connector.manifest.replaced"
    assert audit_event.payload["revises_revision_number"] == 1
    assert audit_event.payload["revision_number"] == 2
    assert audit_event.payload["previous_manifest_version"] == "2026-06-22"
    assert audit_event.payload["manifest_version"] == "2026-07-01"


def test_validate_connector_manifests_returns_mixed_batch_in_request_order(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        record_demo_connector_manifest(
            AxisPersistenceRepository(session),
            external_db_manifest_request(),
        )
    client = TestClient(app)
    new_request_payload = external_db_manifest_request().model_dump()
    new_request_payload["manifest"]["connector_id"] = "external_db_new_orders"
    new_request_payload["manifest"]["display_name"] = "New orders database mirror"
    new_request = ConnectorManifestCreateRequest.model_validate(new_request_payload)
    invalid_document = manifest_validation_document(external_db_manifest_request())
    invalid_document["manifest"].pop("connector_id")
    request = manifest_validation_request(
        new_request,
        external_db_manifest_request(),
    )
    request["manifests"].append(invalid_document)

    response = client.post(
        "/operations/connectors/manifests/validation",
        json=request,
    )

    assert response.status_code == 200
    body = response.json()
    assert [result["connector_id"] for result in body["results"]] == [
        "external_db_new_orders",
        "external_db_shift_orders",
        None,
    ]
    assert [result["outcome"] for result in body["results"]] == [
        "would_register",
        "would_replace",
        "invalid",
    ]
    assert body["results"][2]["errors"] == [
        {
            "field_path": "manifest.connector_id",
            "message": "Field required",
            "reason": "invalid_manifest_payload",
        }
    ]
    assert body["summary"] == {
        "would_register": 1,
        "would_replace": 1,
        "invalid": 1,
    }


def test_validate_connector_manifest_without_sample_is_applyable(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    document = sampleless_external_db_manifest_payload()
    document.pop("tenant_id")
    document.pop("registered_by")

    response = client.post(
        "/operations/connectors/manifests/validation",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "registered_by": "platform-connector-owner-role",
            "manifests": [document],
        },
    )

    assert response.status_code == 200
    assert response.json()["results"] == [
        {
            "connector_id": "external_db_sampleless_orders",
            "outcome": "would_register",
            "errors": [],
        }
    ]


def test_validate_connector_manifests_has_no_database_side_effects(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)

    response = client.post(
        "/operations/connectors/manifests/validation",
        json=manifest_validation_request(external_db_manifest_request()),
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["outcome"] == "would_register"
    with session_scope(session_factory) as session:
        assert session.scalar(
            select(func.count()).select_from(ConnectorManifestRecord)
        ) == 0
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_validate_connector_manifests_rejects_duplicate_connector_ids(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    request = manifest_validation_request(
        external_db_manifest_request(),
        external_db_manifest_request(),
    )

    response = client.post(
        "/operations/connectors/manifests/validation",
        json=request,
    )

    assert response.status_code == 200
    body = response.json()
    assert [result["outcome"] for result in body["results"]] == [
        "invalid",
        "invalid",
    ]
    assert body["summary"]["invalid"] == 2
    for result in body["results"]:
        assert result["connector_id"] == "external_db_shift_orders"
        assert result["errors"] == [
            {
                "field_path": "manifest.connector_id",
                "message": (
                    "Duplicate connector_id within this manifest validation request."
                ),
                "reason": "duplicate_connector_id",
            }
        ]


def test_validate_connector_manifests_rejects_over_batch_limit(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    document = manifest_validation_document(external_db_manifest_request())
    request = {
        "tenant_id": "tenant_demo_manufacturing",
        "registered_by": "platform-connector-owner-role",
        "manifests": [
            {
                **document,
                "manifest": {
                    **document["manifest"],
                    "connector_id": f"external_db_{index}",
                },
            }
            for index in range(MANIFEST_VALIDATION_BATCH_LIMIT + 1)
        ],
    }

    response = client.post(
        "/operations/connectors/manifests/validation",
        json=request,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "VALIDATION_FAILED",
        "message": (
            "Connector manifest validation accepts at most "
            f"{MANIFEST_VALIDATION_BATCH_LIMIT} manifests per request."
        ),
        "reason": "manifest_validation_batch_limit_exceeded",
        "maximum": MANIFEST_VALIDATION_BATCH_LIMIT,
    }


def test_manifest_validation_applyability_promise_matches_registration_endpoint(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    existing_request = external_db_manifest_request()
    with session_scope(session_factory) as session:
        record_demo_connector_manifest(
            AxisPersistenceRepository(session),
            existing_request,
        )
    new_request_payload = existing_request.model_dump()
    new_request_payload["manifest"]["connector_id"] = "external_db_new_orders"
    new_request_payload["manifest"]["display_name"] = "New orders database mirror"
    new_request = ConnectorManifestCreateRequest.model_validate(new_request_payload)
    sampleless_request = ConnectorManifestCreateRequest.model_validate(
        sampleless_external_db_manifest_payload(
            connector_id="external_db_sampleless_applyability"
        )
    )
    registration_requests = [new_request, existing_request, sampleless_request]

    validation = client.post(
        "/operations/connectors/manifests/validation",
        json=manifest_validation_request(*registration_requests),
    )

    assert validation.status_code == 200
    results = validation.json()["results"]
    assert [result["outcome"] for result in results] == [
        "would_register",
        "would_replace",
        "would_register",
    ]

    for result, registration_request in zip(
        results,
        registration_requests,
        strict=True,
    ):
        if result["outcome"] == "would_register":
            applied = client.post(
                "/operations/connectors/manifests",
                json=registration_request.model_dump(exclude_unset=True),
            )
            assert applied.status_code == 201
        else:
            assert result["outcome"] == "would_replace"
            applied = client.put(
                f"/operations/connectors/manifests/{result['connector_id']}",
                json=manifest_replacement_payload(
                    registration_request,
                    idempotency_key="dry-run-apply-replacement",
                ),
            )
            assert applied.status_code == 200
        assert applied.json()["connector_id"] == result["connector_id"]


def test_manifest_validation_failure_matches_real_registration_reason(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    client = TestClient(app)
    registration_request = external_db_manifest_request().model_dump()
    registration_request["manifest"].pop("connector_id")
    validation_request = {
        "tenant_id": registration_request.pop("tenant_id"),
        "registered_by": registration_request.pop("registered_by"),
        "manifests": [registration_request],
    }

    validation = client.post(
        "/operations/connectors/manifests/validation",
        json=validation_request,
    )
    registration = client.post(
        "/operations/connectors/manifests",
        json={
            "tenant_id": validation_request["tenant_id"],
            "registered_by": validation_request["registered_by"],
            **registration_request,
        },
    )

    assert validation.status_code == 200
    assert validation.json()["results"][0]["outcome"] == "invalid"
    assert registration.status_code == 422
    assert validation.json()["results"][0]["errors"] == (
        registration.json()["detail"]["errors"]
    )
    assert validation.json()["results"][0]["errors"][0]["reason"] == (
        registration.json()["detail"]["reason"]
    )


def test_transition_connector_manifest_lifecycle_marks_active_preview(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        record_demo_connector_manifest(repository, external_db_manifest_request())
        transitioned = transition_demo_connector_manifest_lifecycle(
            repository,
            "external_db_shift_orders",
            ConnectorManifestLifecycleRequest(
                tenant_id="tenant_demo_manufacturing",
                transitioned_by="platform-connector-owner-role",
                target_status="active_preview",
                actor_scopes=["connectors:manifest:lifecycle"],
                transition_reason="Ready for governed preview configuration.",
                evidence_refs=["approval:connector-manifest-preview-activation"],
            ),
        )

    assert transitioned.status == "active_preview"
    assert transitioned.audit_event_type == "connector.manifest.lifecycle_transitioned"
    assert transitioned.notes[-1] == "Lifecycle transition: active_preview"
    assert transitioned.manifest["connector_id"] == "external_db_shift_orders"
    assert "password" not in transitioned.model_dump_json().lower()


def test_transition_connector_manifest_lifecycle_enables_active_live_with_gate(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        record_demo_connector_manifest(
            repository,
            live_capable_external_db_manifest_request(),
        )
        transition_demo_connector_manifest_lifecycle(
            repository,
            "external_db_shift_orders",
            ConnectorManifestLifecycleRequest(
                tenant_id="tenant_demo_manufacturing",
                transitioned_by="platform-connector-owner-role",
                target_status="active_preview",
                actor_scopes=["connectors:manifest:lifecycle"],
                transition_reason="Ready for governed preview configuration.",
                evidence_refs=["approval:connector-manifest-preview-activation"],
            ),
        )

        transitioned = transition_demo_connector_manifest_lifecycle(
            repository,
            "external_db_shift_orders",
            ConnectorManifestLifecycleRequest(
                tenant_id="tenant_demo_manufacturing",
                transitioned_by="platform-connector-owner-role",
                target_status="active_live",
                actor_scopes=[
                    "connectors:manifest:lifecycle",
                    "connectors:manifest:enable_live",
                ],
                transition_reason="Governance approval for allowlisted live query preflight.",
                evidence_refs=[
                    "approval:connector-live-enable",
                    "policy:egress-allowlist-reviewed",
                    "credential:external-db-readonly-lease-policy",
                ],
            ),
        )
        audit_event = repository.get_audit_event(
            "tenant_demo_manufacturing",
            transitioned.audit_event_id,
        )

    assert transitioned.status == "active_live"
    assert transitioned.audit_event_type == "connector.manifest.live_enabled"
    assert transitioned.notes[-1] == "Lifecycle transition: active_live"
    assert transitioned.manifest["sync_modes"] == [
        "schema_preview",
        "manual_import",
        "live_query",
    ]
    assert transitioned.runtime_policy["allowed_operations"] == [
        "schema_validate",
        "metadata_preview",
        "live_query",
        "external_egress",
    ]
    assert audit_event is not None
    assert audit_event.event_type == "connector.manifest.live_enabled"
    assert audit_event.payload["required_scope"] == "connectors:manifest:enable_live"
    assert audit_event.payload["live_sync_enabled"] == "true"
    assert audit_event.payload["external_sync_started"] == "false"
    assert audit_event.payload["evidence_refs"] == [
        "approval:connector-live-enable",
        "policy:egress-allowlist-reviewed",
        "credential:external-db-readonly-lease-policy",
    ]
    assert "password" not in transitioned.model_dump_json().lower()


def test_transition_connector_manifest_lifecycle_requires_live_scope(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        record_demo_connector_manifest(
            repository,
            live_capable_external_db_manifest_request(),
        )
        transition_demo_connector_manifest_lifecycle(
            repository,
            "external_db_shift_orders",
            ConnectorManifestLifecycleRequest(
                tenant_id="tenant_demo_manufacturing",
                transitioned_by="platform-connector-owner-role",
                target_status="active_preview",
                actor_scopes=["connectors:manifest:lifecycle"],
                transition_reason="Ready for governed preview configuration.",
                evidence_refs=["approval:connector-manifest-preview-activation"],
            ),
        )

        with pytest.raises(ConnectorManifestLifecycleValidationError) as exc_info:
            transition_demo_connector_manifest_lifecycle(
                repository,
                "external_db_shift_orders",
                ConnectorManifestLifecycleRequest(
                    tenant_id="tenant_demo_manufacturing",
                    transitioned_by="platform-connector-owner-role",
                    target_status="active_live",
                    actor_scopes=["connectors:manifest:lifecycle"],
                    transition_reason="Governance approval for live query.",
                    evidence_refs=[
                        "approval:connector-live-enable",
                        "policy:egress-allowlist-reviewed",
                        "credential:external-db-readonly-lease-policy",
                    ],
                ),
            )

    assert exc_info.value.reason == "missing_manifest_live_scope"


def test_transition_connector_manifest_lifecycle_requires_lifecycle_scope_for_live(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        record_demo_connector_manifest(
            repository,
            live_capable_external_db_manifest_request(),
        )
        transition_demo_connector_manifest_lifecycle(
            repository,
            "external_db_shift_orders",
            ConnectorManifestLifecycleRequest(
                tenant_id="tenant_demo_manufacturing",
                transitioned_by="platform-connector-owner-role",
                target_status="active_preview",
                actor_scopes=["connectors:manifest:lifecycle"],
                transition_reason="Ready for governed preview configuration.",
                evidence_refs=["approval:connector-manifest-preview-activation"],
            ),
        )

        with pytest.raises(ConnectorManifestLifecycleValidationError) as exc_info:
            transition_demo_connector_manifest_lifecycle(
                repository,
                "external_db_shift_orders",
                ConnectorManifestLifecycleRequest(
                    tenant_id="tenant_demo_manufacturing",
                    transitioned_by="platform-connector-owner-role",
                    target_status="active_live",
                    actor_scopes=["connectors:manifest:enable_live"],
                    transition_reason="Governance approval for live query.",
                    evidence_refs=[
                        "approval:connector-live-enable",
                        "policy:egress-allowlist-reviewed",
                        "credential:external-db-readonly-lease-policy",
                    ],
                ),
            )

    assert exc_info.value.reason == "missing_manifest_lifecycle_scope"


def test_transition_connector_manifest_lifecycle_requires_live_runtime_policy(
    session_factory: sessionmaker[Session],
) -> None:
    request_payload = live_capable_external_db_manifest_request().model_dump()
    request_payload["runtime_policy"]["blocked_operations"].append("live_query")
    request = ConnectorManifestCreateRequest.model_validate(request_payload)

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        record_demo_connector_manifest(repository, request)
        transition_demo_connector_manifest_lifecycle(
            repository,
            "external_db_shift_orders",
            ConnectorManifestLifecycleRequest(
                tenant_id="tenant_demo_manufacturing",
                transitioned_by="platform-connector-owner-role",
                target_status="active_preview",
                actor_scopes=["connectors:manifest:lifecycle"],
                transition_reason="Ready for governed preview configuration.",
                evidence_refs=["approval:connector-manifest-preview-activation"],
            ),
        )

        with pytest.raises(ConnectorManifestLifecycleValidationError) as exc_info:
            transition_demo_connector_manifest_lifecycle(
                repository,
                "external_db_shift_orders",
                ConnectorManifestLifecycleRequest(
                    tenant_id="tenant_demo_manufacturing",
                    transitioned_by="platform-connector-owner-role",
                    target_status="active_live",
                    actor_scopes=[
                        "connectors:manifest:lifecycle",
                        "connectors:manifest:enable_live",
                    ],
                    transition_reason="Governance approval for live query.",
                    evidence_refs=[
                        "approval:connector-live-enable",
                        "policy:egress-allowlist-reviewed",
                        "credential:external-db-readonly-lease-policy",
                    ],
                ),
            )

    assert exc_info.value.reason == "manifest_runtime_policy_blocks_live_query"


def test_transition_connector_manifest_endpoint_requires_live_evidence(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        record_demo_connector_manifest(
            repository,
            live_capable_external_db_manifest_request(),
        )
        transition_demo_connector_manifest_lifecycle(
            repository,
            "external_db_shift_orders",
            ConnectorManifestLifecycleRequest(
                tenant_id="tenant_demo_manufacturing",
                transitioned_by="platform-connector-owner-role",
                target_status="active_preview",
                actor_scopes=["connectors:manifest:lifecycle"],
                transition_reason="Ready for governed preview configuration.",
                evidence_refs=["approval:connector-manifest-preview-activation"],
            ),
        )
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/manifests/external_db_shift_orders/lifecycle",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "transitioned_by": "platform-connector-owner-role",
            "target_status": "active_live",
            "actor_scopes": [
                "connectors:manifest:lifecycle",
                "connectors:manifest:enable_live",
            ],
            "transition_reason": "Governance approval for live query.",
            "evidence_refs": ["approval:connector-live-enable"],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "manifest_live_evidence_incomplete"


def test_transition_connector_manifest_lifecycle_rejects_live_enabled_target(
    session_factory: sessionmaker[Session],
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        record_demo_connector_manifest(repository, external_db_manifest_request())
        with pytest.raises(ConnectorManifestLifecycleValidationError) as exc_info:
            transition_demo_connector_manifest_lifecycle(
                repository,
                "external_db_shift_orders",
                ConnectorManifestLifecycleRequest(
                    tenant_id="tenant_demo_manufacturing",
                    transitioned_by="platform-connector-owner-role",
                    target_status="live_enabled",
                    actor_scopes=["connectors:manifest:lifecycle"],
                    transition_reason="Enable live sync.",
                    evidence_refs=["approval:live-sync"],
                ),
            )

    assert exc_info.value.reason == "unsupported_manifest_lifecycle_target"


def test_transition_connector_manifest_endpoint_updates_manifest_with_audit(
    session_factory: sessionmaker[Session],
) -> None:
    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = session_factory
    with session_scope(session_factory) as session:
        record_demo_connector_manifest(
            AxisPersistenceRepository(session),
            external_db_manifest_request(),
        )
    client = TestClient(app)

    response = client.post(
        "/demo/manufacturing/connectors/manifests/external_db_shift_orders/lifecycle",
        json={
            "tenant_id": "tenant_demo_manufacturing",
            "transitioned_by": "platform-connector-owner-role",
            "target_status": "active_preview",
            "actor_scopes": ["connectors:manifest:lifecycle"],
            "transition_reason": "Ready for governed preview configuration.",
            "evidence_refs": ["approval:connector-manifest-preview-activation"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active_preview"
    assert body["audit_event_type"] == "connector.manifest.lifecycle_transitioned"
    assert body["notes"][-1] == "Lifecycle transition: active_preview"


def test_openapi_exposes_connector_manifest_endpoints() -> None:
    client = TestClient(create_app())
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/demo/manufacturing/connectors/manifests" in paths
    assert "get" in paths["/demo/manufacturing/connectors/manifests"]
    assert "post" in paths["/demo/manufacturing/connectors/manifests"]
    assert "/operations/connectors/manifests/validation" in paths
    assert "post" in paths["/operations/connectors/manifests/validation"]
    assert (
        "/demo/manufacturing/connectors/manifests/{connector_id}/lifecycle" in paths
    )
    assert (
        "post"
        in paths["/demo/manufacturing/connectors/manifests/{connector_id}/lifecycle"]
    )
    schemas = response.json()["components"]["schemas"]
    for schema_name in (
        "ConnectorManifestCreateRequest",
        "ConnectorManifestReplaceRequest",
    ):
        schema = schemas[schema_name]
        assert "preview_sample" not in schema.get("required", [])
        assert {entry.get("$ref") for entry in schema["properties"]["preview_sample"]["anyOf"]} == {
            "#/components/schemas/ConnectorPreviewSample",
            None,
        }
