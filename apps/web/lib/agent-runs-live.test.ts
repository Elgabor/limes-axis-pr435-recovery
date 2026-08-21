import { describe, expect, it } from "vitest";

import {
  AgentRunsLiveParseError,
  agentRunDetailPath,
  agentRunStatusClass,
  agentRunStatusLabel,
  agentRunsPath,
  buildAgentRunRail,
  buildApprovalActionRunHref,
  isDeferredAgentRunStatus,
  modelInvocationDetailPath,
  parseAgentRun,
  parseAgentRunList,
} from "./agent-runs-live";
import { OPERATIONS_API_PREFIX } from "./tenant-scope";

const runFixture = {
  tenant_id: "tenant_demo_manufacturing",
  run_id: "5a4b3c2d-3333-4e5f-8a9b-1c2d3e4f5a6b",
  agent_id: "agent_quality_risk",
  idempotency_key: "idem-run-1",
  status: "proposal_recorded",
  mode: "propose",
  requested_by: "plant-operations-owner-role",
  autonomy_level: "L1",
  context_refs: ["risk_quality_003"],
  model_invocation_ids: ["3d1c2a3e-1111-4f2b-8a3c-9d8e7f6a5b4c"],
  proposed_action_run_id: null,
  proposal_payload: { action_id: "hold_batch" },
  permission_decision: { allowed: true, reason: "scope_present" },
  audit_event_id: "audit-uuid-3",
  audit_event_type: "agent.run.proposal_recorded",
  error_reason: null,
  idempotent_replay: false,
  notes: [],
  created_at: "2026-07-09T11:00:00Z",
  steps: [
    {
      seq: 2,
      step_type: "model_invocation",
      status: "completed",
      created_at: "2026-07-09T11:00:02Z",
      evidence: { model_invocation_id: "3d1c2a3e-1111-4f2b-8a3c-9d8e7f6a5b4c" },
    },
    {
      seq: 1,
      step_type: "context_read",
      status: "completed",
      created_at: "2026-07-09T11:00:01Z",
      evidence: { context_refs: ["risk_quality_003"] },
    },
    {
      seq: 3,
      step_type: "proposal",
      status: "completed",
      created_at: "2026-07-09T11:00:03Z",
      evidence: { action_id: "hold_batch" },
    },
  ],
};

describe("agent run live paths", () => {
  it("targets the persisted agent run surfaces", () => {
    expect(agentRunsPath("agent_quality_risk")).toBe(
      `${OPERATIONS_API_PREFIX}/agents/agent_quality_risk/runs?page_size=20`,
    );
    expect(agentRunDetailPath("agent_quality_risk", "run-1")).toBe(
      `${OPERATIONS_API_PREFIX}/agents/agent_quality_risk/runs/run-1`,
    );
    expect(modelInvocationDetailPath("inv-1")).toBe("/platform/models/invocations/inv-1");
  });

  it("deep-links proposed action runs into the approvals queue", () => {
    expect(buildApprovalActionRunHref("run-uuid-1")).toBe(
      "/approvals?action_run_id=run-uuid-1",
    );
    expect(buildApprovalActionRunHref(null)).toBe("/approvals");
  });
});

describe("parseAgentRunList", () => {
  it("parses persisted runs and orders steps by sequence", () => {
    const list = parseAgentRunList({
      tenant_id: "tenant_demo_manufacturing",
      agent_id: "agent_quality_risk",
      runs: [runFixture],
      has_more: false,
      next_cursor: null,
      run_notes: ["Runs are listed newest-first with keyset continuation."],
    });

    expect(list.agent_id).toBe("agent_quality_risk");
    expect(list.runs).toHaveLength(1);
    const run = list.runs[0];
    expect(run).toMatchObject({
      run_id: runFixture.run_id,
      status: "proposal_recorded",
      mode: "propose",
      autonomy_level: "L1",
      model_invocation_ids: ["3d1c2a3e-1111-4f2b-8a3c-9d8e7f6a5b4c"],
      proposed_action_run_id: null,
    });
    expect(run.steps.map((step) => step.step_type)).toEqual([
      "context_read",
      "model_invocation",
      "proposal",
    ]);
  });

  it("accepts an empty run list without fabricating runs", () => {
    const list = parseAgentRunList({
      tenant_id: "tenant_demo_manufacturing",
      agent_id: "agent_quality_risk",
    });

    expect(list.runs).toEqual([]);
    expect(list.has_more).toBe(false);
  });

  it("rejects malformed run payloads", () => {
    expect(() => parseAgentRunList(null)).toThrow(AgentRunsLiveParseError);
    expect(() => parseAgentRun({ ...runFixture, status: 7 })).toThrow(/status/);
    expect(() => parseAgentRun({ ...runFixture, steps: "none" })).toThrow(/steps/);
  });
});

