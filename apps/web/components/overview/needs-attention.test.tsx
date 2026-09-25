import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";
import type { ActionRunList } from "@/lib/action-demo";
import type { ManufacturingApprovalInbox } from "@/lib/approval-demo";
import type { ManufacturingOverview } from "@/lib/platform-overview";

const mocks = vi.hoisted(() => ({
  axisFetchParsedJson: vi.fn(),
  useAxisQuery: vi.fn(),
}));

vi.mock("@/lib/axis-api", () => ({
  axisFetchParsedJson: mocks.axisFetchParsedJson,
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

import { NeedsAttention } from "./needs-attention";
import {
  actionRunsFixture,
  approvalInboxFixture,
  emptyActionRunsFixture,
  overviewFixture,
} from "./overview-fixtures";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

type QuerySource = "loading" | "api" | "unavailable";

type QueryResult<T> = {
  data: T | null;
  source: QuerySource;
};

function queryState<T>(result: QueryResult<T>) {
  return {
    data: result.data,
    source: result.source,
    error: result.source === "unavailable" ? "Axis API request failed." : null,
    isRefreshing: false,
    isLoading: result.source === "loading",
    isUnavailable: result.source === "unavailable",
  };
}

/**
 * The strip reads two endpoints, so the mocked hook answers per path. Action
 * runs default to an empty list: tests that care supply their own.
 */
function mockApprovalsQuery(
  result: QueryResult<ManufacturingApprovalInbox>,
  actionRuns: QueryResult<ActionRunList> = { data: emptyActionRunsFixture, source: "api" },
) {
  mocks.useAxisQuery.mockImplementation((path: string) =>
    path.startsWith(`${OPERATIONS_API_PREFIX}/actions/runs`)
      ? queryState(actionRuns)
      : queryState(result),
  );
}

function renderStrip(overview: {
  data: ManufacturingOverview | null;
  source: "loading" | "api" | "unavailable";
}, tenantId?: string) {
  return render(
    <ToastProvider>
      <NeedsAttention
        actor={{ actorId: "acme-operator", scopes: ["approvals:supply:decide"] }}
        identitySession={null}
        overview={overview}
        tenantId={tenantId}
      />
    </ToastProvider>,
  );
}

beforeEach(() => {
  mocks.axisFetchParsedJson.mockReset();
  mocks.useAxisQuery.mockReset();
});

describe("NeedsAttention items", () => {
  it("renders the top three pending approvals, blocked workflows, and risk signals", () => {
    mockApprovalsQuery({ data: approvalInboxFixture, source: "api" });
    renderStrip({ data: overviewFixture, source: "api" });

    // Top three approvals only — the fourth stays on the approvals page.
    expect(screen.getByText("Expedite supplier batch")).toBeInTheDocument();
    expect(screen.getByText("Place quality hold")).toBeInTheDocument();
    expect(screen.getByText("Shift maintenance window")).toBeInTheDocument();
    expect(screen.queryByText("Fourth queued approval")).not.toBeInTheDocument();

    // Blocked / waiting workflows from the overview payload.
    expect(screen.getByText("Supplier Delay Review")).toBeInTheDocument();
    expect(screen.getByText(/Awaiting expedite approval/)).toBeInTheDocument();
    expect(screen.queryByText("Quality Hold Review")).not.toBeInTheDocument();
    expect(screen.getByText(/Example workflow · Awaiting expedite approval/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "View recorded runs" })[0]).toHaveAttribute(
      "href",
      "/workflows",
    );

    // Risk signals with a deep link to the audit evidence.
    expect(screen.getByText("Supplier delay may block Line 2 packaging")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Open audit" })[0]).toHaveAttribute(
      "href",
      "/audit",
    );
  });

  it("keeps live workflows actionable without describing them as examples", () => {
    mockApprovalsQuery({ data: approvalInboxFixture, source: "api" });
    renderStrip({ data: { ...overviewFixture, provenance: "live" }, source: "api" });

    expect(screen.getAllByRole("link", { name: "Open workflows" })[0]).toHaveAttribute(
      "href",
      "/workflows",
    );
    expect(screen.queryByText(/Example workflow/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View recorded runs" })).not.toBeInTheDocument();
  });

  it("does not present reconciled decided approvals as attention items", () => {
    const decidedFirst = approvalInboxFixture.approvals.map((approval, index) => ({
      ...approval,
      status: index === 0 ? "decided" : approval.status,
    }));
    mockApprovalsQuery({
      data: { ...approvalInboxFixture, approvals: decidedFirst },
      source: "api",
    });
    renderStrip({ data: overviewFixture, source: "api" });

    // The decided item leaves the attention strip entirely; a pending item
    // takes its slot so the limit still surfaces actionable work first.
    expect(screen.queryByText("Expedite supplier batch")).not.toBeInTheDocument();
    expect(screen.getByText("Place quality hold")).toBeInTheDocument();
  });

  it("renders a positive all-clear line when nothing needs attention", () => {
    mockApprovalsQuery({ data: { ...approvalInboxFixture, approvals: [] }, source: "api" });
    renderStrip({
      data: {
        ...overviewFixture,
        workflows: overviewFixture.workflows.map((workflow) => ({
          ...workflow,
          state: "completed",
          blocker: null,
        })),
        risk_signals: [],
      },
      source: "api",
    });

    expect(
      screen.getByRole("heading", { name: "All clear — nothing waiting on you" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
  });
});

describe("NeedsAttention stalled action runs", () => {
  it("surfaces approved runs past the stall threshold, longest wait first", () => {
    mockApprovalsQuery(
      { data: approvalInboxFixture, source: "api" },
      { data: actionRunsFixture, source: "api" },
    );
    renderStrip({ data: overviewFixture, source: "api" });

    const strip = screen.getByRole("region", { name: "Needs attention" });
    expect(strip).toHaveTextContent("Request Supplier Expedite");
    expect(strip).toHaveTextContent("Place Quality Hold");

    // The wait an operator judges the threshold by, never raw seconds.
    expect(strip).toHaveTextContent("Waiting 1 day 4 hr");
    expect(strip).toHaveTextContent("Waiting 21 hr 43 min");
    expect(strip).not.toHaveTextContent("102368");
    expect(strip).not.toHaveTextContent("78183");

    // The row points at the authorising approval; Axis never executes or retries.
    expect(strip).toHaveTextContent("No outcome reported by an external executor");
    const approvalLinks = within(strip).getAllByRole("link", { name: "Open approval" });
    expect(approvalLinks).toHaveLength(2);
    expect(approvalLinks[0]).toHaveAttribute(
      "href",
      "/approvals?approval_id=appr_fixture_expedite",
    );
    expect(approvalLinks[1]).toHaveAttribute(
      "href",
      "/approvals?approval_id=appr_fixture_quality",
    );
  });

  it("keeps runs under the threshold, past the cap, or already reported off the strip", () => {
    mockApprovalsQuery(
      { data: approvalInboxFixture, source: "api" },
      { data: actionRunsFixture, source: "api" },
    );
    renderStrip({ data: overviewFixture, source: "api" });

    const strip = screen.getByRole("region", { name: "Needs attention" });
    // Third-longest stalled run: past the threshold but past the cap as well.
    expect(strip).not.toHaveTextContent("Shift Maintenance Window");
    // Waiting under one shift — normal in-flight work.
    expect(strip).not.toHaveTextContent("Reorder Packaging Film");
    // An executor already reported this one.
    expect(strip).not.toHaveTextContent("Release Finished Batch");
    // Longest wait of all, but no approval authorised it.
    expect(strip).not.toHaveTextContent("Generate Daily Brief");
  });
});

describe("NeedsAttention degradation", () => {
  it("keeps approvals, workflows and risk items when the action run API fails", () => {
    mockApprovalsQuery(
      { data: approvalInboxFixture, source: "api" },
      { data: null, source: "unavailable" },
    );
    renderStrip({ data: overviewFixture, source: "api" });

    expect(screen.getByText("Expedite supplier batch")).toBeInTheDocument();
    expect(screen.getByText("Supplier Delay Review")).toBeInTheDocument();
    expect(screen.getByText("Supplier delay may block Line 2 packaging")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Approved actions awaiting an external executor could not be loaded from the action run API.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps workflow and risk items when only the approval API fails", () => {
    mockApprovalsQuery({ data: null, source: "unavailable" });
    renderStrip({ data: overviewFixture, source: "api" });

    expect(screen.getByText("Supplier Delay Review")).toBeInTheDocument();
    expect(screen.getByText("Supplier delay may block Line 2 packaging")).toBeInTheDocument();
    expect(
      screen.getByText("Pending approvals could not be loaded from the approval API."),
    ).toBeInTheDocument();
  });

  it("keeps approvals when only the overview API fails", () => {
    mockApprovalsQuery({ data: approvalInboxFixture, source: "api" });
    renderStrip({ data: null, source: "unavailable" });

    expect(screen.getByText("Expedite supplier batch")).toBeInTheDocument();
    expect(
      screen.getByText("Workflow and risk signals could not be loaded from the overview API."),
    ).toBeInTheDocument();
  });

  it("renders one ErrorPanel when both sources fail", () => {
    mockApprovalsQuery({ data: null, source: "unavailable" });
    renderStrip({ data: null, source: "unavailable" });

    expect(
      screen.getByRole("heading", { name: "Attention items unavailable" }),
    ).toBeInTheDocument();
  });

  it("renders a loading skeleton without error copy while loading", () => {
    mockApprovalsQuery({ data: null, source: "loading" });
    renderStrip({ data: null, source: "loading" });

    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
  });
});

describe("NeedsAttention inline decision flow", () => {
  it("gates persistence behind the same confirm dialog as the approvals page", async () => {
    const user = userEvent.setup();
    mockApprovalsQuery({ data: approvalInboxFixture, source: "api" });
    mocks.axisFetchParsedJson.mockResolvedValue({
      tenant_id: "tenant_fixture",
      approval_id: "appr_fixture_expedite",
      workflow_id: "wf_supplier_delay_review",
      action_id: "act_fixture",
      decision: "approve",
      status: "approved",
      actor_id: "plant-operations-owner-role",
      audit_event_id: "22222222-2222-4222-8222-222222222222",
      audit_event_type: "approval.decision.recorded",
      persisted: true,
      permission_decision: { allowed: true, reason: "required_scope_present" },
      workflow_signal: {
        workflow_id: "wf_supplier_delay_review",
        status: "signaled",
        adapter: "memory",
        signal_name: "approval_decision",
        payload: { approval_id: "appr_fixture_expedite", approved: true },
      },
      workflow_signal_status: "signaled",
    });
    renderStrip({ data: overviewFixture, source: "api" }, "tenant_fixture");

    // Open the decision sheet for the first approval.
    await user.click(screen.getAllByRole("button", { name: "Review & decide" })[0]);
    expect(
      await screen.findByText("The expedite order is dispatched to the supplier."),
    ).toBeVisible();

    // Choosing an option opens the confirm dialog without persisting yet.
    await user.click(screen.getByRole("button", { name: /Approve & execute/ }));
    expect(await screen.findByRole("button", { name: "Confirm decision" })).toBeVisible();
    expect(mocks.axisFetchParsedJson).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Confirm decision" }));
    await waitFor(() => {
      expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(1);
    });
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/approvals/appr_fixture_expedite/decision?tenant_id=tenant_fixture`,
      expect.any(Function),
      expect.objectContaining({
        method: "POST",
        body: expect.objectContaining({
          actor_id: "acme-operator",
          actor_scopes: ["approvals:supply:decide"],
        }),
      }),
    );
  });
});
