export type PlatformStatus = "ready" | "watch" | "action_required";
export type ManufacturingProvenance = "reference_scenario" | "live" | "empty";

export type OverviewMetric = {
  label: string;
  value: string;
  detail: string;
  status: PlatformStatus;
};

export type RiskSignal = {
  title: string;
  domain: string;
  severity: PlatformStatus;
  owner_role: string;
  evidence: string;
  related_asset: string;
};

export type WorkflowSummary = {
  workflow_id: string;
  name: string;
  state: string;
  owner_role: string;
  blocker: string | null;
  eta: string;
};

export type ApprovalSummary = {
  approval_id: string;
  action: string;
  risk_level: string;
  requested_by: string;
  owner_role: string;
  due: string;
};

export type AgentSummary = {
  agent_id: string;
  name: string;
  autonomy_level: "L0" | "L1" | "L2" | "L3" | "L4";
  status: string;
  proposals_pending: number;
  model_policy: string;
};

export type AuditEvidence = {
  event: string;
  actor: string;
  scope: string;
  result: string;
};

export type ManufacturingOverview = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  as_of: string;
  metrics: OverviewMetric[];
  risk_signals: RiskSignal[];
  workflows: WorkflowSummary[];
  approvals: ApprovalSummary[];
  agents: AgentSummary[];
  audit_events: AuditEvidence[];
};

export type ManufacturingDomainSnapshot = {
  domain: string;
  record_count: number;
  action_required_count: number;
  watch_count: number;
  highest_risk_level: string;
  owner_roles: string[];
  workflow_ids: string[];
  evidence_refs: string[];
};

export type ManufacturingBriefSummary = {
  brief_id: string;
  brief_date: string;
  status: string;
  requested_by: string;
  source_record_count: number;
  generation_boundary: string;
  audit_event_type: string;
};

export type ManufacturingRiskScenarioSummary = {
  scenario_id: string;
  domain: string;
  status: string;
  risk_level: string;
  owner_role: string;
  workflow_ids: string[];
  source_record_count: number;
  generation_boundary: string;
  audit_event_type: string;
};

export type ManufacturingWorkflowSnapshot = {
  workflow_id: string;
  name: string;
  domain: string;
  state: string;
  status: string;
  owner_role: string;
  autonomy_level: string;
  blocker: string | null;
  pending_signal_count: number;
  replay_ready: boolean;
};

export type ManufacturingApprovalSnapshot = {
  approval_id: string;
  workflow_id: string | null;
  action_id: string;
  status: string;
  owner_role: string;
  risk_level: string;
  requested_by: string;
};

export type ManufacturingAuditEventSummary = {
  event_type: string;
  actor_id: string;
  created_at: string;
  payload_refs: Record<string, string | string[]>;
};

export type ManufacturingOperationsSnapshot = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  as_of: string;
  metrics: OverviewMetric[];
  domain_snapshots: ManufacturingDomainSnapshot[];
  latest_daily_briefs: ManufacturingBriefSummary[];
  risk_scenarios: ManufacturingRiskScenarioSummary[];
  active_workflows: ManufacturingWorkflowSnapshot[];
  pending_approvals: ManufacturingApprovalSnapshot[];
  recent_audit_events: ManufacturingAuditEventSummary[];
  generation_boundary: string;
  notes: string[];
};

export type ManufacturingDemoReadinessTrack = {
  name: string;
  status: PlatformStatus;
  detail: string;
};

export type ManufacturingDemoReadinessCheck = {
  check_id: string;
  label: string;
  status: PlatformStatus;
  observed_count: number;
  detail: string;
  evidence_refs: string[];
};

export type ManufacturingDemoReadinessReport = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  as_of: string;
  readiness_status: PlatformStatus;
  summary: string;
  tracks: ManufacturingDemoReadinessTrack[];
  checks: ManufacturingDemoReadinessCheck[];
  limitations: string[];
  next_actions: string[];
  generation_boundary: string;
  notes: string[];
};

