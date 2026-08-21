import { OPERATIONS_API_PREFIX } from "./tenant-scope";
/**
 * Typed parsers for the live agent-run read surfaces:
 *
 * - GET /operations/agents/{agent_id}/runs — persisted run records
 *   (status, mode, autonomy level, model invocation links, step timeline).
 * - GET /operations/agents/{agent_id}/runs/{run_id} — single run.
 *
 * Runs carry reference-based evidence only: prompts and model outputs are
 * never persisted on the run. Parsing is strict — unexpected shapes raise
 * AgentRunsLiveParseError instead of degrading into fabricated defaults.
 */

export const AGENT_RUN_EXECUTION_FLAG = "AXIS_AGENT_RUN_EXECUTION_ENABLED";

export const agentRunStepOrder = ["context_read", "model_invocation", "proposal"] as const;

export type AgentRunStepType = (typeof agentRunStepOrder)[number];

export function agentRunsPath(agentId: string, pageSize = 20): string {
  const params = new URLSearchParams({ page_size: String(pageSize) });
  return `${OPERATIONS_API_PREFIX}/agents/${encodeURIComponent(agentId)}/runs?${params.toString()}`;
}

export function agentRunDetailPath(agentId: string, runId: string): string {
  return `${OPERATIONS_API_PREFIX}/agents/${encodeURIComponent(agentId)}/runs/${encodeURIComponent(runId)}`;
}

export function modelInvocationDetailPath(invocationId: string): string {
  return `/platform/models/invocations/${encodeURIComponent(invocationId)}`;
}

/** Deep-link a proposed action run into the approvals queue, mirroring the
 * audit explorer's `?event_id=` query-param convention. */
export function buildApprovalActionRunHref(
  proposedActionRunId: string | null | undefined,
): string {
  if (!proposedActionRunId) {
    return "/approvals";
  }
  const params = new URLSearchParams({ action_run_id: proposedActionRunId });
  return `/approvals?${params.toString()}`;
}

export class AgentRunsLiveParseError extends Error {
  readonly field: string;

  constructor(field: string, expected: string) {
    super(`Invalid agent run payload: ${field} is not ${expected}`);
    this.name = "AgentRunsLiveParseError";
    this.field = field;
  }
}

function asRecord(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new AgentRunsLiveParseError(field, "an object");
  }
  return value as Record<string, unknown>;
}

function asString(value: unknown, field: string): string {
  if (typeof value !== "string") {
    throw new AgentRunsLiveParseError(field, "a string");
  }
  return value;
}

function asOptionalString(value: unknown, field: string): string | null {
  if (value === undefined || value === null) {
    return null;
  }
  return asString(value, field);
}

function asNumber(value: unknown, field: string): number {
  if (typeof value !== "number" || Number.isNaN(value)) {
    throw new AgentRunsLiveParseError(field, "a number");
  }
  return value;
}

function asStringArray(value: unknown, field: string): string[] {
  if (value === undefined || value === null) {
    return [];
  }
  if (!Array.isArray(value)) {
    throw new AgentRunsLiveParseError(field, "an array of strings");
  }
  return value.map((entry, index) => asString(entry, `${field}[${index}]`));
}

export type AgentRunStep = {
  seq: number;
  step_type: string;
  status: string;
  created_at: string;
  evidence: Record<string, unknown>;
};

export type AgentRunRecord = {
  run_id: string;
  agent_id: string;
  status: string;
  mode: string;
  autonomy_level: string;
  requested_by: string;
  created_at: string;
  model_invocation_ids: string[];
  proposed_action_run_id: string | null;
  audit_event_id: string | null;
  error_reason: string | null;
  idempotent_replay: boolean;
  notes: string[];
  steps: AgentRunStep[];
};

export type AgentRunList = {
  tenant_id: string;
  agent_id: string;
  runs: AgentRunRecord[];
  has_more: boolean;
  next_cursor: string | null;
  run_notes: string[];
};

