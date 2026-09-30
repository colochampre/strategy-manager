import { useTranslation } from "react-i18next";

import { BookingsListView } from "@/features/bookings/BookingsListView";

/**
 * Placeholder until PR 11. The pending-bookings list already lives here,
 * where the design puts it (the right-hand decision rail); PR 10c filters it
 * by exchange.
 */
export function OverviewPage() {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-2xl font-bold text-ink">{t("overview.title")}</h1>
      <aside aria-labelledby="decision-rail-title" className="flex flex-col gap-3">
        <h2 id="decision-rail-title" className="font-display text-base font-semibold text-ink">
          {t("overview.decisionRail.title")}
        </h2>
        <BookingsListView />
      </aside>
    </div>
  );
}
