import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  useAxisQuery: vi.fn(),
}));

vi.mock("@/lib/use-axis-query", () => ({
  useAxisQuery: mocks.useAxisQuery,
}));

import { strings } from "@/lib/strings";

import { PostureCards } from "./posture-cards";
import {
  modelRoutingFixture,
  overviewFixture,
  policyRegistryFixture,
  snapshotFixture,
} from "./overview-fixtures";

function mockPoliciesQuery(result: {
  data: typeof policyRegistryFixture | null;
  source: "loading" | "api" | "unavailable";
}) {
  mocks.useAxisQuery.mockReturnValue({
    data: result.data,
    source: result.source,
    error: null,
    isRefreshing: false,
    isLoading: result.source === "loading",
    isUnavailable: result.source === "unavailable",
  });
}

beforeEach(() => {
  mocks.useAxisQuery.mockReset();
});

function card(label: string): HTMLElement {
  const cards = screen.getAllByRole("listitem");
  const match = cards.find((item) => within(item).queryByText(label) !== null);
  if (!match) {
    throw new Error(`No posture card labelled ${label}`);
  }
  return match;
}

describe("PostureCards", () => {
  it("renders five posture cards with one number and one link each", () => {
    mockPoliciesQuery({ data: policyRegistryFixture, source: "api" });
    render(
      <PostureCards
        overview={{ data: overviewFixture, source: "api" }}
        routing={{ data: modelRoutingFixture, source: "api" }}
        snapshot={{ data: snapshotFixture, source: "api" }}
      />,
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(5);

    expect(within(card(strings.overview.posture.agents.label)).getByText("2")).toBeInTheDocument();
    expect(within(card(strings.overview.posture.agents.label)).getByRole("link", { name: /Manage agents/ })).toHaveAttribute(
      "href",
      "/agents",
    );
    expect(within(card(strings.overview.posture.workflows.label)).getByText("2")).toBeInTheDocument();
    expect(
      within(card(strings.overview.posture.workflows.label)).getByRole("link", { name: /Open workflows/ }),
    ).toHaveAttribute("href", "/workflows");
    expect(within(card(strings.overview.posture.connectors.label)).getByText("1")).toBeInTheDocument();
    expect(
      within(card(strings.overview.posture.connectors.label)).getByRole("link", { name: /Manage connectors/ }),
    ).toHaveAttribute("href", "/connectors");
    expect(within(card(strings.overview.posture.policies.label)).getByText("1")).toBeInTheDocument();
    expect(
      within(card(strings.overview.posture.policies.label)).getByRole("link", { name: /Review policies/ }),
    ).toHaveAttribute("href", "/policies");
    expect(within(card(strings.overview.posture.models.label)).getByText("2")).toBeInTheDocument();
    expect(within(card(strings.overview.posture.models.label)).getByRole("link", { name: /View routing/ })).toHaveAttribute(
      "href",
      "/model-routing",
    );
  });

  it("degrades only the cards whose endpoint failed", () => {
    mockPoliciesQuery({ data: policyRegistryFixture, source: "api" });
    render(
      <PostureCards
        overview={{ data: null, source: "unavailable" }}
        routing={{ data: modelRoutingFixture, source: "api" }}
        snapshot={{ data: snapshotFixture, source: "api" }}
      />,
    );

    expect(within(card(strings.overview.posture.agents.label)).getByText("Unavailable")).toBeInTheDocument();
    expect(within(card(strings.overview.posture.workflows.label)).getByText("Unavailable")).toBeInTheDocument();
    // The other three cards keep their API-backed values.
    expect(within(card(strings.overview.posture.connectors.label)).getByText("1")).toBeInTheDocument();
    expect(within(card(strings.overview.posture.policies.label)).getByText("1")).toBeInTheDocument();
    expect(within(card(strings.overview.posture.models.label)).getByText("2")).toBeInTheDocument();
  });
});
