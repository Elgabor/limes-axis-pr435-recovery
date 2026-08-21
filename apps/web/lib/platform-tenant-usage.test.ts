import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildPlatformTenantUsagePath,
  defaultUsageWindowDays,
  fetchTenantUsage,
  summarizeUsageByMetric,
  usageMetricLabel,
  type TenantUsageSummary,
} from "./platform-tenant-usage";

function buildSummary(overrides: Partial<TenantUsageSummary> = {}): TenantUsageSummary {
  return {
    tenant_id: "tenant_acme",
    window_start: "2026-07-03T00:00:00Z",
    window_end: "2026-07-10T00:00:00Z",
    period_window_seconds: 86400,
    metric_totals: [
      { metric_key: "api_request", quantity: 15 },
      { metric_key: "session_created", quantity: 2 },
    ],
    periods: [
      { period_start: "2026-07-09T00:00:00Z", metric_key: "api_request", quantity: 10 },
      { period_start: "2026-07-08T00:00:00Z", metric_key: "api_request", quantity: 5 },
      { period_start: "2026-07-09T00:00:00Z", metric_key: "session_created", quantity: 2 },
    ],
    usage_notes: ["Metering is cumulative accounting."],
    ...overrides,
  };
}

describe("usage metric labels and paths", () => {
  it("labels known metrics and falls back to the raw key", () => {
    expect(usageMetricLabel("api_request")).toBe("API requests");
    expect(usageMetricLabel("connector_sync_rows")).toBe("Connector sync rows");
    expect(usageMetricLabel("session_created")).toBe("Sessions created");
    expect(usageMetricLabel("future_metric")).toBe("future_metric");
  });

  it("builds the usage path with the default and a custom window", () => {
    expect(buildPlatformTenantUsagePath("tenant_acme")).toBe(
      `/platform/tenants/tenant_acme/usage?last_days=${defaultUsageWindowDays}`,
    );
    expect(buildPlatformTenantUsagePath("tenant_acme", 30)).toBe(
      "/platform/tenants/tenant_acme/usage?last_days=30",
    );
  });

  it("encodes the tenant id in the path", () => {
    expect(buildPlatformTenantUsagePath("tenant/with space")).toContain(
      "tenant%2Fwith%20space",
    );
  });
});

describe("summarizeUsageByMetric (panel rendering states)", () => {
  it("returns no rows for a null summary (loading / unavailable state)", () => {
    expect(summarizeUsageByMetric(null)).toEqual([]);
  });

  it("returns no rows for an empty summary (no-usage state)", () => {
    expect(
      summarizeUsageByMetric(buildSummary({ metric_totals: [], periods: [] })),
    ).toEqual([]);
  });

  it("folds totals and period counts per metric, ordered by label", () => {
    const rows = summarizeUsageByMetric(buildSummary());
    expect(rows).toEqual([
      { metricKey: "api_request", label: "API requests", total: 15, periodCount: 2 },
      {
        metricKey: "session_created",
        label: "Sessions created",
        total: 2,
        periodCount: 1,
      },
    ]);
  });

  it("tolerates missing periods array", () => {
    const rows = summarizeUsageByMetric(
      buildSummary({ periods: undefined, metric_totals: [{ metric_key: "api_request", quantity: 4 }] }),
    );
    expect(rows).toEqual([
      { metricKey: "api_request", label: "API requests", total: 4, periodCount: 0 },
    ]);
  });
});

describe("fetchTenantUsage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_AXIS_API_BASE_URL;
  });

  function stubFetch(status: number, body: unknown, requestId?: string) {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      new Response(body === null ? null : JSON.stringify(body), {
        headers: {
          "Content-Type": "application/json",
          ...(requestId ? { "x-request-id": requestId } : {}),
        },
        status,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("returns the summary and sends last_days with credentials on 200", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const summary = buildSummary();
    const fetchMock = stubFetch(200, summary);

    await expect(fetchTenantUsage("tenant_acme", {}, 30)).resolves.toEqual(summary);

    const [url, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    expect(url).toBe("http://axis-api.test/platform/tenants/tenant_acme/usage?last_days=30");
    expect(init?.credentials).toBe("include");
  });

  it("returns null for an unknown tenant (404)", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(404, { detail: { message: "not found" } });

    await expect(fetchTenantUsage("tenant_absent")).resolves.toBeNull();
  });

  it("throws AxisApiError on a non-OK, non-404 response", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubFetch(503, { detail: { message: "down" } }, "request-tenant-usage-503");

    await expect(fetchTenantUsage("tenant_acme")).rejects.toMatchObject({
      requestId: "request-tenant-usage-503",
      status: 503,
    });
  });
});
