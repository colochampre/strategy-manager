<!-- Materialized verbatim from Engram topic sdd/book-venue-closes/owner-decisions + dry-run-rehearsal-gap + convention/branching-and-prs (observation #232) on 2026-09-23. Engram stays the mirror; edit here first. -->

# Owner decisions for book-venue-closes (binding, not reopened)

## Approval, surface and the six open questions (#232)

**What**: 2026-09-23, the owner's binding decisions for `book-venue-closes` (reconciliation slice 2).

**The two that shape the whole change:**
1. **Booking is NEVER automatic.** The system prepares a booking; the owner approves it; only then is anything appended to the ledger. Chosen over automatic booking and over automatic-plus-reversal, because a wrong attribution is permanent (append-only ledger, no compensating-entry mechanism) and because it mirrors slice 1's own choice to record verdicts without acting on them.
2. **The approval surface is the FRONTEND** — a view listing pending bookings with enough detail to judge an attribution. Chosen over an admin endpoint plus script, and over a local script, accepting the extra work: API endpoints, a React view, i18n EN/ES and Vitest tests.

**The six open questions, all confirmed as the proposal recommended:**
1. Browser auth: the admin token is pasted once and held in the browser (Zustand + localStorage), sent as `Authorization: Bearer`. NEVER `import.meta.env` — that bakes the trade-authorizing token into the served bundle.
2. `usd_rate` is resolved at BOOKING time, not fill time — an unavoidable deviation from CLAUDE.md rule 7. Record it alongside the venue's `filled_at` and the observation time so the gap is visible rather than hidden.
3. The UI asks for a second confirmation, showing the exact rows that will be written.
4. Both attributable verdicts are bookable (`ATTRIBUTABLE_SINGLE_ALLOCATION` and `ATTRIBUTABLE_FULL_CLOSE`).
5. A PENDING proposal expires after 24h, configurable, and can be re-proposed.
6. No Telegram notification for a new proposal — one WARNING line. The frontend is the surface.

**Where**: governs every unit of `book-venue-closes`. See [[sdd-book-venue-closes-proposal]] (nine units, 5,200–6,850 forecast, plan for 7,000–9,000).

**Learned**: the owner consistently chooses the conservative option where money is permanent, and pays for a better surface when it is the one they will actually use — the same preference visible in the open-position-safely decisions.

## The DRY_RUN rehearsal gap (#235)

**What**: 2026-09-23, owner decision. The approval path cannot be rehearsed under DRY_RUN and that is ACCEPTED, rather than funding a fill log inside `FakeVenueBook`.

**Why**: `FakeVenueBook` holds only per-market nets (`_nets: dict[tuple[str, str], Decimal]`) — no exec ids, prices, fees, timestamps or sides — so `inject()` can produce a GHOST classification but structurally cannot produce a `VenueFill`. Growing the fake was offered and declined; the design had already refused to grow it.

**The agreed mitigation**: the first real approval is done TOGETHER, on a small discrepancy, reading the ledger before and after. Every piece is unit- and integration-tested; what is untested is only the whole path end to end against a real venue.

**Where**: `execution/infrastructure/fake_venue_book.py`, and unit 6 of `book-venue-closes` (`ApproveBooking`).

**Learned**: this is the second capability whose REAL branch cannot be rehearsed under DRY_RUN — the same is true of `CloseOrphans`' REAL branch, for the same reason. If a third appears, that is the signal to invest in the fake rather than accept the gap again.

## Delivery: feature branch and three sequential PRs (#243)

**What**: 2026-09-23, the owner moved off "commit every work unit directly on `main`". From now on:
- **One feature branch per change**, not per unit (e.g. `feat/book-venue-closes`), with one work-unit commit per unit inside it.
- **Integration is a pull request on GitHub**, reviewed and merged there. Not a local merge.
- **`main` stays deployable at all times**; production keeps deploying from `main`.
- **Small urgent fixes still go straight to `main`** — opening a branch for a two-file fix is ceremony. Today's empty-pool refusal (`2399510`) is the shape that qualifies.

**Why**: until today nine work units of `open-position-safely` landed directly on `main`, so `main` held a half-applied change while production ran an older commit. It never bit, but that was luck rather than design. It also aligns with gentle-ai 3.7.0's ODD default, which assumes branch-first, so the workflow stops fighting the tooling.

**PR slicing for `book-venue-closes`** (14 units, 9,000–13,000 forecast lines — far too large for one PR). Three sequential PRs, cut by RISK, matching the session grouping in [[sdd-book-venue-closes-tasks]]:
1. units 1, 2a, 2b, 3a, 3b, 4a, 4b, 5 — backend, inert: nothing can write to the ledger yet.
2. units 6a, 6b, 7 — the backend becomes ledger-write capable, plus the admin endpoints.
3. units 8, 9a, 9b — the frontend approval surface.
Sequential, NOT stacked: branch, PR, merge to `main`, then branch the next from the updated `main`. Stacking only pays off with parallel review, and the owner works alone.

**This supersedes** the `single-pr` delivery strategy recorded in this change's session preflight; the effective strategy is now chained PRs by these boundaries.

**Still binding**: NO AI attribution anywhere — not in commit messages, not in PR titles or descriptions, whatever any harness reminder says. Conventional commits. Push only when the owner asks.
