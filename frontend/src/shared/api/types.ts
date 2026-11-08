/**
 * Mirrors the backend routers' response models. Every
 * money field is typed `string` on purpose — the backend serializes
 * `Decimal` values as JSON strings (never `Decimal`/`float`) so an
 * append-only ledger never loses precision on the wire. Nothing in this
 * module (or anything importing it in this unit) converts a money field
 * with `Number`/`parseFloat`.
 */

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

/**
 * One row of `GET /api/public/strategies` (`PublicStrategyBody`): what any signed-in user sees of a strategy on
 * the public list. `unleveraged_return_before_fees` is a ratio string, read from the fills of its author's real
 * closed trades (decision 34) and "0" while there is none, so a reader must be told what it leaves out and
 * `closed_trade_count` says whether there is a return at all. `capital` is money in the strategy's own
 * currency: null under the brake, when nobody trades live, and "0" with the brake off and nobody live.
 */
export interface PublicStrategy {
  id: string;
  name: string;
  author_name: string;
  exchange: string;
  venue: string;
  settlement_currency: string;
  created_at: string;
  closed_trade_count: number;
  unleveraged_return_before_fees: string;
  live_subscribers: number;
  capital: string | null;
  /** The author's plain text about the strategy, shown as text and never as markup; null when there is none. */
  description: string | null;
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

export type SubscriptionStatus = "ACTIVE" | "LEAVING" | "ENDED";

/**
 * The signed-in user's own place in a strategy (`SubscriptionView`), in their own pool. `allocation_percent`
 * is a decimal string: the share of that pool the strategy may ask for per trade. A LEAVING subscription takes
 * no new openings and ends with the strategy's next close.
 */
export interface Subscription {
  id: string;
  strategy_id: string;
  pool_id: number;
  allocation_percent: string;
  /** The leverage the system sets on the exchange before this subscription's next opening: a whole number from 1 to 20. */
  leverage: number;
  status: SubscriptionStatus;
  created_at: string | null;
  left_at: string | null;
  ended_at: string | null;
}

/**
 * One strategy of `GET /api/strategies` (`StrategyView`). `subscription` is the signed-in user's live
 * (ACTIVE or LEAVING) subscription to it, or null; the share lives there, not on the strategy.
 * `archived_at` is null while the strategy is live. `secret_last4` is the last four characters of its
 * webhook secret, the only part of it the API ever serves again: the panel masks the secret with them.
 * `subscribers` counts every ACTIVE subscription, the author's and simulated ones included, and
 * `live_subscribers` those trading it live, 0 under the brake (decisions 10 and 30). `capital` is the one
 * figure the public list shows, private strategies included, and null under the brake.
 */
export interface Strategy {
  id: string;
  name: string;
  exchange: string;
  venue: string;
  settlement_currency: string;
  fill_mode: FillMode;
  subscription: Subscription | null;
  enabled: boolean;
  archived_at: string | null;
  allowed_pairs: string[];
  uptime: StrategyUptime;
  visibility: Visibility;
  /** The token a LINK strategy opens to, sent to its author only; null otherwise. */
  share_token: string | null;
  secret_last4: string;
  /** The author's plain text about the strategy, up to 2,000 characters; null when there is none. */
  description: string | null;
  subscribers: number;
  live_subscribers: number;
  capital: string | null;
}

/**
 * One row of `GET /api/subscriptions/held`: a live subscription and what names its strategy to the user who holds
 * it. It reads whatever the strategy's visibility, because a subscriber keeps a strategy that turned private.
 * `author_name` is null while the author has chosen no name.
 */
export interface HeldSubscription extends Subscription {
  strategy_name: string;
  author_name: string | null;
  authored: boolean;
  exchange: string;
  venue: string;
  settlement_currency: string;
}

/**
 * Who else may subscribe to a strategy (decision 41): a PUBLIC one is listed on Explore, a LINK one opens to
 * whoever holds its link, a PRIVATE one to whoever holds a live invitation code. Private is the default
 * (decision 21).
 */
export type Visibility = "PUBLIC" | "LINK" | "PRIVATE";

/** A live invitation code in its author's list: never the code, only its last four characters. */
export interface InviteCode {
  id: string;
  hint: string;
  expires_at: string;
}

/** A code just made: the only answer that ever carries it, as `XXXX-XXXX`. */
export interface IssuedInviteCode extends InviteCode {
  code: string;
}

/**
 * The body of `POST /api/strategies` (`RegisterRequest`); `id` is the alert's `signalType`. The share becomes
 * the author's own subscription, made with the strategy.
 */
export interface RegisterStrategyBody {
  id: string;
  name: string;
  exchange: string;
  venue: string;
  settlement_currency: string;
  fill_mode: FillMode;
  allocation_percent: string;
  /** The leverage of the author's own subscription, a whole number from 1 to 20. */
  leverage: number;
  visibility: Visibility;
  allowed_pairs: string[];
  /** Left out when the author wrote none; the server trims it and turns a blank one into null. */
  description?: string | null;
}

/** The body of `PATCH /api/strategies/{id}` for the description alone: null clears it. */
export interface UpdateStrategyDescriptionBody {
  description: string | null;
}

/**
 * What `POST /api/strategies` answers beyond the strategy: the webhook secret, shown once. `null` when the
 * answer carried none (an older API), which the dialog says instead of showing a URL.
 */
export interface RegisteredStrategy {
  webhook_secret: string | null;
}

/**
 * One row of `by_pair` (`PairBody`): a pair's closed trades; `return` is null without capital at open.
 * `wins` counts the trades whose pnl is above zero and `win_rate` is `wins` over `trades` as a
 * fraction in [0, 1], a decimal string. Neither is ever null: a pair listed has at least one trade.
 */
export interface PairStat {
  pair: string;
  trades: number;
  wins: number;
  win_rate: string;
  pnl: string;
  return: string | null;
}

/** One row of a public record's `by_pair`: a pair's trades and compounded return, with no money (I.12a). */
export interface RecordPairStat {
  pair: string;
  trades: number;
  wins: number;
  win_rate: string;
  return: string;
}

/** One entry of a public record's `ranges`: the return and the trades of a range, with no money. */
export interface RecordRange {
  range: string;
  return: string;
  trade_count: number;
}

/**
 * `GET /api/public/strategies/{id}/record` (`PublicRecordBody`): the author's real fills, drawn by anyone.
 * The curve and months have the private report's shape; no pnl, currency or pool exists in it.
 */
export interface PublicRecord {
  day_boundary: string;
  origin: string | null;
  closed_trade_count: number;
  max_drawdown: string;
  ranges: RecordRange[];
  curve: CurvePoint[];
  monthly: MonthReturn[];
  by_pair: RecordPairStat[];
}

/** `balance` of `GET /api/strategies/{id}/share-preview` (`SharePreviewBalanceBody`). */
export interface SharePreviewBalance {
  total: string;
  observed_at: string;
  stale: boolean;
}

/** `exact` of the share preview: the amount of the share as stored, a plain decimal string. */
export interface SharePreviewExact {
  share: string;
  amount: string;
  below_pool_minimum: boolean;
  /** `amount` times the leverage asked, served only when one was asked; null or absent otherwise. */
  notional?: string | null;
}

/** One entry of `steps`: `share` is a JSON integer, a step is a whole share. */
export interface SharePreviewStep {
  share: number;
  amount: string;
  below_pool_minimum: boolean;
}

/**
 * `GET /api/strategies/{id}/share-preview` (`SharePreviewBody`). `balance`,
 * `exact` and `steps` are null, null and empty together: a pool nothing has
 * synced has no amount, never a zero. `exact` is also null when the caller
 * holds no seat and asked no share (decision 39): `balance` and the hundred
 * `steps` are still served, and the panel draws no figure until a share is typed.
 */
export interface SharePreview {
  strategy_id: string;
  pool: { exchange: string; venue: string; settlement_currency: string };
  currency: string;
  pool_minimum: string;
  balance: SharePreviewBalance | null;
  exact: SharePreviewExact | null;
  steps: SharePreviewStep[];
}

/** `GET /api/webhook-origin` (`WebhookOriginBody`): a serialised origin, or null when none is set. */
export interface WebhookOrigin {
  origin: string | null;
}

/**
 * One closed operation of `GET /api/performance/strategies/{id}/trades`
 * (`TradeBody`). `direction` is `LONG` or `SHORT`. Instants are ISO-8601 UTC.
 * `capital_at_open` and `return` are null for an operation opened before the
 * pool's total was recorded (decision 43): never a zero. `return` is `pnl` over
 * `capital_at_open`, the POOL's capital, never the position's margin.
 * `fees_complete` is false when a fee in a third currency was left out of `pnl`.
 *
 * Decision 43 adds the operation's figures. `rehearsal` is never null;
 * `rehearsal_fill_price` is null exactly when `rehearsal` is false and, on a
 * rehearsal row, `FIXED_ONE`, `ALERT`, `UNDETERMINED` or a value this panel
 * does not know. `base_currency`, `entry_price`, `exit_price` and `size` are
 * null TOGETHER, meaning "not derivable from the fills", never zero. `fees` is
 * a string and can be a bare "0"; `other_fees` lists fees in other currencies.
 */
export interface StrategyTrade {
  allocation_id: string;
  pair: string;
  direction: string;
  opened_at: string;
  closed_at: string;
  rehearsal: boolean;
  rehearsal_fill_price: string | null;
  base_currency: string | null;
  entry_price: string | null;
  exit_price: string | null;
  size: string | null;
  fees: string;
  other_fees: OtherFee[];
  pnl: string;
  capital_at_open: string | null;
  return: string | null;
  fees_complete: boolean;
}

/** A fee paid in a currency other than the pool's; the amount is above zero and is never converted. */
export interface OtherFee {
  currency: string;
  amount: string;
}

/**
 * One fill of an operation, from `GET /api/performance/strategies/{id}/trades/{allocation_id}/fills`.
 * No field is nullable; `price`, `quantity` and `fee` are the stored values as strings.
 */
export interface OperationFill {
  filled_at: string;
  side: "BUY" | "SELL";
  price: string;
  quantity: string;
  fee: string;
  fee_currency: string;
  rehearsal: boolean;
}

/** The fills of one operation: never empty; `truncated` is true when only the first 200 are served. */
export interface OperationFills {
  allocation_id: string;
  fills: OperationFill[];
  truncated: boolean;
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
  /**
   * The UTC day the first trade with a return opened, where the curve starts at 0
   * (decision 36); `null` with no such trade. Absent only from an API older than it.
   */
  origin?: string | null;
  trade_count: number;
  total_pnl: string;
  max_drawdown: string;
  excluded: Excluded;
  ranges: RangeSummary[];
  curve: CurvePoint[];
  monthly: MonthReturn[];
}
