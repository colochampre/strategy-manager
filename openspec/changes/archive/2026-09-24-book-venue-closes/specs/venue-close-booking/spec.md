<!-- Materialized verbatim from Engram topic sdd/book-venue-closes/spec (observation #233) on 2026-09-23. Engram stays the mirror; edit here first. -->

# Spec: book-venue-closes (reconciliation slice 2)

Owner decisions (#232) vs proposal (#231): **no conflicts found** — the owner
confirmed all six open-question recommendations (Q1–Q6) and both shaping
decisions verbatim. This spec treats them as binding requirements, not
recommendations.


## ADDED Requirements

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
- GIVEN the same approval replayed, WHEN it runs again, THEN zero rows are written and the result is SUPERSEDED, not an error.

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

## Explicitly NOT specified here (belongs to design)

- Prepare job trigger point/wiring (inline in `ScanPools` vs. a separate sweep) and its schedule.
- Live-probed fill-fetch window, pagination, and rate-limit budget per venue — blocks the fetch unit; must precede any fixed interval.
- Exact `client_order_id` synthesis string (proposal suggests `vnu:{exchange}:{venue_order_id}`, not binding here).
- `booking_proposals`/`origin` migration DDL and indexes beyond the stated uniqueness constraints.
- Whether booking takes the pool advisory lock (proposal argues no; not required here).
- Frontend confirm-step copy, Zustand store shape, React Query hook design.
- Notification behavior: one WARNING log line only, no Telegram (owner-decided, not elaborated further here).
