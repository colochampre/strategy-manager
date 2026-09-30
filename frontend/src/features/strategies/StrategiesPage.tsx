import { useTranslation } from "react-i18next";

/** Placeholder until PR 12. */
export function StrategiesPage() {
  const { t } = useTranslation();

  return <h1 className="font-display text-2xl font-bold text-ink">{t("strategies.title")}</h1>;
}
