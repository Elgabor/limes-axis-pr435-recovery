import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from axis_api.audit import AuditEventCreate
from axis_api.audit_queries import _audit_event_to_ledger_event
from axis_api.demo import AuditLedgerEvent, OverviewMetric, OverviewStatus, WorkflowTimelineEvent
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    find_manufacturing_tenant_metadata,
    operational_provenance,
)
from axis_api.models import (
    AuditEvent,
    ReplaySimulationOutput,
    WorkflowRunRecord,
    WorkflowTimelineRecord,
)
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import AxisPersistenceRepository, ReplaySimulationOutputCreate
from axis_api.workflow_queries import _timeline_event_to_public


class ReplaySimulationQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    workflow_id: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=20, ge=1, le=100)
    retention_days: int = Field(default=365, ge=1, le=3650)
    legal_hold: bool = False
    baseline_policy_set_id: str | None = Field(default=None, min_length=1, max_length=180)
    candidate_policy_set_id: str | None = Field(default=None, min_length=1, max_length=180)
    connector_id: str | None = Field(default=None, min_length=1, max_length=160)


class ReplayPolicySetDiffValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ReplayPolicySetDiffDisabled(PermissionError):
    def __init__(self) -> None:
        super().__init__(ARBITRARY_POLICY_SET_DIFF_DISABLED_REASON)
        self.reason = ARBITRARY_POLICY_SET_DIFF_DISABLED_REASON


class ReplaySimulationOutputValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ReplaySimulationOutputPermissionDenied(PermissionError):
    def __init__(self, required_permission: str, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permission = required_permission
        self.decision = decision


class ReplaySimulationOutputConflict(ValueError):
    def __init__(self, simulation_output_id: str, reason: str) -> None:
        super().__init__("Replay simulation output already exists or conflicts")
        self.simulation_output_id = simulation_output_id
        self.reason = reason


class ReplaySimulationOutputPersistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    workflow_id: str = Field(min_length=1, max_length=160)
    simulation_output_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    idempotency_key: str = Field(min_length=1, max_length=200)
    requested_by: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=600)
    retention_window_days: int = Field(default=30, ge=1, le=3650)
    notes: list[str] = Field(default_factory=list)
    baseline_policy_set_id: str | None = Field(default=None, min_length=1, max_length=180)
    candidate_policy_set_id: str | None = Field(default=None, min_length=1, max_length=180)
    connector_id: str | None = Field(default=None, min_length=1, max_length=160)


class PolicySimulationResult(BaseModel):
    policy_id: str = Field(min_length=1)
    policy_name: str = Field(min_length=1)
    baseline_decision: str = Field(min_length=1)
    simulated_decision: str = Field(min_length=1)
    changed_outcome: bool
    evidence_refs: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)


class PolicySetEventDecision(BaseModel):
    event_ref: str = Field(min_length=1)
    event_kind: str = Field(min_length=1)
    baseline_decision: str = Field(min_length=1)
    candidate_decision: str = Field(min_length=1)
    changed_outcome: bool


class PolicySetVersionDiff(BaseModel):
    diff_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    baseline_policy_set_id: str = Field(min_length=1)
    baseline_policy_set_version: str = Field(min_length=1)
    candidate_policy_set_id: str = Field(min_length=1)
    candidate_policy_set_version: str = Field(min_length=1)
    historical_event_count: int = Field(ge=0)
    changed_policy_ids: list[str] = Field(default_factory=list)
    baseline_decision: str = Field(min_length=1)
    candidate_decision: str = Field(min_length=1)
    changed_outcome: bool
    diff_status: str = Field(min_length=1)
    audit_event_type: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    events_evaluated: int = Field(default=0, ge=0)
    changed_outcome_event_count: int = Field(default=0, ge=0)
    event_decisions: list[PolicySetEventDecision] = Field(default_factory=list)


class ReplayArtifact(BaseModel):
    artifact_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    workflow_name: str = Field(min_length=1)
    audit_scope: str = Field(min_length=1)
    replay_mode: str = Field(min_length=1)
    replay_ready: bool
    determinism_status: str = Field(min_length=1)
    timeline_event_count: int = Field(ge=0)
    audit_event_count: int = Field(ge=0)
    evidence_refs: list[str] = Field(default_factory=list)
    timeline: list[WorkflowTimelineEvent] = Field(default_factory=list)
    audit_events: list[AuditLedgerEvent] = Field(default_factory=list)
    policy_results: list[PolicySimulationResult] = Field(default_factory=list)
    policy_set_diffs: list[PolicySetVersionDiff] = Field(default_factory=list)


