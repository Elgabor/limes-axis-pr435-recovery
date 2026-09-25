"use client";

import { useCallback, useMemo, useRef, useSyncExternalStore } from "react";
import { Database, List, Share2, ShieldCheck } from "lucide-react";

import { ErrorPanel } from "@/components/ui/states";
import { OntologyEntitySheet } from "@/components/ontology/entity-sheet";
import { useOntologyEntityHistory } from "@/components/ontology/use-ontology-entity-history";
import { OntologyGraph } from "@/components/ontology-graph";
import { Disclosure } from "@/components/ui/disclosure";
import { PlatformStatusPill } from "@/components/status-pill";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { SourcePill } from "@/components/ui/source-pill";
import {
  countNodesByType,
  formatNodeType,
  nodeLabelById,
  type ManufacturingOntology,
  type OntologyNodeType,
} from "@/lib/ontology-demo";
import { formatContextPath, formatNumber } from "@/lib/format";
import {
  enumUrlField,
  opaqueStringUrlField,
  useConsoleUrlState,
} from "@/lib/console-url-state";
import { deriveSourceState } from "@/lib/source-state";
import { strings } from "@/lib/strings";
import { parseManufacturingOntology } from "@/lib/runtime-contracts/ontology";
import {
  buildTenantScopedPath,
  DEMO_TENANT_ID,
  OPERATIONS_API_PREFIX,
} from "@/lib/tenant-scope";
import { useAxisQuery } from "@/lib/use-axis-query";
import {
  IDENTITY_SESSION_ENDPOINT,
  useConsoleTenantScope,
} from "@/lib/use-console-tenant-scope";

type OntologyView = "graph" | "list";

const ontologyViews = ["auto", "graph", "list"] as const;
const ontologyUrlSchema = {
  entityId: opaqueStringUrlField("entity_id"),
  view: enumUrlField("view", ontologyViews, "auto"),
};

function subscribeToViewport(onChange: () => void) {
  window.addEventListener("resize", onChange);
  return () => window.removeEventListener("resize", onChange);
}

function narrowViewport() { return window.innerWidth < 640; }
function serverViewport() { return false; }

function OntologyExplorerSkeleton() {
  return (
    <div className="grid gap-5" aria-busy="true" aria-label="Loading ontology API">
      <Skeleton className="h-28" />
      <Skeleton className="h-[420px]" />
    </div>
  );
}

