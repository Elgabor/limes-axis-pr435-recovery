import { describe, expect, it } from "vitest";

import {
  formatClockTime,
  formatContextPath,
  formatDateTime,
  formatElapsedDuration,
  formatNumber,
  formatTimestamp,
} from "./format";

describe("formatContextPath", () => {
  it("joins present context segments and drops null, undefined, and blank values", () => {
    expect(
      formatContextPath("Northwind Press", null, undefined, " ", "tenant_northwind_press"),
    ).toBe("Northwind Press / tenant_northwind_press");
  });
});

// The API contracts type every timestamp as a bare `z.string()`, so a malformed
// or empty value decodes successfully and only fails at render. `Intl.format`
// throws `RangeError: Invalid time value` on an unparseable date — it does not
// print "Invalid Date" — which took down whole pages.
describe("timestamp formatters", () => {
  const unrenderable = ["", "   ", "not-a-date", "2026-13-45T99:99:99Z"];

  it.each(unrenderable)("renders a fallback instead of throwing for %j", (value) => {
    expect(() => formatTimestamp(value)).not.toThrow();
    expect(formatTimestamp(value)).toBe("Not recorded");
    expect(formatDateTime(value)).toBe("Not recorded");
    expect(formatClockTime(value)).toBe("Not recorded");
  });

  it.each([null, undefined])("renders a fallback for %j", (value) => {
    expect(formatTimestamp(value)).toBe("Not recorded");
  });

  it("does not treat null as the unix epoch", () => {
    // `new Date(null)` is 1970-01-01, which previously rendered as real data.
    expect(formatTimestamp(null)).not.toContain("1970");
  });

  it("formats valid instants", () => {
    expect(formatTimestamp("2026-06-21T16:30:00+02:00")).toContain("2026");
    expect(formatDateTime("2026-06-21T16:30:00Z")).toContain("Jun");
    expect(formatClockTime("2026-06-21T16:30:00Z")).toMatch(/\d{2}:\d{2}/);
  });
});

describe("formatNumber", () => {
  it("groups thousands so large counts stay readable", () => {
    expect(formatNumber(1048576)).toBe("1,048,576");
    expect(formatNumber(0)).toBe("0");
  });

  it("renders a dash for values that are not finite", () => {
    // Guards against NaN/Infinity leaking in from a division by zero.
    expect(formatNumber(Number.NaN)).toBe("—");
    expect(formatNumber(Number.POSITIVE_INFINITY)).toBe("—");
    expect(formatNumber(null)).toBe("—");
  });
});

describe("formatElapsedDuration", () => {
  it("formats operational waits in minutes, hours, and days instead of raw seconds", () => {
    expect(formatElapsedDuration(45)).toBe("under 1 min");
    expect(formatElapsedDuration(3_600)).toBe("1 hr");
    expect(formatElapsedDuration(78_183)).toBe("21 hr 43 min");
    expect(formatElapsedDuration(97_200)).toBe("1 day 3 hr");
  });

  it("fails soft for invalid durations", () => {
    expect(formatElapsedDuration(-1)).toBe("—");
    expect(formatElapsedDuration(Number.NaN)).toBe("—");
    expect(formatElapsedDuration(null)).toBe("—");
  });
});
