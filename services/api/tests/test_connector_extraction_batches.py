"""Batch 11: extraction-batch read model, reconciliation, recovery contracts.

Covers the operator read surface (metadata-only, paged, filtered, scoped),
the read-only store-vs-DB reconciliation classifications, and the crash-
boundary guarantees that make retries converge on deterministic keys without
duplicating audit or payload state. Object-store roots live under the repo's
own .audit runtime directory — never external temp paths.
"""

import asyncio
import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.connector_source_extraction import SourceExtractionOutcome
from axis_api.connector_source_extraction_reconciliation import (
    LocalReconcilableObjectStore,
    reconcile_request_batches,
)
from axis_api.connector_source_ingestion import (
    INGESTION_REQUESTED_EVENT,
    SOURCE_INGESTION_SCOPE,
    ObservationFreshnessIngestionRuntime,
    SourceIngestionOutboxDispatcher,
)
from axis_api.db import session_scope
from axis_api.models import (
    AuditEvent,
    Base,
    ConnectorSourceBinding,
    ConnectorSourceExtractionBatch,
    ConnectorSourceIngestionRequest,
)
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorCredentialLeaseCreate,
    ConnectorEgressPolicyCreate,
    ConnectorSourceIngestionRequestCreate,
    DataResourceObservationCreate,
    TenantCreate,
)

TENANT_A = "tenant_demo_manufacturing"
TENANT_B = "tenant_other_plant"
CONNECTOR_ID = "external_db_operational_mirror"
PROFILE_ID = "profile_postgres_discovery_readonly"
FINGERPRINT = "a" * 64
RESOURCE = "operations.production_orders"
LEASE_ID = "lease_b11_001"
POLICY_ID = "egress_policy_b11_001"
READ_SCOPE = "connectors:source:ingest:read"
STORE_ROOT = Path(".audit/opencode-runtime/batch11/runtime/store")


def both_gates() -> Settings:
    return Settings(
        AXIS_SOURCE_INGESTION_DISPATCH_ENABLED=True,
        AXIS_SOURCE_INGESTION_EXTRACTION_ENABLED=True,
        external_db_live_query_dsn="postgresql://axis:axis@localhost:5432/axis",
        connector_export_object_store_adapter="local_filesystem",
        connector_export_object_store_root=str(STORE_ROOT),
    )


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
        repository.create_tenant(
            TenantCreate(tenant_id=TENANT_A, display_name="R", description="d", created_by="t")
        )
        now = datetime.now(UTC)
        repository.create_connector_credential_lease(
            ConnectorCredentialLeaseCreate(
                tenant_id=TENANT_A, connector_id=CONNECTOR_ID, handle_id="h",
                lease_id=LEASE_ID, status="active", requested_by="a", lease_purpose="p",
                secret_provider="env", secret_ref="S", vault_kms_policy={},
                permission_decision={"allowed": True, "reason": "ok"},
                lease_result={"status": "lease_executed",
                              "provider_lease_ref": "r",
                              "secret_material_returned": "false"},
                granted_at=now, expires_at=now + timedelta(hours=1),
                renewal_due_at=now + timedelta(minutes=45),
            )
        )
        repository.create_connector_egress_policy(
            ConnectorEgressPolicyCreate(
                tenant_id=TENANT_A, connector_id=CONNECTOR_ID, policy_id=POLICY_ID,
                display_name="p", status="active", connection_profile_id=PROFILE_ID,
                egress_boundary="approved_private_endpoint",
                policy_mode="approved_private_endpoint",
                runtime_boundary="b",
                private_endpoint_ref="pe://x", created_by="a",
                policy_document={
                    "approved_endpoint_target_sha256": hashlib.sha256(b"localhost:5432").hexdigest()
                },
                evidence_refs=[], audit_event_type="e",
            )
        )
    yield factory
    engine.dispose()


@pytest.fixture
def store_root():
    if STORE_ROOT.exists():
        shutil.rmtree(STORE_ROOT)
    STORE_ROOT.mkdir(parents=True, exist_ok=True)
    yield STORE_ROOT
    if STORE_ROOT.exists():
        shutil.rmtree(STORE_ROOT)


