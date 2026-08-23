import { expect, test, type Page } from "@playwright/test";

import { scopedRunToken } from "./support/axis-api";
import {
  createPersonaWithRealmRoles,
  deletePersona,
  type SsoPersona,
} from "./support/keycloak";

/*
 * The friendly enforced-auth entry: with AXIS_OIDC_AUTH_REQUIRED=true the API
 * still answers GET /identity/session for anonymous browsers, so the console
 * renders ONE sign-in gate instead of generic error panels.
 *
 * Proven here against the real local Keycloak (authorization code + PKCE):
 * - an unauthenticated deep link shows the gate with the classified reason and
 *   preserves the return path; no tenant surface mounts behind it;
 * - a real SSO login lands back on the deep-linked page with API-verified
 *   operator content;
 * - signing out returns to the gate without stale tenant data;
 * - a tampered session cookie is reported as invalid, never honored.
 *
 * Gate: set AXIS_E2E_LIVE_API=1 and AXIS_E2E_SSO=1 with the local API (SSO,
 * auth-required) + web + Keycloak stack running. Chromium-only: this lane
 * proves behavior, not layout.
 */

test.describe("Axis enforced-auth sign-in gate", () => {
  const runToken = scopedRunToken("gate");
  let persona: SsoPersona;

  test.beforeEach(async ({}, testInfo) => {
    test.skip(
      process.env.AXIS_E2E_LIVE_API !== "1" || process.env.AXIS_E2E_SSO !== "1",
      "Set AXIS_E2E_LIVE_API=1 and AXIS_E2E_SSO=1 with the local auth-required stack running.",
    );
    test.skip(testInfo.project.name !== "chromium", "Chromium-only lane.");
  });

  test.beforeAll(async ({ request }) => {
    if (
      process.env.AXIS_E2E_LIVE_API !== "1"
      || process.env.AXIS_E2E_SSO !== "1"
      || test.info().project.name !== "chromium"
    ) {
      return;
    }
    persona = await createPersonaWithRealmRoles(request, {
      runToken,
      usernamePrefix: "gate",
      roles: ["audit:read", "supply:read", "workflows:read"],
      lastName: "Gate Operator",
    });
  });

  test.afterAll(async ({ request }) => {
    if (persona) {
      await deletePersona(request, persona);
    }
  });

  async function ssoLogin(page: Page): Promise<void> {
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
    await page.locator("#username").fill(persona.username);
    await page.locator("#password").fill(persona.password!);
    const callback = page.waitForResponse(
      (response) => response.url().includes("/identity/oidc/callback"),
      { timeout: 20_000 },
    );
    await page.getByRole("button", { name: /sign in/i }).click();
    const response = await callback;
    if (response.status() >= 400) {
      throw new Error(`SSO login failed at the Axis callback (${response.status()}).`);
    }
  }

  async function signOutViaAccountPanel(page: Page): Promise<void> {
    await page.locator("[data-operator-initials]").first().click();
    await page.getByRole("button", { name: /sign out with identity provider/i }).click();
    // Without an id_token_hint Keycloak 26 asks the browser to confirm the
    // federated logout; confirming is what a real operator does too.
    const confirm = page.getByRole("button", { name: "Logout" });
    try {
      await confirm.click({ timeout: 5_000 });
    } catch {
      // Some IdP configurations log out without an interstitial.
    }
    // Federated logout round-trips through Keycloak back into the gate.
    await expect(page.locator("[data-signin-gate]")).toBeVisible({ timeout: 20_000 });
  }

  test("unauthenticated deep link gates, SSO unlocks it, logout re-gates", async ({ page }) => {
    // 1. Anonymous visit to a tenant surface: one gate, no doomed queries.
    await page.goto("/approvals");
    const gate = page.locator("[data-signin-gate]");
    await expect(gate).toBeVisible({ timeout: 15_000 });
    await expect(gate.getByText("No active session was found")).toBeVisible();
    // The deep link survives into the authorize redirect...
    const signInHref = await gate.locator("[data-gate-sign-in]").getAttribute("href");
    expect(signInHref).toContain("return_to=%2Fapprovals");
    // ...and no console surface renders behind the gate.
    await expect(page.getByRole("heading", { name: "Approvals", exact: true })).toHaveCount(0);

    await page.screenshot({
      path: "../../docs/screenshots/sso-sign-in-gate-2026-08-22/gate-unauthenticated.png",
      fullPage: true,
    });

    // 2. Real PKCE login from the gate itself.
    await gate.locator("[data-gate-sign-in]").click();
    await ssoLogin(page);

    // Back on the deep-linked approvals surface under the verified principal.
    await expect(page).toHaveURL(/\/approvals$/);
    await expect(
      page.getByRole("heading", { name: "Approvals", exact: true }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("[data-signin-gate]")).toHaveCount(0);
    // The account row names the API-verified actor, not a demo placeholder.
    await expect(page.locator("[data-operator-initials]").first()).not.toBeEmpty();

    await page.screenshot({
      path: "../../docs/screenshots/sso-sign-in-gate-2026-08-22/console-authenticated.png",
      fullPage: true,
    });

    // 3. Signing out returns to the gate; no tenant rows linger on screen.
    await signOutViaAccountPanel(page);
    await expect(page.getByText("No active session was found")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Approvals", exact: true }),
    ).toHaveCount(0);

    await page.screenshot({
      path: "../../docs/screenshots/sso-sign-in-gate-2026-08-22/gate-after-logout.png",
      fullPage: true,
    });
  });

  test("a tampered session cookie is reported as invalid, not honored", async ({ page }) => {
    await page.goto("/approvals");
    await expect(page.locator("[data-signin-gate]")).toBeVisible();

    await page.context().addCookies([{
      name: "axis_session",
      value: "tampered-cookie-from-lane",
      domain: "127.0.0.1",
      path: "/",
    }]);
    await page.reload();

    const gate = page.locator("[data-signin-gate]");
    await expect(gate).toBeVisible();
    await expect(gate.getByText("Your session is no longer valid")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Approvals", exact: true }),
    ).toHaveCount(0);
  });
});
