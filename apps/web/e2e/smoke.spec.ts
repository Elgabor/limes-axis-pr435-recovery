import { expect, test, type Page } from "@playwright/test";
import { strings } from "@/lib/strings";
import { OPERATIONS_API_PREFIX } from "@/lib/tenant-scope";

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

/**
 * WCAG 2.2 SC 2.5.8 (Target Size, Minimum): standalone controls need at least a
 * 24x24 CSS px target. Links inline in a sentence are exempt, which is why this
 * ignores anchors sitting inside a paragraph of prose.
 */
async function expectNoUndersizedTargets(page: Page) {
  const undersized = await page.evaluate(() => {
    const offenders: string[] = [];
    for (const element of document.querySelectorAll<HTMLElement>("button, a, [role=button]")) {
      const rect = element.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      if (rect.height >= 24 && rect.width >= 24) continue;
      const inlineInProse =
        element.tagName === "A" && element.closest("p") !== null;
      if (inlineInProse) continue;
      offenders.push(
        `${element.tagName.toLowerCase()} ${Math.round(rect.width)}x${Math.round(rect.height)} ` +
          `"${(element.textContent ?? "").trim().slice(0, 30)}" .${element.className.toString().slice(0, 70)}`,
      );
    }
    return offenders;
  });

  expect(undersized, undersized.join("\n")).toEqual([]);
}

async function expectMobileHeadersStacked(page: Page) {
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));

  const geometry = await page.evaluate(() => {
    const navigation = document.querySelector<HTMLElement>("[data-mobile-navigation]");
    const statusBar = document.querySelector<HTMLElement>(".ops-topbar");
    const trigger = document.querySelector<HTMLElement>("[data-mobile-navigation-trigger]");

    if (!navigation || !statusBar || !trigger) {
      return null;
    }

    const navigationRect = navigation.getBoundingClientRect();
    const statusBarRect = statusBar.getBoundingClientRect();
    const triggerRect = trigger.getBoundingClientRect();
    const hit = document.elementFromPoint(
      triggerRect.left + triggerRect.width / 2,
      triggerRect.top + triggerRect.height / 2,
    );

    return {
      navigationBottom: Math.round(navigationRect.bottom),
      navigationTop: Math.round(navigationRect.top),
      statusBarTop: Math.round(statusBarRect.top),
      triggerHit: hit === trigger || (hit instanceof Node && trigger.contains(hit)),
    };
  });

  expect(geometry).not.toBeNull();
  expect(geometry?.navigationTop).toBe(0);
  expect(geometry?.statusBarTop).toBeGreaterThanOrEqual((geometry?.navigationBottom ?? 0) - 1);
  expect(geometry?.triggerHit).toBe(true);
}

async function expectNavigationDestination(
  page: Page,
  label: string,
  href: string,
) {
  const desktopLink = page.locator(".sidebar").getByRole("link", {
    name: label,
    exact: true,
  });
  if (await desktopLink.isVisible()) {
    await expect(desktopLink).toHaveAttribute("href", href);
    return;
  }

  const trigger = page.locator("[data-mobile-navigation-trigger]");
  await expect(trigger).toBeVisible();
  await trigger.click();
  const drawer = page.getByRole("dialog", { name: "Navigate Axis" });
  await expect(drawer.getByRole("link", { name: label, exact: true })).toHaveAttribute(
    "href",
    href,
  );
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
}

async function expectAxisLightShell(page: Page) {
  const shell = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    const axisMark = document.querySelector<SVGSVGElement>(".sidebar .axis-mark");
    const axisDiamond = document.querySelector<SVGRectElement>(".sidebar .axis-mark rect");

    return {
      axisMarkPresent: Boolean(axisMark),
      axisDiamondFill: axisDiamond ? getComputedStyle(axisDiamond).fill : null,
      bodyBackground: getComputedStyle(document.body).backgroundColor,
      colorScheme: root.colorScheme,
      signalChannels: root.getPropertyValue("--signal").trim(),
      theme: document.documentElement.dataset.theme ?? null,
    };
  });

  expect(shell).toEqual({
    axisMarkPresent: true,
    axisDiamondFill: "rgb(47, 100, 255)",
    bodyBackground: "rgb(247, 248, 251)",
    colorScheme: "light",
    signalChannels: "47 100 255",
    theme: "light",
  });
}

const identitySessionUrl = "http://127.0.0.1:65534/identity/session";

async function routeVerifiedIdentity(page: Page, tenantId: string | null = null) {
  const authenticated = tenantId !== null;
  await page.route(identitySessionUrl, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        authenticated,
        mode: authenticated ? "secure_oidc_cookie" : "public_demo",
        actor_id: authenticated ? "operator-e2e" : null,
        tenant_id: tenantId,
        scopes: authenticated ? ["tenant:read"] : [],
        expires_at: authenticated ? 4102444800 : null,
        api_auth_required: authenticated,
        enterprise_sso_ready: true,
        readiness_status: "watch",
        issuer: "https://idp.example/realms/axis",
        audience: "limes-axis-api",
        jwks_source: "configured",
        session_boundary: "http_only_cookie_verified_by_axis_api",
        capabilities: [],
        limitations: [],
        notes: [],
        unauthenticated_reason: null,
      },
      status: 200,
    });
  });
}

async function routeVerifiedDemoIdentity(page: Page) {
  await routeVerifiedIdentity(page);
}

