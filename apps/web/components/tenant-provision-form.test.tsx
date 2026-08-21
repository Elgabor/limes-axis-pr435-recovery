import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  provisionTenant: vi.fn(),
  triggerRefresh: vi.fn(),
}));

vi.mock("@/lib/platform-tenants", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/platform-tenants")>()),
  provisionTenant: mocks.provisionTenant,
}));

vi.mock("@/lib/ids", () => ({
  safeRandomUuid: () => "idempotency-test-key",
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ triggerRefresh: mocks.triggerRefresh }),
}));

import { TenantProvisionForm } from "./tenant-provision-form";

beforeEach(() => {
  mocks.provisionTenant.mockReset();
  mocks.triggerRefresh.mockReset();
});

describe("TenantProvisionForm failure references", () => {
  it("shows the response request reference for a failed provision", async () => {
    const user = userEvent.setup();
    mocks.provisionTenant.mockResolvedValue({
      kind: "failed",
      status: 503,
      message: "Tenant request failed with 503.",
      requestId: "req-tenant-provision-503",
    });

    render(<TenantProvisionForm />);

    await user.type(screen.getByLabelText("New tenant id"), "tenant_acme");
    await user.type(screen.getByLabelText("New tenant display name"), "Acme");
    await user.click(screen.getByRole("button", { name: "Provision tenant" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Tenant provisioning failed: Tenant request failed with 503.",
    );
    expect(screen.getByText("req-tenant-provision-503")).toBeInTheDocument();
  });

  it("keeps local form validation reference-free and does not call the API", async () => {
    const user = userEvent.setup();
    render(<TenantProvisionForm />);

    await user.click(screen.getByRole("button", { name: "Provision tenant" }));

    expect(
      screen.getByText(/Fix the highlighted fields; nothing was sent to the API\./),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Request reference:/)).not.toBeInTheDocument();
    expect(mocks.provisionTenant).not.toHaveBeenCalled();
  });
});