class ReplayRetentionWindow(BaseModel):
    policy_id: str = Field(min_length=1)
    retention_days: int = Field(ge=1)
    legal_hold: bool
    retention_enforced: bool
    retention_window_start: str = Field(min_length=1)
    disposal_action: str = Field(min_length=1)
    excluded_timeline_event_count: int = Field(ge=0)
    excluded_audit_event_count: int = Field(ge=0)
    excluded_output_count: int = Field(ge=0)
    notes: list[str] = Field(default_factory=list)


class ReplaySimulationOutputRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    simulation_output_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    required_scope: str = Field(min_length=1)
    replay_mode: str = Field(min_length=1)
    determinism_status: str = Field(min_length=1)
    output_hash: str = Field(min_length=1)
    retention_window_days: int = Field(ge=1)
    permission_decision: PermissionDecision
    artifact: ReplayArtifact
    evidence_refs: list[str] = Field(default_factory=list)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    idempotent_replay: bool = False
    created_at: datetime


class ManufacturingReplaySimulation(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    as_of: str = Field(min_length=1)
    simulation_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    retention_window: ReplayRetentionWindow
    artifacts: list[ReplayArtifact] = Field(default_factory=list)
    persisted_outputs: list[ReplaySimulationOutputRecord] = Field(default_factory=list)
    simulation_notes: list[str] = Field(default_factory=list)


REQUIRED_REPLAY_OUTPUT_SCOPE = "simulation:replay:persist"
REPLAY_OUTPUT_AUDIT_EVENT_TYPE = "simulation.replay_output.persisted"
POLICY_SET_DIFF_AUDIT_EVENT_TYPE = "connector.promotion_policy_set.simulated_diff"
ARBITRARY_POLICY_SET_DIFF_DISABLED_REASON = "arbitrary_policy_set_diff_disabled"
SYNTHETIC_BASELINE_POLICY_SET_ID = "policy_set_connector_asset_required_20260622_v2"
SYNTHETIC_CANDIDATE_POLICY_SET_ID = "policy_set_connector_asset_required_20260622_rollback"
POLICY_SET_EVENT_ALLOW_DECISION = "allow_historical_event"
POLICY_SET_EVENT_BLOCK_DECISION = "block_until_required_policy_gate"
POLICY_SET_ALLOW_ALL_DECISION = "allow_historical_events"


@dataclass
class _ReplayRetentionCounts:
    excluded_timeline_event_count: int = 0
    excluded_audit_event_count: int = 0
    excluded_output_count: int = 0

    @property
    def total_excluded(self) -> int:
        return (
            self.excluded_timeline_event_count
            + self.excluded_audit_event_count
            + self.excluded_output_count
        )


@dataclass
class _ArbitraryPolicySetDiffContext:
    baseline: object
    candidate: object
    baseline_policies: list
    candidate_policies: list


def build_replay_simulation(
    repository: AxisPersistenceRepository,
    query: ReplaySimulationQuery,
    *,
    arbitrary_policy_set_diff_enabled: bool = False,
) -> ManufacturingReplaySimulation:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, query.tenant_id)
    generated_at = datetime.now(UTC)
    diff_context = _load_arbitrary_policy_set_diff_context(
        repository,
        query,
        enabled=arbitrary_policy_set_diff_enabled,
    )
    retention_counts = _ReplayRetentionCounts()
    workflow_records = repository.list_workflow_runs(
        tenant_id=query.tenant_id,
        limit=query.limit,
    )
    if query.workflow_id is not None:
        workflow_records = [
            workflow for workflow in workflow_records if workflow.workflow_id == query.workflow_id
        ]

    audit_records = repository.list_audit_events(
        tenant_id=query.tenant_id,
        limit=200,
    )
    artifacts = []
    for workflow in workflow_records:
        retained_timeline, excluded_timeline = _apply_replay_retention(
            repository.list_workflow_timeline_events(
                tenant_id=workflow.tenant_id,
                workflow_id=workflow.workflow_id,
                limit=100,
            ),
            lambda record: record.occurred_at,
            query,
            generated_at,
        )
        retained_audit, excluded_audit = _apply_replay_retention(
            _matching_audit_records(audit_records, workflow),
            lambda record: record.created_at,
            query,
            generated_at,
        )
        retention_counts.excluded_timeline_event_count += excluded_timeline
        retention_counts.excluded_audit_event_count += excluded_audit
        artifacts.append(
            _build_artifact(
                workflow,
                retained_timeline,
                retained_audit,
                diff_context=diff_context,
            )
        )
    artifacts = [artifact for artifact in artifacts if artifact.timeline or artifact.audit_events]
    output_records, excluded_outputs = _apply_replay_output_retention(
        repository.list_replay_simulation_outputs(
            tenant_id=query.tenant_id,
            workflow_id=query.workflow_id,
            limit=query.limit,
        ),
        query,
        generated_at,
    )
    retention_counts.excluded_output_count = excluded_outputs
    retention_window = _retention_window(query, generated_at, retention_counts)
    persisted_outputs = [
        _simulation_output_from_record(record)
        for record in output_records
    ]

    return ManufacturingReplaySimulation(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(
            bool(workflow_records or audit_records or persisted_outputs)
        ),
        as_of=_as_of(artifacts),
        simulation_status=OverviewStatus.READY if artifacts else OverviewStatus.WATCH,
        metrics=_metrics(artifacts, persisted_outputs, retention_window),
        retention_window=retention_window,
        artifacts=artifacts,
        persisted_outputs=persisted_outputs,
        simulation_notes=[
            "Replay artifacts are derived from tenant-scoped workflow history and audit events.",
            "Policy simulation is deterministic preview logic, not live workflow replay.",
            "Policy-set version diffs compare governed connector policy sets over historical "
            "events without activating a new set.",
            "Persisted simulation outputs are governed audit artifacts with retention metadata.",
            "Replay retention windows are enforced at query time; legal hold suspends exclusion.",
            "Raw action payloads are not exposed in replay artifacts.",
            "Temporal replay and replay-output deletion jobs remain Platform work.",
        ],
    )


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _retention_cutoff(generated_at: datetime, retention_days: int) -> datetime:
    return generated_at - timedelta(days=retention_days)


