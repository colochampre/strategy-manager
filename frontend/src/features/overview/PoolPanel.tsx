import type { ReactNode } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { LedgerLine } from "@/features/overview/LedgerLine";
import { MonthlyGrid } from "@/features/overview/MonthlyGrid";
import { MonthlySummary } from "@/features/overview/MonthlySummary";
import { PoolEyebrow } from "@/features/overview/PoolEyebrow";
import { DEFAULT_RANGE, RangeSelector } from "@/features/overview/RangeSelector";
import type { RangeName } from "@/features/overview/RangeSelector";
import { ReturnChart } from "@/features/overview/ReturnChart";
import { usePoolPerformance } from "@/shared/api/performance";
import type { Pool, PoolPerformance } from "@/shared/api/types";

interface PoolPanelProps {
  pool: Pool;
  /** Rendered between the chart and the month grid: the phone layout's decision rail. */
  betweenChartAndGrid?: ReactNode;
}

/** `2026-09-30T10:00:00+00:00` as a short UTC date and time; the server's clock is UTC. */
function observedAtText(observedAt: string, locale: string): string {
  const instant = new Date(observedAt);
  if (Number.isNaN(instant.getTime())) return observedAt;
  const text = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(instant);
  return `${text} UTC`;
}

interface ReportTopProps {
  pool: Pool;
  report: PoolPerformance;
  range: RangeName;
  onRangeChange: (range: RangeName) => void;
}

/** The ledger line with its range selector, then the chart (which always shows the whole series). */
function ReportTop({ pool, report, range, onRangeChange }: ReportTopProps) {
  const { t } = useTranslation();
  const summary = report.ranges.find((entry) => entry.range === range);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        {summary === undefined ? (
          <p role="alert" data-testid="ledger-line" className="text-sm text-loss">
            {t("overview.ledger.unreadable")}
          </p>
        ) : (
          <LedgerLine
            currency={pool.settlement_currency}
            available={pool.balance === null ? null : pool.balance.available}
            range={range}
            pnl={summary.pnl}
            ret={summary.return}
            maxDrawdown={report.max_drawdown}
          />
        )}
        <RangeSelector value={range} onChange={onRangeChange} />
      </div>
      <ReturnChart curve={report.curve} />
    </div>
  );
}

/**
 * One capital pool, in its own settlement currency and never merged with
 * another (rule 7). It fetches its own report once, and every range arrives
 * in that one body, so the selector only chooses which entry the ledger line
 * shows. A failing pool shows its own error and leaves its neighbours alone.
 *
 * The available balance is the pools row's `balance.available`: the
 * performance body does not carry it.
 *
 * The panel is three slots in a fixed order, top, `betweenChartAndGrid` and
 * bottom, so whatever the caller puts in the middle keeps its place (and its
 * state) while the report loads and arrives.
 */
export function PoolPanel({ pool, betweenChartAndGrid = null }: PoolPanelProps) {
  const { t, i18n } = useTranslation();
  const performance = usePoolPerformance(pool.exchange, pool.venue, pool.settlement_currency);
  const [range, setRange] = useState<RangeName>(DEFAULT_RANGE);
  const staleBalance = pool.balance !== null && pool.balance.stale ? pool.balance : null;
  const report = performance.status === "success" ? performance.data : null;

  let top: ReactNode;
  if (performance.status === "pending") {
    top = (
      <p role="status" className="text-sm text-ink-3">
        {t("overview.pool.loading")}
      </p>
    );
  } else if (performance.status === "error") {
    top = (
      <p role="alert" className="rounded-md border border-loss bg-panel p-4 text-sm text-ink-2">
        {t("overview.pool.error")}
      </p>
    );
  } else if (report === null) {
    top = (
      <p role="status" className="text-sm text-ink-3">
        {t("overview.pool.noReport")}
      </p>
    );
  } else {
    top = <ReportTop pool={pool} report={report} range={range} onRangeChange={setRange} />;
  }

  return (
    <section
      data-testid="pool-panel"
      aria-label={`${pool.exchange} · ${pool.venue} · ${pool.settlement_currency}`}
      className="flex min-w-0 flex-col gap-4"
    >
      <PoolEyebrow exchange={pool.exchange} venue={pool.venue} currency={pool.settlement_currency} />
      {staleBalance !== null && (
        <p data-testid="balance-stale" className="font-mono text-[11px] text-ink-2">
          {t("overview.pool.stale", {
            time: observedAtText(staleBalance.observed_at, i18n.resolvedLanguage ?? "en"),
          })}
        </p>
      )}
      {top}
      {betweenChartAndGrid}
      {report !== null && (
        <div className="flex flex-col gap-2">
          <MonthlyGrid monthly={report.monthly} />
          <MonthlySummary monthly={report.monthly} excluded={report.excluded} />
        </div>
      )}
    </section>
  );
}
