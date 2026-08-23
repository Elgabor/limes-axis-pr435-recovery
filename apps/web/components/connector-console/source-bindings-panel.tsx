"use client";

import { DatabaseZap } from "lucide-react";

import { Eyebrow } from "@/components/ui/eyebrow";
import { useAxisQuery } from "@/lib/use-axis-query";
import { parseSourceBindingsView } from "@/lib/runtime-contracts/connectors";
import { strings } from "@/lib/strings";
import { OPERATIONS_API_PREFIX, buildTenantScopedPath } from "@/lib/tenant-scope";

/*
 * Durable view of the active source bindings for one external-DB connector.
 * This is persisted server truth, not session state: it survives reloads and
 * is how operators verify what is actually bound for ingestion. Every row
 * stays honest about ingestion: pending until a real ingestion boundary runs.
 */

export function ConnectorSourceBindingsSection({
  connectorId,
  tenantId,
}: {
  connectorId: string;
  tenantId: string;
}) {
  const copy = strings.connectors.sourceBindings;
  const path = buildTenantScopedPath(
    `${OPERATIONS_API_PREFIX}/connectors/external-db/source-bindings`,
    tenantId,
    { connector_id: connectorId },
  );
  const bindingsQuery = useAxisQuery(path, {
    parse: parseSourceBindingsView,
  });

  if (bindingsQuery.source === "unavailable" || bindingsQuery.source === "tenant_not_found") {
    return (
      <section
        aria-label={copy.title}
        className="grid gap-1 border-t border-line/60 pt-4 dark:border-white/10"
      >
        <BindingsHeader />
        <p className="m-0 text-sm text-muted">{copy.unavailableTitle}: {copy.unavailableDetail}</p>
      </section>
    );
  }

  const bindings = bindingsQuery.data?.bindings ?? [];
  if (bindingsQuery.source === "loading") {
    return (
      <section aria-label={copy.title} className="grid gap-2 border-t border-line/60 pt-4 dark:border-white/10">
        <BindingsHeader />
        <div className="h-10 animate-pulse rounded-xl bg-line/40" />
      </section>
    );
  }

  return (
    <section
      aria-label={copy.title}
      className="grid gap-2 border-t border-line/60 pt-4 dark:border-white/10"
    >
      <BindingsHeader />
      {bindings.length === 0 ? (
        <p className="m-0 max-w-prose text-sm leading-snug text-muted">{copy.emptyDetail}</p>
      ) : (
        <table
          aria-label={copy.title}
          className="w-full min-w-[560px] border-collapse text-left text-sm"
        >
          <thead>
            <tr className="border-b border-line dark:border-white/10">
              <th className="px-2 py-2 font-medium">{copy.tableColumn}</th>
              <th className="px-2 py-2 font-medium">{copy.fingerprintColumn}</th>
              <th className="px-2 py-2 font-medium">{copy.stateColumn}</th>
            </tr>
          </thead>
          <tbody>
            {bindings.map((binding) => (
              <tr
                className="border-b border-line/60 last:border-b-0 dark:border-white/10"
                key={binding.binding_id}
              >
                <td className="px-2 py-2 font-mono text-xs break-all">{binding.resource_name}</td>
                <td
                  className="px-2 py-2 font-mono text-xs break-all text-muted"
                  title={binding.schema_fingerprint}
                >
                  {binding.schema_fingerprint.slice(0, 12)}
                </td>
                <td className="px-2 py-2">
                  <span className={`status-pill ${binding.status === "active" ? "signal-ready" : "status-checking"}`}>
                    {binding.status === "active" ? copy.activePill : binding.status}
                  </span>{" "}
                  <span className="status-pill status-checking">
                    {binding.ingestion_status === "pending_ingestion"
                      ? copy.ingestionPendingPill
                      : binding.ingestion_status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function BindingsHeader() {
  const copy = strings.connectors.sourceBindings;
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <DatabaseZap aria-hidden="true" className="shrink-0 text-signal" size={16} />
      <Eyebrow>{copy.title}</Eyebrow>
    </div>
  );
}
