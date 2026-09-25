# Performance Reporting Specification

> **Revised 2026-09-24.** Realigned with design findings and owner decisions:
> F1 (pool capital comes from the balance read made INSIDE the allocation lock),
> F2 (rehearsal fills are excluded by a named marker), F3 (only
> settlement-currency fees are subtracted; nothing is converted), F4 (pairs are
> keyed by `market_key()` per allocation), decision 16 (UTC day and month
> boundaries) and decision 17 (the return formula in design §11 is confirmed).

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
Every read model in this domain MUST exclude those fills. The constant MUST be
the single definition used both by the fake exchange that mints the ids and by
the reads that exclude them.

#### Scenario: A rehearsal fill never reaches a figure

- GIVEN pool `(bybit, usdt-m, USDT)` has a settled rehearsal allocation whose fills carry `fake-fill-` ids, and one real closed allocation
- WHEN any performance read model is requested for that pool
- THEN only the real allocation is counted, in trades, PnL, the curve, the grid and the ranges

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
zero PnL) rather than an error.

#### Scenario: An empty ledger yields empty performance data

- GIVEN pool `(bybit, usdt-m, USDT)` has no ledger entries
- WHEN any performance read model is requested for that pool
- THEN it returns an empty result with no error raised

#### Scenario: A ledger holding only rehearsal fills yields empty performance data

- GIVEN pool `(bybit, usdt-m, USDT)` holds only fills whose ids start with `fake-fill-`
- WHEN any performance read model is requested for that pool
- THEN it returns the same empty result, with no error raised
