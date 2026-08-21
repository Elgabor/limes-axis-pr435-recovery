import { z } from "zod";

import type { ManufacturingModelRouting } from "../model-routing-demo";
import {
  manufacturingProvenanceSchema,
  nullableStringSchema,
  overviewMetricSchema,
  parseContract,
  platformStatusSchema,
  stringArraySchema,
} from "./shared";

const modelRouting = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  as_of: z.string(),
  routing_status: platformStatusSchema,
  metrics: z.array(overviewMetricSchema),
  filter_options: z.object({
    domains: stringArraySchema,
    providers: stringArraySchema,
    model_policies: stringArraySchema,
    egress_decisions: stringArraySchema,
    statuses: z.array(platformStatusSchema),
  }),
  provider_options: z.array(z.object({
    provider_id: z.string(),
    display_name: z.string(),
    provider_type: z.string(),
    hosting_boundary: z.string(),
    status: z.string(),
    egress_mode: z.string(),
    cost_basis: z.string(),
    allowed_policies: stringArraySchema,
    notes: stringArraySchema,
  })),
  routes: z.array(z.object({
    route_id: z.string(),
    agent_id: z.string(),
    agent_name: z.string(),
    domain: z.string(),
    provider_id: z.string(),
    provider_name: z.string(),
    model: z.string(),
    model_policy: z.string(),
    prompt_classification: z.string(),
    data_boundary: z.string(),
    external_egress_requested: z.boolean(),
    external_egress_allowed: z.boolean(),
    egress_decision: z.string(),
    decision_reason: z.string(),
    route_status: platformStatusSchema,
    input_tokens: z.number(),
    output_tokens: z.number(),
    estimated_cost_eur: z.number(),
    latency_ms: z.number(),
    cost_center: z.string(),
    required_permissions: stringArraySchema,
    evidence_refs: stringArraySchema,
    audit_event_id: z.string(),
    observability_events: stringArraySchema,
  })),
  budget_notes: stringArraySchema,
  observability_notes: stringArraySchema,
});

export function parseManufacturingModelRouting(value: unknown): ManufacturingModelRouting {
  return parseContract(modelRouting, value);
}
