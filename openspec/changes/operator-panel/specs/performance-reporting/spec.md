# Performance Reporting Specification

> **Revised 2026-09-24.** Realigned with design findings and owner decisions:
> F1 (pool capital comes from the balance read made INSIDE the allocation lock),
> F2 (rehearsal fills are excluded by a named marker), F3 (only
> settlement-currency fees are subtracted; nothing is converted), F4 (pairs are
> keyed by `market_key()` per allocation), decision 16 (UTC day and month
> boundaries) and decision 17 (the return formula in design §11 is confirmed).
>
> **Revised 2026-10-04 (owner decisions 43 and 45, design addendum "decision
> 43").** A strategy's operations are listed one by one with their prices, size
> and fees. Rehearsal operations are listed, marked, and only on request; they
> stay out of every figure. Two requirements are revised so they no longer
> contradict that: "Rehearsal Fills Are Excluded From Every Figure" and "No
> Qualifying Trades Produce Empty Results, Not an Error". Four requirements are
> added at the end of this file: "Each Operation In The Trades List Carries Its
> Prices, Size And Fees", "Rehearsal Operations Are Listed Only On Request",
> "A Rehearsal Operation Says How Its Opening Fills Were Priced" and "One
> Operation's Fills Are Read By Strategy And Allocation Together".

## Purpose

Read-only projections over the append-only ledger (rule 6) and the capital
pool at open. Every figure in this domain is scoped to one
`(exchange, venue, settlement_currency)` capital pool, expressed in that
pool's native settlement currency (rule 7). No requirement in this domain
computes, stores, or returns a cross-pool or cross-currency blended total.
Nothing in this domain writes to `ledger_entries`. Every day and month
boundary in this domain is UTC.

## Requirements

### Requirement: Pool Capital At Open Is Recorded On the Reservation

When a reservation is created for an opening signal against pool
`(exchange, venue, settlement_currency)`, the reservation MUST record the
pool's capital at that moment: the `pool_balance.total` that `AllocateCapital`
reads INSIDE the pool's advisory lock, the read the allocation decision is
made from (`allocate_capital.py:131`). It MUST NOT be the earlier pre-lock read
used to size the requested amount. This write MUST occur inside the existing
serialized allocation transaction for that pool; no new read and no new lock
are introduced.

#### Scenario: A reservation records the in-lock pool capital

- GIVEN pool `(bybit, usdt-m, USDT)` reads 510 USDT before the lock (used to size the request) and 500 USDT inside the lock
- WHEN the reservation is created inside that pool's advisory-locked transaction
- THEN the reservation stores 500 USDT as the pool capital at open, the in-lock read, and no additional read is performed

#### Scenario: Pool capital at open cannot be recovered after the fact for a value never recorded

- GIVEN a reservation created before this requirement existed, with no recorded pool-capital-at-open value
- WHEN that reservation's return is computed
- THEN the system MUST treat the value as absent rather than reconstruct it, count the trade in PnL amounts, exclude it from percentage figures, and report the exclusion count

### Requirement: Rehearsal Fills Are Excluded From Every Figure

Fills minted by the DRY_RUN fake exchange carry an `exchange_fill_id` starting
with the named domain constant `REHEARSAL_FILL_ID_PREFIX` (`"fake-fill-"`).
Every figure of this domain MUST exclude those fills. A figure is every sum,
count, ratio or series any read model returns: trade counts, realized PnL, the
return, the compounded curve, drawdown, the monthly grid, the PnL ranges, the
by-pair and by-strategy statistics, and the open-trade and exclusion counts.
Every read model's response to a request that does not ask for rehearsal rows
MUST be computed as if no rehearsal fill existed. The constant MUST be the
single definition used both by the fake exchange that mints the ids and by the
reads that exclude them.

The one exception is the strategy's trades list (see "Rehearsal Operations Are
Listed Only On Request"): requested with `include_rehearsal=true`, it MAY list
a rehearsal operation as a marked row. The exception covers rows only. A
rehearsal operation's own figures belong to that row alone, and no figure of
any read model, including the other fields of the same response, MUST include
them.

`excluded.rehearsal_fill_count` MUST keep its meaning: the number of rehearsal
fills in the read's scope, including fills of allocations that are still open
and of mixed allocations. No other `excluded` key is added.

(Previously: "Every read model in this domain MUST exclude those fills", with
no exception, which the trades list of owner decision 43 contradicts. The rule
now holds for every figure and for every default request, and names the one
exception precisely.)

#### Scenario: A rehearsal fill never reaches a figure

- GIVEN pool `(bybit, usdt-m, USDT)` has a settled rehearsal allocation whose fills carry `fake-fill-` ids, and one real closed allocation
- WHEN any performance read model is requested for that pool without `include_rehearsal`
- THEN only the real allocation is counted, in trades, PnL, the curve, the grid and the ranges

#### Scenario: Asking for rehearsal rows changes no figure

- GIVEN strategy S1 in pool `(bybit, usdt-m, USDT)` has one real closed trade with PnL +14.245 USDT and one rehearsal round trip
- WHEN S1's pool report, strategy report, curve, monthly grid, ranges and by-pair statistics are read, and S1's trades list is read with `include_rehearsal=true`
- THEN every report, curve, grid, range and by-pair response is identical to the one read from a ledger that holds the real trade alone, and the trade count is 1

#### Scenario: The rehearsal fill count keeps counting every rehearsal fill

- GIVEN pool `(bybit, usdt-m, USDT)` holds 4 rehearsal fills of a closed rehearsal allocation, 1 rehearsal fill of a rehearsal allocation still open, and 2 rehearsal fills inside a mixed allocation
- WHEN the pool's report is read
- THEN `excluded.rehearsal_fill_count` is 7, and no new `excluded` key is present

#### Scenario: A rehearsal operation's own PnL is in no total

- GIVEN a rehearsal operation in pool `(bybit, usdt-m, USDT)` whose own PnL is +3 USDT
- WHEN the trades list is read with `include_rehearsal=true`
- THEN that row carries +3 USDT as its own PnL, and every total in the pool report remains the sum over real operations only

### Requirement: Realized PnL Per Closed Allocation, In Native Settlement Currency

For an allocation whose position has netted to zero (non-rehearsal fills
only), the system MUST compute realized PnL as the sum of SELL notional minus
the sum of BUY notional minus the fees whose `fee_currency` equals the pool's
settlement currency, expressed in that pool's native settlement currency. A
fee paid in the base currency MUST NOT be subtracted again, because it already
reduced the base that was later sold. A fee in any third currency MUST NOT be
converted; the trade MUST be counted and flagged as having incomplete fees.
This MUST NEVER be blended across pools or currencies.

#### Scenario: Realized PnL for a single closed allocation

- GIVEN allocation A1 in pool `(bybit, usdt-m, USDT)` opened with notional 100 USDT and closed with notional 106 USDT and total fees 0.5 USDT
- WHEN A1's realized PnL is computed
- THEN it is 5.5 USDT, expressed in USDT (pool `(bybit, usdt-m, USDT)`'s settlement currency)

#### Scenario: A third-currency fee is flagged, not converted

- GIVEN allocation A3 in pool `(binance, usdt-m, USDT)` paid part of its fees in BNB
- WHEN A3's realized PnL is computed
- THEN the BNB fee is omitted, A3 is counted, and it is flagged as having incomplete fees

#### Scenario: An allocation still open has no realized PnL

- GIVEN allocation A2 in pool `(bybit, usdt-m, USDT)` has not netted to zero
- WHEN realized PnL is requested for A2
- THEN no realized PnL value is returned for A2, and A2 is counted as an open trade

### Requirement: Compounded Return Curve Per Pool

For each pool, the system MUST compute a compounded (geometric) return curve
with the formula confirmed by the owner (decision 17):

- each closed trade's return is `r_i = pnl_i / pool_capital_at_open_i`;
- returns of trades that close on the same UTC day are SUMMED into that day's
  return `R_d`;
- days are compounded: `E_d = E_(d-1) * (1 + R_d)`, starting from `E_0 = 1`;
- the second-order error for trades that span days is the accepted
  approximation;
- open trades, rehearsal fills and trades without capital-at-open are excluded,
  and each exclusion is reported as a count.

A strategy's curve MUST use the same formula over that strategy's trades, with
`r_i` still measured against the POOL capital at open, so it is the strategy's
contribution to the pool.

#### Scenario: Two trades on different days compound

- GIVEN pool `(bybit, usdt-m, USDT)` has one closed trade with return +5% on UTC day 1 and another with return +2% on UTC day 2
- WHEN the compounded curve is computed through day 2
- THEN the curve index is `1.05 * 1.02`

#### Scenario: Trades closing on the same UTC day are summed, not chained

- GIVEN a 1,000 USDT pool `(bybit, usdt-m, USDT)` where trade A (capital at open 1,000, PnL +20) and trade B (capital at open 1,000, PnL +10) both close on UTC day 1
- WHEN the curve is computed for day 1
- THEN the day's return is 0.02 + 0.01 = 0.03 and the index is 1.03, not 1.02 * 1.01

#### Scenario: Exclusions are reported, not hidden

- GIVEN pool `(bybit, usdt-m, USDT)` has two open trades and one closed trade without capital at open
- WHEN the curve is read
- THEN the response reports two open trades and one trade excluded for missing capital at open

### Requirement: Drawdown From Previous Peak

For each pool, the system MUST compute drawdown as the percentage decline of
the current compounded curve value from the highest compounded curve value
previously reached by that same pool's curve.

#### Scenario: Drawdown after a new low following a peak

- GIVEN pool `(bybit, usdt-m, USDT)`'s compounded curve peaked at index value 1.20 and has since declined to 1.14
- WHEN drawdown is computed
- THEN it is 5% below the 1.20 peak

#### Scenario: No drawdown at a new peak

- GIVEN pool `(bybit, usdt-m, USDT)`'s compounded curve reaches a new all-time-high value
- WHEN drawdown is computed at that point
- THEN drawdown is 0%

### Requirement: Monthly Grid Per Pool

For each pool, the system MUST provide a month-by-year grid of that pool's
period return, derived from the same compounded curve, with months delimited
in UTC and no cross-pool blending.

#### Scenario: Monthly grid reflects only its own pool

- GIVEN pool `(bybit, usdt-m, USDT)` and pool `(binance, usdt-m, USDT)` each have distinct monthly returns
- WHEN each pool's monthly grid is read
- THEN each grid shows only that pool's own monthly returns, never combined

#### Scenario: A close late on the last day of a month in local time counts in the UTC month

- GIVEN a trade in pool `(bybit, usdt-m, USDT)` closes at 2026-08-31 22:30 in UTC-3, which is 2026-09-01 01:30 UTC
- WHEN the monthly grid is read
- THEN the trade counts in September 2026

### Requirement: PnL By Range

For each pool, the system MUST provide realized PnL and compounded return over
each of the following ranges, computed from that pool's own closed trades only
and ending now: 7 days, 30 days, 90 days, 1 year (365 days), and all time.

#### Scenario: PnL ranges are computed independently per pool

- GIVEN pool `(bybit, usdt-m, USDT)` has closed trades inside and outside the last 30 days
- WHEN the 30D range is requested for that pool
- THEN only that pool's trades closed within the last 30 days are summed, in that pool's settlement currency

### Requirement: Stats By Strategy and By Pair

The system MUST provide, per strategy and per pool, trade count and realized
PnL by pair, where each trade is first derived per allocation and then keyed by
the `market_key()` of that allocation's fills (spelling variants such as
`SOLUSDT.P` and `SOLUSDT` merged), independent of the strategy's current
allowed-pairs list, so a pair removed from the allowlist still shows its
historical statistics.

#### Scenario: Per-pair stats include a pair no longer on the allowlist

- GIVEN strategy S1 in pool `(bybit, usdt-m, USDT)` has closed trades on `SOLUSDT`, which was later removed from S1's allowed pairs
- WHEN S1's per-pair statistics are read
- THEN `SOLUSDT`'s trade count and realized PnL still appear

#### Scenario: One trade with two spellings is one pair

- GIVEN strategy S1's allocation opened with fills on `SOLUSDT.P` and was closed by a booked fill written under `SOLUSDT`
- WHEN S1's per-pair statistics are read
- THEN the trade counts once, under the single pair `SOLUSDT`

#### Scenario: Per-strategy stats are scoped to that strategy's own pool

- GIVEN strategy S1 bound to pool `(bybit, usdt-m, USDT)`
- WHEN S1's stats are read
- THEN every figure is expressed in `(bybit, usdt-m, USDT)`'s settlement currency, USDT

### Requirement: Current Available Balance Per Pool

The system MUST provide each pool's current available balance from
`pool_balance_snapshots`, per pool, never combined across pools.

#### Scenario: Available balance reads the latest snapshot per pool

- GIVEN pool `(bybit, usdt-m, USDT)` has a current snapshot of 480 USDT
- WHEN the pool's available balance is read
- THEN 480 USDT is returned for that pool alone

### Requirement: No Cross-Pool or Cross-Currency Blended Total

No performance read model in this domain MUST compute, cache, or return a
total that sums figures across two different `(exchange, venue,
settlement_currency)` pools, including pools on the same exchange with
different settlement currencies. `usd_rate_at_fill` MUST NOT be used to
produce a blended total anywhere in this domain.

#### Scenario: Two pools on the same exchange are never summed

- GIVEN an exchange with pool `(usdt-m, USDT)` and pool `(coin-m, BTC)`
- WHEN performance data for that exchange is read
- THEN each pool's figures are returned separately and no combined total across them exists

### Requirement: No Qualifying Trades Produce Empty Results, Not an Error

When a pool has no qualifying closed trades (no ledger entries at all, or only
rehearsal fills, as is normal under `DRY_RUN`), every read model in this
domain MUST return a well-defined empty result (zero trades, no curve points,
zero PnL) rather than an error. Rehearsal operations are never qualifying
trades, so a pool that holds only rehearsal fills has no qualifying trades.

The one exception is the strategy's trades list requested with
`include_rehearsal=true`: for a ledger of only rehearsal fills it MUST list the
closed rehearsal operations, marked, instead of an empty list. Every total in
that same pool, and the trades list on a default request, MUST still be empty.

(Previously: "every read model" returned the empty result for a ledger of only
rehearsal fills, with no exception. The trades list on request is now the one
read that does not.)

#### Scenario: An empty ledger yields empty performance data

- GIVEN pool `(bybit, usdt-m, USDT)` has no ledger entries
- WHEN any performance read model is requested for that pool
- THEN it returns an empty result with no error raised

#### Scenario: A ledger holding only rehearsal fills yields empty performance data

- GIVEN pool `(bybit, usdt-m, USDT)` holds only fills whose ids start with `fake-fill-`
- WHEN any performance read model is requested for that pool without `include_rehearsal`
- THEN it returns the same empty result, with no error raised

#### Scenario: A rehearsal-only ledger lists its operations on request and still totals nothing

- GIVEN strategy S1 in pool `(bybit, usdt-m, USDT)` whose ledger holds one closed rehearsal round trip and nothing else
- WHEN S1's trades list is read with `include_rehearsal=true`, and S1's strategy report, the pool's curve and monthly grid are read
- THEN the list holds exactly one row, marked rehearsal, and the report shows 0 trades and 0 PnL, the curve has no points and the grid is empty, with no error raised

### Requirement: Each Operation In The Trades List Carries Its Prices, Size And Fees

> **Added 2026-10-04 (owner decision 43).**

An operation is one allocation of a strategy: one reservation and every ledger
row carrying its id, all in the strategy's own pool, for example
`(bybit, usdt-m, USDT)`. The strategy's trades list MUST serve, for each closed
operation, its base currency, entry price, exit price, size, fees paid and fees
in other currencies, all derived from that operation's own fills, with no new
stored value. The derivation is made per operation and the figures are never
summed across operations.

- The opening fills are the fills on the side of the allocation's earliest fill
  (a tie goes to BUY) and the closing fills are those on the other side. An
  operation is closed when its net base quantity is zero under the existing
  base-fee rule with at least one fill on each side. An operation that has not
  netted to zero is not listed.
- The entry price MUST be the quantity-weighted average of the opening fills:
  the sum of their notional over the sum of their quantity. The exit price MUST
  be the same over the closing fills. The average MUST NOT be a mean of
  per-fill or per-group averages.
- The size MUST be the sum of the opening fills' quantity, in the base
  currency. The base currency MUST be the base of the allocation's market in
  upper case.
- The fees paid MUST be the sum of every fill's fee, both sides, whose fee
  currency is the pool's settlement currency, which is exactly the amount
  subtracted from the operation's PnL. A fee in any other currency MUST be
  listed once per currency, with its own summed amount above zero, sorted by
  currency, and MUST NOT be converted. Fee currencies are compared upper-cased.
- The operation's `fees_complete` flag keeps its meaning: a fee in the base
  currency is listed with the other fees and leaves the flag true, because the
  PnL already contains it. A fee in a third currency is listed and makes the
  flag false.
- When the figures cannot be derived (a side whose summed quantity or notional
  is not above zero, or fills naming more than one market), the base currency,
  entry price, exit price and size MUST all be absent together, the operation
  MUST stay in the list because it is in the totals, and the read MUST log one
  warning naming the pool, strategy and allocation. Two spellings of one market
  (`STXUSDT.P` and `STXUSDT`) are not a disagreement. The fees paid and the
  other fees are plain sums, are never absent, and an absent figure MUST NEVER
  be served as zero.
- The return keeps its meaning: PnL over the pool capital recorded on the
  operation's reservation, absent when none was recorded.
- When both sides hold the same quantity and every fee is in the settlement
  currency, PnL MUST equal `(exit price - entry price) x size x (+1 for LONG,
  -1 for SHORT) - fees paid`.

#### Scenario: One fill per side gives that fill's prices

- GIVEN strategy S1 in pool `(bybit, usdt-m, USDT)` has a closed LONG that bought 1250 `STXUSDT.P` at 0.4512 (notional 564.0, fee 0.31 USDT) and sold 1250 `STXUSDT` at 0.4631 (notional 578.875, fee 0.32 USDT)
- WHEN S1's trades list is read
- THEN the row has pair `STXUSDT`, base currency `STX`, entry price 0.4512, exit price 0.4631, size 1250, fees paid 0.63 USDT, no other fees, and PnL 14.245 USDT

#### Scenario: Several opening fills are averaged by quantity

- GIVEN a closed LONG in pool `(bybit, usdt-m, USDT)` that bought 100 at 0.40, 300 at 0.44 and 600 at 0.46 (total notional 448) and sold 1000 at 0.50
- WHEN the trades list is read
- THEN the entry price is 0.448, not 0.4333..., the size is 1000, and the exit price is 0.50

#### Scenario: A SHORT's entry is its SELL side

- GIVEN a closed SHORT in pool `(bybit, usdt-m, USDT)` that sold 2 `SOLUSDT` at 150 first and bought 2 at 140 later, with no fees
- WHEN the trades list is read
- THEN the direction is SHORT, the entry price is 150, the exit price is 140, the size is 2, and PnL is +20 USDT

#### Scenario: A fee in the base currency is listed and the PnL stays complete

- GIVEN a closed operation that bought 1000 `STX` with a fee of 1 STX and sold 999 `STX`, with every other fee in USDT
- WHEN the trades list is read
- THEN the size is 1000, the other fees list one entry of 1 STX, and `fees_complete` is true

#### Scenario: A fee in a third currency is listed, never converted

- GIVEN a closed operation in pool `(binance, usdt-m, USDT)` that paid 0.00012 BNB in fees and 0.63 USDT in fees
- WHEN the trades list is read
- THEN the fees paid are 0.63 USDT, the other fees list one entry of 0.00012 BNB, and `fees_complete` is false

#### Scenario: A figure that cannot be derived is absent, never zero, and the operation stays listed

- GIVEN a closed operation in pool `(bybit, usdt-m, USDT)` whose fills name `STXUSDT` and `SOLUSDT`
- WHEN the trades list is read
- THEN the operation is listed with the base currency, entry price, exit price and size all absent, its fees paid and other fees present, its PnL as before, and one warning names the pool, the strategy, the allocation and both markets

#### Scenario: Two spellings of one market are not a disagreement

- GIVEN a closed operation opened under `STXUSDT.P` and closed under `STXUSDT`
- WHEN the trades list is read
- THEN all four figures are present and no warning is logged

#### Scenario: An operation that has not netted to zero is not listed

- GIVEN an operation in pool `(bybit, usdt-m, USDT)` that bought 1.000 and sold 0.600, or that has only a BUY
- WHEN the trades list is read
- THEN it is not in the list, and it is counted in the report's open trade count as before

#### Scenario: A close that leaves the net at zero lists once, averaging every closing fill

- GIVEN an operation that bought 1.000 at 100 and whose close filled 0.600 at 110, then 0.400 at 105 in a later order
- WHEN the trades list is read after the second close fill
- THEN it is listed once, with exit price 108 (notional 108 over quantity 1.000), closed at the last fill's instant

#### Scenario: The return is absent when no capital was recorded

- GIVEN a closed operation whose reservation recorded no pool capital at open
- WHEN the trades list is read
- THEN its return and capital at open are absent, its PnL is present, and the other figures are served as usual

### Requirement: Rehearsal Operations Are Listed Only On Request

> **Added 2026-10-04 (owner decision 43, answered 2026-10-03).**

A rehearsal operation is an allocation every one of whose fills carries the
rehearsal fill marker (`REHEARSAL_FILL_ID_PREFIX`, a prefix test), closed under
the same rule as any operation. An operation MUST be wholly real or wholly
rehearsal. An allocation holding fills of both origins (a mixed allocation) is
NOT a rehearsal operation: its real fills MUST be derived exactly as before, its
rehearsal fills MUST NEVER be listed, and the read MUST log one warning naming
the pool, strategy and allocation. An allocation id MUST therefore appear at
most once in the list.

The strategy's trades list MUST serve rehearsal operations only when requested
with `include_rehearsal=true`; the default request MUST serve exactly what it
served before this requirement, with no rehearsal row. Each row MUST say
whether it is a rehearsal row, never absent, false for a real one. A rehearsal
row MUST carry the same derived figures as any row (derived from its own
fills), and those figures MUST be that operation's own and MUST NOT enter any
total (see "Rehearsal Fills Are Excluded From Every Figure"). A rehearsal row's
figures are what the ledger holds, never blanked or substituted: while the
simulated exchange fills every order at a price of 1 with no fee, a rehearsal
row reads entry price 1, exit price 1, fees 0 and PnL 0. How a simulated fill is
priced is outside this requirement (owner decision 45).

Real and rehearsal operations MUST form one list in one order: the close
instant descending, ties broken by allocation id descending, and the paging
cursor (the close instant and the allocation id of the last row served) MUST be
the same with or without rehearsal rows. A cursor minted by a request without
rehearsal rows MUST be a valid position in the list with them, and the reverse.

#### Scenario: The default request lists no rehearsal row

- GIVEN strategy S1 in pool `(bybit, usdt-m, USDT)` has one real closed operation and one closed rehearsal operation
- WHEN S1's trades list is read without `include_rehearsal`
- THEN it holds the real operation only, and its row says it is not a rehearsal row

#### Scenario: A requested list holds both kinds, each marked

- GIVEN the same strategy S1
- WHEN S1's trades list is read with `include_rehearsal=true`
- THEN it holds both operations, the real row marked not rehearsal and the other marked rehearsal, in close-instant order

#### Scenario: A rehearsal row carries the stored numbers

- GIVEN a closed rehearsal operation in pool `(bybit, usdt-m, USDT)` whose fills are at price 1 with no fee, size 12.5
- WHEN the trades list is read with `include_rehearsal=true`
- THEN its row has entry price 1, exit price 1, size 12.5, fees paid 0 and PnL 0, none blanked

#### Scenario: A mixed allocation is never listed as a rehearsal operation

- GIVEN an allocation in pool `(bybit, usdt-m, USDT)` holding a full real round trip and a full rehearsal round trip
- WHEN the trades list is read with `include_rehearsal=true`
- THEN the allocation appears once, derived from its real fills only, as a real row, and one warning names the pool, the strategy and the allocation

#### Scenario: A real and a rehearsal operation closing at the same instant straddle a page edge

- GIVEN a real and a rehearsal operation that close at the same instant, and a page limit of 1
- WHEN the first page and then the page after its cursor are read with `include_rehearsal=true`
- THEN each operation is served exactly once, the higher allocation id first

#### Scenario: A cursor from a list without rehearsal rows resumes the list with them

- GIVEN a cursor taken from the last row of a request made without `include_rehearsal`
- WHEN the next page is read with that cursor and `include_rehearsal=true`
- THEN it resumes at the same position, and no real operation is skipped or repeated

#### Scenario: An operation still open is not listed, rehearsal or not

- GIVEN a rehearsal operation that has only its opening BUY
- WHEN the trades list is read with `include_rehearsal=true`
- THEN it is not in the list

### Requirement: A Rehearsal Operation Says How Its Opening Fills Were Priced

> **Added 2026-10-04 (owner decision 43, answered 2026-10-04; owner decision 45).**

Every rehearsal row MUST carry a fill-price classification, and a real row
MUST carry none. It is derived from stored data alone, by exact decimal
equality between the `price` of the operation's OPENING fills and the price of
the alert that ordered it (the price stored on the signal its reservation
names), and MUST NOT be derived from the averaged entry price:

- `FIXED_ONE`: every opening fill is priced exactly 1 and the alert's price is
  not 1;
- `ALERT`: every opening fill is priced exactly at the alert's price (which
  includes an alert whose price is exactly 1);
