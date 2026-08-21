from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(
        String(600), nullable=False, default="", server_default=""
    )
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="active", server_default="active", index=True
    )
    created_by: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        default="axis-bootstrap",
        server_default="axis-bootstrap",
        index=True,
    )
    bootstrap_admin_actor_id: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True
    )
    provision_idempotency_key: Mapped[str | None] = mapped_column(
        String(200), nullable=True, index=True
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_by: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    suspension_reason: Mapped[str | None] = mapped_column(String(600), nullable=True)
    reactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reactivated_by: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="platform.tenant.bootstrapped",
        server_default="platform.tenant.bootstrapped",
        index=True,
    )
    notes: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    vocabulary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "provision_idempotency_key",
            name="uq_tenants_provision_idempotency",
        ),
    )


class TenantQuota(Base):
    __tablename__ = "tenant_quotas"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    quota_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    quota_value: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "quota_key", name="uq_tenant_quotas_tenant_quota_key"),
    )


class TenantUsageRecord(Base):
    __tablename__ = "tenant_usage_records"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    metric_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    # Left-edge of the aggregation window this row accumulates (UTC, epoch-aligned).
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    period_window_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=86_400,
        server_default=text("86400"),
    )
    # Cumulative consumption for (tenant, metric, period). Incremented in place via
    # upsert-add, so it is a running total rather than a single event.
    quantity: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    dimensions: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    first_recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    last_recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "period_window_seconds BETWEEN 60 AND 86400",
            name="ck_tenant_usage_records_period_window_range",
        ),
        UniqueConstraint(
            "tenant_id",
            "metric_key",
            "period_window_seconds",
            "period_start",
            name="uq_tenant_usage_records_tenant_metric_window_period",
        ),
        Index(
            "ix_tenant_usage_records_tenant_metric_window_period",
            "tenant_id",
            "metric_key",
            "period_window_seconds",
            "period_start",
        ),
    )


class TenantUsageEvent(Base):
    """Immutable source event for exactly-once usage aggregation retries."""

    __tablename__ = "tenant_usage_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    metric_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(220), nullable=False)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    period_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dimensions: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    projected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="ck_tenant_usage_events_quantity_positive",
        ),
        CheckConstraint(
            "period_window_seconds BETWEEN 60 AND 86400",
            name="ck_tenant_usage_events_period_window_range",
        ),
        UniqueConstraint(
            "tenant_id",
            "metric_key",
            "source_type",
            "source_id",
            name="uq_tenant_usage_events_source",
        ),
        Index(
            "ix_tenant_usage_events_tenant_occurred",
            "tenant_id",
            "occurred_at",
            "id",
        ),
        Index(
            "ix_tenant_usage_events_tenant_metric_window_period",
            "tenant_id",
            "metric_key",
            "period_window_seconds",
            "period_start",
        ),
        Index(
            "ix_tenant_usage_events_unprojected",
            "recorded_at",
            "id",
            postgresql_where=text("projected_at IS NULL"),
            sqlite_where=text("projected_at IS NULL"),
        ),
    )


class Actor(Base):
    __tablename__ = "actors"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class OidcBrowserSession(Base):
    __tablename__ = "oidc_browser_sessions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    session_id_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_token_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rotated_to_session_id_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    revoke_audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AuditLegalHold(Base):
    __tablename__ = "audit_legal_holds"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    hold_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(600), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    approved_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    released_by: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    release_reason: Mapped[str | None] = mapped_column(String(600), nullable=True)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    release_audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "hold_id", name="uq_audit_legal_holds_tenant_hold"),
    )


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    approval_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    action_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    owner_role: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_actor_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(600), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "approval_id", name="uq_approval_records_tenant_approval"),
    )


class ApprovalDecisionOutbox(Base):
    __tablename__ = "approval_decision_outbox"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    approval_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    workflow_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    signal_name: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    decision_actor_id: Mapped[str] = mapped_column(String(160), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="pending", server_default="pending", index=True
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claim_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "approval_id", name="uq_approval_decision_outbox_tenant_approval"
        ),
        Index("ix_approval_decision_outbox_dispatch", "status", "available_at", "id"),
        Index(
            "ix_approval_decision_outbox_stale_claim",
            "status",
            "lease_expires_at",
            "id",
        ),
        CheckConstraint(
            "status IN ('pending', 'dispatching', 'delivered', 'dead_letter')",
            name="ck_approval_decision_outbox_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_approval_decision_outbox_attempt_count"),
        CheckConstraint(
            "(status = 'dispatching' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR (status <> 'dispatching' "
            "AND claim_token IS NULL AND claimed_at IS NULL AND lease_expires_at IS NULL)",
            name="ck_approval_decision_outbox_claim_state",
        ),
        CheckConstraint(
            "(status = 'delivered' AND delivered_at IS NOT NULL AND dead_lettered_at IS NULL) "
            "OR (status <> 'delivered' AND delivered_at IS NULL)",
            name="ck_approval_decision_outbox_delivered_state",
        ),
        CheckConstraint(
            "(status = 'dead_letter' AND dead_lettered_at IS NOT NULL AND delivered_at IS NULL) "
            "OR (status <> 'dead_letter' AND dead_lettered_at IS NULL)",
            name="ck_approval_decision_outbox_dead_letter_state",
        ),
    )


