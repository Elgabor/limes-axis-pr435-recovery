import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DataAsset } from "@/lib/data-assets";
import { formatDateTime } from "@/lib/format";
import { strings } from "@/lib/strings";

const mocks = vi.hoisted(() => ({
  axisFetch: vi.fn(),
  onSuccess: vi.fn(),
  useDataAssetStewardship: vi.fn(),
}));

vi.mock("@/lib/axis-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/axis-api")>();
  return {
    ...actual,
    axisFetchParsedJson: async function axisFetchParsedJson<T>(
      path: string,
      decoder: (value: unknown) => T,
      options: import("@/lib/axis-api").AxisFetchOptions = {},
    ): Promise<T> {
      const response: Response = await mocks.axisFetch(path, options);
      const body = await response.json();
      const requestId = actual.axisResponseRequestId(response);
      if (!response.ok) {
        throw new actual.AxisApiError(path, response.status, { body, requestId });
      }
      return actual.decodeAxisJson(path, body, decoder, requestId);
    },
  };
});

vi.mock("@/lib/use-data-asset-stewardship", () => ({
  DATA_ASSET_STEWARDSHIP_ENDPOINTS: { stewardship: "/data/assets/stewardship" },
  buildDataAssetStewardshipPath: (assetId: string, tenantId: string) =>
    `/data/assets/${encodeURIComponent(assetId)}/stewardship?tenant_id=${tenantId}`,
  useDataAssetStewardship: mocks.useDataAssetStewardship,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

import { StewardshipSection } from "./detail";

const tenantId = "tenant_demo_manufacturing";
const assetId = "source:file_csv_manufacturing_assets:default";
const stewardshipCopy = strings.dataCatalog.stewardship;

function assetFixture(): DataAsset {
  return {
    asset_id: assetId,
    tenant_id: tenantId,
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
    schema_fields: [],
    ontology_targets: [],
    last_successful_sync: null,
    registry_origin: "reference",
    manifest_revision: null,
    notes: [],
    stewardship: null,
    observed_resource_count: null,
  };
}

function loadedView(stewardship: Record<string, unknown> | null) {
  return {
    data: {
      asset_id: assetId,
      stewardship,
      tenant_id: tenantId,
    },
    error: null,
    errorRequestId: null,
    isLoading: false,
  };
}

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stewardshipRecordFixture() {
  return {
    classification: "confidential",
    declared_at: "2026-08-21T09:30:00Z",
    declared_by: "plant-operations-owner-role",
    notes: [],
    owner: "data-platform-team",
    residency: "eu-south",
    retention: "7y",
    revision_number: 3,
  };
}

async function fillAndSubmitForm() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(stewardshipCopy.fields.owner), "  data-platform-team ");
  await user.selectOptions(
    screen.getByLabelText(stewardshipCopy.fields.classification),
    "confidential",
  );
  await user.type(screen.getByLabelText(stewardshipCopy.fields.residency), "eu-south");
  await user.type(screen.getByLabelText(stewardshipCopy.fields.retention), "7y");
  await user.click(screen.getByRole("button", { name: stewardshipCopy.form.submit }));
}

beforeEach(() => {
  mocks.axisFetch.mockReset();
  mocks.onSuccess.mockReset();
});

describe("StewardshipSection", () => {
  it("renders every field of a declared record", () => {
    mocks.useDataAssetStewardship.mockReturnValue(
      loadedView(stewardshipRecordFixture()),
    );

    render(<StewardshipSection asset={assetFixture()} onSuccess={mocks.onSuccess} tenantId={tenantId} />);

    expect(screen.getByText(stewardshipCopy.fields.owner)).toBeInTheDocument();
    expect(screen.getByText("data-platform-team")).toBeInTheDocument();
    expect(screen.getByText(stewardshipCopy.classificationLabels.confidential)).toBeInTheDocument();
    expect(screen.getByText("eu-south")).toBeInTheDocument();
    expect(screen.getByText("7y")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("plant-operations-owner-role")).toBeInTheDocument();
    expect(
      screen.getByText(formatDateTime("2026-08-21T09:30:00Z")),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: stewardshipCopy.form.submit }),
    ).not.toBeInTheDocument();
  });

  it("renders the declare form when stewardship is not declared", () => {
    mocks.useDataAssetStewardship.mockReturnValue(loadedView(null));

    render(<StewardshipSection asset={assetFixture()} onSuccess={mocks.onSuccess} tenantId={tenantId} />);

    expect(
      screen.getByRole("form", { name: stewardshipCopy.form.title }),
    ).toBeInTheDocument();
    for (const label of [
      stewardshipCopy.fields.owner,
      stewardshipCopy.fields.classification,
      stewardshipCopy.fields.residency,
      stewardshipCopy.fields.retention,
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(mocks.onSuccess).not.toHaveBeenCalled();
  });

  it("submits the declaration PUT with the exact contract payload", async () => {
    mocks.useDataAssetStewardship.mockReturnValue(loadedView(null));
    mocks.axisFetch.mockResolvedValueOnce(
      response({
        asset_id: assetId,
        stewardship: stewardshipRecordFixture(),
        tenant_id: tenantId,
      }, 201),
    );
    render(<StewardshipSection asset={assetFixture()} onSuccess={mocks.onSuccess} tenantId={tenantId} />);

    await fillAndSubmitForm();

    expect(mocks.axisFetch).toHaveBeenCalledTimes(1);
    const [path, options] = mocks.axisFetch.mock.calls[0] as [string, {
      body: Record<string, unknown>;
      method: string;
    }];
    expect(path).toBe(
      `/data/assets/${encodeURIComponent(assetId)}/stewardship?tenant_id=${tenantId}`,
    );
    expect(options.method).toBe("PUT");
    expect(Object.keys(options.body).sort()).toEqual([
      "classification",
      "expected_revision",
      "idempotency_key",
      "owner",
      "residency",
      "retention",
    ]);
    expect(options.body.owner).toBe("data-platform-team");
    expect(options.body.classification).toBe("confidential");
    expect(options.body.residency).toBe("eu-south");
    expect(options.body.retention).toBe("7y");
    expect(options.body.expected_revision).toBeNull();
    expect(options.body.idempotency_key).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      stewardshipCopy.form.success,
    );
    expect(mocks.onSuccess).toHaveBeenCalledTimes(1);
  });

  it("surfaces an explicit reload-and-retry message on a revision conflict", async () => {
    mocks.useDataAssetStewardship.mockReturnValue(loadedView(null));
    mocks.axisFetch.mockResolvedValueOnce(response({
      detail: {
        code: "CONFLICT",
        current_revision: 2,
        reason: "expected_revision_mismatch",
      },
    }, 409));
    render(<StewardshipSection asset={assetFixture()} onSuccess={mocks.onSuccess} tenantId={tenantId} />);

    await fillAndSubmitForm();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      stewardshipCopy.form.errors.conflict,
    );
    expect(mocks.onSuccess).not.toHaveBeenCalled();
  });

  it("blocks an empty submit client-side without calling the API", async () => {
    const user = userEvent.setup();
    mocks.useDataAssetStewardship.mockReturnValue(loadedView(null));
    render(<StewardshipSection asset={assetFixture()} onSuccess={mocks.onSuccess} tenantId={tenantId} />);

    await user.click(screen.getByRole("button", { name: stewardshipCopy.form.submit }));

    const alerts = screen.getAllByRole("alert");
    expect(alerts.map((alert) => alert.textContent)).toEqual([
      stewardshipCopy.form.errors.ownerRequired,
      stewardshipCopy.form.errors.residencyRequired,
      stewardshipCopy.form.errors.retentionRequired,
    ]);
    expect(mocks.axisFetch).not.toHaveBeenCalled();
    expect(mocks.onSuccess).not.toHaveBeenCalled();
  });

  it("keeps raw response bodies out of operator-facing failures", async () => {
    mocks.useDataAssetStewardship.mockReturnValue(loadedView(null));
    mocks.axisFetch.mockResolvedValueOnce(response({
      detail: { debug: "secret-internal-trace", reason: "write_failed" },
    }, 500));
    render(<StewardshipSection asset={assetFixture()} onSuccess={mocks.onSuccess} tenantId={tenantId} />);

    await fillAndSubmitForm();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      stewardshipCopy.form.errors.declareFailed,
    );
    expect(screen.queryByText(/secret-internal-trace|write_failed/)).not.toBeInTheDocument();
    expect(mocks.onSuccess).not.toHaveBeenCalled();
  });
});
