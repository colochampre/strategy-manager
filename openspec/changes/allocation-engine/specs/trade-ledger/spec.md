# Trade Ledger Specification

## Purpose

The append-only, database-enforced record of every fill. It is the source of truth: positions, PnL and every dashboard timeframe are read-only projections over it. No row is ever mutated or deleted once written.

## Requirements

### Requirement: Ledger Row Content

Every ledger row MUST carry `strategy_id`, `allocation_id`, the settlement-currency pool (`venue`, `settlement_currency`), and `usd_rate_at_fill`, in addition to fill details (`side`, `quantity`, `price`, `fee`, `notional`, `exchange_order_id`, `filled_at`).

#### Scenario: Fill for pool (usdt-m, USDT) is recorded in full

- GIVEN a confirmed fill for pool `(usdt-m, USDT)` under `allocation_id = A3` and `strategy_id = S1`
- WHEN the ledger entry is written
- THEN the row carries `strategy_id = S1`, `allocation_id = A3`, `venue = usdt-m`, `settlement_currency = USDT`, and a stored `usd_rate_at_fill`

### Requirement: Append-Only Enforcement

The database MUST enforce immutability below the application layer. A `BEFORE UPDATE OR DELETE ... FOR EACH ROW` trigger and a `BEFORE TRUNCATE ... FOR EACH STATEMENT` trigger, both raising an exception, MUST be installed on the ledger table and MUST fire even for a superuser connection.

#### Scenario: UPDATE is rejected

- GIVEN an existing ledger row for pool `(spot, USDT)`
- WHEN a raw `UPDATE` targets that row
- THEN the database MUST raise an exception and the row MUST remain unchanged

#### Scenario: DELETE is rejected

- GIVEN an existing ledger row for pool `(coin-m, ETH)`
- WHEN a raw `DELETE` targets that row
- THEN the database MUST raise an exception and the row MUST remain present

#### Scenario: TRUNCATE is rejected

- GIVEN the ledger table contains rows across multiple pools
- WHEN a raw `TRUNCATE` is issued against the ledger table
- THEN the database MUST raise an exception and no rows MUST be removed

### Requirement: Native Settlement-Currency Reporting

Each ledger row's monetary fields MUST be recorded in that row's own pool's native settlement currency. No blended cross-pool USD total MAY be stored or derived at write time.

#### Scenario: Distinct pools keep distinct native currencies

- GIVEN one fill for pool `(spot, USDT)` and one fill for pool `(coin-m, BTC)`
- WHEN both ledger entries are written
- THEN the `(spot, USDT)` row's amounts are in USDT, the `(coin-m, BTC)` row's amounts are in BTC, and no combined total row is written
