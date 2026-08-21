import { describe, expect, it } from "vitest";

import {
  buildReplaySimulationPath,
  countArtifactPolicyDecisions,
  countChangedPolicySetDiffs,
  countChangedPolicyResults,
  findReplayArtifactById,
  formatSimulationLabel,
  shouldUsePersistedReplayData,
  type ManufacturingReplaySimulation,
  type ReplayArtifact,
} from "./simulation-demo";
import { OPERATIONS_API_PREFIX } from "./tenant-scope";

const replayArtifactFixture: ReplayArtifact = {
  artifact_id: "replay_supply_fixture",
  workflow_id: "wf_supply_fixture",
  workflow_name: "Supply Fixture Review",
  audit_scope: "wf_supply_fixture",
  replay_mode: "governance-preview",
  replay_ready: false,
  determinism_status: "preview_only",
  timeline_event_count: 1,
  audit_event_count: 1,
  evidence_refs: ["wf_supply_fixture", "risk_supply_fixture"],
  timeline: [
    {
      event: "workflow.started",
      at: "2026-06-22T08:30:00+02:00",
      actor: "axis-workflow-runtime",
      result: "started",
      summary: "Workflow started.",
    },
  ],
  audit_events: [
    {
      audit_event_id: "audit_supply_fixture",
      occurred_at: "2026-06-22T09:01:00+02:00",
      tenant_id: "tenant_fixture",
      actor_id: "agent_supply_fixture",
      actor_type: "agent",
      event_type: "agent.proposal.created",
      category: "agent",
      domain: "Supply",
      scope: "wf_supply_fixture",
      result: "pending_owner_review",
      severity: "watch",
      source: "axis-agent-runtime",
      summary: "Agent proposed a governed supply action.",
      permission_scope: "approvals:supply:request",
      data_classification: "internal",
      related_workflow_id: "wf_supply_fixture",
      related_approval_id: "appr_supply_fixture",
      related_agent_id: "agent_supply_fixture",
      evidence_refs: ["risk_supply_fixture"],
      payload_preview: { action_id: "expedite_fixture_batch" },
    },
  ],
  policy_results: [
    {
      policy_id: "human-approval-required",
      policy_name: "Human approval before external mutation",
      baseline_decision: "waiting_for_approval",
      simulated_decision: "blocked_until_human_approval",
      changed_outcome: true,
      evidence_refs: ["wf_supply_fixture"],
      summary: "Owner approval remains required.",
    },
  ],
  policy_set_diffs: [
    {
      diff_id: "policy_set_diff_fixture",
      connector_id: "file_csv_fixture_assets",
      baseline_policy_set_id: "policy_set_current",
      baseline_policy_set_version: "2026-06-22.1",
      candidate_policy_set_id: "policy_set_candidate",
      candidate_policy_set_version: "2026-06-22.2",
      historical_event_count: 2,
      changed_policy_ids: ["connector.asset.required"],
      baseline_decision: "allow_after_validation",
      candidate_decision: "block_until_required_asset_gate",
      changed_outcome: true,
      diff_status: "changed_outcome_detected",
      audit_event_type: "connector.promotion_policy_set.simulated_diff",
      evidence_refs: ["wf_supply_fixture"],
      summary: "Candidate policy set changes the outcome.",
    },
  ],
};

const unchangedReplayArtifactFixture: ReplayArtifact = {
  ...replayArtifactFixture,
  artifact_id: "replay_ops_fixture",
  workflow_id: "wf_ops_fixture",
  workflow_name: "Operations Fixture Brief",
  policy_results: [
    {
      policy_id: "read-only-output",
      policy_name: "Read-only output",
      baseline_decision: "allow",
      simulated_decision: "allow",
      changed_outcome: false,
      evidence_refs: ["wf_ops_fixture"],
      summary: "Read-only output remains allowed.",
    },
  ],
  policy_set_diffs: [],
};

