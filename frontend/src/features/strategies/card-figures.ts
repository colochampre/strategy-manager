import type { CardFigures } from "@/features/strategies/StrategyCard";
import type { SortKey } from "@/features/strategies/card-sort";
import type { PublicStrategy, Strategy, StrategyPerformance } from "@/shared/api/types";
import { parseDecimal } from "@/shared/lib/amount-text";

/** What a card shows of a strategy that has no public record to read: a seat on one that is off the public list. */
export const NO_PUBLIC_FIGURES: CardFigures = {
  trades: null,
  ret: null,
  deepest: null,
  winRate: null,
  profitable: null,
  subscribers: null,
  capital: null,
};

/**
 * A strategy's public record as a card draws it. A return, a deepest fall and a win rate are claimed only once a
 * real trade of the author's has closed (decisions 28 and 34); until then they are absent, and the card shows a dash.
 */
export function publicFigures(strategy: PublicStrategy): CardFigures {
  const traded = strategy.closed_trade_count > 0;
  const capital = strategy.capital === null ? null : parseDecimal(strategy.capital);
  const winRate = strategy.win_rate === null ? null : parseDecimal(strategy.win_rate);
  const closed = strategy.closed_trade_count;
  return {
    trades: closed,
    ret: traded ? parseDecimal(strategy.unleveraged_return_before_fees) : null,
    deepest: traded ? parseDecimal(strategy.max_drawdown) : null,
    winRate,
    // The public record serves the rate, not the count: the count is the rate of the closed trades, which it was.
    profitable: winRate === null || closed === 0 ? null : { wins: Math.round(winRate * closed), closed },
    subscribers: strategy.live_subscribers,
    capital: capital === null ? null : { amount: capital, currency: strategy.settlement_currency },
  };
}

/**
 * How old, as a number a list can order by: the older the instant, the larger, so "age, descending" puts the oldest
 * first. An instant that cannot be read has no age.
 */
export function ageOrder(since: string | null): number | null {
  if (since === null) return null;
  const from = Date.parse(since);
  return Number.isNaN(from) ? null : -from;
}

/**
 * The figure a sort key reads off a card: the very number the card shows, so the list is in the order its figures
 * read. A figure the card shows as "…" or "—" is none.
 */
export function sortFigure(figures: CardFigures, age: number | null, key: SortKey): number | null {
  switch (key) {
    case "age":
      return age;
    case "trades":
      return figures.trades ?? null;
    case "return":
      return figures.ret ?? null;
    case "subscribers":
      return figures.subscribers ?? null;
    case "capital":
      return figures.capital?.amount ?? null;
  }
}

/** What a card needs of the author's own report: its status and the body it answered. */
export interface ReportRead {
  status: "pending" | "error" | "success";
  data: StrategyPerformance | null | undefined;
}

/**
 * The all-time PnL of a report the reader reads of their own: `undefined` while it is read, `null` where there is
 * none (no report, a failed read, a figure nobody can read).
 */
export function allTimePnl(read: ReportRead): number | null | undefined {
  if (read.status === "pending" || (read.status === "success" && read.data === undefined)) return undefined;
  if (read.status === "error" || read.data === null || read.data === undefined) return null;
  const all = read.data.ranges.find((entry) => entry.range === "All");
  return all === undefined ? null : parseDecimal(all.pnl);
}

/** The author's strategy as a card draws it, with its PnL (the one figure only this card has). */
export interface AuthoredCard {
  figures: CardFigures;
  /** `undefined` while reading, `null` where there is none. */
  pnl: number | null | undefined;
  /** The report failed, or came back with figures nobody can read: the card says so once. */
  failed: boolean;
}

/** The figures a card takes from somewhere other than a report: who trades it live, and with how much. */
type AumFigures = Pick<CardFigures, "subscribers" | "capital">;

const NO_RECORD = { trades: null, ret: null, deepest: null, winRate: null, profitable: null } as const;

/**
 * The card a report draws, with its live subscribers and capital beside it. Return, closed trades, deepest, win rate
 * and PnL come from the one report, in its pool's currency: the return is the strategy's contribution to the pool. A
 * win rate is every pair's wins over every pair's closed trades, and none before a trade has closed.
 */
function reportFigures(read: ReportRead, aum: AumFigures): AuthoredCard {
  if (read.status === "error") return { figures: { ...aum, ...NO_RECORD }, pnl: null, failed: true };
  if (read.status === "pending" || read.data === undefined) {
    return {
      figures: { ...aum, trades: undefined, ret: undefined, deepest: undefined, winRate: undefined, profitable: undefined },
      pnl: undefined,
      failed: false,
    };
  }
  const report = read.data;
  if (report === null) return { figures: { ...aum, ...NO_RECORD }, pnl: null, failed: false };
  const all = report.ranges.find((entry) => entry.range === "All");
  const pnl = all === undefined ? null : parseDecimal(all.pnl);
  const ret = all === undefined ? null : parseDecimal(all.return);
  if (all !== undefined && (pnl === null || ret === null)) return { figures: { ...aum, ...NO_RECORD }, pnl: null, failed: true };
  const closed = report.by_pair.reduce((sum, pair) => sum + pair.trades, 0);
  const wins = report.by_pair.reduce((sum, pair) => sum + pair.wins, 0);
  return {
    figures: {
      ...aum,
      trades: report.trade_count,
      ret,
      deepest: parseDecimal(report.max_drawdown),
      winRate: closed === 0 ? null : wins / closed,
      profitable: closed === 0 ? null : { wins, closed },
    },
    pnl,
    failed: false,
  };
}

/** An author's strategy as a card draws it: the author's own report, and the strategy's live subscribers and capital. */
export function authoredFigures(strategy: Strategy, read: ReportRead): AuthoredCard {
  const capital = strategy.capital === null ? null : parseDecimal(strategy.capital);
  return reportFigures(read, {
    subscribers: strategy.live_subscribers,
    capital: capital === null ? null : { amount: capital, currency: strategy.settlement_currency },
  });
}

/**
 * A seat as its card draws it (owner, 2026-11-17): the record is the reader's own, from their report in the
 * strategy, so the PnL and the return beside it speak of the same money; who trades it live and with how much come
 * from the public list (`aum`, the dash where the strategy is off it, the ellipsis while it is read).
 */
export function seatFigures(read: ReportRead, aum: AumFigures): AuthoredCard {
  return reportFigures(read, aum);
}