def _apply_replay_retention[RecordT](
    records: list[RecordT],
    timestamp_for: Callable[[RecordT], datetime],
    query: ReplaySimulationQuery,
    generated_at: datetime,
) -> tuple[list[RecordT], int]:
    if query.legal_hold:
        return records, 0

    cutoff = _retention_cutoff(generated_at, query.retention_days)
    retained = [
        record
        for record in records
        if _utc_datetime(timestamp_for(record)) >= cutoff
    ]
    return retained, len(records) - len(retained)


def _apply_replay_output_retention(
    records: list[ReplaySimulationOutput],
    query: ReplaySimulationQuery,
    generated_at: datetime,
) -> tuple[list[ReplaySimulationOutput], int]:
    if query.legal_hold:
        return records, 0

    retained = []
    for record in records:
        effective_days = min(query.retention_days, record.retention_window_days)
        if _utc_datetime(record.created_at) >= _retention_cutoff(
            generated_at,
            effective_days,
        ):
            retained.append(record)
    return retained, len(records) - len(retained)


def _retention_window(
    query: ReplaySimulationQuery,
    generated_at: datetime,
    counts: _ReplayRetentionCounts,
) -> ReplayRetentionWindow:
    window_start = _retention_cutoff(generated_at, query.retention_days)
    retention_enforced = not query.legal_hold
    excluded_summary = (
        "Legal hold is active; replay retention exclusion is suspended."
        if query.legal_hold
        else f"Replay retention excluded {counts.total_excluded} expired record"
        f"{'' if counts.total_excluded == 1 else 's'} from this response."
    )
    return ReplayRetentionWindow(
        policy_id="axis-demo-replay-retention",
        retention_days=query.retention_days,
        legal_hold=query.legal_hold,
        retention_enforced=retention_enforced,
        retention_window_start=window_start.isoformat(),
        disposal_action="retain_legal_hold" if query.legal_hold else "enforced_exclusion",
        excluded_timeline_event_count=counts.excluded_timeline_event_count,
        excluded_audit_event_count=counts.excluded_audit_event_count,
        excluded_output_count=counts.excluded_output_count,
        notes=[
            "Replay windows are enforced before artifacts and persisted outputs are returned.",
            "Persisted outputs use the stricter of the query window and the output "
            "retention window.",
            excluded_summary,
            "Replay-output deletion jobs and non-audit legal hold workflows remain "
            "separate platform work.",
        ],
    )


