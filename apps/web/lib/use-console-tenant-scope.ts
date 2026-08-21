"use client";

import type { IdentitySessionReadModel } from "./platform-overview";
import { parseIdentitySessionReadModel } from "./runtime-contracts/overview";
import { resolveConsoleTenantScope } from "./tenant-scope";
import { useAxisQuery } from "./use-axis-query";

export const IDENTITY_SESSION_ENDPOINT = "/identity/session";

/**
 * Resolve the tenant boundary shared by every tenant-scoped console surface.
 *
 * Feature queries must remain disabled until the identity API has responded.
 * An explicitly unauthenticated response selects the public demo tenant;
 * transport failures and authenticated sessions without a tenant fail closed.
 */
export function useConsoleTenantScope() {
  const identity = useAxisQuery<IdentitySessionReadModel>(IDENTITY_SESSION_ENDPOINT, {
    parse: parseIdentitySessionReadModel,
  });
  const tenantScope = resolveConsoleTenantScope(identity.data);
  const tenantId = tenantScope.tenantId;

  return {
    identity,
    tenantScope,
    tenantId,
    tenantQueriesEnabled: identity.source === "api" && tenantId !== null,
  };
}
