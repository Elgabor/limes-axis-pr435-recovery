"use client";

import { useEffect, useRef } from "react";

import { AxisMark } from "@/components/axis-mark";
import { ShieldKeyIcon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { cn } from "@/lib/cn";
import {
  buildOidcAuthorizeUrl,
  currentReturnPath,
} from "@/lib/oidc-session";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { strings } from "@/lib/strings";
import { useConsole } from "@/providers/console-provider";

/**
 * The one sign-in state for enforced-SSO deployments.
 *
 * Rendered by the shell instead of console surfaces whenever the API reports
 * "sign-in required, no verified session". Tenant data is never mounted in
 * this state, so an expired session cannot leave stale tenant content on
 * screen behind the gate.
 */

function reasonCopy(reason: string | null): string {
  const reasons = strings.identityGate.reasons;
  if (reason && reason in reasons) {
    return reasons[reason as keyof typeof reasons];
  }
  return reasons.fallback;
}

function issuerHost(issuer: string): string {
  try {
    return new URL(issuer).host;
  } catch {
    return "";
  }
}

export function SignInGate({
  identitySession,
  className,
}: {
  identitySession: IdentitySessionReadModel;
  className?: string;
}) {
  const { apiBaseUrl } = useConsole();
  const signInHref = buildOidcAuthorizeUrl(apiBaseUrl, currentReturnPath());
  const host = issuerHost(identitySession.issuer);
  // Keyboard/focus behavior: when a live session is lost mid-use the gate
  // replaces mounted surfaces; moving focus here keeps keyboard operators on
  // the primary action instead of stranding it behind removed content.
  const gateRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    gateRef.current?.focus({ preventScroll: true });
  }, []);

  return (
    <section
      aria-labelledby="signin-gate-title"
      ref={gateRef}
      tabIndex={-1}
      className={cn(
        "grid min-h-[60vh] place-items-center px-4 py-12 outline-none",
        className,
      )}
      data-signin-gate
    >
      <div className="w-full max-w-[420px] rounded-2xl border border-line bg-surface p-6 shadow-sm dark:border-white/10">
        <div className="mb-4 flex items-center gap-2.5">
          <AxisMark className="h-7 w-7 text-ink" />
          <span className="eyebrow">{strings.identityGate.eyebrow}</span>
        </div>
        <h1
          id="signin-gate-title"
          className="m-0 font-display text-xl font-semibold text-ink"
        >
          {strings.identityGate.title}
        </h1>
        <p className="mt-2 mb-0 text-sm leading-snug text-muted">
          {strings.identityGate.description}
        </p>
        <p
          className="mt-3 mb-0 text-sm leading-snug text-ink"
          role="status"
          data-gate-reason
        >
          {reasonCopy(identitySession.unauthenticated_reason)}
        </p>
        <a
          className="mt-5 flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl bg-signal px-4 text-sm font-semibold text-white transition-transform hover:opacity-90 active:scale-[0.98]"
          data-gate-sign-in
          href={signInHref}
        >
          <HugeiconsIcon icon={ShieldKeyIcon} size={17} strokeWidth={1.8} aria-hidden />
          {strings.identityGate.signIn}
        </a>
        <p className="mt-3 mb-0 text-xs leading-snug text-muted">
          {strings.identityGate.returnHint}
          {host ? ` Identity provider: ${host}.` : ""}
        </p>
      </div>
    </section>
  );
}
