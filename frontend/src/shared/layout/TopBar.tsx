import { Languages } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";

import { useMe } from "@/shared/api/me";
import { ExchangeTabs } from "@/shared/layout/ExchangeTabs";
import { ModeBadge } from "@/shared/layout/ModeBadge";
import { isExchangeScoped } from "@/shared/scope/exchange-store";

/**
 * Brand, exchange tabs (scoped routes only), who is signed in (from `lg`), mode
 * badge, language toggle. The tabs render twice, like the two navigations: in
 * the bar from `lg`, and on narrow screens as their own scrollable row below it.
 */
export function TopBar() {
  const { t, i18n } = useTranslation();
  const scoped = isExchangeScoped(useLocation().pathname);
  const me = useMe().data;
  const signedInAs = me?.displayName ?? me?.email;

  const toggleLanguage = () => {
    void i18n.changeLanguage(i18n.resolvedLanguage === "es" ? "en" : "es");
  };

  return (
    <header className="shrink-0 border-b border-rule bg-panel">
      <div className="flex h-14 items-center gap-4 px-4 lg:h-16 lg:gap-8 lg:px-7">
        {/* From lg the brand's box ends so that the tabs start where the page does: 1.75rem of padding, 11.5rem of
            brand and 2rem of gap make the side bar's 13rem plus main's 2.25rem (AppShell, SideNav). */}
        <span className="font-display text-base font-semibold text-ink lg:w-46 lg:shrink-0">{t("app.name")}</span>
        {scoped && <ExchangeTabs className="hidden lg:flex" />}
        <div className="ml-auto flex min-w-0 items-center gap-3">
          {signedInAs !== undefined && (
            <span className="hidden max-w-56 truncate text-sm font-medium text-ink lg:inline">{signedInAs}</span>
          )}
          <ModeBadge />
          <button
            type="button"
            onClick={toggleLanguage}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-md px-2 text-xs uppercase text-ink-3 hover:text-ink"
          >
            <Languages aria-hidden="true" className="size-4 shrink-0" />
            {i18n.resolvedLanguage === "es" ? "en" : "es"}
          </button>
        </div>
      </div>
      {scoped && <ExchangeTabs className="border-t border-rule px-4 lg:hidden" />}
    </header>
  );
}
