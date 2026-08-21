"use client";

import type {
  DataAssetContractEvaluationView,
  DataAssetContractView,
} from "./data-assets";
import {
  parseDataAssetContractEvaluationView,
  parseDataAssetContractView,
} from "./runtime-contracts/data-assets";
import { buildTenantScopedPath, DEMO_TENANT_ID } from "./tenant-scope";
import { useAxisQuery } from "./use-axis-query";

/**
 * Per-asset data contracts live on the dedicated `/data` plane next to the
 * catalog: declaration and read-time evaluation, one tenant-scoped endpoint
 * each.
 */
export function buildDataAssetContractPath(
  assetId: string,
  tenantId: string,
): string {
  return buildTenantScopedPath(
    `/data/assets/${encodeURIComponent(assetId)}/contract`,
    tenantId,
  );
}

export function buildDataAssetContractEvaluationPath(
  assetId: string,
  tenantId: string,
): string {
  return buildTenantScopedPath(
    `/data/assets/${encodeURIComponent(assetId)}/contract/evaluation`,
    tenantId,
  );
}

export function useDataAssetContract(
  assetId: string | null,
  tenantId: string | null,
  enabled: boolean,
) {
  const scopedPath = buildDataAssetContractPath(
    assetId ?? DEMO_TENANT_ID,
    tenantId ?? DEMO_TENANT_ID,
  );

  return useAxisQuery<DataAssetContractView>(scopedPath, {
    enabled: enabled && tenantId !== null && assetId !== null,
    expectedTenantId: tenantId ?? undefined,
    parse: parseDataAssetContractView,
  });
}

export function useDataAssetContractEvaluation(
  assetId: string | null,
  tenantId: string | null,
  enabled: boolean,
) {
  const scopedPath = buildDataAssetContractEvaluationPath(
    assetId ?? DEMO_TENANT_ID,
    tenantId ?? DEMO_TENANT_ID,
  );

  return useAxisQuery<DataAssetContractEvaluationView>(scopedPath, {
    enabled: enabled && tenantId !== null && assetId !== null,
    expectedTenantId: tenantId ?? undefined,
    parse: parseDataAssetContractEvaluationView,
  });
}
