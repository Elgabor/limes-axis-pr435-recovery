from __future__ import annotations

import base64
import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from runpy import run_path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient
from jose import jwt
from jose.utils import base64url_encode
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.db import session_scope
from axis_api.identity import StaticJwksOidcVerifier
from axis_api.main import create_app
from axis_api.models import AuditEvent, Base, OidcBrowserSession, Tenant
from axis_api.oidc_code_flow import (
    OidcCodeFlowConfigurationError,
    OidcTokenExchangeError,
    decrypt_refresh_token,
    encrypt_refresh_token,
    read_session_cookie,
    refresh_token_encryption_key_is_strong,
    validate_refresh_token_encryption_key,
)
from axis_api.persistence import (
    AxisPersistenceRepository,
    DemoReferenceRecordCreate,
    OidcBrowserSessionRevocation,
    TenantCreate,
    TenantQuotaUpsert,
)
from axis_api.platform_tenants import TenantQuotaKey
from axis_api.tenant_admission import (
    TENANT_ADMISSION_REGISTERED_ONLY,
    UNREGISTERED_REQUEST_DENIED_AUDIT_EVENT_TYPE,
)
from axis_api.workflow_runtime import WorkflowSignalResult

TOKEN_SECRET = "axis-test-secret"
DEFAULT_ACTOR = "plant-operations-owner-role"
DEFAULT_TENANT = "tenant_demo_manufacturing"
STRONG_REFRESH_KEY = "axis-refresh-credential-encryption-key-01"


def _oct_jwks(secret: str) -> dict:
    return {
        "keys": [
            {
                "kty": "oct",
                "kid": "axis-test",
                "k": base64url_encode(secret.encode()).decode(),
            }
        ]
    }


def _access_token(
    settings: Settings,
    *,
    actor_id: str = DEFAULT_ACTOR,
    scope: str = "audit:read approvals:supply:decide",
) -> str:
    payload = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "sub": actor_id,
        "axis_tenant": DEFAULT_TENANT,
        "scope": scope,
        "exp": 4102444800,
    }
    return jwt.encode(payload, TOKEN_SECRET, algorithm="HS256", headers={"kid": "axis-test"})


def _id_token(settings: Settings, *, nonce: str, actor_id: str = DEFAULT_ACTOR) -> str:
    payload = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_client_id,
        "azp": settings.oidc_client_id,
        "sub": actor_id,
        "nonce": nonce,
        "exp": 4102444800,
        "iat": 1893456000,
    }
    return jwt.encode(payload, TOKEN_SECRET, algorithm="HS256", headers={"kid": "axis-test"})


def _settings(**overrides: object) -> Settings:
    values = {
        "postgres_dsn": "sqlite+pysqlite://",
        "api_base_url": "https://api.axis.example",
        "public_base_url": "https://console.axis.example",
        "oidc_auth_required": True,
        "oidc_issuer": "https://idp.example/realms/axis",
        "oidc_audience": "limes-axis-api",
        "oidc_jwks_url": "https://idp.example/realms/axis/protocol/openid-connect/certs",
        "oidc_algorithms": ["HS256"],
        "oidc_client_id": "axis-console",
        "oidc_client_secret": "axis-client-secret",
        "oidc_authorization_url": (
            "https://idp.example/realms/axis/protocol/openid-connect/auth"
        ),
        "oidc_token_url": "https://idp.example/realms/axis/protocol/openid-connect/token",
        "oidc_session_cookie_signing_secret": "a-secure-cookie-signing-secret",
        "oidc_session_cookie_secure": False,
        "oidc_refresh_token_encryption_key": STRONG_REFRESH_KEY,
    }
    values.update(overrides)
    return Settings(**values)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class _FakeTokenEndpoint:
    def __init__(
        self,
        settings: Settings,
        *,
        include_refresh_token: bool = True,
        rotate_refresh_token: bool = True,
        refresh_fails: bool = False,
        actor_id: str = DEFAULT_ACTOR,
    ) -> None:
        self.settings = settings
        self.include_refresh_token = include_refresh_token
        self.rotate_refresh_token = rotate_refresh_token
        self.refresh_fails = refresh_fails
        self.actor_id = actor_id
        self.forms: list[dict[str, str]] = []
        self.nonce = ""
        self.issued_refresh_tokens = 0

    def __call__(self, form: dict[str, str], _settings: Settings) -> dict[str, Any]:
        self.forms.append(form)
        if form.get("grant_type") == "refresh_token":
            if self.refresh_fails:
                raise OidcTokenExchangeError("invalid_grant")
            response: dict[str, Any] = {
                "access_token": _access_token(self.settings, actor_id=self.actor_id),
                "expires_in": 900,
                "token_type": "Bearer",
            }
            if self.rotate_refresh_token:
                self.issued_refresh_tokens += 1
                response["refresh_token"] = f"refresh-token-{self.issued_refresh_tokens}"
            return response
        response = {
            "access_token": _access_token(self.settings, actor_id=self.actor_id),
            "expires_in": 900,
            "token_type": "Bearer",
            "id_token": _id_token(self.settings, nonce=self.nonce, actor_id=self.actor_id),
        }
        if self.include_refresh_token:
            self.issued_refresh_tokens = max(self.issued_refresh_tokens, 1)
            response["refresh_token"] = "refresh-token-1"
        return response


