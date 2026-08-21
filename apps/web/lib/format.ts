/**
 * Shared value formatting.
 *
 * Timestamps arrive as bare `z.string()` in the runtime contracts, so a blank
 * or malformed value decodes cleanly and only fails at render — and
 * `Intl.DateTimeFormat.format` throws `RangeError: Invalid time value` on an
 * unparseable date rather than printing "Invalid Date". A single malformed
 * timestamp in a list therefore used to take down the whole page. Every
 * formatter here fails soft to an explicit fallback instead.
 *
 * Formatter instances are module-scoped because constructing an
 * `Intl.DateTimeFormat` is expensive and these run once per table row.
 */

/** Shown when a value is absent or unparseable. Never invent a date. */
export const NOT_RECORDED = "Not recorded";

/** Shown for a numeric value that is absent or not finite. */
export const NO_VALUE = "—";

const timestampFormat = new Intl.DateTimeFormat("en", {
  dateStyle: "medium",
  timeStyle: "short",
});

const dateTimeFormat = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const clockFormat = new Intl.DateTimeFormat("en", {
  hour: "2-digit",
  minute: "2-digit",
});

const numberFormat = new Intl.NumberFormat("en");

/** Join available context labels without rendering empty or null path segments. */
export function formatContextPath(
  ...segments: ReadonlyArray<string | null | undefined>
): string {
  return segments
    .map((segment) => segment?.trim())
    .filter((segment): segment is string => Boolean(segment))
    .join(" / ");
}

/**
 * `new Date(null)` is the unix epoch, not an error, so nullish values are
 * rejected before parsing — otherwise a missing timestamp renders as
 * "Jan 1, 1970" and reads like real recorded data.
 */
function parseInstant(value: string | null | undefined): Date | null {
  if (value === null || value === undefined || value.trim() === "") {
    return null;
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function format(value: string | null | undefined, formatter: Intl.DateTimeFormat): string {
  const parsed = parseInstant(value);
  return parsed ? formatter.format(parsed) : NOT_RECORDED;
}

/** Absolute date and time — "21 Jun 2026, 16:30". For page and record timestamps. */
export function formatTimestamp(value: string | null | undefined): string {
  return format(value, timestampFormat);
}

/** Compact date and time — "Jun 21, 04:30 PM". For dense table and list rows. */
export function formatDateTime(value: string | null | undefined): string {
  return format(value, dateTimeFormat);
}

/** Time only — "04:30 PM". For same-day event feeds. */
export function formatClockTime(value: string | null | undefined): string {
  return format(value, clockFormat);
}

/**
 * Grouped integer — "1,048,576". Guards against NaN/Infinity reaching the UI
 * from a division by zero rather than rendering "NaN" to an operator.
 */
export function formatNumber(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return NO_VALUE;
  }

  return numberFormat.format(value);
}

/** Compact elapsed time for operational waits — "21 hr 43 min", never raw seconds. */
export function formatElapsedDuration(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) {
    return NO_VALUE;
  }

  const totalMinutes = Math.floor(seconds / 60);
  if (totalMinutes < 1) {
    return "under 1 min";
  }

  const totalHours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (totalHours < 1) {
    return `${totalMinutes} min`;
  }

  const days = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  if (days > 0) {
    return hours > 0
      ? `${days} ${days === 1 ? "day" : "days"} ${hours} hr`
      : `${days} ${days === 1 ? "day" : "days"}`;
  }

  return minutes > 0 ? `${totalHours} hr ${minutes} min` : `${totalHours} hr`;
}

/** `1 run` / `2 runs`, so operational copy never reads "1 blocked routes". */
export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${formatNumber(count)} ${count === 1 ? singular : plural}`;
}
