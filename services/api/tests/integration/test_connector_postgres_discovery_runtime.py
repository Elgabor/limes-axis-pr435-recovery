"""Real-source integration tests for Postgres schema discovery.

These run against the live local Docker Postgres (AXIS_RUN_INTEGRATION=1)
and exercise the full governed path: persisted lease + egress policy ->
scope-gated route -> real information_schema introspection -> catalog
resource observations. The throwaway ``axis_discovery_test`` schema is
dropped in a finally block.
"""

import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy import delete as sqlalchemy_delete
from sqlalchemy.orm import sessionmaker

from axis_api.config import Settings
from axis_api.connector_postgres_discovery import (
    ConnectorSourceDiscoveryRequest,
    ConnectorSourceVerifyRequest,
    SelfHostedPostgresDiscoveryRuntime,
    connector_source_discovery_runtime_from_settings,
    record_connector_source_discovery,
    record_connector_source_verification,
)
from axis_api.db import session_scope
from axis_api.main import create_app
from axis_api.models import DataAssetResourceObservation
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorCredentialLeaseCreate,
    ConnectorEgressPolicyCreate,
)

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
SCOPE = "connectors:source:discover"
TEST_SCHEMA = "axis_discovery_test"


def discovery_profile(settings: Settings):
    from axis_api.connector_postgres_discovery import (
        postgres_discovery_profile_from_settings,
    )

    return postgres_discovery_profile_from_settings(
        settings.model_copy(
            update={
                "external_db_live_query_dsn": settings.postgres_dsn.replace(
                    "postgresql+psycopg://", "postgresql://", 1
                ),
                "external_db_discovery_schemas": [TEST_SCHEMA, "operations"],
                "external_db_discovery_max_tables": 3,
                "external_db_discovery_max_columns_per_table": 5,
            }
        )
    )


def runtime_for(settings: Settings) -> SelfHostedPostgresDiscoveryRuntime:
    return SelfHostedPostgresDiscoveryRuntime(
        profile=discovery_profile(settings),
        lease_scoped_secret_resolution_enabled=False,
        runtime_egress_enforcement_enabled=True,
    )


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
        # The local volume is retained across runs; make setup idempotent.
        for stale_lease_id in (LEASE_ID, "lease_discovery_integration_stale"):
            existing = repository.get_connector_credential_lease(TENANT_A, stale_lease_id)
            if existing is not None:
                session.delete(existing)
        existing_policy = repository.get_connector_egress_policy(TENANT_A, POLICY_ID)
        if existing_policy is not None:
            session.delete(existing_policy)
        # Observations from earlier runs of this file would flip first-run
        # drift to "changed"; the throwaway scope makes deletion safe.
        session.execute(
            sqlalchemy_delete(DataAssetResourceObservation).where(
                DataAssetResourceObservation.tenant_id == TENANT_A,
                DataAssetResourceObservation.connector_id == CONNECTOR_ID,
            )
        )
        session.flush()
        now = datetime.now(UTC)
        repository.create_connector_credential_lease(
            ConnectorCredentialLeaseCreate(
                tenant_id=TENANT_A,
                connector_id=CONNECTOR_ID,
                handle_id="cred_external_db_readonly",
                lease_id=LEASE_ID,
                status="active",
                requested_by="axis-operator",
                lease_purpose="source_discovery_integration",
                secret_provider="env",
                secret_ref="AXIS_EXTERNAL_DB_DISCOVERY_TEST_DSN",
                vault_kms_policy={},
                permission_decision={"allowed": True, "reason": "all_required_scopes_present"},
                lease_result={
                    "status": "lease_executed",
                    "provider_lease_ref": (f"self-hosted-vault-kms://{TENANT_A}/{LEASE_ID}"),
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
                    "approved_endpoint_target_sha256": (_endpoint_target_sha256("localhost:5432")),
                },
                evidence_refs=[],
                audit_event_type="connector.egress_policy.registered",
            )
        )
    return factory


def _endpoint_target_sha256(endpoint: str) -> str:
    import hashlib

    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def verify_request(**overrides) -> ConnectorSourceVerifyRequest:
    payload = {
        "tenant_id": TENANT_A,
        "connector_id": CONNECTOR_ID,
        "verification_id": "verify_integration_001",
        "requested_by": "axis-operator",
        "connection_profile_id": PROFILE_ID,
        "credential_lease_id": LEASE_ID,
        "egress_policy_id": POLICY_ID,
        "actor_scopes": [SCOPE],
    }
    payload.update(overrides)
    return ConnectorSourceVerifyRequest(**payload)


