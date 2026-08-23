"use client";

import { LogOut, MonitorSmartphone, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { ErrorPanel } from "@/components/ui/states";
import { ConsolePage } from "@/components/console-page";
import {
  toAxisOperatorError,
  type AxisOperatorError,
} from "@/lib/axis-api";
import { formatNumber } from "@/lib/format";
import {
  canListTenantSessions,
  formatSessionInstant,
  identitySessionsPath,
  isRevocableSessionStatus,
  revokeIdentitySession,
  sessionStatusClass,
  sessionStatusLabel,
  type IdentityBrowserSessionList,
  type IdentityBrowserSessionRecord,
} from "@/lib/identity-sessions";
import { buildOidcAuthorizeUrl, buildOidcLogoutUrl } from "@/lib/oidc-session";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { parseIdentityBrowserSessionList } from "@/lib/runtime-contracts/identity";
import {
  deriveSourceState,
  PROVENANCE_NOT_APPLICABLE,
  type SourceState,
} from "@/lib/source-state";
import { useAxisQuery } from "@/lib/use-axis-query";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useIdentitySession } from "@/lib/use-identity-session";
import { useConsole } from "@/providers/console-provider";

const SESSIONS_ROUTE = "/settings/sessions";
const SESSION_ENDPOINTS = "/identity/session /identity/sessions";

function revokeOperatorError(caught: unknown): AxisOperatorError {
  const failure = toAxisOperatorError(caught, "Axis could not revoke the session.");
  if (failure.status === 403) {
    return {
      ...failure,
      message: "Axis denied the revocation. Managing other actors' sessions requires identity:sessions:admin.",
    };
  }
  if (failure.status === 404) {
    return {
      ...failure,
      message: "Axis could not find that session in this tenant. Refresh the list.",
    };
  }
  return failure;
}

/**
 * `ConsolePage.sourceLabel` is a plain string (it pre-dates `SourcePill` and
 * other callers we don't own still pass literal text), so the source pill it
 * renders can't carry real tone here — text is the only channel available.
 * This mirrors `SourcePill`'s own wording so the copy stays consistent with
 * consoles that render the full component.
 */
function sourceStateLabel(state: SourceState, subject: string): string {
  if (state === "live") {
    return `Live ${subject}`;
  }
  if (state === "stale") {
    return `Stale ${subject}`;
  }
  if (state === "unavailable") {
    return `${subject} unavailable`;
  }
  return `Loading ${subject}`;
}

