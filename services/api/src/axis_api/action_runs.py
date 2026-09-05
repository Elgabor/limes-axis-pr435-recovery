import math
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from axis_api.action_reference import (
    ActionReferenceRecordInvalid,
    ActionReferenceRecordNotFound,
    require_persisted_manufacturing_action_registry,
)
from axis_api.audit import AuditEventCreate
from axis_api.demo import ActionRegistryEntry
from axis_api.ontology_reference import require_persisted_manufacturing_ontology
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    ActionRunCreate,
    ActionRunResultRecord,
    AxisPersistenceRepository,
    WorkflowActionRunOutcomeUpdate,
    WorkflowActionRunUpdate,
)
from axis_api.platform_policies import (
    PlatformPolicyDecision,
    PlatformPolicyEffect,
    PlatformPolicyEvaluationContext,
    PlatformPolicyScope,
    enforce_platform_policy_deny,
)
from axis_api.workflow_history import ensure_workflow_run
from axis_api.workflow_runtime import (
    DeferredWorkflowSignalRuntime,
    WorkflowActionSignalRequest,
    WorkflowSignalError,
    WorkflowSignalResult,
    WorkflowSignalRuntime,
    workflow_signal_failure_result,
)


class DemoActionNotFound(LookupError):
    pass


class DemoActionRunNotFound(LookupError):
    pass


class ActionPayloadValidationError(ValueError):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("Action payload validation failed")
        self.issues = issues


class ActionPermissionDenied(PermissionError):
    def __init__(self, required_permissions: list[str], decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permissions = required_permissions
        self.decision = decision


class ActionRunIdempotencyConflict(ValueError):
    def __init__(self, action_run_id: UUID) -> None:
        super().__init__("Idempotency key already exists with a different payload")
        self.action_run_id = action_run_id


class ActionRunOutcomeValidationError(ValueError):
    def __init__(self, issues: list[str]) -> None:
        super().__init__("Action run outcome validation failed")
        self.issues = issues


class ActionRunOutcomePermissionDenied(PermissionError):
    def __init__(self, required_permission: str, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permission = required_permission
        self.decision = decision


class ActionRunOutcomeConflict(ValueError):
    def __init__(self, action_run_id: UUID, reason: str) -> None:
        super().__init__(reason)
        self.action_run_id = action_run_id
        self.reason = reason


class ActionRunRequest(BaseModel):
    actor_id: str = Field(min_length=1)
    actor_scopes: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    payload: dict = Field(default_factory=dict)


class ActionRunPersistenceResult(BaseModel):
    tenant_id: str = Field(min_length=1)
    action_run_id: UUID
    action_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: str = Field(min_length=1)
    execution_mode: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    approval_required: bool
    approval_id: str | None = None
    workflow_id: str | None = None
    persisted: bool
    idempotent_replay: bool
    permission_decision: PermissionDecision
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None
    workflow_signal: WorkflowSignalResult | None = None
    workflow_signal_status: str = Field(default="not_required", min_length=1)
    workflow_state_updated: bool = False
    workflow_state: str | None = None
    workflow_status: str | None = None
    platform_policy_decision: PlatformPolicyDecision | None = None


class ActionRunQuery(BaseModel):
    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    action_id: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=100, ge=1, le=200)


class ActionRunOutcomeRecord(BaseModel):
    result_summary: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class ActionRunRecord(BaseModel):
    action_run_id: UUID
    action_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    approval_id: str | None = None
    workflow_id: str | None = None
    created_at: datetime
    updated_at: datetime
    waiting_duration_seconds: int = Field(ge=0)
    outcome: ActionRunOutcomeRecord | None = None


class ActionRunList(BaseModel):
    tenant_id: str = Field(min_length=1)
    runs: list[ActionRunRecord] = Field(default_factory=list)


class ActionRunOutcomeRequest(BaseModel):
    actor_id: str = Field(min_length=1)
    actor_scopes: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=200)
    status: str = Field(min_length=1)
    result_summary: str = Field(min_length=1, max_length=800)
    evidence_refs: list[str] = Field(min_length=1)
    metrics: dict = Field(default_factory=dict)
    external_mutation_started: bool = False


