import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from axis_api.audit import AuditEventCreate
from axis_api.audit_signing import (
    AuditLedgerSignatureProof,
    AuditLedgerSigner,
    canonical_ledger_signature_payload,
    unsigned_audit_ledger_signature,
)
from axis_api.connector_credential_leases import (
    ConnectorCredentialLeaseQuery,
    ManufacturingConnectorCredentialLeaseRegistry,
    build_connector_credential_lease_registry,
)
from axis_api.connector_egress_policies import (
    ConnectorEgressPolicyQuery,
    ManufacturingConnectorEgressPolicyRegistry,
    build_connector_egress_policy_registry,
)
from axis_api.connector_runs import (
    ConnectorSyncCheckpointClaimQuery,
    ConnectorSyncCheckpointQuery,
    ManufacturingConnectorSyncCheckpointRegistry,
    build_connector_sync_checkpoint_claim_registry,
    build_connector_sync_checkpoint_registry,
)
from axis_api.demo import ApprovalDecision, OverviewMetric, OverviewStatus
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    find_manufacturing_tenant_metadata,
    operational_provenance,
)
from axis_api.models import AuditEvent
from axis_api.object_storage import ObjectStore
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    ApprovalDecisionRecord,
    ApprovalRecordCreate,
    AxisPersistenceRepository,
    ConnectorEvidenceSnapshotExportMaterializationRecord,
    ConnectorEvidenceSnapshotExportRequestCreate,
    ConnectorEvidenceSnapshotExportRequestDecisionRecord,
)
from axis_api.workflow_runtime import (
    DeferredWorkflowSignalRuntime,
    WorkflowConnectorEvidenceSnapshotExportSignalRequest,
    WorkflowSignalError,
    WorkflowSignalResult,
    WorkflowSignalRuntime,
    workflow_connector_evidence_snapshot_export_signal_failure_result,
)

READ_AUDIT_EVENT_TYPE = "connector.evidence_invariants_read"
SNAPSHOT_AUDIT_EVENT_TYPE = "connector.evidence_invariants.snapshot_persisted"
SNAPSHOT_REQUIRED_SCOPE = "connectors:evidence:snapshot"
SNAPSHOT_EXPORT_AUDIT_EVENT_TYPE = "connector.evidence_invariant_snapshots_exported"
SNAPSHOT_EXPORT_REQUEST_AUDIT_EVENT_TYPE = "connector.evidence_snapshot_export.requested"
SNAPSHOT_EXPORT_REQUEST_DECISION_AUDIT_EVENT_TYPE = (
    "connector.evidence_snapshot_export.decision_recorded"
)
SNAPSHOT_EXPORT_REQUEST_DECISION_REQUIRED_SCOPE = "approvals:connectors:export:decide"
SNAPSHOT_EXPORT_REQUEST_MATERIALIZATION_AUDIT_EVENT_TYPE = (
    "connector.evidence_snapshot_export.materialized"
)
SNAPSHOT_EXPORT_REQUEST_MATERIALIZATION_REQUIRED_SCOPE = (
    "connectors:evidence:snapshot:export:materialize"
)
SNAPSHOT_EXPORT_REQUEST_REQUIRED_SCOPE = "connectors:evidence:snapshot:export:request"
SNAPSHOT_READ_AUDIT_EVENT_TYPE = "connector.evidence_invariant_snapshots_read"
SNAPSHOT_READ_REQUIRED_SCOPE = "connectors:evidence:snapshot:read"
REPORT_HASH_ALGORITHM = "sha256-canonical-json-v1"
SNAPSHOT_EXPORT_REQUEST_STATUS = "approval_required"
SNAPSHOT_EXPORT_REQUEST_EXPORT_STATUS = "not_exported"
SNAPSHOT_EXPORT_REQUEST_STORAGE_STATUS = "not_written"
SNAPSHOT_EXPORT_REQUEST_WORKFLOW_SIGNAL_STATUS = "pending_approval_decision"
SNAPSHOT_EXPORT_REQUEST_REDACTION_POLICY = "connector-snapshot-public-safe"
SNAPSHOT_EXPORT_REQUEST_MATERIALIZED_STATUS = "materialized"
SNAPSHOT_EXPORT_REQUEST_MATERIALIZED_STORAGE_STATUS = "written_local_object_store"


def _default_export_request_controls() -> list[str]:
    return [
        "approval_required",
        "workflow_signal_required",
        "idempotency_enforced",
        "public_safe_bundle_only",
    ]


class ConnectorEvidenceInvariantQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class ConnectorEvidenceInvariantItem(BaseModel):
    evidence_type: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    parent_id: str | None = None
    audit_event_id: str | None = None
    reason: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class ManufacturingConnectorEvidenceInvariantReport(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    invariant_counts: dict[str, int] = Field(default_factory=dict)
    invariants: list[ConnectorEvidenceInvariantItem] = Field(default_factory=list)
    report_notes: list[str] = Field(default_factory=list)


class ConnectorEvidenceInvariantSnapshotRequest(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    snapshot_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    connector_id: str | None = Field(default=None, min_length=1)
    requested_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=240)
    limit: int = Field(default=100, ge=1, le=200)
    notes: list[str] = Field(default_factory=list)


class ConnectorEvidenceInvariantSnapshotRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    connector_id: str | None = None
    requested_by: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    invariant_count: int = Field(ge=0)
    invariant_counts: dict[str, int] = Field(default_factory=dict)
    subject_ids: list[str] = Field(default_factory=list)
    report_digest_sha256: str = Field(min_length=64, max_length=64)
    report_hash_algorithm: str = Field(min_length=1)
    permission_decision: PermissionDecision
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    idempotent_replay: bool = False
    notes: list[str] = Field(default_factory=list)


class ConnectorEvidenceInvariantSnapshotQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    snapshot_id: str | None = Field(default=None, min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class ConnectorEvidenceInvariantSnapshotExportQuery(ConnectorEvidenceInvariantSnapshotQuery):
    export_reason: str = Field(default="connector-evidence-review", min_length=1, max_length=120)
    format: str = Field(default="json", pattern="^json$")


class ConnectorEvidenceInvariantSnapshotExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    export_request_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    idempotency_key: str = Field(min_length=1, max_length=200)
    requested_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    owner_role: str = Field(min_length=1, max_length=160)
    risk_level: str = Field(min_length=1, max_length=40)
    approval_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    connector_id: str | None = Field(default=None, min_length=1)
    snapshot_id: str | None = Field(default=None, min_length=1)
    snapshot_idempotency_key: str | None = Field(default=None, min_length=1)
    export_reason: str = Field(default="connector-evidence-review", min_length=1, max_length=120)
    format: str = Field(default="json", pattern="^json$")
    limit: int = Field(default=100, ge=1, le=200)
    controls: list[str] = Field(default_factory=_default_export_request_controls)
    notes: list[str] = Field(default_factory=list)


class ConnectorEvidenceInvariantSnapshotExportRequestFilter(BaseModel):
    connector_id: str | None = None
    snapshot_id: str | None = None
    idempotency_key: str | None = None
    limit: int = Field(ge=1)


class ConnectorEvidenceInvariantSnapshotExportRequestRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    export_request_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: str = Field(min_length=1)
    export_status: str = Field(min_length=1)
    storage_status: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    risk_level: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    snapshot_filter: ConnectorEvidenceInvariantSnapshotExportRequestFilter
    export_reason: str = Field(min_length=1)
    format: str = Field(min_length=1)
    requested_snapshot_count: int = Field(ge=0)
    snapshot_checksum_sha256: str = Field(min_length=64, max_length=64)
    redaction_policy: str = Field(min_length=1)
    controls: list[str] = Field(default_factory=list)
    permission_decision: PermissionDecision
    workflow_signal_status: str = Field(min_length=1)
    decision: str | None = None
    decision_actor_id: str | None = None
    decision_note: str | None = None
    decided_at: datetime | None = None
    workflow_signal: WorkflowSignalResult | None = None
    materialization_id: str | None = None
    materialization_idempotency_key: str | None = None
    materialized_by: str | None = None
    materialized_at: datetime | None = None
    materialization_reason: str | None = None
    storage_adapter: str | None = None
    storage_key: str | None = None
    storage_uri: str | None = None
    artifact_checksum_sha256: str | None = None
    artifact_size_bytes: int | None = None
    artifact_content_type: str | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime
    idempotent_replay: bool = False


class ConnectorEvidenceInvariantSnapshotHistory(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    history_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    snapshots: list[ConnectorEvidenceInvariantSnapshotRecord] = Field(default_factory=list)
    history_notes: list[str] = Field(default_factory=list)


class ConnectorEvidenceInvariantSnapshotExportManifest(BaseModel):
    export_id: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    format: str = Field(min_length=1)
    redaction_policy: str = Field(min_length=1)
    checksum_sha256: str = Field(min_length=64, max_length=64)
    integrity_chain_tip_sha256: str = Field(min_length=64, max_length=64)
    connector_id: str | None = None
    snapshot_id: str | None = None
    idempotency_key: str | None = None


class ConnectorEvidenceInvariantSnapshotIntegrityProof(BaseModel):
    algorithm: str = Field(min_length=1)
    verification_status: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    chain_tip_sha256: str = Field(min_length=64, max_length=64)
    snapshot_hashes: list[str] = Field(default_factory=list)


class ConnectorEvidenceInvariantSnapshotExportBundle(BaseModel):
    tenant_id: str = Field(min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    format: str = Field(min_length=1)
    export_reason: str = Field(min_length=1)
    filters: ConnectorEvidenceInvariantSnapshotQuery
    manifest: ConnectorEvidenceInvariantSnapshotExportManifest
    integrity_proof: ConnectorEvidenceInvariantSnapshotIntegrityProof
    ledger_signature: AuditLedgerSignatureProof
    snapshots: list[ConnectorEvidenceInvariantSnapshotRecord] = Field(default_factory=list)
    export_notes: list[str] = Field(default_factory=list)


class ConnectorEvidenceInvariantSnapshotExportDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ApprovalDecision
    actor_id: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=600)


class ConnectorEvidenceInvariantSnapshotExportDecisionResult(BaseModel):
    tenant_id: str = Field(min_length=1)
    export_request_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    decision: ApprovalDecision
    status: str = Field(min_length=1)
    export_status: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    export_request: ConnectorEvidenceInvariantSnapshotExportRequestRecord
    permission_decision: PermissionDecision
    audit_event_id: UUID
    audit_event_type: str = Field(min_length=1)
    workflow_signal: WorkflowSignalResult
    workflow_signal_status: str = Field(min_length=1)


class ConnectorEvidenceInvariantSnapshotExportMaterializationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    materialization_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    idempotency_key: str = Field(min_length=1, max_length=200)
    actor_id: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=240)


class ConnectorEvidenceInvariantSnapshotExportMaterializationResult(BaseModel):
    tenant_id: str = Field(min_length=1)
    export_request_id: str = Field(min_length=1)
    materialization_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: str = Field(min_length=1)
    export_status: str = Field(min_length=1)
    storage_status: str = Field(min_length=1)
    storage_adapter: str = Field(min_length=1)
    storage_key: str = Field(min_length=1)
    storage_uri: str = Field(min_length=1)
    artifact_checksum_sha256: str = Field(min_length=64, max_length=64)
    artifact_size_bytes: int = Field(ge=0)
    artifact_content_type: str = Field(min_length=1)
    export_request: ConnectorEvidenceInvariantSnapshotExportRequestRecord
    permission_decision: PermissionDecision
    audit_event_id: UUID
    audit_event_type: str = Field(min_length=1)
    idempotent_replay: bool = False


class ConnectorEvidenceInvariantSnapshotPermissionDenied(PermissionError):
    def __init__(self, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class ConnectorEvidenceInvariantSnapshotConflict(ValueError):
    def __init__(self, snapshot_id: str, reason: str) -> None:
        super().__init__(reason)
        self.snapshot_id = snapshot_id
        self.reason = reason


class ConnectorEvidenceInvariantSnapshotExportRequestConflict(ValueError):
    def __init__(self, export_request_id: str, reason: str) -> None:
        super().__init__(reason)
        self.export_request_id = export_request_id
        self.reason = reason


class ConnectorEvidenceInvariantSnapshotExportRequestNotFound(LookupError):
    pass


class ConnectorEvidenceInvariantSnapshotExportMaterializationConflict(ValueError):
    def __init__(self, export_request_id: str, reason: str) -> None:
        super().__init__(reason)
        self.export_request_id = export_request_id
        self.reason = reason


class ConnectorEvidenceInvariantSnapshotExportDecisionPermissionDenied(PermissionError):
    def __init__(self, required_permission: str, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permission = required_permission
        self.decision = decision


class ConnectorEvidenceInvariantSnapshotExportMaterializationPermissionDenied(PermissionError):
    def __init__(self, required_permission: str, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permission = required_permission
        self.decision = decision


def build_connector_evidence_invariant_report(
    repository: AxisPersistenceRepository,
    query: ConnectorEvidenceInvariantQuery,
) -> ManufacturingConnectorEvidenceInvariantReport:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, query.tenant_id)
    checkpoints = build_connector_sync_checkpoint_registry(
        repository,
        ConnectorSyncCheckpointQuery(
            tenant_id=query.tenant_id,
            connector_id=query.connector_id,
            limit=query.limit,
        ),
    )
    claims = build_connector_sync_checkpoint_claim_registry(
        repository,
        ConnectorSyncCheckpointClaimQuery(
            tenant_id=query.tenant_id,
            connector_id=query.connector_id,
            limit=query.limit,
        ),
    )
    leases = build_connector_credential_lease_registry(
        repository,
        ConnectorCredentialLeaseQuery(
            tenant_id=query.tenant_id,
            connector_id=query.connector_id,
            limit=query.limit,
        ),
    )
    policies = build_connector_egress_policy_registry(
        repository,
        ConnectorEgressPolicyQuery(
            tenant_id=query.tenant_id,
            connector_id=query.connector_id,
            limit=query.limit,
        ),
    )
    invariants = (
        [
            ConnectorEvidenceInvariantItem(
                evidence_type="checkpoint",
                subject_id=invariant.checkpoint_id,
                parent_id=_checkpoint_parent_id(checkpoints, invariant.checkpoint_id),
                audit_event_id=invariant.audit_event_id,
                reason=invariant.reason,
                detail=invariant.detail,
            )
            for invariant in checkpoints.evidence_invariants
        ]
        + [
            ConnectorEvidenceInvariantItem(
                evidence_type="checkpoint_claim",
                subject_id=invariant.claim_id,
                parent_id=invariant.checkpoint_id,
                audit_event_id=invariant.audit_event_id,
                reason=invariant.reason,
                detail=invariant.detail,
            )
            for invariant in claims.claim_evidence_invariants
        ]
        + [
            ConnectorEvidenceInvariantItem(
                evidence_type="credential_lease",
                subject_id=invariant.lease_id,
                parent_id=_lease_parent_id(leases, invariant.lease_id),
                audit_event_id=invariant.audit_event_id,
                reason=invariant.reason,
                detail=invariant.detail,
            )
            for invariant in leases.lease_evidence_invariants
        ]
        + [
            ConnectorEvidenceInvariantItem(
                evidence_type="egress_policy",
                subject_id=invariant.policy_id,
                parent_id=_policy_parent_id(policies, invariant.policy_id),
                audit_event_id=invariant.audit_event_id,
                reason=invariant.reason,
                detail=invariant.detail,
            )
            for invariant in policies.policy_evidence_invariants
        ]
    )
    counts = {
        "checkpoint": len(checkpoints.evidence_invariants),
        "checkpoint_claim": len(claims.claim_evidence_invariants),
        "credential_lease": len(leases.lease_evidence_invariants),
        "egress_policy": len(policies.policy_evidence_invariants),
    }
    return ManufacturingConnectorEvidenceInvariantReport(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(
            bool(checkpoints.checkpoints or claims.claims or leases.leases or policies.policies)
        ),
        registry_status=OverviewStatus.WATCH if invariants else OverviewStatus.READY,
        metrics=[
            OverviewMetric(
                label="Evidence Invariants",
                value=str(len(invariants)),
                detail=(
                    "Public-safe connector evidence issues across checkpoints, "
                    "claims, leases and policies"
                ),
                status=OverviewStatus.WATCH if invariants else OverviewStatus.READY,
            ),
            OverviewMetric(
                label="Evidence Surfaces",
                value=str(sum(1 for count in counts.values() if count > 0)),
                detail="Connector evidence surfaces with at least one invariant",
                status=OverviewStatus.WATCH if invariants else OverviewStatus.READY,
            ),
        ],
        invariant_counts=counts,
        invariants=invariants,
        report_notes=[
            "Aggregated report composes persisted connector evidence registries.",
            "Report reads are audit-backed and exclude secret refs, DSNs and endpoint refs.",
        ],
    )


def persist_connector_evidence_invariant_snapshot(
    repository: AxisPersistenceRepository,
    request: ConnectorEvidenceInvariantSnapshotRequest,
) -> ConnectorEvidenceInvariantSnapshotRecord:
    permission_decision = _evaluate_snapshot_permission(request)
    existing_replay = _find_snapshot_by_idempotency_key(repository, request)
    if existing_replay is not None:
        if (
            existing_replay.payload.get("snapshot_id") != request.snapshot_id
            or existing_replay.payload.get("connector_id") != request.connector_id
        ):
            raise ConnectorEvidenceInvariantSnapshotConflict(
                str(existing_replay.payload.get("snapshot_id") or request.snapshot_id),
                "idempotency_conflict",
            )
        return _snapshot_record_from_audit_event(existing_replay, idempotent_replay=True)

    existing_snapshot = _find_snapshot_by_id(repository, request)
    if existing_snapshot is not None:
        raise ConnectorEvidenceInvariantSnapshotConflict(
            request.snapshot_id,
            "snapshot_id_already_exists",
        )

    report = build_connector_evidence_invariant_report(
        repository,
        ConnectorEvidenceInvariantQuery(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
            limit=request.limit,
        ),
    )
    subject_ids = [invariant.subject_id for invariant in report.invariants]
    report_payload = _snapshot_report_payload(report)
    report_digest = _canonical_sha256(report_payload)
    audit_payload = {
        "snapshot_id": request.snapshot_id,
        "connector_id": request.connector_id,
        "idempotency_key": request.idempotency_key,
        "reason": request.reason,
        "required_scope": SNAPSHOT_REQUIRED_SCOPE,
        "permission_decision": permission_decision.model_dump(),
        "invariant_count": len(report.invariants),
        "invariant_counts": report.invariant_counts,
        "subject_ids": subject_ids,
        "report_digest_sha256": report_digest,
        "report_hash_algorithm": REPORT_HASH_ALGORITHM,
        "report_reason_ids": [invariant.reason for invariant in report.invariants],
        "notes": request.notes,
    }
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type=SNAPSHOT_AUDIT_EVENT_TYPE,
            payload=audit_payload,
        )
    )
    return _snapshot_record_from_audit_event(audit_event)


def read_connector_evidence_invariant_snapshot_history(
    repository: AxisPersistenceRepository,
    query: ConnectorEvidenceInvariantSnapshotQuery,
    *,
    actor_id: str,
    actor_scopes: list[str],
) -> ConnectorEvidenceInvariantSnapshotHistory:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, query.tenant_id)
    _evaluate_snapshot_history_permission(query, actor_id, actor_scopes)
    snapshots = _snapshot_records_for_query(repository, query)
    snapshot_ids = [snapshot.snapshot_id for snapshot in snapshots]
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=query.tenant_id,
            actor_id=actor_id,
            event_type=SNAPSHOT_READ_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": query.connector_id,
                "snapshot_id": query.snapshot_id,
                "idempotency_key": query.idempotency_key,
                "limit": query.limit,
                "returned_snapshot_count": len(snapshots),
                "snapshot_ids": snapshot_ids,
            },
        )
    )
    return ConnectorEvidenceInvariantSnapshotHistory(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(bool(snapshots)),
        history_status=OverviewStatus.READY if snapshots else OverviewStatus.WATCH,
        metrics=[
            OverviewMetric(
                label="Evidence Snapshots",
                value=str(len(snapshots)),
                detail="Persisted connector evidence snapshot audit artifacts",
                status=OverviewStatus.READY if snapshots else OverviewStatus.WATCH,
            )
        ],
        snapshots=snapshots,
        history_notes=[
            "Snapshot history is read from append-only audit events.",
            "History reads return public-safe snapshot metadata only.",
        ],
    )


