import type { ManufacturingProvenance, PlatformStatus } from "./platform-overview";
import type { PlatformPolicyDecision } from "./platform-policies";

export type ActionRiskLevel = "low" | "medium" | "high" | "critical";
export type ApprovalMode = "not_required" | "required" | "conditional";

export type ActionJsonSchema = {
  type?: string;
  required?: string[];
  properties?: Record<
    string,
    {
      type?: string;
      items?: { type?: string; [key: string]: unknown };
      "x-axis-ontology-ref"?: boolean;
      [key: string]: unknown;
    }
  >;
  [key: string]: unknown;
};

export type ActionDefinition = {
  action_id: string;
  display_name: string;
  domain: string;
  risk_level: ActionRiskLevel;
  approval_mode: ApprovalMode;
  input_schema: ActionJsonSchema;
  output_schema: ActionJsonSchema;
  required_permissions: string[];
};

export type ActionRegistryPolicy = {
  approval_role: string;
  autonomy_ceiling: "L0" | "L1" | "L2" | "L3" | "L4";
  execution_mode: string;
  runtime_adapter: string;
  audit_event_type: string;
  model_egress_policy: string;
  idempotency_required: boolean;
  dry_run_supported: boolean;
};

export type ActionRegistryEntry = {
  definition: ActionDefinition;
  description: string;
  owner_role: string;
  status: string;
  side_effects: string;
  policy: ActionRegistryPolicy;
  connected_agents: string[];
  workflow_bindings: string[];
  approval_refs: string[];
  guardrails: string[];
  validation_checks: string[];
  blocked_conditions: string[];
  sample_input: Record<string, string>;
  sample_output: Record<string, string>;
};

export type ActionRegistryFilterOptions = {
  domains: string[];
  risk_levels: ActionRiskLevel[];
  approval_modes: ApprovalMode[];
  statuses: string[];
};

export type ManufacturingActionRegistry = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  as_of: string;
  registry_status: PlatformStatus;
  schema_version: string;
  metrics: {
    label: string;
    value: string;
    detail: string;
    status: PlatformStatus;
  }[];
  filter_options: ActionRegistryFilterOptions;
  actions: ActionRegistryEntry[];
  registry_notes: string[];
};

export type ActionRunRequest = {
  actor_id: string;
  actor_scopes: string[];
  idempotency_key?: string;
  payload: Record<string, unknown>;
};

export type ActionRunWorkflowSignal = {
  workflow_id?: string;
  status?: string;
  adapter: string;
  signal_name: string;
  payload?: Record<string, unknown>;
};

export type ActionRunPersistenceResult = {
  tenant_id: string;
  action_run_id: string;
  action_id: string;
  idempotency_key: string;
  status: string;
  execution_mode: string;
  requested_by: string;
  approval_required: boolean;
  approval_id?: string | null;
  workflow_id?: string | null;
  persisted: boolean;
  idempotent_replay: boolean;
  permission_decision: {
    allowed: boolean;
    reason: string;
  };
  audit_event_id?: string | null;
  audit_event_type?: string | null;
  workflow_signal?: ActionRunWorkflowSignal | null;
  workflow_signal_status: string;
  /** Additive workflow and policy evidence emitted by the action runtime. */
  workflow_state_updated?: boolean;
  workflow_state?: string | null;
  workflow_status?: string | null;
  platform_policy_decision?: PlatformPolicyDecision | null;
};

export type ActionRunOutcomeRecord = {
  result_summary: string;
  evidence_refs: string[];
};

export type ActionRunRecord = {
  action_run_id: string;
  action_id: string;
  status: string;
  approval_id: string | null;
  workflow_id: string | null;
  created_at: string;
  updated_at: string;
  waiting_duration_seconds: number;
  outcome: ActionRunOutcomeRecord | null;
};

export type ActionRunList = {
  tenant_id: string;
  runs: ActionRunRecord[];
};

export type ActionRunFollowThrough = {
  awaiting: ActionRunRecord[];
  reported: ActionRunRecord[];
};

