import { z } from "zod";

import type {
  ActionRunList,
  ActionRunPersistenceResult,
  ManufacturingActionRegistry,
} from "../action-demo";
import {
  autonomyLevelSchema,
  manufacturingProvenanceSchema,
  nullableStringSchema,
  overviewMetricSchema,
  parseContract,
  permissionDecisionSchema,
  platformStatusSchema,
  stringArraySchema,
  stringRecordSchema,
  unknownRecordSchema,
} from "./shared";

const jsonSchema = z.object({
  type: z.string().optional(),
  required: stringArraySchema.optional(),
  properties: z.record(z.string(), z.object({
    type: z.string().optional(),
    items: z.object({ type: z.string().optional() }).passthrough().optional(),
    "x-axis-ontology-ref": z.boolean().optional(),
  }).passthrough()).optional(),
}).passthrough();
const actionRegistry = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  as_of: z.string(),
  registry_status: platformStatusSchema,
  schema_version: z.string(),
  metrics: z.array(overviewMetricSchema),
  filter_options: z.object({
    domains: stringArraySchema,
    risk_levels: z.array(z.enum(["low", "medium", "high", "critical"])),
    approval_modes: z.array(z.enum(["not_required", "required", "conditional"])),
    statuses: stringArraySchema,
  }),
  actions: z.array(z.object({
    definition: z.object({
      action_id: z.string(),
      display_name: z.string(),
      domain: z.string(),
      risk_level: z.enum(["low", "medium", "high", "critical"]),
      approval_mode: z.enum(["not_required", "required", "conditional"]),
      input_schema: jsonSchema,
      output_schema: jsonSchema,
      required_permissions: stringArraySchema,
    }),
    description: z.string(),
    owner_role: z.string(),
    status: z.string(),
    side_effects: z.string(),
    policy: z.object({
      approval_role: z.string(),
      autonomy_ceiling: autonomyLevelSchema,
      execution_mode: z.string(),
      runtime_adapter: z.string(),
      audit_event_type: z.string(),
      model_egress_policy: z.string(),
      idempotency_required: z.boolean(),
      dry_run_supported: z.boolean(),
    }),
    connected_agents: stringArraySchema,
    workflow_bindings: stringArraySchema,
    approval_refs: stringArraySchema,
    guardrails: stringArraySchema,
    validation_checks: stringArraySchema,
    blocked_conditions: stringArraySchema,
    sample_input: stringRecordSchema,
    sample_output: stringRecordSchema,
  })),
  registry_notes: stringArraySchema,
});
const actionRunResult = z.object({
  tenant_id: z.string(),
  action_run_id: z.string(),
  action_id: z.string(),
  idempotency_key: z.string(),
  status: z.string(),
  execution_mode: z.string(),
  requested_by: z.string(),
  approval_required: z.boolean(),
  approval_id: nullableStringSchema.optional(),
  workflow_id: nullableStringSchema.optional(),
  persisted: z.boolean(),
  idempotent_replay: z.boolean(),
  permission_decision: permissionDecisionSchema,
  audit_event_id: nullableStringSchema.optional(),
  audit_event_type: nullableStringSchema.optional(),
  workflow_signal: z.object({
    workflow_id: z.string().optional(),
    status: z.string().optional(),
    adapter: z.string(),
    signal_name: z.string(),
    payload: unknownRecordSchema.optional(),
  }).nullable().optional(),
  workflow_signal_status: z.string(),
});
const actionRunList = z.object({
  tenant_id: z.string(),
  runs: z.array(z.object({
    action_run_id: z.string(),
    action_id: z.string(),
    status: z.string(),
    approval_id: nullableStringSchema,
    workflow_id: nullableStringSchema,
    created_at: z.string(),
    updated_at: z.string(),
    waiting_duration_seconds: z.number().int().nonnegative(),
    outcome: z.object({
      result_summary: z.string(),
      evidence_refs: stringArraySchema,
    }).nullable(),
  })),
});

export function parseManufacturingActionRegistry(value: unknown): ManufacturingActionRegistry {
  return parseContract(actionRegistry, value);
}

export function parseActionRunPersistenceResult(value: unknown): ActionRunPersistenceResult {
  return parseContract(actionRunResult, value);
}

export function parseActionRunList(value: unknown): ActionRunList {
  return parseContract(actionRunList, value);
}
