"""Governed model invocation pipeline (the model router core).

The pipeline mirrors ``action_runs``: permission check, idempotent replay,
fail-closed platform policy enforcement, a layered egress guard, durable
persistence, the runtime call, result + usage recording and an append-only
audit trail. Routing (:func:`decide_model_route`) is pure and deterministic —
no enabled endpoint matching the request means a blocked decision, never a
silent fallback to an external hop.

Transactions: callers that own the request transaction can opt into three
phases — prepare and commit, external await, idempotent finalize. The requested
row is committed before the provider call, so no database transaction is held
across the external await and the idempotency key is durable if the process
dies mid-call. See
``docs/platform-model-routing.md`` and ADR 0003.

Privacy: prompts and responses are never persisted or audited. The invocation
row and audit payload carry SHA-256 hashes plus token counts; an optional
bounded excerpt (``AXIS_MODEL_INVOCATION_PROMPT_EXCERPT_CHARS``, default 0)
may be stored on the row for debugging, and stays off by default.
"""

import base64
import binascii
import hashlib
import json
import math
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import IntegrityError

from axis_api.audit import AuditEventCreate
from axis_api.demo import ModelRouteTelemetry, OverviewStatus
from axis_api.model_endpoints import (
    SELF_HOSTED_BOUNDARY,
    ModelEndpointRecord,
    model_endpoint_record,
)
from axis_api.model_providers import (
    MODEL_INVOCATION_COMPLETED_STATUS,
    MODEL_INVOCATION_DEFERRED_STATUS,
    ModelInvocationRuntime,
    ModelInvocationRuntimeRequest,
    ModelInvocationRuntimeResult,
    ModelProviderInvocationError,
)
from axis_api.models import ModelInvocation
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    AxisPersistenceRepository,
    ModelInvocationCreate,
    ModelInvocationResultRecord,
)
from axis_api.platform_policies import (
    PlatformPolicyDecision,
    PlatformPolicyEvaluationContext,
    PlatformPolicyScope,
    enforce_platform_policy_deny,
    evaluate_platform_policies,
)
from axis_api.usage_metering import (
    DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
    TenantUsageMetric,
    record_tenant_usage_event,
)

MODEL_INVOKE_SCOPE = "models:invoke"
MODEL_INVOCATION_PLATFORM_POLICY_DOMAIN = "model_routing"
MODEL_INVOCATION_RECORDED_AUDIT_EVENT_TYPE = "model.invocation.recorded"
MODEL_INVOCATION_BLOCKED_AUDIT_EVENT_TYPE = "model.invocation.blocked"
MODEL_INVOCATION_PREVIEWED_AUDIT_EVENT_TYPE = "model.invocation.previewed"

MODEL_INVOCATION_REQUESTED_STATUS = "requested"
MODEL_INVOCATION_FAILED_STATUS = "failed"
MODEL_INVOCATION_COST_BASIS = "estimated_from_endpoint_rates"

COMPLETED_REPLAY_NOTE = (
    "Idempotent replay: the stored invocation record is returned; response "
    "bodies are never persisted, so output_text is empty."
)
# Reachable because the requested row is committed before the provider call:
# a duplicate delivery can now observe an invocation whose outcome is not yet
# known. Re-invoking would risk a second provider call, so the record is
# returned as-is.
IN_FLIGHT_REPLAY_NOTE = (
    "Idempotent replay: the provider call for this idempotency key is still in "
    "flight or was interrupted before its outcome was recorded. No result is "
    "available yet and no second provider call was issued."
)

ROUTE_STATUS_ROUTED = "routed"
ROUTE_STATUS_BLOCKED = "blocked"

EGRESS_ALLOWED_SELF_HOSTED = "allowed_self_hosted"
EGRESS_ALLOWED_WITH_EVIDENCE = "allowed_with_egress_policy_evidence"
EGRESS_BLOCKED_EXTERNAL_DISABLED = "blocked_external_egress_disabled"
EGRESS_BLOCKED_EVIDENCE_MISSING = "blocked_egress_policy_evidence_missing"
EGRESS_BLOCKED_EVIDENCE_INVALID = "blocked_egress_policy_evidence_invalid"

# Deterministic boundary preference for route ties: a self-hosted endpoint
# always wins over one that would require egress evidence.
_BOUNDARY_ROUTE_RANK = {
    "self_hosted": 0,
    "approved_private_endpoint": 1,
    "external": 2,
}

_PREVIEW_PROMPT_CHARS_PER_TOKEN = 4
_PREVIEW_DEFAULT_OUTPUT_TOKEN_ESTIMATE = 256
_COST_QUANTUM = Decimal("0.000001")


