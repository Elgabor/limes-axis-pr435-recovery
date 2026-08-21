import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TenantRecord, TenantRegistry as TenantRegistryData } from "@/lib/platform-tenants";

const mocks = vi.hoisted(() => ({
  fetchTenantRegistry: vi.fn(),
}));

vi.mock("@/lib/platform-tenants", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/platform-tenants")>()),
  fetchTenantRegistry: mocks.fetchTenantRegistry,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ refreshNonce: 0, triggerRefresh: vi.fn() }),
}));

import { TenantRegistry } from "./tenant-registry";

function tenant(overrides: Partial<TenantRecord> & { tenant_id: string }): TenantRecord {
  return {
    display_name: `Display ${overrides.tenant_id}`,
    description: "",
    status: "active",
    created_by: "operator",
    audit_event_type: "platform.tenant.provisioned",
    created_at: "2026-07-01T08:00:00Z",
    updated_at: "2026-07-01T08:00:00Z",
    ...overrides,
  };
}

const pageOne: TenantRegistryData = {
  tenant_count: 2,
  active_tenant_count: 2,
  tenants: [tenant({ tenant_id: "tenant_a" }), tenant({ tenant_id: "tenant_b" })],
  has_more: true,
  next_cursor: "cursor-1",
  tenant_notes: [],
};

/** A deferred promise so the test can control exactly when a fetch resolves. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  mocks.fetchTenantRegistry.mockReset();
});

describe("TenantRegistry loadMore", () => {
  it("discards a stale load-more page instead of merging it after the status filter changes", async () => {
    const user = userEvent.setup();

    // Initial load resolves immediately with a has_more page.
    mocks.fetchTenantRegistry.mockResolvedValueOnce(pageOne);

    render(<TenantRegistry />);
    expect(await screen.findByRole("link", { name: "Display tenant_a" })).toBeInTheDocument();

    // Kick off "load more" but keep its request pending under our control.
    const loadMoreDeferred = deferred<TenantRegistryData>();
    mocks.fetchTenantRegistry.mockReturnValueOnce(loadMoreDeferred.promise);

    await user.click(screen.getByRole("button", { name: "Load more tenants" }));
    expect(mocks.fetchTenantRegistry).toHaveBeenCalledTimes(2);

    // Switching the status filter while that page-2 request is still in
    // flight starts a brand-new base load.
    const filteredPage: TenantRegistryData = {
      tenant_count: 1,
      active_tenant_count: 1,
      tenants: [tenant({ tenant_id: "tenant_active_only" })],
      has_more: false,
      next_cursor: null,
      tenant_notes: [],
    };
    mocks.fetchTenantRegistry.mockResolvedValueOnce(filteredPage);

    await user.selectOptions(screen.getByLabelText("Status"), "active");
    expect(window.location.search).toBe("?status=active");
    expect(
      await screen.findByRole("link", { name: "Display tenant_active_only" }),
    ).toBeInTheDocument();

    // Now let the orphaned "load more" page resolve. It must not be merged
    // into the list the operator is currently looking at.
    loadMoreDeferred.resolve({
      tenant_count: 1,
      active_tenant_count: 1,
      tenants: [tenant({ tenant_id: "tenant_from_stale_page" })],
      has_more: false,
      next_cursor: null,
      tenant_notes: [],
    });

    await waitFor(() => expect(mocks.fetchTenantRegistry).toHaveBeenCalledTimes(3));
    expect(screen.queryByText("Display tenant_from_stale_page")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Display tenant_active_only" })).toBeInTheDocument();
  });

  it("surfaces a load-more failure with role=alert instead of failing silently", async () => {
    const user = userEvent.setup();
    mocks.fetchTenantRegistry.mockResolvedValueOnce(pageOne);

    render(<TenantRegistry />);
    expect(await screen.findByRole("link", { name: "Display tenant_a" })).toBeInTheDocument();

    mocks.fetchTenantRegistry.mockRejectedValueOnce(new Error("network down"));
    await user.click(screen.getByRole("button", { name: "Load more tenants" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not load the next page/i,
    );
  });
});
