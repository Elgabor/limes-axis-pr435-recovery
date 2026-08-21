import { ChevronDown } from "lucide-react";
import type { SelectHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

import { controlClassName } from "@/components/ui/input";

/**
 * Native `select` with the OS dropdown arrow suppressed and a Lucide chevron
 * drawn in its place, so filter rows match the rest of the control chrome
 * instead of falling back to platform widget styling.
 */
export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className="relative block min-w-0">
      <select className={cn(controlClassName, "appearance-none pr-8", className)} {...rest}>
        {children}
      </select>
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-muted"
      />
    </span>
  );
}
