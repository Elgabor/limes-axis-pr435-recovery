from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.connector_postgres_discovery import (
    ConnectorSourceOperationError,
)
from axis_api.connector_source_activation import (
    BINDING_PENDING_INGESTION_STATUS,
    ConnectorSourceActivationConflict,
    ConnectorSourceActivationError,
    ConnectorSourceActivationRequest,
    SourceActivationScopeDenied,
    list_connector_source_bindings,
    record_connector_source_activation,
)
from axis_api.db import session_scope
from axis_api.identity import OidcPrincipal
from axis_api.models import (
    AuditEvent,
    Base,
    ConnectorSourceBinding,
)
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorCredentialLeaseCreate,
    ConnectorEgressPolicyCreate,
    DataResourceObservationCreate,
    TenantCreate,
)

TENANT_A = "tenant_demo_manufacturing"
TENANT_B = "tenant_other_plant"
CONNECTOR_ID = "external_db_operational_mirror"
PROFILE_ID = "profile_postgres_discovery_readonly"
LEASE_ID = "lease_external_db_discovery_001"
POLICY_ID = "egress_policy_private_endpoint_ops"
DISCOVERY_SCOPE = "connectors:source:discover"
ACTIVATION_SCOPE = "connectors:source:activate"
FINGERPRINT_A = "a" * 64
FINGERPRINT_B = "b" * 64

RESOURCE_1 = "operations.production_orders"
RESOURCE_2 = "operations.quality_checks"


def selection(binding_id: str, resource_name: str, fingerprint: str) -> dict:
    return {
        "binding_id": binding_id,
        "resource_name": resource_name,
        "expected_schema_fingerprint": fingerprint,
    }


def activation_request(**overrides) -> ConnectorSourceActivationRequest:
    payload = {
        "tenant_id": TENANT_A,
        "connector_id": CONNECTOR_ID,
        "activation_id": "activation_unit_001",
        "requested_by": "axis-operator",
        "connection_profile_id": PROFILE_ID,
        "credential_lease_id": LEASE_ID,
        "egress_policy_id": POLICY_ID,
        "activation_reason": "Prepare governed ingestion for discovered plant tables.",
        "selections": [selection("binding_unit_001", RESOURCE_1, FINGERPRINT_A)],
        "actor_scopes": [ACTIVATION_SCOPE],
    }
    payload.update(overrides)
    return ConnectorSourceActivationRequest(**payload)


@pytest.fixture
def session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = factory_for(engine)
    seed_tenant_governance(factory, TENANT_A)
    yield factory
    engine.dispose()


def factory_for(engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def seed_tenant_governance(
    factory,
    tenant_id: str = TENANT_A,
    *,
    with_connector_records: bool = True,
) -> None:
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.create_tenant(
            TenantCreate(
                tenant_id=tenant_id,
                display_name="Ravenna Works",
                description="Plant Operations Cockpit",
                created_by="test",
            )
        )
        if not with_connector_records:
            return
        now = datetime.now(UTC)
        repository.create_connector_credential_lease(
            ConnectorCredentialLeaseCreate(
                tenant_id=tenant_id,
                connector_id=CONNECTOR_ID,
                handle_id=f"cred_external_db_readonly_{tenant_id}",
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
                    "provider_lease_ref": f"self-hosted-vault-kms://{tenant_id}/{LEASE_ID}",
                    "secret_material_returned": "false",
                },
                granted_at=now,
                expires_at=now + timedelta(hours=1),
                renewal_due_at=now + timedelta(minutes=45),
            )
        )
        repository.create_connector_egress_policy(
            ConnectorEgressPolicyCreate(
                tenant_id=tenant_id,
                connector_id=CONNECTOR_ID,
                policy_id=POLICY_ID,
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
                    "approved_endpoint_target_sha256": "c" * 64,
                },
                evidence_refs=[],
                audit_event_type="connector.egress_policy.registered",
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
                observed_by="e2e-discovery-lane",
                source_kind="postgres_discovery",
            )
        )


