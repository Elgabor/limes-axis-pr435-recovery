"use client";

import { useState } from "react";
import { Layers } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { InlineOperatorError } from "@/components/ui/inline-operator-error";
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
  buildSourceActivationRequest,
  SOURCE_ACTIVATION_SCOPE,
} from "@/lib/connectors-console";
import { safeRandomUuid } from "@/lib/ids";
import {
  parseSourceActivationOutcome,
  type SourceBindingView,
} from "@/lib/runtime-contracts/connectors";
import { strings } from "@/lib/strings";
import { OPERATIONS_API_PREFIX, buildTenantScopedPath } from "@/lib/tenant-scope";
import { useConsole } from "@/providers/console-provider";
import { deriveGovernedActor } from "@/lib/governed-action";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";

/*
 * Progressive activation step for tables the operator just discovered. The
 * API owns every gate; this section asks only for what activation genuinely
 * needs (a governance reason) while reusing the lease/policy references the
 * operator already reviewed above. Success never claims ingestion: bindings
 * land as "pending ingestion".
 */

const ACTIVATION_ENDPOINT = `${OPERATIONS_API_PREFIX}/connectors/external-db/source-bindings`;

export type ActivationSelection = {
  resourceName: string;
  schemaFingerprint: string;
};

function activationErrorCopy(error: AxisOperatorError): string | null {
  const copy = strings.connectors.sourceActivation;
  if (error.status === 403) {
    return error.reason === `missing_scope:${SOURCE_ACTIVATION_SCOPE}`
      ? copy.deniedScope
      : copy.forbidden;
  }
  if (error.status === 404) {
    return copy.notFound;
  }
  if (
    error.status === 422
    || error.status === 409
  ) {
    const blockedCopy = copy.blocked as Record<string, string>;
    if (error.reason && blockedCopy[error.reason]) {
      return blockedCopy[error.reason];
    }
    return copy.genericError;
  }
  return copy.genericError;
}

export function ConnectorSourceActivationPanel({
  tenantId,
  identitySession,
  selections,
  refs,
  onActivated,
}: {
  tenantId: string;
  identitySession: IdentitySessionReadModel | null;
  selections: ActivationSelection[];
  refs: {
    connectionProfileId: string;
    credentialLeaseId: string;
    egressPolicyId: string;
  };
  onActivated: () => void;
}) {
  const copy = strings.connectors.sourceActivation;
  const { triggerRefresh } = useConsole();
  const { push } = useToast();
  const { session } = useOidcConsoleSession();
  const { actorId, ssoBlocked } = deriveGovernedActor(
    identitySession,
    "connector-console-operator",
  );
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [activated, setActivated] = useState<SourceBindingView[] | null>(null);
  const [error, setError] = useState<AxisOperatorError | null>(null);

  const reasonValid = reason.trim().length > 0;
  const referencesReady =
    refs.connectionProfileId.trim().length > 0
    && refs.credentialLeaseId.trim().length > 0
    && refs.egressPolicyId.trim().length > 0;

  async function run() {
    if (pending || !reasonValid || ssoBlocked) {
      return;
    }
    setPending(true);
    setError(null);
    const path = buildTenantScopedPath(ACTIVATION_ENDPOINT, tenantId);
    const body = buildSourceActivationRequest({
      tenantId,
      actorId,
      refs,
      reason: reason.trim(),
      activationToken: safeRandomUuid(),
      selections: selections.map((selection) => ({
        bindingId: `binding_console_${safeRandomUuid().replaceAll("-", "")}`,
        resourceName: selection.resourceName,
        expectedSchemaFingerprint: selection.schemaFingerprint,
      })),
    });
    try {
      const response = await axisFetch(path, { method: "POST", session, body });
      const requestId = axisResponseRequestId(response);
      const responseBody = await readAxisResponseBody(response);
      if (!response.ok) {
        throw new AxisApiError(path, response.status, { body: responseBody, requestId });
      }
      const outcome = parseSourceActivationOutcome(responseBody);
      setActivated(outcome.bindings);
      setReason("");
      onActivated();
      triggerRefresh();
      const replayedCount = outcome.bindings.filter(
        (view) => view.outcome === "replayed",
      ).length;
      push({
        title: copy.successTitle(outcome.bindings.length),
        detail:
          replayedCount === outcome.bindings.length
            ? copy.replayedNote
            : copy.honestNote,
        tone: "positive",
      });
    } catch (caught) {
      if (
        caught instanceof AxisApiError
        || caught instanceof AxisApiDecodeError
      ) {
        const operatorError = toAxisOperatorError(caught, copy.genericError);
        setError({ ...operatorError, message: activationErrorCopy(operatorError) ?? copy.genericError });
      } else {
        setError({ code: null, reason: null, message: copy.genericError, requestId: null, status: null });
      }
    } finally {
      setPending(false);
    }
  }

  if (activated !== null) {
    return (
      <section
        aria-label={copy.title}
        className="grid gap-2 rounded-2xl border border-line px-4 py-3 dark:border-white/10"
      >
        <p className="m-0 text-sm font-medium text-ink" role="status">
          {copy.successTitle(activated.length)}
        </p>
        <p className="m-0 text-sm leading-snug text-muted">{copy.honestNote}</p>
      </section>
    );
  }

  return (
    <section
      aria-label={copy.title}
      className="grid gap-3 rounded-2xl border border-line px-4 py-3 dark:border-white/10"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <Layers aria-hidden="true" className="shrink-0 text-signal" size={16} />
        <Eyebrow>{copy.title}</Eyebrow>
        <span className="text-xs text-muted">{copy.selectedCount(selections.length)}</span>
      </div>
      <p className="m-0 max-w-prose text-sm leading-snug text-muted">{copy.detail}</p>

      <ul className="m-0 grid list-none gap-1 p-0">
        {selections.map((selection) => (
          <li
            className="flex min-w-0 flex-wrap items-center justify-between gap-2"
            key={selection.resourceName}
          >
            <span className="min-w-0 break-all font-mono text-xs text-ink">
              {selection.resourceName}
            </span>
            <span
              className="font-mono text-xs text-muted"
              title={selection.schemaFingerprint}
            >
              {selection.schemaFingerprint.slice(0, 12)}
            </span>
          </li>
        ))}
      </ul>

      {!ssoBlocked ? (
        <>
          <label className="grid gap-1">
            <span className="text-sm font-medium text-ink">{copy.reasonLabel}</span>
            <Textarea
              aria-label={copy.reasonLabel}
              maxLength={600}
              onChange={(event) => setReason(event.target.value)}
              placeholder={copy.reasonPlaceholder}
              rows={2}
              value={reason}
            />
          </label>
          {reason.length === 0 ? (
            <p className="m-0 text-xs text-muted">{copy.reasonRequired}</p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              disabled={!reasonValid || !referencesReady || pending}
              loading={pending}
              onClick={() => void run()}
            >
              {pending ? copy.activating : copy.action(selections.length)}
            </Button>
          </div>
        </>
      ) : null}

      {error ? <InlineOperatorError error={error} /> : null}
    </section>
  );
}
