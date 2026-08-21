import base64
import binascii
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from axis_api.audit import AuditEventCreate
from axis_api.connector_execution import (
    LIVE_SYNC_BATCH_READ_STATUS,
    LIVE_SYNC_PLAN_BLOCKED_STATUS,
    LIVE_SYNC_PLAN_DEFERRED_STATUS,
    LIVE_SYNC_PLAN_READY_STATUS,
    ConnectorExecutionRequest,
    ConnectorExecutionResult,
    ConnectorExecutionRuntime,
    ConnectorLiveSyncBatchRequest,
    ConnectorLiveSyncFieldMapping,
    ConnectorLiveSyncPlan,
    ConnectorLiveSyncPlanRequest,
    ConnectorLiveSyncRuntime,
    ConnectorSyncDispatchRequest,
    ConnectorSyncDispatchResult,
    ConnectorSyncDispatchRuntime,
    ConnectorSyncExecutionRequest,
    ConnectorSyncExecutionResult,
    ConnectorSyncExecutionRuntime,
    ConnectorSyncScheduleRequest,
    ConnectorSyncScheduleResult,
    ConnectorSyncSchedulerRuntime,
    DeferredConnectorExecutionRuntime,
    DeferredConnectorSyncDispatchRuntime,
    DeferredConnectorSyncExecutionRuntime,
    DeferredConnectorSyncSchedulerRuntime,
)
from axis_api.connector_reference import require_persisted_manufacturing_connector_registry
from axis_api.demo import OverviewMetric, OverviewStatus
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    find_manufacturing_tenant_metadata,
    operational_provenance,
)
from axis_api.models import ConnectorSyncCheckpointClaim, utc_now
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorOntologyProposalCreate,
    ConnectorRunCreate,
    ConnectorRunUpdateRecord,
    ConnectorSyncCheckpointClaimCreate,
    ConnectorSyncCheckpointClaimExpirationRecord,
    ConnectorSyncCheckpointClaimReleaseRecord,
    ConnectorSyncCheckpointClaimRenewalRecord,
    ConnectorSyncCheckpointCreate,
)
from axis_api.platform_tenants import TenantQuotaKey
from axis_api.usage_metering import (
    DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
    TenantUsageMetric,
    record_tenant_usage_event,
)


class ConnectorRunValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ConnectorRunNotFound(LookupError):
    pass


class ConnectorRunPermissionDenied(PermissionError):
    def __init__(self, required_permission: str) -> None:
        super().__init__("Connector run permission denied")
        self.required_permission = required_permission


class ConnectorRunDispatchConflict(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__("Connector run dispatch conflict")
        self.reason = reason


class ConnectorRunSyncExecutionConflict(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__("Connector run sync execution conflict")
        self.reason = reason


class ConnectorSyncCheckpointClaimConflict(ValueError):
    def __init__(self, reason: str, active_claim_id: str) -> None:
        super().__init__("Connector sync checkpoint claim conflict")
        self.reason = reason
        self.active_claim_id = active_claim_id


class ConnectorRunQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class ConnectorSyncCheckpointQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    run_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: int = Field(default=100, ge=1, le=200)


class ConnectorSyncCheckpointClaimQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    checkpoint_id: str | None = Field(default=None, min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    run_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    claimed_by: str | None = Field(default=None, min_length=1)
    created_after: datetime | None = None
    created_before: datetime | None = None
    cursor: str | None = Field(default=None, min_length=1, max_length=600)
    limit: int = Field(default=100, ge=1, le=200)


class ConnectorSyncCheckpointClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    claim_id: str = Field(min_length=1, max_length=220, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    claimed_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=220)
    lease_duration_seconds: int = Field(default=900, ge=60, le=86_400)
    notes: list[str] = Field(default_factory=list)


class ConnectorSyncCheckpointClaimRenewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    renewed_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    renewed_at: datetime | None = None
    lease_duration_seconds: int = Field(default=900, ge=60, le=86_400)
    renewal_reason: str = Field(min_length=1, max_length=600)
    notes: list[str] = Field(default_factory=list)


class ConnectorSyncCheckpointClaimReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    released_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    released_at: datetime | None = None
    release_reason: str = Field(min_length=1, max_length=600)
    notes: list[str] = Field(default_factory=list)


class ConnectorRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str = Field(default="file_csv_manufacturing_assets", min_length=1)
    run_id: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    execution_mode: str = Field(default="preview", min_length=1, max_length=80)
    requested_by: str = Field(min_length=1, max_length=160)
    credential_handle_ids: list[str] = Field(default_factory=list)
    credential_lease_id: str | None = Field(default=None, min_length=1, max_length=180)
    schedule_id: str | None = Field(default=None, min_length=1, max_length=180)
    schedule_cadence: str | None = Field(default=None, min_length=1, max_length=80)
    schedule_timezone: str | None = Field(default=None, min_length=1, max_length=80)
    next_run_at: datetime | None = None
    input_summary: dict[str, str] = Field(default_factory=dict)
    result_summary: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ConnectorRunDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    dispatch_id: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    dispatched_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    credential_lease_id: str = Field(min_length=1, max_length=180)
    idempotency_key: str = Field(min_length=1, max_length=220)
    notes: list[str] = Field(default_factory=list)


class ConnectorRunSyncExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    execution_id: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    executed_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    credential_lease_id: str = Field(min_length=1, max_length=180)
    checkpoint_claim_id: str | None = Field(default=None, min_length=1, max_length=220)
    idempotency_key: str = Field(min_length=1, max_length=220)
    notes: list[str] = Field(default_factory=list)


class ConnectorRunRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    execution_mode: str = Field(min_length=1)
    runtime_boundary: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    credential_handle_ids: list[str] = Field(default_factory=list)
    input_summary: dict[str, str] = Field(default_factory=dict)
    result_summary: dict = Field(default_factory=dict)
    execution_result: ConnectorExecutionResult | None = None
    schedule_result: ConnectorSyncScheduleResult | None = None
    dispatch_result: ConnectorSyncDispatchResult | None = None
    sync_execution_result: ConnectorSyncExecutionResult | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime


class ConnectorSyncCheckpointRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    checkpoint_type: str = Field(min_length=1)
    status: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    runtime_boundary: str = Field(min_length=1)
    adapter: str = Field(min_length=1)
    cursor: dict = Field(default_factory=dict)
    result_summary: dict = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime


class ConnectorSyncCheckpointEvidenceInvariant(BaseModel):
    checkpoint_id: str = Field(min_length=1)
    audit_event_id: str | None = None
    reason: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class ConnectorSyncCheckpointClaimRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    claimed_by: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    lease_duration_seconds: int = Field(ge=1)
    lease_expires_at: datetime
    renewed_at: datetime | None = None
    renewed_by: str | None = None
    renewal_count: int = Field(ge=0)
    released_at: datetime | None = None
    released_by: str | None = None
    release_reason: str | None = None
    claim_result: dict = Field(default_factory=dict)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime


class ConnectorSyncCheckpointClaimEvidenceInvariant(BaseModel):
    claim_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    audit_event_id: str | None = None
    reason: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class ManufacturingConnectorRunRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    runs: list[ConnectorRunRecord] = Field(default_factory=list)
    run_notes: list[str] = Field(default_factory=list)


class ManufacturingConnectorSyncCheckpointRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    checkpoints: list[ConnectorSyncCheckpointRecord] = Field(default_factory=list)
    evidence_invariants: list[ConnectorSyncCheckpointEvidenceInvariant] = Field(
        default_factory=list
    )
    checkpoint_notes: list[str] = Field(default_factory=list)


class ManufacturingConnectorSyncCheckpointClaimRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    claims: list[ConnectorSyncCheckpointClaimRecord] = Field(default_factory=list)
    claim_evidence_invariants: list[
        ConnectorSyncCheckpointClaimEvidenceInvariant
    ] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False
    claim_notes: list[str] = Field(default_factory=list)


AUDIT_EVENT_TYPE = "connector.run.recorded"
EXECUTION_AUDIT_EVENT_TYPE = "connector.run.execution_deferred"
SYNC_SCHEDULE_AUDIT_EVENT_TYPE = "connector.run.sync_scheduled"
SYNC_DISPATCH_AUDIT_EVENT_TYPE = "connector.run.sync_dispatch_deferred"
SYNC_EXECUTION_DEFERRED_AUDIT_EVENT_TYPE = "connector.run.sync_execution_deferred"
SYNC_EXECUTION_COMPLETED_AUDIT_EVENT_TYPE = "connector.run.sync_execution_completed"
SYNC_EXECUTION_PREFLIGHT_BLOCKED_AUDIT_EVENT_TYPE = (
    "connector.run.sync_execution_preflight_blocked"
)
SYNC_EXECUTION_PREFLIGHT_PASSED_AUDIT_EVENT_TYPE = (
    "connector.run.sync_execution_preflight_passed"
)
SYNC_EXECUTION_LIVE_QUERY_BLOCKED_AUDIT_EVENT_TYPE = (
    "connector.run.sync_execution_live_query_blocked"
)
SYNC_EXECUTION_STARTED_AUDIT_EVENT_TYPE = "connector.run.sync_execution_started"
SYNC_EXECUTION_FAILED_AUDIT_EVENT_TYPE = "connector.run.sync_execution_failed"
SYNC_EXECUTION_LIVE_SYNC_BLOCKED_AUDIT_EVENT_TYPE = (
    "connector.run.sync_execution_live_sync_blocked"
)
SYNC_BATCH_COMMITTED_AUDIT_EVENT_TYPE = "connector.run.sync_batch_committed"
LIVE_SYNC_PROPOSALS_AUDIT_EVENT_TYPE = "connector.ontology_proposals.recorded"
SYNC_CHECKPOINT_READ_AUDIT_EVENT_TYPE = "connector.run.sync_checkpoints_read"
SYNC_CHECKPOINT_CLAIM_READ_AUDIT_EVENT_TYPE = (
    "connector.run.sync_checkpoint_claims_read"
)
SYNC_CHECKPOINT_CLAIMED_AUDIT_EVENT_TYPE = "connector.run.sync_checkpoint_claimed"
SYNC_CHECKPOINT_CLAIM_EXPIRED_AUDIT_EVENT_TYPE = (
    "connector.run.sync_checkpoint_claim_expired"
)
SYNC_CHECKPOINT_CLAIM_RENEWED_AUDIT_EVENT_TYPE = (
    "connector.run.sync_checkpoint_claim_renewed"
)
SYNC_CHECKPOINT_CLAIM_RELEASED_AUDIT_EVENT_TYPE = (
    "connector.run.sync_checkpoint_claim_released"
)
SYNC_DISPATCH_SCOPE = "connectors:sync:dispatch"
SYNC_EXECUTION_SCOPE = "connectors:sync:execute"
SYNC_CHECKPOINT_READ_SCOPE = "connectors:sync:checkpoint:read"
SYNC_CHECKPOINT_CLAIM_READ_SCOPE = "connectors:sync:checkpoint:claim:read"
SYNC_CHECKPOINT_CLAIM_SCOPE = "connectors:sync:checkpoint:claim"
SYNC_CHECKPOINT_CLAIM_RENEW_SCOPE = "connectors:sync:checkpoint:claim:renew"
SYNC_CHECKPOINT_CLAIM_RELEASE_SCOPE = "connectors:sync:checkpoint:claim:release"
SYNC_CHECKPOINT_FORBIDDEN_PUBLIC_MARKERS = (
    "credential_value",
    "dsn",
    "password",
    "postgresql://",
    "secret_value",
)
LIVE_READ_PUBLIC_SAFE_RESULT_SUMMARY_KEYS = {
    "checkpoint_claim_checkpoint_id",
    "checkpoint_claim_evidence_status",
    "checkpoint_claim_id",
    "checkpoint_claim_lease_expires_at",
    "checkpoint_claim_worker",
    "connection_profile_id",
    "connector_id",
    "credential_access_mode",
    "credential_lease_evidence_status",
    "credential_lease_id",
    "credential_lease_mode",
    "credential_lease_ref",
    "credential_lease_result_status",
    "credential_lease_runtime_boundary",
    "credential_lease_secret_material_returned",
    "credential_material_returned",
    "dispatch_id",
    "egress_boundary",
    "egress_policy_decision",
    "egress_policy_endpoint_target_sha256",
    "egress_policy_evidence_status",
    "egress_policy_id",
    "egress_policy_mode",
    "egress_policy_private_endpoint_ref",
    "egress_policy_ref",
    "egress_policy_result_status",
    "egress_policy_runtime_boundary",
    "egress_policy_scope",
    "execution_id",
    "external_query_started",
    "external_sync_started",
    "graph_mutation_started",
    "live_query_execute_requested",
    "live_query_execution_status",
    "live_query_preflight_status",
    "live_query_profile_id",
    "live_query_requested",
    "live_query_row_limit",
    "provider",
    "query_mode",
    "records_accepted",
    "records_read",
    "records_rejected",
    "runtime_status",
    "schedule_id",
    "schema_name",
    "secret_reference_access_mode",
    "secret_reference_evidence_status",
    "secret_reference_lease_ref",
    "secret_reference_material_returned",
    "secret_reference_result_status",
    "secret_reference_runtime_boundary",
    "secret_reference_scope",
    "secret_resolution_provider_profile",
    "secret_resolution_runtime_boundary",
    "runtime_egress_enforcement",
    "secret_retrieval_decision",
    "selected_column_count",
    "source_mode",
    "table_name",
}
LIVE_SYNC_PUBLIC_SAFE_RESULT_SUMMARY_KEYS = (
    LIVE_READ_PUBLIC_SAFE_RESULT_SUMMARY_KEYS
    | {
        "batch_index",
        "batch_offset",
        "batch_records_read",
        "batch_records_rejected",
        "batch_proposals_recorded",
        "live_sync_requested",
        "live_sync_execution_status",
        "next_offset",
        "proposal_write_mode",
        "proposals_recorded",
        "resume_offset",
        "source_exhausted",
        "source_ref",
        "sync_batches_committed",
        "sync_error_code",
    }
)
LIVE_SYNC_EXECUTION_STATUSES = {"in_progress", "completed", "failed"}
SYNC_EXECUTION_FAILED_STATUS = "sync_execution_failed"
SYNC_EXECUTION_LIVE_SYNC_BLOCKED_STATUS = "sync_execution_live_sync_blocked"
SYNC_BATCH_COMMITTED_STATUS = "sync_batch_committed"
SYNC_BATCH_CHECKPOINT_TYPE = "sync_batch"
LIVE_SYNC_MAPPING_PROFILE = "connector_live_sync_v1"
LIVE_SYNC_MAX_BATCHES_PER_EXECUTION = 100
LIVE_SYNC_CHECKPOINT_LIST_LIMIT = 200
GOVERNED_EXECUTION_MODE = "governed_dry_run"
SCHEDULED_SYNC_PLAN_MODE = "scheduled_sync_plan"
ALLOWED_EXECUTION_MODES = {
    "preview",
    "manual_import_record",
    GOVERNED_EXECUTION_MODE,
    SCHEDULED_SYNC_PLAN_MODE,
}
RAW_PAYLOAD_FIELD_NAMES = {
    "api_key",
    "client_secret",
    "credential_value",
    "csv_content",
    "password",
    "raw_file_content",
    "raw_payload",
    "secret",
    "secret_ref",
    "token",
}


def build_connector_run_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorRunQuery,
) -> ManufacturingConnectorRunRegistry:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, query.tenant_id)
    records = repository.list_connector_runs(
        tenant_id=query.tenant_id,
        connector_id=query.connector_id,
        status=query.status,
        limit=query.limit,
    )
    runs = [_run_from_record(record) for record in records]
    audit_writes = sum(1 for run in runs if run.audit_event_id is not None)
    return ManufacturingConnectorRunRegistry(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(bool(records)),
        registry_status=OverviewStatus.READY if runs else OverviewStatus.WATCH,
        metrics=[
            OverviewMetric(
                label="Connector Runs",
                value=str(len(runs)),
                detail="Metadata-only connector run records",
                status=OverviewStatus.READY if runs else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Audit Writes",
                value=str(audit_writes),
                detail="Append-only audit events linked to run records",
                status=OverviewStatus.READY if audit_writes == len(runs) else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Live Sync",
                value="Disabled",
                detail="Run records do not execute connector sync",
                status=OverviewStatus.WATCH,
            ),
        ],
        runs=runs,
        run_notes=[
            "Connector run records are metadata-only evidence.",
            "Creating a run record writes an append-only audit event.",
            "Raw payloads, file content and credential material are never stored.",
            "Live sync and connector-backed production actions remain future work.",
        ],
    )


def build_connector_sync_checkpoint_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorSyncCheckpointQuery,
) -> ManufacturingConnectorSyncCheckpointRegistry:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, query.tenant_id)
    _validate_checkpoint_time_window(query)
    records = repository.list_connector_sync_checkpoints(
        tenant_id=query.tenant_id,
        connector_id=query.connector_id,
        run_id=query.run_id,
        status=query.status,
        created_after=query.created_after,
        created_before=query.created_before,
        limit=query.limit,
    )
    checkpoints = [_checkpoint_from_record(record) for record in records]
    evidence_invariants = [
        invariant
        for record in records
        if (invariant := _checkpoint_evidence_invariant(repository, record)) is not None
    ]
    audit_refs = sum(1 for checkpoint in checkpoints if checkpoint.audit_event_id is not None)
    return ManufacturingConnectorSyncCheckpointRegistry(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(bool(records)),
        registry_status=OverviewStatus.READY if checkpoints else OverviewStatus.WATCH,
        metrics=[
            OverviewMetric(
                label="Sync Checkpoints",
                value=str(len(checkpoints)),
                detail="Tenant-scoped connector sync checkpoint records",
                status=OverviewStatus.READY if checkpoints else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Audit Evidence",
                value=str(audit_refs),
                detail="Checkpoints linked to append-only audit events",
                status=(
                    OverviewStatus.READY
                    if audit_refs == len(checkpoints)
                    else OverviewStatus.WATCH
                ),
            ),
            OverviewMetric(
                label="Evidence Invariants",
                value=str(len(evidence_invariants)),
                detail="Checkpoint audit ledger binding issues in this result set",
                status=(
                    OverviewStatus.WATCH
                    if evidence_invariants
                    else OverviewStatus.READY
                ),
            ),
            OverviewMetric(
                label="Secret Material",
                value="Excluded",
                detail="Checkpoint cursors carry public-safe retry metadata only",
                status=OverviewStatus.READY,
            ),
        ],
        checkpoints=checkpoints,
        evidence_invariants=evidence_invariants,
        checkpoint_notes=[
            "Sync checkpoints are tenant-scoped runtime evidence for retry/resume.",
            "Checkpoint cursors are public-safe and exclude raw credentials.",
        ],
    )


