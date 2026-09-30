import { useTranslation } from "react-i18next";

import { DecisionRail } from "@/features/overview/DecisionRail";
import { PoolPanel } from "@/features/overview/PoolPanel";
import { usePools } from "@/shared/api/pools";
import { useIsWide } from "@/shared/layout/useIsWide";
import { useExchangeScope } from "@/shared/scope/exchange-store";

/**
 * From Tailwind's `xl`, the rail sits beside the panel. Below it the panel would
 * keep under 700 px once the rail takes its 15 rem floor, less than the 13
 * columns of the month grid need, so the rail goes in-flow there instead.
 */
const RAIL_BESIDE_QUERY = "(min-width: 1280px)";

/**
 * The Overview container: one `PoolPanel` per pool of the selected exchange,
 * never merged (rule 7), and the decision rail, placed once.
 *
 * From `xl` (1280 px) the rail is the column beside the panels, which fill
 * the rest of the width (decision 36: the chart's HEIGHT is bounded, not the
 * panel's width); the rail is fluid, 15 rem to 22.5 rem.
 * Narrower, it is an in-flow block
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
  const wide = useIsWide(RAIL_BESIDE_QUERY);

  const panels =
    scope.status === "ready" && scope.exchange !== null && pools.data !== undefined
      ? pools.data.filter((pool) => pool.exchange === scope.exchange)
      : [];
  const rail = <DecisionRail scope={scope} placement={wide ? "right-rail" : "in-flow"} />;
  const railInFirstPanel = !wide && panels.length > 0;

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-2xl font-bold text-ink">{t("overview.title")}</h1>
      <div data-testid="overview-layout" className="flex flex-col gap-7 xl:flex-row xl:items-start">
        <div className="flex min-w-0 flex-col gap-10 xl:flex-1">
          {panels.map((pool, index) => (
            <PoolPanel
              key={`${pool.exchange}/${pool.venue}/${pool.settlement_currency}`}
              pool={pool}
              betweenChartAndGrid={railInFirstPanel && index === 0 ? rail : null}
            />
          ))}
        </div>
        {!railInFirstPanel && (
          <div data-testid="rail-slot" className="min-w-0 xl:w-[clamp(15rem,25%,22.5rem)] xl:shrink-0">
            {rail}
          </div>
        )}
      </div>
    </div>
  );
}
