"use client";

/* Shared popover chrome. The `.topbar-popover-header` / `.notification-row`
 * class names stay as e2e markers; all styling is Tailwind on tokens. */
const popoverSurfaceClass =
  "z-70 grid max-h-[calc(100vh-94px)] w-[min(360px,calc(100vw-32px))] gap-3 overflow-y-auto overscroll-contain rounded-2xl border border-line bg-surface p-3 shadow-[0_26px_80px_rgb(4_18_46/0.28)] dark:border-white/10";

/** Anchored under the topbar's utility row, opening down and to the left. */
export const popoverClass =
  `absolute top-[calc(100%+10px)] right-4 sm:right-6 ${popoverSurfaceClass}`;

/**
 * Anchored to the sidebar footer, opening upward and to the right so the panel
 * clears the 212px rail instead of being clipped by it.
 */
export const sidebarPopoverClass =
  `absolute bottom-[calc(100%+10px)] left-1 ${popoverSurfaceClass}`;
export const popoverRowClass =
  "grid min-w-0 grid-cols-[18px_minmax(0,1fr)] items-start gap-2.5 rounded-xl border border-line/60 bg-ink/3 p-2.5 text-ink/80 dark:border-white/10 dark:bg-white/4 " +
  "[&_strong]:block [&_strong]:min-w-0 [&_strong]:text-xs [&_strong]:leading-tight [&_strong]:break-words [&_strong]:text-ink " +
  "[&_small]:mt-0.5 [&_small]:block [&_small]:text-[11px] [&_small]:leading-snug [&_small]:text-muted [&>svg]:text-positive";
export const popoverRowLinkClass =
  "transition-colors hover:border-signal/30 hover:bg-signal/10";
export const popoverLinkClass =
  "inline-flex min-h-[34px] items-center justify-center rounded-xl border border-line text-xs font-semibold text-signal transition-colors hover:border-signal/40 hover:bg-signal/10 dark:border-white/15";
export const commandClass =
  "inline-flex min-h-9 w-full min-w-0 items-center justify-center gap-2 rounded-full bg-navy px-4 text-sm font-medium text-white transition-colors select-none hover:bg-signal dark:bg-signal dark:hover:bg-white dark:hover:text-navy";
export const commandSecondaryClass =
  "inline-flex min-h-9 w-full min-w-0 items-center justify-center gap-2 rounded-full border border-line bg-transparent px-4 text-sm font-medium text-ink transition-colors select-none hover:border-signal/50 hover:text-signal dark:border-white/20";
export const tagClass =
  "inline-flex max-w-full min-w-0 items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 font-mono text-xs break-words text-muted dark:border-white/15 dark:bg-white/5";

export function PopoverHeader({
  label,
  children,
}: {
  label: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="topbar-popover-header flex items-center justify-between gap-3">
      <p className="eyebrow m-0">{label}</p>
      {children}
    </div>
  );
}
