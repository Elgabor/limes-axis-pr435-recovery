import type { HTMLAttributes, ReactNode, TableHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export interface DataTableProps extends TableHTMLAttributes<HTMLTableElement> {
  /** Minimum table width; the wrapper scrolls horizontally beyond it. */
  minWidth?: number;
  wrapperProps?: HTMLAttributes<HTMLDivElement>;
  children: ReactNode;
}

/**
 * Styled table wrapper. The wrapper always keeps `overflow-x: auto` and the
 * table a `min-width`, so wide tables scroll inside the card instead of
 * overflowing the page (the no-horizontal-overflow e2e depends on this).
 */
export function DataTable({
  minWidth = 640,
  wrapperProps,
  className,
  children,
  ...rest
}: DataTableProps) {
  return (
    <div
      {...wrapperProps}
      className={cn(
        "overflow-x-auto rounded-2xl border border-line bg-surface dark:border-white/10 dark:bg-white/5",
        wrapperProps?.className,
      )}
    >
      <table
        className={cn(
          "w-full border-collapse text-left text-sm text-ink",
          // Headers are muted, not Signal: an accent-blue header on every column
          // of every table made each list shout and diluted the accent elsewhere.
          "[&_th]:border-b [&_th]:border-line [&_th]:px-4 [&_th]:py-3 [&_th]:font-mono [&_th]:text-[11px] [&_th]:font-medium [&_th]:tracking-[0.12em] [&_th]:uppercase [&_th]:text-muted [&_th]:dark:border-white/10",
          // Tabular figures stop numeric columns re-flowing as digits change.
          "[&_td]:border-b [&_td]:border-line/60 [&_td]:px-4 [&_td]:py-3 [&_td]:align-top [&_td]:tabular-nums [&_td]:dark:border-white/6",
          "[&_tbody_tr:last-child_td]:border-b-0",
          className,
        )}
        style={{ minWidth }}
        {...rest}
      >
        {children}
      </table>
    </div>
  );
}
