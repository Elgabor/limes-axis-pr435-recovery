import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AXIS_BROWSER_SESSION_SIGNED_OUT_EVENT,
  AxisApiDecodeError,
  AxisApiError,
  axisFetch,
  axisFetchParsedJson,
  resetBrowserSessionState,
  toAxisOperatorError,
} from "./axis-api";
import type { OidcConsoleSession } from "./oidc-session";
import { OPERATIONS_API_PREFIX } from "./tenant-scope";

const BEARER_SESSION: OidcConsoleSession = {
  accessToken: "bearer-token",
  actorId: "actor-1",
  tenantId: "tenant-1",
  scopes: [],
};

function parseOk(value: unknown): { ok: boolean } {
  if (typeof value !== "object" || value === null || !("ok" in value) || typeof value.ok !== "boolean") {
    throw new TypeError("ok must be a boolean");
  }
  return { ok: value.ok };
}

const parseUnknownObject = (value: unknown): object => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new TypeError("response must be an object");
  }
  return value;
};

function stubBrowserDocument(cookie: string) {
  vi.stubGlobal("document", { cookie });
}

function stubBrowserWindow() {
  const dispatchEvent = vi.fn();
  vi.stubGlobal("window", { dispatchEvent });
  return dispatchEvent;
}

describe("Axis API fetch layer", () => {
  afterEach(() => {
    // The signed-out latch is module state and would leak between cases.
    resetBrowserSessionState();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete process.env.NEXT_PUBLIC_AXIS_API_BASE_URL;
  });

  it("includes browser credentials so API-owned OIDC cookies can authenticate requests", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const fetchMock = vi.fn<typeof fetch>(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await axisFetch("/identity/session");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://axis-api.test/identity/session",
      expect.objectContaining({
        cache: "no-store",
        credentials: "include",
        method: "GET",
      }),
    );
  });

  it("sets JSON content type on POST bodies without dropping credentials", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const fetchMock = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ ok: true }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await axisFetchParsedJson(`${OPERATIONS_API_PREFIX}/operations/daily-brief`, parseOk, {
      method: "POST",
      body: { tenant_id: "tenant_demo_manufacturing" },
    });

    const [, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    const headers = new Headers(init?.headers);

    expect(init?.credentials).toBe("include");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init?.body).toBe('{"tenant_id":"tenant_demo_manufacturing"}');
  });

  it("attaches the CSRF header to cookie-mode mutations from the readable cookie", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubBrowserDocument("axis_csrf=csrf-token-1");
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await axisFetch("/identity/sessions/ref-1/revoke", { method: "POST" });

    const [, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    const headers = new Headers(init?.headers);
    expect(headers.get("X-Axis-Csrf-Token")).toBe("csrf-token-1");
  });

  it("does not attach the CSRF header to safe methods or when no cookie exists", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubBrowserDocument("axis_csrf=csrf-token-1");
    const fetchMock = vi.fn<typeof fetch>(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await axisFetch("/identity/session");
    stubBrowserDocument("");
    await axisFetch("/identity/sessions/ref-1/revoke", { method: "POST" });

    for (const call of fetchMock.mock.calls) {
      const [, init] = call as [RequestInfo | URL, RequestInit];
      expect(new Headers(init?.headers).has("X-Axis-Csrf-Token")).toBe(false);
    }
  });

  it("keeps bearer-mode mutations CSRF-free because they are exempt server-side", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubBrowserDocument("axis_csrf=csrf-token-1");
    const fetchMock = vi.fn<typeof fetch>(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await axisFetch("/identity/sessions/ref-1/revoke", {
      method: "POST",
      session: BEARER_SESSION,
    });

    const [, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    const headers = new Headers(init?.headers);
    expect(headers.get("Authorization")).toBe("Bearer bearer-token");
    expect(headers.has("X-Axis-Csrf-Token")).toBe(false);
  });

  it("refreshes the browser session once on a cookie-mode 401 and retries the request", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubBrowserDocument("axis_csrf=stale-token");
    stubBrowserWindow();

    let protectedCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/identity/session/refresh")) {
        stubBrowserDocument("axis_csrf=rotated-token");
        return new Response(null, { status: 204 });
      }
      protectedCalls += 1;
      if (protectedCalls === 1) {
        return new Response("{}", { status: 401 });
      }
      return new Response(JSON.stringify({ ok: true }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = await axisFetchParsedJson("/identity/sessions", parseOk, {
      method: "POST",
      body: {},
    });

    expect(payload).toEqual({ ok: true });
    const urls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(urls).toEqual([
      "http://axis-api.test/identity/sessions",
      "http://axis-api.test/identity/session/refresh",
      "http://axis-api.test/identity/sessions",
    ]);

    const refreshHeaders = new Headers(
      (fetchMock.mock.calls[1] as [RequestInfo | URL, RequestInit])[1]?.headers,
    );
    expect(refreshHeaders.get("X-Axis-Csrf-Token")).toBe("stale-token");

    const retryHeaders = new Headers(
      (fetchMock.mock.calls[2] as [RequestInfo | URL, RequestInit])[1]?.headers,
    );
    expect(retryHeaders.get("X-Axis-Csrf-Token")).toBe("rotated-token");
  });

  it("converges to signed-out when the retry after a successful refresh is still 401", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubBrowserDocument("axis_csrf=stale-token");
    const dispatchEvent = stubBrowserWindow();

    let refreshCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/identity/session/refresh")) {
        refreshCalls += 1;
        stubBrowserDocument("axis_csrf=rotated-token");
        return new Response(null, { status: 204 });
      }
      // The session dies between refresh and retry, so the retry is still 401.
      return new Response("{}", { status: 401 });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(axisFetchParsedJson("/identity/sessions", parseUnknownObject)).rejects.toBeInstanceOf(AxisApiError);

    const urls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(urls).toEqual([
      "http://axis-api.test/identity/sessions",
      "http://axis-api.test/identity/session/refresh",
      "http://axis-api.test/identity/sessions",
    ]);
    // Exactly one refresh: no second refresh on the still-401 retry.
    expect(refreshCalls).toBe(1);
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
    const [event] = dispatchEvent.mock.calls[0] as [Event];
    expect(event.type).toBe(AXIS_BROWSER_SESSION_SIGNED_OUT_EVENT);
  });

  it("surfaces the signed-out state when the refresh fails, without retry loops", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubBrowserDocument("axis_csrf=stale-token");
    const dispatchEvent = stubBrowserWindow();

    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/identity/session/refresh")) {
        return new Response("{}", { status: 401 });
      }
      return new Response("{}", { status: 401 });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(axisFetchParsedJson("/identity/sessions", parseUnknownObject)).rejects.toBeInstanceOf(AxisApiError);

    const urls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(urls).toEqual([
      "http://axis-api.test/identity/sessions",
      "http://axis-api.test/identity/session/refresh",
    ]);
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
    const [event] = dispatchEvent.mock.calls[0] as [Event];
    expect(event.type).toBe(AXIS_BROWSER_SESSION_SIGNED_OUT_EVENT);
  });

  it("stops attempting refreshes once the session is known to be dead", async () => {
    // Regression: the console re-runs every live query when it hears the
    // signed-out event. Because the API rejects an expired session without
    // clearing `axis_csrf`, each refetch used to re-arm the refresh, fail, and
    // announce again — an unbounded request loop on any idle tab.
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubBrowserDocument("axis_csrf=stale-token");
    const dispatchEvent = stubBrowserWindow();

    const fetchMock = vi.fn<typeof fetch>(async () => new Response("{}", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    for (let attempt = 0; attempt < 5; attempt += 1) {
      const response = await axisFetch("/identity/sessions");
      expect(response.status).toBe(401);
    }

    const refreshCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).endsWith("/identity/session/refresh"),
    );
    // Exactly one refresh and one announcement across five failing rounds.
    expect(refreshCalls).toHaveLength(1);
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
  });

  it("re-arms the refresh after a new session starts working", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubBrowserDocument("axis_csrf=stale-token");
    stubBrowserWindow();

    let sessionAlive = false;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input).endsWith("/identity/session/refresh")) {
        return new Response("{}", { status: sessionAlive ? 200 : 401 });
      }
      return new Response("{}", { status: sessionAlive ? 200 : 401 });
    });
    vi.stubGlobal("fetch", fetchMock);

    await axisFetch("/identity/sessions");
    // Signing in elsewhere rotates the readable CSRF cookie. The next request
    // observes that new cookie and clears the latch without a reload.
    sessionAlive = true;
    stubBrowserDocument("axis_csrf=fresh-session-token");
    await axisFetch("/identity/sessions");
    sessionAlive = false;

    fetchMock.mockClear();
    await axisFetch("/identity/sessions");
    const refreshCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).endsWith("/identity/session/refresh"),
    );
    expect(refreshCalls).toHaveLength(1);
  });

  it("does not re-arm a failed cookie session after an unrelated public success", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubBrowserDocument("axis_csrf=stale-token");
    const dispatchEvent = stubBrowserWindow();

    let refreshCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/identity/session/refresh")) {
        refreshCalls += 1;
        return new Response("{}", { status: 401 });
      }
      if (url.endsWith("/ready")) {
        return new Response('{"status":"ready"}', { status: 200 });
      }
      return new Response("{}", { status: 401 });
    });
    vi.stubGlobal("fetch", fetchMock);

    expect((await axisFetch("/identity/sessions")).status).toBe(401);
    expect((await axisFetch("/ready")).status).toBe(200);
    expect((await axisFetch("/identity/sessions")).status).toBe(401);

    expect(refreshCalls).toBe(1);
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
  });

  it("does not attempt a refresh for anonymous or bearer-mode 401s", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubBrowserDocument("");
    stubBrowserWindow();
    const fetchMock = vi.fn<typeof fetch>(async () => new Response("{}", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);

    const anonymous = await axisFetch("/identity/sessions");
    expect(anonymous.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    stubBrowserDocument("axis_csrf=csrf-token-1");
    const bearer = await axisFetch("/identity/sessions", { session: BEARER_SESSION });
    expect(bearer.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("deduplicates concurrent 401 refreshes into a single rotation call", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    stubBrowserDocument("axis_csrf=stale-token");
    stubBrowserWindow();

    let refreshCalls = 0;
    let releaseRefresh: (response: Response) => void = () => {};
    const refreshGate = new Promise<Response>((resolve) => {
      releaseRefresh = resolve;
    });
    const firstAttempts = new Set<string>();
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.endsWith("/identity/session/refresh")) {
        refreshCalls += 1;
        return refreshGate;
      }
      if (!firstAttempts.has(url)) {
        firstAttempts.add(url);
        return new Response("{}", { status: 401 });
      }
      return new Response(JSON.stringify({ ok: true }), {
        headers: { "Content-Type": "application/json" },
        status: 200,
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const pending = Promise.all([
      axisFetchParsedJson("/identity/sessions", parseOk),
      axisFetchParsedJson("/identity/session", parseOk),
    ]);
    await vi.waitFor(() => {
      expect(firstAttempts.size).toBe(2);
      expect(refreshCalls).toBe(1);
    });
    releaseRefresh(new Response(null, { status: 204 }));

    await expect(pending).resolves.toEqual([{ ok: true }, { ok: true }]);
    expect(refreshCalls).toBe(1);
  });

  it("preserves structured API error details and request correlation", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        new Response(
          JSON.stringify({
            detail: {
              code: "PERMISSION_DENIED",
              message: "Tenant access denied.",
              reason: "tenant_mismatch",
              required_permission: "tenant:read",
            },
          }),
          { headers: { "x-request-id": "request-123" }, status: 403 },
        ),
      ),
    );

    const error = await axisFetchParsedJson("/protected", parseUnknownObject).catch((value: unknown) => value);

    expect(error).toBeInstanceOf(AxisApiError);
    expect(error).toMatchObject({
      code: "PERMISSION_DENIED",
      message: "Tenant access denied.",
      path: "/protected",
      reason: "tenant_mismatch",
      requestId: "request-123",
      requiredPermission: "tenant:read",
      status: 403,
    });
  });

  it("reduces typed failures to operator-safe messages and request ids", () => {
    const apiError = new AxisApiError("/protected", 403, {
      body: { detail: { code: "PERMISSION_DENIED", message: "Tenant access denied." } },
      requestId: "request-api-123",
    });
    const decodeError = new AxisApiDecodeError("/protected", "Response contract invalid.", {
      cause: new Error("decoder internals must stay hidden"),
      requestId: "request-decode-456",
    });

    expect(toAxisOperatorError(apiError, "Fallback")).toEqual({
      code: "PERMISSION_DENIED",
      message: "Tenant access denied.",
      requestId: "request-api-123",
      status: 403,
    });
    expect(toAxisOperatorError(decodeError, "Fallback")).toEqual({
      code: null,
      message: "Response contract invalid.",
      requestId: "request-decode-456",
      status: null,
    });
  });

  it("does not retain arbitrary error messages or response bodies", () => {
    const arbitraryError = toAxisOperatorError(
      new Error("secret=do-not-render"),
      "Axis request failed.",
    );
    const typedError = toAxisOperatorError(
      new AxisApiError("/protected", 503, {
        body: {
          detail: {
            message: "Axis request unavailable.",
            debug_context: "secret=database-credential",
          },
        },
        requestId: "request-safe-503",
      }),
      "Axis request failed.",
    );

    expect(arbitraryError).toEqual({
      code: null,
      message: "Axis request failed.",
      requestId: null,
      status: null,
    });
    expect(typedError).toEqual({
      code: null,
      message: "Axis request unavailable.",
      requestId: "request-safe-503",
      status: 503,
    });
    expect(JSON.stringify({ arbitraryError, typedError })).not.toContain("secret");
  });

  it("preserves FastAPI validation issues", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const issues = [{ loc: ["body", "tenant_id"], msg: "Field required", type: "missing" }];
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        new Response(JSON.stringify({ detail: issues }), { status: 422 }),
      ),
    );

    const error = await axisFetchParsedJson("/invalid", parseUnknownObject).catch((value: unknown) => value);

    expect(error).toBeInstanceOf(AxisApiError);
    expect(error).toMatchObject({ validationIssues: issues });
  });

  it("reports malformed and empty successful JSON responses as decode errors", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(new Response("not-json", { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(axisFetchParsedJson("/malformed", parseUnknownObject)).rejects.toBeInstanceOf(AxisApiDecodeError);
    await expect(axisFetchParsedJson("/empty", parseUnknownObject)).rejects.toBeInstanceOf(AxisApiDecodeError);
  });

  it("applies an explicit runtime decoder to successful responses", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        new Response(JSON.stringify({ count: "wrong" }), { status: 200 }),
      ),
    );

    await expect(
      axisFetchParsedJson("/counts", (value) => {
        if (
          typeof value !== "object" ||
          value === null ||
          !("count" in value) ||
          typeof value.count !== "number"
        ) {
          throw new TypeError("count must be a number");
        }
        return { count: value.count };
      }),
    ).rejects.toBeInstanceOf(AxisApiDecodeError);
  });

  it("preserves request correlation and sanitized decoder issues", async () => {
    process.env.NEXT_PUBLIC_AXIS_API_BASE_URL = "http://axis-api.test";
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        new Response(JSON.stringify({ count: "wrong" }), {
          headers: { "x-correlation-id": "correlation-456" },
          status: 200,
        }),
      ),
    );

    const error = await axisFetchParsedJson("/counts", () => {
      throw {
        issues: [
          { code: "invalid_type", message: "Expected number", path: ["count"] },
        ],
        payload: "must not leak",
      };
    }).catch((value: unknown) => value);

    expect(error).toBeInstanceOf(AxisApiDecodeError);
    expect(error).toMatchObject({
      requestId: "correlation-456",
      validationIssues: [
        { code: "invalid_type", message: "Expected number", path: "count" },
      ],
    });
    expect(JSON.stringify(error)).not.toContain("must not leak");
  });
});
