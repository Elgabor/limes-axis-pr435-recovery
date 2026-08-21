import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TenantRecord } from "@/lib/platform-tenants";

const mocks = vi.hoisted(() => ({
  suspendTenant: vi.fn(),
  triggerRefresh: vi.fn(),
}));

vi.mock("@/lib/platform-tenants", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/platform-tenants")>()),
  suspendTenant: mocks.suspendTenant,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ triggerRefresh: mocks.triggerRefresh }),
}));

import { TenantLifecycleActions } from "./tenant-lifecycle-actions";

const activeTenant: TenantRecord = {
  tenant_id: "tenant_acme",
  display_name: "Acme",
  description: "",
  status: "active",
  created_by: "platform-tenant-operator-role",
  audit_event_type: "platform.tenant.provisioned",
  created_at: "2026-07-01T08:00:00Z",
  updated_at: "2026-07-01T08:00:00Z",
};

beforeEach(() => {
  mocks.suspendTenant.mockReset();
  mocks.triggerRefresh.mockReset();
});

describe("TenantLifecycleActions failure references", () => {
  it("shows the response request reference for a lifecycle conflict", async () => {
    const user = userEvent.setup();
    mocks.suspendTenant.mockResolvedValue({
      kind: "conflict",
      reason: "tenant_not_active",
      message: "Tenant is no longer active.",
      requestId: "req-tenant-suspend-409",
    });

    render(<TenantLifecycleActions tenant={activeTenant} />);

    await user.type(screen.getByLabelText("Suspension reason"), "Maintenance window");
    await user.click(screen.getByRole("button", { name: "Suspend tenant" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Lifecycle action failed: Tenant is no longer active. (tenant_not_active)",
    );
    expect(screen.getByText("req-tenant-suspend-409")).toBeInTheDocument();
  });

  it("keeps the required-reason gate reference-free and does not call the API", async () => {
    const user = userEvent.setup();
    render(<TenantLifecycleActions tenant={activeTenant} />);

    await user.click(screen.getByRole("button", { name: "Suspend tenant" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Lifecycle action failed: A suspension reason is required.",
    );
    expect(screen.queryByText(/Request reference:/)).not.toBeInTheDocument();
    expect(mocks.suspendTenant).not.toHaveBeenCalled();
  });
});
