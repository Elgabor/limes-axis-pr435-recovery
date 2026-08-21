from datetime import UTC
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel, Field

from axis_api.audit import AuditEventCreate
from axis_api.demo import OverviewMetric, OverviewStatus
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    get_manufacturing_tenant_metadata,
    operational_provenance,
)
from axis_api.models import (
    ManufacturingDailyBrief,
    ManufacturingOperationRecord,
    ManufacturingRiskScenario,
    PlatformNotificationAcknowledgement,
    utc_now,
)
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    AxisPersistenceRepository,
    ManufacturingDailyBriefCreate,
    ManufacturingRiskScenarioCreate,
    PlatformNotificationAcknowledgementCreate,
)

DAILY_BRIEF_REQUIRED_SCOPES = ["briefs:generate", "audit:read", "workflows:read"]
QUALITY_RISK_REQUIRED_SCOPES = ["quality:read", "workflows:read", "audit:read"]
MAINTENANCE_RISK_REQUIRED_SCOPES = [
    "maintenance:read",
    "workflows:read",
    "audit:read",
]
SUPPLIER_DELAY_REQUIRED_SCOPES = ["supply:read", "workflows:read", "audit:read"]
NOTIFICATION_ACKNOWLEDGEMENT_REQUIRED_SCOPES = ["notifications:acknowledge"]
_NOTIFICATION_ACKNOWLEDGEMENT_STATE_ORDER = {
    "unread": 0,
    "read": 1,
    "acknowledged": 2,
}


