<!-- Materialized verbatim from Engram topic sdd/book-venue-closes/tasks (observation #236) on 2026-09-23. Engram stays the mirror; edit here first. -->

> Delivery override, binding: `single-pr` below is superseded by owner decision #243 (convention/branching-and-prs). This change ships as three SEQUENTIAL PRs from `feat/book-venue-closes`: units 1-5, then 6a/6b/7, then 8/9a/9b. The only edit to the Engram text is `- [ ]` added before each numbered task.

# Tasks: Book venue-originated closes (reconciliation slice 2)

SDD phase TASKS, 2026-09-23. HEAD `3fec07a`. Preflight: auto / engram / single-pr / 800.
Follows design (#234), spec (#233), owner-decisions (#232) + dry-run-rehearsal-gap (#235) —
nine owner decisions total, all binding, none reopened here. `delivery_strategy: single-pr`,
`chain_strategy: none`: the owner commits ONE commit per unit directly on `main`, no PRs.

Over the generic 530-word budget on purpose, for the same reason design gave for its own
800-word overage: 14 units, each needing a named RED test first (strict TDD), an honest
forecast, and the three sequencing blockers the brief required — compressing that below
budget is exactly how the previous change's forecast (3,840–5,380) was made to look smaller
than what it actually cost (~10,000, concentrated in `main.py` wiring and integration tests).
Style follows [[sdd/open-position-safely/tasks]] (#208): units in order, one commit each,
every behavioural task opens with its failing test.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 6,700–8,400 bottom-up per design; treat as a FLOOR. open-position-safely's per-unit forecasts summed to roughly this same shape and its actual landed ~2x higher (~10,000), concentrated in job-wiring (`main.py`) and integration units. Plan for **9,000–13,000 actual**, expect the overrun to concentrate in Unit 5 (job wiring — exactly where it landed last time) and Unit 7 (endpoint + integration). |
| 400-line budget risk | High |
| Chained PRs recommended | Yes, as WORK-UNIT boundaries (14 commits), not as separate PRs — `single-pr` forces one PR |
| Suggested split | 14 sequential commits on `main`. Design's own PR-chain shape, kept for reference only in case delivery strategy ever changes: 1+2a+2b → 3a+3b+4a+4b+5 → 6a+6b+7 → 8+9a+9b |
| Delivery strategy | single-pr |
| Chain strategy | none |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: size-exception
400-line budget risk: High

(`single-pr` forces `Decision needed: Yes`; risk is High, so `sdd-apply` must obtain an
explicit `size:exception` before starting — this is ~19x the 400-line budget in one PR.)

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 1 | `execution_attempts.origin` (0022) + blocker (a) | PR 1 | `uv run pytest tests/execution/domain/test_execution_domain.py tests/migrations/test_0022_execution_attempt_origin.py` | Real Postgres, migration up/down | `migrations/versions/0022_*.py` + 2 invariants in `execution_attempt.py`; downgrade to 0021 refuses only once a VENUE row exists (none can yet) |
| 2a | Live probe — blocker (b), 6 items | PR 1 | N/A — run manually: `uv run python scripts/check_venue_fill_windows.py` | Real venue APIs, read-only, run on worker host | `scripts/check_venue_fill_windows.py`, dev tool, not shipped code |
| 2b | Venue fill fetch — blocker (c) | PR 1 | `uv run pytest tests/reconciliation/infrastructure/test_bybit_venue_fill_reader.py tests/reconciliation/infrastructure/test_binance_venue_fill_reader.py` | `httpx.MockTransport` | New `ports.py` additions + 2 readers + registry; unreferenced elsewhere |
| 3a | `booking_proposals` schema (0023) | PR 1 | `uv run pytest tests/migrations/test_0023_booking_proposals.py` | Real Postgres | `migrations/versions/0023_*.py`; downgrade DROPs unconditionally |
| 3b | Proposal repository | PR 1 | `uv run pytest tests/reconciliation/infrastructure/test_booking_proposal_repository_integration.py` | Real Postgres | New repository file, unreferenced until 4a |
| 4a | Booking domain + small ports | PR 1 | `uv run pytest tests/reconciliation/domain/test_booking.py` | None — pure | New `domain/booking.py`, not imported elsewhere yet |
| 4b | `PrepareBooking` use case | PR 1 | `uv run pytest tests/reconciliation/application/test_prepare_booking.py` | Fakes only | New use case file, not wired to any job |
| 5 | Prepare wiring | PR 1 | `uv run pytest tests/reconciliation/application/test_booking_prepare_integration.py` | Real Postgres + fake venue reader | `main.py` job registration, `RECURRING_KINDS`, watchdog set — revert removes the `JobKind` entry |
| 6a | `ApproveBooking` | PR 1 | `uv run pytest tests/reconciliation/application/test_approve_booking_integration.py` | Real Postgres, concurrent-session test | New use case + writer; unreachable without unit 7 |
| 6b | `RejectBooking` + expiry | PR 1 | `uv run pytest tests/reconciliation/application/test_reject_booking.py tests/reconciliation/application/test_expire_booking_proposals.py` | Real Postgres | New use cases; unreachable without unit 7 |
| 7 | Admin endpoints | PR 1 | `uv run pytest tests/reconciliation/infrastructure/test_router.py` | Real Postgres, `TestClient` | New routes on existing router; revert removes 3 handlers |
| 8 | Frontend client + auth | PR 1 | `npm test -- token-store client` | N/A — frontend-only, no backend runtime | New `shared/auth/`, `shared/api/` files; nothing imports them yet |
| 9a | Bookings list view | PR 1 | `npm test -- BookingsListView` | N/A — frontend-only | New `features/bookings/` view + nav change in `App.tsx` |
| 9b | Confirm + reject dialogs | PR 1 | `npm test -- ConfirmBookingDialog RejectBookingDialog` | N/A — frontend-only | New dialog files; completes the feature |

## Blockers — sequenced first, none reopened

| Blocker | Landing task | Why here |
|---|---|---|
| (a) real name of the `client_order_id` unique constraint | Task 1.1 | Same table family as 0022; costs nothing to verify before any migration lands; 6a's `IntegrityError`-by-name matching must import the recorded constant, never a guessed literal (design flagged 0005 used `unique=True`, which does not fix the name) |
| (b) live probe, now SIX items | Unit 2a (whole unit) | Design's own dependency chain (2a→2b→5) already forces this order; item (f) — key acceptance on the fill endpoint — is new, added by design over the proposal's five |
| (c) `VenueFill` needs `side` | Task 2b.1 | First task of the DTO work; `Fill` (7 fields) has no `side` because an order-scoped fetch inherits it from the order — a window fetch has no order. Corrects explore #230 Q3 |

## Unit 1 — `execution_attempts.origin` (350–450 lines)

- [x] 1.1 **[Blocker a]** Query the live schema (`SELECT conname FROM pg_constraint WHERE conrelid='execution_attempts'::regclass AND contype='u'`). RED: `tests/migrations/test_0022_execution_attempt_origin.py::test_client_order_id_constraint_name_matches_recorded_constant` asserting the live name equals a new `CLIENT_ORDER_ID_UNIQUE_CONSTRAINT` constant in `execution/infrastructure/repository.py`. GREEN: record the confirmed name.
- [x] 1.2 RED `tests/execution/domain/test_execution_domain.py::test_venue_origin_requires_filled_status`.
- [x] 1.3 RED same file `::test_venue_origin_requires_closes_allocation_id`.
- [x] 1.4 GREEN: `ExecutionOrigin` StrEnum + 2 new `__post_init__` invariants in `execution/domain/execution_attempt.py`; `origin` REQUIRED (no Python default).
- [x] 1.5 GREEN: pass `origin=SYSTEM` at every construction site — `place_order.py:107-125`, `close_position.py:140-171`, `infrastructure/repository.py` (`insert`/`_to_domain`), every test fixture constructing `ExecutionAttempt` directly.
- [x] 1.6 RED `tests/migrations/test_0022_execution_attempt_origin.py::test_upgrade_backfills_system_default`, `::test_downgrade_refuses_while_venue_rows_exist_naming_ids`, `::test_downgrade_succeeds_with_zero_venue_rows`.
- [x] 1.7 GREEN: `migrations/versions/0022_execution_attempt_origin.py` — `ADD COLUMN ... DEFAULT 'SYSTEM'`, CHECK; downgrade refuses, counts+ids, **no `-x` force flag** (deliberate, unlike 0021).
Gate: `ruff check .`, `mypy src`, `pytest`.

## Unit 2a — live probe (250–350 lines)

- [ ] 2.1 Write `scripts/check_venue_fill_windows.py`, GET-only, both venues, reusing `probe_credentials.announce`/`vault_credentials` (prints which key it runs as). Answers all six items from design decision 10.
- [ ] 2.2 RUN it on the worker's host; record output — the ONLY source for unit 5's five config defaults. Do not fix `reconciliation_booking_prepare_interval_seconds`, `..._window_pad_seconds`, `..._max_span_seconds`, `..._page_limit`, `..._max_pages` before this runs.
- [ ] 2.3 Light unit tests only for pure helpers (bisection, arg parsing) if any exist.
Gate: `ruff check .`, `mypy src`, `pytest`.

## Unit 2b — venue fill-window fetch (650–850 lines, AT RISK)

- [ ] 2b.1 **[Blocker c]** RED `tests/reconciliation/application/test_ports.py::test_venue_fill_carries_side_field_fill_does_not`.
- [ ] 2b.2 GREEN: `VenueFill`, `VenueFillReadError`, `VenueFillReaderPort`, `VenueFillReaderRegistryPort` in `reconciliation/application/ports.py`.
- [ ] 2b.3 RED+GREEN Bybit: `tests/reconciliation/infrastructure/test_bybit_venue_fill_reader.py` (`httpx.MockTransport`) — pagination via `nextPageCursor`, `max_pages` bound RAISES (never truncates silently), tolerant `_parse_window_execution` vs untouched strict parser. **Spelling**: fixture returns `STXUSDT`, test calls `fills_in_window(..., symbol="STXUSDT.P")` — assert contract-marker stripped before the venue call.
- [ ] 2b.4 GREEN: `BybitReadOnlyClient.fills_in_window` + `BybitVenueFillReader`, VAULT credential.
- [ ] 2b.5 RED+GREEN Binance: `tests/reconciliation/infrastructure/test_binance_venue_fill_reader.py` — full-page `startTime` advance + de-dup by `exchange_fill_id`; provisional on 2a's `fromId`+range finding. **Spelling**: fixture returns `STXUSDT_PERP`, test queries `"STXUSDT.P"`.
- [ ] 2b.6 GREEN: `BinanceReadOnlyClient.fills_in_window` + `BinanceVenueFillReader`, `.env` read-only key.
- [ ] 2b.7 RED+GREEN: `VenueFillReaderRegistry` — unserved pool raises, not swallowed.
Gate: `ruff check .`, `mypy src`, `pytest`.
**If it overruns 850: split at the venue boundary** — commit `2b-bybit` (DTO+port+registry+Bybit, ~450) then `2b-binance` (Binance fetch+reader, ~350) as two commits.

## Unit 3a — `booking_proposals` schema (450–550 lines)

- [ ] 3a.1 RED `tests/migrations/test_0023_booking_proposals.py` — every column, CHECKs (PENDING/decided_at, REJECTED-needs-reason, APPROVED-only execution_attempt_id, `kind` restricted to the two bookable kinds), `ux_booking_proposals_pending_per_discrepancy`, both other indexes, downgrade DROPs unconditionally (unlike 0022).
- [ ] 3a.2 GREEN: `migrations/versions/0023_booking_proposals.py`.
- [ ] 3a.3 GREEN: `BookingProposalRow` ORM in `reconciliation/infrastructure/models.py`.
Gate: `ruff check .`, `mypy src`, `pytest` (real Postgres).

## Unit 3b — proposal repository (500–600 lines)

- [ ] 3b.1 RED `tests/reconciliation/infrastructure/test_booking_proposal_repository_integration.py` — 6 methods incl. `get_for_update`, `mark_state`, rejected-suppression lookup, and the FOR UPDATE CAS racing two concurrent updates (second sees non-PENDING, writes nothing).
- [ ] 3b.2 GREEN: `SqlAlchemyBookingProposalRepository`, `BookingProposalRepositoryPort`, DTOs.
Gate: `ruff check .`, `mypy src`, `pytest` (real Postgres).

## Unit 4a — booking domain + small ports (400–500 lines)

- [ ] 4a.1 RED `tests/reconciliation/domain/test_booking.py::test_match_fills_sum_equals_delta`, `::test_match_fills_refuses_mixed_sides`, `::test_match_fills_refuses_zero_unrecorded`, `::test_match_fills_refuses_nonpositive_quantity`, `::test_canonical_fill_ordering_len_then_id_tiebreak_binance_integer_ids`, `::test_canonical_fill_ordering_len_then_id_tiebreak_bybit_string_ids`, `::test_client_order_id_uses_venue_order_id`, `::test_client_order_id_falls_back_to_earliest_fill_id_when_no_order_id`.
- [ ] 4a.2 GREEN: `domain/booking.py` — `BookingState`, `ProposedFill`, `match_fills()`, `BOOKABLE_KINDS`, `vnu:` id builder. Pure `Decimal`, no `market_key` import.
- [ ] 4a.3 RED+GREEN: `RecordedFillIdsPort`/`ReadRecordedFillIds` (sibling of `ReadSymbolPositions`), `AllocationOwnerPort`, `InFlightClosePort` (wraps existing `submitted_for_strategy_symbol`).
Gate: `ruff check .`, `mypy src`, `pytest`.

## Unit 4b — `PrepareBooking` use case (450–550 lines)

- [ ] 4b.1 RED `tests/reconciliation/application/test_prepare_booking.py::test_ambiguous_partial_reduce_and_no_matching_allocation_never_proposed` — money-critical: the two unbookable verdicts.
- [ ] 4b.2 RED `::test_prepare_writes_no_ledger_or_execution_rows` — money-critical: nothing reaches the ledger without approval.
- [ ] 4b.3 RED `::test_at_most_one_pending_proposal_per_discrepancy`, `::test_rejection_suppresses_identical_observation`, `::test_moved_observation_gets_fresh_proposal_after_rejection`, `::test_dry_run_hard_skip_no_fetch_no_proposal`.
- [ ] 4b.4 GREEN: `PrepareBooking` use case, all fakes. **Spelling**: fake `VenueFillReaderPort` returns `"STXUSDT_PERP"`, discrepancy fixture stores `"STXUSDT.P"`; assert the proposal's frozen `symbol` is the market key.
Gate: `ruff check .`, `mypy src`, `pytest`.

## Unit 5 — prepare wiring (600–800 lines, AT RISK — last change's overrun landed here)

- [ ] 5.1 GREEN (no `main.py` yet): 5 config constants from 2a's measured output, not guessed.
- [ ] 5.2 RED+GREEN `tests/reconciliation/application/test_booking_prepare_handler.py` — `JobKind.RECONCILIATION_PREPARE_BOOKING`, `BookingPrepareHandler` with its OWN `_SkipAnnouncement` (never shared with the scan handler's).
- [ ] 5.3 RED+GREEN: `main.py` wiring, `RECURRING_KINDS`, watchdog recurring set.
- [ ] 5.4 RED `tests/reconciliation/application/test_booking_prepare_integration.py::test_end_to_end_scan_to_prepared_proposal` — real DB, fake venue reader. **Spelling**: ledger fixture `"STXUSDT.P"`, fake venue reader `"STXUSDT"`.
Gate: `ruff check .`, `mypy src`, `pytest`.
**If it overruns 800: split at the `main.py` boundary** — commit `5a` (constants+JobKind+handler+unit tests, no `main.py`, ~350) then `5b` (`main.py` wiring, `RECURRING_KINDS`, watchdog, end-to-end integration test, ~350–450) — mirrors open-position-safely's own S5a/S5b split.

## Unit 6a — `ApproveBooking` (650–750 lines, needs 1 + 3b)

- [ ] 6a.1 RED `tests/reconciliation/application/test_approve_booking_integration.py::test_stale_snapshot_refused_marks_superseded` — parametrized across freshness branches (a)-(h). Money-critical.
- [ ] 6a.2 RED `::test_replayed_approval_writes_nothing_further_marks_superseded` — money-critical: approve twice, assert exactly 1 attempt + N ledger rows total; second call SUPERSEDED, zero writes.
- [ ] 6a.3 RED `::test_client_order_id_collision_treated_as_expected_superseded` and `::test_ux_ledger_exchange_fill_collision_treated_as_expected_superseded` — both identified by CONSTRAINT NAME (imports Task 1.1's constant), never message text; assert an unrelated FK/CHECK violation still propagates.
- [ ] 6a.4 RED `::test_concurrent_double_approval_second_sees_non_pending`.
- [ ] 6a.5 RED `::test_dry_run_refuses_at_use_case_level`.
- [ ] 6a.6 GREEN: `ApproveBooking`; `BookingWritePort`/`SqlAlchemyBookingWriter` owning the `session.begin_nested()` SAVEPOINT + the two named-constraint `IntegrityError` translations (infrastructure only).
Gate: `ruff check .`, `mypy src`, `pytest` (real Postgres).

## Unit 6b — `RejectBooking` + expiry (450–550 lines, needs 6a)

- [ ] 6b.1 RED `tests/reconciliation/application/test_reject_booking.py::test_reject_writes_zero_rows_leaves_discrepancy_open_confirmed` — money-critical.
- [ ] 6b.2 RED `::test_reject_without_reason_refused`.
- [ ] 6b.3 RED `tests/reconciliation/application/test_expire_booking_proposals.py::test_pending_past_24h_expires_and_is_reproposable` — money-critical.
- [ ] 6b.4 RED `::test_approve_refuses_expired_but_unswept_proposal`.
- [ ] 6b.5 GREEN: `RejectBooking`, `ExpireBookingProposals` (runs inside the prepare handler before the sweep).
Gate: `ruff check .`, `mypy src`, `pytest`.

## Unit 7 — admin endpoints (450–600 lines, needs 6b)

- [ ] 7.1 RED `tests/reconciliation/infrastructure/test_router.py::test_list_pending_requires_bearer_token`, `::test_approve_requires_bearer_token`, `::test_reject_requires_bearer_token`.
- [ ] 7.2 RED `::test_approve_returns_503_under_dry_run`, `::test_reject_returns_503_under_dry_run` (never 403).
- [ ] 7.3 RED `::test_approve_unknown_id_404`, `::test_approve_not_pending_409`, `::test_reject_empty_reason_422`. **Spelling**: list endpoint queried with `?symbol=stxusdt.p`, fixture stores `STXUSDT.P`; assert normalization.
- [ ] 7.4 GREEN: the 3 routes on the existing `reconciliation/infrastructure/router.py`.
Gate: `ruff check .`, `mypy src`, `pytest` (real Postgres, `TestClient`).

## Unit 8 — frontend client + auth (500–650 lines, needs 7's contract only)

- [ ] 8.1 RED (Vitest) `shared/auth/token-store.test.ts` — persists to `localStorage` key `sm.admin_token`; grep-asserts no `import.meta.env` reference to the token.
- [ ] 8.2 GREEN: `shared/auth/token-store.ts`, `TokenGate`.
- [ ] 8.3 RED `shared/api/client.test.ts` — `apiFetch` sends `Authorization: Bearer`; any 401 clears the store and re-renders `TokenGate`.
- [ ] 8.4 GREEN: `shared/api/client.ts` (reuses `shared/api/config.ts`'s existing `VITE_API_BASE_URL` pattern).
i18n: no new user-facing copy in this unit — verify none slipped in.
Gate: `npm run lint`, `npm test`.

## Unit 9a — bookings list view (500–600 lines, needs 8)

- [ ] 9a.1 RED (Vitest) `features/bookings/BookingsListView.test.tsx` — pending list, empty state, error path.
- [ ] 9a.2 GREEN: `BookingsListView.tsx`, `BookingCard.tsx`, nav rework (`App.tsx` `active` becomes `useState` seeded from `location.hash`; `NAV_ITEMS` gains `bookings`; no router library added).
i18n: every string added to `shared/i18n/en.json` AND `es.json`; RED test asserting both locales carry the new keys before the copy lands. No hardcoded display text.
Tailwind: no hex colours, no `var()` in `className` — palette tokens only from `index.css`'s `@theme`.
Gate: `npm run lint`, `npm test`.

## Unit 9b — confirm + reject dialogs (500–600 lines, needs 9a)

- [ ] 9b.1 RED `features/bookings/ConfirmBookingDialog.test.tsx` — renders every row from the proposal's own frozen snapshot (never recomputed client-side); `usd_rate` deliberately ABSENT with its i18n'd explanatory line; approve mutation callable ONLY from this dialog's confirm button.
- [ ] 9b.2 RED `features/bookings/RejectBookingDialog.test.tsx` — submit refused on empty reason.
- [ ] 9b.3 GREEN: both dialogs + mutations (`vi.stubGlobal("fetch")`, no MSW).
i18n: dialog copy in EN/ES both; RED test before GREEN. No hardcoded display text.
Tailwind: no hex colours, no `var()` in `className`.
Gate: `npm run lint`, `npm test`.

## What can be deferred to a later session without blocking others

Dependencies only point forward (1 ⟂ 2a→2b; 3a→3b; 4a needs 2b+3b; 4b needs 4a; 5 needs 4b;
6a needs 1+3b; 6b needs 6a; 7 needs 6b; 8 needs 7's contract only; 9a→9b need 8), so ANY
prefix of the ordered 14 units is a safe pause point:

1. **Foundation (1, 2a, 2b, 3a, 3b)** — no route, no job, no reachable behavior; each commit independently revertable.
2. **Domain/use-case (4a, 4b)** — pure application logic, still unreachable, no job registered.
3. **Unit 5** is the FIRST unit that makes anything live, but `BookingPrepareHandler`'s DRY_RUN hard-skip means it does nothing under the current default config. Safe to pause after 5.
4. **Approve/reject (6a, 6b)** — still unreachable without 7's routes.
5. **Unit 7** exposes the bearer-gated, DRY_RUN-503'd admin API — structurally safe to pause here, but owner decision 2 makes the FRONTEND the intended surface, so this is not the recommended long-term stopping point in practice.
6. **Units 8, 9a, 9b** — the frontend slice, the natural next-session boundary; 8 needs only 7's already-frozen contract.

**Recommended session split**: Session 1 = 1+2a+2b+3a+3b+4a+4b+5 (backend foundation through wiring, inert under DRY_RUN). Session 2 = 6a+6b+7 (backend becomes live and API-reachable — the first point a real approval could write to the ledger). Session 3 = 8+9a+9b (frontend, the actual approval surface per owner decision 2). This differs slightly from design's own PR-chain grouping (which puts 5 with 3b/4a/4b): 5 moves to session 1's tail here because it is inert, and 6a/6b are the first units carrying real ledger-write risk.
