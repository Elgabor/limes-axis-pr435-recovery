"""Real PostgreSQL integration tests for governed source ingestion requests.

Runs against the live local Docker Postgres (AXIS_RUN_INTEGRATION=1) with
migration 0063 applied. Exercises the durable lifecycle over real activated
bindings: eligibility, creation, dispatch completion with truthful evidence,
drift between create and dispatch, concurrent duplicate creation racing the
(tenant_id, request_id) unique constraint, and skip_locked contention between
concurrent claimers. Every fixture is namespaced (`binding_ingint_`,
`ingreq_actint_`, dedicated schema) so older durable records on the retained
volume can never contaminate whole-tenant assertions.
"""

import asyncio
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy import delete as sqlalchemy_delete
from sqlalchemy.orm import sessionmaker

from axis_api.config import Settings
from axis_api.connector_postgres_discovery import (
    connector_source_discovery_runtime_from_settings,
)
from axis_api.connector_source_ingestion import (
    INGESTION_COMPLETED_EVENT,
    INGESTION_FAILED_EVENT,
    SOURCE_INGESTION_READ_SCOPE,
    SOURCE_INGESTION_SCOPE,
    ObservationFreshnessIngestionRuntime,
    SourceIngestionOutboxDispatcher,
    get_connector_source_ingestion_request_view,
)
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import (
    AuditEvent,
    ConnectorSourceBinding,
    ConnectorSourceIngestionRequest,
    DataAssetResourceObservation,
)
from axis_api.persistence import AxisPersistenceRepository

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("AXIS_RUN_INTEGRATION") != "1",
        reason="set AXIS_RUN_INTEGRATION=1 with the local Docker runtime running",
    ),
]

TENANT_A = "tenant_demo_manufacturing"
CONNECTOR_ID = "external_db_operational_mirror"
PROFILE_ID = "profile_postgres_discovery_readonly"
LEASE_ID = "lease_discovery_integration_001"
POLICY_ID = "egress_policy_private_endpoint_ops"
DISCOVERY_SCOPE = "connectors:source:discover"
ACTIVATION_SCOPE = "connectors:source:activate"
TEST_SCHEMA = "axis_ingestion_test"
BINDING_PREFIX = "binding_ingint_"
REQUEST_PREFIX = "ingreq_actint_"


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def engine(settings: Settings):
    engine = create_engine(settings.postgres_dsn)
    yield engine
    engine.dispose()


@pytest.fixture
def source_schema(engine):
    with engine.begin() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        connection.execute(text(f"CREATE SCHEMA {TEST_SCHEMA}"))
        connection.execute(
            text(
                f"CREATE TABLE {TEST_SCHEMA}.production_orders ("
                "order_id text PRIMARY KEY, asset_id text NOT NULL, status text)"
            )
        )
        connection.execute(
            text(
                f"CREATE TABLE {TEST_SCHEMA}.quality_checks ("
                "check_id text PRIMARY KEY, result text NOT NULL)"
            )
        )
    yield
    with engine.begin() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))


@pytest.fixture
def session_factory(engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        # Retained volume: clear this lane's namespaced state for reruns only;
        # other lanes' durable records are never touched.
        session.execute(
            sqlalchemy_delete(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id.like(f"{REQUEST_PREFIX}%"),
                ConnectorSourceIngestionRequest.tenant_id == TENANT_A,
            )
        )
        session.execute(
            sqlalchemy_delete(ConnectorSourceBinding).where(
                ConnectorSourceBinding.binding_id.like(f"{BINDING_PREFIX}%"),
                ConnectorSourceBinding.tenant_id == TENANT_A,
            )
        )
        session.execute(
            sqlalchemy_delete(DataAssetResourceObservation).where(
                DataAssetResourceObservation.tenant_id == TENANT_A,
                DataAssetResourceObservation.resource_name.like(f"{TEST_SCHEMA}.%"),
            )
        )
        _provision_governance(repository, session)
    return factory


def _provision_governance(repository: AxisPersistenceRepository, session) -> None:
    """Idempotently create the executed no-secret lease + approved policy."""
    stale_lease = repository.get_connector_credential_lease(TENANT_A, LEASE_ID)
    if stale_lease is not None:
        session.delete(stale_lease)
    stale_policy = repository.get_connector_egress_policy(TENANT_A, POLICY_ID)
    if stale_policy is not None:
        session.delete(stale_policy)
    session.flush()
    now = datetime.now(UTC)
    from axis_api.persistence import (
        ConnectorCredentialLeaseCreate,
        ConnectorEgressPolicyCreate,
    )

    repository.create_connector_credential_lease(
        ConnectorCredentialLeaseCreate(
            tenant_id=TENANT_A,
            connector_id=CONNECTOR_ID,
            handle_id="cred_external_db_readonly",
            lease_id=LEASE_ID,
            status="active",
            requested_by="axis-operator",
            lease_purpose="source_ingestion_integration",
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
                "approved_endpoint_target_sha256": hashlib.sha256(b"localhost:5432").hexdigest()
            },
            evidence_refs=[],
            audit_event_type="connector.egress_policy.registered",
        )
    )


