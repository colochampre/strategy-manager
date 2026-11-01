import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router";

import { cn } from "@/shared/lib/cn";

/** `end` on the first: every other list's path starts with its path. */
const LISTS = [
  { to: "/strategies", key: "strategies.tabs.subscriptions", end: true },
  { to: "/strategies/explore", key: "strategies.tabs.explore", end: false },
  { to: "/strategies/authored", key: "strategies.tabs.authored", end: false },
];

/** The three lists of Strategies under one heading: what the user holds, what is public, and what they wrote. */
export function StrategiesLayout() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-2xl font-bold text-ink">{t("strategies.title")}</h1>
      <nav aria-label={t("strategies.tabs.label")} className="flex min-w-0 items-center gap-1 overflow-x-auto">
        {LISTS.map((list) => (
          <NavLink
            key={list.to}
            to={list.to}
            end={list.end}
            className={({ isActive }) =>
              cn(
                "inline-flex min-h-11 items-center whitespace-nowrap rounded-md px-3.5 text-sm transition-colors",
                isActive ? "bg-panel-2 font-semibold text-ink" : "text-ink-3 hover:bg-panel-2 hover:text-ink",
              )
            }
          >
            {t(list.key)}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
