import { ChartCandlestick, LayoutDashboard, Scale, Settings } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  to: string;
  /** Drawn beside the name in the side rail and alone in the bottom bar. */
  icon: LucideIcon;
  /** Key under `nav.*` in the locale files. */
  labelKey: "overview" | "strategies" | "discrepancies" | "settings";
  /** `/` would otherwise stay active on every route. */
  end: boolean;
  /** The item carries the `NavBadge` of what needs the owner. */
  badge?: true;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/", icon: LayoutDashboard, labelKey: "overview", end: true },
  { to: "/strategies", icon: ChartCandlestick, labelKey: "strategies", end: false },
  { to: "/discrepancies", icon: Scale, labelKey: "discrepancies", end: false, badge: true },
  { to: "/settings", icon: Settings, labelKey: "settings", end: false },
];
