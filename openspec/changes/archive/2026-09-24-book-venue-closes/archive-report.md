# Archive Report: book-venue-closes

**Change**: book-venue-closes (reconciliation slice 2)
**Status**: Complete
**Archived**: 2026-09-24
**Artifact store**: openspec

## What Shipped

The change spans three sequential pull requests, merged to main across 2026-09-09 through 2026-09-24:

| PR | Units | Commit | Migrations | Deployed | Details |
|---|---|---|---|---|---|
| #4 | 1–5 | 1eda089 | 0022, 0023 | 2026-09-09 | Foundation: `execution_attempts.origin`, venue fill fetch, `booking_proposals` schema, proposal domain, prepare wiring |
| #5 | 6a, 6b, 7 | 554f414 | — | 2026-09-18 | Backend complete: approve/reject use cases, expiry job, admin endpoints (bearer-gated, DRY_RUN-safe) |
| #6 | 8, 9a, 9b | 8722b2a | — | — | Frontend: auth token store, bookings list view, confirm/reject dialogs. Built but NOT served in any deployment yet. |

## Test Coverage

| Suite | Count | Status |
|---|---|---|
| Backend (pytest) | 1,513 | All passing |
| Frontend (Vitest) | 59 | All passing |
| Integration (real Postgres) | Included in backend count | All passing |

## Specifications Merged Into Main Specs

### New Domain: venue-close-booking
- **Created**: `openspec/specs/venue-close-booking/spec.md`
- **Requirements added**: 8 (proposal freezing, approval/rejection, expiry, DRY_RUN, bearer token, position guard clearing)
- **Final-state facts added during apply** (2026-09-23/24):
  - Single allocation constraint (`ck_booking_proposals_single_allocation`)
  - Matched fill requires `exchange_order_id` NOT NULL
  - Comprehensive refusal logging (one WARNING per condition, no row write)
  - Endpoint status codes: 2xx (success), 409 (already decided/superseded/expired), 503 (DRY_RUN), 404 (unknown)
  - Fill-window bounds: max 7 days both venues; Binance pagination startTime inclusive + de-dup; Bybit Funding excluded; unknown execType raises

### Existing Domain: trade-execution
- **Added requirements**: 2 (execution attempt origin, venue-origin constructed filled)
- **Final-state fact added**: `client_order_id` synthesis pattern `vnu:{exchange}:fill:{earliest_exchange_fill_id}` (not venue order id)

### Existing Domain: trade-ledger
- **Added requirements**: 1 (usd_rate provenance for booked fills — resolved at approval time, not fill time)

### Existing Domain: venue-reconciliation
- **Added requirements**: 2 (confirmed attributable yields booking proposal; rejection suppresses identical re-proposal)

## Review Corrections Applied During Apply

Per design.md sections 4, 5, 9 ("Added/Superseded/Corrected during apply") and tasks.md "Probe results":

1. **venue-close-booking constraint enforcement**: Single allocation per proposal is enforced at schema level with `ck_booking_proposals_single_allocation`, blocking multi-allocation full closes with WARNING.

2. **Matched fill ledger integrity**: `exchange_order_id` is NOT NULL in every ledger row matched into a booking. Fills without it are refused at prepare with WARNING, never written.

3. **Refusal logging discipline**: Every booking refusal (sum mismatch, mixed sides, window exceed, symbol mismatch, fetch failure, missing order id) logs exactly one WARNING and writes no row.

4. **Endpoint status codes**: Approve/reject return 2xx only for success. ALREADY_DECIDED/SUPERSEDED/EXPIRED return 409 Conflict with state committed. DRY_RUN returns 503. Unknown ID returns 404 Not Found.

5. **Fill-window probed bounds**: Maximum 7-day lookback confirmed on both venues (8d refused). Binance pagination validated to advance startTime inclusively with de-dup. Bybit Funding executions excluded. Unknown execType raises error.

6. **client_order_id synthesis**: VENUE-origin attempts use `vnu:{exchange}:fill:{earliest_exchange_fill_id}` to preserve uniqueness across multiple fills in one approval and avoid collision with venue order IDs.

## Known Open Items

1. **Frontend serving/design undecided** — Units 9a/9b (BookingsListView, dialogs) are built and tested but not served in any deployment. The owner has design ideas; surface them first before deployment decision.

2. **First real approval not rehearsable under DRY_RUN** — All tests mock the venue or use DRY_RUN. A real approval requires DRY_RUN=false and actual discrepancy + venue agreement. Owner decision: coordinate this together on a small test discrepancy.

