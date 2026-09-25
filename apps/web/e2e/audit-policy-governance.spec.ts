import { expect, test, type Page } from "@playwright/test";

import { AXIS_API_BASE_URL, DEMO_TENANT_ID, scopedRunToken } from "./support/axis-api";
import { expectNoHorizontalOverflow } from "./support/console-layout";
import {
  createPersonaWithRealmRoles,
  deletePersona,
  type SsoPersona,
} from "./support/keycloak";

/*
 * Real-API, real-Keycloak governance lane for the audit explorer and the
 * policy authoring/revision surfaces, under a verified identity and tenant
 * (auth-required SSO stack).
 *
 * Proven here, end to end:
 * - a least-privilege persona authors and revises a real platform policy
 *   through the console (POST /platform/policies + revisions), with the
 *   registry and detail views reflecting server truth;
 * - an idempotent replay or explicit conflict when the same revision is
 *   submitted twice — never a fabricated third revision;
 * - the authored/revised evidence appearing in the audit ledger with the
 *   policy id surfaced in the event payload preview, reachable through a
 *   deep link (`?event_id=`) that survives a full reload;
 * - an exact missing-scope denial with actionable copy naming the permission
 *   the API's verified-scope decision required;
 * - tenant isolation: a verified principal bound to another tenant never sees
 *   this tenant's governance evidence;
 * - narrow-viewport layout holds without horizontal overflow on the audit
 *   surface and keyboard focus lands inside the page.
 *
 * Gate: AXIS_E2E_LIVE_API=1 and AXIS_E2E_SSO=1 with the local API (SSO,
 * auth-required) + web build + Keycloak running. Chromium-only: this lane
 * proves behavior; width-driven layout lanes cover responsive concerns.
 */

