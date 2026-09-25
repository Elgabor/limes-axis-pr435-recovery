"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Bell, RefreshCw, Search } from "lucide-react";

import { ConsoleCommandMenu } from "@/components/console-command-menu";
import { announcePopoverOpened, useExclusivePopover } from "@/lib/console-popovers";
import { SidebarAccount } from "@/components/sidebar-account";
import { DemoBadge } from "@/components/demo-badge";
import { ThemeToggle } from "@/components/theme-toggle";
import { NotificationPanel } from "@/components/topbar/notification-panel";
import { apiStatusClass } from "@/lib/identity-format";
import { isNavActive } from "@/lib/nav";
import type {
  ManufacturingNotificationCenter,
} from "@/lib/platform-overview";
import { useAxisQuery } from "@/lib/use-axis-query";
import {
  parseManufacturingNotificationCenter,
} from "@/lib/runtime-contracts/overview";
import {
  buildTenantScopedPath,
  DEMO_TENANT_ID,
  resolveConsoleTenantScope,
  OPERATIONS_API_PREFIX,
} from "@/lib/tenant-scope";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";
import { useIdentitySession } from "@/lib/use-identity-session";
import { useConsole } from "@/providers/console-provider";

type TopbarPanel = "notifications" | "help" | "account" | null;

export function ConsoleTopbar({
  sourceLabel,
}: {
  /**
   * Pre-formatted status text from callers that pre-date `SourcePill`
   * (`ConsolePage`'s prop is a plain string, so the tone can't be derived
   * from a real `source`/`hasData` pair here). Rendered in the neutral
   * "checking" tone rather than a hardcoded success green, so a caller
   * surfacing an unavailable API doesn't read as a false-positive success.
   */
  sourceLabel?: string;
}) {
  const pathname = usePathname();
  const { apiStatus, triggerRefresh } = useConsole();
  const [commandMenuOpen, setCommandMenuOpen] = useState(false);
  const [activePanel, setActivePanel] = useState<TopbarPanel>(null);
  useExclusivePopover(
    "topbar",
    useCallback(() => setActivePanel(null), []),
  );
  const { session } = useOidcConsoleSession();
  const identity = useIdentitySession();
  const identitySession = identity.data;
  const identitySessionSource = identity.source;
  const tenantScope = resolveConsoleTenantScope(identitySession);
  const tenantId = tenantScope.tenantId;
  const notificationsEnabled = identitySessionSource === "api" && tenantId !== null;
  const {
    data: notificationCenter,
    source: notificationCenterSource,
  } = useAxisQuery<ManufacturingNotificationCenter>(
    buildTenantScopedPath(
      `${OPERATIONS_API_PREFIX}/notifications`,
      tenantId ?? DEMO_TENANT_ID,
    ),
    {
      enabled: notificationsEnabled,
      expectedTenantId: tenantId ?? undefined,
      parse: parseManufacturingNotificationCenter,
    },
  );
  // A disabled query deliberately reports `loading`, because it has never
  // attempted transport. Do not expose that internal sentinel forever when
  // identity already failed or supplied no usable tenant.
  const effectiveNotificationCenterSource = notificationsEnabled
    ? notificationCenterSource
    : identitySessionSource === "loading"
      ? "loading"
      : "unavailable";

  const notificationCount = notificationCenter?.unread_count ?? 0;
  const notificationBadge = notificationCount > 9 ? "9+" : notificationCount;

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const isTextInput =
        target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable;

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setActivePanel(null);
        setCommandMenuOpen(true);
        return;
      }

      if (!isTextInput && event.key === "/") {
        event.preventDefault();
        setActivePanel(null);
        setCommandMenuOpen(true);
      }

      if (event.key === "Escape") {
        setActivePanel(null);
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <header
      className="ops-topbar sticky top-14 isolate z-10 -mx-4 flex min-h-[62px] flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface/80 px-4 py-2 backdrop-blur-xl max-sm:grid max-sm:min-h-0 max-sm:grid-cols-[minmax(0,1fr)_auto] max-sm:gap-2 max-sm:py-1.5 sm:-mx-6 sm:px-6 min-[921px]:top-0 dark:border-white/10"
      aria-label="Console status bar"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2 max-sm:flex-nowrap max-sm:overflow-x-auto max-sm:pb-px max-sm:[&_.status-pill]:px-2 max-sm:[&_.status-pill]:text-[11px] max-sm:[&_.status-pill]:whitespace-nowrap sm:ml-auto sm:justify-end">
        <span className={`status-pill ${apiStatusClass(apiStatus.state)}`} title={apiStatus.detail}>
          <span aria-hidden="true" className={`status-dot ${apiStatusClass(apiStatus.state)}`} />
          API {apiStatus.label}
        </span>
        <DemoBadge
          enabled={tenantScope.mode === "demo"}
          tenantId={tenantId ?? DEMO_TENANT_ID}
        />
        {sourceLabel ? (
          <span className="status-pill status-checking">{sourceLabel}</span>
        ) : null}
      </div>
      <div
        className="ops-toolbar-icons flex min-w-0 flex-wrap items-center justify-end gap-2 max-sm:flex-nowrap max-sm:gap-0.5"
        aria-label="Utility actions"
      >
        <button
          className="icon-button"
          type="button"
          aria-label="Refresh state"
          title="Refresh state"
          onClick={triggerRefresh}
        >
          <RefreshCw size={17} />
        </button>
        <ThemeToggle />
        <button
          className="icon-button"
          type="button"
          aria-label="Search console"
          title="Search console"
          onClick={() => {
            setActivePanel(null);
            setCommandMenuOpen(true);
          }}
        >
          <Search size={17} />
        </button>
        <button
          className={`icon-button${activePanel === "notifications" ? " icon-button-active" : ""}`}
          type="button"
          aria-expanded={activePanel === "notifications"}
          aria-label="Open notifications"
          title="Open notifications"
          onClick={() =>
            setActivePanel((current) => {
              const next = current === "notifications" ? null : "notifications";
              if (next !== null) {
                announcePopoverOpened("topbar");
              }
              return next;
            })
          }
        >
          <Bell size={17} />
          {notificationCount > 0 ? (
            <span className="absolute top-1 right-1 grid h-[14px] min-w-[14px] place-items-center rounded-full border border-surface bg-positive px-0.5 font-mono text-[9px] leading-none font-extrabold text-white">
              {notificationBadge}
            </span>
          ) : null}
        </button>
        <span
          aria-hidden="true"
          className="mx-0.5 h-[22px] w-px shrink-0 bg-line min-[921px]:hidden dark:bg-white/15"
        />
        <div className="min-[921px]:hidden">
          <SidebarAccount
            identitySession={identitySession ?? null}
            identitySessionUnavailable={identitySessionSource === "unavailable"}
            settingsActive={isNavActive(pathname, "/settings")}
            variant="compact"
          />
        </div>
        {activePanel === "notifications" ? (
          <NotificationPanel
            center={notificationCenter}
            identitySession={identitySession}
            onAcknowledged={triggerRefresh}
            session={session}
            source={effectiveNotificationCenterSource}
          />
        ) : null}
      </div>
      <ConsoleCommandMenu
        apiLabel={apiStatus.label}
        onClose={() => setCommandMenuOpen(false)}
        onRefresh={triggerRefresh}
        open={commandMenuOpen}
        tenantId={tenantId}
        tenantQueriesEnabled={notificationsEnabled}
      />
    </header>
  );
}
