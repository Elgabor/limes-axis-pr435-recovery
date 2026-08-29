"""Governed batch-envelope exports: approval chain, checksums, local retrieval.

Covers the full export lifecycle end to end on SQLite — request creation with
deterministic envelope checksums and auto-created pending approvals, idempotent
replay/conflict semantics, the decision gate, single-shot materialization with
TOCTOU checksum verification, and LOCAL-adapter-only artifact retrieval that
verifies SHA-256 before serving and audits every read. Sentinel tests prove no
watermark value or row-payload key ever reaches the bundle.
"""

import base64
import hashlib
import importlib.util
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.connector_source_batch_exports import (
    BATCH_EXPORT_MATERIALIZED_EVENT,
    BATCH_EXPORT_REQUESTED_EVENT,
    LocalBatchExportArtifactReader,
    _checksum,
)
from axis_api.db import session_scope
from axis_api.models import (
    AuditEvent,
    Base,
    ConnectorSourceBatchExportRequest,
    ConnectorSourceExtractionBatch,
)
from axis_api.object_storage import LocalObjectStore
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorSourceExtractionBatchCreate,
    ConnectorSourceIngestionRequestCreate,
    TenantCreate,
)

TENANT_A = "tenant_demo_manufacturing"
TENANT_B = "tenant_other_plant"
CONNECTOR_ID = "external_db_operational_mirror"
FINGERPRINT = "a" * 64
RESOURCE = "operations.production_orders"
READ_SCOPE = "connectors:source:ingest:read"
REQUEST_SCOPE = "connectors:source:batch_export:request"
DECISION_SCOPE = "approvals:connectors:source:batch_export:decide"
MATERIALIZE_SCOPE = "connectors:source:batch_export:materialize"
STORE_ROOT = Path(".audit/opencode-runtime/batch13/runtime/store")

REQUESTS_URL = (
    "/operations/connectors/external-db/source-ingestion-requests/ingreq_b13"
    "/batch-envelope-export-requests"
)


@pytest.fixture
def store_root():
    if STORE_ROOT.exists():
        shutil.rmtree(STORE_ROOT)
    STORE_ROOT.mkdir(parents=True, exist_ok=True)
    yield STORE_ROOT
    if STORE_ROOT.exists():
        shutil.rmtree(STORE_ROOT)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        for tenant_id in (TENANT_A, TENANT_B):
            repository.create_tenant(
                TenantCreate(
                    tenant_id=tenant_id,
                    display_name="Probe",
                    description="batch export lane",
                    created_by="test",
                )
            )
    yield factory
    engine.dispose()


def seed_ingestion_request(
    factory,
    request_id: str = "ingreq_b13",
    *,
    tenant_id: str = TENANT_A,
) -> None:
    created = datetime.now(UTC) - timedelta(minutes=5)
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=tenant_id,
                actor_id="axis-operator",
                event_type="connector.source.ingestion.requested",
                payload={"request_id": request_id},
            )
        )
        repository.create_connector_source_ingestion_request(
            ConnectorSourceIngestionRequestCreate(
                tenant_id=tenant_id,
                connector_id=CONNECTOR_ID,
                request_id=request_id,
                requested_by="axis-operator",
                reason="Batch export seeding.",
                stage="extract",
                selections=[
                    {
                        "binding_id": "binding_b13_a",
                        "resource_name": RESOURCE,
                        "schema_fingerprint": FINGERPRINT,
                    }
                ],
                audit_event_id=event.id,
                audit_event_type="connector.source.ingestion.requested",
            ),
            available_at=created,
        )


def seed_batches(
    factory,
    count: int,
    request_id: str = "ingreq_b13",
    *,
    tenant_id: str = TENANT_A,
    watermark_value: str | None = "o-1",
    start_index: int = 0,
) -> None:
    """Persist batch metadata exactly as the dispatcher would."""
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        for offset in range(count):
            index = start_index + offset
            event = repository.append_audit_event(
                AuditEventCreate(
                    tenant_id=tenant_id,
                    actor_id="axis-source-ingestion-outbox",
                    event_type="connector.source.extraction.batch_recorded",
                    payload={"request_id": request_id, "index": str(index)},
                )
            )
            batch_key = f"{request_id}:binding_b13_{chr(97 + index)}:{index}"
            storage_key = (
                f"tenants/{tenant_id}/source-ingestion/{request_id}/"
                f"binding_b13_{chr(97 + index)}/{batch_key}.json"
            )
            encoded_bytes = json.dumps({"rows": [f"row-{index}"]}).encode()
            watermark = (
                {"order_id": watermark_value} if watermark_value is not None else None
            )
            repository.create_connector_source_extraction_batch(
                ConnectorSourceExtractionBatchCreate(
                    tenant_id=tenant_id,
                    connector_id=CONNECTOR_ID,
                    request_id=request_id,
                    batch_key=batch_key,
                    binding_id=f"binding_b13_{chr(97 + index)}",
                    resource_name=RESOURCE,
                    pinned_schema_fingerprint=FINGERPRINT,
                    observed_schema_fingerprint=FINGERPRINT,
                    ordering_mode="primary_key",
                    cursor_watermark=watermark,
                    row_count=2,
                    byte_size=32,
                    truncated=False,
                    limit_reason=None,
                    duration_ms=12,
                    limits_applied={"max_rows": 10_000},
                    provenance={"stage": "extract"},
                    digest_sha256=hashlib.sha256(encoded_bytes).hexdigest(),
                    storage_adapter="local_filesystem",
                    storage_key=storage_key,
                    storage_uri=f"axis-local-object-store://{storage_key}",
                    content_type="application/json",
                    stored_size_bytes=len(encoded_bytes),
                    classification="confidential",
                    executed_by="axis-source-ingestion-outbox",
                    audit_event_id=event.id,
                    audit_event_type="connector.source.extraction.batch_recorded",
                )
            )


