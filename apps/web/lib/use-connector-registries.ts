"use client";

import { useCallback } from "react";
import {
  parseManufacturingConnectorCredentialHandleRegistry,
  parseManufacturingConnectorCredentialLeaseRegistry,
  parseManufacturingConnectorEgressPolicyRegistry,
  parseManufacturingConnectorEvidenceInvariantReport,
  parseManufacturingConnectorEvidenceInvariantSnapshotHistory,
  parseManufacturingConnectorRegistry,
  parseManufacturingConnectorRunRegistry,
} from "./runtime-contracts/connectors";
import {
  parseConnectorWorkspaceDetail,
  parseConnectorWorkspaceSummary,
} from "./runtime-contracts/connector-workspace";
import { useAxisQuery } from "./use-axis-query";
import { buildTenantScopedPath, DEMO_TENANT_ID, OPERATIONS_API_PREFIX } from "./tenant-scope";

export const CONNECTOR_ENDPOINTS = {
  registry: `${OPERATIONS_API_PREFIX}/connectors`,
  workspace: `${OPERATIONS_API_PREFIX}/connectors/workspace`,
  detail: `${OPERATIONS_API_PREFIX}/connectors/workspace/detail`,
  manifests: `${OPERATIONS_API_PREFIX}/connectors/manifests`,
  credentialHandles: `${OPERATIONS_API_PREFIX}/connectors/credential-handles`,
  credentialLeases: `${OPERATIONS_API_PREFIX}/connectors/credential-leases`,
  egressPolicies: `${OPERATIONS_API_PREFIX}/connectors/egress-policies`,
  runs: `${OPERATIONS_API_PREFIX}/connectors/runs`,
  evidenceInvariants: `${OPERATIONS_API_PREFIX}/connectors/evidence-invariants`,
  evidenceSnapshots: `${OPERATIONS_API_PREFIX}/connectors/evidence-invariants/snapshots`,
} as const;

/** One summary, then only the selected connector and the visible tab's reads. */
export function useConnectorRegistries(
  tenantId: string | null,
  enabled: boolean,
  snapshotId = "",
  connectorId = "",
  tab = "overview",
  offset = 0,
  wizardOpen = false,
) {
  const tenant = tenantId ?? DEMO_TENANT_ID;
  const queryOptions = {
    enabled: enabled && tenantId !== null,
    expectedTenantId: tenantId ?? undefined,
  };
  const registry = useAxisQuery(
    buildTenantScopedPath(CONNECTOR_ENDPOINTS.workspace, tenant, { offset: String(offset) }),
    { ...queryOptions, parse: parseConnectorWorkspaceSummary },
  );
  const evidenceSnapshots = useAxisQuery(
    buildTenantScopedPath(CONNECTOR_ENDPOINTS.evidenceSnapshots, tenant, {
      ...(snapshotId ? { snapshot_id: snapshotId } : {}),
      ...(connectorId ? { connector_id: connectorId } : {}),
    }),
    {
      ...queryOptions,
      enabled: queryOptions.enabled && Boolean(snapshotId),
      parse: parseManufacturingConnectorEvidenceInvariantSnapshotHistory,
    },
  );
  const snapshot = snapshotId
    ? evidenceSnapshots.data?.snapshots.find((item) => item.snapshot_id === snapshotId)
    : undefined;
  const selectedConnectorId = connectorId || snapshot?.connector_id
    || (!snapshotId ? registry.data?.connectors[0]?.manifest.connector_id : "") || "";
  const selectedEnabled = queryOptions.enabled && Boolean(selectedConnectorId)
    && (!snapshotId || Boolean(snapshot));
  const parseDetail = useCallback((value: unknown) => {
    const detail = parseConnectorWorkspaceDetail(value);
    if (detail.connector.manifest.connector_id !== selectedConnectorId) {
      throw new Error("Connector detail response does not match the selected connector.");
    }
    return detail;
  }, [selectedConnectorId]);
  const detail = useAxisQuery(
    buildTenantScopedPath(CONNECTOR_ENDPOINTS.detail, tenant, {
      connector_id: selectedConnectorId || "unresolved",
    }),
    { ...queryOptions, enabled: selectedEnabled, parse: parseDetail },
  );
  const activeTab = snapshotId && tab === "overview" ? "governance" : tab;
  const governance = selectedEnabled && activeTab === "governance";
  const runsVisible = selectedEnabled && activeTab === "runs";
  const scopedDetailPath = (path: string) => buildTenantScopedPath(path, tenant, {
    connector_id: selectedConnectorId || "unresolved",
  });
  const credentialHandles = useAxisQuery(
    scopedDetailPath(CONNECTOR_ENDPOINTS.credentialHandles),
    { ...queryOptions, enabled: governance, parse: parseManufacturingConnectorCredentialHandleRegistry },
  );
  const credentialLeases = useAxisQuery(
    scopedDetailPath(CONNECTOR_ENDPOINTS.credentialLeases),
    {
      ...queryOptions,
      enabled: governance || runsVisible,
      parse: parseManufacturingConnectorCredentialLeaseRegistry,
    },
  );
  const egressPolicies = useAxisQuery(
    scopedDetailPath(CONNECTOR_ENDPOINTS.egressPolicies),
    { ...queryOptions, enabled: governance, parse: parseManufacturingConnectorEgressPolicyRegistry },
  );
  const runs = useAxisQuery(
    scopedDetailPath(CONNECTOR_ENDPOINTS.runs),
    { ...queryOptions, enabled: runsVisible, parse: parseManufacturingConnectorRunRegistry },
  );
  const evidenceInvariants = useAxisQuery(
    scopedDetailPath(CONNECTOR_ENDPOINTS.evidenceInvariants),
    { ...queryOptions, enabled: governance, parse: parseManufacturingConnectorEvidenceInvariantReport },
  );
  const templates = useAxisQuery(
    buildTenantScopedPath(CONNECTOR_ENDPOINTS.registry, tenant),
    {
      ...queryOptions,
      enabled: queryOptions.enabled && wizardOpen,
      parse: parseManufacturingConnectorRegistry,
    },
  );

  return {
    registry,
    detail,
    selectedConnectorId,
    templates,
    credentialHandles,
    credentialLeases,
    egressPolicies,
    runs,
    evidenceInvariants,
    evidenceSnapshots,
  };
}

export type ConnectorRegistries = ReturnType<typeof useConnectorRegistries>;
