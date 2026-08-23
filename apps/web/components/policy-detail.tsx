"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  FlaskConical,
  GitCompareArrows,
  ScrollText,
  ShieldCheck,
} from "lucide-react";

import { ErrorPanel, LoadingPanel } from "@/components/ui/states";
import { toAxisOperatorError } from "@/lib/axis-api";
import { SourcePill } from "@/components/ui/source-pill";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PolicyEvaluationPanel } from "@/components/policy-evaluation-panel";
import { PolicyReviseForm } from "@/components/policy-revise-form";
import { PolicyRevisionCompare } from "@/components/policy-revision-compare";
import {
  buildPlatformPolicyDetailPath,
  fetchPlatformPolicyDetail,
  platformPolicyPrecedenceSteps,
  policyEffectClass,
  policyEffectLabel,
  policyScopeLabel,
  policyStatusClass,
  policyStatusLabel,
  summarizePolicyConditions,
  type PlatformPolicyDetail,
  type PlatformPolicyRecord,
} from "@/lib/platform-policies";
import { formatNumber, formatTimestamp } from "@/lib/format";
import {
  enumUrlField,
  opaqueStringUrlField,
  stringUrlField,
  useConsoleUrlState,
} from "@/lib/console-url-state";
import { deriveSourceState, PROVENANCE_NOT_APPLICABLE } from "@/lib/source-state";
import { strings } from "@/lib/strings";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useConsole } from "@/providers/console-provider";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import {
  IDENTITY_SESSION_ENDPOINT,
  useConsoleTenantScope,
} from "@/lib/use-console-tenant-scope";

type DetailSource = "loading" | "api" | "unavailable" | "missing";

const policyDetailTabs = ["conditions", "revisions", "evaluate"] as const;
type PolicyDetailTab = (typeof policyDetailTabs)[number];
const policyDetailUrlSchema = {
  tab: enumUrlField("tab", policyDetailTabs, "conditions"),
  compareRevisionNumber: stringUrlField("compare_revision"),
  // Revision confirmation marker: the durable feedback is derived from the
  // refetched detail record through this marker, surviving the query refresh
  // that recording a revision triggers.
  revisedRevisionNumber: opaqueStringUrlField("revised"),
};

type DetailResult = {
  tenantId: string;
  detail: PlatformPolicyDetail | null;
  errorRequestId: string | null;
  source: Exclude<DetailSource, "loading">;
};

function ConditionTagList({ items, anyLabel }: { items?: string[]; anyLabel: string }) {
  const values = items ?? [];

  return (
    <div className="flex min-w-0 flex-wrap gap-2">
      {values.length > 0 ? (
        values.map((item) => (
          <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5" key={item}>
            {item}
          </span>
        ))
      ) : (
        <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5">{anyLabel}</span>
      )}
    </div>
  );
}

