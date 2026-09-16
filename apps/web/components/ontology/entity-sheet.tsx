"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";

import { EntityDetailContent } from "@/components/ontology/entity-detail-content";
import { useOntologyEntity } from "@/components/ontology/use-ontology-entity";
import { PlatformStatusPill } from "@/components/status-pill";
import { Eyebrow } from "@/components/ui/eyebrow";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  type SheetContentProps,
} from "@/components/ui/sheet";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/ui/states";
import { formatNodeType } from "@/lib/ontology-demo";
import { buildOntologyEntityRoute } from "@/lib/ontology-routes";
import { strings } from "@/lib/strings";

type OntologyEntitySheetProps = {
  /** Entity to show; `null` keeps the sheet closed (and fetches nothing). */
  nodeId: string | null;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus?: SheetContentProps["onCloseAutoFocus"];
  /** Swap the sheet to a peer entity without navigating away. */
  onNavigateToNode?: (nodeId: string) => void;
  /** API-verified tenant inherited from the ontology explorer. */
  tenantId: string;
};

/**
 * Slide-over entity detail for the ontology explorer. Opening it never
 * navigates, so the graph behind keeps its view mode, zoom and selection;
 * the "Open full page" link points at the deep-linkable entity route.
 */
export function OntologyEntitySheet({
  nodeId,
  onOpenChange,
  onCloseAutoFocus,
  onNavigateToNode,
  tenantId,
}: OntologyEntitySheetProps) {
  const { detail, endpoint, errorRequestId, source } = useOntologyEntity(nodeId, tenantId);

  if (!nodeId) {
    return null;
  }

  return (
    <Sheet open onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-xl" onCloseAutoFocus={onCloseAutoFocus}>
        <SheetHeader>
          <Eyebrow>{strings.ontology.sheet.eyebrow}</Eyebrow>
          <SheetTitle>{detail ? detail.node.label : nodeId}</SheetTitle>
          <SheetDescription>
            {detail
              ? `${formatNodeType(detail.node.node_type)} / ${detail.node.domain}`
              : strings.ontology.sheet.eyebrow}
          </SheetDescription>
          <div className="flex flex-wrap items-center gap-3 pt-1">
            {detail ? <PlatformStatusPill status={detail.node.status} /> : null}
            <Link
              className="inline-flex items-center gap-1.5 text-sm font-medium text-signal hover:underline"
              href={buildOntologyEntityRoute(nodeId)}
            >
              <ExternalLink aria-hidden="true" size={14} />
              {strings.ontology.sheet.openFullPage}
            </Link>
          </div>
        </SheetHeader>

        {source === "loading" ? (
          <LoadingPanel layout="detail" />
        ) : source === "unavailable" && !detail ? (
          <ErrorPanel
            detail={strings.ontology.sheet.error.detail}
            endpoint={endpoint ?? undefined}
            reference={errorRequestId ?? undefined}
            title={strings.ontology.sheet.error.title}
          />
        ) : source === "missing" || !detail ? (
          <EmptyPanel
            detail={strings.ontology.sheet.notFound.detail}
            title={strings.ontology.sheet.notFound.title}
          />
        ) : (
          <>
            {source === "unavailable" ? (
              <p className="m-0 text-sm text-warning" role="status">
                Live refresh failed. Showing the last validated entity data.
              </p>
            ) : null}
            <EntityDetailContent detail={detail} layout="sheet" onNavigateToNode={onNavigateToNode} />
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