class ActionRunOutcomePersistenceResult(BaseModel):
    tenant_id: str = Field(min_length=1)
    action_run_id: UUID
    action_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: str = Field(min_length=1)
    execution_mode: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    approval_id: str | None = None
    workflow_id: str | None = None
    result_summary: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    persisted: bool
    idempotent_replay: bool
    permission_decision: PermissionDecision
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None
    workflow_state_updated: bool = False
    workflow_state: str | None = None
    workflow_status: str | None = None


ACTION_RUN_OUTCOME_RECORD_SCOPE = "actions:result:record"
ACTION_RUN_OUTCOME_STATUSES = {
    "dry_run_completed",
    "execution_completed",
    "execution_failed",
    "execution_blocked",
}
ACTION_RUN_TERMINAL_OUTCOME_STATUSES = ACTION_RUN_OUTCOME_STATUSES
EXECUTION_ADVANCING_OUTCOME_STATUSES = {
    "dry_run_completed",
    "execution_completed",
}


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _listed_outcome(result_payload: object) -> ActionRunOutcomeRecord | None:
    if not isinstance(result_payload, dict):
        return None
    if result_payload.get("source") != "action_run_outcome":
        return None

    result_summary = result_payload.get("result_summary")
    evidence_refs = result_payload.get("evidence_refs")
    if not isinstance(result_summary, str) or not result_summary:
        return None
    if not isinstance(evidence_refs, list) or not all(
        isinstance(reference, str) for reference in evidence_refs
    ):
        return None
    return ActionRunOutcomeRecord(
        result_summary=result_summary,
        evidence_refs=evidence_refs,
    )


def list_action_run_records(
    repository: AxisPersistenceRepository,
    query: ActionRunQuery,
    *,
    observed_at: datetime | None = None,
) -> ActionRunList:
    records = repository.list_action_runs(
        tenant_id=query.tenant_id,
        action_id=query.action_id,
        status=query.status,
        limit=query.limit,
    )
    now = _ensure_utc(observed_at or datetime.now(UTC))
    runs: list[ActionRunRecord] = []
    for record in records:
        created_at = _ensure_utc(record.created_at)
        # Waiting time is derived because a stored moving duration would become stale.
        waiting_duration_seconds = max(0, int((now - created_at).total_seconds()))
        runs.append(
            ActionRunRecord(
                action_run_id=record.id,
                action_id=record.action_id,
                status=record.status,
                approval_id=record.approval_id,
                workflow_id=record.workflow_id,
                created_at=created_at,
                updated_at=_ensure_utc(record.updated_at),
                waiting_duration_seconds=waiting_duration_seconds,
                outcome=_listed_outcome(record.result_payload),
            )
        )

    # Listing only reads governed state; execution remains the external executor's boundary.
    return ActionRunList(tenant_id=query.tenant_id, runs=runs)


def _find_action(
    repository: AxisPersistenceRepository,
    action_id: str,
    tenant_id: str,
) -> tuple[str, ActionRegistryEntry, str]:
    registry = require_persisted_manufacturing_action_registry(
        repository, tenant_id=tenant_id
    )
    for action in registry.actions:
        if action.definition.action_id == action_id:
            return registry.tenant_id, action, registry.schema_version

    raise DemoActionNotFound("Action not found")


def _field_type_matches(value: object, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str) and value != ""
    if expected_type == "array":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        # bool is an int subclass in Python but not an integer in a schema.
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        # Numeric strings are NOT accepted for schema-declared numeric fields;
        # only fields declared as "string" carry string-encoded numbers (the
        # policy layer then parses them and fails closed on garbage). NaN and
        # infinities are rejected outright.
        return (
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    if expected_type == "object":
        return isinstance(value, dict)
    return True


def _validate_payload(action: ActionRegistryEntry, payload: dict) -> None:
    schema = action.definition.input_schema
    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))
    issues: list[str] = []

    for field_name in required_fields:
        if field_name not in payload:
            issues.append(f"missing_required:{field_name}")

    for field_name, value in payload.items():
        field_schema = properties.get(field_name)
        if field_schema is None:
            issues.append(f"unknown_field:{field_name}")
            continue

        expected_type = field_schema.get("type")
        if expected_type and not _field_type_matches(value, expected_type):
            issues.append(f"invalid_type:{field_name}:{expected_type}")

    if issues:
        raise ActionPayloadValidationError(issues)


