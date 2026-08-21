"""Governed agent run execution: the L1/L2 recommendation loop.

The pipeline mirrors ``action_runs``: resolve the agent from the persisted
registry, evaluate permission (the ``agents:run:execute`` scope plus the
agent's own registry-declared permissions), replay idempotently, enforce
platform policy fail-closed, persist the run, then execute a bounded loop:

1. CONTEXT READ — only surfaces granted by the agent's ``data_access``
   declarations are read, through the existing tenant-scoped read functions.
   Evidence is reference-based (record ids and counts, never payload dumps).
2. MODEL — every model call goes through :func:`invoke_model`, so the run
   inherits the router's full governance (permission, routing, egress guard,
   platform policy, metering and audit). Nothing here talks to a provider.
3. PROPOSAL — the model output is strict-parsed into a typed
   :class:`AgentActionProposalDraft`. Unparseable output fails the run; a
   fallback proposal is never fabricated. The proposed action must exist in
   the action registry, be allowed (and not blocked) for the agent, and sit
   within the agent's autonomy and risk ceilings.

Autonomy semantics follow the registry's L0-L4 ladder: L0 (Observe) and
L3/L4 are refused outright; L1 (Recommend) records the proposal on the run
without creating an action run; L2 (Prepare) submits the proposal through
:func:`record_demo_action_run`, which lands it in the existing human
approval pipeline untouched. ``dry_run`` mode stops after the proposal parse
for both levels and never creates an action run.
"""

import base64
import binascii
import json
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from axis_api.action_reference import (
    ActionReferenceRecordInvalid,
    ActionReferenceRecordNotFound,
    require_persisted_manufacturing_action_registry,
)
from axis_api.action_runs import (
    ActionPayloadValidationError,
    ActionPermissionDenied,
    ActionRunIdempotencyConflict,
    ActionRunPersistenceResult,
    ActionRunRequest,
    record_demo_action_run,
)
from axis_api.agent_reference import require_persisted_manufacturing_agent_registry
from axis_api.audit import AuditEventCreate
from axis_api.demo import ActionRegistryEntry, AgentRegistryEntry
from axis_api.model_invocations import (
    ModelEgressBlocked,
    ModelInvocationIdempotencyConflict,
    ModelInvocationPermissionDenied,
    ModelInvocationRequest,
    ModelInvocationValidationError,
    invoke_model,
)
from axis_api.model_providers import (
    MODEL_INVOCATION_DEFERRED_STATUS,
    ModelInvocationRuntime,
)
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    AgentRunCreate,
    AgentRunResultRecord,
    AgentRunStepCreate,
    AxisPersistenceRepository,
)
from axis_api.platform_policies import (
    PlatformPolicyDecision,
    PlatformPolicyEnforcementDenied,
    PlatformPolicyEvaluationContext,
    PlatformPolicyScope,
    enforce_platform_policy_deny,
)
from axis_api.usage_metering import (
    DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
    TenantUsageMetric,
    record_tenant_usage_event,
)
from axis_api.workflow_runtime import WorkflowSignalRuntime

AGENT_RUN_EXECUTE_SCOPE = "agents:run:execute"
AGENT_RUN_PLATFORM_POLICY_DOMAIN = "agent_runs"
AGENT_RUN_MODEL_TASK_TYPE = "agent_proposal"

AGENT_RUN_MODE_PROPOSE = "propose"
AGENT_RUN_MODE_DRY_RUN = "dry_run"

AGENT_RUN_REQUESTED_STATUS = "requested"
AGENT_RUN_DEFERRED_STATUS = "deferred"
AGENT_RUN_BLOCKED_STATUS = "blocked"
AGENT_RUN_FAILED_CONTEXT_READ_STATUS = "failed_context_read"
AGENT_RUN_FAILED_MODEL_INVOCATION_STATUS = "failed_model_invocation"
AGENT_RUN_FAILED_INVALID_PROPOSAL_STATUS = "failed_invalid_proposal"
AGENT_RUN_PROPOSAL_RECORDED_STATUS = "proposal_recorded"
AGENT_RUN_PROPOSAL_CREATED_STATUS = "proposal_created"
AGENT_RUN_DRY_RUN_COMPLETED_STATUS = "dry_run_completed"

AGENT_RUN_REQUESTED_AUDIT_EVENT_TYPE = "agent.run.requested"
AGENT_RUN_CONTEXT_READ_AUDIT_EVENT_TYPE = "agent.run.context_read"
AGENT_RUN_MODEL_INVOKED_AUDIT_EVENT_TYPE = "agent.run.model_invoked"
AGENT_RUN_PROPOSAL_RECORDED_AUDIT_EVENT_TYPE = "agent.run.proposal_recorded"
AGENT_RUN_PROPOSAL_CREATED_AUDIT_EVENT_TYPE = "agent.run.proposal_created"
AGENT_RUN_BLOCKED_AUDIT_EVENT_TYPE = "agent.run.blocked"
AGENT_RUN_FAILED_AUDIT_EVENT_TYPE = "agent.run.failed"
AGENT_RUN_DRY_RUN_COMPLETED_AUDIT_EVENT_TYPE = "agent.run.dry_run_completed"
AGENT_RUN_DEFERRED_AUDIT_EVENT_TYPE = "agent.run.deferred"

STEP_TYPE_CONTEXT_READ = "context_read"
STEP_TYPE_MODEL_INVOCATION = "model_invocation"
STEP_TYPE_PROPOSAL = "proposal"

STEP_STATUS_COMPLETED = "completed"
STEP_STATUS_FAILED = "failed"
STEP_STATUS_BLOCKED = "blocked"
STEP_STATUS_DEFERRED = "deferred"

