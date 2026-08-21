import { describe, expect, it } from "vitest";

import {
  formatOverviewTimestamp,
  getDemoReadinessCounts,
  getDemoReadinessPriorityStatus,
  getOperationsSnapshotStatus,
  getPersistedArtifactCount,
  platformStatusClass,
  platformStatusLabel,
  sortDomainSnapshotsByOperationalPriority,
  type ManufacturingDemoReadinessReport,
  type ManufacturingOperationsSnapshot,
} from "./platform-overview";

describe("platform overview helpers", () => {
  it("formats platform status labels and classes", () => {
    expect(platformStatusLabel("action_required")).toBe("Action Required");
    expect(platformStatusClass("action_required")).toBe("signal-action-required");
    expect(platformStatusClass("ready")).toBe("signal-ready");
    expect(platformStatusLabel("watch")).toBe("Watch");
  });

  it("formats API timestamps for display", () => {
    expect(formatOverviewTimestamp("2026-06-22T09:00:00+02:00")).toContain("2026");
  });

  it("summarizes the persisted operations snapshot for the overview console", () => {
    const snapshot: ManufacturingOperationsSnapshot = {
      tenant_id: "tenant_demo_manufacturing",
      plant_name: "Ravenna Works",
      scenario: "daily-operations-demo",
      provenance: "live",
      as_of: "2026-06-22T09:00:00+02:00",
      metrics: [],
      domain_snapshots: [
        {
          domain: "Maintenance",
          record_count: 2,
          action_required_count: 0,
          watch_count: 2,
          highest_risk_level: "medium",
          owner_roles: ["maintenance-owner"],
          workflow_ids: ["wf_maintenance_window"],
          evidence_refs: ["cmms:machine:line-2"],
        },
        {
          domain: "Supply",
          record_count: 1,
          action_required_count: 1,
          watch_count: 0,
          highest_risk_level: "high",
          owner_roles: ["supply-planning-owner"],
          workflow_ids: ["wf_supplier_delay_review"],
          evidence_refs: ["supplier_portal:shipment:motors-7741"],
        },
      ],
      latest_daily_briefs: [
        {
          brief_id: "brief_20260622_demo",
          brief_date: "2026-06-22",
          status: "generated",
          requested_by: "agent_daily_brief",
          source_record_count: 5,
          generation_boundary: "deterministic_persisted_records",
          audit_event_type: "manufacturing.daily_brief.generated",
        },
      ],
      risk_scenarios: [
        {
          scenario_id: "supplier_delay_demo",
          domain: "Supply",
          status: "generated",
          risk_level: "high",
          owner_role: "supply-planning-owner",
          workflow_ids: ["wf_supplier_delay_review"],
          source_record_count: 1,
          generation_boundary: "deterministic_persisted_supply_records",
          audit_event_type: "manufacturing.risk_scenario.generated",
        },
      ],
      active_workflows: [
        {
          workflow_id: "wf_supplier_delay_review",
          name: "Supplier delay review",
          domain: "Supply",
          state: "awaiting_approval",
          status: "action_required",
          owner_role: "supply-planning-owner",
          autonomy_level: "L2",
          blocker: "Owner approval required before expedite.",
          pending_signal_count: 1,
          replay_ready: true,
        },
      ],
      pending_approvals: [
        {
          approval_id: "appr_supplier_expedite",
          workflow_id: "wf_supplier_delay_review",
          action_id: "request_supplier_expedite",
          status: "pending",
          owner_role: "supply-planning-owner",
          risk_level: "high",
          requested_by: "agent_supplier_delay",
        },
      ],
      recent_audit_events: [
        {
          event_type: "manufacturing.risk_scenario.generated",
          actor_id: "agent_supplier_delay",
          created_at: "2026-06-22T09:01:00+02:00",
          payload_refs: { scenario_id: "supplier_delay_demo" },
        },
      ],
      generation_boundary: "persisted_operations_snapshot",
      notes: ["Composed from persisted tenant-scoped records."],
    };

    expect(getPersistedArtifactCount(snapshot)).toBe(2);
    expect(getOperationsSnapshotStatus(snapshot)).toBe("action_required");
    expect(sortDomainSnapshotsByOperationalPriority(snapshot.domain_snapshots).map((item) => item.domain)).toEqual([
      "Supply",
      "Maintenance",
    ]);
  });

  it("summarizes demo readiness checks for the overview console", () => {
    const report: ManufacturingDemoReadinessReport = {
      tenant_id: "tenant_demo_manufacturing",
      plant_name: "Ravenna Works",
      scenario: "Plant Operations Cockpit",
      as_of: "2026-06-22T09:00:00+02:00",
      readiness_status: "watch",
      summary:
        "Axis is ready for structured SME feedback and enterprise evaluation walkthroughs, with production-readiness limits made explicit.",
      tracks: [
        {
          name: "SME feedback demo",
          status: "ready",
          detail: "Core operations demo evidence is present.",
        },
        {
          name: "Enterprise evaluation walkthrough",
          status: "watch",
          detail: "Architecture evaluation is available, production limits remain explicit.",
        },
      ],
      checks: [
        {
          check_id: "operations_snapshot",
          label: "Persisted operations snapshot",
          status: "ready",
          observed_count: 2,
          detail: "2 operation records across 2 domains.",
          evidence_refs: ["erp:orders:PO-4812"],
        },
        {
          check_id: "production_readiness_limits",
          label: "Production readiness limits",
          status: "watch",
          observed_count: 4,
          detail: "Enterprise production hardening remains open.",
          evidence_refs: [],
        },
      ],
      limitations: ["Not a production readiness claim."],
      next_actions: ["Run the walkthrough with a design partner."],
      generation_boundary: "derived_from_persisted_demo_evidence",
      notes: ["No browser-local mock data is used."],
    };

    expect(getDemoReadinessCounts(report)).toEqual({
      action_required: 0,
      ready: 1,
      watch: 1,
    });
    expect(getDemoReadinessPriorityStatus(report)).toBe("watch");
  });
});