def _payload_ontology_refs(action: ActionRegistryEntry, payload: dict) -> list[str]:
    properties = action.definition.input_schema.get("properties", {})
    refs: set[str] = set()
    for field_name, field_schema in properties.items():
        if not isinstance(field_schema, dict) or not field_schema.get("x-axis-ontology-ref"):
            continue

        value = payload.get(field_name)
        if isinstance(value, str) and value:
            refs.add(value)
        elif isinstance(value, list):
            refs.update(item for item in value if isinstance(item, str) and item)

    return sorted(refs)


def _relationship_scopes_for_refs(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    resource_refs: list[str],
) -> list[str]:
    if not resource_refs:
        return []

    ref_ids = set(resource_refs)
    ontology = require_persisted_manufacturing_ontology(
        repository, tenant_id=tenant_id
    )
    return sorted(
        {
            relationship.permission_scope
            for relationship in ontology.relationships
            if relationship.source_id in ref_ids or relationship.target_id in ref_ids
        }
    )


def _evaluate_action_permission(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    action: ActionRegistryEntry,
    request: ActionRunRequest,
) -> tuple[PermissionDecision, list[str]]:
    resource_refs = _payload_ontology_refs(action, request.payload)
    relationship_scopes = _relationship_scopes_for_refs(repository, tenant_id, resource_refs)
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=tenant_id,
            actor_id=request.actor_id,
            actor_scopes=request.actor_scopes,
            required_scopes=action.definition.required_permissions,
            relationship_scopes=relationship_scopes,
            attributes={
                "action_id": action.definition.action_id,
                "domain": action.definition.domain,
                "risk_level": action.definition.risk_level.value,
                "approval_mode": action.definition.approval_mode.value,
                "owner_role": action.owner_role,
                "execution_mode": action.policy.execution_mode,
                "resource_refs": resource_refs,
                "relationship_scopes": relationship_scopes,
            },
        )
    )
    if not decision.allowed:
        raise ActionPermissionDenied(
            sorted(set(action.definition.required_permissions) | set(relationship_scopes)),
            decision,
        )

    return decision, relationship_scopes


def _action_status(action: ActionRegistryEntry, approval_required: bool) -> str:
    if approval_required:
        return "approval_required"
    return "preview_generated"


def payload_requested_amount(payload: dict) -> tuple[float | None, bool]:
    """Parse the amount-like payload field into (amount, malformed).

    A missing or null field is treated as absent. A present value that is not
    a finite non-negative number is reported as malformed so amount-conditioned
    policies can fail closed instead of being evaded.
    """
    if "requested_amount" not in payload:
        return None, False

    value = payload["requested_amount"]
    if value is None:
        return None, False
    if isinstance(value, bool):
        return None, True
    if isinstance(value, int | float):
        amount = float(value)
    elif isinstance(value, str):
        try:
            amount = float(value)
        except ValueError:
            return None, True
    else:
        return None, True

    if not math.isfinite(amount) or amount < 0:
        return None, True
    return amount, False


def registry_action_entry(
    repository: AxisPersistenceRepository,
    action_id: str,
    tenant_id: str = "tenant_demo_manufacturing",
) -> ActionRegistryEntry | None:
    try:
        _, action, _ = _find_action(repository, action_id, tenant_id)
    except (DemoActionNotFound, ActionReferenceRecordInvalid, ActionReferenceRecordNotFound):
        return None
    return action


def _platform_policy_context(
    action: ActionRegistryEntry,
    request: ActionRunRequest,
) -> PlatformPolicyEvaluationContext:
    requested_amount, requested_amount_malformed = payload_requested_amount(request.payload)
    return PlatformPolicyEvaluationContext(
        action_id=action.definition.action_id,
        action_domain=action.definition.domain,
        risk_level=action.definition.risk_level.value,
        autonomy_level=action.policy.autonomy_ceiling,
        requested_amount=requested_amount,
        requested_amount_malformed=requested_amount_malformed,
    )


