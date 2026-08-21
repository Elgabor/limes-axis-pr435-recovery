import { z } from "zod";

import type { ManufacturingReplaySimulation } from "../simulation-demo";
import { auditEventSchema } from "./audit-event";
import {
  manufacturingProvenanceSchema,
  nullableStringSchema,
  overviewMetricSchema,
  parseContract,
  permissionDecisionSchema,
  platformStatusSchema,
  stringArraySchema,
} from "./shared";

const workflowTimelineEvent = z.object({
  event: z.string(),
  at: z.string(),
  actor: z.string(),
  result: z.string(),
  summary: z.string(),
});
const replayArtifact = z.object({
  artifact_id: z.string(),
  workflow_id: z.string(),
  workflow_name: z.string(),
  audit_scope: z.string(),
  replay_mode: z.string(),
  replay_ready: z.boolean(),
  determinism_status: z.string(),
  timeline_event_count: z.number(),
  audit_event_count: z.number(),
  evidence_refs: stringArraySchema,
  timeline: z.array(workflowTimelineEvent),
  audit_events: z.array(auditEventSchema),
  policy_results: z.array(z.object({
    policy_id: z.string(),
    policy_name: z.string(),
    baseline_decision: z.string(),
    simulated_decision: z.string(),
    changed_outcome: z.boolean(),
    evidence_refs: stringArraySchema,
    summary: z.string(),
  })),
  policy_set_diffs: z.array(z.object({
    diff_id: z.string(),
    connector_id: z.string(),
    baseline_policy_set_id: z.string(),
    baseline_policy_set_version: z.string(),
    candidate_policy_set_id: z.string(),
    candidate_policy_set_version: z.string(),
    historical_event_count: z.number(),
    changed_policy_ids: stringArraySchema,
    baseline_decision: z.string(),
    candidate_decision: z.string(),
    changed_outcome: z.boolean(),
    diff_status: z.string(),
    audit_event_type: z.string(),
    evidence_refs: stringArraySchema,
    summary: z.string(),
  })),
});
const replaySimulation = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  as_of: z.string(),
  simulation_status: platformStatusSchema,
  metrics: z.array(overviewMetricSchema),
  retention_window: z.object({
    policy_id: z.string(),
    retention_days: z.number(),
    legal_hold: z.boolean(),
    retention_enforced: z.boolean(),
    retention_window_start: z.string(),
    disposal_action: z.string(),
    excluded_timeline_event_count: z.number(),
    excluded_audit_event_count: z.number(),
    excluded_output_count: z.number(),
    notes: stringArraySchema,
  }),
  artifacts: z.array(replayArtifact),
  persisted_outputs: z.array(z.object({
    tenant_id: z.string(),
    simulation_output_id: z.string(),
    workflow_id: z.string(),
    artifact_id: z.string(),
    idempotency_key: z.string(),
    status: z.string(),
    requested_by: z.string(),
    required_scope: z.string(),
    replay_mode: z.string(),
    determinism_status: z.string(),
    output_hash: z.string(),
    retention_window_days: z.number(),
    permission_decision: permissionDecisionSchema,
    artifact: replayArtifact,
    evidence_refs: stringArraySchema,
    audit_event_id: nullableStringSchema,
    audit_event_type: z.string(),
    reason: z.string(),
    notes: stringArraySchema,
    idempotent_replay: z.boolean(),
    created_at: z.string(),
  })),
  simulation_notes: stringArraySchema,
});

export function parseManufacturingReplaySimulation(
  value: unknown,
): ManufacturingReplaySimulation {
  return parseContract(replaySimulation, value);
}
