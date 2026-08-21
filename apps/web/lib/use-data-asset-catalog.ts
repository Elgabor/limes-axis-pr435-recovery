"use client";

import type { DataAssetCatalog } from "./data-assets";
import { parseDataAssetCatalog } from "./runtime-contracts/data-assets";
import { buildTenantScopedPath, DEMO_TENANT_ID } from "./tenant-scope";
import { useAxisQuery } from "./use-axis-query";

/**
 * The data asset catalog lives on the dedicated `/data` plane: it is a
 * first-class platform surface, not part of the demo operations namespace.
 */
export const DATA_ASSET_ENDPOINTS = {
  assets: "/data/assets",
} as const;

export function useDataAssetCatalog(tenantId: string | null, enabled: boolean) {
  // Hooks must receive a stable path even while identity is unresolved. The
  // query gate guarantees the placeholder demo path is never requested until
  // the identity API has explicitly selected that tenant.
  const scopedPath = buildTenantScopedPath(
    DATA_ASSET_ENDPOINTS.assets,
    tenantId ?? DEMO_TENANT_ID,
  );

  return useAxisQuery<DataAssetCatalog>(scopedPath, {
    enabled: enabled && tenantId !== null,
    expectedTenantId: tenantId ?? undefined,
    parse: parseDataAssetCatalog,
  });
}
