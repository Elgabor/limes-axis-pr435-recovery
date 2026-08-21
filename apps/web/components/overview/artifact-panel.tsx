"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { AlertTriangle, FileCheck2, ShieldCheck } from "lucide-react";

import { Card } from "@/components/ui/card";
import { ErrorPanel, LoadingPanel } from "@/components/ui/states";
import {
  axisFetchParsedJson,
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import { buildOidcAuthorizeUrl } from "@/lib/oidc-session";
import {
  buildOperationsArtifactRequest,
  getOperationsArtifactActionState,
  operationsArtifactHeadline,
  operationsArtifactRecordId,
  OPERATIONS_ARTIFACT_ACTIONS,
  type OperationsArtifactKind,
  type OperationsArtifactResponse,
} from "@/lib/operations-artifacts";
import {
  platformStatusClass,
  type IdentitySessionReadModel,
  type ManufacturingOperationsSnapshot,
} from "@/lib/platform-overview";
import { strings } from "@/lib/strings";
import {
  parseIdentitySessionReadModel,
  parseOperationsArtifactResponse,
} from "@/lib/runtime-contracts/overview";
import { useAxisQuery } from "@/lib/use-axis-query";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useConsole } from "@/providers/console-provider";

import { buildAuditEventHref } from "@/lib/audit-demo";
import { PanelHeader, StatusDot, type OverviewQuery } from "./overview-shared";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

/*
 * Compact governed-evidence generation panel: one card, one action row, the
 * persisted result inline. The SSO banner only renders when the identity API
 * has confirmed the browser session is unauthenticated — a missing identity
 * endpoint just leaves the actions disabled with their scope reason.
 */

export const SNAPSHOT_ENDPOINT = `${OPERATIONS_API_PREFIX}/operations/snapshot`;

const ACTION_ICONS: Record<string, typeof FileCheck2> = {
  daily_brief: FileCheck2,
  supplier_delay: AlertTriangle,
};

