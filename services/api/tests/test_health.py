from fastapi.testclient import TestClient
from jose import jwt
from jose.utils import base64url_encode
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from axis_api.config import Settings
from axis_api.identity import StaticJwksOidcVerifier
from axis_api.main import create_app
from axis_api.models import AuditEvent, Base
from axis_api.platform_tenants import TenantStateSnapshot
from axis_api.rate_limit import InMemoryRateLimiter
from axis_api.runtime_readiness import static_runtime_readiness_service


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


def _token(secret: str, claims: dict) -> str:
    return jwt.encode(claims, secret, algorithm="HS256", headers={"kid": "axis-test"})


class _ActiveTenantStateCache:
    def snapshot(self, _session_factory, _tenant_id: str) -> TenantStateSnapshot:
        return TenantStateSnapshot(status="active", quotas={})


class _SuspendedTenantStateCache:
    def snapshot(self, _session_factory, _tenant_id: str) -> TenantStateSnapshot:
        return TenantStateSnapshot(status="suspended", quotas={})


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "axis-api"}


async def _healthy_probe() -> None:
    return None


async def _failing_probe() -> None:
    raise RuntimeError("postgresql://user:secret@internal.example/axis")


def _readiness_service(*, postgres_probe=_healthy_probe):
    return static_runtime_readiness_service(
        {
            "postgres": (True, postgres_probe),
            "typedb": (False, None),
            "temporal": (False, None),
        }
    )


def test_ready_checks_required_dependencies_without_exposing_secrets() -> None:
    client = TestClient(create_app(readiness_service=_readiness_service()))
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    postgres_latency_ms = body["dependencies"]["postgres"]["latency_ms"]
    assert body["dependencies"] == {
        "postgres": {
            "required": True,
            "status": "ready",
            "latency_ms": postgres_latency_ms,
        },
        "typedb": {"required": False, "status": "disabled", "latency_ms": 0.0},
        "temporal": {"required": False, "status": "disabled", "latency_ms": 0.0},
    }
    assert "password" not in str(body).lower()


def test_ready_returns_503_and_redacts_dependency_errors() -> None:
    client = TestClient(
        create_app(readiness_service=_readiness_service(postgres_probe=_failing_probe))
    )

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["dependencies"]["postgres"]["status"] == "unavailable"
    assert "secret" not in str(body).lower()


def test_ready_degrades_after_persistent_usage_projection_failures() -> None:
    app = create_app(
        Settings(
            postgres_dsn="sqlite+pysqlite://",
            usage_metering_enabled=True,
            workflow_signals_enabled=False,
        )
    )
    projector = app.state.usage_event_projector
    with projector._lock:
        projector._initialized = True
        projector._consecutive_failures = projector.failure_threshold

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    latency_ms = response.json()["dependencies"]["usage_metering"]["latency_ms"]
    assert response.json()["dependencies"]["usage_metering"] == {
        "required": True,
        "status": "unavailable",
        "latency_ms": latency_ms,
    }


