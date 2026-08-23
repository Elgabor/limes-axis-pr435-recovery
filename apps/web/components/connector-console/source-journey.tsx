"use client";

import { CheckCircle2, Circle, Route } from "lucide-react";

import { Eyebrow } from "@/components/ui/eyebrow";
import {
  SOURCE_INGESTION_ENDPOINTS,
  buildSourceIngestionReadPath,
} from "@/lib/connectors-console";
import {
  parseSourceBindingsView,
  parseSourceIngestionOverview,
} from "@/lib/runtime-contracts/connectors";
import { fillTemplate } from "@/lib/format";
import { strings } from "@/lib/strings";
import { buildTenantScopedPath, OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";
import { useAxisQuery } from "@/lib/use-axis-query";

/*
 * Guided verify → discover → activate → validate journey for the external-DB
 * connector. Every state is derived from durable API truth (bindings and the
 * ingestion overview read models) — never session state, never invented
 * progress. Each step names its prerequisite, consequence, and next action in
 * plain language so an SME can act without knowing request IDs.
 */

type JourneyKey = "verifyDiscover" | "activate" | "requestIngestion" | "validate";

function useJourneyData(connectorId: string, tenantId: string) {
  const bindingsPath = buildTenantScopedPath(
    `${OPERATIONS_API_PREFIX}/connectors/external-db/source-bindings`,
    tenantId,
    { connector_id: connectorId },
  );
  const bindingsQuery = useAxisQuery(bindingsPath, {
    expectedTenantId: tenantId,
    parse: parseSourceBindingsView,
  });
  const overviewPath = buildSourceIngestionReadPath({
    endpoint: SOURCE_INGESTION_ENDPOINTS.overview,
    tenantId,
    connectorId,
  });
  const overviewQuery = useAxisQuery(overviewPath, {
    expectedTenantId: tenantId,
    parse: parseSourceIngestionOverview,
  });
  return {
    loading: bindingsQuery.source === "loading" || overviewQuery.source === "loading",
    unavailable:
      bindingsQuery.source === "unavailable"
      || bindingsQuery.source === "tenant_not_found"
      || overviewQuery.source === "unavailable"
      || overviewQuery.source === "tenant_not_found",
    bindings: bindingsQuery.data?.bindings ?? [],
    summary: overviewQuery.data?.summary ?? null,
  };
}

export function SourceJourneySpine({
  connectorId,
  tenantId,
}: {
  connectorId: string;
  tenantId: string;
}) {
  const copy = strings.connectors.sourceJourney;
  const { loading, unavailable, bindings, summary } = useJourneyData(
    connectorId,
    tenantId,
  );

  if (loading) {
    return (
      <section aria-label={copy.title} className="grid gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Route aria-hidden="true" className="shrink-0 text-signal" size={16} />
          <Eyebrow>{copy.title}</Eyebrow>
        </div>
        <div aria-hidden="true" className="h-16 animate-pulse rounded-xl bg-line/40" />
      </section>
    );
  }
  if (unavailable) {
    return (
      <section aria-label={copy.title} className="grid gap-1">
        <div className="flex min-w-0 items-center gap-2">
          <Route aria-hidden="true" className="shrink-0 text-signal" size={16} />
          <Eyebrow>{copy.title}</Eyebrow>
        </div>
        <p className="m-0 text-sm text-muted">{copy.unavailable}</p>
      </section>
    );
  }

  const activeBindings = bindings.filter((binding) => binding.status === "active");
  const pendingIngestion = activeBindings.filter(
    (binding) => binding.ingestion_status === "pending_ingestion",
  );
  const completedRequests = summary?.status_counts["completed"] ?? 0;
  const failedRequests = summary?.dead_lettered_count ?? 0;

  // Step truth comes only from what the API durably reports.
  const verifiedAndDiscovered = bindings.length > 0;
  const activated = activeBindings.length > 0;
  const requested = (summary?.total_count ?? 0) > 0;
  const validated = completedRequests > 0;

  const steps: Array<{
    key: JourneyKey;
    label: string;
    done: boolean;
    body: string;
    consequence: string;
    next?: string;
    warn?: boolean;
  }> = [
    {
      key: "verifyDiscover",
      label: copy.steps.verifyDiscover.label,
      done: verifiedAndDiscovered,
      body: verifiedAndDiscovered
        ? copy.steps.verifyDiscover.done
        : copy.steps.verifyDiscover.todo,
      consequence: copy.steps.verifyDiscover.consequence,
      next: verifiedAndDiscovered ? undefined : copy.nextActions.verifyDiscover,
    },
    {
      key: "activate",
      label: copy.steps.activate.label,
      done: activated,
      body: pendingIngestion.length > 0
        ? fillTemplate(copy.steps.activate.done, { count: pendingIngestion.length })
        : copy.steps.activate.todo,
      consequence: copy.steps.activate.consequence,
      next: activated ? undefined : copy.nextActions.activate,
    },
    {
      key: "requestIngestion",
      label: copy.steps.requestIngestion.label,
      done: requested,
      body: requested
        ? fillTemplate(copy.steps.requestIngestion.done, {
            count: summary?.total_count ?? 0,
          })
        : copy.steps.requestIngestion.todo,
      consequence: copy.steps.requestIngestion.consequence,
      next: requested ? undefined : copy.nextActions.requestIngestion,
    },
    {
      key: "validate",
      label: copy.steps.validate.label,
      done: validated,
      body: failedRequests > 0
        ? copy.steps.validate.remediation
        : validated
          ? fillTemplate(copy.steps.validate.doneClean, { completed: completedRequests })
          : copy.steps.validate.todo,
      consequence: copy.steps.validate.consequence,
      next: validated ? undefined : copy.nextActions.validate,
      warn: failedRequests > 0,
    },
  ];

  return (
    <section aria-label={copy.title} className="grid gap-2">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <Route aria-hidden="true" className="shrink-0 text-signal" size={16} />
        <Eyebrow>{copy.title}</Eyebrow>
      </div>
      <p className="m-0 max-w-prose text-sm leading-snug text-muted">{copy.detail}</p>
      <ol className="m-0 grid list-none gap-2 p-0">
        {steps.map((step) => (
          <li
            className={`grid gap-1 rounded-xl border px-3 py-2 ${
              step.warn
                ? "border-[rgb(var(--signal))]/40"
                : "border-line/60 dark:border-white/10"
            }`}
            data-journey-step={step.key}
            key={step.key}
          >
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              {step.done ? (
                <CheckCircle2
                  aria-hidden="true"
                  className="size-4 shrink-0 text-[rgb(var(--signal))]"
                />
              ) : (
                <Circle aria-hidden="true" className="size-4 shrink-0 text-muted" />
              )}
              <span className="text-sm font-medium text-ink">
                <span className="sr-only">
                  {step.done ? "Completed step: " : "Not done yet: "}
                </span>
                {step.label}
              </span>
              <span
                className={`status-pill ${
                  step.warn
                    ? "signal-action-required"
                    : step.done
                      ? "signal-ready"
                      : "status-checking"
                }`}
              >
                {step.warn ? "Needs attention" : step.done ? "Done" : "To do"}
              </span>
            </div>
            <p className="m-0 max-w-prose text-xs leading-snug text-muted">{step.body}</p>
            <p className="m-0 max-w-prose text-[11px] leading-snug text-muted">
              {step.consequence}
            </p>
            {step.next ? (
              <p className="m-0 max-w-prose text-xs leading-snug font-medium text-ink">
                {`${copy.nextActionLabel}: ${step.next}`}
              </p>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
