import type { ManufacturingProvenance, PlatformStatus } from "./platform-overview";

export type ConnectorCredentialRequirements = {
  storage: string;
  required_secret_refs: string[];
  notes: string[];
};

export type ConnectorSchemaField = {
  source_column: string;
  target_field: string;
  ontology_target: string;
  data_type: string;
  required: boolean;
  description: string;
};

export type ConnectorManifest = {
  connector_id: string;
  display_name: string;
  connector_type: string;
  version: string;
  source_type: string;
  sync_modes: string[];
  runtime_boundary: string;
  required_permissions: string[];
  credential_requirements: ConnectorCredentialRequirements;
  schema_fields: ConnectorSchemaField[];
  mapping_notes: string[];
};

export type ConnectorRuntimePolicy = {
  allowed_operations: string[];
  blocked_operations: string[];
  egress_policy: string;
  max_file_size_mb: number;
  row_limit: number;
  payload_policy: string;
};

export type ConnectorPreviewSample = {
  file_name: string;
  record_count: number;
  headers: string[];
  sample_rows: Record<string, string>[];
};

export type ConnectorSyncObservation = {
  run_id: string;
  completed_at: string;
  records_read: number;
};

export type ConnectorRegistryOrigin = "reference" | "persisted_manifest";

export type ConnectorPersistedManifestSummary = {
  manifest_id: string;
  revision_number: number;
  status: string;
  registered_by: string;
  registered_at: string;
  notes: string[];
};

export type ConnectorRegistryItem = {
  manifest: ConnectorManifest;
  runtime_policy: ConnectorRuntimePolicy;
  preview_sample: ConnectorPreviewSample | null;
  last_successful_sync: ConnectorSyncObservation | null;
  connector_status: PlatformStatus;
  registry_origin: ConnectorRegistryOrigin;
  persisted_manifest: ConnectorPersistedManifestSummary | null;
};

export type ManufacturingConnectorRegistry = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  registry_status: PlatformStatus;
  metrics: {
    label: string;
    value: string;
    detail: string;
    status: PlatformStatus;
  }[];
  connectors: ConnectorRegistryItem[];
  connector_notes: string[];
};

export type ConnectorManifestRecord = {
  tenant_id: string;
  manifest_id: string;
  connector_id: string;
  revision_number: number;
  display_name: string;
  connector_type: string;
  source_type: string;
  version: string;
  status: string;
  runtime_boundary: string;
  registered_by: string;
  manifest: ConnectorManifest;
  runtime_policy: ConnectorRuntimePolicy;
  preview_sample: ConnectorPreviewSample | null;
  audit_event_id: string | null;
  audit_event_type: string;
  revises_revision_number: number | null;
  replaced_by_revision_number: number | null;
  revision_idempotency_key: string | null;
  idempotent_replay: boolean;
  unchanged: boolean;
  notes: string[];
  created_at: string;
};

export type ConnectorManifestDetail = {
  tenant_id: string;
  connector_id: string;
  current_revision: ConnectorManifestRecord;
  revisions: ConnectorManifestRecord[];
};

export type ManufacturingConnectorManifestRegistry = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  registry_status: PlatformStatus;
  metrics: {
    label: string;
    value: string;
    detail: string;
    status: PlatformStatus;
  }[];
  manifests: ConnectorManifestRecord[];
  manifest_notes: string[];
};

export type ConnectorCsvPreviewRequest = {
  tenant_id: string;
  connector_id: string;
  file_name: string;
  csv_content: string;
};

