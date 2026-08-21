import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlatformPolicyDetail, PlatformPolicyRecord } from "@/lib/platform-policies";

const mocks = vi.hoisted(() => ({
  fetchPlatformPolicyDetail: vi.fn(),
}));

vi.mock("@/lib/use-console-tenant-scope", () => ({
  IDENTITY_SESSION_ENDPOINT: "/identity/session",
  useConsoleTenantScope: () => ({
    identity: { data: null, source: "api" },
    tenantId: "tenant_demo_manufacturing",
    tenantQueriesEnabled: true,
  }),
}));

vi.mock("@/lib/platform-policies", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/platform-policies")>()),
  fetchPlatformPolicyDetail: mocks.fetchPlatformPolicyDetail,
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({
    refreshNonce: 0,
    triggerRefresh: vi.fn(),
    apiBaseUrl: "http://localhost:8000",
    apiStatus: { state: "ok", label: "Ready", detail: "" },
  }),
}));

import { PolicyDetail } from "./policy-detail";

const baseRevision: PlatformPolicyRecord = {
  tenant_id: "tenant_demo_manufacturing",
  policy_id: "deny_critical_actions",
  revision_number: 1,
  policy_version: "1.0.0",
  display_name: "Deny critical actions",
  description: "Blocks critical-risk action execution.",
  scope: "action_execution",
  effect: "require_approval",
  conditions: { risk_levels: ["high", "critical"] },
  status: "superseded",
  notes: [],
  created_by: "platform-governance-owner-role",
  created_at: "2026-07-01T08:00:00Z",
  required_authoring_scope: "platform:policy:author",
  revises_revision_number: null,
  replaced_by_revision_number: 2,
  revision_idempotency_key: null,
  idempotent_replay: false,
  audit_event_type: "platform.policy.authored",
  audit_event_id: null,
  permission_decision: { allowed: true, reason: "authoring_scope_present" },
};

const currentRevision: PlatformPolicyRecord = {
  ...baseRevision,
  revision_number: 2,
  policy_version: "1.1.0",
  effect: "deny",
  conditions: { risk_levels: ["critical"] },
  status: "active",
  revises_revision_number: 1,
  replaced_by_revision_number: null,
  revision_idempotency_key: "idem-key-1",
  required_authoring_scope: "platform:policy:revise",
  audit_event_type: "platform.policy.revised",
};

const detailFixture: PlatformPolicyDetail = {
  tenant_id: "tenant_demo_manufacturing",
  policy_id: "deny_critical_actions",
  current_revision: currentRevision,
  revisions: [baseRevision, currentRevision],
};

describe("PolicyDetail tabs", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/policies/deny_critical_actions");
    mocks.fetchPlatformPolicyDetail.mockReset();
    mocks.fetchPlatformPolicyDetail.mockResolvedValue(detailFixture);
  });

  it("requests and validates the verified tenant scope", async () => {
    render(<PolicyDetail policyId="deny_critical_actions" />);

    await screen.findByRole("heading", { name: "Deny critical actions" });
    expect(mocks.fetchPlatformPolicyDetail).toHaveBeenCalledWith(
      "deny_critical_actions",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
      "tenant_demo_manufacturing",
    );
  });

  it("keeps header and KPIs above tabs and defaults to Conditions", async () => {
    render(<PolicyDetail policyId="deny_critical_actions" />);

    expect(
      await screen.findByRole("heading", { name: "Deny critical actions" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Conditions" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Revisions" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Evaluate" })).toBeInTheDocument();

    // Conditions tab is active: rule conditions + precedence render.
    expect(screen.getByText("Rule Conditions")).toBeInTheDocument();
    expect(screen.getByText("Evaluation Precedence")).toBeInTheDocument();

    // Revisions and Evaluate content are not mounted yet.
    expect(
      screen.queryByRole("form", { name: "Platform policy revision" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "Policy dry-run evaluation" }),
    ).not.toBeInTheDocument();
  });

  it("shows revise form, history and compare under the Revisions tab", async () => {
    const user = userEvent.setup();
    const pushState = vi.spyOn(window.history, "pushState");
    render(<PolicyDetail policyId="deny_critical_actions" />);
    await screen.findByRole("heading", { name: "Deny critical actions" });

    await user.click(screen.getByRole("tab", { name: "Revisions" }));

    expect(
      screen.getByRole("form", { name: "Platform policy revision" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Revision History")).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: "Policy revision history" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Revision Compare")).toBeInTheDocument();
    expect(screen.getByLabelText("Revision to compare")).toBeInTheDocument();
    expect(window.location.search).toBe("?tab=revisions");
    expect(pushState).toHaveBeenCalledWith(
      window.history.state,
      "",
      "/policies/deny_critical_actions?tab=revisions",
    );
    pushState.mockRestore();
  });

  it("restores a linked revision tab and comparison target from the URL", async () => {
    window.history.replaceState(
      null,
      "",
      "/policies/deny_critical_actions?tab=revisions&compare_revision=1",
    );

    render(<PolicyDetail policyId="deny_critical_actions" />);

    await screen.findByRole("form", { name: "Platform policy revision" });
    expect(screen.getByRole("tab", { name: "Revisions" })).toHaveAttribute(
      "data-state",
      "active",
    );
    expect(screen.getByLabelText("Revision to compare")).toHaveValue("1");
  });

  it("removes a comparison revision that the loaded policy cannot resolve", async () => {
    window.history.replaceState(
      null,
      "",
      "/policies/deny_critical_actions?tab=revisions&compare_revision=99",
    );

    render(<PolicyDetail policyId="deny_critical_actions" />);

    await screen.findByRole("form", { name: "Platform policy revision" });
    await waitFor(() => {
      expect(window.location.search).toBe("?tab=revisions");
    });
    expect(screen.getByLabelText("Revision to compare")).toHaveValue("");
  });

  it("renders exactly one dry-run evaluator under the Evaluate tab", async () => {
    const user = userEvent.setup();
    render(<PolicyDetail policyId="deny_critical_actions" />);
    await screen.findByRole("heading", { name: "Deny critical actions" });

    await user.click(screen.getByRole("tab", { name: "Evaluate" }));

    expect(screen.getAllByRole("form", { name: "Policy dry-run evaluation" })).toHaveLength(1);
  });
});
