import { useTranslation } from "react-i18next";

import { PoolPanel } from "@/features/overview/PoolPanel";
import { orderPools } from "@/features/overview/poolOrder";
import { usePools } from "@/shared/api/pools";
import { useExchangeScope } from "@/shared/scope/exchange-store";

/**
 * The Overview container: one `PoolPanel` per pool of the selected exchange,
 * never merged (rule 7), in the interim order of `orderPools` (decision 37),
 * in ONE column that takes the whole width (decision 36: the chart's HEIGHT is
 * bounded, not the panel's width). There is no decision rail, no column beside
 * the panels and no slot between a chart and its grid (owner decision 66).
 *
 * Nothing pool-scoped renders until the exchange scope is KNOWN: while pools
 * load or have failed there is no panel and no performance request, because
 * unfiltered data under an exchange tab claims a filter that is not applied.
 * The page says why, under its title, where the panels would be: loading,
 * failed, or no exchange configured (design addendum "PR 15" § H and § K row 7).
 */
export function OverviewPage() {
  const { t } = useTranslation();
  const scope = useExchangeScope();
  const pools = usePools();

  const panels =
    scope.status === "ready" && scope.exchange !== null && pools.data !== undefined
      ? orderPools(pools.data.filter((pool) => pool.exchange === scope.exchange))
      : [];

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-2xl font-bold text-ink">{t("overview.title")}</h1>
      {scope.status === "loading" && (
        <p role="status" className="text-sm text-ink-3">
          {t("overview.scope.loading")}
        </p>
      )}
      {scope.status === "error" && (
        <p role="alert" className="rounded-md border border-loss bg-panel p-4 text-sm text-ink-2">
          {t("overview.scope.error")}
        </p>
      )}
      {scope.status === "ready" && scope.exchange === null && (
        <p className="text-sm text-ink-3">{t("overview.scope.noExchanges")}</p>
      )}
      {panels.length > 0 && (
        <div data-testid="overview-layout" className="flex min-w-0 flex-col gap-10">
          {panels.map((pool) => (
            <PoolPanel key={`${pool.exchange}/${pool.venue}/${pool.settlement_currency}`} pool={pool} />
          ))}
        </div>
      )}
    </div>
  );
}