export function OntologyExplorer() {
  const { identity, tenantId, tenantQueriesEnabled } = useConsoleTenantScope();
  const ontologyPath = buildTenantScopedPath(
    `${OPERATIONS_API_PREFIX}/ontology`,
    tenantId ?? DEMO_TENANT_ID,
  );
  const {
    data: ontology,
    errorRequestId: ontologyErrorRequestId,
    source,
  } = useAxisQuery<ManufacturingOntology>(ontologyPath, {
    enabled: tenantQueriesEnabled,
    expectedTenantId: tenantId ?? undefined,
    parse: parseManufacturingOntology,
  });
  const [urlState, setUrlState] = useConsoleUrlState(ontologyUrlSchema);
  const narrow = useSyncExternalStore(subscribeToViewport, narrowViewport, serverViewport);
  const view: OntologyView = urlState.view === "auto" ? (narrow ? "list" : "graph") : urlState.view;
  const selectedNodeId = urlState.entityId || null;
  const entityTriggerRef = useRef<HTMLElement | SVGElement | null>(null);
  const explorerHeadingRef = useRef<HTMLHeadingElement>(null);
  const updateEntityId = useCallback(
    (entityId: string, history: "push" | "replace") => {
      setUrlState({ entityId }, { history });
    },
    [setUrlState],
  );
  const { closeEntity, navigateToEntity } = useOntologyEntityHistory({
    entityId: selectedNodeId,
    updateEntityId,
  });

  function activateEntity(nodeId: string, trigger: HTMLElement | SVGElement) {
    entityTriggerRef.current = trigger;
    navigateToEntity(nodeId);
  }

  function restoreEntityFocus(event: Event) {
    event.preventDefault();
    const fallback = explorerHeadingRef.current;
    // Route unmounts must leave focus management to the destination page.
    if (!fallback?.isConnected) return;

    const trigger = entityTriggerRef.current;
    if (trigger?.isConnected) {
      trigger.focus();
      if (trigger.ownerDocument.activeElement === trigger) return;
    }
    fallback.focus();
  }

  const nodeLabels = useMemo(
    () => (ontology ? nodeLabelById(ontology) : new Map<string, string>()),
    [ontology],
  );
  const nodeTypeCounts = useMemo(
    () => (ontology ? countNodesByType(ontology) : new Map<OntologyNodeType, number>()),
    [ontology],
  );

  if (identity.source === "loading") {
    return <OntologyExplorerSkeleton />;
  }

  if (identity.source === "unavailable") {
    return (
      <ErrorPanel
        detail="The ontology is not loaded until the current actor and tenant are verified."
        endpoint={IDENTITY_SESSION_ENDPOINT}
        reference={identity.errorRequestId ?? undefined}
        title="Identity API unavailable"
      />
    );
  }

  if (!tenantId) {
    return (
      <ErrorPanel
        detail="The authenticated identity response does not contain a tenant. Axis will not fall back to the demo ontology."
        endpoint={IDENTITY_SESSION_ENDPOINT}
        title="Authenticated tenant missing"
      />
    );
  }

  if (!ontology) {
    if (source === "loading") {
      return <OntologyExplorerSkeleton />;
    }

    return (
      <ErrorPanel
        detail="Axis did not receive API-backed ontology records. Local fallback ontology records are disabled."
        endpoint={ontologyPath}
        reference={ontologyErrorRequestId ?? undefined}
        title="Ontology API unavailable"
      />
    );
  }

  return (
    <div className="grid gap-5">
      <div
        aria-label="Ontology source"
        className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2"
      >
        <p className="m-0 min-w-0 text-sm break-words text-muted">
          {formatContextPath(ontology.plant_name, ontology.scenario, ontology.tenant_id)}
        </p>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <SourcePill
            state={deriveSourceState(source, Boolean(ontology), ontology.provenance)}
            subject="ontology"
          />
          <span className="font-mono text-xs text-muted">{formatNumber(ontology.nodes.length)} nodes</span>
          <span className="font-mono text-xs text-muted">
            {formatNumber(ontology.relationships.length)} relationships
          </span>
        </div>
      </div>

      <Card className="grid gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="grid gap-1">
            <h2 ref={explorerHeadingRef} tabIndex={-1} className="font-display m-0 text-xl text-ink">{strings.clarity.ontologyObjects}</h2>
          </div>
          <div className="flex gap-2" role="group" aria-label="Ontology view">
            <Button
              aria-pressed={view === "graph"}
              className="px-4 py-2 text-sm"
              onClick={() => setUrlState({ view: "graph" })}
              variant={view === "graph" ? "primary" : "secondary"}
            >
              <Share2 size={15} />
              Graph
            </Button>
            <Button
              aria-pressed={view === "list"}
              className="px-4 py-2 text-sm"
              onClick={() => setUrlState({ view: "list" })}
              variant={view === "list" ? "primary" : "secondary"}
            >
              <List size={15} />
              List
            </Button>
          </div>
        </div>
        <div aria-hidden="true" className="rule-hairline" />

        {view === "graph" ? (
          <div className="grid gap-3">
            <OntologyGraph
              nodes={ontology.nodes}
              relationships={ontology.relationships}
              selectedNodeId={selectedNodeId ?? undefined}
              onNodeActivate={activateEntity}
            />
            <div
              className="flex flex-wrap items-center gap-x-4 gap-y-2 font-mono text-[11px] tracking-[0.14em] text-muted uppercase"
              aria-label={strings.ontology.legend.label}
            >
              <span className="inline-flex items-center gap-2">
                <span aria-hidden="true" className="inline-block size-2 rotate-45 bg-ink" />
                {strings.ontology.legend.entity}
              </span>
              <span className="inline-flex items-center gap-2">
                <span aria-hidden="true" className="inline-block size-2 rotate-45 bg-signal" />
                {strings.ontology.legend.selected}
              </span>
              <span className="inline-flex items-center gap-2">
                <span aria-hidden="true" className="inline-block h-px w-5 bg-signal/60" />
                {strings.ontology.legend.relation}
              </span>
              {Array.from(nodeTypeCounts.entries()).map(([type, count]) => (
                <span key={type}>{`${formatNodeType(type)} ×${count}`}</span>
              ))}
              <span className="normal-case">{strings.ontology.legend.hint}</span>
            </div>
          </div>
        ) : (
          <div className="grid gap-4">
            <div className="grid gap-2 sm:hidden" aria-label={strings.clarity.businessObjects}>
              {ontology.nodes.map((node) => (
                <button key={node.node_id} type="button" onClick={(event) => activateEntity(node.node_id, event.currentTarget)}
                  className="grid min-w-0 justify-items-start gap-2 rounded-xl border border-line p-3 text-left dark:border-white/10">
                  <span className="font-medium text-ink">{node.label}</span>
                  <span className="text-xs text-muted">{formatNodeType(node.node_type)} · {node.domain}</span>
                  <span className="text-sm text-muted">{node.summary}</span>
                  <PlatformStatusPill status={node.status} />
                </button>
              ))}
            </div>
            <div className="hidden min-w-0 sm:grid sm:gap-4">
            <DataTable aria-label="Ontology nodes">
              <thead>
                <tr>
                  <th>Node</th>
                  <th>Type</th>
                  <th>Domain</th>
                  <th>Source</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {ontology.nodes.map((node) => (
                  <tr key={node.node_id}>
                    <td>
                      <button
                        className="cursor-pointer border-0 bg-transparent p-0 text-left font-medium text-signal hover:underline"
                        onClick={(event) => activateEntity(node.node_id, event.currentTarget)}
                        type="button"
                      >
                        {node.label}
                      </button>
                      <p className="m-0 mt-1 text-xs text-muted">{node.summary}</p>
                    </td>
                    <td>{formatNodeType(node.node_type)}</td>
                    <td>{node.domain}</td>
                    <td>{node.source_system}</td>
                    <td>
                      <PlatformStatusPill status={node.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </DataTable>

            </div>
            <Disclosure title={strings.clarity.relationships}>
            <DataTable aria-label="Ontology relationships">
              <thead>
                <tr>
                  <th>Relationship</th>
                  <th>From</th>
                  <th>To</th>
                  <th>Permission</th>
                  <th>Owner</th>
                </tr>
              </thead>
              <tbody>
                {ontology.relationships.map((relationship) => (
                  <tr key={relationship.relationship_id}>
                    <td>
                      <strong>{relationship.relation_type}</strong>
                      <p className="m-0 mt-1 text-xs text-muted">{relationship.summary}</p>
                    </td>
                    <td>{nodeLabels.get(relationship.source_id)}</td>
                    <td>{nodeLabels.get(relationship.target_id)}</td>
                    <td>
                      <span className="font-mono text-xs">{relationship.permission_scope}</span>
                      <p className="m-0 mt-1 text-xs text-muted">
                        {Math.round(relationship.metadata.confidence * 100)}% confidence
                      </p>
                    </td>
                    <td>
                      {relationship.metadata.owner_role}
                      <p className="m-0 mt-1 font-mono text-xs text-muted">
                        {relationship.metadata.verification_status} /{" "}
                        {relationship.metadata.last_verified_at}
                      </p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
            </Disclosure>
          </div>
        )}
      </Card>

      <Disclosure title={strings.clarity.ontologySources}>
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="grid content-start gap-3">
            <Eyebrow>Source Systems</Eyebrow>
            <h2 className="font-display m-0 text-xl text-ink">Connected context</h2>
            <div className="flex flex-wrap gap-2">
              {ontology.source_systems.map((system) => (
                <span
                  className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1 font-mono text-xs text-muted dark:border-white/15"
                  key={system}
                >
                  <Database size={13} />
                  {system}
                </span>
              ))}
            </div>
          </Card>

          <Card className="grid content-start gap-3">
            <Eyebrow>Graph Query</Eyebrow>
            <h2 className="font-display m-0 text-xl text-ink">{ontology.graph_query.adapter}</h2>
            <div className="flex flex-wrap gap-2" aria-label="Ontology graph query metadata">
              <span className="status-pill signal-ready">
                <ShieldCheck size={15} />
                {ontology.graph_query.query_mode}
              </span>
              <span className="font-mono text-xs text-muted">{ontology.graph_query.source}</span>
              <span className="font-mono text-xs text-muted">
                {formatNumber(ontology.graph_query.denied_relationship_count)} denied relationships
              </span>
            </div>
            <div aria-hidden="true" className="rule-hairline" />
            <p className="m-0 text-sm text-muted">
              {formatNumber(ontology.graph_query.returned_node_count)} nodes /{" "}
              {formatNumber(ontology.graph_query.returned_relationship_count)} relationships returned for{" "}
              {ontology.graph_query.actor_id}
            </p>
            <p className="m-0 text-sm text-muted">
              Permission decision: {ontology.graph_query.permission_decision.reason}
            </p>
          </Card>

          <Card className="grid content-start gap-3">
            <Eyebrow>Permission Notes</Eyebrow>
            <h2 className="font-display m-0 text-xl text-ink">Read boundaries</h2>
            <div className="grid gap-2">
              {ontology.permission_notes.map((note) => (
                <p className="m-0 text-sm text-muted" key={note}>
                  {note}
                </p>
              ))}
            </div>
          </Card>
        </div>
      </Disclosure>

      <OntologyEntitySheet
        nodeId={selectedNodeId}
        onCloseAutoFocus={restoreEntityFocus}
        onNavigateToNode={navigateToEntity}
        onOpenChange={(open) => {
          if (!open) {
            closeEntity();
          }
        }}
        tenantId={tenantId}
      />
    </div>
  );
}
