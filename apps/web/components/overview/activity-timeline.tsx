"use client";

import { useRef, useState } from "react";
import type { AuditLedgerEvent } from "@/lib/audit-demo";

type TimelineInput = Pick<AuditLedgerEvent, "occurred_at"> & { severity: string };

export type ActivityDateBin = {
  date: string;
  count: number;
  attention: number;
  unknownSeverity: number;
  attentionShare: number | null;
};

function utcDate(timestamp: string): string | null {
  // Require an explicit timezone: browser-local parsing must not move a bin.
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.exec(timestamp);
  if (!parts) return null;
  const [, year, month, day, hour, minute, second] = parts.map(Number);
  const calendar = new Date(0);
  calendar.setUTCFullYear(year, month - 1, day);
  if (calendar.getUTCFullYear() !== year || calendar.getUTCMonth() !== month - 1 || calendar.getUTCDate() !== day || hour > 23 || minute > 59 || second > 59) return null;
  const instant = new Date(timestamp);
  return Number.isFinite(instant.getTime()) ? instant.toISOString().slice(0, 10) : null;
}

/** Only observed dates are binned; missing days never become invented zeroes. */
export function aggregateAuditTimeline(events: readonly TimelineInput[]) {
  const dates = new Map<string, ActivityDateBin>();
  let invalidTimestamps = 0;
  for (const event of events) {
    const date = utcDate(event.occurred_at);
    if (!date) { invalidTimestamps += 1; continue; }
    const bin = dates.get(date) ?? { date, count: 0, attention: 0, unknownSeverity: 0, attentionShare: null };
    bin.count += 1;
    if (event.severity === "watch" || event.severity === "action_required") bin.attention += 1;
    else if (event.severity !== "ready") bin.unknownSeverity += 1;
    dates.set(date, bin);
  }
  const bins = [...dates.values()].sort((a, b) => a.date.localeCompare(b.date));
  for (const bin of bins) bin.attentionShare = bin.unknownSeverity ? null : bin.attention / bin.count;
  return { bins, invalidTimestamps };
}

const percent = new Intl.NumberFormat("en", { style: "percent", maximumFractionDigits: 1 });
const month = new Intl.DateTimeFormat("en", { month: "short", timeZone: "UTC" });
const rangeDate = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeZone: "UTC" });
const dateInstant = (date: string) => new Date(`${date}T00:00:00Z`);
const attentionValue = (bin: ActivityDateBin) => bin.attentionShare === null
  ? `Attention unavailable · ${bin.unknownSeverity} unknown severity`
  : `${percent.format(bin.attentionShare)} attention · ${bin.attention}/${bin.count}`;

