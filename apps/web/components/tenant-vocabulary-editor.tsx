"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { BookOpenText, Plus, Trash2 } from "lucide-react";

import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  buildPlatformTenantVocabularyPath,
  buildTenantVocabularyUpdatePayload,
  platformTenantConfigureScope,
  tenantVocabularyDomainLimit,
  tenantVocabularyLabelMaxLength,
  tenantWriteOperatorError,
  updateTenantVocabulary,
  type TenantVocabulary,
  type TenantVocabularySet,
} from "@/lib/platform-tenants";
import { toAxisOperatorError, type AxisOperatorError } from "@/lib/axis-api";
import { strings } from "@/lib/strings";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useTenantVocabulary } from "@/providers/tenant-vocabulary-provider";
import { InlineOperatorError } from "@/components/ui/inline-operator-error";

type DomainLabelRow = {
  id: number;
  key: string;
  label: string;
};

type VocabularyFormState = {
  siteSingular: string;
  sitePlural: string;
  workspaceLabel: string;
  domainRows: DomainLabelRow[];
};

type VocabularyFieldErrors = Partial<
  Record<"siteSingular" | "sitePlural" | "workspaceLabel" | "domainLabels", string>
>;

type SaveState =
  | { phase: "idle" }
  | { phase: "confirming" }
  | { phase: "saving" }
  | { phase: "done" }
  | { phase: "failed"; error: AxisOperatorError };

let nextDomainRowId = 0;

function formFromVocabularySet(record: TenantVocabularySet): VocabularyFormState {
  return {
    siteSingular: record.vocabulary.site_singular,
    sitePlural: record.vocabulary.site_plural,
    workspaceLabel: record.vocabulary.workspace_label,
    domainRows: Object.entries(record.vocabulary.domain_labels)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, label]) => ({ id: nextDomainRowId++, key, label })),
  };
}

function formsEqual(left: VocabularyFormState, right: VocabularyFormState): boolean {
  return (
    left.siteSingular === right.siteSingular
    && left.sitePlural === right.sitePlural
    && left.workspaceLabel === right.workspaceLabel
    && left.domainRows.length === right.domainRows.length
    && left.domainRows.every((row, index) => {
      const other = right.domainRows[index];
      return other?.key === row.key && other.label === row.label;
    })
  );
}

function validateForm(form: VocabularyFormState): VocabularyFieldErrors {
  const copy = strings.tenantVocabulary.validation;
  const errors: VocabularyFieldErrors = {};

  for (const [field, value] of [
    ["siteSingular", form.siteSingular],
    ["sitePlural", form.sitePlural],
    ["workspaceLabel", form.workspaceLabel],
  ] as const) {
    if (value.length > tenantVocabularyLabelMaxLength) {
      errors[field] = copy.labelTooLong(tenantVocabularyLabelMaxLength);
    }
  }

  if (form.domainRows.length > tenantVocabularyDomainLimit) {
    errors.domainLabels = copy.domainLimit(tenantVocabularyDomainLimit);
    return errors;
  }

  const domainKeys = new Set<string>();
  for (const row of form.domainRows) {
    const key = row.key.trim();
    if (!key) {
      errors.domainLabels = copy.missingDomainKey;
      break;
    }
    if (domainKeys.has(key)) {
      errors.domainLabels = copy.duplicateDomainKey;
      break;
    }
    domainKeys.add(key);
  }

  return errors;
}

function vocabularyFromForm(form: VocabularyFormState): TenantVocabulary {
  return {
    site_singular: form.siteSingular.trim(),
    site_plural: form.sitePlural.trim(),
    workspace_label: form.workspaceLabel.trim(),
    domain_labels: Object.fromEntries(
      form.domainRows.map((row) => [row.key.trim(), row.label.trim()]),
    ),
  };
}

function sourceLabel(source: ReturnType<typeof useTenantVocabulary>["source"]): string {
  return strings.tenantVocabulary.source[source];
}