class ActionRun(Base):
    __tablename__ = "action_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    action_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(80), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    approval_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "action_id",
            "idempotency_key",
            name="uq_action_runs_tenant_action_idempotency",
        ),
    )


class DemoReferenceRecord(Base):
    __tablename__ = "demo_reference_records"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    surface: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "surface",
            "reference_id",
            name="uq_demo_reference_records_tenant_surface_reference",
        ),
    )


class WorkflowRunRecord(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    workflow_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    owner_role: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    runtime: Mapped[str] = mapped_column(String(120), nullable=False)
    adapter: Mapped[str] = mapped_column(String(120), nullable=False)
    autonomy_level: Mapped[str] = mapped_column(String(8), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    eta: Mapped[str] = mapped_column(String(120), nullable=False)
    blocker: Mapped[str | None] = mapped_column(String(600), nullable=True)
    objective: Mapped[str] = mapped_column(String(1000), nullable=False)
    current_step: Mapped[str] = mapped_column(String(200), nullable=False)
    related_risk: Mapped[str] = mapped_column(String(160), nullable=False)
    related_assets: Mapped[list] = mapped_column(JSON, nullable=False)
    inputs: Mapped[list] = mapped_column(JSON, nullable=False)
    proposed_outputs: Mapped[list] = mapped_column(JSON, nullable=False)
    pending_signals: Mapped[list] = mapped_column(JSON, nullable=False)
    controls: Mapped[list] = mapped_column(JSON, nullable=False)
    audit_scope: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    replay_ready: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "workflow_id", name="uq_workflow_runs_tenant_workflow"),
    )


class WorkflowTimelineRecord(Base):
    __tablename__ = "workflow_timeline_events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    workflow_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(120), nullable=False)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workflow_id",
            "sequence",
            name="uq_workflow_timeline_tenant_workflow_sequence",
        ),
    )


class ReplaySimulationOutput(Base):
    __tablename__ = "replay_simulation_outputs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    simulation_output_id: Mapped[str] = mapped_column(
        String(180),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    artifact_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    required_scope: Mapped[str] = mapped_column(String(160), nullable=False)
    replay_mode: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    determinism_status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    output_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    retention_window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    permission_decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    artifact_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(600), nullable=False)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "simulation_output_id",
            name="uq_replay_simulation_outputs_tenant_output",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_replay_simulation_outputs_tenant_idempotency",
        ),
    )


class ConnectorConfiguration(Base):
    __tablename__ = "connector_configurations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sync_mode: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    runtime_boundary: Mapped[str] = mapped_column(String(160), nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    configuration_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    credential_ref_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "connector_id",
            name="uq_connector_configurations_tenant_connector",
        ),
    )


class ConnectorManifestRecord(Base):
    __tablename__ = "connector_manifests"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    connector_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    runtime_boundary: Mapped[str] = mapped_column(String(160), nullable=False)
    registered_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    manifest_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    runtime_policy: Mapped[dict] = mapped_column(JSON, nullable=False)
    preview_sample: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    revises_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replaced_by_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision_idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        index=True,
    )
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "connector_id",
            "revision_number",
            name="uq_connector_manifests_tenant_connector_revision",
        ),
        UniqueConstraint(
            "tenant_id",
            "revision_idempotency_key",
            name="uq_connector_manifests_tenant_revision_idempotency",
        ),
    )


class ConnectorCredentialHandle(Base):
    __tablename__ = "connector_credential_handles"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    handle_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    secret_provider: Mapped[str] = mapped_column(String(120), nullable=False)
    secret_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    purpose: Mapped[str] = mapped_column(String(160), nullable=False)
    rotation_interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    last_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_rotation_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    created_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    labels: Mapped[dict] = mapped_column(JSON, nullable=False)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "handle_id",
            name="uq_connector_credential_handles_tenant_handle",
        ),
    )


