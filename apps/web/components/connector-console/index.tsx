"use client";

import { useMemo, useState } from "react";
import { Cable, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DetailGrid, KeyValueRow } from "@/components/ui/detail-grid";
import { Eyebrow } from "@/components/ui/eyebrow";
import { InspectDrawer } from "@/components/ui/inspect-drawer";
import { MasterDetail } from "@/components/ui/master-detail";
import { MetricStrip, type Metric } from "@/components/ui/metric-strip";
import { SourcePill } from "@/components/ui/source-pill";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/ui/states";
import { pendingProposalCount } from "@/lib/connectors-console";
import {
  formatConnectorLabel,
  type ConnectorEvidenceInvariantSnapshotRecord,
  type ConnectorRegistryItem,
} from "@/lib/connectors-demo";
import {
  enumUrlField,
  stringUrlField,
  useConsoleUrlState,
} from "@/lib/console-url-state";
import { formatContextPath, formatNumber } from "@/lib/format";
import { platformStatusClass, platformStatusLabel } from "@/lib/platform-overview";
import { deriveSourceState } from "@/lib/source-state";
import { strings } from "@/lib/strings";
import {
  IDENTITY_SESSION_ENDPOINT,
  useConsoleTenantScope,
} from "@/lib/use-console-tenant-scope";
import {
  CONNECTOR_ENDPOINTS,
  useConnectorRegistries,
  type ConnectorRegistries,
} from "@/lib/use-connector-registries";
import { useConsole } from "@/providers/console-provider";

import { AddConnectorWizard } from "./add-connector-wizard";
import {
  ConnectorDetail,
  connectorDetailTabs,
  type ConnectorDetailTab,
} from "./detail";
import { ConnectorList } from "./list";
import { ManifestImportPanel } from "./manifest-import-panel";

/*
 * Connector console orchestrator: five user-relevant metrics, a master/detail
 * layout over the connector registry, and the Add Connector wizard. Each
 * registry endpoint loads independently — a failing side registry degrades its
 * own section instead of blanking the page.
 */

function countOrPlaceholder(count: number | undefined): string | number {
  return count === undefined ? strings.connectors.metrics.unavailable : formatNumber(count);
}

function buildMetrics(
  registries: ConnectorRegistries,
  connectors: ConnectorRegistryItem[],
): Metric[] {
  const copy = strings.connectors.metrics;
  const invariantCount = registries.evidenceInvariants.data?.invariants.length;

  return [
    {
      label: copy.connectors.label,
      value: countOrPlaceholder(registries.registry.data ? connectors.length : undefined),
      detail: copy.connectors.detail,
    },
    {
      label: copy.runs.label,
      value: countOrPlaceholder(registries.runs.data?.runs.length),
      detail: copy.runs.detail,
    },
    {
      label: copy.pendingProposals.label,
      value: countOrPlaceholder(
        registries.ontologyProposals.data
          ? pendingProposalCount(registries.ontologyProposals.data.proposals)
          : undefined,
      ),
      detail: copy.pendingProposals.detail,
    },
    {
      label: copy.egressPolicies.label,
      value: countOrPlaceholder(registries.egressPolicies.data?.policies.length),
      detail: copy.egressPolicies.detail,
    },
    {
      label: copy.evidenceIssues.label,
      value: countOrPlaceholder(invariantCount),
      detail: copy.evidenceIssues.detail,
      ...(invariantCount !== undefined
        ? { tone: invariantCount > 0 ? ("action" as const) : ("ready" as const) }
        : {}),
    },
  ];
}

function formatUpdatedAt(updatedAt: Date): string {
  return new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(updatedAt);
}

const connectorUrlSchema = {
  connectorId: stringUrlField("connector_id"),
  snapshotId: stringUrlField("snapshot_id"),
  tab: enumUrlField("tab", connectorDetailTabs, "overview"),
};

