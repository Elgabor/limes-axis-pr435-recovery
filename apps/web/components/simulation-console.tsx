"use client";

import { FileText, GitBranch, History, ShieldCheck } from "lucide-react";

import { RunReplayForm } from "@/components/simulation/run-replay-form";
import { SourcePill } from "@/components/ui/source-pill";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/ui/states";
import {
  formatContextPath,
  formatDateTime,
  formatNumber,
  pluralize,
} from "@/lib/format";
import { stringUrlField, useConsoleUrlState } from "@/lib/console-url-state";
import { parseManufacturingReplaySimulation } from "@/lib/runtime-contracts/simulation";
import { deriveSourceState } from "@/lib/source-state";
import { strings } from "@/lib/strings";
import {
  buildReplaySimulationPath,
  countChangedPolicySetDiffs,
  countChangedPolicyResults,
  formatSimulationLabel,
  type ManufacturingReplaySimulation,
  type PolicySimulationResult,
} from "@/lib/simulation-demo";
import {
  formatOverviewTimestamp,
  platformStatusClass,
  platformStatusLabel,
} from "@/lib/platform-overview";
import { DEMO_TENANT_ID } from "@/lib/tenant-scope";
import { useAxisQuery } from "@/lib/use-axis-query";
import {
  IDENTITY_SESSION_ENDPOINT,
  useConsoleTenantScope,
} from "@/lib/use-console-tenant-scope";

// Module scope, like every other console's schema: an inline literal is a new
// object each render, which defeats the hook's memo and makes its setter churn.
const simulationUrlSchema = {
  artifactId: stringUrlField("artifact_id"),
};