def read_connector_sync_checkpoint_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorSyncCheckpointQuery,
    *,
    actor_id: str,
    read_scope_source: str,
) -> ManufacturingConnectorSyncCheckpointRegistry:
    registry = build_connector_sync_checkpoint_registry(repository, query)
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=query.tenant_id,
            actor_id=actor_id,
            event_type=SYNC_CHECKPOINT_READ_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": query.connector_id,
                "run_id": query.run_id,
                "status": query.status,
                "created_after": _datetime_as_utc_string(query.created_after),
                "created_before": _datetime_as_utc_string(query.created_before),
                "limit": query.limit,
                "returned_checkpoint_count": len(registry.checkpoints),
                "evidence_invariant_count": len(registry.evidence_invariants),
                "checkpoint_ids": [
                    checkpoint.checkpoint_id for checkpoint in registry.checkpoints
                ],
                "required_permission": SYNC_CHECKPOINT_READ_SCOPE,
                "read_scope_source": read_scope_source,
            },
        )
    )
    return registry


def build_connector_sync_checkpoint_claim_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorSyncCheckpointClaimQuery,
) -> ManufacturingConnectorSyncCheckpointClaimRegistry:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, query.tenant_id)
    _validate_checkpoint_claim_time_window(query)
    cursor_created_at, cursor_row_id = _decode_checkpoint_claim_cursor(query.cursor)
    records = repository.list_connector_sync_checkpoint_claims(
        tenant_id=query.tenant_id,
        checkpoint_id=query.checkpoint_id,
        connector_id=query.connector_id,
        run_id=query.run_id,
        status=query.status,
        claimed_by=query.claimed_by,
        created_after=query.created_after,
        created_before=query.created_before,
        cursor_created_at=cursor_created_at,
        cursor_row_id=cursor_row_id,
        limit=query.limit + 1,
    )
    has_more = len(records) > query.limit
    page_records = records[: query.limit]
    claims = [_checkpoint_claim_from_record(record) for record in page_records]
    next_cursor = (
        _encode_checkpoint_claim_cursor(page_records[-1])
        if has_more and page_records
        else None
    )
    active_claims = sum(1 for claim in claims if claim.status == "claimed")
    closed_claims = sum(1 for claim in claims if claim.status in {"expired", "released"})
    claim_evidence_invariants = [
        invariant
        for record in page_records
        if (invariant := _claim_evidence_invariant(repository, record)) is not None
    ]
    return ManufacturingConnectorSyncCheckpointClaimRegistry(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(bool(page_records)),
        registry_status=OverviewStatus.READY if claims else OverviewStatus.WATCH,
        metrics=[
            OverviewMetric(
                label="Checkpoint Claims",
                value=str(len(claims)),
                detail="Tenant-scoped worker leases for sync checkpoints",
                status=OverviewStatus.READY if claims else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Active Claims",
                value=str(active_claims),
                detail="Unclosed worker ownership records returned by the query",
                status=OverviewStatus.READY if active_claims else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Closed Claims",
                value=str(closed_claims),
                detail="Released or expired worker leases returned by the query",
                status=OverviewStatus.READY if closed_claims else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Claim Evidence Invariants",
                value=str(len(claim_evidence_invariants)),
                detail="Claim audit ledger binding issues in this result set",
                status=(
                    OverviewStatus.WATCH
                    if claim_evidence_invariants
                    else OverviewStatus.READY
                ),
            ),
            OverviewMetric(
                label="Secret Material",
                value="Excluded",
                detail="Claim records expose ownership and lease metadata only",
                status=OverviewStatus.READY,
            ),
        ],
        claims=claims,
        claim_evidence_invariants=claim_evidence_invariants,
        next_cursor=next_cursor,
        has_more=has_more,
        claim_notes=[
            "Checkpoint claim records expose worker ownership and lease state.",
            "Claim reads are tenant-scoped and audited without secret material.",
        ],
    )


def read_connector_sync_checkpoint_claim_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorSyncCheckpointClaimQuery,
    *,
    actor_id: str,
    read_scope_source: str,
) -> ManufacturingConnectorSyncCheckpointClaimRegistry:
    registry = build_connector_sync_checkpoint_claim_registry(repository, query)
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=query.tenant_id,
            actor_id=actor_id,
            event_type=SYNC_CHECKPOINT_CLAIM_READ_AUDIT_EVENT_TYPE,
            payload={
                "checkpoint_id": query.checkpoint_id,
                "connector_id": query.connector_id,
                "run_id": query.run_id,
                "status": query.status,
                "claimed_by": query.claimed_by,
                "created_after": _datetime_as_utc_string(query.created_after),
                "created_before": _datetime_as_utc_string(query.created_before),
                "cursor": query.cursor,
                "limit": query.limit,
                "returned_claim_count": len(registry.claims),
                "claim_evidence_invariant_count": len(
                    registry.claim_evidence_invariants
                ),
                "next_cursor": registry.next_cursor,
                "has_more": registry.has_more,
                "claim_ids": [claim.claim_id for claim in registry.claims],
                "required_permission": SYNC_CHECKPOINT_CLAIM_READ_SCOPE,
                "read_scope_source": read_scope_source,
            },
        )
    )
    return registry


def _encode_checkpoint_claim_cursor(record: ConnectorSyncCheckpointClaim) -> str:
    payload = {
        "created_at": _datetime_as_utc_string(record.created_at),
        "row_id": str(record.id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_checkpoint_claim_cursor(
    cursor: str | None,
) -> tuple[datetime | None, UUID | None]:
    if cursor is None:
        return None, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        created_at = datetime.fromisoformat(
            str(payload["created_at"]).replace("Z", "+00:00")
        )
        row_id = UUID(str(payload["row_id"]))
    except (
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
        binascii.Error,
        json.JSONDecodeError,
    ) as exc:
        raise ConnectorRunValidationError(
            "Connector sync checkpoint claim cursor is invalid.",
            "invalid_checkpoint_claim_cursor",
        ) from exc
    return _ensure_timezone(created_at), row_id


def _validate_checkpoint_claim_time_window(
    query: ConnectorSyncCheckpointClaimQuery,
) -> None:
    # Callers may mix offset-aware and naive datetimes in the query string;
    # normalize (naive means UTC) so the comparison cannot raise TypeError.
    if (
        query.created_after is not None
        and query.created_before is not None
        and _ensure_timezone(query.created_after) >= _ensure_timezone(query.created_before)
    ):
        raise ConnectorRunValidationError(
            "Connector checkpoint claim created_after must be earlier than created_before.",
            "invalid_checkpoint_claim_time_window",
        )


def claim_connector_sync_checkpoint(
    repository: AxisPersistenceRepository,
    checkpoint_id: str,
    request: ConnectorSyncCheckpointClaimRequest,
) -> tuple[ConnectorSyncCheckpointClaimRecord, bool]:
    _validate_sync_checkpoint_claim_scope(request)
    checkpoint = repository.get_connector_sync_checkpoint(request.tenant_id, checkpoint_id)
    if checkpoint is None:
        raise ConnectorRunNotFound()

    existing = repository.get_connector_sync_checkpoint_claim_by_idempotency(
        request.tenant_id,
        checkpoint_id,
        request.idempotency_key,
    )
    if existing is not None:
        if existing.claim_id != request.claim_id:
            raise ConnectorRunValidationError(
                "Connector sync checkpoint claim idempotency key has a different claim_id.",
                "idempotency_key_claim_mismatch",
            )
        return _checkpoint_claim_from_record(existing), False

    now = utc_now()
    active_claims = repository.list_connector_sync_checkpoint_claims(
        request.tenant_id,
        checkpoint_id=checkpoint_id,
        status="claimed",
    )
    _expire_stale_checkpoint_claims(
        repository,
        request,
        checkpoint,
        active_claims,
        now,
    )
    active_claim = _active_unexpired_checkpoint_claim(active_claims, now)
    if active_claim is not None:
        raise ConnectorSyncCheckpointClaimConflict(
            "active_checkpoint_claim_exists",
            active_claim.claim_id,
        )

    lease_expires_at = now + timedelta(seconds=request.lease_duration_seconds)
    claim_result = {
        "external_sync_started": False,
        "secret_material_returned": False,
        "worker_claim_only": True,
    }
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.claimed_by,
            event_type=SYNC_CHECKPOINT_CLAIMED_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": checkpoint.connector_id,
                "run_id": checkpoint.run_id,
                "checkpoint_id": checkpoint.checkpoint_id,
                "claim_id": request.claim_id,
                "status": "claimed",
                "claimed_by": request.claimed_by,
                "idempotency_key": request.idempotency_key,
                "lease_duration_seconds": request.lease_duration_seconds,
                "lease_expires_at": _datetime_as_utc_string(lease_expires_at),
                "runtime_boundary": checkpoint.runtime_boundary,
                "adapter": checkpoint.adapter,
                "required_permission": SYNC_CHECKPOINT_CLAIM_SCOPE,
                **claim_result,
            },
        )
    )
    try:
        claim = repository.create_connector_sync_checkpoint_claim(
            ConnectorSyncCheckpointClaimCreate(
                tenant_id=request.tenant_id,
                connector_id=checkpoint.connector_id,
                run_id=checkpoint.run_id,
                checkpoint_id=checkpoint.checkpoint_id,
                claim_id=request.claim_id,
                status="claimed",
                claimed_by=request.claimed_by,
                idempotency_key=request.idempotency_key,
                lease_duration_seconds=request.lease_duration_seconds,
                lease_expires_at=lease_expires_at,
                claim_result=claim_result,
                audit_event_id=audit_event.id,
                audit_event_type=SYNC_CHECKPOINT_CLAIMED_AUDIT_EVENT_TYPE,
                notes=request.notes,
            )
        )
    except IntegrityError as exc:
        # The partial unique index on (tenant_id, checkpoint_id) WHERE
        # status='claimed' is the DB-level backstop for the app-level
        # read-active-then-insert check: a racing worker that also passed the
        # app check loses here and is reported as the same 409 claim conflict.
        raise ConnectorSyncCheckpointClaimConflict(
            "active_checkpoint_claim_exists",
            request.claim_id,
        ) from exc
    return _checkpoint_claim_from_record(claim), True


