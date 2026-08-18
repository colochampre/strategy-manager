# Proposal: Allocation Engine

## Intent

Pionex signal bots lock a fixed slice of capital per bot, so alternating
strategies leave most of the account idle. Build the contention engine that lets
every strategy compete for up to 100% of *available* capital in its own
settlement-currency pool. Everything later (dashboard, PnL, timeframes) is a
projection of what this engine writes.

## Scope

### In Scope

- Webhook ingress: secret + source-IP check, persist with idempotency key, 200 fast, no inline execution.
- Postgres job queue (`FOR UPDATE SKIP LOCKED`) in `shared/`.
- Allocation transaction: `pg_advisory_xact_lock(hashtext(venue), hashtext(currency))` → availability read → decision → reservation write, one transaction.
- Skip-or-partial-fill rule, per strategy.
- Reservation lifecycle `PENDING→SUBMITTED→FILLED|RELEASED|EXPIRED` + expiry sweeper.
- Append-only ledger write, DB-enforced.
- Execution against `FakeExchangeAdapter` only.
- First Alembic migration; startup pool lock-key collision invariant.

### Out of Scope

Real Pionex HTTP client, frontend/dashboard, PnL queries, credential-encryption UI, COIN-M venue adapter, per-strategy TTL override, dedicated least-privilege DB role, ledger-derived balance semantics.

## Capabilities

### New Capabilities

- `signal-ingress`: authenticated webhook, idempotency contract, enqueue-only.
- `job-queue`: SKIP LOCKED claim/ack/retry, crash reclaim.
- `capital-allocation`: pool availability, serialized decision, reservation lifecycle and expiry.
- `trade-execution`: reservation-bound order submission via `ExchangePort`.
- `trade-ledger`: append-only fill records with per-row `usd_rate_at_fill`.

### Modified Capabilities

None — `openspec/specs/` is empty.

## Approach

Follow the exploration's domain model and port map. `Money`/`Currency`/`Venue`
live in `shared/domain/` — the only types crossing module lines.

**Resolved decision 1 — reservation TTL.** Default **30s**, via
`Settings.reservation_ttl_seconds` (env `RESERVATION_TTL_SECONDS`) in
`shared/config.py`; the use case passes it in, the domain never reads config.
30s is 10x the TradingView 3s budget and covers one Pionex round-trip plus a
retry, while capping idle capital under a minute. Paired hard rule: the execution
worker MUST re-check its reservation is non-expired immediately before
submitting, and MUST abort to `RELEASED` if expired. This makes the failure mode
a rare skipped signal, never a double-allocated pool.

**Resolved decision 2 — append-only enforcement.** Use a
`BEFORE UPDATE OR DELETE ... FOR EACH ROW` trigger raising an exception, plus a
`BEFORE TRUNCATE` statement trigger, shipped in the first migration. Reason:
the app runs as `postgres`, and superusers bypass `REVOKE` entirely, so the
role-based option is a no-op today and would give false assurance. Triggers still
fire for superusers. A dedicated role + `REVOKE` is deferred as later
defence-in-depth.

**Resolved decision 3 — cross-module coupling.** One rule: **the consumer
declares the port, the provider owns the adapter, `main.py` binds them.**
Cross-module dependencies are application→application via `Protocol` only; no
`domain`→`domain` import ever crosses a module. Concrete ports:

| Port | Declared in | Adapter in |
| --- | --- | --- |
| `StrategyPolicyPort` | `allocation/application` | `strategies/application` |
| `PoolBalancePort` | `allocation/application` | `accounts/application` |
| `AdvisoryLockPort` | `allocation/application` | `allocation/infrastructure` |
| `ReservationRepositoryPort` | `allocation/application` | `allocation/infrastructure` |
| `FillRecorderPort` | `execution/application` | `ledger/application` |
| `JobQueuePort`, `ClockPort`, `UsdRateProviderPort` | `shared` | `shared/infrastructure` |

`LedgerRepositoryPort` stays internal to `ledger`; `execution` never sees it.
Port DTOs are defined by the consumer, so no provider domain type leaks.

## Non-negotiable Rule Impact

| Rule | Impact |
| --- | --- |
| **`DRY_RUN`** | Default stays `true`. Only `FakeExchangeAdapter` exists, so the whole change is DRY_RUN-safe by construction. Composition root MUST fail startup if `dry_run=false` with no real adapter registered, rather than trading silently. No test needs a credential. |
| **Idempotency keys** | Established here. Stored key = `(strategy_id, client field)` with a DB unique constraint; missing field → 4xx at ingress; duplicate → `INSERT ... ON CONFLICT DO NOTHING` + lookup → **200**, no second row, no second job. Reservation and ledger rows carry `allocation_id` so a replayed job cannot double-fill. |
| **Capital-pool isolation** | Pools keyed `(venue, settlement_currency)`. Every reservation, availability read and ledger row carries the pool key; the advisory lock is per pool pair, so distinct pools allocate concurrently and can never fund each other. No blended cross-pool total is written or read. |

