import { useTranslation } from "react-i18next";

import { DryRunBadge } from "@/shared/layout/DryRunBadge";

export function TopBar() {
  const { t, i18n } = useTranslation();

  const toggleLanguage = () => {
    void i18n.changeLanguage(i18n.resolvedLanguage === "es" ? "en" : "es");
  };

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-rule bg-panel px-4 lg:h-16 lg:px-7">
      <span className="font-display text-base font-semibold text-ink">{t("app.name")}</span>
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
    </header>
  );
}
