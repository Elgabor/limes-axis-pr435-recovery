"use client";

import { useEffect, useState } from "react";
import { Activity } from "lucide-react";

import {
  buildPlatformTenantUsagePath,
  defaultUsageWindowDays,
  fetchTenantUsage,
  platformTenantUsageScope,
  summarizeUsageByMetric,
  type TenantUsageSummary,
  type UsageMetricSummaryRow,
} from "@/lib/platform-tenant-usage";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useConsole } from "@/providers/console-provider";

type UsageSource = "loading" | "api" | "unavailable" | "missing";

function sourceLabel(source: UsageSource): string {
  if (source === "api") {
    return "API usage ledger";
  }

  if (source === "missing") {
    return "Tenant not found";
  }

  return source === "loading" ? "Loading usage API" : "Usage API unavailable";
}

export function TenantUsagePanel({ tenantId }: { tenantId: string }) {
  const { session } = useOidcConsoleSession();
  const { refreshNonce } = useConsole();
  const [summary, setSummary] = useState<TenantUsageSummary | null>(null);
  const [source, setSource] = useState<UsageSource>("loading");

  useEffect(() => {
    const controller = new AbortController();

    async function loadUsage() {
      setSource("loading");

      try {
        const result = await fetchTenantUsage(
          tenantId,
          { session, signal: controller.signal },
          defaultUsageWindowDays,
        );

        if (controller.signal.aborted) {
          return;
        }

        if (result === null) {
          setSummary(null);
          setSource("missing");
          return;
        }

        setSummary(result);
        setSource("api");
      } catch {
        if (!controller.signal.aborted) {
          setSummary(null);
          setSource("unavailable");
        }
      }
    }

    void loadUsage();

    return () => controller.abort();
  }, [tenantId, session, refreshNonce]);

  const rows: UsageMetricSummaryRow[] = summarizeUsageByMetric(summary);
  const usageNotes = summary?.usage_notes ?? [];

  return (
    <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10">
        <div>
          <p className="eyebrow m-0">Usage Metering</p>
          <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">Consumption over the last {defaultUsageWindowDays} days</h2>
        </div>
        <Activity size={18} />
      </div>

      {source !== "api" ? (
        <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words" role="status">
          {sourceLabel(source)}
        </p>
      ) : rows.length === 0 ? (
        <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words" role="status">
          No metered consumption in this window.
        </p>
      ) : (
        <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4 [&>*]:min-w-0" aria-label="Per-metric consumption">
          {rows.map((row) => (
            <article className="min-w-0 rounded-2xl border border-line bg-surface p-4 dark:border-white/10 dark:bg-white/5 min-h-[120px]" key={row.metricKey}>
              <p className="eyebrow m-0">{row.label}</p>
              <p className="font-display mx-0 mt-3 mb-1.5 text-2xl tabular-nums break-words text-ink">{row.total.toLocaleString()}</p>
              <p className="m-0 text-xs leading-relaxed text-muted break-words">
                {row.periodCount} {row.periodCount === 1 ? "period" : "periods"} in window
              </p>
            </article>
          ))}
        </div>
      )}

      <details className="mt-4 border-t border-line/60 pt-3 text-sm text-muted dark:border-white/10">
        <summary className="cursor-pointer font-medium text-ink">Usage methodology and access</summary>
        <div className="mt-3 grid min-w-0 grid-cols-1 gap-2.5 [&>p]:min-w-0 [&>p]:[overflow-wrap:anywhere]">
          <p className="m-0 leading-snug">Metering is cumulative consumption accounting; quotas remain the enforcement ceilings.</p>
          <p className="m-0 leading-snug break-words">Required permission: {platformTenantUsageScope}.</p>
          <p className="m-0 break-words font-mono text-[13px]">GET {buildPlatformTenantUsagePath(tenantId)}</p>
          {usageNotes.map((note) => (
            <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words" key={note}>
              {note}
            </p>
          ))}
        </div>
      </details>
    </section>
  );
}