const replaySimulationFixture: ManufacturingReplaySimulation = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Runtime contract fixture",
  provenance: "live",
  as_of: "2026-06-22T09:00:00+02:00",
  simulation_status: "ready",
  metrics: [],
  retention_window: {
    policy_id: "replay-retention-fixture",
    retention_days: 30,
    legal_hold: false,
    retention_enforced: true,
    retention_window_start: "2026-05-22T09:00:00+02:00",
    disposal_action: "enforced_exclusion",
    excluded_timeline_event_count: 0,
    excluded_audit_event_count: 0,
    excluded_output_count: 0,
    notes: ["Fixture data is scoped to tests."],
  },
  artifacts: [replayArtifactFixture, unchangedReplayArtifactFixture],
  persisted_outputs: [
    {
      tenant_id: "tenant_fixture",
      simulation_output_id: "replay_output_fixture",
      workflow_id: "wf_supply_fixture",
      artifact_id: "replay_supply_fixture",
      idempotency_key: "tenant_fixture:replay_supply_fixture",
      status: "persisted",
      requested_by: "simulation-owner-role",
      required_scope: "simulation:replay:persist",
      replay_mode: "governance-preview",
      determinism_status: "preview_only",
      output_hash: "hash_fixture",
      retention_window_days: 30,
      permission_decision: {
        allowed: true,
        reason: "allowed",
      },
      artifact: replayArtifactFixture,
      evidence_refs: ["wf_supply_fixture"],
      audit_event_id: "audit_replay_fixture",
      audit_event_type: "simulation.replay_output.persisted",
      reason: "Persist fixture replay output.",
      notes: ["Fixture data is scoped to tests."],
      idempotent_replay: false,
      created_at: "2026-06-22T09:00:00+02:00",
    },
  ],
  simulation_notes: ["Fixture data is scoped to tests."],
};

describe("replay simulation helpers", () => {
  it("finds artifacts and counts policy outcome changes", () => {
    expect(findReplayArtifactById(replaySimulationFixture, "wf_supply_fixture").workflow_name).toBe(
      "Supply Fixture Review",
    );
    expect(countChangedPolicyResults(replaySimulationFixture)).toBe(1);
    expect(countChangedPolicySetDiffs(replaySimulationFixture)).toBe(1);
  });

  it("uses persisted replay data only when artifacts are available", () => {
    expect(shouldUsePersistedReplayData(replaySimulationFixture)).toBe(true);
    expect(
      shouldUsePersistedReplayData({
        ...replaySimulationFixture,
        simulation_status: "watch",
        artifacts: [],
      }),
    ).toBe(false);
  });

  it("formats simulation labels", () => {
    expect(formatSimulationLabel("changed_outcome_detected")).toBe("Changed Outcome Detected");
  });
});

describe("buildReplaySimulationPath", () => {
  it("always scopes to the tenant and omits unset params", () => {
    expect(buildReplaySimulationPath({ tenantId: "tenant_fixture" })).toBe(
      `${OPERATIONS_API_PREFIX}/simulation/replay?tenant_id=tenant_fixture`,
    );
  });

  it("serializes every replay parameter the API accepts", () => {
    const path = buildReplaySimulationPath({
      tenantId: "tenant_fixture",
      workflowId: "wf_supply_fixture",
      limit: 50,
      retentionDays: 90,
      legalHold: true,
      baselinePolicySetId: "policy_set_baseline_v1",
      candidatePolicySetId: "policy_set_candidate_v2",
      connectorId: "connector_csv_assets",
    });
    const query = new URLSearchParams(path.split("?")[1]);

    expect(path.startsWith(`${OPERATIONS_API_PREFIX}/simulation/replay?`)).toBe(true);
    expect(Object.fromEntries(query.entries())).toEqual({
      tenant_id: "tenant_fixture",
      workflow_id: "wf_supply_fixture",
      limit: "50",
      retention_days: "90",
      legal_hold: "true",
      baseline_policy_set_id: "policy_set_baseline_v1",
      candidate_policy_set_id: "policy_set_candidate_v2",
      connector_id: "connector_csv_assets",
    });
  });

  it("ignores whitespace-only optional ids and false legal hold", () => {
    const path = buildReplaySimulationPath({
      tenantId: "tenant_fixture",
      workflowId: "  ",
      legalHold: false,
      baselinePolicySetId: "",
      candidatePolicySetId: "  ",
      connectorId: "",
    });
    expect(path).toBe(`${OPERATIONS_API_PREFIX}/simulation/replay?tenant_id=tenant_fixture`);
  });

  it("counts total and changed policy decisions across artifacts", () => {
    expect(countArtifactPolicyDecisions([replayArtifactFixture])).toEqual({
      total: replayArtifactFixture.policy_results.length,
      changed: replayArtifactFixture.policy_results.filter((r) => r.changed_outcome).length,
    });
  });
});
