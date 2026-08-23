import { expect, test } from "@playwright/test";

import { scopedRunToken } from "./support/axis-api";
import { expectTabStripKeyboardNavigable, expectNoHorizontalOverflow } from "./support/console-layout";

/*
 * Operator journey against the real local stack (API + console + Postgres):
 * register a CSV connector through the wizard, watch the runs gate clear on
 * activation, and confirm live enablement stays honestly gated. Identifiers
 * are project-scoped and time-tokenized so the three parallel browser projects
 * never race on the same records; rows persist by design (append-only API)
 * under their `file_csv_e2e_lifecycle_` prefix.
 *
 * The demo deployment has no OIDC principal, so every write runs through the
 * API's demo-mode convention; SSO-denial surfaces are covered by component
 * tests instead of being fabricated here.
 */

test.describe("Axis live story: connector lifecycle journey", () => {
  test.skip(
    process.env.AXIS_E2E_LIVE_API !== "1",
    "Set AXIS_E2E_LIVE_API=1 when the local Axis API is running.",
  );

  // Required columns of the file_csv_manufacturing_assets mapping template.
  const CSV = [
    "asset_id,asset_name,domain,station,risk_level",
    "asset_e2e_001,E2E press,manufacturing,pres-01,low",
    "asset_e2e_002,E2E lathe,manufacturing,lat-02,medium",
    "",
  ].join("\n");

  test("registers a connector and clears the runs gate by activation", async ({ page }, testInfo) => {
    // Deliberately long identifiers: every layout assertion below also
    // exercises worst-case label width.
    const runToken = scopedRunToken(testInfo.project.name);
    const CONNECTOR_ID = `file_csv_e2e_lifecycle_long_identifier_${runToken}_press_shop_floor_orders`;
    const DISPLAY_NAME = `E2E lifecycle ${runToken} press shop floor orders weekly rollup mirror`;

    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/connectors");
    await expect(page.getByRole("heading", { name: "Connectors", exact: true })).toBeVisible();
    await expectNoHorizontalOverflow(page);

    // --- Registration through the real wizard -----------------------------
    await page.getByRole("button", { name: "Add connector" }).click();
    const dialog = page.getByRole("dialog", { name: "Add connector" });
    await dialog.getByRole("button", { name: /CSV file/ }).first().click();
    await dialog.getByRole("button", { name: "Next" }).click();

    await dialog.locator('input[type="file"]').setInputFiles({
      name: "e2e-lifecycle-assets.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(CSV),
    });
    await dialog.getByRole("button", { name: "Preview file" }).click();
    await expect(dialog.getByText("Preview ready")).toBeVisible({ timeout: 15_000 });
    await dialog.getByRole("button", { name: "Next" }).click();

    await dialog.getByLabel("Connector id").fill(CONNECTOR_ID);
    await dialog.getByLabel("Display name").fill(DISPLAY_NAME);
    await dialog.getByRole("button", { name: "Register connector" }).click();
    await expect(page.getByText("Connector registered")).toBeVisible({ timeout: 15_000 });
    await expect(dialog).not.toBeVisible();

    // --- Registered state: activation gate on the Runs tab ----------------
    await page.getByRole("button", { name: DISPLAY_NAME }).click();
    await expect(page.getByRole("heading", { name: DISPLAY_NAME })).toBeVisible();

    // Long identifiers must not push the page sideways at any project width,
    // and the tab strip stays keyboard-reachable with visible focus.
    await expectNoHorizontalOverflow(page);
    await expectTabStripKeyboardNavigable(page, [
      "Overview",
      "Data & Schema",
      "Runs",
      "Governance & Evidence",
    ]);
    await expectNoHorizontalOverflow(page);

    const lifecycle = page.getByRole("region", { name: "Activation state" }).or(
      page.getByLabel("Activation state"),
    );
    await expect(lifecycle).toBeVisible();
    await expect(lifecycle).toContainText("Registered Preview Only");
    await expect(lifecycle).toContainText("Registered for previews only.");

    // The fresh revision already appears as the trail's first entry.
    const history = page.getByRole("list", { name: "Revision history" });
    await expect(history).toBeVisible();
    await expect(history).toContainText("r1");
    await expect(history).toContainText("Registration recorded");
    // Registration is not a transition: the governed transition trail starts
    // empty until a lifecycle change is recorded.
    await expect(page.getByRole("list", { name: "Transition history" })).toHaveCount(0);

    await page.getByRole("tab", { name: "Runs" }).click();
    await expect(
      page.getByText(/registered but not activated yet/),
    ).toBeVisible();

    // --- Keyboard-driven activation ----------------------------------------
    await page.getByRole("tab", { name: "Overview" }).click();
    const activate = page.getByRole("button", { name: "Activate for previews" });
    await activate.focus();
    await page.keyboard.press("Enter");

    await expect(
      page.getByText("Active Preview", { exact: true }).first(),
    ).toBeVisible({ timeout: 15_000 });

    // The transition ledger now records the activation against its own
    // per-connector projection, separate from the revision trail.
    const transitions = page.getByRole("list", { name: "Transition history" });
    await expect(transitions).toBeVisible();
    await expect(transitions).toContainText("Active Preview");
    await expect(transitions).toContainText("Activated for previews");

    // --- The runs gate cleared to the next honest boundary -----------------
    await page.getByRole("tab", { name: "Runs" }).click();
    await expect(page.getByText(/registered but not activated yet/)).toHaveCount(0);
    // Activated but no credential lease yet: that is the remaining blocker.
    await expect(page.getByText(/needs an active credential lease/)).toBeVisible();

    // --- Live enablement stays honestly gated ------------------------------
    await page.getByRole("tab", { name: "Overview" }).click();
    await page.getByRole("button", { name: /Enable live sync/ }).click();

    const requirements = page.getByRole("list", { name: "Live-enablement requirements" });
    await expect(requirements).toBeVisible();
    await expect(requirements).toContainText("Missing");

    const enableLive = page.getByRole("button", { name: "Enable live operation" });
    await expect(enableLive).toBeDisabled();

    // Even complete evidence must not fake readiness while the runtime policy
    // blocks live operations — the submit stays gated.
    await page.getByLabel("Evidence references").fill(
      "approval:e2e-review\npolicy:e2e-egress\ncredential:vault://e2e/db",
    );
    await expect(enableLive).toBeDisabled();

    expect(pageErrors).toEqual([]);
  });

  test("connector list and detail stay usable on narrow viewports", async ({ page }) => {
    await page.goto("/connectors");
    await expect(page.getByRole("heading", { name: "Connectors", exact: true })).toBeVisible();

    // Open the first connector's detail and check the overview renders without
    // horizontal overflow at this project's viewport (desktop, mobile, tablet).
    await page.locator("button", { hasText: "File CSV" }).first().click();
    await expect(page.getByRole("tab", { name: "Overview" })).toBeVisible();
    await expectNoHorizontalOverflow(page);

    await page.getByRole("tab", { name: "Runs" }).click();
    await expectNoHorizontalOverflow(page);
  });
});
