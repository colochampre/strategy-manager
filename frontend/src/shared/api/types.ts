/**
 * Mirrors `reconciliation/infrastructure/router.py`'s response models. Every
 * money field is typed `string` on purpose — the backend serializes
 * `Decimal` values as JSON strings (never `Decimal`/`float`) so an
 * append-only ledger never loses precision on the wire. Nothing in this
 * module (or anything importing it in this unit) converts a money field
 * with `Number`/`parseFloat`.
 */

export interface ProposedFill {
  exchange_fill_id: string;
  exchange_order_id: string | null;
  side: string;
  quantity: string;
  price: string;
  fee: string;
  fee_currency: string;
  filled_at: string;
}

/** Mirrors `BookingProposalView` — the frozen snapshot in full. */
export interface BookingProposal {
  id: string;
  discrepancy_id: string;
  exchange: string;
  venue: string;
  settlement_currency: string;
  symbol: string;
  kind: string;
  allocation_id: string;
  strategy_id: string;
  side: string;
  quantity: string;
  observed_venue_net_base: string;
  observed_ledger_net_base: string;
  observed_allocation_ids: readonly string[];
  fills: readonly ProposedFill[];
  client_order_id: string;
  expires_at: string;
  prepared_by_job_id: string;
  created_at: string;
  state: string;
  decided_at: string | null;
  decided_by: string | null;
  decision_reason: string | null;
  execution_attempt_id: string | null;
}

export interface ApproveResponse {
  outcome: string;
  execution_attempt_id: string | null;
  ledger_entries_written: number;
}

export interface RejectResponse {
  outcome: string;
  reason: string | null;
}

/** The flat `{outcome, detail}` shape every 409/422/503 refusal returns. */
export interface RefusalBody {
  outcome: string;
  detail: string;
}

/**
 * The part of `GET /api/pools` (`accounts/infrastructure/pools_router.py`,
 * `PoolBody`) the panel reads so far. Balance and reserved money join it with
 * the Overview (PR 11); none of it is ever summed across pools (rule 7).
 */
export interface Pool {
  exchange: string;
  venue: string;
  settlement_currency: string;
  enabled: boolean;
}

/**
 * One day of `curve` in `GET /api/performance/pools/{exchange}/{venue}/{ccy}`
 * (`performance_router.py`, `CurvePointBody`). `date` is a UTC calendar date
 * (`YYYY-MM-DD`); the ratios are decimal strings, as `Ratio` writes them in
 * `wire.py`: `index` is the compounded index E (1 is flat), `drawdown` is
 * E / peak - 1 (never above 0). The chart parses them for geometry only.
 */
export interface CurvePoint {
  date: string;
  daily_return: string;
  index: string;
  drawdown: string;
}

/** One UTC month of `monthly` (`MonthBody`); `return` is a ratio string (0.031 is 3.1%). */
export interface MonthReturn {
  year: number;
  month: number;
  return: string;
}

/**
 * One entry of `ranges` (`RangeBody`). `range` is one of `7D`, `30D`, `90D`,
 * `1Y`, `All`; `pnl` is money in the pool's settlement currency and `return`
 * a ratio, which the server never writes as null here.
 */
export interface RangeSummary {
  range: string;
  pnl: string;
  return: string;
  trade_count: number;
}

/** `excluded` (`ExcludedBody`): what the figures leave out. */
export interface Excluded {
  open_trade_count: number;
  rehearsal_fill_count: number;
  no_capital_at_open: number;
  unconverted_fee: number;
  unresolved_allocation_count: number;
}