class DailyPlantBriefPermissionDenied(PermissionError):
    def __init__(self, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class DailyPlantBriefValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class DailyPlantBriefIdempotencyConflict(ValueError):
    def __init__(self, brief_id: str) -> None:
        super().__init__("Idempotency key already exists with a different request")
        self.brief_id = brief_id


class QualityRiskScenarioPermissionDenied(PermissionError):
    def __init__(self, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class QualityRiskScenarioValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class QualityRiskScenarioIdempotencyConflict(ValueError):
    def __init__(self, scenario_id: str) -> None:
        super().__init__("Idempotency key already exists with a different request")
        self.scenario_id = scenario_id


class MaintenanceRiskScenarioPermissionDenied(PermissionError):
    def __init__(self, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class MaintenanceRiskScenarioValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class MaintenanceRiskScenarioIdempotencyConflict(ValueError):
    def __init__(self, scenario_id: str) -> None:
        super().__init__("Idempotency key already exists with a different request")
        self.scenario_id = scenario_id


class SupplierDelayScenarioPermissionDenied(PermissionError):
    def __init__(self, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class SupplierDelayScenarioValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class SupplierDelayScenarioIdempotencyConflict(ValueError):
    def __init__(self, scenario_id: str) -> None:
        super().__init__("Idempotency key already exists with a different request")
        self.scenario_id = scenario_id


class ManufacturingNotificationAcknowledgementConflict(ValueError):
    def __init__(
        self,
        notification_id: str,
        *,
        reason: str,
        current_state: str,
        requested_state: str,
    ) -> None:
        super().__init__("Notification acknowledgement conflicts with persisted state")
        self.notification_id = notification_id
        self.reason = reason
        self.current_state = current_state
        self.requested_state = requested_state


class ManufacturingNotificationAcknowledgementPermissionDenied(PermissionError):
    def __init__(self, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


class ManufacturingNotificationNotFound(LookupError):
    def __init__(self, notification_id: str) -> None:
        super().__init__("Notification not found")
        self.notification_id = notification_id


class ManufacturingOperationRecordView(BaseModel):
    record_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    record_type: str = Field(min_length=1)
    source_system: str = Field(min_length=1)
    status: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    occurred_at: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    related_asset: str | None = None
    workflow_id: str | None = None
    risk_level: str | None = None


class ManufacturingOperationsDataset(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    as_of: str = Field(min_length=1)
    metrics: list[OverviewMetric]
    domains: list[str]
    source_systems: list[str]
    records: list[ManufacturingOperationRecordView]
    notes: list[str] = Field(default_factory=list)


class ManufacturingOperationsSnapshotQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    operation_limit: int = Field(default=100, ge=1, le=200)
    workflow_limit: int = Field(default=25, ge=1, le=100)
    approval_limit: int = Field(default=25, ge=1, le=100)
    artifact_limit: int = Field(default=10, ge=1, le=50)
    audit_limit: int = Field(default=25, ge=1, le=100)


class ManufacturingDomainSnapshot(BaseModel):
    domain: str = Field(min_length=1)
    record_count: int = Field(ge=0)
    action_required_count: int = Field(ge=0)
    watch_count: int = Field(ge=0)
    highest_risk_level: str = Field(min_length=1)
    owner_roles: list[str] = Field(default_factory=list)
    workflow_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ManufacturingBriefSummary(BaseModel):
    brief_id: str = Field(min_length=1)
    brief_date: str = Field(min_length=1)
    status: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    source_record_count: int = Field(ge=0)
    generation_boundary: str = Field(min_length=1)
    audit_event_type: str = Field(min_length=1)


class ManufacturingRiskScenarioSummary(BaseModel):
    scenario_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    status: str = Field(min_length=1)
    risk_level: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    workflow_ids: list[str] = Field(default_factory=list)
    source_record_count: int = Field(ge=0)
    generation_boundary: str = Field(min_length=1)
    audit_event_type: str = Field(min_length=1)


class ManufacturingWorkflowSnapshot(BaseModel):
    workflow_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    state: str = Field(min_length=1)
    status: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    autonomy_level: str = Field(min_length=1)
    blocker: str | None = None
    pending_signal_count: int = Field(ge=0)
    replay_ready: bool


class ManufacturingApprovalSnapshot(BaseModel):
    approval_id: str = Field(min_length=1)
    workflow_id: str | None = None
    action_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    risk_level: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)


class ManufacturingAuditEventSummary(BaseModel):
    event_type: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    payload_refs: dict[str, str | list[str]] = Field(default_factory=dict)


class ManufacturingOperationsSnapshot(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    as_of: str = Field(min_length=1)
    metrics: list[OverviewMetric]
    domain_snapshots: list[ManufacturingDomainSnapshot]
    latest_daily_briefs: list[ManufacturingBriefSummary]
    risk_scenarios: list[ManufacturingRiskScenarioSummary]
    active_workflows: list[ManufacturingWorkflowSnapshot]
    pending_approvals: list[ManufacturingApprovalSnapshot]
    recent_audit_events: list[ManufacturingAuditEventSummary]
    generation_boundary: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)


class ManufacturingDemoReadinessTrack(BaseModel):
    name: str = Field(min_length=1)
    status: OverviewStatus
    detail: str = Field(min_length=1)


class ManufacturingDemoReadinessCheck(BaseModel):
    check_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    status: OverviewStatus
    observed_count: int = Field(ge=0)
    detail: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class ManufacturingDemoReadinessReport(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    as_of: str = Field(min_length=1)
    readiness_status: OverviewStatus
    summary: str = Field(min_length=1)
    tracks: list[ManufacturingDemoReadinessTrack]
    checks: list[ManufacturingDemoReadinessCheck]
    limitations: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    generation_boundary: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)


class ManufacturingNotificationQuery(ManufacturingOperationsSnapshotQuery):
    notification_limit: int = Field(default=8, ge=1, le=25)
    actor_id: str | None = Field(default=None, min_length=1)


class ManufacturingPlatformNotification(BaseModel):
    notification_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    severity: OverviewStatus
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    source: str = Field(min_length=1)
    route: str = Field(min_length=1)
    occurred_at: str = Field(min_length=1)
    owner_role: str | None = None
    related_workflow_id: str | None = None
    related_approval_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    action_label: str = Field(min_length=1)
    read_state: str = Field(default="unread", min_length=1)
    acknowledged_by: str | None = None
    acknowledged_at: str | None = None
    acknowledgement_reason: str | None = None


class ManufacturingNotificationCenter(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    as_of: str = Field(min_length=1)
    unread_count: int = Field(ge=0)
    action_required_count: int = Field(ge=0)
    watch_count: int = Field(ge=0)
    notifications: list[ManufacturingPlatformNotification]
    generation_boundary: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)


class ManufacturingNotificationAcknowledgementRequest(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    actor_id: str = Field(min_length=1)
    actor_scopes: list[str] = Field(default_factory=list)
    state: str = Field(default="acknowledged", pattern="^(read|acknowledged)$")
    reason: str = Field(min_length=1, max_length=600)


class ManufacturingNotificationAcknowledgementResult(BaseModel):
    tenant_id: str = Field(min_length=1)
    notification_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    state: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    read_state: str = Field(min_length=1)
    acknowledged_at: str = Field(min_length=1)
    generation_boundary: str = Field(min_length=1)


class ManufacturingOperationQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    domain: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    record_type: str | None = Field(default=None, min_length=1)
    source_system: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class DailyPlantBriefRequest(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    brief_date: str = Field(min_length=1, max_length=40)
    requested_by: str = Field(default="agent_daily_brief", min_length=1)
    actor_scopes: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=220)
    source_record_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=200)


class QualityRiskScenarioRequest(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    requested_by: str = Field(default="agent_quality_risk", min_length=1)
    actor_scopes: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=220)
    source_record_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=200)


class MaintenanceRiskScenarioRequest(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    requested_by: str = Field(default="agent_maintenance_risk", min_length=1)
    actor_scopes: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=220)
    source_record_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=200)


class SupplierDelayScenarioRequest(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    requested_by: str = Field(default="agent_supplier_delay", min_length=1)
    actor_scopes: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=220)
    source_record_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=200)


class DailyPlantBriefRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    brief_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    brief_date: str = Field(min_length=1)
    status: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    required_scopes: list[str]
    source_record_ids: list[str]
    summary_payload: dict
    permission_decision: PermissionDecision
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    idempotent_replay: bool = False


class QualityRiskScenarioRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    status: str = Field(min_length=1)
    risk_level: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    workflow_ids: list[str]
    source_record_ids: list[str]
    scenario_payload: dict
    permission_decision: PermissionDecision
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    idempotent_replay: bool = False


class MaintenanceRiskScenarioRecord(QualityRiskScenarioRecord):
    pass


class SupplierDelayScenarioRecord(QualityRiskScenarioRecord):
    pass


def _isoformat_utc(value) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _operation_record_to_public(
    record: ManufacturingOperationRecord,
) -> ManufacturingOperationRecordView:
    return ManufacturingOperationRecordView(
        record_id=record.record_id,
        domain=record.domain,
        record_type=record.record_type,
        source_system=record.source_system,
        status=record.status,
        owner_role=record.owner_role,
        related_asset=record.related_asset,
        workflow_id=record.workflow_id,
        risk_level=record.risk_level,
        occurred_at=_isoformat_utc(record.occurred_at),
        payload=record.payload,
        evidence_refs=record.evidence_refs,
    )


def _brief_record_to_public(
    brief: ManufacturingDailyBrief,
    *,
    idempotent_replay: bool,
) -> DailyPlantBriefRecord:
    return DailyPlantBriefRecord(
        tenant_id=brief.tenant_id,
        brief_id=brief.brief_id,
        idempotency_key=brief.idempotency_key,
        brief_date=brief.brief_date,
        status=brief.status,
        requested_by=brief.requested_by,
        required_scopes=brief.required_scopes,
        source_record_ids=brief.source_record_ids,
        summary_payload=brief.summary_payload,
        permission_decision=PermissionDecision.model_validate(brief.permission_decision),
        audit_event_id=brief.audit_event_id,
        audit_event_type=brief.audit_event_type,
        idempotent_replay=idempotent_replay,
    )


def _risk_scenario_to_public(
    scenario: ManufacturingRiskScenario,
    *,
    idempotent_replay: bool,
) -> QualityRiskScenarioRecord:
    return QualityRiskScenarioRecord(
        tenant_id=scenario.tenant_id,
        scenario_id=scenario.scenario_id,
        idempotency_key=scenario.idempotency_key,
        domain=scenario.domain,
        status=scenario.status,
        risk_level=scenario.risk_level,
        requested_by=scenario.requested_by,
        owner_role=scenario.owner_role,
        workflow_ids=scenario.workflow_ids,
        source_record_ids=scenario.source_record_ids,
        scenario_payload=scenario.scenario_payload,
        permission_decision=PermissionDecision.model_validate(scenario.permission_decision),
        audit_event_id=scenario.audit_event_id,
        audit_event_type=scenario.audit_event_type,
        idempotent_replay=idempotent_replay,
    )


def _metric_status(records: list[ManufacturingOperationRecordView]) -> OverviewStatus:
    if any(record.status == "action_required" for record in records):
        return OverviewStatus.ACTION_REQUIRED
    if any(record.status == "watch" for record in records):
        return OverviewStatus.WATCH
    return OverviewStatus.READY


def _metrics(records: list[ManufacturingOperationRecordView]) -> list[OverviewMetric]:
    action_required = sum(1 for record in records if record.status == "action_required")
    watch = sum(1 for record in records if record.status == "watch")
    domains = sorted({record.domain for record in records})
    source_systems = sorted({record.source_system for record in records})
    return [
        OverviewMetric(
            label="Operational Records",
            value=str(len(records)),
            detail="Tenant-scoped manufacturing records read from Postgres",
            status=OverviewStatus.READY if records else OverviewStatus.WATCH,
        ),
        OverviewMetric(
            label="Action Required",
            value=str(action_required),
            detail="Records currently blocking or escalating an operating decision",
            status=(
                OverviewStatus.ACTION_REQUIRED
                if action_required
                else OverviewStatus.READY
            ),
        ),
        OverviewMetric(
            label="Watch",
            value=str(watch),
            detail="Records that require owner monitoring before mutation",
            status=OverviewStatus.WATCH if watch else OverviewStatus.READY,
        ),
        OverviewMetric(
            label="Coverage",
            value=f"{len(domains)} domains",
            detail=f"{len(source_systems)} source systems represented",
            status=_metric_status(records),
        ),
    ]


def query_manufacturing_operations_dataset(
    repository: AxisPersistenceRepository,
    query: ManufacturingOperationQuery,
) -> ManufacturingOperationsDataset:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, query.tenant_id)
    records = [
        _operation_record_to_public(record)
        for record in repository.list_manufacturing_operation_records(
            tenant_id=query.tenant_id,
            domain=query.domain,
            status=query.status,
            record_type=query.record_type,
            source_system=query.source_system,
            limit=query.limit,
        )
    ]
    has_persisted_records = bool(records)
    if not has_persisted_records and any(
        value is not None
        for value in (query.domain, query.status, query.record_type, query.source_system)
    ):
        has_persisted_records = bool(
            repository.list_manufacturing_operation_records(
                tenant_id=query.tenant_id,
                limit=1,
            )
        )
    as_of = records[0].occurred_at if records else tenant_metadata.as_of
    return ManufacturingOperationsDataset(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(has_persisted_records),
        as_of=as_of,
        metrics=_metrics(records),
        domains=sorted({record.domain for record in records}),
        source_systems=sorted({record.source_system for record in records}),
        records=records,
        notes=[
            "This view is backed by tenant-scoped manufacturing operation records.",
            "Records are public-safe operational references, not browser fallbacks.",
            "Source payloads are redacted to business metadata before API exposure.",
        ],
    )


RISK_LEVEL_ORDER = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


def _risk_level_rank(value: str | None) -> int:
    return RISK_LEVEL_ORDER.get((value or "").lower(), 0)


def _highest_risk_level(records: list[ManufacturingOperationRecordView]) -> str:
    ranked = sorted(
        {record.risk_level for record in records if record.risk_level},
        key=_risk_level_rank,
        reverse=True,
    )
    if ranked:
        return ranked[0]
    if any(record.status == "action_required" for record in records):
        return "high"
    if any(record.status == "watch" for record in records):
        return "medium"
    return "low"


def _domain_snapshots(
    records: list[ManufacturingOperationRecordView],
) -> list[ManufacturingDomainSnapshot]:
    domains = sorted({record.domain for record in records})
    snapshots: list[ManufacturingDomainSnapshot] = []
    for domain in domains:
        domain_records = [record for record in records if record.domain == domain]
        snapshots.append(
            ManufacturingDomainSnapshot(
                domain=domain,
                record_count=len(domain_records),
                action_required_count=sum(
                    1 for record in domain_records if record.status == "action_required"
                ),
                watch_count=sum(1 for record in domain_records if record.status == "watch"),
                highest_risk_level=_highest_risk_level(domain_records),
                owner_roles=sorted({record.owner_role for record in domain_records}),
                workflow_ids=sorted(
                    {record.workflow_id for record in domain_records if record.workflow_id}
                ),
                evidence_refs=sorted(
                    {ref for record in domain_records for ref in record.evidence_refs}
                ),
            )
        )
    return snapshots


def _brief_summary(brief) -> ManufacturingBriefSummary:
    return ManufacturingBriefSummary(
        brief_id=brief.brief_id,
        brief_date=brief.brief_date,
        status=brief.status,
        requested_by=brief.requested_by,
        source_record_count=len(brief.source_record_ids),
        generation_boundary=brief.summary_payload.get(
            "generation_boundary",
            "persisted_daily_brief",
        ),
        audit_event_type=brief.audit_event_type,
    )


def _risk_scenario_summary(scenario) -> ManufacturingRiskScenarioSummary:
    return ManufacturingRiskScenarioSummary(
        scenario_id=scenario.scenario_id,
        domain=scenario.domain,
        status=scenario.status,
        risk_level=scenario.risk_level,
        owner_role=scenario.owner_role,
        workflow_ids=scenario.workflow_ids,
        source_record_count=len(scenario.source_record_ids),
        generation_boundary=scenario.scenario_payload.get(
            "generation_boundary",
            "persisted_risk_scenario",
        ),
        audit_event_type=scenario.audit_event_type,
    )


def _workflow_snapshot(workflow) -> ManufacturingWorkflowSnapshot:
    return ManufacturingWorkflowSnapshot(
        workflow_id=workflow.workflow_id,
        name=workflow.name,
        domain=workflow.domain,
        state=workflow.state,
        status=workflow.status,
        owner_role=workflow.owner_role,
        autonomy_level=workflow.autonomy_level,
        blocker=workflow.blocker,
        pending_signal_count=len(workflow.pending_signals),
        replay_ready=workflow.replay_ready,
    )


def _approval_snapshot(approval) -> ManufacturingApprovalSnapshot:
    return ManufacturingApprovalSnapshot(
        approval_id=approval.approval_id,
        workflow_id=approval.workflow_id,
        action_id=approval.action_id,
        status=approval.status,
        owner_role=approval.owner_role,
        risk_level=approval.risk_level,
        requested_by=approval.requested_by,
    )


def _normalize_audit_reference(value: object) -> str | list[str] | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return None


def _audit_event_summary(audit_event) -> ManufacturingAuditEventSummary:

    payload_refs = {
        key: reference
        for key, value in audit_event.payload.items()
        if key.endswith("_id")
        or key.endswith("_ids")
        or key in {"domain", "risk_level", "brief_date"}
        if (reference := _normalize_audit_reference(value)) is not None
    }
    return ManufacturingAuditEventSummary(
        event_type=audit_event.event_type,
        actor_id=audit_event.actor_id,
        created_at=_isoformat_utc(audit_event.created_at),
        payload_refs=payload_refs,
    )


def _snapshot_metrics(
    *,
    records: list[ManufacturingOperationRecordView],
    workflows: list,
    approvals: list,
    briefs: list,
    scenarios: list,
) -> list[OverviewMetric]:
    open_workflows = _open_workflows(workflows)
    pending_approvals = [approval for approval in approvals if approval.status == "pending"]
    generated_artifacts = len(briefs) + len(scenarios)
    return [
        OverviewMetric(
            label="Operation Records",
            value=str(len(records)),
            detail="Persisted tenant-scoped operational records in the snapshot",
            status=OverviewStatus.READY if records else OverviewStatus.WATCH,
        ),
        OverviewMetric(
            label="Open Workflows",
            value=str(len(open_workflows)),
            detail="Persisted workflows that are not completed or cancelled",
            status=OverviewStatus.ACTION_REQUIRED if open_workflows else OverviewStatus.READY,
        ),
        OverviewMetric(
            label="Pending Approvals",
            value=str(len(pending_approvals)),
            detail="Persisted approval records awaiting owner decision",
            status=(
                OverviewStatus.ACTION_REQUIRED
                if pending_approvals
                else OverviewStatus.READY
            ),
        ),
        OverviewMetric(
            label="Generated Artifacts",
            value=str(generated_artifacts),
            detail="Persisted daily briefs and risk scenarios linked to operations",
            status=OverviewStatus.READY if generated_artifacts else OverviewStatus.WATCH,
        ),
    ]


def _open_workflows(workflows: list) -> list:
    return [
        workflow
        for workflow in workflows
        if workflow.state not in {"completed", "cancelled", "failed"}
    ]


def build_manufacturing_operations_snapshot(
    repository: AxisPersistenceRepository,
    query: ManufacturingOperationsSnapshotQuery,
) -> ManufacturingOperationsSnapshot:
    tenant_metadata = get_manufacturing_tenant_metadata(repository, query.tenant_id)
    records = [
        _operation_record_to_public(record)
        for record in repository.list_manufacturing_operation_records(
            tenant_id=query.tenant_id,
            limit=query.operation_limit,
        )
    ]
    workflows = repository.list_workflow_runs(
        tenant_id=query.tenant_id,
        limit=query.workflow_limit,
    )
    approvals = repository.list_approval_records(
        tenant_id=query.tenant_id,
        limit=query.approval_limit,
    )
    briefs = repository.list_manufacturing_daily_briefs(
        tenant_id=query.tenant_id,
        limit=query.artifact_limit,
    )
    scenarios = repository.list_manufacturing_risk_scenarios(
        tenant_id=query.tenant_id,
        limit=query.artifact_limit,
    )
    audit_events = repository.list_audit_events(
        tenant_id=query.tenant_id,
        limit=query.audit_limit,
    )
    as_of_candidates = [
        *[record.occurred_at for record in records],
        *[_isoformat_utc(workflow.started_at) for workflow in workflows],
        *[_isoformat_utc(event.created_at) for event in audit_events],
    ]
    as_of = max(as_of_candidates) if as_of_candidates else tenant_metadata.as_of
    has_persisted_records = any(
        (records, workflows, approvals, briefs, scenarios, audit_events)
    )

    return ManufacturingOperationsSnapshot(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(has_persisted_records),
        as_of=as_of,
        metrics=_snapshot_metrics(
            records=records,
            workflows=workflows,
            approvals=approvals,
            briefs=briefs,
            scenarios=scenarios,
        ),
        domain_snapshots=_domain_snapshots(records),
        latest_daily_briefs=[_brief_summary(brief) for brief in briefs],
        risk_scenarios=[_risk_scenario_summary(scenario) for scenario in scenarios],
        active_workflows=[
            _workflow_snapshot(workflow) for workflow in _open_workflows(workflows)
        ],
        pending_approvals=[
            _approval_snapshot(approval)
            for approval in approvals
            if approval.status == "pending"
        ],
        recent_audit_events=[_audit_event_summary(event) for event in audit_events],
        generation_boundary="persisted_manufacturing_operations_snapshot",
        notes=[
            "Snapshot composes persisted operations, workflows, approvals and audit artifacts.",
            "It does not generate new briefs, scenarios, workflow signals or connector runs.",
            "No source-system query, model provider call or credential retrieval is performed.",
        ],
    )


def _ready_if_has_records(count: int) -> OverviewStatus:
    return OverviewStatus.READY if count > 0 else OverviewStatus.ACTION_REQUIRED


def _watch_if_empty(count: int) -> OverviewStatus:
    return OverviewStatus.READY if count > 0 else OverviewStatus.WATCH


def _demo_readiness_status(checks: list[ManufacturingDemoReadinessCheck]) -> OverviewStatus:
    if any(check.status == OverviewStatus.ACTION_REQUIRED for check in checks):
        return OverviewStatus.ACTION_REQUIRED
    if any(check.status == OverviewStatus.WATCH for check in checks):
        return OverviewStatus.WATCH
    return OverviewStatus.READY


def _limited_evidence_refs(values: list[str]) -> list[str]:
    return sorted({value for value in values if value})[:6]


def _notification_id(*parts: str | None) -> str:
    stable_parts = [part or "" for part in parts]
    digest = sha256("|".join(stable_parts).encode()).hexdigest()[:12]
    return f"notif_{digest}"


def _status_label(status: str) -> str:
    return status.replace("_", " ")


def _notification_priority(notification: ManufacturingPlatformNotification) -> tuple[int, str]:
    severity_order = {
        OverviewStatus.ACTION_REQUIRED: 0,
        OverviewStatus.WATCH: 1,
        OverviewStatus.READY: 2,
    }
    return (severity_order[notification.severity], notification.notification_id)


def _acknowledged_notification_count(
    notifications: list[ManufacturingPlatformNotification],
) -> int:
    return sum(
        1
        for notification in notifications
        if notification.read_state in {"read", "acknowledged"}
    )


def _with_acknowledgement_state(
    repository: AxisPersistenceRepository,
    query: ManufacturingNotificationQuery,
    notifications: list[ManufacturingPlatformNotification],
) -> list[ManufacturingPlatformNotification]:
    if query.actor_id is None or not notifications:
        return notifications

    acknowledgements = repository.list_platform_notification_acknowledgements(
        tenant_id=query.tenant_id,
        actor_id=query.actor_id,
        notification_ids=[notification.notification_id for notification in notifications],
    )
    acknowledgements_by_id = {
        acknowledgement.notification_id: acknowledgement
        for acknowledgement in acknowledgements
    }
    resolved_notifications: list[ManufacturingPlatformNotification] = []
    for notification in notifications:
        acknowledgement = acknowledgements_by_id.get(notification.notification_id)
        if acknowledgement is None:
            resolved_notifications.append(notification)
            continue

        resolved_notifications.append(
            notification.model_copy(
                update={
                    "read_state": acknowledgement.state,
                    "acknowledged_by": acknowledgement.actor_id,
                    "acknowledged_at": _isoformat_utc(acknowledgement.acknowledged_at),
                    "acknowledgement_reason": acknowledgement.reason,
                }
            )
        )
    return resolved_notifications


def build_manufacturing_notification_center(
    repository: AxisPersistenceRepository,
    query: ManufacturingNotificationQuery,
) -> ManufacturingNotificationCenter:
    snapshot = build_manufacturing_operations_snapshot(repository, query)
    notifications: list[ManufacturingPlatformNotification] = []

    for domain in snapshot.domain_snapshots:
        if domain.action_required_count == 0 and domain.watch_count == 0:
            continue

        severity = (
            OverviewStatus.ACTION_REQUIRED
            if domain.action_required_count > 0
            else OverviewStatus.WATCH
        )
        detail = (
            f"{domain.action_required_count} action-required and "
            f"{domain.watch_count} watch records across {domain.record_count} "
            f"{domain.domain} records."
        )
        notifications.append(
            ManufacturingPlatformNotification(
                notification_id=_notification_id(
                    snapshot.tenant_id,
                    "domain",
                    domain.domain,
                    str(domain.action_required_count),
                    str(domain.watch_count),
                ),
                category="operations",
                severity=severity,
                title=f"{domain.domain} needs operator attention",
                detail=detail,
                source="operations_snapshot",
                route="/",
                occurred_at=snapshot.as_of,
                owner_role=domain.owner_roles[0] if domain.owner_roles else None,
                related_workflow_id=domain.workflow_ids[0] if domain.workflow_ids else None,
                evidence_refs=domain.evidence_refs[:4],
                action_label="Open operations",
            )
        )

    for approval in snapshot.pending_approvals:
        severity = (
            OverviewStatus.ACTION_REQUIRED
            if approval.risk_level.lower() in {"critical", "high"}
            else OverviewStatus.WATCH
        )
        notifications.append(
            ManufacturingPlatformNotification(
                notification_id=_notification_id(
                    snapshot.tenant_id,
                    "approval",
                    approval.approval_id,
                    approval.status,
                ),
                category="approval",
                severity=severity,
                title=f"Approval pending for {approval.action_id}",
                detail=(
                    f"{approval.requested_by} requested {approval.owner_role} review; "
                    f"risk level is {approval.risk_level}."
                ),
                source="approval_records",
                route="/approvals",
                occurred_at=snapshot.as_of,
                owner_role=approval.owner_role,
                related_workflow_id=approval.workflow_id,
                related_approval_id=approval.approval_id,
                evidence_refs=[approval.approval_id],
                action_label="Review approval",
            )
        )

    for workflow in snapshot.active_workflows:
        if workflow.pending_signal_count == 0 and workflow.blocker is None:
            continue

        severity = (
            OverviewStatus.ACTION_REQUIRED
            if workflow.status == "action_required"
            else OverviewStatus.WATCH
        )
        notifications.append(
            ManufacturingPlatformNotification(
                notification_id=_notification_id(
                    snapshot.tenant_id,
                    "workflow",
                    workflow.workflow_id,
                    workflow.state,
                    str(workflow.pending_signal_count),
                ),
                category="workflow",
                severity=severity,
                title=f"{workflow.name} is {_status_label(workflow.state)}",
                detail=workflow.blocker
                or f"{workflow.pending_signal_count} pending workflow signals.",
                source="workflow_runs",
                route="/workflows",
                occurred_at=snapshot.as_of,
                owner_role=workflow.owner_role,
                related_workflow_id=workflow.workflow_id,
                evidence_refs=[workflow.workflow_id],
                action_label="Open workflow",
            )
        )

    for event in snapshot.recent_audit_events[:3]:
        notifications.append(
            ManufacturingPlatformNotification(
                notification_id=_notification_id(
                    snapshot.tenant_id,
                    "audit",
                    event.event_type,
                    event.created_at,
                ),
                category="audit",
                severity=OverviewStatus.READY,
                title=f"Audit evidence recorded: {event.event_type}",
                detail=f"{event.actor_id} wrote append-only evidence.",
                source="audit_events",
                route="/audit",
                occurred_at=event.created_at,
                owner_role=None,
                evidence_refs=[event.event_type],
                action_label="Open audit",
            )
        )

    notifications = sorted(notifications, key=_notification_priority)[
        : query.notification_limit
    ]
    notifications = _with_acknowledgement_state(repository, query, notifications)
    return ManufacturingNotificationCenter(
        tenant_id=snapshot.tenant_id,
        plant_name=snapshot.plant_name,
        scenario=snapshot.scenario,
        provenance=snapshot.provenance,
        as_of=snapshot.as_of,
        unread_count=len(notifications) - _acknowledged_notification_count(notifications),
        action_required_count=sum(
            1
            for notification in notifications
            if notification.severity == OverviewStatus.ACTION_REQUIRED
        ),
        watch_count=sum(
            1 for notification in notifications if notification.severity == OverviewStatus.WATCH
        ),
        notifications=notifications,
        generation_boundary="derived_from_persisted_operations_snapshot",
        notes=[
            (
                "Notifications are derived from persisted operations, workflow, "
                "approval and audit state."
            ),
            "Notification read and acknowledgement state is persisted per tenant actor.",
            "The API does not use local fallback data for notification state.",
        ],
    )


def _notification_acknowledgement_event_type(state: str) -> str:
    if state == "read":
        return "platform.notification.read"
    return "platform.notification.acknowledged"


def _notification_acknowledgement_permission(
    request: ManufacturingNotificationAcknowledgementRequest,
    notification: ManufacturingPlatformNotification,
) -> PermissionDecision:
    return evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            actor_scopes=request.actor_scopes,
            required_scopes=NOTIFICATION_ACKNOWLEDGEMENT_REQUIRED_SCOPES,
            attributes={
                "notification_id": notification.notification_id,
                "category": notification.category,
                "severity": notification.severity.value,
                "source": notification.source,
                "route": notification.route,
                "owner_role": notification.owner_role,
            },
        )
    )