export type ConnectorExternalDbPreviewRequest = {
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

export type ProposedOntologyEntity = {
  node_id: string;
  node_type: string;
  ontology_type: string;
  field_summary: Record<string, string>;
  evidence_refs: string[];
};

export type ConnectorAuditEventPreview = {
  event_type: string;
  scope: string;
  actor_id: string;
  result: string;
  evidence_refs: string[];
  payload_preview: Record<string, string>;
};

export type ConnectorCsvPreviewResult = {
  tenant_id: string;
  connector_id: string;
  file_name: string;
  preview_status: string;
  sync_mode: string;
  record_count: number;
  accepted_record_count: number;
  rejected_record_count: number;
  validation_issues: string[];
  proposed_entities: ProposedOntologyEntity[];
  audit_event_preview: ConnectorAuditEventPreview;
  preview_notes: string[];
};

export type ConnectorExternalDbColumnPreview = {
  source_column: string;
  target_field: string;
  ontology_target: string;
  data_type: string;
  nullable: boolean;
};

export type ConnectorExternalDbTablePreview = {
  schema_name: string;
  table_name: string;
  table_ref: string;
  record_count_estimate: string;
  sample_limit: number;
  columns: ConnectorExternalDbColumnPreview[];
  sample_rows: Record<string, string>[];
};

export type ConnectorExternalDbPreviewResult = {
  tenant_id: string;
  connector_id: string;
  connection_profile_id: string;
  source_type: string;
  preview_status: string;
  sync_mode: string;
  live_query_executed: boolean;
  validation_issues: string[];
  inspected_table: ConnectorExternalDbTablePreview;
  proposed_entities: ProposedOntologyEntity[];
  audit_event_preview: ConnectorAuditEventPreview;
  preview_notes: string[];
};

export type ConnectorCredentialRotation = {
  tenant_id: string;
  handle_id: string;
  rotated_by: string;
  rotated_at: string;
  evidence_ref: string;
  status: string;
  notes: string[];
};

export type ConnectorCredentialHandle = {
  tenant_id: string;
  connector_id: string;
  handle_id: string;
  display_name: string;
  status: string;
  secret_provider: string;
  secret_ref: string;
  purpose: string;
  rotation_interval_days: number;
  rotation_status: string;
  rotation_count: number;
  last_rotated_at: string | null;
  next_rotation_due_at: string | null;
  created_by: string;
  labels: Record<string, string>;
  notes: string[];
  last_rotation: ConnectorCredentialRotation | null;
};

export type ManufacturingConnectorCredentialHandleRegistry = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  registry_status: PlatformStatus;
  metrics: {
    label: string;
    value: string;
    detail: string;
    status: PlatformStatus;
  }[];
  handles: ConnectorCredentialHandle[];
  handle_notes: string[];
};

export type ConnectorCredentialLeaseRecord = {
  tenant_id: string;
  connector_id: string;
  handle_id: string;
  lease_id: string;
  status: string;
  lease_mode: string;
  runtime_boundary: string;
  requested_by: string;
  lease_purpose: string;
  secret_provider: string;
  secret_ref: string;
  vault_kms_policy: Record<string, string>;
  permission_decision: {
    allowed: boolean;
    reason: string;
  };
  lease_result: Record<string, string>;
  granted_at: string;
  expires_at: string;
  renewal_due_at: string;
  renewed_at: string | null;
  renewed_by: string | null;
  renewal_count: number;
  revoked_at: string | null;
  revoked_by: string | null;
  revocation_reason: string | null;
  audit_event_id: string | null;
  audit_event_type: string;
  notes: string[];
  created_at: string;
};

export type ConnectorCredentialLeaseEvidenceInvariant = {
  lease_id: string;
  audit_event_id: string | null;
  reason: string;
  detail: string;
};

export type ManufacturingConnectorCredentialLeaseRegistry = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  registry_status: PlatformStatus;
  metrics: {
    label: string;
    value: string;
    detail: string;
    status: PlatformStatus;
  }[];
  leases: ConnectorCredentialLeaseRecord[];
  lease_evidence_invariants: ConnectorCredentialLeaseEvidenceInvariant[];
  lease_notes: string[];
};

export type ConnectorEgressPolicyRecord = {
  tenant_id: string;
  connector_id: string;
  policy_id: string;
  display_name: string;
  status: string;
  connection_profile_id: string;
  egress_boundary: string;
  policy_mode: string;
  runtime_boundary: string;
  private_endpoint_ref: string;
  created_by: string;
  policy_document: Record<string, string>;
  evidence_refs: string[];
  audit_event_id: string | null;
  audit_event_type: string;
  notes: string[];
  created_at: string;
};

export type ConnectorEgressPolicyEvidenceInvariant = {
  policy_id: string;
  audit_event_id: string | null;
  reason: string;
  detail: string;
};

export type ManufacturingConnectorEgressPolicyRegistry = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  registry_status: PlatformStatus;
  metrics: {
    label: string;
    value: string;
    detail: string;
    status: PlatformStatus;
  }[];
  policies: ConnectorEgressPolicyRecord[];
  policy_evidence_invariants: ConnectorEgressPolicyEvidenceInvariant[];
  policy_notes: string[];
};

export type ConnectorRunRecord = {
  tenant_id: string;
  connector_id: string;
  run_id: string;
  status: string;
  execution_mode: string;
  runtime_boundary: string;
  requested_by: string;
  credential_handle_ids: string[];
  input_summary: Record<string, string>;
  result_summary: Record<string, unknown>;
  execution_result: ConnectorExecutionResult | null;
  schedule_result: ConnectorSyncScheduleResult | null;
  dispatch_result: ConnectorSyncDispatchResult | null;
  sync_execution_result: ConnectorSyncExecutionResult | null;
  audit_event_id: string | null;
  audit_event_type: string;
  notes: string[];
  created_at: string;
};

export type ConnectorExecutionResult = {
  adapter: string;
  status: string;
  external_sync_started: boolean;
  idempotency_key: string;
  result_summary: Record<string, string>;
  notes: string[];
};

