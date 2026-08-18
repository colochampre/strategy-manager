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

`DRY_RUN` MUST default to `true`. The composition root MUST fail startup if `dry_run=false` is configured while no real (non-fake) `ExchangePort` adapter is registered.

#### Scenario: Default startup is DRY_RUN

- GIVEN no explicit `DRY_RUN` override
- WHEN the application starts
- THEN `DRY_RUN` is `true` and only `FakeExchangeAdapter` is used for any submission

#### Scenario: Unsafe live configuration fails startup

- GIVEN `dry_run=false` is configured and no real exchange adapter is registered
- WHEN the application starts
- THEN startup MUST fail rather than allow silent trading

### Requirement: Fill Recording

A successful execution against pool `(venue, settlement_currency)` MUST record a fill through `FillRecorderPort`, carrying the reservation's `allocation_id` and strategy id.

#### Scenario: Successful fill is recorded

- GIVEN `ExchangePort` reports a successful fill for pool `(coin-m, BTC)` under `allocation_id = A2`
- WHEN the worker processes the result
- THEN a fill is recorded via `FillRecorderPort` carrying `allocation_id = A2`, the owning `strategy_id`, and pool `(coin-m, BTC)`