def _notification_acknowledgement_payload(
    request: ManufacturingNotificationAcknowledgementRequest,
    notification: ManufacturingPlatformNotification,
) -> dict:
    return {
        "notification_id": notification.notification_id,
        "state": request.state,
        "reason": request.reason,
        "title": notification.title,
        "category": notification.category,
        "severity": notification.severity.value,
        "source": notification.source,
        "route": notification.route,
        "owner_role": notification.owner_role,
        "related_workflow_id": notification.related_workflow_id,
        "related_approval_id": notification.related_approval_id,
        "evidence_refs": notification.evidence_refs,
        "generation_boundary": "derived_from_persisted_operations_snapshot",
    }


def _notification_acknowledgement_result(
    acknowledgement: PlatformNotificationAcknowledgement,
) -> ManufacturingNotificationAcknowledgementResult:
    return ManufacturingNotificationAcknowledgementResult(
        tenant_id=acknowledgement.tenant_id,
        notification_id=acknowledgement.notification_id,
        actor_id=acknowledgement.actor_id,
        state=acknowledgement.state,
        reason=acknowledgement.reason,
        audit_event_id=acknowledgement.audit_event_id,
        audit_event_type=acknowledgement.audit_event_type,
        read_state=acknowledgement.state,
        acknowledged_at=_isoformat_utc(acknowledgement.acknowledged_at),
        generation_boundary="persisted_platform_notification_acknowledgement",
    )