test.describe("Axis live story: governed audit and policy authoring", () => {
  const runToken = scopedRunToken("gov");
  const POLICY_ID = `e2e_gov_${runToken}`;
  const DISPLAY_NAME = `E2E Governance ${runToken}`;
  const SCREENSHOT_DIR = "../../docs/screenshots/audit-policy-governance-2026-08-22";

  let persona: SsoPersona;
  let denialPersona: SsoPersona;
  let foreignPersona: SsoPersona;

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
      usernamePrefix: "gov",
      lastName: "Governance Operator",
      roles: [
        "audit:read",
        "platform:policy:author",
        "platform:policy:read",
        "platform:policy:revise",
      ],
    });
    denialPersona = await createPersonaWithRealmRoles(request, {
      runToken,
      usernamePrefix: "govdeny",
      lastName: "No Audit Scope",
      // Deliberately no `audit:read` and no platform policy grants.
      roles: ["notifications:acknowledge"],
    });
    foreignPersona = await createPersonaWithRealmRoles(request, {
      runToken,
      usernamePrefix: "govforeign",
      lastName: "Foreign Tenant Auditor",
      roles: ["audit:read"],
      tenantId: `tenant_e2e_gov_other_${runToken}`,
    });
  });

  test.afterAll(async ({ request }) => {
    if (persona) {
      await deletePersona(request, persona);
    }
    if (denialPersona) {
      await deletePersona(request, denialPersona);
    }
    if (foreignPersona) {
      await deletePersona(request, foreignPersona);
    }
  });

  async function ssoLoginFromGate(
    page: Page,
    as: SsoPersona,
    path: string,
  ): Promise<void> {
    await page.goto(path);
    const gate = page.locator("[data-signin-gate]");
    await expect(gate).toBeVisible({ timeout: 15_000 });
    await gate.locator("[data-gate-sign-in]").click();
    await page.locator("#username").fill(as.username);
    await page.locator("#password").fill(as.password!);
    const callback = page.waitForResponse(
      (response) => response.url().includes("/identity/oidc/callback"),
      { timeout: 20_000 },
    );
    await page.getByRole("button", { name: /sign in/i }).click();
    const response = await callback;
    if (response.status() >= 400) {
      throw new Error(`SSO login failed at the Axis callback (${response.status()}).`);
    }
    await expect(page).toHaveURL(new RegExp(`${path.replace(/\//g, "\\/")}(\\?.*)?$`));
  }

  /**
   * Read the audit ledger through the signed-in page itself so the request
   * carries the real HTTP-only session cookie; returns the authored-event ids
   * for one policy id, resolved server-side rather than guessed client-side.
   */
  async function findAuthoredEventIds(
    page: Page,
    eventType: string,
    policyId: string,
  ): Promise<string[]> {
    return page.evaluate(
      async ({ api, tenant, type, policy }) => {
        const response = await fetch(
          `${api}/operations/audit/events?tenant_id=${encodeURIComponent(tenant)}`
            + `&limit=100&event_type=${encodeURIComponent(type)}`,
          { credentials: "include" },
        );
        if (!response.ok) {
          throw new Error(`Audit events read failed (${response.status}).`);
        }
        const body = (await response.json()) as {
          events?: Array<{
            audit_event_id: string;
            payload_preview?: Record<string, string>;
          }>;
        };
        return (body.events ?? [])
          .filter((event) => event.payload_preview?.policy_id === policy)
          .map((event) => event.audit_event_id);
      },
      { api: AXIS_API_BASE_URL, tenant: DEMO_TENANT_ID, type: eventType, policy: policyId },
    );
  }

  test("authors and revises a policy, then finds its evidence in the audit ledger", async ({
    page,
  }) => {
    await ssoLoginFromGate(page, persona, "/policies");

    // --- Author a real policy through the console ---------------------------
    await expect(
      page.getByRole("heading", { name: "Policies", exact: true }),
    ).toBeVisible({ timeout: 15_000 });
    await page.locator("summary").filter({ hasText: /^Create policy$/ }).click();
    await page.getByLabel("New policy id").fill(POLICY_ID);
    await page.getByLabel("New policy display name").fill(DISPLAY_NAME);
    await page
      .getByLabel("New policy description")
      .fill("Authored by the local governance e2e lane to prove authoring and audit trail.");
    // The API rejects empty rules; declare one real condition.
    await page.getByLabel("New policy action domains").fill("Operations");
    await page.getByRole("group", { name: "New policy risk levels" })
      .getByRole("button", { name: "high" })
      .click();
    await page.getByRole("button", { name: "Author policy" }).click();

    // The durable confirmation is derived from the refreshed registry.
    const authoredBanner = page.getByLabel("Policy authoring result");
    await expect(authoredBanner).toContainText("Policy authored as r1 / 1.0.0", {
      timeout: 15_000,
    });

    // The registry reads server truth: the new policy row links to its detail.
    const detailLink = page.getByRole("link", { name: DISPLAY_NAME }).first();
    await expect(detailLink).toHaveAttribute("href", `/policies/${POLICY_ID}`, {
      timeout: 15_000,
    });

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/policy-authored.png`,
      fullPage: true,
    });

    // --- Append one real revision ------------------------------------------
    await detailLink.click();
    await expect(
      page.getByRole("heading", { name: DISPLAY_NAME }),
    ).toBeVisible({ timeout: 15_000 });
    await page.getByRole("tab", { name: "Revisions" }).click();
    await page.getByLabel("Revision policy version").fill("1.1.0");
    await page.getByLabel("Revision display name").fill(DISPLAY_NAME);
    await page
      .getByLabel("Revision description")
      .fill("Revised by the local governance e2e lane.");
    await page.getByRole("button", { name: "Append revision" }).click();

    // The durable confirmation is derived from the refetched detail record.
    const revisedBanner = page.getByLabel("Policy revision result");
    await expect(revisedBanner).toContainText("Revision recorded: r2", {
      timeout: 15_000,
    });
    await expect(revisedBanner).toContainText("The active revision is r2");

    // --- Idempotent replay/conflict at the API contract level --------------
    // The console rotates the client-side key after every accepted write, so
    // key reuse is proven directly through the signed-in session: an exact
    // replay of the same key+payload returns the SAME revision without
    // appending, while the same key with a different payload conflicts.
    const replayProbe = await page.evaluate(async ({ api, tenant, policy }) => {
      // The API rebinds attribution to the verified principal and rejects
      // mismatches, so the probe carries the session's own actor id.
      const identityResponse = await fetch(`${api}/identity/session`, {
        credentials: "include",
      });
      const identity = (await identityResponse.json()) as { actor_id?: string };
      // Governed writes require the CSRF header paired with the readable
      // cookie, exactly like the console's own fetch layer.
      const csrfToken = document.cookie
        .split("; ")
        .find((entry) => entry.startsWith("axis_csrf="))
        ?.split("=")[1];
      const post = async (version: string) => {
        const response = await fetch(
          `${api}/platform/policies/${encodeURIComponent(policy)}/revisions`
            + `?tenant_id=${encodeURIComponent(tenant)}`,
          {
            method: "POST",
            credentials: "include",
            headers: {
              "Content-Type": "application/json",
              ...(csrfToken ? { "X-Axis-Csrf-Token": csrfToken } : {}),
            },
            body: JSON.stringify({
              tenant_id: tenant,
              policy_id: policy,
              policy_version: version,
              display_name: `E2E Governance replay ${version}`,
              description: "Replay probe from the governance e2e lane.",
              effect: "require_approval",
              conditions: { action_domains: ["Operations"], risk_levels: ["high"] },
              updated_by: identity.actor_id ?? "e2e-replay-probe",
              actor_scopes: ["platform:policy:revise"],
              idempotency_key: `${policy}-fixed-replay-key`,
              notes: [],
            }),
          },
        );
        return { status: response.status, body: await response.json() };
      };

      const first = await post("1.2.0");
      const replay = await post("1.2.0");
      const conflict = await post("1.3.0");
      return {
        firstStatus: first.status,
        firstRevision: (first.body as { revision_number?: number }).revision_number,
        replayStatus: replay.status,
        replayRevision: (replay.body as { revision_number?: number }).revision_number,
        replayFlag: (replay.body as { idempotent_replay?: boolean }).idempotent_replay,
        conflictStatus: conflict.status,
        conflictReason: (conflict.body as { detail?: { reason?: string } }).detail?.reason,
      };
    }, { api: AXIS_API_BASE_URL, tenant: DEMO_TENANT_ID, policy: POLICY_ID });

    expect(replayProbe.firstStatus, JSON.stringify(replayProbe)).toBe(201);
    expect(replayProbe.firstRevision).toBe(3);
    // Exact replay: the endpoint answers 200 with idempotent_replay=true and
    // no fourth revision is appended.
    expect(replayProbe.replayStatus).toBe(200);
    expect(replayProbe.replayFlag).toBe(true);
    expect(replayProbe.replayRevision).toBe(3);
    // Reused key with a different payload fails closed.
    expect(replayProbe.conflictStatus).toBe(409);
    expect(replayProbe.conflictReason).toBe("revision_idempotency_conflict");

    // Refreshing the detail reflects server truth: r3 / 1.2.0 is active.
    await page.reload();
    await expect(revisedBanner).toContainText("The active revision is r3 / 1.2.0", {
      timeout: 15_000,
    });

    // --- The governed writes are visible in the audit ledger ---------------
    await page.goto("/audit");
    await expect(
      page.getByRole("heading", { name: "Audit", exact: true }),
    ).toBeVisible({ timeout: 15_000 });
    const [authoredEventId] = await findAuthoredEventIds(
      page,
      "platform.policy.authored",
      POLICY_ID,
    );
    expect(authoredEventId).toBeTruthy();

    // Deep link straight into the exact event...
    await page.goto(`/audit?event_id=${encodeURIComponent(authoredEventId!)}`);
    await expect(page).toHaveURL(/event_id=[0-9a-f-]{36}/);
    const selectedRow = page.locator("[aria-pressed='true']");
    await expect(selectedRow).toHaveCount(1);
    // ...the payload preview names the policy it is evidence of...
    await expect(page.locator("[data-audit-detail]").getByText(POLICY_ID).first()).toBeVisible();

    // ...and the deep link survives a full reload.
    await page.reload();
    await expect(page.locator("[aria-pressed='true']")).toHaveCount(1);
    await expect(page.locator("[data-audit-detail]").getByText(POLICY_ID).first()).toBeVisible();

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/audit-event-deep-link.png`,
      fullPage: true,
    });

    // The revisions recorded their own ledger entries as well.
    const [revisedEventId] = await findAuthoredEventIds(
      page,
      "platform.policy.revised",
      POLICY_ID,
    );
    expect(revisedEventId).toBeTruthy();

    // --- Narrow viewport: layout holds and keyboard focus stays usable -----
    await page.setViewportSize({ width: 390, height: 844 });
    await expectNoHorizontalOverflow(page);
    await page.keyboard.press("Tab");
    await expect(page.locator(":focus")).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 800 });
  });

  test("denies the audit ledger without audit:read and names the permission", async ({
    browser,
  }) => {
    const context = await browser.newContext();
    const page = await context.newPage();

    await ssoLoginFromGate(page, denialPersona, "/audit");

    const denial = page.locator("[data-scope-denial]");
    await expect(denial).toBeVisible({ timeout: 15_000 });
    await expect(denial).toContainText(/roles do not include this permission/i);
    await expect(denial.locator("[data-required-permission]")).toContainText("audit:read");

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/audit-scope-denial.png`,
      fullPage: true,
    });
    await context.close();
  });

  test("a verified principal from another tenant never sees this governance evidence", async ({
    browser,
  }) => {
    const context = await browser.newContext();
    const page = await context.newPage();

    await ssoLoginFromGate(page, foreignPersona, "/audit");
    await expect(
      page.getByRole("heading", { name: "Audit", exact: true }),
    ).toBeVisible({ timeout: 15_000 });

    // Whatever honest empty/unbootstrapped state this tenant shows, the demo
    // tenant's authored policy must not leak into it.
    await page.waitForLoadState("networkidle").catch(() => {});
    await expect(page.getByText(POLICY_ID)).toHaveCount(0);
    await expect(page.getByText(DISPLAY_NAME)).toHaveCount(0);

    await context.close();
  });
});
