import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ManufacturingWorkflowConsole } from "@/lib/workflow-demo";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
  useConsoleTenantScope: vi.fn(),
  useTenantVocabulary: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/lib/use-console-tenant-scope", () => ({
  IDENTITY_SESSION_ENDPOINT: "/identity/session",
  useConsoleTenantScope: mocks.useConsoleTenantScope,
}));

vi.mock("@/providers/tenant-vocabulary-provider", () => ({
  useTenantVocabulary: mocks.useTenantVocabulary,
}));

import {
  WORKFLOW_RUNS_ENDPOINT,
  WorkflowConsole,
} from "./workflow-console";

const WORKFLOW_RUNS_PATH = `${WORKFLOW_RUNS_ENDPOINT}?tenant_id=tenant_fixture&limit=100`;

const hourAgo = new Date(Date.now() - 3_600_000).toISOString();
const twoHoursAgo = new Date(Date.now() - 7_200_000).toISOString();

export const workflowConsoleFixture: ManufacturingWorkflowConsole = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Runtime contract fixture",
  provenance: "reference_scenario",
  as_of: hourAgo,
  runtime_status: "watch",
  metrics: [
    { label: "Active runs", value: "2", detail: "Fixture detail", status: "ready" },
  ],
  workflow_runs: [
    {
      workflow_id: "wf_supply_fixture",
      name: "Supply Fixture Review",
      domain: "Supply",
      state: "waiting_for_approval",
      status: "action_required",
      owner_role: "supply-owner",
      runtime: "Temporal OSS",
      adapter: "axis-temporal-adapter",
      autonomy_level: "L2",
      started_at: twoHoursAgo,
      eta: "Today 17:30",
      blocker: "Owner approval required",
      objective: "Resolve a delayed supplier batch.",
      current_step: "Approval gate",
      related_risk: "risk_supply_fixture",
      related_assets: ["asset_fixture_line"],
      inputs: ["Supplier status feed"],
      proposed_outputs: ["Expedite fixture batch"],
      pending_signals: [
        {
          signal: "approval_decision",
          required_role: "supply-owner",
          status: "waiting",
          approval_id: "appr_supply_fixture",
        },
      ],
      controls: ["Human approval required"],
      timeline: [
        {
          event: "workflow.started",
          at: twoHoursAgo,
          actor: "axis-workflow-runtime",
          result: "started",
          summary: "Workflow started.",
        },
        {
          event: "approval.requested",
          at: hourAgo,
          actor: "agent_supply_fixture",
          result: "waiting",
          summary: "Approval requested from the supply owner.",
        },
      ],
      audit_scope: "wf_supply_fixture",
      replay_ready: false,
    },
    {
      workflow_id: "wf_ops_fixture",
      name: "Operations Fixture Brief",
      domain: "Operations",
      state: "proposal_ready",
      status: "ready",
      owner_role: "operations-owner",
      runtime: "Temporal OSS",
      adapter: "axis-temporal-adapter",
      autonomy_level: "L1",
      started_at: hourAgo,
      eta: "Today 12:00",
      blocker: null,
      objective: "Prepare read-only shift summary.",
      current_step: "Review summary",
      related_risk: "risk_ops_fixture",
      related_assets: ["asset_fixture_line"],
      inputs: ["Shift status"],
      proposed_outputs: ["Daily brief"],
      pending_signals: [],
      controls: ["Read-only output"],
      timeline: [
        {
          event: "proposal.ready",
          at: hourAgo,
          actor: "agent_ops_fixture",
          result: "ready",
          summary: "Proposal prepared.",
        },
      ],
      audit_scope: "wf_ops_fixture",
      replay_ready: true,
    },
  ],
  runtime_notes: ["Fixture data is scoped to tests."],
};

type MockedSource = "loading" | "api" | "unavailable";

function queryResult(data: unknown, source: MockedSource) {
  return {
    data,
    source,
    error: source === "unavailable" ? "Axis API request failed." : null,
    isRefreshing: false,
    isLoading: source === "loading",
    isUnavailable: source === "unavailable",
  };
}

