import type {
  ConnectorManifestDetail,
  ConnectorCredentialLeaseRecord,
  ConnectorOntologyProposalRecord,
  ConnectorPreviewSample,
  ConnectorRegistryItem,
} from "./connectors-demo";
import { OPERATIONS_API_PREFIX } from "./tenant-scope";

/*
 * Pure helpers behind the connector console: client-side CSV parsing for the
 * Add Connector wizard, request builders that mirror the Axis API schemas
 * exactly (no invented fields), and small registry summaries. All request
 * shapes were read from `services/api/src/axis_api/{connectors,connector_manifests,connector_runs}.py`.
 */

export const CONNECTOR_SYNC_DISPATCH_SCOPE = "connectors:sync:dispatch";
export const CONNECTOR_SYNC_EXECUTE_SCOPE = "connectors:sync:execute";
export const CONNECTOR_MANIFEST_LIFECYCLE_SCOPE = "connectors:manifest:lifecycle";
export const CONNECTOR_MANIFEST_ENABLE_LIVE_SCOPE = "connectors:manifest:enable_live";
export const SOURCE_DISCOVERY_SCOPE = "connectors:source:discover";
export const CONNECTOR_MANIFEST_BATCH_LIMIT = 50;

/** The one connector whose source operations reach a real external database. */
export const EXTERNAL_DB_CONNECTOR_ID = "external_db_operational_mirror";

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

// ---------------------------------------------------------------------------
// Manifest lifecycle transitions

/**
 * Allowed lifecycle targets per current status, mirroring the API's
 * `MANIFEST_LIFECYCLE_TRANSITIONS` (connector_manifests.py). Deprecation is
 * terminal; only the API decides whether a requested transition is legal.
 */
export function manifestLifecycleTargets(status: string | null | undefined): string[] {
  switch (status) {
    case "registered_preview_only":
      return ["active_preview", "deprecated"];
    case "active_preview":
      return ["active_live", "deprecated"];
    case "active_live":
      return ["deprecated"];
    default:
      return [];
  }
}

/** Mirrors the API's `ConnectorManifestLifecycleRequest` (extra="forbid"). */
export type ConnectorManifestLifecyclePayload = {
  tenant_id: string;
  transitioned_by: string;
  target_status: string;
  actor_scopes: string[];
  required_scope: string;
  transition_reason: string;
  evidence_refs: string[];
};

/**
 * Scopes the API checks for a transition, mirroring
 * `_required_scopes_for_target` (connector_manifests.py): live enablement
 * demands the base lifecycle scope *and* the dedicated enable-live scope.
 */
export function manifestLifecycleScopes(targetStatus: string): string[] {
  return targetStatus === "active_live"
    ? [CONNECTOR_MANIFEST_LIFECYCLE_SCOPE, CONNECTOR_MANIFEST_ENABLE_LIVE_SCOPE]
    : [CONNECTOR_MANIFEST_LIFECYCLE_SCOPE];
}

export function buildManifestLifecycleRequest(input: {
  tenantId: string;
  actorId: string;
  targetStatus: string;
  reason: string;
  evidenceRefs?: string[];
}): ConnectorManifestLifecyclePayload {
  const scopes = manifestLifecycleScopes(input.targetStatus);
  return {
    tenant_id: input.tenantId,
    transitioned_by: input.actorId,
    target_status: input.targetStatus,
    // Demo-mode deployments have no OIDC principal, so the API evaluates the
    // grants declared here; authenticated sessions are re-stamped server-side
    // from the verified token.
    actor_scopes: scopes,
    required_scope: scopes[0],
    transition_reason: input.reason,
    evidence_refs: input.evidenceRefs ?? [],
  };
}

export type SourceOperationRefs = {
  connectionProfileId: string;
  schemaName?: string;
  credentialLeaseId: string;
  egressPolicyId: string;
};

/**
 * Build verify/discover payloads from operator-supplied references. Lease
 * and egress evidence are resolved server-side from persisted records; the
 * payload only names them. Demo mode declares its scope in the body, same
 * convention as lifecycle transitions.
 */
export function buildSourceVerifyRequest(input: {
  tenantId: string;
  actorId: string;
  refs: SourceOperationRefs;
  token: string;
}) {
  const token = input.token.toLowerCase().replaceAll("-", "");
  return {
    tenant_id: input.tenantId,
    connector_id: EXTERNAL_DB_CONNECTOR_ID,
    verification_id: `verify_console_${token}`,
    requested_by: input.actorId,
    connection_profile_id: input.refs.connectionProfileId,
    credential_lease_id: input.refs.credentialLeaseId,
    egress_policy_id: input.refs.egressPolicyId,
    actor_scopes: [SOURCE_DISCOVERY_SCOPE],
  };
}

