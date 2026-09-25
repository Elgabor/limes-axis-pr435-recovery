"use client";

import { useMemo, useRef, useState, type ChangeEvent } from "react";
import { Database, FileText, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DetailGrid, KeyValueRow } from "@/components/ui/detail-grid";
import { Field, FieldError } from "@/components/ui/field";
import { InlineOperatorError } from "@/components/ui/inline-operator-error";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import {
  AxisApiDecodeError,
  AxisApiError,
  axisFetch,
  axisResponseRequestId,
  decodeAxisJson,
  readAxisResponseBody,
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import { cn } from "@/lib/cn";
import {
  buildExternalDbPreviewRequest,
  buildManifestCreateRequest,
  CONNECTOR_CONSOLE_ACTOR,
  deriveConnectorId,
  parseCsvText,
  type ParsedCsv,
} from "@/lib/connectors-console";
import type {
  ConnectorCsvPreviewResult,
  ConnectorExternalDbPreviewResult,
  ConnectorRegistryItem,
} from "@/lib/connectors-demo";
import { formatNumber } from "@/lib/format";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { deriveGovernedActor } from "@/lib/governed-action";
import {
  parseConnectorCsvPreviewResult,
  parseConnectorExternalDbPreviewResult,
} from "@/lib/runtime-contracts/connectors";
import { strings } from "@/lib/strings";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

/*
 * Add Connector wizard. The Axis preview endpoints validate real content
 * against an existing registry connector's field mapping, so the CSV step
 * pairs the uploaded file with a mapping template from the registry; the
 * manifest that gets registered is the template with the new identity and the
 * file-derived preview sample. Registration never starts a live sync.
 */

type WizardStep = "type" | "source" | "review";
type ConnectorChoice = "file_csv" | "external_db";
type SubmitErrorKind = "conflict" | "forbidden" | "validation" | "generic";

const CSV_PREVIEW_ENDPOINT = `${OPERATIONS_API_PREFIX}/connectors/file-csv/preview`;
const DB_PREVIEW_ENDPOINT = `${OPERATIONS_API_PREFIX}/connectors/external-db/preview`;
const MANIFESTS_ENDPOINT = `${OPERATIONS_API_PREFIX}/connectors/manifests`;

type SubmitError = {
  kind: SubmitErrorKind;
  error: AxisOperatorError;
};

type DbForm = {
  connectionProfileId: string;
  schemaName: string;
  tableName: string;
  credentialHandleId: string;
};

const DEFAULT_DB_FORM: DbForm = {
  connectionProfileId: "profile_postgres_ops_readonly",
  schemaName: "operations",
  tableName: "production_orders",
  credentialHandleId: "cred_external_db_readonly",
};

function operatorErrorWithMessage(caught: unknown, message: string): AxisOperatorError {
  return { ...toAxisOperatorError(caught, message), message };
}

async function responseOperatorError(
  path: string,
  response: Response,
  message: string,
): Promise<AxisOperatorError> {
  const error = new AxisApiError(path, response.status, {
    body: await readAxisResponseBody(response),
    requestId: axisResponseRequestId(response),
  });
  return operatorErrorWithMessage(error, message);
}

function IssueList({ title, issues }: { title: string; issues: string[] }) {
  return (
    <div className="grid gap-1.5 rounded-2xl border border-warning/40 bg-warning/8 p-4">
      <p className="m-0 text-sm font-medium text-ink">{title}</p>
      <ul className="m-0 grid list-none gap-1 p-0">
        {issues.map((issue) => (
          <li className="text-sm text-muted" key={issue}>
            {issue}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AddConnectorWizard({
  connectors,
  templatesLoading = false,
  templatesUnavailable = false,
  identitySession,
  open,
  onOpenChange,
  onCreated,
  tenantId,
}: {
  connectors: ConnectorRegistryItem[];
  templatesLoading?: boolean;
  templatesUnavailable?: boolean;
  identitySession: IdentitySessionReadModel | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
  tenantId: string;
}) {
  const copy = strings.connectors.wizard;
  const { push } = useToast();
  const { session } = useOidcConsoleSession();

  const [step, setStep] = useState<WizardStep>("type");
  const [choice, setChoice] = useState<ConnectorChoice>("file_csv");

  // CSV source state
  const [csvTemplateId, setCsvTemplateId] = useState("");
  const [csvFileName, setCsvFileName] = useState("");
  const [csvText, setCsvText] = useState("");
  const [parsedCsv, setParsedCsv] = useState<ParsedCsv | null>(null);
  const [csvPreview, setCsvPreview] = useState<ConnectorCsvPreviewResult | null>(null);
  const [fileReadError, setFileReadError] = useState(false);

  // External DB source state
  const [dbTemplateId, setDbTemplateId] = useState("");
  const [dbForm, setDbForm] = useState<DbForm>(DEFAULT_DB_FORM);
  const [dbPreview, setDbPreview] = useState<ConnectorExternalDbPreviewResult | null>(null);

  // Shared preview/submit lifecycle
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<AxisOperatorError | null>(null);
  const previewGeneration = useRef(0);

  // Review state
  const [connectorId, setConnectorId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<SubmitError | null>(null);

  const csvTemplates = useMemo(
    () => connectors.filter((connector) => connector.manifest.connector_type === "file_csv"),
    [connectors],
  );
  const dbTemplates = useMemo(
    () => connectors.filter((connector) => connector.manifest.connector_type === "external_db"),
    [connectors],
  );

  const templates = choice === "file_csv" ? csvTemplates : dbTemplates;
  const selectedTemplateId = choice === "file_csv" ? csvTemplateId : dbTemplateId;
  const template =
    templates.find((item) => item.manifest.connector_id === selectedTemplateId)
    ?? templates[0]
    ?? null;

  // Submission is gated only when the API confirms it enforces OIDC and the
  // browser session is unauthenticated; in public-evaluation deployments
  // (api_auth_required=false) unauthenticated demo writes are accepted.
  const { actorId, ssoBlocked } = deriveGovernedActor(
    identitySession,
    CONNECTOR_CONSOLE_ACTOR,
  );

  const sourceReady =
    choice === "file_csv"
      ? csvPreview?.preview_status === "ready" && parsedCsv !== null
      : dbPreview?.preview_status === "ready";

  function invalidatePreviewState(): number {
    previewGeneration.current += 1;
    setCsvPreview(null);
    setDbPreview(null);
    setPreviewError(null);
    setPreviewing(false);
    return previewGeneration.current;
  }

  function beginPreview(): number {
    previewGeneration.current += 1;
    setPreviewing(true);
    setPreviewError(null);
    return previewGeneration.current;
  }

  function resetAll() {
    previewGeneration.current += 1;
    setStep("type");
    setChoice("file_csv");
    setCsvTemplateId("");
    setCsvFileName("");
    setCsvText("");
    setParsedCsv(null);
    setCsvPreview(null);
    setFileReadError(false);
    setDbTemplateId("");
    setDbForm(DEFAULT_DB_FORM);
    setDbPreview(null);
    setPreviewing(false);
    setPreviewError(null);
    setConnectorId("");
    setDisplayName("");
    setSubmitting(false);
    setSubmitError(null);
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen) {
      resetAll();
    }
    onOpenChange(nextOpen);
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    const fileGeneration = invalidatePreviewState();
    setFileReadError(false);
    setCsvFileName("");
    setCsvText("");
    setParsedCsv(null);
    if (!file) {
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      if (previewGeneration.current !== fileGeneration) {
        return;
      }
      const text = typeof reader.result === "string" ? reader.result : "";
      setCsvFileName(file.name);
      setCsvText(text);
      setParsedCsv(parseCsvText(text));
    };
    reader.onerror = () => {
      if (previewGeneration.current === fileGeneration) {
        setFileReadError(true);
      }
    };
    reader.readAsText(file);
  }

  async function previewCsv() {
    if (!template || !csvText) {
      return;
    }
    const requestGeneration = beginPreview();
    try {
      const response = await axisFetch(CSV_PREVIEW_ENDPOINT, {
        method: "POST",
        session,
        body: {
          tenant_id: tenantId,
          connector_id: template.manifest.connector_id,
          file_name: csvFileName,
          csv_content: csvText,
        },
      });
      const requestId = axisResponseRequestId(response);
      const body = await readAxisResponseBody(response);
      if (!response.ok) {
        throw new AxisApiError(CSV_PREVIEW_ENDPOINT, response.status, { body, requestId });
      }
      const preview = decodeAxisJson(
        CSV_PREVIEW_ENDPOINT,
        body,
        parseConnectorCsvPreviewResult,
        requestId,
      );
      if (preview.tenant_id !== tenantId) {
        throw new AxisApiDecodeError(
          CSV_PREVIEW_ENDPOINT,
          "Axis API response did not match the requested tenant.",
          { requestId },
        );
      }
      if (previewGeneration.current === requestGeneration) {
        setCsvPreview(preview);
      }
    } catch (caught) {
      if (previewGeneration.current === requestGeneration) {
        setPreviewError(operatorErrorWithMessage(caught, copy.csvStep.previewError));
      }
    } finally {
      if (previewGeneration.current === requestGeneration) {
        setPreviewing(false);
      }
    }
  }

  async function previewDb() {
    if (!template) {
      return;
    }
    const requestGeneration = beginPreview();
    try {
      const response = await axisFetch(DB_PREVIEW_ENDPOINT, {
        method: "POST",
        session,
        body: buildExternalDbPreviewRequest({
          tenantId,
          connectorId: template.manifest.connector_id,
          connectionProfileId: dbForm.connectionProfileId,
          schemaName: dbForm.schemaName,
          tableName: dbForm.tableName,
          credentialHandleId: dbForm.credentialHandleId,
          template,
        }),
      });
      const requestId = axisResponseRequestId(response);
      const body = await readAxisResponseBody(response);
      if (!response.ok) {
        throw new AxisApiError(DB_PREVIEW_ENDPOINT, response.status, { body, requestId });
      }
      const preview = decodeAxisJson(
        DB_PREVIEW_ENDPOINT,
        body,
        parseConnectorExternalDbPreviewResult,
        requestId,
      );
      if (preview.tenant_id !== tenantId) {
        throw new AxisApiDecodeError(
          DB_PREVIEW_ENDPOINT,
          "Axis API response did not match the requested tenant.",
          { requestId },
        );
      }
      if (previewGeneration.current === requestGeneration) {
        setDbPreview(preview);
      }
    } catch (caught) {
      if (previewGeneration.current === requestGeneration) {
        setPreviewError(operatorErrorWithMessage(caught, copy.dbStep.previewError));
      }
    } finally {
      if (previewGeneration.current === requestGeneration) {
        setPreviewing(false);
      }
    }
  }

  function advanceToReview() {
    if (choice === "file_csv") {
      setConnectorId(deriveConnectorId(csvFileName, "file_csv"));
      setDisplayName(csvFileName.replace(/\.[^.]+$/, "") || "New CSV connector");
    } else {
      setConnectorId(
        deriveConnectorId(`${dbForm.schemaName}_${dbForm.tableName}`, "external_db"),
      );
      setDisplayName(`${dbForm.schemaName}.${dbForm.tableName} mirror`);
    }
    setSubmitError(null);
    setStep("review");
  }

  async function submitManifest() {
    if (!template || (choice === "external_db" && !template.preview_sample)) {
      return;
    }
    setSubmitting(true);
    setSubmitError(null);

    const previewSample =
      choice === "file_csv" && parsedCsv
        ? {
            file_name: csvFileName,
            record_count: parsedCsv.rows.length,
            headers: parsedCsv.headers,
            sample_rows: parsedCsv.rows.slice(0, 5),
          }
        : {
            ...template.preview_sample!,
            file_name: `${dbForm.schemaName}.${dbForm.tableName}`,
          };

    try {
      const response = await axisFetch(MANIFESTS_ENDPOINT, {
        method: "POST",
        session,
        body: buildManifestCreateRequest({
          tenantId,
          registeredBy: actorId,
          template,
          connectorId: connectorId.trim(),
          displayName: displayName.trim(),
          previewSample: previewSample,
        }),
      });

      if (response.status === 201) {
        push({
          title: copy.reviewStep.toastTitle,
          detail: copy.reviewStep.toastDetail,
          tone: "positive",
        });
        handleOpenChange(false);
        onCreated();
        return;
      }
      if (response.status === 409) {
        setSubmitError({
          kind: "conflict",
          error: await responseOperatorError(
            MANIFESTS_ENDPOINT,
            response,
            submitErrorLabel.conflict,
          ),
        });
        return;
      }
      if (response.status === 403) {
        setSubmitError({
          kind: "forbidden",
          error: await responseOperatorError(
            MANIFESTS_ENDPOINT,
            response,
            submitErrorLabel.forbidden,
          ),
        });
        return;
      }
      if (response.status === 422) {
        setSubmitError({
          kind: "validation",
          error: await responseOperatorError(
            MANIFESTS_ENDPOINT,
            response,
            submitErrorLabel.validation,
          ),
        });
        return;
      }
      setSubmitError({
        kind: "generic",
        error: await responseOperatorError(
          MANIFESTS_ENDPOINT,
          response,
          submitErrorLabel.generic,
        ),
      });
    } catch (caught) {
      setSubmitError({
        kind: "generic",
        error: operatorErrorWithMessage(caught, submitErrorLabel.generic),
      });
    } finally {
      setSubmitting(false);
    }
  }

  const submitErrorLabel: Record<SubmitErrorKind, string> = {
    conflict: copy.reviewStep.conflict,
    forbidden: copy.reviewStep.forbidden,
    validation: copy.reviewStep.validationFailed,
    generic: copy.reviewStep.genericError,
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent aria-describedby={undefined} className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription>{copy.description}</DialogDescription>
        </DialogHeader>

        {templatesLoading ? <p role="status">Loading connector templates…</p> : null}
        {templatesUnavailable ? <FieldError>Connector templates unavailable. Close and reopen to retry.</FieldError> : null}
        {step === "type" ? (
          <div className="grid gap-3">
            <p className="m-0 text-sm font-medium text-ink">{copy.typeStep.title}</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {(
                [
                  {
                    value: "file_csv" as const,
                    icon: FileText,
                    title: copy.typeStep.csvTitle,
                    detail: copy.typeStep.csvDetail,
                  },
                  {
                    value: "external_db" as const,
                    icon: Database,
                    title: copy.typeStep.dbTitle,
                    detail: copy.typeStep.dbDetail,
                  },
                ]
              ).map((option) => (
                <button
                  aria-pressed={choice === option.value}
                  className={cn(
                    "grid cursor-pointer content-start gap-1.5 rounded-2xl border bg-surface p-4 text-left transition-colors dark:bg-transparent",
                    choice === option.value
                      ? "border-signal/60 bg-tint-50 dark:bg-signal/10"
                      : "border-line hover:border-signal/40 dark:border-white/15",
                  )}
                  key={option.value}
                  onClick={() => {
                    invalidatePreviewState();
                    setChoice(option.value);
                  }}
                  type="button"
                >
                  <span className="flex items-center gap-2 text-sm font-medium text-ink">
                    <option.icon aria-hidden="true" size={16} />
                    {option.title}
                  </span>
                  <span className="text-xs leading-snug text-muted">{option.detail}</span>
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {step === "source" && choice === "file_csv" ? (
          <div className="grid gap-3.5">
            {csvTemplates.length === 0 ? (
              <FieldError>{copy.csvStep.noTemplates}</FieldError>
            ) : (
              <>
                <Field label={copy.csvStep.template}>
                  <Select
                    disabled={previewing}
                    onChange={(event) => {
                      invalidatePreviewState();
                      setCsvTemplateId(event.target.value);
                    }}
                    value={template?.manifest.connector_id ?? ""}
                  >
                    {csvTemplates.map((item) => (
                      <option
                        key={item.manifest.connector_id}
                        value={item.manifest.connector_id}
                      >
                        {item.manifest.display_name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <p className="m-0 text-xs text-muted">{copy.csvStep.templateDetail}</p>
                <Field label={copy.csvStep.file}>
                  <Input accept=".csv,text/csv" onChange={handleFileChange} type="file" />
                </Field>
                {fileReadError ? <FieldError>{copy.csvStep.fileReadError}</FieldError> : null}
                <div>
                  <Button
                    className="px-4 py-2 text-sm"
                    disabled={!csvText || previewing}
                    variant="secondary"
                    onClick={() => void previewCsv()}
                  >
                    {previewing ? copy.csvStep.previewing : copy.csvStep.preview}
                  </Button>
                </div>
                {previewError ? <InlineOperatorError error={previewError} /> : null}
                {csvPreview ? (
                  <div className="grid gap-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          "status-pill",
                          csvPreview.preview_status === "ready"
                            ? "signal-ready"
                            : "signal-action-required",
                        )}
                      >
                        {csvPreview.preview_status === "ready"
                          ? copy.csvStep.readyTitle
                          : copy.csvStep.blockedTitle}
                      </span>
                      <span className="text-sm text-muted">
                        {csvPreview.preview_status === "ready" && csvPreview.accepted_record_count < csvPreview.record_count ? (
                          strings.connectors.partialCsvPreview(csvPreview.accepted_record_count, csvPreview.record_count)
                        ) : (
                          <>
                            {formatNumber(csvPreview.record_count)} {copy.csvStep.rows} /{" "}
                            {formatNumber(csvPreview.accepted_record_count)} {copy.csvStep.accepted} /{" "}
                            {formatNumber(csvPreview.rejected_record_count)} {copy.csvStep.rejected}
                          </>
                        )}
                      </span>
                    </div>
                    {csvPreview.validation_issues.length > 0 ? (
                      <IssueList
                        issues={csvPreview.validation_issues}
                        title={copy.csvStep.issuesTitle}
                      />
                    ) : null}
                    {csvPreview.proposed_entities.length > 0 ? (
                      <DataTable
                        aria-label={copy.csvStep.entitiesTitle}
                        minWidth={360}
                      >
                        <thead>
                          <tr>
                            <th>Node</th>
                            <th>Type</th>
                            <th>Ontology target</th>
                          </tr>
                        </thead>
                        <tbody>
                          {csvPreview.proposed_entities.slice(0, 5).map((entity) => (
                            <tr key={entity.node_id}>
                              <td className="font-mono text-xs">{entity.node_id}</td>
                              <td className="text-xs text-muted">{entity.node_type}</td>
                              <td className="font-mono text-xs">{entity.ontology_type}</td>
                            </tr>
                          ))}
                        </tbody>
                      </DataTable>
                    ) : null}
                  </div>
                ) : null}
              </>
            )}
          </div>
        ) : null}

        {step === "source" && choice === "external_db" ? (
          <div className="grid gap-3.5">
            {dbTemplates.length === 0 ? (
              <FieldError>{copy.dbStep.noTemplates}</FieldError>
            ) : (
              <>
                <Field label={copy.dbStep.template}>
                  <Select
                    disabled={previewing}
                    onChange={(event) => {
                      invalidatePreviewState();
                      setDbTemplateId(event.target.value);
                    }}
                    value={template?.manifest.connector_id ?? ""}
                  >
                    {dbTemplates.map((item) => (
                      <option
                        key={item.manifest.connector_id}
                        value={item.manifest.connector_id}
                      >
                        {item.manifest.display_name}
                      </option>
                    ))}
                  </Select>
                </Field>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label={copy.dbStep.profile}>
                    <Input
                      onChange={(event) => {
                        invalidatePreviewState();
                        setDbForm((current) => ({
                          ...current,
                          connectionProfileId: event.target.value,
                        }));
                      }}
                      value={dbForm.connectionProfileId}
                    />
                  </Field>
                  <Field label={copy.dbStep.credentialHandle}>
                    <Input
                      onChange={(event) => {
                        invalidatePreviewState();
                        setDbForm((current) => ({
                          ...current,
                          credentialHandleId: event.target.value,
                        }));
                      }}
                      value={dbForm.credentialHandleId}
                    />
                  </Field>
                  <Field label={copy.dbStep.schema}>
                    <Input
                      onChange={(event) => {
                        invalidatePreviewState();
                        setDbForm((current) => ({ ...current, schemaName: event.target.value }));
                      }}
                      value={dbForm.schemaName}
                    />
                  </Field>
                  <Field label={copy.dbStep.table}>
                    <Input
                      onChange={(event) => {
                        invalidatePreviewState();
                        setDbForm((current) => ({ ...current, tableName: event.target.value }));
                      }}
                      value={dbForm.tableName}
                    />
                  </Field>
                </div>
                <p className="m-0 text-xs text-muted">{copy.dbStep.profileDetail}</p>
                <div>
                  <Button
                    className="px-4 py-2 text-sm"
                    disabled={previewing}
                    variant="secondary"
                    onClick={() => void previewDb()}
                  >
                    {previewing ? copy.dbStep.previewing : copy.dbStep.preview}
                  </Button>
                </div>
                {previewError ? <InlineOperatorError error={previewError} /> : null}
                {dbPreview ? (
                  <div className="grid gap-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          "status-pill",
                          dbPreview.preview_status === "ready"
                            ? "signal-ready"
                            : "signal-action-required",
                        )}
                      >
                        {dbPreview.preview_status === "ready"
                          ? copy.dbStep.readyTitle
                          : copy.dbStep.blockedTitle}
                      </span>
                      <span className="font-mono text-xs text-muted">
                        {dbPreview.inspected_table.table_ref}
                      </span>
                    </div>
                    {dbPreview.validation_issues.length > 0 ? (
                      <IssueList
                        issues={dbPreview.validation_issues}
                        title={copy.csvStep.issuesTitle}
                      />
                    ) : null}
                    {dbPreview.inspected_table.columns.length > 0 ? (
                      <DataTable aria-label={copy.dbStep.columnsTitle} minWidth={360}>
                        <thead>
                          <tr>
                            <th>Column</th>
                            <th>Target</th>
                            <th>Ontology target</th>
                          </tr>
                        </thead>
                        <tbody>
                          {dbPreview.inspected_table.columns.map((column) => (
                            <tr key={column.source_column}>
                              <td className="font-mono text-xs">{column.source_column}</td>
                              <td className="font-mono text-xs">{column.target_field}</td>
                              <td className="font-mono text-xs">{column.ontology_target}</td>
                            </tr>
                          ))}
                        </tbody>
                      </DataTable>
                    ) : null}
                  </div>
                ) : null}
              </>
            )}
          </div>
        ) : null}

        {step === "review" && template ? (
          <div className="grid gap-3.5">
            <p className="m-0 text-sm font-medium text-ink">{copy.reviewStep.title}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={copy.reviewStep.connectorId}>
                <Input
                  className="font-mono text-xs"
                  onChange={(event) => {
                    setConnectorId(event.target.value);
                    setSubmitError(null);
                  }}
                  value={connectorId}
                />
              </Field>
              <Field label={copy.reviewStep.displayName}>
                <Input
                  onChange={(event) => {
                    setDisplayName(event.target.value);
                    setSubmitError(null);
                  }}
                  value={displayName}
                />
              </Field>
            </div>
            <DetailGrid>
              <KeyValueRow label={copy.reviewStep.type}>
                {choice === "file_csv"
                  ? copy.typeStep.csvTitle
                  : copy.typeStep.dbTitle}
              </KeyValueRow>
              <KeyValueRow label={copy.reviewStep.records}>
                {choice === "file_csv"
                  ? `${formatNumber(parsedCsv?.rows.length ?? 0)} rows from ${csvFileName}`
                  : `${dbForm.schemaName}.${dbForm.tableName} metadata`}
              </KeyValueRow>
            </DetailGrid>

            {ssoBlocked ? (
              <p className="m-0 flex items-center gap-2 text-sm text-muted" role="status">
                <ShieldCheck aria-hidden="true" className="shrink-0 text-signal" size={15} />
                {copy.ssoGate}
              </p>
            ) : null}
            {submitError ? (
              <InlineOperatorError error={submitError.error} />
            ) : null}
          </div>
        ) : null}

        <DialogFooter>
          {step !== "type" ? (
            <Button
              className="px-4 py-2 text-sm"
              variant="ghost"
              onClick={() => {
                invalidatePreviewState();
                setStep(step === "review" ? "source" : "type");
              }}
            >
              {copy.back}
            </Button>
          ) : null}
          <Button
            className="px-4 py-2 text-sm"
            variant="secondary"
            onClick={() => handleOpenChange(false)}
          >
            {copy.cancel}
          </Button>
          {step === "type" ? (
            <Button className="px-4 py-2 text-sm" disabled={templatesLoading || templatesUnavailable} onClick={() => setStep("source")}>
              {copy.next}
            </Button>
          ) : null}
          {step === "source" ? (
            <Button
              className="px-4 py-2 text-sm"
              disabled={!sourceReady}
              onClick={advanceToReview}
            >
              {copy.next}
            </Button>
          ) : null}
          {step === "review" ? (
            <Button
              className="px-4 py-2 text-sm"
              disabled={
                submitting || ssoBlocked || connectorId.trim() === "" || displayName.trim() === ""
              }
              onClick={() => void submitManifest()}
            >
              {submitting ? copy.submitting : copy.submit}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