export function ActivityTimeline({ events }: { events: readonly AuditLedgerEvent[] }) {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [hoveredDate, setHoveredDate] = useState<string | null>(null);
  const [focusedDate, setFocusedDate] = useState<string | null>(null);
  const dateButtons = useRef<Array<SVGGElement | null>>([]);
  const { bins, invalidTimestamps } = aggregateAuditTimeline(events);
  const activeDate = hoveredDate ?? focusedDate ?? selectedDate;
  const active = bins.find((bin) => bin.date === activeDate);
  const focusIndex = Math.max(0, bins.findIndex((bin) => bin.date === (focusedDate ?? selectedDate)));
  const dense = bins.length > 7;
  const width = dense ? bins.length * 50 + 62 : 250;
  const plotLeft = 26;
  const plotRight = width - 36;
  const plotTop = 20;
  const plotBottom = 146;
  const plotHeight = plotBottom - plotTop;
  const maxCount = Math.max(1, ...bins.map((bin) => bin.count));
  const step = (plotRight - plotLeft) / Math.max(1, bins.length);
  const points = bins.map((bin, index) => ({
    x: plotLeft + step * (index + 0.5),
    y: bin.attentionShare === null ? null : plotBottom - bin.attentionShare * plotHeight,
  }));
  const clearSelection = () => {
    setSelectedDate(null);
    setHoveredDate(null);
    setFocusedDate(null);
  };
  const toggleDate = (date: string) => {
    setSelectedDate((current) => current === date ? null : date);
    setHoveredDate(null);
    setFocusedDate(null);
  };

  return (
    <div className="grid min-w-0 gap-3">
      <div className="grid gap-1">
        <div className="flex items-start justify-between gap-2">
          <p className="m-0 text-xs font-medium text-muted">{active ? `${active.date} UTC` : "Returned window"}</p>
          <button type="button" disabled={!active} onClick={clearSelection} className="shrink-0 cursor-pointer border-0 bg-transparent p-0 text-xs text-signal disabled:cursor-default disabled:text-muted">Reset</button>
        </div>
        <p role="status" className="m-0 text-sm font-medium tabular-nums text-ink">
          {active ? `${active.count} ${active.count === 1 ? "event" : "events"} · ${attentionValue(active)}` : `${events.length} returned ${events.length === 1 ? "event" : "events"} · ${bins.length} UTC ${bins.length === 1 ? "date" : "dates"}`}
        </p>
        {bins.length > 1 ? <p className="m-0 text-xs text-muted">{rangeDate.formatRange(dateInstant(bins[0].date), dateInstant(bins[bins.length - 1].date))} UTC</p> : null}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-2 text-xs text-muted" aria-label="Chart legend">
        <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm bg-signal" />Events · left axis</span>
        <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="h-0.5 w-4 bg-warning" />Attention share · right axis</span>
      </div>
      {bins.length ? (
        <div className="min-w-0 overflow-x-auto rounded-xl border border-line bg-signal/[0.03] p-1 dark:border-white/10" role="region" aria-label={dense ? "Events and attention share by UTC date; scroll for more dates" : "Events and attention share by UTC date"}>
          <svg role="group" aria-label="Choose a UTC date. Arrow keys navigate; Enter or Space selects; Escape clears." viewBox={`0 0 ${width} 194`} style={{ minWidth: dense ? width : undefined }} className="block h-auto w-full text-muted">
            {[0, 0.5, 1].map((fraction) => {
              const y = plotBottom - fraction * plotHeight;
              return <g key={fraction} aria-hidden="true" pointerEvents="none">
                <line x1={plotLeft} x2={plotRight} y1={y} y2={y} stroke="currentColor" strokeOpacity={0.15} strokeDasharray={fraction ? "3 4" : undefined} />
                {fraction !== 0.5 || maxCount % 2 === 0 ? <text x={plotLeft - 5} y={y + 4} textAnchor="end" fill="currentColor" fontSize={11}>{maxCount * fraction}</text> : null}
                <text x={plotRight + 5} y={y + 4} fill="currentColor" fontSize={11}>{fraction * 100}%</text>
              </g>;
            })}
            {bins.map((bin, index) => {
              const point = points[index];
              const barHeight = bin.count / maxCount * plotHeight;
              const highlighted = active?.date === bin.date;
              return <g key={bin.date}
                role="button"
                ref={(element) => { dateButtons.current[index] = element; }}
                tabIndex={index === focusIndex ? 0 : -1}
                aria-label={`${bin.date} UTC: ${bin.count} ${bin.count === 1 ? "event" : "events"}; ${attentionValue(bin)}`}
                aria-pressed={selectedDate === bin.date}
                className="cursor-pointer outline-none"
                onPointerEnter={(event) => { if (event.pointerType !== "touch") setHoveredDate(bin.date); }}
                onPointerLeave={() => setHoveredDate(null)}
                onFocus={() => setFocusedDate(bin.date)}
                onBlur={() => setFocusedDate(null)}
                onClick={() => toggleDate(bin.date)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); toggleDate(bin.date); }
                  else if (event.key === "Escape") { event.preventDefault(); clearSelection(); }
                  else if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
                    event.preventDefault();
                    const next = event.key === "Home" ? 0 : event.key === "End" ? bins.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + bins.length) % bins.length;
                    const target = dateButtons.current[next];
                    target?.focus();
                    target?.scrollIntoView({ block: "nearest", inline: "nearest" });
                  }
                }}>
                <rect x={point.x - step / 2 + 1} y={4} width={step - 2} height={184} rx={5} fill="transparent" stroke={highlighted ? "rgb(var(--signal))" : "transparent"} strokeOpacity={0.45} />
                <rect x={point.x - Math.min(14, step / 4)} y={plotBottom - barHeight} width={Math.min(28, step / 2)} height={barHeight} rx={4} className="fill-signal transition-opacity" fillOpacity={active && !highlighted ? 0.2 : highlighted ? 1 : 0.72} />
                <text x={point.x} y={plotBottom - barHeight - 6} textAnchor="middle" className="fill-ink" fontSize={12}>{bin.count}</text>
                <text x={point.x} y={168} textAnchor="middle" fill="currentColor" fontSize={12}>{Number(bin.date.slice(8))}</text>
                <text x={point.x} y={182} textAnchor="middle" fill="currentColor" fontSize={11}>{month.format(dateInstant(bin.date))}</text>
              </g>;
            })}
            {points.map((point, index) => {
              const previous = points[index - 1];
              const highlighted = active?.date === bins[index].date;
              return point.y === null ? null : <g key={bins[index].date} aria-hidden="true" pointerEvents="none">
                {previous?.y != null ? <line x1={previous.x} y1={previous.y} x2={point.x} y2={point.y} className="stroke-warning" strokeWidth={2.5} opacity={active ? 0.3 : 1} /> : null}
                <circle cx={point.x} cy={point.y} r={highlighted ? 5 : 4} className="fill-warning stroke-surface" strokeWidth={2} opacity={active && !highlighted ? 0.25 : 1} />
              </g>;
            })}
          </svg>
        </div>
      ) : <p className="m-0 text-sm text-muted">No valid timestamps to plot.</p>}
      <p className="m-0 text-xs leading-relaxed text-muted">
        {bins.length === 1 ? "Only one UTC date in this window." : bins.length > 1 ? "Select a date to inspect. Returned dates only." : "No dated activity in this window."}
      </p>
      {invalidTimestamps > 0 ? <p className="m-0 text-xs text-warning">{invalidTimestamps} {invalidTimestamps === 1 ? "event has" : "events have"} an invalid timestamp and cannot be placed by date.</p> : null}
      {bins.length > 0 ? <details className="text-xs text-muted">
        <summary className="cursor-pointer font-medium text-ink">Daily values</summary>
        <p className="mb-0 mt-3 leading-relaxed">Attention = Watch + Action required; share of that date’s returned events. Not complete daily totals.</p>
        <div className="mt-3 grid gap-2" aria-label="Daily activity values">
        {bins.map((bin) => <div key={bin.date} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-2 border-b border-line/60 pb-2 text-xs last:border-0 last:pb-0">
          <time dateTime={bin.date} className="font-medium text-ink">{bin.date} UTC</time>
          <span className="tabular-nums text-ink">{bin.count} {bin.count === 1 ? "event" : "events"}</span>
          <span className="col-span-2 mt-1 text-muted">{bin.attentionShare === null ? `Attention share unavailable · ${bin.unknownSeverity} unknown severity` : `${bin.attention}/${bin.count} attention · ${percent.format(bin.attentionShare)}`}</span>
        </div>)}
        </div>
      </details> : null}
    </div>
  );
}
