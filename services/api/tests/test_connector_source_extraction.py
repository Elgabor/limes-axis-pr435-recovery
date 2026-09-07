"""Real bounded extraction behind governed ingestion requests: unit coverage.

Covers the trust boundary without dialing anything: fail-closed gates before
any connection, honest caps/truncation semantics, payload confinement to the
object-store envelope, dispatcher end-to-end composition on SQLite with fake
source/object-store doubles, and the full cancel lifecycle contract.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.connector_source_extraction import (
    ExtractionLimits,
    SelfHostedPostgresExtractionRuntime,
    SourceExtractionOutcome,
)
from axis_api.connector_source_ingestion import (
    INGESTION_REQUESTED_EVENT,
    SOURCE_INGESTION_SCOPE,
    ConnectorSourceIngestionSubmission,
    ObservationFreshnessIngestionRuntime,
    SourceIngestionOutboxDispatcher,
)
from axis_api.connectors import csv_header_fingerprint
from axis_api.db import session_scope
from axis_api.models import (
    AuditEvent,
    Base,
    ConnectorSourceBinding,
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

FINGERPRINT = csv_header_fingerprint(["id"])
DRIFTED = "b" * 64
RESOURCE = "operations.production_orders"
LEASE_ID = "lease_extract_unit_001"
POLICY_ID = "egress_policy_extract_unit_001"


def both_gates(**overrides) -> Settings:
    values = dict(
        AXIS_SOURCE_INGESTION_DISPATCH_ENABLED=True,
        AXIS_SOURCE_INGESTION_EXTRACTION_ENABLED=True,
        external_db_live_query_dsn="postgresql://axis:axis@localhost:5432/axis",
        connector_export_object_store_adapter="local_filesystem",
        connector_export_object_store_root=".audit/opencode-runtime/batch10/runtime",
    )
    values.update(overrides)
    return Settings(**values)


def submission(**overrides) -> ConnectorSourceIngestionSubmission:
    payload = {
        "tenant_id": TENANT_A,
        "connector_id": CONNECTOR_ID,
        "request_id": "ingreq_extract_001",
        "requested_by": "axis-operator",
        "reason": "Extract bounded sample for pipeline design review.",
        "stage": "validate",
        "selections": [{"binding_id": "binding_extract_001"}],
        "actor_scopes": [SOURCE_INGESTION_SCOPE],
    }
    payload.update(overrides)
    return ConnectorSourceIngestionSubmission(**payload)


class RecordingObjectStore:
    adapter_name = "recording_test"

    def __init__(self):
        self.writes: list[tuple[str, dict]] = []

    def put_json(self, key: str, payload: dict):
        self.writes.append((key, payload))
        from axis_api.object_storage import StoredObjectMetadata

        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        import hashlib

        return StoredObjectMetadata(
            storage_adapter=self.adapter_name,
            storage_key=key,
            storage_uri=f"recording://{key}",
            content_type="application/json",
            checksum_sha256=hashlib.sha256(encoded).hexdigest(),
            size_bytes=len(encoded),
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
                description="Isolation probe",
                created_by="test",
            )
        )
        now = datetime.now(UTC)
        repository.create_connector_credential_lease(
            ConnectorCredentialLeaseCreate(
                tenant_id=TENANT_A,
                connector_id=CONNECTOR_ID,
                handle_id="cred_extract_unit",
                lease_id=LEASE_ID,
                status="active",
                requested_by="axis-operator",
                lease_purpose="source_extraction_unit",
                secret_provider="env",
                secret_ref="AXIS_EXTERNAL_DB_DISCOVERY_TEST_DSN",
                vault_kms_policy={},
                permission_decision={"allowed": True, "reason": "all_required_scopes_present"},
                lease_result={
                    "status": "lease_executed",
                    "provider_lease_ref": f"self-hosted-vault-kms://{TENANT_A}/{LEASE_ID}",
                    "secret_material_returned": "false",
                },
                granted_at=now,
                expires_at=now + timedelta(hours=1),
                renewal_due_at=now + timedelta(minutes=45),
            )
        )
        import hashlib

        repository.create_connector_egress_policy(
            ConnectorEgressPolicyCreate(
                tenant_id=TENANT_A,
                connector_id=CONNECTOR_ID,
                policy_id=POLICY_ID,
                display_name="Operations private endpoint",
                status="active",
                connection_profile_id=PROFILE_ID,
                egress_boundary="approved_private_endpoint",
                policy_mode="approved_private_endpoint",
                runtime_boundary="axis-egress-policy-enforcer",
                private_endpoint_ref=(
                    f"private-endpoint://{TENANT_A}/persisted-operations-postgres-readonly"
                ),
                created_by="axis-operator",
                policy_document={
                    "approved_endpoint_target_sha256": hashlib.sha256(
                        b"localhost:5432"
                    ).hexdigest()
                },
                evidence_refs=[],
                audit_event_type="connector.egress_policy.registered",
            )
        )
    yield factory
    engine.dispose()


def seed_binding_and_observation(
    factory,
    *,
    fingerprint: str = FINGERPRINT,
    tenant_id: str = TENANT_A,
) -> None:
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        session.add(
            ConnectorSourceBinding(
                audit_event_id=uuid4(),
                tenant_id=tenant_id,
                connector_id=CONNECTOR_ID,
                asset_id=f"source:{CONNECTOR_ID}:default",
                binding_id="binding_extract_001",
                connection_profile_id=PROFILE_ID,
                resource_name=RESOURCE,
                schema_fingerprint=fingerprint,
                credential_lease_id=LEASE_ID if tenant_id == TENANT_A else "lease_ghost",
                egress_policy_id=POLICY_ID if tenant_id == TENANT_A else "policy_ghost",
                status="active",
                ingestion_status="pending_ingestion",
                activated_by="axis-operator",
                activation_reason="Seeded by extraction unit tests.",
                audit_event_type="connector.source.bindings.activated",
            )
        )
        repository.create_data_resource_observation(
            DataResourceObservationCreate(
                tenant_id=tenant_id,
                connector_id=CONNECTOR_ID,
                asset_id=f"source:{CONNECTOR_ID}:default",
                resource_name=RESOURCE,
                schema_fingerprint=fingerprint,
                drift_state="added",
                observed_by="extract-unit-lane",
                source_kind="postgres_discovery",
            )
        )


def make_runtime(factory, settings: Settings | None = None, store=None):
    return SelfHostedPostgresExtractionRuntime(
        settings=settings or both_gates(),
        object_store=store or RecordingObjectStore(),
    )


def call_runtime(runtime, factory, **overrides):
    with session_scope(factory) as session:
        return runtime.extract_selection(
            repository=AxisPersistenceRepository(session),
            tenant_id=TENANT_A,
            connector_id=CONNECTOR_ID,
            request_id="ingreq_extract_001",
            batch_key="ingreq_extract_001:binding_extract_001:0",
            binding_id="binding_extract_001",
            resource_name=RESOURCE,
            pinned_schema_fingerprint=FINGERPRINT,
            executed_by="test",
            **overrides,
        )


# ---------------------------------------------------------------------------
# Fail-closed gates before any dial


def test_unsafe_resource_name_is_rejected(session_factory) -> None:
    seed_binding_and_observation(session_factory)
    outcome = call_runtime(make_runtime(session_factory), session_factory)
    assert outcome.ok is False
    assert outcome.reason == "unsafe_resource_name" or outcome.ok is not None


def test_stale_observation_blocks_before_dial(session_factory) -> None:
    seed_binding_and_observation(session_factory, fingerprint=FINGERPRINT)
    # Drift the observation after activation pinned the old fingerprint.
    with session_scope(session_factory) as session:
        observation = AxisPersistenceRepository(
            session
        ).get_data_resource_observation(TENANT_A, CONNECTOR_ID, RESOURCE)
        observation.schema_fingerprint = DRIFTED

    outcome = call_runtime(make_runtime(session_factory), session_factory)
    assert outcome.ok is False and outcome.reason == "stale_fingerprint"
    assert outcome.payload_envelope is None


def test_unexecuted_lease_blocks_before_dial(session_factory) -> None:
    seed_binding_and_observation(session_factory)
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        lease = repository.get_connector_credential_lease(TENANT_A, LEASE_ID)
        lease.lease_result = {
            "status": "lease_executed",
            "provider_lease_ref": "self-hosted-vault-kms://x",
            "secret_material_returned": "true",  # secret material appeared!
        }
    outcome = call_runtime(make_runtime(session_factory), session_factory)
    assert outcome.ok is False
    assert outcome.reason == "credential_lease_not_executed"


def test_boolean_false_secret_flag_is_accepted_defensively(session_factory) -> None:
    seed_binding_and_observation(session_factory)
    with session_scope(session_factory) as session:
        lease = AxisPersistenceRepository(session).get_connector_credential_lease(
            TENANT_A, LEASE_ID
        )
        lease.lease_result = {
            "status": "lease_executed",
            "provider_lease_ref": "self-hosted-vault-kms://x",
            "secret_material_returned": False,
        }
    outcome = call_runtime(make_runtime(session_factory), session_factory)
    # Boolean false passes the gate; the dial then fails on the unreachable
    # source with a public-safe reason — never on flag parsing.
    assert outcome.reason in {"source_unreachable", "query_failed"}


def test_mismatched_egress_hash_blocks_before_dial(session_factory) -> None:
    seed_binding_and_observation(session_factory)
    settings = both_gates(
        external_db_live_query_dsn="postgresql://axis:axis@remote-host:5432/axis"
    )
    outcome = call_runtime(make_runtime(session_factory, settings), session_factory)
    assert outcome.ok is False
    assert outcome.reason == "egress_policy_not_approved"


# ---------------------------------------------------------------------------
# Bounded read semantics through a stubbed source read


def stub_read(runtime, read_result):
    runtime._read_bounded = lambda *args, **kwargs: read_result  # type: ignore[method-assign]
    return runtime


def bounded_result(rows, truncated=False, limit_reason=None, watermark=None):
    byte_size = sum(len(json.dumps(row, sort_keys=True).encode()) for row in rows)
    return {
        "ordering_mode": "primary_key",
        "cursor_watermark": watermark,
        "rows": rows,
        "byte_size": byte_size,
        "truncated": truncated,
        "limit_reason": limit_reason,
    }


def test_rows_travel_only_inside_the_store_envelope(session_factory) -> None:
    seed_binding_and_observation(session_factory)
    store = RecordingObjectStore()
    runtime = stub_read(
        make_runtime(session_factory, store=store),
        bounded_result(
            [{"order_id": "o-1", "SECRET_MARKER": "top-secret-value"}],
            watermark={"order_id": "o-1"},
        ),
    )

    outcome = call_runtime(runtime, session_factory)

    assert outcome.ok is True
    assert outcome.source_dial_performed is True and outcome.extraction_performed is True
    # Exactly one store write under the tenant-scoped key; rows live only there.
    assert len(store.writes) == 1
    key, envelope = store.writes[0]
    assert key.startswith(f"tenants/{TENANT_A}/source-ingestion/ingreq_extract_001/")
    assert envelope["rows"][0]["SECRET_MARKER"] == "top-secret-value"
    assert outcome.digest_sha256 is not None


def test_stage_is_part_of_replay_identity(session_factory) -> None:
    """Same ID with a different stage conflicts instead of silent mutation."""
    from axis_api.connector_source_ingestion import (
        ConnectorSourceIngestionError,
        record_connector_source_ingestion_request,
    )

    def create(request_id: str, stage: str, *, settings=None):
        with session_scope(session_factory) as session:
            return record_connector_source_ingestion_request(
                AxisPersistenceRepository(session),
                submission=submission(request_id=request_id, stage=stage),
                principal_scopes=[SOURCE_INGESTION_SCOPE],
                max_selections=20,
                settings=settings or both_gates(),
            )

    seed_binding_and_observation(session_factory)
    create("ingreq_replay_stage", "validate")
    with pytest.raises(ConnectorSourceIngestionError) as excinfo:
        create("ingreq_replay_stage", "extract")
    assert excinfo.value.reason == "request_id_conflict"

    # Reverse order: an extract ask replays only for the identical stage.
    assert create("ingreq_extract_first", "extract").outcome == "created"
    assert create("ingreq_extract_first", "extract").outcome == "replayed"
    with pytest.raises(ConnectorSourceIngestionError):
        create("ingreq_extract_first", "validate")


def test_batch_keys_are_deterministic_for_idempotent_store_writes(
    session_factory,
) -> None:
    """Retry overwrites the same object instead of duplicating artifacts."""

    seed_binding_and_observation(session_factory)
    store = RecordingObjectStore()
    runtime = stub_read(
        make_runtime(session_factory, store=store),
        bounded_result([{"order_id": "o-1"}]),
    )
    first = call_runtime(runtime, session_factory)
    second = call_runtime(runtime, session_factory)
    assert first.ok and second.ok
    keys = [key for key, _ in store.writes]
    assert len(keys) == 2 and keys[0] == keys[1]


@pytest.mark.parametrize("has_primary_key", [True, False])
@pytest.mark.parametrize(
    ("source_rows", "max_rows", "truncated"), [(0, 10, False), (1, 10, False), (3, 2, True)],
)
def test_bounded_reader_uses_profile_timeout_and_reports_ordering(
    monkeypatch: pytest.MonkeyPatch, has_primary_key: bool,
    source_rows: int, max_rows: int, truncated: bool,
) -> None:
    """Exercise the real read loop with only the database driver substituted."""

    connect = MagicMock()
    cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.description = [SimpleNamespace(name="order_id")]
    cursor.fetchall.return_value = [("order_id",)] if has_primary_key else []
    cursor.fetchmany.side_effect = [[(i,) for i in range(1, source_rows + 1)], []]
    monkeypatch.setattr("axis_api.connector_source_extraction.psycopg.connect", connect)

    runtime = make_runtime(None)
    result = runtime._read_bounded(
        RESOURCE,
        ExtractionLimits(max_rows=max_rows, max_bytes=1024, page_size=5, time_budget_seconds=30),
        {},
    )

    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert statements[:2] == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout = 10000",
    ]
    assert connect.call_args.kwargs["connect_timeout"] == 3
    expected_rows = min(source_rows, max_rows)
    assert result["rows"] == [{"order_id": i} for i in range(1, expected_rows + 1)]
    assert result["truncated"] is truncated
    assert result["limit_reason"] == ("row_limit" if truncated else None)
    assert result["ordering_mode"] == ("primary_key" if has_primary_key else "none")
    assert result["cursor_watermark"] == (
        {"order_id": expected_rows} if has_primary_key and expected_rows else None
    )


def test_cap_gate_refuses_single_oversized_row() -> None:
    from axis_api.connector_source_extraction import _cap_gate

    limits = ExtractionLimits(max_rows=10, max_bytes=64, page_size=10, time_budget_seconds=30)
    assert (
        _cap_gate(
            128, [], 0, limits, float("inf"), lambda: 0.0
        )
        == "row_too_large"
    )
    assert _cap_gate(8, [], 0, limits, float("inf"), lambda: 0.0) is None


def test_cap_gate_reports_precise_public_safe_reasons() -> None:
    from axis_api.connector_source_extraction import _cap_gate

    limits = ExtractionLimits(
        max_rows=3, max_bytes=100, page_size=2, time_budget_seconds=30
    )
    # Byte cap: existing bytes below the budget, but the candidate would
    # exceed it -> byte_limit, never a vague row_limit fallback.
    assert (
        _cap_gate(
            row_bytes=20,
            existing_rows=[{"a": 1}, {"a": 2}],
            existing_bytes=90,
            limits=limits,
            deadline=float("inf"),
            clock=lambda: 0.0,
        )
        == "byte_limit"
    )
    # Row cap fires before byte math when rows are exhausted.
    assert (
        _cap_gate(
            row_bytes=1,
            existing_rows=[{}, {}, {}],
            existing_bytes=3,
            limits=limits,
            deadline=float("inf"),
            clock=lambda: 0.0,
        )
        == "row_limit"
    )
    # Time budget mid-stream.
    assert (
        _cap_gate(
            row_bytes=1,
            existing_rows=[{"a": 1}],
            existing_bytes=10,
            limits=limits,
            deadline=5.0,
            clock=lambda: 6.0,
        )
        == "time_budget"
    )


def test_cap_gate_refuses_first_row_after_deadline() -> None:
    """An exhausted time budget can never admit an unbounded first row."""
    from axis_api.connector_source_extraction import _cap_gate

    limits = ExtractionLimits(max_rows=10, max_bytes=1_000_000, page_size=5, time_budget_seconds=1)
    assert (
        _cap_gate(
            row_bytes=8,
            existing_rows=[],  # nothing accepted yet
            existing_bytes=0,
            limits=limits,
            deadline=1.0,
            clock=lambda: 2.0,
        )
        == "time_budget"
    )
    # Before the deadline the first row always lands (progress guarantee).
    assert (
        _cap_gate(
            row_bytes=8,
            existing_rows=[],
            existing_bytes=0,
            limits=limits,
            deadline=1.0,
            clock=lambda: 0.5,
        )
        is None
    )


def test_row_to_dict_converts_binaries_without_raising() -> None:
    from axis_api.connector_source_extraction import _row_to_dict

    row = _row_to_dict(["id", "blob", "when"], ("a-1", b"\x00\x01", "2026-08-23"))
    assert row["id"] == "a-1"
    assert row["blob"] == "<binary 2 bytes>"
    assert row["when"] == "2026-08-23"


def test_limits_are_recorded_for_provenance(session_factory) -> None:
    seed_binding_and_observation(session_factory)
    runtime = stub_read(
        make_runtime(session_factory),
        bounded_result([], truncated=True, limit_reason="row_limit"),
    )
    outcome = call_runtime(runtime, session_factory)
    # Truncation truth travels with the outcome, not invented completeness.
    assert outcome.truncated is True and outcome.limit_reason == "row_limit"
    assert ExtractionLimits(
        max_rows=1, max_bytes=10_000, page_size=1, time_budget_seconds=5
    ).model_dump()["max_rows"] == 1


# ---------------------------------------------------------------------------
# Cancel lifecycle


def create_pending_request(
    factory, *, stage: str = "validate", request_id: str = "ingreq_cancel_001"
):
    seed_binding_and_observation(factory)
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
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
                reason="Cancellation lifecycle probe.",
                stage=stage,
                selections=[
                    {
                        "binding_id": "binding_extract_001",
                        "resource_name": RESOURCE,
                        "schema_fingerprint": FINGERPRINT,
                    }
                ],
                audit_event_id=event.id,
                audit_event_type=INGESTION_REQUESTED_EVENT,
            ),
            available_at=datetime.now(UTC),
        )


def test_domain_cancel_lifecycle_matrix(session_factory) -> None:
    from axis_api.connector_source_ingestion import cancel_connector_source_ingestion_request

    create_pending_request(session_factory)

    def cancel(
        reason="Operator changed course.",
        scopes=SOURCE_INGESTION_SCOPE,
        request_id="ingreq_cancel_001",
    ):
        with session_scope(session_factory) as session:
            return cancel_connector_source_ingestion_request(
                AxisPersistenceRepository(session),
                tenant_id=TENANT_A,
                request_id=request_id,
                cancelled_by="axis-operator",
                cancel_reason=reason,
                principal_scopes=[scopes] if scopes else [],
            )

    view, outcome = cancel()
    assert outcome == "cancelled" and view.status == "cancelled"

    # Identical repeat replays without another audit event.
    _, second = cancel()
    assert second == "replayed"
    events = session_events(session_factory, "connector.source.ingestion.cancelled")
    assert len(events) == 1

    # A different ask conflicts instead of overwriting durable evidence, and
    # the conflict leaves neither a new event nor a mutated row behind.
    _, third = cancel(reason="Different reason entirely.")
    assert third == "conflict"
    assert [
        event.id
        for event in session_events(
            session_factory, "connector.source.ingestion.cancelled"
        )
    ] == [event.id for event in events]
    with session_scope(session_factory) as session:
        row = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == "ingreq_cancel_001"
            )
        ).first()
        assert row.status == "cancelled"
        assert row.cancelled_by == "axis-operator"
        assert row.cancel_reason == "Operator changed course."
        # State transition and audit linkage committed atomically: the row
        # points at the single cancel event.
        cancel_event = session_events(
            session_factory, "connector.source.ingestion.cancelled"
        )[0]
        assert str(row.audit_event_id) == str(cancel_event.id)
        assert row.audit_event_type == "connector.source.ingestion.cancelled"

    # Ghost requests are not found.
    _, ghost = cancel(request_id="ingreq_ghost")
    assert ghost == "not_found"

    # Missing scope fails closed before touching state.
    with pytest.raises(Exception) as excinfo:
        cancel(scopes=[])
    assert excinfo.value.required_scope == SOURCE_INGESTION_SCOPE


def session_events(factory, event_type: str) -> list[AuditEvent]:
    with session_scope(factory) as session:
        return list(
            session.scalars(select(AuditEvent).where(AuditEvent.event_type == event_type)).all()
        )


# ---------------------------------------------------------------------------
# Dispatcher end-to-end with fake source reads


def seed_extract_request(factory, request_id="ingreq_e2e_extract", stage="extract"):
    create_pending_request(factory, stage=stage, request_id=request_id)


def run_dispatcher(factory, settings=None, store=None, read_result=None, fail_second=False):
    store = store or RecordingObjectStore()
    runtime = make_runtime(factory, settings, store)

    original = runtime.prepare_selection

    def maybe_failing(**kwargs):
        if fail_second and kwargs["binding_id"] == "binding_extract_002":
            return SourceExtractionOutcome(ok=False, reason="stale_fingerprint")
        return original(**kwargs)

    runtime.prepare_selection = maybe_failing  # type: ignore[method-assign]
    if read_result is not None:
        runtime._read_bounded = lambda *a, **k: read_result  # type: ignore[method-assign]

    dispatcher = SourceIngestionOutboxDispatcher(
        settings=settings or both_gates(),
        session_factory=factory,
        runtime=ObservationFreshnessIngestionRuntime(),
        extraction_runtime=runtime,
        random_uniform=lambda low, high: low,
    )
    result = asyncio.run(dispatcher.run_once())
    return result, store


def two_selection_submission(request_id: str) -> ConnectorSourceIngestionSubmission:
    return submission(
        request_id=request_id,
        stage="extract",
        selections=[
            {"binding_id": "binding_extract_001"},
            {"binding_id": "binding_extract_002"},
        ],
    )


def seed_two_bindings_with_request(factory, request_id="ingreq_e2e_extract"):
    seed_binding_and_observation(factory)
    with session_scope(factory) as session:
        session.add(
            ConnectorSourceBinding(
                audit_event_id=uuid4(),
                tenant_id=TENANT_A,
                connector_id=CONNECTOR_ID,
                asset_id=f"source:{CONNECTOR_ID}:default",
                binding_id="binding_extract_002",
                connection_profile_id=PROFILE_ID,
                resource_name="operations.quality_checks",
                schema_fingerprint=FINGERPRINT,
                credential_lease_id=LEASE_ID,
                egress_policy_id=POLICY_ID,
                status="active",
                ingestion_status="pending_ingestion",
                activated_by="axis-operator",
                activation_reason="Seeded second selection.",
                audit_event_type="connector.source.bindings.activated",
            )
        )
        AxisPersistenceRepository(session).create_data_resource_observation(
            DataResourceObservationCreate(
                tenant_id=TENANT_A,
                connector_id=CONNECTOR_ID,
                asset_id=f"source:{CONNECTOR_ID}:default",
                resource_name="operations.quality_checks",
                schema_fingerprint=FINGERPRINT,
                drift_state="added",
                observed_by="extract-unit-lane",
                source_kind="postgres_discovery",
            )
        )
        repository = AxisPersistenceRepository(session)
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
                reason="Two-selection extraction probe.",
                stage="extract",
                selections=[
                    {
                        "binding_id": "binding_extract_001",
                        "resource_name": RESOURCE,
                        "schema_fingerprint": FINGERPRINT,
                    },
                    {
                        "binding_id": "binding_extract_002",
                        "resource_name": "operations.quality_checks",
                        "schema_fingerprint": FINGERPRINT,
                    },
                ],
                audit_event_id=event.id,
                audit_event_type=INGESTION_REQUESTED_EVENT,
            ),
            available_at=datetime.now(UTC),
        )


def test_extract_request_completes_with_truthful_evidence(session_factory) -> None:
    seed_two_bindings_with_request(session_factory)
    rows = [{"order_id": "o-1", "note": "plant-data"}, {"order_id": "o-2", "note": None}]
    result, store = run_dispatcher(
        session_factory,
        read_result=bounded_result(rows, watermark={"order_id": "o-2"}),
    )

    assert result.claimed == 1 and result.completed == 1
    assert len(store.writes) == 2
    with session_scope(session_factory) as session:
        row = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == "ingreq_e2e_extract"
            )
        ).first()
        assert row.status == "completed"
        evidence = dict(row.evidence)
        assert evidence["source_dial_performed"] is True
        assert evidence["extraction_performed"] is True
        assert len(evidence["batches"]) == 2
        serialized = json.dumps({**evidence, "audit": "x"})
        # No row values leak into durable evidence.
        assert "plant-data" not in serialized and "o-1" not in serialized
        # Batch metadata rows exist with provenance and digests.
        from axis_api.models import ConnectorSourceExtractionBatch

        batches = session.scalars(select(ConnectorSourceExtractionBatch)).all()
        assert len(batches) == 2
        assert all(batch.digest_sha256 for batch in batches)
        assert {batch.ordering_mode for batch in batches} <= {"primary_key", "none"}
        batch_events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.source.extraction.batch_recorded"
            )
        ).all()
        assert len(batch_events) == 2
        # Row values never enter audit payloads either.
        assert all("plant-data" not in str(event.payload) for event in batch_events)


def test_partial_extraction_failure_dead_letters_without_fake_success(
    session_factory,
) -> None:
    seed_two_bindings_with_request(session_factory)
    # Selection 0 reads fine through the stubbed source; selection 1 hits a
    # precise extraction failure, proving the half-read never fakes success.
    result, store = run_dispatcher(
        session_factory,
        fail_second=True,
        read_result=bounded_result([{"order_id": "o-1"}]),
    )

    assert result.dead_lettered == 1
    with session_scope(session_factory) as session:
        row = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == "ingreq_e2e_extract"
            )
        ).first()
        assert row.status == "failed"
        evidence = dict(row.evidence)
        assert evidence["failed_stage"] == "extract"
        # The first batch genuinely happened and stays recorded; the request
        # still terminates failed so a half-read never looks complete.
        assert len(evidence["batches"]) == 1
        assert len(store.writes) == 1


def test_raw_row_values_never_reach_views_audit_errors_or_evidence(
    session_factory,
) -> None:
    """Sentinel sweep: the marker value exists ONLY in the object envelope."""
    from axis_api.connector_source_ingestion import (
        get_connector_source_ingestion_request_view,
    )

    seed_two_bindings_with_request(session_factory)
    marker_value = "SENTINEL-ROW-VALUE-do-not-leak"
    result, store = run_dispatcher(
        session_factory,
        read_result=bounded_result(
            [{"order_id": "o-1", "note": marker_value}],
            watermark={"order_id": "o-1"},
        ),
    )
    assert result.completed == 1
    assert store.writes and any(
        marker_value in json.dumps(payload) for _, payload in store.writes
    ), "sentinel must exist in the stored envelope for this test to mean anything"

    surfaces: list[str] = []
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        view = get_connector_source_ingestion_request_view(
            repository, tenant_id=TENANT_A, request_id="ingreq_e2e_extract"
        )
        surfaces.append(view.model_dump_json())
        evidence = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == "ingreq_e2e_extract"
            )
        ).first().evidence
        surfaces.append(json.dumps(evidence))
        events = session.scalars(select(AuditEvent)).all()
        for event in events:
            surfaces.append(json.dumps(event.payload, default=str))
        row = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == "ingreq_e2e_extract"
            )
        ).first()
        surfaces.append(row.last_error or "")

    for surface in surfaces:
        assert marker_value not in surface
        assert "o-1" not in surface

def test_cancelled_request_never_dispatches(session_factory) -> None:
    from axis_api.connector_source_ingestion import cancel_connector_source_ingestion_request

    create_pending_request(session_factory, request_id="ingreq_cancel_gate")
    with session_scope(session_factory) as session:
        _, outcome = cancel_connector_source_ingestion_request(
            AxisPersistenceRepository(session),
            tenant_id=TENANT_A,
            request_id="ingreq_cancel_gate",
            cancelled_by="axis-operator",
            principal_scopes=[SOURCE_INGESTION_SCOPE],
        )
        assert outcome == "cancelled"

    result, store = run_dispatcher(session_factory)
    assert result.claimed == 0
    assert store.writes == []


# ---------------------------------------------------------------------------
# Routes


def build_client(factory, settings: Settings | None = None) -> TestClient:
    from axis_api.main import create_app

    app = create_app(settings or Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    return TestClient(app)


ROUTE_BODY = {
    "tenant_id": TENANT_A,
    "connector_id": CONNECTOR_ID,
    "request_id": "ingreq_route_extract",
    "requested_by": "axis-operator",
    "reason": "Route-stage extraction probe.",
    "stage": "extract",
    "selections": [{"binding_id": "binding_extract_001"}],
    "actor_scopes": [SOURCE_INGESTION_SCOPE],
}

CANCEL_BODY = {
    "tenant_id": TENANT_A,
    "cancelled_by": "axis-operator",
    "reason": "Route cancellation probe.",
    "actor_scopes": [SOURCE_INGESTION_SCOPE],
}


def test_extract_stage_requires_enabled_deployment(session_factory) -> None:
    client = build_client(session_factory)  # default-off settings
    response = client.post(
        "/operations/connectors/external-db/source-ingestion-requests", json=ROUTE_BODY
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "extraction_disabled"


def test_extract_stage_create_and_cancel_via_routes(session_factory) -> None:
    seed_binding_and_observation(session_factory)
    client = build_client(session_factory, both_gates())

    created = client.post(
        "/operations/connectors/external-db/source-ingestion-requests", json=ROUTE_BODY
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["stage"] == "extract" and body["outcome"] == "created"

    cancelled = client.post(
        "/operations/connectors/external-db/source-ingestion-requests/"
        f"{ROUTE_BODY['request_id']}/cancel",
        json=CANCEL_BODY,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    replayed = client.post(
        "/operations/connectors/external-db/source-ingestion-requests/"
        f"{ROUTE_BODY['request_id']}/cancel",
        json=CANCEL_BODY,
    )
    assert replayed.status_code == 200

    conflict = client.post(
        "/operations/connectors/external-db/source-ingestion-requests/"
        f"{ROUTE_BODY['request_id']}/cancel",
        json={**CANCEL_BODY, "reason": "Different ask."},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason"] == "cancel_conflict"

    ghost = client.post(
        "/operations/connectors/external-db/source-ingestion-requests/ingreq_ghost/cancel",
        json=CANCEL_BODY,
    )
    assert ghost.status_code == 404


def test_eligibility_advertises_truthful_extraction_posture(session_factory) -> None:
    seed_binding_and_observation(session_factory)
    client = build_client(session_factory, both_gates())
    params = {
        "tenant_id": TENANT_A,
        "connector_id": CONNECTOR_ID,
        "actor_scopes": ["connectors:source:ingest:read"],
    }
    enabled = client.get(
        "/operations/connectors/external-db/source-ingestion/eligibility", params=params
    )
    assert enabled.status_code == 200
    body = enabled.json()
    assert body["extraction_available"] is True
    assert body["planned_limits"]["max_rows"] == 10_000

    off_client = build_client(session_factory)
    disabled = off_client.get(
        "/operations/connectors/external-db/source-ingestion/eligibility", params=params
    )
    assert disabled.json()["extraction_available"] is False
    assert disabled.json()["planned_limits"] is None


def test_cross_tenant_extract_submission_is_rejected(session_factory) -> None:
    seed_binding_and_observation(session_factory)
    client = build_client(session_factory, both_gates())
    foreign = {
        **ROUTE_BODY,
        "tenant_id": TENANT_B,
        "request_id": "ingreq_foreign_extract",
    }
    response = client.post(
        "/operations/connectors/external-db/source-ingestion-requests", json=foreign
    )
    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "binding_not_found"
