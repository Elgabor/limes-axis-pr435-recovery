import { expect, test } from "@playwright/test";

/*
 * Demo story 1 (plan task 6.4): the control room loads live data and hands
 * off into the approvals queue. Read-only — deciding approvals is covered by
 * live-overview.spec.ts, so this story never mutates the live tenant.
 */

test.describe("Axis live story: control room", () => {
  test.skip(
    process.env.AXIS_E2E_LIVE_API !== "1",
    "Set AXIS_E2E_LIVE_API=1 when the local Axis API is running.",
  );

  test("loads the live control room and reaches the approvals queue", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recorded activity" })).toBeVisible();

    // The attention strip resolves to items or the explicit all-clear state.
    await expect(
      page
        .getByText("Needs attention")
        .or(page.getByRole("heading", { name: "All clear — nothing waiting on you" }))
        .first(),
    ).toBeVisible();

    await page.goto("/approvals");
    await expect(page.getByRole("heading", { name: "Approvals", exact: true })).toBeVisible();
    // Queue renders live content: either pending approvals or the empty state
    // — never a blank surface or an error wall.
    await expect(
      page
        .getByText("Approval inbox")
        .or(page.getByRole("heading", { name: "No approvals waiting" }))
        .first(),
    ).toBeVisible();
    await expect(page.getByText("Approval API unavailable")).toHaveCount(0);

    expect(pageErrors).toEqual([]);
  });
});
