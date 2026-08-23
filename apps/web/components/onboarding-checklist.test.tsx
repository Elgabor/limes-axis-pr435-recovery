import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

import { ONBOARDING_ENDPOINTS, OnboardingChecklist } from "./onboarding-checklist";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

type Source = "loading" | "api" | "unavailable";

function queryResult(data: unknown, source: Source) {
  return {
    data,
    source,
    error: source === "unavailable" ? "Axis API request failed." : null,
    errorStatus: null,
    isRefreshing: false,
    isLoading: source === "loading",
    isUnavailable: source === "unavailable",
  };
}

/**
 * Registry payloads carrying only the count-bearing fields the checklist
 * reads; per-endpoint counts choose the done-state of each step. Connector
 * fixtures are activated manifests by default; pass a status to vary it.
 */
function registryFixture(endpoint: string, count: number): unknown {
  switch (endpoint) {
    case ONBOARDING_ENDPOINTS.connectors:
      return {
        connectors: Array.from({ length: count }, (_, i) => ({
          connector_id: `c${i}`,
          persisted_manifest: { status: "active_preview" },
        })),
      };
    case ONBOARDING_ENDPOINTS.ontology:
      return { nodes: Array.from({ length: count }, (_, i) => ({ node_id: `n${i}` })) };
    case ONBOARDING_ENDPOINTS.policies:
      return { policy_count: count, active_policy_count: count, policies: [] };
    case ONBOARDING_ENDPOINTS.agents:
      return { agents: Array.from({ length: count }, (_, i) => ({ agent_id: `a${i}` })) };
    case ONBOARDING_ENDPOINTS.workflows:
      return {
        workflow_runs: Array.from({ length: count }, (_, i) => ({ workflow_id: `w${i}` })),
      };
    default:
      throw new Error(`Unexpected onboarding endpoint: ${endpoint}`);
  }
}

function mockRegistries(
  counts: Partial<Record<keyof typeof ONBOARDING_ENDPOINTS, number>>,
  unavailable: string[] = [],
  connectorStatuses: string[] = [],
) {
  mocks.useAxisQuery.mockImplementation((path: string) => {
    const endpointPath = path.split("?", 1)[0];
    const entry = Object.entries(ONBOARDING_ENDPOINTS).find(
      ([, endpoint]) => endpoint === endpointPath,
    );
    if (!entry) {
      throw new Error(`Unexpected onboarding query path: ${path}`);
    }
    if (unavailable.includes(endpointPath)) {
      return queryResult(null, "unavailable");
    }
    const count = counts[entry[0] as keyof typeof ONBOARDING_ENDPOINTS] ?? 0;
    const payload = registryFixture(endpointPath, count) as {
      connectors: Array<{ persisted_manifest: { status: string } }>;
    };
    if (
      endpointPath === ONBOARDING_ENDPOINTS.connectors
      && connectorStatuses.length > 0
    ) {
      payload.connectors.forEach((connector, index) => {
        connector.persisted_manifest.status =
          connectorStatuses[index % connectorStatuses.length];
      });
    }
    return queryResult(payload, "api");
  });
}

beforeEach(() => {
  mocks.useAxisQuery.mockReset();
});