function RevisionHistoryTable({ revisions }: { revisions: PlatformPolicyRecord[] }) {
  return (
    <section className="min-w-0 overflow-x-auto rounded-2xl border border-line bg-surface dark:border-white/10 dark:bg-white/5">
      <table className="w-full min-w-[640px] border-collapse text-left text-sm text-ink [&_th]:border-b [&_th]:border-line [&_th]:px-4 [&_th]:py-3 [&_th]:text-left [&_th]:font-mono [&_th]:text-[11px] [&_th]:font-medium [&_th]:tracking-[0.16em] [&_th]:uppercase [&_th]:text-signal dark:[&_th]:border-white/10 [&_td]:border-b [&_td]:border-line/60 [&_td]:px-4 [&_td]:py-3 [&_td]:align-top dark:[&_td]:border-white/6 [&_tbody_tr:last-child_td]:border-b-0">
        <caption className="sr-only">Policy revision history</caption>
        <thead>
          <tr>
            <th>Revision</th>
            <th>Effect</th>
            <th>Conditions</th>
            <th>Status</th>
            <th>Authored</th>
          </tr>
        </thead>
        <tbody>
          {revisions.map((revision) => (
            <tr key={revision.revision_number}>
              <td>
                <span className="font-mono text-[13px] break-words">
                  r{revision.revision_number} / {revision.policy_version}
                </span>
                {revision.revises_revision_number != null ? (
                  <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">Revises r{revision.revises_revision_number}</p>
                ) : (
                  <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">Initial revision</p>
                )}
              </td>
              <td>
                <span className={`status-pill ${policyEffectClass(revision.effect)}`}>
                  {policyEffectLabel(revision.effect)}
                </span>
              </td>
              <td>
                <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{summarizePolicyConditions(revision.conditions)}</p>
              </td>
              <td>
                <span className={`status-pill ${policyStatusClass(revision.status)}`}>
                  {policyStatusLabel(revision.status)}
                </span>
                {revision.replaced_by_revision_number != null ? (
                  <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                    Superseded by r{revision.replaced_by_revision_number}
                  </p>
                ) : null}
              </td>
              <td>
                <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{revision.created_by}</p>
                <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{formatTimestamp(revision.created_at)}</p>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function PolicyDetail({ policyId }: { policyId: string }) {
  const [result, setResult] = useState<DetailResult | null>(null);
  const [urlState, setUrlState] = useConsoleUrlState(policyDetailUrlSchema);
  const { session } = useOidcConsoleSession();
  const { refreshNonce } = useConsole();
  const { identity, tenantId, tenantQueriesEnabled } = useConsoleTenantScope();
  const detailPath = buildPlatformPolicyDetailPath(policyId, tenantId ?? undefined);

  useEffect(() => {
    if (!tenantQueriesEnabled || !tenantId) {
      return;
    }
    const requestedTenantId: string = tenantId;

    const controller = new AbortController();

    async function fetchPolicy() {
      try {
        const policyDetail = await fetchPlatformPolicyDetail(
          policyId,
          {
            session,
            signal: controller.signal,
          },
          requestedTenantId,
        );

        if (policyDetail === null) {
          setResult({
            tenantId: requestedTenantId,
            detail: null,
            errorRequestId: null,
            source: "missing",
          });
          return;
        }

        if (policyDetail.tenant_id !== requestedTenantId) {
          throw new Error(`Policy detail tenant does not match ${requestedTenantId}.`);
        }

        setResult({
          tenantId: requestedTenantId,
          detail: policyDetail,
          errorRequestId: null,
          source: "api",
        });
      } catch (caught) {
        if (!controller.signal.aborted) {
          setResult({
            tenantId: requestedTenantId,
            detail: null,
            errorRequestId: toAxisOperatorError(
              caught,
              strings.policyDetail.error.detailDetail,
            ).requestId,
            source: "unavailable",
          });
        }
      }
    }

    void fetchPolicy();

    return () => controller.abort();
  }, [policyId, session, refreshNonce, tenantId, tenantQueriesEnabled]);

  useEffect(() => {
    const detail = result?.tenantId === tenantId ? result.detail : null;
    if (!detail || !urlState.compareRevisionNumber) {
      return;
    }

    const comparisonExists = detail.revisions.some(
      (revision) => (
        revision.revision_number !== detail.current_revision.revision_number
        && String(revision.revision_number) === urlState.compareRevisionNumber
      ),
    );
    if (!comparisonExists) {
      setUrlState({ compareRevisionNumber: "" });
    }
  }, [result, setUrlState, tenantId, urlState.compareRevisionNumber]);

  if (identity.source === "loading") {
    return <LoadingPanel layout="detail" />;
  }

  if (identity.source === "unavailable" || !tenantId) {
    return (
      <ErrorPanel
        detail="The console could not verify the current actor and tenant. Policy data is not loaded until identity is available."
        endpoint={IDENTITY_SESSION_ENDPOINT}
        reference={identity.errorRequestId ?? undefined}
        title="Identity API unavailable"
      />
    );
  }

  const detail = result?.tenantId === tenantId ? result.detail : null;
  const source: DetailSource = result?.tenantId === tenantId ? result.source : "loading";

  if (!detail) {
    if (source === "loading") {
      return <LoadingPanel layout="detail" />;
    }

    if (source !== "missing") {
      return (
        <ErrorPanel
          detail={strings.policyDetail.error.detailDetail}
          endpoint={detailPath}
          reference={result?.errorRequestId ?? undefined}
          title={strings.policyDetail.error.title}
        />
      );
    }

    return (
      <div className="grid min-w-0 gap-4">
        <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5 flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="eyebrow m-0">Platform Policy</p>
            <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">Policy not found</h2>
            <p className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">{policyId}</p>
          </div>
          <Link className="inline-flex items-center justify-center gap-2 rounded-full border border-mist bg-surface px-4 py-2 text-sm font-medium text-ink transition-all duration-300 select-none hover:border-signal/50 hover:text-signal disabled:cursor-not-allowed disabled:opacity-55 dark:border-white/20 dark:hover:border-signal/60" href="/policies">
            <ArrowLeft size={17} />
            Policies
          </Link>
        </section>
      </div>
    );
  }

  const current = detail.current_revision;
  const compareCandidates = detail.revisions.filter(
    (revision) => revision.revision_number !== current.revision_number,
  );
  const compareRevision =
    compareCandidates.find(
      (revision) => String(revision.revision_number) === urlState.compareRevisionNumber,
    ) ?? null;
  const compareRevisionNumber = compareRevision ? urlState.compareRevisionNumber : "";

  return (
    <div className="grid min-w-0 gap-4">
      <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow m-0">{policyScopeLabel(current.scope)}</p>
          <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">{current.display_name}</h2>
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">{current.description}</p>
          <p className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">
            {detail.policy_id} / {detail.tenant_id}
          </p>
        </div>
        <div className="flex min-w-0 flex-wrap items-center justify-end gap-2" aria-label="Policy source and status">
          <SourcePill
            state={deriveSourceState(
              source === "missing" ? "unavailable" : source,
              Boolean(detail),
              PROVENANCE_NOT_APPLICABLE,
            )}
            subject="policy"
          />
          <span className={`status-pill ${policyEffectClass(current.effect)}`}>
            <ShieldCheck size={15} />
            {policyEffectLabel(current.effect)}
          </span>
          <Link className="inline-flex items-center justify-center gap-2 rounded-full border border-mist bg-surface px-4 py-2 text-sm font-medium text-ink transition-all duration-300 select-none hover:border-signal/50 hover:text-signal disabled:cursor-not-allowed disabled:opacity-55 dark:border-white/20 dark:hover:border-signal/60" href="/policies">
            <ArrowLeft size={17} />
            Policies
          </Link>
        </div>
      </section>

      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4 [&>*]:min-w-0">
        <article className="min-w-0 rounded-2xl border border-line bg-surface p-4 dark:border-white/10 dark:bg-white/5 min-h-[120px]">
          <p className="eyebrow m-0">Current Revision</p>
          <p className="mx-0 mt-2 mb-0 font-mono text-[13px] break-words text-ink">r{current.revision_number}</p>
          <p className="m-0 text-xs leading-relaxed text-muted break-words">{current.policy_version}</p>
        </article>
        <article className="min-w-0 rounded-2xl border border-line bg-surface p-4 dark:border-white/10 dark:bg-white/5 min-h-[120px]">
          <p className="eyebrow m-0">Status</p>
          <p className="font-display mx-0 mt-3 mb-1.5 text-2xl tabular-nums break-words text-ink">{policyStatusLabel(current.status)}</p>
          <p className="m-0 text-xs leading-relaxed text-muted break-words">Only the active revision is evaluated</p>
        </article>
        <article className="min-w-0 rounded-2xl border border-line bg-surface p-4 dark:border-white/10 dark:bg-white/5 min-h-[120px]">
          <p className="eyebrow m-0">Authored By</p>
          <p className="font-display mx-0 mt-3 mb-1.5 text-2xl tabular-nums break-words text-ink">{current.created_by}</p>
          <p className="m-0 text-xs leading-relaxed text-muted break-words">{formatTimestamp(current.created_at)}</p>
        </article>
        <article className="min-w-0 rounded-2xl border border-line bg-surface p-4 dark:border-white/10 dark:bg-white/5 min-h-[120px]">
          <p className="eyebrow m-0">Authoring Scope</p>
          <p className="mx-0 mt-2 mb-0 font-mono text-[13px] break-words text-ink">{current.required_authoring_scope}</p>
          <p className="m-0 text-xs leading-relaxed text-muted break-words">{current.audit_event_type}</p>
        </article>
      </div>

      <Tabs
        className="grid min-w-0 gap-3"
        onValueChange={(tab) =>
          setUrlState({ tab: tab as PolicyDetailTab }, { history: "push" })
        }
        value={urlState.tab}
      >
        <TabsList>
          <TabsTrigger value="conditions">{strings.policyDetail.tabs.conditions}</TabsTrigger>
          <TabsTrigger value="revisions">{strings.policyDetail.tabs.revisions}</TabsTrigger>
          <TabsTrigger value="evaluate">{strings.policyDetail.tabs.evaluate}</TabsTrigger>
        </TabsList>

        <TabsContent className="grid min-w-0 gap-4" value="conditions">
          <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
            <p className="eyebrow m-0">Rule Conditions</p>
            <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">
              {summarizePolicyConditions(current.conditions)}
            </h2>
            <div className="grid grid-cols-2 gap-3.5 border-y border-line/60 py-3.5 xl:grid-cols-4 dark:border-white/10 [&>*]:min-w-0">
              <div>
                <p className="eyebrow m-0">Action Domains</p>
                <ConditionTagList
                  anyLabel="Any domain"
                  items={current.conditions.action_domains}
                />
              </div>
              <div>
                <p className="eyebrow m-0">Risk Levels</p>
                <ConditionTagList
                  anyLabel="Any risk level"
                  items={current.conditions.risk_levels}
                />
              </div>
              <div>
                <p className="eyebrow m-0">Autonomy Levels</p>
                <ConditionTagList
                  anyLabel="Any autonomy level"
                  items={current.conditions.autonomy_levels}
                />
              </div>
              <div>
                <p className="eyebrow m-0">Amount Threshold</p>
                <p className="m-0 font-mono text-[13px] font-medium text-ink break-words">
                  {current.conditions.requested_amount_at_least != null
                    ? `>= ${current.conditions.requested_amount_at_least}`
                    : "No amount gate"}
                </p>
                <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                  Malformed amounts fail closed
                </p>
              </div>
            </div>
            {current.notes && current.notes.length > 0 ? (
              <div className="grid min-w-0 gap-2.5">
                {current.notes.map((note) => (
                  <p
                    className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words"
                    key={note}
                  >
                    {note}
                  </p>
                ))}
              </div>
            ) : null}
          </section>

          <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
            <p className="eyebrow m-0">Evaluation Precedence</p>
            <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">
              Deterministic decision order
            </h2>
            <div className="grid min-w-0 gap-2.5">
              {platformPolicyPrecedenceSteps.map((step) => (
                <p
                  className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words"
                  key={step}
                >
                  {step}
                </p>
              ))}
            </div>
          </section>
        </TabsContent>

        <TabsContent className="grid min-w-0 gap-4" value="revisions">
          {urlState.revisedRevisionNumber ? (
            <div
              aria-label="Policy revision result"
              className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-2xl border border-signal/30 bg-tint-50 px-4 py-3 dark:border-signal/40 dark:bg-signal/10"
              data-policy-revised
              role="status"
            >
              <p className="m-0 min-w-0 text-sm leading-snug break-words text-ink">
                Revision recorded: r{urlState.revisedRevisionNumber}. The active revision is
                r{current.revision_number} / {current.policy_version}.
              </p>
              <button
                className="inline-flex min-h-6 cursor-pointer items-center font-mono text-xs text-muted transition-colors hover:text-signal"
                onClick={() => setUrlState({ revisedRevisionNumber: "" })}
                type="button"
              >
                Dismiss
              </button>
            </div>
          ) : null}
          <PolicyReviseForm
            current={current}
            key={`revise-${current.revision_number}`}
            tenantId={detail.tenant_id}
          />

          <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10">
              <div>
                <p className="eyebrow m-0">Revision History</p>
                <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">
                  {formatNumber(detail.revisions.length)} append-only revisions
                </h2>
                <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                  Superseded revisions stay readable but are never evaluated.
                </p>
              </div>
              <ScrollText size={18} />
            </div>
          </section>
          <RevisionHistoryTable revisions={detail.revisions} />

          <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10">
              <div>
                <p className="eyebrow m-0">Revision Compare</p>
                <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">
                  Diff a revision against the current one
                </h2>
                <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                  Field-level compare of name, description, effect and typed conditions.
                </p>
              </div>
              <GitCompareArrows size={18} />
            </div>
            {compareCandidates.length > 0 ? (
              <div className="grid grid-cols-1 items-end gap-3 border-t border-line/60 pt-4 dark:border-white/10 sm:grid-cols-[repeat(auto-fit,minmax(150px,1fr))]">
                <Field label="Compare Revision">
                  <Select
                    aria-label="Revision to compare"
                    onChange={(event) =>
                      setUrlState({ compareRevisionNumber: event.target.value })
                    }
                    value={compareRevisionNumber}
                  >
                    <option value="">Select a revision</option>
                    {compareCandidates.map((revision) => (
                      <option key={revision.revision_number} value={revision.revision_number}>
                        r{revision.revision_number} / {revision.policy_version}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
            ) : (
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                Only the initial revision exists; append a revision to compare definitions.
              </p>
            )}
            {compareRevision ? (
              <PolicyRevisionCompare base={compareRevision} target={current} />
            ) : null}
          </section>
        </TabsContent>

        <TabsContent className="grid min-w-0 gap-4" value="evaluate">
          <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10">
              <div>
                <p className="eyebrow m-0">Dry-Run Evaluation</p>
                <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">
                  Evaluate a context against tenant policies
                </h2>
                <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                  Dry run only: evaluation is deterministic, records no audit event and
                  never mutates state.
                </p>
              </div>
              <FlaskConical size={18} />
            </div>
            <PolicyEvaluationPanel
              formLabel="Policy dry-run evaluation"
              scope={current.scope}
              tenantId={detail.tenant_id}
            />
          </section>
        </TabsContent>
      </Tabs>
    </div>
  );
}
