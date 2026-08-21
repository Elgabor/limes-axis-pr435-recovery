import type {
  ManufacturingOntology,
  OntologyNode,
  OntologyRelationship,
} from "@/lib/ontology-demo";

/*
 * Deterministic ontology payloads for component tests. Kept out of the
 * production bundle — only test files import from this module.
 */

function node(
  overrides: Partial<OntologyNode> & Pick<OntologyNode, "node_id" | "node_type" | "label">,
): OntologyNode {
  return {
    domain: "Quality",
    status: "ready",
    source_system: "MES",
    summary: "Fixture node summary.",
    ...overrides,
  };
}

function relationship(
  overrides: Partial<OntologyRelationship> &
    Pick<OntologyRelationship, "relationship_id" | "source_id" | "target_id">,
): OntologyRelationship {
  return {
    relation_type: "governs",
    summary: "Fixture relationship summary.",
    permission_scope: "ontology:read",
    metadata: {
      owner_role: "quality-owner",
      source_adapter: "typedb",
      confidence: 0.92,
      evidence_refs: ["audit_evt_fixture"],
      valid_from: "2026-01-01",
      valid_to: null,
      last_verified_at: "2026-07-01",
      verification_status: "verified",
    },
    ...overrides,
  };
}

export const ontologyFixture: ManufacturingOntology = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Runtime contract fixture",
  provenance: "reference_scenario",
  as_of: "2026-07-10T09:00:00+02:00",
  nodes: [
    node({ node_id: "org_fixture_plant", node_type: "organization", label: "Fixture Plant" }),
    node({ node_id: "asset_line_1", node_type: "asset", label: "Line 1 Filling" }),
    node({ node_id: "asset_line_2", node_type: "asset", label: "Line 2 Packaging" }),
    node({ node_id: "policy_egress", node_type: "policy", label: "Egress Policy" }),
  ],
  relationships: [
    relationship({
      relationship_id: "rel_plant_line_1",
      source_id: "org_fixture_plant",
      target_id: "asset_line_1",
      relation_type: "operates",
    }),
    relationship({
      relationship_id: "rel_plant_line_2",
      source_id: "org_fixture_plant",
      target_id: "asset_line_2",
      relation_type: "operates",
    }),
    relationship({
      relationship_id: "rel_policy_line_2",
      source_id: "policy_egress",
      target_id: "asset_line_2",
    }),
  ],
  source_systems: ["MES", "ERP"],
  permission_notes: ["Fixture ontology is scoped to tests."],
  graph_query: {
    adapter: "typedb",
    source: "fixture",
    query_mode: "read_only",
    tenant_id: "tenant_fixture",
    actor_id: "actor_fixture",
    permission_decision: { allowed: true, reason: "read_scope_present" },
    requested_scopes: ["ontology:read"],
    applied_relationship_scopes: ["ontology:read"],
    denied_relationship_count: 0,
    returned_node_count: 4,
    returned_relationship_count: 3,
    typeql: null,
    notes: [],
  },
};
