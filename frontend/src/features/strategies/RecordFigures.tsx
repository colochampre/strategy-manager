import { useTranslation } from "react-i18next";

import { useRangeStore } from "@/features/overview/range-store";
import type { RangeName } from "@/features/overview/RangeSelector";
import { publicFigures } from "@/features/strategies/card-figures";
import { FigureGroups } from "@/features/strategies/StrategyCard";
import type { CardFigures, CardPnl } from "@/features/strategies/StrategyCard";
import { useStrategyPerformance } from "@/shared/api/performance";
import { usePublicRecord } from "@/shared/api/public-record";
import type { PublicStrategy, Strategy, StrategyPerformance } from "@/shared/api/types";
import { parseDecimal } from "@/shared/lib/amount-text";
import { InfoButton, InfoText, useInfoDisclosure } from "@/shared/ui/InfoDisclosure";

/** Which report the row's return and drawdown are read from: the strategy's record, the reader's own, or not yet known. */
export type FiguresView = "record" | "mine" | null;

interface RowProps {
  prefix: string;
  testId: string;
  figures: CardFigures;
  pnl?: CardPnl;
  /** Whether the return's (i) is drawn: it explains the record's return, not a report's own. */
  recordReturn: boolean;
}

/** The figures in the cards' groups, the Total PnL named by the chart's range, the capital explained on request. */
function Row({ prefix, testId, figures, pnl, recordReturn }: RowProps) {
  const { t } = useTranslation();
  const range = useRangeStore((state) => state.range);
  const returnInfo = useInfoDisclosure();
  const capitalInfo = useInfoDisclosure();

  return (
    <div className="flex flex-col gap-2">
      <FigureGroups
        testId={testId}
        prefix={prefix}
        figures={figures}
        pnl={pnl}
        // The range as its button names it ("30D"): the long form wrapped beside an (i) and pushed the chart down.
        pnlLabel={
          range === "All"
            ? t("strategies.card.totalPnl")
            : t("strategies.card.totalPnlRange", { range: t(`overview.range.${range}`) })
        }
        pnlInfo={
          recordReturn ? <InfoButton disclosure={returnInfo} label={t("strategies.public.returnInfo")} /> : undefined
        }
        aumInfo={<InfoButton disclosure={capitalInfo} label={t("strategies.public.capitalInfo")} />}
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

/** What a row reads of a report of the reader's own: its PnL and return over the range, its deepest fall and its wins. */
interface OwnFigures {
  figures: Pick<CardFigures, "trades" | "ret" | "deepest" | "winRate" | "profitable">;
  pnl: number | null | undefined;
}

/**
 * A report of the reader's own over the chart's range: `undefined` while it is read, a dash where there is no closed
 * trade or no report. The win rate is every pair's wins over every pair's closed trades, as on the cards.
 */
function ownFigures(status: "pending" | "error" | "success", data: StrategyPerformance | null | undefined, range: RangeName): OwnFigures {
  if (status === "pending" || (status === "success" && data === undefined)) {
    return { figures: { trades: undefined, ret: undefined, deepest: undefined, winRate: undefined, profitable: undefined }, pnl: undefined };
  }
  const report = status === "success" ? data : null;
  if (report === null || report === undefined || report.trade_count === 0) {
    return { figures: { trades: report?.trade_count ?? null, ret: null, deepest: null, winRate: null, profitable: null }, pnl: null };
  }
  const summary = report.ranges.find((entry) => entry.range === range);
  const closed = report.by_pair.reduce((sum, pair) => sum + pair.trades, 0);
  const wins = report.by_pair.reduce((sum, pair) => sum + pair.wins, 0);
  return {
    figures: {
      trades: report.trade_count,
      ret: summary?.return == null ? null : parseDecimal(summary.return),
      deepest: parseDecimal(report.max_drawdown),
      winRate: closed === 0 ? null : wins / closed,
      profitable: closed === 0 ? null : { wins, closed },
    },
    pnl: summary === undefined ? null : parseDecimal(summary.pnl),
  };
}

/** The record's return and deepest fall, over the chart's range; a dash with no closed trade, "…" while it is read. */
function FromRecord({ strategy, pending }: { strategy: PublicStrategy; pending: boolean }) {
  const range = useRangeStore((state) => state.range);
  const record = usePublicRecord(strategy.id, !pending);

  const data = pending || record.status === "pending" ? undefined : record.status === "success" ? record.data : null;
  const traded = data !== undefined && data !== null && data.closed_trade_count > 0;
  const summary = traded ? data.ranges.find((entry) => entry.range === range) : undefined;
  return (
    <Row
      prefix="public"
      testId="record-line"
      figures={{
        ...publicFigures(strategy),
        ret: data === undefined ? undefined : summary === undefined ? null : parseDecimal(summary.return),
        deepest: data === undefined ? undefined : traded ? parseDecimal(data.max_drawdown) : null,
      }}
      recordReturn
    />
  );
}

/**
 * The reader's own PnL, return, drawdown and wins in the strategy, over the chart's range, as their report names them:
 * the return is their contribution to their pool. Who trades it live and with how much are the public list's.
 */
function FromMine({ strategy }: { strategy: PublicStrategy }) {
  const range = useRangeStore((state) => state.range);
  const own = useStrategyPerformance(strategy.id);
  const mine = ownFigures(own.status, own.data, range);
  return (
    <Row
      prefix="public"
      testId="record-line"
      figures={{ ...publicFigures(strategy), ...mine.figures }}
      pnl={{ value: mine.pnl, currency: strategy.settlement_currency }}
      recordReturn={false}
    />
  );
}

/**
 * Another author's strategy at the top of Performance, grouped as its card groups it: Total PnL, Max drawdown,
 * Profitable trades and AuM. The return and the fall follow the chart's range: the record's under the strategy's
 * record, the reader's own under My results, with their PnL and their wins. Until the view is known they wait ("…"),
 * so a subscriber never sees the record's for a moment.
 */
export function RecordFigures({ strategy, view }: { strategy: PublicStrategy; view: FiguresView }) {
  if (view === "mine") return <FromMine strategy={strategy} />;
  return <FromRecord strategy={strategy} pending={view === null} />;
}

/**
 * The author's own strategy at the top of Performance, as another author's page draws its own (owner, 2026-11-17):
 * the author's report over the chart's range, and the strategy's live subscribers and capital.
 */
export function AuthorFigures({ strategy }: { strategy: Strategy }) {
  const range = useRangeStore((state) => state.range);
  const own = useStrategyPerformance(strategy.id);
  const mine = ownFigures(own.status, own.data, range);
  const capital = strategy.capital === null ? null : parseDecimal(strategy.capital);
  return (
    <Row
      prefix="strategy"
      testId="figure-line"
      figures={{
        ...mine.figures,
        subscribers: strategy.live_subscribers,
        capital: capital === null ? null : { amount: capital, currency: strategy.settlement_currency },
      }}
      pnl={{ value: mine.pnl, currency: strategy.settlement_currency }}
      recordReturn={false}
    />
  );
}