function SessionRow({
  record,
  showActor,
  pending,
  logoutUrl,
  onRevoke,
}: {
  record: IdentityBrowserSessionRecord;
  showActor: boolean;
  pending: boolean;
  logoutUrl: string;
  onRevoke: (record: IdentityBrowserSessionRecord) => void;
}) {
  const revocable = isRevocableSessionStatus(record.status);

  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10" aria-label={`Browser session ${record.session_ref}`}>
      <div>
        <p className="m-0 font-medium text-ink break-words">
          {showActor ? record.actor_id : `Session ${record.session_ref.slice(0, 8)}`}
          {record.current ? " (this browser)" : ""}
        </p>
        <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
          Created {formatSessionInstant(record.created_at)} · Last seen{" "}
          {formatSessionInstant(record.last_seen_at)} · Expires{" "}
          {formatSessionInstant(record.expires_at)} · Refreshes{" "}
          {formatNumber(record.refresh_count)}
        </p>
        {record.revoked_at ? (
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
            Revoked {formatSessionInstant(record.revoked_at)}
            {record.revocation_reason ? ` (${record.revocation_reason.replaceAll("_", " ")})` : ""}
          </p>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <span className={`status-pill ${sessionStatusClass(record.status)}`}>
          {record.current ? "Current" : sessionStatusLabel(record.status)}
        </span>
        {revocable ? (
          record.current ? (
            <a
              className="inline-flex items-center justify-center gap-2 rounded-full border border-mist bg-surface px-4 py-2 text-sm font-medium text-ink transition-all duration-300 select-none hover:border-signal/50 hover:text-signal disabled:cursor-not-allowed disabled:opacity-55 dark:border-white/20 dark:hover:border-signal/60"
              href={logoutUrl}
              title="Revoking this browser's session signs you out through the identity provider"
            >
              <LogOut size={15} />
              Sign out
            </a>
          ) : (
            <button
              className="inline-flex items-center justify-center gap-2 rounded-full border border-mist bg-surface px-4 py-2 text-sm font-medium text-ink transition-all duration-300 select-none hover:border-signal/50 hover:text-signal disabled:cursor-not-allowed disabled:opacity-55 dark:border-white/20 dark:hover:border-signal/60"
              disabled={pending}
              onClick={() => onRevoke(record)}
              type="button"
            >
              {pending ? "Revoking" : "Revoke"}
            </button>
          )
        ) : null}
      </div>
    </div>
  );
}

function SignedOutPanel({ signInUrl }: { signInUrl: string }) {
  return (
    <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5 flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="eyebrow m-0">Signed out</p>
        <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">No authenticated operator session</h2>
        <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
          Session management lists only API-verified sessions. Sign in with the API-owned OIDC
          browser session, or attach a bearer token from the account panel, before managing
          sessions.
        </p>
      </div>
      <a className="inline-flex items-center justify-center gap-2 rounded-full border border-mist bg-surface px-4 py-2 text-sm font-medium text-ink transition-all duration-300 select-none hover:border-signal/50 hover:text-signal disabled:cursor-not-allowed disabled:opacity-55 dark:border-white/20 dark:hover:border-signal/60" href={signInUrl}>
        <ShieldCheck size={16} />
        Sign in with SSO
      </a>
    </section>
  );
}

function SessionListPanel({
  identitySession,
  logoutUrl,
}: {
  identitySession: IdentitySessionReadModel;
  logoutUrl: string;
}) {
  const { session } = useOidcConsoleSession();
  const { triggerRefresh } = useConsole();
  const adminCapable = canListTenantSessions(identitySession.scopes);
  const [tenantWide, setTenantWide] = useState(false);
  const listTenantWide = adminCapable && tenantWide;
  const sessions = useAxisQuery<IdentityBrowserSessionList>(
    identitySessionsPath(listTenantWide),
    { parse: parseIdentityBrowserSessionList },
  );
  // A Set of in-flight session refs, not a single id: revoking two sessions
  // back to back (a slow one, then a fast one) must not let the fast one's
  // completion clear the pending flag for the still in-flight slow one and
  // re-enable its button for a double submit.
  const [pendingSessionRefs, setPendingSessionRefs] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const [revokeError, setRevokeError] = useState<AxisOperatorError | null>(null);

  async function revokeSession(record: IdentityBrowserSessionRecord) {
    setPendingSessionRefs((current) => new Set(current).add(record.session_ref));
    setRevokeError(null);
    try {
      await revokeIdentitySession(record.session_ref, { session });
      triggerRefresh();
    } catch (caught) {
      setRevokeError(revokeOperatorError(caught));
    } finally {
      setPendingSessionRefs((current) => {
        const next = new Set(current);
        next.delete(record.session_ref);
        return next;
      });
    }
  }

  if (sessions.isUnavailable && !sessions.data) {
    return (
      <ErrorPanel
        detail="Live session data requires the Axis identity session APIs. Local fallback session records are disabled."
        endpoint={identitySessionsPath(listTenantWide)}
        reference={sessions.errorRequestId ?? undefined}
        title="Sessions API unavailable"
      />
    );
  }

  const list = sessions.data;

  return (
    <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow m-0">Browser sessions</p>
          <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">
            {listTenantWide ? "Tenant-wide sessions" : "Your sessions"}
          </h2>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {adminCapable ? (
            <button
              className="inline-flex items-center justify-center gap-2 rounded-full border border-mist bg-surface px-4 py-2 text-sm font-medium text-ink transition-all duration-300 select-none hover:border-signal/50 hover:text-signal disabled:cursor-not-allowed disabled:opacity-55 dark:border-white/20 dark:hover:border-signal/60"
              onClick={() => setTenantWide((value) => !value)}
              type="button"
            >
              {listTenantWide ? "Show my sessions" : "Show tenant sessions"}
            </button>
          ) : null}
          <span className={`status-pill ${list ? "signal-ready" : "signal-watch"}`}>
            {list ? `${formatNumber(list.sessions.length)} recorded` : "Loading sessions"}
          </span>
        </div>
      </div>

      {sessions.isUnavailable && list ? (
        <p className="m-0 text-sm text-warning" role="status">
          Live refresh failed. Showing the last validated session data.
        </p>
      ) : null}

      {list ? (
        <div className="grid min-w-0 gap-2.5">
          {list.sessions.length > 0 ? (
            list.sessions.map((record) => (
              <SessionRow
                key={record.session_ref}
                logoutUrl={logoutUrl}
                onRevoke={(target) => void revokeSession(target)}
                pending={pendingSessionRefs.has(record.session_ref)}
                record={record}
                showActor={listTenantWide}
              />
            ))
          ) : (
            <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10">
              <div>
                <p className="m-0 font-medium text-ink break-words">No browser sessions recorded</p>
                <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                  Axis has no persisted OIDC browser sessions for this actor. Bearer-token
                  bridges do not create cookie sessions; sign in with SSO to start one.
                </p>
              </div>
              <span className="status-pill signal-ready">Empty</span>
            </div>
          )}
        </div>
      ) : (
        <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">Loading persisted session records from the Axis API.</p>
      )}

      {revokeError ? (
        <div role="alert">
          <ErrorPanel
            detail={revokeError.message}
            reference={revokeError.requestId ?? undefined}
            title="Session revocation failed"
          />
        </div>
      ) : null}

      {list?.notes.length ? (
        <div className="flex min-w-0 flex-wrap gap-2">
          {list.notes.map((note) => (
            <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors enabled:cursor-pointer aria-pressed:border-signal aria-pressed:bg-signal/10 aria-pressed:text-signal dark:border-white/15 dark:bg-white/5" key={note}>
              {note}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function SessionSecurityConsole() {
  const { apiBaseUrl } = useConsole();
  const identity = useIdentitySession();
  const identitySession = identity.data;
  const signInUrl = buildOidcAuthorizeUrl(apiBaseUrl, SESSIONS_ROUTE);
  const logoutUrl = buildOidcLogoutUrl(apiBaseUrl, SESSIONS_ROUTE);

  return (
    <ConsolePage
      controls={
        identitySession?.authenticated && identitySession.mode === "secure_oidc_cookie" ? (
          <a className="inline-flex items-center justify-center gap-2 rounded-full border border-mist bg-surface px-4 py-2 text-sm font-medium text-ink transition-all duration-300 select-none hover:border-signal/50 hover:text-signal disabled:cursor-not-allowed disabled:opacity-55 dark:border-white/20 dark:hover:border-signal/60" href={logoutUrl}>
            <LogOut size={16} />
            Sign out
          </a>
        ) : undefined
      }
      eyebrow="Platform control"
      sourceLabel={sourceStateLabel(
        deriveSourceState(
          identity.source,
          Boolean(identitySession),
          PROVENANCE_NOT_APPLICABLE,
        ),
        "session security",
      )}
      subtitle="API-owned OIDC browser sessions with rotation, revocation and logout evidence."
      title="Session security"
    >
      {!identitySession ? (
        <ErrorPanel
          detail="Live session management requires the Axis identity APIs. Local fallback session records are disabled."
          endpoint={SESSION_ENDPOINTS}
          reference={identity.errorRequestId ?? undefined}
          title="Session API unavailable"
        />
      ) : !identitySession.authenticated ? (
        <SignedOutPanel signInUrl={signInUrl} />
      ) : (
        <>
          <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
            <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
              <div>
                <p className="eyebrow m-0">Operator session</p>
                <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">API-verified identity</h2>
              </div>
              <span className="status-pill signal-ready">
                <MonitorSmartphone size={15} />
                {identitySession.mode === "secure_oidc_cookie" ? "Cookie session" : "Bearer session"}
              </span>
            </div>
            <div className="mb-3.5 grid gap-2.5 sm:grid-cols-2 [&>span]:grid [&>span]:min-w-0 [&>span]:gap-1 [&>span]:rounded-xl [&>span]:border [&>span]:border-line/60 [&>span]:bg-ink/3 [&>span]:p-2.5 dark:[&>span]:border-white/10 dark:[&>span]:bg-white/4 [&_small]:text-[11px] [&_small]:font-medium [&_small]:tracking-wide [&_small]:uppercase [&_small]:text-muted [&_strong]:min-w-0 [&_strong]:break-words [&_strong]:text-[13px] [&_strong]:leading-tight [&_strong]:text-ink">
              <span>
                <small>Actor</small>
                <strong>{identitySession.actor_id ?? "Unknown"}</strong>
              </span>
              <span>
                <small>Tenant</small>
                <strong>{identitySession.tenant_id ?? "Unknown"}</strong>
              </span>
              <span>
                <small>Session boundary</small>
                <strong>{identitySession.session_boundary.replaceAll("_", " ")}</strong>
              </span>
              <span>
                <small>Scopes</small>
                <strong>{formatNumber(identitySession.scopes.length)}</strong>
              </span>
            </div>
            {identitySession.mode !== "secure_oidc_cookie" ? (
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                This console is attached through the developer bearer bridge. Revocation below
                applies to persisted browser cookie sessions; clear the bearer bridge from the
                account panel to detach this console.
              </p>
            ) : null}
          </section>
          <SessionListPanel identitySession={identitySession} logoutUrl={logoutUrl} />
        </>
      )}
    </ConsolePage>
  );
}