export function parseAgentRun(input: unknown, field = "run"): AgentRunRecord {
  const run = asRecord(input, field);
  const at = (name: string) => `${field}.${name}`;
  const stepsInput = run.steps ?? [];
  if (!Array.isArray(stepsInput)) {
    throw new AgentRunsLiveParseError(at("steps"), "an array");
  }

  return {
    run_id: asString(run.run_id, at("run_id")),
    agent_id: asString(run.agent_id, at("agent_id")),
    status: asString(run.status, at("status")),
    mode: asString(run.mode, at("mode")),
    autonomy_level: asString(run.autonomy_level, at("autonomy_level")),
    requested_by: asString(run.requested_by, at("requested_by")),
    created_at: asString(run.created_at, at("created_at")),
    model_invocation_ids: asStringArray(run.model_invocation_ids, at("model_invocation_ids")),
    proposed_action_run_id: asOptionalString(
      run.proposed_action_run_id,
      at("proposed_action_run_id"),
    ),
    audit_event_id: asOptionalString(run.audit_event_id, at("audit_event_id")),
    error_reason: asOptionalString(run.error_reason, at("error_reason")),
    idempotent_replay: run.idempotent_replay === true,
    notes: asStringArray(run.notes, at("notes")),
    steps: stepsInput
      .map((entry, index) => {
        const step = asRecord(entry, `${at("steps")}[${index}]`);
        const stepField = (name: string) => `${at("steps")}[${index}].${name}`;
        return {
          seq: asNumber(step.seq, stepField("seq")),
          step_type: asString(step.step_type, stepField("step_type")),
          status: asString(step.status, stepField("status")),
          created_at: asString(step.created_at, stepField("created_at")),
          evidence:
            step.evidence === undefined || step.evidence === null
              ? {}
              : asRecord(step.evidence, stepField("evidence")),
        };
      })
      .sort((left, right) => left.seq - right.seq),
  };
}

export function parseAgentRunList(input: unknown): AgentRunList {
  const payload = asRecord(input, "runs");
  const runsInput = payload.runs ?? [];
  if (!Array.isArray(runsInput)) {
    throw new AgentRunsLiveParseError("runs.runs", "an array");
  }

  return {
    tenant_id: asString(payload.tenant_id, "runs.tenant_id"),
    agent_id: asString(payload.agent_id, "runs.agent_id"),
    runs: runsInput.map((entry, index) => parseAgentRun(entry, `runs.runs[${index}]`)),
    has_more: payload.has_more === true,
    next_cursor: asOptionalString(payload.next_cursor, "runs.next_cursor"),
    run_notes: asStringArray(payload.run_notes, "runs.run_notes"),
  };
}

export function agentRunStatusLabel(status: string): string {
  if (!status) {
    return "Unknown";
  }
  const compact = status.replaceAll("_", " ");
  return compact.charAt(0).toUpperCase() + compact.slice(1);
}

export function agentRunStatusClass(status: string): string {
  if (
    status === "proposal_recorded"
    || status === "proposal_created"
    || status === "dry_run_completed"
  ) {
    return "signal-ready";
  }
  if (status === "requested" || status === "deferred") {
    return "signal-watch";
  }
  return "signal-action-required";
}

export function isDeferredAgentRunStatus(status: string): boolean {
  return status === "deferred";
}

export type AgentRunRailState = "done" | "current" | "failed" | "pending";

export type AgentRunRailStage = {
  step_type: AgentRunStepType;
  label: string;
  detail: string;
  state: AgentRunRailState;
};

const railLabels: Record<AgentRunStepType, string> = {
  context_read: "Context read",
  model_invocation: "Model call",
  proposal: "Proposal",
};

/**
 * Project the persisted step records onto the fixed context_read →
 * model_invocation → proposal rail. Steps that never happened stay pending;
 * a failed / blocked / deferred step marks its stage and everything after it
 * stays pending — no synthetic progress is ever shown.
 */
export function buildAgentRunRail(run: AgentRunRecord): AgentRunRailStage[] {
  let blockedSeen = false;

  return agentRunStepOrder.map((stepType) => {
    const step = run.steps.find((candidate) => candidate.step_type === stepType);

    if (!step || blockedSeen) {
      return {
        step_type: stepType,
        label: railLabels[stepType],
        detail: blockedSeen ? "Not reached" : "Not recorded",
        state: "pending" as const,
      };
    }

    if (step.status === "completed") {
      return {
        step_type: stepType,
        label: railLabels[stepType],
        detail: agentRunStatusLabel(step.status),
        state: "done" as const,
      };
    }

    blockedSeen = true;
    return {
      step_type: stepType,
      label: railLabels[stepType],
      detail: agentRunStatusLabel(step.status),
      state: step.status === "deferred" ? ("current" as const) : ("failed" as const),
    };
  });
}
