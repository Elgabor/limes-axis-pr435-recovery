from fastapi import FastAPI
from fastapi.testclient import TestClient

from axis_api.config import Settings
from axis_api.main import create_app as create_axis_app
from axis_api.rate_limit import InMemoryRateLimiter


def create_app(settings: Settings) -> FastAPI:
    """Build a production-shaped app without requiring Redis in unit tests."""

    return create_axis_app(
        settings,
        rate_limit_backend=InMemoryRateLimiter(
            limit=settings.api_rate_limit_requests,
            window_seconds=settings.api_rate_limit_window_seconds,
        ),
    )


def _checks_by_id(body: dict) -> dict[str, dict]:
    return {check["check_id"]: check for check in body["checks"]}


def _enterprise_sso_settings(**overrides: object) -> Settings:
    values = {
        "environment": "production",
        "postgres_dsn": "sqlite+pysqlite://",
        "api_base_url": "https://api.axis.example",
        "public_base_url": "https://console.axis.example",
        "oidc_auth_required": True,
        "oidc_issuer": "https://idp.example/realms/axis",
        "oidc_jwks_url": "https://idp.example/realms/axis/protocol/openid-connect/certs",
        "oidc_algorithms": ["RS256"],
        "oidc_client_id": "axis-console",
        "oidc_redirect_uri": "https://api.axis.example/identity/oidc/callback",
        "oidc_authorization_url": (
            "https://idp.example/realms/axis/protocol/openid-connect/auth"
        ),
        "oidc_token_url": "https://idp.example/realms/axis/protocol/openid-connect/token",
        "oidc_end_session_url": (
            "https://idp.example/realms/axis/protocol/openid-connect/logout"
        ),
        "oidc_post_logout_redirect_uri": "https://console.axis.example/signed-out",
        "oidc_session_cookie_signing_secret": "axis-cookie-signing-key",
        "oidc_session_cookie_secure": True,
        "oidc_refresh_token_encryption_key": "axis-refresh-credential-encryption-key-01",
        "api_rate_limit_enabled": True,
        "api_rate_limit_paths": ["*"],
        "api_rate_limit_backend": "redis",
        "api_rate_limit_failure_mode": "closed",
        "redis_url": "redis://redis.example:6379/0",
        "api_rate_limit_requests": 120,
        "api_rate_limit_window_seconds": 60,
        "tenant_admission_mode": "registered_only",
        "deployment_tenancy_mode": "saas_multi_tenant",
        "deployment_customer_isolation_configured": True,
        "deployment_data_residency_configured": True,
        "deployment_operator_access_runbook_configured": True,
        "deployment_break_glass_approval_configured": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_deployment_readiness_marks_default_profile_demo_safe_not_production_ready() -> None:
    client = TestClient(create_app(Settings(postgres_dsn="sqlite+pysqlite://")))

    response = client.get("/deployment/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "action_required"
    assert body["environment"] == "development"
    assert body["profile"] == "local_demo"
    assert body["production_ready"] is False
    assert body["demo_safe"] is True
    assert body["capabilities"]["external_model_egress_enabled"] is False
    assert body["capabilities"]["external_db_live_query_execution_enabled"] is False
    assert body["capabilities"]["external_db_live_query_profile_configured"] is False
    assert body["capabilities"]["tenant_admission_mode"] == "claims_only"
    assert body["capabilities"]["api_rate_limit_enabled"] is False
    assert body["capabilities"]["object_store_adapter"] == "local_filesystem"
    assert body["capabilities"]["network_policy_enabled"] is False
    assert body["capabilities"]["network_egress_mode"] == "not_configured"
    assert body["capabilities"]["network_egress_allowlist_configured"] is False
    assert body["capabilities"]["deployment_tenancy_mode"] == "saas_multi_tenant"
    assert body["capabilities"]["deployment_customer_isolation_configured"] is False
    assert body["capabilities"]["deployment_data_residency_configured"] is False
    assert (
        body["capabilities"]["deployment_operator_access_runbook_configured"] is False
    )
    assert body["capabilities"]["deployment_break_glass_approval_configured"] is False

    checks = _checks_by_id(body)
    assert checks["oidc_enterprise_sso"]["status"] == "action_required"
    assert checks["oidc_secure_cookie_session"]["status"] == "action_required"
    assert checks["registered_tenant_admission"]["status"] == "action_required"
    assert checks["api_rate_limiting"]["status"] == "action_required"
    assert checks["external_model_egress_disabled"]["status"] == "ready"
    assert checks["live_connector_execution_disabled"]["status"] == "ready"
    assert checks["audit_ledger_signing_configured"]["status"] == "action_required"
    assert checks["production_object_store_adapter"]["status"] == "action_required"
    assert checks["production_dr_procedures"]["status"] == "action_required"
    assert checks["network_egress_restricted"]["status"] == "action_required"
    assert checks["deployment_tenancy_profile"]["status"] == "action_required"
    assert body["capabilities"]["dr_runbook_configured"] is False
    assert body["capabilities"]["dr_rpo_rto_defined"] is False
    assert body["capabilities"]["dr_rehearsal_evidence_configured"] is False
    assert body["capabilities"]["dr_restore_owner_configured"] is False
    assert body["capabilities"]["dr_customer_approval_configured"] is False
    assert body["production_blockers"] == [
        "oidc_enterprise_sso",
        "oidc_secure_cookie_session",
        "registered_tenant_admission",
        "api_rate_limiting",
        "network_egress_restricted",
        "deployment_tenancy_profile",
        "audit_ledger_signing_configured",
        "production_object_store_adapter",
        "production_dr_procedures",
    ]
    assert "secret key" not in str(body).lower()
    assert "access key" not in str(body).lower()


def test_deployment_readiness_flags_unsafe_production_egress_and_live_execution() -> None:
    client = TestClient(
        create_app(
            _enterprise_sso_settings(
                audit_ledger_signing_secret="super-secret-signing-key",
                external_model_egress_enabled=True,
                connector_sync_execution_enabled=True,
                external_db_live_query_execution_enabled=True,
                external_db_live_query_dsn="postgresql://readonly.local/axis_external",
            )
        )
    )

    response = client.get("/deployment/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["profile"] == "production"
    assert body["production_ready"] is False
    checks = _checks_by_id(body)
    assert checks["oidc_enterprise_sso"]["status"] == "ready"
    assert checks["oidc_secure_cookie_session"]["status"] == "ready"
    assert checks["api_rate_limiting"]["status"] == "ready"
    assert checks["audit_ledger_signing_configured"]["status"] == "ready"
    assert checks["external_model_egress_disabled"]["status"] == "action_required"
    assert checks["live_connector_execution_disabled"]["status"] == "action_required"
    assert body["capabilities"]["external_db_live_query_execution_enabled"] is True
    assert body["capabilities"]["external_db_live_query_profile_configured"] is True
    assert "external_model_egress_disabled" in body["production_blockers"]
    assert "live_connector_execution_disabled" in body["production_blockers"]
    assert "super-secret-signing-key" not in str(body)
    assert "readonly.local" not in str(body)


def test_deployment_readiness_keeps_object_store_as_production_blocker() -> None:
    client = TestClient(
        create_app(
            _enterprise_sso_settings(
                audit_ledger_signing_secret="production-signing-key",
                external_model_egress_enabled=False,
                connector_sync_execution_enabled=False,
                external_db_sync_execution_enabled=False,
                external_db_live_query_preflight_enabled=False,
                credential_lease_execution_enabled=False,
                credential_lease_provider_adapters_enabled=False,
                dr_runbook_configured=True,
                dr_rpo_rto_defined=True,
                dr_rehearsal_evidence_configured=True,
                dr_restore_owner_configured=True,
                dr_customer_approval_configured=True,
                deployment_network_policy_enabled=True,
                deployment_network_egress_mode="restricted",
                deployment_network_egress_allowlist_configured=True,
            )
        )
    )

    response = client.get("/deployment/readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "action_required"
    assert body["production_ready"] is False
    checks = _checks_by_id(body)
    assert checks["oidc_enterprise_sso"]["status"] == "ready"
    assert checks["oidc_secure_cookie_session"]["status"] == "ready"
    assert checks["api_rate_limiting"]["status"] == "ready"
    assert checks["external_model_egress_disabled"]["status"] == "ready"
    assert checks["live_connector_execution_disabled"]["status"] == "ready"
    assert checks["audit_ledger_signing_configured"]["status"] == "ready"
    assert checks["production_object_store_adapter"]["status"] == "action_required"
    assert body["production_blockers"] == ["production_object_store_adapter"]
    assert "production-signing-key" not in str(body)


def test_deployment_readiness_accepts_s3_compatible_worm_object_store_profile() -> None:
    client = TestClient(
        create_app(
            _enterprise_sso_settings(
                audit_ledger_signing_secret="production-signing-key",
                external_model_egress_enabled=False,
                connector_sync_execution_enabled=False,
                external_db_sync_execution_enabled=False,
                external_db_live_query_preflight_enabled=False,
                credential_lease_execution_enabled=False,
                credential_lease_provider_adapters_enabled=False,
                connector_export_object_store_adapter="s3_compatible",
                connector_export_s3_endpoint="minio.internal:9000",
                connector_export_s3_bucket="axis-evidence",
                connector_export_s3_access_key="axis-service-account",
                connector_export_s3_secret_key="axis-secret-key",
                connector_export_s3_secure_transport=True,
                connector_export_s3_object_lock_enabled=True,
                connector_export_s3_retention_mode="GOVERNANCE",
                connector_export_s3_retention_days=90,
                connector_export_s3_legal_hold_enabled=False,
                dr_runbook_configured=True,
                dr_rpo_rto_defined=True,
                dr_rehearsal_evidence_configured=True,
                dr_restore_owner_configured=True,
                dr_customer_approval_configured=True,
                deployment_network_policy_enabled=True,
                deployment_network_egress_mode="restricted",
                deployment_network_egress_allowlist_configured=True,
            )
        )
    )

    response = client.get("/deployment/readiness")

    assert response.status_code == 200
    body = response.json()
    checks = _checks_by_id(body)
    assert checks["oidc_secure_cookie_session"]["status"] == "ready"
    assert checks["production_object_store_adapter"]["status"] == "ready"
    assert checks["api_rate_limiting"]["status"] == "ready"
    assert "production_object_store_adapter" not in body["production_blockers"]
    assert body["capabilities"]["oidc_session_cookie_secure"] is True
    assert body["capabilities"][
        "oidc_session_cookie_signing_secret_configured"
    ] is True
    assert body["capabilities"]["oidc_session_cookie_ttl_seconds"] == 3600
    assert body["capabilities"]["api_base_url_https"] is True
    assert body["capabilities"]["public_base_url_https"] is True
    assert body["capabilities"]["oidc_redirect_uri_https"] is True
    assert body["capabilities"]["oidc_post_logout_redirect_uri_https"] is True
    assert body["capabilities"]["api_rate_limit_enabled"] is True
    assert body["capabilities"]["api_rate_limit_requests"] == 120
    assert body["capabilities"]["api_rate_limit_window_seconds"] == 60
    assert body["capabilities"]["object_store_adapter"] == "s3_compatible"
    assert body["capabilities"]["object_store_bucket_configured"] is True
    assert body["capabilities"]["object_store_endpoint_configured"] is True
    assert body["capabilities"]["object_store_credentials_configured"] is True
    assert body["capabilities"]["object_store_worm_retention_enabled"] is True
    assert body["capabilities"]["object_store_retention_mode"] == "GOVERNANCE"
    assert body["capabilities"]["object_store_retention_days"] == 90
    assert body["capabilities"]["dr_runbook_configured"] is True
    assert body["capabilities"]["dr_rpo_rto_defined"] is True
    assert body["capabilities"]["dr_rehearsal_evidence_configured"] is True
    assert body["capabilities"]["dr_restore_owner_configured"] is True
    assert body["capabilities"]["dr_customer_approval_configured"] is True
    assert body["capabilities"]["network_policy_enabled"] is True
    assert body["capabilities"]["network_egress_mode"] == "restricted"
    assert body["capabilities"]["network_egress_allowlist_configured"] is True
    assert "axis-secret-key" not in str(body)
    assert "axis-service-account" not in str(body)


def test_deployment_readiness_blocks_port_allowlist_network_egress_mode() -> None:
    client = TestClient(
        create_app(
            _enterprise_sso_settings(
                audit_ledger_signing_secret="production-signing-key",
                external_model_egress_enabled=False,
                connector_sync_execution_enabled=False,
                external_db_sync_execution_enabled=False,
                external_db_live_query_preflight_enabled=False,
                credential_lease_execution_enabled=False,
                credential_lease_provider_adapters_enabled=False,
                connector_export_object_store_adapter="s3_compatible",
                connector_export_s3_endpoint="minio.internal:9000",
                connector_export_s3_bucket="axis-evidence",
                connector_export_s3_access_key="axis-service-account",
                connector_export_s3_secret_key="axis-secret-key",
                connector_export_s3_secure_transport=True,
                connector_export_s3_object_lock_enabled=True,
                connector_export_s3_retention_mode="GOVERNANCE",
                connector_export_s3_retention_days=90,
                dr_runbook_configured=True,
                dr_rpo_rto_defined=True,
                dr_rehearsal_evidence_configured=True,
                dr_restore_owner_configured=True,
                dr_customer_approval_configured=True,
                deployment_network_policy_enabled=True,
                deployment_network_egress_mode="port_allowlist",
                deployment_network_egress_allowlist_configured=False,
            )
        )
    )

    response = client.get("/deployment/readiness")

    assert response.status_code == 200
    body = response.json()
    checks = _checks_by_id(body)
    assert checks["network_egress_restricted"]["status"] == "action_required"
    assert body["production_blockers"] == ["network_egress_restricted"]
    assert body["capabilities"]["network_policy_enabled"] is True
    assert body["capabilities"]["network_egress_mode"] == "port_allowlist"
    assert body["capabilities"]["network_egress_allowlist_configured"] is False


def test_deployment_readiness_blocks_dr_without_operational_procedure_commitments() -> None:
    client = TestClient(
        create_app(
            _enterprise_sso_settings(
                audit_ledger_signing_secret="production-signing-key",
                external_model_egress_enabled=False,
                connector_sync_execution_enabled=False,
                external_db_sync_execution_enabled=False,
                external_db_live_query_preflight_enabled=False,
                credential_lease_execution_enabled=False,
                credential_lease_provider_adapters_enabled=False,
                connector_export_object_store_adapter="s3_compatible",
                connector_export_s3_endpoint="minio.internal:9000",
                connector_export_s3_bucket="axis-evidence",
                connector_export_s3_access_key="axis-service-account",
                connector_export_s3_secret_key="axis-secret-key",
                connector_export_s3_secure_transport=True,
                connector_export_s3_object_lock_enabled=True,
                connector_export_s3_retention_mode="GOVERNANCE",
                connector_export_s3_retention_days=90,
                dr_runbook_configured=True,
                dr_rpo_rto_defined=False,
                dr_rehearsal_evidence_configured=True,
                dr_restore_owner_configured=False,
                dr_customer_approval_configured=True,
                deployment_network_policy_enabled=True,
                deployment_network_egress_mode="restricted",
                deployment_network_egress_allowlist_configured=True,
            )
        )
    )

    response = client.get("/deployment/readiness")

    assert response.status_code == 200
    body = response.json()
    checks = _checks_by_id(body)
    assert checks["production_object_store_adapter"]["status"] == "ready"
    assert checks["production_dr_procedures"]["status"] == "action_required"
    assert body["production_blockers"] == ["production_dr_procedures"]
    assert body["capabilities"]["dr_runbook_configured"] is True
    assert body["capabilities"]["dr_rpo_rto_defined"] is False
    assert body["capabilities"]["dr_rehearsal_evidence_configured"] is True
    assert body["capabilities"]["dr_restore_owner_configured"] is False
    assert body["capabilities"]["dr_customer_approval_configured"] is True
    assert "production-signing-key" not in str(body)


def test_deployment_readiness_blocks_dedicated_profile_without_isolation_evidence() -> None:
    client = TestClient(
        create_app(
            _enterprise_sso_settings(
                audit_ledger_signing_secret="production-signing-key",
                external_model_egress_enabled=False,
                connector_sync_execution_enabled=False,
                external_db_sync_execution_enabled=False,
                external_db_live_query_preflight_enabled=False,
                credential_lease_execution_enabled=False,
                credential_lease_provider_adapters_enabled=False,
                connector_export_object_store_adapter="s3_compatible",
                connector_export_s3_endpoint="minio.internal:9000",
                connector_export_s3_bucket="axis-evidence",
                connector_export_s3_access_key="axis-service-account",
                connector_export_s3_secret_key="axis-secret-key",
                connector_export_s3_secure_transport=True,
                connector_export_s3_object_lock_enabled=True,
                connector_export_s3_retention_mode="GOVERNANCE",
                connector_export_s3_retention_days=90,
                dr_runbook_configured=True,
                dr_rpo_rto_defined=True,
                dr_rehearsal_evidence_configured=True,
                dr_restore_owner_configured=True,
                dr_customer_approval_configured=True,
                deployment_network_policy_enabled=True,
                deployment_network_egress_mode="restricted",
                deployment_network_egress_allowlist_configured=True,
                deployment_tenancy_mode="single_tenant_managed",
                deployment_customer_isolation_configured=True,
                deployment_data_residency_configured=True,
                deployment_operator_access_runbook_configured=False,
                deployment_break_glass_approval_configured=False,
            )
        )
    )

    response = client.get("/deployment/readiness")

    assert response.status_code == 200
    body = response.json()
    checks = _checks_by_id(body)
    assert body["production_ready"] is False
    assert body["capabilities"]["deployment_tenancy_mode"] == "single_tenant_managed"
    assert body["capabilities"]["deployment_customer_isolation_configured"] is True
    assert body["capabilities"]["deployment_data_residency_configured"] is True
    assert (
        body["capabilities"]["deployment_operator_access_runbook_configured"] is False
    )
    assert body["capabilities"]["deployment_break_glass_approval_configured"] is False
    assert checks["deployment_tenancy_profile"]["status"] == "action_required"
    assert body["production_blockers"] == ["deployment_tenancy_profile"]
    assert "production-signing-key" not in str(body)


def test_deployment_readiness_accepts_on_prem_profile_with_required_boundaries() -> None:
    client = TestClient(
        create_app(
            _enterprise_sso_settings(
                audit_ledger_signing_secret="production-signing-key",
                external_model_egress_enabled=False,
                connector_sync_execution_enabled=False,
                external_db_sync_execution_enabled=False,
                external_db_live_query_preflight_enabled=False,
                credential_lease_execution_enabled=False,
                credential_lease_provider_adapters_enabled=False,
                connector_export_object_store_adapter="s3_compatible",
                connector_export_s3_endpoint="minio.internal:9000",
                connector_export_s3_bucket="axis-evidence",
                connector_export_s3_access_key="axis-service-account",
                connector_export_s3_secret_key="axis-secret-key",
                connector_export_s3_secure_transport=True,
                connector_export_s3_object_lock_enabled=True,
                connector_export_s3_retention_mode="GOVERNANCE",
                connector_export_s3_retention_days=90,
                dr_runbook_configured=True,
                dr_rpo_rto_defined=True,
                dr_rehearsal_evidence_configured=True,
                dr_restore_owner_configured=True,
                dr_customer_approval_configured=True,
                deployment_network_policy_enabled=True,
                deployment_network_egress_mode="offline",
                deployment_network_egress_allowlist_configured=True,
                deployment_tenancy_mode="on_prem",
                deployment_customer_isolation_configured=True,
                deployment_data_residency_configured=True,
                deployment_operator_access_runbook_configured=True,
                deployment_break_glass_approval_configured=True,
            )
        )
    )

    response = client.get("/deployment/readiness")

    assert response.status_code == 200
    body = response.json()
    checks = _checks_by_id(body)
    assert body["production_ready"] is True
    assert body["capabilities"]["deployment_tenancy_mode"] == "on_prem"
    assert body["capabilities"]["tenant_admission_mode"] == "registered_only"
    assert checks["registered_tenant_admission"]["status"] == "ready"
    assert checks["deployment_tenancy_profile"]["status"] == "ready"
    assert "deployment_tenancy_profile" not in body["production_blockers"]
    assert "axis-secret-key" not in str(body)
    assert "production-signing-key" not in str(body)


def test_deployment_readiness_flags_insecure_cookie_session_profile() -> None:
    client = TestClient(
        create_app(
            _enterprise_sso_settings(
                api_base_url="http://api.axis.example",
                public_base_url="http://console.axis.example",
                oidc_redirect_uri="http://api.axis.example/identity/oidc/callback",
                oidc_post_logout_redirect_uri="https://console.axis.example/signed-out",
                oidc_session_cookie_secure=True,
                oidc_session_cookie_signing_secret="super-secret-cookie-key",
                audit_ledger_signing_secret="production-signing-key",
            )
        )
    )

    response = client.get("/deployment/readiness")

    assert response.status_code == 200
    body = response.json()
    checks = _checks_by_id(body)
    assert checks["oidc_enterprise_sso"]["status"] == "ready"
    assert checks["oidc_secure_cookie_session"]["status"] == "action_required"
    assert "oidc_secure_cookie_session" in body["production_blockers"]
    assert body["capabilities"]["oidc_session_cookie_secure"] is True
    assert body["capabilities"][
        "oidc_session_cookie_signing_secret_configured"
    ] is True
    assert body["capabilities"]["oidc_session_cookie_ttl_seconds"] == 3600
    assert body["capabilities"]["api_base_url_https"] is False
    assert body["capabilities"]["public_base_url_https"] is False
    assert body["capabilities"]["oidc_redirect_uri_https"] is False
    assert body["capabilities"]["oidc_post_logout_redirect_uri_https"] is True
    assert "super-secret-cookie-key" not in str(body)
