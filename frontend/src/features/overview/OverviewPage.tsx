import { useTranslation } from "react-i18next";

import { DecisionRail } from "@/features/overview/DecisionRail";
import { PoolPanel } from "@/features/overview/PoolPanel";
import { usePools } from "@/shared/api/pools";
import { useIsWide } from "@/shared/layout/useIsWide";
import { useExchangeScope } from "@/shared/scope/exchange-store";

/**
 * The Overview container: one `PoolPanel` per pool of the selected exchange,
 * never merged (rule 7), and the decision rail, placed once.
 *
 * Wide, the rail is the right-hand column. Narrow, it is an in-flow block
 * between the first panel's chart and its month grid (Mobile.dc.html), or
 * after the page when there is no panel to sit in. It is rendered in exactly
 * one place either way.
 *
 * Nothing pool-scoped renders until the exchange scope is KNOWN: while pools
 * load or have failed there is no panel, no performance request and no
 * bookings, because unfiltered data under an exchange tab claims a filter that
 * is not applied. The rail says why.
 */
export function OverviewPage() {
  const { t } = useTranslation();
  const scope = useExchangeScope();
  const pools = usePools();
  const wide = useIsWide();

  const panels =
    scope.status === "ready" && scope.exchange !== null && pools.data !== undefined
      ? pools.data.filter((pool) => pool.exchange === scope.exchange)
      : [];
  const rail = <DecisionRail scope={scope} placement={wide ? "right-rail" : "in-flow"} />;
  const railInFirstPanel = !wide && panels.length > 0;

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-2xl font-bold text-ink">{t("overview.title")}</h1>
      <div className="flex flex-col gap-7 lg:grid lg:grid-cols-[minmax(0,1fr)_22.5rem] lg:items-start">
        <div className="flex min-w-0 flex-col gap-10">
          {panels.map((pool, index) => (
            <PoolPanel
              key={`${pool.exchange}/${pool.venue}/${pool.settlement_currency}`}
              pool={pool}
              betweenChartAndGrid={railInFirstPanel && index === 0 ? rail : null}
            />
          ))}
        </div>
        {!railInFirstPanel && rail}
      </div>
    </div>
  );
}