def _enforce_platform_policies(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    action: ActionRegistryEntry,
    request: ActionRunRequest,
    idempotency_key: str,
) -> PlatformPolicyDecision:
    return enforce_platform_policy_deny(
        repository,
        tenant_id=tenant_id,
        actor_id=request.actor_id,
        scope=PlatformPolicyScope.ACTION_EXECUTION,
        context=_platform_policy_context(action, request),
        enforcement_point="action_run_creation",
        audit_payload={
            "action_id": action.definition.action_id,
            "idempotency_key": idempotency_key,
        },
    )


def _outcome_platform_policy_context(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    action_run,
) -> tuple[PlatformPolicyEvaluationContext, bool]:
    action = registry_action_entry(repository, action_run.action_id, tenant_id)
    context_degraded = action is None

    payload = action_run.payload if isinstance(action_run.payload, dict) else {}
    input_payload = payload.get("input")
    if not isinstance(input_payload, dict):
        input_payload = {}
    requested_amount, requested_amount_malformed = payload_requested_amount(input_payload)
    context = PlatformPolicyEvaluationContext(
        action_id=action_run.action_id,
        action_domain=action.definition.domain if action is not None else None,
        risk_level=action.definition.risk_level.value if action is not None else None,
        autonomy_level=action.policy.autonomy_ceiling if action is not None else None,
        requested_amount=requested_amount,
        requested_amount_malformed=requested_amount_malformed,
    )
    return context, context_degraded


def _enforce_outcome_platform_policies(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    action_run,
    request: ActionRunOutcomeRequest,
) -> bool:
    if request.status not in EXECUTION_ADVANCING_OUTCOME_STATUSES:
        return False

    context, context_degraded = _outcome_platform_policy_context(
        repository,
        tenant_id,
        action_run,
    )
    enforce_platform_policy_deny(
        repository,
        tenant_id=tenant_id,
        actor_id=request.actor_id,
        scope=PlatformPolicyScope.ACTION_EXECUTION,
        context=context,
        enforcement_point="action_run_outcome",
        audit_payload={
            "action_id": action_run.action_id,
            "action_run_id": str(action_run.id),
            "idempotency_key": request.idempotency_key,
            "outcome_status": request.status,
            "context_degraded": context_degraded,
        },
        context_degraded=context_degraded,
    )
    return context_degraded


def _idempotency_key(
    tenant_id: str,
    action: ActionRegistryEntry,
    request: ActionRunRequest,
) -> str:
    if request.idempotency_key:
        return request.idempotency_key

    if action.policy.idempotency_required:
        raise ActionPayloadValidationError(["missing_idempotency_key"])

    return f"{tenant_id}:{action.definition.action_id}:{request.actor_id}:preview"


def _stored_payload(
    action: ActionRegistryEntry,
    request: ActionRunRequest,
    schema_version: str,
) -> dict:
    return {
        "input": request.payload,
        "schema_version": schema_version,
        "dry_run": action.policy.dry_run_supported,
    }


def _should_signal_workflow(action: ActionRegistryEntry) -> bool:
    return (
        bool(action.workflow_bindings) and action.policy.runtime_adapter == "axis-temporal-adapter"
    )


def _workflow_signal_status(workflow_signal: WorkflowSignalResult | None) -> str:
    if workflow_signal is None:
        return "not_required"
    return workflow_signal.status


def _outcome_permission_decision(
    tenant_id: str,
    request: ActionRunOutcomeRequest,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=tenant_id,
            actor_id=request.actor_id,
            actor_scopes=request.actor_scopes,
            required_scopes=[ACTION_RUN_OUTCOME_RECORD_SCOPE],
            attributes={"operation": "record_action_run_outcome"},
        )
    )
    if not decision.allowed:
        raise ActionRunOutcomePermissionDenied(ACTION_RUN_OUTCOME_RECORD_SCOPE, decision)

    return decision


def _validate_outcome_request(action_status: str, request: ActionRunOutcomeRequest) -> None:
    issues: list[str] = []
    if request.status not in ACTION_RUN_OUTCOME_STATUSES:
        issues.append(f"invalid_status:{request.status}")
    if request.external_mutation_started:
        issues.append("external_mutation_not_enabled")
    if action_status == "approval_required":
        issues.append("approval_required_before_outcome")

    if issues:
        raise ActionRunOutcomeValidationError(issues)


