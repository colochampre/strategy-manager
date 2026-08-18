# Archive Report: Allocation Engine

Archived 2026-08-18. All 99 tasks complete across 7 work units.

## What shipped

The contention engine that replaces Pionex's per-bot capital lock. Every
strategy can now compete for up to 100% of *available* capital in its own
`(venue, settlement_currency)` pool, instead of being confined to a fixed
share reserved for its exclusive use.

| Capability | Spec | Where it lives |
|---|---|---|
| Idempotent TradingView webhook ingress | `signal-ingress` | `signals/` |
| PostgreSQL `SKIP LOCKED` job queue | `job-queue` | `shared/` |
| Serialized capital allocation | `capital-allocation` | `allocation/`, `accounts/`, `strategies/` |
| Reservation execution against the exchange | `trade-execution` | `execution/` |
| Append-only fill ledger | `trade-ledger` | `ledger/` |

## Final verification

- **239 pytest passed**, 0 failed
- `ruff check .` clean
- `mypy src` clean over 93 source files
- Full Alembic chain replays from scratch: `downgrade base` → `upgrade head` → `0008 (head)`

## Work units as delivered

| Unit | Branch | Commit | Runtime-counted lines |
|---|---|---|---|
| 1 — Shared foundation + job queue | `slice/1-shared-foundation` | `be08e57` | 821 |
| 2 — Signal ingress | `slice/2-signal-ingress` | `1cb599a` | 1442 |
| 3 — Strategies + accounts | `slice/3-strategies-accounts` | `073f96a` | 1464 |
| 4 — Allocation core | `slice/4-allocation-core` | `4cfcffb` | 1913 |
| 5 — Execution + ledger | `slice/5-execution-ledger` | `91d1de2` | 2721 |
| 7 — Per-strategy allocation percentage | `slice/7-allocation-percentage` | `1a2ccb0` | 506 |
| 6 — Reservation expiry sweeper | `slice/6-reservation-sweeper` | `41d120e` | 1128 |

Migrations `0001`–`0005`, `0007`, `0008`. `0006` is intentionally unused.

## Decisions worth carrying forward

**The percent caps the ask; the lock and `decide()` govern the grant.**
`allocation_percent` applies to the pool *balance*, not to availability, so a
strategy has a stable absolute ceiling. Sizing against availability would let a
strategy configured at 100% drain an idle pool — reintroducing the per-bot
capital lock from the other direction.

**A concurrency test that passes proves nothing on its own.** The 30-iteration
race test is meaningful only because a negative control runs the same scenario
against a `NoOpAdvisoryLock` and fails outright if 50 lock-free iterations never
over-allocate. It breaches on the first iteration today.

**Anything that lives only in a migration needs a test against a genuinely
migrated database.** `Base.metadata.create_all` builds tables and columns —
never triggers, CHECK constraints or partial indexes. A green suite on a
`create_all` schema says nothing about them, which means production would
enforce rules the tests never exercise. Both the ledger's append-only triggers
and migration `0008`'s CHECK constraints are proven against real
`alembic upgrade head` databases for exactly this reason.

**A row-level trigger does not fire on `TRUNCATE`.** Verified empirically
against live PostgreSQL 17.9: the table emptied with the trigger never invoked.
The append-only ledger therefore carries both a row trigger and a
statement-level `BEFORE TRUNCATE` trigger. One alone leaves a hole big enough
to erase the only table in this system that cannot be reconstructed.

**Code independence does not buy migration independence.** The sweeper depends
on slice 4 alone in code, but the Alembic revision chain is linear and shared,
so it had to be sequenced last and numbered `0008`.

## Deviations from design, accepted and documented

1. Unknown-pool detection happens *inside* the advisory lock, because pool
   existence is only knowable from the balance read and that read must stay
   under the lock.
2. `AllocationResult.skip_reason` is a `str`, not the domain `SkipReason` enum —
   the application layer carries `STRATEGY_DISABLED`, which `decide()` cannot know.
3. `ProcessSignalHandler` reads the pool balance twice: once unlocked to size
   the ask, once inside the lock to compute availability. Safe, because the money
   invariant depends only on the in-lock read. Deliberately *not* fixed by moving
   the percent into `AllocateCapital`, which would couple the allocation engine
   to a per-strategy product policy.

## Known gaps this change does not close

- **REVERSE transitions** route through the CONSUMES branch only; the releasing
  half of a reverse is not separately executed.
- **The sweep chain dies silently** if a `reservation.sweep` job exhausts
  `max_attempts`. Nothing depends on the sweep for correctness — `sum_active`
  already excludes expired reservations — but the bookkeeping stops.
- **`capital_pools.min_order_size` seed values are placeholders** pending real
  Pionex minimums.
- **No leverage-setting endpoint** is documented in the Pionex futures Trade API.
- **COIN-M API coverage is unconfirmed.** Spot and USDT-M are implemented; the
  venue stays an abstraction so COIN-M lands as a later adapter.
- **`FakeExchangeAdapter` is the only exchange adapter.** No real Pionex client
  exists yet, and `DRY_RUN` defaults to true.
