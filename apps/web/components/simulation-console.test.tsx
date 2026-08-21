import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ManufacturingReplaySimulation } from "@/lib/simulation-demo";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
  useConsoleTenantScope: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({ useAxisQuery: mocks.useAxisQuery }));
vi.mock("@/lib/use-console-tenant-scope", () => ({
  IDENTITY_SESSION_ENDPOINT: "/identity/session",
  useConsoleTenantScope: mocks.useConsoleTenantScope,
}));
vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

import { SimulationConsole } from "./simulation-console";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

const emptyReplay: ManufacturingReplaySimulation = {
  tenant_id: "tenant_acme",
  plant_name: "Acme Operations",
  scenario: "Replay history",
  provenance: "empty",
  as_of: "2026-07-22T12:00:00Z",
  simulation_status: "ready",
  metrics: [],
  retention_window: {
    policy_id: "retention_acme",
    retention_days: 30,
    legal_hold: false,
    retention_enforced: true,
    retention_window_start: "2026-06-22T12:00:00Z",
    disposal_action: "cryptographic_erasure",
    excluded_timeline_event_count: 0,
    excluded_audit_event_count: 0,
    excluded_output_count: 0,
    notes: [],
  },
  artifacts: [],
  persisted_outputs: [],
  simulation_notes: [],
};

function queryResult(data: unknown, source: "loading" | "api" | "unavailable") {
  return {
    data,
    source,
    error: source === "unavailable" ? "Axis API request failed." : null,
    isRefreshing: false,
    isLoading: source === "loading",
    isUnavailable: source === "unavailable",
  };
}

describe("SimulationConsole tenant and empty states", () => {
  beforeEach(() => {
    mocks.useAxisQuery.mockReset();
    mocks.useConsoleTenantScope.mockReset();
    mocks.useConsoleTenantScope.mockReturnValue({
      identity: queryResult({ authenticated: true, tenant_id: "tenant_acme" }, "api"),
      tenantId: "tenant_acme",
      tenantQueriesEnabled: true,
    });
    mocks.useAxisQuery.mockReturnValue(queryResult(emptyReplay, "api"));
  });

  it("scopes replay reads and decoded responses to the verified tenant", () => {
    render(<SimulationConsole />);

    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      `${OPERATIONS_API_PREFIX}/simulation/replay?tenant_id=tenant_acme&limit=20`,
      expect.objectContaining({ enabled: true, expectedTenantId: "tenant_acme" }),
    );
  });

  it("treats a valid zero-artifact response as an empty state", () => {
    render(<SimulationConsole />);

    expect(screen.getByRole("heading", { name: "No replay history yet" })).toBeInTheDocument();
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
  });

  it("fails closed when identity cannot be verified", () => {
    mocks.useConsoleTenantScope.mockReturnValue({
      identity: queryResult(null, "unavailable"),
      tenantId: null,
      tenantQueriesEnabled: false,
    });
    mocks.useAxisQuery.mockReturnValue(queryResult(null, "loading"));

    render(<SimulationConsole />);

    expect(screen.getByRole("heading", { name: "Identity API unavailable" })).toBeInTheDocument();
    expect(mocks.useAxisQuery).toHaveBeenCalledWith(
      expect.stringContaining("tenant_id=tenant_demo_manufacturing"),
      expect.objectContaining({ enabled: false }),
    );
  });
});

describe("SimulationConsole artifact with no policy results", () => {
  beforeEach(() => {
    mocks.useAxisQuery.mockReset();
    mocks.useConsoleTenantScope.mockReset();
    mocks.useConsoleTenantScope.mockReturnValue({
      identity: queryResult({ authenticated: true, tenant_id: "tenant_acme" }, "api"),
      tenantId: "tenant_acme",
      tenantQueriesEnabled: true,
    });
  });

  // The API contract allows an empty policy_results array (a run with no
  // policy attached to it). `selectedArtifact.policy_results[0]` used to be
  // dereferenced unguarded, so this shape crashed the page.
  it("renders without crashing and shows the no-policy-result fallback", () => {
    const replayWithEmptyPolicyResults: ManufacturingReplaySimulation = {
      ...emptyReplay,
      artifacts: [
        {
          artifact_id: "artifact_no_policy",
          workflow_id: "wf_no_policy",
          workflow_name: "No-policy Fixture Workflow",
          audit_scope: "wf_no_policy",
          replay_mode: "preview",
          replay_ready: true,
          determinism_status: "deterministic",
          timeline_event_count: 1,
          audit_event_count: 0,
          evidence_refs: [],
          timeline: [
            {
              event: "workflow.started",
              at: "2026-07-22T12:00:00Z",
              actor: "axis-workflow-runtime",
              result: "started",
              summary: "Workflow started.",
            },
          ],
          audit_events: [],
          policy_results: [],
          policy_set_diffs: [],
        },
      ],
    };
    mocks.useAxisQuery.mockReturnValue(queryResult(replayWithEmptyPolicyResults, "api"));
    window.history.replaceState(
      null,
      "",
      "/simulation?artifact_id=artifact_no_policy",
    );

    render(<SimulationConsole />);

    expect(
      screen.getByText("No policy result recorded for this replay."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "No-policy Fixture Workflow" }),
    ).toBeInTheDocument();
  });
});
