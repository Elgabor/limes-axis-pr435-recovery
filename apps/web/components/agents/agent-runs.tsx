"use client";

import { useEffect, useState } from "react";
import { Activity } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { EmptyPanel, ErrorPanel } from "@/components/ui/states";
import {
  agentRunDetailPath,
  agentRunStatusClass,
  agentRunStatusLabel,
  agentRunsPath,
  buildAgentRunRail,
  buildApprovalActionRunHref,
  isDeferredAgentRunStatus,
  modelInvocationDetailPath,
  parseAgentRun,
  parseAgentRunList,
  type AgentRunRailState,
  type AgentRunRecord,
} from "@/lib/agent-runs-live";
import { buildAuditEventHref } from "@/lib/audit-demo";
import { axisFetchParsedJson } from "@/lib/axis-api";
import { cn } from "@/lib/cn";
import { formatModelRoutingLabel } from "@/lib/model-routing-demo";
import {
  formatLiveEuroCost,
  formatLiveTimestamp,
  parseModelInvocation,
  type LiveModelInvocation,
} from "@/lib/model-routing-live";
import { strings } from "@/lib/strings";
import { useAxisQuery } from "@/lib/use-axis-query";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

function RunRailMarker({ state }: { state: AgentRunRailState }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block size-2.5 shrink-0 rotate-45",
        state === "done" && "bg-signal",
        state === "current" && "border-2 border-signal bg-transparent",
        state === "failed" && "border-2 border-danger bg-transparent",
        state === "pending" && "border border-mist bg-transparent dark:border-white/25",
      )}
      style={
        state === "current"
          ? { animation: "tick-pulse 1.6s ease-in-out infinite" }
          : undefined
      }
    />
  );
}

/**
 * Step timeline projected from the persisted agent_run_steps records onto
 * the fixed context_read → model call → proposal rail, mirroring the
 * approval inbox decision rail treatment.
 */