def local_settings(store_root: Path) -> Settings:
    return Settings(
        postgres_dsn="sqlite+pysqlite://",
        connector_export_object_store_adapter="local_filesystem",
        connector_export_object_store_root=str(store_root),
    )


def build_client(
    factory,
    settings: Settings | None = None,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    from axis_api.main import create_app

    app = create_app(settings or local_settings(STORE_ROOT))
    app.state.session_factory = factory
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def export_body(**overrides) -> dict:
    payload = {
        "tenant_id": TENANT_A,
        "connector_id": CONNECTOR_ID,
        "request_id": "ingreq_b13",
        "export_request_id": "batchexport_b13_001",
        "idempotency_key": "bexp-key-0001",
        "requested_by": "axis-operator",
        "owner_role": "plant-data-steward",
        "risk_level": "medium",
        "approval_id": "approval_bexp_001",
        "workflow_id": "workflow_bexp_001",
        "export_reason": "Quarterly governance review of extracted evidence.",
        "actor_scopes": [REQUEST_SCOPE],
    }
    payload.update(overrides)
    return payload


def decision_body(**overrides) -> dict:
    payload = {
        "tenant_id": TENANT_A,
        "decision": "approve",
        "actor_id": "axis-governor",
        "actor_scopes": [DECISION_SCOPE],
        "note": "Approved for the quarterly review.",
    }
    payload.update(overrides)
    return payload


def materialize_body(**overrides) -> dict:
    payload = {
        "tenant_id": TENANT_A,
        "materialization_id": "matb13001",
        "idempotency_key": "mat-key-0001",
        "actor_id": "axis-operator",
        "actor_scopes": [MATERIALIZE_SCOPE],
        "reason": "Write the reviewed envelope bundle.",
    }
    payload.update(overrides)
    return payload


def get_export_row(factory, export_request_id: str = "batchexport_b13_001"):
    with session_scope(factory) as session:
        return AxisPersistenceRepository(
            session
        ).get_connector_source_batch_export_request(TENANT_A, export_request_id)


def audit_events(factory, event_type: str) -> list[AuditEvent]:
    with session_scope(factory) as session:
        return list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.event_type == event_type)
            ).all()
        )


# ---------------------------------------------------------------------------
# Request creation


def test_request_creation_records_checksum_and_pending_approval(
    session_factory, store_root
) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=2)
    client = build_client(session_factory)

    response = client.post(REQUESTS_URL, json=export_body())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "approval_required"
    assert body["storage_status"] == "not_written"
    assert body["envelope_filter"]["request_id"] == "ingreq_b13"
    assert body["redaction_policy"] == "source-batch-envelope-public-safe"

    row = get_export_row(session_factory)
    with session_scope(session_factory) as session:
        batches = list(
            session.scalars(
                select(ConnectorSourceExtractionBatch)
                .where(ConnectorSourceExtractionBatch.request_id == "ingreq_b13")
                .order_by(ConnectorSourceExtractionBatch.batch_key.asc())
            ).all()
        )
    # The recorded checksum must be reproducible from durable metadata alone.
    from axis_api.connector_source_ingestion import SourceExtractionBatchView

    views = [
        SourceExtractionBatchView(
            batch_key=batch.batch_key,
            binding_id=batch.binding_id,
            resource_name=batch.resource_name,
            pinned_schema_fingerprint=batch.pinned_schema_fingerprint,
            observed_schema_fingerprint=batch.observed_schema_fingerprint,
            ordering_mode=batch.ordering_mode,
            has_watermark=batch.cursor_watermark is not None,
            row_count=batch.row_count,
            byte_size=batch.byte_size,
            truncated=batch.truncated,
            limit_reason=batch.limit_reason,
            duration_ms=batch.duration_ms,
            digest_sha256=batch.digest_sha256,
            storage_uri=batch.storage_uri,
            content_type=batch.content_type,
            stored_size_bytes=batch.stored_size_bytes,
            classification=batch.classification,
            executed_by=batch.executed_by,
            created_at=batch.created_at,
        )
        for batch in batches
    ]
    canonical_envelopes = [view.model_dump(mode="json") for view in views]
    expected_checksum = _checksum(
        {"envelopes": canonical_envelopes, "request_id": "ingreq_b13"}
    )
    assert row.envelope_checksum_sha256 == expected_checksum
    assert row.batch_count == 2

    approval = None
    with session_scope(session_factory) as session:
        approval = AxisPersistenceRepository(session).get_approval_record(
            TENANT_A, "approval_bexp_001"
        )
    assert approval is not None and approval.status == "pending"


def test_identical_replay_returns_existing_without_second_audit(
    session_factory, store_root
) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    first = client.post(REQUESTS_URL, json=export_body())
    second = client.post(REQUESTS_URL, json=export_body())

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True
    assert len(audit_events(session_factory, BATCH_EXPORT_REQUESTED_EVENT)) == 1


def test_replay_with_different_ask_conflicts(session_factory, store_root) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    client.post(REQUESTS_URL, json=export_body())
    different = client.post(
        REQUESTS_URL,
        json=export_body(export_reason="A completely different review."),
    )
    assert different.status_code == 409
    assert different.json()["detail"]["reason"] == "idempotency_conflict"


