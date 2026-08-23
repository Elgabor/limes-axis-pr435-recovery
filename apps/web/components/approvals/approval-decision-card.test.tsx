import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/toast";
import type { ApprovalInboxItem } from "@/lib/approval-demo";
import { AxisApiError } from "@/lib/axis-api";

const mocks = vi.hoisted(() => ({
  axisFetchParsedJson: vi.fn(),
}));

vi.mock("@/lib/axis-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/axis-api")>()),
  axisFetchParsedJson: mocks.axisFetchParsedJson,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

import { ApprovalDecisionCard, useApprovalDecisionState } from "./approval-decision-card";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

const approvalFixture: ApprovalInboxItem = {
  approval_id: "appr_supply_fixture",
  action: "Expedite fixture batch",
  risk_level: "high",
  status: "pending",
  requested_by: "agent_supply_fixture",
  owner_role: "plant-operations-owner",
  due: "Today 17:30",
  workflow_id: "wf_supply_fixture",
  domain: "Supply",
  summary: "Approve or reject a governed supply action.",
  evidence: ["risk_supply_fixture"],
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
};

const persistenceResultFixture = {
  tenant_id: "tenant_fixture",
  approval_id: "appr_supply_fixture",
  workflow_id: "wf_supply_fixture",
  action_id: "act_fixture",
  decision: "approve",
  status: "approved",
  actor_id: "plant-operations-owner-role",
  audit_event_id: "11111111-1111-4111-8111-111111111111",
  audit_event_type: "approval.decision.recorded",
  persisted: true,
  permission_decision: { allowed: true, reason: "required_scope_present" },
  workflow_signal: {
    workflow_id: "wf_supply_fixture",
    status: "signaled",
    adapter: "memory",
    signal_name: "approval_decision",
    payload: { approval_id: "appr_supply_fixture", approved: true },
  },
  workflow_signal_status: "signaled",
};

function Harness({
  approval = approvalFixture,
  actor,
  identitySession = null,
}: {
  approval?: ApprovalInboxItem;
  actor?: { actorId: string; scopes: string[] };
  identitySession?: NonNullable<
    Parameters<typeof ApprovalDecisionCard>[0]["identitySession"]
  > | null;
}) {
  const { decisions, errors, setDecision, setError } = useApprovalDecisionState();

  return (
    <ToastProvider>
      <ApprovalDecisionCard
        actor={actor}
        approval={approval}
        decision={decisions[approval.approval_id]}
        error={errors[approval.approval_id]}
        identitySession={identitySession}
        onDecisionChange={setDecision}
        onErrorChange={setError}
      />
    </ToastProvider>
  );
}

beforeEach(() => {
  mocks.axisFetchParsedJson.mockReset();
});

