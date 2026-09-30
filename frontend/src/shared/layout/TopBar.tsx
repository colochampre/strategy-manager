import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";

import { DryRunBadge } from "@/shared/layout/DryRunBadge";
import { ExchangeTabs } from "@/shared/layout/ExchangeTabs";
import { isExchangeScoped } from "@/shared/scope/exchange-store";

/**
 * Brand, exchange tabs (scoped routes only), mode badge, language toggle. The
 * tabs render twice, like the two navigations: in the bar from `lg`, and on
 * narrow screens as their own scrollable row below it.
 */
export function TopBar() {
  const { t, i18n } = useTranslation();
  const scoped = isExchangeScoped(useLocation().pathname);

  const toggleLanguage = () => {
    void i18n.changeLanguage(i18n.resolvedLanguage === "es" ? "en" : "es");
  };

  return (
    <header className="shrink-0 border-b border-rule bg-panel">
      <div className="flex h-14 items-center gap-4 px-4 lg:h-16 lg:gap-8 lg:px-7">
        <span className="font-display text-base font-semibold text-ink">{t("app.name")}</span>
        {scoped && <ExchangeTabs className="hidden lg:flex" />}
        <div className="ml-auto flex items-center gap-3">
          <DryRunBadge />
          <button
            type="button"
            onClick={toggleLanguage}
            className="min-h-11 rounded-md px-2 text-xs uppercase text-ink-3 hover:text-ink"
          >
            {i18n.resolvedLanguage === "es" ? "en" : "es"}
          </button>
        </div>
      </div>
      {scoped && <ExchangeTabs className="border-t border-rule px-4 lg:hidden" />}
    </header>
  );
}
