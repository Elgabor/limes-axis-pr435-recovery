import { z } from "zod";

import type {
  ConnectorCsvPreviewResult,
  ConnectorExternalDbPreviewResult,
  ConnectorRunRecord,
  ManufacturingConnectorCredentialHandleRegistry,
  ManufacturingConnectorCredentialLeaseRegistry,
  ManufacturingConnectorEgressPolicyRegistry,
  ManufacturingConnectorEvidenceInvariantReport,
  ManufacturingConnectorEvidenceInvariantSnapshotHistory,
  ManufacturingConnectorManifestRegistry,
  ManufacturingConnectorOntologyProposalRegistry,
  ManufacturingConnectorRegistry,
  ManufacturingConnectorRunRegistry,
} from "../connectors-demo";
import {
  manufacturingProvenanceSchema,
  nullableStringSchema,
  overviewMetricSchema,
  parseContract,
  platformStatusSchema,
  stringArraySchema,
} from "./shared";

const stringRecord = z.record(z.string(), z.string());
const unknownRecord = z.record(z.string(), z.unknown());
const connectorManifest = z.object({
  connector_id: z.string(),
  display_name: z.string(),
  connector_type: z.string(),
  version: z.string(),
  source_type: z.string(),
  sync_modes: stringArraySchema,
  runtime_boundary: z.string(),
  required_permissions: stringArraySchema,
  credential_requirements: z.object({
    storage: z.string(),
    required_secret_refs: stringArraySchema,
    notes: stringArraySchema,
  }),
  schema_fields: z.array(z.object({
    source_column: z.string(),
    target_field: z.string(),
    ontology_target: z.string(),
    data_type: z.string(),
    required: z.boolean(),
    description: z.string(),
  })),
  mapping_notes: stringArraySchema,
});
const connectorRuntimePolicy = z.object({
  allowed_operations: stringArraySchema,
  blocked_operations: stringArraySchema,
  egress_policy: z.string(),
  max_file_size_mb: z.number(),
  row_limit: z.number(),
  payload_policy: z.string(),
});
const connectorPreviewSample = z.object({
  file_name: z.string(),
  record_count: z.number(),
  headers: stringArraySchema,
  sample_rows: z.array(stringRecord),
});
const connectorPersistedManifestSummary = z.object({
  manifest_id: z.string(),
  revision_number: z.number().int().positive(),
  status: z.string(),
  registered_by: z.string(),
  registered_at: z.string(),
  notes: stringArraySchema,
});
export const connectorRegistryItem = z.object({
  manifest: connectorManifest,
  runtime_policy: connectorRuntimePolicy,
  preview_sample: connectorPreviewSample.nullable(),
  last_successful_sync: z.object({
    run_id: z.string(),
    completed_at: z.string(),
    records_read: z.number().int().nonnegative(),
  }).nullable(),
  connector_status: platformStatusSchema,
  registry_origin: z.enum(["reference", "persisted_manifest"]),
  persisted_manifest: connectorPersistedManifestSummary.nullable(),
}).superRefine((item, context) => {
  if (item.registry_origin === "persisted_manifest" && item.persisted_manifest === null) {
    context.addIssue({
      code: "custom",
      message: "Persisted-manifest connector items require persistence metadata.",
      path: ["persisted_manifest"],
    });
  }
});
const proposedOntologyEntity = z.object({
  node_id: z.string(),
  node_type: z.string(),
  ontology_type: z.string(),
  field_summary: stringRecord,
  evidence_refs: stringArraySchema,
});
const connectorAuditEventPreview = z.object({
  event_type: z.string(),
  scope: z.string(),
  actor_id: z.string(),
  result: z.string(),
  evidence_refs: stringArraySchema,
  payload_preview: stringRecord,
});
const connectorCsvPreviewResult = z.object({
  tenant_id: z.string(),
  connector_id: z.string(),
  file_name: z.string(),
  preview_status: z.string(),
  sync_mode: z.string(),
  record_count: z.number(),
  accepted_record_count: z.number(),
  rejected_record_count: z.number(),
  validation_issues: stringArraySchema,
  proposed_entities: z.array(proposedOntologyEntity),
  audit_event_preview: connectorAuditEventPreview,
  preview_notes: stringArraySchema,
});
const connectorExternalDbPreviewResult = z.object({
  tenant_id: z.string(),
  connector_id: z.string(),
  connection_profile_id: z.string(),
  source_type: z.string(),
  preview_status: z.string(),
  sync_mode: z.string(),
  live_query_executed: z.boolean(),
  validation_issues: stringArraySchema,
  inspected_table: z.object({
    schema_name: z.string(),
    table_name: z.string(),
    table_ref: z.string(),
    record_count_estimate: z.string(),
    sample_limit: z.number(),
    columns: z.array(z.object({
      source_column: z.string(),
      target_field: z.string(),
      ontology_target: z.string(),
      data_type: z.string(),
      nullable: z.boolean(),
    })),
    sample_rows: z.array(stringRecord),
  }),
  proposed_entities: z.array(proposedOntologyEntity),
  audit_event_preview: connectorAuditEventPreview,
  preview_notes: stringArraySchema,
});
const connectorRegistryHeader = {
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  registry_status: platformStatusSchema,
  metrics: z.array(overviewMetricSchema),
};
const connectorRegistry = z.object({
  ...connectorRegistryHeader,
  connectors: z.array(connectorRegistryItem),
  connector_notes: stringArraySchema,
});
const connectorManifestRecord = z.object({
  tenant_id: z.string(),
  manifest_id: z.string(),
  connector_id: z.string(),
  revision_number: z.number().int().positive(),
  display_name: z.string(),
  connector_type: z.string(),
  source_type: z.string(),
  version: z.string(),
  status: z.string(),
  runtime_boundary: z.string(),
  registered_by: z.string(),
  manifest: connectorManifest,
  runtime_policy: connectorRuntimePolicy,
  preview_sample: connectorPreviewSample.nullable(),
  audit_event_id: nullableStringSchema,
  audit_event_type: z.string(),
  revises_revision_number: z.number().int().positive().nullable(),
  replaced_by_revision_number: z.number().int().positive().nullable(),
  revision_idempotency_key: nullableStringSchema,
  idempotent_replay: z.boolean(),
  unchanged: z.boolean(),
  notes: stringArraySchema,
  created_at: z.string(),
});
const connectorManifestRegistry = z.object({
  ...connectorRegistryHeader,
  manifests: z.array(connectorManifestRecord),
  manifest_notes: stringArraySchema,
});
const connectorManifestTransition = z.object({
  from_status: z.string(),
  target_status: z.string(),
  transitioned_by: z.string(),
  transition_reason: z.string(),
  evidence_refs: stringArraySchema,
  audit_event_id: z.string(),
  audit_event_type: z.string(),
  transitioned_at: z.string(),
});
const connectorManifestDetail = z.object({
  tenant_id: z.string(),
  connector_id: z.string(),
  current_revision: connectorManifestRecord,
  revisions: z.array(connectorManifestRecord),
  transitions: z.array(connectorManifestTransition),
}).superRefine((detail, context) => {
  const revisions = [detail.current_revision, ...detail.revisions];
  revisions.forEach((revision, index) => {
    const pathPrefix = index === 0 ? ["current_revision"] : ["revisions", index - 1];
    if (revision.tenant_id !== detail.tenant_id) {
      context.addIssue({
        code: "custom",
        message: "Manifest revision tenant does not match the detail envelope.",
        path: [...pathPrefix, "tenant_id"],
      });
    }
    if (revision.connector_id !== detail.connector_id) {
      context.addIssue({
        code: "custom",
        message: "Manifest revision connector does not match the detail envelope.",
        path: [...pathPrefix, "connector_id"],
      });
    }
    if (revision.manifest.connector_id !== detail.connector_id) {
      context.addIssue({
        code: "custom",
        message: "Nested manifest connector does not match the detail envelope.",
        path: [...pathPrefix, "manifest", "connector_id"],
      });
    }
  });
});
const connectorManifestBatchValidationResponse = z.object({
  tenant_id: z.string(),
  summary: z.object({
    would_register: z.number().int().nonnegative(),
    would_replace: z.number().int().nonnegative(),
    invalid: z.number().int().nonnegative(),
  }),
  results: z.array(z.object({
    connector_id: nullableStringSchema,
    outcome: z.enum(["would_register", "would_replace", "invalid"]),
    errors: z.array(z.object({
      field_path: z.string(),
      message: z.string(),
      reason: z.string(),
    })),
  })),
});
const credentialRotation = z.object({
  tenant_id: z.string(),
  handle_id: z.string(),
  rotated_by: z.string(),
  rotated_at: z.string(),
  evidence_ref: z.string(),
  status: z.string(),
  notes: stringArraySchema,
});
const connectorCredentialHandleRegistry = z.object({
  ...connectorRegistryHeader,
  handles: z.array(z.object({
    tenant_id: z.string(),
    connector_id: z.string(),
    handle_id: z.string(),
    display_name: z.string(),
    status: z.string(),
    secret_provider: z.string(),
    secret_ref: z.string(),
    purpose: z.string(),
    rotation_interval_days: z.number(),
    rotation_status: z.string(),
    rotation_count: z.number(),
    last_rotated_at: nullableStringSchema,
    next_rotation_due_at: nullableStringSchema,
    created_by: z.string(),
    labels: stringRecord,
    notes: stringArraySchema,
    last_rotation: credentialRotation.nullable(),
  })),
  handle_notes: stringArraySchema,
});
const permissionDecision = z.object({ allowed: z.boolean(),
  reason: z.string() });
