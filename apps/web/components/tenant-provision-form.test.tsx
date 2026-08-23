import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IdentitySessionReadModel } from "@/lib/platform-overview";

const mocks = vi.hoisted(() => ({
  provisionTenant: vi.fn(),
  triggerRefresh: vi.fn(),
  useAxisQuery: vi.fn(),
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

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/use-identity-session", () => ({
  useIdentitySession: () => mocks.useAxisQuery("/identity/session"),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ triggerRefresh: mocks.triggerRefresh }),
}));

import { TenantProvisionForm } from "./tenant-provision-form";

const publicDemoIdentity: IdentitySessionReadModel = {
  authenticated: false,
  mode: "public_demo",
  actor_id: null,
  tenant_id: null,
  scopes: [],
  expires_at: null,
  api_auth_required: false,
  enterprise_sso_ready: false,
  readiness_status: "ready",
  issuer: "",
  audience: "",
  jwks_source: "disabled",
  session_boundary: "public_demo",
  capabilities: [],
  limitations: [],
  notes: [],
  unauthenticated_reason: null,
};

beforeEach(() => {
  mocks.provisionTenant.mockReset();
  mocks.triggerRefresh.mockReset();
  mocks.useAxisQuery.mockReset();
  mocks.useAxisQuery.mockImplementation(() => ({
    data: publicDemoIdentity,
    source: "api",
    errorRequestId: null,
  }));
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

  it("replaces provisioning with an SSO gate when sign-in is enforced", () => {
    mocks.useAxisQuery.mockImplementation(() => ({
      data: {
        ...publicDemoIdentity,
        mode: "sso",
        api_auth_required: true,
        enterprise_sso_ready: true,
        session_boundary: "cookie",
        jwks_source: "remote",
      },
      source: "api",
      errorRequestId: null,
    }));

    render(<TenantProvisionForm />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Sign in with SSO to provision tenants.",
    );
    expect(
      screen.queryByRole("button", { name: "Provision tenant" }),
    ).not.toBeInTheDocument();
  });
});
