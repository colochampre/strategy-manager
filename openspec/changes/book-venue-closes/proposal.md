<!-- Materialized verbatim from Engram topic sdd/book-venue-closes/proposal (observation #231) on 2026-09-23. Engram stays the mirror; edit here first. -->

# Proposal: Book venue-originated closes (reconciliation slice 2)

SDD phase PROPOSE, 2026-09-23. HEAD `3fec07a`. Preflight: auto / engram / single-pr / 800.
Follows [[sdd-book-venue-closes-explore]] (#230) and [[sdd-propose-detect-venue-originated-position-changes]] (#182).

## Intent

Slice 1 ships detection: `reconciliation.scan` records `ATTRIBUTABLE_SINGLE_ALLOCATION` / `ATTRIBUTABLE_FULL_CLOSE` verdicts and acts on none of them. So a venue stop-loss, a liquidation or a manual close in the exchange app still leaves the ledger believing a position is open, forever. Every later signal on that symbol is refused GHOST by `HoldingGuard` until a human intervenes, and PnL — the number the owner trades on — stays wrong. This change closes the loop: prepare a booking, let the owner approve it, then append the fill to the ledger.

## Owner decisions (closed, not re-opened)

1. **Booking is never automatic.** The system prepares; the OWNER approves; only then is anything written. The ledger is append-only (`trg_ledger_no_update_delete`) and no compensating-entry mechanism exists, so a wrong attribution is permanent.
2. **The approval surface is the FRONTEND** — a view listing pending bookings with enough detail to judge an attribution, plus approve/reject. Implies admin API endpoints (`ADMIN_API_TOKEN` bearer), React 19 + TS strict, i18n EN/ES, Tailwind 4 (no hex, no `var()` in `className`), Vitest.

## Scope

### In scope
- `execution_attempts.origin` (`SYSTEM` | `VENUE`), NOT NULL, defaulted for existing rows.
- New table `booking_proposals`: a FROZEN, immutable snapshot of a proposed attribution (pool, symbol, strategy, allocation, side, quantity, the fetched fills with their `exchange_fill_id`s, the `Observation` triple it was computed from), with lifecycle `PENDING | APPROVED | REJECTED | SUPERSEDED | EXPIRED`.
- Symbol + time-window fill fetch on BOTH venue clients (currently order-scoped only).
- `PrepareBooking` (fetch fills, match, freeze a proposal) driven by a new recurring/companion job; writes nothing to `ledger_entries`.
- `ApproveBooking` / `RejectBooking` use cases; approval writes one `execution_attempts` row (constructed `FILLED`, `origin='VENUE'`) and N `ledger_entries` via the existing `RecordFill`.
- Admin endpoints under the existing `/reconciliation` router: list pending, approve, reject-with-reason.
- Frontend: first real API client + token handling, the pending-bookings view, approve/reject, EN/ES, Vitest.

### Out of scope
- `AMBIGUOUS_PARTIAL_REDUCE` and `NO_MATCHING_ALLOCATION` — unbookable by construction (no single candidate; no allocation at all). Unchanged.
- Any FIFO/LIFO/pro-rata split rule. Inventing one is the failure this design refuses.
- A compensating-entry / ledger-correction mechanism. Manual DB intervention remains the only repair; manual approval is the mitigation.
- Notifications (Telegram/watchdog) when a proposal appears — one WARNING log line only.
- Pionex, COIN-M, spot. Auto-booking without approval, ever.

## Capabilities

### New
- `venue-close-booking`: preparing, approving and rejecting an attribution of a venue-originated fill to an allocation.

### Modified
- `venue-reconciliation`: a CONFIRMED attributable discrepancy now yields a booking proposal; rejection semantics.
- `trade-execution`: `execution_attempts` gains `origin`; a `VENUE` attempt is constructed already-`FILLED` and was never submitted.
- `trade-ledger`: a ledger entry may originate from a venue-observed fill; `usd_rate` provenance.

## The questions this proposal must answer

**Pending / booked / rejected lives on `booking_proposals`, NOT on `reconciliation_discrepancies`.** The discrepancy row mutates every 30s and `next_consecutive_scans` resets to 1 on any movement; approval needs a frozen snapshot of what is being approved. Its partial unique is on OPEN pool+symbol, so a booked history row could not survive resolution there. A partial unique `ON booking_proposals (discrepancy_id) WHERE state = 'PENDING'` gives at most one live proposal per discrepancy — which also fixes the explore's "re-proposes on every scan" problem without touching slice 1's table.

**`client_order_id` is synthesized DETERMINISTICALLY**, not `uuid4()`: `vnu:{exchange}:{venue_order_id}`, falling back to `vnu:{exchange}:fill:{earliest_exchange_fill_id}` when the venue reports no order id (a liquidation may — must be probed). The column is NOT NULL UNIQUE, so a deterministic value makes a replayed approval collide and be recognised as "already booked" instead of creating an orphan duplicate attempt with zero ledger rows. The `vnu:` prefix cannot collide with system uuid4 ids.

**`origin` IS built now, first.** It is not required for correctness — 0021's `WHERE ... status = 'SUBMITTED'` partial index already permits many VENUE closes per allocation. It is built now because the cost asymmetry decides it: the production ledger has ZERO rows today and `DRY_RUN` is true, so a NOT NULL column costs a trivial migration. Once DRY_RUN goes false, the same column needs a backfill over live trading history. The greppable `vnu:` prefix is provenance; `origin` is a queryable predicate the frontend and any future rule ("never let `CloseOrphans` act on a VENUE-booked residual") need. Downgrade must REFUSE if any VENUE attempt exists, following 0012/0021 precedent, rather than delete trading history.

**The fill fetch** adds one consumer-owned port method implemented by both adapters through the existing registry. Bybit: `GET /v5/execution/list` + `symbol`/`startTime`/`endTime`/`limit`/`cursor`, reusing `_parse_execution` unchanged. Binance: `GET /fapi/v1/userTrades` + `symbol`/`startTime`/`endTime`/`limit`/`fromId`, likewise. **Must be probed live (read-only key, a `scripts/` probe in the `check_bybit_round_trip.py` tradition) BEFORE any interval or window is fixed**: (a) max accepted window span (Bybit's and Binance's documented 7 days are unverified here; Binance's 3-month depth likewise); (b) pagination shape and page size, and whether an empty window errors or returns `[]`; (c) rate-limit weight per call, against `reconciliation.scan` at 30s and `balance.sync` at 60s; (d) whether a LIQUIDATION fill appears on the same endpoint and carries an `orderId` — this decides the `client_order_id` fallback above; (e) padding needed on the window boundary for clock skew. The fetch window is `[first_observed_at − pad, now]`; `pad` waits on the probe.

**Coordination — two layers, and booking does NOT take the pool advisory lock.**
- *Correctness*: the `ledger_entries` `UNIQUE(exchange, venue, exchange_fill_id)` plus the new deterministic `client_order_id` UNIQUE. `ApproveBooking` must treat BOTH IntegrityErrors as EXPECTED outcomes meaning "someone already recorded this fill", mark the proposal `SUPERSEDED`, and succeed with a note — never fail the job. No code handles this today; it is new work.
- *Freshness*: approval re-validates before writing — discrepancy still open and CONFIRMED, its `Observation` triple byte-identical to the frozen one, `open_allocation_ids` unchanged, and no `execution_attempts` row SUBMITTED for that allocation (the `in_flight` predicate `HoldingGuard` already owns). Any mismatch → `SUPERSEDED`, zero writes, a fresh proposal next scan. This is the explore's Q4(b) guard, made concrete.
- *Why not the lock*: `AllocateCapital` and `ClosePosition` take `pg_advisory_xact_lock` to serialize an availability read against a reservation write. Booking writes no reservation and changes no availability — it appends history. Holding that lock across a HUMAN-paced approval would block every signal in the pool for no capital-safety gain, and would create a reconciliation→allocation dependency on a lock primitive across a module boundary that does not exist. Rule 4 governs allocation transactions; booking is not one.
- *`CloseOrphans`*: after approval the strategy nets to zero on that symbol, `classify_orphan` returns proceed, and GHOST stops recurring — a strict improvement. The reverse race (a SYSTEM close placed while a proposal is pending) is caught by the freshness re-check and the two UNIQUEs.

**A REJECTED attribution changes nothing about the discrepancy.** Rejection is a statement about the ATTRIBUTION, not about the disagreement — the venue and the ledger still disagree either way. So reject writes ZERO ledger rows, sets the proposal `REJECTED` with a REQUIRED reason plus actor and time, and leaves the discrepancy row OPEN and CONFIRMED, still listed by `/reconciliation/discrepancies`, still re-observed every scan. It must NOT delete the row, must NOT mark it resolved, and must NOT silently re-propose the identical booking next scan — a nag loop trains the owner to click through. Mechanism: `PrepareBooking` skips a discrepancy holding a REJECTED proposal whose frozen `Observation` equals the current one. If the disagreement MOVES, `next_consecutive_scans` already resets to 1 and the genuinely different situation earns a fresh proposal. If venue and ledger later agree, slice 1's `resolve_absent` resolves the row normally. One WARNING line is logged at rejection, because a rejected-but-real discrepancy means the ledger is knowingly wrong.

## Impact on the non-negotiables

| Rule | Impact |
| --- | --- |
| **DRY_RUN (1)** | `reconciliation.scan` already hard-skips, so no proposals exist. The approve/reject endpoints must ALSO refuse EXPLICITLY under DRY_RUN and log it — a 404-by-empty-table is not a safety property, and the frontend is reachable in DRY_RUN. No venue fill fetch under DRY_RUN. |
| **Idempotency (2)** | Three independent layers: `client_order_id` UNIQUE, `ledger_entries` `UNIQUE(exchange,venue,exchange_fill_id)`, and the `PENDING` partial unique. A replayed approval inserts zero rows and lands `SUPERSEDED`. No webhook, no order, so rule 2's signal key is untouched. |
| **Pool isolation (4, 5)** | Keyed by `(exchange, venue, settlement_currency)` throughout; fills fetched per symbol within one pool; no cross-pool aggregation. Nothing writes `capital_pools` or `reservations`, so availability is unchanged and no advisory lock is taken. |
| **Append-only (6)** | Honoured. Booking only APPENDS. Nothing is updated or deleted; every entry keeps its `strategy_id` and `allocation_id`. |
| **Native-currency PnL (7)** | Honoured for currency. **Deviation, stated plainly**: `usd_rate` is resolved at BOOKING time, not fill time, because the fill already happened and the existing `UsdRateProviderPort` serves no historical rate. Store the venue's `filled_at` alongside the rate's observation time so the gap is always computable and a booking-time rate is never presented as a fill-time rate. See open question Q2. |

## Slicing and an honest line forecast

The last change forecast 3,840–5,380 and took roughly **10,000**, overrunning in `main.py` wiring and integration tests. This forecast is built bottom-up with that correction applied, not around it.

**A frontend slice and a backend slice is NOT enough.** That seam yields two units of roughly 3,000 lines each — about 4x the 800-line budget. Nine units are needed.

| # | Unit | Split point (what it ends at) | Forecast |
| --- | --- | --- | --- |
| 1 | `execution_attempts.origin` | Migration + ORM + downgrade guard. No use case reads it yet. | 300–450 |
| 2 | Venue fill-window fetch | Port + both clients + registry. No DB, no use case. Preceded by the live probe. | 550–750 |
| 3 | `booking_proposals` schema | Migration + ORM + repository + DTOs. No use case. | 750–950 |
| 4 | `PrepareBooking` use case | Use case + unit tests only. No job wiring. | 700–900 |
| 5 | Prepare wiring | Job kind + handler + `main.py` + config + integration tests. | 500–700 |
| 6 | `ApproveBooking` / `RejectBooking` | Both use cases, synthesized id, IntegrityError swallow, freshness re-check. | 800–1,000 |
| 7 | Admin API endpoints | List pending / approve / reject on the existing router. | 450–600 |
| 8 | Frontend API client + auth | First real API call from the SPA: client, token handling, query hooks. **Blocked on Q1.** | 450–600 |
| 9 | Frontend pending-bookings view | View + approve/reject + confirm step + EN/ES + Vitest. | 700–900 |

Bottom-up total **5,200–6,850**. Given the documented overrun, plan for **7,000–9,000** and expect units 4, 6 and 9 to split again at `sdd-tasks`. Units 1–2 are independent of 3–7; 8–9 depend only on 7's contract.

**Unit 8 is larger than it looks.** The frontend is a bare shell: `App.tsx`, `main.tsx`, i18n, `cn.ts` — nine files, zero API calls ever made, no router library installed, navigation is hardcoded `href="#..."` anchors with `active` a constant. `QueryClientProvider` IS wired in `main.tsx`. So unit 8 builds the first API client and the first authenticated request this app has ever made, and unit 9 must add real navigation to a view or render conditionally off the existing anchors.

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| A wrong attribution permanently corrupts two strategies' PnL | Med | Manual approval (decision 1); freshness re-check; CONFIRMED-only; the frozen snapshot shown in full before approval |
| Venue fill-endpoint window/pagination/rate-limit unverified | High | Live probe REQUIRED before any interval is fixed; no interval chosen here |
| `main.py` wiring overruns again | High | Unit 5 exists solely to hold wiring + integration tests, so an overrun lands inside one unit |
| Admin token in the browser | Med | Q1 — token entered once, held client-side; never baked into the built bundle |
| Approval fatigue turns into click-through | Med | Rejection suppresses the identical proposal; expiry (Q5) bounds a stale queue |
| Frontend shell work inflates the "add a view" estimate | High | Split into units 8 and 9 at the API-client boundary |

## Rollback

- **Units 8–9**: revert; the view disappears. Nothing server-side depends on it.
- **Unit 7**: drop the router includes; endpoints 404.
- **Units 4–6**: stop seeding the prepare job; proposals stop being created. Approve/reject become unreachable once unit 7 is out.
- **Unit 3**: downgrade drops `booking_proposals`. It holds no money data — only proposals.
- **Units 1–2**: `origin`'s downgrade REFUSES while any VENUE attempt exists (0012/0021 precedent). The fill-fetch methods are additive and unused once callers are gone.
- **Stated plainly: ledger rows written by an approved booking CANNOT be rolled back.** `trg_ledger_no_update_delete` forbids it and no compensating entry exists. Rollback restores the CAPABILITY, never the DATA. That asymmetry is exactly why approval is manual.

## Success criteria

- [ ] A position closed by hand on the venue yields a PENDING proposal within two scan intervals, showing pool, symbol, strategy, allocation, side, quantity, price, fee and the venue fill ids.
- [ ] Approving writes exactly one `execution_attempts` row (`origin='VENUE'`, `status='FILLED'`) and exactly N `ledger_entries`; the strategy's `net_base` on that symbol becomes zero.
- [ ] The next signal on that symbol passes `HoldingGuard` instead of being refused GHOST.
- [ ] Approving the same proposal twice writes nothing the second time and returns `SUPERSEDED`, not an error.
- [ ] Rejecting leaves the discrepancy OPEN and CONFIRMED, writes zero ledger rows, and no identical proposal reappears while the observation is unchanged.
- [ ] `DRY_RUN=true` produces zero proposals AND explicitly refuses approve/reject with a log line.
- [ ] `ledger_entries` is byte-identical before and after a PREPARE. Only APPROVE writes.
- [ ] Frontend renders in EN and ES with no hardcoded display text; Vitest covers pending list, empty state, approve, reject-with-reason and an error path.

## Proposal question round — OPEN QUESTIONS for the owner

Execution mode is `auto`, so these are raised here rather than asked interactively. Each carries an evidence-based recommendation; none is decided silently.

**Q1 — How does the browser authenticate? BLOCKS UNIT 8.** `ADMIN_API_TOKEN` is a bearer token and the frontend has never called the API (grep finds it in zero frontend files). *Recommendation*: the owner pastes the token once into a field; hold it in Zustand + `localStorage`; send `Authorization: Bearer`. NOT `import.meta.env` — that bakes the trade-authorizing admin token into a built bundle served off the VPS. A real login is a separate change.

**Q2 — `usd_rate` provenance (rule 7 tension).** The rate cannot be read at fill time because the fill already happened. *Recommendation*: record the booking-time rate AND the venue's `filled_at` plus the rate's observation time, so the gap is always visible and never presented as a fill-time rate.

**Q3 — Does approval need a second confirmation in the UI?** *Recommendation*: yes — one confirm step showing the exact rows about to be written. Cheap, and the write is permanent.

**Q4 — Both attributable kinds, or start with `ATTRIBUTABLE_FULL_CLOSE` only?** *Recommendation*: both. `classify()`'s ladder makes them equally unambiguous — a flat venue and a single disagreeing allocation each leave exactly one candidate — and restricting to one halves the value while saving almost no code.

**Q5 — Should a PENDING proposal expire?** *Recommendation*: yes, `EXPIRED` after a configurable window (default 24h). A frozen fill set weeks old misleads more than it helps, and expiry is re-proposable on the next scan.

**Q6 — Notify when a proposal appears?** The project already has Telegram alerting and a watchdog. *Recommendation*: out of scope here, one WARNING log line only. The frontend is the surface the owner chose; adding a second delivery channel before the first is proven doubles the surface.
