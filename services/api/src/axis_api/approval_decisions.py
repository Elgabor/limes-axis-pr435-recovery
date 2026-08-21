from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError

from axis_api.action_reference import (
    ActionReferenceRecordInvalid,
    ActionReferenceRecordNotFound,
    require_persisted_manufacturing_action_registry,
)
from axis_api.action_runs import payload_requested_amount, registry_action_entry
from axis_api.approval_reference import require_persisted_manufacturing_approval_inbox
from axis_api.audit import AuditEventCreate
from axis_api.demo import ApprovalDecision, ApprovalInboxItem
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    ActionRunCreate,
    ActionRunResultRecord,
    ApprovalDecisionOutboxCreate,
    ApprovalDecisionRecord,
    ApprovalRecordCreate,
    AxisPersistenceRepository,
    WorkflowApprovalDecisionUpdate,
)
from axis_api.platform_policies import (
    PlatformPolicyDecision,
    PlatformPolicyEvaluationContext,
    PlatformPolicyScope,
    enforce_platform_policy_deny,
)
from axis_api.workflow_history import ensure_workflow_run
from axis_api.workflow_runtime import (
    APPROVAL_DECISION_SCHEMA_VERSION,
    APPROVAL_DECISION_SIGNAL_NAME,
    DeferredWorkflowSignalRuntime,
    WorkflowSignalError,
    WorkflowSignalRequest,
    WorkflowSignalResult,
    WorkflowSignalRuntime,
    workflow_signal_failure_result,
)


class DemoApprovalNotFound(LookupError):
    pass


class ApprovalPermissionDenied(PermissionError):
    def __init__(self, required_permission: str, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permission = required_permission
        self.decision = decision


class ApprovalDecisionConflict(RuntimeError):
    def __init__(self, approval_id: str, reason: str = "approval_decision_conflict") -> None:
        super().__init__("Approval already has a terminal decision")
        self.approval_id = approval_id
        self.reason = reason


class ApprovalDecisionRequest(BaseModel):
    decision: ApprovalDecision
    actor_id: str = Field(min_length=1)
    actor_scopes: list[str] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=600)


class ApprovalDecisionPersistenceResult(BaseModel):
    tenant_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    decision: ApprovalDecision
    status: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    audit_event_id: UUID
    audit_event_type: str = Field(min_length=1)
    persisted: bool
    idempotent_replay: bool = False
    permission_decision: PermissionDecision
    workflow_signal: WorkflowSignalResult
    workflow_signal_status: str = Field(min_length=1)
    workflow_state_updated: bool
    workflow_state: str | None = None
    workflow_status: str | None = None
    action_run_recorded: bool = False
    action_run_id: UUID | None = None
    action_run_status: str | None = None
    action_run_idempotency_key: str | None = None
    action_run_idempotent_replay: bool = False
    platform_policy_decision: PlatformPolicyDecision | None = None
    decision_event_id: UUID | None = None


class ApprovalActionTransition(BaseModel):
    recorded: bool
    action_run_id: UUID | None = None
    status: str | None = None
    idempotency_key: str | None = None
    execution_mode: str | None = None
    idempotent_replay: bool = False


_APPROVAL_ACTION_IDS = {
    "appr_expedite_supplier_batch": "request_supplier_expedite",
    "appr_quality_hold_batch": "place_quality_hold",
    "appr_shift_maintenance_window": "shift_maintenance_window",
}


def _approval_action_id(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    approval_id: str,
) -> str:
    try:
        registry = require_persisted_manufacturing_action_registry(
            repository, tenant_id=tenant_id
        )
    except (ActionReferenceRecordNotFound, ActionReferenceRecordInvalid) as exc:
        if tenant_id == "tenant_demo_manufacturing":
            return _APPROVAL_ACTION_IDS.get(approval_id, approval_id)
        raise DemoApprovalNotFound("Approval action registry not found") from exc

    matches = [
        action.definition.action_id
        for action in registry.actions
        if approval_id in action.approval_refs
    ]
    if len(matches) == 1:
        return matches[0]
    if tenant_id == "tenant_demo_manufacturing":
        return _APPROVAL_ACTION_IDS.get(approval_id, approval_id)
    raise DemoApprovalNotFound("Approval action binding is missing or ambiguous")


