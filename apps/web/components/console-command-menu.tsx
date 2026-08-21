"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ExternalLink, Moon, RefreshCw, Sun } from "lucide-react";

import { navIconMap } from "@/components/nav-icons";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import type { ManufacturingAgentRegistry } from "@/lib/agent-demo";
import { axisFetchParsedJson } from "@/lib/axis-api";
import type { ManufacturingConnectorRegistry } from "@/lib/connectors-demo";
import { navGroups } from "@/lib/nav";
import type { OidcConsoleSession } from "@/lib/oidc-session";
import type { PlatformPolicyRegistry } from "@/lib/platform-policies";
import { strings } from "@/lib/strings";
import { buildTenantScopedPath, OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";
import { parseManufacturingAgentRegistry } from "@/lib/runtime-contracts/agents";
import { parseManufacturingConnectorRegistry } from "@/lib/runtime-contracts/connectors";
import { parseManufacturingWorkflowConsole } from "@/lib/runtime-contracts/workflows";
import { parsePlatformPolicyRegistry } from "@/lib/runtime-contracts/policies";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import type { ManufacturingWorkflowConsole } from "@/lib/workflow-demo";
import { useTheme } from "@/providers/theme-provider";

type CommandMenuProps = {
  apiLabel: string;
  onClose: () => void;
  onRefresh: () => void;
  open: boolean;
  tenantId: string | null;
  tenantQueriesEnabled: boolean;
};

type EntityCommand = {
  id: string;
  name: string;
  href: string;
  kind: string;
};

const copy = strings.commandMenu;

/**
 * Best-effort entity index for the search menu: fetched in parallel when the
 * menu opens; endpoints that fail are silently skipped.
 */
async function loadEntityCommands(
  session: OidcConsoleSession | null,
  tenantId: string,
): Promise<EntityCommand[]> {
  const acceptTenant = <T extends { tenant_id: string }>(payload: T | null): T | null =>
    payload?.tenant_id === tenantId ? payload : null;
  const [workflows, agents, policies, connectors] = await Promise.all([
    axisFetchParsedJson<ManufacturingWorkflowConsole>(
      buildTenantScopedPath(`${OPERATIONS_API_PREFIX}/workflows`, tenantId),
      parseManufacturingWorkflowConsole,
      { session },
    ).then(acceptTenant).catch(() => null),
    axisFetchParsedJson<ManufacturingAgentRegistry>(
      buildTenantScopedPath(`${OPERATIONS_API_PREFIX}/agents`, tenantId),
      parseManufacturingAgentRegistry,
      { session },
    ).then(acceptTenant).catch(() => null),
    axisFetchParsedJson<PlatformPolicyRegistry>(
      buildTenantScopedPath("/platform/policies", tenantId),
      parsePlatformPolicyRegistry,
      { session },
    ).then(acceptTenant).catch(() => null),
    axisFetchParsedJson<ManufacturingConnectorRegistry>(
      buildTenantScopedPath(`${OPERATIONS_API_PREFIX}/connectors`, tenantId),
      parseManufacturingConnectorRegistry,
      { session },
    ).then(acceptTenant).catch(() => null),
  ]);

  return [
    ...(workflows?.workflow_runs ?? []).map((run) => ({
      id: run.workflow_id,
      name: run.name,
      href: "/workflows",
      kind: strings.pages.workflows.title,
    })),
    ...(agents?.agents ?? []).map((agent) => ({
      id: agent.agent_id,
      name: agent.name,
      href: "/agents",
      kind: strings.pages.agents.title,
    })),
    ...(policies?.policies ?? []).map((policy) => ({
      id: policy.policy_id,
      name: policy.display_name,
      href: "/policies",
      kind: strings.pages.policies.title,
    })),
    ...(connectors?.connectors ?? []).map((connector) => ({
      id: connector.manifest.connector_id,
      name: connector.manifest.display_name,
      href: "/connectors",
      kind: strings.pages.connectors.title,
    })),
  ];
}

export function ConsoleCommandMenu({
  apiLabel,
  onClose,
  onRefresh,
  open,
  tenantId,
  tenantQueriesEnabled,
}: CommandMenuProps) {
  const router = useRouter();
  const { session } = useOidcConsoleSession();
  const { resolvedTheme, setTheme } = useTheme();
  const [entityIndex, setEntityIndex] = useState<{
    tenantId: string | null;
    commands: EntityCommand[];
  }>({ tenantId: null, commands: [] });

  useEffect(() => {
    if (!open || !tenantQueriesEnabled || tenantId === null) {
      return undefined;
    }

    let cancelled = false;

    void loadEntityCommands(session, tenantId).then((commands) => {
      if (!cancelled) {
        setEntityIndex({ tenantId, commands });
      }
    });

    return () => {
      cancelled = true;
    };
  }, [open, session, tenantId, tenantQueriesEnabled]);

  // Never expose a previous principal's results while a new tenant index is
  // loading or identity has become unresolved.
  const entities =
    tenantQueriesEnabled && entityIndex.tenantId === tenantId
      ? entityIndex.commands
      : [];

  function navigate(href: string) {
    router.push(href);
    onClose();
  }

  return (
    <CommandDialog
      onOpenChange={(next) => {
        if (!next) {
          onClose();
        }
      }}
      open={open}
      title="Console command menu"
    >
      <CommandInput aria-label="Search console commands" placeholder={copy.placeholder} />
      <CommandList>
        <CommandEmpty>{copy.empty}</CommandEmpty>
        {navGroups.map((group) => (
          <CommandGroup heading={group.label} key={group.label}>
            {group.items.map((item) => {
              const Icon = navIconMap[item.icon];

              return (
                <CommandItem
                  key={item.href}
                  onSelect={() => navigate(item.href)}
                  value={`${group.label} ${item.label}`}
                >
                  <Icon className="shrink-0 text-muted" size={15} />
                  <span>{item.label}</span>
                </CommandItem>
              );
            })}
          </CommandGroup>
        ))}
        <CommandSeparator />
        <CommandGroup heading={copy.actionsHeading}>
          <CommandItem
            onSelect={() => {
              onRefresh();
              onClose();
            }}
            value={copy.refresh.label}
          >
            <RefreshCw className="shrink-0 text-muted" size={15} />
            <span>{copy.refresh.label}</span>
            <span className="ml-auto pl-2 text-xs text-muted">{copy.refresh.detail}</span>
          </CommandItem>
          <CommandItem
            onSelect={() => {
              setTheme(resolvedTheme === "dark" ? "light" : "dark");
              onClose();
            }}
            value={copy.toggleTheme.label}
          >
            <Sun className="shrink-0 text-muted dark:hidden" size={15} />
            <Moon className="hidden shrink-0 text-muted dark:block" size={15} />
            <span>{copy.toggleTheme.label}</span>
          </CommandItem>
          <CommandItem
            onSelect={() => {
              window.open(copy.docs.href, "_blank", "noreferrer");
              onClose();
            }}
            value={copy.docs.label}
          >
            <ExternalLink className="shrink-0 text-muted" size={15} />
            <span>{copy.docs.label}</span>
          </CommandItem>
        </CommandGroup>
        {entities.length > 0 ? (
          <>
            <CommandSeparator />
            <CommandGroup heading={copy.entitiesHeading}>
              {entities.map((entity) => (
                <CommandItem
                  key={`${entity.href}:${entity.id}`}
                  onSelect={() => navigate(entity.href)}
                  value={`${entity.name} ${entity.id}`}
                >
                  <span className="min-w-0 truncate">{entity.name}</span>
                  <span className="ml-auto shrink-0 pl-2 text-xs text-muted">{entity.kind}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        ) : null}
      </CommandList>
      <div
        aria-label="Current API status"
        className="flex items-center justify-between border-t border-line px-3.5 py-2 font-mono text-[10.5px] font-medium tracking-[0.16em] text-muted uppercase dark:border-white/10"
      >
        <span>{copy.apiStatus}</span>
        <span className="text-positive">{apiLabel}</span>
      </div>
    </CommandDialog>
  );
}