def discovery_request(**overrides) -> ConnectorSourceDiscoveryRequest:
    payload = {
        "tenant_id": TENANT_A,
        "connector_id": CONNECTOR_ID,
        "discovery_id": "discovery_integration_001",
        "requested_by": "axis-operator",
        "connection_profile_id": PROFILE_ID,
        "schema_name": TEST_SCHEMA,
        "credential_lease_id": LEASE_ID,
        "egress_policy_id": POLICY_ID,
        "actor_scopes": [SCOPE],
    }
    payload.update(overrides)
    return ConnectorSourceDiscoveryRequest(**payload)


def test_verify_connects_to_real_source_and_reports_database_name(
    settings, session_factory, source_schema
) -> None:
    with session_scope(session_factory) as session:
        outcome = record_connector_source_verification(
            AxisPersistenceRepository(session),
            runtime=runtime_for(settings),
            request=verify_request(),
            principal_scopes=[SCOPE],
        )

    assert outcome.result.status == "source_verified"
    assert outcome.result.database_name == "axis"
    assert outcome.result.evidence_summary["runtime_egress_enforcement"] == (
        "enforced_target_match"
    )
    assert outcome.result.evidence_summary["row_data_read"] == "false"


def test_discovery_enumerates_real_tables_with_fingerprints(
    settings, session_factory, source_schema
) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        outcome = record_connector_source_discovery(
            repository,
            runtime=runtime_for(settings),
            request=discovery_request(),
            principal_scopes=[SCOPE],
        )

    assert outcome.result.status == "discovery_completed"
    table_names = [table.table_name for table in outcome.result.tables]
    assert table_names == ["production_orders", "quality_checks"]
    orders = outcome.result.tables[0]
    assert orders.column_names == ["order_id", "asset_id", "status"]
    assert len(orders.column_fingerprint) == 64
    assert not orders.columns_truncated


def test_repeat_discovery_after_column_addition_marks_drift_changed(
    settings, session_factory, source_schema, engine
) -> None:
    def run(discovery_id: str):
        with session_scope(session_factory) as session:
            return record_connector_source_discovery(
                AxisPersistenceRepository(session),
                runtime=runtime_for(settings),
                request=discovery_request(discovery_id=discovery_id),
                principal_scopes=[SCOPE],
            )

    first = run("discovery_drift_r1")
    assert all(obs.observation.drift_state == "added" for obs in first.observations)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"ALTER TABLE {TEST_SCHEMA}.quality_checks "
                "ADD COLUMN severity text NOT NULL DEFAULT 'low'"
            )
        )
    second = run("discovery_drift_r2")

    by_resource = {
        obs.observation.resource_name: obs.observation.drift_state for obs in second.observations
    }
    assert by_resource[f"{TEST_SCHEMA}.production_orders"] == "unchanged"
    assert by_resource[f"{TEST_SCHEMA}.quality_checks"] == "changed"
    quality_observation = next(
        obs
        for obs in second.observations
        if obs.observation.resource_name == f"{TEST_SCHEMA}.quality_checks"
    )
    assert quality_observation.observation.observation_count == 2
    assert quality_observation.observation.previous_fingerprint is not None
    assert (
        quality_observation.observation.schema_fingerprint
        != quality_observation.observation.previous_fingerprint
    )


def test_empty_allowlisted_schema_completes_with_zero_tables(
    settings, session_factory, source_schema, engine
) -> None:
    from axis_api.connector_postgres_discovery import (
        postgres_discovery_profile_from_settings,
    )

    empty_schema = f"{TEST_SCHEMA}_empty"
    with engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {empty_schema}"))
    runtime = SelfHostedPostgresDiscoveryRuntime(
        profile=postgres_discovery_profile_from_settings(
            settings.model_copy(
                update={
                    "external_db_live_query_dsn": settings.postgres_dsn.replace(
                        "postgresql+psycopg://", "postgresql://", 1
                    ),
                    "external_db_discovery_schemas": [TEST_SCHEMA, empty_schema],
                    "external_db_runtime_egress_enforcement_enabled": True,
                }
            )
        ),
        runtime_egress_enforcement_enabled=True,
    )
    try:
        with session_scope(session_factory) as session:
            outcome = record_connector_source_discovery(
                AxisPersistenceRepository(session),
                runtime=runtime,
                request=discovery_request(schema_name=empty_schema),
                principal_scopes=[SCOPE],
            )
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA}_empty"))

    assert outcome.result.status == "discovery_completed"
    assert outcome.result.tables == []
    assert outcome.observations == []


def test_table_bound_truncates_honestly(settings, session_factory, source_schema, engine) -> None:
    with engine.begin() as connection:
        for index in range(5):
            connection.execute(
                text(f"CREATE TABLE {TEST_SCHEMA}.extra_table_{index} (id text PRIMARY KEY)")
            )

    with session_scope(session_factory) as session:
        outcome = record_connector_source_discovery(
            AxisPersistenceRepository(session),
            runtime=runtime_for(settings),
            request=discovery_request(),
            principal_scopes=[SCOPE],
        )

    # Profile pins max_tables=3; the source has 7 base tables.
    assert len(outcome.result.tables) == 3
    assert outcome.result.tables_truncated is True
    assert outcome.result.evidence_summary["tables_truncated"] == "true"


