from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from itertools import batched
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import Select, and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from axis_api.audit import AuditEventCreate
from axis_api.models import (
    ActionRun,
    Actor,
    AgentRun,
    AgentRunStep,
    ApprovalDecisionOutbox,
    ApprovalRecord,
    AuditEvent,
    AuditLegalHold,
    ConnectorConfiguration,
    ConnectorCredentialHandle,
    ConnectorCredentialLease,
    ConnectorCredentialRotation,
    ConnectorEgressPolicy,
    ConnectorEvidenceSnapshotExportRequest,
    ConnectorLifecycleEventRecord,
    ConnectorManifestRecord,
    ConnectorManualImportRequest,
    ConnectorOntologyPromotion,
    ConnectorOntologyProposal,
    ConnectorPromotionPolicy,
    ConnectorPromotionPolicySet,
    ConnectorRun,
    ConnectorSourceBatchExportRequest,
    ConnectorSourceBinding,
    ConnectorSourceExtractionBatch,
    ConnectorSourceIngestionRequest,
    ConnectorSyncCheckpoint,
    ConnectorSyncCheckpointClaim,
    DataAssetContractRecord,
    DataAssetResourceObservation,
    DataAssetStewardshipRecord,
    DemoReferenceRecord,
    ManufacturingDailyBrief,
    ManufacturingOperationRecord,
    ManufacturingRiskScenario,
    ModelEndpoint,
    ModelInvocation,
    OidcBrowserSession,
    PlatformNotificationAcknowledgement,
    PlatformPolicy,
    ReplaySimulationOutput,
    Tenant,
    TenantQuota,
    TenantUsageEvent,
    TenantUsageRecord,
    WorkflowRunRecord,
    WorkflowTimelineRecord,
    utc_now,
)
from axis_api.repositories.errors import PersistenceRecordNotFound as PersistenceRecordNotFound
from axis_api.repositories.models import (
    ModelEndpointCreate as ModelEndpointCreate,
)
from axis_api.repositories.models import (
    ModelEndpointStatusUpdate as ModelEndpointStatusUpdate,
)
from axis_api.repositories.models import (
    ModelInvocationCreate as ModelInvocationCreate,
)
from axis_api.repositories.models import (
    ModelInvocationResultRecord as ModelInvocationResultRecord,
)
from axis_api.repositories.models import (
    ModelPersistencePort,
    ModelRepository,
)


class TenantUsageIdempotencyConflict(RuntimeError):
    pass


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class ApprovalRecordCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    workflow_id: str | None = None
    action_id: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    risk_level: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    status: str = Field(default="pending", min_length=1)


class ApprovalDecisionRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    decision_actor_id: str = Field(min_length=1)
    decision_note: str | None = None


class ApprovalDecisionOutboxCreate(BaseModel):
    id: UUID
    tenant_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    signal_name: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    decision_actor_id: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    available_at: datetime


class ActionRunCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    execution_mode: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    approval_id: str | None = None
    workflow_id: str | None = None
    status: str = Field(default="requested", min_length=1)


class ActionRunResultRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    action_run_id: UUID
    status: str = Field(min_length=1)
    result_payload: dict = Field(default_factory=dict)


class AuditLegalHoldCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    hold_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    event_type: str | None = Field(default=None, min_length=1)
    actor_id: str | None = Field(default=None, min_length=1)
    audit_event_id: UUID | None = None
    notes: list[str] = Field(default_factory=list)


class AuditLegalHoldRelease(BaseModel):
    tenant_id: str = Field(min_length=1)
    hold_id: str = Field(min_length=1)
    released_by: str = Field(min_length=1)
    release_reason: str = Field(min_length=1)
    release_audit_event_id: UUID | None = None


class DemoReferenceRecordCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    reference_id: str = Field(min_length=1)
    status: str = Field(default="active", min_length=1)
    source: str = Field(min_length=1)
    version: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)


class WorkflowRunCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    state: str = Field(min_length=1)
    status: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    adapter: str = Field(min_length=1)
    autonomy_level: str = Field(pattern=r"^L[0-4]$")
    started_at: datetime
    eta: str = Field(min_length=1)
    blocker: str | None = None
    objective: str = Field(min_length=1)
    current_step: str = Field(min_length=1)
    related_risk: str = Field(min_length=1)
    related_assets: list[str] = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    proposed_outputs: list[str] = Field(min_length=1)
    pending_signals: list[dict] = Field(default_factory=list)
    controls: list[str] = Field(min_length=1)
    audit_scope: str = Field(min_length=1)
    replay_ready: bool = False


class WorkflowTimelineEventCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    event: str = Field(min_length=1)
    occurred_at: datetime
    actor: str = Field(min_length=1)
    result: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class WorkflowApprovalDecisionUpdate(BaseModel):
    tenant_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)


class WorkflowActionRunUpdate(BaseModel):
    tenant_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    action_run_id: UUID
    idempotency_key: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    workflow_signal_status: str = Field(min_length=1)
    requires_approval: bool
    approval_id: str | None = None


class WorkflowActionRunOutcomeUpdate(BaseModel):
    tenant_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    action_run_id: UUID
    idempotency_key: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    result_summary: str = Field(min_length=1)


class ReplaySimulationOutputCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    simulation_output_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: str = Field(default="persisted", min_length=1)
    requested_by: str = Field(min_length=1)
    required_scope: str = Field(default="simulation:replay:persist", min_length=1)
    replay_mode: str = Field(min_length=1)
    determinism_status: str = Field(min_length=1)
    output_hash: str = Field(min_length=1)
    retention_window_days: int = Field(ge=1)
    permission_decision: dict = Field(default_factory=dict)
    artifact_payload: dict = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="simulation.replay_output.persisted", min_length=1)
    reason: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)


class ConnectorConfigurationCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    status: str = Field(default="configured_preview_only", min_length=1)
    sync_mode: str = Field(default="preview", min_length=1)
    runtime_boundary: str = Field(default="axis-connector-sandbox", min_length=1)
    created_by: str = Field(min_length=1)
    configuration_payload: dict = Field(default_factory=dict)
    credential_ref_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ConnectorManifestCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    revision_number: int = Field(ge=1)
    display_name: str = Field(min_length=1)
    connector_type: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: str = Field(default="registered_preview_only", min_length=1)
    runtime_boundary: str = Field(default="axis-connector-sandbox", min_length=1)
    registered_by: str = Field(min_length=1)
    manifest_payload: dict = Field(default_factory=dict)
    runtime_policy: dict = Field(default_factory=dict)
    preview_sample: dict | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="connector.manifest.registered", min_length=1)
    revises_revision_number: int | None = None
    replaced_by_revision_number: int | None = None
    revision_idempotency_key: str | None = None
    notes: list[str] = Field(default_factory=list)


class ConnectorManifestLifecycleUpdate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(
        default="connector.manifest.lifecycle_transitioned",
        min_length=1,
    )
    note: str = Field(min_length=1)


class ConnectorLifecycleEventCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    from_status: str = Field(min_length=1)
    target_status: str = Field(min_length=1)
    transitioned_by: str = Field(min_length=1)
    transition_reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    audit_event_id: UUID
    audit_event_type: str = Field(min_length=1)


class ConnectorSourceBindingCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    binding_id: str = Field(min_length=1, max_length=180)
    connection_profile_id: str = Field(min_length=1, max_length=180)
    resource_name: str = Field(min_length=1, max_length=240)
    schema_fingerprint: str = Field(min_length=64, max_length=64)
    schema_fingerprint_version: str = "column_names_v1"
    supersedes_binding_id: str | None = None
    credential_lease_id: str = Field(min_length=1, max_length=180)
    egress_policy_id: str = Field(min_length=1, max_length=180)
    ingestion_status: str = Field(min_length=1, max_length=60)
    activated_by: str = Field(min_length=1, max_length=160)
    activation_reason: str = Field(min_length=1, max_length=600)
    audit_event_id: UUID
    audit_event_type: str = Field(min_length=1)


class ConnectorSourceIngestionRequestCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1, max_length=180)
    requested_by: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=600)
    stage: str = Field(default="validate", pattern="^(validate|extract)$")
    # ID/fingerprint pairs pinned by the domain layer from the active bindings;
    # never credential material.
    selections: list[dict]
    audit_event_id: UUID
    audit_event_type: str = Field(min_length=1)


class ConnectorSourceExtractionBatchCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1, max_length=180)
    batch_key: str = Field(min_length=1, max_length=240)
    binding_id: str = Field(min_length=1, max_length=180)
    resource_name: str = Field(min_length=1, max_length=240)
    pinned_schema_fingerprint: str = Field(min_length=64, max_length=64)
    observed_schema_fingerprint: str = Field(min_length=64, max_length=64)
    ordering_mode: str = Field(pattern="^(primary_key|none)$")
    cursor_watermark: dict | None = None
    row_count: int = Field(ge=0)
    byte_size: int = Field(ge=0)
    truncated: bool
    limit_reason: str | None = None
    duration_ms: int = Field(ge=0)
    limits_applied: dict
    provenance: dict
    digest_sha256: str = Field(min_length=64, max_length=64)
    storage_adapter: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)
    storage_uri: str = Field(min_length=1)
    content_type: str = Field(min_length=1)
    stored_size_bytes: int = Field(ge=0)
    classification: str = Field(min_length=1, max_length=40)
    executed_by: str = Field(min_length=1, max_length=160)
    audit_event_id: UUID
    audit_event_type: str = Field(min_length=1)


class ConnectorSourceBatchExportRequestCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1, max_length=180)
    export_request_id: str = Field(min_length=1, max_length=180)
    idempotency_key: str = Field(min_length=1, max_length=200)
    requested_by: str = Field(min_length=1, max_length=160)
    owner_role: str = Field(min_length=1, max_length=160)
    risk_level: str = Field(min_length=1, max_length=40)
    approval_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    export_reason: str = Field(min_length=1, max_length=240)
    status: str = Field(default="approval_required", min_length=1)
    export_status: str = Field(default="not_exported", min_length=1)
    storage_status: str = Field(default="not_written", min_length=1)
    batch_count: int = Field(ge=0)
    total_row_count: int = Field(ge=0)
    envelope_checksum_sha256: str = Field(min_length=64, max_length=64)
    redaction_policy: str = Field(default="source-batch-envelope-public-safe", min_length=1)
    controls: list[str] = Field(default_factory=list)
    permission_decision: dict = Field(default_factory=dict)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(
        default="connector.source.batch_export.requested",
        min_length=1,
    )
    notes: list[str] = Field(default_factory=list)


class ConnectorSourceBatchExportDecisionRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    export_request_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    export_status: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    decision_actor_id: str = Field(min_length=1)
    decision_note: str | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None


class ConnectorSourceBatchExportMaterializationRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    export_request_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    export_status: str = Field(min_length=1)
    storage_status: str = Field(min_length=1)
    materialization_id: str = Field(min_length=1)
    materialization_idempotency_key: str = Field(min_length=1)
    materialized_by: str = Field(min_length=1)
    materialization_reason: str = Field(min_length=1)
    storage_adapter: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)
    storage_uri: str = Field(min_length=1)
    artifact_checksum_sha256: str = Field(min_length=64, max_length=64)
    artifact_size_bytes: int = Field(ge=0)
    artifact_content_type: str = Field(min_length=1)
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None


class DataAssetStewardshipCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    revision_number: int = Field(ge=1)
    owner: str = Field(min_length=1, max_length=200)
    classification: str = Field(min_length=1, max_length=40)
    residency: str = Field(min_length=1, max_length=80)
    retention: str = Field(min_length=1, max_length=80)
    declared_by: str = Field(min_length=1)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="data.stewardship.declared", min_length=1)
    revises_revision_number: int | None = None
    replaced_by_revision_number: int | None = None
    revision_idempotency_key: str | None = None
    notes: list[str] = Field(default_factory=list)


ObservationSourceKind = Literal["csv_preview", "postgres_discovery", "s3_object_discovery"]
"""The governed boundary an observation was actually seen through.

Extending this set is deliberate: each new kind is a distinct evidence
provenance the catalog and audit consumers must understand.
"""


class DataResourceObservationCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    resource_name: str = Field(min_length=1, max_length=240)
    schema_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    schema_fingerprint_version: str = "column_names_v1"
    drift_state: str = Field(min_length=1, max_length=20)
    observed_by: str = Field(min_length=1)
    source_kind: ObservationSourceKind = Field(default="csv_preview", max_length=40)
    audit_event_type: str = Field(default="data.resource.observed", min_length=1)


class DataAssetContractCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    revision_number: int = Field(ge=1)
    expected_resource_name: str = Field(min_length=1, max_length=240)
    expected_schema_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    freshness_warn_hours: int | None = Field(default=None, ge=1)
    freshness_fail_hours: int | None = Field(default=None, ge=1)
    notes: list[str] = Field(default_factory=list)
    declared_by: str = Field(min_length=1)
    audit_event_type: str = Field(default="data.contract.declared", min_length=1)
    revises_revision_number: int | None = None
    replaced_by_revision_number: int | None = None
    revision_idempotency_key: str | None = None


class ConnectorCredentialHandleCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    handle_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    status: str = Field(default="active", min_length=1)
    secret_provider: str = Field(min_length=1)
    secret_ref: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    rotation_interval_days: int = Field(ge=1, le=3660)
    last_rotated_at: datetime | None = None
    next_rotation_due_at: datetime | None = None
    created_by: str = Field(min_length=1)
    labels: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ConnectorCredentialRotationCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    handle_id: str = Field(min_length=1)
    rotated_by: str = Field(min_length=1)
    rotated_at: datetime
    evidence_ref: str = Field(min_length=1)
    status: str = Field(default="rotated", min_length=1)
    notes: list[str] = Field(default_factory=list)


class ConnectorCredentialLeasePermissionDecision(BaseModel):
    """The persisted shape of one credential-broker authorization decision.

    Mirrors ``PermissionDecision`` so every reader (API registry, console
    contracts) can rely on ``allowed`` being a boolean and ``reason`` always
    naming why. Enforced at the write boundary: a lease row that could not
    satisfy this must never be persisted, because the read model rejects it
    and any registry query would fail as a whole.
    """

    allowed: bool
    reason: str = Field(min_length=1)


class ConnectorCredentialLeaseCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    handle_id: str = Field(min_length=1)
    lease_id: str = Field(min_length=1)
    status: str = Field(default="active", min_length=1)
    lease_mode: str = Field(default="deferred_vault_kms_lease", min_length=1)
    runtime_boundary: str = Field(default="axis-credential-lease-broker", min_length=1)
    requested_by: str = Field(min_length=1)
    lease_purpose: str = Field(min_length=1)
    secret_provider: str = Field(min_length=1)
    secret_ref: str = Field(min_length=1)
    vault_kms_policy: dict[str, str] = Field(default_factory=dict)
    permission_decision: ConnectorCredentialLeasePermissionDecision
    # String-valued by contract: the runtime result is public-safe evidence
    # rendered verbatim by API and console readers; booleans here broke the
    # read model before this was enforced at the write boundary.
    lease_result: dict[str, str] = Field(default_factory=dict)
    granted_at: datetime
    expires_at: datetime
    renewal_due_at: datetime
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="connector.credential_lease.requested", min_length=1)
    notes: list[str] = Field(default_factory=list)


class ConnectorCredentialLeaseRenewalRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    lease_id: str = Field(min_length=1)
    renewed_by: str = Field(min_length=1)
    renewed_at: datetime
    expires_at: datetime
    renewal_due_at: datetime
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="connector.credential_lease.renewed", min_length=1)
    lease_result: dict = Field(default_factory=dict)
    note: str | None = None


class ConnectorCredentialLeaseRevocationRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    lease_id: str = Field(min_length=1)
    revoked_by: str = Field(min_length=1)
    revoked_at: datetime
    revocation_reason: str = Field(min_length=1)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="connector.credential_lease.revoked", min_length=1)
    lease_result: dict = Field(default_factory=dict)


class ConnectorEgressPolicyCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    status: str = Field(default="active", min_length=1)
    connection_profile_id: str = Field(min_length=1)
    egress_boundary: str = Field(min_length=1)
    policy_mode: str = Field(min_length=1)
    runtime_boundary: str = Field(default="axis-egress-policy-enforcer", min_length=1)
    private_endpoint_ref: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
    policy_document: dict = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="connector.egress_policy.registered", min_length=1)
    notes: list[str] = Field(default_factory=list)


class ConnectorRunCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    status: str = Field(default="recorded_preview_only", min_length=1)
    execution_mode: str = Field(default="preview", min_length=1)
    runtime_boundary: str = Field(default="axis-connector-sandbox", min_length=1)
    requested_by: str = Field(min_length=1)
    credential_handle_ids: list[str] = Field(default_factory=list)
    input_summary: dict = Field(default_factory=dict)
    result_summary: dict = Field(default_factory=dict)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="connector.run.recorded", min_length=1)
    notes: list[str] = Field(default_factory=list)


class ConnectorRunUpdateRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    result_summary: dict = Field(default_factory=dict)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="connector.run.recorded", min_length=1)
    notes: list[str] | None = None


class ConnectorSyncCheckpointCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    checkpoint_type: str = Field(min_length=1)
    status: str = Field(default="checkpoint_recorded", min_length=1)
    sequence: int = Field(ge=0)
    runtime_boundary: str = Field(min_length=1)
    adapter: str = Field(min_length=1)
    cursor: dict = Field(default_factory=dict)
    result_summary: dict = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(
        default="connector.run.sync_checkpoint.recorded",
        min_length=1,
    )
    notes: list[str] = Field(default_factory=list)


class ConnectorSyncCheckpointClaimCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    status: str = Field(default="claimed", min_length=1)
    claimed_by: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    lease_duration_seconds: int = Field(ge=1)
    lease_expires_at: datetime
    claim_result: dict = Field(default_factory=dict)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(
        default="connector.run.sync_checkpoint_claimed",
        min_length=1,
    )
    notes: list[str] = Field(default_factory=list)


class ConnectorSyncCheckpointClaimRenewalRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    renewed_by: str = Field(min_length=1)
    renewed_at: datetime
    lease_duration_seconds: int = Field(ge=1)
    lease_expires_at: datetime
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(
        default="connector.run.sync_checkpoint_claim_renewed",
        min_length=1,
    )
    note: str | None = None


class ConnectorSyncCheckpointClaimReleaseRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    released_by: str = Field(min_length=1)
    released_at: datetime
    release_reason: str = Field(min_length=1)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(
        default="connector.run.sync_checkpoint_claim_released",
        min_length=1,
    )
    note: str | None = None


class ConnectorSyncCheckpointClaimExpirationRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    expired_at: datetime
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(
        default="connector.run.sync_checkpoint_claim_expired",
        min_length=1,
    )
    note: str | None = None


class ConnectorOntologyProposalCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    source_run_id: str | None = None
    source_file_name: str = Field(min_length=1)
    mapping_profile: str = Field(min_length=1)
    status: str = Field(default="proposed_from_preview", min_length=1)
    write_mode: str = Field(default="proposal_only", min_length=1)
    graph_mutation_status: str = Field(default="not_applied", min_length=1)
    proposed_by: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    node_type: str = Field(min_length=1)
    ontology_type: str = Field(min_length=1)
    field_summary: dict = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    promotion_id: str | None = None
    policy_id: str | None = None
    policy_set_id: str | None = None
    policy_ids: list[str] | None = None
    policy_decision: dict | None = None
    promoted_by: str | None = None
    ontology_mutation: dict | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="connector.ontology_proposals.recorded", min_length=1)
    notes: list[str] = Field(default_factory=list)


class ConnectorOntologyPromotionCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    promotion_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    manual_import_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    promotion_mode: str = Field(default="approved_manual_import", min_length=1)
    requested_by: str = Field(min_length=1)
    graph_mutation_status: str = Field(min_length=1)
    ontology_mutation: dict = Field(default_factory=dict)
    permission_decision: dict = Field(default_factory=dict)
    policy_id: str | None = None
    policy_set_id: str | None = None
    policy_ids: list[str] | None = None
    policy_decision: dict | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="connector.ontology_promotion.applied", min_length=1)
    notes: list[str] = Field(default_factory=list)


class ConnectorOntologyPromotionResultRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    graph_mutation_status: str = Field(min_length=1)
    promotion_id: str = Field(min_length=1)
    promoted_by: str = Field(min_length=1)
    ontology_mutation: dict = Field(default_factory=dict)
    policy_id: str | None = None
    policy_set_id: str | None = None
    policy_ids: list[str] | None = None
    policy_decision: dict | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None


class ConnectorPromotionPolicyCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    status: str = Field(default="draft", min_length=1)
    enforcement_mode: str = Field(default="advisory", min_length=1)
    created_by: str = Field(min_length=1)
    required_authoring_scope: str = Field(
        default="connectors:promotion_policy:author",
        min_length=1,
    )
    required_scopes: list[str] = Field(min_length=1)
    required_manual_import_status: str = Field(min_length=1)
    required_workflow_signal_status: str = Field(min_length=1)
    allowed_risk_levels: list[str] = Field(min_length=1)
    allowed_ontology_types: list[str] = Field(min_length=1)
    review_window_hours: int = Field(ge=1, le=24 * 30)
    permission_decision: dict = Field(default_factory=dict)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="connector.promotion_policy.authored", min_length=1)
    revises_policy_id: str | None = None
    replaced_by_policy_id: str | None = None
    revision_idempotency_key: str | None = None
    revision_approval_id: str | None = None
    revision_decision: str | None = None
    revision_workflow_signal_status: str | None = None
    notes: list[str] = Field(default_factory=list)


class ConnectorPromotionPolicyEnableRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    status: str = Field(default="enabled", min_length=1)
    enforcement_mode: str = Field(default="required", min_length=1)
    permission_decision: dict = Field(default_factory=dict)
    audit_event_id: UUID
    audit_event_type: str = Field(default="connector.promotion_policy.enabled", min_length=1)
    note: str | None = None


class ConnectorPromotionPolicySetCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    policy_set_id: str = Field(min_length=1)
    policy_set_version: str = Field(min_length=1)
    status: str = Field(default="active", min_length=1)
    activated_by: str = Field(min_length=1)
    activation_scope: str = Field(
        default="connectors:promotion_policy_set:activate",
        min_length=1,
    )
    policy_ids: list[str] = Field(min_length=1)
    permission_decision: dict = Field(default_factory=dict)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(
        default="connector.promotion_policy_set.activated",
        min_length=1,
    )
    activation_reason: str = Field(min_length=1)
    replaces_policy_set_id: str | None = None
    replaced_by_policy_set_id: str | None = None
    replacement_approval_id: str | None = None
    replacement_decision: str | None = None
    replacement_workflow_signal_status: str | None = None
    replaced_at: datetime | None = None
    rollback_to_policy_set_id: str | None = None
    rollback_approval_id: str | None = None
    rollback_decision: str | None = None
    rollback_workflow_signal_status: str | None = None
    policy_revision_adoptions: list[dict] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PlatformPolicyCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    revision_number: int = Field(ge=1)
    policy_version: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    effect: str = Field(min_length=1)
    conditions: dict = Field(default_factory=dict)
    status: str = Field(default="active", min_length=1)
    created_by: str = Field(min_length=1)
    required_authoring_scope: str = Field(default="platform:policy:author", min_length=1)
    permission_decision: dict = Field(default_factory=dict)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="platform.policy.authored", min_length=1)
    revises_revision_number: int | None = None
    replaced_by_revision_number: int | None = None
    revision_idempotency_key: str | None = None
    notes: list[str] = Field(default_factory=list)


class TenantCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(default="")
    status: str = Field(default="active", min_length=1)
    created_by: str = Field(min_length=1)
    bootstrap_admin_actor_id: str | None = None
    provision_idempotency_key: str | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="platform.tenant.provisioned", min_length=1)
    notes: list[str] = Field(default_factory=list)


class TenantLifecycleTransition(BaseModel):
    tenant_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    reason: str | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)


class TenantQuotaUpsert(BaseModel):
    tenant_id: str = Field(min_length=1)
    quota_key: str = Field(min_length=1)
    quota_value: int = Field(ge=0)
    updated_by: str = Field(min_length=1)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="platform.tenant.quota.updated", min_length=1)
    notes: list[str] = Field(default_factory=list)


