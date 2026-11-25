import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { LedgerLine } from "@/features/overview/LedgerLine";
import { MonthlyGrid } from "@/features/overview/MonthlyGrid";
import { MonthlySummary } from "@/features/overview/MonthlySummary";
import { RangeSelector } from "@/features/overview/RangeSelector";
import { useRangeStore } from "@/features/overview/range-store";
import { ReturnChart } from "@/features/overview/ReturnChart";
import { PairStatsTable } from "@/features/strategies/PairStatsTable";
import { useStrategyPerformance } from "@/shared/api/performance";
import type { StrategyPerformance as StrategyReport } from "@/shared/api/types";
import { Card } from "@/shared/ui/Card";
import { ReportSection } from "@/shared/ui/ReportSection";

interface PerformanceCardProps {
  /** The range selector, at the right of the title, once there is a chart to pick a range for. */
  action?: ReactNode;
  children: ReactNode;
}

/**
 * The strategy pages' chart card: "Performance" is the card's own title with the range selector at its right, in
 * place of the chart's old title, which is gone (L26). It is drawn in every state of the read, so the page's title is
 * there while the report loads or fails.
 */
export function PerformanceCard({ action, children }: PerformanceCardProps) {
  const { t } = useTranslation();
  return (
    <Card title={t("strategies.report.title")} action={action}>
      {children}
    </Card>
  );
}

interface StrategyPerformanceProps {
  strategyId: string;
  /** Whether to draw the ledger line over the chart; off where the page draws those figures in its own row. */
  ledger?: boolean;
}

interface ReportViewProps {
  report: StrategyReport;
  /** When the report was read (ms): the "now" the chart's range windows end on. */
  asOf: number;
  ledger: boolean;
}

function ReportView({ report, asOf, ledger }: ReportViewProps) {
  const { t } = useTranslation();
  const range = useRangeStore((state) => state.range);
  const setRange = useRangeStore((state) => state.setRange);
  const summary = report.ranges.find((entry) => entry.range === range);

  return (
    <>
      <div className="flex min-w-0 flex-col gap-4">
        {!ledger ? null : summary === undefined ? (
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
          />
        )}
        <PerformanceCard
          action={<RangeSelector value={range} onChange={setRange} />}
        >
          <ReturnChart bare curve={report.curve} origin={report.origin ?? null} range={range} asOf={asOf} />
        </PerformanceCard>
      </div>
      <ReportSection>
        <div className="flex flex-col gap-1.5">
          <MonthlyGrid monthly={report.monthly} />
          <MonthlySummary monthly={report.monthly} excluded={report.excluded} />
        </div>
      </ReportSection>
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
export function StrategyPerformance({ strategyId, ledger = true }: StrategyPerformanceProps) {
  const { t } = useTranslation();
  const performance = useStrategyPerformance(strategyId);

  if (performance.status === "pending") {
    return (
      <PerformanceCard>
        <p role="status" className="text-sm text-ink-3">
          {t("strategies.performance.loading")}
        </p>
      </PerformanceCard>
    );
  }
  if (performance.status === "error") {
    return (
      <PerformanceCard>
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-ink-2">
            {t("strategies.performance.error")}
          </p>
          <button
            type="button"
            onClick={() => void performance.refetch()}
            className="min-h-11 rounded-lg border border-rule px-3.5 text-sm text-ink hover:bg-panel-2"
          >
            {t("strategies.performance.retry")}
          </button>
        </div>
      </PerformanceCard>
    );
  }
  if (performance.data === null) {
    return (
      <PerformanceCard>
        <p role="status" className="text-sm text-ink-3">
          {t("strategies.performance.noReport")}
        </p>
      </PerformanceCard>
    );
  }
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <ReportView report={performance.data} asOf={performance.dataUpdatedAt} ledger={ledger} />
    </div>
  );
}
