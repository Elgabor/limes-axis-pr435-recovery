import { z } from "zod";

import type { OperationsArtifactResponse } from "../operations-artifacts";
import type {
  IdentitySessionReadModel,
  ManufacturingNotificationAcknowledgementResult,
  ManufacturingNotificationCenter,
  ManufacturingOperationsSnapshot,
  ManufacturingOverview,
} from "../platform-overview";
import {
  manufacturingProvenanceSchema,
  nullableStringSchema,
  overviewMetricSchema,
  parseContract,
  platformStatusSchema,
  stringArraySchema,
} from "./shared";

const manufacturingOverview = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  as_of: z.string(),
  metrics: z.array(overviewMetricSchema),
  risk_signals: z.array(z.object({
    title: z.string(),
    domain: z.string(),
    severity: platformStatusSchema,
    owner_role: z.string(),
    evidence: z.string(),
    related_asset: z.string(),
  })),
  workflows: z.array(z.object({
    workflow_id: z.string(),
    name: z.string(),
    state: z.string(),
    owner_role: z.string(),
    blocker: nullableStringSchema,
    eta: z.string(),
  })),
  approvals: z.array(z.object({
    approval_id: z.string(),
    action: z.string(),
    risk_level: z.string(),
    requested_by: z.string(),
    owner_role: z.string(),
    due: z.string(),
  })),
  agents: z.array(z.object({
    agent_id: z.string(),
    name: z.string(),
    autonomy_level: z.enum(["L0", "L1", "L2", "L3", "L4"]),
    status: z.string(),
    proposals_pending: z.number(),
    model_policy: z.string(),
  })),
  audit_events: z.array(z.object({
    event: z.string(),
    actor: z.string(),
    scope: z.string(),
    result: z.string(),
  })),
});

const operationsSnapshot = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  as_of: z.string(),
  metrics: z.array(overviewMetricSchema),
  domain_snapshots: z.array(z.object({
    domain: z.string(),
    record_count: z.number(),
    action_required_count: z.number(),
    watch_count: z.number(),
    highest_risk_level: z.string(),
    owner_roles: stringArraySchema,
    workflow_ids: stringArraySchema,
    evidence_refs: stringArraySchema,
  })),
  latest_daily_briefs: z.array(z.object({
    brief_id: z.string(),
    brief_date: z.string(),
    status: z.string(),
    requested_by: z.string(),
    source_record_count: z.number(),
    generation_boundary: z.string(),
    audit_event_type: z.string(),
  })),
  risk_scenarios: z.array(z.object({
    scenario_id: z.string(),
    domain: z.string(),
    status: z.string(),
    risk_level: z.string(),
    owner_role: z.string(),
    workflow_ids: stringArraySchema,
    source_record_count: z.number(),
    generation_boundary: z.string(),
    audit_event_type: z.string(),
  })),
  active_workflows: z.array(z.object({
    workflow_id: z.string(),
    name: z.string(),
    domain: z.string(),
    state: z.string(),
    status: z.string(),
    owner_role: z.string(),
    autonomy_level: z.string(),
    blocker: nullableStringSchema,
    pending_signal_count: z.number(),
    replay_ready: z.boolean(),
  })),
  pending_approvals: z.array(z.object({
    approval_id: z.string(),
    workflow_id: nullableStringSchema,
    action_id: z.string(),
    status: z.string(),
    owner_role: z.string(),
    risk_level: z.string(),
    requested_by: z.string(),
  })),
  recent_audit_events: z.array(z.object({
    event_type: z.string(),
    actor_id: z.string(),
    created_at: z.string(),
    payload_refs: z.record(z.string(), z.union([z.string(), stringArraySchema])),
  })),
  generation_boundary: z.string(),
  notes: stringArraySchema,
});

const notificationCenter = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  as_of: z.string(),
  unread_count: z.number(),
  action_required_count: z.number(),
  watch_count: z.number(),
  notifications: z.array(z.object({
    notification_id: z.string(),
    category: z.string(),
    severity: platformStatusSchema,
    title: z.string(),
    detail: z.string(),
    source: z.string(),
    route: z.string(),
    occurred_at: z.string(),
    owner_role: nullableStringSchema,
    related_workflow_id: nullableStringSchema,
    related_approval_id: nullableStringSchema,
    evidence_refs: stringArraySchema,
    action_label: z.string(),
    read_state: z.string(),
    acknowledged_by: nullableStringSchema,
    acknowledged_at: nullableStringSchema,
    acknowledgement_reason: nullableStringSchema,
  })),
  generation_boundary: z.string(),
  notes: stringArraySchema,
});

const identitySession = z.object({
  authenticated: z.boolean(),
  mode: z.string(),
  actor_id: nullableStringSchema,
  tenant_id: nullableStringSchema,
  scopes: stringArraySchema,
  expires_at: z.number().nullable(),
  api_auth_required: z.boolean(),
  enterprise_sso_ready: z.boolean(),
  readiness_status: platformStatusSchema,
  issuer: z.string(),
  audience: z.string(),
  jwks_source: z.string(),
  session_boundary: z.string(),
  capabilities: stringArraySchema,
  limitations: stringArraySchema,
  notes: stringArraySchema,
  unauthenticated_reason: nullableStringSchema,
});

const operationsArtifactResponse = z.object({
  tenant_id: z.string(),
  status: z.string(),
  requested_by: z.string(),
  audit_event_id: nullableStringSchema,
  audit_event_type: z.string(),
  idempotent_replay: z.boolean(),
  source_record_ids: stringArraySchema,
  brief_id: z.string().optional(),
  brief_date: z.string().optional(),
  summary_payload: z.object({ headline: z.string().optional() }).optional(),
  scenario_id: z.string().optional(),
  domain: z.string().optional(),
  risk_level: z.string().optional(),
  owner_role: z.string().optional(),
  workflow_ids: stringArraySchema.optional(),
  scenario_payload: z.object({ headline: z.string().optional() }).optional(),
});

const notificationAcknowledgementResult = z.object({
  tenant_id: z.string(),
  notification_id: z.string(),
  actor_id: z.string(),
  state: z.string(),
  reason: z.string(),
  audit_event_id: nullableStringSchema,
  audit_event_type: z.string(),
  read_state: z.string(),
  acknowledged_at: z.string(),
  generation_boundary: z.string(),
});

export function parseManufacturingOverview(value: unknown): ManufacturingOverview {
  return parseContract(manufacturingOverview, value);
}

export function parseManufacturingOperationsSnapshot(
  value: unknown,
): ManufacturingOperationsSnapshot {
  return parseContract(operationsSnapshot, value);
}

export function parseManufacturingNotificationCenter(
  value: unknown,
): ManufacturingNotificationCenter {
  return parseContract(notificationCenter, value);
}

export function parseIdentitySessionReadModel(value: unknown): IdentitySessionReadModel {
  return parseContract(identitySession, value);
}

export function parseOperationsArtifactResponse(value: unknown): OperationsArtifactResponse {
  return parseContract(operationsArtifactResponse, value);
}

export function parseManufacturingNotificationAcknowledgementResult(
  value: unknown,
): ManufacturingNotificationAcknowledgementResult {
  return parseContract(notificationAcknowledgementResult, value);
}
