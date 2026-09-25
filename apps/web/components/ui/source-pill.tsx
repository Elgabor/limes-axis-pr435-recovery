import {
  BookOpenText,
  CircleAlert,
  CircleCheck,
  CircleMinus,
  Clock,
  Loader2,
} from "lucide-react";
import type { ComponentType } from "react";

import { cn } from "@/lib/cn";
import type { SourceState } from "@/lib/source-state";

const tones: Record<SourceState, string> = {
  loading: "status-checking",
  live: "signal-ready",
  reference: "status-checking",
  empty: "status-checking",
  stale: "signal-watch",
  unavailable: "signal-action-required",
};

const icons: Record<SourceState, ComponentType<{ className?: string }>> = {
  loading: Loader2,
  live: CircleCheck,
  reference: BookOpenText,
  empty: CircleMinus,
  stale: Clock,
  unavailable: CircleAlert,
};

export interface SourcePillProps {
  state: SourceState;
  /**
   * What the pill is describing, e.g. "agent registry". The state word is
   * supplied by the component so the tone and the wording can never disagree.
   */
  subject: string;
  className?: string;
  /** Short visible labels for grouped dashboard summaries. */
  compact?: boolean;
}

const labels: Record<SourceState, (subject: string) => string> = {
  loading: (subject) => `${subject}: loading`,
  live: (subject) => `${subject}: live`,
  reference: (subject) => `${subject}: reference scenario`,
  empty: (subject) => `${subject}: no records`,
  stale: (subject) => `${subject}: stale`,
  unavailable: (subject) => `${subject}: unavailable`,
};

/**
 * Data-provenance badge. Previously each console hardcoded the green `ready`
 * tone and computed only the text, so a surface could render a green pill
 * reading "Agent API unavailable". Tone and label are derived together here.
 */
export function SourcePill({ state, subject, className, compact = false }: SourcePillProps) {
  const Icon = icons[state];

  return (
    <span className={cn("status-pill", tones[state], className)} data-source-state={state}>
      <Icon aria-hidden="true" className={cn("size-3.5", state === "loading" && "animate-spin")} />
      <span className="sr-only">Data source: </span>
      {compact && state === "reference" ? `${subject}: example` : labels[state](subject)}
    </span>
  );
}
