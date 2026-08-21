import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildOntologyEntityDetail } from "@/lib/ontology-demo";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { DEMO_TENANT_ID, OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

import { ontologyFixture } from "./ontology-fixtures";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
  axisFetch: vi.fn(),
  refreshNonce: 0,
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/axis-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/axis-api")>();
  return {
    ...actual,
    axisFetch: mocks.axisFetch,
    axisFetchParsedJson: async function axisFetchParsedJson<T>(
      path: string,
      decoder: (value: unknown) => T,
      options: import("@/lib/axis-api").AxisFetchOptions = {},
    ): Promise<T> {
      const response: Response = await mocks.axisFetch(path, options);
      const body = await response.json();
      const requestId = actual.axisResponseRequestId(response);
      if (!response.ok) {
        throw new actual.AxisApiError(path, response.status, { body, requestId });
      }
      return actual.decodeAxisJson(path, body, decoder, requestId);
    },
  };
});

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ refreshNonce: mocks.refreshNonce }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import { OntologyExplorer } from "../ontology-explorer";
import { OntologyEntityDetail } from "../ontology-entity-detail";
import { OntologyEntitySheet } from "./entity-sheet";

const entityDetail = buildOntologyEntityDetail(ontologyFixture, "asset_line_2");
if (!entityDetail) {
  throw new Error("fixture entity missing");
}

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
};

function mockExplorerScope() {
  mocks.useAxisQuery.mockImplementation((path: string) => {
    if (path === "/identity/session") {
      return { data: publicIdentity, source: "api" };
    }
    if (path === `${OPERATIONS_API_PREFIX}/ontology?tenant_id=${DEMO_TENANT_ID}`) {
      return { data: ontologyFixture, source: "api" };
    }
    return { data: null, source: "loading" };
  });
}

function fulfillEntity(tenantId = DEMO_TENANT_ID) {
  mocks.axisFetch.mockResolvedValue({
    headers: { get: () => null },
    ok: true,
    status: 200,
    json: async () => ({ ...entityDetail, tenant_id: tenantId }),
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/ontology");
  mocks.axisFetch.mockReset();
  mocks.useAxisQuery.mockReset();
  mocks.refreshNonce = 0;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("OntologyEntitySheet", () => {
  it("renders nothing (and fetches nothing) while closed", () => {
    render(
      <OntologyEntitySheet
        nodeId={null}
        onOpenChange={vi.fn()}
        tenantId={DEMO_TENANT_ID}
      />,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mocks.axisFetch).not.toHaveBeenCalled();
  });

  it("shows the entity detail with an 'Open full page' deep link", async () => {
    fulfillEntity();

    render(
      <OntologyEntitySheet
        nodeId="asset_line_2"
        onOpenChange={vi.fn()}
        tenantId={DEMO_TENANT_ID}
      />,
    );

    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByRole("heading", { name: "Line 2 Packaging" }),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: /Open full page/ })).toHaveAttribute(
      "href",
      "/ontology/asset_line_2",
    );
    // The presentational entity core renders inside the sheet.
    expect(within(dialog).getByText("Read-only entity context")).toBeInTheDocument();
    expect(within(dialog).getByText(/connected$/)).toBeInTheDocument();
    expect(mocks.axisFetch).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/ontology/entities/asset_line_2?tenant_id=${DEMO_TENANT_ID}`,
      expect.anything(),
    );
  });

  it("encodes an opaque node id as one detail-path segment without normalizing it", async () => {
    const nodeId = " node/with?# ";
    fulfillEntity();

    render(
      <OntologyEntitySheet
        nodeId={nodeId}
        onOpenChange={vi.fn()}
        tenantId={DEMO_TENANT_ID}
      />,
    );

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("link", { name: /Open full page/ })).toHaveAttribute(
      "href",
      "/ontology/%20node%2Fwith%3F%23%20",
    );
    expect(mocks.axisFetch).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/ontology/entities/%20node%2Fwith%3F%23%20?tenant_id=${DEMO_TENANT_ID}`,
      expect.anything(),
    );
  });

  it("scopes entity reads to an authenticated tenant", async () => {
    mocks.axisFetch.mockResolvedValue({
      headers: { get: () => null },
      ok: true,
      status: 200,
      json: async () => ({ ...entityDetail, tenant_id: "tenant_acme" }),
    });

    render(
      <OntologyEntitySheet
        nodeId="asset_line_2"
        onOpenChange={vi.fn()}
        tenantId="tenant_acme"
      />,
    );

    expect(await screen.findByRole("heading", { name: "Line 2 Packaging" })).toBeInTheDocument();
    expect(mocks.axisFetch).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/ontology/entities/asset_line_2?tenant_id=tenant_acme`,
      expect.anything(),
    );
  });

  it("rejects an entity payload from a different tenant", async () => {
    fulfillEntity(DEMO_TENANT_ID);

    render(
      <OntologyEntitySheet
        nodeId="asset_line_2"
        onOpenChange={vi.fn()}
        tenantId="tenant_acme"
      />,
    );

    expect(
      await screen.findByRole("heading", { name: "Entity API unavailable" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Line 2 Packaging" })).not.toBeInTheDocument();
  });

  it("swaps to a peer entity in place instead of navigating", async () => {
    fulfillEntity();
    const onNavigateToNode = vi.fn();

    render(
      <OntologyEntitySheet
        nodeId="asset_line_2"
        onNavigateToNode={onNavigateToNode}
        onOpenChange={vi.fn()}
        tenantId={DEMO_TENANT_ID}
      />,
    );

    const dialog = await screen.findByRole("dialog");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Fixture Plant" }));

    expect(onNavigateToNode).toHaveBeenCalledWith("org_fixture_plant");
  });

  it("shows the error state when the entity API is unavailable", async () => {
    mocks.axisFetch.mockRejectedValue(new Error("api down"));

    render(
      <OntologyEntitySheet
        nodeId="asset_line_2"
        onOpenChange={vi.fn()}
        tenantId={DEMO_TENANT_ID}
      />,
    );

    expect(
      await screen.findByRole("heading", { name: "Entity API unavailable" }),
    ).toBeInTheDocument();
  });

  it("keeps validated entity data visible when a refresh fails", async () => {
    fulfillEntity();
    const { rerender } = render(
      <OntologyEntitySheet
        nodeId="asset_line_2"
        onOpenChange={vi.fn()}
        tenantId={DEMO_TENANT_ID}
      />,
    );
    expect(
      await screen.findByRole("heading", { name: "Line 2 Packaging" }),
    ).toBeInTheDocument();

    mocks.axisFetch.mockRejectedValueOnce(new Error("refresh failed"));
    mocks.refreshNonce = 1;
    rerender(
      <OntologyEntitySheet
        nodeId="asset_line_2"
        onOpenChange={vi.fn()}
        tenantId={DEMO_TENANT_ID}
      />,
    );

    expect(
      await screen.findByText("Live refresh failed. Showing the last validated entity data."),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Line 2 Packaging" })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Entity API unavailable" }),
    ).not.toBeInTheDocument();
  });

  it("shows the not-found state for a 404", async () => {
    mocks.axisFetch.mockResolvedValue(new Response("{}", {
      headers: { "Content-Type": "application/json" },
      status: 404,
    }));

    render(
      <OntologyEntitySheet
        nodeId="ghost_node"
        onOpenChange={vi.fn()}
        tenantId={DEMO_TENANT_ID}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Entity not found" })).toBeInTheDocument();
  });
});

describe("OntologyEntityDetail tenant scope", () => {
  it("loads the full-page entity from the authenticated tenant", async () => {
    mocks.useAxisQuery.mockImplementation((path: string) =>
      path === "/identity/session"
        ? {
            data: {
              ...publicIdentity,
              authenticated: true,
              mode: "oidc",
              actor_id: "operator_acme",
              tenant_id: "tenant_acme",
            },
            source: "api",
          }
        : { data: null, source: "loading" },
    );
    fulfillEntity("tenant_acme");

    render(<OntologyEntityDetail nodeId="asset_line_2" />);

    expect(await screen.findByRole("heading", { name: "Line 2 Packaging" })).toBeInTheDocument();
    expect(mocks.axisFetch).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/ontology/entities/asset_line_2?tenant_id=tenant_acme`,
      expect.anything(),
    );
  });

  it("fails closed when the full-page identity cannot be verified", () => {
    mocks.useAxisQuery.mockReturnValue({ data: null, source: "unavailable" });

    render(<OntologyEntityDetail nodeId="asset_line_2" />);

    expect(screen.getByRole("heading", { name: "Identity API unavailable" })).toBeInTheDocument();
    expect(mocks.axisFetch).not.toHaveBeenCalled();
  });
});

