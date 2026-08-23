import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";
import type { ActionRunList } from "@/lib/action-demo";
import type { ManufacturingApprovalInbox } from "@/lib/approval-demo";

const mocks = vi.hoisted(() => ({
  axisFetchParsedJson: vi.fn(),
  triggerRefresh: vi.fn(),
  useAxisQuery: vi.fn(),
  useTenantVocabulary: vi.fn(),
}));

vi.mock("@/lib/axis-api", () => ({
  axisFetchParsedJson: mocks.axisFetchParsedJson,
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

vi.mock("@/providers/tenant-vocabulary-provider", () => ({
  useTenantVocabulary: mocks.useTenantVocabulary,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

import { ApprovalInbox } from "./approval-inbox";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

const inboxFixture: ManufacturingApprovalInbox = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Runtime contract fixture",
  provenance: "reference_scenario",
  as_of: "2026-07-10T09:00:00+02:00",
  queue_status: "action_required",
  policy_notes: ["Fixture data is scoped to tests."],
  approvals: [
    {
      approval_id: "appr_supply_fixture",
      action: "Expedite fixture batch",
      risk_level: "high",
      status: "pending",
      requested_by: "agent_supply_fixture",
      owner_role: "plant-operations-owner",
      due: "Today 17:30",
      workflow_id: "wf_supply_fixture_with_a_very_long_identifier_suffix",
      domain: "Supply",
      summary: "Approve or reject a governed supply action.",
      evidence: ["Supplier confirmed capacity for the expedite window."],
      data_accessed: ["Supplier status"],
      risks: ["External shipment mutation"],
      alternatives: ["Adjust production schedule"],
      estimated_cost: "EUR 120",
      model_policy: "no-external-egress",
      required_permission: "approvals:supply:decide",
      audit_event_preview: {
        event: "approval.decision.recorded",
        actor_role: "plant-operations-owner",
        scope: "wf_supply_fixture",
        result: "pending",
      },
      decision_options: [
        {
          decision: "approve",
          label: "Approve & execute",
          consequence: "The expedite order is dispatched to the supplier.",
        },
        {
          decision: "reject",
          label: "Reject",
          consequence: "The current production plan stays unchanged.",
        },
      ],
    },
    {
      approval_id: "appr_quality_fixture",
      action: "Place fixture quality hold",
      risk_level: "medium",
      status: "pending",
      requested_by: "agent_quality_fixture",
      owner_role: "quality-owner",
      due: "Today 18:00",
      workflow_id: "wf_quality_fixture",
      domain: "Quality",
      summary: "Review quality hold evidence.",
      evidence: ["QMS deviation recorded on lot 42."],
      data_accessed: ["QMS deviation summary"],
      risks: ["Production delay"],
      alternatives: ["Escalate to quality review"],
      estimated_cost: "EUR 0",
      model_policy: "local-only",
      required_permission: "approvals:quality:decide",
      audit_event_preview: {
        event: "approval.decision.recorded",
        actor_role: "quality-owner",
        scope: "wf_quality_fixture",
        result: "pending",
      },
      decision_options: [
        {
          decision: "approve",
          label: "Approve hold",
          consequence: "The batch is held for quality review.",
        },
        {
          decision: "reject",
          label: "Reject",
          consequence: "The batch is released to shipping.",
        },
      ],
    },
  ],
};

const persistenceResultFixture = {
  tenant_id: "tenant_fixture",
  approval_id: "appr_supply_fixture",
  workflow_id: "wf_supply_fixture_with_a_very_long_identifier_suffix",
  action_id: "act_fixture",
  decision: "approve",
  status: "approved",
  actor_id: "plant-operations-owner-role",
  audit_event_id: "22222222-2222-4222-8222-222222222222",
  audit_event_type: "approval.decision.recorded",
  persisted: true,
  permission_decision: { allowed: true, reason: "required_scope_present" },
  workflow_signal: {
    workflow_id: "wf_supply_fixture_with_a_very_long_identifier_suffix",
    status: "signaled",
    adapter: "memory",
    signal_name: "approval_decision",
    payload: { approval_id: "appr_supply_fixture", approved: true },
  },
  workflow_signal_status: "signaled",
};

function mockQuery(result: {
  data: ManufacturingApprovalInbox | null;
  source: "loading" | "api" | "unavailable";
}, auditEvents: Array<{
  evidence_refs: string[];
  payload_preview: Record<string, string>;
}> = [], actionRuns: {
  data: ActionRunList | null;
  source: "loading" | "api" | "unavailable";
} = {
  data: { tenant_id: "tenant_fixture", runs: [] },
  source: "api",
}) {
  mocks.useAxisQuery.mockImplementation((path: string) => {
    if (path === "/identity/session") {
      return {
        data: {
          authenticated: true,
          actor_id: "acme-operator",
          tenant_id: "tenant_fixture",
          scopes: ["approvals:supply:decide", "tenant:read"],
        },
        source: "api",
        error: null,
        isRefreshing: false,
        isLoading: false,
        isUnavailable: false,
      };
    }
    if (path.startsWith(`${OPERATIONS_API_PREFIX}/audit/events`)) {
      return {
        data: {
          tenant_id: "tenant_fixture",
          plant_name: "Fixture Plant",
          scenario: "Runtime contract fixture",
          as_of: "2026-07-10T09:00:00+02:00",
          ledger_status: "ready",
          filter_options: { tenants: [], event_types: [], scopes: [] },
          events: auditEvents,
          retention_notes: [],
          metrics: [],
        },
        source: "api",
        error: null,
        isRefreshing: false,
        isLoading: false,
        isUnavailable: false,
      };
    }
    if (path === `${OPERATIONS_API_PREFIX}/actions/runs?tenant_id=tenant_fixture`) {
      return {
        data: actionRuns.data,
        source: actionRuns.source,
        error: actionRuns.source === "unavailable" ? "Axis API request failed." : null,
        isRefreshing: false,
        isLoading: actionRuns.source === "loading",
        isUnavailable: actionRuns.source === "unavailable",
      };
    }
    return {
      data: result.data,
      source: result.source,
      error: result.source === "unavailable" ? "Axis API request failed." : null,
      isRefreshing: false,
      isLoading: result.source === "loading",
      isUnavailable: result.source === "unavailable",
    };
  });
}

function renderInbox() {
  return render(
    <ToastProvider>
      <ApprovalInbox />
    </ToastProvider>,
  );
}

beforeEach(() => {
  mocks.axisFetchParsedJson.mockReset();
  mocks.triggerRefresh.mockReset();
  mocks.useAxisQuery.mockReset();
  mocks.useTenantVocabulary.mockReturnValue({
    labelDomain: (domain: string) => domain,
  });
  window.history.replaceState(null, "", "/approvals");
});

describe("ApprovalInbox states", () => {
  it("renders a loading skeleton without any error copy while loading", () => {
    mockQuery({ data: null, source: "loading" });
    renderInbox();

    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/API required/i)).not.toBeInTheDocument();
  });

  it("renders the ErrorPanel when the approval API is unavailable", () => {
    mockQuery({ data: null, source: "unavailable" });
    renderInbox();

    expect(
      screen.getByRole("heading", { name: "Approval API unavailable" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Local fallback approval records are disabled\./),
    ).toBeInTheDocument();
    // Endpoint stays demoted behind the technical-details expander.
    expect(screen.queryByText(`${OPERATIONS_API_PREFIX}/approvals`)).not.toBeInTheDocument();
  });

  it("renders the EmptyPanel when the API responds with zero approvals", () => {
    mockQuery({ data: { ...inboxFixture, approvals: [] }, source: "api" });
    renderInbox();

    expect(screen.getByRole("heading", { name: "No approvals waiting" })).toBeInTheDocument();
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
  });

  it("counts API-reconciled decisions as decided, not pending", () => {
    mockQuery({
      data: {
        ...inboxFixture,
        approvals: [
          inboxFixture.approvals[0],
          { ...inboxFixture.approvals[0], approval_id: "appr_decided_fixture", status: "decided" },
        ],
      },
      source: "api",
    });
    renderInbox();

    // One genuinely pending, one already decided and reconciled by the API.
    const metrics = screen.getByLabelText("Approval metrics");
    expect(metrics).toHaveTextContent(/Pending\s*Needs watching:\s*1(?!\d)/);
    expect(metrics).toHaveTextContent(/Decided\s*Ready:\s*1(?!\d)/);
  });

  it("keeps decided approvals out of the actionable queue and in decision history", () => {
    mockQuery({
      data: {
        ...inboxFixture,
        approvals: [
          inboxFixture.approvals[0],
          { ...inboxFixture.approvals[1], status: "decided" },
        ],
        decision_history: [
          {
            approval_id: "appr_quality_fixture",
            action: "Place fixture quality hold",
            risk_level: "medium",
            status: "approved",
            decision: "approve",
            domain: "Quality",
            workflow_id: "wf_quality_fixture",
            decided_by: "quality-owner",
            decided_at: "2026-08-22T08:30:00Z",
            rationale: "Deviation confirmed by QMS.",
            audit_event_id: "33333333-3333-4333-8333-333333333333",
            follow_through_status: "signaled",
          },
        ],
      },
      source: "api",
    });
    renderInbox();

    // The decided item is not offered as actionable queue work…
    expect(
      screen.queryByRole("button", { name: /Place fixture quality hold/ }),
    ).not.toBeInTheDocument();
    // …but stays visible as terminal history with its recorded facts.
    const history = within(screen.getByLabelText("Decision history"));
    expect(history.getByText("Place fixture quality hold")).toBeVisible();
    expect(screen.getByText(/quality-owner/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "View audit event" }),
    ).toHaveAttribute("href", "/audit?event_id=33333333-3333-4333-8333-333333333333");
  });

  it("renders an honest empty state when no decisions have been recorded", () => {
    mockQuery({ data: inboxFixture, source: "api" });
    renderInbox();

    expect(screen.getByText("No terminal decisions recorded yet.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Decision history")).toBeInTheDocument();
  });

  it("keeps past follow-through visible when the current approval queue is empty", () => {
    mockQuery(
      { data: { ...inboxFixture, approvals: [] }, source: "api" },
      [],
      {
        source: "api",
        data: {
          tenant_id: "tenant_fixture",
          runs: [
            {
              action_run_id: "run-reported",
              action_id: "place_quality_hold",
              status: "execution_completed",
              approval_id: "appr_quality_fixture",
              workflow_id: "wf_quality_fixture",
              created_at: "2026-07-24T10:00:00Z",
              updated_at: "2026-07-24T11:00:00Z",
              waiting_duration_seconds: 3_600,
              outcome: {
                result_summary: "External executor completed the quality hold.",
                evidence_refs: ["audit_quality_hold_execution"],
              },
            },
          ],
        },
      },
    );
    renderInbox();

    expect(screen.getByRole("heading", { name: "No approvals waiting" })).toBeInTheDocument();
    expect(screen.getByText("External executor completed the quality hold.")).toBeVisible();
  });
});

describe("ApprovalInbox decision flow", () => {
  beforeEach(() => {
    mockQuery({ data: inboxFixture, source: "api" });
  });

  it("shows consequence text for every option without hover", () => {
    renderInbox();

    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/approvals?tenant_id=tenant_fixture`,
      expect.objectContaining({ expectedTenantId: "tenant_fixture" }),
    );
    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/actions/runs?tenant_id=tenant_fixture`,
      expect.objectContaining({ expectedTenantId: "tenant_fixture" }),
    );
    expect(
      screen.getByText("The expedite order is dispatched to the supplier."),
    ).toBeVisible();
    expect(screen.getByText("The current production plan stays unchanged.")).toBeVisible();
  });

  it("uses the tenant label in approval chips, detail and confirmation", async () => {
    const user = userEvent.setup();
    mocks.useTenantVocabulary.mockReturnValue({
      labelDomain: (domain: string) => (
        domain === "Supply" ? "Pharmacy supply" : domain
      ),
    });

    renderInbox();

    expect(
      screen.getByRole("button", { name: /Expedite fixture batch/ }),
    ).toHaveTextContent("Pharmacy supply");
    expect(screen.getByText("Pharmacy supply", { selector: ".eyebrow" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Approve & execute/ }));
    expect(within(await screen.findByRole("dialog")).getByText(/Pharmacy supply/))
      .toBeInTheDocument();
  });

  it("selects the approval linked to an action run", () => {
    mockQuery(
      { data: inboxFixture, source: "api" },
      [{
        evidence_refs: ["action_run_quality_fixture", "appr_quality_fixture"],
        payload_preview: { approval_id: "appr_quality_fixture" },
      }],
    );
    window.history.replaceState(
      null,
      "",
      "/approvals?action_run_id=action_run_quality_fixture",
    );
    renderInbox();

    expect(
      screen.getByRole("heading", { name: "Place fixture quality hold" }),
    ).toBeInTheDocument();
  });

  it("does not select the first approval for an unknown action run", () => {
    window.history.replaceState(
      null,
      "",
      "/approvals?action_run_id=action_run_unknown",
    );
    renderInbox();

    expect(
      screen.getByRole("heading", { name: "Requested approval is not in this queue" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Expedite fixture batch" }),
    ).not.toBeInTheDocument();
  });

  it("switches the detail panel when a queue item is selected", async () => {
    const user = userEvent.setup();
    renderInbox();

    expect(
      screen.getByRole("heading", { name: "Expedite fixture batch" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Place fixture quality hold/ }));
    expect(window.location.search).toBe("?approval_id=appr_quality_fixture");
    expect(
      screen.getByRole("heading", { name: "Place fixture quality hold" }),
    ).toBeInTheDocument();
    expect(screen.getByText("The batch is held for quality review.")).toBeVisible();
  });

  it("moves the queue selection with ArrowDown and ArrowUp", async () => {
    const user = userEvent.setup();
    renderInbox();

    const firstItem = screen.getByRole("button", { name: /Expedite fixture batch/ });
    firstItem.focus();
    await user.keyboard("{ArrowDown}");
    expect(
      screen.getByRole("heading", { name: "Place fixture quality hold" }),
    ).toBeInTheDocument();

    await user.keyboard("{ArrowUp}");
    expect(
      screen.getByRole("heading", { name: "Expedite fixture batch" }),
    ).toBeInTheDocument();
  });

  it("gates persistence behind the confirm dialog and posts the decision payload", async () => {
    const user = userEvent.setup();
    mocks.axisFetchParsedJson.mockResolvedValue(persistenceResultFixture);
    renderInbox();

    await user.click(screen.getByRole("button", { name: /Approve & execute/ }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(mocks.axisFetchParsedJson).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Confirm decision" }));

    await waitFor(() => {
      expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(1);
    });
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/approvals/appr_supply_fixture/decision?tenant_id=tenant_fixture`,
      expect.any(Function),
      expect.objectContaining({
        method: "POST",
        body: {
          decision: "approve",
          actor_id: "acme-operator",
          actor_scopes: ["approvals:supply:decide", "tenant:read"],
          note: "Console decision recorded for appr_supply_fixture.",
        },
      }),
    );
    expect(mocks.triggerRefresh).toHaveBeenCalledTimes(1);
    // The decided approval is pinned in the URL so the operator keeps
    // reviewing exactly what they decided after it leaves the queue.
    expect(window.location.search).toBe("?approval_id=appr_supply_fixture");

    // Inline confirmation links to the created audit event.
    const decisionSection = screen.getByRole("region", { name: "Decision" });
    expect(
      await within(decisionSection).findByRole("link", { name: "View audit event" }),
    ).toHaveAttribute("href", "/audit?event_id=22222222-2222-4222-8222-222222222222");
  });

  it("truncates the workflow id and exposes the full value in a tooltip", () => {
    renderInbox();

    const workflowValue = screen.getByText(
      "wf_supply_fixture_with_a_very_long_identifier_suffix",
    );
    expect(workflowValue).toHaveClass("truncate");
    expect(workflowValue).toHaveAttribute(
      "title",
      "wf_supply_fixture_with_a_very_long_identifier_suffix",
    );
  });
});
