# Venue-Close-Booking Specification

## Purpose

Prepares, approves, and rejects booking proposals for venue-originated fills that disagree with the ledger, backing a multi-step workflow where fills detected by the reconciliation scan are reviewed and manually attributed to ledger allocations before being recorded.

## Requirements

### Requirement: Proposal Prepared From a Frozen Snapshot, At Most One Pending
PrepareBooking MUST create a proposal only from a CONFIRMED attributable
discrepancy, freezing an IMMUTABLE snapshot: pool
`(exchange, venue, settlement_currency)`, symbol, strategy_id, allocation_id,
side, quantity, the fetched venue fills (`exchange_fill_id` each), and the
Observation triple. Prepare MUST write nothing to `ledger_entries` or
`execution_attempts`. At most one PENDING proposal MAY exist per discrepancy.

- GIVEN a confirmed discrepancy, WHEN prepared, THEN the proposal's frozen fields match what was observed and no ledger/execution row changed.
- GIVEN a proposal already PENDING for a discrepancy, WHEN prepare runs again, THEN no second PENDING proposal is created.

### Requirement: Approval Is Manual and Freshness-Checked
Nothing reaches `ledger_entries`/`execution_attempts` for a venue-originated
fill without an explicit owner approval (actor, time recorded). Approval MUST
refuse, writing nothing and marking the proposal SUPERSEDED, when the
discrepancy is no longer OPEN+CONFIRMED, its current Observation differs from
the frozen one, or an execution attempt is SUBMITTED for the allocation.

- GIVEN a PENDING proposal untouched since freezing, WHEN approved, THEN it proceeds to write.
- GIVEN the discrepancy moved since freezing, WHEN approval is attempted, THEN it is refused, nothing is written, and the proposal becomes SUPERSEDED.

### Requirement: Approval Appends Exactly Once, Replay-Safe
Approving a PENDING proposal MUST append exactly one `execution_attempts` row
(`origin='VENUE'`, `status='FILLED'`, a deterministically synthesized
`client_order_id`) and its fills via the existing `RecordFill`, honoring
`UNIQUE(exchange, venue, exchange_fill_id)`. Replaying the same approval MUST
insert nothing further: a `client_order_id` or `exchange_fill_id` collision
MUST be treated as an expected outcome — mark the proposal SUPERSEDED, never
fail the job.

- GIVEN a first approval, WHEN it runs, THEN one attempt row and N ledger rows are written and the symbol's strategy net returns to zero.
- GIVEN the same approval replayed, WHEN it runs again, THEN zero rows are written and the result is ALREADY_DECIDED, not an error (the first approval already moved the proposal out of PENDING).
- GIVEN an approval whose write collides on `client_order_id` or `exchange_fill_id`, WHEN it runs, THEN zero rows are written and the proposal becomes SUPERSEDED, not an error.

### Requirement: Rejection Writes Nothing and Requires a Reason
Rejecting a PENDING proposal MUST require a reason, MUST write zero ledger
rows, MUST set the proposal REJECTED with actor/time, and MUST leave the
discrepancy OPEN and CONFIRMED — rejection is a statement about the
attribution, not about the disagreement.

- GIVEN a reason, WHEN rejected, THEN the ledger is untouched and the discrepancy stays OPEN/CONFIRMED.
- GIVEN no reason supplied, WHEN reject is attempted, THEN it is refused.

### Requirement: Proposal Expiry
A PENDING proposal MUST expire to EXPIRED after a configurable window
(default 24h) and remains re-proposable on a later scan.

- GIVEN a proposal older than the configured window, WHEN checked, THEN it is EXPIRED and not approvable, and a fresh proposal may be prepared next scan.

### Requirement: DRY_RUN Refuses Booking Entirely
Under `DRY_RUN`, prepare MUST create zero proposals, and approve/reject MUST
explicitly refuse with a logged reason — never a silent 404 on an empty table.

- GIVEN `DRY_RUN=true`, WHEN prepare, approve or reject is invoked, THEN each explicitly refuses and logs why.

### Requirement: Admin Endpoints Require the Bearer Token, Never Bundled
List-pending, approve and reject MUST require the existing `ADMIN_API_TOKEN`
bearer, mounted at router level. The token MUST be entered once by the
operator and held client-side; it MUST NEVER be embedded via
`import.meta.env` or any other mechanism into the built frontend bundle.

- GIVEN no bearer token, WHEN any booking endpoint is called, THEN the request is refused before handler logic.
- GIVEN the built frontend bundle, WHEN inspected, THEN it contains no token string.

### Requirement: Approved Booking Clears the Existing-Position Guard
Once approved, the strategy's ledger net on the booked symbol MUST return to
exactly zero, so a later signal on that symbol is evaluated by the
Existing-Position Guard (capital-allocation) as holding nothing and MUST NOT
be classified GHOST for that close.

