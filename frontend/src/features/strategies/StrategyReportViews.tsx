import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PublicRecordReport } from "@/features/strategies/PublicRecordReport";
import { RecordFigures } from "@/features/strategies/RecordFigures";
import { StrategyPerformance } from "@/features/strategies/StrategyPerformance";
import { useOwnSeat } from "@/features/strategies/SubscribePanel";
import { useStrategyPerformance } from "@/shared/api/performance";
import { useMe } from "@/shared/api/me";
import { useHeldSubscriptions } from "@/shared/api/subscriptions";
import type { PublicStrategy } from "@/shared/api/types";
import { cn } from "@/shared/lib/cn";

type View = "record" | "mine";

const VIEWS: readonly View[] = ["mine", "record"];

/** The reader's own trades in this strategy; one that has closed none says so rather than drawing an empty chart. */
function MyResults({ strategyId }: { strategyId: string }) {
  const { t } = useTranslation();
  const performance = useStrategyPerformance(strategyId);
  if (performance.data !== undefined && performance.data !== null && performance.data.trade_count === 0) {
    return (
      <p role="status" className="text-sm text-ink-3">
        {t("strategies.report.mineEmpty")}
      </p>
    );
  }
  return <StrategyPerformance strategyId={strategyId} />;
}

/**
 * The public page's one report (curve, month by month, by pair) in two views, never drawn together: "Strategy
 * record" for anyone, and "My results" only for a reader who holds a seat, the view they open on. Without a seat
 * there is no selector, only the record.
 */
export function StrategyReportViews({ strategy }: { strategy: PublicStrategy }) {
  const { t } = useTranslation();
  const seat = useOwnSeat(strategy);
  const me = useMe();
  const held = useHeldSubscriptions();
  const [chosen, setChosen] = useState<View | null>(null);
  const view: View = seat === undefined ? "record" : (chosen ?? "mine");

  // Whether the reader holds a seat decides the view they open on, so no view is drawn until both reads are
  // settled: otherwise a subscriber would see the record for a moment and then be moved to their own results.
  const settled = !me.isPending && !held.isPending;

  return (
    <section aria-label={t("strategies.report.title")} className="flex min-w-0 flex-col gap-4">
      <h2 className="font-display text-base font-semibold text-ink">{t("strategies.report.title")}</h2>
      {/* The strategy's figures first, the ones its card shows, whichever view is open below. */}
      <RecordFigures strategy={strategy} />
      {!settled && (
        <p role="status" className="text-sm text-ink-3">
          {t("strategies.report.recordLoading")}
        </p>
      )}
      {settled && seat !== undefined && (
        <div role="group" aria-label={t("strategies.report.views")} className="flex flex-wrap gap-2">
          {VIEWS.map((name) => (
            <button
              key={name}
              type="button"
              aria-pressed={name === view}
              onClick={() => setChosen(name)}
              className={cn(
                "min-h-11 rounded-md border border-rule px-3.5 text-sm focus-visible:outline-2 focus-visible:outline-gain",
                name === view ? "bg-panel-2 text-ink" : "bg-transparent text-ink-2",
              )}
            >
              {t(name === "mine" ? "strategies.report.mine" : "strategies.report.record")}
            </button>
          ))}
        </div>
      )}
      {settled &&
        (view === "mine" ? (
          <MyResults strategyId={strategy.id} />
        ) : (
          <PublicRecordReport strategyId={strategy.id} joined={seat?.created_at?.slice(0, 10) ?? null} />
        ))}
    </section>
  );
}
