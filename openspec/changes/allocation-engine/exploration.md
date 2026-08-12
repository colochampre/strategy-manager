# Exploration — allocation-engine

Date: 2026-08-12
Status: complete

## Subject

The capital-allocation contention engine. It is the core of the product;
the dashboard, PnL and every timeframe are projections of what it writes.

**Problem:** Pionex signal bots lock a fixed share of account capital per bot,
so strategies that signal alternately leave most capital idle. This engine lets
every strategy compete for up to 100% of *available* capital in its pool.

## Scope

In scope:

- Signal ingress: verify shared secret and TradingView source IP, persist with
  an idempotency key, return 200 fast. No execution inline.
- A PostgreSQL job queue using `FOR UPDATE SKIP LOCKED`.
- The allocation decision, serialized per `(venue, settlement_currency)` with
  `pg_advisory_xact_lock`, inside one transaction covering availability read →
  decision → reservation write.
- The skip-or-partial-fill rule, configurable per strategy.
- The append-only ledger write.
- Execution against a fake in-memory exchange adapter.

Out of scope: the real Pionex HTTP client, frontend, dashboard, PnL queries,
credential encryption UI, COIN-M support.

## Domain model by module

| Module | Domain objects |
| --- | --- |
| `signals` | `WebhookSignal` (id, strategy_id, idempotency_key, raw_payload, received_at, status); `IdempotencyKey` (VO) |
| `strategies` | `Strategy` (id, venue, settlement_currency, enabled); `AllocationPolicy` (VO: skip or partial-fill) |
| `allocation` | `CapitalPool` (aggregate root, keyed by `(venue, settlement_currency)`); `Reservation` (id, strategy_id, pool key, amount, status, expires_at); `AllocationDecision` (VO: full / partial / skip + amount); `LockKey` (VO) |
| `execution` | `ExecutionAttempt` (allocation_id, venue, side, quantity, status, exchange_order_id) |
| `ledger` | `LedgerEntry` — immutable, append-only, no mutators |
| `accounts` | Pool configuration only in this change; the fake adapter is the balance source |

`Money`, `Currency` and `Venue` belong in `shared/domain/` — `allocation`,
`ledger` and `execution` all need them and none should own a type the others
import across module boundaries.

## Ports and adapters

| Port | Owning module | Adapter |
| --- | --- | --- |
| `SignalRepositoryPort` | `signals` | SQLAlchemy repo, unique constraint on `idempotency_key` |
| `WebhookAuthPort` | `signals` | FastAPI dependency over `TRADINGVIEW_SOURCE_IPS` / `webhook_secret` |
| `JobQueuePort` | `shared` | Postgres `FOR UPDATE SKIP LOCKED` adapter |
| `AdvisoryLockPort` | `allocation` | raw SQL `pg_advisory_xact_lock` on the *same* session as the reservation write |
| `ReservationRepositoryPort` | `allocation` | SQLAlchemy repo |
| `PoolBalancePort` | `allocation` (port), `accounts` (impl) | delegates to the fake adapter in this change |
| `StrategyPolicyPort` | `allocation` (port), `strategies` (impl) | in-process adapter; keeps `allocation` domain decoupled |
| `ExchangePort` | `execution` | `FakeExchangeAdapter` only |
| `LedgerRepositoryPort` | `ledger` | SQLAlchemy repo, insert-only |
| `ClockPort` | `shared` | real clock in prod, controllable fake in tests |
| `UsdRateProviderPort` | `shared` | fixed rate in this change |

## Decisions

### Advisory lock keying — VERIFIED against the live database

Use the Postgres-native two-int form:
`pg_advisory_xact_lock(hashtext(venue), hashtext(settlement_currency))`.

Confirmed on PostgreSQL 17.9 in this project's database:

- `pg_advisory_xact_lock` exists as both `(bigint)` and `(integer, integer)`.
- `hashtext(text)` returns `integer`.
- The four real pools produce distinct key pairs:

| venue | currency | k1 | k2 |
| --- | --- | --- | --- |
| spot | USDT | -1433983757 | -1176528098 |
| usdt-m | USDT | -1905269066 | -1176528098 |
| coin-m | BTC | 1937348485 | -1182514593 |
| coin-m | ETH | 1937348485 | 273220054 |

`coin-m/BTC` and `coin-m/ETH` share `k1` and differ in `k2` — the *pair* is the
key, so they do not collide.

Add a startup invariant that enumerates every configured pool and asserts no two
produce the same pair. The domain space is a handful of combinations, so the
exhaustive check is cheap and removes reliance on hash probability.

Note: `hashtext` is an internal, undocumented Postgres function whose algorithm
is not guaranteed stable across major versions. This is acceptable here because
advisory lock keys are never persisted — they only need to be consistent within
a running cluster.

