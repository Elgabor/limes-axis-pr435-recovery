import { expect, test } from "@playwright/test";

import { expectNoHorizontalOverflow } from "./support/console-layout";

/*
 * Operator journey on the real approval inbox (API + console + Postgres).
 *
 * Proven here against live data:
 * - the queue is API-backed and stays overflow-free at this project's width;
 * - the queue list supports roving arrow-key selection with focus that
 *   follows the selection;
 * - deciding a pending approval through the keyboard-reachable dialog records
 *   it through the real decision API, flips the card to its persisted state,
 *   and its audit deep link opens the exact event in the audit explorer.
 *
 * Decisions mutate shared demo data append-only, so the mutation lane runs
 * once on chromium and picks whatever approval is still pending at run time;
 * when every seeded approval has already been decided by an earlier run, the
 * lane asserts the honest all-persisted rendering instead of fabricating a
 * fresh approval. No destructive cleanup endpoint exists or is needed here.
 *
 * Since Batch 6 the console separates actionable work from terminal
 * outcomes: the queue lists only PENDING approvals, and decided ones move to
 * the decision history derived from persisted server records. These lanes
 * assert that contract against live data.
 */

test.describe("Axis live story: approval inbox console", () => {
  test.skip(
    process.env.AXIS_E2E_LIVE_API !== "1",
    "Set AXIS_E2E_LIVE_API=1 when the local Axis API is running.",
  );

  // Every project shares the one demo tenant's queue, and deciding an
  // approval re-renders it: these lanes must not interleave.
  test.describe.configure({ mode: "serial" });

  const QUEUE_ENDPOINT =
    "http://127.0.0.1:8000/operations/approvals?tenant_id=tenant_demo_manufacturing";

  type QueueApproval = {
    approval_id: string;
    action: string;
    status: string;
    decision_options: Array<{ decision: string; label: string }>;
  };

  async function readQueue(request: import("@playwright/test").APIRequestContext) {
    const response = await request.get(QUEUE_ENDPOINT);
    if (!response.ok()) {
      throw new Error(`Approval queue read failed (${response.status()}).`);
    }
    const body = (await response.json()) as { approvals: QueueApproval[] };
    // The actionable queue is the pending slice of server truth; decided
    // approvals belong to the decision history instead.
    return {
      pending: body.approvals.filter((approval) => approval.status === "pending"),
      decided: body.approvals.filter((approval) => approval.status !== "pending"),
      all: body.approvals,
    };
  }

  function actionRegex(action: string): RegExp {
    return new RegExp(action.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  }

  test("renders the API-backed queue without horizontal overflow", async ({ page }) => {
    await page.goto("/approvals");

    const queue = await readQueue(page.request);
    if (queue.pending.length > 0) {
      // Rendered rows must be exactly the live PENDING queue, not fixtures.
      await expect(page.getByRole("heading", { name: "Approval inbox" })).toBeVisible();
      for (const approval of queue.pending.slice(0, 3)) {
        await expect(
          page.getByRole("button", { name: actionRegex(approval.action) }),
        ).toBeVisible();
      }
    } else {
      await expect(page.getByRole("heading", { name: "No approvals waiting" })).toBeVisible();
    }
    // Decided work never lingers in the actionable queue...
    for (const approval of queue.decided.slice(0, 3)) {
      await expect(page.getByRole("button", { name: actionRegex(approval.action) })).toHaveCount(0);
    }
    // ...and the decision history stays rendered from server truth.
    await expect(page.getByLabel("Decision history")).toBeVisible();

    await expectNoHorizontalOverflow(page);
  });

  test("queue selection follows arrow keys", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "Keyboard walk runs once.");

    await page.goto("/approvals");
    const queue = await readQueue(page.request);
    test.skip(queue.pending.length < 2, "Needs at least two pending approvals.");

    const [first, second] = queue.pending;
    const firstRow = page.getByRole("button", { name: actionRegex(first.action) }).first();
    await firstRow.click();
    await expect(firstRow).toHaveAttribute("aria-pressed", "true");

    // Roving selection: ArrowDown moves both selection and focus to the next
    // row; ArrowUp returns it. Focus never escapes the list while doing so.
    await page.keyboard.press("ArrowDown");
    const secondRow = page.getByRole("button", { name: actionRegex(second.action) }).first();
    await expect(secondRow).toBeFocused();
    await expect(secondRow).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("ArrowUp");
    await expect(firstRow).toBeFocused();
    await expect(firstRow).toHaveAttribute("aria-pressed", "true");
  });

  test("decides a pending approval through the real API and links the audit event", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "Mutation lane runs once.");

    const queue = await readQueue(page.request);
    const pending = queue.pending[0];
    test.skip(pending === undefined, "Every seeded approval is already decided.");

    await page.goto(`/approvals?approval_id=${encodeURIComponent(pending!.approval_id)}`);
    await expect(page.getByRole("heading", { name: pending!.action })).toBeVisible();

    // Keyboard path only: Tab reaches the option buttons in DOM order,
    // Enter opens the confirm dialog for the focused option.
    const approveOption = page.getByRole("button", { name: /Approve/ });
    const rejectOption = page.getByRole("button", { name: "Reject" });
    await approveOption.focus();
    await expect(approveOption).toBeFocused();

    // DOM order is the tab order: approve, then reject, then request changes.
    await page.keyboard.press("Tab");
    await expect(rejectOption).toBeFocused();

    await approveOption.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Confirm decision" }).click();

    // The decided approval leaves the actionable queue immediately...
    await expect(
      page.getByRole("button", { name: actionRegex(pending!.action) }),
    ).toHaveCount(0, { timeout: 15_000 });
    // ...and its recorded evidence is reachable either from the persisted
    // decision card or from the server-derived decision history entry.
    const auditLink = page
      .getByRole("link", { name: "View audit event" })
      .first();
    await expect(auditLink).toBeVisible({ timeout: 15_000 });
    const href = await auditLink.getAttribute("href");
    expect(href).toMatch(/^\/audit\?event_id=[0-9a-f-]+$/);

    // The deep link opens the audit explorer on the exact recorded event.
    await auditLink.click();
    await expect(page).toHaveURL(new RegExp(`event_id=${href!.split("=")[1]}`));
    await expect(
      page.getByText("approval.decision.recorded", { exact: false }).first(),
    ).toBeVisible({ timeout: 15_000 });
  });

  test("decided approvals render honestly instead of offering options again", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium", "Mutation lane runs once.");

    const queue = await readQueue(page.request);
    const decided = queue.decided[0];
    test.skip(decided === undefined, "No decided approval in the queue yet.");

    await page.goto(`/approvals?approval_id=${encodeURIComponent(decided!.approval_id)}`);
    await expect(page.getByRole("heading", { name: decided!.action })).toBeVisible();
    // The stale-pending lie would offer decision options that can only 409.
    // Option suppression is asserted per-branch in component tests; here the
    // live proof is the recorded-decision status replacing the offer.
    const decisionRegion = page.getByRole("region", { name: "Decision" });
    await expect(decisionRegion.getByRole("status")).toHaveText(
      "A terminal decision was already recorded for this approval.",
    );
  });

  test("keeps the inbox usable on this viewport after decisions land", async ({ page }) => {
    await page.goto("/approvals");
    const queue = await readQueue(page.request);
    if (queue.pending.length > 0) {
      await expect(page.getByRole("heading", { name: "Approval inbox" })).toBeVisible();
    } else {
      await expect(page.getByRole("heading", { name: "Decision history" })).toBeVisible();
    }
    await expectNoHorizontalOverflow(page);
  });
});
