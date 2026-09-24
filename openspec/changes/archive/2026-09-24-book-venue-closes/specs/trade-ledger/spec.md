<!-- Materialized verbatim from Engram topic sdd/book-venue-closes/spec (observation #233) on 2026-09-23. Engram stays the mirror; edit here first. -->

# Spec: book-venue-closes (reconciliation slice 2)

Owner decisions (#232) vs proposal (#231): **no conflicts found** — the owner
confirmed all six open-question recommendations (Q1–Q6) and both shaping
decisions verbatim. This spec treats them as binding requirements, not
recommendations.


## ADDED Requirements

### Requirement: usd_rate Provenance for a Booked Fill (rule 7 deviation, stated explicitly)
For a ledger row originating from a VENUE-origin attempt, `usd_rate_at_fill`
MUST be resolved at booking (approval) time, not at the venue's fill time —
a deliberate deviation from the fill-time rule, because the fill already
occurred and no historical-rate source exists. The row MUST also record the
venue's `filled_at` distinct from the rate's observation time, so the gap is
always computable and never presented as a fill-time rate.

- GIVEN an approved venue-origin fill, WHEN the ledger row is written, THEN it carries both the venue's `filled_at` and a later, distinct rate-observation time.