describe("OntologyExplorer entity slide-over", () => {
  it("opens from graph node activation and preserves graph state on close", async () => {
    mockExplorerScope();
    fulfillEntity();

    render(<OntologyExplorer />);

    // Zoom in so we can assert the graph view survives the sheet round trip.
    const svg = screen.getByTestId("ontology-graph");
    const initialViewBox = svg.getAttribute("viewBox");
    await userEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    const zoomedViewBox = svg.getAttribute("viewBox");
    expect(zoomedViewBox).not.toBe(initialViewBox);

    await userEvent.click(screen.getByRole("link", { name: /Line 2 Packaging — Asset/ }));

    expect(window.location.search).toBe("?entity_id=asset_line_2");

    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByRole("heading", { name: "Line 2 Packaging" }),
    ).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    // No navigation happened and the zoomed view is still applied.
    expect(screen.getByTestId("ontology-graph").getAttribute("viewBox")).toBe(zoomedViewBox);
    expect(window.location.search).toBe("");
  });

  it("opens from a list row without navigating", async () => {
    mockExplorerScope();
    fulfillEntity();

    render(<OntologyExplorer />);

    await userEvent.click(screen.getByRole("button", { name: "List" }));
    const nodesTable = screen.getByRole("table", { name: "Ontology nodes" });
    await userEvent.click(within(nodesTable).getByRole("button", { name: "Line 2 Packaging" }));

    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByRole("heading", { name: "Line 2 Packaging" }),
    ).toBeInTheDocument();
    expect(window.location.search).toBe("?view=list&entity_id=asset_line_2");
  });

  it("opens a directly linked entity without losing the explorer", async () => {
    mockExplorerScope();
    fulfillEntity();
    window.history.replaceState(null, "", "/ontology?entity_id=asset_line_2");
    const go = vi.spyOn(window.history, "go");

    render(<OntologyExplorer />);

    const dialog = await screen.findByRole("dialog");
    expect(
      await within(dialog).findByRole("heading", { name: "Line 2 Packaging" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("ontology-graph")).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(go).not.toHaveBeenCalled();
    expect(window.location.search).toBe("");
  });
});
