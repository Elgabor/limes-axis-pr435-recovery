import { Loader2 } from "lucide-react";
import { Slot } from "radix-ui";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "secondary" | "destructive" | "ghost";
/** `md` (36px) is the console control height, shared with Input and Select. */
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Render as the single child element (e.g. a `next/link`) instead of a `button`. */
  asChild?: boolean;
  /**
   * Shows a spinner and blocks further clicks. Use for any action that hits
   * the API so a slow request cannot be submitted twice.
   */
  loading?: boolean;
  children: ReactNode;
}

const base = cn(
  "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg font-medium whitespace-nowrap",
  "transition-colors duration-150 select-none",
  "disabled:pointer-events-none disabled:opacity-50",
  "[&_svg]:shrink-0",
);

const sizes: Record<ButtonSize, string> = {
  sm: "h-8 gap-1 px-2.5 text-[13px] [&_svg]:size-3.5",
  md: "h-9 px-3.5 text-sm [&_svg]:size-4",
  lg: "h-10 px-5 text-sm [&_svg]:size-4",
};

/**
 * Hover shifts the same hue rather than switching color, and no variant casts
 * a glow — a console button should read as a control, not a landing-page CTA.
 */
const variants: Record<ButtonVariant, string> = {
  primary: cn(
    "bg-navy text-white hover:bg-navy/88 active:bg-navy/80",
    "dark:bg-signal dark:text-white dark:hover:bg-signal/85",
  ),
  secondary: cn(
    "border border-line bg-surface text-ink hover:border-ink/20 hover:bg-ink/4",
    "dark:border-white/15 dark:bg-white/5 dark:hover:border-white/25 dark:hover:bg-white/10",
  ),
  destructive: cn(
    "border border-danger/40 bg-surface text-danger hover:border-danger hover:bg-danger/8",
    "dark:border-danger/50 dark:bg-transparent dark:hover:bg-danger/12",
  ),
  ghost: cn("text-ink hover:bg-ink/6", "dark:hover:bg-white/10"),
};

export function Button({
  variant = "primary",
  size = "md",
  asChild = false,
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const classes = cn(base, sizes[size], variants[variant], className);

  if (asChild) {
    return (
      <Slot.Root className={classes} {...rest}>
        {children}
      </Slot.Root>
    );
  }

  return (
    <button
      aria-busy={loading || undefined}
      className={classes}
      disabled={disabled || loading}
      type="button"
      {...rest}
    >
      {loading ? <Loader2 aria-hidden="true" className="animate-spin" /> : null}
      {children}
    </button>
  );
}