export function buildSourceDiscoveryRequest(input: {
  tenantId: string;
  actorId: string;
  refs: SourceOperationRefs;
  token: string;
}) {
  if (!input.refs.schemaName) {
    throw new Error("Schema name is required for source discovery.");
  }
  const token = input.token.toLowerCase().replaceAll("-", "");
  return {
    tenant_id: input.tenantId,
    connector_id: EXTERNAL_DB_CONNECTOR_ID,
    discovery_id: `discovery_console_${token}`,
    requested_by: input.actorId,
    connection_profile_id: input.refs.connectionProfileId,
    schema_name: input.refs.schemaName,
    credential_lease_id: input.refs.credentialLeaseId,
    egress_policy_id: input.refs.egressPolicyId,
    actor_scopes: [SOURCE_DISCOVERY_SCOPE],
  };
}

export const SOURCE_ACTIVATION_SCOPE = "connectors:source:activate";

export type SourceActivationSelection = {
  bindingId: string;
  resourceName: string;
  expectedSchemaFingerprint: string;
  expectedSchemaFingerprintVersion?: "column_names_v1" | "postgres_schema_v2";
  supersedesBindingId?: string;
};

export function buildSourceActivationRequest(input: {
  tenantId: string;
  actorId: string;
  refs: SourceOperationRefs;
  reason: string;
  activationToken: string;
  selections: SourceActivationSelection[];
}) {
  if (input.selections.length === 0) {
    throw new Error("At least one table must be selected for activation.");
  }
  const activationId = `activation_console_${input.activationToken
    .toLowerCase()
    .replaceAll("-", "")}`;
  return {
    tenant_id: input.tenantId,
    connector_id: EXTERNAL_DB_CONNECTOR_ID,
    activation_id: activationId,
    requested_by: input.actorId,
    connection_profile_id: input.refs.connectionProfileId,
    credential_lease_id: input.refs.credentialLeaseId,
    egress_policy_id: input.refs.egressPolicyId,
    activation_reason: input.reason,
    selections: input.selections.map((selection) => ({
      binding_id: selection.bindingId,
      resource_name: selection.resourceName,
      expected_schema_fingerprint: selection.expectedSchemaFingerprint,
      expected_schema_fingerprint_version: selection.expectedSchemaFingerprintVersion ?? "column_names_v1",
      ...(selection.supersedesBindingId ? { supersedes_binding_id: selection.supersedesBindingId } : {}),
    })),
    actor_scopes: [SOURCE_ACTIVATION_SCOPE],
  };
}

export const SOURCE_INGESTION_SCOPE = "connectors:source:ingest";
export const SOURCE_INGESTION_READ_SCOPE = "connectors:source:ingest:read";

export const SOURCE_INGESTION_ENDPOINTS = {
  eligibility: `${OPERATIONS_API_PREFIX}/connectors/external-db/source-ingestion/eligibility`,
  overview: `${OPERATIONS_API_PREFIX}/connectors/external-db/source-ingestion/overview`,
  requests: `${OPERATIONS_API_PREFIX}/connectors/external-db/source-ingestion-requests`,
} as const;

/**
 * Build the governed ingestion request payload. The operator only names
 * bindings; the server pins each schema fingerprint from the active binding
 * itself, so no fingerprint ever crosses the client boundary. Demo mode
 * declares its scope in the body, same convention as discovery/activation.
 */
export function buildSourceIngestionRequest(input: {
  tenantId: string;
  actorId: string;
  requestId: string;
  reason: string;
  bindingIds: string[];
  stage?: "validate" | "extract";
}) {
  const requestId = input.requestId.trim();
  const reason = input.reason.trim();
  if (!requestId) {
    throw new Error("A request ID is required for governed ingestion.");
  }
  if (!reason) {
    throw new Error("A governance reason is required for ingestion requests.");
  }
  const bindingIds = [...new Set(input.bindingIds)];
  if (bindingIds.length === 0) {
    throw new Error("At least one pending binding must be selected for ingestion.");
  }
  return {
    tenant_id: input.tenantId,
    connector_id: EXTERNAL_DB_CONNECTOR_ID,
    request_id: requestId,
    requested_by: input.actorId,
    reason,
    stage: input.stage ?? "validate",
    selections: bindingIds.map((binding_id) => ({ binding_id })),
    actor_scopes: [SOURCE_INGESTION_SCOPE],
  };
}

export const SOURCE_EXTRACTION_BATCHES_ENDPOINT = (
  requestId: string,
) =>
  `${SOURCE_INGESTION_ENDPOINTS.requests}/${encodeURIComponent(requestId)}/batches`;

