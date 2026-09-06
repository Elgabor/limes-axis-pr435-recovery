"""Policy configuration field definitions (no environment loading)."""

from pydantic import BaseModel, Field


class PolicySettings(BaseModel):
    api_rate_limit_enabled: bool = Field(
        default=False,
        alias="AXIS_API_RATE_LIMIT_ENABLED",
    )
    api_rate_limit_requests: int = Field(
        default=120,
        alias="AXIS_API_RATE_LIMIT_REQUESTS",
    )
    api_rate_limit_window_seconds: int = Field(
        default=60,
        alias="AXIS_API_RATE_LIMIT_WINDOW_SECONDS",
    )
    api_rate_limit_paths: list[str] = Field(
        default_factory=lambda: [
            "/identity/oidc/authorize",
            "/identity/oidc/callback",
            "/identity/oidc/logout",
            "/identity/session/logout",
            "/identity/session/refresh",
            "/deployment/readiness",
            "/support/diagnostics",
        ],
        alias="AXIS_API_RATE_LIMIT_PATHS",
    )
    api_rate_limit_backend: str = Field(
        default="memory",
        pattern="^(memory|redis)$",
        alias="AXIS_API_RATE_LIMIT_BACKEND",
    )
    api_rate_limit_failure_mode: str = Field(
        default="open",
        pattern="^(open|closed)$",
        alias="AXIS_API_RATE_LIMIT_FAILURE_MODE",
    )
    deployment_network_policy_enabled: bool = Field(
        default=False,
        alias="AXIS_DEPLOYMENT_NETWORK_POLICY_ENABLED",
    )
    deployment_network_egress_mode: str = Field(
        default="not_configured",
        alias="AXIS_DEPLOYMENT_NETWORK_EGRESS_MODE",
    )
    deployment_network_egress_allowlist_configured: bool = Field(
        default=False,
        alias="AXIS_DEPLOYMENT_NETWORK_EGRESS_ALLOWLIST_CONFIGURED",
    )
    deployment_tenancy_mode: str = Field(
        default="saas_multi_tenant",
        alias="AXIS_DEPLOYMENT_TENANCY_MODE",
    )
    deployment_customer_isolation_configured: bool = Field(
        default=False,
        alias="AXIS_DEPLOYMENT_CUSTOMER_ISOLATION_CONFIGURED",
    )
    deployment_data_residency_configured: bool = Field(
        default=False,
        alias="AXIS_DEPLOYMENT_DATA_RESIDENCY_CONFIGURED",
    )
    deployment_operator_access_runbook_configured: bool = Field(
        default=False,
        alias="AXIS_DEPLOYMENT_OPERATOR_ACCESS_RUNBOOK_CONFIGURED",
    )
    deployment_break_glass_approval_configured: bool = Field(
        default=False,
        alias="AXIS_DEPLOYMENT_BREAK_GLASS_APPROVAL_CONFIGURED",
    )
    replay_arbitrary_policy_set_diff_enabled: bool = Field(
        default=False,
        alias="AXIS_REPLAY_ARBITRARY_POLICY_SET_DIFF_ENABLED",
    )
