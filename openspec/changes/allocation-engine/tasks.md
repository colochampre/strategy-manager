# Tasks: Allocation Engine

> Size note: the skill's 530-word tasks budget is deliberately exceeded, for the
> same reason recorded in design.md — six slices, one gated, each needing its
> own RED/GREEN pairs, explicit race-test and negative-control tasks, and full
> work-unit evidence per the launch brief. Recorded as a risk, not an oversight.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~2,600–3,400 total (per-slice: 600 / 550 / 450 / 800 / 700 / 300) |
| Session review budget override | **2000 lines/PR from slice 5 onward** (raised by maintainer decision 2026-08-18; was 1600 from slice 3, 800 before that) |
| 400-line budget risk | High (every slice exceeds the skill's literal 400-line default; kept for guard matching) |
| Why the budget was raised (800 → 1600) | The per-slice estimates count **production** lines, but `strict_tdd: true` roughly doubles each slice with its tests. Measured: slice 1 = 821 changed lines, slice 2 = 1442. Both breached an 800 ceiling that was never calibrated for TDD. |
| Why the budget was raised again (1600 → 2000) | Slice 4 landed at 1913 runtime-counted lines — 623 production, 78 migration, 1138 tests, the rest artifacts. The overage is entirely mandated coverage: `decide()`'s 6 ordered rules with 7 edge cases, the `Reservation` transition matrix, the TXN-A integration test, the 30-iteration race test and the 50-iteration negative control. Trimming to fit 1600 would have cut the highest-value tests in the change. Accepted as `size:exception`, budget raised so slice 5 does not block on the same miscalibration. |
| 2000-line budget risk | Low for slice 6; Medium for slice 5 (execution + ledger, grown by tasks 5.16–5.17, and the append-only ledger needs both a row trigger and a statement-level `BEFORE TRUNCATE` trigger with guard tests for each) |
| Measured per slice | Runtime-counted, includes artifacts: slice 1 = 821, slice 2 = 1442, slice 3 = 1464, slice 4 = 1913, slice 5 = 2721, slice 7 = 506 (`git diff --stat`: 462 insertions + 44 deletions across 15 files) |
| Chained PRs recommended | Yes |
| Suggested split | 6 slices, PR 1 → PR 6, matching the proposal's delivery table |
| Delivery strategy | auto-chain |
| Chain strategy | feature-branch-chain |

```text
Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High
```

**Threat matrix**: N/A — this change routes no shell commands, subprocess,
VCS/PR automation or executable-file classification (per design.md). No
threat-matrix RED tasks are required.

### Suggested Work Units

| Unit | Goal | Branch (base) | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 1 | Shared domain + job queue | `slice/1-shared-foundation` (base `tracker/allocation-engine`) | `cd backend && uv run pytest tests/shared -q` | Live PG `strategy_manager_test`, `alembic upgrade head` on `0001` [DB] | `alembic downgrade base`; delete `shared/{domain,application,infrastructure}` additions |
| 2 | Signal ingress | `slice/2-signal-ingress` (base `slice/1-shared-foundation`) | `cd backend && uv run pytest tests/signals -q` | Live PG, `0002` applied; `httpx.AsyncClient` for router tests [DB] | `alembic downgrade 0001`; remove `signals/` package and router mount |
| 3 | Strategies + accounts | `slice/3-strategies-accounts` (base `slice/2-signal-ingress`) | `cd backend && uv run pytest tests/strategies tests/accounts -q` | Live PG, `0003` applied incl. seeded `capital_pools` rows [DB] | `alembic downgrade 0002`; remove `strategies/` and `accounts/` packages |
| 4 | Allocation core (race test + negative control) | `slice/4-allocation-core` (base `slice/3-strategies-accounts`) | `cd backend && uv run pytest tests/allocation -q` | Live PG, `0004` applied; concurrency tests need real concurrent connections, no fake exists [DB] | `alembic downgrade 0003`; remove `allocation/` package |
| 5 | Execution + ledger | `slice/5-execution-ledger` (base `slice/4-allocation-core`) | `cd backend && uv run pytest tests/execution tests/ledger -q` | Live PG, `0005` applied; Tier B fresh-DB-per-module for trigger tests [DB] | `alembic downgrade 0004` (blocked by ledger-cutoff rule once a fill exists); remove `execution/` and `ledger/` packages |
| 7 | Per-strategy allocation percentage (**added 2026-08-18**, closes a gap found in slice 5) | `slice/7-allocation-percentage` (base `slice/5-execution-ledger`) | `cd backend && uv run pytest -q` | Live PG, `0007` applied (`down_revision = "0005"`) [DB] | `alembic downgrade 0005`; revert `AllocationPolicy`, `StrategyPolicySnapshot` and `ProcessSignalHandler` to their slice-5 state |
| 6 | Reservation expiry sweeper — **runs last, see the note below** | `slice/6-reservation-sweeper` (base `slice/7-allocation-percentage`) | `cd backend && uv run pytest tests/allocation -q` | Live PG, migration **`0008`** applied (`down_revision = "0007"`) [DB] | `alembic downgrade 0007`; revert `expire_reservations.py` and `SweepHandler` |

> **Slice 6 moved after slice 7 and renumbered to migration `0008`
> (2026-08-18).** Its *code* dependency really is slice 4 only — nothing in the
> sweeper touches execution, the ledger or the allocation percent. But the
> Alembic revision chain is linear and shared across every slice, so basing
> slice 6 on `slice/4-allocation-core` and numbering it `0006` would fork the
> chain: `0006` and `0007` would both descend from a common ancestor, leaving
> two heads and forcing a merge revision at integration time. Code
> independence does not buy migration independence. Slice 6 therefore chains
> from `0007` as `0008`, and `0006` is intentionally never used.

---

## Slice 1: Shared foundation and job queue

- [x] 1.1 RED: unit tests for `Money`/`Currency`/`Venue` in `backend/tests/shared/domain/test_money.py`
- [x] 1.2 GREEN: implement `shared/domain/money.py` and `shared/domain/errors.py`
- [x] 1.3 RED: unit tests for `Job`/`JobKind`/`ClaimedJob` DTOs in `backend/tests/shared/application/test_job.py`
- [x] 1.4 GREEN: implement `shared/application/job.py` and Protocol ports in `shared/application/ports.py`
- [x] 1.5 GREEN: implement `SystemClock`, `FixedUsdRateProvider`; add `reservation_ttl_seconds`, `worker_poll_interval_seconds` to `shared/config.py`
- [x] 1.6 Migration `0001_jobs`: `jobs` table + `ix_jobs_claimable`, real `downgrade()` [DB]
- [x] 1.7 RED: integration test — two workers claim distinct jobs concurrently, neither blocks (spec: job-queue § SKIP LOCKED Claim) [DB]
- [x] 1.8 RED: integration test — crash reclaim: killed connection releases the row lock (spec: job-queue § Crash Reclaim) [DB]
- [x] 1.9 RED: integration test — no-jobs poll returns cleanly; ack marks complete; failure allows retry (spec: job-queue § Acknowledge and Retry) [DB]
- [x] 1.10 GREEN: implement `PostgresJobQueue` (claim/ack/fail/retry) in `shared/infrastructure/job_queue.py` [DB]
- [x] 1.11 GREEN: implement `SqlAlchemyUnitOfWork` and `JobRow`
- [x] 1.12 GREEN: implement `WorkerRunner` claim loop + handler registry
- [x] 1.13 Verify slice green: `cd backend && uv run pytest tests/shared -q`; `ruff check .`; `mypy src`

## Slice 2: Signal ingress

> **Alert contract resolved 2026-08-12** — see design.md § "Alert Contract and
> Signal Routing". The payload is the owner's existing Pionex-format alert,
> adopted unchanged. Two consequences land in this slice:
> 1. `signals` MUST persist `action`, `contracts`, `position_size`, `price` and
>    `symbol` as typed columns, not just an opaque payload blob — the
>    open/close transition cannot be reconstructed later without them.
> 2. The idempotency key is
>    `hash(signal_type + time + action + contracts + position_size)`, not `time`
>    alone; `{{timenow}}` has only second resolution.

- [x] 2.0a RED: unit tests for `TradingViewAlert` parsing — the exact Pionex-format payload parses; `contracts`/`position_size`/`price` coerce from strings to `Decimal`; a malformed or missing `data` object is rejected
- [x] 2.0b GREEN: implement `signals/domain/alert.py` (parsing + coercion, no framework imports)
- [x] 2.0c RED: unit tests for `derive_idempotency_key` — identical payload yields an identical key; a differing `position_size` or `contracts` yields a different key within the same `time` second
- [x] 2.0d GREEN: implement the composite key derivation
- [x] 2.0e RED: unit tests for `PositionTransition.classify(prior, next)` — the five cases (open long, open short, close long, close short, reverse) plus absent prior treated as `0`; asserts each maps to CONSUMES or RELEASES
- [x] 2.0f GREEN: implement `signals/domain/position_transition.py`
- [x] 2.1 RED: unit tests for `WebhookSignal`/`IdempotencyKey`/`SignalStatus` in `backend/tests/signals/domain/test_signal.py`
- [x] 2.2 GREEN: implement `signals/domain/signal.py`
- [x] 2.3 RED: unit tests for `SourceIpAndSecretAuth` — valid, wrong IP, missing/wrong secret (spec: signal-ingress § Webhook Authentication)
- [x] 2.4 GREEN: implement `signals/infrastructure/auth.py` with the four allowlisted TradingView IPs
- [x] 2.5 RED: unit tests for `IngestSignal` — missing key rejected, first delivery persists+enqueues, duplicate resumes (spec: signal-ingress § Idempotent Signal Persistence) with fake ports
- [x] 2.6 GREEN: implement `signals/application/ports.py` and `ingest_signal.py`
- [x] 2.7 Migration `0002_signals`: `signals` table + `ux_signals_idempotency`, real `downgrade()`. Columns MUST include typed `action`, `contracts`, `position_size`, `price`, `symbol` and `signal_type`, plus an index on `(strategy_id, symbol, received_at DESC)` so the prior `position_size` lookup is cheap [DB]
- [x] 2.8 RED: integration test — `ON CONFLICT DO NOTHING` insert produces no second row on duplicate key [DB]
- [x] 2.9 GREEN: implement `SqlAlchemySignalRepository` + `SignalRow`
- [x] 2.10 RED: API test — `POST /webhook/tradingview`: 200 fast, 401 wrong IP, 422 missing key, no exchange call on any branch, spy `ExchangePort` (spec: signal-ingress § Fast Enqueue-Only Response) [DB]
- [x] 2.11 GREEN: implement `signals/infrastructure/router.py`; wire into `main.py`
- [x] 2.12 Verify slice green: `cd backend && uv run pytest tests/signals -q`; `ruff check .`; `mypy src`

## Slice 3: Strategies and accounts

> **HARD CONSTRAINT FROM SLICE 2.** `signals.strategy_id` is already populated
> with `UUID(alert.signal_type)`. Strategy registration MUST set `strategies.id`
> explicitly to that same `signal_type` UUID and MUST NOT rely on the
> `gen_random_uuid()` server default. Otherwise task 3.5's
> `ADD CONSTRAINT fk_signals_strategy` fails against rows slice 2 already
> inserted, and it will look like a migration bug rather than an identity
> mismatch. See design.md § "`strategy_id` derives from `signal_type`".

- [x] 3.0 RED: integration test — inserting a signal with `signal_type` X then registering a strategy with `id = X` lets migration `0003`'s FK apply cleanly; registering with a generated id instead makes it fail [DB]
- [x] 3.1 RED: unit tests for `Strategy`/`FillMode`/`AllocationPolicy` in `backend/tests/strategies/domain/test_strategy.py`
- [x] 3.2 GREEN: implement `strategies/domain/strategy.py`
- [x] 3.3 RED: unit tests for `PoolConfig` VO in `backend/tests/accounts/domain/test_pool_config.py`
- [x] 3.4 GREEN: implement `accounts/domain/pool_config.py`
- [x] 3.5 Migration `0003_strategies_pools`: `capital_pools` + `strategies` tables, FK, `ALTER TABLE signals ADD CONSTRAINT fk_signals_strategy`, seed the four configured pools (`spot`/USDT, `usdt-m`/USDT, `coin-m`/BTC, `coin-m`/ETH) — **`capital_pools` is the single source of truth; no `CONFIGURED_POOLS` env list**, real `downgrade()` [DB]
- [x] 3.6 RED: integration test — reading `capital_pools` returns the seeded rows [DB]
- [x] 3.7 GREEN: implement `SqlAlchemyStrategyRepository`+`StrategyRow`, and a pool-config repository that reads `capital_pools` (`accounts/infrastructure/`) — supersedes the design draft's env-parsing `PoolConfigLoader` per the resolved single-source-of-truth decision
- [x] 3.8 GREEN: implement `FakeBalanceSource` and `BalanceSourcePort`
- [x] 3.9 RED: unit test — `StrategyPolicyAdapter` maps `Strategy` → `StrategyPolicySnapshot` DTO with a fake repository
- [x] 3.10 GREEN: implement `strategies/application/policy_adapter.py` (implements `allocation.application.StrategyPolicyPort`)
- [x] 3.11 RED: unit test — `PoolBalanceAdapter` maps pool config + `FakeBalanceSource` to `PoolBalancePort`
- [x] 3.12 GREEN: implement `accounts/application/pool_balance_adapter.py`
- [x] 3.13 RED: unit test — `assert_pool_lock_keys_distinct` raises `PoolLockKeyCollisionError` given two synthetic pools sharing a lock-key pair (pure, no DB) (spec: capital-allocation § Startup Lock-Key Collision Invariant)
- [x] 3.14 RED: integration test — collision check against the four seeded pools passes; confirms `coin-m`/BTC and `coin-m`/ETH share `k1` but differ in `k2` [DB]
- [x] 3.15 GREEN: implement `allocation/infrastructure/lock_key_invariant.py`; wire invariant 1 into `main.py` lifespan
- [x] 3.16 Verify slice green: `cd backend && uv run pytest tests/strategies tests/accounts -q`; `ruff check .`; `mypy src`

## Slice 4: Allocation core — race test and negative control

- [x] 4.1 RED: unit tests for `decide()` — all 6 ordered rules and all 7 edge cases (spec: capital-allocation § Strategy Policy Resolution, § Reservation Expiry)
- [x] 4.2 GREEN: implement `allocation/domain/decision.py` and `rules.py`
- [x] 4.3 RED: unit tests for `CapitalPool.available` (clamped at 0) and `PoolKey`/`LockKey` construction
- [x] 4.4 GREEN: implement `capital_pool.py`, `pool_key.py`, `lock_key.py`
- [x] 4.5 RED: unit tests for `Reservation` state transitions — legal moves accepted, illegal moves rejected
- [x] 4.6 GREEN: implement `allocation/domain/reservation.py`
- [x] 4.7 RED: unit tests for `AllocateCapital` pre-lock guards — resume without lock, disabled-strategy skip without lock, unknown pool raises, currency mismatch, non-positive request — fake ports + `FrozenClock`
- [x] 4.8 GREEN: implement `allocation/application/ports.py` and `allocate_capital.py`
- [x] 4.9 Migration `0004_reservations`: `reservations` table + `ix_reservations_active`, real `downgrade()` [DB]
- [x] 4.10 GREEN: implement `PgAdvisoryLockAdapter` and `SqlAlchemyReservationRepository`+`ReservationRow` [DB]
- [x] 4.11 RED: integration test — TXN-A end to end: full/partial/skip each write or skip a reservation row inside the locked transaction (spec: capital-allocation § Serialized Allocation Decision, § Pool Availability) [DB]
- [x] 4.12 **[HIGHEST VALUE]** RED: concurrency race test — 8 concurrent 200-unit requests against a 1000-balance pool, parametrized over 30 iterations; assert committed reservations never exceed 1000, every result is FULL/PARTIAL/SKIP, no phantom grants (spec: capital-allocation § Concurrency Safety Invariant) [DB]
- [x] 4.13 GREEN: confirm 4.12 passes against `PgAdvisoryLockAdapter`; no new production code expected beyond 4.10 [DB]
- [x] 4.14 **[HIGHEST VALUE]** RED: negative control — `NoOpAdvisoryLock` stub, same scenario for up to 50 iterations, explicit `pytest.fail("50 lock-free iterations never over-allocated...")` branch if no breach is ever observed (spec: capital-allocation § Concurrency Safety Invariant, negative-control scenario) [DB]
- [x] 4.15 Verify 4.14 observes a real breach on this codebase today (the `pytest.fail` branch only fires on regression) [DB]
- [x] 4.16 Verify slice green: `cd backend && uv run pytest tests/allocation -q` (incl. 4.12, 4.14); `ruff check .`; `mypy src`

## Slice 5: Execution and ledger

> **Unblocked 2026-08-12.** The alert contract is confirmed — see design.md
> § "Alert Contract and Signal Routing". `quantity = granted / price`, where
> `granted` comes from the strategy's configured percentage of pool
> availability. The alert's `contracts` field is TradingView simulated-equity
> sizing and MUST NEVER be used as a real order quantity; persist it as
> diagnostic context only. `price` from the alert is the bar close at signal
> time — a slippage reference, never the ledger fill price.
>
> New scope in this slice: tasks 5.16–5.17 route by `PositionTransition` so a
> capital-RELEASING signal never takes the advisory lock.

- [x] 5.1 RED: unit tests for `ExecutionAttempt`/`OrderRequest`/`Fill` (`execution/domain/`) — `quantity = granted / price`, `granted` from the strategy's configured pool percentage, never from the alert's `contracts`
- [x] 5.2 GREEN: implement `execution/domain/`
- [x] 5.3 RED: unit tests for `LedgerEntry` (frozen, zero mutators)
- [x] 5.4 GREEN: implement `ledger/domain/ledger_entry.py`
- [x] 5.5 RED: unit tests for `ExecuteReservation` pre-submit expiry re-check — valid submits, expired aborts to `RELEASED` with no submission (spec: trade-execution § Pre-Submit Expiry Re-Check) — fake `ExchangePort` + `FrozenClock`
- [x] 5.6 GREEN: implement `execution/application/ports.py` and `execute_reservation.py`
- [x] 5.7 GREEN: implement `FakeExchangeAdapter` (`is_live = False`)
- [x] 5.8 RED: unit test — `RecordFill` implements `FillRecorderPort`, maps `FillRecord` (incl. `usd_rate_at_fill`) with a fake `LedgerRepositoryPort`
- [x] 5.9 GREEN: implement `ledger/application/ports.py` (internal) and `record_fill.py`
- [x] 5.10 Migration `0005_ledger_execution` — `execution_attempts`, `ledger_entries`, `fn_ledger_append_only()`, both triggers; `downgrade()` refuses with existing rows unless `-x force_ledger_drop=1` [DB]
- [x] 5.11 GREEN: implement `SqlAlchemyExecutionAttemptRepository`+`Row` and `SqlAlchemyLedgerRepository`+`Row` (insert-only)
- [x] 5.12 RED (Tier B): raw `UPDATE`, `DELETE`, `TRUNCATE` on `ledger_entries` each raise `restrict_violation`, fresh-DB-per-module fixture (spec: trade-ledger § Append-Only Enforcement) [DB]
- [x] 5.13 RED: successful fill records via `FillRecorderPort` carrying `allocation_id`, `strategy_id`, pool (spec: trade-ledger § Ledger Row Content, trade-execution § Fill Recording) [DB]
- [x] 5.14 GREEN: wire `ProcessSignalHandler` (`AllocateCapital` then `ExecuteReservation`); register `signal.process` in `WorkerRunner` via `main.py`
- [x] 5.16 RED: unit test — a RELEASE-path signal (close long, close short) never acquires the advisory lock, asserted with a spy `AdvisoryLockPort`; a CONSUME-path signal does acquire it
- [x] 5.17 GREEN: route by `PositionTransition` in `ProcessSignalHandler` — CONSUMES goes through `AllocateCapital`, RELEASES goes straight to `ExecuteReservation` without the lock
- [x] 5.15 Verify: `cd backend && uv run pytest tests/execution tests/ledger -q`; `ruff check .`; `mypy src`

## Slice 6: Reservation expiry sweeper

> Depends on **slice 4 only** (needs `ReservationRepositoryPort`, `Reservation`,
> job queue). It does **not** depend on slice 5 and may ship in parallel with it.

- [ ] 6.1 RED: unit tests for `ExpireReservations` — marks past-`expires_at` `PENDING`/`SUBMITTED` as `EXPIRED` with `terminal_at` set — fake repository + `FrozenClock` (spec: capital-allocation § Reservation Expiry)
- [ ] 6.2 GREEN: implement `allocation/application/expire_reservations.py`
- [ ] 6.3 Migration `0008_reservation_terminal` (**not `0006`** — see the work-unit table note; `down_revision = "0007"`): `terminal_at`, `release_reason` columns + `ix_reservations_sweepable`, real `downgrade()` [DB]
- [ ] 6.4 RED: integration test — TXN-C batch expiry updates all past-expiry rows to `EXPIRED` [DB]
- [ ] 6.5 GREEN: extend `SqlAlchemyReservationRepository` with the sweep query/update [DB]
- [ ] 6.6 RED: unit test — `SweepHandler` re-enqueues `reservation.sweep` with `run_after = now + worker_poll_interval_seconds`
- [ ] 6.7 GREEN: implement self-re-enqueuing `SweepHandler`; register `reservation.sweep` in `WorkerRunner` via `main.py`
- [ ] 6.8 Verify slice green: `cd backend && uv run pytest tests/allocation -q`; `ruff check .`; `mypy src`

## Slice 7: Per-strategy allocation percentage

> **Added 2026-08-18 to close a gap found during slice 5.** design.md always
> required `requested` to come from the strategy's configured percentage, but
> no such field was ever created — slice 3 built `AllocationPolicy` with only
> `venue`, `settlement_currency` and `fill_mode`. Slice 5 shipped a stand-in,
> `requested = abs(position_size) * price`, which sizes from TradingView's
> *simulated* equity and therefore asks for the whole pool on every signal.
> Harmless only because `DRY_RUN` defaults to true. This slice closes it.
>
> **Percent base: pool balance, not availability** (owner's decision
> 2026-08-18 — see design.md § "Order size never comes from the alert"). A
> strategy at 20% of a 1000-balance pool requests 200, always, regardless of
> what other strategies hold. `decide()` is unchanged and still clamps
> `granted` to real availability, so the balance base can never over-allocate:
> the percent caps the *ask*, the lock and `decide()` govern the *grant*.

- [x] 7.1 RED: unit tests for `AllocationPercent` — accepts 0 < p <= 100, rejects zero, negative, and > 100; `Decimal` throughout
- [x] 7.2 GREEN: implement `AllocationPercent` in `strategies/domain/strategy.py` and add it to `AllocationPolicy`
- [x] 7.3 RED: unit tests for `requested_from_percent(balance, percent)` — `ROUND_DOWN` quantization, and a 100% strategy requests exactly the balance
- [x] 7.4 GREEN: implement it in the allocation domain (pure, no framework)
- [x] 7.5 Migration `0007_allocation_percent`: `strategies.allocation_percent numeric NOT NULL DEFAULT 100` + a `CHECK (allocation_percent > 0 AND allocation_percent <= 100)`, real `downgrade()` [DB]
- [x] 7.6 GREEN: carry `allocation_percent` through `StrategyPolicySnapshot`, `SqlAlchemyStrategyRepository` and `StrategyPolicyAdapter`
- [x] 7.7 RED: unit test — `ProcessSignalHandler` derives `requested` from `allocation_percent` × pool balance, and **never** from `position_size` or `contracts`; assert with a strategy whose `position_size × price` differs wildly from its percent-derived request
- [x] 7.8 GREEN: replace the slice-5 stand-in in `signals/application/process_signal.py`; delete its deviation note
- [x] 7.9 RED (integration): two strategies at 60% and 60% of the same 1000-balance pool — the first grants 600, the second is clamped to the remaining 400 by `decide()`, proving the percent caps the ask without breaking the invariant [DB]
- [x] 7.10 Verify slice green: `cd backend && uv run pytest -q`; `ruff check .`; `mypy src`