def record_manufacturing_notification_acknowledgement(
    repository: AxisPersistenceRepository,
    notification_id: str,
    request: ManufacturingNotificationAcknowledgementRequest,
) -> ManufacturingNotificationAcknowledgementResult:
    center = build_manufacturing_notification_center(
        repository,
        ManufacturingNotificationQuery(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            notification_limit=25,
        ),
    )
    notification = next(
        (
            item
            for item in center.notifications
            if item.notification_id == notification_id
        ),
        None,
    )
    if notification is None:
        raise ManufacturingNotificationNotFound(notification_id)

    decision = _notification_acknowledgement_permission(request, notification)
    if not decision.allowed:
        raise ManufacturingNotificationAcknowledgementPermissionDenied(decision)

    repository.acquire_platform_notification_acknowledgement_lock(
        tenant_id=request.tenant_id,
        notification_id=notification.notification_id,
        actor_id=request.actor_id,
    )
    existing_acknowledgement = repository.get_platform_notification_acknowledgement(
        tenant_id=request.tenant_id,
        notification_id=notification.notification_id,
        actor_id=request.actor_id,
    )
    if existing_acknowledgement is not None:
        if existing_acknowledgement.state == request.state:
            if existing_acknowledgement.reason == request.reason:
                return _notification_acknowledgement_result(existing_acknowledgement)
            raise ManufacturingNotificationAcknowledgementConflict(
                notification.notification_id,
                reason="acknowledgement_replay_payload_conflict",
                current_state=existing_acknowledgement.state,
                requested_state=request.state,
            )
        current_state_order = _NOTIFICATION_ACKNOWLEDGEMENT_STATE_ORDER.get(
            existing_acknowledgement.state
        )
        requested_state_order = _NOTIFICATION_ACKNOWLEDGEMENT_STATE_ORDER[request.state]
        if current_state_order is None or requested_state_order < current_state_order:
            raise ManufacturingNotificationAcknowledgementConflict(
                notification.notification_id,
                reason=(
                    "acknowledgement_current_state_invalid"
                    if current_state_order is None
                    else "acknowledgement_state_regression"
                ),
                current_state=existing_acknowledgement.state,
                requested_state=request.state,
            )

    event_type = _notification_acknowledgement_event_type(request.state)
    acknowledged_at = utc_now()
    payload = _notification_acknowledgement_payload(request, notification)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            event_type=event_type,
            payload=payload,
        )
    )
    acknowledgement = repository.upsert_platform_notification_acknowledgement(
        PlatformNotificationAcknowledgementCreate(
            tenant_id=request.tenant_id,
            notification_id=notification.notification_id,
            actor_id=request.actor_id,
            state=request.state,
            reason=request.reason,
            source=notification.source,
            notification_title=notification.title,
            notification_category=notification.category,
            notification_severity=notification.severity.value,
            payload=payload,
            audit_event_id=audit_event.id,
            audit_event_type=event_type,
            acknowledged_at=acknowledged_at,
        )
    )

    return _notification_acknowledgement_result(acknowledgement)


