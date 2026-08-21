import { Clock3, History, MessageSquareText } from "lucide-react";
import Link from "next/link";

import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/ui/states";
import { SourcePill } from "@/components/ui/source-pill";
import {
  formatActionLabel,
  partitionActionRuns,
  type ActionRunList,
  type ActionRunRecord,
} from "@/lib/action-demo";
import { buildApprovalHref } from "@/lib/approval-demo";
import { buildAuditEventHref } from "@/lib/audit-demo";
import { formatDateTime, formatElapsedDuration, formatNumber } from "@/lib/format";
import {
  deriveSourceState,
  PROVENANCE_NOT_APPLICABLE,
  type AxisSource,
} from "@/lib/source-state";
import { strings } from "@/lib/strings";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

const ACTION_RUNS_ENDPOINT = `${OPERATIONS_API_PREFIX}/actions/runs`;

function RunLinks({ run }: { run: ActionRunRecord }) {
  const copy = strings.approvals.followThrough;

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
      {run.approval_id ? (
        <Link
          className="inline-flex min-h-6 min-w-6 items-center font-mono text-xs text-signal underline-offset-2 hover:underline"
          href={buildApprovalHref(run.approval_id)}
        >
          {copy.links.approval}
        </Link>
      ) : (
        <span className="font-mono text-xs text-muted">{copy.fields.noApproval}</span>
      )}
      {run.outcome ? (
        run.outcome.evidence_refs.length > 0 ? (
          run.outcome.evidence_refs.map((reference, index) => (
            <Link
              aria-label={`${copy.links.auditEvidence}: ${reference}`}
              className="inline-flex min-h-6 min-w-6 items-center font-mono text-xs text-signal underline-offset-2 hover:underline"
              href={buildAuditEventHref(reference)}
              key={`${run.action_run_id}:${reference}:${index}`}
            >
              {copy.links.auditEvidence}
              {run.outcome && run.outcome.evidence_refs.length > 1 ? ` ${index + 1}` : ""}
            </Link>
          ))
        ) : (
          <span className="font-mono text-xs text-muted">{copy.fields.noAuditEvidence}</span>
        )
      ) : null}
    </div>
  );
}

function RunMetadata({
  run,
  timestamp,
  timestampLabel,
}: {
  run: ActionRunRecord;
  timestamp: string;
  timestampLabel: string;
}) {
  const copy = strings.approvals.followThrough;

  return (
    <dl className="m-0 grid min-w-0 gap-x-5 gap-y-2 sm:grid-cols-3">
      <div className="grid min-w-0 gap-0.5">
        <dt className="eyebrow m-0">{timestampLabel}</dt>
        <dd className="m-0 text-xs text-muted">{formatDateTime(timestamp)}</dd>
      </div>
      <div className="grid min-w-0 gap-0.5">
        <dt className="eyebrow m-0">{copy.fields.workflow}</dt>
        <dd
          className="m-0 truncate font-mono text-xs text-muted"
          title={run.workflow_id ?? undefined}
        >
          {run.workflow_id ?? copy.fields.noWorkflow}
        </dd>
      </div>
      <div className="grid min-w-0 gap-0.5">
        <dt className="eyebrow m-0">{copy.fields.run}</dt>
        <dd className="m-0 truncate font-mono text-xs text-muted" title={run.action_run_id}>
          {run.action_run_id}
        </dd>
      </div>
    </dl>
  );
}

function AwaitingRun({ run }: { run: ActionRunRecord }) {
  const copy = strings.approvals.followThrough;

  return (
    <article className="grid min-w-0 gap-3 py-4">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="grid min-w-0 gap-1">
          <h4 className="font-display m-0 text-base text-ink">
            {formatActionLabel(run.action_id)}
          </h4>
          <p className="m-0 flex items-center gap-1.5 text-sm font-medium text-ink">
            <Clock3 aria-hidden="true" className="shrink-0 text-warning" size={15} />
            {copy.awaiting.waited(formatElapsedDuration(run.waiting_duration_seconds))}
          </p>
        </div>
        <span className="status-pill signal-watch">{copy.awaiting.status}</span>
      </div>
      <RunMetadata
        run={run}
        timestamp={run.created_at}
        timestampLabel={copy.fields.approved}
      />
      <RunLinks run={run} />
    </article>
  );
}

