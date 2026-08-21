import type { ManufacturingProvenance, PlatformStatus } from "./platform-overview";
import { strings } from "./strings";

export type AuditLedgerEvent = {
  audit_event_id: string;
  occurred_at: string;
  tenant_id: string;
  actor_id: string;
  actor_type: string;
  event_type: string;
  category: string;
  domain: string;
  scope: string;
  result: string;
  severity: PlatformStatus;
  source: string;
  summary: string;
  permission_scope: string;
  data_classification: string;
  related_workflow_id: string | null;
  related_approval_id: string | null;
  related_agent_id: string | null;
  evidence_refs: string[];
  payload_preview: Record<string, string>;
};

export type AuditFilterOptions = {
  tenants: string[];
  event_types: string[];
  scopes: string[];
  actors: string[];
  categories: string[];
};

export type ManufacturingAuditExplorer = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  as_of: string;
  ledger_status: PlatformStatus;
  metrics: {
    label: string;
    value: string;
    detail: string;
    status: PlatformStatus;
  }[];
  filter_options: AuditFilterOptions;
  events: AuditLedgerEvent[];
  retention_notes: string[];
};

export type AuditRetentionPolicy = {
  policy_id: string;
  retention_days: number;
  retention_basis: string;
  disposal_action: string;
  legal_hold: boolean;
  export_requires_review: boolean;
  notes: string[];
};

export type AuditExportManifest = {
  export_id: string;
  generated_at: string;
  tenant_id: string;
  record_count: number;
  format: string;
  redaction_policy: string;
  retention_policy_id: string;
  checksum_sha256: string;
  integrity_chain_tip_sha256: string;
  retention_enforced: boolean;
  retention_window_start: string;
  excluded_record_count: number;
};

export type AuditIntegrityProof = {
  algorithm: string;
  verification_status: string;
  record_count: number;
  chain_tip_sha256: string;
  event_hashes: string[];
};

export type AuditLedgerSignatureProof = {
  algorithm: string;
  key_id: string | null;
  signing_mode: string;
  verification_status: string;
  signed_payload_sha256: string;
  signature: string | null;
  notes: string[];
};

export type AuditExportBundle = {
  tenant_id: string;
  scenario: string | null;
  format: string;
  export_reason: string;
  filters: {
    tenant_id: string;
    event_type: string | null;
    actor_id: string | null;
    scope: string | null;
    limit: number;
  };
  retention_policy: AuditRetentionPolicy;
  manifest: AuditExportManifest;
  integrity_proof: AuditIntegrityProof;
  ledger_signature: AuditLedgerSignatureProof;
  events: AuditLedgerEvent[];
  retention_notes: string[];
};

export type AuditFilters = {
  tenant: string;
  eventType: string;
  scope: string;
};

export const allAuditFilter = "all";

type AuditEventSelectionInput = {
  explorer: ManufacturingAuditExplorer;
  filteredEvents: AuditLedgerEvent[];
  requestedEventId: string | null;
  selectedEventId: string;
};

export function filterAuditEvents(
  explorer: ManufacturingAuditExplorer,
  filters: AuditFilters,
): AuditLedgerEvent[] {
  return explorer.events.filter((event) => {
    const tenantMatches = filters.tenant === allAuditFilter || event.tenant_id === filters.tenant;
    const eventMatches =
      filters.eventType === allAuditFilter || event.event_type === filters.eventType;
    const scopeMatches = filters.scope === allAuditFilter || event.scope === filters.scope;

    return tenantMatches && eventMatches && scopeMatches;
  });
}

export function findAuditEventById(
  explorer: ManufacturingAuditExplorer,
  auditEventId: string,
): AuditLedgerEvent {
  return (
    explorer.events.find((event) => event.audit_event_id === auditEventId) ?? explorer.events[0]
  );
}

export function buildAuditEventHref(auditEventId: string | null | undefined): string {
  if (!auditEventId) {
    return "/audit";
  }

  const params = new URLSearchParams({ event_id: auditEventId });
  return `/audit?${params.toString()}`;
}

export function resolveAuditEventSelection(input: AuditEventSelectionInput): string {
  const requestedEventId = input.requestedEventId;
  const requestedEventIsVisible =
    requestedEventId !== null &&
    input.filteredEvents.some((event) => event.audit_event_id === requestedEventId);

  if (requestedEventIsVisible) {
    return requestedEventId;
  }

  const selectedEventIsVisible = input.filteredEvents.some(
    (event) => event.audit_event_id === input.selectedEventId,
  );

  if (selectedEventIsVisible) {
    return input.selectedEventId;
  }

  return input.filteredEvents[0]?.audit_event_id ?? input.explorer.events[0]?.audit_event_id ?? "";
}

export type AuditExportSummaryLine = {
  id: "ledger" | "retention" | "signature";
  tone: PlatformStatus;
  text: string;
  detail: string;
};

const verifiedIntegrityStatuses = new Set(["verified", "reference_verified"]);

/**
 * Plain-first summary of the export bundle's integrity/retention/signature
 * proofs. Raw hashes, checksums and key ids stay in the Inspect drawer.
 */
export function buildAuditExportSummary(bundle: AuditExportBundle): AuditExportSummaryLine[] {
  const copy = strings.audit.integrity;

  const ledgerVerified = verifiedIntegrityStatuses.has(
    bundle.integrity_proof.verification_status,
  );
  const ledger: AuditExportSummaryLine = {
    id: "ledger",
    tone: ledgerVerified ? "ready" : "action_required",
    text: ledgerVerified ? copy.ledger.verified : copy.ledger.unverified,
    detail: `${bundle.integrity_proof.record_count} records covered — ${copy.ledger.detail}`,
  };

  const legalHold = bundle.retention_policy.legal_hold;
  const retentionEnforced = bundle.manifest.retention_enforced;
  const retention: AuditExportSummaryLine = legalHold
    ? {
        id: "retention",
        tone: "watch",
        text: copy.retention.legalHold,
        detail: `${bundle.retention_policy.retention_days}-day policy — legal hold: ${copy.retention.legalHoldDetail}`,
      }
    : {
        id: "retention",
        tone: retentionEnforced ? "ready" : "action_required",
        text: retentionEnforced ? copy.retention.enforced : copy.retention.notEnforced,
        detail: `${bundle.retention_policy.retention_days}-day policy — ${bundle.manifest.excluded_record_count} records excluded from this export`,
      };

  const signatureVerified =
    bundle.ledger_signature.verification_status === "verified" &&
    bundle.ledger_signature.signature !== null;
  const signature: AuditExportSummaryLine = {
    id: "signature",
    tone: signatureVerified ? "ready" : "watch",
    text: signatureVerified ? copy.signature.verified : copy.signature.notConfigured,
    detail: signatureVerified ? copy.signature.verifiedDetail : copy.signature.notConfiguredDetail,
  };

  return [ledger, retention, signature];
}

/** Dated client-download name: axis-audit-export-<tenant>-<yyyy-mm-dd>.json */
export function buildAuditExportFileName(bundle: AuditExportBundle): string {
  const generated = new Date(bundle.manifest.generated_at);
  const date = Number.isNaN(generated.getTime())
    ? new Date().toISOString().slice(0, 10)
    : generated.toISOString().slice(0, 10);
  return `axis-audit-export-${bundle.tenant_id}-${date}.json`;
}

export function formatAuditLabel(value: string): string {
  return value
    .split(/[._:]/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