def bindings(factory) -> list[ConnectorSourceBinding]:
    with session_scope(factory) as session:
        return list(session.scalars(select(ConnectorSourceBinding)).all())


def audit_events(factory, event_type: str) -> list[AuditEvent]:
    with session_scope(factory) as session:
        return list(
            session.scalars(select(AuditEvent).where(AuditEvent.event_type == event_type)).all()
        )


def activate(factory, request: ConnectorSourceActivationRequest, **kwargs):
    with session_scope(factory) as session:
        return record_connector_source_activation(
            AxisPersistenceRepository(session),
            request=request,
            **{"principal_scopes": [ACTIVATION_SCOPE], "max_selections": 20, **kwargs},
        )


# ---------------------------------------------------------------------------
# Gate order and evidence


def test_activation_requires_scope(session_factory) -> None:
    with pytest.raises(SourceActivationScopeDenied) as excinfo:
        activate(session_factory, activation_request(), principal_scopes=[])
    assert excinfo.value.required_scope == ACTIVATION_SCOPE


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"credential_lease_id": "lease_ghost"}, "credential_lease_not_found"),
        ({"egress_policy_id": "policy_ghost"}, "egress_policy_not_found"),
    ],
)
def test_unknown_references_fail_closed(session_factory, overrides, expected_reason) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    with pytest.raises(ConnectorSourceOperationError) as excinfo:
        activate(session_factory, activation_request(**overrides))
    assert excinfo.value.reason == expected_reason


