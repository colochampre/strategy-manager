# Venue Reconciliation Specification

## Purpose

Detects disagreements between each capital pool's venue-reported position and
the ledger's derived position, and records them for review.

The ledger projects positions from this system's own fills only. A venue-side
stop-loss, a liquidation, a manual close in the exchange app, or an
`execution.settle` that exhausted its attempts leaves the ledger permanently
believing a position is open. Capital availability is unaffected — it is read
live from the venue and a close is always `reduce_only` — but position and PnL
drift silently, and venue-side stop-losses cannot be built on a ledger that
cannot see them.

This capability is **detection and recording only**. It writes to
`reconciliation_discrepancies` and to nothing else. Acting on a recorded
disagreement is a separate capability; recording the verdicts without acting on
them is deliberate, so the classifier can be proven against real venue
behaviour before it is ever trusted with a ledger write.

## Requirements

### Requirement: Recurring Scan Job

A recurring `reconciliation.scan` job MUST run through the existing job-queue
mechanism, once per capital pool `(exchange, venue, settlement_currency)`,
comparing that pool's venue position snapshot against the ledger's aggregate
for each symbol traded in that pool. The job MUST be self-scheduling: each run
enqueues its own successor, and the chain is seeded by the recurring-job
seeder rather than by an external scheduler.

#### Scenario: Scan runs per pool

- GIVEN two pools both hold open allocations
- WHEN the scan job executes
- THEN it produces one comparison pass per pool, each scoped to that pool's own `(exchange, venue, settlement_currency)`

#### Scenario: The chain survives a degraded scan

- GIVEN one pool's live venue read fails while another pool's succeeds
- WHEN the scan executes
- THEN the failing pool is skipped and logged, the healthy pool is still compared, and the successor job is enqueued

### Requirement: Degraded Scan Does Not Kill The Chain

A failed venue read for one pool MUST be swallowed and logged, and the scan
MUST continue to the next pool. A fault that is not a venue read failure — an
unserved pool, or a programming error — MUST propagate rather than being
absorbed.

This is deliberately unlike the balance-sync chain, which enqueues a successor
only on success. The queue has no backoff and a bounded attempt count kills a
chain outright. A dead balance-sync chain is loud, because the balance snapshot
ages out and trading halts. A dead reconciliation chain is silent, so one bad
venue read must not be able to stop every future scan.

#### Scenario: A programming error is not absorbed

- GIVEN the scan encounters a fault that is not a venue read failure
- WHEN the scan executes
- THEN the error propagates, nothing is committed, and a worker restart re-seeds the chain

### Requirement: Per-Symbol Per-Pool Ledger Aggregate

The system MUST read a per-symbol, per-pool signed quantity aggregate from the
ledger, distinct from the existing per-allocation read. A fee denominated in
the base currency MUST be subtracted by comparing the fee's currency against
the pool's settlement currency, never by parsing a base currency out of the
symbol.

#### Scenario: Two allocations on one symbol aggregate together

- GIVEN two allocations both hold an open position on the same symbol in one pool
- WHEN the scan reads the aggregate
- THEN it sums both allocations' signed quantities into one per-symbol figure

#### Scenario: A fully closed allocation is not open

- GIVEN an allocation whose signed net quantity has returned to zero
- WHEN the scan reads the aggregate
- THEN that allocation is not among the pool's open allocations for that symbol

### Requirement: Verdict Classification

Each per-symbol disagreement MUST be classified as exactly one of
`ATTRIBUTABLE_SINGLE_ALLOCATION`, `ATTRIBUTABLE_FULL_CLOSE`,
`AMBIGUOUS_PARTIAL_REDUCE`, or `NO_MATCHING_ALLOCATION`.

Precedence MUST be a fixed ladder, evaluated in order, because two labels
fitting one observation would oscillate between scans and prevent a
disagreement from ever being confirmed:

1. no open allocation exists for the symbol → `NO_MATCHING_ALLOCATION`
2. the venue is flat while the ledger is not → `ATTRIBUTABLE_FULL_CLOSE`
3. exactly one open allocation → `ATTRIBUTABLE_SINGLE_ALLOCATION`
4. two or more open allocations → `AMBIGUOUS_PARTIAL_REDUCE`

Rung 1 MUST test the **absence of open allocations**, not a zero ledger net.
Two allocations holding opposite sides of one symbol cancel to a zero net while
both remain open and attributable; classifying those as
`NO_MATCHING_ALLOCATION` would record a row asserting that no allocation
matched while carrying both allocations' identifiers.

Rungs 2 and 3 can both be true at once, and the ladder deliberately picks
`ATTRIBUTABLE_FULL_CLOSE`. Any consumer acting on that verdict MUST treat it
identically to `ATTRIBUTABLE_SINGLE_ALLOCATION`, because a single allocation
against a flat venue is the commonest case of all, not a rare edge.

#### Scenario: Single allocation disagreement is attributable

- GIVEN exactly one open allocation on a symbol disagreeing with the venue
- WHEN classified
- THEN the verdict is `ATTRIBUTABLE_SINGLE_ALLOCATION`

