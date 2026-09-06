import type { IdentitySessionReadModel } from "./platform-overview";

/**
 * Prefix for every operational API call. These routes were served under
 * `/demo/manufacturing` — a path no customer should call, naming a vertical the
 * product does not only serve. The API still answers there as a deprecated
 * alias; the console does not. Kept as one constant so the next move is a
 * one-line change rather than another sweep of call sites.
 *
 * `/demo/bootstrap` is deliberately excluded: it seeds the
 * demonstration scenario and has no operational equivalent.
 */
export const OPERATIONS_API_PREFIX = "/operations";
export const DEMO_TENANT_ID = "tenant_demo_manufacturing";

export type ConsoleTenantScope =
  | { mode: "authenticated"; tenantId: string }
  | { mode: "demo"; tenantId: typeof DEMO_TENANT_ID }
  | { mode: "unresolved"; tenantId: null };

/**
 * Resolve the API-verified tenant used by tenant-scoped console queries.
 *
 * The manufacturing demo remains available only for an explicitly
 * unauthenticated identity response. An authenticated response without a
 * tenant claim fails closed instead of silently reading the demo tenant.
 */
export function resolveConsoleTenantScope(
  identity: IdentitySessionReadModel | null,
): ConsoleTenantScope {
  if (!identity) {
    return { mode: "unresolved", tenantId: null };
  }
  if (!identity.authenticated) {
    return { mode: "demo", tenantId: DEMO_TENANT_ID };
  }

  const tenantId = identity.tenant_id?.trim();
  return tenantId
    ? { mode: "authenticated", tenantId }
    : { mode: "unresolved", tenantId: null };
}

export function buildTenantScopedPath(
  path: string,
  tenantId: string,
  parameters: Record<string, string | number> = {},
): string {
  const query = new URLSearchParams({ tenant_id: tenantId });
  Object.entries(parameters).forEach(([key, value]) => {
    query.set(key, String(value));
  });
  return `${path}?${query.toString()}`;
}
