import { z } from "zod";

import type { TenantUsageSummary } from "../platform-tenant-usage";
import type {
  TenantQuotaSet,
  TenantRecord,
  TenantRegistry,
  TenantVocabularySet,
} from "../platform-tenants";
import {
  nullableStringSchema,
  parseContract,
  permissionDecisionSchema,
  stringArraySchema,
} from "./shared";

const tenantRecord = z.object({
  tenant_id: z.string(),
  display_name: z.string(),
  description: z.string(),
  status: z.enum(["active", "suspended", "pending_deletion"]),
  created_by: z.string(),
  bootstrap_admin_actor_id: nullableStringSchema.optional(),
  provision_idempotency_key: nullableStringSchema.optional(),
  suspended_at: nullableStringSchema.optional(),
  suspended_by: nullableStringSchema.optional(),
  suspension_reason: nullableStringSchema.optional(),
  reactivated_at: nullableStringSchema.optional(),
  reactivated_by: nullableStringSchema.optional(),
  permission_decision: permissionDecisionSchema.nullable().optional(),
  audit_event_id: nullableStringSchema.optional(),
  audit_event_type: z.string(),
  idempotent_replay: z.boolean().optional(),
  notes: stringArraySchema.optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
const tenantRegistry = z.object({
  tenant_count: z.number(),
  active_tenant_count: z.number(),
  tenants: z.array(tenantRecord).optional(),
  has_more: z.boolean().optional(),
  next_cursor: nullableStringSchema.optional(),
  tenant_notes: stringArraySchema.optional(),
});
const tenantQuotaSet = z.object({
  tenant_id: z.string(),
  quotas: z.record(z.string(), z.number()).optional(),
  changes: z.array(z.object({
    quota_key: z.string(),
    previous_value: z.number().nullable().optional(),
    new_value: z.number().nullable().optional(),
    audit_event_id: nullableStringSchema.optional(),
    audit_event_type: z.string(),
  })).optional(),
  quota_notes: stringArraySchema.optional(),
});
const tenantVocabulary = z.object({
  site_singular: z.string(),
  site_plural: z.string(),
  workspace_label: z.string(),
  domain_labels: z.record(z.string(), z.string()),
});
const tenantVocabularySet = z.object({
  tenant_id: z.string(),
  vocabulary: tenantVocabulary,
  configured: z.boolean(),
  changes: z.array(z.object({
    previous_value: tenantVocabulary.nullable().optional(),
    new_value: tenantVocabulary,
    audit_event_id: nullableStringSchema.optional(),
    audit_event_type: z.string(),
  })).optional(),
  vocabulary_notes: stringArraySchema.optional(),
});
const tenantUsageSummary = z.object({
  tenant_id: z.string(),
  window_start: z.string(),
  window_end: z.string(),
  period_window_seconds: z.number(),
  metric_totals: z.array(z.object({ metric_key: z.string(),
    quantity: z.number() })).optional(),
  periods: z.array(z.object({
    period_start: z.string(),
    metric_key: z.string(),
    quantity: z.number(),
  })).optional(),
  usage_notes: stringArraySchema.optional(),
});

export function parseTenantRecord(value: unknown): TenantRecord {
  return parseContract(tenantRecord, value);
}

export function parseTenantRegistry(value: unknown): TenantRegistry {
  return parseContract(tenantRegistry, value);
}

export function parseTenantQuotaSet(value: unknown): TenantQuotaSet {
  return parseContract(tenantQuotaSet, value);
}
export function parseTenantVocabularySet(value: unknown): TenantVocabularySet {
  return parseContract(tenantVocabularySet, value);
}
export function parseTenantUsageSummary(value: unknown): TenantUsageSummary {
  return parseContract(tenantUsageSummary, value);
}
