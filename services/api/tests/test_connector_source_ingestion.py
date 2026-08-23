"""Governed source ingestion requests: unit and route contracts on SQLite.

Covers the full operator-facing matrix — eligibility labelling, tenant
isolation, RBAC scopes, reason bounds, selection hygiene, replay/mismatch
idempotency, stale-fingerprint fail-closed at both create and dispatch, audit
hygiene, public-safe errors — plus the dispatch machinery's claim fencing,
lease recovery, retry backoff, and dead-letter semantics, all deterministic
via injected clock randomness.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.audit import AuditEventCreate
from axis_api.config import Settings
from axis_api.connector_source_ingestion import (
    BINDING_PENDING_INGESTION_STATUS,
    INGESTION_COMPLETED_EVENT,
    INGESTION_FAILED_EVENT,
    INGESTION_REQUESTED_EVENT,
    MAX_ATTEMPT_TIMELINE_ENTRIES,
    SOURCE_INGESTION_READ_SCOPE,
    SOURCE_INGESTION_SCOPE,
    ConnectorSourceIngestionError,
    ConnectorSourceIngestionSubmission,
    ObservationFreshnessIngestionRuntime,
    SourceIngestionOutboxDispatcher,
    SourceIngestionScopeDenied,
    SourceIngestionValidationOutcome,
    get_connector_source_ingestion_request_view,
    list_connector_source_ingestion_request_views,
    max_source_ingestion_selections,
    preview_source_ingestion_eligibility,
    record_connector_source_ingestion_request,
)
from axis_api.db import session_scope
from axis_api.models import (
    AuditEvent,
    Base,
    ConnectorSourceBinding,
    ConnectorSourceIngestionRequest,
)
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorSourceIngestionRequestCreate,
    DataResourceObservationCreate,
    TenantCreate,
)

TENANT_A = "tenant_demo_manufacturing"
TENANT_B = "tenant_other_plant"
CONNECTOR_ID = "external_db_operational_mirror"
FINGERPRINT_A = "a" * 64
FINGERPRINT_B = "b" * 64
RESOURCE_1 = "operations.production_orders"
RESOURCE_2 = "operations.quality_checks"


def submission(**overrides) -> ConnectorSourceIngestionSubmission:
    payload = {
        "tenant_id": TENANT_A,
        "connector_id": CONNECTOR_ID,
        "request_id": "ingest_unit_001",
        "requested_by": "axis-operator",
        "reason": "Validate bound plant tables before extraction design review.",
        "selections": [{"binding_id": "binding_unit_001"}],
        "actor_scopes": [SOURCE_INGESTION_SCOPE],
    }
    payload.update(overrides)
    return ConnectorSourceIngestionSubmission(**payload)


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
        AxisPersistenceRepository(session).create_tenant(
            TenantCreate(
                tenant_id=TENANT_A,
                display_name="Ravenna Works",
                description="Plant Operations Cockpit",
                created_by="test",
            )
        )
        AxisPersistenceRepository(session).create_tenant(
            TenantCreate(
                tenant_id=TENANT_B,
                display_name="Other Plant",
                description="Isolation probe",
                created_by="test",
            )
        )
    yield factory
    engine.dispose()


def seed_binding(
    factory,
    binding_id: str,
    resource_name: str,
    fingerprint: str,
    *,
    tenant_id: str = TENANT_A,
) -> None:
    with session_scope(factory) as session:
        session.add(
            ConnectorSourceBinding(
                audit_event_id=uuid4(),
                tenant_id=tenant_id,
                connector_id=CONNECTOR_ID,
                asset_id=f"source:{CONNECTOR_ID}:default",
                binding_id=binding_id,
                connection_profile_id="profile_postgres_discovery_readonly",
                resource_name=resource_name,
                schema_fingerprint=fingerprint,
                credential_lease_id="lease_seed_001",
                egress_policy_id="egress_policy_seed_001",
                status="active",
                ingestion_status=BINDING_PENDING_INGESTION_STATUS,
                activated_by="axis-operator",
                activation_reason="Seeded by ingestion unit tests.",
                audit_event_type="connector.source.bindings.activated",
            )
        )


def seed_observation(
    factory,
    resource_name: str,
    fingerprint: str,
    *,
    tenant_id: str = TENANT_A,
) -> None:
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).create_data_resource_observation(
            DataResourceObservationCreate(
                tenant_id=tenant_id,
                connector_id=CONNECTOR_ID,
                asset_id=f"source:{CONNECTOR_ID}:default",
                resource_name=resource_name,
                schema_fingerprint=fingerprint,
                drift_state="added",
                observed_by="ingest-unit-lane",
                source_kind="postgres_discovery",
            )
        )


def drift_observation(factory, resource_name: str, new_fingerprint: str) -> None:
    """Simulate a later discovery run observing changed schema evidence."""

    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        observation = repository.get_data_resource_observation(
            TENANT_A, CONNECTOR_ID, resource_name
        )
        observation.schema_fingerprint = new_fingerprint


def ingest(factory, sub: ConnectorSourceIngestionSubmission, **kwargs):
    with session_scope(factory) as session:
        return record_connector_source_ingestion_request(
            AxisPersistenceRepository(session),
            submission=sub,
            **{
                "principal_scopes": [SOURCE_INGESTION_SCOPE],
                "max_selections": 20,
                **kwargs,
            },
        )


def request_rows(factory) -> list[ConnectorSourceIngestionRequest]:
    with session_scope(factory) as session:
        return list(session.scalars(select(ConnectorSourceIngestionRequest)).all())


def audit_events(factory, event_type: str) -> list[AuditEvent]:
    with session_scope(factory) as session:
        return list(
            session.scalars(select(AuditEvent).where(AuditEvent.event_type == event_type)).all()
        )


def make_dispatcher(
    factory,
    *,
    runtime=None,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> SourceIngestionOutboxDispatcher:
    clock_now = now or datetime.now(UTC)
    return SourceIngestionOutboxDispatcher(
        settings=settings or Settings(),
        session_factory=factory,
        runtime=runtime or ObservationFreshnessIngestionRuntime(),
        clock=lambda: clock_now,
        random_uniform=lambda low, high: low,
    )


def dispatch(dispatcher) -> object:
    return asyncio.run(dispatcher.run_once())


# ---------------------------------------------------------------------------
# Eligibility


def test_eligibility_labels_are_honest_per_binding(session_factory) -> None:
    seed_binding(session_factory, "binding_ok", RESOURCE_1, FINGERPRINT_A)
    seed_binding(session_factory, "binding_stale", RESOURCE_2, FINGERPRINT_B)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_2, FINGERPRINT_A)  # drifted

    with session_scope(session_factory) as session:
        rows = preview_source_ingestion_eligibility(
            AxisPersistenceRepository(session),
            tenant_id=TENANT_A,
            connector_id=CONNECTOR_ID,
        )

    by_id = {row.binding_id: row for row in rows}
    assert by_id["binding_ok"].eligible is True
    assert by_id["binding_ok"].blocked_reason is None
    assert by_id["binding_stale"].eligible is False
    assert by_id["binding_stale"].blocked_reason == "stale_fingerprint"


def test_eligibility_is_scoped_to_tenant_and_connector(session_factory) -> None:
    seed_binding(session_factory, "binding_other", RESOURCE_1, FINGERPRINT_A, tenant_id=TENANT_B)
    with session_scope(session_factory) as session:
        rows = preview_source_ingestion_eligibility(
            AxisPersistenceRepository(session),
            tenant_id=TENANT_A,
            connector_id=CONNECTOR_ID,
        )
    assert rows == []


# ---------------------------------------------------------------------------
# Creation gates


def test_create_requires_write_scope(session_factory) -> None:
    seed_binding(session_factory, "binding_unit_001", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    with pytest.raises(SourceIngestionScopeDenied) as excinfo:
        ingest(session_factory, submission(), principal_scopes=[SOURCE_INGESTION_READ_SCOPE])
    assert excinfo.value.required_scope == SOURCE_INGESTION_SCOPE


def test_create_pins_server_side_fingerprints_and_audits_ids_only(
    session_factory,
) -> None:
    seed_binding(session_factory, "binding_unit_001", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)

    view = ingest(session_factory, submission(request_id="ingest_pin_001"))

    assert view.outcome == "created"
    assert view.status == "pending"
    assert view.selections[0].schema_fingerprint == FINGERPRINT_A
    events = audit_events(session_factory, INGESTION_REQUESTED_EVENT)
    assert len(events) == 1
    serialized = str(events[0].payload)
    # Evidence carries IDs and counts only: never lease handles, DSNs, secrets.
    assert "lease" not in serialized and "dsn" not in serialized.lower()
    assert "password" not in serialized.lower()


def test_replay_is_deterministic_without_duplicate_audit(session_factory) -> None:
    seed_binding(session_factory, "binding_unit_001", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    first = ingest(session_factory, submission())
    second = ingest(session_factory, submission())

    assert first.outcome == "created"
    assert second.outcome == "replayed"
    assert second.request_id == first.request_id
    assert len(audit_events(session_factory, INGESTION_REQUESTED_EVENT)) == 1


def test_replay_survives_post_request_drift_without_refreshing_evidence(
    session_factory,
) -> None:
    """Identity-based replay: drift after creation never mutes the replay."""

    seed_binding(session_factory, "binding_unit_001", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    ingest(session_factory, submission())
    drift_observation(session_factory, RESOURCE_1, FINGERPRINT_B)

    replayed = ingest(session_factory, submission())
    assert replayed.outcome == "replayed"
    assert replayed.selections[0].schema_fingerprint == FINGERPRINT_A


def test_racing_insert_rolls_back_duplicate_audit_and_replays(session_factory) -> None:
    """The IntegrityError loser must not leave a second `requested` event.

    Simulates losing the (tenant_id, request_id) insert race: the lookup saw
    nothing, our savepoint appended audit + attempted the insert, and the
    constraint rejected it because another transaction committed first.
    """

    from sqlalchemy.exc import IntegrityError as SAIntegrityError

    seed_binding(session_factory, "binding_unit_001", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)

    # Racer one wins normally.
    ingest(session_factory, submission())

    class RacingRepository:
        """Real repo whose request lookup misses once, then finds the row."""

        def __init__(self, inner):
            self._inner = inner
            self.lookups = 0

        def get_connector_source_ingestion_request(self, tenant_id, request_id):
            self.lookups += 1
            if self.lookups == 1:
                return None  # raced window: not yet visible to this txn
            return self._inner.get_connector_source_ingestion_request(tenant_id, request_id)

        def get_connector_source_binding(self, tenant_id, binding_id):
            return self._inner.get_connector_source_binding(tenant_id, binding_id)

        def get_data_resource_observation(self, tenant_id, connector_id, resource_name):
            return self._inner.get_data_resource_observation(tenant_id, connector_id, resource_name)

        def append_audit_event(self, *args, **kwargs):
            return self._inner.append_audit_event(*args, **kwargs)

        @property
        def session(self):
            return self._inner.session

        def create_connector_source_ingestion_request(self, record, *, available_at):
            # The constraint fires AFTER our audit append sits in the savepoint.
            raise SAIntegrityError("INSERT failed", {}, Exception("uq_tenant_request"))

    with session_scope(session_factory) as session:
        racing = RacingRepository(AxisPersistenceRepository(session))
        view = record_connector_source_ingestion_request(
            racing,
            submission=submission(),
            principal_scopes=[SOURCE_INGESTION_SCOPE],
            max_selections=20,
        )

    assert view.outcome == "replayed"
    # Exactly one durable audit event for this request: the loser's copy was
    # rolled back with the savepoint instead of committing a duplicate.
    events = audit_events(session_factory, INGESTION_REQUESTED_EVENT)
    assert len(events) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"reason": "A completely different governance reason."},
        {"selections": [{"binding_id": "binding_unit_002"}]},
    ],
)
def test_request_id_mismatch_conflicts(session_factory, overrides) -> None:
    seed_binding(session_factory, "binding_unit_001", RESOURCE_1, FINGERPRINT_A)
    seed_binding(session_factory, "binding_unit_002", RESOURCE_2, FINGERPRINT_B)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_2, FINGERPRINT_B)
    ingest(session_factory, submission())
    with pytest.raises(ConnectorSourceIngestionError) as excinfo:
        ingest(session_factory, submission(**overrides))
    assert excinfo.value.reason == "request_id_conflict"


def test_cross_tenant_submission_cannot_see_foreign_bindings(session_factory) -> None:
    seed_binding(session_factory, "binding_unit_001", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    foreign = submission(tenant_id=TENANT_B)
    with pytest.raises(ConnectorSourceIngestionError) as excinfo:
        ingest(session_factory, foreign)
    assert excinfo.value.reason == "binding_not_found"
    assert request_rows(session_factory) == []


def test_unknown_inactive_and_not_pending_bindings_fail_closed(session_factory) -> None:
    class StubRepository:
        def __init__(self, binding):
            self._binding = binding

        def get_connector_source_binding(self, tenant_id, binding_id):
            return self._binding

        def get_connector_source_ingestion_request(self, tenant_id, request_id):
            return None

        def get_data_resource_observation(self, tenant_id, connector_id, resource_name):
            return SimpleNamespace(schema_fingerprint=FINGERPRINT_A)

    base_binding = {
        "connector_id": CONNECTOR_ID,
        "binding_id": "binding_x",
        "resource_name": RESOURCE_1,
        "schema_fingerprint": FINGERPRINT_A,
        "status": "active",
        "ingestion_status": BINDING_PENDING_INGESTION_STATUS,
    }

    with pytest.raises(ConnectorSourceIngestionError) as excinfo:
        record_connector_source_ingestion_request(
            StubRepository(None),
            submission=submission(),
            principal_scopes=[SOURCE_INGESTION_SCOPE],
            max_selections=20,
        )
    assert excinfo.value.reason == "binding_not_found"

    inactive = SimpleNamespace(**base_binding)
    inactive.status = "revoked"
    with pytest.raises(ConnectorSourceIngestionError) as excinfo:
        record_connector_source_ingestion_request(
            StubRepository(inactive),
            submission=submission(selections=[{"binding_id": "binding_x"}]),
            principal_scopes=[SOURCE_INGESTION_SCOPE],
            max_selections=20,
        )
    assert excinfo.value.reason == "binding_inactive"

    consumed = SimpleNamespace(**base_binding)
    consumed.ingestion_status = "ingested"
    with pytest.raises(ConnectorSourceIngestionError) as excinfo:
        record_connector_source_ingestion_request(
            StubRepository(consumed),
            submission=submission(selections=[{"binding_id": "binding_x"}]),
            principal_scopes=[SOURCE_INGESTION_SCOPE],
            max_selections=20,
        )
    assert excinfo.value.reason == "binding_not_pending_ingestion"


def test_stale_fingerprint_at_create_is_rejected_before_writes(session_factory) -> None:
    seed_binding(session_factory, "binding_unit_001", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_B)  # drifted post-activation

    with pytest.raises(ConnectorSourceIngestionError) as excinfo:
        ingest(session_factory, submission())
    assert excinfo.value.reason == "stale_fingerprint"
    assert request_rows(session_factory) == []
    assert audit_events(session_factory, INGESTION_REQUESTED_EVENT) == []


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"selections": []}, None),
        (
            {"selections": [{"binding_id": "binding_a"}, {"binding_id": "binding_a"}]},
            "duplicate_binding_id",
        ),
    ],
)
def test_empty_and_duplicate_selections_fail_closed(
    session_factory, overrides, expected_reason
) -> None:
    if expected_reason is None:
        with pytest.raises(ValidationError):
            submission(**overrides)
        return
    seed_binding(session_factory, "binding_a", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    with pytest.raises(ConnectorSourceIngestionError) as excinfo:
        ingest(session_factory, submission(**overrides))
    assert excinfo.value.reason == expected_reason


def test_oversized_selections_exceeding_bound_fail_closed(session_factory) -> None:
    oversized = submission(
        selections=[
            {"binding_id": f"binding_{index}"} for index in range(21)
        ]
    )
    with pytest.raises(ConnectorSourceIngestionError) as excinfo:
        ingest(
            session_factory,
            oversized,
            max_selections=max_source_ingestion_selections(Settings()),
        )
    assert excinfo.value.reason == "selection_too_large"


@pytest.mark.parametrize(
    "reason",
    ["", "x" * 601],
)
def test_reason_is_required_and_bounded(reason) -> None:
    with pytest.raises(ValidationError):
        submission(reason=reason)


# ---------------------------------------------------------------------------
# Views


def test_get_list_views_and_not_found(session_factory) -> None:
    seed_binding(session_factory, "binding_unit_001", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    ingest(session_factory, submission())

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        found = get_connector_source_ingestion_request_view(
            repository, tenant_id=TENANT_A, request_id="ingest_unit_001"
        )
        assert found is not None and found.request_id == "ingest_unit_001"
        assert get_connector_source_ingestion_request_view(
            repository, tenant_id=TENANT_A, request_id="ingest_ghost"
        ) is None
        listed = list_connector_source_ingestion_request_views(
            repository, tenant_id=TENANT_A, connector_id=CONNECTOR_ID
        )
        assert [view.request_id for view in listed] == ["ingest_unit_001"]
        # Tenant isolation: another tenant's listing stays empty.
        assert (
            list_connector_source_ingestion_request_views(
                repository, tenant_id=TENANT_B, connector_id=CONNECTOR_ID
            )
            == []
        )


# ---------------------------------------------------------------------------
# Dispatch machinery


def dispatch_settings(max_attempts: int = 3) -> Settings:
    return Settings(
        source_ingestion_retry_base_seconds=2,
        source_ingestion_retry_max_seconds=2,
        source_ingestion_max_attempts=max_attempts,
    )


def create_dispatchable_request(
    factory,
    request_id: str,
    binding_id: str,
    resource_name: str,
    fingerprint: str,
) -> None:
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=TENANT_A,
                actor_id="axis-operator",
                event_type=INGESTION_REQUESTED_EVENT,
                payload={"request_id": request_id, "connector_id": CONNECTOR_ID},
            )
        )
        repository.create_connector_source_ingestion_request(
            ConnectorSourceIngestionRequestCreate(
                tenant_id=TENANT_A,
                connector_id=CONNECTOR_ID,
                request_id=request_id,
                requested_by="axis-operator",
                reason="Dispatch fixture.",
                selections=[
                    {
                        "binding_id": binding_id,
                        "resource_name": resource_name,
                        "schema_fingerprint": fingerprint,
                    }
                ],
                audit_event_id=event.id,
                audit_event_type=INGESTION_REQUESTED_EVENT,
            ),
            available_at=datetime.now(UTC),
        )


class RaisingRuntime:
    """Operational failure surrogate: the boundary itself blew up."""

    def validate_selection(self, **kwargs) -> SourceIngestionValidationOutcome:
        raise RuntimeError("connection pool exhausted while validating")


def test_retry_backoff_grows_exponentially_then_caps() -> None:
    dispatcher = make_dispatcher(object())
    # random_uniform(low, high) -> high samples the top of each window.
    dispatcher._random_uniform = lambda low, high: high
    assert dispatcher._retry_delay(1).total_seconds() == 2  # base
    assert dispatcher._retry_delay(2).total_seconds() == 4  # base * 2
    assert dispatcher._retry_delay(9).total_seconds() == 60  # capped at max


def test_dispatcher_completes_fresh_requests_with_truthful_evidence(
    session_factory,
) -> None:
    seed_binding(session_factory, "binding_ok", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_001", "binding_ok", RESOURCE_1, FINGERPRINT_A
    )

    result = dispatch(make_dispatcher(session_factory))

    assert result.claimed == 1 and result.completed == 1
    row = request_rows(session_factory)[0]
    assert row.status == "completed" and row.completed_at is not None
    evidence = dict(row.evidence)
    assert evidence["stage"] == "validation"
    assert evidence["source_dial_performed"] is False
    assert evidence["extraction_performed"] is False
    assert evidence["validated_count"] == 1
    completed_events = audit_events(session_factory, INGESTION_COMPLETED_EVENT)
    assert len(completed_events) == 1
    assert completed_events[0].actor_id == "axis-source-ingestion-outbox"


def test_stale_fingerprint_at_dispatch_dead_letters_permanently(session_factory) -> None:
    seed_binding(session_factory, "binding_drift", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_002", "binding_drift", RESOURCE_1, FINGERPRINT_A
    )
    drift_observation(session_factory, RESOURCE_1, FINGERPRINT_B)

    result = dispatch(make_dispatcher(session_factory))

    assert result.dead_lettered == 1
    row = request_rows(session_factory)[0]
    assert row.status == "failed"
    assert row.dead_lettered_at is not None
    assert "stale_fingerprint" in (row.last_error or "")
    evidence = dict(row.evidence)
    assert evidence["failed_count"] == 1
    dead_events = audit_events(session_factory, INGESTION_FAILED_EVENT)
    assert len(dead_events) == 1
    # A dead-lettered request is never claimed again.
    again = dispatch(make_dispatcher(session_factory))
    assert again.claimed == 0


def test_operational_failure_retries_then_dead_letters_when_exhausted(
    session_factory,
) -> None:
    seed_binding(session_factory, "binding_op", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_003", "binding_op", RESOURCE_1, FINGERPRINT_A
    )
    dispatcher = make_dispatcher(
        session_factory, runtime=RaisingRuntime(), settings=dispatch_settings(max_attempts=2)
    )

    first = dispatch(dispatcher)
    assert first.retried == 1
    row = request_rows(session_factory)[0]
    assert row.status == "pending"
    assert row.attempt_count == 1
    assert row.dead_lettered_at is None
    assert row.last_error == "RuntimeError"

    second = dispatch(dispatcher)
    assert second.dead_lettered == 1
    row = request_rows(session_factory)[0]
    assert row.status == "failed"
    assert row.attempt_count == 2
    assert row.dead_lettered_at is not None


def test_claim_fencing_blocks_stale_tokens_and_double_claims(session_factory) -> None:
    seed_binding(session_factory, "binding_fence", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_004", "binding_fence", RESOURCE_1, FINGERPRINT_A
    )
    now = datetime.now(UTC)

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        claimed = repository.claim_connector_source_ingestion_requests(
            now=now,
            lease_expires_at=now + timedelta(seconds=120),
            limit=10,
        )
        assert len(claimed) == 1
        token = claimed[0].claim_token
        # While the lease is valid, nobody else can claim the same row.
        assert (
            repository.claim_connector_source_ingestion_requests(
                now=now, lease_expires_at=now + timedelta(seconds=120), limit=10
            )
            == []
        )
        # A stale token can never finalize state.
        assert (
            repository.complete_connector_source_ingestion_request(
                claimed[0].id,
                uuid4(),
                completed_at=now,
                evidence={"stage": "validation"},
            )
            is False
        )
        # The rightful token finalizes exactly once.
        assert (
            repository.complete_connector_source_ingestion_request(
                claimed[0].id,
                token,
                completed_at=now,
                evidence={"stage": "validation"},
            )
            is True
        )
        assert (
            repository.complete_connector_source_ingestion_request(
                claimed[0].id,
                token,
                completed_at=now,
                evidence={"stage": "validation"},
            )
            is False
        )


def test_expired_lease_is_recovered_by_the_next_claim(session_factory) -> None:
    seed_binding(session_factory, "binding_lease", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_005", "binding_lease", RESOURCE_1, FINGERPRINT_A
    )
    now = datetime.now(UTC)

    # Simulate a worker that claimed and died mid-flight: the row is stranded
    # in `dispatching` with an expired lease and an orphaned claim token.
    with session_scope(session_factory) as session:
        row = session.scalars(select(ConnectorSourceIngestionRequest)).first()
        row.status = "dispatching"
        row.attempt_count = 1
        row.claim_token = row.id  # any stable UUID-shaped token
        row.lease_expires_at = now - timedelta(seconds=5)

    recovered = dispatch(make_dispatcher(session_factory))
    assert recovered.claimed == 1
    assert recovered.completed == 1
    row = request_rows(session_factory)[0]
    assert row.status == "completed"
    assert row.attempt_count == 2


def test_validation_stage_runtime_port_contract() -> None:
    fresh = SimpleNamespace(
        schema_fingerprint=FINGERPRINT_A,
    )
    active_binding = SimpleNamespace(status="active")

    class StubRepository:
        def __init__(self, observation, binding):
            self._observation = observation
            self._binding = binding

        def get_data_resource_observation(self, tenant_id, connector_id, resource_name):
            return self._observation

        def get_connector_source_binding(self, tenant_id, binding_id):
            return self._binding

    runtime = ObservationFreshnessIngestionRuntime()

    ok = runtime.validate_selection(
        repository=StubRepository(fresh, active_binding),
        tenant_id=TENANT_A,
        connector_id=CONNECTOR_ID,
        binding_id="binding_x",
        resource_name=RESOURCE_1,
        schema_fingerprint=FINGERPRINT_A,
    )
    assert ok.ok and ok.source_dial_performed is False and ok.extraction_performed is False

    stale = runtime.validate_selection(
        repository=StubRepository(
            SimpleNamespace(schema_fingerprint=FINGERPRINT_B), active_binding
        ),
        tenant_id=TENANT_A,
        connector_id=CONNECTOR_ID,
        binding_id="binding_x",
        resource_name=RESOURCE_1,
        schema_fingerprint=FINGERPRINT_A,
    )
    assert stale.ok is False and stale.reason == "stale_fingerprint"

    missing = runtime.validate_selection(
        repository=StubRepository(None, active_binding),
        tenant_id=TENANT_A,
        connector_id=CONNECTOR_ID,
        binding_id="binding_x",
        resource_name=RESOURCE_1,
        schema_fingerprint=FINGERPRINT_A,
    )
    assert missing.ok is False and missing.reason == "observation_missing"

    inactive = runtime.validate_selection(
        repository=StubRepository(fresh, SimpleNamespace(status="revoked")),
        tenant_id=TENANT_A,
        connector_id=CONNECTOR_ID,
        binding_id="binding_x",
        resource_name=RESOURCE_1,
        schema_fingerprint=FINGERPRINT_A,
    )
    assert inactive.ok is False and inactive.reason == "binding_inactive"


# ---------------------------------------------------------------------------
# Route contracts


def build_client(factory: sessionmaker) -> TestClient:
    from axis_api.main import create_app

    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    return TestClient(app)


ROUTE_BODY = {
    "tenant_id": TENANT_A,
    "connector_id": CONNECTOR_ID,
    "request_id": "ingest_api_001",
    "requested_by": "axis-operator",
    "reason": "Route-contract validation before extraction review.",
    "selections": [{"binding_id": "binding_api_001"}],
    "actor_scopes": [SOURCE_INGESTION_SCOPE],
}

READ_PARAMS = {
    "tenant_id": TENANT_A,
    "connector_id": CONNECTOR_ID,
    "actor_scopes": [SOURCE_INGESTION_READ_SCOPE],
}


def test_route_creates_and_returns_view_contract(session_factory) -> None:
    seed_binding(session_factory, "binding_api_001", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    client = build_client(session_factory)
    response = client.post(
        "/operations/connectors/external-db/source-ingestion-requests", json=ROUTE_BODY
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "created"
    assert body["status"] == "pending"
    assert body["selections"][0]["schema_fingerprint"] == FINGERPRINT_A


def test_route_enforces_write_scope_for_demo_traffic(session_factory) -> None:
    client = build_client(session_factory)
    response = client.post(
        "/operations/connectors/external-db/source-ingestion-requests",
        json={**ROUTE_BODY, "actor_scopes": []},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["required_permission"] == SOURCE_INGESTION_SCOPE


def test_route_read_endpoints_require_read_scope(session_factory) -> None:
    seed_binding(session_factory, "binding_api_001", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    client = build_client(session_factory)
    client.post(
        "/operations/connectors/external-db/source-ingestion-requests", json=ROUTE_BODY
    )

    denied = client.get(
        "/operations/connectors/external-db/source-ingestion/eligibility",
        params={"tenant_id": TENANT_A, "connector_id": CONNECTOR_ID},
    )
    assert denied.status_code == 403
    assert (
        denied.json()["detail"]["required_permission"] == SOURCE_INGESTION_READ_SCOPE
    )

    allowed = client.get(
        "/operations/connectors/external-db/source-ingestion/eligibility",
        params=READ_PARAMS,
    )
    assert allowed.status_code == 200, allowed.text
    eligibility_body = allowed.json()
    # The envelope advertises the deployment's honest extraction posture.
    assert eligibility_body["extraction_available"] is False
    assert eligibility_body["planned_limits"] is None
    assert eligibility_body["rows"][0]["binding_id"] == "binding_api_001"

    listed = client.get(
        "/operations/connectors/external-db/source-ingestion-requests",
        params=READ_PARAMS,
    )
    assert listed.status_code == 200
    assert listed.json()[0]["request_id"] == ROUTE_BODY["request_id"]

    single = client.get(
        (
            "/operations/connectors/external-db/source-ingestion-requests/"
            f"{ROUTE_BODY['request_id']}"
        ),
        params={"tenant_id": TENANT_A, "actor_scopes": [SOURCE_INGESTION_READ_SCOPE]},
    )
    assert single.status_code == 200
    assert single.json()["request_id"] == ROUTE_BODY["request_id"]

    ghost = client.get(
        "/operations/connectors/external-db/source-ingestion-requests/ingest_ghost",
        params={"tenant_id": TENANT_A, "actor_scopes": [SOURCE_INGESTION_READ_SCOPE]},
    )
    assert ghost.status_code == 404
    assert ghost.json()["detail"]["reason"] == "ingestion_request_not_found"


def test_route_maps_conflict_and_stale_to_precise_statuses(session_factory) -> None:
    seed_binding(session_factory, "binding_api_001", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    client = build_client(session_factory)
    assert (
        client.post(
            "/operations/connectors/external-db/source-ingestion-requests",
            json=ROUTE_BODY,
        ).status_code
        == 200
    )

    mismatch = client.post(
        "/operations/connectors/external-db/source-ingestion-requests",
        json={**ROUTE_BODY, "reason": "Different reason entirely."},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["reason"] == "request_id_conflict"

    drift_response = client.post(
        "/operations/connectors/external-db/source-ingestion-requests",
        json={
            **ROUTE_BODY,
            "request_id": "ingest_api_002",
            "selections": [{"binding_id": "binding_api_001"}],
        },
    )
    drift_observation(session_factory, RESOURCE_1, FINGERPRINT_B)
    stale = client.post(
        "/operations/connectors/external-db/source-ingestion-requests",
        json={
            **ROUTE_BODY,
            "request_id": "ingest_api_003",
            "selections": [{"binding_id": "binding_api_001"}],
        },
    )
    assert drift_response.status_code == 200
    assert stale.status_code == 422
    assert stale.json()["detail"]["reason"] == "stale_fingerprint"


# ---------------------------------------------------------------------------
# Attempt timeline (per-selection dispatch observability, metadata-only)


def view_row(factory):
    with session_scope(factory) as session:
        return get_connector_source_ingestion_request_view(
            AxisPersistenceRepository(session),
            tenant_id=TENANT_A,
            request_id="ingest_run_001",
        )


def test_completed_attempt_appends_metadata_only_timeline(session_factory) -> None:
    seed_binding(session_factory, "binding_ok", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_001", "binding_ok", RESOURCE_1, FINGERPRINT_A
    )

    result = dispatch(make_dispatcher(session_factory))

    assert result.completed == 1
    row = request_rows(session_factory)[0]
    attempts = row.evidence["attempts"]
    assert len(attempts) == 1
    entry = attempts[0]
    assert entry["attempt_number"] == 1
    assert entry["outcome"] == "completed"
    assert "error_code" not in entry
    assert entry["finished_at"]
    assert entry["selections"] == [
        {
            "binding_id": "binding_ok",
            "resource_name": RESOURCE_1,
            "outcome": "validated",
        }
    ]
    view = view_row(session_factory)
    assert view.attempts[0].outcome == "completed"
    assert view.attempts[0].selections[0].resource_name == RESOURCE_1


def test_retry_then_dead_letter_builds_two_entry_timeline(session_factory) -> None:
    seed_binding(session_factory, "binding_op", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_001", "binding_op", RESOURCE_1, FINGERPRINT_A
    )
    dispatcher = make_dispatcher(
        session_factory, runtime=RaisingRuntime(), settings=dispatch_settings(max_attempts=2)
    )

    first = dispatch(dispatcher)
    second = dispatch(dispatcher)

    assert first.retried == 1 and second.dead_lettered == 1
    row = request_rows(session_factory)[0]
    attempts = row.evidence["attempts"]
    assert [entry["outcome"] for entry in attempts] == ["retried", "dead_lettered"]
    assert [entry["attempt_number"] for entry in attempts] == [1, 2]
    assert all(entry["error_code"] == "RuntimeError" for entry in attempts)


def test_stale_fingerprint_timeline_records_selection_reason(session_factory) -> None:
    seed_binding(session_factory, "binding_drift", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_001", "binding_drift", RESOURCE_1, FINGERPRINT_A
    )
    drift_observation(session_factory, RESOURCE_1, FINGERPRINT_B)

    dispatch(make_dispatcher(session_factory))

    row = request_rows(session_factory)[0]
    entry = row.evidence["attempts"][0]
    assert entry["outcome"] == "dead_lettered"
    assert entry["error_code"].startswith("stale_fingerprint")
    assert entry["selections"][0]["outcome"] == "failed"
    assert entry["selections"][0]["reason"] == "stale_fingerprint"


def test_fenced_finalize_writes_no_timeline_entry(session_factory) -> None:
    """A stale claim token can append neither state nor a timeline entry."""
    seed_binding(session_factory, "binding_fence", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_001", "binding_fence", RESOURCE_1, FINGERPRINT_A
    )
    now = datetime.now(UTC)
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        claimed = repository.claim_connector_source_ingestion_requests(
            now=now,
            lease_expires_at=now + timedelta(seconds=120),
            limit=10,
        )
        assert (
            repository.complete_connector_source_ingestion_request(
                claimed[0].id,
                uuid4(),
                completed_at=now,
                evidence={"attempts": [{"attempt_number": 9}]},
            )
            is False
        )
        assert repository.get_connector_source_ingestion_request_attempts(
            claimed[0].id
        ) == []


def test_requeue_preserves_history_and_new_cycle_appends(session_factory) -> None:
    seed_binding(session_factory, "binding_rq", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_001", "binding_rq", RESOURCE_1, FINGERPRINT_A
    )
    dead_dispatcher = make_dispatcher(
        session_factory, runtime=RaisingRuntime(), settings=dispatch_settings(max_attempts=1)
    )
    dispatch(dead_dispatcher)
    row = request_rows(session_factory)[0]
    assert row.status == "failed"

    with session_scope(session_factory) as session:
        outcome = AxisPersistenceRepository(
            session
        ).requeue_connector_source_ingestion_request(
            tenant_id=TENANT_A,
            request_id="ingest_run_001",
            requeued_by="axis-operator",
            requeue_reason="Remediated the source; retrying validation.",
            idempotency_key="requeue_tl_001",
            now=datetime.now(UTC),
        )
    assert outcome == "requeued"
    # History is immutable: the requeue did not truncate prior attempts.
    assert len(request_rows(session_factory)[0].evidence["attempts"]) == 1

    recovered = dispatch(make_dispatcher(session_factory))
    assert recovered.completed == 1
    attempts = request_rows(session_factory)[0].evidence["attempts"]
    assert [entry["outcome"] for entry in attempts] == ["dead_lettered", "completed"]
    # The new cycle restarts its own attempt numbering.
    assert [entry["attempt_number"] for entry in attempts] == [1, 1]


def test_attempt_timeline_ordering_is_stable_across_duplicate_cycles(
    session_factory,
) -> None:
    """Re-dispatch cycles restart numbering; history stays insertion-ordered.

    Two cycles can legitimately produce identical (attempt_number, outcome)
    pairs — the durable timeline preserves chronological order and the view
    must expose exactly that, so clients can render both entries without key
    collisions or reordering.
    """
    seed_binding(session_factory, "binding_dup", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_001", "binding_dup", RESOURCE_1, FINGERPRINT_A
    )
    dead_dispatcher = make_dispatcher(
        session_factory, runtime=RaisingRuntime(), settings=dispatch_settings(max_attempts=1)
    )

    # Cycle 1: operational failure exhausts the single allowed attempt.
    assert dispatch(dead_dispatcher).dead_lettered == 1
    row = request_rows(session_factory)[0]
    assert row.status == "failed"

    # Governed re-dispatch resets numbering but preserves history.
    with session_scope(session_factory) as session:
        outcome = AxisPersistenceRepository(
            session
        ).requeue_connector_source_ingestion_request(
            tenant_id=TENANT_A,
            request_id="ingest_run_001",
            requeued_by="axis-operator",
            requeue_reason="Remediation probe for duplicate attempt pairs.",
            idempotency_key="requeue_dup_001",
            now=datetime.now(UTC),
        )
    assert outcome == "requeued"

    # Cycle 2 fails identically: same number, same outcome, new entry.
    # A fresh dispatcher carries a fresh clock so the requeued availability
    # time has arrived.
    cycle2 = make_dispatcher(
        session_factory, runtime=RaisingRuntime(), settings=dispatch_settings(max_attempts=1)
    )
    assert dispatch(cycle2).dead_lettered == 1

    attempts = request_rows(session_factory)[0].evidence["attempts"]
    assert [entry["attempt_number"] for entry in attempts] == [1, 1]
    assert [entry["outcome"] for entry in attempts] == [
        "dead_lettered",
        "dead_lettered",
    ]
    view = view_row(session_factory)
    assert [(a.attempt_number, a.outcome) for a in view.attempts] == [
        (1, "dead_lettered"),
        (1, "dead_lettered"),
    ]
    assert all(a.error_code == "RuntimeError" for a in view.attempts)


def test_attempt_views_skip_malformed_history_entries(session_factory) -> None:
    seed_binding(session_factory, "binding_ok", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_001", "binding_ok", RESOURCE_1, FINGERPRINT_A
    )
    dispatch(make_dispatcher(session_factory))
    with session_scope(session_factory) as session:
        row = session.scalars(select(ConnectorSourceIngestionRequest)).first()
        row.evidence = {
            **row.evidence,
            "attempts": [
                "not-a-dict",
                {"attempt_number": 0},
                *row.evidence["attempts"],
            ],
        }

    view = view_row(session_factory)

    assert len(view.attempts) == 1
    assert view.attempts[0].attempt_number == 1


def _seed_attempt_history(factory, count: int, *, prefix: str = "cycle") -> None:
    """Write `count` valid dead-lettered entries exactly as finalizers do."""
    with session_scope(factory) as session:
        row = session.scalars(select(ConnectorSourceIngestionRequest)).first()
        evidence = dict(row.evidence or {})
        attempts = list(evidence.get("attempts", []))
        for index in range(count):
            attempts.append(
                {
                    "attempt_number": 1,
                    "outcome": "dead_lettered",
                    "error_code": "RuntimeError",
                    "finished_at": f"2026-08-23T08:{index:02d}:00+00:00",
                    "selections": [
                        {
                            "binding_id": "binding_ok",
                            "resource_name": RESOURCE_1,
                            "outcome": "failed",
                            "reason": "RuntimeError",
                        }
                    ],
                }
            )
        row.evidence = {**evidence, "attempts": attempts}


def test_attempt_timeline_is_bounded_to_newest_window_with_flag(
    session_factory,
) -> None:
    seed_binding(session_factory, "binding_ok", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_001", "binding_ok", RESOURCE_1, FINGERPRINT_A
    )
    dispatch(make_dispatcher(session_factory))  # entry #1: completed
    _seed_attempt_history(session_factory, MAX_ATTEMPT_TIMELINE_ENTRIES + 5)

    view = view_row(session_factory)

    assert view.attempts_truncated is True
    assert len(view.attempts) == MAX_ATTEMPT_TIMELINE_ENTRIES
    # Chronological order preserved inside the newest window.
    assert all(
        entry.outcome == "dead_lettered" for entry in view.attempts
    )
    # The durable record itself is NOT truncated: append-only stays intact.
    stored = request_rows(session_factory)[0].evidence["attempts"]
    assert len(stored) == MAX_ATTEMPT_TIMELINE_ENTRIES + 6


def test_attempt_timeline_below_limit_reports_untruncated(
    session_factory,
) -> None:
    seed_binding(session_factory, "binding_ok", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_001", "binding_ok", RESOURCE_1, FINGERPRINT_A
    )
    dispatch(make_dispatcher(session_factory))
    view = view_row(session_factory)
    assert view.attempts_truncated is False
    assert len(view.attempts) == 1


def test_malformed_entries_do_not_distort_window_or_flag(
    session_factory,
) -> None:
    seed_binding(session_factory, "binding_ok", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_001", "binding_ok", RESOURCE_1, FINGERPRINT_A
    )
    dispatch(make_dispatcher(session_factory))
    junk = ["garbage", {"attempt_number": 0}, {"outcome": "completed"}]
    with session_scope(session_factory) as session:
        row = session.scalars(select(ConnectorSourceIngestionRequest)).first()
        row.evidence = {
            **row.evidence,
            "attempts": [*junk, *row.evidence["attempts"]],
        }

    view = view_row(session_factory)

    assert view.attempts_truncated is False
    assert [(a.attempt_number, a.outcome) for a in view.attempts] == [
        (1, "completed")
    ]


def test_attempt_timeline_entries_carry_metadata_only(session_factory) -> None:
    """Sentinel: no row values, watermark values, or payload keys anywhere."""
    seed_binding(session_factory, "binding_ok", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    create_dispatchable_request(
        session_factory, "ingest_run_001", "binding_ok", RESOURCE_1, FINGERPRINT_A
    )
    dispatch(make_dispatcher(session_factory))
    import json as jsonlib

    serialized = jsonlib.dumps(
        [entry.model_dump(mode="json") for entry in view_row(session_factory).attempts]
    )
    assert "row-" not in serialized
    assert "cursor_watermark" not in serialized
    assert "rows" not in serialized


def test_route_status_exposes_attempts_truncated_flag(session_factory) -> None:
    seed_binding(session_factory, "binding_api_001", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    client = build_client(session_factory)
    client.post(
        "/operations/connectors/external-db/source-ingestion-requests", json=ROUTE_BODY
    )
    result = dispatch(make_dispatcher(session_factory))
    assert result.completed == 1

    body = client.get(
        (
            "/operations/connectors/external-db/source-ingestion-requests/"
            f"{ROUTE_BODY['request_id']}"
        ),
        params={"tenant_id": TENANT_A, "actor_scopes": [SOURCE_INGESTION_READ_SCOPE]},
    ).json()
    assert body["attempts_truncated"] is False
    assert len(body["attempts"]) == 1


def test_route_status_exposes_attempt_timeline(session_factory) -> None:
    seed_binding(session_factory, "binding_api_001", RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    client = build_client(session_factory)
    client.post(
        "/operations/connectors/external-db/source-ingestion-requests", json=ROUTE_BODY
    )
    result = dispatch(make_dispatcher(session_factory))
    assert result.completed == 1

    body = client.get(
        (
            "/operations/connectors/external-db/source-ingestion-requests/"
            f"{ROUTE_BODY['request_id']}"
        ),
        params={"tenant_id": TENANT_A, "actor_scopes": [SOURCE_INGESTION_READ_SCOPE]},
    ).json()
    assert body["attempts"][0]["outcome"] == "completed"
    assert body["attempts"][0]["selections"][0]["binding_id"] == "binding_api_001"
