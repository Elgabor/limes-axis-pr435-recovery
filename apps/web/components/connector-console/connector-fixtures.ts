import type {
  ConnectorRegistryItem,
  ManufacturingConnectorCredentialHandleRegistry,
  ManufacturingConnectorCredentialLeaseRegistry,
  ManufacturingConnectorEgressPolicyRegistry,
  ManufacturingConnectorEvidenceInvariantReport,
  ManufacturingConnectorManifestRegistry,
  ManufacturingConnectorOntologyProposalRegistry,
  ManufacturingConnectorRegistry,
  ManufacturingConnectorRunRegistry,
} from "@/lib/connectors-demo";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

const registryBase = {
  tenant_id: "tenant_demo_manufacturing",
  plant_name: "Ravenna Works",
  scenario: "Plant Operations Cockpit",
  provenance: "reference_scenario" as const,
  registry_status: "watch" as const,
  metrics: [],
};

export const csvConnectorFixture: ConnectorRegistryItem = {
  manifest: {
    connector_id: "file_csv_manufacturing_assets",
    display_name: "Manufacturing assets CSV",
    connector_type: "file_csv",
    version: "1.0.0",
    source_type: "csv_upload",
    sync_modes: ["preview"],
    runtime_boundary: "self_hosted",
    required_permissions: ["connectors:preview"],
    credential_requirements: {
      storage: "none",
      required_secret_refs: [],
      notes: [],
    },
    schema_fields: [
      {
        source_column: "asset_id",
        target_field: "node_id",
        ontology_target: "manufacturing_asset",
        data_type: "string",
        required: true,
        description: "Asset identifier",
      },
      {
        source_column: "asset_name",
        target_field: "display_name",
        ontology_target: "manufacturing_asset",
        data_type: "string",
        required: false,
        description: "Readable name",
      },
    ],
    mapping_notes: [],
  },
  runtime_policy: {
    allowed_operations: ["preview"],
    blocked_operations: ["live_query", "external_egress"],
    egress_policy: "no-external-egress",
    max_file_size_mb: 5,
    row_limit: 100,
    payload_policy: "metadata_only",
  },
  preview_sample: {
    file_name: "assets.csv",
    record_count: 2,
    headers: ["asset_id", "asset_name"],
    sample_rows: [
      { asset_id: "ast-1", asset_name: "CNC Mill" },
      { asset_id: "ast-2", asset_name: "Press" },
    ],
  },
  last_successful_sync: null,
  connector_status: "watch",
  registry_origin: "reference",
  persisted_manifest: {
    manifest_id: "manifest-1",
    revision_number: 2,
    status: "active_preview",
    registered_by: "plant-operations-owner-role",
    registered_at: "2026-07-10T08:00:00Z",
    notes: [],
  },
};

export const dbConnectorFixture: ConnectorRegistryItem = {
  ...csvConnectorFixture,
  manifest: {
    ...csvConnectorFixture.manifest,
    connector_id: "external_db_operational_mirror",
    display_name: "Operational mirror DB",
    connector_type: "external_db",
    source_type: "postgres_metadata",
  },
  preview_sample: {
    ...csvConnectorFixture.preview_sample!,
    file_name: "operations.production_orders",
  },
  persisted_manifest: null,
};

export const connectorRegistryFixture: ManufacturingConnectorRegistry = {
  ...registryBase,
  connectors: [csvConnectorFixture, dbConnectorFixture],
  connector_notes: [],
};

export const manifestRegistryFixture: ManufacturingConnectorManifestRegistry = {
  ...registryBase,
  manifests: [
    {
      tenant_id: registryBase.tenant_id,
      manifest_id: "manifest-1",
      connector_id: "file_csv_manufacturing_assets",
      revision_number: 2,
      display_name: "Manufacturing assets CSV",
      connector_type: "file_csv",
      source_type: "csv_upload",
      version: "1.0.0",
      status: "active_preview",
      runtime_boundary: "self_hosted",
      registered_by: "plant-operations-owner-role",
      manifest: csvConnectorFixture.manifest,
      runtime_policy: csvConnectorFixture.runtime_policy,
      preview_sample: csvConnectorFixture.preview_sample,
      audit_event_id: "audit-manifest-1",
      audit_event_type: "connector.manifest.registered",
      revises_revision_number: 1,
      replaced_by_revision_number: null,
      revision_idempotency_key: "fixture-revision-2",
      idempotent_replay: false,
      unchanged: false,
      notes: [],
      created_at: "2026-07-10T08:00:00Z",
    },
  ],
  manifest_notes: [],
};