def _approval_action_status(decision: ApprovalDecision) -> str:
    return {
        ApprovalDecision.APPROVE: "approved_for_execution",
        ApprovalDecision.REJECT: "blocked_by_rejection",
        ApprovalDecision.REQUEST_CHANGES: "changes_requested",
    }[decision]


def _approval_gate_idempotency_key(
    tenant_id: str,
    action_id: str,
    approval_id: str,
) -> str:
    return f"{tenant_id}:{action_id}:{approval_id}:approval-gate"


def _approval_gate_payload(approval: ApprovalInboxItem, action_id: str) -> dict:
    return {
        "source": "approval_decision_gate",
        "approval_id": approval.approval_id,
        "workflow_id": approval.workflow_id,
        "action_id": action_id,
        "action": approval.action,
        "summary": approval.summary,
        "risk_level": approval.risk_level,
        "requested_by": approval.requested_by,
        "owner_role": approval.owner_role,
        "required_permission": approval.required_permission,
        "model_policy": approval.model_policy,
        "evidence": approval.evidence,
        "data_accessed": approval.data_accessed,
    }


def _approval_action_result_payload(
    *,
    approval: ApprovalInboxItem,
    action_id: str,
    request: ApprovalDecisionRequest,
    workflow_signal: WorkflowSignalResult,
    workflow_state_updated: bool,
    workflow_state: str | None,
    workflow_status: str | None,
) -> dict:
    return {
        "source": "approval_decision",
        "approval_id": approval.approval_id,
        "workflow_id": approval.workflow_id,
        "action_id": action_id,
        "decision": request.decision.value,
        "decision_actor_id": request.actor_id,
        "decision_note_recorded": str(request.note is not None).lower(),
        "workflow_signal_status": workflow_signal.status,
        "workflow_state_updated": workflow_state_updated,
        "workflow_state": workflow_state,
        "workflow_status": workflow_status,
    }


def _record_approval_action_transition(
    repository: AxisPersistenceRepository,
    *,
    tenant_id: str,
    approval: ApprovalInboxItem,
    action_id: str,
    request: ApprovalDecisionRequest,
    workflow_signal: WorkflowSignalResult,
    workflow_state_updated: bool,
    workflow_state: str | None,
    workflow_status: str | None,
) -> ApprovalActionTransition:
    status = _approval_action_status(request.decision)
    result_payload = _approval_action_result_payload(
        approval=approval,
        action_id=action_id,
        request=request,
        workflow_signal=workflow_signal,
        workflow_state_updated=workflow_state_updated,
        workflow_state=workflow_state,
        workflow_status=workflow_status,
    )
    existing_runs = repository.list_action_runs_for_approval(
        tenant_id,
        action_id,
        approval.approval_id,
    )
    action_run = existing_runs[0] if existing_runs else None

    if action_run is None:
        action_run = repository.create_action_run(
            ActionRunCreate(
                tenant_id=tenant_id,
                action_id=action_id,
                idempotency_key=_approval_gate_idempotency_key(
                    tenant_id,
                    action_id,
                    approval.approval_id,
                ),
                execution_mode="approval_decision_gate",
                requested_by=approval.requested_by,
                approval_id=approval.approval_id,
                workflow_id=approval.workflow_id,
                payload=_approval_gate_payload(approval, action_id),
                status=status,
            )
        )
    elif action_run.status == status and action_run.result_payload == result_payload:
        return ApprovalActionTransition(
            recorded=True,
            action_run_id=action_run.id,
            status=action_run.status,
            idempotency_key=action_run.idempotency_key,
            execution_mode=action_run.execution_mode,
            idempotent_replay=True,
        )

    action_run = repository.record_action_run_result(
        ActionRunResultRecord(
            tenant_id=tenant_id,
            action_run_id=action_run.id,
            status=status,
            result_payload=result_payload,
        )
    )
    return ApprovalActionTransition(
        recorded=True,
        action_run_id=action_run.id,
        status=action_run.status,
        idempotency_key=action_run.idempotency_key,
        execution_mode=action_run.execution_mode,
        idempotent_replay=False,
    )