class ConnectorCredentialRotation(Base):
    __tablename__ = "connector_credential_rotations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    handle_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    rotated_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ConnectorCredentialLease(Base):
    __tablename__ = "connector_credential_leases"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    handle_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    lease_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    lease_mode: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    runtime_boundary: Mapped[str] = mapped_column(String(160), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    lease_purpose: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    secret_provider: Mapped[str] = mapped_column(String(120), nullable=False)
    secret_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    vault_kms_policy: Mapped[dict] = mapped_column(JSON, nullable=False)
    permission_decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    lease_result: Mapped[dict] = mapped_column(JSON, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    renewal_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    renewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    renewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    renewal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(600), nullable=True)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "lease_id",
            name="uq_connector_credential_leases_tenant_lease",
        ),
    )


class ConnectorEgressPolicy(Base):
    __tablename__ = "connector_egress_policies"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    policy_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connection_profile_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    egress_boundary: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    policy_mode: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    runtime_boundary: Mapped[str] = mapped_column(String(160), nullable=False)
    private_endpoint_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    policy_document: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "policy_id",
            name="uq_connector_egress_policies_tenant_policy",
        ),
    )


class ConnectorRun(Base):
    __tablename__ = "connector_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    runtime_boundary: Mapped[str] = mapped_column(String(160), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    credential_handle_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    input_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            name="uq_connector_runs_tenant_run",
        ),
    )


class ConnectorSyncCheckpoint(Base):
    __tablename__ = "connector_sync_checkpoints"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    checkpoint_id: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    checkpoint_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    runtime_boundary: Mapped[str] = mapped_column(String(160), nullable=False)
    adapter: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    cursor: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "checkpoint_id",
            name="uq_connector_sync_checkpoints_tenant_checkpoint",
        ),
    )


class ConnectorSyncCheckpointClaim(Base):
    __tablename__ = "connector_sync_checkpoint_claims"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    checkpoint_id: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    claim_id: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    claimed_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    lease_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    renewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    renewed_by: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    renewal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    release_reason: Mapped[str | None] = mapped_column(String(600), nullable=True)
    claim_result: Mapped[dict] = mapped_column(JSON, nullable=False)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "claim_id",
            name="uq_connector_sync_checkpoint_claims_tenant_claim",
        ),
        UniqueConstraint(
            "tenant_id",
            "checkpoint_id",
            "idempotency_key",
            name="uq_connector_sync_checkpoint_claims_tenant_checkpoint_idempotency",
        ),
        Index(
            "uq_conn_sync_claims_single_active",
            "tenant_id",
            "checkpoint_id",
            unique=True,
            postgresql_where=text("status = 'claimed'"),
            sqlite_where=text("status = 'claimed'"),
        ),
    )


class ConnectorOntologyProposal(Base):
    __tablename__ = "connector_ontology_proposals"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    proposal_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    source_run_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    source_file_name: Mapped[str] = mapped_column(String(240), nullable=False)
    mapping_profile: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    write_mode: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    graph_mutation_status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    proposed_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    node_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    ontology_type: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    field_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False)
    promotion_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    policy_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    policy_set_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    policy_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    policy_decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    promoted_by: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ontology_mutation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "proposal_id",
            name="uq_connector_ontology_proposals_tenant_proposal",
        ),
    )


class ConnectorOntologyPromotion(Base):
    __tablename__ = "connector_ontology_promotions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    promotion_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    proposal_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    manual_import_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    promotion_mode: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    graph_mutation_status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    ontology_mutation: Mapped[dict] = mapped_column(JSON, nullable=False)
    permission_decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    policy_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    policy_set_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    policy_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    policy_decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "promotion_id",
            name="uq_connector_ontology_promotions_tenant_promotion",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_connector_ontology_promotions_tenant_idempotency",
        ),
    )


class DataAssetStewardshipRecord(Base):
    """Append-only stewardship declaration history for one data asset.

    Every accepted declaration inserts a new revision; the current revision is
    the row whose ``replaced_by_revision_number`` is null. Stewardship
    attributes are declared, never inferred, so no inference metadata exists
    here by design.
    """

    __tablename__ = "data_asset_stewardship_records"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    owner: Mapped[str] = mapped_column(String(200), nullable=False)
    classification: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    residency: Mapped[str] = mapped_column(String(80), nullable=False)
    retention: Mapped[str] = mapped_column(String(80), nullable=False)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    declared_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    revises_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replaced_by_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision_idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "classification IN ('public', 'internal', 'confidential', 'restricted')",
            name="ck_data_asset_stewardship_classification",
        ),
        UniqueConstraint(
            "tenant_id",
            "asset_id",
            "revision_number",
            name="uq_data_asset_stewardship_tenant_asset_revision",
        ),
        UniqueConstraint(
            "tenant_id",
            "revision_idempotency_key",
            name="uq_data_asset_stewardship_tenant_idempotency",
        ),
    )


