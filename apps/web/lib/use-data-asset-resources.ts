"use client";

import type { DataAssetResourcesView } from "./data-assets";
import { parseDataAssetResourcesView } from "./runtime-contracts/data-assets";
import { buildTenantScopedPath, DEMO_TENANT_ID } from "./tenant-scope";
import { useAxisQuery } from "./use-axis-query";

/**
 * Per-asset resource observations live on the dedicated `/data` plane next
 * to the catalog: one tenant-scoped endpoint per asset.
 */
export const DATA_ASSET_RESOURCES_ENDPOINTS = {
  resources: "/data/assets/resources",
} as const;

export function buildDataAssetResourcesPath(
  assetId: string,
  tenantId: string,
): string {
  return buildTenantScopedPath(
    `/data/assets/${encodeURIComponent(assetId)}/resources`,
    tenantId,
  );
}

export function useDataAssetResources(
  assetId: string | null,
  tenantId: string | null,
  enabled: boolean,
) {
  // Hooks must receive a stable path even while identity is unresolved. The
  // query gate guarantees the placeholder demo path is never requested until
  // the identity API has explicitly selected that tenant and an asset exists.
  const scopedPath = buildDataAssetResourcesPath(
    assetId ?? DEMO_TENANT_ID,
    tenantId ?? DEMO_TENANT_ID,
  );

  return useAxisQuery<DataAssetResourcesView>(scopedPath, {
    enabled: enabled && tenantId !== null && assetId !== null,
    expectedTenantId: tenantId ?? undefined,
    parse: parseDataAssetResourcesView,
  });
}
