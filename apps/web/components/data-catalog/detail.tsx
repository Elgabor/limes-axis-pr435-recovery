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
import type { DataAsset, DataAssetClassification } from "@/lib/data-assets";
import { formatDateTime } from "@/lib/format";
import { safeRandomUuid } from "@/lib/ids";
import { parseDataAssetStewardshipView } from "@/lib/runtime-contracts/data-assets";
import { strings } from "@/lib/strings";
import {
  buildDataAssetStewardshipPath,
  DATA_ASSET_STEWARDSHIP_ENDPOINTS,
  useDataAssetStewardship,
} from "@/lib/use-data-asset-stewardship";
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
