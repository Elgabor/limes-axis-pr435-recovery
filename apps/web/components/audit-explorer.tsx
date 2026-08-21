"use client";

import { useEffect, useState } from "react";
import { Download, FileText, Filter, RotateCcw, ShieldCheck } from "lucide-react";

import {
  axisFetchParsedJson,
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import {
  parseAuditExportBundle,
  parseManufacturingAuditExplorer,
} from "@/lib/runtime-contracts/audit";
import {
  allAuditFilter,
  buildAuditExportFileName,
  buildAuditExportSummary,
  filterAuditEvents,
  formatAuditLabel,
  type AuditFilters,
  type AuditExportBundle,
  type ManufacturingAuditExplorer,
} from "@/lib/audit-demo";
import { stringUrlField, useConsoleUrlState } from "@/lib/console-url-state";
import { strings } from "@/lib/strings";
import {
  buildTenantScopedPath,
  DEMO_TENANT_ID,
  OPERATIONS_API_PREFIX,
} from "@/lib/tenant-scope";
import {
  IDENTITY_SESSION_ENDPOINT,
  useConsoleTenantScope,
} from "@/lib/use-console-tenant-scope";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useAxisQuery } from "@/lib/use-axis-query";
import { buildConnectorSnapshotHref } from "@/lib/connectors-demo";
import { formatContextPath, formatDateTime, formatNumber } from "@/lib/format";
import { deriveSourceState } from "@/lib/source-state";
import {
  formatOverviewTimestamp,
  platformStatusClass,
  platformStatusLabel,
} from "@/lib/platform-overview";
import { useConsole } from "@/providers/console-provider";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { InspectDrawer } from "@/components/ui/inspect-drawer";
import { Select } from "@/components/ui/select";
import { SourcePill } from "@/components/ui/source-pill";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/ui/states";

const AUDIT_EVENTS_ENDPOINT = `${OPERATIONS_API_PREFIX}/audit/events`;
const AUDIT_EXPORT_ENDPOINT = `${OPERATIONS_API_PREFIX}/audit/export`;

const defaultFilters: AuditFilters = {
  tenant: allAuditFilter,
  eventType: allAuditFilter,
  scope: allAuditFilter,
};
const auditUrlSchema = {
  tenant: stringUrlField("tenant", allAuditFilter),
  eventType: stringUrlField("event_type", allAuditFilter),
  scope: stringUrlField("scope", allAuditFilter),
  eventId: stringUrlField("event_id"),
};

