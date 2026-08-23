"use client";

import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { DetailGrid, KeyValueRow } from "@/components/ui/detail-grid";
import { Eyebrow } from "@/components/ui/eyebrow";
import { InspectDrawer } from "@/components/ui/inspect-drawer";
import { ErrorPanel, LoadingPanel } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  formatConnectorLabel,
  type ConnectorManifestDetail,
  type ConnectorRegistryItem,
} from "@/lib/connectors-demo";
import { connectorWithCurrentManifest } from "@/lib/connectors-console";
import { strings } from "@/lib/strings";
import { formatNumber, formatTimestamp } from "@/lib/format";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { parseConnectorManifestDetail } from "@/lib/runtime-contracts/connectors";
import { buildTenantScopedPath } from "@/lib/tenant-scope";
import { useAxisQuery, type AxisQuerySource } from "@/lib/use-axis-query";
import type { ConnectorRegistries } from "@/lib/use-connector-registries";
import { CONNECTOR_ENDPOINTS } from "@/lib/use-connector-registries";
import { useConsole } from "@/providers/console-provider";

import { ConnectorGovernance } from "./governance";
import { ConnectorLifecyclePanel } from "./lifecycle-panel";
import { ConnectorRuns } from "./runs";
import { ConnectorSourceBindingsSection } from "./source-bindings-panel";
import { ConnectorSourceIngestionSection } from "./source-ingestion-panel";
import { ConnectorSourceDiscoveryPanel } from "./source-discovery-panel";
import { SourceJourneySpine } from "./source-journey";
import { ManifestExportPanel } from "./manifest-export-panel";

/*
 * Connector detail pane: Overview / Data & Schema / Runs / Governance &
 * Evidence tabs. The old ~40 invariant tiles compress into the governance tab
 * as DetailGrid sections with Inspect drawers.
 */

