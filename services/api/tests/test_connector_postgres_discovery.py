from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.connector_postgres_discovery import (
    ConnectorSourceDiscoveryExecution,
    ConnectorSourceDiscoveryRequest,
    ConnectorSourceDiscoveryResult,
    ConnectorSourceOperationError,
    ConnectorSourceVerificationExecution,
    ConnectorSourceVerificationResult,
    ConnectorSourceVerifyRequest,
    DeferredConnectorSourceDiscoveryRuntime,
    DiscoveredSourceTable,
    PostgresDiscoveryProfile,
    SelfHostedPostgresDiscoveryRuntime,
    SourceScopeDenied,
    _classify_postgres_error,
    connector_source_discovery_runtime_from_settings,
    postgres_discovery_profile_from_settings,
    record_connector_source_discovery,
    record_connector_source_verification,
)
from axis_api.db import session_scope
from axis_api.identity import OidcPrincipal
from axis_api.models import AuditEvent, Base, DataAssetResourceObservation
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorCredentialLeaseCreate,
    ConnectorEgressPolicyCreate,
    TenantCreate,
)

TENANT_A = "tenant_demo_manufacturing"
CONNECTOR_ID = "external_db_operational_mirror"
PROFILE_ID = "profile_postgres_discovery_readonly"
LEASE_ID = "lease_external_db_discovery_001"
POLICY_ID = "egress_policy_private_endpoint_ops"
SCOPE = "connectors:source:discover"


def verify_request(**overrides) -> ConnectorSourceVerifyRequest:
    payload = {
        "tenant_id": TENANT_A,
        "connector_id": CONNECTOR_ID,
        "verification_id": "verify_unit_001",
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
        "discovery_id": "discovery_unit_001",
        "requested_by": "axis-operator",
        "connection_profile_id": PROFILE_ID,
        "schema_name": "operations",
        "credential_lease_id": LEASE_ID,
        "egress_policy_id": POLICY_ID,
        "actor_scopes": [SCOPE],
    }
    payload.update(overrides)
    return ConnectorSourceDiscoveryRequest(**payload)


class StubDiscoveryRuntime:
    """Records the execution inputs it received; returns canned results."""

    def __init__(
        self,
        *,
        verification: ConnectorSourceVerificationResult | None = None,
        discovery: ConnectorSourceDiscoveryResult | None = None,
    ) -> None:
        self.verification_result = verification or ConnectorSourceVerificationResult(
            adapter="stub",
            status="source_verified",
            database_name="axis_external",
            evidence_summary={"runtime_status": "source_verified"},
        )
        self.discovery_result = discovery or ConnectorSourceDiscoveryResult(
            adapter="stub",
            status="discovery_completed",
            discovered_schema="operations",
            tables=[
                DiscoveredSourceTable(
                    schema_name="operations",
                    table_name="production_orders",
                    column_names=["order_id", "asset_id"],
                    column_fingerprint="a" * 64,
                    columns_truncated=False,
                ),
            ],
        )
        self.verification_inputs: list[ConnectorSourceVerificationExecution] = []
        self.discovery_inputs: list[ConnectorSourceDiscoveryExecution] = []

    def verify(
        self, request: ConnectorSourceVerificationExecution
    ) -> ConnectorSourceVerificationResult:
        self.verification_inputs.append(request)
        return self.verification_result

    def discover(
        self, request: ConnectorSourceDiscoveryExecution
    ) -> ConnectorSourceDiscoveryResult:
        self.discovery_inputs.append(request)
        return self.discovery_result


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
        repository = AxisPersistenceRepository(session)
        repository.create_tenant(
            TenantCreate(
                tenant_id=TENANT_A,
                display_name="Ravenna Works",
                description="Plant Operations Cockpit",
                created_by="test",
            )
        )
        now = datetime.now(UTC)
        repository.create_connector_credential_lease(
            ConnectorCredentialLeaseCreate(
                tenant_id=TENANT_A,
                connector_id=CONNECTOR_ID,
                handle_id="cred_external_db_readonly",
                lease_id=LEASE_ID,
                status="active",
                requested_by="axis-operator",
                lease_purpose="source_discovery",
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
                    "approved_endpoint_target_sha256": "b" * 64,
                },
                evidence_refs=[],
                audit_event_type="connector.egress_policy.registered",
            )
        )
    yield factory
    engine.dispose()


