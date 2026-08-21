import { describe, expect, it } from "vitest";

import {
  allWorkflowFilter,
  countWaitingWorkflowSignals,
  filterWorkflows,
  findWorkflowById,
  formatWorkflowRelativeTime,
  formatWorkflowState,
  shouldUsePersistedWorkflowData,
  workflowBlockingApprovalId,
  workflowFilterOptions,
  workflowStatusLine,
  workflowTimelineTone,
  type ManufacturingWorkflowConsole,
} from "./workflow-demo";

const workflowConsoleFixture: ManufacturingWorkflowConsole = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Runtime contract fixture",
  provenance: "reference_scenario",
  as_of: "2026-06-22T09:00:00+02:00",
  runtime_status: "watch",
  metrics: [],
  workflow_runs: [
    {
      workflow_id: "wf_supply_fixture",
      name: "Supply Fixture Review",
      domain: "Supply",
      state: "waiting_for_approval",
      status: "action_required",
      owner_role: "supply-owner",
      runtime: "Temporal OSS",
      adapter: "axis-temporal-adapter",
      autonomy_level: "L2",
      started_at: "2026-06-22T08:30:00+02:00",
      eta: "Today 17:30",
      blocker: "Owner approval required",
      objective: "Resolve a delayed supplier batch.",
      current_step: "Approval gate",
      related_risk: "risk_supply_fixture",
      related_assets: ["asset_fixture_line"],
      inputs: ["Supplier status"],
      proposed_outputs: ["Expedite fixture batch"],
      pending_signals: [
        {
          signal: "approval_decision",
          required_role: "supply-owner",
          status: "waiting",
          approval_id: "appr_supply_fixture",
        },
      ],
      controls: ["Human approval required"],
      timeline: [
        {
          event: "workflow.started",
          at: "2026-06-22T08:30:00+02:00",
          actor: "axis-workflow-runtime",
          result: "started",
          summary: "Workflow started.",
        },
      ],
      audit_scope: "wf_supply_fixture",
      replay_ready: false,
    },
    {
      workflow_id: "wf_ops_fixture",
      name: "Operations Fixture Brief",
      domain: "Operations",
      state: "proposal_ready",
      status: "ready",
      owner_role: "operations-owner",
      runtime: "Temporal OSS",
      adapter: "axis-temporal-adapter",
      autonomy_level: "L1",
      started_at: "2026-06-22T08:45:00+02:00",
      eta: "Today 12:00",
      blocker: null,
      objective: "Prepare read-only shift summary.",
      current_step: "Review summary",
      related_risk: "risk_ops_fixture",
      related_assets: ["asset_fixture_line"],
      inputs: ["Shift status"],
      proposed_outputs: ["Daily brief"],
      pending_signals: [],
      controls: ["Read-only output"],
      timeline: [
        {
          event: "proposal.ready",
          at: "2026-06-22T08:50:00+02:00",
          actor: "agent_ops_fixture",
          result: "ready",
          summary: "Proposal prepared.",
        },
      ],
      audit_scope: "wf_ops_fixture",
      replay_ready: true,
    },
  ],
  runtime_notes: ["Fixture data is scoped to tests."],
};

describe("workflow console helpers", () => {
  it("counts waiting workflow signals", () => {
    expect(countWaitingWorkflowSignals(workflowConsoleFixture)).toBe(1);
  });

  it("finds workflows by id with a safe fallback", () => {
    expect(findWorkflowById(workflowConsoleFixture, "wf_ops_fixture").name).toBe(
      "Operations Fixture Brief",
    );
    expect(findWorkflowById(workflowConsoleFixture, "missing").name).toBe(
      "Supply Fixture Review",
    );
  });

  it("formats workflow state labels", () => {
    expect(formatWorkflowState("waiting_for_approval")).toBe("Waiting For Approval");
    expect(formatWorkflowState("proposal_ready")).toBe("Proposal Ready");
  });

  it("uses persisted workflow data only when workflow runs exist", () => {
    expect(shouldUsePersistedWorkflowData(workflowConsoleFixture)).toBe(true);
    expect(
      shouldUsePersistedWorkflowData({
        ...workflowConsoleFixture,
        workflow_runs: [],
      }),
    ).toBe(false);
  });
});