def _approval_platform_policy_context(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    approval: ApprovalInboxItem,
    action_id: str,
) -> PlatformPolicyEvaluationContext:
    action = registry_action_entry(repository, action_id, tenant_id)
    linked_runs = repository.list_action_runs_for_approval(
        tenant_id,
        action_id,
        approval.approval_id,
    )
    requested_amount = None
    requested_amount_malformed = False
    if linked_runs:
        payload = linked_runs[0].payload if isinstance(linked_runs[0].payload, dict) else {}
        input_payload = payload.get("input")
        if not isinstance(input_payload, dict):
            input_payload = {}
        requested_amount, requested_amount_malformed = payload_requested_amount(input_payload)

    return PlatformPolicyEvaluationContext(
        action_id=action_id,
        action_domain=action.definition.domain if action is not None else approval.domain,
        risk_level=(
            action.definition.risk_level.value if action is not None else approval.risk_level
        ),
        autonomy_level=action.policy.autonomy_ceiling if action is not None else None,
        requested_amount=requested_amount,
        requested_amount_malformed=requested_amount_malformed,
    )


def _enforce_approval_platform_policies(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    approval: ApprovalInboxItem,
    action_id: str,
    request: ApprovalDecisionRequest,
) -> PlatformPolicyDecision | None:
    if request.decision != ApprovalDecision.APPROVE:
        return None

    return enforce_platform_policy_deny(
        repository,
        tenant_id=tenant_id,
        actor_id=request.actor_id,
        scope=PlatformPolicyScope.ACTION_EXECUTION,
        context=_approval_platform_policy_context(repository, tenant_id, approval, action_id),
        enforcement_point="approval_decision_transition",
        audit_payload={
            "approval_id": approval.approval_id,
            "workflow_id": approval.workflow_id,
            "action_id": action_id,
            "decision": request.decision.value,
        },
    )


def _find_approval(
    repository: AxisPersistenceRepository,
    approval_id: str,
    tenant_id: str,
) -> tuple[str, ApprovalInboxItem]:
    inbox = require_persisted_manufacturing_approval_inbox(
        repository, tenant_id=tenant_id
    )
    for approval in inbox.approvals:
        if approval.approval_id == approval_id:
            return inbox.tenant_id, approval

    raise DemoApprovalNotFound("Approval not found")


def _ensure_approval_record(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    approval: ApprovalInboxItem,
    action_id: str,
) -> None:
    existing = repository.get_approval_record(tenant_id, approval.approval_id)
    if existing is not None:
        return

    repository.create_approval_record(
        ApprovalRecordCreate(
            tenant_id=tenant_id,
            approval_id=approval.approval_id,
            workflow_id=approval.workflow_id,
            action_id=action_id,
            requested_by=approval.requested_by,
            owner_role=approval.owner_role,
            risk_level=approval.risk_level,
            payload={
                "action": approval.action,
                "summary": approval.summary,
                "required_permission": approval.required_permission,
                "model_policy": approval.model_policy,
                "estimated_cost": approval.estimated_cost,
                "audit_event_preview": approval.audit_event_preview.model_dump(),
            },
        )
    )


def _evaluate_approval_decision_permission(
    tenant_id: str,
    approval: ApprovalInboxItem,
    request: ApprovalDecisionRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=tenant_id,
            actor_id=request.actor_id,
            actor_scopes=request.actor_scopes,
            required_scopes=[approval.required_permission],
            attributes={
                "approval_id": approval.approval_id,
                "workflow_id": approval.workflow_id,
                "domain": approval.domain,
                "owner_role": approval.owner_role,
                "risk_level": approval.risk_level,
            },
        )
    )
    if not decision.allowed:
        raise ApprovalPermissionDenied(approval.required_permission, decision)

    return decision


