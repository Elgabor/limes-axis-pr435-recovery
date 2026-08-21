import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DataAsset,
  DataAssetResourcesView,
} from "@/lib/data-assets";
import { strings } from "@/lib/strings";

const mocks = vi.hoisted(() => ({
  useDataAssetResources: vi.fn(),
}));

vi.mock("@/lib/use-data-asset-resources", () => ({
  DATA_ASSET_RESOURCES_ENDPOINTS: { resources: "/data/assets/resources" },
  useDataAssetResources: mocks.useDataAssetResources,
}));

import { ResourcesSection } from "./detail";

function assetFixture(): DataAsset {
  return {
    asset_id: "source:file_csv_manufacturing_assets:default",
    tenant_id: "tenant_demo_manufacturing",
    connector_id: "file_csv_manufacturing_assets",
    display_name: "Manufacturing assets CSV",
    kind: "default",
    evidence: "sync_observed",
    governance: "declared",
    source_type: "file",
    connector_type: "file_csv",
    runtime_boundary: "axis-connector-sandbox",
    egress_policy: "no-external-egress",
    payload_policy: "metadata-only",
    sync_modes: ["preview"],
    schema_fields: [],
    ontology_targets: [],
    last_successful_sync: null,
    registry_origin: "reference",
    manifest_revision: null,
    notes: [],
    stewardship: null,
    observed_resource_count: 2,
  };
}

function resourcesFixture(
  overrides: Partial<DataAssetResourcesView> = {},
): DataAssetResourcesView {
  return {
    tenant_id: "tenant_demo_manufacturing",
    asset_id: "source:file_csv_manufacturing_assets:default",
    resources: [
      {
        resource_name: "assets-day-1.csv",
        schema_fingerprint: "a".repeat(64),
        previous_fingerprint: null,
        drift_state: "added",
        first_seen_at: "2026-08-21T10:00:00Z",
        last_seen_at: "2026-08-21T11:00:00Z",
        observation_count: 3,
        observed_by: "actor-1",
      },
      {
        resource_name: "assets-day-2.csv",
        schema_fingerprint: "b".repeat(64),
        previous_fingerprint: "c".repeat(64),
        drift_state: "changed",
        first_seen_at: "2026-08-20T10:00:00Z",
        last_seen_at: "2026-08-21T09:00:00Z",
        observation_count: 2,
        observed_by: "actor-1",
      },
    ],
    notes: ["Observations come from governed preview boundaries."],
    ...overrides,
  };
}

beforeEach(() => {
  mocks.useDataAssetResources.mockReset();
});

describe("ResourcesSection", () => {
  it("renders observed resources with drift pills and counts", () => {
    mocks.useDataAssetResources.mockReturnValue({
      data: resourcesFixture(),
      error: null,
      errorRequestId: null,
      isLoading: false,
    });

    render(<ResourcesSection asset={assetFixture()} tenantId="tenant_demo_manufacturing" />);

    expect(screen.getByText("2 resources observed")).toBeInTheDocument();
    expect(screen.getByText("assets-day-1.csv")).toBeInTheDocument();
    const changedRow = screen.getByText("assets-day-2.csv").closest(
      "[data-resource-name]",
    );
    expect(changedRow).not.toBeNull();
    expect(changedRow).toHaveTextContent(strings.dataCatalog.resources.drift.changed);
    expect(changedRow).toHaveTextContent("2 observations");
  });

  it("renders the empty state when no resources were observed", () => {
    mocks.useDataAssetResources.mockReturnValue({
      data: resourcesFixture({ resources: [] }),
      error: null,
      errorRequestId: null,
      isLoading: false,
    });

    render(<ResourcesSection asset={assetFixture()} tenantId="tenant_demo_manufacturing" />);

    expect(
      screen.getByText(strings.dataCatalog.resources.empty.title),
    ).toBeInTheDocument();
    expect(screen.getByText("0 resources observed")).toBeInTheDocument();
  });

  it("renders a fail-closed error state without inventing resources", () => {
    mocks.useDataAssetResources.mockReturnValue({
      data: null,
      error: "boom",
      errorRequestId: "req-9",
      isLoading: false,
    });

    render(<ResourcesSection asset={assetFixture()} tenantId="tenant_demo_manufacturing" />);

    expect(
      screen.getByRole("heading", {
        name: strings.dataCatalog.resources.states.error.title,
      }),
    ).toBeInTheDocument();
  });
});
