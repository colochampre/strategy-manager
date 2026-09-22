# Capital Allocation Specification

## Purpose

The contention engine. Every capital pool is keyed by `(venue, settlement_currency)`. This module decides, per pool, how much of a signal's requested amount to reserve, serialized so concurrent signals against the same pool can never over-commit it, while distinct pools proceed concurrently.

## Requirements

### Requirement: Pool Availability

For a given pool `(venue, settlement_currency)`, available capital MUST be computed as the live pool balance minus the sum of that pool's active, non-expired reservations.

#### Scenario: Availability excludes expired reservations

- GIVEN pool `(spot, USDT)` has a balance of 1000 USDT and one reservation of 200 USDT that is past `expires_at`
- WHEN available capital is computed for `(spot, USDT)`
- THEN the expired reservation is excluded and available capital is 1000 USDT

### Requirement: Serialized Allocation Decision

The system MUST serialize the availability read, allocation decision, and reservation write for a pool inside one database transaction, using `pg_advisory_xact_lock(hashtext(venue), hashtext(settlement_currency))` as the pool's lock key.

#### Scenario: One transaction per decision

- GIVEN a signal requests capital from pool `(usdt-m, USDT)`
- WHEN the allocation use case runs
- THEN the availability read, decision, and reservation write all occur inside a single transaction holding the pool's advisory lock

### Requirement: Concurrency Safety Invariant

Under concurrent allocation requests against the same pool, the sum of that pool's committed reservations MUST NEVER exceed the pool's available balance. Every request MUST resolve to full, partial, or skip.

#### Scenario: Concurrent requests never over-commit a pool

- GIVEN pool `(spot, USDT)` has 1000 USDT available and two concurrent signals each request 700 USDT
- WHEN both allocation requests run concurrently
- THEN the sum of committed reservations for `(spot, USDT)` never exceeds 1000 USDT, and each request resolves to full, partial, or skip

#### Scenario: Advisory lock disabled breaks the invariant (negative control)

- GIVEN the advisory lock is stubbed to a no-op for pool `(spot, USDT)`
- WHEN the same concurrent-request scenario runs
- THEN the invariant is observed to break, proving the lock is what enforces it

### Requirement: Pool Isolation

Distinct pools MUST allocate concurrently and MUST NEVER fund each other. No cross-pool blended total may be read or written.

#### Scenario: Distinct pools allocate without blocking each other

- GIVEN pool `(spot, USDT)` and pool `(coin-m, BTC)` each receive a signal at the same time
- WHEN both allocation requests run concurrently
- THEN neither pool's transaction blocks on the other's advisory lock, and each pool's reservation draws only from its own balance

### Requirement: Strategy Policy Resolution

For a contended signal, the owning strategy's `AllocationPolicy` MUST resolve the outcome to exactly one of: full allocation, partial allocation, or skip.

#### Scenario: Partial-fill policy under contention

- GIVEN a strategy configured for partial-fill and its pool has less available capital than requested
- WHEN the signal is allocated
- THEN the reservation is created for the available amount and the decision is recorded as partial

#### Scenario: Skip policy under contention

- GIVEN a strategy configured for skip-only and its pool has less available capital than requested
- WHEN the signal is allocated
- THEN no reservation is created and the decision is recorded as skip

### Requirement: Reservation Expiry

Every reservation MUST carry an `expires_at` derived from a configurable TTL (`Settings.reservation_ttl_seconds`, default 30 seconds). An expired reservation MUST NEVER authorize capital reuse.

#### Scenario: Pre-submit re-check aborts an expired reservation

- GIVEN a reservation for pool `(usdt-m, USDT)` whose `expires_at` has passed by the time the worker is about to submit
- WHEN the worker performs its immediate pre-submit expiry check
- THEN the worker MUST abort submission and transition the reservation to `RELEASED`

#### Scenario: Crashed worker's reservation stops blocking its pool

- GIVEN a worker holding a `PENDING` reservation for pool `(spot, USDT)` crashes before submitting
- WHEN that reservation's `expires_at` passes
- THEN subsequent availability reads for `(spot, USDT)` exclude it, and it no longer blocks new allocations

### Requirement: Startup Lock-Key Collision Invariant

At startup, the system MUST enumerate every configured pool and verify that no two pools produce the same `(hashtext(venue), hashtext(settlement_currency))` pair.

#### Scenario: Startup passes with distinct pool keys

- GIVEN the configured pools are `(spot, USDT)`, `(usdt-m, USDT)`, `(coin-m, BTC)`, `(coin-m, ETH)`
- WHEN the application starts
- THEN the collision check passes because every pair is distinct

#### Scenario: Startup fails on a detected collision

- GIVEN two configured pools resolve to the same lock-key pair
- WHEN the application starts
- THEN startup MUST fail before accepting traffic

### Requirement: On-Demand Balance Refresh Before Allocation

Before acquiring the advisory lock of pool `(exchange, venue, settlement_currency)` for an opening signal, the system MUST attempt to refresh that pool's balance from the venue, bounded by its own timeout shorter than the venue client's. It MUST NEVER do so at webhook ingress. The in-lock read MUST remain a local read. The periodic `balance.sync` MUST keep running as a heartbeat.