def _outcome_payload(request: ActionRunOutcomeRequest) -> dict:
    return {
        "source": "action_run_outcome",
        "outcome_idempotency_key": request.idempotency_key,
        "status": request.status,
        "result_summary": request.result_summary,
        "evidence_refs": request.evidence_refs,
        "metrics": request.metrics,
        "external_mutation_started": request.external_mutation_started,
        "recorded_by": request.actor_id,
    }


async def _signal_action_workflow(
    workflow_runtime: WorkflowSignalRuntime,
    *,
    tenant_id: str,
    action: ActionRegistryEntry,
    action_run_id: UUID,
    idempotency_key: str,
    request: ActionRunRequest,
) -> WorkflowSignalResult | None:
    if not _should_signal_workflow(action):
        return None

    signal_request = WorkflowActionSignalRequest(
        tenant_id=tenant_id,
        workflow_id=action.workflow_bindings[0],
        action_id=action.definition.action_id,
        action_run_id=action_run_id,
        idempotency_key=idempotency_key,
        approval_id=action.approval_refs[0] if action.approval_refs else None,
        execution_mode=action.policy.execution_mode,
        payload=request.payload,
    )
    try:
        return await workflow_runtime.signal_action_run(signal_request)
    except WorkflowSignalError as exc:
        return workflow_signal_failure_result(signal_request, reason=str(exc))


def _result_from_action_run(
    *,
    tenant_id: str,
    action: ActionRegistryEntry,
    action_run_id: UUID,
    idempotency_key: str,
    status: str,
    requested_by: str,
    permission_decision: PermissionDecision,
    audit_event_id: UUID | None,
    audit_event_type: str | None,
    idempotent_replay: bool,
    approval_required: bool | None = None,
    workflow_signal: WorkflowSignalResult | None = None,
    workflow_signal_status: str | None = None,
    workflow_state_updated: bool = False,
    workflow_state: str | None = None,
    workflow_status: str | None = None,
    platform_policy_decision: PlatformPolicyDecision | None = None,
) -> ActionRunPersistenceResult:
    return ActionRunPersistenceResult(
        tenant_id=tenant_id,
        action_run_id=action_run_id,
        action_id=action.definition.action_id,
        idempotency_key=idempotency_key,
        status=status,
        execution_mode=action.policy.execution_mode,
        requested_by=requested_by,
        approval_required=(
            approval_required
            if approval_required is not None
            else action.definition.requires_approval
        ),
        approval_id=action.approval_refs[0] if action.approval_refs else None,
        workflow_id=action.workflow_bindings[0] if action.workflow_bindings else None,
        persisted=True,
        idempotent_replay=idempotent_replay,
        permission_decision=permission_decision,
        audit_event_id=audit_event_id,
        audit_event_type=audit_event_type,
        workflow_signal=workflow_signal,
        workflow_signal_status=workflow_signal_status or _workflow_signal_status(workflow_signal),
        workflow_state_updated=workflow_state_updated,
        workflow_state=workflow_state,
        workflow_status=workflow_status,
        platform_policy_decision=platform_policy_decision,
    )


