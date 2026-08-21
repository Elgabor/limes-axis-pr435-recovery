"use client";

import { Suspense } from "react";

import { OnboardingChecklist } from "@/components/onboarding-checklist";
import { ArtifactPanel } from "@/components/overview/artifact-panel";
import { EvidenceFeed } from "@/components/overview/evidence-feed";
import { NeedsAttention } from "@/components/overview/needs-attention";
import { type OverviewQuery } from "@/components/overview/overview-shared";
import { PostureCards } from "@/components/overview/posture-cards";
import { SideRail } from "@/components/overview/side-rail";
import { SourcePill } from "@/components/ui/source-pill";
import { ErrorPanel, LoadingPanel } from "@/components/ui/states";
import type { ManufacturingAuditExplorer } from "@/lib/audit-demo";
import type { ManufacturingModelRouting } from "@/lib/model-routing-demo";
import {
  formatContextPath,
  formatNumber,
  formatTimestamp,
  NO_VALUE,
} from "@/lib/format";
import {
  type IdentitySessionReadModel,
  type ManufacturingOperationsSnapshot,
  type ManufacturingOverview,
} from "@/lib/platform-overview";
import { strings } from "@/lib/strings";
import { parseManufacturingAuditExplorer } from "@/lib/runtime-contracts/audit";
import { parseManufacturingModelRouting } from "@/lib/runtime-contracts/model-routing";
import {
  parseManufacturingOperationsSnapshot,
  parseManufacturingOverview,
  parseIdentitySessionReadModel,
} from "@/lib/runtime-contracts/overview";
import { deriveSourceState } from "@/lib/source-state";
import {
  buildTenantScopedPath,
  DEMO_TENANT_ID,
  resolveConsoleTenantScope,
  OPERATIONS_API_PREFIX,
} from "@/lib/tenant-scope";
import { useAxisQuery } from "@/lib/use-axis-query";
import { useDemoBootstrap } from "@/lib/use-demo-bootstrap";
import { useConsole } from "@/providers/console-provider";

/*
 * Overview control room (spec §5.1): slim hero, needs-attention strip,
 * posture cards, one evidence feed, governed-artifact panel, side rail.
 * Four independent queries — there is deliberately no page-level gate, so a
 * failing endpoint degrades only the sections that read from it.
 */

const IDENTITY_SESSION_ENDPOINT = "/identity/session";
const OVERVIEW_ENDPOINT = `${OPERATIONS_API_PREFIX}/overview`;
const SNAPSHOT_ENDPOINT = `${OPERATIONS_API_PREFIX}/operations/snapshot`;
const MODEL_ROUTING_ENDPOINT = `${OPERATIONS_API_PREFIX}/model-routing`;
const AUDIT_EVENTS_ENDPOINT = `${OPERATIONS_API_PREFIX}/audit/events`;

