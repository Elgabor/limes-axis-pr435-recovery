import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { DEMO_TENANT_ID, OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";
import { ontologyFixture } from "./ontology/ontology-fixtures";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
  axisFetch: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/use-identity-session", () => ({
  useIdentitySession: () => mocks.useAxisQuery("/identity/session"),
}));

vi.mock("@/lib/axis-api", () => ({
  axisFetch: mocks.axisFetch,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ refreshNonce: 0 }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { OntologyExplorer } from "./ontology-explorer";

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

function queryResult(data: unknown, source: "loading" | "api" | "unavailable" = "api") {
  return { data, source, isLoading: source === "loading", isUnavailable: source === "unavailable" };
}

function mockOntology(
  identity: IdentitySessionReadModel = publicIdentity,
  provenance: "reference_scenario" | "live" | "empty" = ontologyFixture.provenance,
) {
  const tenantId = identity.authenticated ? identity.tenant_id : DEMO_TENANT_ID;
  mocks.useAxisQuery.mockImplementation((path: string) => {
    if (path === "/identity/session") {
      return queryResult(identity);
    }
    if (path === `${OPERATIONS_API_PREFIX}/ontology?tenant_id=${tenantId}`) {
      return queryResult({ ...ontologyFixture, tenant_id: tenantId, provenance });
    }
    return queryResult(null, "loading");
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/ontology");
  mocks.useAxisQuery.mockReset();
  mockOntology();
});

describe("OntologyExplorer", () => {
  it("scopes authenticated and public-demo ontology reads explicitly", () => {
    const authenticatedIdentity: IdentitySessionReadModel = {
      ...publicIdentity,
      authenticated: true,
      mode: "oidc",
      actor_id: "operator_acme",
      tenant_id: "tenant_acme",
    };
    mockOntology(authenticatedIdentity);

    const { unmount } = render(<OntologyExplorer />);

    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/ontology?tenant_id=tenant_acme`,
      expect.objectContaining({ enabled: true, expectedTenantId: "tenant_acme" }),
    );

    unmount();
    mocks.useAxisQuery.mockReset();
    mockOntology();
    render(<OntologyExplorer />);

    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/ontology?tenant_id=${DEMO_TENANT_ID}`,
      expect.objectContaining({ enabled: true, expectedTenantId: DEMO_TENANT_ID }),
    );
  });

  it("renders no per-type metric cards", () => {
    render(<OntologyExplorer />);

    expect(screen.queryByText("Mapped demo ontology nodes")).not.toBeInTheDocument();
  });

  it("labels reference ontology records as a scenario rather than live data", () => {
    mockOntology(publicIdentity, "reference_scenario");

    const { container } = render(<OntologyExplorer />);

    const source = container.querySelector('[data-source-state="reference"]');
    expect(source).toHaveTextContent("ontology: reference scenario");
    expect(container.querySelector('[data-source-state="live"]')).toBeNull();
  });

  it("shows node-type counts inside the graph legend", () => {
    render(<OntologyExplorer />);

    const legend = screen.getByLabelText("Ontology graph legend");
    expect(within(legend).getByText("Organization ×1")).toBeInTheDocument();
    expect(within(legend).getByText("Asset ×2")).toBeInTheDocument();
    expect(within(legend).getByText("Policy ×1")).toBeInTheDocument();
    // The existing legend markers stay in the same row.
    expect(within(legend).getByText("Entity")).toBeInTheDocument();
    expect(within(legend).getByText("Relation")).toBeInTheDocument();
  });

  it("zooms the graph with the +/− controls and resets the view", async () => {
    render(<OntologyExplorer />);

    const svg = screen.getByTestId("ontology-graph");
    const initialViewBox = svg.getAttribute("viewBox");
    expect(initialViewBox).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(svg.getAttribute("viewBox")).not.toBe(initialViewBox);

    await userEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(svg.getAttribute("viewBox")).toBe(initialViewBox);

    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    await userEvent.click(screen.getByRole("button", { name: "Reset view" }));
    expect(svg.getAttribute("viewBox")).toBe(initialViewBox);
  });

  it("keeps the graph and list views working", async () => {
    render(<OntologyExplorer />);

    expect(screen.getByTestId("ontology-graph")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "List" }));

    expect(screen.queryByTestId("ontology-graph")).not.toBeInTheDocument();
    expect(window.location.search).toBe("?view=list");
    const nodesTable = screen.getByRole("table", { name: "Ontology nodes" });
    expect(within(nodesTable).getByText("Line 2 Packaging")).toBeInTheDocument();
  });

  it("restores a shareable list view from the URL", () => {
    window.history.replaceState(null, "", "/ontology?view=list");

    render(<OntologyExplorer />);

    expect(screen.queryByTestId("ontology-graph")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
  });
});
