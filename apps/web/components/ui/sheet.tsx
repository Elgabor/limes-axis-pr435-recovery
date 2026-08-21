"use client";

import type { ComponentProps } from "react";

import { X } from "lucide-react";
import { Dialog as SheetPrimitive } from "radix-ui";

import { cn } from "@/lib/cn";

/*
 * Side drawer built on Radix Dialog. Defaults to the right edge — the
 * console's Inspect drawers live there.
 */

export const Sheet = SheetPrimitive.Root;
export const SheetTrigger = SheetPrimitive.Trigger;
export const SheetPortal = SheetPrimitive.Portal;
export const SheetClose = SheetPrimitive.Close;

export function SheetOverlay({
  className,
  ...props
}: ComponentProps<typeof SheetPrimitive.Overlay>) {
  return (
    <SheetPrimitive.Overlay
      className={cn("fixed inset-0 z-50 bg-navy/55 backdrop-blur-sm", className)}
      {...props}
    />
  );
}

export type SheetSide = "right" | "left" | "top" | "bottom";

const sideClasses: Record<SheetSide, string> = {
  right: "inset-y-0 right-0 h-full w-full max-w-lg border-l",
  left: "inset-y-0 left-0 h-full w-full max-w-lg border-r",
  top: "inset-x-0 top-0 max-h-[80vh] border-b",
  bottom: "inset-x-0 bottom-0 max-h-[80vh] border-t",
};

export interface SheetContentProps extends ComponentProps<typeof SheetPrimitive.Content> {
  side?: SheetSide;
}

export function SheetContent({ side = "right", className, children, ...props }: SheetContentProps) {
  return (
    <SheetPortal>
      <SheetOverlay />
      <SheetPrimitive.Content
        className={cn(
          "fixed z-50 flex min-w-0 flex-col gap-4 overflow-y-auto border-line bg-surface p-6",
          "shadow-[0_24px_60px_rgb(4_18_46/0.35)] dark:border-white/10 dark:shadow-[0_24px_60px_rgb(0_0_0/0.5)]",
          sideClasses[side],
          className,
        )}
        {...props}
      >
        {children}
        <SheetPrimitive.Close aria-label="Close" className="icon-button absolute! top-4 right-4">
          <X aria-hidden="true" size={16} />
        </SheetPrimitive.Close>
      </SheetPrimitive.Content>
    </SheetPortal>
  );
}

export function SheetHeader({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("flex min-w-0 flex-col gap-1.5 pr-10", className)} {...props} />;
}

export function SheetFooter({ className, ...props }: ComponentProps<"div">) {
  return (
    <div className={cn("mt-auto flex flex-wrap items-center justify-end gap-2", className)} {...props} />
  );
}

export function SheetTitle({ className, ...props }: ComponentProps<typeof SheetPrimitive.Title>) {
  return (
    <SheetPrimitive.Title
      className={cn("font-display m-0 text-lg text-ink", className)}
      {...props}
    />
  );
}

export function SheetDescription({
  className,
  ...props
}: ComponentProps<typeof SheetPrimitive.Description>) {
  return (
    <SheetPrimitive.Description
      className={cn("m-0 text-sm leading-snug text-muted", className)}
      {...props}
    />
  );
}
