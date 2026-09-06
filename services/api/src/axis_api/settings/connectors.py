"""Connectors configuration field definitions (no environment loading)."""

from pydantic import BaseModel, Field


class ConnectorsSettings(BaseModel):
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