- GIVEN an approved booking zeroing a strategy's net on a symbol, WHEN the next signal for that symbol arrives, THEN the guard proceeds instead of refusing GHOST.

### Requirement: Single Allocation Per Booking Proposal (added during apply, 2026-09-23/24)
A booking proposal MUST be prepared ONLY when a discrepancy has exactly ONE open allocation. An `ATTRIBUTABLE_FULL_CLOSE` verdict applying to multiple allocations MUST be refused with a logged WARNING and written as no row. The database constraint `ck_booking_proposals_single_allocation` enforces this at write time.

- GIVEN a CONFIRMED discrepancy with exactly one open allocation, WHEN prepared, THEN a proposal is created.
- GIVEN a CONFIRMED discrepancy with multiple allocations both matching the full close, WHEN prepare runs, THEN no proposal is created and a WARNING is logged.

### Requirement: Matched Fill Requires Exchange Order ID (added during apply, 2026-09-23/24)
Every matched fill in a booking proposal MUST carry the venue's order ID (`exchange_order_id`), because `ledger_entries.exchange_order_id` is NOT NULL and approval could not record the fill otherwise. A discrepancy whose matched fills include one without a venue order ID (a liquidation may carry none) is refused at prepare time: no proposal row is written and a WARNING is logged. Approval refuses such a fill too, as a second guard.

- GIVEN a venue fill matched against the ledger without an exchange_order_id, WHEN prepare runs, THEN no proposal is created and a WARNING is logged.

### Requirement: Refusal Logging (added during apply, 2026-09-23/24)
Every condition that prevents a proposal from being PREPARED MUST log exactly one WARNING naming the discrepancy and the reason, and MUST write no proposal row. The conditions are: a sum that does not equal the delta, mixed sides, zero unrecorded fills, a fill window over the maximum span, a fill whose market differs from the discrepancy's market key, a failed venue fetch, more than one open allocation, and a fill without a venue order ID. Every approval or rejection that does not succeed (ALREADY_DECIDED, SUPERSEDED, EXPIRED, DRY_RUN) MUST also log a WARNING naming the proposal. Of those outcomes, SUPERSEDED and EXPIRED commit the proposal's state change, and none of them writes to `ledger_entries` or `execution_attempts`.

- GIVEN any prepare refusal condition, WHEN prepare runs, THEN a single WARNING is logged and no proposal row is written.
- GIVEN an approval refused as SUPERSEDED, WHEN it runs, THEN a WARNING is logged, the proposal is marked SUPERSEDED, and no ledger or execution row is written.

### Requirement: Endpoint Status Codes (added during apply, 2026-09-23/24)
Approve and reject endpoints MUST return 2xx only when the proposal moves to APPROVED or REJECTED respectively. ALREADY_DECIDED, SUPERSEDED, and EXPIRED states MUST return 409 Conflict with the state change committed. DRY_RUN mode MUST return 503 Service Unavailable. Unknown proposal ID MUST return 404 Not Found.

- GIVEN an approval request on a PENDING proposal with valid freshness, WHEN approve succeeds, THEN the response is 2xx.
- GIVEN an approval request on a proposal no longer PENDING, WHEN approve runs, THEN the response is 409 and the state change is committed.
- GIVEN any booking request under DRY_RUN, WHEN the endpoint is called, THEN the response is 503.
- GIVEN a proposal ID that does not exist, WHEN approve or reject is called, THEN the response is 404.

### Requirement: Fill-Window Bounds and Pagination (added during apply, 2026-09-23/24)
The fill window is `[first_observed_at − pad, now]` and MUST NOT exceed the venues' maximum span of 7 days, probed live on both venues. A longer window MUST be refused with a WARNING, never truncated. Pagination on Binance MUST advance `startTime` to the last trade's time, inclusive, and deduplicate by `exchange_fill_id`. A full page that yields no new IDs MUST raise, and so MUST reaching the page bound, never truncate. Bybit funding executions MUST be excluded. Unknown `execType` values MUST raise an error.

- GIVEN a discrepancy whose fill window would exceed 7 days, WHEN prepare runs, THEN it is refused with a WARNING and no window is fetched.
- GIVEN Binance pagination, WHEN advancing to the next page, THEN `startTime` is set to the last trade's time (inclusive) and duplicates are discarded.
- GIVEN a full Binance page whose trades all share one millisecond and add no new IDs, WHEN paginating, THEN an error is raised rather than dropping trades.
- GIVEN Bybit fills including funding executions, WHEN parsed, THEN funding rows are excluded.
- GIVEN an unknown `execType` value from any venue, WHEN the response is parsed, THEN an error is raised.
