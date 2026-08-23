import { expect, test } from "@playwright/test";

import {
  AXIS_API_BASE_URL,
  fetchManifestDetail,
  registerCsvManifest,
  scopedRunToken,
} from "./support/axis-api";
import {
  createForeignTenantPersona,
  createLifecycleOnlyPersona,
  deletePersona,
  ensureTenantAttributeInUserProfile,
} from "./support/keycloak";

/*
 * Real SSO denial journey: a verified Keycloak principal that carries
 * `connectors:manifest:lifecycle` but NOT `connectors:manifest:enable_live`
 * drives the real console through the real authorization-code + PKCE login.
 *
 * Proven here, end to end:
 * - the API verifies the session cookie against Keycloak's JWKS and re-stamps
 *   the request with the *verified* scopes (body-declared scopes never win);
 * - activating previews succeeds for this persona;
 * - enabling live operation is denied 403 with the exact
 *   `missing_manifest_live_scope` reason, and the console renders the distinct
 *   actionable copy plus the API request reference;
 * - no transition or audit success is fabricated for the denied submit;
 * - a verified principal bound to another tenant cannot see the connector.
 *
 * The throwaway personas are created through the local Keycloak admin seam
 * (support/keycloak.ts) and deleted in cleanup; Axis-side records persist
 * locally by design under their `e2e_sso_` prefixes.
 */

