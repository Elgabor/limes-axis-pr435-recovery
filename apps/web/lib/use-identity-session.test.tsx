import { renderHook, waitFor, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  axisFetchParsedJson: vi.fn(),
  refreshNonce: 0,
  session: null as null | {
    accessToken: string;
    actorId: string;
    tenantId: string;
    scopes: string[];
  },
  hydrated: true,
}));

vi.mock("@/lib/axis-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./axis-api")>()),
  axisFetchParsedJson: mocks.axisFetchParsedJson,
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({
    apiBaseUrl: "http://localhost:8000",
    apiStatus: { state: "online", label: "Online", detail: "" },
    refreshNonce: mocks.refreshNonce,
    triggerRefresh: vi.fn(),
  }),
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({
    session: mocks.session,
    hydrated: mocks.hydrated,
  }),
}));

import { resetIdentitySessionStore } from "./use-identity-session";
import { startIdentitySessionHeartbeat, useIdentitySession } from "./use-identity-session";

const SESSION_A = {
  accessToken: "token-a",
  actorId: "actor-a",
  tenantId: "tenant-a",
  scopes: ["demo:read"],
};

const SESSION_B = {
  accessToken: "token-b",
  actorId: "actor-b",
  tenantId: "tenant-b",
  scopes: ["platform:admin"],
};

function sessionPayload(tenantId: string, actorId: string) {
  return {
    authenticated: true,
    mode: "validated_oidc_bearer",
    actor_id: actorId,
    tenant_id: tenantId,
    scopes: ["demo:read"],
    expires_at: 1900000000,
    api_auth_required: true,
    enterprise_sso_ready: true,
    readiness_status: "ready",
    issuer: "https://idp.example.com/realms/axis",
    audience: "limes-axis-api",
    jwks_source: "explicit_jwks_url",
    session_boundary: "bearer_token_verified_by_axis_api",
    capabilities: [],
    limitations: [],
    notes: [],
  };
}

beforeEach(() => {
  mocks.axisFetchParsedJson.mockReset();
  mocks.refreshNonce = 0;
  mocks.session = null;
  mocks.hydrated = true;
  resetIdentitySessionStore();
});

describe("useIdentitySession", () => {
  it("moves from loading to api on initial success", async () => {
    mocks.axisFetchParsedJson.mockResolvedValue(sessionPayload("tenant-a", "actor-a"));

    const { result } = renderHook(() => useIdentitySession());

    expect(result.current.source).toBe("loading");
    expect(result.current.data).toBeNull();

    await waitFor(() => expect(result.current.source).toBe("api"));
    expect(result.current.data?.tenant_id).toBe("tenant-a");
    expect(result.current.isRefreshing).toBe(false);
  });

  it("issues one shared request for multiple concurrent consumers", async () => {
    mocks.axisFetchParsedJson.mockResolvedValue(sessionPayload("tenant-a", "actor-a"));

    const first = renderHook(() => useIdentitySession());
    const second = renderHook(() => useIdentitySession());

    await waitFor(() => expect(first.result.current.source).toBe("api"));
    await waitFor(() => expect(second.result.current.source).toBe("api"));

    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(1);
    expect(second.result.current.data?.tenant_id).toBe("tenant-a");
  });

  it("keeps previous data and flags isRefreshing across a nonce refresh", async () => {
    mocks.axisFetchParsedJson.mockResolvedValueOnce(sessionPayload("tenant-a", "actor-a"));

    const { result, rerender } = renderHook(() => useIdentitySession());
    await waitFor(() => expect(result.current.source).toBe("api"));

    let resolveSecond!: (value: unknown) => void;
    mocks.axisFetchParsedJson.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveSecond = resolve;
      }),
    );

    mocks.refreshNonce = 1;
    rerender();

    expect(result.current.data?.tenant_id).toBe("tenant-a");
    expect(result.current.isRefreshing).toBe(true);

    await act(async () => {
      resolveSecond(sessionPayload("tenant-a", "actor-a"));
    });
    await waitFor(() => expect(result.current.isRefreshing).toBe(false));
    expect(result.current.source).toBe("api");
  });

  it("never exposes a prior principal's data after an actor change", async () => {
    mocks.axisFetchParsedJson.mockResolvedValueOnce(sessionPayload("tenant-a", "actor-a"));

    const { result, rerender } = renderHook(() => useIdentitySession());
    await waitFor(() => expect(result.current.source).toBe("api"));
    expect(result.current.data?.tenant_id).toBe("tenant-a");

    mocks.session = SESSION_B;
    mocks.axisFetchParsedJson.mockResolvedValueOnce(sessionPayload("tenant-b", "actor-b"));
    rerender();

    // Masked immediately: no committed frame may show the previous principal.
    expect(result.current.data).toBeNull();
    expect(result.current.source).toBe("loading");

    await waitFor(() => expect(result.current.source).toBe("api"));
    expect(result.current.data?.tenant_id).toBe("tenant-b");
    expect(result.current.data?.actor_id).toBe("actor-b");
  });

  it("masks the prior tenant's data while a tenant change reloads", async () => {
    mocks.session = SESSION_A;
    mocks.axisFetchParsedJson.mockResolvedValueOnce(sessionPayload("tenant-a", "actor-a"));

    const { result, rerender } = renderHook(() => useIdentitySession());
    await waitFor(() => expect(result.current.data?.tenant_id).toBe("tenant-a"));

    let rejectNext!: (reason: unknown) => void;
    mocks.axisFetchParsedJson.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectNext = reject;
        }),
    );
    mocks.session = SESSION_B;
    rerender();

    expect(result.current.data).toBeNull();

    await act(async () => {
      rejectNext(new Error("network down"));
    });
    await waitFor(() => expect(result.current.source).toBe("unavailable"));
    expect(result.current.data).toBeNull();
  });

  it("keeps stale data with a classified failure when a refresh fails", async () => {
    mocks.axisFetchParsedJson.mockResolvedValueOnce(sessionPayload("tenant-a", "actor-a"));

    const { result, rerender } = renderHook(() => useIdentitySession());
    await waitFor(() => expect(result.current.source).toBe("api"));

    mocks.axisFetchParsedJson.mockRejectedValueOnce(new Error("connection refused"));
    mocks.refreshNonce = 1;
    rerender();

    await waitFor(() => expect(result.current.isRefreshing).toBe(false));
    expect(result.current.data?.tenant_id).toBe("tenant-a");
    expect(result.current.source).toBe("unavailable");
    expect(result.current.error).toBe("connection refused");
  });

  it("stays loading without fetching until the OIDC session is hydrated", async () => {
    mocks.hydrated = false;
    mocks.axisFetchParsedJson.mockResolvedValue(sessionPayload("tenant-a", "actor-a"));

    const { result, rerender } = renderHook(() => useIdentitySession());

    expect(result.current.source).toBe("loading");
    expect(result.current.isLoading).toBe(true);
    expect(mocks.axisFetchParsedJson).not.toHaveBeenCalled();

    mocks.hydrated = true;
    rerender();

    await waitFor(() => expect(result.current.source).toBe("api"));
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(1);
  });

  it("retries after an initial failure on the next refresh nonce", async () => {
    mocks.axisFetchParsedJson.mockRejectedValueOnce(new Error("boom"));

    const { result, rerender } = renderHook(() => useIdentitySession());
    await waitFor(() => expect(result.current.source).toBe("unavailable"));
    expect(result.current.errorStatus).toBeNull();

    mocks.axisFetchParsedJson.mockResolvedValueOnce(sessionPayload("tenant-a", "actor-a"));
    mocks.refreshNonce = 1;
    rerender();

    await waitFor(() => expect(result.current.source).toBe("api"));
    expect(result.current.data?.tenant_id).toBe("tenant-a");
  });
});