const connectorCredentialLeaseRegistry = z.object({
  ...connectorRegistryHeader,
  leases: z.array(z.object({
    tenant_id: z.string(),
    connector_id: z.string(),
    handle_id: z.string(),
    lease_id: z.string(),
    status: z.string(),
    lease_mode: z.string(),
    runtime_boundary: z.string(),
    requested_by: z.string(),
    lease_purpose: z.string(),
    secret_provider: z.string(),
    secret_ref: z.string(),
    vault_kms_policy: stringRecord,
    permission_decision: permissionDecision,
    lease_result: stringRecord,
    granted_at: z.string(),
    expires_at: z.string(),
    renewal_due_at: z.string(),
    renewed_at: nullableStringSchema,
    renewed_by: nullableStringSchema,
    renewal_count: z.number(),
    revoked_at: nullableStringSchema,
    revoked_by: nullableStringSchema,
    revocation_reason: nullableStringSchema,
    audit_event_id: nullableStringSchema,
    audit_event_type: z.string(),
    notes: stringArraySchema,
    created_at: z.string(),
  })),
  lease_evidence_invariants: z.array(z.object({
    lease_id: z.string(),
    audit_event_id: nullableStringSchema,
    reason: z.string(),
    detail: z.string(),
  })),
  lease_notes: stringArraySchema,
});
const connectorEgressPolicyRegistry = z.object({
  ...connectorRegistryHeader,
  policies: z.array(z.object({
    tenant_id: z.string(),
    connector_id: z.string(),
    policy_id: z.string(),
    display_name: z.string(),
    status: z.string(),
    connection_profile_id: z.string(),
    egress_boundary: z.string(),
    policy_mode: z.string(),
    runtime_boundary: z.string(),
    private_endpoint_ref: z.string(),
    created_by: z.string(),
    policy_document: stringRecord,
    evidence_refs: stringArraySchema,
    audit_event_id: nullableStringSchema,
    audit_event_type: z.string(),
    notes: stringArraySchema,
    created_at: z.string(),
  })),
  policy_evidence_invariants: z.array(z.object({
    policy_id: z.string(),
    audit_event_id: nullableStringSchema,
    reason: z.string(),
    detail: z.string(),
  })),
  policy_notes: stringArraySchema,
});
const connectorRunResult = z.object({
  adapter: z.string(),
  status: z.string(),
  external_sync_started: z.boolean(),
  idempotency_key: z.string(),
  result_summary: stringRecord,
  notes: stringArraySchema,
});
const connectorRunRecord = z.object({
  tenant_id: z.string(),
  connector_id: z.string(),
  run_id: z.string(),
  status: z.string(),
  execution_mode: z.string(),
  runtime_boundary: z.string(),
  requested_by: z.string(),
  credential_handle_ids: stringArraySchema,
  input_summary: stringRecord,
  result_summary: unknownRecord,
  execution_result: connectorRunResult.nullable(),
  schedule_result: connectorRunResult.extend({ schedule_ref: z.string() }).nullable(),
  dispatch_result: connectorRunResult.extend({ dispatch_ref: z.string() }).nullable(),
  sync_execution_result: connectorRunResult.extend({ sync_ref: z.string() }).nullable(),
  audit_event_id: nullableStringSchema,
  audit_event_type: z.string(),
  notes: stringArraySchema,
  created_at: z.string(),
});
const connectorRunRegistry = z.object({
  ...connectorRegistryHeader,
  runs: z.array(connectorRunRecord),
  run_notes: stringArraySchema,
});
const connectorEvidenceInvariantReport = z.object({
  ...connectorRegistryHeader,
  invariant_counts: z.object({
    checkpoint: z.number(),
    checkpoint_claim: z.number(),
    credential_lease: z.number(),
    egress_policy: z.number(),
  }),
  invariants: z.array(z.object({
    evidence_type: z.enum(["checkpoint", "checkpoint_claim", "credential_lease", "egress_policy"]),
    subject_id: z.string(),
    parent_id: nullableStringSchema,
    audit_event_id: nullableStringSchema,
    reason: z.string(),
    detail: z.string(),
  })),
  report_notes: stringArraySchema,
});
const connectorEvidenceInvariantSnapshotHistory = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  history_status: platformStatusSchema,
  metrics: z.array(overviewMetricSchema),
  snapshots: z.array(z.object({
    tenant_id: z.string(),
    snapshot_id: z.string(),
    status: z.string(),
    connector_id: nullableStringSchema,
    requested_by: z.string(),
    idempotency_key: z.string(),
    reason: z.string(),
    invariant_count: z.number(),
    invariant_counts: z.record(z.string(), z.number()),
    subject_ids: stringArraySchema,
    report_digest_sha256: z.string(),
    report_hash_algorithm: z.string(),
    permission_decision: permissionDecision,
    audit_event_id: nullableStringSchema,
    audit_event_type: z.string(),
    idempotent_replay: z.boolean(),
    notes: stringArraySchema,
  })),
  history_notes: stringArraySchema,
});
const connectorPromotionDecision = z.object({
  status: z.string(),
  allowed: z.boolean(),
  policy_id: nullableStringSchema,
  policy_version: nullableStringSchema,
  policy_set_id: nullableStringSchema,
  policy_set_version: nullableStringSchema,
  policy_ids: stringArraySchema,
  policy_results: z.array(unknownRecord),
  enforcement_mode: z.string(),
  reason: z.string(),
  required_scopes: stringArraySchema,
  matched_constraints: stringRecord,
});
const connectorOntologyProposalRegistry = z.object({
  ...connectorRegistryHeader,
  proposals: z.array(z.object({
    tenant_id: z.string(),
    connector_id: z.string(),
    proposal_id: z.string(),
    source_run_id: nullableStringSchema,
    source_file_name: z.string(),
    mapping_profile: z.string(),
    status: z.string(),
    write_mode: z.string(),
    graph_mutation_status: z.string(),
    proposed_by: z.string(),
    node_id: z.string(),
    node_type: z.string(),
    ontology_type: z.string(),
    field_summary: stringRecord,
    evidence_refs: stringArraySchema,
    promotion_id: nullableStringSchema,
    policy_id: nullableStringSchema,
    policy_set_id: nullableStringSchema,
    policy_ids: stringArraySchema.nullable(),
    policy_decision: connectorPromotionDecision.nullable(),
    promoted_by: nullableStringSchema,
    promoted_at: nullableStringSchema,
    ontology_mutation: z.object({
      status: z.string(),
      adapter: z.string(),
      mutation_ref: nullableStringSchema,
      typeql: nullableStringSchema,
      payload: unknownRecord,
    }).nullable(),
    audit_event_id: nullableStringSchema,
    audit_event_type: z.string(),
    notes: stringArraySchema,
    created_at: z.string(),
  })),
  proposal_notes: stringArraySchema,
});