- `UNDETERMINED`: anything else, including opening fills of mixed prices and a
  case where the alert's price cannot be read.

The classification MUST NOT depend on the closing fills. It MUST NOT require a
new stored marker. For the rehearsal rows of one page the facts MUST be read in
a single request and not once per row. When the facts of a rehearsal row are
missing, the row MUST read `UNDETERMINED` and the read MUST log one warning
naming the pool, strategy and allocation. When a page holds rehearsal rows
read `UNDETERMINED`, the read MUST log one informational line with their
count.

#### Scenario: Filled at 1 against another alert price is FIXED_ONE

- GIVEN a rehearsal operation in pool `(bybit, usdt-m, USDT)` whose opening fill is priced 1 and whose alert carried 0.4512
- WHEN the trades list is read with `include_rehearsal=true`
- THEN the row's classification is `FIXED_ONE`

#### Scenario: Filled at the alert's price is ALERT, even when the average differs in the last places

- GIVEN a rehearsal operation whose opening fill is priced 0.4512 against an alert of 0.4512, with a quantity small enough that the derived entry price differs from 0.4512 in its last places
- WHEN the trades list is read with `include_rehearsal=true`
- THEN the row's classification is `ALERT`

#### Scenario: An alert priced exactly 1 reads ALERT

- GIVEN a rehearsal operation whose opening fill is priced 1 against an alert of exactly 1
- WHEN the trades list is read with `include_rehearsal=true`
- THEN the row's classification is `ALERT`

