import { z } from "zod";

import type { DataAssetCatalog } from "../data-assets";
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

