# Subscriber safety — tasks

Planning. Decisions made; nothing is built until the owner says to build. It goes before `account-deletion`.

## Tasks

- [x] SS.0 Decisions D1-D4 (owner, 2026-11-12), recorded in `proposal.md`.
- [x] SS.1 Verify the exchange stop live on Bybit and Binance with a probe that
  signs from the vault (`scripts/probe_credentials.py`, `--user-email`): order
  shape, reduce-only, how a stop's fill is reported, and how it is cancelled
  when the strategy closes first.
  - *Run 1, Bybit, 2026-11-12, `--mode trigger` (PR #103's
    `scripts/check_bybit_stop.py`), not triggered:* SOLUSDT LONG 0.2 at 81.4,
    1x. The price rose to 81.75 and never reached the stop at 81.27; after 15
    minutes the stop was cancelled and the position closed. The account ended
    flat with no stop resting, +0.038 USDT. What was seen:
    - `POST /v5/position/trading-stop` with `tpslMode: Full`, `positionIdx: 0`,
      `slOrderType: Market` answers `{}`.
    - The stop rests as a conditional order under `orderFilter=StopOrder`:
      - `stopOrderType: StopLoss`, `createType: CreateByStopLoss`;
      - `orderStatus: Untriggered`, `triggerPrice: 81.27`,
        `triggerBy: LastPrice`, `triggerDirection: 2`;
      - `reduceOnly: true`, `closeOnTrigger: true`;
      - `qty` equals the whole position (Full mode);
      - `orderLinkId: ""`. A stop carries no client id of ours.
    - On that order `stopLoss` and `slTriggerBy` come back empty. The level is
      in `triggerPrice`/`triggerBy`, and the position object reports
      `stopLoss: '81.27'`.
    - `stopLoss: "0"` answers `{}`. Whether the cancel alone removed the stop
      is not yet separated from the close that followed it: `--mode cancel`
      answers that.
  - *Run 2, Bybit, 2026-11-12, `--mode trigger --stop-pct 0.05`, TRIGGERED:*
    SOLUSDT LONG 0.2 at 81.59, 1x. The stop was set at 81.54 and fired about
    a minute later.
    - The execution carries `orderLinkId: ""`, but its `orderId` is the
      resting stop's own `orderId` (`e93b3d2a…`). Recording that id when the
      stop is set is how the ledger recognises the fill, without
      reconciliation.
    - It is marked by `stopOrderType: StopLoss`, `createType: CreateByStopLoss`
      and `closedSize: 0.2` (the whole position).
    - It filled at the trigger price exactly, 81.54, while `orderPrice: 77.49`
      is Bybit's own slippage bound for the market order.
    - The fee is charged in USDT at `0.00055` taker, as for any close.
    - Order history shows the stop `Filled`. Afterwards there was no resting
      stop, and the position reported `stopLoss: ''`.
    - The accounting closes exactly. The price moved −0.01 and the fees were
      0.0089749 + 0.0089694, which makes −0.0279443, the balance difference to
      the eighth decimal.
  - *Design finding:* setting the stop is a second call after the opening
    fills. That leaves the position unprotected for about a second, and with no
    stop at all if that call fails. Bybit's order creation accepts `stopLoss`
    on the opening order itself. Verify it next: one atomic call is the right
    shape for D1.
  - *Run 3, Bybit, 2026-11-12, `--mode close-first`:* a SOLUSDT LONG of 0.2 at
    81.45, with the stop at 81.32, then a reduce-only market close as a
    strategy's signal would send it. Once the position closed, the stop was
    GONE: no resting stop order, and the position reported `stopLoss: ''`.
    Bybit removes a Full-mode stop with its position, so a normal close leaves
    nothing behind to cancel. The accounting closes exactly: price −0.002 and
    fees 0.0089595 + 0.0089584 make −0.0199179, the balance difference.
  - *Run 4, Bybit, 2026-11-12, `--mode attach` (PR #104), the stop sent ON the
    opening order:* `/v5/order/create` with `stopLoss: "81.330"`,
    `slTriggerBy: LastPrice`, `tpslMode: Full`, `slOrderType: Market` was
    accepted. SOLUSDT LONG 0.2 filled at 81.47.
    - The resting stop existed as soon as the fill did, so there was no
      unprotected moment and no second call that could fail. **This is the
      shape for D1 on Bybit.**
    - The stop carries `parentOrderLinkId` equal to the opening's
      `orderLinkId`, which is our own id. The stop is thus tied to its
      allocation from the start, and run 2 showed that its execution carries
      the stop's own `orderId`.
    - Otherwise it is the same order as run 1: `StopLoss`, `CreateByStopLoss`,
      `Untriggered`, `reduceOnly`, `closeOnTrigger`, `qty` the whole
      position, `orderLinkId: ""`.
    - A reduce-only close removed it, as in run 3. The cost was −0.0239201
      USDT.
  - *Run 5, Binance, 2026-11-12, `--mode trigger` (PR #104), TRIGGERED:*
    DOGEUSDT LONG 76 at 0.066340, 1x, fee 0.00252091 USDT.
    - `POST /fapi/v1/algoOrder` with `algoType: CONDITIONAL`,
      `type: STOP_MARKET`, `triggerPrice: 0.066240`,
      `workingType: CONTRACT_PRICE`, `closePosition: true` and a UUID
      `clientAlgoId` was acknowledged with an `algoId`. It reported
      `algoStatus: NEW`, `reduceOnly: true`, `quantity: "0"` (closePosition
      sizes at trigger) and `timeInForce: GTE_GTC`.
    - The stop was created 1.02s after the opening filled (fill time against
      `createTime`). That is the unprotected gap on Binance, which has no stop
      on the opening order.
    - *Probe defect:* about a second after the acknowledgement,
      `GET /fapi/v1/algoOrder?algoId=` answered `-2013 Order does not exist.`
      The probe treated that read as fatal and exited with the position and
      the stop still live. The stop then fired about 31 minutes after it was
      created. PR #105 makes the read retry and adds `--inspect`.
    - Read afterwards with `--inspect`, the same GET found the stop:
      - `algoStatus: FINISHED`, `actualOrderId: 105975543111`,
        `actualType: MARKET`, `actualQty: 76`, `actualPrice: 0.066240`,
        `triggerTime` set;
      - `quantity` had become `76`;
      - `clientAlgoId` round-trips, so the stop can carry our own id.
    - `userTrades?orderId=<actualOrderId>` returned the fill: SELL 76 at
      0.066240, the trigger price exactly, fee 0.00251712 USDT (0.0005 taker),
      `realizedPnl: -0.0076`.
    - The trade itself names no `clientAlgoId`. The ledger reaches the fill
      through the algo order: `clientAlgoId` (ours) to `actualOrderId`, then
      `userTrades`.
    - No open algo order was left, and the position was flat.
    - The `-2013` right after creation looks like read-after-write lag: the
      same GET worked later. This is an assumption, not verified. A system
      reading a just-placed stop must retry `-2013` and must not conclude the
      stop is missing.
  - *Run 6, Binance, 2026-11-12, `--mode close-first` (PR #105):* DOGEUSDT
    LONG 76 at 0.066280, stop at 0.066180, then a reduce-only market close.
    - The stop was created 1.47s after the opening filled. The gap on Binance
      is a second or more, every time.
    - The GET right after creation found it on the first attempt this time.
      The `-2013` of run 5 is intermittent.
    - `openAlgoOrders` listed it (`quantity: "0.0"`, `triggerPrice: "0.06618"`:
      that list formats numbers differently from the single-order GET).
    - The close filled at 22:24:00.818. The stop went to
      `algoStatus: EXPIRED` at `updateTime` 0.824, 6 ms later, with no
      `actualOrderId`, and `openAlgoOrders` was empty. **Binance expires a
      `closePosition` stop with its position, as Bybit removes a Full-mode
      one: a normal close leaves nothing to cancel on either venue.**
    - The accounting closes exactly: no price move, and fees 0.00251864 ×
      2 = 0.00503728, the balance difference.
  - Not run, optional: Bybit `--mode cancel` on its own, which would show that
    `stopLoss: "0"` removes the stop while the position stays open. It
    matters only if a changed stop level ever moves stops already placed.
- [x] SS.2 Specs and tasks for the chosen layers.
  - Owner decisions D5-D8 were taken on 2026-11-12 and are recorded in
    `proposal.md`. The specs are `specs/protective-stop`, `specs/safety-close`
    and `specs/safety-events`. Rules the owner did not decide are marked
    *Assumption*:
    - the 1-50 range;
    - the leverage cap formula;
    - `MarkPrice` as the trigger;
    - the 30 s stop watcher;
    - simulated openings without a stop;
    - the seat staying ACTIVE after "Close now".
  - The code map came from a read-only explorer:
    - The author trades through a subscription of their own
      (`register_strategy.py:215-218`), so no separate author path is needed.
    - Disable is a bare PATCH through `UpdateStrategy`, with no exposure check
      (`update_strategy.py:154-175`).
    - `ArchiveStrategy` already refuses on exposure, through
      `StrategyExposureAdapter`.
    - `ClosePosition` raises `NothingRecordedYet` on a zero ledger net and
      retries.
    - Ledger rows have no cause. `ExecutionAttempt` has `origin` and
      `signal_id`.
    - No per-user event list exists.
    - The next migration is 0040.

Implementation, not started. Each task is planned as one PR, following the
owner's preference.

- [x] SS.3 The stop level and the leverage cap. Route: one bounded writer,
  for the context backstop of a long parent session. Branch
  `feat/subscriber-safety-stop-level`. Each later task brings its own
  migration with the code that uses it.
  - Migration 0040 adds `strategies.stop_loss_pct`: NOT NULL, existing rows
    at 10, CHECK 1-50, two decimals. It is rehearsed on a restored backup
    before production.
  - Domain and validation, `RegisterStrategy` and `UpdateStrategy`, and the
    router fields.
  - The panel: a field in the new-strategy dialog (10 offered) and an editor
    on the strategy's page.
  - `LEVERAGE_ABOVE_STOP_CAP` on subscribe, on a seat's leverage change and
    at registration (the author's seat). The panel's leverage control is
    capped.
  - A live opening is refused for a seat above the cap, before any capital is
    reserved. Its `OPENING_REFUSED_LEVERAGE_CAP` safety event comes with
    SS.10, which creates the table.
  - Risk: item 1 (migration) and item 3 (the strategy contract gains a
    field).
  - Progress, 2026-11-12. The first writer built the backend and the panel.
    - A SIMULATION opening is not refused for the cap. That mirrors the
      key-capability refusal, which checks LIVE only, and a simulated opening
      places no stop.
    - The refusal is recorded as a REJECTED delivery with a WARNING.
    - *Advisory, for SS.5/SS.6:* the cap is checked before the pool lock and
      not again inside it. An author widening the level in between would let
      one opening through above the new cap. The stop placed must use the
      same level the cap was checked against, so SS.5/SS.6 read it once and
      carry it.
    - A second writer is closing three gaps:
      - the public and held-seat views lacked the level, so the subscriber's
        slider was not capped;
      - the frontend types were optional;
      - there was no RED evidence for the code written before its tests.
    - Closed. The second writer added the level to the public and held-seat
      views and made the panel types require it. It ran 30 mutations; 4 of
      them went undetected and got new tests that now go red.
    - Commit `01c111c`. Gate green on the full backend suite (ruff, mypy,
      pytest exit 0) and the frontend (lint, 3878 tests).
    - Independent verifier (item 1, the migration): no blockers. It verified
      by reading, because DB-backed tests cannot reach PostgreSQL from a
      scratch worktree that has no `.env`. The parent re-ran
      `test_0040_strategy_stop_loss_pct.py` in the workspace: exit 0.
      Advisories:
      - `ChangeShare` refuses a request that re-sends the current leverage of
        a seat already above the cap;
      - a missing strategy on a leverage change now answers 404.
    - Deploy notes:
      - `POST /strategies` now requires `stop_loss_pct`, so a registration
        from the old panel fails between the API deploy and the panel move.
      - Count production seats above 9x before migrating: their live
        openings are refused from the deploy on.
        Counted on 2026-11-13: 0 seats that are not ENDED sit above 9x.
  - **Delivered.** Merged as #106 (`ec75f7e`) and deployed by the owner on
    2026-11-13 with three scripts piped over ssh from Git Bash (PowerShell has
    no `<` redirection):
    - Rehearsal on `sm_rehearsal_0040`, restored from
      `pre-0040-rehearsal-20261113T032457Z.dump`:
      - `0039 -> 0040`;
      - all 7 strategies at `10.00`;
      - `numeric(4,2)`, NOT NULL, default 10, and the CHECK present;
      - every other column of every strategy unchanged (md5 over all rows);
      - downgrade and re-upgrade clean;
      - the copy dropped.
    - API: 0 seats above 9x, then backup
      `pre-0040-deploy-20261113T032611Z.dump` and production `0039 -> 0040`,
      with 7 strategies at `10.00`. Both services `active`, and no ERROR or
      Traceback line.
    - Panel (pps.6): built by the assistant from a detached worktree of
      `origin/main` at `ec75f7e467d0`, 22 entries, SHA-256
      `547beff6a81338b08a13398508c8c0ca84ea140623f3503056cdb2b3a7c0d6a2`. The
      owner's block printed `OK`, `readable`, and both `bundle` and `checkout`
      at `ec75f7e467d0`.
- [x] SS.5 Bybit: the stop attached to the opening order, with the migration
  creating `protective_stops`. The resting stop is
  found by `parentOrderLinkId` and recorded. A failure closes the position at
  once. Risk: item 6 (live venue behaviour) and item 4.
  - Design, 2026-11-13, from a read-only code map.
    - The level is carried in memory from the policy snapshot that the
      cap was checked against (`process_signal.py`, `_handle_consumes`):
      `PlaceCommand.stop_loss_pct`, then `OpenOrderSpec.stop_loss_pct`. The
      strategy is never re-read for it, which closes the SS.3 advisory.
    - `FuturesMarketOrder` gains `stop_price: Decimal | None`. The Bybit
      `build_open_order` computes it from the mark price it already sizes
      against, rounded to the tick away from the entry, by one domain helper
      in `execution/domain/futures_order.py`. `place()` sends `stopLoss`,
      `slTriggerBy: MarkPrice`, `tpslMode: Full` and `slOrderType: Market`.
    - Migration 0041 creates `protective_stops`, one row per opening
      attempt. It is written in the same transaction as the opening's
      execution attempt, before the order is sent, so a crash leaves a trace.
      Statuses: `PENDING`, `RESTING`, `FAILED`, `GONE`, `VOID`, `SIMULATED`.
      SS.7 adds `FIRED`.
    - A simulated opening writes a `SIMULATED` row with the level and places
      nothing. Binance writes no row until SS.6.
    - Settle enqueues a new job, `PROTECTIVE_STOP_CONFIRM`, in the same
      transaction as the opening's fills. A failure after settle's commit
      then cannot be lost to the `ALREADY_SETTLED` gate.
    - The job finds the conditional order whose `parentOrderLinkId` is the
      opening's `orderLinkId` (`/v5/order/realtime`, `orderFilter=StopOrder`,
      matched client-side):
      - found: `RESTING`, with its `orderId`;
      - ambiguous error: the job retries;
      - not found: `FAILED`, an ERROR line, and `ClosePosition` at once with
        no signal. A ledger already flat (`NothingRecordedYet`) marks it
        `GONE` instead. The `STOP_FAILED_CLOSED` row comes with SS.10.
    - An opening that ends without fills marks its row `VOID`.
  - Progress, 2026-11-13.
    - The first writer was cut by the 5-hour usage limit with two tests in
      RED. A fresh writer finished from the working tree: the `FAILED` mark
      is staged, not committed, and rides `ClosePosition`'s own commit. A
      close that cannot be built rolls it back, so the stop stays `PENDING`
      and the job's retry looks again.
    - Gate on `27c2ab0`: `ruff`, `mypy src` and the full `pytest`, exit 0.
    - Independent verifier (items 1, 4 and 6), against `8db8988`: no
      blockers.
      - Every `ClosePosition` outcome commits the mark: PLACED, refused,
        NOT_CLOSABLE, and an ambiguous place, whose retry then skips.
      - A redelivered settle enqueues one confirm. `VOID` is set only on a
        definitive refusal and on settle's no-order path.
      - Binance, Pionex and the fake exchange build and send what they did.
      - 15 hand mutations, 15 caught.
    - Advisories, not fixed here:
      - A FAILED stop whose close is refused, or is dust, leaves the
        position open without a stop. Only `ClosePosition`'s ERROR line says
        so. SS.10's `STOP_FAILED_CLOSED` event is where the user learns it.
      - One empty read of `/v5/order/realtime` closes the position. Run 4
        found the stop resting as soon as the fill exists, and the job runs
        after settle, so no retry was added.
      - That read takes the first page only (20 orders per symbol). One-way
        mode holds one position per symbol, so a miss is unlikely.
      - The confirm job stages its UPDATE on the stop row before it locks
        the reservation row. No concurrent pair takes both today.
      - A `SIMULATED` row records the level, with `trigger_price` NULL.
    - The Binance DOGE example in the spec gave 0.059706 on a 0.000010 tick.
      That is not a multiple of the tick: corrected to 0.059700 for SS.6.
  - Delivered, 2026-11-13: PR #107, merge `5d6931638709`, with the panel fix
    for the stop level editor (`8db8988`). The owner ran the three steps from
    Git Bash.
    - Rehearsal on `sm_rehearsal_0041`, restored from a fresh backup: 0040 to
      0041; `protective_stops` empty, with its 9 constraints and 4 indexes;
      `execution_attempts` (50 rows) and `reservations` (26) hashed unchanged;
      the downgrade dropped the table and the re-upgrade made it again. The
      copy was dropped.
    - Production: backup `pre-0041-deploy-20261113T144140Z.dump`, 0040 to
      0041, `protective_stops` empty, both services `active`, and no ERROR
      or Traceback line after the restart.
    - Panel (pps.6): built by the assistant from a detached worktree of
      `origin/main` at `5d6931638709`, 22 entries, SHA-256
      `f05b56eb199c7b4a23e2eed5a05a55fdc2fd5d5fce4f1971fc1d2c340554732a`. The
      owner's block printed `OK`, `readable`, and both `bundle` and `checkout`
      at `5d6931638709`.
- [ ] SS.6 Binance: the algo stop right after the fill, with `clientAlgoId`
  recorded first, `-2013` retried, an unknown outcome resolved by reading
  back, and a failure closing at once. Risk: items 4 and 6.
  - Design, 2026-11-13, from a read-only code map.
    - Migration 0042 adds `protective_stops.client_stop_id` (nullable, unique
      where set).
    - Adapters declare `places_stop_after_fill`: Binance yes, every other
      adapter no. `PlaceOrder` writes a `PENDING` row for a live Binance
      opening, with a fresh UUID as `client_stop_id` and no trigger price.
      It goes in the attempt's own transaction, so the `clientAlgoId` is
      recorded before any algo request.
    - Settle enqueues `PROTECTIVE_STOP_CONFIRM` as in SS.5. For a venue that
      places after the fill, the job does this:
      - With no trigger price recorded, it reads the opening's fills through
        `fetch_fills` and takes their volume-weighted average as the entry. The
        adapter turns that into the trigger, rounded to the tick away from the
        entry (`protective_stop_price`). The trigger is committed, then
        `POST /fapi/v1/algoOrder` is sent:
        - `algoType` CONDITIONAL and `type` STOP_MARKET;
        - `side` opposite the position;
        - `workingType` MARK_PRICE and `closePosition` true;
        - the recorded `clientAlgoId`.
      - With a trigger price already recorded, an earlier POST may have
        reached the venue. The job first reads the stop back with
        `GET /fapi/v1/algoOrder?clientAlgoId=`. The Binance documentation
        accepts either id (checked 2026-11-13). A `-2013` is retried 5 times,
        2 s apart, with an injectable sleep. Found in any status, the stop is
        `RESTING`, and SS.7's watcher reads its status. Still `-2013` after
        the retries, the POST is sent again with the same `clientAlgoId` and
        trigger.
      - An acknowledged POST is `RESTING` at once, with its `algoId`. It is
        not read back, so `-2013` cannot hit the normal path.
      - An ambiguous error (the stricter `_is_definitive_setting_refusal`
        rule) makes the job retry. A definitive refusal takes SS.5's path:
        `FAILED`, an ERROR line, and `ClosePosition` at once.
    - Bybit's path is unchanged.
  - Progress, 2026-11-13.
    - The writer built it as designed, plus three choices:
      - The confirm job branches on the row (`client_stop_id` set) rather
        than on the adapter.
      - Empty fills raise `FillsNotPublishedYet`, so the job retries and
        closes nothing.
      - One mixin, `NoAfterFillStop`, gives Bybit, Pionex and the fake
        exchange the flag set to false and refusing calls.
    - This supersedes SS.5's "Binance writes no row until SS.6": a live
      Binance opening now writes a `PENDING` row.
    - Gate on `03ba6c7`: `ruff`, `mypy src` and the full `pytest`, exit 0.
    - Independent verifier (items 4 and 6), against `75de478`: no blockers.
      - Crash safety at each step leaves exactly one stop.
      - Every ambiguous error retries.
      - SIMULATED still wins over the after-fill flag.
      - Bybit, Pionex and the fake exchange are untouched.
      - 19 hand mutations: 18 caught, one survived.
    - Fixed after the verifier:
      - The surviving mutation: the read-back's ambiguity test now covers
        503/-1008, 429/-1003 and 408. That rules the lax rule out on the
        GET, as it already was on the POST; a mutation proved it.
      - A POST sent again may be refused because the first request did
        arrive and its read only lagged past the retries, for example as a
        duplicate `clientAlgoId`. Binance's answer to a duplicate id is
        unverified. The stop is now read once more before anything is
        closed, so a protected position is not closed for it. A first POST
        that is refused is not read back.
    - Advisories, not fixed here:
      - A stop the read never sees and Binance refuses again is `FAILED`
        and closed. If it did rest, it is left at the venue: nothing cancels
        it. A `closePosition` stop on a flat position cannot open one, and
        SS.7's watcher reads it.
      - `place_stop_order`'s own refusals, of an invalid id or a
        non-positive trigger, carry no code, so they read as ambiguous and
        would retry for ever. A UUID4 and a priced trigger cannot reach
        them.
- [ ] SS.7 The stop watcher job, with the migration adding a cause to
  `execution_attempts` (SIGNAL / STOP / SAFETY_CLOSE / MANUAL):
  - fills booked under the allocation with cause STOP, plus `STOP_FIRED`;
  - gone stops marked;
  - `ALREADY_CLOSED_BY_STOP` and `ALREADY_FLAT` in `ClosePosition`;
  - reconciliation stays quiet on a fired stop.

  Risk: items 1 and 4.
- [ ] SS.8 Disable refused on exposure, under the archive's locks, with the
  lock-hold concurrency test on PostgreSQL. Plus the sweep's safety close of
  stopped strategies with positions. Risk: items 3 and 4.
- [ ] SS.9 "Close now": the API and the panel's confirmation dialog, cause
  MANUAL, idempotent while in flight, with its event.
- [ ] SS.10 The `safety_events` table, its API and the panel list, in EN and
  ES, and the `OPENING_REFUSED_LEVERAGE_CAP` event from SS.3's refusal.
- [ ] SS.11 Docs: CLAUDE.md's venue facts on stops, and the panel's help text.

## Log

- L1 (owner, 2026-11-12): "Si un autor deshabilita su estrategia, y además
  altera o desactiva su alerta de tradingview, qué medida de seguridad hay para
  un suscriptor?"
- L2 Correction, the same day: the assistant had said `Leave` closes the
  subscriber's position. It does not (`leave.py:16`). No in-app close exists
  for a subscriber.
- L4 Correction, 2026-11-12: the first draft of `protective-stop` refused live
  Pionex openings (`STOP_NOT_SUPPORTED`). The assistant wrote it from the
  presence of `pionex_exchange.py`, without checking its registration. No
  Pionex adapter is registered (`main.py:1203-1212`), and no Pionex key can be
  saved, so that path cannot happen. The owner asked "No se pueden vincular
  claves API de Pionex de todos modos, por lo que no termino de entender cómo
  se rechaza una apertura de Pionex". The requirement now states the adapter
  contract instead.
- L3 (owner, 2026-11-12): "Si, va a haber que planificar medidas de seguridad
  para los suscriptores. Un cierre manual no puede ser la única medida de
  seguridad. Un usuario que no entra al panel no puede cerrar a mano."