# Registry statuses under which an agent may execute. The seed registry uses
# activity-flavored statuses instead of a bare "active"; anything outside this
# set (retired, suspended, unknown values) is refused fail-closed.
ACTIVE_AGENT_STATUSES = frozenset(
    {
        "active",
        "recommending",
        "waiting_for_approval",
        "drafting_actions",
        "proposal_ready",
    }
)

EXECUTABLE_AUTONOMY_LEVELS = frozenset({"L1", "L2"})

_AUTONOMY_RANK = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4}
_RISK_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}

# The highest action risk level each executable autonomy level may propose:
# L1 recommends read-only/low-risk work; L2 may prepare up to high-risk
# actions because every prepared action still crosses the human approval gate.
_AUTONOMY_RISK_CEILING = {"L1": "low", "L2": "high"}

# Context read surfaces served by existing tenant-scoped read functions.
CONTEXT_SURFACE_OPERATIONS_RECORDS = "operations_records"
CONTEXT_SURFACE_RISK_SCENARIOS = "risk_scenarios"
CONTEXT_SURFACE_DAILY_BRIEFS = "daily_briefs"

# Governed binding between the persisted agent registry's ``data_access``
# declarations and the Axis read surfaces that serve them. The context read
# fails closed when an agent declares access the platform cannot map to a
# governed read function — an unknown declaration never widens into a read.
AGENT_DATA_ACCESS_SURFACE_BINDINGS: dict[str, str] = {
    # Daily Brief Agent
    "workflow summaries": CONTEXT_SURFACE_OPERATIONS_RECORDS,
    "approval queue summaries": CONTEXT_SURFACE_OPERATIONS_RECORDS,
    "audit event summaries": CONTEXT_SURFACE_DAILY_BRIEFS,
    "ontology relationship summaries": CONTEXT_SURFACE_OPERATIONS_RECORDS,
    # Supply Risk Agent
    "inbound shipment status": CONTEXT_SURFACE_OPERATIONS_RECORDS,
    "Line 2 packaging schedule": CONTEXT_SURFACE_OPERATIONS_RECORDS,
    "rush order priority flag": CONTEXT_SURFACE_OPERATIONS_RECORDS,
    "supply approval history": CONTEXT_SURFACE_RISK_SCENARIOS,
    # Quality Risk Agent
    "sample inspection variance": CONTEXT_SURFACE_OPERATIONS_RECORDS,
    "batch genealogy": CONTEXT_SURFACE_OPERATIONS_RECORDS,
    "customer order priority": CONTEXT_SURFACE_OPERATIONS_RECORDS,
    "quality proposal audit trail": CONTEXT_SURFACE_RISK_SCENARIOS,
    # Maintenance Planner Agent
    "Press 4 maintenance window": CONTEXT_SURFACE_OPERATIONS_RECORDS,
    "rush order schedule": CONTEXT_SURFACE_OPERATIONS_RECORDS,
    "service interval tolerance": CONTEXT_SURFACE_OPERATIONS_RECORDS,
    "maintenance proposal audit trail": CONTEXT_SURFACE_RISK_SCENARIOS,
}

_CONTEXT_READ_LIMIT = 50
_CONTEXT_EVIDENCE_REF_LIMIT = 20


class AgentRunAgentNotFound(LookupError):
    pass


class AgentRunNotFound(LookupError):
    pass


