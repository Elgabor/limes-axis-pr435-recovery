import { z } from "zod";

import type {
  DataAssetCatalog,
  DataAssetResourcesView,
  DataAssetStewardshipView,
} from "../data-assets";
import {
  manufacturingProvenanceSchema,
  nullableStringSchema,
  overviewMetricSchema,
  parseContract,
  platformStatusSchema,
  stringArraySchema,
} from "./shared";

const dataAssetEvidenceSchema = z.enum([
  "sync_observed",
  "preview_only",
  "declared_only",
]);
const dataAssetGovernanceSchema = z.enum(["declared", "partial", "not_declared"]);
const dataAssetClassificationSchema = z.enum([
  "public",
  "internal",
  "confidential",
  "restricted",
]);
const dataAssetKindSchema = z.enum([
  "default",
  "table",
  "view",
  "file",
  "folder",
  "object_prefix",
  "topic",
  "api_resource",
  "document_collection",
]);
const dataAssetRegistryOriginSchema = z.enum(["reference", "persisted_manifest"]);

const dataAssetSchemaField = z.object({
  source_column: z.string(),
  target_field: z.string(),
  ontology_target: z.string(),
  data_type: z.string(),
  required: z.boolean(),
  description: z.string(),
});

const dataAssetSyncObservation = z.object({
  run_id: z.string(),
  completed_at: z.string(),
  records_read: z.number(),
});

const dataAssetStewardshipSummary = z.object({
  owner: z.string(),
  classification: dataAssetClassificationSchema,
  residency: z.string(),
  retention: z.string(),
  revision_number: z.number(),
});

const dataAssetStewardshipRecord = z.object({
  owner: z.string(),
  classification: dataAssetClassificationSchema,
  residency: z.string(),
  retention: z.string(),
  notes: stringArraySchema,
  revision_number: z.number(),
  declared_by: z.string(),
  declared_at: z.string(),
});

const dataAssetStewardshipView = z.object({
  tenant_id: z.string(),
  asset_id: z.string(),
  stewardship: dataAssetStewardshipRecord.nullable(),
});

const dataAssetResourceDriftSchema = z.enum(["added", "changed", "unchanged"]);

const dataAssetResourceObservation = z.object({
  resource_name: z.string(),
  schema_fingerprint: z.string().nullable(),
  previous_fingerprint: z.string().nullable(),
  drift_state: dataAssetResourceDriftSchema,
  first_seen_at: z.string(),
  last_seen_at: z.string(),
  observation_count: z.number(),
  observed_by: z.string(),
});

const dataAssetResourcesView = z.object({
  tenant_id: z.string(),
  asset_id: z.string(),
  resources: z.array(dataAssetResourceObservation),
  notes: stringArraySchema,
});

const dataAsset = z.object({
  asset_id: z.string(),
  tenant_id: z.string(),
  connector_id: z.string(),
  display_name: z.string(),
  kind: dataAssetKindSchema,
  evidence: dataAssetEvidenceSchema,
  governance: dataAssetGovernanceSchema,
  source_type: z.string(),
  connector_type: z.string(),
  runtime_boundary: z.string(),
  egress_policy: z.string(),
  payload_policy: z.string(),
  sync_modes: stringArraySchema,
  schema_fields: z.array(dataAssetSchemaField),
  ontology_targets: stringArraySchema,
  last_successful_sync: dataAssetSyncObservation.nullable(),
  registry_origin: dataAssetRegistryOriginSchema,
  manifest_revision: z.number().nullable(),
  notes: stringArraySchema,
  stewardship: dataAssetStewardshipSummary.nullable(),
  observed_resource_count: z.number().nullable(),
});

const dataAssetCatalog = z.object({
  tenant_id: z.string(),
  plant_name: nullableStringSchema,
  scenario: nullableStringSchema,
  provenance: manufacturingProvenanceSchema,
  catalog_status: platformStatusSchema,
  metrics: z.array(overviewMetricSchema),
  assets: z.array(dataAsset),
  notes: stringArraySchema,
});

/** Validate without transforming the response, preserving additive API fields. */
export function parseDataAssetCatalog(value: unknown): DataAssetCatalog {
  return parseContract(dataAssetCatalog, value);
}

/** Validate without transforming the response, preserving additive API fields. */
export function parseDataAssetStewardshipView(
  value: unknown,
): DataAssetStewardshipView {
  return parseContract(dataAssetStewardshipView, value);
}

/** Validate without transforming the response, preserving additive API fields. */
export function parseDataAssetResourcesView(
  value: unknown,
): DataAssetResourcesView {
  return parseContract(dataAssetResourcesView, value);
}