def export_connector_evidence_invariant_snapshots(
    repository: AxisPersistenceRepository,
    query: ConnectorEvidenceInvariantSnapshotExportQuery,
    *,
    actor_id: str,
    actor_scopes: list[str],
    ledger_signer: AuditLedgerSigner | None = None,
) -> ConnectorEvidenceInvariantSnapshotExportBundle:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, query.tenant_id)
    _evaluate_snapshot_history_permission(query, actor_id, actor_scopes)
    snapshots = _snapshot_records_for_query(repository, query)
    bundle = _snapshot_export_bundle_for_records(
        query,
        snapshots,
        scenario=tenant_metadata.scenario,
        ledger_signer=ledger_signer,
    )
    snapshot_ids = [snapshot.snapshot_id for snapshot in snapshots]
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=query.tenant_id,
            actor_id=actor_id,
            event_type=SNAPSHOT_EXPORT_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": query.connector_id,
                "snapshot_id": query.snapshot_id,
                "idempotency_key": query.idempotency_key,
                "limit": query.limit,
                "export_reason": query.export_reason,
                "export_id": bundle.manifest.export_id,
                "checksum_sha256": bundle.manifest.checksum_sha256,
                "signature_status": bundle.ledger_signature.verification_status,
                "exported_snapshot_count": len(snapshots),
                "snapshot_ids": snapshot_ids,
            },
        )
    )
    return bundle


