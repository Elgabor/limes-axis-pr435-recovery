"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { Menu as MenuIcon } from "lucide-react";

import { AxisMark } from "@/components/axis-mark";
import { navIconMap } from "@/components/nav-icons";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { cn } from "@/lib/cn";
import { isNavActive, navGroups, resolveNavItem } from "@/lib/nav";

const drawerLinkClass =
  "flex min-h-[44px] items-center gap-2.5 rounded-xl px-3 text-[13px] font-medium text-muted transition-colors hover:bg-signal/8 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal";
const drawerLinkActiveClass =
  "bg-tint-100 text-signal shadow-[inset_2px_0_0_rgb(var(--signal))] hover:bg-tint-100 hover:text-signal dark:bg-signal/15 dark:text-ink dark:hover:bg-signal/15 dark:hover:text-ink";

/**
 * Compact shell navigation for viewports where the desktop rail is hidden.
 * The closed state always names the current section; the Sheet exposes the
 * same grouped information architecture as command search, including
 * Settings. Radix owns focus trapping, Escape handling and trigger focus
 * restoration.
 */
export function MobileNavigation({
  badge,
  pathname,
}: {
  badge: ReactNode;
  pathname: string;
}) {
  const [open, setOpen] = useState(false);
  const currentItem = resolveNavItem(pathname);
  const currentGroup = currentItem
    ? navGroups.find((group) => group.items.some((item) => item.href === currentItem.href))
    : null;
  const currentLabel = currentItem?.label ?? "Console";

  return (
    <nav
      aria-label={`Mobile Axis navigation. Current section: ${currentLabel}`}
      className="sticky top-0 z-20 block h-14 border-b border-line bg-surface/95 px-3 backdrop-blur-xl min-[921px]:hidden dark:border-white/10"
      data-mobile-navigation
    >
      <div className="flex h-full min-w-0 items-center gap-2.5">
        <Link
          aria-current={currentItem?.href === "/" ? "page" : undefined}
          aria-label="Limes Axis overview"
          className="grid size-11 shrink-0 place-items-center rounded-xl text-ink transition-colors hover:bg-signal/8 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal"
          href="/"
        >
          <AxisMark className="size-8" />
        </Link>

        <div className="grid min-w-0 flex-1 leading-tight">
          <span className="truncate font-mono text-[9px] font-semibold tracking-[0.16em] text-muted uppercase">
            {currentGroup?.label ?? "Limes Axis"}
          </span>
          <span
            className="truncate text-sm font-semibold text-ink"
            data-mobile-current-section
          >
            {currentLabel}
          </span>
        </div>

        <Sheet onOpenChange={setOpen} open={open}>
          <SheetTrigger asChild>
            <button
              aria-label={`Open navigation. Current section: ${currentLabel}`}
              className="inline-flex min-h-11 shrink-0 cursor-pointer items-center gap-2 rounded-xl border border-line bg-surface px-3 text-sm font-semibold text-ink transition-colors hover:border-signal/40 hover:bg-signal/8 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal dark:border-white/15"
              data-mobile-navigation-trigger
              type="button"
            >
              <MenuIcon aria-hidden="true" size={18} />
              <span>Menu</span>
            </button>
          </SheetTrigger>
          <SheetContent className="w-[88vw]! max-w-[22rem]! gap-5 p-4!" side="left">
            <SheetHeader>
              <SheetTitle>Navigate Axis</SheetTitle>
              <SheetDescription>
                Current section: {currentLabel}. Choose another console area.
              </SheetDescription>
            </SheetHeader>

            <nav
              aria-label="All Axis sections"
              className="grid min-h-0 grow content-start gap-1 overflow-y-auto overscroll-contain pr-1 pb-2"
            >
              {navGroups.map((group, index) => (
                <section aria-label={group.label} className="grid gap-1" key={group.label}>
                  <span className={cn("eyebrow px-3", index === 0 ? "pt-1" : "pt-3")}>
                    {group.label}
                  </span>
                  {group.items.map((item) => {
                    const Icon = navIconMap[item.icon];
                    const active = isNavActive(pathname, item.href);

                    return (
                      <Link
                        aria-current={active ? "page" : undefined}
                        className={cn(drawerLinkClass, active && drawerLinkActiveClass)}
                        href={item.href}
                        key={item.href}
                        onClick={() => setOpen(false)}
                      >
                        <Icon size={18} />
                        <span>{item.label}</span>
                        {item.badge === "approvals" ? badge : null}
                      </Link>
                    );
                  })}
                </section>
              ))}
            </nav>
          </SheetContent>
        </Sheet>
      </div>
    </nav>
  );
}
