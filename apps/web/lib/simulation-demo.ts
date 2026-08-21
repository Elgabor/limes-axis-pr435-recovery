import type { AuditLedgerEvent } from "./audit-demo";
import type { ManufacturingProvenance, PlatformStatus } from "./platform-overview";
import type { WorkflowTimelineEvent } from "./workflow-demo";
import { OPERATIONS_API_PREFIX } from "./tenant-scope";

export type PolicySimulationResult = {
  policy_id: string;
  policy_name: string;
  baseline_decision: string;
  simulated_decision: string;
  changed_outcome: boolean;
  evidence_refs: string[];
  summary: string;
};

export type PolicySetVersionDiff = {
  diff_id: string;
  connector_id: string;
  baseline_policy_set_id: string;
  baseline_policy_set_version: string;
  candidate_policy_set_id: string;
  candidate_policy_set_version: string;
  historical_event_count: number;
  changed_policy_ids: string[];
  baseline_decision: string;
  candidate_decision: string;
  changed_outcome: boolean;
  diff_status: string;
  audit_event_type: string;
  evidence_refs: string[];
  summary: string;
};

export type ReplayArtifact = {
  artifact_id: string;
  workflow_id: string;
  workflow_name: string;
  audit_scope: string;
  replay_mode: string;
  replay_ready: boolean;
  determinism_status: string;
  timeline_event_count: number;
  audit_event_count: number;
  evidence_refs: string[];
  timeline: WorkflowTimelineEvent[];
  audit_events: AuditLedgerEvent[];
  policy_results: PolicySimulationResult[];
  policy_set_diffs: PolicySetVersionDiff[];
};

export type ReplaySimulationOutputRecord = {
  tenant_id: string;
  simulation_output_id: string;
  workflow_id: string;
  artifact_id: string;
  idempotency_key: string;
  status: string;
  requested_by: string;
  required_scope: string;
  replay_mode: string;
  determinism_status: string;
  output_hash: string;
  retention_window_days: number;
  permission_decision: {
    allowed: boolean;
    reason: string;
  };
  artifact: ReplayArtifact;
  evidence_refs: string[];
  audit_event_id: string | null;
  audit_event_type: string;
  reason: string;
  notes: string[];
  idempotent_replay: boolean;
  created_at: string;
};

export type ReplayRetentionWindow = {
  policy_id: string;
  retention_days: number;
  legal_hold: boolean;
  retention_enforced: boolean;
  retention_window_start: string;
  disposal_action: string;
  excluded_timeline_event_count: number;
  excluded_audit_event_count: number;
  excluded_output_count: number;
  notes: string[];
};

export type ManufacturingReplaySimulation = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  as_of: string;
  simulation_status: PlatformStatus;
  metrics: {
    label: string;
    value: string;
    detail: string;
    status: PlatformStatus;
  }[];
  retention_window: ReplayRetentionWindow;
  artifacts: ReplayArtifact[];
  persisted_outputs: ReplaySimulationOutputRecord[];
  simulation_notes: string[];
};

/**
 * Parameters of GET /operations/simulation/replay, verified against
 * `ReplaySimulationQuery` in services/api/src/axis_api/replay_simulation.py.
 */
export type ReplayRunParams = {
  tenantId: string;
  workflowId?: string;
  limit?: number;
  retentionDays?: number;
  legalHold?: boolean;
  baselinePolicySetId?: string;
  candidatePolicySetId?: string;
  connectorId?: string;
};

export function buildReplaySimulationPath(params: ReplayRunParams): string {
  const query = new URLSearchParams({ tenant_id: params.tenantId });
  const workflowId = params.workflowId?.trim();
  if (workflowId) {
    query.set("workflow_id", workflowId);
  }
  if (params.limit !== undefined) {
    query.set("limit", String(params.limit));
  }
  if (params.retentionDays !== undefined) {
    query.set("retention_days", String(params.retentionDays));
  }
  if (params.legalHold) {
    query.set("legal_hold", "true");
  }
  const baseline = params.baselinePolicySetId?.trim();
  if (baseline) {
    query.set("baseline_policy_set_id", baseline);
  }
  const candidate = params.candidatePolicySetId?.trim();
  if (candidate) {
    query.set("candidate_policy_set_id", candidate);
  }
  const connector = params.connectorId?.trim();
  if (connector) {
    query.set("connector_id", connector);
  }
  return `${OPERATIONS_API_PREFIX}/simulation/replay?${query.toString()}`;
}

export function countArtifactPolicyDecisions(artifacts: ReplayArtifact[]): {
  total: number;
  changed: number;
} {
  let total = 0;
  let changed = 0;
  for (const artifact of artifacts) {
    for (const result of artifact.policy_results) {
      total += 1;
      if (result.changed_outcome) {
        changed += 1;
      }
    }
  }
  return { total, changed };
}

export function shouldUsePersistedReplayData(data: ManufacturingReplaySimulation): boolean {
  return data.simulation_status === "ready" && data.artifacts.length > 0;
}

export function findReplayArtifactById(
  data: ManufacturingReplaySimulation,
  artifactIdOrWorkflowId: string,
): ReplayArtifact {
  return (
    data.artifacts.find(
      (artifact) =>
        artifact.artifact_id === artifactIdOrWorkflowId ||
        artifact.workflow_id === artifactIdOrWorkflowId,
    ) ?? data.artifacts[0]
  );
}

export function countChangedPolicyResults(data: ManufacturingReplaySimulation): number {
  return data.artifacts.reduce(
    (total, artifact) =>
      total + artifact.policy_results.filter((result) => result.changed_outcome).length,
    0,
  );
}

export function countChangedPolicySetDiffs(data: ManufacturingReplaySimulation): number {
  return data.artifacts.reduce(
    (total, artifact) =>
      total + (artifact.policy_set_diffs ?? []).filter((diff) => diff.changed_outcome).length,
    0,
  );
}

export function formatSimulationLabel(value: string): string {
  return value
    .split(/[_-]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