function SnapshotPanel({ snapshot }: { snapshot: ConnectorEvidenceInvariantSnapshotRecord }) {
  const copy = strings.connectors.snapshot;

  return (
    <Card className="grid content-start gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <Eyebrow>{copy.eyebrow}</Eyebrow>
          <h2 className="font-display m-0 text-xl text-ink">{copy.title}</h2>
        </div>
        <InspectDrawer record={snapshot} title={copy.inspect} />
      </div>
      <DetailGrid>
        <KeyValueRow label={copy.id} mono>{snapshot.snapshot_id}</KeyValueRow>
        <KeyValueRow label={copy.connector} mono>
          {snapshot.connector_id ?? strings.connectors.metrics.unavailable}
        </KeyValueRow>
        <KeyValueRow label={copy.findings}>{formatNumber(snapshot.invariant_count)}</KeyValueRow>
        <KeyValueRow label={copy.reason}>{snapshot.reason}</KeyValueRow>
        <KeyValueRow label={copy.digest} mono>{snapshot.report_digest_sha256}</KeyValueRow>
      </DetailGrid>
      <span className={`status-pill ${platformStatusClass(
        snapshot.permission_decision.allowed ? "ready" : "action_required",
      )}`}>
        {formatConnectorLabel(snapshot.status)}
      </span>
    </Card>
  );
}