describe("workflow filters", () => {
  it("derives state and domain filter options from the payload", () => {
    expect(workflowFilterOptions(workflowConsoleFixture)).toEqual({
      states: ["waiting_for_approval", "proposal_ready"],
      domains: ["Operations", "Supply"],
    });
  });

  it("deduplicates repeated states and domains", () => {
    const doubled = {
      ...workflowConsoleFixture,
      workflow_runs: [
        ...workflowConsoleFixture.workflow_runs,
        ...workflowConsoleFixture.workflow_runs,
      ],
    };
    expect(workflowFilterOptions(doubled)).toEqual({
      states: ["waiting_for_approval", "proposal_ready"],
      domains: ["Operations", "Supply"],
    });
  });

  it("returns every run when both filters are set to all", () => {
    expect(
      filterWorkflows(workflowConsoleFixture, {
        state: allWorkflowFilter,
        domain: allWorkflowFilter,
      }),
    ).toHaveLength(2);
  });

  it("filters runs by state and domain", () => {
    expect(
      filterWorkflows(workflowConsoleFixture, {
        state: "waiting_for_approval",
        domain: allWorkflowFilter,
      }).map((run) => run.workflow_id),
    ).toEqual(["wf_supply_fixture"]);
    expect(
      filterWorkflows(workflowConsoleFixture, {
        state: allWorkflowFilter,
        domain: "Operations",
      }).map((run) => run.workflow_id),
    ).toEqual(["wf_ops_fixture"]);
    expect(
      filterWorkflows(workflowConsoleFixture, {
        state: "proposal_ready",
        domain: "Supply",
      }),
    ).toEqual([]);
  });
});

describe("workflow detail helpers", () => {
  const [waitingRun, readyRun] = workflowConsoleFixture.workflow_runs;

  it("finds the blocking approval id from pending signals", () => {
    expect(workflowBlockingApprovalId(waitingRun)).toBe("appr_supply_fixture");
    expect(workflowBlockingApprovalId(readyRun)).toBeNull();
  });

  it("writes a plain-language status line", () => {
    expect(workflowStatusLine(waitingRun)).toBe(
      'Paused at "Approval gate" — Owner approval required.',
    );
    expect(workflowStatusLine(readyRun)).toBe(
      'Now at "Review summary" (Proposal Ready), expected Today 12:00.',
    );
  });

  it("assigns timeline tones from the step result", () => {
    const baseEvent = workflowConsoleFixture.workflow_runs[0].timeline[0];
    expect(workflowTimelineTone({ ...baseEvent, result: "started" })).toBe("ready");
    expect(workflowTimelineTone({ ...baseEvent, result: "completed" })).toBe("ready");
    expect(workflowTimelineTone({ ...baseEvent, result: "waiting" })).toBe("watch");
    expect(workflowTimelineTone({ ...baseEvent, result: "pending_approval" })).toBe("watch");
    expect(workflowTimelineTone({ ...baseEvent, result: "failed" })).toBe("action_required");
    expect(workflowTimelineTone({ ...baseEvent, result: "denied" })).toBe("action_required");
  });

  it("formats relative timestamps against a reference time", () => {
    const now = new Date("2026-06-22T10:00:00+02:00");
    expect(formatWorkflowRelativeTime("2026-06-22T09:59:40+02:00", now)).toBe("just now");
    expect(formatWorkflowRelativeTime("2026-06-22T09:45:00+02:00", now)).toBe("15m ago");
    expect(formatWorkflowRelativeTime("2026-06-22T07:00:00+02:00", now)).toBe("3h ago");
    expect(formatWorkflowRelativeTime("2026-06-20T10:00:00+02:00", now)).toBe("2d ago");
    expect(formatWorkflowRelativeTime("2026-04-01T10:00:00+02:00", now)).toBe("Apr 1");
  });
});
