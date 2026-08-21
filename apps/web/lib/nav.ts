import { strings } from "@/lib/strings";

/*
 * Grouped navigation model for the console shell and command menu. Icons are
 * referenced by name so this module stays renderable in node test envs; the
 * shell maps names to icon components in `components/nav-icons.ts`.
 */

export type NavIcon =
  | "gauge"
  | "network"
  | "workflow"
  | "bot"
  | "route"
  | "shield"
  | "scroll"
  | "receipt"
  | "flask"
  | "cable"
  | "building"
  | "settings";

export type NavItem = {
  href: string;
  label: string;
  icon: NavIcon;
  /** Named badge slot rendered by the shell (currently only pending approvals). */
  badge?: "approvals";
};

export type NavGroup = {
  label: string;
  items: NavItem[];
};

const pages = strings.pages;

export const navGroups: NavGroup[] = [
  {
    label: strings.nav.operate,
    items: [
      { href: "/", label: pages.overview.title, icon: "gauge" },
      { href: "/approvals", label: pages.approvals.title, icon: "shield", badge: "approvals" },
      { href: "/workflows", label: pages.workflows.title, icon: "workflow" },
      { href: "/agents", label: pages.agents.title, icon: "bot" },
    ],
  },
  {
    label: strings.nav.dataAndModels,
    items: [
      { href: "/ontology", label: pages.ontology.title, icon: "network" },
      { href: "/connectors", label: pages.connectors.title, icon: "cable" },
      { href: "/model-routing", label: pages["model-routing"].title, icon: "route" },
    ],
  },
  {
    label: strings.nav.governance,
    items: [
      { href: "/policies", label: pages.policies.title, icon: "scroll" },
      { href: "/audit", label: pages.audit.title, icon: "receipt" },
      { href: "/simulation", label: pages.simulation.title, icon: "flask" },
    ],
  },
  {
    label: strings.nav.platform,
    items: [
      { href: "/tenants", label: pages.tenants.title, icon: "building" },
      { href: "/settings", label: pages.settings.title, icon: "settings" },
    ],
  },
];

/** Canonical flat route list used by route resolution and non-rail navigation. */
export const navItems: NavItem[] = navGroups.flatMap((group) => group.items);

/**
 * The desktop rail keeps Settings in its account footer, where identity and
 * deployment controls already live. Every other navigation surface consumes
 * the canonical groups above so Settings remains discoverable on mobile and in
 * command search without appearing twice in the rail.
 */
export const desktopNavGroups: NavGroup[] = navGroups.map((group) => ({
  ...group,
  items: group.items.filter((item) => item.href !== "/settings"),
}));

/** Match a route boundary without treating similar prefixes as descendants. */
export function isNavActive(pathname: string, href: string): boolean {
  if (href === "/") {
    return pathname === "/";
  }

  return pathname === href || pathname.startsWith(`${href}/`);
}

/** Resolve dynamic detail routes to the section that owns them. */
export function resolveNavItem(pathname: string): NavItem | null {
  return navItems.find((item) => isNavActive(pathname, item.href)) ?? null;
}