class ConnectorPromotionPolicy(Base):
    __tablename__ = "connector_promotion_policies"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    policy_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    enforcement_mode: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    required_authoring_scope: Mapped[str] = mapped_column(String(160), nullable=False)
    required_scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    required_manual_import_status: Mapped[str] = mapped_column(String(80), nullable=False)
    required_workflow_signal_status: Mapped[str] = mapped_column(String(80), nullable=False)
    allowed_risk_levels: Mapped[list] = mapped_column(JSON, nullable=False)
    allowed_ontology_types: Mapped[list] = mapped_column(JSON, nullable=False)
    review_window_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    permission_decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    revises_policy_id: Mapped[str | None] = mapped_column(
        String(180),
        nullable=True,
        index=True,
    )
    replaced_by_policy_id: Mapped[str | None] = mapped_column(
        String(180),
        nullable=True,
        index=True,
    )
    revision_idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        index=True,
    )
    revision_approval_id: Mapped[str | None] = mapped_column(
        String(180),
        nullable=True,
        index=True,
    )
    revision_decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revision_workflow_signal_status: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "policy_id",
            name="uq_connector_promotion_policies_tenant_policy",
        ),
        UniqueConstraint(
            "tenant_id",
            "revision_idempotency_key",
            name="uq_connector_promotion_policies_tenant_revision_idempotency",
        ),
    )


class ConnectorPromotionPolicySet(Base):
    __tablename__ = "connector_promotion_policy_sets"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    policy_set_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    policy_set_version: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    activated_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    activation_scope: Mapped[str] = mapped_column(String(160), nullable=False)
    policy_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    permission_decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    activation_reason: Mapped[str] = mapped_column(String(600), nullable=False)
    replaces_policy_set_id: Mapped[str | None] = mapped_column(
        String(180),
        nullable=True,
        index=True,
    )
    replaced_by_policy_set_id: Mapped[str | None] = mapped_column(
        String(180),
        nullable=True,
        index=True,
    )
    replacement_approval_id: Mapped[str | None] = mapped_column(
        String(180),
        nullable=True,
        index=True,
    )
    replacement_decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    replacement_workflow_signal_status: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_to_policy_set_id: Mapped[str | None] = mapped_column(
        String(180),
        nullable=True,
        index=True,
    )
    rollback_approval_id: Mapped[str | None] = mapped_column(
        String(180),
        nullable=True,
        index=True,
    )
    rollback_decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rollback_workflow_signal_status: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    policy_revision_adoptions: Mapped[list] = mapped_column(JSON, nullable=False)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "policy_set_id",
            name="uq_connector_promotion_policy_sets_tenant_set",
        ),
    )


class ConnectorManualImportRequest(Base):
    __tablename__ = "connector_manual_import_requests"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    connector_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    import_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    import_mode: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    owner_role: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    approval_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    workflow_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    proposal_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    import_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    controls: Mapped[list] = mapped_column(JSON, nullable=False)
    graph_mutation_status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    workflow_signal_status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    decision: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    decision_actor_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    decision_note: Mapped[str | None] = mapped_column(String(600), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    workflow_signal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "import_id",
            name="uq_connector_manual_import_requests_tenant_import",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_connector_manual_import_requests_tenant_idempotency",
        ),
    )


class ConnectorEvidenceSnapshotExportRequest(Base):
    __tablename__ = "connector_evidence_snapshot_export_requests"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    export_request_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    export_status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    storage_status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    owner_role: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    approval_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    workflow_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    connector_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    snapshot_idempotency_key: Mapped[str | None] = mapped_column(
        String(200), nullable=True, index=True
    )
    export_reason: Mapped[str] = mapped_column(String(160), nullable=False)
    format: Mapped[str] = mapped_column(String(40), nullable=False)
    limit: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_snapshot_count: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    redaction_policy: Mapped[str] = mapped_column(String(120), nullable=False)
    controls: Mapped[list] = mapped_column(JSON, nullable=False)
    permission_decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    workflow_signal_status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    decision: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    decision_actor_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    decision_note: Mapped[str | None] = mapped_column(String(600), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    workflow_signal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    materialization_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    materialization_idempotency_key: Mapped[str | None] = mapped_column(
        String(200), nullable=True, index=True
    )
    materialized_by: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    materialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    materialization_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    storage_adapter: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_uri: Mapped[str | None] = mapped_column(String(700), nullable=True)
    artifact_checksum_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    artifact_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "export_request_id",
            name="uq_connector_evidence_snapshot_export_requests_tenant_request",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_connector_evidence_snapshot_export_requests_tenant_idempotency",
        ),
    )