def test_local_console_origin_is_allowed_for_cors_preflight() -> None:
    client = TestClient(create_app())
    response = client.options(
        "/ready",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_console_no_store_fetch_header_is_allowed_for_cors_preflight() -> None:
    client = TestClient(create_app())
    response = client.options(
        "/demo/manufacturing/overview",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "cache-control",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert "cache-control" in response.headers["access-control-allow-headers"].lower()


def test_playwright_console_origin_is_allowed_for_cors_preflight() -> None:
    client = TestClient(create_app())
    response = client.options(
        "/demo/manufacturing/overview",
        headers={
            "Origin": "http://127.0.0.1:3100",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "cache-control",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3100"
    assert "cache-control" in response.headers["access-control-allow-headers"].lower()


def test_openapi_metadata_names_axis() -> None:
    client = TestClient(create_app())
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Limes Axis API"
    assert "/ready" in response.json()["paths"]


def test_production_disables_public_api_documentation() -> None:
    settings = Settings(
        environment="production",
        postgres_dsn="sqlite+pysqlite://",
        oidc_auth_required=True,
        api_rate_limit_enabled=True,
        api_rate_limit_paths=["*"],
        api_rate_limit_backend="redis",
        api_rate_limit_failure_mode="closed",
        redis_url="redis://rate-limit.internal:6379/0",
        tenant_admission_mode="registered_only",
    )
    client = TestClient(
        create_app(
            settings,
            rate_limit_backend=InMemoryRateLimiter(
                limit=120,
                window_seconds=60,
            ),
        )
    )

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_api_rate_limiter_is_disabled_by_default_for_local_demos() -> None:
    client = TestClient(create_app(Settings(postgres_dsn="sqlite+pysqlite://")))

    responses = [client.get("/health") for _ in range(4)]

    assert [response.status_code for response in responses] == [200, 200, 200, 200]


def test_api_rate_limiter_blocks_over_limit_client_endpoint() -> None:
    client = TestClient(
        create_app(
            Settings(
                postgres_dsn="sqlite+pysqlite://",
                api_rate_limit_enabled=True,
                api_rate_limit_requests=2,
                api_rate_limit_window_seconds=60,
                api_rate_limit_paths=["/identity/oidc/readiness"],
            )
        )
    )

    first = client.get("/identity/oidc/readiness")
    second = client.get("/identity/oidc/readiness")
    third = client.get("/identity/oidc/readiness")

    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "2"
    assert first.headers["x-ratelimit-remaining"] == "1"
    assert second.status_code == 200
    assert second.headers["x-ratelimit-remaining"] == "0"
    assert third.status_code == 429
    assert third.headers["retry-after"] == "60"
    assert third.headers["x-ratelimit-limit"] == "2"
    assert third.headers["x-ratelimit-remaining"] == "0"
    assert third.json() == {
        "detail": {
            "code": "RATE_LIMITED",
            "message": "Too many requests for this endpoint.",
            "limit": 2,
            "window_seconds": 60,
            "retry_after_seconds": 60,
            "scope": "client_endpoint",
        }
    }


def test_api_rate_limiter_keeps_each_endpoint_bucket_separate() -> None:
    client = TestClient(
        create_app(
            Settings(
                postgres_dsn="sqlite+pysqlite://",
                api_rate_limit_enabled=True,
                api_rate_limit_requests=1,
                api_rate_limit_window_seconds=60,
                api_rate_limit_paths=["/identity/oidc/readiness", "/ready"],
                workflow_signals_enabled=False,
            )
        )
    )

    assert client.get("/identity/oidc/readiness").status_code == 200
    assert client.get("/identity/oidc/readiness").status_code == 429
    assert client.get("/ready").status_code == 200


def test_oidc_readiness_reports_enterprise_profile_without_secrets() -> None:
    client = TestClient(
        create_app(
            Settings(
                postgres_dsn="sqlite+pysqlite://",
                oidc_auth_required=True,
                oidc_issuer="https://idp.example/realms/axis",
                oidc_audience="limes-axis-api",
                oidc_jwks_url="https://idp.example/realms/axis/protocol/openid-connect/certs",
                oidc_algorithms=["RS256"],
                oidc_actor_claim="preferred_username",
                oidc_tenant_claim="axis_tenant",
                oidc_jwks_cache_seconds=900,
                oidc_client_id="axis-console",
                oidc_authorization_url=(
                    "https://idp.example/realms/axis/protocol/openid-connect/auth"
                ),
                oidc_token_url="https://idp.example/realms/axis/protocol/openid-connect/token",
                oidc_end_session_url=(
                    "https://idp.example/realms/axis/protocol/openid-connect/logout"
                ),
                oidc_post_logout_redirect_uri="https://console.axis.example/signed-out",
                oidc_session_cookie_signing_secret="axis-cookie-signing-secret",
                oidc_session_cookie_secure=True,
                oidc_refresh_token_encryption_key="axis-refresh-credential-encryption-key-01",
                workflow_signals_enabled=False,
            )
        )
    )

    response = client.get("/identity/oidc/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["enterprise_sso_ready"] is True
    assert body["auth_required"] is True
    assert body["issuer"] == "https://idp.example/realms/axis"
    assert body["audience"] == "limes-axis-api"
    assert body["jwks_source"] == "configured"
    assert body["jwks_url_configured"] is True
    assert body["jwks_cache_seconds"] == 900
    assert body["federated_logout"] == {
        "end_session_source": "configured",
        "end_session_url_configured": True,
        "post_logout_redirect_uri": "https://console.axis.example/signed-out",
        "stores_provider_logout_tokens": False,
    }
    assert body["token_binding"] == {
        "actor_claim": "preferred_username",
        "tenant_claim": "axis_tenant",
        "scope_sources": [
            "scope",
            "scp",
            "realm_access.roles",
            "resource_access[limes-axis-api].roles",
        ],
    }
    assert body["session_lifecycle"] == {
        "idle_timeout_seconds": 1800,
        "absolute_timeout_seconds": 28800,
        "max_concurrent_sessions": 5,
        "refresh_credential_encryption_configured": True,
        "refresh_rotation": "server_side_rotating_sessions",
        "csrf_protection": "hmac_double_submit_header",
        "host_prefixed_session_cookie": True,
    }
    assert {check["check_id"]: check["status"] for check in body["checks"]} == {
        "auth_required": "ready",
        "https_issuer": "ready",
        "explicit_jwks_url": "ready",
        "asymmetric_algorithms": "ready",
        "openid_scope": "ready",
        "tenant_claim": "ready",
        "actor_claim": "ready",
        "authorization_code_client": "ready",
        "authorization_endpoint": "ready",
        "token_endpoint": "ready",
        "end_session_endpoint": "ready",
        "post_logout_redirect": "ready",
        "session_cookie_signing": "ready",
        "secure_session_cookie": "ready",
        "host_prefixed_session_cookie": "ready",
        "refresh_credential_encryption": "ready",
        "session_idle_timeout": "ready",
        "session_absolute_timeout": "ready",
    }
    assert "secret" not in str(body).lower()
    assert "password" not in str(body).lower()
    assert "refresh_token" not in str(body).lower()


def test_oidc_onboarding_report_is_public_safe_and_computed_from_settings() -> None:
    client = TestClient(
        create_app(
            Settings(
                postgres_dsn="sqlite+pysqlite://",
                public_base_url="https://console.axis.example",
                api_base_url="https://api.axis.example",
                oidc_auth_required=True,
                oidc_issuer="https://idp.example/realms/axis",
                oidc_audience="limes-axis-api",
                oidc_jwks_url="https://idp.example/realms/axis/protocol/openid-connect/certs",
                oidc_algorithms=["RS256"],
                oidc_actor_claim="preferred_username",
                oidc_tenant_claim="axis_tenant",
                oidc_client_id="axis-console",
                oidc_client_secret="super-secret-client-secret",
                oidc_authorization_url=(
                    "https://idp.example/realms/axis/protocol/openid-connect/auth"
                ),
                oidc_token_url="https://idp.example/realms/axis/protocol/openid-connect/token",
                oidc_redirect_uri="https://api.axis.example/identity/oidc/callback",
                oidc_end_session_url=(
                    "https://idp.example/realms/axis/protocol/openid-connect/logout"
                ),
                oidc_post_logout_redirect_uri="https://console.axis.example/signed-out",
                oidc_session_cookie_signing_secret="super-secret-cookie-signing-key",
                oidc_session_cookie_secure=True,
                oidc_refresh_token_encryption_key="axis-refresh-credential-encryption-key-01",
                workflow_signals_enabled=False,
            )
        )
    )

    response = client.get("/identity/oidc/onboarding")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["enterprise_sso_ready"] is True
    assert body["provider"]["issuer"] == "https://idp.example/realms/axis"
    assert (
        body["provider"]["discovery_url"]
        == "https://idp.example/realms/axis/.well-known/openid-configuration"
    )
    assert (
        body["provider"]["jwks_url"]
        == "https://idp.example/realms/axis/protocol/openid-connect/certs"
    )
    assert (
        body["provider"]["authorization_url"]
        == "https://idp.example/realms/axis/protocol/openid-connect/auth"
    )
    assert body["client"]["client_id"] == "axis-console"
    assert body["client"]["redirect_uri"] == "https://api.axis.example/identity/oidc/callback"
    assert (
        body["client"]["post_logout_redirect_uri"]
        == "https://console.axis.example/signed-out"
    )
    assert body["client"]["auth_flow"] == "authorization_code_pkce"
    assert body["client"]["confidential_client_configured"] is True
    assert body["client"]["session_cookie_secure"] is True
    assert body["required_redirect_uris"] == ["https://api.axis.example/identity/oidc/callback"]
    assert body["required_post_logout_redirect_uris"] == [
        "https://console.axis.example/signed-out"
    ]
    assert body["claims"]["actor_claim"] == "preferred_username"
    assert body["claims"]["tenant_claim"] == "axis_tenant"
    assert body["open_action_items"] == []

    rendered = str(body).lower()
    forbidden_terms = (
        "super-secret",
        "client_secret",
        "cookie-signing",
        "access_token",
        "refresh_token",
        "id_token",
        "password",
    )
    assert all(term not in rendered for term in forbidden_terms)


def test_oidc_onboarding_report_lists_action_items_for_local_profile() -> None:
    client = TestClient(create_app(Settings(postgres_dsn="sqlite+pysqlite://")))

    response = client.get("/identity/oidc/onboarding")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "action_required"
    assert body["enterprise_sso_ready"] is False
    assert body["client"]["client_id"] is None
    assert body["client"]["session_cookie_secure"] is False
    assert body["provider"]["jwks_source"] == "derived_from_issuer"
    assert set(body["open_action_items"]) >= {
        "auth_required",
        "https_issuer",
        "explicit_jwks_url",
        "authorization_code_client",
        "end_session_endpoint",
        "session_cookie_signing",
        "secure_session_cookie",
    }
    rendered = str(body).lower()
    assert "client_secret" not in rendered
    assert "refresh_token" not in rendered
    assert "id_token" not in rendered


def test_oidc_readiness_requires_openid_scope_for_id_token_issuance() -> None:
    client = TestClient(
        create_app(
            Settings(
                postgres_dsn="sqlite+pysqlite://",
                oidc_auth_required=True,
                oidc_issuer="https://idp.example/realms/axis",
                oidc_audience="limes-axis-api",
                oidc_jwks_url="https://idp.example/realms/axis/protocol/openid-connect/certs",
                oidc_algorithms=["RS256"],
                oidc_client_id="axis-console",
                oidc_authorization_url=(
                    "https://idp.example/realms/axis/protocol/openid-connect/auth"
                ),
                oidc_token_url="https://idp.example/realms/axis/protocol/openid-connect/token",
                oidc_end_session_url=(
                    "https://idp.example/realms/axis/protocol/openid-connect/logout"
                ),
                oidc_post_logout_redirect_uri="https://console.axis.example/signed-out",
                oidc_session_cookie_signing_secret="axis-cookie-signing-secret",
                oidc_session_cookie_secure=True,
                oidc_scopes=["profile", "email"],
            )
        )
    )

    response = client.get("/identity/oidc/readiness")

    assert response.status_code == 200
    body = response.json()
    checks = {check["check_id"]: check for check in body["checks"]}
    assert body["enterprise_sso_ready"] is False
    assert body["status"] == "action_required"
    assert checks["openid_scope"]["status"] == "action_required"
    assert "openid" in checks["openid_scope"]["detail"]


def test_oidc_readiness_marks_default_local_profile_as_not_enterprise_ready() -> None:
    client = TestClient(create_app(Settings(postgres_dsn="sqlite+pysqlite://")))

    response = client.get("/identity/oidc/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "action_required"
    assert body["enterprise_sso_ready"] is False
    assert body["auth_required"] is False
    assert body["jwks_source"] == "derived_from_issuer"
    checks = {check["check_id"]: check for check in body["checks"]}
    assert checks["auth_required"]["status"] == "action_required"
    assert checks["https_issuer"]["status"] == "action_required"
    assert checks["explicit_jwks_url"]["status"] == "action_required"
    assert checks["authorization_code_client"]["status"] == "action_required"
    assert checks["end_session_endpoint"]["status"] == "action_required"
    assert checks["post_logout_redirect"]["status"] == "action_required"
    assert checks["session_cookie_signing"]["status"] == "action_required"
    assert checks["secure_session_cookie"]["status"] == "action_required"


def test_identity_session_reports_public_evaluation_without_local_claims() -> None:
    client = TestClient(create_app(Settings(postgres_dsn="sqlite+pysqlite://")))

    response = client.get("/identity/session")

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert body["mode"] == "public_evaluation"
    assert body["actor_id"] is None
    assert body["tenant_id"] is None
    assert body["scopes"] == []
    assert body["session_boundary"] == "no_authenticated_api_actor"
    assert body["api_auth_required"] is False
    assert body["enterprise_sso_ready"] is False
    assert "No authenticated API actor is attached." in body["limitations"]
    rendered = str(body).lower()
    assert "access_token" not in rendered
    assert "refresh_token" not in rendered
    assert "id_token" not in rendered
    assert "secret" not in str(body).lower()
    assert "password" not in str(body).lower()


def test_identity_session_returns_validated_oidc_context_without_token_material() -> None:
    secret = "axis-test-secret"
    settings = Settings(
        postgres_dsn="sqlite+pysqlite://",
        oidc_auth_required=True,
        oidc_issuer="https://issuer.example/realms/axis",
        oidc_audience="limes-axis-api",
        oidc_jwks_url="https://issuer.example/realms/axis/protocol/openid-connect/certs",
        oidc_algorithms=["HS256"],
    )
    app = create_app(settings)
    app.state.tenant_state_cache = _ActiveTenantStateCache()
    app.state.identity_verifier = StaticJwksOidcVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        algorithms=settings.oidc_algorithms,
        jwks=_oct_jwks(secret),
        tenant_claim=settings.oidc_tenant_claim,
    )
    token = _token(
        secret,
        {
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_audience,
            "sub": "plant-operations-owner-role",
            "axis_tenant": "tenant_demo_manufacturing",
            "scope": "approvals:supply:decide audit:read",
            "exp": 4102444800,
        },
    )
    client = TestClient(app)

    response = client.get("/identity/session", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["mode"] == "validated_oidc_bearer"
    assert body["actor_id"] == "plant-operations-owner-role"
    assert body["tenant_id"] == "tenant_demo_manufacturing"
    assert body["scopes"] == ["approvals:supply:decide", "audit:read"]
    assert body["expires_at"] == 4102444800
    assert body["api_auth_required"] is True
    assert body["session_boundary"] == "bearer_token_verified_by_axis_api"
    assert "Bearer token validated by the Axis OIDC verifier." in body["capabilities"]
    assert token not in str(body)
    assert "secret" not in str(body).lower()
    assert "password" not in str(body).lower()


def test_tenant_admission_gates_the_session_report_for_verified_principals() -> None:
    """Admission enforcement must cover every authenticated path.

    The session report is readable without credentials, but a principal that
    DOES verify — bearer or cookie, freshly resolved or cached — is still
    subject to tenant admission. A suspended tenant gets the same 403 on
    ``/identity/session`` as on protected routes, and no actor data leaks.
    """
    secret = "axis-test-secret"
    settings = Settings(
        postgres_dsn="sqlite+pysqlite://",
        oidc_auth_required=True,
        oidc_issuer="https://issuer.example/realms/axis",
        oidc_audience="limes-axis-api",
        oidc_jwks_url="https://issuer.example/realms/axis/protocol/openid-connect/certs",
        oidc_algorithms=["HS256"],
    )
    app = create_app(settings)
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app.state.session_factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    app.state.tenant_state_cache = _SuspendedTenantStateCache()
    app.state.identity_verifier = StaticJwksOidcVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        algorithms=settings.oidc_algorithms,
        jwks=_oct_jwks(secret),
        tenant_claim=settings.oidc_tenant_claim,
    )
    token = _token(
        secret,
        {
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_audience,
            "sub": "plant-operations-owner-role",
            "axis_tenant": "tenant_demo_manufacturing",
            "scope": "audit:read",
            "exp": 4102444800,
        },
    )
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    session_response = client.get("/identity/session", headers=headers)
    assert session_response.status_code == 403
    detail = session_response.json()["detail"]
    assert detail["code"] == "PERMISSION_DENIED"
    assert detail["tenant_status"] == "suspended"
    assert "plant-operations-owner-role" not in str(session_response.json())

    protected_response = client.get(
        "/operations/approvals?tenant_id=tenant_demo_manufacturing",
        headers=headers,
    )
    assert protected_response.status_code == 403

    with sessionmaker(bind=engine)() as session:
        denial_events = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.event_type == "platform.tenant.suspended_request.denied"
                )
            )
        )
        assert len(denial_events) >= 1


def test_identity_session_requires_token_when_oidc_auth_is_required() -> None:
    client = TestClient(
        create_app(
            Settings(
                postgres_dsn="sqlite+pysqlite://",
                oidc_auth_required=True,
            )
        )
    )

    response = client.get("/identity/session")

    # The session report stays readable without credentials so the console can
    # render its sign-in gate; the anonymous state is classified, not a 401.
    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert body["api_auth_required"] is True
    assert body["unauthenticated_reason"] == "missing_authorization"


def test_ready_includes_oidc_readiness_summary() -> None:
    client = TestClient(
        create_app(
            Settings(
                postgres_dsn="sqlite+pysqlite://",
                oidc_auth_required=True,
                oidc_issuer="https://idp.example/realms/axis",
                oidc_jwks_url="https://idp.example/realms/axis/protocol/openid-connect/certs",
                oidc_client_id="axis-console",
                oidc_authorization_url=(
                    "https://idp.example/realms/axis/protocol/openid-connect/auth"
                ),
                oidc_token_url="https://idp.example/realms/axis/protocol/openid-connect/token",
                oidc_end_session_url=(
                    "https://idp.example/realms/axis/protocol/openid-connect/logout"
                ),
                oidc_post_logout_redirect_uri="https://console.axis.example/signed-out",
                oidc_session_cookie_signing_secret="axis-cookie-signing-secret",
                oidc_session_cookie_secure=True,
                oidc_refresh_token_encryption_key="axis-refresh-credential-encryption-key-01",
                workflow_signals_enabled=False,
            )
        )
    )

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["identity"] == {
        "oidc_auth_required": True,
        "enterprise_sso_ready": True,
        "readiness_status": "ready",
    }
