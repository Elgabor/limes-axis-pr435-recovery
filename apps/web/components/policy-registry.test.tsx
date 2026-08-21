import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlatformPolicyRegistry } from "@/lib/platform-policies";

const mocks = vi.hoisted(() => ({
  tenantScope: {
    identity: { data: null, source: "api" as "api" | "unavailable" },
    tenantId: "tenant_acme" as string | null,
    tenantQueriesEnabled: true,
  },
  useAxisQuery: vi.fn(),
}));

vi.mock("@/lib/use-console-tenant-scope", () => ({
  IDENTITY_SESSION_ENDPOINT: "/identity/session",
  useConsoleTenantScope: () => mocks.tenantScope,
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/components/policy-create-form", () => ({
  PolicyCreateForm: ({ tenantId }: { tenantId: string }) => (
    <div data-testid="policy-create-tenant">{tenantId}</div>
  ),
}));

import { PolicyRegistry } from "./policy-registry";

const registry: PlatformPolicyRegistry = {
  tenant_id: "tenant_acme",
  policy_count: 0,
  active_policy_count: 0,
  policies: [],
  policy_notes: [],
};

describe("PolicyRegistry tenant scope", () => {
  beforeEach(() => {
    mocks.tenantScope.identity.source = "api";
    mocks.tenantScope.tenantId = "tenant_acme";
    mocks.tenantScope.tenantQueriesEnabled = true;
    mocks.useAxisQuery.mockReset();
    mocks.useAxisQuery.mockReturnValue({ data: registry, source: "api" });
  });

  it("requests and validates the verified tenant", () => {
    window.history.replaceState(null, "", "/policies?scope=approval_requirement");
    render(<PolicyRegistry />);

    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      "/platform/policies?tenant_id=tenant_acme&scope=approval_requirement",
      expect.objectContaining({ enabled: true, expectedTenantId: "tenant_acme" }),
    );
    expect(screen.getByTestId("policy-create-tenant")).toHaveTextContent("tenant_acme");
    expect(screen.getByRole("heading", { name: "No policies match the current filters" })).toBeInTheDocument();
  });

  it("fails closed when identity is unavailable", () => {
    mocks.tenantScope.identity.source = "unavailable";
    mocks.tenantScope.tenantId = null;
    mocks.tenantScope.tenantQueriesEnabled = false;

    render(<PolicyRegistry />);

    expect(screen.getByRole("heading", { name: "Identity API unavailable" })).toBeInTheDocument();
    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      "/platform/policies",
      expect.objectContaining({ enabled: false }),
    );
  });
});
