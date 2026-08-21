from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field

from axis_api.config import Settings
from axis_api.object_storage import ObjectLockCapability, build_object_store_readiness
from axis_api.oidc_code_flow import post_logout_redirect_uri, redirect_uri
from axis_api.telemetry import observability_posture
from axis_api.tenant_admission import TENANT_ADMISSION_REGISTERED_ONLY

OIDC_SESSION_COOKIE_MAX_TTL_SECONDS = 12 * 60 * 60
SUPPORTED_DEPLOYMENT_TENANCY_MODES = {
    "saas_multi_tenant",
    "single_tenant_managed",
    "private_cloud",
    "on_prem",
}


class DeploymentReadinessCheck(BaseModel):
    check_id: str = Field(min_length=1)
    status: str = Field(pattern="^(ready|action_required)$")
    production_required: bool
    detail: str = Field(min_length=1)


class DeploymentReadinessCapabilities(BaseModel):
    tenant_admission_mode: str = Field(min_length=1)
    oidc_session_cookie_secure: bool
    oidc_session_cookie_signing_secret_configured: bool
    oidc_session_cookie_ttl_seconds: int = Field(ge=0)
    api_base_url_https: bool
    public_base_url_https: bool
    oidc_redirect_uri_https: bool
    oidc_post_logout_redirect_uri_https: bool
    api_rate_limit_enabled: bool
    api_rate_limit_requests: int = Field(ge=1)
    api_rate_limit_window_seconds: int = Field(ge=1)
    network_policy_enabled: bool
    network_egress_mode: str = Field(min_length=1)
    network_egress_allowlist_configured: bool
    deployment_tenancy_mode: str = Field(min_length=1)
    deployment_customer_isolation_configured: bool
    deployment_data_residency_configured: bool
    deployment_operator_access_runbook_configured: bool
    deployment_break_glass_approval_configured: bool
    external_model_egress_enabled: bool
    ontology_mutations_enabled: bool
    ontology_queries_enabled: bool
    ontology_typedb_address_configured: bool
    connector_sync_execution_enabled: bool
    external_db_sync_execution_enabled: bool
    external_db_live_query_preflight_enabled: bool
    external_db_live_query_execution_enabled: bool
    external_db_live_query_profile_configured: bool
    credential_lease_execution_enabled: bool
    credential_lease_provider_adapters_enabled: bool
    audit_ledger_signing_configured: bool
    object_store_adapter: str = Field(min_length=1)
    object_store_bucket_configured: bool
    object_store_endpoint_configured: bool
    object_store_credentials_configured: bool
    object_store_secure_transport: bool
    object_store_worm_retention_enabled: bool
    object_store_retention_mode: str = Field(min_length=1)
    object_store_retention_days: int = Field(ge=0)
    object_store_legal_hold_enabled: bool
    object_store_object_lock_bucket_verified: bool
    object_store_compliance_enforceable: bool
    dr_runbook_configured: bool
    dr_rpo_rto_defined: bool
    dr_rehearsal_evidence_configured: bool
    dr_restore_owner_configured: bool
    dr_customer_approval_configured: bool
    otel_enabled: bool
    otel_metrics_enabled: bool
    otel_exporter_endpoint_configured: bool


class DeploymentReadinessReport(BaseModel):
    status: str = Field(pattern="^(ready|action_required)$")
    environment: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    production_ready: bool
    demo_safe: bool
    capabilities: DeploymentReadinessCapabilities
    production_blockers: list[str]
    checks: list[DeploymentReadinessCheck]
    notes: list[str] = Field(default_factory=list)


def _deployment_profile(environment: str) -> str:
    normalized = environment.strip().casefold()
    if normalized in {"development", "dev", "local", "test"}:
        return "local_demo"
    if normalized in {"production", "prod"}:
        return "production"
    return normalized or "unspecified"


def _check(
    check_id: str,
    ok: bool,
    ready_detail: str,
    action_detail: str,
    *,
    production_required: bool = True,
) -> DeploymentReadinessCheck:
    return DeploymentReadinessCheck(
        check_id=check_id,
        status="ready" if ok else "action_required",
        production_required=production_required,
        detail=ready_detail if ok else action_detail,
    )


def _public_object_store_missing_requirements(requirements: list[str]) -> str:
    public_terms: list[str] = []
    credentials_missing = False
    for requirement in requirements:
        if requirement in {"access key", "secret key"}:
            credentials_missing = True
            continue
        public_terms.append(requirement)
    if credentials_missing:
        public_terms.append("credentials")
    return ", ".join(public_terms)