class ModelInvocationValidationError(ValueError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class ModelInvocationPermissionDenied(PermissionError):
    def __init__(self, required_permission: str, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permission = required_permission
        self.decision = decision


class ModelInvocationIdempotencyConflict(ValueError):
    def __init__(self, invocation_id: UUID) -> None:
        super().__init__("Idempotency key already exists with a different payload")
        self.invocation_id = invocation_id


class ModelInvocationNotFound(LookupError):
    pass


class ModelInvocationCursorError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ModelEgressBlocked(RuntimeError):
    """The layered egress guard blocked a non-self-hosted model invocation."""

    def __init__(
        self,
        message: str,
        *,
        egress_decision: str,
        route_decision: "ModelRouteDecision",
        audit_event_id: UUID | None = None,
        audit_event_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.egress_decision = egress_decision
        self.route_decision = route_decision
        self.audit_event_id = audit_event_id
        self.audit_event_type = audit_event_type


class ModelRouteDecision(BaseModel):
    status: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    requested_model: str | None = None
    requested_endpoint_id: str | None = None
    endpoint_id: str | None = None
    provider_type: str | None = None
    hosting_boundary: str | None = None
    model_id: str | None = None
    evaluated_endpoint_count: int = Field(ge=0)
    candidate_endpoint_ids: list[str] = Field(default_factory=list)


class ModelInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    actor_id: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=200)
    task_type: str = Field(min_length=1, max_length=120)
    requested_model: str | None = Field(default=None, min_length=1, max_length=160)
    endpoint_id: str | None = Field(default=None, min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=100_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=32_768)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    egress_policy_evidence: dict[str, str] = Field(default_factory=dict)


class ModelInvocationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    actor_id: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    task_type: str = Field(min_length=1, max_length=120)
    requested_model: str | None = Field(default=None, min_length=1, max_length=160)
    endpoint_id: str | None = Field(default=None, min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=100_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=32_768)
    egress_policy_evidence: dict[str, str] = Field(default_factory=dict)


class ModelInvocationResult(BaseModel):
    tenant_id: str = Field(min_length=1)
    invocation_id: UUID
    idempotency_key: str = Field(min_length=1)
    status: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    endpoint_id: str | None = None
    provider_type: str | None = None
    hosting_boundary: str | None = None
    model_id: str | None = None
    requested_by: str = Field(min_length=1)
    output_text: str = Field(default="")
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    estimated_cost_eur: float = Field(default=0.0, ge=0)
    cost_basis: str = Field(default=MODEL_INVOCATION_COST_BASIS, min_length=1)
    egress_decision: str = Field(min_length=1)
    prompt_sha256: str = Field(min_length=64, max_length=64)
    response_sha256: str | None = None
    provider_request_ref: str | None = None
    error_code: str | None = None
    route_decision: ModelRouteDecision
    permission_decision: PermissionDecision
    platform_policy_decision: PlatformPolicyDecision | None = None
    persisted: bool = True
    idempotent_replay: bool = False
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None
    notes: list[str] = Field(default_factory=list)
    created_at: datetime


class ModelInvocationPreview(BaseModel):
    tenant_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    egress_decision: str = Field(min_length=1)
    estimated_input_tokens: int = Field(ge=0)
    estimated_output_tokens: int = Field(ge=0)
    estimated_cost_eur: float = Field(ge=0)
    cost_basis: str = Field(default=MODEL_INVOCATION_COST_BASIS, min_length=1)
    prompt_sha256: str = Field(min_length=64, max_length=64)
    route_decision: ModelRouteDecision
    permission_decision: PermissionDecision
    platform_policy_decision: PlatformPolicyDecision
    audit_event_id: UUID | None = None
    audit_event_type: str | None = None
    notes: list[str] = Field(default_factory=list)


def decide_model_route(
    endpoints: list[ModelEndpointRecord],
    *,
    task_type: str,
    requested_model: str | None = None,
    requested_endpoint_id: str | None = None,
) -> ModelRouteDecision:
    """Deterministically select an enabled endpoint for a task.

    Candidates must be enabled, serve ``task_type`` and — when the caller pins a
    model or endpoint — match it exactly. Ties break on (hosting boundary rank,
    endpoint_id), so a self-hosted endpoint always beats one that would need
    egress. No candidate means a fail-closed blocked decision; there is no
    fallback hop of any kind.
    """
    candidates = [
        endpoint
        for endpoint in endpoints
        if endpoint.status == "enabled"
        and task_type in endpoint.task_types
        and (requested_endpoint_id is None or endpoint.endpoint_id == requested_endpoint_id)
        and (requested_model is None or endpoint.default_model == requested_model)
    ]
    candidates.sort(
        key=lambda endpoint: (
            _BOUNDARY_ROUTE_RANK.get(endpoint.hosting_boundary, len(_BOUNDARY_ROUTE_RANK)),
            endpoint.endpoint_id,
        )
    )
    if not candidates:
        return ModelRouteDecision(
            status=ROUTE_STATUS_BLOCKED,
            reason="no_matching_endpoint",
            task_type=task_type,
            requested_model=requested_model,
            requested_endpoint_id=requested_endpoint_id,
            evaluated_endpoint_count=len(endpoints),
        )

    selected = candidates[0]
    return ModelRouteDecision(
        status=ROUTE_STATUS_ROUTED,
        reason="matched_enabled_endpoint",
        task_type=task_type,
        requested_model=requested_model,
        requested_endpoint_id=requested_endpoint_id,
        endpoint_id=selected.endpoint_id,
        provider_type=selected.provider_type,
        hosting_boundary=selected.hosting_boundary,
        model_id=requested_model or selected.default_model,
        evaluated_endpoint_count=len(endpoints),
        candidate_endpoint_ids=[endpoint.endpoint_id for endpoint in candidates],
    )


def preview_model_invocation(
    repository: AxisPersistenceRepository,
    request: ModelInvocationPreviewRequest,
    *,
    external_model_egress_enabled: bool = False,
) -> ModelInvocationPreview:
    """Evaluate the full governance path for an invocation without calling a provider.

    Permission is enforced (a denied actor cannot probe the registry); the route
    decision, platform policy evaluation, egress decision and cost estimate are
    returned as evidence. No provider call, persistence of the prompt, or token
    consumption happens.
    """
    permission_decision = _evaluate_invoke_permission(
        tenant_id=request.tenant_id,
        actor_id=request.actor_id,
        actor_scopes=request.actor_scopes,
        task_type=request.task_type,
        operation="preview_model_invocation",
    )
    endpoint_registry = _endpoint_records(repository, request.tenant_id)
    route_decision = decide_model_route(
        endpoint_registry,
        task_type=request.task_type,
        requested_model=request.requested_model,
        requested_endpoint_id=request.endpoint_id,
    )
    policy_context, _ = _platform_policy_context(request.task_type)
    platform_policy_decision = evaluate_platform_policies(
        repository,
        tenant_id=request.tenant_id,
        scope=PlatformPolicyScope.MODEL_INVOCATION,
        context=policy_context,
    )
    endpoint = _endpoint_by_id(endpoint_registry, route_decision.endpoint_id)
    egress_decision = (
        _egress_decision(
            endpoint,
            evidence=request.egress_policy_evidence,
            external_model_egress_enabled=external_model_egress_enabled,
        )
        if endpoint is not None
        else "blocked_no_matching_endpoint"
    )
    estimated_input_tokens = _estimated_prompt_tokens(request.prompt)
    estimated_output_tokens = (
        request.max_output_tokens
        if request.max_output_tokens is not None
        else _PREVIEW_DEFAULT_OUTPUT_TOKEN_ESTIMATE
    )
    estimated_cost = (
        _estimated_cost_eur(endpoint, estimated_input_tokens, estimated_output_tokens)
        if endpoint is not None
        else Decimal("0")
    )
    status = (
        "preview_ready"
        if route_decision.status == ROUTE_STATUS_ROUTED
        and egress_decision.startswith("allowed")
        and platform_policy_decision.effect != "deny"
        else "preview_blocked"
    )
    prompt_sha256 = _sha256(request.prompt)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            event_type=MODEL_INVOCATION_PREVIEWED_AUDIT_EVENT_TYPE,
            payload={
                "status": status,
                "task_type": request.task_type,
                "requested_model": request.requested_model,
                "requested_endpoint_id": request.endpoint_id,
                "route_decision": route_decision.model_dump(),
                "egress_decision": egress_decision,
                "estimated_input_tokens": estimated_input_tokens,
                "estimated_output_tokens": estimated_output_tokens,
                "estimated_cost_eur": str(estimated_cost),
                "cost_basis": MODEL_INVOCATION_COST_BASIS,
                "prompt_sha256": prompt_sha256,
                "required_permission": MODEL_INVOKE_SCOPE,
                "permission_decision": permission_decision.model_dump(),
                "platform_policy_effect": platform_policy_decision.effect,
                "provider_call_started": False,
            },
        )
    )
    return ModelInvocationPreview(
        tenant_id=request.tenant_id,
        actor_id=request.actor_id,
        status=status,
        task_type=request.task_type,
        egress_decision=egress_decision,
        estimated_input_tokens=estimated_input_tokens,
        estimated_output_tokens=estimated_output_tokens,
        estimated_cost_eur=float(estimated_cost),
        prompt_sha256=prompt_sha256,
        route_decision=route_decision,
        permission_decision=permission_decision,
        platform_policy_decision=platform_policy_decision,
        audit_event_id=audit_event.id,
        audit_event_type=audit_event.event_type,
        notes=[
            "Preview evaluated permission, routing, platform policy and egress "
            "without any provider call.",
            "The cost figure is an estimate derived from endpoint rates, not a "
            "provider-billed amount.",
        ],
    )


