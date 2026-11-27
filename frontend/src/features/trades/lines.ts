import { strategyHref } from "@/features/positions/strategyHref";
import type { OpenPosition } from "@/shared/api/positions";
import type { MyTrade, TradeStrategyChoice } from "@/shared/api/trades";

/** One row of My trades: an operation still open, from the positions read, or a closed one, from the trades read. */
export type TradeLine =
  | { kind: "open"; key: string; position: OpenPosition }
  | { kind: "closed"; key: string; trade: MyTrade };

export function strategyOf(line: TradeLine): { name: string; href: string | null } {
  if (line.kind === "open") {
    const { strategy_id: id, strategy_name: name, strategy_page: page } = line.position;
    return { name, href: strategyHref(id, page) };
  }
  const { strategy_id: id, strategy_name: name, strategy_page: page } = line.trade;
  return { name, href: strategyHref(id, page) };
}

export function currencyOf(line: TradeLine): string {
  return line.kind === "open" ? line.position.currency : line.trade.currency;
}

export function exchangeOf(line: TradeLine): string {
  return line.kind === "open" ? line.position.pool.exchange : line.trade.exchange;
}

export function openedAtOf(line: TradeLine): string | null {
  return line.kind === "open" ? line.position.opened_at : line.trade.opened_at;
}

export function sideOf(line: TradeLine): "LONG" | "SHORT" | null {
  return line.kind === "open" ? line.position.side : line.trade.direction;
}

/** The pair as the venue's markets name it: an open position may hold several. */
export function pairOf(line: TradeLine): string {
  return line.kind === "open" ? line.position.markets.join(" / ") : line.trade.pair;
}

/**
 * The open operations of this user that pass the Strategy and Exchange filters, newest opening first (L55). The
 * period is not applied: an open operation is now. One whose opening instant is unknown goes last.
 */
export function openLinesOf(positions: readonly OpenPosition[], strategyId: string, exchange: string): TradeLine[] {
  return positions
    .filter((position) => strategyId === "" || position.strategy_id === strategyId)
    .filter((position) => exchange === "" || position.pool.exchange === exchange)
    .map((position): TradeLine => ({ kind: "open", key: `open-${position.allocation_id}`, position }))
    .sort((a, b) => {
      const left = Date.parse(openedAtOf(a) ?? "");
      const right = Date.parse(openedAtOf(b) ?? "");
      return (Number.isNaN(right) ? -Infinity : right) - (Number.isNaN(left) ? -Infinity : left) || 0;
    });
}

export function closedLinesOf(trades: readonly MyTrade[]): TradeLine[] {
  return trades.map((trade): TradeLine => ({ kind: "closed", key: `closed-${trade.allocation_id}`, trade }));
}

/** The strategies to choose from: the ones the server holds closed operations of, and those with one open now. */
export function strategyChoices(
  served: readonly TradeStrategyChoice[],
  positions: readonly OpenPosition[],
): TradeStrategyChoice[] {
  const byId = new Map<string, TradeStrategyChoice>(served.map((choice) => [choice.id, choice]));
  for (const position of positions) {
    if (position.strategy_id !== null && !byId.has(position.strategy_id)) {
      byId.set(position.strategy_id, {
        id: position.strategy_id,
        name: position.strategy_name,
        archived: position.strategy_archived === true,
      });
    }
  }
  return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name));
}

/** The exchanges to choose from, by id: the server's and those of the open positions. */
export function exchangeChoices(served: readonly string[], positions: readonly OpenPosition[]): string[] {
  return [...new Set([...served, ...positions.map((position) => position.pool.exchange)])];
}