def build_manufacturing_demo_readiness_report(
    repository: AxisPersistenceRepository,
    query: ManufacturingOperationsSnapshotQuery,
) -> ManufacturingDemoReadinessReport:
    snapshot = build_manufacturing_operations_snapshot(repository, query)
    operation_count = sum(domain.record_count for domain in snapshot.domain_snapshots)
    generated_artifact_count = len(snapshot.latest_daily_briefs) + len(snapshot.risk_scenarios)
    pending_gate_count = len(snapshot.pending_approvals)
    audit_event_count = len(snapshot.recent_audit_events)
    replay_ready_count = sum(1 for workflow in snapshot.active_workflows if workflow.replay_ready)

    operation_evidence = _limited_evidence_refs(
        [ref for domain in snapshot.domain_snapshots for ref in domain.evidence_refs]
    )
    generated_evidence = _limited_evidence_refs(
        [brief.brief_id for brief in snapshot.latest_daily_briefs]
        + [scenario.scenario_id for scenario in snapshot.risk_scenarios]
    )
    approval_evidence = _limited_evidence_refs(
        [approval.approval_id for approval in snapshot.pending_approvals]
    )
    audit_evidence = _limited_evidence_refs(
        [event.event_type for event in snapshot.recent_audit_events]
    )

    limitations = [
        "Not a production readiness claim.",
        (
            "Local demo backup and restore are available; Enterprise HA and "
            "disaster recovery are not yet acceptance-gated."
        ),
        "SSO/Keycloak hardening is not complete for customer production rollout.",
        (
            "S3/MinIO retention adapter readiness exists for governed connector "
            "evidence exports; production KMS policy, bucket-policy review, "
            "restore drills and legal operations remain Enterprise work."
        ),
        (
            "Live customer connector execution requires explicit credential, egress "
            "and support runbooks."
        ),
    ]
    checks = [
        ManufacturingDemoReadinessCheck(
            check_id="operations_snapshot",
            label="Persisted operations snapshot",
            status=_ready_if_has_records(operation_count),
            observed_count=operation_count,
            detail=(
                f"{operation_count} operation records across "
                f"{len(snapshot.domain_snapshots)} persisted domains."
            ),
            evidence_refs=operation_evidence,
        ),
        ManufacturingDemoReadinessCheck(
            check_id="generated_artifacts",
            label="Generated governed artifacts",
            status=_ready_if_has_records(generated_artifact_count),
            observed_count=generated_artifact_count,
            detail="Daily briefs and risk scenarios are persisted and audit-backed.",
            evidence_refs=generated_evidence,
        ),
        ManufacturingDemoReadinessCheck(
            check_id="human_approval_gates",
            label="Human approval gates",
            status=_watch_if_empty(pending_gate_count),
            observed_count=pending_gate_count,
            detail=(
                "Pending approval records prove the operations snapshot can show "
                "human-in-the-loop control."
            ),
            evidence_refs=approval_evidence,
        ),
        ManufacturingDemoReadinessCheck(
            check_id="audit_evidence",
            label="Append-only audit evidence",
            status=_ready_if_has_records(audit_event_count),
            observed_count=audit_event_count,
            detail=(
                "Recent persisted audit events are available for walkthrough "
                "and evidence review."
            ),
            evidence_refs=audit_evidence,
        ),
        ManufacturingDemoReadinessCheck(
            check_id="workflow_replay",
            label="Replay-aware workflow state",
            status=OverviewStatus.READY if replay_ready_count > 0 else OverviewStatus.WATCH,
            observed_count=replay_ready_count,
            detail="Replay-ready active workflows are available when workflow state is pending.",
            evidence_refs=_limited_evidence_refs(
                [
                    workflow.workflow_id
                    for workflow in snapshot.active_workflows
                    if workflow.replay_ready
                ]
            ),
        ),
        ManufacturingDemoReadinessCheck(
            check_id="production_readiness_limits",
            label="Production readiness limits",
            status=OverviewStatus.WATCH,
            observed_count=len(limitations),
            detail=(
                "Enterprise production gaps are explicit before design-partner "
                "or buyer feedback."
            ),
            evidence_refs=[],
        ),
    ]
    sme_check_ids = {
        "operations_snapshot",
        "generated_artifacts",
        "human_approval_gates",
        "audit_evidence",
    }
    sme_checks = [check for check in checks if check.check_id in sme_check_ids]
    sme_status = _demo_readiness_status(sme_checks)
    readiness_status = _demo_readiness_status(checks)

    return ManufacturingDemoReadinessReport(
        tenant_id=snapshot.tenant_id,
        plant_name=snapshot.plant_name,
        scenario=snapshot.scenario,
        as_of=snapshot.as_of,
        readiness_status=readiness_status,
        summary=(
            "Axis is ready for structured SME feedback and enterprise evaluation walkthroughs, "
            "with production-readiness limits made explicit."
        ),
        tracks=[
            ManufacturingDemoReadinessTrack(
                name="SME feedback demo",
                status=sme_status,
                detail=(
                    "Use for manufacturing operations, governance, approval and audit feedback "
                    "when all core evidence checks are ready."
                ),
            ),
            ManufacturingDemoReadinessTrack(
                name="Enterprise evaluation walkthrough",
                status=OverviewStatus.WATCH,
                detail=(
                    "Use for architecture and product evaluation while production deployment "
                    "hardening remains explicit."
                ),
            ),
        ],
        checks=checks,
        limitations=limitations,
        next_actions=[
            "Run the SME walkthrough against the local Docker-backed demo stack.",
            "Collect workflow, approval and audit feedback from design partners.",
            "Prioritize Enterprise hardening only after demo feedback confirms the buying path.",
        ],
        generation_boundary="derived_from_persisted_demo_evidence",
        notes=[
            "Readiness is computed from the persisted manufacturing operations snapshot.",
            "The endpoint does not generate new artifacts, run connectors or query source systems.",
            "No browser-local mock data is used.",
        ],
    )


