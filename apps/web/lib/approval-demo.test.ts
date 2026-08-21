import { describe, expect, it } from "vitest";

import {
  approvalDecisionActorId,
  approvalDecisionActorScopes,
  approvalDecisionLabel,
  approvalRiskClass,
  buildApprovalDecisionPayload,
  buildApprovalHref,
  findApprovalById,
  type ManufacturingApprovalInbox,
} from "./approval-demo";

const approvalInboxFixture: ManufacturingApprovalInbox = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Runtime contract fixture",
  provenance: "reference_scenario",
  as_of: "2026-06-22T09:00:00+02:00",
  queue_status: "action_required",
  policy_notes: ["Fixture data is scoped to tests."],
  approvals: [
    {
      approval_id: "appr_supply_fixture",
      action: "Expedite fixture batch",
      risk_level: "high",
      status: "pending",
      requested_by: "agent_supply_fixture",
      owner_role: "plant-operations-owner",
      due: "Today 17:30",
      workflow_id: "wf_supply_fixture",
      domain: "Supply",
      summary: "Approve or reject a governed supply action.",
      evidence: ["risk_supply_fixture"],
      data_accessed: ["Supplier status"],
      risks: ["External shipment mutation"],
      alternatives: ["Adjust production schedule"],
      estimated_cost: "EUR 120",
      model_policy: "no-external-egress",
      required_permission: "approvals:supply:decide",
      audit_event_preview: {
        event: "approval.decision.recorded",
        actor_role: "plant-operations-owner",
        scope: "wf_supply_fixture",
        result: "pending",
      },
      decision_options: [
        { decision: "approve", label: "Approve", consequence: "Proceed to action runtime." },
        { decision: "reject", label: "Reject", consequence: "Keep current plan." },
        {
          decision: "request_changes",
          label: "Request changes",
          consequence: "Return to agent proposal.",
        },
      ],
    },
    {
      approval_id: "appr_quality_fixture",
      action: "Place fixture quality hold",
      risk_level: "medium",
      status: "pending",
      requested_by: "agent_quality_fixture",
      owner_role: "quality-owner",
      due: "Today 18:00",
      workflow_id: "wf_quality_fixture",
      domain: "Quality",
      summary: "Review quality hold evidence.",
      evidence: ["risk_quality_fixture"],
      data_accessed: ["QMS deviation summary"],
      risks: ["Production delay"],
      alternatives: ["Escalate to quality review"],
      estimated_cost: "EUR 0",
      model_policy: "local-only",
      required_permission: "approvals:quality:decide",
      audit_event_preview: {
        event: "approval.decision.recorded",
        actor_role: "quality-owner",
        scope: "wf_quality_fixture",
        result: "pending",
      },
      decision_options: [
        { decision: "approve", label: "Approve", consequence: "Apply hold." },
        { decision: "reject", label: "Reject", consequence: "Release batch." },
        {
          decision: "request_changes",
          label: "Request changes",
          consequence: "Ask for more evidence.",
        },
      ],
    },
  ],
};

describe("approval inbox helpers", () => {
  it("formats approval risk and local decision states", () => {
    expect(approvalRiskClass("high")).toBe("signal-action-required");
    expect(approvalRiskClass("medium")).toBe("signal-watch");
    expect(approvalRiskClass("low")).toBe("signal-ready");
    expect(approvalDecisionLabel("request_changes")).toBe("Changes Requested");
  });

  it("finds approvals by id with a safe fallback", () => {
    expect(findApprovalById(approvalInboxFixture, "appr_quality_fixture").action).toBe(
      "Place fixture quality hold",
    );
    expect(findApprovalById(approvalInboxFixture, "missing").action).toBe(
      "Expedite fixture batch",
    );
  });

  it("builds shareable approval deep links", () => {
    expect(buildApprovalHref("approval / 42")).toBe("/approvals?approval_id=approval+%2F+42");
    expect(buildApprovalHref(null)).toBe("/approvals");
  });

  it("builds public-safe persisted decision payloads from provided approval data", () => {
    const approval = findApprovalById(approvalInboxFixture, "appr_supply_fixture");
    const payload = buildApprovalDecisionPayload(approval, "approve");

    expect(approvalDecisionActorId(approval)).toBe("plant-operations-owner-role");
    expect(approvalDecisionActorScopes(approval)).toEqual(["approvals:supply:decide"]);
    expect(payload).toEqual({
      decision: "approve",
      actor_id: "plant-operations-owner-role",
      actor_scopes: ["approvals:supply:decide"],
      note: "Console decision recorded for appr_supply_fixture.",
    });
    expect(JSON.stringify(payload)).not.toContain("@");
  });

  it("records an operator rationale as the decision note when provided", () => {
    const approval = findApprovalById(approvalInboxFixture, "appr_supply_fixture");

    expect(
      buildApprovalDecisionPayload(approval, "reject", "Supplier already confirmed.").note,
    ).toBe("Supplier already confirmed.");
    // Whitespace-only rationale falls back to the default console note.
    expect(buildApprovalDecisionPayload(approval, "reject", "   ").note).toBe(
      "Console decision recorded for appr_supply_fixture.",
    );
  });
});
