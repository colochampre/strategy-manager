import { ChartCandlestick, LayoutDashboard, Scale, Settings, ShieldAlert, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useMe } from "@/shared/api/me";

export interface NavItem {
  to: string;
  /** Drawn beside the name in the side rail and alone in the bottom bar. */
  icon: LucideIcon;
  /** Key under `nav.*` in the locale files. */
  labelKey: "overview" | "strategies" | "discrepancies" | "users" | "safetyEvents" | "settings";
  /** `/` would otherwise stay active on every route. */
  end: boolean;
  /** The item carries the `NavBadge` of what needs the owner. */
  badge?: true;
  /** Offered to the admin alone (AD11). The server enforces it anyway. */
  adminOnly?: true;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/", icon: LayoutDashboard, labelKey: "overview", end: true },
  { to: "/strategies", icon: ChartCandlestick, labelKey: "strategies", end: false },
  { to: "/discrepancies", icon: Scale, labelKey: "discrepancies", end: false, badge: true, adminOnly: true },
  { to: "/users", icon: Users, labelKey: "users", end: false, adminOnly: true },
  { to: "/safety-events", icon: ShieldAlert, labelKey: "safetyEvents", end: false },
  { to: "/settings", icon: Settings, labelKey: "settings", end: false },
];

/** The items this person is offered: until the answer is known they are not the admin's, so no stranger sees them flash by. */
export function useNavItems(): readonly NavItem[] {
  const { data } = useMe();
  return NAV_ITEMS.filter((item) => item.adminOnly !== true || data?.isAdmin === true);
}
