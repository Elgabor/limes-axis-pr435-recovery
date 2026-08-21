from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from axis_api.actions import ActionDefinition, ActionRiskLevel, ApprovalMode
from axis_api.manufacturing_metadata import ManufacturingResponseProvenance
from axis_api.ontology.queries import OntologyGraphQueryMetadata
from axis_api.permissions import PermissionDecision


class OverviewStatus(StrEnum):
    READY = "ready"
    WATCH = "watch"
    ACTION_REQUIRED = "action_required"


def _default_ontology_graph_query_metadata() -> OntologyGraphQueryMetadata:
    return OntologyGraphQueryMetadata(
        adapter="axis-deferred-ontology-query-adapter",
        source="demo-seed",
        query_mode="unfiltered_public_seed",
        tenant_id="tenant_demo_manufacturing",
        actor_id="public-demo-reader",
        permission_decision=PermissionDecision(allowed=True, reason="public_seed"),
        requested_scopes=[],
        applied_relationship_scopes=[],
        denied_relationship_count=0,
        returned_node_count=0,
        returned_relationship_count=0,
        typeql=None,
        notes=[
            "Public ontology seed is served through the Axis graph query contract.",
            "Authenticated reads can be filtered by relationship-derived scopes.",
        ],
    )


class OverviewMetric(BaseModel):
    label: str = Field(min_length=1)
    value: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    status: OverviewStatus


class RiskSignal(BaseModel):
    title: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    severity: OverviewStatus
    owner_role: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    related_asset: str = Field(min_length=1)


class WorkflowSummary(BaseModel):
    workflow_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    state: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    blocker: str | None = None
    eta: str = Field(min_length=1)


class WorkflowSignal(BaseModel):
    signal: str = Field(min_length=1)
    required_role: str = Field(min_length=1)
    status: str = Field(min_length=1)
    approval_id: str | None = None


class WorkflowTimelineEvent(BaseModel):
    event: str = Field(min_length=1)
    at: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    result: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class WorkflowRun(BaseModel):
    workflow_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    state: str = Field(min_length=1)
    status: OverviewStatus
    owner_role: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    adapter: str = Field(min_length=1)
    autonomy_level: str = Field(pattern=r"^L[0-4]$")
    started_at: str = Field(min_length=1)
    eta: str = Field(min_length=1)
    blocker: str | None = None
    objective: str = Field(min_length=1)
    current_step: str = Field(min_length=1)
    related_risk: str = Field(min_length=1)
    related_assets: list[str] = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    proposed_outputs: list[str] = Field(min_length=1)
    pending_signals: list[WorkflowSignal] = Field(min_length=1)
    controls: list[str] = Field(min_length=1)
    timeline: list[WorkflowTimelineEvent] = Field(default_factory=list)
    audit_scope: str = Field(min_length=1)
    replay_ready: bool


