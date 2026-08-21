import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface EyebrowProps extends HTMLAttributes<HTMLParagraphElement> {
  /**
   * Renders in Signal Blue. Reserved for the page eyebrow, where the accent
   * names the navigation group and aids orientation — section markers stay
   * muted so the accent keeps its meaning.
   */
  accent?: boolean;
  children: ReactNode;
}

/** Mono uppercase micro-label — the console's one caption treatment. */
export function Eyebrow({ accent = false, className, children, ...rest }: EyebrowProps) {
  return (
    <p className={cn("eyebrow m-0", accent && "eyebrow-accent", className)} {...rest}>
      {children}
    </p>
  );
}
