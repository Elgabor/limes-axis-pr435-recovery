import { describe, expect, it } from "vitest";

import {
  apiStatusClass,
  compactActorLabel,
  formatExpiry,
  identitySessionLabel,
  identitySessionTone,
  notificationTone,
  operatorInitials,
} from "./identity-format";
import type { IdentitySessionReadModel } from "./platform-overview";

function identitySession(
  overrides: Partial<IdentitySessionReadModel> = {},
): IdentitySessionReadModel {
  return {
    authenticated: false,
    mode: "public",
    actor_id: null,
    tenant_id: null,
    scopes: [],
    expires_at: null,
    api_auth_required: false,
    enterprise_sso_ready: false,
    readiness_status: "ready",
    issuer: "https://idp.example.com",
    audience: "limes-axis",
    jwks_source: "remote",
    session_boundary: "Public evaluation boundary",
    capabilities: [],
    limitations: [],
    notes: [],
    unauthenticated_reason: null,
    ...overrides,
  };
}

describe("apiStatusClass", () => {
  it("maps online to ready", () => {
    expect(apiStatusClass("online")).toBe("signal-ready");
  });

  it("maps degraded and checking to watch", () => {
    expect(apiStatusClass("degraded")).toBe("signal-watch");
    expect(apiStatusClass("checking")).toBe("signal-watch");
  });

  it("maps anything else to action required", () => {
    expect(apiStatusClass("offline")).toBe("signal-action-required");
  });
});

describe("compactActorLabel", () => {
  it("returns short actor ids unchanged", () => {
    expect(compactActorLabel("operator@plant.example")).toBe("operator@plant.example");
  });

  it("truncates actor ids longer than 30 characters with an ellipsis", () => {
    const actorId = "a-very-long-operator-identifier@plant.example.com";
    const label = compactActorLabel(actorId);

    expect(label).toBe(`${actorId.slice(0, 27)}...`);
    expect(label).toHaveLength(30);
  });
});

describe("operatorInitials", () => {
  it("falls back to OP when no actor id is provided", () => {
    expect(operatorInitials()).toBe("OP");
    expect(operatorInitials(undefined)).toBe("OP");
  });

  it("uses the first letter of the first two segments", () => {
    expect(operatorInitials("jane.doe@example.com")).toBe("JD");
    expect(operatorInitials("ops-team")).toBe("OT");
  });

  it("uses the first two characters for single-segment ids", () => {
    expect(operatorInitials("frank")).toBe("F");
    expect(operatorInitials("x")).toBe("X");
  });

  it("uses the raw leading character when the id has no alphanumeric segments", () => {
    expect(operatorInitials("@@@")).toBe("@");
  });
});

describe("formatExpiry", () => {
  it("returns Not provided for missing expiry", () => {
    expect(formatExpiry()).toBe("Not provided");
    expect(formatExpiry(undefined)).toBe("Not provided");
    expect(formatExpiry(0)).toBe("Not provided");
  });

  it("formats a past epoch-seconds timestamp as a medium date with time", () => {
    const pastEpochSeconds = Math.floor(new Date("2020-01-15T12:30:00Z").getTime() / 1000);
    const expected = new Intl.DateTimeFormat("en", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(pastEpochSeconds * 1000));

    expect(formatExpiry(pastEpochSeconds)).toBe(expected);
  });

  it("formats a future epoch-seconds timestamp as a medium date with time", () => {
    const futureEpochSeconds = Math.floor(Date.now() / 1000) + 60 * 60;
    const expected = new Intl.DateTimeFormat("en", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(futureEpochSeconds * 1000));

    expect(formatExpiry(futureEpochSeconds)).toBe(expected);
  });
});

describe("notificationTone", () => {
  it("maps severities to signal tones", () => {
    expect(notificationTone("ready")).toBe("signal-ready");
    expect(notificationTone("watch")).toBe("signal-watch");
    expect(notificationTone("action_required")).toBe("signal-action-required");
  });
});

describe("identitySessionLabel", () => {
  it("returns API required when the session read model is missing", () => {
    expect(identitySessionLabel(null)).toBe("API required");
  });

  it("returns API verified for an authenticated session", () => {
    expect(identitySessionLabel(identitySession({ authenticated: true }))).toBe("API verified");
  });

  it("returns Public for an unauthenticated session", () => {
    expect(identitySessionLabel(identitySession({ authenticated: false }))).toBe("Public");
  });
});

describe("identitySessionTone", () => {
  it("returns action required when the session read model is missing", () => {
    expect(identitySessionTone(null)).toBe("signal-action-required");
  });

  it("returns ready for an authenticated session", () => {
    expect(identitySessionTone(identitySession({ authenticated: true }))).toBe("signal-ready");
  });

  it("returns action required for an unauthenticated session that requires API auth", () => {
    expect(
      identitySessionTone(identitySession({ authenticated: false, api_auth_required: true })),
    ).toBe("signal-action-required");
  });

  it("returns watch for a public session that does not require API auth", () => {
    expect(
      identitySessionTone(identitySession({ authenticated: false, api_auth_required: false })),
    ).toBe("signal-watch");
  });
});