class AgentRunAgentNotExecutable(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class AgentRunPermissionDenied(PermissionError):
    def __init__(self, required_permissions: list[str], decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permissions = required_permissions
        self.decision = decision


class AgentRunIdempotencyConflict(ValueError):
    def __init__(self, run_id: UUID) -> None:
        super().__init__("Idempotency key already exists with a different payload")
        self.run_id = run_id


class AgentRunCursorError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AgentRunContextAccessError(ValueError):
    """The agent's data_access declarations do not authorize the context read."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AgentRunProposalParseError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AgentActionProposalDraft(BaseModel):
    """Typed proposal contract the model must emit as a bare JSON object."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1, max_length=180)
    summary: str = Field(min_length=1, max_length=800)
    payload: dict = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class AgentRunStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    actor_id: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=200)
    mode: str = Field(default=AGENT_RUN_MODE_PROPOSE, pattern=r"^(propose|dry_run)$")


class AgentRunStepView(BaseModel):
    seq: int = Field(ge=1)
    step_type: str = Field(min_length=1)
    status: str = Field(min_length=1)
    evidence: dict = Field(default_factory=dict)
    created_at: datetime


class AgentRunResult(BaseModel):
    tenant_id: str = Field(min_length=1)
    run_id: UUID
    agent_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    status: str = Field(min_length=1)
    mode: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    autonomy_level: str = Field(min_length=1)
    context_refs: list[str] = Field(default_factory=list)
    model_invocation_ids: list[str] = Field(default_factory=list)
    proposed_action_run_id: UUID | None = None
    proposal_payload: dict | None = None
    permission_decision: PermissionDecision
    platform_policy_decision: PlatformPolicyDecision | None = None
    error_reason: str | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None
    persisted: bool = True
    idempotent_replay: bool = False
    steps: list[AgentRunStepView] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime


class AgentRunList(BaseModel):
    tenant_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    runs: list[AgentRunResult] = Field(default_factory=list)
    has_more: bool = False
    next_cursor: str | None = None
    run_notes: list[str] = Field(default_factory=list)


def resolve_agent_context_surfaces(agent: AgentRegistryEntry) -> list[str]:
    """Map the agent's data_access declarations to read surfaces, fail-closed.

    Every declaration must bind to a known surface; an empty declaration list
    or any unknown declaration raises :class:`AgentRunContextAccessError` so a
    misdeclared agent can never read anything.
    """
    declarations = [entry for entry in agent.data_access if entry.strip()]
    if not declarations:
        raise AgentRunContextAccessError("empty_data_access")
    surfaces: set[str] = set()
    for declaration in declarations:
        surface = AGENT_DATA_ACCESS_SURFACE_BINDINGS.get(declaration)
        if surface is None:
            raise AgentRunContextAccessError(f"unknown_data_access_surface:{declaration}")
        surfaces.add(surface)
    return sorted(surfaces)


def parse_agent_action_proposal(output_text: str) -> AgentActionProposalDraft:
    """Strict-parse model output into the typed proposal contract.

    Accepts a bare JSON object, optionally wrapped in a single Markdown code
    fence. Anything else — prose, partial JSON, wrong shape, extra fields —
    raises :class:`AgentRunProposalParseError`. A fallback proposal is never
    fabricated from unparseable output.
    """
    text = output_text.strip()
    if not text:
        raise AgentRunProposalParseError("empty_model_output")
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentRunProposalParseError("model_output_not_json") from exc
    if not isinstance(payload, dict):
        raise AgentRunProposalParseError("model_output_not_json_object")
    try:
        return AgentActionProposalDraft.model_validate(payload)
    except ValidationError as exc:
        raise AgentRunProposalParseError("model_output_schema_invalid") from exc


def build_agent_proposal_prompt(
    agent: AgentRegistryEntry,
    tenant_id: str,
    context_evidence: dict[str, dict],
    allowed_actions: list[ActionRegistryEntry],
) -> str:
    """Build the deterministic proposal prompt from registry + context evidence.

    The template is fully derived from persisted records (agent charter,
    guardrails, granted context references and the allowed action contracts),
    so identical inputs always produce an identical prompt.
    """
    lines = [
        f"You are {agent.name} ({agent.agent_id}), a governed "
        f"{agent.policy_boundary.autonomy_level} agent in the Limes Axis control plane.",
        f"Verified tenant context: {tenant_id}",
        f"Charter: {agent.purpose}",
        "Guardrails:",
    ]
    lines.extend(f"- {guardrail}" for guardrail in agent.policy_boundary.guardrails)
    lines.append("Context evidence (reference ids only, newest first):")
    for surface in sorted(context_evidence):
        evidence = context_evidence[surface]
        refs = ", ".join(evidence.get("refs", [])) or "none"
        lines.append(f"- {surface}: {evidence.get('count', 0)} records; refs: {refs}")
    lines.append("Actions you may propose (exactly one):")
    for action in sorted(allowed_actions, key=lambda entry: entry.definition.action_id):
        schema = action.definition.input_schema
        required_fields = ", ".join(sorted(schema.get("required", []))) or "none"
        lines.append(
            f"- action_id={action.definition.action_id} "
            f"({action.definition.display_name}); "
            f"risk={action.definition.risk_level.value}; "
            f"required payload fields: {required_fields}"
        )
    lines.append(
        "Respond with ONLY a JSON object (no prose, no code fence) matching: "
        '{"action_id": string, "summary": string, "payload": object, '
        '"evidence_refs": [string, ...]}. The payload must satisfy the action '
        "input schema and evidence_refs must cite the context references above. "
        f"If the payload schema includes tenant_id, set it exactly to {tenant_id}."
    )
    return "\n".join(lines)


def _agent_action_allowed(agent: AgentRegistryEntry, action: ActionRegistryEntry) -> bool:
    action_names = {action.definition.action_id, action.definition.display_name}
    return (
        agent.agent_id in action.connected_agents
        or bool(action_names.intersection(agent.allowed_actions))
    )


def _agent_action_blocked(agent: AgentRegistryEntry, action: ActionRegistryEntry) -> bool:
    action_names = {action.definition.action_id, action.definition.display_name}
    return bool(action_names.intersection(agent.blocked_actions))


def _proposal_enforcement_block_reason(
    agent: AgentRegistryEntry,
    action: ActionRegistryEntry,
) -> str | None:
    """Return the fail-closed block reason for a proposed action, if any."""
    if _agent_action_blocked(agent, action):
        return "action_blocked_for_agent"
    if not _agent_action_allowed(agent, action):
        return "action_not_allowed_for_agent"
    agent_ceiling = agent.policy_boundary.max_action_level
    action_ceiling = action.policy.autonomy_ceiling
    if _AUTONOMY_RANK.get(action_ceiling, len(_AUTONOMY_RANK)) > _AUTONOMY_RANK.get(
        agent_ceiling, -1
    ):
        return "action_autonomy_above_agent_ceiling"
    risk_ceiling = _AUTONOMY_RISK_CEILING.get(agent_ceiling)
    if risk_ceiling is None or _RISK_RANK.get(
        action.definition.risk_level.value, len(_RISK_RANK) + 1
    ) > _RISK_RANK.get(risk_ceiling, 0):
        return "action_risk_above_autonomy_ceiling"
    return None


def _resolve_agent(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    agent_id: str,
) -> AgentRegistryEntry:
    registry = require_persisted_manufacturing_agent_registry(
        repository, tenant_id=tenant_id
    )
    agent = next(
        (entry for entry in registry.agents if entry.agent_id == agent_id),
        None,
    )
    if agent is None:
        raise AgentRunAgentNotFound("Agent not found")
    if agent.status not in ACTIVE_AGENT_STATUSES:
        raise AgentRunAgentNotExecutable(
            "The agent is not active in the persisted registry.",
            f"agent_not_active:{agent.status}",
        )
    autonomy_level = agent.policy_boundary.autonomy_level
    if autonomy_level not in EXECUTABLE_AUTONOMY_LEVELS:
        raise AgentRunAgentNotExecutable(
            "Only L1 (Recommend) and L2 (Prepare) agents may execute runs; "
            "L0 is observe-only and L3/L4 autonomy is not enabled.",
            f"autonomy_level_not_executable:{autonomy_level}",
        )
    return agent


def _evaluate_agent_run_permission(
    tenant_id: str,
    agent: AgentRegistryEntry,
    request: AgentRunStartRequest,
) -> PermissionDecision:
    required_scopes = sorted(
        {AGENT_RUN_EXECUTE_SCOPE, *agent.policy_boundary.required_permissions}
    )
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=tenant_id,
            actor_id=request.actor_id,
            actor_scopes=request.actor_scopes,
            required_scopes=required_scopes,
            attributes={
                "agent_id": agent.agent_id,
                "autonomy_level": agent.policy_boundary.autonomy_level,
                "mode": request.mode,
                "operation": "start_agent_run",
            },
        )
    )
    if not decision.allowed:
        raise AgentRunPermissionDenied(required_scopes, decision)
    return decision


