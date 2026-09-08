"use client";

import Link from "next/link";
import { useState } from "react";
import { Check, ChevronDown, ChevronRight, Inbox } from "lucide-react";

import {
  ApprovalDecisionCard,
  useApprovalDecisionState,
  type ApprovalDecisionRecord,
} from "@/components/approvals/approval-decision-card";
import { ApprovalQueue, filterApprovalQueue } from "@/components/approvals/approval-queue";
import { ApprovalReviewLayout } from "@/components/approvals/approval-review-layout";
import { ActionFollowThrough } from "@/components/approvals/action-follow-through";
import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { DetailGrid, KeyValueRow } from "@/components/ui/detail-grid";
import { Eyebrow } from "@/components/ui/eyebrow";
import { InspectDrawer } from "@/components/ui/inspect-drawer";
import { MasterDetail } from "@/components/ui/master-detail";
import type { Metric } from "@/components/ui/metric-strip";
import { SourcePill } from "@/components/ui/source-pill";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/ui/states";
import type { ActionRunList } from "@/lib/action-demo";
import {
  approvalDecisionLabel,
  approvalRiskClass,
  type ApprovalDecision,
  type ApprovalDecisionHistoryEntry,
  type ApprovalInboxItem,
  type ManufacturingApprovalInbox,
} from "@/lib/approval-demo";
import { cn } from "@/lib/cn";
import type { AxisOperatorError } from "@/lib/axis-api";
import { enumUrlField, opaqueStringUrlField, stringUrlField, useConsoleUrlState } from "@/lib/console-url-state";
import { formatContextPath, formatNumber, formatTimestamp } from "@/lib/format";
import { type IdentitySessionReadModel } from "@/lib/platform-overview";
import { deriveSourceState } from "@/lib/source-state";
import { strings } from "@/lib/strings";
import { parseActionRunList } from "@/lib/runtime-contracts/actions";
import { parseManufacturingApprovalInbox } from "@/lib/runtime-contracts/approvals";
import {
  parseManufacturingAuditExplorer,
} from "@/lib/runtime-contracts/audit";
import type { ManufacturingAuditExplorer } from "@/lib/audit-demo";
import {
  buildTenantScopedPath,
  DEMO_TENANT_ID,
  resolveConsoleTenantScope,
  OPERATIONS_API_PREFIX,
} from "@/lib/tenant-scope";
import { useAxisQuery } from "@/lib/use-axis-query";
import { useIdentitySession } from "@/lib/use-identity-session";
import { useConsole } from "@/providers/console-provider";
import { useTenantVocabulary } from "@/providers/tenant-vocabulary-provider";

const APPROVALS_ENDPOINT = `${OPERATIONS_API_PREFIX}/approvals`;
const ACTION_RUNS_ENDPOINT = `${OPERATIONS_API_PREFIX}/actions/runs`;
const AUDIT_EVENTS_ENDPOINT = `${OPERATIONS_API_PREFIX}/audit/events`;
const approvalUrlSchema = {
  approvalId: stringUrlField("approval_id"),
  actionRunId: stringUrlField("action_run_id"),
  search: opaqueStringUrlField("q"),
  risk: enumUrlField("risk", ["all", "high", "medium", "low"], "all"),
  domain: stringUrlField("domain"),
};

type RailStageState = "done" | "current" | "pending" | "required";

type RailStage = {
  label: string;
  detail: string;
  state: RailStageState;
};

/**
 * Stage rail derived from the real approval record: submission metadata,
 * the attached policy controls, the human decision, and the persisted audit
 * evidence returned by the decision API.
 */
