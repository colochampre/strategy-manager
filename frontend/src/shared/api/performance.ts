import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";
import type {
  OperationFill,
  OperationFills,
  PoolPerformance,
  StrategyPerformance,
  StrategyTrade,
  StrategyTradesPage,
  TradeCursor,
} from "@/shared/api/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The shape the panel reads, checked one level deep. A body that is not a
 * report must read as an error: treating it as an empty ledger would show
 * "No closed trades yet" for a pool whose data simply failed to arrive.
 */
function isPoolPerformance(value: unknown): value is PoolPerformance {
  if (!isRecord(value)) return false;
  return (
    typeof value.currency === "string" &&
    typeof value.total_pnl === "string" &&
    typeof value.max_drawdown === "string" &&
    isRecord(value.excluded) &&
    Array.isArray(value.ranges) &&
    Array.isArray(value.curve) &&
    Array.isArray(value.monthly)
  );
}

/**
 * `GET /api/performance/pools/{exchange}/{venue}/{ccy}`. A 404 ("no such pool")
 * resolves to `null`: the pool list named this pool a moment ago, so it is a
 * pool without a report, not a failure. Every other non-2xx status throws.
 */
export async function fetchPoolPerformance(
  exchange: string,
  venue: string,
  currency: string,
): Promise<PoolPerformance | null> {
  const path = [exchange, venue, currency].map(encodeURIComponent).join("/");
  let body: unknown;
  try {
    body = await apiFetch<unknown>(`/performance/pools/${path}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
  if (!isPoolPerformance(body)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /performance/pools: expected a pool report",
    });
  }
  return body;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isPairStat(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.pair === "string" &&
    typeof value.trades === "number" &&
    typeof value.pnl === "string" &&
    isNullableString(value.return)
  );
}

/** A pool report plus a `by_pair` list whose every entry is readable: one bad entry fails the lot, so no row shows a wrong figure. */
function isStrategyPerformance(value: unknown): value is StrategyPerformance {
  return (
    isPoolPerformance(value) &&
    typeof (value as { strategy_id?: unknown }).strategy_id === "string" &&
    Array.isArray((value as { by_pair?: unknown }).by_pair) &&
    (value as unknown as { by_pair: unknown[] }).by_pair.every(isPairStat)
  );
}

/**
 * `GET /api/performance/strategies/{id}`. As for a pool, a 404 is a strategy
 * without a report (null) and any other failure, or a body that is not a
 * strategy report, throws.
 */
export async function fetchStrategyPerformance(strategyId: string): Promise<StrategyPerformance | null> {
  let body: unknown;
  try {
    body = await apiFetch<unknown>(`/performance/strategies/${encodeURIComponent(strategyId)}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
  if (!isStrategyPerformance(body)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /performance/strategies: expected a strategy report",
    });
  }
  return body;
}

export const TRADES_PAGE_SIZE = 20;

function isOtherFee(value: unknown): boolean {
  return isRecord(value) && typeof value.currency === "string" && typeof value.amount === "string";
}

/**
 * `rehearsal_fill_price` is null exactly when the row is not a rehearsal row. On a rehearsal
 * row any string is kept, so a value a later API invents is read as the plain tag, not refused.
 */
function isRehearsalMark(rehearsal: boolean, price: unknown): boolean {
  return rehearsal ? typeof price === "string" : price === null;
}

function isTrade(value: unknown): value is StrategyTrade {
  return (
    isRecord(value) &&
    typeof value.allocation_id === "string" &&
    typeof value.pair === "string" &&
    typeof value.direction === "string" &&
    typeof value.opened_at === "string" &&
    typeof value.closed_at === "string" &&
    typeof value.rehearsal === "boolean" &&
    isRehearsalMark(value.rehearsal, value.rehearsal_fill_price) &&
    isNullableString(value.base_currency) &&
    isNullableString(value.entry_price) &&
    isNullableString(value.exit_price) &&
    isNullableString(value.size) &&
    typeof value.fees === "string" &&
    Array.isArray(value.other_fees) &&
    value.other_fees.every(isOtherFee) &&
    typeof value.pnl === "string" &&
    isNullableString(value.capital_at_open) &&
    isNullableString(value.return) &&
    typeof value.fees_complete === "boolean"
  );
}

function isCursor(value: unknown): value is TradeCursor {
  return isRecord(value) && typeof value.before_closed_at === "string" && typeof value.before_allocation_id === "string";
}

function isTradesPage(value: unknown): value is StrategyTradesPage {
  return (
    isRecord(value) &&
    Array.isArray(value.trades) &&
    value.trades.every(isTrade) &&
    (value.next_cursor === null || isCursor(value.next_cursor))
  );
}

