"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, CircleCheckBig, Clock3, GitBranch, TriangleAlert } from "lucide-react";

import {
  ApprovalDecisionCard,
  useApprovalDecisionState,
} from "@/components/approvals/approval-decision-card";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { SourcePill } from "@/components/ui/source-pill";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/ui/states";
import {
  formatActionLabel,
  partitionActionRuns,
  type ActionRunList,
  type ActionRunRecord,
} from "@/lib/action-demo";
import {
  approvalDecisionLabel,
  approvalRiskClass,
  buildApprovalHref,
  type ApprovalInboxItem,
  type ManufacturingApprovalInbox,
} from "@/lib/approval-demo";
import { cn } from "@/lib/cn";
import { formatElapsedDuration } from "@/lib/format";
import type {
  IdentitySessionReadModel,
  ManufacturingOverview,
  RiskSignal,
  WorkflowSummary,
} from "@/lib/platform-overview";
import { strings } from "@/lib/strings";
import { deriveSourceState, PROVENANCE_NOT_APPLICABLE } from "@/lib/source-state";
import { buildTenantScopedPath, DEMO_TENANT_ID, OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";
import { parseActionRunList } from "@/lib/runtime-contracts/actions";
import { parseManufacturingApprovalInbox } from "@/lib/runtime-contracts/approvals";
import { useAxisQuery } from "@/lib/use-axis-query";

import {
  normalizeLabel,
  overviewErrorReference,
  PanelHeader,
  StatusDot,
  type OverviewQuery,
} from "./overview-shared";

/*
 * The needs-attention strip: everything currently waiting on a human, each
 * as one line with one action. Approvals reuse the exact decision card (and
 * its confirm dialog) from the approvals page inside a Sheet, so a decision
 * taken here follows the same governed persistence path.
 */

export const APPROVALS_ENDPOINT = `${OPERATIONS_API_PREFIX}/approvals`;
const ACTION_RUNS_ENDPOINT = `${OPERATIONS_API_PREFIX}/actions/runs`;

const APPROVAL_LIMIT = 3;

/*
 * An approved action is carried out by an external executor and only reaches
 * Axis again when that executor reports back, so some wait is normal and does
 * not belong on a triage surface. Eight hours is one full production shift: a
 * run approved during a shift that still has no reported outcome by the end of
 * it has outlived the crew that authorised it, and is now something to chase.
 * The row states the actual wait, so an operator judges the age rather than
 * this threshold.
 */
const STALLED_ACTION_THRESHOLD_SECONDS = 8 * 60 * 60;

/*
 * A stalled run is a chase, not a decision, so it may never crowd out the
 * approvals and blocked workflows above it. Two lines are enough to show that
 * executors have stopped reporting; the full queue stays on the approvals
 * follow-through panel.
 */
const STALLED_ACTION_LIMIT = 2;

function isBlockedWorkflow(workflow: WorkflowSummary): boolean {
  return workflow.blocker !== null || workflow.state.includes("waiting");
}

function pendingRiskSignals(overview: ManufacturingOverview): RiskSignal[] {
  return overview.risk_signals.filter((signal) => signal.severity !== "ready");
}

/** Approved runs past the threshold, longest wait first. */
function stalledActionRuns(actionRuns: ActionRunList | null): ActionRunRecord[] {
  // `partitionActionRuns` already drops runs without an authorising approval
  // and orders the awaiting queue longest wait first.
  return partitionActionRuns(actionRuns?.runs ?? [])
    .awaiting.filter((run) => run.waiting_duration_seconds >= STALLED_ACTION_THRESHOLD_SECONDS)
    .slice(0, STALLED_ACTION_LIMIT);
}

function stalledActionDetail(run: ActionRunRecord): string {
  const waited = strings.approvals.followThrough.awaiting.waited(
    formatElapsedDuration(run.waiting_duration_seconds),
  );

  return `${waited} / ${strings.overview.needsAttention.stalledAction.noOutcome}`;
}

function AttentionRow({
  tone,
  title,
  detail,
  action,
}: {
  tone: React.ReactNode;
  title: string;
  detail: string;
  action: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-line px-4 py-3 dark:border-white/10">
      {tone}
      <div className="grid min-w-0 flex-1 gap-0.5">
        <p className="m-0 text-sm font-medium break-words text-ink">{title}</p>
        <p className="m-0 text-xs text-muted">{detail}</p>
      </div>
      {action}
    </div>
  );
}

function rowLinkClass(): string {
  return cn(
    "inline-flex items-center rounded-full border border-line px-3.5 py-1.5 text-xs font-medium",
    "text-ink transition-colors hover:border-signal/50 hover:text-signal dark:border-white/15",
  );
}

function ApprovalAttentionRow({
  approval,
  actor,
  identitySession,
  tenantId,
}: {
  approval: ApprovalInboxItem;
  actor?: { actorId: string; scopes: string[] };
  identitySession: IdentitySessionReadModel | null;
  tenantId: string;
}) {
  const [open, setOpen] = useState(false);
  const { decisions, errors, setDecision, setError } = useApprovalDecisionState();
  const decision = decisions[approval.approval_id];

  return (
    <>
      <AttentionRow
        action={
          <span className="flex items-center gap-2">
            {decision ? (
              <span className="status-pill signal-ready">
                {approvalDecisionLabel(decision.decision)}
              </span>
            ) : (
              <span className={`status-pill ${approvalRiskClass(approval.risk_level)}`}>
                {approval.risk_level}
              </span>
            )}
            <button className={rowLinkClass()} onClick={() => setOpen(true)} type="button">
              {strings.overview.needsAttention.review}
            </button>
          </span>
        }
        detail={`${approval.domain} / due ${approval.due}`}
        title={approval.action}
        tone={<StatusDot status={approval.risk_level === "high" ? "action_required" : "watch"} />}
      />
      <Sheet onOpenChange={setOpen} open={open}>
        <SheetContent aria-describedby={undefined}>
          <div className="grid gap-1 pr-8">
            <Eyebrow>{approval.domain}</Eyebrow>
            <SheetTitle className="font-display m-0 text-xl text-ink">
              {approval.action}
            </SheetTitle>
            <SheetDescription className="m-0 text-sm text-muted">
              {approval.summary}
            </SheetDescription>
          </div>
          <ApprovalDecisionCard
            actor={actor}
            approval={approval}
            decision={decision}
            error={errors[approval.approval_id]}
            identitySession={identitySession}
            onDecisionChange={setDecision}
            onErrorChange={setError}
            tenantId={tenantId}
          />
          <Link
            className="inline-flex w-fit items-center text-sm font-medium text-signal hover:underline"
            href="/approvals"
          >
            Open the full approval inbox
          </Link>
        </SheetContent>
      </Sheet>
    </>
  );
}

function SourceUnavailableNote({ message }: { message: string }) {
  return (
    <p className="m-0 flex items-center gap-2 text-xs text-danger">
      <TriangleAlert aria-hidden="true" size={14} />
      {message}
    </p>
  );
}

function AttentionSources({
  actionRuns,
  approvals,
  overview,
}: {
  actionRuns: OverviewQuery<ActionRunList>;
  approvals: OverviewQuery<ManufacturingApprovalInbox>;
  overview: OverviewQuery<ManufacturingOverview>;
}) {
  return (
    <div
      aria-label="Needs attention data sources"
      className="flex min-w-0 flex-wrap items-center justify-end gap-1.5"
    >
      <SourcePill
        state={deriveSourceState(
          overview.source,
          Boolean(overview.data),
          overview.data?.provenance,
        )}
        subject="risk context"
      />
      <SourcePill
        state={deriveSourceState(
          approvals.source,
          Boolean(approvals.data),
          approvals.data?.provenance,
        )}
        subject="approval queue"
      />
      <SourcePill
        state={deriveSourceState(
          actionRuns.source,
          Boolean(actionRuns.data),
          PROVENANCE_NOT_APPLICABLE,
        )}
        subject="action follow-through"
      />
    </div>
  );
}

export function NeedsAttention({
  actor,
  identitySession,
  overview,
  tenantId = DEMO_TENANT_ID,
}: {
  actor?: { actorId: string; scopes: string[] };
  identitySession: IdentitySessionReadModel | null;
  overview: OverviewQuery<ManufacturingOverview>;
  tenantId?: string;
}) {
  const approvalsQuery = useAxisQuery<ManufacturingApprovalInbox>(
    buildTenantScopedPath(APPROVALS_ENDPOINT, tenantId),
    { expectedTenantId: tenantId, parse: parseManufacturingApprovalInbox },
  );
  // Best effort: this source adds stalled runs to the strip, it never gates it.
  const actionRunsQuery = useAxisQuery<ActionRunList>(
    buildTenantScopedPath(ACTION_RUNS_ENDPOINT, tenantId),
    { expectedTenantId: tenantId, parse: parseActionRunList },
  );
  const copy = strings.overview.needsAttention;

  /*
   * "Nothing is waiting on you" is a governance claim, so it may only be made
   * once BOTH sources have reported. The gate used to require both to be
   * dataless: if the overview resolved empty while approvals was still in
   * flight, the panel announced "All clear" and then flipped to three pending
   * approvals a moment later.
   */
  if (overview.source === "loading" || approvalsQuery.source === "loading") {
    return <LoadingPanel rows={3} />;
  }

  if (!overview.data && !approvalsQuery.data) {

    return (
      <ErrorPanel
        detail={copy.error.detail}
        endpoint={`${APPROVALS_ENDPOINT} + ${OPERATIONS_API_PREFIX}/overview`}
        reference={overviewErrorReference(overview, approvalsQuery)}
        title={copy.error.title}
      />
    );
  }

  // Decided approvals stay as history in the approvals queue; here they would
  // only invite a decision that can no longer be recorded.
  const approvals =
    approvalsQuery.data?.approvals
      .filter((approval) => approval.status !== "decided")
      .slice(0, APPROVAL_LIMIT) ?? [];
  const blockedWorkflows = overview.data?.workflows.filter(isBlockedWorkflow) ?? [];
  const stalledRuns = stalledActionRuns(actionRunsQuery.data);
  const riskSignals = overview.data ? pendingRiskSignals(overview.data) : [];
  const approvalsFailed = !approvalsQuery.data && approvalsQuery.source === "unavailable";
  const overviewFailed = !overview.data && overview.source === "unavailable";
  const actionRunsFailed = !actionRunsQuery.data && actionRunsQuery.source === "unavailable";
  const itemCount =
    approvals.length + blockedWorkflows.length + stalledRuns.length + riskSignals.length;

  if (itemCount === 0 && !approvalsFailed && !overviewFailed && !actionRunsFailed) {
    // "All clear" now also claims that no approved action is stuck, so it waits
    // for the action-run source too. Only this claim waits: with items to show,
    // the strip renders while that source is still in flight.
    if (actionRunsQuery.source === "loading") {
      return <LoadingPanel rows={3} />;
    }

    return (
      <div className="grid gap-3">
        <AttentionSources
          actionRuns={actionRunsQuery}
          approvals={approvalsQuery}
          overview={overview}
        />
        <EmptyPanel
          detail={copy.allClear.detail}
          icon={CircleCheckBig}
          title={copy.allClear.title}
        />
      </div>
    );
  }

  return (
    <section aria-label={copy.eyebrow} className="grid gap-3">
      <PanelHeader
        aside={
          <AttentionSources
            actionRuns={actionRunsQuery}
            approvals={approvalsQuery}
            overview={overview}
          />
        }
        eyebrow={copy.eyebrow}
      />
      {approvalsFailed ? <SourceUnavailableNote message={copy.approvalsUnavailable} /> : null}
      {overviewFailed ? <SourceUnavailableNote message={copy.overviewUnavailable} /> : null}
      {actionRunsFailed ? <SourceUnavailableNote message={copy.actionRunsUnavailable} /> : null}
      <Card className="grid gap-2 p-4">
        {approvals.map((approval) => (
          <ApprovalAttentionRow
            approval={approval}
            actor={actor}
            identitySession={identitySession}
            key={approval.approval_id}
            tenantId={tenantId}
          />
        ))}
        {blockedWorkflows.map((workflow) => (
          <AttentionRow
            action={
              <Link className={rowLinkClass()} href="/workflows">
                {copy.openWorkflows}
              </Link>
            }
            detail={workflow.blocker ?? normalizeLabel(workflow.state)}
            key={workflow.workflow_id}
            title={workflow.name}
            tone={<GitBranch aria-hidden="true" className="shrink-0 text-warning" size={16} />}
          />
        ))}
        {stalledRuns.map((run) => (
          <AttentionRow
            action={
              <Link className={rowLinkClass()} href={buildApprovalHref(run.approval_id)}>
                {copy.openApproval}
              </Link>
            }
            detail={stalledActionDetail(run)}
            key={run.action_run_id}
            title={formatActionLabel(run.action_id)}
            tone={<Clock3 aria-hidden="true" className="shrink-0 text-warning" size={16} />}
          />
        ))}
        {riskSignals.map((signal) => (
          <AttentionRow
            action={
              <Link className={rowLinkClass()} href="/audit">
                {copy.openAudit}
              </Link>
            }
            detail={`${signal.domain} / ${normalizeLabel(signal.owner_role)}`}
            key={signal.title}
            title={signal.title}
            tone={
              <AlertTriangle
                aria-hidden="true"
                className={cn(
                  "shrink-0",
                  signal.severity === "action_required" ? "text-danger" : "text-warning",
                )}
                size={16}
              />
            }
          />
        ))}
      </Card>
    </section>
  );
}
