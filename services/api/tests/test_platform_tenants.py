import secrets
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.identity import OidcPrincipal
from axis_api.main import create_app
from axis_api.models import Actor, AuditEvent, Base, Tenant, TenantQuota
from axis_api.oidc_code_flow import (
    read_session_cookie,
    session_cookie_name,
    session_id_hash,
    sign_cookie,
)
from axis_api.persistence import (
    AxisPersistenceRepository,
    OidcBrowserSessionCreate,
    OidcBrowserSessionRevocation,
    TenantCreate,
    TenantQuotaUpsert,
)
from axis_api.platform_tenants import (
    TENANT_VOCABULARY_LABEL_MAX_LENGTH,
    TENANT_VOCABULARY_MAX_DOMAIN_LABELS,
    TenantProvisionConflict,
    TenantProvisionRequest,
    TenantQuotaKey,
    TenantQuotaUpdateRequest,
    TenantReactivateRequest,
    TenantRecord,
    TenantSuspendRequest,
    TenantVocabularyUpdateRequest,
    bootstrap_first_tenant,
)
from axis_api.tenant_admission import (
    TENANT_ADMISSION_CLAIMS_ONLY,
    TENANT_ADMISSION_REGISTERED_ONLY,
    UNREGISTERED_REQUEST_DENIED_AUDIT_EVENT_TYPE,
    tenant_admission_denial_reason,
)

OPERATOR_ACTOR = "axis-platform-operator-role"
OPERATOR_SCOPES = [
    "platform:tenant:operator",
    "platform:tenant:provision",
    "platform:tenant:suspend",
    "platform:tenant:read",
    "platform:tenant:quota",
    "platform:tenant:configure",
]
TENANT_ID = "tenant_acme_manufacturing"
SECOND_TENANT_ID = "tenant_beta_manufacturing"
RATE_LIMIT_TEST_PATH = "/identity/oidc/readiness"
SECOND_RATE_LIMIT_TEST_PATH = "/identity/oidc/onboarding"


class StaticIdentityVerifier:
    def __init__(self, principal: OidcPrincipal) -> None:
        self.principal = principal

    def verify_authorization_header(self, authorization: str | None) -> OidcPrincipal:
        assert authorization == "Bearer valid-token"
        return self.principal


def build_test_client(
    settings: Settings | None = None,
) -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    app = create_app(settings or Settings(postgres_dsn="sqlite+pysqlite://"))
    app.state.session_factory = factory
    return TestClient(app), factory


def provision_payload(
    *,
    tenant_id: str = TENANT_ID,
    display_name: str = "Acme Manufacturing",
    idempotency_key: str = "idem_provision_acme_v1",
    requested_by: str = OPERATOR_ACTOR,
    actor_scopes: list[str] | None = None,
    bootstrap_admin: dict | None = None,
) -> dict:
    payload = {
        "tenant_id": tenant_id,
        "display_name": display_name,
        "description": "Reference multi-tenant SaaS design partner.",
        "requested_by": requested_by,
        "actor_scopes": actor_scopes if actor_scopes is not None else OPERATOR_SCOPES,
        "idempotency_key": idempotency_key,
        "notes": ["Provisioned during platform tenant tests."],
    }
    payload["bootstrap_admin"] = (
        bootstrap_admin
        if bootstrap_admin is not None
        else {
            "actor_id": "acme-platform-admin-role",
            "display_name": "Acme platform admin",
            "scopes": ["platform:policy:author", "audit:read"],
        }
    )
    return payload


def bootstrap_tenant(
    factory: sessionmaker[Session],
    *,
    tenant_id: str = "tenant_axis_platform_ops",
    display_name: str = "Axis platform operators",
    idempotency_key: str = "idem_bootstrap_axis_platform_ops_v1",
) -> TenantRecord:
    request = TenantProvisionRequest.model_validate(
        provision_payload(
            tenant_id=tenant_id,
            display_name=display_name,
            idempotency_key=idempotency_key,
            bootstrap_admin={
                "actor_id": f"{tenant_id}-bootstrap-admin-role",
                "display_name": f"{display_name} bootstrap admin",
                "scopes": ["platform:tenant:operator"],
            },
        )
    )
    with session_scope(factory) as session:
        return bootstrap_first_tenant(AxisPersistenceRepository(session), request)


def suspend_payload(*, actor_scopes: list[str] | None = None) -> dict:
    return {
        "requested_by": OPERATOR_ACTOR,
        "actor_scopes": actor_scopes if actor_scopes is not None else OPERATOR_SCOPES,
        "reason": "Suspicious usage pending design-partner review.",
        "notes": ["Suspended during platform tenant tests."],
    }


def reactivate_payload(*, actor_scopes: list[str] | None = None) -> dict:
    return {
        "requested_by": OPERATOR_ACTOR,
        "actor_scopes": actor_scopes if actor_scopes is not None else OPERATOR_SCOPES,
        "reason": "Review completed.",
    }


def quota_payload(
    *,
    quotas: dict | None = None,
    actor_scopes: list[str] | None = None,
) -> dict:
    return {
        "requested_by": OPERATOR_ACTOR,
        "actor_scopes": actor_scopes if actor_scopes is not None else OPERATOR_SCOPES,
        "quotas": quotas
        if quotas is not None
        else {
            "api_requests_per_window": 50,
            "max_concurrent_sessions": 2,
        },
    }


def vocabulary_payload(
    *,
    vocabulary: dict | None = None,
    actor_scopes: list[str] | None = None,
) -> dict:
    return {
        "requested_by": OPERATOR_ACTOR,
        "actor_scopes": actor_scopes if actor_scopes is not None else OPERATOR_SCOPES,
        "vocabulary": vocabulary
        if vocabulary is not None
        else {
            "site_singular": "Facility",
            "site_plural": "Facilities",
            "workspace_label": "Control room",
            "domain_labels": {
                "supply": "Materials",
                "quality": "Clinical quality",
            },
        },
    }


def audit_events(
    session: Session,
    tenant_id: str,
    event_type: str | None = None,
) -> list[AuditEvent]:
    statement = select(AuditEvent).where(AuditEvent.tenant_id == tenant_id)
    if event_type is not None:
        statement = statement.where(AuditEvent.event_type == event_type)
    return list(session.scalars(statement.order_by(AuditEvent.created_at.asc())))


def session_cookie_for(
    settings: Settings,
    *,
    factory: sessionmaker[Session] | None = None,
    tenant_id: str,
    actor_id: str = "acme-console-user-role",
) -> tuple[str, str]:
    session_id = secrets.token_urlsafe(48)
    cookie_value = sign_cookie(
        {
            "kind": "oidc_session",
            "session_id": session_id,
            "actor_id": actor_id,
            "tenant_id": tenant_id,
            "scopes": ["audit:read"],
            "expires_at": 4102444800,
        },
        settings,
    )
    if factory is not None:
        with session_scope(factory) as session:
            AxisPersistenceRepository(session).create_oidc_browser_session(
                OidcBrowserSessionCreate(
                    session_id_hash=session_id_hash(session_id, settings),
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    scopes=["audit:read"],
                    expires_at=datetime(2100, 1, 1, tzinfo=UTC),
                )
            )
    return session_cookie_name(settings), cookie_value


