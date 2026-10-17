# Venue-Close-Booking Specification (delta of change `operator-panel`, PR 15)

> **Added 2026-10-16 (owner decision 66; design addendum "PR 15 — Confirmed discrepancies", sections C, D, E, F and K; the owner's answers Q1, Q2, Q3 and Q9 of 2026-10-16).**
>
> This delta REVERSES one rule of the archived change `book-venue-closes`: its proposal's item 1, "Booking is never automatic", and its out-of-scope line "Auto-booking without approval, ever". The reason that change gave, that the ledger is append-only and has no compensating entry, still holds, so the reversal is bounded: only `ATTRIBUTABLE_FULL_CLOSE` and `ATTRIBUTABLE_SINGLE_ALLOCATION` whose venue fills sum exactly to the observed difference, that reduce the position, that belong to no order this system placed, and that name exactly one open allocation, are booked without a human. Everything else needs the owner (see the delta of `venue-reconciliation`).
>
> Sections follow the order RENAMED, MODIFIED, REMOVED, ADDED. A requirement of the main spec that is not named here is unchanged.

## RENAMED Requirements

- FROM: `### Requirement: Approval Is Manual and Freshness-Checked`
- TO: `### Requirement: Approval Is Automatic and Freshness-Checked`

## MODIFIED Requirements

### Requirement: Approval Is Automatic and Freshness-Checked

A PENDING proposal MUST be approved by the worker, with the fixed actor `system:auto-booking`, through the same `ApproveBooking.approve` use case that the approve route ran before this change, one transaction per proposal. Nothing reaches `ledger_entries` or `execution_attempts` for a venue-originated fill except through that use case. Approval MUST refuse, writing nothing and marking the proposal SUPERSEDED, when the discrepancy is no longer OPEN+CONFIRMED, its current Observation differs from the frozen one, or an execution attempt is SUBMITTED for the allocation. Approval MUST refuse with EXPIRED when the proposal is older than its window. The actor and the time of the approval MUST be recorded.

(Previously: "Approval Is Manual and Freshness-Checked": nothing reached the ledger "without an explicit owner approval". Every guard of the approval, its freshness checks, the writer's SAVEPOINT and its replay safety are unchanged; only who calls it changes.)

#### Scenario: A PENDING proposal untouched since freezing is approved by the system

- GIVEN a PENDING proposal untouched since freezing and `DRY_RUN=false`
- WHEN the worker's automatic step runs
- THEN the proposal becomes APPROVED with `decided_by` equal to `system:auto-booking` and `decided_at` set, one VENUE attempt and its ledger rows are written, and the strategy's net on the symbol is zero

#### Scenario: A discrepancy that moved since freezing is refused and superseded

- GIVEN a PENDING proposal whose discrepancy's current Observation differs from the frozen one
- WHEN the automatic step reaches it
- THEN nothing is written to the ledger, the proposal becomes SUPERSEDED, and one WARNING names the proposal

#### Scenario: An expired proposal is not booked

- GIVEN a PENDING proposal older than its expiry window
- WHEN the automatic step reaches it
- THEN the outcome is EXPIRED, nothing is written to the ledger, and one WARNING names the proposal

#### Scenario: The automatic step uses the route's USD rate provider

- GIVEN the worker builds `ApproveBooking` for the automatic step
- WHEN a booking is written
- THEN its `usd_rate_at_fill` equals the one the approve route's provider (`FixedUsdRateProvider({USDT: 1})`) would have stored, so it does not depend on which process wrote it

### Requirement: DRY_RUN Refuses Booking Entirely

Under `DRY_RUN`, the `reconciliation.prepare_booking` handler MUST skip the expiry, the sweep, the automatic step and the announcement, and MUST still enqueue its successor. `PrepareBooking` MUST create zero proposals, and `ApproveBooking` MUST explicitly refuse with `DRY_RUN_REFUSED` and a logged WARNING, never a silent no-op. The automatic step MUST add no `DRY_RUN` check of its own: the handler never reaches it under `DRY_RUN`, and the use case refuses if it ever does.

(Previously: "approve/reject MUST explicitly refuse with a logged reason", and the endpoints answered 503. The routes no longer exist.)

#### Scenario: The handler does nothing but enqueue its successor

- GIVEN `DRY_RUN=true`
- WHEN the prepare-booking job runs
- THEN none of expiry, sweep, automatic step and announcement is called, and the successor job is enqueued

#### Scenario: Prepare refuses under DRY_RUN

- GIVEN `DRY_RUN=true` and a CONFIRMED attributable discrepancy
- WHEN `PrepareBooking.sweep` is called directly
- THEN no proposal row is written and a refusal is logged

#### Scenario: Approve refuses under DRY_RUN

- GIVEN `DRY_RUN=true` and a PENDING proposal
- WHEN `ApproveBooking.approve` is called directly
- THEN the outcome is `DRY_RUN_REFUSED`, one WARNING is logged, and no ledger or execution row is written

### Requirement: Admin Endpoints Require the Bearer Token, Never Bundled

The booking-related read route that remains, `GET /reconciliation/confirmed`, MUST require the existing `ADMIN_API_TOKEN` bearer, mounted at router level. The token MUST be entered once by the operator and held client-side; it MUST NEVER be embedded via `import.meta.env` or any other mechanism into the built frontend bundle.

(Previously: "List-pending, approve and reject MUST require the existing bearer". Those three routes are removed (admin-api, "The Booking Routes Are Removed").)

#### Scenario: No bearer is refused before the handler

- GIVEN no bearer token
- WHEN `GET /api/reconciliation/confirmed` is called
- THEN the request is refused before handler logic

#### Scenario: The bundle holds no token

- GIVEN the built frontend bundle
- WHEN it is inspected
- THEN it contains no token string

### Requirement: Single Allocation Per Booking Proposal (added during apply, 2026-09-23/24)

A booking proposal MUST be prepared ONLY when a discrepancy has exactly ONE open allocation. An `ATTRIBUTABLE_FULL_CLOSE` verdict applying to multiple allocations MUST be refused with a logged WARNING and written as no row. The database constraint `ck_booking_proposals_single_allocation` enforces this at write time. Such a discrepancy is therefore booked neither automatically nor by hand: it MUST be sorted as needing the owner with the reason `SEVERAL_ALLOCATIONS` (owner decision 66, Q9) and MUST be announced.

(Revised 2026-10-16. This corrects what the owner was told before the design, that a full liquidation would be booked automatically whatever the number of allocations: that is true of the verdict, not of the booking. A split by a rule such as pro-rata or FIFO would be an invented attribution written permanently, the rule `book-venue-closes` ruled out.)

#### Scenario: One open allocation yields a proposal

- GIVEN a CONFIRMED discrepancy with exactly one open allocation
- WHEN prepared
- THEN a proposal is created

#### Scenario: Several allocations yield no proposal, a WARNING and a reason

- GIVEN a CONFIRMED `ATTRIBUTABLE_FULL_CLOSE` discrepancy over two open allocations
- WHEN prepare runs
- THEN no proposal is created, one WARNING is logged, and the refusal's code `SEVERAL_ALLOCATIONS` is in the sweep's result for that discrepancy

#### Scenario: The sorting rule says it needs the owner at once

- GIVEN the same discrepancy, confirmed one minute ago
- WHEN the discrepancy is sorted by the rule of attention
- THEN it needs the owner with the reason `SEVERAL_ALLOCATIONS`, with no grace

### Requirement: Refusal Logging (added during apply, 2026-09-23/24)

Every condition that prevents a proposal from being PREPARED MUST log exactly one WARNING naming the discrepancy and the reason, and MUST write no proposal row. The conditions are: a sum that does not equal the delta, mixed sides, zero unrecorded fills, a non-positive quantity, a fill window over the maximum span, a fill whose market differs from the discrepancy's market key, a failed venue fetch, more than one open allocation, a fill without a venue order ID, a difference that grows or flips the position, a matched fill that belongs to an order this system placed, and a historical rejection of the identical observation. Every approval that does not succeed (ALREADY_DECIDED, SUPERSEDED, EXPIRED, DRY_RUN_REFUSED) MUST also log a WARNING naming the proposal. Of those outcomes, SUPERSEDED and EXPIRED commit the proposal's state change, and none of them writes to `ledger_entries` or `execution_attempts`. An approval that succeeds MUST log an INFO line, and the handler MUST log one INFO summary of the run's outcomes when anything moved, otherwise DEBUG.

(Previously: the list ended at "a fill without a venue order ID" and spoke of "approval or rejection". The two new conditions are Q2's; the rejection is historical only.)

#### Scenario: Any prepare refusal logs one WARNING and writes no row

- GIVEN any prepare refusal condition above
- WHEN prepare runs
- THEN a single WARNING is logged and no proposal row is written

#### Scenario: A refusal approval writes nothing and logs

- GIVEN an approval refused as SUPERSEDED
- WHEN it runs
- THEN a WARNING is logged, the proposal is marked SUPERSEDED, and no ledger or execution row is written

#### Scenario: The run's summary is INFO only when something moved

- GIVEN one run that approved a proposal and one that found nothing pending
- WHEN the handler logs
- THEN the first logs one INFO summary naming the counts and the second logs at DEBUG

## REMOVED Requirements

### Requirement: Rejection Writes Nothing and Requires a Reason

**Reason (owner decision 66, Q1):** the reject route and `RejectBooking` are removed. A proposal is `PENDING` for the seconds between the sweep's commit and its automatic approval, so a human has nothing left to reject. Only an attributable discrepancy with one allocation could ever be approved by hand, and that is exactly the kind that is now automatic: no manual path is lost. A historical `REJECTED` row stays readable and keeps suppressing its identical observation (venue-reconciliation, "Rejection Suppresses Identical Re-Proposal").

**Migration:** none. No column or row is changed.

### Requirement: Endpoint Status Codes (added during apply, 2026-09-23/24)

**Reason (owner decision 66, Q1):** the approve and reject routes no longer exist, so there is no 2xx, 409, 503 or 404 of theirs to specify. The outcomes of an approval remain specified by their log lines and states ("Approval Is Automatic and Freshness-Checked", "Refusal Logging").

**Migration:** none.

## ADDED Requirements

### Requirement: Prepared Proposals Are Approved By The Worker In The Same Job, After The Sweep Has Committed

The `reconciliation.prepare_booking` handler MUST run, in this order and only when `DRY_RUN` is false: expire, sweep, the automatic step, the announcement, then enqueue its successor. The automatic step MUST list every PENDING proposal (not only those this job prepared) and call `approve` once per proposal in list order, with `decided_by` equal to `system:auto-booking`, defined once beside the route's former admin actor. The sweep MUST commit before any approval begins, and `PrepareBooking.sweep` MUST NOT approve: prepare writes nothing to `ledger_entries` or `execution_attempts`.

#### Scenario: The order of the steps

- GIVEN `DRY_RUN=false` and fakes recording their calls
- WHEN the handler runs
- THEN the calls are expire, sweep, automatic step, announcement, enqueue, in that order

#### Scenario: Prepare alone still writes no ledger row

- GIVEN a CONFIRMED attributable discrepancy
- WHEN `PrepareBooking.sweep` runs and the automatic step does not
- THEN a PENDING proposal exists and no `ledger_entries` or `execution_attempts` row was written

#### Scenario: A crash between the sweep and the approvals loses nothing

- GIVEN a PENDING proposal left by a run that crashed after the sweep's commit
- WHEN the next run's automatic step starts
- THEN the proposal is approved if it is still fresh, otherwise it becomes SUPERSEDED or EXPIRED and is prepared again

#### Scenario: The same job twice writes the ledger once

- GIVEN a booked discrepancy and the job run a second time
- WHEN the second run completes
- THEN zero additional ledger rows and zero additional execution attempts are written

### Requirement: An Automatic Booking Is An APPROVED Proposal Whose Decider Names The System, With No Migration

An automatic booking MUST be a proposal with `state='APPROVED'` and `decided_by='system:auto-booking'`. The unit MUST add no column, no table and no migration, and the migration head MUST be unchanged. The refusal reason of a discrepancy that could not be booked MUST NOT be stored.

#### Scenario: The decider is the system

- GIVEN a booking made by the automatic step
- WHEN the proposal row is read
- THEN `state` is `APPROVED` and `decided_by` is `system:auto-booking`

#### Scenario: The migration head is unchanged

- GIVEN the change is applied
- WHEN `alembic heads` is read
- THEN it names the same revision as before the change

### Requirement: Automatic Booking Refuses A Difference That Grows Or Flips The Position

`PrepareBooking` MUST refuse, with one WARNING and no row, a discrepancy whose venue net does not lie between zero and the ledger net, inclusive of zero: the venue net MUST have the same sign as the ledger net or be flat, and be smaller in size. A close made outside the system only shrinks a position; an increase or a flip is a fill this system cannot explain. `ATTRIBUTABLE_FULL_CLOSE` MUST always pass this test. The refusal's code is `GROWS_OR_FLIPS`. The cost, said to the owner, is that adding to a position by hand is never booked automatically (owner decision 66, Q2).

#### Scenario: An increase is refused

- GIVEN a ledger net of 0.5 and a venue net of 0.8 with unrecorded fills summing exactly to +0.3
- WHEN prepare runs
- THEN no proposal is created, one WARNING is logged, and the code `GROWS_OR_FLIPS` is returned for the discrepancy

#### Scenario: A flip is refused

- GIVEN a ledger net of 0.5 and a venue net of -0.2 with unrecorded fills summing exactly to -0.7
- WHEN prepare runs
- THEN no proposal is created and the code is `GROWS_OR_FLIPS`

#### Scenario: A reduction still prepares

- GIVEN a ledger net of 0.5 and a venue net of 0.2 with unrecorded fills summing exactly to -0.3
- WHEN prepare runs
- THEN a proposal is created

#### Scenario: A full close always passes

- GIVEN an `ATTRIBUTABLE_FULL_CLOSE` discrepancy with a venue net of zero
- WHEN prepare runs
- THEN the test of this requirement does not refuse it

#### Scenario: A short position reduces towards zero

- GIVEN a ledger net of -0.5 and a venue net of -0.2
- WHEN prepare runs
- THEN the difference reduces the position and is not refused by this requirement

### Requirement: Automatic Booking Refuses Fills Of An Order This System Placed

`PrepareBooking` MUST refuse, with one WARNING and no row, a discrepancy when any matched fill's `exchange_order_id` equals the `exchange_order_id` of an `execution_attempts` row of the same pool. Such fills are the system's own and are recorded by `SettleExecution` or its recovery, never as a venue-originated close; booking them to another strategy would be a permanent wrong attribution. The refusal's code is `SYSTEM_ORDER_FILL`. This MUST be decided in prepare, not in the automatic step, so that a PENDING proposal keeps meaning "approvable". The attempt's lookup MUST go through a read port over `SqlAlchemyExecutionAttemptRepository`.

#### Scenario: The example of strategy B's unrecorded open fills

- GIVEN strategy B opened 0.3 and its settle exhausted its retries, so B's fills are unrecorded and B has no open allocation, and strategy A holds 0.5 on the same symbol, and the venue reads 0.8
- WHEN prepare runs
- THEN the sum matches exactly but no proposal is created for A, one WARNING is logged, and the code `SYSTEM_ORDER_FILL` or `GROWS_OR_FLIPS` is returned

#### Scenario: A fill with an outside order id is booked

- GIVEN matched fills whose order ids belong to no `execution_attempts` row of the pool
- WHEN prepare runs
- THEN a proposal is created

#### Scenario: Another pool's attempt does not refuse

- GIVEN a matched fill whose order id equals that of an attempt of a different pool
- WHEN prepare runs
- THEN this requirement does not refuse it

### Requirement: Every Refusal Is Returned With A Code From One Closed Vocabulary

`BookingRefusal` MUST be a closed `StrEnum` in `reconciliation/domain/booking.py` with exactly these codes: `SUM_MISMATCH`, `MIXED_SIDES`, `ZERO_UNRECORDED`, `NONPOSITIVE_QUANTITY`, `WINDOW_TOO_LONG`, `MARKET_MISMATCH`, `VENUE_READ_FAILED`, `NO_ORDER_ID`, `SEVERAL_ALLOCATIONS`, `SUPPRESSED_BY_REJECTION`, `GROWS_OR_FLIPS`, `SYSTEM_ORDER_FILL`, `STALE_AT_APPROVAL`. `PrepareBookingResult.refusals` MUST map a discrepancy id to its code, filled by every refusal branch next to that branch's WARNING. The automatic step's result MUST map each proposal that was not approved to its discrepancy id and a code (`STALE_AT_APPROVAL` for SUPERSEDED and EXPIRED). The handler MUST merge both into a module-level memory that drops an id once it is booked or resolved. Each code MUST have one fixed English phrase.

#### Scenario: Every old and new refusal branch returns its code

- GIVEN each refusal condition of "Refusal Logging", one at a time
- WHEN prepare runs
- THEN the result's `refusals` holds that discrepancy's id with the code named for the condition

#### Scenario: A stale approval returns STALE_AT_APPROVAL

- GIVEN a proposal that the automatic step finds SUPERSEDED or EXPIRED
- WHEN the step returns
- THEN its result maps the proposal's discrepancy id to `STALE_AT_APPROVAL`

#### Scenario: The memory drops a booked or resolved id

- GIVEN a remembered refusal for a discrepancy that is then booked
- WHEN the handler's next run completes
- THEN the id is no longer in the memory

### Requirement: Automatic Approval Takes Only The Proposal's Row Lock

The automatic step MUST take no pool advisory lock: a booking reads no availability and writes no reservation, so capital-allocation's serialized allocation does not govern it. The only lock MUST be the proposal's `FOR UPDATE` row lock, held from `get_for_update` to the commit of the same proposal's approval. A second actor on the same proposal MUST wait for that lock, then read the committed state and return ALREADY_DECIDED, writing nothing. If a later change makes booking write a reservation or move availability, it MUST take the pool lock FIRST, before `get_for_update`, the order every other path uses.

#### Scenario: A second approver waits for the row lock

- GIVEN a connection holding `SELECT ... FOR UPDATE` on a PENDING proposal, on real PostgreSQL
- WHEN the automatic step starts for the same proposal in a task
- THEN after a bounded wait the task is not done; once the first connection marks the proposal APPROVED and commits, the task returns ALREADY_DECIDED and exactly one attempt row exists

#### Scenario: The wait is not vacuous

- GIVEN a copy of the call without the row lock
- WHEN the same test runs against it
- THEN the wait assertion fails

#### Scenario: No pool lock is taken

- GIVEN the automatic step runs a booking
- WHEN the transaction's locks are read
- THEN no advisory lock keyed by a pool is held

### Requirement: A Fault In An Approval Stops The Run And Is Loud

`BookingProposalNotFound`, `InvariantViolation`, an unexpected `IntegrityError` and any other exception raised by an approval MUST propagate out of the automatic step: the session is discarded, the job fails and is retried by the queue, and no successor is enqueued for that run. They MUST NOT be caught per proposal. An exhausted job reaches the watchdog's ERRORs ("ended FAILED", "nothing scheduled"), which reach Telegram. The cost, accepted by the design, is that one poisoned proposal halts every booking until it is fixed, and it does so loudly.

#### Scenario: An unexpected exception enqueues no successor

- GIVEN an approval that raises an unexpected exception
- WHEN the handler runs
- THEN the exception propagates and no successor is enqueued

#### Scenario: The run is cut by the list's limit

- GIVEN more PENDING proposals than `list_pending`'s limit
- WHEN the step runs
- THEN the rest are approved on the next run and the INFO summary names the count

### Requirement: A Proposal Still PENDING At Deploy Is Booked If Current, Otherwise Discarded And Prepared Again

A PENDING proposal present when this change is deployed MUST be approved by the first non-dry-run run if it is still fresh; otherwise it MUST become SUPERSEDED or EXPIRED and be prepared again by a later sweep (owner decision 66, Q1). A historical REJECTED row MUST keep suppressing its identical observation, which then reaches the owner through the grace of the rule of attention.

#### Scenario: A fresh leftover is booked

- GIVEN a PENDING proposal prepared before the deploy and still fresh
- WHEN the first non-dry-run job runs
- THEN it is APPROVED with `decided_by` `system:auto-booking`

#### Scenario: A stale leftover is discarded and prepared again

- GIVEN a PENDING proposal prepared before the deploy whose discrepancy moved
- WHEN the first non-dry-run job runs
- THEN it becomes SUPERSEDED and a later sweep prepares a new proposal

### Requirement: Approval Of A Prepared Proposal Never Books The Two Ambiguous Kinds

`AMBIGUOUS_PARTIAL_REDUCE` and `NO_MATCHING_ALLOCATION` MUST never be prepared and therefore never booked, automatically or otherwise: the first would need an invented rule of attribution written permanently, and the second has no allocation to book to.

#### Scenario: Neither ambiguous kind produces a proposal

- GIVEN a CONFIRMED `AMBIGUOUS_PARTIAL_REDUCE` row and a CONFIRMED `NO_MATCHING_ALLOCATION` row
- WHEN the job runs
- THEN no proposal exists for either and no ledger row was written
