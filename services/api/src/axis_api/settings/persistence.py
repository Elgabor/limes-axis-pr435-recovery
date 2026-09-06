"""Persistence configuration field definitions (no environment loading)."""

from pydantic import BaseModel, Field


class PersistenceSettings(BaseModel):
    redis_url: str | None = Field(default=None, alias="AXIS_REDIS_URL")
    redis_timeout_seconds: float = Field(
        default=0.25,
        ge=0.05,
        le=5.0,
        alias="AXIS_REDIS_TIMEOUT_SECONDS",
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