export type ManufacturingPlatformNotification = {
  notification_id: string;
  category: string;
  severity: PlatformStatus;
  title: string;
  detail: string;
  source: string;
  route: string;
  occurred_at: string;
  owner_role: string | null;
  related_workflow_id: string | null;
  related_approval_id: string | null;
  evidence_refs: string[];
  action_label: string;
  read_state: string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  acknowledgement_reason: string | null;
};

export type ManufacturingNotificationCenter = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  as_of: string;
  unread_count: number;
  action_required_count: number;
  watch_count: number;
  notifications: ManufacturingPlatformNotification[];
  generation_boundary: string;
  notes: string[];
};

export type ManufacturingNotificationAcknowledgementResult = {
  tenant_id: string;
  notification_id: string;
  actor_id: string;
  state: string;
  reason: string;
  audit_event_id: string | null;
  audit_event_type: string;
  read_state: string;
  acknowledged_at: string;
  generation_boundary: string;
};

export type IdentitySessionReadModel = {
  authenticated: boolean;
  mode: string;
  actor_id: string | null;
  tenant_id: string | null;
  scopes: string[];
  expires_at: number | null;
  api_auth_required: boolean;
  enterprise_sso_ready: boolean;
  readiness_status: PlatformStatus;
  issuer: string;
  audience: string;
  jwks_source: string;
  session_boundary: string;
  capabilities: string[];
  limitations: string[];
  notes: string[];
  /** Why no API-verified actor is attached; null when authenticated or demo mode. */
  unauthenticated_reason: string | null;
};

export type DemoReadinessCounts = Record<PlatformStatus, number>;

export function platformStatusLabel(status: PlatformStatus): string {
  if (status === "action_required") {
    return "Action Required";
  }

  return status === "watch" ? "Watch" : "Ready";
}

export function platformStatusClass(status: PlatformStatus): string {
  return `signal-${status.replace("_", "-")}`;
}

export function formatOverviewTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function getPersistedArtifactCount(snapshot: ManufacturingOperationsSnapshot): number {
  return snapshot.latest_daily_briefs.length + snapshot.risk_scenarios.length;
}

export function getOperationsSnapshotStatus(
  snapshot: ManufacturingOperationsSnapshot,
): PlatformStatus {
  const hasActionRequired =
    snapshot.pending_approvals.length > 0 ||
    snapshot.domain_snapshots.some((domain) => domain.action_required_count > 0) ||
    snapshot.active_workflows.some((workflow) => workflow.status === "action_required");

  if (hasActionRequired) {
    return "action_required";
  }

  const hasWatch =
    snapshot.domain_snapshots.some((domain) => domain.watch_count > 0) ||
    snapshot.risk_scenarios.some((scenario) => scenario.risk_level !== "low");

  return hasWatch ? "watch" : "ready";
}

export function sortDomainSnapshotsByOperationalPriority(
  domains: ManufacturingDomainSnapshot[],
): ManufacturingDomainSnapshot[] {
  return [...domains].sort((left, right) => {
    const actionDelta = right.action_required_count - left.action_required_count;
    if (actionDelta !== 0) {
      return actionDelta;
    }

    const watchDelta = right.watch_count - left.watch_count;
    if (watchDelta !== 0) {
      return watchDelta;
    }

    return left.domain.localeCompare(right.domain);
  });
}

export function getDemoReadinessCounts(
  report: ManufacturingDemoReadinessReport,
): DemoReadinessCounts {
  return report.checks.reduce<DemoReadinessCounts>(
    (counts, check) => ({
      ...counts,
      [check.status]: counts[check.status] + 1,
    }),
    {
      action_required: 0,
      ready: 0,
      watch: 0,
    },
  );
}

export function getDemoReadinessPriorityStatus(
  report: ManufacturingDemoReadinessReport,
): PlatformStatus {
  if (report.readiness_status === "action_required") {
    return "action_required";
  }

  const counts = getDemoReadinessCounts(report);
  if (counts.action_required > 0) {
    return "action_required";
  }

  return report.readiness_status === "watch" || counts.watch > 0 ? "watch" : "ready";
}
