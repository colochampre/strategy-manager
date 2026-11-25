import { Users } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useRangeStore } from "@/features/overview/range-store";
import type { RangeName } from "@/features/overview/RangeSelector";
import { publicFigures } from "@/features/strategies/card-figures";
import { NamedValue } from "@/features/strategies/StrategyCard";
import type { CardFigures, CardPnl } from "@/features/strategies/StrategyCard";
import { SecondLine, StatsRow, StatTile, StatUnit } from "@/features/strategies/StrategyHeaderCard";
import { useStrategyPerformance } from "@/shared/api/performance";
import { usePublicRecord } from "@/shared/api/public-record";
import type { PublicStrategy, Strategy, StrategyPerformance } from "@/shared/api/types";
import { amountText, parseDecimal, percentText, toneClass } from "@/shared/lib/amount-text";
import { Masked } from "@/shared/hidden/Masked";
import { InfoTip } from "@/shared/ui/Tooltip";

/** What a figure shows where there is nothing true to say yet, and while its report is on its way. */
const NO_FIGURE = "—";
const LOADING = "…";

/** Which report the row's return and drawdown are read from: the strategy's record, the reader's own, or not yet known. */
export type FiguresView = "record" | "mine" | null;

interface RowProps {
  prefix: string;
  testId: string;
  figures: CardFigures;
  pnl?: CardPnl;
  /** Whether the return's (i) is drawn: it explains the record's return, not a report's own. */
  recordReturn: boolean;
  /** The pool's settlement currency, the one every money figure of the row is in (rule 7). */
  currency: string;
}

/** A tip beside a label, as tall as the label's own line so a figure's row never grows for it. */
function LabelTip({ label, text }: { label: string; text: string }) {
  return (
    <span className="-my-1 inline-flex">
      <InfoTip label={label} text={text} />
    </span>
  );
}

/** Money as a lead figure: stars while the balances are hidden, with its currency beside it; "…" or "—" where none. */
function leadMoney(amount: number | null | undefined, currency: string, locale: string, signed: boolean): ReactNode {
  if (amount === undefined) return LOADING;
  if (amount === null) return NO_FIGURE;
  return (
    <>
      <Masked>{amountText(amount, currency, locale, signed)}</Masked>
      <StatUnit currency={currency} />
    </>
  );
}

/**
 * A signed ratio as a lead figure, the way the dashboard's header card writes one (`+3.8%`, the same size as the
 * figure), with its tone; "…" or "—" where there is none.
 */
function leadPercent(ratio: number | null | undefined, locale: string): { value: string; tone: string | undefined } {
  if (ratio === undefined) return { value: LOADING, tone: undefined };
  if (ratio === null) return { value: NO_FIGURE, tone: undefined };
  return { value: percentText(ratio, locale), tone: toneClass(ratio) };
}

/** The win rate, unsigned: whole when it is whole and one decimal otherwise. */
function leadRate(value: number | null | undefined, locale: string): string {
  if (value === undefined) return LOADING;
  if (value === null) return NO_FIGURE;
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(value);
}

/**
 * The figures as the dashboard's header card draws its row (ex11, ex12): Total PnL named by the chart's range, Max
 * drawdown, Win rate with its trades, and AuM with its currency and its live subscribers. Where there is a PnL it
 * leads and the return sits under it; where there is none (a record holds no money) the return leads. The money is
 * masked while the balances are hidden; the percentages and the counts are not (S1).
 */
function Row({ prefix, testId, figures, pnl, recordReturn, currency }: RowProps) {
  const { t, i18n } = useTranslation();
  const locale = i18n.resolvedLanguage ?? "en";
  const range = useRangeStore((state) => state.range);
  const ret = leadPercent(figures.ret, locale);
  const deepest = leadPercent(figures.deepest, locale);
  const subscribers = figures.subscribers;
  const capital = figures.capital;

  return (
    <StatsRow testId={testId}>
      <StatTile
        testId={`${prefix}-group-pnl`}
        position={0}
        // The range as its button names it ("30D"): the long form wrapped beside an (i) and pushed the chart down.
        label={
          range === "All"
            ? t("strategies.card.totalPnl")
            : t("strategies.card.totalPnlRange", { range: t(`overview.range.${range}`) })
        }
        info={
          recordReturn ? (
            <LabelTip label={t("strategies.public.returnInfo")} text={t("strategies.public.returnHint")} />
          ) : undefined
        }
      >
        {pnl === undefined ? (
          <span data-testid={`${prefix}-return`} className={ret.tone}>
            {ret.value}
          </span>
        ) : (
          <>
            <span
              data-testid={`${prefix}-pnl`}
              className={pnl.value === undefined || pnl.value === null ? undefined : toneClass(pnl.value)}
            >
              {leadMoney(pnl.value, pnl.currency, locale, true)}
            </span>
            <SecondLine testId={`${prefix}-return`} className={ret.tone}>
              {ret.value}
            </SecondLine>
          </>
        )}
      </StatTile>
      <StatTile testId={`${prefix}-group-drawdown`} position={1} label={t("strategies.card.maxDrawdown")}>
        <span data-testid={`${prefix}-deepest`} className={deepest.tone}>
          {deepest.value}
        </span>
      </StatTile>
      <StatTile testId={`${prefix}-group-profitable`} position={2} label={t("strategies.card.winRate")}>
        <span data-testid={`${prefix}-winrate`}>{leadRate(figures.winRate, locale)}</span>
        {figures.profitable !== undefined && figures.profitable !== null && (
          <SecondLine testId={`${prefix}-wins`}>
            {t("strategies.header.wins", { wins: figures.profitable.wins, closed: figures.profitable.closed })}
          </SecondLine>
        )}
      </StatTile>
      <StatTile
        testId={`${prefix}-group-aum`}
        position={3}
        label={t("strategies.card.aum")}
        info={<LabelTip label={t("strategies.public.capitalInfo")} text={t("strategies.public.capitalHint")} />}
      >
        <span data-testid={`${prefix}-capital`}>
          {capital === undefined ? LOADING : capital === null ? NO_FIGURE : <Masked>{amountText(capital.amount, currency, locale)}</Masked>}
        </span>
        <SecondLine>
          {currency}
          {" · "}
          <NamedValue icon={Users} label={t("strategies.card.subscribers")} testId={`${prefix}-subscribers`}>
            {subscribers === undefined ? LOADING : subscribers === null ? NO_FIGURE : String(subscribers)}
          </NamedValue>
        </SecondLine>
      </StatTile>
    </StatsRow>
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
      currency={strategy.settlement_currency}
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
      currency={strategy.settlement_currency}
    />
  );
}

/**
 * Another author's strategy in the header card's row of figures: Total PnL, Max drawdown, Win rate and AuM. The return and the fall follow the chart's range: the record's under the strategy's
 * record, the reader's own under My results, with their PnL and their wins. Until the view is known they wait ("…"),
 * so a subscriber never sees the record's for a moment.
 */
export function RecordFigures({ strategy, view }: { strategy: PublicStrategy; view: FiguresView }) {
  if (view === "mine") return <FromMine strategy={strategy} />;
  return <FromRecord strategy={strategy} pending={view === null} />;
}

/**
 * The author's own strategy in the header card's row of figures, as another author's page draws its own (owner,
 * 2026-11-17): the author's report over the chart's range, and the strategy's live subscribers and capital.
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
      currency={strategy.settlement_currency}
    />
  );
}
