"use client";

import { useRef, useState, type ChangeEvent } from "react";
import { FileJson, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Field } from "@/components/ui/field";
import { InlineOperatorError } from "@/components/ui/inline-operator-error";
import { Input, Textarea } from "@/components/ui/input";
import { ErrorPanel } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import {
  AxisApiError,
  axisFetch,
  axisFetchParsedJson,
  axisResponseRequestId,
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import { cn } from "@/lib/cn";
import {
  CONNECTOR_CONSOLE_ACTOR,
  CONNECTOR_MANIFEST_BATCH_LIMIT,
  type ConnectorManifestBatchValidationResponse,
  type ConnectorManifestValidationOutcome,
  type ConnectorRegistrationDocument,
} from "@/lib/connectors-console";
import { safeRandomUuid } from "@/lib/ids";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import {
  parseConnectorManifestBatchValidationResponse,
  parseConnectorManifestDetail,
} from "@/lib/runtime-contracts/connectors";
import { strings } from "@/lib/strings";
import { buildTenantScopedPath, OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";

export const MANIFESTS_ENDPOINT = `${OPERATIONS_API_PREFIX}/connectors/manifests`;
export const MANIFEST_VALIDATION_ENDPOINT = `${MANIFESTS_ENDPOINT}/validation`;

type LocalError = "malformed" | "shape" | "file" | null;
type ApplyResult = "landed" | "failed" | "conflict" | "notAttempted" | "pending";

type ApplyState =
  | { phase: "idle" }
  | { phase: "confirming" }
  | { phase: "applying"; results: ApplyResult[] }
  | { phase: "done"; results: ApplyResult[]; landed: number };

function parseDocuments(text: string):
  | { documents: ConnectorRegistrationDocument[] }
  | { error: Exclude<LocalError, "file" | null> } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { error: "malformed" };
  }

  const documents = Array.isArray(parsed) ? parsed : [parsed];
  if (
    documents.length === 0
    || documents.some((document) => (
      typeof document !== "object" || document === null || Array.isArray(document)
    ))
  ) {
    return { error: "shape" };
  }
  return { documents: documents as ConnectorRegistrationDocument[] };
}

function outcomeClass(outcome: ConnectorManifestValidationOutcome): string {
  if (outcome === "would_register") {
    return "signal-ready";
  }
  return outcome === "would_replace" ? "signal-watch" : "signal-action-required";
}

function applyResultClass(result: ApplyResult): string {
  if (result === "landed") {
    return "signal-ready";
  }
  if (result === "failed" || result === "conflict") {
    return "signal-action-required";
  }
  return "status-checking";
}

export function buildManifestDetailPath(connectorId: string, tenantId: string): string {
  return buildTenantScopedPath(
    `${MANIFESTS_ENDPOINT}/${encodeURIComponent(connectorId)}`,
    tenantId,
  );
}

