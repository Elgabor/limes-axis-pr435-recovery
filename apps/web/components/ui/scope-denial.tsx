"use client";

import { ShieldOff } from "lucide-react";

import { cn } from "@/lib/cn";
import { strings } from "@/lib/strings";

/**
 * Classified failure of one governed read: the API answered 403 with the
 * `missing_required_scope` denial class and named the permission.
 *
 * Surfaces render this instead of a generic "API unavailable" panel so an
 * operator can act on a scope denial rather than suspecting an outage. The
 * named permission comes from the API's verified-scope decision, never from
 * client-side guessing.
 */
export function missingRequiredScopePermission(query: {
  errorStatus: number | null;
  errorCode: string | null;
  errorReason: string | null;
  errorRequiredPermission: string | null;
}): string | null {
  if (
    query.errorStatus !== 403
    || query.errorCode !== "PERMISSION_DENIED"
    || query.errorReason !== "missing_required_scope"
    || !query.errorRequiredPermission
  ) {
    return null;
  }
  return query.errorRequiredPermission;
}

export function ScopeDenialPanel({
  className,
  requiredPermission,
  subject,
}: {
  className?: string;
  requiredPermission: string;
  subject: string;
}) {
  return (
    <section
      aria-live="polite"
      className={cn(
        "min-w-0 rounded-2xl border border-line bg-surface p-4 dark:border-white/10 dark:bg-white/5",
        className,
      )}
      data-scope-denial
      role="alert"
    >
      <h2 className="font-display m-0 flex items-center gap-2 text-lg text-ink">
        <ShieldOff aria-hidden="true" className="shrink-0 text-muted" size={17} />
        {strings.scopeDenial.title}
      </h2>
      <p className="mx-0 mt-1.5 mb-0 max-w-2xl text-sm leading-snug text-muted">
        {strings.scopeDenial.bodyPrefix} {subject}{" "}
        {strings.scopeDenial.bodySuffix}
      </p>
      <p
        className="mx-0 mt-2 mb-0 break-words font-mono text-xs text-muted"
        data-required-permission
      >
        {strings.scopeDenial.permissionLabel}: {requiredPermission}
      </p>
    </section>
  );
}
