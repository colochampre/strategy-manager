# Venue-Reconciliation Specification (delta of change `operator-panel`, PR 15)

> **Added 2026-10-16 (owner decision 66; design addendum "PR 15 — Confirmed discrepancies", sections B, D, E and G; the owner's answers Q2 to Q6 and Q9 of 2026-10-16).**
>
> A discrepancy is CONFIRMED after `reconciliation_confirmations` consecutive scans. This delta adds one pure rule that sorts every open CONFIRMED discrepancy into who must act, the announcement and the reminder that tell the owner, and the route the panel reads. It reads the confirmation STATE, never the presence of `confirmed_at`, as "Confirmation State And Its Timestamp Are Not The Same Question" requires. The scan, the verdict classification and the detection-only write boundary are unchanged.

## MODIFIED Requirements

### Requirement: Confirmed Attributable Discrepancy Yields a Booking Proposal

A discrepancy reaching CONFIRMED with verdict `ATTRIBUTABLE_SINGLE_ALLOCATION` or `ATTRIBUTABLE_FULL_CLOSE` MUST cause a booking proposal to be PREPARED, unless suppressed by a historical rejection or refused by one of the conditions of venue-close-booking's "Refusal Logging", and a prepared proposal MUST then be booked automatically by the worker (venue-close-booking, "Prepared Proposals Are Approved By The Worker In The Same Job, After The Sweep Has Committed"). `AMBIGUOUS_PARTIAL_REDUCE` and `NO_MATCHING_ALLOCATION` MUST NEVER be proposed; they MUST be shown to the owner and announced instead (this delta, "Confirmed Discrepancies Needing The Owner Are Announced").

(Previously: the proposal waited for an owner's approval.)

#### Scenario: A confirmed single-allocation row yields a proposal

- GIVEN a CONFIRMED `ATTRIBUTABLE_SINGLE_ALLOCATION` row
- WHEN prepare runs
- THEN a proposal is created

#### Scenario: A confirmed ambiguous row yields none

- GIVEN a CONFIRMED `AMBIGUOUS_PARTIAL_REDUCE` or `NO_MATCHING_ALLOCATION` row
- WHEN prepare runs
- THEN no proposal is created and the row is sorted as needing the owner

### Requirement: Rejection Suppresses Identical Re-Proposal

GIVEN a CONFIRMED discrepancy holding a REJECTED proposal whose frozen Observation triple is byte-identical to the discrepancy's current observation, prepare MUST skip it, log one WARNING and return the code `SUPPRESSED_BY_REJECTION`. If the observation moves, a fresh proposal MUST be prepared. No new rejection can be written after this change (the reject route is removed); the rule applies to REJECTED rows that already exist, which the rule of attention then reaches through its grace.

(Previously: the rule applied to rejections made through the reject route.)

#### Scenario: An unchanged rejected observation is skipped

- GIVEN a historical REJECTED proposal with an unchanged observation
- WHEN prepare runs
- THEN no new proposal appears and the code `SUPPRESSED_BY_REJECTION` is returned

#### Scenario: A moved observation is prepared again

- GIVEN the observation moved since the rejection
- WHEN prepare runs
- THEN a fresh proposal is created

#### Scenario: The suppressed discrepancy reaches the owner after the grace

- GIVEN a CONFIRMED attributable discrepancy suppressed by a historical rejection and confirmed more than the grace ago
- WHEN the rule of attention sorts it
- THEN it needs the owner with the reason `NOT_BOOKED`

## ADDED Requirements

### Requirement: One Pure Rule Sorts Every Open Confirmed Discrepancy By Who Must Act

`reconciliation/domain/attention.py` MUST hold one pure function (no framework) that sorts every open CONFIRMED discrepancy into exactly one of three groups: NEEDS_OWNER, BEING_BOOKED, BOOKED. An `OBSERVED` or resolved row MUST belong to none. Its inputs are the row, `now`, the grace, whether the discrepancy has more than one open allocation, and whether an `APPROVED` proposal for that discrepancy froze the row's CURRENT observation (kind and both nets, compared by `Decimal` value). The first matching condition wins:

1. the kind is `AMBIGUOUS_PARTIAL_REDUCE` or `NO_MATCHING_ALLOCATION`: NEEDS_OWNER, reason `NOT_BOOKABLE`;
2. an `APPROVED` proposal froze the current observation: BOOKED (waiting for the next scan to resolve it);
3. more than one open allocation: NEEDS_OWNER, reason `SEVERAL_ALLOCATIONS`;
4. `now - confirmed_at` is more than the grace: NEEDS_OWNER, reason `NOT_BOOKED`;
5. otherwise: BEING_BOOKED.

The grace MUST be the setting `reconciliation_auto_booking_grace_seconds`, default 300 (five prepare intervals; owner decision 66, Q3). The nav badge, the view's first list and the announcement MUST all use this one function, so they cannot disagree. A booking MUST NEVER count as needing the owner.

#### Scenario: Each ambiguous kind needs the owner at once

- GIVEN a CONFIRMED `NO_MATCHING_ALLOCATION` row confirmed one second ago
- WHEN it is sorted
- THEN it is NEEDS_OWNER with reason `NOT_BOOKABLE`; and the same for `AMBIGUOUS_PARTIAL_REDUCE`

#### Scenario: A booked current observation is hidden as booked

- GIVEN an attributable row and an APPROVED proposal that froze its current observation
- WHEN it is sorted
- THEN it is BOOKED

#### Scenario: A booking that the venue then outran is not hidden

- GIVEN an APPROVED proposal and a later scan that moved the row's observation
- WHEN the row is sorted
- THEN the earlier booking no longer hides it: it is BEING_BOOKED inside the grace and NEEDS_OWNER with reason `NOT_BOOKED` after it

#### Scenario: Several allocations need the owner at once

- GIVEN an `ATTRIBUTABLE_FULL_CLOSE` row over two open allocations confirmed one second ago
- WHEN it is sorted
- THEN it is NEEDS_OWNER with reason `SEVERAL_ALLOCATIONS`

#### Scenario: An unbooked attributable row inside the grace is being booked

- GIVEN an attributable row with one allocation, confirmed 4 minutes ago and not booked
- WHEN it is sorted
- THEN it is BEING_BOOKED

#### Scenario: Past the grace it needs the owner

- GIVEN the same row confirmed 6 minutes ago
- WHEN it is sorted
- THEN it is NEEDS_OWNER with reason `NOT_BOOKED`

#### Scenario: An OBSERVED or resolved row belongs to no group

- GIVEN an `OBSERVED` row and a resolved row
- WHEN they are sorted
- THEN neither appears in any group

#### Scenario: A row confirmed long ago, demoted and confirmed again counts at once

- GIVEN a row whose `confirmed_at` survived a demotion and is older than the grace
- WHEN it is sorted after being confirmed again
- THEN it is NEEDS_OWNER with reason `NOT_BOOKED`

#### Scenario: The grace is a setting

- GIVEN `reconciliation_auto_booking_grace_seconds` set to 60
- WHEN a row confirmed 2 minutes ago and unbooked is sorted
- THEN it is NEEDS_OWNER

### Requirement: Confirmed Discrepancies Needing The Owner Are Announced

After the automatic step, `AnnounceNeedsOwner` MUST read the open CONFIRMED rows and the APPROVED proposals of those discrepancies, apply the rule above, and collect every NEEDS_OWNER discrepancy not yet announced in this process. If any were collected it MUST log ONE ERROR record naming each by pool, symbol, kind, reason code with its fixed English phrase, and discrepancy id. The record MUST contain no quantity, price or fee. Its message template MUST be the constant `"confirmed discrepancies need the owner: %s"` with the list of items, reasons included, as its single argument, so that a reason never mints a new throttle key. The record's logger MUST be the module's own `strategy_manager.reconciliation...` logger and MUST NOT sit under `strategy_manager.alerts`, which the alert bridge drops. The memory of what was announced MUST be process-scoped and module-level; an id that stops needing the owner MUST be dropped from it, so a recurrence is announced again. Each start of the worker MUST announce everything still open once (owner decision 66, Q4). Automatic bookings MUST NOT be announced. Under `DRY_RUN` nothing runs.

The reason MUST come from the run: rules 1 and 3 of the rule of attention take theirs from the row (`NOT_BOOKABLE` with the kind, `SEVERAL_ALLOCATIONS`); a NOT_BOOKED item takes the code the sweep or the automatic step returned for it in this process; a NOT_BOOKED item whose reason this process has not seen MUST be announced as `REASON_UNKNOWN`, "see the worker log", and MUST NEVER be left out.

#### Scenario: One record lists two new items with their reasons

- GIVEN two NEEDS_OWNER items, one `NOT_BOOKED` with the code `SUM_MISMATCH` from this run's sweep and one `NOT_BOOKABLE`
- WHEN the announcement runs
- THEN exactly one ERROR record is logged, naming both with their reason codes and phrases and their discrepancy ids

#### Scenario: An unknown reason is announced, not dropped

- GIVEN a NOT_BOOKED item no sweep of this process has refused
- WHEN the announcement runs
- THEN its entry reads `REASON_UNKNOWN` and points to the worker log

#### Scenario: The second run announces nothing new

- GIVEN the same items on a second run
- WHEN the announcement runs
- THEN no record is logged

#### Scenario: A recurrence is announced again

- GIVEN an item that stopped needing the owner and then returns
- WHEN the announcement runs
- THEN it is announced again

#### Scenario: Different reasons share one throttle key

- GIVEN two announcements with different reasons
- WHEN their records are compared
- THEN both have the same `record.msg`

#### Scenario: The record carries no quantity and sits outside the alerts logger

- GIVEN an announcement
- WHEN its record is read
- THEN its message holds no quantity, price or fee and its logger is not under `strategy_manager.alerts`

#### Scenario: The bridge delivers it

- GIVEN a fake `AlertPort` behind a real `AlertLogBridge`
- WHEN the announcement runs
- THEN the record is delivered to the port

#### Scenario: Automatic bookings are not announced

- GIVEN a discrepancy booked automatically
- WHEN the announcement runs
- THEN nothing is logged for it above INFO

#### Scenario: Nothing is announced under DRY_RUN

- GIVEN `DRY_RUN=true`
- WHEN the handler runs
- THEN the announcement is not called

### Requirement: A Daily Reminder Repeats What Still Needs The Owner

While anything is NEEDS_OWNER, at most one ERROR every `reconciliation_needs_owner_reminder_seconds` (default 86400) MUST list every such item with its reason. It MUST be timed from the process's last announcement or reminder. It MUST use its OWN constant template, `"reminder: %d confirmed discrepancies still need the owner: %s"`, so the alert throttle (one message per logger and message template every 900 s) cannot fold it into an announcement made in the same window. It MUST NOT fire when nothing needs the owner.

#### Scenario: The reminder fires after the interval

- GIVEN an item still needing the owner and an injected clock advanced by the reminder interval
- WHEN the announcement step runs
- THEN one ERROR is logged listing every item that needs the owner, with a `record.msg` different from the announcement's

#### Scenario: It does not fire early

- GIVEN the clock advanced by less than the interval
- WHEN the step runs
- THEN no reminder is logged

#### Scenario: It does not fire when nothing needs the owner

- GIVEN no item needs the owner and the interval has passed
- WHEN the step runs
- THEN no reminder is logged

#### Scenario: It closes the throttle's gap

- GIVEN two discrepancies confirmed within 900 s of each other, the second announcement possibly folded by the throttle
- WHEN the reminder fires
- THEN both are listed in it

### Requirement: Confirmed Discrepancy Read Endpoint

`GET /reconciliation/confirmed` MUST be mounted on the existing reconciliation router, behind the admin bearer attached at router level, read-only, taking no parameter, and answering for the whole system. The body MUST be:

`{ "read_at", "dry_run", "needs_owner_count", "needs_owner": [Discrepancy], "being_booked": [Discrepancy], "booked": [Booking] }`

where a Discrepancy is `{ "discrepancy_id", "exchange", "venue", "settlement_currency", "symbol", "kind", "reason": "NOT_BOOKABLE" | "SEVERAL_ALLOCATIONS" | "NOT_BOOKED" | null, "venue_net_base", "ledger_net_base", "allocations": [{ "allocation_id", "strategy_id", "strategy_name" }], "confirmed_at", "last_observed_at" }` and a Booking is `{ "proposal_id", "discrepancy_id", "exchange", "venue", "settlement_currency", "symbol", "kind", "strategy_id", "strategy_name", "allocation_id", "side", "quantity", "fill_count", "decided_at", "decided_by": "automatic" | "owner", "execution_attempt_id", "discrepancy_open" }`.

`needs_owner_count` MUST equal the length of `needs_owner`. Quantities and money MUST be strings. `dry_run` MUST be `settings.dry_run`. `booked` MUST hold every APPROVED proposal decided within the last 30 days, or whose discrepancy is still open, newest first, at most 100 (owner decision 66, Q5); `discrepancy_open` says whether the scan has resolved its discrepancy yet; `decided_by` is `automatic` for `system:auto-booking` and `owner` otherwise. The route MUST read through three statements regardless of the number of rows (the open CONFIRMED discrepancies, the APPROVED proposals, the strategy names by allocation id) and MUST write nothing. A fault in stored data, such as an allocation whose strategy row is missing, MUST be served with `strategy_name: null` and logged at WARNING with the ids, never ERROR: the route is polled every 60 s per open tab and an ERROR here would flood the alerts that the announcement relies on. `GET /reconciliation/discrepancies` MUST be unchanged.

#### Scenario: Unauthenticated request is refused

- GIVEN no bearer token
- WHEN `GET /api/reconciliation/confirmed` is called
- THEN the request is refused before reaching handler logic

#### Scenario: The body has the agreed shape

- GIVEN one NEEDS_OWNER item, one BEING_BOOKED item and one automatic booking
- WHEN the route is called
- THEN the body holds the three lists with every key above, quantities as strings, and `needs_owner_count` equal to 1

#### Scenario: The count equals the list

- GIVEN any number of NEEDS_OWNER items
- WHEN the route is called
- THEN `needs_owner_count` equals `len(needs_owner)`

#### Scenario: The whole system is served

- GIVEN confirmed discrepancies on two exchanges
- WHEN the route is called
- THEN both appear, each naming its exchange, venue and settlement currency

#### Scenario: A booking older than 30 days is left out unless its discrepancy is open

- GIVEN an automatic booking decided 31 days ago whose discrepancy is resolved, and another decided 31 days ago whose discrepancy is open
- WHEN the route is called
- THEN the first is absent and the second is present

#### Scenario: At most 100 bookings, newest first

- GIVEN 101 automatic bookings within 30 days
- WHEN the route is called
- THEN `booked` holds 100 in descending `decided_at`

#### Scenario: A booking approved before the deploy is attributed to the owner

- GIVEN an APPROVED proposal whose `decided_by` is not `system:auto-booking`
- WHEN the route is called
- THEN its `decided_by` is `owner`

#### Scenario: A missing strategy row is served as null with one WARNING

- GIVEN an allocation whose strategy row is missing
- WHEN the route is called
- THEN the allocation is served with `strategy_name: null` and one WARNING names the allocation id, and no ERROR is logged

#### Scenario: The statement count does not grow with the rows

- GIVEN 1 and then 20 open discrepancies
- WHEN the route is called each time
- THEN the number of statements is the same

#### Scenario: The route writes nothing

- GIVEN a table snapshot
- WHEN the route is called
- THEN no row of any table changed

#### Scenario: The dry-run flag is served

- GIVEN `DRY_RUN=true`
- WHEN the route is called
- THEN `dry_run` is `true`

#### Scenario: The older list route is unchanged

- GIVEN open discrepancies
- WHEN `GET /api/reconciliation/discrepancies` is called
- THEN its answer is as before this change