async def record_demo_action_run_outcome(
    repository: AxisPersistenceRepository,
    action_run_id: UUID | str,
    request: ActionRunOutcomeRequest,
    *,
    tenant_id: str = "tenant_demo_manufacturing",
    workflow_history_persistence_enabled: bool = False,
) -> ActionRunOutcomePersistenceResult:
    try:
        action_run_uuid = action_run_id if isinstance(action_run_id, UUID) else UUID(action_run_id)
    except ValueError as exc:
        raise DemoActionRunNotFound("Action run not found") from exc

    action_run = repository.get_action_run(tenant_id, action_run_uuid)
    if action_run is None:
        raise DemoActionRunNotFound("Action run not found")

    permission_decision = _outcome_permission_decision(tenant_id, request)
    _validate_outcome_request(action_run.status, request)
    payload = _outcome_payload(request)
    existing_payload = action_run.result_payload or {}
    existing_key = existing_payload.get("outcome_idempotency_key")

    if existing_key == request.idempotency_key:
        if existing_payload != payload:
            raise ActionRunOutcomeConflict(action_run.id, "outcome_idempotency_conflict")
        return ActionRunOutcomePersistenceResult(
            tenant_id=tenant_id,
            action_run_id=action_run.id,
            action_id=action_run.action_id,
            idempotency_key=request.idempotency_key,
            status=action_run.status,
            execution_mode=action_run.execution_mode,
            requested_by=action_run.requested_by,
            approval_id=action_run.approval_id,
            workflow_id=action_run.workflow_id,
            result_summary=request.result_summary,
            evidence_refs=request.evidence_refs,
            persisted=True,
            idempotent_replay=True,
            permission_decision=permission_decision,
        )
    if existing_key is not None or action_run.status in ACTION_RUN_TERMINAL_OUTCOME_STATUSES:
        raise ActionRunOutcomeConflict(action_run.id, "action_run_outcome_already_recorded")

    platform_policy_context_degraded = _enforce_outcome_platform_policies(
        repository,
        tenant_id,
        action_run,
        request,
    )
    action_run = repository.record_action_run_result(
        ActionRunResultRecord(
            tenant_id=tenant_id,
            action_run_id=action_run.id,
            status=request.status,
            result_payload=payload,
        )
    )
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=tenant_id,
            actor_id=request.actor_id,
            event_type="action.run.outcome.recorded",
            payload={
                "action_run_id": str(action_run.id),
                "action_id": action_run.action_id,
                "idempotency_key": request.idempotency_key,
                "status": request.status,
                "execution_mode": action_run.execution_mode,
                "approval_id": action_run.approval_id,
                "workflow_id": action_run.workflow_id,
                "result_summary": request.result_summary,
                "evidence_refs": request.evidence_refs,
                "metric_names": sorted(request.metrics.keys()),
                "external_mutation_started": request.external_mutation_started,
                "permission_decision": permission_decision.model_dump(),
                "platform_policy_context_degraded": platform_policy_context_degraded,
            },
        )
    )
    workflow_run = None
    if action_run.workflow_id is not None:
        if workflow_history_persistence_enabled:
            ensure_workflow_run(repository, tenant_id, action_run.workflow_id)
        workflow_run = repository.record_workflow_action_run_outcome(
            WorkflowActionRunOutcomeUpdate(
                tenant_id=tenant_id,
                workflow_id=action_run.workflow_id,
                action_id=action_run.action_id,
                action_run_id=action_run.id,
                idempotency_key=request.idempotency_key,
                actor_id=request.actor_id,
                status=request.status,
                result_summary=request.result_summary,
            )
        )

    return ActionRunOutcomePersistenceResult(
        tenant_id=tenant_id,
        action_run_id=action_run.id,
        action_id=action_run.action_id,
        idempotency_key=request.idempotency_key,
        status=action_run.status,
        execution_mode=action_run.execution_mode,
        requested_by=action_run.requested_by,
        approval_id=action_run.approval_id,
        workflow_id=action_run.workflow_id,
        result_summary=request.result_summary,
        evidence_refs=request.evidence_refs,
        persisted=True,
        idempotent_replay=False,
        permission_decision=permission_decision,
        audit_event_id=audit_event.id,
        audit_event_type=audit_event.event_type,
        workflow_state_updated=workflow_run is not None,
        workflow_state=workflow_run.state if workflow_run is not None else None,
        workflow_status=workflow_run.status if workflow_run is not None else None,
    )