def renew_connector_sync_checkpoint_claim(
    repository: AxisPersistenceRepository,
    checkpoint_id: str,
    claim_id: str,
    request: ConnectorSyncCheckpointClaimRenewRequest,
) -> ConnectorSyncCheckpointClaimRecord:
    _validate_sync_checkpoint_claim_renew_scope(request)
    claim = _active_checkpoint_claim(repository, request.tenant_id, checkpoint_id, claim_id)
    renewed_at = _ensure_timezone(request.renewed_at or utc_now())
    lease_expires_at = renewed_at + timedelta(seconds=request.lease_duration_seconds)
    claim_result = _worker_claim_result()
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.renewed_by,
            event_type=SYNC_CHECKPOINT_CLAIM_RENEWED_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": claim.connector_id,
                "run_id": claim.run_id,
                "checkpoint_id": claim.checkpoint_id,
                "claim_id": claim.claim_id,
                "status": "claimed",
                "renewed_by": request.renewed_by,
                "renewed_at": _datetime_as_utc_string(renewed_at),
                "renewal_reason": request.renewal_reason,
                "lease_duration_seconds": request.lease_duration_seconds,
                "lease_expires_at": _datetime_as_utc_string(lease_expires_at),
                "required_permission": SYNC_CHECKPOINT_CLAIM_RENEW_SCOPE,
                **claim_result,
            },
        )
    )
    renewed = repository.renew_connector_sync_checkpoint_claim(
        ConnectorSyncCheckpointClaimRenewalRecord(
            tenant_id=request.tenant_id,
            checkpoint_id=checkpoint_id,
            claim_id=claim_id,
            renewed_by=request.renewed_by,
            renewed_at=renewed_at,
            lease_duration_seconds=request.lease_duration_seconds,
            lease_expires_at=lease_expires_at,
            audit_event_id=audit_event.id,
            audit_event_type=SYNC_CHECKPOINT_CLAIM_RENEWED_AUDIT_EVENT_TYPE,
            note=f"Claim renewed: {request.renewal_reason}",
        )
    )
    if request.notes:
        renewed.notes = [*renewed.notes, *request.notes]
    return _checkpoint_claim_from_record(renewed)


def release_connector_sync_checkpoint_claim(
    repository: AxisPersistenceRepository,
    checkpoint_id: str,
    claim_id: str,
    request: ConnectorSyncCheckpointClaimReleaseRequest,
) -> ConnectorSyncCheckpointClaimRecord:
    _validate_sync_checkpoint_claim_release_scope(request)
    claim = _active_checkpoint_claim(repository, request.tenant_id, checkpoint_id, claim_id)
    released_at = _ensure_timezone(request.released_at or utc_now())
    claim_result = _worker_claim_result()
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.released_by,
            event_type=SYNC_CHECKPOINT_CLAIM_RELEASED_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": claim.connector_id,
                "run_id": claim.run_id,
                "checkpoint_id": claim.checkpoint_id,
                "claim_id": claim.claim_id,
                "status": "released",
                "released_by": request.released_by,
                "released_at": _datetime_as_utc_string(released_at),
                "release_reason": request.release_reason,
                "required_permission": SYNC_CHECKPOINT_CLAIM_RELEASE_SCOPE,
                **claim_result,
            },
        )
    )
    released = repository.release_connector_sync_checkpoint_claim(
        ConnectorSyncCheckpointClaimReleaseRecord(
            tenant_id=request.tenant_id,
            checkpoint_id=checkpoint_id,
            claim_id=claim_id,
            released_by=request.released_by,
            released_at=released_at,
            release_reason=request.release_reason,
            audit_event_id=audit_event.id,
            audit_event_type=SYNC_CHECKPOINT_CLAIM_RELEASED_AUDIT_EVENT_TYPE,
            note=f"Claim released: {request.release_reason}",
        )
    )
    if request.notes:
        released.notes = [*released.notes, *request.notes]
    return _checkpoint_claim_from_record(released)


def _validate_checkpoint_time_window(query: ConnectorSyncCheckpointQuery) -> None:
    # Callers may mix offset-aware and naive datetimes in the query string;
    # normalize (naive means UTC) so the comparison cannot raise TypeError.
    if (
        query.created_after is not None
        and query.created_before is not None
        and _ensure_timezone(query.created_after) >= _ensure_timezone(query.created_before)
    ):
        raise ConnectorRunValidationError(
            "Connector checkpoint created_after must be earlier than created_before.",
            "invalid_checkpoint_time_window",
        )


def record_demo_connector_run(
    repository: AxisPersistenceRepository,
    request: ConnectorRunCreateRequest,
    execution_runtime: ConnectorExecutionRuntime | None = None,
    sync_scheduler_runtime: ConnectorSyncSchedulerRuntime | None = None,
) -> ConnectorRunRecord:
    _validate_execution_mode(request.execution_mode)
    _validate_redacted_summary(request.input_summary)
    _validate_redacted_summary(request.result_summary)
    manifest = _active_preview_manifest_for_connector(
        repository,
        request.tenant_id,
        request.connector_id,
    )
    schedule_result = _schedule_connector_sync(
        repository,
        request,
        runtime_boundary=manifest.runtime_boundary,
        sync_scheduler_runtime=sync_scheduler_runtime or DeferredConnectorSyncSchedulerRuntime(),
    )
    execution_result = _execute_connector_run(
        repository,
        request,
        runtime_boundary=manifest.runtime_boundary,
        execution_runtime=execution_runtime or DeferredConnectorExecutionRuntime(),
    )
    if schedule_result is not None:
        status = schedule_result.status
        audit_event_type = SYNC_SCHEDULE_AUDIT_EVENT_TYPE
    elif execution_result is not None:
        status = execution_result.status
        audit_event_type = EXECUTION_AUDIT_EVENT_TYPE
    else:
        status = _status_for_execution_mode(request.execution_mode)
        audit_event_type = AUDIT_EVENT_TYPE
    result_summary = dict(request.result_summary)
    if schedule_result is not None:
        result_summary.update(schedule_result.result_summary)
        result_summary["sync_schedule_result"] = schedule_result.model_dump(mode="json")
    if execution_result is not None:
        result_summary.update(execution_result.result_summary)
        result_summary["execution_result"] = execution_result.model_dump(mode="json")

    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type=audit_event_type,
            payload={
                "connector_id": request.connector_id,
                "run_id": request.run_id,
                "status": status,
                "execution_mode": request.execution_mode,
                "credential_handle_ids": request.credential_handle_ids,
                "credential_lease_id": request.credential_lease_id,
                "schedule_id": request.schedule_id,
                "schedule_cadence": request.schedule_cadence,
                "schedule_timezone": request.schedule_timezone,
                "next_run_at": _datetime_as_utc_string(request.next_run_at),
                "input_summary": request.input_summary,
                "result_summary": result_summary,
                "execution_result": (
                    execution_result.model_dump(mode="json")
                    if execution_result is not None
                    else None
                ),
                "schedule_result": (
                    schedule_result.model_dump(mode="json")
                    if schedule_result is not None
                    else None
                ),
                "runtime_boundary": manifest.runtime_boundary,
            },
        )
    )
    record = repository.create_connector_run(
        ConnectorRunCreate(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
            run_id=request.run_id,
            status=status,
            execution_mode=request.execution_mode,
            runtime_boundary=manifest.runtime_boundary,
            requested_by=request.requested_by,
            credential_handle_ids=request.credential_handle_ids,
            input_summary=request.input_summary,
            result_summary=result_summary,
            audit_event_id=audit_event.id,
            audit_event_type=audit_event_type,
            notes=request.notes,
        )
    )
    return _run_from_record(record)


def dispatch_demo_connector_sync(
    repository: AxisPersistenceRepository,
    run_id: str,
    request: ConnectorRunDispatchRequest,
    sync_dispatch_runtime: ConnectorSyncDispatchRuntime | None = None,
) -> ConnectorRunRecord:
    _validate_dispatch_scope(request)
    run = repository.get_connector_run(request.tenant_id, run_id)
    if run is None:
        raise ConnectorRunNotFound()

    existing_dispatch = _dispatch_result_from_summary(run.result_summary)
    if existing_dispatch is not None:
        if (
            existing_dispatch.idempotency_key == request.idempotency_key
            and run.result_summary.get("dispatch_id") == request.dispatch_id
        ):
            return _run_from_record(run)
        raise ConnectorRunDispatchConflict("sync_dispatch_idempotency_conflict")

    _validate_dispatchable_scheduled_run(run)
    schedule_result = _schedule_result_from_summary(run.result_summary)
    if schedule_result is None:
        raise ConnectorRunValidationError(
            "Scheduled connector sync dispatch requires schedule result evidence.",
            "schedule_result_required",
        )
    _validate_active_credential_lease_for_run(
        repository,
        run,
        request.credential_lease_id,
    )
    _active_preview_manifest_for_connector(
        repository,
        run.tenant_id,
        run.connector_id,
    )

    dispatch_runtime = sync_dispatch_runtime or DeferredConnectorSyncDispatchRuntime()
    dispatch_result = dispatch_runtime.dispatch(
        ConnectorSyncDispatchRequest(
            tenant_id=run.tenant_id,
            connector_id=run.connector_id,
            run_id=run.run_id,
            dispatch_id=request.dispatch_id,
            runtime_boundary=run.runtime_boundary,
            dispatched_by=request.dispatched_by,
            credential_handle_ids=run.credential_handle_ids,
            credential_lease_id=request.credential_lease_id,
            schedule_id=schedule_result.result_summary.get("schedule_id", "unknown_schedule"),
            schedule_ref=schedule_result.schedule_ref,
            idempotency_key=request.idempotency_key,
        )
    )

    result_summary = dict(run.result_summary)
    result_summary.update(dispatch_result.result_summary)
    result_summary["dispatch_id"] = request.dispatch_id
    result_summary["sync_dispatch_result"] = dispatch_result.model_dump(mode="json")

    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=run.tenant_id,
            actor_id=request.dispatched_by,
            event_type=SYNC_DISPATCH_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": run.connector_id,
                "run_id": run.run_id,
                "dispatch_id": request.dispatch_id,
                "status": dispatch_result.status,
                "execution_mode": run.execution_mode,
                "credential_handle_ids": run.credential_handle_ids,
                "credential_lease_id": request.credential_lease_id,
                "schedule_result": schedule_result.model_dump(mode="json"),
                "dispatch_result": dispatch_result.model_dump(mode="json"),
                "idempotency_key": request.idempotency_key,
                "runtime_boundary": run.runtime_boundary,
                "external_sync_started": False,
            },
        )
    )
    updated = repository.update_connector_run(
        ConnectorRunUpdateRecord(
            tenant_id=run.tenant_id,
            run_id=run.run_id,
            status=dispatch_result.status,
            result_summary=result_summary,
            audit_event_id=audit_event.id,
            audit_event_type=SYNC_DISPATCH_AUDIT_EVENT_TYPE,
            notes=[*run.notes, *request.notes],
        )
    )
    return _run_from_record(updated)