function mockWorkflowQueries({
  persisted,
}: {
  persisted: { data: ManufacturingWorkflowConsole | null; source: MockedSource };
}) {
  mocks.useAxisQuery.mockImplementation((path: string) => {
    if (path === WORKFLOW_RUNS_PATH) {
      return queryResult(persisted.data, persisted.source);
    }
    return queryResult(null, "loading");
  });
}

beforeEach(() => {
  mocks.useAxisQuery.mockReset();
  mocks.useConsoleTenantScope.mockReset();
  mocks.useConsoleTenantScope.mockReturnValue({
    identity: queryResult(
      {
        authenticated: true,
        tenant_id: "tenant_fixture",
      },
      "api",
    ),
    tenantId: "tenant_fixture",
    tenantQueriesEnabled: true,
  });
  mocks.useTenantVocabulary.mockReturnValue({
    labelDomain: (domain: string) => domain,
  });
});

describe("WorkflowConsole states", () => {
  it("renders a loading skeleton without any error copy while loading", () => {
    mockWorkflowQueries({ persisted: { data: null, source: "loading" } });
    render(<WorkflowConsole />);

    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
  });

  it("renders the ErrorPanel when the workflow API is unavailable", () => {
    mockWorkflowQueries({ persisted: { data: null, source: "unavailable" } });
    render(<WorkflowConsole />);

    expect(
      screen.getByRole("heading", { name: "Workflow API unavailable" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Local fallback workflow records are disabled\./),
    ).toBeInTheDocument();
    // Endpoint stays demoted behind the technical-details expander.
    expect(screen.queryByText(WORKFLOW_RUNS_ENDPOINT)).not.toBeInTheDocument();
  });

  it("renders the EmptyPanel when the persisted endpoint responds with zero runs", () => {
    const emptyConsole = { ...workflowConsoleFixture, workflow_runs: [], metrics: [] };
    mockWorkflowQueries({
      persisted: { data: emptyConsole, source: "api" },
    });
    render(<WorkflowConsole />);

    expect(screen.getByRole("heading", { name: "No workflow runs yet" })).toBeInTheDocument();
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
  });

  it("does not replace an empty persisted dataset with reference records", () => {
    const emptyConsole = { ...workflowConsoleFixture, workflow_runs: [], metrics: [] };
    mockWorkflowQueries({
      persisted: { data: emptyConsole, source: "api" },
    });
    render(<WorkflowConsole />);

    expect(screen.getByRole("heading", { name: "No workflow runs yet" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Supply Fixture Review/ })).not.toBeInTheDocument();
    expect(mocks.useAxisQuery).toHaveBeenCalledTimes(1);
  });

  it("scopes the workflow request and response to the verified tenant", () => {
    mockWorkflowQueries({ persisted: { data: workflowConsoleFixture, source: "api" } });
    render(<WorkflowConsole />);

    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      WORKFLOW_RUNS_PATH,
      expect.objectContaining({ enabled: true, expectedTenantId: "tenant_fixture" }),
    );
  });
});

