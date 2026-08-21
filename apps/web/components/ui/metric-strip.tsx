import { cn } from "@/lib/cn";

export type Metric = {
  label: string;
  value: string | number;
  detail?: string;
  tone?: "ready" | "watch" | "action";
};

const MAX_METRICS = 5;

const toneClasses: Record<NonNullable<Metric["tone"]>, string> = {
  ready: "text-positive",
  watch: "text-warning",
  action: "text-danger",
};

/** Tone must never be conveyed by the dot's color alone. */
const toneText: Record<NonNullable<Metric["tone"]>, string> = {
  ready: "Ready:",
  watch: "Needs watching:",
  action: "Action required:",
};

/**
 * Horizontal strip of page metrics. Hard cap: renders the first five and
 * warns in development if given more — metrics must describe user-relevant
 * state, not enumerate internal invariants.
 */
export function MetricStrip({ metrics }: { metrics: Metric[] }) {
  if (process.env.NODE_ENV !== "production" && metrics.length > MAX_METRICS) {
    console.warn(
      `MetricStrip renders at most ${MAX_METRICS} metrics; received ${metrics.length}. Extra metrics are dropped — move detail into the page body or an Inspect drawer.`,
    );
  }

  const visible = metrics.slice(0, MAX_METRICS);

  return (
    <div className="flex min-w-0 flex-wrap gap-3" role="list">
      {visible.map((metric) => (
        <article
          key={metric.label}
          className={cn(
            "min-w-[160px] flex-1 basis-40 rounded-2xl border border-line bg-surface p-4",
            "dark:border-white/10 dark:bg-white/5",
          )}
          role="listitem"
        >
          <p className="eyebrow m-0">{metric.label}</p>
          <p className="font-display mx-0 mt-3 mb-0 flex items-center gap-2 text-2xl tabular-nums text-ink">
            {metric.tone ? (
              <>
                <span aria-hidden="true" className={cn("status-dot", toneClasses[metric.tone])} />
                <span className="sr-only">{toneText[metric.tone]} </span>
              </>
            ) : null}
            {metric.value}
          </p>
          {metric.detail ? (
            <p className="mx-0 mt-1.5 mb-0 text-xs leading-snug break-words text-muted">
              {metric.detail}
            </p>
          ) : null}
        </article>
      ))}
    </div>
  );
}