/** Serialize the already-fetched export bundle and trigger a client download. */
function downloadAuditExportBundle(bundle: AuditExportBundle) {
  const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = buildAuditExportFileName(bundle);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/**
 * Plain-first integrity/export panel: verification, retention and signature
 * proofs as tone-dotted sentences, raw hashes behind the Inspect drawer, and
 * a real client-side download of the fetched export bundle.
 */
function AuditIntegrityExportPanel({ exportBundle }: { exportBundle: AuditExportBundle }) {
  const copy = strings.audit.integrity;
  const summary = buildAuditExportSummary(exportBundle);
  const inspectRecord: Record<string, unknown> = {
    manifest: exportBundle.manifest,
    retention_policy: exportBundle.retention_policy,
    integrity_proof: exportBundle.integrity_proof,
    ledger_signature: exportBundle.ledger_signature,
    filters: exportBundle.filters,
    retention_notes: exportBundle.retention_notes,
  };

  return (
    <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5 grid gap-4">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow m-0">{copy.eyebrow}</p>
          <h2 className="font-display mx-0 mt-1 mb-1 text-xl text-ink">{copy.title}</h2>
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
            {formatNumber(exportBundle.manifest.record_count)} records, ready to download as{" "}
            {exportBundle.format.toUpperCase()}.
          </p>
          <p className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">
            {exportBundle.manifest.export_id}
          </p>
        </div>
        <div className="flex min-w-0 flex-wrap items-center justify-end gap-3">
          <Button
            className="px-4 py-2 text-sm"
            onClick={() => downloadAuditExportBundle(exportBundle)}
          >
            <Download aria-hidden="true" size={15} />
            {copy.download}
          </Button>
          <InspectDrawer record={inspectRecord} title={copy.inspect} />
        </div>
      </div>

      <ul className="m-0 grid list-none gap-2.5 border-t border-line/60 p-0 pt-3.5 dark:border-white/10">
        {summary.map((line) => (
          <li className="flex min-w-0 items-start gap-2.5" key={line.id}>
            <span
              aria-hidden="true"
              className={`status-dot mt-1.5 ${platformStatusClass(line.tone)}`}
            />
            <span className="grid min-w-0 gap-0.5">
              <span className="text-sm font-medium text-ink break-words">{line.text}</span>
              <span className="text-sm leading-snug text-muted break-words">{line.detail}</span>
            </span>
          </li>
        ))}
      </ul>

      {exportBundle.ledger_signature.notes.length > 0 || exportBundle.retention_notes.length > 0 ? (
        <div className="grid min-w-0 gap-1.5 border-t border-line/60 pt-3.5 dark:border-white/10">
          {[...exportBundle.ledger_signature.notes, ...exportBundle.retention_notes].map((note) => (
            <p className="m-0 text-xs leading-relaxed text-muted break-words" key={note}>
              {note}
            </p>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function AuditExplorer() {
  const [auditExport, setAuditExport] = useState<AuditExportBundle | null>(null);
  const [auditExportError, setAuditExportError] = useState<AxisOperatorError | null>(null);
  const [urlState, setUrlState] = useConsoleUrlState(auditUrlSchema);
  const { refreshNonce } = useConsole();
  const { session } = useOidcConsoleSession();
  const { identity, tenantId, tenantQueriesEnabled } = useConsoleTenantScope();
  const auditEventsPath = buildTenantScopedPath(
    AUDIT_EVENTS_ENDPOINT,
    tenantId ?? DEMO_TENANT_ID,
    { limit: 100 },
  );
  const auditExportPath = buildTenantScopedPath(
    AUDIT_EXPORT_ENDPOINT,
    tenantId ?? DEMO_TENANT_ID,
    { limit: 100, export_reason: "console-review" },
  );
  const auditQuery = useAxisQuery<ManufacturingAuditExplorer>(auditEventsPath, {
    enabled: tenantQueriesEnabled,
    expectedTenantId: tenantId ?? undefined,
    parse: parseManufacturingAuditExplorer,
  });
  const auditData = auditQuery.data;
  const source = deriveSourceState(
    auditQuery.source,
    Boolean(auditData),
    auditData?.provenance,
  );
  const filters: AuditFilters = auditData
    ? {
        tenant: urlState.tenant === allAuditFilter
          || auditData.filter_options.tenants.includes(urlState.tenant)
          ? urlState.tenant
          : allAuditFilter,
        eventType: urlState.eventType === allAuditFilter
          || auditData.filter_options.event_types.includes(urlState.eventType)
          ? urlState.eventType
          : allAuditFilter,
        scope: urlState.scope === allAuditFilter
          || auditData.filter_options.scopes.includes(urlState.scope)
          ? urlState.scope
          : allAuditFilter,
      }
    : defaultFilters;

  useEffect(() => {
    const controller = new AbortController();

    async function loadAuditExport() {
      if (!tenantQueriesEnabled || !tenantId) {
        setAuditExport(null);
        setAuditExportError(null);
        return;
      }

      setAuditExport(null);
      setAuditExportError(null);
      try {
        const exportData = await axisFetchParsedJson<AuditExportBundle>(
          auditExportPath,
          (value) => {
            const parsed = parseAuditExportBundle(value);
            if (parsed.tenant_id !== tenantId) {
              throw new Error("Audit export tenant does not match the verified console tenant.");
            }
            return parsed;
          },
          { session, signal: controller.signal },
        );
        if (!controller.signal.aborted) {
          setAuditExport(exportData);
          setAuditExportError(null);
        }
      } catch (caught) {
        if (!controller.signal.aborted) {
          setAuditExport(null);
          setAuditExportError(toAxisOperatorError(
            caught,
            strings.audit.integrity.error.detail,
          ));
        }
      }
    }

    void loadAuditExport();

    return () => controller.abort();
  }, [auditExportPath, refreshNonce, session, tenantId, tenantQueriesEnabled]);

  const filteredEvents = auditData ? filterAuditEvents(auditData, filters) : [];
  const selectedEvent = urlState.eventId
    ? filteredEvents.find((event) => event.audit_event_id === urlState.eventId)
    : filteredEvents[0];
  const selectedEventConnectorSnapshotHref =
    selectedEvent?.event_type === "connector.evidence_invariants.snapshot_persisted" &&
    selectedEvent.payload_preview.snapshot_id
      ? buildConnectorSnapshotHref({
          snapshotId: selectedEvent.payload_preview.snapshot_id,
          connectorId: selectedEvent.payload_preview.connector_id ?? null,
        })
      : null;

  function updateFilter(filterName: keyof AuditFilters, value: string) {
    setUrlState({ [filterName]: value, eventId: "" });
  }

  function resetFilters() {
    setUrlState({ ...defaultFilters, eventId: "" });
  }

  if (identity.source === "loading") {
    return <LoadingPanel layout="detail" />;
  }

  if (identity.source === "unavailable" || !tenantId) {
    return (
      <ErrorPanel
        detail="The console could not verify the current actor and tenant. Audit data is not loaded until identity is available."
        endpoint={IDENTITY_SESSION_ENDPOINT}
        reference={identity.errorRequestId ?? undefined}
        title="Identity API unavailable"
      />
    );
  }

  if (!auditData) {
    if (source === "loading") {
      return <LoadingPanel layout="detail" />;
    }

    return (
      <ErrorPanel
        detail={strings.audit.error.detail}
        endpoint={auditEventsPath}
        reference={auditQuery.errorRequestId ?? undefined}
        title={strings.audit.error.title}
      />
    );
  }

  if (auditData.events.length === 0) {
    return (
      <EmptyPanel
        detail="Governed actions and decisions will appear here as append-only evidence."
        icon={FileText}
        title="No audit evidence yet"
      />
    );
  }

  if (urlState.eventId && !selectedEvent) {
    return (
      <EmptyPanel
        action={{ label: "Reset filters", onClick: resetFilters }}
        detail={strings.states.requestedRecord.detail}
        icon={Filter}
        title={strings.states.requestedRecord.title}
      />
    );
  }

  if (!selectedEvent) {
    return (
      <EmptyPanel
        action={{ label: "Reset filters", onClick: resetFilters }}
        detail="No audit events match the selected filters."
        icon={Filter}
        title="No matching audit evidence"
      />
    );
  }

  return (
    <div className="grid min-w-0 gap-4">
      <div
        aria-label="Audit source and ledger status"
        className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2"
      >
        <p className="m-0 min-w-0 text-sm leading-snug break-words text-muted">
          {formatContextPath(
            auditData.plant_name,
            auditData.scenario,
            auditData.tenant_id,
          )}
        </p>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <SourcePill state={source} subject="audit ledger" />
          <span className={`status-pill ${platformStatusClass(auditData.ledger_status)}`}>
            <ShieldCheck size={15} />
            {platformStatusLabel(auditData.ledger_status)}
          </span>
          <span className="font-mono text-[13px] break-words text-muted">{formatOverviewTimestamp(auditData.as_of)}</span>
        </div>
      </div>

      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4 [&>*]:min-w-0">
        {auditData.metrics.map((metric) => (
          <article className="min-w-0 rounded-2xl border border-line bg-surface p-4 dark:border-white/10 dark:bg-white/5 min-h-[120px]" key={metric.label}>
            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10">
              <p className="eyebrow m-0">{metric.label}</p>
              <span className={`status-pill ${platformStatusClass(metric.status)}`}>
                {platformStatusLabel(metric.status)}
              </span>
            </div>
            <p className="font-display mx-0 mt-3 mb-1.5 text-2xl tabular-nums break-words text-ink">{metric.value}</p>
            <p className="m-0 text-xs leading-relaxed text-muted break-words">{metric.detail}</p>
          </article>
        ))}
      </div>

      <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow m-0">Filters</p>
          <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">Audit explorer</h2>
        </div>
        <div className="grid w-full min-w-0 gap-2.5 sm:flex sm:w-auto sm:flex-wrap sm:items-end sm:justify-end">
          <Field label="Tenant">
            <Select value={filters.tenant} onChange={(event) => updateFilter("tenant", event.target.value)}>
              <option value={allAuditFilter}>All tenants</option>
              {auditData.filter_options.tenants.map((tenant) => (
                <option key={tenant} value={tenant}>
                  {tenant}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Event">
            <Select
              value={filters.eventType}
              onChange={(event) => updateFilter("eventType", event.target.value)}
            >
              <option value={allAuditFilter}>All events</option>
              {auditData.filter_options.event_types.map((eventType) => (
                <option key={eventType} value={eventType}>
                  {formatAuditLabel(eventType)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Scope">
            <Select value={filters.scope} onChange={(event) => updateFilter("scope", event.target.value)}>
              <option value={allAuditFilter}>All scopes</option>
              {auditData.filter_options.scopes.map((scope) => (
                <option key={scope} value={scope}>
                  {scope}
                </option>
              ))}
            </Select>
          </Field>
          <button className="icon-button" onClick={resetFilters} title="Reset filters" type="button">
            <RotateCcw size={17} />
          </button>
        </div>
      </section>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(310px,0.48fr)_minmax(0,1fr)] [&>*]:min-w-0">
        <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
            <div>
              <p className="eyebrow m-0">Events</p>
              <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">{formatNumber(filteredEvents.length)} visible</h2>
            </div>
            <span className="status-pill signal-ready">
              <Filter size={15} />
              {formatNumber(auditData.events.length)} total
            </span>
          </div>
          {filteredEvents.length === 0 ? (
            <EmptyPanel
              action={{ label: "Reset filters", onClick: resetFilters }}
              detail="Adjust or reset the tenant, event and scope filters to see recorded audit events."
              title="No events match the current filters"
            />
          ) : null}
          <div className="grid">
            {filteredEvents.map((event) => {
              const isSelected = event.audit_event_id === selectedEvent.audit_event_id;

              return (
                <button
                  aria-pressed={isSelected}
                  className={`grid w-full cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-3.5 border-0 border-t border-line/60 bg-transparent px-2.5 py-3.5 text-left text-ink transition-colors first:border-t-0 hover:bg-ink/4 dark:border-white/10 dark:hover:bg-white/6${isSelected ? " bg-signal/10 shadow-[inset_2px_0_0_rgb(var(--signal))] dark:bg-signal/15" : ""}`}
                  key={event.audit_event_id}
                  onClick={() => setUrlState({ eventId: event.audit_event_id })}
                  type="button"
                >
                  <span>
                    <span className="m-0 font-medium text-ink break-words font-mono text-[13px]">{event.event_type}</span>
                    <span className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                      {formatDateTime(event.occurred_at)} / {event.actor_id}
                    </span>
                    <span className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{event.scope}</span>
                  </span>
                  <span className={`status-pill ${platformStatusClass(event.severity)}`}>
                    {event.result}
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5 grid gap-4">
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
            <div>
              <p className="eyebrow m-0">{selectedEvent.category}</p>
              <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">{formatAuditLabel(selectedEvent.event_type)}</h2>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{selectedEvent.summary}</p>
            </div>
            <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
              <span className={`status-pill ${platformStatusClass(selectedEvent.severity)}`}>
                {platformStatusLabel(selectedEvent.severity)}
              </span>
              <span className="status-pill status-checking">{selectedEvent.result}</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3.5 border-y border-line/60 py-3.5 xl:grid-cols-4 dark:border-white/10 [&>*]:min-w-0">
            <div>
              <p className="eyebrow m-0">Audit Event</p>
              <p className="m-0 font-medium text-ink break-words font-mono text-[13px]">{selectedEvent.audit_event_id}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{selectedEvent.event_type}</p>
            </div>
            <div>
              <p className="eyebrow m-0">Actor</p>
              <p className="m-0 font-medium text-ink break-words">{selectedEvent.actor_id}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{selectedEvent.actor_type}</p>
            </div>
            <div>
              <p className="eyebrow m-0">Scope</p>
              <p className="m-0 font-medium text-ink break-words font-mono text-[13px]">{selectedEvent.scope}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{selectedEvent.permission_scope}</p>
            </div>
            <div>
              <p className="eyebrow m-0">Source</p>
              <p className="m-0 font-medium text-ink break-words">{selectedEvent.source}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{selectedEvent.domain}</p>
            </div>
            <div>
              <p className="eyebrow m-0">Occurred</p>
              <p className="m-0 font-medium text-ink break-words">{formatDateTime(selectedEvent.occurred_at)}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{selectedEvent.data_classification}</p>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
            <section>
              <p className="eyebrow m-0">Related</p>
              <div className="flex min-w-0 flex-wrap gap-2">
                {[
                  selectedEvent.related_workflow_id,
                  selectedEvent.related_approval_id,
                  selectedEvent.related_agent_id,
                ]
                  .filter(Boolean)
                  .map((item) => (
                    <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5" key={item}>
                      {item}
                    </span>
                  ))}
              </div>
            </section>
            <section>
              <p className="eyebrow m-0">Evidence</p>
              <div className="flex min-w-0 flex-wrap gap-2">
                {selectedEvent.evidence_refs.map((item) => (
                  <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5" key={item}>
                    {item}
                  </span>
                ))}
              </div>
            </section>
          </div>

          <section className="grid min-w-0 gap-3 border-t border-line/60 pt-3.5 dark:border-white/10">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
              <div>
                <p className="eyebrow m-0">Payload Preview</p>
                <h3 className="font-display mx-0 mt-1 mb-0 text-lg text-ink">Redacted fields</h3>
              </div>
              {selectedEventConnectorSnapshotHref ? (
                <a className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words" href={selectedEventConnectorSnapshotHref}>
                  Connector snapshot
                </a>
              ) : (
                <FileText size={18} />
              )}
            </div>
            <div className="grid min-w-0 gap-2">
              {Object.entries(selectedEvent.payload_preview).map(([key, value]) => (
                <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5" key={key}>
                  <span className="eyebrow m-0">{formatAuditLabel(key)}</span>
                  <span className="font-mono text-[13px] break-words">{value}</span>
                </div>
              ))}
            </div>
          </section>
        </section>
      </div>

      <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
        <p className="eyebrow m-0">Retention Notes</p>
        <div className="grid min-w-0 gap-2.5">
          {auditData.retention_notes.map((note) => (
            <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words" key={note}>
              {note}
            </p>
          ))}
        </div>
      </section>

      {auditExport ? (
        <AuditIntegrityExportPanel exportBundle={auditExport} />
      ) : (
        <ErrorPanel
          detail={strings.audit.integrity.error.detail}
          endpoint={auditExportPath}
          reference={auditExportError?.requestId ?? undefined}
          title={strings.audit.integrity.error.title}
        />
      )}
    </div>
  );
}
