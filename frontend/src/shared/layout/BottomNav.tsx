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
          title={t(`nav.${item.labelKey}`)}
          className={({ isActive }) =>
            cn(
              "flex min-h-11 min-w-0 flex-1 items-center justify-center transition-colors",
              isActive ? "bg-panel-2 text-ink" : "text-ink-3",
            )
          }
        >
          {/* Icon alone (owner decision 67 Q2): the name stays as visually hidden text, so the badge's hidden words still join it. */}
          <span className="relative flex items-center justify-center px-3">
            <item.icon aria-hidden="true" className="size-5 shrink-0" />
            <span className="sr-only">{t(`nav.${item.labelKey}`)}</span>
            {item.badge && <NavBadge corner />}
          </span>
        </NavLink>
      ))}
    </nav>
  );
}
