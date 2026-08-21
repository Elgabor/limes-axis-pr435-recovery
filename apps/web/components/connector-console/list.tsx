"use client";

import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { PlatformStatusPill } from "@/components/status-pill";
import { cn } from "@/lib/cn";
import { formatConnectorLabel, type ConnectorRegistryItem } from "@/lib/connectors-demo";
import { formatDateTime, pluralize } from "@/lib/format";
import { strings } from "@/lib/strings";

function manifestLifecycleClass(status: string): string {
  if (status === "active_live") {
    return "signal-ready";
  }
  if (status === "active_preview") {
    return "signal-watch";
  }
  if (status === "registered_preview_only") {
    return "status-checking";
  }
  return "signal-action-required";
}

/** Connector list rail over the API's complete registry contract. */
export function ConnectorList({
  connectors,
  selectedConnectorId,
  onSelect,
}: {
  connectors: ConnectorRegistryItem[];
  selectedConnectorId: string;
  onSelect: (connectorId: string) => void;
}) {
  return (
    <Card className="grid content-start gap-4">
      <div className="grid gap-1">
        <Eyebrow>{strings.connectors.list.eyebrow}</Eyebrow>
        <h2 className="font-display m-0 text-xl text-ink">
          {pluralize(connectors.length, "connector")}
        </h2>
      </div>
      <div className="grid gap-2">
        {connectors.map((connector) => {
          const isSelected = connector.manifest.connector_id === selectedConnectorId;
          const syncObservation = connector.last_successful_sync;

          return (
            <button
              aria-pressed={isSelected}
              className={cn(
                "flex w-full cursor-pointer items-start justify-between gap-3 rounded-2xl border px-4 py-3 text-left transition-colors",
                isSelected
                  ? "border-signal/60 bg-tint-100 dark:bg-signal/15"
                  : "border-line bg-transparent hover:border-signal/40 hover:bg-tint-50 dark:border-white/10 dark:hover:bg-white/5",
              )}
              key={connector.manifest.connector_id}
              onClick={() => onSelect(connector.manifest.connector_id)}
              type="button"
            >
              <span className="grid min-w-0 gap-0.5">
                <span className="text-sm font-medium text-ink">
                  {connector.manifest.display_name}
                </span>
                <span className="text-xs text-muted">
                  {formatConnectorLabel(connector.manifest.connector_type)}
                </span>
                <span className="text-xs text-muted">
                  {syncObservation
                    ? strings.connectors.list.observedRecords(syncObservation.records_read)
                    : connector.preview_sample
                      ? pluralize(connector.preview_sample.record_count, "sample row")
                      : strings.connectors.list.neverSampled}
                </span>
                {syncObservation ? (
                  <span className="text-xs text-muted">
                    {strings.connectors.list.successfulSync(
                      formatDateTime(syncObservation.completed_at),
                      syncObservation.run_id,
                    )}
                  </span>
                ) : connector.preview_sample ? (
                  <span className="text-xs text-muted">
                    {strings.connectors.list.previewSample}
                  </span>
                ) : null}
              </span>
              {connector.registry_origin === "persisted_manifest" && connector.persisted_manifest ? (
                <span
                  className={`status-pill ${manifestLifecycleClass(
                    connector.persisted_manifest.status,
                  )}`}
                >
                  {formatConnectorLabel(connector.persisted_manifest.status)}
                </span>
              ) : (
                <PlatformStatusPill status={connector.connector_status} />
              )}
            </button>
          );
        })}
      </div>
    </Card>
  );
}