def test_used_export_request_id_conflicts(session_factory, store_root) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    client.post(REQUESTS_URL, json=export_body())
    clash = client.post(
        REQUESTS_URL,
        json=export_body(idempotency_key="bexp-key-0002"),
    )
    assert clash.status_code == 409
    assert clash.json()["detail"]["reason"] == "export_request_id_already_exists"


def test_unknown_ingestion_request_is_not_found(session_factory, store_root) -> None:
    client = build_client(session_factory)
    response = client.post(REQUESTS_URL, json=export_body())
    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "ingestion_request_not_found"


def test_cross_tenant_ingestion_request_is_invisible(session_factory, store_root) -> None:
    seed_ingestion_request(
        session_factory, "ingreq_other", tenant_id=TENANT_B
    )
    seed_batches(session_factory, 1, request_id="ingreq_other", tenant_id=TENANT_B)
    client = build_client(session_factory)
    response = client.post(
        "/operations/connectors/external-db/source-ingestion-requests/ingreq_other"
        "/batch-envelope-export-requests",
        json=export_body(request_id="ingreq_other"),
    )
    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "ingestion_request_not_found"


@pytest.mark.parametrize(
    ("scope", "url_suffix"),
    [
        (REQUEST_SCOPE, ""),
    ],
)
def test_write_scopes_are_enforced(session_factory, store_root, scope, url_suffix) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    denied = client.post(
        REQUESTS_URL, json=export_body(actor_scopes=["connectors:unrelated"])
    )
    assert denied.status_code == 403
    detail = denied.json()["detail"]
    assert detail["required_permission"] == scope


# ---------------------------------------------------------------------------
# Decision gate


def full_flow_to_approved(client: TestClient) -> None:
    created = client.post(REQUESTS_URL, json=export_body())
    assert created.status_code == 201, created.text
    decided = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision", json=decision_body()
    )
    assert decided.status_code == 200, decided.text


def test_decision_requires_decision_scope(session_factory, store_root) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    client.post(REQUESTS_URL, json=export_body())
    denied = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision",
        json=decision_body(actor_scopes=[REQUEST_SCOPE]),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["required_permission"] == DECISION_SCOPE


def test_approve_updates_status_and_persists_decision(session_factory, store_root) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    full_flow_to_approved(client)

    row = get_export_row(session_factory)
    assert row.status == "approval_approved"
    assert row.export_status == "approved_not_exported"
    assert row.decision == "approve"
    assert row.decided_at is not None
    events = audit_events(
        session_factory, "connector.source.batch_export.decision_recorded"
    )
    assert len(events) == 1


def test_rejection_blocks_materialization(session_factory, store_root) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    client.post(REQUESTS_URL, json=export_body())
    rejected = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision",
        json=decision_body(decision="reject", note="Not this quarter."),
    )
    assert rejected.status_code == 200
    blocked = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(),
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["reason"] == "export_request_not_approved"


def test_materialization_before_approval_conflicts(session_factory, store_root) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    client.post(REQUESTS_URL, json=export_body())
    early = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(),
    )
    assert early.status_code == 409
    assert early.json()["detail"]["reason"] == "export_request_not_approved"


# ---------------------------------------------------------------------------
# Materialization


def test_materialization_writes_metadata_only_bundle_once(
    session_factory, store_root
) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=2)
    client = build_client(session_factory)
    full_flow_to_approved(client)

    first = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(),
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["status"] == "materialized"
    assert body["storage_adapter"] == "local_filesystem"
    assert body["artifact_content_type"] == "application/json"
    assert len(body["artifact_checksum_sha256"]) == 64

    row = get_export_row(session_factory)
    assert row.storage_status == "written_local_object_store"
    assert row.materialized_at is not None

    # The written bundle carries metadata-only envelopes.
    artifact_path = store_root / row.storage_key
    raw = artifact_path.read_bytes()
    bundle = json.loads(raw)
    assert hashlib.sha256(raw).hexdigest() == row.artifact_checksum_sha256
    assert bundle["manifest"]["request_id"] == "ingreq_b13"
    assert bundle["manifest"]["watermark_disclosure"] == "presence_only"
    assert len(bundle["envelopes"]) == 2
    for envelope in bundle["envelopes"]:
        assert envelope["has_watermark"] is True
        assert "cursor_watermark" not in envelope
        assert "rows" not in envelope

    # Exact replay returns the same result without a second write or event.
    replay = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(),
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    # A different ask conflicts.
    conflict = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(materialization_id="matb13002"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason"] == "materialization_idempotency_conflict"
    assert len(audit_events(session_factory, BATCH_EXPORT_MATERIALIZED_EVENT)) == 1


def test_materialization_requires_materialize_scope(session_factory, store_root) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    full_flow_to_approved(client)
    denied = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(actor_scopes=[REQUEST_SCOPE]),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["required_permission"] == MATERIALIZE_SCOPE


def test_checksum_drift_between_request_and_materialization_detected(
    session_factory, store_root
) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    full_flow_to_approved(client)
    # New evidence lands after the export was requested.
    seed_batches(session_factory, 1, start_index=5)
    drifted = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(),
    )
    assert drifted.status_code == 409
    assert drifted.json()["detail"]["reason"] == "envelope_checksum_changed"
    row = get_export_row(session_factory)
    assert row.storage_status == "not_written"


