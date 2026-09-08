import { describe, expect, it } from "vitest";

import type { OntologyNode, OntologyRelationship } from "./ontology-demo";
import {
  buildOntologyGraphLayout,
  ONTOLOGY_GRAPH_MAX_ZOOM,
  ONTOLOGY_NODE_TIERS,
  panViewBox,
  zoomViewBox,
  type GraphViewBox,
} from "./ontology-graph-layout";

function node(overrides: Partial<OntologyNode> & Pick<OntologyNode, "node_id" | "node_type">): OntologyNode {
  return {
    label: overrides.node_id,
    domain: "Quality",
    status: "ready",
    source_system: "MES",
    summary: "Test node",
    ...overrides,
  };
}

function relationship(
  overrides: Partial<OntologyRelationship> &
    Pick<OntologyRelationship, "relationship_id" | "source_id" | "target_id">,
): OntologyRelationship {
  return {
    relation_type: "governs",
    summary: "Test relationship",
    permission_scope: "ontology:read",
    metadata: {
      owner_role: "Quality Lead",
      source_adapter: "typedb",
      confidence: 0.9,
      evidence_refs: [],
      valid_from: "2026-01-01",
      valid_to: null,
      last_verified_at: "2026-07-01",
      verification_status: "verified",
    },
    ...overrides,
  };
}

const nodes: OntologyNode[] = [
  node({ node_id: "org_plant", node_type: "organization", label: "Ravenna Works" }),
  node({ node_id: "asset_line_2", node_type: "asset", label: "Line 2 Packaging" }),
  node({ node_id: "process_qa", node_type: "process", label: "Quality Assurance" }),
  node({ node_id: "workflow_delay", node_type: "workflow", label: "Supplier Delay Review" }),
  node({ node_id: "agent_supply", node_type: "agent", label: "Supply Risk Agent" }),
  node({ node_id: "system_mes", node_type: "system", label: "MES" }),
  node({ node_id: "risk_batch", node_type: "risk", label: "Batch Risk", status: "watch" }),
  node({ node_id: "policy_egress", node_type: "policy", label: "Egress Policy" }),
  node({ node_id: "approval_expedite", node_type: "approval", label: "Expedite Approval" }),
  node({ node_id: "audit_evt", node_type: "audit_event", label: "Audit Event" }),
];

const relationships: OntologyRelationship[] = [
  relationship({ relationship_id: "rel_1", source_id: "org_plant", target_id: "asset_line_2" }),
  relationship({ relationship_id: "rel_2", source_id: "asset_line_2", target_id: "process_qa" }),
  relationship({ relationship_id: "rel_3", source_id: "policy_egress", target_id: "agent_supply" }),
  relationship({ relationship_id: "rel_4", source_id: "workflow_delay", target_id: "approval_expedite" }),
];

