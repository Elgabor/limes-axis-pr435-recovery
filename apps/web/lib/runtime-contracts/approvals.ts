import { z } from "zod";

import type {
  ApprovalDecisionPersistenceResult,
  ManufacturingApprovalInbox,
} from "../approval-demo";
import {
  manufacturingProvenanceSchema,
  nullableStringSchema,
  parseContract,
  platformStatusSchema,
  stringArraySchema,
} from "./shared";

const approvalDecision = z.enum(["approve", "reject", "request_changes"]);
const approvalDecisionHistoryEntry = z.object({
  approval_id: z.string(),
  action: z.string(),
  risk_level: z.string(),
  status: z.string(),
  decision: z.string(),
  domain: nullableStringSchema,
  workflow_id: nullableStringSchema,
  decided_by: nullableStringSchema,
  decided_at: nullableStringSchema,
  rationale: nullableStringSchema,
  audit_event_id: nullableStringSchema,
  follow_through_status: nullableStringSchema,
});
const approvalInbox = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  as_of: z.string(),
  queue_status: platformStatusSchema,
  policy_notes: stringArraySchema,
  // Older deployments predate the history projection; default keeps one type.
  decision_history: z.array(approvalDecisionHistoryEntry).default([]),
  approvals: z.array(z.object({
    approval_id: z.string(),
    action_run_id: z.string().nullable().optional(),
    action: z.string(),
    risk_level: z.enum(["high", "medium", "low"]),
    status: z.string(),
    requested_by: z.string(),
    owner_role: z.string(),
    due: z.string(),
    workflow_id: z.string(),
    domain: z.string(),
    summary: z.string(),
    evidence: stringArraySchema,
    data_accessed: stringArraySchema,
    risks: stringArraySchema,
    alternatives: stringArraySchema,
    estimated_cost: z.string(),
    model_policy: z.string(),
    required_permission: z.string(),
    audit_event_preview: z.object({
      event: z.string(),
      actor_role: z.string(),
      scope: z.string(),
      result: z.string(),
    }),
    decision_options: z.array(z.object({
      decision: approvalDecision,
      label: z.string(),
      consequence: z.string(),
    })),
  })),
});

const approvalDecisionResult = z.object({
  tenant_id: z.string(),
  approval_id: z.string(),
  workflow_id: z.string(),
  action_id: z.string(),
  decision: approvalDecision,
  status: z.string(),
  actor_id: z.string(),
  audit_event_id: z.string(),
  audit_event_type: z.string(),
  persisted: z.boolean(),
  idempotent_replay: z.boolean(),
  permission_decision: z.object({ allowed: z.boolean(),
    reason: z.string() }),
  workflow_signal: z.object({
    workflow_id: z.string(),
    status: z.string(),
    adapter: z.string(),
    signal_name: z.string(),
    payload: z.object({
      approval_id: z.string().optional(),
      approved: z.boolean().optional(),
      decision: approvalDecision.optional(),
      reason: z.string().optional(),
    }),
  }),
  workflow_signal_status: z.string(),
  decision_event_id: z.string().uuid().nullable().optional(),
});

export function parseManufacturingApprovalInbox(value: unknown): ManufacturingApprovalInbox {
  return parseContract(approvalInbox, value);
}

export function parseApprovalDecisionPersistenceResult(
  value: unknown,
): ApprovalDecisionPersistenceResult {
  return parseContract(approvalDecisionResult, value);
}