@pytest.mark.parametrize(
    ("status", "admission_mode", "expected_reason"),
    [
        (None, TENANT_ADMISSION_CLAIMS_ONLY, None),
        (None, TENANT_ADMISSION_REGISTERED_ONLY, "tenant_not_registered"),
        ("active", TENANT_ADMISSION_REGISTERED_ONLY, None),
        ("suspended", TENANT_ADMISSION_REGISTERED_ONLY, "tenant_suspended"),
        (
            "pending_deletion",
            TENANT_ADMISSION_REGISTERED_ONLY,
            "tenant_pending_deletion",
        ),
        (
            "future_lifecycle_state",
            TENANT_ADMISSION_REGISTERED_ONLY,
            "tenant_status_not_active",
        ),
        (
            "ACTIVE",
            TENANT_ADMISSION_REGISTERED_ONLY,
            "tenant_status_not_active",
        ),
    ],
)
def test_tenant_admission_policy_matrix(
    status: str | None,
    admission_mode: str,
    expected_reason: str | None,
) -> None:
    assert tenant_admission_denial_reason(status, admission_mode=admission_mode) == expected_reason


def test_first_tenant_bootstrap_succeeds_once_and_exact_replay_is_idempotent() -> None:
    _client, factory = build_test_client()

    created = bootstrap_tenant(factory)
    replay = bootstrap_tenant(factory)

    assert created.idempotent_replay is False
    assert replay.idempotent_replay is True
    with factory() as session:
        assert len(list(session.scalars(select(Tenant)))) == 1
        assert len(list(session.scalars(select(Actor)))) == 1
        assert (
            len(
                audit_events(
                    session,
                    "tenant_axis_platform_ops",
                    "platform.tenant.provisioned",
                )
            )
            == 1
        )


def test_first_tenant_bootstrap_refuses_replay_of_normal_provisioning() -> None:
    client, factory = build_test_client()
    tenant_id = "tenant_axis_platform_ops"
    payload = provision_payload(
        tenant_id=tenant_id,
        display_name="Axis platform operators",
        idempotency_key="idem_bootstrap_axis_platform_ops_v1",
        bootstrap_admin={
            "actor_id": f"{tenant_id}-bootstrap-admin-role",
            "display_name": "Axis platform operators bootstrap admin",
            "scopes": ["platform:tenant:operator"],
        },
    )
    assert client.post("/platform/tenants", json=payload).status_code == 201

    with pytest.raises(TenantProvisionConflict) as exc_info:
        bootstrap_tenant(factory)

    assert exc_info.value.reason == "tenant_registry_already_initialized"
    with factory() as session:
        assert not audit_events(
            session,
            tenant_id,
            "platform.tenant.first_bootstrap.completed",
        )


@pytest.mark.parametrize(
    ("field", "corrupt_value"),
    [
        ("actor_id", "different-bootstrap-operator"),
        ("authority", "authenticated_api"),
        ("provision_audit_event_id", "00000000-0000-0000-0000-000000000000"),
        ("idempotency_key", "different-bootstrap-key"),
    ],
)
def test_first_tenant_bootstrap_refuses_replay_with_corrupt_authority_evidence(
    field: str,
    corrupt_value: str,
) -> None:
    _client, factory = build_test_client()
    bootstrap_tenant(factory)
    with session_scope(factory) as session:
        event = audit_events(
            session,
            "tenant_axis_platform_ops",
            "platform.tenant.first_bootstrap.completed",
        )[0]
        if field == "actor_id":
            event.actor_id = corrupt_value
        else:
            event.payload = {**event.payload, field: corrupt_value}

    with pytest.raises(TenantProvisionConflict) as exc_info:
        bootstrap_tenant(factory)

    assert exc_info.value.reason == "tenant_registry_already_initialized"


@pytest.mark.parametrize(
    ("tenant_id", "idempotency_key"),
    [
        ("tenant_axis_platform_ops", "idem_bootstrap_axis_platform_ops_v2"),
        ("tenant_second_platform_ops", "idem_bootstrap_second_platform_ops_v1"),
    ],
)
def test_first_tenant_bootstrap_refuses_non_replay_after_registry_initialization(
    tenant_id: str,
    idempotency_key: str,
) -> None:
    _client, factory = build_test_client()
    bootstrap_tenant(factory)

    with pytest.raises(TenantProvisionConflict) as exc_info:
        bootstrap_tenant(
            factory,
            tenant_id=tenant_id,
            display_name="Unexpected bootstrap",
            idempotency_key=idempotency_key,
        )

    assert exc_info.value.reason == "tenant_registry_already_initialized"
    with factory() as session:
        tenants = list(session.scalars(select(Tenant)))
        assert [tenant.id for tenant in tenants] == ["tenant_axis_platform_ops"]


def test_registered_only_bootstrap_admits_operator_then_authenticated_provisioning() -> None:
    operator_tenant_id = "tenant_axis_platform_ops"
    settings = Settings(
        postgres_dsn="sqlite+pysqlite://",
        tenant_admission_mode=TENANT_ADMISSION_REGISTERED_ONLY,
        tenant_state_cache_ttl_seconds=60,
        oidc_auth_required=True,
    )
    client, factory = build_test_client(settings)
    operator_principal = OidcPrincipal(
        actor_id=OPERATOR_ACTOR,
        tenant_id=operator_tenant_id,
        scopes=OPERATOR_SCOPES,
    )
    client.app.state.identity_verifier = StaticIdentityVerifier(operator_principal)
    bearer = {"Authorization": "Bearer valid-token"}

    denied = client.get("/platform/tenants", headers=bearer)

    assert denied.status_code == 403
    assert denied.json()["detail"] == {
        "code": "PERMISSION_DENIED",
        "message": "The tenant for this request is not active.",
        "reason": "tenant_not_registered",
        "tenant_status": "unregistered",
    }
    with factory() as session:
        denial_events = audit_events(
            session,
            operator_tenant_id,
            UNREGISTERED_REQUEST_DENIED_AUDIT_EVENT_TYPE,
        )
        assert len(denial_events) == 1
        assert denial_events[0].payload["path"] == "/platform/tenants"
        assert denial_events[0].payload["tenant_status"] == "unregistered"

    # The one-shot command runs after migrations and before the first operator
    # login. Recreate the process here only to clear the deliberate miss cached
    # by the pre-bootstrap denial above.
    bootstrap_tenant(factory, tenant_id=operator_tenant_id)
    restarted_app = create_app(settings)
    restarted_app.state.session_factory = factory
    restarted_app.state.identity_verifier = StaticIdentityVerifier(operator_principal)
    restarted_client = TestClient(restarted_app)

    registry = restarted_client.get("/platform/tenants", headers=bearer)
    assert registry.status_code == 200
    assert [tenant["tenant_id"] for tenant in registry.json()["tenants"]] == [operator_tenant_id]

    # Prime an unregistered cache entry for the target tenant, then prove that
    # authenticated provisioning invalidates it after persistence succeeds.
    target_principal = OidcPrincipal(
        actor_id="acme-console-user-role",
        tenant_id=TENANT_ID,
        scopes=["platform:policy:read"],
    )
    restarted_app.state.identity_verifier = StaticIdentityVerifier(target_principal)
    target_denied = restarted_client.get(
        "/platform/policies",
        params={"tenant_id": TENANT_ID},
        headers=bearer,
    )
    assert target_denied.status_code == 403
    assert target_denied.json()["detail"]["reason"] == "tenant_not_registered"

    restarted_app.state.identity_verifier = StaticIdentityVerifier(operator_principal)
    provisioned = restarted_client.post(
        "/platform/tenants",
        json=provision_payload(actor_scopes=[]),
        headers=bearer,
    )
    assert provisioned.status_code == 201

    restarted_app.state.identity_verifier = StaticIdentityVerifier(target_principal)
    admitted = restarted_client.get(
        "/platform/policies",
        params={"tenant_id": TENANT_ID},
        headers=bearer,
    )
    assert admitted.status_code == 200


