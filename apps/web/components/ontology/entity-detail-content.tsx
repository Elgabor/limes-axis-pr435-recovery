"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowLeftRight, Database, Network } from "lucide-react";

import { Reveal } from "@/components/reveal";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { formatNodeType, type ManufacturingOntologyEntityDetail } from "@/lib/ontology-demo";
import { buildOntologyEntityRoute } from "@/lib/ontology-routes";

/*
 * Presentational core of the ontology entity detail, shared by the full
 * entity page and the explorer slide-over. Page chrome (headers, source
 * pills, back links) stays with the callers.
 */

type EntityDetailLayout = "page" | "sheet";

type EntityDetailContentProps = {
  detail: ManufacturingOntologyEntityDetail;
  /** "page" spreads sections into columns; "sheet" stacks them. */
  layout?: EntityDetailLayout;
  /**
   * When set, peer entity chips become buttons handled in place (the
   * slide-over swaps entities without navigating). Defaults to links to
   * the full entity pages.
   */
  onNavigateToNode?: (nodeId: string) => void;
  /** Optional action rendered next to the summary (e.g. a back link). */
  summaryAction?: ReactNode;
};

function TagList({ items, emptyLabel }: { items: string[]; emptyLabel: string }) {
  const rendered = items.length > 0 ? items : [emptyLabel];

  return (
    <div className="flex flex-wrap gap-2">
      {rendered.map((item) => (
        <span
          className="inline-flex items-center rounded-full border border-line px-3 py-1 font-mono text-xs text-muted dark:border-white/15"
          key={item}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function EntityMetric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <Card className="grid content-start gap-2 p-5">
      <Eyebrow>{label}</Eyebrow>
      <p className="font-display m-0 text-2xl break-words text-ink">{value}</p>
      <div aria-hidden="true" className="rule-hairline" />
      <p className="m-0 font-mono text-xs break-words text-muted">{detail}</p>
    </Card>
  );
}

function PeerNodeChip({
  label,
  nodeId,
  onNavigateToNode,
}: {
  label: string;
  nodeId: string;
  onNavigateToNode?: (nodeId: string) => void;
}) {
  const className =
    "inline-flex items-center rounded-full border border-line px-3 py-1 font-mono text-xs text-ink transition-colors hover:border-signal/60 hover:text-signal dark:border-white/15";

  if (onNavigateToNode) {
    return (
      <button className={className} onClick={() => onNavigateToNode(nodeId)} type="button">
        {label}
      </button>
    );
  }

  return (
    <Link className={className} href={buildOntologyEntityRoute(nodeId)}>
      {label}
    </Link>
  );
}

export function EntityDetailContent({
  detail,
  layout = "page",
  onNavigateToNode,
  summaryAction,
}: EntityDetailContentProps) {
  const isPage = layout === "page";
  const MaybeReveal = isPage ? Reveal : "div";

  return (
    <div className="grid min-w-0 gap-5">
      <div className={`grid grid-cols-2 gap-4 ${isPage ? "lg:grid-cols-4" : ""}`}>
        <EntityMetric
          detail={detail.node.node_id}
          label="Type"
          value={formatNodeType(detail.node.node_type)}
        />
        <EntityMetric detail={detail.node.source_system} label="Domain" value={detail.node.domain} />
        <EntityMetric
          detail="Incoming relationships"
          label="Inbound"
          value={String(detail.inbound_count)}
        />
        <EntityMetric
          detail="Outgoing relationships"
          label="Outbound"
          value={String(detail.outbound_count)}
        />
      </div>

      <Card className="flex flex-wrap items-start justify-between gap-4">
        <div className="grid max-w-2xl gap-1">
          <Eyebrow>Summary</Eyebrow>
          <h2 className="font-display m-0 text-xl text-ink">Read-only entity context</h2>
          <p className="m-0 text-sm text-muted">{detail.node.summary}</p>
        </div>
        {summaryAction}
      </Card>

      <MaybeReveal>
        <div className={`grid gap-4 ${isPage ? "xl:grid-cols-[3fr_2fr]" : ""}`}>
          <Card className="grid content-start gap-4">
            <div className="flex items-start justify-between gap-3">
              <div className="grid gap-1">
                <Eyebrow>Relationships</Eyebrow>
                <h2 className="font-display m-0 text-xl text-ink">
                  {detail.connected_relationships.length} connected
                </h2>
              </div>
              <Network className="text-signal" size={18} />
            </div>
            <div className="grid gap-0">
              {detail.connected_relationships.map((item, index) => (
                <div
                  className="grid gap-3 py-4 first:pt-0 last:pb-0"
                  key={item.relationship.relationship_id}
                >
                  {index > 0 ? <div aria-hidden="true" className="rule-hairline -mt-4 mb-1" /> : null}
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="grid min-w-0 gap-1">
                      <p className="m-0 inline-flex items-center gap-2 text-sm font-medium text-ink">
                        <ArrowLeftRight className="shrink-0 text-signal" size={14} />
                        {item.direction} / {item.relationship.relation_type}
                      </p>
                      <p className="m-0 text-sm text-muted">{item.relationship.summary}</p>
                      <p className="m-0 font-mono text-xs text-muted">
                        {item.relationship.permission_scope}
                      </p>
                      <p className="m-0 text-xs text-muted">
                        {item.relationship.metadata.owner_role} /{" "}
                        {item.relationship.metadata.verification_status}
                      </p>
                      <p className="m-0 font-mono text-xs break-words text-muted">
                        {item.relationship.metadata.evidence_refs.join(", ")}
                      </p>
                    </div>
                    <PeerNodeChip
                      label={item.peer_node.label}
                      nodeId={item.peer_node.node_id}
                      onNavigateToNode={onNavigateToNode}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card className="grid content-start gap-4">
            <div className="grid gap-1">
              <Eyebrow>Governance</Eyebrow>
              <h2 className="font-display m-0 text-xl text-ink">Access and evidence</h2>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <section className="grid content-start gap-2">
                <Eyebrow>Required Permissions</Eyebrow>
                <TagList items={detail.required_permissions} emptyLabel="derived read scope" />
              </section>
              <section className="grid content-start gap-2">
                <Eyebrow>Evidence</Eyebrow>
                <TagList items={detail.evidence_refs} emptyLabel="node summary only" />
              </section>
            </div>
            <div aria-hidden="true" className="rule-hairline" />
            <div className="grid gap-4 sm:grid-cols-2">
              <section className="grid content-start gap-2">
                <Eyebrow>Workflows</Eyebrow>
                <TagList items={detail.related_workflows} emptyLabel="no workflow relation" />
              </section>
              <section className="grid content-start gap-2">
                <Eyebrow>Approvals</Eyebrow>
                <TagList items={detail.related_approvals} emptyLabel="no approval relation" />
              </section>
            </div>
            <div aria-hidden="true" className="rule-hairline" />
            <section className="grid content-start gap-2">
              <Eyebrow>Agents</Eyebrow>
              <TagList items={detail.related_agents} emptyLabel="no agent relation" />
            </section>
          </Card>
        </div>
      </MaybeReveal>

      <MaybeReveal>
        <div className={`grid gap-4 ${isPage ? "lg:grid-cols-2" : ""}`}>
          <Card className="grid content-start gap-3">
            <Eyebrow>Data Access</Eyebrow>
            <div className="grid gap-3">
              {detail.data_access.map((item) => (
                <div className="flex items-start justify-between gap-3" key={item}>
                  <div className="grid gap-0.5">
                    <p className="m-0 text-sm font-medium text-ink">{item}</p>
                    <p className="m-0 text-xs text-muted">Public demo summary only</p>
                  </div>
                  <Database className="shrink-0 text-signal" size={16} />
                </div>
              ))}
            </div>
          </Card>

          <Card className="grid content-start gap-3">
            <Eyebrow>Detail Notes</Eyebrow>
            <div className="grid gap-2">
              {detail.detail_notes.map((note) => (
                <p className="m-0 text-sm text-muted" key={note}>
                  {note}
                </p>
              ))}
            </div>
          </Card>
        </div>
      </MaybeReveal>
    </div>
  );
}