function buildDecisionRail(
  approval: ApprovalInboxItem,
  decision: ApprovalDecisionRecord | undefined,
): RailStage[] {
  const decided = Boolean(decision);
  const recorded = decision?.storage === "persisted";

  return [
    {
      label: "Submitted",
      detail: `${approval.requested_by} / due ${approval.due}`,
      state: "done",
    },
    {
      label: "Required controls",
      detail: `${approval.required_permission} / ${approval.model_policy}`,
      state: "required",
    },
    {
      label: "Approval",
      detail: decision
        ? approvalDecisionLabel(decision.decision)
        : `${approval.owner_role} decision pending`,
      state: decided ? "done" : "current",
    },
    {
      label: "Recorded",
      detail: recorded
        ? (decision?.auditEventId ?? approval.audit_event_preview.event)
        : decided
          ? "Persisting audit evidence"
          : approval.audit_event_preview.event,
      state: recorded ? "done" : decided ? "current" : "pending",
    },
  ];
}

function DecisionRail({ approval, decision }: {
  approval: ApprovalInboxItem;
  decision: ApprovalDecisionRecord | undefined;
}) {
  return (
    <ol aria-label="Decision stage rail" className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2 2xl:grid-cols-4">
      {buildDecisionRail(approval, decision).map((stage, index) => (
        <li className="flex min-w-0 items-start gap-2" key={stage.label}>
          <span aria-hidden="true" className={cn(
            "flex size-6 shrink-0 items-center justify-center rounded-full border text-xs tabular-nums",
            stage.state === "pending" || stage.state === "required" ? "border-line text-muted dark:border-white/20" : "border-signal/40 bg-signal/10 text-signal",
          )}>
            {stage.state === "done" ? <Check size={13} /> : index + 1}
          </span>
          <div className="grid min-w-0 flex-1 grid-cols-1 gap-1">
            <p className="m-0 min-w-0 text-xs font-medium text-ink">
              {stage.label}<span className="sr-only">: {stage.state}</span>
            </p>
            <p className="m-0 min-w-0 text-xs leading-relaxed wrap-anywhere text-muted">{stage.detail}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

function CollapsibleSection({
  label,
  defaultOpen = false,
  children,
}: {
  label: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <Collapsible onOpenChange={setOpen} open={open}>
      <CollapsibleTrigger className="flex min-h-6 cursor-pointer items-center gap-1.5 bg-transparent p-0">
        <Chevron aria-hidden="true" className="text-muted" size={14} />
        <span className="eyebrow">{label}</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2 pl-5.5">{children}</CollapsibleContent>
    </Collapsible>
  );
}

function BulletList({ items }: { items: string[] }) {
  return (
    <ul className="m-0 grid list-none gap-1.5 p-0 text-sm text-muted">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

/**
 * Terminal outcomes, separate from the actionable queue. Every row is derived
 * from server-side persisted decision records; fields the record does not
 * carry are omitted rather than invented.
 */
function DecisionHistory({
  entries,
}: {
  entries: readonly ApprovalDecisionHistoryEntry[];
}) {
  return (
    <Card className="grid content-start gap-3" as="section">
      <div aria-label="Decision history" className="grid content-start gap-3">
        <div className="grid gap-1">
          <Eyebrow>{strings.approvals.history.eyebrow}</Eyebrow>
          <h2 className="font-display m-0 text-xl text-ink">
            {strings.approvals.history.title}
          </h2>
          <p className="m-0 text-sm text-muted">{strings.approvals.history.description}</p>
        </div>
        {entries.length === 0 ? (
          <p className="m-0 text-sm text-muted" role="status">
            {strings.approvals.history.empty}
          </p>
        ) : (
          <ul className="m-0 grid list-none gap-2 p-0">
            {entries.map((entry) => {
              const decision = entry.decision as ApprovalDecision | undefined;
              const knownDecision =
                decision === "approve" || decision === "reject" || decision === "request_changes";
              return (
                <li
                  className="grid gap-1.5 rounded-2xl border border-line px-4 py-3 dark:border-white/10"
                  data-decision-history-entry={entry.approval_id}
                  key={entry.approval_id}
                >
                  <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <span className="flex min-w-0 items-center gap-2">
                      {knownDecision ? (
                        <span
                          className={`status-pill ${decision === "approve" ? "signal-ready" : ""}`}
                        >
                          {approvalDecisionLabel(decision)}
                        </span>
                      ) : (
                        <span className="status-pill">{entry.decision}</span>
                      )}
                      <span className="truncate text-sm font-medium text-ink">
                        {entry.action}
                      </span>
                    </span>
                    {entry.audit_event_id ? (
                      <Link
                        className="inline-flex items-center text-xs font-medium text-signal hover:underline"
                        href={`/audit?event_id=${encodeURIComponent(entry.audit_event_id)}`}
                      >
                        {strings.approvals.decision.auditLink}
                      </Link>
                    ) : null}
                  </div>
                  <p className="m-0 font-mono text-xs text-muted">
                    {[
                      entry.decided_by ?? strings.approvals.history.actorUnknown,
                      entry.decided_at ? formatTimestamp(entry.decided_at) : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                  {entry.rationale ? (
                    <p className="m-0 text-sm leading-snug text-muted">{entry.rationale}</p>
                  ) : null}
                  {entry.follow_through_status ? (
                    <p className="m-0 text-xs text-muted">
                      {strings.approvals.history.followThrough}{" "}
                      <span className="font-mono">{entry.follow_through_status}</span>
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
}

function ApprovalDetail({
  approval,
  actor,
  decision,
  domainLabel,
  error,
  identitySession,
  onDecisionChange,
  onErrorChange,
  tenantId,
}: {
  approval: ApprovalInboxItem;
  actor?: { actorId: string; scopes: string[] };
  decision: ApprovalDecisionRecord | undefined;
  domainLabel: string;
  error: AxisOperatorError | undefined;
  identitySession: IdentitySessionReadModel | null;
  onDecisionChange: (approvalId: string, record: ApprovalDecisionRecord | null) => void;
  onErrorChange: (approvalId: string, error: AxisOperatorError | null) => void;
  tenantId: string;
}) {
  return (
    <Card className="grid min-w-0 content-start gap-5">
      <div className="grid min-w-0 gap-3">
        <div className="grid min-w-0 gap-1">
          <Eyebrow>{domainLabel || approval.domain}</Eyebrow>
          <h2 className="font-display m-0 text-xl break-words text-ink">{approval.action}</h2>
          <p className="m-0 text-sm leading-relaxed break-words text-muted">{approval.summary}</p>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted">
          <span className={`status-pill ${approvalRiskClass(approval.risk_level)}`}>
            {approval.risk_level} risk
          </span>
          <span>Due {approval.due}</span>
          <span className="min-w-0 [overflow-wrap:anywhere]">Owner: {approval.owner_role}</span>
        </div>
      </div>

      <ApprovalDecisionCard
        actor={actor}
        approval={approval}
        decision={decision}
        error={error}
        identitySession={identitySession}
        onDecisionChange={onDecisionChange}
        onErrorChange={onErrorChange}
        tenantId={tenantId}
      />

      <div aria-hidden="true" className="rule-hairline" />

      <CollapsibleSection defaultOpen label={strings.approvals.sections.evidence}>
        <div className="grid gap-3">
          <BulletList items={approval.evidence} />
          <div className="grid gap-1.5">
            <p className="m-0 text-xs font-medium text-muted">
              {strings.approvals.sections.dataAccessed}
            </p>
            <div className="flex flex-wrap gap-2">
              {approval.data_accessed.map((item) => (
                <span
                  className="inline-flex items-center rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted dark:border-white/15 dark:bg-transparent"
                  key={item}
                >
                  {item}
                </span>
              ))}
            </div>
          </div>
        </div>
      </CollapsibleSection>

      <CollapsibleSection defaultOpen label={strings.approvals.sections.risksAlternatives}>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid content-start gap-1.5">
            <p className="m-0 text-xs font-medium text-muted">Risks</p>
            <BulletList items={approval.risks} />
          </div>
          <div className="grid content-start gap-1.5">
            <p className="m-0 text-xs font-medium text-muted">Alternatives</p>
            <BulletList items={approval.alternatives} />
          </div>
        </div>
      </CollapsibleSection>

      <div aria-hidden="true" className="rule-hairline" />

      <CollapsibleSection label="Decision trail">
        <DecisionRail approval={approval} decision={decision} />
      </CollapsibleSection>

      <div className="grid gap-3">
        <DetailGrid>
          <KeyValueRow label="Workflow" mono>
            <span className="block max-w-full truncate" title={approval.workflow_id}>
              {approval.workflow_id}
            </span>
          </KeyValueRow>
          <KeyValueRow label="Requested by">{approval.requested_by}</KeyValueRow>
          <KeyValueRow label="Cost exposure">{approval.estimated_cost}</KeyValueRow>
        </DetailGrid>
        <InspectDrawer
          record={{ tenant_id: tenantId, ...approval }}
          title={approval.action}
          trigger={
            <button
              className="inline-flex min-h-6 w-fit cursor-pointer items-center font-mono text-xs text-muted transition-colors duration-200 hover:text-signal"
              type="button"
            >
              {strings.approvals.sections.inspect}
            </button>
          }
        />
      </div>
    </Card>
  );
}

export function ApprovalInbox() {
  const { labelDomain } = useTenantVocabulary();
  const { triggerRefresh } = useConsole();
  const identity = useIdentitySession();
  const tenantScope = resolveConsoleTenantScope(identity.data);
  const tenantId = tenantScope.tenantId;
  const {
    data: inbox,
    errorRequestId: inboxErrorRequestId,
    source,
  } = useAxisQuery<ManufacturingApprovalInbox>(
    buildTenantScopedPath(APPROVALS_ENDPOINT, tenantId ?? DEMO_TENANT_ID),
    {
      enabled: identity.source === "api" && tenantId !== null,
      expectedTenantId: tenantId ?? undefined,
      parse: parseManufacturingApprovalInbox,
    },
  );
  const actionRunsQuery = useAxisQuery<ActionRunList>(
    buildTenantScopedPath(ACTION_RUNS_ENDPOINT, tenantId ?? DEMO_TENANT_ID),
    {
      enabled: identity.source === "api" && tenantId !== null,
      expectedTenantId: tenantId ?? undefined,
      parse: parseActionRunList,
    },
  );
  const [urlState, setUrlState] = useConsoleUrlState(approvalUrlSchema);
  const actionRunAudit = useAxisQuery<ManufacturingAuditExplorer>(
    buildTenantScopedPath(
      AUDIT_EVENTS_ENDPOINT,
      tenantId ?? DEMO_TENANT_ID,
      { limit: 100 },
    ),
    {
      enabled: identity.source === "api" && tenantId !== null && Boolean(urlState.actionRunId),
      expectedTenantId: tenantId ?? undefined,
      parse: parseManufacturingAuditExplorer,
    },
  );
  const { decisions, errors, setDecision, setError } = useApprovalDecisionState();

  function handleDecisionChange(
    approvalId: string,
    record: ApprovalDecisionRecord | null,
  ) {
    setDecision(approvalId, record);
    if (record?.storage === "persisted") {
      // The decided approval leaves the actionable queue; pin it in the URL so
      // the operator keeps reviewing exactly what they just decided while the
      // refreshed queue reconciles and the history section picks it up.
      setUrlState({ actionRunId: "", approvalId });
      triggerRefresh();
    }
  }

  if (identity.source === "unavailable") {
    return (
      <ErrorPanel
        detail="The approval queue is not loaded until the current actor and tenant are verified."
        endpoint="/identity/session"
        reference={identity.errorRequestId ?? undefined}
        title="Identity API unavailable"
      />
    );
  }

  if (identity.source === "api" && !tenantId) {
    return (
      <ErrorPanel
        detail="The authenticated identity response does not contain a tenant."
        endpoint="/identity/session"
        title="Authenticated tenant missing"
      />
    );
  }

  if (!inbox) {
    if (source === "loading") {
      return (
        <div aria-label="Loading approval API" className="grid gap-4">
          <LoadingPanel layout="metrics" rows={3} />
          <MasterDetail
            detail={<LoadingPanel layout="detail" />}
            list={<LoadingPanel rows={4} />}
          />
        </div>
      );
    }

    return (
      <ErrorPanel
        detail={strings.approvals.error.detail}
        endpoint={APPROVALS_ENDPOINT}
        reference={inboxErrorRequestId ?? undefined}
        title={strings.approvals.error.title}
      />
    );
  }

  const directActionRunApproval = urlState.actionRunId
    ? inbox.approvals.find((approval) => approval.action_run_id === urlState.actionRunId)
    : undefined;
  // The actionable queue is server truth minus terminal decisions; decided
  // work moves to the decision history instead of lingering in the inbox.
  const actionableApprovals = inbox.approvals.filter(
    (approval) =>
      approval.status !== "decided" && !decisions[approval.approval_id],
  );
  const filteredApprovals = filterApprovalQueue(actionableApprovals, urlState, labelDomain);
  const detailOpen = Boolean(urlState.approvalId || urlState.actionRunId);
  const linkedApprovalId = urlState.actionRunId
    ? actionRunAudit.data?.events.find(
        (event) => event.evidence_refs.includes(urlState.actionRunId),
      )?.payload_preview.approval_id
    : undefined;
  const selectedApproval = urlState.actionRunId
    ? directActionRunApproval
      ?? inbox.approvals.find((approval) => approval.approval_id === linkedApprovalId)
    : urlState.approvalId
      ? inbox.approvals.find((approval) => approval.approval_id === urlState.approvalId)
      : filteredApprovals[0];

  if (
    urlState.actionRunId
    && !directActionRunApproval
    && actionRunAudit.source === "loading"
  ) {
    return <LoadingPanel layout="detail" />;
  }

  if (
    urlState.actionRunId
    && !directActionRunApproval
    && actionRunAudit.source === "unavailable"
  ) {
    return (
      <ErrorPanel
        detail={strings.approvals.lookupError.detail}
        endpoint={AUDIT_EVENTS_ENDPOINT}
        reference={actionRunAudit.errorRequestId ?? undefined}
        title={strings.approvals.lookupError.title}
      />
    );
  }

  // A decision counts as decided whether it was recorded in this session or
  // already persisted and reconciled into the queue by the API.
  const decidedCount = inbox.approvals.filter(
    (approval) =>
      Boolean(decisions[approval.approval_id]) || approval.status === "decided",
  ).length;
  const pendingCount = inbox.approvals.length - decidedCount;
  const highRiskCount = inbox.approvals.filter(
    (approval) =>
      approval.risk_level === "high"
      && !decisions[approval.approval_id]
      && approval.status !== "decided",
  ).length;

  const metrics: Metric[] = [
    {
      label: strings.approvals.metrics.pending,
      value: pendingCount,
      detail: strings.approvals.metrics.pendingDetail,
      tone: pendingCount > 0 ? "watch" : "ready",
    },
    {
      label: strings.approvals.metrics.highRisk,
      value: highRiskCount,
      detail: strings.approvals.metrics.highRiskDetail,
      tone: highRiskCount > 0 ? "action" : "ready",
    },
    {
      label: strings.approvals.metrics.decided,
      value: decidedCount,
      detail: strings.approvals.metrics.decidedDetail,
      tone: "ready",
    },
  ];

  return (
    <div className="grid gap-4">
      <div
        aria-label="Approval source and status"
        className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2"
      >
        <p className="m-0 min-w-0 text-sm break-words text-muted">
          {formatContextPath(inbox.plant_name, inbox.scenario)}
        </p>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <SourcePill
            state={deriveSourceState(source, Boolean(inbox), inbox.provenance)}
            subject="approval queue"
          />
          <span className="font-mono text-xs text-muted">
            {formatTimestamp(inbox.as_of)}
          </span>
        </div>
      </div>

      <div aria-label="Approval metrics" className={cn("grid grid-cols-3 divide-x divide-line overflow-hidden rounded-xl border border-line bg-surface dark:divide-white/10 dark:border-white/10", detailOpen && "hidden lg:grid")} role="list">
        {metrics.map((metric) => (
          <div className="grid min-w-0 gap-1 px-3 py-3 sm:px-4" key={metric.label} role="listitem">
            <p className="m-0 text-xs font-medium text-muted">{metric.label}</p>
            <p className="m-0 text-xl font-medium tabular-nums text-ink">
              <span className="sr-only">{metric.tone === "ready" ? "Ready:" : metric.tone === "watch" ? "Needs watching:" : "Action required:"} </span>
              {formatNumber(Number(metric.value))}
            </p>
            <p className="m-0 hidden text-xs text-muted sm:block">{metric.detail}</p>
          </div>
        ))}
      </div>

      <ApprovalReviewLayout
        approvalId={selectedApproval?.approval_id}
        open={detailOpen}
        onBack={() => setUrlState({ actionRunId: "", approvalId: "" })}
        queue={
          <ApprovalQueue
            allApprovals={actionableApprovals}
            approvals={filteredApprovals}
            filters={urlState}
            labelDomain={labelDomain}
            onFilterChange={(change) => setUrlState({ ...change, actionRunId: "", approvalId: "" })}
            onReset={() => setUrlState({ search: "", risk: "all", domain: "", actionRunId: "", approvalId: "" })}
            onSelect={(approvalId, pushHistory) => setUrlState({ actionRunId: "", approvalId }, { history: pushHistory ? "push" : "replace" })}
            selectedApprovalId={selectedApproval?.approval_id}
          />
        }
        detail={selectedApproval ? (
          <>
          {detailOpen && actionableApprovals.some((approval) => approval.approval_id === selectedApproval.approval_id) && !filteredApprovals.some((approval) => approval.approval_id === selectedApproval.approval_id) ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line bg-surface p-3 text-sm dark:border-white/10">
              <p className="m-0 text-muted">This linked approval is outside the current queue filters.</p>
              <button className="min-h-9 cursor-pointer font-medium text-signal" onClick={() => setUrlState({ search: "", risk: "all", domain: "" })} type="button">Clear queue filters</button>
            </div>
          ) : null}
          <ApprovalDetail
            actor={identity.data?.actor_id ? { actorId: identity.data.actor_id, scopes: identity.data.scopes } : undefined}
            approval={selectedApproval}
            decision={decisions[selectedApproval.approval_id]}
            domainLabel={labelDomain(selectedApproval.domain)}
            identitySession={identity.data ?? null}
            error={errors[selectedApproval.approval_id]}
            onDecisionChange={handleDecisionChange}
            onErrorChange={setError}
            tenantId={inbox.tenant_id}
          />
          </>
        ) : (
          <EmptyPanel
            detail={detailOpen ? strings.approvals.requestedMissing.detail : actionableApprovals.length ? strings.approvals.queue.selectDetail : strings.approvals.empty.detail}
            icon={Inbox}
            title={detailOpen ? strings.approvals.requestedMissing.title : actionableApprovals.length ? strings.approvals.queue.select : strings.approvals.empty.title}
          />
        )}
      />

      <DecisionHistory entries={inbox.decision_history ?? []} />

      <ActionFollowThrough
        actionRuns={actionRunsQuery.data}
        errorRequestId={actionRunsQuery.errorRequestId}
        source={actionRunsQuery.source}
      />

      <Card className="grid content-start gap-3">
        <Eyebrow>Policy Notes</Eyebrow>
        <div className="grid gap-2">
          {inbox.policy_notes.map((note) => (
            <p className="m-0 text-sm text-muted" key={note}>
              {note}
            </p>
          ))}
        </div>
      </Card>
    </div>
  );
}
