import { useState } from "react";
import { useTranslation } from "react-i18next";

import { LedgerLine } from "@/features/overview/LedgerLine";
import { MonthlyGrid } from "@/features/overview/MonthlyGrid";
import { MonthlySummary } from "@/features/overview/MonthlySummary";
import { DEFAULT_RANGE, RangeSelector } from "@/features/overview/RangeSelector";
import type { RangeName } from "@/features/overview/RangeSelector";
import { ReturnChart } from "@/features/overview/ReturnChart";
import { PairStatsTable } from "@/features/strategies/PairStatsTable";
import { useStrategyPerformance } from "@/shared/api/performance";
import type { StrategyPerformance as StrategyReport } from "@/shared/api/types";

interface StrategyPerformanceProps {
  strategyId: string;
}

interface ReportViewProps {
  report: StrategyReport;
  /** When the report was read (ms): the "now" the chart's range windows end on. */
  asOf: number;
}

function ReportView({ report, asOf }: ReportViewProps) {
  const { t } = useTranslation();
  const [range, setRange] = useState<RangeName>(DEFAULT_RANGE);
  const summary = report.ranges.find((entry) => entry.range === range);

  return (
    <>
      <div className="flex min-w-0 flex-col gap-3">
        {summary === undefined ? (
          <p role="alert" data-testid="ledger-line" className="text-sm text-loss">
            {t("overview.ledger.unreadable")}
          </p>
        ) : (
          <LedgerLine
            currency={report.currency}
            range={range}
            pnl={summary.pnl}
            ret={summary.return}
            maxDrawdown={report.max_drawdown}
            returnLabel={t("strategies.performance.contribution", { range: t(`overview.range.${range}`) })}
          />
        )}
        <ReturnChart
          curve={report.curve}
          range={range}
          asOf={asOf}
          title={t("strategies.performance.chartTitle")}
          headerAction={<RangeSelector value={range} onChange={setRange} />}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <MonthlyGrid monthly={report.monthly} />
        <MonthlySummary monthly={report.monthly} excluded={report.excluded} />
      </div>
      <PairStatsTable pairs={report.by_pair} currency={report.currency} />
    </>
  );
}

/**
 * One strategy's performance, in its own pool's currency: the Overview's ledger
 * line, return chart and monthly grid fed with the strategy's report (its
 * contribution to the pool, `r = pnl / the pool's capital at open`), then the
 * By pair table of the same report. The Overview's components are reused as
 * they are; only the lead figure, the return's label and the chart's title are
 * the strategy's. It fetches once, so every part of it loads, fails and
 * refreshes together.
 */
export function StrategyPerformance({ strategyId }: StrategyPerformanceProps) {
  const { t } = useTranslation();
  const performance = useStrategyPerformance(strategyId);

  if (performance.status === "pending") {
    return (
      <p role="status" className="text-sm text-ink-3">
        {t("strategies.performance.loading")}
      </p>
    );
  }
  if (performance.status === "error") {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-loss bg-panel p-4">
        <p role="alert" className="text-sm text-ink-2">
          {t("strategies.performance.error")}
        </p>
        <button
          type="button"
          onClick={() => void performance.refetch()}
          className="min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2"
        >
          {t("strategies.performance.retry")}
        </button>
      </div>
    );
  }
  if (performance.data === null) {
    return (
      <p role="status" className="text-sm text-ink-3">
        {t("strategies.performance.noReport")}
      </p>
    );
  }
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <ReportView report={performance.data} asOf={performance.dataUpdatedAt} />
    </div>
  );
}
