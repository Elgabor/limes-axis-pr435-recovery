"use client";

import { IDENTITY_SESSION_ENDPOINT, useIdentitySession } from "./use-identity-session";
import { resolveConsoleTenantScope } from "./tenant-scope";

export { IDENTITY_SESSION_ENDPOINT };

/**
 * Resolve the tenant boundary shared by every tenant-scoped console surface.
 *
 * Feature queries must remain disabled until the identity API has responded.
 * An explicitly unauthenticated response selects the public demo tenant;
 * transport failures and authenticated sessions without a tenant fail closed.
 */
export function useConsoleTenantScope() {
  const identity = useIdentitySession();
  const tenantScope = resolveConsoleTenantScope(identity.data);
  const tenantId = tenantScope.tenantId;

  return {
    identity,
    tenantScope,
    tenantId,
    tenantQueriesEnabled: identity.source === "api" && tenantId !== null,
  };
}
