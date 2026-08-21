import { z } from "zod";

import type { ManufacturingWorkflowConsole } from "../workflow-demo";
import {
  autonomyLevelSchema,
  manufacturingProvenanceSchema,
  nullableStringSchema,
  overviewMetricSchema,
  parseContract,
  platformStatusSchema,
  stringArraySchema,
} from "./shared";

const workflowConsole = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  as_of: z.string(),
  runtime_status: platformStatusSchema,
  metrics: z.array(overviewMetricSchema),
  workflow_runs: z.array(z.object({
    workflow_id: z.string(),
    name: z.string(),
    domain: z.string(),
    state: z.string(),
    status: platformStatusSchema,
    owner_role: z.string(),
    runtime: z.string(),
    adapter: z.string(),
    autonomy_level: autonomyLevelSchema,
    started_at: z.string(),
    eta: z.string(),
    blocker: nullableStringSchema,
    objective: z.string(),
    current_step: z.string(),
    related_risk: z.string(),
    related_assets: stringArraySchema,
    inputs: stringArraySchema,
    proposed_outputs: stringArraySchema,
    pending_signals: z.array(z.object({
      signal: z.string(),
      required_role: z.string(),
      status: z.string(),
      approval_id: nullableStringSchema,
    })),
    controls: stringArraySchema,
    timeline: z.array(z.object({
      event: z.string(),
      at: z.string(),
      actor: z.string(),
      result: z.string(),
      summary: z.string(),
    })),
    audit_scope: z.string(),
    replay_ready: z.boolean(),
  })),
  runtime_notes: stringArraySchema,
});

export function parseManufacturingWorkflowConsole(value: unknown): ManufacturingWorkflowConsole {
  return parseContract(workflowConsole, value);
}
