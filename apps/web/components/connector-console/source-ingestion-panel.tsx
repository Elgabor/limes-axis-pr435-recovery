"use client";

import { useState } from "react";
import { FileClock } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { InlineOperatorError } from "@/components/ui/inline-operator-error";
import { Input } from "@/components/ui/input";
import {
  AxisApiDecodeError,
  AxisApiError,
  axisFetch,
  axisResponseRequestId,
  readAxisResponseBody,
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import {
  buildSourceIngestionCancelRequest,
  buildSourceIngestionRedispatchRequest,
  buildSourceIngestionReadPath,
  buildSourceIngestionRequest,
  SOURCE_EXTRACTION_BATCHES_ENDPOINT,
  SOURCE_EXTRACTION_RECONCILIATION_ENDPOINT,
  SOURCE_INGESTION_ENDPOINTS,
} from "@/lib/connectors-console";
import { safeRandomUuid } from "@/lib/ids";
import { fillTemplate, formatTimestamp } from "@/lib/format";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import {
  parseSourceExtractionBatchesPage,
  parseSourceExtractionReconciliationReport,
  parseSourceIngestionEligibilityView,
  parseSourceIngestionOverview,
  parseSourceIngestionRequestView,
  parseSourceIngestionRequestViews,
  type SourceIngestionEligibilityRow,
  type SourceIngestionRequestView,
} from "@/lib/runtime-contracts/connectors";
import { strings } from "@/lib/strings";
import { useConsole } from "@/providers/console-provider";
import { useToast } from "@/components/ui/toast";
import { deriveGovernedActor } from "@/lib/governed-action";
import { buildTenantScopedPath } from "@/lib/tenant-scope";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useAxisQuery } from "@/lib/use-axis-query";

/*
 * Governed ingestion requests for the external database connector. Both lists
 * are persisted server truth reloaded through the refresh bus — never session
 * state. Every state shown is one the API actually reported. The validation
 * stage dials nothing; the extraction stage, when the server advertises it,
 * performs one bounded read-only read per bound table and stores payloads in
 * the governed object store — this UI only ever shows counts, digests and
 * watermarks, and says so.
 */

type EligibilityRow = SourceIngestionEligibilityRow;
type Stage = "validate" | "extract";

function eligibilityPill(row: EligibilityRow): { label: string; className: string } {
  const copy = strings.connectors.sourceIngestion;
  if (row.eligible) {
    return { label: copy.eligiblePill, className: "signal-ready" };
  }
  return {
    label: copy.blockedReasons[row.blocked_reason ?? ""] ?? copy.blockedPill,
    className:
      row.blocked_reason === "stale_fingerprint"
        ? "signal-action-required"
        : "status-checking",
  };
}

function PreflightRow({ met, label }: { met: boolean; label: string }) {
  return (
    <li className="flex min-w-0 flex-wrap items-center justify-between gap-2">
      <span className="min-w-0 break-words text-xs text-ink">{label}</span>
      <span className={`status-pill ${met ? "signal-ready" : "status-checking"}`}>
        {met ? "Yes" : "Off"}
      </span>
    </li>
  );
}

function requestStatusPill(status: string): { label: string; className: string } {
  const pills = strings.connectors.sourceIngestion.statusPills;
  switch (status) {
    case "completed":
      return { label: pills.completed, className: "signal-ready" };
    case "failed":
      return { label: pills.failed, className: "signal-action-required" };
    case "dispatching":
      return { label: pills.dispatching, className: "signal-watch" };
    case "cancelled":
      return { label: pills.cancelled, className: "status-checking" };
    default:
      return { label: pills.pending ?? status, className: "status-checking" };
  }
}

/** Operator copy per API failure class; unknown reasons stay honest. */
function ingestionErrorCopy(error: AxisOperatorError): string {
  const copy = strings.connectors.sourceIngestion;
  if (error.status === 403) {
    return error.reason?.startsWith("missing_scope:") ? copy.deniedScope : copy.forbidden;
  }
  if (error.status === 409) {
    return error.reason === "cancel_conflict" ? copy.conflictMessage : copy.conflict;
  }
  if (error.status === 404) {
    return copy.notFound;
  }
  if (error.status === 422) {
    return copy.validationFailed;
  }
  return copy.genericError;
}

/**
 * Daily operator landing read model for this connector's ingestion activity:
 * plain-language aggregates over server truth, never session state. Every line
 * names what needs attention and, where relevant, what to do next.
 */
