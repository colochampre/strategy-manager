# Order not placeable: refuse definitively instead of retrying

## Objective

A futures order that the venue's own per-symbol rules make impossible, such as a size that floors to zero or falls below the minimum quantity or notional, must end as a definitive refusal. Today it is a generic job retry.

## Problem

`PlaceOrder.place()` and `ClosePosition.close()` call the adapter's `build_open_order` / `build_close_order` at two points where no refusal is handled:

- **before** the execution attempt is inserted;
- **outside** the `try/except ExchangeError` that wraps only `exchange.place`.

On top of that, `BybitApiError` and `BinanceApiError` do not subclass `ExchangeError`. The result:

- **A sub-minimum open** propagates to `WorkerRunner`, which logs a WARNING and retries with backoff until the job ends FAILED. No attempt row is written, and the reservation is never RELEASED: it leaks until the TTL sweep.
- **A sub-minimum close residual** retries the same way, while the position stays open at the venue.

Evidence: `execution/application/place_order.py:130-190`, `close_position.py:147-198`, adapters `execution/infrastructure/{bybit,binance}_futures_exchange.py`, rules `shared/infrastructure/{bybit,binance}/read_client.py` (`round_qty`, `assert_tradable`).

## Why

This must be fixed before `DRY_RUN=false`. With capital withdrawn to Earn, small grants make the path likely.

## Approach (approved by the owner, 2026-09-24)

Fix it where the rules are already checked, with no extra venue call and no pre-reservation leverage read.

- Adapters raise a typed, definitive `OrderNotPlaceable` (an `ExchangeError`) ONLY for rule refusals: a size that floors to zero, or one below the minimum quantity or notional. A live-call failure inside `build_*` (the leverage read, the instrument read, a network or auth error) is NOT a rule refusal and keeps its current behaviour.
- **Open:** `OrderNotPlaceable` releases the reservation at once, logs ONE WARNING and ends the signal definitively, with no retry. This is the same shape as the empty-pool refusal in `2399510`.
- **Close of a sub-minimum residual:** logs ONE ERROR (it reaches Telegram), ends the job definitively with no retry loop, and leaves the position for a human. It is dust that no order can close.

## Scope

Bybit linear USDT-M and Binance USDⓈ-M futures, the only adapters wired in `main.py` `exchange_for`. The Pionex adapters are never instantiated.

## Constraints

- Strict TDD: RED is seen failing at an assertion before GREEN. Protections are proven non-vacuous by breaking them.
- A test that crosses a module boundary on a symbol uses a different spelling on each side: `STXUSDT.P`, `STXUSDT` or `STXUSDT_PERP`.
- `DRY_RUN` defaults to true; no test needs a real credential.
- No AI attribution. One conventional commit per task. `git commit -F`.

## TDD

- Mode: ON. Source: `openspec/config.yaml` (`strict_tdd: true`).
- Runner: `cd backend && uv run pytest --tb=short`.

## Tasks

- [x] **T1: the typed refusal in both adapters.** Define `OrderNotPlaceable(ExchangeError)` in `execution/application/ports.py`. Both adapters' `build_open_order` / `build_close_order` raise it for a floored-to-zero size and for `assert_tradable` failures. The message names the symbol, the size, the minimum and the step. Live-call errors raised during build must NOT be translated, and a test must show it. Route: delegated direct (the writer trigger fires: 2+ non-trivial files).
- [x] **T2: open refusal.** `PlaceOrder` catches `OrderNotPlaceable` from `build_open_order`, marks the reservation RELEASED in the same transaction, logs ONE WARNING naming the signal, symbol and reason, and returns a refused outcome. `process_signal` ends the job without an exception, so there is no retry. Also verify, and report, what a retry of a signal whose build raised a TRANSIENT error does to the reservation it already holds. Route: delegated direct.
- [x] **T3: close residual.** `ClosePosition` (and so `CloseOrphans`) catches `OrderNotPlaceable` from `build_close_order`, logs ONE ERROR naming the strategy, allocation, symbol, residual and minimum, writes no attempt, and returns a definitive "not closable" outcome. The job does not retry. Route: delegated direct.