test.describe("Axis live story: SSO-gated connector lifecycle", () => {
  const runToken = scopedRunToken("sso");
  const CONNECTOR_ID = `file_csv_e2e_sso_${runToken}`;
  const DISPLAY_NAME = `E2E SSO ${runToken}`;

  let persona: Awaited<ReturnType<typeof createLifecycleOnlyPersona>>;
  let foreignPersona: Awaited<ReturnType<typeof createForeignTenantPersona>>;

  test.beforeEach(async ({}, testInfo) => {
    test.skip(
      process.env.AXIS_E2E_LIVE_API !== "1" || process.env.AXIS_E2E_SSO !== "1",
      "Set AXIS_E2E_LIVE_API=1 and AXIS_E2E_SSO=1 with the local API + Keycloak stack running.",
    );
    // The SSO journey proves behavior, not layout; it runs once while the
    // width-driven lanes cover responsive concerns in parallel.
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
    await ensureTenantAttributeInUserProfile(request);
    persona = await createLifecycleOnlyPersona(request, runToken);
    foreignPersona = await createForeignTenantPersona(request, runToken);
    // The foreign tenant must exist so its verified session reads an empty
    // registry instead of an unbootstrapped-tenant failure.
    const bootstrap = await request.post(`${AXIS_API_BASE_URL}/demo/manufacturing/bootstrap`, {
      data: {
        tenant_id: `tenant_e2e_sso_other_${runToken}`,
        requested_by: "e2e-sso-denial-lane",
        actor_scopes: ["demo:scenario:bootstrap"],
      },
    });
    if (!bootstrap.ok()) {
      throw new Error(`Foreign tenant bootstrap failed (${bootstrap.status()}).`);
    }
    // Seed a live-capable manifest so active_preview offers live enablement.
    const registration = await registerCsvManifest(request, {
      connectorId: CONNECTOR_ID,
      displayName: DISPLAY_NAME,
      liveCapable: true,
    });
    if (registration.status !== 201) {
      throw new Error(`Manifest registration failed (${registration.status}).`);
    }
  });

  test.afterAll(async ({ request }) => {
    if (persona) {
      await deletePersona(request, persona);
    }
    if (foreignPersona) {
      await deletePersona(request, foreignPersona);
    }
  });

  async function ssoLogin(page: import("@playwright/test").Page, as: typeof persona): Promise<void> {
    await page.goto(`${AXIS_API_BASE_URL}/identity/oidc/authorize?return_to=/`);
    await page.locator("#username").fill(as.username);
    await page.locator("#password").fill(as.password!);
    // Wait for the full redirect chain: submitting the form fires a
    // cross-origin navigation through the Axis callback, and navigating away
    // early would abort it mid-flight and silently stay unauthenticated.
    const callback = page.waitForResponse(
      (response) => response.url().includes("/identity/oidc/callback"),
      { timeout: 20_000 },
    );
    await page.getByRole("button", { name: /sign in/i }).click();
    const response = await callback;
    // Success is the 307 redirect to the return path (cookies set); anything
    // 4xx/5xx is a real login failure.
    if (response.status() >= 400) {
      throw new Error(`SSO login failed at the Axis callback (${response.status()}).`);
    }
    // Session cookies are host-scoped, so console XHRs on :3100 carry them
    // automatically from here on.
  }

  test("denies live enablement with exact reason, copy and reference", async ({ page }) => {
    // Capture every governed lifecycle POST from the start: activation first,
    // then the denied enable-live attempt.
    const lifecycleResponses: number[] = [];
    page.on("response", (response) => {
      if (response.url().includes("/lifecycle") && response.request().method() === "POST") {
        lifecycleResponses.push(response.status());
      }
    });

    await ssoLogin(page, persona);

    // --- The real console now operates under the verified principal --------
    await page.goto("/connectors");
    await expect(page.getByRole("heading", { name: "Connectors", exact: true })).toBeVisible();
    await page.getByRole("button", { name: DISPLAY_NAME }).click();
    await expect(page.getByRole("heading", { name: DISPLAY_NAME })).toBeVisible();
    const lifecycleSection = page.getByRole("region", { name: "Activation state" }).or(
      page.locator("section", { has: page.getByRole("list", { name: "Transition history" }) }),
    );

    // Activation is allowed: the persona carries the lifecycle scope. This
    // also proves the API re-stamps verified scopes over body-declared ones.
    await page.getByRole("button", { name: "Activate for previews" }).click();
    // Status pill, revision trail and transition trail all flip together.
    await expect(
      lifecycleSection.getByText("Active Preview", { exact: true }).first(),
    ).toBeVisible({ timeout: 15_000 });
    // Exactly the activation reached the API so far.
    await expect.poll(() => lifecycleResponses).toEqual([200]);

    // --- Live enablement: every UI gate passes, the API still denies -------
    await page.getByRole("button", { name: /Enable live sync/ }).click();
    const requirements = page.getByRole("list", { name: "Live-enablement requirements" });
    await expect(requirements).toContainText("Met");

    await page
      .getByLabel("Evidence references")
      .fill("approval:e2e-live\npolicy:e2e-egress\ncredential:vault://e2e/db");
    const submit = page.getByRole("button", { name: "Enable live operation" });
    await expect(submit).toBeEnabled();
    await submit.click();

    // a) The API returned the exact missing-scope denial class as the second
    // governed POST (poll: the response lands just after the click resolves).
    await expect.poll(() => lifecycleResponses).toEqual([200, 403]);

    // b) ...and the console renders the distinct actionable copy...
    const alert = page.getByRole("tabpanel").getByRole("alert");
    await expect(alert).toContainText(
      "Enabling live operation additionally requires the enable-live scope",
    );
    // c) ...with the API request reference displayed.
    await expect(alert).toContainText(/Request reference: req_[0-9a-f]+/);

    // d) No transition or audit success was fabricated: the pill stands and
    // the transition trail still holds only the activation.
    await expect(
      lifecycleSection.getByText("Active Preview", { exact: true }).first(),
    ).toBeVisible();
    const transitions = page.getByRole("list", { name: "Transition history" });
    await expect(transitions).toContainText("Active Preview");
    await expect(transitions).not.toContainText("Live operation enabled");

    const detail = (await fetchManifestDetail(page.request, CONNECTOR_ID)) as {
      current_revision?: { status?: string };
      transitions?: unknown[];
    };
    expect(detail?.current_revision?.status).toBe("active_preview");
    expect(detail?.transitions).toHaveLength(1);
  });

  test("a principal bound to another tenant cannot see the connector", async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await ssoLogin(page, foreignPersona);

    // Every registry read binds to the verified tenant, so the connector that
    // exists in the demo tenant is invisible here — a direct deep link degrades
    // to the honest missing-record state instead of leaking another tenant's
    // record.
    await page.goto(`/connectors?connector_id=${encodeURIComponent(CONNECTOR_ID)}`);
    await expect(
      page.getByText("Requested connector is not in this registry"),
    ).toBeVisible();
    await context.close();
  });
});
