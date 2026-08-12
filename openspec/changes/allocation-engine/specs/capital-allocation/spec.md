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