def _daily_brief_idempotency_key(request: DailyPlantBriefRequest) -> str:
    if request.idempotency_key is not None:
        return request.idempotency_key
    return f"{request.tenant_id}:daily-plant-brief:{request.brief_date}:{request.requested_by}"


def _daily_brief_request_fingerprint(request: DailyPlantBriefRequest) -> dict:
    return {
        "brief_date": request.brief_date,
        "requested_by": request.requested_by,
        "source_record_ids": sorted(request.source_record_ids),
        "limit": request.limit,
    }


def _evaluate_daily_brief_permission(
    request: DailyPlantBriefRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            actor_scopes=request.actor_scopes,
            required_scopes=DAILY_BRIEF_REQUIRED_SCOPES,
            relationship_scopes=[],
            attributes={
                "brief_date": request.brief_date,
                "source_record_ids": request.source_record_ids,
                "operation": "manufacturing.daily_plant_brief.generate",
            },
        )
    )
    if not decision.allowed:
        raise DailyPlantBriefPermissionDenied(decision)
    return decision


def _select_daily_brief_records(
    repository: AxisPersistenceRepository,
    request: DailyPlantBriefRequest,
) -> list[ManufacturingOperationRecordView]:
    records = [
        _operation_record_to_public(record)
        for record in repository.list_manufacturing_operation_records(
            tenant_id=request.tenant_id,
            limit=request.limit,
        )
    ]
    if request.source_record_ids:
        requested = set(request.source_record_ids)
        records = [record for record in records if record.record_id in requested]
        found = {record.record_id for record in records}
        missing = sorted(requested - found)
        if missing:
            raise DailyPlantBriefValidationError(
                "Daily plant brief source records were not found.",
                f"missing_source_records:{','.join(missing)}",
            )

    if not records:
        raise DailyPlantBriefValidationError(
            "Daily plant brief requires at least one persisted operation record.",
            "no_operation_records",
        )

    return records


def _daily_brief_summary_payload(
    *,
    request: DailyPlantBriefRequest,
    records: list[ManufacturingOperationRecordView],
) -> dict:
    action_required = [record for record in records if record.status == "action_required"]
    watch = [record for record in records if record.status == "watch"]
    domains = sorted({record.domain for record in records})
    source_systems = sorted({record.source_system for record in records})
    top_actions = [
        {
            "record_id": record.record_id,
            "domain": record.domain,
            "status": record.status,
            "owner_role": record.owner_role,
            "related_asset": record.related_asset,
            "workflow_id": record.workflow_id,
            "risk_level": record.risk_level,
        }
        for record in [*action_required, *watch][:5]
    ]
    return {
        "request": _daily_brief_request_fingerprint(request),
        "headline": (
            f"Ravenna Works has {len(action_required)} action-required and "
            f"{len(watch)} watch records across {len(domains)} operational domains."
        ),
        "summary": {
            "record_count": len(records),
            "action_required_count": len(action_required),
            "watch_count": len(watch),
            "domains": domains,
            "source_systems": source_systems,
        },
        "top_actions": top_actions,
        "cited_evidence": sorted({ref for record in records for ref in record.evidence_refs}),
        "source_records": [
            {
                "record_id": record.record_id,
                "domain": record.domain,
                "record_type": record.record_type,
                "source_system": record.source_system,
                "status": record.status,
                "occurred_at": record.occurred_at,
            }
            for record in records
        ],
        "generation_boundary": "deterministic_persisted_records",
        "notes": [
            "Generated from persisted tenant-scoped manufacturing operation records.",
            "No external model provider or source-system mutation is invoked.",
        ],
    }


def _daily_brief_id(request: DailyPlantBriefRequest, source_record_ids: list[str]) -> str:
    digest = sha256(
        "|".join([request.tenant_id, request.brief_date, *sorted(source_record_ids)]).encode()
    ).hexdigest()[:12]
    return f"brief_{request.brief_date.replace('-', '')}_{digest}"


def generate_daily_plant_brief(
    repository: AxisPersistenceRepository,
    request: DailyPlantBriefRequest,
) -> DailyPlantBriefRecord:
    idempotency_key = _daily_brief_idempotency_key(request)
    decision = _evaluate_daily_brief_permission(request)
    existing = repository.get_manufacturing_daily_brief_by_idempotency_key(
        request.tenant_id,
        idempotency_key,
    )
    if existing is not None:
        if existing.summary_payload.get("request") != _daily_brief_request_fingerprint(request):
            raise DailyPlantBriefIdempotencyConflict(existing.brief_id)
        return _brief_record_to_public(existing, idempotent_replay=True)

    records = _select_daily_brief_records(repository, request)
    source_record_ids = [record.record_id for record in records]
    summary_payload = _daily_brief_summary_payload(request=request, records=records)
    brief_id = _daily_brief_id(request, source_record_ids)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type="manufacturing.daily_brief.generated",
            payload={
                "brief_id": brief_id,
                "brief_date": request.brief_date,
                "source_record_ids": source_record_ids,
                "required_scopes": DAILY_BRIEF_REQUIRED_SCOPES,
                "permission_decision": decision.model_dump(),
            },
        )
    )
    brief = repository.create_manufacturing_daily_brief(
        ManufacturingDailyBriefCreate(
            tenant_id=request.tenant_id,
            brief_id=brief_id,
            idempotency_key=idempotency_key,
            brief_date=request.brief_date,
            requested_by=request.requested_by,
            required_scopes=DAILY_BRIEF_REQUIRED_SCOPES,
            source_record_ids=source_record_ids,
            summary_payload=summary_payload,
            permission_decision=decision.model_dump(),
            audit_event_id=audit_event.id,
        )
    )
    return _brief_record_to_public(brief, idempotent_replay=False)


def _quality_risk_idempotency_key(request: QualityRiskScenarioRequest) -> str:
    if request.idempotency_key is not None:
        return request.idempotency_key
    return f"{request.tenant_id}:quality-risk-scenario:{request.requested_by}"


def _quality_risk_request_fingerprint(request: QualityRiskScenarioRequest) -> dict:
    return {
        "requested_by": request.requested_by,
        "source_record_ids": sorted(request.source_record_ids),
        "limit": request.limit,
    }


def _evaluate_quality_risk_permission(
    request: QualityRiskScenarioRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            actor_scopes=request.actor_scopes,
            required_scopes=QUALITY_RISK_REQUIRED_SCOPES,
            relationship_scopes=[],
            attributes={
                "domain": "Quality",
                "source_record_ids": request.source_record_ids,
                "operation": "manufacturing.quality_risk_scenario.generate",
            },
        )
    )
    if not decision.allowed:
        raise QualityRiskScenarioPermissionDenied(decision)
    return decision


def _select_quality_risk_records(
    repository: AxisPersistenceRepository,
    request: QualityRiskScenarioRequest,
) -> list[ManufacturingOperationRecordView]:
    records = [
        _operation_record_to_public(record)
        for record in repository.list_manufacturing_operation_records(
            tenant_id=request.tenant_id,
            domain="Quality",
            limit=request.limit,
        )
    ]
    if request.source_record_ids:
        requested = set(request.source_record_ids)
        records = [record for record in records if record.record_id in requested]
        found = {record.record_id for record in records}
        missing = sorted(requested - found)
        if missing:
            raise QualityRiskScenarioValidationError(
                "Quality risk scenario source records were not found.",
                f"missing_source_records:{','.join(missing)}",
            )

    if not records:
        raise QualityRiskScenarioValidationError(
            "Quality risk scenario requires at least one persisted quality operation record.",
            "no_quality_operation_records",
        )
    return records


def _operation_risk_level(records: list[ManufacturingOperationRecordView]) -> str:
    risk_levels = {record.risk_level for record in records}
    if "critical" in risk_levels:
        return "critical"
    if "high" in risk_levels:
        return "high"
    if any(record.status == "action_required" for record in records):
        return "high"
    if "medium" in risk_levels or any(record.status == "watch" for record in records):
        return "medium"
    return "low"


