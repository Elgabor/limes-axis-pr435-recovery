"""Runtime configuration field definitions (no environment loading)."""

from pydantic import BaseModel, Field, model_validator


class RuntimeSettings(BaseModel):
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
    def validate_approval_decision_outbox_retry_window(self) -> "RuntimeSettings":
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