def _build_app(
    settings: Settings,
    *,
    factory: sessionmaker[Session] | None = None,
    token_endpoint: _FakeTokenEndpoint | None = None,
    base_url: str = "http://testserver",
) -> tuple[TestClient, sessionmaker[Session], _FakeTokenEndpoint]:
    app = create_app(settings)
    resolved_factory = factory or _session_factory()
    app.state.session_factory = resolved_factory
    app.state.identity_verifier = StaticJwksOidcVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        algorithms=settings.oidc_algorithms,
        jwks=_oct_jwks(TOKEN_SECRET),
        tenant_claim=settings.oidc_tenant_claim,
    )
    resolved_endpoint = token_endpoint or _FakeTokenEndpoint(settings)
    app.state.oidc_token_exchanger = resolved_endpoint
    client = TestClient(app, follow_redirects=False, base_url=base_url)
    return client, resolved_factory, resolved_endpoint


def _login(
    client: TestClient,
    token_endpoint: _FakeTokenEndpoint,
    *,
    return_to: str = "/",
) -> None:
    authorize = client.get(f"/identity/oidc/authorize?return_to={return_to}")
    params = parse_qs(urlparse(authorize.headers["location"]).query)
    token_endpoint.nonce = params["nonce"][0]
    state = params["state"][0]
    callback = client.get(f"/identity/oidc/callback?code=valid-code&state={state}")
    assert callback.status_code == 307


def _csrf_headers(client: TestClient, cookie_name: str = "axis_csrf") -> dict[str, str]:
    csrf_token = client.cookies.get(cookie_name)
    assert csrf_token
    return {"X-Axis-Csrf-Token": csrf_token}


def _sessions(session: Session) -> list[OidcBrowserSession]:
    return list(
        session.scalars(
            select(OidcBrowserSession).order_by(OidcBrowserSession.created_at.asc())
        )
    )


def _audit_event_types(session: Session) -> list[str]:
    return [event.event_type for event in session.scalars(select(AuditEvent))]


def test_callback_stores_encrypted_refresh_token_with_absolute_expiry() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)

    _login(client, token_endpoint)

    with factory() as session:
        stored = _sessions(session)
        assert len(stored) == 1
        ciphertext = stored[0].refresh_token_ciphertext
        assert ciphertext
        assert "refresh-token-1" not in ciphertext
        assert decrypt_refresh_token(ciphertext, settings) == "refresh-token-1"
        assert stored[0].absolute_expires_at is not None
        assert stored[0].refresh_count == 0
        audit_events = list(session.scalars(select(AuditEvent)))
        assert [event.event_type for event in audit_events] == [
            "identity.oidc_session.created"
        ]
        assert audit_events[0].payload["refresh_token_stored"] is True
        assert "refresh-token-1" not in str(audit_events[0].payload)
    csrf_cookie = client.cookies.get("axis_csrf")
    assert csrf_cookie
    assert len(csrf_cookie) == 64


def test_session_refresh_rotates_session_and_refresh_token() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    old_session_cookie = client.cookies.get("axis_session")

    refresh = client.post("/identity/session/refresh", headers=_csrf_headers(client))

    assert refresh.status_code == 204
    new_session_cookie = client.cookies.get("axis_session")
    assert new_session_cookie
    assert new_session_cookie != old_session_cookie
    refresh_form = token_endpoint.forms[-1]
    assert refresh_form["grant_type"] == "refresh_token"
    assert refresh_form["refresh_token"] == "refresh-token-1"
    assert refresh_form["client_id"] == "axis-console"
    assert refresh_form["client_secret"] == "axis-client-secret"

    with factory() as session:
        stored = _sessions(session)
        assert len(stored) == 2
        rotated, active = stored
        assert rotated.status == "rotated"
        assert rotated.refresh_token_ciphertext is None
        assert rotated.rotated_to_session_id_hash == active.session_id_hash
        assert active.status == "active"
        assert active.refresh_count == 1
        assert active.absolute_expires_at == rotated.absolute_expires_at
        assert active.refresh_token_ciphertext
        assert decrypt_refresh_token(
            active.refresh_token_ciphertext, settings
        ) == "refresh-token-2"
        audit_events = list(session.scalars(select(AuditEvent)))
        assert [event.event_type for event in audit_events] == [
            "identity.oidc_session.created",
            "identity.oidc_session.refreshed",
        ]
        refreshed_payload = audit_events[-1].payload
        assert refreshed_payload["previous_session_id_hash"] == rotated.session_id_hash
        assert refreshed_payload["session_id_hash"] == active.session_id_hash
        assert refreshed_payload["refresh_count"] == 1
        assert refreshed_payload["refresh_token_rotated"] is True
        rendered_payloads = str([event.payload for event in audit_events])
        assert "refresh-token-1" not in rendered_payloads
        assert "refresh-token-2" not in rendered_payloads

    session_read = client.get("/identity/session")
    assert session_read.status_code == 200
    assert session_read.json()["authenticated"] is True

    client.cookies.set("axis_session", old_session_cookie)
    replayed = client.get("/identity/session")
    assert replayed.status_code == 401
    assert replayed.json()["detail"]["reason"] == "revoked_session_cookie"


