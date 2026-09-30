import { useTranslation } from "react-i18next";
import { NavLink } from "react-router";

import { cn } from "@/shared/lib/cn";
import { NAV_ITEMS } from "@/shared/layout/navItems";

/** The left rail: hidden below `lg`, where `BottomNav` takes over. */
export function SideNav() {
  const { t } = useTranslation();

  return (
    <nav
      aria-label={t("nav.sections")}
      className="hidden w-52 shrink-0 flex-col gap-1 border-r border-rule bg-panel px-3 py-6 lg:flex"
    >
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            cn(
              "rounded-md px-3.5 py-3 text-sm transition-colors",
              isActive
                ? "bg-panel-2 font-semibold text-ink"
                : "text-ink-2 hover:bg-panel-2 hover:text-ink",
            )
          }
        >
          {t(`nav.${item.labelKey}`)}
        </NavLink>
      ))}
    </nav>
  );
}