export function TenantVocabularyEditor({ tenantId }: { tenantId: string }) {
  const { session } = useOidcConsoleSession();
  const {
    tenantId: loadedTenantId,
    vocabularySet,
    source,
    replaceVocabulary,
  } = useTenantVocabulary();
  const [form, setForm] = useState<VocabularyFormState | null>(null);
  const [fieldErrors, setFieldErrors] = useState<VocabularyFieldErrors>({});
  const [save, setSave] = useState<SaveState>({ phase: "idle" });
  const formBaselineRef = useRef<VocabularyFormState | null>(null);
  const formRef = useRef(form);
  const saveRef = useRef(save);

  useEffect(() => {
    formRef.current = form;
    saveRef.current = save;
  }, [form, save]);

  useEffect(() => {
    if (!vocabularySet || loadedTenantId !== tenantId) {
      return;
    }

    if (
      formRef.current
      && formBaselineRef.current
      && (
        !formsEqual(formRef.current, formBaselineRef.current)
        || saveRef.current.phase === "saving"
      )
    ) {
      return;
    }

    const nextForm = formFromVocabularySet(vocabularySet);
    const matchesSavedBaseline = Boolean(
      formBaselineRef.current
      && formsEqual(nextForm, formBaselineRef.current),
    );
    formBaselineRef.current = nextForm;
    setForm(nextForm);
    setSave((current) => (
      current.phase === "idle"
      || (current.phase === "done" && matchesSavedBaseline)
        ? current
        : { phase: "idle" }
    ));
  }, [loadedTenantId, tenantId, vocabularySet]);

  function updateField(
    field: "siteSingular" | "sitePlural" | "workspaceLabel",
    value: string,
  ) {
    setForm((current) => (current ? { ...current, [field]: value } : current));
    if (save.phase === "confirming" || save.phase === "done") {
      setSave({ phase: "idle" });
    }
  }

  function updateDomainRow(id: number, field: "key" | "label", value: string) {
    setForm((current) => (
      current
        ? {
            ...current,
            domainRows: current.domainRows.map((row) => (
              row.id === id ? { ...row, [field]: value } : row
            )),
          }
        : current
    ));
    setSave((current) => (
      current.phase === "confirming" || current.phase === "done"
        ? { phase: "idle" }
        : current
    ));
  }

  function addDomainRow() {
    setForm((current) => (
      current
        ? {
            ...current,
            domainRows: [
              ...current.domainRows,
              { id: nextDomainRowId++, key: "", label: "" },
            ],
          }
        : current
    ));
    setSave({ phase: "idle" });
  }

  function removeDomainRow(id: number) {
    setForm((current) => (
      current
        ? {
            ...current,
            domainRows: current.domainRows.filter((row) => row.id !== id),
          }
        : current
    ));
    setSave({ phase: "idle" });
  }

  function requestConfirmation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form) {
      return;
    }

    const errors = validateForm(form);
    setFieldErrors(errors);

    if (Object.keys(errors).length > 0) {
      setSave({
        phase: "failed",
        error: toAxisOperatorError(null, strings.tenantVocabulary.validation.fix),
      });
      return;
    }

    setSave({ phase: "confirming" });
  }

  async function confirmSave() {
    if (!form) {
      return;
    }

    setSave({ phase: "saving" });

    try {
      const result = await updateTenantVocabulary(
        tenantId,
        buildTenantVocabularyUpdatePayload(vocabularyFromForm(form)),
        { session },
      );

      if (result.kind === "updated") {
        setFieldErrors({});
        const savedForm = formFromVocabularySet(result.record);
        formBaselineRef.current = savedForm;
        setForm(savedForm);
        replaceVocabulary(result.record);
        setSave({ phase: "done" });
        return;
      }

      if (result.kind === "forbidden") {
        setSave({
          phase: "failed",
          error: tenantWriteOperatorError(
            result,
            result.requiredPermission
              ? strings.tenantVocabulary.errors.requiredPermission(
                  result.message,
                  result.requiredPermission,
                )
              : result.message,
          ),
        });
        return;
      }

      if (result.kind === "invalid") {
        setFieldErrors(result.fieldErrors);
        setSave({ phase: "failed", error: tenantWriteOperatorError(result) });
        return;
      }

      setSave({
        phase: "failed",
        error: tenantWriteOperatorError(
          result,
          result.kind === "failed"
            ? result.message
            : result.kind === "notFound"
              ? result.message
              : strings.tenantVocabulary.errors.generic,
        ),
      });
    } catch (caught) {
      setSave({
        phase: "failed",
        error: toAxisOperatorError(caught, strings.tenantVocabulary.errors.unavailable),
      });
    }
  }

  const copy = strings.tenantVocabulary;
  const recordReady = vocabularySet && loadedTenantId === tenantId && form;

  return (
    <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10">
        <div>
          <p className="eyebrow m-0">{copy.eyebrow}</p>
          <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">{copy.title}</h2>
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
            {copy.description}
          </p>
        </div>
        <BookOpenText size={18} />
      </div>

      {!recordReady ? (
        <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words" role="status">
          {sourceLabel(loadedTenantId === tenantId ? source : "loading")}
        </p>
      ) : (
        <>
          <div className="mb-4 flex min-w-0 flex-wrap items-start gap-2">
            <span
              className={`status-pill ${
                vocabularySet.configured ? "signal-ready" : "status-checking"
              }`}
            >
              {vocabularySet.configured ? copy.mode.configured : copy.mode.defaults}
            </span>
            <p className="m-0 text-sm leading-snug text-muted">
              {vocabularySet.configured
                ? copy.mode.configuredDetail
                : copy.mode.defaultsDetail}
            </p>
          </div>

          <form
            aria-label={copy.title}
            className="grid grid-cols-1 items-end gap-4 border-t border-line/60 pt-4 dark:border-white/10 sm:grid-cols-3"
            noValidate
            onSubmit={requestConfirmation}
          >
            <Field label={copy.fields.siteSingular}>
              <Input
                aria-invalid={Boolean(fieldErrors.siteSingular)}
                maxLength={tenantVocabularyLabelMaxLength}
                onChange={(event) => updateField("siteSingular", event.target.value)}
                value={form.siteSingular}
              />
              <span className="m-0 text-xs leading-snug text-muted">
                {copy.fields.siteSingularDetail}
              </span>
              {fieldErrors.siteSingular ? (
                <span className="m-0 text-sm leading-snug text-danger" role="alert">
                  {fieldErrors.siteSingular}
                </span>
              ) : null}
            </Field>
            <Field label={copy.fields.sitePlural}>
              <Input
                aria-invalid={Boolean(fieldErrors.sitePlural)}
                maxLength={tenantVocabularyLabelMaxLength}
                onChange={(event) => updateField("sitePlural", event.target.value)}
                value={form.sitePlural}
              />
              <span className="m-0 text-xs leading-snug text-muted">
                {copy.fields.sitePluralDetail}
              </span>
              {fieldErrors.sitePlural ? (
                <span className="m-0 text-sm leading-snug text-danger" role="alert">
                  {fieldErrors.sitePlural}
                </span>
              ) : null}
            </Field>
            <Field label={copy.fields.workspaceLabel}>
              <Input
                aria-invalid={Boolean(fieldErrors.workspaceLabel)}
                maxLength={tenantVocabularyLabelMaxLength}
                onChange={(event) => updateField("workspaceLabel", event.target.value)}
                value={form.workspaceLabel}
              />
              <span className="m-0 text-xs leading-snug text-muted">
                {copy.fields.workspaceLabelDetail}
              </span>
              {fieldErrors.workspaceLabel ? (
                <span className="m-0 text-sm leading-snug text-danger" role="alert">
                  {fieldErrors.workspaceLabel}
                </span>
              ) : null}
            </Field>

            <div className="col-span-full grid min-w-0 gap-3 border-t border-line/60 pt-4 dark:border-white/10">
              <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="m-0 text-sm font-medium text-ink">{copy.fields.domainLabels}</p>
                  <p className="mx-0 mt-1 mb-0 text-xs leading-snug text-muted">
                    {copy.fields.domainLabelsDetail}
                  </p>
                </div>
                <button
                  className="inline-flex items-center justify-center gap-2 rounded-full border border-mist bg-surface px-4 py-2 text-sm font-medium text-ink transition-all duration-300 select-none hover:border-signal/50 hover:text-signal disabled:cursor-not-allowed disabled:opacity-55 dark:border-white/20 dark:hover:border-signal/60"
                  disabled={form.domainRows.length >= tenantVocabularyDomainLimit}
                  onClick={addDomainRow}
                  type="button"
                >
                  <Plus size={15} />
                  {copy.actions.addDomain}
                </button>
              </div>

              {form.domainRows.map((row) => (
                <div
                  className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]"
                  key={row.id}
                >
                  <Field label={copy.fields.domainKey}>
                    <Input
                      aria-invalid={Boolean(fieldErrors.domainLabels)}
                      onChange={(event) => updateDomainRow(row.id, "key", event.target.value)}
                      placeholder={copy.fields.domainKeyPlaceholder}
                      value={row.key}
                    />
                  </Field>
                  <Field label={copy.fields.domainLabel}>
                    <Input
                      aria-invalid={Boolean(fieldErrors.domainLabels)}
                      onChange={(event) => updateDomainRow(row.id, "label", event.target.value)}
                      placeholder={copy.fields.domainLabelPlaceholder}
                      value={row.label}
                    />
                  </Field>
                  <button
                    aria-label={`${copy.actions.removeDomain}: ${row.key || copy.fields.domainKey}`}
                    className="inline-flex h-9 w-9 items-center justify-center self-end rounded-full text-muted transition-colors hover:bg-danger/8 hover:text-danger"
                    onClick={() => removeDomainRow(row.id)}
                    type="button"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              ))}

              {fieldErrors.domainLabels ? (
                <p className="m-0 text-sm leading-snug text-danger" role="alert">
                  {fieldErrors.domainLabels}
                </p>
              ) : null}
            </div>

            {save.phase === "confirming" ? (
              <div className="col-span-full grid min-w-0 gap-2.5">
                <p className="m-0 text-sm leading-snug text-muted" role="status">
                  {copy.confirmation}
                </p>
                <div className="grid w-full min-w-0 gap-2.5 sm:flex sm:w-auto sm:flex-wrap sm:items-end sm:justify-end">
                  <button
                    className="inline-flex items-center justify-center gap-2 rounded-full border border-mist bg-surface px-4 py-2 text-sm font-medium text-ink transition-all duration-300 select-none hover:border-signal/50 hover:text-signal disabled:cursor-not-allowed disabled:opacity-55 dark:border-white/20 dark:hover:border-signal/60"
                    onClick={() => void confirmSave()}
                    type="button"
                  >
                    <BookOpenText size={15} />
                    {copy.actions.confirm}
                  </button>
                  <button
                    className="inline-flex items-center justify-center rounded-full px-3 py-2 text-sm font-medium text-ink transition-all duration-300 select-none hover:text-signal"
                    onClick={() => setSave({ phase: "idle" })}
                    type="button"
                  >
                    {copy.actions.cancel}
                  </button>
                </div>
              </div>
            ) : (
              <button
                className="col-span-full inline-flex items-center justify-center gap-2 rounded-full bg-navy px-4 py-2 text-sm font-medium text-white transition-all duration-300 select-none hover:bg-signal disabled:cursor-not-allowed disabled:opacity-55 dark:bg-signal dark:hover:bg-white dark:hover:text-navy sm:justify-self-end"
                disabled={save.phase === "saving"}
                type="submit"
              >
                <BookOpenText size={15} />
                {save.phase === "saving" ? copy.actions.saving : copy.actions.review}
              </button>
            )}
          </form>
        </>
      )}

      {save.phase === "failed" ? (
        <InlineOperatorError error={save.error} prefix={copy.errors.prefix.replace(/:$/, "")} />
      ) : null}
      {save.phase === "done" ? (
        <p className="mx-0 mt-3 mb-0 text-sm leading-snug text-muted" role="status">
          {copy.success}
        </p>
      ) : null}

      <details className="mt-4 border-t border-line/60 pt-3 text-sm text-muted dark:border-white/10">
        <summary className="cursor-pointer font-medium text-ink">Vocabulary technical details</summary>
        <div className="mt-3 grid min-w-0 grid-cols-1 gap-2.5 [&>p]:min-w-0 [&>p]:[overflow-wrap:anywhere]">
          <p className="m-0 leading-snug break-words">{copy.requiredScope(platformTenantConfigureScope)}</p>
          <p aria-label={copy.endpoint} className="m-0 font-mono text-[13px] leading-snug break-words">{buildPlatformTenantVocabularyPath(tenantId)}</p>
          {vocabularySet?.vocabulary_notes?.map((note) => (
            <p className="m-0 leading-snug break-words" key={note}>{note}</p>
          ))}
        </div>
      </details>
    </section>
  );
}
