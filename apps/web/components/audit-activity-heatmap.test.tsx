import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AuditActivityHeatmap, buildAuditActivity, filterAuditTimeInterval } from "./audit-activity-heatmap";

const event = (occurred_at: string) => ({ occurred_at });

describe("audit activity binning", () => {
  it("uses UTC, half-open six-hour boundaries and exactly seven calendar dates", () => {
    const events = [
      event("2026-09-02T00:00:00Z"),
      event("2026-09-02T05:59:59Z"),
      event("2026-09-02T06:00:00Z"),
      event("2026-09-08T14:00:00+02:00"),
      event("2026-09-08T23:59:59Z"),
      event("2026-09-01T23:59:59Z"),
    ];
    const result = buildAuditActivity(events, events);
    expect(result.days).toHaveLength(7);
    expect(result.days[0]).toEqual({ timestamp: Date.parse("2026-09-02T00:00:00Z"), bins: [2, 1, 0, 0] });
    expect(result.days[6].bins).toEqual([0, 0, 1, 1]);
    expect(result).toMatchObject({ inRange: 5, filteredCount: 6, returnedCount: 6, outsideRange: 1, invalid: 0, maximum: 2 });
  });

  it("keeps the returned-window anchor and full denominator when filters exclude the newest event", () => {
    const returned = [event("2026-09-08T18:00:00Z"), event("2026-09-02T06:00:00Z"), event("2026-08-01T00:00:00Z"), event("invalid"), event("2026-09-03T10:00:00")];
    const result = buildAuditActivity(returned.slice(1), returned);
    expect(result.days[6].timestamp).toBe(Date.parse("2026-09-08T00:00:00Z"));
    expect(result).toMatchObject({ inRange: 1, filteredCount: 4, returnedCount: 5, outsideRange: 1, invalid: 2 });
    expect(result.days.flatMap((day) => day.bins).reduce((sum, count) => sum + count, 0)).toBe(1);
  });

  it("does not manufacture dates from invalid input or the current clock", () => {
    expect(buildAuditActivity([event("invalid")], [event("invalid")])).toMatchObject({ days: [], maximum: 0, invalid: 1, inRange: 0 });
    expect(buildAuditActivity([], [])).toMatchObject({ days: [], returnedCount: 0 });
    expect(buildAuditActivity([event("2026-02-30T12:00:00Z")], [event("2026-02-30T12:00:00Z")])).toMatchObject({ days: [], invalid: 1 });
  });

  it("filters the exact half-open UTC interval and refuses invalid timestamps", () => {
    const events = [event("2026-09-08T05:59:59Z"), event("2026-09-08T08:00:00+02:00"),
      event("2026-09-08T11:59:59.999Z"), event("2026-09-08T12:00:00Z"), event("2026-09-08T10:00:00"), event("invalid")];
    const interval = { start: Date.parse("2026-09-08T06:00:00Z"), end: Date.parse("2026-09-08T12:00:00Z"), label: "fixture" };
    expect(filterAuditTimeInterval(events, interval)).toEqual([events[1], events[2]]);
    expect(filterAuditTimeInterval(events, null)).toBe(events);
  });
});

describe("AuditActivityHeatmap", () => {
  it("filters only on keyboard activation, supports zero cells and clears the active interval", async () => {
    const events = [event("2026-09-08T06:00:00Z")];
    const onSelectInterval = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<AuditActivityHeatmap events={events} returnedEvents={events} onSelectInterval={onSelectInterval} controlsId="events" />);
    const zero = screen.getByRole("button", { name: "2 Sept 2026, 00:00–06:00 UTC: 0 events in returned window" });
    await user.tab();
    expect(zero).toHaveFocus();
    expect(onSelectInterval).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");
    const interval = { start: Date.parse("2026-09-02T00:00:00Z"), end: Date.parse("2026-09-02T06:00:00Z"), label: "2 Sept 2026, 00:00–06:00 UTC" };
    expect(onSelectInterval).toHaveBeenLastCalledWith(interval);
    rerender(<AuditActivityHeatmap events={events} returnedEvents={events} onSelectInterval={onSelectInterval} selectedInterval={interval} controlsId="events" />);
    expect(zero).toHaveAttribute("aria-pressed", "true");
    expect(zero).toHaveAttribute("aria-controls", "events");
    await user.click(screen.getByRole("button", { name: "Clear time filter" }));
    expect(onSelectInterval).toHaveBeenLastCalledWith(null);
    await user.click(zero);
    expect(onSelectInterval).toHaveBeenLastCalledWith(null);
  });
  it("exposes counts without color or hover and lets keyboard focus inspect a bin", async () => {
    const events = [event("2026-09-08T06:00:00Z"), event("2026-09-08T08:00:00Z")];
    render(<AuditActivityHeatmap events={events} returnedEvents={events} />);
    expect(screen.getByRole("heading", { name: "Activity by time" })).toBeInTheDocument();
    expect(screen.getByText("2 events")).toBeInTheDocument();
    expect(screen.queryByText(/2 of 2 filtered events/)).not.toBeInTheDocument();
    expect(screen.getByRole("table", { name: /UTC date/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "8 Sept 2026, 06:00–12:00 UTC: 2 events in returned window" })).toHaveTextContent("2");
    expect(screen.getByLabelText("Color scale: zero to 2 events per cell")).toBeInTheDocument();
    expect(screen.getByText("Counts cover the returned window only.")).toBeInTheDocument();
    const zero = screen.getByRole("button", { name: "2 Sept 2026, 00:00–06:00 UTC: 0 events in returned window" });
    fireEvent.focus(zero);
    expect(screen.getByRole("status")).toHaveTextContent("0 events · 2 Sept 2026, 00:00–06:00 UTC");
    await userEvent.click(screen.getByRole("button", { name: "8 Sept 2026, 06:00–12:00 UTC: 2 events in returned window" }));
    expect(screen.getByRole("status")).toHaveTextContent("2 events · 8 Sept 2026, 06:00–12:00 UTC");
  });

  it("reports excluded and invalid timestamps, and updates when filters change", () => {
    const returned = [event("2026-09-08T06:00:00Z"), event("2026-08-01T00:00:00Z"), event("not-a-date")];
    const { rerender } = render(<AuditActivityHeatmap events={returned} returnedEvents={returned} />);
    expect(screen.getByText("1 of 3 filtered events")).toBeInTheDocument();
    expect(screen.getByText(/1 outside these seven dates.*1 with invalid/)).toBeInTheDocument();
    rerender(<AuditActivityHeatmap events={[returned[1]]} returnedEvents={returned} />);
    expect(screen.getByText("0 of 1 filtered events")).toBeInTheDocument();
    expect(screen.getByText(/3 returned.*8 Sept 2026 UTC/)).toBeInTheDocument();
    expect(screen.getByLabelText("Color scale: zero to 0 events per cell")).toBeInTheDocument();
  });
});
