import { useQuery } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/shared/api/client";

/**
 * `GET /api/positions/open` (design addendum "open positions", sections F and H).
 * Money, sizes and the leverage are JSON strings and are never converted here.
 */

export interface OpenPool {
  exchange: string;
  venue: string;
  settlement_currency: string;
}

export interface OtherFee {
  currency: string;
  amount: string;
}

export interface VenueDisagreement {
  discrepancy_id: string;
  venue_net_base: string;
  ledger_net_base: string;
  allocation_count: number;
  last_observed_at: string;
}

export type PositionOrigin = "rehearsal" | "live" | "mixed";
export type OrderOrigin = "rehearsal" | "live" | "unknown";

export interface OpenPosition {
  allocation_id: string;
  strategy_id: string | null;
  strategy_name: string;
  strategy_archived: boolean | null;
  pool: OpenPool;
  currency: string;
  markets: string[];
  origin: PositionOrigin;
  figures_missing: string | null;
  side: "LONG" | "SHORT" | null;
  base_currency: string | null;
  size: string | null;
  opened_size: string | null;
  entry_price: string | null;
  opened_at: string | null;
  fill_count: number;
  fees: string | null;
  other_fees: OtherFee[];
  margin_granted: string | null;
  leverage: string | null;
  reservation_status: string | null;
  venue_disagreement: VenueDisagreement | null;
}

export interface InFlightOrder {
  attempt_id: string;
  strategy_id: string | null;
  strategy_archived: boolean | null;
  strategy_name: string | null;
  pool: OpenPool;
  market: string;
  action: "OPEN" | "CLOSE" | null;
  origin: OrderOrigin;
  submitted_at: string | null;
}