export function ConnectorConsole() {
  const { identity, tenantId, tenantQueriesEnabled } = useConsoleTenantScope();
  const [urlState, setUrlState] = useConsoleUrlState(connectorUrlSchema);
  const registries = useConnectorRegistries(
    tenantId,
    tenantQueriesEnabled,
    urlState.snapshotId,
    urlState.connectorId,
  );
  const { registry } = registries;
  const { triggerRefresh } = useConsole();
  const [wizardOpen, setWizardOpen] = useState(false);
  // Real fetch time (no hardcoded timestamps): stamped when a new registry
  // payload arrives, using the render-time state-adjustment pattern.
  const [fetchStamp, setFetchStamp] = useState<{ payload: unknown; at: Date } | null>(null);
  if (registry.data && fetchStamp?.payload !== registry.data) {
    setFetchStamp({ payload: registry.data, at: new Date() });
  }
  const updatedAt = fetchStamp?.at ?? null;

  const connectors = useMemo(() => registry.data?.connectors ?? [], [registry.data]);
  const requestedSnapshot = urlState.snapshotId
    ? registries.evidenceSnapshots.data?.snapshots.find(
        (snapshot) => snapshot.snapshot_id === urlState.snapshotId,
      ) ?? null
    : null;
  const requestedConnectorId = urlState.connectorId || requestedSnapshot?.connector_id || "";
  const selectedConnector = requestedConnectorId
    ? connectors.find(
        (connector) => connector.manifest.connector_id === requestedConnectorId,
      )
    : connectors[0];

  if (!tenantQueriesEnabled || tenantId === null) {
    if (identity.source === "loading") {
      return (
        <div aria-label="Loading connector identity" className="grid gap-4">
          <LoadingPanel layout="metrics" rows={5} />
          <MasterDetail detail={<LoadingPanel layout="detail" />} list={<LoadingPanel rows={4} />} />
        </div>
      );
    }

    return (
      <ErrorPanel
        detail="The connector console is disabled because the current tenant could not be verified."
        endpoint={IDENTITY_SESSION_ENDPOINT}
        reference={identity.errorRequestId ?? undefined}
        title="Tenant identity unavailable"
      />
    );
  }

  if (!registry.data) {
    if (registry.source === "loading") {
      return (
        <div aria-label="Loading connector API" className="grid gap-4">
          <LoadingPanel layout="metrics" rows={5} />
          <MasterDetail detail={<LoadingPanel layout="detail" />} list={<LoadingPanel rows={4} />} />
        </div>
      );
    }

    return (
      <ErrorPanel
        detail={strings.connectors.error.detail}
        endpoint={CONNECTOR_ENDPOINTS.registry}
        reference={registry.errorRequestId ?? undefined}
        title={strings.connectors.error.title}
      />
    );
  }

  if (urlState.snapshotId && !requestedSnapshot) {
    if (registries.evidenceSnapshots.source === "loading") {
      return <LoadingPanel layout="detail" />;
    }
    if (registries.evidenceSnapshots.source === "unavailable") {
      return (
        <ErrorPanel
          detail={strings.connectors.snapshot.errorDetail}
          endpoint={CONNECTOR_ENDPOINTS.evidenceSnapshots}
          reference={registries.evidenceSnapshots.errorRequestId ?? undefined}
          title={strings.connectors.snapshot.errorTitle}
        />
      );
    }
    return (
      <EmptyPanel
        detail={strings.connectors.snapshot.missingDetail}
        icon={Cable}
        title={strings.connectors.snapshot.missingTitle}
      />
    );
  }

  if (requestedConnectorId && !selectedConnector) {
    return (
      <EmptyPanel
        detail={strings.connectors.requestedMissing.detail}
        icon={Cable}
        title={strings.connectors.requestedMissing.title}
      />
    );
  }

  const registryData = registry.data;
  const identitySession = identity.data;
  const wizard = (
    <AddConnectorWizard
      connectors={connectors}
      identitySession={identitySession}
      open={wizardOpen}
      onCreated={triggerRefresh}
      onOpenChange={setWizardOpen}
      tenantId={tenantId}
    />
  );

  return (
    <div className="grid gap-4">
      <div
        aria-label="Connector source and status"
        className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2"
      >
        <p className="m-0 min-w-0 text-sm break-words text-muted">
          {formatContextPath(
            registryData.plant_name,
            registryData.scenario,
            registryData.tenant_id,
          )}
        </p>
        <div className="flex min-w-0 flex-wrap items-center gap-2.5">
          <SourcePill
            state={deriveSourceState(
              registry.source,
              Boolean(registry.data),
              registryData.provenance,
            )}
            subject="connector registry"
          />
          <span className={`status-pill ${platformStatusClass(registryData.registry_status)}`}>
            <Cable size={15} />
            {platformStatusLabel(registryData.registry_status)}
          </span>
          {updatedAt ? (
            <span className="font-mono text-xs text-muted">
              {strings.connectors.header.updated} {formatUpdatedAt(updatedAt)}
            </span>
          ) : null}
          <Button
            className="px-4 py-2 text-sm"
            onClick={() => setWizardOpen(true)}
          >
            <Plus aria-hidden="true" size={15} />
            {strings.connectors.header.addConnector}
          </Button>
        </div>
      </div>

      <MetricStrip
        metrics={buildMetrics(registries, connectors)}
        label={strings.connectors.metrics.stripLabel}
      />

      <ManifestImportPanel
        identitySession={identitySession}
        onApplied={triggerRefresh}
        tenantId={tenantId}
      />

      {requestedSnapshot ? <SnapshotPanel snapshot={requestedSnapshot} /> : null}

      {connectors.length === 0 || !selectedConnector ? (
        <EmptyPanel
          action={{
            label: strings.connectors.empty.action,
            onClick: () => setWizardOpen(true),
          }}
          detail={strings.connectors.empty.detail}
          icon={Cable}
          title={strings.connectors.empty.title}
        />
      ) : (
        <MasterDetail
          detail={
            <ConnectorDetail
              activeTab={
                requestedSnapshot && urlState.tab === "overview"
                  ? "governance"
                  : urlState.tab
              }
              // Remounts the whole detail pane (and its nested action state —
              // ConnectorRuns' validating/validateOutcome/stepper/syncRunning)
              // when the selected connector changes. Without this key, Radix
              // Tabs is uncontrolled and that state is component state, so
              // switching connectors mid-validation showed the previous
              // connector's "Validation passed" result under the new one.
              key={selectedConnector.manifest.connector_id}
              connector={selectedConnector}
              identitySession={identitySession}
              onTabChange={(tab: ConnectorDetailTab) => setUrlState({ tab })}
              registries={registries}
              tenantId={tenantId}
            />
          }
          list={
            <ConnectorList
              connectors={connectors}
              selectedConnectorId={selectedConnector.manifest.connector_id}
              onSelect={(connectorId) => setUrlState({
                connectorId,
                snapshotId: "",
              })}
            />
          }
        />
      )}

      {wizard}
    </div>
  );
}
