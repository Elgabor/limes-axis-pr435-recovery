from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from axis_api.audit import AuditEventCreate
from axis_api.connector_reference import require_persisted_manufacturing_connector_registry
from axis_api.demo import ApprovalDecision, OverviewMetric, OverviewStatus
from axis_api.manufacturing_metadata import (
    ManufacturingResponseProvenance,
    find_manufacturing_tenant_metadata,
    operational_provenance,
)
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    ApprovalDecisionRecord,
    ApprovalRecordCreate,
    AxisPersistenceRepository,
    ConnectorManualImportDecisionRecord,
    ConnectorManualImportRequestCreate,
)
from axis_api.workflow_runtime import (
    DeferredWorkflowSignalRuntime,
    WorkflowConnectorManualImportSignalRequest,
    WorkflowSignalError,
    WorkflowSignalResult,
    WorkflowSignalRuntime,
    workflow_signal_failure_result,
)


class ConnectorManualImportValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ConnectorManualImportIdempotencyConflict(ValueError):
    def __init__(self, import_id: str) -> None:
        super().__init__("Idempotency key already exists with a different payload")
        self.import_id = import_id


class ConnectorManualImportNotFound(LookupError):
    pass


class ConnectorManualImportPermissionDenied(PermissionError):
    def __init__(self, required_permission: str, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permission = required_permission
        self.decision = decision


class ConnectorManualImportQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


def _default_controls() -> list[str]:
    return [
        "approval_required",
        "workflow_signal_required",
        "idempotency_enforced",
    ]


class ConnectorManualImportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    connector_id: str = Field(default="file_csv_manufacturing_assets", min_length=1)
    import_id: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    idempotency_key: str = Field(min_length=1, max_length=200)
    import_mode: str = Field(default="manual_import_request", min_length=1, max_length=80)
    requested_by: str = Field(min_length=1, max_length=160)
    owner_role: str = Field(min_length=1, max_length=160)
    risk_level: str = Field(min_length=1, max_length=40)
    approval_id: str = Field(min_length=1, max_length=160)
    workflow_id: str = Field(min_length=1, max_length=160)
    proposal_ids: list[str] = Field(min_length=1)
    import_summary: dict[str, str] = Field(default_factory=dict)
    controls: list[str] = Field(default_factory=_default_controls)
    notes: list[str] = Field(default_factory=list)


class ConnectorManualImportDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ApprovalDecision
    actor_id: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=600)


class ConnectorManualImportRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    import_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: str = Field(min_length=1)
    import_mode: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    risk_level: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    proposal_ids: list[str] = Field(default_factory=list)
    import_summary: dict[str, str] = Field(default_factory=dict)
    controls: list[str] = Field(default_factory=list)
    graph_mutation_status: str = Field(min_length=1)
    workflow_signal_status: str = Field(min_length=1)
    decision: str | None = None
    decision_actor_id: str | None = None
    decision_note: str | None = None
    decided_at: datetime | None = None
    workflow_signal: WorkflowSignalResult | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime
    idempotent_replay: bool = False


class ConnectorManualImportDecisionResult(BaseModel):
    tenant_id: str = Field(min_length=1)
    import_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    decision: ApprovalDecision
    status: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    manual_import: ConnectorManualImportRecord
    permission_decision: PermissionDecision
    audit_event_id: UUID
    audit_event_type: str = Field(min_length=1)
    workflow_signal: WorkflowSignalResult
    workflow_signal_status: str = Field(min_length=1)


class ManufacturingConnectorManualImportRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    imports: list[ConnectorManualImportRecord] = Field(default_factory=list)
    import_notes: list[str] = Field(default_factory=list)


AUDIT_EVENT_TYPE = "connector.manual_import.requested"
DECISION_AUDIT_EVENT_TYPE = "connector.manual_import.decision_recorded"
REQUIRED_DECISION_SCOPE = "approvals:connectors:decide"
ALLOWED_IMPORT_MODES = {"manual_import_request"}
REQUEST_STATUS = "approval_required"
GRAPH_MUTATION_STATUS = "not_applied"
WORKFLOW_SIGNAL_STATUS = "pending_approval_decision"
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