export function parseManufacturingConnectorRegistry(
  value: unknown,
): ManufacturingConnectorRegistry {
  return parseContract(connectorRegistry, value);
}

export function parseManufacturingConnectorManifestRegistry(
  value: unknown,
): ManufacturingConnectorManifestRegistry {
  return parseContract(connectorManifestRegistry, value);
}

export function parseConnectorManifestDetail(value: unknown) {
  return parseContract(connectorManifestDetail, value);
}

export function parseConnectorManifestRecord(value: unknown) {
  return parseContract(connectorManifestRecord, value);
}

export function parseConnectorManifestBatchValidationResponse(value: unknown) {
  return parseContract(connectorManifestBatchValidationResponse, value);
}

export function parseManufacturingConnectorCredentialHandleRegistry(
  value: unknown,
): ManufacturingConnectorCredentialHandleRegistry {
  return parseContract(connectorCredentialHandleRegistry, value);
}

export function parseManufacturingConnectorCredentialLeaseRegistry(
  value: unknown,
): ManufacturingConnectorCredentialLeaseRegistry {
  return parseContract(connectorCredentialLeaseRegistry, value);
}

export function parseManufacturingConnectorEgressPolicyRegistry(
  value: unknown,
): ManufacturingConnectorEgressPolicyRegistry {
  return parseContract(connectorEgressPolicyRegistry, value);
}