def audit_events(factory: sessionmaker, event_type: str) -> list[AuditEvent]:
    with session_scope(factory) as session:
        return list(
            session.scalars(select(AuditEvent).where(AuditEvent.event_type == event_type)).all()
        )


def observations(factory: sessionmaker) -> list[DataAssetResourceObservation]:
    with session_scope(factory) as session:
        return list(session.scalars(select(DataAssetResourceObservation)).all())


# ---------------------------------------------------------------------------
# Runtime contract


def test_deferred_runtime_reports_deferred_without_external_query() -> None:
    runtime = DeferredConnectorSourceDiscoveryRuntime()

    verified = runtime.verify(
        ConnectorSourceVerificationExecution(
            tenant_id=TENANT_A,
            connector_id=CONNECTOR_ID,
            verification_id="verify_x",
            requested_by="axis-operator",
            connection_profile_id=PROFILE_ID,
        )
    )
    discovered = runtime.discover(
        ConnectorSourceDiscoveryExecution(
            tenant_id=TENANT_A,
            connector_id=CONNECTOR_ID,
            discovery_id="discovery_x",
            requested_by="axis-operator",
            connection_profile_id=PROFILE_ID,
            schema_name="operations",
        )
    )

    assert verified.status == "verification_deferred"
    assert discovered.status == "discovery_deferred"
    assert (
        verified.evidence_summary["external_query_started"] == "false"
        and discovered.evidence_summary["external_query_started"] == "false"
    )


def test_profile_rejects_unsafe_schema_identifiers() -> None:
    with pytest.raises(ValueError, match="not a safe Postgres identifier"):
        PostgresDiscoveryProfile(
            profile_id=PROFILE_ID,
            dsn="postgresql://readonly.local/axis_external",
            allowed_schemas=["operations; DROP SCHEMA public"],
            private_endpoint_ref="private-endpoint://test",
            endpoint_target_sha256="b" * 64,
        )


def test_self_hosted_runtime_blocks_when_profile_missing() -> None:
    runtime = SelfHostedPostgresDiscoveryRuntime(profile=None)

    verified = runtime.verify(
        ConnectorSourceVerificationExecution(
            tenant_id=TENANT_A,
            connector_id=CONNECTOR_ID,
            verification_id="verify_x",
            requested_by="axis-operator",
            connection_profile_id=PROFILE_ID,
        )
    )
    discovered = runtime.discover(
        ConnectorSourceDiscoveryExecution(
            tenant_id=TENANT_A,
            connector_id=CONNECTOR_ID,
            discovery_id="discovery_x",
            requested_by="axis-operator",
            connection_profile_id=PROFILE_ID,
            schema_name="operations",
        )
    )

    assert verified.block_reason == "profile_not_configured"
    assert discovered.block_reason == "profile_not_configured"


def test_error_classification_maps_sqlstate_and_types() -> None:
    unreachable = psycopg_error("OperationalError", sqlstate=None)
    auth_denied = psycopg_error("OperationalError", sqlstate="28P01")
    permission_denied = psycopg_error("ProgrammingError", sqlstate="42501")
    missing_database = psycopg_error("OperationalError", sqlstate="3D000")
    other = psycopg_error("ProgrammingError", sqlstate="42601")

    assert _classify_postgres_error(unreachable) == "source_unreachable"
    assert _classify_postgres_error(auth_denied) == "auth_denied"
    assert _classify_postgres_error(permission_denied) == "permission_denied"
    assert _classify_postgres_error(missing_database) == "source_database_missing"
    assert _classify_postgres_error(other) == "query_failed"


def psycopg_error(name: str, *, sqlstate: str | None):
    import psycopg

    error_type = getattr(psycopg.errors, name, None)
    if error_type is None:
        error_type = getattr(psycopg, name)
    exc = error_type("synthetic failure")
    exc.sqlstate = sqlstate
    return exc


# ---------------------------------------------------------------------------
# Governed operations


def test_verification_requires_source_discovery_scope(session_factory) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(SourceScopeDenied):
            record_connector_source_verification(
                repository,
                runtime=StubDiscoveryRuntime(),
                request=verify_request(actor_scopes=["connectors:read"]),
                principal_scopes=["connectors:read"],
            )


def test_discovery_requires_source_discovery_scope(session_factory) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(SourceScopeDenied):
            record_connector_source_discovery(
                repository,
                runtime=StubDiscoveryRuntime(),
                request=discovery_request(),
                principal_scopes=[],
            )


