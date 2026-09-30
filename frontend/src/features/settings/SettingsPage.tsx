import { useTranslation } from "react-i18next";

/** Placeholder until PR 13. */
export function SettingsPage() {
  const { t } = useTranslation();

  return <h1 className="font-display text-2xl font-bold text-ink">{t("settings.title")}</h1>;
}