def test_session_refresh_cannot_resurrect_session_revoked_during_exchange() -> None:
    settings = _settings()
    factory = _session_factory()

    class _RevokingTokenEndpoint(_FakeTokenEndpoint):
        def __call__(self, form: dict[str, str], settings: Settings) -> dict[str, Any]:
            response = super().__call__(form, settings)
            if form.get("grant_type") == "refresh_token":
                with session_scope(factory) as session:
                    repository = AxisPersistenceRepository(session)
                    parent = _sessions(session)[0]
                    assert parent.status == "refreshing"
                    repository.revoke_oidc_browser_session(
                        OidcBrowserSessionRevocation(
                            session_id_hash=parent.session_id_hash,
                            revoked_by="identity-admin-role",
                            revocation_reason="manual_security_revocation",
                        )
                    )
            return response

    endpoint = _RevokingTokenEndpoint(settings)
    client, _factory, endpoint = _build_app(
        settings,
        factory=factory,
        token_endpoint=endpoint,
    )
    _login(client, endpoint)

    refresh = client.post("/identity/session/refresh", headers=_csrf_headers(client))

    assert refresh.status_code == 401
    assert refresh.json()["detail"]["reason"] == "invalid_session_cookie"
    assert "Max-Age=0" in refresh.headers["set-cookie"]
    with factory() as session:
        stored = _sessions(session)
        assert len(stored) == 1
        assert stored[0].status == "revoked"
        assert stored[0].revocation_reason == "manual_security_revocation"
        assert stored[0].rotated_to_session_id_hash is None
        assert "identity.oidc_session.refreshed" not in _audit_event_types(session)


def test_session_refresh_requires_matching_csrf_token() -> None:
    settings = _settings()
    client, _factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)

    missing = client.post("/identity/session/refresh")
    assert missing.status_code == 403
    assert missing.json()["detail"]["reason"] == "csrf_token_required"

    mismatched = client.post(
        "/identity/session/refresh",
        headers={"X-Axis-Csrf-Token": "0" * 64},
    )
    assert mismatched.status_code == 403
    assert mismatched.json()["detail"]["reason"] == "csrf_token_mismatch"


def test_session_logout_requires_csrf_token_for_cookie_sessions() -> None:
    settings = _settings()
    client, _factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)

    response = client.post("/identity/session/logout")

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "csrf_token_required"


def test_session_refresh_failure_revokes_session_and_deletes_cookies() -> None:
    settings = _settings()
    token_endpoint = _FakeTokenEndpoint(_settings(), refresh_fails=True)
    client, factory, token_endpoint = _build_app(settings, token_endpoint=token_endpoint)
    _login(client, token_endpoint)

    refresh = client.post("/identity/session/refresh", headers=_csrf_headers(client))

    assert refresh.status_code == 401
    assert refresh.json()["detail"]["reason"] == "invalid_grant"
    set_cookie = refresh.headers["set-cookie"]
    assert "axis_session=" in set_cookie
    assert "Max-Age=0" in set_cookie
    with factory() as session:
        stored = _sessions(session)
        assert len(stored) == 1
        assert stored[0].status == "revoked"
        assert stored[0].revocation_reason == "refresh_failed"
        assert _audit_event_types(session) == [
            "identity.oidc_session.created",
            "identity.oidc_session.refresh_failed",
            "identity.oidc_session.revoked",
        ]

    replay = client.get("/identity/session")
    assert replay.status_code == 401


def test_session_refresh_conflicts_when_no_refresh_token_is_stored() -> None:
    settings = _settings(oidc_refresh_token_encryption_key=None)
    token_endpoint = _FakeTokenEndpoint(settings, include_refresh_token=False)
    client, factory, token_endpoint = _build_app(settings, token_endpoint=token_endpoint)
    _login(client, token_endpoint)

    refresh = client.post("/identity/session/refresh", headers=_csrf_headers(client))

    assert refresh.status_code == 409
    assert refresh.json()["detail"]["reason"] == "refresh_not_available"
    with factory() as session:
        stored = _sessions(session)
        assert stored[0].status == "active"
        assert stored[0].refresh_token_ciphertext is None


