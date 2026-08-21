import { afterEach, describe, expect, it, vi } from "vitest";

import { AxisApiError } from "./axis-api";
import {
  IDENTITY_SESSION_ADMIN_SCOPE,
  canListTenantSessions,
  formatSessionInstant,
  identitySessionsPath,
  isRevocableSessionStatus,
  revokeIdentitySession,
  sessionStatusClass,
  sessionStatusLabel,
} from "./identity-sessions";

describe("identity session bindings", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_AXIS_API_BASE_URL;
  });

  it("builds the self and tenant-wide listing paths", () => {
    expect(identitySessionsPath(false)).toBe("/identity/sessions");
    expect(identitySessionsPath(true)).toBe("/identity/sessions?tenant_wide=true");
  });

  it("detects the tenant-wide admin scope from the identity read model", () => {
    expect(IDENTITY_SESSION_ADMIN_SCOPE).toBe("identity:sessions:admin");
    expect(canListTenantSessions(["audit:read", "identity:sessions:admin"])).toBe(true);
    expect(canListTenantSessions(["audit:read"])).toBe(false);
    expect(canListTenantSessions([])).toBe(false);
  });

  it("revokes a session by opaque reference with a CSRF-protected cookie POST", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    vi.stubGlobal("document", { cookie: "axis_csrf=csrf-token-1" });
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await revokeIdentitySession("2f6d8f34-1b34-4b7e-9f3a-51f6f0f9c001");

    const [url, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    expect(String(url)).toBe(
      "http://axis-api.test/identity/sessions/2f6d8f34-1b34-4b7e-9f3a-51f6f0f9c001/revoke",
    );
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(new Headers(init?.headers).get("X-Axis-Csrf-Token")).toBe("csrf-token-1");
  });

  it("throws a typed error when the API denies the revocation", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const fetchMock = vi.fn<typeof fetch>(async () => new Response("{}", {
      headers: { "x-request-id": "request-session-revoke-403" },
      status: 403,
    }));
    vi.stubGlobal("fetch", fetchMock);

    const failure = revokeIdentitySession("2f6d8f34-1b34-4b7e-9f3a-51f6f0f9c001");
    await expect(failure).rejects.toBeInstanceOf(AxisApiError);
    await expect(
      revokeIdentitySession("2f6d8f34-1b34-4b7e-9f3a-51f6f0f9c001"),
    ).rejects.toMatchObject({
      requestId: "request-session-revoke-403",
      status: 403,
    });
  });

  it("labels session lifecycle statuses with console signal classes", () => {
    expect(sessionStatusLabel("active")).toBe("Active");
    expect(sessionStatusLabel("revoked")).toBe("Revoked");
    expect(sessionStatusLabel("idle_timeout")).toBe("Idle timeout");
    expect(sessionStatusClass("active")).toBe("signal-ready");
    expect(sessionStatusClass("refreshing")).toBe("signal-watch");
    expect(sessionStatusClass("rotated")).toBe("signal-watch");
    expect(sessionStatusClass("revoked")).toBe("signal-action-required");
    expect(isRevocableSessionStatus("active")).toBe(true);
    expect(isRevocableSessionStatus("refreshing")).toBe(true);
    expect(isRevocableSessionStatus("revoked")).toBe(false);
    expect(isRevocableSessionStatus("rotated")).toBe(false);
  });

  it("formats session instants defensively", () => {
    expect(formatSessionInstant(null)).toBe("Not recorded");
    expect(formatSessionInstant(undefined)).toBe("Not recorded");
    expect(formatSessionInstant("not-a-date")).toBe("Not recorded");
    expect(formatSessionInstant("2026-07-07T10:30:00Z")).toContain("2026");
  });
});