async def invoke_model(
    repository: AxisPersistenceRepository,
    request: ModelInvocationRequest,
    runtime: ModelInvocationRuntime,
    *,
    external_model_egress_enabled: bool = False,
    prompt_excerpt_chars: int = 0,
    usage_metering_enabled: bool = False,
    usage_window_seconds: int = DEFAULT_USAGE_PERIOD_WINDOW_SECONDS,
    commit_before_provider_call: bool = False,
) -> ModelInvocationResult:
    """Run one governed model invocation.

    ``commit_before_provider_call`` states that the caller owns the request
    transaction and that everything pending in the session is this invocation's
    own prepared evidence. The request handler for
    ``POST /platform/models/invocations`` sets it, which closes the transaction
    before the provider call and makes the idempotency key durable. Callers
    that embed an invocation inside a larger unit of work — an agent run, for
    example — leave it unset, because committing there would also commit their
    own partial state.
    """

    permission_decision = _evaluate_invoke_permission(
        tenant_id=request.tenant_id,
        actor_id=request.actor_id,
        actor_scopes=request.actor_scopes,
        task_type=request.task_type,
        operation="invoke_model",
    )
    prompt_sha256 = _sha256(request.prompt)

    existing = repository.get_model_invocation_by_idempotency_key(
        request.tenant_id,
        request.idempotency_key,
    )
    if existing is not None:
        if not _replay_matches_request(existing, request, prompt_sha256):
            raise ModelInvocationIdempotencyConflict(existing.id)
        return _result_from_invocation(
            existing,
            permission_decision=permission_decision,
            idempotent_replay=True,
        )

    policy_context, policy_context_degraded = _platform_policy_context(request.task_type)
    platform_policy_decision = enforce_platform_policy_deny(
        repository,
        tenant_id=request.tenant_id,
        actor_id=request.actor_id,
        scope=PlatformPolicyScope.MODEL_INVOCATION,
        context=policy_context,
        enforcement_point="model_invocation",
        audit_payload={
            "task_type": request.task_type,
            "idempotency_key": request.idempotency_key,
            "context_degraded": policy_context_degraded,
        },
        context_degraded=policy_context_degraded,
    )

    endpoint_registry = _endpoint_records(repository, request.tenant_id)
    route_decision = decide_model_route(
        endpoint_registry,
        task_type=request.task_type,
        requested_model=request.requested_model,
        requested_endpoint_id=request.endpoint_id,
    )
    if route_decision.status != ROUTE_STATUS_ROUTED:
        raise ModelInvocationValidationError(
            "No enabled model endpoint matches the requested task; the route "
            "decision fails closed.",
            "no_matching_endpoint",
        )
    endpoint = _endpoint_by_id(endpoint_registry, route_decision.endpoint_id)
    if endpoint is None:  # defensive: routed decisions always carry a registry endpoint
        raise ModelInvocationValidationError(
            "The routed model endpoint is no longer present in the registry.",
            "routed_endpoint_missing",
        )

    egress_decision = _egress_decision(
        endpoint,
        evidence=request.egress_policy_evidence,
        external_model_egress_enabled=external_model_egress_enabled,
    )
    if not egress_decision.startswith("allowed"):
        audit_event = repository.append_audit_event(
            AuditEventCreate(
                tenant_id=request.tenant_id,
                actor_id=request.actor_id,
                event_type=MODEL_INVOCATION_BLOCKED_AUDIT_EVENT_TYPE,
                payload={
                    "task_type": request.task_type,
                    "idempotency_key": request.idempotency_key,
                    "endpoint_id": endpoint.endpoint_id,
                    "provider_type": endpoint.provider_type,
                    "hosting_boundary": endpoint.hosting_boundary,
                    "model_id": route_decision.model_id,
                    "egress_decision": egress_decision,
                    "egress_policy_id": endpoint.egress_policy_id,
                    "prompt_sha256": prompt_sha256,
                    "route_decision": route_decision.model_dump(),
                    "permission_decision": permission_decision.model_dump(),
                    "provider_call_started": False,
                },
            )
        )
        raise ModelEgressBlocked(
            "External model egress is blocked for this endpoint.",
            egress_decision=egress_decision,
            route_decision=route_decision,
            audit_event_id=audit_event.id,
            audit_event_type=audit_event.event_type,
        )

    # Phase 1 — prepare and commit. The requested row carries the idempotency
    # key together with the route, permission, policy and egress decisions.
    # When the caller owns the transaction, committing it here makes that
    # evidence durable and returns the pooled connection, so nothing stays open
    # across the external await.
    invocation, duplicate_delivery = _prepare_invocation(
        repository,
        ModelInvocationCreate(
            tenant_id=request.tenant_id,
            idempotency_key=request.idempotency_key,
            status=MODEL_INVOCATION_REQUESTED_STATUS,
            task_type=request.task_type,
            endpoint_id=endpoint.endpoint_id,
            provider_type=endpoint.provider_type,
            hosting_boundary=endpoint.hosting_boundary,
            model_id=route_decision.model_id,
            requested_by=request.actor_id,
            route_decision=route_decision.model_dump(),
            permission_decision=permission_decision.model_dump(),
            platform_policy_decision=(
                platform_policy_decision.model_dump()
                if platform_policy_decision.matched
                else None
            ),
            egress_decision=egress_decision,
            prompt_sha256=prompt_sha256,
            prompt_excerpt=_bounded_excerpt(request.prompt, prompt_excerpt_chars),
        ),
        commit=commit_before_provider_call,
    )
    if duplicate_delivery:
        # A concurrent request with the same key won the unique constraint
        # while this one was still routing. Returning its record keeps
        # duplicate delivery to at most one provider call.
        if not _replay_matches_request(invocation, request, prompt_sha256):
            raise ModelInvocationIdempotencyConflict(invocation.id)
        return _result_from_invocation(
            invocation,
            permission_decision=permission_decision,
            idempotent_replay=True,
        )
    invocation_id = invocation.id

    # Phase 2 — external await. With phase 1 committed, no transaction is open
    # here and no lazy attribute load is issued, so the provider timeout cannot
    # occupy a database connection.
    runtime_result = await _call_runtime(
        runtime,
        request=request,
        invocation_id=invocation_id,
        endpoint=endpoint,
        model_id=route_decision.model_id or endpoint.default_model,
    )

    # Phase 3 — idempotent finalize. A new transaction records the outcome
    # against the committed row. If it never commits, the row stays
    # ``requested``: a later retry replays that record instead of issuing a
    # second provider call, because the result of the first one is unknown.
    status = _invocation_status(runtime_result)
    estimated_cost = _estimated_cost_eur(
        endpoint,
        runtime_result.input_tokens,
        runtime_result.output_tokens,
    )
    response_sha256 = _sha256(runtime_result.output_text) if runtime_result.output_text else None

    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            event_type=MODEL_INVOCATION_RECORDED_AUDIT_EVENT_TYPE,
            payload={
                "invocation_id": str(invocation.id),
                "idempotency_key": request.idempotency_key,
                "status": status,
                "task_type": request.task_type,
                "endpoint_id": endpoint.endpoint_id,
                "provider_type": endpoint.provider_type,
                "hosting_boundary": endpoint.hosting_boundary,
                "model_id": route_decision.model_id,
                "adapter": runtime_result.adapter,
                "input_tokens": runtime_result.input_tokens,
                "output_tokens": runtime_result.output_tokens,
                "latency_ms": runtime_result.latency_ms,
                "estimated_cost_eur": str(estimated_cost),
                "cost_basis": MODEL_INVOCATION_COST_BASIS,
                "egress_decision": egress_decision,
                "prompt_sha256": prompt_sha256,
                "response_sha256": response_sha256,
                "provider_request_ref": runtime_result.provider_request_ref or None,
                "error_code": runtime_result.error_code or None,
                "route_decision": route_decision.model_dump(),
                "permission_decision": permission_decision.model_dump(),
                "platform_policy_decision": (
                    platform_policy_decision.model_dump()
                    if platform_policy_decision.matched
                    else None
                ),
            },
        )
    )
    invocation = repository.record_model_invocation_result(
        ModelInvocationResultRecord(
            tenant_id=request.tenant_id,
            invocation_id=invocation.id,
            status=status,
            input_tokens=runtime_result.input_tokens,
            output_tokens=runtime_result.output_tokens,
            latency_ms=runtime_result.latency_ms,
            estimated_cost_eur=estimated_cost,
            response_sha256=response_sha256,
            response_excerpt=_bounded_excerpt(
                runtime_result.output_text, prompt_excerpt_chars
            ),
            provider_request_ref=runtime_result.provider_request_ref or None,
            error_code=runtime_result.error_code or None,
            audit_event_id=audit_event.id,
            audit_event_type=audit_event.event_type,
            notes=runtime_result.notes,
        )
    )

    if usage_metering_enabled and status != MODEL_INVOCATION_DEFERRED_STATUS:
        dimensions = {
            "provider_id": endpoint.endpoint_id,
            "model_id": route_decision.model_id,
        }
        record_tenant_usage_event(
            repository,
            request.tenant_id,
            TenantUsageMetric.MODEL_INVOCATIONS,
            1,
            source_type="model_invocation",
            source_id=str(invocation.id),
            window_seconds=usage_window_seconds,
            occurred_at=invocation.updated_at,
            dimensions=dimensions,
        )
        record_tenant_usage_event(
            repository,
            request.tenant_id,
            TenantUsageMetric.MODEL_INPUT_TOKENS,
            runtime_result.input_tokens,
            source_type="model_invocation",
            source_id=str(invocation.id),
            window_seconds=usage_window_seconds,
            occurred_at=invocation.updated_at,
            dimensions=dimensions,
        )
        record_tenant_usage_event(
            repository,
            request.tenant_id,
            TenantUsageMetric.MODEL_OUTPUT_TOKENS,
            runtime_result.output_tokens,
            source_type="model_invocation",
            source_id=str(invocation.id),
            window_seconds=usage_window_seconds,
            occurred_at=invocation.updated_at,
            dimensions=dimensions,
        )

    return _result_from_invocation(
        invocation,
        permission_decision=permission_decision,
        idempotent_replay=False,
        output_text=runtime_result.output_text,
        runtime_notes=runtime_result.notes,
    )


