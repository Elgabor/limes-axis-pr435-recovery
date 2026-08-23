import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ManufacturingAgentRegistry } from "@/lib/agent-demo";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { DEMO_TENANT_ID, OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

import { agentRegistryFixture } from "./agents-fixtures";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
  useTenantVocabulary: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/use-identity-session", () => ({
  useIdentitySession: () => mocks.useAxisQuery("/identity/session"),
}));

vi.mock("@/providers/tenant-vocabulary-provider", () => ({
  useTenantVocabulary: mocks.useTenantVocabulary,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

import { AgentRegistry } from "../agent-registry";

const publicIdentity: IdentitySessionReadModel = {
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

function queryResult(result: {
  data: unknown;
  errorRequestId?: string | null;
  source: "loading" | "api" | "unavailable";
}) {
  return {
    data: result.data,
    errorRequestId: result.errorRequestId ?? null,
    source: result.source,
    error: result.source === "unavailable" ? "Axis API request failed." : null,
    isRefreshing: false,
    isLoading: result.source === "loading",
    isUnavailable: result.source === "unavailable",
  };
}

function mockRegistry(result: {
  data: ManufacturingAgentRegistry | null;
  errorRequestId?: string | null;
  source: "loading" | "api" | "unavailable";
}, identity: IdentitySessionReadModel = publicIdentity) {
  const tenantId = identity.authenticated ? identity.tenant_id : DEMO_TENANT_ID;
  mocks.useAxisQuery.mockImplementation((path: string) => {
    if (path === "/identity/session") {
      return queryResult({ data: identity, source: "api" });
    }
    if (path === `${OPERATIONS_API_PREFIX}/agents?tenant_id=${tenantId}`) {
      return queryResult(result);
    }
    return queryResult({ data: null, source: "loading" });
  });
}

beforeEach(() => {
  mocks.useAxisQuery.mockReset();
  mocks.useTenantVocabulary.mockReturnValue({
    labelDomain: (domain: string) => domain,
  });
});

describe("AgentRegistry states", () => {
  it("scopes authenticated and public-demo registry reads explicitly", () => {
    const authenticatedIdentity = {
      ...publicIdentity,
      authenticated: true,
      mode: "oidc",
      actor_id: "operator_acme",
      tenant_id: "tenant_acme",
    };
    mockRegistry(
      { data: { ...agentRegistryFixture, tenant_id: "tenant_acme" }, source: "api" },
      authenticatedIdentity,
    );

    const { unmount } = render(<AgentRegistry />);

    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/agents?tenant_id=tenant_acme`,
      expect.objectContaining({ enabled: true, expectedTenantId: "tenant_acme" }),
    );

    unmount();
    mocks.useAxisQuery.mockReset();
    mockRegistry({ data: agentRegistryFixture, source: "api" });
    render(<AgentRegistry />);

    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/agents?tenant_id=${DEMO_TENANT_ID}`,
      expect.objectContaining({ enabled: true, expectedTenantId: DEMO_TENANT_ID }),
    );
  });

  it("fails closed when identity cannot be verified", () => {
    mocks.useAxisQuery.mockImplementation((path: string) =>
      path === "/identity/session"
        ? queryResult({ data: null, source: "unavailable" })
        : queryResult({ data: null, source: "loading" }),
    );

    render(<AgentRegistry />);

    expect(screen.getByRole("heading", { name: "Identity API unavailable" })).toBeInTheDocument();
    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/agents?tenant_id=${DEMO_TENANT_ID}`,
      expect.objectContaining({ enabled: false, expectedTenantId: undefined }),
    );
  });

  it("renders a loading skeleton without any error copy while loading", () => {
    mockRegistry({ data: null, source: "loading" });
    render(<AgentRegistry />);

    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
  });

  it("renders the API request reference inside technical details", async () => {
    const user = userEvent.setup();
    mockRegistry({
      data: null,
      errorRequestId: "request-agent-registry-503",
      source: "unavailable",
    });
    render(<AgentRegistry />);

    expect(
      screen.getByRole("heading", { name: "Agent API unavailable" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Local fallback agent records are disabled\./),
    ).toBeInTheDocument();
    // Endpoint stays demoted behind the technical-details expander.
    expect(screen.queryByText(`${OPERATIONS_API_PREFIX}/agents`)).not.toBeInTheDocument();
    expect(screen.queryByText("request-agent-registry-503")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Technical details" }));

    expect(screen.getByText("request-agent-registry-503")).toBeInTheDocument();
  });

  it("renders the EmptyPanel when the API responds with zero agents", () => {
    mockRegistry({
      data: {
        ...agentRegistryFixture,
        provenance: "empty",
        agents: [],
        metrics: [],
      },
      source: "api",
    });
    render(<AgentRegistry />);

    expect(
      screen.getByRole("heading", { name: "No agents registered yet" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
  });

  it("labels a reference payload without claiming that it is live", () => {
    mockRegistry({
      data: { ...agentRegistryFixture, provenance: "reference_scenario" },
      source: "api",
    });

    render(<AgentRegistry />);

    expect(screen.getByText("agent registry: reference scenario")).toBeInTheDocument();
    expect(screen.queryByText("agent registry: live")).not.toBeInTheDocument();
  });

  it("labels cached registry data stale after a failed refresh", () => {
    mockRegistry({
      data: { ...agentRegistryFixture, provenance: "reference_scenario" },
      source: "unavailable",
    });

    render(<AgentRegistry />);

    expect(screen.getByText("agent registry: stale")).toBeInTheDocument();
    expect(screen.queryByText("agent registry: reference scenario")).not.toBeInTheDocument();
  });
});

describe("AgentRegistry list and filters", () => {
  beforeEach(() => {
    mockRegistry({ data: agentRegistryFixture, source: "api" });
  });

  it("lists agents with name, domain and autonomy level chip", () => {
    render(<AgentRegistry />);

    const supplyItem = screen.getByRole("button", { name: /Supply Risk Agent/ });
    expect(supplyItem).toHaveTextContent("Supply");
    expect(supplyItem).toHaveTextContent("L2");
    expect(screen.getByRole("button", { name: /Quality Hold Agent/ })).toHaveTextContent("L1");
  });

  it("uses the tenant label in agent chips, detail and domain filters", () => {
    mocks.useTenantVocabulary.mockReturnValue({
      labelDomain: (domain: string) => (
        domain === "Supply" ? "Pharmacy supply" : domain
      ),
    });

    render(<AgentRegistry />);

    expect(screen.getByRole("button", { name: /Supply Risk Agent/ })).toHaveTextContent(
      "Pharmacy supply",
    );
    expect(screen.getByText("Pharmacy supply", { selector: ".eyebrow" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Pharmacy supply" })).toHaveValue("Supply");
  });

  it("switches the detail panel when a list item is selected", async () => {
    const user = userEvent.setup();
    render(<AgentRegistry />);

    expect(screen.getByRole("heading", { name: "Supply Risk Agent" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Quality Hold Agent/ }));
    expect(window.location.search).toContain("agent_id=agent_quality_fixture");
    expect(screen.getByRole("heading", { name: "Quality Hold Agent" })).toBeInTheDocument();
  });

  it("filters the list by domain", async () => {
    const user = userEvent.setup();
    render(<AgentRegistry />);

    await user.selectOptions(screen.getByLabelText("Domain"), "Quality");
    expect(window.location.search).toContain("domain=Quality");

    expect(screen.queryByRole("button", { name: /Supply Risk Agent/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Quality Hold Agent/ })).toBeInTheDocument();
  });

  it("shows a zero-results EmptyPanel with a working reset action", async () => {
    const user = userEvent.setup();
    render(<AgentRegistry />);

    await user.selectOptions(screen.getByLabelText("Domain"), "Quality");
    await user.selectOptions(screen.getByLabelText("Autonomy"), "L2");

    expect(
      screen.getByRole("heading", { name: "No agents match the current filters" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getByRole("button", { name: /Supply Risk Agent/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Quality Hold Agent/ })).toBeInTheDocument();
  });
});