test.describe("Axis console smoke", () => {
  test.beforeEach(async ({ page }) => {
    // Tenant-scoped feature tests start from an API-verified public-demo
    // identity. Identity-failure and authenticated-session tests replace it.
    await routeVerifiedDemoIdentity(page);
  });

  test("requires the overview APIs section by section instead of local data", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    // Explicitly model an auth-optional public-demo session. The overview may
    // use the demo tenant only after the identity API confirms this state;
    // transport failures must remain fail-closed instead.
    await page.route("http://127.0.0.1:65534/identity/session", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        json: {
          authenticated: false,
          mode: "public_demo",
          actor_id: null,
          tenant_id: null,
          scopes: [],
          expires_at: null,
          api_auth_required: false,
          enterprise_sso_ready: true,
          readiness_status: "watch",
          issuer: "https://idp.example/realms/axis",
          audience: "limes-axis-api",
          jwks_source: "configured",
          session_boundary: "http_only_cookie_verified_by_axis_api",
          capabilities: [],
          limitations: [],
          notes: [],
          unauthenticated_reason: null,
        },
        status: 200,
      });
    });

    await page.goto("/");

    // The page header renders once; every section shows its own ErrorPanel
    // instead of one page-level gate.
    await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: strings.overview.hero.error.title })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Attention items unavailable" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Audit evidence API unavailable" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Operations snapshot API unavailable" }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Activity breakdown unavailable" })).toBeVisible();
    await expect(page.getByText(strings.overview.hero.error.detail)).toBeVisible();

    // Posture cards degrade in place instead of disappearing.
    await expect(page.locator("[data-kpi-card]")).toHaveCount(5);
    await expect(page.getByText("Unavailable", { exact: true })).toHaveCount(5);

    // Endpoint paths are demoted behind the ErrorPanel "Technical details" expander.
    await expect(page.getByText(`${OPERATIONS_API_PREFIX}/overview`)).toHaveCount(0);
    await page.getByRole("button", { name: "Technical details" }).first().click();
    await expect(page.getByText(`${OPERATIONS_API_PREFIX}/overview`)).toBeVisible();
    await expect(page.getByText("Fallback demo seed")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Ravenna Works" })).toHaveCount(0);
    await expect(page.getByText("Plant Operations Cockpit")).toHaveCount(0);
    await expect(page.getByText("Live API")).toHaveCount(0);

    await page.getByRole("button", { name: "Refresh state" }).click();
    await expect(page.getByRole("heading", { name: strings.overview.hero.error.title })).toBeVisible();

    await expectAxisLightShell(page);
    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    expect(pageErrors).toEqual([]);
  });

  test("toggles to the navy dark theme and persists it across reloads", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/");
    await expectAxisLightShell(page);

    await page.getByRole("button", { name: "Toggle color theme" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

    const dark = await page.evaluate(() => ({
      bodyBackground: getComputedStyle(document.body).backgroundColor,
      colorScheme: getComputedStyle(document.documentElement).colorScheme,
      storedPreference: localStorage.getItem("axis-theme"),
    }));
    expect(dark).toEqual({
      bodyBackground: "rgb(4, 18, 46)",
      colorScheme: "dark",
      storedPreference: "dark",
    });

    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    const reloaded = await page.evaluate(
      () => getComputedStyle(document.body).backgroundColor,
    );
    expect(reloaded).toBe("rgb(4, 18, 46)");
    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);

    await page.getByRole("button", { name: "Toggle color theme" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expectAxisLightShell(page);
    expect(pageErrors).toEqual([]);
  });

  test("keeps shell utilities actionable without mock controls", async ({ page }) => {
    await page.unroute(identitySessionUrl);
    await page.goto("/");

    await expect(page.getByRole("button", { name: "Open notifications" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Open platform help" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Open operator account" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Connect OIDC bearer token" })).toHaveCount(0);

    await page.getByRole("button", { name: "Search console" }).click();
    await expect(page.getByRole("dialog", { name: "Console command menu" })).toBeVisible();
    await page.getByRole("combobox", { name: "Search console commands" }).fill("audit");
    // cmdk renders commands as options, not links.
    await expect(page.getByRole("option", { name: "Audit", exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Console command menu" })).toHaveCount(0);

    const topbarHeight = await page.locator(".ops-topbar").evaluate((element) =>
      Math.round(element.getBoundingClientRect().height),
    );
    expect(topbarHeight).toBeLessThanOrEqual(80);

    await page.getByRole("button", { name: "Open notifications" }).click();
    const notificationsPanel = page.locator('[aria-label="Notifications"]');
    await expect(notificationsPanel).toBeVisible();
    await expect(
      notificationsPanel.locator('[data-source-state="unavailable"]'),
    ).toContainText("notifications: unavailable");
    await expect(
      notificationsPanel.getByText(
        `Notification data requires ${OPERATIONS_API_PREFIX}/notifications.`,
      ),
    ).toBeVisible();
    const notificationsTopbarHeight = await page.locator(".ops-topbar").evaluate((element) =>
      Math.round(element.getBoundingClientRect().height),
    );
    expect(notificationsTopbarHeight).toBe(topbarHeight);
    await page.keyboard.press("Escape");
    await expect(page.locator('[aria-label="Notifications"]')).toHaveCount(0);

    await page.getByRole("button", { name: "Open platform help" }).click();
    await expect(page.locator('[aria-label="Platform help"]')).toBeVisible();
    await expect(page.getByRole("link", { name: /Architecture docs/ })).toHaveAttribute(
      "href",
      "https://github.com/Limes-Labs/limes-axis/blob/main/docs/architecture.md",
    );
    await page.keyboard.press("Escape");

    await page.getByRole("button", { name: "Open operator account" }).click();
    await expect(page.locator('[aria-label="Operator account"]')).toBeVisible();
    await expect(page.getByText("Session API unavailable")).toBeVisible();
    await expect(
      page.getByText("The account panel needs `/identity/session` before it can display an API-verified actor."),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Sign in with SSO" })).toHaveAttribute(
      "href",
      "http://127.0.0.1:65534/identity/oidc/authorize?return_to=%2F",
    );
    await expect(page.getByRole("link", { name: "Open SSO setup" })).toHaveAttribute(
      "href",
      "http://127.0.0.1:65534/identity/oidc/onboarding",
    );
    // The bearer-token form is demoted behind the "Developer access" collapsible.
    await expect(page.getByRole("button", { name: "Attach bearer bridge" })).toHaveCount(0);
    await page.getByRole("button", { name: "Developer access" }).click();
    await expect(page.getByRole("button", { name: "Attach bearer bridge" })).toBeVisible();
    const accountTopbarHeight = await page.locator(".ops-topbar").evaluate((element) =>
      Math.round(element.getBoundingClientRect().height),
    );
    expect(accountTopbarHeight).toBe(topbarHeight);

    await expect(page.getByRole("combobox", { name: "Environment" })).toHaveCount(0);
    await expect(page.getByRole("combobox", { name: "Evidence window" })).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
  });

  test("routes verified cookie sessions through the real federated logout endpoint", async ({
    page,
  }) => {
    await page.unroute(identitySessionUrl);
    await page.route(identitySessionUrl, async (route) => {
      await route.fulfill({
        contentType: "application/json",
        json: {
          authenticated: true,
          mode: "secure_oidc_cookie",
          actor_id: "plant-operations-owner-role",
          tenant_id: "tenant_demo_manufacturing",
          scopes: ["audit:read"],
          expires_at: 4102444800,
          api_auth_required: true,
          enterprise_sso_ready: true,
          readiness_status: "ready",
          issuer: "https://idp.example/realms/axis",
          audience: "limes-axis-api",
          jwks_source: "configured",
          session_boundary: "http_only_cookie_verified_by_axis_api",
          capabilities: ["Browser session verified by the Axis API."],
          limitations: [],
          notes: [],
          unauthenticated_reason: null,
        },
        status: 200,
      });
    });

    await page.goto("/");
    await page.getByRole("button", { name: "Open operator account" }).click();

    await expect(page.locator('[aria-label="Operator account"]')).toBeVisible();
    await expect(
      page.locator('[aria-label="Operator account"]').getByText("plant-operations-owner-role"),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Sign out with identity provider" }),
    ).toBeVisible();
    await expect(page.locator("[data-operator-initials]").first()).toHaveText("PO");

    const [logoutRequest] = await Promise.all([
      page.waitForRequest("http://127.0.0.1:65534/identity/oidc/logout?return_to=%2F"),
      page.getByRole("button", { name: "Sign out with identity provider" }).click(),
    ]);
    expect(logoutRequest.method()).toBe("GET");
  });

  test("keeps the desktop sidebar complete on short enterprise screens", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 420 });
    await page.goto("/");

    const sidebarState = await page.evaluate(() => {
      const sidebar = document.querySelector<HTMLElement>("[data-console-sidebar]");
      const nav = document.querySelector<HTMLElement>(".nav-list");
      const links = Array.from(document.querySelectorAll<HTMLAnchorElement>(".nav-list a")).map(
        (link) => link.textContent?.trim() ?? "",
      );

      return {
        links,
        nav: nav
          ? {
              clientHeight: nav.clientHeight,
              flexGrow: window.getComputedStyle(nav).flexGrow,
              overflowY: window.getComputedStyle(nav).overflowY,
              scrollHeight: nav.scrollHeight,
            }
          : null,
        sidebar: sidebar
          ? {
              clientHeight: sidebar.clientHeight,
              overflowY: window.getComputedStyle(sidebar).overflowY,
              scrollHeight: sidebar.scrollHeight,
            }
          : null,
        viewportHeight: window.innerHeight,
      };
    });

    // Grouped nav order from lib/nav.ts, flattened.
    expect(sidebarState.links).toEqual([
      "Overview",
      "Approvals",
      "Workflows",
      "Agents",
      "Data",
      "Ontology",
      "Connectors",
      "Models",
      "Policies",
      "Audit",
      "Simulation",
      "Tenants",
    ]);
    expect(sidebarState.sidebar?.clientHeight).toBe(sidebarState.viewportHeight);
    expect(sidebarState.sidebar?.scrollHeight ?? 0).toBeLessThanOrEqual(
      (sidebarState.sidebar?.clientHeight ?? 0) + 1,
    );
    expect(sidebarState.nav?.flexGrow).toBe("1");
    expect(sidebarState.nav?.overflowY).toBe("auto");

    await page.locator(".nav-list").evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    // Settings and the account row live in the footer now, outside the
    // scrolling nav list, so they stay reachable on a short screen.
    await expect(page.getByRole("link", { name: "Settings" })).toBeInViewport();
    await expect(page.getByRole("button", { name: "Open operator account" })).toBeInViewport();
  });

  test("keeps topbar utility hitboxes and popovers stable", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 760 });
    await page.goto("/");

    const topbarHeight = await page.locator(".ops-topbar").evaluate((element) =>
      Math.round(element.getBoundingClientRect().height),
    );
    const utilityRects = await page
      .locator(".ops-toolbar-icons button")
      .evaluateAll((buttons) =>
        buttons
          // Below 921px the topbar also carries the identity controls; at this
          // width they are display:none and would measure 0x0.
          .filter((button) => (button as HTMLElement).offsetParent !== null)
          .map((button) => {
            const rect = button.getBoundingClientRect();
            return {
              height: Math.round(rect.height),
              width: Math.round(rect.width),
            };
          }),
      );

    expect(utilityRects.length).toBeGreaterThanOrEqual(4);
    for (const rect of utilityRects) {
      expect(rect).toEqual({ height: 34, width: 34 });
    }

    const accountButton = page.getByRole("button", { name: "Open operator account" });
    const beforeAccountRect = await accountButton.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        height: Math.round(rect.height),
        left: Math.round(rect.left),
        top: Math.round(rect.top),
        width: Math.round(rect.width),
      };
    });

    await page.getByRole("button", { name: "Open notifications" }).click();
    await expect(page.locator('[aria-label="Notifications"]')).toBeVisible();
    await accountButton.click();
    await expect(page.locator('[aria-label="Operator account"]')).toBeVisible();
    await expect(page.locator('[aria-label="Notifications"]')).toHaveCount(0);

    const afterAccountRect = await accountButton.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        height: Math.round(rect.height),
        left: Math.round(rect.left),
        top: Math.round(rect.top),
        width: Math.round(rect.width),
      };
    });
    expect(afterAccountRect).toEqual(beforeAccountRect);

    const accountPopover = await page.locator('[aria-label="Operator account"]').evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        bottom: Math.round(rect.bottom),
        right: Math.round(rect.right),
        top: Math.round(rect.top),
      };
    });
    expect(accountPopover.top).toBeGreaterThanOrEqual(topbarHeight);
    expect(accountPopover.right).toBeLessThanOrEqual(1440 - 16);
    expect(accountPopover.bottom).toBeLessThanOrEqual(760 - 16);
  });

  test("keeps grouped navigation operable and requires agent/action APIs on mobile", async ({ page }) => {
    await routeVerifiedDemoIdentity(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/settings/sessions");

    const mobileNav = page.locator("[data-mobile-navigation]");
    await expect(mobileNav).toBeVisible();
    await expect(mobileNav.locator("[data-mobile-current-section]")).toHaveText("Settings");
    const menuTrigger = mobileNav.getByRole("button", {
      name: "Open navigation. Current section: Settings",
    });
    await menuTrigger.click();

    const drawer = page.getByRole("dialog", { name: "Navigate Axis" });
    await expect(drawer).toBeVisible();
    const platformGroup = drawer.getByRole("region", { name: "Platform" });
    await expect(platformGroup.getByRole("link", { name: "Settings" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(menuTrigger).toBeFocused();

    await menuTrigger.click();
    await drawer.getByRole("link", { name: "Agents" }).click();
    await expect(drawer).toBeHidden();
    await expect(page).toHaveURL(/\/agents$/);

    await expect(page.getByRole("heading", { name: "Agents", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Agent API unavailable" })).toBeVisible();
    await page.locator("summary").filter({ hasText: /^Action catalog:/ }).click();
    await expect(page.getByRole("heading", { name: "Action API unavailable" })).toBeVisible();
    await expect(page.getByText("Local fallback agent records are disabled.")).toBeVisible();
    await expect(page.getByText("Local fallback action records are disabled.")).toBeVisible();
    await expect(page.getByText("Fallback agent seed")).toHaveCount(0);
    await expect(page.getByText("Fallback action seed")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Supply Risk Agent/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Request supplier expedite/ })).toHaveCount(0);

    // The endpoint path stays demoted behind the ErrorPanel expander, and no
    // fabricated run timelines or detail tabs render without the registry API.
    await expect(page.getByText(`${OPERATIONS_API_PREFIX}/agents`, { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Technical details" }).first().click();
    await expect(
      page.getByText(
        `${OPERATIONS_API_PREFIX}/agents?tenant_id=tenant_demo_manufacturing`,
        { exact: true },
      ),
    ).toBeVisible();
    await expect(page.getByRole("tab", { name: "Runs" })).toHaveCount(0);
    await expect(page.getByText("No runs recorded — execution flag-gated")).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    await expectMobileHeadersStacked(page);

    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto("/policies/policy_e2e_navigation");
    await expect(page.locator("[data-mobile-current-section]")).toHaveText("Policies");
    await expectMobileHeadersStacked(page);
    await expectNoHorizontalOverflow(page);
  });

  test("opens Data as a tenant-bound catalog rather than a missing page", async ({ page }) => {
    await page.goto("/data");
    await expect(page.getByRole("heading", { name: "Data", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Data catalog unavailable" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Page not found" })).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
  });

  test("requires the ontology APIs instead of local graph data", async ({ page }) => {
    await page.goto("/ontology");

    await expect(page.getByRole("heading", { name: "Ontology", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Ontology API unavailable" })).toBeVisible();
    await expect(page.getByText("Local fallback ontology records are disabled.")).toBeVisible();
    await expect(page.getByText("Fallback ontology seed")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Line 2 Packaging" })).toHaveCount(0);
    await expect(page.getByTestId("ontology-graph")).toHaveCount(0);

    await page.goto("/ontology/asset_line_2_packaging");

    await expect(page.getByRole("heading", { name: "Entity detail" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Entity API unavailable" })).toBeVisible();
    await expect(page.getByText("Local fallback entity records are disabled.")).toBeVisible();
    await expect(page.getByText("Fallback entity seed")).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
  });

  test("zooms the mocked ontology graph and opens the entity slide-over in place", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.unroute(identitySessionUrl);
    await routeVerifiedIdentity(page, "tenant_e2e");

    const relationshipMetadata = {
      owner_role: "quality-owner",
      source_adapter: "typedb",
      confidence: 0.92,
      evidence_refs: ["audit_evt_e2e"],
      valid_from: "2026-01-01",
      valid_to: null,
      last_verified_at: "2026-07-01",
      verification_status: "verified",
    };
    const nodes = [
      {
        node_id: "org_e2e_plant",
        label: "E2E Plant",
        node_type: "organization",
        domain: "Operations",
        status: "ready",
        source_system: "ERP",
        summary: "Mocked organization node.",
      },
      {
        node_id: "asset_line_2",
        label: "Line 2 Packaging",
        node_type: "asset",
        domain: "Packaging",
        status: "ready",
        source_system: "MES",
        summary: "Mocked packaging line node.",
      },
      {
        node_id: "asset_line_1",
        label: "Line 1 Filling",
        node_type: "asset",
        domain: "Filling",
        status: "ready",
        source_system: "MES",
        summary: "Mocked filling line node.",
      },
    ];
    const relationships = [
      {
        relationship_id: "rel_plant_line_2",
        source_id: "org_e2e_plant",
        target_id: "asset_line_2",
        relation_type: "operates",
        summary: "Mocked relationship.",
        permission_scope: "ontology:read",
        metadata: relationshipMetadata,
      },
    ];

    await page.route(
      (url) => url.href.startsWith(`http://127.0.0.1:65534${OPERATIONS_API_PREFIX}/ontology`),
      async (route) => {
        if (route.request().url().includes("/entities/")) {
          const requestUrl = new URL(route.request().url());
          const requestedNodeId = decodeURIComponent(requestUrl.pathname.split("/").at(-1) ?? "");
          const requestedNode = nodes.find((node) => node.node_id === requestedNodeId);
          if (!requestedNode) {
            await route.fulfill({ contentType: "application/json", json: {}, status: 404 });
            return;
          }

          const viewingPlant = requestedNode.node_id === nodes[0].node_id;
          await route.fulfill({
            contentType: "application/json",
            json: {
              tenant_id: "tenant_e2e",
              plant_name: "E2E Plant",
              scenario: "E2E mocked scenario",
              provenance: "reference_scenario",
              as_of: "2026-07-10T09:00:00+02:00",
              node: requestedNode,
              connected_relationships: [
                {
                  direction: viewingPlant ? "outbound" : "inbound",
                  relationship: relationships[0],
                  peer_node: viewingPlant ? nodes[1] : nodes[0],
                },
              ],
              inbound_count: viewingPlant ? 0 : 1,
              outbound_count: viewingPlant ? 1 : 0,
              required_permissions: ["ontology:read"],
              evidence_refs: ["audit_evt_e2e"],
              data_access: ["MES summary"],
              governed_by: [],
              related_workflows: [],
              related_approvals: [],
              related_agents: [],
              detail_notes: ["This entity detail is read-only."],
            },
            status: 200,
          });
          return;
        }

        await route.fulfill({
          contentType: "application/json",
          json: {
            tenant_id: "tenant_e2e",
            plant_name: "E2E Plant",
            scenario: "E2E mocked scenario",
            provenance: "reference_scenario",
            as_of: "2026-07-10T09:00:00+02:00",
            nodes,
            relationships,
            source_systems: ["MES", "ERP"],
            permission_notes: ["Mocked ontology for the smoke suite."],
            graph_query: {
              adapter: "typedb",
              source: "e2e",
              query_mode: "read_only",
              tenant_id: "tenant_e2e",
              actor_id: "actor_e2e",
              permission_decision: { allowed: true, reason: "read_scope_present" },
              requested_scopes: ["ontology:read"],
              applied_relationship_scopes: ["ontology:read"],
              denied_relationship_count: 0,
              returned_node_count: 3,
              returned_relationship_count: 1,
              typeql: null,
              notes: [],
            },
          },
          status: 200,
        });
      },
    );

    // Keep a deterministic pre-explorer entry so the final Close -> Back
    // assertion can detect a duplicate explorer entry, not only a reopened
    // entity sheet.
    await page.goto("/ontology?history_origin=1");
    await page.goto("/ontology");

    if ((page.viewportSize()?.width ?? 1024) < 640) {
      await page.getByRole("button", { name: "Graph", exact: true }).click();
      await expect.poll(() => new URL(page.url()).searchParams.get("view")).toBe("graph");
    }
    const explorerSearch = new URL(page.url()).search;
    const graph = page.getByTestId("ontology-graph");
    await expect(graph).toBeVisible();
    const ontologySource = page.locator('[data-source-state="reference"]');
    await expect(ontologySource).toBeVisible();
    await expect(ontologySource).toContainText("ontology: reference scenario");
    await expect(
      page.locator('[data-source-state="live"]').filter({ hasText: "ontology" }),
    ).toHaveCount(0);

    // Node-type counts live in the legend; the old metric cards are gone.
    const legend = page.getByLabel("Ontology graph legend");
    await expect(legend.getByText("Organization ×1")).toBeVisible();
    await expect(legend.getByText("Asset ×2")).toBeVisible();
    await expect(page.getByText("Mapped demo ontology nodes")).toHaveCount(0);

    // Zoom controls drive the svg viewBox; reset restores the full view.
    const initialViewBox = await graph.getAttribute("viewBox");
    await page.getByRole("button", { name: "Zoom in" }).click();
    await expect(graph).not.toHaveAttribute("viewBox", initialViewBox ?? "");
    await page.getByRole("button", { name: "Reset view" }).click();
    await expect(graph).toHaveAttribute("viewBox", initialViewBox ?? "");
    await page.getByRole("button", { name: "Zoom in" }).click();
    const zoomedViewBox = await graph.getAttribute("viewBox");

    // Activating a node opens the slide-over without navigating.
    await graph.getByRole("link", { name: /Line 2 Packaging/ }).click();
    const sheet = page.getByRole("dialog");
    await expect(sheet.getByRole("heading", { name: "Line 2 Packaging" })).toBeVisible();
    await expect(sheet.getByRole("link", { name: "Open full page" })).toHaveAttribute(
      "href",
      "/ontology/asset_line_2",
    );
    await expect(sheet.getByRole("heading", { name: "Summary", exact: true })).toBeVisible();
    expect(new URL(page.url()).pathname).toBe("/ontology");
    expect(new URL(page.url()).searchParams.get("entity_id")).toBe("asset_line_2");

    // Peer traversal is URL-backed. Back walks the entity history in place,
    // then closes the sheet without leaving the ontology explorer.
    await sheet.getByRole("button", { name: "E2E Plant" }).click();
    await expect(sheet.getByRole("heading", { name: "E2E Plant" })).toBeVisible();
    expect(new URL(page.url()).searchParams.get("entity_id")).toBe("org_e2e_plant");

    await page.goBack();
    await expect(sheet.getByRole("heading", { name: "Line 2 Packaging" })).toBeVisible();
    expect(new URL(page.url()).searchParams.get("entity_id")).toBe("asset_line_2");

    await page.goBack();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(new URL(page.url()).pathname).toBe("/ontology");
    expect(new URL(page.url()).search).toBe(explorerSearch);
    await expect(graph).toHaveAttribute("viewBox", zoomedViewBox ?? "");

    // Explicit Close collapses the whole peer traversal to the explorer root.
    // The next Back must reach the entry before that root, not reopen either
    // entity or visit a duplicate /ontology entry.
    await graph.getByRole("link", { name: /Line 2 Packaging/ }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(new URL(page.url()).searchParams.get("entity_id")).toBe("asset_line_2");
    await sheet.getByRole("button", { name: "E2E Plant" }).click();
    await expect(sheet.getByRole("heading", { name: "E2E Plant" })).toBeVisible();
    expect(new URL(page.url()).searchParams.get("entity_id")).toBe("org_e2e_plant");
    await sheet.getByRole("button", { name: "Close" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(graph).toHaveAttribute("viewBox", zoomedViewBox ?? "");
    expect(new URL(page.url()).pathname).toBe("/ontology");
    expect(new URL(page.url()).search).toBe(explorerSearch);

    await page.goBack();
    await expect.poll(() => new URL(page.url()).searchParams.get("history_origin")).toBe("1");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(new URL(page.url()).searchParams.has("entity_id")).toBe(false);

    expect(pageErrors).toEqual([]);
  });

  test("requires the model routing API instead of local routing data", async ({ page }) => {
    await page.goto("/model-routing");

    await expect(page.getByRole("heading", { name: "Models", exact: true })).toBeVisible();

    // One header strip explains the reference-vs-live split and hosts the tabs.
    await expect(
      page.getByText(
        "Reference routing shows the governed routing design; live invocations are the calls the platform actually executed.",
      ),
    ).toBeVisible();
    await expect(page.getByRole("tab", { name: "Reference routing" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Live invocations" })).toBeVisible();

    // Reference tab (default): API-required state, never fabricated routes.
    await expect(page.getByRole("heading", { name: "Routing API unavailable" })).toBeVisible();
    await expect(page.getByText("Local fallback routing records are disabled.")).toBeVisible();
    await expect(page.getByText("Fallback routing seed")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Quality Risk Agent/ })).toHaveCount(0);
    await page.getByRole("button", { name: "Technical details" }).click();
    await expect(
      page.getByText(
        `${OPERATIONS_API_PREFIX}/model-routing?tenant_id=tenant_demo_manufacturing`,
        { exact: true },
      ),
    ).toBeVisible();

    // Live tab: its own API-required states instead of fabricated invocation
    // rows or endpoint cards.
    await page.getByRole("tab", { name: "Live invocations" }).click();
    // The "Live executed" badge must NOT appear while the invocation API is
    // down — it previously rendered unconditionally, so a green "Live executed"
    // sat directly above "Model invocation API unavailable".
    await expect(page.getByText("Live executed", { exact: true })).toHaveCount(0);
    await expect(
      page.getByRole("heading", { name: "Model invocation API unavailable" }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByRole("heading", { name: "Model endpoint API unavailable" }),
    ).toBeVisible();
    // Endpoint paths sit behind the per-panel "Technical details" expanders.
    const liveDetailToggles = page.getByRole("button", { name: "Technical details" });
    await expect(liveDetailToggles).toHaveCount(2);
    for (let index = 0; index < 2; index += 1) {
      await liveDetailToggles.nth(index).click();
    }
    await expect(
      page.getByText(
        "/platform/models/invocations?tenant_id=tenant_demo_manufacturing&page_size=50",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(
      page.getByText(
        "/platform/models/endpoints?tenant_id=tenant_demo_manufacturing&limit=100",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(page.locator("[data-testid='live-invocations-table']")).toHaveCount(0);
    await expect(page.getByText("Execution disabled — flag-gated")).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
  });

  test("requires the approval API instead of local approval decisions", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await routeVerifiedDemoIdentity(page);

    await page.goto("/approvals");

    await expect(page.getByRole("heading", { name: "Approvals", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Approval API unavailable" })).toBeVisible();
    await expect(page.getByText("Local fallback approval records are disabled.")).toBeVisible();
    await expect(page.getByText("Fallback approval seed")).toHaveCount(0);
    await expect(page.getByText("Local preview")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Expedite supplier batch/ })).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    expect(pageErrors).toEqual([]);
  });

  test("requires the workflow API instead of local workflow data", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/workflows");

    await expect(page.getByRole("heading", { name: "Workflows", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Workflow API unavailable" })).toBeVisible();
    await expect(page.getByText("Local fallback workflow records are disabled.")).toBeVisible();
    await expect(page.getByText("Fallback workflow seed")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Supplier Delay Review/ })).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    expect(pageErrors).toEqual([]);
  });

  test("requires the platform policy API instead of local policy data", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/");
    await expect(page.getByRole("link", { name: "Policies" }).first()).toHaveAttribute(
      "href",
      "/policies",
    );

    await page.goto("/policies");

    await expect(page.getByRole("heading", { name: "Policies", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Policy API unavailable" })).toBeVisible();
    await expect(page.getByText("Local fallback policy records are disabled.")).toBeVisible();
    await page.getByRole("button", { name: "Technical details" }).first().click();
    await expect(
      page.getByText("/platform/policies?tenant_id=tenant_demo_manufacturing", {
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.getByText("Fallback policy seed")).toHaveCount(0);
    await expect(page.getByRole("link", { name: /Deny critical actions/ })).toHaveCount(0);

    await expect(page.getByRole("form", { name: "Platform policy authoring" })).toHaveCount(0);

    await page.goto("/policies/deny_critical_actions");

    await expect(page.getByRole("heading", { name: "Policy detail" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Policy API unavailable" })).toBeVisible();
    await page.getByRole("button", { name: "Technical details" }).first().click();
    await expect(
      page.getByText(
        "/platform/policies/deny_critical_actions?tenant_id=tenant_demo_manufacturing",
      ),
    ).toBeVisible();
    await expect(page.getByRole("form", { name: "Policy dry-run evaluation" })).toHaveCount(0);
    await expect(page.getByRole("form", { name: "Platform policy revision" })).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    expect(pageErrors).toEqual([]);
  });

  test("authors a platform policy through the mocked policy API", async ({ context, page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await context.addCookies([
      { name: "axis_csrf", value: "csrf-e2e-token", url: "http://127.0.0.1:3100" },
    ]);

    const policyRecord = {
      tenant_id: "tenant_demo_manufacturing",
      policy_id: "deny_critical_actions",
      revision_number: 1,
      policy_version: "1.0.0",
      display_name: "Deny critical actions",
      description: "Blocks critical-risk action execution.",
      scope: "action_execution",
      effect: "deny",
      conditions: { risk_levels: ["critical"] },
      status: "active",
      notes: [],
      created_by: "platform-governance-owner-role",
      created_at: "2026-07-01T08:00:00Z",
      required_authoring_scope: "platform:policy:author",
      revises_revision_number: null,
      replaced_by_revision_number: null,
      revision_idempotency_key: null,
      idempotent_replay: false,
      audit_event_type: "platform.policy.authored",
      audit_event_id: null,
      permission_decision: { allowed: true, reason: "authoring_scope_present" },
    };

    const policyPosts: string[] = [];
    let registryPolicies = [policyRecord];
    await page.route(
      (url) => url.href.startsWith("http://127.0.0.1:65534/platform/policies"),
      async (route) => {
        if (route.request().method() === "POST") {
          policyPosts.push(route.request().postData() ?? "");
          const createdPolicy = {
            ...policyRecord,
            policy_id: "gate_high_spend",
            display_name: "Gate high spend",
            description: "Requires approval above the spend threshold.",
            effect: "require_approval",
            scope: "approval_requirement",
            conditions: { risk_levels: ["high"], requested_amount_at_least: 10000 },
          };
          registryPolicies = [...registryPolicies, createdPolicy];
          await route.fulfill({
            contentType: "application/json",
            json: createdPolicy,
            status: 201,
          });
          return;
        }

        await route.fulfill({
          contentType: "application/json",
          json: {
            tenant_id: "tenant_demo_manufacturing",
            policy_count: registryPolicies.length,
            active_policy_count: registryPolicies.length,
            policies: registryPolicies,
            policy_notes: [],
          },
          status: 200,
        });
      },
    );

    await page.goto("/policies");

    await page.locator("summary").filter({ hasText: /^Create policy$/ }).click();
    const createForm = page.getByRole("form", { name: "Platform policy authoring" });
    await expect(createForm).toBeVisible();

    // Client-side validation blocks a policy id the API pattern rejects.
    await page.getByLabel("New policy id").fill("Bad Policy Id");
    await page.getByLabel("New policy display name").fill("Gate high spend");
    await page
      .getByLabel("New policy description")
      .fill("Requires approval above the spend threshold.");
    await createForm.getByRole("button", { name: "Author policy" }).click();
    await expect(
      page.getByText("Policy id must match ^[a-z0-9][a-z0-9_-]*$", { exact: false }),
    ).toBeVisible();
    await expect(
      page.getByText("Declare at least one condition", { exact: false }),
    ).toBeVisible();
    expect(policyPosts).toEqual([]);

    // A valid draft round-trips through the mocked create endpoint.
    await page.getByLabel("New policy id").fill("gate_high_spend");
    await page.getByLabel("New policy scope").selectOption("approval_requirement");
    await page.getByLabel("New policy effect").selectOption("require_approval");
    await page
      .getByRole("group", { name: "New policy risk levels" })
      .getByRole("button", { name: "high", exact: true })
      .click();
    await page.getByLabel("New policy amount threshold").fill("10000");

    const [createRequest] = await Promise.all([
      page.waitForRequest(
        (request) =>
          request.method() === "POST"
          && request.url() === "http://127.0.0.1:65534/platform/policies",
      ),
      createForm.getByRole("button", { name: "Author policy" }).click(),
    ]);
    expect(createRequest.headers()["x-axis-csrf-token"]).toBe("csrf-e2e-token");
    expect(createRequest.postDataJSON()).toEqual({
      tenant_id: "tenant_demo_manufacturing",
      policy_id: "gate_high_spend",
      policy_version: "1.0.0",
      display_name: "Gate high spend",
      description: "Requires approval above the spend threshold.",
      scope: "approval_requirement",
      effect: "require_approval",
      conditions: { risk_levels: ["high"], requested_amount_at_least: 10000 },
      created_by: "platform-governance-owner-role",
      actor_scopes: ["platform:policy:author"],
      notes: [],
    });

    await expect(page.getByText("Policy authored as r1 / 1.0.0: Gate high spend")).toBeVisible();
    await expect(page.getByRole("link", { name: "Gate high spend" })).toHaveAttribute(
      "href",
      "/policies/gate_high_spend",
    );

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    expect(pageErrors).toEqual([]);
  });

  test("shows the revise form and revision compare on the mocked policy detail", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    const baseRecord = {
      tenant_id: "tenant_demo_manufacturing",
      policy_id: "deny_critical_actions",
      revision_number: 1,
      policy_version: "1.0.0",
      display_name: "Deny critical actions",
      description: "Blocks critical-risk action execution.",
      scope: "action_execution",
      effect: "require_approval",
      conditions: { risk_levels: ["high", "critical"] },
      status: "superseded",
      notes: [],
      created_by: "platform-governance-owner-role",
      created_at: "2026-07-01T08:00:00Z",
      required_authoring_scope: "platform:policy:author",
      revises_revision_number: null,
      replaced_by_revision_number: 2,
      revision_idempotency_key: null,
      idempotent_replay: false,
      audit_event_type: "platform.policy.authored",
      audit_event_id: null,
      permission_decision: { allowed: true, reason: "authoring_scope_present" },
    };
    const currentRecord = {
      ...baseRecord,
      revision_number: 2,
      policy_version: "1.1.0",
      effect: "deny",
      conditions: { risk_levels: ["critical"] },
      status: "active",
      revises_revision_number: 1,
      replaced_by_revision_number: null,
      revision_idempotency_key: "idem-key-1",
      required_authoring_scope: "platform:policy:revise",
      audit_event_type: "platform.policy.revised",
    };

    await page.route(
      (url) =>
        url.href.startsWith(
          "http://127.0.0.1:65534/platform/policies/deny_critical_actions?",
        ),
      async (route) => {
        await route.fulfill({
          contentType: "application/json",
          json: {
            tenant_id: "tenant_demo_manufacturing",
            policy_id: "deny_critical_actions",
            current_revision: currentRecord,
            revisions: [baseRecord, currentRecord],
          },
          status: 200,
        });
      },
    );

    await page.goto("/policies/deny_critical_actions");

    await expect(page.getByRole("heading", { name: "Deny critical actions" })).toBeVisible();

    // Revising, history and compare live together under the Revisions tab.
    await expect(page.getByRole("tab", { name: "Conditions" })).toBeVisible();
    await page.getByRole("tab", { name: "Revisions" }).click();

    // Revise form is pre-filled from the current revision with a
    // client-generated idempotency key.
    const reviseForm = page.getByRole("form", { name: "Platform policy revision" });
    await expect(reviseForm).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Append a revision to r2" }),
    ).toBeVisible();
    await expect(page.getByText(/Idempotency key [0-9a-f-]{36}/)).toBeVisible();
    await expect(page.getByLabel("Revision policy version")).toHaveValue("1.1.0");
    await expect(page.getByLabel("Revision display name")).toHaveValue("Deny critical actions");
    await expect(
      page
        .getByRole("group", { name: "Revision risk levels" })
        .getByRole("button", { name: "critical", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");

    // Revision compare renders a field-level diff against the current revision.
    await page.getByLabel("Revision to compare").selectOption("1");
    await expect(page.getByText("Comparing r1 / 1.0.0 against the current r2 / 1.1.0")).toBeVisible();
    await expect(page.getByText("Require approval → Deny")).toBeVisible();
    await expect(page.getByText("− high")).toBeVisible();

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    expect(pageErrors).toEqual([]);
  });

  test("requires the audit API instead of local audit data", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/audit");

    await expect(page.getByRole("heading", { name: "Audit", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Audit API unavailable" })).toBeVisible();
    await expect(page.getByText("Local fallback audit records are disabled.")).toBeVisible();
    await expect(page.getByText("Fallback audit seed")).toHaveCount(0);
    await expect(page.getByText("audit-export-local-seed")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /workflow.started/ })).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    expect(pageErrors).toEqual([]);
  });

  test("requires the replay API instead of local replay artifacts", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/simulation");

    await expect(page.getByRole("heading", { name: "Simulation", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Replay API unavailable" })).toBeVisible();
    await expect(page.getByText("Local fallback replay records are disabled.")).toBeVisible();
    await expect(page.getByText("Fallback replay seed")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Supplier Delay Review/ })).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    expect(pageErrors).toEqual([]);
  });

  test("requires the connector API instead of local connector fallback data", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/connectors");

    await expect(page.getByRole("heading", { name: "Connectors", exact: true })).toBeVisible();
    // An unreachable API renders the unified ErrorPanel — never the empty
    // state and never local fallback records.
    await expect(page.getByRole("heading", { name: "Connector API unavailable" })).toBeVisible();
    await expect(page.getByText("Local fallback connector records are disabled.")).toBeVisible();
    await expect(page.getByRole("heading", { name: "No connectors yet" })).toHaveCount(0);
    await expect(page.getByText("Fallback connector seed")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Manufacturing assets CSV/ })).toHaveCount(0);

    // The workspace endpoint stays demoted behind the technical-details expander.
    await expect(page.getByText(`${OPERATIONS_API_PREFIX}/connectors/workspace`, { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Technical details" }).click();
    await expect(page.getByText(`${OPERATIONS_API_PREFIX}/connectors/workspace`, { exact: true })).toBeVisible();

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    expect(pageErrors).toEqual([]);
  });

  test("requires the identity session APIs on the sessions view", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.unroute(identitySessionUrl);

    await page.goto("/settings/sessions");

    await expect(page.getByRole("heading", { name: "Session security" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Session API unavailable" })).toBeVisible();
    await expect(page.getByText("Local fallback session records are disabled.")).toBeVisible();
    await page.getByRole("button", { name: "Technical details" }).first().click();
    await expect(page.getByText("/identity/session /identity/sessions")).toBeVisible();
    await expect(page.getByRole("button", { name: "Revoke" })).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    expect(pageErrors).toEqual([]);
  });

  test("lists browser sessions and revokes with the CSRF double-submit header", async ({
    context,
    page,
  }) => {
    await page.unroute(identitySessionUrl);
    await context.addCookies([
      { name: "axis_csrf", value: "csrf-e2e-token", url: "http://127.0.0.1:3100" },
    ]);

    await page.route(identitySessionUrl, async (route) => {
      await route.fulfill({
        contentType: "application/json",
        json: {
          authenticated: true,
          mode: "secure_oidc_cookie",
          actor_id: "plant-operations-owner-role",
          tenant_id: "tenant_demo_manufacturing",
          scopes: ["audit:read", "identity:sessions:admin"],
          expires_at: 4102444800,
          api_auth_required: true,
          enterprise_sso_ready: true,
          readiness_status: "ready",
          issuer: "https://idp.example/realms/axis",
          audience: "limes-axis-api",
          jwks_source: "configured",
          session_boundary: "http_only_cookie_verified_by_axis_api",
          capabilities: ["Browser session verified by the Axis API."],
          limitations: [],
          notes: [],
          unauthenticated_reason: null,
        },
        status: 200,
      });
    });
    await page.route("http://127.0.0.1:65534/identity/sessions*", async (route) => {
      const tenantWide = route.request().url().includes("tenant_wide=true");
      await route.fulfill({
        contentType: "application/json",
        json: {
          tenant_id: "tenant_demo_manufacturing",
          actor_id: "plant-operations-owner-role",
          tenant_wide: tenantWide,
          sessions: [
            {
              session_ref: "0b6a4e52-93d4-4f5f-8f2a-2f24c9b7a101",
              actor_id: "plant-operations-owner-role",
              status: "active",
              current: true,
              created_at: "2026-07-07T08:00:00Z",
              expires_at: "2026-07-07T16:00:00Z",
              absolute_expires_at: "2026-07-07T16:00:00Z",
              last_seen_at: "2026-07-07T09:30:00Z",
              refresh_count: 3,
              revoked_at: null,
              revocation_reason: null,
            },
            {
              session_ref: "9c1f2ad4-7a75-4d0e-b1de-6d9d0c4be202",
              actor_id: tenantWide ? "quality-auditor-role" : "plant-operations-owner-role",
              status: "active",
              current: false,
              created_at: "2026-07-06T18:00:00Z",
              expires_at: "2026-07-07T02:00:00Z",
              absolute_expires_at: null,
              last_seen_at: null,
              refresh_count: 0,
              revoked_at: null,
              revocation_reason: null,
            },
            {
              session_ref: "5d2e6bc8-1f9b-45b6-9f5c-0a8f2f6de303",
              actor_id: "plant-operations-owner-role",
              status: "revoked",
              current: false,
              created_at: "2026-07-05T18:00:00Z",
              expires_at: "2026-07-06T02:00:00Z",
              absolute_expires_at: null,
              last_seen_at: "2026-07-05T19:00:00Z",
              refresh_count: 1,
              revoked_at: "2026-07-05T20:00:00Z",
              revocation_reason: "idle_timeout",
            },
          ],
          notes: ["Session references are opaque identifiers; no token material is returned."],
        },
        status: 200,
      });
    });
    await page.route(
      "http://127.0.0.1:65534/identity/sessions/9c1f2ad4-7a75-4d0e-b1de-6d9d0c4be202/revoke",
      async (route) => {
        await route.fulfill({ status: 204 });
      },
    );

    await page.goto("/settings/sessions");

    await expect(page.getByRole("heading", { name: "Session security" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Your sessions" })).toBeVisible();
    await expect(page.getByText("3 recorded")).toBeVisible();
    await expect(page.getByText("(this browser)")).toBeVisible();
    await expect(page.getByText("Current", { exact: true })).toBeVisible();
    await expect(page.getByText("Revoked", { exact: true })).toBeVisible();
    await expect(page.getByText("idle timeout")).toBeVisible();
    await expect(page.getByRole("button", { name: "Revoke", exact: true })).toHaveCount(1);

    const signOutLinks = page.getByRole("link", { name: "Sign out" });
    await expect(signOutLinks).toHaveCount(2);
    await expect(signOutLinks.first()).toHaveAttribute(
      "href",
      "http://127.0.0.1:65534/identity/oidc/logout?return_to=%2Fsettings%2Fsessions",
    );

    const [revokeRequest] = await Promise.all([
      page.waitForRequest(
        "http://127.0.0.1:65534/identity/sessions/9c1f2ad4-7a75-4d0e-b1de-6d9d0c4be202/revoke",
      ),
      page.getByRole("button", { name: "Revoke", exact: true }).click(),
    ]);
    expect(revokeRequest.method()).toBe("POST");
    expect(revokeRequest.headers()["x-axis-csrf-token"]).toBe("csrf-e2e-token");

    await page.getByRole("button", { name: "Show tenant sessions" }).click();
    await expect(page.getByRole("heading", { name: "Tenant-wide sessions" })).toBeVisible();
    await expect(page.getByText("quality-auditor-role")).toBeVisible();

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
  });

  test("requires the platform tenant API instead of local tenant data", async ({ page }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto("/");
    await expectNavigationDestination(page, "Tenants", "/tenants");

    await page.goto("/tenants");

    await expect(page.getByRole("heading", { name: "Tenants", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Tenant API unavailable" })).toBeVisible();
    await expect(page.getByText("Local fallback tenant records are disabled.")).toBeVisible();
    await page.getByRole("button", { name: "Technical details" }).first().click();
    await expect(page.getByText("/platform/tenants", { exact: true })).toBeVisible();
    await expect(page.getByRole("form", { name: "Tenant provisioning" })).toHaveCount(0);

    await page.goto("/tenants/tenant_acme");

    await expect(page.getByRole("heading", { name: "Tenant detail" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Tenant API unavailable" })).toBeVisible();
    await page.getByRole("button", { name: "Technical details" }).first().click();
    await expect(page.getByText("/platform/tenants/tenant_acme", { exact: true })).toBeVisible();
    await expect(page.getByRole("form", { name: "Suspend tenant" })).toHaveCount(0);
    await expect(page.getByRole("form", { name: "Tenant quota update" })).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    expect(pageErrors).toEqual([]);
  });

  test("provisions a tenant and suspends it through the mocked tenant API", async ({
    context,
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await context.addCookies([
      { name: "axis_csrf", value: "csrf-e2e-token", url: "http://127.0.0.1:3100" },
    ]);

    const tenantRecord = {
      tenant_id: "tenant_acme",
      display_name: "Acme Manufacturing",
      description: "Reference tenant.",
      status: "active",
      created_by: "platform-tenant-operator-role",
      bootstrap_admin_actor_id: null,
      provision_idempotency_key: "idem-key-1",
      suspended_at: null,
      suspended_by: null,
      suspension_reason: null,
      reactivated_at: null,
      reactivated_by: null,
      permission_decision: { allowed: true, reason: "operator_scope_present" },
      audit_event_id: "11111111-1111-4111-8111-111111111111",
      audit_event_type: "platform.tenant.provisioned",
      idempotent_replay: false,
      notes: [],
      created_at: "2026-07-01T08:00:00Z",
      updated_at: "2026-07-01T08:00:00Z",
    };

    const tenantPosts: string[] = [];
    // Registry list + provision POST live on the same base path.
    await page.route(
      (url) =>
        url.href === "http://127.0.0.1:65534/platform/tenants"
        || url.href.startsWith("http://127.0.0.1:65534/platform/tenants?"),
      async (route) => {
        if (route.request().method() === "POST") {
          tenantPosts.push(route.request().postData() ?? "");
          await route.fulfill({ contentType: "application/json", json: tenantRecord, status: 201 });
          return;
        }

        await route.fulfill({
          contentType: "application/json",
          json: {
            tenant_count: 1,
            active_tenant_count: 1,
            tenants: [tenantRecord],
            tenant_notes: [],
          },
          status: 200,
        });
      },
    );

    const [listRequest] = await Promise.all([
      page.waitForRequest(
        (request) =>
          request.method() === "GET"
          && request.url().startsWith("http://127.0.0.1:65534/platform/tenants"),
      ),
      page.goto("/tenants"),
    ]);
    // The list is requested at the API maximum so the ceiling is as high as
    // the API allows.
    expect(new URL(listRequest.url()).searchParams.get("limit")).toBe("200");

    await expect(page.getByRole("heading", { name: "Tenants", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Acme Manufacturing" })).toBeVisible();
    // A short list is not capped, so no cap notice is shown.
    await expect(page.getByRole("heading", { name: /Showing the first 200 tenants/ })).toHaveCount(
      0,
    );

    await page.locator("summary").filter({ hasText: /^Create organization$/ }).click();
    const provisionForm = page.getByRole("form", { name: "Tenant provisioning" });
    await expect(provisionForm).toBeVisible();

    // Client-side validation blocks a bad tenant id with zero requests.
    await page.getByLabel("New tenant id").fill("Bad Tenant Id");
    await page.getByLabel("New tenant display name").fill("Bad Tenant");
    await provisionForm.getByRole("button", { name: "Provision tenant" }).click();
    await expect(
      page.getByText("Tenant id must match ^[a-z0-9][a-z0-9_-]*$", { exact: false }),
    ).toBeVisible();
    expect(tenantPosts).toEqual([]);

    // A valid draft round-trips through the mocked provision endpoint with CSRF.
    await page.getByLabel("New tenant id").fill("tenant_acme");
    await page.getByLabel("New tenant display name").fill("Acme Manufacturing");
    await page.getByLabel("New tenant description").fill("Reference tenant.");

    const [provisionRequest] = await Promise.all([
      page.waitForRequest(
        (request) =>
          request.method() === "POST"
          && request.url() === "http://127.0.0.1:65534/platform/tenants",
      ),
      provisionForm.getByRole("button", { name: "Provision tenant" }).click(),
    ]);
    expect(provisionRequest.headers()["x-axis-csrf-token"]).toBe("csrf-e2e-token");
    const provisionBody = provisionRequest.postDataJSON();
    expect(provisionBody.tenant_id).toBe("tenant_acme");
    expect(provisionBody.display_name).toBe("Acme Manufacturing");
    expect(provisionBody.actor_scopes).toEqual([
      "platform:tenant:operator",
      "platform:tenant:provision",
    ]);
    expect(typeof provisionBody.idempotency_key).toBe("string");
    await expect(page.getByText("Tenant provisioned.")).toBeVisible();
    // The provision success triggers a console refresh that reloads the tenant
    // registry. The registry must stay mounted (stale-while-revalidate) rather
    // than flashing to the API-unavailable state, otherwise the provision form
    // and this confirmation would be torn down mid-refresh.
    await expect(page.getByRole("link", { name: "Acme Manufacturing" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Tenant API unavailable" })).toHaveCount(0);

    // Suspend the tenant from the detail view; the action posts the reason.
    await page.route(
      "http://127.0.0.1:65534/platform/tenants/tenant_acme/quotas",
      async (route) => {
        await route.fulfill({
          contentType: "application/json",
          json: { tenant_id: "tenant_acme", quotas: {}, quota_notes: [] },
          status: 200,
        });
      },
    );
    await page.route(
      "http://127.0.0.1:65534/platform/tenants/tenant_acme/suspend",
      async (route) => {
        await route.fulfill({
          contentType: "application/json",
          json: { ...tenantRecord, status: "suspended", suspended_by: "operator" },
          status: 200,
        });
      },
    );

    // The detail view reads the dedicated single-tenant route rather than
    // deriving the record from the registry list.
    await page.route(
      "http://127.0.0.1:65534/platform/tenants/tenant_acme",
      async (route) => {
        await route.fulfill({
          contentType: "application/json",
          json: tenantRecord,
          status: 200,
        });
      },
    );

    await page.goto("/tenants/tenant_acme");
    await expect(page.getByRole("heading", { name: "Acme Manufacturing" })).toBeVisible();
    await expect(page.getByText("Provisioned", { exact: true })).toBeVisible();

    const suspendForm = page.getByRole("form", { name: "Suspend tenant" });
    await expect(suspendForm).toBeVisible();
    await page.getByLabel("Suspension reason").fill("Contract paused");

    const [suspendRequest] = await Promise.all([
      page.waitForRequest("http://127.0.0.1:65534/platform/tenants/tenant_acme/suspend"),
      suspendForm.getByRole("button", { name: "Suspend tenant" }).click(),
    ]);
    expect(suspendRequest.method()).toBe("POST");
    expect(suspendRequest.headers()["x-axis-csrf-token"]).toBe("csrf-e2e-token");
    expect(suspendRequest.postDataJSON()).toMatchObject({
      reason: "Contract paused",
      actor_scopes: ["platform:tenant:operator", "platform:tenant:suspend"],
    });
    await expect(page.getByText(/Tenant suspended\./)).toBeVisible();

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    expect(pageErrors).toEqual([]);
  });

  test("requires the settings readiness APIs per panel instead of local settings data", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.unroute(identitySessionUrl);

    await page.goto("/settings");

    // The page header is "System status"; the nav label stays Settings.
    await expect(page.getByRole("heading", { name: "System status", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Settings API unavailable" })).toHaveCount(0);

    // Readiness tab (default): each panel degrades on its own instead of one
    // page-wide gate.
    await expect(
      page.getByRole("heading", { name: "Readiness API unavailable", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Deployment readiness API unavailable", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Local fallback settings records are disabled.").first(),
    ).toBeVisible();
    await page.getByRole("button", { name: "Technical details" }).first().click();
    await expect(page.getByText("/ready", { exact: true })).toBeVisible();

    // Identity tab: OIDC readiness and the session read model degrade apart.
    await page.getByRole("tab", { name: "Identity" }).click();
    await expect(
      page.getByRole("heading", { name: "Identity readiness API unavailable" }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Session API unavailable" })).toBeVisible();
    await page.getByRole("button", { name: "Technical details" }).first().click();
    await expect(page.getByText("/identity/oidc/readiness", { exact: true })).toBeVisible();

    // Support tab: its own panel-scoped error.
    await page.getByRole("tab", { name: "Support" }).click();
    await expect(
      page.getByRole("heading", { name: "Support diagnostics API unavailable" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Technical details" }).click();
    await expect(page.getByText("/support/diagnostics", { exact: true })).toBeVisible();
    await expect(page.getByText("Fallback settings seed")).toHaveCount(0);

    await expectNoHorizontalOverflow(page);
    await expectNoUndersizedTargets(page);
    expect(pageErrors).toEqual([]);
  });
});
