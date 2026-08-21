"use client";

import Link from "next/link";
import { Bot, GitBranch, Play, ShieldCheck } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { ErrorPanel, LoadingPanel } from "@/components/ui/states";
import {
  countBlockedModelRoutes,
  type ManufacturingModelRouting,
} from "@/lib/model-routing-demo";
import {
  platformStatusLabel,
  type ManufacturingOperationsSnapshot,
  type ManufacturingOverview,
  type PlatformStatus,
} from "@/lib/platform-overview";
import { strings } from "@/lib/strings";

import { overviewErrorReference, StatusDot, type OverviewQuery } from "./overview-shared";

/*
 * Overview side rail: the system-health radar (computed from the live
 * overview / snapshot / model-routing payloads — the internal demo-readiness
 * QA panel is gone) plus quick actions. Signals from a failed endpoint are
 * simply omitted rather than faked.
 */

type HealthSignal = { label: string; status: PlatformStatus };

function statusScore(status: PlatformStatus): number {
  if (status === "ready") {
    return 0.92;
  }

  return status === "watch" ? 0.68 : 0.46;
}

function radarPoint(index: number, total: number, status: PlatformStatus): string {
  const center = 54;
  const radius = 41 * statusScore(status);
  const angle = -Math.PI / 2 + (Math.PI * 2 * index) / total;

  return `${(center + Math.cos(angle) * radius).toFixed(1)},${(
    center + Math.sin(angle) * radius
  ).toFixed(1)}`;
}

function buildHealthSignals({
  overview,
  snapshot,
  routing,
}: {
  overview: ManufacturingOverview | null;
  snapshot: ManufacturingOperationsSnapshot | null;
  routing: ManufacturingModelRouting | null;
}): HealthSignal[] {
  const signals: HealthSignal[] = [];

  if (overview) {
    const workflowMetric = overview.metrics.find((metric) => metric.label === "Workflow Load");
    const agentsMetric = overview.metrics.find((metric) => metric.label === "Agents");
    signals.push(
      { label: "Workflows", status: workflowMetric?.status ?? "watch" },
      { label: "Agents", status: agentsMetric?.status ?? "ready" },
      { label: "Approvals", status: overview.approvals.length > 0 ? "watch" : "ready" },
    );
  }

  if (snapshot) {
    signals.push(
      {
        label: "Data",
        status: snapshot.metrics.every((metric) => metric.status === "ready") ? "ready" : "watch",
      },
      {
        label: "Connectors",
        status: snapshot.recent_audit_events.some((event) =>
          event.event_type.startsWith("connector."),
        )
          ? "ready"
          : "watch",
      },
    );
  }

  if (routing) {
    signals.push({ label: "Models", status: routing.routing_status });
  }

  return signals;
}

function SystemHealth({
  overview,
  snapshot,
  routing,
}: {
  overview: OverviewQuery<ManufacturingOverview>;
  snapshot: OverviewQuery<ManufacturingOperationsSnapshot>;
  routing: OverviewQuery<ManufacturingModelRouting>;
}) {
  const copy = strings.overview.sideRail;
  const signals = buildHealthSignals({
    overview: overview.data,
    snapshot: snapshot.data,
    routing: routing.data,
  });

  // A radar needs at least three axes; below that the section degrades.
  if (signals.length < 3) {
    const anyLoading = [overview, snapshot, routing].some(
      (query) => query.source === "loading" && !query.data,
    );

    if (anyLoading) {
      return <LoadingPanel layout="detail" />;
    }

    return (
      <ErrorPanel
        detail={copy.error.detail}
        reference={overviewErrorReference(overview, snapshot, routing)}
        title={copy.error.title}
      />
    );
  }

  const polygon = signals
    .map((signal, index) => radarPoint(index, signals.length, signal.status))
    .join(" ");
  const baseline = signals
    .map((_, index) => radarPoint(index, signals.length, "watch"))
    .join(" ");

  return (
    <Card className="grid content-start gap-3">
      <h2 className="eyebrow m-0 text-[11px] font-medium">{copy.health}</h2>
      <svg
        aria-label="System health radar"
        className="mx-auto h-auto w-full max-w-52"
        role="img"
        viewBox="0 0 108 108"
      >
        {[18, 30, 42].map((radius) => (
          <circle
            cx="54"
            cy="54"
            fill="none"
            key={radius}
            r={radius}
            stroke="rgb(var(--line) / 0.7)"
          />
        ))}
        {signals.map((signal, index) => {
          const point = radarPoint(index, signals.length, "ready");
          const [x, y] = point.split(",");

          return (
            <line key={signal.label} stroke="rgb(var(--line) / 0.6)" x1="54" x2={x} y1="54" y2={y} />
          );
        })}
        <polygon
          fill="none"
          points={baseline}
          stroke="rgb(var(--muted) / 0.5)"
          strokeDasharray="2 3"
        />
        <polygon
          fill="rgb(var(--signal) / 0.16)"
          points={polygon}
          stroke="rgb(var(--signal))"
          strokeWidth="2"
        />
      </svg>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
        {signals.map((signal) => (
          <span className="inline-flex items-center gap-2 text-xs text-muted" key={signal.label}>
            <StatusDot status={signal.status} />
            {signal.label}
          </span>
        ))}
      </div>
      {routing.data ? (
        <>
          <div aria-hidden="true" className="rule-hairline" />
          <p className="m-0 text-xs text-muted">
            Routing posture: {platformStatusLabel(routing.data.routing_status)} /{" "}
            {countBlockedModelRoutes(routing.data)} blocked route
            {countBlockedModelRoutes(routing.data) === 1 ? "" : "s"}
          </p>
        </>
      ) : null}
    </Card>
  );
}

function QuickActions() {
  const actions = [
    { label: "View workflows", href: "/workflows", icon: GitBranch },
    { label: "View agents", href: "/agents", icon: Bot },
    { label: "Create policy", href: "/policies", icon: ShieldCheck },
    { label: "Run simulation", href: "/simulation", icon: Play },
  ];

  return (
    <Card className="grid content-start gap-3">
      <Eyebrow>{strings.overview.sideRail.quickActions}</Eyebrow>
      <div className="grid grid-cols-2 gap-2">
        {actions.map((action) => {
          const Icon = action.icon;

          return (
            <Link
              className="inline-flex items-center gap-2 rounded-xl border border-line px-3 py-2.5 text-xs font-medium text-ink transition-colors hover:border-signal/50 hover:text-signal dark:border-white/10"
              href={action.href}
              key={action.label}
            >
              <Icon className="shrink-0" size={15} />
              {action.label}
            </Link>
          );
        })}
      </div>
    </Card>
  );
}

export function SideRail({
  overview,
  snapshot,
  routing,
}: {
  overview: OverviewQuery<ManufacturingOverview>;
  snapshot: OverviewQuery<ManufacturingOperationsSnapshot>;
  routing: OverviewQuery<ManufacturingModelRouting>;
}) {
  return (
    <>
      <SystemHealth overview={overview} routing={routing} snapshot={snapshot} />
      <QuickActions />
    </>
  );
}