async def record_demo_action_run(
    repository: AxisPersistenceRepository,
    action_id: str,
    request: ActionRunRequest,
    workflow_runtime: WorkflowSignalRuntime | None = None,
    *,
    tenant_id: str = "tenant_demo_manufacturing",
    workflow_history_persistence_enabled: bool = False,
) -> ActionRunPersistenceResult:
    tenant_id, action, schema_version = _find_action(repository, action_id, tenant_id)
    payload_tenant_id = request.payload.get("tenant_id")
    if payload_tenant_id is not None and payload_tenant_id != tenant_id:
        raise ActionPayloadValidationError(["tenant_mismatch:tenant_id"])
    _validate_payload(action, request.payload)
    permission_decision, relationship_scopes = _evaluate_action_permission(
        repository,
        tenant_id,
        action,
        request,
    )
    idempotency_key = _idempotency_key(tenant_id, action, request)
    payload = _stored_payload(action, request, schema_version)
    runtime = workflow_runtime or DeferredWorkflowSignalRuntime()

    existing = repository.get_action_run_by_idempotency_key(
        tenant_id,
        action.definition.action_id,
        idempotency_key,
    )
    if existing is not None:
        if existing.payload != payload:
            raise ActionRunIdempotencyConflict(existing.id)

        return _result_from_action_run(
            tenant_id=tenant_id,
            action=action,
            action_run_id=existing.id,
            idempotency_key=idempotency_key,
            status=existing.status,
            requested_by=existing.requested_by,
            permission_decision=permission_decision,
            audit_event_id=None,
            audit_event_type=None,
            idempotent_replay=True,
            workflow_signal_status="idempotent_replay",
        )

    platform_policy_decision = _enforce_platform_policies(
        repository,
        tenant_id,
        action,
        request,
        idempotency_key,
    )
    approval_required = (
        action.definition.requires_approval
        or platform_policy_decision.effect == PlatformPolicyEffect.REQUIRE_APPROVAL.value
    )
    status = _action_status(action, approval_required)
    action_run = repository.create_action_run(
        ActionRunCreate(
            tenant_id=tenant_id,
            action_id=action.definition.action_id,
            idempotency_key=idempotency_key,
            execution_mode=action.policy.execution_mode,
            requested_by=request.actor_id,
            approval_id=action.approval_refs[0] if action.approval_refs else None,
            workflow_id=action.workflow_bindings[0] if action.workflow_bindings else None,
            payload=payload,
            status=status,
        )
    )
    workflow_signal = await _signal_action_workflow(
        runtime,
        tenant_id=tenant_id,
        action=action,
        action_run_id=action_run.id,
        idempotency_key=idempotency_key,
        request=request,
    )
    workflow_signal_status = _workflow_signal_status(workflow_signal)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=tenant_id,
            actor_id=request.actor_id,
            event_type=action.policy.audit_event_type,
            payload={
                "action_id": action.definition.action_id,
                "action_run_id": str(action_run.id),
                "idempotency_key": idempotency_key,
                "status": status,
                "execution_mode": action.policy.execution_mode,
                "approval_required": approval_required,
                "approval_id": action.approval_refs[0] if action.approval_refs else None,
                "workflow_id": action.workflow_bindings[0] if action.workflow_bindings else None,
                "risk_level": action.definition.risk_level.value,
                "approval_mode": action.definition.approval_mode.value,
                "permission_decision": permission_decision.model_dump(),
                "relationship_scopes": relationship_scopes,
                "payload_field_names": sorted(request.payload.keys()),
                "payload_recorded": "true",
                "workflow_signal_status": workflow_signal_status,
                "workflow_signal": workflow_signal.model_dump() if workflow_signal else None,
                "platform_policy_decision": (
                    platform_policy_decision.model_dump()
                    if platform_policy_decision.matched
                    else None
                ),
            },
        )
    )
    workflow_run = None
    if action.workflow_bindings:
        if workflow_history_persistence_enabled:
            ensure_workflow_run(repository, tenant_id, action.workflow_bindings[0])
        workflow_run = repository.record_workflow_action_run(
            WorkflowActionRunUpdate(
                tenant_id=tenant_id,
                workflow_id=action.workflow_bindings[0],
                action_id=action.definition.action_id,
                action_run_id=action_run.id,
                idempotency_key=idempotency_key,
                actor_id=request.actor_id,
                workflow_signal_status=workflow_signal_status,
                requires_approval=approval_required,
                approval_id=action.approval_refs[0] if action.approval_refs else None,
            )
        )

    return _result_from_action_run(
        tenant_id=tenant_id,
        action=action,
        action_run_id=action_run.id,
        idempotency_key=idempotency_key,
        status=action_run.status,
        requested_by=action_run.requested_by,
        permission_decision=permission_decision,
        audit_event_id=audit_event.id,
        audit_event_type=audit_event.event_type,
        idempotent_replay=False,
        approval_required=approval_required,
        workflow_signal=workflow_signal,
        workflow_signal_status=workflow_signal_status,
        workflow_state_updated=workflow_run is not None,
        workflow_state=workflow_run.state if workflow_run is not None else None,
        workflow_status=workflow_run.status if workflow_run is not None else None,
        platform_policy_decision=platform_policy_decision,
    )
