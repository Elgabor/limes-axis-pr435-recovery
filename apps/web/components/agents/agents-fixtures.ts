import type { AgentRegistryEntry, ManufacturingAgentRegistry } from "@/lib/agent-demo";

export const supplyAgentFixture: AgentRegistryEntry = {
  agent_id: "agent_supply_fixture",
  name: "Supply Risk Agent",
  domain: "Supply",
  status: "waiting_for_approval",
  owner_role: "plant-operations-owner",
  purpose: "Watches supplier risk and proposes governed mitigations.",
  policy_boundary: {
    autonomy_level: "L2",
    model_policy: "no-external-egress",
    external_egress_allowed: false,
    max_action_level: "L2",
    required_permissions: ["approvals:supply:decide", "agents:read"],
    guardrails: ["Proposals only; execution requires owner approval."],
  },
  connected_systems: ["Axis Audit", "Temporal"],
  data_access: ["Supplier status", "Open purchase orders"],
  allowed_actions: ["Draft supplier expedite proposal"],
  blocked_actions: ["Mutate supplier master data"],
  proposals: [
    {
      proposal_id: "prop_supply_fixture",
      action: "Request supplier expedite",
      risk_level: "high",
      status: "pending",
      approval_required: true,
      related_workflow_id: "wf_supply_fixture",
      related_approval_id: "appr_supply_fixture",
    },
  ],
  active_workflows: ["wf_supply_fixture"],
  pending_approvals: ["appr_supply_fixture"],
  last_audit_event: "audit_supply_fixture_event",
  evidence_refs: ["audit_supply_fixture_event", "wf_supply_fixture"],
};

export const qualityAgentFixture: AgentRegistryEntry = {
  agent_id: "agent_quality_fixture",
  name: "Quality Hold Agent",
  domain: "Quality",
  status: "recommending",
  owner_role: "quality-owner",
  purpose: "Summarizes quality deviations for review.",
  policy_boundary: {
    autonomy_level: "L1",
    model_policy: "local-or-approved-provider",
    external_egress_allowed: false,
    max_action_level: "L1",
    required_permissions: ["audit:read"],
    guardrails: ["Summaries only; no action payload execution."],
  },
  connected_systems: ["Axis Audit"],
  data_access: ["QMS deviations"],
  allowed_actions: ["Summarize quality deviations"],
  blocked_actions: ["Release held batches"],
  proposals: [],
  active_workflows: [],
  pending_approvals: [],
  last_audit_event: "audit_quality_fixture_event",
  evidence_refs: ["audit_quality_fixture_event"],
};

export const agentRegistryFixture: ManufacturingAgentRegistry = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Runtime contract fixture",
  provenance: "reference_scenario",
  as_of: "2026-07-10T09:00:00+02:00",
  registry_status: "ready",
  metrics: [
    { label: "Registered agents", value: "2", detail: "Governed by policy", status: "ready" },
    { label: "Pending proposals", value: "1", detail: "Awaiting review", status: "watch" },
  ],
  filter_options: {
    domains: ["Quality", "Supply"],
    autonomy_levels: ["L1", "L2"],
    statuses: ["recommending", "waiting_for_approval"],
    model_policies: ["local-or-approved-provider", "no-external-egress"],
  },
  agents: [supplyAgentFixture, qualityAgentFixture],
  registry_notes: ["Fixture registry data is scoped to tests."],
};

export const agentRunListFixture = {
  tenant_id: "tenant_fixture",
  agent_id: "agent_supply_fixture",
  runs: [
    {
      run_id: "run_fixture_001",
      agent_id: "agent_supply_fixture",
      status: "proposal_recorded",
      mode: "dry_run",
      autonomy_level: "L2",
      requested_by: "scheduler",
      created_at: "2026-07-10T08:30:00Z",
      model_invocation_ids: [],
      proposed_action_run_id: null,
      audit_event_id: "audit_run_fixture",
      error_reason: null,
      idempotent_replay: false,
      notes: [],
      steps: [],
    },
  ],
  has_more: false,
  next_cursor: null,
  run_notes: [],
};

export const agentRunDetailFixture = {
  ...agentRunListFixture.runs[0],
  steps: [
    {
      seq: 1,
      step_type: "context_read",
      status: "completed",
      created_at: "2026-07-10T08:30:01Z",
      evidence: {},
    },
    {
      seq: 2,
      step_type: "model_invocation",
      status: "completed",
      created_at: "2026-07-10T08:30:02Z",
      evidence: {},
    },
    {
      seq: 3,
      step_type: "proposal",
      status: "completed",
      created_at: "2026-07-10T08:30:03Z",
      evidence: {},
    },
  ],
};
