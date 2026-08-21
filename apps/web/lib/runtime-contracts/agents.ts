import { z } from "zod";

import type { ManufacturingAgentRegistry } from "../agent-demo";
import {
  autonomyLevelSchema,
  manufacturingProvenanceSchema,
  nullableStringSchema,
  overviewMetricSchema,
  parseContract,
  platformStatusSchema,
  stringArraySchema,
} from "./shared";

const agentRegistry = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  as_of: z.string(),
  registry_status: platformStatusSchema,
  metrics: z.array(overviewMetricSchema),
  filter_options: z.object({
    domains: stringArraySchema,
    autonomy_levels: stringArraySchema,
    statuses: stringArraySchema,
    model_policies: stringArraySchema,
  }),
  agents: z.array(z.object({
    agent_id: z.string(),
    name: z.string(),
    domain: z.string(),
    status: z.string(),
    owner_role: z.string(),
    purpose: z.string(),
    policy_boundary: z.object({
      autonomy_level: autonomyLevelSchema,
      model_policy: z.string(),
      external_egress_allowed: z.boolean(),
      max_action_level: autonomyLevelSchema,
      required_permissions: stringArraySchema,
      guardrails: stringArraySchema,
    }),
    connected_systems: stringArraySchema,
    data_access: stringArraySchema,
    allowed_actions: stringArraySchema,
    blocked_actions: stringArraySchema,
    proposals: z.array(z.object({
      proposal_id: z.string(),
      action: z.string(),
      risk_level: z.enum(["high", "medium", "low"]),
      status: z.string(),
      approval_required: z.boolean(),
      related_workflow_id: nullableStringSchema,
      related_approval_id: nullableStringSchema,
    })),
    active_workflows: stringArraySchema,
    pending_approvals: stringArraySchema,
    last_audit_event: z.string(),
    evidence_refs: stringArraySchema,
  })),
  registry_notes: stringArraySchema,
});

export function parseManufacturingAgentRegistry(value: unknown): ManufacturingAgentRegistry {
  return parseContract(agentRegistry, value);
}
