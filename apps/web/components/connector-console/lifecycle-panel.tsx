"use client";

import { useState } from "react";
import { ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { DetailGrid, KeyValueRow } from "@/components/ui/detail-grid";
import { Eyebrow } from "@/components/ui/eyebrow";
import { InlineOperatorError } from "@/components/ui/inline-operator-error";
import { Field } from "@/components/ui/field";
import { Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import {
  AxisApiDecodeError,
  AxisApiError,
  axisFetch,
  axisResponseRequestId,
  readAxisResponseBody,
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import {
  allLiveRequirementsMet,
  buildManifestLifecycleRequest,
  liveEnablementRequirements,
  manifestLifecycleTargets,
  missingLiveEvidenceCategories,
} from "@/lib/connectors-console";
import { formatConnectorLabel, type ConnectorManifestRecord, type ConnectorManifestTransition, type ConnectorRegistryItem } from "@/lib/connectors-demo";
import { formatDateTime } from "@/lib/format";
import { deriveGovernedActor } from "@/lib/governed-action";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { parseConnectorManifestRecord } from "@/lib/runtime-contracts/connectors";
import { strings } from "@/lib/strings";
import { OPERATIONS_API_PREFIX, buildTenantScopedPath } from "@/lib/tenant-scope";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";

/*
 * Lifecycle control for one persisted connector manifest. The API owns every
 * rule (transition legality, scopes, live-enablement gates); this panel makes
 * the current state, what it allows, and the next safe transition legible —
 * activation and deprecation are one click, while live enablement asks for
 * its approval/policy/credential evidence up front.
 */

const LIFECYCLE_ENDPOINT_BASE = `${OPERATIONS_API_PREFIX}/connectors/manifests`;

type TransitionKind = "activate" | "enable_live" | "deprecate";

const TARGET_BY_KIND: Record<TransitionKind, string> = {
  activate: "active_preview",
  enable_live: "active_live",
  deprecate: "deprecated",
};

function transitionReason(kind: TransitionKind): string {
  const copy = strings.connectors.lifecycle;
  if (kind === "activate") {
    return copy.activateReason;
  }
  return kind === "deprecate" ? copy.deprecateReason : copy.enableLiveReason;
}

function lifecycleStatusClass(status: string): string {
  if (status === "active_live") {
    return "signal-ready";
  }
  if (status === "active_preview") {
    return "signal-watch";
  }
  if (status === "registered_preview_only") {
    return "status-checking";
  }
  return "signal-action-required";
}

/**
 * Operator copy per API failure class. Scope denials are keyed by the API's
 * `reason` so the two lifecycle grants stay distinguishable; every other
 * denial falls back to status-class copy, and unknown reasons land on the
 * same generic 403 line instead of inventing a claim about the session.
 */
function lifecycleErrorCopy(error: AxisOperatorError): string {
  const copy = strings.connectors.lifecycle;
  if (error.reason === "missing_manifest_lifecycle_scope") {
    return copy.deniedLifecycleScope;
  }
  if (error.reason === "missing_manifest_live_scope") {
    return copy.deniedLiveScope;
  }
  if (error.status === 403) {
    return copy.forbidden;
  }
  if (error.status === 422) {
    return copy.validationFailed;
  }
  if (error.status === 409) {
    return copy.conflict;
  }
  return copy.genericError;
}

function parseEvidenceRefs(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function RequirementRow({ met, label }: { met: boolean; label: string }) {
  const copy = strings.connectors.lifecycle;
  return (
    <li className="flex min-w-0 flex-wrap items-center justify-between gap-2">
      <span className="min-w-0 break-words text-sm text-ink">{label}</span>
      <span className={`status-pill ${met ? "signal-ready" : "signal-action-required"}`}>
        {met ? copy.requirementMet : copy.requirementUnmet}
      </span>
    </li>
  );
}

const MANIFEST_AUDIT_EVENT_PREFIX = "connector.manifest.";

/** Calm operator label for a revision's content event; unknown types stay honest. */
function revisionEventLabel(auditEventType: string): string | null {
  const copy = strings.connectors.lifecycle.history;
  if (!auditEventType.startsWith(MANIFEST_AUDIT_EVENT_PREFIX)) {
    return copy.unknownEvent;
  }
  const shortType = auditEventType.slice(MANIFEST_AUDIT_EVENT_PREFIX.length);
  // Lifecycle transitions mutate the current revision in place; they are
  // narrated by the transition ledger below, never as revision content.
  if (shortType === "lifecycle_transitioned" || shortType === "live_enabled") {
    return null;
  }
  return (copy.events as Record<string, string>)[shortType] ?? copy.unknownEvent;
}

/** Operator label for one recorded lifecycle transition. */
function transitionEventLabel(auditEventType: string, targetStatus: string): string {
  const copy = strings.connectors.lifecycle.transitions;
  if (auditEventType !== "connector.manifest.live_enabled"
    && auditEventType !== "connector.manifest.lifecycle_transitioned") {
    return copy.unknownEvent;
  }
  return (copy.events as Record<string, string>)[targetStatus] ?? copy.unknownEvent;
}

function HistoryRow({ revision }: { revision: ConnectorManifestRecord }) {
  const contentLabel = revisionEventLabel(revision.audit_event_type);
  return (
    <li className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <span className={`status-pill ${lifecycleStatusClass(revision.status)}`}>
        {formatConnectorLabel(revision.status)}
      </span>
      <span className="font-mono text-xs text-muted">r{revision.revision_number}</span>
      {contentLabel ? (
        <span className="min-w-0 break-words text-sm text-muted">
          {contentLabel}
        </span>
      ) : null}
      <span className="text-xs text-muted">{formatDateTime(revision.created_at)}</span>
    </li>
  );
}

function TransitionRow({ transition }: { transition: ConnectorManifestTransition }) {
  return (
    <li className="grid min-w-0 gap-1">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <span className={`status-pill ${lifecycleStatusClass(transition.target_status)}`}>
          {formatConnectorLabel(transition.target_status)}
        </span>
        <span className="min-w-0 break-words text-sm text-muted">
          {transitionEventLabel(transition.audit_event_type, transition.target_status)}
        </span>
        <span className="min-w-0 break-words font-mono text-xs text-muted">
          {transition.transitioned_by}
        </span>
        <span className="text-xs text-muted">{formatDateTime(transition.transitioned_at)}</span>
      </div>
      <p className="m-0 text-xs leading-snug break-words text-muted">
        {transition.from_status === transition.target_status
          ? transition.transition_reason
          : `${formatConnectorLabel(transition.from_status)} → ${formatConnectorLabel(transition.target_status)}: ${transition.transition_reason}`}
      </p>
    </li>
  );
}

export function ConnectorLifecyclePanel({
  connector,
  identitySession,
  onTransitioned,
  revisions,
  transitions,
  tenantId,
}: {
  connector: ConnectorRegistryItem;
  identitySession: IdentitySessionReadModel | null;
  onTransitioned: () => void;
  /** Persisted revisions from the detail envelope, newest first. */
  revisions?: ConnectorManifestRecord[];
  /** Governed lifecycle transitions from the detail envelope, newest first. */
  transitions?: ConnectorManifestTransition[];
  tenantId: string;
}) {
  const copy = strings.connectors.lifecycle;
  const { push } = useToast();
  const { session } = useOidcConsoleSession();
  const { actorId, ssoBlocked } = deriveGovernedActor(
    identitySession,
    "connector-console-operator",
  );

  const [pendingKind, setPendingKind] = useState<TransitionKind | null>(null);
  const [confirmingDeprecate, setConfirmingDeprecate] = useState(false);
  const [liveOpen, setLiveOpen] = useState(false);
  const [evidenceText, setEvidenceText] = useState("");
  const [error, setError] = useState<AxisOperatorError | null>(null);

  const connectorId = connector.manifest.connector_id;
  // Registry-reference entries carry no persisted row, so there is nothing to
  // transition; only API-backed manifests expose lifecycle controls here.
  const status = connector.persisted_manifest?.status ?? null;
  const targets = manifestLifecycleTargets(status);
  const canActivate = targets.includes("active_preview");
  const canEnableLive = targets.includes("active_live");
  const canDeprecate = targets.includes("deprecated");
  const requirements = liveEnablementRequirements(connector);
  const liveRequirementsMet = allLiveRequirementsMet(requirements);
  const evidenceRefs = parseEvidenceRefs(evidenceText);
  const missingEvidence = missingLiveEvidenceCategories(evidenceRefs);

  async function transition(kind: TransitionKind) {
    if (pendingKind !== null || ssoBlocked) {
      return;
    }
    setPendingKind(kind);
    setError(null);
    const path = buildTenantScopedPath(
      `${LIFECYCLE_ENDPOINT_BASE}/${encodeURIComponent(connectorId)}/lifecycle`,
      tenantId,
    );
    try {
      const response = await axisFetch(path, {
        method: "POST",
        session,
        body: buildManifestLifecycleRequest({
          tenantId,
          actorId,
          targetStatus: TARGET_BY_KIND[kind],
          reason: transitionReason(kind),
          evidenceRefs: kind === "enable_live" ? evidenceRefs : [],
        }),
      });
      const requestId = axisResponseRequestId(response);
      const body = await readAxisResponseBody(response);
      if (!response.ok) {
        throw new AxisApiError(path, response.status, { body, requestId });
      }
      const record = parseConnectorManifestRecord(body);
      if (record.tenant_id !== tenantId || record.connector_id !== connectorId) {
        throw new AxisApiDecodeError(
          path,
          "Lifecycle response did not match the selected connector.",
          { requestId },
        );
      }
      push({
        title: copy.successToast.title,
        detail: copy.successToast.detail,
        tone: "positive",
      });
      setLiveOpen(false);
      setEvidenceText("");
      setConfirmingDeprecate(false);
      onTransitioned();
    } catch (caught) {
      const operatorError = toAxisOperatorError(caught, copy.genericError);
      setError({ ...operatorError, message: lifecycleErrorCopy(operatorError) });
    } finally {
      setPendingKind(null);
    }
  }

  return (
    <section
      aria-label={copy.title}
      className="grid gap-3 border-t border-line/60 pt-4 dark:border-white/10"
    >
      <Eyebrow>{copy.eyebrow}</Eyebrow>
      <DetailGrid>
        <KeyValueRow label={copy.title}>
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            {status ? (
              <>
                <span className={`status-pill ${lifecycleStatusClass(status)}`}>
                  {formatConnectorLabel(status)}
                </span>
                <span className="min-w-0 break-words text-sm text-muted">
                  {copy.stateDetail[status as keyof typeof copy.stateDetail] ?? copy.unknownState}
                </span>
              </>
            ) : (
              <span className="text-sm text-muted">{copy.unknownState}</span>
            )}
          </span>
        </KeyValueRow>
      </DetailGrid>

      {revisions && revisions.length > 0 ? (
        <div className="grid gap-1.5">
          <Eyebrow>{copy.history.title}</Eyebrow>
          {/* How each persisted revision stands right now, newest first;
              content changes live here, activation changes in the transition
              trail below. */}
          <ol aria-label={copy.history.title} className="m-0 grid list-none gap-1.5 p-0">
            {revisions.map((revision) => (
              <HistoryRow key={revision.revision_number} revision={revision} />
            ))}
          </ol>
        </div>
      ) : null}

      {transitions && transitions.length > 0 ? (
        <div className="grid gap-1.5">
          <Eyebrow>{copy.transitions.title}</Eyebrow>
          {/* The API's per-connector transition projection, newest first:
              every governed activation change with its actor and reason. */}
          <ol aria-label={copy.transitions.title} className="m-0 grid list-none gap-2 p-0">
            {transitions.map((transition) => (
              <TransitionRow
                key={transition.audit_event_id}
                transition={transition}
              />
            ))}
          </ol>
        </div>
      ) : null}

      {!ssoBlocked && (canActivate || canEnableLive || canDeprecate) ? (
        <div className="flex flex-wrap items-center gap-2">
          {canActivate ? (
            <Button
              loading={pendingKind === "activate"}
              disabled={pendingKind !== null}
              onClick={() => void transition("activate")}
            >
              {pendingKind === "activate" ? copy.activating : copy.activateAction}
            </Button>
          ) : null}
          {canEnableLive ? (
            <Button
              aria-expanded={liveOpen}
              variant="secondary"
              onClick={() => setLiveOpen((open) => !open)}
            >
              {liveOpen ? strings.connectors.wizard.cancel : copy.enableLiveAction}
            </Button>
          ) : null}
          {canDeprecate && !confirmingDeprecate ? (
            <Button variant="ghost" onClick={() => setConfirmingDeprecate(true)}>
              {copy.deprecateAction}
            </Button>
          ) : null}
          {confirmingDeprecate ? (
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted">{copy.deprecatedHint}</span>
              <Button
                loading={pendingKind === "deprecate"}
                disabled={pendingKind !== null}
                variant="destructive"
                onClick={() => void transition("deprecate")}
              >
                {pendingKind === "deprecate" ? copy.deprecating : copy.confirmDeprecate}
              </Button>
              <Button variant="ghost" onClick={() => setConfirmingDeprecate(false)}>
                {strings.connectors.wizard.cancel}
              </Button>
            </span>
          ) : null}
        </div>
      ) : null}

      {ssoBlocked ? (
        <p className="m-0 flex items-center gap-2 text-sm text-muted" role="status">
          <ShieldCheck aria-hidden="true" className="shrink-0 text-signal" size={15} />
          {copy.ssoGate}
        </p>
      ) : null}

      {liveOpen && canEnableLive ? (
        <div className="grid gap-3 rounded-2xl border border-line p-4 dark:border-white/10">
          <div className="grid gap-1">
            <p className="m-0 text-sm font-medium text-ink">{copy.enableLiveTitle}</p>
            <p className="m-0 text-sm leading-snug text-muted">{copy.enableLiveDetail}</p>
          </div>
          <ul aria-label={copy.requirements.title} className="m-0 grid list-none gap-1.5 p-0">
            <RequirementRow
              label={copy.requirements.liveSyncMode}
              met={requirements.liveSyncMode.met}
            />
            <RequirementRow
              label={copy.requirements.liveOperationsAllowed}
              met={requirements.liveOperationsAllowed.met}
            />
            <RequirementRow
              label={copy.requirements.egressBoundaryNamed}
              met={requirements.egressBoundaryNamed.met}
            />
          </ul>
          <Field label={copy.evidenceLabel}>
            <Textarea
              className="min-h-24 font-mono text-xs"
              onChange={(event) => setEvidenceText(event.target.value)}
              placeholder={copy.evidencePlaceholder}
              value={evidenceText}
            />
          </Field>
          <p className="m-0 text-xs leading-snug text-muted">{copy.evidenceDetail}</p>
          {evidenceRefs.length > 0 && missingEvidence.length > 0 ? (
            <p className="m-0 text-xs leading-snug" role="status">
              {copy.evidenceMissing(missingEvidence)}
            </p>
          ) : null}
          <div>
            <Button
              disabled={
                pendingKind !== null
                || !liveRequirementsMet
                || missingEvidence.length > 0
              }
              loading={pendingKind === "enable_live"}
              onClick={() => void transition("enable_live")}
            >
              {pendingKind === "enable_live" ? copy.enablingLive : copy.enableLiveTitle}
            </Button>
          </div>
        </div>
      ) : null}

      {error ? <InlineOperatorError error={error} /> : null}
    </section>
  );
}
