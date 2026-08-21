import { describe, expect, it } from "vitest";

import {
  allAuditFilter,
  buildAuditEventHref,
  buildAuditExportFileName,
  buildAuditExportSummary,
  filterAuditEvents,
  findAuditEventById,
  formatAuditLabel,
  resolveAuditEventSelection,
  type AuditExportBundle,
  type ManufacturingAuditExplorer,
} from "./audit-demo";

const auditExplorerFixture: ManufacturingAuditExplorer = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Runtime contract fixture",
  provenance: "live",
  as_of: "2026-06-22T09:00:00+02:00",
  ledger_status: "ready",
  metrics: [],
  filter_options: {
    tenants: ["tenant_fixture"],
    event_types: ["agent.proposal.created", "policy.egress.blocked"],
    scopes: ["wf_supply_fixture", "model_route_fixture"],
    actors: ["agent_supply_fixture", "model-router"],
    categories: ["agent", "policy"],
  },
  events: [
    {
      audit_event_id: "audit_supply_fixture",
      occurred_at: "2026-06-22T09:01:00+02:00",
      tenant_id: "tenant_fixture",
      actor_id: "agent_supply_fixture",
      actor_type: "agent",
      event_type: "agent.proposal.created",
      category: "agent",
      domain: "Supply",
      scope: "wf_supply_fixture",
      result: "pending_owner_review",
      severity: "watch",
      source: "axis-agent-runtime",
      summary: "Agent proposed a governed supply action.",
      permission_scope: "approvals:supply:request",
      data_classification: "internal",
      related_workflow_id: "wf_supply_fixture",
      related_approval_id: "appr_supply_fixture",
      related_agent_id: "agent_supply_fixture",
      evidence_refs: ["risk_supply_fixture"],
      payload_preview: { action_id: "expedite_fixture_batch" },
    },
    {
      audit_event_id: "audit_egress_fixture",
      occurred_at: "2026-06-22T09:02:00+02:00",
      tenant_id: "tenant_fixture",
      actor_id: "model-router",
      actor_type: "service",
      event_type: "policy.egress.blocked",
      category: "policy",
      domain: "Quality",
      scope: "model_route_fixture",
      result: "blocked",
      severity: "action_required",
      source: "axis-model-router",
      summary: "External model egress was blocked by policy.",
      permission_scope: "models:route",
      data_classification: "restricted",
      related_workflow_id: null,
      related_approval_id: null,
      related_agent_id: null,
      evidence_refs: ["route_quality_fixture"],
      payload_preview: { provider: "external-general-llm" },
    },
  ],
  retention_notes: ["Fixture data is scoped to tests."],
};

describe("audit explorer helpers", () => {
  it("filters events by tenant, event type and scope", () => {
    const events = filterAuditEvents(auditExplorerFixture, {
      tenant: "tenant_fixture",
      eventType: "agent.proposal.created",
      scope: "wf_supply_fixture",
    });

    expect(events).toHaveLength(1);
    expect(events[0].actor_id).toBe("agent_supply_fixture");
  });

  it("keeps all events when filters are set to all", () => {
    expect(
      filterAuditEvents(auditExplorerFixture, {
        tenant: allAuditFilter,
        eventType: allAuditFilter,
        scope: allAuditFilter,
      }),
    ).toHaveLength(auditExplorerFixture.events.length);
  });

  it("finds audit events by id with a safe fallback", () => {
    expect(findAuditEventById(auditExplorerFixture, "audit_egress_fixture").event_type).toBe(
      "policy.egress.blocked",
    );
    expect(findAuditEventById(auditExplorerFixture, "missing").event_type).toBe(
      "agent.proposal.created",
    );
  });

  it("builds public-safe audit event deep links", () => {
    expect(buildAuditEventHref("audit_egress_fixture")).toBe("/audit?event_id=audit_egress_fixture");
    expect(buildAuditEventHref("audit event/id:fixture")).toBe(
      "/audit?event_id=audit+event%2Fid%3Afixture",
    );
    expect(buildAuditEventHref(null)).toBe("/audit");
  });

  it("resolves requested audit event selections before falling back to visible events", () => {
    const filteredEvents = filterAuditEvents(auditExplorerFixture, {
      tenant: allAuditFilter,
      eventType: allAuditFilter,
      scope: allAuditFilter,
    });

    expect(
      resolveAuditEventSelection({
        explorer: auditExplorerFixture,
        filteredEvents,
        requestedEventId: "audit_egress_fixture",
        selectedEventId: "",
      }),
    ).toBe("audit_egress_fixture");

    expect(
      resolveAuditEventSelection({
        explorer: auditExplorerFixture,
        filteredEvents: filteredEvents.slice(0, 1),
        requestedEventId: "missing",
        selectedEventId: "audit_egress_fixture",
      }),
    ).toBe("audit_supply_fixture");
  });

  it("formats audit labels", () => {
    expect(formatAuditLabel("policy.egress.blocked")).toBe("Policy Egress Blocked");
    expect(formatAuditLabel("approvals:supply:decide")).toBe("Approvals Supply Decide");
  });
});

