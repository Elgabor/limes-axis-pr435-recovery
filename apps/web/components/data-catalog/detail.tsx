"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DetailGrid, KeyValueRow } from "@/components/ui/detail-grid";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Field } from "@/components/ui/field";
import { InlineOperatorError } from "@/components/ui/inline-operator-error";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/ui/states";
import {
  AxisApiError,
  axisFetchParsedJson,
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import type {
  DataAsset,
  DataAssetClassification,
  DataAssetResourceObservation,
} from "@/lib/data-assets";
import { formatDateTime } from "@/lib/format";
import { safeRandomUuid } from "@/lib/ids";
import { parseDataAssetContractView, parseDataAssetStewardshipView } from "@/lib/runtime-contracts/data-assets";
import { strings } from "@/lib/strings";
import {
  buildDataAssetStewardshipPath,
  DATA_ASSET_STEWARDSHIP_ENDPOINTS,
  useDataAssetStewardship,
} from "@/lib/use-data-asset-stewardship";
import {
  buildDataAssetContractPath,
  useDataAssetContract,
  useDataAssetContractEvaluation,
} from "@/lib/use-data-asset-contract";
import {
  DATA_ASSET_RESOURCES_ENDPOINTS,
  useDataAssetResources,
} from "@/lib/use-data-asset-resources";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";

/** Data asset detail pane: metadata-only by contract, mirroring the API. */
export function DataAssetDetail({ asset }: { asset: DataAsset }) {
  const copy = strings.dataCatalog.detail;

  return (
    <Card className="grid content-start gap-4">
      <div className="grid gap-1">
        <Eyebrow>{asset.asset_id}</Eyebrow>
        <h2 className="font-display m-0 text-xl text-ink">{asset.display_name}</h2>
      </div>
      <DetailGrid>
        <KeyValueRow label={copy.assetId} mono>
          {asset.asset_id}
        </KeyValueRow>
        <KeyValueRow label={copy.connector} mono>
          {asset.connector_id}
        </KeyValueRow>
        <KeyValueRow label={copy.kind}>{asset.kind}</KeyValueRow>
        <KeyValueRow label={copy.evidence}>
          {strings.dataCatalog.evidence[asset.evidence]}
        </KeyValueRow>
        <KeyValueRow label={copy.governance}>
          {strings.dataCatalog.governance[asset.governance]}
        </KeyValueRow>
        <KeyValueRow label={copy.sourceType}>{asset.source_type}</KeyValueRow>
        <KeyValueRow label={copy.runtimeBoundary} mono>
          {asset.runtime_boundary}
        </KeyValueRow>
        <KeyValueRow label={copy.egressPolicy} mono>
          {asset.egress_policy}
        </KeyValueRow>
        <KeyValueRow label={copy.payloadPolicy} mono>
          {asset.payload_policy}
        </KeyValueRow>
        <KeyValueRow label={copy.syncModes}>
          {asset.sync_modes.length > 0 ? asset.sync_modes.join(", ") : "—"}
        </KeyValueRow>
        <KeyValueRow label={copy.lastSync}>
          {asset.last_successful_sync
            ? `${formatDateTime(asset.last_successful_sync.completed_at)} · ${
                asset.last_successful_sync.run_id
              }`
            : "—"}
        </KeyValueRow>
        <KeyValueRow label={copy.manifestRevision}>
          {asset.manifest_revision ?? "—"}
        </KeyValueRow>
        <KeyValueRow label={copy.registryOrigin}>{asset.registry_origin}</KeyValueRow>
      </DetailGrid>
      <div className="grid gap-2">
        <h3 className="m-0 text-sm font-medium text-ink">{copy.schemaTitle}</h3>
        {asset.schema_fields.length === 0 ? (
          <p className="m-0 text-xs text-muted">{copy.schemaEmpty}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-xs">
              <thead>
                <tr className="border-b border-line text-muted">
                  <th className="py-1.5 pr-3 font-medium" scope="col">
                    {copy.columns.source}
                  </th>
                  <th className="py-1.5 pr-3 font-medium" scope="col">
                    {copy.columns.target}
                  </th>
                  <th className="py-1.5 pr-3 font-medium" scope="col">
                    {copy.columns.ontology}
                  </th>
                  <th className="py-1.5 pr-3 font-medium" scope="col">
                    {copy.columns.type}
                  </th>
                  <th className="py-1.5 font-medium" scope="col">
                    {copy.columns.required}
                  </th>
                </tr>
              </thead>
              <tbody>
                {asset.schema_fields.map((field) => (
                  <tr className="border-b border-line/60" key={field.source_column}>
                    <td className="py-1.5 pr-3 font-mono text-ink">{field.source_column}</td>
                    <td className="py-1.5 pr-3 text-muted">{field.target_field}</td>
                    <td className="py-1.5 pr-3 text-muted">{field.ontology_target}</td>
                    <td className="py-1.5 pr-3 text-muted">{field.data_type}</td>
                    <td className="py-1.5 text-muted">{field.required ? "✓" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {asset.ontology_targets.length > 0 ? (
        <div className="grid gap-2">
          <h3 className="m-0 text-sm font-medium text-ink">{copy.ontologyTargets}</h3>
          <div className="flex flex-wrap gap-1.5">
            {asset.ontology_targets.map((target) => (
              <span
                className="rounded-full bg-tint-100 px-2.5 py-0.5 text-xs text-signal dark:bg-signal/15"
                key={target}
              >
                {target}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {asset.notes.length > 0 ? (
        <div className="grid gap-2">
          <h3 className="m-0 text-sm font-medium text-ink">{copy.notes}</h3>
          <ul className="m-0 grid list-disc gap-1 pl-4">
            {asset.notes.map((note) => (
              <li className="text-xs text-muted" key={note}>
                {note}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}

/** Fail-closed detail state for an asset ID that is not in the catalog. */
export function UnknownDataAssetPanel({ assetId }: { assetId: string }) {
  const copy = strings.dataCatalog.states.unknownAsset;

  return (
    <Card className="grid content-start gap-4">
      <EmptyPanel detail={copy.detail} title={copy.title} />
      <p className="m-0 font-mono text-xs break-all text-muted">{assetId}</p>
    </Card>
  );
}

const CLASSIFICATION_VALUES = [
  "public",
  "internal",
  "confidential",
  "restricted",
] as const;

/** Mirrors the PUT /data/assets/{id}/stewardship field constraints. */
const OWNER_LIMIT = 200;
const SHORT_FIELD_LIMIT = 80;

type StewardshipFormState = {
  owner: string;
  classification: DataAssetClassification;
  residency: string;
  retention: string;
};

type StewardshipFieldErrors = Partial<
  Record<"owner" | "residency" | "retention", string>
>;

function validateStewardshipForm(
  form: StewardshipFormState,
): StewardshipFieldErrors {
  const copy = strings.dataCatalog.stewardship.form.errors;
  const errors: StewardshipFieldErrors = {};
  const owner = form.owner.trim();
  if (owner.length === 0) {
    errors.owner = copy.ownerRequired;
  } else if (owner.length > OWNER_LIMIT) {
    errors.owner = copy.ownerTooLong(OWNER_LIMIT);
  }
  const residency = form.residency.trim();
  if (residency.length === 0) {
    errors.residency = copy.residencyRequired;
  } else if (residency.length > SHORT_FIELD_LIMIT) {
    errors.residency = copy.residencyTooLong(SHORT_FIELD_LIMIT);
  }
  const retention = form.retention.trim();
  if (retention.length === 0) {
    errors.retention = copy.retentionRequired;
  } else if (retention.length > SHORT_FIELD_LIMIT) {
    errors.retention = copy.retentionTooLong(SHORT_FIELD_LIMIT);
  }
  return errors;
}

/**
 * Per-asset stewardship: the declared record when one exists, otherwise an
 * inline declare form. The declaration PUT is idempotent and revision-guarded;
 * a successful declare asks the parent to refresh so the catalog and this
 * section converge on the new revision.
 */
export function StewardshipSection({
  asset,
  onSuccess,
  tenantId,
}: {
  asset: DataAsset;
  onSuccess: () => void;
  tenantId: string;
}) {
  const copy = strings.dataCatalog.stewardship;
  const { session } = useOidcConsoleSession();
  const stewardshipQuery = useDataAssetStewardship(asset.asset_id, tenantId, true);
  const [form, setForm] = useState<StewardshipFormState>({
    classification: "internal",
    owner: "",
    residency: "",
    retention: "",
  });
  const [fieldErrors, setFieldErrors] = useState<StewardshipFieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [error, setError] = useState<AxisOperatorError | null>(null);
  const [declared, setDeclared] = useState(false);

  function updateField<K extends keyof StewardshipFormState>(
    field: K,
    value: StewardshipFormState[K],
  ) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function submitDeclaration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const errors = validateStewardshipForm(form);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      return;
    }

    setSubmitting(true);
    setConflict(false);
    setError(null);
    try {
      await axisFetchParsedJson(
        buildDataAssetStewardshipPath(asset.asset_id, tenantId),
        (value) => {
          const decoded = parseDataAssetStewardshipView(value);
          if (decoded.tenant_id !== tenantId || decoded.asset_id !== asset.asset_id) {
            throw new Error("Stewardship response scope mismatch.");
          }
          return decoded;
        },
        {
          body: {
            classification: form.classification,
            expected_revision: null,
            idempotency_key: safeRandomUuid(),
            owner: form.owner.trim(),
            residency: form.residency.trim(),
            retention: form.retention.trim(),
          },
          method: "PUT",
          session,
        },
      );
      setDeclared(true);
      onSuccess();
    } catch (caught) {
      if (
        caught instanceof AxisApiError
        && caught.status === 409
        && caught.reason === "expected_revision_mismatch"
      ) {
        setConflict(true);
      } else {
        setError(toAxisOperatorError(caught, copy.form.errors.declareFailed));
      }
    } finally {
      setSubmitting(false);
    }
  }

  const record = stewardshipQuery.data?.stewardship ?? null;

  return (
    <Card className="grid content-start gap-4">
      <div className="grid gap-1">
        <Eyebrow>{copy.title}</Eyebrow>
        <p className="m-0 text-sm text-muted">{copy.description}</p>
      </div>
      {stewardshipQuery.isLoading ? (
        <LoadingPanel rows={2} />
      ) : !stewardshipQuery.data || stewardshipQuery.error ? (
        <ErrorPanel
          detail={copy.states.error.detail}
          endpoint={DATA_ASSET_STEWARDSHIP_ENDPOINTS.stewardship}
          reference={stewardshipQuery.errorRequestId ?? undefined}
          title={copy.states.error.title}
        />
      ) : record ? (
        <DetailGrid>
          <KeyValueRow label={copy.fields.owner}>{record.owner}</KeyValueRow>
          <KeyValueRow label={copy.fields.classification}>
            {copy.classificationLabels[record.classification]}
          </KeyValueRow>
          <KeyValueRow label={copy.fields.residency}>{record.residency}</KeyValueRow>
          <KeyValueRow label={copy.fields.retention}>{record.retention}</KeyValueRow>
          <KeyValueRow label={copy.fields.revision}>{record.revision_number}</KeyValueRow>
          <KeyValueRow label={copy.fields.declaredBy}>{record.declared_by}</KeyValueRow>
          <KeyValueRow label={copy.fields.declaredAt}>
            {formatDateTime(record.declared_at)}
          </KeyValueRow>
        </DetailGrid>
      ) : (
        <>
          <form
            aria-label={copy.form.title}
            className="grid gap-3"
            noValidate
            onSubmit={(event) => void submitDeclaration(event)}
          >
            <p className="m-0 text-sm leading-snug text-muted">{copy.form.description}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={copy.fields.owner}>
                <Input
                  aria-invalid={Boolean(fieldErrors.owner)}
                  disabled={submitting}
                  onChange={(event) => updateField("owner", event.target.value)}
                  value={form.owner}
                />
                {fieldErrors.owner ? (
                  <span className="m-0 text-sm text-danger" role="alert">
                    {fieldErrors.owner}
                  </span>
                ) : null}
              </Field>
              <Field label={copy.fields.classification}>
                <Select
                  disabled={submitting}
                  onChange={(event) =>
                    updateField(
                      "classification",
                      event.target.value as DataAssetClassification,
                    )
                  }
                  value={form.classification}
                >
                  {CLASSIFICATION_VALUES.map((value) => (
                    <option key={value} value={value}>
                      {copy.classificationLabels[value]}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={copy.fields.residency}>
                <Input
                  aria-invalid={Boolean(fieldErrors.residency)}
                  disabled={submitting}
                  onChange={(event) => updateField("residency", event.target.value)}
                  value={form.residency}
                />
                {fieldErrors.residency ? (
                  <span className="m-0 text-sm text-danger" role="alert">
                    {fieldErrors.residency}
                  </span>
                ) : null}
              </Field>
              <Field label={copy.fields.retention}>
                <Input
                  aria-invalid={Boolean(fieldErrors.retention)}
                  disabled={submitting}
                  onChange={(event) => updateField("retention", event.target.value)}
                  value={form.retention}
                />
                {fieldErrors.retention ? (
                  <span className="m-0 text-sm text-danger" role="alert">
                    {fieldErrors.retention}
                  </span>
                ) : null}
              </Field>
            </div>
            <div className="flex flex-wrap justify-end">
              <Button loading={submitting} type="submit">
                {submitting ? copy.form.submitting : copy.form.submit}
              </Button>
            </div>
          </form>
          {conflict ? (
            <p className="m-0 text-sm text-danger" role="alert">
              {copy.form.errors.conflict}
            </p>
          ) : null}
          {error ? (
            <InlineOperatorError error={error} prefix={copy.form.errors.declareFailed} />
          ) : null}
          {declared ? (
            <p className="m-0 text-sm text-muted" role="status">
              {copy.form.success}
            </p>
          ) : null}
        </>
      )}
    </Card>
  );
}

function driftPillClass(driftState: string): string {
  if (driftState === "added") {
    return "signal-watch";
  }
  if (driftState === "changed") {
    return "signal-action-required";
  }
  return "signal-ready";
}

function ResourceRow({ resource }: { resource: DataAssetResourceObservation }) {
  const copy = strings.dataCatalog.resources;

  return (
    <div
      className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-line px-3 py-2 dark:border-white/10"
      data-resource-name={resource.resource_name}
    >
      <span className="min-w-0">
        <span className="block truncate font-mono text-xs text-ink">
          {resource.resource_name}
        </span>
        <span className="text-xs text-muted">
          {copy.observations(resource.observation_count)} ·{" "}
          {formatDateTime(resource.last_seen_at)}
        </span>
      </span>
      <span className={`status-pill ${driftPillClass(resource.drift_state)}`}>
        {copy.drift[resource.drift_state]}
      </span>
    </div>
  );
}

/**
 * Read-only observation log for one asset: resources Axis actually saw
 * through governed preview boundaries, with evidence-derived drift states.
 */
export function ResourcesSection({
  asset,
  tenantId,
}: {
  asset: DataAsset;
  tenantId: string;
}) {
  const copy = strings.dataCatalog.resources;
  const resourcesQuery = useDataAssetResources(asset.asset_id, tenantId, true);

  return (
    <Card className="grid content-start gap-4" data-testid="resources-section">
      <div className="grid gap-1">
        <Eyebrow>{copy.title}</Eyebrow>
        <p className="m-0 text-sm text-muted">{copy.description}</p>
      </div>
      {resourcesQuery.isLoading ? (
        <LoadingPanel rows={2} />
      ) : !resourcesQuery.data || resourcesQuery.error ? (
        <ErrorPanel
          detail={copy.states.error.detail}
          endpoint={DATA_ASSET_RESOURCES_ENDPOINTS.resources}
          reference={resourcesQuery.errorRequestId ?? undefined}
          title={copy.states.error.title}
        />
      ) : (
        <>
          <p className="m-0 text-sm text-ink">
            {copy.countSummary(resourcesQuery.data.resources.length)}
          </p>
          {resourcesQuery.data.resources.length === 0 ? (
            <EmptyPanel detail={copy.empty.detail} title={copy.empty.title} />
          ) : (
            <div className="grid gap-2">
              {resourcesQuery.data.resources.map((resource) => (
                <ResourceRow key={resource.resource_name} resource={resource} />
              ))}
            </div>
          )}
          {resourcesQuery.data.notes.length > 0 ? (
            <details className="text-xs text-muted">
              <summary className="cursor-pointer">{copy.notesTitle}</summary>
              <ul className="m-0 mt-1 grid list-disc gap-1 pl-4">
                {resourcesQuery.data.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </>
      )}
    </Card>
  );
}

const FINGERPRINT_LENGTH = 64;

type ContractFormState = {
  expectedResourceName: string;
  expectedSchemaFingerprint: string;
  freshnessWarnHours: string;
  freshnessFailHours: string;
};

function contractStatusPillClass(state: string): string {
  if (state === "pass") {
    return "signal-ready";
  }
  if (state === "warn") {
    return "signal-watch";
  }
  if (state === "fail") {
    return "signal-action-required";
  }
  return "status-checking";
}

function parseOptionalHours(value: string): number | null | "invalid" {
  const trimmed = value.trim();
  if (trimmed.length === 0) {
    return null;
  }
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed) || parsed < 1) {
    return "invalid";
  }
  return parsed;
}

function validateContractForm(form: ContractFormState): {
  errors: Record<string, string>;
  parsed: {
    expectedSchemaFingerprint: string | null;
    freshnessWarnHours: number | null;
    freshnessFailHours: number | null;
  };
} {
  const copy = strings.dataCatalog.contract.form.errors;
  const errors: Record<string, string> = {};
  if (form.expectedResourceName.trim().length === 0) {
    errors.expectedResourceName = copy.resourceRequired;
  }
  const fingerprint = form.expectedSchemaFingerprint.trim().toLowerCase();
  let parsedFingerprint: string | null = null;
  if (fingerprint.length > 0) {
    if (
      fingerprint.length !== FINGERPRINT_LENGTH
      || !/^[0-9a-f]+$/.test(fingerprint)
    ) {
      errors.expectedSchemaFingerprint = copy.fingerprintInvalid(
        FINGERPRINT_LENGTH,
      );
    } else {
      parsedFingerprint = fingerprint;
    }
  }
  const warnHours = parseOptionalHours(form.freshnessWarnHours);
  if (warnHours === "invalid") {
    errors.freshnessWarnHours = copy.hoursInvalid;
  }
  const failHours = parseOptionalHours(form.freshnessFailHours);
  if (failHours === "invalid") {
    errors.freshnessFailHours = copy.hoursInvalid;
  }
  if (
    typeof warnHours === "number"
    && typeof failHours === "number"
    && warnHours > failHours
  ) {
    errors.freshnessFailHours = copy.orderingInvalid;
  }
  return {
    errors,
    parsed: {
      expectedSchemaFingerprint: parsedFingerprint,
      freshnessWarnHours: typeof warnHours === "number" ? warnHours : null,
      freshnessFailHours: typeof failHours === "number" ? failHours : null,
    },
  };
}

/**
 * Declared expectations plus their read-time evaluation. The section never
 * renders green without evidence: an undeclared or unobserved asset shows
 * the explicit unknown state.
 */
export function ContractSection({
  asset,
  onSuccess,
  tenantId,
}: {
  asset: DataAsset;
  onSuccess: () => void;
  tenantId: string;
}) {
  const copy = strings.dataCatalog.contract;
  const { session } = useOidcConsoleSession();
  const contractQuery = useDataAssetContract(asset.asset_id, tenantId, true);
  const evaluationQuery = useDataAssetContractEvaluation(
    asset.asset_id,
    tenantId,
    true,
  );
  const [form, setForm] = useState<ContractFormState>({
    expectedResourceName: "",
    expectedSchemaFingerprint: "",
    freshnessWarnHours: "",
    freshnessFailHours: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [error, setError] = useState<AxisOperatorError | null>(null);
  const [declared, setDeclared] = useState(false);

  function updateField(field: keyof ContractFormState, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function submitDeclaration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const { errors: fieldErrors, parsed } = validateContractForm(form);
    setErrors(fieldErrors);
    if (Object.keys(fieldErrors).length > 0) {
      return;
    }

    setSubmitting(true);
    setConflict(false);
    setError(null);
    try {
      await axisFetchParsedJson(
        buildDataAssetContractPath(asset.asset_id, tenantId),
        (value) => {
          const decoded = parseDataAssetContractView(value);
          if (
            decoded.tenant_id !== tenantId
            || decoded.asset_id !== asset.asset_id
          ) {
            throw new Error("Contract response scope mismatch.");
          }
          return decoded;
        },
        {
          body: {
            expected_resource_name: form.expectedResourceName.trim(),
            expected_schema_fingerprint: parsed.expectedSchemaFingerprint,
            freshness_warn_hours: parsed.freshnessWarnHours,
            freshness_fail_hours: parsed.freshnessFailHours,
            expected_revision: null,
            idempotency_key: safeRandomUuid(),
          },
          method: "PUT",
          session,
        },
      );
      setDeclared(true);
      onSuccess();
    } catch (caught) {
      if (
        caught instanceof AxisApiError
        && caught.status === 409
        && caught.reason === "expected_revision_mismatch"
      ) {
        setConflict(true);
      } else {
        setError(toAxisOperatorError(caught, copy.form.errors.declareFailed));
      }
    } finally {
      setSubmitting(false);
    }
  }

  const record = contractQuery.data?.contract ?? null;

  return (
    <Card className="grid content-start gap-4" data-testid="contract-section">
      <div className="grid gap-1">
        <Eyebrow>{copy.title}</Eyebrow>
        <p className="m-0 text-sm text-muted">{copy.description}</p>
      </div>
      {contractQuery.isLoading || evaluationQuery.isLoading ? (
        <LoadingPanel rows={2} />
      ) : !contractQuery.data
        || contractQuery.error
        || !evaluationQuery.data
        || evaluationQuery.error ? (
        <ErrorPanel
          detail={copy.states.error.detail}
          endpoint={buildDataAssetContractPath(asset.asset_id, tenantId)}
          reference={contractQuery.errorRequestId ?? undefined}
          title={copy.states.error.title}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`status-pill ${contractStatusPillClass(evaluationQuery.data.status)}`}
            >
              {copy.status[evaluationQuery.data.status]}
            </span>
            {!record ? (
              <span className="text-xs text-muted">{copy.status.notDeclared}</span>
            ) : null}
          </div>
          {evaluationQuery.data.checks.length > 0 ? (
            <ul className="m-0 grid list-none gap-1.5 p-0">
              {evaluationQuery.data.checks.map((check) => (
                <li className="grid gap-0.5" key={check.kind}>
                  <span className="flex items-center gap-2 text-xs font-medium text-ink">
                    {copy.checks[check.kind]}
                    <span
                      className={`status-pill ${contractStatusPillClass(check.state)}`}
                    >
                      {copy.status[check.state]}
                    </span>
                  </span>
                  <span className="text-xs text-muted">{check.detail}</span>
                </li>
              ))}
            </ul>
          ) : null}
          {record ? (
            <DetailGrid>
              <KeyValueRow label={copy.fields.expectedResource} mono>
                {record.expected_resource_name}
              </KeyValueRow>
              <KeyValueRow label={copy.fields.expectedFingerprint} mono>
                {record.expected_schema_fingerprint ?? "—"}
              </KeyValueRow>
              <KeyValueRow label={copy.fields.warnHours}>
                {record.freshness_warn_hours ?? "—"}
              </KeyValueRow>
              <KeyValueRow label={copy.fields.failHours}>
                {record.freshness_fail_hours ?? "—"}
              </KeyValueRow>
              <KeyValueRow label={copy.fields.revision}>
                {record.revision_number}
              </KeyValueRow>
              <KeyValueRow label={copy.fields.declaredBy}>
                {record.declared_by}
              </KeyValueRow>
              <KeyValueRow label={copy.fields.declaredAt}>
                {formatDateTime(record.declared_at)}
              </KeyValueRow>
            </DetailGrid>
          ) : (
            <>
              <form
                aria-label={copy.form.title}
                className="grid gap-3"
                noValidate
                onSubmit={(event) => void submitDeclaration(event)}
              >
                <p className="m-0 text-sm leading-snug text-muted">
                  {copy.form.description}
                </p>
                <div className="grid gap-3">
                  <Field label={copy.fields.expectedResource}>
                    <Input
                      aria-invalid={Boolean(errors.expectedResourceName)}
                      disabled={submitting}
                      onChange={(event) =>
                        updateField("expectedResourceName", event.target.value)
                      }
                      value={form.expectedResourceName}
                    />
                    {errors.expectedResourceName ? (
                      <span className="m-0 text-sm text-danger" role="alert">
                        {errors.expectedResourceName}
                      </span>
                    ) : null}
                  </Field>
                  <Field label={copy.fields.expectedFingerprint}>
                    <Input
                      aria-invalid={Boolean(errors.expectedSchemaFingerprint)}
                      disabled={submitting}
                      onChange={(event) =>
                        updateField("expectedSchemaFingerprint", event.target.value)
                      }
                      value={form.expectedSchemaFingerprint}
                    />
                    {errors.expectedSchemaFingerprint ? (
                      <span className="m-0 text-sm text-danger" role="alert">
                        {errors.expectedSchemaFingerprint}
                      </span>
                    ) : null}
                  </Field>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label={copy.fields.warnHours}>
                      <Input
                        aria-invalid={Boolean(errors.freshnessWarnHours)}
                        disabled={submitting}
                        inputMode="numeric"
                        onChange={(event) =>
                          updateField("freshnessWarnHours", event.target.value)
                        }
                        value={form.freshnessWarnHours}
                      />
                      {errors.freshnessWarnHours ? (
                        <span className="m-0 text-sm text-danger" role="alert">
                          {errors.freshnessWarnHours}
                        </span>
                      ) : null}
                    </Field>
                    <Field label={copy.fields.failHours}>
                      <Input
                        aria-invalid={Boolean(errors.freshnessFailHours)}
                        disabled={submitting}
                        inputMode="numeric"
                        onChange={(event) =>
                          updateField("freshnessFailHours", event.target.value)
                        }
                        value={form.freshnessFailHours}
                      />
                      {errors.freshnessFailHours ? (
                        <span className="m-0 text-sm text-danger" role="alert">
                          {errors.freshnessFailHours}
                        </span>
                      ) : null}
                    </Field>
                  </div>
                </div>
                <div className="flex flex-wrap justify-end">
                  <Button loading={submitting} type="submit">
                    {submitting ? copy.form.submitting : copy.form.submit}
                  </Button>
                </div>
              </form>
              {conflict ? (
                <p className="m-0 text-sm text-danger" role="alert">
                  {copy.form.errors.conflict}
                </p>
              ) : null}
              {error ? (
                <InlineOperatorError
                  error={error}
                  prefix={copy.form.errors.declareFailed}
                />
              ) : null}
              {declared ? (
                <p className="m-0 text-sm text-muted" role="status">
                  {copy.form.success}
                </p>
              ) : null}
            </>
          )}
        </>
      )}
    </Card>
  );
}
