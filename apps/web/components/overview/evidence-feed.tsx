"use client";

import Link from "next/link";

import { Card } from "@/components/ui/card";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/ui/states";
import {
  buildAuditEventHref,
  type ManufacturingAuditExplorer,
} from "@/lib/audit-demo";
import { strings } from "@/lib/strings";

import {
  normalizeLabel,
  PanelHeader,
  PanelLink,
  shortTime,
  StatusDot,
  type OverviewQuery,
} from "./overview-shared";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

/*
 * The single evidence feed for the overview: one list of recent persisted
 * audit events with tone dots and deep links into /audit. Replaces the three
 * overlapping audit surfaces of the previous overview (connector evidence
 * table, audit observability chart, recent activity list).
 */

export const AUDIT_EVENTS_ENDPOINT = `${OPERATIONS_API_PREFIX}/audit/events`;

const FEED_ROW_LIMIT = 10;

export function EvidenceFeed({
  auditEvents,
}: {
  auditEvents: OverviewQuery<ManufacturingAuditExplorer>;
}) {
  const copy = strings.overview.evidenceFeed;

  if (!auditEvents.data) {
    if (auditEvents.source === "loading") {
      return <LoadingPanel rows={6} />;
    }

    return (
      <ErrorPanel
        detail={copy.error.detail}
        endpoint={AUDIT_EVENTS_ENDPOINT}
        reference={auditEvents.errorRequestId ?? undefined}
        title={copy.error.title}
      />
    );
  }

  const events = auditEvents.data.events;

  if (events.length === 0) {
    return <EmptyPanel detail={copy.empty.detail} title={copy.empty.title} />;
  }

  return (
    <Card className="flex flex-col gap-4">
      <PanelHeader
        aside={
          <span className="font-mono text-xs whitespace-nowrap text-muted">
            Showing {Math.min(events.length, FEED_ROW_LIMIT)} of {events.length} recent events
          </span>
        }
        eyebrow={copy.eyebrow}
        title={copy.title}
      />
      <div className="grid gap-3">
        {events.slice(0, FEED_ROW_LIMIT).map((event) => (
          <div className="flex items-start gap-3" key={event.audit_event_id}>
            <span className="mt-1.5">
              <StatusDot status={event.severity} />
            </span>
            <div className="grid min-w-0 flex-1 gap-0.5">
              <Link
                className="m-0 inline-flex min-h-6 w-fit items-center text-sm font-medium break-words text-ink hover:text-signal hover:underline"
                href={buildAuditEventHref(event.audit_event_id)}
                title={copy.viewEvent}
              >
                {normalizeLabel(event.event_type)}
              </Link>
              <p className="m-0 text-xs text-muted">{event.actor_id}</p>
            </div>
            <span className="font-mono text-xs whitespace-nowrap text-muted">
              {shortTime(event.occurred_at)}
            </span>
          </div>
        ))}
      </div>
      <PanelLink href="/audit">{copy.openAudit}</PanelLink>
    </Card>
  );
}