export type ConnectorSyncScheduleResult = {
  adapter: string;
  status: string;
  schedule_ref: string;
  external_sync_started: boolean;
  idempotency_key: string;
  result_summary: Record<string, string>;
  notes: string[];
};

export type ConnectorSyncDispatchResult = {
  adapter: string;
  status: string;
  dispatch_ref: string;
  external_sync_started: boolean;
  idempotency_key: string;
  result_summary: Record<string, string>;
  notes: string[];
};

export type ConnectorSyncExecutionResult = {
  adapter: string;
  status: string;
  sync_ref: string;
  external_sync_started: boolean;
  idempotency_key: string;
  result_summary: Record<string, string>;
  notes: string[];
};

export type ManufacturingConnectorRunRegistry = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  registry_status: PlatformStatus;
  metrics: {
    label: string;
    value: string;
    detail: string;
    status: PlatformStatus;
  }[];
  runs: ConnectorRunRecord[];
  run_notes: string[];
};

export type ConnectorEvidenceInvariantType =
  | "checkpoint"
  | "checkpoint_claim"
  | "credential_lease"
  | "egress_policy";

export type ConnectorEvidenceInvariantItem = {
  evidence_type: ConnectorEvidenceInvariantType;
  subject_id: string;
  parent_id: string | null;
  audit_event_id: string | null;
  reason: string;
  detail: string;
};

export type ManufacturingConnectorEvidenceInvariantReport = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  registry_status: PlatformStatus;
  metrics: {
    label: string;
    value: string;
    detail: string;
    status: PlatformStatus;
  }[];
  invariant_counts: Record<ConnectorEvidenceInvariantType, number>;
  invariants: ConnectorEvidenceInvariantItem[];
  report_notes: string[];
};

export type ConnectorEvidenceInvariantSnapshotRecord = {
  tenant_id: string;
  snapshot_id: string;
  status: string;
  connector_id: string | null;
  requested_by: string;
  idempotency_key: string;
  reason: string;
  invariant_count: number;
  invariant_counts: Record<string, number>;
  subject_ids: string[];
  report_digest_sha256: string;
  report_hash_algorithm: string;
  permission_decision: {
    allowed: boolean;
    reason: string;
  };
  audit_event_id: string | null;
  audit_event_type: string;
  idempotent_replay: boolean;
  notes: string[];
};

export type ManufacturingConnectorEvidenceInvariantSnapshotHistory = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  history_status: PlatformStatus;
  metrics: {
    label: string;
    value: string;
    detail: string;
    status: PlatformStatus;
  }[];
  snapshots: ConnectorEvidenceInvariantSnapshotRecord[];
  history_notes: string[];
};

type ConnectorSnapshotHrefInput = {
  snapshotId: string | null | undefined;
  connectorId?: string | null | undefined;
};

export type ConnectorOntologyProposalRecord = {
  tenant_id: string;
  connector_id: string;
  proposal_id: string;
  source_run_id: string | null;
  source_file_name: string;
  mapping_profile: string;
  status: string;
  write_mode: string;
  graph_mutation_status: string;
  proposed_by: string;
  node_id: string;
  node_type: string;
  ontology_type: string;
  field_summary: Record<string, string>;
  evidence_refs: string[];
  promotion_id: string | null;
  policy_id: string | null;
  policy_set_id: string | null;
  policy_ids: string[] | null;
  policy_decision: ConnectorPromotionPolicyDecision | null;
  promoted_by: string | null;
  promoted_at: string | null;
  ontology_mutation: {
    status: string;
    adapter: string;
    mutation_ref: string | null;
    typeql: string | null;
    payload: Record<string, unknown>;
  } | null;
  audit_event_id: string | null;
  audit_event_type: string;
  notes: string[];
  created_at: string;
};

export type ConnectorPromotionPolicyDecision = {
  status: string;
  allowed: boolean;
  policy_id: string | null;
  policy_version: string | null;
  policy_set_id: string | null;
  policy_set_version: string | null;
  policy_ids: string[];
  policy_results: Record<string, unknown>[];
  enforcement_mode: string;
  reason: string;
  required_scopes: string[];
  matched_constraints: Record<string, string>;
};

export type ManufacturingConnectorOntologyProposalRegistry = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  registry_status: PlatformStatus;
  metrics: {
    label: string;
    value: string;
    detail: string;
    status: PlatformStatus;
  }[];
  proposals: ConnectorOntologyProposalRecord[];
  proposal_notes: string[];
};

export function buildConnectorSnapshotHref(input: ConnectorSnapshotHrefInput): string {
  if (!input.snapshotId) {
    return "/connectors";
  }

  const params = new URLSearchParams({ snapshot_id: input.snapshotId });
  if (input.connectorId) {
    params.set("connector_id", input.connectorId);
  }

  return `/connectors?${params.toString()}`;
}

export function formatConnectorLabel(value: string): string {
  return value
    .split(/[._:-]/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