#### Scenario: A fill at neither price is UNDETERMINED

- GIVEN a rehearsal operation whose opening fill is priced 0.45 against an alert of 0.4512
- WHEN the trades list is read with `include_rehearsal=true`
- THEN the row's classification is `UNDETERMINED`, and one informational line counts it

#### Scenario: Opening fills at different prices are UNDETERMINED

- GIVEN a rehearsal operation with two opening fills, one priced 1 and one priced 0.4512, against an alert of 0.4512
- WHEN the trades list is read with `include_rehearsal=true`
- THEN the row's classification is `UNDETERMINED`

#### Scenario: Only the opening side decides

- GIVEN a rehearsal operation opened at 1 and closed at its alert's price 0.4512
- WHEN the trades list is read with `include_rehearsal=true`
- THEN the row's classification is `FIXED_ONE`

#### Scenario: Missing facts read UNDETERMINED and are logged

- GIVEN a rehearsal row whose alert price cannot be read
- WHEN the trades list is read with `include_rehearsal=true`
- THEN the row's classification is `UNDETERMINED` and one warning names the pool, the strategy and the allocation

#### Scenario: A real row has no classification

- GIVEN a real closed operation
- WHEN the trades list is read with `include_rehearsal=true`
- THEN its classification is absent

### Requirement: One Operation's Fills Are Read By Strategy And Allocation Together