export function parseManufacturingConnectorRunRegistry(
  value: unknown,
): ManufacturingConnectorRunRegistry {
  return parseContract(connectorRunRegistry, value);
}

export function parseManufacturingConnectorEvidenceInvariantReport(
  value: unknown,
): ManufacturingConnectorEvidenceInvariantReport {
  return parseContract(connectorEvidenceInvariantReport, value);
}

export function parseManufacturingConnectorEvidenceInvariantSnapshotHistory(
  value: unknown,
): ManufacturingConnectorEvidenceInvariantSnapshotHistory {
  return parseContract(connectorEvidenceInvariantSnapshotHistory, value);
}

export function parseManufacturingConnectorOntologyProposalRegistry(
  value: unknown,
): ManufacturingConnectorOntologyProposalRegistry {
  return parseContract(connectorOntologyProposalRegistry, value);
}

export function parseConnectorCsvPreviewResult(value: unknown): ConnectorCsvPreviewResult {
  return parseContract(connectorCsvPreviewResult, value);
}

export function parseConnectorExternalDbPreviewResult(
  value: unknown,
): ConnectorExternalDbPreviewResult {
  return parseContract(connectorExternalDbPreviewResult, value);
}

export function parseConnectorRunRecord(value: unknown): ConnectorRunRecord {
  return parseContract(connectorRunRecord, value);
}

