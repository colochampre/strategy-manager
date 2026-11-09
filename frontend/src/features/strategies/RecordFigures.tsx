import { useTranslation } from "react-i18next";

import { rangeLabel } from "@/features/overview/LedgerLine";
import { useRangeStore } from "@/features/overview/range-store";
import { publicFigures } from "@/features/strategies/card-figures";
import { CardFigureGrid } from "@/features/strategies/StrategyCard";
import type { CardPnl } from "@/features/strategies/StrategyCard";
import { useStrategyPerformance } from "@/shared/api/performance";
import { usePublicRecord } from "@/shared/api/public-record";
import type { PublicStrategy } from "@/shared/api/types";
import { parseDecimal } from "@/shared/lib/amount-text";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";

/** Hidden between the widths that hold one row of eight figures (32rem) and one of nine (40rem). */
const PNL_WHERE_IT_FITS = "@[32rem]:hidden @[40rem]:flex";

/** Which report the row's return and drawdown are read from: the strategy's record, the reader's own, or not yet known. */
export type FiguresView = "record" | "mine" | null;

interface RowProps {
  strategy: PublicStrategy;
  ret: number | null | undefined;
  deepest: number | null | undefined;
  returnLabel: string;
  /** Whether the return's (i) is drawn: it explains the record's return, not the reader's own. */
  recordReturn: boolean;
  pnl?: CardPnl;
}

function Row({ strategy, ret, deepest, returnLabel, recordReturn, pnl }: RowProps) {
  const { t } = useTranslation();
  const returnInfo = useInfoDisclosure();
  const capitalInfo = useInfoDisclosure();

  return (
    <div className="@container flex flex-col gap-2">
      <CardFigureGrid
        testId="record-line"
        layout="page"
        prefix="public"
        since={strategy.created_at}
        sinceKind="age"
        uptime={strategy.uptime}
        figures={{ ...publicFigures(strategy), ret, deepest }}
        pnl={pnl}
        returnLabel={returnLabel}
        returnInfo={
          recordReturn ? <InfoButton disclosure={returnInfo} label={t("strategies.public.returnInfo")} /> : undefined
        }
        capitalInfo={<InfoButton disclosure={capitalInfo} label={t("strategies.public.capitalInfo")} />}
      />
      {recordReturn && (
        <InfoText disclosure={returnInfo}>
          <p className="text-xs text-ink-3">{t("strategies.public.returnHint")}</p>
        </InfoText>
      )}
      <InfoText disclosure={capitalInfo}>
        <p className="text-xs text-ink-3">{t("strategies.public.capitalHint")}</p>
      </InfoText>
    </div>
  );
}

/** The record's return and deepest fall, over the chart's range; a dash with no closed trade, "…" while it is read. */
function FromRecord({ strategy, pending }: { strategy: PublicStrategy; pending: boolean }) {
  const { t } = useTranslation();
  const range = useRangeStore((state) => state.range);
  const record = usePublicRecord(strategy.id, !pending);

  const data = pending || record.status === "pending" ? undefined : record.status === "success" ? record.data : null;
  const traded = data !== undefined && data !== null && data.closed_trade_count > 0;
  const summary = traded ? data.ranges.find((entry) => entry.range === range) : undefined;
  return (
    <Row
      strategy={strategy}
      ret={data === undefined ? undefined : summary === undefined ? null : parseDecimal(summary.return)}
      deepest={data === undefined ? undefined : traded ? parseDecimal(data.max_drawdown) : null}
      returnLabel={rangeLabel(t, "strategies.report.recordReturn", range)}
      recordReturn
    />
  );
}

/**
 * The reader's own PnL, return and drawdown in the strategy, over the chart's range, as their report names them: the
 * return is their contribution to their pool. A dash where they have no closed trade.
 */
function FromMine({ strategy }: { strategy: PublicStrategy }) {
  const { t } = useTranslation();
  const range = useRangeStore((state) => state.range);
  const own = useStrategyPerformance(strategy.id);

  const report = own.status === "pending" ? undefined : own.status === "success" ? own.data : null;
  const traded = report !== undefined && report !== null && report.trade_count > 0;
  const summary = traded ? report.ranges.find((entry) => entry.range === range) : undefined;
  const known = (read: () => number | null) => (report === undefined ? undefined : summary === undefined ? null : read());
  return (
    <Row
      strategy={strategy}
      ret={known(() => (summary?.return == null ? null : parseDecimal(summary.return)))}
      deepest={known(() => (traded ? parseDecimal(report.max_drawdown) : null))}
      returnLabel={rangeLabel(t, "strategies.performance.contribution", range)}
      recordReturn={false}
      pnl={{
        value: known(() => (summary === undefined ? null : parseDecimal(summary.pnl))),
        currency: strategy.settlement_currency,
        label: rangeLabel(t, "overview.ledger.pnl", range),
        // A ninth figure: where the column holds one row of eight but not of nine, the row stays one and the PnL
        // goes (the owner's word); on a phone, four a row, it has its place.
        className: PNL_WHERE_IT_FITS,
      }}
    />
  );
}

/**
 * Another author's strategy in one row, as its card draws it, at the top of Performance: age, days active, closed
 * trades, return, deepest fall, win rate, live subscribers and capital. The return and the fall follow the chart's
 * range: the record's under the strategy's record, the reader's own under My results, with their PnL left of the
 * return. Until the view is known they wait ("…"), so a subscriber never sees the record's for a moment.
 */
export function RecordFigures({ strategy, view }: { strategy: PublicStrategy; view: FiguresView }) {
  if (view === "mine") return <FromMine strategy={strategy} />;
  return <FromRecord strategy={strategy} pending={view === null} />;
}
