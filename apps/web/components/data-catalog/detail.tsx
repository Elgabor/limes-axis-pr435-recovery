"use client";

import { Card } from "@/components/ui/card";
import { DetailGrid, KeyValueRow } from "@/components/ui/detail-grid";
import { Eyebrow } from "@/components/ui/eyebrow";
import { EmptyPanel } from "@/components/ui/states";
import type { DataAsset } from "@/lib/data-assets";
import { formatDateTime } from "@/lib/format";
import { strings } from "@/lib/strings";

/** Data asset detail pane: metadata-only by contract, mirroring the API. */
export function DataAssetDetail({ asset }: { asset: DataAsset }) {
  const copy = strings.dataCatalog.detail;

  return (
    <Card className="grid content-start gap-4">
      <div className="grid gap-1">
        <Eyebrow>{asset.asset_id}</Eyebrow>
        <h2 className="font-display m-0 text-xl text-ink">{asset.display_name}</h2>
      </div>
      <DetailGrid>
        <KeyValueRow label={copy.assetId} mono>
          {asset.asset_id}
        </KeyValueRow>
        <KeyValueRow label={copy.connector} mono>
          {asset.connector_id}
        </KeyValueRow>
        <KeyValueRow label={copy.kind}>{asset.kind}</KeyValueRow>
        <KeyValueRow label={copy.evidence}>
          {strings.dataCatalog.evidence[asset.evidence]}
        </KeyValueRow>
        <KeyValueRow label={copy.governance}>
          {strings.dataCatalog.governance[asset.governance]}
        </KeyValueRow>
        <KeyValueRow label={copy.sourceType}>{asset.source_type}</KeyValueRow>
        <KeyValueRow label={copy.runtimeBoundary} mono>
          {asset.runtime_boundary}
        </KeyValueRow>
        <KeyValueRow label={copy.egressPolicy} mono>
          {asset.egress_policy}
        </KeyValueRow>
        <KeyValueRow label={copy.payloadPolicy} mono>
          {asset.payload_policy}
        </KeyValueRow>
        <KeyValueRow label={copy.syncModes}>
          {asset.sync_modes.length > 0 ? asset.sync_modes.join(", ") : "—"}
        </KeyValueRow>
        <KeyValueRow label={copy.lastSync}>
          {asset.last_successful_sync
            ? `${formatDateTime(asset.last_successful_sync.completed_at)} · ${
                asset.last_successful_sync.run_id
              }`
            : "—"}
        </KeyValueRow>
        <KeyValueRow label={copy.manifestRevision}>
          {asset.manifest_revision ?? "—"}
        </KeyValueRow>
        <KeyValueRow label={copy.registryOrigin}>{asset.registry_origin}</KeyValueRow>
      </DetailGrid>
      <div className="grid gap-2">
        <h3 className="m-0 text-sm font-medium text-ink">{copy.schemaTitle}</h3>
        {asset.schema_fields.length === 0 ? (
          <p className="m-0 text-xs text-muted">{copy.schemaEmpty}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-xs">
              <thead>
                <tr className="border-b border-line text-muted">
                  <th className="py-1.5 pr-3 font-medium" scope="col">
                    {copy.columns.source}
                  </th>
                  <th className="py-1.5 pr-3 font-medium" scope="col">
                    {copy.columns.target}
                  </th>
                  <th className="py-1.5 pr-3 font-medium" scope="col">
                    {copy.columns.ontology}
                  </th>
                  <th className="py-1.5 pr-3 font-medium" scope="col">
                    {copy.columns.type}
                  </th>
                  <th className="py-1.5 font-medium" scope="col">
                    {copy.columns.required}
                  </th>
                </tr>
              </thead>
              <tbody>
                {asset.schema_fields.map((field) => (
                  <tr className="border-b border-line/60" key={field.source_column}>
                    <td className="py-1.5 pr-3 font-mono text-ink">{field.source_column}</td>
                    <td className="py-1.5 pr-3 text-muted">{field.target_field}</td>
                    <td className="py-1.5 pr-3 text-muted">{field.ontology_target}</td>
                    <td className="py-1.5 pr-3 text-muted">{field.data_type}</td>
                    <td className="py-1.5 text-muted">{field.required ? "✓" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {asset.ontology_targets.length > 0 ? (
        <div className="grid gap-2">
          <h3 className="m-0 text-sm font-medium text-ink">{copy.ontologyTargets}</h3>
          <div className="flex flex-wrap gap-1.5">
            {asset.ontology_targets.map((target) => (
              <span
                className="rounded-full bg-tint-100 px-2.5 py-0.5 text-xs text-signal dark:bg-signal/15"
                key={target}
              >
                {target}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {asset.notes.length > 0 ? (
        <div className="grid gap-2">
          <h3 className="m-0 text-sm font-medium text-ink">{copy.notes}</h3>
          <ul className="m-0 grid list-disc gap-1 pl-4">
            {asset.notes.map((note) => (
              <li className="text-xs text-muted" key={note}>
                {note}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}

/** Fail-closed detail state for an asset ID that is not in the catalog. */
export function UnknownDataAssetPanel({ assetId }: { assetId: string }) {
  const copy = strings.dataCatalog.states.unknownAsset;

  return (
    <Card className="grid content-start gap-4">
      <EmptyPanel detail={copy.detail} title={copy.title} />
      <p className="m-0 font-mono text-xs break-all text-muted">{assetId}</p>
    </Card>
  );
}