const sourceVerificationResult = z.object({
  adapter: z.string(),
  status: z.string(),
  block_reason: z.string(),
  database_name: z.string(),
  evidence_summary: stringRecord,
  notes: stringArraySchema,
});

const sourceDiscoveryTable = z.object({
  schema_name: z.string(),
  table_name: z.string(),
  column_names: stringArraySchema,
  column_fingerprint: z.string(),
  schema_fingerprint_version: z.enum(["column_names_v1", "postgres_schema_v2"]).optional(),
  columns_truncated: z.boolean(),
});

const sourceDiscoveryObservation = z.object({
  table_name: z.string(),
  observation: z.object({
    resource_name: z.string(),
    schema_fingerprint: nullableStringSchema,
    previous_fingerprint: nullableStringSchema,
    drift_state: z.string(),
    last_source_kind: z.string(),
    first_seen_at: z.string(),
    last_seen_at: z.string(),
    observation_count: z.number(),
    observed_by: z.string(),
  }),
});

const sourceVerificationOutcome = z.object({
  verification_id: z.string(),
  result: sourceVerificationResult,
  correlation_ref: z.string(),
});

const sourceDiscoveryOutcome = z.object({
  discovery_id: z.string(),
  result: z.object({
    adapter: z.string(),
    status: z.string(),
    block_reason: z.string(),
    discovered_schema: z.string(),
    tables: z.array(sourceDiscoveryTable),
    tables_truncated: z.boolean(),
    evidence_summary: stringRecord,
    notes: stringArraySchema,
  }),
  observations: z.array(sourceDiscoveryObservation),
  correlation_ref: z.string(),
});

