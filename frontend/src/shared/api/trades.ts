import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";

/** Operations a page of My trades holds (RD.4). */
export const MY_TRADES_PAGE_SIZE = 20;

export type CloseCause = "SIGNAL" | "STOP_FIRED" | "STOP_FAILED_CLOSED" | "STRATEGY_STOPPED_CLOSED" | "MANUAL_CLOSE";

const CLOSE_CAUSES: readonly string[] = [
  "SIGNAL",
  "STOP_FIRED",
  "STOP_FAILED_CLOSED",
  "STRATEGY_STOPPED_CLOSED",
  "MANUAL_CLOSE",
];

/** One closed operation of `GET /performance/trades`; every figure is in the row's own `currency` (rule 7). */
export interface MyTrade {
  allocation_id: string;
  strategy_id: string;
  strategy_name: string;
  strategy_archived: boolean;
  /** Which page of the strategy this user can open: their own detail, its public page, or none. */
  strategy_page: "AUTHORED" | "LISTED" | null;
  exchange: string;
  venue: string;
  currency: string;
  pair: string;
  direction: "LONG" | "SHORT";
  opened_at: string;
  closed_at: string;
  rehearsal: boolean;
  entry_price: string | null;
  exit_price: string | null;
  pnl: string | null;
  fees_complete: boolean;
  close_cause: CloseCause;
}

export interface TradeStrategyChoice {
  id: string;
  name: string;
  archived: boolean;
}

export interface MyTradesPage {
  trades: MyTrade[];
  /** Every closed operation that passes the filters, before the page is cut. */
  total: number;
  /** What the user's closed operations hold with no filter applied, so the choices do not shrink as filters narrow. */
  strategies: TradeStrategyChoice[];
  exchanges: string[];
}

export interface TradesQuery {
  limit: number;
  offset: number;
  /** An ISO instant with an offset; null asks for every close. */
  closedSince: string | null;
  strategyId: string | null;
  exchange: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isText(value: unknown): value is string {
  return typeof value === "string";
}

function isTextOrNull(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isTrade(value: unknown): value is MyTrade {
  return (
    isRecord(value) &&
    isText(value.allocation_id) &&
    isText(value.strategy_id) &&
    isText(value.strategy_name) &&
    typeof value.strategy_archived === "boolean" &&
    (value.strategy_page === null || value.strategy_page === "AUTHORED" || value.strategy_page === "LISTED") &&
    isText(value.exchange) &&
    isText(value.venue) &&
    isText(value.currency) &&
    isText(value.pair) &&
    (value.direction === "LONG" || value.direction === "SHORT") &&
    isText(value.opened_at) &&
    isText(value.closed_at) &&
    typeof value.rehearsal === "boolean" &&
    isTextOrNull(value.entry_price) &&
    isTextOrNull(value.exit_price) &&
    isTextOrNull(value.pnl) &&
    typeof value.fees_complete === "boolean" &&
    isText(value.close_cause) &&
    CLOSE_CAUSES.includes(value.close_cause)
  );
}

function isChoice(value: unknown): value is TradeStrategyChoice {
  return isRecord(value) && isText(value.id) && isText(value.name) && typeof value.archived === "boolean";
}

function isTradesPage(value: unknown): value is MyTradesPage {
  return (
    isRecord(value) &&
    Array.isArray(value.trades) &&
    value.trades.every(isTrade) &&
    typeof value.total === "number" &&
    Array.isArray(value.strategies) &&
    value.strategies.every(isChoice) &&
    Array.isArray(value.exchanges) &&
    value.exchanges.every(isText)
  );
}

/**
 * `GET /api/performance/trades`: the signed-in user's closed operations across every pool, newest close first. A
 * filter that is not set is not sent. A body that is not a page throws, because an empty list would read as "no
 * trades" for a read that simply failed.
 */
export async function fetchMyTrades(query: TradesQuery): Promise<MyTradesPage> {
  const params = new URLSearchParams({ limit: String(query.limit), offset: String(query.offset) });
  if (query.closedSince !== null) params.set("closed_since", query.closedSince);
  if (query.strategyId !== null) params.set("strategy_id", query.strategyId);
  if (query.exchange !== null) params.set("exchange", query.exchange);
  const body = await apiFetch<unknown>(`/performance/trades?${params}`);
  if (!isTradesPage(body)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /performance/trades: expected a page of trades",
    });
  }
  return body;
}

export function myTradesKey(query: TradesQuery) {
  return ["performance", "trades", query.limit, query.offset, query.closedSince, query.strategyId, query.exchange] as const;
}

const MY_TRADES_STALE_MS = 60_000;

/** The previous answer stays while the next page or filter loads, so the filters' choices do not vanish meanwhile. */
export function useMyTrades(query: TradesQuery, enabled = true) {
  return useQuery({
    queryKey: myTradesKey(query),
    queryFn: () => fetchMyTrades(query),
    enabled,
    staleTime: MY_TRADES_STALE_MS,
    placeholderData: keepPreviousData,
  });
}