def execute_demo_connector_sync(
    repository: AxisPersistenceRepository,
    run_id: str,
    request: ConnectorRunSyncExecutionRequest,
    sync_execution_runtime: ConnectorSyncExecutionRuntime | None = None,
    live_sync_runtime: ConnectorLiveSyncRuntime | None = None,
    *,
    usage_metering_enabled: bool = False,
    usage_window_seconds: int = DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
) -> ConnectorRunRecord:
    _validate_sync_execution_scope(request)
    run = repository.get_connector_run(request.tenant_id, run_id)
    if run is None:
        raise ConnectorRunNotFound()

    existing_execution = _sync_execution_result_from_summary(run.result_summary)
    if existing_execution is not None:
        if (
            existing_execution.idempotency_key == request.idempotency_key
            and run.result_summary.get("sync_execution_id") == request.execution_id
        ):
            return _run_from_record(run)
        if not _live_sync_retry_allowed(run, existing_execution, request):
            raise ConnectorRunSyncExecutionConflict("sync_execution_idempotency_conflict")

    _validate_executable_scheduled_run(run)
    schedule_result = _schedule_result_from_summary(run.result_summary)
    dispatch_result = _dispatch_result_from_summary(run.result_summary)
    if schedule_result is None:
        raise ConnectorRunValidationError(
            "Scheduled connector sync execution requires schedule result evidence.",
            "schedule_result_required",
        )
    if dispatch_result is None:
        raise ConnectorRunValidationError(
            "Scheduled connector sync execution requires dispatch result evidence.",
            "dispatch_result_required",
        )
    credential_lease = _validate_active_credential_lease_for_run(
        repository,
        run,
        request.credential_lease_id,
    )
    manifest = _active_preview_manifest_for_connector(
        repository,
        run.tenant_id,
        run.connector_id,
    )
    _validate_active_live_manifest_for_live_query_execution(manifest, run)
    egress_policy_evidence = _egress_policy_evidence_for_run(repository, run)
    checkpoint_claim = _validate_active_worker_checkpoint_claim_for_live_query(
        repository,
        run,
        request,
    )

    live_sync_plan = None
    if _live_sync_requested(run) and live_sync_runtime is not None:
        live_sync_plan = live_sync_runtime.plan(
            ConnectorLiveSyncPlanRequest(
                tenant_id=run.tenant_id,
                connector_id=run.connector_id,
                run_id=run.run_id,
                execution_id=request.execution_id,
                executed_by=request.executed_by,
                credential_lease_id=request.credential_lease_id,
                credential_lease_result=credential_lease.lease_result,
                egress_policy_evidence=egress_policy_evidence,
                field_mappings=_live_sync_field_mappings(manifest),
                input_summary=run.input_summary,
            )
        )
    if live_sync_plan is not None and live_sync_plan.status == LIVE_SYNC_PLAN_READY_STATUS:
        live_sync_plan = _apply_tenant_live_sync_row_cap(
            repository,
            run.tenant_id,
            live_sync_plan,
        )
    if live_sync_plan is not None and live_sync_plan.status != LIVE_SYNC_PLAN_DEFERRED_STATUS:
        _validate_active_live_manifest_for_live_sync(manifest)
        # Capture the resume seed BEFORE the attempt runs so usage meters only the
        # rows this attempt reads, not the run-cumulative total on a resume.
        resume_records_seed = _live_sync_resume_records_seed(repository, run)
        sync_execution_result = _execute_live_connector_sync(
            repository,
            run,
            request,
            live_sync_runtime=live_sync_runtime,
            plan=live_sync_plan,
            manifest=manifest,
            schedule_result=schedule_result,
            credential_lease=credential_lease,
            egress_policy_evidence=egress_policy_evidence,
        )
        return _persist_sync_execution_outcome(
            repository,
            run,
            request,
            sync_execution_result,
            schedule_result=schedule_result,
            dispatch_result=dispatch_result,
            usage_metering_enabled=usage_metering_enabled,
            usage_window_seconds=usage_window_seconds,
            resume_records_seed=resume_records_seed,
        )

    execution_runtime = sync_execution_runtime or DeferredConnectorSyncExecutionRuntime()
    sync_execution_result = execution_runtime.execute(
        ConnectorSyncExecutionRequest(
            tenant_id=run.tenant_id,
            connector_id=run.connector_id,
            run_id=run.run_id,
            execution_id=request.execution_id,
            runtime_boundary=run.runtime_boundary,
            executed_by=request.executed_by,
            credential_handle_ids=run.credential_handle_ids,
            credential_lease_id=request.credential_lease_id,
            credential_lease_mode=credential_lease.lease_mode,
            credential_lease_runtime_boundary=credential_lease.runtime_boundary,
            credential_lease_result=credential_lease.lease_result,
            credential_secret_provider=credential_lease.secret_provider,
            credential_secret_ref=credential_lease.secret_ref,
            egress_policy_evidence=egress_policy_evidence,
            schedule_id=schedule_result.result_summary.get("schedule_id", "unknown_schedule"),
            schedule_ref=schedule_result.schedule_ref,
            dispatch_id=run.result_summary.get("dispatch_id", "unknown_dispatch"),
            dispatch_ref=dispatch_result.dispatch_ref,
            idempotency_key=request.idempotency_key,
            input_summary=run.input_summary,
        )
    )
    if checkpoint_claim is not None:
        sync_execution_result = sync_execution_result.model_copy(
            update={
                "result_summary": {
                    **sync_execution_result.result_summary,
                    "checkpoint_claim_evidence_status": "validated",
                    "checkpoint_claim_id": checkpoint_claim.claim_id,
                    "checkpoint_claim_checkpoint_id": checkpoint_claim.checkpoint_id,
                    "checkpoint_claim_worker": checkpoint_claim.claimed_by,
                    "checkpoint_claim_lease_expires_at": _datetime_as_utc_string(
                        checkpoint_claim.lease_expires_at
                    ),
                }
            }
        )

    return _persist_sync_execution_outcome(
        repository,
        run,
        request,
        sync_execution_result,
        schedule_result=schedule_result,
        dispatch_result=dispatch_result,
        usage_metering_enabled=usage_metering_enabled,
        usage_window_seconds=usage_window_seconds,
    )


def _persist_sync_execution_outcome(
    repository: AxisPersistenceRepository,
    run,
    request: ConnectorRunSyncExecutionRequest,
    sync_execution_result: ConnectorSyncExecutionResult,
    *,
    schedule_result: ConnectorSyncScheduleResult,
    dispatch_result: ConnectorSyncDispatchResult,
    usage_metering_enabled: bool = False,
    usage_window_seconds: int = DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
    resume_records_seed: int = 0,
) -> ConnectorRunRecord:
    result_summary = dict(run.result_summary)
    result_summary.update(sync_execution_result.result_summary)
    result_summary["sync_execution_id"] = request.execution_id
    result_summary["sync_execution_result"] = sync_execution_result.model_dump(mode="json")
    audit_event_type = _sync_execution_audit_event_type(sync_execution_result)

    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=run.tenant_id,
            actor_id=request.executed_by,
            event_type=audit_event_type,
            payload={
                "connector_id": run.connector_id,
                "run_id": run.run_id,
                "checkpoint_id": f"chk_{request.execution_id}",
                "execution_id": request.execution_id,
                "status": sync_execution_result.status,
                "execution_mode": run.execution_mode,
                "credential_handle_ids": run.credential_handle_ids,
                "credential_lease_id": request.credential_lease_id,
                "schedule_result": schedule_result.model_dump(mode="json"),
                "dispatch_result": dispatch_result.model_dump(mode="json"),
                "sync_execution_result": sync_execution_result.model_dump(mode="json"),
                "idempotency_key": request.idempotency_key,
                "runtime_boundary": run.runtime_boundary,
                "external_sync_started": sync_execution_result.external_sync_started,
            },
        )
    )
    _record_sync_execution_checkpoint(
        repository,
        run,
        request,
        sync_execution_result,
        audit_event.id,
        audit_event_type,
    )

    updated = repository.update_connector_run(
        ConnectorRunUpdateRecord(
            tenant_id=run.tenant_id,
            run_id=run.run_id,
            status=sync_execution_result.status,
            result_summary=result_summary,
            audit_event_id=audit_event.id,
            audit_event_type=audit_event_type,
            notes=[*run.notes, *request.notes],
        )
    )
    if usage_metering_enabled:
        # Meter the rows read by THIS execution attempt. For a resumed live sync
        # the summary's records_read is the run-cumulative total (it is seeded
        # from the last committed checkpoint), so metering the cumulative value
        # would double-count rows already billed by the earlier attempt. Subtract
        # the resume seed to meter only this attempt's incremental rows.
        _record_connector_sync_rows_usage(
            repository,
            run.tenant_id,
            sync_execution_result,
            usage_window_seconds,
            resume_records_seed=resume_records_seed,
            source_id=f"{run.run_id}:{request.execution_id}",
            occurred_at=audit_event.created_at,
            dimensions={
                "connector_id": run.connector_id,
                "run_id": run.run_id,
                "execution_id": request.execution_id,
            },
        )
    return _run_from_record(updated)


def _record_connector_sync_rows_usage(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    sync_execution_result: ConnectorSyncExecutionResult,
    usage_window_seconds: int,
    *,
    resume_records_seed: int = 0,
    source_id: str,
    occurred_at: datetime,
    dimensions: dict | None = None,
) -> None:
    raw_rows = sync_execution_result.result_summary.get("records_read", "0")
    try:
        cumulative_rows_read = int(raw_rows)
    except (TypeError, ValueError):
        cumulative_rows_read = 0
    # Fresh (non-resumed) runs and the deferred non-live path carry a zero seed,
    # so the delta is the full count; resumed runs meter only their increment.
    rows_this_execution = cumulative_rows_read - resume_records_seed
    if rows_this_execution <= 0:
        return
    record_tenant_usage_event(
        repository,
        tenant_id,
        TenantUsageMetric.CONNECTOR_SYNC_ROWS.value,
        rows_this_execution,
        source_type="connector_sync_execution",
        source_id=source_id,
        window_seconds=usage_window_seconds,
        occurred_at=occurred_at,
        dimensions=dimensions,
    )


def _live_sync_resume_records_seed(repository: AxisPersistenceRepository, run) -> int:
    """Rows already read+committed before this attempt (its resume seed).

    Mirrors the seed :func:`_execute_live_connector_sync` reads from the latest
    committed batch checkpoint. Queried before the attempt runs, so it is the
    pre-attempt cumulative total; the attempt's own new checkpoints do not affect
    it. Zero for a fresh (never-resumed) run.
    """
    latest_batch_checkpoint = repository.get_latest_connector_sync_checkpoint(
        run.tenant_id,
        run_id=run.run_id,
        connector_id=run.connector_id,
        checkpoint_type=SYNC_BATCH_CHECKPOINT_TYPE,
        status=SYNC_BATCH_COMMITTED_STATUS,
    )
    if latest_batch_checkpoint is None:
        return 0
    return _cursor_int(latest_batch_checkpoint.cursor, "total_records_read")


def _live_sync_requested(run_record) -> bool:
    return str(run_record.input_summary.get("live_sync_requested", "false")).lower() == "true"


def _live_sync_retry_allowed(
    run_record,
    existing_execution: ConnectorSyncExecutionResult,
    request: ConnectorRunSyncExecutionRequest,
) -> bool:
    return (
        _live_sync_requested(run_record)
        and existing_execution.status == SYNC_EXECUTION_FAILED_STATUS
        and existing_execution.idempotency_key != request.idempotency_key
        and run_record.result_summary.get("sync_execution_id") != request.execution_id
    )


def _live_sync_field_mappings(manifest) -> list[ConnectorLiveSyncFieldMapping]:
    schema_fields = (manifest.manifest_payload or {}).get("schema_fields") or []
    return [
        ConnectorLiveSyncFieldMapping(
            source_column=str(field.get("source_column", "")),
            target_field=str(field.get("target_field", "")),
            ontology_target=str(field.get("ontology_target", "")),
        )
        for field in schema_fields
        if field.get("source_column") and field.get("target_field")
        and field.get("ontology_target")
    ]


def _validate_active_live_manifest_for_live_sync(manifest) -> None:
    if manifest.status != "active_live":
        raise ConnectorRunValidationError(
            "Connector manifest must be active_live before governed live sync execution.",
            "connector_manifest_not_active_live",
        )


def _apply_tenant_live_sync_row_cap(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    plan: ConnectorLiveSyncPlan,
) -> ConnectorLiveSyncPlan:
    quota = repository.get_tenant_quota(
        tenant_id,
        TenantQuotaKey.MAX_CONNECTOR_SYNC_ROWS_PER_RUN.value,
    )
    if quota is None or plan.max_records <= quota.quota_value:
        return plan
    capped_rows = quota.quota_value
    return plan.model_copy(
        update={
            "max_records": capped_rows,
            "batch_size": max(1, min(plan.batch_size, capped_rows)),
            "notes": [
                *plan.notes,
                "The tenant quota max_connector_sync_rows_per_run capped this "
                "run's row limit.",
            ],
        }
    )