def _load_arbitrary_policy_set_diff_context(
    repository: AxisPersistenceRepository,
    query: ReplaySimulationQuery,
    *,
    enabled: bool,
) -> _ArbitraryPolicySetDiffContext | None:
    requested = any(
        value is not None
        for value in (
            query.baseline_policy_set_id,
            query.candidate_policy_set_id,
            query.connector_id,
        )
    )
    if not requested:
        return None
    if not enabled:
        raise ReplayPolicySetDiffDisabled()
    if query.baseline_policy_set_id is None or query.candidate_policy_set_id is None:
        raise ReplayPolicySetDiffValidationError(
            "Arbitrary policy-set comparison requires both baseline and candidate "
            "policy set ids.",
            "policy_set_diff_pair_required",
        )
    if query.baseline_policy_set_id == query.candidate_policy_set_id:
        raise ReplayPolicySetDiffValidationError(
            "Arbitrary policy-set comparison requires two distinct policy sets.",
            "policy_set_diff_identical_policy_sets",
        )
    baseline = repository.get_connector_promotion_policy_set(
        query.tenant_id,
        query.baseline_policy_set_id,
    )
    if baseline is None:
        raise ReplayPolicySetDiffValidationError(
            "Arbitrary policy-set comparison baseline policy set was not found "
            "in this tenant.",
            "policy_set_diff_baseline_not_found",
        )
    candidate = repository.get_connector_promotion_policy_set(
        query.tenant_id,
        query.candidate_policy_set_id,
    )
    if candidate is None:
        raise ReplayPolicySetDiffValidationError(
            "Arbitrary policy-set comparison candidate policy set was not found "
            "in this tenant.",
            "policy_set_diff_candidate_not_found",
        )
    if baseline.connector_id != candidate.connector_id:
        raise ReplayPolicySetDiffValidationError(
            "Arbitrary policy-set comparison cannot cross connector boundaries.",
            "policy_set_diff_connector_mismatch",
        )
    if query.connector_id is not None and query.connector_id != baseline.connector_id:
        raise ReplayPolicySetDiffValidationError(
            "Arbitrary policy-set comparison connector does not match the policy sets.",
            "policy_set_diff_connector_mismatch",
        )
    return _ArbitraryPolicySetDiffContext(
        baseline=baseline,
        candidate=candidate,
        baseline_policies=_member_policies(repository, query.tenant_id, baseline.policy_ids),
        candidate_policies=_member_policies(repository, query.tenant_id, candidate.policy_ids),
    )


def _member_policies(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    policy_ids: list[str],
) -> list:
    policies = []
    for policy_id in policy_ids:
        policy = repository.get_connector_promotion_policy(tenant_id, policy_id)
        if policy is not None:
            policies.append(policy)
    return policies


