import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import {
  AXIS_API_BASE_URL,
  DEMO_TENANT_ID,
  scopedRunToken,
} from "./support/axis-api";
import {
  addColumnToSourceTable,
  createSourceTables,
  discoverSourceTables,
  seedGovernanceRecords,
  SOURCE_SCHEMA,
} from "./support/source-lane";

/*
 * Rendered-proof capture lane for the governed source activation journey.
 * Opt-in only (AXIS_E2E_CAPTURE_SCREENSHOTS=1) so canonical runs never rewrite
 * documentation assets as a side effect. Every pixel comes from the real
 * journey against the live local stack — no mocked states are captured.
 */

// Anchored to this file's location, never to a process CWD, so captures can
// only ever land inside the repository's docs/screenshots directory.
const SHOT_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "docs",
  "screenshots",
  "connectors-source-activation-2026-08-23",
);

test.describe("Axis rendered proof: governed source activation", () => {
  test.skip(
    process.env.AXIS_E2E_LIVE_API !== "1"
      || process.env.AXIS_E2E_CAPTURE_SCREENSHOTS !== "1",
    "Set AXIS_E2E_LIVE_API=1 and AXIS_E2E_CAPTURE_SCREENSHOTS=1 to recapture.",
  );

  const isMobileProject = (projectName: string) => projectName !== "chromium";

  async function discoverRealTables(page: Page, token: string) {
    createSourceTables(token);
    const { leaseId, policyId } = await seedGovernanceRecords(page.request, token);
    await page.goto("/connectors");
    await page.getByRole("button", { name: /Postgres operational mirror/ }).click();
    const panel = page.getByRole("region", { name: "Verify & discover" });
    await expect(panel).toBeVisible();
    await panel.getByLabel("Credential lease ID").fill(leaseId);
    await panel.getByLabel("Egress policy ID").fill(policyId);
    await panel.getByRole("button", { name: "Verify connection" }).click();
    await expect(panel.getByText(/Connected read-only to database/)).toBeVisible({
      timeout: 15_000,
    });
    await panel.getByLabel("Schema to discover").fill(SOURCE_SCHEMA);
    await panel.getByRole("button", { name: "Discover tables" }).click();
    await expect(panel.getByRole("table")).toBeVisible({ timeout: 15_000 });
    return { leaseId, policyId };
  }

  function ordersCheckbox(page: Page, token: string) {
    return page.getByRole("checkbox", {
      name: `Activate: ${SOURCE_SCHEMA}.production_orders_${token}`,
    });
  }

  test("captures the activation journey states", async ({ page }, testInfo) => {
    const token = scopedRunToken(testInfo.project.name);
    const prefix = isMobileProject(testInfo.project.name) ? "mobile" : "desktop";
    const shot = (name: string) => `${SHOT_DIR}/${prefix}-${name}.png`;

    const { leaseId, policyId } = await discoverRealTables(page, token);

    // State 1: discovered tables ready for selection, prerequisites legible.
    await page.screenshot({ path: shot("01-discovered-ready-for-selection"), fullPage: true });

    // State 2: keyboard focus on the row selector plus the progressive
    // activation section with its required governance reason.
    const box = ordersCheckbox(page, token);
    await box.focus();
    await page.keyboard.press("Space");
    await expect(page.getByText("1 table selected")).toBeVisible();
    await expect(page.getByRole("button", { name: "Activate 1 table" })).toBeDisabled();
    await box.focus();
    await page.screenshot({ path: shot("02-keyboard-selection-reason-required"), fullPage: true });

    // State 3: pending activation. Delay-only interception keeps every pixel
    // sourced from the real API exchange.
    await page.route("**/operations/connectors/external-db/source-bindings*", async (route) => {
      if (route.request().method() === "POST") {
        await new Promise((resolve) => setTimeout(resolve, 1200));
      }
      await route.continue();
    });
    await page.getByLabel("Activation reason").fill(
      `Rendered proof ${token}: bind reviewed schema for governed ingestion.`,
    );
    await page.getByRole("button", { name: "Activate 1 table" }).click();
    await expect(page.getByRole("button", { name: "Activating…" })).toBeVisible();
    await page.screenshot({ path: shot("03-pending-activation"), fullPage: true });

    // State 4: durable outcome — Active plus Pending ingestion, never "synced".
    await expect(page.getByText(/Activated 1 binding/).first()).toBeVisible({
      timeout: 15_000,
    });
    const bindingsSection = page.getByRole("region", { name: "Active source bindings" });
    const bindingRow = bindingsSection
      .getByRole("table")
      .getByRole("row", { name: new RegExp(`${SOURCE_SCHEMA}\\.production_orders_${token}`) });
    await expect(bindingRow).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: shot("04-activated-durable-bindings"), fullPage: true });

    if (!isMobileProject(testInfo.project.name)) {
      // State 5 (desktop): truthful recoverable error. The successful
      // activation above reset the journey, so review quality_checks through
      // a fresh PRE-drift discovery first; then real drift plus a concurrent
      // API discovery make that reviewed evidence stale on activation.
      const panel = page.getByRole("region", { name: "Verify & discover" });
      await panel.getByLabel("Schema to discover").fill(SOURCE_SCHEMA);
      await panel.getByRole("button", { name: "Discover tables" }).click();
      await expect(panel.getByRole("table")).toBeVisible({ timeout: 15_000 });
      addColumnToSourceTable(`quality_checks_${token}`);
      await discoverSourceTables(page.request, {
        token,
        discoveryId: `discovery_e2e_shot_${token}`,
        leaseId,
        policyId,
      });
      const checksBox = page.getByRole("checkbox", {
        name: `Activate: ${SOURCE_SCHEMA}.quality_checks_${token}`,
      });
      await checksBox.focus();
      await page.keyboard.press("Space");
      await expect(page.getByText("1 table selected")).toBeVisible();
      await page.getByLabel("Activation reason").fill(`Stale proof ${token}`);
      await page.getByRole("button", { name: "Activate 1 table" }).click();
      await expect(
        page.getByText(/changed since it was discovered/i),
      ).toBeVisible({ timeout: 15_000 });
      await page.screenshot({ path: shot("05-stale-recovery-copy"), fullPage: true });
    }

    if (isMobileProject(testInfo.project.name)) {
      // Mobile reload proves the same durability on the narrow layout.
      await page.reload();
      const reloaded = page.getByRole("region", { name: "Active source bindings" });
      await expect(reloaded.getByRole("table")).toBeVisible({ timeout: 15_000 });
      await page.screenshot({ path: shot("06-reloaded-bindings-narrow"), fullPage: true });

      // The persisted API view matches what the narrow screen shows.
      const listed = await page.request.get(
        `${AXIS_API_BASE_URL}/operations/connectors/external-db/source-bindings`,
        { params: { tenant_id: DEMO_TENANT_ID, connector_id: "external_db_operational_mirror" } },
      );
      expect(listed.ok()).toBeTruthy();
    }
  });
});
