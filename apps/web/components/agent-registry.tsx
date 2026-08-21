"use client";

import { Bot } from "lucide-react";

import { AgentDetail } from "@/components/agents/agent-detail";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { FilterBar, type FilterDef } from "@/components/ui/filter-bar";
import { Term } from "@/components/ui/glossary";
import { MasterDetail } from "@/components/ui/master-detail";
import { MetricStrip, type Metric } from "@/components/ui/metric-strip";
import { SourcePill } from "@/components/ui/source-pill";
import { EmptyPanel, ErrorPanel, LoadingPanel } from "@/components/ui/states";
import {
  allAgentFilter,
  filterAgents,
  formatAgentLabel,
  type AgentFilters,
  type ManufacturingAgentRegistry,
} from "@/lib/agent-demo";
import { cn } from "@/lib/cn";
import { enumUrlField, stringUrlField, useConsoleUrlState } from "@/lib/console-url-state";
import { formatContextPath, formatNumber, formatTimestamp } from "@/lib/format";
import {
  platformStatusClass,
  platformStatusLabel,
  type PlatformStatus,
} from "@/lib/platform-overview";
import { deriveSourceState } from "@/lib/source-state";
import { strings } from "@/lib/strings";
import { parseManufacturingAgentRegistry } from "@/lib/runtime-contracts/agents";
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
import { useTenantVocabulary } from "@/providers/tenant-vocabulary-provider";

const AGENTS_ENDPOINT = `${OPERATIONS_API_PREFIX}/agents`;

const defaultFilters: AgentFilters = {
  domain: allAgentFilter,
  autonomyLevel: allAgentFilter,
  status: allAgentFilter,
};
const agentTabs = ["overview", "permissions", "runs", "evidence"] as const;
const agentUrlSchema = {
  domain: stringUrlField("domain", allAgentFilter),
  autonomyLevel: stringUrlField("autonomy", allAgentFilter),
  status: stringUrlField("status", allAgentFilter),
  agentId: stringUrlField("agent_id"),
  tab: enumUrlField("tab", agentTabs, "overview"),
  runId: stringUrlField("run_id"),
};

const metricTones: Record<PlatformStatus, Metric["tone"]> = {
  ready: "ready",
  watch: "watch",
  action_required: "action",
};

/** Traffic-light tone for the list's status dot, derived from the agent status. */
function agentStatusToneClass(status: string): string {
  if (/(blocked|failed|disabled|suspended|retired)/.test(status)) {
    return "text-danger";
  }
  if (/(waiting|pending|proposal_ready|paused)/.test(status)) {
    return "text-warning";
  }
  return "text-positive";
}

function buildFilterDefs(
  registry: ManufacturingAgentRegistry,
  labelDomain: (domain: string) => string,
): FilterDef[] {
  return [
    {
      id: "domain",
      label: "Domain",
      options: [
        { value: allAgentFilter, label: "All domains" },
        ...registry.filter_options.domains.map((domain) => ({
          value: domain,
          label: labelDomain(domain),
        })),
      ],
    },
    {
      id: "autonomy",
      label: "Autonomy",
      options: [
        { value: allAgentFilter, label: "All levels" },
        ...registry.filter_options.autonomy_levels.map((level) => ({
          value: level,
          label: level,
        })),
      ],
    },
    {
      id: "status",
      label: "Status",
      options: [
        { value: allAgentFilter, label: "All statuses" },
        ...registry.filter_options.statuses.map((status) => ({
          value: status,
          label: formatAgentLabel(status),
        })),
      ],
    },
  ];
}

const filterIdToKey: Record<string, keyof AgentFilters> = {
  domain: "domain",
  autonomy: "autonomyLevel",
  status: "status",
};