def _execute_live_connector_sync(
    repository: AxisPersistenceRepository,
    run,
    request: ConnectorRunSyncExecutionRequest,
    *,
    live_sync_runtime: ConnectorLiveSyncRuntime,
    plan: ConnectorLiveSyncPlan,
    manifest,
    schedule_result: ConnectorSyncScheduleResult,
    credential_lease=None,
    egress_policy_evidence: dict[str, str] | None = None,
) -> ConnectorSyncExecutionResult:
    base_summary = _live_sync_base_summary(run, request, plan, schedule_result)
    if plan.status == LIVE_SYNC_PLAN_BLOCKED_STATUS:
        return _blocked_live_sync_result(run, request, plan, base_summary)
    if plan.status != LIVE_SYNC_PLAN_READY_STATUS:
        return _failed_live_sync_result(
            run,
            request,
            plan,
            base_summary,
            error_code=plan.error_code or "live_sync_plan_failed",
            batches_committed=0,
            records_synced=0,
            records_rejected=0,
            proposals_recorded=0,
            resume_offset=0,
            next_offset=0,
            external_query_started=False,
        )

    field_mappings = _live_sync_field_mappings(manifest)
    latest_batch_checkpoint = repository.get_latest_connector_sync_checkpoint(
        run.tenant_id,
        run_id=run.run_id,
        connector_id=run.connector_id,
        checkpoint_type=SYNC_BATCH_CHECKPOINT_TYPE,
        status=SYNC_BATCH_COMMITTED_STATUS,
    )
    if latest_batch_checkpoint is not None:
        cursor = latest_batch_checkpoint.cursor
        resume_offset = _cursor_int(cursor, "next_offset")
        records_synced = _cursor_int(cursor, "total_records_read")
        records_rejected = _cursor_int(cursor, "total_records_rejected")
        proposals_recorded = _cursor_int(cursor, "total_proposals_recorded")
        batch_index = _cursor_int(cursor, "batch_index")
    else:
        resume_offset = 0
        records_synced = 0
        records_rejected = 0
        proposals_recorded = 0
        batch_index = 0
    claim_evidence: dict[str, str] = {}
    if latest_batch_checkpoint is not None:
        resume_claim = _validate_live_sync_resume_claim(
            repository,
            run,
            request,
            latest_batch_checkpoint,
        )
        claim_evidence = {
            "checkpoint_claim_evidence_status": "validated",
            "checkpoint_claim_id": resume_claim.claim_id,
            "checkpoint_claim_checkpoint_id": resume_claim.checkpoint_id,
            "checkpoint_claim_worker": resume_claim.claimed_by,
            "checkpoint_claim_lease_expires_at": _datetime_as_utc_string(
                resume_claim.lease_expires_at
            ),
        }
    base_summary.update(claim_evidence)
    checkpoint_sequence = repository.count_connector_sync_checkpoints(
        run.tenant_id,
        run_id=run.run_id,
    )
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=run.tenant_id,
            actor_id=request.executed_by,
            event_type=SYNC_EXECUTION_STARTED_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": run.connector_id,
                "run_id": run.run_id,
                "execution_id": request.execution_id,
                "status": "sync_execution_started",
                "source_mode": plan.source_mode,
                "source_ref": plan.source_ref,
                "resume_offset": str(resume_offset),
                "committed_batches": str(batch_index),
                "batch_size": str(plan.batch_size),
                "max_records": str(plan.max_records),
                "runtime_boundary": run.runtime_boundary,
                "external_sync_started": False,
                "credential_material_returned": "false",
                "graph_mutation_started": "false",
                **claim_evidence,
            },
        )
    )

    offset = resume_offset
    batches_this_execution = 0
    error_code = ""
    external_query_started = False
    while True:
        if plan.max_records > 0 and offset >= plan.max_records:
            # The plan row limit (profile row limit, possibly capped by the
            # tenant quota) is exhausted; stop without reading further rows.
            break
        if batches_this_execution >= LIVE_SYNC_MAX_BATCHES_PER_EXECUTION:
            error_code = "sync_batch_limit_exceeded"
            break
        lease_error = _live_sync_lease_error(repository, run, request.credential_lease_id)
        if lease_error is not None:
            error_code = lease_error
            break
        batch_size = plan.batch_size
        if plan.max_records > 0:
            batch_size = min(batch_size, plan.max_records - offset)
        batch = live_sync_runtime.read_batch(
            ConnectorLiveSyncBatchRequest(
                tenant_id=run.tenant_id,
                connector_id=run.connector_id,
                run_id=run.run_id,
                execution_id=request.execution_id,
                offset=offset,
                batch_size=batch_size,
                field_mappings=field_mappings,
                credential_lease_result=(
                    credential_lease.lease_result if credential_lease is not None else {}
                ),
                credential_secret_provider=(
                    credential_lease.secret_provider if credential_lease is not None else ""
                ),
                credential_secret_ref=(
                    credential_lease.secret_ref if credential_lease is not None else ""
                ),
                egress_policy_evidence=egress_policy_evidence or {},
                input_summary=run.input_summary,
            )
        )
        if batch.status != LIVE_SYNC_BATCH_READ_STATUS:
            error_code = batch.error_code or "sync_batch_failed"
            break
        if batch.evidence_summary:
            # Public-safe runtime security evidence (lease-scoped secret
            # resolution decision, runtime egress enforcement outcome) flows
            # into the batch checkpoint and the final result summary.
            base_summary.update(batch.evidence_summary)
        if plan.external_query_required:
            external_query_started = True
        proposal_count = 0
        if batch.records:
            proposal_count = _record_live_sync_proposals(
                repository,
                run,
                request,
                plan,
                batch.records,
                record_offset=offset,
            )
        batch_index += 1
        checkpoint_sequence += 1
        records_synced += len(batch.records)
        records_rejected += batch.records_rejected
        proposals_recorded += proposal_count
        _record_live_sync_batch_checkpoint(
            repository,
            run,
            request,
            plan,
            batch,
            base_summary=base_summary,
            batch_index=batch_index,
            batch_offset=offset,
            sequence=checkpoint_sequence,
            proposal_count=proposal_count,
            total_records_read=records_synced,
            total_records_rejected=records_rejected,
            total_proposals_recorded=proposals_recorded,
            external_query_started=external_query_started,
        )
        offset = batch.next_offset
        batches_this_execution += 1
        if batch.source_exhausted:
            break

    if error_code:
        return _failed_live_sync_result(
            run,
            request,
            plan,
            base_summary,
            error_code=error_code,
            batches_committed=batch_index,
            records_synced=records_synced,
            records_rejected=records_rejected,
            proposals_recorded=proposals_recorded,
            resume_offset=resume_offset,
            next_offset=offset,
            external_query_started=external_query_started,
        )
    return ConnectorSyncExecutionResult(
        adapter=plan.adapter,
        status="sync_execution_completed",
        sync_ref=_live_sync_ref(run, request, plan),
        external_sync_started=external_query_started,
        idempotency_key=request.idempotency_key,
        result_summary={
            **base_summary,
            "runtime_status": "sync_execution_completed",
            "external_sync_started": _bool_summary_text(external_query_started),
            "live_sync_execution_status": "completed",
            "records_read": str(records_synced),
            "records_accepted": str(records_synced),
            "records_rejected": str(records_rejected),
            "sync_batches_committed": str(batch_index),
            "resume_offset": str(resume_offset),
            "next_offset": str(offset),
            "proposals_recorded": str(proposals_recorded),
            "external_query_started": _bool_summary_text(external_query_started),
        },
        notes=[
            "Governed live connector sync completed through committed batch checkpoints.",
            (
                "Synced rows were persisted as review-only ontology proposals; "
                "no credential material or graph mutation was stored."
            ),
        ],
    )


def _live_sync_base_summary(
    run,
    request: ConnectorRunSyncExecutionRequest,
    plan: ConnectorLiveSyncPlan,
    schedule_result: ConnectorSyncScheduleResult,
) -> dict[str, str]:
    return {
        "connector_id": run.connector_id,
        "schedule_id": schedule_result.result_summary.get("schedule_id", "unknown_schedule"),
        "dispatch_id": run.result_summary.get("dispatch_id", "unknown_dispatch"),
        "execution_id": request.execution_id,
        "live_sync_requested": "true",
        "proposal_write_mode": "proposal_only",
        "source_mode": plan.source_mode or "live_sync_unplanned",
        "source_ref": plan.source_ref or "unknown_source",
        "credential_material_returned": "false",
        "graph_mutation_started": "false",
    }


def _blocked_live_sync_result(
    run,
    request: ConnectorRunSyncExecutionRequest,
    plan: ConnectorLiveSyncPlan,
    base_summary: dict[str, str],
) -> ConnectorSyncExecutionResult:
    return ConnectorSyncExecutionResult(
        adapter=plan.adapter,
        status=SYNC_EXECUTION_LIVE_SYNC_BLOCKED_STATUS,
        sync_ref=_live_sync_ref(run, request, plan, suffix="-blocked"),
        external_sync_started=False,
        idempotency_key=request.idempotency_key,
        result_summary={
            **base_summary,
            "runtime_status": SYNC_EXECUTION_LIVE_SYNC_BLOCKED_STATUS,
            "external_sync_started": "false",
            "live_sync_execution_status": f"blocked_{plan.block_reason or 'policy'}",
            "records_read": "0",
            "records_accepted": "0",
            "records_rejected": "0",
            "sync_batches_committed": "0",
            "proposals_recorded": "0",
            "external_query_started": "false",
        },
        notes=[
            "Governed live connector sync was blocked by Axis runtime policy.",
            "No source read, credential material or graph mutation was started.",
        ],
    )


def _failed_live_sync_result(
    run,
    request: ConnectorRunSyncExecutionRequest,
    plan: ConnectorLiveSyncPlan,
    base_summary: dict[str, str],
    *,
    error_code: str,
    batches_committed: int,
    records_synced: int,
    records_rejected: int,
    proposals_recorded: int,
    resume_offset: int,
    next_offset: int,
    external_query_started: bool,
) -> ConnectorSyncExecutionResult:
    return ConnectorSyncExecutionResult(
        adapter=plan.adapter,
        status=SYNC_EXECUTION_FAILED_STATUS,
        sync_ref=_live_sync_ref(run, request, plan, suffix="-failed"),
        external_sync_started=external_query_started,
        idempotency_key=request.idempotency_key,
        result_summary={
            **base_summary,
            "runtime_status": SYNC_EXECUTION_FAILED_STATUS,
            "external_sync_started": _bool_summary_text(external_query_started),
            "live_sync_execution_status": "failed",
            "sync_error_code": error_code,
            "records_read": str(records_synced),
            "records_accepted": str(records_synced),
            "records_rejected": str(records_rejected),
            "sync_batches_committed": str(batches_committed),
            "resume_offset": str(resume_offset),
            "next_offset": str(next_offset),
            "proposals_recorded": str(proposals_recorded),
            "external_query_started": _bool_summary_text(external_query_started),
        },
        notes=[
            "Governed live connector sync failed closed with persisted checkpoints.",
            "The run can be retried and resumes from the last committed batch checkpoint.",
        ],
    )


def _live_sync_ref(
    run,
    request: ConnectorRunSyncExecutionRequest,
    plan: ConnectorLiveSyncPlan,
    *,
    suffix: str = "",
) -> str:
    scheme = (plan.source_mode or "live_sync_unplanned").replace("_", "-")
    return (
        f"{scheme}{suffix}://{run.tenant_id}/"
        f"{run.run_id}/{request.execution_id}"
    )


def _bool_summary_text(value: bool) -> str:
    return "true" if value else "false"


def _cursor_int(cursor: dict, key: str) -> int:
    try:
        return int(str(cursor.get(key, "0")))
    except ValueError:
        return 0


def _live_sync_lease_error(
    repository: AxisPersistenceRepository,
    run,
    credential_lease_id: str,
) -> str | None:
    try:
        _validate_active_credential_lease_for_run(repository, run, credential_lease_id)
    except ConnectorRunValidationError as exc:
        if exc.reason == "credential_lease_expired":
            return "credential_lease_expired_mid_run"
        return "credential_lease_invalid_mid_run"
    return None


def _validate_live_sync_resume_claim(
    repository: AxisPersistenceRepository,
    run,
    request: ConnectorRunSyncExecutionRequest,
    last_batch_checkpoint,
):
    if request.checkpoint_claim_id is None:
        raise ConnectorRunValidationError(
            "Live connector sync resume requires checkpoint_claim_id for the last "
            "committed batch checkpoint.",
            "checkpoint_claim_id_required_for_live_sync_resume",
        )
    claims = repository.list_connector_sync_checkpoint_claims(
        tenant_id=run.tenant_id,
        checkpoint_id=last_batch_checkpoint.checkpoint_id,
        status="claimed",
        limit=LIVE_SYNC_CHECKPOINT_LIST_LIMIT,
    )
    now = utc_now()
    for claim in claims:
        if claim.claim_id != request.checkpoint_claim_id:
            continue
        if claim.claimed_by != request.executed_by:
            raise ConnectorRunValidationError(
                "Live connector sync resume claim belongs to a different worker.",
                "live_sync_resume_claim_worker_mismatch",
            )
        if _ensure_timezone(claim.lease_expires_at) <= now:
            raise ConnectorRunValidationError(
                "Live connector sync resume claim lease is expired.",
                "live_sync_resume_claim_expired",
            )
        if not _sync_checkpoint_claim_result_is_worker_lease_only(claim.claim_result):
            raise ConnectorRunValidationError(
                "Live connector sync resume claim result evidence is not "
                "worker-lease-only.",
                "live_sync_resume_claim_result_unsafe",
            )
        return claim
    raise ConnectorRunValidationError(
        "Live connector sync resume requires an active checkpoint claim for the "
        "executing worker.",
        "live_sync_resume_claim_not_active",
    )


def _record_live_sync_proposals(
    repository: AxisPersistenceRepository,
    run,
    request: ConnectorRunSyncExecutionRequest,
    plan: ConnectorLiveSyncPlan,
    records,
    *,
    record_offset: int,
) -> int:
    proposal_ids = [
        f"prop_{run.run_id}_r{record_offset + index}"
        for index in range(len(records))
    ]
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=run.tenant_id,
            actor_id=request.executed_by,
            event_type=LIVE_SYNC_PROPOSALS_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": run.connector_id,
                "proposal_ids": proposal_ids,
                "proposal_count": len(proposal_ids),
                "source_run_id": run.run_id,
                "source_file_name": plan.source_ref,
                "mapping_profile": LIVE_SYNC_MAPPING_PROFILE,
                "write_mode": "proposal_only",
                "graph_mutation_status": "not_applied",
                "runtime_boundary": run.runtime_boundary,
            },
        )
    )
    created_count = 0
    for proposal_id, record in zip(proposal_ids, records, strict=True):
        _, created = repository.create_connector_ontology_proposal_if_absent(
            ConnectorOntologyProposalCreate(
                tenant_id=run.tenant_id,
                connector_id=run.connector_id,
                proposal_id=proposal_id,
                source_run_id=run.run_id,
                source_file_name=plan.source_ref,
                mapping_profile=LIVE_SYNC_MAPPING_PROFILE,
                status="proposed_from_preview",
                write_mode="proposal_only",
                graph_mutation_status="not_applied",
                proposed_by=request.executed_by,
                node_id=record.node_id,
                node_type=record.node_type,
                ontology_type=record.ontology_type,
                field_summary=record.field_summary,
                evidence_refs=[plan.source_ref, record.node_id],
                audit_event_id=audit_event.id,
                audit_event_type=LIVE_SYNC_PROPOSALS_AUDIT_EVENT_TYPE,
                notes=[
                    "Proposal derived from governed live connector sync.",
                    "Graph mutation stays behind the approval-gated promotion path.",
                ],
            )
        )
        if created:
            created_count += 1
    return created_count