describe("OnboardingChecklist (full)", () => {
  it("shows all five steps with CTA deep links on an empty tenant", () => {
    mockRegistries({});
    render(<OnboardingChecklist variant="full" />);

    expect(
      screen.getByRole("heading", { name: "Set up your governed platform" }),
    ).toBeInTheDocument();
    expect(screen.getByText("0 of 5 setup steps complete")).toBeInTheDocument();

    expect(screen.getByText("Connect a system")).toBeInTheDocument();
    expect(screen.getByText("Import ontology entities")).toBeInTheDocument();
    expect(screen.getByText("Define a policy")).toBeInTheDocument();
    expect(screen.getByText("Register an agent")).toBeInTheDocument();
    expect(screen.getByText("Run a governed workflow")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "Open connectors" })).toHaveAttribute(
      "href",
      "/connectors",
    );
    expect(screen.getByRole("link", { name: "Open ontology" })).toHaveAttribute(
      "href",
      "/ontology",
    );
    expect(screen.getByRole("link", { name: "Open policies" })).toHaveAttribute(
      "href",
      "/policies",
    );
    expect(screen.getByRole("link", { name: "Open agents" })).toHaveAttribute("href", "/agents");
    expect(screen.getByRole("link", { name: "Open workflows" })).toHaveAttribute(
      "href",
      "/workflows",
    );
  });

  it("renders the demo CTA disabled with the coming-soon title until provisioning exists", () => {
    mockRegistries({});
    render(<OnboardingChecklist variant="full" />);

    const demoButton = screen.getByRole("button", { name: "Explore with demo data" });
    expect(demoButton).toBeDisabled();
    expect(demoButton).toHaveAttribute("title", "Coming with demo provisioning");
  });

  it("enables the demo CTA and calls the handler when provisioning is available", async () => {
    mockRegistries({});
    const onExploreDemo = vi.fn();
    const user = userEvent.setup();
    render(<OnboardingChecklist demoAvailable onExploreDemo={onExploreDemo} variant="full" />);

    const demoButton = screen.getByRole("button", { name: "Explore with demo data" });
    expect(demoButton).toBeEnabled();
    await user.click(demoButton);
    expect(onExploreDemo).toHaveBeenCalledTimes(1);
  });

  it("renders the demo bootstrap error inline above the CTA", () => {
    mockRegistries({});
    render(
      <OnboardingChecklist
        demoAvailable
        demoError={{
          code: "forbidden",
          reason: null,
          message: "Axis API request failed with 403",
          requestId: "req-demo-403",
          status: 403,
        }}
        onExploreDemo={() => {}}
        variant="full"
      />,
    );

    expect(screen.getByText("Axis API request failed with 403")).toBeInTheDocument();
    expect(screen.getByText("req-demo-403")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explore with demo data" })).toBeEnabled();
  });

  it("disables the demo CTA and shows the pending label while bootstrapping", () => {
    mockRegistries({});
    render(
      <OnboardingChecklist demoAvailable demoPending onExploreDemo={() => {}} variant="full" />,
    );

    expect(screen.getByRole("button", { name: "Loading demo data…" })).toBeDisabled();
  });

  it("marks completed steps done and reports progress", () => {
    mockRegistries({ connectors: 2, policies: 1 });
    render(<OnboardingChecklist variant="full" />);

    expect(screen.getByText("2 of 5 setup steps complete")).toBeInTheDocument();
    expect(screen.getAllByText("Done")).toHaveLength(2);
    // Completed steps drop their CTA link.
    expect(screen.queryByRole("link", { name: "Open connectors" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open agents" })).toBeInTheDocument();
  });

  it("keeps the connectors step open while registered connectors are not activated yet", () => {
    mockRegistries(
      { connectors: 2, policies: 1 },
      [],
      ["registered_preview_only", "deprecated"],
    );
    render(<OnboardingChecklist variant="full" />);

    expect(screen.getByText("1 of 5 setup steps complete")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open connectors" })).toBeInTheDocument();
  });

  it("scopes every registry query to the supplied tenant", () => {
    mockRegistries({});
    render(<OnboardingChecklist tenantId="tenant_acme" variant="full" />);

    const paths = mocks.useAxisQuery.mock.calls.map(([path]) => path);
    expect(paths).toHaveLength(5);
    expect(paths).toEqual(
      expect.arrayContaining(
        Object.values(ONBOARDING_ENDPOINTS).map(
          (endpoint) => `${endpoint}?tenant_id=tenant_acme`,
        ),
      ),
    );
  });

  it("hides entirely when every step is complete", () => {
    mockRegistries({ connectors: 1, ontology: 1, policies: 1, agents: 1, workflows: 1 });
    const { container } = render(<OnboardingChecklist variant="full" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("treats a failing registry as not-done instead of rendering an error wall", () => {
    mockRegistries({ policies: 1 }, [`${OPERATIONS_API_PREFIX}/connectors`]);
    render(<OnboardingChecklist variant="full" />);

    expect(screen.getByText("1 of 5 setup steps complete")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open connectors" })).toBeInTheDocument();
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/could not be loaded/i)).not.toBeInTheDocument();
  });
});

describe("OnboardingChecklist (compact)", () => {
  it("renders nothing when no step is complete", () => {
    mockRegistries({});
    const { container } = render(<OnboardingChecklist variant="compact" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when every step is complete", () => {
    mockRegistries({ connectors: 1, ontology: 1, policies: 1, agents: 1, workflows: 1 });
    const { container } = render(<OnboardingChecklist variant="compact" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("shows collapsed progress for a partially onboarded tenant and expands to steps", async () => {
    mockRegistries({ connectors: 1, agents: 1, workflows: 1 });
    const user = userEvent.setup();
    render(<OnboardingChecklist variant="compact" />);

    expect(screen.getByText("3 of 5 setup steps complete")).toBeInTheDocument();
    // Steps stay collapsed until expanded.
    expect(screen.queryByRole("link", { name: "Open ontology" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show setup steps" }));
    expect(screen.getByRole("link", { name: "Open ontology" })).toHaveAttribute(
      "href",
      "/ontology",
    );
    expect(screen.getByRole("link", { name: "Open policies" })).toHaveAttribute(
      "href",
      "/policies",
    );
  });
});
