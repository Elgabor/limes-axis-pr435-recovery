import type {
  ConnectorManifestDetail,
  ConnectorCredentialLeaseRecord,
  ConnectorOntologyProposalRecord,
  ConnectorPreviewSample,
  ConnectorRegistryItem,
} from "./connectors-demo";

/*
 * Pure helpers behind the connector console: client-side CSV parsing for the
 * Add Connector wizard, request builders that mirror the Axis API schemas
 * exactly (no invented fields), and small registry summaries. All request
 * shapes were read from `services/api/src/axis_api/{connectors,connector_manifests,connector_runs}.py`.
 */

export const CONNECTOR_SYNC_DISPATCH_SCOPE = "connectors:sync:dispatch";
export const CONNECTOR_SYNC_EXECUTE_SCOPE = "connectors:sync:execute";
export const CONNECTOR_MANIFEST_BATCH_LIMIT = 50;

/** Fallback actor recorded on unauthenticated demo writes; the API rebinds it to the OIDC principal when a session exists. */
export const CONNECTOR_CONSOLE_ACTOR = "connector-console-operator";

export type ConnectorRegistrationDocument = {
  manifest: ConnectorRegistryItem["manifest"];
  runtime_policy: ConnectorRegistryItem["runtime_policy"];
  preview_sample?: ConnectorPreviewSample | null;
  notes?: string[];
};

export type ConnectorManifestValidationOutcome =
  | "would_register"
  | "would_replace"
  | "invalid";

export type ConnectorManifestValidationResult = {
  connector_id: string | null;
  outcome: ConnectorManifestValidationOutcome;
  errors: Array<{
    field_path: string;
    message: string;
    reason: string;
  }>;
};

export type ConnectorManifestBatchValidationResponse = {
  tenant_id: string;
  summary: Record<ConnectorManifestValidationOutcome, number>;
  results: ConnectorManifestValidationResult[];
};

export function buildConnectorRegistrationDocument(
  connector: ConnectorRegistryItem,
): ConnectorRegistrationDocument {
  return {
    manifest: connector.manifest,
    runtime_policy: connector.runtime_policy,
    preview_sample: connector.preview_sample,
    notes: connector.persisted_manifest?.notes ?? [],
  };
}

export function serializeConnectorRegistrationDocument(connector: ConnectorRegistryItem): string {
  return JSON.stringify(buildConnectorRegistrationDocument(connector), null, 2);
}

export function connectorRegistrationFileName(connector: ConnectorRegistryItem): string {
  const connectorId = connector.manifest.connector_id.replace(/[^a-zA-Z0-9_-]+/g, "-");
  return `${connectorId}.registration.json`;
}

/**
 * Overlay the selected connector with the separately fetched current revision.
 * The registry remains the complete list/source fallback; once detail resolves,
 * schema, actions and export must all consume the same authoritative revision.
 */
export function connectorWithCurrentManifest(
  connector: ConnectorRegistryItem,
  detail: ConnectorManifestDetail | null,
): ConnectorRegistryItem {
  const registryManifest = connector.persisted_manifest;
  if (detail === null || registryManifest === null) {
    return connector;
  }

  const current = detail.current_revision;
  const connectorId = connector.manifest.connector_id;
  if (
    detail.connector_id !== connectorId ||
    current.connector_id !== connectorId ||
    current.manifest.connector_id !== connectorId
  ) {
    return connector;
  }

  // Registry and detail are fetched independently. A retained detail response
  // must not roll a freshly refreshed registry back to an older revision.
  // Revision number supplies ordering; manifest id resolves the equal-revision
  // case without guessing which divergent record is authoritative.
  if (
    current.revision_number < registryManifest.revision_number ||
    (current.revision_number === registryManifest.revision_number &&
      current.manifest_id !== registryManifest.manifest_id)
  ) {
    return connector;
  }

  return {
    ...connector,
    manifest: current.manifest,
    runtime_policy: current.runtime_policy,
    preview_sample: current.preview_sample,
    persisted_manifest: {
      manifest_id: current.manifest_id,
      revision_number: current.revision_number,
      status: current.status,
      registered_by: current.registered_by,
      registered_at: current.created_at,
      notes: current.notes,
    },
  };
}

// ---------------------------------------------------------------------------
// CSV round-trip

export type ParsedCsv = {
  headers: string[];
  rows: Record<string, string>[];
};

/**
 * Minimal RFC-4180 CSV parser for wizard previews: quoted fields may contain
 * commas, escaped quotes ("") and newlines. Values are trimmed the same way
 * the API's DictReader-based preview trims them.
 */