function ReportedRun({ run }: { run: ActionRunRecord }) {
  const copy = strings.approvals.followThrough;

  if (!run.outcome) {
    return null;
  }

  return (
    <article className="grid min-w-0 gap-3 py-4">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div className="grid min-w-0 gap-1">
          <h4 className="font-display m-0 text-base text-ink">
            {formatActionLabel(run.action_id)}
          </h4>
          <p className="m-0 text-sm leading-snug text-ink">{run.outcome.result_summary}</p>
        </div>
        <span className="status-pill status-checking">
          <MessageSquareText aria-hidden="true" size={14} />
          {formatActionLabel(run.status)}
        </span>
      </div>
      <RunMetadata
        run={run}
        timestamp={run.updated_at}
        timestampLabel={copy.fields.reported}
      />
      <RunLinks run={run} />
    </article>
  );
}

export function ActionFollowThrough({
  actionRuns,
  errorRequestId,
  source,
}: {
  actionRuns: ActionRunList | null;
  errorRequestId?: string | null;
  source: AxisSource;
}) {
  const copy = strings.approvals.followThrough;
  const followThrough = partitionActionRuns(actionRuns?.runs ?? []);
  const hasVisibleRuns = followThrough.awaiting.length > 0 || followThrough.reported.length > 0;

  return (
    <Card aria-labelledby="action-follow-through-title" as="section" className="grid gap-5">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
        <div className="grid max-w-2xl gap-1">
          <Eyebrow>{copy.eyebrow}</Eyebrow>
          <h2 className="font-display m-0 text-xl text-ink" id="action-follow-through-title">
            {copy.title}
          </h2>
          <p className="m-0 text-sm leading-snug text-muted">{copy.detail}</p>
        </div>
        <SourcePill
          state={deriveSourceState(source, Boolean(actionRuns), PROVENANCE_NOT_APPLICABLE)}
          subject={copy.sourceSubject}
        />
      </div>

      {source === "unavailable" && actionRuns ? (
        <p className="m-0 text-sm text-warning" role="status">
          {copy.stale}
        </p>
      ) : null}

      {source === "loading" && !actionRuns ? (
        <LoadingPanel rows={3} />
      ) : source === "unavailable" && !actionRuns ? (
        <ErrorPanel
          detail={copy.error.detail}
          endpoint={ACTION_RUNS_ENDPOINT}
          reference={errorRequestId ?? undefined}
          title={copy.error.title}
        />
      ) : actionRuns && !hasVisibleRuns ? (
        <EmptyPanel detail={copy.empty.detail} icon={History} title={copy.empty.title} />
      ) : actionRuns ? (
        <div className="grid items-start gap-5 lg:grid-cols-2">
          <section
            aria-labelledby="awaiting-execution-title"
            className="grid min-w-0 content-start gap-3"
          >
            <div className="flex min-w-0 items-start justify-between gap-3 border-b border-line/60 pb-3 dark:border-white/10">
              <div className="grid min-w-0 gap-1">
                <h3
                  className="font-display m-0 text-lg text-ink"
                  id="awaiting-execution-title"
                >
                  {copy.awaiting.title}
                </h3>
                <p className="m-0 text-xs leading-snug text-muted">{copy.awaiting.detail}</p>
              </div>
              <span className="status-pill signal-watch">
                {formatNumber(followThrough.awaiting.length)}
              </span>
            </div>
            {followThrough.awaiting.length > 0 ? (
              <ol className="m-0 grid list-none divide-y divide-line/60 p-0 dark:divide-white/10">
                {followThrough.awaiting.map((run) => (
                  <li key={run.action_run_id}>
                    <AwaitingRun run={run} />
                  </li>
                ))}
              </ol>
            ) : (
              <EmptyPanel detail={copy.awaiting.emptyDetail} title={copy.awaiting.emptyTitle} />
            )}
          </section>

          <section
            aria-labelledby="reported-outcomes-title"
            className="grid min-w-0 content-start gap-3"
          >
            <div className="flex min-w-0 items-start justify-between gap-3 border-b border-line/60 pb-3 dark:border-white/10">
              <div className="grid min-w-0 gap-1">
                <h3
                  className="font-display m-0 text-lg text-ink"
                  id="reported-outcomes-title"
                >
                  {copy.reported.title}
                </h3>
                <p className="m-0 text-xs leading-snug text-muted">{copy.reported.detail}</p>
              </div>
              <span className="status-pill status-checking">
                {formatNumber(followThrough.reported.length)}
              </span>
            </div>
            {followThrough.reported.length > 0 ? (
              <ol className="m-0 grid list-none divide-y divide-line/60 p-0 dark:divide-white/10">
                {followThrough.reported.map((run) => (
                  <li key={run.action_run_id}>
                    <ReportedRun run={run} />
                  </li>
                ))}
              </ol>
            ) : (
              <EmptyPanel detail={copy.reported.emptyDetail} title={copy.reported.emptyTitle} />
            )}
          </section>
        </div>
      ) : null}
    </Card>
  );
}
