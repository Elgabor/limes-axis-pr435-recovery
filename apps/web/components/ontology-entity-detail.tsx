"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { EntityDetailContent } from "@/components/ontology/entity-detail-content";
import { useOntologyEntity } from "@/components/ontology/use-ontology-entity";
import { PlatformStatusPill } from "@/components/status-pill";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { SourcePill } from "@/components/ui/source-pill";
import { EmptyPanel, ErrorPanel } from "@/components/ui/states";
import { formatContextPath, formatTimestamp } from "@/lib/format";
import { deriveSourceState } from "@/lib/source-state";
import { DEMO_TENANT_ID } from "@/lib/tenant-scope";
import {
  IDENTITY_SESSION_ENDPOINT,
  useConsoleTenantScope,
} from "@/lib/use-console-tenant-scope";

export function OntologyEntityDetail({ nodeId }: { nodeId: string }) {
  const { identity, tenantId, tenantQueriesEnabled } = useConsoleTenantScope();
  const { detail, endpoint, errorRequestId, source } = useOntologyEntity(
    nodeId,
    tenantId ?? DEMO_TENANT_ID,
    tenantQueriesEnabled,
  );

  if (identity.source === "unavailable") {
    return (
      <ErrorPanel
        detail="The entity is not loaded until the current actor and tenant are verified."
        endpoint={IDENTITY_SESSION_ENDPOINT}
        reference={identity.errorRequestId ?? undefined}
        title="Identity API unavailable"
      />
    );
  }

  if (identity.source === "api" && !tenantId) {
    return (
      <ErrorPanel
        detail="The authenticated identity response does not contain a tenant. Axis will not fall back to a demo entity."
        endpoint={IDENTITY_SESSION_ENDPOINT}
        title="Authenticated tenant missing"
      />
    );
  }

  if (!detail) {
    if (source === "loading") {
      return (
        <div className="grid gap-5" aria-busy="true" aria-label="Loading entity API">
          <Skeleton className="h-28" />
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
          </div>
          <Skeleton className="h-72" />
        </div>
      );
    }

    if (source !== "missing") {
      return (
        <ErrorPanel
          detail="Axis did not receive an API-backed ontology entity. Local fallback entity records are disabled."
          endpoint={endpoint ?? undefined}
          reference={errorRequestId ?? undefined}
          title="Entity API unavailable"
        />
      );
    }

    return (
      <EmptyPanel
        action={{ label: "Back to ontology", href: "/ontology" }}
        detail={`No ontology entity exists with the id ${nodeId}. It may have been renamed or removed from the graph.`}
        title="Entity not found"
      />
    );
  }

  return (
    <div className="grid gap-5">
      <Card className="flex flex-wrap items-start justify-between gap-4">
        <div className="grid gap-1">
          <Eyebrow>Ontology Entity</Eyebrow>
          <h2 className="font-display m-0 text-2xl text-ink">{detail.node.label}</h2>
          <p className="m-0 text-sm text-muted">
            {formatContextPath(detail.scenario, detail.tenant_id)}
          </p>
        </div>
        <div
          className="flex flex-wrap items-center gap-2"
          aria-label="Entity source and node status"
        >
          <SourcePill
            state={deriveSourceState(
              source === "missing" ? "unavailable" : source,
              Boolean(detail),
              detail.provenance,
            )}
            subject="ontology entity"
          />
          <PlatformStatusPill status={detail.node.status} />
          <span className="font-mono text-xs text-muted">
            {formatTimestamp(detail.as_of)}
          </span>
        </div>
      </Card>

      <EntityDetailContent
        detail={detail}
        summaryAction={
          <Link
            className="inline-flex items-center gap-2 rounded-full border border-mist bg-surface px-5 py-2.5 text-sm font-medium text-ink transition-colors hover:border-signal/50 hover:text-signal dark:border-white/20"
            href="/ontology"
          >
            <ArrowLeft size={16} />
            Ontology
          </Link>
        }
      />
    </div>
  );
}
