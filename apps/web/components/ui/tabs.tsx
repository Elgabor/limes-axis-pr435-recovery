"use client";

import type { ComponentProps } from "react";

import { Tabs as TabsPrimitive } from "radix-ui";

import { cn } from "@/lib/cn";

export const Tabs = TabsPrimitive.Root;

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