def test_idle_timeout_revokes_session() -> None:
    settings = _settings(oidc_session_idle_timeout_seconds=300)
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    with factory() as session:
        stored = _sessions(session)[0]
        stored.last_seen_at = datetime.now(UTC) - timedelta(seconds=301)
        session.commit()

    response = client.get("/identity/session")

    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "idle_session_timeout"
    with factory() as session:
        stored = _sessions(session)[0]
        assert stored.status == "revoked"
        assert stored.revocation_reason == "idle_timeout"
        assert stored.revoked_by == "axis-session-lifecycle"
        assert _audit_event_types(session) == [
            "identity.oidc_session.created",
            "identity.oidc_session.revoked",
        ]


def test_absolute_timeout_rejects_and_revokes_session() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    with factory() as session:
        stored = _sessions(session)[0]
        stored.absolute_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    response = client.get("/identity/session")

    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "expired_session_cookie"
    with factory() as session:
        stored = _sessions(session)[0]
        assert stored.status == "revoked"
        assert stored.revocation_reason == "absolute_timeout"


def test_session_refresh_rejects_after_absolute_timeout() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    with factory() as session:
        stored = _sessions(session)[0]
        stored.absolute_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    refresh = client.post("/identity/session/refresh", headers=_csrf_headers(client))

    assert refresh.status_code == 401
    assert refresh.json()["detail"]["reason"] == "expired_session_cookie"
    with factory() as session:
        assert _sessions(session)[0].status == "revoked"
    assert all(form.get("grant_type") != "refresh_token" for form in token_endpoint.forms)


def test_concurrent_session_limit_revokes_oldest_session() -> None:
    settings = _settings(oidc_session_max_concurrent=1)
    client, factory, token_endpoint = _build_app(settings)

    _login(client, token_endpoint)
    _login(client, token_endpoint)

    with factory() as session:
        stored = _sessions(session)
        assert len(stored) == 2
        oldest, newest = stored
        assert oldest.status == "revoked"
        assert oldest.revocation_reason == "concurrent_session_limit"
        assert newest.status == "active"
        assert _audit_event_types(session) == [
            "identity.oidc_session.created",
            "identity.oidc_session.created",
            "identity.oidc_session.revoked",
        ]

    assert client.get("/identity/session").status_code == 200


def test_tenant_quota_overrides_concurrent_session_limit() -> None:
    settings = _settings(oidc_session_max_concurrent=5)
    client, factory, token_endpoint = _build_app(settings)
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_tenant_quota(
            TenantQuotaUpsert(
                tenant_id=DEFAULT_TENANT,
                quota_key=TenantQuotaKey.MAX_CONCURRENT_SESSIONS.value,
                quota_value=1,
                updated_by="axis-platform-operator-role",
            )
        )

    _login(client, token_endpoint)
    _login(client, token_endpoint)

    with factory() as session:
        stored = _sessions(session)
        assert len(stored) == 2
        oldest, newest = stored
        assert oldest.status == "revoked"
        assert oldest.revocation_reason == "concurrent_session_limit"
        assert newest.status == "active"

    assert client.get("/identity/session").status_code == 200


def _persist_tenant(
    factory: sessionmaker[Session],
    *,
    status: str,
    tenant_id: str = DEFAULT_TENANT,
) -> None:
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).create_tenant(
            TenantCreate(
                tenant_id=tenant_id,
                display_name="Demo Manufacturing",
                status=status,
                created_by="axis-platform-operator-role",
            )
        )


def test_login_callback_rejects_suspended_tenant_fail_closed() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)
    _persist_tenant(factory, status="suspended")

    authorize = client.get("/identity/oidc/authorize?return_to=/")
    params = parse_qs(urlparse(authorize.headers["location"]).query)
    token_endpoint.nonce = params["nonce"][0]
    state = params["state"][0]
    callback = client.get(f"/identity/oidc/callback?code=valid-code&state={state}")

    assert callback.status_code == 403
    assert callback.json()["detail"]["reason"] == "tenant_suspended"
    with factory() as session:
        # No session row is created, and the denial is audited.
        assert _sessions(session) == []
        assert _audit_event_types(session) == [
            "platform.tenant.suspended_request.denied"
        ]
    assert client.cookies.get("axis_session") is None


def test_login_callback_rejects_unregistered_tenant_in_registered_only_mode() -> None:
    settings = _settings(tenant_admission_mode=TENANT_ADMISSION_REGISTERED_ONLY)
    client, factory, token_endpoint = _build_app(settings)

    authorize = client.get("/identity/oidc/authorize?return_to=/")
    params = parse_qs(urlparse(authorize.headers["location"]).query)
    token_endpoint.nonce = params["nonce"][0]
    state = params["state"][0]
    callback = client.get(f"/identity/oidc/callback?code=valid-code&state={state}")

    assert callback.status_code == 403
    assert callback.json()["detail"]["reason"] == "tenant_not_registered"
    with factory() as session:
        assert _sessions(session) == []
        assert _audit_event_types(session) == [
            UNREGISTERED_REQUEST_DENIED_AUDIT_EVENT_TYPE
        ]
    assert client.cookies.get("axis_session") is None


