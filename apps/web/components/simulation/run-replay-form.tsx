"use client";

import { useState, type FormEvent } from "react";
import { ArrowRight, FlaskConical, GitCompareArrows } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { InspectDrawer } from "@/components/ui/inspect-drawer";
import { EmptyPanel, ErrorPanel } from "@/components/ui/states";
import {
  axisFetchParsedJson,
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import { parseManufacturingReplaySimulation } from "@/lib/runtime-contracts/simulation";
import {
  buildReplaySimulationPath,
  countArtifactPolicyDecisions,
  formatSimulationLabel,
  type ManufacturingReplaySimulation,
  type ReplayArtifact,
} from "@/lib/simulation-demo";
import { strings } from "@/lib/strings";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";

/*
 * Run replay from the UI: a parameterized GET against
 * /operations/simulation/replay (workflow window, retention,
 * optional policy-set comparison), rendered as a baseline-vs-simulated
 * decision diff. The raw API result stays behind the Inspect drawer.
 */

const DEFAULT_LIMIT = 20;
const DEFAULT_RETENTION_DAYS = 365;

type ReplayDraft = {
  workflowId: string;
  limit: string;
  retentionDays: string;
  legalHold: boolean;
  baselinePolicySetId: string;
  candidatePolicySetId: string;
  connectorId: string;
};

const initialDraft: ReplayDraft = {
  workflowId: "",
  limit: String(DEFAULT_LIMIT),
  retentionDays: String(DEFAULT_RETENTION_DAYS),
  legalHold: false,
  baselinePolicySetId: "",
  candidatePolicySetId: "",
  connectorId: "",
};

function parseBoundedInt(value: string, fallback: number, min: number, max: number): number {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return Math.min(Math.max(parsed, min), max);
}

function DecisionRow({
  name,
  summary,
  baseline,
  simulated,
  changed,
}: {
  name: string;
  summary: string;
  baseline: string;
  simulated: string;
  changed: boolean;
}) {
  const copy = strings.simulation.run.result;

  return (
    <li
      className="grid min-w-0 grid-cols-1 items-center gap-2 border-t border-line/60 py-3 first:border-t-0 first:pt-0 dark:border-white/10 lg:grid-cols-[minmax(0,1fr)_auto]"
      data-changed-outcome={changed}
    >
      <span className="grid min-w-0 gap-0.5">
        <span className="text-sm font-medium text-ink break-words">{name}</span>
        <span className="text-sm leading-snug text-muted break-words">{summary}</span>
      </span>
      <span className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="status-pill status-checking">
          {copy.baseline}: {formatSimulationLabel(baseline)}
        </span>
        <ArrowRight aria-hidden="true" className="shrink-0 text-muted" size={14} />
        <span className={`status-pill ${changed ? "signal-watch" : "signal-ready"}`}>
          {copy.simulated}: {formatSimulationLabel(simulated)}
        </span>
        <span className={`status-pill ${changed ? "signal-watch" : "signal-ready"}`}>
          {changed ? copy.changed : copy.unchanged}
        </span>
      </span>
    </li>
  );
}

function ReplayComparison({ result }: { result: ManufacturingReplaySimulation }) {
  const copy = strings.simulation.run.result;
  const artifacts = result.artifacts ?? [];
  const decisions = countArtifactPolicyDecisions(artifacts);
  const policySetDiffs = artifacts.flatMap(
    (artifact: ReplayArtifact) => artifact.policy_set_diffs ?? [],
  );

  return (
    <section
      className="grid min-w-0 gap-4 border-t border-line/60 pt-4 dark:border-white/10"
      data-replay-result
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow m-0">{copy.eyebrow}</p>
          <h3 className="font-display mx-0 mt-1 mb-0 text-lg text-ink">
            {decisions.total} decisions compared — {decisions.changed} changed
          </h3>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <span className={`status-pill ${decisions.changed > 0 ? "signal-watch" : "signal-ready"}`}>
            <GitCompareArrows size={15} />
            {decisions.changed} {copy.changed.toLowerCase()}
          </span>
          <InspectDrawer record={result as unknown as Record<string, unknown>} title={copy.inspect} />
        </div>
      </div>

      {decisions.total === 0 && policySetDiffs.length === 0 ? (
        <EmptyPanel detail={copy.empty.detail} title={copy.empty.title} />
      ) : null}

      {artifacts
        .filter((artifact) => artifact.policy_results.length > 0)
        .map((artifact) => (
          <div className="grid min-w-0 gap-1" key={artifact.artifact_id}>
            <p className="eyebrow m-0">{copy.decisionsTitle}</p>
            <p className="m-0 text-sm font-medium text-ink break-words">{artifact.workflow_name}</p>
            <ul className="m-0 grid list-none gap-0 p-0">
              {artifact.policy_results.map((policyResult) => (
                <DecisionRow
                  baseline={policyResult.baseline_decision}
                  changed={policyResult.changed_outcome}
                  key={`${artifact.artifact_id}-${policyResult.policy_id}`}
                  name={policyResult.policy_name}
                  simulated={policyResult.simulated_decision}
                  summary={policyResult.summary}
                />
              ))}
            </ul>
          </div>
        ))}

      {policySetDiffs.length > 0 ? (
        <div className="grid min-w-0 gap-1">
          <p className="eyebrow m-0">{copy.policySetTitle}</p>
          <ul className="m-0 grid list-none gap-0 p-0">
            {policySetDiffs.map((diff) => (
              <li
                className="grid min-w-0 gap-1.5 border-t border-line/60 py-3 first:border-t-0 first:pt-0 dark:border-white/10"
                data-changed-outcome={diff.changed_outcome}
                key={diff.diff_id}
              >
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                  <span className="text-sm leading-snug text-ink break-words">{diff.summary}</span>
                  <span
                    className={`status-pill ${diff.changed_outcome ? "signal-watch" : "signal-ready"}`}
                  >
                    {diff.changed_outcome ? copy.changed : copy.unchanged}
                  </span>
                </div>
                <p className="m-0 font-mono text-xs leading-snug text-muted break-words">
                  {diff.baseline_policy_set_id} / {diff.baseline_policy_set_version} →{" "}
                  {diff.candidate_policy_set_id} / {diff.candidate_policy_set_version}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

export function RunReplayForm({ tenantId }: { tenantId: string }) {
  const copy = strings.simulation.run;
  const { session } = useOidcConsoleSession();
  const [draft, setDraft] = useState<ReplayDraft>(initialDraft);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<AxisOperatorError | null>(null);
  const [result, setResult] = useState<ManufacturingReplaySimulation | null>(null);

  function updateDraft(patch: Partial<ReplayDraft>) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  async function runReplay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (running) {
      return;
    }
    setRunning(true);
    setRunError(null);

    const path = buildReplaySimulationPath({
      tenantId,
      workflowId: draft.workflowId,
      limit: parseBoundedInt(draft.limit, DEFAULT_LIMIT, 1, 100),
      retentionDays: parseBoundedInt(draft.retentionDays, DEFAULT_RETENTION_DAYS, 1, 3650),
      legalHold: draft.legalHold,
      baselinePolicySetId: draft.baselinePolicySetId,
      candidatePolicySetId: draft.candidatePolicySetId,
      connectorId: draft.connectorId,
    });

    try {
      const replay = await axisFetchParsedJson(
        path,
        (value) => {
          const parsed = parseManufacturingReplaySimulation(value);
          if (parsed.tenant_id !== tenantId) {
            throw new Error("Replay response tenant mismatch.");
          }
          return parsed;
        },
        { session },
      );
      setResult(replay);
    } catch (caught) {
      setResult(null);
      setRunError(toAxisOperatorError(caught, copy.error.detail));
    } finally {
      setRunning(false);
    }
  }

  return (
    <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5 grid gap-4">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow m-0">{copy.eyebrow}</p>
          <h2 className="font-display mx-0 mt-1 mb-1 text-xl text-ink">{copy.title}</h2>
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
            {copy.description}
          </p>
        </div>
        <FlaskConical aria-hidden="true" size={18} />
      </div>

      <form
        aria-label={copy.eyebrow}
        className="grid grid-cols-1 items-end gap-3 border-t border-line/60 pt-4 dark:border-white/10 sm:grid-cols-[repeat(auto-fit,minmax(180px,1fr))]"
        onSubmit={(event) => void runReplay(event)}
      >
        <Field label={copy.fields.workflow}>
          <Input
            onChange={(event) => updateDraft({ workflowId: event.target.value })}
            placeholder={copy.fields.workflowPlaceholder}
            value={draft.workflowId}
          />
        </Field>
        <Field label={copy.fields.limit}>
          <Input
            max={100}
            min={1}
            onChange={(event) => updateDraft({ limit: event.target.value })}
            type="number"
            value={draft.limit}
          />
        </Field>
        <Field label={copy.fields.retentionDays}>
          <Input
            max={3650}
            min={1}
            onChange={(event) => updateDraft({ retentionDays: event.target.value })}
            type="number"
            value={draft.retentionDays}
          />
        </Field>
        <Field label={copy.fields.baselineSet}>
          <Input
            onChange={(event) => updateDraft({ baselinePolicySetId: event.target.value })}
            value={draft.baselinePolicySetId}
          />
        </Field>
        <Field label={copy.fields.candidateSet}>
          <Input
            onChange={(event) => updateDraft({ candidatePolicySetId: event.target.value })}
            value={draft.candidatePolicySetId}
          />
        </Field>
        <Field label={copy.fields.connector}>
          <Input
            onChange={(event) => updateDraft({ connectorId: event.target.value })}
            value={draft.connectorId}
          />
        </Field>
        <label className="flex min-h-[38px] items-center gap-2 text-sm text-ink select-none">
          <input
            checked={draft.legalHold}
            className="size-4 accent-[rgb(var(--signal))]"
            onChange={(event) => updateDraft({ legalHold: event.target.checked })}
            type="checkbox"
          />
          {copy.fields.legalHold}
        </label>
        <Button className="px-4 py-2 text-sm" disabled={running} type="submit">
          {running ? copy.running : copy.submit}
        </Button>
      </form>
      <p className="m-0 text-xs leading-relaxed text-muted break-words">
        {copy.fields.comparisonHint}
      </p>

      {runError ? (
        <ErrorPanel
          detail={runError.message}
          reference={runError.requestId ?? undefined}
          title={copy.error.title}
        />
      ) : null}
      {result ? <ReplayComparison result={result} /> : null}
    </section>
  );
}
