"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { FilePlus2, FlaskConical } from "lucide-react";

import { PolicyConditionFields } from "@/components/policy-condition-fields";
import { PolicyEvaluationPanel } from "@/components/policy-evaluation-panel";
import { Field } from "@/components/ui/field";
import { InlineOperatorError } from "@/components/ui/inline-operator-error";
import { Input, Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { toAxisOperatorError, type AxisOperatorError } from "@/lib/axis-api";
import {
  buildPolicyConditionsPayload,
  buildPolicyCreatePayload,
  createPlatformPolicy,
  emptyPolicyDraft,
  platformPolicyAuthorScope,
  platformPolicyEffects,
  platformPolicyIdPattern,
  platformPolicyScopes,
  policyEffectLabel,
  policyScopeLabel,
  policyWriteOperatorError,
  validatePolicyDraft,
  type PlatformPolicyRecord,
  type PlatformPolicyScope,
  type PolicyConditionsFormState,
  type PolicyDraftFieldErrors,
  type PolicyDraftFormState,
} from "@/lib/platform-policies";
import { strings } from "@/lib/strings";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useConsole } from "@/providers/console-provider";

type SubmissionState =
  | { phase: "idle" }
  | { phase: "saving" }
  | { phase: "created"; record: PlatformPolicyRecord }
  | { phase: "failed"; error: AxisOperatorError };

export function PolicyCreateForm({ tenantId }: { tenantId: string }) {
  const { session } = useOidcConsoleSession();
  const { triggerRefresh } = useConsole();
  const [draft, setDraft] = useState<PolicyDraftFormState>(emptyPolicyDraft);
  const [fieldErrors, setFieldErrors] = useState<PolicyDraftFieldErrors>({});
  const [submission, setSubmission] = useState<SubmissionState>({ phase: "idle" });

  function updateDraft(patch: Partial<PolicyDraftFormState>) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  function updateConditions(conditions: PolicyConditionsFormState) {
    updateDraft({ conditions });
  }

  async function submitPolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const validationErrors = validatePolicyDraft(draft);
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
      const result = await createPlatformPolicy(buildPolicyCreatePayload(tenantId, draft), {
        session,
      });

      if (result.kind === "created") {
        setDraft(emptyPolicyDraft());
        setFieldErrors({});
        setSubmission({ phase: "created", record: result.record });
        triggerRefresh();
        return;
      }

      if (result.kind === "conflict") {
        setFieldErrors({ policyId: result.message });
        setSubmission({ phase: "failed", error: policyWriteOperatorError(result) });
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

      setSubmission({
        phase: "failed",
        error: policyWriteOperatorError(result),
      });
    } catch (caught) {
      setSubmission({
        phase: "failed",
        error: toAxisOperatorError(caught, "Policy authoring API is unavailable."),
      });
    }
  }

  const draftConditions = buildPolicyConditionsPayload(draft.conditions);
  const hasDraftConditions = Object.keys(draftConditions).length > 0;

  return (
    <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10">
        <div>
          <p className="eyebrow m-0">Author Policy</p>
          <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">New policy</h2>
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
            {strings.policyDetail.authorAccess.summary}{" "}
            {strings.policyDetail.authorAccess.detail}
          </p>
          <p className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">
            POST /platform/policies — {platformPolicyAuthorScope}
          </p>
        </div>
        <FilePlus2 size={18} />
      </div>

      <form
        aria-label="Platform policy authoring"
        className="grid grid-cols-1 items-end gap-3 border-t border-line/60 pt-4 dark:border-white/10 sm:grid-cols-[repeat(auto-fit,minmax(150px,1fr))]"
        noValidate
        onSubmit={(event) => void submitPolicy(event)}
      >
        <Field label="Policy ID">
          <Input
            aria-label="New policy id"
            onChange={(event) => updateDraft({ policyId: event.target.value })}
            pattern={platformPolicyIdPattern}
            placeholder="deny_critical_actions"
            required
            type="text"
            value={draft.policyId}
          />
        </Field>
        <Field label="Policy Version">
          <Input
            aria-label="New policy version"
            onChange={(event) => updateDraft({ policyVersion: event.target.value })}
            required
            type="text"
            value={draft.policyVersion}
          />
        </Field>
        <Field label="Scope">
          <Select
            aria-label="New policy scope"
            onChange={(event) =>
              updateDraft({ scope: event.target.value as PlatformPolicyScope })
            }
            value={draft.scope}
          >
            {platformPolicyScopes.map((scope) => (
              <option key={scope} value={scope}>
                {policyScopeLabel(scope)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Effect">
          <Select
            aria-label="New policy effect"
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
            aria-label="New policy display name"
            onChange={(event) => updateDraft({ displayName: event.target.value })}
            placeholder="Deny critical actions"
            required
            type="text"
            value={draft.displayName}
          />
        </Field>
        <Field className="col-span-full" label="Description">
          <Input
            aria-label="New policy description"
            onChange={(event) => updateDraft({ description: event.target.value })}
            placeholder="What this policy gates and why"
            required
            type="text"
            value={draft.description}
          />
        </Field>
        {fieldErrors.policyId ? (
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-danger break-words col-span-full" role="alert">
            {fieldErrors.policyId}
          </p>
        ) : null}
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
          labelPrefix="New policy"
          onChange={updateConditions}
        />
        <Field className="col-span-full" label="Notes (one per line)">
          <Textarea
            aria-label="New policy notes"
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
          <FilePlus2 size={15} />
          {submission.phase === "saving" ? "Authoring" : "Author policy"}
        </button>
      </form>

      {submission.phase === "failed" ? (
        <InlineOperatorError error={submission.error} prefix="Policy authoring failed" />
      ) : null}
      {submission.phase === "created" ? (
        <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words" role="status">
          Policy created as r{submission.record.revision_number} /{" "}
          {submission.record.policy_version}.{" "}
          <Link className="inline-flex min-h-6 items-center font-medium text-signal underline decoration-1 underline-offset-2" href={`/policies/${submission.record.policy_id}`}>
            Open {submission.record.policy_id}
          </Link>
        </p>
      ) : null}

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10">
        <div>
          <p className="eyebrow m-0">Preview Evaluation</p>
          <h3 className="font-display mx-0 mt-1 mb-0 text-lg text-ink">Advisory dry run for the drafted scope</h3>
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
            Runs POST /platform/policies/evaluate against the policies already persisted for
            this tenant, plus a client-side check of whether the drafted conditions would match
            the sample context. Advisory only: the draft is not evaluated by the API until it
            is authored.
          </p>
        </div>
        <FlaskConical size={18} />
      </div>
      <PolicyEvaluationPanel
        draftConditions={hasDraftConditions ? draftConditions : null}
        formLabel="Draft policy preview evaluation"
        scope={draft.scope}
        scopeLocked
        tenantId={tenantId}
      />
    </section>
  );
}