def _uses_https(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme.casefold() == "https" and bool(parsed.netloc)


def _network_egress_mode(settings: Settings) -> str:
    return settings.deployment_network_egress_mode.strip().casefold() or "not_configured"


def _deployment_tenancy_mode(settings: Settings) -> str:
    normalized = (
        settings.deployment_tenancy_mode.strip().casefold().replace("-", "_").replace(" ", "_")
    )
    return normalized or "not_configured"


def build_deployment_readiness_report(
    settings: Settings,
    *,
    oidc_readiness_report: dict[str, object],
    object_lock_capability: ObjectLockCapability | None = None,
) -> DeploymentReadinessReport:
    profile = _deployment_profile(settings.environment)
    live_connector_execution_enabled = any(
        (
            settings.connector_sync_execution_enabled,
            settings.external_db_sync_execution_enabled,
            settings.external_db_live_query_preflight_enabled,
            settings.external_db_live_query_execution_enabled,
            settings.credential_lease_execution_enabled,
            settings.credential_lease_provider_adapters_enabled,
        )
    )
    api_rate_limiting_ready = (
        settings.api_rate_limit_enabled
        and settings.api_rate_limit_requests > 0
        and settings.api_rate_limit_window_seconds > 0
        and bool(settings.api_rate_limit_paths)
    )
    network_egress_mode = _network_egress_mode(settings)
    network_egress_restricted_ready = settings.deployment_network_policy_enabled and (
        network_egress_mode == "offline"
        or (
            network_egress_mode == "restricted"
            and settings.deployment_network_egress_allowlist_configured
        )
    )
    audit_signing_configured = bool(settings.audit_ledger_signing_secret)
    deployment_tenancy_mode = _deployment_tenancy_mode(settings)
    deployment_tenancy_profile_ready = (
        deployment_tenancy_mode in SUPPORTED_DEPLOYMENT_TENANCY_MODES
        and settings.deployment_customer_isolation_configured
        and settings.deployment_data_residency_configured
        and settings.deployment_operator_access_runbook_configured
        and settings.deployment_break_glass_approval_configured
    )
    object_store_readiness = build_object_store_readiness(
        settings,
        object_lock_capability=object_lock_capability,
    )
    public_object_store_missing_requirements = _public_object_store_missing_requirements(
        object_store_readiness.missing_requirements
    )
    production_dr_procedures_ready = all(
        (
            settings.dr_runbook_configured,
            settings.dr_rpo_rto_defined,
            settings.dr_rehearsal_evidence_configured,
            settings.dr_restore_owner_configured,
            settings.dr_customer_approval_configured,
        )
    )
    observability = observability_posture(settings)
    observability_ready = bool(observability["otel_enabled"]) and bool(
        observability["otel_exporter_endpoint_configured"]
    )
    # Ontology graph mutation posture. Disabled-by-default is a ready posture
    # (promotions defer, nothing is written). If mutations are enabled the live
    # path must be coherent: a reachable TypeDB address and ontology reads
    # enabled so promoted nodes can be read back and served under the ontology
    # read authorization.
    ontology_graph_mutation_posture_ready = (not settings.ontology_mutations_enabled) or (
        bool(settings.typedb_address) and settings.ontology_queries_enabled
    )
    resolved_redirect_uri = redirect_uri(settings)
    resolved_post_logout_redirect_uri = post_logout_redirect_uri(settings, "/")
    oidc_session_cookie_ttl_seconds = max(0, settings.oidc_session_cookie_ttl_seconds)
    oidc_secure_cookie_session_ready = (
        settings.oidc_session_cookie_secure
        and bool(settings.oidc_session_cookie_signing_secret)
        and 0 < settings.oidc_session_cookie_ttl_seconds <= OIDC_SESSION_COOKIE_MAX_TTL_SECONDS
        and _uses_https(settings.api_base_url)
        and _uses_https(settings.public_base_url)
        and _uses_https(resolved_redirect_uri)
        and _uses_https(resolved_post_logout_redirect_uri)
    )

    capabilities = DeploymentReadinessCapabilities(
        tenant_admission_mode=settings.tenant_admission_mode,
        oidc_session_cookie_secure=settings.oidc_session_cookie_secure,
        oidc_session_cookie_signing_secret_configured=bool(
            settings.oidc_session_cookie_signing_secret
        ),
        oidc_session_cookie_ttl_seconds=oidc_session_cookie_ttl_seconds,
        api_base_url_https=_uses_https(settings.api_base_url),
        public_base_url_https=_uses_https(settings.public_base_url),
        oidc_redirect_uri_https=_uses_https(resolved_redirect_uri),
        oidc_post_logout_redirect_uri_https=_uses_https(
            resolved_post_logout_redirect_uri
        ),
        api_rate_limit_enabled=settings.api_rate_limit_enabled,
        api_rate_limit_requests=max(1, settings.api_rate_limit_requests),
        api_rate_limit_window_seconds=max(1, settings.api_rate_limit_window_seconds),
        network_policy_enabled=settings.deployment_network_policy_enabled,
        network_egress_mode=network_egress_mode,
        network_egress_allowlist_configured=(
            settings.deployment_network_egress_allowlist_configured
        ),
        deployment_tenancy_mode=deployment_tenancy_mode,
        deployment_customer_isolation_configured=(
            settings.deployment_customer_isolation_configured
        ),
        deployment_data_residency_configured=settings.deployment_data_residency_configured,
        deployment_operator_access_runbook_configured=(
            settings.deployment_operator_access_runbook_configured
        ),
        deployment_break_glass_approval_configured=(
            settings.deployment_break_glass_approval_configured
        ),
        external_model_egress_enabled=settings.external_model_egress_enabled,
        ontology_mutations_enabled=settings.ontology_mutations_enabled,
        ontology_queries_enabled=settings.ontology_queries_enabled,
        ontology_typedb_address_configured=bool(settings.typedb_address),
        connector_sync_execution_enabled=settings.connector_sync_execution_enabled,
        external_db_sync_execution_enabled=settings.external_db_sync_execution_enabled,
        external_db_live_query_preflight_enabled=settings.external_db_live_query_preflight_enabled,
        external_db_live_query_execution_enabled=(
            settings.external_db_live_query_execution_enabled
        ),
        external_db_live_query_profile_configured=bool(
            settings.external_db_live_query_dsn
        ),
        credential_lease_execution_enabled=settings.credential_lease_execution_enabled,
        credential_lease_provider_adapters_enabled=settings.credential_lease_provider_adapters_enabled,
        audit_ledger_signing_configured=audit_signing_configured,
        object_store_adapter=object_store_readiness.adapter,
        object_store_bucket_configured=object_store_readiness.bucket_configured,
        object_store_endpoint_configured=object_store_readiness.endpoint_configured,
        object_store_credentials_configured=object_store_readiness.credentials_configured,
        object_store_secure_transport=object_store_readiness.secure_transport,
        object_store_worm_retention_enabled=object_store_readiness.worm_retention_enabled,
        object_store_retention_mode=object_store_readiness.retention_mode,
        object_store_retention_days=object_store_readiness.retention_days,
        object_store_legal_hold_enabled=object_store_readiness.legal_hold_enabled,
        object_store_object_lock_bucket_verified=(
            object_store_readiness.object_lock_bucket_verified
        ),
        object_store_compliance_enforceable=object_store_readiness.compliance_enforceable,
        dr_runbook_configured=settings.dr_runbook_configured,
        dr_rpo_rto_defined=settings.dr_rpo_rto_defined,
        dr_rehearsal_evidence_configured=settings.dr_rehearsal_evidence_configured,
        dr_restore_owner_configured=settings.dr_restore_owner_configured,
        dr_customer_approval_configured=settings.dr_customer_approval_configured,
        otel_enabled=bool(observability["otel_enabled"]),
        otel_metrics_enabled=bool(observability["otel_metrics_enabled"]),
        otel_exporter_endpoint_configured=bool(
            observability["otel_exporter_endpoint_configured"]
        ),
    )

    checks = [
        _check(
            "oidc_enterprise_sso",
            bool(oidc_readiness_report.get("enterprise_sso_ready")),
            "OIDC is configured for enterprise SSO evaluation.",
            (
                "OIDC is not enterprise-ready; require auth, HTTPS issuer, "
                "explicit JWKS and asymmetric algorithms."
            ),
        ),
        _check(
            "oidc_secure_cookie_session",
            oidc_secure_cookie_session_ready,
            "OIDC browser sessions use Secure cookies, signed state, bounded TTL and HTTPS URLs.",
            (
                "OIDC browser sessions are not production-ready; require Secure cookies, "
                "an operator-provided signing secret, a bounded TTL and HTTPS "
                "API/public/redirect URLs."
            ),
        ),
        _check(
            "registered_tenant_admission",
            settings.tenant_admission_mode == TENANT_ADMISSION_REGISTERED_ONLY,
            (
                "Authenticated principals are admitted only when their tenant is "
                "registered and active."
            ),
            (
                "Tenant admission trusts identity-provider claims without requiring a "
                "registered tenant; use AXIS_TENANT_ADMISSION_MODE=registered_only "
                "before production."
            ),
        ),
        _check(
            "external_model_egress_disabled",
            not settings.external_model_egress_enabled,
            "External model egress is disabled by default.",
            (
                "External model egress is enabled; require tenant policy, "
                "audit and data-classification controls."
            ),
        ),
        _check(
            "api_rate_limiting",
            api_rate_limiting_ready,
            "API rate limiting is enabled for public and sensitive routes.",
            "API rate limiting is not enabled; configure request throttling before production.",
        ),
        _check(
            "network_egress_restricted",
            network_egress_restricted_ready,
            "Network egress is restricted by NetworkPolicy in restricted or offline mode.",
            (
                "Network egress is not production-restricted; enable NetworkPolicy "
                "and use offline mode or restricted mode with an explicit destination allowlist."
            ),
        ),
        _check(
            "deployment_tenancy_profile",
            deployment_tenancy_profile_ready,
            (
                "Deployment tenancy profile declares supported mode, customer isolation, "
                "data residency, operator access and break-glass approval evidence."
            ),
            (
                "Deployment tenancy profile is incomplete; require a supported mode "
                "(saas_multi_tenant, single_tenant_managed, private_cloud or on_prem), "
                "customer isolation evidence, data-residency evidence, an operator "
                "access runbook and break-glass approval controls."
            ),
        ),
        _check(
            "live_connector_execution_disabled",
            not live_connector_execution_enabled,
            "Live connector execution flags are disabled by default.",
            (
                "One or more live connector execution flags are enabled; require "
                "provider policy bundles and support runbooks."
            ),
        ),
        _check(
            "ontology_graph_mutation_posture",
            ontology_graph_mutation_posture_ready,
            (
                "Connector ontology graph promotion is either deferred (disabled) "
                "or enabled with a configured TypeDB address and ontology reads "
                "enabled for verifiable read-back."
            ),
            (
                "Ontology graph mutations are enabled without a coherent live path; "
                "configure AXIS_TYPEDB_ADDRESS and enable AXIS_ONTOLOGY_QUERIES_ENABLED "
                "so promoted nodes are written and read back."
            ),
            production_required=False,
        ),
        _check(
            "audit_ledger_signing_configured",
            audit_signing_configured,
            "Audit ledger signing is configured.",
            "Audit ledger signing is not configured; evidence exports remain unsigned.",
        ),
        _check(
            "production_object_store_adapter",
            object_store_readiness.production_ready,
            (
                "S3-compatible object storage is configured with endpoint, bucket, "
                "credentials, secure transport and WORM retention."
            ),
            (
                "S3/MinIO WORM retention is not production-ready; missing "
                f"{public_object_store_missing_requirements}."
            ),
        ),
        _check(
            "observability_instrumentation",
            observability_ready,
            (
                "OpenTelemetry instrumentation is enabled and an OTLP exporter "
                "endpoint is configured."
            ),
            (
                "OpenTelemetry instrumentation is disabled (default); enable "
                "AXIS_OTEL_ENABLED and point AXIS_OTEL_EXPORTER_OTLP_ENDPOINT at a "
                "collector to emit distributed traces and metrics."
            ),
            production_required=False,
        ),
        _check(
            "production_dr_procedures",
            production_dr_procedures_ready,
            (
                "Production backup, restore and disaster-recovery procedures are "
                "configured with RPO/RTO, rehearsal evidence, restore ownership "
                "and customer approval."
            ),
            (
                "Production disaster recovery procedures are incomplete; require "
                "approved runbook, RPO/RTO, rehearsal evidence, restore owner and "
                "customer approval before production."
            ),
        ),
    ]
    production_blockers = [
        check.check_id
        for check in checks
        if check.production_required and check.status != "ready"
    ]
    production_ready = not production_blockers
    demo_safe = (
        profile == "local_demo"
        and not settings.external_model_egress_enabled
        and not live_connector_execution_enabled
    )
    return DeploymentReadinessReport(
        status="ready" if production_ready else "action_required",
        environment=settings.environment,
        profile=profile,
        production_ready=production_ready,
        demo_safe=demo_safe,
        capabilities=capabilities,
        production_blockers=production_blockers,
        checks=checks,
        notes=[
            "This report is a deployment posture gate, not a production certification.",
            (
                "Production readiness remains blocked until the listed "
                "production blockers are resolved."
            ),
        ],
    )
