import { useTranslation } from "react-i18next";
import { NavLink } from "react-router";

import { cn } from "@/shared/lib/cn";
import { NavBadge } from "@/shared/layout/NavBadge";
import { NAV_ITEMS } from "@/shared/layout/navItems";

/**
 * The phone navigation: hidden from `lg`. It is the last row of the shell's
 * flex column rather than a fixed overlay, so the content area ends where it
 * starts and no bottom padding has to reserve its height.
 */
export function BottomNav() {
  const { t } = useTranslation();

  return (
    <nav
      aria-label={t("nav.sections")}
      className="flex shrink-0 border-t border-rule bg-panel lg:hidden"
    >
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            cn(
              "relative flex min-h-11 min-w-0 flex-1 items-end justify-center whitespace-nowrap pb-2 text-xs transition-colors",
              isActive ? "bg-panel-2 font-semibold text-ink" : "text-ink-3",
            )
          }
        >
          <span>{t(`nav.${item.labelKey}`)}</span>
          {item.badge && <NavBadge corner />}
        </NavLink>
      ))}
    </nav>
  );
}
