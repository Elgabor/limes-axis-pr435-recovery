import { z } from "zod";

import { connectorRegistryItem } from "./connectors";
import { manufacturingProvenanceSchema, parseContract, platformStatusSchema } from "./shared";

const label = z.string().min(1).max(512);
const count = z.number().int().nonnegative();
const workspaceItem = z.object({
  manifest: z.object({
    connector_id: label,
    display_name: label,
    connector_type: z.string().min(1).max(128),
  }),
  connector_status: platformStatusSchema,
  registry_origin: z.enum(["reference", "persisted_manifest"]),
  persisted_manifest: z.object({ status: z.string().min(1).max(128) }).nullable(),
  preview_sample: z.object({ record_count: count }).nullable(),
  last_successful_sync: z.object({
    run_id: label,
    completed_at: z.string().datetime({ offset: true }),
    records_read: count,
  }).nullable(),
});
const summary = z.object({
  tenant_id: label,
  plant_name: label.nullable(),
  scenario: label.nullable(),
  provenance: manufacturingProvenanceSchema,
  registry_status: platformStatusSchema,
  generated_at: z.string().datetime({ offset: true }),
  connectors: z.array(workspaceItem).max(50),
  total_connectors: count,
  offset: count,
  limit: z.number().int().min(1).max(50),
  next_offset: count.nullable(),
  counts: z.object({
    runs: count.nullable(),
    pending_proposals: count.nullable(),
    egress_policies: count.nullable(),
    evidence_issues: count.nullable(),
    source_limit: z.literal(100),
  }),
});
const detail = z.object({ tenant_id: label, connector: connectorRegistryItem });

export type ConnectorWorkspaceItem = z.infer<typeof workspaceItem>;
export type ConnectorWorkspaceSummary = z.infer<typeof summary>;
export type ConnectorWorkspaceDetail = z.infer<typeof detail>;

export function parseConnectorWorkspaceSummary(value: unknown): ConnectorWorkspaceSummary {
  return parseContract(summary, value);
}

export function parseConnectorWorkspaceDetail(value: unknown): ConnectorWorkspaceDetail {
  return parseContract(detail, value);
}