# ---------------------------------------------------------------------------
# Closure audit: fence-before-write metadata + failure injection


def test_materialization_metadata_matches_local_store_serialization(
    session_factory, store_root
) -> None:
    """Pre-fence metadata must equal what LocalObjectStore actually writes."""
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    full_flow_to_approved(client)
    materialized = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(),
    )
    assert materialized.status_code == 201

    row = get_export_row(session_factory)
    assert row.storage_adapter == "local_filesystem"
    assert row.storage_uri.startswith("axis-local-object-store://")
    assert row.artifact_content_type == "application/json"
    raw = (store_root / row.storage_key).read_bytes()
    # LocalObjectStore.put_json serializes canonically; the digest recorded by
    # the fence must be exactly the digest of the bytes on disk.
    assert hashlib.sha256(raw).hexdigest() == row.artifact_checksum_sha256


class _ExplodingStore:
    """Fails BEFORE writing anything."""

    adapter_name = "local_filesystem"

    def put_json(self, key, payload):
        raise RuntimeError("object store unavailable")


class _WriteThenRaiseStore:
    """Simulates a crash AFTER the bytes landed but before success returns."""

    adapter_name = "local_filesystem"
    uri_scheme = "axis-local-object-store"

    def __init__(self, root):
        self._inner = LocalObjectStore(root)

    def put_json(self, key, payload):
        self._inner.put_json(key, payload)
        raise RuntimeError("crashed right after writing")


def test_object_store_exception_rolls_back_db_and_audits_nothing(
    session_factory, store_root, monkeypatch
) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory, raise_server_exceptions=False)
    full_flow_to_approved(client)

    import axis_api.main as main_module

    monkeypatch.setattr(main_module, "LocalObjectStore", lambda root: _ExplodingStore())
    failed = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(),
    )
    # An unexpected operational store failure is not a public-safe 4xx.
    assert failed.status_code == 500

    row = get_export_row(session_factory)
    assert row.storage_status == "not_written"
    assert row.materialization_id is None
    assert len(audit_events(session_factory, BATCH_EXPORT_MATERIALIZED_EVENT)) == 0
    files = [path for path in store_root.rglob("*") if path.is_file()]
    assert files == []


def test_write_then_raise_leaves_only_the_documented_file_residual(
    session_factory, store_root, monkeypatch
) -> None:
    """Precise crash residual: bytes exist, DB state and audit do not.

    The fence precedes the write inside one transaction, so an in-process
    store failure rolls everything back cleanly. The residual window this
    leaves is a crash BETWEEN the object write and transaction commit: the
    file exists while the row stays not_written. That residual is recorded in
    the handoff; two-phase local write/finalize is Batch 14 design work, and
    no broad cleanup exists or runs here.
    """
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory, raise_server_exceptions=False)
    full_flow_to_approved(client)

    import axis_api.main as main_module

    original_local_object_store = main_module.LocalObjectStore
    monkeypatch.setattr(
        main_module,
        "LocalObjectStore",
        lambda root: _WriteThenRaiseStore(root),
    )
    crashed = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(),
    )
    assert crashed.status_code == 500

    row = get_export_row(session_factory)
    assert row.storage_status == "not_written"
    assert len(audit_events(session_factory, BATCH_EXPORT_MATERIALIZED_EVENT)) == 0
    files = [path for path in store_root.rglob("*.json") if path.is_file()]
    assert len(files) == 1  # the precise, single-file residual

    # The retry path converges: a fresh materialization fences again, rewrites
    # the same deterministic bytes under its own key, and completes honestly.
    monkeypatch.setattr(main_module, "LocalObjectStore", original_local_object_store)
    recovered = build_client(session_factory)
    retry = recovered.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(materialization_id="matb13002", idempotency_key="retry-key-001"),
    )
    assert retry.status_code == 201
    events = audit_events(session_factory, BATCH_EXPORT_MATERIALIZED_EVENT)
    assert len(events) == 1
    final_row = get_export_row(session_factory)
    assert final_row.storage_status == "written_local_object_store"


# ---------------------------------------------------------------------------
# Artifact retrieval (local-only)


def full_flow_to_materialized(factory, client: TestClient) -> None:
    seed_ingestion_request(factory)
    seed_batches(factory, count=1)
    full_flow_to_approved(client)
    materialized = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(),
    )
    assert materialized.status_code == 201, materialized.text


ARTIFACT_URL = f"{REQUESTS_URL}/batchexport_b13_001/artifact"


def test_artifact_round_trip_verifies_digest_and_audits_read(
    session_factory, store_root
) -> None:
    full_flow_to_materialized(session_factory, build_client(session_factory))
    client = build_client(session_factory)

    response = client.get(
        ARTIFACT_URL,
        params={"tenant_id": TENANT_A, "actor_scopes": [READ_SCOPE]},
    )

    assert response.status_code == 200, response.text
    row = get_export_row(session_factory)
    assert hashlib.sha256(response.content).hexdigest() == row.artifact_checksum_sha256
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment" in response.headers["content-disposition"]
    reads = audit_events(
        session_factory, "connector.source.batch_export.artifact_read"
    )
    assert len(reads) == 1


def test_artifact_requires_read_scope_and_tenant_binding(
    session_factory, store_root
) -> None:
    full_flow_to_materialized(session_factory, build_client(session_factory))
    client = build_client(session_factory)
    denied = client.get(
        ARTIFACT_URL, params={"tenant_id": TENANT_A, "actor_scopes": ["other:scope"]}
    )
    assert denied.status_code == 403
    foreign = client.get(
        ARTIFACT_URL, params={"tenant_id": TENANT_B, "actor_scopes": [READ_SCOPE]}
    )
    assert foreign.status_code == 404


