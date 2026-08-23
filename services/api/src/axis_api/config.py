from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from axis_api.tenant_admission import (
    TENANT_ADMISSION_CLAIMS_ONLY,
    TENANT_ADMISSION_REGISTERED_ONLY,
)


class Settings(BaseSettings):
    environment: str = Field(default="development", alias="AXIS_ENV")
    public_base_url: str = Field(default="http://localhost:3000", alias="AXIS_PUBLIC_BASE_URL")
    api_base_url: str = Field(default="http://localhost:8000", alias="AXIS_API_BASE_URL")
    cors_origins: list[str] = Field(
        default=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3100",
            "http://127.0.0.1:3100",
        ],
        alias="AXIS_CORS_ORIGINS",
    )
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
    redis_url: str | None = Field(default=None, alias="AXIS_REDIS_URL")
    redis_timeout_seconds: float = Field(
        default=0.25,
        ge=0.05,
        le=5.0,
        alias="AXIS_REDIS_TIMEOUT_SECONDS",
    )
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
    postgres_connect_timeout_seconds: int = Field(
        default=3,
        ge=1,
        le=30,
        alias="AXIS_POSTGRES_CONNECT_TIMEOUT_SECONDS",
    )
    postgres_pool_timeout_seconds: float = Field(
        default=3.0,
        ge=0.1,
        le=30.0,
        alias="AXIS_POSTGRES_POOL_TIMEOUT_SECONDS",
    )
    usage_metering_enabled: bool = Field(
        default=False,
        alias="AXIS_USAGE_METERING_ENABLED",
    )
    usage_metering_failure_mode: str = Field(
        default="open",
        pattern="^(open|closed)$",
        alias="AXIS_USAGE_METERING_FAILURE_MODE",
    )
    usage_metering_admission_statement_timeout_ms: int = Field(
        default=1_500,
        ge=100,
        le=10_000,
        alias="AXIS_USAGE_METERING_ADMISSION_STATEMENT_TIMEOUT_MS",
    )
    usage_metering_flush_interval_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=3600.0,
        alias="AXIS_USAGE_METERING_FLUSH_INTERVAL_SECONDS",
    )
    usage_metering_aggregation_window_seconds: int = Field(
        default=86_400,
        ge=60,
        le=86_400,
        alias="AXIS_USAGE_METERING_AGGREGATION_WINDOW_SECONDS",
    )
    usage_metering_projection_batch_size: int = Field(
        default=500,
        ge=1,
        le=10_000,
        alias="AXIS_USAGE_METERING_PROJECTION_BATCH_SIZE",
    )
    usage_metering_projection_max_batches_per_tick: int = Field(
        default=10,
        ge=1,
        le=100,
        alias="AXIS_USAGE_METERING_PROJECTION_MAX_BATCHES_PER_TICK",
    )
    usage_metering_projection_failure_threshold: int = Field(
        default=3,
        ge=1,
        le=100,
        alias="AXIS_USAGE_METERING_PROJECTION_FAILURE_THRESHOLD",
    )
    usage_metering_projection_max_backlog_age_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=86_400.0,
        alias="AXIS_USAGE_METERING_PROJECTION_MAX_BACKLOG_AGE_SECONDS",
    )
    usage_metering_shutdown_timeout_seconds: float = Field(
        default=10.0,
        ge=0.1,
        le=60.0,
        alias="AXIS_USAGE_METERING_SHUTDOWN_TIMEOUT_SECONDS",
    )
    readiness_probe_timeout_seconds: float = Field(
        default=1.0,
        ge=0.05,
        le=10.0,
        alias="AXIS_READINESS_PROBE_TIMEOUT_SECONDS",
    )
    scheduled_jobs_enabled: bool = Field(
        default=False,
        alias="AXIS_SCHEDULED_JOBS_ENABLED",
    )
    scheduled_audit_retention_interval_seconds: int = Field(
        default=86_400,
        ge=60,
        alias="AXIS_SCHEDULED_AUDIT_RETENTION_INTERVAL_SECONDS",
    )
    scheduled_audit_retention_days: int = Field(
        default=365,
        ge=30,
        le=3650,
        alias="AXIS_SCHEDULED_AUDIT_RETENTION_DAYS",
    )
    scheduled_audit_retention_dry_run: bool = Field(
        default=True,
        alias="AXIS_SCHEDULED_AUDIT_RETENTION_DRY_RUN",
    )
    scheduled_audit_retention_batch_limit: int = Field(
        default=500,
        ge=1,
        le=1000,
        alias="AXIS_SCHEDULED_AUDIT_RETENTION_BATCH_LIMIT",
    )
    scheduled_session_sweep_interval_seconds: int = Field(
        default=900,
        ge=60,
        alias="AXIS_SCHEDULED_SESSION_SWEEP_INTERVAL_SECONDS",
    )
    scheduled_session_sweep_batch_limit: int = Field(
        default=500,
        ge=1,
        le=5000,
        alias="AXIS_SCHEDULED_SESSION_SWEEP_BATCH_LIMIT",
    )
    scheduled_tenant_reconciliation_interval_seconds: int = Field(
        default=3600,
        ge=60,
        alias="AXIS_SCHEDULED_TENANT_RECONCILIATION_INTERVAL_SECONDS",
    )
    otel_enabled: bool = Field(
        default=False,
        alias="AXIS_OTEL_ENABLED",
    )
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4318",
        alias="AXIS_OTEL_EXPORTER_OTLP_ENDPOINT",
    )
    otel_service_name: str | None = Field(
        default=None,
        alias="AXIS_OTEL_SERVICE_NAME",
    )
    otel_metrics_enabled: bool = Field(
        default=True,
        alias="AXIS_OTEL_METRICS_ENABLED",
    )
    postgres_dsn: str = Field(
        default="postgresql+psycopg://axis:axis@localhost:5432/axis",
        alias="AXIS_POSTGRES_DSN",
    )
    typedb_address: str = Field(default="localhost:1729", alias="AXIS_TYPEDB_ADDRESS")
    typedb_username: str = Field(default="admin", alias="AXIS_TYPEDB_USERNAME")
    typedb_password: str = Field(default="password", alias="AXIS_TYPEDB_PASSWORD")
    typedb_database: str = Field(default="axis", alias="AXIS_TYPEDB_DATABASE")
    ontology_mutations_enabled: bool = Field(
        default=False,
        alias="AXIS_ONTOLOGY_MUTATIONS_ENABLED",
    )
    ontology_queries_enabled: bool = Field(
        default=False,
        alias="AXIS_ONTOLOGY_QUERIES_ENABLED",
    )
    temporal_address: str = Field(default="localhost:7233", alias="AXIS_TEMPORAL_ADDRESS")
    temporal_namespace: str = Field(default="default", alias="AXIS_TEMPORAL_NAMESPACE")
    temporal_signal_timeout_seconds: float = Field(
        default=2.0,
        alias="AXIS_TEMPORAL_SIGNAL_TIMEOUT_SECONDS",
    )
    workflow_signals_enabled: bool = Field(
        default=True,
        alias="AXIS_WORKFLOW_SIGNALS_ENABLED",
    )
    approval_decision_outbox_enabled: bool = Field(
        default=False,
        alias="AXIS_APPROVAL_DECISION_OUTBOX_ENABLED",
    )
    approval_decision_outbox_dispatch_enabled: bool = Field(
        default=False,
        alias="AXIS_APPROVAL_DECISION_OUTBOX_DISPATCH_ENABLED",
    )
    approval_decision_outbox_dispatch_interval_seconds: int = Field(
        default=5,
        ge=1,
        le=3600,
        alias="AXIS_APPROVAL_DECISION_OUTBOX_DISPATCH_INTERVAL_SECONDS",
    )
    approval_decision_outbox_batch_size: int = Field(
        default=10,
        ge=1,
        le=100,
        alias="AXIS_APPROVAL_DECISION_OUTBOX_BATCH_SIZE",
    )
    approval_decision_outbox_claim_timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=3600,
        alias="AXIS_APPROVAL_DECISION_OUTBOX_CLAIM_TIMEOUT_SECONDS",
    )
    approval_decision_outbox_max_attempts: int = Field(
        default=10,
        ge=1,
        le=100,
        alias="AXIS_APPROVAL_DECISION_OUTBOX_MAX_ATTEMPTS",
    )
    approval_decision_outbox_retry_base_seconds: int = Field(
        default=1,
        ge=1,
        le=3600,
        alias="AXIS_APPROVAL_DECISION_OUTBOX_RETRY_BASE_SECONDS",
    )
    approval_decision_outbox_retry_max_seconds: int = Field(
        default=300,
        ge=1,
        le=86_400,
        alias="AXIS_APPROVAL_DECISION_OUTBOX_RETRY_MAX_SECONDS",
    )

    workflow_history_persistence_enabled: bool = Field(
        default=False,
        alias="AXIS_WORKFLOW_HISTORY_PERSISTENCE_ENABLED",
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
    external_model_egress_enabled: bool = Field(
        default=False,
        alias="AXIS_EXTERNAL_MODEL_EGRESS_ENABLED",
    )
    model_routing_execution_enabled: bool = Field(
        default=False,
        alias="AXIS_MODEL_ROUTING_EXECUTION_ENABLED",
    )
    model_invocation_timeout_seconds: float = Field(
        default=30.0,
        ge=0.1,
        le=600.0,
        alias="AXIS_MODEL_INVOCATION_TIMEOUT_SECONDS",
    )
    model_invocation_allowed_base_urls: list[str] = Field(
        default_factory=list,
        alias="AXIS_MODEL_INVOCATION_ALLOWED_BASE_URLS",
    )
    model_invocation_prompt_excerpt_chars: int = Field(
        default=0,
        ge=0,
        le=2000,
        alias="AXIS_MODEL_INVOCATION_PROMPT_EXCERPT_CHARS",
    )
    agent_run_execution_enabled: bool = Field(
        default=False,
        alias="AXIS_AGENT_RUN_EXECUTION_ENABLED",
    )
    agent_run_max_model_calls: int = Field(
        default=3,
        ge=1,
        le=10,
        alias="AXIS_AGENT_RUN_MAX_MODEL_CALLS",
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
    credential_lease_execution_enabled: bool = Field(
        default=False,
        alias="AXIS_CREDENTIAL_LEASE_EXECUTION_ENABLED",
    )
    credential_lease_provider_adapters_enabled: bool = Field(
        default=False,
        alias="AXIS_CREDENTIAL_LEASE_PROVIDER_ADAPTERS_ENABLED",
    )
    connector_sync_execution_enabled: bool = Field(
        default=False,
        alias="AXIS_CONNECTOR_SYNC_EXECUTION_ENABLED",
    )
    connector_live_sync_execution_enabled: bool = Field(
        default=False,
        alias="AXIS_CONNECTOR_LIVE_SYNC_EXECUTION_ENABLED",
    )
    file_csv_live_sync_root: str | None = Field(
        default=None,
        alias="AXIS_FILE_CSV_LIVE_SYNC_ROOT",
    )
    file_csv_live_sync_profile_id: str = Field(
        default="profile_file_csv_local_dropzone",
        alias="AXIS_FILE_CSV_LIVE_SYNC_PROFILE_ID",
    )
    file_csv_live_sync_max_rows: int = Field(
        default=500,
        ge=1,
        le=10_000,
        alias="AXIS_FILE_CSV_LIVE_SYNC_MAX_ROWS",
    )
    file_csv_live_sync_batch_size: int = Field(
        default=100,
        ge=1,
        le=1_000,
        alias="AXIS_FILE_CSV_LIVE_SYNC_BATCH_SIZE",
    )
    external_db_live_sync_batch_size: int = Field(
        default=100,
        ge=1,
        le=1_000,
        alias="AXIS_EXTERNAL_DB_LIVE_SYNC_BATCH_SIZE",
    )
    external_db_sync_execution_enabled: bool = Field(
        default=False,
        alias="AXIS_EXTERNAL_DB_SYNC_EXECUTION_ENABLED",
    )
    external_db_live_query_preflight_enabled: bool = Field(
        default=False,
        alias="AXIS_EXTERNAL_DB_LIVE_QUERY_PREFLIGHT_ENABLED",
    )
    external_db_live_query_execution_enabled: bool = Field(
        default=False,
        alias="AXIS_EXTERNAL_DB_LIVE_QUERY_EXECUTION_ENABLED",
    )
    external_db_live_query_dsn: str | None = Field(
        default=None,
        alias="AXIS_EXTERNAL_DB_LIVE_QUERY_DSN",
    )
    external_db_live_query_profile_id: str = Field(
        default="profile_postgres_ops_readonly",
        alias="AXIS_EXTERNAL_DB_LIVE_QUERY_PROFILE_ID",
    )
    external_db_live_query_schema: str = Field(
        default="operations",
        alias="AXIS_EXTERNAL_DB_LIVE_QUERY_SCHEMA",
    )
    external_db_live_query_table: str = Field(
        default="production_orders",
        alias="AXIS_EXTERNAL_DB_LIVE_QUERY_TABLE",
    )
    external_db_live_query_columns: list[str] = Field(
        default_factory=lambda: [
            "order_id",
            "asset_id",
            "work_center",
            "status",
            "risk_level",
        ],
        alias="AXIS_EXTERNAL_DB_LIVE_QUERY_COLUMNS",
    )
    external_db_live_query_row_limit: int = Field(
        default=100,
        ge=1,
        le=1000,
        alias="AXIS_EXTERNAL_DB_LIVE_QUERY_ROW_LIMIT",
    )
    external_db_live_query_private_endpoint_ref: str = Field(
        default=(
            "private-endpoint://tenant_demo_manufacturing/"
            "persisted-operations-postgres-readonly"
        ),
        alias="AXIS_EXTERNAL_DB_LIVE_QUERY_PRIVATE_ENDPOINT_REF",
    )
    external_db_lease_scoped_secret_resolution_enabled: bool = Field(
        default=False,
        alias="AXIS_EXTERNAL_DB_LEASE_SCOPED_SECRET_RESOLUTION_ENABLED",
    )
    external_db_runtime_egress_enforcement_enabled: bool = Field(
        default=False,
        alias="AXIS_EXTERNAL_DB_RUNTIME_EGRESS_ENFORCEMENT_ENABLED",
    )
    external_db_live_query_endpoint_target_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
        alias="AXIS_EXTERNAL_DB_LIVE_QUERY_ENDPOINT_TARGET_SHA256",
    )
    external_db_discovery_enabled: bool = Field(
        default=False,
        alias="AXIS_EXTERNAL_DB_DISCOVERY_ENABLED",
    )
    external_db_discovery_profile_id: str = Field(
        default="profile_postgres_discovery_readonly",
        alias="AXIS_EXTERNAL_DB_DISCOVERY_PROFILE_ID",
    )
    external_db_discovery_schemas: list[str] = Field(
        default_factory=lambda: ["operations"],
        alias="AXIS_EXTERNAL_DB_DISCOVERY_SCHEMAS",
    )
    external_db_discovery_max_tables: int = Field(
        default=25,
        ge=1,
        le=200,
        alias="AXIS_EXTERNAL_DB_DISCOVERY_MAX_TABLES",
    )
    external_db_discovery_max_columns_per_table: int = Field(
        default=40,
        ge=1,
        le=200,
        alias="AXIS_EXTERNAL_DB_DISCOVERY_MAX_COLUMNS_PER_TABLE",
    )
    connector_source_activation_max_selections: int = Field(
        default=20,
        ge=1,
        le=100,
        alias="AXIS_CONNECTOR_SOURCE_ACTIVATION_MAX_SELECTIONS",
    )
    connector_source_ingestion_max_selections: int = Field(
        default=20,
        ge=1,
        le=100,
        alias="AXIS_CONNECTOR_SOURCE_INGESTION_MAX_SELECTIONS",
    )
    source_ingestion_dispatch_enabled: bool = Field(
        default=False,
        alias="AXIS_SOURCE_INGESTION_DISPATCH_ENABLED",
    )
    source_ingestion_dispatch_interval_seconds: int = Field(
        default=15,
        ge=1,
        alias="AXIS_SOURCE_INGESTION_DISPATCH_INTERVAL_SECONDS",
    )
    source_ingestion_batch_size: int = Field(
        default=10,
        ge=1,
        le=100,
        alias="AXIS_SOURCE_INGESTION_BATCH_SIZE",
    )
    source_ingestion_claim_timeout_seconds: int = Field(
        default=120,
        ge=5,
        alias="AXIS_SOURCE_INGESTION_CLAIM_TIMEOUT_SECONDS",
    )
    source_ingestion_retry_base_seconds: int = Field(
        default=2,
        ge=0,
        alias="AXIS_SOURCE_INGESTION_RETRY_BASE_SECONDS",
    )
    source_ingestion_retry_max_seconds: int = Field(
        default=60,
        ge=1,
        alias="AXIS_SOURCE_INGESTION_RETRY_MAX_SECONDS",
    )
    source_ingestion_max_attempts: int = Field(
        default=3,
        ge=1,
        le=20,
        alias="AXIS_SOURCE_INGESTION_MAX_ATTEMPTS",
    )
    source_ingestion_extraction_enabled: bool = Field(
        default=False,
        alias="AXIS_SOURCE_INGESTION_EXTRACTION_ENABLED",
    )
    source_ingestion_extraction_max_rows: int = Field(
        default=10_000,
        ge=1,
        le=1_000_000,
        alias="AXIS_SOURCE_INGESTION_EXTRACTION_MAX_ROWS",
    )
    source_ingestion_extraction_max_bytes: int = Field(
        default=5_000_000,
        ge=1024,
        le=1_000_000_000,
        alias="AXIS_SOURCE_INGESTION_EXTRACTION_MAX_BYTES",
    )
    source_ingestion_extraction_page_size: int = Field(
        default=500,
        ge=1,
        le=10_000,
        alias="AXIS_SOURCE_INGESTION_EXTRACTION_PAGE_SIZE",
    )
    source_ingestion_extraction_time_budget_seconds: int = Field(
        default=30,
        ge=1,
        le=3600,
        alias="AXIS_SOURCE_INGESTION_EXTRACTION_TIME_BUDGET_SECONDS",
    )
    connector_scheduled_live_sync_enabled: bool = Field(
        default=False,
        alias="AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_ENABLED",
    )
    connector_scheduled_live_sync_interval_seconds: int = Field(
        default=3600,
        ge=60,
        alias="AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_INTERVAL_SECONDS",
    )
    connector_scheduled_live_sync_tenant_id: str = Field(
        default="tenant_demo_manufacturing",
        alias="AXIS_CONNECTOR_SCHEDULED_LIVE_SYNC_TENANT_ID",
    )
    audit_ledger_signing_key_id: str = Field(
        default="axis-self-hosted-audit-ledger",
        alias="AXIS_AUDIT_LEDGER_SIGNING_KEY_ID",
    )
    audit_ledger_signing_secret: str | None = Field(
        default=None,
        alias="AXIS_AUDIT_LEDGER_SIGNING_SECRET",
    )
    connector_export_object_store_root: str = Field(
        default=".axis/object-store",
        alias="AXIS_CONNECTOR_EXPORT_OBJECT_STORE_ROOT",
    )
    connector_export_object_store_adapter: str = Field(
        default="local_filesystem",
        alias="AXIS_CONNECTOR_EXPORT_OBJECT_STORE_ADAPTER",
    )
    connector_export_s3_endpoint: str | None = Field(
        default=None,
        alias="AXIS_CONNECTOR_EXPORT_S3_ENDPOINT",
    )
    connector_export_s3_region: str | None = Field(
        default=None,
        alias="AXIS_CONNECTOR_EXPORT_S3_REGION",
    )
    connector_export_s3_bucket: str | None = Field(
        default=None,
        alias="AXIS_CONNECTOR_EXPORT_S3_BUCKET",
    )
    connector_export_s3_access_key: str | None = Field(
        default=None,
        alias="AXIS_CONNECTOR_EXPORT_S3_ACCESS_KEY",
    )
    connector_export_s3_secret_key: str | None = Field(
        default=None,
        alias="AXIS_CONNECTOR_EXPORT_S3_SECRET_KEY",
    )
    connector_export_s3_secure_transport: bool = Field(
        default=True,
        alias="AXIS_CONNECTOR_EXPORT_S3_SECURE_TRANSPORT",
    )
    connector_export_s3_object_lock_enabled: bool = Field(
        default=False,
        alias="AXIS_CONNECTOR_EXPORT_S3_OBJECT_LOCK_ENABLED",
    )
    connector_export_s3_retention_mode: str = Field(
        default="GOVERNANCE",
        alias="AXIS_CONNECTOR_EXPORT_S3_RETENTION_MODE",
    )
    connector_export_s3_retention_days: int = Field(
        default=0,
        alias="AXIS_CONNECTOR_EXPORT_S3_RETENTION_DAYS",
    )
    connector_export_s3_legal_hold_enabled: bool = Field(
        default=False,
        alias="AXIS_CONNECTOR_EXPORT_S3_LEGAL_HOLD_ENABLED",
    )
    replay_arbitrary_policy_set_diff_enabled: bool = Field(
        default=False,
        alias="AXIS_REPLAY_ARBITRARY_POLICY_SET_DIFF_ENABLED",
    )
    dr_runbook_configured: bool = Field(
        default=False,
        alias="AXIS_DR_RUNBOOK_CONFIGURED",
    )
    dr_rpo_rto_defined: bool = Field(
        default=False,
        alias="AXIS_DR_RPO_RTO_DEFINED",
    )
    dr_rehearsal_evidence_configured: bool = Field(
        default=False,
        alias="AXIS_DR_REHEARSAL_EVIDENCE_CONFIGURED",
    )
    dr_restore_owner_configured: bool = Field(
        default=False,
        alias="AXIS_DR_RESTORE_OWNER_CONFIGURED",
    )
    dr_customer_approval_configured: bool = Field(
        default=False,
        alias="AXIS_DR_CUSTOMER_APPROVAL_CONFIGURED",
    )
    support_model_enabled: bool = Field(
        default=False,
        alias="AXIS_SUPPORT_MODEL_ENABLED",
    )
    support_coverage: str = Field(
        default="demo_business_hours",
        alias="AXIS_SUPPORT_COVERAGE",
    )
    support_s1_response_minutes: int = Field(
        default=0,
        alias="AXIS_SUPPORT_S1_RESPONSE_MINUTES",
    )
    support_s2_response_minutes: int = Field(
        default=0,
        alias="AXIS_SUPPORT_S2_RESPONSE_MINUTES",
    )
    support_s3_response_minutes: int = Field(
        default=0,
        alias="AXIS_SUPPORT_S3_RESPONSE_MINUTES",
    )
    support_s4_response_minutes: int = Field(
        default=0,
        alias="AXIS_SUPPORT_S4_RESPONSE_MINUTES",
    )
    support_escalation_channels: list[str] = Field(
        default_factory=list,
        alias="AXIS_SUPPORT_ESCALATION_CHANNELS",
    )
    support_customer_runbook_url: str | None = Field(
        default=None,
        alias="AXIS_SUPPORT_CUSTOMER_RUNBOOK_URL",
    )
    support_status_page_url: str | None = Field(
        default=None,
        alias="AXIS_SUPPORT_STATUS_PAGE_URL",
    )
    support_incident_review_required: bool = Field(
        default=False,
        alias="AXIS_SUPPORT_INCIDENT_REVIEW_REQUIRED",
    )
    support_signed_commitment_configured: bool = Field(
        default=False,
        alias="AXIS_SUPPORT_SIGNED_COMMITMENT_CONFIGURED",
    )
    support_named_staffing_model_configured: bool = Field(
        default=False,
        alias="AXIS_SUPPORT_NAMED_STAFFING_MODEL_CONFIGURED",
    )
    support_customer_incident_operations_configured: bool = Field(
        default=False,
        alias="AXIS_SUPPORT_CUSTOMER_INCIDENT_OPERATIONS_CONFIGURED",
    )
    support_legal_sla_terms_configured: bool = Field(
        default=False,
        alias="AXIS_SUPPORT_LEGAL_SLA_TERMS_CONFIGURED",
    )

    @model_validator(mode="after")
    def validate_approval_decision_outbox_retry_window(self) -> "Settings":
        if (
            self.approval_decision_outbox_retry_max_seconds
            < self.approval_decision_outbox_retry_base_seconds
        ):
            raise ValueError(
                "AXIS_APPROVAL_DECISION_OUTBOX_RETRY_MAX_SECONDS must be greater "
                "than or equal to AXIS_APPROVAL_DECISION_OUTBOX_RETRY_BASE_SECONDS."
            )
        if (
            self.approval_decision_outbox_dispatch_enabled
            and self.approval_decision_outbox_claim_timeout_seconds
            <= self.temporal_signal_timeout_seconds
        ):
            raise ValueError(
                "AXIS_APPROVAL_DECISION_OUTBOX_CLAIM_TIMEOUT_SECONDS must be greater "
                "than AXIS_TEMPORAL_SIGNAL_TIMEOUT_SECONDS."
            )
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


class RuntimeConfigurationError(ValueError):
    """Raised before startup side effects when a runtime profile is unsafe."""


def validate_runtime_configuration(settings: Settings) -> None:
    """Reject production configurations that would expose unauthenticated APIs."""

    environment = settings.environment.strip().casefold()
    if environment in {"prod", "production"} and not settings.oidc_auth_required:
        raise RuntimeConfigurationError(
            "AXIS_OIDC_AUTH_REQUIRED must be true when AXIS_ENV is production."
        )
    if environment in {"prod", "production"} and not settings.api_rate_limit_enabled:
        raise RuntimeConfigurationError(
            "AXIS_API_RATE_LIMIT_ENABLED must be true when AXIS_ENV is production."
        )
    if environment in {"prod", "production"}:
        if "*" not in settings.api_rate_limit_paths:
            raise RuntimeConfigurationError(
                "AXIS_API_RATE_LIMIT_PATHS must include '*' in production."
            )
        if settings.api_rate_limit_backend != "redis":
            raise RuntimeConfigurationError(
                "AXIS_API_RATE_LIMIT_BACKEND must be redis in production."
            )
        if settings.api_rate_limit_failure_mode != "closed":
            raise RuntimeConfigurationError(
                "AXIS_API_RATE_LIMIT_FAILURE_MODE must be closed in production."
            )
        if not settings.redis_url:
            raise RuntimeConfigurationError(
                "AXIS_REDIS_URL is required for production rate limiting."
            )
        if (
            settings.usage_metering_enabled
            and settings.usage_metering_failure_mode != "closed"
        ):
            raise RuntimeConfigurationError(
                "AXIS_USAGE_METERING_FAILURE_MODE must be closed in production "
                "when usage metering is enabled."
            )
        if settings.tenant_admission_mode != TENANT_ADMISSION_REGISTERED_ONLY:
            raise RuntimeConfigurationError(
                "AXIS_TENANT_ADMISSION_MODE must be registered_only when "
                "AXIS_ENV is production."
            )