async function readResponseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text.trim()) {
    return null;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function concurrentChangeReason(body: unknown): boolean {
  if (!body || typeof body !== "object" || !("detail" in body)) {
    return false;
  }
  const detail = (body as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object" || !("reason" in detail)) {
    return false;
  }
  const reason = (detail as { reason?: unknown }).reason;
  return reason === "expected_revision_mismatch"
    || reason === "revision_idempotency_conflict";
}

function operatorErrorWithMessage(caught: unknown, message: string): AxisOperatorError {
  return { ...toAxisOperatorError(caught, message), message };
}

export function ManifestImportPanel({
  identitySession,
  onApplied,
  tenantId,
}: {
  identitySession: IdentitySessionReadModel | null;
  onApplied: () => void;
  tenantId: string;
}) {
  const copy = strings.connectors.manifestImport;
  const { push } = useToast();
  const { session } = useOidcConsoleSession();
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [localError, setLocalError] = useState<LocalError>(null);
  const [limitErrorCount, setLimitErrorCount] = useState<number | null>(null);
  const [checking, setChecking] = useState(false);
  const [requestError, setRequestError] = useState<AxisOperatorError | null>(null);
  const [applyError, setApplyError] = useState<AxisOperatorError | null>(null);
  const [documents, setDocuments] = useState<ConnectorRegistrationDocument[]>([]);
  const [validation, setValidation] = useState<ConnectorManifestBatchValidationResponse | null>(null);
  const [replacementRevisions, setReplacementRevisions] = useState<Array<number | null>>([]);
  const [applyState, setApplyState] = useState<ApplyState>({ phase: "idle" });
  const reviewGeneration = useRef(0);

  const ssoBlocked = identitySession != null
    && identitySession.api_auth_required
    && !identitySession.authenticated;
  const invalidCount = validation?.summary.invalid ?? 0;
  const applying = applyState.phase === "applying";
  const canApply = validation !== null
    && invalidCount === 0
    && validation.results.every((result, index) => (
      result.outcome !== "would_replace" || typeof replacementRevisions[index] === "number"
    ))
    && !ssoBlocked
    && applyState.phase === "idle";

  function resetReview(nextText: string): number {
    reviewGeneration.current += 1;
    setText(nextText);
    setLocalError(null);
    setLimitErrorCount(null);
    setRequestError(null);
    setApplyError(null);
    setDocuments([]);
    setValidation(null);
    setReplacementRevisions([]);
    setApplyState({ phase: "idle" });
    setChecking(false);
    return reviewGeneration.current;
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    const fileGeneration = resetReview(file ? "" : text);
    setFileName(file?.name ?? "");
    if (!file) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      if (reviewGeneration.current === fileGeneration) {
        resetReview(typeof reader.result === "string" ? reader.result : "");
      }
    };
    reader.onerror = () => {
      if (reviewGeneration.current === fileGeneration) {
        setLocalError("file");
      }
    };
    reader.readAsText(file);
  }

  async function checkDocuments() {
    const parsed = parseDocuments(text);
    if ("error" in parsed) {
      setLocalError(parsed.error);
      setValidation(null);
      return;
    }
    if (parsed.documents.length > CONNECTOR_MANIFEST_BATCH_LIMIT) {
      setLimitErrorCount(parsed.documents.length);
      setValidation(null);
      return;
    }

    reviewGeneration.current += 1;
    const requestGeneration = reviewGeneration.current;
    setChecking(true);
    setLocalError(null);
    setLimitErrorCount(null);
    setRequestError(null);
    setApplyError(null);
    setDocuments([]);
    setValidation(null);
    setReplacementRevisions([]);
    setApplyState({ phase: "idle" });
    let loadingReplacementRevisions = false;
    try {
      const result = await axisFetchParsedJson<ConnectorManifestBatchValidationResponse>(
        MANIFEST_VALIDATION_ENDPOINT,
        (value) => {
          const decoded = parseConnectorManifestBatchValidationResponse(value);
          if (
            decoded.tenant_id !== tenantId
            || decoded.results.length !== parsed.documents.length
          ) {
            throw new Error("Manifest validation response scope mismatch.");
          }
          return decoded;
        },
        {
          method: "POST",
          session,
          body: {
            tenant_id: tenantId,
            registered_by: identitySession?.actor_id ?? CONNECTOR_CONSOLE_ACTOR,
            manifests: parsed.documents,
          },
        },
      );
      loadingReplacementRevisions = true;
      const revisions = await Promise.all(result.results.map(async (validationResult) => {
        if (validationResult.outcome !== "would_replace") {
          return null;
        }
        if (!validationResult.connector_id) {
          throw new Error(copy.errors.replacementRevisionRequest);
        }
        const detailPath = buildManifestDetailPath(validationResult.connector_id, tenantId);
        const detail = await axisFetchParsedJson(
          detailPath,
          (value) => {
            const decoded = parseConnectorManifestDetail(value);
            if (
              decoded.tenant_id !== tenantId
              || decoded.connector_id !== validationResult.connector_id
            ) {
              throw new Error("Manifest detail response scope mismatch.");
            }
            return decoded;
          },
          { session },
        );
        return detail.current_revision.revision_number;
      }));
      if (reviewGeneration.current === requestGeneration) {
        setDocuments(parsed.documents);
        setReplacementRevisions(revisions);
        setValidation(result);
      }
    } catch (caught) {
      if (reviewGeneration.current === requestGeneration) {
        setRequestError(toAxisOperatorError(
          caught,
          loadingReplacementRevisions
            ? copy.errors.replacementRevisionRequest
            : copy.errors.validationRequest,
        ));
      }
    } finally {
      if (reviewGeneration.current === requestGeneration) {
        setChecking(false);
      }
    }
  }

  async function applyDocuments() {
    if (!validation || invalidCount > 0) {
      return;
    }
    const results: ApplyResult[] = documents.map(() => "pending");
    const applyAttemptId = safeRandomUuid();
    const idempotencyKeys = documents.map((_, index) => (
      `connector-manifest-replace:${applyAttemptId}:${index + 1}`
    ));
    setApplyError(null);
    setApplyState({ phase: "applying", results });
    let landed = 0;
    for (let index = 0; index < documents.length; index += 1) {
      try {
        const validationResult = validation.results[index];
        const replacing = validationResult.outcome === "would_replace";
        const connectorId = validationResult.connector_id;
        const path = replacing && connectorId
          ? `${MANIFESTS_ENDPOINT}/${encodeURIComponent(connectorId)}`
          : MANIFESTS_ENDPOINT;
        const response = await axisFetch(path, {
          method: replacing ? "PUT" : "POST",
          session,
          body: {
            ...documents[index],
            tenant_id: tenantId,
            registered_by: identitySession?.actor_id ?? CONNECTOR_CONSOLE_ACTOR,
            ...(replacing ? {
              idempotency_key: idempotencyKeys[index],
              expected_revision_number: replacementRevisions[index],
            } : {}),
          },
        });
        const expectedStatus = replacing ? 200 : 201;
        if (response.status !== expectedStatus) {
          const responseBody = await readResponseBody(response);
          const conflict = response.status === 409 && concurrentChangeReason(responseBody);
          const fallbackMessage = conflict && connectorId
            ? copy.concurrentConflict(connectorId)
            : copy.applyFailure(landed, documents.length);
          setApplyError(operatorErrorWithMessage(
            new AxisApiError(path, response.status, {
              body: responseBody,
              requestId: axisResponseRequestId(response),
            }),
            fallbackMessage,
          ));
          results[index] = conflict ? "conflict" : "failed";
          for (let pendingIndex = index + 1; pendingIndex < results.length; pendingIndex += 1) {
            results[pendingIndex] = "notAttempted";
          }
          setApplyState({ phase: "done", results: [...results], landed });
          const detail = conflict && connectorId
            ? copy.concurrentConflict(connectorId)
            : copy.applyFailure(landed, documents.length);
          push({
            title: copy.toast.partial,
            detail,
            tone: "danger",
          });
          if (landed > 0) {
            onApplied();
          }
          return;
        }
      } catch (caught) {
        setApplyError(operatorErrorWithMessage(
          caught,
          copy.applyFailure(landed, documents.length),
        ));
        results[index] = "failed";
        for (let pendingIndex = index + 1; pendingIndex < results.length; pendingIndex += 1) {
          results[pendingIndex] = "notAttempted";
        }
        setApplyState({ phase: "done", results: [...results], landed });
        push({
          title: copy.toast.partial,
          detail: copy.applyFailure(landed, documents.length),
          tone: "danger",
        });
        if (landed > 0) {
          onApplied();
        }
        return;
      }
      results[index] = "landed";
      landed += 1;
      setApplyState({ phase: "applying", results: [...results] });
    }
    setApplyState({ phase: "done", results: [...results], landed });
    push({
      title: copy.toast.success,
      detail: copy.applySuccess(landed),
      tone: "positive",
    });
    onApplied();
  }

  const applyResults = applyState.phase === "applying" || applyState.phase === "done"
    ? applyState.results
    : null;
  const applyMessage = applyState.phase === "done"
    ? applyState.results.includes("conflict")
      ? copy.concurrentConflict(
          validation?.results[applyState.results.indexOf("conflict")].connector_id
            ?? copy.table.unknownConnector,
        )
      : applyState.landed === documents.length
      ? copy.applySuccess(applyState.landed)
      : copy.applyFailure(applyState.landed, documents.length)
    : null;

  return (
    <Card className="grid min-w-0 gap-4">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-3xl">
          <Eyebrow>{copy.eyebrow}</Eyebrow>
          <h2 className="font-display mx-0 mt-1 mb-1 text-xl text-ink">{copy.title}</h2>
          <p className="m-0 text-sm leading-snug text-muted">{copy.description}</p>
          <p className="mx-0 mt-2 mb-0 text-sm leading-snug text-muted">{copy.access}</p>
          <p className="mx-0 mt-1 mb-0 font-mono text-xs break-words text-muted">
            {copy.validationEndpoint}: {MANIFEST_VALIDATION_ENDPOINT}
          </p>
          <p className="mx-0 mt-1 mb-0 font-mono text-xs break-words text-muted">
            {copy.applyEndpoint}: {copy.applyEndpointPaths(MANIFESTS_ENDPOINT)}
          </p>
        </div>
        <FileJson aria-hidden="true" className="text-muted" size={20} />
      </div>

      <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(220px,0.35fr)]">
        <Field label={copy.inputLabel}>
          <Textarea
            aria-invalid={Boolean(localError || limitErrorCount)}
            className="min-h-40 font-mono text-xs"
            disabled={applying}
            onChange={(event) => resetReview(event.target.value)}
            placeholder={copy.inputPlaceholder}
            value={text}
          />
        </Field>
        <Field label={copy.fileLabel}>
          <Input
            accept=".json,application/json"
            disabled={applying}
            onChange={handleFileChange}
            type="file"
          />
          {fileName ? <span className="font-mono text-xs text-muted">{fileName}</span> : null}
        </Field>
      </div>

      {localError ? (
        <p className="m-0 text-sm text-danger" role="alert">
          {localError === "file" ? copy.fileReadError : copy.errors[localError]}
        </p>
      ) : null}
      {limitErrorCount !== null ? (
        <p className="m-0 text-sm text-danger" role="alert">
          {copy.errors.tooMany(limitErrorCount, CONNECTOR_MANIFEST_BATCH_LIMIT)}
        </p>
      ) : null}
      {ssoBlocked ? (
        <p className="m-0 flex items-center gap-2 text-sm text-muted" role="status">
          <ShieldCheck aria-hidden="true" className="shrink-0 text-signal" size={15} />
          {copy.ssoGate}
        </p>
      ) : null}

      <div className="flex flex-wrap justify-end gap-2">
        <Button
          disabled={!text.trim() || ssoBlocked || applying}
          loading={checking}
          onClick={() => void checkDocuments()}
          variant="secondary"
        >
          {checking ? copy.checking : copy.check}
        </Button>
        <Button
          disabled={!canApply}
          onClick={() => setApplyState({ phase: "confirming" })}
        >
          {copy.reviewApply}
        </Button>
      </div>

      {requestError ? (
        <ErrorPanel
          detail={requestError.message}
          endpoint={MANIFEST_VALIDATION_ENDPOINT}
          reference={requestError.requestId ?? undefined}
          title={copy.errors.validationRequest}
        />
      ) : null}

      {validation ? (
        <div className="grid gap-4">
          <div aria-label={copy.summary.title} className="grid gap-2 sm:grid-cols-3">
            {([
              ["would_register", copy.summary.wouldRegister],
              ["would_replace", copy.summary.wouldReplace],
              ["invalid", copy.summary.invalid],
            ] as const).map(([outcome, label]) => (
              <div className="rounded-xl border border-line p-3 dark:border-white/10" key={outcome}>
                <p className="m-0 text-xs text-muted">{label}</p>
                <p className="m-0 text-xl font-medium text-ink">{validation.summary[outcome]}</p>
              </div>
            ))}
          </div>

          <DataTable aria-label={copy.title} minWidth={680}>
            <thead>
              <tr>
                <th>{copy.table.document}</th>
                <th>{copy.table.connector}</th>
                <th>{copy.table.outcome}</th>
                {applyResults ? <th>{copy.table.applyResult}</th> : null}
              </tr>
            </thead>
            <tbody>
              {validation.results.map((result, index) => (
                <tr key={index}>
                  <td className="font-mono text-xs">{index + 1}</td>
                  <td className="font-mono text-xs">
                    {result.connector_id ?? copy.table.unknownConnector}
                    {result.errors.length > 0 ? (
                      <ul className="mt-2 mb-0 grid gap-1 pl-4">
                        {result.errors.map((error, errorIndex) => (
                          <li className="text-xs text-danger" key={`${error.field_path}-${errorIndex}`}>
                            <span className="font-mono">{error.field_path}</span>: {error.message}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </td>
                  <td>
                    <span className={cn("status-pill", outcomeClass(result.outcome))}>
                      {copy.outcomes[result.outcome]}
                    </span>
                    {result.outcome === "would_replace" && replacementRevisions[index] ? (
                      <p className="mx-0 mt-1 mb-0 text-xs text-muted">
                        {copy.table.replacesRevision(replacementRevisions[index])}
                      </p>
                    ) : null}
                  </td>
                  {applyResults ? (
                    <td>
                      <span className={cn("status-pill", applyResultClass(applyResults[index]))}>
                        {copy.applyResults[applyResults[index]]}
                      </span>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </DataTable>

          <p
            className={cn("m-0 text-sm", invalidCount > 0 ? "text-danger" : "text-muted")}
            role="status"
          >
            {copy.applyability(invalidCount, documents.length)}
          </p>
          {applyState.phase === "confirming" ? (
            <div className="grid gap-3 rounded-xl border border-warning/40 bg-warning/8 p-4">
              <p className="m-0 text-sm text-muted" role="status">
                {copy.confirmation(documents.length)}
              </p>
              <div className="flex flex-wrap justify-end gap-2">
                <Button onClick={() => setApplyState({ phase: "idle" })} variant="ghost">
                  {copy.cancel}
                </Button>
                <Button onClick={() => void applyDocuments()}>{copy.apply}</Button>
              </div>
            </div>
          ) : null}
          {applyState.phase === "applying" ? (
            <p className="m-0 text-sm text-muted" role="status">{copy.applying}</p>
          ) : null}
          {applyMessage && !applyError ? (
            <p
              className={cn(
                "m-0 text-sm",
                applyState.phase === "done" && applyState.landed === documents.length
                  ? "text-muted"
                  : "text-danger",
              )}
              role="status"
            >
              {applyMessage}
            </p>
          ) : null}
          {applyError ? <InlineOperatorError error={applyError} /> : null}
        </div>
      ) : null}
    </Card>
  );
}