class TenantUsageAdd(BaseModel):
    """A single consumption delta to fold into the (tenant, metric, period) row."""

    tenant_id: str = Field(min_length=1)
    metric_key: str = Field(min_length=1)
    period_start: datetime
    period_window_seconds: int = Field(ge=60, le=86_400)
    quantity: int = Field(ge=0)
    first_occurred_at: datetime
    last_occurred_at: datetime


class TenantUsageEventAppend(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    tenant_id: str = Field(min_length=1, max_length=80)
    metric_key: str = Field(min_length=1, max_length=60)
    source_type: str = Field(min_length=1, max_length=60)
    source_id: str = Field(min_length=1, max_length=220)
    period_start: datetime
    period_window_seconds: int = Field(ge=60, le=86_400)
    quantity: int = Field(gt=0)
    occurred_at: datetime
    dimensions: dict = Field(default_factory=dict)


class TenantUsagePeriodTotal(BaseModel):
    metric_key: str
    period_start: datetime
    quantity: int


class TenantUsageProjectionResult(BaseModel):
    events_projected: int = Field(ge=0)
    quantity_projected: int = Field(ge=0)


class AgentRunCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: str = Field(default="requested", min_length=1)
    mode: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    autonomy_level: str = Field(min_length=1)
    request_fingerprint: dict = Field(default_factory=dict)
    context_refs: list[str] = Field(default_factory=list)
    model_invocation_ids: list[str] = Field(default_factory=list)
    permission_decision: dict = Field(default_factory=dict)
    platform_policy_decision: dict | None = None
    notes: list[str] = Field(default_factory=list)


class AgentRunResultRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    run_id: UUID
    status: str = Field(min_length=1)
    context_refs: list[str] | None = None
    model_invocation_ids: list[str] | None = None
    proposed_action_run_id: UUID | None = None
    proposal_payload: dict | None = None
    error_reason: str | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None
    notes: list[str] | None = None


class AgentRunStepCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    run_id: UUID
    seq: int = Field(ge=1)
    step_type: str = Field(min_length=1)
    status: str = Field(min_length=1)
    evidence: dict = Field(default_factory=dict)


class ActorCreate(BaseModel):
    actor_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    actor_type: str = Field(default="human", min_length=1)


class ConnectorManualImportRequestCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    import_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: str = Field(default="approval_required", min_length=1)
    import_mode: str = Field(default="manual_import_request", min_length=1)
    requested_by: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    risk_level: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    proposal_ids: list[str] = Field(min_length=1)
    import_summary: dict = Field(default_factory=dict)
    controls: list[str] = Field(default_factory=list)
    graph_mutation_status: str = Field(default="not_applied", min_length=1)
    workflow_signal_status: str = Field(default="pending_approval_decision", min_length=1)
    decision: str | None = None
    decision_actor_id: str | None = None
    decision_note: str | None = None
    workflow_signal: dict | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="connector.manual_import.requested", min_length=1)
    notes: list[str] = Field(default_factory=list)


class ConnectorEvidenceSnapshotExportRequestCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    export_request_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: str = Field(default="approval_required", min_length=1)
    export_status: str = Field(default="not_exported", min_length=1)
    storage_status: str = Field(default="not_written", min_length=1)
    requested_by: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    risk_level: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    connector_id: str | None = None
    snapshot_id: str | None = None
    snapshot_idempotency_key: str | None = None
    export_reason: str = Field(min_length=1)
    format: str = Field(default="json", min_length=1)
    limit: int = Field(ge=1)
    requested_snapshot_count: int = Field(ge=0)
    snapshot_checksum_sha256: str = Field(min_length=64, max_length=64)
    redaction_policy: str = Field(default="connector-snapshot-public-safe", min_length=1)
    controls: list[str] = Field(default_factory=list)
    permission_decision: dict = Field(default_factory=dict)
    workflow_signal_status: str = Field(default="pending_approval_decision", min_length=1)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(
        default="connector.evidence_snapshot_export.requested",
        min_length=1,
    )
    notes: list[str] = Field(default_factory=list)


class ConnectorEvidenceSnapshotExportRequestDecisionRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    export_request_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    export_status: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    decision_actor_id: str = Field(min_length=1)
    decision_note: str | None = None
    workflow_signal_status: str = Field(min_length=1)
    workflow_signal: dict = Field(default_factory=dict)
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None


class ConnectorEvidenceSnapshotExportMaterializationRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    export_request_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    export_status: str = Field(min_length=1)
    storage_status: str = Field(min_length=1)
    materialization_id: str = Field(min_length=1)
    materialization_idempotency_key: str = Field(min_length=1)
    materialized_by: str = Field(min_length=1)
    materialization_reason: str = Field(min_length=1)
    storage_adapter: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)
    storage_uri: str = Field(min_length=1)
    artifact_checksum_sha256: str = Field(min_length=64, max_length=64)
    artifact_size_bytes: int = Field(ge=0)
    artifact_content_type: str = Field(min_length=1)
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None


class ConnectorManualImportDecisionRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    import_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    decision_actor_id: str = Field(min_length=1)
    decision_note: str | None = None
    workflow_signal_status: str = Field(min_length=1)
    workflow_signal: dict = Field(default_factory=dict)
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None


class ManufacturingOperationRecordCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    record_type: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    status: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    occurred_at: datetime
    payload: dict = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    related_asset: str | None = None
    workflow_id: str | None = None
    risk_level: str | None = None


class ManufacturingDailyBriefCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    brief_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    brief_date: str = Field(min_length=1)
    status: str = Field(default="generated", min_length=1)
    requested_by: str = Field(min_length=1)
    required_scopes: list[str] = Field(min_length=1)
    source_record_ids: list[str] = Field(min_length=1)
    summary_payload: dict = Field(default_factory=dict)
    permission_decision: dict = Field(default_factory=dict)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(default="manufacturing.daily_brief.generated", min_length=1)


class ManufacturingRiskScenarioCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    status: str = Field(default="generated", min_length=1)
    risk_level: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    workflow_ids: list[str] = Field(default_factory=list)
    source_record_ids: list[str] = Field(min_length=1)
    scenario_payload: dict = Field(default_factory=dict)
    permission_decision: dict = Field(default_factory=dict)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(
        default="manufacturing.risk_scenario.generated",
        min_length=1,
    )


class PlatformNotificationAcknowledgementCreate(BaseModel):
    tenant_id: str = Field(min_length=1)
    notification_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    state: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=600)
    source: str = Field(min_length=1)
    notification_title: str = Field(min_length=1)
    notification_category: str = Field(min_length=1)
    notification_severity: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(
        default="platform.notification.acknowledged",
        min_length=1,
    )
    acknowledged_at: datetime


class OidcBrowserSessionCreate(BaseModel):
    session_id_hash: str = Field(min_length=32, max_length=128)
    tenant_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime
    absolute_expires_at: datetime | None = None
    refresh_token_ciphertext: str | None = None
    refresh_count: int = Field(default=0, ge=0)
    user_agent: str | None = Field(default=None, max_length=256)
    client_ip: str | None = Field(default=None, max_length=64)
    device_label: str | None = Field(default=None, max_length=80)
    created_audit_event_id: UUID | None = None


class OidcBrowserSessionRevocation(BaseModel):
    session_id_hash: str = Field(min_length=32, max_length=128)
    revoked_by: str = Field(min_length=1)
    revocation_reason: str = Field(min_length=1)
    revoke_audit_event_id: UUID | None = None


class AxisPersistenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._models: ModelPersistencePort = ModelRepository(session)

    def defer_until_after_commit(self, callback: Callable[[], None]) -> None:
        """Run a process-local side effect only after this transaction commits."""

        callbacks = self.session.info.setdefault("axis_after_commit_callbacks", [])
        callbacks.append(callback)

    def run_after_commit_callbacks(self) -> None:
        """Drain callbacks registered by a successfully committed request."""

        callbacks = self.session.info.pop("axis_after_commit_callbacks", [])
        for callback in callbacks:
            callback()

    def _insert_with_on_conflict(self, model: type):
        """Return a dialect-aware INSERT that supports on_conflict_do_nothing.

        Both the Postgres production engine and the SQLite test engine expose an
        on-conflict insert; the generic core insert does not, so callers that
        need insert-or-ignore semantics must build the statement here.
        """
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "postgresql":
            return postgresql_insert(model)
        if dialect_name == "sqlite":
            return sqlite_insert(model)
        raise NotImplementedError(
            f"on_conflict insert is not supported for dialect {dialect_name!r}."
        )

    def append_audit_event(self, event: AuditEventCreate) -> AuditEvent:
        audit_event = AuditEvent(
            tenant_id=event.tenant_id,
            actor_id=event.actor_id,
            event_type=event.event_type,
            payload=event.payload,
        )
        self.session.add(audit_event)
        self.session.flush()
        return audit_event

    def acquire_oidc_session_admission_lock(
        self,
        *,
        tenant_id: str,
        actor_id: str,
    ) -> None:
        """Serialize browser-session admission for one tenant principal.

        PostgreSQL advisory transaction locks coordinate across API processes
        and replicas without persisting lock rows. The length-prefixed key keeps
        tenant and actor boundaries unambiguous. SQLite serializes writes at the
        database level and is used only by local/test profiles, so it needs no
        additional lock primitive here.
        """
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "sqlite":
            return
        if dialect_name != "postgresql":
            raise NotImplementedError(
                f"OIDC session admission locking is not supported for dialect {dialect_name!r}."
            )
        lock_key = (
            f"axis:oidc-session-admission:{len(tenant_id)}:{tenant_id}{len(actor_id)}:{actor_id}"
        )
        self.session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))

    def get_audit_event(self, tenant_id: str, audit_event_id: UUID) -> AuditEvent | None:
        statement: Select[tuple[AuditEvent]] = select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.id == audit_event_id,
        )
        return self.session.scalar(statement)

    def create_oidc_browser_session(
        self,
        record: OidcBrowserSessionCreate,
    ) -> OidcBrowserSession:
        browser_session = OidcBrowserSession(
            session_id_hash=record.session_id_hash,
            tenant_id=record.tenant_id,
            actor_id=record.actor_id,
            status="active",
            scopes=record.scopes,
            expires_at=record.expires_at,
            absolute_expires_at=record.absolute_expires_at,
            refresh_token_ciphertext=record.refresh_token_ciphertext,
            refresh_count=record.refresh_count,
            user_agent=record.user_agent,
            client_ip=record.client_ip,
            device_label=record.device_label,
            created_audit_event_id=record.created_audit_event_id,
        )
        self.session.add(browser_session)
        self.session.flush()
        return browser_session

    def get_oidc_browser_session_by_hash(
        self,
        session_id_hash: str,
    ) -> OidcBrowserSession | None:
        statement: Select[tuple[OidcBrowserSession]] = select(OidcBrowserSession).where(
            OidcBrowserSession.session_id_hash == session_id_hash
        )
        return self.session.scalar(statement)

    def get_oidc_browser_session(
        self,
        tenant_id: str,
        session_ref: UUID,
    ) -> OidcBrowserSession | None:
        statement: Select[tuple[OidcBrowserSession]] = select(OidcBrowserSession).where(
            OidcBrowserSession.tenant_id == tenant_id,
            OidcBrowserSession.id == session_ref,
        )
        return self.session.scalar(statement)

    def get_oidc_browser_session_for_update(
        self,
        tenant_id: str,
        session_ref: UUID,
    ) -> OidcBrowserSession | None:
        """Lock a tenant-scoped session for a terminal state transition.

        The lock makes reference-based revocation linearizable with refresh
        finalization on PostgreSQL: whichever transaction obtains the row first
        determines whether the session is revoked or already rotated.
        """
        statement: Select[tuple[OidcBrowserSession]] = (
            select(OidcBrowserSession)
            .where(
                OidcBrowserSession.tenant_id == tenant_id,
                OidcBrowserSession.id == session_ref,
            )
            .with_for_update()
        )
        return self.session.scalar(statement)

    def get_oidc_browser_session_by_row_id(
        self,
        session_row_id: UUID,
    ) -> OidcBrowserSession | None:
        """Reload a session by primary key (used by the scheduled sweep to
        re-check a candidate's status inside its own revoke transaction)."""
        return self.session.get(OidcBrowserSession, session_row_id)

    def list_oidc_browser_sessions(
        self,
        tenant_id: str,
        actor_id: str | None = None,
        cursor_created_at: datetime | None = None,
        cursor_row_id: UUID | None = None,
        limit: int = 100,
    ) -> list[OidcBrowserSession]:
        statement: Select[tuple[OidcBrowserSession]] = select(OidcBrowserSession).where(
            OidcBrowserSession.tenant_id == tenant_id
        )
        if actor_id is not None:
            statement = statement.where(OidcBrowserSession.actor_id == actor_id)
        if cursor_created_at is not None and cursor_row_id is not None:
            # Newest-first keyset continuation: resume strictly after the
            # cursor row in (created_at desc, id desc) order.
            statement = statement.where(
                or_(
                    OidcBrowserSession.created_at < cursor_created_at,
                    and_(
                        OidcBrowserSession.created_at == cursor_created_at,
                        OidcBrowserSession.id < cursor_row_id,
                    ),
                )
            )
        statement = statement.order_by(
            OidcBrowserSession.created_at.desc(),
            OidcBrowserSession.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def list_active_oidc_browser_sessions(
        self,
        tenant_id: str,
        actor_id: str,
    ) -> list[OidcBrowserSession]:
        statement: Select[tuple[OidcBrowserSession]] = (
            select(OidcBrowserSession)
            .where(
                OidcBrowserSession.tenant_id == tenant_id,
                OidcBrowserSession.actor_id == actor_id,
                OidcBrowserSession.status == "active",
            )
            .order_by(
                OidcBrowserSession.created_at.asc(),
                OidcBrowserSession.id.asc(),
            )
        )
        return list(self.session.scalars(statement))

    def touch_oidc_browser_session(
        self,
        session_id_hash: str,
        seen_at: datetime,
    ) -> OidcBrowserSession | None:
        browser_session = self.get_oidc_browser_session_by_hash(session_id_hash)
        if browser_session is None:
            return None
        browser_session.last_seen_at = seen_at
        browser_session.updated_at = seen_at
        self.session.flush()
        return browser_session

    def claim_oidc_browser_session_refresh(
        self,
        session_id_hash: str,
    ) -> bool:
        """Atomically transition an active session into the refreshing state.

        Only one caller can win the ``active`` -> ``refreshing`` transition, so
        concurrent refreshes with the same cookie serialize and cannot both mint
        a child session. Returns ``True`` for the winning caller and ``False``
        when the session was already claimed, rotated or revoked.
        """
        now = utc_now()
        statement = (
            update(OidcBrowserSession)
            .where(
                OidcBrowserSession.session_id_hash == session_id_hash,
                OidcBrowserSession.status == "active",
            )
            .values(status="refreshing", updated_at=now)
        )
        result = self.session.execute(statement)
        self.session.flush()
        return bool(result.rowcount)

    def release_oidc_browser_session_refresh(
        self,
        session_id_hash: str,
    ) -> OidcBrowserSession | None:
        """Return a claimed session to the active state (refresh aborted)."""
        browser_session = self.get_oidc_browser_session_by_hash(session_id_hash)
        if browser_session is None or browser_session.status != "refreshing":
            return browser_session
        now = utc_now()
        browser_session.status = "active"
        browser_session.updated_at = now
        self.session.flush()
        return browser_session

    def finalize_oidc_browser_session_refresh(
        self,
        *,
        session_id_hash: str,
        rotated_to_session_id_hash: str,
    ) -> bool:
        """Atomically rotate a session only while its refresh claim is live.

        Logout, administrative revocation and the orphan sweep may revoke a
        session while the IdP exchange is in flight. The conditional update
        prevents that terminal decision from being overwritten and stops the
        refresh caller from minting a replacement session after revocation.
        """
        now = utc_now()
        statement = (
            update(OidcBrowserSession)
            .where(
                OidcBrowserSession.session_id_hash == session_id_hash,
                OidcBrowserSession.status == "refreshing",
            )
            .values(
                status="rotated",
                rotated_to_session_id_hash=rotated_to_session_id_hash,
                refresh_token_ciphertext=None,
                updated_at=now,
            )
        )
        result = self.session.execute(statement)
        self.session.flush()
        return bool(result.rowcount)

    def revoke_oidc_browser_session(
        self,
        record: OidcBrowserSessionRevocation,
    ) -> OidcBrowserSession | None:
        browser_session = self.get_oidc_browser_session_by_hash(record.session_id_hash)
        if browser_session is None:
            return None
        if browser_session.status == "revoked":
            return browser_session
        now = utc_now()
        browser_session.status = "revoked"
        browser_session.revoked_at = now
        browser_session.revoked_by = record.revoked_by
        browser_session.revocation_reason = record.revocation_reason
        browser_session.revoke_audit_event_id = record.revoke_audit_event_id
        # At-rest data minimization: a revoked session can never refresh, so
        # drop the encrypted refresh credential, mirroring the rotation path.
        browser_session.refresh_token_ciphertext = None
        browser_session.updated_at = now
        self.session.flush()
        return browser_session

    def list_orphaned_refreshing_oidc_browser_sessions(
        self,
        *,
        claim_deadline: datetime,
        tenant_id: str | None = None,
        limit: int = 200,
    ) -> list[OidcBrowserSession]:
        """Return sessions stuck in ``refreshing`` past the claim staleness window.

        A refresh claim is normally resolved (rotated or revoked) within one IdP
        exchange. A row whose ``updated_at`` is older than ``claim_deadline`` means
        the refreshing process crashed between claim and completion, so the row is
        an orphan that the request path only recovers lazily on re-presentation.
        """
        statement: Select[tuple[OidcBrowserSession]] = select(OidcBrowserSession).where(
            OidcBrowserSession.status == "refreshing",
            OidcBrowserSession.updated_at <= claim_deadline,
        )
        if tenant_id is not None:
            statement = statement.where(OidcBrowserSession.tenant_id == tenant_id)
        statement = statement.order_by(
            OidcBrowserSession.updated_at.asc(),
            OidcBrowserSession.id.asc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def list_expired_active_oidc_browser_sessions(
        self,
        *,
        now: datetime,
        idle_deadline: datetime | None = None,
        tenant_id: str | None = None,
        limit: int = 200,
    ) -> list[OidcBrowserSession]:
        """Return active sessions past their absolute/idle expiry that still linger.

        The request path expires these lazily on presentation; without a sweep, a
        session that is never presented again stays ``active`` at rest forever. A
        row qualifies when its sliding ``expires_at`` has passed, its
        ``absolute_expires_at`` has passed, or its last activity is older than
        ``idle_deadline`` (when idle timeout is enabled).
        """
        expiry_clauses = [
            OidcBrowserSession.expires_at <= now,
            and_(
                OidcBrowserSession.absolute_expires_at.is_not(None),
                OidcBrowserSession.absolute_expires_at <= now,
            ),
        ]
        if idle_deadline is not None:
            expiry_clauses.append(
                func.coalesce(
                    OidcBrowserSession.last_seen_at,
                    OidcBrowserSession.created_at,
                )
                <= idle_deadline
            )
        statement: Select[tuple[OidcBrowserSession]] = select(OidcBrowserSession).where(
            OidcBrowserSession.status == "active",
            or_(*expiry_clauses),
        )
        if tenant_id is not None:
            statement = statement.where(OidcBrowserSession.tenant_id == tenant_id)
        statement = statement.order_by(
            OidcBrowserSession.created_at.asc(),
            OidcBrowserSession.id.asc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def list_audit_events(
        self,
        tenant_id: str,
        event_type: str | None = None,
        actor_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        statement: Select[tuple[AuditEvent]] = select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id
        )
        if event_type is not None:
            statement = statement.where(AuditEvent.event_type == event_type)
        if actor_id is not None:
            statement = statement.where(AuditEvent.actor_id == actor_id)

        statement = statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(
            limit
        )
        return list(self.session.scalars(statement))

    def list_audit_events_before(
        self,
        tenant_id: str,
        cutoff: datetime,
        event_type: str | None = None,
        actor_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        self.session.flush()
        statement: Select[tuple[AuditEvent]] = select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.created_at < cutoff,
            AuditEvent.event_type != "audit.retention_deletion.executed",
        )
        if event_type is not None:
            statement = statement.where(AuditEvent.event_type == event_type)
        if actor_id is not None:
            statement = statement.where(AuditEvent.actor_id == actor_id)

        statement = statement.order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc()).limit(
            limit
        )
        return list(self.session.scalars(statement))

    def delete_audit_events(self, records: list[AuditEvent]) -> int:
        deleted_count = 0
        for record in records:
            self.session.delete(record)
            deleted_count += 1
        self.session.flush()
        return deleted_count

    def create_audit_legal_hold(
        self,
        record: AuditLegalHoldCreate,
    ) -> AuditLegalHold:
        legal_hold = AuditLegalHold(
            tenant_id=record.tenant_id,
            hold_id=record.hold_id,
            status="active",
            reason=record.reason,
            event_type=record.event_type,
            actor_id=record.actor_id,
            requested_by=record.requested_by,
            approved_by=record.approved_by,
            audit_event_id=record.audit_event_id,
            notes=record.notes,
        )
        self.session.add(legal_hold)
        self.session.flush()
        return legal_hold

    def get_audit_legal_hold(
        self,
        tenant_id: str,
        hold_id: str,
    ) -> AuditLegalHold | None:
        statement = select(AuditLegalHold).where(
            AuditLegalHold.tenant_id == tenant_id,
            AuditLegalHold.hold_id == hold_id,
        )
        return self.session.scalars(statement).first()

    def list_active_audit_legal_holds(
        self,
        tenant_id: str,
    ) -> list[AuditLegalHold]:
        statement: Select[tuple[AuditLegalHold]] = (
            select(AuditLegalHold)
            .where(
                AuditLegalHold.tenant_id == tenant_id,
                AuditLegalHold.status == "active",
            )
            .order_by(AuditLegalHold.created_at.asc(), AuditLegalHold.id.asc())
        )
        return list(self.session.scalars(statement))

    def release_audit_legal_hold(
        self,
        record: AuditLegalHoldRelease,
    ) -> AuditLegalHold:
        legal_hold = self.get_audit_legal_hold(record.tenant_id, record.hold_id)
        if legal_hold is None:
            raise PersistenceRecordNotFound("Audit legal hold record not found")

        now = utc_now()
        legal_hold.status = "released"
        legal_hold.released_by = record.released_by
        legal_hold.release_reason = record.release_reason
        legal_hold.release_audit_event_id = record.release_audit_event_id
        legal_hold.released_at = now
        legal_hold.updated_at = now
        self.session.flush()
        return legal_hold

    def acquire_platform_notification_acknowledgement_lock(
        self,
        *,
        tenant_id: str,
        notification_id: str,
        actor_id: str,
    ) -> None:
        """Serialize one actor's acknowledgement state transition.

        PostgreSQL uses a transaction-scoped advisory lock so coordination also
        works across API processes and replicas. SQLite permits only one writer;
        a no-op update acquires that write intent before the acknowledgement is
        read, including when no acknowledgement row exists yet. In both cases
        the lock is held until the request transaction commits or rolls back.
        """

        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "postgresql":
            lock_key = (
                "axis:platform-notification-acknowledgement:"
                f"{len(tenant_id)}:{tenant_id}"
                f"{len(notification_id)}:{notification_id}"
                f"{len(actor_id)}:{actor_id}"
            )
            self.session.execute(
                select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0)))
            )
            return
        if dialect_name == "sqlite":
            self.session.execute(
                update(PlatformNotificationAcknowledgement)
                .where(
                    PlatformNotificationAcknowledgement.tenant_id == tenant_id,
                    PlatformNotificationAcknowledgement.notification_id == notification_id,
                    PlatformNotificationAcknowledgement.actor_id == actor_id,
                )
                .values(
                    updated_at=PlatformNotificationAcknowledgement.updated_at,
                )
            )
            return
        raise NotImplementedError(
            "Platform notification acknowledgement locking is not supported for "
            f"dialect {dialect_name!r}."
        )

    def upsert_platform_notification_acknowledgement(
        self,
        record: PlatformNotificationAcknowledgementCreate,
    ) -> PlatformNotificationAcknowledgement:
        acknowledgement = self.get_platform_notification_acknowledgement(
            tenant_id=record.tenant_id,
            notification_id=record.notification_id,
            actor_id=record.actor_id,
        )
        if acknowledgement is None:
            acknowledgement = PlatformNotificationAcknowledgement(
                tenant_id=record.tenant_id,
                notification_id=record.notification_id,
                actor_id=record.actor_id,
                state=record.state,
                reason=record.reason,
                source=record.source,
                notification_title=record.notification_title,
                notification_category=record.notification_category,
                notification_severity=record.notification_severity,
                payload=record.payload,
                audit_event_id=record.audit_event_id,
                audit_event_type=record.audit_event_type,
                acknowledged_at=record.acknowledged_at,
            )
            self.session.add(acknowledgement)
        else:
            acknowledgement.state = record.state
            acknowledgement.reason = record.reason
            acknowledgement.source = record.source
            acknowledgement.notification_title = record.notification_title
            acknowledgement.notification_category = record.notification_category
            acknowledgement.notification_severity = record.notification_severity
            acknowledgement.payload = record.payload
            acknowledgement.audit_event_id = record.audit_event_id
            acknowledgement.audit_event_type = record.audit_event_type
            acknowledgement.acknowledged_at = record.acknowledged_at
            acknowledgement.updated_at = utc_now()

        self.session.flush()
        return acknowledgement

    def get_platform_notification_acknowledgement(
        self,
        tenant_id: str,
        notification_id: str,
        actor_id: str,
    ) -> PlatformNotificationAcknowledgement | None:
        statement: Select[tuple[PlatformNotificationAcknowledgement]] = select(
            PlatformNotificationAcknowledgement
        ).where(
            PlatformNotificationAcknowledgement.tenant_id == tenant_id,
            PlatformNotificationAcknowledgement.notification_id == notification_id,
            PlatformNotificationAcknowledgement.actor_id == actor_id,
        )
        return self.session.scalars(statement).first()

    def list_platform_notification_acknowledgements(
        self,
        tenant_id: str,
        actor_id: str,
        notification_ids: list[str] | None = None,
    ) -> list[PlatformNotificationAcknowledgement]:
        statement: Select[tuple[PlatformNotificationAcknowledgement]] = select(
            PlatformNotificationAcknowledgement
        ).where(
            PlatformNotificationAcknowledgement.tenant_id == tenant_id,
            PlatformNotificationAcknowledgement.actor_id == actor_id,
        )
        if notification_ids:
            statement = statement.where(
                PlatformNotificationAcknowledgement.notification_id.in_(notification_ids)
            )

        statement = statement.order_by(
            PlatformNotificationAcknowledgement.updated_at.desc(),
            PlatformNotificationAcknowledgement.id.desc(),
        )
        return list(self.session.scalars(statement))

    def create_approval_record(self, record: ApprovalRecordCreate) -> ApprovalRecord:
        approval = ApprovalRecord(
            tenant_id=record.tenant_id,
            approval_id=record.approval_id,
            workflow_id=record.workflow_id,
            action_id=record.action_id,
            requested_by=record.requested_by,
            owner_role=record.owner_role,
            status=record.status,
            risk_level=record.risk_level,
            payload=record.payload,
        )
        self.session.add(approval)
        self.session.flush()
        return approval

    def acquire_approval_decision_lock(self, tenant_id: str, approval_id: str) -> None:
        """Serialize one approval's terminal decision across API replicas."""
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "sqlite":
            return
        if dialect_name != "postgresql":
            raise NotImplementedError(
                f"Approval decision locking is not supported for dialect {dialect_name!r}."
            )
        lock_key = (
            f"axis:approval-decision:{len(tenant_id)}:{tenant_id}{len(approval_id)}:{approval_id}"
        )
        self.session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))

    def create_approval_decision_outbox(
        self, record: ApprovalDecisionOutboxCreate
    ) -> ApprovalDecisionOutbox:
        outbox = ApprovalDecisionOutbox(
            id=record.id,
            tenant_id=record.tenant_id,
            approval_id=record.approval_id,
            workflow_id=record.workflow_id,
            signal_name=record.signal_name,
            schema_version=record.schema_version,
            decision=record.decision,
            decision_actor_id=record.decision_actor_id,
            payload=record.payload,
            available_at=record.available_at,
        )
        self.session.add(outbox)
        self.session.flush()
        return outbox

    def get_approval_decision_outbox(
        self, tenant_id: str, approval_id: str
    ) -> ApprovalDecisionOutbox | None:
        return self.session.scalar(
            select(ApprovalDecisionOutbox).where(
                ApprovalDecisionOutbox.tenant_id == tenant_id,
                ApprovalDecisionOutbox.approval_id == approval_id,
            )
        )

    def claim_approval_decision_outbox(
        self,
        *,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> list[ApprovalDecisionOutbox]:
        statement = (
            select(ApprovalDecisionOutbox)
            .where(
                or_(
                    and_(
                        ApprovalDecisionOutbox.status == "pending",
                        ApprovalDecisionOutbox.available_at <= now,
                    ),
                    and_(
                        ApprovalDecisionOutbox.status == "dispatching",
                        ApprovalDecisionOutbox.lease_expires_at <= now,
                    ),
                )
            )
            .order_by(
                ApprovalDecisionOutbox.available_at.asc(),
                ApprovalDecisionOutbox.created_at.asc(),
                ApprovalDecisionOutbox.id.asc(),
            )
            .limit(limit)
        )
        if self.session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        rows = list(self.session.scalars(statement))
        for row in rows:
            row.status = "dispatching"
            row.attempt_count += 1
            row.claim_token = uuid4()
            row.claimed_at = now
            row.lease_expires_at = lease_expires_at
            row.last_attempt_at = now
            row.updated_at = now
        self.session.flush()
        return rows

    def complete_approval_decision_outbox(
        self,
        outbox_id: UUID,
        claim_token: UUID,
        *,
        delivered_at: datetime,
    ) -> bool:
        result = self.session.execute(
            update(ApprovalDecisionOutbox)
            .where(
                ApprovalDecisionOutbox.id == outbox_id,
                ApprovalDecisionOutbox.claim_token == claim_token,
                ApprovalDecisionOutbox.status == "dispatching",
            )
            .values(
                status="delivered",
                delivered_at=delivered_at,
                dead_lettered_at=None,
                claim_token=None,
                claimed_at=None,
                lease_expires_at=None,
                last_error=None,
                updated_at=delivered_at,
            )
        )
        return result.rowcount == 1

    def retry_approval_decision_outbox(
        self,
        outbox_id: UUID,
        claim_token: UUID,
        *,
        available_at: datetime,
        updated_at: datetime,
        error: str,
        dead_letter: bool,
    ) -> bool:
        result = self.session.execute(
            update(ApprovalDecisionOutbox)
            .where(
                ApprovalDecisionOutbox.id == outbox_id,
                ApprovalDecisionOutbox.claim_token == claim_token,
                ApprovalDecisionOutbox.status == "dispatching",
            )
            .values(
                status="dead_letter" if dead_letter else "pending",
                dead_lettered_at=updated_at if dead_letter else None,
                available_at=available_at,
                claim_token=None,
                claimed_at=None,
                lease_expires_at=None,
                last_error=error[:200],
                updated_at=updated_at,
            )
        )
        return result.rowcount == 1

    def get_approval_record(self, tenant_id: str, approval_id: str) -> ApprovalRecord | None:
        statement = select(ApprovalRecord).where(
            ApprovalRecord.tenant_id == tenant_id,
            ApprovalRecord.approval_id == approval_id,
        )
        return self.session.scalars(statement).first()

    def record_approval_decision(self, decision: ApprovalDecisionRecord) -> ApprovalRecord:
        approval = self.get_approval_record(decision.tenant_id, decision.approval_id)
        if approval is None:
            raise PersistenceRecordNotFound("Approval record not found")

        now = utc_now()
        approval.status = decision.decision
        approval.decision = decision.decision
        approval.decision_actor_id = decision.decision_actor_id
        approval.decision_note = decision.decision_note
        approval.decided_at = now
        approval.updated_at = now
        self.session.flush()
        return approval

    def list_approval_records(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ApprovalRecord]:
        statement: Select[tuple[ApprovalRecord]] = select(ApprovalRecord).where(
            ApprovalRecord.tenant_id == tenant_id
        )
        if status is not None:
            statement = statement.where(ApprovalRecord.status == status)

        statement = statement.order_by(ApprovalRecord.created_at.desc()).limit(limit)
        return list(self.session.scalars(statement))

    def create_action_run(self, record: ActionRunCreate) -> ActionRun:
        action_run = ActionRun(
            tenant_id=record.tenant_id,
            action_id=record.action_id,
            idempotency_key=record.idempotency_key,
            status=record.status,
            execution_mode=record.execution_mode,
            requested_by=record.requested_by,
            approval_id=record.approval_id,
            workflow_id=record.workflow_id,
            payload=record.payload,
        )
        self.session.add(action_run)
        self.session.flush()
        return action_run

    def get_action_run_by_idempotency_key(
        self,
        tenant_id: str,
        action_id: str,
        idempotency_key: str,
    ) -> ActionRun | None:
        statement = select(ActionRun).where(
            ActionRun.tenant_id == tenant_id,
            ActionRun.action_id == action_id,
            ActionRun.idempotency_key == idempotency_key,
        )
        return self.session.scalars(statement).first()

    def get_action_run(self, tenant_id: str, action_run_id: UUID) -> ActionRun | None:
        statement = select(ActionRun).where(
            ActionRun.tenant_id == tenant_id,
            ActionRun.id == action_run_id,
        )
        return self.session.scalars(statement).first()

    def record_action_run_result(self, result: ActionRunResultRecord) -> ActionRun:
        statement = select(ActionRun).where(
            ActionRun.tenant_id == result.tenant_id,
            ActionRun.id == result.action_run_id,
        )
        action_run = self.session.scalars(statement).first()
        if action_run is None:
            raise PersistenceRecordNotFound("Action run not found")

        action_run.status = result.status
        action_run.result_payload = result.result_payload
        action_run.updated_at = utc_now()
        self.session.flush()
        return action_run

    def list_action_runs_for_approval(
        self,
        tenant_id: str,
        action_id: str,
        approval_id: str,
    ) -> list[ActionRun]:
        statement: Select[tuple[ActionRun]] = (
            select(ActionRun)
            .where(
                ActionRun.tenant_id == tenant_id,
                ActionRun.action_id == action_id,
                ActionRun.approval_id == approval_id,
            )
            .order_by(ActionRun.updated_at.desc(), ActionRun.created_at.desc())
        )
        return list(self.session.scalars(statement))

    def list_action_runs(
        self,
        tenant_id: str,
        action_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ActionRun]:
        statement: Select[tuple[ActionRun]] = select(ActionRun).where(
            ActionRun.tenant_id == tenant_id
        )
        if action_id is not None:
            statement = statement.where(ActionRun.action_id == action_id)
        if status is not None:
            statement = statement.where(ActionRun.status == status)

        statement = statement.order_by(ActionRun.created_at.desc(), ActionRun.id.desc()).limit(
            limit
        )
        return list(self.session.scalars(statement))

    def upsert_demo_reference_record(
        self,
        record: DemoReferenceRecordCreate,
    ) -> DemoReferenceRecord:
        existing = self.get_demo_reference_record(
            tenant_id=record.tenant_id,
            surface=record.surface,
            reference_id=record.reference_id,
            status=None,
        )
        if existing is not None:
            existing.status = record.status
            existing.source = record.source
            existing.version = record.version
            existing.payload = record.payload
            existing.updated_at = utc_now()
            self.session.flush()
            return existing

        reference_record = DemoReferenceRecord(
            tenant_id=record.tenant_id,
            surface=record.surface,
            reference_id=record.reference_id,
            status=record.status,
            source=record.source,
            version=record.version,
            payload=record.payload,
        )
        self.session.add(reference_record)
        self.session.flush()
        return reference_record

    def get_demo_reference_record(
        self,
        tenant_id: str,
        surface: str,
        reference_id: str,
        status: str | None = "active",
    ) -> DemoReferenceRecord | None:
        statement = select(DemoReferenceRecord).where(
            DemoReferenceRecord.tenant_id == tenant_id,
            DemoReferenceRecord.surface == surface,
            DemoReferenceRecord.reference_id == reference_id,
        )
        if status is not None:
            statement = statement.where(DemoReferenceRecord.status == status)
        return self.session.scalars(statement).first()

    def has_demo_reference_records(self, tenant_id: str) -> bool:
        """Whether any active reference record was ever seeded for this tenant.

        Databases bootstrapped before tenants were registered in ``tenants``
        hold reference records with no matching registry row. Treating those
        records as proof of existence keeps such deployments serving instead of
        answering TENANT_NOT_FOUND for every console after an upgrade.
        """
        statement = (
            select(DemoReferenceRecord.id)
            .where(
                DemoReferenceRecord.tenant_id == tenant_id,
                DemoReferenceRecord.status == "active",
            )
            .limit(1)
        )
        return self.session.scalars(statement).first() is not None

    def create_workflow_run(self, record: WorkflowRunCreate) -> WorkflowRunRecord:
        workflow_run = WorkflowRunRecord(
            tenant_id=record.tenant_id,
            workflow_id=record.workflow_id,
            name=record.name,
            domain=record.domain,
            state=record.state,
            status=record.status,
            owner_role=record.owner_role,
            runtime=record.runtime,
            adapter=record.adapter,
            autonomy_level=record.autonomy_level,
            started_at=record.started_at,
            eta=record.eta,
            blocker=record.blocker,
            objective=record.objective,
            current_step=record.current_step,
            related_risk=record.related_risk,
            related_assets=record.related_assets,
            inputs=record.inputs,
            proposed_outputs=record.proposed_outputs,
            pending_signals=record.pending_signals,
            controls=record.controls,
            audit_scope=record.audit_scope,
            replay_ready=record.replay_ready,
        )
        self.session.add(workflow_run)
        self.session.flush()
        return workflow_run

    def get_workflow_run(
        self,
        tenant_id: str,
        workflow_id: str,
    ) -> WorkflowRunRecord | None:
        statement = select(WorkflowRunRecord).where(
            WorkflowRunRecord.tenant_id == tenant_id,
            WorkflowRunRecord.workflow_id == workflow_id,
        )
        return self.session.scalars(statement).first()

    def record_workflow_approval_decision(
        self,
        record: WorkflowApprovalDecisionUpdate,
    ) -> WorkflowRunRecord | None:
        workflow_run = self.get_workflow_run(record.tenant_id, record.workflow_id)
        if workflow_run is None:
            return None

        decision_status = {
            "approve": "approved",
            "reject": "rejected",
            "request_changes": "changes_requested",
        }.get(record.decision, record.decision)
        pending_signals = []
        matched_signal = False
        for signal in workflow_run.pending_signals:
            next_signal = dict(signal)
            if next_signal.get("approval_id") == record.approval_id:
                next_signal["status"] = decision_status
                next_signal["decision"] = record.decision
                next_signal["decided_by"] = record.actor_id
                matched_signal = True
            pending_signals.append(next_signal)

        if not matched_signal:
            pending_signals.append(
                {
                    "signal": "approval.decision",
                    "required_role": workflow_run.owner_role,
                    "status": decision_status,
                    "approval_id": record.approval_id,
                    "decision": record.decision,
                    "decided_by": record.actor_id,
                }
            )

        if record.decision == "approve":
            workflow_run.state = "approval_approved"
            workflow_run.status = "ready"
            workflow_run.current_step = "Approval approved"
            workflow_run.blocker = None
            workflow_run.replay_ready = True
        elif record.decision == "reject":
            workflow_run.state = "approval_rejected"
            workflow_run.status = "watch"
            workflow_run.current_step = "Approval rejected"
            workflow_run.blocker = "Approval rejected; action execution is blocked."
            workflow_run.replay_ready = True
        else:
            workflow_run.state = "changes_requested"
            workflow_run.status = "action_required"
            workflow_run.current_step = "Approval changes requested"
            workflow_run.blocker = "Approval reviewer requested changes before execution."
            workflow_run.replay_ready = True

        workflow_run.pending_signals = pending_signals
        workflow_run.updated_at = utc_now()
        self.session.flush()

        latest_sequence = self.session.scalars(
            select(WorkflowTimelineRecord.sequence)
            .where(
                WorkflowTimelineRecord.tenant_id == record.tenant_id,
                WorkflowTimelineRecord.workflow_id == record.workflow_id,
            )
            .order_by(WorkflowTimelineRecord.sequence.desc())
            .limit(1)
        ).first()
        self.append_workflow_timeline_event(
            WorkflowTimelineEventCreate(
                tenant_id=record.tenant_id,
                workflow_id=record.workflow_id,
                sequence=(latest_sequence or 0) + 1,
                event="workflow.approval_decision.recorded",
                occurred_at=workflow_run.updated_at,
                actor=record.actor_id,
                result=decision_status,
                summary=(
                    f"Approval {record.approval_id} recorded decision "
                    f"{record.decision} and updated persisted workflow state."
                ),
            )
        )
        return workflow_run

    def record_workflow_action_run(
        self,
        record: WorkflowActionRunUpdate,
    ) -> WorkflowRunRecord | None:
        workflow_run = self.get_workflow_run(record.tenant_id, record.workflow_id)
        if workflow_run is None:
            return None

        pending_signals = list(workflow_run.pending_signals)
        pending_signals.append(
            {
                "signal": "action.requested",
                "status": record.workflow_signal_status,
                "action_id": record.action_id,
                "action_run_id": str(record.action_run_id),
                "approval_id": record.approval_id,
                "idempotency_key": record.idempotency_key,
            }
        )

        if record.requires_approval:
            workflow_run.state = "action_proposed"
            workflow_run.status = "action_required"
            workflow_run.current_step = "Action proposal recorded"
            workflow_run.blocker = "Approval required before governed action execution."
        else:
            workflow_run.state = "action_requested"
            workflow_run.status = "running"
            workflow_run.current_step = "Action requested"
            workflow_run.blocker = None

        workflow_run.pending_signals = pending_signals
        workflow_run.replay_ready = True
        workflow_run.updated_at = utc_now()
        self.session.flush()

        latest_sequence = self.session.scalars(
            select(WorkflowTimelineRecord.sequence)
            .where(
                WorkflowTimelineRecord.tenant_id == record.tenant_id,
                WorkflowTimelineRecord.workflow_id == record.workflow_id,
            )
            .order_by(WorkflowTimelineRecord.sequence.desc())
            .limit(1)
        ).first()
        self.append_workflow_timeline_event(
            WorkflowTimelineEventCreate(
                tenant_id=record.tenant_id,
                workflow_id=record.workflow_id,
                sequence=(latest_sequence or 0) + 1,
                event="workflow.action_run.recorded",
                occurred_at=workflow_run.updated_at,
                actor=record.actor_id,
                result=record.workflow_signal_status,
                summary=(
                    f"Action run {record.action_run_id} for {record.action_id} "
                    "was persisted and signaled through the workflow boundary."
                ),
            )
        )
        return workflow_run

    def record_workflow_action_run_outcome(
        self,
        record: WorkflowActionRunOutcomeUpdate,
    ) -> WorkflowRunRecord | None:
        workflow_run = self.get_workflow_run(record.tenant_id, record.workflow_id)
        if workflow_run is None:
            return None

        pending_signals = list(workflow_run.pending_signals)
        pending_signals.append(
            {
                "signal": "action.outcome",
                "status": record.status,
                "action_id": record.action_id,
                "action_run_id": str(record.action_run_id),
                "idempotency_key": record.idempotency_key,
            }
        )

        if record.status in {"dry_run_completed", "execution_completed"}:
            workflow_run.state = "action_completed"
            workflow_run.status = "ready"
            workflow_run.current_step = "Action outcome recorded"
            workflow_run.blocker = None
        elif record.status == "execution_failed":
            workflow_run.state = "action_failed"
            workflow_run.status = "watch"
            workflow_run.current_step = "Action outcome failed"
            workflow_run.blocker = "Action run outcome recorded a failure."
        else:
            workflow_run.state = "action_blocked"
            workflow_run.status = "action_required"
            workflow_run.current_step = "Action outcome blocked"
            workflow_run.blocker = "Action run outcome requires operator follow-up."

        workflow_run.pending_signals = pending_signals
        workflow_run.replay_ready = True
        workflow_run.updated_at = utc_now()
        self.session.flush()

        latest_sequence = self.session.scalars(
            select(WorkflowTimelineRecord.sequence)
            .where(
                WorkflowTimelineRecord.tenant_id == record.tenant_id,
                WorkflowTimelineRecord.workflow_id == record.workflow_id,
            )
            .order_by(WorkflowTimelineRecord.sequence.desc())
            .limit(1)
        ).first()
        self.append_workflow_timeline_event(
            WorkflowTimelineEventCreate(
                tenant_id=record.tenant_id,
                workflow_id=record.workflow_id,
                sequence=(latest_sequence or 0) + 1,
                event="workflow.action_run.completed",
                occurred_at=workflow_run.updated_at,
                actor=record.actor_id,
                result=record.status,
                summary=(
                    f"Action run {record.action_run_id} recorded outcome "
                    f"{record.status}: {record.result_summary}"
                ),
            )
        )
        return workflow_run

    def list_workflow_runs(
        self,
        tenant_id: str,
        state: str | None = None,
        limit: int = 100,
    ) -> list[WorkflowRunRecord]:
        statement: Select[tuple[WorkflowRunRecord]] = select(WorkflowRunRecord).where(
            WorkflowRunRecord.tenant_id == tenant_id
        )
        if state is not None:
            statement = statement.where(WorkflowRunRecord.state == state)

        statement = statement.order_by(WorkflowRunRecord.started_at.desc()).limit(limit)
        return list(self.session.scalars(statement))

    def append_workflow_timeline_event(
        self,
        event: WorkflowTimelineEventCreate,
    ) -> WorkflowTimelineRecord:
        timeline_event = WorkflowTimelineRecord(
            tenant_id=event.tenant_id,
            workflow_id=event.workflow_id,
            sequence=event.sequence,
            event=event.event,
            occurred_at=event.occurred_at,
            actor=event.actor,
            result=event.result,
            summary=event.summary,
        )
        self.session.add(timeline_event)
        self.session.flush()
        return timeline_event

    def list_workflow_timeline_events(
        self,
        tenant_id: str,
        workflow_id: str,
        limit: int = 100,
    ) -> list[WorkflowTimelineRecord]:
        statement: Select[tuple[WorkflowTimelineRecord]] = (
            select(WorkflowTimelineRecord)
            .where(
                WorkflowTimelineRecord.tenant_id == tenant_id,
                WorkflowTimelineRecord.workflow_id == workflow_id,
            )
            .order_by(WorkflowTimelineRecord.sequence.asc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def create_replay_simulation_output(
        self,
        record: ReplaySimulationOutputCreate,
    ) -> ReplaySimulationOutput:
        output = ReplaySimulationOutput(
            tenant_id=record.tenant_id,
            simulation_output_id=record.simulation_output_id,
            workflow_id=record.workflow_id,
            artifact_id=record.artifact_id,
            idempotency_key=record.idempotency_key,
            status=record.status,
            requested_by=record.requested_by,
            required_scope=record.required_scope,
            replay_mode=record.replay_mode,
            determinism_status=record.determinism_status,
            output_hash=record.output_hash,
            retention_window_days=record.retention_window_days,
            permission_decision=record.permission_decision,
            artifact_payload=record.artifact_payload,
            evidence_refs=record.evidence_refs,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            reason=record.reason,
            notes=record.notes,
        )
        self.session.add(output)
        self.session.flush()
        return output

    def get_replay_simulation_output(
        self,
        tenant_id: str,
        simulation_output_id: str,
    ) -> ReplaySimulationOutput | None:
        statement = select(ReplaySimulationOutput).where(
            ReplaySimulationOutput.tenant_id == tenant_id,
            ReplaySimulationOutput.simulation_output_id == simulation_output_id,
        )
        return self.session.scalars(statement).first()

    def get_replay_simulation_output_by_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> ReplaySimulationOutput | None:
        statement = select(ReplaySimulationOutput).where(
            ReplaySimulationOutput.tenant_id == tenant_id,
            ReplaySimulationOutput.idempotency_key == idempotency_key,
        )
        return self.session.scalars(statement).first()

    def list_replay_simulation_outputs(
        self,
        tenant_id: str,
        workflow_id: str | None = None,
        limit: int = 100,
    ) -> list[ReplaySimulationOutput]:
        statement: Select[tuple[ReplaySimulationOutput]] = select(ReplaySimulationOutput).where(
            ReplaySimulationOutput.tenant_id == tenant_id
        )
        if workflow_id is not None:
            statement = statement.where(ReplaySimulationOutput.workflow_id == workflow_id)

        statement = statement.order_by(
            ReplaySimulationOutput.created_at.desc(),
            ReplaySimulationOutput.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def create_connector_configuration(
        self,
        record: ConnectorConfigurationCreate,
    ) -> ConnectorConfiguration:
        configuration = ConnectorConfiguration(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            display_name=record.display_name,
            status=record.status,
            sync_mode=record.sync_mode,
            runtime_boundary=record.runtime_boundary,
            created_by=record.created_by,
            configuration_payload=record.configuration_payload,
            credential_ref_ids=record.credential_ref_ids,
            notes=record.notes,
        )
        self.session.add(configuration)
        self.session.flush()
        return configuration

    def list_connector_configurations(
        self,
        tenant_id: str,
        connector_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ConnectorConfiguration]:
        statement: Select[tuple[ConnectorConfiguration]] = select(ConnectorConfiguration).where(
            ConnectorConfiguration.tenant_id == tenant_id
        )
        if connector_id is not None:
            statement = statement.where(ConnectorConfiguration.connector_id == connector_id)
        if status is not None:
            statement = statement.where(ConnectorConfiguration.status == status)

        statement = statement.order_by(
            ConnectorConfiguration.created_at.desc(),
            ConnectorConfiguration.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def create_connector_manifest(
        self,
        record: ConnectorManifestCreate,
    ) -> ConnectorManifestRecord:
        manifest = ConnectorManifestRecord(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            revision_number=record.revision_number,
            display_name=record.display_name,
            connector_type=record.connector_type,
            source_type=record.source_type,
            version=record.version,
            status=record.status,
            runtime_boundary=record.runtime_boundary,
            registered_by=record.registered_by,
            manifest_payload=record.manifest_payload,
            runtime_policy=record.runtime_policy,
            preview_sample=record.preview_sample,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            revises_revision_number=record.revises_revision_number,
            replaced_by_revision_number=record.replaced_by_revision_number,
            revision_idempotency_key=record.revision_idempotency_key,
            notes=record.notes,
        )
        self.session.add(manifest)
        self.session.flush()
        return manifest

    def get_connector_manifest(
        self,
        tenant_id: str,
        connector_id: str,
        *,
        for_update: bool = False,
    ) -> ConnectorManifestRecord | None:
        statement = (
            select(ConnectorManifestRecord)
            .where(
                ConnectorManifestRecord.tenant_id == tenant_id,
                ConnectorManifestRecord.connector_id == connector_id,
                ConnectorManifestRecord.replaced_by_revision_number.is_(None),
            )
            .order_by(ConnectorManifestRecord.revision_number.desc())
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalars(statement).first()

    def get_connector_manifest_by_revision_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> ConnectorManifestRecord | None:
        statement = select(ConnectorManifestRecord).where(
            ConnectorManifestRecord.tenant_id == tenant_id,
            ConnectorManifestRecord.revision_idempotency_key == idempotency_key,
        )
        return self.session.scalars(statement).first()

    def create_data_asset_stewardship_record(
        self,
        record: DataAssetStewardshipCreate,
    ) -> DataAssetStewardshipRecord:
        stewardship = DataAssetStewardshipRecord(
            tenant_id=record.tenant_id,
            asset_id=record.asset_id,
            revision_number=record.revision_number,
            owner=record.owner,
            classification=record.classification,
            residency=record.residency,
            retention=record.retention,
            notes=record.notes,
            declared_by=record.declared_by,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            revises_revision_number=record.revises_revision_number,
            replaced_by_revision_number=record.replaced_by_revision_number,
            revision_idempotency_key=record.revision_idempotency_key,
        )
        self.session.add(stewardship)
        self.session.flush()
        return stewardship

    def get_current_data_asset_stewardship(
        self,
        tenant_id: str,
        asset_id: str,
    ) -> DataAssetStewardshipRecord | None:
        statement = (
            select(DataAssetStewardshipRecord)
            .where(
                DataAssetStewardshipRecord.tenant_id == tenant_id,
                DataAssetStewardshipRecord.asset_id == asset_id,
                DataAssetStewardshipRecord.replaced_by_revision_number.is_(None),
            )
            .order_by(DataAssetStewardshipRecord.revision_number.desc())
        )
        return self.session.scalars(statement).first()

    def get_data_asset_stewardship_by_revision_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> DataAssetStewardshipRecord | None:
        statement = select(DataAssetStewardshipRecord).where(
            DataAssetStewardshipRecord.tenant_id == tenant_id,
            DataAssetStewardshipRecord.revision_idempotency_key == idempotency_key,
        )
        return self.session.scalars(statement).first()

    def append_data_asset_stewardship_revision(
        self,
        current_record: DataAssetStewardshipRecord,
        record: DataAssetStewardshipCreate,
    ) -> DataAssetStewardshipRecord:
        current_record.replaced_by_revision_number = record.revision_number
        current_record.updated_at = utc_now()
        self.session.flush()
        return self.create_data_asset_stewardship_record(record)

    def list_current_data_asset_stewardship(
        self,
        tenant_id: str,
        asset_ids: Sequence[str],
    ) -> list[DataAssetStewardshipRecord]:
        """Read current stewardship for named assets in bounded query batches.

        The caller passes the assets its response will actually contain, so the
        read stays proportional to the response instead of to everything the
        tenant has ever declared.
        """

        if not asset_ids:
            return []
        records: list[DataAssetStewardshipRecord] = []
        # Registries have no connector cap. Keep each IN clause below backend
        # parameter limits without truncating the catalog or duplicating rows.
        for asset_id_batch in batched(sorted(set(asset_ids)), 500):
            statement = (
                select(DataAssetStewardshipRecord)
                .where(
                    DataAssetStewardshipRecord.tenant_id == tenant_id,
                    DataAssetStewardshipRecord.asset_id.in_(asset_id_batch),
                    DataAssetStewardshipRecord.replaced_by_revision_number.is_(None),
                )
                .order_by(DataAssetStewardshipRecord.asset_id.asc())
            )
            records.extend(self.session.scalars(statement))
        return records

    def acquire_data_asset_stewardship_lock(
        self,
        *,
        tenant_id: str,
        asset_id: str,
    ) -> None:
        """Serialize stewardship declarations for one tenant asset.

        The first declaration on an asset has no row to ``SELECT ... FOR
        UPDATE``, so the write path is serialized with an advisory transaction
        lock instead. PostgreSQL coordinates across API processes and
        replicas; SQLite serializes writes at the database level and is used
        only by local/test profiles.
        """
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "sqlite":
            return
        if dialect_name != "postgresql":
            raise NotImplementedError(
                f"Data asset stewardship locking is not supported for dialect {dialect_name!r}."
            )
        lock_key = f"axis:data-stewardship:{len(tenant_id)}:{tenant_id}{len(asset_id)}:{asset_id}"
        self.session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))

    def create_data_resource_observation(
        self,
        record: DataResourceObservationCreate,
    ) -> DataAssetResourceObservation:
        observation = DataAssetResourceObservation(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            asset_id=record.asset_id,
            resource_name=record.resource_name,
            schema_fingerprint=record.schema_fingerprint,
            schema_fingerprint_version=record.schema_fingerprint_version,
            previous_fingerprint=None,
            drift_state=record.drift_state,
            first_seen_at=utc_now(),
            last_seen_at=utc_now(),
            last_source_kind=record.source_kind,
            observation_count=1,
            observed_by=record.observed_by,
            audit_event_type=record.audit_event_type,
        )
        self.session.add(observation)
        self.session.flush()
        return observation

    def get_data_resource_observation(
        self,
        tenant_id: str,
        connector_id: str,
        resource_name: str,
    ) -> DataAssetResourceObservation | None:
        statement = select(DataAssetResourceObservation).where(
            DataAssetResourceObservation.tenant_id == tenant_id,
            DataAssetResourceObservation.connector_id == connector_id,
            DataAssetResourceObservation.resource_name == resource_name,
        )
        return self.session.scalars(statement).first()

    def get_data_resource_observation_for_asset(
        self,
        tenant_id: str,
        asset_id: str,
        resource_name: str,
    ) -> DataAssetResourceObservation | None:
        """Contract evaluation resolves observations by catalog asset ID."""

        statement = select(DataAssetResourceObservation).where(
            DataAssetResourceObservation.tenant_id == tenant_id,
            DataAssetResourceObservation.asset_id == asset_id,
            DataAssetResourceObservation.resource_name == resource_name,
        )
        return self.session.scalars(statement).first()

    def list_data_resource_observations_by_asset(
        self,
        tenant_id: str,
        asset_id: str,
    ) -> list[DataAssetResourceObservation]:
        statement = (
            select(DataAssetResourceObservation)
            .where(
                DataAssetResourceObservation.tenant_id == tenant_id,
                DataAssetResourceObservation.asset_id == asset_id,
            )
            .order_by(DataAssetResourceObservation.resource_name.asc())
        )
        return list(self.session.scalars(statement))

    def count_data_resource_observations_by_asset(
        self,
        tenant_id: str,
        asset_ids: Sequence[str],
    ) -> dict[str, int]:
        """Count observations for named assets in bounded grouped queries.

        Scoping the group-by to the requested assets keeps the aggregate
        proportional to the response. The composite ``(tenant_id, asset_id)``
        index keeps the scan proportional to this tenant's rows; without it the
        planner combines two single-column indexes and touches index entries for
        every other tenant holding the same asset ids.
        """

        if not asset_ids:
            return {}
        counts: dict[str, int] = {}
        for asset_id_batch in batched(sorted(set(asset_ids)), 500):
            statement = (
                select(
                    DataAssetResourceObservation.asset_id,
                    func.count(DataAssetResourceObservation.id),
                )
                .where(
                    DataAssetResourceObservation.tenant_id == tenant_id,
                    DataAssetResourceObservation.asset_id.in_(asset_id_batch),
                )
                .group_by(DataAssetResourceObservation.asset_id)
            )
            counts.update(self.session.execute(statement).all())
        return counts

    def record_repeat_data_resource_observation(
        self,
        existing: DataAssetResourceObservation,
        *,
        schema_fingerprint: str | None,
        schema_fingerprint_version: str = "column_names_v1",
        drift_state: str,
        observed_by: str,
    ) -> DataAssetResourceObservation:
        """Update the current observation row in place; history stays in audit."""

        existing.previous_fingerprint = existing.schema_fingerprint
        existing.schema_fingerprint = schema_fingerprint
        existing.schema_fingerprint_version = schema_fingerprint_version
        existing.drift_state = drift_state
        existing.last_seen_at = utc_now()
        existing.observation_count += 1
        existing.observed_by = observed_by
        self.session.flush()
        return existing

    def acquire_data_resource_observation_lock(
        self,
        *,
        tenant_id: str,
        connector_id: str,
        resource_name: str,
    ) -> None:
        """Serialize resource observation upserts across replicas.

        Mirrors the stewardship lock: the first observation of a resource has
        no row to lock, so coordination uses an advisory transaction key.
        SQLite (local/test profiles) needs no extra primitive.
        """
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "sqlite":
            return
        if dialect_name != "postgresql":
            raise NotImplementedError(
                f"Data resource observation locking is not supported for dialect {dialect_name!r}."
            )
        lock_key = (
            "axis:data-resource-observation:"
            f"{len(tenant_id)}:{tenant_id}{len(connector_id)}:{connector_id}"
            f"{len(resource_name)}:{resource_name}"
        )
        self.session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))

    def create_data_asset_contract_record(
        self,
        record: DataAssetContractCreate,
    ) -> DataAssetContractRecord:
        contract = DataAssetContractRecord(
            tenant_id=record.tenant_id,
            asset_id=record.asset_id,
            revision_number=record.revision_number,
            expected_resource_name=record.expected_resource_name,
            expected_schema_fingerprint=record.expected_schema_fingerprint,
            freshness_warn_hours=record.freshness_warn_hours,
            freshness_fail_hours=record.freshness_fail_hours,
            notes=record.notes,
            declared_by=record.declared_by,
            audit_event_type=record.audit_event_type,
            revises_revision_number=record.revises_revision_number,
            replaced_by_revision_number=record.replaced_by_revision_number,
            revision_idempotency_key=record.revision_idempotency_key,
        )
        self.session.add(contract)
        self.session.flush()
        return contract

    def get_current_data_asset_contract(
        self,
        tenant_id: str,
        asset_id: str,
    ) -> DataAssetContractRecord | None:
        statement = (
            select(DataAssetContractRecord)
            .where(
                DataAssetContractRecord.tenant_id == tenant_id,
                DataAssetContractRecord.asset_id == asset_id,
                DataAssetContractRecord.replaced_by_revision_number.is_(None),
            )
            .order_by(DataAssetContractRecord.revision_number.desc())
        )
        return self.session.scalars(statement).first()

    def get_data_asset_contract_by_revision_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> DataAssetContractRecord | None:
        statement = select(DataAssetContractRecord).where(
            DataAssetContractRecord.tenant_id == tenant_id,
            DataAssetContractRecord.revision_idempotency_key == idempotency_key,
        )
        return self.session.scalars(statement).first()

    def append_data_asset_contract_revision(
        self,
        current_contract: DataAssetContractRecord,
        record: DataAssetContractCreate,
    ) -> DataAssetContractRecord:
        current_contract.replaced_by_revision_number = record.revision_number
        current_contract.updated_at = utc_now()
        self.session.flush()
        return self.create_data_asset_contract_record(record)

    def acquire_data_asset_contract_lock(
        self,
        *,
        tenant_id: str,
        asset_id: str,
    ) -> None:
        """Serialize contract declarations for one tenant asset.

        Mirrors the stewardship lock: the first declaration has no row to
        ``SELECT ... FOR UPDATE``, so coordination uses an advisory
        transaction key. SQLite (local/test profiles) needs no extra
        primitive.
        """
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "sqlite":
            return
        if dialect_name != "postgresql":
            raise NotImplementedError(
                f"Data asset contract locking is not supported for dialect {dialect_name!r}."
            )
        lock_key = f"axis:data-contract:{len(tenant_id)}:{tenant_id}{len(asset_id)}:{asset_id}"
        self.session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))

    def append_connector_manifest_revision(
        self,
        current_manifest: ConnectorManifestRecord,
        record: ConnectorManifestCreate,
    ) -> ConnectorManifestRecord:
        current_manifest.replaced_by_revision_number = record.revision_number
        current_manifest.updated_at = utc_now()
        self.session.flush()
        return self.create_connector_manifest(record)

    def list_connector_manifests(
        self,
        tenant_id: str,
        connector_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ConnectorManifestRecord]:
        statement = self._connector_manifest_statement(
            tenant_id,
            connector_id=connector_id,
            status=status,
        ).limit(limit)
        return list(self.session.scalars(statement))

    def list_all_current_connector_manifests(
        self,
        tenant_id: str,
        connector_id: str | None = None,
        status: str | None = None,
    ) -> list[ConnectorManifestRecord]:
        """Materialize one consistent tenant registry view in a single query."""

        statement = self._connector_manifest_statement(
            tenant_id,
            connector_id=connector_id,
            status=status,
        )
        return list(self.session.scalars(statement))

    @staticmethod
    def _connector_manifest_statement(
        tenant_id: str,
        *,
        connector_id: str | None = None,
        status: str | None = None,
    ) -> Select[tuple[ConnectorManifestRecord]]:
        statement: Select[tuple[ConnectorManifestRecord]] = select(ConnectorManifestRecord).where(
            ConnectorManifestRecord.tenant_id == tenant_id,
            ConnectorManifestRecord.replaced_by_revision_number.is_(None),
        )
        if connector_id is not None:
            statement = statement.where(ConnectorManifestRecord.connector_id == connector_id)
        if status is not None:
            statement = statement.where(ConnectorManifestRecord.status == status)

        return statement.order_by(
            ConnectorManifestRecord.created_at.desc(),
            ConnectorManifestRecord.id.desc(),
        )

    def list_connector_manifest_revisions(
        self,
        tenant_id: str,
        connector_id: str,
    ) -> list[ConnectorManifestRecord]:
        statement = (
            select(ConnectorManifestRecord)
            .where(
                ConnectorManifestRecord.tenant_id == tenant_id,
                ConnectorManifestRecord.connector_id == connector_id,
            )
            .order_by(ConnectorManifestRecord.revision_number.asc())
        )
        return list(self.session.scalars(statement))

    def update_connector_manifest_lifecycle(
        self,
        record: ConnectorManifestLifecycleUpdate,
    ) -> ConnectorManifestRecord:
        manifest = self.get_connector_manifest(record.tenant_id, record.connector_id)
        if manifest is None:
            raise PersistenceRecordNotFound("Connector manifest not found")

        now = utc_now()
        manifest.status = record.status
        manifest.audit_event_id = record.audit_event_id
        manifest.audit_event_type = record.audit_event_type
        manifest.notes = [*manifest.notes, record.note]
        manifest.updated_at = now
        self.session.flush()
        return manifest

    def append_connector_lifecycle_event(
        self,
        record: ConnectorLifecycleEventCreate,
    ) -> ConnectorLifecycleEventRecord:
        event = ConnectorLifecycleEventRecord(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            from_status=record.from_status,
            target_status=record.target_status,
            transitioned_by=record.transitioned_by,
            transition_reason=record.transition_reason,
            evidence_refs=record.evidence_refs,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def list_connector_lifecycle_events(
        self,
        tenant_id: str,
        connector_id: str,
        limit: int = 20,
    ) -> list[ConnectorLifecycleEventRecord]:
        statement = (
            select(ConnectorLifecycleEventRecord)
            .where(
                ConnectorLifecycleEventRecord.tenant_id == tenant_id,
                ConnectorLifecycleEventRecord.connector_id == connector_id,
            )
            .order_by(
                ConnectorLifecycleEventRecord.created_at.desc(),
                ConnectorLifecycleEventRecord.id.desc(),
            )
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def acquire_connector_source_activation_lock(
        self,
        *,
        tenant_id: str,
        connector_id: str,
    ) -> None:
        """Serialize source-binding activations for one tenant connector.

        Activation validates every selection against current observations
        before writing, so concurrent batches must not interleave their read
        and write phases. PostgreSQL coordinates across API processes via an
        advisory transaction lock; SQLite serializes writes at the database
        level and is used only by local/test profiles.
        """
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "sqlite":
            return
        if dialect_name != "postgresql":
            raise NotImplementedError(
                "Connector source activation locking is not supported for "
                f"dialect {dialect_name!r}."
            )
        lock_key = (
            f"axis:connector-source-activation:{len(tenant_id)}:{tenant_id}"
            f"{len(connector_id)}:{connector_id}"
        )
        self.session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))

    def create_connector_source_binding(
        self,
        record: ConnectorSourceBindingCreate,
    ) -> ConnectorSourceBinding:
        binding = ConnectorSourceBinding(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            asset_id=record.asset_id,
            binding_id=record.binding_id,
            connection_profile_id=record.connection_profile_id,
            resource_name=record.resource_name,
            schema_fingerprint=record.schema_fingerprint,
            schema_fingerprint_version=record.schema_fingerprint_version,
            supersedes_binding_id=record.supersedes_binding_id,
            credential_lease_id=record.credential_lease_id,
            egress_policy_id=record.egress_policy_id,
            status="active",
            ingestion_status=record.ingestion_status,
            activated_by=record.activated_by,
            activation_reason=record.activation_reason,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
        )
        self.session.add(binding)
        self.session.flush()
        return binding

    def get_connector_source_binding(
        self,
        tenant_id: str,
        binding_id: str,
        *,
        for_update: bool = False,
    ) -> ConnectorSourceBinding | None:
        statement = select(ConnectorSourceBinding).where(
            ConnectorSourceBinding.tenant_id == tenant_id,
            ConnectorSourceBinding.binding_id == binding_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalars(statement).first()

    def get_active_connector_source_binding_for_resource(
        self,
        tenant_id: str,
        connector_id: str,
        resource_name: str,
    ) -> ConnectorSourceBinding | None:
        statement = (
            select(ConnectorSourceBinding)
            .where(
                ConnectorSourceBinding.tenant_id == tenant_id,
                ConnectorSourceBinding.connector_id == connector_id,
                ConnectorSourceBinding.resource_name == resource_name,
                ConnectorSourceBinding.status == "active",
            )
            .order_by(ConnectorSourceBinding.activated_at.asc(), ConnectorSourceBinding.id.asc())
        )
        return self.session.scalars(statement).first()

    def list_active_connector_source_bindings(
        self,
        tenant_id: str,
        connector_id: str,
        limit: int = 200,
    ) -> list[ConnectorSourceBinding]:
        statement = (
            select(ConnectorSourceBinding)
            .where(
                ConnectorSourceBinding.tenant_id == tenant_id,
                ConnectorSourceBinding.connector_id == connector_id,
                ConnectorSourceBinding.status == "active",
            )
            .order_by(
                ConnectorSourceBinding.activated_at.asc(),
                ConnectorSourceBinding.binding_id.asc(),
            )
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    # ------------------------------------------------------------------
    # Governed source ingestion requests (validation-stage outbox)

    def create_connector_source_ingestion_request(
        self,
        record: ConnectorSourceIngestionRequestCreate,
        *,
        available_at: datetime,
    ) -> ConnectorSourceIngestionRequest:
        request_row = ConnectorSourceIngestionRequest(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            request_id=record.request_id,
            requested_by=record.requested_by,
            reason=record.reason,
            stage=record.stage,
            selections=record.selections,
            status="pending",
            attempt_count=0,
            available_at=available_at,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
        )
        self.session.add(request_row)
        self.session.flush()
        return request_row

    def get_connector_source_ingestion_request(
        self,
        tenant_id: str,
        request_id: str,
    ) -> ConnectorSourceIngestionRequest | None:
        statement = select(ConnectorSourceIngestionRequest).where(
            ConnectorSourceIngestionRequest.tenant_id == tenant_id,
            ConnectorSourceIngestionRequest.request_id == request_id,
        )
        return self.session.scalars(statement).first()

    def list_connector_source_ingestion_requests(
        self,
        tenant_id: str,
        connector_id: str,
        limit: int = 50,
    ) -> list[ConnectorSourceIngestionRequest]:
        statement = (
            select(ConnectorSourceIngestionRequest)
            .where(
                ConnectorSourceIngestionRequest.tenant_id == tenant_id,
                ConnectorSourceIngestionRequest.connector_id == connector_id,
            )
            .order_by(
                ConnectorSourceIngestionRequest.created_at.desc(),
                ConnectorSourceIngestionRequest.request_id.asc(),
            )
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def summarize_connector_source_ingestion_requests(
        self,
        tenant_id: str,
        connector_id: str,
    ) -> dict:
        """Aggregate counts over the connector's own ingestion requests.

        One grouped read over the existing table — no parallel store. The
        dead-lettered count is the subset of ``failed`` rows whose
        ``dead_lettered_at`` is set, so a request that failed and was requeued
        never double-counts as attention-worthy.
        """
        status_counts = {
            status: count
            for status, count in self.session.execute(
                select(
                    ConnectorSourceIngestionRequest.status,
                    func.count(),
                )
                .where(
                    ConnectorSourceIngestionRequest.tenant_id == tenant_id,
                    ConnectorSourceIngestionRequest.connector_id == connector_id,
                )
                .group_by(ConnectorSourceIngestionRequest.status)
            ).all()
        }
        total_count = sum(status_counts.values())
        dead_lettered_count = int(
            self.session.scalar(
                select(func.count())
                .select_from(ConnectorSourceIngestionRequest)
                .where(
                    ConnectorSourceIngestionRequest.tenant_id == tenant_id,
                    ConnectorSourceIngestionRequest.connector_id == connector_id,
                    ConnectorSourceIngestionRequest.status == "failed",
                    ConnectorSourceIngestionRequest.dead_lettered_at.is_not(None),
                )
            )
        )
        extract_stage_count = int(
            self.session.scalar(
                select(func.count())
                .select_from(ConnectorSourceIngestionRequest)
                .where(
                    ConnectorSourceIngestionRequest.tenant_id == tenant_id,
                    ConnectorSourceIngestionRequest.connector_id == connector_id,
                    ConnectorSourceIngestionRequest.stage == "extract",
                )
            )
        )
        last_activity_at = self.session.scalar(
            select(func.max(ConnectorSourceIngestionRequest.updated_at)).where(
                ConnectorSourceIngestionRequest.tenant_id == tenant_id,
                ConnectorSourceIngestionRequest.connector_id == connector_id,
            )
        )
        return {
            "status_counts": status_counts,
            "total_count": total_count,
            "dead_lettered_count": dead_lettered_count,
            "extract_stage_count": extract_stage_count,
            "last_activity_at": last_activity_at,
        }

    def list_connector_source_ingestion_requests_page(
        self,
        tenant_id: str,
        connector_id: str,
        *,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_request_id: str | None = None,
    ) -> list[ConnectorSourceIngestionRequest]:
        """Keyset-paged recent requests (newest first), stable across inserts.

        The cursor is the ``(created_at, request_id)`` pair of the last row of
        the previous page; callers pass ``limit + 1`` to detect a following
        page. Ordering matches :meth:`list_connector_source_ingestion_requests`
        so both surfaces interleave identically.
        """
        statement = (
            select(ConnectorSourceIngestionRequest)
            .where(
                ConnectorSourceIngestionRequest.tenant_id == tenant_id,
                ConnectorSourceIngestionRequest.connector_id == connector_id,
            )
            .order_by(
                ConnectorSourceIngestionRequest.created_at.desc(),
                ConnectorSourceIngestionRequest.request_id.asc(),
            )
        )
        if cursor_created_at is not None and cursor_request_id is not None:
            statement = statement.where(
                or_(
                    ConnectorSourceIngestionRequest.created_at < cursor_created_at,
                    and_(
                        ConnectorSourceIngestionRequest.created_at == cursor_created_at,
                        ConnectorSourceIngestionRequest.request_id > cursor_request_id,
                    ),
                )
            )
        return list(self.session.scalars(statement.limit(limit)))

    def claim_connector_source_ingestion_requests(
        self,
        *,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> list[ConnectorSourceIngestionRequest]:
        statement = (
            select(ConnectorSourceIngestionRequest)
            .where(
                or_(
                    and_(
                        ConnectorSourceIngestionRequest.status == "pending",
                        ConnectorSourceIngestionRequest.available_at <= now,
                    ),
                    and_(
                        ConnectorSourceIngestionRequest.status == "dispatching",
                        ConnectorSourceIngestionRequest.lease_expires_at <= now,
                    ),
                )
            )
            .order_by(
                ConnectorSourceIngestionRequest.available_at.asc(),
                ConnectorSourceIngestionRequest.created_at.asc(),
                ConnectorSourceIngestionRequest.id.asc(),
            )
            .limit(limit)
        )
        if self.session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        rows = list(self.session.scalars(statement))
        for row in rows:
            row.status = "dispatching"
            row.attempt_count += 1
            row.claim_token = uuid4()
            row.claimed_at = now
            row.lease_expires_at = lease_expires_at
            row.last_attempt_at = now
            row.updated_at = now
        self.session.flush()
        return rows

    def lock_connector_source_ingestion_claim(
        self, ingestion_request_id: UUID, claim_token: UUID, *, now: datetime,
    ) -> bool:
        """Fence a short batch transaction against claim takeover and expiry."""
        statement = (
            select(ConnectorSourceIngestionRequest.id)
            .where(
                ConnectorSourceIngestionRequest.id == ingestion_request_id,
                ConnectorSourceIngestionRequest.claim_token == claim_token,
                ConnectorSourceIngestionRequest.status == "dispatching",
                ConnectorSourceIngestionRequest.lease_expires_at > now,
            )
            .with_for_update()
        )
        return self.session.scalar(statement) is not None

    def complete_connector_source_ingestion_request(
        self,
        ingestion_request_id: UUID,
        claim_token: UUID,
        *,
        completed_at: datetime,
        evidence: dict,
    ) -> bool:
        result = self.session.execute(
            update(ConnectorSourceIngestionRequest)
            .where(
                ConnectorSourceIngestionRequest.id == ingestion_request_id,
                ConnectorSourceIngestionRequest.claim_token == claim_token,
                ConnectorSourceIngestionRequest.status == "dispatching",
                ConnectorSourceIngestionRequest.lease_expires_at > completed_at,
            )
            .values(
                status="completed",
                completed_at=completed_at,
                dead_lettered_at=None,
                claim_token=None,
                claimed_at=None,
                lease_expires_at=None,
                last_error=None,
                evidence=evidence,
                updated_at=completed_at,
            )
        )
        return result.rowcount == 1

    def retry_connector_source_ingestion_request(
        self,
        ingestion_request_id: UUID,
        claim_token: UUID,
        *,
        available_at: datetime,
        updated_at: datetime,
        error: str,
        dead_letter: bool,
        evidence: dict | None = None,
    ) -> bool:
        result = self.session.execute(
            update(ConnectorSourceIngestionRequest)
            .where(
                ConnectorSourceIngestionRequest.id == ingestion_request_id,
                ConnectorSourceIngestionRequest.claim_token == claim_token,
                ConnectorSourceIngestionRequest.status == "dispatching",
                ConnectorSourceIngestionRequest.lease_expires_at > updated_at,
            )
            .values(
                status="failed" if dead_letter else "pending",
                dead_lettered_at=updated_at if dead_letter else None,
                available_at=available_at,
                claim_token=None,
                claimed_at=None,
                lease_expires_at=None,
                last_error=error[:200],
                evidence=evidence,
                updated_at=updated_at,
            )
        )
        return result.rowcount == 1

    def cancel_connector_source_ingestion_request(
        self,
        *,
        tenant_id: str,
        request_id: str,
        cancelled_by: str,
        cancel_reason: str | None,
        now: datetime,
    ) -> Literal["cancelled", "replayed", "conflict", "not_found"]:
        """Fenced cancel of a still-pending governed ingestion request.

        Only ``pending`` rows transition to ``cancelled``. An identical replay
        returns ``replayed`` without new writes; dispatched or terminal states
        conflict instead of being overwritten. Audit linkage is written by the
        caller afterwards via :meth:`mark_connector_source_ingestion_request_audit`
        so a conflicted or not-found call never leaves an orphan event.
        """
        row = self.get_connector_source_ingestion_request(tenant_id, request_id)
        if row is None:
            return "not_found"
        normalized_reason = cancel_reason[:200] if cancel_reason else None
        if row.status == "cancelled":
            same_ask = (
                row.cancelled_by == cancelled_by
                and (row.cancel_reason or None) == normalized_reason
            )
            return "replayed" if same_ask else "conflict"
        if row.status != "pending":
            return "conflict"
        result = self.session.execute(
            update(ConnectorSourceIngestionRequest)
            .where(
                ConnectorSourceIngestionRequest.id == row.id,
                ConnectorSourceIngestionRequest.status == "pending",
            )
            .values(
                status="cancelled",
                cancelled_at=now,
                cancelled_by=cancelled_by,
                cancel_reason=normalized_reason,
                updated_at=now,
            )
        )
        return "cancelled" if result.rowcount == 1 else "conflict"

    def requeue_connector_source_ingestion_request(
        self,
        *,
        tenant_id: str,
        request_id: str,
        requeued_by: str,
        requeue_reason: str,
        idempotency_key: str,
        now: datetime,
    ) -> Literal["requeued", "replayed", "conflict", "not_found"]:
        """Fenced re-dispatch of a dead-lettered governed ingestion request.

        Only terminally dead-lettered requests transition. Identity for replay
        is the full ask — actor, reason, and explicit idempotency key — stored
        on the row at the moment of mutation, so an identical repeat replays
        without a second audit event and any different ask conflicts. Pinned
        selections and stage remain untouched; execution revalidates current
        fingerprints. Audit linkage is written by the caller via
        :meth:`mark_connector_source_ingestion_request_audit` inside the same
        transaction.
        """
        row = self.get_connector_source_ingestion_request(tenant_id, request_id)
        if row is None:
            return "not_found"
        same_ask = (
            row.requeued_by == requeued_by
            and row.requeue_reason == requeue_reason
            and row.requeue_idempotency_key == idempotency_key
        )
        if row.status == "pending" and row.dead_lettered_at is None:
            # Already requeued by this exact ask (or by someone else).
            return "replayed" if same_ask else "conflict"
        if row.status != "failed" or row.dead_lettered_at is None:
            return "conflict"
        result = self.session.execute(
            update(ConnectorSourceIngestionRequest)
            .where(
                ConnectorSourceIngestionRequest.id == row.id,
                ConnectorSourceIngestionRequest.status == "failed",
                ConnectorSourceIngestionRequest.dead_lettered_at.is_not(None),
            )
            .values(
                status="pending",
                attempt_count=0,
                available_at=now,
                claim_token=None,
                claimed_at=None,
                lease_expires_at=None,
                last_attempt_at=None,
                completed_at=None,
                dead_lettered_at=None,
                last_error=None,
                requeued_at=now,
                requeued_by=requeued_by,
                requeue_reason=requeue_reason[:600],
                requeue_idempotency_key=idempotency_key[:180],
                updated_at=now,
            )
        )
        return "requeued" if result.rowcount == 1 else "conflict"

    def mark_connector_source_ingestion_request_audit(
        self,
        *,
        tenant_id: str,
        request_id: str,
        audit_event_id: UUID,
        audit_event_type: str,
    ) -> None:
        """Bind the latest lifecycle audit event onto the request row."""
        self.session.execute(
            update(ConnectorSourceIngestionRequest)
            .where(
                ConnectorSourceIngestionRequest.tenant_id == tenant_id,
                ConnectorSourceIngestionRequest.request_id == request_id,
            )
            .values(audit_event_id=audit_event_id, audit_event_type=audit_event_type)
        )

    def get_connector_source_ingestion_request_attempts(
        self,
        ingestion_request_id: UUID,
    ) -> list[dict]:
        """Prior finalized dispatch-attempt records from the row's evidence.

        The evidence JSON is the durable history: each finalized attempt
        appends one metadata-only entry. Only well-formed dict entries are
        returned; anything else is ignored so historical rows keep reading.
        """
        row = self.session.get(ConnectorSourceIngestionRequest, ingestion_request_id)
        if row is None or not isinstance(row.evidence, dict):
            return []
        attempts = row.evidence.get("attempts")
        if not isinstance(attempts, list):
            return []
        return [entry for entry in attempts if isinstance(entry, dict)]

    # ------------------------------------------------------------------
    # Governed batch-envelope export requests

    def create_connector_source_batch_export_request(
        self,
        record: ConnectorSourceBatchExportRequestCreate,
    ) -> ConnectorSourceBatchExportRequest:
        export_request = ConnectorSourceBatchExportRequest(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            request_id=record.request_id,
            export_request_id=record.export_request_id,
            idempotency_key=record.idempotency_key,
            requested_by=record.requested_by,
            owner_role=record.owner_role,
            risk_level=record.risk_level,
            approval_id=record.approval_id,
            workflow_id=record.workflow_id,
            export_reason=record.export_reason,
            status=record.status,
            export_status=record.export_status,
            storage_status=record.storage_status,
            batch_count=record.batch_count,
            total_row_count=record.total_row_count,
            envelope_checksum_sha256=record.envelope_checksum_sha256,
            redaction_policy=record.redaction_policy,
            controls=record.controls,
            permission_decision=record.permission_decision,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            notes=record.notes,
        )
        self.session.add(export_request)
        self.session.flush()
        return export_request

    def get_connector_source_batch_export_request(
        self,
        tenant_id: str,
        export_request_id: str,
    ) -> ConnectorSourceBatchExportRequest | None:
        # populate_existing is load-bearing for canonical re-reads inside one
        # session: fenced transitions deliberately skip session synchronization
        # (see above), so callers re-reading after a lost race must observe
        # committed truth, not a cached pre-fence instance.
        statement = (
            select(ConnectorSourceBatchExportRequest)
            .where(
                ConnectorSourceBatchExportRequest.tenant_id == tenant_id,
                ConnectorSourceBatchExportRequest.export_request_id == export_request_id,
            )
            .execution_options(populate_existing=True)
        )
        return self.session.scalars(statement).first()

    def get_connector_source_batch_export_request_by_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> ConnectorSourceBatchExportRequest | None:
        statement = select(ConnectorSourceBatchExportRequest).where(
            ConnectorSourceBatchExportRequest.tenant_id == tenant_id,
            ConnectorSourceBatchExportRequest.idempotency_key == idempotency_key,
        )
        return self.session.scalars(statement).first()

    def list_connector_source_batch_export_requests(
        self,
        tenant_id: str,
        request_id: str,
        *,
        limit: int = 50,
    ) -> list[ConnectorSourceBatchExportRequest]:
        statement = (
            select(ConnectorSourceBatchExportRequest)
            .where(
                ConnectorSourceBatchExportRequest.tenant_id == tenant_id,
                ConnectorSourceBatchExportRequest.request_id == request_id,
            )
            .order_by(ConnectorSourceBatchExportRequest.created_at.asc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def record_connector_source_batch_export_decision(
        self,
        record: ConnectorSourceBatchExportDecisionRecord,
    ) -> bool:
        """Fenced decision transition of a still-undecided export request.

        Only rows whose ``decision`` is still unset transition, so concurrent
        deciders produce exactly one winner; the caller maps a ``False`` return
        to an explicit conflict instead of a silent overwrite. Audit linkage is
        attached by :meth:`link_connector_source_batch_export_audit` AFTER the
        fence is won, inside the same transaction, so a loser never leaves an
        orphan event behind.
        """
        now = utc_now()
        result = self.session.execute(
            update(ConnectorSourceBatchExportRequest)
            .where(
                ConnectorSourceBatchExportRequest.tenant_id == record.tenant_id,
                ConnectorSourceBatchExportRequest.export_request_id
                == record.export_request_id,
                ConnectorSourceBatchExportRequest.decision.is_(None),
            )
            .values(
                status=record.status,
                export_status=record.export_status,
                decision=record.decision,
                decision_actor_id=record.decision_actor_id,
                decision_note=record.decision_note,
                decided_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def record_connector_source_batch_export_materialization(
        self,
        record: ConnectorSourceBatchExportMaterializationRecord,
    ) -> bool:
        """Single-shot materialization transition of a not-yet-written request.

        The ``storage_status``/``materialization_id`` guards make the write
        winnable exactly once under genuine concurrency; losers must surface a
        conflict or an exact replay instead of overwriting recorded evidence.
        Audit linkage is attached by :meth:`link_connector_source_batch_export_audit`
        after the fence is won, inside the same transaction.
        """
        now = utc_now()
        result = self.session.execute(
            update(ConnectorSourceBatchExportRequest)
            .where(
                ConnectorSourceBatchExportRequest.tenant_id == record.tenant_id,
                ConnectorSourceBatchExportRequest.export_request_id
                == record.export_request_id,
                ConnectorSourceBatchExportRequest.storage_status == "not_written",
                ConnectorSourceBatchExportRequest.materialization_id.is_(None),
            )
            .values(
                status=record.status,
                export_status=record.export_status,
                storage_status=record.storage_status,
                materialization_id=record.materialization_id,
                materialization_idempotency_key=(
                    record.materialization_idempotency_key
                ),
                materialized_by=record.materialized_by,
                materialized_at=now,
                materialization_reason=record.materialization_reason,
                storage_adapter=record.storage_adapter,
                storage_key=record.storage_key,
                storage_uri=record.storage_uri,
                artifact_checksum_sha256=record.artifact_checksum_sha256,
                artifact_size_bytes=record.artifact_size_bytes,
                artifact_content_type=record.artifact_content_type,
                updated_at=now,
            )
            # synchronize_session=False is load-bearing: the default would
            # apply the UPDATE values to the session's cached instance even
            # when zero rows matched, poisoning the caller's post-loss
            # canonical re-read with phantom state.
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def link_connector_source_batch_export_audit(
        self,
        *,
        tenant_id: str,
        export_request_id: str,
        audit_event_id: UUID,
        audit_event_type: str,
    ) -> None:
        """Bind the lifecycle audit event onto the export-request row."""
        self.session.execute(
            update(ConnectorSourceBatchExportRequest)
            .where(
                ConnectorSourceBatchExportRequest.tenant_id == tenant_id,
                ConnectorSourceBatchExportRequest.export_request_id
                == export_request_id,
            )
            .values(audit_event_id=audit_event_id, audit_event_type=audit_event_type)
        )

    def create_connector_source_extraction_batch(
        self,
        record: ConnectorSourceExtractionBatchCreate,
    ) -> ConnectorSourceExtractionBatch:
        batch_row = ConnectorSourceExtractionBatch(**record.model_dump())
        self.session.add(batch_row)
        self.session.flush()
        return batch_row

    def get_connector_source_extraction_batch_by_key(
        self,
        tenant_id: str,
        batch_key: str,
    ) -> ConnectorSourceExtractionBatch | None:
        statement = select(ConnectorSourceExtractionBatch).where(
            ConnectorSourceExtractionBatch.tenant_id == tenant_id,
            ConnectorSourceExtractionBatch.batch_key == batch_key,
        )
        return self.session.scalars(statement).first()

    def count_connector_source_extraction_batches_for_binding(
        self,
        tenant_id: str,
        request_id: str,
        binding_id: str,
    ) -> int:
        """Generation counter for deterministic, collision-free batch keys."""
        statement = (
            select(func.count())
            .select_from(ConnectorSourceExtractionBatch)
            .where(
                ConnectorSourceExtractionBatch.tenant_id == tenant_id,
                ConnectorSourceExtractionBatch.request_id == request_id,
                ConnectorSourceExtractionBatch.binding_id == binding_id,
            )
        )
        return int(self.session.scalar(statement))

    def advance_connector_source_checkpoint(
        self, *, tenant_id: str, connector_id: str, binding_id: str,
        expected_revision: int, checkpoint: dict,
    ) -> bool:
        """CAS within the caller's batch/request transaction; no source I/O here."""
        result = self.session.execute(
            update(ConnectorSourceBinding)
            .where(
                ConnectorSourceBinding.tenant_id == tenant_id,
                ConnectorSourceBinding.connector_id == connector_id,
                ConnectorSourceBinding.binding_id == binding_id,
                ConnectorSourceBinding.status == "active",
                ConnectorSourceBinding.source_checkpoint_revision == expected_revision,
            )
            .values(source_checkpoint_revision=expected_revision + 1, source_checkpoint=checkpoint)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def has_incompatible_raw_checkpoint(self, tenant_id: str, request_id: str) -> bool:
        return self.session.scalar(
            select(ConnectorSourceExtractionBatch.id).where(
                ConnectorSourceExtractionBatch.tenant_id == tenant_id,
                ConnectorSourceExtractionBatch.request_id == request_id,
                ~ConnectorSourceExtractionBatch.batch_key.startswith("raw-v1:"),
            ).limit(1)
        ) is not None

    def get_connector_source_ingestion_request_batches(
        self,
        tenant_id: str,
        request_id: str,
        *,
        limit: int,
        cursor_key: str | None = None,
        binding_id: str | None = None,
        truncated: bool | None = None,
    ) -> list[ConnectorSourceExtractionBatch]:
        """Keyset-paged batch metadata, deterministically ordered by batch key.

        Callers pass ``limit + 1`` to detect a following page; the extra row
        never leaves the repository contract as data.
        """
        statement = (
            select(ConnectorSourceExtractionBatch)
            .where(
                ConnectorSourceExtractionBatch.tenant_id == tenant_id,
                ConnectorSourceExtractionBatch.request_id == request_id,
            )
            .order_by(ConnectorSourceExtractionBatch.batch_key.asc())
        )
        if cursor_key is not None:
            statement = statement.where(
                ConnectorSourceExtractionBatch.batch_key > cursor_key
            )
        if binding_id is not None:
            statement = statement.where(
                ConnectorSourceExtractionBatch.binding_id == binding_id
            )
        if truncated is not None:
            statement = statement.where(
                ConnectorSourceExtractionBatch.truncated == truncated
            )
        return list(self.session.scalars(statement.limit(limit)))

    def count_connector_source_ingestion_request_batches(
        self,
        tenant_id: str,
        request_id: str,
        *,
        binding_id: str | None = None,
        truncated: bool | None = None,
    ) -> int:
        conditions = [
            ConnectorSourceExtractionBatch.tenant_id == tenant_id,
            ConnectorSourceExtractionBatch.request_id == request_id,
        ]
        if binding_id is not None:
            conditions.append(
                ConnectorSourceExtractionBatch.binding_id == binding_id
            )
        if truncated is not None:
            conditions.append(ConnectorSourceExtractionBatch.truncated == truncated)
        statement = (
            select(func.count())
            .select_from(ConnectorSourceExtractionBatch)
            .where(*conditions)
        )
        return int(self.session.scalar(statement))

    def create_connector_credential_handle(
        self,
        record: ConnectorCredentialHandleCreate,
    ) -> ConnectorCredentialHandle:
        credential_handle = ConnectorCredentialHandle(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            handle_id=record.handle_id,
            display_name=record.display_name,
            status=record.status,
            secret_provider=record.secret_provider,
            secret_ref=record.secret_ref,
            purpose=record.purpose,
            rotation_interval_days=record.rotation_interval_days,
            last_rotated_at=record.last_rotated_at,
            next_rotation_due_at=record.next_rotation_due_at,
            created_by=record.created_by,
            labels=record.labels,
            notes=record.notes,
        )
        self.session.add(credential_handle)
        self.session.flush()
        return credential_handle

    def get_connector_credential_handle(
        self,
        tenant_id: str,
        handle_id: str,
        *,
        for_update: bool = False,
    ) -> ConnectorCredentialHandle | None:
        statement = select(ConnectorCredentialHandle).where(
            ConnectorCredentialHandle.tenant_id == tenant_id,
            ConnectorCredentialHandle.handle_id == handle_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalars(statement).first()

    def list_connector_credential_handles(
        self,
        tenant_id: str,
        connector_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ConnectorCredentialHandle]:
        statement: Select[tuple[ConnectorCredentialHandle]] = select(
            ConnectorCredentialHandle
        ).where(ConnectorCredentialHandle.tenant_id == tenant_id)
        if connector_id is not None:
            statement = statement.where(ConnectorCredentialHandle.connector_id == connector_id)
        if status is not None:
            statement = statement.where(ConnectorCredentialHandle.status == status)

        statement = statement.order_by(
            ConnectorCredentialHandle.created_at.desc(),
            ConnectorCredentialHandle.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def record_connector_credential_rotation(
        self,
        record: ConnectorCredentialRotationCreate,
    ) -> ConnectorCredentialRotation:
        handle = self.get_connector_credential_handle(record.tenant_id, record.handle_id)
        if handle is None:
            raise PersistenceRecordNotFound("Connector credential handle not found")

        rotation = ConnectorCredentialRotation(
            tenant_id=record.tenant_id,
            handle_id=record.handle_id,
            rotated_by=record.rotated_by,
            rotated_at=record.rotated_at,
            evidence_ref=record.evidence_ref,
            status=record.status,
            notes=record.notes,
        )
        handle.status = "active"
        handle.last_rotated_at = record.rotated_at
        handle.next_rotation_due_at = record.rotated_at + timedelta(
            days=handle.rotation_interval_days
        )
        handle.updated_at = utc_now()
        self.session.add(rotation)
        self.session.flush()
        return rotation

    def list_connector_credential_rotations(
        self,
        tenant_id: str,
        handle_id: str,
        limit: int = 100,
    ) -> list[ConnectorCredentialRotation]:
        statement: Select[tuple[ConnectorCredentialRotation]] = (
            select(ConnectorCredentialRotation)
            .where(
                ConnectorCredentialRotation.tenant_id == tenant_id,
                ConnectorCredentialRotation.handle_id == handle_id,
            )
            .order_by(
                ConnectorCredentialRotation.rotated_at.desc(),
                ConnectorCredentialRotation.created_at.desc(),
            )
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def create_connector_credential_lease(
        self,
        record: ConnectorCredentialLeaseCreate,
    ) -> ConnectorCredentialLease:
        lease = ConnectorCredentialLease(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            handle_id=record.handle_id,
            lease_id=record.lease_id,
            status=record.status,
            lease_mode=record.lease_mode,
            runtime_boundary=record.runtime_boundary,
            requested_by=record.requested_by,
            lease_purpose=record.lease_purpose,
            secret_provider=record.secret_provider,
            secret_ref=record.secret_ref,
            vault_kms_policy=record.vault_kms_policy,
            # JSON columns persist plain values; the typed decision is the
            # write-boundary contract, not the storage shape.
            permission_decision=record.permission_decision.model_dump(mode="json"),
            lease_result=record.lease_result,
            granted_at=record.granted_at,
            expires_at=record.expires_at,
            renewal_due_at=record.renewal_due_at,
            renewed_at=None,
            renewed_by=None,
            renewal_count=0,
            revoked_at=None,
            revoked_by=None,
            revocation_reason=None,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            notes=record.notes,
        )
        self.session.add(lease)
        self.session.flush()
        return lease

    def get_connector_credential_lease(
        self,
        tenant_id: str,
        lease_id: str,
        *,
        for_update: bool = False,
    ) -> ConnectorCredentialLease | None:
        statement = select(ConnectorCredentialLease).where(
            ConnectorCredentialLease.tenant_id == tenant_id,
            ConnectorCredentialLease.lease_id == lease_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalars(statement).first()

    def list_connector_credential_leases(
        self,
        tenant_id: str,
        connector_id: str | None = None,
        handle_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ConnectorCredentialLease]:
        statement: Select[tuple[ConnectorCredentialLease]] = select(ConnectorCredentialLease).where(
            ConnectorCredentialLease.tenant_id == tenant_id
        )
        if connector_id is not None:
            statement = statement.where(ConnectorCredentialLease.connector_id == connector_id)
        if handle_id is not None:
            statement = statement.where(ConnectorCredentialLease.handle_id == handle_id)
        if status is not None:
            statement = statement.where(ConnectorCredentialLease.status == status)

        statement = statement.order_by(
            ConnectorCredentialLease.created_at.desc(),
            ConnectorCredentialLease.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def renew_connector_credential_lease(
        self,
        record: ConnectorCredentialLeaseRenewalRecord,
    ) -> ConnectorCredentialLease:
        lease = self.get_connector_credential_lease(record.tenant_id, record.lease_id)
        if lease is None:
            raise PersistenceRecordNotFound("Connector credential lease not found")
        lease.status = "active"
        lease.renewed_at = record.renewed_at
        lease.renewed_by = record.renewed_by
        lease.renewal_count += 1
        lease.expires_at = record.expires_at
        lease.renewal_due_at = record.renewal_due_at
        lease.audit_event_id = record.audit_event_id
        lease.audit_event_type = record.audit_event_type
        lease.lease_result = record.lease_result
        if record.note is not None:
            lease.notes = [*lease.notes, record.note]
        lease.updated_at = utc_now()
        self.session.flush()
        return lease

    def revoke_connector_credential_lease(
        self,
        record: ConnectorCredentialLeaseRevocationRecord,
    ) -> ConnectorCredentialLease:
        lease = self.get_connector_credential_lease(record.tenant_id, record.lease_id)
        if lease is None:
            raise PersistenceRecordNotFound("Connector credential lease not found")
        lease.status = "revoked"
        lease.revoked_at = record.revoked_at
        lease.revoked_by = record.revoked_by
        lease.revocation_reason = record.revocation_reason
        lease.audit_event_id = record.audit_event_id
        lease.audit_event_type = record.audit_event_type
        lease.lease_result = record.lease_result
        lease.updated_at = utc_now()
        self.session.flush()
        return lease

    def create_connector_egress_policy(
        self,
        record: ConnectorEgressPolicyCreate,
    ) -> ConnectorEgressPolicy:
        policy = ConnectorEgressPolicy(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            policy_id=record.policy_id,
            display_name=record.display_name,
            status=record.status,
            connection_profile_id=record.connection_profile_id,
            egress_boundary=record.egress_boundary,
            policy_mode=record.policy_mode,
            runtime_boundary=record.runtime_boundary,
            private_endpoint_ref=record.private_endpoint_ref,
            created_by=record.created_by,
            policy_document=record.policy_document,
            evidence_refs=record.evidence_refs,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            notes=record.notes,
        )
        self.session.add(policy)
        self.session.flush()
        return policy

    def get_connector_egress_policy(
        self,
        tenant_id: str,
        policy_id: str,
        *,
        for_update: bool = False,
    ) -> ConnectorEgressPolicy | None:
        statement = select(ConnectorEgressPolicy).where(
            ConnectorEgressPolicy.tenant_id == tenant_id,
            ConnectorEgressPolicy.policy_id == policy_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def list_connector_egress_policies(
        self,
        tenant_id: str,
        connector_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ConnectorEgressPolicy]:
        statement: Select[tuple[ConnectorEgressPolicy]] = select(ConnectorEgressPolicy).where(
            ConnectorEgressPolicy.tenant_id == tenant_id
        )
        if connector_id is not None:
            statement = statement.where(ConnectorEgressPolicy.connector_id == connector_id)
        if status is not None:
            statement = statement.where(ConnectorEgressPolicy.status == status)

        statement = statement.order_by(
            ConnectorEgressPolicy.created_at.desc(),
            ConnectorEgressPolicy.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def create_connector_run(
        self,
        record: ConnectorRunCreate,
    ) -> ConnectorRun:
        connector_run = ConnectorRun(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            run_id=record.run_id,
            status=record.status,
            execution_mode=record.execution_mode,
            runtime_boundary=record.runtime_boundary,
            requested_by=record.requested_by,
            credential_handle_ids=record.credential_handle_ids,
            input_summary=record.input_summary,
            result_summary=record.result_summary,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            notes=record.notes,
        )
        self.session.add(connector_run)
        self.session.flush()
        return connector_run

    def list_connector_runs(
        self,
        tenant_id: str,
        connector_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ConnectorRun]:
        statement: Select[tuple[ConnectorRun]] = select(ConnectorRun).where(
            ConnectorRun.tenant_id == tenant_id
        )
        if connector_id is not None:
            statement = statement.where(ConnectorRun.connector_id == connector_id)
        if status is not None:
            statement = statement.where(ConnectorRun.status == status)

        statement = statement.order_by(
            ConnectorRun.created_at.desc(),
            ConnectorRun.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def get_latest_connector_run(
        self,
        tenant_id: str,
        connector_id: str,
        status: str,
    ) -> ConnectorRun | None:
        statement = (
            select(ConnectorRun)
            .where(
                ConnectorRun.tenant_id == tenant_id,
                ConnectorRun.connector_id == connector_id,
                ConnectorRun.status == status,
            )
            .order_by(
                ConnectorRun.updated_at.desc(),
                ConnectorRun.created_at.desc(),
                ConnectorRun.id.desc(),
            )
            .limit(1)
        )
        return self.session.scalar(statement)

    def list_latest_connector_runs_by_connector(
        self,
        tenant_id: str,
        status: str,
    ) -> list[ConnectorRun]:
        """Return the latest matching run for every tenant connector in one query.

        This stays tenant-wide because registry size is not capped; binding every
        connector ID would introduce backend-specific parameter-count limits.
        """

        ranked_runs = (
            select(
                ConnectorRun.id.label("connector_run_id"),
                func.row_number()
                .over(
                    partition_by=ConnectorRun.connector_id,
                    order_by=(
                        ConnectorRun.updated_at.desc(),
                        ConnectorRun.created_at.desc(),
                        ConnectorRun.id.desc(),
                    ),
                )
                .label("run_rank"),
            )
            .where(
                ConnectorRun.tenant_id == tenant_id,
                ConnectorRun.status == status,
            )
            .subquery()
        )
        statement = (
            select(ConnectorRun)
            .join(
                ranked_runs,
                ConnectorRun.id == ranked_runs.c.connector_run_id,
            )
            .where(ranked_runs.c.run_rank == 1)
            .order_by(ConnectorRun.connector_id.asc())
        )
        return list(self.session.scalars(statement))

    def get_connector_run(self, tenant_id: str, run_id: str) -> ConnectorRun | None:
        statement = select(ConnectorRun).where(
            ConnectorRun.tenant_id == tenant_id,
            ConnectorRun.run_id == run_id,
        )
        return self.session.scalar(statement)

    def update_connector_run(
        self,
        record: ConnectorRunUpdateRecord,
    ) -> ConnectorRun:
        connector_run = self.get_connector_run(record.tenant_id, record.run_id)
        if connector_run is None:
            raise PersistenceRecordNotFound("Connector run not found")
        connector_run.status = record.status
        connector_run.result_summary = record.result_summary
        connector_run.audit_event_id = record.audit_event_id
        connector_run.audit_event_type = record.audit_event_type
        if record.notes is not None:
            connector_run.notes = record.notes
        connector_run.updated_at = utc_now()
        self.session.flush()
        return connector_run

    def create_connector_sync_checkpoint(
        self,
        record: ConnectorSyncCheckpointCreate,
    ) -> ConnectorSyncCheckpoint:
        checkpoint = ConnectorSyncCheckpoint(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            run_id=record.run_id,
            checkpoint_id=record.checkpoint_id,
            checkpoint_type=record.checkpoint_type,
            status=record.status,
            sequence=record.sequence,
            runtime_boundary=record.runtime_boundary,
            adapter=record.adapter,
            cursor=record.cursor,
            result_summary=record.result_summary,
            evidence_refs=record.evidence_refs,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            notes=record.notes,
        )
        self.session.add(checkpoint)
        self.session.flush()
        return checkpoint

    def get_connector_sync_checkpoint(
        self,
        tenant_id: str,
        checkpoint_id: str,
    ) -> ConnectorSyncCheckpoint | None:
        statement: Select[tuple[ConnectorSyncCheckpoint]] = select(ConnectorSyncCheckpoint).where(
            ConnectorSyncCheckpoint.tenant_id == tenant_id,
            ConnectorSyncCheckpoint.checkpoint_id == checkpoint_id,
        )
        return self.session.scalar(statement)

    def get_connector_sync_checkpoint_claim_by_idempotency(
        self,
        tenant_id: str,
        checkpoint_id: str,
        idempotency_key: str,
    ) -> ConnectorSyncCheckpointClaim | None:
        statement: Select[tuple[ConnectorSyncCheckpointClaim]] = select(
            ConnectorSyncCheckpointClaim
        ).where(
            ConnectorSyncCheckpointClaim.tenant_id == tenant_id,
            ConnectorSyncCheckpointClaim.checkpoint_id == checkpoint_id,
            ConnectorSyncCheckpointClaim.idempotency_key == idempotency_key,
        )
        return self.session.scalar(statement)

    def get_connector_sync_checkpoint_claim(
        self,
        tenant_id: str,
        checkpoint_id: str,
        claim_id: str,
    ) -> ConnectorSyncCheckpointClaim | None:
        statement: Select[tuple[ConnectorSyncCheckpointClaim]] = select(
            ConnectorSyncCheckpointClaim
        ).where(
            ConnectorSyncCheckpointClaim.tenant_id == tenant_id,
            ConnectorSyncCheckpointClaim.checkpoint_id == checkpoint_id,
            ConnectorSyncCheckpointClaim.claim_id == claim_id,
        )
        return self.session.scalar(statement)

    def list_connector_sync_checkpoint_claims(
        self,
        tenant_id: str,
        checkpoint_id: str | None = None,
        connector_id: str | None = None,
        run_id: str | None = None,
        status: str | None = None,
        claimed_by: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        cursor_created_at: datetime | None = None,
        cursor_row_id: UUID | None = None,
        limit: int = 100,
    ) -> list[ConnectorSyncCheckpointClaim]:
        statement: Select[tuple[ConnectorSyncCheckpointClaim]] = select(
            ConnectorSyncCheckpointClaim
        ).where(ConnectorSyncCheckpointClaim.tenant_id == tenant_id)
        if checkpoint_id is not None:
            statement = statement.where(ConnectorSyncCheckpointClaim.checkpoint_id == checkpoint_id)
        if connector_id is not None:
            statement = statement.where(ConnectorSyncCheckpointClaim.connector_id == connector_id)
        if run_id is not None:
            statement = statement.where(ConnectorSyncCheckpointClaim.run_id == run_id)
        if status is not None:
            statement = statement.where(ConnectorSyncCheckpointClaim.status == status)
        if claimed_by is not None:
            statement = statement.where(ConnectorSyncCheckpointClaim.claimed_by == claimed_by)
        if created_after is not None:
            statement = statement.where(ConnectorSyncCheckpointClaim.created_at > created_after)
        if created_before is not None:
            statement = statement.where(ConnectorSyncCheckpointClaim.created_at < created_before)
        if cursor_created_at is not None and cursor_row_id is not None:
            statement = statement.where(
                or_(
                    ConnectorSyncCheckpointClaim.created_at > cursor_created_at,
                    and_(
                        ConnectorSyncCheckpointClaim.created_at == cursor_created_at,
                        ConnectorSyncCheckpointClaim.id > cursor_row_id,
                    ),
                )
            )
        statement = statement.order_by(
            ConnectorSyncCheckpointClaim.created_at.asc(),
            ConnectorSyncCheckpointClaim.id.asc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def create_connector_sync_checkpoint_claim(
        self,
        record: ConnectorSyncCheckpointClaimCreate,
    ) -> ConnectorSyncCheckpointClaim:
        claim = ConnectorSyncCheckpointClaim(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            run_id=record.run_id,
            checkpoint_id=record.checkpoint_id,
            claim_id=record.claim_id,
            status=record.status,
            claimed_by=record.claimed_by,
            idempotency_key=record.idempotency_key,
            lease_duration_seconds=record.lease_duration_seconds,
            lease_expires_at=record.lease_expires_at,
            claim_result=record.claim_result,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            notes=record.notes,
        )
        self.session.add(claim)
        self.session.flush()
        return claim

    def renew_connector_sync_checkpoint_claim(
        self,
        record: ConnectorSyncCheckpointClaimRenewalRecord,
    ) -> ConnectorSyncCheckpointClaim:
        claim = self.get_connector_sync_checkpoint_claim(
            record.tenant_id,
            record.checkpoint_id,
            record.claim_id,
        )
        if claim is None:
            raise PersistenceRecordNotFound("Connector sync checkpoint claim not found")
        claim.status = "claimed"
        claim.renewed_at = record.renewed_at
        claim.renewed_by = record.renewed_by
        claim.renewal_count += 1
        claim.lease_duration_seconds = record.lease_duration_seconds
        claim.lease_expires_at = record.lease_expires_at
        claim.audit_event_id = record.audit_event_id
        claim.audit_event_type = record.audit_event_type
        if record.note is not None:
            claim.notes = [*claim.notes, record.note]
        claim.updated_at = utc_now()
        self.session.flush()
        return claim

    def release_connector_sync_checkpoint_claim(
        self,
        record: ConnectorSyncCheckpointClaimReleaseRecord,
    ) -> ConnectorSyncCheckpointClaim:
        claim = self.get_connector_sync_checkpoint_claim(
            record.tenant_id,
            record.checkpoint_id,
            record.claim_id,
        )
        if claim is None:
            raise PersistenceRecordNotFound("Connector sync checkpoint claim not found")
        claim.status = "released"
        claim.released_at = record.released_at
        claim.released_by = record.released_by
        claim.release_reason = record.release_reason
        claim.audit_event_id = record.audit_event_id
        claim.audit_event_type = record.audit_event_type
        if record.note is not None:
            claim.notes = [*claim.notes, record.note]
        claim.updated_at = utc_now()
        self.session.flush()
        return claim

    def expire_connector_sync_checkpoint_claim(
        self,
        record: ConnectorSyncCheckpointClaimExpirationRecord,
    ) -> ConnectorSyncCheckpointClaim:
        claim = self.get_connector_sync_checkpoint_claim(
            record.tenant_id,
            record.checkpoint_id,
            record.claim_id,
        )
        if claim is None:
            raise PersistenceRecordNotFound("Connector sync checkpoint claim not found")
        claim.status = "expired"
        claim.audit_event_id = record.audit_event_id
        claim.audit_event_type = record.audit_event_type
        if record.note is not None:
            claim.notes = [*claim.notes, record.note]
        claim.updated_at = record.expired_at
        self.session.flush()
        return claim

    def list_connector_sync_checkpoints(
        self,
        tenant_id: str,
        connector_id: str | None = None,
        run_id: str | None = None,
        status: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 100,
    ) -> list[ConnectorSyncCheckpoint]:
        statement: Select[tuple[ConnectorSyncCheckpoint]] = select(ConnectorSyncCheckpoint).where(
            ConnectorSyncCheckpoint.tenant_id == tenant_id
        )
        if connector_id is not None:
            statement = statement.where(ConnectorSyncCheckpoint.connector_id == connector_id)
        if run_id is not None:
            statement = statement.where(ConnectorSyncCheckpoint.run_id == run_id)
        if status is not None:
            statement = statement.where(ConnectorSyncCheckpoint.status == status)
        if created_after is not None:
            statement = statement.where(ConnectorSyncCheckpoint.created_at > created_after)
        if created_before is not None:
            statement = statement.where(ConnectorSyncCheckpoint.created_at < created_before)

        statement = statement.order_by(
            ConnectorSyncCheckpoint.sequence.asc(),
            ConnectorSyncCheckpoint.created_at.asc(),
            ConnectorSyncCheckpoint.id.asc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def count_connector_sync_checkpoints(
        self,
        tenant_id: str,
        run_id: str | None = None,
    ) -> int:
        statement: Select[tuple[int]] = select(func.count(ConnectorSyncCheckpoint.id)).where(
            ConnectorSyncCheckpoint.tenant_id == tenant_id
        )
        if run_id is not None:
            statement = statement.where(ConnectorSyncCheckpoint.run_id == run_id)
        return int(self.session.scalar(statement) or 0)

    def get_latest_connector_sync_checkpoint(
        self,
        tenant_id: str,
        run_id: str,
        connector_id: str | None = None,
        checkpoint_type: str | None = None,
        status: str | None = None,
    ) -> ConnectorSyncCheckpoint | None:
        statement: Select[tuple[ConnectorSyncCheckpoint]] = select(ConnectorSyncCheckpoint).where(
            ConnectorSyncCheckpoint.tenant_id == tenant_id,
            ConnectorSyncCheckpoint.run_id == run_id,
        )
        if connector_id is not None:
            statement = statement.where(ConnectorSyncCheckpoint.connector_id == connector_id)
        if checkpoint_type is not None:
            statement = statement.where(ConnectorSyncCheckpoint.checkpoint_type == checkpoint_type)
        if status is not None:
            statement = statement.where(ConnectorSyncCheckpoint.status == status)
        statement = statement.order_by(
            ConnectorSyncCheckpoint.sequence.desc(),
            ConnectorSyncCheckpoint.created_at.desc(),
            ConnectorSyncCheckpoint.id.desc(),
        ).limit(1)
        return self.session.scalars(statement).first()

    def create_connector_ontology_proposal(
        self,
        record: ConnectorOntologyProposalCreate,
    ) -> ConnectorOntologyProposal:
        proposal = ConnectorOntologyProposal(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            proposal_id=record.proposal_id,
            source_run_id=record.source_run_id,
            source_file_name=record.source_file_name,
            mapping_profile=record.mapping_profile,
            status=record.status,
            write_mode=record.write_mode,
            graph_mutation_status=record.graph_mutation_status,
            proposed_by=record.proposed_by,
            node_id=record.node_id,
            node_type=record.node_type,
            ontology_type=record.ontology_type,
            field_summary=record.field_summary,
            evidence_refs=record.evidence_refs,
            promotion_id=record.promotion_id,
            policy_id=record.policy_id,
            policy_set_id=record.policy_set_id,
            policy_ids=record.policy_ids,
            policy_decision=record.policy_decision,
            promoted_by=record.promoted_by,
            ontology_mutation=record.ontology_mutation,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            notes=record.notes,
        )
        self.session.add(proposal)
        self.session.flush()
        return proposal

    def create_connector_ontology_proposal_if_absent(
        self,
        record: ConnectorOntologyProposalCreate,
    ) -> tuple[ConnectorOntologyProposal, bool]:
        """Insert-or-ignore a proposal on (tenant_id, proposal_id).

        Returns the resulting proposal and whether it was newly created. This
        keeps the dedup guarantee for resumable/idempotent connector sync at the
        write path itself instead of relying only on transaction shape, so a
        duplicate proposal_id never surfaces as an IntegrityError/500.
        """
        insert_stmt = (
            self._insert_with_on_conflict(ConnectorOntologyProposal)
            .values(
                tenant_id=record.tenant_id,
                connector_id=record.connector_id,
                proposal_id=record.proposal_id,
                source_run_id=record.source_run_id,
                source_file_name=record.source_file_name,
                mapping_profile=record.mapping_profile,
                status=record.status,
                write_mode=record.write_mode,
                graph_mutation_status=record.graph_mutation_status,
                proposed_by=record.proposed_by,
                node_id=record.node_id,
                node_type=record.node_type,
                ontology_type=record.ontology_type,
                field_summary=record.field_summary,
                evidence_refs=record.evidence_refs,
                promotion_id=record.promotion_id,
                policy_id=record.policy_id,
                policy_set_id=record.policy_set_id,
                policy_ids=record.policy_ids,
                policy_decision=record.policy_decision,
                promoted_by=record.promoted_by,
                ontology_mutation=record.ontology_mutation,
                audit_event_id=record.audit_event_id,
                audit_event_type=record.audit_event_type,
                notes=record.notes,
            )
            .on_conflict_do_nothing(
                index_elements=["tenant_id", "proposal_id"],
            )
        )
        result = self.session.execute(insert_stmt)
        self.session.flush()
        created = result.rowcount != 0
        proposal = self.get_connector_ontology_proposal(
            record.tenant_id,
            record.proposal_id,
        )
        if proposal is None:  # pragma: no cover - insert or existing row guarantees a match
            raise PersistenceRecordNotFound("Connector ontology proposal not found")
        return proposal, created

    def get_connector_ontology_proposal(
        self,
        tenant_id: str,
        proposal_id: str,
    ) -> ConnectorOntologyProposal | None:
        statement = select(ConnectorOntologyProposal).where(
            ConnectorOntologyProposal.tenant_id == tenant_id,
            ConnectorOntologyProposal.proposal_id == proposal_id,
        )
        return self.session.scalars(statement).first()

    def list_connector_ontology_proposals(
        self,
        tenant_id: str,
        connector_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ConnectorOntologyProposal]:
        statement: Select[tuple[ConnectorOntologyProposal]] = select(
            ConnectorOntologyProposal
        ).where(ConnectorOntologyProposal.tenant_id == tenant_id)
        if connector_id is not None:
            statement = statement.where(ConnectorOntologyProposal.connector_id == connector_id)
        if status is not None:
            statement = statement.where(ConnectorOntologyProposal.status == status)

        statement = statement.order_by(
            ConnectorOntologyProposal.created_at.desc(),
            ConnectorOntologyProposal.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def create_connector_ontology_promotion(
        self,
        record: ConnectorOntologyPromotionCreate,
    ) -> ConnectorOntologyPromotion:
        promotion = ConnectorOntologyPromotion(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            promotion_id=record.promotion_id,
            idempotency_key=record.idempotency_key,
            proposal_id=record.proposal_id,
            manual_import_id=record.manual_import_id,
            status=record.status,
            promotion_mode=record.promotion_mode,
            requested_by=record.requested_by,
            graph_mutation_status=record.graph_mutation_status,
            ontology_mutation=record.ontology_mutation,
            permission_decision=record.permission_decision,
            policy_id=record.policy_id,
            policy_set_id=record.policy_set_id,
            policy_ids=record.policy_ids,
            policy_decision=record.policy_decision,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            notes=record.notes,
        )
        self.session.add(promotion)
        self.session.flush()
        return promotion

    def get_connector_ontology_promotion_by_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> ConnectorOntologyPromotion | None:
        statement = select(ConnectorOntologyPromotion).where(
            ConnectorOntologyPromotion.tenant_id == tenant_id,
            ConnectorOntologyPromotion.idempotency_key == idempotency_key,
        )
        return self.session.scalars(statement).first()

    def list_connector_ontology_promotions(
        self,
        tenant_id: str,
        proposal_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ConnectorOntologyPromotion]:
        statement: Select[tuple[ConnectorOntologyPromotion]] = select(
            ConnectorOntologyPromotion
        ).where(ConnectorOntologyPromotion.tenant_id == tenant_id)
        if proposal_id is not None:
            statement = statement.where(ConnectorOntologyPromotion.proposal_id == proposal_id)
        if status is not None:
            statement = statement.where(ConnectorOntologyPromotion.status == status)

        statement = statement.order_by(
            ConnectorOntologyPromotion.created_at.desc(),
            ConnectorOntologyPromotion.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def iter_connector_ontology_lineage_promotions(
        self,
        tenant_id: str,
        proposal_ids: list[str],
    ) -> Iterator[tuple[str, str, str, str, str, datetime]]:
        if not proposal_ids:
            return

        # Rank within each proposal before limiting: a global LIMIT would let
        # a busy proposal hide another proposal's promotion history.
        promotion = ConnectorOntologyPromotion
        ranked = select(
            promotion.id,
            func.row_number().over(
                partition_by=promotion.proposal_id,
                order_by=(promotion.created_at.desc(), promotion.id.desc()),
            ).label("position"),
        ).where(
            promotion.tenant_id == tenant_id,
            promotion.proposal_id.in_(proposal_ids),
        ).subquery()
        # Lineage needs neither the mutation payload nor policy/audit JSON.
        # Stream the projection so a full history does not retain 10,000 ORM objects.
        statement = select(
            promotion.proposal_id,
            promotion.promotion_id,
            promotion.status,
            promotion.promotion_mode,
            promotion.requested_by,
            promotion.created_at,
        ).join(ranked, promotion.id == ranked.c.id).where(
            promotion.tenant_id == tenant_id,
            ranked.c.position <= 50,
        )
        yield from self.session.execute(statement.execution_options(yield_per=100)).tuples()

    def record_connector_ontology_proposal_promotion(
        self,
        record: ConnectorOntologyPromotionResultRecord,
    ) -> ConnectorOntologyProposal:
        proposal = self.get_connector_ontology_proposal(record.tenant_id, record.proposal_id)
        if proposal is None:
            raise PersistenceRecordNotFound("Connector ontology proposal not found")

        proposal.status = record.status
        proposal.graph_mutation_status = record.graph_mutation_status
        proposal.promotion_id = record.promotion_id
        proposal.policy_id = record.policy_id
        proposal.policy_set_id = record.policy_set_id
        proposal.policy_ids = record.policy_ids
        proposal.policy_decision = record.policy_decision
        proposal.promoted_by = record.promoted_by
        proposal.promoted_at = utc_now()
        proposal.ontology_mutation = record.ontology_mutation
        if record.audit_event_id is not None:
            proposal.audit_event_id = record.audit_event_id
        if record.audit_event_type is not None:
            proposal.audit_event_type = record.audit_event_type
        proposal.updated_at = utc_now()
        self.session.flush()
        return proposal

    def create_connector_promotion_policy(
        self,
        record: ConnectorPromotionPolicyCreate,
    ) -> ConnectorPromotionPolicy:
        policy = ConnectorPromotionPolicy(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            policy_id=record.policy_id,
            policy_version=record.policy_version,
            status=record.status,
            enforcement_mode=record.enforcement_mode,
            created_by=record.created_by,
            required_authoring_scope=record.required_authoring_scope,
            required_scopes=record.required_scopes,
            required_manual_import_status=record.required_manual_import_status,
            required_workflow_signal_status=record.required_workflow_signal_status,
            allowed_risk_levels=record.allowed_risk_levels,
            allowed_ontology_types=record.allowed_ontology_types,
            review_window_hours=record.review_window_hours,
            permission_decision=record.permission_decision,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            revises_policy_id=record.revises_policy_id,
            replaced_by_policy_id=record.replaced_by_policy_id,
            revision_idempotency_key=record.revision_idempotency_key,
            revision_approval_id=record.revision_approval_id,
            revision_decision=record.revision_decision,
            revision_workflow_signal_status=record.revision_workflow_signal_status,
            notes=record.notes,
        )
        self.session.add(policy)
        self.session.flush()
        return policy

    def get_connector_promotion_policy(
        self,
        tenant_id: str,
        policy_id: str,
    ) -> ConnectorPromotionPolicy | None:
        statement = select(ConnectorPromotionPolicy).where(
            ConnectorPromotionPolicy.tenant_id == tenant_id,
            ConnectorPromotionPolicy.policy_id == policy_id,
        )
        return self.session.scalars(statement).first()

    def get_connector_promotion_policy_by_revision_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> ConnectorPromotionPolicy | None:
        statement = select(ConnectorPromotionPolicy).where(
            ConnectorPromotionPolicy.tenant_id == tenant_id,
            ConnectorPromotionPolicy.revision_idempotency_key == idempotency_key,
        )
        return self.session.scalars(statement).first()

    def revise_connector_promotion_policy(
        self,
        policy: ConnectorPromotionPolicy,
        record: ConnectorPromotionPolicyCreate,
    ) -> ConnectorPromotionPolicy:
        policy.status = "superseded"
        policy.replaced_by_policy_id = record.policy_id
        policy.updated_at = utc_now()
        revised_policy = self.create_connector_promotion_policy(record)
        self.session.flush()
        return revised_policy

    def enable_connector_promotion_policy(
        self,
        record: ConnectorPromotionPolicyEnableRecord,
    ) -> ConnectorPromotionPolicy:
        policy = self.get_connector_promotion_policy(record.tenant_id, record.policy_id)
        if policy is None:
            raise PersistenceRecordNotFound("Connector promotion policy not found")

        policy.status = record.status
        policy.enforcement_mode = record.enforcement_mode
        policy.permission_decision = record.permission_decision
        policy.audit_event_id = record.audit_event_id
        policy.audit_event_type = record.audit_event_type
        if record.note:
            policy.notes = [*policy.notes, record.note]
        policy.updated_at = utc_now()
        self.session.flush()
        return policy

    def adopt_connector_promotion_policy_revision(
        self,
        current_policy: ConnectorPromotionPolicy,
        revised_policy: ConnectorPromotionPolicy,
        *,
        audit_event_id: UUID,
        audit_event_type: str,
        note: str,
    ) -> ConnectorPromotionPolicy:
        current_policy.status = "superseded"
        current_policy.replaced_by_policy_id = revised_policy.policy_id
        current_policy.updated_at = utc_now()

        revised_policy.status = "enabled"
        revised_policy.enforcement_mode = "required"
        revised_policy.audit_event_id = audit_event_id
        revised_policy.audit_event_type = audit_event_type
        revised_policy.notes = [*revised_policy.notes, note]
        revised_policy.updated_at = utc_now()
        self.session.flush()
        return revised_policy

    def list_connector_promotion_policies(
        self,
        tenant_id: str,
        connector_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ConnectorPromotionPolicy]:
        statement: Select[tuple[ConnectorPromotionPolicy]] = select(ConnectorPromotionPolicy).where(
            ConnectorPromotionPolicy.tenant_id == tenant_id
        )
        if connector_id is not None:
            statement = statement.where(ConnectorPromotionPolicy.connector_id == connector_id)
        if status is not None:
            statement = statement.where(ConnectorPromotionPolicy.status == status)

        statement = statement.order_by(
            ConnectorPromotionPolicy.created_at.desc(),
            ConnectorPromotionPolicy.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def create_connector_promotion_policy_set(
        self,
        record: ConnectorPromotionPolicySetCreate,
    ) -> ConnectorPromotionPolicySet:
        policy_set = ConnectorPromotionPolicySet(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            policy_set_id=record.policy_set_id,
            policy_set_version=record.policy_set_version,
            status=record.status,
            activated_by=record.activated_by,
            activation_scope=record.activation_scope,
            policy_ids=record.policy_ids,
            permission_decision=record.permission_decision,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            activation_reason=record.activation_reason,
            replaces_policy_set_id=record.replaces_policy_set_id,
            replaced_by_policy_set_id=record.replaced_by_policy_set_id,
            replacement_approval_id=record.replacement_approval_id,
            replacement_decision=record.replacement_decision,
            replacement_workflow_signal_status=record.replacement_workflow_signal_status,
            replaced_at=record.replaced_at,
            rollback_to_policy_set_id=record.rollback_to_policy_set_id,
            rollback_approval_id=record.rollback_approval_id,
            rollback_decision=record.rollback_decision,
            rollback_workflow_signal_status=record.rollback_workflow_signal_status,
            policy_revision_adoptions=record.policy_revision_adoptions,
            notes=record.notes,
        )
        self.session.add(policy_set)
        self.session.flush()
        return policy_set

    def replace_connector_promotion_policy_set(
        self,
        active_policy_set: ConnectorPromotionPolicySet,
        record: ConnectorPromotionPolicySetCreate,
    ) -> ConnectorPromotionPolicySet:
        replaced_at = utc_now()
        active_policy_set.status = "superseded"
        active_policy_set.replaced_by_policy_set_id = record.policy_set_id
        active_policy_set.replacement_approval_id = (
            record.replacement_approval_id or record.rollback_approval_id
        )
        active_policy_set.replacement_decision = (
            record.replacement_decision or record.rollback_decision
        )
        active_policy_set.replacement_workflow_signal_status = (
            record.replacement_workflow_signal_status or record.rollback_workflow_signal_status
        )
        active_policy_set.replaced_at = replaced_at
        policy_set = self.create_connector_promotion_policy_set(
            record.model_copy(
                update={
                    "replaces_policy_set_id": active_policy_set.policy_set_id,
                    "replaced_at": None,
                }
            )
        )
        self.session.flush()
        return policy_set

    def get_connector_promotion_policy_set(
        self,
        tenant_id: str,
        policy_set_id: str,
    ) -> ConnectorPromotionPolicySet | None:
        statement = select(ConnectorPromotionPolicySet).where(
            ConnectorPromotionPolicySet.tenant_id == tenant_id,
            ConnectorPromotionPolicySet.policy_set_id == policy_set_id,
        )
        return self.session.scalars(statement).first()

    def list_connector_promotion_policy_sets(
        self,
        tenant_id: str,
        connector_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ConnectorPromotionPolicySet]:
        statement: Select[tuple[ConnectorPromotionPolicySet]] = select(
            ConnectorPromotionPolicySet
        ).where(ConnectorPromotionPolicySet.tenant_id == tenant_id)
        if connector_id is not None:
            statement = statement.where(ConnectorPromotionPolicySet.connector_id == connector_id)
        if status is not None:
            statement = statement.where(ConnectorPromotionPolicySet.status == status)

        statement = statement.order_by(
            ConnectorPromotionPolicySet.created_at.desc(),
            ConnectorPromotionPolicySet.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def list_active_connector_promotion_policy_sets(
        self,
        tenant_id: str,
        connector_id: str,
    ) -> list[ConnectorPromotionPolicySet]:
        return self.list_connector_promotion_policy_sets(
            tenant_id=tenant_id,
            connector_id=connector_id,
            status="active",
            limit=20,
        )

    def create_tenant(self, record: TenantCreate) -> Tenant:
        tenant = Tenant(
            id=record.tenant_id,
            name=record.display_name,
            description=record.description,
            status=record.status,
            created_by=record.created_by,
            bootstrap_admin_actor_id=record.bootstrap_admin_actor_id,
            provision_idempotency_key=record.provision_idempotency_key,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            notes=record.notes,
        )
        self.session.add(tenant)
        self.session.flush()
        return tenant

    def acquire_first_tenant_bootstrap_lock(self) -> None:
        """Serialize the one permitted empty-registry bootstrap transaction."""

        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "postgresql":
            self.session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtextextended("axis:first-tenant-bootstrap", 0)
                    )
                )
            )
            return
        if dialect_name == "sqlite":
            # SQLite has no advisory locks. A no-op write takes database write
            # intent before the empty-registry read, closing the two-bootstrap
            # race in local/test profiles.
            self.session.execute(
                update(Tenant)
                .where(Tenant.id == "__axis_first_tenant_bootstrap_lock__")
                .values(updated_at=Tenant.updated_at)
            )
            return
        raise NotImplementedError(
            f"First-tenant bootstrap locking is not supported for dialect {dialect_name!r}."
        )

    def get_tenant(self, tenant_id: str) -> Tenant | None:
        return self.session.get(Tenant, tenant_id)

    def get_tenant_by_provision_idempotency_key(
        self,
        idempotency_key: str,
    ) -> Tenant | None:
        statement: Select[tuple[Tenant]] = select(Tenant).where(
            Tenant.provision_idempotency_key == idempotency_key
        )
        return self.session.scalar(statement)

    def list_tenants(
        self,
        status: str | None = None,
        limit: int = 100,
        cursor_tenant_id: str | None = None,
    ) -> list[Tenant]:
        statement: Select[tuple[Tenant]] = select(Tenant)
        if status is not None:
            statement = statement.where(Tenant.status == status)
        if cursor_tenant_id is not None:
            # Keyset continuation: resume strictly after the cursor row in
            # (id asc) order. The id is the primary key, so this is a total
            # order and needs no secondary sort key.
            statement = statement.where(Tenant.id > cursor_tenant_id)
        statement = statement.order_by(Tenant.id.asc()).limit(limit)
        return list(self.session.scalars(statement))

    def list_tenants_after(
        self,
        cursor_tenant_id: str | None = None,
        limit: int = 500,
    ) -> list[Tenant]:
        """Keyset page of tenants ordered by id, resuming strictly after cursor.

        Used by the scheduled jobs to page through every tenant without silently
        truncating at a fixed limit.
        """
        statement: Select[tuple[Tenant]] = select(Tenant)
        if cursor_tenant_id is not None:
            statement = statement.where(Tenant.id > cursor_tenant_id)
        statement = statement.order_by(Tenant.id.asc()).limit(limit)
        return list(self.session.scalars(statement))

    def update_tenant_lifecycle(self, transition: TenantLifecycleTransition) -> Tenant:
        tenant = self.get_tenant(transition.tenant_id)
        if tenant is None:
            raise PersistenceRecordNotFound()
        occurred_at = utc_now()
        tenant.status = transition.status
        if transition.status == "active":
            tenant.suspended_at = None
            tenant.suspended_by = None
            tenant.suspension_reason = None
            tenant.reactivated_at = occurred_at
            tenant.reactivated_by = transition.actor_id
        else:
            tenant.suspended_at = occurred_at
            tenant.suspended_by = transition.actor_id
            tenant.suspension_reason = transition.reason
            tenant.reactivated_at = None
            tenant.reactivated_by = None
        tenant.audit_event_id = transition.audit_event_id
        tenant.audit_event_type = transition.audit_event_type
        tenant.notes = [*tenant.notes, *transition.notes]
        tenant.updated_at = occurred_at
        self.session.flush()
        return tenant

    def get_tenant_quota(self, tenant_id: str, quota_key: str) -> TenantQuota | None:
        statement: Select[tuple[TenantQuota]] = select(TenantQuota).where(
            TenantQuota.tenant_id == tenant_id,
            TenantQuota.quota_key == quota_key,
        )
        return self.session.scalar(statement)

    def list_tenant_quotas(self, tenant_id: str) -> list[TenantQuota]:
        statement: Select[tuple[TenantQuota]] = (
            select(TenantQuota)
            .where(TenantQuota.tenant_id == tenant_id)
            .order_by(TenantQuota.quota_key.asc())
        )
        return list(self.session.scalars(statement))

    def upsert_tenant_quota(self, record: TenantQuotaUpsert) -> TenantQuota:
        quota = self.get_tenant_quota(record.tenant_id, record.quota_key)
        if quota is None:
            quota = TenantQuota(
                tenant_id=record.tenant_id,
                quota_key=record.quota_key,
                quota_value=record.quota_value,
                updated_by=record.updated_by,
                audit_event_id=record.audit_event_id,
                audit_event_type=record.audit_event_type,
                notes=record.notes,
            )
            self.session.add(quota)
        else:
            quota.quota_value = record.quota_value
            quota.updated_by = record.updated_by
            quota.audit_event_id = record.audit_event_id
            quota.audit_event_type = record.audit_event_type
            quota.notes = record.notes
            quota.updated_at = utc_now()
        self.session.flush()
        return quota

    def delete_tenant_quota(self, tenant_id: str, quota_key: str) -> bool:
        quota = self.get_tenant_quota(tenant_id, quota_key)
        if quota is None:
            return False
        self.session.delete(quota)
        self.session.flush()
        return True

    def update_tenant_vocabulary(self, tenant_id: str, vocabulary: dict) -> Tenant:
        tenant = self.get_tenant(tenant_id)
        if tenant is None:
            raise PersistenceRecordNotFound()
        tenant.vocabulary = vocabulary
        tenant.updated_at = utc_now()
        self.session.flush()
        return tenant

    def add_tenant_usage(self, record: TenantUsageAdd) -> None:
        """Fold a consumption delta into the (tenant, metric, period) ledger row.

        This is an upsert-add: the first delta for a bucket inserts the row, later
        deltas increment ``quantity`` in place via ``ON CONFLICT DO UPDATE`` with
        ``quantity = quantity + excluded.quantity``. The add happens in a single
        SQL statement under a row lock, so concurrent flushers, replicas and the
        synchronous choke-point recorders can all target the same bucket without
        losing or double-counting deltas. ``first_recorded_at`` is preserved on
        conflict; ``last_recorded_at``/``updated_at`` advance to the new delta.
        """
        now = utc_now()
        insert_stmt = self._insert_with_on_conflict(TenantUsageRecord).values(
            id=uuid4(),
            tenant_id=record.tenant_id,
            metric_key=record.metric_key,
            period_start=record.period_start,
            period_window_seconds=record.period_window_seconds,
            quantity=record.quantity,
            dimensions={},
            first_recorded_at=record.first_occurred_at,
            last_recorded_at=record.last_occurred_at,
            created_at=now,
            updated_at=now,
        )
        statement = insert_stmt.on_conflict_do_update(
            index_elements=[
                "tenant_id",
                "metric_key",
                "period_window_seconds",
                "period_start",
            ],
            set_={
                "quantity": TenantUsageRecord.quantity + insert_stmt.excluded.quantity,
                "first_recorded_at": case(
                    (
                        TenantUsageRecord.first_recorded_at
                        <= insert_stmt.excluded.first_recorded_at,
                        TenantUsageRecord.first_recorded_at,
                    ),
                    else_=insert_stmt.excluded.first_recorded_at,
                ),
                "last_recorded_at": case(
                    (
                        TenantUsageRecord.last_recorded_at >= insert_stmt.excluded.last_recorded_at,
                        TenantUsageRecord.last_recorded_at,
                    ),
                    else_=insert_stmt.excluded.last_recorded_at,
                ),
                "dimensions": insert_stmt.excluded.dimensions,
                "updated_at": insert_stmt.excluded.updated_at,
            },
        )
        self.session.execute(statement)
        self.session.flush()

    def get_tenant_usage_event_by_source(
        self,
        tenant_id: str,
        metric_key: str,
        source_type: str,
        source_id: str,
    ) -> TenantUsageEvent | None:
        return self.session.scalar(
            select(TenantUsageEvent).where(
                TenantUsageEvent.tenant_id == tenant_id,
                TenantUsageEvent.metric_key == metric_key,
                TenantUsageEvent.source_type == source_type,
                TenantUsageEvent.source_id == source_id,
            )
        )

    def append_tenant_usage_event(
        self,
        event: TenantUsageEventAppend,
        *,
        project_immediately: bool = True,
    ) -> bool:
        """Append and aggregate a source event exactly once in this transaction.

        A retry with the same source identity is a no-op only when its billing
        payload matches the original event. Reusing an identity for a different
        quantity, period, window, or dimensions is an explicit invariant error.
        """

        now = utc_now()
        insert_stmt = self._insert_with_on_conflict(TenantUsageEvent).values(
            id=event.event_id,
            tenant_id=event.tenant_id,
            metric_key=event.metric_key,
            source_type=event.source_type,
            source_id=event.source_id,
            period_start=event.period_start,
            period_window_seconds=event.period_window_seconds,
            quantity=event.quantity,
            dimensions=event.dimensions,
            occurred_at=event.occurred_at,
            recorded_at=now,
            projected_at=now if project_immediately else None,
        )
        statement = insert_stmt.on_conflict_do_nothing(
            index_elements=["tenant_id", "metric_key", "source_type", "source_id"]
        ).returning(TenantUsageEvent.id)
        inserted_id = self.session.execute(statement).scalar_one_or_none()
        if inserted_id is None:
            existing = self.get_tenant_usage_event_by_source(
                event.tenant_id,
                event.metric_key,
                event.source_type,
                event.source_id,
            )
            if existing is None:
                raise RuntimeError("Usage event conflict did not resolve to an existing row.")
            if (
                existing.quantity != event.quantity
                or _utc_datetime(existing.period_start) != _utc_datetime(event.period_start)
                or existing.period_window_seconds != event.period_window_seconds
                or _utc_datetime(existing.occurred_at) != _utc_datetime(event.occurred_at)
                or existing.dimensions != event.dimensions
            ):
                raise TenantUsageIdempotencyConflict(
                    "Usage event source identity was reused with a different payload."
                )
            return False

        if project_immediately:
            self.add_tenant_usage(
                TenantUsageAdd(
                    tenant_id=event.tenant_id,
                    metric_key=event.metric_key,
                    period_start=event.period_start,
                    period_window_seconds=event.period_window_seconds,
                    quantity=event.quantity,
                    first_occurred_at=event.occurred_at,
                    last_occurred_at=event.occurred_at,
                )
            )
        return True

    def project_pending_tenant_usage_events(
        self,
        *,
        batch_size: int,
    ) -> TenantUsageProjectionResult:
        """Claim and fold one pending event batch in the current transaction."""

        candidate_ids = (
            select(TenantUsageEvent.id)
            .where(TenantUsageEvent.projected_at.is_(None))
            .order_by(TenantUsageEvent.recorded_at.asc(), TenantUsageEvent.id.asc())
            .limit(batch_size)
        )
        if self.session.get_bind().dialect.name == "postgresql":
            candidate_ids = candidate_ids.with_for_update(skip_locked=True)
        projected_at = utc_now()
        claim = (
            update(TenantUsageEvent)
            .where(
                TenantUsageEvent.id.in_(candidate_ids),
                TenantUsageEvent.projected_at.is_(None),
            )
            .values(projected_at=projected_at)
            .returning(
                TenantUsageEvent.tenant_id,
                TenantUsageEvent.metric_key,
                TenantUsageEvent.period_window_seconds,
                TenantUsageEvent.period_start,
                TenantUsageEvent.quantity,
                TenantUsageEvent.occurred_at,
            )
        )
        rows = list(self.session.execute(claim))
        buckets: dict[
            tuple[str, str, int, datetime],
            tuple[int, datetime, datetime],
        ] = {}
        for (
            tenant_id,
            metric_key,
            period_window_seconds,
            period_start,
            quantity,
            occurred_at,
        ) in rows:
            key = (
                tenant_id,
                metric_key,
                period_window_seconds,
                period_start,
            )
            current = buckets.get(key)
            if current is None:
                buckets[key] = (quantity, occurred_at, occurred_at)
                continue
            current_quantity, first_occurred_at, last_occurred_at = current
            buckets[key] = (
                current_quantity + quantity,
                min(first_occurred_at, occurred_at),
                max(last_occurred_at, occurred_at),
            )
        for (
            tenant_id,
            metric_key,
            period_window_seconds,
            period_start,
        ), (
            quantity,
            first_occurred_at,
            last_occurred_at,
        ) in sorted(buckets.items()):
            self.add_tenant_usage(
                TenantUsageAdd(
                    tenant_id=tenant_id,
                    metric_key=metric_key,
                    period_start=period_start,
                    period_window_seconds=period_window_seconds,
                    quantity=quantity,
                    first_occurred_at=first_occurred_at,
                    last_occurred_at=last_occurred_at,
                )
            )
        return TenantUsageProjectionResult(
            events_projected=len(rows),
            quantity_projected=sum(int(row.quantity) for row in rows),
        )

    def oldest_pending_tenant_usage_event_at(self) -> datetime | None:
        return self.session.scalar(
            select(TenantUsageEvent.recorded_at)
            .where(TenantUsageEvent.projected_at.is_(None))
            .order_by(TenantUsageEvent.recorded_at.asc(), TenantUsageEvent.id.asc())
            .limit(1)
        )

    def aggregate_tenant_usage(
        self,
        tenant_id: str,
        *,
        period_window_seconds: int,
        period_start_from: datetime | None = None,
        period_start_to: datetime | None = None,
        metric_keys: list[str] | None = None,
    ) -> list[TenantUsagePeriodTotal]:
        """Return per-(metric, period) totals for a tenant over a period window.

        ``period_start_to`` is an exclusive upper bound. Results are ordered by
        metric then period so the read layer can build a stable breakdown.
        """
        statement = (
            select(
                TenantUsageRecord.metric_key,
                TenantUsageRecord.period_start,
                func.sum(TenantUsageRecord.quantity),
            )
            .where(TenantUsageRecord.tenant_id == tenant_id)
            .where(TenantUsageRecord.period_window_seconds == period_window_seconds)
            .group_by(TenantUsageRecord.metric_key, TenantUsageRecord.period_start)
            .order_by(
                TenantUsageRecord.metric_key.asc(),
                TenantUsageRecord.period_start.asc(),
            )
        )
        if period_start_from is not None:
            statement = statement.where(TenantUsageRecord.period_start >= period_start_from)
        if period_start_to is not None:
            statement = statement.where(TenantUsageRecord.period_start < period_start_to)
        if metric_keys:
            statement = statement.where(TenantUsageRecord.metric_key.in_(metric_keys))
        return [
            TenantUsagePeriodTotal(
                metric_key=metric_key,
                period_start=period_start,
                quantity=int(quantity or 0),
            )
            for metric_key, period_start, quantity in self.session.execute(statement)
        ]

    def get_actor(self, actor_id: str) -> Actor | None:
        return self.session.get(Actor, actor_id)

    def create_actor(self, record: ActorCreate) -> Actor:
        actor = Actor(
            id=record.actor_id,
            tenant_id=record.tenant_id,
            display_name=record.display_name,
            actor_type=record.actor_type,
        )
        self.session.add(actor)
        self.session.flush()
        return actor

    def create_platform_policy(
        self,
        record: PlatformPolicyCreate,
    ) -> PlatformPolicy:
        policy = PlatformPolicy(
            tenant_id=record.tenant_id,
            policy_id=record.policy_id,
            revision_number=record.revision_number,
            policy_version=record.policy_version,
            display_name=record.display_name,
            description=record.description,
            scope=record.scope,
            effect=record.effect,
            conditions=record.conditions,
            status=record.status,
            created_by=record.created_by,
            required_authoring_scope=record.required_authoring_scope,
            permission_decision=record.permission_decision,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            revises_revision_number=record.revises_revision_number,
            replaced_by_revision_number=record.replaced_by_revision_number,
            revision_idempotency_key=record.revision_idempotency_key,
            notes=record.notes,
        )
        self.session.add(policy)
        self.session.flush()
        return policy

    def get_platform_policy(
        self,
        tenant_id: str,
        policy_id: str,
    ) -> PlatformPolicy | None:
        statement = (
            select(PlatformPolicy)
            .where(
                PlatformPolicy.tenant_id == tenant_id,
                PlatformPolicy.policy_id == policy_id,
            )
            .order_by(PlatformPolicy.revision_number.desc())
        )
        return self.session.scalars(statement).first()

    def get_platform_policy_by_revision_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> PlatformPolicy | None:
        statement = select(PlatformPolicy).where(
            PlatformPolicy.tenant_id == tenant_id,
            PlatformPolicy.revision_idempotency_key == idempotency_key,
        )
        return self.session.scalars(statement).first()

    def append_platform_policy_revision(
        self,
        current_policy: PlatformPolicy,
        record: PlatformPolicyCreate,
    ) -> PlatformPolicy:
        current_policy.status = "superseded"
        current_policy.replaced_by_revision_number = record.revision_number
        current_policy.updated_at = utc_now()
        # Flush the supersede update before inserting the replacement revision so
        # the single-active-revision partial unique index never sees two active rows.
        self.session.flush()
        return self.create_platform_policy(record)

    def list_platform_policies(
        self,
        tenant_id: str,
        scope: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[PlatformPolicy]:
        statement: Select[tuple[PlatformPolicy]] = select(PlatformPolicy).where(
            PlatformPolicy.tenant_id == tenant_id
        )
        if scope is not None:
            statement = statement.where(PlatformPolicy.scope == scope)
        if status is not None:
            statement = statement.where(PlatformPolicy.status == status)

        statement = statement.order_by(
            PlatformPolicy.policy_id.asc(),
            PlatformPolicy.revision_number.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def list_platform_policy_revisions(
        self,
        tenant_id: str,
        policy_id: str,
    ) -> list[PlatformPolicy]:
        statement = (
            select(PlatformPolicy)
            .where(
                PlatformPolicy.tenant_id == tenant_id,
                PlatformPolicy.policy_id == policy_id,
            )
            .order_by(PlatformPolicy.revision_number.asc())
        )
        return list(self.session.scalars(statement))

    def create_model_endpoint(self, record: ModelEndpointCreate) -> ModelEndpoint:
        return self._models.create_model_endpoint(record)

    def get_model_endpoint(
        self,
        tenant_id: str,
        endpoint_id: str,
    ) -> ModelEndpoint | None:
        return self._models.get_model_endpoint(tenant_id, endpoint_id)

    def list_model_endpoints(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ModelEndpoint]:
        return self._models.list_model_endpoints(tenant_id, status, limit)

    def update_model_endpoint_status(
        self,
        record: ModelEndpointStatusUpdate,
    ) -> ModelEndpoint:
        return self._models.update_model_endpoint_status(record)

    def create_model_invocation(self, record: ModelInvocationCreate) -> ModelInvocation:
        return self._models.create_model_invocation(record)

    def get_model_invocation(
        self,
        tenant_id: str,
        invocation_id: UUID,
    ) -> ModelInvocation | None:
        return self._models.get_model_invocation(tenant_id, invocation_id)

    def get_model_invocation_by_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> ModelInvocation | None:
        return self._models.get_model_invocation_by_idempotency_key(tenant_id, idempotency_key)

    def record_model_invocation_result(
        self,
        result: ModelInvocationResultRecord,
    ) -> ModelInvocation:
        return self._models.record_model_invocation_result(result)

    def list_model_invocations(
        self,
        tenant_id: str,
        cursor_created_at: datetime | None = None,
        cursor_row_id: UUID | None = None,
        limit: int = 100,
    ) -> list[ModelInvocation]:
        return self._models.list_model_invocations(
            tenant_id, cursor_created_at, cursor_row_id, limit,
        )

    def list_active_platform_policies_for_scope(
        self,
        tenant_id: str,
        scope: str,
    ) -> list[PlatformPolicy]:
        statement = (
            select(PlatformPolicy)
            .where(
                PlatformPolicy.tenant_id == tenant_id,
                PlatformPolicy.scope == scope,
                PlatformPolicy.status == "active",
            )
            .order_by(
                PlatformPolicy.policy_id.asc(),
                PlatformPolicy.revision_number.desc(),
            )
        )
        return list(self.session.scalars(statement))

    def create_agent_run(self, record: AgentRunCreate) -> AgentRun:
        agent_run = AgentRun(
            tenant_id=record.tenant_id,
            agent_id=record.agent_id,
            idempotency_key=record.idempotency_key,
            status=record.status,
            mode=record.mode,
            requested_by=record.requested_by,
            autonomy_level=record.autonomy_level,
            request_fingerprint=record.request_fingerprint,
            context_refs=record.context_refs,
            model_invocation_ids=record.model_invocation_ids,
            permission_decision=record.permission_decision,
            platform_policy_decision=record.platform_policy_decision,
            notes=record.notes,
        )
        self.session.add(agent_run)
        self.session.flush()
        return agent_run

    def get_agent_run(self, tenant_id: str, run_id: UUID) -> AgentRun | None:
        statement: Select[tuple[AgentRun]] = select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.id == run_id,
        )
        return self.session.scalar(statement)

    def get_agent_run_by_idempotency_key(
        self,
        tenant_id: str,
        agent_id: str,
        idempotency_key: str,
    ) -> AgentRun | None:
        statement: Select[tuple[AgentRun]] = select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.agent_id == agent_id,
            AgentRun.idempotency_key == idempotency_key,
        )
        return self.session.scalar(statement)

    def record_agent_run_result(self, result: AgentRunResultRecord) -> AgentRun:
        agent_run = self.get_agent_run(result.tenant_id, result.run_id)
        if agent_run is None:
            raise PersistenceRecordNotFound("Agent run not found")
        agent_run.status = result.status
        if result.context_refs is not None:
            agent_run.context_refs = result.context_refs
        if result.model_invocation_ids is not None:
            agent_run.model_invocation_ids = result.model_invocation_ids
        if result.proposed_action_run_id is not None:
            agent_run.proposed_action_run_id = result.proposed_action_run_id
        if result.proposal_payload is not None:
            agent_run.proposal_payload = result.proposal_payload
        agent_run.error_reason = result.error_reason
        agent_run.audit_event_id = result.audit_event_id
        agent_run.audit_event_type = result.audit_event_type
        if result.notes is not None:
            agent_run.notes = result.notes
        agent_run.updated_at = utc_now()
        self.session.flush()
        return agent_run

    def list_agent_runs(
        self,
        tenant_id: str,
        agent_id: str,
        cursor_created_at: datetime | None = None,
        cursor_row_id: UUID | None = None,
        limit: int = 100,
    ) -> list[AgentRun]:
        statement: Select[tuple[AgentRun]] = select(AgentRun).where(
            AgentRun.tenant_id == tenant_id,
            AgentRun.agent_id == agent_id,
        )
        if cursor_created_at is not None and cursor_row_id is not None:
            # Newest-first keyset continuation: resume strictly after the
            # cursor row in (created_at desc, id desc) order.
            statement = statement.where(
                or_(
                    AgentRun.created_at < cursor_created_at,
                    and_(
                        AgentRun.created_at == cursor_created_at,
                        AgentRun.id < cursor_row_id,
                    ),
                )
            )
        statement = statement.order_by(
            AgentRun.created_at.desc(),
            AgentRun.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def append_agent_run_step(self, record: AgentRunStepCreate) -> AgentRunStep:
        """Append a step to the run timeline; steps are immutable once written."""
        step = AgentRunStep(
            tenant_id=record.tenant_id,
            run_id=record.run_id,
            seq=record.seq,
            step_type=record.step_type,
            status=record.status,
            evidence=record.evidence,
        )
        self.session.add(step)
        self.session.flush()
        return step

    def list_agent_run_steps(self, tenant_id: str, run_id: UUID) -> list[AgentRunStep]:
        statement: Select[tuple[AgentRunStep]] = (
            select(AgentRunStep)
            .where(
                AgentRunStep.tenant_id == tenant_id,
                AgentRunStep.run_id == run_id,
            )
            .order_by(AgentRunStep.seq.asc())
        )
        return list(self.session.scalars(statement))

    def create_connector_manual_import_request(
        self,
        record: ConnectorManualImportRequestCreate,
    ) -> ConnectorManualImportRequest:
        manual_import = ConnectorManualImportRequest(
            tenant_id=record.tenant_id,
            connector_id=record.connector_id,
            import_id=record.import_id,
            idempotency_key=record.idempotency_key,
            status=record.status,
            import_mode=record.import_mode,
            requested_by=record.requested_by,
            owner_role=record.owner_role,
            risk_level=record.risk_level,
            approval_id=record.approval_id,
            workflow_id=record.workflow_id,
            proposal_ids=record.proposal_ids,
            import_summary=record.import_summary,
            controls=record.controls,
            graph_mutation_status=record.graph_mutation_status,
            workflow_signal_status=record.workflow_signal_status,
            decision=record.decision,
            decision_actor_id=record.decision_actor_id,
            decision_note=record.decision_note,
            workflow_signal=record.workflow_signal,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            notes=record.notes,
        )
        self.session.add(manual_import)
        self.session.flush()
        return manual_import

    def get_connector_manual_import_request(
        self,
        tenant_id: str,
        import_id: str,
    ) -> ConnectorManualImportRequest | None:
        statement = select(ConnectorManualImportRequest).where(
            ConnectorManualImportRequest.tenant_id == tenant_id,
            ConnectorManualImportRequest.import_id == import_id,
        )
        return self.session.scalars(statement).first()

    def get_connector_manual_import_request_by_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> ConnectorManualImportRequest | None:
        statement = select(ConnectorManualImportRequest).where(
            ConnectorManualImportRequest.tenant_id == tenant_id,
            ConnectorManualImportRequest.idempotency_key == idempotency_key,
        )
        return self.session.scalars(statement).first()

    def list_connector_manual_import_requests(
        self,
        tenant_id: str,
        connector_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ConnectorManualImportRequest]:
        statement: Select[tuple[ConnectorManualImportRequest]] = select(
            ConnectorManualImportRequest
        ).where(ConnectorManualImportRequest.tenant_id == tenant_id)
        if connector_id is not None:
            statement = statement.where(ConnectorManualImportRequest.connector_id == connector_id)
        if status is not None:
            statement = statement.where(ConnectorManualImportRequest.status == status)

        statement = statement.order_by(
            ConnectorManualImportRequest.created_at.desc(),
            ConnectorManualImportRequest.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def record_connector_manual_import_decision(
        self,
        record: ConnectorManualImportDecisionRecord,
    ) -> ConnectorManualImportRequest:
        manual_import = self.get_connector_manual_import_request(
            record.tenant_id,
            record.import_id,
        )
        if manual_import is None:
            raise PersistenceRecordNotFound("Connector manual import request not found")

        manual_import.status = record.status
        manual_import.decision = record.decision
        manual_import.decision_actor_id = record.decision_actor_id
        manual_import.decision_note = record.decision_note
        manual_import.decided_at = utc_now()
        manual_import.workflow_signal_status = record.workflow_signal_status
        manual_import.workflow_signal = record.workflow_signal
        if record.audit_event_id is not None:
            manual_import.audit_event_id = record.audit_event_id
        if record.audit_event_type is not None:
            manual_import.audit_event_type = record.audit_event_type
        manual_import.updated_at = utc_now()
        self.session.flush()
        return manual_import

    def create_connector_evidence_snapshot_export_request(
        self,
        record: ConnectorEvidenceSnapshotExportRequestCreate,
    ) -> ConnectorEvidenceSnapshotExportRequest:
        export_request = ConnectorEvidenceSnapshotExportRequest(
            tenant_id=record.tenant_id,
            export_request_id=record.export_request_id,
            idempotency_key=record.idempotency_key,
            status=record.status,
            export_status=record.export_status,
            storage_status=record.storage_status,
            requested_by=record.requested_by,
            owner_role=record.owner_role,
            risk_level=record.risk_level,
            approval_id=record.approval_id,
            workflow_id=record.workflow_id,
            connector_id=record.connector_id,
            snapshot_id=record.snapshot_id,
            snapshot_idempotency_key=record.snapshot_idempotency_key,
            export_reason=record.export_reason,
            format=record.format,
            limit=record.limit,
            requested_snapshot_count=record.requested_snapshot_count,
            snapshot_checksum_sha256=record.snapshot_checksum_sha256,
            redaction_policy=record.redaction_policy,
            controls=record.controls,
            permission_decision=record.permission_decision,
            workflow_signal_status=record.workflow_signal_status,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
            notes=record.notes,
        )
        self.session.add(export_request)
        self.session.flush()
        return export_request

    def get_connector_evidence_snapshot_export_request(
        self,
        tenant_id: str,
        export_request_id: str,
    ) -> ConnectorEvidenceSnapshotExportRequest | None:
        statement = select(ConnectorEvidenceSnapshotExportRequest).where(
            ConnectorEvidenceSnapshotExportRequest.tenant_id == tenant_id,
            ConnectorEvidenceSnapshotExportRequest.export_request_id == export_request_id,
        )
        return self.session.scalars(statement).first()

    def get_connector_evidence_snapshot_export_request_by_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> ConnectorEvidenceSnapshotExportRequest | None:
        statement = select(ConnectorEvidenceSnapshotExportRequest).where(
            ConnectorEvidenceSnapshotExportRequest.tenant_id == tenant_id,
            ConnectorEvidenceSnapshotExportRequest.idempotency_key == idempotency_key,
        )
        return self.session.scalars(statement).first()

    def record_connector_evidence_snapshot_export_request_decision(
        self,
        record: ConnectorEvidenceSnapshotExportRequestDecisionRecord,
    ) -> ConnectorEvidenceSnapshotExportRequest:
        export_request = self.get_connector_evidence_snapshot_export_request(
            record.tenant_id,
            record.export_request_id,
        )
        if export_request is None:
            raise PersistenceRecordNotFound("Connector evidence snapshot export request not found")

        export_request.status = record.status
        export_request.export_status = record.export_status
        export_request.decision = record.decision
        export_request.decision_actor_id = record.decision_actor_id
        export_request.decision_note = record.decision_note
        export_request.decided_at = utc_now()
        export_request.workflow_signal_status = record.workflow_signal_status
        export_request.workflow_signal = record.workflow_signal
        if record.audit_event_id is not None:
            export_request.audit_event_id = record.audit_event_id
        if record.audit_event_type is not None:
            export_request.audit_event_type = record.audit_event_type
        export_request.updated_at = utc_now()
        self.session.flush()
        return export_request

    def record_connector_evidence_snapshot_export_materialization(
        self,
        record: ConnectorEvidenceSnapshotExportMaterializationRecord,
    ) -> ConnectorEvidenceSnapshotExportRequest:
        export_request = self.get_connector_evidence_snapshot_export_request(
            record.tenant_id,
            record.export_request_id,
        )
        if export_request is None:
            raise PersistenceRecordNotFound("Connector evidence snapshot export request not found")

        export_request.status = record.status
        export_request.export_status = record.export_status
        export_request.storage_status = record.storage_status
        export_request.materialization_id = record.materialization_id
        export_request.materialization_idempotency_key = record.materialization_idempotency_key
        export_request.materialized_by = record.materialized_by
        export_request.materialized_at = utc_now()
        export_request.materialization_reason = record.materialization_reason
        export_request.storage_adapter = record.storage_adapter
        export_request.storage_key = record.storage_key
        export_request.storage_uri = record.storage_uri
        export_request.artifact_checksum_sha256 = record.artifact_checksum_sha256
        export_request.artifact_size_bytes = record.artifact_size_bytes
        export_request.artifact_content_type = record.artifact_content_type
        if record.audit_event_id is not None:
            export_request.audit_event_id = record.audit_event_id
        if record.audit_event_type is not None:
            export_request.audit_event_type = record.audit_event_type
        export_request.updated_at = utc_now()
        self.session.flush()
        return export_request

    def create_manufacturing_operation_record(
        self,
        record: ManufacturingOperationRecordCreate,
    ) -> ManufacturingOperationRecord:
        operation_record = ManufacturingOperationRecord(
            tenant_id=record.tenant_id,
            record_id=record.record_id,
            domain=record.domain,
            record_type=record.record_type,
            source_system=record.source_system,
            status=record.status,
            owner_role=record.owner_role,
            related_asset=record.related_asset,
            workflow_id=record.workflow_id,
            risk_level=record.risk_level,
            occurred_at=record.occurred_at,
            payload=record.payload,
            evidence_refs=record.evidence_refs,
        )
        self.session.add(operation_record)
        self.session.flush()
        return operation_record

    def list_manufacturing_operation_records(
        self,
        tenant_id: str,
        domain: str | None = None,
        status: str | None = None,
        record_type: str | None = None,
        source_system: str | None = None,
        limit: int = 100,
    ) -> list[ManufacturingOperationRecord]:
        statement: Select[tuple[ManufacturingOperationRecord]] = select(
            ManufacturingOperationRecord
        ).where(ManufacturingOperationRecord.tenant_id == tenant_id)
        if domain is not None:
            statement = statement.where(ManufacturingOperationRecord.domain == domain)
        if status is not None:
            statement = statement.where(ManufacturingOperationRecord.status == status)
        if record_type is not None:
            statement = statement.where(ManufacturingOperationRecord.record_type == record_type)
        if source_system is not None:
            statement = statement.where(ManufacturingOperationRecord.source_system == source_system)

        statement = statement.order_by(
            ManufacturingOperationRecord.occurred_at.desc(),
            ManufacturingOperationRecord.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def create_manufacturing_daily_brief(
        self,
        record: ManufacturingDailyBriefCreate,
    ) -> ManufacturingDailyBrief:
        brief = ManufacturingDailyBrief(
            tenant_id=record.tenant_id,
            brief_id=record.brief_id,
            idempotency_key=record.idempotency_key,
            brief_date=record.brief_date,
            status=record.status,
            requested_by=record.requested_by,
            required_scopes=record.required_scopes,
            source_record_ids=record.source_record_ids,
            summary_payload=record.summary_payload,
            permission_decision=record.permission_decision,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
        )
        self.session.add(brief)
        self.session.flush()
        return brief

    def get_manufacturing_daily_brief(
        self,
        tenant_id: str,
        brief_id: str,
    ) -> ManufacturingDailyBrief | None:
        statement = select(ManufacturingDailyBrief).where(
            ManufacturingDailyBrief.tenant_id == tenant_id,
            ManufacturingDailyBrief.brief_id == brief_id,
        )
        return self.session.scalars(statement).first()

    def get_manufacturing_daily_brief_by_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> ManufacturingDailyBrief | None:
        statement = select(ManufacturingDailyBrief).where(
            ManufacturingDailyBrief.tenant_id == tenant_id,
            ManufacturingDailyBrief.idempotency_key == idempotency_key,
        )
        return self.session.scalars(statement).first()

    def list_manufacturing_daily_briefs(
        self,
        tenant_id: str,
        brief_date: str | None = None,
        limit: int = 100,
    ) -> list[ManufacturingDailyBrief]:
        statement: Select[tuple[ManufacturingDailyBrief]] = select(ManufacturingDailyBrief).where(
            ManufacturingDailyBrief.tenant_id == tenant_id
        )
        if brief_date is not None:
            statement = statement.where(ManufacturingDailyBrief.brief_date == brief_date)

        statement = statement.order_by(
            ManufacturingDailyBrief.created_at.desc(),
            ManufacturingDailyBrief.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))

    def create_manufacturing_risk_scenario(
        self,
        record: ManufacturingRiskScenarioCreate,
    ) -> ManufacturingRiskScenario:
        scenario = ManufacturingRiskScenario(
            tenant_id=record.tenant_id,
            scenario_id=record.scenario_id,
            idempotency_key=record.idempotency_key,
            domain=record.domain,
            status=record.status,
            risk_level=record.risk_level,
            requested_by=record.requested_by,
            owner_role=record.owner_role,
            workflow_ids=record.workflow_ids,
            source_record_ids=record.source_record_ids,
            scenario_payload=record.scenario_payload,
            permission_decision=record.permission_decision,
            audit_event_id=record.audit_event_id,
            audit_event_type=record.audit_event_type,
        )
        self.session.add(scenario)
        self.session.flush()
        return scenario

    def get_manufacturing_risk_scenario_by_idempotency_key(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> ManufacturingRiskScenario | None:
        statement = select(ManufacturingRiskScenario).where(
            ManufacturingRiskScenario.tenant_id == tenant_id,
            ManufacturingRiskScenario.idempotency_key == idempotency_key,
        )
        return self.session.scalars(statement).first()

    def list_manufacturing_risk_scenarios(
        self,
        tenant_id: str,
        domain: str | None = None,
        risk_level: str | None = None,
        limit: int = 100,
    ) -> list[ManufacturingRiskScenario]:
        statement: Select[tuple[ManufacturingRiskScenario]] = select(
            ManufacturingRiskScenario
        ).where(ManufacturingRiskScenario.tenant_id == tenant_id)
        if domain is not None:
            statement = statement.where(ManufacturingRiskScenario.domain == domain)
        if risk_level is not None:
            statement = statement.where(ManufacturingRiskScenario.risk_level == risk_level)

        statement = statement.order_by(
            ManufacturingRiskScenario.created_at.desc(),
            ManufacturingRiskScenario.id.desc(),
        ).limit(limit)
        return list(self.session.scalars(statement))