def record_connector_evidence_invariant_snapshot_export_request(
    repository: AxisPersistenceRepository,
    request: ConnectorEvidenceInvariantSnapshotExportRequest,
) -> ConnectorEvidenceInvariantSnapshotExportRequestRecord:
    permission_decision = _evaluate_snapshot_export_request_permission(request)
    existing_replay = (
        repository.get_connector_evidence_snapshot_export_request_by_idempotency_key(
            request.tenant_id,
            request.idempotency_key,
        )
    )
    if existing_replay is not None:
        if _export_request_fingerprint_from_record(
            existing_replay
        ) != _export_request_fingerprint_from_request(request):
            raise ConnectorEvidenceInvariantSnapshotExportRequestConflict(
                existing_replay.export_request_id,
                "idempotency_conflict",
            )
        return _snapshot_export_request_from_record(existing_replay, idempotent_replay=True)

    existing_request = repository.get_connector_evidence_snapshot_export_request(
        request.tenant_id,
        request.export_request_id,
    )
    if existing_request is not None:
        raise ConnectorEvidenceInvariantSnapshotExportRequestConflict(
            request.export_request_id,
            "export_request_id_already_exists",
        )

    query = ConnectorEvidenceInvariantSnapshotQuery(
        tenant_id=request.tenant_id,
        connector_id=request.connector_id,
        snapshot_id=request.snapshot_id,
        idempotency_key=request.snapshot_idempotency_key,
        limit=request.limit,
    )
    snapshots = _snapshot_records_for_query(repository, query)
    checksum = _snapshots_checksum(snapshots)
    snapshot_ids = [snapshot.snapshot_id for snapshot in snapshots]
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type=SNAPSHOT_EXPORT_REQUEST_AUDIT_EVENT_TYPE,
            payload={
                "export_request_id": request.export_request_id,
                "idempotency_key": request.idempotency_key,
                "connector_id": request.connector_id,
                "snapshot_id": request.snapshot_id,
                "snapshot_idempotency_key": request.snapshot_idempotency_key,
                "limit": request.limit,
                "export_reason": request.export_reason,
                "format": request.format,
                "status": SNAPSHOT_EXPORT_REQUEST_STATUS,
                "export_status": SNAPSHOT_EXPORT_REQUEST_EXPORT_STATUS,
                "storage_status": SNAPSHOT_EXPORT_REQUEST_STORAGE_STATUS,
                "approval_id": request.approval_id,
                "workflow_id": request.workflow_id,
                "owner_role": request.owner_role,
                "risk_level": request.risk_level,
                "required_scope": SNAPSHOT_EXPORT_REQUEST_REQUIRED_SCOPE,
                "permission_decision": permission_decision.model_dump(),
                "requested_snapshot_count": len(snapshots),
                "snapshot_checksum_sha256": checksum,
                "snapshot_ids": snapshot_ids,
                "redaction_policy": SNAPSHOT_EXPORT_REQUEST_REDACTION_POLICY,
                "controls": request.controls,
                "workflow_signal_status": SNAPSHOT_EXPORT_REQUEST_WORKFLOW_SIGNAL_STATUS,
            },
        )
    )
    _ensure_export_request_approval_record(
        repository,
        request,
        requested_snapshot_count=len(snapshots),
        snapshot_checksum_sha256=checksum,
    )
    record = repository.create_connector_evidence_snapshot_export_request(
        ConnectorEvidenceSnapshotExportRequestCreate(
            tenant_id=request.tenant_id,
            export_request_id=request.export_request_id,
            idempotency_key=request.idempotency_key,
            status=SNAPSHOT_EXPORT_REQUEST_STATUS,
            export_status=SNAPSHOT_EXPORT_REQUEST_EXPORT_STATUS,
            storage_status=SNAPSHOT_EXPORT_REQUEST_STORAGE_STATUS,
            requested_by=request.requested_by,
            owner_role=request.owner_role,
            risk_level=request.risk_level,
            approval_id=request.approval_id,
            workflow_id=request.workflow_id,
            connector_id=request.connector_id,
            snapshot_id=request.snapshot_id,
            snapshot_idempotency_key=request.snapshot_idempotency_key,
            export_reason=request.export_reason,
            format=request.format,
            limit=request.limit,
            requested_snapshot_count=len(snapshots),
            snapshot_checksum_sha256=checksum,
            redaction_policy=SNAPSHOT_EXPORT_REQUEST_REDACTION_POLICY,
            controls=request.controls,
            permission_decision=permission_decision.model_dump(),
            workflow_signal_status=SNAPSHOT_EXPORT_REQUEST_WORKFLOW_SIGNAL_STATUS,
            audit_event_id=audit_event.id,
            audit_event_type=SNAPSHOT_EXPORT_REQUEST_AUDIT_EVENT_TYPE,
            notes=request.notes,
        )
    )
    return _snapshot_export_request_from_record(record)


async def record_connector_evidence_invariant_snapshot_export_request_decision(
    repository: AxisPersistenceRepository,
    export_request_id: str,
    request: ConnectorEvidenceInvariantSnapshotExportDecisionRequest,
    workflow_runtime: WorkflowSignalRuntime | None = None,
    tenant_id: str = "tenant_demo_manufacturing",
) -> ConnectorEvidenceInvariantSnapshotExportDecisionResult:
    export_request = repository.get_connector_evidence_snapshot_export_request(
        tenant_id,
        export_request_id,
    )
    if export_request is None:
        raise ConnectorEvidenceInvariantSnapshotExportRequestNotFound(
            "Connector evidence snapshot export request not found"
        )

    permission_decision = _evaluate_snapshot_export_request_decision_permission(
        export_request,
        request,
    )
    _ensure_export_request_approval_record_from_record(repository, export_request)
    repository.record_approval_decision(
        ApprovalDecisionRecord(
            tenant_id=export_request.tenant_id,
            approval_id=export_request.approval_id,
            decision=request.decision.value,
            decision_actor_id=request.actor_id,
            decision_note=request.note,
        )
    )
    status = _export_request_status_for_decision(request.decision)
    export_status = _export_status_for_decision(request.decision)
    runtime = workflow_runtime or DeferredWorkflowSignalRuntime()
    workflow_signal = await _signal_snapshot_export_workflow(
        runtime,
        export_request,
        request,
        export_status=export_status,
    )
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=export_request.tenant_id,
            actor_id=request.actor_id,
            event_type=SNAPSHOT_EXPORT_REQUEST_DECISION_AUDIT_EVENT_TYPE,
            payload={
                "export_request_id": export_request.export_request_id,
                "idempotency_key": export_request.idempotency_key,
                "connector_id": export_request.connector_id,
                "snapshot_id": export_request.snapshot_id,
                "snapshot_idempotency_key": export_request.snapshot_idempotency_key,
                "approval_id": export_request.approval_id,
                "workflow_id": export_request.workflow_id,
                "decision": request.decision.value,
                "status": status,
                "export_status": export_status,
                "storage_status": export_request.storage_status,
                "required_permission": SNAPSHOT_EXPORT_REQUEST_DECISION_REQUIRED_SCOPE,
                "permission_decision": permission_decision.model_dump(),
                "requested_snapshot_count": export_request.requested_snapshot_count,
                "snapshot_checksum_sha256": export_request.snapshot_checksum_sha256,
                "redaction_policy": export_request.redaction_policy,
                "workflow_signal": workflow_signal.model_dump(),
                "decision_note_recorded": str(request.note is not None).lower(),
            },
        )
    )
    updated_export_request = (
        repository.record_connector_evidence_snapshot_export_request_decision(
            ConnectorEvidenceSnapshotExportRequestDecisionRecord(
                tenant_id=export_request.tenant_id,
                export_request_id=export_request.export_request_id,
                status=status,
                export_status=export_status,
                decision=request.decision.value,
                decision_actor_id=request.actor_id,
                decision_note=request.note,
                workflow_signal_status=workflow_signal.status,
                workflow_signal=workflow_signal.model_dump(),
                audit_event_id=audit_event.id,
                audit_event_type=SNAPSHOT_EXPORT_REQUEST_DECISION_AUDIT_EVENT_TYPE,
            )
        )
    )

    return ConnectorEvidenceInvariantSnapshotExportDecisionResult(
        tenant_id=export_request.tenant_id,
        export_request_id=export_request.export_request_id,
        approval_id=export_request.approval_id,
        workflow_id=export_request.workflow_id,
        decision=request.decision,
        status=status,
        export_status=export_status,
        actor_id=request.actor_id,
        export_request=_snapshot_export_request_from_record(updated_export_request),
        permission_decision=permission_decision,
        audit_event_id=audit_event.id,
        audit_event_type=audit_event.event_type,
        workflow_signal=workflow_signal,
        workflow_signal_status=workflow_signal.status,
    )