/**
 * One page of `GET /api/performance/strategies/{id}/trades`. `cursor` is the
 * previous page's `next_cursor`, sent back as it came (both values, never a
 * rebuilt one); null asks for the newest page. Keyset, never an offset: the
 * server pages on `(closed_at, allocation_id)`. A 404 throws: the page that
 * asks has just loaded the strategy, so a missing one is a failure, not an
 * empty list. A body that is not a trades page throws rather than render a
 * row with a wrong figure.
 */
export async function fetchStrategyTrades(
  strategyId: string,
  cursor: TradeCursor | null,
  limit = TRADES_PAGE_SIZE,
): Promise<StrategyTradesPage> {
  // Rehearsal rows are always asked for: the table marks them rather than hide them (decision 43).
  const query = new URLSearchParams({ limit: String(limit), include_rehearsal: "true" });
  if (cursor !== null) {
    query.set("before_closed_at", cursor.before_closed_at);
    query.set("before_allocation_id", cursor.before_allocation_id);
  }
  const body = await apiFetch<unknown>(`/performance/strategies/${encodeURIComponent(strategyId)}/trades?${query}`);
  if (!isTradesPage(body)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /performance/strategies/{id}/trades: expected a page of trades",
    });
  }
  return body;
}

function isOperationFill(value: unknown): value is OperationFill {
  return (
    isRecord(value) &&
    typeof value.filled_at === "string" &&
    (value.side === "BUY" || value.side === "SELL") &&
    typeof value.price === "string" &&
    typeof value.quantity === "string" &&
    typeof value.fee === "string" &&
    typeof value.fee_currency === "string" &&
    typeof value.rehearsal === "boolean"
  );
}

/**
 * The fills of one operation, from
 * `GET /api/performance/strategies/{id}/trades/{allocation_id}/fills`. The body must name the
 * allocation that was asked for and hold a non-empty list of readable fills: anything else is an
 * error, never a partial table. A 404 ("no such operation") throws too: the dialog that asks is
 * opened from a row of the list, so a missing operation is a failure.
 */
export async function fetchOperationFills(strategyId: string, allocationId: string): Promise<OperationFills> {
  const body = await apiFetch<unknown>(
    `/performance/strategies/${encodeURIComponent(strategyId)}/trades/${encodeURIComponent(allocationId)}/fills`,
  );
  if (
    !isRecord(body) ||
    body.allocation_id !== allocationId ||
    !Array.isArray(body.fills) ||
    body.fills.length === 0 ||
    !body.fills.every(isOperationFill) ||
    typeof body.truncated !== "boolean"
  ) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /performance/strategies/{id}/trades/{allocation_id}/fills: expected the fills of the operation asked for",
    });
  }
  return { allocation_id: body.allocation_id, fills: body.fills, truncated: body.truncated };
}

/**
 * `['performance','strategy',id,'trade-fills',allocationId]` (design § F). Mounting it is what
 * asks for the fills; without both ids it asks for nothing.
 */
export function useOperationFills(strategyId: string, allocationId: string) {
  return useQuery({
    queryKey: ["performance", "strategy", strategyId, "trade-fills", allocationId],
    queryFn: () => fetchOperationFills(strategyId, allocationId),
    enabled: strategyId !== "" && allocationId !== "",
    staleTime: PERFORMANCE_STALE_MS,
  });
}

/** Query key `['performance','strategy',id]` (design.md § 15). */
export function useStrategyPerformance(strategyId: string) {
  return useQuery({
    queryKey: ["performance", "strategy", strategyId],
    queryFn: () => fetchStrategyPerformance(strategyId),
    staleTime: PERFORMANCE_STALE_MS,
  });
}

/**
 * `['performance','strategy',id,'trades']` (design.md § 15): an infinite query on the
 * keyset cursor. The next page's parameter is exactly the `next_cursor` the server
 * answered; a null cursor ends the list.
 */
export function useStrategyTrades(strategyId: string) {
  return useInfiniteQuery({
    queryKey: ["performance", "strategy", strategyId, "trades"],
    initialPageParam: null as TradeCursor | null,
    queryFn: ({ pageParam }) => fetchStrategyTrades(strategyId, pageParam),
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    staleTime: PERFORMANCE_STALE_MS,
  });
}

export function poolPerformanceKey(exchange: string, venue: string, currency: string) {
  return ["performance", "pool", exchange, venue, currency] as const;
}

const PERFORMANCE_STALE_MS = 60_000;

/** Query key `['performance','pool',ex,venue,ccy]`; every range arrives in the one body. */
export function usePoolPerformance(exchange: string, venue: string, currency: string) {
  return useQuery({
    queryKey: poolPerformanceKey(exchange, venue, currency),
    queryFn: () => fetchPoolPerformance(exchange, venue, currency),
    staleTime: PERFORMANCE_STALE_MS,
  });
}
