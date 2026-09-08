import { expect, test, type Page } from "@playwright/test";
import type { ManufacturingApprovalInbox } from "../lib/approval-demo";
import { expectNoHorizontalOverflow } from "./support/console-layout";

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


const api = process.env.AXIS_E2E_API_BASE_URL ?? "http://127.0.0.1:8000";
const endpoint = `${api}/operations/approvals?tenant_id=tenant_demo_manufacturing`;
const compact = (page: Page) => (page.viewportSize()?.width ?? 1280) < 1024;

// Runs in the read-only lane, before stateful decisions consume the three
// seeded approvals. Only the density test substitutes browser responses.
test.describe("approval review workspace", () => {
  test.skip(process.env.AXIS_E2E_LIVE_API !== "1", "Requires the isolated local API.");

  test("filters compose, preserve spaces, reset and survive browser history", async ({ page }) => {
    await page.goto("/approvals");
    const search = page.getByRole("searchbox", { name: "Search approvals" });
    await search.pressSequentially("quality hold");
    await expect(search).toHaveValue("quality hold");
    await expect(page.getByRole("status").filter({ hasText: "1 of 3 pending" })).toBeVisible();
    await page.getByRole("combobox", { name: "Risk", exact: true }).selectOption("medium");
    await expect(page.getByText("No pending approvals match these filters. Try another search or clear the filters.")).toBeVisible();
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await expect(search).toHaveValue("");
    await page.getByRole("combobox", { name: "Domain", exact: true }).selectOption({ label: "Quality" });
    const row = page.getByRole("button", { name: /Place Batch Q-1842/ });
    await row.click();
    await expect(page.getByRole("heading", { name: "Place Batch Q-1842 on quality hold" })).toBeVisible();
    if (compact(page)) {
      await expect(page.getByRole("region", { name: "Approval review", exact: true })).toBeFocused();
      await expect(search).toBeHidden();
      await page.getByRole("button", { name: "Back to approval inbox" }).click();
      await expect(row).toBeFocused();
    } else {
      await page.goBack();
    }
    await expect(page.getByRole("combobox", { name: "Domain", exact: true })).toHaveValue(/quality/i);
    await row.click();
    await page.goBack();
    await expect(search).toBeVisible();
    await expect(page).not.toHaveURL(/approval_id=/);
    await row.click();
    if (compact(page)) await page.getByRole("button", { name: "Back to approval inbox" }).click();
    await search.fill("quality");
    await expect(page).toHaveURL(/q=quality/);
    await page.goBack();
    await expect(search).toHaveValue("");
    await expectNoHorizontalOverflow(page);
  });

  test("direct link remains reviewable outside filters, including missing records", async ({ page }) => {
    const response = await page.request.get(endpoint);
    expect(response.ok()).toBe(true);
    const inbox = await response.json() as ManufacturingApprovalInbox;
    const approval = inbox.approvals[0];
    await page.goto(`/approvals?approval_id=${encodeURIComponent(approval.approval_id)}&q=unmatched`);
    await expect(page.getByRole("heading", { name: approval.action, exact: true })).toBeVisible();
    await expect(page.getByText("This linked approval is outside the current queue filters.")).toBeVisible();
    await page.getByRole("button", { name: "Clear queue filters" }).click();
    await expect(page).toHaveURL(/approval_id=/);
    await expect(page).not.toHaveURL(/q=/);
    await page.goto("/approvals?approval_id=missing-review-record");
    await expect(page.getByRole("heading", { name: "Requested approval is not in this queue" })).toBeVisible();
    if (compact(page)) {
      await page.getByRole("button", { name: "Back to approval inbox" }).click();
      await expect(page.getByRole("heading", { name: "Approval inbox", exact: true })).toBeFocused();
    }
    await expectNoHorizontalOverflow(page);
  });

  test("dense long records and sparse or empty queues remain readable", async ({ page }) => {
    const response = await page.request.get(endpoint);
    expect(response.ok()).toBe(true);
    const original = await response.json() as ManufacturingApprovalInbox;
    let inbox = structuredClone(original);
    inbox.approvals = Array.from({ length: 30 }, (_, index) => ({
      ...original.approvals[0],
      approval_id: `review-layout-${index}`,
      action: `${index + 1}. Review the delayed inbound manufacturing batch and coordinate an alternative delivery window`,
      owner_role: "manufacturing_operations_owner_with_a_very_long_role_identifier",
      required_permission: "manufacturing_operations_permission_with_a_very_long_identifier",
    }));
    await page.route("**/operations/approvals?**", (route) => route.fulfill({ json: inbox }));
    await page.goto("/approvals");
    await expect(page.getByRole("status").filter({ hasText: "30 of 30 pending" })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.getByRole("button", { name: /^30\. Review/ }).click();
    await page.getByRole("button", { name: "Decision trail", exact: true }).click();
    await expect(page.getByText(/manufacturing_operations_permission_with_a_very_long_identifier/).first()).toBeVisible();
    await expectNoHorizontalOverflow(page);
    const trail = page.getByRole("list", { name: "Decision stage rail" });
    const metadataWidths = await trail.locator("p").evaluateAll((paragraphs) => paragraphs.map((paragraph) => ({
      width: paragraph.clientWidth,
      scroll: paragraph.scrollWidth,
      parent: paragraph.parentElement!.clientWidth,
    })));
    for (const metadata of metadataWidths) {
      expect(metadata.scroll).toBeLessThanOrEqual(metadata.width + 1);
      expect(metadata.width).toBeLessThanOrEqual(metadata.parent + 1);
    }
    inbox = { ...original, approvals: [original.approvals[0]] };
    await page.goto("/approvals?q=");
    await expect(page.getByRole("status").filter({ hasText: "1 of 1 pending" })).toBeVisible();
    inbox = { ...original, approvals: [], decision_history: [] };
    await page.reload();
    await expect(page.getByRole("status").filter({ hasText: "0 of 0 pending" })).toBeVisible();
    await expect(page.getByRole("button", { name: /^Approve/ })).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
  });

  test("decision dialog can be reviewed and cancelled without a mutation", async ({ page }) => {
    let writes = 0;
    page.on("request", (request) => { if (request.method() === "POST" && request.url().includes("/approvals/")) writes += 1; });
    await page.goto("/approvals");
    await page.getByRole("button", { name: /Expedite supplier batch/ }).click();
    await page.getByRole("button", { name: /^Approve/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Confirm decision" })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    expect(writes).toBe(0);
  });
});
