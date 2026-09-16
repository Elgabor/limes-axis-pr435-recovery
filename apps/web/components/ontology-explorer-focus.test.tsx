import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildOntologyEntityDetail } from "@/lib/ontology-demo";
import { strings } from "@/lib/strings";
import { ontologyFixture } from "./ontology/ontology-fixtures";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
  useOntologyEntity: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({ useAxisQuery: mocks.useAxisQuery }));
vi.mock("@/lib/use-console-tenant-scope", () => ({
  IDENTITY_SESSION_ENDPOINT: "/identity/session",
  useConsoleTenantScope: () => ({
    identity: { source: "api" },
    tenantId: "tenant_fixture",
    tenantQueriesEnabled: true,
  }),
}));
vi.mock("@/components/ontology/use-ontology-entity", () => ({
  useOntologyEntity: mocks.useOntologyEntity,
}));
vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ refreshNonce: 0 }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { OntologyExplorer } from "./ontology-explorer";

type Surface = "graph" | "table" | "card";
const surfaces: Surface[] = ["graph", "table", "card"];

function renderSurface(surface: Surface) {
  vi.stubGlobal("innerWidth", surface === "card" ? 390 : 1280);
  window.history.replaceState(null, "", `/ontology?view=${surface === "graph" ? "graph" : "list"}`);
  return render(<OntologyExplorer />);
}

function controlsFor(surface: Surface) {
  if (surface === "graph") {
    return within(screen.getByTestId("ontology-graph")).getAllByRole("link");
  }
  const container = surface === "table"
    ? screen.getByRole("table", { name: "Ontology nodes" })
    : screen.getByLabelText("Business objects");
  return within(container).getAllByRole("button");
}

async function expectFocusReturned(opener: Element) {
  await waitFor(() => {
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
  expect(new URLSearchParams(window.location.search).has("entity_id")).toBe(false);
}

async function expectFallbackFocus() {
  await waitFor(() => {
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: strings.clarity.ontologyObjects })).toHaveFocus();
  });
  expect(new URLSearchParams(window.location.search).has("entity_id")).toBe(false);
}

beforeEach(() => {
  vi.stubGlobal("innerWidth", 1280);
  window.history.replaceState(null, "", "/ontology");
  mocks.useAxisQuery.mockReturnValue({ data: ontologyFixture, source: "api" });
  mocks.useOntologyEntity.mockImplementation((nodeId: string | null) => ({
    detail: nodeId ? buildOntologyEntityDetail(ontologyFixture, nodeId) : null,
    endpoint: null,
    errorRequestId: null,
    source: "api",
  }));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("ontology entity focus return", () => {
  it.each(surfaces)("returns to the %s opener after Enter and Escape, then resumes Tab", async (surface) => {
    const user = userEvent.setup();
    renderSurface(surface);
    const controls = controlsFor(surface);
    const opener = controls[1];
    act(() => opener.focus());

    await user.keyboard("{Enter}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await expectFocusReturned(opener);

    await user.tab();
    expect(controls[2]).toHaveFocus();
    expect(new URLSearchParams(window.location.search).get("view"))
      .toBe(surface === "graph" ? "graph" : "list");
  });

  it.each(surfaces)("returns to the clicked %s control when Close is activated", async (surface) => {
    const user = userEvent.setup();
    renderSurface(surface);
    const opener = controlsFor(surface)[1];

    await user.click(opener);
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Close" }));

    await expectFocusReturned(opener);
  });

  it("preserves the original opener through peer traversal and browser Back/Forward", async () => {
    const user = userEvent.setup();
    renderSurface("table");
    const opener = within(screen.getByRole("table", { name: "Ontology nodes" }))
      .getByRole("button", { name: "Line 2 Packaging" });
    await user.click(opener);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Fixture Plant" }));
    expect(within(screen.getByRole("dialog")).getByRole("heading", { name: "Fixture Plant" }))
      .toBeInTheDocument();

    act(() => window.history.back());
    await waitFor(() => {
      expect(within(screen.getByRole("dialog")).getByRole("heading", { name: "Line 2 Packaging" }))
        .toBeInTheDocument();
    });
    act(() => window.history.back());
    await expectFocusReturned(opener);
    act(() => window.history.forward());
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await expectFocusReturned(opener);
  });

  it.each(["asset_line_2", "missing-entity"])("uses the explorer heading when a direct link has no opener (%s)", async (nodeId) => {
    const user = userEvent.setup();
    window.history.replaceState(
      { unrelatedRouterState: "retained" },
      "",
      `/ontology?view=list&entity_id=${nodeId}&context=retained`,
    );
    const go = vi.spyOn(window.history, "go");
    render(<OntologyExplorer />);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Close" }));

    await expectFallbackFocus();
    expect(new URLSearchParams(window.location.search).get("view")).toBe("list");
    expect(new URLSearchParams(window.location.search).get("context")).toBe("retained");
    expect(window.history.state.unrelatedRouterState).toBe("retained");
    expect(go).not.toHaveBeenCalled();
  });

  it("falls back when refreshed records remove the opening graph node", async () => {
    const user = userEvent.setup();
    const { rerender } = renderSurface("graph");
    const opener = screen.getByRole("link", { name: /Line 2 Packaging — Asset/ });
    await user.click(opener);
    mocks.useAxisQuery.mockReturnValue({
      data: {
        ...ontologyFixture,
        nodes: ontologyFixture.nodes.filter((node) => node.node_id !== "asset_line_2"),
        relationships: ontologyFixture.relationships.filter(
          (relationship) => relationship.source_id !== "asset_line_2" && relationship.target_id !== "asset_line_2",
        ),
      },
      source: "api",
    });
    rerender(<OntologyExplorer />);
    expect(opener.isConnected).toBe(false);
    await user.keyboard("{Escape}");

    await expectFallbackFocus();
  });

  it("keeps focus trapped in the open sheet and preserves the graph zoom on close", async () => {
    const user = userEvent.setup();
    renderSurface("graph");
    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    const graph = screen.getByTestId("ontology-graph");
    const viewBox = graph.getAttribute("viewBox");
    const opener = controlsFor("graph")[1];
    act(() => opener.focus());
    await user.keyboard(" ");
    const dialog = screen.getByRole("dialog");
    const first = within(dialog).getByRole("link", { name: /Open full page/ });
    const last = within(dialog).getByRole("button", { name: "Close" });
    act(() => first.focus());

    await user.tab({ shift: true });
    expect(last).toHaveFocus();
    await user.tab();
    expect(first).toHaveFocus();
    await user.keyboard("{Escape}");
    await expectFocusReturned(opener);
    expect(graph).toHaveAttribute("viewBox", viewBox);
  });
});
