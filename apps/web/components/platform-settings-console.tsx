"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { Database } from "lucide-react";

import { ConsolePage } from "@/components/console-page";
import { InspectDrawer } from "@/components/ui/inspect-drawer";
import { ErrorPanel, LoadingPanel } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { enumUrlField, useConsoleUrlState } from "@/lib/console-url-state";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import {
  settingsCheckGuidance,
  settingsStatusClass,
  settingsStatusLabel,
  type AxisReadyReport,
  type DeploymentReadinessReport,
  type OidcReadinessReport,
  type SettingsCheck,
  type SupportDiagnosticsReport,
} from "@/lib/platform-settings";
import { strings } from "@/lib/strings";
import {
  parseAxisReadyReport,
  parseDeploymentReadinessReport,
  parseOidcReadinessReport,
  parseSupportDiagnosticsReport,
} from "@/lib/runtime-contracts/identity";
import {
  IDENTITY_SESSION_ENDPOINT,
  useIdentitySession,
} from "@/lib/use-identity-session";
import { useAxisQuery, type AxisQuerySource } from "@/lib/use-axis-query";

/*
 * System status console (spec §5.7): each readiness surface has its own
 * query and its own Loading/Error state, organized into Readiness / Identity
 * / Deployment / Support tabs. A single failing endpoint degrades only its
 * panel — there is deliberately no page-level gate. Every "Action required"
 * pill carries a plain-English what-to-do line; raw API detail stays as
 * secondary mono text and full payloads live in Inspect drawers.
 */

const READY_ENDPOINT = "/ready";
const OIDC_READINESS_ENDPOINT = "/identity/oidc/readiness";
const DEPLOYMENT_READINESS_ENDPOINT = "/deployment/readiness";
const SUPPORT_DIAGNOSTICS_ENDPOINT = "/support/diagnostics";

const copy = strings.settings;

const settingsTabs = ["readiness", "identity", "deployment", "support"] as const;
type SettingsTab = (typeof settingsTabs)[number];
const settingsUrlSchema = {
  tab: enumUrlField("tab", settingsTabs, "readiness"),
};

type SettingsQuery<T> = {
  data: T | null;
  errorRequestId?: string | null;
  source: AxisQuerySource;
};

function boolLabel(value: boolean): string {
  return value ? "Enabled" : "Disabled";
}

function compactId(value: string): string {
  return value.replaceAll("_", " ");
}

function SettingsStatusPill({ status }: { status: "ready" | "action_required" }) {
  return (
    <span className={`status-pill ${settingsStatusClass(status)}`}>
      {settingsStatusLabel(status)}
    </span>
  );
}

/**
 * Per-panel state gate: loading skeleton, panel-scoped ErrorPanel, or the
 * panel content. This replaces the old page-wide 5-way OR collapse.
 */
function PanelState<T>({
  query,
  endpoint,
  error,
  children,
}: {
  query: SettingsQuery<T>;
  endpoint: string;
  error: { title: string; detail: string };
  children: (data: T) => ReactNode;
}) {
  if (query.data) {
    return (
      <div className="grid min-w-0 gap-2">
        {query.source !== "api" ? (
          <p className="m-0 text-sm text-warning" role="status">
            {copy.stale}
            {query.errorRequestId ? ` Request ${query.errorRequestId}.` : null}
          </p>
        ) : null}
        {children(query.data)}
      </div>
    );
  }

  if (query.source === "loading") {
    return <LoadingPanel layout="detail" />;
  }

  return (
    <ErrorPanel
      detail={error.detail}
      endpoint={endpoint}
      reference={query.errorRequestId ?? undefined}
      title={error.title}
    />
  );
}

/** Check list with a guidance line on every action-required check. */
function CheckList({ checks }: { checks: SettingsCheck[] }) {
  return (
    <div className="grid min-w-0 gap-0 border-t border-line/60 pt-1 dark:border-white/10">
      {checks.map((check) => (
        <div
          className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10"
          key={check.check_id}
        >
          <div className="grid min-w-0 gap-1">
            <p className="m-0 font-medium text-ink break-words">{compactId(check.check_id)}</p>
            {check.status === "action_required" ? (
              <p className="m-0 text-sm leading-snug text-ink break-words">
                {settingsCheckGuidance(check.check_id)}
              </p>
            ) : null}
            <p className="m-0 font-mono text-xs leading-snug text-muted break-words">
              {check.detail}
            </p>
          </div>
          <SettingsStatusPill status={check.status} />
        </div>
      ))}
    </div>
  );
}

