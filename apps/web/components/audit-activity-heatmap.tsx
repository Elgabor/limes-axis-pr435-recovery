"use client";

import { useId, useState } from "react";

type TimedEvent = { occurred_at: string };
export type AuditTimeInterval = { start: number; end: number; label: string };
const DAY = 86_400_000;
const SIX_HOURS = DAY / 4;
const dateLabel = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
});
const weekdayLabel = new Intl.DateTimeFormat("en-GB", { weekday: "short", timeZone: "UTC" });
const hours = ["00:00–06:00", "06:00–12:00", "12:00–18:00", "18:00–24:00"];

function timestamp(value: string) {
  // Require an explicit zone: a browser-local timestamp would shift the UTC bins.
  if (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return NaN;
  const date = value.slice(0, 10);
  const midnight = new Date(`${date}T00:00:00Z`);
  // Date.parse normalizes some impossible dates, such as 30 February.
  if (!Number.isFinite(midnight.getTime()) || midnight.toISOString().slice(0, 10) !== date) return NaN;
  return Date.parse(value);
}

export function filterAuditTimeInterval<T extends TimedEvent>(events: T[], interval: AuditTimeInterval | null): T[] {
  if (!interval) return events;
  return events.filter((event) => {
    const at = timestamp(event.occurred_at);
    return Number.isFinite(at) && at >= interval.start && at < interval.end;
  });
}

export function buildAuditActivity(events: TimedEvent[], returnedEvents: TimedEvent[]) {
  const validReturned = returnedEvents.map((event) => timestamp(event.occurred_at)).filter(Number.isFinite);
  const latest = validReturned.length ? Math.max(...validReturned) : null;
  const end = latest === null ? null : Math.floor(latest / DAY) * DAY + DAY;
  const start = end === null ? null : end - 7 * DAY;
  const days = start === null ? [] : Array.from({ length: 7 }, (_, day) => ({
    timestamp: start + day * DAY,
    bins: [0, 0, 0, 0],
  }));
  let invalid = 0;
  let inRange = 0;
  for (const event of events) {
    const at = timestamp(event.occurred_at);
    if (!Number.isFinite(at)) { invalid += 1; continue; }
    if (start === null || end === null || at < start || at >= end) continue;
    const offset = at - start;
    days[Math.floor(offset / DAY)].bins[Math.floor((offset % DAY) / SIX_HOURS)] += 1;
    inRange += 1;
  }
  return { days, inRange, invalid, outsideRange: events.length - invalid - inRange,
    filteredCount: events.length, returnedCount: returnedEvents.length,
    maximum: Math.max(0, ...days.flatMap((day) => day.bins)) };
}

function intensity(count: number, maximum: number) {
  if (count === 0) return "bg-ink/4 text-muted dark:bg-white/5";
  const fraction = count / maximum;
  if (fraction > 0.75) return "bg-signal text-white";
  if (fraction > 0.5) return "bg-signal/25 text-ink dark:bg-signal/30";
  if (fraction > 0.25) return "bg-signal/15 text-ink dark:bg-signal/20";
  return "bg-signal/8 text-ink dark:bg-signal/10";
}

export function AuditActivityHeatmap({ events, returnedEvents, selectedInterval = null, onSelectInterval, controlsId }: {
  events: TimedEvent[];
  returnedEvents: TimedEvent[];
  selectedInterval?: AuditTimeInterval | null;
  onSelectInterval?: (interval: AuditTimeInterval | null) => void;
  controlsId?: string;
}) {
  const id = useId();
  const [inspected, setInspected] = useState<string | null>(null);
  const activity = buildAuditActivity(events, returnedEvents);
  const cells = activity.days.flatMap((day) => day.bins.map((count, bin) => ({
    key: `${day.timestamp}-${bin}`, count,
    start: day.timestamp + bin * SIX_HOURS,
    label: `${dateLabel.format(day.timestamp)}, ${hours[bin]} UTC`,
  })));
  const selected = cells.find((cell) => cell.key === inspected)
    ?? cells.find((cell) => cell.start === selectedInterval?.start)
    ?? cells.find((cell) => cell.count === activity.maximum);
  const completeWindow = activity.inRange === activity.filteredCount
    && activity.filteredCount === activity.returnedCount;
  const range = activity.days.length > 0
    ? `${dateLabel.formatRange(activity.days[0].timestamp, activity.days[6].timestamp)} UTC`
    : "No valid dated events to plot";

  return (
    <section aria-labelledby={`${id}-title`} className="min-w-0 rounded-2xl border border-line bg-surface p-4 dark:border-white/10 dark:bg-white/5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h2 id={`${id}-title`} className="font-display m-0 text-lg text-ink">Activity by time</h2>
        <span className="rounded-full bg-ink/4 px-2.5 py-1 text-xs tabular-nums text-muted dark:bg-white/5">UTC · 6-hour bins</span>
      </div>
      <p className="mb-2 mt-2 text-xs leading-relaxed text-muted">
        {completeWindow ? (
          <><strong className="font-medium text-ink">{activity.inRange} {activity.inRange === 1 ? "event" : "events"}</strong> · {range}</>
        ) : (
          <><strong className="font-medium text-ink">{activity.inRange} of {activity.filteredCount} filtered events</strong> in range · {activity.returnedCount} returned · {range}</>
        )}
      </p>
      {activity.days.length > 0 ? (
        <>
          <table className="w-full table-fixed border-separate border-spacing-1" aria-label="Audit events by UTC date and six-hour interval">
            <thead>
              <tr>
                <th scope="col" className="w-12 text-left text-[11px] font-normal text-muted">UTC</th>
                {activity.days.map((day) => (
                  <th scope="col" key={day.timestamp} className="pb-1 text-center text-xs font-normal text-muted" aria-label={dateLabel.format(day.timestamp)}>
                    <span className="block">{weekdayLabel.format(day.timestamp)}</span>
                    <span className="mt-0.5 block tabular-nums text-ink">{new Date(day.timestamp).getUTCDate()}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {hours.map((hour, bin) => (
                <tr key={hour}>
                  <th scope="row" className="text-left text-[11px] font-normal tabular-nums text-muted">{hour.replaceAll(":00", "")}</th>
                  {activity.days.map((day) => {
                    const count = day.bins[bin];
                    const key = `${day.timestamp}-${bin}`;
                    const start = day.timestamp + bin * SIX_HOURS;
                    const isActive = selectedInterval?.start === start;
                    return (
                      <td key={key} className="p-0">
                        <button type="button"
                          aria-label={`${dateLabel.format(day.timestamp)}, ${hour} UTC: ${count} ${count === 1 ? "event" : "events"} in returned window`}
                          aria-describedby={`${id}-detail`}
                          aria-pressed={onSelectInterval ? isActive : undefined}
                          aria-controls={controlsId}
                          onFocus={() => setInspected(key)} onClick={() => {
                            setInspected(key);
                            onSelectInterval?.(isActive ? null : {
                              start, end: start + SIX_HOURS,
                              label: `${dateLabel.format(day.timestamp)}, ${hour} UTC`,
                            });
                          }}
                          className={`min-h-8 w-full cursor-pointer rounded-md border-0 px-0.5 text-xs font-medium tabular-nums focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal active:scale-[0.97] ${intensity(count, activity.maximum)} ${isActive ? "ring-2 ring-ink ring-offset-1 ring-offset-surface" : ""}`}>
                          {count}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 text-xs">
            <p id={`${id}-detail`} role="status" className="m-0 min-w-0 leading-relaxed text-ink">
              {selected?.count} {selected?.count === 1 ? "event" : "events"} · {selected?.label}
            </p>
            <div className="flex items-center gap-1.5 text-muted" aria-label={`Color scale: zero to ${activity.maximum} events per cell`}>
              <span>0</span>
              <span aria-hidden="true" className="flex gap-0.5">
                {["bg-ink/4 dark:bg-white/5", "bg-signal/15", "bg-signal/25", "bg-signal"].map((color) => <span key={color} className={`h-2.5 w-3 rounded-sm ${activity.maximum ? color : "bg-ink/4 dark:bg-white/5"}`} />)}
              </span>
              <span>{activity.maximum} max</span>
            </div>
          </div>
          {selectedInterval && onSelectInterval ? (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-line/60 pt-3 dark:border-white/10">
              <p className="m-0 text-xs font-medium text-ink">Time filter: {selectedInterval.label}</p>
              <button type="button" onClick={() => onSelectInterval(null)} aria-controls={controlsId}
                className="min-h-8 cursor-pointer rounded-lg border border-line bg-transparent px-2.5 text-xs font-medium text-ink hover:bg-ink/4 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal dark:border-white/15">
                Clear time filter
              </button>
            </div>
          ) : null}
        </>
      ) : null}
      <p className="mb-0 mt-2 text-[11px] leading-relaxed text-muted">
        Counts cover the returned window only.{onSelectInterval ? " Select a cell to filter events below." : ""}
        {activity.outsideRange > 0 ? ` ${activity.outsideRange} outside these seven dates.` : ""}
        {activity.invalid > 0 ? ` ${activity.invalid} with invalid or unzoned timestamps excluded.` : ""}
      </p>
    </section>
  );
}