export function SimulationConsole() {
  const [urlState, setUrlState] = useConsoleUrlState(simulationUrlSchema);
  const { identity, tenantId, tenantQueriesEnabled } = useConsoleTenantScope();
  const replayPath = buildReplaySimulationPath({
    tenantId: tenantId ?? DEMO_TENANT_ID,
    limit: 20,
  });
  const replayQuery = useAxisQuery<ManufacturingReplaySimulation>(replayPath, {
    enabled: tenantQueriesEnabled,
    expectedTenantId: tenantId ?? undefined,
    parse: parseManufacturingReplaySimulation,
  });
  const simulationData = replayQuery.data;
  const source = deriveSourceState(
    replayQuery.source,
    Boolean(simulationData),
    simulationData?.provenance,
  );

  const selectedArtifact = urlState.artifactId
    ? simulationData?.artifacts.find(
        (artifact) => artifact.artifact_id === urlState.artifactId,
      ) ?? null
    : simulationData?.artifacts[0] ?? null;
  const changedPolicies = simulationData ? countChangedPolicyResults(simulationData) : 0;
  const changedPolicySetDiffs = simulationData ? countChangedPolicySetDiffs(simulationData) : 0;

  if (identity.source === "loading") {
    return <LoadingPanel layout="detail" />;
  }

  if (identity.source === "unavailable" || !tenantId) {
    return (
      <ErrorPanel
        detail="The console could not verify the current actor and tenant. Replay data is not loaded until identity is available."
        endpoint={IDENTITY_SESSION_ENDPOINT}
        reference={identity.errorRequestId ?? undefined}
        title="Identity API unavailable"
      />
    );
  }

  if (!simulationData) {
    if (source === "loading") {
      return <LoadingPanel layout="detail" />;
    }

    return (
      <ErrorPanel
        detail={strings.simulation.error.detail}
        endpoint={replayPath}
        reference={replayQuery.errorRequestId ?? undefined}
        title={strings.simulation.error.title}
      />
    );
  }

  if (simulationData.artifacts.length === 0) {
    return (
      <EmptyPanel
        detail={strings.simulation.noArtifacts.detail}
        icon={History}
        title={strings.simulation.noArtifacts.title}
      />
    );
  }

  if (!selectedArtifact) {
    return (
      <EmptyPanel
        detail={strings.states.requestedRecord.detail}
        title={strings.states.requestedRecord.title}
      />
    );
  }

  const primaryPolicy: PolicySimulationResult | undefined = selectedArtifact.policy_results[0];
  const primaryPolicySetDiff = (selectedArtifact.policy_set_diffs ?? [])[0];
  const persistedOutputs = simulationData.persisted_outputs ?? [];
  const retentionWindow = simulationData.retention_window;
  const excludedReplayRecords =
    retentionWindow.excluded_timeline_event_count +
    retentionWindow.excluded_audit_event_count +
    retentionWindow.excluded_output_count;

  return (
    <div className="grid min-w-0 gap-4">
      <div
        aria-label="Simulation source and status"
        className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2"
      >
        <p className="m-0 min-w-0 text-sm leading-snug break-words text-muted">
          {formatContextPath(
            simulationData.plant_name,
            simulationData.scenario,
            simulationData.tenant_id,
          )}
        </p>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <SourcePill state={source} subject="replay artifacts" />
          <span className={`status-pill ${platformStatusClass(simulationData.simulation_status)}`}>
            <ShieldCheck size={15} />
            {platformStatusLabel(simulationData.simulation_status)}
          </span>
          <span className="font-mono text-[13px] break-words text-muted">{formatOverviewTimestamp(simulationData.as_of)}</span>
        </div>
      </div>

      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4 [&>*]:min-w-0">
        {simulationData.metrics.map((metric) => (
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

      <RunReplayForm tenantId={simulationData.tenant_id} />

      <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
          <div>
            <p className="eyebrow m-0">Replay Window</p>
            <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">{pluralize(retentionWindow.retention_days, "day")} retention</h2>
            <p className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">
              {retentionWindow.policy_id} / {retentionWindow.disposal_action}
            </p>
          </div>
          <span
            className={`status-pill ${
              retentionWindow.legal_hold ? "signal-watch" : "signal-ready"
            }`}
          >
            <ShieldCheck size={15} />
            {retentionWindow.legal_hold ? "legal hold" : "enforced"}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-3.5 border-y border-line/60 py-3.5 xl:grid-cols-4 dark:border-white/10 [&>*]:min-w-0">
          <div>
            <p className="eyebrow m-0">Window Start</p>
            <p className="m-0 font-medium text-ink break-words">{formatDateTime(retentionWindow.retention_window_start)}</p>
            <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{retentionWindow.retention_enforced ? "active" : "held"}</p>
          </div>
          <div>
            <p className="eyebrow m-0">Timeline</p>
            <p className="m-0 font-medium text-ink break-words">{formatNumber(retentionWindow.excluded_timeline_event_count)} excluded</p>
            <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">history events</p>
          </div>
          <div>
            <p className="eyebrow m-0">Audit</p>
            <p className="m-0 font-medium text-ink break-words">{formatNumber(retentionWindow.excluded_audit_event_count)} excluded</p>
            <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">ledger events</p>
          </div>
          <div>
            <p className="eyebrow m-0">Outputs</p>
            <p className="m-0 font-medium text-ink break-words">{formatNumber(retentionWindow.excluded_output_count)} excluded</p>
            <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{formatNumber(excludedReplayRecords)} total excluded</p>
          </div>
        </div>
      </section>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(300px,0.42fr)_minmax(0,1fr)] [&>*]:min-w-0">
        <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
            <div>
              <p className="eyebrow m-0">Artifacts</p>
              <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">{pluralize(simulationData.artifacts.length, "replay preview")}</h2>
            </div>
            <span className="status-pill signal-watch">
              <GitBranch size={15} />
              {formatNumber(changedPolicies + changedPolicySetDiffs)} changed
            </span>
          </div>

          <div className="grid">
            {simulationData.artifacts.map((artifact) => {
              const isSelected = artifact.artifact_id === selectedArtifact.artifact_id;

              return (
                <button
                  aria-pressed={isSelected}
                  className={`grid w-full cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-3.5 border-0 border-t border-line/60 bg-transparent px-2.5 py-3.5 text-left text-ink transition-colors first:border-t-0 hover:bg-ink/4 dark:border-white/10 dark:hover:bg-white/6${isSelected ? " bg-signal/10 shadow-[inset_2px_0_0_rgb(var(--signal))] dark:bg-signal/15" : ""}`}
                  key={artifact.artifact_id}
                  onClick={() => setUrlState({ artifactId: artifact.artifact_id })}
                  type="button"
                >
                  <span>
                    <span className="m-0 font-medium text-ink break-words">{artifact.workflow_name}</span>
                    <span className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">{artifact.workflow_id}</span>
                    <span className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                      {pluralize(artifact.timeline_event_count + artifact.audit_event_count, "evidence event")}
                    </span>
                  </span>
                  <span className="status-pill signal-watch">
                    {formatSimulationLabel(artifact.determinism_status)}
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5 grid gap-4">
          <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
            <div>
              <p className="eyebrow m-0">{selectedArtifact.replay_mode}</p>
              <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">{selectedArtifact.workflow_name}</h2>
              <p className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">{selectedArtifact.artifact_id}</p>
            </div>
            <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
              <span className="status-pill signal-watch">
                {formatSimulationLabel(selectedArtifact.determinism_status)}
              </span>
              <span className="status-pill status-checking">{selectedArtifact.audit_scope}</span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3.5 border-y border-line/60 py-3.5 xl:grid-cols-4 dark:border-white/10 [&>*]:min-w-0">
            <div>
              <p className="eyebrow m-0">Timeline</p>
              <p className="m-0 font-medium text-ink break-words">{selectedArtifact.timeline_event_count}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">workflow history events</p>
            </div>
            <div>
              <p className="eyebrow m-0">Audit</p>
              <p className="m-0 font-medium text-ink break-words">{selectedArtifact.audit_event_count}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">ledger events</p>
            </div>
            <div>
              <p className="eyebrow m-0">Policy</p>
              {primaryPolicy ? (
                <>
                  <p className="m-0 font-medium text-ink break-words font-mono text-[13px]">{primaryPolicy.policy_id}</p>
                  <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{primaryPolicy.simulated_decision}</p>
                </>
              ) : (
                <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{strings.simulation.noPolicyResult}</p>
              )}
            </div>
            <div>
              <p className="eyebrow m-0">Replay Ready</p>
              <p className="m-0 font-medium text-ink break-words">{selectedArtifact.replay_ready ? "Yes" : "No"}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">preview foundation</p>
            </div>
          </div>

          {primaryPolicy ? (
            <section className="grid items-start gap-4 border-b border-line/60 pb-4 dark:border-white/10 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.48fr)] [&>*]:min-w-0">
              <div>
                <p className="eyebrow m-0">Policy Simulation</p>
                <h3 className="font-display mx-0 mt-1 mb-0 text-lg text-ink">{primaryPolicy.policy_name}</h3>
                <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{primaryPolicy.summary}</p>
              </div>
              <div className="grid min-w-0 gap-2">
                <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
                  <span className="eyebrow m-0">Baseline</span>
                  <span className="font-mono text-[13px] break-words">{primaryPolicy.baseline_decision}</span>
                </div>
                <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
                  <span className="eyebrow m-0">Simulated</span>
                  <span className="font-mono text-[13px] break-words">{primaryPolicy.simulated_decision}</span>
                </div>
                <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
                  <span className="eyebrow m-0">Outcome Change</span>
                  <span className="font-mono text-[13px] break-words">{primaryPolicy.changed_outcome ? "yes" : "no"}</span>
                </div>
              </div>
            </section>
          ) : null}

          {primaryPolicySetDiff ? (
            <section className="grid items-start gap-4 border-b border-line/60 pb-4 dark:border-white/10 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.48fr)] [&>*]:min-w-0">
              <div>
                <p className="eyebrow m-0">Policy Set Diff</p>
                <h3 className="font-display mx-0 mt-1 mb-0 text-lg text-ink">{primaryPolicySetDiff.connector_id}</h3>
                <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{primaryPolicySetDiff.summary}</p>
              </div>
              <div className="grid min-w-0 gap-2">
                <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
                  <span className="eyebrow m-0">Baseline Set</span>
                  <span className="font-mono text-[13px] break-words">
                    {primaryPolicySetDiff.baseline_policy_set_id} /{" "}
                    {primaryPolicySetDiff.baseline_policy_set_version}
                  </span>
                </div>
                <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
                  <span className="eyebrow m-0">Candidate Set</span>
                  <span className="font-mono text-[13px] break-words">
                    {primaryPolicySetDiff.candidate_policy_set_id} /{" "}
                    {primaryPolicySetDiff.candidate_policy_set_version}
                  </span>
                </div>
                <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
                  <span className="eyebrow m-0">Diff Status</span>
                  <span className="font-mono text-[13px] break-words">{primaryPolicySetDiff.diff_status}</span>
                </div>
                <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
                  <span className="eyebrow m-0">Audit Event</span>
                  <span className="font-mono text-[13px] break-words">{primaryPolicySetDiff.audit_event_type}</span>
                </div>
                <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
                  <span className="eyebrow m-0">Changed Policies</span>
                  <span className="font-mono text-[13px] break-words">{primaryPolicySetDiff.changed_policy_ids.join(", ")}</span>
                </div>
              </div>
            </section>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-3 [&>*]:min-w-0">
            <section>
              <p className="eyebrow m-0">Evidence</p>
              <div className="flex min-w-0 flex-wrap gap-2">
                {selectedArtifact.evidence_refs.slice(0, 10).map((ref) => (
                  <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5" key={ref}>
                    {ref}
                  </span>
                ))}
              </div>
            </section>
            <section>
              <p className="eyebrow m-0">Audit Event Types</p>
              <div className="flex min-w-0 flex-wrap gap-2">
                {selectedArtifact.audit_events.slice(0, 8).map((event) => (
                  <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5" key={event.audit_event_id}>
                    {event.event_type}
                  </span>
                ))}
              </div>
            </section>
            <section>
              <p className="eyebrow m-0">Mode</p>
              <div className="flex min-w-0 flex-wrap gap-2">
                <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5">{selectedArtifact.replay_mode}</span>
                <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5">{selectedArtifact.determinism_status}</span>
              </div>
            </section>
          </div>

          <section className="grid gap-3">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
              <div>
                <p className="eyebrow m-0">Replay Trace</p>
                <h3 className="font-display mx-0 mt-1 mb-0 text-lg text-ink">Timeline evidence</h3>
              </div>
              <span className="status-pill signal-ready">
                <History size={15} />
                {pluralize(selectedArtifact.timeline.length, "event")}
              </span>
            </div>
            <div className="grid gap-3">
              {selectedArtifact.timeline.map((event, index) => (
                <div className="grid grid-cols-[42px_minmax(0,1fr)] items-start gap-3" key={`${event.event}-${event.at}`}>
                  <div className="grid size-[42px] place-items-center rounded-xl bg-signal/10 font-mono text-sm font-medium text-signal">{index + 1}</div>
                  <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10">
                    <div>
                      <p className="m-0 font-medium text-ink break-words font-mono text-[13px]">{event.event}</p>
                      <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                        {formatDateTime(event.at)} / {event.actor} / {event.result}
                      </p>
                      <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{event.summary}</p>
                    </div>
                    <FileText size={18} aria-label={event.result} />
                  </div>
                </div>
              ))}
            </div>
          </section>
        </section>
      </div>

      <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
          <div>
            <p className="eyebrow m-0">Persisted Outputs</p>
            <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">{pluralize(persistedOutputs.length, "governed output")}</h2>
          </div>
          <span className="status-pill signal-ready">
            <FileText size={15} />
            audit-backed
          </span>
        </div>
        <div className="grid min-w-0 gap-2">
          {persistedOutputs.length ? (
            persistedOutputs.map((output) => (
              <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5" key={output.simulation_output_id}>
                <span>
                  <span className="eyebrow m-0">{output.simulation_output_id}</span>
                  <span className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">{output.audit_event_type}</span>
                </span>
                <span className="font-mono text-[13px] break-words">{output.output_hash.slice(0, 12)}</span>
              </div>
            ))
          ) : (
            <div className="grid min-w-0 grid-cols-1 items-start gap-1 border-t border-line/60 pt-2 first:border-t-0 first:pt-0 dark:border-white/10 sm:grid-cols-[minmax(120px,0.35fr)_minmax(0,1fr)] sm:gap-2.5">
              <span className="eyebrow m-0">No persisted output</span>
              <span className="font-mono text-[13px] break-words">preview-only</span>
            </div>
          )}
        </div>
        {persistedOutputs.map((output) => (
          <div className="grid grid-cols-2 gap-3.5 border-y border-line/60 py-3.5 xl:grid-cols-4 dark:border-white/10 [&>*]:min-w-0" key={`${output.simulation_output_id}-detail`}>
            <div>
              <p className="eyebrow m-0">Workflow</p>
              <p className="m-0 font-medium text-ink break-words">{output.workflow_id}</p>
              <p className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">{output.artifact_id}</p>
            </div>
            <div>
              <p className="eyebrow m-0">Retention</p>
              <p className="m-0 font-medium text-ink break-words">{pluralize(output.retention_window_days, "day")}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{output.status}</p>
            </div>
            <div>
              <p className="eyebrow m-0">Requested By</p>
              <p className="m-0 font-medium text-ink break-words">{output.requested_by}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{output.permission_decision.reason}</p>
            </div>
            <div>
              <p className="eyebrow m-0">Audit</p>
              <p className="m-0 font-medium text-ink break-words">{output.audit_event_id ?? "pending"}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{output.required_scope}</p>
            </div>
          </div>
        ))}
      </section>

      <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
        <p className="eyebrow m-0">Simulation Notes</p>
        <div className="grid min-w-0 gap-2.5">
          {simulationData.simulation_notes.map((note) => (
            <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words" key={note}>
              {note}
            </p>
          ))}
        </div>
      </section>
    </div>
  );
}
