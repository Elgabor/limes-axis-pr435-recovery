import { describe, expect, it } from "vitest";

import type { IdentitySessionReadModel } from "./platform-overview";
import { deriveGovernedActor } from "./governed-action";

function identitySession(
  overrides: Partial<IdentitySessionReadModel> = {},
): IdentitySessionReadModel {
  return {
    authenticated: true,
    actor_id: "operator-1",
    tenant_id: "tenant_demo_manufacturing",
    scopes: [],
    mode: "demo",
    api_auth_required: false,
    ...overrides,
  } as IdentitySessionReadModel;
}

describe("deriveGovernedActor", () => {
  it("falls back to the demo actor without a session", () => {
    expect(deriveGovernedActor(null, "connector-console-operator")).toEqual({
      actorId: "connector-console-operator",
      ssoBlocked: false,
    });
  });

  it("uses the verified actor when a session exists", () => {
    expect(deriveGovernedActor(identitySession(), "demo-actor")).toEqual({
      actorId: "operator-1",
      ssoBlocked: false,
    });
  });

  it("blocks governed writes only when the API enforces SSO and no session exists", () => {
    const blocked = deriveGovernedActor(
      identitySession({ authenticated: false, actor_id: null, api_auth_required: true }),
      "demo-actor",
    );
    expect(blocked.ssoBlocked).toBe(true);

    // Public evaluation deployments accept unauthenticated demo writes.
    const openDemo = deriveGovernedActor(
      identitySession({ authenticated: false, actor_id: null }),
      "demo-actor",
    );
    expect(openDemo.ssoBlocked).toBe(false);
  });
});
