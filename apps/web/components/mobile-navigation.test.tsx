import type { AnchorHTMLAttributes } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    onClick,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a
      href={href}
      onClick={(event) => {
        event.preventDefault();
        onClick?.(event);
      }}
      {...props}
    />
  ),
}));

import { MobileNavigation } from "@/components/mobile-navigation";

function renderNavigation(pathname = "/settings/sessions") {
  return render(
    <MobileNavigation
      badge={<span aria-label="3 pending approvals">3</span>}
      pathname={pathname}
    />,
  );
}

describe("MobileNavigation", () => {
  it("names a deep route and exposes every grouped destination", async () => {
    const user = userEvent.setup();
    renderNavigation();

    expect(
      screen.getByText("Settings", { selector: "[data-mobile-current-section]" }),
    ).toBeVisible();
    const trigger = screen.getByRole("button", {
      name: "Open navigation. Current section: Settings",
    });

    await user.click(trigger);

    const drawer = screen.getByRole("dialog", { name: "Navigate Axis" });
    expect(within(drawer).getByRole("region", { name: "Operate" })).toBeInTheDocument();
    expect(within(drawer).getByRole("region", { name: "Data & Models" })).toBeInTheDocument();
    expect(within(drawer).getByRole("region", { name: "Governance" })).toBeInTheDocument();
    expect(within(drawer).getByRole("region", { name: "Platform" })).toBeInTheDocument();
    expect(within(drawer).getByRole("link", { name: "Settings" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(drawer).getByLabelText("3 pending approvals")).toBeInTheDocument();
  });

  it("closes on Escape and restores focus to the trigger", async () => {
    const user = userEvent.setup();
    renderNavigation("/policies/policy_egress");
    const trigger = screen.getByRole("button", {
      name: "Open navigation. Current section: Policies",
    });

    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "Navigate Axis" })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Navigate Axis" })).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });
  });

  it("closes after a destination is selected", async () => {
    const user = userEvent.setup();
    renderNavigation();
    const trigger = screen.getByRole("button", {
      name: "Open navigation. Current section: Settings",
    });

    await user.click(trigger);
    const drawer = screen.getByRole("dialog", { name: "Navigate Axis" });
    await user.click(within(drawer).getByRole("link", { name: "Agents" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Navigate Axis" })).not.toBeInTheDocument(),
    );
  });
});
