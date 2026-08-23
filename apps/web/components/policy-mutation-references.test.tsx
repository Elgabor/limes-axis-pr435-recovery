import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlatformPolicyRecord } from "@/lib/platform-policies";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";

const mocks = vi.hoisted(() => ({
  createPlatformPolicy: vi.fn(),
  evaluatePlatformPolicy: vi.fn(),
  revisePlatformPolicy: vi.fn(),
  triggerRefresh: vi.fn(),
  useAxisQuery: vi.fn(),
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

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/use-identity-session", () => ({
  useIdentitySession: () => mocks.useAxisQuery("/identity/session"),
}));

vi.mock("@/providers/console-provider", () => ({
  useConsole: () => ({ triggerRefresh: mocks.triggerRefresh }),
}));

import { AxisApiError } from "@/lib/axis-api";
import { PolicyCreateForm } from "./policy-create-form";
import { PolicyEvaluationPanel } from "./policy-evaluation-panel";
import { PolicyReviseForm } from "./policy-revise-form";

const publicDemoIdentity: IdentitySessionReadModel = {
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
  unauthenticated_reason: null,
};

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
  mocks.useAxisQuery.mockReset();
  mocks.useAxisQuery.mockImplementation(() => ({
    data: publicDemoIdentity,
    source: "api",
    errorRequestId: null,
  }));
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

    fireEvent.change(screen.getByLabelText("New policy id"), {
      target: { value: "deny_fixture_actions" },
    });
    fireEvent.change(screen.getByLabelText("New policy display name"), {
      target: { value: "Deny fixture actions" },
    });
    fireEvent.change(screen.getByLabelText("New policy description"), {
      target: { value: "Blocks fixture actions." },
    });
    fireEvent.change(screen.getByLabelText("New policy action domains"), {
      target: { value: "Operations" },
    });
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

describe("policy mutation SSO gate", () => {
  const enforcedIdentity = {
    ...publicDemoIdentity,
    mode: "sso",
    api_auth_required: true,
    enterprise_sso_ready: true,
    session_boundary: "cookie",
    jwks_source: "remote",
  };

  beforeEach(() => {
    mocks.useAxisQuery.mockImplementation(() => ({
      data: enforcedIdentity,
      source: "api",
      errorRequestId: null,
    }));
  });

  it("replaces authoring with an SSO gate when sign-in is enforced", () => {
    render(<PolicyCreateForm tenantId="tenant_fixture" />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Sign in with SSO to author platform policies.",
    );
    expect(screen.queryByRole("button", { name: "Author policy" })).not.toBeInTheDocument();
    expect(mocks.createPlatformPolicy).not.toHaveBeenCalled();
  });

  it("replaces revision appending with an SSO gate when sign-in is enforced", () => {
    render(<PolicyReviseForm current={currentPolicy} tenantId="tenant_fixture" />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Sign in with SSO to append policy revisions.",
    );
    expect(
      screen.queryByRole("button", { name: "Append revision" }),
    ).not.toBeInTheDocument();
    expect(mocks.revisePlatformPolicy).not.toHaveBeenCalled();
  });
});