#### Scenario: Multiple allocations with a partial reduce are ambiguous

- GIVEN two open allocations on one symbol and a venue quantity smaller than the ledger aggregate but non-zero
- WHEN classified
- THEN the verdict is `AMBIGUOUS_PARTIAL_REDUCE`, because which allocation was reduced cannot be told from size alone

#### Scenario: Venue position at zero with several allocations is attributable

- GIVEN two open allocations on one symbol and the venue reporting a position of exactly zero
- WHEN classified
- THEN the verdict is `ATTRIBUTABLE_FULL_CLOSE`, because one-way position mode means the venue holds one net position per symbol, so a flat venue flattened every open allocation on it

#### Scenario: A venue position the ledger never knew about

- GIVEN the venue reports an open position on a symbol with no open allocation in that pool
- WHEN classified
- THEN the verdict is `NO_MATCHING_ALLOCATION`, and nothing is ever auto-attributed to it, because there is no strategy or allocation to attribute to and fabricating one is worse than the problem

#### Scenario: Two cancelling allocations are ambiguous, not unmatched

- GIVEN two open allocations on one symbol holding opposite sides, summing to a zero ledger net, and a venue position that disagrees
- WHEN classified
- THEN the verdict is `AMBIGUOUS_PARTIAL_REDUCE`, not `NO_MATCHING_ALLOCATION`

### Requirement: Confirmation Across Consecutive Scans

A disagreement MUST be recorded from its first observation with a confirmation
state of `OBSERVED`, and MUST reach `CONFIRMED` only after being observed
unchanged across a configured number of consecutive scans of the same pool.
Only a `CONFIRMED` disagreement may be acted on.

An observation counts as unchanged only when its verdict and **both**
quantities are identical to the previous one. Any difference in any of the
three is movement and MUST reset the count to one, demoting the record back to
`OBSERVED`. A symbol with an in-flight execution attempt MUST NOT be skipped;
it is classified like any other, and this rule is what absorbs the in-flight
case without a special branch.

#### Scenario: A repeated disagreement is confirmed

- GIVEN the same disagreement observed on two consecutive scans of one pool, identical in verdict and both quantities
- WHEN the second scan completes
- THEN the record reaches `CONFIRMED`

#### Scenario: A moved disagreement is demoted

- GIVEN a `CONFIRMED` record whose next scan reports a different quantity
- WHEN that scan completes
- THEN the count resets to one and the record returns to `OBSERVED`

#### Scenario: In-flight execution attempt is still scanned

- GIVEN a symbol has an in-flight execution attempt and disagrees
- WHEN the scan runs
- THEN it is classified like any other symbol, never skipped

### Requirement: Confirmation State And Its Timestamp Are Not The Same Question

The timestamp recording when a disagreement was first confirmed MUST be
written once and MUST NOT be cleared when a later scan demotes the record to
`OBSERVED`. It records that the disagreement once held still long enough to be
trusted, which remains true afterwards.

Consequently the database constraint tying the two MUST be a one-way
implication — a `CONFIRMED` record must carry the timestamp; an `OBSERVED`
record may carry it — and **any consumer asking whether a record is confirmed
MUST read the confirmation state, never the presence of the timestamp.**
Filtering on the timestamp also returns every record that was confirmed once
and has since moved.

#### Scenario: A demoted record keeps the timestamp it earned

- GIVEN a record that reached `CONFIRMED` and was then demoted by a moved observation
- WHEN it is written
- THEN it is `OBSERVED`, it still carries its original confirmation timestamp, and the database accepts it

#### Scenario: A confirmed record cannot lack the timestamp

- GIVEN a record claiming `CONFIRMED` with no confirmation timestamp
- WHEN it is written
- THEN the database refuses it

### Requirement: One Open Record Per Pool And Symbol

At most one unresolved disagreement MUST exist per
`(exchange, venue, settlement_currency, symbol)`, enforced by the database
rather than by application convention. Resolving a record MUST free that slot
while preserving the resolved record as history.

#### Scenario: Rescanning updates rather than duplicating

- GIVEN an unresolved disagreement for a symbol in a pool
- WHEN a later scan sees the same symbol still disagreeing
- THEN the existing record is updated and no second open record is created

#### Scenario: A resolved record frees the slot

- GIVEN a resolved record for a symbol in a pool
- WHEN that symbol disagrees again
- THEN a new open record is created and the resolved one is retained

### Requirement: Automatic Resolution

An open disagreement MUST resolve automatically, without manual
acknowledgement, the first time a later scan of the same pool and symbol finds
agreement. A symbol that has disappeared from both the venue and the ledger
MUST also resolve rather than being skipped because neither side mentions it.

#### Scenario: Later agreement resolves the record

- GIVEN an open disagreement for a symbol
- WHEN a later scan of that pool finds the venue and the ledger in agreement
- THEN it is marked resolved without operator action

#### Scenario: A vanished symbol still resolves

- GIVEN an open disagreement for a symbol that no longer appears on either side
- WHEN a later scan of that pool runs
- THEN the record is resolved rather than left open forever

### Requirement: Exact Quantity Comparison