def test_session_refresh_rejects_suspended_tenant_and_revokes_session() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    # Suspend the tenant behind the API's back after a healthy login.
    _persist_tenant(factory, status="suspended")

    refresh = client.post("/identity/session/refresh", headers=_csrf_headers(client))

    assert refresh.status_code == 403
    assert refresh.json()["detail"]["reason"] == "tenant_suspended"
    with factory() as session:
        stored = _sessions(session)
        assert len(stored) == 1
        assert stored[0].status == "revoked"
        assert stored[0].revocation_reason == "tenant_suspended"
        assert "identity.oidc_session.revoked" in _audit_event_types(session)
    # No refresh_token grant was attempted against the IdP.
    assert all(form.get("grant_type") != "refresh_token" for form in token_endpoint.forms)


def test_session_refresh_rejects_tenant_removed_after_login() -> None:
    settings = _settings(tenant_admission_mode=TENANT_ADMISSION_REGISTERED_ONLY)
    client, factory, token_endpoint = _build_app(settings)
    _persist_tenant(factory, status="active")
    _login(client, token_endpoint)
    with session_scope(factory) as session:
        tenant = session.get(Tenant, DEFAULT_TENANT)
        assert tenant is not None
        session.delete(tenant)

    refresh = client.post("/identity/session/refresh", headers=_csrf_headers(client))

    assert refresh.status_code == 403
    assert refresh.json()["detail"]["reason"] == "tenant_not_registered"
    with factory() as session:
        stored = _sessions(session)
        assert len(stored) == 1
        assert stored[0].status == "revoked"
        assert stored[0].revocation_reason == "tenant_not_registered"
        assert "identity.oidc_session.revoked" in _audit_event_types(session)
    assert all(form.get("grant_type") != "refresh_token" for form in token_endpoint.forms)


def test_identity_sessions_lists_own_sessions_with_current_flag() -> None:
    settings = _settings()
    client, _factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    assert (
        client.post("/identity/session/refresh", headers=_csrf_headers(client)).status_code
        == 204
    )

    response = client.get("/identity/sessions")

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == DEFAULT_TENANT
    assert body["actor_id"] == DEFAULT_ACTOR
    assert body["tenant_wide"] is False
    assert len(body["sessions"]) == 2
    by_status = {record["status"]: record for record in body["sessions"]}
    assert by_status["active"]["current"] is True
    assert by_status["active"]["refresh_count"] == 1
    assert by_status["rotated"]["current"] is False
    rendered = str(body).lower()
    assert "ciphertext" not in rendered
    assert "refresh-token" not in rendered
    assert "session_id_hash" not in rendered


def test_identity_sessions_requires_authentication() -> None:
    settings = _settings()
    client, _factory, _token_endpoint = _build_app(settings)

    response = client.get("/identity/sessions")

    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "missing_authorization"