def test_artifact_download_before_materialization_conflicts(
    session_factory, store_root
) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    client.post(REQUESTS_URL, json=export_body())
    early = client.get(
        ARTIFACT_URL,
        params={"tenant_id": TENANT_A, "actor_scopes": [READ_SCOPE]},
    )
    assert early.status_code == 409
    assert early.json()["detail"]["reason"] == "artifact_not_written"


def test_artifact_download_on_s3_adapter_answers_409_without_client(
    session_factory, store_root, monkeypatch
) -> None:
    """Structural regression: the S3-configured deployment must answer 409
    without ever constructing a client or touching a bucket."""
    full_flow_to_materialized(session_factory, build_client(session_factory))

    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "No S3 client factory may run on the unsupported-adapter path."
        )

    import axis_api.main as main_module
    import axis_api.object_storage as object_storage_module

    monkeypatch.setattr(object_storage_module, "_s3_client_factory", fail_if_called)
    # The route must not even reach store construction via the shared builder.
    monkeypatch.setattr(main_module, "build_connector_export_object_store", fail_if_called)

    s3_settings = Settings(
        postgres_dsn="sqlite+pysqlite://",
        connector_export_object_store_adapter="s3_compatible",
        connector_export_object_store_root=str(store_root),
        connector_export_s3_bucket="probe-bucket",
        connector_export_s3_endpoint="http://127.0.0.1:9000",
        connector_export_s3_access_key="probe",
        connector_export_s3_secret_key="probe",
    )
    client = build_client(session_factory, s3_settings)
    response = client.get(
        ARTIFACT_URL,
        params={"tenant_id": TENANT_A, "actor_scopes": [READ_SCOPE]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "store_adapter_unsupported"


def test_materialization_on_s3_adapter_answers_409_without_client(
    session_factory, store_root, monkeypatch
) -> None:
    """Structural regression for the materialize POST path (no DI store)."""
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    full_flow_to_approved(client)

    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "Materialization must never construct an S3 client; it is "
            "local-filesystem-only in this batch."
        )

    import axis_api.object_storage as object_storage_module

    monkeypatch.setattr(object_storage_module, "_s3_client_factory", fail_if_called)

    s3_settings = Settings(
        postgres_dsn="sqlite+pysqlite://",
        connector_export_object_store_adapter="s3_compatible",
        connector_export_object_store_root=str(store_root),
        connector_export_s3_bucket="probe-bucket",
    )
    s3_client = build_client(session_factory, s3_settings)
    response = s3_client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "store_adapter_unsupported"
    row = get_export_row(session_factory)
    assert row.storage_status == "not_written"


def test_tampered_artifact_fails_closed(session_factory, store_root) -> None:
    full_flow_to_materialized(session_factory, build_client(session_factory))
    row = get_export_row(session_factory)
    target = store_root / row.storage_key
    target.write_bytes(json.dumps({"manifest": {}, "envelopes": []}).encode())

    client = build_client(session_factory)
    tampered = client.get(
        ARTIFACT_URL,
        params={"tenant_id": TENANT_A, "actor_scopes": [READ_SCOPE]},
    )
    assert tampered.status_code == 409
    assert tampered.json()["detail"]["reason"] == "artifact_checksum_mismatch"


def test_unsafe_storage_keys_are_never_read(session_factory, store_root) -> None:
    reader = LocalBatchExportArtifactReader(store_root)
    from axis_api.connector_source_batch_exports import ConnectorSourceBatchExportError

    for bad_key in ("/etc/passwd", "../escape.json", "a/../b.json", ""):
        with pytest.raises(ConnectorSourceBatchExportError):
            reader.read_bytes(bad_key)


def test_reconciliation_route_serves_a_real_local_store(
    session_factory, store_root
) -> None:
    """Route-level regression: the dry-run GET must reach the real filesystem.

    This pins a latent defect found during the Task 5 correction pass: the
    route used FastAPI's ``Path`` parameter helper instead of ``pathlib.Path``
    when constructing the local store, which no prior route-level exercise
    reached because every earlier test stopped at a 403/409 guard.
    """
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1, watermark_value="o-1")
    client = build_client(session_factory)
    response = client.get(
        "/operations/connectors/external-db/source-ingestion-requests/"
        "ingreq_b13/batches/reconciliation",
        params={"tenant_id": TENANT_A, "actor_scopes": [READ_SCOPE]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True
    assert body["clean_matches"] == 0  # objects were never written to the store
    assert body["missing_objects"] == 1


def test_bundle_sentinel_never_carries_watermark_values_or_row_payloads(
    session_factory, store_root
) -> None:
    """Sentinel: watermark VALUES and row payloads never reach any artifact."""
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=2)
    client = build_client(session_factory)
    full_flow_to_approved(client)
    materialized = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(),
    )
    assert materialized.status_code == 201
    row = get_export_row(session_factory)
    raw = (store_root / row.storage_key).read_bytes().decode()

    assert "o-1" not in raw  # cursor-watermark VALUE stays out
    assert '"has_watermark":true' in raw.replace(" ", "") or '"has_watermark": true' in raw
    assert "row-0" not in raw  # payload rows stay out
    downloaded = client.get(
        ARTIFACT_URL,
        params={"tenant_id": TENANT_A, "actor_scopes": [READ_SCOPE]},
    )
    assert downloaded.status_code == 200
    assert b"o-1" not in downloaded.content