function IngestionOverviewStrip({
  tenantId,
  connectorId,
}: {
  tenantId: string;
  connectorId: string;
}) {
  const copy = strings.connectors.sourceIngestion;
  const path = buildSourceIngestionReadPath({
    endpoint: SOURCE_INGESTION_ENDPOINTS.overview,
    tenantId,
    connectorId,
  });
  const overviewQuery = useAxisQuery(path, {
    expectedTenantId: tenantId,
    parse: parseSourceIngestionOverview,
  });

  if (overviewQuery.isUnavailable || overviewQuery.isTenantNotFound || !overviewQuery.data) {
    return (
      <p className="m-0 text-xs text-muted">
        {copy.overviewUnavailable}
      </p>
    );
  }
  const { summary } = overviewQuery.data;
  if (summary.total_count === 0) {
    return (
      <p
        className="m-0 max-w-prose text-sm leading-snug text-muted"
        data-testid="source-ingestion-overview"
      >
        {copy.overviewQuiet}
      </p>
    );
  }
  const working = summary.status_counts["dispatching"] ?? 0;
  const pending = summary.status_counts["pending"] ?? 0;
  const lines: Array<{ label: string; tone: string }> = [];
  if (summary.dead_lettered_count > 0) {
    lines.push({
      label: fillTemplate(copy.overviewNeedsAttention, { count: summary.dead_lettered_count }),
      tone: "signal-action-required",
    });
  }
  if (working > 0) {
    lines.push({ label: fillTemplate(copy.overviewWorking, { count: working }), tone: "signal-watch" });
  }
  if (pending > 0) {
    lines.push({ label: fillTemplate(copy.overviewPending, { count: pending }), tone: "status-checking" });
  }
  return (
    <div className="grid gap-1" data-testid="source-ingestion-overview">
      <ul aria-label={copy.overviewTitle} className="m-0 flex list-none flex-wrap gap-2 p-0">
        {lines.map((line) => (
          <li className={`status-pill ${line.tone}`} key={line.label}>
            {line.label}
          </li>
        ))}
        {lines.length === 0 ? (
          <li className="status-pill signal-ready">{copy.overviewQuiet}</li>
        ) : null}
      </ul>
      <p className="m-0 font-mono text-[11px] break-all text-muted">
        {fillTemplate(copy.overviewTotals, {
          total: summary.total_count,
          extract: summary.extract_stage_count,
          activity: summary.last_activity_at
            ? formatTimestamp(summary.last_activity_at)
            : copy.overviewNever,
        })}
      </p>
    </div>
  );
}