def _build_client(settings: Settings, session_factory) -> TestClient:
    app = create_app(Settings(postgres_dsn=settings.postgres_dsn))
    app.state.session_factory = session_factory
    app.state.connector_source_discovery_runtime = (
        connector_source_discovery_runtime_from_settings(
            Settings(
                postgres_dsn=settings.postgres_dsn,
                external_db_live_query_dsn=settings.postgres_dsn.replace(
                    "postgresql+psycopg://", "postgresql://", 1
                ),
                connector_sync_execution_enabled=True,
                external_db_sync_execution_enabled=True,
                external_db_discovery_enabled=True,
                external_db_discovery_schemas=[TEST_SCHEMA],
                external_db_runtime_egress_enforcement_enabled=True,
            )
        )
    )
    return TestClient(app)


def _discover_real_fingerprints(client: TestClient, discovery_id: str) -> dict[str, str]:
    response = client.post(
        "/operations/connectors/external-db/discover",
        json={
            "tenant_id": TENANT_A,
            "connector_id": CONNECTOR_ID,
            "discovery_id": discovery_id,
            "requested_by": "axis-operator",
            "connection_profile_id": PROFILE_ID,
            "schema_name": TEST_SCHEMA,
            "credential_lease_id": LEASE_ID,
            "egress_policy_id": POLICY_ID,
            "actor_scopes": [DISCOVERY_SCOPE],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["status"] == "discovery_completed", body["result"]
    return {
        f"{table['schema_name']}.{table['table_name']}": table["column_fingerprint"]
        for table in body["result"]["tables"]
    }


def _activate(client: TestClient, fingerprints: dict[str, str], activation_id: str):
    response = client.post(
        "/operations/connectors/external-db/source-bindings",
        json={
            "tenant_id": TENANT_A,
            "connector_id": CONNECTOR_ID,
            "activation_id": activation_id,
            "requested_by": "axis-operator",
            "connection_profile_id": PROFILE_ID,
            "credential_lease_id": LEASE_ID,
            "egress_policy_id": POLICY_ID,
            "activation_reason": (
                "Integration lane: bind discovered tables for governed ingestion."
            ),
            "selections": [
                {
                    "binding_id": f"{BINDING_PREFIX}{index}",
                    "resource_name": resource_name,
                    "expected_schema_fingerprint": fingerprint,
                }
                for index, (resource_name, fingerprint) in enumerate(sorted(fingerprints.items()))
            ],
            "actor_scopes": [ACTIVATION_SCOPE],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


READ_PARAMS = {
    "tenant_id": TENANT_A,
    "connector_id": CONNECTOR_ID,
    "actor_scopes": [SOURCE_INGESTION_READ_SCOPE],
}


def _ingest_body(request_id: str, binding_ids: list[str]) -> dict:
    return {
        "tenant_id": TENANT_A,
        "connector_id": CONNECTOR_ID,
        "request_id": request_id,
        "requested_by": "axis-operator",
        "reason": "Integration lane: validate bound tables before extraction.",
        "selections": [{"binding_id": binding_id} for binding_id in binding_ids],
        "actor_scopes": [SOURCE_INGESTION_SCOPE],
    }


def test_request_lifecycle_over_real_activated_bindings(
    settings, source_schema, session_factory
) -> None:
    client = _build_client(settings, session_factory)
    fingerprints = _discover_real_fingerprints(client, "discovery_ingint_001")
    activated = _activate(client, fingerprints, "activation_ingint_001")
    binding_ids = [view["binding_id"] for view in activated["bindings"]]
    assert len(binding_ids) == len(fingerprints)

    eligibility = client.get(
        "/operations/connectors/external-db/source-ingestion/eligibility",
        params=READ_PARAMS,
    )
    assert eligibility.status_code == 200, eligibility.text
    eligible_rows = [row for row in eligibility.json() if row["eligible"]]
    assert sorted(row["binding_id"] for row in eligible_rows) == sorted(binding_ids)

    created = client.post(
        "/operations/connectors/external-db/source-ingestion-requests",
        json=_ingest_body(f"{REQUEST_PREFIX}001", binding_ids),
    )
    assert created.status_code == 200, created.text
    view = created.json()
    assert view["outcome"] == "created" and view["status"] == "pending"

    replayed = client.post(
        "/operations/connectors/external-db/source-ingestion-requests",
        json=_ingest_body(f"{REQUEST_PREFIX}001", binding_ids),
    )
    assert replayed.status_code == 200
    assert replayed.json()["outcome"] == "replayed"

    dispatcher = SourceIngestionOutboxDispatcher(
        settings=settings,
        session_factory=session_factory,
        runtime=ObservationFreshnessIngestionRuntime(),
    )
    result = asyncio.run(dispatcher.run_once())
    assert result.claimed == 1 and result.completed == 1

    # Durability: a brand-new session sees terminal truth, not cached state.
    with session_scope(session_factory) as session:
        stored = get_connector_source_ingestion_request_view(
            AxisPersistenceRepository(session),
            tenant_id=TENANT_A,
            request_id=f"{REQUEST_PREFIX}001",
        )
        assert stored is not None
        assert stored.status == "completed"
    with session_scope(session_factory) as session:
        row = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == f"{REQUEST_PREFIX}001"
            )
        ).first()
        evidence = dict(row.evidence)
        assert evidence["source_dial_performed"] is False
        assert evidence["extraction_performed"] is False
        assert evidence["validated_count"] == len(binding_ids)
        completed = session.scalars(
            select(AuditEvent).where(AuditEvent.event_type == INGESTION_COMPLETED_EVENT)
        ).all()
        assert any(
            event.payload.get("request_id") == f"{REQUEST_PREFIX}001" for event in completed
        )


def test_drift_between_create_and_dispatch_dead_letters(
    settings, source_schema, session_factory, engine
) -> None:
    client = _build_client(settings, session_factory)
    fingerprints = _discover_real_fingerprints(client, "discovery_ingint_002")
    activated = _activate(
        client,
        {"production_orders": fingerprints[f"{TEST_SCHEMA}.production_orders"]},
        "activation_ingint_002",
    )
    binding_id = activated["bindings"][0]["binding_id"]

    created = client.post(
        "/operations/connectors/external-db/source-ingestion-requests",
        json=_ingest_body(f"{REQUEST_PREFIX}002", [binding_id]),
    )
    assert created.status_code == 200

    # Simulate a later discovery observing changed schema evidence after the
    # request pinned the old fingerprint: dispatch must fail closed forever.
    resource_name = activated["bindings"][0]["resource_name"]
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE data_asset_resource_observations "
                "SET schema_fingerprint = :fp "
                "WHERE tenant_id = :tenant AND resource_name = :resource"
            ),
            {"fp": "d" * 64, "tenant": TENANT_A, "resource": resource_name},
        )

    dispatcher = SourceIngestionOutboxDispatcher(
        settings=settings,
        session_factory=session_factory,
        runtime=ObservationFreshnessIngestionRuntime(),
    )
    result = asyncio.run(dispatcher.run_once())
    assert result.dead_lettered == 1

    with session_scope(session_factory) as session:
        row = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == f"{REQUEST_PREFIX}002"
            )
        ).first()
        assert row.status == "failed"
        assert row.dead_lettered_at is not None
        assert "stale_fingerprint" in (row.last_error or "")
        dead_letters = session.scalars(
            select(AuditEvent).where(AuditEvent.event_type == INGESTION_FAILED_EVENT)
        ).all()
        assert any(
            event.payload.get("request_id") == f"{REQUEST_PREFIX}002"
            for event in dead_letters
        )