def test_unknown_lease_fails_closed(session_factory) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(ConnectorSourceOperationError) as exc_info:
            record_connector_source_verification(
                repository,
                runtime=StubDiscoveryRuntime(),
                request=verify_request(credential_lease_id="lease_ghost"),
                principal_scopes=[SCOPE],
            )
    assert exc_info.value.reason == "credential_lease_not_found"


def test_lease_of_another_connector_is_rejected(session_factory) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        _persist_lease(
            repository,
            lease_id="lease_other_connector",
            connector_id="file_csv_manufacturing_assets",
        )
        with pytest.raises(ConnectorSourceOperationError) as exc_info:
            record_connector_source_verification(
                repository,
                runtime=StubDiscoveryRuntime(),
                request=verify_request(credential_lease_id="lease_other_connector"),
                principal_scopes=[SCOPE],
            )
    assert exc_info.value.reason == "credential_lease_not_found"


def test_unexecuted_lease_is_rejected_like_live_reads(session_factory) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        _persist_lease(
            repository,
            lease_id="lease_deferred_only",
            connector_id=CONNECTOR_ID,
            lease_result={"status": "lease_deferred", "provider_lease_ref": ""},
        )
        with pytest.raises(ConnectorSourceOperationError) as exc_info:
            record_connector_source_discovery(
                repository,
                runtime=StubDiscoveryRuntime(),
                request=discovery_request(credential_lease_id="lease_deferred_only"),
                principal_scopes=[SCOPE],
            )
    assert exc_info.value.reason == "credential_lease_not_executed"


def test_lease_returning_secret_material_is_rejected(session_factory) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        _persist_lease(
            repository,
            lease_id="lease_leaky",
            connector_id=CONNECTOR_ID,
            # Realistic leaky-broker shape: the contract is string-valued,
            # and "true" must be rejected by the posture gate.
            lease_result={
                "status": "lease_executed",
                "provider_lease_ref": "ref-1",
                "secret_material_returned": "true",
            },
        )
        with pytest.raises(ConnectorSourceOperationError) as exc_info:
            record_connector_source_verification(
                repository,
                runtime=StubDiscoveryRuntime(),
                request=verify_request(credential_lease_id="lease_leaky"),
                principal_scopes=[SCOPE],
            )
    assert exc_info.value.reason == "credential_lease_not_executed"


def _persist_lease(
    repository: AxisPersistenceRepository,
    *,
    lease_id: str,
    connector_id: str,
    lease_result: dict | None = None,
) -> None:
    now = datetime.now(UTC)
    repository.create_connector_credential_lease(
        ConnectorCredentialLeaseCreate(
            tenant_id=TENANT_A,
            connector_id=connector_id,
            handle_id="cred_extra",
            lease_id=lease_id,
            status="active",
            requested_by="axis-operator",
            lease_purpose="unit_fixture",
            secret_provider="env",
            secret_ref="SOME_REF",
            vault_kms_policy={},
            permission_decision={
                "allowed": True,
                "reason": "all_required_scopes_present",
            },
            lease_result=lease_result
            or {
                "status": "lease_executed",
                "provider_lease_ref": f"self-hosted-vault-kms://{TENANT_A}/{lease_id}",
                "secret_material_returned": "false",
            },
            granted_at=now,
            expires_at=now + timedelta(hours=1),
            renewal_due_at=now + timedelta(minutes=45),
        )
    )


def test_mismatched_egress_policy_is_rejected(session_factory) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        with pytest.raises(ConnectorSourceOperationError) as exc_info:
            record_connector_source_discovery(
                repository,
                runtime=StubDiscoveryRuntime(),
                request=discovery_request(connection_profile_id="profile_other"),
                principal_scopes=[SCOPE],
            )
    assert exc_info.value.reason == "egress_policy_profile_mismatch"