def _quality_risk_payload(
    *,
    request: QualityRiskScenarioRequest,
    records: list[ManufacturingOperationRecordView],
    risk_level: str,
) -> dict:
    workflow_ids = sorted({record.workflow_id for record in records if record.workflow_id})
    evidence_refs = sorted({ref for record in records for ref in record.evidence_refs})
    assets = sorted({record.related_asset for record in records if record.related_asset})
    owner_roles = sorted({record.owner_role for record in records})
    return {
        "request": _quality_risk_request_fingerprint(request),
        "headline": (
            f"Quality risk scenario is {risk_level} across {len(records)} "
            "persisted quality records."
        ),
        "domain": "Quality",
        "risk_level": risk_level,
        "owner_roles": owner_roles,
        "related_assets": assets,
        "workflow_ids": workflow_ids,
        "recommended_controls": [
            "Keep quality owner review before any hold or release decision.",
            "Cite QMS and batch genealogy evidence before workflow mutation.",
            "Maintain no-external-egress policy for quality-risk analysis.",
        ],
        "cited_evidence": evidence_refs,
        "source_records": [
            {
                "record_id": record.record_id,
                "record_type": record.record_type,
                "status": record.status,
                "risk_level": record.risk_level,
                "owner_role": record.owner_role,
                "related_asset": record.related_asset,
                "workflow_id": record.workflow_id,
                "source_system": record.source_system,
                "occurred_at": record.occurred_at,
            }
            for record in records
        ],
        "generation_boundary": "deterministic_persisted_quality_records",
        "notes": [
            "Generated from persisted tenant-scoped quality operation records.",
            "No QMS mutation, model provider call or approval decision is performed.",
        ],
    }


def _quality_scenario_id(
    request: QualityRiskScenarioRequest,
    source_record_ids: list[str],
) -> str:
    digest = sha256(
        "|".join([request.tenant_id, "quality", *sorted(source_record_ids)]).encode()
    ).hexdigest()[:12]
    return f"quality_risk_{digest}"


def generate_quality_risk_scenario(
    repository: AxisPersistenceRepository,
    request: QualityRiskScenarioRequest,
) -> QualityRiskScenarioRecord:
    idempotency_key = _quality_risk_idempotency_key(request)
    decision = _evaluate_quality_risk_permission(request)
    existing = repository.get_manufacturing_risk_scenario_by_idempotency_key(
        request.tenant_id,
        idempotency_key,
    )
    if existing is not None:
        if existing.scenario_payload.get("request") != _quality_risk_request_fingerprint(
            request
        ):
            raise QualityRiskScenarioIdempotencyConflict(existing.scenario_id)
        return _risk_scenario_to_public(existing, idempotent_replay=True)

    records = _select_quality_risk_records(repository, request)
    source_record_ids = [record.record_id for record in records]
    risk_level = _operation_risk_level(records)
    scenario_id = _quality_scenario_id(request, source_record_ids)
    scenario_payload = _quality_risk_payload(
        request=request,
        records=records,
        risk_level=risk_level,
    )
    workflow_ids = sorted({record.workflow_id for record in records if record.workflow_id})
    owner_roles = sorted({record.owner_role for record in records})
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type="manufacturing.risk_scenario.generated",
            payload={
                "scenario_id": scenario_id,
                "domain": "Quality",
                "risk_level": risk_level,
                "source_record_ids": source_record_ids,
                "workflow_ids": workflow_ids,
                "required_scopes": QUALITY_RISK_REQUIRED_SCOPES,
                "permission_decision": decision.model_dump(),
            },
        )
    )
    scenario = repository.create_manufacturing_risk_scenario(
        ManufacturingRiskScenarioCreate(
            tenant_id=request.tenant_id,
            scenario_id=scenario_id,
            idempotency_key=idempotency_key,
            domain="Quality",
            risk_level=risk_level,
            requested_by=request.requested_by,
            owner_role=owner_roles[0] if owner_roles else "quality-owner",
            workflow_ids=workflow_ids,
            source_record_ids=source_record_ids,
            scenario_payload=scenario_payload,
            permission_decision=decision.model_dump(),
            audit_event_id=audit_event.id,
        )
    )
    return _risk_scenario_to_public(scenario, idempotent_replay=False)


def _maintenance_risk_idempotency_key(
    request: MaintenanceRiskScenarioRequest,
) -> str:
    if request.idempotency_key is not None:
        return request.idempotency_key
    return f"{request.tenant_id}:maintenance-risk-scenario:{request.requested_by}"


def _maintenance_risk_request_fingerprint(
    request: MaintenanceRiskScenarioRequest,
) -> dict:
    return {
        "domain": "Maintenance",
        "requested_by": request.requested_by,
        "source_record_ids": sorted(request.source_record_ids),
        "limit": request.limit,
    }


def _evaluate_maintenance_risk_permission(
    request: MaintenanceRiskScenarioRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            actor_scopes=request.actor_scopes,
            required_scopes=MAINTENANCE_RISK_REQUIRED_SCOPES,
            relationship_scopes=[],
            attributes={
                "domain": "Maintenance",
                "source_record_ids": request.source_record_ids,
                "operation": "manufacturing.maintenance_risk_scenario.generate",
            },
        )
    )
    if not decision.allowed:
        raise MaintenanceRiskScenarioPermissionDenied(decision)
    return decision


def _select_maintenance_risk_records(
    repository: AxisPersistenceRepository,
    request: MaintenanceRiskScenarioRequest,
) -> list[ManufacturingOperationRecordView]:
    records = [
        _operation_record_to_public(record)
        for record in repository.list_manufacturing_operation_records(
            tenant_id=request.tenant_id,
            domain="Maintenance",
            limit=request.limit,
        )
    ]
    if request.source_record_ids:
        requested = set(request.source_record_ids)
        records = [record for record in records if record.record_id in requested]
        found = {record.record_id for record in records}
        missing = sorted(requested - found)
        if missing:
            raise MaintenanceRiskScenarioValidationError(
                "Maintenance risk scenario source records were not found.",
                f"missing_source_records:{','.join(missing)}",
            )

    if not records:
        raise MaintenanceRiskScenarioValidationError(
            "Maintenance risk scenario requires at least one persisted maintenance "
            "operation record.",
            "no_maintenance_operation_records",
        )
    return records


def _maintenance_risk_payload(
    *,
    request: MaintenanceRiskScenarioRequest,
    records: list[ManufacturingOperationRecordView],
    risk_level: str,
) -> dict:
    workflow_ids = sorted({record.workflow_id for record in records if record.workflow_id})
    evidence_refs = sorted({ref for record in records for ref in record.evidence_refs})
    assets = sorted({record.related_asset for record in records if record.related_asset})
    owner_roles = sorted({record.owner_role for record in records})
    return {
        "request": _maintenance_risk_request_fingerprint(request),
        "headline": (
            f"Maintenance risk scenario is {risk_level} across {len(records)} "
            "persisted maintenance records."
        ),
        "domain": "Maintenance",
        "risk_level": risk_level,
        "owner_roles": owner_roles,
        "related_assets": assets,
        "workflow_ids": workflow_ids,
        "recommended_controls": [
            "Keep maintenance planner review before work-order mutation.",
            "Cite CMMS evidence and affected asset context before dispatch changes.",
            "Coordinate with production owners before schedule-impacting actions.",
        ],
        "cited_evidence": evidence_refs,
        "source_records": [
            {
                "record_id": record.record_id,
                "record_type": record.record_type,
                "status": record.status,
                "risk_level": record.risk_level,
                "owner_role": record.owner_role,
                "related_asset": record.related_asset,
                "workflow_id": record.workflow_id,
                "source_system": record.source_system,
                "occurred_at": record.occurred_at,
            }
            for record in records
        ],
        "generation_boundary": "deterministic_persisted_maintenance_records",
        "notes": [
            "Generated from persisted tenant-scoped maintenance operation records.",
            "No CMMS/MES mutation, model provider call or approval decision is performed.",
        ],
    }


def _maintenance_scenario_id(
    request: MaintenanceRiskScenarioRequest,
    source_record_ids: list[str],
) -> str:
    digest = sha256(
        "|".join([request.tenant_id, "maintenance", *sorted(source_record_ids)]).encode()
    ).hexdigest()[:12]
    return f"maintenance_risk_{digest}"