def get_model_invocation_result(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    invocation_id: UUID | str,
) -> ModelInvocationResult:
    try:
        invocation_uuid = (
            invocation_id if isinstance(invocation_id, UUID) else UUID(invocation_id)
        )
    except ValueError as exc:
        raise ModelInvocationNotFound("Model invocation not found") from exc
    invocation = repository.get_model_invocation(tenant_id, invocation_uuid)
    if invocation is None:
        raise ModelInvocationNotFound("Model invocation not found")
    return _result_from_invocation(invocation, idempotent_replay=False)


def list_model_invocation_results(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    *,
    cursor_created_at: datetime | None = None,
    cursor_row_id: UUID | None = None,
    limit: int = 100,
) -> list[ModelInvocationResult]:
    invocations = repository.list_model_invocations(
        tenant_id,
        cursor_created_at=cursor_created_at,
        cursor_row_id=cursor_row_id,
        limit=limit,
    )
    return [
        _result_from_invocation(invocation, idempotent_replay=False)
        for invocation in invocations
    ]


class ModelInvocationList(BaseModel):
    tenant_id: str = Field(min_length=1)
    invocations: list[ModelInvocationResult] = Field(default_factory=list)
    has_more: bool = False
    next_cursor: str | None = None
    invocation_notes: list[str] = Field(default_factory=list)


