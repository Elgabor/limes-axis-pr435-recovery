"use client";

import { useState, type FormEvent } from "react";
import { GitBranchPlus } from "lucide-react";

import { PolicyConditionFields } from "@/components/policy-condition-fields";
import { Field } from "@/components/ui/field";
import { InlineOperatorError } from "@/components/ui/inline-operator-error";
import { Input, Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { toAxisOperatorError, type AxisOperatorError } from "@/lib/axis-api";
import {
  buildPolicyRevisePayload,
  draftFromPolicyRecord,
  platformPolicyEffects,
  platformPolicyReviseScope,
  policyEffectLabel,
  policyScopeLabel,
  policyWriteOperatorError,
  revisePlatformPolicy,
  validatePolicyDraft,
  type PlatformPolicyRecord,
  type PolicyConditionsFormState,
  type PolicyDraftFieldErrors,
  type PolicyDraftFormState,
} from "@/lib/platform-policies";
import { safeRandomUuid } from "@/lib/ids";
import { strings } from "@/lib/strings";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useConsole } from "@/providers/console-provider";

type SubmissionState =
  | { phase: "idle" }
  | { phase: "saving" }
  | { phase: "created"; record: PlatformPolicyRecord }
  | { phase: "replayed"; record: PlatformPolicyRecord }
  | { phase: "conflict"; error: AxisOperatorError }
  | { phase: "failed"; error: AxisOperatorError };

