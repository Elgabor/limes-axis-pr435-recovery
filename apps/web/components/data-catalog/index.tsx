"use client";

import { useMemo } from "react";

import { DataAssetDetail, UnknownDataAssetPanel } from "./detail";
import {
  DataAssetList,
  dataAssetEvidenceFilterValues,
  type DataAssetEvidenceFilter,
} from "./list";
import { Card } from "@/components/ui/card";
import { MasterDetail } from "@/components/ui/master-detail";
import { MetricStrip, type Metric } from "@/components/ui/metric-strip";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/ui/states";
import {
  enumUrlField,
  opaqueStringUrlField,
  stringUrlField,
  useConsoleUrlState,
} from "@/lib/console-url-state";
import type { DataAssetEvidenceState } from "@/lib/data-assets";
import { strings } from "@/lib/strings";
import { useConsoleTenantScope } from "@/lib/use-console-tenant-scope";
import { DATA_ASSET_ENDPOINTS, useDataAssetCatalog } from "@/lib/use-data-asset-catalog";

const dataCatalogUrlSchema = {
  assetId: opaqueStringUrlField("asset_id"),
  evidence: enumUrlField<DataAssetEvidenceFilter>(
    "evidence",
    dataAssetEvidenceFilterValues,
    "all",
  ),
  q: stringUrlField("q"),
};

function metricTone(status: "ready" | "watch" | "action_required"): Metric["tone"] {
  if (status === "action_required") {
    return "action";
  }
  return status === "watch" ? "watch" : "ready";
}

/**
 * Data Asset Catalog console: the governed layer between connectors and the
 * ontology. One tenant-scoped endpoint feeds the whole page; filters and the
 * selected asset are URL-backed so deep links stay shareable and fail closed.
 */
export function DataCatalog() {
  const { tenantId, tenantQueriesEnabled } = useConsoleTenantScope();
  const [urlState, setUrlState] = useConsoleUrlState(dataCatalogUrlSchema);
  const catalog = useDataAssetCatalog(tenantId, tenantQueriesEnabled);
  const copy = strings.dataCatalog;

  const filteredAssets = useMemo(() => {
    const assets = catalog.data?.assets ?? [];
    const needle = urlState.q.trim().toLowerCase();
    return assets.filter((asset) => {
      if (
        urlState.evidence !== "all" &&
        asset.evidence !== (urlState.evidence as DataAssetEvidenceState)
      ) {
        return false;
      }
      if (
        needle.length > 0 &&
        !`${asset.display_name}\n${asset.connector_id}`.toLowerCase().includes(needle)
      ) {
        return false;
      }
      return true;
    });
  }, [catalog.data, urlState.evidence, urlState.q]);

  if (!tenantQueriesEnabled || catalog.isLoading) {
    return <LoadingPanel layout="detail" />;
  }

  if (catalog.error) {
    return (
      <ErrorPanel
        detail={copy.states.error.detail}
        endpoint={DATA_ASSET_ENDPOINTS.assets}
        reference={catalog.errorRequestId ?? undefined}
        title={copy.states.error.title}
      />
    );
  }

  if (!catalog.data) {
    return null;
  }

  const metrics: Metric[] = catalog.data.metrics.map((metric) => ({
    detail: metric.detail,
    label: metric.label,
    tone: metricTone(metric.status),
    value: metric.value,
  }));

  const requestedAssetId = urlState.assetId;
  const knownAssetIds = new Set(catalog.data.assets.map((asset) => asset.asset_id));
  const unknownAssetRequested =
    requestedAssetId.length > 0 && !knownAssetIds.has(requestedAssetId);
  const selectedAssetId =
    requestedAssetId.length > 0 && !unknownAssetRequested
      ? requestedAssetId
      : (filteredAssets[0]?.asset_id ?? "");
  const selectedAsset =
    filteredAssets.find((asset) => asset.asset_id === selectedAssetId) ?? null;

  return (
    <div className="grid min-w-0 gap-3.5">
      <MetricStrip metrics={metrics} />
      {catalog.data.assets.length === 0 ? (
        <Card>
          <EmptyPanel
            detail={copy.states.empty.detail}
            title={copy.states.empty.title}
          />
        </Card>
      ) : (
        <MasterDetail
          detail={
            unknownAssetRequested ? (
              <UnknownDataAssetPanel assetId={requestedAssetId} />
            ) : selectedAsset ? (
              <DataAssetDetail asset={selectedAsset} />
            ) : (
              <Card>
                <EmptyPanel
                  detail={copy.states.noMatches.detail}
                  title={copy.states.noMatches.title}
                />
              </Card>
            )
          }
          list={
            <DataAssetList
              assets={filteredAssets}
              evidenceFilter={urlState.evidence}
              onEvidenceFilterChange={(evidence) => setUrlState({ evidence })}
              onSearchChange={(q) => setUrlState({ q })}
              onSelect={(assetId) => setUrlState({ assetId }, { history: "push" })}
              search={urlState.q}
              selectedAssetId={selectedAssetId}
            />
          }
        />
      )}
    </div>
  );
}