describe("buildOntologyGraphLayout", () => {
  it("is deterministic regardless of input order", () => {
    const layout = buildOntologyGraphLayout(nodes, relationships);
    const shuffled = buildOntologyGraphLayout(
      [...nodes].reverse(),
      [...relationships].reverse(),
    );

    expect(shuffled).toEqual(layout);
    expect(buildOntologyGraphLayout(nodes, relationships)).toEqual(layout);
  });

  it("positions every node inside the viewBox with a margin", () => {
    const layout = buildOntologyGraphLayout(nodes, relationships);

    expect(layout.nodes).toHaveLength(nodes.length);
    for (const positioned of layout.nodes) {
      expect(positioned.x).toBeGreaterThan(0);
      expect(positioned.x).toBeLessThan(layout.width);
      expect(positioned.y).toBeGreaterThan(0);
      expect(positioned.y).toBeLessThan(layout.height);
    }
  });

  it("places a lone organization at the center and outer tiers farther out", () => {
    const layout = buildOntologyGraphLayout(nodes, relationships);
    const cx = layout.width / 2;
    const cy = layout.height / 2;
    const distance = (id: string) => {
      const positioned = layout.nodes.find((entry) => entry.id === id);
      if (!positioned) {
        throw new Error(`missing node ${id}`);
      }
      return Math.hypot(positioned.x - cx, positioned.y - cy);
    };

    expect(distance("org_plant")).toBe(0);
    expect(distance("asset_line_2")).toBeGreaterThan(0);
    expect(distance("policy_egress")).toBeGreaterThan(distance("asset_line_2"));
    expect(distance("agent_supply")).toBeGreaterThan(distance("asset_line_2"));
  });

  it("assigns tiers from the node type map", () => {
    const layout = buildOntologyGraphLayout(nodes, relationships);

    for (const positioned of layout.nodes) {
      expect(positioned.tier).toBe(ONTOLOGY_NODE_TIERS[positioned.type]);
    }
  });

  it("keeps long labels separate from labels and node markers in a populated graph", () => {
    const populated = Array.from({ length: 18 }, (_, index) => node({
      node_id: `node_${index}`,
      node_type: nodes[index % nodes.length].node_type,
      label: `Supplier Delay Review Batch ${index}`,
    }));
    const layout = buildOntologyGraphLayout(populated, []);
    expect(layout.nodes.every((entry) => entry.labelVisible)).toBe(true);
    const boxes = layout.nodes.map((entry) => ({
      left: entry.labelX - entry.displayLabel.length * 4 - 4,
      right: entry.labelX + entry.displayLabel.length * 4 + 4,
      top: entry.labelY - 14,
      bottom: entry.labelY + 4,
    }));
    boxes.forEach((box, index) => {
      expect(box.top).toBeGreaterThanOrEqual(8);
      expect(box.bottom).toBeLessThanOrEqual(layout.height - 8);
      for (const other of boxes.slice(index + 1)) {
        expect(box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top).toBe(false);
      }
      for (const marker of layout.nodes) {
        expect(box.left < marker.x + 14 && box.right > marker.x - 14 && box.top < marker.y + 14 && box.bottom > marker.y - 14).toBe(false);
      }
    });
  });

  it("defers crowded labels to node focus without dropping their full names", () => {
    const crowded = Array.from({ length: 60 }, (_, index) => node({
      node_id: `node_${index}`,
      node_type: nodes[index % nodes.length].node_type,
      label: `Supplier Delay Review Batch ${index}`,
    }));
    const layout = buildOntologyGraphLayout(crowded, []);
    expect(layout.nodes.some((entry) => !entry.labelVisible)).toBe(true);
    expect(layout.nodes).toHaveLength(crowded.length);
    expect(layout.nodes.map((entry) => entry.label).sort()).toEqual(crowded.map((entry) => entry.label).sort());
    const visible = layout.nodes.filter((entry) => entry.labelVisible);
    visible.forEach((entry, index) => {
      for (const other of visible.slice(index + 1)) {
        const overlapsX = Math.abs(entry.labelX - other.labelX) < (entry.displayLabel.length + other.displayLabel.length) * 4 + 8;
        const overlapsY = Math.abs(entry.labelY - other.labelY) < 18;
        expect(overlapsX && overlapsY).toBe(false);
      }
    });
  });

  it("builds edge paths and symmetric neighbor sets from relationships", () => {
    const layout = buildOntologyGraphLayout(nodes, relationships);

    expect(layout.edges).toHaveLength(relationships.length);
    for (const edge of layout.edges) {
      expect(edge.path).toMatch(/^M [\d.-]+ [\d.-]+ Q [\d.-]+ [\d.-]+ [\d.-]+ [\d.-]+$/);
      expect(edge.length).toBeGreaterThan(0);
      expect(layout.neighbors.get(edge.sourceId)?.has(edge.targetId)).toBe(true);
      expect(layout.neighbors.get(edge.targetId)?.has(edge.sourceId)).toBe(true);
    }
  });

  it("skips relationships that reference unknown nodes", () => {
    const layout = buildOntologyGraphLayout(nodes, [
      ...relationships,
      relationship({ relationship_id: "rel_ghost", source_id: "org_plant", target_id: "missing" }),
    ]);

    expect(layout.edges.map((edge) => edge.id)).toEqual(["rel_1", "rel_2", "rel_3", "rel_4"]);
  });

  it("handles an empty payload", () => {
    const layout = buildOntologyGraphLayout([], []);

    expect(layout.nodes).toEqual([]);
    expect(layout.edges).toEqual([]);
    expect(layout.neighbors.size).toBe(0);
  });
});