def _submit_in_thread(
    postgres_dsn: str, request_id: str, binding_id: str
) -> tuple[str, str]:
    """One racer with its own engine/session: create or replay honestly."""

    engine = create_engine(postgres_dsn)
    try:
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        def race():
            with session_scope(factory) as session:
                view = record_create(session, request_id, binding_id)
                return ("created" if view.outcome == "created" else "replayed", view.request_id)

        return race()
    finally:
        engine.dispose()


def record_create(session, request_id: str, binding_id: str):
    from axis_api.connector_source_ingestion import (
        ConnectorSourceIngestionSubmission,
        record_connector_source_ingestion_request,
    )

    return record_connector_source_ingestion_request(
        AxisPersistenceRepository(session),
        submission=ConnectorSourceIngestionSubmission(
            tenant_id=TENANT_A,
            connector_id=CONNECTOR_ID,
            request_id=request_id,
            requested_by="axis-operator",
            reason="Concurrent duplicate creation probe.",
            selections=[{"binding_id": binding_id}],
            actor_scopes=[SOURCE_INGESTION_SCOPE],
        ),
        principal_scopes=[SOURCE_INGESTION_SCOPE],
        max_selections=20,
    )


def test_concurrent_duplicate_creates_yield_one_durable_row(
    settings, source_schema, session_factory
) -> None:
    client = _build_client(settings, session_factory)
    fingerprints = _discover_real_fingerprints(client, "discovery_ingint_003")
    activated = _activate(
        client,
        {"production_orders": fingerprints[f"{TEST_SCHEMA}.production_orders"]},
        "activation_ingint_003",
    )
    binding_id = activated["bindings"][0]["binding_id"]
    request_id = f"{REQUEST_PREFIX}003"

    racers = 8
    with ThreadPoolExecutor(max_workers=racers) as pool:
        outcomes = list(
            pool.map(
                lambda _: _submit_in_thread(settings.postgres_dsn, request_id, binding_id),
                range(racers),
            )
        )

    created_count = sum(1 for outcome, _ in outcomes if outcome == "created")
    assert created_count == 1, outcomes
    with session_scope(session_factory) as session:
        rows = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == request_id
            )
        ).all()
        assert len(rows) == 1
        requested_events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "connector.source.ingestion.requested"
            )
        ).all()
        matching = [
            event
            for event in requested_events
            if event.payload.get("request_id") == request_id
        ]
        assert len(matching) == 1