def build_connector_manual_import_registry(
    repository: AxisPersistenceRepository,
    query: ConnectorManualImportQuery,
) -> ManufacturingConnectorManualImportRegistry:
    tenant_metadata = find_manufacturing_tenant_metadata(repository, query.tenant_id)
    records = repository.list_connector_manual_import_requests(
        tenant_id=query.tenant_id,
        connector_id=query.connector_id,
        status=query.status,
        limit=query.limit,
    )
    imports = [_manual_import_from_record(record) for record in records]
    approval_required = sum(1 for item in imports if item.status == REQUEST_STATUS)
    workflow_signals = sum(1 for item in imports if item.workflow_signal is not None)
    graph_mutations = sum(
        1 for item in imports if item.graph_mutation_status != GRAPH_MUTATION_STATUS
    )
    return ManufacturingConnectorManualImportRegistry(
        tenant_id=query.tenant_id,
        plant_name=tenant_metadata.plant_name,
        scenario=tenant_metadata.scenario,
        provenance=operational_provenance(bool(records)),
        registry_status=OverviewStatus.READY if imports else OverviewStatus.WATCH,
        metrics=[
            OverviewMetric(
                label="Manual Imports",
                value=str(len(imports)),
                detail="Approval-gated connector import requests",
                status=OverviewStatus.READY if imports else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Approval Required",
                value=str(approval_required),
                detail="Manual imports waiting for human decision",
                status=OverviewStatus.WATCH if approval_required else OverviewStatus.READY,
            ),
            OverviewMetric(
                label="Workflow Signals",
                value=str(workflow_signals),
                detail="Manual import decisions signaled to the workflow runtime",
                status=OverviewStatus.READY if workflow_signals else OverviewStatus.WATCH,
            ),
            OverviewMetric(
                label="Graph Mutations",
                value=str(graph_mutations),
                detail="Manual import requests do not mutate the ontology graph",
                status=OverviewStatus.READY
                if graph_mutations == 0
                else OverviewStatus.ACTION_REQUIRED,
            ),
        ],
        imports=imports,
        import_notes=[
            "Manual import requests are approval-gated metadata records.",
            "Workflow ids and signal status are recorded before any connector import can run.",
            "Idempotency keys prevent duplicate import requests and duplicate audit events.",
            "Graph mutation is only handled by the approved ontology promotion endpoint.",
        ],
    )


def record_demo_connector_manual_import(
    repository: AxisPersistenceRepository,
    request: ConnectorManualImportCreateRequest,
) -> ConnectorManualImportRecord:
    _validate_import_mode(request.import_mode)
    _validate_redacted_summary(request.import_summary)
    manifest = _active_preview_manifest_for_connector(
        repository,
        request.tenant_id,
        request.connector_id,
    )

    existing = repository.get_connector_manual_import_request_by_idempotency_key(
        request.tenant_id,
        request.idempotency_key,
    )
    if existing is not None:
        if _fingerprint_from_record(existing) != _fingerprint_from_request(request):
            raise ConnectorManualImportIdempotencyConflict(existing.import_id)
        return _manual_import_from_record(existing, idempotent_replay=True)

    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.requested_by,
            event_type=AUDIT_EVENT_TYPE,
            payload={
                "connector_id": request.connector_id,
                "import_id": request.import_id,
                "idempotency_key": request.idempotency_key,
                "status": REQUEST_STATUS,
                "import_mode": request.import_mode,
                "requested_by": request.requested_by,
                "owner_role": request.owner_role,
                "risk_level": request.risk_level,
                "approval_id": request.approval_id,
                "workflow_id": request.workflow_id,
                "proposal_ids": request.proposal_ids,
                "proposal_count": len(request.proposal_ids),
                "import_summary": request.import_summary,
                "controls": request.controls,
                "graph_mutation_status": GRAPH_MUTATION_STATUS,
                "workflow_signal_status": WORKFLOW_SIGNAL_STATUS,
                "runtime_boundary": manifest.runtime_boundary,
            },
        )
    )
    record = repository.create_connector_manual_import_request(
        ConnectorManualImportRequestCreate(
            tenant_id=request.tenant_id,
            connector_id=request.connector_id,
            import_id=request.import_id,
            idempotency_key=request.idempotency_key,
            status=REQUEST_STATUS,
            import_mode=request.import_mode,
            requested_by=request.requested_by,
            owner_role=request.owner_role,
            risk_level=request.risk_level,
            approval_id=request.approval_id,
            workflow_id=request.workflow_id,
            proposal_ids=request.proposal_ids,
            import_summary=request.import_summary,
            controls=request.controls,
            graph_mutation_status=GRAPH_MUTATION_STATUS,
            workflow_signal_status=WORKFLOW_SIGNAL_STATUS,
            audit_event_id=audit_event.id,
            audit_event_type=AUDIT_EVENT_TYPE,
            notes=request.notes,
        )
    )
    return _manual_import_from_record(record)