function ChipList({ items, emptyLabel }: { items: string[]; emptyLabel?: string }) {
  if (items.length === 0) {
    return <span className="text-sm text-muted">{emptyLabel ?? "None"}</span>;
  }

  return (
    <div className="flex min-w-0 flex-wrap gap-2">
      {items.map((item) => (
        <span
          className="inline-flex max-w-full min-w-0 items-center rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs break-words text-muted dark:border-white/15 dark:bg-transparent"
          key={item}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function OverviewTab({
  connector,
  identitySession,
  manifestDetail,
  manifestDetailErrorRequestId,
  manifestDetailPath,
  manifestDetailSource,
  onTransitioned,
  registries,
  tenantId,
}: {
  connector: ConnectorRegistryItem;
  identitySession: IdentitySessionReadModel | null;
  manifestDetail: ConnectorManifestDetail | null;
  manifestDetailErrorRequestId: string | null;
  manifestDetailPath: string;
  manifestDetailSource: AxisQuerySource;
  onTransitioned: () => void;
  registries: ConnectorRegistries;
  tenantId: string;
}) {
  const copy = strings.connectors.overview;
  const { manifest, runtime_policy: runtimePolicy } = connector;
  const persistedManifest = connector.persisted_manifest;
  const currentManifest = manifestDetail?.current_revision ?? null;

  return (
    <div className="grid content-start gap-5">
      <DetailGrid>
        <KeyValueRow label={copy.type}>
          {formatConnectorLabel(manifest.connector_type)}
        </KeyValueRow>
        <KeyValueRow label={copy.version}>{manifest.version}</KeyValueRow>
        <KeyValueRow label={copy.source}>
          {formatConnectorLabel(manifest.source_type)}
        </KeyValueRow>
        <KeyValueRow label={copy.syncModes}>
          {manifest.sync_modes.map(formatConnectorLabel).join(", ")}
        </KeyValueRow>
        <KeyValueRow label={copy.boundary}>
          {formatConnectorLabel(manifest.runtime_boundary)}
        </KeyValueRow>
        <KeyValueRow label={copy.credentials}>
          {formatConnectorLabel(manifest.credential_requirements.storage)}
        </KeyValueRow>
        <KeyValueRow label={copy.payloadPolicy}>
          {formatConnectorLabel(runtimePolicy.payload_policy)}
        </KeyValueRow>
        <KeyValueRow label={copy.egressPolicy} mono>
          {runtimePolicy.egress_policy}
        </KeyValueRow>
      </DetailGrid>

      {persistedManifest ? (
        <ConnectorLifecyclePanel
          connector={connector}
          identitySession={identitySession}
          onTransitioned={onTransitioned}
          revisions={manifestDetail?.revisions}
          transitions={manifestDetail?.transitions}
          tenantId={tenantId}
        />
      ) : null}

      {/* Real source operations exist only for the external database connector;
          other connectors have no source boundary to verify or discover. */}
      {connector.manifest.connector_type === "external_db" ? (
        <>
          <SourceJourneySpine
            connectorId={connector.manifest.connector_id}
            tenantId={tenantId}
          />
          <ConnectorSourceDiscoveryPanel
            connector={connector}
            identitySession={identitySession}
            registries={registries}
            tenantId={tenantId}
          />
          <ConnectorSourceBindingsSection
            connectorId={connector.manifest.connector_id}
            tenantId={tenantId}
          />
          <ConnectorSourceIngestionSection
            connectorId={connector.manifest.connector_id}
            identitySession={identitySession}
            tenantId={tenantId}
          />
        </>
      ) : null}

      <div className="grid gap-3">
        <div className="grid gap-2">
          <Eyebrow>{copy.permissions}</Eyebrow>
          <ChipList items={manifest.required_permissions} />
        </div>
        <div className="grid gap-2">
          <Eyebrow>{copy.blocked}</Eyebrow>
          <ChipList items={runtimePolicy.blocked_operations} />
        </div>
      </div>

      <div className="grid gap-2 border-t border-line/60 pt-4 dark:border-white/10">
        <Eyebrow>{copy.manifest}</Eyebrow>
        {persistedManifest ? (
          <div className="grid gap-4">
            <DetailGrid>
              <KeyValueRow label={copy.manifestStatus}>
                {formatConnectorLabel(currentManifest?.status ?? persistedManifest.status)}
              </KeyValueRow>
              <KeyValueRow label={copy.manifestRegisteredBy}>
                {currentManifest?.registered_by ?? persistedManifest.registered_by}
              </KeyValueRow>
              <KeyValueRow label={copy.currentRevision}>
                {formatNumber(
                  currentManifest?.revision_number ?? persistedManifest.revision_number,
                )}
              </KeyValueRow>
            </DetailGrid>
            {manifestDetailSource === "loading" ? <LoadingPanel rows={2} /> : null}
            {manifestDetailSource === "unavailable" ? (
              <ErrorPanel
                detail={copy.revisionHistoryUnavailableDetail}
                endpoint={manifestDetailPath}
                reference={manifestDetailErrorRequestId ?? undefined}
                title={copy.revisionHistoryUnavailable}
              />
            ) : null}
            {manifestDetail ? (
              <section className="grid gap-2">
                <div className="grid gap-1">
                  <Eyebrow>{copy.revisionHistory}</Eyebrow>
                  <p className="m-0 text-sm text-muted">{copy.revisionHistoryDetail}</p>
                </div>
                <DataTable aria-label={copy.revisionHistory} minWidth={680}>
                  <thead>
                    <tr>
                      <th>{copy.revisionColumns.revision}</th>
                      <th>{copy.revisionColumns.version}</th>
                      <th>{copy.revisionColumns.status}</th>
                      <th>{copy.revisionColumns.registeredBy}</th>
                      <th>{copy.revisionColumns.createdAt}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {manifestDetail.revisions.map((revision) => (
                      <tr key={revision.revision_number}>
                        <td>{formatNumber(revision.revision_number)}</td>
                        <td className="font-mono text-xs">{revision.version}</td>
                        <td>{formatConnectorLabel(revision.status)}</td>
                        <td>{revision.registered_by}</td>
                        <td>{formatTimestamp(revision.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </DataTable>
              </section>
            ) : null}
          </div>
        ) : (
          <p className="m-0 text-sm text-muted">{copy.manifestMissing}</p>
        )}
      </div>
    </div>
  );
}

function DataSchemaTab({ connector }: { connector: ConnectorRegistryItem }) {
  const copy = strings.connectors.schema;
  const { schema_fields: schemaFields } = connector.manifest;
  const sample = connector.preview_sample;

  return (
    <div className="grid content-start gap-5">
      <section className="grid gap-2">
        <div className="grid gap-1">
          <Eyebrow>{copy.mappingTitle}</Eyebrow>
          <p className="m-0 text-sm text-muted">{copy.mappingDetail}</p>
        </div>
        <DataTable aria-label={copy.mappingTitle} minWidth={520}>
          <thead>
            <tr>
              <th>{copy.columns.source}</th>
              <th>{copy.columns.target}</th>
              <th>{copy.columns.ontology}</th>
              <th>{copy.columns.type}</th>
              <th>{copy.columns.required}</th>
            </tr>
          </thead>
          <tbody>
            {schemaFields.map((field) => (
              <tr key={field.source_column}>
                <td className="font-mono text-xs">{field.source_column}</td>
                <td className="font-mono text-xs">{field.target_field}</td>
                <td className="font-mono text-xs">{field.ontology_target}</td>
                <td className="text-xs text-muted">{field.data_type}</td>
                <td className="text-xs text-muted">
                  {field.required ? copy.requiredYes : copy.requiredNo}
                </td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      </section>

      <section className="grid gap-2">
        <div className="grid gap-1">
          <Eyebrow>{copy.sampleTitle}</Eyebrow>
          {sample ? (
            <p className="m-0 text-sm text-muted">
              {copy.sampleDetail}{" "}
              <span className="font-mono text-xs">{sample.file_name}</span>
            </p>
          ) : (
            <p className="m-0 text-sm text-muted">{copy.neverSampled}</p>
          )}
        </div>
        {!sample ? null : sample.sample_rows.length === 0 ? (
          <p className="m-0 text-sm text-muted">{copy.sampleEmpty}</p>
        ) : (
          <DataTable aria-label={copy.sampleTitle} minWidth={420}>
            <thead>
              <tr>
                {sample.headers.map((header) => (
                  <th key={header}>{header}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sample.sample_rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {sample.headers.map((header) => (
                    <td className="text-xs" key={header}>
                      {row[header] ?? ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </section>
    </div>
  );
}

export function ConnectorDetail({
  activeTab,
  connector,
  identitySession,
  onTabChange,
  registries,
  tenantId,
}: {
  activeTab: ConnectorDetailTab;
  connector: ConnectorRegistryItem;
  identitySession: IdentitySessionReadModel | null;
  onTabChange: (tab: ConnectorDetailTab) => void;
  registries: ConnectorRegistries;
  tenantId: string;
}) {
  const tabs = strings.connectors.tabs;
  const { manifest } = connector;
  const { triggerRefresh } = useConsole();
  const manifestDetailPath = buildTenantScopedPath(
    `${CONNECTOR_ENDPOINTS.manifests}/${encodeURIComponent(manifest.connector_id)}`,
    tenantId,
  );
  const manifestDetail = useAxisQuery<ConnectorManifestDetail>(manifestDetailPath, {
    enabled: connector.persisted_manifest !== null,
    expectedTenantId: tenantId,
    parse: (value) => {
      const detail = parseConnectorManifestDetail(value);
      if (detail.connector_id !== manifest.connector_id) {
        throw new Error("Connector manifest detail response does not match the selected connector.");
      }
      return detail;
    },
  });
  const effectiveConnector = connectorWithCurrentManifest(
    connector,
    manifestDetail.data,
  );
  const effectiveManifest = effectiveConnector.manifest;

  return (
    <Card className="grid content-start gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid max-w-xl gap-1">
          <Eyebrow>{formatConnectorLabel(effectiveManifest.connector_type)}</Eyebrow>
          <h2 className="font-display m-0 text-xl text-ink">
            {effectiveManifest.display_name}
          </h2>
          <p className="m-0 font-mono text-xs break-words text-muted">
            {effectiveManifest.connector_id}
          </p>
        </div>
        <InspectDrawer record={effectiveConnector} title={effectiveManifest.display_name} />
        <ManifestExportPanel connector={effectiveConnector} />
      </div>

      <Tabs value={activeTab} onValueChange={(value) => {
        if (isConnectorDetailTab(value)) {
          onTabChange(value);
        }
      }}>
        <TabsList>
          <TabsTrigger value="overview">{tabs.overview}</TabsTrigger>
          <TabsTrigger value="schema">{tabs.dataSchema}</TabsTrigger>
          <TabsTrigger value="runs">{tabs.runs}</TabsTrigger>
          <TabsTrigger value="governance">{tabs.governance}</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <OverviewTab
            connector={effectiveConnector}
            identitySession={identitySession}
            manifestDetail={manifestDetail.data}
            manifestDetailErrorRequestId={manifestDetail.errorRequestId}
            manifestDetailPath={manifestDetailPath}
            manifestDetailSource={manifestDetail.source}
            onTransitioned={triggerRefresh}
            registries={registries}
            tenantId={tenantId}
          />
        </TabsContent>
        <TabsContent value="schema">
          <DataSchemaTab connector={effectiveConnector} />
        </TabsContent>
        <TabsContent value="runs">
          <ConnectorRuns
            connector={effectiveConnector}
            identitySession={identitySession}
            registries={registries}
            tenantId={tenantId}
          />
        </TabsContent>
        <TabsContent value="governance">
          <ConnectorGovernance
            connectorId={effectiveManifest.connector_id}
            registries={registries}
          />
        </TabsContent>
      </Tabs>
    </Card>
  );
}

export const connectorDetailTabs = ["overview", "schema", "runs", "governance"] as const;
export type ConnectorDetailTab = typeof connectorDetailTabs[number];

function isConnectorDetailTab(value: string): value is ConnectorDetailTab {
  return connectorDetailTabs.some((tab) => tab === value);
}