def _request_fingerprint(agent_id: str, request: AgentRunStartRequest) -> dict:
    return {"agent_id": agent_id, "mode": request.mode}


def _read_context_surface(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    surface: str,
) -> tuple[list[str], int]:
    if surface == CONTEXT_SURFACE_OPERATIONS_RECORDS:
        records = repository.list_manufacturing_operation_records(
            tenant_id=tenant_id,
            limit=_CONTEXT_READ_LIMIT,
        )
        refs = [f"manufacturing_operation_record:{record.record_id}" for record in records]
    elif surface == CONTEXT_SURFACE_RISK_SCENARIOS:
        scenarios = repository.list_manufacturing_risk_scenarios(
            tenant_id,
            limit=_CONTEXT_READ_LIMIT,
        )
        refs = [f"manufacturing_risk_scenario:{scenario.scenario_id}" for scenario in scenarios]
    elif surface == CONTEXT_SURFACE_DAILY_BRIEFS:
        briefs = repository.list_manufacturing_daily_briefs(
            tenant_id,
            limit=_CONTEXT_READ_LIMIT,
        )
        refs = [f"manufacturing_daily_brief:{brief.brief_id}" for brief in briefs]
    else:  # defensive: bindings only produce the surfaces above
        raise AgentRunContextAccessError(f"unknown_data_access_surface:{surface}")
    return refs, len(refs)


