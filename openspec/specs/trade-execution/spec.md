# Trade Execution Specification

## Purpose

Submits a committed reservation as an order against a pool's venue via `ExchangePort`, re-verifying the reservation is still valid immediately before submission. In this change the only registered adapter is `FakeExchangeAdapter`.

## Requirements

### Requirement: Reservation-Bound Submission

Every execution attempt MUST reference exactly one reservation's `allocation_id` and MUST submit against that reservation's pool `(venue, settlement_currency)` via `ExchangePort`.

#### Scenario: Submission carries the allocation id

- GIVEN a committed reservation for pool `(spot, USDT)` with `allocation_id = A1`
- WHEN the worker submits the order
- THEN the resulting `ExecutionAttempt` references `allocation_id = A1` and pool `(spot, USDT)`

### Requirement: Pre-Submit Expiry Re-Check

Immediately before submitting an order, the worker MUST re-check that the bound reservation is non-expired. If it has expired, the worker MUST abort submission and transition the reservation to `RELEASED`, never submitting.

#### Scenario: Reservation still valid at submit time

- GIVEN a reservation for pool `(usdt-m, USDT)` with `expires_at` still in the future
- WHEN the worker performs the pre-submit check
- THEN submission proceeds via `ExchangePort`

#### Scenario: Reservation expired at submit time

- GIVEN a reservation for pool `(usdt-m, USDT)` whose `expires_at` has just passed
- WHEN the worker performs the pre-submit check
- THEN the worker MUST NOT submit an order and MUST transition the reservation to `RELEASED`

### Requirement: DRY_RUN Safety

`DRY_RUN` MUST default to `true`. The composition root MUST fail startup if `dry_run=false` is configured while no real (non-fake) `ExchangePort` adapter is registered. Additionally: the automatic orphan close and the continuation's open MUST route through `FakeExchangeAdapter` under DRY_RUN, and no test exercising them may require a real credential. Under DRY_RUN a fake venue position reader MUST make the REAL branch reachable for rehearsal.

#### Scenario: Default startup is DRY_RUN

- GIVEN no explicit `DRY_RUN` override
- WHEN the application starts
- THEN `DRY_RUN` is `true` and only `FakeExchangeAdapter` is used for any submission

#### Scenario: Unsafe live configuration fails startup

- GIVEN `dry_run=false` is configured and no real exchange adapter is registered
- WHEN the application starts
- THEN startup MUST fail rather than allow silent trading

### Requirement: Definitive Close Rejection Recording

A definitive venue rejection of a close in pool `(exchange, venue, settlement_currency)` MUST record the attempt FAILED, MUST log exactly one ERROR naming strategy, symbol, allocation, attempt and the venue's error, and MUST NOT be reported as executed. A timing gap where the fill is simply not recorded yet MUST keep retrying as today.

### Requirement: Retryable Close, Single In-Flight Attempt

In pool `(exchange, venue, settlement_currency)`, at most ONE close attempt per allocation MAY be SUBMITTED at any time. A FAILED, FILLED or ABORTED_EXPIRED attempt MUST NOT prevent a later close on that allocation.

#### Scenario: Retry after a failed close

- One FAILED close on A1 → a new close is recorded

#### Scenario: A residual after a partial fill can still be closed

- A1's close FILLED leaving a non-zero residual → a new close for the residual is recorded

#### Scenario: No two closes in flight

- Two concurrent close attempts on A1 → at most one is SUBMITTED

#### Scenario: A retried close is not re-sent

- A close for A1 already SUBMITTED or FILLED → a retry does not place a second close order

### Requirement: Reverse Completion

A reverse in pool `(exchange, venue, settlement_currency)` on a market that can hold the new side MUST end FLIPPED: the close half settles first, then the open half is placed. A reverse whose new side cannot be held (a short on spot) keeps today's behaviour and reports the unexecuted half.

#### Scenario: Ends flipped

- S1 long ETHUSDT under A1 in `(bybit, usdt-m, USDT)`, reverse → A1 closed, and only after that close fills a short is opened

#### Scenario: The reverse's own position is not an orphan

- The guard, run for the reverse's open half after its close fills, sees A1 at zero net and does not classify it

### Requirement: Fill Recording

A successful execution against pool `(venue, settlement_currency)` MUST record a fill through `FillRecorderPort`, carrying the reservation's `allocation_id` and strategy id.

#### Scenario: Successful fill is recorded

- GIVEN `ExchangePort` reports a successful fill for pool `(coin-m, BTC)` under `allocation_id = A2`
- WHEN the worker processes the result
- THEN a fill is recorded via `FillRecorderPort` carrying `allocation_id = A2`, the owning `strategy_id`, and pool `(coin-m, BTC)`
### Requirement: Execution Attempt Origin
`execution_attempts` MUST carry `origin` (`SYSTEM`|`VENUE`), NOT NULL,
defaulted `SYSTEM` for pre-existing rows. Downgrading the migration MUST
refuse while any VENUE-origin attempt exists, rather than deleting trading
history.

- GIVEN a new system-submitted attempt, WHEN recorded, THEN `origin='SYSTEM'`.
- GIVEN a VENUE-origin attempt exists, WHEN the migration is downgraded, THEN it refuses.

### Requirement: Venue-Origin Attempt Is Constructed Already Filled
A VENUE-origin attempt MUST be constructed directly in status FILLED; it MUST
NEVER pass through SUBMITTED and MUST NEVER be sent to `ExchangePort`, because
the fill already happened at the venue.

- GIVEN an approved booking, WHEN the attempt is constructed, THEN it is FILLED immediately and no order is submitted to any exchange.

### Requirement: Venue-Origin Attempt Client Order ID Synthesis (added during apply, 2026-09-23/24)
A VENUE-origin attempt's `client_order_id` MUST be synthesized deterministically as `vnu:{exchange}:fill:{earliest_exchange_fill_id}`, under the canonical fill ordering, NEVER the venue order ID. One venue order can fill across two scans and so yield two bookings; keyed on the order ID, both would share one `client_order_id`, and the second approval would collide and be read as a harmless replay, so that close could never be booked. A fill is recorded at most once, so the earliest unrecorded fill names exactly one booking. A replay of the same proposal still collides, because the ID is frozen when the proposal is prepared.

- GIVEN multiple fills combined into one VENUE-origin attempt, WHEN the attempt is recorded, THEN the `client_order_id` uses the earliest fill's ID, not any venue order ID.
- GIVEN one venue order whose fills are booked by two separate proposals, WHEN both are approved, THEN the two attempts carry different `client_order_id`s.