class ModelRoutingTelemetryProjection(BaseModel):
    tenant_id: str = Field(min_length=1)
    route_count: int = Field(ge=0)
    routes: list[ModelRouteTelemetry] = Field(default_factory=list)
    telemetry_notes: list[str] = Field(default_factory=list)


def build_model_routing_telemetry(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    *,
    limit: int = 100,
) -> ModelRoutingTelemetryProjection:
    """Project persisted invocations into the reference telemetry shape.

    Route id, token counts, cost, latency, egress decision and audit event id
    all come from real invocation rows — this surface carries no synthetic
    reference data (the demo reference stays at
    ``/demo/manufacturing/model-routing``).
    """
    invocations = repository.list_model_invocations(tenant_id, limit=limit)
    routes = [_route_telemetry_from_invocation(invocation) for invocation in invocations]
    return ModelRoutingTelemetryProjection(
        tenant_id=tenant_id,
        route_count=len(routes),
        routes=routes,
        telemetry_notes=[
            "Routes project persisted model invocations; token counts, latency and "
            "egress decisions are recorded values.",
            "Costs are estimates derived from endpoint rates, never provider-billed "
            "amounts.",
            "Prompt and response bodies are never persisted; evidence is hash-based.",
        ],
    )


def _route_telemetry_from_invocation(invocation) -> ModelRouteTelemetry:
    route_decision = invocation.route_decision or {}
    hosting_boundary = invocation.hosting_boundary or "unrouted"
    external_requested = invocation.hosting_boundary is not None and (
        invocation.hosting_boundary != SELF_HOSTED_BOUNDARY
    )
    egress_allowed = invocation.egress_decision.startswith("allowed")
    if invocation.status == "completed":
        route_status = OverviewStatus.READY
    elif invocation.status in {MODEL_INVOCATION_DEFERRED_STATUS, "requested"}:
        route_status = OverviewStatus.WATCH
    else:
        route_status = OverviewStatus.ACTION_REQUIRED
    return ModelRouteTelemetry(
        route_id=str(invocation.id),
        agent_id=invocation.requested_by,
        agent_name=invocation.requested_by,
        domain=invocation.task_type,
        provider_id=invocation.endpoint_id or "unrouted",
        provider_name=invocation.endpoint_id or "unrouted",
        model=invocation.model_id or "unrouted",
        model_policy=hosting_boundary,
        prompt_classification="hash_only_no_body_persisted",
        data_boundary=hosting_boundary,
        external_egress_requested=external_requested,
        external_egress_allowed=external_requested and egress_allowed,
        egress_decision=invocation.egress_decision,
        decision_reason=str(route_decision.get("reason", "routed")),
        route_status=route_status,
        input_tokens=invocation.input_tokens,
        output_tokens=invocation.output_tokens,
        estimated_cost_eur=float(invocation.estimated_cost_eur),
        latency_ms=invocation.latency_ms,
        cost_center="platform-model-routing",
        required_permissions=[MODEL_INVOKE_SCOPE],
        evidence_refs=[f"model_invocation:{invocation.id}"],
        audit_event_id=(
            str(invocation.audit_event_id)
            if invocation.audit_event_id is not None
            else "pending"
        ),
        observability_events=[
            invocation.audit_event_type or MODEL_INVOCATION_RECORDED_AUDIT_EVENT_TYPE
        ],
    )


