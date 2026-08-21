import { expect, test, type Page } from "@playwright/test";
import { strings } from "@/lib/strings";

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    const clientWidth = root.clientWidth;
    const offenders = Array.from(document.querySelectorAll<HTMLElement>("body *"))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          className: element.className.toString(),
          left: Math.floor(rect.left),
          right: Math.ceil(rect.right),
          tagName: element.tagName.toLowerCase(),
          text: element.textContent?.trim().replace(/\s+/g, " ").slice(0, 90) ?? "",
          width: Math.ceil(rect.width),
        };
      })
      .filter((entry) => entry.right > clientWidth || entry.left < 0 || entry.width > clientWidth)
      .slice(0, 8);

    return {
      clientWidth,
      hasOverflow: root.scrollWidth > clientWidth,
      offenders,
      scrollWidth: root.scrollWidth,
    };
  });

  expect(overflow.hasOverflow, JSON.stringify(overflow, null, 2)).toBe(false);
}

test.describe("Axis live overview demo", () => {
  test.skip(
    process.env.AXIS_E2E_LIVE_API !== "1",
    "Set AXIS_E2E_LIVE_API=1 when the local Axis API is running.",
  );

  test("renders the persisted control room on the overview page", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/");

    // Single page header + slim hero: the cockpit name renders exactly once.
    await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
    await expect(page.getByText("Plant Operations Cockpit")).toHaveCount(1);
    await expect(page.locator("[data-hero-subtitle]")).toContainText("Ravenna Works");

    // The hero audit count and the evidence feed read the same registry.
    // "—" is the placeholder while the audit events query is still loading.
    await expect(page.getByTestId("hero-audit-count")).not.toHaveText("—");
    const heroAuditCount = await page.getByTestId("hero-audit-count").innerText();
    const visibleAuditCount = Math.min(Number(heroAuditCount.trim()), 10);
    await expect(
      page.getByText(`Showing ${visibleAuditCount} of ${heroAuditCount.trim()}`),
    ).toBeVisible();

    // Needs-attention strip with inline decision entry points.
    await expect(page.getByText("Needs attention")).toBeVisible();
    expect(await page.getByRole("button", { name: "Review & decide" }).count()).toBeGreaterThan(0);

    // Five posture cards, one link each.
    await expect(page.locator("[data-kpi-card]")).toHaveCount(5);
    await expect(page.getByRole("link", { name: /Manage agents/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /Review policies/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /View routing/ })).toBeVisible();

    // One evidence feed with deep links into the audit ledger.
    await expect(page.getByRole("heading", { name: "Recent audit evidence" })).toBeVisible();
    const firstEventHref = await page
      .locator("a[href^='/audit?event_id=']")
      .first()
      .getAttribute("href");
    expect(firstEventHref).toContain("/audit?event_id=");

    // Governed artifact runtime stays, gated on the unauthenticated session.
    await expect(page.getByRole("heading", { name: "Generate governed evidence" })).toBeVisible();
    await expect(page.getByText("OIDC session required")).toBeVisible();
    await expect(page.getByRole("button", { name: /Generate daily brief/ })).toBeDisabled();
    await expect(page.getByRole("button", { name: /Build quality scenario/ })).toBeDisabled();

    // Side rail: system health radar + quick actions.
    await expect(page.getByRole("heading", { name: "System health" })).toBeVisible();
    await expect(page.getByText("Quick actions")).toBeVisible();

    // Dropped surfaces stay dropped: domain graph, routing strip, readiness QA.
    await expect(page.getByRole("heading", { name: "Domain graph" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Persisted routing posture" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Feedback environment" })).toHaveCount(0);
    await expect(page.getByText(strings.overview.hero.error.title)).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    expect(pageErrors).toEqual([]);
  });

  // The seed owns one deterministic approval queue. Run this tagged write once
  // after the cross-viewport read-only pass instead of racing three projects.
  test("decides a live approval from the needs-attention strip with audit evidence", {
    tag: "@stateful",
  }, async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/");

    // Wait for the strip to resolve (items or the all-clear state) before
    // deciding whether there is an approval to exercise.
    await expect(
      page
        .getByText("Needs attention")
        .or(page.getByRole("heading", { name: "All clear — nothing waiting on you" }))
        .first(),
    ).toBeVisible();
    const reviewButtons = page.getByRole("button", { name: "Review & decide" });
    await expect(
      reviewButtons.first(),
      "The freshly seeded live tenant must expose a pending approval.",
    ).toBeVisible();

    // The sheet reuses the approvals decision card: consequences visible,
    // confirm dialog gating persistence.
    await reviewButtons.first().click();
    const optionButton = page
      .locator("section[aria-label='Decision'] button")
      .first();
    await expect(optionButton).toBeVisible();
    await optionButton.click();
    await expect(page.getByRole("button", { name: "Confirm decision" })).toBeVisible();
    await page.getByRole("button", { name: "Confirm decision" }).click();

    await expect(page.getByText("Recorded as evidence")).toBeVisible();
    // Scope to the decision card — the confirmation toast links to the same
    // audit event under the same label.
    await expect(
      page
        .locator("section[aria-label='Decision']")
        .getByRole("link", { name: "View audit event" }),
    ).toHaveAttribute("href", /\/audit\?event_id=/);

    expect(pageErrors).toEqual([]);
  });

  test("opens live platform utility panels without leaving the console", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();

    const topbarHeight = await page.locator(".ops-topbar").evaluate((element) =>
      Math.round(element.getBoundingClientRect().height),
    );
    expect(topbarHeight).toBeLessThanOrEqual(80);

    await page.getByRole("button", { name: "Open notifications" }).click();
    const notificationsPanel = page.locator('[aria-label="Notifications"]');
    await expect(notificationsPanel).toBeVisible();
    await expect(notificationsPanel.getByText("API required", { exact: true })).toHaveCount(0);
    await expect(notificationsPanel.locator(".topbar-popover-header")).toContainText("live");
    expect(await notificationsPanel.locator(".notification-row").count()).toBeGreaterThan(0);
    await expect(
      notificationsPanel.getByText("Sign in with SSO to acknowledge notifications."),
    ).toBeVisible();
    await expect(notificationsPanel.getByRole("button", { name: "Ack" }).first()).toBeDisabled();
    await expect(page.getByRole("link", { name: "Open audit evidence" })).toHaveAttribute(
      "href",
      "/audit",
    );
    const notificationsTopbarHeight = await page.locator(".ops-topbar").evaluate((element) =>
      Math.round(element.getBoundingClientRect().height),
    );
    expect(notificationsTopbarHeight).toBe(topbarHeight);

    await page.getByRole("button", { name: "Open operator account" }).click();
    await expect(page.locator('[aria-label="Operator account"]')).toBeVisible();
    await expect(page.getByText("Public evaluation operator")).toBeVisible();
    await expect(page.getByText("no_authenticated_api_actor")).toBeVisible();
    await expect(page.getByText("No authenticated API actor is attached.")).toBeVisible();
    const accountPanel = page.locator('[aria-label="Operator account"]');
    await expect(accountPanel.getByRole("link", { name: "Sign in with SSO" })).toHaveAttribute(
      "href",
      /\/identity\/oidc\/authorize/,
    );
    await expect(accountPanel.getByRole("link", { name: "Open SSO setup" })).toHaveAttribute(
      "href",
      /\/identity\/oidc\/onboarding/,
    );
    // The bearer-token form is demoted behind the "Developer access" collapsible.
    await accountPanel.getByRole("button", { name: "Developer access" }).click();
    await expect(accountPanel.getByRole("button", { name: "Attach bearer bridge" })).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });

  test("keeps the enterprise navigation stable while the live dashboard scrolls", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();

    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));

    const navigation = await page.evaluate(() => {
      const element = document.querySelector<HTMLElement>("[data-console-sidebar]");
      const mobileNavigation = document.querySelector<HTMLElement>("[data-mobile-navigation]");
      const statusBar = document.querySelector<HTMLElement>(".ops-topbar");
      const viewportWidth = window.innerWidth;

      if (!element) {
        return null;
      }

      const rect = element.getBoundingClientRect();
      return {
        bottom: Math.round(rect.bottom),
        display: window.getComputedStyle(element).display,
        height: Math.round(rect.height),
        navVisible: element.textContent?.includes("Connectors") ?? false,
        top: Math.round(rect.top),
        mobileNavigationBottom: mobileNavigation
          ? Math.round(mobileNavigation.getBoundingClientRect().bottom)
          : null,
        mobileNavigationVisible: mobileNavigation
          ? window.getComputedStyle(mobileNavigation).display !== "none"
          : false,
        statusBarTop: statusBar ? Math.round(statusBar.getBoundingClientRect().top) : null,
        viewportHeight: window.innerHeight,
        viewportWidth,
      };
    });

    expect(navigation).not.toBeNull();

    if ((navigation?.viewportWidth ?? 0) <= 920) {
      expect(navigation?.display).toBe("none");
      expect(navigation?.mobileNavigationVisible).toBe(true);
      expect(navigation?.statusBarTop).toBeGreaterThanOrEqual(
        (navigation?.mobileNavigationBottom ?? 0) - 1,
      );
      return;
    }

    expect(navigation?.display).not.toBe("none");
    expect(navigation?.top).toBe(0);
    expect(navigation?.bottom).toBe(navigation?.viewportHeight);
    expect(navigation?.height).toBe(navigation?.viewportHeight);
    expect(navigation?.navVisible).toBe(true);
  });

  test("keeps the live operations dashboard readable on laptop-width screens", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
    await expect(page.locator(".ops-dashboard-grid")).toBeVisible();
    await expect(page.locator("[data-kpi-card]")).toHaveCount(5);

    const dashboardLayout = await page.evaluate(() => {
      const dashboard = document.querySelector<HTMLElement>(".ops-dashboard-grid");
      const main = document.querySelector<HTMLElement>(".ops-dashboard-main");
      const rightRail = document.querySelector<HTMLElement>(".ops-right-rail");
      const kpiCards = Array.from(document.querySelectorAll<HTMLElement>("[data-kpi-card]"));

      const rect = (element: HTMLElement | null) => {
        if (!element) {
          return null;
        }

        const bounds = element.getBoundingClientRect();
        return {
          bottom: Math.round(bounds.bottom),
          height: Math.round(bounds.height),
          top: Math.round(bounds.top),
          width: Math.round(bounds.width),
        };
      };

      return {
        hasDashboard: Boolean(dashboard),
        hasMain: Boolean(main),
        hasRightRail: Boolean(rightRail),
        gridColumns: dashboard ? window.getComputedStyle(dashboard).gridTemplateColumns : "",
        kpiWidths: kpiCards.map((card) => Math.round(card.getBoundingClientRect().width)),
        main: rect(main),
        rightRail: rect(rightRail),
      };
    });

    expect(dashboardLayout.hasDashboard).toBe(true);
    expect(dashboardLayout.hasMain).toBe(true);
    expect(dashboardLayout.hasRightRail).toBe(true);
    expect(dashboardLayout.gridColumns.trim().split(/\s+/)).toHaveLength(1);
    expect(Math.min(...dashboardLayout.kpiWidths)).toBeGreaterThanOrEqual(170);
    expect(dashboardLayout.rightRail?.top ?? 0).toBeGreaterThan(
      dashboardLayout.main?.top ?? 0,
    );
    await expectNoHorizontalOverflow(page);
  });
});
