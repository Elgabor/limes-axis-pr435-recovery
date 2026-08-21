"""Typed response and request models for the Limes Axis REST API.

The shapes mirror the committed OpenAPI artifact (``docs/openapi.json``) of
the same repository revision. Models allow extra fields so that additive
API changes do not break deserialization; removed or retyped fields follow
the SDK compatibility policy documented in ``docs/sdk-python.md``.

This module is standalone: it must not import from ``axis_api``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AxisModel(BaseModel):
    """Base model: tolerant of additive fields returned by newer APIs."""

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Shared enums and primitives
# ---------------------------------------------------------------------------


class OverviewStatus(StrEnum):
    READY = "ready"
    WATCH = "watch"
    ACTION_REQUIRED = "action_required"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


class ApprovalMode(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    CONDITIONAL = "conditional"


class ActionRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


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


class PermissionDecision(AxisModel):
    allowed: bool
    reason: str


class OverviewMetric(AxisModel):
    label: str
    value: str
    detail: str
    status: OverviewStatus


class WorkflowSignalResult(AxisModel):
    workflow_id: str
    status: str
    adapter: str
    signal_name: str
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


class HealthStatus(AxisModel):
    status: str
    service: str


class ReadinessStatus(AxisModel):
    status: str
    service: str
    dependencies: dict[str, Any] = Field(default_factory=dict)
    identity: dict[str, Any] = Field(default_factory=dict)
    external_model_egress_enabled: bool | None = None


class DeploymentReadinessReport(AxisModel):
    """Public-safe deployment readiness report (`/deployment/readiness`).

    Checks and capabilities are large nested structures; the SDK keeps them
    dynamically typed apart from the summary fields.
    """

    status: str
    environment: str
    profile: str
    production_ready: bool
    demo_safe: bool
    capabilities: dict[str, Any] = Field(default_factory=dict)
    production_blockers: list[str] = Field(default_factory=list)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


class ApprovalAuditPreview(AxisModel):
    event: str
    actor_role: str
    scope: str
    result: str


class ApprovalDecisionOption(AxisModel):
    decision: ApprovalDecision
    label: str
    consequence: str


class ApprovalInboxItem(AxisModel):
    approval_id: str
    workflow_id: str
    action: str
    requested_by: str
    owner_role: str
    risk_level: str
    due: str
    status: str
    summary: str
    domain: str
    estimated_cost: str
    model_policy: str
    required_permission: str
    data_accessed: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    decision_options: list[ApprovalDecisionOption] = Field(default_factory=list)
    audit_event_preview: ApprovalAuditPreview | None = None


class ApprovalInbox(AxisModel):
    tenant_id: str
    plant_name: str
    scenario: str
    as_of: str
    queue_status: OverviewStatus
    approvals: list[ApprovalInboxItem] = Field(default_factory=list)
    policy_notes: list[str] = Field(default_factory=list)


class ApprovalDecisionResult(AxisModel):
    tenant_id: str
    approval_id: str
    workflow_id: str
    action_id: str
    actor_id: str
    decision: ApprovalDecision
    status: str
    persisted: bool
    permission_decision: PermissionDecision
    audit_event_id: str
    audit_event_type: str
    workflow_signal: WorkflowSignalResult
    workflow_signal_status: str
    workflow_state_updated: bool
    workflow_state: str | None = None
    workflow_status: str | None = None
    action_run_recorded: bool = False
    action_run_id: str | None = None
    action_run_status: str | None = None
    action_run_idempotency_key: str | None = None
    action_run_idempotent_replay: bool = False
    decision_event_id: str | None = None


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


class ActionDefinition(AxisModel):
    action_id: str
    display_name: str
    domain: str
    risk_level: ActionRiskLevel
    approval_mode: ApprovalMode
    required_permissions: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


class ActionRegistryPolicy(AxisModel):
    execution_mode: str
    runtime_adapter: str
    approval_role: str
    audit_event_type: str
    autonomy_ceiling: str
    model_egress_policy: str
    dry_run_supported: bool
    idempotency_required: bool


class ActionRegistryEntry(AxisModel):
    definition: ActionDefinition
    policy: ActionRegistryPolicy
    status: str
    description: str
    owner_role: str
    side_effects: str
    guardrails: list[str] = Field(default_factory=list)
    blocked_conditions: list[str] = Field(default_factory=list)
    validation_checks: list[str] = Field(default_factory=list)
    connected_agents: list[str] = Field(default_factory=list)
    workflow_bindings: list[str] = Field(default_factory=list)
    approval_refs: list[str] = Field(default_factory=list)
    sample_input: dict[str, Any] = Field(default_factory=dict)
    sample_output: dict[str, Any] = Field(default_factory=dict)


class ActionRegistryFilterOptions(AxisModel):
    domains: list[str] = Field(default_factory=list)
    risk_levels: list[ActionRiskLevel] = Field(default_factory=list)
    approval_modes: list[ApprovalMode] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)


class ActionRegistry(AxisModel):
    tenant_id: str
    plant_name: str
    scenario: str
    schema_version: str
    as_of: str
    registry_status: OverviewStatus
    actions: list[ActionRegistryEntry] = Field(default_factory=list)
    metrics: list[OverviewMetric] = Field(default_factory=list)
    filter_options: ActionRegistryFilterOptions | None = None
    registry_notes: list[str] = Field(default_factory=list)


class ActionRunResult(AxisModel):
    tenant_id: str
    action_id: str
    action_run_id: str
    idempotency_key: str
    idempotent_replay: bool
    execution_mode: str
    status: str
    requested_by: str
    persisted: bool
    approval_required: bool
    permission_decision: PermissionDecision
    workflow_signal_status: str
    workflow_state_updated: bool
    approval_id: str | None = None
    workflow_id: str | None = None
    workflow_state: str | None = None
    workflow_status: str | None = None
    workflow_signal: WorkflowSignalResult | None = None
    audit_event_id: str | None = None
    audit_event_type: str | None = None


class ActionRunOutcomeResult(AxisModel):
    tenant_id: str
    action_id: str
    action_run_id: str
    idempotency_key: str
    idempotent_replay: bool
    execution_mode: str
    status: str
    result_summary: str
    requested_by: str
    persisted: bool
    permission_decision: PermissionDecision
    workflow_state_updated: bool
    evidence_refs: list[str] = Field(default_factory=list)
    approval_id: str | None = None
    workflow_id: str | None = None
    workflow_state: str | None = None
    workflow_status: str | None = None
    audit_event_id: str | None = None
    audit_event_type: str | None = None


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


class WorkflowSignal(AxisModel):
    signal: str
    required_role: str
    status: str
    approval_id: str | None = None


class WorkflowTimelineEvent(AxisModel):
    event: str
    at: str
    actor: str
    result: str
    summary: str


class WorkflowRun(AxisModel):
    workflow_id: str
    name: str
    domain: str
    state: str
    status: OverviewStatus
    owner_role: str
    runtime: str
    adapter: str
    autonomy_level: str
    started_at: str
    eta: str
    objective: str
    current_step: str
    related_risk: str
    audit_scope: str
    replay_ready: bool
    blocker: str | None = None
    related_assets: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    proposed_outputs: list[str] = Field(default_factory=list)
    pending_signals: list[WorkflowSignal] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    timeline: list[WorkflowTimelineEvent] = Field(default_factory=list)


class WorkflowConsole(AxisModel):
    tenant_id: str
    plant_name: str | None = None
    scenario: str | None = None
    as_of: str
    runtime_status: OverviewStatus
    workflow_runs: list[WorkflowRun] = Field(default_factory=list)
    metrics: list[OverviewMetric] = Field(default_factory=list)
    runtime_notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class AuditLedgerEvent(AxisModel):
    audit_event_id: str
    tenant_id: str
    event_type: str
    category: str
    occurred_at: str
    actor_id: str
    actor_type: str
    scope: str
    domain: str
    severity: OverviewStatus
    source: str
    summary: str
    result: str
    permission_scope: str
    data_classification: str
    evidence_refs: list[str] = Field(default_factory=list)
    payload_preview: dict[str, Any] = Field(default_factory=dict)
    related_workflow_id: str | None = None
    related_approval_id: str | None = None
    related_agent_id: str | None = None


class AuditFilterOptions(AxisModel):
    tenants: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)
    actors: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)


class AuditExplorer(AxisModel):
    tenant_id: str
    plant_name: str | None = None
    scenario: str | None = None
    as_of: str
    ledger_status: OverviewStatus
    events: list[AuditLedgerEvent] = Field(default_factory=list)
    metrics: list[OverviewMetric] = Field(default_factory=list)
    filter_options: AuditFilterOptions | None = None
    retention_notes: list[str] = Field(default_factory=list)


class AuditEventQuery(AxisModel):
    tenant_id: str = "tenant_demo_manufacturing"
    event_type: str | None = None
    actor_id: str | None = None
    scope: str | None = None
    limit: int = 100


class AuditRetentionPolicy(AxisModel):
    policy_id: str
    retention_days: int
    retention_basis: str
    disposal_action: str
    legal_hold: bool
    export_requires_review: bool
    notes: list[str] = Field(default_factory=list)


class AuditIntegrityProof(AxisModel):
    algorithm: str
    verification_status: str
    record_count: int
    chain_tip_sha256: str
    event_hashes: list[str] = Field(default_factory=list)


class AuditLedgerSignatureProof(AxisModel):
    algorithm: str
    signing_mode: str
    verification_status: str
    signed_payload_sha256: str
    key_id: str | None = None
    signature: str | None = None
    notes: list[str] = Field(default_factory=list)


class AuditExportManifest(AxisModel):
    export_id: str
    generated_at: str
    tenant_id: str
    record_count: int
    format: str
    redaction_policy: str
    retention_policy_id: str
    checksum_sha256: str
    integrity_chain_tip_sha256: str
    retention_enforced: bool
    retention_window_start: str
    excluded_record_count: int


class AuditExportBundle(AxisModel):
    tenant_id: str
    scenario: str | None = None
    format: str
    export_reason: str
    filters: AuditEventQuery
    retention_policy: AuditRetentionPolicy
    manifest: AuditExportManifest
    integrity_proof: AuditIntegrityProof
    ledger_signature: AuditLedgerSignatureProof
    events: list[AuditLedgerEvent] = Field(default_factory=list)
    retention_notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Ontology
# ---------------------------------------------------------------------------


class OntologyNode(AxisModel):
    node_id: str
    node_type: OntologyNodeType
    label: str
    domain: str
    source_system: str
    status: OverviewStatus
    summary: str


class OntologyRelationshipMetadata(AxisModel):
    owner_role: str
    source_adapter: str
    confidence: float
    valid_from: str
    last_verified_at: str
    verification_status: str
    valid_to: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class OntologyRelationship(AxisModel):
    relationship_id: str
    source_id: str
    target_id: str
    relation_type: str
    permission_scope: str
    summary: str
    metadata: OntologyRelationshipMetadata | None = None


class OntologyGraphQueryMetadata(AxisModel):
    tenant_id: str
    actor_id: str
    adapter: str
    source: str
    query_mode: str
    permission_decision: PermissionDecision
    returned_node_count: int
    returned_relationship_count: int
    denied_relationship_count: int
    requested_scopes: list[str] = Field(default_factory=list)
    applied_relationship_scopes: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    typeql: str | None = None


class OntologyGraph(AxisModel):
    tenant_id: str
    plant_name: str
    scenario: str
    as_of: str
    nodes: list[OntologyNode] = Field(default_factory=list)
    relationships: list[OntologyRelationship] = Field(default_factory=list)
    source_systems: list[str] = Field(default_factory=list)
    permission_notes: list[str] = Field(default_factory=list)
    graph_query: OntologyGraphQueryMetadata | None = None


class OntologyEntityRelationship(AxisModel):
    direction: str
    relationship: OntologyRelationship
    peer_node: OntologyNode


class OntologyEntityDetail(AxisModel):
    tenant_id: str
    plant_name: str
    scenario: str
    as_of: str
    node: OntologyNode
    inbound_count: int
    outbound_count: int
    connected_relationships: list[OntologyEntityRelationship] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    data_access: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    detail_notes: list[str] = Field(default_factory=list)
    related_workflows: list[str] = Field(default_factory=list)
    related_approvals: list[str] = Field(default_factory=list)
    related_agents: list[str] = Field(default_factory=list)
    governed_by: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


class AgentPolicyBoundary(AxisModel):
    autonomy_level: str
    max_action_level: str
    model_policy: str
    external_egress_allowed: bool
    required_permissions: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)


class AgentActionProposal(AxisModel):
    proposal_id: str
    action: str
    risk_level: str
    status: str
    approval_required: bool
    related_workflow_id: str | None = None
    related_approval_id: str | None = None


class AgentRegistryEntry(AxisModel):
    agent_id: str
    name: str
    domain: str
    purpose: str
    owner_role: str
    status: str
    last_audit_event: str
    policy_boundary: AgentPolicyBoundary
    connected_systems: list[str] = Field(default_factory=list)
    data_access: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    blocked_actions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    active_workflows: list[str] = Field(default_factory=list)
    pending_approvals: list[str] = Field(default_factory=list)
    proposals: list[AgentActionProposal] = Field(default_factory=list)


class AgentRegistryFilterOptions(AxisModel):
    domains: list[str] = Field(default_factory=list)
    autonomy_levels: list[str] = Field(default_factory=list)
    model_policies: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)


class AgentRegistry(AxisModel):
    tenant_id: str
    plant_name: str
    scenario: str
    as_of: str
    registry_status: OverviewStatus
    agents: list[AgentRegistryEntry] = Field(default_factory=list)
    metrics: list[OverviewMetric] = Field(default_factory=list)
    filter_options: AgentRegistryFilterOptions | None = None
    registry_notes: list[str] = Field(default_factory=list)