def test_tenant_cache_invalidation_runs_only_after_successful_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory = build_test_client()
    transaction_events: list[str] = []
    cache = client.app.state.tenant_state_cache
    original_invalidate = cache.invalidate

    def observe_commit(_session: Session) -> None:
        transaction_events.append("commit")

    def reject_commit_once(_session: Session) -> None:
        raise RuntimeError("forced commit failure")

    def observe_invalidation(tenant_id: str) -> None:
        transaction_events.append(f"invalidate:{tenant_id}")
        original_invalidate(tenant_id)

    event.listen(factory.class_, "after_commit", observe_commit)
    monkeypatch.setattr(cache, "invalidate", observe_invalidation)
    try:
        event.listen(factory.class_, "before_commit", reject_commit_once)
        try:
            with pytest.raises(RuntimeError, match="forced commit failure"):
                client.post("/platform/tenants", json=provision_payload())
        finally:
            event.remove(factory.class_, "before_commit", reject_commit_once)

        assert transaction_events == []
        with factory() as session:
            assert session.get(Tenant, TENANT_ID) is None

        succeeded = client.post("/platform/tenants", json=provision_payload())
        assert succeeded.status_code == 201
        assert transaction_events == ["commit", f"invalidate:{TENANT_ID}"]
    finally:
        event.remove(factory.class_, "after_commit", observe_commit)


def test_registered_only_cookie_admission_rejects_unregistered_tenant() -> None:
    settings = Settings(
        postgres_dsn="sqlite+pysqlite://",
        tenant_admission_mode=TENANT_ADMISSION_REGISTERED_ONLY,
        oidc_session_cookie_signing_secret="registered-only-cookie-test-secret",
    )
    client, factory = build_test_client(settings)
    cookie_name, cookie_value = session_cookie_for(
        settings,
        factory=factory,
        tenant_id=TENANT_ID,
    )
    client.cookies.set(cookie_name, cookie_value)

    denied = client.get("/identity/session")

    assert denied.status_code == 403
    assert denied.json()["detail"]["reason"] == "tenant_not_registered"
    with factory() as session:
        assert (
            len(
                audit_events(
                    session,
                    TENANT_ID,
                    UNREGISTERED_REQUEST_DENIED_AUDIT_EVENT_TYPE,
                )
            )
            == 1
        )


