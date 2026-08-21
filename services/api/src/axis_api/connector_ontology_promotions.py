from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from axis_api.audit import AuditEventCreate
from axis_api.connector_ontology_proposals import ConnectorOntologyProposalRecord
from axis_api.connector_reference import require_persisted_manufacturing_connector_registry
from axis_api.ontology.mutations import (
    DeferredOntologyMutationRuntime,
    OntologyMutationError,
    OntologyMutationRequest,
    OntologyMutationResult,
    OntologyMutationRuntime,
    ontology_mutation_failure_result,
)
from axis_api.permissions import PermissionDecision, PermissionRequest, evaluate_permission
from axis_api.persistence import (
    AxisPersistenceRepository,
    ConnectorOntologyPromotionCreate,
    ConnectorOntologyPromotionResultRecord,
)


class ConnectorOntologyPromotionNotFound(LookupError):
    pass


class ConnectorOntologyPromotionValidationError(ValueError):
    def __init__(
        self,
        message: str,
        reason: str,
        audit_event_id: UUID | None = None,
        audit_event_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.audit_event_id = audit_event_id
        self.audit_event_type = audit_event_type


class ConnectorOntologyPromotionPermissionDenied(PermissionError):
    def __init__(self, required_permission: str, decision: PermissionDecision) -> None:
        super().__init__(decision.reason)
        self.required_permission = required_permission
        self.decision = decision


class ConnectorOntologyPromotionIdempotencyConflict(ValueError):
    def __init__(self, promotion_id: str) -> None:
        super().__init__("Idempotency key already exists with a different payload")
        self.promotion_id = promotion_id


class ConnectorOntologyPromotionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(default="tenant_demo_manufacturing", min_length=1)
    promotion_id: str = Field(min_length=1, max_length=180, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    idempotency_key: str = Field(min_length=1, max_length=200)
    proposal_id: str = Field(min_length=1, max_length=180)
    manual_import_id: str = Field(min_length=1, max_length=180)
    actor_id: str = Field(min_length=1, max_length=160)
    actor_scopes: list[str] = Field(default_factory=list)
    promotion_mode: str = Field(default="approved_manual_import", min_length=1, max_length=80)
    policy_id: str | None = Field(default=None, min_length=1, max_length=180)
    note: str | None = Field(default=None, max_length=600)


class ConnectorPromotionPolicyDecision(BaseModel):
    status: str = Field(min_length=1)
    allowed: bool
    policy_id: str | None = None
    policy_version: str | None = None
    policy_set_id: str | None = None
    policy_set_version: str | None = None
    policy_ids: list[str] = Field(default_factory=list)
    policy_results: list[dict] = Field(default_factory=list)
    enforcement_mode: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    required_scopes: list[str] = Field(default_factory=list)
    matched_constraints: dict[str, str] = Field(default_factory=dict)


class ConnectorOntologyPromotionRecord(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    promotion_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    manual_import_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    promotion_mode: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    graph_mutation_status: str = Field(min_length=1)
    ontology_mutation: OntologyMutationResult
    policy_id: str | None = None
    policy_set_id: str | None = None
    policy_ids: list[str] | None = None
    policy_decision: ConnectorPromotionPolicyDecision | None = None
    audit_event_id: UUID | None = None
    audit_event_type: str = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime


class ConnectorOntologyPromotionResult(BaseModel):
    tenant_id: str = Field(min_length=1)
    connector_id: str = Field(min_length=1)
    promotion_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    manual_import_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    graph_mutation_status: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    proposal: ConnectorOntologyProposalRecord
    promotion: ConnectorOntologyPromotionRecord
    permission_decision: PermissionDecision
    ontology_mutation: OntologyMutationResult
    policy_id: str | None = None
    policy_set_id: str | None = None
    policy_ids: list[str] | None = None
    policy_decision: ConnectorPromotionPolicyDecision | None = None
    audit_event_id: UUID
    audit_event_type: str = Field(min_length=1)
    idempotent_replay: bool = False


REQUIRED_PROMOTION_SCOPE = "connectors:ontology:promote"
PROMOTION_MODE = "approved_manual_import"
APPLIED_AUDIT_EVENT_TYPE = "connector.ontology_promotion.applied"
DEFERRED_AUDIT_EVENT_TYPE = "connector.ontology_promotion.deferred"
FAILED_AUDIT_EVENT_TYPE = "connector.ontology_promotion.failed"
REJECTED_AUDIT_EVENT_TYPE = "connector.ontology_promotion.rejected"


def record_demo_connector_ontology_promotion(
    repository: AxisPersistenceRepository,
    request: ConnectorOntologyPromotionRequest,
    ontology_mutation_runtime: OntologyMutationRuntime | None = None,
) -> ConnectorOntologyPromotionResult:
    if request.promotion_mode != PROMOTION_MODE:
        raise ConnectorOntologyPromotionValidationError(
            "Connector ontology promotions require approved_manual_import mode.",
            "unsupported_promotion_mode",
        )

    existing = repository.get_connector_ontology_promotion_by_idempotency_key(
        request.tenant_id,
        request.idempotency_key,
    )
    if existing is not None:
        replay_policy_identity = _policy_identity_for_idempotency_replay(existing, request)
        if _fingerprint_from_existing(existing) != _fingerprint_from_request(
            request,
            policy_id=replay_policy_identity["policy_id"],
            policy_set_id=replay_policy_identity["policy_set_id"],
            policy_ids=replay_policy_identity["policy_ids"],
        ):
            raise ConnectorOntologyPromotionIdempotencyConflict(existing.promotion_id)
        proposal = repository.get_connector_ontology_proposal(
            existing.tenant_id,
            existing.proposal_id,
        )
        if proposal is None:
            raise ConnectorOntologyPromotionNotFound("Connector ontology proposal not found")
        return _result_from_existing(existing, proposal, idempotent_replay=True)

    proposal = repository.get_connector_ontology_proposal(request.tenant_id, request.proposal_id)
    if proposal is None:
        raise ConnectorOntologyPromotionNotFound("Connector ontology proposal not found")
    _validate_proposal_promotable(proposal)
    manual_import = repository.get_connector_manual_import_request(
        request.tenant_id,
        request.manual_import_id,
    )
    _validate_manual_import_for_promotion(manual_import, request.proposal_id)
    manifest = _active_preview_manifest_for_connector(
        repository,
        request.tenant_id,
        proposal.connector_id,
    )
    permission_decision = _evaluate_promotion_permission(request, proposal, manual_import)
    policy_decision = _evaluate_promotion_policy(
        repository,
        request,
        proposal,
        manual_import,
        permission_decision,
    )
    effective_policy_id = policy_decision.policy_id if policy_decision else request.policy_id
    effective_policy_set_id = policy_decision.policy_set_id if policy_decision else None
    effective_policy_ids = policy_decision.policy_ids if policy_decision else None

    mutation_request = OntologyMutationRequest(
        tenant_id=proposal.tenant_id,
        connector_id=proposal.connector_id,
        promotion_id=request.promotion_id,
        proposal_id=proposal.proposal_id,
        manual_import_id=manual_import.import_id,
        actor_id=request.actor_id,
        node_id=proposal.node_id,
        node_type=proposal.node_type,
        ontology_type=proposal.ontology_type,
        field_summary=proposal.field_summary,
        evidence_refs=proposal.evidence_refs,
    )
    runtime = ontology_mutation_runtime or DeferredOntologyMutationRuntime()
    try:
        ontology_mutation = runtime.promote_connector_proposal(mutation_request)
    except OntologyMutationError as exc:
        ontology_mutation = ontology_mutation_failure_result(
            mutation_request,
            reason=str(exc),
            status=getattr(exc, "status", "type_db_mutation_unavailable"),
        )

    promotion_status = _promotion_status(ontology_mutation)
    audit_event_type = _audit_event_type(ontology_mutation)
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            event_type=audit_event_type,
            payload={
                "connector_id": proposal.connector_id,
                "promotion_id": request.promotion_id,
                "proposal_id": proposal.proposal_id,
                "manual_import_id": manual_import.import_id,
                "promotion_mode": request.promotion_mode,
                "policy_id": effective_policy_id,
                "policy_set_id": effective_policy_set_id,
                "policy_ids": effective_policy_ids,
                "policy_decision": policy_decision.model_dump() if policy_decision else None,
                "status": promotion_status,
                "graph_mutation_status": ontology_mutation.status,
                "runtime_boundary": manifest.runtime_boundary,
                "required_permission": REQUIRED_PROMOTION_SCOPE,
                "permission_decision": permission_decision.model_dump(),
                "ontology_mutation": ontology_mutation.model_dump(),
                "node_id": proposal.node_id,
                "node_type": proposal.node_type,
                "ontology_type": proposal.ontology_type,
                "field_summary_keys": sorted(proposal.field_summary.keys()),
                "decision_note_recorded": str(request.note is not None).lower(),
            },
        )
    )
    promotion = repository.create_connector_ontology_promotion(
        ConnectorOntologyPromotionCreate(
            tenant_id=request.tenant_id,
            connector_id=proposal.connector_id,
            promotion_id=request.promotion_id,
            idempotency_key=request.idempotency_key,
            proposal_id=proposal.proposal_id,
            manual_import_id=manual_import.import_id,
            status=promotion_status,
            promotion_mode=request.promotion_mode,
            requested_by=request.actor_id,
            graph_mutation_status=ontology_mutation.status,
            ontology_mutation=ontology_mutation.model_dump(),
            permission_decision=permission_decision.model_dump(),
            policy_id=effective_policy_id,
            policy_set_id=effective_policy_set_id,
            policy_ids=effective_policy_ids,
            policy_decision=policy_decision.model_dump() if policy_decision else None,
            audit_event_id=audit_event.id,
            audit_event_type=audit_event.event_type,
            notes=[request.note] if request.note else [],
        )
    )

    if ontology_mutation.status == "type_db_mutation_applied":
        proposal = repository.record_connector_ontology_proposal_promotion(
            ConnectorOntologyPromotionResultRecord(
                tenant_id=proposal.tenant_id,
                proposal_id=proposal.proposal_id,
                status=promotion_status,
                graph_mutation_status=ontology_mutation.status,
                promotion_id=request.promotion_id,
                promoted_by=request.actor_id,
                ontology_mutation=ontology_mutation.model_dump(),
                policy_id=effective_policy_id,
                policy_set_id=effective_policy_set_id,
                policy_ids=effective_policy_ids,
                policy_decision=policy_decision.model_dump() if policy_decision else None,
                audit_event_id=audit_event.id,
                audit_event_type=audit_event.event_type,
            )
        )

    return ConnectorOntologyPromotionResult(
        tenant_id=request.tenant_id,
        connector_id=proposal.connector_id,
        promotion_id=request.promotion_id,
        proposal_id=proposal.proposal_id,
        manual_import_id=manual_import.import_id,
        status=promotion_status,
        graph_mutation_status=ontology_mutation.status,
        actor_id=request.actor_id,
        proposal=_proposal_from_record(proposal),
        promotion=_promotion_from_record(promotion),
        permission_decision=permission_decision,
        ontology_mutation=ontology_mutation,
        policy_id=effective_policy_id,
        policy_set_id=effective_policy_set_id,
        policy_ids=effective_policy_ids,
        policy_decision=policy_decision,
        audit_event_id=audit_event.id,
        audit_event_type=audit_event.event_type,
        idempotent_replay=False,
    )


def _validate_proposal_promotable(proposal) -> None:
    if proposal.status == "promoted_to_graph":
        raise ConnectorOntologyPromotionValidationError(
            "Connector ontology proposal has already been promoted.",
            "proposal_already_promoted",
        )
    if proposal.status != "proposed_from_preview":
        raise ConnectorOntologyPromotionValidationError(
            "Connector ontology proposal is not waiting for promotion.",
            "proposal_not_promotable",
        )
    if proposal.graph_mutation_status != "not_applied":
        raise ConnectorOntologyPromotionValidationError(
            "Connector ontology proposal graph mutation status is not promotable.",
            "proposal_graph_status_not_promotable",
        )


def _validate_manual_import_for_promotion(manual_import, proposal_id: str) -> None:
    if manual_import is None:
        raise ConnectorOntologyPromotionValidationError(
            "Manual import approval evidence is required before promotion.",
            "manual_import_not_found",
        )
    if proposal_id not in manual_import.proposal_ids:
        raise ConnectorOntologyPromotionValidationError(
            "Manual import does not reference this ontology proposal.",
            "manual_import_proposal_mismatch",
        )
    if manual_import.status != "approval_approved" or manual_import.decision != "approve":
        raise ConnectorOntologyPromotionValidationError(
            "Manual import must be approved before ontology promotion.",
            "manual_import_not_approved",
        )
    if manual_import.workflow_signal is None:
        raise ConnectorOntologyPromotionValidationError(
            "Manual import workflow signal evidence is required before promotion.",
            "manual_import_missing_workflow_signal",
        )
    if manual_import.workflow_signal_status == "runtime_signal_unavailable":
        raise ConnectorOntologyPromotionValidationError(
            "Manual import workflow signal must not be unavailable before promotion.",
            "manual_import_workflow_signal_unavailable",
        )


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
    raise ConnectorOntologyPromotionValidationError(
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
        raise ConnectorOntologyPromotionValidationError(
            "Connector manifest must be registered before ontology promotion.",
            "connector_manifest_not_found",
        )
    # active_live is the stricter lifecycle state (it requires active_preview
    # first plus live enablement evidence), and governed live sync only runs on
    # active_live manifests, so its proposals must stay promotable there.
    if manifest.status not in {"active_preview", "active_live"}:
        raise ConnectorOntologyPromotionValidationError(
            "Connector manifest must be active_preview before ontology promotion.",
            "connector_manifest_not_active_preview",
        )
    return manifest


def _evaluate_promotion_permission(request, proposal, manual_import) -> PermissionDecision:
    decision = evaluate_permission(
        PermissionRequest(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            actor_scopes=request.actor_scopes,
            required_scopes=[REQUIRED_PROMOTION_SCOPE],
            attributes={
                "connector_id": proposal.connector_id,
                "proposal_id": proposal.proposal_id,
                "manual_import_id": manual_import.import_id,
                "node_id": proposal.node_id,
                "node_type": proposal.node_type,
                "ontology_type": proposal.ontology_type,
                "risk_level": proposal.field_summary.get("risk_level"),
            },
        )
    )
    if not decision.allowed:
        raise ConnectorOntologyPromotionPermissionDenied(REQUIRED_PROMOTION_SCOPE, decision)
    return decision


def _evaluate_promotion_policy(
    repository: AxisPersistenceRepository,
    request: ConnectorOntologyPromotionRequest,
    proposal,
    manual_import,
    permission_decision: PermissionDecision,
) -> ConnectorPromotionPolicyDecision | None:
    active_policy_sets = repository.list_active_connector_promotion_policy_sets(
        request.tenant_id,
        proposal.connector_id,
    )
    if len(active_policy_sets) > 1:
        raise ConnectorOntologyPromotionValidationError(
            "Multiple active policy sets match this connector promotion.",
            "promotion_policy_set_selection_ambiguous",
        )
    if len(active_policy_sets) == 1:
        if request.policy_id is not None:
            policy_set = active_policy_sets[0]
            policy_decision = _required_policy_set_decision(
                requested_policy_id=request.policy_id,
                policy_set=policy_set,
                manual_import=manual_import,
                proposal=proposal,
            )
            _raise_policy_rejection_with_audit(
                repository=repository,
                request=request,
                proposal=proposal,
                manual_import=manual_import,
                permission_decision=permission_decision,
                policy_decision=policy_decision,
                message="Active connector promotion policy sets require set-level evaluation.",
                rejection_reason="promotion_policy_set_required",
            )
        return _evaluate_promotion_policy_set(
            repository,
            request,
            proposal,
            manual_import,
            permission_decision,
            active_policy_sets[0],
        )

    selection_mode = "explicit"
    if request.policy_id is None:
        policy = _select_required_promotion_policy(
            repository,
            request.tenant_id,
            proposal.connector_id,
        )
        if policy is None:
            return None
        selection_mode = "auto_required"
    else:
        policy = repository.get_connector_promotion_policy(request.tenant_id, request.policy_id)
    if policy is None:
        raise ConnectorOntologyPromotionValidationError(
            "Connector promotion policy was not found for this tenant.",
            "promotion_policy_not_found",
        )
    if policy.connector_id != proposal.connector_id:
        raise ConnectorOntologyPromotionValidationError(
            "Connector promotion policy does not apply to this connector.",
            "promotion_policy_connector_mismatch",
        )

    matched_constraints = {
        "policy_status": policy.status,
        "manual_import_status": manual_import.status,
        "workflow_signal_status": manual_import.workflow_signal_status,
        "risk_level": manual_import.risk_level,
        "ontology_type": proposal.ontology_type,
        "selection_mode": selection_mode,
    }
    if policy.status != "enabled" or policy.enforcement_mode != "required":
        return ConnectorPromotionPolicyDecision(
            status="policy_advisory",
            allowed=True,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_ids=[policy.policy_id],
            policy_results=[
                {
                    "policy_id": policy.policy_id,
                    "status": "policy_advisory",
                    "allowed": True,
                    "reason": "policy_not_enforced",
                }
            ],
            enforcement_mode=policy.enforcement_mode,
            reason="policy_not_enforced",
            required_scopes=policy.required_scopes,
            matched_constraints=matched_constraints,
        )

    violations = _policy_violations(policy, request, proposal, manual_import)

    if violations:
        policy_decision = _rejected_policy_decision(
            policy=policy,
            violations=violations,
            matched_constraints=matched_constraints,
        )
        _raise_policy_rejection_with_audit(
            repository=repository,
            request=request,
            proposal=proposal,
            manual_import=manual_import,
            permission_decision=permission_decision,
            policy_decision=policy_decision,
            message="Connector promotion policy rejected this promotion.",
            rejection_reason="promotion_policy_rejected",
        )

    return ConnectorPromotionPolicyDecision(
        status="policy_enforced",
        allowed=True,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_ids=[policy.policy_id],
        policy_results=[
            {
                "policy_id": policy.policy_id,
                "status": "policy_enforced",
                "allowed": True,
                "reason": "policy_constraints_satisfied",
            }
        ],
        enforcement_mode=policy.enforcement_mode,
        reason="policy_constraints_satisfied",
        required_scopes=policy.required_scopes,
        matched_constraints=matched_constraints,
    )


def _evaluate_promotion_policy_set(
    repository: AxisPersistenceRepository,
    request: ConnectorOntologyPromotionRequest,
    proposal,
    manual_import,
    permission_decision: PermissionDecision,
    policy_set,
) -> ConnectorPromotionPolicyDecision:
    policies = []
    for policy_id in policy_set.policy_ids:
        policy = repository.get_connector_promotion_policy(request.tenant_id, policy_id)
        if policy is None:
            raise ConnectorOntologyPromotionValidationError(
                "Connector promotion policy set references an unknown policy.",
                "promotion_policy_set_policy_not_found",
            )
        if policy.connector_id != proposal.connector_id:
            raise ConnectorOntologyPromotionValidationError(
                "Connector promotion policy set references another connector.",
                "promotion_policy_set_connector_mismatch",
            )
        if policy.status != "enabled" or policy.enforcement_mode != "required":
            raise ConnectorOntologyPromotionValidationError(
                "Connector promotion policy set references a non-required policy.",
                "promotion_policy_set_policy_not_enabled_required",
            )
        policies.append(policy)

    required_policy_ids = {
        policy.policy_id
        for policy in repository.list_connector_promotion_policies(
            tenant_id=request.tenant_id,
            connector_id=proposal.connector_id,
            status="enabled",
        )
        if policy.enforcement_mode == "required"
    }
    if set(policy_set.policy_ids) != required_policy_ids:
        raise ConnectorOntologyPromotionValidationError(
            "Connector promotion policy set does not cover the active required policies.",
            "promotion_policy_set_incomplete",
        )

    policy_results = []
    for policy in policies:
        violations = _policy_violations(policy, request, proposal, manual_import)
        if violations:
            policy_results.append(
                {
                    "policy_id": policy.policy_id,
                    "policy_version": policy.policy_version,
                    "status": "policy_rejected",
                    "allowed": False,
                    "reason": "policy_constraints_failed",
                    "violations": violations,
                }
            )
            policy_decision = _rejected_policy_set_decision(
                policy_set=policy_set,
                policies=policies,
                policy_results=policy_results,
                manual_import=manual_import,
                proposal=proposal,
            )
            _raise_policy_rejection_with_audit(
                repository=repository,
                request=request,
                proposal=proposal,
                manual_import=manual_import,
                permission_decision=permission_decision,
                policy_decision=policy_decision,
                message="Connector promotion policy rejected this promotion.",
                rejection_reason="promotion_policy_rejected",
            )
        policy_results.append(
            {
                "policy_id": policy.policy_id,
                "policy_version": policy.policy_version,
                "status": "policy_enforced",
                "allowed": True,
                "reason": "policy_constraints_satisfied",
            }
        )

    policy_ids = [policy.policy_id for policy in policies]
    required_scopes = sorted({scope for policy in policies for scope in policy.required_scopes})
    matched_constraints = {
        "policy_set_status": policy_set.status,
        "manual_import_status": manual_import.status,
        "workflow_signal_status": manual_import.workflow_signal_status,
        "risk_level": manual_import.risk_level,
        "ontology_type": proposal.ontology_type,
        "selection_mode": "active_policy_set",
        "policy_count": str(len(policy_ids)),
    }
    return ConnectorPromotionPolicyDecision(
        status="policy_set_enforced",
        allowed=True,
        policy_id=policy_ids[0],
        policy_version=policies[0].policy_version,
        policy_set_id=policy_set.policy_set_id,
        policy_set_version=policy_set.policy_set_version,
        policy_ids=policy_ids,
        policy_results=policy_results,
        enforcement_mode="required",
        reason="policy_set_constraints_satisfied",
        required_scopes=required_scopes,
        matched_constraints=matched_constraints,
    )


def _rejected_policy_decision(
    *,
    policy,
    violations: list[str],
    matched_constraints: dict[str, str],
) -> ConnectorPromotionPolicyDecision:
    return ConnectorPromotionPolicyDecision(
        status="policy_rejected",
        allowed=False,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_ids=[policy.policy_id],
        policy_results=[
            {
                "policy_id": policy.policy_id,
                "policy_version": policy.policy_version,
                "status": "policy_rejected",
                "allowed": False,
                "reason": "policy_constraints_failed",
                "violations": violations,
            }
        ],
        enforcement_mode=policy.enforcement_mode,
        reason="policy_constraints_failed",
        required_scopes=policy.required_scopes,
        matched_constraints=matched_constraints,
    )


def _rejected_policy_set_decision(
    *,
    policy_set,
    policies: list,
    policy_results: list[dict],
    manual_import,
    proposal,
) -> ConnectorPromotionPolicyDecision:
    policy_ids = [policy.policy_id for policy in policies]
    required_scopes = sorted({scope for policy in policies for scope in policy.required_scopes})
    matched_constraints = {
        "policy_set_status": policy_set.status,
        "manual_import_status": manual_import.status,
        "workflow_signal_status": manual_import.workflow_signal_status,
        "risk_level": manual_import.risk_level,
        "ontology_type": proposal.ontology_type,
        "selection_mode": "active_policy_set",
        "policy_count": str(len(policy_ids)),
    }
    return ConnectorPromotionPolicyDecision(
        status="policy_set_rejected",
        allowed=False,
        policy_id=policy_ids[0],
        policy_version=policies[0].policy_version,
        policy_set_id=policy_set.policy_set_id,
        policy_set_version=policy_set.policy_set_version,
        policy_ids=policy_ids,
        policy_results=policy_results,
        enforcement_mode="required",
        reason="policy_set_constraints_failed",
        required_scopes=required_scopes,
        matched_constraints=matched_constraints,
    )


def _required_policy_set_decision(
    *,
    requested_policy_id: str,
    policy_set,
    manual_import,
    proposal,
) -> ConnectorPromotionPolicyDecision:
    matched_constraints = {
        "policy_set_status": policy_set.status,
        "manual_import_status": manual_import.status,
        "workflow_signal_status": manual_import.workflow_signal_status,
        "risk_level": manual_import.risk_level,
        "ontology_type": proposal.ontology_type,
        "selection_mode": "active_policy_set",
        "policy_count": str(len(policy_set.policy_ids)),
    }
    return ConnectorPromotionPolicyDecision(
        status="policy_set_rejected",
        allowed=False,
        policy_id=requested_policy_id,
        policy_set_id=policy_set.policy_set_id,
        policy_set_version=policy_set.policy_set_version,
        policy_ids=policy_set.policy_ids,
        policy_results=[
            {
                "policy_id": requested_policy_id,
                "status": "policy_set_rejected",
                "allowed": False,
                "reason": "policy_set_required",
            }
        ],
        enforcement_mode="required",
        reason="policy_set_required",
        required_scopes=[],
        matched_constraints=matched_constraints,
    )


def _raise_policy_rejection_with_audit(
    *,
    repository: AxisPersistenceRepository,
    request: ConnectorOntologyPromotionRequest,
    proposal,
    manual_import,
    permission_decision: PermissionDecision,
    policy_decision: ConnectorPromotionPolicyDecision,
    message: str,
    rejection_reason: str,
) -> None:
    audit_event = repository.append_audit_event(
        AuditEventCreate(
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            event_type=REJECTED_AUDIT_EVENT_TYPE,
            payload={
                "connector_id": proposal.connector_id,
                "promotion_id": request.promotion_id,
                "proposal_id": proposal.proposal_id,
                "manual_import_id": manual_import.import_id,
                "promotion_mode": request.promotion_mode,
                "policy_id": policy_decision.policy_id,
                "policy_set_id": policy_decision.policy_set_id,
                "policy_ids": policy_decision.policy_ids,
                "policy_decision": policy_decision.model_dump(),
                "status": "promotion_rejected",
                "graph_mutation_status": "not_applied",
                "rejection_reason": rejection_reason,
                "required_permission": REQUIRED_PROMOTION_SCOPE,
                "permission_decision": permission_decision.model_dump(),
                "node_id": proposal.node_id,
                "node_type": proposal.node_type,
                "ontology_type": proposal.ontology_type,
                "field_summary_keys": sorted(proposal.field_summary.keys()),
                "decision_note_recorded": str(request.note is not None).lower(),
            },
        )
    )
    raise ConnectorOntologyPromotionValidationError(
        message,
        rejection_reason,
        audit_event_id=audit_event.id,
        audit_event_type=audit_event.event_type,
    )


def _policy_violations(policy, request, proposal, manual_import) -> list[str]:
    violations: list[str] = []
    missing_scopes = sorted(set(policy.required_scopes) - set(request.actor_scopes))
    violations.extend(f"missing_scope:{scope}" for scope in missing_scopes)
    if manual_import.status != policy.required_manual_import_status:
        violations.append("manual_import_status_mismatch")
    if manual_import.workflow_signal_status != policy.required_workflow_signal_status:
        violations.append("workflow_signal_status_mismatch")
    if manual_import.risk_level not in policy.allowed_risk_levels:
        violations.append("risk_level_not_allowed")
    if proposal.ontology_type not in policy.allowed_ontology_types:
        violations.append("ontology_type_not_allowed")
    return violations


def _select_required_promotion_policy(
    repository: AxisPersistenceRepository,
    tenant_id: str,
    connector_id: str,
):
    policies = repository.list_connector_promotion_policies(
        tenant_id=tenant_id,
        connector_id=connector_id,
        status="enabled",
    )
    required_policies = [policy for policy in policies if policy.enforcement_mode == "required"]
    if not required_policies:
        return None
    if len(required_policies) > 1:
        raise ConnectorOntologyPromotionValidationError(
            "Multiple enabled required policies match this connector promotion.",
            "promotion_policy_selection_ambiguous",
        )
    return required_policies[0]


def _policy_identity_for_idempotency_replay(
    record,
    request: ConnectorOntologyPromotionRequest,
) -> dict:
    if request.policy_id is not None:
        return {
            "policy_id": request.policy_id,
            "policy_set_id": None,
            "policy_ids": [request.policy_id],
        }
    if _policy_selection_mode_from_record(record) in {"auto_required", "active_policy_set"}:
        return {
            "policy_id": record.policy_id,
            "policy_set_id": record.policy_set_id,
            "policy_ids": record.policy_ids,
        }
    return {"policy_id": None, "policy_set_id": None, "policy_ids": None}


def _policy_selection_mode_from_record(record) -> str | None:
    if not record.policy_decision:
        return None
    matched_constraints = record.policy_decision.get("matched_constraints", {})
    return matched_constraints.get("selection_mode")


def _promotion_status(ontology_mutation: OntologyMutationResult) -> str:
    if ontology_mutation.status == "type_db_mutation_applied":
        return "promoted_to_graph"
    if ontology_mutation.status == "type_db_mutation_deferred":
        return "promotion_deferred"
    return "promotion_failed"


def _audit_event_type(ontology_mutation: OntologyMutationResult) -> str:
    if ontology_mutation.status == "type_db_mutation_applied":
        return APPLIED_AUDIT_EVENT_TYPE
    if ontology_mutation.status == "type_db_mutation_deferred":
        return DEFERRED_AUDIT_EVENT_TYPE
    return FAILED_AUDIT_EVENT_TYPE


def _proposal_from_record(record) -> ConnectorOntologyProposalRecord:
    return ConnectorOntologyProposalRecord(
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
        promoted_at=record.promoted_at,
        ontology_mutation=record.ontology_mutation,
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        notes=record.notes,
        created_at=record.created_at,
    )


def _promotion_from_record(record) -> ConnectorOntologyPromotionRecord:
    return ConnectorOntologyPromotionRecord(
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
        policy_id=record.policy_id,
        policy_set_id=record.policy_set_id,
        policy_ids=record.policy_ids,
        policy_decision=(
            ConnectorPromotionPolicyDecision.model_validate(record.policy_decision)
            if record.policy_decision
            else None
        ),
        audit_event_id=record.audit_event_id,
        audit_event_type=record.audit_event_type,
        notes=record.notes,
        created_at=record.created_at,
    )


def _result_from_existing(
    existing, proposal, idempotent_replay: bool
) -> ConnectorOntologyPromotionResult:
    ontology_mutation = OntologyMutationResult.model_validate(existing.ontology_mutation)
    return ConnectorOntologyPromotionResult(
        tenant_id=existing.tenant_id,
        connector_id=existing.connector_id,
        promotion_id=existing.promotion_id,
        proposal_id=existing.proposal_id,
        manual_import_id=existing.manual_import_id,
        status=existing.status,
        graph_mutation_status=existing.graph_mutation_status,
        actor_id=existing.requested_by,
        proposal=_proposal_from_record(proposal),
        promotion=_promotion_from_record(existing),
        permission_decision=PermissionDecision.model_validate(existing.permission_decision),
        ontology_mutation=ontology_mutation,
        policy_id=existing.policy_id,
        policy_set_id=existing.policy_set_id,
        policy_ids=existing.policy_ids,
        policy_decision=(
            ConnectorPromotionPolicyDecision.model_validate(existing.policy_decision)
            if existing.policy_decision
            else None
        ),
        audit_event_id=existing.audit_event_id,
        audit_event_type=existing.audit_event_type,
        idempotent_replay=idempotent_replay,
    )


def _fingerprint_from_request(
    request: ConnectorOntologyPromotionRequest,
    *,
    policy_id: str | None = None,
    policy_set_id: str | None = None,
    policy_ids: list[str] | None = None,
) -> dict:
    effective_policy_id = request.policy_id if policy_id is None else policy_id
    effective_policy_ids = (
        [effective_policy_id]
        if policy_ids is None and effective_policy_id is not None
        else policy_ids
    )
    return {
        "promotion_id": request.promotion_id,
        "proposal_id": request.proposal_id,
        "manual_import_id": request.manual_import_id,
        "promotion_mode": request.promotion_mode,
        "policy_id": effective_policy_id,
        "policy_set_id": policy_set_id,
        "policy_ids": effective_policy_ids,
        "requested_by": request.actor_id,
        "notes": [request.note] if request.note else [],
    }


def _fingerprint_from_existing(record) -> dict:
    return {
        "promotion_id": record.promotion_id,
        "proposal_id": record.proposal_id,
        "manual_import_id": record.manual_import_id,
        "promotion_mode": record.promotion_mode,
        "policy_id": record.policy_id,
        "policy_set_id": record.policy_set_id,
        "policy_ids": record.policy_ids,
        "requested_by": record.requested_by,
        "notes": record.notes,
    }