function OverviewHero({
  overview,
  snapshot,
  auditEvents,
}: {
  overview: OverviewQuery<ManufacturingOverview>;
  snapshot: OverviewQuery<ManufacturingOperationsSnapshot>;
  auditEvents: OverviewQuery<ManufacturingAuditExplorer>;
}) {
  if (!overview.data) {
    if (overview.source === "loading") {
      return <LoadingPanel layout="detail" />;
    }

    return (
      <ErrorPanel
        detail={strings.overview.hero.error.detail}
        endpoint={OVERVIEW_ENDPOINT}
        reference={overview.errorRequestId ?? undefined}
        title={strings.overview.hero.error.title}
      />
    );
  }

  const data = overview.data;
  const asOf = snapshot.data?.as_of ?? data.as_of;
  /*
   * Every headline number is read from the persisted operations snapshot, not
   * from the reference scenario. The scenario's own arrays and metrics describe
   * a fictional plant — on a live tenant they read "3 workflows / 3 approvals
   * pending" while the persisted truth is zero, which is exactly the kind of
   * confident-but-wrong number this console must never show. When the snapshot
   * has not resolved, the fact reads "—" rather than falling back to seed data.
   */
  const persistedFact = (metricLabel: string): string => {
    const metric = snapshot.data?.metrics.find((entry) => entry.label === metricLabel);
    return metric ? metric.value : NO_VALUE;
  };
  // The audit endpoint is fetched with a fixed limit and exposes no total, so
  // this is explicitly the size of the latest window, never "all events".
  const auditEventCount = auditEvents.data
    ? formatNumber(auditEvents.data.events.length)
    : NO_VALUE;
  const facts = [
    { label: strings.overview.hero.facts.openWorkflows, value: persistedFact("Open Workflows") },
    {
      label: strings.overview.hero.facts.pendingApprovals,
      value: persistedFact("Pending Approvals"),
    },
    { label: strings.overview.hero.facts.operationRecords, value: persistedFact("Operation Records") },
    {
      label: strings.overview.hero.facts.recentAudit,
      value: auditEventCount,
      testId: "hero-audit-count",
    },
  ];

  return (
    <div className="grid gap-2">
      <section className="relative overflow-hidden rounded-3xl border border-navy bg-navy px-6 py-6 text-white sm:px-8 dark:border-white/10">
        {/* Signal glow + static dot grid, same treatment in both themes. */}
        <div
          aria-hidden="true"
          className="absolute inset-0"
          style={{
            backgroundImage:
              "radial-gradient(ellipse 80% 90% at 50% 110%, rgb(47 100 255 / 0.35) 0%, rgb(47 100 255 / 0.08) 45%, transparent 70%), radial-gradient(rgb(255 255 255 / 0.05) 1px, transparent 1px)",
            backgroundSize: "auto, 22px 22px",
          }}
        />
        <div className="relative z-10 flex flex-wrap items-center justify-between gap-x-8 gap-y-4">
          <div className="grid gap-1">
            <h2 className="font-display font-display-lg m-0 text-2xl text-white">
              {formatContextPath(data.scenario) || strings.overview.hero.fallbackTitle}
            </h2>
            <p className="m-0 text-sm text-white/70" data-hero-subtitle>
              {formatContextPath(data.plant_name, formatTimestamp(asOf))}
            </p>
          </div>
          <div className="flex flex-wrap gap-x-8 gap-y-3">
            {facts.map((fact) => (
              <div className="grid gap-0.5" key={fact.label}>
                {/* Facts sit one step below the scenario title so the band has a
                    single focal point, and use tabular figures so the row does
                    not shift as counts change. */}
                <span
                  className="font-display text-xl tabular-nums text-white"
                  data-testid={fact.testId}
                >
                  {fact.value}
                </span>
                <span className="font-mono text-[11px] tracking-[0.12em] text-white/60 uppercase">
                  {fact.label}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>
      <div
        aria-label="Overview data sources"
        className="flex min-w-0 flex-wrap items-center justify-end gap-1.5"
      >
        <SourcePill
          state={deriveSourceState(overview.source, true, data.provenance)}
          subject="scenario context"
        />
        <SourcePill
          state={deriveSourceState(
            snapshot.source,
            Boolean(snapshot.data),
            snapshot.data?.provenance,
          )}
          subject="operations snapshot"
        />
        <SourcePill
          state={deriveSourceState(
            auditEvents.source,
            Boolean(auditEvents.data),
            auditEvents.data?.provenance,
          )}
          subject="audit window"
        />
      </div>
    </div>
  );
}

export function PlatformOverview() {
  const { apiStatus, triggerRefresh } = useConsole();
  const demoBootstrap = useDemoBootstrap();
  const identityQuery = useAxisQuery<IdentitySessionReadModel>(IDENTITY_SESSION_ENDPOINT, {
    parse: parseIdentitySessionReadModel,
  });
  const tenantScope = resolveConsoleTenantScope(identityQuery.data);
  const tenantId = tenantScope.tenantId;
  const tenantQueriesEnabled = identityQuery.source === "api" && tenantId !== null;
  const overviewPath = buildTenantScopedPath(
    OVERVIEW_ENDPOINT,
    tenantId ?? DEMO_TENANT_ID,
  );
  const snapshotPath = buildTenantScopedPath(
    SNAPSHOT_ENDPOINT,
    tenantId ?? DEMO_TENANT_ID,
  );
  const routingPath = buildTenantScopedPath(
    MODEL_ROUTING_ENDPOINT,
    tenantId ?? DEMO_TENANT_ID,
  );
  const auditEventsPath = buildTenantScopedPath(
    AUDIT_EVENTS_ENDPOINT,
    tenantId ?? DEMO_TENANT_ID,
    { limit: 25 },
  );
  const overviewQuery = useAxisQuery<ManufacturingOverview>(overviewPath, {
    enabled: tenantQueriesEnabled,
    expectedTenantId: tenantId ?? undefined,
    parse: parseManufacturingOverview,
  });
  const snapshotQuery = useAxisQuery<ManufacturingOperationsSnapshot>(snapshotPath, {
    enabled: tenantQueriesEnabled,
    expectedTenantId: tenantId ?? undefined,
    parse: parseManufacturingOperationsSnapshot,
  });
  const routingQuery = useAxisQuery<ManufacturingModelRouting>(routingPath, {
    enabled: tenantQueriesEnabled,
    expectedTenantId: tenantId ?? undefined,
    parse: parseManufacturingModelRouting,
  });
  const auditEventsQuery = useAxisQuery<ManufacturingAuditExplorer>(auditEventsPath, {
    enabled: tenantQueriesEnabled,
    expectedTenantId: tenantId ?? undefined,
    parse: parseManufacturingAuditExplorer,
  });

  if (identityQuery.source === "loading") {
    return <LoadingPanel layout="detail" />;
  }

  if (identityQuery.source === "unavailable") {
    return (
      <ErrorPanel
        detail="The console could not verify the current actor and tenant. Tenant-scoped data is not loaded until identity is available."
        endpoint={IDENTITY_SESSION_ENDPOINT}
        reference={identityQuery.errorRequestId ?? undefined}
        title="Identity API unavailable"
      />
    );
  }

  if (!tenantId) {
    return (
      <ErrorPanel
        detail="The authenticated identity response does not contain a tenant. Axis will not fall back to demo data for an authenticated actor."
        endpoint={IDENTITY_SESSION_ENDPOINT}
        title="Authenticated tenant missing"
      />
    );
  }

  // An overview 404 on an otherwise healthy API means the tenant has never
  // been bootstrapped — that is the guided-setup story (spec §6), not an
  // error. A genuinely unreachable API (network failure, /ready probe down)
  // keeps the section-level error wall below.
  const tenantEmpty =
    !overviewQuery.data
    && overviewQuery.source === "unavailable"
    && overviewQuery.errorStatus === 404
    && apiStatus.state !== "unavailable";

  if (tenantEmpty) {
    return (
      <div className="grid gap-4">
        <OnboardingChecklist
          demoAvailable={tenantScope.mode === "demo"}
          demoError={demoBootstrap.error}
          demoPending={demoBootstrap.pending}
          onExploreDemo={demoBootstrap.bootstrapDemo}
          tenantId={tenantId}
          variant="full"
        />
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      {/* Partially onboarded tenants keep a compact progress strip on top;
          it renders nothing at 0 of 5 or 5 of 5. */}
      <OnboardingChecklist tenantId={tenantId} variant="compact" />
      <OverviewHero
        auditEvents={auditEventsQuery}
        overview={overviewQuery}
        snapshot={snapshotQuery}
      />

      <NeedsAttention
        actor={
          identityQuery.data?.actor_id
            ? { actorId: identityQuery.data.actor_id, scopes: identityQuery.data.scopes }
            : undefined
        }
        overview={overviewQuery}
        tenantId={tenantId}
      />

      <PostureCards
        overview={overviewQuery}
        routing={routingQuery}
        snapshot={snapshotQuery}
        tenantId={tenantId}
      />

      <div className="ops-dashboard-grid grid grid-cols-1 gap-4 min-[1400px]:grid-cols-[minmax(0,1fr)_320px]">
        <section aria-label="Operations evidence" className="ops-dashboard-main grid min-w-0 content-start gap-4">
          <EvidenceFeed auditEvents={auditEventsQuery} />
          {/* Suspense boundary for useSearchParams inside the artifact panel. */}
          <Suspense fallback={<LoadingPanel layout="detail" />}>
            <ArtifactPanel onArtifactCommitted={triggerRefresh} snapshot={snapshotQuery} />
          </Suspense>
        </section>
        <aside
          aria-label="Operations side rail"
          className="ops-right-rail grid min-w-0 content-start gap-4"
        >
          <SideRail overview={overviewQuery} routing={routingQuery} snapshot={snapshotQuery} />
        </aside>
      </div>
    </div>
  );
}