function AgentRunRail({ run }: { run: AgentRunRecord }) {
  const stages = buildAgentRunRail(run);

  return (
    <div className="grid gap-2" aria-label="Agent run step timeline">
      <div className="flex items-center gap-2">
        {stages.map((stage, index) => (
          <div
            className={cn("flex items-center gap-2", index > 0 && "min-w-0 flex-1")}
            key={stage.step_type}
          >
            {index > 0 ? <div className="rule-hairline relative h-px min-w-6 flex-1" /> : null}
            <RunRailMarker state={stage.state} />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-2">
        {stages.map((stage) => (
          <div className="grid min-w-0 gap-0.5" key={stage.step_type}>
            <p
              className={cn(
                "m-0 font-mono text-[10.5px] tracking-[0.14em] uppercase",
                stage.state === "pending"
                  ? "text-muted"
                  : stage.state === "failed"
                    ? "text-danger"
                    : "text-signal",
              )}
            >
              {stage.label}
            </p>
            <p className="m-0 truncate text-xs text-muted" title={stage.detail}>
              {stage.detail}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

type LinkedInvocationsState = {
  invocations: LiveModelInvocation[];
  failedIds: string[];
  isLoading: boolean;
};

type LinkedInvocationsResult = {
  /** The id-list key the result was resolved for; stale results are ignored. */
  key: string;
  invocations: LiveModelInvocation[];
  failedIds: string[];
};

/** Resolve the run's linked model invocation records from the platform
 * router; failures are reported per id instead of being masked. */
function useLinkedModelInvocations(invocationIds: string[]): LinkedInvocationsState {
  const { session } = useOidcConsoleSession();
  const [result, setResult] = useState<LinkedInvocationsResult | null>(null);
  const idsKey = invocationIds.join(",");

  useEffect(() => {
    if (idsKey === "") {
      return;
    }

    const controller = new AbortController();
    const ids = idsKey.split(",");

    async function load() {
      const invocations: LiveModelInvocation[] = [];
      const failedIds: string[] = [];

      await Promise.all(
        ids.map(async (invocationId) => {
          try {
            const payload = await axisFetchParsedJson(
              modelInvocationDetailPath(invocationId),
              parseModelInvocation,
              { session, signal: controller.signal },
            );
            invocations.push(payload);
          } catch {
            failedIds.push(invocationId);
          }
        }),
      );

      if (!controller.signal.aborted) {
        setResult({ key: idsKey, invocations, failedIds });
      }
    }

    void load();

    return () => controller.abort();
  }, [idsKey, session]);

  const resolved = result !== null && result.key === idsKey ? result : null;

  return {
    invocations: resolved?.invocations ?? [],
    failedIds: resolved?.failedIds ?? [],
    isLoading: idsKey !== "" && resolved === null,
  };
}

function AgentRunDetail({ agentId, run }: { agentId: string; run: AgentRunRecord }) {
  const linked = useLinkedModelInvocations(run.model_invocation_ids);
  // The run LIST endpoint returns runs without their step records; only the
  // run DETAIL endpoint carries the persisted context_read → model call →
  // proposal steps. Fetch the detail for the selected run so the step rail
  // reflects recorded step statuses instead of always rendering "pending".
  const detailQuery = useAxisQuery(agentRunDetailPath(agentId, run.run_id), {
    parse: parseAgentRun,
  });
  const detailRun = detailQuery.data;

  return (
    <div className="grid min-w-0 gap-3 border-t border-line/60 pt-3 dark:border-white/10" data-run-detail={run.run_id}>
      {detailQuery.isLoading ? (
        <Skeleton aria-label="Loading agent run steps" className="h-14 w-full" />
      ) : detailRun ? (
        <AgentRunRail run={detailRun} />
      ) : (
        <ErrorPanel
          detail={strings.agents.runs.detailError.detail}
          endpoint={agentRunDetailPath(agentId, run.run_id)}
          reference={detailQuery.errorRequestId ?? undefined}
          title={strings.agents.runs.detailError.title}
        />
      )}

      {run.error_reason ? (
        <p className="m-0 font-mono text-xs break-words text-muted">
          Error reason: {run.error_reason}
        </p>
      ) : null}

      <div>
        <p className="eyebrow m-0">{strings.agents.runs.linkedInvocations}</p>
        {run.model_invocation_ids.length === 0 ? (
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted">
            {strings.agents.runs.noInvocations}
          </p>
        ) : linked.isLoading ? (
          <Skeleton className="mt-2 h-9 w-full" />
        ) : (
          <div className="mt-1 grid min-w-0 gap-2">
            {linked.invocations.map((invocation) => (
              <div
                className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-t border-line/60 py-2 first:border-t-0 dark:border-white/10"
                key={invocation.invocation_id}
              >
                <div>
                  <p className="m-0 font-mono text-[13px] text-ink break-words">
                    {invocation.model_id ?? "unrouted"} / {invocation.endpoint_id ?? "unrouted"}
                  </p>
                  <p className="mx-0 mt-0.5 mb-0 text-xs leading-snug text-muted break-words">
                    {invocation.input_tokens} in / {invocation.output_tokens} out tokens /{" "}
                    {formatLiveEuroCost(invocation.estimated_cost_eur)} / {invocation.latency_ms} ms /{" "}
                    {formatModelRoutingLabel(invocation.egress_decision)}
                  </p>
                </div>
                {invocation.audit_event_id ? (
                  <a
                    className="font-mono text-xs text-signal underline-offset-2 hover:underline"
                    href={buildAuditEventHref(invocation.audit_event_id)}
                  >
                    {strings.agents.runs.openAudit}
                  </a>
                ) : (
                  <span className="font-mono text-xs text-muted">
                    {strings.agents.runs.auditPending}
                  </span>
                )}
              </div>
            ))}
            {linked.failedIds.map((invocationId) => (
              <p className="m-0 font-mono text-xs break-words text-muted" key={invocationId}>
                Invocation {invocationId} detail unavailable (/platform/models/invocations).
              </p>
            ))}
          </div>
        )}
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-3">
        {run.proposed_action_run_id ? (
          <a
            className="font-mono text-xs text-signal underline-offset-2 hover:underline"
            href={buildApprovalActionRunHref(run.proposed_action_run_id)}
          >
            {strings.agents.runs.openActionRun}
          </a>
        ) : (
          <span className="font-mono text-xs text-muted">
            {strings.agents.runs.noActionRun}
          </span>
        )}
        {run.audit_event_id ? (
          <a
            className="font-mono text-xs text-signal underline-offset-2 hover:underline"
            href={buildAuditEventHref(run.audit_event_id)}
          >
            {strings.agents.runs.openRunAudit}
          </a>
        ) : null}
      </div>

      {run.notes.length > 0 ? (
        <ul className="mx-0 mt-0 mb-0 grid list-disc gap-1.5 pl-5 text-xs leading-relaxed text-muted">
          {run.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/**
 * Runs tab content: persisted run records for the agent, loaded when the tab
 * mounts. Renders exclusively API-backed rows — empty and unavailable states
 * stay honest, run timelines are never fabricated.
 */
export function AgentRuns({
  agentId,
  onSelect,
  selectedRunId,
}: {
  agentId: string;
  onSelect?: (runId: string) => void;
  selectedRunId?: string;
}) {
  const [internalSelectedRunId, setInternalSelectedRunId] = useState("");
  const resolvedSelectedRunId = selectedRunId ?? internalSelectedRunId;
  const runsQuery = useAxisQuery(agentRunsPath(agentId), { parse: parseAgentRunList });
  const runList = runsQuery.data;

  const selectedRun = resolvedSelectedRunId
    ? runList?.runs.find((run) => run.run_id === resolvedSelectedRunId) ?? null
    : runList?.runs[0] ?? null;
  const deferredCount = runList
    ? runList.runs.filter((run) => isDeferredAgentRunStatus(run.status)).length
    : 0;

  if (runsQuery.isLoading) {
    return (
      <div aria-label="Loading agent runs" className="grid gap-2.5" role="status">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-2/3" />
      </div>
    );
  }

  if (!runList) {
    return (
      <ErrorPanel
        detail={strings.agents.runs.error.detail}
        endpoint={`${OPERATIONS_API_PREFIX}/agents/${agentId}/runs`}
        reference={runsQuery.errorRequestId ?? undefined}
        title={strings.agents.runs.error.title}
      />
    );
  }

  if (runList.runs.length === 0) {
    return (
      <EmptyPanel
        detail={strings.agents.runs.empty.detail}
        title={strings.agents.runs.empty.title}
      />
    );
  }

  if (resolvedSelectedRunId && !selectedRun) {
    return (
      <EmptyPanel
        detail={strings.states.requestedRecord.detail}
        title={strings.states.requestedRecord.title}
      />
    );
  }

  return (
    <div className="grid min-w-0 gap-3" data-agent-runs-panel={agentId}>
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
        <p className="mx-0 mt-0 mb-0 text-sm leading-snug text-muted break-words">
          {strings.agents.runs.detail}
        </p>
        <span className="status-pill signal-ready" data-source-badge="live">
          <Activity size={15} />
          {strings.agents.runs.liveBadge}
        </span>
      </div>

      {deferredCount > 0 ? (
        <p className="m-0 font-mono text-xs text-muted">
          {deferredCount} deferred run{deferredCount === 1 ? "" : "s"} — model routing
          execution is flag-gated; deferred runs end honestly without a proposal.
        </p>
      ) : null}

      <div className="grid min-w-0">
        {runList.runs.map((run) => {
          const isSelected = selectedRun !== null && run.run_id === selectedRun.run_id;

          return (
            <button
              aria-pressed={isSelected}
              className={cn(
                "grid w-full cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-3.5 border-0 border-t border-line/60 bg-transparent px-2.5 py-3 text-left text-ink transition-colors first:border-t-0 hover:bg-ink/4 dark:border-white/10 dark:hover:bg-white/6",
                isSelected
                  && "bg-signal/10 shadow-[inset_2px_0_0_rgb(var(--signal))] dark:bg-signal/15",
              )}
              data-run-id={run.run_id}
              key={run.run_id}
              onClick={() => {
                if (selectedRunId === undefined) {
                  setInternalSelectedRunId(run.run_id);
                }
                onSelect?.(run.run_id);
              }}
              type="button"
            >
              <span>
                <span className="m-0 font-mono text-[13px] text-ink break-words">
                  {run.run_id}
                </span>
                <span className="mx-0 mt-1 mb-0 block text-sm leading-snug text-muted break-words">
                  {run.autonomy_level} / started {formatLiveTimestamp(run.created_at)} by{" "}
                  {run.requested_by}
                </span>
              </span>
              <span className="flex min-w-0 flex-wrap items-center justify-end gap-2">
                {run.mode === "dry_run" ? (
                  <span className="status-pill signal-watch">{strings.agents.runs.dryRun}</span>
                ) : null}
                <span className={`status-pill ${agentRunStatusClass(run.status)}`}>
                  {agentRunStatusLabel(run.status)}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {selectedRun ? <AgentRunDetail agentId={agentId} run={selectedRun} /> : null}

      {runList.run_notes.length > 0 ? (
        <ul className="mx-0 mt-0 mb-0 grid list-disc gap-1.5 pl-5 text-xs leading-relaxed text-muted">
          {runList.run_notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