> **Added 2026-10-04 (owner decision 43, answered 2026-10-04).**

The system MUST read the individual fills of one operation of a strategy, in
the strategy's own pool, by the strategy id AND the allocation id together; the
read MUST NOT be possible by the allocation id alone. For each fill it MUST
return the instant, side, the fill's own price, quantity, fee, fee currency
(upper-cased) and whether it is a rehearsal fill, each never absent. It MUST
NOT average, round, convert or sum, and MUST NOT return the fill's USD rate,
venue order or fill ids, notional or symbol.

- Fills MUST be ordered by instant ascending, ties broken by the row id.
- The read MUST be capped at 200 fills and MUST say whether the cap cut it
  (`truncated`); exactly 200 fills are not truncated, 201 are. A cut MUST log
  one warning naming the strategy, the allocation and the cap.
- The fills of an allocation MUST be returned whatever the spelling of the
  symbol each was written under. An allocation that is still open MUST be
  served. A rehearsal operation's fills MUST each carry the rehearsal flag
  true; a mixed allocation's fills MUST ALL be returned, each with its own flag
  and one warning.
- When no fill carries both the strategy id and the allocation id, the outcome
  MUST be the same "no such operation" whether the allocation does not exist,
  belongs to another strategy, or never had a fill, and one warning MUST name
  the strategy and the allocation.