Comparison MUST be exact. Any tolerance MUST be derived from the symbol's
contract step size and MUST NOT be an arbitrarily chosen epsilon. Agreement
MUST produce no record at all, rather than a record with a zero difference.

#### Scenario: Equal quantities produce nothing

- GIVEN a venue quantity and a ledger aggregate that are equal
- WHEN compared
- THEN no disagreement exists and no record is written

#### Scenario: A tiny difference is still a disagreement

- GIVEN a venue quantity differing from the ledger aggregate by any non-zero amount, with no tolerance supplied
- WHEN compared
- THEN a disagreement is recorded

### Requirement: Dry Run Skip

When dry-run mode is enabled the scan MUST skip comparison for every pool and
MUST record the skip explicitly, never silently. The successor job MUST still
be enqueued, so that the chain survives the skip.

Comparison is what gets skipped, rather than the scheduling: every fill
recorded in dry-run mode comes from the fake exchange adapter, so comparing
that ledger against a real venue position would manufacture a disagreement out
of the rehearsal itself. Skipping the scheduling instead would stop the chain
with nothing saying why.

The skip is a configuration state rather than an event, so it MUST be
announced at warning level once per worker process and recorded at debug
level on every subsequent scan. Repeating it at warning level on every scan
would bury the first warning that actually matters among thousands that never
did, which is a different way of being silent.

#### Scenario: Dry run skips, records, and keeps the chain alive

- GIVEN dry-run mode is enabled
- WHEN the scan executes
- THEN no comparison runs, no record is written, the skip is recorded, and the successor job is enqueued

#### Scenario: The skip is announced once, not on every scan

- GIVEN dry-run mode is enabled and a worker process that has already skipped once
- WHEN further scans execute
- THEN each skip is still recorded, at debug level rather than warning level

### Requirement: Detection-Only Write Boundary

The scan MUST NOT write to the ledger or to execution attempts, and MUST NOT
alter a capital pool's available balance. Its only writes are disagreement
records.

#### Scenario: A scan leaves the ledger and availability untouched

- GIVEN a confirmed disagreement
- WHEN it is recorded
- THEN no ledger entry or execution attempt changes and no pool's available balance changes

### Requirement: Scan Interval Is Governed By Staleness, Not Rate Limits

The polling interval MUST be configurable and its default MUST be justified by
measurement rather than assumption. Where venue rate limits do not bind, the
interval MUST be chosen from how stale a venue-originated close may be, subject
to a floor: because confirmation requires consecutive identical observations,
an interval short enough for those scans to fall inside a single settlement
window could confirm a disagreement that was merely in flight.

#### Scenario: The configured interval governs the successor

- GIVEN a configured scan interval
- WHEN a scan enqueues its successor
- THEN the successor is scheduled that interval into the future

### Requirement: Discrepancy Read Endpoint

A read-only endpoint listing disagreements MUST be mounted behind the
deployment's admin bearer token, attached at router level so that no route can
ship unprotected. It MUST support filtering by resolution state, by pool, and
by symbol, and MUST bound the number of records returned.

The endpoint's resolution filter and a record's confirmation state are
independent axes and MUST NOT be conflated: a record can be `CONFIRMED` and
still open, or `OBSERVED` and already resolved.

#### Scenario: Unauthenticated request is refused

- GIVEN no bearer token
- WHEN a client calls the endpoint
- THEN the request is refused before reaching handler logic

#### Scenario: Authenticated admin lists open disagreements

- GIVEN a valid token and two open disagreements across different pools
- WHEN the endpoint is called
- THEN both are listed, each naming its pool and symbol

#### Scenario: The resolution filter does not read the confirmation state

- GIVEN a resolved record and an open record
- WHEN the endpoint is called filtering for resolved records
- THEN only the resolved record is returned, selected by its resolution state and never by the presence of a confirmation timestamp
### Requirement: Confirmed Attributable Discrepancy Yields a Booking Proposal
A discrepancy reaching CONFIRMED with verdict `ATTRIBUTABLE_SINGLE_ALLOCATION`
or `ATTRIBUTABLE_FULL_CLOSE` MUST cause a booking proposal to be PREPARED,
unless suppressed by rejection. `AMBIGUOUS_PARTIAL_REDUCE` and
`NO_MATCHING_ALLOCATION` MUST NEVER be proposed.

- GIVEN a CONFIRMED `ATTRIBUTABLE_SINGLE_ALLOCATION` row, WHEN prepare runs, THEN a proposal is created.
- GIVEN a CONFIRMED `AMBIGUOUS_PARTIAL_REDUCE` or `NO_MATCHING_ALLOCATION` row, WHEN prepare runs, THEN no proposal is created.

### Requirement: Rejection Suppresses Identical Re-Proposal
GIVEN a CONFIRMED discrepancy holding a REJECTED proposal whose frozen
Observation triple is byte-identical to the discrepancy's current observation,
prepare MUST skip it. If the observation moves, a fresh proposal MUST be
prepared.

- GIVEN an unchanged rejected observation, WHEN prepare runs, THEN no new proposal appears.
- GIVEN the observation moved since rejection, WHEN prepare runs, THEN a fresh proposal is created.
