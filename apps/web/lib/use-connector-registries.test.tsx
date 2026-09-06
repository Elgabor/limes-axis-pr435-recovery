import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  connectorEndpointFixtures,
  connectorRegistryFixture,
  workspaceFixture,
} from "@/components/connector-console/connector-fixtures";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  refreshNonce: 0,
  session: null as null | { tenantId: string; actorId: string; accessToken: string; scopes: string[] },
}));
vi.mock("@/lib/axis-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./axis-api")>()),
  axisFetchParsedJson: mocks.fetch,
}));
vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ refreshNonce: mocks.refreshNonce }),
}));
vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: mocks.session, hydrated: true }),
}));

import { useConnectorRegistries, CONNECTOR_ENDPOINTS as endpoints } from "./use-connector-registries";

const tenant = "tenant_demo_manufacturing";
function pending<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function responseFor(path: string): unknown {
  const url = new URL(path, "http://localhost");
  if (url.pathname === endpoints.workspace) return workspaceFixture();
  if (url.pathname === endpoints.detail) {
    const connector = connectorRegistryFixture.connectors.find(
      (item) => item.manifest.connector_id === url.searchParams.get("connector_id"),
    );
    return { tenant_id: tenant, connector };
  }
  return connectorEndpointFixtures[url.pathname]
    ?? connectorEndpointFixtures[`${url.pathname}?tenant_id=${tenant}`];
}
function fetchedPaths() {
  return mocks.fetch.mock.calls.map(([path]) => new URL(path, "http://localhost").pathname);
}

beforeEach(() => {
  mocks.fetch.mockReset();
  mocks.refreshNonce = 0;
  mocks.session = null;
  mocks.fetch.mockImplementation(async (path: string, decode: (value: unknown) => unknown) =>
    decode(responseFor(path)),
  );
});