function SettingsPanel({
  eyebrow,
  title,
  status,
  inspect,
  children,
}: {
  eyebrow: string;
  title: string;
  status?: "ready" | "action_required";
  inspect?: Record<string, unknown>;
  children: ReactNode;
}) {
  return (
    <section className="min-w-0 rounded-2xl border border-line bg-surface p-5 dark:border-white/10 dark:bg-white/5">
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
        <div>
          <p className="eyebrow m-0">{eyebrow}</p>
          <h2 className="font-display mx-0 mt-1 mb-4 text-xl text-ink">{title}</h2>
        </div>
        <div className="flex items-center gap-3">
          {status ? <SettingsStatusPill status={status} /> : null}
          {inspect ? <InspectDrawer record={inspect} title={`${title} report`} /> : null}
        </div>
      </div>
      {children}
    </section>
  );
}

const factGridClass =
  "mb-3.5 grid gap-2.5 sm:grid-cols-2 [&>span]:grid [&>span]:min-w-0 [&>span]:gap-1 [&>span]:rounded-xl [&>span]:border [&>span]:border-line/60 [&>span]:bg-ink/3 [&>span]:p-2.5 dark:[&>span]:border-white/10 dark:[&>span]:bg-white/4 [&_small]:text-[11px] [&_small]:font-medium [&_small]:tracking-wide [&_small]:uppercase [&_small]:text-muted [&_strong]:min-w-0 [&_strong]:break-words [&_strong]:text-[13px] [&_strong]:leading-tight [&_strong]:text-ink";

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <small>{label}</small>
      <strong>{value}</strong>
    </span>
  );
}

function ReadyPanel({ query }: { query: SettingsQuery<AxisReadyReport> }) {
  return (
    <PanelState endpoint={READY_ENDPOINT} error={copy.ready.error} query={query}>
      {(report) => (
        <SettingsPanel
          eyebrow={copy.ready.eyebrow}
          inspect={report as unknown as Record<string, unknown>}
          status={report.status === "ready" ? "ready" : "action_required"}
          title={copy.ready.title}
        >
          <div className={`${factGridClass} [&>span]:grid-cols-[auto_minmax(0,1fr)] [&>span]:items-center [&_small]:col-start-2 [&_small]:normal-case [&_small]:tracking-normal`}>
            {Object.entries(report.dependencies).map(([dependency, readiness]) => (
              <span key={dependency}>
                <Database size={16} />
                <strong>{compactId(dependency)}</strong>
                <small
                  className={
                    readiness.status === "ready" || readiness.status === "disabled"
                      ? "signal-ready"
                      : "signal-action-required"
                  }
                >
                  {readiness.status === "ready"
                    ? copy.ready.dependencyReachable
                    : readiness.status === "disabled"
                      ? copy.ready.dependencyNotConfigured
                      : compactId(readiness.status)}
                </small>
              </span>
            ))}
          </div>
          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 dark:border-white/10">
            <div>
              <p className="m-0 font-medium text-ink break-words">{copy.ready.egressTitle}</p>
              <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                {copy.ready.egressDetail}
              </p>
            </div>
            <span
              className={`status-pill ${
                report.external_model_egress_enabled ? "signal-action-required" : "signal-ready"
              }`}
            >
              {boolLabel(report.external_model_egress_enabled)}
            </span>
          </div>
        </SettingsPanel>
      )}
    </PanelState>
  );
}

