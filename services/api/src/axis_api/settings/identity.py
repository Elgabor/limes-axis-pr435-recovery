"""Identity configuration field definitions (no environment loading)."""

from pydantic import BaseModel, Field

from axis_api.tenant_admission import TENANT_ADMISSION_CLAIMS_ONLY


class IdentitySettings(BaseModel):
    tenant_state_cache_ttl_seconds: float = Field(
        default=5.0,
        ge=0,
        alias="AXIS_TENANT_STATE_CACHE_TTL_SECONDS",
    )
    tenant_admission_mode: str = Field(
        default=TENANT_ADMISSION_CLAIMS_ONLY,
        pattern="^(claims_only|registered_only)$",
        alias="AXIS_TENANT_ADMISSION_MODE",
    )
    oidc_issuer: str = Field(
        default="http://localhost:8080/realms/axis",
        alias="AXIS_OIDC_ISSUER",
    )
    oidc_audience: str = Field(default="limes-axis-api", alias="AXIS_OIDC_AUDIENCE")
    oidc_jwks_url: str | None = Field(default=None, alias="AXIS_OIDC_JWKS_URL")
    oidc_algorithms: list[str] = Field(
        default_factory=lambda: ["RS256"],
        alias="AXIS_OIDC_ALGORITHMS",
    )
    oidc_actor_claim: str = Field(default="sub", alias="AXIS_OIDC_ACTOR_CLAIM")
    oidc_tenant_claim: str = Field(default="axis_tenant", alias="AXIS_OIDC_TENANT_CLAIM")
    oidc_jwks_cache_seconds: int = Field(default=300, alias="AXIS_OIDC_JWKS_CACHE_SECONDS")
    oidc_auth_required: bool = Field(default=False, alias="AXIS_OIDC_AUTH_REQUIRED")
    oidc_client_id: str | None = Field(default=None, alias="AXIS_OIDC_CLIENT_ID")
    oidc_client_secret: str | None = Field(default=None, alias="AXIS_OIDC_CLIENT_SECRET")
    oidc_authorization_url: str | None = Field(default=None, alias="AXIS_OIDC_AUTHORIZATION_URL")
    oidc_token_url: str | None = Field(default=None, alias="AXIS_OIDC_TOKEN_URL")
    oidc_redirect_uri: str | None = Field(default=None, alias="AXIS_OIDC_REDIRECT_URI")
    oidc_end_session_url: str | None = Field(
        default=None,
        alias="AXIS_OIDC_END_SESSION_URL",
    )
    oidc_post_logout_redirect_uri: str | None = Field(
        default=None,
        alias="AXIS_OIDC_POST_LOGOUT_REDIRECT_URI",
    )
    oidc_scopes: list[str] = Field(
        default_factory=lambda: ["openid", "profile", "email"],
        alias="AXIS_OIDC_SCOPES",
    )
    oidc_login_cookie_name: str = Field(
        default="axis_oidc_login",
        alias="AXIS_OIDC_LOGIN_COOKIE_NAME",
    )
    oidc_session_cookie_name: str = Field(
        default="axis_session",
        alias="AXIS_OIDC_SESSION_COOKIE_NAME",
    )
    oidc_session_cookie_signing_secret: str | None = Field(
        default=None,
        alias="AXIS_OIDC_SESSION_COOKIE_SIGNING_SECRET",
    )
    oidc_login_state_ttl_seconds: int = Field(
        default=600,
        alias="AXIS_OIDC_LOGIN_STATE_TTL_SECONDS",
    )
    oidc_session_cookie_ttl_seconds: int = Field(
        default=3600,
        alias="AXIS_OIDC_SESSION_COOKIE_TTL_SECONDS",
    )
    oidc_session_cookie_secure: bool = Field(
        default=False,
        alias="AXIS_OIDC_SESSION_COOKIE_SECURE",
    )
    oidc_session_cookie_host_prefix: bool = Field(
        default=True,
        alias="AXIS_OIDC_SESSION_COOKIE_HOST_PREFIX",
    )
    oidc_csrf_cookie_name: str = Field(
        default="axis_csrf",
        alias="AXIS_OIDC_CSRF_COOKIE_NAME",
    )
    oidc_session_idle_timeout_seconds: int = Field(
        default=1800,
        ge=0,
        alias="AXIS_OIDC_SESSION_IDLE_TIMEOUT_SECONDS",
    )
    oidc_session_absolute_timeout_seconds: int = Field(
        default=28800,
        ge=0,
        alias="AXIS_OIDC_SESSION_ABSOLUTE_TIMEOUT_SECONDS",
    )
    oidc_session_max_concurrent: int = Field(
        default=5,
        ge=0,
        alias="AXIS_OIDC_SESSION_MAX_CONCURRENT",
    )
    oidc_refresh_token_encryption_key: str | None = Field(
        default=None,
        alias="AXIS_OIDC_REFRESH_TOKEN_ENCRYPTION_KEY",
    )
    oidc_refresh_claim_staleness_seconds: int = Field(
        default=120,
        ge=1,
        alias="AXIS_OIDC_REFRESH_CLAIM_STALENESS_SECONDS",
    )
    identity_session_trusted_proxy_enabled: bool = Field(
        default=False,
        alias="AXIS_IDENTITY_SESSION_TRUSTED_PROXY_ENABLED",
    )