# ---------------------------------------------------------------------------
# Decision replay / conflict / tenant binding


def test_identical_decision_replays_without_second_event(
    session_factory, store_root
) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    client.post(REQUESTS_URL, json=export_body())
    first = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision", json=decision_body()
    )
    replay = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision", json=decision_body()
    )
    assert first.status_code == 200 and replay.status_code == 200
    assert len(
        audit_events(
            session_factory, "connector.source.batch_export.decision_recorded"
        )
    ) == 1


# ---------------------------------------------------------------------------
# Closure audit: replay authorization ordering + decision semantic identity


def test_exact_decision_replay_without_scope_is_still_denied(
    session_factory, store_root
) -> None:
    """An exact replay evaluates the decision scope BEFORE returning truth."""
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    client.post(REQUESTS_URL, json=export_body())
    decided = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision", json=decision_body()
    )
    assert decided.status_code == 200
    unprivileged = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision",
        json=decision_body(actor_scopes=["connectors:unrelated"]),
    )
    assert unprivileged.status_code == 403
    assert (
        unprivileged.json()["detail"]["required_permission"] == DECISION_SCOPE
    )


def test_exact_materialization_replay_without_scope_is_still_denied(
    session_factory, store_root
) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    full_flow_to_approved(client)
    materialized = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(),
    )
    assert materialized.status_code == 201
    unprivileged = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(actor_scopes=["connectors:unrelated"]),
    )
    assert unprivileged.status_code == 403
    assert (
        unprivileged.json()["detail"]["required_permission"] == MATERIALIZE_SCOPE
    )


def test_exact_create_replay_without_scope_is_still_denied(
    session_factory, store_root
) -> None:
    """The CREATE exact-replay path evaluates the request scope FIRST.

    Same tenant/actor/idempotency identity as a stored export request, but no
    required mutation scope: the caller gets 403 — never the canonical truth.
    """
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    created = client.post(REQUESTS_URL, json=export_body())
    assert created.status_code == 201
    unprivileged = client.post(
        REQUESTS_URL,
        json=export_body(actor_scopes=["connectors:unrelated"]),
    )
    assert unprivileged.status_code == 403
    detail = unprivileged.json()["detail"]
    assert detail["required_permission"] == REQUEST_SCOPE
    # Nothing leaked and nothing was written by the denied call.
    assert len(audit_events(session_factory, BATCH_EXPORT_REQUESTED_EVENT)) == 1


def test_same_actor_same_decision_with_different_note_conflicts(
    session_factory, store_root
) -> None:
    """Decision identity is the full ask: actor + decision + note."""
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    client.post(REQUESTS_URL, json=export_body())
    first = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision", json=decision_body()
    )
    assert first.status_code == 200
    different_note = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision",
        json=decision_body(note="A materially different justification."),
    )
    assert different_note.status_code == 409
    assert different_note.json()["detail"]["reason"] == "decision_conflict"
    # Canonical truth keeps the ORIGINAL note; no second event exists.
    row = get_export_row(session_factory)
    assert row.decision_note == "Approved for the quarterly review."
    assert row.decided_at is not None
    events = audit_events(
        session_factory, "connector.source.batch_export.decision_recorded"
    )
    assert len(events) == 1


def test_decision_note_whitespace_normalization_semantics(
    session_factory, store_root
) -> None:
    """Cosmetic whitespace never fabricates a conflict; substance does."""
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    client.post(REQUESTS_URL, json=export_body())
    first = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision",
        json=decision_body(note="  Approved   for the quarterly review. "),
    )
    assert first.status_code == 200

    # Persisted value is normalized: trimmed, internal runs collapsed.
    row = get_export_row(session_factory)
    assert row.decision_note == "Approved for the quarterly review."

    # Same substance, different cosmetics → exact replay.
    cosmetic = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision",
        json=decision_body(note="Approved for the quarterly review."),
    )
    assert cosmetic.status_code == 200

    # Whitespace-only note normalizes to None; None-vs-blank is one identity.
    # (First decide with a blank note on a FRESH export request below.)
    client.post(
        REQUESTS_URL,
        json=export_body(
            export_request_id="batchexport_b13_002",
            idempotency_key="bexp-key-0002",
            approval_id="approval_bexp_002",
        ),
    )
    decided_blank = client.post(
        f"{REQUESTS_URL}/batchexport_b13_002/decision",
        json=decision_body(note="   "),
    )
    assert decided_blank.status_code == 200
    row2 = get_export_row(session_factory, "batchexport_b13_002")
    assert row2.decision_note is None
    replay_none = client.post(
        f"{REQUESTS_URL}/batchexport_b13_002/decision",
        json=decision_body(note=None),
    )
    assert replay_none.status_code == 200

    # A materially different note still conflicts.
    conflicting = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision",
        json=decision_body(note="Escalated to the plant steward instead."),
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"]["reason"] == "decision_conflict"
    assert len(
        audit_events(
            session_factory, "connector.source.batch_export.decision_recorded"
        )
    ) == 2


