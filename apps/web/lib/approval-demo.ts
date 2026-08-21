import type { ManufacturingProvenance, PlatformStatus } from "./platform-overview";
import type { PlatformPolicyDecision } from "./platform-policies";

export type ApprovalDecision = "approve" | "reject" | "request_changes";

export type ApprovalDecisionOption = {
  decision: ApprovalDecision;
  label: string;
  consequence: string;
};

export type ApprovalAuditPreview = {
  event: string;
  actor_role: string;
  scope: string;
  result: string;
};

export type ApprovalInboxItem = {
  approval_id: string;
  action_run_id?: string | null;
  action: string;
  risk_level: "high" | "medium" | "low";
  status: string;
  requested_by: string;
  owner_role: string;
  due: string;
  workflow_id: string;
  domain: string;
  summary: string;
  evidence: string[];
  data_accessed: string[];
  risks: string[];
  alternatives: string[];
  estimated_cost: string;
  model_policy: string;
  required_permission: string;
  audit_event_preview: ApprovalAuditPreview;
  decision_options: ApprovalDecisionOption[];
};

export type ManufacturingApprovalInbox = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  as_of: string;
  queue_status: PlatformStatus;
  policy_notes: string[];
  approvals: ApprovalInboxItem[];
};

export type ApprovalDecisionPersistenceResult = {
  tenant_id: string;
  approval_id: string;
  workflow_id: string;
  action_id: string;
  decision: ApprovalDecision;
  status: string;
  actor_id: string;
  audit_event_id: string;
  audit_event_type: string;
  persisted: boolean;
  idempotent_replay: boolean;
  permission_decision: {
    allowed: boolean;
    reason: string;
  };
  workflow_signal: {
    workflow_id: string;
    status: string;
    adapter: string;
    signal_name: string;
    payload: Record<string, unknown> & {
      approval_id?: string;
      approved?: boolean;
      decision?: ApprovalDecision;
      reason?: string;
    };
  };
  workflow_signal_status: string;
  /** Additive workflow/action evidence returned by the enterprise API. */
  workflow_state_updated?: boolean;
  workflow_state?: string | null;
  workflow_status?: string | null;
  action_run_recorded?: boolean;
  action_run_id?: string | null;
  action_run_status?: string | null;
  action_run_idempotency_key?: string | null;
  action_run_idempotent_replay?: boolean;
  platform_policy_decision?: PlatformPolicyDecision | null;
  decision_event_id?: string | null;
};

export type ApprovalDecisionRequestPayload = {
  decision: ApprovalDecision;
  actor_id: string;
  actor_scopes: string[];
  note?: string;
};

export function approvalRiskClass(riskLevel: ApprovalInboxItem["risk_level"]): string {
  if (riskLevel === "high") {
    return "signal-action-required";
  }

  return riskLevel === "medium" ? "signal-watch" : "signal-ready";
}

export function approvalDecisionLabel(decision: ApprovalDecision): string {
  if (decision === "request_changes") {
    return "Changes Requested";
  }

  return decision === "approve" ? "Approved" : "Rejected";
}

export function approvalDecisionActorId(approval: ApprovalInboxItem): string {
  return `${approval.owner_role}-role`;
}

export function approvalDecisionActorScopes(approval: ApprovalInboxItem): string[] {
  return [approval.required_permission];
}

export function buildApprovalDecisionPayload(
  approval: ApprovalInboxItem,
  decision: ApprovalDecision,
  note?: string,
  actor?: { actorId: string; scopes: string[] },
): ApprovalDecisionRequestPayload {
  const trimmedNote = note?.trim();

  return {
    decision,
    actor_id: actor?.actorId ?? approvalDecisionActorId(approval),
    actor_scopes: actor?.scopes ?? approvalDecisionActorScopes(approval),
    // The API caps notes at 600 characters; the console textarea enforces it.
    note: trimmedNote || `Console decision recorded for ${approval.approval_id}.`,
  };
}

export function findApprovalById(
  inbox: ManufacturingApprovalInbox,
  approvalId: string,
): ApprovalInboxItem {
  return (
    inbox.approvals.find((approval) => approval.approval_id === approvalId) ?? inbox.approvals[0]
  );
}

export function buildApprovalHref(approvalId: string | null | undefined): string {
  if (!approvalId) {
    return "/approvals";
  }

  const params = new URLSearchParams({ approval_id: approvalId });
  return `/approvals?${params.toString()}`;
}