def materialize_connector_evidence_invariant_snapshot_export_request(
    repository: AxisPersistenceRepository,
    export_request_id: str,
    request: ConnectorEvidenceInvariantSnapshotExportMaterializationRequest,
    object_store: ObjectStore,
    ledger_signer: AuditLedgerSigner | None = None,
    tenant_id: str = "tenant_demo_manufacturing",
) -> ConnectorEvidenceInvariantSnapshotExportMaterializationResult:
    export_request = repository.get_connector_evidence_snapshot_export_request(
        tenant_id,
        export_request_id,
    )
    if export_request is None:
        raise ConnectorEvidenceInvariantSnapshotExportRequestNotFound(
            "Connector evidence snapshot export request not found"
        )

    permission_decision = _evaluate_snapshot_export_request_materialization_permission(
        export_request,
        request,
    )
    existing_materialization = _existing_materialization_result(
        export_request,
        request,
        permission_decision,
    )
    if existing_materialization is not None:
        return existing_materialization
    _ensure_export_request_can_materialize(export_request)

    query = ConnectorEvidenceInvariantSnapshotExportQuery(
        tenant_id=export_request.tenant_id,
        connector_id=export_request.connector_id,
        snapshot_id=export_request.snapshot_id,
        idempotency_key=export_request.snapshot_idempotency_key,
        limit=export_request.limit,
        export_reason=export_request.export_reason,
        format=export_request.format,
    )
    snapshots = _snapshot_records_for_query(repository, query)
    checksum = _snapshots_checksum(snapshots)
    if checksum != export_request.snapshot_checksum_sha256:
        raise ConnectorEvidenceInvariantSnapshotExportMaterializationConflict(
            export_request.export_request_id,
            "snapshot_checksum_changed",
        )
    bundle = _snapshot_export_bundle_for_records(
        query,
        snapshots,
        scenario=find_manufacturing_tenant_metadata(
            repository, query.tenant_id
        ).scenario,
        ledger_signer=ledger_signer,
    )
    artifact_payload = bundle.model_dump(mode="json")
    storage_key = _materialization_storage_key(export_request, request)
    stored_object = object_store.put_json(storage_key, artifact_payload)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=export_request.tenant_id,
            actor_id=request.actor_id,
            event_type=SNAPSHOT_EXPORT_REQUEST_MATERIALIZATION_AUDIT_EVENT_TYPE,
            payload={
                "export_request_id": export_request.export_request_id,
                "materialization_id": request.materialization_id,
                "idempotency_key": request.idempotency_key,
                "connector_id": export_request.connector_id,
                "snapshot_id": export_request.snapshot_id,
                "approval_id": export_request.approval_id,
                "workflow_id": export_request.workflow_id,
                "decision": export_request.decision,
                "export_status": SNAPSHOT_EXPORT_REQUEST_MATERIALIZED_STATUS,
                "storage_status": SNAPSHOT_EXPORT_REQUEST_MATERIALIZED_STORAGE_STATUS,
                "storage_adapter": stored_object.storage_adapter,
                "storage_key": stored_object.storage_key,
                "storage_uri": stored_object.storage_uri,
                "artifact_checksum_sha256": stored_object.checksum_sha256,
                "artifact_size_bytes": stored_object.size_bytes,
                "artifact_content_type": stored_object.content_type,
                "requested_snapshot_count": export_request.requested_snapshot_count,
                "redaction_policy": export_request.redaction_policy,
                "required_permission": SNAPSHOT_EXPORT_REQUEST_MATERIALIZATION_REQUIRED_SCOPE,
                "permission_decision": permission_decision.model_dump(),
            },
        )
    )
    updated_export_request = repository.record_connector_evidence_snapshot_export_materialization(
        ConnectorEvidenceSnapshotExportMaterializationRecord(
            tenant_id=export_request.tenant_id,
            export_request_id=export_request.export_request_id,
            status=SNAPSHOT_EXPORT_REQUEST_MATERIALIZED_STATUS,
            export_status=SNAPSHOT_EXPORT_REQUEST_MATERIALIZED_STATUS,
            storage_status=SNAPSHOT_EXPORT_REQUEST_MATERIALIZED_STORAGE_STATUS,
            materialization_id=request.materialization_id,
            materialization_idempotency_key=request.idempotency_key,
            materialized_by=request.actor_id,
            materialization_reason=request.reason,
            storage_adapter=stored_object.storage_adapter,
            storage_key=stored_object.storage_key,
            storage_uri=stored_object.storage_uri,
            artifact_checksum_sha256=stored_object.checksum_sha256,
            artifact_size_bytes=stored_object.size_bytes,
            artifact_content_type=stored_object.content_type,
            audit_event_id=audit_event.id,
            audit_event_type=SNAPSHOT_EXPORT_REQUEST_MATERIALIZATION_AUDIT_EVENT_TYPE,
        )
    )
    return _materialization_result_from_record(
        updated_export_request,
        permission_decision,
    )


def read_connector_evidence_invariant_report(
    repository: AxisPersistenceRepository,
    query: ConnectorEvidenceInvariantQuery,
    *,
    actor_id: str,
) -> ManufacturingConnectorEvidenceInvariantReport:
    report = build_connector_evidence_invariant_report(repository, query)
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=query.tenant_id,
            actor_id=actor_id,
            event_type=READ_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": query.connector_id,
                "limit": query.limit,
                "returned_invariant_count": len(report.invariants),
                "invariant_counts": report.invariant_counts,
                "subject_ids": [invariant.subject_id for invariant in report.invariants],
            },
        )
    )
    return report


def _snapshots_checksum(snapshots: list[ConnectorEvidenceInvariantSnapshotRecord]) -> str:
    encoded_snapshots = json.dumps(
        [snapshot.model_dump(mode="json") for snapshot in snapshots],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded_snapshots.encode("utf-8")).hexdigest()


