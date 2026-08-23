"use client";

import type { ComponentProps } from "react";

import { Tabs as TabsPrimitive } from "radix-ui";

import { cn } from "@/lib/cn";

export function Tabs({ className, ...props }: ComponentProps<typeof TabsPrimitive.Root>) {
  return (
    <TabsPrimitive.Root
      className={cn(
        // Tabbed surfaces are usually grid/flex children. Without min-width:0
        // the strip's intrinsic width inflates the parent track and pushes the
        // page horizontally on narrow viewports; in plain block flow this is a
        // no-op. The list itself scrolls (TabsList), nothing is clipped.
        "min-w-0",
        className,
      )}
      {...props}
    />
  );
}

export function TabsList({ className, ...props }: ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn(
        "inline-flex max-w-full items-center gap-1 overflow-x-auto rounded-full border border-line bg-surface p-1",
        "dark:border-white/10 dark:bg-white/5",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({ className, ...props }: ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-full border border-transparent px-3.5 py-1.5",
        "text-sm font-medium whitespace-nowrap text-muted transition-colors duration-200 select-none",
        "hover:text-ink disabled:cursor-not-allowed disabled:opacity-55",
        "data-[state=active]:border-signal/25 data-[state=active]:bg-tint-100 data-[state=active]:text-signal",
        className,
      )}
      // Roving-focus arrow navigation moves focus programmatically, and
      // browsers do not follow programmatic focus with scroll-into-view — so
      // on narrow viewports the newly focused tab can stay clipped outside
      // the scrolling strip. No-op whenever the tab is already visible.
      onFocus={(event) =>
        event.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" })
      }
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      className={cn(
        "mt-3 min-w-0 focus-visible:rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal",
        className,
      )}
      {...props}
    />
  );
}