function ProductionGatesPanel({ query }: { query: SettingsQuery<DeploymentReadinessReport> }) {
  return (
    <PanelState endpoint={DEPLOYMENT_READINESS_ENDPOINT} error={copy.deployment.error} query={query}>
      {(report) => (
        <SettingsPanel
          eyebrow={copy.gates.eyebrow}
          status={report.status}
          title={copy.gates.title}
        >
          <div className={factGridClass}>
            <Fact label={copy.gates.demoSafe} value={boolLabel(report.demo_safe)} />
            <Fact label={copy.gates.productionReady} value={boolLabel(report.production_ready)} />
          </div>
          <CheckList
            checks={report.checks.filter(
              (check) => check.production_required && check.status === "action_required",
            )}
          />
          {report.production_blockers.length === 0 ? (
            <p className="m-0 pt-2 text-sm text-muted">{copy.gates.noBlockers}</p>
          ) : null}
        </SettingsPanel>
      )}
    </PanelState>
  );
}

function OidcPanel({ query }: { query: SettingsQuery<OidcReadinessReport> }) {
  return (
    <PanelState endpoint={OIDC_READINESS_ENDPOINT} error={copy.oidc.error} query={query}>
      {(report) => (
        <SettingsPanel
          eyebrow={copy.oidc.eyebrow}
          inspect={report as unknown as Record<string, unknown>}
          status={report.status}
          title={copy.oidc.title}
        >
          <div className={factGridClass}>
            <Fact label={copy.oidc.issuer} value={report.issuer} />
            <Fact label={copy.oidc.audience} value={report.audience} />
            <Fact label={copy.oidc.authRequired} value={boolLabel(report.auth_required)} />
            <Fact label={copy.oidc.actorClaim} value={report.token_binding.actor_claim} />
          </div>
          <CheckList checks={report.checks} />
        </SettingsPanel>
      )}
    </PanelState>
  );
}

function SessionPanel({ query }: { query: SettingsQuery<IdentitySessionReadModel> }) {
  return (
    <PanelState endpoint={IDENTITY_SESSION_ENDPOINT} error={copy.session.error} query={query}>
      {(session) => (
        <SettingsPanel
          eyebrow={copy.session.eyebrow}
          inspect={session as unknown as Record<string, unknown>}
          title={copy.session.title}
        >
          <div className={factGridClass}>
            <Fact
              label={copy.session.actor}
              value={session.authenticated && session.actor_id ? session.actor_id : copy.session.publicActor}
            />
            <Fact label={copy.session.tenant} value={session.tenant_id ?? "—"} />
            <Fact label={copy.session.mode} value={compactId(session.mode)} />
            <Fact label={copy.session.authenticated} value={boolLabel(session.authenticated)} />
          </div>
          <Link
            className="inline-flex w-fit items-center text-sm font-medium text-signal hover:underline"
            href="/settings/sessions"
          >
            {copy.session.manageSessions}
          </Link>
        </SettingsPanel>
      )}
    </PanelState>
  );
}

function DeploymentPanel({ query }: { query: SettingsQuery<DeploymentReadinessReport> }) {
  return (
    <PanelState endpoint={DEPLOYMENT_READINESS_ENDPOINT} error={copy.deployment.error} query={query}>
      {(report) => (
        <SettingsPanel
          eyebrow={copy.deployment.eyebrow}
          inspect={report as unknown as Record<string, unknown>}
          status={report.status}
          title={report.profile}
        >
          <div className={factGridClass}>
            <Fact label={copy.deployment.environment} value={report.environment} />
            <Fact label={copy.deployment.demoSafe} value={boolLabel(report.demo_safe)} />
            <Fact
              label={copy.deployment.productionReady}
              value={boolLabel(report.production_ready)}
            />
            <Fact
              label={copy.deployment.objectStore}
              value={String(report.capabilities.object_store_adapter)}
            />
            <Fact
              label={copy.deployment.wormRetention}
              value={boolLabel(Boolean(report.capabilities.object_store_worm_retention_enabled))}
            />
            <Fact
              label={copy.deployment.retentionMode}
              value={String(report.capabilities.object_store_retention_mode)}
            />
            <Fact
              label={copy.deployment.retentionDays}
              value={String(report.capabilities.object_store_retention_days)}
            />
          </div>
          <CheckList checks={report.checks.filter((check) => check.production_required)} />
        </SettingsPanel>
      )}
    </PanelState>
  );
}

