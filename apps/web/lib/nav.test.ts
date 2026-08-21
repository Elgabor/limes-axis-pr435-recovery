import { describe, expect, it } from "vitest";

import { desktopNavGroups, isNavActive, navGroups, navItems, resolveNavItem } from "./nav";

describe("grouped navigation model", () => {
  it("organizes the console into the four spec sections", () => {
    expect(navGroups.map((group) => group.label)).toEqual([
      "Operate",
      "Data & Models",
      "Governance",
      "Platform",
    ]);
  });

  it("keeps all 12 grouped console routes addressable exactly once", () => {
    const hrefs = navItems.map((item) => item.href);

    expect(hrefs).toHaveLength(12);
    expect(new Set(hrefs).size).toBe(12);
    expect([...hrefs].sort()).toEqual(
      [
        "/",
        "/agents",
        "/approvals",
        "/audit",
        "/connectors",
        "/model-routing",
        "/ontology",
        "/policies",
        "/settings",
        "/simulation",
        "/tenants",
        "/workflows",
      ].sort(),
    );
  });

  it("keeps Settings canonical while leaving its desktop rail slot to the footer", () => {
    const desktopHrefs = desktopNavGroups.flatMap((group) =>
      group.items.map((item) => item.href),
    );

    expect(navItems.map((item) => item.href)).toContain("/settings");
    expect(desktopHrefs).not.toContain("/settings");
  });

  it.each([
    ["/policies/policy_egress", "/policies"],
    ["/tenants/tenant_acme", "/tenants"],
    ["/settings/sessions", "/settings"],
    ["/agents", "/agents"],
    ["/agentship", null],
    ["/not-a-console-route", null],
  ])("resolves %s to its owning console route", (pathname, expectedHref) => {
    expect(resolveNavItem(pathname)?.href ?? null).toBe(expectedHref);
  });

  it("matches the overview only at the route root", () => {
    expect(isNavActive("/", "/")).toBe(true);
    expect(isNavActive("/approvals", "/")).toBe(false);
  });

  it("gives every item a unique icon", () => {
    const icons = navItems.map((item) => item.icon);

    expect(new Set(icons).size).toBe(icons.length);
  });

  it("reserves the badge slot for pending approvals", () => {
    const badged = navItems.filter((item) => item.badge);

    expect(badged).toEqual([
      expect.objectContaining({ href: "/approvals", badge: "approvals" }),
    ]);
  });
});
