import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface CardProps extends HTMLAttributes<HTMLElement> {
  /** Landmark element to render. Use `section`/`article` when the card is a real region. */
  as?: "div" | "section" | "article";
  /** `md` (20px) is the console default; `sm` suits stat tiles and nested cards. */
  padding?: "none" | "sm" | "md";
  /** Emphasizes the border on hover — for cards that are themselves a target. */
  interactive?: boolean;
  children: ReactNode;
}

const paddings: Record<NonNullable<CardProps["padding"]>, string> = {
  none: "",
  sm: "p-4",
  md: "p-5",
};

/**
 * The console's one surface treatment: hairline border, 16px radius. Hover is
 * a border change rather than a lift — surfaces in a dense tool should not move
 * under the pointer.
 */
export function Card({
  as: Component = "div",
  padding = "md",
  interactive = false,
  className,
  children,
  ...rest
}: CardProps) {
  return (
    <Component
      className={cn(
        "min-w-0 rounded-2xl border border-line bg-surface",
        "dark:border-white/10 dark:bg-white/5",
        paddings[padding],
        interactive &&
          "transition-colors duration-150 hover:border-ink/20 dark:hover:border-white/25",
        className,
      )}
      {...rest}
    >
      {children}
    </Component>
  );
}
