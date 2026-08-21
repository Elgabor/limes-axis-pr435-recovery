import {
  AxisApiError,
  axisFetch,
  axisResponseRequestId,
  decodeAxisJson,
  type AxisFetchOptions,
} from "./axis-api";
import { buildPlatformTenantDetailPath } from "./platform-tenants";
import { parseTenantUsageSummary } from "./runtime-contracts/tenants";

export type TenantUsageMetricTotal = {
  metric_key: string;
  quantity: number;
};

export type TenantUsagePeriodPoint = {
  period_start: string;
  metric_key: string;
  quantity: number;
};

export type TenantUsageSummary = {
  tenant_id: string;
  window_start: string;
  window_end: string;
  period_window_seconds: number;
  metric_totals?: TenantUsageMetricTotal[];
  periods?: TenantUsagePeriodPoint[];
  usage_notes?: string[];
};

// The usage read route requires the operator scope plus this dedicated
// billing-adjacent read scope (mirrors the server REQUIRED_USAGE_READ_SCOPE).
export const platformTenantUsageScope = "platform:tenant:usage";

// Default read window. The route accepts last_days (1..366) or an explicit
// from/to; the console uses the last-N-days form.
export const defaultUsageWindowDays = 7;

// Human labels for the known metric keys; unknown keys fall back to the raw key
// so a newly metered surface still renders without a console change.
const metricLabels: Record<string, string> = {
  api_request: "API requests",
  connector_sync_rows: "Connector sync rows",
  session_created: "Sessions created",
};

export function usageMetricLabel(metricKey: string): string {
  return metricLabels[metricKey] ?? metricKey;
}

export function buildPlatformTenantUsagePath(
  tenantId: string,
  lastDays: number = defaultUsageWindowDays,
): string {
  const params = new URLSearchParams();
  params.set("last_days", String(lastDays));
  return `${buildPlatformTenantDetailPath(tenantId)}/usage?${params.toString()}`;
}

/**
 * Read aggregated per-metric consumption for a tenant over the last N days.
 * A 404 (unknown tenant) resolves to null so the panel can render a
 * tenant-not-found state; other non-OK responses throw AxisApiError so the
 * caller falls back to the API-unavailable state.
 */
export async function fetchTenantUsage(
  tenantId: string,
  options: AxisFetchOptions = {},
  lastDays: number = defaultUsageWindowDays,
): Promise<TenantUsageSummary | null> {
  const path = buildPlatformTenantUsagePath(tenantId, lastDays);
  const response = await axisFetch(path, options);

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    throw new AxisApiError(path, response.status, {
      requestId: axisResponseRequestId(response),
    });
  }

  return decodeAxisJson(
    path,
    await response.json(),
    parseTenantUsageSummary,
    axisResponseRequestId(response),
  );
}

export type UsageMetricSummaryRow = {
  metricKey: string;
  label: string;
  total: number;
  periodCount: number;
};

/**
 * Fold a usage summary into one row per metric for the panel: the cumulative
 * total plus how many distinct period buckets contributed. Metrics are ordered
 * by their known label so the panel is stable across reads.
 */
export function summarizeUsageByMetric(
  summary: TenantUsageSummary | null,
): UsageMetricSummaryRow[] {
  if (!summary) {
    return [];
  }

  const totals = summary.metric_totals ?? [];
  const periods = summary.periods ?? [];
  const periodCounts = new Map<string, number>();
  for (const point of periods) {
    periodCounts.set(point.metric_key, (periodCounts.get(point.metric_key) ?? 0) + 1);
  }

  return totals
    .map((total) => ({
      metricKey: total.metric_key,
      label: usageMetricLabel(total.metric_key),
      total: total.quantity,
      periodCount: periodCounts.get(total.metric_key) ?? 0,
    }))
    .sort((left, right) => left.label.localeCompare(right.label));
}
