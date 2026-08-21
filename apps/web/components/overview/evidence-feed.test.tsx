import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvidenceFeed } from "./evidence-feed";
import { auditEventsFixture } from "./overview-fixtures";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

describe("EvidenceFeed", () => {
  it("renders a loading skeleton without any error copy while loading", () => {
    render(<EvidenceFeed auditEvents={{ data: null, source: "loading" }} />);

    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    expect(screen.queryByText(/unavailable/i)).not.toBeInTheDocument();
  });

  it("renders the ErrorPanel when the audit events API is unavailable", () => {
    render(<EvidenceFeed auditEvents={{ data: null, source: "unavailable" }} />);

    expect(
      screen.getByRole("heading", { name: "Audit evidence API unavailable" }),
    ).toBeInTheDocument();
    // Endpoint stays demoted behind the technical-details expander.
    expect(screen.queryByText(`${OPERATIONS_API_PREFIX}/audit/events`)).not.toBeInTheDocument();
  });

  it("renders the EmptyPanel when the ledger has no events yet", () => {
    render(
      <EvidenceFeed
        auditEvents={{ data: { ...auditEventsFixture, events: [] }, source: "api" }}
      />,
    );

    expect(screen.getByRole("heading", { name: "No audit evidence yet" })).toBeInTheDocument();
  });

  it("renders one feed row per event with a deep link into the audit page", () => {
    render(<EvidenceFeed auditEvents={{ data: auditEventsFixture, source: "api" }} />);

    const approvalLink = screen.getByRole("link", { name: /Approval Decision Recorded/ });
    expect(approvalLink).toHaveAttribute(
      "href",
      "/audit?event_id=00000000-0000-4000-8000-000000000001",
    );
    expect(screen.getByRole("link", { name: /Agent Proposal Recorded/ })).toHaveAttribute(
      "href",
      "/audit?event_id=00000000-0000-4000-8000-000000000004",
    );
    // Actor + event count come straight from the payload.
    expect(screen.getByText("Showing 4 of 4")).toBeInTheDocument();
    expect(screen.getByText("connector-runtime")).toBeInTheDocument();
  });

  it("renders one compact sparkline in the feed header", () => {
    render(<EvidenceFeed auditEvents={{ data: auditEventsFixture, source: "api" }} />);

    expect(
      screen.getByRole("img", {
        name:
          "Recent audit events by category. approval: 1, connector: 1, workflow: 1, agent: 1.",
      }),
    ).toBeInTheDocument();
  });
});