export function ArtifactPanel({
  snapshot,
  onArtifactCommitted,
}: {
  snapshot: OverviewQuery<ManufacturingOperationsSnapshot>;
  onArtifactCommitted: () => void;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { apiBaseUrl } = useConsole();
  const { session } = useOidcConsoleSession();
  const { data: identitySession, isUnavailable: identitySessionUnavailable } =
    useAxisQuery<IdentitySessionReadModel>("/identity/session", {
      parse: parseIdentitySessionReadModel,
    });
  const [pendingKind, setPendingKind] = useState<OperationsArtifactKind | null>(null);
  const [artifact, setArtifact] = useState<{
    actionLabel: string;
    response: OperationsArtifactResponse;
  } | null>(null);
  const [error, setError] = useState<AxisOperatorError | null>(null);
  const copy = strings.overview.artifact;

  if (!snapshot.data) {
    if (snapshot.source === "loading") {
      return <LoadingPanel layout="detail" />;
    }

    return (
      <ErrorPanel
        detail={copy.error.detail}
        endpoint={SNAPSHOT_ENDPOINT}
        reference={snapshot.errorRequestId ?? undefined}
        title={copy.error.title}
      />
    );
  }

  const operationsSnapshot = snapshot.data;
  const sessionStatus = identitySession?.authenticated ? "ready" : "watch";
  const sessionLabel = identitySession?.authenticated
    ? "API-verified actor"
    : identitySessionUnavailable
      ? "Identity API required"
      : "OIDC session required";
  const returnTo = `${pathname}${searchParams.toString() ? `?${searchParams.toString()}` : ""}`;
  const signInUrl = buildOidcAuthorizeUrl(apiBaseUrl, returnTo);
  // The SSO banner needs a confirmed unauthenticated session, not a missing
  // identity endpoint.
  const showSsoGate = identitySession !== null && !identitySession.authenticated;

  async function submitArtifact(kind: OperationsArtifactKind) {
    setPendingKind(kind);
    setError(null);

    try {
      const request = buildOperationsArtifactRequest({
        kind,
        identitySession,
        snapshot: operationsSnapshot,
      });
      const response = await axisFetchParsedJson<OperationsArtifactResponse>(
        request.endpoint,
        parseOperationsArtifactResponse,
        { method: "POST", session, body: request.body },
      );

      setArtifact({ actionLabel: request.action.label, response });
      onArtifactCommitted();
    } catch (caught) {
      setError(toAxisOperatorError(
        caught,
        "Axis could not persist the operations artifact.",
      ));
    } finally {
      setPendingKind(null);
    }
  }

  return (
    <Card className="grid content-start gap-4">
      <PanelHeader
        aside={
          <span className={`status-pill ${platformStatusClass(sessionStatus)}`}>
            {sessionLabel}
          </span>
        }
        eyebrow={copy.eyebrow}
        title={copy.title}
      />
      <p className="m-0 max-w-3xl text-sm text-muted">{copy.description}</p>

      {showSsoGate ? (
        <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-signal/30 bg-tint-50 p-4 dark:bg-signal/10">
          <ShieldCheck className="shrink-0 text-signal" size={18} />
          <div className="grid min-w-0 flex-1 gap-0.5">
            <p className="m-0 text-sm font-medium text-ink">{copy.ssoTitle}</p>
            <p className="m-0 text-xs text-muted">{copy.ssoDetail}</p>
          </div>
          <a
            className="inline-flex items-center gap-2 rounded-full bg-navy px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-signal dark:bg-signal dark:hover:bg-white dark:hover:text-navy"
            href={signInUrl}
          >
            {copy.signIn}
          </a>
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2" role="group" aria-label="Governed artifact actions">
        {OPERATIONS_ARTIFACT_ACTIONS.map((action) => {
          const state = getOperationsArtifactActionState(action.kind, identitySession);
          const pending = pendingKind === action.kind;
          const Icon = ACTION_ICONS[action.kind] ?? ShieldCheck;

          return (
            <button
              aria-describedby={`${action.kind}-artifact-state`}
              className="inline-flex items-center gap-2 rounded-full border border-line px-4 py-2 text-xs font-medium text-ink transition-colors enabled:hover:border-signal/50 enabled:hover:text-signal disabled:cursor-not-allowed disabled:opacity-55 dark:border-white/15"
              disabled={!state.canRun || Boolean(pendingKind)}
              key={action.kind}
              onClick={() => void submitArtifact(action.kind)}
              title={state.reason ?? action.description}
              type="button"
            >
              <Icon aria-hidden="true" size={14} />
              {pending ? "Persisting..." : action.label}
              <span className="sr-only" id={`${action.kind}-artifact-state`}>
                {state.reason ?? action.description}
              </span>
            </button>
          );
        })}
      </div>

      {artifact ? (
        <div
          className="flex flex-wrap items-start gap-3 rounded-2xl border border-positive/35 bg-positive/8 p-4"
          role="status"
        >
          <StatusDot status="ready" />
          <div className="grid min-w-0 flex-1 gap-1">
            <p className="m-0 font-mono text-sm break-words text-ink">
              {artifact.actionLabel} / {operationsArtifactRecordId(artifact.response)}
            </p>
            <p className="m-0 text-xs text-muted">{operationsArtifactHeadline(artifact.response)}</p>
            <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-muted">
              <span>{artifact.response.idempotent_replay ? "Idempotent replay" : "Created"}</span>
              <span>{artifact.response.source_record_ids.length} source records</span>
              <span>{artifact.response.audit_event_type}</span>
            </div>
          </div>
          {artifact.response.audit_event_id ? (
            <Link
              className="font-mono text-xs tracking-[0.12em] text-signal uppercase hover:underline"
              href={buildAuditEventHref(artifact.response.audit_event_id)}
            >
              Open audit
            </Link>
          ) : null}
        </div>
      ) : null}

      {error ? (
        <ErrorPanel
          detail={error.message}
          reference={error.requestId ?? undefined}
          title="Artifact persistence failed"
        />
      ) : null}
    </Card>
  );
}