describe("ApprovalDecisionCard", () => {
  it("shows every option's consequence text without hover", () => {
    render(<Harness />);

    expect(
      screen.getByText("The expedite order is dispatched to the supplier."),
    ).toBeVisible();
    expect(screen.getByText("The current production plan stays unchanged.")).toBeVisible();
  });

  it("does not persist until the confirm dialog is confirmed", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: /Approve & execute/ }));

    // The dialog restates the option and its consequence.
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Approve & execute");
    expect(dialog).toHaveTextContent("The expedite order is dispatched to the supplier.");
    expect(mocks.axisFetchParsedJson).not.toHaveBeenCalled();

    // Cancelling also never calls the API.
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mocks.axisFetchParsedJson).not.toHaveBeenCalled();
  });

  it("persists through the decision endpoint with the rationale note on confirm", async () => {
    const user = userEvent.setup();
    mocks.axisFetchParsedJson.mockResolvedValue(persistenceResultFixture);
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: /Approve & execute/ }));
    await user.type(
      await screen.findByLabelText("Rationale (optional)"),
      "Supplier confirmed the slot.",
    );
    await user.click(screen.getByRole("button", { name: "Confirm decision" }));

    await waitFor(() => {
      expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(1);
    });
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/approvals/appr_supply_fixture/decision?tenant_id=tenant_demo_manufacturing`,
      expect.any(Function),
      expect.objectContaining({
        method: "POST",
        session: null,
        body: {
          decision: "approve",
          actor_id: "plant-operations-owner-role",
          actor_scopes: ["approvals:supply:decide"],
          note: "Supplier confirmed the slot.",
        },
      }),
    );
  });

  it("uses the verified identity actor and scopes for authenticated decisions", async () => {
    const user = userEvent.setup();
    mocks.axisFetchParsedJson.mockResolvedValue({
      ...persistenceResultFixture,
      actor_id: "acme-operator",
    });
    render(
      <Harness actor={{ actorId: "acme-operator", scopes: ["approvals:supply:decide"] }} />,
    );

    await user.click(screen.getByRole("button", { name: /Approve & execute/ }));
    await user.click(await screen.findByRole("button", { name: "Confirm decision" }));

    await waitFor(() => expect(mocks.axisFetchParsedJson).toHaveBeenCalledTimes(1));
    expect(mocks.axisFetchParsedJson).toHaveBeenCalledWith(
      expect.any(String),
      expect.any(Function),
      expect.objectContaining({
        body: expect.objectContaining({
          actor_id: "acme-operator",
          actor_scopes: ["approvals:supply:decide"],
        }),
      }),
    );
  });

  it("renders the audit-event link and a toast after a persisted decision", async () => {
    const user = userEvent.setup();
    mocks.axisFetchParsedJson.mockResolvedValue(persistenceResultFixture);
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: /Approve & execute/ }));
    await user.click(await screen.findByRole("button", { name: "Confirm decision" }));

    // Inline confirmation and the success toast both deep-link to the audit
    // event id returned by the decision API.
    const auditLinks = await screen.findAllByRole("link", { name: "View audit event" });
    expect(auditLinks).toHaveLength(2);
    for (const link of auditLinks) {
      expect(link).toHaveAttribute(
        "href",
        "/audit?event_id=11111111-1111-4111-8111-111111111111",
      );
    }
    expect(screen.getByText("Decision recorded")).toBeInTheDocument();

    // Option buttons are replaced by the recorded state.
    expect(screen.queryByRole("button", { name: /Approve & execute/ })).not.toBeInTheDocument();
  });

  it("replaces decisions with the SSO gate when the deployment enforces sign-in", () => {
    render(
      <Harness
        identitySession={
          {
            authenticated: false,
            actor_id: null,
            tenant_id: "tenant_demo_manufacturing",
            scopes: [],
            mode: "sso",
            api_auth_required: true,
            expires_at: null,
            enterprise_sso_ready: true,
            readiness_status: "ready",
            issuer: "https://issuer.example",
            audience: "limes-axis-api",
            jwks_source: "remote",
            session_boundary: "cookie",
            capabilities: [],
            limitations: [],
            notes: [],
            unauthenticated_reason: null,
          } as NonNullable<Parameters<typeof ApprovalDecisionCard>[0]["identitySession"]>
        }
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "Sign in with SSO to record approval decisions.",
    );
    // No doomed request is fired and no decision option remains clickable.
    expect(
      screen.queryByRole("button", { name: /Approve & execute/ }),
    ).not.toBeInTheDocument();
    expect(mocks.axisFetchParsedJson).not.toHaveBeenCalled();
  });

  it("hides options for an approval whose terminal decision was already recorded", () => {
    render(
      <Harness
        approval={{ ...approvalFixture, status: "decided" }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "A terminal decision was already recorded for this approval.",
    );
    expect(
      screen.queryByRole("button", { name: /Approve & execute/ }),
    ).not.toBeInTheDocument();
    expect(mocks.axisFetchParsedJson).not.toHaveBeenCalled();
  });

  it("surfaces persistence failures and keeps the options available", async () => {
    const user = userEvent.setup();
    mocks.axisFetchParsedJson.mockRejectedValue(new AxisApiError("/approval", 503, {
      body: {
        detail: {
          message: "Approval persistence is temporarily unavailable.",
          debug_context: "secret=database-credential",
        },
      },
      requestId: "request-approval-503",
    }));
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: /Approve & execute/ }));
    await user.click(await screen.findByRole("button", { name: "Confirm decision" }));

    expect(
      await screen.findByText("Approval persistence is temporarily unavailable."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/database-credential/)).not.toBeInTheDocument();
    expect(screen.queryByText("request-approval-503")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Technical details" }));
    expect(screen.getByText("request-approval-503")).toBeInTheDocument();
    expect(screen.queryByText(/database-credential/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve & execute/ })).toBeEnabled();
  });
});