## Affected Areas

| Area | Impact | Description |
| --- | --- | --- |
| `backend/src/strategy_manager/shared/` | Modified | `domain/` VOs, ports, queue adapter, `reservation_ttl_seconds` |
| `.../signals/`, `strategies/`, `allocation/`, `execution/`, `ledger/`, `accounts/` | New | All three layers per module; currently empty `__init__.py` only |
| `backend/migrations/versions/` | New | First migration: all tables, indexes, unique constraints, append-only triggers |
| `backend/src/strategy_manager/main.py` | Modified | Composition root, router, startup invariants |
| `backend/tests/` | New | Unit + live-Postgres integration, incl. race test with negative control |

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Advisory lock silently ineffective; concurrency test passes vacuously | Med | Mandatory negative control: stub `AdvisoryLockPort` to a no-op and assert the invariant *breaks*. Repeat the positive test over many iterations. |
| 30s TTL wrong for real latency | Med | Env-configurable; worker pre-submit expiry re-check makes the failure direction "skip", not "double-allocate". Revisit with the real adapter. |
| `hashtext` unstable across PG major versions | Low | Keys are never persisted; exhaustive startup collision check over all configured pools. |
| Available-capital equation breaks on async settlement | Med | Explicitly deferred; `PoolBalancePort` isolates the swap to ledger-derived balance. |
| User-authored TradingView template omits the idempotency field | High | Fail loudly with 4xx; document the exact required alert JSON template. |
| Size: work far exceeds the 800-line review budget | High | Chained PRs, see Delivery. |

## Delivery

Estimated **~2,600–3,400 changed lines** (7 modules from empty skeletons, first
migration, and `strict_tdd: true` roughly doubling code with tests).

**Chaining is needed: Yes.** Six stacked slices, each independently
deployable, each shipping its own tests:

| # | Slice | ~Lines |
| --- | --- | --- |
| 1 | `shared/domain` VOs, `ClockPort`, `UsdRateProviderPort`, `JobQueuePort` + SKIP LOCKED adapter, migration `0001` (jobs table) | 600 |
| 2 | Signal ingress: auth, idempotency, `ON CONFLICT DO NOTHING` repo, enqueue, signals table | 550 |
| 3 | `strategies` + `accounts`: `Strategy`, `AllocationPolicy`, pool config, the two read ports, startup collision invariant | 450 |
| 4 | Allocation core: `CapitalPool`, `Reservation`, `AllocationDecision`, `LockKey`, advisory lock adapter, `AllocateCapital`; race test + negative control | 800 |
| 5 | Execution + ledger: `ExecutionAttempt`, `FakeExchangeAdapter`, `FillRecorderPort`, ledger table + append-only triggers, worker | 700 |
| 6 | Reservation expiry sweeper and terminal statuses | 300 |

PR #1 targets the tracker branch; each later PR targets the previous slice's
branch. Slices 1–3 have no money-path behaviour, so they can land ahead of the
allocation decision.

## Rollback Plan

- This ships the **first** migration (`alembic_version` currently holds 0 rows).
  Every revision MUST implement a real `downgrade()` — no `pass` — dropping its
  tables, indexes, triggers and the trigger function. `alembic downgrade base`
  returns the database to zero revisions.
- **Ledger cutoff rule:** once a single live fill exists, `downgrade` of the
  ledger revision is forbidden — an append-only ledger cannot be reconstructed.
  From that point rollback is a code revert with the schema left in place.
- **Safe partial rollback:** ingress is decoupled from execution, so stopping the
  worker halts all trading while signals keep accumulating durably. This is the
  first response to any incident, before any schema action.
- Chained slices revert in reverse order (6→1); each slice's revert leaves the
  previous slice green.
- `DRY_RUN=true` is the standing kill switch and needs no rollback.

## Dependencies

- Live PostgreSQL 17.9 `strategy_manager` (verified reachable 2026-08-12) —
  advisory locks and `SKIP LOCKED` have no meaningful fake.
- Documented TradingView alert JSON template carrying the idempotency field.

## Success Criteria

- [ ] Concurrent allocations against one pool never exceed its balance; every request resolves to full, partial or skip.
- [ ] The negative-control test fails the invariant when the advisory lock is stubbed out.
- [ ] Ingress returns 200 well under 3s and never executes a trade.
- [ ] A duplicate webhook creates no second signal row and no second job, and returns 200.
- [ ] Raw `UPDATE`, `DELETE` and `TRUNCATE` against `ledger_entries` all raise.
- [ ] `alembic upgrade head` then `downgrade base` is clean and repeatable.
- [ ] Full suite, `ruff check .` and `mypy src` green with `DRY_RUN=true` and no credentials.