## Acceptance criteria

- A sub-minimum open: no exception reaches `WorkerRunner`, the reservation is RELEASED at once, exactly one WARNING is logged, and the job is not retried.
- A sub-minimum close: exactly one ERROR, no retry loop, no attempt row, and the position is untouched.
- A transient venue failure during build still propagates, and is retried as before.
- Gate: `ruff check .`, `mypy src`, `pytest` (exit 0 plus the summed per-file count).

## Checks

Backend gate after each task.

## Delivery

One PR from `fix/order-not-placeable`. The forecast is about 600–900 authored lines. The strategy is `ask-on-risk` and the owner already accepts per-change PRs of this size, so this is one PR with three work-unit commits.

## Progress

- Branch `fix/order-not-placeable` from `main` at `7df8c96`.
- **T1 done**, commit `3ce3dc3` (`fix(execution): raise OrderNotPlaceable for venue rule refusals`).
  - `OrderNotPlaceable(ExchangeError)` added to `execution/application/ports.py`,
    carrying `symbol`/`size`/`minimum`/`step`.
  - Both adapters (`bybit_futures_exchange.py`, `binance_futures_exchange.py`)
    raise it from `build_open_order`/`build_close_order` for a floored-to-zero
    size, and translate an `assert_tradable` rule failure into it.
  - Implementation choice: `PerpContract.assert_tradable` in both
    `shared/infrastructure/{bybit,binance}/read_client.py` now raises a new
    `BybitRuleRefusal(BybitApiError)` / `BinanceRuleRefusal(BinanceApiError)`
    subclass instead of the bare `*ApiError`. The adapter catches only that
    narrow subclass around the `assert_tradable` call and translates it to
    `OrderNotPlaceable`; a live-call failure from `leverage_for`/`perp_rules`
    (network, auth, 5xx) still raises the bare `*ApiError`, which is never
    caught by that narrow except, so it propagates completely unchanged.
    Existing `binance/test_futures_rules.py` assertions on `BinanceApiError`
    for `assert_tradable` failures stay green unmodified, since the new
    subclass IS-A `BinanceApiError`.
  - RED confirmed genuinely (not just an ImportError): stashed the adapter
    and read-client source changes, restored only the `OrderNotPlaceable`
    class stub in `ports.py`, and re-ran the new/updated adapter tests —
    11 failed at the `pytest.raises(OrderNotPlaceable, ...)` assertion
    (each caught the pre-fix `BybitApiError`/`BinanceApiError`/`ExchangeError`
    instead), then GREEN after restoring the full fix. The two
    "unreadable leverage/rules" non-translation tests already passed
    pre-fix (they pin a property that already held, not a bug this task
    fixes) — expected, not vacuous, since they'd fail if a future change
    widened the except's scope.
  - Non-vacuity: each `OrderNotPlaceable` test also asserts `.symbol`,
    `.size`, `.minimum` (and `.step` where meaningful) against the fixture's
    real numbers, so a translation that fired but dropped the fields would
    still fail.
  - Symbol spelling rule honoured: `test_a_grant_too_small_to_reach_one_step_
    is_refused_by_name` (both venues) feeds the adapter `f"{SYMBOL}.P"` and
    asserts `exc.symbol == SYMBOL` (unsuffixed).
  - Gate: `ruff check .` clean; `mypy src` — Success, 210 files; `pytest`
    exit 0, `--co -q` sums to 1,518 (baseline 1,513 + 5 new tests).