def test_concurrent_claimers_partition_work_without_overlap(
    settings, source_schema, session_factory
) -> None:
    client = _build_client(settings, session_factory)
    fingerprints = _discover_real_fingerprints(client, "discovery_ingint_004")
    activated = _activate(client, fingerprints, "activation_ingint_004")
    binding_ids = [view["binding_id"] for view in activated["bindings"]]

    created = client.post(
        "/operations/connectors/external-db/source-ingestion-requests",
        json=_ingest_body(f"{REQUEST_PREFIX}004", binding_ids[:1]),
    )
    assert created.status_code == 200
    for index in range(1, len(binding_ids)):
        extra = client.post(
            "/operations/connectors/external-db/source-ingestion-requests",
            json={
                **_ingest_body(f"{REQUEST_PREFIX}004_{index}", [binding_ids[index]]),
                "requested_by": "axis-operator",
            },
        )
        assert extra.status_code == 200

    total_requests = len(binding_ids)
    workers = 4

    def claim_worker(_: int) -> list[str]:
        engine = create_engine(settings.postgres_dsn)
        try:
            factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
            now = datetime.now(UTC)
            with session_scope(factory) as session:
                claimed = AxisPersistenceRepository(
                    session
                ).claim_connector_source_ingestion_requests(
                    now=now,
                    lease_expires_at=now + timedelta(seconds=120),
                    limit=10,
                )
                return [str(row.id) for row in claimed]
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        batches = list(pool.map(claim_worker, range(workers)))

    claimed_ids = [row_id for batch in batches for row_id in batch]
    assert len(claimed_ids) == total_requests
    assert len(set(claimed_ids)) == total_requests  # no double claims


def test_expired_leases_are_recovered_by_the_next_dispatcher_pass(
    settings, source_schema, session_factory
) -> None:
    client = _build_client(settings, session_factory)
    fingerprints = _discover_real_fingerprints(client, "discovery_ingint_005")
    activated = _activate(
        client,
        {"production_orders": fingerprints[f"{TEST_SCHEMA}.production_orders"]},
        "activation_ingint_005",
    )
    binding_id = activated["bindings"][0]["binding_id"]
    request_id = f"{REQUEST_PREFIX}005"

    assert (
        client.post(
            "/operations/connectors/external-db/source-ingestion-requests",
            json=_ingest_body(request_id, [binding_id]),
        ).status_code
        == 200
    )

    # A worker claimed and died mid-flight: strand the lease in the past.
    now = datetime.now(UTC)
    with session_scope(session_factory) as session:
        row = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == request_id
            )
        ).first()
        row.status = "dispatching"
        row.attempt_count = 1
        row.claim_token = uuid4()
        row.claimed_at = now - timedelta(minutes=5)
        row.last_attempt_at = now - timedelta(minutes=5)
        row.lease_expires_at = now - timedelta(minutes=4)

    dispatcher = SourceIngestionOutboxDispatcher(
        settings=settings,
        session_factory=session_factory,
        runtime=ObservationFreshnessIngestionRuntime(),
    )
    result = asyncio.run(dispatcher.run_once())
    assert result.claimed == 1 and result.completed == 1

    with session_scope(session_factory) as session:
        row = session.scalars(
            select(ConnectorSourceIngestionRequest).where(
                ConnectorSourceIngestionRequest.request_id == request_id
            )
        ).first()
        assert row.status == "completed"
        assert row.attempt_count == 2