3. **DRY_RUN=false blocked on per-symbol venue minimums debt** — The system can calculate available capital but cannot guarantee minimum order sizes per symbol per venue. This is a separate capability; booking does not unblock it, but live trading requires it.

4. **Binance "oldest first" page ordering unobserved** — When a window holds more trades than one page, the reader assumes Binance returns the OLDEST first, advancing `startTime` to the last trade's time (inclusive) and de-duplicating. This could not be observed live, because there were no fills in the probe's 7-day window. If the assumption is wrong, trades in the middle go missing, the sum no longer equals the delta, and `match_fills` refuses with a WARNING. It fails safe, and cannot produce a wrong booking. MockTransport tests cover the implemented rule.

5. **Liquidation fills unobserved** — No liquidation fills appeared in history on either venue during probing. If they occur, unknown execType or missing order_id would raise/refuse per the spec. Document the handling when observed.

6. **Multi-allocation full closes need manual reconciliation** — ATTRIBUTABLE_FULL_CLOSE over multiple allocations is refused. If the venue closed multiple allocations in one transaction, they must be booked individually (one per proposal) or resolved by manual ledger adjustment.

## Artifacts Retained in Archive

```
openspec/changes/archive/2026-09-24-book-venue-closes/
├── proposal.md                 — Original proposal from sdd-propose
├── specs/
│   ├── trade-execution/spec.md — Delta spec (merged into main)
│   ├── trade-ledger/spec.md    — Delta spec (merged into main)
│   ├── venue-close-booking/spec.md — Delta spec (copied as new main spec)
│   └── venue-reconciliation/spec.md — Delta spec (merged into main)
├── design.md                   — Design document with all decisions
├── exploration.md              — Exploration notes
├── owner-decisions.md          — Binding owner decisions (6 open questions resolved)
├── tasks.md                    — Task list, all 57 tasks marked complete
└── (No verify-report.md)       — Verification was not run as separate phase; checks inline during apply

All files are preserved byte-identical for the audit trail, with one exception: the heading of each of the four delta specs was normalised from `## Delta: <domain> — ADDED` to `## ADDED Requirements`, the form the spec-merge tool recognises. No requirement text changed.

After the merge, the orchestrator corrected the merged main specs where the delta text disagreed with the shipped code: the replay outcome is ALREADY_DECIDED, not SUPERSEDED; the order ID comes from the venue; approval refusals do commit their state change; an over-long window is refused rather than bounded; Binance pagination advances to the last trade's time; and the reason for the fill-keyed `client_order_id`.
```

## SDD Cycle Closure

| Phase | Status | Evidence |
|---|---|---|
| propose | Complete | proposal.md in archive |
| spec | Complete | 4 delta specs in archive, merged into main specs |
| design | Complete | design.md in archive; all decisions binding per owner |
| tasks | Complete | tasks.md in archive, 57/57 tasks marked complete |
| apply | Complete | 3 PRs merged, 1,513 backend tests + 59 frontend tests passing |
| verify | Not run | Verification deferred; functional checks run inline during apply |
| archive | Complete | Change folder moved to archive; specs merged; report written |

## Key Implementation Facts (For Future Reference)

- **Proposal frozen at prepare time**: The `booking_proposals` table carries an immutable snapshot of pool, symbol, strategy_id, allocation_id, side, quantity, fetched fills, and Observation triple. This prevents TOCTOU races between prepare and approve.

- **Venue-origin attempts are created filled**: A VENUE-origin `ExecutionAttempt` is constructed directly in status FILLED (never SUBMITTED), because the fill already occurred. The client_order_id uses the earliest fill ID in the set, ensuring deterministic replay-safety.

- **Single ledger write per approval**: Approval writes exactly one `ExecutionAttempt` row and N `LedgerEntry` rows (one per matched fill). Replays on the same proposal hit the unique constraint collision on either the client_order_id or exchange_fill_id and mark the proposal SUPERSEDED, never fail.

- **DRY_RUN hard-skip at use-case level**: Under DRY_RUN, prepare creates no proposals and approve/reject explicitly refuse with 503. This prevents false positives: fills in DRY_RUN come from FakeExchangeAdapter, and comparing them against the real venue would manufacture disagreements.

- **Pool advisory locks not held across approve**: Unlike allocation (which locks the pool during availability read + reservation write), booking approval does not hold an advisory lock. The freshness check re-validates the discrepancy at approve time, detecting moved observations instead.