const exportBundleFixture: AuditExportBundle = {
  tenant_id: "tenant_fixture",
  scenario: "Runtime contract fixture",
  format: "jsonl",
  export_reason: "console-review",
  filters: {
    tenant_id: "tenant_fixture",
    event_type: null,
    actor_id: null,
    scope: null,
    limit: 100,
  },
  retention_policy: {
    policy_id: "retention_fixture",
    retention_days: 365,
    retention_basis: "regulatory",
    disposal_action: "cryptographic_erasure",
    legal_hold: false,
    export_requires_review: true,
    notes: [],
  },
  manifest: {
    export_id: "export_fixture",
    generated_at: "2026-07-09T08:30:00+02:00",
    tenant_id: "tenant_fixture",
    record_count: 42,
    format: "jsonl",
    redaction_policy: "payload_preview_only",
    retention_policy_id: "retention_fixture",
    checksum_sha256: "a".repeat(64),
    integrity_chain_tip_sha256: "b".repeat(64),
    retention_enforced: true,
    retention_window_start: "2025-07-09T08:30:00+02:00",
    excluded_record_count: 3,
  },
  integrity_proof: {
    algorithm: "sha256-hash-chain-v1",
    verification_status: "verified",
    record_count: 42,
    chain_tip_sha256: "b".repeat(64),
    event_hashes: ["c".repeat(64)],
  },
  ledger_signature: {
    algorithm: "unsigned",
    key_id: null,
    signing_mode: "not_configured",
    verification_status: "unsigned",
    signed_payload_sha256: "d".repeat(64),
    signature: null,
    notes: [],
  },
  events: [],
  retention_notes: [],
};

describe("audit export summary", () => {
  it("maps a verified hash chain and enforced retention to ready tones", () => {
    const summary = buildAuditExportSummary(exportBundleFixture);
    const byId = Object.fromEntries(summary.map((line) => [line.id, line]));

    expect(summary).toHaveLength(3);
    expect(byId.ledger.tone).toBe("ready");
    expect(byId.ledger.text).toBe("Ledger verified — hash chain intact");
    expect(byId.retention.tone).toBe("ready");
    expect(byId.retention.text).toBe("Retention enforced");
    expect(byId.retention.detail).toContain("365-day policy");
    expect(byId.retention.detail).toContain("3 records excluded");
  });

  it("treats reference-verified demo proofs as verified", () => {
    const summary = buildAuditExportSummary({
      ...exportBundleFixture,
      integrity_proof: {
        ...exportBundleFixture.integrity_proof,
        verification_status: "reference_verified",
      },
    });
    expect(summary.find((line) => line.id === "ledger")?.tone).toBe("ready");
  });

  it("flags unverified chains, unenforced retention, and missing signatures", () => {
    const summary = buildAuditExportSummary({
      ...exportBundleFixture,
      integrity_proof: {
        ...exportBundleFixture.integrity_proof,
        verification_status: "failed",
      },
      manifest: { ...exportBundleFixture.manifest, retention_enforced: false },
    });
    const byId = Object.fromEntries(summary.map((line) => [line.id, line]));

    expect(byId.ledger.tone).toBe("action_required");
    expect(byId.retention.tone).toBe("action_required");
    expect(byId.signature.tone).toBe("watch");
    expect(byId.signature.text).toBe("Signature: not configured");
  });

  it("marks a verified ledger signature ready and legal holds as watch", () => {
    const summary = buildAuditExportSummary({
      ...exportBundleFixture,
      retention_policy: { ...exportBundleFixture.retention_policy, legal_hold: true },
      ledger_signature: {
        ...exportBundleFixture.ledger_signature,
        algorithm: "hmac-sha256",
        key_id: "audit-signing-key-1",
        signing_mode: "self_hosted_hmac",
        verification_status: "verified",
        signature: "e".repeat(64),
      },
    });
    const byId = Object.fromEntries(summary.map((line) => [line.id, line]));

    expect(byId.signature.tone).toBe("ready");
    expect(byId.signature.text).toBe("Ledger signature verified");
    expect(byId.retention.tone).toBe("watch");
    expect(byId.retention.detail).toContain("legal hold");
  });

  it("builds a dated export bundle file name", () => {
    expect(buildAuditExportFileName(exportBundleFixture)).toBe(
      "axis-audit-export-tenant_fixture-2026-07-09.json",
    );
  });
});
