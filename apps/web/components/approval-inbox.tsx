"use client";

import { useRef, useState, type KeyboardEvent } from "react";
import { ChevronDown, ChevronRight, Inbox, ShieldAlert } from "lucide-react";

import {
  ApprovalDecisionCard,
  useApprovalDecisionState,
  type ApprovalDecisionRecord,
} from "@/components/approvals/approval-decision-card";
import { ActionFollowThrough } from "@/components/approvals/action-follow-through";
import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { DetailGrid, KeyValueRow } from "@/components/ui/detail-grid";
import { Eyebrow } from "@/components/ui/eyebrow";
import { InspectDrawer } from "@/components/ui/inspect-drawer";
import { MasterDetail } from "@/components/ui/master-detail";
import { MetricStrip, type Metric } from "@/components/ui/metric-strip";
import { SourcePill } from "@/components/ui/source-pill";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/ui/states";
import type { ActionRunList } from "@/lib/action-demo";
import {
  approvalDecisionLabel,
  approvalRiskClass,
  type ApprovalInboxItem,
  type ManufacturingApprovalInbox,
} from "@/lib/approval-demo";
import { cn } from "@/lib/cn";
import type { AxisOperatorError } from "@/lib/axis-api";
import { stringUrlField, useConsoleUrlState } from "@/lib/console-url-state";
import { formatContextPath, formatNumber, formatTimestamp } from "@/lib/format";
import { type IdentitySessionReadModel, platformStatusClass } from "@/lib/platform-overview";
import { deriveSourceState } from "@/lib/source-state";
import { strings } from "@/lib/strings";
import { parseActionRunList } from "@/lib/runtime-contracts/actions";
import { parseManufacturingApprovalInbox } from "@/lib/runtime-contracts/approvals";
import {
  parseManufacturingAuditExplorer,
} from "@/lib/runtime-contracts/audit";
import type { ManufacturingAuditExplorer } from "@/lib/audit-demo";
import { parseIdentitySessionReadModel } from "@/lib/runtime-contracts/overview";
import {
  buildTenantScopedPath,
  DEMO_TENANT_ID,
  resolveConsoleTenantScope,
  OPERATIONS_API_PREFIX,
} from "@/lib/tenant-scope";
import { useAxisQuery } from "@/lib/use-axis-query";
import { useConsole } from "@/providers/console-provider";
import { useTenantVocabulary } from "@/providers/tenant-vocabulary-provider";

const APPROVALS_ENDPOINT = `${OPERATIONS_API_PREFIX}/approvals`;
const ACTION_RUNS_ENDPOINT = `${OPERATIONS_API_PREFIX}/actions/runs`;
const AUDIT_EVENTS_ENDPOINT = `${OPERATIONS_API_PREFIX}/audit/events`;
const approvalUrlSchema = {
  approvalId: stringUrlField("approval_id"),
  actionRunId: stringUrlField("action_run_id"),
};

type RailStageState = "done" | "current" | "pending";

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
      label: "Policy evaluation",
      detail: `${approval.required_permission} / ${approval.model_policy}`,
      state: "done",
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

function RailMarker({ state }: { state: RailStageState }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block size-2.5 shrink-0 rotate-45",
        state === "done" && "bg-signal",
        state === "current" && "border-2 border-signal bg-transparent",
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

function DecisionRail({
  approval,
  decision,
}: {
  approval: ApprovalInboxItem;
  decision: ApprovalDecisionRecord | undefined;
}) {
  const stages = buildDecisionRail(approval, decision);
  const currentIndex = stages.findIndex((stage) => stage.state === "current");

  return (
    <div className="grid gap-1.5" aria-label="Decision stage rail">
      <div className="flex items-center gap-2">
        {stages.map((stage, index) => (
          <div
            className={cn("flex items-center gap-2", index > 0 && "min-w-0 flex-1")}
            key={stage.label}
          >
            {index > 0 ? (
              <div className="rule-hairline relative h-px min-w-6 flex-1 overflow-hidden">
                {index === currentIndex ? (
                  <span
                    className="absolute top-1/2 left-0 h-[3px] w-1/5 -translate-y-1/2 rounded-full bg-signal"
                    style={{ animation: "rail-pulse 1.8s linear infinite" }}
                  />
                ) : null}
              </div>
            ) : null}
            <RailMarker state={stage.state} />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-4 gap-2">
        {stages.map((stage) => (
          <div className="grid min-w-0 gap-0.5" key={stage.label}>
            <p
              className={cn(
                "m-0 font-mono text-[10px] tracking-[0.14em] uppercase",
                stage.state === "pending" ? "text-muted" : "text-signal",
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

function QueueList({
  inbox,
  selectedApproval,
  decisions,
  labelDomain,
  onSelect,
}: {
  inbox: ManufacturingApprovalInbox;
  selectedApproval: ApprovalInboxItem;
  decisions: Record<string, ApprovalDecisionRecord>;
  labelDomain: (domain: string) => string;
  onSelect: (approvalId: string) => void;
}) {
  const itemRefs = useRef(new Map<string, HTMLButtonElement>());

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
      return;
    }
    event.preventDefault();

    const index = inbox.approvals.findIndex(
      (approval) => approval.approval_id === selectedApproval.approval_id,
    );
    const nextIndex =
      event.key === "ArrowDown"
        ? Math.min(index + 1, inbox.approvals.length - 1)
        : Math.max(index - 1, 0);
    const next = inbox.approvals[nextIndex];
    if (next && next.approval_id !== selectedApproval.approval_id) {
      onSelect(next.approval_id);
      itemRefs.current.get(next.approval_id)?.focus();
    }
  }

  return (
    <Card className="grid content-start gap-4">
      <div className="grid gap-1">
        <Eyebrow>{strings.approvals.queue.eyebrow}</Eyebrow>
        <h2 className="font-display m-0 text-xl text-ink">{strings.approvals.queue.title}</h2>
      </div>
      {/* Roving arrow-key selection across the queue buttons. */}
      <div className="grid gap-2" onKeyDown={handleKeyDown}>
        {inbox.approvals.map((approval) => {
          const decision = decisions[approval.approval_id];
          const isSelected = approval.approval_id === selectedApproval.approval_id;

          return (
            <button
              aria-pressed={isSelected}
              className={cn(
                "flex w-full cursor-pointer items-start justify-between gap-3 rounded-2xl border px-4 py-3 text-left transition-colors",
                isSelected
                  ? "border-signal/60 bg-tint-100 dark:bg-signal/15"
                  : "border-line bg-transparent hover:border-signal/40 hover:bg-tint-50 dark:border-white/10 dark:hover:bg-white/5",
              )}
              key={approval.approval_id}
              onClick={() => onSelect(approval.approval_id)}
              ref={(element) => {
                if (element) {
                  itemRefs.current.set(approval.approval_id, element);
                } else {
                  itemRefs.current.delete(approval.approval_id);
                }
              }}
              type="button"
            >
              <span className="grid min-w-0 gap-0.5">
                <span className="text-sm font-medium text-ink">{approval.action}</span>
                <span className="text-xs text-muted">
                  {labelDomain(approval.domain)} / {approval.owner_role}
                </span>
                <span className="font-mono text-xs text-muted">Due {approval.due}</span>
              </span>
              <span
                className={`status-pill ${
                  decision ? "signal-ready" : approvalRiskClass(approval.risk_level)
                }`}
              >
                {decision ? approvalDecisionLabel(decision.decision) : approval.risk_level}
              </span>
            </button>
          );
        })}
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
  onDecisionChange,
  onErrorChange,
  tenantId,
}: {
  approval: ApprovalInboxItem;
  actor?: { actorId: string; scopes: string[] };
  decision: ApprovalDecisionRecord | undefined;
  domainLabel: string;
  error: AxisOperatorError | undefined;
  onDecisionChange: (approvalId: string, record: ApprovalDecisionRecord | null) => void;
  onErrorChange: (approvalId: string, error: AxisOperatorError | null) => void;
  tenantId: string;
}) {
  return (
    <Card className="grid content-start gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid max-w-xl gap-1">
          <Eyebrow>{domainLabel || approval.domain}</Eyebrow>
          <h2 className="font-display m-0 text-xl text-ink">{approval.action}</h2>
          <p className="m-0 text-sm text-muted">{approval.summary}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <span className={`status-pill ${approvalRiskClass(approval.risk_level)}`}>
            {approval.risk_level}
          </span>
          <span className="font-mono text-xs text-muted">Due {approval.due}</span>
        </div>
      </div>

      <ApprovalDecisionCard
        actor={actor}
        approval={approval}
        decision={decision}
        error={error}
        onDecisionChange={onDecisionChange}
        onErrorChange={onErrorChange}
        tenantId={tenantId}
      />

      <DecisionRail approval={approval} decision={decision} />

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

      <CollapsibleSection label={strings.approvals.sections.risksAlternatives}>
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

      <div className="grid gap-3">
        <DetailGrid>
          <KeyValueRow label="Workflow" mono>
            <span className="block max-w-full truncate" title={approval.workflow_id}>
              {approval.workflow_id}
            </span>
          </KeyValueRow>
          <KeyValueRow label="Requested by">{approval.requested_by}</KeyValueRow>
          <KeyValueRow label="Owner">{approval.owner_role}</KeyValueRow>
          <KeyValueRow label="Cost exposure">{approval.estimated_cost}</KeyValueRow>
        </DetailGrid>
        <InspectDrawer
          record={approval}
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
  const identity = useAxisQuery<IdentitySessionReadModel>("/identity/session", {
    parse: parseIdentitySessionReadModel,
  });
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
      : inbox.approvals[0];

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

  if (!selectedApproval && (urlState.actionRunId || urlState.approvalId)) {
    return (
      <EmptyPanel
        detail={strings.approvals.requestedMissing.detail}
        icon={Inbox}
        title={strings.approvals.requestedMissing.title}
      />
    );
  }
  const decidedCount = inbox.approvals.filter(
    (approval) => decisions[approval.approval_id],
  ).length;
  const pendingCount = inbox.approvals.length - decidedCount;
  const highRiskCount = inbox.approvals.filter(
    (approval) => approval.risk_level === "high" && !decisions[approval.approval_id],
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
          {formatContextPath(inbox.plant_name, inbox.scenario, inbox.tenant_id)}
        </p>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <SourcePill
            state={deriveSourceState(source, Boolean(inbox), inbox.provenance)}
            subject="approval queue"
          />
          <span className={`status-pill ${platformStatusClass(inbox.queue_status)}`}>
            <ShieldAlert size={15} />
            {formatNumber(pendingCount)} pending
          </span>
          <span className="font-mono text-xs text-muted">
            {formatTimestamp(inbox.as_of)}
          </span>
        </div>
      </div>

      <MetricStrip metrics={metrics} />

      {selectedApproval ? (
        <MasterDetail
          detail={
            <ApprovalDetail
              actor={
                identity.data?.actor_id
                  ? { actorId: identity.data.actor_id, scopes: identity.data.scopes }
                  : undefined
              }
              approval={selectedApproval}
              decision={decisions[selectedApproval.approval_id]}
              domainLabel={labelDomain(selectedApproval.domain)}
              error={errors[selectedApproval.approval_id]}
              onDecisionChange={handleDecisionChange}
              onErrorChange={setError}
              tenantId={inbox.tenant_id}
            />
          }
          list={
            <QueueList
              decisions={decisions}
              inbox={inbox}
              labelDomain={labelDomain}
              onSelect={(approvalId) => setUrlState({
                actionRunId: "",
                approvalId,
              })}
              selectedApproval={selectedApproval}
            />
          }
        />
      ) : (
        <EmptyPanel
          detail={strings.approvals.empty.detail}
          icon={Inbox}
          title={strings.approvals.empty.title}
        />
      )}

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
