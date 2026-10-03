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

/** `balance` of `GET /api/pools` (`BalanceBody`): one pool's snapshot, in its own currency. */
export interface PoolBalance {
  total: string;
  /** What the allocator may still use; the Overview's lead figure. */
  available: string;
  /** ISO-8601 with an explicit offset. */
  observed_at: string;
  /** Older than the allocator's own limit, so it would refuse this snapshot. */
  stale: boolean;
}

/**
 * One row of `GET /api/pools` (`accounts/infrastructure/pools_router.py`,
 * `PoolBody`). `balance` and `allocatable` are null for a pool nothing has
 * synced. Nothing here is ever summed across pools (rule 7).
 */
export interface Pool {
  exchange: string;
  venue: string;
  settlement_currency: string;
  enabled: boolean;
  balance: PoolBalance | null;
  reserved: string;
  allocatable: string | null;
}

/** The three values that name one capital pool (`PoolRef` on the server). */
export interface PoolKey {
  exchange: string;
  venue: string;
  settlement_currency: string;
}

/**
 * `GET /api/pools/{exchange}/{venue}/{ccy}/available-pairs`
 * (`strategies/infrastructure/pair_catalog_router.py`, `AvailablePairsBody`).
 * `pairs` is sorted and in market-key form (`STXUSDT`), which is the form a
 * save accepts back; `count` is `pairs.length`. No money or quantity in it.
 */
export interface AvailablePairs {
  pool: PoolKey;
  pairs: string[];
  count: number;
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

/** `uptime` of `GET /api/strategies` (`UptimeView`): cumulative time enabled (decision 9). */
export interface StrategyUptime {
  seconds: number;
  /** ISO-8601; null for a strategy that was never enabled. */
  first_enabled_at: string | null;
  /** The earliest enable is a migration BASELINE row, so the true first date is unknown. */
  baseline: boolean;
}

/**
 * One row of `GET /api/strategies/{id}/events` (`EnablementEventView`).
 * `origin` is `OBSERVED` for a change this system saw and `BASELINE` for the one
 * row a migration wrote for a strategy that was already enabled.
 */
export interface EnablementEvent {
  enabled: boolean;
  /** ISO-8601 with an explicit offset. */
  occurred_at: string;
  origin: string;
}

export type FillMode = "SKIP" | "PARTIAL";

/**
 * One strategy of `GET /api/strategies` (`StrategyView`). `allocation_percent`
 * is a decimal string; `archived_at` is null while the strategy is live.
 */
export interface Strategy {
  id: string;
  name: string;
  exchange: string;
  venue: string;
  settlement_currency: string;
  fill_mode: FillMode;
  allocation_percent: string;
  enabled: boolean;
  archived_at: string | null;
  allowed_pairs: string[];
  uptime: StrategyUptime;
}

/** The body of `POST /api/strategies` (`RegisterRequest`); `id` is the alert's `signalType`. */
export interface RegisterStrategyBody {
  id: string;
  name: string;
  exchange: string;
  venue: string;
  settlement_currency: string;
  fill_mode: FillMode;
  allocation_percent: string;
  allowed_pairs: string[];
}

/** One row of `by_pair` (`PairBody`): a pair's closed trades; `return` is null without capital at open. */
export interface PairStat {
  pair: string;
  trades: number;
  pnl: string;
  return: string | null;
}

/**
 * One closed operation of `GET /api/performance/strategies/{id}/trades`
 * (`TradeBody`). `direction` is `LONG` or `SHORT`. Instants are ISO-8601 UTC.
 * `capital_at_open` and `return` are null for an operation opened before the
 * pool's total was recorded (decision 43): never a zero. `return` is `pnl` over
 * `capital_at_open`, the POOL's capital, never the position's margin.
 * `fees_complete` is false when a fee in a third currency was left out of `pnl`.
 */
export interface StrategyTrade {
  allocation_id: string;
  pair: string;
  direction: string;
  opened_at: string;
  closed_at: string;
  pnl: string;
  capital_at_open: string | null;
  return: string | null;
  fees_complete: boolean;
}

/** `next_cursor` of the trades list: exactly the two query parameters that ask for the page after it. */
export interface TradeCursor {
  before_closed_at: string;
  before_allocation_id: string;
}

/** One page of the trades list; a null `next_cursor` is the last page. */
export interface StrategyTradesPage {
  trades: StrategyTrade[];
  next_cursor: TradeCursor | null;
}

/**
 * `GET /api/performance/strategies/{id}` (`StrategyPerformanceBody`): the pool
 * report's shape for one strategy, in its pool's own currency, plus the
 * breakdown by pair.
 */
export interface StrategyPerformance extends PoolPerformance {
  strategy_id: string;
  by_pair: PairStat[];
}

/**
 * `GET /api/performance/pools/{exchange}/{venue}/{ccy}` (`PerformanceBody`).
 * One pool in its own currency: the endpoint returns every range at once, so
 * the range selector only chooses an entry of `ranges` and never refetches.
 * An empty ledger (the DRY_RUN reality) is a 200 with zeros and empty lists.
 */
export interface PoolPerformance {
  pool: { exchange: string; venue: string; settlement_currency: string };
  currency: string;
  day_boundary: string;
  trade_count: number;
  total_pnl: string;
  max_drawdown: string;
  excluded: Excluded;
  ranges: RangeSummary[];
  curve: CurvePoint[];
  monthly: MonthReturn[];
}
