"use client";

import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { cn } from "@/lib/cn";
import type { DataAsset, DataAssetEvidenceState } from "@/lib/data-assets";
import { formatDateTime, pluralize } from "@/lib/format";
import { strings } from "@/lib/strings";

const EVIDENCE_FILTER_VALUES = [
  "all",
  "sync_observed",
  "preview_only",
  "declared_only",
] as const;

export type DataAssetEvidenceFilter = (typeof EVIDENCE_FILTER_VALUES)[number];

export const dataAssetEvidenceFilterValues: readonly DataAssetEvidenceFilter[] =
  EVIDENCE_FILTER_VALUES;

function evidencePillClass(evidence: DataAssetEvidenceState): string {
  if (evidence === "sync_observed") {
    return "signal-ready";
  }
  if (evidence === "preview_only") {
    return "signal-watch";
  }
  return "status-checking";
}

/** Data asset list rail over the API's complete catalog contract. */
export function DataAssetList({
  assets,
  selectedAssetId,
  onSelect,
  search,
  onSearchChange,
  evidenceFilter,
  onEvidenceFilterChange,
}: {
  assets: DataAsset[];
  selectedAssetId: string;
  onSelect: (assetId: string) => void;
  search: string;
  onSearchChange: (value: string) => void;
  evidenceFilter: DataAssetEvidenceFilter;
  onEvidenceFilterChange: (value: DataAssetEvidenceFilter) => void;
}) {
  const copy = strings.dataCatalog;

  return (
    <Card className="grid content-start gap-4">
      <div className="grid gap-1">
        <Eyebrow>{copy.listTitle}</Eyebrow>
        <h2 className="font-display m-0 text-xl text-ink">
          {pluralize(assets.length, "asset")}
        </h2>
      </div>
      <div className="grid gap-2">
        <Input
          aria-label={copy.searchLabel}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={copy.searchPlaceholder}
          type="search"
          value={search}
        />
        <Select
          aria-label={copy.evidenceFilterLabel}
          onChange={(event) =>
            onEvidenceFilterChange(event.target.value as DataAssetEvidenceFilter)
          }
          value={evidenceFilter}
        >
          {EVIDENCE_FILTER_VALUES.map((value) => (
            <option key={value} value={value}>
              {value === "all" ? copy.evidence.all : copy.evidence[value]}
            </option>
          ))}
        </Select>
      </div>
      <div className="grid gap-2">
        {assets.map((asset) => {
          const isSelected = asset.asset_id === selectedAssetId;

          return (
            <button
              aria-pressed={isSelected}
              className={cn(
                "flex w-full cursor-pointer items-start justify-between gap-3 rounded-2xl border px-4 py-3 text-left transition-colors",
                isSelected
                  ? "border-signal/60 bg-tint-100 dark:bg-signal/15"
                  : "border-line bg-transparent hover:border-signal/40 hover:bg-tint-50 dark:border-white/10 dark:hover:bg-white/5",
              )}
              key={asset.asset_id}
              onClick={() => onSelect(asset.asset_id)}
              type="button"
            >
              <span className="grid min-w-0 gap-0.5">
                <span className="text-sm font-medium text-ink">{asset.display_name}</span>
                <span className="text-xs text-muted">{asset.connector_type}</span>
                <span className="text-xs text-muted">
                  {asset.last_successful_sync
                    ? `${asset.last_successful_sync.records_read} records · ${formatDateTime(
                        asset.last_successful_sync.completed_at,
                      )}`
                    : copy.governance[asset.governance]}
                </span>
              </span>
              <span className={`status-pill ${evidencePillClass(asset.evidence)}`}>
                {copy.evidence[asset.evidence]}
              </span>
            </button>
          );
        })}
      </div>
    </Card>
  );
}
