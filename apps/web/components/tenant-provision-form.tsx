"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Building2 } from "lucide-react";

import {
  buildTenantProvisionPayload,
  emptyTenantProvisionForm,
  platformTenantProvisionScope,
  provisionTenant,
  tenantIdPattern,
  tenantWriteOperatorError,
  validateTenantProvisionForm,
  type TenantProvisionFieldErrors,
  type TenantProvisionFormState,
  type TenantRecord,
} from "@/lib/platform-tenants";
import { toAxisOperatorError, type AxisOperatorError } from "@/lib/axis-api";
import { safeRandomUuid } from "@/lib/ids";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useConsole } from "@/providers/console-provider";
import { Field } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import { InlineOperatorError } from "@/components/ui/inline-operator-error";

type SubmissionState =
  | { phase: "idle" }
  | { phase: "saving" }
  | { phase: "created"; record: TenantRecord }
  | { phase: "replayed"; record: TenantRecord }
  | { phase: "conflict"; error: AxisOperatorError }
  | { phase: "failed"; error: AxisOperatorError };

export function TenantProvisionForm() {
  const { session } = useOidcConsoleSession();
  const { triggerRefresh } = useConsole();
  const [form, setForm] = useState<TenantProvisionFormState>(emptyTenantProvisionForm);
  const [idempotencyKey, setIdempotencyKey] = useState<string>(() => safeRandomUuid());
  const [fieldErrors, setFieldErrors] = useState<TenantProvisionFieldErrors>({});
  const [submission, setSubmission] = useState<SubmissionState>({ phase: "idle" });

  function updateForm(patch: Partial<TenantProvisionFormState>) {
    setForm((current) => ({ ...current, ...patch }));
  }

  async function submitProvision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const validationErrors = validateTenantProvisionForm(form);
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
      const result = await provisionTenant(
        buildTenantProvisionPayload(form, idempotencyKey),
        { session },
      );

      if (result.kind === "created") {
        setForm(emptyTenantProvisionForm());
        setFieldErrors({});
        setIdempotencyKey(safeRandomUuid());
        setSubmission({ phase: "created", record: result.record });
        triggerRefresh();
        return;
      }

      if (result.kind === "replayed") {
        // The same idempotency key + matching request replays the prior write
        // without creating a duplicate. Keep the form; surface the replay.
        setSubmission({ phase: "replayed", record: result.record });
        triggerRefresh();
        return;
      }

      if (result.kind === "conflict") {
        // A duplicate tenant, or the key was reused with a different request.
        // A fresh key can never resolve a duplicate tenant, but it clears a
        // stale-key replay conflict for the next attempt.
        setIdempotencyKey(safeRandomUuid());
        setFieldErrors(
          result.reason === "tenant_already_exists" ? { tenantId: result.message } : {},
        );
        setSubmission({
          phase: "conflict",
          error: tenantWriteOperatorError(
            result,
            `${result.message} A fresh idempotency key was generated for the next attempt.`,
          ),
        });
        return;
      }

      if (result.kind === "invalid") {
        setFieldErrors(result.fieldErrors as TenantProvisionFieldErrors);
        setSubmission({
          phase: "failed",
          error: tenantWriteOperatorError(result),
        });
        return;
      }

      if (result.kind === "forbidden") {
        setSubmission({
          phase: "failed",
          error: tenantWriteOperatorError(
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
        error: tenantWriteOperatorError(
          result,
          result.kind === "failed" ? result.message : "Tenant provisioning failed.",
        ),
      });
    } catch (caught) {
      setSubmission({
        phase: "failed",
        error: toAxisOperatorError(caught, "Tenant provisioning API is unavailable."),
      });
    }
  }

  return (
    <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10">
        <div>
          <p className="eyebrow m-0">Provision Tenant</p>
          <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">New tenant</h2>
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
            Creates an active tenant through POST /platform/tenants. The API enforces the{" "}
            {platformTenantProvisionScope} scope and records provisioning audit evidence.
          </p>
          <p className="mx-0 mt-1 mb-0 leading-snug text-muted break-words font-mono text-[13px]">Idempotency key {idempotencyKey}</p>
        </div>
        <Building2 size={18} />
      </div>

      <form
        aria-label="Tenant provisioning"
        className="grid grid-cols-1 items-end gap-3 border-t border-line/60 pt-4 dark:border-white/10 sm:grid-cols-[repeat(auto-fit,minmax(150px,1fr))]"
        noValidate
        onSubmit={(event) => void submitProvision(event)}
      >
        <Field label="Tenant ID">
          <Input
            aria-label="New tenant id"
            onChange={(event) => updateForm({ tenantId: event.target.value })}
            pattern={tenantIdPattern}
            placeholder="tenant_acme_manufacturing"
            required
            type="text"
            value={form.tenantId}
          />
        </Field>
        <Field label="Display Name">
          <Input
            aria-label="New tenant display name"
            onChange={(event) => updateForm({ displayName: event.target.value })}
            placeholder="Acme Manufacturing"
            required
            type="text"
            value={form.displayName}
          />
        </Field>
        <Field className="col-span-full" label="Description">
          <Input
            aria-label="New tenant description"
            onChange={(event) => updateForm({ description: event.target.value })}
            placeholder="What this tenant is for (optional)"
            type="text"
            value={form.description}
          />
        </Field>
        {fieldErrors.tenantId ? (
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-danger break-words col-span-full" role="alert">
            {fieldErrors.tenantId}
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

        <label className="col-span-full flex items-center gap-2.5">
          <Input
            aria-label="Bootstrap an admin actor"
            checked={form.bootstrapEnabled}
            onChange={(event) => updateForm({ bootstrapEnabled: event.target.checked })}
            type="checkbox"
          />
          <span className="eyebrow m-0">Bootstrap an admin actor for this tenant</span>
        </label>

        {form.bootstrapEnabled ? (
          <>
            <Field label="Bootstrap Admin Actor ID">
              <Input
                aria-label="Bootstrap admin actor id"
                onChange={(event) => updateForm({ bootstrapActorId: event.target.value })}
                placeholder="acme-admin-role"
                type="text"
                value={form.bootstrapActorId}
              />
            </Field>
            <Field label="Bootstrap Admin Display Name">
              <Input
                aria-label="Bootstrap admin display name"
                onChange={(event) => updateForm({ bootstrapDisplayName: event.target.value })}
                placeholder="Acme Administrator"
                type="text"
                value={form.bootstrapDisplayName}
              />
            </Field>
            <Field className="col-span-full" label="Bootstrap Admin Requested Scopes (comma or newline separated)">
              <Textarea
                aria-label="Bootstrap admin requested scopes"
                onChange={(event) => updateForm({ bootstrapScopesText: event.target.value })}
                placeholder="platform:tenant:read"
                rows={2}
                value={form.bootstrapScopesText}
              />
              <span className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                Recorded as audit evidence only. Scope grants stay IdP-owned; the API never
                grants these live.
              </span>
            </Field>
            {fieldErrors.bootstrapActorId ? (
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-danger break-words col-span-full" role="alert">
                {fieldErrors.bootstrapActorId}
              </p>
            ) : null}
            {fieldErrors.bootstrapDisplayName ? (
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-danger break-words col-span-full" role="alert">
                {fieldErrors.bootstrapDisplayName}
              </p>
            ) : null}
          </>
        ) : null}

        <Field className="col-span-full" label="Notes (one per line)">
          <Textarea
            aria-label="New tenant notes"
            onChange={(event) => updateForm({ notesText: event.target.value })}
            placeholder="Optional provisioning notes"
            rows={2}
            value={form.notesText}
          />
        </Field>
        <button className="inline-flex items-center justify-center gap-2 rounded-full bg-navy px-4 py-2 text-sm font-medium text-white transition-all duration-300 select-none hover:bg-signal hover:shadow-[0_8px_24px_rgb(47_100_255/0.35)] disabled:cursor-not-allowed disabled:opacity-55 dark:bg-signal dark:hover:bg-white dark:hover:text-navy dark:hover:shadow-none" disabled={submission.phase === "saving"} type="submit">
          <Building2 size={15} />
          {submission.phase === "saving" ? "Provisioning" : "Provision tenant"}
        </button>
      </form>

      {submission.phase === "failed" ? (
        <InlineOperatorError error={submission.error} prefix="Tenant provisioning failed" />
      ) : null}
      {submission.phase === "conflict" ? (
        <InlineOperatorError error={submission.error} prefix="Tenant provisioning conflict" />
      ) : null}
      {submission.phase === "created" ? (
        <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words" role="status">
          Tenant provisioned.{" "}
          <Link className="inline-flex min-h-6 items-center font-medium text-signal underline decoration-1 underline-offset-2" href={`/tenants/${submission.record.tenant_id}`}>
            Open {submission.record.tenant_id}
          </Link>
        </p>
      ) : null}
      {submission.phase === "replayed" ? (
        <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words" role="status">
          Idempotent replay: the API returned the existing tenant for this key without creating a
          duplicate.{" "}
          <Link className="inline-flex min-h-6 items-center font-medium text-signal underline decoration-1 underline-offset-2" href={`/tenants/${submission.record.tenant_id}`}>
            Open {submission.record.tenant_id}
          </Link>
        </p>
      ) : null}
    </section>
  );
}
