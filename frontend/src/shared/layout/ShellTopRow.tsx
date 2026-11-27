import { Menu, User } from "lucide-react";
import type { Ref } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation } from "react-router";

import { BrandIcon } from "@/shared/layout/BrandIcon";
import { ExchangeTabs } from "@/shared/layout/ExchangeTabs";
import { Flag } from "@/shared/layout/Flag";
import { ModeBadge } from "@/shared/layout/ModeBadge";
import { NotificationBell } from "@/shared/layout/NotificationBell";
import { isExchangeScoped } from "@/shared/scope/exchange-store";

/** One size for every icon button of the row (S7: "Que los iconos queden del mismo tamaño"): 36 px, as the prototype draws them. */
export const ICON_BUTTON =
  "inline-flex size-9 shrink-0 items-center justify-center rounded-lg border border-rule bg-panel text-ink-2 transition-colors hover:bg-panel-2 hover:text-ink motion-reduce:transition-none";

interface ShellTopRowProps {
  /** The user has not signed up yet (public-site LS2): nothing of the panel to go to or act on. */
  pending: boolean;
  onOpenMenu: () => void;
  menuRef: Ref<HTMLButtonElement>;
}

/**
 * The row above every page's header, where the top bar used to be. On the left the exchange buttons, only on the pages
 * the exchange scopes (the same `isExchangeScoped` the pages read); on the right the mode, the person (to My account),
 * the bell (to Notifications) and the language, in that order. Below `lg` the hamburger takes the left, and the exchange buttons drop to a row
 * of their own that scrolls sideways when they do not fit. The same row on every page, so nothing jumps when
 * navigating: the exchange buttons, the mode badge and the icon buttons are all 36 px tall, so the row is too,
 * whether it holds the exchange buttons or not.
 */
export function ShellTopRow({ pending, onOpenMenu, menuRef }: ShellTopRowProps) {
  const { t, i18n } = useTranslation();
  const scoped = isExchangeScoped(useLocation().pathname) && !pending;

  const toggleLanguage = () => {
    void i18n.changeLanguage(i18n.resolvedLanguage === "es" ? "en" : "es");
  };

  return (
    <div className="mb-7 flex flex-wrap items-center gap-x-3 gap-y-4 lg:min-h-9">
      {pending ? (
        // A newcomer has no sidebar to carry the brand.
        <span className="flex items-center gap-2.5">
          <BrandIcon />
          <span className="font-display text-[15px] font-semibold tracking-[0.01em] text-ink">{t("app.name")}</span>
        </span>
      ) : (
        <button
          ref={menuRef}
          type="button"
          aria-label={t("nav.openMenu")}
          onClick={onOpenMenu}
          className={`${ICON_BUTTON} lg:hidden`}
        >
          <Menu aria-hidden="true" className="size-4" />
        </button>
      )}
      {scoped && <ExchangeTabs className="order-3 w-full lg:order-2 lg:w-auto" />}
      <div role="group" aria-label={t("nav.tools")} className="order-2 ml-auto flex items-center gap-2 lg:order-3">
        {!pending && <ModeBadge />}
        {!pending && (
          <Link to="/settings" aria-label={t("nav.account")} className={ICON_BUTTON}>
            <User aria-hidden="true" className="size-4" />
          </Link>
        )}
        {!pending && <NotificationBell className={ICON_BUTTON} />}
        <button type="button" onClick={toggleLanguage} aria-label={t("app.language")} className={ICON_BUTTON}>
          <Flag country={i18n.resolvedLanguage === "es" ? "ar" : "us"} />
        </button>
      </div>
    </div>
  );
}