def persist_replay_simulation_output(
    repository: AxisPersistenceRepository,
    request: ReplaySimulationOutputPersistRequest,
    *,
    arbitrary_policy_set_diff_enabled: bool = False,
) -> ReplaySimulationOutputRecord:
    existing_replay = repository.get_replay_simulation_output_by_idempotency_key(
        request.tenant_id,
        request.idempotency_key,
    )
    if existing_replay is not None:
        if (
            existing_replay.simulation_output_id != request.simulation_output_id
            or existing_replay.workflow_id != request.workflow_id
        ):
            raise ReplaySimulationOutputConflict(
                existing_replay.simulation_output_id,
                "simulation_output_idempotency_conflict",
            )
        return _simulation_output_from_record(existing_replay, idempotent_replay=True)

    existing_output = repository.get_replay_simulation_output(
        request.tenant_id,
        request.simulation_output_id,
    )
    if existing_output is not None:
        raise ReplaySimulationOutputConflict(
            existing_output.simulation_output_id,
            "simulation_output_already_exists",
        )

    simulation = build_replay_simulation(
        repository,
        ReplaySimulationQuery(
            tenant_id=request.tenant_id,
            workflow_id=request.workflow_id,
            limit=1,
            baseline_policy_set_id=request.baseline_policy_set_id,
            candidate_policy_set_id=request.candidate_policy_set_id,
            connector_id=request.connector_id,
        ),
        arbitrary_policy_set_diff_enabled=arbitrary_policy_set_diff_enabled,
    )
    if not simulation.artifacts:
        raise ReplaySimulationOutputValidationError(
            "Replay simulation output requires an existing replay artifact.",
            "replay_artifact_not_found",
        )
    artifact = simulation.artifacts[0]
    permission_decision = _evaluate_replay_output_permission(request, artifact)
    artifact_payload = artifact.model_dump(mode="json")
    output_hash = _artifact_output_hash(artifact_payload)
    audit_payload = {
        "simulation_output_id": request.simulation_output_id,
        "workflow_id": artifact.workflow_id,
        "artifact_id": artifact.artifact_id,
        "output_hash": output_hash,
        "replay_mode": artifact.replay_mode,
        "determinism_status": artifact.determinism_status,
        "retention_window_days": request.retention_window_days,
        "evidence_refs": artifact.evidence_refs,
        "policy_result_ids": [result.policy_id for result in artifact.policy_results],
        "policy_set_diff_ids": [diff.diff_id for diff in artifact.policy_set_diffs],
        "required_scope": REQUIRED_REPLAY_OUTPUT_SCOPE,
        "permission_decision": permission_decision.model_dump(),
        "reason": request.reason,
    }
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type=REPLAY_OUTPUT_AUDIT_EVENT_TYPE,
            payload=audit_payload,
        )
    )
    output = repository.create_replay_simulation_output(
        ReplaySimulationOutputCreate(
            tenant_id=request.tenant_id,
            simulation_output_id=request.simulation_output_id,
            workflow_id=artifact.workflow_id,
            artifact_id=artifact.artifact_id,
            idempotency_key=request.idempotency_key,
            requested_by=request.requested_by,
            required_scope=REQUIRED_REPLAY_OUTPUT_SCOPE,
            replay_mode=artifact.replay_mode,
            determinism_status=artifact.determinism_status,
            output_hash=output_hash,
            retention_window_days=request.retention_window_days,
            permission_decision=permission_decision.model_dump(),
            artifact_payload=artifact_payload,
            evidence_refs=artifact.evidence_refs,
            audit_event_id=audit_event.id,
            audit_event_type=audit_event.event_type,
            reason=request.reason,
            notes=request.notes,
        )
    )
    return _simulation_output_from_record(output)


def _evaluate_replay_output_permission(
    request: ReplaySimulationOutputPersistRequest,
    artifact: ReplayArtifact,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            actor_scopes=request.actor_scopes,
            required_scopes=[REQUIRED_REPLAY_OUTPUT_SCOPE],
            attributes={
                "workflow_id": artifact.workflow_id,
                "artifact_id": artifact.artifact_id,
                "simulation_output_id": request.simulation_output_id,
            },
        )
    )
    if not decision.allowed:
        raise ReplaySimulationOutputPermissionDenied(
            REQUIRED_REPLAY_OUTPUT_SCOPE,
            decision,
        )
    return decision


