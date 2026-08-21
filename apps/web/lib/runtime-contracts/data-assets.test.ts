import { describe, expect, it } from "vitest";

import { parseDataAssetCatalog, parseDataAssetStewardshipView } from "./data-assets";

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
        stewardship: {
          classification: "internal",
          owner: "plant-operations-owner-role",
          residency: "eu-south",
          retention: "7y",
          revision_number: 2,
        },
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

  it("accepts an asset with a stewardship summary and preserves its additive fields", () => {
    const payload = catalogFixture();
    (payload.assets[0] as { stewardship: unknown }).stewardship = {
      classification: "restricted",
      future_summary_field: true,
      owner: "data-platform-team",
      residency: "eu-south",
      retention: "10y",
      revision_number: 4,
    };

    const parsed = parseDataAssetCatalog(payload);

    expect(parsed.assets[0]?.stewardship).toEqual({
      classification: "restricted",
      future_summary_field: true,
      owner: "data-platform-team",
      residency: "eu-south",
      retention: "10y",
      revision_number: 4,
    });
  });

  it("rejects an unknown stewardship summary classification", () => {
    const payload = catalogFixture();
    const asset = payload.assets[0];
    if (!asset.stewardship) {
      throw new Error("fixture must carry a stewardship summary");
    }
    asset.stewardship.classification = "top_secret";

    expect(() => parseDataAssetCatalog(payload)).toThrow();
  });

  it("rejects an asset without the stewardship key", () => {
    const payload = catalogFixture();
    delete (payload.assets[0] as { stewardship?: unknown }).stewardship;

    expect(() => parseDataAssetCatalog(payload)).toThrow();
  });
});

describe("parseDataAssetStewardshipView", () => {
  function stewardshipViewFixture() {
    return {
      asset_id: "source:file_csv_manufacturing_assets:default",
      future_view_field: { nested: true },
      stewardship: {
        asset_id: "ignored_additive_field",
        classification: "confidential",
        declared_at: "2026-08-21T09:30:00Z",
        declared_by: "plant-operations-owner-role",
        notes: ["Personal data present."],
        owner: "data-platform-team",
        residency: "eu-south",
        retention: "7y",
        revision_number: 3,
      },
      tenant_id: "tenant_demo_manufacturing",
    };
  }

  it("accepts a valid declared view and preserves additive fields", () => {
    const parsed = parseDataAssetStewardshipView(stewardshipViewFixture());

    expect(parsed.tenant_id).toBe("tenant_demo_manufacturing");
    expect(parsed.asset_id).toBe("source:file_csv_manufacturing_assets:default");
    expect(parsed.stewardship?.owner).toBe("data-platform-team");
    expect(parsed.stewardship?.classification).toBe("confidential");
    expect(parsed.stewardship?.revision_number).toBe(3);
    expect(
      (parsed as Record<string, unknown>).future_view_field,
    ).toEqual({ nested: true });
  });

  it("accepts an undeclared view with a null stewardship record", () => {
    const payload = stewardshipViewFixture();
    (payload as { stewardship: unknown }).stewardship = null;

    const parsed = parseDataAssetStewardshipView(payload);

    expect(parsed.stewardship).toBeNull();
  });

  it("rejects an unknown stewardship classification", () => {
    const payload = stewardshipViewFixture();
    if (!payload.stewardship) {
      throw new Error("fixture must carry a stewardship record");
    }
    payload.stewardship.classification = "secret";

    expect(() => parseDataAssetStewardshipView(payload)).toThrow();
  });

  it("rejects a missing tenant_id", () => {
    const payload = stewardshipViewFixture();
    delete (payload as { tenant_id?: unknown }).tenant_id;

    expect(() => parseDataAssetStewardshipView(payload)).toThrow();
  });
});
