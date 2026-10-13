import { useQuery } from "@tanstack/react-query";

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

const EMPTY: OpenState = { as_of: "", positions: [], orders: [] };

export async function fetchOpenPositions(): Promise<OpenState> {
  return Promise.resolve(EMPTY);
}

export function useOpenPositions() {
  return useQuery({ queryKey: ["positions", "stub"], queryFn: fetchOpenPositions });
}

export function ofExchange(state: OpenState, _exchange: string): OpenState {
  return { ...state, positions: [], orders: [] };
}

export function ofStrategy(state: OpenState, _strategyId: string): OpenState {
  return { ...state, positions: [], orders: [] };
}

export function ofPool(state: OpenState, _pool: OpenPool): OpenState {
  return { ...state, positions: [], orders: [] };
}

export function notShown(state: OpenState, _visibleStrategyIds: ReadonlySet<string>): OpenState {
  return { ...state, positions: [], orders: [] };
}

export function unmatched(state: OpenState): OpenState {
  return { ...state, positions: [], orders: [] };
}
