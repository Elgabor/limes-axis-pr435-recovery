"""The enforced-auth session report is the console's friendly entry gate.

With ``AXIS_OIDC_AUTH_REQUIRED=true`` an unauthenticated browser must still be
able to read ``GET /identity/session`` so the console can render a sign-in
gate instead of generic API error panels. The endpoint reports only safe
facts: authentication state, readiness posture, public IdP coordinates
(issuer, audience) and a classified ``unauthenticated_reason``. It never
returns token material, and it never honors credentials that fail
verification. Every tenant read/write keeps failing closed with 401/403.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from jose import jwt
from jose.utils import base64url_encode
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.identity import StaticJwksOidcVerifier
from axis_api.main import create_app
from axis_api.models import Base

TOKEN_SECRET = "axis-test-secret"
DEFAULT_ACTOR = "plant-operations-owner-role"
DEFAULT_TENANT = "tenant_demo_manufacturing"


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


def _settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
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
        "oidc_authorization_url": ("https://idp.example/realms/axis/protocol/openid-connect/auth"),
        "oidc_token_url": "https://idp.example/realms/axis/protocol/openid-connect/token",
        "oidc_session_cookie_signing_secret": "a-secure-cookie-signing-secret",
        "oidc_session_cookie_secure": False,
    }
    values.update(overrides)
    return Settings(**values)


def _build_app(settings: Settings) -> tuple[TestClient, sessionmaker[Session]]:
    app = create_app(settings)
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    app.state.session_factory = factory
    app.state.identity_verifier = StaticJwksOidcVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        algorithms=settings.oidc_algorithms,
        jwks=_oct_jwks(TOKEN_SECRET),
        tenant_claim=settings.oidc_tenant_claim,
    )
    return TestClient(app), factory


def _access_token(
    settings: Settings,
    *,
    actor_id: str = DEFAULT_ACTOR,
    tenant_id: str = DEFAULT_TENANT,
    scope: str = "audit:read approvals:supply:decide",
) -> str:
    payload = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "sub": actor_id,
        "axis_tenant": tenant_id,
        "scope": scope,
        "exp": 4102444800,
    }
    return jwt.encode(payload, TOKEN_SECRET, algorithm="HS256", headers={"kid": "axis-test"})


def test_session_report_stays_readable_without_credentials_when_auth_required() -> None:
    client, _factory = _build_app(_settings())

    response = client.get("/identity/session")

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert body["api_auth_required"] is True
    assert body["unauthenticated_reason"] == "missing_authorization"
    assert body["actor_id"] is None
    assert body["tenant_id"] is None
    assert body["scopes"] == []
    # Public IdP coordinates only: enough for the console to build an
    # authorize URL, never a secret or token.
    assert body["issuer"] == "https://idp.example/realms/axis"
    assert body["audience"] == "limes-axis-api"
    rendered = str(body).lower()
    assert "axis-client-secret" not in rendered
    assert "access_token" not in rendered


def test_session_report_classifies_an_invalid_bearer_without_honoring_it() -> None:
    client, _factory = _build_app(_settings())

    response = client.get(
        "/identity/session",
        headers={"Authorization": "Bearer not-a-jwt"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert body["unauthenticated_reason"] == "invalid_token"
    assert body["actor_id"] is None
    assert body["tenant_id"] is None


def test_tenant_reads_still_fail_closed_when_the_session_report_is_public() -> None:
    settings = _settings()
    client, _factory = _build_app(settings)

    anonymous = client.get("/operations/approvals?tenant_id=tenant_demo_manufacturing")
    assert anonymous.status_code == 401
    assert anonymous.json()["detail"]["reason"] == "missing_authorization"

    forged = client.get(
        "/operations/approvals?tenant_id=tenant_demo_manufacturing",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert forged.status_code == 401
    assert forged.json()["detail"]["reason"] == "invalid_token"


def test_valid_bearer_still_receives_the_full_authenticated_report() -> None:
    settings = _settings()
    client, _factory = _build_app(settings)

    response = client.get(
        "/identity/session",
        headers={"Authorization": f"Bearer {_access_token(settings)}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["mode"] == "validated_oidc_bearer"
    assert body["actor_id"] == DEFAULT_ACTOR
    assert body["tenant_id"] == DEFAULT_TENANT
    assert body["session_boundary"] == "bearer_token_verified_by_axis_api"
    assert body["unauthenticated_reason"] is None


def test_public_demo_mode_reports_no_failure_reason_for_anonymous_callers() -> None:
    client, _factory = _build_app(_settings(oidc_auth_required=False))

    response = client.get("/identity/session")

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert body["api_auth_required"] is False
    assert body["unauthenticated_reason"] is None


def test_expired_bearer_is_classified_not_crashed() -> None:
    settings = _settings()
    expired_payload = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "sub": DEFAULT_ACTOR,
        "axis_tenant": DEFAULT_TENANT,
        "scope": "audit:read",
        "exp": 1000000000,
    }
    expired_token = jwt.encode(
        expired_payload,
        TOKEN_SECRET,
        algorithm="HS256",
        headers={"kid": "axis-test"},
    )
    client, _factory = _build_app(settings)

    response = client.get(
        "/identity/session",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert body["unauthenticated_reason"] in {"invalid_token", "token_expired"}
