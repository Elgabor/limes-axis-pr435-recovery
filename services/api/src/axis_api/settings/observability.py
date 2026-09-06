"""Observability configuration field definitions (no environment loading)."""

from pydantic import BaseModel, Field


class ObservabilitySettings(BaseModel):
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
    audit_ledger_signing_key_id: str = Field(
        default="axis-self-hosted-audit-ledger",
        alias="AXIS_AUDIT_LEDGER_SIGNING_KEY_ID",
    )
    audit_ledger_signing_secret: str | None = Field(
        default=None,
        alias="AXIS_AUDIT_LEDGER_SIGNING_SECRET",
    )
