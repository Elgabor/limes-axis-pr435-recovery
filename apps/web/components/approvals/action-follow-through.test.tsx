import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ActionRunList } from "@/lib/action-demo";

import { ActionFollowThrough } from "./action-follow-through";

const actionRunsFixture: ActionRunList = {
  tenant_id: "tenant_fixture",
  runs: [
    {
      action_run_id: "run-short-wait",
      action_id: "request_supplier_expedite",
      status: "approved_for_execution",
      approval_id: "appr_supply_fixture",
      workflow_id: "wf_supply_fixture",
      created_at: "2026-07-25T10:00:00Z",
      updated_at: "2026-07-25T10:00:00Z",
      waiting_duration_seconds: 3_600,
      outcome: null,
    },
    {
      action_run_id: "run-long-wait",
      action_id: "place_quality_hold",
      status: "approved_for_execution",
      approval_id: "appr_quality_fixture",
      workflow_id: "wf_quality_fixture",
      created_at: "2026-07-24T12:00:00Z",
      updated_at: "2026-07-24T12:00:00Z",
      waiting_duration_seconds: 78_183,
      outcome: null,
    },
    {
      action_run_id: "run-reported",
      action_id: "shift_maintenance_window",
      status: "execution_completed",
      approval_id: "appr_maintenance_fixture",
      workflow_id: "wf_maintenance_fixture",
      created_at: "2026-07-23T08:00:00Z",
      updated_at: "2026-07-23T09:30:00Z",
      waiting_duration_seconds: 5_400,
      outcome: {
        result_summary: "External executor moved the maintenance window.",
        evidence_refs: ["audit_maintenance_execution"],
      },
    },
    {
      action_run_id: "run-not-authorised",
      action_id: "generate_daily_brief",
      status: "execution_completed",
      approval_id: null,
      workflow_id: null,
      created_at: "2026-07-23T07:00:00Z",
      updated_at: "2026-07-23T10:00:00Z",
      waiting_duration_seconds: 10_800,
      outcome: {
        result_summary: "Read-only brief generated without an approval gate.",
        evidence_refs: ["audit_daily_brief"],
      },
    },
  ],
};

describe("ActionFollowThrough", () => {
  it("orders waits longest first and distinguishes waiting from reported outcomes", () => {
    render(<ActionFollowThrough actionRuns={actionRunsFixture} source="api" />);

    expect(
      screen.getByText(/Axis does not execute or retry approved actions\./),
    ).toBeInTheDocument();

    const awaiting = screen.getByRole("region", { name: "Awaiting external execution" });
    const awaitingItems = within(awaiting).getAllByRole("listitem");
    expect(awaitingItems).toHaveLength(2);
    expect(awaitingItems[0]).toHaveTextContent("Place Quality Hold");
    expect(awaitingItems[0]).toHaveTextContent("Waiting 21 hr 43 min");
    expect(awaitingItems[0]).not.toHaveTextContent("78183");
    expect(awaitingItems[1]).toHaveTextContent("Request Supplier Expedite");
    expect(awaitingItems[1]).toHaveTextContent("Waiting 1 hr");

    const approvalLink = within(awaitingItems[0]).getByRole("link", {
      name: "Open authorising approval",
    });
    expect(approvalLink).toHaveAttribute(
      "href",
      "/approvals?approval_id=appr_quality_fixture",
    );
    expect(approvalLink).toHaveClass("min-h-6", "min-w-6");

    const reported = screen.getByRole("region", { name: "Reported outcomes" });
    expect(reported).toHaveTextContent("External executor moved the maintenance window.");
    expect(reported).not.toHaveTextContent("Waiting for external executor");
    expect(reported).not.toHaveTextContent("Read-only brief generated without an approval gate.");
    expect(
      within(reported).getByRole("link", {
        name: "Open audit evidence: audit_maintenance_execution",
      }),
    ).toHaveAttribute("href", "/audit?event_id=audit_maintenance_execution");
  });

  it("renders an explicit empty state when no approved action exists", () => {
    render(
      <ActionFollowThrough
        actionRuns={{ tenant_id: "tenant_fixture", runs: [] }}
        source="api"
      />,
    );

    expect(
      screen.getByRole("heading", { name: "No approved actions yet" }),
    ).toBeInTheDocument();
  });

  it("renders the normal error panel when the action-run API is unavailable", () => {
    render(<ActionFollowThrough actionRuns={null} source="unavailable" />);

    expect(
      screen.getByRole("heading", { name: "Action run API unavailable" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/No follow-through state is inferred\./)).toBeInTheDocument();
  });
});
