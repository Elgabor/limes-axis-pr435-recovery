import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DataAsset } from "@/lib/data-assets";
import { strings } from "@/lib/strings";

const mocks = vi.hoisted(() => ({
  axisFetch: vi.fn(),
  onSuccess: vi.fn(),
  useDataAssetContract: vi.fn(),
  useDataAssetContractEvaluation: vi.fn(),
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

vi.mock("@/lib/use-data-asset-contract", () => ({
  buildDataAssetContractPath: (assetId: string, tenantId: string) =>
    `/data/assets/${encodeURIComponent(assetId)}/contract?tenant_id=${tenantId}`,
  useDataAssetContract: mocks.useDataAssetContract,
  useDataAssetContractEvaluation: mocks.useDataAssetContractEvaluation,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

import { ContractSection } from "./detail";

const tenantId = "tenant_demo_manufacturing";
const assetId = "source:file_csv_manufacturing_assets:default";
const copy = strings.dataCatalog.contract;

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

function loadedViews({
  contract = null,
  status = "unknown",
  checks = [],
}: {
  contract?: Record<string, unknown> | null;
  status?: string;
  checks?: Array<{ kind: string; state: string; detail: string }>;
} = {}) {
  mocks.useDataAssetContract.mockReturnValue({
    data: { tenant_id: tenantId, asset_id: assetId, contract },
    error: null,
    errorRequestId: null,
    isLoading: false,
  });
  mocks.useDataAssetContractEvaluation.mockReturnValue({
    data: {
      tenant_id: tenantId,
      asset_id: assetId,
      status,
      checks,
      evaluated_at: "2026-08-21T10:00:00Z",
    },
    error: null,
    errorRequestId: null,
    isLoading: false,
  });
}

beforeEach(() => {
  mocks.axisFetch.mockReset();
  mocks.onSuccess.mockClear();
  loadedViews();
});

describe("ContractSection", () => {
  it("renders the explicit unknown state and the declare form when no contract exists", () => {
    loadedViews();

    render(<ContractSection asset={assetFixture()} onSuccess={mocks.onSuccess} tenantId={tenantId} />);

    expect(screen.getByText(copy.status.unknown)).toBeInTheDocument();
    expect(screen.getByText(copy.status.notDeclared)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: copy.form.submit }),
    ).toBeInTheDocument();
  });

  it("renders a failing evaluation with per-check detail and the declared record", () => {
    loadedViews({
      contract: {
        expected_resource_name: "assets.csv",
        expected_schema_fingerprint: null,
        freshness_warn_hours: 12,
        freshness_fail_hours: 48,
        notes: [],
        revision_number: 1,
        declared_by: "actor-1",
        declared_at: "2026-08-21T10:00:00Z",
      },
      status: "fail",
      checks: [
        { kind: "presence", state: "pass", detail: "seen recently" },
        { kind: "freshness", state: "fail", detail: "72.0h old" },
      ],
    });

    render(<ContractSection asset={assetFixture()} onSuccess={mocks.onSuccess} tenantId={tenantId} />);

    // The overall status and the failing check both render a "Fail" pill.
    expect(screen.getAllByText(copy.status.fail).length).toBeGreaterThan(0);
    expect(screen.getByText(copy.checks.freshness)).toBeInTheDocument();
    expect(screen.getByText("72.0h old")).toBeInTheDocument();
    expect(screen.getByText("assets.csv")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: copy.form.submit }),
    ).not.toBeInTheDocument();
  });

  it("submits a PUT payload with trimmed and parsed fields", async () => {
    const user = userEvent.setup();
    mocks.axisFetch.mockImplementation(async (_path: string, options: { body: unknown }) => {
      const requestedBody = (options as { body: Record<string, unknown> }).body;
      expect(requestedBody).toEqual({
        expected_resource_name: "assets.csv",
        expected_schema_fingerprint: "a".repeat(64),
        freshness_warn_hours: 12,
        freshness_fail_hours: 48,
        expected_revision: null,
        idempotency_key: expect.any(String),
      });
      return new Response(
        JSON.stringify({
          tenant_id: tenantId,
          asset_id: assetId,
          contract: {
            expected_resource_name: "assets.csv",
            expected_schema_fingerprint: "a".repeat(64),
            freshness_warn_hours: 12,
            freshness_fail_hours: 48,
            notes: [],
            revision_number: 1,
            declared_by: "public-demo-steward",
            declared_at: "2026-08-21T10:00:00Z",
          },
        }),
        { status: 201 },
      );
    });
    loadedViews();

    render(<ContractSection asset={assetFixture()} onSuccess={mocks.onSuccess} tenantId={tenantId} />);
    await user.type(screen.getAllByRole("textbox")[0], "assets.csv");
    await user.type(screen.getAllByRole("textbox")[1], "A".repeat(64).toLowerCase());
    await user.type(screen.getByLabelText(copy.fields.warnHours), "12");
    await user.type(screen.getByLabelText(copy.fields.failHours), "48");
    await user.click(screen.getByRole("button", { name: copy.form.submit }));

    expect(mocks.axisFetch).toHaveBeenCalledTimes(1);
    expect(mocks.onSuccess).toHaveBeenCalled();
  });

  it("blocks submit when the warn threshold exceeds the fail threshold", async () => {
    const user = userEvent.setup();
    loadedViews();

    render(<ContractSection asset={assetFixture()} onSuccess={mocks.onSuccess} tenantId={tenantId} />);
    await user.type(screen.getAllByRole("textbox")[0], "assets.csv");
    await user.type(screen.getByLabelText(copy.fields.warnHours), "99");
    await user.type(screen.getByLabelText(copy.fields.failHours), "10");
    await user.click(screen.getByRole("button", { name: copy.form.submit }));

    expect(mocks.axisFetch).not.toHaveBeenCalled();
    expect(screen.getByText(copy.form.errors.orderingInvalid)).toBeInTheDocument();
  });

  it("surfaces the conflict message on a 409 revision mismatch", async () => {
    const user = userEvent.setup();
    loadedViews();
    mocks.axisFetch.mockResolvedValue(
      new Response(
        JSON.stringify({ detail: { reason: "expected_revision_mismatch" } }),
        { status: 409 },
      ),
    );

    render(<ContractSection asset={assetFixture()} onSuccess={mocks.onSuccess} tenantId={tenantId} />);
    await user.type(screen.getAllByRole("textbox")[0], "assets.csv");
    await user.click(screen.getByRole("button", { name: copy.form.submit }));

    expect(await screen.findByText(copy.form.errors.conflict)).toBeInTheDocument();
  });
});
