import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "./tabs";

describe("Tabs", () => {
  it("keeps keyboard focus visible when navigation reaches the active panel", async () => {
    const user = userEvent.setup();
    render(
      <Tabs defaultValue="one">
        <TabsList aria-label="Example tabs">
          <TabsTrigger value="one">One</TabsTrigger>
          <TabsTrigger value="two">Two</TabsTrigger>
        </TabsList>
        <TabsContent value="one">First panel</TabsContent>
        <TabsContent value="two">Second panel</TabsContent>
      </Tabs>,
    );

    await user.tab();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Two" })).toHaveFocus();

    await user.tab();
    const panel = screen.getByRole("tabpanel", { name: "Two" });
    expect(panel).toHaveFocus();
    expect(panel).toHaveClass(
      "focus-visible:outline-2",
      "focus-visible:outline-offset-2",
      "focus-visible:outline-signal",
    );
  });

  it("scrolls a roving-focused trigger into view on arrow navigation", async () => {
    // Browsers scroll to sequentially-tabbed elements but not to
    // programmatically focused ones — Radix moves tab focus with focus(), so
    // the shared trigger must bridge the gap itself or keyboard users on
    // narrow viewports navigate clipped tabs they cannot see.
    const user = userEvent.setup();
    const scrollIntoView = vi.fn();
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scrollIntoView;
    try {
      render(
        <Tabs defaultValue="one">
          <TabsList aria-label="Example tabs">
            <TabsTrigger value="one">One</TabsTrigger>
            <TabsTrigger value="two">Two</TabsTrigger>
          </TabsList>
          <TabsContent value="one">First panel</TabsContent>
          <TabsContent value="two">Second panel</TabsContent>
        </Tabs>,
      );

      await user.tab();
      expect(scrollIntoView).toHaveBeenCalled();
      scrollIntoView.mockClear();

      await user.keyboard("{ArrowRight}");
      expect(screen.getByRole("tab", { name: "Two" })).toHaveFocus();
      expect(scrollIntoView).toHaveBeenCalledWith({
        block: "nearest",
        inline: "nearest",
      });
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });
});