- A fill of the allocation and strategy that sits in another pool than the
  strategy's MUST refuse the whole read as an integrity failure, not filter
  that fill out.
- The read MUST issue the same number of statements for 1 fill and for 50, and
  MUST write nothing and take no lock.

#### Scenario: A closed operation's fills come in the order they happened

- GIVEN strategy S1 in pool `(bybit, usdt-m, USDT)` has an operation whose later fill was inserted first
- WHEN the operation's fills are read
- THEN they are returned by instant ascending, each with price, quantity, fee and fee currency as stored

#### Scenario: Fills written under two spellings are all returned

- GIVEN an operation opened as `STXUSDT.P` and closed as `STXUSDT`
- WHEN its fills are read by S1 and the allocation id
- THEN the fills of both spellings are returned

#### Scenario: A rehearsal operation's fills each say so

- GIVEN a closed rehearsal operation
- WHEN its fills are read
- THEN every fill carries the rehearsal flag true, and a real operation's fills carry false

#### Scenario: A mixed allocation hides nothing

- GIVEN an allocation holding 2 real fills and 2 rehearsal fills
- WHEN its fills are read
- THEN all 4 are returned, each with its own flag, and one warning names the strategy and the allocation

#### Scenario: The cap cuts at 200 and says so

- GIVEN an operation with 201 fills
- WHEN its fills are read
- THEN the first 200 are returned with `truncated` true and one warning is logged; an operation with exactly 200 returns 200 with `truncated` false

#### Scenario: Another strategy's operation is not readable through this strategy

- GIVEN strategies S1 and S2 in the same pool `(bybit, usdt-m, USDT)`, and S2 has an operation A2
- WHEN S1's fills are read for allocation A2
- THEN the outcome is "no such operation", and no fill of A2 leaves the database

#### Scenario: An unknown, a foreign and an empty allocation are the same outcome

- GIVEN a random allocation id, S2's allocation A2, and a reservation of S1 that never had a fill
- WHEN S1's fills are read for each
- THEN each yields the identical "no such operation" outcome

#### Scenario: A fill in another pool refuses the read

- GIVEN an allocation of S1 with one fill written under pool `(bybit, spot, USDT)` while S1's pool is `(bybit, usdt-m, USDT)`
- WHEN its fills are read
- THEN the read fails as an integrity failure and returns no partial list

#### Scenario: An open allocation's fills are served

- GIVEN an allocation with only its opening BUY
- WHEN its fills are read
- THEN that one fill is returned

#### Scenario: The statement count does not grow with the fills

- GIVEN one operation with 1 fill and another with 50
- WHEN each one's fills are read
- THEN both reads issue the same number of statements
