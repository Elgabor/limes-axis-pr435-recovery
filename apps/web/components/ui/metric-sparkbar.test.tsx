import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MetricSparkbar } from "@/components/ui/metric-sparkbar";

describe("MetricSparkbar", () => {
  it("caps bar width so a sparse series stays a chart", () => {
    // A brand-new tenant's events land in one bucket. With `flex-1` alone the
    // single bar filled the whole strip and read as a solid blue slab.
    render(<MetricSparkbar caption="Audit events" points={[{ label: "10:00", value: 9 }]} />);

    const bar = screen.getByTitle("10:00: 9");
    expect(bar.className).toContain("max-w-6");
  });

  it("scales bar heights against the largest value", () => {
    render(
      <MetricSparkbar
        caption="Audit events"
        points={[
          { label: "09:00", value: 5 },
          { label: "10:00", value: 10 },
        ]}
      />,
    );

    expect(screen.getByTitle("09:00: 5")).toHaveStyle({ height: "50%" });
    expect(screen.getByTitle("10:00: 10")).toHaveStyle({ height: "100%" });
    expect(
      screen.getByRole("img", {
        name: "Audit events. 09:00: 5, 10:00: 10.",
      }),
    ).toBeInTheDocument();
  });

  it("keeps a zero-valued bucket visible instead of collapsing it", () => {
    render(
      <MetricSparkbar
        caption="Audit events"
        points={[
          { label: "09:00", value: 0 },
          { label: "10:00", value: 4 },
        ]}
      />,
    );

    expect(screen.getByTitle("09:00: 0")).toHaveStyle({ height: "8%" });
  });

  it("announces an empty series without relying on hover text", () => {
    render(<MetricSparkbar caption="Audit events" points={[]} />);

    expect(
      screen.getByRole("img", { name: "Audit events. No data." }),
    ).toBeInTheDocument();
  });
});
