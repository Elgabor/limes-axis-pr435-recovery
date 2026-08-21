import { render, screen } from "@testing-library/react";
import { getRouteMatcher } from "next/dist/shared/lib/router/utils/route-matcher";
import { getRouteRegex } from "next/dist/shared/lib/router/utils/route-regex";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildOntologyEntityRoute } from "@/lib/ontology-routes";

vi.mock("@/components/console-page", () => ({
  ConsolePage: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));

vi.mock("@/components/ontology-entity-detail", () => ({
  OntologyEntityDetail: ({ nodeId }: { nodeId: string }) => (
    <output data-testid="entity-node-id">{nodeId}</output>
  ),
}));

import OntologyEntityPage, { generateMetadata } from "./page";

const matchOntologyRoute = getRouteMatcher(getRouteRegex("/ontology/[nodeId]"));

function routeParams(nodeId: string) {
  const params = matchOntologyRoute(buildOntologyEntityRoute(nodeId));
  if (!params || typeof params.nodeId !== "string") {
    throw new Error("Next did not match the ontology entity route.");
  }
  return { params: Promise.resolve({ nodeId: params.nodeId }) };
}

describe("ontology entity page route boundary", () => {
  it("passes the decoded opaque node ID to the full-page entity detail", async () => {
    render(
      await OntologyEntityPage(
        routeParams(" node/with?# "),
      ),
    );

    expect(screen.getByTestId("entity-node-id").textContent).toBe(" node/with?# ");
  });

  it("uses the decoded node ID in metadata", async () => {
    await expect(generateMetadata(routeParams("asset/line?2"))).resolves.toEqual({
      title: "Entity asset/line?2",
    });
  });

  it("does not decode a literal percent escape for a second time", async () => {
    const nodeId = "asset%2Fline%3F2";

    render(await OntologyEntityPage(routeParams(nodeId)));

    expect(screen.getByTestId("entity-node-id")).toHaveTextContent(nodeId);
    await expect(generateMetadata(routeParams(nodeId))).resolves.toEqual({
      title: `Entity ${nodeId}`,
    });
  });

  it("renders a malformed percent escape without throwing", async () => {
    render(await OntologyEntityPage(routeParams("node%E0%A4%A")));

    expect(screen.getByTestId("entity-node-id")).toHaveTextContent("node%E0%A4%A");
  });
});
