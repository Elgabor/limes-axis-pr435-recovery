import { expect, test } from "@playwright/test";

/*
 * Demo story 2 (plan task 6.4): the connector registry renders live records
 * and the Add Connector wizard opens with both source types. Read-only — the
 * registration write path is verified against the live API elsewhere.
 */

test.describe("Axis live story: connectors", () => {
  test.skip(
    process.env.AXIS_E2E_LIVE_API !== "1",
    "Set AXIS_E2E_LIVE_API=1 when the local Axis API is running.",
  );

  test("lists live connectors and opens the Add Connector wizard", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/connectors");
    await expect(page.getByRole("heading", { name: "Connectors", exact: true })).toBeVisible();

    // At least one live reference-registry entry. A reference connector is not
    // mislabeled as a persisted manifest registration.
    await expect(
      page.getByRole("button", { name: /Manufacturing assets CSV/ }),
    ).toBeVisible();

    await page.getByRole("button", { name: "Add connector" }).click();
    await expect(page.getByText("What are you connecting?")).toBeVisible();
    await expect(page.getByText("CSV file", { exact: true })).toBeVisible();
    await expect(page.getByText("External database", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByText("What are you connecting?")).toHaveCount(0);

    expect(pageErrors).toEqual([]);
  });
});
