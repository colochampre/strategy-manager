import { useTranslation } from "react-i18next";

/**
 * PLACEHOLDER (cd.2.7): the title and the sentence, so the route has a page. cd.2.10 to cd.2.13 draw the read
 * states, the lists and the bookings.
 */
export function DiscrepanciesPage() {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col items-start gap-3">
      <h1 className="font-display text-2xl font-bold text-ink">{t("discrepancies.title")}</h1>
      <p className="text-sm text-ink-2">{t("discrepancies.lede")}</p>
    </div>
  );
}
