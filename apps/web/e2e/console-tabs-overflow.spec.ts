import { expect, test } from "@playwright/test";

import { expectNoHorizontalOverflow, expectTabStripKeyboardNavigable } from "./support/console-layout";

/*
 * Every console surface that uses the shared Tabs component must hold its
 * layout together at all project widths (desktop / mobile / tablet) and keep
 * its tab strip keyboard-reachable. Read-only: no writes, so the three
 * parallel projects can run these checks concurrently against demo data.
 *
 * The connector detail tabs are exercised with deliberately long identifiers
 * in connectors-lifecycle.spec.ts; this spec covers the remaining real
 * consumers of the shared Tabs root.
 */

test.describe("Axis live story: tabbed console layout hardening", () => {
  test.skip(
    process.env.AXIS_E2E_LIVE_API !== "1",
    "Set AXIS_E2E_LIVE_API=1 when the local Axis API is running.",
  );

  test("agent registry tabs stay inside the viewport", async ({ page }) => {
    await page.goto("/agents");
    await expect(page.getByRole("heading", { name: "Agents", exact: true })).toBeVisible();
    // The registry auto-selects the first agent, so its detail tabs render.
    const tabs = ["Overview", "Permissions & Guardrails", "Runs", "Evidence"];
    for (const name of tabs) {
      await expect(page.getByRole("tab", { name })).toBeVisible();
    }
    await expectNoHorizontalOverflow(page);
    await expectTabStripKeyboardNavigable(page, tabs);
    await expectNoHorizontalOverflow(page);
  });

  test("policy detail tabs stay inside the viewport", async ({ page, request }) => {
    const registry = await request.get(
      "http://127.0.0.1:8000/platform/policies?tenant_id=tenant_demo_manufacturing",
    );
    expect(registry.status()).toBe(200);
    const policies = (await registry.json()).policies as Array<{ policy_id: string }>;
    expect(policies.length).toBeGreaterThan(0);
    const policyId = policies[0].policy_id;

    await page.goto(`/policies/${encodeURIComponent(policyId)}`);
    await expect(
      page.getByRole("heading", { name: "Policy detail", exact: true }),
    ).toBeVisible();
    const tabs = ["Conditions", "Revisions", "Evaluate"];
    for (const name of tabs) {
      await expect(page.getByRole("tab", { name })).toBeVisible();
    }
    await expectNoHorizontalOverflow(page);
    await expectTabStripKeyboardNavigable(page, tabs);
    await expectNoHorizontalOverflow(page);
  });

  test("model routing tabs stay inside the viewport", async ({ page }) => {
    await page.goto("/model-routing");
    await expect(
      page.getByRole("heading", { name: "Models", exact: true }),
    ).toBeVisible();
    const tabs = ["Reference routing", "Live invocations"];
    for (const name of tabs) {
      await expect(page.getByRole("tab", { name })).toBeVisible();
    }
    await expectNoHorizontalOverflow(page);
    await expectTabStripKeyboardNavigable(page, tabs);
    await expectNoHorizontalOverflow(page);
  });

  test("platform settings tabs stay inside the viewport", async ({ page }) => {
    await page.goto("/settings");
    await expect(
      page.getByRole("heading", { name: "System status", exact: true }),
    ).toBeVisible();
    const tabs = ["Readiness", "Identity", "Deployment", "Support"];
    for (const name of tabs) {
      await expect(page.getByRole("tab", { name })).toBeVisible();
    }
    await expectNoHorizontalOverflow(page);
    await expectTabStripKeyboardNavigable(page, tabs);
    await expectNoHorizontalOverflow(page);
  });
});
