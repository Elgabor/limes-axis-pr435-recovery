import type { ManufacturingProvenance, PlatformStatus } from "./platform-overview";

export type OntologyNodeType =
  | "organization"
  | "asset"
  | "process"
  | "workflow"
  | "risk"
  | "approval"
  | "agent"
  | "system"
  | "policy"
  | "audit_event";

export type OntologyNode = {
  node_id: string;
  label: string;
  node_type: OntologyNodeType;
  domain: string;
  status: PlatformStatus;
  source_system: string;
  summary: string;
};

export type OntologyRelationship = {
  relationship_id: string;
  source_id: string;
  target_id: string;
  relation_type: string;
  summary: string;
  permission_scope: string;
  metadata: OntologyRelationshipMetadata;
};

export type OntologyRelationshipMetadata = {
  owner_role: string;
  source_adapter: string;
  confidence: number;
  evidence_refs: string[];
  valid_from: string;
  valid_to: string | null;
  last_verified_at: string;
  verification_status: string;
};

export type OntologyGraphQueryMetadata = {
  adapter: string;
  source: string;
  query_mode: string;
  tenant_id: string;
  actor_id: string;
  permission_decision: {
    allowed: boolean;
    reason: string;
  };
  requested_scopes: string[];
  applied_relationship_scopes: string[];
  denied_relationship_count: number;
  returned_node_count: number;
  returned_relationship_count: number;
  typeql: string | null;
  notes: string[];
};

export type ManufacturingOntology = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  as_of: string;
  nodes: OntologyNode[];
  relationships: OntologyRelationship[];
  source_systems: string[];
  permission_notes: string[];
  graph_query: OntologyGraphQueryMetadata;
};

export type OntologyEntityRelationship = {
  direction: "inbound" | "outbound";
  relationship: OntologyRelationship;
  peer_node: OntologyNode;
};

export type ManufacturingOntologyEntityDetail = {
  tenant_id: string;
  plant_name: string | null;
  scenario: string | null;
  provenance: ManufacturingProvenance;
  as_of: string;
  node: OntologyNode;
  connected_relationships: OntologyEntityRelationship[];
  inbound_count: number;
  outbound_count: number;
  required_permissions: string[];
  evidence_refs: string[];
  data_access: string[];
  governed_by: string[];
  related_workflows: string[];
  related_approvals: string[];
  related_agents: string[];
  detail_notes: string[];
};

export function nodeLabelById(ontology: ManufacturingOntology): Map<string, string> {
  return new Map(ontology.nodes.map((node) => [node.node_id, node.label]));
}

export function countNodesByType(ontology: ManufacturingOntology): Map<OntologyNodeType, number> {
  return ontology.nodes.reduce((counts, node) => {
    counts.set(node.node_type, (counts.get(node.node_type) ?? 0) + 1);
    return counts;
  }, new Map<OntologyNodeType, number>());
}

export function formatNodeType(type: OntologyNodeType): string {
  return type
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

type DetailLists = {
  evidence_refs: string[];
  data_access: string[];
  detail_notes: string[];
};

function defaultDetailLists(node: OntologyNode): DetailLists {
  return {
    evidence_refs: [node.node_id],
    data_access: [
      `${node.source_system} summary`,
      `${node.domain} relationship context`,
      `${node.node_type} metadata`,
    ],
    detail_notes: [
      "This entity detail is read-only.",
      "Production entity details will require tenant-scoped graph query permissions.",
    ],
  };
}

export function buildOntologyEntityDetail(
  ontology: ManufacturingOntology,
  nodeId: string,
): ManufacturingOntologyEntityDetail | null {
  const nodeById = new Map(ontology.nodes.map((node) => [node.node_id, node]));
  const node = nodeById.get(nodeId);

  if (!node) {
    return null;
  }

  const connectedRelationships: OntologyEntityRelationship[] = [];

  for (const relationship of ontology.relationships) {
    if (relationship.source_id === nodeId) {
      const peerNode = nodeById.get(relationship.target_id);
      if (peerNode) {
        connectedRelationships.push({
          direction: "outbound",
          relationship,
          peer_node: peerNode,
        });
      }
    } else if (relationship.target_id === nodeId) {
      const peerNode = nodeById.get(relationship.source_id);
      if (peerNode) {
        connectedRelationships.push({
          direction: "inbound",
          relationship,
          peer_node: peerNode,
        });
      }
    }
  }

  const inboundCount = connectedRelationships.filter(
    (relationship) => relationship.direction === "inbound",
  ).length;
  const outboundCount = connectedRelationships.length - inboundCount;
  const permissions = Array.from(
    new Set(
      connectedRelationships.map((item) => item.relationship.permission_scope),
    ),
  ).sort();
  const detailLists = defaultDetailLists(node);

  return {
    tenant_id: ontology.tenant_id,
    plant_name: ontology.plant_name,
    scenario: ontology.scenario,
    provenance: ontology.provenance,
    as_of: ontology.as_of,
    node,
    connected_relationships: connectedRelationships,
    inbound_count: inboundCount,
    outbound_count: outboundCount,
    required_permissions: permissions.length > 0 ? permissions : [`${node.domain.toLowerCase()}:read`],
    evidence_refs: detailLists.evidence_refs,
    data_access: detailLists.data_access,
    governed_by: connectedRelationships
      .filter((item) => item.relationship.relation_type === "governs")
      .map((item) => item.peer_node.node_id)
      .sort(),
    related_workflows: Array.from(
      new Set([
        ...connectedRelationships
          .filter((item) => item.peer_node.node_type === "workflow")
          .map((item) => item.peer_node.node_id),
        ...(node.node_type === "workflow" ? [node.node_id] : []),
      ]),
    ).sort(),
    related_approvals: Array.from(
      new Set([
        ...connectedRelationships
          .filter((item) => item.peer_node.node_type === "approval")
          .map((item) => item.peer_node.node_id),
        ...(node.node_type === "approval" ? [node.node_id] : []),
      ]),
    ).sort(),
    related_agents: Array.from(
      new Set([
        ...connectedRelationships
          .filter((item) => item.peer_node.node_type === "agent")
          .map((item) => item.peer_node.node_id),
        ...(node.node_type === "agent" ? [node.node_id] : []),
      ]),
    ).sort(),
    detail_notes: detailLists.detail_notes,
  };
}
