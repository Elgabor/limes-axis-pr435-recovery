import { describe, expect, it } from "vitest";

import {
  buildOntologyEntityDetail,
  countNodesByType,
  formatNodeType,
  nodeLabelById,
  type ManufacturingOntology,
  type OntologyRelationship,
} from "./ontology-demo";

function relationshipMetadata(
  relationshipId: string,
  ownerRole = "Operations Steward",
): OntologyRelationship["metadata"] {
  return {
    owner_role: ownerRole,
    source_adapter: "axis-reference-ontology",
    confidence: 0.9,
    evidence_refs: [`ontology:${relationshipId}`],
    valid_from: "2026-06-22T09:00:00+02:00",
    valid_to: null,
    last_verified_at: "2026-06-22T09:00:00+02:00",
    verification_status: "reference_verified",
  };
}

const ontologyFixture: ManufacturingOntology = {
  tenant_id: "tenant_fixture",
  plant_name: "Fixture Plant",
  scenario: "Runtime contract fixture",
  provenance: "reference_scenario",
  as_of: "2026-06-22T09:00:00+02:00",
  source_systems: ["ERP", "MES", "Axis Audit"],
  permission_notes: ["Fixture data is scoped to tests."],
  graph_query: {
    adapter: "axis-ontology-query-adapter",
    source: "fixture",
    query_mode: "tenant_scoped",
    tenant_id: "tenant_fixture",
    actor_id: "axis-test-role",
    permission_decision: {
      allowed: true,
      reason: "test_fixture",
    },
    requested_scopes: ["operations:read"],
    applied_relationship_scopes: ["operations:read", "approvals:read", "agents:read"],
    denied_relationship_count: 0,
    returned_node_count: 5,
    returned_relationship_count: 4,
    typeql: null,
    notes: ["Fixture graph query metadata."],
  },
  nodes: [
    {
      node_id: "asset_fixture_line",
      label: "Fixture Line",
      node_type: "asset",
      domain: "Operations",
      status: "ready",
      source_system: "MES",
      summary: "A production line fixture.",
    },
    {
      node_id: "risk_supply_fixture",
      label: "Supply Fixture Risk",
      node_type: "risk",
      domain: "Supply",
      status: "watch",
      source_system: "ERP",
      summary: "A delayed supplier batch risk.",
    },
    {
      node_id: "wf_supply_fixture",
      label: "Supply Fixture Workflow",
      node_type: "workflow",
      domain: "Supply",
      status: "action_required",
      source_system: "Axis Workflow",
      summary: "Workflow waiting for owner approval.",
    },
    {
      node_id: "appr_supply_fixture",
      label: "Supply Fixture Approval",
      node_type: "approval",
      domain: "Supply",
      status: "action_required",
      source_system: "Axis Approvals",
      summary: "Approval gate for the supply action.",
    },
    {
      node_id: "agent_supply_fixture",
      label: "Supply Fixture Agent",
      node_type: "agent",
      domain: "Supply",
      status: "watch",
      source_system: "Axis Agents",
      summary: "Agent requesting the approval.",
    },
  ],
  relationships: [
    {
      relationship_id: "rel_risk_impacts_asset",
      source_id: "risk_supply_fixture",
      target_id: "asset_fixture_line",
      relation_type: "impacts",
      summary: "The supplier delay can impact the production line.",
      permission_scope: "operations:read",
      metadata: relationshipMetadata("rel_risk_impacts_asset"),
    },
    {
      relationship_id: "rel_workflow_mitigates_risk",
      source_id: "wf_supply_fixture",
      target_id: "risk_supply_fixture",
      relation_type: "mitigates",
      summary: "The workflow mitigates the supply risk.",
      permission_scope: "operations:read",
      metadata: relationshipMetadata("rel_workflow_mitigates_risk"),
    },
    {
      relationship_id: "rel_workflow_requires_approval",
      source_id: "wf_supply_fixture",
      target_id: "appr_supply_fixture",
      relation_type: "requires",
      summary: "The workflow requires owner approval.",
      permission_scope: "approvals:read",
      metadata: relationshipMetadata(
        "rel_workflow_requires_approval",
        "Approval Steward",
      ),
    },
    {
      relationship_id: "rel_agent_requests_workflow",
      source_id: "agent_supply_fixture",
      target_id: "wf_supply_fixture",
      relation_type: "requests",
      summary: "The agent requested the workflow.",
      permission_scope: "agents:read",
      metadata: relationshipMetadata(
        "rel_agent_requests_workflow",
        "Agent Operations Steward",
      ),
    },
  ],
};

describe("ontology helpers", () => {
  it("keeps relationship endpoints resolvable", () => {
    const labels = nodeLabelById(ontologyFixture);

    expect(labels.get("asset_fixture_line")).toBe("Fixture Line");
    expect(
      ontologyFixture.relationships.every(
        (relationship) =>
          labels.has(relationship.source_id) && labels.has(relationship.target_id),
      ),
    ).toBe(true);
    expect(
      ontologyFixture.relationships.every(
        (relationship) =>
          relationship.metadata.owner_role.length > 0 &&
          relationship.metadata.evidence_refs.length > 0,
      ),
    ).toBe(true);
  });

  it("counts nodes by type", () => {
    const counts = countNodesByType(ontologyFixture);

    expect(counts.get("asset")).toBe(1);
    expect(counts.get("risk")).toBe(1);
    expect(counts.get("workflow")).toBe(1);
    expect(counts.get("approval")).toBe(1);
    expect(counts.get("agent")).toBe(1);
  });

  it("formats node type labels for the UI", () => {
    expect(formatNodeType("audit_event")).toBe("Audit Event");
    expect(formatNodeType("workflow")).toBe("Workflow");
  });

  it("builds connected entity detail pages from the provided graph", () => {
    const detail = buildOntologyEntityDetail(ontologyFixture, "wf_supply_fixture");

    expect(detail?.node.label).toBe("Supply Fixture Workflow");
    expect(detail?.inbound_count).toBe(1);
    expect(detail?.outbound_count).toBe(2);
    expect(detail?.required_permissions).toEqual([
      "agents:read",
      "approvals:read",
      "operations:read",
    ]);
    expect(detail?.evidence_refs).toEqual(["wf_supply_fixture"]);
    expect(detail?.related_workflows).toEqual(["wf_supply_fixture"]);
    expect(detail?.related_approvals).toEqual(["appr_supply_fixture"]);
    expect(detail?.related_agents).toEqual(["agent_supply_fixture"]);
  });

  it("returns null when a detail node is missing", () => {
    expect(buildOntologyEntityDetail(ontologyFixture, "missing")).toBeNull();
  });
});