describe("parseAgentRun on the run detail surface", () => {
  it("parses list-shaped runs without steps to an empty step list", () => {
    // The runs LIST endpoint omits step records; only the run DETAIL
    // endpoint carries them. The runs panel must therefore fetch the detail
    // before rendering a step rail with real statuses.
    const listShapedRun: Record<string, unknown> = { ...runFixture };
    delete listShapedRun.steps;

    expect(parseAgentRun(listShapedRun).steps).toEqual([]);
    expect(parseAgentRun({ ...runFixture, steps: [] }).steps).toEqual([]);
  });

  it("parses detail payloads into an ordered step rail with recorded statuses", () => {
    const detailRun = parseAgentRun(runFixture);

    expect(detailRun.steps.map((step) => [step.step_type, step.status])).toEqual([
      ["context_read", "completed"],
      ["model_invocation", "completed"],
      ["proposal", "completed"],
    ]);
    expect(buildAgentRunRail(detailRun).map((stage) => stage.state)).toEqual([
      "done",
      "done",
      "done",
    ]);
  });
});

describe("agent run status helpers", () => {
  it("labels and classifies run statuses", () => {
    expect(agentRunStatusLabel("proposal_recorded")).toBe("Proposal recorded");
    expect(agentRunStatusClass("proposal_recorded")).toBe("signal-ready");
    expect(agentRunStatusClass("dry_run_completed")).toBe("signal-ready");
    expect(agentRunStatusClass("deferred")).toBe("signal-watch");
    expect(agentRunStatusClass("blocked")).toBe("signal-action-required");
    expect(agentRunStatusClass("failed_model_invocation")).toBe("signal-action-required");
    expect(isDeferredAgentRunStatus("deferred")).toBe(true);
    expect(isDeferredAgentRunStatus("proposal_recorded")).toBe(false);
  });
});

describe("buildAgentRunRail", () => {
  it("marks every recorded completed step as done", () => {
    const rail = buildAgentRunRail(parseAgentRun(runFixture));

    expect(rail.map((stage) => stage.state)).toEqual(["done", "done", "done"]);
    expect(rail.map((stage) => stage.label)).toEqual([
      "Context read",
      "Model call",
      "Proposal",
    ]);
  });

  it("keeps unreached stages pending after a deferred model call", () => {
    const rail = buildAgentRunRail(
      parseAgentRun({
        ...runFixture,
        status: "deferred",
        steps: [
          runFixture.steps[1],
          {
            seq: 2,
            step_type: "model_invocation",
            status: "deferred",
            created_at: "2026-07-09T11:00:02Z",
            evidence: {},
          },
        ],
      }),
    );

    expect(rail.map((stage) => stage.state)).toEqual(["done", "current", "pending"]);
    expect(rail[2].detail).toBe("Not reached");
  });

  it("marks blocked steps as failed without synthetic progress", () => {
    const rail = buildAgentRunRail(
      parseAgentRun({
        ...runFixture,
        status: "blocked",
        steps: [
          {
            seq: 1,
            step_type: "context_read",
            status: "blocked",
            created_at: "2026-07-09T11:00:01Z",
            evidence: { reason: "permission_denied" },
          },
        ],
      }),
    );

    expect(rail.map((stage) => stage.state)).toEqual(["failed", "pending", "pending"]);
  });

  it("reports unrecorded steps honestly for requested runs", () => {
    const rail = buildAgentRunRail(parseAgentRun({ ...runFixture, steps: [] }));

    expect(rail.map((stage) => stage.state)).toEqual(["pending", "pending", "pending"]);
    expect(rail[0].detail).toBe("Not recorded");
  });
});
