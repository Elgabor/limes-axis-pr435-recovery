/**
 * Data Asset Catalog domain types: the governed layer between connectors and
 * the ontology. Mirrors the API contract in
 * `services/api/src/axis_api/data_assets.py` one-to-one; the catalog is
 * metadata-only by contract, so no type here can carry source rows.
 */

export type DataAssetEvidenceState =
  | "sync_observed"
  | "preview_only"
  | "declared_only";

export type DataAssetGovernanceState = "declared" | "partial" | "not_declared";

export type DataAssetKind =
  | "default"
  | "table"
  | "view"
  | "file"
  | "folder"
  | "object_prefix"
  | "topic"
  | "api_resource"
  | "document_collection";

export type DataAssetRegistryOrigin = "reference" | "persisted_manifest";

export type DataAssetSchemaField = {
  source_column: string;
  target_field: string;
  ontology_target: string;
  data_type: string;
  required: boolean;
  description: string;
};

export type DataAssetSyncObservation = {
  run_id: string;
  completed_at: string;
  records_read: number;
};

export type DataAsset = {
  asset_id: string;
  tenant_id: string;
  connector_id: string;
  display_name: string;
  kind: DataAssetKind;
  evidence: DataAssetEvidenceState;
  governance: DataAssetGovernanceState;
  source_type: string;
  connector_type: string;
  runtime_boundary: string;
  egress_policy: string;
  payload_policy: string;
  sync_modes: string[];
  schema_fields: DataAssetSchemaField[];
  ontology_targets: string[];
  last_successful_sync: DataAssetSyncObservation | null;
  registry_origin: DataAssetRegistryOrigin;
  manifest_revision: number | null;
  notes: string[];
};

export type DataAssetCatalogMetric = {
  label: string;
  value: string;
  detail: string;
  status: "ready" | "watch" | "action_required";
};

export type DataAssetCatalogProvenance =
  | "reference_scenario"
  | "live"
  | "empty";

export type DataAssetCatalog = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: DataAssetCatalogProvenance;
  catalog_status: "ready" | "watch" | "action_required";
  metrics: DataAssetCatalogMetric[];
  assets: DataAsset[];
  notes: string[];
};