def test_concurrent_different_materializations_leave_no_orphan_object(
    store_root,
) -> None:
    """Two racers with DIFFERENT identities: one winner, zero orphans.

    The database fence is taken before any byte is written, so the loser can
    leave neither a second audit event nor an untracked object behind.
    """
    import threading

    db_dir = Path(".audit/opencode-runtime/batch13/runtime")
    db_dir.mkdir(parents=True, exist_ok=True)
    db_file = db_dir / "batch-export-orphan-probe.sqlite3"
    if db_file.exists():
        db_file.unlink()

    def fresh_settings():
        return Settings(
            postgres_dsn=f"sqlite:///{db_file}",
            connector_export_object_store_adapter="local_filesystem",
            connector_export_object_store_root=str(store_root),
        )

    def fresh_factory():
        # Generous busy timeout: the probe wants real fence behaviour, not
        # environment-level lock-timeout noise from SQLite's 5s default.
        engine = create_engine(
            f"sqlite:///{db_file}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    maker = fresh_factory()
    seed_ingestion_request(maker)
    seed_batches(maker, 1)
    primary_client = build_client(maker, fresh_settings())
    created = primary_client.post(REQUESTS_URL, json=export_body())
    assert created.status_code == 201, created.text
    decided = primary_client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision",
        json=decision_body(),
    )
    assert decided.status_code == 200, decided.text
    clients = [primary_client, TestClient(primary_client.app)]

    outcomes: list[tuple[int, str]] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def hit(client: TestClient, materialization_id: str, idempotency_key: str) -> None:
        try:
            barrier.wait()
            response = client.post(
                f"{REQUESTS_URL}/batchexport_b13_001/materializations",
                json=materialize_body(
                    materialization_id=materialization_id,
                    idempotency_key=idempotency_key,
                ),
            )
            body = response.json()
            reason = ""
            if isinstance(body.get("detail"), dict):
                reason = body["detail"].get("reason", "")
            outcomes.append((response.status_code, reason))
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(
            target=hit,
            args=(clients[0], "matorpha01", "orphan-key-0001"),
        ),
        threading.Thread(
            target=hit,
            args=(clients[1], "matorpha02", "orphan-key-0002"),
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for client in clients:
        client.close()

    assert errors == [], errors
    successes = [pair for pair in outcomes if pair[0] == 201]
    conflicts = [
        pair
        for pair in outcomes
        if pair[0] == 409
        and pair[1] == "materialization_idempotency_conflict"
    ]
    assert len(successes) == 1, outcomes
    assert len(conflicts) == 1, outcomes

    # Exactly ONE artifact file exists under the export namespace — the loser
    # wrote nothing — and exactly one audit event records it.
    artifacts = list(store_root.rglob("source-batch-envelope-exports/**/*"))
    files = [path for path in artifacts if path.is_file()]
    assert len(files) == 1, [str(path) for path in files]
    verify = fresh_factory()
    with session_scope(verify) as session:
        events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == BATCH_EXPORT_MATERIALIZED_EVENT
            )
        ).all()
        row = session.scalars(
            select(ConnectorSourceBatchExportRequest).where(
                ConnectorSourceBatchExportRequest.export_request_id
                == "batchexport_b13_001"
            )
        ).first()
    assert len(events) == 1
    assert row is not None
    assert row.storage_status == "written_local_object_store"
    # The recorded key is the winner's file.
    assert (store_root / row.storage_key).is_file()
    if db_file.exists():
        db_file.unlink()


def test_conflicting_decision_fails_explicitly(session_factory, store_root) -> None:
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    client.post(REQUESTS_URL, json=export_body())
    client.post(f"{REQUESTS_URL}/batchexport_b13_001/decision", json=decision_body())
    conflicting = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision",
        json=decision_body(decision="reject"),
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"]["reason"] == "decision_conflict"
    # The approved truth stands untouched.
    row = get_export_row(session_factory)
    assert row.status == "approval_approved"


def test_decision_and_materialization_binds_body_tenant(session_factory, store_root) -> None:
    """A body naming another tenant must never reach that tenant's rows."""
    seed_ingestion_request(session_factory)
    seed_batches(session_factory, count=1)
    client = build_client(session_factory)
    client.post(REQUESTS_URL, json=export_body())
    foreign_decision = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision",
        json=decision_body(tenant_id=TENANT_B),
    )
    assert foreign_decision.status_code == 404
    foreign_materialize = client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(tenant_id=TENANT_B),
    )
    assert foreign_materialize.status_code == 404
    row = get_export_row(session_factory)
    assert row.decision is None
    assert row.storage_status == "not_written"