export type SourceVerificationOutcome = z.infer<typeof sourceVerificationOutcome>;
export type SourceDiscoveryOutcome = z.infer<typeof sourceDiscoveryOutcome>;

export function parseSourceVerificationOutcome(
  value: unknown,
): SourceVerificationOutcome {
  return parseContract(sourceVerificationOutcome, value);
}

export function parseSourceDiscoveryOutcome(value: unknown): SourceDiscoveryOutcome {
  return parseContract(sourceDiscoveryOutcome, value);
}

const sourceBindingView = z.object({
  binding_id: z.string(),
  resource_name: z.string(),
  schema_fingerprint: z.string(),
  schema_fingerprint_version: z.string().optional(),
  supersedes_binding_id: z.string().nullable().optional(),
  status: z.string(),
  ingestion_status: z.string(),
  outcome: z.string(),
  connection_profile_id: z.string(),
  activated_by: z.string(),
  activated_at: z.string(),
});

export type SourceBindingView = z.infer<typeof sourceBindingView>;

const sourceActivationOutcome = z.object({
  tenant_id: z.string(),
  connector_id: z.string(),
  activation_id: z.string(),
  bindings: z.array(sourceBindingView),
  correlation_ref: z.string(),
});

const sourceBindingsView = z.object({
  tenant_id: z.string(),
  connector_id: z.string(),
  bindings: z.array(sourceBindingView),
});

type SourceActivationOutcome = z.infer<typeof sourceActivationOutcome>;
type SourceBindingsView = z.infer<typeof sourceBindingsView>;

export function parseSourceActivationOutcome(value: unknown): SourceActivationOutcome {
  return parseContract(sourceActivationOutcome, value);
}

export function parseSourceBindingsView(value: unknown): SourceBindingsView {
  return parseContract(sourceBindingsView, value);
}

const sourceIngestionSelection = z.object({
  binding_id: z.string(),
  resource_name: z.string(),
  schema_fingerprint: z.string(),
});

const sourceExtractionSummary = z.object({
  batch_count: z.number(),
  total_rows: z.number(),
  truncated_any: z.boolean(),
});

const sourceIngestionAttemptSelection = z.object({
  binding_id: z.string(),
  resource_name: z.string(),
  outcome: z.enum(["validated", "failed"]),
  reason: z.string().nullable(),
});

const sourceIngestionAttempt = z.object({
  attempt_number: z.number(),
  outcome: z.enum(["completed", "retried", "dead_lettered"]),
  error_code: z.string().nullable(),
  finished_at: z.string().nullable(),
  selections: z.array(sourceIngestionAttemptSelection),
});