def test_completed_discovery_records_observations_and_audit(session_factory) -> None:
    runtime = StubDiscoveryRuntime()

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        outcome = record_connector_source_discovery(
            repository,
            runtime=runtime,
            request=discovery_request(),
            principal_scopes=[SCOPE],
        )

    assert outcome.result.status == "discovery_completed"
    execution_input = runtime.discovery_inputs[0]
    # Lease evidence resolved server-side from the persisted record.
    assert execution_input.credential_lease_result["status"] == "lease_executed"
    assert execution_input.credential_secret_provider == "env"
    assert execution_input.credential_secret_ref == ("AXIS_EXTERNAL_DB_DISCOVERY_TEST_DSN")
    assert execution_input.egress_policy_evidence["egress_policy_evidence_status"] == ("validated")
    stored = observations(session_factory)
    assert len(stored) == 1
    assert stored[0].resource_name == "operations.production_orders"
    assert stored[0].last_source_kind == "postgres_discovery"
    assert stored[0].drift_state == "added"
    discover_events = audit_events(session_factory, "connector.source.discover")
    observed_events = audit_events(session_factory, "data.resource.observed")
    assert len(discover_events) == 1 and len(observed_events) == 1
    assert discover_events[0].payload["discovered_table_count"] == "1"
    assert discover_events[0].payload["credential_material_returned"] == "false"


def test_blocked_discovery_records_audit_but_no_observation(session_factory) -> None:
    blocked_result = ConnectorSourceDiscoveryResult(
        adapter=SelfHostedPostgresDiscoveryRuntime.adapter_name,
        status="discovery_blocked_source_unreachable",
        block_reason="source_unreachable",
    )
    runtime = StubDiscoveryRuntime(discovery=blocked_result)

    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        outcome = record_connector_source_discovery(
            repository,
            runtime=runtime,
            request=discovery_request(),
            principal_scopes=[SCOPE],
        )

    assert outcome.result.block_reason == "source_unreachable"
    assert outcome.observations == []
    assert observations(session_factory) == []
    events = audit_events(session_factory, "connector.source.discover")
    assert len(events) == 1
    assert events[0].payload["status"] == "discovery_blocked_source_unreachable"


def test_verification_records_audit_with_public_safe_payload(session_factory) -> None:
    with session_scope(session_factory) as session:
        repository = AxisPersistenceRepository(session)
        outcome = record_connector_source_verification(
            repository,
            runtime=StubDiscoveryRuntime(),
            request=verify_request(),
            principal_scopes=[SCOPE],
        )

    assert outcome.result.database_name == "axis_external"
    events = audit_events(session_factory, "connector.source.verify")
    assert len(events) == 1
    payload_text = str(events[0].payload).lower()
    assert "password" not in payload_text
    assert "postgresql://" not in payload_text


def test_repeat_discovery_marks_drift_unchanged(session_factory) -> None:
    for discovery_id in ("discovery_r1", "discovery_r2"):
        with session_scope(session_factory) as session:
            repository = AxisPersistenceRepository(session)
            record_connector_source_discovery(
                repository,
                runtime=StubDiscoveryRuntime(),
                request=discovery_request(discovery_id=discovery_id),
                principal_scopes=[SCOPE],
            )
    stored = observations(session_factory)
    assert len(stored) == 1
    assert stored[0].observation_count == 2
    assert stored[0].drift_state == "unchanged"


# ---------------------------------------------------------------------------
# Settings wiring


def test_settings_default_keeps_discovery_deferred() -> None:
    settings = Settings(postgres_dsn="sqlite+pysqlite://")

    runtime = connector_source_discovery_runtime_from_settings(settings)

    assert isinstance(runtime, DeferredConnectorSourceDiscoveryRuntime)


def test_settings_enablement_builds_self_hosted_runtime_with_bounds() -> None:
    settings = Settings(
        postgres_dsn="postgresql://readonly.local/axis_external",
        external_db_live_query_dsn="postgresql://readonly.local/axis_external",
        connector_sync_execution_enabled=True,
        external_db_sync_execution_enabled=True,
        external_db_discovery_enabled=True,
        external_db_discovery_schemas=["operations", "quality"],
        external_db_discovery_max_tables=7,
        external_db_discovery_max_columns_per_table=11,
    )

    runtime = connector_source_discovery_runtime_from_settings(settings)

    assert isinstance(runtime, SelfHostedPostgresDiscoveryRuntime)
    assert runtime.profile is not None
    assert runtime.profile.max_tables == 7
    assert runtime.profile.max_columns_per_table == 11
    assert runtime.profile.allows_schema("operations")
    assert not runtime.profile.allows_schema("public")