def _snapshot_export_bundle_for_records(
    query: ConnectorEvidenceInvariantSnapshotExportQuery,
    snapshots: list[ConnectorEvidenceInvariantSnapshotRecord],
    *,
    scenario: str | None,
    ledger_signer: AuditLedgerSigner | None,
) -> ConnectorEvidenceInvariantSnapshotExportBundle:
    checksum = _snapshots_checksum(snapshots)
    integrity_proof = _snapshot_integrity_proof(snapshots)
    manifest = ConnectorEvidenceInvariantSnapshotExportManifest(
        export_id=f"connector-evidence-snapshot-export-{checksum[:16]}",
        generated_at=datetime.now(UTC).isoformat(),
        tenant_id=query.tenant_id,
        record_count=len(snapshots),
        format=query.format,
        redaction_policy="connector-snapshot-public-safe",
        checksum_sha256=checksum,
        integrity_chain_tip_sha256=integrity_proof.chain_tip_sha256,
        connector_id=query.connector_id,
        snapshot_id=query.snapshot_id,
        idempotency_key=query.idempotency_key,
    )
    signature_payload = canonical_ledger_signature_payload(manifest, integrity_proof)
    ledger_signature = (
        ledger_signer.sign_payload(signature_payload)
        if ledger_signer is not None
        else unsigned_audit_ledger_signature(signature_payload)
    )
    return ConnectorEvidenceInvariantSnapshotExportBundle(
        tenant_id=query.tenant_id,
        scenario=scenario,
        provenance=operational_provenance(bool(snapshots)),
        format=query.format,
        export_reason=query.export_reason,
        filters=ConnectorEvidenceInvariantSnapshotQuery(
            tenant_id=query.tenant_id,
            connector_id=query.connector_id,
            snapshot_id=query.snapshot_id,
            idempotency_key=query.idempotency_key,
            limit=query.limit,
        ),
        manifest=manifest,
        integrity_proof=integrity_proof,
        ledger_signature=ledger_signature,
        snapshots=snapshots,
        export_notes=[
            "Snapshot export bundle is tenant-scoped before optional filters are applied.",
            "Snapshots include public-safe invariant counts, subject ids and report digests only.",
            "Manifest checksum covers exported connector evidence snapshot metadata.",
            "Integrity proof links exported snapshots with a deterministic SHA-256 hash chain.",
        ],
    )


def _snapshot_integrity_proof(
    snapshots: list[ConnectorEvidenceInvariantSnapshotRecord],
) -> ConnectorEvidenceInvariantSnapshotIntegrityProof:
    snapshot_hashes: list[str] = []
    chain_tip = "0" * 64
    for snapshot in snapshots:
        encoded_snapshot = json.dumps(
            snapshot.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        snapshot_hash = hashlib.sha256(encoded_snapshot.encode("utf-8")).hexdigest()
        chain_tip = hashlib.sha256(f"{chain_tip}:{snapshot_hash}".encode()).hexdigest()
        snapshot_hashes.append(snapshot_hash)

    return ConnectorEvidenceInvariantSnapshotIntegrityProof(
        algorithm="sha256-hash-chain-v1",
        verification_status="verified",
        record_count=len(snapshots),
        chain_tip_sha256=chain_tip,
        snapshot_hashes=snapshot_hashes,
    )


def _evaluate_snapshot_export_request_permission(
    request: ConnectorEvidenceInvariantSnapshotExportRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            actor_scopes=request.actor_scopes,
            required_scopes=[SNAPSHOT_EXPORT_REQUEST_REQUIRED_SCOPE],
            attributes={
                "connector_id": request.connector_id,
                "snapshot_id": request.snapshot_id,
                "approval_id": request.approval_id,
                "workflow_id": request.workflow_id,
                "risk_level": request.risk_level,
                "export_reason": request.export_reason,
                "storage_status": SNAPSHOT_EXPORT_REQUEST_STORAGE_STATUS,
            },
        )
    )
    if not decision.allowed:
        raise ConnectorEvidenceInvariantSnapshotPermissionDenied(decision)
    return decision


def _evaluate_snapshot_export_request_decision_permission(
    export_request,
    request: ConnectorEvidenceInvariantSnapshotExportDecisionRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=export_request.tenant_id,
            actor_id=request.actor_id,
            actor_scopes=request.actor_scopes,
            required_scopes=[SNAPSHOT_EXPORT_REQUEST_DECISION_REQUIRED_SCOPE],
            attributes={
                "connector_id": export_request.connector_id,
                "snapshot_id": export_request.snapshot_id,
                "export_request_id": export_request.export_request_id,
                "approval_id": export_request.approval_id,
                "workflow_id": export_request.workflow_id,
                "risk_level": export_request.risk_level,
                "decision": request.decision.value,
                "storage_status": export_request.storage_status,
            },
        )
    )
    if not decision.allowed:
        raise ConnectorEvidenceInvariantSnapshotExportDecisionPermissionDenied(
            SNAPSHOT_EXPORT_REQUEST_DECISION_REQUIRED_SCOPE,
            decision,
        )
    return decision


def _evaluate_snapshot_export_request_materialization_permission(
    export_request,
    request: ConnectorEvidenceInvariantSnapshotExportMaterializationRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=export_request.tenant_id,
            actor_id=request.actor_id,
            actor_scopes=request.actor_scopes,
            required_scopes=[SNAPSHOT_EXPORT_REQUEST_MATERIALIZATION_REQUIRED_SCOPE],
            attributes={
                "connector_id": export_request.connector_id,
                "snapshot_id": export_request.snapshot_id,
                "export_request_id": export_request.export_request_id,
                "approval_id": export_request.approval_id,
                "workflow_id": export_request.workflow_id,
                "decision": export_request.decision,
                "storage_status": export_request.storage_status,
                "materialization_id": request.materialization_id,
            },
        )
    )
    if not decision.allowed:
        raise ConnectorEvidenceInvariantSnapshotExportMaterializationPermissionDenied(
            SNAPSHOT_EXPORT_REQUEST_MATERIALIZATION_REQUIRED_SCOPE,
            decision,
        )
    return decision


def _evaluate_snapshot_history_permission(
    query: ConnectorEvidenceInvariantSnapshotQuery,
    actor_id: str,
    actor_scopes: list[str],
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=query.tenant_id,
            actor_id=actor_id,
            actor_scopes=actor_scopes,
            required_scopes=[SNAPSHOT_READ_REQUIRED_SCOPE],
            attributes={
                "connector_id": query.connector_id,
                "snapshot_id": query.snapshot_id,
                "idempotency_key": query.idempotency_key,
            },
        )
    )
    if not decision.allowed:
        raise ConnectorEvidenceInvariantSnapshotPermissionDenied(decision)
    return decision


def _ensure_export_request_approval_record(
    repository: AxisPersistenceRepository,
    request: ConnectorEvidenceInvariantSnapshotExportRequest,
    *,
    requested_snapshot_count: int,
    snapshot_checksum_sha256: str,
) -> None:
    existing = repository.get_approval_record(request.tenant_id, request.approval_id)
    if existing is not None:
        return
    action_connector = request.connector_id or "tenant"
    repository.create_approval_record(
        ApprovalRecordCreate(
            tenant_id=request.tenant_id,
            approval_id=request.approval_id,
            workflow_id=request.workflow_id,
            action_id=f"connector_evidence_snapshot_export:{action_connector}",
            requested_by=request.requested_by,
            owner_role=request.owner_role,
            risk_level=request.risk_level,
            payload={
                "export_request_id": request.export_request_id,
                "idempotency_key": request.idempotency_key,
                "connector_id": request.connector_id,
                "snapshot_id": request.snapshot_id,
                "snapshot_idempotency_key": request.snapshot_idempotency_key,
                "export_reason": request.export_reason,
                "format": request.format,
                "limit": request.limit,
                "required_permission": SNAPSHOT_EXPORT_REQUEST_REQUIRED_SCOPE,
                "requested_snapshot_count": requested_snapshot_count,
                "snapshot_checksum_sha256": snapshot_checksum_sha256,
                "redaction_policy": SNAPSHOT_EXPORT_REQUEST_REDACTION_POLICY,
                "storage_status": SNAPSHOT_EXPORT_REQUEST_STORAGE_STATUS,
            },
        )
    )


