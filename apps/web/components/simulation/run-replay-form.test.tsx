import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ManufacturingReplaySimulation } from "@/lib/simulation-demo";

const mocks = vi.hoisted(() => ({
  axisFetch: vi.fn(),
}));

vi.mock("@/lib/axis-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/axis-api")>();
  return {
    ...actual,
    axisFetch: mocks.axisFetch,
    axisFetchParsedJson: async <T,>(
      path: string,
      decoder: (value: unknown) => T,
      options: import("@/lib/axis-api").AxisFetchOptions = {},
    ): Promise<T> => {
      const response = await mocks.axisFetch(path, options) as Response;
      const requestId = actual.axisResponseRequestId(response);
      const body = await response.json();
      if (!response.ok) {
        throw new actual.AxisApiError(path, response.status, { body, requestId });
      }
      return actual.decodeAxisJson(path, body, decoder, requestId);
    },
  };
});

vi.mock("@/lib/use-oidc-session", () => ({
  useOidcConsoleSession: () => ({ session: null }),
}));

import { RunReplayForm } from "./run-replay-form";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

const replayResultFixture: ManufacturingReplaySimulation = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Replay fixture",
  provenance: "live",
  as_of: "2026-07-09T09:00:00+02:00",
  simulation_status: "ready",
  metrics: [],
  retention_window: {
    policy_id: "retention_fixture",
    retention_days: 90,
    legal_hold: false,
    retention_enforced: true,
    retention_window_start: "2026-04-10T09:00:00+02:00",
    disposal_action: "cryptographic_erasure",
    excluded_timeline_event_count: 0,
    excluded_audit_event_count: 0,
    excluded_output_count: 0,
    notes: [],
  },
  artifacts: [
    {
      artifact_id: "replay_fixture",
      workflow_id: "wf_supply_fixture",
      workflow_name: "Supply Fixture Review",
      audit_scope: "wf_supply_fixture",
      replay_mode: "governance-preview",
      replay_ready: true,
      determinism_status: "deterministic",
      timeline_event_count: 2,
      audit_event_count: 1,
      evidence_refs: [],
      timeline: [],
      audit_events: [],
      policy_results: [
        {
          policy_id: "policy_supply_gate",
          policy_name: "Supply approval gate",
          baseline_decision: "require_approval",
          simulated_decision: "deny",
          changed_outcome: true,
          evidence_refs: [],
          summary: "Candidate policy set denies what the baseline gated.",
        },
        {
          policy_id: "policy_evidence",
          policy_name: "Evidence recording",
          baseline_decision: "allow_with_evidence",
          simulated_decision: "allow_with_evidence",
          changed_outcome: false,
          evidence_refs: [],
          summary: "Evidence policy unchanged.",
        },
      ],
      policy_set_diffs: [
        {
          diff_id: "diff_fixture",
          connector_id: "connector_csv_assets",
          baseline_policy_set_id: "policy_set_v1",
          baseline_policy_set_version: "1.0.0",
          candidate_policy_set_id: "policy_set_v2",
          candidate_policy_set_version: "2.0.0",
          historical_event_count: 12,
          changed_policy_ids: ["policy_supply_gate"],
          baseline_decision: "promote",
          candidate_decision: "block",
          changed_outcome: true,
          diff_status: "changed_outcome_detected",
          audit_event_type: "connector.promotion_policy_set.simulated_diff",
          evidence_refs: [],
          summary: "Candidate set blocks the recorded promotion.",
        },
      ],
    },
  ],
  persisted_outputs: [],
  simulation_notes: [],
};

function jsonResponse(
  payload: unknown,
  status = 200,
  requestId?: string,
): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...(requestId ? { "x-request-id": requestId } : {}),
    },
  });
}