Rejected: a single 64-bit hash of the composite string (no natural collision
guard) and a hand-maintained integer registry (zero collision risk but easy to
forget to update when a pool is added).

### Reservation lifecycle and crash recovery

States: `PENDING` → `SUBMITTED` → `FILLED` | `RELEASED` | `EXPIRED`.

The reservation is written in the same transaction as the availability read and
the advisory lock, so its existence is atomic with the decision. Order
submission happens *after* that transaction commits, to keep the locked
transaction short. The failure window is therefore between "reservation
committed" and "fill recorded".

Every reservation carries `expires_at`. Availability reads exclude reservations
that are expired, so a crashed worker's reservation stops blocking new
allocations without requiring a background process for *correctness*. A sweeper
job is still needed to give orphaned reservations a terminal status for
bookkeeping and observability.

On the queue side, `FOR UPDATE SKIP LOCKED` row locks die with the connection,
so a crashed worker's job is automatically reclaimable — a concrete advantage of
Postgres-as-queue over an external queue needing its own visibility timeout.

**Open decision for design:** the expiry window is a money parameter. Too short
releases capital while a fill is still in flight and risks double-allocation;
too long leaves capital idle, which is the exact problem this project exists to
solve. It must be configurable and explicitly chosen, never hardcoded during
implementation.

### Available capital

`available = live_pool_balance − sum(active, non-expired reservations)`.

Once a reservation becomes `FILLED` it leaves the active sum and the balance has
already moved, so the equation stays self-consistent. This works cleanly with
the fake adapter's synchronous fills.

Flagged for the real Pionex adapter: asynchronous settlement will force a choice
between this and a ledger-derived balance
(`opening_balance + net realized ledger change − active reservations`), which
never trusts a live exchange balance mid-session and is more consistent with the
append-only ledger rule. Not decided here.

### Idempotency

The key must be carried by the signal, not synthesized server-side. Deriving it
from payload content plus a time bucket cannot distinguish a genuine repeated
signal from a TradingView delivery retry, and getting that wrong either drops a
real trade or doubles a position.

Require an explicit field in the alert JSON template, combined server-side with
the strategy id to form the stored key. A missing field is rejected at ingress
with 4xx — still fast, still no execution.

On duplicate: do not persist a second row or enqueue a second job, but return
**200** with the same shape as the original, via
`INSERT ... ON CONFLICT DO NOTHING` followed by a lookup. Returning 4xx would
make TradingView treat a harmless redelivery of an already-accepted alert as a
failure.

### Ledger schema (minimum)

`id, strategy_id, allocation_id, venue, settlement_currency, side, quantity,
price, fee, notional (stored, not recomputed), exchange_order_id, filled_at,
usd_rate_at_fill, created_at`.

No blended USD total column. The USD rate is stored per row because it can never
be backfilled.

**Open decision for design:** append-only is currently a convention enforced by
the absence of domain mutators, which raw SQL can bypass. Choose between
revoking `UPDATE`/`DELETE` from the application's database role, or a
`BEFORE UPDATE OR DELETE` trigger that raises. Either enforces the rule below
the application layer.

### Job queue shape

A shared generic queue port in `shared/`, with an opaque JSON payload the
consumer interprets. `shared/db.py` already states that the queue and the
allocation lock share one connection pool and transaction boundary, and a second
consumer — the reservation sweeper — is already implied, so the reuse pays off
immediately.

Rejected: a queue table owned by `execution`. Lower effort now, but duplicates
the `SKIP LOCKED` plumbing as soon as the sweeper appears.

## Testing the race

A concurrency test that passes once proves nothing. The plan:

1. Launch N concurrent allocation use-case calls on separate sessions via
   `asyncio.gather`, against one pool, with requested amounts summing to more
   than available capital.
2. Assert the **invariant**, not a winner: total committed reservations never
   exceed the pool balance, and every request is accounted for as full, partial
   or skip.
3. **Negative control:** rerun with `AdvisoryLockPort` stubbed to a no-op and
   assert the invariant *breaks*. Without this, a vacuously-passing test is
   indistinguishable from a working lock. This is the most important test in the
   change.
4. Repeat the positive test across many iterations, not once.
5. Optionally pin start order with an `asyncio.Event` barrier for a deterministic
   winner/loser assertion.

This requires a live PostgreSQL connection. Advisory locks are a server feature
with no meaningful fake. The database is available as of 2026-08-12, so this is
not blocked.

## Risks

1. The reservation expiry window is an unresolved money-risk parameter.
2. Cross-module coupling: `allocation` needs data from `strategies` and
   `accounts`. Wire these as application-layer ports, never direct domain
   imports, or the engine becomes untestable in isolation.
3. The idempotency contract depends on user-authored TradingView alert
   templates. A missing field must fail loudly and be documented clearly.
4. Available-capital semantics will need revisiting when fills stop being
   synchronous.

## Next

`sdd-propose`.