def _ensure_export_request_approval_record_from_record(
    repository: AxisPersistenceRepository,
    export_request,
) -> None:
    existing = repository.get_approval_record(
        export_request.tenant_id,
        export_request.approval_id,
    )
    if existing is not None:
        return
    action_connector = export_request.connector_id or "tenant"
    repository.create_approval_record(
        ApprovalRecordCreate(
            tenant_id=export_request.tenant_id,
            approval_id=export_request.approval_id,
            workflow_id=export_request.workflow_id,
            action_id=f"connector_evidence_snapshot_export:{action_connector}",
            requested_by=export_request.requested_by,
            owner_role=export_request.owner_role,
            risk_level=export_request.risk_level,
            payload={
                "export_request_id": export_request.export_request_id,
                "idempotency_key": export_request.idempotency_key,
                "connector_id": export_request.connector_id,
                "snapshot_id": export_request.snapshot_id,
                "snapshot_idempotency_key": export_request.snapshot_idempotency_key,
                "export_reason": export_request.export_reason,
                "format": export_request.format,
                "limit": export_request.limit,
                "required_permission": SNAPSHOT_EXPORT_REQUEST_REQUIRED_SCOPE,
                "requested_snapshot_count": export_request.requested_snapshot_count,
                "snapshot_checksum_sha256": export_request.snapshot_checksum_sha256,
                "redaction_policy": export_request.redaction_policy,
                "storage_status": export_request.storage_status,
            },
        )
    )


def _ensure_export_request_can_materialize(export_request) -> None:
    if (
        export_request.status != "approval_approved"
        or export_request.export_status != "approved_not_exported"
        or export_request.decision != ApprovalDecision.APPROVE.value
    ):
        raise ConnectorEvidenceInvariantSnapshotExportMaterializationConflict(
            export_request.export_request_id,
            "export_request_not_approved",
        )
    if export_request.storage_status != SNAPSHOT_EXPORT_REQUEST_STORAGE_STATUS:
        raise ConnectorEvidenceInvariantSnapshotExportMaterializationConflict(
            export_request.export_request_id,
            "export_request_already_materialized",
        )


def _existing_materialization_result(
    export_request,
    request: ConnectorEvidenceInvariantSnapshotExportMaterializationRequest,
    permission_decision: PermissionDecision,
) -> ConnectorEvidenceInvariantSnapshotExportMaterializationResult | None:
    if export_request.materialization_id is None:
        return None
    if (
        export_request.materialization_id == request.materialization_id
        and export_request.materialization_idempotency_key == request.idempotency_key
    ):
        return _materialization_result_from_record(
            export_request,
            permission_decision,
            idempotent_replay=True,
        )
    raise ConnectorEvidenceInvariantSnapshotExportMaterializationConflict(
        export_request.export_request_id,
        "materialization_idempotency_conflict",
    )


def _materialization_storage_key(
    export_request,
    request: ConnectorEvidenceInvariantSnapshotExportMaterializationRequest,
) -> str:
    return (
        f"{export_request.tenant_id}/connector-evidence-snapshot-exports/"
        f"{export_request.export_request_id}/{request.materialization_id}.json"
    )


def _snapshot_export_request_from_record(
    record,
    idempotent_replay: bool = False,
) -> ConnectorEvidenceInvariantSnapshotExportRequestRecord:
    return ConnectorEvidenceInvariantSnapshotExportRequestRecord(
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
        snapshot_filter=ConnectorEvidenceInvariantSnapshotExportRequestFilter(
            connector_id=record.connector_id,
            snapshot_id=record.snapshot_id,
            idempotency_key=record.snapshot_idempotency_key,
            limit=record.limit,
        ),
        export_reason=record.export_reason,
        format=record.format,
        requested_snapshot_count=record.requested_snapshot_count,
        snapshot_checksum_sha256=record.snapshot_checksum_sha256,
        redaction_policy=record.redaction_policy,
        controls=record.controls,
        permission_decision=PermissionDecision(**record.permission_decision),
        workflow_signal_status=record.workflow_signal_status,
        decision=record.decision,
        decision_actor_id=record.decision_actor_id,
        decision_note=record.decision_note,
        decided_at=record.decided_at,
        workflow_signal=record.workflow_signal,
        materialization_id=record.materialization_id,
        materialization_idempotency_key=record.materialization_idempotency_key,
        materialized_by=record.materialized_by,
        materialized_at=record.materialized_at,
        materialization_reason=record.materialization_reason,
        storage_adapter=record.storage_adapter,
        storage_key=record.storage_key,
        storage_uri=record.storage_uri,
        artifact_checksum_sha256=record.artifact_checksum_sha256,
        artifact_size_bytes=record.artifact_size_bytes,
        artifact_content_type=record.artifact_content_type,
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        notes=record.notes,
        created_at=record.created_at,
        idempotent_replay=idempotent_replay,
    )


def _materialization_result_from_record(
    record,
    permission_decision: PermissionDecision,
    idempotent_replay: bool = False,
) -> ConnectorEvidenceInvariantSnapshotExportMaterializationResult:
    if (
        record.materialization_id is None
        or record.materialization_idempotency_key is None
        or record.storage_adapter is None
        or record.storage_key is None
        or record.storage_uri is None
        or record.artifact_checksum_sha256 is None
        or record.artifact_size_bytes is None
        or record.artifact_content_type is None
        or record.audit_event_id is None
    ):
        raise ConnectorEvidenceInvariantSnapshotExportMaterializationConflict(
            record.export_request_id,
            "materialization_metadata_incomplete",
        )
    return ConnectorEvidenceInvariantSnapshotExportMaterializationResult(
        tenant_id=record.tenant_id,
        export_request_id=record.export_request_id,
        materialization_id=record.materialization_id,
        idempotency_key=record.materialization_idempotency_key,
        status=record.status,
        export_status=record.export_status,
        storage_status=record.storage_status,
        storage_adapter=record.storage_adapter,
        storage_key=record.storage_key,
        storage_uri=record.storage_uri,
        artifact_checksum_sha256=record.artifact_checksum_sha256,
        artifact_size_bytes=record.artifact_size_bytes,
        artifact_content_type=record.artifact_content_type,
        export_request=_snapshot_export_request_from_record(record),
        permission_decision=permission_decision,
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        idempotent_replay=idempotent_replay,
    )


def _export_request_fingerprint_from_request(
    request: ConnectorEvidenceInvariantSnapshotExportRequest,
) -> dict:
    return {
        "export_request_id": request.export_request_id,
        "requested_by": request.requested_by,
        "owner_role": request.owner_role,
        "risk_level": request.risk_level,
        "approval_id": request.approval_id,
        "workflow_id": request.workflow_id,
        "connector_id": request.connector_id,
        "snapshot_id": request.snapshot_id,
        "snapshot_idempotency_key": request.snapshot_idempotency_key,
        "export_reason": request.export_reason,
        "format": request.format,
        "limit": request.limit,
        "controls": request.controls,
        "notes": request.notes,
    }


