import { describe, expect, it } from "vitest";

import { parseDataAssetCatalog } from "./data-assets";

function catalogFixture() {
  return {
    tenant_id: "tenant_demo_manufacturing",
    plant_name: "Ravenna Works",
    scenario: "Plant Operations Cockpit",
    provenance: "reference_scenario",
    catalog_status: "ready",
    metrics: [
      {
        label: "Data Assets",
        value: "1",
        detail: "Connector-level assets projected into the catalog",
        status: "ready",
      },
    ],
    assets: [
      {
        asset_id: "source:file_csv_manufacturing_assets:default",
        tenant_id: "tenant_demo_manufacturing",
        connector_id: "file_csv_manufacturing_assets",
        display_name: "Manufacturing assets CSV",
        kind: "default",
        evidence: "sync_observed",
        governance: "partial",
        source_type: "file",
        connector_type: "file_csv",
        runtime_boundary: "axis-connector-sandbox",
        egress_policy: "no-external-egress",
        payload_policy: "metadata-only",
        sync_modes: ["preview", "manual_import"],
        schema_fields: [
          {
            source_column: "asset_id",
            target_field: "node_id",
            ontology_target: "manufacturing_asset",
            data_type: "string",
            required: true,
            description: "Asset identifier.",
          },
        ],
        ontology_targets: ["manufacturing_asset"],
        last_successful_sync: {
          run_id: "run_catalog_001",
          completed_at: "2026-08-21T10:00:00Z",
          records_read: 42,
        },
        registry_origin: "reference",
        manifest_revision: null,
        notes: ["Sync observation present."],
      },
    ],
    notes: ["Metadata-only catalog."],
  };
}

describe("parseDataAssetCatalog", () => {
  it("accepts a valid API payload and preserves additive fields", () => {
    const payload = {
      ...catalogFixture(),
      future_field: { nested: true },
    };

    const parsed = parseDataAssetCatalog(payload);

    expect(parsed.assets).toHaveLength(1);
    expect(parsed.assets[0]?.asset_id).toBe(
      "source:file_csv_manufacturing_assets:default",
    );
    expect((parsed as Record<string, unknown>).future_field).toEqual({ nested: true });
  });

  it("rejects an unknown evidence state", () => {
    const payload = catalogFixture();
    payload.assets[0].evidence = "materialized";

    expect(() => parseDataAssetCatalog(payload)).toThrow();
  });

  it("rejects an unknown governance state", () => {
    const payload = catalogFixture();
    payload.assets[0].governance = "invented";

    expect(() => parseDataAssetCatalog(payload)).toThrow();
  });

  it("rejects a missing metrics array", () => {
    const payload = catalogFixture();
    delete (payload as { metrics?: unknown }).metrics;

    expect(() => parseDataAssetCatalog(payload)).toThrow();
  });
});