def _blocked_source_runtime(dsn: str) -> SelfHostedPostgresDiscoveryRuntime:
    from axis_api.connector_postgres_discovery import PostgresDiscoveryProfile

    return SelfHostedPostgresDiscoveryRuntime(
        profile=PostgresDiscoveryProfile(
            profile_id=PROFILE_ID,
            dsn=dsn,
            allowed_schemas=[TEST_SCHEMA],
            private_endpoint_ref=(
                f"private-endpoint://{TENANT_A}/persisted-operations-postgres-readonly"
            ),
            endpoint_target_sha256=_endpoint_target_sha256("localhost:5432"),
        ),
    )


def test_unreachable_source_classifies_as_source_unreachable(
    settings, session_factory, source_schema
) -> None:
    blocked_runtime = _blocked_source_runtime("postgresql://axis:axis@127.0.0.1:54329/axis")

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        verified = record_connector_source_verification(
            repository,
            runtime=blocked_runtime,
            request=verify_request(),
            principal_scopes=[SCOPE],
        )
        discovered = record_connector_source_discovery(
            repository,
            runtime=blocked_runtime,
            request=discovery_request(),
            principal_scopes=[SCOPE],
        )

    assert verified.result.block_reason == "source_unreachable"
    assert discovered.result.block_reason == "source_unreachable"
    assert discovered.result.tables == []


def test_auth_failure_classifies_as_auth_denied_without_leaking_material(
    settings, session_factory, source_schema
) -> None:
    blocked_runtime = _blocked_source_runtime(
        "postgresql://axis:not-the-password@localhost:5432/axis"
    )

    with session_scope(session_factory) as session:
        outcome = record_connector_source_verification(
            AxisPersistenceRepository(session),
            runtime=blocked_runtime,
            request=verify_request(),
            principal_scopes=[SCOPE],
        )

    assert outcome.result.block_reason == "auth_denied"
    body = str(outcome.result).lower()
    assert "not-the-password" not in body


def test_non_allowlisted_schema_blocks_before_connecting(
    settings, session_factory, source_schema
) -> None:
    with session_scope(session_factory) as session:
        outcome = record_connector_source_discovery(
            AxisPersistenceRepository(session),
            runtime=runtime_for(settings),
            request=discovery_request(schema_name="public"),
            principal_scopes=[SCOPE],
        )

    assert outcome.result.block_reason == "schema_not_allowlisted"
    assert outcome.observations == []


def test_full_api_path_discovers_real_tables_into_catalog(
    settings, session_factory, source_schema
) -> None:
    app = create_app(Settings(postgres_dsn=settings.postgres_dsn))
    app.state.session_factory = session_factory
    app.state.connector_source_discovery_runtime = connector_source_discovery_runtime_from_settings(
        Settings(
            postgres_dsn=settings.postgres_dsn,
            external_db_live_query_dsn=settings.postgres_dsn.replace(
                "postgresql+psycopg://", "postgresql://", 1
            ),
            connector_sync_execution_enabled=True,
            external_db_sync_execution_enabled=True,
            external_db_discovery_enabled=True,
            external_db_discovery_schemas=[TEST_SCHEMA, "operations"],
            external_db_runtime_egress_enforcement_enabled=True,
        )
    )
    client = TestClient(app)

    response = client.post(
        "/operations/connectors/external-db/discover",
        json={
            "tenant_id": TENANT_A,
            "connector_id": CONNECTOR_ID,
            "discovery_id": "discovery_api_real_001",
            "requested_by": "axis-operator",
            "connection_profile_id": PROFILE_ID,
            "schema_name": TEST_SCHEMA,
            "credential_lease_id": LEASE_ID,
            "egress_policy_id": POLICY_ID,
            "actor_scopes": [SCOPE],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["status"] == "discovery_completed"
    assert len(body["result"]["tables"]) == 2
    assert len(body["observations"]) == 2
    observation_names = {obs["observation"]["resource_name"] for obs in body["observations"]}
    assert observation_names == {
        f"{TEST_SCHEMA}.production_orders",
        f"{TEST_SCHEMA}.quality_checks",
    }

    resources = client.get(
        f"/data/assets/source:{CONNECTOR_ID}:default/resources",
        params={"tenant_id": TENANT_A},
    )
    assert resources.status_code == 200
    listed = resources.json()["resources"]
    assert {resource["resource_name"] for resource in listed} == observation_names
    assert all(resource["last_source_kind"] == "postgres_discovery" for resource in listed)
