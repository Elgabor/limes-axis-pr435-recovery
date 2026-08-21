import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  axisFetchParsedJson: vi.fn(),
  refreshNonce: 0,
  session: null as null | {
    accessToken: string;
    actorId: string;
    tenantId: string;
    scopes: string[];
  },
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
  useOidcConsoleSession: () => ({ session: mocks.session }),
}));

import { AxisApiDecodeError, AxisApiError } from "./axis-api";
import { useAxisQuery } from "./use-axis-query";
import { OPERATIONS_API_PREFIX } from "./tenant-scope";

type Registry = { items: string[] };
const parseRegistry = (value: unknown): Registry => value as Registry;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  mocks.axisFetchParsedJson.mockReset();
  mocks.refreshNonce = 0;
  mocks.session = null;
});

describe("useAxisQuery", () => {
  it("moves from loading to api on initial success", async () => {
    mocks.axisFetchParsedJson.mockResolvedValue({ items: ["a"] });

    const { result } = renderHook(() =>
      useAxisQuery<Registry>("/demo/registry", { parse: parseRegistry }),
    );

    expect(result.current.source).toBe("loading");
    expect(result.current.data).toBeNull();
    expect(result.current.isRefreshing).toBe(false);

    await waitFor(() => expect(result.current.source).toBe("api"));
    expect(result.current.data).toEqual({ items: ["a"] });
    expect(result.current.error).toBeNull();
    expect(result.current.isRefreshing).toBe(false);
  });

  it("keeps previous data and toggles isRefreshing across a refresh", async () => {
    mocks.axisFetchParsedJson.mockResolvedValueOnce({ items: ["a"] });

    const { result, rerender } = renderHook(() =>
      useAxisQuery<Registry>("/demo/registry", { parse: parseRegistry }),
    );
    await waitFor(() => expect(result.current.source).toBe("api"));

    const second = deferred<Registry>();
    mocks.axisFetchParsedJson.mockReturnValueOnce(second.promise);
    mocks.refreshNonce = 1;
    rerender();

    await waitFor(() => expect(result.current.isRefreshing).toBe(true));
    expect(result.current.data).toEqual({ items: ["a"] });
    expect(result.current.source).toBe("api");

    second.resolve({ items: ["a", "b"] });

    await waitFor(() => expect(result.current.isRefreshing).toBe(false));
    expect(result.current.data).toEqual({ items: ["a", "b"] });
    expect(result.current.source).toBe("api");
  });

  it("keeps data but flips source to unavailable when a refresh fails", async () => {
    mocks.axisFetchParsedJson.mockResolvedValueOnce({ items: ["a"] });

    const { result, rerender } = renderHook(() =>
      useAxisQuery<Registry>("/demo/registry", { parse: parseRegistry }),
    );
    await waitFor(() => expect(result.current.source).toBe("api"));

    mocks.axisFetchParsedJson.mockRejectedValueOnce(new Error("Axis API request failed with 503"));
    mocks.refreshNonce = 1;
    rerender();

    await waitFor(() => expect(result.current.source).toBe("unavailable"));
    expect(result.current.data).toEqual({ items: ["a"] });
    expect(result.current.error).toBe("Axis API request failed with 503");
    expect(result.current.isRefreshing).toBe(false);
  });

  it("exposes the HTTP status of a failed request as errorStatus", async () => {
    mocks.axisFetchParsedJson.mockRejectedValueOnce(new AxisApiError("/demo/registry", 404));

    const { result } = renderHook(() =>
      useAxisQuery<Registry>("/demo/registry", { parse: parseRegistry }),
    );

    await waitFor(() => expect(result.current.source).toBe("unavailable"));
    expect(result.current.errorStatus).toBe(404);
    expect(result.current.data).toBeNull();
  });

  it("classifies a TENANT_NOT_FOUND response separately from transport unavailability", async () => {
    mocks.axisFetchParsedJson.mockRejectedValueOnce(
      new AxisApiError(`${OPERATIONS_API_PREFIX}/overview`, 404, {
        body: {
          detail: {
            code: "TENANT_NOT_FOUND",
            message: "The manufacturing tenant is unknown.",
            tenant_id: "tenant_nope",
          },
        },
      }),
    );

    const { result } = renderHook(() =>
      useAxisQuery<Registry>(`${OPERATIONS_API_PREFIX}/overview?tenant_id=tenant_nope`, {
        parse: parseRegistry,
      }),
    );

    await waitFor(() => expect(result.current.source).toBe("tenant_not_found"));
    expect(result.current.errorStatus).toBe(404);
    expect(result.current.errorCode).toBe("TENANT_NOT_FOUND");
    expect(result.current.isTenantNotFound).toBe(true);
    expect(result.current.isUnavailable).toBe(false);
  });

  it("keeps errorStatus null for non-HTTP failures and clears it on success", async () => {
    mocks.axisFetchParsedJson.mockRejectedValueOnce(new TypeError("fetch failed"));

    const { result, rerender } = renderHook(() =>
      useAxisQuery<Registry>("/demo/registry", { parse: parseRegistry }),
    );
    await waitFor(() => expect(result.current.source).toBe("unavailable"));
    expect(result.current.errorStatus).toBeNull();

    mocks.axisFetchParsedJson.mockResolvedValueOnce({ items: ["a"] });
    mocks.refreshNonce = 1;
    rerender();

    await waitFor(() => expect(result.current.source).toBe("api"));
    expect(result.current.errorStatus).toBeNull();
  });

  it("resets to loading and drops data when the path changes", async () => {
    mocks.axisFetchParsedJson.mockResolvedValueOnce({ items: ["a"] });

    const { result, rerender } = renderHook(
      ({ path }: { path: string }) =>
        useAxisQuery<Registry>(path, { parse: parseRegistry }),
      { initialProps: { path: "/demo/registry" } },
    );
    await waitFor(() => expect(result.current.source).toBe("api"));

    const second = deferred<Registry>();
    mocks.axisFetchParsedJson.mockReturnValueOnce(second.promise);
    rerender({ path: "/demo/other" });

    await waitFor(() => expect(result.current.source).toBe("loading"));
    expect(result.current.data).toBeNull();
    expect(result.current.isRefreshing).toBe(false);

    second.resolve({ items: ["z"] });
    await waitFor(() => expect(result.current.source).toBe("api"));
    expect(result.current.data).toEqual({ items: ["z"] });
  });

  it("uses the supplied runtime decoder and surfaces contract failures", async () => {
    const parse = (value: unknown): Registry => {
      if (typeof value !== "object" || value === null || !("items" in value)) {
        throw new TypeError("items missing");
      }
      return value as Registry;
    };
    mocks.axisFetchParsedJson.mockRejectedValueOnce(
      new Error("Axis API response did not match the expected contract."),
    );

    const { result } = renderHook(() =>
      useAxisQuery<Registry>("/demo/registry", { parse }),
    );

    await waitFor(() => expect(result.current.source).toBe("unavailable"));
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledWith(
      "/demo/registry",
      expect.any(Function),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    const decoder = mocks.axisFetchParsedJson.mock.calls[0]?.[1] as (value: unknown) => Registry;
    expect(decoder({ items: ["decoded"] })).toEqual({ items: ["decoded"] });
    expect(result.current.error).toBe(
      "Axis API response did not match the expected contract.",
    );
    expect(result.current.errorStatus).toBeNull();
  });

  it("keeps stale data after a decoder failure and clears the failure on recovery", async () => {
    mocks.axisFetchParsedJson.mockResolvedValueOnce({ items: ["stable"] });
    const { result, rerender } = renderHook(() =>
      useAxisQuery<Registry>("/demo/registry", { parse: parseRegistry }),
    );
    await waitFor(() => expect(result.current.source).toBe("api"));

    mocks.axisFetchParsedJson.mockRejectedValueOnce(
      new AxisApiDecodeError("/demo/registry", "Contract mismatch", {
        requestId: "request-stale",
        validationIssues: [{ code: "invalid_type", path: "items.0", message: "Invalid" }],
      }),
    );
    mocks.refreshNonce = 1;
    rerender();

    await waitFor(() => expect(result.current.source).toBe("unavailable"));
    expect(result.current.data).toEqual({ items: ["stable"] });
    expect(result.current.errorRequestId).toBe("request-stale");
    expect(result.current.validationIssues).toHaveLength(1);

    mocks.axisFetchParsedJson.mockResolvedValueOnce({ items: ["recovered"] });
    mocks.refreshNonce = 2;
    rerender();

    await waitFor(() => expect(result.current.source).toBe("api"));
    expect(result.current.data).toEqual({ items: ["recovered"] });
    expect(result.current.error).toBeNull();
    expect(result.current.errorRequestId).toBeNull();
    expect(result.current.validationIssues).toEqual([]);
  });

  it("drops stale data when the actor or tenant identity changes", async () => {
    mocks.session = {
      accessToken: "token-a",
      actorId: "actor-a",
      tenantId: "tenant-a",
      scopes: ["tenant:read"],
    };
    mocks.axisFetchParsedJson.mockResolvedValueOnce({ items: ["tenant-a-secret"] });
    const { result, rerender } = renderHook(() =>
      useAxisQuery<Registry>("/demo/registry", { parse: parseRegistry }),
    );
    await waitFor(() => expect(result.current.source).toBe("api"));

    mocks.session = {
      accessToken: "token-b",
      actorId: "actor-b",
      tenantId: "tenant-b",
      scopes: ["tenant:read"],
    };
    mocks.axisFetchParsedJson.mockRejectedValueOnce(new Error("tenant-b unavailable"));
    rerender();

    expect(result.current.data).toBeNull();
    expect(result.current.source).toBe("loading");
    await waitFor(() => expect(result.current.source).toBe("unavailable"));
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe("tenant-b unavailable");
  });

  it("masks loaded data synchronously when the query is disabled", async () => {
    mocks.axisFetchParsedJson.mockResolvedValueOnce({ items: ["tenant-secret"] });
    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) =>
        useAxisQuery<Registry>("/demo/registry", { enabled, parse: parseRegistry }),
      { initialProps: { enabled: true } },
    );
    await waitFor(() => expect(result.current.source).toBe("api"));

    rerender({ enabled: false });

    expect(result.current.data).toBeNull();
    expect(result.current.source).toBe("loading");
    expect(result.current.isRefreshing).toBe(false);
    expect(result.current.isUnavailable).toBe(false);
  });

  it("rejects a response owned by a different tenant", async () => {
    const parseTenantRegistry = (value: unknown) => value as Registry & { tenant_id: string };
    mocks.axisFetchParsedJson.mockImplementation(async (path, decoder) => {
      expect(() => decoder({
        items: ["tenant-a-secret"],
        tenant_id: "tenant-a",
      })).toThrow("Axis API response belongs to a different tenant.");
      throw new AxisApiDecodeError(path, "Axis API response did not match the expected contract.", {
        requestId: "request-tenant-mismatch",
      });
    });

    const { result } = renderHook(() =>
      useAxisQuery<Registry & { tenant_id: string }>("/demo/registry?tenant_id=tenant-b", {
        expectedTenantId: "tenant-b",
        parse: parseTenantRegistry,
      }),
    );

    await waitFor(() => expect(result.current.source).toBe("unavailable"));
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe("Axis API response did not match the expected contract.");
    expect(result.current.errorRequestId).toBe("request-tenant-mismatch");
    expect(result.current.error).not.toContain("tenant-a-secret");
  });
});
