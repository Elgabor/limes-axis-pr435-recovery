import { createElement, type ComponentType } from "react";

import {
  AiBrain01Icon,
  Building01Icon,
  DashboardSquare01Icon,
  Database01Icon,
  ElectricPlugsIcon,
  HierarchySquare01Icon,
  Invoice01Icon,
  Legal01Icon,
  Route01Icon,
  SecurityCheckIcon,
  Settings01Icon,
  TestTube01Icon,
  WorkflowSquare01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";

import type { NavIcon } from "@/lib/nav";

type NavIconComponent = ComponentType<{ size?: number; className?: string }>;

/**
 * Hugeicons render through a single `HugeiconsIcon` component that takes the
 * icon data as a prop. Wrapping each one preserves the `<Icon size={n} />`
 * interface the shell and command menu already use, so changing icon set stays
 * a change to this module alone.
 *
 * `strokeWidth` is pinned above the 1.5 default: an 18px glyph at 1.5 reads
 * thin next to the 13px medium-weight nav labels.
 */
function navIcon(icon: typeof DashboardSquare01Icon): NavIconComponent {
  return function NavIconGlyph({ size = 18, className }) {
    return createElement(HugeiconsIcon, { className, icon, size, strokeWidth: 1.8 });
  };
}

/** Maps `lib/nav.ts` icon names to components for the shell + command menu. */
export const navIconMap: Record<NavIcon, NavIconComponent> = {
  gauge: navIcon(DashboardSquare01Icon),
  network: navIcon(HierarchySquare01Icon),
  workflow: navIcon(WorkflowSquare01Icon),
  bot: navIcon(AiBrain01Icon),
  route: navIcon(Route01Icon),
  shield: navIcon(SecurityCheckIcon),
  scroll: navIcon(Legal01Icon),
  receipt: navIcon(Invoice01Icon),
  flask: navIcon(TestTube01Icon),
  cable: navIcon(ElectricPlugsIcon),
  database: navIcon(Database01Icon),
  building: navIcon(Building01Icon),
  settings: navIcon(Settings01Icon),
};