export function AgentRegistry() {
  const { labelDomain } = useTenantVocabulary();
  const { identity, tenantId, tenantQueriesEnabled } = useConsoleTenantScope();
  const agentsPath = buildTenantScopedPath(AGENTS_ENDPOINT, tenantId ?? DEMO_TENANT_ID);
  const {
    data: registry,
    errorRequestId: registryErrorRequestId,
    source,
  } = useAxisQuery<ManufacturingAgentRegistry>(agentsPath, {
    enabled: tenantQueriesEnabled,
    expectedTenantId: tenantId ?? undefined,
    parse: parseManufacturingAgentRegistry,
  });
  const [urlState, setUrlState] = useConsoleUrlState(agentUrlSchema);
  const filters: AgentFilters = registry
    ? {
        domain: urlState.domain === allAgentFilter
          || registry.filter_options.domains.includes(urlState.domain)
          ? urlState.domain
          : allAgentFilter,
        autonomyLevel: urlState.autonomyLevel === allAgentFilter
          || registry.filter_options.autonomy_levels.includes(urlState.autonomyLevel)
          ? urlState.autonomyLevel
          : allAgentFilter,
        status: urlState.status === allAgentFilter
          || registry.filter_options.statuses.includes(urlState.status)
          ? urlState.status
          : allAgentFilter,
      }
    : defaultFilters;

  const filteredAgents = registry ? filterAgents(registry, filters) : [];

  if (identity.source === "unavailable") {
    return (
      <ErrorPanel
        detail="The agent registry is not loaded until the current actor and tenant are verified."
        endpoint={IDENTITY_SESSION_ENDPOINT}
        reference={identity.errorRequestId ?? undefined}
        title="Identity API unavailable"
      />
    );
  }

  if (identity.source === "api" && !tenantId) {
    return (
      <ErrorPanel
        detail="The authenticated identity response does not contain a tenant. Axis will not fall back to demo agent records."
        endpoint={IDENTITY_SESSION_ENDPOINT}
        title="Authenticated tenant missing"
      />
    );
  }

  if (!registry) {
    if (source === "loading") {
      return (
        <div aria-label="Loading agent API" className="grid gap-4">
          <LoadingPanel layout="metrics" rows={3} />
          <MasterDetail
            detail={<LoadingPanel layout="detail" />}
            list={<LoadingPanel rows={4} />}
          />
        </div>
      );
    }

    return (
      <ErrorPanel
        detail={strings.agents.error.detail}
        endpoint={agentsPath}
        reference={registryErrorRequestId ?? undefined}
        title={strings.agents.error.title}
      />
    );
  }

  if (registry.agents.length === 0) {
    return (
      <EmptyPanel
        detail={strings.agents.empty.detail}
        icon={Bot}
        title={strings.agents.empty.title}
      />
    );
  }

  const selectedAgent = urlState.agentId
    ? filteredAgents.find((agent) => agent.agent_id === urlState.agentId)
    : filteredAgents[0];

  const metrics: Metric[] = registry.metrics.map((metric) => ({
    label: metric.label,
    value: metric.value,
    detail: metric.detail,
    tone: metricTones[metric.status],
  }));

  return (
    <div className="grid gap-4">
      <div
        aria-label="Agent source and registry status"
        className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-2"
      >
        <p className="m-0 min-w-0 text-sm break-words text-muted">
          {formatContextPath(registry.plant_name, registry.scenario, registry.tenant_id)}
        </p>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <SourcePill
            state={deriveSourceState(source, Boolean(registry), registry.provenance)}
            subject="agent registry"
          />
          <span className={`status-pill ${platformStatusClass(registry.registry_status)}`}>
            <Bot size={15} />
            {platformStatusLabel(registry.registry_status)}
          </span>
          <span className="font-mono text-xs text-muted">
            {formatTimestamp(registry.as_of)}
          </span>
        </div>
      </div>

      {metrics.length > 0 ? <MetricStrip metrics={metrics} /> : null}

      <FilterBar
        filters={buildFilterDefs(registry, labelDomain)}
        values={{
          domain: filters.domain,
          autonomy: filters.autonomyLevel,
          status: filters.status,
        }}
        onChange={(id, value) => {
          const key = filterIdToKey[id];
          if (key) {
            setUrlState({ [key]: value, agentId: "", runId: "" });
          }
        }}
        onReset={() => setUrlState({ ...defaultFilters, agentId: "", runId: "" })}
      />

      {urlState.agentId && !selectedAgent ? (
        <EmptyPanel
          detail={strings.states.requestedRecord.detail}
          title={strings.states.requestedRecord.title}
        />
      ) : filteredAgents.length === 0 || !selectedAgent ? (
        <EmptyPanel
          action={{
            label: strings.agents.noMatch.reset,
            onClick: () => setUrlState({ ...defaultFilters, agentId: "", runId: "" }),
          }}
          detail={strings.agents.noMatch.detail}
          title={strings.agents.noMatch.title}
        />
      ) : (
        <MasterDetail
          detail={
            <AgentDetail
              activeTab={urlState.tab}
              agent={selectedAgent}
              domainLabel={labelDomain(selectedAgent.domain)}
              onRunSelect={(runId) => setUrlState({ runId })}
              onTabChange={(tab) => setUrlState({ tab })}
              selectedRunId={urlState.runId}
            />
          }
          list={
            <Card className="grid content-start gap-4">
              <div className="grid gap-1">
                <Eyebrow>{strings.agents.list.eyebrow}</Eyebrow>
                <h2 className="font-display m-0 text-xl text-ink">
                  {formatNumber(filteredAgents.length)} visible
                </h2>
              </div>
              <div className="grid gap-2">
                {filteredAgents.map((agent) => {
                  const isSelected = agent.agent_id === selectedAgent.agent_id;

                  return (
                    <button
                      aria-pressed={isSelected}
                      className={cn(
                        "flex w-full cursor-pointer items-start justify-between gap-3 rounded-2xl border px-4 py-3 text-left transition-colors",
                        isSelected
                          ? "border-signal/60 bg-tint-100 dark:bg-signal/15"
                          : "border-line bg-transparent hover:border-signal/40 hover:bg-tint-50 dark:border-white/10 dark:hover:bg-white/5",
                      )}
                      key={agent.agent_id}
                      onClick={() => setUrlState({ agentId: agent.agent_id, runId: "" })}
                      type="button"
                    >
                      <span className="grid min-w-0 gap-0.5">
                        <span className="text-sm font-medium text-ink">{agent.name}</span>
                        <span className="text-xs text-muted">{labelDomain(agent.domain)}</span>
                        <span className="flex items-center gap-1.5 text-xs text-muted">
                          <span
                            aria-hidden="true"
                            className={cn("status-dot", agentStatusToneClass(agent.status))}
                          />
                          {formatAgentLabel(agent.status)}
                        </span>
                      </span>
                      <span className="status-pill signal-watch">
                        <Term k="autonomy_level">
                          {agent.policy_boundary.autonomy_level}
                        </Term>
                      </span>
                    </button>
                  );
                })}
              </div>
            </Card>
          }
        />
      )}

      {registry.registry_notes.length > 0 ? (
        <Card className="grid content-start gap-3">
          <Eyebrow>Registry Notes</Eyebrow>
          <div className="grid gap-2">
            {registry.registry_notes.map((note) => (
              <p className="m-0 text-sm text-muted" key={note}>
                {note}
              </p>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  );
}
