import { expect, test } from "@playwright/test";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

/*
 * Demo story 3 (plan task 6.4): bootstrapping the demo scenario into a fresh
 * tenant. The console has no tenant switcher, so the throwaway tenant is
 * exercised through the API directly (a fixed id keeps reruns idempotent —
 * the endpoint answers 200 + idempotent_replay instead of accumulating
 * records), and the UI check asserts the default tenant's Demo badge.
 */

const API_BASE_URL =
  process.env.NEXT_PUBLIC_AXIS_API_BASE_URL ?? "http://127.0.0.1:8000";
const E2E_TENANT_ID = "tenant_e2e_onboarding";

test.describe("Axis live story: onboarding demo bootstrap", () => {
  test.skip(
    process.env.AXIS_E2E_LIVE_API !== "1",
    "Set AXIS_E2E_LIVE_API=1 when the local Axis API is running.",
  );

  // The API story is viewport-independent and writes a shared tenant. Keep it
  // in the single-worker Chromium lane; the UI story still covers all projects.
  test("bootstraps the demo scenario into a throwaway tenant", {
    tag: "@stateful",
  }, async ({ request }) => {
    const response = await request.post(`${API_BASE_URL}/demo/bootstrap`, {
      data: {
        tenant_id: E2E_TENANT_ID,
        requested_by: "e2e-onboarding-story",
        actor_scopes: ["demo:scenario:bootstrap"],
      },
    });
    // 201 on the first run, 200 idempotent replay afterwards.
    expect([200, 201]).toContain(response.status());
    const record = await response.json();
    expect(record.tenant_id).toBe(E2E_TENANT_ID);
    expect(record.bootstrapped).toBe(true);
    expect(record.scenario).toBeTruthy();
    expect(record.idempotent_replay).toBe(response.status() === 200);

    const overview = await request.get(
      `${API_BASE_URL}${OPERATIONS_API_PREFIX}/overview?tenant_id=${E2E_TENANT_ID}`,
    );
    expect(overview.status()).toBe(200);
    const payload = await overview.json();
    expect(payload.scenario).toBe(record.scenario);
    expect(payload.plant_name).toBe(record.plant_name);
  });

  test("shows the Demo badge on the bootstrapped tenant's topbar", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
    const badge = page.locator(".ops-topbar").getByText("Demo", { exact: true });
    await expect(badge).toBeVisible();
    // The explanation is an accessible description rather than tooltip-only
    // content: Radix suppresses tooltips on touch, so a phone user would
    // otherwise never learn what the badge means.
    const described = await badge.getAttribute("aria-describedby");
    expect(described).toBeTruthy();
    await expect(page.locator(`#${described}`)).toHaveText(
      "This tenant runs the demo manufacturing scenario",
    );
  });
});
