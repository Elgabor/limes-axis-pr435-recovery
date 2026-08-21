import { z } from "zod";

import type { AuditExportBundle, ManufacturingAuditExplorer } from "../audit-demo";
import { auditEventSchema } from "./audit-event";
import {
  manufacturingProvenanceSchema,
  nullableStringSchema,
  overviewMetricSchema,
  parseContract,
  platformStatusSchema,
  stringArraySchema,
} from "./shared";
const auditExplorer = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  as_of: z.string(),
  ledger_status: platformStatusSchema,
  metrics: z.array(overviewMetricSchema),
  filter_options: z.object({
    tenants: stringArraySchema,
    event_types: stringArraySchema,
    scopes: stringArraySchema,
    actors: stringArraySchema,
    categories: stringArraySchema,
  }),
  events: z.array(auditEventSchema),
  retention_notes: stringArraySchema,
});
const auditExportBundle = z.object({
  tenant_id: z.string(),
  scenario: nullableStringSchema,
  format: z.string(),
  export_reason: z.string(),
  filters: z.object({
    tenant_id: z.string(),
    event_type: nullableStringSchema,
    actor_id: nullableStringSchema,
    scope: nullableStringSchema,
    limit: z.number(),
  }),
  retention_policy: z.object({
    policy_id: z.string(),
    retention_days: z.number(),
    retention_basis: z.string(),
    disposal_action: z.string(),
    legal_hold: z.boolean(),
    export_requires_review: z.boolean(),
    notes: stringArraySchema,
  }),
  manifest: z.object({
    export_id: z.string(),
    generated_at: z.string(),
    tenant_id: z.string(),
    record_count: z.number(),
    format: z.string(),
    redaction_policy: z.string(),
    retention_policy_id: z.string(),
    checksum_sha256: z.string(),
    integrity_chain_tip_sha256: z.string(),
    retention_enforced: z.boolean(),
    retention_window_start: z.string(),
    excluded_record_count: z.number(),
  }),
  integrity_proof: z.object({
    algorithm: z.string(),
    verification_status: z.string(),
    record_count: z.number(),
    chain_tip_sha256: z.string(),
    event_hashes: stringArraySchema,
  }),
  ledger_signature: z.object({
    algorithm: z.string(),
    key_id: nullableStringSchema,
    signing_mode: z.string(),
    verification_status: z.string(),
    signed_payload_sha256: z.string(),
    signature: nullableStringSchema,
    notes: stringArraySchema,
  }),
  events: z.array(auditEventSchema),
  retention_notes: stringArraySchema,
});

export function parseManufacturingAuditExplorer(value: unknown): ManufacturingAuditExplorer {
  return parseContract(auditExplorer, value);
}

export function parseAuditExportBundle(value: unknown): AuditExportBundle {
  return parseContract(auditExportBundle, value);
}