describe("identity session heartbeat", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  async function mountWithSession(payload?: unknown) {
    mocks.axisFetchParsedJson.mockResolvedValueOnce(
      payload ?? sessionPayload("tenant-a", "actor-a"),
    );
    const rendered = renderHook(() => useIdentitySession());
    const stopHeartbeat = startIdentitySessionHeartbeat(60_000);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    return { rendered, stopHeartbeat };
  }

  it("revalidates the verified session on the interval", async () => {
    const { stopHeartbeat } = await mountWithSession();
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });

    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(2);
    expect(mocks.axisFetchParsedJson).toHaveBeenLastCalledWith(
      "/identity/session",
      expect.any(Function),
      expect.anything(),
    );
    stopHeartbeat();
  });

  it("stops revalidating once the session reports unauthenticated", async () => {
    const unauthenticated = {
      ...sessionPayload("tenant-a", "actor-a"),
      authenticated: false,
      actor_id: null,
      tenant_id: null,
      scopes: [],
      expires_at: null,
      unauthenticated_reason: "expired_session_cookie",
    };
    const { stopHeartbeat } = await mountWithSession(unauthenticated);
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(180_000);
    });

    // The gate owns the screen now; polling a dead session would only churn.
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(1);
    stopHeartbeat();
  });

  it("never polls auth-optional deployments", async () => {
    const authOptional = {
      ...sessionPayload("tenant-a", "actor-a"),
      api_auth_required: false,
    };
    const { stopHeartbeat } = await mountWithSession(authOptional);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(180_000);
    });

    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(1);
    stopHeartbeat();
  });

  it("revalidates on window focus and throttles bursts", async () => {
    const { stopHeartbeat } = await mountWithSession();
    // Follow-up revalidations keep resolving an authenticated session.
    mocks.axisFetchParsedJson.mockResolvedValue(sessionPayload("tenant-a", "actor-a"));

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("focus"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(2);

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      await vi.advanceTimersByTimeAsync(0);
    });
    // Still inside the throttle window; no extra request.
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
      window.dispatchEvent(new Event("focus"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(3);
    stopHeartbeat();
  });

  it("keeps stale data visible when a background revalidation fails", async () => {
    const { rendered, stopHeartbeat } = await mountWithSession();
    mocks.axisFetchParsedJson.mockRejectedValueOnce(new Error("connection refused"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });

    expect(rendered.result.current.source).toBe("unavailable");
    expect(rendered.result.current.data?.tenant_id).toBe("tenant-a");
    stopHeartbeat();
  });
});