#### Scenario: A dead periodic sync does not lose a signal

- GIVEN pool `(binance, usdt-m, USDT)` whose `balance.sync` has not run for 3 days AND a reachable venue
- WHEN an opening signal is processed
- THEN it is sized from the freshly refreshed balance

#### Scenario: Refresh fails, snapshot fresh

- GIVEN pool `(bybit, usdt-m, USDT)` with a snapshot 40s old
- WHEN the refresh times out
- THEN it proceeds on the snapshot AND logs a WARNING naming the pool, the reason and the snapshot's age

#### Scenario: Refresh fails, snapshot stale

- GIVEN pool `(bybit, usdt-m, USDT)` with a snapshot 120s old
- WHEN the refresh times out
- THEN the signal is refused AND an ERROR is logged naming the pool, the signal, the strategy and the symbol

### Requirement: Existing-Position Guard

Before allocating for an opening signal, the system MUST determine from the LEDGER — never from TradingView's reported position — whether the owning strategy holds a non-zero net position on the signal's symbol within pool `(exchange, venue, settlement_currency)`. The check MUST be per strategy, not per pool. Symbol spellings (`STXUSDT`, `STXUSDT.P`, `STXUSDT_PERP`) MUST be treated as the same market.

#### Scenario: Strategy holds nothing

- GIVEN strategy S1 holds nothing on ETHUSDT in `(bybit, usdt-m, USDT)`
- WHEN S1 opens ETHUSDT
- THEN allocation proceeds exactly as today

#### Scenario: A different strategy holds the symbol

- GIVEN S2 holds a non-zero net on ETHUSDT in `(bybit, usdt-m, USDT)` AND S1 holds nothing
- WHEN S1 opens ETHUSDT
- THEN allocation proceeds; another strategy's position MUST NOT block it

#### Scenario: Spelling does not hide a holding

- GIVEN S1's ledger rows for the market are recorded as `STXUSDT.P`
- WHEN S1 opens `STXUSDT`
- THEN the holding is found

#### Scenario: A close still in flight is not an orphan

- GIVEN S1 holds a position on ETHUSDT whose close is still SUBMITTED
- WHEN S1 opens ETHUSDT
- THEN the open is deferred until that close settles, not classified as an orphan and not refused

#### Scenario: A divergent holding is classified

- GIVEN S1 holds a non-zero net on ETHUSDT with nothing in flight
- WHEN S1 opens ETHUSDT
- THEN the holding is classified per Orphan Classification before any allocation

### Requirement: Orphan Classification

Let `L_S` be the strategy's ledger net on the symbol (non-zero), `L_P` the pool's ledger net on the symbol summed over every strategy, `O = L_P − L_S`, and `V` the venue's reported net for the account. Comparison MUST be exact Decimal. The system MUST classify as **REAL** iff `V == L_P`; **GHOST** iff `V ≠ L_P` and `V == O`; **AMBIGUOUS** otherwise, and also whenever the venue read fails or times out.

#### Scenario: Real, single strategy

- `(binance, usdt-m, USDT)`: L_S +0.5, O 0, V +0.5 → REAL

#### Scenario: Ghost, closed by hand or liquidated

- L_S +0.5, O 0, V 0 → GHOST

#### Scenario: Partial liquidation is ambiguous, not real

- L_S +0.5, O 0, V +0.3 → AMBIGUOUS. A close sized for 0.5 MUST NOT be sent

#### Scenario: Real with a second strategy on the symbol

- L_S +0.5, O +0.2, V +0.7 → REAL

#### Scenario: Ghost with a second strategy

- L_S +0.5, O +0.2, V +0.2 → GHOST

#### Scenario: Both legs gone

- L_S +0.5, O +0.2, V 0 → AMBIGUOUS

#### Scenario: Opposite sides netted in one-way mode

- L_S +0.5, O −0.5, V 0 → REAL; V −0.5 → GHOST

#### Scenario: Venue unreachable

- The read fails → AMBIGUOUS

### Requirement: Ghost and Ambiguous Refusal

GHOST or AMBIGUOUS in pool `(exchange, venue, settlement_currency)` MUST refuse the opening signal, MUST NOT attempt any close, and MUST NOT book the venue's close into the ledger. A WARNING MUST name the strategy, symbol, allocation(s) and the nets compared.

### Requirement: Real-Orphan Resolution via Close-Then-Open

REAL in pool `(exchange, venue, settlement_currency)` MUST close every allocation of the strategy with a non-zero net on that symbol, and the opening signal MUST be allocated only after every such close has settled.

#### Scenario: Opened only after settlement

- GIVEN REAL for S1 on ETHUSDT under A1 in `(bybit, usdt-m, USDT)`
- WHEN processed
- THEN A1 is closed AND no opening attempt for the signal exists while A1's close is SUBMITTED AND the open follows its fill

#### Scenario: A rejected orphan close never triggers the open

- GIVEN REAL for S1 under A1
- WHEN A1's close is definitively rejected
- THEN the open is never allocated AND the failure is recorded per Definitive Close Rejection Recording
