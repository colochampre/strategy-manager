<!-- Materialized verbatim from Engram topic sdd/book-venue-closes/spec (observation #233) on 2026-09-23. Engram stays the mirror; edit here first. -->

# Spec: book-venue-closes (reconciliation slice 2)

Owner decisions (#232) vs proposal (#231): **no conflicts found** — the owner
confirmed all six open-question recommendations (Q1–Q6) and both shaping
decisions verbatim. This spec treats them as binding requirements, not
recommendations.


## Delta: trade-execution — ADDED

### Requirement: Execution Attempt Origin
`execution_attempts` MUST carry `origin` (`SYSTEM`|`VENUE`), NOT NULL,
defaulted `SYSTEM` for pre-existing rows. Downgrading the migration MUST
refuse while any VENUE-origin attempt exists, rather than deleting trading
history.

- GIVEN a new system-submitted attempt, WHEN recorded, THEN `origin='SYSTEM'`.
- GIVEN a VENUE-origin attempt exists, WHEN the migration is downgraded, THEN it refuses.

### Requirement: Venue-Origin Attempt Is Constructed Already Filled
A VENUE-origin attempt MUST be constructed directly in status FILLED; it MUST
NEVER pass through SUBMITTED and MUST NEVER be sent to `ExchangePort`, because
the fill already happened at the venue.

- GIVEN an approved booking, WHEN the attempt is constructed, THEN it is FILLED immediately and no order is submitted to any exchange.
