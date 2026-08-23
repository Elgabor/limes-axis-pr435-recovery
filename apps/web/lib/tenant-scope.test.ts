import { describe, expect, it } from "vitest";

import type { IdentitySessionReadModel } from "./platform-overview";
import {
  buildTenantScopedPath,
  DEMO_TENANT_ID,
  resolveConsoleTenantScope,
} from "./tenant-scope";

function identity(
  overrides: Partial<IdentitySessionReadModel> = {},
): IdentitySessionReadModel {
  return {
    authenticated: false,
    mode: "public_demo",
    actor_id: null,
    tenant_id: null,
    scopes: [],
    expires_at: null,
    api_auth_required: true,
    enterprise_sso_ready: true,
    readiness_status: "ready",
    issuer: "https://idp.example",
    audience: "limes-axis-api",
    jwks_source: "configured",
    session_boundary: "api_verified",
    capabilities: [],
    limitations: [],
    notes: [],
    unauthenticated_reason: null,
    ...overrides,
  };
}

describe("resolveConsoleTenantScope", () => {
  it("uses the API-verified tenant for an authenticated principal", () => {
    expect(
      resolveConsoleTenantScope(
        identity({ authenticated: true, tenant_id: "tenant_acme", actor_id: "operator" }),
      ),
    ).toEqual({ mode: "authenticated", tenantId: "tenant_acme" });
  });

  it("uses the demo tenant only after an explicit unauthenticated response", () => {
    expect(resolveConsoleTenantScope(identity())).toEqual({
      mode: "demo",
      tenantId: DEMO_TENANT_ID,
    });
  });

  it("fails closed while identity is unresolved or an authenticated tenant is missing", () => {
    expect(resolveConsoleTenantScope(null)).toEqual({ mode: "unresolved", tenantId: null });
    expect(resolveConsoleTenantScope(identity({ authenticated: true }))).toEqual({
      mode: "unresolved",
      tenantId: null,
    });
  });
});

describe("buildTenantScopedPath", () => {
  it("encodes tenant ids and additional query parameters", () => {
    expect(buildTenantScopedPath("/operations", "tenant/acme + eu", { limit: 25 })).toBe(
      "/operations?tenant_id=tenant%2Facme+%2B+eu&limit=25",
    );
  });
});