async def _signal_snapshot_export_workflow(
    workflow_runtime: WorkflowSignalRuntime,
    export_request,
    request: ConnectorEvidenceInvariantSnapshotExportDecisionRequest,
    *,
    export_status: str,
) -> WorkflowSignalResult:
    signal_request = WorkflowConnectorEvidenceSnapshotExportSignalRequest(
        tenant_id=export_request.tenant_id,
        workflow_id=export_request.workflow_id,
        export_request_id=export_request.export_request_id,
        idempotency_key=export_request.idempotency_key,
        approval_id=export_request.approval_id,
        decision=request.decision,
        connector_id=export_request.connector_id,
        snapshot_id=export_request.snapshot_id,
        requested_snapshot_count=export_request.requested_snapshot_count,
        export_status=export_status,
        storage_status=export_request.storage_status,
        redaction_policy=export_request.redaction_policy,
    )
    try:
        return await workflow_runtime.signal_connector_evidence_snapshot_export(signal_request)
    except WorkflowSignalError as exc:
        return workflow_connector_evidence_snapshot_export_signal_failure_result(
            signal_request,
            reason=str(exc),
        )


def _export_request_status_for_decision(decision: ApprovalDecision) -> str:
    if decision == ApprovalDecision.APPROVE:
        return "approval_approved"
    if decision == ApprovalDecision.REJECT:
        return "approval_rejected"
    return "changes_requested"


def _export_status_for_decision(decision: ApprovalDecision) -> str:
    if decision == ApprovalDecision.APPROVE:
        return "approved_not_exported"
    if decision == ApprovalDecision.REJECT:
        return "rejected_not_exported"
    return "changes_requested_not_exported"


def _export_request_fingerprint_from_record(record) -> dict:
    return {
        "export_request_id": record.export_request_id,
        "requested_by": record.requested_by,
        "owner_role": record.owner_role,
        "risk_level": record.risk_level,
        "approval_id": record.approval_id,
        "workflow_id": record.workflow_id,
        "connector_id": record.connector_id,
        "snapshot_id": record.snapshot_id,
        "snapshot_idempotency_key": record.snapshot_idempotency_key,
        "export_reason": record.export_reason,
        "format": record.format,
        "limit": record.limit,
        "controls": record.controls,
        "notes": record.notes,
    }


def _evaluate_snapshot_permission(
    request: ConnectorEvidenceInvariantSnapshotRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            actor_scopes=request.actor_scopes,
            required_scopes=[SNAPSHOT_REQUIRED_SCOPE],
            attributes={
                "snapshot_id": request.snapshot_id,
                "connector_id": request.connector_id,
            },
        )
    )
    if not decision.allowed:
        raise ConnectorEvidenceInvariantSnapshotPermissionDenied(decision)
    return decision


def _snapshot_records_for_query(
    repository: AxisPersistenceRepository,
    query: ConnectorEvidenceInvariantSnapshotQuery,
) -> list[ConnectorEvidenceInvariantSnapshotRecord]:
    events = repository.list_audit_events(
        tenant_id=query.tenant_id,
        event_type=SNAPSHOT_AUDIT_EVENT_TYPE,
        limit=200,
    )
    records = [
        _snapshot_record_from_audit_event(event)
        for event in events
        if _snapshot_event_matches_query(event, query)
    ]
    return records[: query.limit]


def _snapshot_event_matches_query(
    event: AuditEvent,
    query: ConnectorEvidenceInvariantSnapshotQuery,
) -> bool:
    payload = event.payload
    return (
        (query.connector_id is None or payload.get("connector_id") == query.connector_id)
        and (query.snapshot_id is None or payload.get("snapshot_id") == query.snapshot_id)
        and (
            query.idempotency_key is None
            or payload.get("idempotency_key") == query.idempotency_key
        )
    )


def _find_snapshot_by_idempotency_key(
    repository: AxisPersistenceRepository,
    request: ConnectorEvidenceInvariantSnapshotRequest,
) -> AuditEvent | None:
    events = repository.list_audit_events(
        tenant_id=request.tenant_id,
        event_type=SNAPSHOT_AUDIT_EVENT_TYPE,
        limit=200,
    )
    return next(
        (
            event
            for event in events
            if event.payload.get("idempotency_key") == request.idempotency_key
        ),
        None,
    )


def _find_snapshot_by_id(
    repository: AxisPersistenceRepository,
    request: ConnectorEvidenceInvariantSnapshotRequest,
) -> AuditEvent | None:
    events = repository.list_audit_events(
        tenant_id=request.tenant_id,
        event_type=SNAPSHOT_AUDIT_EVENT_TYPE,
        limit=200,
    )
    return next(
        (
            event
            for event in events
            if event.payload.get("snapshot_id") == request.snapshot_id
        ),
        None,
    )


def _snapshot_record_from_audit_event(
    audit_event: AuditEvent,
    *,
    idempotent_replay: bool = False,
) -> ConnectorEvidenceInvariantSnapshotRecord:
    payload = audit_event.payload
    return ConnectorEvidenceInvariantSnapshotRecord(
        tenant_id=audit_event.tenant_id,
        snapshot_id=str(payload["snapshot_id"]),
        status="persisted",
        connector_id=payload.get("connector_id"),
        requested_by=audit_event.actor_id,
        idempotency_key=str(payload["idempotency_key"]),
        reason=str(payload["reason"]),
        invariant_count=int(payload["invariant_count"]),
        invariant_counts=dict(payload["invariant_counts"]),
        subject_ids=list(payload["subject_ids"]),
        report_digest_sha256=str(payload["report_digest_sha256"]),
        report_hash_algorithm=str(payload["report_hash_algorithm"]),
        permission_decision=PermissionDecision.model_validate(payload["permission_decision"]),
        audit_event_id=audit_event.id,
        audit_event_type=audit_event.event_type,
        idempotent_replay=idempotent_replay,
        notes=list(payload.get("notes") or []),
    )


def _snapshot_report_payload(report: ManufacturingConnectorEvidenceInvariantReport) -> dict:
    return {
        "tenant_id": report.tenant_id,
        "invariant_counts": report.invariant_counts,
        "invariants": [
            invariant.model_dump(mode="json")
            for invariant in sorted(
                report.invariants,
                key=lambda item: (item.evidence_type, item.subject_id, item.reason),
            )
        ],
    }


def _canonical_sha256(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _checkpoint_parent_id(
    report: ManufacturingConnectorSyncCheckpointRegistry,
    checkpoint_id: str,
) -> str | None:
    checkpoint = next(
        (
            candidate
            for candidate in report.checkpoints
            if candidate.checkpoint_id == checkpoint_id
        ),
        None,
    )
    return checkpoint.run_id if checkpoint is not None else None


def _lease_parent_id(
    report: ManufacturingConnectorCredentialLeaseRegistry,
    lease_id: str,
) -> str | None:
    lease = next(
        (candidate for candidate in report.leases if candidate.lease_id == lease_id),
        None,
    )
    return lease.handle_id if lease is not None else None


def _policy_parent_id(
    report: ManufacturingConnectorEgressPolicyRegistry,
    policy_id: str,
) -> str | None:
    policy = next(
        (candidate for candidate in report.policies if candidate.policy_id == policy_id),
        None,
    )
    return policy.connection_profile_id if policy is not None else None
