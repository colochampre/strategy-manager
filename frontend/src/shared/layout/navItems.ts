export interface NavItem {
  to: string;
  /** Key under `nav.*` in the locale files. */
  labelKey: "overview" | "strategies" | "settings";
  /** `/` would otherwise stay active on every route. */
  end: boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/", labelKey: "overview", end: true },
  { to: "/strategies", labelKey: "strategies", end: false },
  { to: "/settings", labelKey: "settings", end: false },
];
