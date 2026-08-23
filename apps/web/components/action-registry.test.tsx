import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ManufacturingActionRegistry } from "@/lib/action-demo";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { DEMO_TENANT_ID, OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

vi.mock("@/lib/use-identity-session", () => ({
  useIdentitySession: () => mocks.useAxisQuery("/identity/session"),
}));

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

import { ActionRegistry } from "./action-registry";

const publicIdentity: IdentitySessionReadModel = {
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

const actionRegistryFixture: ManufacturingActionRegistry = {
  tenant_id: DEMO_TENANT_ID,
  plant_name: "Fixture Plant",
  scenario: "Runtime contract fixture",
  provenance: "reference_scenario",
  as_of: "2026-06-22T09:00:00+02:00",
  registry_status: "ready",
  schema_version: "2026-06-22",
  metrics: [],
  filter_options: {
    domains: ["Supply", "Operations"],
    risk_levels: ["high", "low"],
    approval_modes: ["required", "not_required"],
    statuses: ["approval_required", "ready"],
  },
  actions: [
    {
      definition: {
        action_id: "expedite_fixture_batch",
        display_name: "Expedite fixture batch",
        domain: "Supply",
        risk_level: "high",
        approval_mode: "required",
        input_schema: {
          type: "object",
          required: ["supplier_batch_id", "evidence_refs"],
          properties: {
            supplier_batch_id: { type: "string", "x-axis-ontology-ref": true },
            evidence_refs: { type: "array", items: { type: "string" } },
          },
        },
        output_schema: { type: "object", properties: { status: { type: "string" } } },
        required_permissions: ["approvals:supply:request"],
      },
      description: "Fixture action requiring owner approval.",
      owner_role: "supply-owner",
      status: "approval_required",
      side_effects: "Requests an external shipment update through the action runtime.",
      policy: {
        approval_role: "supply-owner",
        autonomy_ceiling: "L2",
        execution_mode: "dry_run",
        runtime_adapter: "axis-action-runtime",
        audit_event_type: "action.requested",
        model_egress_policy: "no-external-egress",
        idempotency_required: true,
        dry_run_supported: true,
      },
      connected_agents: ["agent_supply_fixture"],
      workflow_bindings: ["wf_supply_fixture"],
      approval_refs: ["appr_supply_fixture"],
      guardrails: ["Require human approval"],
      validation_checks: ["Validate supplier batch"],
      blocked_conditions: ["Missing owner approval"],
      sample_input: {
        supplier_batch_id: "batch-42",
        evidence_refs: "risk_supply_fixture,audit_fixture",
      },
      sample_output: { status: "queued" },
    },
    {
      definition: {
        action_id: "brief_fixture",
        display_name: "Generate fixture brief",
        domain: "Operations",
        risk_level: "low",
        approval_mode: "not_required",
        input_schema: { type: "object", properties: { shift: { type: "string" } } },
        output_schema: { type: "object", properties: { summary: { type: "string" } } },
        required_permissions: ["operations:read"],
      },
      description: "Read-only operational summary.",
      owner_role: "operations-owner",
      status: "ready",
      side_effects: "None.",
      policy: {
        approval_role: "operations-owner",
        autonomy_ceiling: "L1",
        execution_mode: "preview",
        runtime_adapter: "axis-action-runtime",
        audit_event_type: "action.previewed",
        model_egress_policy: "local-only",
        idempotency_required: true,
        dry_run_supported: true,
      },
      connected_agents: [],
      workflow_bindings: [],
      approval_refs: [],
      guardrails: ["Read-only output"],
      validation_checks: ["Validate shift"],
      blocked_conditions: ["No tenant context"],
      sample_input: { shift: "morning" },
      sample_output: { summary: "ready" },
    },
  ],
  registry_notes: ["Fixture data is scoped to tests."],
};

function queryResult(data: unknown, source: "loading" | "api" | "unavailable" = "api") {
  return {
    data,
    source,
    error: source === "unavailable" ? "Axis API request failed." : null,
    isRefreshing: false,
    isLoading: source === "loading",
    isUnavailable: source === "unavailable",
  };
}

function mockActions(registry: ManufacturingActionRegistry = actionRegistryFixture) {
  mocks.useAxisQuery.mockImplementation((path: string) => {
    if (path === "/identity/session") {
      return queryResult(publicIdentity);
    }
    if (path === `${OPERATIONS_API_PREFIX}/actions?tenant_id=${DEMO_TENANT_ID}`) {
      // A fresh object identity every call, mirroring `useAxisQuery`'s real
      // behaviour: every fetch — including a background refresh that finds
      // nothing new — returns a brand-new object.
      return queryResult({
        ...registry,
        actions: registry.actions.map((action) => ({ ...action })),
      });
    }
    return queryResult(null, "loading");
  });
}

beforeEach(() => {
  mocks.useAxisQuery.mockReset();
  mockActions();
});

describe("ActionRegistry selection", () => {
  it("renders a valid empty payload as onboarding state, not an API error", () => {
    mockActions({
      ...actionRegistryFixture,
      provenance: "empty",
      metrics: [],
      actions: [],
    });

    render(<ActionRegistry />);

    expect(screen.getByRole("heading", { name: "No actions registered yet" })).toBeInTheDocument();
    expect(screen.getByText("action registry: no records")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Action API returned no records" }))
      .not.toBeInTheDocument();
  });

  it("keeps the selected action across a background refetch", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<ActionRegistry />);

    await user.click(screen.getByRole("button", { name: /Generate fixture brief/ }));
    expect(
      screen.getByRole("heading", { name: "Generate fixture brief" }),
    ).toBeInTheDocument();

    // Simulate a global refresh: useAxisQuery returns a brand-new registry
    // object (new identity, same data), which used to yank the selection
    // back to the first action via the deleted effect.
    rerender(<ActionRegistry />);

    expect(
      screen.getByRole("heading", { name: "Generate fixture brief" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Expedite fixture batch" }),
    ).not.toBeInTheDocument();
  });
});

describe("ActionRegistry governed-write gate", () => {
  it("replaces the run request with an SSO gate when sign-in is enforced", () => {
    const enforcedIdentity: IdentitySessionReadModel = {
      ...publicIdentity,
      mode: "sso",
      api_auth_required: true,
      enterprise_sso_ready: true,
      session_boundary: "cookie",
      jwks_source: "remote",
    };
    mocks.useAxisQuery.mockImplementation((path: string) => {
      if (path === "/identity/session") {
        return queryResult(enforcedIdentity);
      }
      if (path === `${OPERATIONS_API_PREFIX}/actions?tenant_id=${DEMO_TENANT_ID}`) {
        return queryResult(actionRegistryFixture);
      }
      return queryResult(null, "loading");
    });

    render(<ActionRegistry />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Sign in with SSO to request governed action runs.",
    );
    expect(
      screen.queryByRole("button", { name: /Request dry-run/ }),
    ).not.toBeInTheDocument();
  });
});
