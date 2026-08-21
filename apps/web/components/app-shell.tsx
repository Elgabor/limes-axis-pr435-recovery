"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { AxisMark } from "@/components/axis-mark";
import { MobileNavigation } from "@/components/mobile-navigation";
import { navIconMap } from "@/components/nav-icons";
import { SidebarAccount } from "@/components/sidebar-account";
import type { ManufacturingApprovalInbox } from "@/lib/approval-demo";
import { cn } from "@/lib/cn";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { ToastProvider } from "@/components/ui/toast";
import { desktopNavGroups, isNavActive, type NavItem } from "@/lib/nav";
import { useAxisQuery } from "@/lib/use-axis-query";
import { parseManufacturingApprovalInbox } from "@/lib/runtime-contracts/approvals";
import { parseIdentitySessionReadModel } from "@/lib/runtime-contracts/overview";
import {
  buildTenantScopedPath,
  DEMO_TENANT_ID,
  resolveConsoleTenantScope,
  OPERATIONS_API_PREFIX,
} from "@/lib/tenant-scope";
import { ConsoleProvider } from "@/providers/console-provider";
import {
  resolveVocabularyTenantId,
  TenantVocabularyProvider,
} from "@/providers/tenant-vocabulary-provider";

const navItemClass =
  "flex min-h-[44px] items-center gap-2.5 rounded-xl px-3 text-[13px] font-medium text-muted transition-colors hover:bg-signal/8 hover:text-ink";
const navItemActiveClass =
  "bg-tint-100 text-signal shadow-[inset_2px_0_0_rgb(var(--signal))] hover:bg-tint-100 hover:text-signal dark:bg-signal/15 dark:text-ink dark:hover:bg-signal/15 dark:hover:text-ink";

/**
 * Pending-approvals count pill next to the Approvals nav label. Best-effort:
 * while loading or when the API is unavailable it renders nothing.
 */
function ApprovalsBadge({
  identitySource,
  tenantId,
}: {
  identitySource: string;
  tenantId: string | null;
}) {
  const { data } = useAxisQuery<ManufacturingApprovalInbox>(
    buildTenantScopedPath(
      `${OPERATIONS_API_PREFIX}/approvals`,
      tenantId ?? DEMO_TENANT_ID,
    ),
    {
      enabled: identitySource === "api" && tenantId !== null,
      expectedTenantId: tenantId ?? undefined,
      parse: parseManufacturingApprovalInbox,
    },
  );
  const pendingCount =
    data?.approvals?.filter((approval) => approval.status === "pending")
      .length ?? 0;

  if (pendingCount === 0) {
    return null;
  }

  return (
    <span
      aria-label={`${pendingCount} pending approvals`}
      className="ml-auto inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-signal px-1.5 font-mono text-[10px] leading-none font-bold text-white"
    >
      {pendingCount > 9 ? "9+" : pendingCount}
    </span>
  );
}

function NavLink({
  badge,
  item,
  pathname,
  className,
}: {
  badge?: ReactNode;
  item: NavItem;
  pathname: string;
  className?: string;
}) {
  const Icon = navIconMap[item.icon];
  const active = isNavActive(pathname, item.href);

  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={cn(navItemClass, className, active && navItemActiveClass)}
      href={item.href}
    >
      <Icon size={18} />
      <span>{item.label}</span>
      {item.badge === "approvals" ? badge : null}
    </Link>
  );
}

function Navigation({
  badge,
  pathname,
}: {
  badge: ReactNode;
  pathname: string;
}) {
  return (
    <nav
      className="nav-list grid min-h-0 grow content-start gap-1 overflow-y-auto overscroll-contain pr-1 pb-1"
      aria-label="Axis sections"
    >
      {desktopNavGroups.map((group, index) => (
        <section
          aria-label={group.label}
          className="grid gap-1"
          key={group.label}
        >
          <span className={cn("eyebrow px-3", index === 0 ? "pt-1" : "pt-3")}>
            {group.label}
          </span>
          {group.items.map((item) => (
            <NavLink
              badge={badge}
              item={item}
              key={item.href}
              pathname={pathname}
            />
          ))}
        </section>
      ))}
    </nav>
  );
}

/**
 * Shell body. Split from `AppShell` because it reads console context via
 * `useAxisQuery`, and `AppShell` is the component that mounts the provider —
 * calling the hook there runs it outside the provider it is creating.
 */
function ConsoleShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const identity = useAxisQuery<IdentitySessionReadModel>("/identity/session", {
    parse: parseIdentitySessionReadModel,
  });
  const tenantScope = resolveConsoleTenantScope(identity.data);
  const vocabularyTenantId = resolveVocabularyTenantId(pathname, tenantScope.tenantId);
  const approvalsBadge = (
    <ApprovalsBadge
      identitySource={identity.source}
      tenantId={tenantScope.tenantId}
    />
  );

  return (
    <TenantVocabularyProvider
      enabled={identity.source === "api" && vocabularyTenantId !== null}
      tenantId={vocabularyTenantId}
    >
      <>
        <a
          className="fixed top-2 left-2 z-50 -translate-y-20 rounded-lg bg-ink px-4 py-2 text-sm font-medium text-surface shadow-lg transition-transform focus:translate-y-0"
          href="#console-main"
        >
          Skip to main content
        </a>
        <div className="grid min-h-screen grid-cols-1 min-[921px]:grid-cols-[212px_minmax(0,1fr)]">
          <aside
            className="sidebar fixed inset-y-0 left-0 z-12 hidden h-dvh min-h-0 w-[212px] flex-col overflow-hidden border-r border-line bg-surface px-2.5 pt-4 pb-3 min-[921px]:flex dark:border-white/10"
            data-console-sidebar
          >
            <Link
              className="mb-3.5 flex min-h-[44px] items-center gap-3 border-b border-line px-1.5 pb-3.5 dark:border-white/10"
              href="/"
              aria-label="Limes Axis home"
            >
              <AxisMark className="h-[30px] w-[30px] shrink-0 text-ink" />
              <span>
                <span className="font-display block text-base text-ink">
                  Limes Axis
                </span>
                <span className="mt-0.5 block font-mono text-[9px] font-medium tracking-[0.18em] text-muted uppercase">
                  Control plane
                </span>
              </span>
            </Link>
            <Navigation badge={approvalsBadge} pathname={pathname} />
            <SidebarAccount
              identitySession={identity.data}
              identitySessionUnavailable={identity.source === "unavailable"}
              settingsActive={isNavActive(pathname, "/settings")}
            />
          </aside>
          <main
            className="min-w-0 min-[921px]:col-start-2"
            id="console-main"
            tabIndex={-1}
          >
            <MobileNavigation badge={approvalsBadge} pathname={pathname} />
            {children}
          </main>
        </div>
      </>
    </TenantVocabularyProvider>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <ConsoleProvider>
      <ToastProvider>
        <ConsoleShell>{children}</ConsoleShell>
      </ToastProvider>
    </ConsoleProvider>
  );
}