function SupportPanel({ query }: { query: SettingsQuery<SupportDiagnosticsReport> }) {
  return (
    <PanelState endpoint={SUPPORT_DIAGNOSTICS_ENDPOINT} error={copy.support.error} query={query}>
      {(report) => (
        <SettingsPanel
          eyebrow={copy.support.eyebrow}
          inspect={report as unknown as Record<string, unknown>}
          status={report.status}
          title={copy.support.title}
        >
          <div className={factGridClass}>
            <Fact label={copy.support.safeToShare} value={boolLabel(report.safe_to_share)} />
            <Fact label={copy.support.demoSupport} value={boolLabel(report.demo_support_ready)} />
            <Fact
              label={copy.support.productionSupport}
              value={boolLabel(report.production_support_ready)}
            />
            <Fact
              label={copy.support.objectRetention}
              value={
                report.diagnostics.object_store_worm_retention_enabled
                  ? `${report.diagnostics.object_store_retention_mode} / ${report.diagnostics.object_store_retention_days}d`
                  : copy.support.retentionActionRequired
              }
            />
          </div>
          <div className="mb-3.5 flex min-w-0 flex-wrap gap-2">
            {report.redaction_policy.map((policy) => (
              <span
                className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words dark:border-white/15 dark:bg-white/5"
                key={policy}
              >
                {compactId(policy)}
              </span>
            ))}
          </div>
          <CheckList checks={report.checks} />
        </SettingsPanel>
      )}
    </PanelState>
  );
}

export function PlatformSettingsConsole() {
  const [urlState, setUrlState] = useConsoleUrlState(settingsUrlSchema);
  const ready = useAxisQuery<AxisReadyReport>(READY_ENDPOINT, { parse: parseAxisReadyReport });
  const oidc = useAxisQuery<OidcReadinessReport>(OIDC_READINESS_ENDPOINT, {
    parse: parseOidcReadinessReport,
  });
  const identity = useIdentitySession();
  const deployment = useAxisQuery<DeploymentReadinessReport>(DEPLOYMENT_READINESS_ENDPOINT, {
    parse: parseDeploymentReadinessReport,
  });
  const support = useAxisQuery<SupportDiagnosticsReport>(SUPPORT_DIAGNOSTICS_ENDPOINT, {
    parse: parseSupportDiagnosticsReport,
  });

  const queries = [ready, oidc, identity, deployment, support];
  const sourceLabel = queries.every((query) => query.source === "api")
    ? copy.source.live
    : queries.some((query) => query.source === "loading" && !query.data)
      ? copy.source.loading
      : queries.some((query) => !query.data)
        ? copy.source.required
        : copy.source.stale;

  return (
    <ConsolePage pageKey="settings" sourceLabel={sourceLabel} title={copy.pageTitle}>
      <Tabs
        className="grid min-w-0 gap-1"
        onValueChange={(tab) =>
          setUrlState({ tab: tab as SettingsTab }, { history: "push" })
        }
        value={urlState.tab}
      >
        <TabsList>
          <TabsTrigger value="readiness">{copy.tabs.readiness}</TabsTrigger>
          <TabsTrigger value="identity">{copy.tabs.identity}</TabsTrigger>
          <TabsTrigger value="deployment">{copy.tabs.deployment}</TabsTrigger>
          <TabsTrigger value="support">{copy.tabs.support}</TabsTrigger>
        </TabsList>
        <TabsContent className="grid items-start gap-4 lg:grid-cols-2 [&>*]:min-w-0" value="readiness">
          <ReadyPanel query={ready} />
          <ProductionGatesPanel query={deployment} />
        </TabsContent>
        <TabsContent className="grid items-start gap-4 lg:grid-cols-2 [&>*]:min-w-0" value="identity">
          <OidcPanel query={oidc} />
          <SessionPanel query={identity} />
        </TabsContent>
        <TabsContent value="deployment">
          <DeploymentPanel query={deployment} />
        </TabsContent>
        <TabsContent value="support">
          <SupportPanel query={support} />
        </TabsContent>
      </Tabs>
    </ConsolePage>
  );
}