def encode_model_invocation_cursor(result: "ModelInvocationResult") -> str:
    payload = {
        "created_at": _ensure_utc(result.created_at).isoformat(),
        "row_id": str(result.invocation_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_model_invocation_cursor(
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
        raise ModelInvocationCursorError("invalid_model_invocation_cursor") from exc
    return _ensure_utc(created_at), row_id


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _call_runtime_request(
    request: ModelInvocationRequest,
    *,
    invocation_id: UUID,
    endpoint: ModelEndpointRecord,
    model_id: str,
) -> ModelInvocationRuntimeRequest:
    return ModelInvocationRuntimeRequest(
        tenant_id=request.tenant_id,
        invocation_id=str(invocation_id),
        endpoint_id=endpoint.endpoint_id,
        base_url=endpoint.base_url,
        model_id=model_id,
        prompt=request.prompt,
        max_output_tokens=request.max_output_tokens,
        temperature=request.temperature,
    )


def _prepare_invocation(
    repository: AxisPersistenceRepository,
    record: ModelInvocationCreate,
    *,
    commit: bool,
) -> tuple[ModelInvocation, bool]:
    """Persist the requested row, optionally committing it.

    Returns the invocation and whether a concurrent request had already claimed
    the idempotency key. Committing here ends the transaction before the
    provider call; the unique constraint on tenant and idempotency key is what
    makes a concurrent duplicate observable instead of fatal.
    """

    if not commit:
        return repository.create_model_invocation(record), False
    try:
        # The insert is flushed here, so the unique constraint can already
        # fire before the commit does.
        invocation = repository.create_model_invocation(record)
        repository.session.commit()
    except IntegrityError:
        repository.session.rollback()
        existing = repository.get_model_invocation_by_idempotency_key(
            record.tenant_id,
            record.idempotency_key,
        )
        if existing is None:
            # The conflict was not the tenant/idempotency uniqueness contract,
            # so it is not ours to translate into an idempotent replay.
            raise
        return existing, True
    # The session is configured with ``expire_on_commit=False``, so the
    # committed row stays readable without a second query.
    return invocation, False


async def _call_runtime(
    runtime: ModelInvocationRuntime,
    *,
    request: ModelInvocationRequest,
    invocation_id: UUID,
    endpoint: ModelEndpointRecord,
    model_id: str,
) -> ModelInvocationRuntimeResult:
    runtime_request = _call_runtime_request(
        request,
        invocation_id=invocation_id,
        endpoint=endpoint,
        model_id=model_id,
    )
    try:
        return await runtime.invoke(runtime_request)
    except ModelProviderInvocationError as exc:
        return ModelInvocationRuntimeResult(
            adapter=getattr(runtime, "adapter_name", "axis-model-invocation-adapter"),
            status=MODEL_INVOCATION_FAILED_STATUS,
            latency_ms=exc.latency_ms,
            error_code=exc.error_code,
            error_message=exc.message,
            notes=[
                "The model provider call failed; no output was fabricated.",
                f"Provider failure code: {exc.error_code}.",
            ],
        )


def _invocation_status(runtime_result: ModelInvocationRuntimeResult) -> str:
    if runtime_result.status == MODEL_INVOCATION_COMPLETED_STATUS:
        return "completed"
    if runtime_result.status == MODEL_INVOCATION_DEFERRED_STATUS:
        return MODEL_INVOCATION_DEFERRED_STATUS
    return MODEL_INVOCATION_FAILED_STATUS


def _replay_matches_request(
    invocation,
    request: ModelInvocationRequest,
    prompt_sha256: str,
) -> bool:
    stored_route = invocation.route_decision or {}
    return (
        invocation.task_type == request.task_type
        and invocation.prompt_sha256 == prompt_sha256
        and stored_route.get("requested_model") == request.requested_model
        and stored_route.get("requested_endpoint_id") == request.endpoint_id
    )


def _result_from_invocation(
    invocation,
    *,
    permission_decision: PermissionDecision | None = None,
    idempotent_replay: bool,
    output_text: str = "",
    runtime_notes: list[str] | None = None,
) -> ModelInvocationResult:
    notes = list(runtime_notes or invocation.notes or [])
    if idempotent_replay:
        notes.append(
            IN_FLIGHT_REPLAY_NOTE
            if invocation.status == MODEL_INVOCATION_REQUESTED_STATUS
            else COMPLETED_REPLAY_NOTE
        )
    return ModelInvocationResult(
        tenant_id=invocation.tenant_id,
        invocation_id=invocation.id,
        idempotency_key=invocation.idempotency_key,
        status=invocation.status,
        task_type=invocation.task_type,
        endpoint_id=invocation.endpoint_id,
        provider_type=invocation.provider_type,
        hosting_boundary=invocation.hosting_boundary,
        model_id=invocation.model_id,
        requested_by=invocation.requested_by,
        output_text=output_text,
        input_tokens=invocation.input_tokens,
        output_tokens=invocation.output_tokens,
        latency_ms=invocation.latency_ms,
        estimated_cost_eur=float(invocation.estimated_cost_eur),
        egress_decision=invocation.egress_decision,
        prompt_sha256=invocation.prompt_sha256,
        response_sha256=invocation.response_sha256,
        provider_request_ref=invocation.provider_request_ref,
        error_code=invocation.error_code,
        route_decision=ModelRouteDecision.model_validate(invocation.route_decision),
        permission_decision=(
            permission_decision
            if permission_decision is not None
            else PermissionDecision.model_validate(invocation.permission_decision)
        ),
        platform_policy_decision=(
            PlatformPolicyDecision.model_validate(invocation.platform_policy_decision)
            if invocation.platform_policy_decision
            else None
        ),
        persisted=True,
        idempotent_replay=idempotent_replay,
        audit_event_id=invocation.audit_event_id,
        audit_event_type=invocation.audit_event_type,
        notes=notes,
        created_at=invocation.created_at,
    )


def _endpoint_records(
    repository: AxisPersistenceRepository,
    tenant_id: str,
) -> list[ModelEndpointRecord]:
    return [
        model_endpoint_record(record)
        for record in repository.list_model_endpoints(tenant_id, limit=200)
    ]


def _endpoint_by_id(
    endpoints: list[ModelEndpointRecord],
    endpoint_id: str | None,
) -> ModelEndpointRecord | None:
    if endpoint_id is None:
        return None
    return next(
        (endpoint for endpoint in endpoints if endpoint.endpoint_id == endpoint_id),
        None,
    )


def _egress_decision(
    endpoint: ModelEndpointRecord,
    *,
    evidence: dict[str, str],
    external_model_egress_enabled: bool,
) -> str:
    """Layered egress guard for non-self-hosted endpoints.

    Layer 1: the deployment-level ``AXIS_EXTERNAL_MODEL_EGRESS_ENABLED`` flag
    must be on. Layer 2: the caller must present validated egress-policy
    evidence naming the endpoint's registered egress policy (mirroring the
    connector execution evidence contract). Both layers fail closed.
    """
    if endpoint.hosting_boundary == SELF_HOSTED_BOUNDARY:
        return EGRESS_ALLOWED_SELF_HOSTED
    if not external_model_egress_enabled:
        return EGRESS_BLOCKED_EXTERNAL_DISABLED
    if not evidence:
        return EGRESS_BLOCKED_EVIDENCE_MISSING
    evidence_valid = (
        evidence.get("egress_policy_evidence_status", "") == "validated"
        and evidence.get("egress_policy_result_status", "") == "egress_policy_approved"
        and evidence.get("egress_policy_mode", "") == endpoint.hosting_boundary
        and endpoint.egress_policy_id is not None
        and evidence.get("egress_policy_id", "") == endpoint.egress_policy_id
    )
    if not evidence_valid:
        return EGRESS_BLOCKED_EVIDENCE_INVALID
    return EGRESS_ALLOWED_WITH_EVIDENCE


def _platform_policy_context(
    task_type: str,
) -> tuple[PlatformPolicyEvaluationContext, bool]:
    """Build the policy context; a malformed task type degrades the context.

    A degraded context makes ``enforce_platform_policy_deny`` fail closed
    against any active deny policy instead of letting malformed input evade
    policy matching.
    """
    try:
        return (
            PlatformPolicyEvaluationContext(
                action_id=task_type,
                action_domain=MODEL_INVOCATION_PLATFORM_POLICY_DOMAIN,
            ),
            False,
        )
    except ValidationError:
        return (
            PlatformPolicyEvaluationContext(
                action_domain=MODEL_INVOCATION_PLATFORM_POLICY_DOMAIN,
            ),
            True,
        )


def _evaluate_invoke_permission(
    *,
    tenant_id: str,
    actor_id: str,
    actor_scopes: list[str],
    task_type: str,
    operation: str,
) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_scopes=actor_scopes,
            required_scopes=[MODEL_INVOKE_SCOPE],
            attributes={
                "task_type": task_type,
                "operation": operation,
            },
        )
    )
    if not decision.allowed:
        raise ModelInvocationPermissionDenied(MODEL_INVOKE_SCOPE, decision)
    return decision


def _estimated_cost_eur(
    endpoint: ModelEndpointRecord,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    cost = (
        Decimal(input_tokens) * Decimal(str(endpoint.cost_input_per_1k))
        + Decimal(output_tokens) * Decimal(str(endpoint.cost_output_per_1k))
    ) / Decimal(1000)
    return cost.quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP)


def _estimated_prompt_tokens(prompt: str) -> int:
    return max(1, math.ceil(len(prompt) / _PREVIEW_PROMPT_CHARS_PER_TOKEN))


def _bounded_excerpt(text: str, excerpt_chars: int) -> str | None:
    if excerpt_chars <= 0 or not text:
        return None
    return text[:excerpt_chars]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
