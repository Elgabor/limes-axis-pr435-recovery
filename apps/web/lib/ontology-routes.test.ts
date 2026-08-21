import { describe, expect, it } from "vitest";
import { getRouteMatcher } from "next/dist/shared/lib/router/utils/route-matcher";
import { getRouteRegex } from "next/dist/shared/lib/router/utils/route-regex";

import { buildOntologyEntityRoute } from "./ontology-routes";

const matchOntologyRoute = getRouteMatcher(getRouteRegex("/ontology/[nodeId]"));

function nextRouteNodeId(nodeId: string): string {
  const params = matchOntologyRoute(buildOntologyEntityRoute(nodeId));
  if (!params || typeof params.nodeId !== "string") {
    throw new Error("Next did not match the ontology entity route.");
  }
  return params.nodeId;
}

describe("ontology entity routes", () => {
  it("round-trips an opaque ID through the installed Next route matcher", () => {
    const nodeId = " node/with?# ";
    const route = buildOntologyEntityRoute(nodeId);

    expect(route).toBe("/ontology/%20node%2Fwith%3F%23%20");
    expect(nextRouteNodeId(nodeId)).toBe(nodeId);
  });

  it("preserves a literal percent escape after Next performs its one decode", () => {
    const nodeId = "node%2Fwith%20escape";

    expect(buildOntologyEntityRoute(nodeId)).toBe("/ontology/node%252Fwith%2520escape");
    expect(nextRouteNodeId(nodeId)).toBe(nodeId);
  });

  it("retains malformed-looking literal escapes as opaque ID text", () => {
    const nodeId = "node%E0%A4%A";

    expect(nextRouteNodeId(nodeId)).toBe(nodeId);
  });
});