async def record_demo_connector_manual_import_decision(
    repository: AxisPersistenceRepository,
    import_id: str,
    request: ConnectorManualImportDecisionRequest,
    workflow_runtime: WorkflowSignalRuntime | None = None,
    tenant_id: str = "tenant_demo_manufacturing",
) -> ConnectorManualImportDecisionResult:
    manual_import = repository.get_connector_manual_import_request(tenant_id, import_id)
    if manual_import is None:
        raise ConnectorManualImportNotFound("Connector manual import request not found")

    permission_decision = _evaluate_decision_permission(manual_import, request)
    runtime = workflow_runtime or DeferredWorkflowSignalRuntime()
    _ensure_approval_record(repository, manual_import)

    repository.record_approval_decision(
        ApprovalDecisionRecord(
            tenant_id=manual_import.tenant_id,
            approval_id=manual_import.approval_id,
            decision=request.decision.value,
            decision_actor_id=request.actor_id,
            decision_note=request.note,
        )
    )
    workflow_signal = await _signal_manual_import_workflow(runtime, manual_import, request)
    status = _manual_import_status_for_decision(request.decision)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=manual_import.tenant_id,
            actor_id=request.actor_id,
            event_type=DECISION_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": manual_import.connector_id,
                "import_id": manual_import.import_id,
                "idempotency_key": manual_import.idempotency_key,
                "approval_id": manual_import.approval_id,
                "workflow_id": manual_import.workflow_id,
                "import_mode": manual_import.import_mode,
                "decision": request.decision.value,
                "status": status,
                "required_permission": REQUIRED_DECISION_SCOPE,
                "permission_decision": permission_decision.model_dump(),
                "proposal_ids": manual_import.proposal_ids,
                "proposal_count": len(manual_import.proposal_ids),
                "graph_mutation_status": GRAPH_MUTATION_STATUS,
                "workflow_signal": workflow_signal.model_dump(),
                "decision_note_recorded": str(request.note is not None).lower(),
            },
        )
    )
    updated_manual_import = repository.record_connector_manual_import_decision(
        ConnectorManualImportDecisionRecord(
            tenant_id=manual_import.tenant_id,
            import_id=manual_import.import_id,
            status=status,
            decision=request.decision.value,
            decision_actor_id=request.actor_id,
            decision_note=request.note,
            workflow_signal_status=workflow_signal.status,
            workflow_signal=workflow_signal.model_dump(),
            audit_event_id=audit_event.id,
            audit_event_type=DECISION_AUDIT_EVENT_TYPE,
        )
    )

    return ConnectorManualImportDecisionResult(
        tenant_id=manual_import.tenant_id,
        import_id=manual_import.import_id,
        approval_id=manual_import.approval_id,
        workflow_id=manual_import.workflow_id,
        decision=request.decision,
        status=status,
        actor_id=request.actor_id,
        manual_import=_manual_import_from_record(updated_manual_import),
        permission_decision=permission_decision,
        audit_event_id=audit_event.id,
        audit_event_type=audit_event.event_type,
        workflow_signal=workflow_signal,
        workflow_signal_status=workflow_signal.status,
    )


def _manual_import_from_record(
    record,
    idempotent_replay: bool = False,
) -> ConnectorManualImportRecord:
    return ConnectorManualImportRecord(
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
        decided_at=record.decided_at,
        workflow_signal=record.workflow_signal,
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        notes=record.notes,
        created_at=record.created_at,
        idempotent_replay=idempotent_replay,
    )


def _evaluate_decision_permission(
    manual_import,
    request: ConnectorManualImportDecisionRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=manual_import.tenant_id,
            actor_id=request.actor_id,
            actor_scopes=request.actor_scopes,
            required_scopes=[REQUIRED_DECISION_SCOPE],
            attributes={
                "connector_id": manual_import.connector_id,
                "import_id": manual_import.import_id,
                "approval_id": manual_import.approval_id,
                "workflow_id": manual_import.workflow_id,
                "owner_role": manual_import.owner_role,
                "risk_level": manual_import.risk_level,
                "proposal_count": len(manual_import.proposal_ids),
                "graph_mutation_status": manual_import.graph_mutation_status,
            },
        )
    )
    if not decision.allowed:
        raise ConnectorManualImportPermissionDenied(REQUIRED_DECISION_SCOPE, decision)

    return decision