export function ConnectorSourceIngestionSection({
  connectorId,
  identitySession,
  tenantId,
}: {
  connectorId: string;
  identitySession: IdentitySessionReadModel | null;
  tenantId: string;
}) {
  const copy = strings.connectors.sourceIngestion;
  const { triggerRefresh } = useConsole();
  const { push } = useToast();
  const { session } = useOidcConsoleSession();
  const { actorId, ssoBlocked } = deriveGovernedActor(
    identitySession,
    "connector-console-operator",
  );

  const eligibilityPath = buildSourceIngestionReadPath({
    endpoint: SOURCE_INGESTION_ENDPOINTS.eligibility,
    tenantId,
    connectorId,
  });
  const requestsPath = buildSourceIngestionReadPath({
    endpoint: SOURCE_INGESTION_ENDPOINTS.requests,
    tenantId,
    connectorId,
  });
  const eligibilityQuery = useAxisQuery(eligibilityPath, {
    expectedTenantId: tenantId,
    parse: parseSourceIngestionEligibilityView,
  });
  const requestsQuery = useAxisQuery(requestsPath, {
    expectedTenantId: tenantId,
    parse: parseSourceIngestionRequestViews,
  });

  // Only bindings the API currently reports eligible can be selected; the map
  // is pruned against fresh eligibility so stale rows can never be submitted.
  const [selectedBindings, setSelectedBindings] = useState<Map<string, string>>(
    () => new Map(),
  );
  const [stage, setStage] = useState<Stage>("validate");
  const [requestId, setRequestId] = useState(
    () => `ingest_console_${safeRandomUuid().replaceAll("-", "")}`,
  );
  const [reason, setReason] = useState("");
  type BusyAction =
    | { kind: "create" }
    | { kind: "cancel"; requestId: string }
    | { kind: "requeue"; requestId: string };
  const [pendingAction, setPendingAction] = useState<BusyAction | null>(null);
  const [outcome, setOutcome] = useState<{ replayed: boolean } | null>(null);
  const [openRequestIds, setOpenRequestIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [redispatch, setRedispatch] = useState<{
    requestId: string;
    reason: string;
    idempotencyKey: string;
  } | null>(null);
  const [error, setError] = useState<AxisOperatorError | null>(null);

  const eligibilityData = eligibilityQuery.data;
  const eligibleRows = eligibilityData?.rows.filter((row) => row.eligible) ?? [];
  const extractionAvailable = eligibilityData?.extraction_available ?? false;
  const effectiveStage: Stage = extractionAvailable ? stage : "validate";
  const selectedCount = selectedBindings.size;
  const reasonValid = reason.trim().length > 0;
  const requestIdValid = requestId.trim().length > 0;
  const canSubmit =
    !ssoBlocked && pendingAction === null && selectedCount > 0 && reasonValid && requestIdValid;

  function toggleBinding(row: EligibilityRow) {
    setSelectedBindings((current) => {
      const next = new Map(current);
      if (next.has(row.binding_id)) {
        next.delete(row.binding_id);
      } else {
        next.set(row.binding_id, row.resource_name);
      }
      return next;
    });
  }

  async function submit() {
    if (!canSubmit || ssoBlocked) {
      return;
    }
    setPendingAction({ kind: "create" });
    setError(null);
    setOutcome(null);
    try {
      const response = await axisFetch(SOURCE_INGESTION_ENDPOINTS.requests, {
        method: "POST",
        session,
        body: buildSourceIngestionRequest({
          tenantId,
          actorId,
          requestId,
          reason,
          bindingIds: [...selectedBindings.keys()],
          stage: effectiveStage,
        }),
      });
      const apiRequestId = axisResponseRequestId(response);
      const responseBody = await readAxisResponseBody(response);
      if (!response.ok) {
        throw new AxisApiError(SOURCE_INGESTION_ENDPOINTS.requests, response.status, {
          body: responseBody,
          requestId: apiRequestId,
        });
      }
      const view: SourceIngestionRequestView =
        parseSourceIngestionRequestView(responseBody);
      const replayed = view.outcome === "replayed";
      setOutcome({ replayed });
      setReason("");
      setSelectedBindings(new Map());
      setRequestId(`ingest_console_${safeRandomUuid().replaceAll("-", "")}`);
      triggerRefresh();
      push({
        title: replayed ? copy.createdStatus.replayed : copy.createdStatus.created,
        detail: `${copy.requestColumn}: ${view.request_id}`,
        tone: replayed ? "neutral" : "positive",
      });
    } catch (caught) {
      if (caught instanceof AxisApiError || caught instanceof AxisApiDecodeError) {
        const operatorError = toAxisOperatorError(caught, copy.genericError);
        setError({ ...operatorError, message: ingestionErrorCopy(operatorError) });
      } else {
        setError({
          code: null,
          reason: null,
          message: copy.genericError,
          requestId: null,
          status: null,
        });
      }
    } finally {
      setPendingAction(null);
    }
  }

  async function cancel(requestIdToCancel: string) {
    if (pendingAction !== null || ssoBlocked) {
      return;
    }
    setPendingAction({ kind: "cancel", requestId: requestIdToCancel });
    setError(null);
    try {
      const response = await axisFetch(
        `${SOURCE_INGESTION_ENDPOINTS.requests}/${encodeURIComponent(requestIdToCancel)}/cancel`,
        {
          method: "POST",
          session,
          body: buildSourceIngestionCancelRequest({ tenantId, actorId }),
        },
      );
      const apiRequestId = axisResponseRequestId(response);
      const responseBody = await readAxisResponseBody(response);
      if (!response.ok) {
        throw new AxisApiError(
          `${SOURCE_INGESTION_ENDPOINTS.requests}/${requestIdToCancel}/cancel`,
          response.status,
          { body: responseBody, requestId: apiRequestId },
        );
      }
      triggerRefresh();
      push({ title: copy.cancelledStatus, detail: `${copy.requestColumn}: ${requestIdToCancel}`, tone: "neutral" });
    } catch (caught) {
      if (caught instanceof AxisApiError || caught instanceof AxisApiDecodeError) {
        const operatorError = toAxisOperatorError(caught, copy.genericError);
        setError({ ...operatorError, message: ingestionErrorCopy(operatorError) });
      } else {
        setError({
          code: null,
          reason: null,
          message: copy.genericError,
          requestId: null,
          status: null,
        });
      }
    } finally {
      setPendingAction(null);
    }
  }

  async function requeue(requestIdToRequeue: string) {
    if (
      pendingAction !== null
      || ssoBlocked
      || redispatch?.requestId !== requestIdToRequeue
      || !redispatch.reason.trim()
      || !redispatch.idempotencyKey.trim()
    ) {
      return;
    }
    setPendingAction({ kind: "requeue", requestId: requestIdToRequeue });
    setError(null);
    try {
      const response = await axisFetch(
        `${SOURCE_INGESTION_ENDPOINTS.requests}/${encodeURIComponent(requestIdToRequeue)}/requeue`,
        {
          method: "POST",
          session,
          body: buildSourceIngestionRedispatchRequest({
            tenantId,
            actorId,
            reason: redispatch.reason,
            idempotencyKey: redispatch.idempotencyKey,
          }),
        },
      );
      const apiRequestId = axisResponseRequestId(response);
      const responseBody = await readAxisResponseBody(response);
      if (!response.ok) {
        throw new AxisApiError(
          `${SOURCE_INGESTION_ENDPOINTS.requests}/${requestIdToRequeue}/requeue`,
          response.status,
          { body: responseBody, requestId: apiRequestId },
        );
      }
      triggerRefresh();
      push({
        title: copy.requeuedStatus,
        detail: `${copy.requestColumn}: ${requestIdToRequeue}`,
        tone: "positive",
      });
      setRedispatch(null);
    } catch (caught) {
      if (caught instanceof AxisApiError || caught instanceof AxisApiDecodeError) {
        const operatorError = toAxisOperatorError(caught, copy.genericError);
        setError({ ...operatorError, message: ingestionErrorCopy(operatorError) });
      } else {
        setError({
          code: null,
          reason: null,
          message: copy.genericError,
          requestId: null,
          status: null,
        });
      }
    } finally {
      setPendingAction(null);
    }
  }

  const requests: SourceIngestionRequestView[] = requestsQuery.data ?? [];

  return (
    <section
      aria-label={copy.title}
      className="grid gap-3 border-t border-line/60 pt-4 dark:border-white/10"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <FileClock aria-hidden="true" className="shrink-0 text-signal" size={16} />
        <Eyebrow>{copy.title}</Eyebrow>
      </div>
      <p
        className="m-0 max-w-prose rounded-2xl border border-line px-4 py-3 text-sm leading-snug text-muted dark:border-white/10"
        data-testid="source-ingestion-validation-note"
      >
        {copy.validationOnlyNote}
      </p>
      <IngestionOverviewStrip connectorId={connectorId} tenantId={tenantId} />
      {extractionAvailable ? (
        <p className="m-0 max-w-prose text-xs leading-snug text-muted">
          {copy.extractionAvailableNote}
        </p>
      ) : null}
      <section
        aria-label={copy.preflightTitle}
        className="grid gap-1 rounded-2xl border border-line/60 px-4 py-3 dark:border-white/10"
      >
        <Eyebrow>{copy.preflightTitle}</Eyebrow>
        <ul aria-label={copy.preflightTitle} className="m-0 grid list-none gap-1 p-0">
          <PreflightRow
            met={extractionAvailable}
            label={
              extractionAvailable ? copy.preflightExtractOn : copy.preflightExtractOff
            }
          />
          <PreflightRow met label={copy.preflightReasonReady} />
        </ul>
      </section>

      {eligibilityQuery.isUnavailable || eligibilityQuery.isTenantNotFound ? (
        <p className="m-0 text-sm text-muted">
          {copy.unavailableTitle}: {copy.unavailableDetail}
        </p>
      ) : eligibilityQuery.isLoading ? (
        <div aria-hidden="true" className="h-10 animate-pulse rounded-xl bg-line/40" />
      ) : (
        <div className="grid gap-2">
          <div className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <Eyebrow>{copy.eligibilityTitle}</Eyebrow>
            {extractionAvailable && eligibilityData?.planned_limits ? (
              <span className="font-mono text-[11px] break-all text-muted">
                {copy.plannedLimitsLabel}:{" "}
                {Object.entries(eligibilityData.planned_limits)
                  .map(([key, value]) => `${key}≤${value}`)
                  .join(" · ")}
              </span>
            ) : null}
          </div>
          {(eligibilityData?.rows ?? []).length === 0 ? (
            <p className="m-0 max-w-prose text-sm leading-snug text-muted">
              {copy.emptyDetail}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table
                aria-label={copy.eligibilityTitle}
                className="w-full min-w-[560px] border-collapse text-left text-sm"
              >
                <thead>
                  <tr className="border-b border-line dark:border-white/10">
                    <th className="px-2 py-2 font-medium">{copy.selectColumn}</th>
                    <th className="px-2 py-2 font-medium">{copy.tableColumn}</th>
                    <th className="px-2 py-2 font-medium">{copy.fingerprintColumn}</th>
                    <th className="px-2 py-2 font-medium">{copy.stateColumn}</th>
                  </tr>
                </thead>
                <tbody>
                  {(eligibilityData?.rows ?? []).map((row) => {
                    const pill = eligibilityPill(row);
                    return (
                      <tr
                        className="border-b border-line/60 last:border-b-0 dark:border-white/10"
                        key={row.binding_id}
                      >
                        <td className="px-2 py-2 align-top">
                          {row.eligible ? (
                            <input
                              aria-label={`${copy.selectColumn}: ${row.resource_name}`}
                              checked={selectedBindings.has(row.binding_id)}
                              className="-m-2 size-4 cursor-pointer p-2 accent-[rgb(var(--signal))]"
                              onChange={() => toggleBinding(row)}
                              type="checkbox"
                            />
                          ) : (
                            <span aria-hidden="true" className="text-xs text-muted">—</span>
                          )}
                        </td>
                        <td className="px-2 py-2 font-mono text-xs break-all">
                          {row.resource_name}
                        </td>
                        <td
                          className="px-2 py-2 font-mono text-xs break-all text-muted"
                          title={row.schema_fingerprint}
                        >
                          {row.schema_fingerprint.slice(0, 12)}
                        </td>
                        <td className="px-2 py-2">
                          <span className={`status-pill ${pill.className}`}>{pill.label}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {ssoBlocked ? (
        <p className="m-0 text-sm leading-snug text-muted" role="status">
          {copy.ssoGate}
        </p>
      ) : eligibilityQuery.source === "api" && eligibleRows.length > 0 ? (
        <form
          aria-label={copy.createAction}
          className="grid gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div className="grid gap-1">
            <label className="text-xs font-medium text-muted" htmlFor="source-ingestion-request-id">
              {copy.requestIdLabel}
            </label>
            <Input
              autoComplete="off"
              className="max-w-md font-mono text-xs"
              id="source-ingestion-request-id"
              onChange={(event) => setRequestId(event.target.value)}
              value={requestId}
            />
          </div>
          <div className="grid gap-1">
            <label className="text-xs font-medium text-muted" htmlFor="source-ingestion-reason">
              {copy.reasonLabel}
            </label>
            <Input
              aria-describedby="source-ingestion-form-hint"
              autoComplete="off"
              className="max-w-md"
              id="source-ingestion-reason"
              maxLength={600}
              onChange={(event) => setReason(event.target.value)}
              placeholder={copy.reasonPlaceholder}
              value={reason}
            />
          </div>
          {extractionAvailable ? (
            <div className="grid gap-1">
              <label className="text-xs font-medium text-muted" htmlFor="source-ingestion-stage">
                {copy.stageLabels[effectiveStage]}
              </label>
              <select
                className="max-w-md min-h-9 rounded-lg border border-line bg-surface px-3 text-sm text-ink focus:border-signal focus:outline-none focus:ring-2 focus:ring-signal/25 dark:border-white/15 dark:bg-white/5"
                id="source-ingestion-stage"
                onChange={(event) => setStage(event.target.value as Stage)}
                value={effectiveStage}
              >
                <option value="validate">{copy.stageLabels.validate}</option>
                <option value="extract">{copy.stageLabels.extract}</option>
              </select>
            </div>
          ) : null}
          <p className="m-0 max-w-prose text-xs leading-snug text-muted" id="source-ingestion-form-hint">
            {copy.formHint}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              disabled={!canSubmit}
              loading={pendingAction?.kind === "create"}
              type="submit"
            >
              {pendingAction?.kind === "create" ? copy.creatingAction : copy.createAction}
            </Button>
            <span aria-live="polite" className="text-xs text-muted" role="status">
              {outcome
                ? outcome.replayed
                  ? copy.createdStatus.replayed
                  : copy.createdStatus.created
                : ""}
            </span>
          </div>
        </form>
      ) : null}

      {requestsQuery.isUnavailable || requestsQuery.isTenantNotFound ? (
        <p className="m-0 text-sm text-muted">
          {copy.unavailableTitle}: {copy.unavailableDetail}
        </p>
      ) : requestsQuery.isLoading ? (
        <div aria-hidden="true" className="h-10 animate-pulse rounded-xl bg-line/40" />
      ) : (
        <section aria-label={copy.title} className="grid gap-2">
          {requests.length === 0 ? (
            <p className="m-0 max-w-prose text-sm leading-snug text-muted">{copy.emptyDetail}</p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table
                  aria-label={copy.title}
                  className="w-full min-w-[560px] border-collapse text-left text-sm"
                >
                  <thead>
                    <tr className="border-b border-line dark:border-white/10">
                      <th className="px-2 py-2 font-medium">{copy.requestColumn}</th>
                      <th className="px-2 py-2 font-medium">{copy.stageHeader}</th>
                      <th className="px-2 py-2 font-medium">{copy.stateColumn}</th>
                      <th className="px-2 py-2 font-medium">{copy.attemptsColumn}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {requests.map((request) => {
                      const pill = requestStatusPill(request.status);
                      const deadLettered = request.dead_lettered_at !== null;
                      return (
                        <tr
                          className="border-b border-line/60 last:border-b-0 dark:border-white/10"
                          key={request.request_id}
                        >
                          <td className="px-2 py-2 font-mono text-xs break-all">
                            {request.request_id}
                          </td>
                          <td className="px-2 py-2 text-xs">
                            {copy.stageLabels[request.stage]}
                          </td>
                          <td className="px-2 py-2">
                            <span className={`status-pill ${pill.className}`}>{pill.label}</span>
                            {deadLettered ? (
                              <>
                                {" "}
                                <span className={`status-pill ${pill.className}`}>
                                  {copy.deadLetteredPill}
                                </span>
                              </>
                            ) : null}
                          </td>
                          <td className="px-2 py-2 font-mono text-xs">{request.attempt_count}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {requests.map((request) => (
                <details
                  className="rounded-xl border border-line/60 px-3 py-2 dark:border-white/10"
                  key={`${request.request_id}-detail`}
                  onToggle={(event) => {
                    const open = (event.target as HTMLDetailsElement).open;
                    setOpenRequestIds((current) => {
                      const next = new Set(current);
                      if (open) {
                        next.add(request.request_id);
                      } else {
                        next.delete(request.request_id);
                      }
                      return next;
                    });
                  }}
                >
                  <summary className="cursor-pointer text-sm font-medium">
                    {copy.requestColumn}:{" "}
                    <span className="font-mono text-xs break-all">{request.request_id}</span>
                  </summary>
                  <dl
                    className="mt-2 grid gap-1.5 text-xs leading-snug"
                    data-request-detail={request.request_id}
                  >
                    <div className="flex min-w-0 flex-wrap gap-x-2">
                      <dt className="font-medium">{copy.reasonHeader}:</dt>
                      <dd className="m-0 min-w-0 break-words text-muted">{request.reason}</dd>
                    </div>
                    <div className="flex min-w-0 flex-wrap gap-x-2">
                      <dt className="font-medium">{copy.selectionsLabel}:</dt>
                      <dd className="m-0 min-w-0">
                        <ul className="m-0 grid list-none gap-y-1 p-0 md:flex md:flex-wrap md:gap-x-3">
                          {request.selections.map((selection) => (
                            <li
                              className="font-mono break-all text-muted"
                              data-selection-resource={selection.resource_name}
                              key={selection.binding_id}
                            >
                              {selection.resource_name}
                            </li>
                          ))}
                        </ul>
                      </dd>
                    </div>
                    {request.extraction ? (
                      <div className="flex min-w-0 flex-wrap gap-x-2">
                        <dt className="font-medium">{copy.batchesLabel}:</dt>
                        <dd className="m-0 font-mono text-muted">
                          {request.extraction.batch_count} · {copy.batchRowsLabel}:{" "}
                          {request.extraction.total_rows} · {copy.batchTruncatedLabel}:{" "}
                          {request.extraction.truncated_any ? copy.yesPill : copy.noPill}
                        </dd>
                      </div>
                    ) : null}
                    {request.last_error !== null ? (
                      <div className="flex min-w-0 flex-wrap gap-x-2">
                        <dt className="font-medium">{copy.lastErrorLabel}:</dt>
                        <dd className="m-0 font-mono break-all text-muted">{request.last_error}</dd>
                      </div>
                    ) : null}
                  </dl>
                  {request.attempts.length > 0 ? (
                    <section
                      aria-label={copy.attemptsLabel}
                      className="mt-2 grid gap-1 border-t border-line/60 pt-2 dark:border-white/10"
                      data-testid={`attempts-${request.request_id}`}
                    >
                      <Eyebrow>{copy.attemptsLabel}</Eyebrow>
                      <ol className="m-0 grid list-none gap-1 p-0 text-xs leading-snug">
                        {request.attempts.map((attempt, attemptIndex) => (
                          <li
                            className="flex min-w-0 flex-wrap items-baseline gap-x-2"
                            /* Position-prefixed: re-dispatch cycles restart
                               attempt numbering, so number+outcome alone can
                               collide across historical entries. */
                            key={`${attemptIndex}-${attempt.attempt_number}-${attempt.outcome}`}
                          >
                            <span
                              className={`status-pill ${
                                attempt.outcome === "completed"
                                  ? "signal-ready"
                                  : attempt.outcome === "dead_lettered"
                                    ? "signal-action-required"
                                    : "signal-watch"
                              }`}
                            >
                              #{attempt.attempt_number}{" "}
                              {copy.attemptOutcome[attempt.outcome] ?? attempt.outcome}
                            </span>
                            {attempt.error_code ? (
                              <span className="font-mono break-all text-muted">
                                {attempt.error_code}
                              </span>
                            ) : (
                              <span className="text-muted">
                                {attempt.selections.filter((s) => s.outcome === "validated").length}
                                /{attempt.selections.length}{" "}
                                {copy.attemptSelectionValidated}
                              </span>
                            )}
                          </li>
                        ))}
                      </ol>
                      {request.attempts_truncated ? (
                        <p
                          className="m-0 text-[11px] leading-snug text-muted"
                          data-testid={`attempts-truncated-${request.request_id}`}
                        >
                          {copy.attemptsTruncatedNotice}
                        </p>
                      ) : null}
                    </section>
                  ) : null}
                  {openRequestIds.has(request.request_id) ? (
                    <ExtractionBatchesEvidence
                      requestId={request.request_id}
                      session={session}
                      tenantId={tenantId}
                    />
                  ) : null}
                  {request.status === "pending" ? (
                    <div className="mt-2">
                      <Button
                        disabled={pendingAction !== null}
                        loading={
                          pendingAction?.kind === "cancel"
                          && pendingAction.requestId === request.request_id
                        }
                        onClick={() => void cancel(request.request_id)}
                        variant="secondary"
                      >
                        {pendingAction?.kind === "cancel"
                          && pendingAction.requestId === request.request_id
                          ? copy.cancellingAction
                          : copy.cancelAction}
                      </Button>
                    </div>
                  ) : null}
                  {openRequestIds.has(request.request_id)
                    && request.status === "failed"
                    && request.dead_lettered_at !== null
                    ? (
                    <form
                      aria-label={copy.redispatchAction}
                      className="mt-2 grid gap-1.5 border-t border-line/60 pt-2 dark:border-white/10"
                      onSubmit={(event) => {
                        event.preventDefault();
                        void requeue(request.request_id);
                      }}
                    >
                      <p className="m-0 max-w-prose text-[11px] leading-snug text-muted">
                        {copy.redispatchHint}
                      </p>
                      <label
                        className="text-xs font-medium text-muted"
                        htmlFor={`redispatch-reason-${request.request_id}`}
                      >
                        {copy.redispatchReasonLabel}
                      </label>
                      <Input
                        autoComplete="off"
                        className="max-w-md"
                        id={`redispatch-reason-${request.request_id}`}
                        maxLength={600}
                        onChange={(event) =>
                          setRedispatch({
                            requestId: request.request_id,
                            reason: event.target.value,
                            idempotencyKey:
                              redispatch?.requestId === request.request_id
                                ? redispatch.idempotencyKey
                                : `requeue_${safeRandomUuid().replaceAll("-", "")}`,
                          })
                        }
                        value={
                          redispatch?.requestId === request.request_id
                            ? redispatch.reason
                            : ""
                        }
                      />
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          disabled={
                            pendingAction !== null
                            || redispatch?.requestId !== request.request_id
                            || !redispatch.reason.trim()
                          }
                          loading={
                            pendingAction?.kind === "requeue"
                            && pendingAction.requestId === request.request_id
                          }
                          type="submit"
                          variant="secondary"
                        >
                          {pendingAction?.kind === "requeue"
                            && pendingAction.requestId === request.request_id
                            ? copy.redispatchingAction
                            : copy.redispatchAction}
                        </Button>
                      </div>
                    </form>
                  ) : null}
                </details>
              ))}
            </>
          )}
        </section>
      )}

      {error ? <InlineOperatorError error={error} /> : null}
    </section>
  );
}


function ExtractionBatchesEvidence({
  requestId,
  tenantId,
  session,
}: {
  requestId: string;
  tenantId: string;
  session: ReturnType<typeof useOidcConsoleSession>["session"];
}) {
  const copy = strings.connectors.sourceIngestion;
  const path = buildTenantScopedPath(
    SOURCE_EXTRACTION_BATCHES_ENDPOINT(requestId),
    tenantId,
  );
  const batchesQuery = useAxisQuery(path, {
    expectedTenantId: tenantId,
    parse: parseSourceExtractionBatchesPage,
  });
  const [reconState, setReconState] = useState<
    | { kind: "idle" }
    | { kind: "loading" }
    | { kind: "report"; payload: ReturnType<typeof parseSourceExtractionReconciliationReport> }
    | { kind: "unsupported" }
  >({ kind: "idle" });

  async function checkStorage() {
    setReconState({ kind: "loading" });
    try {
      const response = await axisFetch(
        buildTenantScopedPath(
          SOURCE_EXTRACTION_RECONCILIATION_ENDPOINT(requestId),
          tenantId,
        ),
        { method: "GET", session },
      );
      const responseBody = await readAxisResponseBody(response);
      if (!response.ok) {
        if (
          response.status === 409
          && (responseBody as { detail?: { reason?: string } })?.detail?.reason
            === "store_adapter_unsupported"
        ) {
          setReconState({ kind: "unsupported" });
          return;
        }
        setReconState({ kind: "idle" });
        return;
      }
      setReconState({
        kind: "report",
        payload: parseSourceExtractionReconciliationReport(responseBody),
      });
    } catch {
      setReconState({ kind: "idle" });
    }
  }

  if (batchesQuery.isLoading) {
    return (
      <div aria-hidden="true" className="mt-2 h-8 animate-pulse rounded-lg bg-line/40" />
    );
  }
  if (batchesQuery.isUnavailable || !batchesQuery.data || batchesQuery.data.batches.length === 0) {
    return null;
  }
  const page = batchesQuery.data;

  return (
    <div className="mt-2 grid gap-2">
      <Eyebrow>{copy.batchesTitle}</Eyebrow>
      <div className="overflow-x-auto">
        <table
          aria-label={`${copy.batchesTitle}: ${requestId}`}
          className="w-full min-w-[520px] border-collapse text-left text-xs"
        >
          <thead>
            <tr className="border-b border-line dark:border-white/10">
              <th className="px-2 py-1.5 font-medium">{copy.batchColumn}</th>
              <th className="px-2 py-1.5 font-medium">{copy.rowsLabel}</th>
              <th className="px-2 py-1.5 font-medium">{copy.truncatedLabel}</th>
              <th className="px-2 py-1.5 font-medium">{copy.orderingLabel}</th>
              <th className="px-2 py-1.5 font-medium">{copy.digestLabel}</th>
            </tr>
          </thead>
          <tbody>
            {page.batches.map((batch) => (
              <tr
                className="border-b border-line/60 last:border-b-0 dark:border-white/10"
                key={batch.batch_key}
              >
                <td className="px-2 py-1.5 font-mono break-all">
                  {batch.batch_key}
                  <span className="block text-[11px] text-muted">
                    {copy.classificationLabel}: {batch.classification} ·{" "}
                    {copy.provenanceLabel}: {batch.executed_by}
                  </span>
                </td>
                <td className="px-2 py-1.5 font-mono">{batch.row_count}</td>
                <td className="px-2 py-1.5">
                  {batch.truncated ? (
                    <span className="status-pill signal-watch">
                      {copy.yesPill}
                      {batch.limit_reason ? ` · ${batch.limit_reason}` : ""}
                    </span>
                  ) : (
                    <span className="text-muted">{copy.noPill}</span>
                  )}
                </td>
                <td className="px-2 py-1.5 text-muted">
                  {batch.ordering_mode === "primary_key"
                    ? batch.has_watermark
                      ? copy.watermarkPresent
                      : copy.orderingLabel
                    : copy.noWatermark}
                </td>
                <td
                  className="px-2 py-1.5 font-mono text-muted"
                  title={batch.digest_sha256}
                >
                  {batch.digest_sha256.slice(0, 12)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={reconState.kind === "loading"}
          loading={reconState.kind === "loading"}
          onClick={() => void checkStorage()}
          variant="secondary"
        >
          {reconState.kind === "loading" ? copy.checkingStorageAction : copy.checkStorageAction}
        </Button>
        {reconState.kind === "unsupported" ? (
          <span className="text-xs text-muted" role="status">
            {copy.reconUnsupported}
          </span>
        ) : null}
        {reconState.kind === "report" ? (
          <span
            aria-live="polite"
            className="font-mono text-[11px] break-all text-muted"
            role="status"
          >
            {copy.reconciliationTitle}:{" "}
            {(
              [
                ["clean_matches", copy.reconLabels.clean_match],
                ["digest_mismatches", copy.reconLabels.digest_mismatch],
                ["missing_objects", copy.reconLabels.missing_object],
                ["orphaned_objects", copy.reconLabels.orphaned_object],
              ] as const
            )
              .map(
                ([field, label]) =>
                  `${label} ${reconState.payload[field]}`,
              )
              .join(" · ")}
          </span>
        ) : null}
      </div>
    </div>
  );
}