def test_discovery_profile_requires_pinned_target_or_static_dsn() -> None:
    settings = Settings(postgres_dsn="sqlite+pysqlite://")
    assert postgres_discovery_profile_from_settings(settings) is None

    pinned = Settings(
        postgres_dsn="sqlite+pysqlite://",
        external_db_lease_scoped_secret_resolution_enabled=True,
        external_db_live_query_endpoint_target_sha256="c" * 64,
        external_db_discovery_enabled=True,
    )
    profile = postgres_discovery_profile_from_settings(pinned)
    assert profile is not None
    assert profile.dsn.endswith(".invalid:5432/axis")


# ---------------------------------------------------------------------------
# API surface


def build_client(factory: sessionmaker, runtime) -> TestClient:
    from axis_api.main import create_app

    app = create_app(Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    app.state.connector_source_discovery_runtime = runtime
    return TestClient(app)


@pytest.mark.parametrize(
    "route",
    ["/operations/connectors/external-db/verify-source", "/operations/connectors/sources/verify"],
)
def test_verify_route_returns_outcome_contract(session_factory, route) -> None:
    client = build_client(session_factory, StubDiscoveryRuntime())

    response = client.post(
        route,
        json={
            "tenant_id": TENANT_A,
            "connector_id": CONNECTOR_ID,
            "verification_id": "verify_api_001",
            "requested_by": "axis-operator",
            "connection_profile_id": PROFILE_ID,
            "credential_lease_id": LEASE_ID,
            "egress_policy_id": POLICY_ID,
            "actor_scopes": [SCOPE],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["status"] == "source_verified"
    assert body["correlation_ref"].startswith(f"source-verify://{TENANT_A}/")


@pytest.mark.parametrize(
    "route",
    ["/operations/connectors/external-db/discover", "/operations/connectors/sources/discover"],
)
def test_discovery_route_rejects_missing_scope(session_factory, route) -> None:
    client = build_client(session_factory, StubDiscoveryRuntime())

    response = client.post(
        route,
        json={
            "tenant_id": TENANT_A,
            "connector_id": CONNECTOR_ID,
            "discovery_id": "discovery_api_001",
            "requested_by": "axis-operator",
            "connection_profile_id": PROFILE_ID,
            "schema_name": "operations",
            "credential_lease_id": LEASE_ID,
            "egress_policy_id": POLICY_ID,
            "actor_scopes": [],
        },
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["reason"] == f"missing_scope:{SCOPE}"


@pytest.mark.parametrize(
    "route",
    ["/operations/connectors/external-db/discover", "/operations/connectors/sources/discover"],
)
def test_discovery_route_maps_unknown_policy_to_404(session_factory, route) -> None:
    client = build_client(session_factory, StubDiscoveryRuntime())

    response = client.post(
        route,
        json={
            "tenant_id": TENANT_A,
            "connector_id": CONNECTOR_ID,
            "discovery_id": "discovery_api_002",
            "requested_by": "axis-operator",
            "connection_profile_id": PROFILE_ID,
            "schema_name": "operations",
            "credential_lease_id": LEASE_ID,
            "egress_policy_id": "policy_ghost",
            "actor_scopes": [SCOPE],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "egress_policy_not_found"


@pytest.mark.parametrize(
    "route",
    ["/operations/connectors/external-db/discover", "/operations/connectors/sources/discover"],
)
def test_discovery_route_rejects_cross_tenant_principal(session_factory, route) -> None:
    client = build_client(session_factory, StubDiscoveryRuntime())
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="actor-b",
            tenant_id="tenant_other_plant",
            scopes=[SCOPE],
        )
    )

    response = client.post(
        route,
        json={
            "tenant_id": TENANT_A,
            "connector_id": CONNECTOR_ID,
            "discovery_id": "discovery_api_003",
            "requested_by": "actor-b",
            "connection_profile_id": PROFILE_ID,
            "schema_name": "operations",
            "credential_lease_id": LEASE_ID,
            "egress_policy_id": POLICY_ID,
        },
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "tenant_mismatch"


class StaticIdentityVerifier:
    def __init__(self, principal: OidcPrincipal) -> None:
        self.principal = principal

    def verify_authorization_header(self, authorization: str | None) -> OidcPrincipal:
        assert authorization == "Bearer valid-token"
        return self.principal


def test_openapi_declares_both_source_routes(session_factory) -> None:
    client = build_client(session_factory, StubDiscoveryRuntime())
    paths = client.app.openapi()["paths"]

    assert "/operations/connectors/external-db/verify-source" in paths
    assert "/operations/connectors/external-db/discover" in paths
