import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";

import { useMe } from "@/shared/api/me";
import { ExchangeTabs } from "@/shared/layout/ExchangeTabs";
import { Flag } from "@/shared/layout/Flag";
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
        {/* From lg the brand's box is fixed, so the tabs start just past the side bar whatever the font draws:
            1.75rem of padding, 9.5rem of brand and 2rem of gap make 13.25rem, the side bar's 13rem (SideNav) plus
            4px. A fixed box, not a wider gap: a gap adds to the text's own width, which the font decides. */}
        <span className="font-display text-base font-semibold text-ink lg:w-38 lg:shrink-0">{t("app.name")}</span>
        {scoped && <ExchangeTabs className="hidden lg:flex" />}
        <div className="ml-auto flex min-w-0 items-center gap-3">
          {signedInAs !== undefined && (
            <span className="hidden max-w-56 truncate text-sm font-medium text-ink lg:inline">{signedInAs}</span>
          )}
          <ModeBadge />
          <button
            type="button"
            onClick={toggleLanguage}
            aria-label={t("app.language")}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-md px-2 text-xs uppercase text-ink-3 hover:text-ink"
          >
            {/* The language in use, its flag beside its code; the button's name says what pressing it does. */}
            <Flag country={i18n.resolvedLanguage === "es" ? "ar" : "us"} />
            {i18n.resolvedLanguage === "es" ? "es" : "en"}
          </button>
        </div>
      </div>
      {scoped && <ExchangeTabs className="border-t border-rule px-4 lg:hidden" />}
    </header>
  );
}
