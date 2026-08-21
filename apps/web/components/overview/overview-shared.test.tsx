import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusDot } from "./overview-shared";

describe("StatusDot", () => {
  it.each([
    ["ready", "Ready", "circle-check"],
    ["watch", "Watch", "clock-3"],
    ["action_required", "Action Required", "circle-alert"],
  ] as const)("exposes the %s status with text and a distinct shape", (status, label, icon) => {
    render(<StatusDot status={status} />);

    const indicator = screen.getByRole("img", { name: `Status: ${label}` });
    expect(indicator).toHaveAttribute("data-status", status);
    expect(indicator).toHaveClass(`lucide-${icon}`);
  });
});