class ManufacturingWorkflowConsole(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance = (
        ManufacturingResponseProvenance.REFERENCE_SCENARIO
    )
    as_of: str = Field(min_length=1)
    runtime_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    workflow_runs: list[WorkflowRun] = Field(default_factory=list)
    runtime_notes: list[str] = Field(default_factory=list)


class ApprovalSummary(BaseModel):
    approval_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    risk_level: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    due: str = Field(min_length=1)


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


class ApprovalDecisionOption(BaseModel):
    decision: ApprovalDecision
    label: str = Field(min_length=1)
    consequence: str = Field(min_length=1)


class ApprovalAuditPreview(BaseModel):
    event: str = Field(min_length=1)
    actor_role: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    result: str = Field(min_length=1)


class ApprovalInboxItem(BaseModel):
    approval_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    risk_level: str = Field(min_length=1)
    status: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    due: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    data_accessed: list[str] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    alternatives: list[str] = Field(min_length=1)
    estimated_cost: str = Field(min_length=1)
    model_policy: str = Field(min_length=1)
    required_permission: str = Field(min_length=1)
    audit_event_preview: ApprovalAuditPreview
    decision_options: list[ApprovalDecisionOption] = Field(min_length=1)


class ActionRegistryPolicy(BaseModel):
    approval_role: str = Field(min_length=1)
    autonomy_ceiling: str = Field(pattern=r"^L[0-4]$")
    execution_mode: str = Field(min_length=1)
    runtime_adapter: str = Field(min_length=1)
    audit_event_type: str = Field(min_length=1)
    model_egress_policy: str = Field(min_length=1)
    idempotency_required: bool
    dry_run_supported: bool


class ActionRegistryEntry(BaseModel):
    definition: ActionDefinition
    description: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    status: str = Field(min_length=1)
    side_effects: str = Field(min_length=1)
    policy: ActionRegistryPolicy
    connected_agents: list[str] = Field(min_length=1)
    workflow_bindings: list[str] = Field(default_factory=list)
    approval_refs: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(min_length=1)
    validation_checks: list[str] = Field(min_length=1)
    blocked_conditions: list[str] = Field(min_length=1)
    sample_input: dict[str, str] = Field(min_length=1)
    sample_output: dict[str, str] = Field(min_length=1)


class ActionRegistryFilterOptions(BaseModel):
    domains: list[str] = Field(default_factory=list)
    risk_levels: list[ActionRiskLevel] = Field(default_factory=list)
    approval_modes: list[ApprovalMode] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)


class ManufacturingActionRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance = (
        ManufacturingResponseProvenance.REFERENCE_SCENARIO
    )
    as_of: str = Field(min_length=1)
    registry_status: OverviewStatus
    schema_version: str = Field(min_length=1)
    metrics: list[OverviewMetric] = Field(default_factory=list)
    filter_options: ActionRegistryFilterOptions
    actions: list[ActionRegistryEntry] = Field(default_factory=list)
    registry_notes: list[str] = Field(default_factory=list)


class ManufacturingApprovalInbox(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance = (
        ManufacturingResponseProvenance.REFERENCE_SCENARIO
    )
    as_of: str = Field(min_length=1)
    queue_status: OverviewStatus
    policy_notes: list[str] = Field(default_factory=list)
    approvals: list[ApprovalInboxItem] = Field(default_factory=list)


class AgentSummary(BaseModel):
    agent_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    autonomy_level: str = Field(pattern=r"^L[0-4]$")
    status: str = Field(min_length=1)
    proposals_pending: int = Field(ge=0)
    model_policy: str = Field(min_length=1)


class AgentActionProposal(BaseModel):
    proposal_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    risk_level: str = Field(min_length=1)
    status: str = Field(min_length=1)
    approval_required: bool
    related_workflow_id: str | None = None
    related_approval_id: str | None = None


class AgentPolicyBoundary(BaseModel):
    autonomy_level: str = Field(pattern=r"^L[0-4]$")
    model_policy: str = Field(min_length=1)
    external_egress_allowed: bool
    max_action_level: str = Field(pattern=r"^L[0-4]$")
    required_permissions: list[str] = Field(min_length=1)
    guardrails: list[str] = Field(min_length=1)


class AgentRegistryEntry(BaseModel):
    agent_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    status: str = Field(min_length=1)
    owner_role: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    policy_boundary: AgentPolicyBoundary
    connected_systems: list[str] = Field(min_length=1)
    data_access: list[str] = Field(min_length=1)
    allowed_actions: list[str] = Field(min_length=1)
    blocked_actions: list[str] = Field(min_length=1)
    proposals: list[AgentActionProposal] = Field(default_factory=list)
    active_workflows: list[str] = Field(default_factory=list)
    pending_approvals: list[str] = Field(default_factory=list)
    last_audit_event: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)


class AgentRegistryFilterOptions(BaseModel):
    domains: list[str] = Field(default_factory=list)
    autonomy_levels: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    model_policies: list[str] = Field(default_factory=list)


