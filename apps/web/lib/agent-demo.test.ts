import { describe, expect, it } from "vitest";

import {
  allAgentFilter,
  countPendingAgentProposals,
  describeAgentPermission,
  filterAgents,
  findAgentById,
  formatAgentLabel,
  summarizeAgentBoundary,
  type ManufacturingAgentRegistry,
} from "./agent-demo";

const agentRegistryFixture: ManufacturingAgentRegistry = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Runtime contract fixture",
  provenance: "reference_scenario",
  as_of: "2026-06-22T09:00:00+02:00",
  registry_status: "watch",
  metrics: [],
  filter_options: {
    domains: ["Supply", "Operations"],
    autonomy_levels: ["L1", "L2"],
    statuses: ["waiting_for_approval", "ready"],
    model_policies: ["local-only"],
  },
  agents: [
    {
      agent_id: "agent_supply_fixture",
      name: "Supply Fixture Agent",
      domain: "Supply",
      status: "waiting_for_approval",
      owner_role: "supply-owner",
      purpose: "Review delayed supplier batches.",
      policy_boundary: {
        autonomy_level: "L2",
        model_policy: "local-only",
        external_egress_allowed: false,
        max_action_level: "L2",
        required_permissions: ["supply:read", "approvals:supply:request"],
        guardrails: ["Require human approval for mutations"],
      },
      connected_systems: ["ERP"],
      data_access: ["Supplier status"],
      allowed_actions: ["expedite_fixture_batch"],
      blocked_actions: ["live_supplier_mutation"],
      proposals: [
        {
          proposal_id: "proposal_supply_fixture",
          action: "Expedite fixture batch",
          risk_level: "high",
          status: "pending_owner_review",
          approval_required: true,
          related_workflow_id: "wf_supply_fixture",
          related_approval_id: "appr_supply_fixture",
        },
      ],
      active_workflows: ["wf_supply_fixture"],
      pending_approvals: ["appr_supply_fixture"],
      last_audit_event: "audit_supply_fixture",
      evidence_refs: ["risk_supply_fixture"],
    },
    {
      agent_id: "agent_brief_fixture",
      name: "Brief Fixture Agent",
      domain: "Operations",
      status: "ready",
      owner_role: "operations-owner",
      purpose: "Prepare read-only shift summaries.",
      policy_boundary: {
        autonomy_level: "L1",
        model_policy: "local-only",
        external_egress_allowed: false,
        max_action_level: "L1",
        required_permissions: ["operations:read"],
        guardrails: ["Read-only outputs"],
      },
      connected_systems: ["MES"],
      data_access: ["Shift status"],
      allowed_actions: ["brief_fixture"],
      blocked_actions: ["workflow_mutation"],
      proposals: [],
      active_workflows: [],
      pending_approvals: [],
      last_audit_event: "audit_brief_fixture",
      evidence_refs: ["asset_fixture_line"],
    },
  ],
  registry_notes: ["Fixture data is scoped to tests."],
};

describe("agent registry helpers", () => {
  it("filters agents by domain, autonomy level and status", () => {
    const agents = filterAgents(agentRegistryFixture, {
      domain: "Supply",
      autonomyLevel: "L2",
      status: "waiting_for_approval",
    });

    expect(agents).toHaveLength(1);
    expect(agents[0].agent_id).toBe("agent_supply_fixture");
  });

  it("keeps all agents when filters are set to all", () => {
    expect(
      filterAgents(agentRegistryFixture, {
        domain: allAgentFilter,
        autonomyLevel: allAgentFilter,
        status: allAgentFilter,
      }),
    ).toHaveLength(agentRegistryFixture.agents.length);
  });

  it("finds agents by id with a safe fallback", () => {
    expect(findAgentById(agentRegistryFixture, "agent_supply_fixture").name).toBe(
      "Supply Fixture Agent",
    );
    expect(findAgentById(agentRegistryFixture, "missing").name).toBe("Supply Fixture Agent");
  });

  it("counts proposals and formats labels", () => {
    expect(countPendingAgentProposals(agentRegistryFixture)).toBe(1);
    expect(formatAgentLabel("waiting_for_approval")).toBe("Waiting For Approval");
    expect(formatAgentLabel("approvals:supply:request")).toBe("Approvals Supply Request");
  });

  it("describes IAM scopes as plain sentences", () => {
    expect(describeAgentPermission("agents:read")).toBe("May read agents");
    expect(describeAgentPermission("approvals:supply:decide")).toBe(
      "May decide supply approvals",
    );
    expect(describeAgentPermission("audit")).toBe("May use audit");
  });

  it("summarizes the policy boundary in plain language", () => {
    const boundary = agentRegistryFixture.agents[0].policy_boundary;
    const summary = summarizeAgentBoundary(boundary);

    expect(summary).toContain("L2");
    expect(summary).toMatch(/data never leaves the platform/i);
    expect(summary).toMatch(/Local Only/);
    expect(summary).not.toContain("model_policy");

    const egressSummary = summarizeAgentBoundary({
      ...boundary,
      external_egress_allowed: true,
      max_action_level: "L3",
    });
    expect(egressSummary).toMatch(/may send data to approved external systems/i);
    expect(egressSummary).toContain("L3");
  });
});
