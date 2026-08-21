import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TenantQuotaSet } from "@/lib/platform-tenants";

const mocks = vi.hoisted(() => ({
  fetchTenantQuotas: vi.fn(),
  updateTenantQuotas: vi.fn(),
  refreshNonce: 0,
}));

vi.mock("@/lib/platform-tenants", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/platform-tenants")>()),
  fetchTenantQuotas: mocks.fetchTenantQuotas,
  updateTenantQuotas: mocks.updateTenantQuotas,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ refreshNonce: mocks.refreshNonce, triggerRefresh: vi.fn() }),
}));

import { TenantQuotaEditor } from "./tenant-quota-editor";

const initialQuotas: TenantQuotaSet = {
  tenant_id: "tenant_x",
  quotas: {
    api_requests_per_window: 100,
    max_concurrent_sessions: 10,
    max_connector_sync_rows_per_run: 1000,
  },
  changes: [],
  quota_notes: [],
};

beforeEach(() => {
  mocks.fetchTenantQuotas.mockReset();
  mocks.updateTenantQuotas.mockReset();
  mocks.refreshNonce = 0;
});

describe("TenantQuotaEditor background refresh", () => {
  it("does not overwrite an unsaved edit when a background refresh reloads quotas", async () => {
    const user = userEvent.setup();
    mocks.fetchTenantQuotas.mockResolvedValueOnce(initialQuotas);

    const { rerender } = render(<TenantQuotaEditor tenantId="tenant_x" />);

    const field = await screen.findByLabelText("API requests per window");
    expect(field).toHaveValue(100);

    await user.clear(field);
    await user.type(field, "555");
    expect(field).toHaveValue(555);

    // A background refresh (e.g. suspending the tenant elsewhere on the
    // page) reloads the same tenant's quotas from the server.
    mocks.fetchTenantQuotas.mockResolvedValueOnce(initialQuotas);
    mocks.refreshNonce = 1;
    rerender(<TenantQuotaEditor tenantId="tenant_x" />);

    await waitFor(() => expect(mocks.fetchTenantQuotas).toHaveBeenCalledTimes(2));
    // The unsaved edit must survive the reload instead of being silently
    // reverted to the server's value.
    expect(field).toHaveValue(555);
  });

  it("keeps a pending confirmation intact instead of letting a reload zero it out", async () => {
    const user = userEvent.setup();
    mocks.fetchTenantQuotas.mockResolvedValueOnce(initialQuotas);

    const { rerender } = render(<TenantQuotaEditor tenantId="tenant_x" />);

    const field = await screen.findByLabelText("API requests per window");
    await user.clear(field);
    await user.type(field, "555");
    await user.click(screen.getByRole("button", { name: "Review quota update" }));

    expect(
      screen.getByText("Confirm the quota update: blank fields clear the override."),
    ).toBeInTheDocument();

    mocks.fetchTenantQuotas.mockResolvedValueOnce(initialQuotas);
    mocks.refreshNonce = 1;
    rerender(<TenantQuotaEditor tenantId="tenant_x" />);

    await waitFor(() => expect(mocks.fetchTenantQuotas).toHaveBeenCalledTimes(2));

    // Still confirming the operator's real edit — not silently reverted to
    // the server's value nor left claiming "applied with 0 changes".
    expect(
      screen.getByText("Confirm the quota update: blank fields clear the override."),
    ).toBeInTheDocument();
    expect(field).toHaveValue(555);
    expect(mocks.updateTenantQuotas).not.toHaveBeenCalled();
  });

  it("does apply a reload once the form is pristine again", async () => {
    mocks.fetchTenantQuotas.mockResolvedValueOnce(initialQuotas);

    const { rerender } = render(<TenantQuotaEditor tenantId="tenant_x" />);

    const field = await screen.findByLabelText("API requests per window");
    expect(field).toHaveValue(100);

    mocks.fetchTenantQuotas.mockResolvedValueOnce({
      ...initialQuotas,
      quotas: { ...initialQuotas.quotas, api_requests_per_window: 250 },
    });
    mocks.refreshNonce = 1;
    rerender(<TenantQuotaEditor tenantId="tenant_x" />);

    await waitFor(() => expect(field).toHaveValue(250));
  });
});

describe("TenantQuotaEditor failure references", () => {
  it("shows the response request reference for a failed quota update", async () => {
    const user = userEvent.setup();
    mocks.fetchTenantQuotas.mockResolvedValue(initialQuotas);
    mocks.updateTenantQuotas.mockResolvedValue({
      kind: "failed",
      status: 503,
      message: "Tenant request failed with 503.",
      requestId: "req-tenant-quota-503",
    });

    render(<TenantQuotaEditor tenantId="tenant_x" />);

    await screen.findByLabelText("API requests per window");
    await user.click(screen.getByRole("button", { name: "Review quota update" }));
    await user.click(screen.getByRole("button", { name: "Confirm quota update" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Quota update failed: Tenant request failed with 503.",
    );
    expect(screen.getByText("req-tenant-quota-503")).toBeInTheDocument();
  });

  it("keeps local quota validation reference-free and does not call the API", async () => {
    const user = userEvent.setup();
    mocks.fetchTenantQuotas.mockResolvedValue(initialQuotas);

    render(<TenantQuotaEditor tenantId="tenant_x" />);

    const field = await screen.findByLabelText("API requests per window");
    await user.clear(field);
    await user.type(field, "-1");
    await user.click(screen.getByRole("button", { name: "Review quota update" }));

    expect(
      screen.getAllByRole("alert").find((alert) =>
        alert.textContent?.includes("Quota update failed: Fix the highlighted fields; nothing was sent."),
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Request reference:/)).not.toBeInTheDocument();
    expect(mocks.updateTenantQuotas).not.toHaveBeenCalled();
  });
});
