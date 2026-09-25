import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DataAssetCatalog } from "@/lib/data-assets";
import { strings } from "@/lib/strings";

const mocks = vi.hoisted(() => ({
  setUrlState: vi.fn(),
  triggerRefresh: vi.fn(),
  urlState: { assetId: "", evidence: "all", q: "" },
  useDataAssetCatalog: vi.fn(),
  useDataAssetStewardship: vi.fn(),
}));

vi.mock("@/lib/use-console-tenant-scope", () => ({
  useConsoleTenantScope: () => ({
    tenantId: "tenant_demo_manufacturing",
    tenantQueriesEnabled: true,
  }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({
    refreshNonce: 0,
    triggerRefresh: mocks.triggerRefresh,
  }),
}));

vi.mock("@/lib/use-data-asset-catalog", () => ({
  DATA_ASSET_ENDPOINTS: { assets: "/data/assets" },
  useDataAssetCatalog: mocks.useDataAssetCatalog,
}));

vi.mock("@/lib/use-data-asset-stewardship", () => ({
  DATA_ASSET_STEWARDSHIP_ENDPOINTS: { stewardship: "/data/assets/stewardship" },
  useDataAssetStewardship: mocks.useDataAssetStewardship,
}));

vi.mock("@/lib/console-url-state", () => ({
  enumUrlField: vi.fn(
    (param: string, _values: readonly string[], fallback: string) => ({
      defaultValue: fallback,
      param,
    }),
  ),
  opaqueStringUrlField: vi.fn((param: string) => ({ defaultValue: "", param })),
  stringUrlField: vi.fn((param: string) => ({ defaultValue: "", param })),
  useConsoleUrlState: () => [mocks.urlState, mocks.setUrlState],
}));

import { DataCatalog } from "./index";

function catalogFixture(overrides: Partial<DataAssetCatalog> = {}): DataAssetCatalog {
  return {
    tenant_id: "tenant_demo_manufacturing",
    plant_name: "Ravenna Works",
    scenario: null,
    provenance: "reference_scenario",
    catalog_status: "ready",
    metrics: [
      {
        label: "Data Assets",
        value: "2",
        detail: "Connector-level assets projected into the catalog",
        status: "ready",
      },
      {
        label: "Stewardship Gaps",
        value: "2",
        detail: "Assets without fully declared stewardship",
        status: "action_required",
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
        sync_modes: ["preview"],
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
        observed_resource_count: null,
        notes: [],
        stewardship: null,
      },
      {
        asset_id: "source:external_db_operational_mirror:default",
        tenant_id: "tenant_demo_manufacturing",
        connector_id: "external_db_operational_mirror",
        display_name: "Operational DB mirror",
        kind: "default",
        evidence: "declared_only",
        governance: "not_declared",
        source_type: "database",
        connector_type: "external_db",
        runtime_boundary: "axis-connector-sandbox",
        egress_policy: "no-external-egress",
        payload_policy: "metadata-only",
        sync_modes: [],
        schema_fields: [],
        ontology_targets: [],
        last_successful_sync: null,
        registry_origin: "persisted_manifest",
        manifest_revision: 3,
        observed_resource_count: 0,
        notes: [],
        stewardship: null,
      },
    ],
    notes: [],
    ...overrides,
  };
}

function loadedCatalog(data: DataAssetCatalog | null) {
  return {
    data,
    error: null,
    errorRequestId: null,
    isLoading: false,
  };
}

beforeEach(() => {
  mocks.urlState = { assetId: "", evidence: "all", q: "" };
  mocks.setUrlState.mockClear();
  mocks.useDataAssetStewardship.mockReset();
  mocks.useDataAssetStewardship.mockReturnValue({
    data: null,
    error: null,
    errorRequestId: null,
    isLoading: false,
  });
});

describe("DataCatalog", () => {
  it("renders the loading state before the catalog resolves", () => {
    mocks.useDataAssetCatalog.mockReturnValue({
      data: null,
      error: null,
      errorRequestId: null,
      isLoading: true,
    });

    render(<DataCatalog />);

    expect(screen.getByRole("status", { name: "Loading content" })).toBeInTheDocument();
  });

  it("renders a fail-closed error state without inventing assets", async () => {
    const user = userEvent.setup();
    mocks.useDataAssetCatalog.mockReturnValue({
      data: null,
      error: "boom",
      errorRequestId: "req-1",
      isLoading: false,
    });

    render(<DataCatalog />);

    expect(
      screen.getByRole("heading", { name: strings.dataCatalog.states.error.title }),
    ).toBeInTheDocument();
    await user.click(screen.getByText(strings.states.technicalDetails));
    expect(screen.getByText("req-1")).toBeInTheDocument();
  });

  it("renders the empty state for a tenant without assets", () => {
    mocks.useDataAssetCatalog.mockReturnValue(
      loadedCatalog(catalogFixture({ assets: [] })),
    );

    render(<DataCatalog />);

    expect(screen.getByText(strings.dataCatalog.states.empty.title)).toBeInTheDocument();
  });

  it("renders assets with master/detail selection and URL-backed select", async () => {
    const user = userEvent.setup();
    mocks.useDataAssetCatalog.mockReturnValue(loadedCatalog(catalogFixture()));

    render(<DataCatalog />);

    const csvButton = screen.getByRole("button", {
      name: /Manufacturing assets CSV/,
    });
    expect(csvButton).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getAllByText("source:file_csv_manufacturing_assets:default").length,
    ).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: /Operational DB mirror/ }));

    expect(mocks.setUrlState).toHaveBeenCalledWith(
      { assetId: "source:external_db_operational_mirror:default" },
      { history: "push" },
    );
  });

  it("fails closed on an unknown deep-linked asset id", () => {
    mocks.urlState = {
      assetId: "source:not_a_real_asset:default",
      evidence: "all",
      q: "",
    };
    mocks.useDataAssetCatalog.mockReturnValue(loadedCatalog(catalogFixture()));

    render(<DataCatalog />);

    expect(
      screen.getByText(strings.dataCatalog.states.unknownAsset.title),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("source:file_csv_manufacturing_assets:default"),
    ).not.toBeInTheDocument();
  });

  it("filters the list by the URL-backed search text", () => {
    mocks.urlState = { assetId: "", evidence: "all", q: "mirror" };
    mocks.useDataAssetCatalog.mockReturnValue(loadedCatalog(catalogFixture()));

    render(<DataCatalog />);

    expect(
      screen.getByRole("button", { name: /Operational DB mirror/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Manufacturing assets CSV/ }),
    ).not.toBeInTheDocument();
  });

  it("wires search and evidence edits to the URL state", async () => {
    const user = userEvent.setup();
    mocks.useDataAssetCatalog.mockReturnValue(loadedCatalog(catalogFixture()));

    render(<DataCatalog />);
    await user.type(screen.getByLabelText("Search data assets"), "m");

    expect(mocks.setUrlState).toHaveBeenCalledWith({ q: "m", assetId: "" });
  });

  it.each(["search", "evidence"])("selects a matching asset after changing %s with another asset selected", (filter) => {
    mocks.urlState.assetId = "source:file_csv_manufacturing_assets:default";
    mocks.useDataAssetCatalog.mockReturnValue(loadedCatalog(catalogFixture()));
    const { rerender } = render(<DataCatalog />);

    if (filter === "search") {
      fireEvent.change(screen.getByLabelText("Search data assets"), { target: { value: "mirror" } });
    } else {
      fireEvent.change(screen.getByRole("combobox"), { target: { value: "declared_only" } });
    }
    const patch = mocks.setUrlState.mock.calls.at(-1)?.[0];
    expect(patch).toMatchObject({ assetId: "" });
    mocks.urlState = { ...mocks.urlState, ...patch };
    rerender(<DataCatalog />);

    expect(screen.getByRole("button", { name: /Operational DB mirror/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("button", { name: /Manufacturing assets CSV/ })).not.toBeInTheDocument();
    expect(screen.queryByText(strings.dataCatalog.states.noMatches.title)).not.toBeInTheDocument();
  });
});