async def _signal_approval_workflow(
    workflow_runtime: WorkflowSignalRuntime,
    tenant_id: str,
    approval: ApprovalInboxItem,
    request: ApprovalDecisionRequest,
) -> WorkflowSignalResult:
    signal_request = WorkflowSignalRequest(
        tenant_id=tenant_id,
        workflow_id=approval.workflow_id,
        approval_id=approval.approval_id,
        decision=request.decision,
        actor_id=request.actor_id,
        note=request.note,
        decided_at=datetime.now(UTC),
    )
    try:
        return await workflow_runtime.signal_approval_decision(signal_request)
    except WorkflowSignalError as exc:
        return workflow_signal_failure_result(signal_request, reason=str(exc))


async def record_demo_approval_decision(
    repository: AxisPersistenceRepository,
    approval_id: str,
    request: ApprovalDecisionRequest,
    workflow_runtime: WorkflowSignalRuntime | None = None,
    *,
    tenant_id: str = "tenant_demo_manufacturing",
    workflow_history_persistence_enabled: bool = False,
    workflow_signal_outbox_enabled: bool = False,
) -> ApprovalDecisionPersistenceResult:
    tenant_id, approval = _find_approval(repository, approval_id, tenant_id)
    action_id = _approval_action_id(repository, tenant_id, approval.approval_id)
    permission_decision = _evaluate_approval_decision_permission(tenant_id, approval, request)
    runtime = workflow_runtime or DeferredWorkflowSignalRuntime()
    repository.acquire_approval_decision_lock(tenant_id, approval.approval_id)
    existing = repository.get_approval_record(tenant_id, approval.approval_id)
    if existing is not None and existing.decision is not None:
        same_request = (
            existing.decision == request.decision.value
            and existing.decision_actor_id == request.actor_id
            and existing.decision_note == request.note
        )
        snapshot = existing.payload.get("decision_result")
        if same_request and isinstance(snapshot, dict):
            try:
                result = ApprovalDecisionPersistenceResult.model_validate(snapshot)
            except ValidationError as exc:
                raise ApprovalDecisionConflict(
                    approval.approval_id, "approval_replay_unavailable"
                ) from exc
            return result.model_copy(update={"idempotent_replay": True})
        if same_request:
            raise ApprovalDecisionConflict(
                approval.approval_id, "approval_replay_unavailable"
            )
        raise ApprovalDecisionConflict(approval.approval_id)

    platform_policy_decision = _enforce_approval_platform_policies(
        repository,
        tenant_id,
        approval,
        action_id,
        request,
    )
    if existing is None:
        _ensure_approval_record(repository, tenant_id, approval, action_id)

    approval_record = repository.record_approval_decision(
        ApprovalDecisionRecord(
            tenant_id=tenant_id,
            approval_id=approval.approval_id,
            decision=request.decision.value,
            decision_actor_id=request.actor_id,
            decision_note=request.note,
        )
    )
    decision_outbox = None
    if workflow_signal_outbox_enabled:
        decision_event_id = uuid4()
        decided_at = datetime.now(UTC)
        outbox_payload = WorkflowSignalRequest(
            tenant_id=tenant_id,
            workflow_id=approval.workflow_id,
            approval_id=approval.approval_id,
            decision=request.decision,
            decision_event_id=decision_event_id,
            actor_id=request.actor_id,
            note=request.note,
            decided_at=decided_at,
            signal_name=APPROVAL_DECISION_SIGNAL_NAME,
        ).runtime_payload
        decision_outbox = repository.create_approval_decision_outbox(
            ApprovalDecisionOutboxCreate(
                id=decision_event_id,
                tenant_id=tenant_id,
                approval_id=approval.approval_id,
                workflow_id=approval.workflow_id,
                signal_name=APPROVAL_DECISION_SIGNAL_NAME,
                schema_version=APPROVAL_DECISION_SCHEMA_VERSION,
                decision=request.decision.value,
                decision_actor_id=request.actor_id,
                payload=outbox_payload,
                available_at=decided_at,
            )
        )
        workflow_signal = WorkflowSignalResult(
            workflow_id=approval.workflow_id,
            status="approval_signal_queued",
            adapter="axis-transactional-outbox",
            signal_name=APPROVAL_DECISION_SIGNAL_NAME,
            payload={
                "approval_id": approval.approval_id,
                "approved": request.decision == ApprovalDecision.APPROVE,
                "decision": request.decision.value,
                "decision_event_id": str(decision_outbox.id),
            },
        )
    else:
        workflow_signal = await _signal_approval_workflow(runtime, tenant_id, approval, request)
    if workflow_history_persistence_enabled:
        ensure_workflow_run(repository, tenant_id, approval.workflow_id)
    workflow_run = repository.record_workflow_approval_decision(
        WorkflowApprovalDecisionUpdate(
            tenant_id=tenant_id,
            workflow_id=approval.workflow_id,
            approval_id=approval.approval_id,
            decision=request.decision.value,
            actor_id=request.actor_id,
        )
    )
    action_transition = _record_approval_action_transition(
        repository,
        tenant_id=tenant_id,
        approval=approval,
        action_id=action_id,
        request=request,
        workflow_signal=workflow_signal,
        workflow_state_updated=workflow_run is not None,
        workflow_state=workflow_run.state if workflow_run is not None else None,
        workflow_status=workflow_run.status if workflow_run is not None else None,
    )
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=tenant_id,
            actor_id=request.actor_id,
            event_type="approval.decision.recorded",
            payload={
                "approval_id": approval.approval_id,
                "workflow_id": approval.workflow_id,
                "action_id": action_id,
                "decision": request.decision.value,
                "required_permission": approval.required_permission,
                "permission_decision": permission_decision.model_dump(),
                "workflow_signal": workflow_signal.model_dump(),
                "workflow_state_updated": workflow_run is not None,
                "workflow_state": workflow_run.state if workflow_run is not None else None,
                "workflow_status": workflow_run.status if workflow_run is not None else None,
                "action_run": {
                    "action_run_id": (
                        str(action_transition.action_run_id)
                        if action_transition.action_run_id is not None
                        else None
                    ),
                    "idempotency_key": action_transition.idempotency_key,
                    "status": action_transition.status,
                    "execution_mode": action_transition.execution_mode,
                    "recorded": action_transition.recorded,
                    "idempotent_replay": action_transition.idempotent_replay,
                },
                "result": approval.audit_event_preview.result,
                "decision_note_recorded": str(request.note is not None).lower(),
                "platform_policy_decision": (
                    platform_policy_decision.model_dump()
                    if platform_policy_decision is not None and platform_policy_decision.matched
                    else None
                ),
            },
        )
    )

    result = ApprovalDecisionPersistenceResult(
        tenant_id=tenant_id,
        approval_id=approval.approval_id,
        workflow_id=approval.workflow_id,
        action_id=action_id,
        decision=request.decision,
        status=approval_record.status,
        actor_id=request.actor_id,
        audit_event_id=audit_event.id,
        audit_event_type=audit_event.event_type,
        persisted=True,
        permission_decision=permission_decision,
        workflow_signal=workflow_signal,
        workflow_signal_status=workflow_signal.status,
        workflow_state_updated=workflow_run is not None,
        workflow_state=workflow_run.state if workflow_run is not None else None,
        workflow_status=workflow_run.status if workflow_run is not None else None,
        action_run_recorded=action_transition.recorded,
        action_run_id=action_transition.action_run_id,
        action_run_status=action_transition.status,
        action_run_idempotency_key=action_transition.idempotency_key,
        action_run_idempotent_replay=action_transition.idempotent_replay,
        platform_policy_decision=platform_policy_decision,
        decision_event_id=decision_outbox.id if decision_outbox is not None else None,
    )
    approval_record.payload = {
        **approval_record.payload,
        "decision_result": result.model_dump(mode="json"),
    }
    repository.session.flush()
    return result