const bounds: GraphViewBox = { x: 0, y: 0, width: 720, height: 560 };

describe("zoomViewBox", () => {
  it("zooms in around the given point, keeping it at the same viewport fraction", () => {
    const zoomed = zoomViewBox(bounds, 2, 180, 140, bounds);

    expect(zoomed.width).toBeCloseTo(360);
    expect(zoomed.height).toBeCloseTo(280);
    // (180, 140) sat at 25% of the old view; it stays at 25% of the new one.
    expect((180 - zoomed.x) / zoomed.width).toBeCloseTo(0.25);
    expect((140 - zoomed.y) / zoomed.height).toBeCloseTo(0.25);
  });

  it("preserves the bounds aspect ratio", () => {
    const zoomed = zoomViewBox(bounds, 3, 100, 100, bounds);

    expect(zoomed.width / zoomed.height).toBeCloseTo(bounds.width / bounds.height);
  });

  it("clamps zoom-out at the full bounds", () => {
    const zoomedIn = zoomViewBox(bounds, 2, 360, 280, bounds);
    const zoomedOut = zoomViewBox(zoomedIn, 0.1, 360, 280, bounds);

    expect(zoomedOut).toEqual(bounds);
  });

  it("clamps zoom-in at the maximum zoom factor", () => {
    const zoomed = zoomViewBox(bounds, 1000, 360, 280, bounds);

    expect(zoomed.width).toBeCloseTo(bounds.width / ONTOLOGY_GRAPH_MAX_ZOOM);
    expect(zoomed.height).toBeCloseTo(bounds.height / ONTOLOGY_GRAPH_MAX_ZOOM);
  });

  it("keeps the view inside the bounds when zooming near an edge", () => {
    const zoomedIn = zoomViewBox(bounds, 4, 700, 550, bounds);
    const zoomedOut = zoomViewBox(zoomedIn, 0.5, 700, 550, bounds);

    for (const view of [zoomedIn, zoomedOut]) {
      expect(view.x).toBeGreaterThanOrEqual(bounds.x);
      expect(view.y).toBeGreaterThanOrEqual(bounds.y);
      expect(view.x + view.width).toBeLessThanOrEqual(bounds.x + bounds.width);
      expect(view.y + view.height).toBeLessThanOrEqual(bounds.y + bounds.height);
    }
  });
});

describe("panViewBox", () => {
  it("shifts the view by the given delta", () => {
    const zoomed = zoomViewBox(bounds, 2, 360, 280, bounds);
    const panned = panViewBox(zoomed, 40, -30, bounds);

    expect(panned.x).toBeCloseTo(zoomed.x + 40);
    expect(panned.y).toBeCloseTo(zoomed.y - 30);
    expect(panned.width).toBe(zoomed.width);
    expect(panned.height).toBe(zoomed.height);
  });

  it("clamps panning at the bounds edges", () => {
    const zoomed = zoomViewBox(bounds, 2, 360, 280, bounds);
    const pannedFar = panViewBox(zoomed, 10_000, 10_000, bounds);

    expect(pannedFar.x).toBeCloseTo(bounds.x + bounds.width - zoomed.width);
    expect(pannedFar.y).toBeCloseTo(bounds.y + bounds.height - zoomed.height);

    const pannedBack = panViewBox(pannedFar, -10_000, -10_000, bounds);
    expect(pannedBack.x).toBe(bounds.x);
    expect(pannedBack.y).toBe(bounds.y);
  });

  it("is a no-op at full view", () => {
    expect(panViewBox(bounds, 50, 50, bounds)).toEqual(bounds);
  });
});