- **T2 done**, commit `7b20a05` (`fix(execution): release the reservation on an unplaceable open`).
  - `PlaceOrder.place()` now wraps the `exchange.build_open_order(...)` call
    in `try/except OrderNotPlaceable`: marks the reservation `RELEASED`,
    commits, logs exactly one WARNING (`reservation`, `strategy`, `symbol`,
    `reason`), and returns `PlaceResult(status="REFUSED",
    execution_attempt_id=None, error=str(exc))` instead of letting the
    exception propagate. Added `"REFUSED"` to `PlaceResult.status`'s
    documented values. No attempt row is written and no settle job is
    enqueued, because build runs before either write.
  - `ProcessSignalHandler` needed NO change for the open side: it already
    discards `PlaceOrder.place()`'s return value entirely (never inspects
    `.status`), so once `PlaceOrder` stopped raising, nothing above it could
    still raise either. `test_a_refused_open_ends_the_job_without_raising`
    in `test_process_signal.py` pins this contract as a regression guard,
    but it is NOT a RED test — it already passed before this task's process_
    signal.py (unchanged) because the bug was entirely inside `PlaceOrder`.
  - RED confirmed genuinely: stashed only `place_order.py`, ran the 3 new
    tests against the pre-fix source. 2 failed via the uncaught
    `OrderNotPlaceable` propagating out of `place()` (pytest reports these as
    FAILED, not a collection ERROR, since the exception is inside the test
    body); the third uses an explicit `try/except OrderNotPlaceable:
    pytest.fail(...)` pattern so its RED is a clean assertion-style Failed
    rather than a raw traceback. All 3 GREEN after restoring the fix.
  - Non-vacuity: the "no attempt / no settle job" test asserts
    `attempts.inserted == []` and `queue.enqueued == []` in addition to the
    RELEASED mark, and the logging test asserts the reservation id, strategy
    id, symbol AND the exception's own message text are all present in the
    single WARNING record.
  - **Investigation (T2's second half): what a transient-error retry does to
    the reservation it already holds.** Traced `AllocateCapital.allocate()`
    (`allocation/application/allocate_capital.py:97-100,176-193`): before
    doing anything else it calls `find_by_signal_id(command.signal_id)`, and
    if a reservation already exists for this signal, `_resume()` returns
    that SAME `reservation_id` unconditionally — it does not even look at
    the reservation's current status, and it never re-acquires the advisory
    lock or inserts a second row. So on a retry of `signal.process` after a
    TRANSIENT `build_open_order` failure (a network/auth/5xx read that
    propagates unchanged, per T1): `AllocateCapital.allocate()` is called
    again, finds the existing reservation (still PENDING, because
    `PlaceOrder` never reached `mark(SUBMITTED)` — that write sits AFTER the
    now-failing `build_open_order` call) and returns it unchanged, `resumed
    =True`. `PlaceOrder.place()` is then called again with the SAME
    reservation id; `get_for_update` reads the same still-PENDING snapshot.
    Two outcomes from there: (a) the transient failure clears on a later
    attempt and the SAME reservation is placed normally, or (b) it keeps
    failing until the reservation's TTL (seconds) is reached, at which point
    the pre-submit expiry re-check (place_order.py:106-109) fires on the next
    retry, marks it RELEASED and returns ABORTED_EXPIRED — a clean release,
    not a leak. The only way the reservation genuinely leaks until the TTL
    sweep is if the JOB itself exhausts `max_attempts` and ends FAILED before
    ever reaching the TTL boundary — and that is the pre-existing, intended
    TTL-sweep safety net every transient failure already relies on, not a
    leak specific to this bug. **Conclusion: REUSED, never double-reserved
    (the `reservations.signal_id` UNIQUE constraint plus `_resume`'s dedup
    make a second reservation for the same signal impossible), and its
    eventual release is either the ordinary pre-submit expiry check or the
    ordinary TTL sweep — ordinary retry behaviour, not a second bug.** No
    fix needed; this is correct as designed.
  - Gate: `ruff check .` clean; `mypy src` — Success, 210 files; `pytest`
    exit 0, `--co -q` sums to 1,522 (T1's 1,518 + 4 new tests).

- **T3 done**, commit `6f39fb7` (`fix(execution): end a dust close residual definitively`). The commit's own copy of this line read `5e97f0f`, a hash that an amend replaced; this line was corrected in a follow-up docs commit.
  - `ClosePosition.close()` wraps `exchange.build_close_order(...)` in
    `try/except OrderNotPlaceable`: logs exactly one ERROR (`strategy`,
    `allocation`, `symbol`, `residual` = the ledger's own `base_size`,
    `venue_minimum` = `exc.minimum`, `pool`, and the exception's reason),
    writes no attempt row, and returns `CloseResult(status="NOT_CLOSABLE",
    execution_attempt_id=None, ...)`. Added `"NOT_CLOSABLE"` to
    `CloseResult.status`'s documented values and widened
    `execution_attempt_id` to `UUID | None` (no other caller reads that
    field, confirmed by grep before the change).
  - `ProcessSignalHandler._handle_releases` now treats `NOT_CLOSABLE` the
    same as `FAILED` (`close_result.status in ("FAILED", "NOT_CLOSABLE")`):
    without this the handler fell through to the final `return
    ProcessSignalResult(..., True)` and reported `executed=True` for a close
    that never happened. Genuinely RED before this one-line change (below).
  - `CloseOrphans` needed NO change: it never inspects `CloseResult.status`
    at all, so once `ClosePosition` stopped raising, this caller was
    automatically safe. `test_a_dust_residual_close_does_not_raise_out_of_
    close_orphans` pins that as a regression guard (not RED — no code here
    changed).
  - RED confirmed genuinely for all 3 non-vacuous tests, all failing at a
    clean assertion/pytest.fail (not an ImportError or a raw traceback grep):
    stashed `close_position.py` + `process_signal.py`, ran the new tests --
    2 failed via the `try/except OrderNotPlaceable: pytest.fail(...)` pattern
    at `ClosePosition`'s own level, and
    `test_a_dust_residual_close_is_reported_as_not_executed_without_
    retrying` failed with `AssertionError: assert True is False` at the
    `process_signal.py` layer -- proving the one-line `_handle_releases`
    change is load-bearing, not decorative. GREEN after restoring both
    fixes.
  - Non-vacuity: the "no attempt" test asserts `attempts.inserted == []`,
    `queue.enqueued == []` AND `exchange.orders == []`; the logging test
    asserts strategy id, allocation id, symbol, the residual size AND the
    venue minimum are all present in the single ERROR record.
  - **"What fails here without a log line?"** Nothing on the direct path:
    both T2's release and T3's dust-refusal always log (WARNING / ERROR)
    unconditionally before returning, so there is no silent branch. The one
    second-order case: a REVERSE's reverse-wiring release half seeds its S5
    continuation BEFORE calling `close_position.close(...)`
    (process_signal.py's own documented ordering) -- if that close then
    comes back `NOT_CLOSABLE`, the already-seeded continuation will never
    see a FILLED close to resume on. This is NOT a new gap: it is byte-for-
    byte the same situation the existing FAILED-close branch already
    handles (same `if close_result.status in (...)` branch now covers both),
    and `OpenAfterClose`'s own stuck/stale-continuation handling -- already
    relied on for a FAILED close -- covers `NOT_CLOSABLE` identically,
    because both statuses now take the exact same code path. No new
    silent-failure mode was introduced.
  - Gate: `ruff check .` clean; `mypy src` — Success, 210 files; `pytest`
    exit 0, `--co -q` sums to 1,526 (T2's 1,522 + 4 new tests). No
    `pg_terminate_backend` teardown flake observed in this run.

## Next step

None — all three tasks done. Ready for the owner to review the branch
(`fix/order-not-placeable`, not pushed) and open a PR.