def _record_live_sync_batch_checkpoint(
    repository: AxisPersistenceRepository,
    run,
    request: ConnectorRunSyncExecutionRequest,
    plan: ConnectorLiveSyncPlan,
    batch,
    *,
    base_summary: dict[str, str],
    batch_index: int,
    batch_offset: int,
    sequence: int,
    proposal_count: int,
    total_records_read: int,
    total_records_rejected: int,
    total_proposals_recorded: int,
    external_query_started: bool,
) -> None:
    checkpoint_id = f"chk_{run.run_id}_batch_{batch_index}"
    batch_summary = {
        **base_summary,
        "runtime_status": SYNC_BATCH_COMMITTED_STATUS,
        "external_sync_started": _bool_summary_text(external_query_started),
        "live_sync_execution_status": "in_progress",
        "batch_index": str(batch_index),
        "batch_offset": str(batch_offset),
        "next_offset": str(batch.next_offset),
        "batch_records_read": str(len(batch.records)),
        "batch_records_rejected": str(batch.records_rejected),
        "batch_proposals_recorded": str(proposal_count),
        "source_exhausted": _bool_summary_text(batch.source_exhausted),
        "external_query_started": _bool_summary_text(external_query_started),
    }
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=run.tenant_id,
            actor_id=request.executed_by,
            event_type=SYNC_BATCH_COMMITTED_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": run.connector_id,
                "run_id": run.run_id,
                "checkpoint_id": checkpoint_id,
                "execution_id": request.execution_id,
                "status": SYNC_BATCH_COMMITTED_STATUS,
                "idempotency_key": request.idempotency_key,
                "runtime_boundary": run.runtime_boundary,
                "external_sync_started": external_query_started,
                "sync_execution_result": {
                    "adapter": batch.adapter,
                    "status": SYNC_BATCH_COMMITTED_STATUS,
                    "result_summary": batch_summary,
                },
            },
        )
    )
    repository.create_connector_sync_checkpoint(
        ConnectorSyncCheckpointCreate(
            tenant_id=run.tenant_id,
            connector_id=run.connector_id,
            run_id=run.run_id,
            checkpoint_id=checkpoint_id,
            checkpoint_type=SYNC_BATCH_CHECKPOINT_TYPE,
            status=SYNC_BATCH_COMMITTED_STATUS,
            sequence=sequence,
            runtime_boundary=run.runtime_boundary,
            adapter=batch.adapter,
            cursor={
                "cursor_type": "live_sync_batch",
                "execution_id": request.execution_id,
                "batch_index": str(batch_index),
                "batch_offset": str(batch_offset),
                "next_offset": str(batch.next_offset),
                "batch_records_read": str(len(batch.records)),
                "batch_records_rejected": str(batch.records_rejected),
                "batch_proposals_recorded": str(proposal_count),
                "total_records_read": str(total_records_read),
                "total_records_rejected": str(total_records_rejected),
                "total_proposals_recorded": str(total_proposals_recorded),
                "source_exhausted": _bool_summary_text(batch.source_exhausted),
                "source_mode": plan.source_mode,
                "external_query_started": _bool_summary_text(external_query_started),
                "graph_mutation_started": "false",
            },
            result_summary=batch_summary,
            evidence_refs=[str(audit_event.id)],
            audit_event_id=audit_event.id,
            audit_event_type=SYNC_BATCH_COMMITTED_AUDIT_EVENT_TYPE,
            notes=[
                "Live sync batch checkpoint committed after governed source read.",
                "Checkpoint payload is public-safe and excludes row payloads.",
            ],
        )
    )


def _record_sync_execution_checkpoint(
    repository: AxisPersistenceRepository,
    run,
    request: ConnectorRunSyncExecutionRequest,
    sync_execution_result: ConnectorSyncExecutionResult,
    audit_event_id: UUID,
    audit_event_type: str,
) -> None:
    existing = repository.list_connector_sync_checkpoints(
        run.tenant_id,
        run_id=run.run_id,
    )
    result_summary = sync_execution_result.result_summary
    cursor = {
        "cursor_type": "sync_execution_result",
        "execution_id": request.execution_id,
        "runtime_status": result_summary.get("runtime_status", sync_execution_result.status),
        "source_mode": result_summary.get("source_mode", "unknown"),
        "external_query_started": result_summary.get("external_query_started", "false"),
        "graph_mutation_started": result_summary.get("graph_mutation_started", "false"),
    }
    for optional_key in (
        "connection_profile_id",
        "schema_name",
        "table_name",
        "query_mode",
        "live_query_preflight_status",
        "live_query_execute_requested",
        "live_query_execution_status",
        "live_query_profile_id",
        "live_query_row_limit",
        "selected_column_count",
        "live_sync_requested",
        "live_sync_execution_status",
        "sync_error_code",
        "sync_batches_committed",
        "resume_offset",
        "next_offset",
        "proposals_recorded",
        "source_ref",
    ):
        if optional_key in result_summary:
            cursor[optional_key] = result_summary[optional_key]

    repository.create_connector_sync_checkpoint(
        ConnectorSyncCheckpointCreate(
            tenant_id=run.tenant_id,
            connector_id=run.connector_id,
            run_id=run.run_id,
            checkpoint_id=f"chk_{request.execution_id}",
            checkpoint_type="sync_execution",
            status=sync_execution_result.status,
            sequence=len(existing) + 1,
            runtime_boundary=run.runtime_boundary,
            adapter=sync_execution_result.adapter,
            cursor=cursor,
            result_summary=result_summary,
            evidence_refs=[str(audit_event_id)],
            audit_event_id=audit_event_id,
            audit_event_type=audit_event_type,
            notes=[
                "Sync checkpoint captured after the Axis runtime adapter returned.",
                "Checkpoint payload is public-safe and excludes credential material.",
            ],
        )
    )


def _validate_active_worker_checkpoint_claim_for_live_query(
    repository: AxisPersistenceRepository,
    run,
    request: ConnectorRunSyncExecutionRequest,
):
    if str(run.input_summary.get("live_query_requested", "false")).lower() != "true":
        return None

    if request.checkpoint_claim_id is None:
        raise ConnectorRunValidationError(
            "Live connector sync requires checkpoint_claim_id for live-query execution.",
            "checkpoint_claim_id_required_for_live_query",
        )

    claims = repository.list_connector_sync_checkpoint_claims(
        tenant_id=run.tenant_id,
        connector_id=run.connector_id,
        run_id=run.run_id,
        status="claimed",
        claimed_by=request.executed_by,
        limit=200,
    )
    now = utc_now()
    for claim in claims:
        if claim.claim_id != request.checkpoint_claim_id:
            continue
        if _ensure_timezone(claim.lease_expires_at) <= now:
            continue
        if claim.audit_event_type != SYNC_CHECKPOINT_CLAIMED_AUDIT_EVENT_TYPE:
            raise ConnectorRunValidationError(
                "Live connector sync checkpoint claim is not backed by a "
                "claim-created audit event.",
                "target_sync_checkpoint_claim_audit_invalid",
            )
        claim_audit_event = repository.get_audit_event(
            run.tenant_id,
            claim.audit_event_id,
        )
        if claim_audit_event is None:
            raise ConnectorRunValidationError(
                "Live connector sync checkpoint claim references an audit "
                "event that does not exist.",
                "target_sync_checkpoint_claim_audit_event_not_found",
            )
        if (
            claim_audit_event.event_type != claim.audit_event_type
            or claim_audit_event.payload.get("connector_id") != run.connector_id
            or claim_audit_event.payload.get("run_id") != run.run_id
            or claim_audit_event.payload.get("checkpoint_id") != claim.checkpoint_id
            or claim_audit_event.payload.get("claim_id") != claim.claim_id
            or claim_audit_event.payload.get("claimed_by") != claim.claimed_by
        ):
            raise ConnectorRunValidationError(
                "Live connector sync checkpoint claim is not backed by a "
                "matching audit ledger event.",
                "target_sync_checkpoint_claim_audit_event_mismatch",
            )
        if not _sync_checkpoint_claim_result_is_worker_lease_only(
            claim_audit_event.payload
        ):
            raise ConnectorRunValidationError(
                "Live connector sync checkpoint claim audit payload is not "
                "worker-lease-only.",
                "target_sync_checkpoint_claim_audit_payload_unsafe",
            )
        checkpoint = repository.get_connector_sync_checkpoint(
            run.tenant_id,
            claim.checkpoint_id,
        )
        if checkpoint is None:
            raise ConnectorRunValidationError(
                "Live connector sync requires persisted checkpoint evidence "
                "for the targeted claim.",
                "target_sync_checkpoint_claim_checkpoint_not_found",
            )
        if checkpoint.connector_id != run.connector_id or checkpoint.run_id != run.run_id:
            raise ConnectorRunValidationError(
                "Live connector sync checkpoint claim evidence does not match the run.",
                "target_sync_checkpoint_claim_checkpoint_mismatch",
            )
        if (
            checkpoint.checkpoint_type != "sync_execution"
            or checkpoint.status != "sync_execution_preflight_passed"
        ):
            raise ConnectorRunValidationError(
                "Live connector sync checkpoint claim evidence is not eligible.",
                "target_sync_checkpoint_claim_checkpoint_not_eligible",
            )
        if (
            checkpoint.audit_event_type
            != "connector.run.sync_execution_preflight_passed"
        ):
            raise ConnectorRunValidationError(
                "Live connector sync checkpoint claim evidence is not backed "
                "by a preflight-passed audit event.",
                "target_sync_checkpoint_claim_checkpoint_audit_invalid",
            )
        if checkpoint.audit_event_id is None or str(checkpoint.audit_event_id) not in (
            checkpoint.evidence_refs or []
        ):
            raise ConnectorRunValidationError(
                "Live connector sync checkpoint evidence does not reference "
                "its audit event.",
                "target_sync_checkpoint_claim_checkpoint_evidence_ref_missing",
            )
        checkpoint_audit_event = repository.get_audit_event(
            run.tenant_id,
            checkpoint.audit_event_id,
        )
        if checkpoint_audit_event is None:
            raise ConnectorRunValidationError(
                "Live connector sync checkpoint evidence references an audit "
                "event that does not exist.",
                "target_sync_checkpoint_claim_checkpoint_audit_event_not_found",
            )
        if (
            checkpoint_audit_event.event_type != checkpoint.audit_event_type
            or checkpoint_audit_event.payload.get("connector_id") != run.connector_id
            or checkpoint_audit_event.payload.get("run_id") != run.run_id
            or checkpoint_audit_event.payload.get("checkpoint_id")
            != checkpoint.checkpoint_id
        ):
            raise ConnectorRunValidationError(
                "Live connector sync checkpoint evidence is not backed by a "
                "matching audit ledger event.",
                "target_sync_checkpoint_claim_checkpoint_audit_event_mismatch",
            )
        if not _sync_checkpoint_result_is_public_safe(checkpoint_audit_event.payload):
            raise ConnectorRunValidationError(
                "Live connector sync checkpoint audit payload is not public-safe.",
                "target_sync_checkpoint_claim_checkpoint_audit_payload_unsafe",
            )
        if not _sync_checkpoint_result_is_public_safe(checkpoint.result_summary):
            raise ConnectorRunValidationError(
                "Live connector sync checkpoint result evidence is not public-safe.",
                "target_sync_checkpoint_claim_checkpoint_result_unsafe",
            )
        if not _sync_checkpoint_claim_result_is_worker_lease_only(claim.claim_result):
            raise ConnectorRunValidationError(
                "Live connector sync checkpoint claim result evidence is not "
                "worker-lease-only.",
                "target_sync_checkpoint_claim_result_unsafe",
            )
        return claim

    raise ConnectorRunValidationError(
        "Live connector sync requires an active checkpoint claim for the executing worker.",
        "target_sync_checkpoint_claim_not_active",
    )


def _sync_checkpoint_result_is_public_safe(result_summary: dict) -> bool:
    if _contains_forbidden_checkpoint_public_marker(result_summary):
        return False
    summaries = _sync_execution_result_summaries(result_summary)
    if not summaries:
        summaries = [result_summary]
    return all(_sync_execution_result_summary_is_public_safe(summary) for summary in summaries)


def _sync_execution_result_summaries(payload: dict) -> list[dict]:
    sync_execution_result = payload.get("sync_execution_result")
    if not isinstance(sync_execution_result, dict):
        return []
    nested_summary = sync_execution_result.get("result_summary")
    return [nested_summary] if isinstance(nested_summary, dict) else []