describe("WorkflowConsole list and filters", () => {
  beforeEach(() => {
    mockWorkflowQueries({ persisted: { data: workflowConsoleFixture, source: "api" } });
  });

  it("lists runs and switches the detail panel on selection", async () => {
    const user = userEvent.setup();
    render(<WorkflowConsole />);

    expect(screen.getByRole("heading", { name: "Supply Fixture Review" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Operations Fixture Brief/ }));
    expect(window.location.search).toContain("workflow_id=wf_ops_fixture");
    expect(
      screen.getByRole("heading", { name: "Operations Fixture Brief" }),
    ).toBeInTheDocument();
  });

  it("uses the tenant label in workflow chips, detail and domain filters", () => {
    mocks.useTenantVocabulary.mockReturnValue({
      labelDomain: (domain: string) => (
        domain === "Supply" ? "Pharmacy supply" : domain
      ),
    });

    render(<WorkflowConsole />);

    expect(screen.getByRole("button", { name: /Supply Fixture Review/ })).toHaveTextContent(
      "Pharmacy supply",
    );
    expect(screen.getByText("Pharmacy supply", { selector: ".eyebrow" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Pharmacy supply" })).toHaveValue("Supply");
  });

  it("filters the list by state and domain", async () => {
    const user = userEvent.setup();
    render(<WorkflowConsole />);

    await user.selectOptions(screen.getByLabelText("State"), "waiting_for_approval");
    expect(window.location.search).toContain("state=waiting_for_approval");
    expect(
      screen.queryByRole("button", { name: /Operations Fixture Brief/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Supply Fixture Review/ })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("State"), "all");
    await user.selectOptions(screen.getByLabelText("Domain"), "Operations");
    expect(
      screen.queryByRole("button", { name: /Supply Fixture Review/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Operations Fixture Brief/ }),
    ).toBeInTheDocument();
  });

  it("shows a zero-results EmptyPanel with a working reset action", async () => {
    const user = userEvent.setup();
    render(<WorkflowConsole />);

    await user.selectOptions(screen.getByLabelText("State"), "proposal_ready");
    await user.selectOptions(screen.getByLabelText("Domain"), "Supply");

    expect(
      screen.getByRole("heading", { name: "No workflows match the current filters" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getByRole("button", { name: /Supply Fixture Review/ })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Operations Fixture Brief/ }),
    ).toBeInTheDocument();
  });
});

describe("WorkflowConsole detail", () => {
  beforeEach(() => {
    mockWorkflowQueries({ persisted: { data: workflowConsoleFixture, source: "api" } });
  });

  it("renders a blocker banner linking to approvals and naming the approval", () => {
    render(<WorkflowConsole />);

    const banner = screen.getByRole("status", { name: "Current blocker" });
    expect(within(banner).getByText("Waiting on a human decision")).toBeInTheDocument();
    expect(within(banner).getByText(/Owner approval required/)).toBeInTheDocument();

    const link = within(banner).getByRole("link", { name: /Review blocking approval/ });
    expect(link).toHaveAttribute("href", "/approvals?approval_id=appr_supply_fixture");
    expect(link).toHaveTextContent("appr_supply_fixture");
  });

  it("omits the blocker banner for workflows that are not blocked", async () => {
    const user = userEvent.setup();
    render(<WorkflowConsole />);

    await user.click(screen.getByRole("button", { name: /Operations Fixture Brief/ }));
    expect(screen.queryByRole("status", { name: "Current blocker" })).not.toBeInTheDocument();
  });

  it("renders the runtime timeline with steps and relative timestamps", () => {
    render(<WorkflowConsole />);

    const timeline = screen.getByRole("table", { name: "Workflow runtime timeline" });
    expect(within(timeline).getByText("workflow.started")).toBeInTheDocument();
    expect(within(timeline).getByText("approval.requested")).toBeInTheDocument();
    expect(within(timeline).getByText("2h ago")).toBeInTheDocument();
    expect(
      within(timeline).getByText("Approval requested from the supply owner."),
    ).toBeInTheDocument();
  });

  it("keeps inputs, outputs and context collapsed until toggled", async () => {
    const user = userEvent.setup();
    render(<WorkflowConsole />);

    expect(screen.queryByText("Supplier status feed")).not.toBeInTheDocument();
    expect(screen.queryByText("Expedite fixture batch")).not.toBeInTheDocument();
    expect(screen.queryByText("risk_supply_fixture")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Inputs" }));
    expect(screen.getByText("Supplier status feed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Proposed outputs" }));
    expect(screen.getByText("Expedite fixture batch")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Related context" }));
    expect(screen.getByText("risk_supply_fixture")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Inputs" }));
    expect(screen.queryByText("Supplier status feed")).not.toBeInTheDocument();
  });

  it("shows pending signals and controls in the detail grid", () => {
    render(<WorkflowConsole />);

    expect(screen.getByText("approval_decision")).toBeInTheDocument();
    expect(screen.getByText("Human approval required")).toBeInTheDocument();
  });
});