def encode_agent_run_cursor(result: AgentRunResult) -> str:
    payload = {
        "created_at": _ensure_utc(result.created_at).isoformat(),
        "row_id": str(result.run_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_agent_run_cursor(cursor: str | None) -> tuple[datetime | None, UUID | None]:
    if cursor is None:
        return None, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        created_at = datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00"))
        row_id = UUID(str(payload["row_id"]))
    except (
        KeyError,
        TypeError,
        UnicodeError,
        ValueError,
        binascii.Error,
        json.JSONDecodeError,
    ) as exc:
        raise AgentRunCursorError("invalid_agent_run_cursor") from exc
    return _ensure_utc(created_at), row_id


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _result_from_run(
    run,
    *,
    permission_decision: PermissionDecision | None = None,
    idempotent_replay: bool,
    steps: list[AgentRunStepView] | None = None,
    notes: list[str] | None = None,
) -> AgentRunResult:
    result_notes = list(notes if notes is not None else run.notes or [])
    if idempotent_replay:
        result_notes.append("Idempotent replay: the stored agent run record is returned.")
    return AgentRunResult(
        tenant_id=run.tenant_id,
        run_id=run.id,
        agent_id=run.agent_id,
        idempotency_key=run.idempotency_key,
        status=run.status,
        mode=run.mode,
        requested_by=run.requested_by,
        autonomy_level=run.autonomy_level,
        context_refs=list(run.context_refs or []),
        model_invocation_ids=list(run.model_invocation_ids or []),
        proposed_action_run_id=run.proposed_action_run_id,
        proposal_payload=run.proposal_payload,
        permission_decision=(
            permission_decision
            if permission_decision is not None
            else PermissionDecision.model_validate(run.permission_decision)
        ),
        platform_policy_decision=(
            PlatformPolicyDecision.model_validate(run.platform_policy_decision)
            if run.platform_policy_decision
            else None
        ),
        error_reason=run.error_reason,
        audit_event_id=run.audit_event_id,
        audit_event_type=run.audit_event_type,
        persisted=True,
        idempotent_replay=idempotent_replay,
        steps=steps or [],
        notes=result_notes,
        created_at=run.created_at,
    )


def _step_views(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    run_id: UUID,
) -> list[AgentRunStepView]:
    return [
        AgentRunStepView(
            seq=step.seq,
            step_type=step.step_type,
            status=step.status,
            evidence=step.evidence or {},
            created_at=step.created_at,
        )
        for step in repository.list_agent_run_steps(tenant_id, run_id)
    ]


class _RunExecution:
    """Mutable execution state for one run: step counter, evidence, finalizer."""

    def __init__(
        self,
        repository: AxisPersistenceRepository,
        run,
        request: AgentRunStartRequest,
        agent: AgentRegistryEntry,
        permission_decision: PermissionDecision,
        model_runtime: ModelInvocationRuntime,
    ) -> None:
        self.repository = repository
        self.run = run
        self.request = request
        self.agent = agent
        self.permission_decision = permission_decision
        self.model_runtime = model_runtime
        self.step_seq = 0
        self.context_refs: list[str] = []
        self.model_invocation_ids: list[str] = []

    def append_step(self, step_type: str, status: str, evidence: dict) -> None:
        self.step_seq += 1
        self.repository.append_agent_run_step(
            AgentRunStepCreate(
                tenant_id=self.run.tenant_id,
                run_id=self.run.id,
                seq=self.step_seq,
                step_type=step_type,
                status=status,
                evidence=evidence,
            )
        )

    def finalize(
        self,
        *,
        status: str,
        audit_event_type: str,
        error_reason: str | None = None,
        proposal_payload: dict | None = None,
        proposed_action_run_id: UUID | None = None,
        audit_extra: dict | None = None,
        notes: list[str] | None = None,
    ) -> AgentRunResult:
        audit_event = self.repository.append_audit_event(
            AuditEventCreate(
                tenant_id=self.run.tenant_id,
                actor_id=self.request.actor_id,
                event_type=audit_event_type,
                payload={
                    "agent_run_id": str(self.run.id),
                    "agent_id": self.run.agent_id,
                    "idempotency_key": self.run.idempotency_key,
                    "status": status,
                    "mode": self.run.mode,
                    "autonomy_level": self.run.autonomy_level,
                    "error_reason": error_reason,
                    "context_ref_count": len(self.context_refs),
                    "model_invocation_ids": self.model_invocation_ids,
                    "proposed_action_run_id": (
                        str(proposed_action_run_id)
                        if proposed_action_run_id is not None
                        else None
                    ),
                    **(audit_extra or {}),
                },
            )
        )
        run = self.repository.record_agent_run_result(
            AgentRunResultRecord(
                tenant_id=self.run.tenant_id,
                run_id=self.run.id,
                status=status,
                context_refs=self.context_refs,
                model_invocation_ids=self.model_invocation_ids,
                proposed_action_run_id=proposed_action_run_id,
                proposal_payload=proposal_payload,
                error_reason=error_reason,
                audit_event_id=audit_event.id,
                audit_event_type=audit_event.event_type,
                notes=notes,
            )
        )
        return _result_from_run(
            run,
            permission_decision=self.permission_decision,
            idempotent_replay=False,
            steps=_step_views(self.repository, run.tenant_id, run.id),
        )


async def start_agent_run(
    repository: AxisPersistenceRepository,
    agent_id: str,
    request: AgentRunStartRequest,
    model_runtime: ModelInvocationRuntime,
    *,
    execution_enabled: bool = False,
    max_model_calls: int = 3,
    external_model_egress_enabled: bool = False,
    model_prompt_excerpt_chars: int = 0,
    usage_metering_enabled: bool = False,
    usage_window_seconds: int = DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
    workflow_runtime: WorkflowSignalRuntime | None = None,
) -> AgentRunResult:
    agent = _resolve_agent(repository, request.tenant_id, agent_id)
    permission_decision = _evaluate_agent_run_permission(request.tenant_id, agent, request)
    fingerprint = _request_fingerprint(agent_id, request)

    existing = repository.get_agent_run_by_idempotency_key(
        request.tenant_id,
        agent_id,
        request.idempotency_key,
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise AgentRunIdempotencyConflict(existing.id)
        return _result_from_run(
            existing,
            permission_decision=permission_decision,
            idempotent_replay=True,
            steps=_step_views(repository, request.tenant_id, existing.id),
        )

    platform_policy_decision = enforce_platform_policy_deny(
        repository,
        tenant_id=request.tenant_id,
        actor_id=request.actor_id,
        scope=PlatformPolicyScope.AGENT_RUN,
        context=PlatformPolicyEvaluationContext(
            action_id=agent.agent_id,
            action_domain=AGENT_RUN_PLATFORM_POLICY_DOMAIN,
            autonomy_level=agent.policy_boundary.autonomy_level,
        ),
        enforcement_point="agent_run",
        audit_payload={
            "agent_id": agent.agent_id,
            "idempotency_key": request.idempotency_key,
            "mode": request.mode,
        },
    )

    run = repository.create_agent_run(
        AgentRunCreate(
            tenant_id=request.tenant_id,
            agent_id=agent.agent_id,
            idempotency_key=request.idempotency_key,
            status=AGENT_RUN_REQUESTED_STATUS,
            mode=request.mode,
            requested_by=request.actor_id,
            autonomy_level=agent.policy_boundary.autonomy_level,
            request_fingerprint=fingerprint,
            permission_decision=permission_decision.model_dump(),
            platform_policy_decision=(
                platform_policy_decision.model_dump()
                if platform_policy_decision.matched
                else None
            ),
        )
    )
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            event_type=AGENT_RUN_REQUESTED_AUDIT_EVENT_TYPE,
            payload={
                "agent_run_id": str(run.id),
                "agent_id": agent.agent_id,
                "idempotency_key": request.idempotency_key,
                "mode": request.mode,
                "autonomy_level": agent.policy_boundary.autonomy_level,
                "permission_decision": permission_decision.model_dump(),
                "platform_policy_decision": (
                    platform_policy_decision.model_dump()
                    if platform_policy_decision.matched
                    else None
                ),
            },
        )
    )

    execution = _RunExecution(
        repository, run, request, agent, permission_decision, model_runtime
    )
    if not execution_enabled:
        return execution.finalize(
            status=AGENT_RUN_DEFERRED_STATUS,
            audit_event_type=AGENT_RUN_DEFERRED_AUDIT_EVENT_TYPE,
            error_reason="agent_run_execution_disabled",
            notes=[
                "Agent run execution is disabled by AXIS_AGENT_RUN_EXECUTION_ENABLED; "
                "no context read, model call or proposal was started.",
            ],
        )

    result = await _execute_agent_run(
        execution,
        max_model_calls=max_model_calls,
        external_model_egress_enabled=external_model_egress_enabled,
        model_prompt_excerpt_chars=model_prompt_excerpt_chars,
        usage_metering_enabled=usage_metering_enabled,
        usage_window_seconds=usage_window_seconds,
        workflow_runtime=workflow_runtime,
    )
    if usage_metering_enabled:
        record_tenant_usage_event(
            repository,
            request.tenant_id,
            TenantUsageMetric.AGENT_RUNS,
            1,
            source_type="agent_run",
            source_id=str(run.id),
            window_seconds=usage_window_seconds,
            occurred_at=run.created_at,
            dimensions={"agent_id": agent.agent_id},
        )
    return result


async def _execute_agent_run(
    execution: _RunExecution,
    *,
    max_model_calls: int,
    external_model_egress_enabled: bool,
    model_prompt_excerpt_chars: int,
    usage_metering_enabled: bool,
    usage_window_seconds: int,
    workflow_runtime: WorkflowSignalRuntime | None,
) -> AgentRunResult:
    repository = execution.repository
    request = execution.request
    agent = execution.agent
    run = execution.run

    # Step 1: context read, bounded by the agent's data_access grants.
    try:
        surfaces = resolve_agent_context_surfaces(agent)
    except AgentRunContextAccessError as exc:
        execution.append_step(
            STEP_TYPE_CONTEXT_READ,
            STEP_STATUS_FAILED,
            {"reason": exc.reason},
        )
        return execution.finalize(
            status=AGENT_RUN_FAILED_CONTEXT_READ_STATUS,
            audit_event_type=AGENT_RUN_FAILED_AUDIT_EVENT_TYPE,
            error_reason=exc.reason,
        )

    context_evidence: dict[str, dict] = {}
    for surface in surfaces:
        refs, count = _read_context_surface(repository, request.tenant_id, surface)
        context_evidence[surface] = {
            "count": count,
            "refs": refs[:_CONTEXT_EVIDENCE_REF_LIMIT],
        }
        execution.context_refs.extend(refs[:_CONTEXT_EVIDENCE_REF_LIMIT])
    execution.append_step(
        STEP_TYPE_CONTEXT_READ,
        STEP_STATUS_COMPLETED,
        {"surfaces": context_evidence},
    )
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            event_type=AGENT_RUN_CONTEXT_READ_AUDIT_EVENT_TYPE,
            payload={
                "agent_run_id": str(run.id),
                "agent_id": agent.agent_id,
                "surfaces": {
                    surface: evidence["count"]
                    for surface, evidence in context_evidence.items()
                },
                "context_ref_count": len(execution.context_refs),
            },
        )
    )

    # Step 2: the model call, always through the governed router.
    allowed_actions = _allowed_registry_actions(repository, request.tenant_id, agent)
    prompt = build_agent_proposal_prompt(
        agent,
        request.tenant_id,
        context_evidence,
        allowed_actions,
    )
    if max_model_calls < 1:
        execution.append_step(
            STEP_TYPE_MODEL_INVOCATION,
            STEP_STATUS_FAILED,
            {"reason": "model_call_budget_exhausted", "max_model_calls": max_model_calls},
        )
        return execution.finalize(
            status=AGENT_RUN_FAILED_MODEL_INVOCATION_STATUS,
            audit_event_type=AGENT_RUN_FAILED_AUDIT_EVENT_TYPE,
            error_reason="model_call_budget_exhausted",
        )
    try:
        invocation_result = await invoke_model(
            repository,
            ModelInvocationRequest(
                tenant_id=request.tenant_id,
                actor_id=request.actor_id,
                actor_scopes=request.actor_scopes,
                idempotency_key=f"agent-run:{run.id}:model:1",
                task_type=AGENT_RUN_MODEL_TASK_TYPE,
                prompt=prompt,
            ),
            execution.model_runtime,
            external_model_egress_enabled=external_model_egress_enabled,
            prompt_excerpt_chars=model_prompt_excerpt_chars,
            usage_metering_enabled=usage_metering_enabled,
            usage_window_seconds=usage_window_seconds,
        )
    except ModelInvocationPermissionDenied as exc:
        execution.append_step(
            STEP_TYPE_MODEL_INVOCATION,
            STEP_STATUS_BLOCKED,
            {"reason": exc.decision.reason, "required_permission": exc.required_permission},
        )
        return execution.finalize(
            status=AGENT_RUN_BLOCKED_STATUS,
            audit_event_type=AGENT_RUN_BLOCKED_AUDIT_EVENT_TYPE,
            error_reason="model_invoke_permission_denied",
        )
    except ModelEgressBlocked as exc:
        execution.append_step(
            STEP_TYPE_MODEL_INVOCATION,
            STEP_STATUS_BLOCKED,
            {"reason": exc.egress_decision},
        )
        return execution.finalize(
            status=AGENT_RUN_BLOCKED_STATUS,
            audit_event_type=AGENT_RUN_BLOCKED_AUDIT_EVENT_TYPE,
            error_reason=exc.egress_decision,
        )
    except PlatformPolicyEnforcementDenied as exc:
        execution.append_step(
            STEP_TYPE_MODEL_INVOCATION,
            STEP_STATUS_BLOCKED,
            {"reason": "model_invocation_policy_denied", "policy_id": (
                exc.decision.matched_policy_id
            )},
        )
        return execution.finalize(
            status=AGENT_RUN_BLOCKED_STATUS,
            audit_event_type=AGENT_RUN_BLOCKED_AUDIT_EVENT_TYPE,
            error_reason="model_invocation_policy_denied",
        )
    except ModelInvocationValidationError as exc:
        execution.append_step(
            STEP_TYPE_MODEL_INVOCATION,
            STEP_STATUS_BLOCKED,
            {"reason": exc.reason},
        )
        return execution.finalize(
            status=AGENT_RUN_BLOCKED_STATUS,
            audit_event_type=AGENT_RUN_BLOCKED_AUDIT_EVENT_TYPE,
            error_reason=exc.reason,
        )
    except ModelInvocationIdempotencyConflict:
        execution.append_step(
            STEP_TYPE_MODEL_INVOCATION,
            STEP_STATUS_FAILED,
            {"reason": "model_invocation_idempotency_conflict"},
        )
        return execution.finalize(
            status=AGENT_RUN_FAILED_MODEL_INVOCATION_STATUS,
            audit_event_type=AGENT_RUN_FAILED_AUDIT_EVENT_TYPE,
            error_reason="model_invocation_idempotency_conflict",
        )

    execution.model_invocation_ids.append(str(invocation_result.invocation_id))
    repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            event_type=AGENT_RUN_MODEL_INVOKED_AUDIT_EVENT_TYPE,
            payload={
                # Thin by design: routing, egress, token and cost detail lives
                # in the model invocation's own audit trail.
                "agent_run_id": str(run.id),
                "agent_id": agent.agent_id,
                "model_invocation_id": str(invocation_result.invocation_id),
                "model_invocation_status": invocation_result.status,
                "seq": 1,
            },
        )
    )
    if invocation_result.status == MODEL_INVOCATION_DEFERRED_STATUS:
        execution.append_step(
            STEP_TYPE_MODEL_INVOCATION,
            STEP_STATUS_DEFERRED,
            {"model_invocation_id": str(invocation_result.invocation_id)},
        )
        return execution.finalize(
            status=AGENT_RUN_DEFERRED_STATUS,
            audit_event_type=AGENT_RUN_DEFERRED_AUDIT_EVENT_TYPE,
            error_reason="model_invocation_deferred",
            notes=[
                "Model routing execution is deferred; the run ends honestly "
                "without a proposal.",
            ],
        )
    if invocation_result.status != "completed":
        execution.append_step(
            STEP_TYPE_MODEL_INVOCATION,
            STEP_STATUS_FAILED,
            {
                "model_invocation_id": str(invocation_result.invocation_id),
                "error_code": invocation_result.error_code,
            },
        )
        return execution.finalize(
            status=AGENT_RUN_FAILED_MODEL_INVOCATION_STATUS,
            audit_event_type=AGENT_RUN_FAILED_AUDIT_EVENT_TYPE,
            error_reason=(
                f"model_invocation_failed:{invocation_result.error_code or 'unknown'}"
            ),
        )
    execution.append_step(
        STEP_TYPE_MODEL_INVOCATION,
        STEP_STATUS_COMPLETED,
        {
            "model_invocation_id": str(invocation_result.invocation_id),
            "endpoint_id": invocation_result.endpoint_id,
            "model_id": invocation_result.model_id,
        },
    )

    # Step 3: strict proposal parse + fail-closed enforcement.
    try:
        draft = parse_agent_action_proposal(invocation_result.output_text)
    except AgentRunProposalParseError as exc:
        execution.append_step(
            STEP_TYPE_PROPOSAL,
            STEP_STATUS_FAILED,
            {"reason": exc.reason, "output_chars": len(invocation_result.output_text)},
        )
        return execution.finalize(
            status=AGENT_RUN_FAILED_INVALID_PROPOSAL_STATUS,
            audit_event_type=AGENT_RUN_FAILED_AUDIT_EVENT_TYPE,
            error_reason=exc.reason,
        )

    action = _registry_action(repository, request.tenant_id, agent, draft.action_id)
    if isinstance(action, str):
        execution.append_step(
            STEP_TYPE_PROPOSAL,
            STEP_STATUS_BLOCKED,
            {"action_id": draft.action_id, "reason": action},
        )
        return execution.finalize(
            status=AGENT_RUN_BLOCKED_STATUS,
            audit_event_type=AGENT_RUN_BLOCKED_AUDIT_EVENT_TYPE,
            error_reason=action,
            audit_extra={"proposed_action_id": draft.action_id},
        )
    block_reason = _proposal_enforcement_block_reason(agent, action)
    if block_reason is not None:
        execution.append_step(
            STEP_TYPE_PROPOSAL,
            STEP_STATUS_BLOCKED,
            {"action_id": draft.action_id, "reason": block_reason},
        )
        return execution.finalize(
            status=AGENT_RUN_BLOCKED_STATUS,
            audit_event_type=AGENT_RUN_BLOCKED_AUDIT_EVENT_TYPE,
            error_reason=block_reason,
            audit_extra={"proposed_action_id": draft.action_id},
        )

    proposal_payload = draft.model_dump()
    if request.mode == AGENT_RUN_MODE_DRY_RUN:
        execution.append_step(
            STEP_TYPE_PROPOSAL,
            STEP_STATUS_COMPLETED,
            {"action_id": draft.action_id, "mode": AGENT_RUN_MODE_DRY_RUN},
        )
        return execution.finalize(
            status=AGENT_RUN_DRY_RUN_COMPLETED_STATUS,
            audit_event_type=AGENT_RUN_DRY_RUN_COMPLETED_AUDIT_EVENT_TYPE,
            proposal_payload=proposal_payload,
            audit_extra={"proposed_action_id": draft.action_id},
            notes=["Dry run: the proposal was recorded on the run and no action run exists."],
        )

    if agent.policy_boundary.autonomy_level == "L1":
        execution.append_step(
            STEP_TYPE_PROPOSAL,
            STEP_STATUS_COMPLETED,
            {"action_id": draft.action_id, "autonomy_level": "L1"},
        )
        return execution.finalize(
            status=AGENT_RUN_PROPOSAL_RECORDED_STATUS,
            audit_event_type=AGENT_RUN_PROPOSAL_RECORDED_AUDIT_EVENT_TYPE,
            proposal_payload=proposal_payload,
            audit_extra={"proposed_action_id": draft.action_id},
            notes=[
                "L1 (Recommend): the proposal is recorded on the run; no action "
                "run was submitted.",
            ],
        )

    # L2 (Prepare): submit the proposal through the existing action run
    # pipeline, which owns approval requirements, platform policy and audit.
    action_run_result = await _submit_action_run(execution, draft, action, workflow_runtime)
    if isinstance(action_run_result, AgentRunResult):
        return action_run_result
    execution.append_step(
        STEP_TYPE_PROPOSAL,
        STEP_STATUS_COMPLETED,
        {
            "action_id": draft.action_id,
            "autonomy_level": "L2",
            "action_run_id": str(action_run_result.action_run_id),
            "approval_required": action_run_result.approval_required,
        },
    )
    return execution.finalize(
        status=AGENT_RUN_PROPOSAL_CREATED_STATUS,
        audit_event_type=AGENT_RUN_PROPOSAL_CREATED_AUDIT_EVENT_TYPE,
        proposal_payload=proposal_payload,
        proposed_action_run_id=action_run_result.action_run_id,
        audit_extra={
            "proposed_action_id": draft.action_id,
            "action_run_id": str(action_run_result.action_run_id),
            "approval_required": action_run_result.approval_required,
            "action_run_status": action_run_result.status,
        },
        notes=[
            "L2 (Prepare): the proposal was submitted as a governed action run "
            "and now flows through the human approval pipeline.",
        ],
    )