export function parseCsvText(text: string): ParsedCsv {
  const records: string[][] = [];
  let field = "";
  let record: string[] = [];
  let inQuotes = false;
  const input = text.replace(/\r\n/g, "\n").replace(/^﻿/, "");

  function endField() {
    record.push(field);
    field = "";
  }

  function endRecord() {
    endField();
    records.push(record);
    record = [];
  }

  for (let index = 0; index < input.length; index += 1) {
    const character = input[index];

    if (inQuotes) {
      if (character === '"') {
        if (input[index + 1] === '"') {
          field += '"';
          index += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += character;
      }
      continue;
    }

    if (character === '"') {
      inQuotes = true;
    } else if (character === ",") {
      endField();
    } else if (character === "\n") {
      endRecord();
    } else {
      field += character;
    }
  }
  if (field.length > 0 || record.length > 0) {
    endRecord();
  }

  const nonEmpty = records.filter(
    (cells) => cells.length > 1 || (cells[0] ?? "").trim() !== "",
  );
  const headers = (nonEmpty[0] ?? []).map((header) => header.trim());
  const rows = nonEmpty.slice(1).map((cells) => {
    const row: Record<string, string> = {};
    headers.forEach((header, headerIndex) => {
      row[header] = (cells[headerIndex] ?? "").trim();
    });
    return row;
  });

  return { headers, rows };
}

function escapeCsvValue(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}

/**
 * Serialize a connector's recorded preview sample back into CSV text so the
 * Validate action can re-run the real preview endpoint against it.
 */
export function buildCsvFromPreviewSample(sample: ConnectorPreviewSample): string {
  const lines = [sample.headers.map(escapeCsvValue).join(",")];
  for (const row of sample.sample_rows) {
    lines.push(sample.headers.map((header) => escapeCsvValue(row[header] ?? "")).join(","));
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Wizard request builders

/** Derive a snake_case connector id from an uploaded file name. */
export function deriveConnectorId(fileName: string, connectorType: string): string {
  const stem = fileName.replace(/\.[^.]+$/, "");
  const slug = stem
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_{2,}/g, "_");

  return `${connectorType}_${slug || "connector"}`;
}

/** Mirrors the API's `ConnectorCsvPreviewRequest` (connectors.py). */
export type ConnectorCsvPreviewPayload = {
  tenant_id: string;
  connector_id: string;
  file_name: string;
  csv_content: string;
};

/** Mirrors the API's `ConnectorExternalDbPreviewRequest` (connectors.py, extra="forbid"). */
export type ConnectorExternalDbPreviewPayload = {
  tenant_id: string;
  connector_id: string;
  connection_profile_id: string;
  schema_name: string;
  table_name: string;
  selected_columns: string[];
  sample_limit: number;
  credential_handle_id: string;
  metadata: Record<string, string>;
};

export function buildExternalDbPreviewRequest(input: {
  tenantId: string;
  connectorId: string;
  connectionProfileId: string;
  schemaName: string;
  tableName: string;
  credentialHandleId: string;
  template: ConnectorRegistryItem | null;
}): ConnectorExternalDbPreviewPayload {
  return {
    tenant_id: input.tenantId,
    connector_id: input.connectorId,
    connection_profile_id: input.connectionProfileId,
    schema_name: input.schemaName,
    table_name: input.tableName,
    selected_columns:
      input.template?.manifest.schema_fields.map((field) => field.source_column) ?? [],
    sample_limit: 2,
    credential_handle_id: input.credentialHandleId,
    // Metadata stays empty: raw connection strings, SQL and credentials are
    // rejected by the API's public-safe validation.
    metadata: {},
  };
}

/** Mirrors the API's `ConnectorManifestCreateRequest` (connector_manifests.py, extra="forbid"). */
export type ConnectorManifestCreatePayload = {
  tenant_id: string;
  registered_by: string;
  manifest: ConnectorRegistryItem["manifest"];
  runtime_policy: ConnectorRegistryItem["runtime_policy"];
  preview_sample: ConnectorPreviewSample;
  notes: string[];
};

export function buildManifestCreateRequest(input: {
  tenantId: string;
  registeredBy: string;
  template: ConnectorRegistryItem;
  connectorId: string;
  displayName: string;
  previewSample: ConnectorPreviewSample;
}): ConnectorManifestCreatePayload {
  return {
    tenant_id: input.tenantId,
    registered_by: input.registeredBy,
    manifest: {
      ...input.template.manifest,
      connector_id: input.connectorId,
      display_name: input.displayName,
    },
    runtime_policy: { ...input.template.runtime_policy },
    preview_sample: input.previewSample,
    notes: ["Registered from the connector console wizard."],
  };
}

// ---------------------------------------------------------------------------
// Preview-sync plan (create -> dispatch -> execute-sync)

/** Mirrors the API's `ConnectorRunCreateRequest` (connector_runs.py, extra="forbid"). */
export type ConnectorRunCreatePayload = {
  tenant_id: string;
  connector_id: string;
  run_id: string;
  execution_mode: string;
  requested_by: string;
  credential_handle_ids: string[];
  credential_lease_id: string;
  schedule_id: string;
  schedule_cadence: string;
  schedule_timezone: string;
  next_run_at: string;
  input_summary: Record<string, string>;
  result_summary: Record<string, string>;
  notes: string[];
};

/** Mirrors the API's `ConnectorRunDispatchRequest`. */
export type ConnectorRunDispatchPayload = {
  tenant_id: string;
  dispatch_id: string;
  dispatched_by: string;
  actor_scopes: string[];
  credential_lease_id: string;
  idempotency_key: string;
  notes: string[];
};

/** Mirrors the API's `ConnectorRunSyncExecutionRequest`. */
export type ConnectorRunSyncExecutionPayload = {
  tenant_id: string;
  execution_id: string;
  executed_by: string;
  actor_scopes: string[];
  credential_lease_id: string;
  idempotency_key: string;
  notes: string[];
};

export type ConnectorPreviewSyncPlan = {
  runId: string;
  create: ConnectorRunCreatePayload;
  dispatch: ConnectorRunDispatchPayload;
  execute: ConnectorRunSyncExecutionPayload;
};

/**
 * Find the credential lease the preview-sync flow can legally use: it must
 * belong to the connector, be active, and not be expired — the API enforces
 * exactly these rules in `_validate_active_credential_lease_for_run`.
 */
export function findActiveLeaseForConnector(
  leases: ConnectorCredentialLeaseRecord[],
  connectorId: string,
  now: Date,
): ConnectorCredentialLeaseRecord | null {
  return (
    leases.find(
      (lease) =>
        lease.connector_id === connectorId
        && lease.status === "active"
        && new Date(lease.expires_at).getTime() > now.getTime(),
    ) ?? null
  );
}

/**
 * Build the three-stage preview-sync payloads from one token so retries are
 * idempotent server replays instead of conflicting duplicates.
 */
export function buildPreviewSyncPlan(input: {
  tenantId: string;
  connectorId: string;
  actorId: string;
  lease: ConnectorCredentialLeaseRecord;
  now: Date;
  token: string;
}): ConnectorPreviewSyncPlan {
  const token = input.token.toLowerCase().replaceAll("-", "");
  const runId = `run_console_${token}`;

  return {
    runId,
    create: {
      tenant_id: input.tenantId,
      connector_id: input.connectorId,
      run_id: runId,
      execution_mode: "scheduled_sync_plan",
      requested_by: input.actorId,
      credential_handle_ids: [input.lease.handle_id],
      credential_lease_id: input.lease.lease_id,
      schedule_id: `sched_console_${token}`,
      schedule_cadence: "manual_preview",
      schedule_timezone: "UTC",
      next_run_at: input.now.toISOString(),
      input_summary: { trigger: "connector-console-preview-sync" },
      result_summary: {},
      notes: ["Preview sync started from the connector console."],
    },
    dispatch: {
      tenant_id: input.tenantId,
      dispatch_id: `dispatch_console_${token}`,
      dispatched_by: input.actorId,
      actor_scopes: [CONNECTOR_SYNC_DISPATCH_SCOPE],
      credential_lease_id: input.lease.lease_id,
      idempotency_key: `idem_dispatch_console_${token}`,
      notes: [],
    },
    execute: {
      tenant_id: input.tenantId,
      execution_id: `exec_console_${token}`,
      executed_by: input.actorId,
      actor_scopes: [CONNECTOR_SYNC_EXECUTE_SCOPE],
      credential_lease_id: input.lease.lease_id,
      idempotency_key: `idem_exec_console_${token}`,
      notes: [],
    },
  };
}

// ---------------------------------------------------------------------------
// Registry summaries

/** Proposals still waiting for promotion into the ontology graph. */
export function pendingProposalCount(proposals: ConnectorOntologyProposalRecord[]): number {
  return proposals.filter((proposal) => !proposal.promoted_at).length;
}

/** Manifest lifecycle states in which the API allows connector run operations. */
export function manifestAllowsRuns(manifest: { status: string } | null): boolean {
  return manifest !== null && ["active_preview", "active_live"].includes(manifest.status);
}
