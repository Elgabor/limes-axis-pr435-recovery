/** Build a detail route from one opaque ontology node-id path segment. */
export function buildOntologyEntityRoute(nodeId: string): string {
  return `/ontology/${encodeURIComponent(nodeId)}`;
}