export const manifestDetailFixture = {
  tenant_id: registryBase.tenant_id,
  connector_id: "file_csv_manufacturing_assets",
  current_revision: manifestRegistryFixture.manifests[0],
  revisions: [
    {
      ...manifestRegistryFixture.manifests[0],
      manifest_id: "manifest-0",
      revision_number: 1,
      version: "0.9.0",
      revises_revision_number: null,
      replaced_by_revision_number: 2,
      revision_idempotency_key: null,
      created_at: "2026-07-09T08:00:00Z",
    },
    manifestRegistryFixture.manifests[0],
  ],
  transitions: [],
};

export const credentialHandleRegistryFixture: ManufacturingConnectorCredentialHandleRegistry = {
  ...registryBase,
  handles: [
    {
      tenant_id: registryBase.tenant_id,
      connector_id: "file_csv_manufacturing_assets",
      handle_id: "handle_csv_readonly",
      display_name: "CSV read-only handle",
      status: "active",
      secret_provider: "vault",
      secret_ref: "vault://connectors/csv",
      purpose: "sync",
      rotation_interval_days: 30,
      rotation_status: "current",
      rotation_count: 1,
      last_rotated_at: "2026-07-01T00:00:00Z",
      next_rotation_due_at: "2026-07-31T00:00:00Z",
      created_by: "platform-owner",
      labels: {},
      notes: [],
      last_rotation: null,
    },
  ],
  handle_notes: [],
};

export const credentialLeaseRegistryFixture: ManufacturingConnectorCredentialLeaseRegistry = {
  ...registryBase,
  leases: [
    {
      tenant_id: registryBase.tenant_id,
      connector_id: "file_csv_manufacturing_assets",
      handle_id: "handle_csv_readonly",
      lease_id: "lease_csv_active",
      status: "active",
      lease_mode: "read_only",
      runtime_boundary: "self_hosted",
      requested_by: "sync-worker",
      lease_purpose: "preview-sync",
      secret_provider: "vault",
      secret_ref: "vault://connectors/csv",
      vault_kms_policy: {},
      permission_decision: { allowed: true, reason: "scope_present" },
      lease_result: {},
      granted_at: "2026-07-11T00:00:00Z",
      expires_at: "2999-01-01T00:00:00Z",
      renewal_due_at: "2999-01-01T00:00:00Z",
      renewed_at: null,
      renewed_by: null,
      renewal_count: 0,
      revoked_at: null,
      revoked_by: null,
      revocation_reason: null,
      audit_event_id: "audit-lease-1",
      audit_event_type: "connector.credential.lease_granted",
      notes: [],
      created_at: "2026-07-11T00:00:00Z",
    },
  ],
  lease_evidence_invariants: [],
  lease_notes: [],
};

export const egressPolicyRegistryFixture: ManufacturingConnectorEgressPolicyRegistry = {
  ...registryBase,
  policies: [
    {
      tenant_id: registryBase.tenant_id,
      connector_id: "external_db_operational_mirror",
      policy_id: "egress_ops_mirror",
      display_name: "Ops mirror private endpoint",
      status: "active",
      connection_profile_id: "profile_postgres_ops_readonly",
      egress_boundary: "private_endpoint",
      policy_mode: "enforced",
      runtime_boundary: "self_hosted",
      private_endpoint_ref: "pe://ops-mirror",
      created_by: "platform-owner",
      policy_document: {},
      evidence_refs: [],
      audit_event_id: "audit-egress-1",
      audit_event_type: "connector.egress_policy.recorded",
      notes: [],
      created_at: "2026-07-10T00:00:00Z",
    },
  ],
  policy_evidence_invariants: [],
  policy_notes: [],
};