class ManufacturingAgentRegistry(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance = (
        ManufacturingResponseProvenance.REFERENCE_SCENARIO
    )
    as_of: str = Field(min_length=1)
    registry_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    filter_options: AgentRegistryFilterOptions
    agents: list[AgentRegistryEntry] = Field(default_factory=list)
    registry_notes: list[str] = Field(default_factory=list)


class AuditEvidence(BaseModel):
    event: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    result: str = Field(min_length=1)


class AuditLedgerEvent(BaseModel):
    audit_event_id: str = Field(min_length=1)
    occurred_at: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    actor_type: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    category: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    result: str = Field(min_length=1)
    severity: OverviewStatus
    source: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    permission_scope: str = Field(min_length=1)
    data_classification: str = Field(min_length=1)
    related_workflow_id: str | None = None
    related_approval_id: str | None = None
    related_agent_id: str | None = None
    evidence_refs: list[str] = Field(min_length=1)
    payload_preview: dict[str, str] = Field(min_length=1)


class AuditFilterOptions(BaseModel):
    tenants: list[str] = Field(min_length=1)
    event_types: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    actors: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)


class ManufacturingAuditExplorer(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance = (
        ManufacturingResponseProvenance.REFERENCE_SCENARIO
    )
    as_of: str = Field(min_length=1)
    ledger_status: OverviewStatus
    metrics: list[OverviewMetric] = Field(default_factory=list)
    filter_options: AuditFilterOptions
    events: list[AuditLedgerEvent] = Field(default_factory=list)
    retention_notes: list[str] = Field(default_factory=list)


class ManufacturingOverview(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance = (
        ManufacturingResponseProvenance.REFERENCE_SCENARIO
    )
    as_of: str = Field(min_length=1)
    metrics: list[OverviewMetric] = Field(default_factory=list)
    risk_signals: list[RiskSignal] = Field(default_factory=list)
    workflows: list[WorkflowSummary] = Field(default_factory=list)
    approvals: list[ApprovalSummary] = Field(default_factory=list)
    agents: list[AgentSummary] = Field(default_factory=list)
    audit_events: list[AuditEvidence] = Field(default_factory=list)


class OntologyNodeType(StrEnum):
    ORGANIZATION = "organization"
    ASSET = "asset"
    PROCESS = "process"
    WORKFLOW = "workflow"
    RISK = "risk"
    APPROVAL = "approval"
    AGENT = "agent"
    SYSTEM = "system"
    POLICY = "policy"
    AUDIT_EVENT = "audit_event"


class OntologyNode(BaseModel):
    node_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    node_type: OntologyNodeType
    domain: str = Field(min_length=1)
    status: OverviewStatus
    source_system: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class OntologyRelationshipMetadata(BaseModel):
    owner_role: str = Field(min_length=1)
    source_adapter: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence_refs: list[str] = Field(min_length=1)
    valid_from: str = Field(min_length=1)
    valid_to: str | None = None
    last_verified_at: str = Field(min_length=1)
    verification_status: str = Field(min_length=1)


class OntologyRelationship(BaseModel):
    relationship_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relation_type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    permission_scope: str = Field(min_length=1)
    metadata: OntologyRelationshipMetadata | None = None

    @model_validator(mode="after")
    def ensure_metadata(self) -> "OntologyRelationship":
        if self.metadata is None:
            self.metadata = default_ontology_relationship_metadata(
                self.relationship_id,
                self.permission_scope,
            )
        return self


def default_ontology_relationship_metadata(
    relationship_id: str,
    permission_scope: str,
) -> OntologyRelationshipMetadata:
    owner_by_scope = {
        "agents": "Agent Operations Steward",
        "approvals": "Approval Steward",
        "audit": "Audit Steward",
        "maintenance": "Maintenance Steward",
        "operations": "Operations Steward",
        "quality": "Quality Steward",
        "security": "Security Steward",
        "supply": "Supply Steward",
    }
    scope_prefix = permission_scope.split(":", maxsplit=1)[0]
    return OntologyRelationshipMetadata(
        owner_role=owner_by_scope.get(scope_prefix, "Ontology Steward"),
        source_adapter="axis-reference-ontology",
        confidence=0.9,
        evidence_refs=[f"ontology:{relationship_id}"],
        valid_from="2026-06-21T16:30:00+02:00",
        valid_to=None,
        last_verified_at="2026-06-21T16:30:00+02:00",
        verification_status="reference_verified",
    )


def ontology_relationship_metadata_payload(
    relationship_id: str,
    permission_scope: str,
    *,
    evidence_refs: list[str] | None = None,
    confidence: float = 0.9,
    source_adapter: str = "axis-reference-ontology",
    valid_from: str = "2026-06-21T16:30:00+02:00",
    valid_to: str | None = None,
    last_verified_at: str = "2026-06-21T16:30:00+02:00",
    verification_status: str = "reference_verified",
) -> dict:
    metadata = default_ontology_relationship_metadata(
        relationship_id,
        permission_scope,
    )
    metadata = metadata.model_copy(
        update={
            "source_adapter": source_adapter,
            "confidence": confidence,
            "evidence_refs": evidence_refs or metadata.evidence_refs,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "last_verified_at": last_verified_at,
            "verification_status": verification_status,
        }
    )
    return metadata.model_dump()


class ManufacturingOntology(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance = (
        ManufacturingResponseProvenance.REFERENCE_SCENARIO
    )
    as_of: str = Field(min_length=1)
    nodes: list[OntologyNode] = Field(default_factory=list)
    relationships: list[OntologyRelationship] = Field(default_factory=list)
    source_systems: list[str] = Field(default_factory=list)
    permission_notes: list[str] = Field(default_factory=list)
    graph_query: OntologyGraphQueryMetadata = Field(
        default_factory=_default_ontology_graph_query_metadata
    )



class OntologyEntityRelationship(BaseModel):
    direction: str = Field(pattern=r"^(inbound|outbound)$")
    relationship: OntologyRelationship
    peer_node: OntologyNode


class ManufacturingOntologyEntityDetail(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance = (
        ManufacturingResponseProvenance.REFERENCE_SCENARIO
    )
    as_of: str = Field(min_length=1)
    node: OntologyNode
    connected_relationships: list[OntologyEntityRelationship] = Field(default_factory=list)
    inbound_count: int = Field(ge=0)
    outbound_count: int = Field(ge=0)
    required_permissions: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    data_access: list[str] = Field(min_length=1)
    governed_by: list[str] = Field(default_factory=list)
    related_workflows: list[str] = Field(default_factory=list)
    related_approvals: list[str] = Field(default_factory=list)
    related_agents: list[str] = Field(default_factory=list)
    detail_notes: list[str] = Field(min_length=1)


class ModelProviderOption(BaseModel):
    provider_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    provider_type: str = Field(min_length=1)
    hosting_boundary: str = Field(min_length=1)
    status: str = Field(min_length=1)
    egress_mode: str = Field(min_length=1)
    cost_basis: str = Field(min_length=1)
    allowed_policies: list[str] = Field(min_length=1)
    notes: list[str] = Field(min_length=1)


class ModelRouteTelemetry(BaseModel):
    route_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    model_policy: str = Field(min_length=1)
    prompt_classification: str = Field(min_length=1)
    data_boundary: str = Field(min_length=1)
    external_egress_requested: bool
    external_egress_allowed: bool
    egress_decision: str = Field(min_length=1)
    decision_reason: str = Field(min_length=1)
    route_status: OverviewStatus
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_eur: float = Field(ge=0)
    latency_ms: int = Field(ge=0)
    cost_center: str = Field(min_length=1)
    required_permissions: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    audit_event_id: str = Field(min_length=1)
    observability_events: list[str] = Field(min_length=1)


class ModelRoutingFilterOptions(BaseModel):
    domains: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    model_policies: list[str] = Field(default_factory=list)
    egress_decisions: list[str] = Field(default_factory=list)
    statuses: list[OverviewStatus] = Field(default_factory=list)


class ManufacturingModelRouting(BaseModel):
    tenant_id: str = Field(min_length=1)
    plant_name: str | None = Field(default=None, min_length=1)
    scenario: str | None = Field(default=None, min_length=1)
    provenance: ManufacturingResponseProvenance = (
        ManufacturingResponseProvenance.REFERENCE_SCENARIO
    )
    as_of: str = Field(min_length=1)
    routing_status: OverviewStatus
    # No min_length: a tenant that has not routed a model yet has empty lists,
    # and an empty collection is a valid answer rather than a 404.
    metrics: list[OverviewMetric] = Field(default_factory=list)
    filter_options: ModelRoutingFilterOptions
    provider_options: list[ModelProviderOption] = Field(default_factory=list)
    routes: list[ModelRouteTelemetry] = Field(default_factory=list)
    budget_notes: list[str] = Field(default_factory=list)
    observability_notes: list[str] = Field(default_factory=list)



def _ontology_detail_overrides() -> dict[str, dict[str, list[str]]]:
    return {
        "asset_line_2_packaging": {
            "evidence_refs": [
                "risk_supplier_delay",
                "wf_supplier_delay_review",
                "audit_20260621_154000_ontology_read",
            ],
            "data_access": [
                "MES line status summary",
                "supplier delay risk relationship",
                "approval gate summary",
            ],
            "detail_notes": [
                "This detail page is read-only and derived from the public ontology seed.",
                "Operations can inspect the line context, but cannot execute workflow "
                "signals here.",
                "The supplier delay risk is visible because the relationship scope allows it.",
            ],
        },
        "risk_supplier_delay": {
            "evidence_refs": [
                "asset_motors_batch",
                "asset_line_2_packaging",
                "wf_supplier_delay_review",
            ],
            "data_access": [
                "supplier risk summary",
                "impacted production line",
                "workflow blocker summary",
            ],
            "detail_notes": [
                (
                    "Risk detail is derived from TypeDB-shaped relationships in the "
                    "persisted reference graph."
                ),
                "The risk can drive action proposals, but does not execute actions directly.",
            ],
        },
        "wf_supplier_delay_review": {
            "evidence_refs": [
                "risk_supplier_delay",
                "appr_expedite_supplier_batch",
                "audit_20260621_141800_signal_awaiting",
            ],
            "data_access": [
                "workflow state summary",
                "pending signal metadata",
                "approval requirement relationship",
            ],
            "detail_notes": [
                "Workflow detail is inspectable without exposing runtime mutation controls.",
                "Approval decisions signal this workflow through the Axis runtime adapter.",
            ],
        },
        "appr_expedite_supplier_batch": {
            "evidence_refs": [
                "wf_supplier_delay_review",
                "agent_supply_risk",
                "audit_20260621_141200_agent_proposal",
            ],
            "data_access": [
                "approval summary",
                "requesting agent relationship",
                "workflow requirement relationship",
            ],
            "detail_notes": [
                "Approval detail links the proposed action to the owner review gate.",
                "Decisions are preview-only until persisted approval state is implemented.",
            ],
        },
        "agent_supply_risk": {
            "evidence_refs": [
                "appr_expedite_supplier_batch",
                "risk_supplier_delay",
                "audit_20260621_141200_agent_proposal",
            ],
            "data_access": [
                "agent relationship summary",
                "proposal approval reference",
                "supply risk evidence",
            ],
            "detail_notes": [
                "Agent detail is scoped to declared tenant and domain relationships.",
                "Agent runtime state remains outside this read-only ontology detail slice.",
            ],
        },
        "policy_external_egress": {
            "evidence_refs": [
                "agent_quality_risk",
                "audit_policy_egress_blocked",
                "audit_20260621_133900_egress_blocked",
            ],
            "data_access": [
                "policy summary",
                "governed agent relationship",
                "audit evidence relationship",
            ],
            "detail_notes": [
                "Policy detail shows governance relationships, not policy editing controls.",
                "External model egress remains blocked unless tenant policy explicitly allows it.",
            ],
        },
    }


def _default_ontology_detail_lists(node: OntologyNode) -> dict[str, list[str]]:
    return {
        "evidence_refs": [node.node_id],
        "data_access": [
            f"{node.source_system} public-demo summary",
            f"{node.domain} relationship context",
            f"{node.node_type.value} metadata",
        ],
        "detail_notes": [
            "This entity detail is read-only and synthetic.",
            "Production entity details will require tenant-scoped graph query permissions.",
        ],
    }


def build_manufacturing_ontology_entity_detail(
    ontology: ManufacturingOntology,
    node_id: str,
) -> ManufacturingOntologyEntityDetail | None:
    node_by_id = {node.node_id: node for node in ontology.nodes}
    node = node_by_id.get(node_id)

    if node is None:
        return None

    connected_relationships: list[OntologyEntityRelationship] = []
    inbound_count = 0
    outbound_count = 0

    for relationship in ontology.relationships:
        if relationship.source_id == node_id:
            peer_node = node_by_id[relationship.target_id]
            connected_relationships.append(
                OntologyEntityRelationship(
                    direction="outbound",
                    relationship=relationship,
                    peer_node=peer_node,
                )
            )
            outbound_count += 1
        elif relationship.target_id == node_id:
            peer_node = node_by_id[relationship.source_id]
            connected_relationships.append(
                OntologyEntityRelationship(
                    direction="inbound",
                    relationship=relationship,
                    peer_node=peer_node,
                )
            )
            inbound_count += 1

    permissions = sorted(
        {item.relationship.permission_scope for item in connected_relationships}
        or {f"{node.domain.lower()}:read"}
    )
    detail_lists = _default_ontology_detail_lists(node) | _ontology_detail_overrides().get(
        node_id,
        {},
    )

    return ManufacturingOntologyEntityDetail(
        tenant_id=ontology.tenant_id,
        plant_name=ontology.plant_name,
        scenario=ontology.scenario,
        provenance=ontology.provenance,
        as_of=ontology.as_of,
        node=node,
        connected_relationships=connected_relationships,
        inbound_count=inbound_count,
        outbound_count=outbound_count,
        required_permissions=permissions,
        evidence_refs=detail_lists["evidence_refs"],
        data_access=detail_lists["data_access"],
        governed_by=sorted(
            {
                item.peer_node.node_id
                for item in connected_relationships
                if item.relationship.relation_type == "governs"
            }
        ),
        related_workflows=sorted(
            {
                item.peer_node.node_id
                for item in connected_relationships
                if item.peer_node.node_type == OntologyNodeType.WORKFLOW
            }
            | ({node.node_id} if node.node_type == OntologyNodeType.WORKFLOW else set())
        ),
        related_approvals=sorted(
            {
                item.peer_node.node_id
                for item in connected_relationships
                if item.peer_node.node_type == OntologyNodeType.APPROVAL
            }
            | ({node.node_id} if node.node_type == OntologyNodeType.APPROVAL else set())
        ),
        related_agents=sorted(
            {
                item.peer_node.node_id
                for item in connected_relationships
                if item.peer_node.node_type == OntologyNodeType.AGENT
            }
            | ({node.node_id} if node.node_type == OntologyNodeType.AGENT else set())
        ),
        detail_notes=detail_lists["detail_notes"],
    )