def test_provision_endpoint_creates_tenant_bootstrap_admin_and_audit() -> None:
    client, factory = build_test_client()

    response = client.post("/platform/tenants", json=provision_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == TENANT_ID
    assert body["status"] == "active"
    assert body["created_by"] == OPERATOR_ACTOR
    assert body["bootstrap_admin_actor_id"] == "acme-platform-admin-role"
    assert body["provision_idempotency_key"] == "idem_provision_acme_v1"
    assert body["audit_event_type"] == "platform.tenant.provisioned"
    assert body["idempotent_replay"] is False
    assert body["permission_decision"]["allowed"] is True

    with factory() as session:
        tenant = session.get(Tenant, TENANT_ID)
        assert tenant is not None
        assert tenant.status == "active"
        actor = session.get(Actor, "acme-platform-admin-role")
        assert actor is not None
        assert actor.tenant_id == TENANT_ID
        events = audit_events(session, TENANT_ID, "platform.tenant.provisioned")
        assert len(events) == 1
        assert events[0].actor_id == OPERATOR_ACTOR
        assert events[0].payload["bootstrap_admin_actor_id"] == "acme-platform-admin-role"
        assert events[0].payload["bootstrap_admin_display_name"] == "Acme platform admin"
        assert events[0].payload["bootstrap_admin_requested_scopes"] == [
            "platform:policy:author",
            "audit:read",
        ]
        assert events[0].payload["permission_decision"]["allowed"] is True


@pytest.mark.parametrize(("actor_length", "expected_status"), [(120, 201), (121, 422)])
def test_provision_endpoint_validates_actor_against_audit_storage_limit(
    actor_length: int,
    expected_status: int,
) -> None:
    client, factory = build_test_client()
    requested_by = "o" * actor_length

    response = client.post(
        "/platform/tenants",
        json=provision_payload(requested_by=requested_by),
    )

    assert response.status_code == expected_status
    with factory() as session:
        events = audit_events(session, TENANT_ID, "platform.tenant.provisioned")
        if expected_status == 201:
            assert events[0].actor_id == requested_by
        else:
            assert session.get(Tenant, TENANT_ID) is None
            assert events == []


@pytest.mark.parametrize(
    ("request_model", "payload"),
    [
        (TenantProvisionRequest, provision_payload()),
        (
            TenantSuspendRequest,
            {
                "actor_scopes": OPERATOR_SCOPES,
                "reason": "Boundary validation.",
            },
        ),
        (TenantReactivateRequest, {"actor_scopes": OPERATOR_SCOPES}),
        (
            TenantQuotaUpdateRequest,
            {"actor_scopes": OPERATOR_SCOPES, "quotas": {}},
        ),
        (
            TenantVocabularyUpdateRequest,
            {"actor_scopes": OPERATOR_SCOPES, "vocabulary": {}},
        ),
    ],
)
def test_platform_tenant_audit_actor_models_share_the_storage_boundary(
    request_model: type[BaseModel],
    payload: dict,
) -> None:
    boundary_actor = "o" * 120

    request = request_model.model_validate({**payload, "requested_by": boundary_actor})
    assert request.requested_by == boundary_actor

    with pytest.raises(ValidationError):
        request_model.model_validate({**payload, "requested_by": "o" * 121})


def test_provision_endpoint_replays_idempotent_request() -> None:
    client, factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    replay = client.post("/platform/tenants", json=provision_payload())

    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    with factory() as session:
        assert len(list(session.scalars(select(Tenant)))) == 1
        assert len(list(session.scalars(select(Actor)))) == 1
        assert len(audit_events(session, TENANT_ID, "platform.tenant.provisioned")) == 1


def test_provision_replay_survives_suspend_and_reactivate_lifecycle_evidence() -> None:
    client, factory = build_test_client()
    payload = provision_payload()
    assert client.post("/platform/tenants", json=payload).status_code == 201

    suspended = client.post(
        f"/platform/tenants/{TENANT_ID}/suspend",
        json=suspend_payload(),
    )
    assert suspended.status_code == 200
    assert suspended.json()["audit_event_type"] == "platform.tenant.suspended"

    suspended_replay = client.post("/platform/tenants", json=payload)
    assert suspended_replay.status_code == 200
    assert suspended_replay.json()["status"] == "suspended"
    assert suspended_replay.json()["idempotent_replay"] is True

    reactivated = client.post(
        f"/platform/tenants/{TENANT_ID}/reactivate",
        json=reactivate_payload(),
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["audit_event_type"] == "platform.tenant.reactivated"

    active_replay = client.post("/platform/tenants", json=payload)
    assert active_replay.status_code == 200
    assert active_replay.json()["status"] == "active"
    assert active_replay.json()["idempotent_replay"] is True

    with factory() as session:
        tenant = session.get(Tenant, TENANT_ID)
        assert tenant is not None
        assert tenant.notes != payload["notes"]
        assert tenant.audit_event_type == "platform.tenant.reactivated"
        assert len(audit_events(session, TENANT_ID, "platform.tenant.provisioned")) == 1


def test_legacy_provision_replay_rejects_changed_notes_before_lifecycle() -> None:
    client, factory = build_test_client()
    payload = provision_payload()
    assert client.post("/platform/tenants", json=payload).status_code == 201
    with session_scope(factory) as session:
        event = audit_events(session, TENANT_ID, "platform.tenant.provisioned")[0]
        event.payload = {
            key: value
            for key, value in event.payload.items()
            if key not in {"description", "provision_notes"}
        }

    assert client.post("/platform/tenants", json=payload).status_code == 200

    changed = client.post(
        "/platform/tenants",
        json={**payload, "notes": ["Changed legacy provisioning note."]},
    )

    assert changed.status_code == 409
    assert changed.json()["detail"]["reason"] == "provision_idempotency_conflict"


def test_legacy_provision_replay_fails_closed_after_lifecycle_note_ambiguity() -> None:
    client, factory = build_test_client()
    payload = provision_payload()
    assert client.post("/platform/tenants", json=payload).status_code == 201
    with session_scope(factory) as session:
        event = audit_events(session, TENANT_ID, "platform.tenant.provisioned")[0]
        event.payload = {
            key: value
            for key, value in event.payload.items()
            if key not in {"description", "provision_notes"}
        }

    assert (
        client.post(
            f"/platform/tenants/{TENANT_ID}/suspend",
            json=suspend_payload(),
        ).status_code
        == 200
    )

    replay = client.post("/platform/tenants", json=payload)

    assert replay.status_code == 409
    assert replay.json()["detail"]["reason"] == "provision_idempotency_conflict"


def test_provision_replay_rejects_ambiguous_provision_evidence() -> None:
    client, factory = build_test_client()
    payload = provision_payload()
    assert client.post("/platform/tenants", json=payload).status_code == 201
    with session_scope(factory) as session:
        original = audit_events(session, TENANT_ID, "platform.tenant.provisioned")[0]
        session.add(
            AuditEvent(
                tenant_id=original.tenant_id,
                actor_id=original.actor_id,
                event_type=original.event_type,
                payload=dict(original.payload),
            )
        )

    replay = client.post("/platform/tenants", json=payload)

    assert replay.status_code == 409
    assert replay.json()["detail"]["reason"] == "provision_idempotency_conflict"


def test_provision_replay_rejects_corrupt_immutable_provision_evidence() -> None:
    client, factory = build_test_client()
    payload = provision_payload()
    assert client.post("/platform/tenants", json=payload).status_code == 201
    with session_scope(factory) as session:
        event = audit_events(session, TENANT_ID, "platform.tenant.provisioned")[0]
        event.payload = {**event.payload, "description": "Corrupt description"}

    replay = client.post("/platform/tenants", json=payload)

    assert replay.status_code == 409
    assert replay.json()["detail"]["reason"] == "provision_idempotency_conflict"


def test_provision_endpoint_rejects_idempotency_conflict() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    conflict = client.post(
        "/platform/tenants",
        json=provision_payload(display_name="Acme Manufacturing Renamed"),
    )

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason"] == "provision_idempotency_conflict"


def test_provision_endpoint_rejects_duplicate_tenant() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    duplicate = client.post(
        "/platform/tenants",
        json=provision_payload(idempotency_key="idem_provision_acme_v2"),
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["reason"] == "tenant_already_exists"


def test_provision_endpoint_rejects_existing_bootstrap_admin_actor() -> None:
    client, factory = build_test_client()
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).create_tenant(
            TenantCreate(
                tenant_id="tenant_other",
                display_name="Other tenant",
                created_by=OPERATOR_ACTOR,
            )
        )
        session.add(
            Actor(
                id="acme-platform-admin-role",
                tenant_id="tenant_other",
                display_name="Existing actor",
                actor_type="human",
            )
        )

    response = client.post("/platform/tenants", json=provision_payload())

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "bootstrap_admin_actor_exists"


def test_provision_endpoint_rejects_missing_operator_scope() -> None:
    client, factory = build_test_client()

    response = client.post(
        "/platform/tenants",
        json=provision_payload(actor_scopes=["platform:tenant:provision"]),
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["required_permission"] == "platform:tenant:operator"
    assert detail["reason"] == "missing_required_scope"
    with factory() as session:
        assert session.get(Tenant, TENANT_ID) is None


def test_provision_endpoint_rejects_missing_provision_scope() -> None:
    client, _factory = build_test_client()

    response = client.post(
        "/platform/tenants",
        json=provision_payload(actor_scopes=["platform:tenant:operator"]),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["required_permission"] == "platform:tenant:provision"


def test_provision_endpoint_rejects_invalid_tenant_id() -> None:
    client, _factory = build_test_client()

    response = client.post(
        "/platform/tenants",
        json=provision_payload(tenant_id="Tenant Invalid Id"),
    )

    assert response.status_code == 422


def test_registry_endpoint_lists_tenants_with_status_filter() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201
    assert (
        client.post(
            "/platform/tenants",
            json=provision_payload(
                tenant_id="tenant_beta_manufacturing",
                display_name="Beta Manufacturing",
                idempotency_key="idem_provision_beta_v1",
                bootstrap_admin={
                    "actor_id": "beta-platform-admin-role",
                    "display_name": "Beta platform admin",
                    "scopes": [],
                },
            ),
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/platform/tenants/{TENANT_ID}/suspend",
            json=suspend_payload(),
        ).status_code
        == 200
    )

    registry = client.get("/platform/tenants").json()
    assert registry["tenant_count"] == 2
    assert registry["active_tenant_count"] == 1

    suspended = client.get("/platform/tenants", params={"status": "suspended"}).json()
    assert suspended["tenant_count"] == 1
    assert suspended["tenants"][0]["tenant_id"] == TENANT_ID
    assert suspended["tenants"][0]["suspension_reason"] == (
        "Suspicious usage pending design-partner review."
    )


def test_registry_endpoint_requires_operator_read_scopes_when_authenticated() -> None:
    client, _factory = build_test_client()
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id=OPERATOR_ACTOR,
            tenant_id="tenant_axis_platform_ops",
            scopes=["platform:tenant:read"],
        )
    )

    denied = client.get(
        "/platform/tenants",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["required_permission"] == "platform:tenant:operator"

    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id=OPERATOR_ACTOR,
            tenant_id="tenant_axis_platform_ops",
            scopes=["platform:tenant:operator", "platform:tenant:read"],
        )
    )
    allowed = client.get(
        "/platform/tenants",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert allowed.status_code == 200


def test_suspended_tenant_requests_are_rejected_fail_closed_and_reactivate_restores() -> None:
    client, factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="acme-console-user-role",
            tenant_id=TENANT_ID,
            scopes=["platform:policy:read"],
        )
    )
    bearer = {"Authorization": "Bearer valid-token"}

    before = client.get(
        "/platform/policies",
        params={"tenant_id": TENANT_ID},
        headers=bearer,
    )
    assert before.status_code == 200

    suspended = client.post(
        f"/platform/tenants/{TENANT_ID}/suspend",
        json=suspend_payload(),
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"
    assert suspended.json()["suspended_by"] == OPERATOR_ACTOR

    denied = client.get(
        "/platform/policies",
        params={"tenant_id": TENANT_ID},
        headers=bearer,
    )
    assert denied.status_code == 403
    detail = denied.json()["detail"]
    assert detail["reason"] == "tenant_suspended"
    assert detail["tenant_status"] == "suspended"

    with factory() as session:
        suspend_events = audit_events(session, TENANT_ID, "platform.tenant.suspended")
        assert len(suspend_events) == 1
        assert suspend_events[0].payload["reason"] == (
            "Suspicious usage pending design-partner review."
        )
        denial_events = audit_events(
            session,
            TENANT_ID,
            "platform.tenant.suspended_request.denied",
        )
        assert len(denial_events) == 1
        assert denial_events[0].actor_id == "acme-console-user-role"
        assert denial_events[0].payload["path"] == "/platform/policies"
        assert denial_events[0].payload["reason"] == "tenant_suspended"

    reactivated = client.post(
        f"/platform/tenants/{TENANT_ID}/reactivate",
        json=reactivate_payload(),
    )
    assert reactivated.status_code == 200
    body = reactivated.json()
    assert body["status"] == "active"
    assert body["reactivated_by"] == OPERATOR_ACTOR
    assert body["suspended_at"] is None
    assert body["suspension_reason"] is None

    restored = client.get(
        "/platform/policies",
        params={"tenant_id": TENANT_ID},
        headers=bearer,
    )
    assert restored.status_code == 200
    with factory() as session:
        assert len(audit_events(session, TENANT_ID, "platform.tenant.reactivated")) == 1


def test_suspend_endpoint_rejects_unknown_tenant_and_lifecycle_conflicts() -> None:
    client, _factory = build_test_client()

    missing = client.post(
        "/platform/tenants/tenant_missing/suspend",
        json=suspend_payload(),
    )
    assert missing.status_code == 404

    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201
    already_active = client.post(
        f"/platform/tenants/{TENANT_ID}/reactivate",
        json=reactivate_payload(),
    )
    assert already_active.status_code == 409
    assert already_active.json()["detail"]["reason"] == "tenant_already_active"

    assert (
        client.post(
            f"/platform/tenants/{TENANT_ID}/suspend",
            json=suspend_payload(),
        ).status_code
        == 200
    )
    second_suspend = client.post(
        f"/platform/tenants/{TENANT_ID}/suspend",
        json=suspend_payload(),
    )
    assert second_suspend.status_code == 409
    assert second_suspend.json()["detail"]["reason"] == "tenant_not_active"


def test_suspend_endpoint_rejects_missing_scopes_and_actor_impersonation() -> None:
    client, factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    unscoped = client.post(
        f"/platform/tenants/{TENANT_ID}/suspend",
        json=suspend_payload(actor_scopes=["platform:tenant:suspend"]),
    )
    assert unscoped.status_code == 403
    assert unscoped.json()["detail"]["required_permission"] == "platform:tenant:operator"

    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="another-operator-role",
            tenant_id="tenant_axis_platform_ops",
            scopes=OPERATOR_SCOPES,
        )
    )
    impersonation = client.post(
        f"/platform/tenants/{TENANT_ID}/suspend",
        json=suspend_payload(),
        headers={"Authorization": "Bearer valid-token"},
    )
    assert impersonation.status_code == 403
    assert impersonation.json()["detail"]["reason"] == "actor_mismatch"

    with factory() as session:
        tenant = session.get(Tenant, TENANT_ID)
        assert tenant is not None
        assert tenant.status == "active"