describe("connector workspace requests", () => {
  it("waits for the summary before requesting only the selected detail", async () => {
    const summary = pending<unknown>();
    mocks.fetch.mockImplementationOnce(async (_path, decode) => decode(await summary.promise));
    const { result, rerender } = renderHook(() => useConnectorRegistries(tenant, true));
    expect(fetchedPaths()).toEqual([endpoints.workspace]);
    await act(async () => summary.resolve(workspaceFixture()));
    await waitFor(() => expect(result.current.detail.source).toBe("api"));
    expect(fetchedPaths()).toEqual([endpoints.workspace, endpoints.detail]);
    rerender();
    expect(fetchedPaths()).toEqual([endpoints.workspace, endpoints.detail]);
  });

  it("loads and refreshes only the visible tab, scoped to the selected connector", async () => {
    const { result, rerender } = renderHook(({ tab }) =>
      useConnectorRegistries(tenant, true, "", "", tab),
    { initialProps: { tab: "overview" } });
    await waitFor(() => expect(result.current.detail.source).toBe("api"));
    mocks.fetch.mockClear();
    rerender({ tab: "runs" });
    await waitFor(() => expect(result.current.runs.source).toBe("api"));
    expect(new Set(fetchedPaths())).toEqual(new Set([endpoints.runs, endpoints.credentialLeases]));
    for (const [path] of mocks.fetch.mock.calls) {
      expect(new URL(path, "http://localhost").searchParams.get("connector_id"))
        .toBe("file_csv_manufacturing_assets");
    }
    mocks.fetch.mockClear();
    rerender({ tab: "governance" });
    await waitFor(() => expect(result.current.evidenceInvariants.source).toBe("api"));
    expect(new Set(fetchedPaths())).toEqual(new Set([
      endpoints.credentialHandles, endpoints.egressPolicies, endpoints.evidenceInvariants,
    ]));
    expect(result.current.runs.data).toBeNull();
    mocks.fetch.mockClear();
    mocks.refreshNonce++;
    rerender({ tab: "governance" });
    await waitFor(() => expect(fetchedPaths()).toHaveLength(6));
    expect(new Set(fetchedPaths())).toEqual(new Set([
      endpoints.workspace, endpoints.detail, endpoints.credentialHandles,
      endpoints.credentialLeases, endpoints.egressPolicies, endpoints.evidenceInvariants,
    ]));
    await waitFor(() => expect(result.current.registry.isRefreshing).toBe(false));
  });

  it("fetches templates only when the wizard opens and refetches after closing", async () => {
    const { result, rerender } = renderHook(({ open }) =>
      useConnectorRegistries(tenant, true, "", "", "overview", 0, open),
    { initialProps: { open: false } });
    await waitFor(() => expect(result.current.detail.source).toBe("api"));
    expect(fetchedPaths()).not.toContain(endpoints.registry);
    rerender({ open: true });
    await waitFor(() => expect(result.current.templates.source).toBe("api"));
    rerender({ open: false });
    expect(result.current.templates.data).toBeNull();
    rerender({ open: true });
    await waitFor(() => expect(fetchedPaths().filter((path) => path === endpoints.registry)).toHaveLength(2));
  });

  it("masks the previous connector while another selected detail is pending", async () => {
    const first = "file_csv_manufacturing_assets";
    const second = "external_db_operational_mirror";
    const { result, rerender } = renderHook(({ connector }) =>
      useConnectorRegistries(tenant, true, "", connector),
    { initialProps: { connector: first } });
    await waitFor(() => expect(result.current.detail.source).toBe("api"));
    const detail = pending<unknown>();
    mocks.fetch.mockImplementationOnce(async (_path, decode) => decode(await detail.promise));
    rerender({ connector: second });
    expect(result.current.detail.data).toBeNull();
    await act(async () => detail.resolve({
      tenant_id: tenant, connector: connectorRegistryFixture.connectors[1],
    }));
    await waitFor(() => expect(result.current.detail.data?.connector.manifest.connector_id).toBe(second));
  });

  it("rejects a selected detail from another connector and a summary from another tenant", async () => {
    mocks.fetch.mockImplementation(async (path, decode) => {
      const value = responseFor(path);
      if (new URL(path, "http://localhost").pathname === endpoints.detail) {
        return decode({ tenant_id: tenant, connector: connectorRegistryFixture.connectors[1] });
      }
      return decode(value);
    });
    const { result, unmount } = renderHook(() => useConnectorRegistries(tenant, true));
    await waitFor(() => expect(result.current.detail.source).toBe("unavailable"));
    expect(result.current.detail.data).toBeNull();
    unmount();
    mocks.fetch.mockImplementation(async (_path, decode) =>
      decode({ ...workspaceFixture(), tenant_id: "foreign" }),
    );
    const other = renderHook(() => useConnectorRegistries(tenant, true));
    await waitFor(() => expect(other.result.current.registry.source).toBe("unavailable"));
    expect(other.result.current.registry.data).toBeNull();
    expect(other.result.current.detail.data).toBeNull();
  });

  it("drops principal data immediately when a bearer actor changes", async () => {
    mocks.session = { tenantId: tenant, actorId: "first", accessToken: "first-token", scopes: [] };
    const { result, rerender } = renderHook(() => useConnectorRegistries(tenant, true));
    await waitFor(() => expect(result.current.detail.source).toBe("api"));
    const summary = pending<unknown>();
    mocks.fetch.mockImplementationOnce(async (_path, decode) => decode(await summary.promise));
    mocks.session = { ...mocks.session, actorId: "second", accessToken: "second-token" };
    rerender();
    expect(result.current.registry.data).toBeNull();
    expect(result.current.detail.data).toBeNull();
    await act(async () => summary.resolve(workspaceFixture()));
    await waitFor(() => expect(result.current.detail.source).toBe("api"));
    expect(mocks.fetch.mock.calls.at(-1)?.[2].session.actorId).toBe("second");
  });

  it("does not issue any connector request before identity is verified", () => {
    const { result } = renderHook(() => useConnectorRegistries(null, false));
    expect(mocks.fetch).not.toHaveBeenCalled();
    expect(result.current.registry.data).toBeNull();
  });
});
