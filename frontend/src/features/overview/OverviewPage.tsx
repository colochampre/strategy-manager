import { useTranslation } from "react-i18next";

import { BookingsListView } from "@/features/bookings/BookingsListView";
import { useExchangeScope } from "@/shared/scope/exchange-store";

/**
 * Placeholder until PR 11. The pending-bookings list lives here, where the
 * design puts it (the right-hand decision rail), filtered by the selected
 * exchange (owner decision 3).
 *
 * The rail only renders bookings once the scope is KNOWN. While pools load, or
 * when they fail, it says so instead: the exchange tabs claim a filter, and
 * showing every exchange's bookings under them would contradict it. An
 * approve button on another exchange's proposal is the cost of that mistake.
 */
export function OverviewPage() {
  const { t } = useTranslation();
  const scope = useExchangeScope();

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-2xl font-bold text-ink">{t("overview.title")}</h1>
      <aside aria-labelledby="decision-rail-title" className="flex flex-col gap-3">
        <h2 id="decision-rail-title" className="font-display text-base font-semibold text-ink">
          {t("overview.decisionRail.title")}
        </h2>
        {scope.status === "loading" && (
          <p role="status" className="text-sm text-ink-3">
            {t("overview.decisionRail.scopeLoading")}
          </p>
        )}
        {scope.status === "error" && (
          <p role="alert" className="rounded-md border border-loss bg-panel p-4 text-sm text-ink-2">
            {t("overview.decisionRail.scopeError")}
          </p>
        )}
        {scope.status === "ready" && scope.exchange === null && (
          <p className="text-sm text-ink-3">{t("overview.decisionRail.noExchanges")}</p>
        )}
        {scope.status === "ready" && scope.exchange !== null && (
          <BookingsListView exchange={scope.exchange} />
        )}
      </aside>
    </div>
  );
}
