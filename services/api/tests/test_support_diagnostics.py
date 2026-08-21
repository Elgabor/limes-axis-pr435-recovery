from fastapi import FastAPI
from fastapi.testclient import TestClient

from axis_api.config import Settings
from axis_api.main import create_app as create_axis_app
from axis_api.object_storage import ObjectLockCapability
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


def _seed_verified_object_lock(app: FastAPI) -> FastAPI:
    """Simulate a live probe of a bucket created with object-lock enabled.

    COMPLIANCE retention is only production-ready when the bucket object-lock
    configuration is verified. Tests seed the memoized capability so the
    diagnostics/readiness surfaces do not attempt a real MinIO network probe.
    """

    app.state.audit_export_object_lock_capability_override = ObjectLockCapability(
        adapter="s3_compatible",
        checked=True,
        bucket_object_lock_enabled=True,
        default_retention_mode="COMPLIANCE",
        compliance_enforceable=True,
        reason="test_seeded_object_lock_enabled",
    )
    return app


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
        "oidc_authorization_url": ("https://idp.example/realms/axis/protocol/openid-connect/auth"),
        "oidc_token_url": "https://idp.example/realms/axis/protocol/openid-connect/token",
        "oidc_end_session_url": ("https://idp.example/realms/axis/protocol/openid-connect/logout"),
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
        "dr_runbook_configured": True,
        "dr_rpo_rto_defined": True,
        "dr_rehearsal_evidence_configured": True,
        "dr_restore_owner_configured": True,
        "dr_customer_approval_configured": True,
        "deployment_network_policy_enabled": True,
        "deployment_network_egress_mode": "restricted",
        "deployment_network_egress_allowlist_configured": True,
        "deployment_tenancy_mode": "saas_multi_tenant",
        "deployment_customer_isolation_configured": True,
        "deployment_data_residency_configured": True,
        "deployment_operator_access_runbook_configured": True,
        "deployment_break_glass_approval_configured": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_support_diagnostics_reports_public_safe_demo_support_bundle() -> None:
    client = TestClient(create_app(Settings(postgres_dsn="sqlite+pysqlite://")))

    response = client.get("/support/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "axis-api"
    assert body["status"] == "action_required"
    assert body["safe_to_share"] is True
    assert body["demo_support_ready"] is True
    assert body["production_support_ready"] is False
    assert body["diagnostics"]["deployment"]["profile"] == "local_demo"
    assert body["diagnostics"]["deployment"]["demo_safe"] is True
    assert body["diagnostics"]["deployment"]["production_ready"] is False
    assert body["diagnostics"]["identity"]["readiness_status"] == "action_required"
    assert body["support_blockers"] == [
        "oidc_enterprise_sso",
        "oidc_secure_cookie_session",
        "registered_tenant_admission",
        "api_rate_limiting",
        "network_egress_restricted",
        "deployment_tenancy_profile",
        "audit_ledger_signing_configured",
        "production_object_store_adapter",
        "production_dr_procedures",
        "production_support_model",
        "production_support_commitments",
    ]
    assert body["diagnostics"]["support_model"] == {
        "enabled": False,
        "coverage": "demo_business_hours",
        "severity_response_minutes": {
            "S1": 0,
            "S2": 0,
            "S3": 0,
            "S4": 0,
        },
        "escalation_channels": [],
        "customer_runbook_configured": False,
        "status_page_configured": False,
        "incident_review_required": False,
    }
    assert body["diagnostics"]["support_commitments"] == {
        "signed_commitment_configured": False,
        "named_staffing_model_configured": False,
        "customer_incident_operations_configured": False,
        "legal_sla_terms_configured": False,
    }
    assert body["support_artifacts"] == [
        {"label": "Demo readiness runbook", "path": "docs/demo-readiness.md"},
        {"label": "Deployment threat model", "path": "docs/threat-model.md"},
        {"label": "Support operations runbook", "path": "docs/support-operations.md"},
    ]
    assert body["redaction_policy"] == [
        "bearer_tokens",
        "raw_jwks",
        "credential_material",
        "signing_material",
        "database_dsn",
    ]

    checks = _checks_by_id(body)
    assert checks["support_diagnostics_public_safe"]["status"] == "ready"
    assert checks["support_runbook_baseline"]["status"] == "ready"
    assert checks["production_support_model"]["status"] == "action_required"
    assert "password" not in str(body).lower()


def test_support_diagnostics_never_returns_sensitive_signing_material() -> None:
    client = TestClient(
        create_app(
            _enterprise_sso_settings(
                audit_ledger_signing_secret="do-not-return-this-signing-material",
                external_model_egress_enabled=False,
                connector_sync_execution_enabled=False,
                external_db_sync_execution_enabled=False,
                external_db_live_query_preflight_enabled=False,
                credential_lease_execution_enabled=False,
                credential_lease_provider_adapters_enabled=False,
            )
        )
    )

    response = client.get("/support/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["diagnostics"]["deployment"]["profile"] == "production"
    assert body["diagnostics"]["identity"]["readiness_status"] == "ready"
    assert body["diagnostics"]["audit_ledger_signing_configured"] is True
    assert body["production_support_ready"] is False
    assert body["support_blockers"] == [
        "production_object_store_adapter",
        "production_support_model",
        "production_support_commitments",
    ]
    assert "do-not-return-this-signing-material" not in str(body)
    assert "password" not in str(body).lower()


def test_support_diagnostics_reports_s3_object_store_without_secret_material() -> None:
    client = TestClient(
        _seed_verified_object_lock(
            create_app(
                _enterprise_sso_settings(
                    audit_ledger_signing_secret="do-not-return-this-signing-material",
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
                    connector_export_s3_object_lock_enabled=True,
                    connector_export_s3_retention_mode="COMPLIANCE",
                    connector_export_s3_retention_days=365,
                    connector_export_s3_legal_hold_enabled=True,
                )
            )
        )
    )

    response = client.get("/support/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["diagnostics"]["object_store_adapter"] == "s3_compatible"
    assert body["diagnostics"]["object_store_worm_retention_enabled"] is True
    assert body["diagnostics"]["object_store_retention_mode"] == "COMPLIANCE"
    assert body["diagnostics"]["object_store_retention_days"] == 365
    assert body["support_blockers"] == [
        "production_support_model",
        "production_support_commitments",
    ]
    assert "axis-secret-key" not in str(body)
    assert "axis-service-account" not in str(body)
    assert "do-not-return-this-signing-material" not in str(body)


def test_support_diagnostics_blocks_support_model_without_signed_commitments() -> None:
    client = TestClient(
        _seed_verified_object_lock(
            create_app(
                _enterprise_sso_settings(
                    audit_ledger_signing_secret="do-not-return-this-signing-material",
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
                    connector_export_s3_object_lock_enabled=True,
                    connector_export_s3_retention_mode="COMPLIANCE",
                    connector_export_s3_retention_days=365,
                    connector_export_s3_legal_hold_enabled=True,
                    support_model_enabled=True,
                    support_coverage="24x7",
                    support_s1_response_minutes=30,
                    support_s2_response_minutes=120,
                    support_s3_response_minutes=480,
                    support_s4_response_minutes=1440,
                    support_escalation_channels=[
                        "customer_success_manager",
                        "platform_engineering_on_call",
                        "security_incident_lead",
                    ],
                    support_customer_runbook_url="https://support.axis.example/runbooks/customer",
                    support_status_page_url="https://status.axis.example",
                    support_incident_review_required=True,
                )
            )
        )
    )

    response = client.get("/support/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "action_required"
    assert body["production_support_ready"] is False
    assert body["support_blockers"] == ["production_support_commitments"]
    checks = _checks_by_id(body)
    assert checks["production_support_model"]["status"] == "ready"
    assert checks["production_support_commitments"]["status"] == "action_required"
    assert body["diagnostics"]["support_commitments"] == {
        "signed_commitment_configured": False,
        "named_staffing_model_configured": False,
        "customer_incident_operations_configured": False,
        "legal_sla_terms_configured": False,
    }
    assert "https://support.axis.example" not in str(body)
    assert "https://status.axis.example" not in str(body)
    assert "axis-secret-key" not in str(body)
    assert "do-not-return-this-signing-material" not in str(body)


def test_support_diagnostics_reports_ready_production_support_commitments() -> None:
    client = TestClient(
        _seed_verified_object_lock(
            create_app(
                _enterprise_sso_settings(
                    audit_ledger_signing_secret="do-not-return-this-signing-material",
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
                    connector_export_s3_object_lock_enabled=True,
                    connector_export_s3_retention_mode="COMPLIANCE",
                    connector_export_s3_retention_days=365,
                    connector_export_s3_legal_hold_enabled=True,
                    support_model_enabled=True,
                    support_coverage="24x7",
                    support_s1_response_minutes=30,
                    support_s2_response_minutes=120,
                    support_s3_response_minutes=480,
                    support_s4_response_minutes=1440,
                    support_escalation_channels=[
                        "customer_success_manager",
                        "platform_engineering_on_call",
                        "security_incident_lead",
                    ],
                    support_customer_runbook_url="https://support.axis.example/runbooks/customer",
                    support_status_page_url="https://status.axis.example",
                    support_incident_review_required=True,
                    support_signed_commitment_configured=True,
                    support_named_staffing_model_configured=True,
                    support_customer_incident_operations_configured=True,
                    support_legal_sla_terms_configured=True,
                )
            )
        )
    )

    response = client.get("/support/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["production_support_ready"] is True
    assert body["support_blockers"] == []
    assert body["diagnostics"]["support_model"] == {
        "enabled": True,
        "coverage": "24x7",
        "severity_response_minutes": {
            "S1": 30,
            "S2": 120,
            "S3": 480,
            "S4": 1440,
        },
        "escalation_channels": [
            "customer_success_manager",
            "platform_engineering_on_call",
            "security_incident_lead",
        ],
        "customer_runbook_configured": True,
        "status_page_configured": True,
        "incident_review_required": True,
    }
    assert body["diagnostics"]["support_commitments"] == {
        "signed_commitment_configured": True,
        "named_staffing_model_configured": True,
        "customer_incident_operations_configured": True,
        "legal_sla_terms_configured": True,
    }
    checks = _checks_by_id(body)
    assert checks["production_support_model"]["status"] == "ready"
    assert checks["production_support_commitments"]["status"] == "ready"
    assert checks["support_slo_targets"]["status"] == "ready"
    assert checks["support_escalation_channels"]["status"] == "ready"
    assert "https://support.axis.example" not in str(body)
    assert "https://status.axis.example" not in str(body)
    assert "axis-secret-key" not in str(body)
    assert "do-not-return-this-signing-material" not in str(body)