export const runRegistryFixture: ManufacturingConnectorRunRegistry = {
  ...registryBase,
  runs: [
    {
      tenant_id: registryBase.tenant_id,
      connector_id: "file_csv_manufacturing_assets",
      run_id: "run_seeded_1",
      status: "sync_schedule_deferred",
      execution_mode: "scheduled_sync_plan",
      runtime_boundary: "self_hosted",
      requested_by: "plant-operations-owner-role",
      credential_handle_ids: ["handle_csv_readonly"],
      input_summary: {},
      result_summary: {},
      execution_result: null,
      schedule_result: {
        adapter: "deferred-sync-scheduler",
        status: "sync_schedule_deferred",
        schedule_ref: "sched://deferred",
        external_sync_started: false,
        idempotency_key: "idem_sched_1",
        result_summary: {},
        notes: [],
      },
      dispatch_result: null,
      sync_execution_result: null,
      audit_event_id: "audit-run-1",
      audit_event_type: "connector.sync.schedule_recorded",
      notes: [],
      created_at: "2026-07-11T07:00:00Z",
    },
  ],
  run_notes: [],
};

export const evidenceInvariantReportFixture: ManufacturingConnectorEvidenceInvariantReport = {
  ...registryBase,
  invariant_counts: {
    checkpoint: 0,
    checkpoint_claim: 0,
    credential_lease: 1,
    egress_policy: 0,
  },
  invariants: [
    {
      evidence_type: "credential_lease",
      subject_id: "lease_csv_active",
      parent_id: null,
      audit_event_id: null,
      reason: "missing_audit_event",
      detail: "Credential lease lease_csv_active has no linked audit event.",
    },
  ],
  report_notes: [],
};

export const ontologyProposalRegistryFixture: ManufacturingConnectorOntologyProposalRegistry = {
  ...registryBase,
  proposals: [
    {
      tenant_id: registryBase.tenant_id,
      connector_id: "file_csv_manufacturing_assets",
      proposal_id: "proposal_1",
      source_run_id: null,
      source_file_name: "assets.csv",
      mapping_profile: "default",
      status: "proposed",
      write_mode: "proposal_only",
      graph_mutation_status: "not_requested",
      proposed_by: "connector-preview-service",
      node_id: "ast-1",
      node_type: "asset",
      ontology_type: "manufacturing_asset",
      field_summary: {},
      evidence_refs: [],
      promotion_id: null,
      policy_id: null,
      policy_set_id: null,
      policy_ids: null,
      policy_decision: null,
      promoted_by: null,
      promoted_at: null,
      ontology_mutation: null,
      audit_event_id: null,
      audit_event_type: "connector.ontology.proposal_recorded",
      notes: [],
      created_at: "2026-07-11T06:00:00Z",
    },
  ],
  proposal_notes: [],
};

/** Path → fixture payload map matching CONNECTOR_ENDPOINTS. */
export const connectorEndpointFixtures: Record<string, unknown> = {
  [`${OPERATIONS_API_PREFIX}/connectors`]: connectorRegistryFixture,
  [`${OPERATIONS_API_PREFIX}/connectors/manifests`]: manifestRegistryFixture,
  [`${OPERATIONS_API_PREFIX}/connectors/manifests/file_csv_manufacturing_assets`]:
    manifestDetailFixture,
  [`${OPERATIONS_API_PREFIX}/connectors/credential-handles`]: credentialHandleRegistryFixture,
  [`${OPERATIONS_API_PREFIX}/connectors/credential-leases`]: credentialLeaseRegistryFixture,
  [`${OPERATIONS_API_PREFIX}/connectors/egress-policies`]: egressPolicyRegistryFixture,
  [`${OPERATIONS_API_PREFIX}/connectors/runs`]: runRegistryFixture,
  [`${OPERATIONS_API_PREFIX}/connectors/evidence-invariants?tenant_id=tenant_demo_manufacturing`]:
    evidenceInvariantReportFixture,
  [`${OPERATIONS_API_PREFIX}/connectors/ontology-proposals`]: ontologyProposalRegistryFixture,
};
