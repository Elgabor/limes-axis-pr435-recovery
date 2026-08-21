"use client";

import { HelpCircleIcon, Settings01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { AccountPanel } from "@/components/topbar/account-panel";
import { HelpPanel } from "@/components/topbar/help-panel";
import { popoverClass, sidebarPopoverClass } from "@/components/topbar/panel-chrome";
import { cn } from "@/lib/cn";
import { announcePopoverOpened, useExclusivePopover } from "@/lib/console-popovers";
import { operatorInitials } from "@/lib/identity-format";
import type { IdentitySessionReadModel } from "@/lib/platform-overview";
import { strings } from "@/lib/strings";
import { useOidcConsoleSession } from "@/lib/use-oidc-session";

type SidebarPanel = "account" | "help";

const footerRowClass =
  "flex min-h-[38px] w-full items-center gap-2.5 rounded-xl px-3 text-[13px] font-medium text-muted transition-colors hover:bg-signal/8 hover:text-ink";

/**
 * Identity and configuration live at the foot of the navigation rail rather
 * than the top-right corner: they are "who am I / how is this set up", which
 * belongs with navigation, while the topbar keeps state that changes as you
 * work (API health, provenance, refresh, search, notifications).
 */
export function SidebarAccount({
  identitySession,
  identitySessionUnavailable,
  settingsActive,
  variant = "rail",
}: {
  identitySession: IdentitySessionReadModel | null;
  identitySessionUnavailable: boolean;
  settingsActive: boolean;
  /**
   * `rail` is the sidebar footer. `compact` is the same controls as icon
   * buttons for viewports below 921px, where the sidebar is not rendered at all
   * and these would otherwise be unreachable.
   */
  variant?: "rail" | "compact";
}) {
  const { session } = useOidcConsoleSession();
  const [activePanel, setActivePanel] = useState<SidebarPanel | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (activePanel === null) {
      return;
    }

    function onPointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setActivePanel(null);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setActivePanel(null);
      }
    }

    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [activePanel]);

  useExclusivePopover(
    "sidebar-account",
    useCallback(() => setActivePanel(null), []),
  );

  const actorId = identitySession?.actor_id ?? session?.actorId ?? null;
  const toggle = (panel: SidebarPanel) =>
    setActivePanel((current) => {
      const next = current === panel ? null : panel;
      if (next !== null) {
        announcePopoverOpened("sidebar-account");
      }
      return next;
    });
  const panelClass = variant === "rail" ? sidebarPopoverClass : popoverClass;

  if (variant === "compact") {
    return (
      <div className="relative flex items-center gap-1" ref={containerRef}>
        <Link
          aria-current={settingsActive ? "page" : undefined}
          aria-label={strings.pages.settings.title}
          className={cn("icon-button", settingsActive && "icon-button-active")}
          href="/settings"
        >
          <HugeiconsIcon icon={Settings01Icon} size={17} strokeWidth={1.8} />
        </Link>
        <button
          aria-expanded={activePanel === "help"}
          aria-label="Open platform help"
          className={cn("icon-button", activePanel === "help" && "icon-button-active")}
          onClick={() => toggle("help")}
          title="Open platform help"
          type="button"
        >
          <HugeiconsIcon icon={HelpCircleIcon} size={17} strokeWidth={1.8} />
        </button>
        <button
          aria-expanded={activePanel === "account"}
          aria-label="Open operator account"
          className={cn(
            "grid size-[34px] shrink-0 cursor-pointer place-items-center rounded-full border border-line bg-surface font-mono text-[11px] font-bold text-ink/80 transition-colors hover:border-signal/40 hover:bg-signal/10 dark:border-white/20 dark:bg-white/5",
            activePanel === "account" && "border-signal/40 bg-signal/10",
          )}
          data-operator-initials
          onClick={() => toggle("account")}
          title="Open operator account"
          type="button"
        >
          {operatorInitials(actorId ?? undefined)}
        </button>
        {activePanel === "help" ? <HelpPanel className={panelClass} /> : null}
        {activePanel === "account" ? (
          <AccountPanel
            className={panelClass}
            identitySession={identitySession}
            identitySessionUnavailable={identitySessionUnavailable}
          />
        ) : null}
      </div>
    );
  }

  return (
    <div
      className="relative mt-2 grid gap-1 border-t border-line pt-2 dark:border-white/10"
      ref={containerRef}
    >
      <Link
        aria-current={settingsActive ? "page" : undefined}
        className={cn(
          footerRowClass,
          settingsActive && "bg-tint-100 text-signal dark:bg-signal/15 dark:text-ink",
        )}
        href="/settings"
      >
        <HugeiconsIcon icon={Settings01Icon} size={18} strokeWidth={1.8} />
        <span>{strings.pages.settings.title}</span>
      </Link>

      <button
        aria-expanded={activePanel === "help"}
        aria-label="Open platform help"
        className={cn(footerRowClass, activePanel === "help" && "bg-signal/10 text-ink")}
        onClick={() => toggle("help")}
        title="Open platform help"
        type="button"
      >
        <HugeiconsIcon icon={HelpCircleIcon} size={18} strokeWidth={1.8} />
        <span>{strings.nav.help}</span>
      </button>

      <button
        aria-expanded={activePanel === "account"}
        aria-label="Open operator account"
        className={cn(
          "mt-0.5 flex min-h-[46px] w-full cursor-pointer items-center gap-2.5 rounded-xl border border-line px-2 text-left transition-colors hover:border-signal/40 hover:bg-signal/8 dark:border-white/15",
          activePanel === "account" && "border-signal/40 bg-signal/10",
        )}
        onClick={() => toggle("account")}
        title="Open operator account"
        type="button"
      >
        <span
          aria-hidden="true"
          className="grid size-[28px] shrink-0 place-items-center rounded-full bg-tint-100 font-mono text-[11px] font-bold text-signal dark:bg-signal/20 dark:text-white"
          data-operator-initials
        >
          {operatorInitials(actorId ?? undefined)}
        </span>
        <span className="grid min-w-0">
          <span className="truncate text-[12px] font-semibold text-ink">
            {actorId ?? strings.nav.signedOut}
          </span>
          <span className="truncate text-[10.5px] text-muted">
            {identitySession?.tenant_id ?? strings.nav.noTenant}
          </span>
        </span>
      </button>

      {activePanel === "help" ? <HelpPanel className={panelClass} /> : null}
      {activePanel === "account" ? (
        <AccountPanel
          className={panelClass}
          identitySession={identitySession}
          identitySessionUnavailable={identitySessionUnavailable}
        />
      ) : null}
    </div>
  );
}
