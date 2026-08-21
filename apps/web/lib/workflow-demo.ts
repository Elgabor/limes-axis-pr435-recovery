import type { ManufacturingProvenance, PlatformStatus } from "./platform-overview";

export type WorkflowSignal = {
  signal: string;
  required_role: string;
  status: string;
  approval_id: string | null;
};

export type WorkflowTimelineEvent = {
  event: string;
  at: string;
  actor: string;
  result: string;
  summary: string;
};

export type WorkflowRun = {
  workflow_id: string;
  name: string;
  domain: string;
  state: string;
  status: PlatformStatus;
  owner_role: string;
  runtime: string;
  adapter: string;
  autonomy_level: "L0" | "L1" | "L2" | "L3" | "L4";
  started_at: string;
  eta: string;
  blocker: string | null;
  objective: string;
  current_step: string;
  related_risk: string;
  related_assets: string[];
  inputs: string[];
  proposed_outputs: string[];
  pending_signals: WorkflowSignal[];
  controls: string[];
  timeline: WorkflowTimelineEvent[];
  audit_scope: string;
  replay_ready: boolean;
};

export type ManufacturingWorkflowConsole = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  as_of: string;
  runtime_status: PlatformStatus;
  metrics: {
    label: string;
    value: string;
    detail: string;
    status: PlatformStatus;
  }[];
  workflow_runs: WorkflowRun[];
  runtime_notes: string[];
};

export function findWorkflowById(
  console: ManufacturingWorkflowConsole,
  workflowId: string,
): WorkflowRun {
  return console.workflow_runs.find((run) => run.workflow_id === workflowId) ?? console.workflow_runs[0];
}

export function countWaitingWorkflowSignals(console: ManufacturingWorkflowConsole): number {
  return console.workflow_runs.reduce(
    (total, run) =>
      total + run.pending_signals.filter((signal) => signal.status === "waiting").length,
    0,
  );
}

export function formatWorkflowState(state: string): string {
  return state
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function shouldUsePersistedWorkflowData(
  console: ManufacturingWorkflowConsole,
): boolean {
  return console.workflow_runs.length > 0;
}

export type WorkflowFilters = {
  state: string;
  domain: string;
};

export const allWorkflowFilter = "all";

/**
 * Filter option lists derived from the registry payload itself — the
 * workflows endpoint does not ship a `filter_options` block, so states keep
 * their runtime ordering and domains are sorted for a stable select list.
 */
export function workflowFilterOptions(console: ManufacturingWorkflowConsole): {
  states: string[];
  domains: string[];
} {
  return {
    states: [...new Set(console.workflow_runs.map((run) => run.state))],
    domains: [...new Set(console.workflow_runs.map((run) => run.domain))].sort(),
  };
}

export function filterWorkflows(
  console: ManufacturingWorkflowConsole,
  filters: WorkflowFilters,
): WorkflowRun[] {
  return console.workflow_runs.filter((run) => {
    const stateMatches = filters.state === allWorkflowFilter || run.state === filters.state;
    const domainMatches = filters.domain === allWorkflowFilter || run.domain === filters.domain;

    return stateMatches && domainMatches;
  });
}

/** The approval a blocked workflow is waiting on, when the record carries one. */
export function workflowBlockingApprovalId(run: WorkflowRun): string | null {
  return run.pending_signals.find((signal) => signal.approval_id)?.approval_id ?? null;
}

/** One plain-language sentence describing where the run stands right now. */
export function workflowStatusLine(run: WorkflowRun): string {
  if (run.blocker) {
    return `Paused at "${run.current_step}" — ${run.blocker.replace(/\.$/, "")}.`;
  }

  return `Now at "${run.current_step}" (${formatWorkflowState(run.state)}), expected ${run.eta}.`;
}

/** Traffic-light tone for a timeline step, derived from its recorded result. */
export function workflowTimelineTone(event: WorkflowTimelineEvent): PlatformStatus {
  const result = event.result.toLowerCase();

  if (/(fail|denied|rejected|error|blocked|timeout|cancel)/.test(result)) {
    return "action_required";
  }

  if (/(waiting|pending|paused|hold|escalat)/.test(result)) {
    return "watch";
  }

  return "ready";
}

/** Compact relative timestamp ("15m ago"); falls back to a short date past 30 days. */
export function formatWorkflowRelativeTime(value: string, now: Date = new Date()): string {
  const elapsedMs = now.getTime() - new Date(value).getTime();
  const minutes = Math.round(elapsedMs / 60_000);

  if (Math.abs(minutes) < 1) {
    return "just now";
  }

  const suffix = minutes >= 0 ? " ago" : "";
  const prefix = minutes < 0 ? "in " : "";
  const absMinutes = Math.abs(minutes);

  if (absMinutes < 60) {
    return `${prefix}${absMinutes}m${suffix}`;
  }

  const hours = Math.round(absMinutes / 60);
  if (hours < 24) {
    return `${prefix}${hours}h${suffix}`;
  }

  const days = Math.round(hours / 24);
  if (days <= 30) {
    return `${prefix}${days}d${suffix}`;
  }

  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(
    new Date(value),
  );
}
