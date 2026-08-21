import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlatformPolicyRecord } from "@/lib/platform-policies";

const mocks = vi.hoisted(() => ({
  createPlatformPolicy: vi.fn(),
  evaluatePlatformPolicy: vi.fn(),
  revisePlatformPolicy: vi.fn(),
  triggerRefresh: vi.fn(),
}));

vi.mock("@/lib/platform-policies", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/platform-policies")>()),
  createPlatformPolicy: mocks.createPlatformPolicy,
  evaluatePlatformPolicy: mocks.evaluatePlatformPolicy,
  revisePlatformPolicy: mocks.revisePlatformPolicy,
}));

vi.mock("@/lib/ids", () => ({
  safeRandomUuid: () => "idempotency-test-key",
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ triggerRefresh: mocks.triggerRefresh }),
}));

import { AxisApiError } from "@/lib/axis-api";
import { PolicyCreateForm } from "./policy-create-form";
import { PolicyEvaluationPanel } from "./policy-evaluation-panel";
import { PolicyReviseForm } from "./policy-revise-form";

const currentPolicy: PlatformPolicyRecord = {
  tenant_id: "tenant_fixture",
  policy_id: "deny_critical_actions",
  revision_number: 2,
  policy_version: "1.1.0",
  display_name: "Deny critical actions",
  description: "Blocks critical-risk action execution.",
  scope: "action_execution",
  effect: "deny",
  conditions: { risk_levels: ["critical"] },
  status: "active",
  notes: [],
  created_by: "platform-governance-owner-role",
  created_at: "2026-07-01T08:00:00Z",
  required_authoring_scope: "platform:policy:revise",
  revises_revision_number: 1,
  replaced_by_revision_number: null,
  revision_idempotency_key: "idempotency-prior-key",
  idempotent_replay: false,
  audit_event_type: "platform.policy.revised",
  audit_event_id: null,
  permission_decision: { allowed: true, reason: "authoring_scope_present" },
};

beforeEach(() => {
  mocks.createPlatformPolicy.mockReset();
  mocks.evaluatePlatformPolicy.mockReset();
  mocks.revisePlatformPolicy.mockReset();
  mocks.triggerRefresh.mockReset();
});

describe("policy mutation request references", () => {
  it("shows the request reference returned by a failed policy create", async () => {
    const user = userEvent.setup();
    mocks.createPlatformPolicy.mockResolvedValue({
      kind: "failed",
      message: "Policy storage is temporarily unavailable.",
      requestId: "request-policy-create-503",
      status: 503,
    });
    render(<PolicyCreateForm tenantId="tenant_fixture" />);

    await user.type(screen.getByLabelText("New policy id"), "deny_fixture_actions");
    await user.type(screen.getByLabelText("New policy display name"), "Deny fixture actions");
    await user.type(screen.getByLabelText("New policy description"), "Blocks fixture actions.");
    await user.type(screen.getByLabelText("New policy action domains"), "Operations");
    await user.click(screen.getByRole("button", { name: "Author policy" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Policy authoring failed: Policy storage is temporarily unavailable.",
    );
    expect(screen.getByText("request-policy-create-503")).toBeInTheDocument();
  });

  it("keeps a revision conflict's HTTP reference after rotating the idempotency key", async () => {
    const user = userEvent.setup();
    mocks.revisePlatformPolicy.mockResolvedValue({
      kind: "conflict",
      message: "The idempotency key was already used with another payload.",
      reason: "revision_idempotency_conflict",
      requestId: "request-policy-revise-409",
    });
    render(<PolicyReviseForm current={currentPolicy} tenantId="tenant_fixture" />);

    await user.click(screen.getByRole("button", { name: "Append revision" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Revision conflict");
    expect(screen.getByText("request-policy-revise-409")).toBeInTheDocument();
  });

  it("projects a thrown evaluation failure without rendering raw response fields", async () => {
    const user = userEvent.setup();
    mocks.evaluatePlatformPolicy.mockRejectedValue(
      new AxisApiError("/platform/policies/evaluate", 503, {
        body: {
          detail: {
            message: "Policy evaluation is temporarily unavailable.",
            debug_context: "secret=policy-database-credential",
          },
        },
        requestId: "request-policy-evaluate-503",
      }),
    );
    render(
      <PolicyEvaluationPanel
        formLabel="Policy evaluation"
        scope="action_execution"
        tenantId="tenant_fixture"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Run dry-run evaluation" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Dry-run evaluation failed: Policy evaluation is temporarily unavailable.",
    );
    expect(screen.getByText("request-policy-evaluate-503")).toBeInTheDocument();
    expect(screen.queryByText(/policy-database-credential/)).not.toBeInTheDocument();
  });
});