def seed_request(factory, request_id="ingreq_b11", selections=None):
    bindings = selections or [
        {
            "binding_id": "binding_b11_a",
            "resource_name": RESOURCE,
            "schema_fingerprint": FINGERPRINT,
        }
    ]
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        for selection in bindings:
            session.add(
                ConnectorSourceBinding(
                    audit_event_id=uuid4(),
                    tenant_id=TENANT_A,
                    connector_id=CONNECTOR_ID,
                    asset_id=f"source:{CONNECTOR_ID}:default",
                    binding_id=selection["binding_id"],
                    connection_profile_id=PROFILE_ID,
                    resource_name=selection["resource_name"],
                    schema_fingerprint=selection["schema_fingerprint"],
                    credential_lease_id=LEASE_ID,
                    egress_policy_id=POLICY_ID,
                    status="active",
                    ingestion_status="pending_ingestion",
                    activated_by="axis-operator",
                    activation_reason="Batch 11 seeding.",
                    audit_event_type="connector.source.bindings.activated",
                )
            )
            repository.create_data_resource_observation(
                DataResourceObservationCreate(
                    tenant_id=TENANT_A,
                    connector_id=CONNECTOR_ID,
                    asset_id=f"source:{CONNECTOR_ID}:default",
                    resource_name=selection["resource_name"],
                    schema_fingerprint=selection["schema_fingerprint"],
                    drift_state="added",
                    observed_by="b11-lane",
                    source_kind="postgres_discovery",
                )
            )
        event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=TENANT_A,
                actor_id="axis-operator",
                event_type=INGESTION_REQUESTED_EVENT,
                payload={"request_id": request_id},
            )
        )
        repository.create_connector_source_ingestion_request(
            ConnectorSourceIngestionRequestCreate(
                tenant_id=TENANT_A,
                connector_id=CONNECTOR_ID,
                request_id=request_id,
                requested_by="axis-operator",
                reason="Batch 11 probe.",
                stage="extract",
                selections=bindings,
                audit_event_id=event.id,
                audit_event_type=INGESTION_REQUESTED_EVENT,
            ),
            available_at=datetime.now(UTC),
        )


class ScriptedStore:
    """Records writes; lets tests inject failures at each seam."""

    adapter_name = "scripted"

    def __init__(self):
        self.writes: dict[str, dict] = {}
        self.fail_writes = False

    def put_json(self, key: str, payload: dict):
        if self.fail_writes:
            raise OSError("store unavailable")
        from axis_api.object_storage import StoredObjectMetadata

        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.writes[key] = payload
        return StoredObjectMetadata(
            storage_adapter=self.adapter_name,
            storage_key=key,
            storage_uri=f"axis-local-object-store://{key}",
            content_type="application/json",
            checksum_sha256=hashlib.sha256(encoded).hexdigest(),
            size_bytes=len(encoded),
        )


class FailingInsertRepository:
    """Wraps the repo so batch-metadata INSERTs crash mid-transaction."""

    def __init__(self, inner, fail_first: bool):
        self._inner = inner
        self._fail_first = fail_first

    def __getattr__(self, item):
        return getattr(self._inner, item)

    def create_connector_source_extraction_batch(self, record):
        if self._fail_first:
            raise RuntimeError("db gone right after the object was stored")
        return self._inner.create_connector_source_extraction_batch(record)

    @property
    def session(self):
        return self._inner.session

    def append_audit_event(self, *args, **kwargs):
        if self._fail_first:
            raise RuntimeError("db gone")
        return self._inner.append_audit_event(*args, **kwargs)


def run_dispatcher(factory, settings=None, store=None, *, rows=None, fail_second=False):
    settings = settings or both_gates()
    store = store or ScriptedStore()
    runtime = make_stubbed_runtime(
        factory, settings, store,
        rows=rows or [{"order_id": "o-1"}],
    )

    if fail_second:
        original = runtime.prepare_selection

        def failing_second(**kwargs):
            if kwargs["binding_id"] == "binding_b11_r":
                return SourceExtractionOutcome(ok=False, reason="stale_fingerprint")
            return original(**kwargs)

        runtime.prepare_selection = failing_second  # type: ignore[method-assign]

    dispatcher = SourceIngestionOutboxDispatcher(
        settings=settings,
        session_factory=factory,
        runtime=ObservationFreshnessIngestionRuntime(),
        extraction_runtime=runtime,
        random_uniform=lambda low, high: low,
    )
    return asyncio.run(dispatcher.run_once()), store


def make_stubbed_runtime(factory, settings, store, rows=None):
    from axis_api.connector_source_extraction import SelfHostedPostgresExtractionRuntime

    runtime = SelfHostedPostgresExtractionRuntime(settings=settings, object_store=store)
    payload_rows = rows or [{"order_id": "o-1"}]

    def scripted_read(resource_name, limits, hardening, **schema_evidence):
        encoded_rows = [
            json.dumps(row, sort_keys=True).encode() for row in payload_rows
        ]
        first_column = next(iter(payload_rows[0])) if payload_rows else "id"
        watermark = {first_column: payload_rows[-1][first_column]} if payload_rows else None
        return {
            "ordering_mode": "primary_key",
            "cursor_watermark": watermark,
            "rows": payload_rows,
            "byte_size": sum(len(encoded) for encoded in encoded_rows),
            "truncated": False,
            "limit_reason": None,
        }

    runtime._read_bounded = scripted_read  # type: ignore[method-assign]
    return runtime


# ---------------------------------------------------------------------------
# Read model


def test_batches_endpoint_requires_read_scope(session_factory) -> None:
    seed_request(session_factory)
    client = build_client(session_factory)
    denied = client.get(
        "/operations/connectors/external-db/source-ingestion-requests/ingreq_b11/batches"
    )
    assert denied.status_code == 403
    body = denied.json()["detail"]
    assert body["required_permission"] == READ_SCOPE