export const SOURCE_EXTRACTION_RECONCILIATION_ENDPOINT = (
  requestId: string,
) =>
  `${SOURCE_INGESTION_ENDPOINTS.requests}/${encodeURIComponent(
    requestId,
  )}/batches/reconciliation`;

/** Fenced re-dispatch of a dead-lettered governed ingestion request. */
export function buildSourceIngestionRedispatchRequest(input: {
  tenantId: string;
  actorId: string;
  reason: string;
  idempotencyKey: string;
}) {
  const reason = input.reason.trim();
  const key = input.idempotencyKey.trim();
  if (!reason) {
    throw new Error("A remediation reason is required to re-dispatch.");
  }
  if (!key) {
    throw new Error("An idempotency key is required to re-dispatch.");
  }
  return {
    tenant_id: input.tenantId,
    requeued_by: input.actorId,
    reason,
    idempotency_key: key,
    actor_scopes: [SOURCE_INGESTION_SCOPE],
  };
}

/** Fenced cancel of a still-pending governed ingestion request. */
export function buildSourceIngestionCancelRequest(input: {
  tenantId: string;
  actorId: string;
  reason?: string;
}) {
  return {
    tenant_id: input.tenantId,
    cancelled_by: input.actorId,
    ...(input.reason?.trim() ? { reason: input.reason.trim() } : {}),
    actor_scopes: [SOURCE_INGESTION_SCOPE],
  };
}

/**
 * Read paths carry the demo read scope as a repeated query parameter — the
 * same convention the checkpoint evidence endpoints use for GET scopes.
 */
export function buildSourceIngestionReadPath(input: {
  endpoint: string;
  tenantId: string;
  connectorId?: string;
  requestId?: string;
}): string {
  const query = new URLSearchParams({ tenant_id: input.tenantId });
  if (input.connectorId !== undefined) {
    query.set("connector_id", input.connectorId);
  }
  query.append("actor_scopes", SOURCE_INGESTION_READ_SCOPE);
  const suffix = input.requestId !== undefined
    ? `/${encodeURIComponent(input.requestId)}`
    : "";
  return `${input.endpoint}${suffix}?${query.toString()}`;
}

const LIVE_SYNC_MODES = ["live_query", "live_sync", "scheduled_sync"];
const LIVE_REQUIRED_ALLOWED_OPERATIONS = ["live_query", "external_egress"];
const LIVE_FORBIDDEN_BLOCKED_OPERATIONS = ["live_query", "external_egress"];

export type LiveEnablementRequirement = {
  met: boolean;
};

/**
 * Which of the API's live-enablement preconditions this connector's manifest
 * already satisfies. The API re-validates every gate; this list only tells
 * the operator what to expect before they try.
 */
export function liveEnablementRequirements(
  connector: ConnectorRegistryItem,
): Record<string, LiveEnablementRequirement> {
  const syncModes = connector.manifest.sync_modes ?? [];
  const allowedOperations = connector.runtime_policy.allowed_operations ?? [];
  const blockedOperations = connector.runtime_policy.blocked_operations ?? [];
  const egressPolicy = (connector.runtime_policy.egress_policy ?? "").trim().toLowerCase();

  return {
    liveSyncMode: {
      met: syncModes.some((mode) => LIVE_SYNC_MODES.includes(mode)),
    },
    liveOperationsAllowed: {
      met:
        LIVE_REQUIRED_ALLOWED_OPERATIONS.every((operation) => allowedOperations.includes(operation))
        && !blockedOperations.some((operation) =>
          LIVE_FORBIDDEN_BLOCKED_OPERATIONS.includes(operation)
        ),
    },
    egressBoundaryNamed: {
      met: egressPolicy !== "" && egressPolicy !== "none" && egressPolicy !== "no-external-egress",
    },
  };
}

export function allLiveRequirementsMet(
  requirements: Record<string, LiveEnablementRequirement>,
): boolean {
  return Object.values(requirements).every((requirement) => requirement.met);
}

/** Evidence categories the API demands for live enablement, with accepted prefixes. */
const LIVE_EVIDENCE_PREFIXES: Record<string, string[]> = {
  approval: ["approval:"],
  policy: ["policy:"],
  credential: ["credential:", "secret:", "vault:"],
};

/**
 * Which evidence categories are still missing under the API's
 * `_has_required_live_evidence` contract, so the console can ask for the
 * right references before the submission is rejected.
 */
export function missingLiveEvidenceCategories(evidenceRefs: string[]): string[] {
  const normalizedRefs = evidenceRefs.map((ref) => ref.trim().toLowerCase());
  return Object.entries(LIVE_EVIDENCE_PREFIXES)
    .filter(([, prefixes]) =>
      !normalizedRefs.some((ref) => prefixes.some((prefix) => ref.startsWith(prefix)))
    )
    .map(([category]) => category);
}