def _sync_execution_result_summary_is_public_safe(result_summary: dict) -> bool:
    if str(result_summary.get("credential_material_returned", "false")).lower() != "false":
        return False
    if str(result_summary.get("graph_mutation_started", "false")).lower() != "false":
        return False
    external_query_started = str(
        result_summary.get("external_query_started", "false")
    ).lower()
    if external_query_started == "false":
        return True
    if external_query_started != "true":
        return False
    if result_summary.get("source_mode") == "external_db_live_sync":
        if result_summary.get("live_sync_execution_status") not in (
            LIVE_SYNC_EXECUTION_STATUSES
        ):
            return False
        return set(result_summary) <= LIVE_SYNC_PUBLIC_SAFE_RESULT_SUMMARY_KEYS
    if result_summary.get("source_mode") != "external_db_live_read":
        return False
    if result_summary.get("live_query_execution_status") != "completed":
        return False
    return set(result_summary) <= LIVE_READ_PUBLIC_SAFE_RESULT_SUMMARY_KEYS


def _contains_forbidden_checkpoint_public_marker(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_forbidden_checkpoint_public_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_checkpoint_public_marker(item) for item in value)
    serialized = str(value).lower()
    return any(marker in serialized for marker in SYNC_CHECKPOINT_FORBIDDEN_PUBLIC_MARKERS)


def _sync_checkpoint_claim_result_is_worker_lease_only(claim_result: dict) -> bool:
    if str(claim_result.get("external_sync_started", "false")).lower() != "false":
        return False
    if str(claim_result.get("secret_material_returned", "false")).lower() != "false":
        return False
    return str(claim_result.get("worker_claim_only", "true")).lower() == "true"


def _checkpoint_evidence_invariant(
    repository: AxisPersistenceRepository,
    checkpoint,
) -> ConnectorSyncCheckpointEvidenceInvariant | None:
    audit_event_id = str(checkpoint.audit_event_id) if checkpoint.audit_event_id else None
    if checkpoint.audit_event_id is None:
        return ConnectorSyncCheckpointEvidenceInvariant(
            checkpoint_id=checkpoint.checkpoint_id,
            audit_event_id=None,
            reason="checkpoint_audit_event_missing",
            detail="Checkpoint must reference an append-only audit event.",
        )
    if str(checkpoint.audit_event_id) not in (checkpoint.evidence_refs or []):
        return ConnectorSyncCheckpointEvidenceInvariant(
            checkpoint_id=checkpoint.checkpoint_id,
            audit_event_id=audit_event_id,
            reason="checkpoint_audit_event_ref_missing",
            detail="Checkpoint evidence_refs must include its audit event id.",
        )
    audit_event = repository.get_audit_event(
        checkpoint.tenant_id,
        checkpoint.audit_event_id,
    )
    if audit_event is None:
        return ConnectorSyncCheckpointEvidenceInvariant(
            checkpoint_id=checkpoint.checkpoint_id,
            audit_event_id=audit_event_id,
            reason="checkpoint_audit_event_not_found",
            detail="Checkpoint audit event id must resolve in the tenant ledger.",
        )
    if audit_event.event_type != checkpoint.audit_event_type:
        return ConnectorSyncCheckpointEvidenceInvariant(
            checkpoint_id=checkpoint.checkpoint_id,
            audit_event_id=audit_event_id,
            reason="checkpoint_audit_event_type_mismatch",
            detail="Checkpoint audit event type must match the checkpoint record.",
        )
    if (
        audit_event.payload.get("connector_id") != checkpoint.connector_id
        or audit_event.payload.get("run_id") != checkpoint.run_id
        or audit_event.payload.get("checkpoint_id") != checkpoint.checkpoint_id
    ):
        return ConnectorSyncCheckpointEvidenceInvariant(
            checkpoint_id=checkpoint.checkpoint_id,
            audit_event_id=audit_event_id,
            reason="checkpoint_audit_event_payload_mismatch",
            detail=(
                "Checkpoint audit event payload must match connector_id, "
                "run_id and checkpoint_id."
            ),
        )
    if not _sync_checkpoint_result_is_public_safe(audit_event.payload):
        return ConnectorSyncCheckpointEvidenceInvariant(
            checkpoint_id=checkpoint.checkpoint_id,
            audit_event_id=audit_event_id,
            reason="checkpoint_audit_payload_unsafe",
            detail="Checkpoint audit event payload must remain public-safe.",
        )
    if not _sync_checkpoint_result_is_public_safe(checkpoint.result_summary):
        return ConnectorSyncCheckpointEvidenceInvariant(
            checkpoint_id=checkpoint.checkpoint_id,
            audit_event_id=audit_event_id,
            reason="checkpoint_result_unsafe",
            detail="Checkpoint result evidence must remain public-safe.",
        )
    return None


def _claim_evidence_invariant(
    repository: AxisPersistenceRepository,
    claim,
) -> ConnectorSyncCheckpointClaimEvidenceInvariant | None:
    audit_event_id = str(claim.audit_event_id) if claim.audit_event_id else None
    if claim.audit_event_id is None:
        return ConnectorSyncCheckpointClaimEvidenceInvariant(
            claim_id=claim.claim_id,
            checkpoint_id=claim.checkpoint_id,
            audit_event_id=None,
            reason="claim_audit_event_missing",
            detail="Claim must reference an append-only audit event.",
        )
    audit_event = repository.get_audit_event(claim.tenant_id, claim.audit_event_id)
    if audit_event is None:
        return ConnectorSyncCheckpointClaimEvidenceInvariant(
            claim_id=claim.claim_id,
            checkpoint_id=claim.checkpoint_id,
            audit_event_id=audit_event_id,
            reason="claim_audit_event_not_found",
            detail="Claim audit event id must resolve in the tenant ledger.",
        )
    if audit_event.event_type != claim.audit_event_type:
        return ConnectorSyncCheckpointClaimEvidenceInvariant(
            claim_id=claim.claim_id,
            checkpoint_id=claim.checkpoint_id,
            audit_event_id=audit_event_id,
            reason="claim_audit_event_type_mismatch",
            detail="Claim audit event type must match the claim record.",
        )
    if (
        audit_event.payload.get("connector_id") != claim.connector_id
        or audit_event.payload.get("run_id") != claim.run_id
        or audit_event.payload.get("checkpoint_id") != claim.checkpoint_id
        or audit_event.payload.get("claim_id") != claim.claim_id
        or (
            claim.audit_event_type == SYNC_CHECKPOINT_CLAIMED_AUDIT_EVENT_TYPE
            and audit_event.payload.get("claimed_by") != claim.claimed_by
        )
    ):
        return ConnectorSyncCheckpointClaimEvidenceInvariant(
            claim_id=claim.claim_id,
            checkpoint_id=claim.checkpoint_id,
            audit_event_id=audit_event_id,
            reason="claim_audit_event_payload_mismatch",
            detail=(
                "Claim audit event payload must match connector_id, run_id, "
                "checkpoint_id, claim_id and claimed_by."
            ),
        )
    if not _sync_checkpoint_claim_result_is_worker_lease_only(audit_event.payload):
        return ConnectorSyncCheckpointClaimEvidenceInvariant(
            claim_id=claim.claim_id,
            checkpoint_id=claim.checkpoint_id,
            audit_event_id=audit_event_id,
            reason="claim_audit_payload_unsafe",
            detail="Claim audit event payload must remain worker-lease-only.",
        )
    if not _sync_checkpoint_claim_result_is_worker_lease_only(claim.claim_result):
        return ConnectorSyncCheckpointClaimEvidenceInvariant(
            claim_id=claim.claim_id,
            checkpoint_id=claim.checkpoint_id,
            audit_event_id=audit_event_id,
            reason="claim_result_unsafe",
            detail="Claim result evidence must remain worker-lease-only.",
        )
    return None


def _run_from_record(record) -> ConnectorRunRecord:
    return ConnectorRunRecord(
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
        execution_result=_execution_result_from_summary(record.result_summary),
        schedule_result=_schedule_result_from_summary(record.result_summary),
        dispatch_result=_dispatch_result_from_summary(record.result_summary),
        sync_execution_result=_sync_execution_result_from_summary(record.result_summary),
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        notes=record.notes,
        created_at=record.created_at,
    )


def _checkpoint_from_record(record) -> ConnectorSyncCheckpointRecord:
    return ConnectorSyncCheckpointRecord(
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
        created_at=record.created_at,
    )


def _checkpoint_claim_from_record(record) -> ConnectorSyncCheckpointClaimRecord:
    return ConnectorSyncCheckpointClaimRecord(
        tenant_id=record.tenant_id,
        connector_id=record.connector_id,
        run_id=record.run_id,
        checkpoint_id=record.checkpoint_id,
        claim_id=record.claim_id,
        status=record.status,
        claimed_by=record.claimed_by,
        idempotency_key=record.idempotency_key,
        lease_duration_seconds=record.lease_duration_seconds,
        lease_expires_at=_ensure_timezone(record.lease_expires_at),
        renewed_at=_optional_ensure_timezone(record.renewed_at),
        renewed_by=record.renewed_by,
        renewal_count=record.renewal_count,
        released_at=_optional_ensure_timezone(record.released_at),
        released_by=record.released_by,
        release_reason=record.release_reason,
        claim_result=record.claim_result,
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        notes=record.notes,
        created_at=_ensure_timezone(record.created_at),
    )


def _active_checkpoint_claim(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    checkpoint_id: str,
    claim_id: str,
):
    claim = repository.get_connector_sync_checkpoint_claim(
        tenant_id,
        checkpoint_id,
        claim_id,
    )
    if claim is None:
        raise ConnectorRunNotFound()
    if claim.status != "claimed":
        raise ConnectorRunValidationError(
            "Connector sync checkpoint claim is not active.",
            "connector_sync_checkpoint_claim_not_active",
        )
    return claim


def _active_unexpired_checkpoint_claim(
    claims: list,
    now: datetime,
):
    for claim in claims:
        if _ensure_timezone(claim.lease_expires_at) > _ensure_timezone(now):
            return claim
    return None


def _expire_stale_checkpoint_claims(
    repository: AxisPersistenceRepository,
    request: ConnectorSyncCheckpointClaimRequest,
    checkpoint,
    claims: list,
    now: datetime,
) -> None:
    for claim in claims:
        if _ensure_timezone(claim.lease_expires_at) > _ensure_timezone(now):
            continue
        claim_result = _worker_claim_result()
        audit_event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=request.tenant_id,
                actor_id=request.claimed_by,
                event_type=SYNC_CHECKPOINT_CLAIM_EXPIRED_AUDIT_EVENT_TYPE,
                payload={
                    "connector_id": checkpoint.connector_id,
                    "run_id": checkpoint.run_id,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "expired_claim_id": claim.claim_id,
                    "replacement_claim_id": request.claim_id,
                    "expired_at": _datetime_as_utc_string(now),
                    "lease_expires_at": _datetime_as_utc_string(claim.lease_expires_at),
                    "required_permission": SYNC_CHECKPOINT_CLAIM_SCOPE,
                    **claim_result,
                },
            )
        )
        repository.expire_connector_sync_checkpoint_claim(
            ConnectorSyncCheckpointClaimExpirationRecord(
                tenant_id=request.tenant_id,
                checkpoint_id=checkpoint.checkpoint_id,
                claim_id=claim.claim_id,
                expired_at=now,
                audit_event_id=audit_event.id,
                audit_event_type=SYNC_CHECKPOINT_CLAIM_EXPIRED_AUDIT_EVENT_TYPE,
                note=f"Claim expired before replacement claim {request.claim_id}.",
            )
        )


def _worker_claim_result() -> dict[str, bool]:
    return {
        "external_sync_started": False,
        "secret_material_returned": False,
        "worker_claim_only": True,
    }


def _manifest_for_connector(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    connector_id: str,
):
    registry = require_persisted_manufacturing_connector_registry(
        repository, tenant_id=tenant_id
    )
    for connector in registry.connectors:
        if connector.manifest.connector_id == connector_id:
            return connector.manifest
    raise ConnectorRunValidationError(
        f"Unsupported connector_id: {connector_id}",
        "unsupported_connector_id",
    )


def _active_preview_manifest_for_connector(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    connector_id: str,
):
    _manifest_for_connector(repository, tenant_id, connector_id)
    manifest = repository.get_connector_manifest(tenant_id, connector_id)
    if manifest is None:
        raise ConnectorRunValidationError(
            "Connector manifest must be registered before connector run operations.",
            "connector_manifest_not_found",
        )
    if manifest.status not in {"active_preview", "active_live"}:
        raise ConnectorRunValidationError(
            "Connector manifest must be active_preview before connector run operations.",
            "connector_manifest_not_active_preview",
        )
    return manifest


def _validate_active_live_manifest_for_live_query_execution(manifest, run_record) -> None:
    if str(run_record.input_summary.get("live_query_execute", "false")).lower() != "true":
        return
    if manifest.status != "active_live":
        raise ConnectorRunValidationError(
            "Connector manifest must be active_live before external DB live-query execution.",
            "connector_manifest_not_active_live",
        )


def _validate_execution_mode(execution_mode: str) -> None:
    if execution_mode in ALLOWED_EXECUTION_MODES:
        return
    raise ConnectorRunValidationError(
        (
            "Only preview, manual_import_record, governed_dry_run and "
            "scheduled_sync_plan records are supported."
        ),
        "unsupported_execution_mode",
    )


def _validate_redacted_summary(summary: dict[str, str]) -> None:
    for key in summary:
        if key.lower() in RAW_PAYLOAD_FIELD_NAMES:
            raise ConnectorRunValidationError(
                "Connector run summaries cannot include raw payload or credential fields.",
                "raw_payload_field",
            )


