export interface NavItem {
  to: string;
  /** Key under `nav.*` in the locale files. */
  labelKey: "overview" | "strategies" | "discrepancies" | "settings";
  /** `/` would otherwise stay active on every route. */
  end: boolean;
  /** The item carries the `NavBadge` of what needs the owner. */
  badge?: true;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/", labelKey: "overview", end: true },
  { to: "/strategies", labelKey: "strategies", end: false },
  { to: "/discrepancies", labelKey: "discrepancies", end: false, badge: true },
  { to: "/settings", labelKey: "settings", end: false },
];
