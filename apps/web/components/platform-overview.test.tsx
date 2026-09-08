import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";

const mocks = vi.hoisted(() => ({
  axisFetchParsedJson: vi.fn(),
  triggerRefresh: vi.fn(),
  useAxisQuery: vi.fn(),
}));

vi.mock("@/lib/axis-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/axis-api")>()),
  axisFetchParsedJson: mocks.axisFetchParsedJson,
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/use-identity-session", () => ({
  IDENTITY_SESSION_ENDPOINT: "/identity/session",
  useIdentitySession: () => mocks.useAxisQuery("/identity/session"),
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({
    apiBaseUrl: "http://localhost:8000",
    apiStatus: { state: "ready", label: "ready", detail: "" },
    refreshNonce: 0,
    triggerRefresh: mocks.triggerRefresh,
  }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

import { PlatformOverview } from "./platform-overview";
import { AxisApiError } from "@/lib/axis-api";
import {
  approvalInboxFixture,
  auditEventsFixture,
  emptyActionRunsFixture,
  identitySessionFixture,
  modelRoutingFixture,
  overviewFixture,
  policyRegistryFixture,
  snapshotFixture,
} from "./overview/overview-fixtures";
import type {
  IdentitySessionReadModel,
  ManufacturingOverview,
} from "@/lib/platform-overview";
import { parseManufacturingOverview } from "@/lib/runtime-contracts/overview";
import { strings } from "@/lib/strings";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

type Source = "loading" | "api" | "unavailable";

function queryResult(data: unknown, source: Source, errorStatus: number | null = null) {
  return {
    data,
    source,
    error: source === "unavailable" ? "Axis API request failed." : null,
    errorStatus,
    isRefreshing: false,
    isLoading: source === "loading",
    isUnavailable: source === "unavailable",
  };
}

/** Count-bearing registry payloads that drive the onboarding checklist. */
function onboardingRegistryFixtures(count: number): [string, unknown][] {
  const items = (key: string) => Array.from({ length: count }, (_, i) => ({ [key]: `${key}${i}` }));
  return [
    // Connector fixtures are activated manifests so the connectors step reads
    // as done; the checklist only counts activated manifests.
    [
      `${OPERATIONS_API_PREFIX}/connectors`,
      {
        connectors: Array.from({ length: count }, (_, i) => ({
          connector_id: `connector_id${i}`,
          persisted_manifest: { status: "active_preview" },
        })),
      },
    ],
    [`${OPERATIONS_API_PREFIX}/ontology`, { nodes: items("node_id") }],
    [`${OPERATIONS_API_PREFIX}/agents`, { agents: items("agent_id") }],
    [`${OPERATIONS_API_PREFIX}/workflows`, { workflow_runs: items("workflow_id") }],
  ];
}

type MockOptions = {
  /** Endpoints answering 404 (tenant not bootstrapped) instead of failing. */
  notFoundPaths?: string[];
  /** Overrides every checklist registry count, including /platform/policies. */
  onboardingCount?: number;
  identity?: IdentitySessionReadModel;
  overview?: ManufacturingOverview;
};

/** Route the per-path mock so each endpoint can succeed or fail independently. */
function mockQueriesByPath(unavailablePaths: string[] = [], options: MockOptions = {}) {
  const fixtures: [string, unknown][] = [
    ...(options.onboardingCount !== undefined
      ? ([
          [
            "/platform/policies",
            {
              ...policyRegistryFixture,
              policy_count: options.onboardingCount,
              active_policy_count: options.onboardingCount,
            },
          ],
        ] as [string, unknown][])
      : []),
    [`${OPERATIONS_API_PREFIX}/overview`, options.overview ?? overviewFixture],
    [`${OPERATIONS_API_PREFIX}/operations/snapshot`, snapshotFixture],
    [`${OPERATIONS_API_PREFIX}/model-routing`, modelRoutingFixture],
    [`${OPERATIONS_API_PREFIX}/audit/events`, auditEventsFixture],
    [`${OPERATIONS_API_PREFIX}/approvals`, approvalInboxFixture],
    [`${OPERATIONS_API_PREFIX}/actions/runs`, emptyActionRunsFixture],
    ["/platform/policies", policyRegistryFixture],
    ["/identity/session", options.identity ?? identitySessionFixture],
    ...onboardingRegistryFixtures(options.onboardingCount ?? 1),
  ];

  mocks.useAxisQuery.mockImplementation((path: string) => {
    const match = fixtures.find(([prefix]) => path.startsWith(prefix));
    if (!match) {
      throw new Error(`Unexpected overview query path: ${path}`);
    }
    if (options.notFoundPaths?.some((prefix) => path.startsWith(prefix))) {
      return queryResult(null, "unavailable", 404);
    }
    if (unavailablePaths.some((prefix) => path.startsWith(prefix))) {
      return queryResult(null, "unavailable");
    }
    return queryResult(match[1], "api");
  });
}

function renderOverview() {
  return render(
    <ToastProvider>
      <PlatformOverview />
    </ToastProvider>,
  );
}

beforeEach(() => {
  mocks.axisFetchParsedJson.mockReset();
  mocks.triggerRefresh.mockReset();
  mocks.useAxisQuery.mockReset();
});

describe("PlatformOverview hero", () => {
  it("leads with recorded activity instead of repeating a scenario title", () => {
    mockQueriesByPath();
    renderOverview();

    expect(screen.getByRole("heading", { name: "Recorded activity" })).toBeInTheDocument();
    expect(screen.queryByText("Plant Operations Cockpit")).not.toBeInTheDocument();
    expect(screen.queryByText(/Operations Plant Operations Cockpit/)).not.toBeInTheDocument();
  });

  it("parses and renders a tenant whose scenario is null without empty path segments", () => {
    const overview = parseManufacturingOverview({
      ...overviewFixture,
      plant_name: "Northwind Press",
      scenario: null,
      provenance: "empty",
    });
    mockQueriesByPath([], { overview });

    renderOverview();

    // Vertical-neutral: this console is not manufacturing-only, and a tenant
    // with no scenario of its own must not be labelled as one.
    expect(
      screen.getByRole("heading", { name: "Recorded activity" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Manufacturing overview/)).not.toBeInTheDocument();
    expect(screen.getByTestId("hero-audit-count")).toBeInTheDocument();
    expect(screen.getByText(/Northwind Press/)).not.toHaveTextContent(/null|^\s*\//);
  });

  it("shows the same audit registry count in the hero and the evidence feed", () => {
    mockQueriesByPath();
    renderOverview();

    const heroCount = screen.getByTestId("hero-audit-count");
    expect(heroCount).toHaveTextContent(/^4$/);
    expect(screen.getByText("Showing 4 of 4 recent events")).toBeInTheDocument();
    // The static seeded "Audit" metric string never renders anywhere.
    expect(screen.queryByText(/128 events/)).not.toBeInTheDocument();
  });

  it("labels mixed source provenance instead of collapsing the overview into a live claim", () => {
    mockQueriesByPath([], {
      overview: { ...overviewFixture, provenance: "reference_scenario" },
    });
    renderOverview();

    const sources = screen.getByLabelText("Overview data sources");
    expect(within(sources).getByText("Context: example"))
      .toBeInTheDocument();
    expect(within(sources).getByText("Operations: live")).toBeInTheDocument();
    expect(within(sources).getByText("Audit: live")).toBeInTheDocument();

    const posture = screen.getByLabelText("Platform posture");
    const cards = within(posture).getAllByRole("listitem");
    const agentsCard = cards.find((card) => within(card).queryByText("Agents"));
    const connectorsCard = cards.find((card) => within(card).queryByText("Connector activity"));
    const modelsCard = cards.find((card) => within(card).queryByText("Models"));

    expect(agentsCard).toBeDefined();
    expect(connectorsCard).toBeDefined();
    expect(modelsCard).toBeDefined();
    expect(within(agentsCard as HTMLElement).getByText("agents: reference scenario"))
      .toBeInTheDocument();
    expect(within(connectorsCard as HTMLElement).getByText("connector activity: live"))
      .toBeInTheDocument();
    expect(within(modelsCard as HTMLElement).getByText("models: reference scenario"))
      .toBeInTheDocument();

    const attentionSources = screen.getByLabelText("Needs attention data sources");
    expect(within(attentionSources).getByText("Approvals: example"))
      .toBeInTheDocument();
    expect(within(attentionSources).getByText("Outcomes: live"))
      .toBeInTheDocument();
  });

  it("scopes every overview request to the API-verified authenticated tenant", () => {
    mockQueriesByPath([], {
      identity: {
        ...identitySessionFixture,
        authenticated: true,
        mode: "secure_oidc_cookie",
        actor_id: "acme-operator",
        tenant_id: "tenant_acme",
      },
    });
    renderOverview();

    const paths = mocks.useAxisQuery.mock.calls.map(([path]) => path);
    expect(paths).toContain(`${OPERATIONS_API_PREFIX}/overview?tenant_id=tenant_acme`);
    expect(paths).toContain(
      `${OPERATIONS_API_PREFIX}/operations/snapshot?tenant_id=tenant_acme`,
    );
    expect(paths).toContain(`${OPERATIONS_API_PREFIX}/model-routing?tenant_id=tenant_acme`);
    expect(paths).toContain(
      `${OPERATIONS_API_PREFIX}/audit/events?tenant_id=tenant_acme&limit=25`,
    );
    expect(paths.filter((path) => path.includes("tenant_demo_manufacturing"))).toHaveLength(0);
  });
});

describe("PlatformOverview per-section degradation", () => {
  it("keeps the evidence feed and posture cards when the overview endpoint fails", () => {
    mockQueriesByPath([`${OPERATIONS_API_PREFIX}/overview`]);
    renderOverview();

    expect(
      screen.getByRole("heading", { name: strings.overview.hero.error.title }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Approval Decision Recorded/ }),
    ).toBeInTheDocument();
    const modelsCard = screen
      .getAllByRole("listitem")
      .find((item) => within(item).queryByText("Models"));
    expect(modelsCard).toBeDefined();
    expect(within(modelsCard as HTMLElement).getByText("2")).toBeInTheDocument();
  });

  it("keeps the hero and needs-attention strip when the audit endpoint fails", () => {
    mockQueriesByPath([`${OPERATIONS_API_PREFIX}/audit/events`]);
    renderOverview();

    expect(screen.getByRole("heading", { name: "Recorded activity" })).toBeInTheDocument();
    expect(screen.getByText("Expedite supplier batch")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Audit evidence API unavailable" }),
    ).toBeInTheDocument();
  });

  it("fails closed at identity before loading any tenant-scoped data", () => {
    mockQueriesByPath([
      `${OPERATIONS_API_PREFIX}`,
      "/platform/policies",
      "/identity/session",
    ]);
    renderOverview();

    expect(screen.getByRole("heading", { name: "Identity API unavailable" })).toBeInTheDocument();
    expect(
      screen.getByText("Tenant-scoped data is not loaded until identity is available.", {
        exact: false,
      }),
    ).toBeInTheDocument();
  });

  it("does not fall back to demo data when an authenticated tenant claim is missing", () => {
    mockQueriesByPath([], {
      identity: {
        ...identitySessionFixture,
        authenticated: true,
        mode: "secure_oidc_cookie",
        actor_id: "acme-operator",
        tenant_id: null,
      },
    });
    renderOverview();

    expect(
      screen.getByRole("heading", { name: "Authenticated tenant missing" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Axis will not fall back to demo data", { exact: false }),
    ).toBeInTheDocument();
  });
});

describe("PlatformOverview onboarding checklist", () => {
  it("replaces the control room with the setup checklist when the overview 404s on a healthy API", () => {
    mockQueriesByPath([], {
      notFoundPaths: [`${OPERATIONS_API_PREFIX}/overview`],
      onboardingCount: 0,
    });
    renderOverview();

    expect(
      screen.getByRole("heading", { name: "Set up your governed platform" }),
    ).toBeInTheDocument();
    expect(screen.getByText("0 of 5 setup steps complete")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open connectors" })).toHaveAttribute(
      "href",
      "/connectors",
    );
    // No error wall: the 404 means "not bootstrapped", not "API down".
    expect(
      screen.queryByRole("heading", { name: "Operations API unavailable" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the error wall when the API is down instead of showing the checklist", () => {
    mockQueriesByPath([
      `${OPERATIONS_API_PREFIX}`,
      "/platform/policies",
      "/identity/session",
    ]);
    renderOverview();

    expect(screen.getByRole("heading", { name: "Identity API unavailable" })).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Set up your governed platform" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/setup steps complete/)).not.toBeInTheDocument();
  });

  it("shows the compact setup strip on the control room when onboarding is partial", () => {
    mockQueriesByPath([`${OPERATIONS_API_PREFIX}/ontology`]);
    renderOverview();

    expect(screen.getByText("4 of 5 setup steps complete")).toBeInTheDocument();
    // The control room still renders around the strip.
    expect(screen.getByRole("heading", { name: "Recorded activity" })).toBeInTheDocument();
  });

  it("hides the checklist entirely once every setup step is complete", () => {
    mockQueriesByPath();
    renderOverview();

    expect(screen.queryByText(/setup steps complete/)).not.toBeInTheDocument();
  });
});

describe("PlatformOverview demo bootstrap CTA", () => {
  function renderEmptyTenant() {
    mockQueriesByPath([], {
      notFoundPaths: [`${OPERATIONS_API_PREFIX}/overview`],
      onboardingCount: 0,
    });
    return renderOverview();
  }

  it("POSTs the bootstrap request, toasts, and refreshes the console on success", async () => {
    mocks.axisFetchParsedJson.mockResolvedValue({
      tenant_id: "tenant_demo_manufacturing",
      scenario: "Plant Operations Cockpit",
      plant_name: "Ravenna Works",
      bootstrapped: true,
      surfaces: [],
      audit_event_id: "11111111-1111-4111-8111-111111111111",
      idempotent_replay: false,
    });
    const user = userEvent.setup();
    renderEmptyTenant();

    const demoButton = screen.getByRole("button", { name: "Explore with demo data" });
    expect(demoButton).toBeEnabled();
    await user.click(demoButton);

    expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(1);
    const [endpoint, , options] = mocks.axisFetchParsedJson.mock.calls[0];
    expect(endpoint).toBe("/demo/bootstrap");
    expect(options).toMatchObject({
      method: "POST",
      body: {
        tenant_id: "tenant_demo_manufacturing",
        actor_scopes: ["demo:scenario:bootstrap"],
      },
    });
    expect((options as { body: { requested_by: string } }).body.requested_by).toBeTruthy();

    expect(await screen.findByText("Demo data loaded")).toBeInTheDocument();
    expect(mocks.triggerRefresh).toHaveBeenCalledTimes(1);
  });

  it("renders the bootstrap failure inline on the checklist without refreshing", async () => {
    mocks.axisFetchParsedJson.mockRejectedValue(
      new AxisApiError("/demo/bootstrap", 403, {
        body: { detail: { message: "Demo bootstrap forbidden", debug: "secret-debug" } },
        requestId: "req-demo-bootstrap-403",
      }),
    );
    const user = userEvent.setup();
    renderEmptyTenant();

    await user.click(screen.getByRole("button", { name: "Explore with demo data" }));

    expect(await screen.findByText("Demo bootstrap forbidden")).toBeInTheDocument();
    expect(screen.getByText("req-demo-bootstrap-403")).toBeInTheDocument();
    expect(screen.queryByText(/secret-debug/)).not.toBeInTheDocument();
    expect(mocks.triggerRefresh).not.toHaveBeenCalled();
    expect(screen.queryByText("Demo data loaded")).not.toBeInTheDocument();
    // The checklist stays actionable for a retry.
    expect(screen.getByRole("button", { name: "Explore with demo data" })).toBeEnabled();
  });
});

describe("PlatformOverview dropped surfaces", () => {
  it("no longer renders the demo-readiness, domain-graph, or routing-strip panels", () => {
    mockQueriesByPath();
    renderOverview();

    expect(screen.queryByText("Feedback environment")).not.toBeInTheDocument();
    expect(screen.queryByText("Domain graph")).not.toBeInTheDocument();
    expect(screen.queryByText("Persisted routing posture")).not.toBeInTheDocument();
    expect(screen.queryByText(/records across/)).not.toBeInTheDocument();
  });
});