def generate_maintenance_risk_scenario(
    repository: AxisPersistenceRepository,
    request: MaintenanceRiskScenarioRequest,
) -> MaintenanceRiskScenarioRecord:
    idempotency_key = _maintenance_risk_idempotency_key(request)
    decision = _evaluate_maintenance_risk_permission(request)
    existing = repository.get_manufacturing_risk_scenario_by_idempotency_key(
        request.tenant_id,
        idempotency_key,
    )
    if existing is not None:
        fingerprint = _maintenance_risk_request_fingerprint(request)
        if existing.domain != "Maintenance" or existing.scenario_payload.get(
            "request"
        ) != fingerprint:
            raise MaintenanceRiskScenarioIdempotencyConflict(existing.scenario_id)
        replay = _risk_scenario_to_public(existing, idempotent_replay=True)
        return MaintenanceRiskScenarioRecord.model_validate(replay.model_dump())

    records = _select_maintenance_risk_records(repository, request)
    source_record_ids = [record.record_id for record in records]
    risk_level = _operation_risk_level(records)
    scenario_id = _maintenance_scenario_id(request, source_record_ids)
    scenario_payload = _maintenance_risk_payload(
        request=request,
        records=records,
        risk_level=risk_level,
    )
    workflow_ids = sorted({record.workflow_id for record in records if record.workflow_id})
    owner_roles = sorted({record.owner_role for record in records})
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type="manufacturing.risk_scenario.generated",
            payload={
                "scenario_id": scenario_id,
                "domain": "Maintenance",
                "risk_level": risk_level,
                "source_record_ids": source_record_ids,
                "workflow_ids": workflow_ids,
                "required_scopes": MAINTENANCE_RISK_REQUIRED_SCOPES,
                "permission_decision": decision.model_dump(),
            },
        )
    )
    scenario = repository.create_manufacturing_risk_scenario(
        ManufacturingRiskScenarioCreate(
            tenant_id=request.tenant_id,
            scenario_id=scenario_id,
            idempotency_key=idempotency_key,
            domain="Maintenance",
            risk_level=risk_level,
            requested_by=request.requested_by,
            owner_role=owner_roles[0] if owner_roles else "maintenance-owner",
            workflow_ids=workflow_ids,
            source_record_ids=source_record_ids,
            scenario_payload=scenario_payload,
            permission_decision=decision.model_dump(),
            audit_event_id=audit_event.id,
        )
    )
    record = _risk_scenario_to_public(scenario, idempotent_replay=False)
    return MaintenanceRiskScenarioRecord.model_validate(record.model_dump())


def _supplier_delay_idempotency_key(request: SupplierDelayScenarioRequest) -> str:
    if request.idempotency_key is not None:
        return request.idempotency_key
    return f"{request.tenant_id}:supplier-delay-scenario:{request.requested_by}"


def _supplier_delay_request_fingerprint(request: SupplierDelayScenarioRequest) -> dict:
    return {
        "domain": "Supply",
        "requested_by": request.requested_by,
        "source_record_ids": sorted(request.source_record_ids),
        "limit": request.limit,
    }


def _evaluate_supplier_delay_permission(
    request: SupplierDelayScenarioRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            actor_scopes=request.actor_scopes,
            required_scopes=SUPPLIER_DELAY_REQUIRED_SCOPES,
            relationship_scopes=[],
            attributes={
                "domain": "Supply",
                "source_record_ids": request.source_record_ids,
                "operation": "manufacturing.supplier_delay_scenario.generate",
            },
        )
    )
    if not decision.allowed:
        raise SupplierDelayScenarioPermissionDenied(decision)
    return decision


def _select_supplier_delay_records(
    repository: AxisPersistenceRepository,
    request: SupplierDelayScenarioRequest,
) -> list[ManufacturingOperationRecordView]:
    records = [
        _operation_record_to_public(record)
        for record in repository.list_manufacturing_operation_records(
            tenant_id=request.tenant_id,
            domain="Supply",
            limit=request.limit,
        )
    ]
    if request.source_record_ids:
        requested = set(request.source_record_ids)
        records = [record for record in records if record.record_id in requested]
        found = {record.record_id for record in records}
        missing = sorted(requested - found)
        if missing:
            raise SupplierDelayScenarioValidationError(
                "Supplier delay scenario source records were not found.",
                f"missing_source_records:{','.join(missing)}",
            )

    if not records:
        raise SupplierDelayScenarioValidationError(
            "Supplier delay scenario requires at least one persisted supply "
            "operation record.",
            "no_supply_operation_records",
        )
    return records


def _supplier_delay_payload(
    *,
    request: SupplierDelayScenarioRequest,
    records: list[ManufacturingOperationRecordView],
    risk_level: str,
) -> dict:
    workflow_ids = sorted({record.workflow_id for record in records if record.workflow_id})
    evidence_refs = sorted({ref for record in records for ref in record.evidence_refs})
    assets = sorted({record.related_asset for record in records if record.related_asset})
    owner_roles = sorted({record.owner_role for record in records})
    suppliers = sorted(
        {
            supplier
            for record in records
            if (supplier := record.payload.get("supplier")) is not None
        }
    )
    delay_hours = [
        hours
        for record in records
        if isinstance((hours := record.payload.get("delay_hours")), int | float)
    ]
    return {
        "request": _supplier_delay_request_fingerprint(request),
        "headline": (
            f"Supplier delay scenario is {risk_level} across {len(records)} "
            "persisted supply records."
        ),
        "domain": "Supply",
        "risk_level": risk_level,
        "owner_roles": owner_roles,
        "related_assets": assets,
        "suppliers": suppliers,
        "max_delay_hours": max(delay_hours) if delay_hours else None,
        "workflow_ids": workflow_ids,
        "recommended_controls": [
            "Keep supply planning owner review before expedite commitment.",
            "Cite Supplier Portal and ERP evidence before purchase-order mutation.",
            "Coordinate production schedule impact through workflow approval.",
        ],
        "cited_evidence": evidence_refs,
        "source_records": [
            {
                "record_id": record.record_id,
                "record_type": record.record_type,
                "status": record.status,
                "risk_level": record.risk_level,
                "owner_role": record.owner_role,
                "related_asset": record.related_asset,
                "workflow_id": record.workflow_id,
                "source_system": record.source_system,
                "occurred_at": record.occurred_at,
            }
            for record in records
        ],
        "generation_boundary": "deterministic_persisted_supply_records",
        "notes": [
            "Generated from persisted tenant-scoped supply operation records.",
            "No Supplier Portal, ERP, model provider or approval mutation is performed.",
        ],
    }


def _supplier_delay_scenario_id(
    request: SupplierDelayScenarioRequest,
    source_record_ids: list[str],
) -> str:
    digest = sha256(
        "|".join([request.tenant_id, "supplier-delay", *sorted(source_record_ids)]).encode()
    ).hexdigest()[:12]
    return f"supplier_delay_{digest}"


def generate_supplier_delay_scenario(
    repository: AxisPersistenceRepository,
    request: SupplierDelayScenarioRequest,
) -> SupplierDelayScenarioRecord:
    idempotency_key = _supplier_delay_idempotency_key(request)
    decision = _evaluate_supplier_delay_permission(request)
    existing = repository.get_manufacturing_risk_scenario_by_idempotency_key(
        request.tenant_id,
        idempotency_key,
    )
    if existing is not None:
        fingerprint = _supplier_delay_request_fingerprint(request)
        if existing.domain != "Supply" or existing.scenario_payload.get(
            "request"
        ) != fingerprint:
            raise SupplierDelayScenarioIdempotencyConflict(existing.scenario_id)
        replay = _risk_scenario_to_public(existing, idempotent_replay=True)
        return SupplierDelayScenarioRecord.model_validate(replay.model_dump())

    records = _select_supplier_delay_records(repository, request)
    source_record_ids = [record.record_id for record in records]
    risk_level = _operation_risk_level(records)
    scenario_id = _supplier_delay_scenario_id(request, source_record_ids)
    scenario_payload = _supplier_delay_payload(
        request=request,
        records=records,
        risk_level=risk_level,
    )
    workflow_ids = sorted({record.workflow_id for record in records if record.workflow_id})
    owner_roles = sorted({record.owner_role for record in records})
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type="manufacturing.risk_scenario.generated",
            payload={
                "scenario_id": scenario_id,
                "domain": "Supply",
                "risk_level": risk_level,
                "source_record_ids": source_record_ids,
                "workflow_ids": workflow_ids,
                "required_scopes": SUPPLIER_DELAY_REQUIRED_SCOPES,
                "permission_decision": decision.model_dump(),
            },
        )
    )
    scenario = repository.create_manufacturing_risk_scenario(
        ManufacturingRiskScenarioCreate(
            tenant_id=request.tenant_id,
            scenario_id=scenario_id,
            idempotency_key=idempotency_key,
            domain="Supply",
            risk_level=risk_level,
            requested_by=request.requested_by,
            owner_role=owner_roles[0] if owner_roles else "supply-planning-owner",
            workflow_ids=workflow_ids,
            source_record_ids=source_record_ids,
            scenario_payload=scenario_payload,
            permission_decision=decision.model_dump(),
            audit_event_id=audit_event.id,
        )
    )
    record = _risk_scenario_to_public(scenario, idempotent_replay=False)
    return SupplierDelayScenarioRecord.model_validate(record.model_dump())
