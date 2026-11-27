import { ArrowLeftRight, Bell, LayoutDashboard, Link2, ShieldCheck, TrendingUp } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { useMe } from "@/shared/api/me";

/** A page the sidebar links to. `labelKey` is a key under `nav.*` in the locale files. */
export interface NavLinkItem {
  to: string;
  labelKey:
    | "overview"
    | "trades"
    | "authored"
    | "subscriptions"
    | "explore"
    | "exchanges"
    | "discrepancies"
    | "users"
    | "notifications";
  /** `/` and `/strategies` would otherwise stay active on every route under them. */
  end: boolean;
  /** The item carries the `NavBadge` of what needs the owner. */
  badge?: true;
}

/** A button that opens a list of pages, as Strategies does. */
export interface NavGroup {
  id: "strategies" | "admin";
  icon: LucideIcon;
  labelKey: "strategies" | "admin";
  children: readonly NavLinkItem[];
  /** The group is open when the sidebar first draws, whatever the page. */
  openByDefault: boolean;
  /** Offered to the admin alone (AD11). The server enforces it anyway. */
  adminOnly?: true;
}

export interface NavLeaf extends NavLinkItem {
  icon: LucideIcon;
}

export const OVERVIEW: NavLeaf = { to: "/", icon: LayoutDashboard, labelKey: "overview", end: true };
/** Every operation of the user, open and closed, from every strategy (S5, RD.4). */
export const TRADES: NavLeaf = { to: "/trades", icon: ArrowLeftRight, labelKey: "trades", end: false };
/** Where the API keys are managed (S4, S9), apart from Mi cuenta. */
export const EXCHANGES: NavLeaf = { to: "/exchanges", icon: Link2, labelKey: "exchanges", end: false };
/** The user's operations, the safety events and the notices of their account in one feed (S6, RD.5). */
export const NOTIFICATIONS: NavLeaf = { to: "/notifications", icon: Bell, labelKey: "notifications", end: false };

export const STRATEGIES: NavGroup = {
  id: "strategies",
  icon: TrendingUp,
  labelKey: "strategies",
  openByDefault: true,
  children: [
    { to: "/strategies/authored", labelKey: "authored", end: false },
    // `end`: the path of every other list starts with it.
    { to: "/strategies", labelKey: "subscriptions", end: true },
    { to: "/strategies/explore", labelKey: "explore", end: false },
  ],
};

export const ADMIN: NavGroup = {
  id: "admin",
  icon: ShieldCheck,
  labelKey: "admin",
  openByDefault: false,
  adminOnly: true,
  children: [
    { to: "/discrepancies", labelKey: "discrepancies", end: false, badge: true },
    { to: "/users", labelKey: "users", end: false },
  ],
};

/** The pages the sidebar offers this person, top part then foot. Until `me` answers they are not the admin's, so no stranger sees them flash by. */
export function useNavigation(): { main: readonly (NavLeaf | NavGroup)[]; admin: NavGroup | null } {
  const { data } = useMe();
  return { main: [OVERVIEW, NOTIFICATIONS, TRADES, STRATEGIES, EXCHANGES], admin: data?.isAdmin === true ? ADMIN : null };
}