export function PolicyReviseForm({
  tenantId,
  current,
}: {
  tenantId: string;
  current: PlatformPolicyRecord;
}) {
  const { session } = useOidcConsoleSession();
  const { triggerRefresh } = useConsole();
  const [draft, setDraft] = useState<PolicyDraftFormState>(() =>
    draftFromPolicyRecord(current),
  );
  const [idempotencyKey, setIdempotencyKey] = useState<string>(() => safeRandomUuid());
  const [fieldErrors, setFieldErrors] = useState<PolicyDraftFieldErrors>({});
  const [submission, setSubmission] = useState<SubmissionState>({ phase: "idle" });

  function updateDraft(patch: Partial<PolicyDraftFormState>) {
    setDraft((currentDraft) => ({ ...currentDraft, ...patch }));
  }

  function updateConditions(conditions: PolicyConditionsFormState) {
    updateDraft({ conditions });
  }

  async function submitRevision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const validationErrors = validatePolicyDraft(draft, { requirePolicyId: false });
    setFieldErrors(validationErrors);

    if (Object.keys(validationErrors).length > 0) {
      setSubmission({
        phase: "failed",
        error: toAxisOperatorError(
          null,
          "Fix the highlighted fields; nothing was sent to the API.",
        ),
      });
      return;
    }

    setSubmission({ phase: "saving" });

    try {
      const result = await revisePlatformPolicy(
        current.policy_id,
        buildPolicyRevisePayload(tenantId, current.policy_id, draft, idempotencyKey),
        { session },
      );

      if (result.kind === "created") {
        setFieldErrors({});
        setSubmission({ phase: "created", record: result.record });
        // A fresh key for the next revision; the applied one is spent.
        setIdempotencyKey(safeRandomUuid());
        triggerRefresh();
        return;
      }

      if (result.kind === "replayed") {
        setSubmission({ phase: "replayed", record: result.record });
        return;
      }

      if (result.kind === "conflict") {
        // The key was already used with a different payload; retrying with the
        // same key can never succeed, so rotate it and tell the operator.
        setIdempotencyKey(safeRandomUuid());
        setSubmission({
          phase: "conflict",
          error: policyWriteOperatorError(
            result,
            `${result.message} A fresh idempotency key was generated for the next attempt.`,
          ),
        });
        return;
      }

      if (result.kind === "invalid") {
        setFieldErrors(result.fieldErrors);
        setSubmission({ phase: "failed", error: policyWriteOperatorError(result) });
        return;
      }

      if (result.kind === "forbidden") {
        setSubmission({
          phase: "failed",
          error: policyWriteOperatorError(
            result,
            result.requiredPermission
              ? `${result.message} Required permission: ${result.requiredPermission}.`
              : result.message,
          ),
        });
        return;
      }

      setSubmission({ phase: "failed", error: policyWriteOperatorError(result) });
    } catch (caught) {
      setSubmission({
        phase: "failed",
        error: toAxisOperatorError(caught, "Policy revision API is unavailable."),
      });
    }
  }

  return (
    <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10">
        <div>
          <p className="eyebrow m-0">Revise Policy</p>
          <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">Append a revision to r{current.revision_number}</h2>
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
            {strings.policyDetail.reviseAccess.summary} Pre-filled from the current revision;
            scope stays {policyScopeLabel(current.scope)}.{" "}
            {strings.policyDetail.reviseAccess.detail}
          </p>
          <p className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">
            POST /platform/policies/{current.policy_id}/revisions — {platformPolicyReviseScope}
          </p>
          <p className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">Idempotency key {idempotencyKey}</p>
        </div>
        <GitBranchPlus size={18} />
      </div>

      <form
        aria-label="Platform policy revision"
        className="grid grid-cols-1 items-end gap-3 border-t border-line/60 pt-4 dark:border-white/10 sm:grid-cols-[repeat(auto-fit,minmax(150px,1fr))]"
        noValidate
        onSubmit={(event) => void submitRevision(event)}
      >
        <Field label="Policy Version">
          <Input
            aria-label="Revision policy version"
            onChange={(event) => updateDraft({ policyVersion: event.target.value })}
            required
            type="text"
            value={draft.policyVersion}
          />
        </Field>
        <Field label="Effect">
          <Select
            aria-label="Revision effect"
            onChange={(event) =>
              updateDraft({ effect: event.target.value as PolicyDraftFormState["effect"] })
            }
            value={draft.effect}
          >
            {platformPolicyEffects.map((effect) => (
              <option key={effect} value={effect}>
                {policyEffectLabel(effect)}
              </option>
            ))}
          </Select>
        </Field>
        <Field className="col-span-full" label="Display Name">
          <Input
            aria-label="Revision display name"
            onChange={(event) => updateDraft({ displayName: event.target.value })}
            required
            type="text"
            value={draft.displayName}
          />
        </Field>
        <Field className="col-span-full" label="Description">
          <Input
            aria-label="Revision description"
            onChange={(event) => updateDraft({ description: event.target.value })}
            required
            type="text"
            value={draft.description}
          />
        </Field>
        {fieldErrors.policyVersion ? (
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-danger break-words col-span-full" role="alert">
            {fieldErrors.policyVersion}
          </p>
        ) : null}
        {fieldErrors.displayName ? (
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-danger break-words col-span-full" role="alert">
            {fieldErrors.displayName}
          </p>
        ) : null}
        {fieldErrors.description ? (
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-danger break-words col-span-full" role="alert">
            {fieldErrors.description}
          </p>
        ) : null}
        <PolicyConditionFields
          conditions={draft.conditions}
          errors={fieldErrors}
          labelPrefix="Revision"
          onChange={updateConditions}
        />
        <Field className="col-span-full" label="Notes (one per line)">
          <Textarea
            aria-label="Revision notes"
            onChange={(event) => updateDraft({ notesText: event.target.value })}
            placeholder="Optional reviewer notes"
            rows={2}
            value={draft.notesText}
          />
        </Field>
        <button
          className="inline-flex items-center justify-center gap-2 rounded-full bg-navy px-4 py-2 text-sm font-medium text-white transition-all duration-300 select-none hover:bg-signal hover:shadow-[0_8px_24px_rgb(47_100_255/0.35)] disabled:cursor-not-allowed disabled:opacity-55 dark:bg-signal dark:hover:bg-white dark:hover:text-navy dark:hover:shadow-none"
          disabled={submission.phase === "saving"}
          type="submit"
        >
          <GitBranchPlus size={15} />
          {submission.phase === "saving" ? "Appending" : "Append revision"}
        </button>
      </form>

      {submission.phase === "created" ? (
        <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words" role="status">
          Revision created: r{submission.record.revision_number} /{" "}
          {submission.record.policy_version} is now the active revision.
        </p>
      ) : null}
      {submission.phase === "replayed" ? (
        <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words" role="status">
          Revision already applied: the API replayed r{submission.record.revision_number} /{" "}
          {submission.record.policy_version} for this idempotency key without writing a new
          revision.
        </p>
      ) : null}
      {submission.phase === "conflict" ? (
        <InlineOperatorError error={submission.error} prefix="Revision conflict" />
      ) : null}
      {submission.phase === "failed" ? (
        <InlineOperatorError error={submission.error} prefix="Policy revision failed" />
      ) : null}
    </section>
  );
}