def _artifact_output_hash(artifact_payload: dict) -> str:
    encoded = json.dumps(artifact_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _simulation_output_from_record(
    record,
    *,
    idempotent_replay: bool = False,
) -> ReplaySimulationOutputRecord:
    return ReplaySimulationOutputRecord(
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
        permission_decision=PermissionDecision.model_validate(record.permission_decision),
        artifact=ReplayArtifact.model_validate(record.artifact_payload),
        evidence_refs=record.evidence_refs,
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        reason=record.reason,
        notes=record.notes,
        idempotent_replay=idempotent_replay,
        created_at=record.created_at,
    )


def _matching_audit_records(
    audit_records: list[AuditEvent],
    workflow: WorkflowRunRecord,
) -> list[AuditEvent]:
    records = [
        event
        for event in audit_records
        if event.payload.get("workflow_id") == workflow.workflow_id
        or event.payload.get("scope") == workflow.audit_scope
    ]
    return sorted(records, key=lambda event: (_utc_datetime(event.created_at), str(event.id)))


def _build_artifact(
    workflow: WorkflowRunRecord,
    timeline_records: list[WorkflowTimelineRecord],
    audit_records: list[AuditEvent],
    diff_context: _ArbitraryPolicySetDiffContext | None = None,
) -> ReplayArtifact:
    timeline = [_timeline_event_to_public(event) for event in timeline_records]
    audit_events = [_audit_event_to_ledger_event(event) for event in audit_records]
    evidence_refs = _evidence_refs(workflow, audit_events)

    policy_result = _human_approval_policy(workflow, audit_events, evidence_refs)
    if diff_context is not None:
        policy_set_diff = _arbitrary_policy_set_diff(
            workflow=workflow,
            timeline=timeline,
            audit_events=audit_events,
            evidence_refs=evidence_refs,
            context=diff_context,
        )
    else:
        policy_set_diff = _connector_policy_set_diff(
            workflow=workflow,
            timeline=timeline,
            audit_events=audit_events,
            evidence_refs=evidence_refs,
        )
    return ReplayArtifact(
        artifact_id=_artifact_id(workflow, timeline, audit_events),
        workflow_id=workflow.workflow_id,
        workflow_name=workflow.name,
        audit_scope=workflow.audit_scope,
        replay_mode="governance-preview",
        replay_ready=workflow.replay_ready,
        determinism_status=_determinism_status(workflow, timeline, audit_events),
        timeline_event_count=len(timeline),
        audit_event_count=len(audit_events),
        evidence_refs=evidence_refs,
        timeline=timeline,
        audit_events=audit_events,
        policy_results=[policy_result],
        policy_set_diffs=[policy_set_diff],
    )


def _artifact_id(
    workflow: WorkflowRunRecord,
    timeline: list[WorkflowTimelineEvent],
    audit_events: list[AuditLedgerEvent],
) -> str:
    payload = {
        "workflow_id": workflow.workflow_id,
        "timeline": [event.model_dump(mode="json") for event in timeline],
        "audit": [event.audit_event_id for event in audit_events],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"replay-{workflow.workflow_id}-{checksum}"


def _determinism_status(
    workflow: WorkflowRunRecord,
    timeline: list[WorkflowTimelineEvent],
    audit_events: list[AuditLedgerEvent],
) -> str:
    if workflow.replay_ready and timeline and audit_events:
        return "replay_ready"
    if timeline or audit_events:
        return "preview_only"
    return "insufficient_history"


def _evidence_refs(
    workflow: WorkflowRunRecord,
    audit_events: list[AuditLedgerEvent],
) -> list[str]:
    refs = {workflow.workflow_id, workflow.audit_scope, workflow.related_risk}
    refs.update(str(asset) for asset in workflow.related_assets)
    for signal in workflow.pending_signals:
        approval_id = signal.get("approval_id")
        if approval_id:
            refs.add(str(approval_id))
    for event in audit_events:
        refs.update(event.evidence_refs)
        if event.related_approval_id:
            refs.add(event.related_approval_id)
    return sorted(refs)


def _human_approval_policy(
    workflow: WorkflowRunRecord,
    audit_events: list[AuditLedgerEvent],
    evidence_refs: list[str],
) -> PolicySimulationResult:
    has_waiting_signal = any(
        signal.get("status") == "waiting" for signal in workflow.pending_signals
    )
    has_approval_required_event = any(
        event.severity == OverviewStatus.ACTION_REQUIRED for event in audit_events
    )
    simulated_decision = (
        "blocked_until_human_approval"
        if has_waiting_signal or has_approval_required_event
        else "no_block"
    )
    return PolicySimulationResult(
        policy_id="human-approval-required",
        policy_name="Human approval before external mutation",
        baseline_decision=workflow.state,
        simulated_decision=simulated_decision,
        changed_outcome=workflow.state != simulated_decision,
        evidence_refs=evidence_refs[:8],
        summary=(
            "Replay preview keeps the workflow blocked until the required owner signal "
            "is approved."
            if simulated_decision == "blocked_until_human_approval"
            else "Replay preview finds no pending human approval gate for this workflow."
        ),
    )


def _connector_policy_set_diff(
    workflow: WorkflowRunRecord,
    timeline: list[WorkflowTimelineEvent],
    audit_events: list[AuditLedgerEvent],
    evidence_refs: list[str],
) -> PolicySetVersionDiff:
    changed_policy_ids = ["connector.asset.required"]
    historical_event_count = len(timeline) + len(audit_events)
    return PolicySetVersionDiff(
        diff_id=_policy_set_diff_id(workflow, audit_events),
        connector_id="file_csv_manufacturing_assets",
        baseline_policy_set_id=SYNTHETIC_BASELINE_POLICY_SET_ID,
        baseline_policy_set_version="2026-06-22.2",
        candidate_policy_set_id=SYNTHETIC_CANDIDATE_POLICY_SET_ID,
        candidate_policy_set_version="2026-06-22.3",
        historical_event_count=historical_event_count,
        changed_policy_ids=changed_policy_ids,
        baseline_decision="allow_after_manifest_validation",
        candidate_decision="block_until_required_asset_gate",
        changed_outcome=True,
        diff_status="changed_outcome_detected",
        audit_event_type=POLICY_SET_DIFF_AUDIT_EVENT_TYPE,
        evidence_refs=evidence_refs[:8],
        summary=(
            "Historical workflow and audit evidence would be re-gated by the rollback "
            "policy set before connector promotion."
        ),
    )


def _arbitrary_policy_set_diff(
    workflow: WorkflowRunRecord,
    timeline: list[WorkflowTimelineEvent],
    audit_events: list[AuditLedgerEvent],
    evidence_refs: list[str],
    context: _ArbitraryPolicySetDiffContext,
) -> PolicySetVersionDiff:
    event_decisions: list[PolicySetEventDecision] = []
    for event in timeline:
        event_decisions.append(
            _policy_set_event_decision(
                event_ref=f"timeline:{workflow.workflow_id}:{event.at}:{event.event}",
                event_kind="timeline",
                attributes={"workflow_signal_status": event.result},
                context=context,
            )
        )
    for audit_event in audit_events:
        event_decisions.append(
            _policy_set_event_decision(
                event_ref=f"audit:{audit_event.audit_event_id}",
                event_kind="audit",
                attributes={
                    "status": audit_event.payload_preview.get("status"),
                    "workflow_signal_status": audit_event.payload_preview.get(
                        "workflow_signal_status"
                    ),
                },
                context=context,
            )
        )
    changed_count = sum(decision.changed_outcome for decision in event_decisions)
    changed_outcome = changed_count > 0
    changed_policy_ids = sorted(
        set(context.baseline.policy_ids) ^ set(context.candidate.policy_ids)
    )
    return PolicySetVersionDiff(
        diff_id=_policy_set_diff_id(
            workflow,
            audit_events,
            baseline_policy_set_id=context.baseline.policy_set_id,
            candidate_policy_set_id=context.candidate.policy_set_id,
            timeline=timeline,
        ),
        connector_id=context.baseline.connector_id,
        baseline_policy_set_id=context.baseline.policy_set_id,
        baseline_policy_set_version=context.baseline.policy_set_version,
        candidate_policy_set_id=context.candidate.policy_set_id,
        candidate_policy_set_version=context.candidate.policy_set_version,
        historical_event_count=len(event_decisions),
        changed_policy_ids=changed_policy_ids,
        baseline_decision=_policy_set_overall_decision(
            decision.baseline_decision for decision in event_decisions
        ),
        candidate_decision=_policy_set_overall_decision(
            decision.candidate_decision for decision in event_decisions
        ),
        changed_outcome=changed_outcome,
        diff_status="changed_outcome_detected" if changed_outcome else "no_outcome_change",
        audit_event_type=POLICY_SET_DIFF_AUDIT_EVENT_TYPE,
        evidence_refs=evidence_refs[:8],
        summary=(
            f"Arbitrary policy-set comparison evaluated {len(event_decisions)} historical "
            f"events for {context.baseline.policy_set_id} vs "
            f"{context.candidate.policy_set_id}; {changed_count} outcome(s) changed."
        ),
        events_evaluated=len(event_decisions),
        changed_outcome_event_count=changed_count,
        event_decisions=event_decisions,
    )


def _policy_set_event_decision(
    event_ref: str,
    event_kind: str,
    attributes: dict[str, str | None],
    context: _ArbitraryPolicySetDiffContext,
) -> PolicySetEventDecision:
    baseline_decision = _policy_set_decision_for_event(context.baseline_policies, attributes)
    candidate_decision = _policy_set_decision_for_event(context.candidate_policies, attributes)
    return PolicySetEventDecision(
        event_ref=event_ref,
        event_kind=event_kind,
        baseline_decision=baseline_decision,
        candidate_decision=candidate_decision,
        changed_outcome=baseline_decision != candidate_decision,
    )


def _policy_set_decision_for_event(
    policies: list,
    attributes: dict[str, str | None],
) -> str:
    gated = any(_policy_gates_event(policy, attributes) for policy in policies)
    return POLICY_SET_EVENT_BLOCK_DECISION if gated else POLICY_SET_EVENT_ALLOW_DECISION


def _policy_gates_event(policy, attributes: dict[str, str | None]) -> bool:
    if policy.status != "enabled" or policy.enforcement_mode != "required":
        return False
    status = attributes.get("status")
    if status is not None and status != policy.required_manual_import_status:
        return True
    signal_status = attributes.get("workflow_signal_status")
    return signal_status is not None and signal_status != policy.required_workflow_signal_status


def _policy_set_overall_decision(event_decisions) -> str:
    if any(decision == POLICY_SET_EVENT_BLOCK_DECISION for decision in event_decisions):
        return POLICY_SET_EVENT_BLOCK_DECISION
    return POLICY_SET_ALLOW_ALL_DECISION


def _policy_set_diff_id(
    workflow: WorkflowRunRecord,
    audit_events: list[AuditLedgerEvent],
    baseline_policy_set_id: str = SYNTHETIC_BASELINE_POLICY_SET_ID,
    candidate_policy_set_id: str = SYNTHETIC_CANDIDATE_POLICY_SET_ID,
    timeline: list[WorkflowTimelineEvent] | None = None,
) -> str:
    payload = {
        "workflow_id": workflow.workflow_id,
        "baseline_policy_set_id": baseline_policy_set_id,
        "candidate_policy_set_id": candidate_policy_set_id,
        "audit": [event.audit_event_id for event in audit_events],
    }
    if timeline is not None:
        payload["timeline"] = [f"{event.at}:{event.event}" for event in timeline]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"policy-set-diff-{workflow.workflow_id}-{checksum}"


def _as_of(artifacts: list[ReplayArtifact]) -> str:
    timestamps = [
        event.at
        for artifact in artifacts
        for event in artifact.timeline
    ] + [
        event.occurred_at
        for artifact in artifacts
        for event in artifact.audit_events
    ]
    if timestamps:
        return max(timestamps)
    return "2026-06-21T16:30:00+02:00"


def _metrics(
    artifacts: list[ReplayArtifact],
    persisted_outputs: list[ReplaySimulationOutputRecord],
    retention_window: ReplayRetentionWindow,
) -> list[OverviewMetric]:
    history_events = sum(
        artifact.timeline_event_count + artifact.audit_event_count for artifact in artifacts
    )
    policy_results = sum(len(artifact.policy_results) for artifact in artifacts)
    policy_set_diffs = sum(len(artifact.policy_set_diffs) for artifact in artifacts)
    ready_artifacts = sum(
        artifact.determinism_status == "replay_ready" for artifact in artifacts
    )
    excluded_records = (
        retention_window.excluded_timeline_event_count
        + retention_window.excluded_audit_event_count
        + retention_window.excluded_output_count
    )
    return [
        OverviewMetric(
            label="Replay Artifacts",
            value=str(len(artifacts)),
            detail="Workflow histories with matching audit evidence",
            status=OverviewStatus.READY if artifacts else OverviewStatus.WATCH,
        ),
        OverviewMetric(
            label="History Events",
            value=str(history_events),
            detail="Timeline and audit events included in replay previews",
            status=OverviewStatus.READY if history_events else OverviewStatus.WATCH,
        ),
        OverviewMetric(
            label="Policy Simulations",
            value=str(policy_results),
            detail="Deterministic policy previews evaluated against history",
            status=OverviewStatus.READY if policy_results else OverviewStatus.WATCH,
        ),
        OverviewMetric(
            label="Policy Set Diffs",
            value=str(policy_set_diffs),
            detail="Versioned connector policy-set comparisons over historical events",
            status=OverviewStatus.READY if policy_set_diffs else OverviewStatus.WATCH,
        ),
        OverviewMetric(
            label="Persisted Outputs",
            value=str(len(persisted_outputs)),
            detail="Governed replay outputs retained with audit evidence",
            status=OverviewStatus.READY if persisted_outputs else OverviewStatus.WATCH,
        ),
        OverviewMetric(
            label="Replay Window",
            value=f"{retention_window.retention_days}d",
            detail=(
                "Legal hold active; expired replay records are retained"
                if retention_window.legal_hold
                else "Query-time retention window enforced before replay response"
            ),
            status=(
                OverviewStatus.WATCH
                if retention_window.legal_hold
                else OverviewStatus.READY
            ),
        ),
        OverviewMetric(
            label="Retention Excluded",
            value=str(excluded_records),
            detail="Timeline, audit and output records outside the replay window",
            status=OverviewStatus.WATCH if excluded_records else OverviewStatus.READY,
        ),
        OverviewMetric(
            label="Deterministic Replay",
            value=str(ready_artifacts),
            detail="Full Temporal replay remains behind a future runtime path",
            status=OverviewStatus.WATCH,
        ),
    ]
