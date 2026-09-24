<!-- Materialized verbatim from Engram topic sdd/book-venue-closes/spec (observation #233) on 2026-09-23. Engram stays the mirror; edit here first. -->

# Spec: book-venue-closes (reconciliation slice 2)

Owner decisions (#232) vs proposal (#231): **no conflicts found** — the owner
confirmed all six open-question recommendations (Q1–Q6) and both shaping
decisions verbatim. This spec treats them as binding requirements, not
recommendations.


## ADDED Requirements

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