def test_identity_sessions_tenant_wide_requires_admin_scope() -> None:
    settings = _settings()
    client, _factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)

    forbidden = client.get(
        "/identity/sessions?tenant_wide=true",
        headers={"Authorization": f"Bearer {_access_token(settings)}"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["required_permission"] == "identity:sessions:admin"

    admin_token = _access_token(
        settings,
        actor_id="identity-admin-role",
        scope="identity:sessions:admin",
    )
    allowed = client.get(
        "/identity/sessions?tenant_wide=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["tenant_wide"] is True
    assert {record["actor_id"] for record in body["sessions"]} == {DEFAULT_ACTOR}


def test_revoke_own_session_by_reference() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    listing = client.get("/identity/sessions").json()
    session_ref = listing["sessions"][0]["session_ref"]

    response = client.post(
        f"/identity/sessions/{session_ref}/revoke",
        headers=_csrf_headers(client),
    )

    assert response.status_code == 204
    with factory() as session:
        stored = _sessions(session)[0]
        assert stored.status == "revoked"
        assert stored.revocation_reason == "self_revocation"
        assert stored.revoked_by == DEFAULT_ACTOR
        # Revocation drops the at-rest refresh credential.
        assert stored.refresh_token_ciphertext is None
        assert _audit_event_types(session) == [
            "identity.oidc_session.created",
            "identity.oidc_session.revoked",
        ]

    assert client.get("/identity/session").status_code == 401


def test_revoke_own_refreshing_session_by_reference() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    with factory() as session:
        stored = _sessions(session)[0]
        stored.status = "refreshing"
        session_ref = str(stored.id)
        session.commit()

    response = client.post(
        f"/identity/sessions/{session_ref}/revoke",
        headers={"Authorization": f"Bearer {_access_token(settings)}"},
    )

    assert response.status_code == 204
    with factory() as session:
        stored = _sessions(session)[0]
        assert stored.status == "revoked"
        assert stored.revocation_reason == "self_revocation"
        assert stored.revoked_by == DEFAULT_ACTOR
        assert stored.refresh_token_ciphertext is None
        assert _audit_event_types(session) == [
            "identity.oidc_session.created",
            "identity.oidc_session.revoked",
        ]

    assert client.get("/identity/session").status_code == 401


def test_revoking_other_actor_session_requires_admin_scope() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    with factory() as session:
        session_ref = str(_sessions(session)[0].id)

    forbidden = client.post(
        f"/identity/sessions/{session_ref}/revoke",
        headers={"Authorization": f"Bearer {_access_token(settings, actor_id='other-actor')}"},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["required_permission"] == "identity:sessions:admin"

    admin_token = _access_token(
        settings,
        actor_id="identity-admin-role",
        scope="identity:sessions:admin",
    )
    allowed = client.post(
        f"/identity/sessions/{session_ref}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert allowed.status_code == 204
    with factory() as session:
        stored = _sessions(session)[0]
        assert stored.status == "revoked"
        assert stored.revocation_reason == "admin_revocation"
        assert stored.revoked_by == "identity-admin-role"


def test_admin_can_revoke_refreshing_session_by_reference() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    with factory() as session:
        stored = _sessions(session)[0]
        stored.status = "refreshing"
        session_ref = str(stored.id)
        session.commit()

    admin_token = _access_token(
        settings,
        actor_id="identity-admin-role",
        scope="identity:sessions:admin",
    )
    response = client.post(
        f"/identity/sessions/{session_ref}/revoke",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 204
    with factory() as session:
        stored = _sessions(session)[0]
        assert stored.status == "revoked"
        assert stored.revocation_reason == "admin_revocation"
        assert stored.revoked_by == "identity-admin-role"
        assert stored.refresh_token_ciphertext is None


def test_revoking_session_in_another_tenant_returns_404() -> None:
    settings = _settings()
    client, factory, _token_endpoint = _build_app(settings)
    with factory() as session:
        foreign_session = OidcBrowserSession(
            session_id_hash="f" * 64,
            tenant_id="tenant_other",
            actor_id="other-tenant-actor",
            status="active",
            scopes=[],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(foreign_session)
        session.commit()
        session_ref = str(foreign_session.id)

    response = client.post(
        f"/identity/sessions/{session_ref}/revoke",
        headers={"Authorization": f"Bearer {_access_token(settings)}"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "session_not_found"
    with factory() as session:
        assert _sessions(session)[0].status == "active"


def test_secure_profile_sets_host_prefixed_cookie_attributes() -> None:
    settings = _settings(oidc_session_cookie_secure=True)
    client, _factory, token_endpoint = _build_app(settings, base_url="https://testserver")
    authorize = client.get("/identity/oidc/authorize?return_to=/")
    params = parse_qs(urlparse(authorize.headers["location"]).query)
    token_endpoint.nonce = params["nonce"][0]
    state = params["state"][0]

    callback = client.get(f"/identity/oidc/callback?code=valid-code&state={state}")

    assert callback.status_code == 307
    cookies = SimpleCookie()
    for header_value in callback.headers.get_list("set-cookie"):
        cookies.load(header_value)
    session_cookie = cookies["__Host-axis_session"]
    assert session_cookie["httponly"] is True
    assert session_cookie["secure"] is True
    assert session_cookie["samesite"] == "lax"
    assert session_cookie["path"] == "/"
    csrf_cookie = cookies["__Host-axis_csrf"]
    assert csrf_cookie["secure"] is True
    assert csrf_cookie["httponly"] == ""
    assert csrf_cookie["path"] == "/"
    session_claims = read_session_cookie(session_cookie.value, settings)
    assert session_claims.actor_id == DEFAULT_ACTOR

    session_read = client.get("/identity/session")
    assert session_read.status_code == 200
    assert session_read.json()["mode"] == "secure_oidc_cookie"


# --- Centralized CSRF coverage on a non-identity mutating route -------------


def _seed_approval_inbox(factory: sessionmaker[Session]) -> None:
    migrations_dir = Path(__file__).parents[1] / "migrations" / "versions"
    payload = deepcopy(
        run_path(str(migrations_dir / "0027_approval_inbox_reference.py"))[
            "APPROVAL_INBOX_PAYLOAD"
        ]
    )
    with session_scope(factory) as session:
        AxisPersistenceRepository(session).upsert_demo_reference_record(
            DemoReferenceRecordCreate(
                tenant_id="tenant_demo_manufacturing",
                surface="approvals",
                reference_id="manufacturing-approval-inbox",
                status="active",
                source="bootstrap",
                version="2026-06-22",
                payload=payload,
            )
        )


class _StaticApprovalWorkflowRuntime:
    async def signal_approval_decision(self, request: Any) -> Any:
        return WorkflowSignalResult(
            workflow_id=request.workflow_id,
            status="approval_signaled",
            adapter="axis-test-workflow-adapter",
            signal_name=request.signal_name,
            payload={
                "approval_id": request.approval_id,
                "approved": request.approved,
                "decision": request.decision.value,
            },
        )


def _approval_decision_body() -> dict[str, Any]:
    return {
        "decision": "approve",
        "actor_id": DEFAULT_ACTOR,
        "actor_scopes": [],
        "note": "Approved in CSRF middleware coverage test.",
    }


def test_non_identity_mutating_route_rejects_missing_csrf_for_cookie_session() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)
    _seed_approval_inbox(factory)
    client.app.state.workflow_runtime = _StaticApprovalWorkflowRuntime()
    _login(client, token_endpoint)

    response = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        json=_approval_decision_body(),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "csrf_token_required"
    with factory() as session:
        assert list(session.scalars(select(AuditEvent).where(
            AuditEvent.event_type == "approval.decision.recorded"
        ))) == []


def test_non_identity_mutating_route_rejects_mismatched_csrf_for_cookie_session() -> None:
    settings = _settings()
    client, _factory, token_endpoint = _build_app(settings)
    _seed_approval_inbox(_factory)
    client.app.state.workflow_runtime = _StaticApprovalWorkflowRuntime()
    _login(client, token_endpoint)

    response = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        headers={"X-Axis-Csrf-Token": "0" * 64},
        json=_approval_decision_body(),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "csrf_token_mismatch"


def test_non_identity_mutating_route_accepts_valid_csrf_for_cookie_session() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)
    _seed_approval_inbox(factory)
    client.app.state.workflow_runtime = _StaticApprovalWorkflowRuntime()
    _login(client, token_endpoint)

    response = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        headers=_csrf_headers(client),
        json=_approval_decision_body(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["approval_id"] == "appr_expedite_supplier_batch"
    assert body["actor_id"] == DEFAULT_ACTOR


def test_non_identity_mutating_route_with_bearer_auth_is_csrf_exempt() -> None:
    settings = _settings()
    client, factory, _token_endpoint = _build_app(settings)
    _seed_approval_inbox(factory)
    client.app.state.workflow_runtime = _StaticApprovalWorkflowRuntime()

    # No session cookie is attached; the request authenticates with a bearer
    # token and must not require a CSRF header.
    response = client.post(
        "/demo/manufacturing/approvals/appr_expedite_supplier_batch/decision",
        headers={"Authorization": f"Bearer {_access_token(settings)}"},
        json=_approval_decision_body(),
    )

    assert response.status_code == 201
    assert response.json()["actor_id"] == DEFAULT_ACTOR


def test_safe_methods_never_require_csrf_for_cookie_session() -> None:
    settings = _settings()
    client, _factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)

    # GET carries the session cookie but no CSRF header and must pass.
    response = client.get("/identity/session")

    assert response.status_code == 200
    assert response.json()["authenticated"] is True


# --- Concurrent-refresh safety at the persistence/locking seam --------------


def test_concurrent_refresh_claim_allows_exactly_one_winner() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    with factory() as session:
        session_hash = _sessions(session)[0].session_id_hash

    # Two concurrent refreshes with the same cookie both observe status="active"
    # but only one may win the active->refreshing transition.
    with factory() as session:
        first = AxisPersistenceRepository(session).claim_oidc_browser_session_refresh(
            session_hash
        )
        session.commit()
    with factory() as session:
        second = AxisPersistenceRepository(session).claim_oidc_browser_session_refresh(
            session_hash
        )
        session.commit()

    assert first is True
    assert second is False
    with factory() as session:
        assert _sessions(session)[0].status == "refreshing"


def test_refresh_after_rotation_replay_produces_no_second_child() -> None:
    settings = _settings()
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    original_cookie = client.cookies.get("axis_session")
    original_csrf = _csrf_headers(client)

    assert client.post("/identity/session/refresh", headers=original_csrf).status_code == 204
    with factory() as session:
        assert len(_sessions(session)) == 2

    # Replaying the pre-rotation cookie must not mint a second child session.
    client.cookies.set("axis_session", original_cookie)
    replay = client.post("/identity/session/refresh", headers=original_csrf)

    assert replay.status_code == 401
    assert replay.json()["detail"]["reason"] == "revoked_session_cookie"
    with factory() as session:
        stored = _sessions(session)
        assert len(stored) == 2
        assert sum(1 for row in stored if row.status == "active") == 1


def test_non_ascii_session_cookie_is_rejected_as_invalid_not_500() -> None:
    settings = _settings()
    client, _factory, _token_endpoint = _build_app(settings)

    # Header values are latin-1 decodable, so an attacker can smuggle
    # non-ASCII bytes into the cookie value; it must fail closed as an
    # invalid cookie instead of crashing signature verification.
    response = client.get(
        "/identity/session",
        headers={"Cookie": b"axis_session=\xffgarbage.\xffsig"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "invalid_session_cookie"


def test_non_ascii_csrf_header_is_rejected_as_mismatch_not_500() -> None:
    settings = _settings()
    client, _factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)

    response = client.post(
        "/identity/session/refresh",
        headers={"X-Axis-Csrf-Token": b"\xff" * 64},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["reason"] == "csrf_token_mismatch"


def _mark_session_refreshing(
    factory: sessionmaker[Session],
    *,
    claimed_seconds_ago: int,
) -> None:
    with factory() as session:
        stored = _sessions(session)[0]
        stored.status = "refreshing"
        stored.updated_at = datetime.now(UTC) - timedelta(seconds=claimed_seconds_ago)
        session.commit()


def test_stale_refreshing_session_is_revoked_as_orphaned_on_presentation() -> None:
    settings = _settings(oidc_refresh_claim_staleness_seconds=60)
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    _mark_session_refreshing(factory, claimed_seconds_ago=61)

    response = client.get("/identity/session")

    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "revoked_session_cookie"
    with factory() as session:
        stored = _sessions(session)[0]
        assert stored.status == "revoked"
        assert stored.revocation_reason == "refresh_claim_orphaned"
        assert stored.revoked_by == "axis-session-lifecycle"
        # Orphan recovery revokes via the same path, so the credential is dropped.
        assert stored.refresh_token_ciphertext is None
        revoked_events = [
            event
            for event in session.scalars(select(AuditEvent))
            if event.event_type == "identity.oidc_session.revoked"
        ]
        assert len(revoked_events) == 1
        assert revoked_events[0].payload["revocation_reason"] == "refresh_claim_orphaned"
        assert stored.revoke_audit_event_id == revoked_events[0].id


def test_stale_refreshing_session_refresh_attempt_is_revoked_as_orphaned() -> None:
    settings = _settings(oidc_refresh_claim_staleness_seconds=60)
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    _mark_session_refreshing(factory, claimed_seconds_ago=61)

    refresh = client.post("/identity/session/refresh", headers=_csrf_headers(client))

    assert refresh.status_code == 401
    assert refresh.json()["detail"]["reason"] == "revoked_session_cookie"
    # No IdP refresh grant is attempted for an orphaned claim.
    assert all(form.get("grant_type") != "refresh_token" for form in token_endpoint.forms)
    with factory() as session:
        stored = _sessions(session)[0]
        assert stored.status == "revoked"
        assert stored.revocation_reason == "refresh_claim_orphaned"


def test_fresh_refreshing_session_is_rejected_but_left_for_the_active_claim() -> None:
    settings = _settings(oidc_refresh_claim_staleness_seconds=120)
    client, factory, token_endpoint = _build_app(settings)
    _login(client, token_endpoint)
    _mark_session_refreshing(factory, claimed_seconds_ago=1)

    response = client.get("/identity/session")

    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "revoked_session_cookie"
    with factory() as session:
        stored = _sessions(session)[0]
        assert stored.status == "refreshing"
        assert stored.revocation_reason is None
        assert _audit_event_types(session) == ["identity.oidc_session.created"]


# --- HKDF key derivation and weak-key rejection -----------------------------


def test_weak_refresh_key_is_rejected_at_startup() -> None:
    with pytest.raises(OidcCodeFlowConfigurationError) as exc:
        create_app(_settings(oidc_refresh_token_encryption_key="short-key"))
    assert exc.value.reason == "weak_refresh_token_encryption_key"


def test_weak_refresh_key_reports_not_strong() -> None:
    assert refresh_token_encryption_key_is_strong(
        _settings(oidc_refresh_token_encryption_key="short-key")
    ) is False
    assert refresh_token_encryption_key_is_strong(_settings()) is True


def test_validate_refresh_key_is_noop_when_unset() -> None:
    # A missing key is a deferred-feature state, not a misconfiguration.
    validate_refresh_token_encryption_key(
        _settings(oidc_refresh_token_encryption_key=None)
    )


def test_hkdf_key_derivation_differs_from_bare_sha256() -> None:
    settings = _settings()
    ciphertext = encrypt_refresh_token("provider-refresh-token", settings)
    assert decrypt_refresh_token(ciphertext, settings) == "provider-refresh-token"

    # The AES key is HKDF-derived, not a bare SHA-256 of the config string, so a
    # ciphertext produced under the real key cannot be read with the naive key.
    naive_key = hashlib.sha256(STRONG_REFRESH_KEY.encode()).digest()
    raw = base64.urlsafe_b64decode(ciphertext + "=" * (-len(ciphertext) % 4))
    nonce, blob = raw[:12], raw[12:]
    try:
        AESGCM(naive_key).decrypt(nonce, blob, b"axis-oidc-refresh-token")
        raise AssertionError("HKDF key must not equal bare sha256(config)")
    except InvalidTag:
        pass
