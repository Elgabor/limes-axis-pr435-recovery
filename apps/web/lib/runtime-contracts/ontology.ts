import { z } from "zod";

import type { ManufacturingOntology, ManufacturingOntologyEntityDetail } from "../ontology-demo";
import {
  manufacturingProvenanceSchema,
  nullableStringSchema,
  parseContract,
  platformStatusSchema,
  stringArraySchema,
} from "./shared";

const ontologyNode = z.object({
  node_id: z.string(),
  label: z.string(),
  node_type: z.enum([
    "organization", "asset", "process", "workflow", "risk", "approval", "agent",
    "system", "policy", "audit_event",
  ]),
  domain: z.string(),
  status: platformStatusSchema,
  source_system: z.string(),
  summary: z.string(),
});
const ontologyRelationship = z.object({
  relationship_id: z.string(),
  source_id: z.string(),
  target_id: z.string(),
  relation_type: z.string(),
  summary: z.string(),
  permission_scope: z.string(),
  metadata: z.object({
    owner_role: z.string(),
    source_adapter: z.string(),
    confidence: z.number(),
    evidence_refs: stringArraySchema,
    valid_from: z.string(),
    valid_to: nullableStringSchema,
    last_verified_at: z.string(),
    verification_status: z.string(),
  }),
});
const ontology = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  as_of: z.string(),
  nodes: z.array(ontologyNode),
  relationships: z.array(ontologyRelationship),
  source_systems: stringArraySchema,
  permission_notes: stringArraySchema,
  graph_query: z.object({
    adapter: z.string(),
    source: z.string(),
    query_mode: z.string(),
    tenant_id: z.string(),
    actor_id: z.string(),
    permission_decision: z.object({ allowed: z.boolean(),
      reason: z.string() }),
    requested_scopes: stringArraySchema,
    applied_relationship_scopes: stringArraySchema,
    denied_relationship_count: z.number(),
    returned_node_count: z.number(),
    returned_relationship_count: z.number(),
    typeql: nullableStringSchema,
    notes: stringArraySchema,
  }),
});

const ontologyEntityDetail = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  as_of: z.string(),
  node: ontologyNode,
  connected_relationships: z.array(z.object({
    direction: z.enum(["inbound", "outbound"]),
    relationship: ontologyRelationship,
    peer_node: ontologyNode,
  })),
  inbound_count: z.number(),
  outbound_count: z.number(),
  required_permissions: stringArraySchema,
  evidence_refs: stringArraySchema,
  data_access: stringArraySchema,
  governed_by: stringArraySchema,
  related_workflows: stringArraySchema,
  related_approvals: stringArraySchema,
  related_agents: stringArraySchema,
  detail_notes: stringArraySchema,
});

export function parseManufacturingOntology(value: unknown): ManufacturingOntology {
  return parseContract(ontology, value);
}

export function parseManufacturingOntologyEntityDetail(
  value: unknown,
): ManufacturingOntologyEntityDetail {
  return parseContract(ontologyEntityDetail, value);
}