def test_authenticated_operator_manages_other_tenant_with_operator_scopes() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id=OPERATOR_ACTOR,
            tenant_id="tenant_axis_platform_ops",
            scopes=OPERATOR_SCOPES,
        )
    )

    suspended = client.post(
        f"/platform/tenants/{TENANT_ID}/suspend",
        json=suspend_payload(actor_scopes=[]),
        headers={"Authorization": "Bearer valid-token"},
    )

    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"
    assert suspended.json()["suspended_by"] == OPERATOR_ACTOR


def test_quota_endpoint_updates_clears_and_audits_changes() -> None:
    client, factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    updated = client.put(
        f"/platform/tenants/{TENANT_ID}/quotas",
        json=quota_payload(),
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["quotas"] == {
        "api_requests_per_window": 50,
        "max_concurrent_sessions": 2,
    }
    assert {change["quota_key"]: change["new_value"] for change in body["changes"]} == {
        "api_requests_per_window": 50,
        "max_concurrent_sessions": 2,
    }
    assert all(
        change["audit_event_type"] == "platform.tenant.quota.updated" for change in body["changes"]
    )

    fetched = client.get(f"/platform/tenants/{TENANT_ID}/quotas")
    assert fetched.status_code == 200
    assert fetched.json()["quotas"] == body["quotas"]

    revised = client.put(
        f"/platform/tenants/{TENANT_ID}/quotas",
        json=quota_payload(
            quotas={
                "api_requests_per_window": 75,
                "max_connector_sync_rows_per_run": 3,
            }
        ),
    )
    assert revised.status_code == 200
    revised_body = revised.json()
    assert revised_body["quotas"] == {
        "api_requests_per_window": 75,
        "max_connector_sync_rows_per_run": 3,
    }
    changes = {change["quota_key"]: change for change in revised_body["changes"]}
    assert changes["api_requests_per_window"]["previous_value"] == 50
    assert changes["api_requests_per_window"]["new_value"] == 75
    assert changes["max_concurrent_sessions"]["previous_value"] == 2
    assert changes["max_concurrent_sessions"]["new_value"] is None
    assert changes["max_connector_sync_rows_per_run"]["previous_value"] is None
    assert changes["max_connector_sync_rows_per_run"]["new_value"] == 3

    with factory() as session:
        events = audit_events(session, TENANT_ID, "platform.tenant.quota.updated")
        assert len(events) == 5
        stored = {
            quota.quota_key: quota.quota_value for quota in session.scalars(select(TenantQuota))
        }
        assert stored == {
            "api_requests_per_window": 75,
            "max_connector_sync_rows_per_run": 3,
        }


def test_quota_endpoint_rejects_missing_scope_unknown_tenant_and_bad_values() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    unscoped = client.put(
        f"/platform/tenants/{TENANT_ID}/quotas",
        json=quota_payload(actor_scopes=["platform:tenant:operator"]),
    )
    assert unscoped.status_code == 403
    assert unscoped.json()["detail"]["required_permission"] == "platform:tenant:quota"

    missing = client.put(
        "/platform/tenants/tenant_missing/quotas",
        json=quota_payload(),
    )
    assert missing.status_code == 404
    assert client.get("/platform/tenants/tenant_missing/quotas").status_code == 404

    invalid = client.put(
        f"/platform/tenants/{TENANT_ID}/quotas",
        json=quota_payload(quotas={"api_requests_per_window": 0}),
    )
    assert invalid.status_code == 422


def test_quota_read_requires_operator_read_scopes_when_authenticated() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id=OPERATOR_ACTOR,
            tenant_id="tenant_axis_platform_ops",
            scopes=["platform:tenant:operator"],
        )
    )

    denied = client.get(
        f"/platform/tenants/{TENANT_ID}/quotas",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert denied.status_code == 403
    assert denied.json()["detail"]["required_permission"] == "platform:tenant:read"


def test_vocabulary_defaults_are_returned_as_unconfigured() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    response = client.get(f"/platform/tenants/{TENANT_ID}/vocabulary")

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": TENANT_ID,
        "vocabulary": {
            "site_singular": "Site",
            "site_plural": "Sites",
            "workspace_label": "Operations",
            "domain_labels": {},
        },
        "configured": False,
        "changes": [],
        "vocabulary_notes": [
            "Industry-neutral defaults are returned until this tenant configures vocabulary.",
            "Every vocabulary change appends platform.tenant.vocabulary.updated audit evidence.",
        ],
    }


def test_vocabulary_put_then_get_returns_stored_document() -> None:
    client, factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201
    expected = vocabulary_payload()["vocabulary"]

    updated = client.put(
        f"/platform/tenants/{TENANT_ID}/vocabulary",
        json=vocabulary_payload(),
    )
    fetched = client.get(f"/platform/tenants/{TENANT_ID}/vocabulary")

    assert updated.status_code == 200
    assert updated.json()["configured"] is True
    assert updated.json()["vocabulary"] == expected
    assert fetched.status_code == 200
    assert fetched.json()["configured"] is True
    assert fetched.json()["vocabulary"] == expected
    with factory() as session:
        assert session.get(Tenant, TENANT_ID).vocabulary == expected


def test_vocabulary_rejects_blank_labels_and_domain_keys() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    blank_label = client.put(
        f"/platform/tenants/{TENANT_ID}/vocabulary",
        json=vocabulary_payload(
            vocabulary={
                "site_singular": " \t",
                "site_plural": "Sites",
                "workspace_label": "Operations",
                "domain_labels": {},
            }
        ),
    )
    blank_domain_key = client.put(
        f"/platform/tenants/{TENANT_ID}/vocabulary",
        json=vocabulary_payload(
            vocabulary={
                "site_singular": "Site",
                "site_plural": "Sites",
                "workspace_label": "Operations",
                "domain_labels": {"  ": "Supply"},
            }
        ),
    )

    assert blank_label.status_code == 422
    assert blank_domain_key.status_code == 422


def test_vocabulary_rejects_overlong_labels() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    response = client.put(
        f"/platform/tenants/{TENANT_ID}/vocabulary",
        json=vocabulary_payload(
            vocabulary={
                "site_singular": "S" * (TENANT_VOCABULARY_LABEL_MAX_LENGTH + 1),
                "site_plural": "Sites",
                "workspace_label": "Operations",
                "domain_labels": {},
            }
        ),
    )

    assert response.status_code == 422


def test_vocabulary_rejects_too_many_domain_entries() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    response = client.put(
        f"/platform/tenants/{TENANT_ID}/vocabulary",
        json=vocabulary_payload(
            vocabulary={
                "site_singular": "Site",
                "site_plural": "Sites",
                "workspace_label": "Operations",
                "domain_labels": {
                    f"domain_{index}": f"Domain {index}"
                    for index in range(TENANT_VOCABULARY_MAX_DOMAIN_LABELS + 1)
                },
            }
        ),
    )

    assert response.status_code == 422


def test_vocabulary_rejects_unknown_fields() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201
    vocabulary = vocabulary_payload()["vocabulary"]
    vocabulary["industry"] = "Manufacturing"

    response = client.put(
        f"/platform/tenants/{TENANT_ID}/vocabulary",
        json=vocabulary_payload(vocabulary=vocabulary),
    )

    assert response.status_code == 422


def test_vocabulary_update_requires_its_own_configure_scope() -> None:
    """Renaming labels must not require — or grant — quota authority.

    Quotas are commercial limits; vocabulary is display configuration. Sharing
    one scope would mean anyone allowed to relabel a domain could also raise a
    tenant's quota.
    """
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    response = client.put(
        f"/platform/tenants/{TENANT_ID}/vocabulary",
        json=vocabulary_payload(actor_scopes=["platform:tenant:operator"]),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["required_permission"] == "platform:tenant:configure"
    assert response.json()["detail"]["reason"] == "missing_required_scope"


def test_quota_scope_alone_cannot_change_vocabulary() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    response = client.put(
        f"/platform/tenants/{TENANT_ID}/vocabulary",
        json=vocabulary_payload(
            actor_scopes=["platform:tenant:operator", "platform:tenant:quota"],
        ),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["required_permission"] == "platform:tenant:configure"


def test_vocabulary_update_records_audit_evidence() -> None:
    client, factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201
    expected = vocabulary_payload()["vocabulary"]

    response = client.put(
        f"/platform/tenants/{TENANT_ID}/vocabulary",
        json=vocabulary_payload(),
    )

    assert response.status_code == 200
    change = response.json()["changes"]
    assert len(change) == 1
    assert change[0]["previous_value"] is None
    assert change[0]["new_value"] == expected
    assert change[0]["audit_event_type"] == "platform.tenant.vocabulary.updated"
    with factory() as session:
        events = audit_events(
            session,
            TENANT_ID,
            "platform.tenant.vocabulary.updated",
        )
        assert len(events) == 1
        assert events[0].payload["previous_value"] is None
        assert events[0].payload["new_value"] == expected
        assert events[0].payload["required_configure_scope"] == "platform:tenant:configure"
        assert events[0].payload["permission_decision"]["allowed"] is True


def test_vocabulary_unknown_tenant_matches_platform_404() -> None:
    client, _factory = build_test_client()

    fetched = client.get("/platform/tenants/tenant_missing/vocabulary")
    updated = client.put(
        "/platform/tenants/tenant_missing/vocabulary",
        json=vocabulary_payload(),
    )

    assert fetched.status_code == 404
    assert updated.status_code == 404
    assert (
        fetched.json()["detail"]
        == updated.json()["detail"]
        == {
            "code": "NOT_FOUND",
            "message": "The tenant was not found.",
            "tenant_id": "tenant_missing",
        }
    )


def test_tenant_detail_endpoint_returns_record() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    response = client.get(f"/platform/tenants/{TENANT_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == TENANT_ID
    assert body["display_name"] == "Acme Manufacturing"
    assert body["status"] == "active"
    assert body["bootstrap_admin_actor_id"] == "acme-platform-admin-role"
    assert body["audit_event_type"] == "platform.tenant.provisioned"


def test_tenant_detail_endpoint_returns_404_for_unknown_tenant() -> None:
    client, _factory = build_test_client()

    response = client.get("/platform/tenants/tenant_missing")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "NOT_FOUND"
    assert detail["tenant_id"] == "tenant_missing"


def test_tenant_detail_requires_operator_read_scopes_when_authenticated() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201

    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id=OPERATOR_ACTOR,
            tenant_id="tenant_axis_platform_ops",
            scopes=["platform:tenant:read"],
        )
    )
    missing_operator = client.get(
        f"/platform/tenants/{TENANT_ID}",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert missing_operator.status_code == 403
    assert missing_operator.json()["detail"]["required_permission"] == "platform:tenant:operator"

    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id=OPERATOR_ACTOR,
            tenant_id="tenant_axis_platform_ops",
            scopes=["platform:tenant:operator"],
        )
    )
    missing_read = client.get(
        f"/platform/tenants/{TENANT_ID}",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert missing_read.status_code == 403
    assert missing_read.json()["detail"]["required_permission"] == "platform:tenant:read"

    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id=OPERATOR_ACTOR,
            tenant_id="tenant_axis_platform_ops",
            scopes=["platform:tenant:operator", "platform:tenant:read"],
        )
    )
    allowed = client.get(
        f"/platform/tenants/{TENANT_ID}",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["tenant_id"] == TENANT_ID


def test_tenant_detail_is_isolated_per_tenant_for_cross_tenant_operator() -> None:
    client, _factory = build_test_client()
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201
    assert (
        client.post(
            "/platform/tenants",
            json=provision_payload(
                tenant_id="tenant_beta_manufacturing",
                display_name="Beta Manufacturing",
                idempotency_key="idem_provision_beta_v1",
                bootstrap_admin={
                    "actor_id": "beta-platform-admin-role",
                    "display_name": "Beta platform admin",
                    "scopes": [],
                },
            ),
        ).status_code
        == 201
    )

    # A platform operator authenticated under a third ops tenant reads each
    # tenant across the tenant boundary and gets exactly the requested record,
    # never another tenant's data.
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id=OPERATOR_ACTOR,
            tenant_id="tenant_axis_platform_ops",
            scopes=["platform:tenant:operator", "platform:tenant:read"],
        )
    )
    headers = {"Authorization": "Bearer valid-token"}

    acme = client.get(f"/platform/tenants/{TENANT_ID}", headers=headers)
    assert acme.status_code == 200
    assert acme.json()["tenant_id"] == TENANT_ID
    assert acme.json()["display_name"] == "Acme Manufacturing"

    beta = client.get("/platform/tenants/tenant_beta_manufacturing", headers=headers)
    assert beta.status_code == 200
    assert beta.json()["tenant_id"] == "tenant_beta_manufacturing"
    assert beta.json()["display_name"] == "Beta Manufacturing"


def test_registry_endpoint_paginates_with_cursor() -> None:
    client, _factory = build_test_client()
    tenant_ids = [f"tenant_pager_{index:03d}" for index in range(5)]
    for index, tenant_id in enumerate(tenant_ids):
        assert (
            client.post(
                "/platform/tenants",
                json=provision_payload(
                    tenant_id=tenant_id,
                    display_name=f"Pager {index}",
                    idempotency_key=f"idem_pager_{index}",
                    bootstrap_admin={
                        "actor_id": f"pager-admin-{index}",
                        "display_name": f"Pager admin {index}",
                        "scopes": [],
                    },
                ),
            ).status_code
            == 201
        )

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        page = client.get("/platform/tenants", params=params).json()
        pages += 1
        page_ids = [tenant["tenant_id"] for tenant in page["tenants"]]
        seen.extend(page_ids)
        assert len(page_ids) <= 2
        if page["has_more"]:
            assert page["next_cursor"] is not None
            assert len(page_ids) == 2
            cursor = page["next_cursor"]
        else:
            assert page["next_cursor"] is None
            break

    # Keyset walk visited every tenant exactly once, in ascending id order.
    assert seen == sorted(tenant_ids)
    assert len(seen) == len(set(seen))
    assert pages == 3  # 2 + 2 + 1