class ManufacturingOperationRecord(Base):
    __tablename__ = "manufacturing_operation_records"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    record_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_system: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    owner_role: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    related_asset: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    risk_level: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "record_id",
            name="uq_manufacturing_operation_records_tenant_record",
        ),
    )


class ManufacturingDailyBrief(Base):
    __tablename__ = "manufacturing_daily_briefs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    brief_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    brief_date: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    required_scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    source_record_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    summary_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    permission_decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "brief_id",
            name="uq_manufacturing_daily_briefs_tenant_brief",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_manufacturing_daily_briefs_tenant_idempotency",
        ),
    )


class ManufacturingRiskScenario(Base):
    __tablename__ = "manufacturing_risk_scenarios"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    scenario_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    owner_role: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    workflow_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    source_record_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    scenario_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    permission_decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "scenario_id",
            name="uq_manufacturing_risk_scenarios_tenant_scenario",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_manufacturing_risk_scenarios_tenant_idempotency",
        ),
    )


class PlatformNotificationAcknowledgement(Base):
    __tablename__ = "platform_notification_acknowledgements"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    notification_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(600), nullable=False)
    source: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    notification_title: Mapped[str] = mapped_column(String(300), nullable=False)
    notification_category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    notification_severity: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "notification_id",
            "actor_id",
            name="uq_platform_notification_ack_tenant_notification_actor",
        ),
    )


class ModelEndpoint(Base):
    __tablename__ = "model_endpoints"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    endpoint_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    hosting_boundary: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    default_model: Mapped[str] = mapped_column(String(160), nullable=False)
    task_types: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    credential_handle_id: Mapped[str | None] = mapped_column(
        String(160), nullable=True, index=True
    )
    egress_policy_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    cost_input_per_1k: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    cost_output_per_1k: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    created_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "endpoint_id",
            name="uq_model_endpoints_tenant_endpoint",
        ),
    )


class ModelInvocation(Base):
    __tablename__ = "model_invocations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    endpoint_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    provider_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    hosting_boundary: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    model_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    route_decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    permission_decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    platform_policy_decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    egress_decision: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    response_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    prompt_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    latency_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    estimated_cost_eur: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    provider_request_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_model_invocations_tenant_idempotency",
        ),
        Index(
            "ix_model_invocations_tenant_created_at",
            "tenant_id",
            "created_at",
        ),
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    requested_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    autonomy_level: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    request_fingerprint: Mapped[dict] = mapped_column(JSON, nullable=False)
    context_refs: Mapped[list] = mapped_column(JSON, nullable=False)
    model_invocation_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    proposed_action_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    proposal_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    permission_decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    platform_policy_decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(240), nullable=True, index=True)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_id",
            "idempotency_key",
            name="uq_agent_runs_tenant_agent_idempotency",
        ),
        Index(
            "ix_agent_runs_tenant_agent_created_at",
            "tenant_id",
            "agent_id",
            "created_at",
        ),
    )


class AgentRunStep(Base):
    """Append-only agent run step timeline; steps are never updated or deleted."""

    __tablename__ = "agent_run_steps"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "seq",
            name="uq_agent_run_steps_tenant_run_seq",
        ),
    )


class PlatformPolicy(Base):
    __tablename__ = "platform_policies"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    policy_id: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(600), nullable=False)
    scope: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    effect: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    conditions: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    required_authoring_scope: Mapped[str] = mapped_column(String(160), nullable=False)
    permission_decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audit_event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    revises_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replaced_by_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision_idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        index=True,
    )
    notes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "policy_id",
            "revision_number",
            name="uq_platform_policies_tenant_policy_revision",
        ),
        UniqueConstraint(
            "tenant_id",
            "revision_idempotency_key",
            name="uq_platform_policies_tenant_revision_idempotency",
        ),
        Index(
            "uq_platform_policies_tenant_policy_active",
            "tenant_id",
            "policy_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )
