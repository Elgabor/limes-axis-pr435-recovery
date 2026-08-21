"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { CheckCircle2, CircleX, MessageSquare } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Eyebrow } from "@/components/ui/eyebrow";
import { ErrorPanel } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import {
  axisFetchParsedJson,
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import {
  approvalDecisionActorId,
  approvalDecisionLabel,
  buildApprovalDecisionPayload,
  type ApprovalDecision,
  type ApprovalDecisionOption,
  type ApprovalDecisionPersistenceResult,
  type ApprovalInboxItem,
} from "@/lib/approval-demo";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/strings";
import { parseApprovalDecisionPersistenceResult } from "@/lib/runtime-contracts/approvals";
import { buildTenantScopedPath, DEMO_TENANT_ID, OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useTenantVocabulary } from "@/providers/tenant-vocabulary-provider";

/*
 * The decision block of the approval flow: option buttons with their
 * consequence always visible, a confirm dialog that restates the consequence
 * and takes an optional rationale, and the persisted result with a deep link
 * to the created audit event. Exported standalone so the overview's
 * needs-attention strip can reuse the exact same confirm flow.
 */

const DECISION_NOTE_MAX_LENGTH = 600;

/** Local decision lifecycle for one approval, keyed by the parent. */
export type ApprovalDecisionRecord = {
  decision: ApprovalDecision;
  label: string;
  decidedAt: string;
  storage: "persisting" | "persisted";
  actorId: string;
  auditEventId?: string;
  workflowSignalStatus?: string;
  permissionDetail?: string;
  workflowSignalDetail?: string;
};

export interface ApprovalDecisionCardProps {
  approval: ApprovalInboxItem;
  /** Current decision lifecycle for this approval; undefined = pending. */
  decision?: ApprovalDecisionRecord;
  /** Last persistence error for this approval. */
  error?: AxisOperatorError;
  tenantId?: string;
  actor?: { actorId: string; scopes: string[] };
  onDecisionChange: (approvalId: string, record: ApprovalDecisionRecord | null) => void;
  onErrorChange?: (approvalId: string, error: AxisOperatorError | null) => void;
}

/**
 * Per-approval decision/error maps for hosts rendering one or more
 * `ApprovalDecisionCard`s (approval inbox, overview needs-attention strip).
 */
export function useApprovalDecisionState() {
  const [decisions, setDecisions] = useState<Record<string, ApprovalDecisionRecord>>({});
  const [errors, setErrors] = useState<Record<string, AxisOperatorError>>({});

  const setDecision = useCallback(
    (approvalId: string, record: ApprovalDecisionRecord | null) => {
      setDecisions((current) => {
        if (record === null) {
          const next = { ...current };
          delete next[approvalId];
          return next;
        }
        return { ...current, [approvalId]: record };
      });
    },
    [],
  );

  const setError = useCallback((approvalId: string, error: AxisOperatorError | null) => {
    setErrors((current) => {
      if (error === null) {
        const next = { ...current };
        delete next[approvalId];
        return next;
      }
      return { ...current, [approvalId]: error };
    });
  }, []);

  return { decisions, errors, setDecision, setError };
}

function DecisionIcon({ decision }: { decision: ApprovalDecision }) {
  if (decision === "approve") {
    return <CheckCircle2 aria-hidden="true" size={16} />;
  }

  return decision === "reject" ? (
    <CircleX aria-hidden="true" size={16} />
  ) : (
    <MessageSquare aria-hidden="true" size={16} />
  );
}

const optionToneClasses: Record<ApprovalDecision, string> = {
  approve:
    "border-signal/45 hover:border-signal hover:bg-tint-50 dark:hover:bg-signal/10 [&_.decision-option-label]:text-signal",
  reject:
    "border-danger/35 hover:border-danger hover:bg-danger/5 dark:hover:bg-danger/10 [&_.decision-option-label]:text-danger",
  request_changes:
    "border-line hover:border-signal/50 hover:bg-tint-50 dark:border-white/15 dark:hover:bg-white/5 [&_.decision-option-label]:text-ink",
};

export function ApprovalDecisionCard({
  approval,
  actor,
  decision,
  error,
  onDecisionChange,
  onErrorChange,
  tenantId = DEMO_TENANT_ID,
}: ApprovalDecisionCardProps) {
  const [pendingOption, setPendingOption] = useState<ApprovalDecisionOption | null>(null);
  const [note, setNote] = useState("");
  const { session } = useOidcConsoleSession();
  const { push } = useToast();
  const { labelDomain } = useTenantVocabulary();
  const copy = strings.approvals.decision;

  function openConfirm(option: ApprovalDecisionOption) {
    setNote("");
    setPendingOption(option);
  }

  async function confirmDecision() {
    const option = pendingOption;
    if (!option) {
      return;
    }
    setPendingOption(null);

    const approvalId = approval.approval_id;
    const decidedAt = new Intl.DateTimeFormat("en", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date());

    onDecisionChange(approvalId, {
      decision: option.decision,
      label: option.label,
      decidedAt,
      storage: "persisting",
      actorId: approvalDecisionActorId(approval),
    });
    onErrorChange?.(approvalId, null);

    try {
      const result = await axisFetchParsedJson<ApprovalDecisionPersistenceResult>(
        buildTenantScopedPath(
          `${OPERATIONS_API_PREFIX}/approvals/${approvalId}/decision`,
          tenantId,
        ),
        parseApprovalDecisionPersistenceResult,
        {
          session,
          method: "POST",
          body: buildApprovalDecisionPayload(approval, option.decision, note, actor),
        },
      );
      onDecisionChange(approvalId, {
        decision: result.decision,
        label: option.label,
        decidedAt,
        storage: "persisted",
        actorId: result.actor_id,
        auditEventId: result.audit_event_id,
        workflowSignalStatus: result.workflow_signal_status,
        permissionDetail: `Permission ${result.permission_decision.reason}.`,
        workflowSignalDetail: `${result.workflow_signal.adapter} / ${result.workflow_signal.signal_name}`,
      });
      push({
        title: copy.toastTitle,
        detail: `${option.label} — ${approval.action}`,
        tone: option.decision === "reject" ? "neutral" : "positive",
        ...(result.audit_event_id
          ? {
              href: `/audit?event_id=${encodeURIComponent(result.audit_event_id)}`,
              hrefLabel: copy.auditLink,
            }
          : {}),
      });
    } catch (caught) {
      onDecisionChange(approvalId, null);
      onErrorChange?.(
        approvalId,
        toAxisOperatorError(
          caught,
          "Approval decision API persistence is unavailable.",
        ),
      );
    } finally {
      setNote("");
    }
  }

  return (
    <section
      aria-label="Decision"
      className="grid content-start gap-3 rounded-2xl border border-signal/25 bg-tint-50 p-4 dark:border-signal/30 dark:bg-signal/8"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Eyebrow>{copy.eyebrow}</Eyebrow>
        {decision ? (
          <span className="text-xs text-muted">
            {decision.storage === "persisted" ? copy.persisted : copy.persisting}
          </span>
        ) : null}
      </div>

      {decision ? (
        <div className="grid gap-1">
          <p className="font-display m-0 text-lg text-ink">
            {approvalDecisionLabel(decision.decision)}
          </p>
          <p className="m-0 text-xs text-muted">
            {decision.label} / {decision.decidedAt} / {decision.actorId}
          </p>
          {decision.permissionDetail ? (
            <p className="m-0 text-xs text-muted">{decision.permissionDetail}</p>
          ) : null}
          {decision.storage === "persisted" && decision.auditEventId ? (
            <Link
              className="mt-1 inline-flex w-fit items-center text-sm font-medium text-signal hover:underline"
              href={`/audit?event_id=${encodeURIComponent(decision.auditEventId)}`}
            >
              {copy.auditLink}
            </Link>
          ) : null}
        </div>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {approval.decision_options.map((option) => (
            <button
              className={cn(
                "grid min-w-0 cursor-pointer content-start gap-1 rounded-xl border bg-surface px-3.5 py-3 text-left",
                "transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-55 dark:bg-transparent",
                optionToneClasses[option.decision],
              )}
              key={option.decision}
              onClick={() => openConfirm(option)}
              type="button"
            >
              <span className="decision-option-label flex items-center gap-1.5 text-sm font-medium">
                <DecisionIcon decision={option.decision} />
                {option.label}
              </span>
              <span className="text-xs leading-snug text-muted">{option.consequence}</span>
            </button>
          ))}
        </div>
      )}

      {error ? (
        <ErrorPanel
          detail={error.message}
          reference={error.requestId ?? undefined}
          title="Decision persistence error"
        />
      ) : null}

      <Dialog
        open={pendingOption !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingOption(null);
          }
        }}
      >
        {pendingOption ? (
          <DialogContent>
            <DialogHeader>
              <DialogTitle>
                {copy.confirmTitle}: {pendingOption.label}
              </DialogTitle>
              <DialogDescription>{pendingOption.consequence}</DialogDescription>
            </DialogHeader>
            <p className="m-0 text-sm text-muted">
              {approval.action} <span aria-hidden="true">·</span>{" "}
              {labelDomain(approval.domain)}
            </p>
            <label className="grid gap-1.5">
              <span className="text-xs font-medium text-muted">{copy.rationaleLabel}</span>
              <textarea
                className="min-h-20 w-full resize-y rounded-xl border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-signal/60 dark:border-white/15 dark:bg-transparent"
                maxLength={DECISION_NOTE_MAX_LENGTH}
                onChange={(event) => setNote(event.target.value)}
                placeholder={copy.rationalePlaceholder}
                value={note}
              />
            </label>
            <DialogFooter>
              <Button
                className="px-4 py-2 text-sm"
                variant="secondary"
                onClick={() => setPendingOption(null)}
              >
                {copy.cancel}
              </Button>
              <Button
                className="px-4 py-2 text-sm"
                variant={pendingOption.decision === "reject" ? "destructive" : "primary"}
                onClick={() => void confirmDecision()}
              >
                {copy.confirm}
              </Button>
            </DialogFooter>
          </DialogContent>
        ) : null}
      </Dialog>
    </section>
  );
}
