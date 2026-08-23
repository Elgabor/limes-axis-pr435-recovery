import { expect, type Page } from "@playwright/test";

/*
 * Shared layout assertions for live console lanes. The document must never
 * require sideways scrolling; content may still scroll inside its own
 * containers (the tab strip does exactly that on purpose).
 */

export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}

/**
 * Walk a tab strip with the keyboard and assert every trigger — including the
 * last one — ends up focused and scrolled into view. Radix moves focus with
 * the arrow keys and the list scrolls to keep the focused trigger visible.
 * When the strip genuinely overflows its container this proves tab-strip
 * scrolling; everywhere it proves keyboard reachability with visible focus.
 */
export async function expectTabStripKeyboardNavigable(
  page: Page,
  tabNames: string[],
): Promise<void> {
  const first = page.getByRole("tab", { name: tabNames[0] }).first();
  await first.click();
  await expect(first).toBeFocused();

  const list = first.locator("xpath=..");
  const { scrollWidth, clientWidth } = await list.evaluate(
    (element) => ({
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
    }),
  );

  for (const name of tabNames.slice(1)) {
    await page.keyboard.press("ArrowRight");
    const trigger = page.getByRole("tab", { name }).first();
    await expect(trigger).toBeFocused();
    // The focused trigger must end up fully inside the strip's visible area,
    // so both the label and its focus ring are readable. Radix scrolls the
    // strip asynchronously after focus, so poll instead of asserting once.
    await expect
      .poll(
        async () => {
          const triggerBox = await trigger.boundingBox();
          const listBox = await list.boundingBox();
          if (triggerBox === null || listBox === null) {
            return false;
          }
          return (
            triggerBox.x >= listBox.x - 1
            && triggerBox.x + triggerBox.width <= listBox.x + listBox.width + 1
          );
        },
        { timeout: 5_000 },
      )
      .toBe(true);
  }

  if (scrollWidth > clientWidth) {
    const finalScrollLeft = await list.evaluate((element) => element.scrollLeft);
    expect(finalScrollLeft).toBeGreaterThan(0);
  }

  // Restore the starting selection so a lane can keep asserting the first
  // tab's content right after the walk.
  await first.click();
  await expect(first).toBeFocused();
}
