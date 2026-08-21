"use client";

import Link from "next/link";
import { useState } from "react";

import { AgentRuns } from "@/components/agents/agent-runs";
import { Card } from "@/components/ui/card";
import { DetailGrid, KeyValueRow } from "@/components/ui/detail-grid";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Term } from "@/components/ui/glossary";
import { InspectDrawer } from "@/components/ui/inspect-drawer";
import { EmptyPanel } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  describeAgentPermission,
  formatAgentLabel,
  summarizeAgentBoundary,
  type AgentRegistryEntry,
} from "@/lib/agent-demo";
import { buildAuditEventHref } from "@/lib/audit-demo";
import { strings } from "@/lib/strings";

function ChipList({ items }: { items: string[] }) {
  return (
    <div className="flex min-w-0 flex-wrap gap-2">
      {items.map((item) => (
        <span
          className="inline-flex min-w-0 max-w-full items-center rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words dark:border-white/15 dark:bg-transparent"
          key={item}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function ChipLinkList({ items, href }: { items: string[]; href: string }) {
  return (
    <div className="flex min-w-0 flex-wrap gap-2">
      {items.map((item) => (
        <Link
          className="inline-flex min-w-0 max-w-full items-center rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs text-muted break-words transition-colors hover:border-signal/50 hover:text-signal dark:border-white/15 dark:bg-transparent"
          href={href}
          key={item}
        >
          {item}
        </Link>
      ))}
    </div>
  );
}

function BulletList({ items }: { items: string[] }) {
  return (
    <ul className="mx-0 mt-2 mb-0 grid list-disc gap-2 pl-5 text-sm leading-snug text-muted">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function OverviewTab({ agent }: { agent: AgentRegistryEntry }) {
  return (
    <div className="grid min-w-0 gap-5">
      <div className="grid min-w-0 gap-1.5">
        <Eyebrow>{strings.agents.overview.boundary}</Eyebrow>
        <p className="m-0 max-w-2xl text-sm leading-relaxed text-ink">
          <Term k="autonomy_level" />: {summarizeAgentBoundary(agent.policy_boundary)}
        </p>
      </div>

      <DetailGrid>
        <KeyValueRow label={strings.agents.overview.owner}>{agent.owner_role}</KeyValueRow>
        <KeyValueRow label={strings.agents.overview.modelPolicy}>
          {formatAgentLabel(agent.policy_boundary.model_policy)}
        </KeyValueRow>
      </DetailGrid>

      <div className="grid gap-4 sm:grid-cols-2 [&>*]:min-w-0">
        <section>
          <Eyebrow>{strings.agents.overview.connectedSystems}</Eyebrow>
          <div className="mt-2">
            <ChipList items={agent.connected_systems} />
          </div>
        </section>
        <section>
          <Eyebrow>{strings.agents.overview.dataAccess}</Eyebrow>
          <BulletList items={agent.data_access} />
        </section>
      </div>
    </div>
  );
}

function PermissionsTab({ agent }: { agent: AgentRegistryEntry }) {
  return (
    <div className="grid min-w-0 gap-5">
      <section>
        <Eyebrow>{strings.agents.permissions.required}</Eyebrow>
        <ul className="mx-0 mt-2 mb-0 grid list-none gap-2.5 p-0">
          {agent.policy_boundary.required_permissions.map((permission) => (
            <li className="grid min-w-0 gap-0.5" key={permission}>
              <span className="text-sm text-ink">{describeAgentPermission(permission)}</span>
              <span className="font-mono text-xs break-words text-muted">{permission}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <Eyebrow>{strings.agents.permissions.guardrails}</Eyebrow>
        <BulletList items={agent.policy_boundary.guardrails} />
      </section>

      <div className="grid gap-4 sm:grid-cols-2 [&>*]:min-w-0">
        <section>
          <Eyebrow>{strings.agents.permissions.allowed}</Eyebrow>
          <BulletList items={agent.allowed_actions} />
        </section>
        <section>
          <Eyebrow>{strings.agents.permissions.blocked}</Eyebrow>
          <BulletList items={agent.blocked_actions} />
        </section>
      </div>
    </div>
  );
}

function EvidenceTab({ agent }: { agent: AgentRegistryEntry }) {
  const hasEvidence =
    agent.proposals.length > 0
    || agent.active_workflows.length > 0
    || agent.pending_approvals.length > 0
    || agent.evidence_refs.length > 0;

  if (!hasEvidence) {
    return (
      <EmptyPanel
        detail={strings.agents.evidence.empty}
        title={strings.states.empty.title}
      />
    );
  }

  return (
    <div className="grid min-w-0 gap-5">
      {agent.proposals.length > 0 ? (
        <section className="grid min-w-0 gap-1">
          <Eyebrow>{strings.agents.evidence.proposals}</Eyebrow>
          <p className="m-0 text-sm leading-snug text-muted">
            {strings.agents.evidence.proposalsDetail}
          </p>
          <div className="grid min-w-0 gap-2.5">
            {agent.proposals.map((proposal) => (
              <div
                className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-t border-line/60 py-3 first:border-t-0 dark:border-white/10"
                key={proposal.proposal_id}
              >
                <div>
                  <p className="m-0 font-medium text-ink break-words">{proposal.action}</p>
                  <p className="mx-0 mt-1 mb-0 text-sm leading-snug text-muted break-words">
                    {proposal.approval_required
                      ? strings.agents.evidence.approvalRequired
                      : strings.agents.evidence.noApproval}{" "}
                    / {formatAgentLabel(proposal.status)}
                  </p>
                  <p className="mx-0 mt-1 mb-0 font-mono text-xs leading-snug text-muted break-words">
                    {proposal.proposal_id}
                  </p>
                </div>
                <span
                  className={`status-pill ${
                    proposal.approval_required ? "signal-action-required" : "signal-ready"
                  }`}
                >
                  {proposal.risk_level}
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 [&>*]:min-w-0">
        {agent.active_workflows.length > 0 ? (
          <section>
            <Eyebrow>{strings.agents.evidence.workflows}</Eyebrow>
            <div className="mt-2">
              <ChipLinkList href="/workflows" items={agent.active_workflows} />
            </div>
          </section>
        ) : null}
        {agent.pending_approvals.length > 0 ? (
          <section>
            <Eyebrow>{strings.agents.evidence.approvals}</Eyebrow>
            <div className="mt-2">
              <ChipLinkList href="/approvals" items={agent.pending_approvals} />
            </div>
          </section>
        ) : null}
      </div>

      <section className="grid min-w-0 gap-2">
        <Eyebrow>{strings.agents.evidence.audit}</Eyebrow>
        <DetailGrid>
          <KeyValueRow label={strings.agents.evidence.lastAudit} mono>
            <Link
              className="text-signal underline-offset-2 hover:underline"
              href={buildAuditEventHref(agent.last_audit_event)}
            >
              {agent.last_audit_event}
            </Link>
          </KeyValueRow>
        </DetailGrid>
        {agent.evidence_refs.length > 0 ? <ChipList items={agent.evidence_refs} /> : null}
      </section>
    </div>
  );
}

/**
 * Agent detail pane: plain-language tabs over the registry record. Raw
 * snake_case fields live in the Inspect drawer, never as primary copy.
 */
type AgentDetailTab = "overview" | "permissions" | "runs" | "evidence";

export function AgentDetail({
  activeTab,
  agent,
  domainLabel,
  onRunSelect,
  onTabChange,
  selectedRunId,
}: {
  activeTab?: AgentDetailTab;
  agent: AgentRegistryEntry;
  domainLabel?: string;
  onRunSelect?: (runId: string) => void;
  onTabChange?: (tab: AgentDetailTab) => void;
  selectedRunId?: string;
}) {
  const [internalTab, setInternalTab] = useState<AgentDetailTab>("overview");
  const resolvedTab = activeTab ?? internalTab;

  return (
    <Card className="grid content-start gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid max-w-xl gap-1">
          <Eyebrow>{domainLabel || agent.domain}</Eyebrow>
          <h2 className="font-display m-0 text-xl text-ink">{agent.name}</h2>
          <p className="m-0 text-sm text-muted">{agent.purpose}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <span className="status-pill signal-watch">
            <Term k="autonomy_level">{agent.policy_boundary.autonomy_level}</Term>
          </span>
          <span className="status-pill status-checking">{formatAgentLabel(agent.status)}</span>
        </div>
      </div>

      <Tabs value={resolvedTab} onValueChange={(value) => {
        if (
          value === "overview"
          || value === "permissions"
          || value === "runs"
          || value === "evidence"
        ) {
          if (activeTab === undefined) {
            setInternalTab(value);
          }
          onTabChange?.(value);
        }
      }}>
        <TabsList>
          <TabsTrigger value="overview">{strings.agents.tabs.overview}</TabsTrigger>
          <TabsTrigger value="permissions">{strings.agents.tabs.permissions}</TabsTrigger>
          <TabsTrigger value="runs">{strings.agents.tabs.runs}</TabsTrigger>
          <TabsTrigger value="evidence">{strings.agents.tabs.evidence}</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <OverviewTab agent={agent} />
        </TabsContent>
        <TabsContent value="permissions">
          <PermissionsTab agent={agent} />
        </TabsContent>
        <TabsContent value="runs">
          <AgentRuns
            agentId={agent.agent_id}
            onSelect={onRunSelect}
            selectedRunId={selectedRunId}
          />
        </TabsContent>
        <TabsContent value="evidence">
          <EvidenceTab agent={agent} />
        </TabsContent>
      </Tabs>

      <InspectDrawer
        record={agent}
        title={agent.name}
        trigger={
          <button
            className="inline-flex min-h-6 w-fit cursor-pointer items-center font-mono text-xs text-muted transition-colors duration-200 hover:text-signal"
            type="button"
          >
            {strings.agents.inspect}
          </button>
        }
      />
    </Card>
  );
}
