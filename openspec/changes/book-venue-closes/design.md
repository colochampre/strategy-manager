<!-- Materialized verbatim from Engram topic sdd/book-venue-closes/design (observation #234) on 2026-09-23. Engram stays the mirror; edit here first. -->

# Design: Book venue-originated closes (reconciliation slice 2)

SDD phase DESIGN, 2026-09-23. HEAD `3fec07a`. Preflight: auto / engram / single-pr / 800.
Follows [[sdd-book-venue-closes-proposal]] (#231), bound by [[book-venue-closes-owner-decisions]] (#232), correcting two points in [[sdd-book-venue-closes-explore]] (#230).

Over the generic 800-word design budget on purpose: `openspec/config.yaml` `rules.design` requires the hexagonal layer of every new component, and the phase brief enumerated twelve decisions that must each be justified. Style matches [[sdd-design-open-position-safely]].

## Technical approach

A CONFIRMED attributable discrepancy is swept by a NEW job (`reconciliation.prepare_booking`), which fetches that market's venue fills in a time window, matches the unrecorded ones against the observed delta, and FREEZES a `booking_proposals` row. Nothing reaches the ledger. The owner reads the frozen snapshot in the SPA, confirms twice, and `ApproveBooking` writes one `execution_attempts` row (`origin='VENUE'`, `status='FILLED'`, deterministic `client_order_id`) plus N `ledger_entries` through the existing `RecordFill`. Rejection writes nothing and leaves the discrepancy open.

```
reconciliation.scan (30s, unchanged) ──→ reconciliation_discrepancies
                                                 │ CONFIRMED + ATTRIBUTABLE_*
                                                 ▼
reconciliation.prepare_booking ──→ VenueFillReaderPort ──→ venue (read key)
        │  match_fills (domain, pure)  │
        │  already_recorded (ledger)   │
        ▼                              │
   booking_proposals (PENDING, frozen) ┘        NOTHING written to the ledger
        │
        │  GET /reconciliation/bookings          POST .../{id}/reject → REJECTED
        ▼                                                 (zero ledger rows)
   SPA: list → confirm dialog → POST .../{id}/approve
        │
        ▼  ApproveBooking: FOR UPDATE → freshness → SAVEPOINT
   execution_attempts (1, VENUE/FILLED) + ledger_entries (N)   one transaction
```

## Component inventory, with hexagonal layer

| Component | Layer | Notes |
| --- | --- | --- |
| `BookingState`, `ProposedFill`, `match_fills()`, `BOOKABLE_KINDS` | **domain**/reconciliation (`domain/booking.py`) | Pure `Decimal`, no I/O, no `market_key` import — receives normalised symbols |
| `ExecutionOrigin` StrEnum + two new `__post_init__` invariants | **domain**/execution (`domain/execution_attempt.py`) | Mirrors the new CHECK |
| `VenueFill` DTO, `VenueFillReadError`, `VenueFillReaderPort`, `VenueFillReaderRegistryPort` | **application**/reconciliation (`ports.py`) | Consumer-declared, mirroring `VenuePositionReader*` exactly |
| `RecordedFillIdsPort`, `AllocationOwnerPort`, `InFlightClosePort`, `BookingProposalRepositoryPort`, `BookingWritePort` | **application**/reconciliation (`ports.py`) | All consumer-declared |
| `PrepareBooking`, `ApproveBooking`, `RejectBooking`, `ExpireBookingProposals` | **application**/reconciliation | |
| `BookingPrepareHandler` | **application**/reconciliation | Own `_SkipAnnouncement`; DRY_RUN skip + successor enqueue |
| `ReadRecordedFillIds` | **application**/ledger | Implements `RecordedFillIdsPort`, sibling of `ReadSymbolPositions` |
| `BybitVenueFillReader`, `BinanceVenueFillReader`, `VenueFillReaderRegistry` | **infrastructure**/reconciliation | Siblings of the position readers |
| `BybitReadOnlyClient.fills_in_window`, `BinanceReadOnlyClient.fills_in_window` | **infrastructure**/shared | On the READ-only clients; a fill read is a read |
| `SqlAlchemyBookingProposalRepository`, `SqlAlchemyBookingWriter`, `AllocationOwnerAdapter`, `InFlightCloseAdapter`, `BookingProposalRow` | **infrastructure**/reconciliation | The writer owns the SAVEPOINT and the `IntegrityError` translation |
| routes on `/reconciliation` | **infrastructure**/reconciliation (`router.py`) | Auth already structural on the router |
| `shared/api/client.ts`, `shared/auth/token-store.ts`, `TokenGate`, `features/bookings/*` | frontend | |
| `scripts/check_venue_fill_windows.py` | dev tool, not shipped code | GET-only |

## Decisions

### 1. Booking attaches as a separate swept job, not inside `_scan_pool`

**Choice**: `JobKind.RECONCILIATION_PREPARE_BOOKING = "reconciliation.prepare_booking"`, self-scheduling like the scan, sweeping still-open CONFIRMED rows of the two bookable kinds.
**Rejected**: attaching at the CONFIRMED transition inside `scan_pools.py:227-239`; one job per discrepancy.
**Why**: `ScanPools`' docstring states its write boundary — it never touches `ledger_entries`/`execution_attempts` — and a second remote call with its own rate budget, its own failure mode and its own cadence does not belong in a 30-second compare loop. A job per discrepancy would need the same dedup the partial unique already gives.

### 2. `execution_attempts.origin` — migration 0022

`origin Text NOT NULL DEFAULT 'SYSTEM'`, `CHECK origin IN ('SYSTEM','VENUE')`.

**Existing rows**: backfilled by the ADD COLUMN default. Correct by construction — every pre-0022 row was built by `PlaceOrder` or `ClosePosition`, both of which submit to a venue.
**The DB default stays; the Python field has NO default.** `ExecutionAttempt.origin: ExecutionOrigin` is required, so mypy forces all three constructors to name it. The DB default makes the migration one statement; the missing Python default is the discipline the DB default cannot provide.
**Every place that constructs an attempt today** (verified by grep, these are all of them): `execution/application/place_order.py:107-125` → SYSTEM; `execution/application/close_position.py:140-171` → SYSTEM; `execution/infrastructure/repository.py:46` `insert()` maps it and `:18` `_to_domain` reads it back; test fixtures constructing `ExecutionAttempt` directly. New: `ApproveBooking` → VENUE.
**Two new domain invariants** in `__post_init__` beside the existing two: `origin is VENUE` ⇒ `status is FILLED`, and `origin is VENUE` ⇒ `closes_allocation_id is not None`. A venue-originated OPEN is `NO_MATCHING_ALLOCATION`, which is unbookable, so both hold; stated as invariants they make a future auto-booking bug fail at construction.
**Downgrade REFUSES** while any VENUE row exists, naming the count and ids (0012/0021 precedent) — and offers **no `-x` force flag**, deliberately unlike 0021's `force_failed_close_drop`. That escape deletes FAILED attempts which recorded no fills; a VENUE attempt always has ledger rows behind it, and no flag should offer to delete history the append-only trigger itself forbids deleting.

### 3. `booking_proposals` — migration 0023

Frozen at prepare, never updated: `discrepancy_id` (FK, no cascade — evidence, same argument 0020 makes), `exchange`/`venue`/`settlement_currency` (composite FK to `capital_pools`), `symbol` (the MARKET KEY), `kind` (CHECK restricted to the TWO bookable kinds — the table cannot hold an unbookable one), `allocation_id` FK→`reservations`, `strategy_id` FK→`strategies`, `side` CHECK IN ('BUY','SELL'), `quantity` Numeric(38,18) CHECK > 0, `observed_venue_net_base`, `observed_ledger_net_base`, `observed_allocation_ids uuid[]`, `fills JSONB`, `client_order_id Text`, `expires_at`, `prepared_by_job_id` (a `jobs.id`, NO FK — 0020's reasoning), `created_at`.
Mutable, exactly once: `state`, `decided_at`, `decided_by`, `decision_reason`, `execution_attempt_id` FK→`execution_attempts`.

States `PENDING | APPROVED | REJECTED | SUPERSEDED | EXPIRED`. CHECKs: `state='PENDING' OR decided_at IS NOT NULL`; `state<>'REJECTED' OR btrim(coalesce(decision_reason,''))<>''`; `state='APPROVED' OR execution_attempt_id IS NULL`.

**The frozen snapshot's exact shape** — `fills` is a JSONB array ordered by `(filled_at ASC, exchange_fill_id ASC)` with the tiebreak comparing ids as `(len(id), id)`, which equals numeric order for Binance's integer trade ids and stays total for Bybit's `execId` strings. Every element:

```json
{"exchange_fill_id":"...","exchange_order_id":"..."|null,"side":"SELL",
 "quantity":"0.5","price":"142.37","fee":"0.03913","fee_currency":"USDT",
 "filled_at":"2026-09-23T01:02:03.456000+00:00"}
```

All numbers are STRINGS — a JSON number has already lost precision, the exact rule `_amount()` enforces on the wire, and these land in an append-only ledger. **Rejected**: a child `booking_proposal_fills` table. The snapshot is an immutable blob shown to a human and replayed once; it is never joined, filtered or aggregated, and a child table adds a second write path to keep frozen.

**Indexes**: `ux_booking_proposals_pending_per_discrepancy UNIQUE (discrepancy_id) WHERE state='PENDING'` (at most one live proposal per discrepancy — this IS prepare's idempotency and the anti-re-propose fix); `ix_booking_proposals_pending (state, expires_at) WHERE state='PENDING'` (the list endpoint and the expiry sweep); `ix_booking_proposals_discrepancy (discrepancy_id)` — the REJECTED-suppression lookup reads every state, so the partial index does not serve it.

**Concurrency without a lock table**: the repository's only UPDATE is `... WHERE id=:id AND state='PENDING'`, preceded by `SELECT ... FOR UPDATE` (the shape `ReservationGatewayPort.get_for_update` already documents). Two racing approvals: the second blocks on the row, then reads a non-PENDING state and returns `ALREADY_DECIDED` having written nothing.

**Downgrade**: `DROP TABLE` unconditionally. It holds no money data — only proposals — and an APPROVED row's real consequence lives in `execution_attempts`/`ledger_entries`, which 0022's guard protects. No refusal clause, and the migration says why, so the asymmetry with 0022 is not read as an oversight.

### 4. Deterministic `client_order_id`

`vnu:{exchange}:{venue_order_id}`, falling back to `vnu:{exchange}:fill:{earliest_exchange_fill_id}` under the canonical ordering above. Computed at PREPARE and frozen, so approval writes exactly the id the dialog showed.

> **Superseded during apply (2026-09-23, unit 4a review): the id is ALWAYS `vnu:{exchange}:fill:{earliest_exchange_fill_id}`.** A venue order filling across two scans (a limit close filled in pieces, a staged liquidation) yields two bookings. Keyed on the order id, both would share one `client_order_id`, so the second approval would collide and be read as a harmless replay: SUPERSEDED, zero writes, and that close could never be booked. A fill is recorded at most once, so the earliest unrecorded fill names exactly one booking. A replay of the same proposal still collides, because the id is frozen. The order ids stay in the snapshot and in the ledger. This also makes the "venue reports no order id" fallback below moot for the id; the tolerant parser is still needed for the snapshot.

- `execution_attempts.client_order_id` is `Text`, unbounded; the 36-character limits live in the submit adapters and a VENUE attempt is never submitted.
- The `:` in `vnu:` is **not** in Bybit's `_ORDER_LINK_ID_ALPHABET`, so any future path that tried to submit a VENUE attempt raises `BybitApiError` before an order leaves the process. Fail-closed by construction, not by accident.
- `exchange` is embedded, so two venues issuing the same order id cannot collide — the same reason 0019 widened `ux_ledger_exchange_fill` to include `exchange`.
- **Venue reports no order id**: the window-fetch DTO makes `exchange_order_id` `str | None` and adds a tolerant `_parse_window_execution` to each client; the ORDER-scoped `_parse_execution` stays strict and untouched, because its caller resolved the order by id so an order id is guaranteed there. Today both strict parsers RAISE on a missing `orderId` (`_text`/`_integer`), which is why a separate parser rather than a loosened one. **Probe item (d) decides whether the fallback is ever reachable**; if liquidations do carry an order id, the fallback stays as tested four-line code rather than being deleted — it is the only thing between a NOT NULL column and a crash on the one fill nobody rehearsed.

### 5. The match rule

`match_fills(delta_base, fills, already_recorded_ids)` (domain, pure). The unrecorded fills' SIGNED sum must equal `delta_base = venue_net_base − ledger_net_base` — the generated column 0020 already stores. For `ATTRIBUTABLE_FULL_CLOSE` (V=0) that is `−L`: a long +0.5 needs SELL fills summing −0.5. Any of these refuses to propose, with a WARNING and no row: sum ≠ delta; mixed sides among the unrecorded fills; zero unrecorded fills; a fill whose quantity is ≤ 0.
Fee handling uses the IDENTICAL rule `ReadSymbolPositions` applies (subtract only when `fee_currency` differs from the settlement currency), provably a no-op on USDⓈ-M. A non-USDT-settled pool must re-verify before booking is enabled there.

> **Added during apply (2026-09-23, unit 4b review): exactly ONE open allocation, or no proposal.** Rung 2 of `classify()` returns `ATTRIBUTABLE_FULL_CLOSE` for ANY number of open allocations: a flat venue closed all of them. The explore (Q4) and this design assumed it always leaves one candidate, and that holds only for one allocation. With several, the first implementation booked the whole close against `open_allocation_ids[0]`, which drove that allocation negative and left the others open. That is a permanent corruption of an append-only ledger, and it logged nothing. Splitting the close would need an invented FIFO or pro-rata rule, which the proposal puts out of scope. So `PrepareBooking` refuses with a WARNING, and `ck_booking_proposals_single_allocation` stops the table from holding such a proposal at all (`cardinality(observed_allocation_ids) = 1 AND observed_allocation_ids[1] = allocation_id`). The single-allocation full close, the commonest case, is unaffected.

### 6. `ApproveBooking` — transaction boundary and the two expected IntegrityErrors

One transaction:
1. `proposals.get_for_update(id)` → row lock. Not PENDING → `ALREADY_DECIDED`, zero writes.
2. DRY_RUN → refuse (also refused at the endpoint).
3. Freshness re-check → mismatch → `mark_state(SUPERSEDED)`, commit, return `SUPERSEDED`. Expired → `EXPIRED`.
4. `usd_rate = usd_rates.usd_rate(Currency(settlement_currency))`.
5. `BookingWritePort.write(attempt, fill_records)` → `WRITTEN | ALREADY_RECORDED`.
6. `WRITTEN` → `mark_state(APPROVED, execution_attempt_id)`. `ALREADY_RECORDED` → `mark_state(SUPERSEDED, reason)` + WARNING.
7. commit.

**Exactly two IntegrityErrors are expected outcomes, identified by CONSTRAINT NAME, not by message text**: `execution_attempts_client_order_id_key` (a replayed approval colliding with itself) and `ux_ledger_exchange_fill` (someone else already recorded this fill). Everything else — an FK violation, a CHECK violation, the append-only trigger — is a FAILURE and propagates. A bare `except IntegrityError` here would swallow a bug that writes the wrong `strategy_id`.

**The SAVEPOINT is load-bearing, not tidiness.** Any error aborts a Postgres transaction, so without `session.begin_nested()` the subsequent `mark_state(SUPERSEDED)` would itself fail on an aborted transaction and crash the request — turning the expected outcome into the failure the proposal forbids. The savepoint and the `IntegrityError` translation live in `SqlAlchemyBookingWriter` (infrastructure), so SQLAlchemy never reaches the use case. **Rejected**: rollback-the-whole-transaction-and-reopen — it releases the row lock and re-reads the world, reintroducing the race the lock removed.

### 7. The freshness re-check — exactly what is compared

Re-read the discrepancy by `discrepancy_id` and compare against the proposal's frozen columns:
(a) `resolved_at IS NULL`; (b) `status = 'CONFIRMED'`; (c) `kind` equal; (d) `venue_net_base` equal; (e) `ledger_net_base` equal; (f) `sorted(open_allocation_ids)` equal (sorted, because that array's order comes from a dict iteration in `_ledger_by_market` and is not a contract); (g) `InFlightClosePort.submitted_for(pool, strategy_id, symbol)` is False; (h) `expires_at > now`.

(c)–(e) are the proposal's "Observation triple byte-identical", made concrete as **Decimal VALUE equality** — `Numeric(38,18)` round-trips with a scale-dependent exponent, and `next_consecutive_scans` already documented this exact choice for this exact triple.
**NOT compared**: the `fills` JSONB (a venue may legitimately re-page the same fills in another order), `last_observed_at`, `consecutive_scans`, `last_scan_id`.
(g) uses a reconciliation-owned one-method port whose adapter calls `SqlAlchemyExecutionAttemptRepository.submitted_for_strategy_symbol` — which already exists and already merges spellings. No new SQL, and no reconciliation→`signals` dependency.

### 8. `usd_rate` provenance without touching `ledger_entries`' shape

Resolved inside `ApproveBooking`'s transaction, in the same instant the row is inserted. **The gap is already computable from existing columns**: `ledger_entries.filled_at` is the venue's, `ledger_entries.created_at` is the rate's observation time. No new ledger column. `origin='VENUE'` on the attempt is the queryable predicate that says "this row's `usd_rate` is a booking-time rate, not a fill-time rate" — the column's second justification, and the one that makes owner decision 2 auditable rather than merely documented.

### 9. The fill fetch

```python
@dataclass(frozen=True, slots=True)
class VenueFill:
    exchange_fill_id: str
    exchange_order_id: str | None
    symbol: str
    side: str              # 'BUY' | 'SELL', normalised by the adapter
    quantity: Decimal      # always positive
    price: Decimal
    fee: Decimal
    fee_currency: str
    filled_at: datetime    # tz-aware UTC

class VenueFillReaderPort(Protocol):
    exchange: str
    venues: frozenset[str]
    async def fills_in_window(
        self, pool: PoolKey, symbol: str, start: datetime, end: datetime
    ) -> list[VenueFill]: ...
```

**`VenueFill` carries `side`; `execution.domain.fill.Fill` does NOT** (seven fields, side is not among them) — an order-scoped fetch inherits the side from its order, a window fetch has no order. This corrects explore #230 Q3's claim that the existing types already carry every field needed. A new DTO is required; it is not reuse.

`VenueFillReadError` is the ONE swallowable error, mirroring `VenuePositionReadError`: one market's failed fetch skips that discrepancy, not the sweep. A registry lookup failure for an unserved pool is NOT swallowed.

**Credentials follow each venue's existing position-read precedent unchanged**: Bybit signs with the VAULT credential (as `main.py:998-1010` already does for its position read), Binance with the `.env` read-only key (`binance_credentials_from_settings`). No new credential decision.

**Bybit**: `GET /v5/execution/list` + `category=linear`, `symbol`, `startTime`, `endTime`, `limit`, `cursor`; paginate on `nextPageCursor` while non-empty, bounded by `max_pages`, RAISING `VenueFillReadError` at the bound — silently truncating a fill list produces a proposal that under-books a close, which is worse than no proposal.
**Binance**: `GET /fapi/v1/userTrades` + `symbol`, `startTime`, `endTime`, `limit`; on a full page, advance `startTime` to the last trade's time, INCLUSIVE, and de-duplicate by `exchange_fill_id`; a full page yielding zero new ids RAISES; same `max_pages` bound.

> **Corrected during apply (2026-09-23).** This paragraph originally said "+ 1ms". That silently drops every trade sharing the last trade's millisecond that fell onto the next page, and it would have left the de-duplication with nothing to do. The probe settled the other question: `fromId` and a time range do NOT combine (HTTP 400, -1106). **Unverified assumption:** with more fills than a page, Binance returns the OLDEST first. Nobody could observe this, because there were no fills under DRY_RUN. If it is wrong, fills in the middle go missing, the sum no longer equals the delta, and `match_fills` refuses with a WARNING. So it cannot write a wrong booking.

**Fetch window** `[first_observed_at − pad, now]` — `first_observed_at`, not `confirmed_at`, because the fill happened at or before the FIRST scan that saw the disagreement. If the span exceeds the venue's accepted maximum, PrepareBooking refuses and logs WARNING rather than fetching a truncated window.

### 10. The live probe — `backend/scripts/check_venue_fill_windows.py`

`check_` rather than `measure_` (it answers shape and acceptance, not only a budget), spanning both venues like `measure_reconciliation_rate_limits.py`. GET-only; places nothing; reuses `probe_credentials.announce`/`vault_credentials` so it PRINTS WHICH KEY it is running as (CLAUDE.md's two-keys lesson). `cd backend && uv run python scripts/check_venue_fill_windows.py`. Run **on the worker's host** — Binance weight is per IP.

It must answer, before ANY interval or window constant is fixed:
(a) max accepted window span per venue (bisect 1d/7d/8d/30d/90d; report the first refusal and its code);
(b) pagination shape and page size; whether an empty window returns `[]` or errors; on Binance, whether `fromId` and `startTime`/`endTime` combine;
(c) rate-limit weight per call, as the DIFFERENCE between two responses' headers, against `reconciliation.scan` at 30s and `balance.sync` at 60s;
(d) whether a LIQUIDATION fill appears on this endpoint and whether it carries an order id — this alone decides whether the `client_order_id` fallback is reachable;
(e) venue server time vs host clock, which sets `pad`;
(f) **added by this design, a sixth item the proposal did not list**: whether each venue's configured key is ACCEPTED on the fill endpoint at all.

Until it runs, `reconciliation_booking_prepare_interval_seconds`, `..._window_pad_seconds`, `..._max_span_seconds`, `..._page_limit` and `..._max_pages` have NO defaults in this design.

### 11. Rejection semantics and suppression

Reject: row lock, `REJECTED` + required reason + actor + `decided_at`, ZERO ledger rows, the discrepancy row **untouched** (not deleted, not resolved), one WARNING — a rejected-but-real discrepancy means the ledger is knowingly wrong.
Suppression: `PrepareBooking` skips a discrepancy holding a REJECTED proposal whose frozen `(kind, observed_venue_net_base, observed_ledger_net_base)` equals the current `Observation`, by Decimal value equality. **The suppression key is the Observation triple, never the fill snapshot.** If the disagreement moves, `consecutive_scans` already resets, the triple differs, and the genuinely different situation earns a fresh proposal.
Expiry: `ExpireBookingProposals` runs inside the prepare handler before the sweep, marking `state='EXPIRED'` where `state='PENDING' AND expires_at <= now` (24h default, configurable). Approval also refuses an expired-but-unswept proposal via check (h).

### 12. Admin endpoints and the frontend

On the EXISTING `/reconciliation` router — auth is already structural there, which is that module's documented point.
- `GET /reconciliation/bookings?state=pending&limit=100` → the frozen snapshot in full.
- `POST /reconciliation/bookings/{id}/approve` → `{outcome, execution_attempt_id, ledger_entries_written}`; 404 unknown; 409 not PENDING; **503 under DRY_RUN**.
- `POST /reconciliation/bookings/{id}/reject` body `{reason}` → 200; 422 empty reason; 409; 503.

503 rather than 403: the endpoint exists and the caller is authorised; the DEPLOYMENT is configured not to do this. 403 would say "you may not", which is false — the owner may.

**Where the bearer token lives at runtime**: `shared/auth/token-store.ts`, a Zustand store persisted to `localStorage` under `sm.admin_token`; pasted once through `TokenGate`, sent as `Authorization: Bearer`; cleared by `apiFetch` on any 401, which re-renders the gate. **NEVER `import.meta.env`** — that bakes a trade-authorising token into a bundle served off the VPS. `shared/api/config.ts` DOES read `import.meta.env.VITE_API_BASE_URL ?? ""` (empty = same origin): a base URL is not a secret, and that distinction is exactly the line owner decision 1 drew.

**The second confirmation shows the exact rows to be written**, rendered from the proposal's own frozen snapshot and never recomputed client-side: one line per ledger row (`side · quantity · price · fee fee_currency · filled_at · exchange_fill_id`) plus the single attempt line (`origin=VENUE · status=FILLED · client_order_id · allocation_id · strategy`). `ConfirmBookingDialog`'s button is the ONLY caller of the approve mutation. `usd_rate` is deliberately absent, with one i18n'd line saying the rate is read at write time and is metadata, not PnL (rule 7).

**No router library is added.** `App.tsx`'s `active` stops being a constant, `NAV_ITEMS` gains `bookings`, and the existing `href="#..."` anchors drive a `useState` seeded from `location.hash`. A routing dependency for a four-view shell is not earned yet.
**`fetch` is stubbed with `vi.stubGlobal`**; MSW is not installed and six tests do not justify the dependency.

### 13. Symbol spellings — normalise at every boundary

- The proposal's `symbol` stores the MARKET KEY, like the discrepancy row, for 0020's reason.
- The venue is asked with `strip_contract_marker(symbol)`; a venue lists `STXUSDT`, never `STXUSDT.P`.
- The fill's echoed `symbol` is passed through `market_key()` before any comparison.
- `already_recorded` keys on `(exchange, venue, exchange_fill_id)` and never on symbol, so it cannot reintroduce the mismatch.
- The attempt and the ledger rows are written with the proposal's MARKET KEY. **Consequence, stated**: a booked close may carry a different spelling from the open it nets against — exactly the case `_ledger_by_market`, `market_spellings()` and `symbol_holdings` already merge, so every projection nets them.
- `market_key` stays in `application/` (it imports `execution.domain.market_symbol`); `domain/booking.py` must not import it and receives already-normalised symbols.
- **Testing rule, mandatory, from [[bug-reconciliation-symbol-spelling-mismatch]]**: every test crossing one of these boundaries uses a DIFFERENT spelling on each side — the ledger fixture writes `STXUSDT.P`, the venue fake returns `STXUSDT`, the endpoint filter is queried with `stxusdt.p`. A test using one spelling everywhere proves nothing; that is precisely how the slice-1 bug survived to review.

### 14. Interaction with `open-position-safely`

**GHOST** → after approval the strategy's `net_base` is zero, `HoldingGuard.check` returns proceed at `holding_guard.py:126-127` and never reaches `_classify_divergence`. GHOST on that close stops recurring. This is the change's whole point.
**REAL** → unchanged. `classify_orphan` makes its own live venue read at guard time and never consults the discrepancy or proposal tables; a booked close simply removes the symbol from classification.
**AMBIGUOUS** → unchanged, and structurally so: the bookable kinds are disjoint from the partial-reduce case, which is `AMBIGUOUS_PARTIAL_REDUCE` and unbookable. No path turns an AMBIGUOUS into a proceed.
**`CloseOrphans`** → a fully-booked allocation nets to zero and is no longer returned by `symbol_holdings` (`HAVING net <> 0`), so it cannot act on it. The rule "never let `CloseOrphans` act on a VENUE-booked residual" is deliberately NOT built: it is unreachable today, and `origin` now exists to express it the day it is not.
**Race, booking vs a signal**: three guards, none a lock — freshness check (g); `ux_ledger_exchange_fill` (whoever inserts the fill second loses, and for approve that loss IS the SUPERSEDED outcome); `execution_attempts_client_order_id_key`. The reverse direction needs no guard at all: a PENDING proposal has written nothing, so the guard's reads are exactly what they would have been; worst case the signal is refused GHOST once more, which is today's behaviour.

### 15. The pool advisory lock — CONFIRMED, booking does not take it

1. The lock's invariant is "an availability READ and the reservation WRITE derived from it are one transaction" (rule 4). Booking performs neither — it writes `execution_attempts` and `ledger_entries` and touches neither `capital_pools.available` nor `reservations`. There is no read-then-write pair to serialize.
2. **Taking it would not remove the race it is imagined to remove.** The race is two writers recording the same venue fill. `AllocateCapital` and `ClosePosition` insert no ledger rows inside the lock; `SettleExecution` inserts them and takes no lock at all (verified — `settle_execution.py` acquires nothing). A booking holding the pool lock would still race `SettleExecution` exactly as it does now. The UNIQUE constraints are the real guard and would still be doing all the work.
3. Approval is human-paced; even scoped to the write transaction the lock would span a `usd_rate` provider call, and scoped wider it blocks every signal in the pool while a human reads a dialog.
4. It would create a reconciliation→allocation dependency on a lock primitive across a module boundary that does not exist, for a guarantee the constraints already give.

Overturning is justified only if booking ever writes a reservation or moves pool availability. It does not; the change that makes it do so takes the lock then.

### 16. DRY_RUN

- No proposals exist: `BookingPrepareHandler` gets the same hard skip as `ReconciliationScanHandler`, with **its own module-level `_SkipAnnouncement`** — sharing the scan's singleton would make the two chains cannibalise each other's one loud WARNING.
- No venue fill fetch (it is inside the skipped branch).
- Approve and reject refuse explicitly at BOTH the endpoint and the use case (a `dry_run: bool` constructor arg), logged WARNING. A 404-by-empty-table is not a safety property. Reject refuses too: under DRY_RUN no proposal can exist, so one that does means the mode changed under a live queue, and refusing both is the only reading that does not act on state from the other mode.
- **The REAL branch CANNOT be rehearsed under DRY_RUN, and no attempt is made to make it so.** `FakeVenueBook` holds `_nets: dict[tuple[str,str], Decimal]` — per-`(exchange, market)` NETS only. No exec ids, prices, fees, timestamps or sides. `inject()` manufactures a net delta, which is enough for a GHOST classification and structurally not enough to produce a `VenueFill`. Teaching it to keep a fill log is new fake machinery the proposal did not scope, so the booking path is proven by integration tests against real PostgreSQL with an in-test fake `VenueFillReaderPort` returning scripted fills — the same rigour `ScanPools` is held to — and DRY_RUN keeps its documented meaning: booking is off. **Consequence for the owner: there is no way to rehearse an approval end-to-end on the VPS before the first real one.** See Q3.

## Testing strategy

| Layer | What | How |
| --- | --- | --- |
| Unit | `match_fills` (sum equals delta, mixed sides, zero unrecorded, negative qty); the canonical fill ordering and the `(len, id)` tiebreak across both venues' id shapes; the `vnu:` id and its fallback; the two new `ExecutionAttempt` invariants; each freshness branch (a)–(h) | Pure, no DB |
| Unit | `PrepareBooking` refusals; rejection suppression on an equal vs a moved Observation; DRY_RUN refusal in both use cases; `caplog` level and fields | Fakes for every port |
| Integration | 0022 up/down/refusal; 0023 up/down; the PENDING partial unique; `ON CONFLICT DO NOTHING`; the `FOR UPDATE` CAS; a CONCURRENT double approval; both named IntegrityErrors surviving the SAVEPOINT; the append-only trigger still firing on an UPDATE attempt | **Real PostgreSQL**, per `rules.tasks` |
| Integration | Both fill readers against a stubbed transport: pagination, the `max_pages` raise, a missing `orderId`, an empty window | `httpx.MockTransport` |
| Integration | End-to-end: scan → CONFIRMED → prepare → proposal → approve → exactly 1 attempt + N entries → `symbol_holdings` nets to zero → `HoldingGuard` proceeds | Real DB, fake venue |
| Frontend | pending list, empty state, approve requires the confirm dialog, reject requires a non-empty reason, 401 clears the token, error path | Vitest + `vi.stubGlobal("fetch")` |

Every cross-boundary test uses a DIFFERENT spelling on each side (decision 13).

## Threat matrix

N/A — no routing, shell, subprocess, VCS/PR automation, executable-file classification, or process-integration boundary. The two new admin routes sit behind the existing structural `require_admin_token` dependency; the probe is a developer-run GET-only script, not process integration. The one security-relevant surface, the bearer token in a browser, is decided in decision 12.

## Migration / rollout

0022 (`origin`) and 0023 (`booking_proposals`) are additive and independent of each other. Production holds zero ledger rows and `DRY_RUN=true`, so both are trivial today and neither is trivial later — which is why `origin` is built first. Rollout is by unit; nothing is reachable until unit 7 lands the routes. Rollback per the proposal, with its stated asymmetry unchanged: **ledger rows written by an approved booking cannot be rolled back.**

## Unit split — 9 confirmed, 5 pre-split, 14 total

| # | Unit | Split point | Forecast |
| --- | --- | --- | --- |
| 1 | `execution_attempts.origin` | 0022 + ORM + domain enum + 2 invariants + no-force downgrade | 350–450 |
| 2a | **NEW — the live probe** | `check_venue_fill_windows.py` + its output, run | 250–350 |
| 2b | Venue fill-window fetch | `VenueFill` + port + both read clients + both readers + registry | 650–850 |
| 3a | `booking_proposals` schema | 0023 + ORM + migration tests | 450–550 |
| 3b | Proposal repository | 6 methods + DTOs + integration tests | 500–600 |
| 4a | Booking domain + small ports | `domain/booking.py` + 3 ports + `RecordedFillIds`/`AllocationOwner`/`InFlightClose` adapters | 400–500 |
| 4b | `PrepareBooking` | Use case + unit tests | 450–550 |
| 5 | Prepare wiring | JobKind + handler + `main.py` + 5 config values + `RECURRING_KINDS` + watchdog set + integration | 600–800 |
| 6a | `ApproveBooking` | + `BookingWritePort`/savepoint adapter + freshness + both collisions + concurrency test | 650–750 |
| 6b | `RejectBooking` + expiry | + suppression + `ExpireBookingProposals` | 450–550 |
| 7 | Admin endpoints | list / approve / reject + DRY_RUN 503 | 450–600 |
| 8 | Frontend client + auth | `apiFetch`, token store, `TokenGate`, 401 path | 500–650 |
| 9a | Bookings list view | View + card + nav rework + EN/ES | 500–600 |
| 9b | Confirm + reject dialogs | Dialogs + mutations + Vitest | 500–600 |

Bottom-up **6,700–8,400**, consistent with the proposal's "plan for 7,000–9,000" and derived independently rather than fitted to it.

**Certain to exceed 800 if NOT split — that is why they are pre-split**: original units 3 (~1,000), 4 (~950), 6 (~1,200), 9 (~1,050). **At risk even as one unit**: 2b (650–850) and 5 (600–800), and 5 is where the last change's overrun actually landed.
**Revisions to the proposal's split points**: the probe becomes a visible unit (2a) rather than an invisible precondition — it is ~300 lines of reviewable code, and treating that as free is exactly how the last forecast overran. Unit 5 is raised from 500–700 because `RECURRING_KINDS` and the watchdog's recurring set were not counted.
**Dependencies**: 1 ⟂ 2a→2b; 3a→3b; 4a needs 2b+3b; 4b needs 4a; 5 needs 4b; 6a needs 1+3b; 6b needs 6a; 7 needs 6b; 8 needs 7's contract only; 9a→9b need 8.

`Decision needed before apply: Yes` · `Chained PRs recommended: Yes` · `400-line budget risk: High`

## Open questions — for the owner, not decided here

1. **`VenueFill` must carry `side`, which `Fill` does not.** A new DTO is required; explore #230 Q3's "both already carry every field a `FillRecord` needs" is true for `FillRecord` and false for a window fetch, which has no order to inherit the side from. Decided as a correction, recorded so it is not re-litigated.
2. **The probe gains a sixth item** (key acceptance on the fill endpoint). Decided; flagged because the proposal listed five.
3. **No DRY_RUN rehearsal of an approval is possible** (decision 16). The first approval on the VPS will be the first one ever executed anywhere but a test. Mitigations: the integration suite, the frozen snapshot shown in full, the second confirmation. **The owner should confirm they accept this** rather than fund fill-log machinery in `FakeVenueBook`.
4. **Five constants have no defaults until unit 2a runs.** Expect a second, short decision round between 2a and 5.
5. **`execution_attempts_client_order_id_key` is Postgres's auto-generated name and this design did NOT verify it against the live schema** — 0005 used column-level `unique=True`, which does not name the constraint. An integration test must assert the name before 6a relies on it; if it differs, the collision detection keys on the real name. Stated plainly because guessing a constraint name is how a swallowed-outcome branch silently becomes a crash.
6. **Spelling of the booked close.** It is written under the MARKET KEY while its open may carry `.P`, so the ledger visibly holds two spellings for one position. Every projection merges them, so PnL is right. Recommendation: keep the market key (0020's argument — the row describes a market). The owner may prefer mirroring the open's spelling.
7. **The unit count moves 9 → 14 and delivery is `single-pr`.** That puts roughly 7,500 authored lines in ONE review, about 19x the 400-line budget. The split is for work units, not PR count. If the owner wants a reviewable PR, the natural chain is 1+2a+2b → 3a+3b+4a+4b+5 → 6a+6b+7 → 8+9a+9b.