/** One answer of the route: what every place of the panel selects from. */
export interface OpenState {
  as_of: string;
  positions: OpenPosition[];
  orders: InFlightOrder[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isText(value: unknown): value is string {
  return typeof value === "string";
}

/** A field the route always writes, as text or as JSON null: a MISSING field is neither and is refused. */
function isTextOrNull(value: unknown): boolean {
  return value === null || typeof value === "string";
}

/** An instant the browser can read: a time it cannot would be written as "Invalid Date" or as nothing. */
function isInstant(value: unknown): value is string {
  return typeof value === "string" && !Number.isNaN(new Date(value).getTime());
}

function isInstantOrNull(value: unknown): boolean {
  return value === null || isInstant(value);
}

function isNonEmptyText(value: unknown): value is string {
  return typeof value === "string" && value !== "";
}

/**
 * The three values of a pool, each a non-empty string on EVERY element, as `fetchPools` requires them of a
 * pool: the exchange decides which tab shows the element, so an element without one would belong nowhere and
 * must be an error on screen, never a row that silently is not drawn.
 */
function isPoolKey(value: unknown): value is OpenPool {
  return (
    isRecord(value) &&
    isNonEmptyText(value.exchange) &&
    isNonEmptyText(value.venue) &&
    isNonEmptyText(value.settlement_currency)
  );
}

function isOtherFee(value: unknown): value is OtherFee {
  return isRecord(value) && isText(value.currency) && isText(value.amount);
}

function isVenueDisagreement(value: unknown): value is VenueDisagreement {
  return (
    isRecord(value) &&
    isText(value.discrepancy_id) &&
    isText(value.venue_net_base) &&
    isText(value.ledger_net_base) &&
    typeof value.allocation_count === "number" &&
    isInstant(value.last_observed_at)
  );
}

const POSITION_ORIGINS: readonly unknown[] = ["rehearsal", "live", "mixed"];
const ORDER_ORIGINS: readonly unknown[] = ["rehearsal", "live", "unknown"];

function isPosition(value: unknown): value is OpenPosition {
  if (!isRecord(value)) return false;
  return (
    isText(value.allocation_id) &&
    isTextOrNull(value.strategy_id) &&
    isText(value.strategy_name) &&
    (value.strategy_archived === null || typeof value.strategy_archived === "boolean") &&
    isPoolKey(value.pool) &&
    isText(value.currency) &&
    Array.isArray(value.markets) &&
    value.markets.every(isText) &&
    POSITION_ORIGINS.includes(value.origin) &&
    isTextOrNull(value.figures_missing) &&
    (value.side === null || value.side === "LONG" || value.side === "SHORT") &&
    isTextOrNull(value.base_currency) &&
    isTextOrNull(value.size) &&
    isTextOrNull(value.opened_size) &&
    isTextOrNull(value.entry_price) &&
    isInstantOrNull(value.opened_at) &&
    typeof value.fill_count === "number" &&
    isTextOrNull(value.fees) &&
    Array.isArray(value.other_fees) &&
    value.other_fees.every(isOtherFee) &&
    isTextOrNull(value.margin_granted) &&
    isTextOrNull(value.leverage) &&
    isTextOrNull(value.reservation_status) &&
    (value.venue_disagreement === null || isVenueDisagreement(value.venue_disagreement))
  );
}

function isOrder(value: unknown): value is InFlightOrder {
  if (!isRecord(value)) return false;
  return (
    isText(value.attempt_id) &&
    isTextOrNull(value.strategy_id) &&
    (value.strategy_archived === null || typeof value.strategy_archived === "boolean") &&
    isTextOrNull(value.strategy_name) &&
    isPoolKey(value.pool) &&
    isText(value.market) &&
    (value.action === null || value.action === "OPEN" || value.action === "CLOSE") &&
    ORDER_ORIGINS.includes(value.origin) &&
    isInstantOrNull(value.submitted_at)
  );
}

function isOpenState(value: unknown): value is OpenState {
  return (
    isRecord(value) &&
    isInstant(value.as_of) &&
    Array.isArray(value.positions) &&
    value.positions.every(isPosition) &&
    Array.isArray(value.orders) &&
    value.orders.every(isOrder)
  );
}

/**
 * `GET /api/positions/open`: every open position and every order in flight of the system, one element per
 * allocation or attempt, each with its own pool. The body is checked element by element and refused WHOLE
 * when one is bad: a body that is not this shape is an error, never an empty list (K row 13), because an
 * empty list reads as "nothing is open". A 404 (an API that predates the route) is an error too, unlike the
 * pool report's 404, which means "no report".
 */
export async function fetchOpenPositions(): Promise<OpenState> {
  const body = await apiFetch<unknown>("/positions/open");
  if (!isOpenState(body)) {
    throw new ApiError(200, {
      detail: "Unexpected response shape from GET /positions/open: expected as_of, positions and orders",
    });
  }
  return body;
}

const OPEN_POSITIONS_MS = 60_000;

/** The key the booking dialogs invalidate and the "Read again" button asks for. */
export const OPEN_POSITIONS_KEY = ["positions", "open"] as const;

/**
 * Query key `['positions','open']`: ONE key, read by every component that draws an open position or an
 * order. Stale after 60 s and read again every 60 s (a state the owner acts on, not a history); the window
 * focus refetch is the client's default.
 */
export function useOpenPositions() {
  return useQuery({
    queryKey: OPEN_POSITIONS_KEY,
    queryFn: fetchOpenPositions,
    staleTime: OPEN_POSITIONS_MS,
    refetchInterval: OPEN_POSITIONS_MS,
  });
}

/** The elements whose `pool.exchange` is exactly that string. Nothing here asks the server anything. */
export function ofExchange(state: OpenState, exchange: string): OpenState {
  return {
    ...state,
    positions: state.positions.filter((position) => position.pool.exchange === exchange),
    orders: state.orders.filter((order) => order.pool.exchange === exchange),
  };
}

/** The elements of that strategy. A null `strategy_id` belongs to no strategy: no id equals it. */
export function ofStrategy(state: OpenState, strategyId: string): OpenState {
  return {
    ...state,
    positions: state.positions.filter((position) => position.strategy_id === strategyId),
    orders: state.orders.filter((order) => order.strategy_id === strategyId),
  };
}

function samePool(a: OpenPool, b: OpenPool): boolean {
  return a.exchange === b.exchange && a.venue === b.venue && a.settlement_currency === b.settlement_currency;
}

/** The elements of one pool: all three values, never the exchange alone (rule 7). */
export function ofPool(state: OpenState, pool: OpenPool): OpenState {
  return {
    ...state,
    positions: state.positions.filter((position) => samePool(position.pool, pool)),
    orders: state.orders.filter((order) => samePool(order.pool, pool)),
  };
}

/** The elements whose strategy id is null or is not among the rows on screen: matched by id, never by name. */
export function notShown(state: OpenState, visibleStrategyIds: ReadonlySet<string>): OpenState {
  const hidden = (id: string | null) => id === null || !visibleStrategyIds.has(id);
  return {
    ...state,
    positions: state.positions.filter((position) => hidden(position.strategy_id)),
    orders: state.orders.filter((order) => hidden(order.strategy_id)),
  };
}

/** The elements no strategy owns: a null `strategy_id`. */
export function unmatched(state: OpenState): OpenState {
  return {
    ...state,
    positions: state.positions.filter((position) => position.strategy_id === null),
    orders: state.orders.filter((order) => order.strategy_id === null),
  };
}