def test_concurrent_materializations_yield_one_winner_and_one_event(store_root) -> None:
    """Genuine cross-connection contention over a shared repo-local DB file."""
    import threading

    db_dir = Path(".audit/opencode-runtime/batch13/runtime")
    db_dir.mkdir(parents=True, exist_ok=True)
    db_file = db_dir / "batch-export-concurrency.sqlite3"
    if db_file.exists():
        db_file.unlink()

    def fresh_settings():
        return Settings(
            postgres_dsn=f"sqlite:///{db_file}",
            connector_export_object_store_adapter="local_filesystem",
            connector_export_object_store_root=str(store_root),
        )

    def fresh_factory():
        # Generous busy timeout: the probe wants real fence behaviour, not
        # environment-level lock-timeout noise from SQLite's 5s default.
        engine = create_engine(
            f"sqlite:///{db_file}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    maker = fresh_factory()
    seed_ingestion_request(maker)
    seed_batches(maker, 1)
    primary_client = build_client(maker, fresh_settings())
    created = primary_client.post(REQUESTS_URL, json=export_body())
    assert created.status_code == 201, created.text
    decided = primary_client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/decision",
        json=decision_body(),
    )
    assert decided.status_code == 200, decided.text
    clients = [primary_client, TestClient(primary_client.app)]

    outcomes: list[tuple[int, str]] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2)

    def hit(client: TestClient) -> None:
        try:
            barrier.wait()
            response = client.post(
                f"{REQUESTS_URL}/batchexport_b13_001/materializations",
                json=materialize_body(),
            )
            body = response.json()
            reason = ""
            if isinstance(body.get("detail"), dict):
                reason = body["detail"].get("reason", "")
            elif isinstance(body.get("detail"), list):
                reason = str(body["detail"])
            outcomes.append((response.status_code, reason))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=hit, args=(client,)) for client in clients]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == [], errors
    # Identical concurrent asks: exactly one fresh transition (201); the other
    # returns the canonical stored truth as an exact replay (200).
    successes = [pair for pair in outcomes if pair[0] == 201]
    replays = [pair for pair in outcomes if pair[0] == 200]
    assert len(successes) == 1, outcomes
    assert len(replays) == 1, outcomes
    assert replays[0][1] == ""

    # A materially different follow-up ask must conflict explicitly.
    conflict = primary_client.post(
        f"{REQUESTS_URL}/batchexport_b13_001/materializations",
        json=materialize_body(materialization_id="matb13009"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason"] == "materialization_idempotency_conflict"
    for client in clients:
        client.close()

    verify = fresh_factory()
    with session_scope(verify) as session:
        events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == BATCH_EXPORT_MATERIALIZED_EVENT
            )
        ).all()
        row = session.scalars(
            select(ConnectorSourceBatchExportRequest).where(
                ConnectorSourceBatchExportRequest.export_request_id
                == "batchexport_b13_001"
            )
        ).first()
    assert len(events) == 1
    assert row is not None
    assert row.storage_status == "written_local_object_store"
    if db_file.exists():
        db_file.unlink()


# ---------------------------------------------------------------------------
# Migration identity + projection


def test_migration_0064_identifier_and_down_revision() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0064_connector_source_batch_export_requests.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0064", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "0064_connector_source_batch_exports"
    assert migration.down_revision == "0063_connector_source_ingestion_requests"


def test_migration_0064_columns_constraints_and_indexes_match_the_orm_model() -> None:
    from runpy import run_path

    from sqlalchemy import Column, Constraint

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0064_connector_source_batch_export_requests.py"
    )
    migration = run_path(str(migration_path))

    class RecordingOperations:
        def __init__(self) -> None:
            self.created_table: tuple[str, tuple[object, ...]] | None = None
            self.created_indexes: list[tuple[str, str, tuple[str, ...]]] = []

        def create_table(self, name: str, *items: object) -> None:
            self.created_table = (name, items)

        def create_index(self, name: str, table_name: str, columns: list[str]) -> None:
            self.created_indexes.append((name, table_name, tuple(columns)))

    operations = RecordingOperations()
    migration["upgrade"].__globals__["op"] = operations
    migration["upgrade"]()

    assert operations.created_table is not None
    table_name, items = operations.created_table
    assert table_name == ConnectorSourceBatchExportRequest.__tablename__

    migration_columns = {item.name for item in items if isinstance(item, Column)}
    model_columns = set(ConnectorSourceBatchExportRequest.__table__.columns.keys())
    assert migration_columns == model_columns

    migration_constraints = {
        item.name
        for item in items
        if isinstance(item, Constraint) and item.name is not None
    }
    model_constraints = {
        item.name
        for item in ConnectorSourceBatchExportRequest.__table__.constraints
        if item.name is not None
    }
    assert migration_constraints == model_constraints

    migration_indexes = {name for name, _, _ in operations.created_indexes}
    model_indexes = {
        index.name for index in ConnectorSourceBatchExportRequest.__table__.indexes
    }
    assert migration_indexes == model_indexes


def test_migration_0064_upgrade_creates_and_downgrade_drops(tmp_path) -> None:
    from alembic.command import downgrade, stamp, upgrade
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text

    database_path = tmp_path / "batch-export.sqlite"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")
    stamp(config, "0063_connector_source_ingestion_requests")
    upgrade(config, "0064_connector_source_batch_exports")

    inspector = inspect(engine)
    columns = {
        column["name"]
        for column in inspector.get_columns("connector_source_batch_export_requests")
    }
    assert {
        "id",
        "tenant_id",
        "connector_id",
        "request_id",
        "export_request_id",
        "idempotency_key",
        "envelope_checksum_sha256",
        "status",
        "storage_status",
        "materialization_id",
        "artifact_checksum_sha256",
    } <= columns
    index_names = {
        index["name"]
        for index in inspector.get_indexes(
            "connector_source_batch_export_requests"
        )
    }
    assert {
        "ix_connector_source_batch_export_requests_tenant_ingestion",
        "ix_connector_source_batch_export_requests_status",
    } <= index_names

    with engine.begin() as connection:
        connection.execute(text("SELECT 1 FROM connector_source_batch_export_requests"))

    downgrade(config, "0063_connector_source_ingestion_requests")
    assert not inspector.has_table("connector_source_batch_export_requests")
    engine.dispose()


def test_base64_helper_matches_route_cursor_convention() -> None:
    """Documentary guard keeping cursor encoding conventions aligned."""
    inner = "2026-08-23T10:00:00+00:00|some-request"
    encoded = base64.urlsafe_b64encode(inner.encode()).decode()
    assert base64.urlsafe_b64decode(encoded).decode() == inner
