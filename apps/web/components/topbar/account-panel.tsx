"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { CircleHelp, KeyRound, LogOut, MonitorSmartphone, ShieldCheck } from "lucide-react";

import {
  PopoverHeader,
  commandClass,
  commandSecondaryClass,
  popoverClass,
  popoverRowClass,
  tagClass,
} from "@/components/topbar/panel-chrome";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/cn";
import {
  compactActorLabel,
  formatExpiry,
  identitySessionLabel,
  identitySessionTone,
  operatorInitials,
} from "@/lib/identity-format";
import {
  buildOidcAuthorizeUrl,
  buildOidcLogoutUrl,
  currentReturnPath,
} from "@/lib/oidc-session";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useConsole } from "@/providers/console-provider";

export function AccountPanel({
  className,
  identitySession,
  identitySessionUnavailable,
}: {
  className?: string;
  identitySession: IdentitySessionReadModel | null;
  identitySessionUnavailable: boolean;
}) {
  const { session, saveAccessToken, clearSession } = useOidcConsoleSession();
  const { apiBaseUrl, apiStatus } = useConsole();
  const [accessToken, setAccessToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [developerBridgeOpen, setDeveloperBridgeOpen] = useState(false);
  const verifiedCookieSession =
    identitySession?.authenticated && identitySession.mode === "secure_oidc_cookie";
  const authenticatedSession = identitySession?.authenticated || Boolean(session);
  const visibleScopes =
    identitySession?.scopes.length ? identitySession.scopes : session?.scopes ?? [];
  const authorizeUrl = buildOidcAuthorizeUrl(apiBaseUrl, currentReturnPath());
  const onboardingUrl = `${apiBaseUrl}/identity/oidc/onboarding`;

  function connectSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const token = accessToken.trim();
    if (!token) {
      setError("Paste a JWT bearer token to bridge an OIDC session.");
      return;
    }

    try {
      saveAccessToken(token);
      setAccessToken("");
      setError(null);
    } catch {
      setError("Token rejected. Axis expects a JWT with sub and axis_tenant claims.");
    }
  }

  function signOutWithIdentityProvider() {
    clearSession();
    window.location.assign(buildOidcLogoutUrl(apiBaseUrl, currentReturnPath()));
  }

  return (
    <section
      className={cn(className ?? popoverClass, "w-[min(390px,calc(100vw-32px))]")}
      aria-label="Operator account"
    >
      <PopoverHeader label="Operator">
        <span className={`status-pill ${identitySessionTone(identitySession)}`}>
          {identitySessionLabel(identitySession)}
        </span>
      </PopoverHeader>

      <div className="grid grid-cols-[42px_minmax(0,1fr)] items-center gap-3">
        <div className="grid size-[42px] place-items-center rounded-full border border-line bg-signal/15 text-xs font-extrabold text-ink dark:border-white/15">
          {operatorInitials(identitySession?.actor_id ?? undefined)}
        </div>
        <div>
          <p className="m-0 font-medium break-words text-ink">
            {identitySession?.authenticated && identitySession.actor_id
              ? compactActorLabel(identitySession.actor_id)
              : identitySessionUnavailable
                ? "Session API unavailable"
                : "Public evaluation operator"}
          </p>
          <p className="mx-0 mt-1 mb-0 text-sm leading-snug break-words text-muted">
            {identitySession?.authenticated && identitySession.tenant_id
              ? identitySession.tenant_id
              : identitySession?.session_boundary ?? "Identity session requires `/identity/session`."}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 [&>span]:min-w-0 [&>span]:rounded-xl [&>span]:border [&>span]:border-line/60 [&>span]:bg-ink/3 [&>span]:p-2.5 dark:[&>span]:border-white/10 dark:[&>span]:bg-white/4 [&_small]:block [&_small]:text-[11px] [&_small]:text-muted [&_strong]:mt-0.5 [&_strong]:block [&_strong]:min-w-0 [&_strong]:text-xs [&_strong]:leading-tight [&_strong]:break-words [&_strong]:text-ink">
        <span>
          <small>API</small>
          <strong>{apiBaseUrl}</strong>
        </span>
        <span>
          <small>API status</small>
          <strong>{apiStatus.label}</strong>
        </span>
        <span>
          <small>SSO posture</small>
          <strong>
            {identitySession
              ? identitySession.enterprise_sso_ready
                ? "Enterprise ready"
                : "Needs hardening"
              : "Unknown"}
          </strong>
        </span>
        <span>
          <small>Session expires</small>
          <strong>{formatExpiry(identitySession?.expires_at ?? undefined)}</strong>
        </span>
      </div>

      {identitySession ? (
        <div className="grid max-h-[188px] gap-2 overflow-y-auto overscroll-contain">
          {identitySession.capabilities.slice(0, 2).map((capability) => (
            <div className={popoverRowClass} key={capability}>
              <span aria-hidden="true" className="status-dot signal-ready" />
              <span>
                <strong>Capability</strong>
                <small>{capability}</small>
              </span>
            </div>
          ))}
          {identitySession.limitations.slice(0, 2).map((limitation) => (
            <div className={popoverRowClass} key={limitation}>
              <span aria-hidden="true" className="status-dot signal-watch" />
              <span>
                <strong>Limitation</strong>
                <small>{limitation}</small>
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="m-0 text-sm leading-snug text-muted">
          The account panel needs `/identity/session` before it can display an API-verified
          actor.
        </p>
      )}

      {verifiedCookieSession || session ? (
        <>
          <div className="flex max-h-[86px] min-w-0 flex-wrap gap-2 overflow-y-auto overscroll-contain">
            {visibleScopes.length > 0 ? (
              visibleScopes.slice(0, 6).map((scope) => (
                <span className={tagClass} key={scope}>
                  {scope}
                </span>
              ))
            ) : (
              <span className={tagClass}>
                {identitySession?.authenticated ? "No scopes in token" : "Awaiting API validation"}
              </span>
            )}
          </div>
          <Link className={commandSecondaryClass} href="/settings/sessions">
            <MonitorSmartphone size={16} />
            Manage sessions
          </Link>
          {verifiedCookieSession ? (
            <button
              className={commandClass}
              onClick={signOutWithIdentityProvider}
              type="button"
            >
              <LogOut size={16} />
              Sign out with identity provider
            </button>
          ) : (
            <button className={commandClass} onClick={clearSession} type="button">
              <LogOut size={16} />
              Clear bearer bridge
            </button>
          )}
        </>
      ) : (
        <div className="grid gap-2">
          <a className={commandClass} href={authorizeUrl}>
            <ShieldCheck size={16} />
            Sign in with SSO
          </a>
          <a
            className={commandSecondaryClass}
            href={onboardingUrl}
            rel="noreferrer"
            target="_blank"
          >
            <CircleHelp size={16} />
            Open SSO setup
          </a>
          <Collapsible onOpenChange={setDeveloperBridgeOpen} open={developerBridgeOpen}>
            <CollapsibleTrigger
              className="inline-flex min-h-6 cursor-pointer items-center justify-self-start text-xs text-muted underline underline-offset-2 transition-colors hover:text-ink"
              type="button"
            >
              Developer access
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-2 grid gap-2">
                <p className="m-0 text-xs leading-snug text-muted">
                  For local development against a non-SSO API.
                </p>
                {!authenticatedSession ? (
                  <form className="grid gap-2" onSubmit={connectSession}>
                    <label className="grid gap-1.5 text-xs font-semibold text-muted">
                      Developer bearer bridge
                      <Input
                        aria-invalid={Boolean(error)}
                        onChange={(event) => {
                          setAccessToken(event.target.value);
                          setError(null);
                        }}
                        placeholder="Paste JWT access token"
                        type="password"
                        value={accessToken}
                      />
                    </label>
                    {error ? (
                      <span className="text-xs font-semibold text-danger" role="alert">
                        {error}
                      </span>
                    ) : null}
                    <button className={commandClass} type="submit">
                      <KeyRound size={16} />
                      Attach bearer bridge
                    </button>
                  </form>
                ) : null}
              </div>
            </CollapsibleContent>
          </Collapsible>
        </div>
      )}
    </section>
  );
}
