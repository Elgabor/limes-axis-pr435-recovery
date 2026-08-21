"use client";

import type { DataAssetStewardshipView } from "./data-assets";
import { parseDataAssetStewardshipView } from "./runtime-contracts/data-assets";
import { buildTenantScopedPath, DEMO_TENANT_ID } from "./tenant-scope";
import { useAxisQuery } from "./use-axis-query";

/**
 * Per-asset stewardship lives on the dedicated `/data` plane next to the
 * catalog: one tenant-scoped endpoint per asset.
 */
export const DATA_ASSET_STEWARDSHIP_ENDPOINTS = {
  stewardship: "/data/assets/stewardship",
} as const;

export function buildDataAssetStewardshipPath(
  assetId: string,
  tenantId: string,
): string {
  return buildTenantScopedPath(
    `/data/assets/${encodeURIComponent(assetId)}/stewardship`,
    tenantId,
  );
}

export function useDataAssetStewardship(
  assetId: string | null,
  tenantId: string | null,
  enabled: boolean,
) {
  // Hooks must receive a stable path even while identity is unresolved. The
  // query gate guarantees the placeholder demo path is never requested until
  // the identity API has explicitly selected that tenant and an asset exists.
  const scopedPath = buildDataAssetStewardshipPath(
    assetId ?? DEMO_TENANT_ID,
    tenantId ?? DEMO_TENANT_ID,
  );

  return useAxisQuery<DataAssetStewardshipView>(scopedPath, {
    enabled: enabled && tenantId !== null && assetId !== null,
    expectedTenantId: tenantId ?? undefined,
    parse: parseDataAssetStewardshipView,
  });
}