export function partitionActionRuns(runs: readonly ActionRunRecord[]): ActionRunFollowThrough {
  const authorisedRuns = runs.filter((run) => run.approval_id !== null);
  const awaiting = authorisedRuns
    .filter((run) => run.status === "approved_for_execution" && run.outcome === null)
    .slice()
    .sort((left, right) =>
      right.waiting_duration_seconds - left.waiting_duration_seconds
      || left.created_at.localeCompare(right.created_at),
    );
  const reported = authorisedRuns
    .filter((run) => run.outcome !== null)
    .slice()
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at));

  return { awaiting, reported };
}

export function actionRunWorkflowSignalLabel(
  result: Pick<ActionRunPersistenceResult, "workflow_signal" | "workflow_signal_status">,
): string {
  if (!result.workflow_signal || result.workflow_signal_status === "not_required") {
    return "workflow signal not required";
  }

  return `${result.workflow_signal_status} via ${result.workflow_signal.adapter} / ${result.workflow_signal.signal_name}`;
}

export type ActionFilters = {
  domain: string;
  riskLevel: string;
  approvalMode: string;
  status: string;
};

export const allActionFilter = "all";

export function filterActions(
  registry: ManufacturingActionRegistry,
  filters: ActionFilters,
): ActionRegistryEntry[] {
  return registry.actions.filter((action) => {
    const domainMatches =
      filters.domain === allActionFilter || action.definition.domain === filters.domain;
    const riskMatches =
      filters.riskLevel === allActionFilter ||
      action.definition.risk_level === filters.riskLevel;
    const approvalMatches =
      filters.approvalMode === allActionFilter ||
      action.definition.approval_mode === filters.approvalMode;
    const statusMatches = filters.status === allActionFilter || action.status === filters.status;

    return domainMatches && riskMatches && approvalMatches && statusMatches;
  });
}

export function findActionById(
  registry: ManufacturingActionRegistry,
  actionId: string,
): ActionRegistryEntry {
  return (
    registry.actions.find((action) => action.definition.action_id === actionId) ??
    registry.actions[0]
  );
}

export function countApprovalGatedActions(registry: ManufacturingActionRegistry): number {
  return registry.actions.filter((action) => action.definition.approval_mode !== "not_required")
    .length;
}

export function formatActionLabel(value: string): string {
  return value
    .split(/[._:-]/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function formatSchemaFields(schema: ActionJsonSchema): string[] {
  return Object.entries(schema.properties ?? {}).map(([name, definition]) => {
    const type =
      definition.type === "array" && definition.items
        ? `${definition.items.type ?? "unknown"}[]`
        : (definition.type ?? "unknown");
    const required = schema.required?.includes(name) ? "required" : "optional";

    return `${name}: ${type} (${required})`;
  });
}

export function buildActionRunIdempotencyKey(
  registry: ManufacturingActionRegistry,
  action: ActionRegistryEntry,
): string {
  const approvalOrPreview = action.approval_refs[0] ?? "preview";

  return `${registry.tenant_id}:${action.definition.action_id}:${approvalOrPreview}`;
}

export function buildTypedActionPayload(action: ActionRegistryEntry): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(action.sample_input).map(([field, value]) => {
      const fieldSchema = action.definition.input_schema.properties?.[field];
      if (fieldSchema?.type === "array") {
        return [
          field,
          value
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
        ];
      }

      return [field, value];
    }),
  );
}

export function buildActionRunRequest(
  registry: ManufacturingActionRegistry,
  action: ActionRegistryEntry,
  actor?: { actorId: string; scopes: string[] },
): ActionRunRequest {
  const payload = buildTypedActionPayload(action);
  if (action.definition.input_schema.properties?.tenant_id) {
    payload.tenant_id = registry.tenant_id;
  }

  return {
    actor_id: actor?.actorId ?? action.connected_agents[0] ?? action.owner_role,
    actor_scopes: actor?.scopes ?? action.definition.required_permissions,
    idempotency_key: buildActionRunIdempotencyKey(registry, action),
    payload,
  };
}
