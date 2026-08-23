"""Real-source integration tests for governed source activation.

Runs against the live local Docker Postgres (AXIS_RUN_INTEGRATION=1) and
exercises the full journey over real discovered evidence: bounded discovery
of a throwaway schema -> operator selection activation -> durable bindings ->
replay and drift semantics. The throwaway schema is dropped in a finally
block; binding/observation rows are cleaned per-run because the database
volume is retained across runs.
"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy import delete as sqlalchemy_delete
from sqlalchemy.orm import sessionmaker

from axis_api.config import Settings
from axis_api.connector_postgres_discovery import (
    SelfHostedPostgresDiscoveryRuntime,
    connector_source_discovery_runtime_from_settings,
)
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import ConnectorSourceBinding, DataAssetResourceObservation
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorSourceBindingCreate,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("AXIS_RUN_INTEGRATION") != "1",
        reason="set AXIS_RUN_INTEGRATION=1 with the local Docker runtime running",
    ),
]

TENANT_A = "tenant_demo_manufacturing"
TENANT_B = "tenant_demo_retail"
CONNECTOR_ID = "external_db_operational_mirror"
PROFILE_ID = "profile_postgres_discovery_readonly"
LEASE_ID = "lease_discovery_integration_001"
POLICY_ID = "egress_policy_private_endpoint_ops"
DISCOVERY_SCOPE = "connectors:source:discover"
ACTIVATION_SCOPE = "connectors:source:activate"
TEST_SCHEMA = "axis_activation_test"

# Governance records are provisioned by test_connector_postgres_discovery_runtime's
# own lane too, so this file cleans its own bindings only and reuses the shared
# lease/policy setup style below.


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def engine(settings: Settings):
    engine = create_engine(settings.postgres_dsn)
    yield engine
    engine.dispose()


def _discovery_runtime_for(settings: Settings) -> SelfHostedPostgresDiscoveryRuntime:
    from axis_api.connector_postgres_discovery import (
        postgres_discovery_profile_from_settings,
    )

    return SelfHostedPostgresDiscoveryRuntime(
        profile=postgres_discovery_profile_from_settings(
            settings.model_copy(
                update={
                    "external_db_live_query_dsn": settings.postgres_dsn.replace(
                        "postgresql+psycopg://", "postgresql://", 1
                    ),
                    "external_db_discovery_schemas": [TEST_SCHEMA],
                    "external_db_runtime_egress_enforcement_enabled": True,
                }
            )
        ),
        runtime_egress_enforcement_enabled=True,
    )


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
        # Retained volume: clear this lane's durable state for reruns.
        session.execute(
            sqlalchemy_delete(ConnectorSourceBinding).where(
                ConnectorSourceBinding.binding_id.like("binding_actint_%"),
                ConnectorSourceBinding.tenant_id.in_([TENANT_A, TENANT_B]),
            )
        )
        session.execute(
            sqlalchemy_delete(DataAssetResourceObservation).where(
                DataAssetResourceObservation.tenant_id == TENANT_A,
                DataAssetResourceObservation.resource_name.like(f"{TEST_SCHEMA}.%"),
            )
        )
        # Governance records are provisioned idempotently so this file is
        # self-sufficient even on a fresh database.
        _provision_governance(repository, session, TENANT_A)
    return factory


def _provision_governance(
    repository: AxisPersistenceRepository,
    session,
    tenant_id: str,
) -> None:
    """Idempotently create the executed no-secret lease + approved policy."""
    from datetime import UTC, datetime, timedelta

    from axis_api.persistence import (
        ConnectorCredentialLeaseCreate,
        ConnectorEgressPolicyCreate,
    )

    lease_id = LEASE_ID if tenant_id == TENANT_A else f"{LEASE_ID}_{tenant_id}"
    policy_id = POLICY_ID if tenant_id == TENANT_A else f"{POLICY_ID}_{tenant_id}"

    stale_lease = repository.get_connector_credential_lease(tenant_id, lease_id)
    if stale_lease is not None:
        session.delete(stale_lease)
    stale_policy = repository.get_connector_egress_policy(tenant_id, policy_id)
    if stale_policy is not None:
        session.delete(stale_policy)
    session.flush()
    now = datetime.now(UTC)
    repository.create_connector_credential_lease(
        ConnectorCredentialLeaseCreate(
            tenant_id=tenant_id,
            connector_id=CONNECTOR_ID,
            handle_id="cred_external_db_readonly",
            lease_id=lease_id,
            status="active",
            requested_by="axis-operator",
            lease_purpose="source_activation_integration",
            secret_provider="env",
            secret_ref="AXIS_EXTERNAL_DB_DISCOVERY_TEST_DSN",
            vault_kms_policy={},
            permission_decision={"allowed": True, "reason": "all_required_scopes_present"},
            lease_result={
                "status": "lease_executed",
                "provider_lease_ref": f"self-hosted-vault-kms://{tenant_id}/{lease_id}",
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
            tenant_id=tenant_id,
            connector_id=CONNECTOR_ID,
            policy_id=policy_id,
            display_name="Operations private endpoint",
            status="active",
            connection_profile_id=PROFILE_ID,
            egress_boundary="approved_private_endpoint",
            policy_mode="approved_private_endpoint",
            runtime_boundary="axis-egress-policy-enforcer",
            private_endpoint_ref=(
                f"private-endpoint://{tenant_id}/persisted-operations-postgres-readonly"
            ),
            created_by="axis-operator",
            policy_document={
                "approved_endpoint_target_sha256": hashlib.sha256(b"localhost:5432").hexdigest()
            },
            evidence_refs=[],
            audit_event_type="connector.egress_policy.registered",
        )
    )


def _activate_body(fingerprints: dict[str, str], activation_id: str) -> dict:
    return {
        "tenant_id": TENANT_A,
        "connector_id": CONNECTOR_ID,
        "activation_id": activation_id,
        "requested_by": "axis-operator",
        "connection_profile_id": PROFILE_ID,
        "credential_lease_id": LEASE_ID,
        "egress_policy_id": POLICY_ID,
        "activation_reason": "Integration lane: bind discovered tables for governed ingestion.",
        "selections": [
            {
                "binding_id": f"binding_actint_{suffix}",
                "resource_name": resource_name,
                "expected_schema_fingerprint": fingerprint,
            }
            for suffix, (resource_name, fingerprint) in enumerate(sorted(fingerprints.items()))
        ],
        "actor_scopes": [ACTIVATION_SCOPE],
    }


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


def _discover_real_tables(client: TestClient, discovery_id: str) -> dict[str, str]:
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
    assert body["result"]["status"] == "discovery_completed"
    return {
        table["schema_name"] + "." + table["table_name"]: table["column_fingerprint"]
        for table in body["result"]["tables"]
    }


ACTIVATION_ROUTE = "/operations/connectors/external-db/source-bindings"


def _selection(binding_id: str, resource_name: str, fingerprint: str) -> dict:
    return {
        "binding_id": binding_id,
        "resource_name": resource_name,
        "expected_schema_fingerprint": fingerprint,
    }


def _activation_body(**overrides) -> dict:
    body = {
        "tenant_id": TENANT_A,
        "connector_id": CONNECTOR_ID,
        "activation_id": "activation_actint_x",
        "requested_by": "axis-operator",
        "connection_profile_id": PROFILE_ID,
        "credential_lease_id": LEASE_ID,
        "egress_policy_id": POLICY_ID,
        "activation_reason": (
            "Integration lane: bind discovered tables for governed ingestion."
        ),
        "selections": [],
        "actor_scopes": [ACTIVATION_SCOPE],
    }
    body.update(overrides)
    return body


def _listed_resource_names(client: TestClient, tenant_id: str = TENANT_A) -> set[str]:
    """Resource names bound by THIS lane (binding_actint_ namespace).

    The shared demo tenant legitimately carries other lanes' durable
    bindings (console E2E, smoke); assertions here must stay scoped to the
    rows this file owns, exactly like its cleanup.
    """
    listed = client.get(
        ACTIVATION_ROUTE,
        params={"tenant_id": tenant_id, "connector_id": CONNECTOR_ID},
    )
    assert listed.status_code == 200
    return {
        view["resource_name"]
        for view in listed.json()["bindings"]
        if view["binding_id"].startswith("binding_actint_")
    }


def test_full_api_path_activates_discovered_real_tables(
    settings, session_factory, source_schema
) -> None:
    client = _build_client(settings, session_factory)

    fingerprints = _discover_real_tables(client, "discovery_actint_r1")
    assert set(fingerprints) == {
        f"{TEST_SCHEMA}.production_orders",
        f"{TEST_SCHEMA}.quality_checks",
    }

    activated = client.post(
        ACTIVATION_ROUTE, json=_activate_body(fingerprints, "activation_actint_001")
    )
    assert activated.status_code == 200, activated.text
    body = activated.json()
    assert [view["outcome"] for view in body["bindings"]] == ["activated", "activated"]
    assert all(view["ingestion_status"] == "pending_ingestion" for view in body["bindings"])

    assert _listed_resource_names(client) == set(fingerprints)


def test_replay_over_real_bindings_is_deterministic(
    settings, session_factory, source_schema
) -> None:
    client = _build_client(settings, session_factory)
    fingerprints = _discover_real_tables(client, "discovery_actint_r2")

    first = client.post(
        ACTIVATION_ROUTE, json=_activate_body(fingerprints, "activation_actint_002")
    )
    assert first.status_code == 200, first.text

    replay = client.post(
        ACTIVATION_ROUTE, json=_activate_body(fingerprints, "activation_actint_002")
    )
    assert replay.status_code == 200, replay.text
    assert [view["outcome"] for view in replay.json()["bindings"]] == ["replayed", "replayed"]

    assert len(_listed_resource_names(client)) == 2


def test_drift_after_discovery_makes_activation_stale(
    settings, session_factory, source_schema, engine
) -> None:
    client = _build_client(settings, session_factory)
    fingerprints_before = _discover_real_tables(client, "discovery_actint_r3")

    # Real schema drift happens at the source...
    with engine.begin() as connection:
        connection.execute(
            text(
                f"ALTER TABLE {TEST_SCHEMA}.quality_checks "
                "ADD COLUMN severity text NOT NULL DEFAULT 'low'"
            )
        )
    # ...and only becomes observable truth when Axis discovers again.
    fingerprints_after = _discover_real_tables(client, "discovery_actint_r3b")
    assert fingerprints_after[f"{TEST_SCHEMA}.quality_checks"] != (
        fingerprints_before[f"{TEST_SCHEMA}.quality_checks"]
    )

    # Activating with pre-drift evidence is rejected as stale.
    stale = client.post(
        ACTIVATION_ROUTE,
        json=_activate_body(fingerprints_before, "activation_actint_003"),
    )
    assert stale.status_code == 422, stale.text
    detail = stale.json()["detail"]
    assert detail["reason"] == "schema_fingerprint_stale"
    assert isinstance(detail["selection_index"], int)

    # Rediscovered evidence activates cleanly.
    recovered = client.post(
        ACTIVATION_ROUTE,
        json=_activate_body(fingerprints_after, "activation_actint_003b"),
    )
    assert recovered.status_code == 200, recovered.text


def test_partial_unique_index_blocks_duplicate_active_resource_rows(
    settings, session_factory
) -> None:
    """DB-level backstop behind the domain gates on real PostgreSQL."""
    from uuid import uuid4

    import sqlalchemy.exc

    payload = dict(
        tenant_id=TENANT_A,
        connector_id=CONNECTOR_ID,
        asset_id=f"source:{CONNECTOR_ID}:default",
        connection_profile_id=PROFILE_ID,
        resource_name=f"{TEST_SCHEMA}.backstop_probe",
        schema_fingerprint="a" * 64,
        credential_lease_id=LEASE_ID,
        egress_policy_id=POLICY_ID,
        ingestion_status="pending_ingestion",
        activated_by="integration-backstop",
        activation_reason="Prove the partial unique index blocks duplicates.",
    )

    def _create(binding_id: str) -> None:
        with session_scope(session_factory) as session:
            AxisPersistenceRepository(session).create_connector_source_binding(
                ConnectorSourceBindingCreate(
                    binding_id=binding_id,
                    audit_event_id=uuid4(),
                    audit_event_type="connector.source.bindings.activated",
                    **payload,
                )
            )

    _create("binding_actint_backstop_a")
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        _create("binding_actint_backstop_b")


def test_governance_gates_hold_over_real_postgres(
    settings, session_factory, source_schema
) -> None:
    client = _build_client(settings, session_factory)
    fingerprints = _discover_real_tables(client, "discovery_actint_r4")

    no_scope = client.post(
        ACTIVATION_ROUTE,
        json=_activation_body(
            activation_id="activation_actint_004",
            selections=[
                _selection("binding_actint_004a", *next(iter(fingerprints.items())))
            ],
            actor_scopes=[DISCOVERY_SCOPE],
        ),
    )
    assert no_scope.status_code == 403, no_scope.text
    detail = no_scope.json()["detail"]
    assert detail["reason"] == "missing_scope:connectors:source:activate"
    assert detail["required_permission"] == ACTIVATION_SCOPE

    unknown_lease = client.post(
        ACTIVATION_ROUTE,
        json=_activation_body(
            activation_id="activation_actint_005",
            credential_lease_id="lease_does_not_exist",
            selections=[
                _selection("binding_actint_005a", *next(iter(fingerprints.items())))
            ],
        ),
    )
    assert unknown_lease.status_code == 404, unknown_lease.text
    assert (
        unknown_lease.json()["detail"]["reason"] == "credential_lease_not_found"
    )

    assert _listed_resource_names(client) == set()


def test_failed_batch_and_oversize_writes_nothing(
    settings, session_factory, source_schema
) -> None:
    """Atomic all-or-nothing and the 20-table bound hold on real PostgreSQL."""
    client = _build_client(settings, session_factory)
    fingerprints = _discover_real_tables(client, "discovery_actint_r5")
    real_name, real_fingerprint = next(iter(fingerprints.items()))

    mixed = client.post(
        ACTIVATION_ROUTE,
        json=_activation_body(
            activation_id="activation_actint_006",
            selections=[
                _selection("binding_actint_006a", real_name, real_fingerprint),
                _selection(
                    "binding_actint_006b",
                    f"{TEST_SCHEMA}.never_observed",
                    "b" * 64,
                ),
            ],
        ),
    )
    assert mixed.status_code == 422, mixed.text
    detail = mixed.json()["detail"]
    assert detail["reason"] == "resource_not_observed"
    assert detail["selection_index"] == 1
    # The valid first selection must not have leaked through the failure.
    assert _listed_resource_names(client) == set()

    oversize = client.post(
        ACTIVATION_ROUTE,
        json=_activation_body(
            activation_id="activation_actint_007",
            selections=[
                _selection(
                    f"binding_actint_007_{i:02d}",
                    f"{TEST_SCHEMA}.table_{i:02d}",
                    "c" * 64,
                )
                for i in range(21)
            ],
        ),
    )
    assert oversize.status_code == 422, oversize.text
    assert oversize.json()["detail"]["reason"] == "selection_too_large"

    boundary_ok_shape = client.post(
        ACTIVATION_ROUTE,
        json=_activation_body(
            activation_id="activation_actint_008",
            selections=[
                _selection(
                    f"binding_actint_008_{i:02d}",
                    f"{TEST_SCHEMA}.unobserved_{i:02d}",
                    "c" * 64,
                )
                for i in range(20)
            ],
        ),
    )
    # 20 is inside the bound; the batch now fails on observations instead,
    # proving the size gate passed and validation continued.
    assert boundary_ok_shape.status_code == 422, boundary_ok_shape.text
    assert (
        boundary_ok_shape.json()["detail"]["reason"] == "resource_not_observed"
    )
    assert _listed_resource_names(client) == set()


def test_conflicts_rejected_without_partial_writes(
    settings, session_factory, source_schema
) -> None:
    client = _build_client(settings, session_factory)
    fingerprints = _discover_real_tables(client, "discovery_actint_r6")
    orders_name = f"{TEST_SCHEMA}.production_orders"
    checks_name = f"{TEST_SCHEMA}.quality_checks"
    orders_fingerprint = fingerprints[orders_name]
    checks_fingerprint = fingerprints[checks_name]

    first = client.post(
        ACTIVATION_ROUTE,
        json=_activation_body(
            activation_id="activation_actint_009",
            selections=[_selection("binding_actint_009a", orders_name, orders_fingerprint)],
        ),
    )
    assert first.status_code == 200, first.text

    same_resource_new_binding = client.post(
        ACTIVATION_ROUTE,
        json=_activation_body(
            activation_id="activation_actint_010",
            selections=[_selection("binding_actint_010a", orders_name, orders_fingerprint)],
        ),
    )
    assert same_resource_new_binding.status_code == 409, same_resource_new_binding.text
    assert (
        same_resource_new_binding.json()["detail"]["reason"] == "binding_already_active"
    )

    used_elsewhere = client.post(
        ACTIVATION_ROUTE,
        json=_activation_body(
            activation_id="activation_actint_011",
            selections=[
                _selection("binding_actint_009a", checks_name, checks_fingerprint)
            ],
        ),
    )
    assert used_elsewhere.status_code == 409, used_elsewhere.text
    assert used_elsewhere.json()["detail"]["reason"] == "binding_id_in_use"

    # Both conflicts left exactly the one original binding behind.
    assert _listed_resource_names(client) == {orders_name}


def test_tenant_isolation_holds_for_reads_and_writes(
    settings, session_factory, source_schema, engine
) -> None:
    from axis_api.persistence import AxisPersistenceRepository as Repo

    client = _build_client(settings, session_factory)
    fingerprints = _discover_real_tables(client, "discovery_actint_r7")
    orders_name = f"{TEST_SCHEMA}.production_orders"
    activated = client.post(
        ACTIVATION_ROUTE,
        json=_activation_body(
            activation_id="activation_actint_012",
            selections=[
                _selection(
                    "binding_actint_012a",
                    orders_name,
                    fingerprints[orders_name],
                )
            ],
        ),
    )
    assert activated.status_code == 200, activated.text
    bound_name = activated.json()["bindings"][0]["resource_name"]
    bound_fingerprint = activated.json()["bindings"][0]["schema_fingerprint"]

    # Reads are tenant-scoped: tenant B sees none of tenant A's bindings.
    assert _listed_resource_names(client, TENANT_B) == set()
    assert len(_listed_resource_names(client, TENANT_A)) == 1

    # Tenant B gets its own governance records, then tries to activate the
    # very same physical tables using A's leaked discovery fingerprints.
    with session_scope(session_factory) as session:
        _provision_governance(Repo(session), session, TENANT_B)

    stolen = client.post(
        ACTIVATION_ROUTE,
        json=_activation_body(
            tenant_id=TENANT_B,
            credential_lease_id=f"{LEASE_ID}_{TENANT_B}",
            egress_policy_id=f"{POLICY_ID}_{TENANT_B}",
            activation_id="activation_actint_013",
            selections=[
                _selection("binding_actint_013a", bound_name, bound_fingerprint)
            ],
        ),
    )
    assert stolen.status_code == 422, stolen.text
    assert stolen.json()["detail"]["reason"] == "resource_not_observed"

    # Nothing changed for either tenant.
    assert _listed_resource_names(client, TENANT_B) == set()
    assert _listed_resource_names(client, TENANT_A) == {bound_name}
