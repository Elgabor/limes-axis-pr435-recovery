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
import {
  formatConnectorLabel,
  type ConnectorEvidenceInvariantSnapshotRecord,
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
 * layout over the connector registry, and the Add Connector wizard. The
 * summary supplies the list and counters; selected details load on demand.
 * A failing counter or detail degrades its own section.
 */

function countOrPlaceholder(count: number | null | undefined): string | number {
  return count == null ? strings.connectors.metrics.unavailable : formatNumber(count);
}

function buildMetrics(
  registries: ConnectorRegistries,
): Metric[] {
  const copy = strings.connectors.metrics;
  const counts = registries.registry.data?.counts;
  const invariantCount = counts?.evidence_issues;

  return [
    {
      label: copy.connectors.label,
      value: countOrPlaceholder(registries.registry.data?.total_connectors),
      detail: copy.connectors.detail,
    },
    {
      label: copy.runs.label,
      value: countOrPlaceholder(counts?.runs),
      detail: copy.runs.detail,
    },
    {
      label: copy.pendingProposals.label,
      value: countOrPlaceholder(
        counts?.pending_proposals,
      ),
      detail: copy.pendingProposals.detail,
    },
    {
      label: copy.egressPolicies.label,
      value: countOrPlaceholder(counts?.egress_policies),
      detail: copy.egressPolicies.detail,
    },
    {
      label: copy.evidenceIssues.label,
      value: countOrPlaceholder(invariantCount),
      detail: copy.evidenceIssues.detail,
      ...(invariantCount != null
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
  offset: stringUrlField("offset", "0"),
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
  const scope = useConsoleTenantScope();
  // Cookie sessions have no browser token identity. Remount all workspace
  // queries and action drafts when the API-verified principal changes.
  const principalKey = JSON.stringify([
    scope.tenantId, scope.identity.data?.actor_id, scope.identity.data?.authenticated,
  ]);
  return <ConnectorWorkspace key={principalKey} scope={scope} />;
}

function ConnectorWorkspace({ scope }: { scope: ReturnType<typeof useConsoleTenantScope> }) {
  const { identity, tenantId, tenantQueriesEnabled } = scope;
  const [urlState, setUrlState] = useConsoleUrlState(connectorUrlSchema);
  const [wizardOpen, setWizardOpen] = useState(false);
  const requestedOffset = Number(urlState.offset);
  const offset = Number.isSafeInteger(requestedOffset)
    && requestedOffset >= 0 && requestedOffset <= 1_000_000 ? requestedOffset : 0;
  const registries = useConnectorRegistries(
    tenantId,
    tenantQueriesEnabled,
    urlState.snapshotId,
    urlState.connectorId,
    urlState.tab,
    offset,
    wizardOpen,
  );
  const { registry } = registries;
  const { triggerRefresh } = useConsole();
  const updatedAt = registry.data ? new Date(registry.data.generated_at) : null;

  const connectors = useMemo(() => registry.data?.connectors ?? [], [registry.data]);
  const requestedSnapshot = urlState.snapshotId
    ? registries.evidenceSnapshots.data?.snapshots.find(
        (snapshot) => snapshot.snapshot_id === urlState.snapshotId,
      ) ?? null
    : null;
  const requestedConnectorId = urlState.connectorId || requestedSnapshot?.connector_id || "";
  const selectedConnector = registries.detail.data?.connector;

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
        endpoint={CONNECTOR_ENDPOINTS.workspace}
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

  if (requestedConnectorId && registries.detail.errorStatus === 404) {
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
      connectors={registries.templates.data?.connectors ?? []}
      templatesLoading={registries.templates.source === "loading"}
      templatesUnavailable={registries.templates.source === "unavailable"}
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
        metrics={buildMetrics(registries)}
        label={strings.connectors.metrics.stripLabel}
      />

      <ManifestImportPanel
        identitySession={identitySession}
        onApplied={triggerRefresh}
        tenantId={tenantId}
      />

      {requestedSnapshot ? <SnapshotPanel snapshot={requestedSnapshot} /> : null}

      {registryData.total_connectors === 0 ? (
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
          detail={registries.detail.source === "unavailable" ? (
            <ErrorPanel
              title="Connector detail unavailable"
              detail="Refresh to load the selected connector again."
              endpoint={CONNECTOR_ENDPOINTS.detail}
              reference={registries.detail.errorRequestId ?? undefined}
            />
          ) : !selectedConnector ? (
            registries.selectedConnectorId ? <LoadingPanel layout="detail" /> : (
              <EmptyPanel title="Select a connector" detail="Choose a connector from the list." icon={Cable} />
            )
          ) : (
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
          )}
          list={
            <ConnectorList
              connectors={connectors}
              selectedConnectorId={registries.selectedConnectorId}
              totalConnectors={registryData.total_connectors}
              offset={registryData.offset}
              limit={registryData.limit}
              nextOffset={registryData.next_offset}
              onPageChange={(nextOffset) => setUrlState({
                offset: String(nextOffset), connectorId: "", snapshotId: "",
              })}
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