describe("RunReplayForm", () => {
  beforeEach(() => {
    mocks.axisFetch.mockReset();
  });

  it("runs a replay with the drafted parameters and renders the decision diff", async () => {
    const user = userEvent.setup();
    mocks.axisFetch.mockResolvedValue(jsonResponse(replayResultFixture));

    render(<RunReplayForm tenantId="tenant_fixture" />);

    await user.type(screen.getByLabelText("Workflow id (optional)"), "wf_supply_fixture");
    const limitField = screen.getByLabelText("History window (events)");
    await user.clear(limitField);
    await user.type(limitField, "50");
    await user.type(screen.getByLabelText("Baseline policy set (optional)"), "policy_set_v1");
    await user.type(screen.getByLabelText("Candidate policy set (optional)"), "policy_set_v2");
    await user.type(screen.getByLabelText("Connector id (optional)"), "connector_csv_assets");
    await user.click(screen.getByLabelText("Apply legal hold"));
    await user.click(screen.getByRole("button", { name: "Run replay" }));

    await waitFor(() => {
      expect(mocks.axisFetch).toHaveBeenCalledTimes(1);
    });
    const requestedPath = mocks.axisFetch.mock.calls[0][0] as string;
    const query = new URLSearchParams(requestedPath.split("?")[1]);
    expect(requestedPath.startsWith(`${OPERATIONS_API_PREFIX}/simulation/replay?`)).toBe(true);
    expect(Object.fromEntries(query.entries())).toEqual({
      tenant_id: "tenant_fixture",
      workflow_id: "wf_supply_fixture",
      limit: "50",
      retention_days: "365",
      legal_hold: "true",
      baseline_policy_set_id: "policy_set_v1",
      candidate_policy_set_id: "policy_set_v2",
      connector_id: "connector_csv_assets",
    });

    // Baseline-vs-simulated diff with the changed outcome highlighted.
    expect(await screen.findByText("2 decisions compared — 1 changed")).toBeInTheDocument();
    expect(screen.getByText("Baseline: Require Approval")).toBeInTheDocument();
    expect(screen.getByText("Simulated: Deny")).toBeInTheDocument();
    const rows = document.querySelectorAll("[data-changed-outcome]");
    expect(rows.length).toBeGreaterThanOrEqual(2);
    expect(
      screen.getByText("Supply approval gate").closest("[data-changed-outcome]"),
    ).toHaveAttribute("data-changed-outcome", "true");
    expect(
      screen.getByText("Evidence recording").closest("[data-changed-outcome]"),
    ).toHaveAttribute("data-changed-outcome", "false");

    // Policy-set diff summarized plain-first with mono secondary versions.
    expect(screen.getByText("Candidate set blocks the recorded promotion.")).toBeInTheDocument();
    expect(
      screen.getByText("policy_set_v1 / 1.0.0 → policy_set_v2 / 2.0.0"),
    ).toBeInTheDocument();

    // Raw result stays behind the Inspect drawer.
    expect(screen.getByRole("button", { name: "Inspect" })).toBeInTheDocument();
  });

  it("shows a loading state while the replay request is in flight", async () => {
    const user = userEvent.setup();
    let resolveResponse: (response: Response) => void = () => {};
    mocks.axisFetch.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveResponse = resolve;
        }),
    );

    render(<RunReplayForm tenantId="tenant_fixture" />);
    await user.click(screen.getByRole("button", { name: "Run replay" }));

    expect(screen.getByRole("button", { name: "Running replay…" })).toBeDisabled();

    resolveResponse(jsonResponse(replayResultFixture));
    await screen.findByText("2 decisions compared — 1 changed");
    expect(screen.getByRole("button", { name: "Run replay" })).toBeEnabled();
  });

  it("surfaces a safe API message and keeps its request reference in technical details", async () => {
    const user = userEvent.setup();
    mocks.axisFetch.mockResolvedValue(
      jsonResponse(
        {
          detail: {
            code: "validation_failed",
            message: "Baseline and candidate policy sets must both be provided.",
            debug_context: "secret=simulation-database-credential",
          },
        },
        422,
        "request-replay-422",
      ),
    );

    render(<RunReplayForm tenantId="tenant_fixture" />);
    await user.type(screen.getByLabelText("Baseline policy set (optional)"), "policy_set_v1");
    await user.click(screen.getByRole("button", { name: "Run replay" }));

    expect(await screen.findByText("Replay run failed")).toBeInTheDocument();
    expect(
      screen.getByText("Baseline and candidate policy sets must both be provided."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/simulation-database-credential/)).not.toBeInTheDocument();
    expect(screen.queryByText("request-replay-422")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Technical details" }));

    expect(screen.getByText("request-replay-422")).toBeInTheDocument();
    expect(screen.queryByText(/simulation-database-credential/)).not.toBeInTheDocument();
    expect(document.querySelector("[data-replay-result]")).not.toBeInTheDocument();
  });
});
