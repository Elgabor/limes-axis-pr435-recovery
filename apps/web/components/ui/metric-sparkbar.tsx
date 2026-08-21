import type { CSSProperties, HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export type MetricSparkbarPoint = {
  label: string;
  value: number;
};

export interface MetricSparkbarProps extends HTMLAttributes<HTMLDivElement> {
  points: MetricSparkbarPoint[];
  /** Accessible description of what the bars encode. */
  caption: string;
  /** Bar strip height in pixels. */
  height?: number;
}

/**
 * Tiny animated bar strip for metric cards. Bars grow in via the brand
 * `.bar-grow` utility once an ancestor `.reveal` gains `.revealed` (the
 * `Reveal` wrapper provides this); reduced-motion renders them fully grown.
 * Values must come straight from an API payload — this component only scales.
 */
export function MetricSparkbar({
  points,
  caption,
  height = 44,
  className,
  ...rest
}: MetricSparkbarProps) {
  const max = Math.max(1, ...points.map((point) => point.value));
  const valueSummary = points.map((point) => `${point.label}: ${point.value}`).join(", ");
  const accessibleLabel = valueSummary
    ? `${caption}. ${valueSummary}.`
    : `${caption}. No data.`;

  return (
    <div
      aria-label={accessibleLabel}
      className={cn("grid gap-1.5", className)}
      role="img"
      {...rest}
    >
      <div className="flex items-end gap-1" style={{ height }}>
        {points.map((point, index) => (
          <span
            className={cn(
              "bar-grow min-w-1 flex-1 rounded-t-[3px] bg-signal/80 dark:bg-signal",
              // `flex-1` alone lets a sparse series stretch each bar across the
              // whole strip: one bucket rendered as a solid full-width slab
              // rather than a chart, which is what a new tenant sees.
              "max-w-6",
            )}
            key={`${point.label}-${index}`}
            style={
              {
                height: `${Math.max(8, Math.round((point.value / max) * 100))}%`,
                "--bar-delay": `${index * 70}ms`,
              } as CSSProperties
            }
            title={`${point.label}: ${point.value}`}
          />
        ))}
      </div>
      <div aria-hidden="true" className="rule-hairline" />
    </div>
  );
}