const sourceIngestionRequestView = z.object({
  tenant_id: z.string(),
  connector_id: z.string(),
  request_id: z.string(),
  requested_by: z.string(),
  reason: z.string(),
  stage: z.enum(["validate", "extract"]),
  status: z.enum(["pending", "dispatching", "completed", "failed", "cancelled"]),
  attempt_count: z.number(),
  selections: z.array(sourceIngestionSelection),
  outcome: z.string(),
  planned_limits: z.record(z.string(), z.number()).nullable(),
  extraction: sourceExtractionSummary.nullable(),
  attempts: z.array(sourceIngestionAttempt).default([]),
  attempts_truncated: z.boolean().default(false),
  last_error: z.string().nullable(),
  completed_at: z.string().nullable(),
  dead_lettered_at: z.string().nullable(),
  cancelled_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export type SourceIngestionRequestView = z.infer<typeof sourceIngestionRequestView>;

export type SourceExtractionSummary = z.infer<typeof sourceExtractionSummary>;

const sourceIngestionEligibilityRow = z.object({
  binding_id: z.string(),
  resource_name: z.string(),
  schema_fingerprint: z.string(),
  eligible: z.boolean(),
  blocked_reason: z.string().nullable(),
});

const eligibilityRowsSchema = z.array(sourceIngestionEligibilityRow);

export type SourceIngestionEligibilityRow = z.infer<typeof sourceIngestionEligibilityRow>;

const sourceIngestionEligibilityView = z.object({
  tenant_id: z.string(),
  connector_id: z.string(),
  extraction_available: z.boolean(),
  planned_limits: z.record(z.string(), z.number()).nullable(),
  rows: eligibilityRowsSchema,
});

export type SourceIngestionEligibilityView = z.infer<typeof sourceIngestionEligibilityView>;

export function parseSourceIngestionEligibilityView(
  value: unknown,
): SourceIngestionEligibilityView {
  return parseContract(sourceIngestionEligibilityView, value);
}

const sourceExtractionBatchView = z.object({
  batch_key: z.string(),
  binding_id: z.string(),
  resource_name: z.string(),
  pinned_schema_fingerprint: z.string(),
  observed_schema_fingerprint: z.string(),
  ordering_mode: z.enum(["primary_key", "none"]),
  has_watermark: z.boolean(),
  row_count: z.number(),
  byte_size: z.number(),
  truncated: z.boolean(),
  limit_reason: z.string().nullable(),
  duration_ms: z.number(),
  digest_sha256: z.string(),
  storage_uri: z.string(),
  content_type: z.string(),
  stored_size_bytes: z.number(),
  classification: z.string(),
  executed_by: z.string(),
  created_at: z.string(),
});

const sourceExtractionBatchesPage = z.object({
  tenant_id: z.string(),
  connector_id: z.string(),
  request_id: z.string(),
  total_count: z.number(),
  next_cursor: z.string().nullable(),
  batches: z.array(sourceExtractionBatchView),
});

export type SourceExtractionBatchView = z.infer<typeof sourceExtractionBatchView>;
export type SourceExtractionBatchesPage = z.infer<typeof sourceExtractionBatchesPage>;

export function parseSourceExtractionBatchesPage(
  value: unknown,
): SourceExtractionBatchesPage {
  return parseContract(sourceExtractionBatchesPage, value);
}

const sourceExtractionReconciliationReport = z.object({
  tenant_id: z.string(),
  request_id: z.string(),
  dry_run: z.boolean(),
  clean_matches: z.number(),
  digest_mismatches: z.number(),
  missing_objects: z.number(),
  orphaned_objects: z.number(),
  findings: z.array(
    z.object({
      classification: z.enum([
        "clean_match",
        "digest_mismatch",
        "missing_object",
        "orphaned_object",
      ]),
      batch_key: z.string().nullable(),
      storage_key: z.string().nullable(),
    }),
  ),
});

export type SourceExtractionReconciliationReport = z.infer<
  typeof sourceExtractionReconciliationReport
>;

export function parseSourceExtractionReconciliationReport(
  value: unknown,
): SourceExtractionReconciliationReport {
  return parseContract(sourceExtractionReconciliationReport, value);
}

export function parseSourceIngestionRequestView(value: unknown): SourceIngestionRequestView {
  return parseContract(sourceIngestionRequestView, value);
}

export function parseSourceIngestionRequestViews(
  value: unknown,
): SourceIngestionRequestView[] {
  return parseContract(z.array(sourceIngestionRequestView), value);
}

const sourceIngestionOverviewSummary = z.object({
  status_counts: z.record(z.string(), z.number()),
  total_count: z.number(),
  dead_lettered_count: z.number(),
  extract_stage_count: z.number(),
  last_activity_at: z.string().nullable(),
});

const sourceIngestionOverview = z.object({
  tenant_id: z.string(),
  connector_id: z.string(),
  summary: sourceIngestionOverviewSummary,
  requests: z.array(sourceIngestionRequestView),
  next_cursor: z.string().nullable(),
});

export type SourceIngestionOverviewSummary = z.infer<typeof sourceIngestionOverviewSummary>;
export type SourceIngestionOverview = z.infer<typeof sourceIngestionOverview>;

export function parseSourceIngestionOverview(value: unknown): SourceIngestionOverview {
  return parseContract(sourceIngestionOverview, value);
}