def test_unexecuted_lease_is_rejected_like_live_reads(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    with session_scope(session_factory) as session:
        lease = AxisPersistenceRepository(session).get_connector_credential_lease(
            TENANT_A, LEASE_ID
        )
        lease.lease_result = {"status": "persisted", "secret_material_returned": "false"}
    with pytest.raises(ConnectorSourceOperationError) as excinfo:
        activate(session_factory, activation_request())
    assert excinfo.value.reason == "credential_lease_not_executed"


def test_lease_returning_secret_material_is_rejected(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    with session_scope(session_factory) as session:
        lease = AxisPersistenceRepository(session).get_connector_credential_lease(
            TENANT_A, LEASE_ID
        )
        lease.lease_result = {
            "status": "lease_executed",
            "provider_lease_ref": f"self-hosted-vault-kms://{TENANT_A}/{LEASE_ID}",
            "secret_material_returned": True,
        }
    with pytest.raises(ConnectorSourceOperationError) as excinfo:
        activate(session_factory, activation_request())
    assert excinfo.value.reason == "credential_lease_not_executed"


def test_cross_tenant_lease_never_authorizes(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    request = activation_request(tenant_id=TENANT_B)
    with pytest.raises(ConnectorSourceOperationError) as excinfo:
        activate(session_factory, request)
    assert excinfo.value.reason == "credential_lease_not_found"
    assert bindings(session_factory) == []


# ---------------------------------------------------------------------------
# Selection validation


def test_empty_selections_are_rejected_by_contract() -> None:
    with pytest.raises(ValidationError):
        ConnectorSourceActivationRequest.model_validate(
            {
                **activation_request().model_dump(),
                "selections": [],
            }
        )


def test_oversized_selection_is_rejected_with_bound(session_factory) -> None:
    selections = [
        selection(f"binding_bulk_{i:03d}", f"operations.table_{i:03d}", FINGERPRINT_A)
        for i in range(21)
    ]
    request = activation_request(selections=selections)
    with pytest.raises(ConnectorSourceActivationError) as excinfo:
        activate(session_factory, request)
    assert excinfo.value.reason == "selection_too_large"


def test_duplicate_binding_ids_are_rejected(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_2, FINGERPRINT_B)
    request = activation_request(
        selections=[
            selection("binding_dup_001", RESOURCE_1, FINGERPRINT_A),
            selection("binding_dup_001", RESOURCE_2, FINGERPRINT_B),
        ],
    )
    with pytest.raises(ConnectorSourceActivationError) as excinfo:
        activate(session_factory, request)
    assert excinfo.value.reason == "duplicate_binding_id"


def test_duplicate_resources_are_rejected(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    request = activation_request(
        selections=[
            selection("binding_dup_res_1", RESOURCE_1, FINGERPRINT_A),
            selection("binding_dup_res_2", RESOURCE_1, FINGERPRINT_A),
        ],
    )
    with pytest.raises(ConnectorSourceActivationError) as excinfo:
        activate(session_factory, request)
    assert excinfo.value.reason == "duplicate_resource_name"


@pytest.mark.parametrize(
    "resource_name",
    [
        "operations",  # not qualified
        "operations.",  # empty table part
        "operations.hard;drop",  # unsafe identifier characters
        "../etc.passwd",  # path-like traversal shape
        "operations.extra.table",  # more than two parts
    ],
)
def test_unsafe_resource_names_are_rejected(session_factory, resource_name) -> None:
    request = activation_request(
        selections=[selection("binding_unsafe_001", resource_name, FINGERPRINT_A)]
    )
    with pytest.raises(ConnectorSourceActivationError) as excinfo:
        activate(session_factory, request)
    assert excinfo.value.reason == "unsafe_resource_name"


def test_unsafe_binding_id_pattern_is_rejected_by_contract() -> None:
    with pytest.raises(ValidationError):
        ConnectorSourceActivationRequest.model_validate(
            {
                **activation_request().model_dump(),
                "selections": [selection("binding spaced!", RESOURCE_1, FINGERPRINT_A)],
            }
        )


def test_blank_activation_reason_is_rejected_by_contract() -> None:
    with pytest.raises(ValidationError):
        ConnectorSourceActivationRequest.model_validate(
            {**activation_request().model_dump(), "activation_reason": ""}
        )


# ---------------------------------------------------------------------------
# Observation truth: unknown resources and stale fingerprints


def test_unknown_resource_is_rejected(session_factory) -> None:
    request = activation_request()
    with pytest.raises(ConnectorSourceActivationError) as excinfo:
        activate(session_factory, request)
    assert excinfo.value.reason == "resource_not_observed"
    assert excinfo.value.selection_index == 0
    assert bindings(session_factory) == []


def test_stale_fingerprint_is_rejected_and_names_the_selection(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_2, FINGERPRINT_B)
    request = activation_request(
        selections=[
            selection("binding_ok_001", RESOURCE_1, FINGERPRINT_A),
            selection("binding_stale_002", RESOURCE_2, "9" * 64),
        ],
    )
    with pytest.raises(ConnectorSourceActivationError) as excinfo:
        activate(session_factory, request)
    assert excinfo.value.reason == "schema_fingerprint_stale"
    assert excinfo.value.selection_index == 1
    # Atomicity: nothing was written even though selection 0 was valid.
    assert bindings(session_factory) == []


# ---------------------------------------------------------------------------
# Conflicts and replay


def _fresh_factory():
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = factory_for(engine)
    seed_tenant_governance(factory)
    return engine, factory


def test_first_activation_persists_binding_and_audit() -> None:
    engine, factory = _fresh_factory()
    try:
        seed_observation(factory, RESOURCE_1, FINGERPRINT_A)
        outcome = activate(factory, activation_request())
        assert len(outcome.bindings) == 1
        view = outcome.bindings[0]
        assert view.outcome == "activated"
        assert view.status == "active"
        assert view.ingestion_status == BINDING_PENDING_INGESTION_STATUS
        stored = bindings(factory)
        assert len(stored) == 1
        assert stored[0].resource_name == RESOURCE_1
        assert stored[0].schema_fingerprint == FINGERPRINT_A
        events = audit_events(factory, "connector.source.bindings.activated")
        assert len(events) == 1
        payload = events[0].payload
        assert payload["binding_count"] == "1"
        assert payload["activated_count"] == "1"
        assert payload["replayed_count"] == "0"
        assert payload["ingestion_status"] == "pending_ingestion"
        assert payload["secret_material_returned"] == "false"
        assert "secret_ref" not in payload and "dsn" not in payload
        serialized = repr(payload)
        assert "postgresql://" not in serialized.lower()
        assert outcome.correlation_ref.startswith(f"source-activation://{TENANT_A}/")
    finally:
        engine.dispose()


def test_identical_resubmission_replays_without_new_rows_or_audit() -> None:
    engine, factory = _fresh_factory()
    try:
        seed_observation(factory, RESOURCE_1, FINGERPRINT_A)
        activate(factory, activation_request())
        replay = activate(factory, activation_request())
        assert len(replay.bindings) == 1
        assert replay.bindings[0].outcome == "replayed"
        assert len(bindings(factory)) == 1
        assert len(audit_events(factory, "connector.source.bindings.activated")) == 1
    finally:
        engine.dispose()


def test_different_binding_for_bound_resource_conflicts(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    activate(session_factory, activation_request())
    second = activation_request(
        activation_id="activation_unit_002",
        selections=[selection("binding_other_001", RESOURCE_1, FINGERPRINT_A)],
    )
    with pytest.raises(ConnectorSourceActivationConflict) as excinfo:
        activate(session_factory, second)
    assert excinfo.value.reason == "binding_already_active"
    assert len(bindings(session_factory)) == 1


def test_binding_id_in_use_by_other_resource_conflicts(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_2, FINGERPRINT_B)
    activate(session_factory, activation_request())
    second = activation_request(
        activation_id="activation_unit_003",
        selections=[selection("binding_unit_001", RESOURCE_2, FINGERPRINT_B)],
    )
    with pytest.raises(ConnectorSourceActivationConflict) as excinfo:
        activate(session_factory, second)
    assert excinfo.value.reason == "binding_id_in_use"
    assert len(bindings(session_factory)) == 1


def test_replay_after_drift_returns_prior_binding_deterministically(session_factory) -> None:
    """A replay identifies the prior submission; it is never a new claim."""
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    activate(session_factory, activation_request())
    with session_scope(session_factory) as session:
        observation = AxisPersistenceRepository(session).get_data_resource_observation(
            TENANT_A, CONNECTOR_ID, RESOURCE_1
        )
        observation.schema_fingerprint = "d" * 64
    replay = activate(session_factory, activation_request())
    assert replay.bindings[0].outcome == "replayed"
    assert len(bindings(session_factory)) == 1


# ---------------------------------------------------------------------------
# Batch behavior and read model


def test_batch_activates_multiple_tables_in_one_audit_event(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_2, FINGERPRINT_B)
    request = activation_request(
        activation_id="activation_unit_batch",
        selections=[
            selection("binding_batch_001", RESOURCE_1, FINGERPRINT_A),
            selection("binding_batch_002", RESOURCE_2, FINGERPRINT_B),
        ],
    )
    outcome = activate(session_factory, request)
    assert [view.resource_name for view in outcome.bindings] == [RESOURCE_1, RESOURCE_2]
    assert len(bindings(session_factory)) == 2
    assert len(audit_events(session_factory, "connector.source.bindings.activated")) == 1


def test_bindings_view_lists_active_bindings_deterministically(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    seed_observation(session_factory, RESOURCE_2, FINGERPRINT_B)
    activate(
        session_factory,
        activation_request(
            activation_id="activation_view_001",
            selections=[
                selection("binding_zz_later", RESOURCE_2, FINGERPRINT_B),
            ],
        ),
    )
    activate(
        session_factory,
        activation_request(
            activation_id="activation_view_002",
            selections=[
                selection("binding_aa_earlier", RESOURCE_1, FINGERPRINT_A),
            ],
        ),
    )
    with session_scope(session_factory) as session:
        view = list_connector_source_bindings(
            AxisPersistenceRepository(session),
            tenant_id=TENANT_A,
            connector_id=CONNECTOR_ID,
        )
        stored = list(
            session.scalars(select(ConnectorSourceBinding).where(
                ConnectorSourceBinding.tenant_id == TENANT_A
            ))
        )
    expected_ids = [
        record.binding_id
        for record in sorted(
            stored,
            key=lambda record: (record.activated_at, record.binding_id),
        )
    ]
    assert [view_.binding_id for view_ in view.bindings] == expected_ids


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
    "activation_id": "activation_api_001",
    "requested_by": "axis-operator",
    "connection_profile_id": PROFILE_ID,
    "credential_lease_id": LEASE_ID,
    "egress_policy_id": POLICY_ID,
    "activation_reason": "Prepare governed ingestion for discovered plant tables.",
    "selections": [selection("binding_api_001", RESOURCE_1, FINGERPRINT_A)],
    "actor_scopes": [ACTIVATION_SCOPE],
}


def test_activation_route_returns_outcome_contract(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    client = build_client(session_factory)
    response = client.post(
        "/operations/connectors/external-db/source-bindings", json=ROUTE_BODY
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["bindings"][0]["outcome"] == "activated"
    assert body["bindings"][0]["ingestion_status"] == "pending_ingestion"
    assert body["correlation_ref"].startswith(f"source-activation://{TENANT_A}/")


def test_bindings_route_returns_persisted_view(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    client = build_client(session_factory)
    activated = client.post(
        "/operations/connectors/external-db/source-bindings", json=ROUTE_BODY
    )
    assert activated.status_code == 200
    listed = client.get(
        "/operations/connectors/external-db/source-bindings",
        params={"tenant_id": TENANT_A, "connector_id": CONNECTOR_ID},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["bindings"][0]["binding_id"] == "binding_api_001"
    assert body["bindings"][0]["outcome"] == "activated"


def test_activation_route_rejects_missing_scope(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    client = build_client(session_factory)
    response = client.post(
        "/operations/connectors/external-db/source-bindings",
        json={**ROUTE_BODY, "actor_scopes": []},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["reason"] == f"missing_scope:{ACTIVATION_SCOPE}"
    assert detail["required_permission"] == ACTIVATION_SCOPE


def test_activation_route_maps_unknown_policy_to_404(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    client = build_client(session_factory)
    response = client.post(
        "/operations/connectors/external-db/source-bindings",
        json={**ROUTE_BODY, "egress_policy_id": "policy_ghost"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "egress_policy_not_found"


def test_activation_route_maps_stale_to_422_with_selection_index(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, "9" * 64)
    client = build_client(session_factory)
    response = client.post(
        "/operations/connectors/external-db/source-bindings", json=ROUTE_BODY
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["reason"] == "schema_fingerprint_stale"
    assert detail["selection_index"] == 0


def test_activation_route_maps_conflict_to_409(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    client = build_client(session_factory)
    first = client.post(
        "/operations/connectors/external-db/source-bindings", json=ROUTE_BODY
    )
    assert first.status_code == 200
    conflicting = client.post(
        "/operations/connectors/external-db/source-bindings",
        json={
            **ROUTE_BODY,
            "activation_id": "activation_api_002",
            "selections": [selection("binding_api_other", RESOURCE_1, FINGERPRINT_A)],
        },
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"]["reason"] == "binding_already_active"


def test_activation_route_rejects_cross_tenant_principal(session_factory) -> None:
    seed_observation(session_factory, RESOURCE_1, FINGERPRINT_A)
    client = build_client(session_factory)
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="actor-b",
            tenant_id=TENANT_B,
            scopes=[ACTIVATION_SCOPE],
        )
    )
    response = client.post(
        "/operations/connectors/external-db/source-bindings",
        json={**ROUTE_BODY, "requested_by": "actor-b"},
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


def test_openapi_declares_both_activation_routes(session_factory) -> None:
    client = build_client(session_factory)
    paths = client.app.openapi()["paths"]

    assert "/operations/connectors/external-db/source-bindings" in paths