def _status_for_execution_mode(execution_mode: str) -> str:
    if execution_mode == "manual_import_record":
        return "recorded_manual_import_only"
    return "recorded_preview_only"


def _schedule_connector_sync(
    repository: AxisPersistenceRepository,
    request: ConnectorRunCreateRequest,
    *,
    runtime_boundary: str,
    sync_scheduler_runtime: ConnectorSyncSchedulerRuntime,
) -> ConnectorSyncScheduleResult | None:
    if request.execution_mode != SCHEDULED_SYNC_PLAN_MODE:
        return None

    _validate_governed_execution_credentials(repository, request)
    _validate_schedule_request(request)
    _validate_active_credential_lease(repository, request)

    return sync_scheduler_runtime.schedule(
        ConnectorSyncScheduleRequest(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
            run_id=request.run_id,
            execution_mode=request.execution_mode,
            runtime_boundary=runtime_boundary,
            requested_by=request.requested_by,
            credential_handle_ids=request.credential_handle_ids,
            credential_lease_id=request.credential_lease_id or "",
            schedule_id=request.schedule_id or "",
            schedule_cadence=request.schedule_cadence or "",
            schedule_timezone=request.schedule_timezone or "",
            next_run_at=_datetime_as_utc_string(request.next_run_at) or "",
            input_summary=request.input_summary,
        )
    )


def _execute_connector_run(
    repository: AxisPersistenceRepository,
    request: ConnectorRunCreateRequest,
    *,
    runtime_boundary: str,
    execution_runtime: ConnectorExecutionRuntime,
) -> ConnectorExecutionResult | None:
    if request.execution_mode != GOVERNED_EXECUTION_MODE:
        return None

    _validate_governed_execution_credentials(repository, request)
    return execution_runtime.execute(
        ConnectorExecutionRequest(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
            run_id=request.run_id,
            execution_mode=request.execution_mode,
            runtime_boundary=runtime_boundary,
            requested_by=request.requested_by,
            credential_handle_ids=request.credential_handle_ids,
            input_summary=request.input_summary,
        )
    )


def _validate_schedule_request(request: ConnectorRunCreateRequest) -> None:
    required_fields = {
        "credential_lease_id": request.credential_lease_id,
        "schedule_id": request.schedule_id,
        "schedule_cadence": request.schedule_cadence,
        "schedule_timezone": request.schedule_timezone,
        "next_run_at": request.next_run_at,
    }
    for field_name, value in required_fields.items():
        if value is None:
            raise ConnectorRunValidationError(
                f"Scheduled connector sync requires {field_name}.",
                f"{field_name}_required",
            )


def _validate_active_credential_lease(
    repository: AxisPersistenceRepository,
    request: ConnectorRunCreateRequest,
) -> None:
    lease = repository.get_connector_credential_lease(
        request.tenant_id,
        request.credential_lease_id or "",
    )
    if lease is None:
        raise ConnectorRunValidationError(
            "Connector credential lease not found.",
            "credential_lease_not_found",
        )
    if lease.connector_id != request.connector_id:
        raise ConnectorRunValidationError(
            "Connector credential lease belongs to a different connector.",
            "credential_lease_connector_mismatch",
        )
    if lease.handle_id not in request.credential_handle_ids:
        raise ConnectorRunValidationError(
            "Connector credential lease must match one requested credential handle.",
            "credential_lease_handle_mismatch",
        )
    if lease.status != "active":
        raise ConnectorRunValidationError(
            "Connector credential lease must be active.",
            "credential_lease_inactive",
        )
    if _ensure_timezone(lease.expires_at) <= utc_now():
        raise ConnectorRunValidationError(
            "Connector credential lease is expired.",
            "credential_lease_expired",
        )


def _validate_dispatch_scope(request: ConnectorRunDispatchRequest) -> None:
    if SYNC_DISPATCH_SCOPE not in request.actor_scopes:
        raise ConnectorRunPermissionDenied(SYNC_DISPATCH_SCOPE)


def _validate_sync_execution_scope(request: ConnectorRunSyncExecutionRequest) -> None:
    if SYNC_EXECUTION_SCOPE not in request.actor_scopes:
        raise ConnectorRunPermissionDenied(SYNC_EXECUTION_SCOPE)


def _validate_sync_checkpoint_claim_scope(
    request: ConnectorSyncCheckpointClaimRequest,
) -> None:
    if SYNC_CHECKPOINT_CLAIM_SCOPE not in request.actor_scopes:
        raise ConnectorRunPermissionDenied(SYNC_CHECKPOINT_CLAIM_SCOPE)


def _validate_sync_checkpoint_claim_renew_scope(
    request: ConnectorSyncCheckpointClaimRenewRequest,
) -> None:
    if SYNC_CHECKPOINT_CLAIM_RENEW_SCOPE not in request.actor_scopes:
        raise ConnectorRunPermissionDenied(SYNC_CHECKPOINT_CLAIM_RENEW_SCOPE)


def _validate_sync_checkpoint_claim_release_scope(
    request: ConnectorSyncCheckpointClaimReleaseRequest,
) -> None:
    if SYNC_CHECKPOINT_CLAIM_RELEASE_SCOPE not in request.actor_scopes:
        raise ConnectorRunPermissionDenied(SYNC_CHECKPOINT_CLAIM_RELEASE_SCOPE)


def _validate_dispatchable_scheduled_run(record) -> None:
    if record.execution_mode != SCHEDULED_SYNC_PLAN_MODE:
        raise ConnectorRunValidationError(
            "Only scheduled sync plan run records can be dispatched.",
            "unsupported_dispatch_execution_mode",
        )
    if record.status != "sync_schedule_deferred":
        raise ConnectorRunValidationError(
            "Connector sync run is not waiting for dispatch.",
            "connector_run_not_dispatchable",
        )


def _validate_executable_scheduled_run(record) -> None:
    if record.execution_mode != SCHEDULED_SYNC_PLAN_MODE:
        raise ConnectorRunValidationError(
            "Only scheduled sync plan run records can be executed.",
            "unsupported_sync_execution_mode",
        )
    if record.status == "sync_dispatch_deferred":
        return
    if record.status == SYNC_EXECUTION_FAILED_STATUS and _live_sync_requested(record):
        return
    raise ConnectorRunValidationError(
        "Connector sync run is not waiting for execution.",
        "connector_run_not_executable",
    )


def _validate_active_credential_lease_for_run(
    repository: AxisPersistenceRepository,
    run_record,
    credential_lease_id: str,
):
    lease = repository.get_connector_credential_lease(
        run_record.tenant_id,
        credential_lease_id,
    )
    if lease is None:
        raise ConnectorRunValidationError(
            "Connector credential lease not found.",
            "credential_lease_not_found",
        )
    if lease.connector_id != run_record.connector_id:
        raise ConnectorRunValidationError(
            "Connector credential lease belongs to a different connector.",
            "credential_lease_connector_mismatch",
        )
    if lease.handle_id not in run_record.credential_handle_ids:
        raise ConnectorRunValidationError(
            "Connector credential lease must match one requested credential handle.",
            "credential_lease_handle_mismatch",
        )
    if lease.status != "active":
        raise ConnectorRunValidationError(
            "Connector credential lease must be active.",
            "credential_lease_inactive",
        )
    if _ensure_timezone(lease.expires_at) <= utc_now():
        raise ConnectorRunValidationError(
            "Connector credential lease is expired.",
            "credential_lease_expired",
        )
    return lease


def _egress_policy_evidence_for_run(
    repository: AxisPersistenceRepository,
    run_record,
) -> dict[str, str]:
    live_source_requested = (
        run_record.input_summary.get("live_query_requested", "false").lower() == "true"
        or _live_sync_requested(run_record)
    )
    if (
        run_record.connector_id != "external_db_operational_mirror"
        or not live_source_requested
    ):
        return {}

    policy_id = run_record.input_summary.get("egress_policy_id", "")
    connection_profile_id = run_record.input_summary.get(
        "connection_profile_id",
        "unknown_profile",
    )
    requested_boundary = run_record.input_summary.get("egress_boundary", "")
    requested_scope = f"{run_record.connector_id}:{connection_profile_id}"
    missing_evidence = {
        "egress_policy_evidence_status": "missing",
        "egress_policy_runtime_boundary": "axis-egress-policy-enforcer",
        "egress_policy_result_status": "egress_policy_not_found",
        "egress_policy_ref": (
            f"self-hosted-egress-policy://{run_record.tenant_id}/"
            f"{policy_id or 'missing'}"
        ),
        "egress_policy_scope": requested_scope,
        "egress_policy_mode": "unknown",
        "egress_policy_private_endpoint_ref": "",
        "egress_policy_endpoint_target_sha256": "",
    }
    if not policy_id:
        return missing_evidence

    policy = repository.get_connector_egress_policy(run_record.tenant_id, policy_id)
    if policy is None:
        return missing_evidence

    evidence = {
        "egress_policy_runtime_boundary": policy.runtime_boundary,
        "egress_policy_ref": (
            f"self-hosted-egress-policy://{policy.tenant_id}/{policy.policy_id}"
        ),
        "egress_policy_scope": f"{policy.connector_id}:{policy.connection_profile_id}",
        "egress_policy_mode": policy.policy_mode,
        "egress_policy_private_endpoint_ref": policy.private_endpoint_ref,
        "egress_policy_endpoint_target_sha256": str(
            policy.policy_document.get("approved_endpoint_target_sha256", "")
        ),
    }
    if policy.status != "active":
        return {
            **evidence,
            "egress_policy_evidence_status": "failed",
            "egress_policy_result_status": "egress_policy_inactive",
        }
    if policy.connector_id != run_record.connector_id:
        return {
            **evidence,
            "egress_policy_evidence_status": "failed",
            "egress_policy_result_status": "egress_policy_connector_mismatch",
        }
    if policy.connection_profile_id != connection_profile_id:
        return {
            **evidence,
            "egress_policy_evidence_status": "failed",
            "egress_policy_result_status": "egress_policy_profile_mismatch",
        }
    if (
        policy.egress_boundary != requested_boundary
        or policy.policy_mode != "approved_private_endpoint"
    ):
        return {
            **evidence,
            "egress_policy_evidence_status": "failed",
            "egress_policy_result_status": "egress_policy_boundary_mismatch",
        }
    return {
        **evidence,
        "egress_policy_evidence_status": "validated",
        "egress_policy_result_status": "egress_policy_approved",
    }


def _validate_governed_execution_credentials(
    repository: AxisPersistenceRepository,
    request: ConnectorRunCreateRequest,
) -> None:
    if not request.credential_handle_ids:
        raise ConnectorRunValidationError(
            "Governed connector execution requires at least one credential handle id.",
            "credential_handle_required",
        )

    for handle_id in request.credential_handle_ids:
        handle = repository.get_connector_credential_handle(request.tenant_id, handle_id)
        if handle is None:
            raise ConnectorRunValidationError(
                "Connector credential handle not found.",
                "credential_handle_not_found",
            )
        if handle.connector_id != request.connector_id:
            raise ConnectorRunValidationError(
                "Connector credential handle belongs to a different connector.",
                "credential_handle_connector_mismatch",
            )
        if handle.status != "active":
            raise ConnectorRunValidationError(
                "Connector credential handle must be active.",
                "credential_handle_inactive",
            )


def _datetime_as_utc_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_timezone(value).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _optional_ensure_timezone(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _ensure_timezone(value)


def _execution_result_from_summary(result_summary: dict) -> ConnectorExecutionResult | None:
    raw_result = result_summary.get("execution_result")
    if not isinstance(raw_result, dict):
        return None
    return ConnectorExecutionResult.model_validate(raw_result)


def _schedule_result_from_summary(result_summary: dict) -> ConnectorSyncScheduleResult | None:
    raw_result = result_summary.get("sync_schedule_result")
    if not isinstance(raw_result, dict):
        return None
    return ConnectorSyncScheduleResult.model_validate(raw_result)


def _dispatch_result_from_summary(result_summary: dict) -> ConnectorSyncDispatchResult | None:
    raw_result = result_summary.get("sync_dispatch_result")
    if not isinstance(raw_result, dict):
        return None
    return ConnectorSyncDispatchResult.model_validate(raw_result)


def _sync_execution_result_from_summary(
    result_summary: dict,
) -> ConnectorSyncExecutionResult | None:
    raw_result = result_summary.get("sync_execution_result")
    if not isinstance(raw_result, dict):
        return None
    return ConnectorSyncExecutionResult.model_validate(raw_result)


def _sync_execution_audit_event_type(result: ConnectorSyncExecutionResult) -> str:
    if result.status == "sync_execution_completed":
        return SYNC_EXECUTION_COMPLETED_AUDIT_EVENT_TYPE
    if result.status == "sync_execution_preflight_blocked":
        return SYNC_EXECUTION_PREFLIGHT_BLOCKED_AUDIT_EVENT_TYPE
    if result.status == "sync_execution_preflight_passed":
        return SYNC_EXECUTION_PREFLIGHT_PASSED_AUDIT_EVENT_TYPE
    if result.status == "sync_execution_live_query_blocked":
        return SYNC_EXECUTION_LIVE_QUERY_BLOCKED_AUDIT_EVENT_TYPE
    if result.status == SYNC_EXECUTION_LIVE_SYNC_BLOCKED_STATUS:
        return SYNC_EXECUTION_LIVE_SYNC_BLOCKED_AUDIT_EVENT_TYPE
    if result.status == SYNC_EXECUTION_FAILED_STATUS:
        return SYNC_EXECUTION_FAILED_AUDIT_EVENT_TYPE
    return SYNC_EXECUTION_DEFERRED_AUDIT_EVENT_TYPE