def test_batches_endpoint_unknown_request_is_not_found(session_factory) -> None:
    client = build_client(session_factory)
    response = client.get(
        "/operations/connectors/external-db/source-ingestion-requests/ghost/batches",
        params={"actor_scopes": [READ_SCOPE]},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "ingestion_request_not_found"


def test_batches_pagination_is_stable_and_filtered(session_factory) -> None:
    seed_request(
        session_factory,
        selections=[
            {"binding_id": "binding_b11_a", "resource_name": RESOURCE,
             "schema_fingerprint": FINGERPRINT},
            {"binding_id": "binding_b11_b", "resource_name": "operations.quality_checks",
             "schema_fingerprint": FINGERPRINT},
        ],
    )
    seed_completed_batches(session_factory, count=3)

    client = build_client(session_factory)
    base = "/operations/connectors/external-db/source-ingestion-requests/ingreq_b11/batches"
    params = {"tenant_id": TENANT_A, "actor_scopes": [READ_SCOPE]}

    page_one = client.get(base, params={**params, "limit": 2})
    assert page_one.status_code == 200
    body = page_one.json()
    assert body["total_count"] == 3
    assert [batch["batch_key"] for batch in body["batches"]] == sorted(
        batch["batch_key"] for batch in body["batches"]
    )
    assert body["next_cursor"] is not None

    page_two = client.get(base, params={**params, "limit": 2, "cursor": body["next_cursor"]})
    assert page_two.status_code == 200
    second_body = page_two.json()
    first_keys = {batch["batch_key"] for batch in body["batches"]}
    second_keys = {batch["batch_key"] for batch in second_body["batches"]}
    assert not first_keys & second_keys

    filtered = client.get(
        base, params={**params, "binding_id": "binding_b11_a"}
    )
    assert filtered.status_code == 200
    assert all(
        batch["binding_id"] == "binding_b11_a"
        for batch in filtered.json()["batches"]
    )

    invalid_cursor = client.get(base, params={**params, "cursor": "!!!"})
    assert invalid_cursor.status_code == 422
    assert invalid_cursor.json()["detail"]["reason"] == "invalid_cursor"


def test_batch_items_are_metadata_only(session_factory) -> None:
    seed_request(session_factory)
    seed_completed_batches(session_factory, count=1)
    client = build_client(session_factory)
    response = client.get(
        "/operations/connectors/external-db/source-ingestion-requests/ingreq_b11/batches",
        params={"tenant_id": TENANT_A, "actor_scopes": [READ_SCOPE]},
    )
    batch = response.json()["batches"][0]
    assert set(batch.keys()) == {
        "batch_key", "binding_id", "resource_name",
        "pinned_schema_fingerprint", "observed_schema_fingerprint",
        "ordering_mode", "has_watermark", "row_count", "byte_size", "truncated",
        "limit_reason", "duration_ms", "digest_sha256", "storage_uri",
        "content_type", "stored_size_bytes", "classification", "executed_by",
        "created_at",
    }
    assert batch["has_watermark"] is True


def build_client(factory, settings: Settings | None = None) -> TestClient:
    from axis_api.main import create_app

    app = create_app(settings or Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    return TestClient(app)


def seed_completed_batches(factory, *, count: int, request_id: str = "ingreq_b11") -> list[dict]:
    """Persist batch metadata exactly as the dispatcher would."""
    batches = []
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        for index in range(count):
            event = repository.append_audit_event(
                AuditEventCreate(
                    tenant_id=TENANT_A,
                    actor_id="axis-source-ingestion-outbox",
                    event_type="connector.source.extraction.batch_recorded",
                    payload={"request_id": request_id, "index": str(index)},
                )
            )
            batch_key = f"{request_id}:binding_b11_{chr(97 + index)}:{index}"
            storage_key = (
                f"tenants/{TENANT_A}/source-ingestion/{request_id}/"
                f"binding_b11_{chr(97 + index)}/{batch_key}.json"
            )
            encoded_bytes = json.dumps({"rows": [f"row-{index}"]}).encode()
            repository.create_connector_source_extraction_batch(
                __import__(
                    "axis_api.persistence", fromlist=["ConnectorSourceExtractionBatchCreate"]
                ).ConnectorSourceExtractionBatchCreate(
                    tenant_id=TENANT_A,
                    connector_id=CONNECTOR_ID,
                    request_id=request_id,
                    batch_key=batch_key,
                    binding_id=f"binding_b11_{chr(97 + index)}",
                    resource_name=RESOURCE,
                    pinned_schema_fingerprint=FINGERPRINT,
                    observed_schema_fingerprint=FINGERPRINT,
                    ordering_mode="primary_key",
                    cursor_watermark={"order_id": "o-1"},
                    row_count=1,
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
                    classification="undeclared",
                    executed_by="axis-source-ingestion-outbox",
                    audit_event_id=event.id,
                    audit_event_type="connector.source.extraction.batch_recorded",
                )
            )
            batches.append({
                "storage_key": storage_key,
                "bytes": json.dumps({"rows": [f"row-{index}"]}).encode(),
            })
    # Materialize the matching objects when a store root exists.
    if STORE_ROOT.parent.exists():
        STORE_ROOT.mkdir(parents=True, exist_ok=True)
        for item in batches:
            target = STORE_ROOT / item["storage_key"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item["bytes"])
    return batches


# ---------------------------------------------------------------------------
# Reconciliation


def test_reconciliation_classifies_all_four_states(session_factory, store_root) -> None:
    seed_request(session_factory)
    materialized = seed_completed_batches(session_factory, count=2)
    # Tamper one object (digest mismatch) and delete the other (missing).
    tampered = STORE_ROOT / materialized[0]["storage_key"]
    tampered.write_bytes(json.dumps({"rows": ["tampered"]}).encode())
    (STORE_ROOT / materialized[1]["storage_key"]).unlink()
    # Plant an orphan under the request namespace.
    orphan_key = (
        f"tenants/{TENANT_A}/source-ingestion/ingreq_b11/binding_z/orphan.json"
    )
    orphan_path = STORE_ROOT / orphan_key
    orphan_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_path.write_bytes(b"{}")

    with session_scope(session_factory) as session:
        report = reconcile_request_batches(
            AxisPersistenceRepository(session),
            store=LocalReconcilableObjectStore(store_root),
            local_root=store_root,
            tenant_id=TENANT_A,
            request_id="ingreq_b11",
        )

    assert report is not None
    assert report.dry_run is True
    assert report.clean_matches == 0
    assert report.digest_mismatches == 1
    assert report.missing_objects == 1
    assert report.orphaned_objects == 1
    classes = {finding.classification for finding in report.findings}
    assert classes == {
        "digest_mismatch", "missing_object", "orphaned_object",
    }


def test_reconciliation_clean_match_on_intact_store(session_factory, store_root) -> None:
    seed_request(session_factory)
    seed_completed_batches(session_factory, count=2)
    with session_scope(session_factory) as session:
        report = reconcile_request_batches(
            AxisPersistenceRepository(session),
            store=LocalReconcilableObjectStore(store_root),
            local_root=store_root,
            tenant_id=TENANT_A,
            request_id="ingreq_b11",
        )
    assert report is not None
    assert report.clean_matches == 2
    assert report.orphaned_objects == 0
    serialized = report.model_dump_json()
    assert "row-" not in serialized  # never any row content


# ---------------------------------------------------------------------------
# Stewardship-driven classification


def seed_stewardship(factory, tenant_id: str, classification: str) -> None:
    from axis_api.models import DataAssetStewardshipRecord

    with session_scope(factory) as session:
        session.add(
            DataAssetStewardshipRecord(
                tenant_id=tenant_id,
                asset_id=f"source:{CONNECTOR_ID}:default",
                revision_number=1,
                owner="plant-data-office",
                classification=classification,
                residency="eu",
                retention_policy="standard",
                declared_by="axis-operator",
                schema_mapping={},
                audit_event_type="data.stewardship.declared",
            )
        )


def test_classification_uses_declared_stewardship_only(session_factory) -> None:
    """Declared classification is metadata truth; row values never infer it."""
    from axis_api.persistence import DataAssetStewardshipCreate

    with session_scope(session_factory) as session:
        AxisPersistenceRepository(session).create_data_asset_stewardship_record(
            DataAssetStewardshipCreate(
                tenant_id=TENANT_A,
                asset_id=f"source:{CONNECTOR_ID}:default",
                revision_number=1,
                owner="plant-data-office",
                classification="restricted",
                residency="eu-de",
                retention="standard",
                declared_by="axis-operator",
            )
        )
    seed_request(session_factory)
    store = ScriptedStore()
    # A row VALUE that looks like a classification must not influence anything.
    result, _ = run_dispatcher(
        session_factory,
        store=store,
        rows=[{"order_id": "o-1", "note": "confidential"}],
    )
    assert result.completed == 1
    with session_scope(session_factory) as session:
        batch = session.scalars(select(ConnectorSourceExtractionBatch)).first()
        assert batch.classification == "restricted"
        # Metadata-only: the row value stayed in the object envelope alone.
        report_surface = json.dumps({
            "batch_key": batch.batch_key,
            "digest": batch.digest_sha256,
        })
        assert "confidential" not in report_surface


def test_classification_defaults_to_undeclared_without_declaration(
    session_factory,
) -> None:
    seed_request(session_factory)
    store = ScriptedStore()
    result, _ = run_dispatcher(session_factory, store=store)
    assert result.completed == 1
    with session_scope(session_factory) as session:
        batch = session.scalars(select(ConnectorSourceExtractionBatch)).first()
        assert batch.classification == "undeclared"


def test_classification_respects_tenant_isolation(session_factory) -> None:
    """Another tenant's declaration can never classify this tenant's data."""
    from axis_api.persistence import DataAssetStewardshipCreate

    with session_scope(session_factory) as session:
        AxisPersistenceRepository(session).create_data_asset_stewardship_record(
            DataAssetStewardshipCreate(
                tenant_id=TENANT_B,
                asset_id=f"source:{CONNECTOR_ID}:default",
                revision_number=1,
                owner="other-office",
                classification="public",
                residency="eu",
                retention="standard",
                declared_by="x",
            )
        )
    seed_request(session_factory)
    store = ScriptedStore()
    result, _ = run_dispatcher(session_factory, store=store)
    assert result.completed == 1
    with session_scope(session_factory) as session:
        batch = session.scalars(select(ConnectorSourceExtractionBatch)).first()
        assert batch.classification == "undeclared"


def test_s3_port_filters_prefix_violations_and_paginates() -> None:
    """Unwired typed port: fake client proves containment + pagination."""
    from axis_api.connector_source_extraction_reconciliation import (
        S3ReconcilableObjectStore,
    )

    pages = [
        {
            "Contents": [
                {"Key": "tenants/t/source-ingestion/r1/a.json"},
                {"Key": "tenants/t/source-ingestion/r1/b.json"},
            ],
            "NextContinuationToken": "tok",
        },
        {
            # A misbehaving client returning a key OUTSIDE the prefix must be
            # filtered, never surfaced as reconciliation truth.
            "Contents": [
                {"Key": "tenants/t/source-ingestion/r1/c.json"},
                {"Key": "tenants/OTHER/bucket-wide.json"},
            ],
        },
    ]

    class FakeS3Client:
        def __init__(self):
            self.calls = []

        def list_objects_v2(self, bucket_name, prefix, *, continuation_token=None):
            self.calls.append((bucket_name, prefix, continuation_token))
            return pages[len([c for c in self.calls if c[1] == prefix]) - 1]

    fake = FakeS3Client()
    keys = S3ReconcilableObjectStore(fake, "bucket").list_keys_under(
        ["tenants/t/source-ingestion/r1/"]
    )
    assert keys == {
        "tenants/t/source-ingestion/r1/a.json",
        "tenants/t/source-ingestion/r1/b.json",
        "tenants/t/source-ingestion/r1/c.json",
    }
    assert ("bucket", "tenants/t/source-ingestion/r1/", "tok") in fake.calls


def test_s3_port_rejects_absolute_prefixes() -> None:
    from axis_api.connector_source_extraction_reconciliation import (
        S3ReconcilableObjectStore,
    )

    store = S3ReconcilableObjectStore(object(), "bucket")
    with pytest.raises(ValueError):
        store.list_keys_under(["/absolute"])


def test_reconciliation_prefix_traversal_is_rejected(store_root) -> None:
    store = LocalReconcilableObjectStore(store_root)
    with pytest.raises(ValueError):
        store.list_keys_under(["tenants/../../etc"])
    with pytest.raises(ValueError):
        store.list_keys_under(["/absolute/escape"])


def test_reconciliation_skips_symlink_escape(store_root) -> None:
    """A symlinked directory resolving outside the root is never listed."""
    inside = store_root / "tenants/x/source-ingestion/r1/link"
    outside_dir = store_root / "outside-secret"
    outside_dir.mkdir(parents=True, exist_ok=True)
    (outside_dir / "leak.json").write_bytes(b"{}")
    inside.mkdir(parents=True, exist_ok=True)
    link = inside / "escape"
    try:
        link.symlink_to(outside_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable on this filesystem")

    keys = LocalReconcilableObjectStore(store_root).list_keys_under(
        ["tenants/x/source-ingestion/r1/"]
    )
    assert all(not key.startswith("outside") for key in keys)
    assert "outside-secret/leak.json" not in keys


def test_reconciliation_never_scopes_across_requests(session_factory, store_root) -> None:
    seed_request(session_factory, request_id="ingreq_b11")
    seed_completed_batches(session_factory, count=1, request_id="ingreq_b11")
    seed_request(
        session_factory,
        request_id="ingreq_other",
        selections=[
            {
                "binding_id": "binding_b11_z",
                "resource_name": "operations.shipment_lines",
                "schema_fingerprint": FINGERPRINT,
            }
        ],
    )
    # Sibling batches use that sibling's own binding identity.
    original_count = 1
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=TENANT_A,
                actor_id="axis-source-ingestion-outbox",
                event_type="connector.source.extraction.batch_recorded",
                payload={"request_id": "ingreq_other"},
            )
        )
        batch_key = "ingreq_other:binding_b11_z:0"
        storage_key = (
            f"tenants/{TENANT_A}/source-ingestion/ingreq_other/"
            "binding_b11_z/ingreq_other:binding_b11_z:0.json"
        )
        from axis_api.persistence import ConnectorSourceExtractionBatchCreate

        repository.create_connector_source_extraction_batch(
            ConnectorSourceExtractionBatchCreate(
                tenant_id=TENANT_A,
                connector_id=CONNECTOR_ID,
                request_id="ingreq_other",
                batch_key=batch_key,
                binding_id="binding_b11_z",
                resource_name="operations.shipment_lines",
                pinned_schema_fingerprint=FINGERPRINT,
                observed_schema_fingerprint=FINGERPRINT,
                ordering_mode="none",
                cursor_watermark=None,
                row_count=1,
                byte_size=16,
                truncated=False,
                limit_reason=None,
                duration_ms=5,
                limits_applied={},
                provenance={},
                digest_sha256=hashlib.sha256(b"other").hexdigest(),
                storage_adapter="local_filesystem",
                storage_key=storage_key,
                storage_uri=f"axis-local-object-store://{storage_key}",
                content_type="application/json",
                stored_size_bytes=6,
                classification="undeclared",
                executed_by="axis-source-ingestion-outbox",
                audit_event_id=event.id,
                audit_event_type="connector.source.extraction.batch_recorded",
            )
        )
    STORE_ROOT.joinpath(storage_key).parent.mkdir(parents=True, exist_ok=True)
    STORE_ROOT.joinpath(storage_key).write_bytes(b"other!")
    other = [{"storage_key": storage_key}]
    del original_count

    with session_scope(session_factory) as session:
        report = reconcile_request_batches(
            AxisPersistenceRepository(session),
            store=LocalReconcilableObjectStore(store_root),
            local_root=store_root,
            tenant_id=TENANT_A,
            request_id="ingreq_b11",
        )
    assert report is not None
    # The sibling request's objects are invisible to this scoped scan.
    assert other[0]["storage_key"] not in {
        finding.storage_key for finding in report.findings
    }
    assert report.orphaned_objects == 0


def test_reconciliation_reports_empty_request_as_all_zero(session_factory, store_root) -> None:
    seed_request(session_factory, request_id="ingreq_empty")
    with session_scope(session_factory) as session:
        report = reconcile_request_batches(
            AxisPersistenceRepository(session),
            store=LocalReconcilableObjectStore(store_root),
            local_root=store_root,
            tenant_id=TENANT_A,
            request_id="ingreq_empty",
        )
    assert report is not None
    assert report.clean_matches == 0 and report.orphaned_objects == 0
    assert report.findings == []


def test_reconciliation_findings_are_deterministically_ordered(
    session_factory, store_root
) -> None:
    seed_request(session_factory)
    materialized = seed_completed_batches(session_factory, count=3)
    for item in materialized[1:]:
        (STORE_ROOT / item["storage_key"]).unlink()
    with session_scope(session_factory) as session:
        report = reconcile_request_batches(
            AxisPersistenceRepository(session),
            store=LocalReconcilableObjectStore(store_root),
            local_root=store_root,
            tenant_id=TENANT_A,
            request_id="ingreq_b11",
        )
    keys = [finding.storage_key or finding.batch_key for finding in report.findings]
    assert keys == sorted(keys)


def test_reconciliation_route_rejects_unsupported_adapter(
    session_factory, store_root
) -> None:
    client = build_client(session_factory, both_gates_s3())
    response = client.get(
        "/operations/connectors/external-db/source-ingestion-requests/ingreq_b11/batches/reconciliation",
        params={"tenant_id": TENANT_A, "actor_scopes": [READ_SCOPE]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "store_adapter_unsupported"


def both_gates_s3() -> Settings:
    return Settings(
        postgres_dsn="sqlite+pysqlite://",
        connector_export_object_store_adapter="s3_compatible",
    )


def test_s3_configured_reconciliation_returns_409_without_client_construction(
    session_factory, store_root, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3 configuration must fail closed WITHOUT any client construction."""
    from axis_api import main as main_module

    # Structural proof of the boundary: main imports no private S3 helpers.
    assert not hasattr(main_module, "_s3_client_factory")
    assert not hasattr(main_module, "S3ReconcilableObjectStore")

    settings = Settings(
        postgres_dsn="sqlite+pysqlite://",
        connector_export_object_store_adapter="s3_compatible",
        connector_export_s3_bucket="bucket",
        connector_export_s3_access_key="k",
        connector_export_s3_secret_key="s",
    )
    client = build_client(session_factory, settings)
    response = client.get(
        "/operations/connectors/external-db/source-ingestion-requests/ingreq_b11/batches/reconciliation",
        params={"tenant_id": TENANT_A, "actor_scopes": [READ_SCOPE]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "store_adapter_unsupported"


def test_reconciliation_route_rejects_non_dry_run(session_factory, store_root) -> None:
    seed_request(session_factory)
    client = build_client(session_factory)
    response = client.get(
        "/operations/connectors/external-db/source-ingestion-requests/ingreq_b11/batches/reconciliation",
        params={"tenant_id": TENANT_A, "actor_scopes": [READ_SCOPE], "dry_run": False},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "dry_run_only"


# ---------------------------------------------------------------------------
# Recovery / crash boundaries


def test_store_write_failure_leaves_no_metadata_or_audit(session_factory) -> None:
    seed_request(session_factory)
    store = ScriptedStore()
    store.fail_writes = True
    result, _ = run_dispatcher(session_factory, store=store)

    assert result.retried == 1 or result.dead_lettered == 1
    with session_scope(session_factory) as session:
        assert session.scalars(select(ConnectorSourceExtractionBatch)).all() == []
        events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.source.extraction.batch_recorded"
            )
        ).all()
        assert events == []


def test_db_failure_after_store_write_converges_on_same_key(session_factory) -> None:
    """Retry overwrites the identical object key; nothing duplicates."""

    seed_request(session_factory)
    store = ScriptedStore()

    # First pass: metadata insert crashes after the object was stored.
    settings = both_gates()
    runtime = make_stubbed_runtime(session_factory, settings, store)
    dispatcher = SourceIngestionOutboxDispatcher(
        settings=settings,
        session_factory=session_factory,
        runtime=ObservationFreshnessIngestionRuntime(),
        extraction_runtime=runtime,
        random_uniform=lambda lo, hi: lo,
    )
    real_extract = runtime.read_selection

    def extract_with_db_failure(prepared):
        outcome = real_extract(prepared)
        if outcome.ok:
            # Simulate the crash AFTER the store write, BEFORE the DB commit.
            raise RuntimeError("crash between stores")
        return outcome

    runtime.read_selection = extract_with_db_failure  # type: ignore[method-assign]
    first = asyncio.run(dispatcher.run_once())
    assert first.retried == 1
    key_after_crash = next(iter(store.writes))

    second, _ = run_dispatcher(session_factory, settings=settings, store=store)
    assert second.completed == 1
    assert len(store.writes) == 1  # same single key, overwritten
    assert next(iter(store.writes)) == key_after_crash

    with session_scope(session_factory) as session:
        batches = session.scalars(select(ConnectorSourceExtractionBatch)).all()
        assert len(batches) == 1  # metadata never duplicates across attempts
        events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.source.extraction.batch_recorded"
            )
        ).all()
        assert len(events) == 1  # exactly one durable audit event


def test_completed_request_never_claims_or_writes_again(session_factory) -> None:
    seed_request(session_factory)
    store = ScriptedStore()
    first, _ = run_dispatcher(session_factory, store=store)
    assert first.completed == 1
    writes_after_success = len(store.writes)
    events_after_success = session_events_count(
        session_factory, "connector.source.extraction.batch_recorded"
    )

    second, _ = run_dispatcher(session_factory, store=store)
    assert second.claimed == 0
    assert len(store.writes) == writes_after_success
    assert (
        session_events_count(session_factory, "connector.source.extraction.batch_recorded")
        == events_after_success
    )


# ---------------------------------------------------------------------------
# Re-dispatch of dead-lettered requests


def seed_dead_lettered(factory, request_id="ingreq_dead", reason_code="stale_fingerprint"):
    seed_request(factory, request_id=request_id)
    with session_scope(factory) as session:
        row = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == request_id
            )
        ).first()
        now = datetime.now(UTC)
        row.status = "failed"
        row.attempt_count = 3
        row.dead_lettered_at = now
        row.last_error = reason_code


REQUEUE_BODY = {
    "tenant_id": TENANT_A,
    "requeued_by": "axis-operator",
    "reason": "Fresh discovery completed; fingerprints remediated.",
    "idempotency_key": "requeue_lane_001",
    "actor_scopes": [SOURCE_INGESTION_SCOPE],
}


def requeue_via_route(client, request_id="ingreq_dead", body=None):
    return client.post(
        f"/operations/connectors/external-db/source-ingestion-requests/{request_id}/requeue",
        json=body or REQUEUE_BODY,
    )


def test_redispatch_route_full_matrix(session_factory) -> None:
    seed_dead_lettered(session_factory)
    client = build_client(session_factory, both_gates())

    # Missing write scope fails closed.
    denied = requeue_via_route(
        client, body={**REQUEUE_BODY, "actor_scopes": ["connectors:source:ingest:read"]}
    )
    assert denied.status_code == 403

    # Ghost request 404s.
    ghost = requeue_via_route(client, request_id="ingreq_ghost")
    assert ghost.status_code == 404

    # Happy path: dead-lettered -> pending.
    ok = requeue_via_route(client)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "pending"

    # Identical replay returns 200 without a second audit event.
    replay = requeue_via_route(client)
    assert replay.status_code == 200
    events = session_events_count(
        session_factory, "connector.source.ingestion.requeued"
    )
    assert events == 1

    # Different ask conflicts and changes nothing.
    conflict = requeue_via_route(
        client, body={**REQUEUE_BODY, "reason": "A different remediation."}
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason"] == "requeue_conflict"
    assert (
        session_events_count(session_factory, "connector.source.ingestion.requeued") == 1
    )

    # A pending (non-dead-lettered) request cannot be re-dispatched.
    seed_request(
        session_factory,
        request_id="ingreq_plain_pending",
        selections=[
            {
                "binding_id": "binding_b11_p",
                "resource_name": "operations.shipment_lines",
                "schema_fingerprint": FINGERPRINT,
            }
        ],
    )
    pending_hit = requeue_via_route(client, request_id="ingreq_plain_pending")
    assert pending_hit.status_code == 409


def test_redispatch_requires_reason_and_idempotency_key(session_factory) -> None:
    client = build_client(session_factory, both_gates())
    for missing in ("reason", "idempotency_key"):
        body = {k: v for k, v in REQUEUE_BODY.items() if k != missing}
        response = requeue_via_route(client, request_id="whatever", body=body)
        assert response.status_code == 422  # pydantic contract, before any state


def test_redispatch_then_remediated_extraction_completes(session_factory) -> None:
    """The full operator story: drift -> dead-letter -> fix -> re-dispatch."""

    # Two selections: first healthy, second will fail validation then be
    # remediated — the full operator recovery story.
    seed_request(
        session_factory,
        request_id="ingreq_redispatch_e2e",
        selections=[
            {"binding_id": "binding_b11_a", "resource_name": RESOURCE,
             "schema_fingerprint": FINGERPRINT},
            {"binding_id": "binding_b11_r", "resource_name": "operations.quality_checks",
             "schema_fingerprint": FINGERPRINT},
        ],
    )

    # Force the terminal failure honestly through a failing second selection.
    store = ScriptedStore()
    settings = both_gates()
    first, _ = run_dispatcher(
        session_factory, settings=settings, store=store, fail_second=True,
        rows=[{"order_id": "o-1"}],
    )
    assert first.dead_lettered == 1

    # Operator remediates and re-dispatches via the governed route semantics.
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        _, outcome = __import__(
            "axis_api.connector_source_ingestion",
            fromlist=["requeue_connector_source_ingestion_request"],
        ).requeue_connector_source_ingestion_request(
            repository,
            tenant_id=TENANT_A,
            request_id="ingreq_redispatch_e2e",
            requeued_by="axis-operator",
            reason="Second table re-activated after fresh discovery.",
            idempotency_key="requeue_e2e_001",
            principal_scopes=[SOURCE_INGESTION_SCOPE],
        )
        assert outcome == "requeued"

    # Remediation: make selection 2 healthy again by healing its fingerprint.
    with session_scope(session_factory) as session:
        observation = AxisPersistenceRepository(
            session
        ).get_data_resource_observation(
            TENANT_A, CONNECTOR_ID, "operations.quality_checks"
        )
        observation.schema_fingerprint = FINGERPRINT

    result, _ = run_dispatcher(
        session_factory,
        settings=settings,
        store=store,
        rows=[{"check_id": "c-1"}],
    )
    assert result.completed == 1
    with session_scope(session_factory) as session:
        row = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == "ingreq_redispatch_e2e"
            )
        ).first()
        assert row.status == "completed"
        assert row.attempt_count == 1  # reset by requeue, then this pass
        surfaces = json.dumps(row.evidence) + json.dumps(
            [str(e.payload) for e in session.scalars(select(AuditEvent)).all()]
        )
        assert "c-1" not in surfaces  # sentinel: no raw values anywhere


def test_concurrent_redispatch_yields_exactly_one_mutation_and_event(
    store_root,
) -> None:
    """Genuine cross-connection contention over a shared repo-local DB file."""
    import threading

    db_file = store_root / "redispatch-concurrency.sqlite3"

    def fresh_factory():
        engine = create_engine(
            f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    # Bootstrap durable truth once through the canonical repository seam.
    maker = fresh_factory()
    with session_scope(maker) as session:
        repository = AxisPersistenceRepository(session)
        repository.create_tenant(
            TenantCreate(tenant_id=TENANT_A, display_name="R", description="d", created_by="t")
        )
        event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=TENANT_A,
                actor_id="axis-operator",
                event_type=INGESTION_REQUESTED_EVENT,
                payload={"request_id": "ingreq_dead"},
            )
        )
        repository.create_connector_source_ingestion_request(
            ConnectorSourceIngestionRequestCreate(
                tenant_id=TENANT_A,
                connector_id=CONNECTOR_ID,
                request_id="ingreq_dead",
                requested_by="axis-operator",
                reason="Concurrency probe.",
                stage="extract",
                selections=[
                    {
                        "binding_id": "binding_b11_a",
                        "resource_name": RESOURCE,
                        "schema_fingerprint": FINGERPRINT,
                    }
                ],
                audit_event_id=event.id,
                audit_event_type=INGESTION_REQUESTED_EVENT,
            ),
            available_at=datetime.now(UTC),
        )
        row = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == "ingreq_dead"
            )
        ).first()
        now = datetime.now(UTC)
        row.status = "failed"
        row.attempt_count = 3
        row.dead_lettered_at = now
        row.last_error = "stale_fingerprint"

    settings = both_gates()
    outcomes: list[tuple[int, str]] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2)
    primary_client = build_client(fresh_factory(), settings)
    clients = [primary_client, TestClient(primary_client.app)]

    # Compile the shared response model before the threads contend on the file DB.
    warmup = primary_client.get(
        "/operations/connectors/external-db/source-ingestion-requests/ingreq_dead",
        params={"tenant_id": TENANT_A, "actor_scopes": [READ_SCOPE]},
    )
    assert warmup.status_code == 200

    def hit(client: TestClient) -> None:
        try:
            barrier.wait()
            response = requeue_via_route(client)
            body = response.json()
            outcomes.append((response.status_code, body.get("status", "")))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=hit, args=(client,)) for client in clients]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for client in clients:
        client.close()

    assert errors == [], errors
    conflicts = [code for code, _ in outcomes if code == 409]
    successes = [pair for pair in outcomes if pair[0] == 200]
    assert len(outcomes) == 2 and len(successes) >= 1
    assert len(conflicts) + len(successes) == 2

    verify = fresh_factory()
    with session_scope(verify) as session:
        row = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == "ingreq_dead"
            )
        ).first()
        events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.source.ingestion.requeued"
            )
        ).all()

    assert row is not None
    assert row.status == "pending" and row.dead_lettered_at is None
    assert len(events) == 1
    assert str(row.audit_event_id) == str(events[0].id)
    assert row.stage == "extract"
    assert [sel["binding_id"] for sel in row.selections] == ["binding_b11_a"]


def session_events_count(factory, event_type: str) -> int:
    with session_scope(factory) as session:
        return len(
            session.scalars(
                select(AuditEvent).where(AuditEvent.event_type == event_type)
            ).all()
        )