def _ensure_approval_record(repository: AxisPersistenceRepository, manual_import) -> None:
    existing = repository.get_approval_record(manual_import.tenant_id, manual_import.approval_id)
    if existing is not None:
        return

    repository.create_approval_record(
        ApprovalRecordCreate(
            tenant_id=manual_import.tenant_id,
            approval_id=manual_import.approval_id,
            workflow_id=manual_import.workflow_id,
            action_id=f"connector_manual_import:{manual_import.connector_id}",
            requested_by=manual_import.requested_by,
            owner_role=manual_import.owner_role,
            risk_level=manual_import.risk_level,
            payload={
                "connector_id": manual_import.connector_id,
                "import_id": manual_import.import_id,
                "idempotency_key": manual_import.idempotency_key,
                "import_mode": manual_import.import_mode,
                "proposal_ids": manual_import.proposal_ids,
                "proposal_count": len(manual_import.proposal_ids),
                "required_permission": REQUIRED_DECISION_SCOPE,
                "graph_mutation_status": manual_import.graph_mutation_status,
                "import_summary": manual_import.import_summary,
            },
        )
    )


async def _signal_manual_import_workflow(
    workflow_runtime: WorkflowSignalRuntime,
    manual_import,
    request: ConnectorManualImportDecisionRequest,
) -> WorkflowSignalResult:
    signal_request = WorkflowConnectorManualImportSignalRequest(
        tenant_id=manual_import.tenant_id,
        workflow_id=manual_import.workflow_id,
        connector_id=manual_import.connector_id,
        import_id=manual_import.import_id,
        idempotency_key=manual_import.idempotency_key,
        approval_id=manual_import.approval_id,
        import_mode=manual_import.import_mode,
        decision=request.decision,
        proposal_ids=manual_import.proposal_ids,
        graph_mutation_status=GRAPH_MUTATION_STATUS,
    )
    try:
        return await workflow_runtime.signal_connector_manual_import(signal_request)
    except WorkflowSignalError as exc:
        return workflow_signal_failure_result(
            signal_request,
            reason=str(exc),
        )


def _manual_import_status_for_decision(decision: ApprovalDecision) -> str:
    if decision == ApprovalDecision.APPROVE:
        return "approval_approved"
    if decision == ApprovalDecision.REJECT:
        return "approval_rejected"
    return "changes_requested"


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
    raise ConnectorManualImportValidationError(
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
        raise ConnectorManualImportValidationError(
            "Connector manifest must be registered before manual import creation.",
            "connector_manifest_not_found",
        )
    # active_live is the stricter lifecycle state (it requires active_preview
    # first plus live enablement evidence). Manual import approval evidence must
    # stay recordable there so live-sync proposals can reach the promotion gate.
    if manifest.status not in {"active_preview", "active_live"}:
        raise ConnectorManualImportValidationError(
            "Connector manifest must be active_preview before manual import creation.",
            "connector_manifest_not_active_preview",
        )
    return manifest


def _validate_import_mode(import_mode: str) -> None:
    if import_mode in ALLOWED_IMPORT_MODES:
        return
    raise ConnectorManualImportValidationError(
        "Connector manual imports can only be recorded as manual_import_request.",
        "unsupported_import_mode",
    )


def _validate_redacted_summary(summary: dict[str, str]) -> None:
    for key in summary:
        if key.lower() in RAW_PAYLOAD_FIELD_NAMES:
            raise ConnectorManualImportValidationError(
                "Connector manual import summaries cannot include raw payload fields.",
                "raw_payload_field",
            )


def _fingerprint_from_request(request: ConnectorManualImportCreateRequest) -> dict:
    return {
        "connector_id": request.connector_id,
        "import_id": request.import_id,
        "import_mode": request.import_mode,
        "requested_by": request.requested_by,
        "owner_role": request.owner_role,
        "risk_level": request.risk_level,
        "approval_id": request.approval_id,
        "workflow_id": request.workflow_id,
        "proposal_ids": request.proposal_ids,
        "import_summary": request.import_summary,
        "controls": request.controls,
        "notes": request.notes,
    }


def _fingerprint_from_record(record) -> dict:
    return {
        "connector_id": record.connector_id,
        "import_id": record.import_id,
        "import_mode": record.import_mode,
        "requested_by": record.requested_by,
        "owner_role": record.owner_role,
        "risk_level": record.risk_level,
        "approval_id": record.approval_id,
        "workflow_id": record.workflow_id,
        "proposal_ids": record.proposal_ids,
        "import_summary": record.import_summary,
        "controls": record.controls,
        "notes": record.notes,
    }
