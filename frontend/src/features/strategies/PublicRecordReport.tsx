import { useTranslation } from "react-i18next";

import { MonthlyGrid } from "@/features/overview/MonthlyGrid";
import { MonthlySummary } from "@/features/overview/MonthlySummary";
import { RangeSelector } from "@/features/overview/RangeSelector";
import { useRangeStore } from "@/features/overview/range-store";
import { ReturnChart } from "@/features/overview/ReturnChart";
import { PairStatsTable } from "@/features/strategies/PairStatsTable";
import { usePublicRecord } from "@/shared/api/public-record";
import type { Excluded, PublicRecord } from "@/shared/api/types";
import { ReportSection } from "@/shared/ui/ReportSection";

/** A record leaves nothing out that it could count: it has no open trades, rehearsals or unconverted fees to name. */
const NOTHING_EXCLUDED: Excluded = {
  open_trade_count: 0,
  rehearsal_fill_count: 0,
  no_capital_at_open: 0,
  unconverted_fee: 0,
  unresolved_allocation_count: 0,
};

interface PublicRecordReportProps {
  strategyId: string;
  /** The UTC day (`YYYY-MM-DD`) the reader's seat began, marked on the curve; null for a reader with no seat. */
  joined: string | null;
}

/** `YYYY-MM-DD` as a short date in the reader's language, read in UTC like every day of the record. */
function dayText(date: string, locale: string): string {
  const [year, month, day] = date.split("-").map(Number);
  const instant = new Date(Date.UTC(year ?? Number.NaN, (month ?? Number.NaN) - 1, day ?? Number.NaN));
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(instant);
}

function RecordView({ record, asOf, joined }: { record: PublicRecord; asOf: number; joined: string | null }) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";
  const range = useRangeStore((state) => state.range);
  const setRange = useRangeStore((state) => state.setRange);

  return (
    <>
      <div className="flex min-w-0 flex-col gap-3">
        <ReportSection>
          <ReturnChart
            curve={record.curve}
            origin={record.origin}
            range={range}
            asOf={asOf}
            title={t("strategies.report.recordChartTitle")}
            headerAction={<RangeSelector value={range} onChange={setRange} />}
            marker={joined === null ? null : { date: joined, label: t("strategies.report.joined", { date: dayText(joined, locale) }) }}
          />
        </ReportSection>
      </div>
      <ReportSection>
        <div className="flex flex-col gap-1.5">
          <MonthlyGrid monthly={record.monthly} />
          <MonthlySummary monthly={record.monthly} excluded={NOTHING_EXCLUDED} />
        </div>
      </ReportSection>
      <PairStatsTable pairs={record.by_pair} />
    </>
  );
}

/**
 * The strategy's record for anyone (I.12a): the author's real fills since the start, as a curve, months and
 * pairs, with no money in it. A reader with a seat sees the day it began marked on the curve. It is never drawn
 * together with the reader's own results: those are another capital, share and leverage.
 */
export function PublicRecordReport({ strategyId, joined }: PublicRecordReportProps) {
  const { t } = useTranslation();
  const query = usePublicRecord(strategyId);

  if (query.status === "pending") {
    return (
      <p role="status" className="text-sm text-ink-3">
        {t("strategies.report.recordLoading")}
      </p>
    );
  }
  if (query.status === "error") {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-loss bg-panel p-4">
        <p role="alert" className="text-sm text-ink-2">
          {t("strategies.report.recordError")}
        </p>
        <button
          type="button"
          onClick={() => void query.refetch()}
          className="min-h-11 rounded-md border border-rule px-3.5 text-sm text-ink hover:bg-panel-2"
        >
          {t("strategies.performance.retry")}
        </button>
      </div>
    );
  }
  if (query.data === null) {
    return (
      <p role="status" className="text-sm text-ink-3">
        {t("strategies.report.recordGone")}
      </p>
    );
  }
  if (query.data.closed_trade_count === 0) {
    return (
      <p role="status" className="text-sm text-ink-3">
        {t("strategies.report.recordEmpty")}
      </p>
    );
  }
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <RecordView record={query.data} asOf={query.dataUpdatedAt} joined={joined} />
    </div>
  );
}