def _allowed_registry_actions(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    agent: AgentRegistryEntry,
) -> list[ActionRegistryEntry]:
    try:
        registry = require_persisted_manufacturing_action_registry(
            repository, tenant_id=tenant_id
        )
    except (ActionReferenceRecordNotFound, ActionReferenceRecordInvalid):
        return []
    return [
        action
        for action in registry.actions
        if _agent_action_allowed(agent, action) and not _agent_action_blocked(agent, action)
    ]


def _registry_action(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    agent: AgentRegistryEntry,
    action_id: str,
) -> ActionRegistryEntry | str:
    """Resolve the proposed action or return a fail-closed block reason."""
    try:
        registry = require_persisted_manufacturing_action_registry(
            repository, tenant_id=tenant_id
        )
    except (ActionReferenceRecordNotFound, ActionReferenceRecordInvalid):
        return "action_registry_unavailable"
    action = next(
        (entry for entry in registry.actions if entry.definition.action_id == action_id),
        None,
    )
    if action is None:
        return "action_not_registered"
    return action


async def _submit_action_run(
    execution: _RunExecution,
    draft: AgentActionProposalDraft,
    action: ActionRegistryEntry,
    workflow_runtime: WorkflowSignalRuntime | None,
) -> "ActionRunPersistenceResult | AgentRunResult":
    request = execution.request
    try:
        return await record_demo_action_run(
            execution.repository,
            action.definition.action_id,
            ActionRunRequest(
                actor_id=request.actor_id,
                actor_scopes=request.actor_scopes,
                idempotency_key=f"agent-run:{execution.run.id}:action",
                payload=draft.payload,
            ),
            workflow_runtime,
            tenant_id=request.tenant_id,
        )
    except ActionPayloadValidationError as exc:
        execution.append_step(
            STEP_TYPE_PROPOSAL,
            STEP_STATUS_FAILED,
            {"action_id": draft.action_id, "issues": exc.issues},
        )
        return execution.finalize(
            status=AGENT_RUN_FAILED_INVALID_PROPOSAL_STATUS,
            audit_event_type=AGENT_RUN_FAILED_AUDIT_EVENT_TYPE,
            error_reason="proposal_payload_schema_invalid",
            audit_extra={
                "proposed_action_id": draft.action_id,
                "payload_issues": exc.issues,
            },
        )
    except ActionPermissionDenied as exc:
        execution.append_step(
            STEP_TYPE_PROPOSAL,
            STEP_STATUS_BLOCKED,
            {"action_id": draft.action_id, "reason": exc.decision.reason},
        )
        return execution.finalize(
            status=AGENT_RUN_BLOCKED_STATUS,
            audit_event_type=AGENT_RUN_BLOCKED_AUDIT_EVENT_TYPE,
            error_reason="action_run_permission_denied",
            audit_extra={"proposed_action_id": draft.action_id},
        )
    except PlatformPolicyEnforcementDenied:
        execution.append_step(
            STEP_TYPE_PROPOSAL,
            STEP_STATUS_BLOCKED,
            {"action_id": draft.action_id, "reason": "action_run_policy_denied"},
        )
        return execution.finalize(
            status=AGENT_RUN_BLOCKED_STATUS,
            audit_event_type=AGENT_RUN_BLOCKED_AUDIT_EVENT_TYPE,
            error_reason="action_run_policy_denied",
            audit_extra={"proposed_action_id": draft.action_id},
        )
    except ActionRunIdempotencyConflict:
        execution.append_step(
            STEP_TYPE_PROPOSAL,
            STEP_STATUS_FAILED,
            {"action_id": draft.action_id, "reason": "action_run_idempotency_conflict"},
        )
        return execution.finalize(
            status=AGENT_RUN_FAILED_INVALID_PROPOSAL_STATUS,
            audit_event_type=AGENT_RUN_FAILED_AUDIT_EVENT_TYPE,
            error_reason="action_run_idempotency_conflict",
            audit_extra={"proposed_action_id": draft.action_id},
        )


def get_agent_run_result(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    agent_id: str,
    run_id: UUID | str,
) -> AgentRunResult:
    try:
        run_uuid = run_id if isinstance(run_id, UUID) else UUID(run_id)
    except ValueError as exc:
        raise AgentRunNotFound("Agent run not found") from exc
    run = repository.get_agent_run(tenant_id, run_uuid)
    if run is None or run.agent_id != agent_id:
        raise AgentRunNotFound("Agent run not found")
    return _result_from_run(
        run,
        idempotent_replay=False,
        steps=_step_views(repository, tenant_id, run.id),
    )


def list_agent_run_results(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    agent_id: str,
    *,
    cursor_created_at: datetime | None = None,
    cursor_row_id: UUID | None = None,
    limit: int = 100,
) -> list[AgentRunResult]:
    runs = repository.list_agent_runs(
        tenant_id,
        agent_id,
        cursor_created_at=cursor_created_at,
        cursor_row_id=cursor_row_id,
        limit=limit,
    )
    return [_result_from_run(run, idempotent_replay=False) for run in runs]