def test_registry_endpoint_rejects_invalid_cursor() -> None:
    client, _factory = build_test_client()

    response = client.get("/platform/tenants", params={"cursor": "!!!not-base64!!!"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "VALIDATION_FAILED"
    assert detail["reason"] == "invalid_tenant_cursor"


def rate_limited_settings() -> Settings:
    return Settings(
        postgres_dsn="sqlite+pysqlite://",
        api_rate_limit_enabled=True,
        api_rate_limit_requests=5,
        api_rate_limit_window_seconds=60,
        api_rate_limit_paths=[RATE_LIMIT_TEST_PATH],
        oidc_session_cookie_signing_secret="a-secure-cookie-signing-secret",
        tenant_state_cache_ttl_seconds=0,
    )


def seed_tenant_with_request_quota(
    factory: sessionmaker[Session],
    *,
    quota_value: int | None,
    tenant_id: str = TENANT_ID,
    display_name: str = "Acme Manufacturing",
) -> None:
    with session_scope(factory) as session:
        repository = AxisPersistenceRepository(session)
        repository.create_tenant(
            TenantCreate(
                tenant_id=tenant_id,
                display_name=display_name,
                created_by=OPERATOR_ACTOR,
            )
        )
        if quota_value is not None:
            repository.upsert_tenant_quota(
                TenantQuotaUpsert(
                    tenant_id=tenant_id,
                    quota_key=TenantQuotaKey.API_REQUESTS_PER_WINDOW.value,
                    quota_value=quota_value,
                    updated_by=OPERATOR_ACTOR,
                )
            )


def test_rate_limit_enforces_tenant_quota_before_global_limit() -> None:
    settings = rate_limited_settings()
    client, factory = build_test_client(settings)
    seed_tenant_with_request_quota(factory, quota_value=2)
    cookie_name, cookie_value = session_cookie_for(
        settings,
        factory=factory,
        tenant_id=TENANT_ID,
    )
    client.cookies.set(cookie_name, cookie_value)

    assert client.get(RATE_LIMIT_TEST_PATH).status_code == 200
    assert client.get(RATE_LIMIT_TEST_PATH).status_code == 200
    limited = client.get(RATE_LIMIT_TEST_PATH)

    assert limited.status_code == 429
    detail = limited.json()["detail"]
    assert detail["scope"] == "tenant_quota"
    assert detail["limit"] == 2
    assert limited.headers["Retry-After"]


def test_rate_limit_falls_back_to_global_limit_without_tenant_quota() -> None:
    settings = rate_limited_settings()
    client, factory = build_test_client(settings)
    seed_tenant_with_request_quota(factory, quota_value=None)
    cookie_name, cookie_value = session_cookie_for(
        settings,
        factory=factory,
        tenant_id=TENANT_ID,
    )
    client.cookies.set(cookie_name, cookie_value)

    for _ in range(5):
        assert client.get(RATE_LIMIT_TEST_PATH).status_code == 200
    limited = client.get(RATE_LIMIT_TEST_PATH)

    assert limited.status_code == 429
    assert limited.json()["detail"]["scope"] == "client_endpoint"
    assert limited.json()["detail"]["limit"] == 5


def test_rate_limit_verified_bearer_token_selects_tenant_quota() -> None:
    settings = rate_limited_settings()
    client, factory = build_test_client(settings)
    seed_tenant_with_request_quota(factory, quota_value=1)
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="acme-console-user-role",
            tenant_id=TENANT_ID,
            scopes=[],
        )
    )
    bearer = {"Authorization": "Bearer valid-token"}

    assert client.get(RATE_LIMIT_TEST_PATH, headers=bearer).status_code == 200
    limited = client.get(RATE_LIMIT_TEST_PATH, headers=bearer)

    assert limited.status_code == 429
    assert limited.json()["detail"]["scope"] == "tenant_quota"
    assert limited.json()["detail"]["limit"] == 1


def test_tenant_request_quota_is_shared_across_endpoints() -> None:
    settings = rate_limited_settings().model_copy(
        update={
            "api_rate_limit_paths": [
                RATE_LIMIT_TEST_PATH,
                SECOND_RATE_LIMIT_TEST_PATH,
            ]
        }
    )
    client, factory = build_test_client(settings)
    seed_tenant_with_request_quota(factory, quota_value=1)
    seed_tenant_with_request_quota(
        factory,
        quota_value=1,
        tenant_id=SECOND_TENANT_ID,
        display_name="Beta Manufacturing",
    )
    bearer = {"Authorization": "Bearer valid-token"}
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="acme-console-user-role",
            tenant_id=TENANT_ID,
            scopes=[],
        )
    )

    assert client.get(RATE_LIMIT_TEST_PATH, headers=bearer).status_code == 200
    limited = client.get(SECOND_RATE_LIMIT_TEST_PATH, headers=bearer)

    assert limited.status_code == 429
    assert limited.json()["detail"]["scope"] == "tenant_quota"
    assert limited.json()["detail"]["message"] == "Tenant request quota exceeded."

    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="beta-console-user-role",
            tenant_id=SECOND_TENANT_ID,
            scopes=[],
        )
    )
    assert client.get(SECOND_RATE_LIMIT_TEST_PATH, headers=bearer).status_code == 200


def test_revoked_session_cookie_cannot_consume_tenant_quota() -> None:
    settings = rate_limited_settings()
    client, factory = build_test_client(settings)
    seed_tenant_with_request_quota(factory, quota_value=1)
    cookie_name, cookie_value = session_cookie_for(
        settings,
        factory=factory,
        tenant_id=TENANT_ID,
    )
    client.cookies.set(cookie_name, cookie_value)
    session_id = read_session_cookie(cookie_value, settings).session_id
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).revoke_oidc_browser_session(
            OidcBrowserSessionRevocation(
                session_id_hash=session_id_hash(session_id, settings),
                revoked_by="security-operator",
                revocation_reason="test_revocation",
            )
        )

    # Revoked credentials may hit the client bucket, but never the shared
    # tenant quota. A fresh verified bearer still receives the tenant's one slot.
    assert client.get(RATE_LIMIT_TEST_PATH).status_code == 200
    client.cookies.clear()
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="acme-console-user-role",
            tenant_id=TENANT_ID,
            scopes=[],
        )
    )
    bearer = {"Authorization": "Bearer valid-token"}
    assert client.get(RATE_LIMIT_TEST_PATH, headers=bearer).status_code == 200
    assert client.get(RATE_LIMIT_TEST_PATH, headers=bearer).status_code == 429


def test_rate_limit_ignores_unverifiable_session_cookies() -> None:
    settings = rate_limited_settings()
    client, factory = build_test_client(settings)
    seed_tenant_with_request_quota(factory, quota_value=1)
    cookie_name, _cookie_value = session_cookie_for(
        settings,
        factory=factory,
        tenant_id=TENANT_ID,
    )
    client.cookies.set(cookie_name, "tampered-cookie-value")

    # A cookie that fails HMAC verification must never select a tenant limit.
    assert client.get(RATE_LIMIT_TEST_PATH).status_code == 200
    assert client.get(RATE_LIMIT_TEST_PATH).status_code == 200


def test_tenant_state_cache_serves_stale_status_within_ttl() -> None:
    settings = Settings(
        postgres_dsn="sqlite+pysqlite://",
        tenant_state_cache_ttl_seconds=60,
    )
    client, factory = build_test_client(settings)
    assert client.post("/platform/tenants", json=provision_payload()).status_code == 201
    client.app.state.identity_verifier = StaticIdentityVerifier(
        OidcPrincipal(
            actor_id="acme-console-user-role",
            tenant_id=TENANT_ID,
            scopes=["platform:policy:read"],
        )
    )
    bearer = {"Authorization": "Bearer valid-token"}
    assert (
        client.get(
            "/platform/policies",
            params={"tenant_id": TENANT_ID},
            headers=bearer,
        ).status_code
        == 200
    )

    # Suspend behind the API's back: the cached active status keeps serving
    # until the TTL elapses or the entry is invalidated by a lifecycle route.
    with session_scope(factory) as session:
        tenant = session.get(Tenant, TENANT_ID)
        assert tenant is not None
        tenant.status = "suspended"
    stale = client.get(
        "/platform/policies",
        params={"tenant_id": TENANT_ID},
        headers=bearer,
    )
    assert stale.status_code == 200

    client.app.state.tenant_state_cache.invalidate(TENANT_ID)
    fresh = client.get(
        "/platform/policies",
        params={"tenant_id": TENANT_ID},
        headers=bearer,
    )
    assert fresh.status_code == 403
    assert fresh.json()["detail"]["reason"] == "tenant_suspended"
