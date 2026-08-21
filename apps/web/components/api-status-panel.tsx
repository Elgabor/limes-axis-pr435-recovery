"use client";

import { useEffect, useState } from "react";
import { Activity, ServerCrash } from "lucide-react";

import {
  getApiBaseUrl,
  summarizeApiStatus,
  type ApiStatusSummary,
} from "@/lib/api-status";

const checkingStatus: ApiStatusSummary = {
  state: "checking",
  label: "Checking",
  detail: "Reading API health and readiness.",
};

async function endpointResponds(url: string, signal: AbortSignal): Promise<boolean> {
  const response = await fetch(url, { signal, cache: "no-store" });
  return response.ok;
}

export function ApiStatusPanel() {
  const [status, setStatus] = useState<ApiStatusSummary>(checkingStatus);
  const apiBaseUrl = getApiBaseUrl();

  useEffect(() => {
    const controller = new AbortController();

    async function probeApi() {
      try {
        const [healthOk, readyOk] = await Promise.all([
          endpointResponds(`${apiBaseUrl}/health`, controller.signal),
          endpointResponds(`${apiBaseUrl}/ready`, controller.signal),
        ]);
        setStatus(summarizeApiStatus({ healthOk, readyOk }));
      } catch {
        setStatus(summarizeApiStatus({ healthOk: false, readyOk: false }));
      }
    }

    void probeApi();

    return () => controller.abort();
  }, [apiBaseUrl]);

  const Icon = status.state === "unavailable" ? ServerCrash : Activity;

  return (
    <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5 grid gap-3">
      <div>
        <p className="eyebrow m-0">API Status</p>
        <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">Control API</h2>
      </div>
      <div className="grid gap-2">
        <span className={`status-pill status-${status.state}`}>
          <Icon size={15} />
          {status.label}
        </span>
        <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{status.detail}</p>
        <p className="font-mono text-[13px] break-words text-muted">{apiBaseUrl}</p>
      </div>
    </section>
  );
}
