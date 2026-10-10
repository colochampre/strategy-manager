# Tasks: Operator panel

SDD phase TASKS, 2026-09-24. Follows proposal.md, design.md (incl. the 2026-09-25
orchestrator correction on F11), owner-decisions.md (23 decisions, binding, none
reopened), and specs/{exchange-credentials,strategy-lifecycle,performance-reporting,
admin-api,panel-serving,operator-panel,capital-allocation}/spec.md. `delivery_strategy:
auto-chain`, `chain_strategy: sequential PRs to main` (owner convention #243: branch,
PR, merge, next branch from the updated `main`; never stacked). One work-unit commit
per unit, `git commit -F` (never `-m` with embedded newlines typed inline).

Style follows `openspec/changes/archive/2026-09-24-book-venue-closes/tasks.md`: units in
order, each behavioural task opens with its named failing test, gates and harness stated
per unit, honest forecasts that assume the ~2x bias that change measured (concentrated in
`main.py` wiring and integration tests — design's own forecast already applies it).

## Cross-cutting rules (apply to every unit below)

- **Symbol spelling.** Every cross-boundary test (allowlist matching, seeding, per-pair
  stats, webhook-message parsing, market_key relocation) MUST use a DIFFERENT spelling on
  each side of the boundary: `STXUSDT.P` / `STXUSDT` / `STXUSDT_PERP`. A test that uses the
  same spelling on both sides proves nothing about normalization.
- **Money, quantities and ratios are JSON strings** on every response (pydantic v2
  `Decimal` serialization, existing `_amount()` convention). Never a JSON number.
- **Rule 7**: no response, view, or read model sums figures across two different
  `(exchange, venue, settlement_currency)` pools, including two pools on one exchange.
- **No AI attribution** in any commit message. Conventional commits only.
- **`git commit -F <file>`**, never an inline `-m` with embedded formatting — every commit
  message is drafted in a scratch file first.
- **Never PowerShell `Get-Content`/`Set-Content` on a source file.** Use the `Read`/`Edit`
  tools or POSIX-style tools; PowerShell text cmdlets have re-encoded files before.
- **Never print a credential, a DSN, or a secret** in a log line, a test failure message,
  or a probe/script's stdout — every probe and diagnostic script prints last-4 only.
- **Per unit, ask**: "what fails here without a log line?" — a refusal with no WARNING/ERROR
  is a debugging dead end six months from now. Every refusal path in this change carries one.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | Bottom-up 16,550–23,300 per design (revised 2026-09-25), **plus PR 8's split overhead is already inside that range** — treat 23,300 as a floor, not a ceiling: book-venue-closes forecast 6,700–8,400 and landed ~10,000 (~1.4–1.5x), concentrated in `main.py` wiring and integration units; open-position-safely's bias was ~2x. **Plan for 23,000–32,000 actual.** |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | 14 sequential PRs to `main` (PR 1 → PR 14 below); PR 8 (design's PR 8) is split into **PR 8a** and **PR 8b** because 2,900–4,050 lines in one PR is roughly 2x the next-largest PR (PR 4/5/6) even at each range's low end |
| Delivery strategy | auto-chain |
| Chain strategy | sequential PRs to main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

(`stacked-to-main` is the closest fit in the guard's four-value vocabulary for "sequential
PRs to `main`, never stacked as in parent/child branches" — each PR here targets `main`
directly, in order, exactly like `stacked-to-main`'s "each PR merges to main in order" half,
with the parent/child branch-basing half of that term simply not used. `auto-chain` already
resolves `Decision needed before apply` to `No` per the skill's own mapping; the owner's
probe (PR 1) and deploy gates below remain operational steps, not open decisions.)

**Added 2026-10-02 (unit 9v, decisions 40 and 41).** Validating allowed pairs against the
venue catalogue adds **2,600–3,800** authored lines on top of the table above, in six
sequential PRs to `main` after PR 12a-2: **12v-0** probe (200–300), **12v-1** public venue
sources (500–700), **12v-2** catalogue port and read endpoint (550–800), **12v-3** save
refusals (500–750), **12v-4** selector (450–650), **12v-5** dialog (400–600). The backend
alone (12v-1 to 12v-3, 1,550–2,250) is about four times the review budget as one PR, which
is why it is three. The guard lines above do not change: `Decision needed before apply: No`
(design addendum § L lists three owner questions; none blocks 12v-0 or 12v-1),
`Chained PRs recommended: Yes`, `400-line budget risk: High`.

**Added 2026-10-02 (unit 9x, decision 42).** Deleting a strategy that has no history adds
**2,000–2,950** authored lines, in five sequential PRs to `main`: **12x-1** webhook refusal for
an unregistered strategy (300–450), **12x-2** history read (450–650), **12x-3** `DeleteStrategy`
and its lock-hold tests (550–800), **12x-4** endpoint (300–450), **12x-5** panel control
(400–600). A sixth, **12x-6** migration 0028 (400–600), is built only if the owner answers
design addendum 9x § L, Q1 with "enablement events do not block"; with it the total is
2,400–3,550. As one PR the unit would be five to seven times the review budget. The guard lines
above do not change: `Decision needed before apply: No` (three owner questions are open; each
blocks only the tasks marked with it in PR 12x, and none blocks 12x-1 or 12x-2),
`Chained PRs recommended: Yes`, `400-line budget risk: High`.

**Added 2026-10-06 (unit 12f, decisions 44 and 48).** The detail page's follow-ups (the share of the pool
as a slider with its amount and warning, "Saved", two Copy buttons, the webhook's full URL, and the
WIN RATE column of By pair) are two sequential PRs to `main`, never stacked, split by deploy order and
not by size: **12f-1** backend (unit 12f.9) and **12f-2** panel (unit 12f.10). Information only, as
the owner holds a standing size exception: bottom-up, **12f-1 is 2,000–3,000** authored lines (the
design forecasts 1,000–1,500 and says tests run at about twice the production code; this section
counts the tests it lists, and the bias this change measured on every earlier unit is about 2x) and
**12f-2 is 4,500–6,500** (design: 2,800–4,100). No migration. The guard lines above do not change:
`Decision needed before apply: No` (every question of design addendum 12f § N is answered),
`Chained PRs recommended: Yes`, `400-line budget risk: High`. Nothing is split to fit a budget.

### Suggested Work Units (PR-level; see per-PR tables below for unit-level detail)

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|------|------|-----------|----------------------|-----------------|-------------------|
| 1a | Permission probe, GET-only | PR 1 | `cd backend && uv run pytest --tb=short backend/tests/scripts/test_check_key_permissions.py` | Owner runs the script on the VPS against real keys; the redaction unit test runs locally with no real credential | `backend/scripts/check_key_permissions.py`, a dev tool never imported by shipped code |
| 4a | `/api` move | PR 2 | `cd backend && uv run pytest --tb=short backend/tests/strategies/infrastructure/test_router_auth.py backend/tests/reconciliation/infrastructure/test_router.py` + `cd frontend && npm test -- client` | `httpx.AsyncClient` over the ASGI app | Prefix change only; revert restores `/strategies`, `/reconciliation` |
| 1b | Binance reads onto the vault | PR 3 | `cd backend && uv run pytest --tb=short backend/tests/main/test_booking_prepare_wiring.py` | Fakes + real vault (envelope decrypt), gated by PR 1's P4 | `main.py`'s five Binance factory call sites; revert restores `.env` reads while `.env` values are kept until proven |
| 2a+2d+2e | Lifecycle schema, enablement log, pairs/list endpoints | PR 4 | `cd backend && uv run pytest --tb=short backend/tests/migrations/test_0024_strategy_lifecycle.py backend/tests/strategies/` | Real PostgreSQL, migration up/down, seeding rehearsal | `migrations/versions/0024_*.py` + new strategies columns; downgrade refuses while OBSERVED events exist |
| 2b+2c | Allowlist/archived refusals, `ArchiveStrategy`, concurrency | PR 5 | `cd backend && uv run pytest --tb=short backend/tests/signals/application/test_process_signal.py backend/tests/strategies/application/test_archive_strategy_integration.py` | Real PostgreSQL, live concurrency test (advisory lock) | Pre-lock refusal methods + `ArchiveStrategy`; revert removes both, signals flow as before |
| 2f | Log lines on the five silent signal paths (decision 25) | PR 5 | `cd backend && uv run pytest --tb=short backend/tests/allocation/ backend/tests/execution/` | Fakes + caplog | Log lines only |
| 5b | Signal outcomes decided in signal.process, migration 0025 (decision 25) | PR 5b | `cd backend && uv run pytest --tb=short backend/tests/migrations/test_0025_signal_outcomes.py backend/tests/signals/` | Real PostgreSQL for the migration and atomicity tests | Migration 0025 (downgrade refuses while outcomes exist) + the outcome writes |
| 5c | Asynchronous signal outcomes: settle, continuation, close linkage, exhausted jobs | PR 5c | `cd backend && uv run pytest --tb=short backend/tests/execution/ backend/tests/signals/` | Real PostgreSQL | The writes only |
| 3a+3b+3c+3d | Pool capital at open, PnL, curve/drawdown/grid, stats | PR 6 | `cd backend && uv run pytest --tb=short backend/tests/allocation/ backend/tests/performance/` | Real PostgreSQL for 3a; pure for 3b–3d | `reservations.pool_total_at_open` (additive) + new `performance/` module; downgrade refuses while non-null values exist |
| 5-reads | Pools/performance/webhook-secret read endpoints | PR 7 | `cd backend && uv run pytest --tb=short backend/tests/accounts/infrastructure/test_pools_router.py backend/tests/performance/infrastructure/test_performance_router.py backend/tests/signals/infrastructure/test_webhook_secret_router.py` | `httpx.AsyncClient` over ASGI | New routers only; revert 404s the paths, no view depends on them yet |
| 6a+6b+6c | Key policy, inspectors, 0027, `SaveCredential`, `TradeCapabilityPort` | PR 8a | `cd backend && uv run pytest --tb=short backend/tests/accounts/` | `httpx.MockTransport` for inspectors, real vault for the migration, gated by PR 1's P1–P3 | Migration 0027 (refuses downgrade while any row is not the backfill shape) + new use case; revert leaves scripts working unchanged |
| 6d+6e | Pool auto-enable, `DeleteCredential`, exposure adapter | PR 8b | `cd backend && uv run pytest --tb=short backend/tests/accounts/application/test_delete_credential_integration.py` | Real PostgreSQL, concurrent delete-vs-allocate test (advisory lock) | `CapitalPoolWriterPort` + `DeleteCredential`; revert removes both, keys already stored remain valid |
| 4b | SPA serving, fallback, CSP, invariant 5 (dropped, K5) | PR 9 | `cd backend && uv run pytest --tb=short backend/tests/shared/infrastructure/test_spa.py` | `httpx.AsyncClient` over ASGI with a temp `dist` directory | `shared/infrastructure/spa.py` + `mount_panel()` call; revert removes the mount, `/api` untouched |
| 7-shell | Router, shell, exchange scope, bookings re-homed, theme swap | PR 10 | `cd frontend && npm test -- router AppShell exchange-store` | N/A — frontend-only, `vi.stubGlobal("fetch")` | New `app/router.tsx`, `shared/layout/*`; revert restores the hash-based nav |
| 8-overview | Overview: ledger line, chart, grid, decision rail | PR 11 | `cd frontend && npm test -- OverviewPage ReturnChart MonthlyGrid` | N/A — frontend-only, pure geometry unit tests | New `features/overview/*`; revert removes the route content, shell untouched |
| 9-strategies | Strategies list + detail + dialogs + webhook message | PR 12 | `cd frontend && npm test -- StrategiesPage StrategyDetailPage WebhookMessage` | N/A — frontend-only | New `features/strategies/*`; revert removes the route content |
| 10-settings | Settings: key card, form, delete flow | PR 13 | `cd frontend && npm test -- SettingsPage ExchangeKeyCard DeleteKeyDialog` | N/A — frontend-only | New `features/settings/*`; revert removes the route content |
| 9v0 | Probe P7: both public catalogues answer unsigned from the VPS (decision 41) | PR 12v-0 | `cd backend && uv run pytest --tb=short backend/tests/scripts/test_check_public_catalogue.py` | Owner runs the script on the VPS; the unit test uses `httpx.MockTransport` and no credential | `backend/scripts/check_public_catalogue.py`, a dev tool imported by nothing |
| 9va | Credential-free transports and public catalogue sources, Bybit and Binance | PR 12v-1 | `cd backend && uv run pytest --tb=short backend/tests/shared/infrastructure/bybit backend/tests/shared/infrastructure/binance` | `httpx.MockTransport`, gated by P7 | New classes nothing calls yet, plus two behaviour-preserving extractions in the venue transports |
| 9vb | `PairCatalogPort`, `VenuePairCatalog` (cache), `GET /api/pools/{exchange}/{venue}/{ccy}/available-pairs` | PR 12v-2 | `cd backend && uv run pytest --tb=short backend/tests/strategies` | Fakes and `httpx.MockTransport`; real PostgreSQL for the router | One GET route and its adapter; revert 404s the path, no save depends on it yet |
| 9vc | Unlisted-pair refusals in `RegisterStrategy` and `ReplaceAllowedPairs`, venue call before the row lock | PR 12v-3 | `cd backend && uv run pytest --tb=short backend/tests/strategies` | Real PostgreSQL, lock-hold harness (row lock) | Two use cases and their HTTP mapping; revert restores normalize-only saves, stored pairs stay valid |
| 9vd | `ApiError` structured detail, `useAvailablePairs`, `PairSelector` (not mounted) | PR 12v-4 | `cd frontend && npm test -- client pairs PairSelector` | N/A — frontend-only, `vi.stubGlobal("fetch")` | New files and two added `ApiError` fields; nothing mounts the selector |
| 9ve | Selector in `NewStrategyDialog`, refusal texts, harness venue corrected | PR 12v-5 | `cd frontend && npm test -- NewStrategyDialog StrategiesPage` | N/A — frontend-only | One dialog; revert restores the textarea, the server still validates |
| 9xa | The webhook refuses an alert whose strategy is not registered: 422, one WARNING (decision 42) | PR 12x-1 | `cd backend && uv run pytest --tb=short backend/tests/signals/infrastructure/test_unknown_strategy_ingress.py backend/tests/signals/application/test_ingest_signal.py` | Real PostgreSQL migrated to `head` (the foreign key exists only there) | One caught error and its HTTP mapping; revert restores the unhandled 500 |
| 9xb | `StrategyHistoryPort`, the six counts, the exhaustiveness guard | PR 12x-2 | `cd backend && uv run pytest --tb=short backend/tests/strategies` | Real PostgreSQL: ORM schema for the counts, `head` for the guard | Read methods and one adapter nothing calls |
| 9xc | `DeleteStrategy`, `repository.delete`, lock-hold concurrency tests | PR 12x-3 | `cd backend && uv run pytest --tb=short backend/tests/strategies` | Real PostgreSQL migrated to `head`, lock-hold harness (advisory lock and row lock) | A use case nothing routes to |
| 9xd | `DELETE /api/strategies/{id}` and its refusals | PR 12x-4 | `cd backend && uv run pytest --tb=short backend/tests/strategies/infrastructure/test_router.py backend/tests/strategies/infrastructure/test_router_auth.py` | `httpx.AsyncClient` over ASGI, real PostgreSQL | One route; revert answers 405 |
| 9xe | `useDeleteStrategy`, `DeleteStrategyControl`, `DeleteStrategyDialog` (not mounted) | PR 12x-5 | `cd frontend && npm test -- strategies DeleteStrategy` | N/A — frontend-only, `vi.stubGlobal("fetch")` | New files; nothing mounts them until task 9d.6 |
| 9xf | Migration 0028: enablement events are deleted with their strategy (ONLY if Q1 says so) | PR 12x-6 | `cd backend && uv run pytest --tb=short backend/tests/migrations/test_0028_enablement_events_cascade.py backend/tests/strategies` | Real PostgreSQL, migration up and down, VPS rehearsal | Migration 0028's downgrade; the use-case change reverts alone |
| 9p.4 | A strategy's operations: figures, rehearsal rows on request, fill-price classification, `GET .../trades/{allocation_id}/fills` (decision 43) | PR 12e-1 | `cd backend && uv run pytest --tb=short backend/tests/performance backend/tests/shared/infrastructure/test_wire_price.py backend/tests/signals/infrastructure/test_webhook_secret_router.py` | Real PostgreSQL on the ORM schema; `head` schema for the CHECK and index tests only; no migration | Two reverts: the figures and rehearsal split restore the nine-field row; the fills read removes one route |
| 9p.5 | The operations table, dry-run marks, detail dialog and fills table (decision 43) | PR 12e-2 | `cd frontend && npm test -- TradesTable TradeDetailDialog OperationFillsTable format performance` | N/A — frontend-only, `vi.stubGlobal("fetch")`; the owner's review by eye with `vite.fixture.config.ts` | A revert restores the seven-column table, which still works against the new API |
| 9q | The simulated exchange fills at the alert's price, charges the venue's taker fee, refuses an unusable price and a market not quoted in USDT; an exchange with no rate is not served (decision 45) | PR 12g | `cd backend && uv run pytest --tb=short backend/tests/execution backend/tests/signals backend/tests/test_main_simulated_exchanges.py` | Real PostgreSQL on the ORM schema through the production composition root (`main.build_worker_runner`, `run_once`); `head` schema for one constraint test; `httpx.MockTransport` with the frozen clock for the two registered real adapters; no credential, no network | One revert of the whole PR (a partial revert would leave opens priced and closes refused). It restores the fixed price of 1 and the fee of 0 for NEW fills; fills already written keep their alert price and fee. No migration, no data touched |
| 12f.9 | The detail page's backend follow-ups: wins and win rate in `by_pair`, the webhook origin (setting, parser, route, startup line), the INFO line of a changed share and the share in plain notation, the share-preview route (decisions 44 and 48) | PR 12f-1 | `cd backend && uv run pytest --tb=short backend/tests/performance backend/tests/signals/infrastructure/test_webhook_origin_router.py backend/tests/signals/infrastructure/test_webhook_origin_check.py backend/tests/strategies backend/tests/allocation/domain/test_share_preview.py backend/tests/accounts/infrastructure/test_pool_sizing.py backend/tests/signals/infrastructure/test_webhook_secret_router.py` | Real PostgreSQL on the ORM schema for the adapter, the routes and the integration tests; no `head` schema is needed (no constraint or index decides an outcome); `httpx.AsyncClient` over ASGI; the lifespan for the startup lines; no credential, no network, no migration | Two independent reverts: the wins (12f.9.1 and 12f.9.2) and everything else; each removes new fields or new routes only, and their paths then answer 404. No data is touched |
| 12f.10 | The detail page's panel follow-ups: the share slider with its field, amount, warning and two information buttons, "Saved", two Copy buttons, the full webhook URL, the Win rate column (decisions 44 and 48) | PR 12f-2 | `cd frontend && npm test -- share PoolShareEditor ShareSlider ShareAmount InfoDisclosure InlineStatus clipboard webhook-url webhook-origin PairStatsTable WebhookMessage AllowedPairsEditor StrategyDetailPage theme format` | N/A — frontend-only, `vi.stubGlobal("fetch")` and a stubbed `navigator.clipboard`; the owner's review by eye with `vite.fixture.config.ts`, and the built bundle served by FastAPI with `PANEL_DIST_DIR` set for the CSP | A revert restores the page as it is today, which works against the new API |

## Delivery log

Updated after every merge and deploy. With this and `git log`, the state can be resumed from
any machine.

**Production now** (2026-10-06): `main` at `c7893ab`, alembic `0028`, `DRY_RUN=true`, the
frontend is not served. The rest of this paragraph was last confirmed on 2026-10-02. Enabled pools: `bybit/usdt-m/USDT` and `binance/usdt-m/USDT`. The vault
holds one key each for binance, bybit and pionex. Three strategies are enabled, each with one
allowed pair: SFP → `SFPUSDT`, AAVE → `AAVEUSDT`, STX → `STXUSDT`.

| Plan PR | GitHub | Merge commit | Migration | Deployed | Notes |
|---|---|---|---|---|---|
| PR 1 | #9 | `a09b5eb` | — | 2026-09-25 | Probe script. The owner ran it on the VPS; results in "PR 1 — Probe results". |
| PR 2 | #10 | `897514d` | — | 2026-09-25 | Pull, restart the API. |
| PR 3 | #11 | `733064b` | — | 2026-09-25 | Restart both. Then `BYBIT_/BINANCE_API_KEY/SECRET` were removed from `backend/.env`. |
| PR 4 | #12 | `fbde874` | 0024 | 2026-09-28 | Rehearsed on `sm_rehearsal_0024`. Backup `/root/sm_pre0024_20260928_1552.dump`. The owner confirmed the seeded pairs. |
| PR 5 | #13 | `17681ef` | — | 2026-09-28 | Restart both. The allowed-pairs gate is live. |
| PR 5b | #14 | `d6833f9` | 0025 | 2026-09-29 | Tasks 5b.1–5b.5. Rehearsed on `sm_rehearsal_0025`, including the downgrade refusal once an outcome exists. Backup `/root/sm_pre0025_20260929_0219.dump`. Restart both. The 17 existing signals stay `ACCEPTED`. |
| PR 5b2 | #15 | `5978ac8` | — | 2026-09-29 | Tasks 5b.6–5b.11 (5b.11 is decision 27). Pull, restart both. |
| PR 5c | #16 | `d9fb55d` | — | 2026-09-29 | Tasks 5c.1–5c.5. Pull, restart both. |
| PR 5c2 | #17 | `22a94b0` | — | 2026-09-29 | Tasks 5c.6–5c.7. Pull, restart both. Decision 25 is fully delivered. |
| PR 6a | #18 | `4041a3a` | 0026 | 2026-09-29 | Unit 3a. Rehearsed on `sm_rehearsal_0026`, including the downgrade refusal once a value exists. Backup `/root/sm_pre0026_20260929_1534.dump` (an earlier `..._1532.dump` is from a run that aborted on the HEAD check before touching anything). Restart both. The 2 existing reservations stay NULL; only new ones record `pool_total_at_open`. |
| PR 6b | #19 | `50a68db` | — | 2026-09-29 | Units 3b + 3c, plus decision 28 recorded. PR 6 gate: production holds **4** `fake-fill-%` ledger rows (owner ran the count, 2026-09-29); they are excluded from the curve and counted as rehearsal fills. Pull, restart both. |
| PR 6c | #20 | `849ad1a` | — | 2026-09-29 | Unit 3d. Pull, restart both. The original PR 6 is complete. |
| PR 6d | #21 | `a969e40` | — | 2026-09-29 | Decision 28. The guard ran against the production ledger before the restart: clean for `DRY_RUN=true`, and a `DRY_RUN=false` start would also be allowed. Restart both. The worker unit has `Restart=always`, `RestartSec=5` and no `StartLimit*`, so a refused start would loop and alert every few seconds. |
| PR 6e | #22 | `b0cbda1` | — | 2026-09-29 | Decision 29. Restart both. Drop-in `/etc/systemd/system/strategy-worker.service.d/startup-refusal.conf` installed (`RestartPreventExitStatus=78`), systemd reloaded, and the worker stayed active. The API unit also runs `Restart=always`, `RestartSec=5`, with no drop-in: its lifespan refusals would loop silently (see decision 29's note on the API). |
| PR 7a | #23 | `94ca953` | — | 2026-09-29 | Tasks 7.1, 7.2 and the pools/performance half of 7.4. Pull, restart both; the API and the worker came up active. |
| PR 7b | #24 | `1eab7a9` | — | 2026-09-29 | Task 7.3 and the webhook-secret half of 7.4 (decision 23). Independent security verification: no blocker; follow-ups 7f.1–7f.5. Pull, restart both; the API and the worker came up active. The read endpoints are complete. |
| PR 8a-0 | #25 | `5deb0fe` | — | 2026-09-29 | Probe P6 (task 8a.0a). Pull only, no restart. The owner ran the probe: a read-only Binance key reads every fapi endpoint, and `canTrade`/`canWithdraw` are account-level. See 8a.0a's results and decision 30. |
| PR 8a-1 | #26 | `e9307c7` | 0027 | 2026-09-29 | Unit 6a. Rehearsed on `sm_rehearsal_0027`, including the downgrade refusal once a fact is recorded. Backup `/root/sm_pre0027_20260929_2210.dump`. Restart both; the vault self-test opened all 3 keys through the new columns. All 4 credential rows (binance, bybit, pionex active, plus one inactive pionex) are `trade_capable`, both sources `UNRECORDED`. S2 (httpx INFO logs) is a follow-up for 8a-3. |
| PR 8a-2 | #27 | `ab415ad` | — | 2026-09-30 | `SaveCredential` and the script fold (6b.1, 6b.4, 6b.7). Pull, restart both. The owner re-saved the Binance trade key (`***3h2M`) with both confirmations. It is now `OWNER_CONFIRMED` for trade capability and withdraw check, validated 2026-09-29T22:40:29Z. **Defect found doing it:** `credential_cli.py` read the API key with `input()`, so the full key was printed on the terminal and copied into a chat. The secret was not exposed. The owner is advised to rotate that key once the fix is deployed. |
| Fix | #28 | `6293f58` | — | 2026-09-30 | No-echo key prompt, shipped alone. Pull only. The owner then **rotated the Binance key**. The new key has Enable Futures, has withdrawals disabled, and is IP-bound to the VPS; it was saved with both confirmations through the fixed script. Both services were restarted, and the vault self-test opened all 3 keys. The exposed key `***3h2M` is superseded in the vault and is to be deleted on Binance. |
| PR 8a-3 | #29 | `49b494e` | — | 2026-09-30 | The HTTP surface (6b.2, 6b.3, 6b.5, 6b.6, and S2). Risk **high**: the first API route that receives secrets. Independent security verification: no blocker; W1 (`no-store`), W2 (key and secret limited to printable ASCII) and S1 (`max_length` 256) fixed before the PR; follow-ups 8f.1–8f.3. Pull (as `strategy`, see below), restart both; the API and the worker came up active. **Found doing it:** `git pull` as root fails with "detected dubious ownership", because the checkout `/opt/strategy-manager/app` and both services belong to the `strategy` user. The pull now runs as that user, and root's global git config is left alone (CLAUDE.md, Delivery). |
| PR 8a-4 | #30 | `5ed16f5` | — | 2026-09-30 | Unit 6c (tasks 6c.1-6c.8): `TradeCapabilityPort`, `VaultTradeCapabilityAdapter`, `DryRunTradeCapability` and the up-front refusal of a live open on a read-only or keyless exchange (decisions 18 and 20). Risk **medium**: it can only refuse an open, never place one; the dangerous direction (`DryRunTradeCapability` wired live) is pinned by the wiring test. Pull as `strategy`, restart both; the API and the worker came up active. Production runs `DRY_RUN=true`, so nothing is refused yet. PR 8a is complete. |
| PR 8b-1 | #31 | `c893e83` | — | 2026-09-30 | Unit 6d (tasks 6d.1-6d.7): `KNOWN_FUTURES_POOLS`, `CapitalPoolWriterPort`, `SqlAlchemyCapitalPoolWriter`, and `SaveCredential` enabling the exchange's one futures pool (`usdt-m/USDT` for Bybit and Binance) in the same transaction as the credential write (decision 21). Risk **medium**: it can only switch a pool on, never place an order, and production already has both rows enabled (0017/0018), so today a save is a no-op on them; a lost race, a refusal or a venue failure leaves the pool untouched (proved on real PostgreSQL). No migration. Pulled as `strategy`, restarted both; the API and the worker came up active. PR 8b-2 (unit 6e, `DeleteCredential`) follows. |
| PR 8b-2 | #32 | `49b2823` | — | 2026-09-30 | Unit 6e (tasks 6e.1-6e.11): `DELETE /api/credentials/{exchange}`, `DeleteCredential`, `PoolExposurePort`/`PoolExposureAdapter`, `SqlAlchemyCredentialRevoker` (decision 22; decision 31 for an exchange without a known pool). Pulled as `strategy`, restarted both; the API and the worker came up active. PR 8 (backend) is complete. Risk **high**: a new write route that deletes keys and disables a pool, plus a concurrency boundary with allocation (proved on real PostgreSQL in both orderings; lock order is pool advisory lock first, then the row lock, which corrects the task text). No migration. Independent verification (2026-09-30): no blocker. W1 (an allocation waiting on the pool lock while the delete disabled the pool could reserve capital on a keyless exchange) fixed in `6a4487e` (`POOL_DISABLED` skip, in-lock pool re-read through `PoolStatusPort`); follow-ups 8f.4-8f.5 open. |
| PR 9 | #33 | `baf4b50` | — | 2026-09-30 | Unit 4b (tasks 4b.1-4b.7): `mount_panel`, `Settings.panel_dist_dir`, the `index.html` refusal (invariant 5 was dropped, see the correction below). Risk **medium**. No migration. Pulled as `strategy`, restarted both; the API and the worker came up active. `PANEL_DIST_DIR` is left **UNSET**, so the mount stays off until the owner completes the "PR 9 deploy prerequisites" (DuckDNS, `cloudflared`, Cloudflare Access, a frontend build). CORS (7f.1) is not removed by this PR. |
| PR 10a | #34 | `2c1374c` | — | 2026-09-30 | Unit 7t-theme (7t.1-7t.3): direction-A `@theme`, class renames, self-hosted fonts, `recharts` removed. Risk **low**. No migration. Pulled as `strategy`, no restart (frontend only, not served while `PANEL_DIST_DIR` is unset). The owner reviewed it locally and approved the primary-button contrast (`text-ground` on `bg-gain`). They also reported that Bookings scrolls vertically with only the token-gate card; the cause is pre-existing (`TokenGate`'s `min-h-full` inside the padded `<main>`), and the fix is carried into PR 10b. |
| PR 10b | #35 | `65ab3bc` | — | 2026-09-30 | Unit 7-router (7r.1-7r.3): `react-router` 7.18.4, `AppRoutes`, `AppShell`/`TopBar`/`SideNav`/`BottomNav`, `DryRunBadge` on `GET /health` (always visible, decision 32), the vertical-overflow fix, and the Vite `/health` proxy. Risk **low** (frontend only). No migration. Pulled as `strategy`, no restart (frontend only, not served while `PANEL_DIST_DIR` is unset). The owner reviewed it locally: no page scroll at wide or narrow width, deep links survive a refresh, and the badge shows "Mode unknown" with the backend stopped. |
| PR 10c | #36 | `7b78b9a` | — | 2026-09-30 | Unit 7s-scope (7s.1-7s.3): the exchange store (`sm.exchange`), `ExchangeTabs` on the scoped routes, and the decision rail filtered by exchange. Risk **low** (frontend only). No migration. Pulled as `strategy`, no restart (frontend only, not served while `PANEL_DIST_DIR` is unset). The owner reviewed it locally (tabs, persistence, unscoped routes, narrow row, the pools-failure message). The tab key marks were deferred to PR 13 (10c.4), and the owner polish is 7p.1-7p.2. **PR 10 is complete.** |
| PR 11a | #37 | `299c150` | — | 2026-09-30 | Units 8c-geometry and 8r-chart (8c.1-8c.2, 8r.1-8r.2): the pure waterline geometry in `shared/charts/scale.ts` and the `ReturnChart` inline SVG. Risk **low** (frontend only, nothing mounts the chart yet). No migration. Pulled as `strategy`, no restart (frontend only, not served while `PANEL_DIST_DIR` is unset). The visual review waits for PR 11c, which mounts the chart. |
| PR 11b | #38 | `ed30e64` | — | 2026-09-30 | Unit 8g-grid (8g.1-8g.4): `PoolEyebrow`, `RangeSelector`, `LedgerLine`, `MonthlyGrid`, `MonthlySummary` and the display helpers, all presentational with typed props. Risk **low** (frontend only, nothing mounts the components yet). No migration. Pulled as `strategy`, no restart (frontend only, not served while `PANEL_DIST_DIR` is unset). The visual review waits for PR 11c, which mounts them. |
| PR 11c | #39 | `1d3220a` | — | 2026-10-01 | Merged and pulled as `strategy`, no restart. **PR 11 is complete.** Unit 8o-overview (8o.1-8o.3), which completes PR 11: `OverviewPage`, `PoolPanel` and `DecisionRail` wired to live data, `usePoolPerformance`, the pools `balance` typed and validated, and the decision rail placed right on wide screens and between the chart and the grid on narrow ones. Committed on `feat/operator-panel-overview-page` (`57d1015`, `c5bef02`, `665d842`, plus the owner's visual-review fixes, decisions 33-35: `41f77df` chart follows the range, `2a09c3e` three years of the grid, `08e8d77` bounded panel and fluid rail; then the second review, decisions 36-37: `10c644c` chart at its measured width and fixed height, `cf49809` panel fills the width with the selector in the chart header, `67143bb` interim pool order), **not pushed**. Risk **low** (frontend only, read-only endpoints, no backend change; the first PR that mounts the chart and the grid with live data). No migration. Deploy: pull as `strategy`, no restart (frontend only, not served while `PANEL_DIST_DIR` is unset). |
| PR 12a-1 | #40 | `ccc7c92` | — | 2026-10-02 | The list half of unit 9l-list (task 9l.1): `StrategiesPage`, `StrategyRow`, `ArchivedToggle`, the `['strategies',{includeArchived}]` query, the enabled switch that PATCHes from the row, and one `['performance','strategy',id]` request per row. Unit 9l came out at about 1,330 lines against a 400-550 forecast, so the owner split it: the new-strategy dialog (9l.2, 9l.3) is PR 12a-2. Risk **low** (frontend only, no backend change). No migration. The owner reviewed the list locally before the push. Pulled as `strategy`, no restart (frontend only, not served while `PANEL_DIST_DIR` is unset). |
| PR 12a-2 | #41 | `ed4c9f1` | — | 2026-10-02 | The dialog half of unit 9l-list (tasks 9l.2-9l.3), which completes unit 9l: `NewStrategyDialog` with an id from `crypto.randomUUID()` reused on retry, the zero-pairs guard, and its own messages for a 409 and a 422. Also task 9l.4 (decision 39): the row sub-line is `<venue> · <pairs>`. It carries the documents of decisions 40-42: the design of unit 9v (PR 12v, pairs validated against the venue catalogue) and unit 9x (deleting a strategy with no history, not designed). The pairs textarea is temporary until PR 12v-5. Risk **low** (frontend only, no backend change). No migration. The owner reviewed the dialog and the row locally before the push. Pulled as `strategy`, no restart (frontend only, not served while `PANEL_DIST_DIR` is unset). |
| PR 12v-0 | #42 | `c95a625` | — | 2026-10-02 | Unit 9v0 (tasks 9v0.1-9v0.3): `scripts/check_public_catalogue.py`, the GET-only, unsigned probe P7, and its 14 tests. Risk **low** (a development script nothing imports; it loads no credential and builds no order). No migration. Pulled as `strategy`, no restart. The owner ran the probe on the VPS: both public catalogues answer HTTP 200 with no signature and no key, and the filter strings hold; see "PR 12v-0 — Probe P7 results". It also showed Bybit at 891 `linear` entries against the 1,000-entry single page of the order path (follow-up 9vf.1). |
| Fix | #44 | `23fbe4e` | — | 2026-10-02 | Tests only: an autouse fixture in `backend/tests/conftest.py` turns operator alerts off on the shared settings for every test. **Found doing PR 12v-0 and 12v-1:** every full backend suite run on the owner's machine sent a real Telegram alert ("cannot save a credential: MASTER_ENCRYPTION_KEY is not set"), because `test_lifespan_wiring.py` enters the real lifespan, which installed the alert bridge from the local `.env`, and then logs its one intended ERROR. Confirmed against the chat: a full run from 16:28:53 to 16:32:54 UTC sent nothing. Pulled as `strategy` together with PR 12v-1. |
| PR 12v-1 | #43 | `c490fe7` | — | 2026-10-02 | Unit 9va (tasks 9va.1-9va.6): `BybitPublicTransport` and `BinancePublicTransport`, which cannot sign; `PerpContract.settles_in`; `BybitPublicCatalogue` (follows `nextPageCursor`, stops on an empty or absent cursor, a page cap raises) and `BinancePublicCatalogue`. The signed transports changed only by a behaviour-preserving extraction of `send_request`; no pre-existing test was modified. Nothing is wired yet. Risk **medium**: the worker imports both transport files. No migration. Pulled as `strategy`, restarted both; the API and the worker came up active. Also recorded: the owner's authorization of follow-up 9vf.1. |
| Fix 9vf.1 | #45 | `749ae48` | — | 2026-10-02 | Follow-up 9vf.1: the signed `perp_contracts` of the ORDER path follows `nextPageCursor` to the end through `bybit/catalogue_pages.py::read_every_page`, the loop extracted from the public catalogue. A one-page catalogue behaves as before; a repeated cursor or more than ten pages raises instead of returning a partial list; parsing stays eager and strict. Risk **medium**: it is the order path, though `DRY_RUN=true` keeps the fake adapters in use, so production does not exercise it yet. No migration. The owner merged and deployed it (the worker imports `read_client.py`, so the deploy is a pull as `strategy` plus a restart of both services); the API and the worker came up active. Nothing was run against the real venue. |
| PR 12v-2 | #46 | `ad9dbdd` | — | 2026-10-02 | Unit 9vb (tasks 9vb.1-9vb.7): `PairCatalogPort`, `VenuePairCatalog` (credential-free, 300 s TTL per pool triple, single flight, failures not cached), `ReadAvailablePairs` and `GET /api/pools/{exchange}/{venue}/{settlement_currency}/available-pairs`. Risk **medium**: the first PR in which the API process reads the venues' public catalogues; no save depends on it yet. No migration. Pulled as `strategy`, restarted; the API and the worker are active. **Checked in production by the owner:** `bybit/usdt-m/USDT` answers 200 with 783 pairs (`AAVEUSDT` and `STXUSDT` listed, `SFPUSDT` not), and `binance/usdt-m/USDT` answers 200 with 528 pairs (all three listed). Both counts equal probe P7.4, so the real parser drops no pair the probe's filter kept. One existing test changed: the secret sweep was taught the new route. |
| PR 12v-3 | #47 | `e6ffd58` | — | 2026-10-02 | Unit 9vc (tasks 9vc.1-9vc.8): `RegisterStrategy` refuses every unlisted pair; `ReplaceAllowedPairs` validates only added pairs, asks the venue before the row lock and re-checks under it (409 `PAIRS_CHANGED`); 422 `UNKNOWN_PAIRS` with the symbols, 422 `PAIR_CATALOGUE_NOT_SERVED`, 502 `PAIR_CATALOGUE_UNAVAILABLE`. Risk **medium**: it changes what a save accepts, and `get_by_id_for_update` now uses `populate_existing=True` (found doing it: a locked read of a row the session had already loaded returned stale ORM values). No migration. Pulled as `strategy`, restarted the API; the API and the worker are active. **Checked in production by the owner:** a `POST /api/strategies` on `binance/usdt-m/USDT` with pairs `BTCUSDT` and `YPF` answered 422 `UNKNOWN_PAIRS`, "the venue does not list: YPF", and stored nothing. Until PR 12v-5 the dialog's free-text field shows that refusal as a generic message. |
| PR 12v-4 | #48 | `3d5af4a` | — | 2026-10-02 | Unit 9vd (tasks 9vd.1-9vd.4): `ApiError` exposes a structured detail's `code` and `fields` and always carries human text; `fetchAvailablePairs` and `useAvailablePairs` with the response validated (shape, pool match, count); `PairSelector`, presentational and not mounted. Risk **low** (frontend only; nothing on screen changes). One behaviour change: a list `detail` from a FastAPI validation failure is no longer kept under a string type. No migration. Pulled as `strategy`, no restart (frontend only, not served while `PANEL_DIST_DIR` is unset). The visual review waits for PR 12v-5, which mounts the selector. |
| PR 12v-5 | #49 | `c4499ae` | — | 2026-10-02 | Unit 9ve (tasks 9ve.1-9ve.3), the last PR of unit 9v: `PairSelector` mounted in `NewStrategyDialog` over `useAvailablePairs`; the free-text field, `parsePairs` and `pairsHint` removed; Create disabled until the pool's list has loaded; refusals read by `error.code` and naming the unknown symbols; the test harness's default pool corrected to `bybit/usdt-m/USDT`. Risk **low** (frontend only). No migration. The owner reviewed it locally against the real public catalogues and accepted the double alert on a pool with no catalogue source. Pulled as `strategy`, no restart (frontend only, not served while `PANEL_DIST_DIR` is unset). **Unit 9v is complete: decisions 40 and 41 are delivered.** Owner polish 7p.3 (bottom padding of the scrolled content) was recorded with it. |
| PR 12x-1 | #50 | `0234caa` | — | 2026-10-02 | Unit 9xa (tasks 9xa.1-9xa.5), the first PR of unit 9x: an alert naming an unregistered strategy is refused at the webhook with 422 `UNKNOWN_STRATEGY` and one WARNING, recognised by the violated constraint's name (`fk_signals_strategy`); it used to be an unhandled 500. Ingress gains no lookup and no lock. Also `tests/pg_head_schema.py`, a throwaway database migrated to `head`. It carries the design of unit 9x and the owner's answer that enablement events do not block a delete (migration 0028, unit 9xf, now in scope). Risk **medium**: it edits the webhook path, though only an error branch. No migration. Pulled as `strategy`, restarted the API. |
| PR 12x-2 | #51 | `3985709` | — | 2026-10-02 | Unit 9xb (tasks 9xb.1-9xb.4): `StrategyHistory` (six counts) and `StrategyHistoryPort`, one read-only count per provider repository, `StrategyHistoryAdapter`, and a `pg_constraint` guard on a head-migrated database that fails when a foreign key into `strategies` is not counted. Nothing calls it yet. Enablement events block until migration 0028 (unit 9xf). It also carries decision 43 (the per-strategy list of operations, tasks 9p.4-9p.5) and the owner's answer that an archived strategy with no history can be deleted. Risk **low**: read methods only, no behaviour change. No migration. Pulled as `strategy`, restarted both; the API and the worker are active. |
| PR 12x-3 | #52 | `fcdf9dd` | — | 2026-10-03 | Unit 9xc (tasks 9xc.1-9xc.7): `DeleteStrategy` (pool advisory lock, then the row lock, then the six counts; enabled and any history refuse; an archived strategy with no history is deleted), `SqlAlchemyStrategyRepository.delete` translating a foreign-key refusal by SQLSTATE and constraint name, and lock-hold tests on a head-migrated database. No route calls it yet. Enablement events block until migration 0028 (unit 9xf). Size exception approved by the owner: 1,627 lines, about 200 of them production code. Risk **low**: a use case nothing routes to, no behaviour change. No migration. Pulled as `strategy`, restarted both; the API and the worker are active. |
| PR 12x-4 | #53 | `8e9af65` | — | 2026-10-03 | Unit 9xd (tasks 9xd.1-9xd.3): `DELETE /api/strategies/{id}`: 204 no body; 404 unknown or repeated; 409 `STILL_ENABLED`; 409 `HAS_HISTORY` with all six counts, also for a database refusal, never a 500; the session rolled back on every refusal. An archived strategy with no history is deleted; enablement events block until migration 0028 (unit 9xf). 445 lines. Risk **medium**: from this deploy a strategy with no history can be deleted through the API with the admin token. No migration. Pulled as `strategy`, restarted both; the API and the worker are active. Task 9xd.4 (the owner deleting the two test strategies) is pending. |
| PR 12x-5 | #54 | `d5de677` | — | 2026-10-03 | Unit 9xe (tasks 9xe.1-9xe.4; 9xe.5 void, unit 9d is not merged): `deleteStrategy` and `useDeleteStrategy`, `DeleteStrategyDialog` (the name typed to confirm, the refusals rendered with their counts) and `DeleteStrategyControl`, with `strategies.delete.*` in EN and ES. Nothing mounts the control until task 9d.6, so no screen changes. Size exception approved by the owner: 827 lines. Not checked by eye in a browser, at the owner's choice. Risk **low**: frontend only, and the panel is not served in production. No migration. Pulled as `strategy`, no restart. |
| PR 12x-6 | #55 | `150f3d8` | 0028 | 2026-10-03 | Unit 9xf (tasks 9xf.0-9xf.5): enablement events are deleted with their strategy. `fk_strategy_enablement_events_strategy` is `ON DELETE CASCADE` and the append-only trigger function lets a `DELETE` through only when the parent strategy no longer exists; `StrategyHistory.blocking()` leaves the events out and the delete's INFO line names how many went, the first enable time and the uptime. Size: 903 lines, one PR by the owner's choice. Rehearsed on `sm_rehearsal` restored from a fresh backup, all seven steps passed: no row moved (3 strategies, 3 events); a direct `DELETE` and an `UPDATE` of an event refused; a strategy with a signal refused by `fk_signals_strategy` with its events intact; a strategy with only events deleted with them; the downgrade clean with exactly one `WARNI` line and the delete refused again by the events key; up, down, up clean. Production was read only and stayed at 0027 during the rehearsal. Backup `/root/sm_pre0028_20261003_2031.dump`. Then pulled as `strategy`, `alembic upgrade head` (0027 -> 0028), restarted both; the API and the worker are active and `alembic current` answers `0028 (head)`. Risk **medium**: a schema change, and from this deploy a strategy that was only switched on and off can be deleted. Open follow-up for the owner: the delete dialog still names enablement events among the reasons of a `HAS_HISTORY` refusal, although they no longer block. |
| PR 12b | #56 | `9fa5d6d` | — | 2026-10-03 | Unit 9d (tasks 9d.1-9d.9) and polish 7p.3: the strategy detail page (header and uptime, enable history, the allowed-pairs editor on `PairSelector`, the enable switch, the archive control and dialog) with the delete control mounted at the bottom; the delete dialog no longer names enablement events (the follow-up of PR 12x-6, decided by the owner); the bottom padding of the scrolled content fixed in the shell. Size: 1,852 lines, one PR by the owner's choice. Checked by eye by the owner, who asked for two overflow fixes (the history capped at `max-h-100`, the pair list at `max-h-36`) before the push. After migrating the local database to 0028 the owner deleted a strategy that had only been switched on and off, from the panel, locally. Risk **low**: frontend only, and the panel is not served in production. No migration. Pulled as `strategy`, no restart. Task 9xd.4 (the two test strategies in production) still waits for the panel to be served there. |
| PR 12c | #57 | `49aaa3d` | — | 2026-10-03 | Unit 9w (tasks 9w.1-9w.3) and polish 7p.4: the "Connect a TradingView alert" block on the strategy detail page, with the webhook URL behind a placeholder, "Show secret" fetching the secret only on the click and evicting it on hide, on leaving the view and on a strategy change, and the alert message rendered from a fixture the backend parser also reads; the Overview's ledger line no longer overflows sideways under 1024px. It also records unit 12f, eight follow-ups that wait for an owner decision. Size: 764 lines. Checked by eye by the owner with the network panel open: no request to the secret endpoint on opening a strategy, one on the click, the placeholder back after leaving. Risk **low**: frontend and one backend test file, and the panel is not served in production. No migration. Pulled as `strategy`, no restart. |
| PR 12d | #58 | `9c8fc6d` | — | 2026-10-04 | Unit 9p (tasks 9p.1-9p.3 and 9p.6-9p.12) and polish 7p.5: one strategy's performance from the Overview's instruments, the By pair table, and the closed trades paged 20 at a time with Previous and Next. From the owner's review by eye: the enable history moved into the settings column under the enable switch, capped at `max-h-18`; a second scrollbar on the document removed (`main` is now `relative`); "Connect a TradingView alert" opens from a button in the page header and is unmounted when closed; the pair list shows nothing until the owner searches; "LONG" and "SHORT" in Spanish; "Try again" when the performance fails to load. It also records decision 44, the owner's answers on the detail page. Tasks 9p.4 and 9p.5 (decision 43) are not in it. Size: 2,177 lines, 813 of them production code and locale keys, one PR by the owner's choice; the owner no longer wants PRs split by size. Checked by eye by the owner with a local fixture serving a strategy report and 120 trades, and approved. Risk **low**: frontend only, and the panel is not served in production. No migration. Pulled as `strategy`, no restart. |
| PR 12g | #59 | `4388590` | — | 2026-10-04 | Unit 9q (tasks 9q.1-9q.29), owner decision 45: under `DRY_RUN` the simulated exchange fills an order at its alert's price, exactly, and charges the venue's taker fee in USDT (Bybit `0.00055`, Binance `0.0005`); a close is priced at the alert that closes it; an unusable price is refused, never defaulted; a market not quoted in USDT and an exchange with no rate are refused in a dry run. No real adapter file and no existing real-adapter test changed; `DRY_RUN=false` is unchanged. It also carries the planning of decision 43 (PR 12e) and of this decision: design addenda, spec deltas and tasks. Size: 3,546 lines, about 480 of them production code. Before the restart the owner ran the read-only check of task 9q.29: alembic 0028; no open rehearsal allocation on an exchange with no fee rate; no open rehearsal allocation at all, so no position straddles the change; 4 rehearsal fills in the ledger, all priced at 1 with a fee of 0. Then pulled as `strategy` and restarted both; the API and the worker are active. Risk **medium**: it changes how the worker fills orders in a dry run. No migration. The worker's journal confirms the new pricing from its start at 23:27:37 on the VPS clock: one INFO naming `binance=0.0005, bybit=0.00055`, and no line naming a fixed price or a missing fee rate. **Not confirmed yet (task 9q.30):** no dry-run fill has been seen since the deploy, so its price and fee are still to be checked in the log and in the ledger. |
| PR 12e-1 | #60 | `845f02a` | — | 2026-10-05 | Unit 9p.4 (tasks 9p.4.1-9p.4.37), the backend of owner decision 43: each row of a strategy's trades list gains `rehearsal`, `rehearsal_fill_price`, `base_currency`, `entry_price`, `exit_price`, `size`, `fees` and `other_fees`; dry-run operations are listed only for `include_rehearsal=true` (default false, so the older panel reads what it read); the new route `GET /api/performance/strategies/{id}/trades/{allocation_id}/fills` answers one operation's stored fills, capped at 200, with one 404 for an unknown, a foreign and a fill-less allocation. The shared fills aggregate now groups by origin and by symbol and returns dry-run groups in a set of their own; `require_live_only` refuses a dry-run group in any total. New wire type `Price`. Size: 5,419 lines added, 1,024 of them production code, one PR by the owner's standing choice. Built in three sequential batches on one branch. Gate at `568a683`: ruff 0, mypy 0 (284 source files), pytest 0, 3,160 tests after the unit's last task; one earlier run hit the known teardown flake in `tests/reconciliation/application/test_reject_booking.py` and the re-run was clean. Recorded in the PR: reverting only the fills route's commit `58ef460` leaves the webhook-secret sweep red, because its sweep edit is in `4632915`; `fees` can be served as a bare `"0"`. Risk **medium**: it edits the aggregate every performance read shares and adds a route; it places no order and writes nothing. No migration. Merged 2026-10-05 02:51 UTC with a merge commit. The owner pulled as `strategy` and restarted both; the API and the worker are active (the owner's report). The optional read-only check of task 9p.4.38 (the list with and without `include_rehearsal=true`) was not reported. |
| PR 12e-2 | #61 | `3b54844` | — | 2026-10-05 | Unit 9p.5 (tasks 9p.5.1-9p.5.25 and 9p.5.27-9p.5.33), the panel of owner decision 43, which completes it: "Closed trades" is a full-width section of the strategy detail page with twelve columns shown by width (six, eight, eleven, twelve), each operation's entry, exit, size and fees, dry-run operations marked under the pair with their kind and explained by notes below the table, and a Details button that opens a modal with the operation's figures and a table of its fills, requested only on opening. A page or a fills body that lacks a field is refused whole. It records three owner answers: the wording for an alert-priced dry-run row (9qf.3, under decision 45), the headings of an operation with no base currency (under decision 43), and decision 46 from the review by eye (an asterisk and a note for incomplete fees, "Pool at open", compact two-line dates, at most 5 decimals with a 4-significant-digit floor, fees with two decimals, the notes below the table). Found in review and fixed before the push: a refactor lost a backslash in a regular expression of `format.ts`, with the gate green (`7e2ecae`, `325f6b9`). Gate at `8512197`: lint 0, 49 test files and 857 tests. Size: 2,838 lines added under `frontend/`, 784 of them production code and locale keys, one PR by the owner's standing choice. Checked by eye by the owner twice, with the local fixture updated to serve the new fields and the fills route. Risk **low**: frontend only, and the panel is not served in production. No migration. Merged 2026-10-05 17:25 UTC with a merge commit; the owner reported the merge and the deploy (a pull as `strategy`, no restart). |
| Fix 9qf.1 | #62 | `5c9899d` | — | 2026-10-05 | Follow-up 9qf.1 of PR 12g: the webhook refuses an alert whose `price`, `data.contracts` or `data.position_size` is not a finite number, in every spelling `Decimal` accepts. It answers 422 naming the field and not the value, stores no signal and no job, and writes one WARNING. Before it, on the route: `NaN` answered 200 and was stored (an opening order then failed at build in the worker and its job was retried until its attempts ran out); an infinity answered an unhandled 500. The check is in `_to_decimal`, the one place that coerces the alert's numbers. The requirement is a new delta of the change, `specs/signal-ingress/spec.md`. One existing test depended on the defect and now writes its `NaN` by SQL, assertions unchanged. Gate: ruff 0, mypy 0 (284 source files), pytest 0, 3,224 tests. Size: 372 lines added, 23 of them production code. Risk **low**: it adds a refusal before anything is stored. No migration. Merged 2026-10-05 19:27 UTC with a merge commit; the owner pulled as `strategy` and restarted both, and reported the API and the worker active. It left two follow-ups, 9qf.5 and 9qf.6. |
| Fix 9qf.5 + 9qf.6 | #63 | `ed7e692` | — | 2026-10-06 | Follow-ups 9qf.5 and 9qf.6, both found building 9qf.1. **9qf.5:** the webhook refuses with a 422 what the `signals` table would refuse at the insert, where it answered an unhandled 500: a `price` of zero or below (or zero once rounded to 18 decimals), a number with more than 20 integer digits in any of the three numeric fields, an exponent beyond PostgreSQL's 16383, a body that is not valid JSON, and a JSON body that is not an object. The checks compare the number as `NUMERIC(38, 18)` would store it and return it as it was sent, so the idempotency key of a valid alert is unchanged. `data.contracts` and `data.position_size` got no sign rule: the migrations have one sign CHECK, `price > 0`. **9qf.6:** every refusal after authentication writes exactly one WARNING, `webhook alert refused: <field> <reason>`, that never carries a value the sender supplied; the 401 path writes none, nor does an accepted or duplicate alert. The requirements are ADDED to the change's delta `specs/signal-ingress/spec.md`. One test of 9qf.1 used a negative price as a valid value and now uses a positive one, assertion unchanged. Gate: ruff 0, mypy 0 (284 source files), pytest 0, 3,427 tests. Size: 1,182 lines added, 133 of them production code. Risk **low**: a valid alert takes the same path. No migration. Merged 2026-10-06 14:36 UTC with a merge commit; the owner pulled as `strategy` and restarted both, and reported the API and the worker active. **Checked by the owner after the deploy:** `journalctl -u strategy-api --since "1 hour ago"` shows no `webhook alert refused` line, so no alert was refused in that hour. It left follow-up 9qf.7. |
| Docs 9qf.2 + 9qf.4 | #64 | `bf8373e` | — | 2026-10-06 | Documentation only. **9qf.2:** CLAUDE.md's section on credentials is rewritten from the code as "one key per exchange, in the vault" (owner decision 18): the one vault key signs reads and orders alike, the settings have no Bybit or Binance key field, a read-only key is accepted with a warning and supersedes the active one, only the worker decrypts, and every probe that signs loads from the vault. The owner approved the text before the commit. `.env.example` made the same false statement and is corrected with it: it called the Binance read-only key load-bearing in live mode, listed `BINANCE_API_KEY` and `BYBIT_API_KEY` entries that nothing reads, and said the worker never reads the vault under `DRY_RUN`. **9qf.4:** the docstring of the test that pins `CloseCommand` has no field named `price` now says a close carries `reference_price` since PR 12g. No executable line changed, so the full gate was not run; the two touched or pinning test files pass. Size: 72 lines added. Risk **none** to a running process. No migration. Merged 2026-10-06 15:07 UTC with a merge commit; the owner reported the merge and the deploy (a pull as `strategy`, no restart). |
| Fix 9qf.7 | #65 | `a9ccb61` | — | 2026-10-06 | Follow-up 9qf.7, the last known 500 on the webhook: a body that is authenticated, valid JSON and shaped like an alert, and still cannot be stored. Observed as a class on the route before fixing: a NUL character or a lone surrogate in a field, in the rest of the stored body or in an object key; the literals `NaN`, `Infinity`, `-Infinity` or an overflowing number such as `1e999` as an extra value; and a body nested 3,000 levels or more, where the JSON parser overflows its recursion. Each answered 500 and now answers 422, stores nothing and writes one WARNING with a fixed reason and no value. The check is one ITERATIVE pass over the parsed body in `signals/domain/alert.py`; storable text is decided by encoding it, so accented, CJK and astral text is still accepted. `MAX_BODY_DEPTH = 64`, against a contract two levels deep and a shallowest measured failure between 2,000 and 3,000 levels. Changed on purpose: a body nested 65 to 2,000 levels was stored and is now refused; a NUL in `signal_type` keeps its 422 with the character reason instead of the UUID one. A safety net at the insert was considered and not built: the exception type it would catch also covers a lost connection, a timeout and a deadlock. Gate: ruff 0, mypy 0 (284 source files), pytest 0, 3,505 tests; a first run hit the known teardown flake twice, with no assertion failure, and the re-run was clean. Size: 796 lines added, 86 of them production code. Risk **low**. No migration. Merged 2026-10-06 16:11 UTC with a merge commit; the owner pulled as `strategy` and restarted both, and reported the API and the worker active. It left follow-up 9qf.8. |
| Fix 9qf.8 | #66 | `c7893ab` | — | 2026-10-06 | Follow-up 9qf.8, owner decision 47, which completes unit 9qf: the webhook refuses a body larger than 65,536 bytes with a 413, stores nothing and writes one WARNING. Before it nothing bounded the body, and one carrying an 8 MB string was stored with a 200. The body is never read whole and then measured: a declared `Content-Length` past the limit is refused before reading, and otherwise the request's stream is read with a running count that stops at the first chunk past the limit; the count of bytes received is the authority, never the header. Authentication is still first, so an unauthenticated request is answered 401 with none of its body read. The limit is a constant in `signals/infrastructure/router.py`, on the webhook route only. Three route tests of 9qf.7 posted 100,000 levels of nesting, about 200 KB, and now post 9,000, within the limit and still past the parser's recursion failure. Probed against a local uvicorn: a `Content-Length` that lies or is not a number is answered 400 by the server before the application runs. Gate: ruff 0, mypy 0 (284 source files), pytest 0, 3,550 tests. Size: 722 lines added, 66 of them production code. Risk **low**: a real alert is about 300 bytes. No migration. Merged 2026-10-06 17:05 UTC with a merge commit; the owner pulled as `strategy` and restarted both, and reported both services active. |
| PR 12f-1 | #67 | `06878b5` | — | 2026-10-09 | Unit 12f.9 (tasks 12f.9.1-12f.9.15 and 12f.9.17), the backend of owner decisions 44, 48 and 50: `wins` and `win_rate` on each `by_pair` entry of a strategy's report; the webhook's public origin from the new setting `WEBHOOK_PUBLIC_ORIGIN`, parsed as an origin and nothing more and served by `GET /api/webhook-origin`; a strategy's share of the pool served in plain notation, with one INFO line when it changes; `GET /api/strategies/{id}/share-preview`, read-only, which answers what a share asks for from the pool's total with the engine's own function, 100 integer steps and the pool's minimum; and a share bounded at 18 decimal places on its three inputs, which also turns a 500 of the update and the registration at `1e-20000` into a 422. It also carries unit tif (every throwaway test database dropped through `backend/tests/pg_drop.py`, which waits out the autovacuum worker), decision 49 with the owner-run unit whn, and the design, specs and tasks of unit 12f. Gate at `bdad8ec`: ruff 0, mypy 0 (291 source files), pytest 0, 3,764 tests. Size: 9,276 lines added, 681 of them production code, one PR by the owner's standing choice. Risk **low**: every route is new or gains fields. No migration. Merged 2026-10-09 with a merge commit. The owner pulled as `strategy`, set `WEBHOOK_PUBLIC_ORIGIN` to the name of decision 49 and restarted both. **Checked on the VPS after the deploy** (read-only, over loopback): both services active on `06878b5`; the origin route answers the configured origin; the share preview of each of the three strategies answers 100 steps with a balance that is present and not stale; the report answers with an empty `by_pair` under `DRY_RUN`. **One check failed and found unit alg:** the journal holds no startup line of the origin, because the API process writes none of its own INFO lines. |
| Fix alg | #68 | `2f4d738` | — | 2026-10-10 | Unit alg (tasks alg.1-alg.4), found by the check after the deploy of PR 12f-1: the API process writes its own log lines. The worker configured logging at startup and the API never did, and uvicorn's configuration covers only its own loggers, so in the API the root logger sat at WARNING with no handler: every INFO line was dropped, and with operator alerts on, whose bridge is a handler on the root logger, a WARNING and an ERROR were written nowhere by the process. `configure_api_logging()` sets the root logger to INFO and adds one handler of its own that writes to stderr in the worker's format; it is the first line of `lifespan`, before the alert bridge, and not in `create_app()`, which runs at import and which the worker imports. The worker and the text of every line are unchanged; uvicorn's lines are still written once, the access line still masks the webhook's secret, and `httpx` and `httpcore` stay at WARNING. The tests of what is written run in a subprocess with uvicorn's real configuration, because `caplog` is what hid the defect. Also run against a real local uvicorn before the push. Gate at `788fbe0`: ruff 0, mypy 0 (292 source files), pytest 0, 3,784 tests. Size: 315 lines under `backend/`, 66 of them production code. Risk **low**. No migration. Merged 2026-10-10 02:06 UTC with a merge commit; the owner pulled as `strategy` and restarted both. **Checked on the VPS after the deploy:** both services active on `2f4d738`; one startup line of the origin and one "operator alerts are on" line in the journal; no WARNING, no ERROR; no secret, token or database URL in the run's lines. **It settles that alerting is on in production**, so for as long as it has been on no WARNING of the API reached the journal, and the check recorded with fix 9qf.5 + 9qf.6 may prove nothing. |

Also done outside the PRs (2026-09-25): the three stale Pionex rows were deleted from
`pool_balance_snapshots`, and the Bybit FUND balance was moved to UNIFIED.

## Probe gates (owner-run, GET-only, never places an order)

- **Before PR 3 deploys**: probe item **P4** (live reads against the Bybit and Binance vault
  keys) must be recorded in "PR 1 — Probe results" below. PR 3 rewires Binance's five read
  sites onto the vault key; P4 is the only proof that key can perform every one of those GETs.
- **Before PR 8a's rules are written**: probe items **P1** (Bybit withdraw shape), **P2**
  (Bybit trade capability), **P3** (Binance `apiRestrictions`) must be recorded. No line of
  `key_policy.py`'s `evaluate_key()` is written before this section exists — the
  book-venue-closes unit 2a precedent (design's own instruction).
- **P5** (binding/expiry fields) is informational only; it gates nothing, but its shape must
  be recorded before PR 13's Settings card renders it.
- **Before PR 12v-1's adapters are written** (added 2026-10-02, decision 41): probe **P7**
  (`backend/scripts/check_public_catalogue.py`, PR 12v-0) must be recorded in "PR 12v-0 —
  Probe P7 results". It loads no credential at all. P7.1 proves that Bybit
  `GET /v5/market/instruments-info?category=linear` and Binance `GET /fapi/v1/exchangeInfo`
  answer 200 from the VPS with no signature and no key header; P7.2 records the entry counts
  by contract type, status and settle or margin coin (the exact strings the filter compares);
  P7.3 records whether Bybit returns a `nextPageCursor` and that following it returns every
  entry once. No line of `public_catalogue.py` is written before that section exists
  (tasks 9va.4–9va.6). P7.5 (are `SFPUSDT`, `AAVEUSDT`, `STXUSDT` listed) is informational.

## Migration rehearsal (0024, 0025, 0026, 0027, 0028)

Every migration in this change is rehearsed **locally** first (Tier B: up, down, refusals)
and then **on the VPS against a throwaway restore**, per design's "Migration / rollout":

```
pg_dump production → createdb sm_rehearsal → restore →
DATABASE_URL=postgresql://.../sm_rehearsal uv run alembic upgrade head →
read the seeding/backfill log →
DATABASE_URL=postgresql://.../sm_rehearsal uv run alembic downgrade -1 (assert the refusal) →
dropdb sm_rehearsal
```

The throwaway copy never leaves the VPS. Never print the `DATABASE_URL` or any connection
string in a log line, a commit message, or this file.

- **0024** (PR 4, strategy lifecycle): rehearse, read the seeded-pairs log line per strategy
  and the BASELINE event count, **the owner reviews the seeded pairs in the panel/`GET
  /api/strategies` before PR 5 deploys** (Q1's resolution — the migration itself is what
  answers Q1, not a separate owner decision).
- **0025** (PR 5b, signal outcomes, decision 25): rehearse; additive nullable columns and a
  nullable FK, no seeding. Existing signals stay `ACCEPTED`. The downgrade refuses once any
  outcome is recorded.
- **0026** (PR 6, `pool_total_at_open`): rehearse; additive column, no seeding to review.
- **0027** (PR 8a, credential snapshot): rehearse; confirm the backfill sets every existing
  row `trade_capable=true` (correct by construction — every current store script already
  refuses a key that cannot trade) and that the downgrade refuses while `trade_capable=false`
  exists.
- **0028** (PR 12x-6, enablement events cascade; the owner answered design addendum 9x § L, Q1
  with "enablement events do not block a delete", decision 42). Rehearse on a throwaway
  database restored from a FRESH backup, as above, and additionally, inside `sm_rehearsal` only:
  1. After `upgrade head`: confirm `fk_strategy_enablement_events_strategy` is `ON DELETE
     CASCADE` and that the count of `strategy_enablement_events` rows is unchanged (the
     migration moves no data).
  2. `DELETE` one event of a strategy that exists: it must be refused (`restrict_violation`).
  3. `UPDATE` one event: it must be refused (`restrict_violation`).
  4. `DELETE` a strategy that has a signal: it must be refused by `fk_signals_strategy`, and its
     events must still be there.
  5. `DELETE` a strategy that has only events (create one for the purpose if production has
     none): it must succeed and take its events with it, and no other strategy's events move.
  6. `alembic downgrade -1`: it must succeed with no refusal (it discards no data), the log
     must show exactly one `WARNI` line naming 0028 (`alembic.ini` truncates WARNING to five
     characters), the events that survived must still be there, and step 5 must then be
     refused again by `fk_strategy_enablement_events_strategy`.
  7. `alembic upgrade head` once more: it must succeed (up, down, up is clean).
  Schema-only on both sides: no seeding and no backfill log to read. Production migrates only
  after this passes. Deploy order for PR 12x-6: pull, `alembic upgrade head`, restart both
  services; the code alone, before the migration, still refuses a strategy that has events
  (the database says so, and the delete answers `HAS_HISTORY` with one ERROR).

## Dependencies

- PR 1 ⟂ PR 2 (independent; both can start immediately).
- PR 3 needs PR 1's **P4** output recorded (not PR 2 — PR 3 rewires Binance reads, not paths).
- PR 5 needs PR 4 (schema + endpoints the owner needs to prune the seeded pairs).
- PR 6 needs PR 5 only for unit 3d (per-strategy stats read the allowlist/archived snapshot
  fields); 3a–3c have no dependency on PR 5.
- PR 7 needs PR 6 (the read endpoints wrap PR 6's read models).
- PR 8a needs PR 1's **P1–P3** recorded, and PR 3 (one active-key vault shape).
- PR 8b needs PR 8a (`SaveCredential`'s pool-enable hook) and PR 5 (`DeleteCredential` reuses
  PR 5's pool-lock adapter and `StrategyExposurePort` query shape).
- PR 9 ⟂ the rest of the backend (SPA serving touches no domain module).
- PR 10 needs PR 2 (the `/api` prefix its `apiFetch` calls) and PR 9 (mount + fallback,
  though the shell can be built before infra is proven; the built bundle just has nowhere to
  be served without PR 9's owner steps).
- PR 11 needs PR 10 and PR 7 (pools + performance reads).
- PR 12 needs PR 10, PR 7 (webhook-secret), PR 4 and PR 5 (strategy/pairs/archive endpoints).
- PR 13 needs PR 10, PR 8a and PR 8b (credential add/rotate/delete endpoints).
- Unit 9v (added 2026-10-02, decision 41), strictly in this order, each cut from `main` after
  the previous one merged and deployed:
  - PR 12v-0 needs PR 12a-2 merged (delivery order only; the script depends on no code).
  - PR 12v-1 needs **P7** recorded (the filter strings and the cursor behaviour).
  - PR 12v-2 needs PR 12v-1 (the sources its adapter wraps).
  - PR 12v-3 needs PR 12v-2 (`PairCatalogPort` and its wiring). Its `PairCatalogNotServed`
    tasks also need the owner's answer to design addendum § L, Q1.
  - PR 12v-4 needs PR 12v-2 (the read endpoint) and PR 12v-3 (the refusal bodies it parses).
  - PR 12v-5 needs PR 12v-4 and PR 12a-2 (`NewStrategyDialog`).
  - Unit 9d's task 9d.5 (`AllowedPairsEditor` on the selector) needs PR 12v-4.
  - PR 12v-1 to 12v-3 ⟂ the rest of PR 12 (units 9d, 9w, 9p) and PR 13: no shared file.
    Only 9d.5 and PR 12v-5 touch files the rest of PR 12 touches.
- Unit 9x (added 2026-10-02, decision 42), strictly in this order, each cut from `main` after
  the previous one merged and deployed:
  - PR 12x-1 needs nothing. It is independent of unit 9d and of PR 13.
  - PR 12x-2 needs nothing from 12x-1 in code; it follows it in delivery order only.
  - PR 12x-3 needs PR 12x-1 (`UnknownSignalStrategy`, used by its concurrency test) and
    PR 12x-2 (`StrategyHistoryPort`). Its task 9xc.6 needs the owner's answer to Q3.
  - PR 12x-4 needs PR 12x-3, and PR 12x-1 **deployed**: no strategy may be deletable in
    production while the webhook still answers a 500 for its leftover alert. The archived case
    of 9xd.1 needs Q3.
  - PR 12x-5 needs PR 12x-4 (the refusal bodies it parses). It does NOT need unit 9d: the
    control ships unmounted. The archived case of 9xe.3 needs Q3.
  - **Unit 9d and PR 12x-5, either order.** If 12x-5 merges first, unit 9d mounts the control
    (task 9d.6). If unit 9d merges first, task 9d.6 moves into PR 12x-5 as task 9xe.5. The
    mounting is one edit and is done once.
  - PR 12x-6 needs PR 12x-3 and the owner's answer to Q1 (answered: "enablement events do not
    block"). It may land before or after 12x-4 and 12x-5.
  - PR 12x-1 to 12x-4 ⟂ the rest of PR 12 (units 9d, 9w, 9p) and PR 13: no shared file.
- Unit 12f (added 2026-10-06, decisions 44 and 48), strictly in this order, each cut from `main` after
  the previous one merged and deployed:
  - PR 12f-1 needs nothing unmerged. It reads `by_pair`, `UpdateStrategy`, the strategies router,
    `allocation/domain/percent.py`, `capital_pools` and `pool_balance_snapshots`, all on `main`.
  - PR 12f-2 needs PR 12f-1 **merged and deployed**: the panel refuses a `by_pair` entry that lacks
    `wins` and `win_rate`, and reads two routes (`/api/strategies/{id}/share-preview` and
    `/api/webhook-origin`) that must exist. Against an older API the amount reads "could not be
    loaded" and the host "could not be loaded"; the win rate is the one that refuses a whole report.
  - Unit 12f touches `StrategyDetailPage.tsx`, `WebhookMessage.tsx`, `AllowedPairsEditor.tsx`,
    `PairStatsTable.tsx` and both locale files. PR 13 touches the locale files too; whichever is cut
    second starts from the updated `main`.

### Safe pause points (prefixes)

Every prefix below is independently deployable and revertible; none leaves `main` in a
half-migrated state:

1. **{PR 1}** — a dev tool only, nothing shipped changes behavior.
2. **{PR 1, PR 2}** — the `/api` move alone; the owner's `curl` runbooks move.
3. **{PR 1, PR 2, PR 3}** — every venue read signs with the vault key; `.env` still holds the
   Binance read key until this is proven, then it is deleted. Credentials are hardened.
4. **{…, PR 4, PR 5}** — the money path gains the allowlist and archive; no panel yet.
5. **{…, PR 6, PR 7}** — performance read models and their endpoints exist, exercised only by
   tests; nothing renders them yet. Backend-complete for reads.
6. **{…, PR 8a, PR 8b}** — key validation, read-only/no-key refusal, and delete-with-flat-check
   are all live; still no panel UI.
7. **{…, PR 9}** — SPA serving exists; deploying it needs the owner's Cloudflare/DuckDNS steps.
8. **{…, PR 10}** — the shell is navigable with empty views.
9. **{…, PR 11, PR 12, PR 13}** — full panel. This is the change's end state.

Any of these 9 stopping points can end a session without leaving unreachable or half-wired
code on `main`.

Unit 9v (added 2026-10-02) adds its own pause points, each deployable and revertible alone:
after **12v-0** (a dev script), after **12v-1** (venue classes nothing calls), after **12v-2**
(a read endpoint no view uses), after **12v-3** (saves validated; the textarea still works and
a typo is refused), after **12v-4** (a selector nothing mounts), after **12v-5** (end state).

Unit 9x (added 2026-10-02) adds its own pause points, each deployable and revertible alone:
after **12x-1** (the webhook refuses an unregistered strategy cleanly; nothing can be deleted
yet), after **12x-2** (reads nothing calls), after **12x-3** (a use case nothing routes to),
after **12x-4** (delete works through the API), after **12x-5** (a control nothing mounts until
9d.6), after **12x-6** if it is built (a toggled test strategy becomes deletable).

Unit 12f (added 2026-10-06) adds two pause points, each deployable and revertible alone: after
**12f-1** (two more fields on each `by_pair` entry, two read-only routes and one startup line; the
older panel shows what it showed), after **12f-2** (end state; the panel is not served in production
until `PANEL_DIST_DIR` is set).

---

## PR 1 — Unit 1a: permission probe (250–400 lines)

**Goal**: a GET-only script, run by the owner on the VPS, that answers the five probe items
design decision 3 lists, before any refusal rule in `key_policy.py` is coded.

**Files**: Create `backend/scripts/check_key_permissions.py` (+ `backend/tests/scripts/test_check_key_permissions.py`).

- [x] 1a.1 RED `backend/tests/scripts/test_check_key_permissions.py::test_redaction_masks_every_apikey_and_secret_field_to_last_four` — pins the redaction rule (any field named `apiKey`/`secret`, and any string equal to the key or secret, redacted to last-4) against a fixture Bybit `query-api` payload that echoes `apiKey`.
- [x] 1a.2 RED same file `::test_announce_prints_last_four_and_source_never_the_full_value`.
- [x] 1a.3 GREEN: `check_key_permissions.py` — loads Bybit/Binance vault keys via `probe_credentials.vault_credentials`, and for last use before removal the Bybit `***Swka` and Binance `.env` read keys. **Deviation from the original task text** (binding orchestrator correction): no `--prompt`/`getpass` — the project rule is never to ask for or paste credentials; a key stored nowhere is simply absent and the item that needed it prints UNKNOWN naming what is missing. Prints `Signing as ***last4 (from the source)` before each call via the pure `format_signing_line` helper.
- [x] 1a.4 GREEN: implement the five probe items as named functions — `probe_bybit_withdraw_shape` (P1: `GET /v5/user/query-api` → `permissions.Wallet`), `probe_bybit_trade_capability` (P2: `readOnly`, `ContractTrade`, `Derivatives`), `probe_binance_restrictions` (P3: `GET /sapi/v1/account/apiRestrictions`), `probe_bybit_live_reads`/`probe_binance_live_reads` (P4: Bybit `wallet-balance UNIFIED`; Binance `GET /fapi/v3/account`, `/fapi/v3/positionRisk`, `/fapi/v1/symbolConfig` — with the VAULT key, printed explicitly per item), `probe_binding_and_expiry_bybit`/`probe_binding_and_expiry_binance` (P5: `ips`/`expiredAt`/`deadlineDay`; `ipRestrict`/`tradingAuthorityExpirationTime`).

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/scripts/test_check_key_permissions.py`.
Harness: the redaction/announce tests run with no real credential (fixture payloads only); the probe items themselves are **owner-run on the VPS**, not part of CI.
Rollback boundary: the script is a dev tool with zero importers in `src/`; deleting it reverts nothing else.
Forecast: 250–400 lines.

### PR 1 — Probe results (owner ran it on the VPS, 2026-09-25)

| Item | Bybit | Binance |
| --- | --- | --- |
| P1 withdraw shape | `permissions.Wallet` is a list of tokens; the vault key has `['AccountTransfer','SubMemberTransfer']`. No withdraw-enabled key was observed. | n/a |
| P2 trade capability field | `readOnly` (0 = can trade, 1 = read-only). The read-only key STILL lists `ContractTrade ['Order','Position']` and `Derivatives ['DerivativesTrade']`, so the permission lists do NOT reveal trade capability. | n/a |
| P3 `apiRestrictions` shape | n/a | **Unreachable**: HTTP 403 with an HTML page for both keys. `api.binance.com` is refused from the VPS, while `fapi` works. |
| P4 live reads with the vault key | wallet-balance UNIFIED OK. **PR 3 gate passes.** | account, positionRisk and symbolConfig all OK with the vault key. **PR 3 gate passes.** |
| P5 binding/expiry fields | `ips` bound (includes the VPS); `expiredAt` 1970 / `deadlineDay` −2 means no expiry. | Unreachable (same 403). |

**Consequences for PR 8a, binding (owner decision 24):**

- **Bybit 8b is FAIL-CLOSED.** A key is accepted only when `Wallet ⊆ {AccountTransfer, SubMemberTransfer}`; any other token is refused.
- **Bybit trade capability is `readOnly == 0`.** The permission lists are never used for it.
- **Binance 8b cannot be verified from the VPS.** A Binance key is saved only with an explicit owner confirmation that withdrawals are disabled. The confirmation is recorded with its timestamp, and the key is shown as "withdraw not verified".
- **Binance trade capability is also unverifiable**, because the same endpoint answers 403. How `trade_capable` is derived for Binance is to be designed in PR 8a, never assumed.
- **Never display a raw permissions payload.** It carries the owner's whitelisted IPs, userID and KYC region.

---

## PR 2 — Unit 4a: the `/api` move (550–800 lines)

**Goal**: every admin router mounts under `/api`; the frontend's `apiFetch` centralizes the
prefix. No behavior changes, only paths.

**Files**: Modify `backend/src/strategy_manager/main.py` (new `api_router = APIRouter(prefix="/api")`
wrapping `strategies_router`, `reconciliation_router`); `backend/src/strategy_manager/strategies/infrastructure/admin_token_invariant.py`
(message names `/api`); `frontend/src/shared/api/config.ts` (`API_PREFIX = "/api"`); every
frontend caller under `frontend/src/features/bookings/*`.

- [x] 4a.1 RED `backend/tests/strategies/infrastructure/test_router_auth.py::test_strategy_routes_live_under_api_prefix`.
- [x] 4a.2 RED `backend/tests/reconciliation/infrastructure/test_router.py::test_reconciliation_routes_live_under_api_prefix`. **Deviation**: no `tests/reconciliation/infrastructure/conftest.py` builds an app/client fixture — this file's own bare `_app()`/`client` fixture is local to `test_router.py` and stays untouched (every other test in the file still hits the unprefixed path against that isolated router mount, on purpose, per its own docstring). The new test builds its own `create_app()`-based transport instead.
- [x] 4a.3 RED — **deviation from the file list above**: `backend/tests/shared/infrastructure/test_admin_auth.py` and `backend/tests/shared/infrastructure/test_access_log.py` test isolated units (`AdminTokenAuth`, query-secret redaction) with no HTTP route ever called — confirmed by searching the whole test tree for literal `/strategies`/`/reconciliation` path usage, which returned only `test_router_auth.py` and `test_router.py`. Adding an `/api`-prefix assertion to either would be unrelated to what the file tests. The actual `test_smoke.py` lives at `backend/tests/test_smoke.py` (not `.../shared/infrastructure/`); `test_webhook_and_health_paths_are_never_moved_under_api` was added there instead, pinning `/health` (200), `/api/health` (404) and `POST /api/webhook/tradingview` (404) against the real `create_app()`.
- [x] 4a.4 GREEN: wrap both routers in `api_router`, mount in `main.py`; update `admin_token_invariant.py`'s startup message.
- [x] 4a.5 RED (Vitest) `frontend/src/shared/api/client.test.ts::test_apiFetch_prefixes_every_call_with_api_base_and_api_prefix`.
- [x] 4a.6 GREEN: `shared/api/config.ts` gains `API_PREFIX`; `apiFetch` builds `${API_BASE_URL}${API_PREFIX}${path}`; callers in `BookingsListView.tsx`, `ConfirmBookingDialog.tsx`, `RejectBookingDialog.tsx` keep their relative paths unchanged (`apiFetch` absorbs the prefix, per design's "smallest possible diff") — confirmed unchanged, no caller names `/api` itself.
- [x] 4a.7 GREEN: no other `client.test.ts` fixture asserted a URL before this unit (confirmed by reading the whole file) — nothing else needed updating beyond the new 4a.5 test itself.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short` + `cd frontend && npm run lint && npm test`.
Harness: `httpx.AsyncClient` over the ASGI app (backend); `vi.stubGlobal("fetch")` (frontend), no MSW.
Rollback boundary: a prefix-only change on both sides; revert restores `/strategies`, `/reconciliation` and the un-prefixed frontend calls together, same PR.
Forecast: 550–800 lines.

---

## PR 3 — Unit 1b: Binance reads onto the vault (600–900 lines)

**Gate before deploy**: PR 1's **P4** recorded with the vault Binance key succeeding on every read.

**Goal**: the five Binance read sites stop reading `.env` and load the vault key; `.env` holds
no Bybit or Binance key; the startup self-test degrades a keyless exchange instead of refusing
to start (decision 20 — this unit absorbs the "startup no longer raises" change because it is
the natural site of the Binance rewiring).

**Files**: Modify `backend/src/strategy_manager/main.py` (five sites: `756` balance refresh,
`822` venue position, `960` balance sync, `1039` reconciliation scan, `1119` booking prepare);
`backend/src/strategy_manager/worker.py` (`_assert_keys_present`); `backend/src/strategy_manager/shared/config.py`
(remove `bybit_api_key/secret`, `binance_api_key/secret`); `backend/src/strategy_manager/shared/infrastructure/bybit/factory.py`,
`binance/factory.py` (remove `credentials_from_settings`); `backend/scripts/{probe_credentials,check_bybit_read,check_binance_read,check_venue_fill_windows,measure_reconciliation_rate_limits}.py`
(load from vault, `announce()` prints `***last4 (vault)`).

- [x] 1b.1 RED `backend/tests/main/test_booking_prepare_wiring.py::test_binance_booking_prepare_signs_with_vault_key_not_settings` (design flags this exact test at `test_booking_prepare_wiring.py:61-82` as needing the assertion swap). **Path deviation**: the file actually lives at `backend/tests/shared/infrastructure/test_booking_prepare_wiring.py` (tasks.md's `tests/main/` path does not exist); swapped the existing `test_the_binance_fill_reader_uses_the_read_only_env_key` assertion in place under the new name.
- [x] 1b.2 RED four more wiring tests, one per remaining site, each named `test_binance_<site>_signs_with_vault_key` — balance refresh, venue position, balance sync, reconciliation scan. Same file, each sliced to its own nested function/block via `inspect.getsource`.
- [x] 1b.3 RED `backend/tests/test_worker.py::test_missing_key_for_enabled_pool_logs_one_error_and_still_starts` — via `caplog`, asserting `_assert_keys_present` returns the DEGRADED set and does **not** raise. **Path deviation**: real file is `backend/tests/test_worker.py` (top-level), not `tests/worker/`.
- [x] 1b.4 RED same file `::test_degraded_exchange_does_not_affect_any_other_exchange` — Binance DEGRADED, Bybit not named. **Binding correction extended this task** (orchestrator, work unit 2): also added the behavioral consequence proof at the application layer, `backend/tests/accounts/application/test_balance_sync_handler.py::test_a_degraded_exchange_omitted_from_syncs_still_lets_the_successor_enqueue` — a `CompositeBalanceSync` built with only the healthy exchange's `SyncBalances` still writes its data AND the handler still enqueues the successor (proven non-vacuous: temporarily included a raising stub for the degraded exchange, observed the successor-enqueue assertion go RED, then restored).
- [x] 1b.5 RED `backend/tests/shared/test_no_dotenv_credentials.py::test_settings_carries_no_bybit_or_binance_key_field` and `::test_grep_finds_no_production_reader_of_env_bybit_or_binance_key` (a repo-grep test, following the design's own "no Bybit/Binance `credentials_from_settings` left" line).
- [x] 1b.6 GREEN: rewire the five Binance sites onto `vault.load(BINANCE_EXCHANGE)` inside the same lazy-factory pattern Bybit already uses; remove `Settings.bybit_api_key/secret`, `binance_api_key/secret`, and both factories' `credentials_from_settings`.
- [x] 1b.7 GREEN: `_assert_keys_present(hints, pools) -> frozenset[str]` in `worker.py` — logs one ERROR per DEGRADED exchange (name + how to store a key), never raises, returns the DEGRADED set. **Binding correction (orchestrator, overrides this task's original "caller skips registering adapters at startup" wording): DEGRADED is not a startup snapshot.** `_assert_keys_present` is startup-only, seeding `build_worker_runner`'s new `initial_degraded` parameter. Every read site (balance refresh, venue position, balance sync, reconciliation scan, booking prepare) now re-checks the vault's active-key listing PER JOB via new `main._active_exchanges`/`main._track_degraded_exchanges` (a shared, process-lifetime tracker that logs an ERROR once per exchange going degraded and an INFO once per recovery, silent in steady state) — a key saved or deleted while the worker runs is seen on the next job, not only after a restart. Reconciliation-scan additionally filters the degraded exchange's pools out of the list passed to `ScanPools` (not just its reader), and booking-prepare registers a new `main._DegradedVenueFillReader` stand-in (raises the `VenueFillReadError` `PrepareBooking.sweep` already swallows per discrepancy) instead of omitting the reader — both because their consumers do NOT swallow an unregistered-pool error the way `RefreshPoolBalance`/`VenueNetPositionAdapter` do, and would otherwise kill the chain exactly like the urgent balance.sync bug this unit fixes.
- [x] 1b.8 GREEN: fold the five diagnostic/probe scripts onto `probe_credentials.vault_credentials`; each `announce()` prints `***last4 (vault)`. **Deviation (orchestrator-scoped addition)**: also folded `check_key_permissions.py`, which tasks.md's file list omitted — it imported both factories' `credentials_from_settings` (as `bybit_env_credentials`/`binance_env_credentials`) for its own ".env key, last use before PR 3 retires it" pass; that pass is now dead (the use it existed for is already recorded in "PR 1 -- Probe results") and is removed, with `tests/scripts/test_check_key_permissions.py` gaining a regression test that the module carries neither symbol.
- [x] 1b.9 RED `backend/tests/accounts/application/test_balance_sync_reloads_pools.py::test_pool_enabled_while_running_is_read_on_the_next_cycle` + `::test_pool_disabled_while_running_stops_being_read_on_the_next_cycle`, both against real Postgres, exercising `main.py`'s ACTUAL `JobKind.BALANCE_SYNC` handler (`runner._handlers[...]`) with only the venue HTTP clients faked (call-counting stand-ins). **Extended scope (orchestrator's binding map, work unit 3)**: also added `test_zero_enabled_pools_still_enqueues_the_successor` (binding requirement 5) and `test_a_lock_key_collision_in_the_reloaded_set_keeps_the_previous_pools` (binding requirement 4, `assert_pool_lock_keys_distinct` monkeypatched since a real hash collision cannot be engineered deterministically) in the same file, plus 20 unit-level tests in new `backend/tests/test_main_pool_reload.py` for `_PoolSet`, `_track_pool_changes`, `_track_degraded_exchanges`'s de-configuration cleanup, and source-inspection wiring pins per consumer.
- [x] 1b.10 GREEN, with a **binding correction to this task's own wording (orchestrator, work unit 3): a shared, mutable `_PoolSet` holder, refreshed ONLY by `handle_balance_sync`'s own ~60s cadence** (not "wherever the in-memory map is consulted" independently) — `signal.process` runs once per claimed signal, far more often than pool config ever changes, so every OTHER consumer reads the SAME shared instance instead of issuing its own `list_enabled()` query. Consumer map (every place the frozen `pools_by_key`/`configured_exchanges` locals were read, now `pool_set.by_key`/`pool_set.configured_exchanges`): `balance_refresh_reader_for` (site 1), `venue_net_position_reader_for` (site 2), `handle_balance_sync` (site 3, the reload point), `handle_reconciliation_scan` (site 4), `handle_reconciliation_prepare_booking` (site 5), `handle_signal_process`/`handle_signal_open_after_close` → `_build_process_signal_handler` (→ `PoolBalanceAdapter`, → `AllocateCapital`), and all five `_track_degraded_exchanges` call sites (`configured=`). Lock-key safety (binding requirement 4): `_reload_pools()` re-runs `assert_pool_lock_keys_distinct` on every reload; a collision keeps the previous `pool_set` and logs one ERROR (deduped against the last-reported collision, not every cycle). `_track_degraded_exchanges` gained a fourth branch: an exchange with no pool left in `configured` is dropped from the tracker silently (no "reads resume" INFO) — it did not recover, it stopped mattering. `fakes_by_exchange` (DRY_RUN) now unconditionally covers `BYBIT_EXCHANGE`/`BINANCE_EXCHANGE` on top of whatever the startup pool list names, so `tradable_pools` is exchange-complete in DRY_RUN too, matching LIVE mode's already-exchange-complete `registered` tuple (binding requirement 6). Left deliberately unrefreshed and documented as a known, non-silent gap: the STARTUP-only `unserved_pools`/`describe_unserved` sanity warning (a pool whose venue no adapter serves at all) — re-running it every cycle for a persistent misconfiguration would flood the log the same way an undeduped ERROR would, and no binding requirement asked for it.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: fakes for the per-site wiring tests; a real vault (envelope decrypt) for the "does not decrypt when it shouldn't" boundary is not relevant here — that's PR 8a's structural test. This unit's harness is fakes + real vault decrypt.
Rollback boundary: the five `main.py` call sites and `worker.py`'s check; revert restores single-key `.env` reads **provided the Binance read key is still in `.env`** (kept until this PR is proven in production, per the deploy runbook below).
Forecast: 600–900 lines.

**Deploy runbook** (owner-run):
1. Confirm PR 1's P4 gate is recorded.
2. Deploy code; restart worker and API.
3. Watch the worker log: vault self-test opens Bybit and Binance; a missing key for an
   enabled-pool exchange logs one ERROR by name (reaching Telegram) and the worker still
   starts and accepts jobs.
4. Watch one `balance.sync` cycle for the Binance pool succeed.
5. Only after step 4 is proven: delete `BYBIT_API_KEY/SECRET` and `BINANCE_API_KEY/SECRET`
   from `.env`. Do **not** store the `.env` Binance read key in the vault — under
   one-active-per-exchange it would supersede the trade key and make Binance read-only.

---

## PR 4 — Units 2a + 2d + 2e: lifecycle schema, enablement log, pairs endpoints (2,100–2,850 lines)

**Gate before PR 5 deploys**: the owner reviews the 0024-seeded allowed pairs through
`GET /api/strategies` and prunes with `PUT .../allowed-pairs` (this is Q1's resolution).

### Unit 2a — schema, ORM, VOs, seeding (900–1,200 lines)

**Files**: Create `backend/migrations/versions/0024_strategy_lifecycle.py`; Create
`backend/src/strategy_manager/strategies/domain/allowed_pairs.py`, `enablement.py`; Modify
`backend/src/strategy_manager/strategies/domain/strategy.py`; Modify
`backend/src/strategy_manager/strategies/infrastructure/models.py`; Modify
`backend/src/strategy_manager/execution/domain/market_symbol.py` (receives `market_key()`,
moved from `strip_contract_marker`'s module); Modify
`backend/src/strategy_manager/reconciliation/application/market_key.py` (becomes a re-export).

- [x] 2a.1 RED `backend/tests/execution/domain/test_market_symbol.py::test_market_key_moved_reconciliation_reexport_still_works` — imports `reconciliation/application/market_key.py`'s `market_key` and asserts identity with `execution/domain/market_symbol.py`'s.
- [x] 2a.2 RED `backend/tests/strategies/domain/test_allowed_pairs.py::test_allowed_pairs_rejects_empty_string_entry`, `::test_allowed_pairs_rejects_lowercase_entry`, `::test_allowed_pairs_stores_sorted`.
- [x] 2a.3 RED `backend/tests/migrations/test_0024_strategy_lifecycle.py::test_seeding_uses_distinct_market_key_normalized_symbols_from_signals` — strategy with prior signals spelled `ETHUSDT` and `ETHUSDT.P` (same canonical pair) plus `SOLUSDT`; asserts seeded set `{ETHUSDT, SOLUSDT}` and a WARNING log line naming the strategy and the seeded set.
- [x] 2a.4 RED same file `::test_strategy_with_no_signals_seeded_empty`.
- [x] 2a.5 RED same file `::test_seeding_uses_a_frozen_normalization_copy_not_application_import` — asserts the migration module imports no `strategy_manager.execution` code (migrations must not import application code that can change later). Deviation: checks only actual `import`/`from` statement lines, not the whole file text, so the docstring may still name the real module in prose explaining the deliberate omission.
- [x] 2a.6 RED same file `::test_archived_at_check_constraint_refuses_archived_and_enabled`, `::test_enablement_events_table_and_index_created`, `::test_append_only_trigger_refuses_update`, `::test_append_only_trigger_refuses_delete`, `::test_no_truncate_trigger_exists` (the deliberate omission — eight integration conftests `TRUNCATE ... CASCADE`).
- [x] 2a.7 RED same file `::test_baseline_event_written_for_every_currently_enabled_strategy_at_migration_time`.
- [x] 2a.8 RED same file `::test_downgrade_refuses_while_any_observed_event_exists_naming_count`.
- [x] 2a.9 GREEN: `allowed_pairs.py` (`AllowedPairs(frozenset[str])`, asserts non-empty entries, upper-case, no whitespace), `strategy.py` (`archived_at` field). Deviation (review correction 2026-09-25): `enablement.py` (`EnablementEvent`, `EnablementOrigin`, `uptime(events, now)`) MOVED OUT of this unit — it shipped without a RED test, which breaks strict TDD. It now belongs to unit 2d, written test-first there, driven by 2d.5's `test_enablement.py`. Migration 0024 still writes the BASELINE/OBSERVED rows that future function will read; nothing in this unit imports `enablement.py`.
- [x] 2a.10 GREEN: `execution/domain/market_symbol.py` gains `market_key()`; `reconciliation/application/market_key.py` re-exports it; every existing import path verified unchanged.
- [x] 2a.11 GREEN: `migrations/versions/0024_strategy_lifecycle.py` — `strategies.allowed_pairs TEXT[] NOT NULL DEFAULT '{}'` + `CHECK (array_position(allowed_pairs, NULL) IS NULL)`; `archived_at timestamptz NULL` + `CHECK (archived_at IS NULL OR enabled = false)`; `strategy_enablement_events` table + `(strategy_id, occurred_at)` index + `fn_strategy_enablement_events_append_only` trigger (UPDATE/DELETE only, no TRUNCATE guard); seeding loop over `DISTINCT strategy_id, symbol FROM signals`; BASELINE event insert for every currently-enabled strategy; downgrade refusal counting OBSERVED rows. Plus two orchestrator-required additions: a frozen-copy/`market_key()` parity test and an unparseable-symbol (empty string) skip-with-WARNING path.
- [x] 2a.12 GREEN: ORM columns on `strategies/infrastructure/models.py`.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/migrations/test_0024_strategy_lifecycle.py backend/tests/strategies/domain/ backend/tests/execution/domain/test_market_symbol.py`.
Harness: real PostgreSQL (`rules.tasks`: advisory-lock and trigger behavior have no meaningful fake), Tier B up/down/refusal.
Rollback boundary: `migrations/versions/0024_*.py` + the new domain files; downgrade refuses while any OBSERVED event exists (0012/0021 precedent — BASELINE rows carry no information the migration did not create, so a downgrade with only BASELINE rows is allowed).
Forecast: 900–1,200 lines.

### Unit 2d — enablement log wiring + uptime query (600–850 lines)

**Files**: Modify `backend/src/strategy_manager/strategies/application/update_strategy.py`,
`register_strategy.py`; Create `backend/src/strategy_manager/strategies/infrastructure/enablement_log.py`.

- [x] 2d.1 RED `backend/tests/strategies/application/test_update_strategy.py::test_toggling_enabled_twice_writes_two_events_same_transaction_as_enabled_write`.
- [x] 2d.2 RED same file `::test_noop_patch_setting_enabled_true_again_writes_no_event`.
- [x] 2d.3 RED `backend/tests/strategies/infrastructure/test_update_strategy_concurrency.py::test_update_strategy_takes_for_update_lock_on_strategy_row` (two concurrent toggles must not both read `false` and both append an "enabled" event). Deviation: lives under `tests/strategies/infrastructure/`, not `application/`, to reuse that directory's real-Postgres fixtures — the same convention `AllocateCapital`'s own concurrency tests already follow (`tests/allocation/infrastructure/test_concurrency_race.py`).
- [x] 2d.4 RED `backend/tests/strategies/application/test_register_strategy.py::test_creation_writes_no_event_and_first_enable_writes_the_first_one` (F8 — POST cannot create enabled; this replaces the withdrawn "creating enabled writes the first event" scenario).
- [x] 2d.5 RED `backend/tests/strategies/domain/test_enablement.py::test_uptime_sums_closed_and_open_intervals`, `::test_never_enabled_strategy_has_zero_uptime_no_activation_date`, `::test_uptime_ignores_repeated_same_state_events_defensively`, `::test_uptime_baseline_flag_renders_as_active_at_least_x_days`. `enablement.py` written test-first here, as corrected.
- [x] Orchestrator addition: atomicity — `test_event_append_failure_rolls_back_the_enabled_write_too` (same concurrency test file), proving the event write and the `enabled` write commit or roll back together.
- [x] 2d.6 GREEN: `SqlAlchemyEnablementLog`, `StrategyEnablementEventRow`; `UpdateStrategy` gains `ClockPort` and `SELECT ... FOR UPDATE` (via new port method `get_by_id_for_update`), appends an event only when `enabled` actually changes, in the same transaction, before commit; `RegisterStrategy` appends defensively if `enabled` is ever true (dead code path today, kept for safety per F8, `# pragma: no cover`). `router.py` wired to both with `SqlAlchemyEnablementLog`/`SystemClock`.
- [x] 2d.7 GREEN: `uptime(events, now)` pure function in `enablement.py`.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/strategies/`.
Harness: real PostgreSQL for the FOR-UPDATE race test; pure for `uptime()`.
Rollback boundary: `enablement_log.py` + the two modified use cases; revert stops writing events, existing rows are untouched.
Forecast: 600–850 lines.

### Unit 2e — pairs endpoints, POST requires pairs, list filter, view fields, events GET (600–800 lines)

**Files**: Modify `backend/src/strategy_manager/strategies/infrastructure/router.py`,
`repository.py`; Modify `backend/src/strategy_manager/strategies/application/ports.py`; Create
`backend/src/strategy_manager/strategies/application/replace_allowed_pairs.py`.

- [x] 2e.1 RED `backend/tests/strategies/application/test_register_strategy.py::test_creating_with_empty_allowed_pairs_is_refused`, `::test_creating_with_at_least_one_pair_succeeds`. RED via a deliberately-wrong `RegisterStrategy.register()` stub (accepted `allowed_pairs` but ignored it), not a constructor `TypeError`.
- [x] 2e.2 RED `backend/tests/strategies/application/test_replace_allowed_pairs.py::test_replace_pairs_normalizes_via_market_key`, `::test_replace_pairs_with_empty_list_refused`. Plus 3 more in the same file (duplicate collapse, normalizes-to-empty refusal, unknown strategy). RED via a deliberately-wrong `ReplaceAllowedPairs.replace()` stub (uppercased raw input, no `market_key()`, no empty checks).
- [x] 2e.3 RED `backend/tests/strategies/infrastructure/test_router.py::test_get_strategies_excludes_archived_by_default`, `::test_get_strategies_include_archived_true_shows_archived`, `::test_get_strategy_detail_by_id_always_loads_archived`, `::test_put_allowed_pairs_endpoint`, `::test_post_strategies_requires_min_one_pair_422`, `::test_get_strategy_events_endpoint`. Plus 6 more (binding additions: duplicate-collapse, empty-list 422, normalizes-to-empty 422, PUT unknown 404, GET events unknown 404, uptime on detail+list). RED via real HTTP status-code mismatches against the pre-2e router (404s for missing routes, 200 where 422 expected). 3 tests that passed vacuously against the old router (`include_archived=true`, both unknown-404 tests) were proven non-vacuous by breaking the real implementation post-GREEN and watching them fail, then restoring.
- [x] 2e.4 GREEN: `ReplaceAllowedPairs` use case; `POST /strategies` requires `allowed_pairs: [str] (min 1)`; `PUT /strategies/{id}/allowed-pairs`; `GET /strategies?include_archived=false`; `GET /strategies/{id}/events`; `StrategyView` gains `archived_at|null`, `allowed_pairs` (sorted), `uptime: {seconds, first_enabled_at|null, baseline}`. `Strategy` domain gained an `allowed_pairs: AllowedPairs` field and `archived_at` was wired through the repository (both were previously unwired — necessary completion of unit 2a's domain shape, in scope here since 2e is the first unit to actually read/write them end-to-end). Owner correction (2026-09-25): `ReplaceAllowedPairs` reads through `get_by_id_for_update` (the same row lock `UpdateStrategy` takes) instead of a plain `get_by_id` — without it, a concurrent PUT allowed-pairs and PATCH enabled could interleave and silently revert the PATCH's change, since `repository.update()` writes every mutable field including `enabled`. Proven RED first on real Postgres with the deterministic lock-hold harness from `test_update_strategy_concurrency.py` (`test_replace_allowed_pairs_and_update_strategy_serialize_on_the_same_row_lock`): against the plain `get_by_id`, a concurrent PATCH completed without blocking; after the fix, it genuinely blocks until the PUT commits, and the final row has the new pairs, `enabled=true`, and exactly one OBSERVED event.
- [x] 2e.5 GREEN: `list_all(include_archived)` on the repository. List endpoint loads events with ONE bulk query (`SqlAlchemyEnablementLog.list_for_many`), matching design.md § 14's "one events query" wording — not one query per strategy.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/strategies/infrastructure/`.
Harness: real PostgreSQL, `httpx.AsyncClient`.
Rollback boundary: new router methods only; revert 404s the new paths, existing strategy CRUD untouched.
Forecast: 600–800 lines.

---

## PR 5 — Units 2b + 2c: allowlist/archived refusals, archive, concurrency (1,800–2,500 lines)

**Gate before deploy**: PR 4's seeded pairs are pruned by the owner (Q1).

### Unit 2b — allowlist and archived refusals, opens only (700–1,000 lines)

**Files**: Modify `backend/src/strategy_manager/signals/application/process_signal.py`;
Modify `backend/src/strategy_manager/allocation/application/ports.py` (`StrategyPolicySnapshot.archived`, `.allowed_pairs`).

- [x] 2b.1 RED `backend/tests/signals/application/test_process_signal.py::test_listed_pair_proceeds_normally`.
- [x] 2b.2 RED same file `::test_unlisted_pair_opening_signal_refused_before_lock_no_reservation_one_warning`.
- [x] 2b.3 RED same file `::test_close_on_pair_removed_from_list_still_closes_with_one_warning`.
- [x] 2b.4 RED same file `::test_reverse_on_unlisted_pair_closes_then_refuses_open_ends_flat`.
- [x] 2b.5 RED same file `::test_spelling_variant_ethusdt_dot_p_matches_allowed_pair_ethusdt` (spelling rule: allowed pair stored as `ETHUSDT`, signal spelled `ETHUSDT.P`). Deviation: also covers the Pionex `_PERP` form in the same test (orchestrator addition), looping both spellings against the same stored `ETHUSDT` pair.
- [x] 2b.6 RED same file `::test_archived_strategy_signal_refused_before_untradable_pool_check_one_warning` — WARNING text asserted verbatim: "signal `<id>` for ARCHIVED strategy `<name>` (`<id>`) refused; remove its TradingView alert".
- [x] 2b.7 RED same file `::test_archived_strategy_refusal_also_applies_in_open_now_continuation`.
- [x] 2b.8 RED `backend/tests/signals/application/test_ingest_signal.py::test_archived_strategy_webhook_persists_signal_unchanged_no_lookup_added` — asserts no strategy lookup at ingress. Deviation: the file lives under `signals/application/`, not `signals/infrastructure/` as written (that is where `IngestSignal`'s own unit tests already live; no `signals/infrastructure/test_ingest_signal.py` exists).
- [x] 2b.9 GREEN: `_refuse_unlisted_pair` and the archived-strategy refusal at the top of `handle()`/`_handle_consumes` (archived check first — "whatever its pool" — then unlisted-pair, per design's ordering); each refusal logs exactly one WARNING and never calls `allocate`.
- [x] 2b.10 GREEN: `StrategyPolicySnapshot.archived`, `.allowed_pairs` fields threaded through `policy_adapter.py`. Deviation: also added `StrategyPolicySnapshot.name` (default `""`), threaded from `Strategy.name` — the verbatim archived-strategy WARNING text required by 2b.6 names the strategy, and no other field on the snapshot carries it. Both new fields default (`archived=False`, `allowed_pairs=frozenset()`) so every pre-2b caller (`AllocateCapital`'s tests, unit 2c's in-lock re-check) keeps constructing the DTO unchanged.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/signals/`.
Harness: fakes for every port.
Rollback boundary: two named refusal methods in `process_signal.py`; revert removes both, signals flow as today.
Forecast: 700–1,000 lines.

Deviation (undeclared blast radius): the new allowlist gate refused two PRE-EXISTING live-Postgres
integration tests that open a real position through a real, DB-seeded strategy without ever naming
an allowed pair (`test_open_after_close_integration.py`, `test_open_now_concurrent_redelivery.py`) —
their shared `seed_strategy` helper (`backend/tests/signals/infrastructure/conftest.py`) always left
`allowed_pairs` at the DB's `'{}'` default. Fixed by adding an optional `allowed_pairs` parameter to
that helper (defaulting to the prior empty-array behaviour) and passing `frozenset({"STXUSDT"})` at
both call sites — the `market_key()` both scenarios' three symbol spellings already normalize to. A
full-suite run (1654 tests, up from the 1643 baseline by the 11 tests this unit adds) confirmed no
other integration test elsewhere in the tree was affected.

### Unit 2c — `ArchiveStrategy`, exposure adapter, pool lock, in-lock re-check, concurrency (1,100–1,500 lines)

**Files**: Create `backend/src/strategy_manager/strategies/application/archive_strategy.py`;
Create `backend/src/strategy_manager/strategies/infrastructure/{exposure_adapter,pool_lock_adapter}.py`;
Modify `backend/src/strategy_manager/allocation/application/allocate_capital.py`; Modify
`backend/src/strategy_manager/strategies/infrastructure/router.py`.

- [x] 2c.1 RED `backend/tests/strategies/application/test_archive_strategy_integration.py::test_archiving_disabled_flat_strategy_succeeds`.
- [x] 2c.2 RED same file `::test_archiving_enabled_strategy_refused_409_still_enabled`. Also asserts the raised type is exactly `StillEnabled`, never `IntegrityError` (binding 3).
- [x] 2c.3 RED same file `::test_archiving_disabled_strategy_with_open_position_refused_409_names_symbols`. Deviation (addition): also added `test_archiving_refuses_on_an_unlisted_delisted_pair_too` (decision 15's delisted-pair case) and `test_live_reservation_with_no_fill_yet_still_refuses_archive` (live-reservation-only exposure, no ledger fill).
- [x] 2c.4 RED same file `::test_dust_that_close_position_reports_not_closable_keeps_ledger_net_nonzero_archive_refuses`.
- [x] 2c.5 RED same file `::test_archive_is_idempotent_same_archived_at_on_second_call`. Also added `test_archive_unknown_strategy_raises` (404 path).
- [x] 2c.6 RED same file `::test_archived_strategy_patch_refused_409_strategy_archived`, `::test_archived_strategy_pairs_put_refused_409_strategy_archived`.
- [x] 2c.7 RED same file `::test_enabling_archived_strategy_refused_enabled_unchanged`.
- [x] 2c.8 RED `backend/tests/strategies/application/test_archive_vs_allocate_concurrency.py::test_allocation_wins_lock_first_archive_then_refused_sees_live_reservation` — **live PostgreSQL, both orderings**.
- [x] 2c.9 RED same file `::test_archive_wins_lock_first_allocation_in_lock_reread_sees_archived_skips_no_reservation`.
- [x] 2c.10 RED `backend/tests/allocation/application/test_allocate_capital.py::test_in_lock_reread_skips_with_strategy_disabled_when_disabled_after_prelock_read`, `::test_in_lock_reread_skips_with_strategy_archived_when_archived_after_prelock_read`. Both assert the in-lock skip's exactly-one WARNING via `caplog` (binding 4).
- [x] 2c.11 GREEN: `ArchiveStrategy.archive(id)` — `SELECT ... FOR UPDATE`, idempotent if already archived, 409 `STILL_ENABLED`, `pg_advisory_xact_lock(LockKey(pool))`, `StrategyExposurePort.exposure` (ledger net ≠ 0 per allocation across every allocation — the multiplicity lesson — live reservations, SUBMITTED attempts), 409 `OPEN_POSITION` naming symbols/allocations/live_reservations/in_flight_attempts, else `archived_at = now`. Also added `backend/tests/strategies/application/test_archive_strategy_integration.py::test_two_allocations_same_symbol_offsetting_nets_both_still_flagged_open` (offsetting +/- nets on the same market) as the discriminating multiplicity proof — see apply-progress report.
- [x] 2c.12 GREEN: `StrategyExposureAdapter` (composes `ReadSymbolHoldings`, reservations, attempts, following the `InFlightWorkAdapter` precedent), `PoolLockAdapter`. Deviation: `StrategyExposureAdapter` also needed one new ledger-repository method, `distinct_symbols_for_strategy` (`ledger/application/ports.py` + `ledger/infrastructure/repository.py`), plus two new strategy-wide repository methods, `SqlAlchemyReservationRepository.live_for_strategy` and `SqlAlchemyExecutionAttemptRepository.submitted_for_strategy` — `ReadSymbolHoldings` alone can only answer per-market, and exposure must enumerate every market a strategy has ever touched (decision 15).
- [x] 2c.13 GREEN: `AllocateCapital` re-reads policy right after `acquire`, before the balance read; skips with `STRATEGY_DISABLED`/`STRATEGY_ARCHIVED`, logging exactly one WARNING naming the signal and strategy (binding 4).
- [x] 2c.14 GREEN: `POST /api/strategies/{id}/archive` endpoint; PATCH and pairs-PUT refuse 409 `STRATEGY_ARCHIVED` for an archived strategy. Deviation (addition): router-level RED/GREEN coverage added in `backend/tests/strategies/infrastructure/test_router.py` (archive happy path, idempotency, STILL_ENABLED, 404, OPEN_POSITION body shape, PATCH/PUT STRATEGY_ARCHIVED at the HTTP layer) — this caught and fixed a real bug: `HTTPException.detail` with raw `UUID` values raises `TypeError` at response-render time (Starlette uses plain `json.dumps`, not `jsonable_encoder`), fixed by stringifying every id in the `OPEN_POSITION` body.
- [x] 2c.15 (post-review addition) RED/GREEN: fixed a reviewer-found reachable deadlock — `ArchiveStrategy` took the strategy row's `FOR UPDATE` lock before the pool's advisory lock, the opposite order `AllocateCapital`'s own advisory lock + its reservation INSERT's implicit `FOR KEY SHARE` row lock impose, so a concurrent disable-then-archive racing an in-flight allocation could deadlock (Postgres aborts one side with `DeadlockDetected`). RED: `backend/tests/strategies/application/test_archive_vs_allocate_concurrency.py::test_archive_takes_pool_lock_before_row_lock_no_deadlock_with_inflight_allocation`, reproduced a genuine `DeadlockDetectedError` against the original order (recorded verbatim in the apply-progress report). GREEN: `ArchiveStrategy.archive` now reads the strategy unlocked first (pool is immutable, so this is safe), takes the pool advisory lock, THEN the row `FOR UPDATE` lock, and re-reads everything it decides on (`enabled`, `archived_at`) from that locked read; 404 comes only from the unlocked read.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/strategies/ backend/tests/allocation/`.
Harness: **real PostgreSQL, live concurrency test** (`rules.tasks`: advisory locks have no meaningful fake) — both lock-win orderings proven.
Rollback boundary: `archive_strategy.py`, the two new infra adapters, and the in-lock re-check in `allocate_capital.py`; revert removes archive entirely, `AllocateCapital` returns to its pre-check shape. `DB CHECK (archived_at IS NULL OR enabled = false)` was already added in 2a and stays.
Forecast: 1,100–1,500 lines.

### Unit 2f — a log line on every silent signal path (150–250 lines)

Added 2026-09-28 by owner decision 25. A read-only map of every terminal signal path found
five that end with no log line at all. This unit gives each one a log line, and nothing else:
no schema, no status write. Recording the outcome in the database is PR 5b and PR 5c.

**Files**: Modify `backend/src/strategy_manager/signals/application/process_signal.py`,
`allocation/application/allocate_capital.py`, `execution/application/place_order.py`,
`execution/application/settle_execution.py`.

- [x] 2f.1 RED `AllocateCapital` SKIP, which `process_signal.py` drops at `result.reservation_id is None`. Assert one log line naming the signal, the strategy and the skip reason, for the pre-lock `STRATEGY_DISABLED` skip and for each `decide()` skip (`NO_AVAILABILITY`, `INSUFFICIENT_AVAILABILITY`, `REQUEST_BELOW_MIN_ORDER_SIZE`). The in-lock skip from 2c already logs; do not log it twice. Four RED tests, one per skip reason, `test_allocate_capital.py`.
- [x] 2f.2 RED `PlaceOrder` `ABORTED_EXPIRED`: the reservation expired before submit. Assert one log line naming the reservation.
- [x] 2f.3 RED `PlaceOrder` `FAILED` on a venue `ExchangeError` at submit. Assert one ERROR naming the reservation, the symbol and the venue's error. It is an ERROR so it reaches Telegram, because an order the venue rejected is a trade that did not happen.
- [x] 2f.4 RED `SettleExecution` FILLED and NEVER_PLACED. Assert one INFO for FILLED, and one WARNING for NEVER_PLACED naming the attempt.
- [x] 2f.5 GREEN: the log lines. Where one call site already logs the same fact, log in exactly one place. Deviation: `process_signal.py` was NOT modified — every log line was placed in the class that already owns the fact and already discards it today (`AllocateCapital.allocate`'s two SKIP branches; `PlaceOrder.place`'s `ABORTED_EXPIRED` and `ExchangeError` branches; `SettleExecution.settle`'s FILLED path and `_release_never_placed`'s NEVER_PLACED path), never at the `process_signal.py` call sites that merely drop the already-discarded result. This keeps ownership consistent with 2c's own in-lock WARNING, which logs where the fact is decided, not where it is read.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: fakes and caplog. Each test asserts exactly one record at the stated level.
Rollback boundary: log lines only.
Forecast: 150–250 lines.

---

## Signal outcome map (decision 25; the input to PR 5b and PR 5c)

Read-only mapping of the code at 17681ef (2026-09-28). `signals.status` is written `ACCEPTED`
at ingest (`ingest_signal.py`) and never changes. The CHECK in `0002_signals.py` already allows
`ACCEPTED`, `PROCESSING`, `PROCESSED` and `REJECTED`. `main.py::handle_signal_process`
discards `ProcessSignalResult`, and the job ends `DONE` whether the signal executed or was
refused. Line numbers are those of 17681ef; re-check them before editing.

| # | Where | Kind | Final in which job | Reason code |
|---|---|---|---|---|
| 1 | `process_signal.py` `_refuse_untradable_pool` | refusal | signal.process | `UNTRADABLE_POOL` |
| 2 | `process_signal.py` `_refuse_archived_strategy` (`handle`, `open_now`) | refusal | signal.process or continuation | `STRATEGY_ARCHIVED` |
| 3 | `process_signal.py` `_refuse_unlisted_pair` | refusal, opens only | signal.process or continuation | `PAIR_NOT_ALLOWED` |
| 4 | `holding_guard.py` `_classify_divergence` GHOST / AMBIGUOUS | refusal | signal.process | `DIVERGENT_HOLDING_GHOST` / `_AMBIGUOUS` |
| 5 | `holding_guard.py` `_on_in_flight`, past the age bound | refusal | signal.process | `IN_FLIGHT_TIMEOUT` |
| 6 | `process_signal.py` balance refresh UNAVAILABLE | refusal (logs ERROR) | signal.process | `BALANCE_UNAVAILABLE` |
| 7 | `process_signal.py` `_refuse_non_positive_request` | refusal | signal.process | `NOTHING_TO_ALLOCATE` |
| 8 | `allocate_capital.py` SKIP: pre-lock, in-lock, and `decide()` | skip | signal.process | the existing `skip_reason` value (`STRATEGY_DISABLED`, `STRATEGY_ARCHIVED`, `NO_AVAILABILITY`, `INSUFFICIENT_AVAILABILITY`, `REQUEST_BELOW_MIN_ORDER_SIZE`, `PARTIAL_BELOW_MIN_ORDER_SIZE`) |
| 9 | `place_order.py` `ABORTED_EXPIRED` | definitive | signal.process | `RESERVATION_EXPIRED_BEFORE_SUBMIT` |
| 10 | `place_order.py` `REFUSED` (`OrderNotPlaceable`) | definitive | signal.process | `ORDER_NOT_PLACEABLE` |
| 11 | `place_order.py` `FAILED` (venue `ExchangeError`) | definitive | signal.process | `ORDER_REJECTED_BY_VENUE` |
| 12 | `place_order.py` `PLACED` | NOT final: schedules settle | → PROCESSING | — |
| 13 | `close_position.py` `NOT_CLOSABLE` (dust) | definitive | signal.process | `CLOSE_DUST_NOT_CLOSABLE` |
| 14 | `close_position.py` `FAILED` | definitive | signal.process | `CLOSE_REJECTED_BY_VENUE` |
| 15 | `close_position.py` `PLACED` | NOT final: schedules settle | → PROCESSING | — |
| 16 | `settle_execution.py` FILLED | terminal | execution.settle | → PROCESSED |
| 17 | `settle_execution.py` `_release_never_placed` | terminal | execution.settle | `ORDER_NEVER_REACHED_EXCHANGE` |
| 18 | `process_signal.py` `_note_unexecuted_tail` | annotation on a REVERSE's open half | — | none of its own |
| 19 | duplicate delivery, `ingest_signal.py` `inserted=False` | no-op at ingress | — | none: same row, no second outcome |
| 20 | idempotent close replay (existing close not FAILED) | re-reports a prior close | — | never overwrites a recorded outcome |

**Deferrals.** Two `_handle_consumes` branches hand the open to the `signal.open_after_close`
continuation: in-flight work not yet timed out, and a REAL orphan closed by `CloseOrphans`.
The `signal.process` job ends `DONE` with the signal undecided. The continuation
(`open_after_close.py` `poll`, its own job and session) either calls `open_now` and lands on
rows 2–15, or abandons: signal deleted, superseded by a newer signal, an awaited close FAILED,
or timed out. Today the abandonments log but write nothing to `signals`.

**Exceptions.** No `try/except` in `process_signal.py`, `handle_signal_process` or
`handle_execution_settle`: errors reach `WorkerRunner.run_once`, and `queue.fail()` retries,
then marks the job `FAILED`, with `jobs.last_error`. `queue.fail()` is job-kind-agnostic and has
no `signal_id` in scope. The raising paths include `UnknownStrategyError`, `UnknownPoolError`,
`NothingRecordedYet` (close before the open's fills settle) and `NotSettledYet`.

**Transactions.** One `signal.process` run uses one session but several commits:
`AllocateCapital` commits once, `PlaceOrder` up to four times, `ClosePosition` three times, and
the handler once more at the end. A status write is atomic with an outcome only when staged
on that session immediately before the commit that makes the outcome durable. Venue calls run
outside any transaction. Writing `PROCESSED` from the handler's trailing commit when
`PlaceOrder` returns `PLACED` would be WRONG: the order is only submitted, and its fate is
known in `execution.settle`.

**Close linkage.** `SettleExecution` sees `attempt_id` and `allocation_id`. For an open,
`reservation.signal_id` gives the signal. For a close, `allocation_id` is the OPENING
allocation, so its reservation names the opening signal, not the closing one. A close attempt
carries no link to its own signal today.

---

## PR 5b — Signal outcomes decided inside signal.process (900–1,300 lines)

Decision 25. Records the outcome of every path in the map that is decided inside the
`signal.process` job (rows 1–15, and the deferrals as `PROCESSING`). Migration **0025**.

**Rules** (binding for 5b and 5c):
- Status machine: `ACCEPTED → PROCESSING → PROCESSED | REJECTED`, or `ACCEPTED → PROCESSED |
  REJECTED` directly. `PROCESSED` and `REJECTED` are terminal and never overwritten; a
  write against a terminal signal is a no-op and logs a WARNING if the new outcome differs.
- Each outcome write is staged on the same session immediately before the commit that makes
  that outcome durable (the reservation mark, the attempt write, the fills write). Never a
  separate, later transaction.
- A submitted order is `PROCESSING`, never `PROCESSED`.
- A `REJECTED` outcome stores a stable reason code (the table above) and the human message
  already logged for it.
- Signals received before 0025 stay `ACCEPTED`; nothing is reconstructed.

- [x] 5b.1 Design addendum in design.md: the status machine, the reason-code table, the same-commit rule, and the REVERSE rule. Proposed REVERSE rule: the close half moves the signal to `PROCESSING`, and the open half decides the final status. If the open is refused after the close executed, the signal is `REJECTED` with the open's reason, and the detail says the close executed. The owner confirms the REVERSE rule before 5b.4. — Confirmed 2026-09-28 as decision 26; the alternative (`PROCESSED` whenever something executed) was declined.
- [x] 5b.2 RED `backend/tests/migrations/test_0025_signal_outcomes.py`: `signals.outcome_reason TEXT NULL`, `outcome_detail TEXT NULL`, `decided_at timestamptz NULL`; CHECK `status <> 'REJECTED' OR outcome_reason IS NOT NULL`; CHECK `status NOT IN ('PROCESSED','REJECTED') OR decided_at IS NOT NULL`; `execution_attempts.signal_id UUID NULL` with an FK to `signals` (filled from 5c, NULL for history); downgrade refuses while any signal is not `ACCEPTED` or any attempt carries a `signal_id`, naming the counts. Confirmed RED by temporarily disabling the migration file: 8/11 tests failed on real assertions/DB errors (undefined column, "DID NOT RAISE IntegrityError"), 3 passed (the tests that don't touch the new columns).
- [x] 5b.3 GREEN: migration 0025, ORM columns (`SignalRow.outcome_reason/outcome_detail/decided_at`, `ExecutionAttemptRow.signal_id`), a `SignalOutcome` value object (`signals/domain/outcome.py`, invariant enforced in `__post_init__` ahead of the CHECK) and `SignalOutcomePort.record(signal_id, outcome)` (`signals/application/ports.py`), implemented by `SqlAlchemySignalOutcomeAdapter` (`signals/infrastructure/outcome_repository.py`, a new adapter separate from `SqlAlchemySignalRepository` so no existing `SqlAlchemySignalRepository(session)` call site needed a clock param), with the terminal-state guard. All 11 migration tests and 8 adapter tests green; full gate green (1713 passed). *Correction (Unit A of the 5b.4/5b.5 batch):* the guard's read is now fresh and locked (`populate_existing=True, with_for_update=True`); the original plain `session.get` read a stale identity-map row. Two real-PostgreSQL tests added (stale identity map; lock-hold `not task.done()`).
- [x] 5b.4 RED refusals, rows 1–7: each ends `REJECTED` with its code and message. At least one runs on real Postgres; the rest use fakes. Done: `ProcessSignalHandler._reject` stages `SignalOutcomePort.record` and commits (rows 1–7 had no commit of their own, so each gets one at the refusal); `GuardOutcome.reason` carries rows 4–5's code (`DIVERGENT_HOLDING_GHOST`/`_AMBIGUOUS`, `IN_FLIGHT_TIMEOUT`). Decision 26: the open half of a REVERSE refused in `open_now` (close already executed) keeps the open's code and its detail appends that the close executed; `handle()` and non-REVERSE `open_now` never say so. Tests: `tests/signals/application/test_process_signal_outcomes.py` (fakes, 11), `tests/signals/infrastructure/test_refusal_outcomes_integration.py` (real Postgres). The REVERSE detail is driven through `open_now` directly, without 5c wiring.
- [x] 5b.5 RED skips, row 8: `REJECTED` with the existing `skip_reason` value; the in-lock skip too. Done: `AllocateCapital` gained the consumer-side `SkipRecorderPort` (adapter `signals/infrastructure/skip_recorder.py`, so `allocation` never imports `signals`); the pre-lock `STRATEGY_DISABLED` skip got its own added commit, the in-lock and `decide()` skips stage before their existing commits. Detail is the exact message already logged. Tests: `tests/allocation/application/test_allocate_capital_skip_outcomes.py` plus two real-Postgres cases in the integration file above. Wired in `main.py::_build_process_signal_handler` (the only composition root).
**Split, 2026-09-28 (owner, auto-chain).** PR 5b ships 5b.1–5b.5 alone: the branch had reached
~2,430 authored lines against a 900–1,300 forecast, with 5b.6–5b.10 still open. The cut leaves
no wrong state: a placed order's signal simply stays `ACCEPTED` until PR 5b2 lands. Tasks
5b.6–5b.10 move to **PR 5b2**, a new branch cut from `main` after PR 5b merges, keeping their
IDs. The Gate, Harness and Rollback lines below apply to both PRs; the Deploy line (0025) is
PR 5b's only.

### PR 5b2 — PlaceOrder, ClosePosition, deferrals, replays (tasks 5b.6–5b.10)

- [x] 5b.6 RED `PlaceOrder`, rows 9–12: expired, refused and venue-rejected end `REJECTED`; `PLACED` ends `PROCESSING`. Atomicity test: inject a failing commit and assert that the status and the reservation mark land together or not at all. Done (unit C, gate green): `PlaceOrder` takes the consumer-side `OrderOutcomeRecorderPort` (adapter `signals/infrastructure/order_outcome_recorder.py`; `execution` never imports `signals`) and reaches the signal through `ReservationSnapshot.signal_id` (new field). Row 9 and row 10 stage on their release commit, row 11 on the post-network release+`mark_failed` commit, row 12 (`PROCESSING`, never `PROCESSED`) on the `mark_placed` commit, not the pre-network SUBMITTED one. `outcome_detail` is the exact logged message (built once, recorded, logged). Atomicity on real PostgreSQL (`tests/signals/infrastructure/test_order_outcomes_integration.py`): a commit that fails loses the mark and the outcome together, and a clean run proves the exact commit count; made non-vacuous by moving each outcome onto a commit of its own (4 mutations, each red).
- [x] 5b.7 RED `ClosePosition`, rows 13–15, with the same atomicity test. Done (unit C, gate green): `CloseCommand.signal_id: UUID | None`, REQUIRED with no default. `_handle_releases` passes the signal, `CloseOrphans` passes `None` on purpose (a refused orphan close must not reject the open deferred behind it). Row 13 (`NOT_CLOSABLE`) got its NEW commit at that branch, which also makes a caller's staged continuation seed durable and commits even with no signal; row 14 stages on the post-network `mark_failed` commit, row 15 (`PROCESSING`) on `mark_placed`. REVERSE (decision 26): the close half is `PROCESSING`; a refused close ends `REJECTED` with the close's code; row 18 (`REVERSE_NEW_SIDE_UNHOLDABLE`) is written by `signal.process` on its own commit after the close is placed, only when `result.executed`, and the replay branches write nothing. Atomicity tests on real PostgreSQL in the file above, with the same mutation proof.
- [x] 5b.8 RED deferrals: the in-flight wait and the orphan close leave the signal `PROCESSING`. Done (unit D, gate green): both `_handle_consumes` deferrals stage `PROCESSING` on the commit that makes the continuation seed durable. In-flight wait: between `open_after_close.seed` and its `commit()` (also on the `open_now` re-deferral at `poll + 1`). Real orphan: immediately before `close_orphans.close(...)`, so it rides the first commit inside `CloseOrphans` (a close's own first commit, the NOT_CLOSABLE commit, or its final commit), the same commit that carries the seed. Tests: `tests/signals/application/test_process_signal_deferral_outcomes.py` (shared timeline of seed, outcome and commit). Lock-order note in design.md § C.
- [x] 5b.9 RED rows 19–20: a duplicate delivery and an idempotent close replay never change a recorded outcome. Done (unit D, gate green): needed no production code. `tests/signals/infrastructure/test_replay_outcomes_integration.py` starts from a signal that already holds a terminal outcome (PROCESSED and REJECTED), replays a duplicate delivery through the real `IngestSignal`, the idempotent close replay, the FAILED-reverse replay and the spot-short REVERSE replay, and asserts status, reason, detail and `decided_at` unchanged plus no WARNING from the terminal guard (the guard would otherwise hide a stray write as a no-op). Non-vacuous: each protection was broken in turn (reset the row on a duplicate, stage a write in either replay branch, vary row 18's detail) and each test went red.
- [x] 5b.10 GREEN: the writes, each on its deciding commit. Done (units C and D): every write sits on its deciding commit. Rows 9-12 and 13-15 in `PlaceOrder`/`ClosePosition` (unit C, with the NEW row-13 commit), row 18 on the handler commit after the close is placed, the two deferrals on the seed commit (unit D). Where the code differs from design.md § C the table and its "As built" notes were corrected.
- [x] 5b.11 RED decision 27: a releasing signal with no position to release (`_handle_releases`, `prior_reservation_id is None`) logs one WARNING naming the signal, the strategy and the symbol, and ends `REJECTED` `NO_POSITION_TO_CLOSE` with that message as the detail, on the commit that carries the refusal. Cover CLOSE and REVERSE. A REVERSE with no position opens nothing today either, and its detail must say so. The behaviour stays as it is; only the outcome and the log line are new. Add the row to design.md § B and § C. Done (unit E, gate green): `_handle_releases` now logs one WARNING (signal, strategy, symbol) and returns through `_reject`, ending `REJECTED` `NO_POSITION_TO_CLOSE` with that message as the detail on the refusal commit; a REVERSE's message adds "and the new side was not opened". Nothing else changed. Tests: `tests/signals/application/test_process_signal_no_position.py` (CLOSE, REVERSE, one-WARNING) plus a real-PostgreSQL durability case in `test_refusal_outcomes_integration.py`, proven non-vacuous by bypassing `_reject` (row stayed ACCEPTED). design.md § B row 21 and § C.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: real PostgreSQL for the migration and the atomicity tests; fakes elsewhere.
Rollback boundary: migration 0025 (its downgrade refuses while outcomes exist) and the outcome writes.
Deploy: rehearse 0025 on a throwaway restore like 0024; no seeding to review.
Forecast: 900–1,300 lines.

---

## PR 5c — Asynchronous signal outcomes (900–1,400 lines)

Decision 25. Closes the outcomes decided outside `signal.process` (rows 16–17, the
continuation, exhausted jobs). No new migration: 0025 already added `execution_attempts.signal_id`.

- [x] 5c.1 RED settle of an OPEN: FILLED ends `PROCESSED`, in the same commit as the fills, with the signal resolved through `reservation.signal_id`. Done (unit F, gate green): `SettleExecution` takes the consumer-side `SettleOutcomeRecorderPort` (`record_open_filled`, `record_close_filled`, `record_never_placed`; adapter `signals/infrastructure/settle_outcome_recorder.py`, `execution` never imports `signals`) and stages `record_open_filled(reservation.signal_id)` after the fills and the reservation mark, immediately before the one commit. Unit tests with fakes assert the exact call order (`ledger.record`, `outcome.open_filled`, `commit`); atomicity on real PostgreSQL in `tests/signals/infrastructure/test_settle_outcomes_integration.py` (fault on the commit loses fills, mark and outcome together; a clean run asserts exactly one commit). Non-vacuous: moving the outcome onto its own later commit turned the commit-count tests red. A legacy open attempt with a NULL link still resolves through the reservation.
- [x] 5c.2 RED `NEVER_PLACED` ends `REJECTED` `ORDER_NEVER_REACHED_EXCHANGE`, in the same commit as the release. Done (unit F, gate green): `_release_never_placed` builds the message once (the exact line it already logged), stages `record_never_placed(signal_id, message)` immediately before the release commit and logs it with `"%s"` afterwards. An open resolves its signal through the reservation (read before the release so its row lock is taken first); a close through `attempt.signal_id`, and a close with a NULL link records nothing. A REVERSE's refused close ends `REJECTED` with this code. Real-PostgreSQL atomicity tests for the open and the close; non-vacuous by the same later-commit mutation.
- [x] 5c.3 RED close linkage: `PlaceOrder` and `ClosePosition` write `execution_attempts.signal_id`. Settle of a CLOSE resolves the closing signal, never the opening one. The test must fail if settle reads the opening reservation's `signal_id` for a close. A FILLED close of a REVERSE whose open half is still pending leaves the signal `PROCESSING` (decision 26): the open half decides, and a `PROCESSED` written here would block it through the terminal guard. The test must fail if a REVERSE's close fill writes a terminal status. This includes a spot REVERSE whose new side cannot be held: it is already `REJECTED` `REVERSE_NEW_SIDE_UNHOLDABLE` from 5b (row 18), so its close fill writes nothing at all rather than hitting the terminal guard with a differing `PROCESSED` and a WARNING on every such trade. Done (unit F, gate green): `ExecutionAttempt.signal_id` (default `None`) is written on the attempt insert by `PlaceOrder` (`reservation.signal_id`) and `ClosePosition` (`command.signal_id`, NULL for an orphan close); `SqlAlchemyExecutionAttemptRepository` maps it both ways; nothing is backfilled. Settle of a close resolves `attempt.signal_id`, never `reservation.signal_id` (mutation proof: reading the reservation's signal turned the plain-close integration test red). Settle cannot tell a REVERSE from a CLOSE and `execution` may not import `signals`, so the adapter derives the kind exactly as `SignalContextAdapter` does when `signal.process` routes the signal: the signal's `position_size` against `find_prior` through `PositionTransition.classify` (the kind is stored nowhere, both inputs are immutable). A REVERSE's filled close writes nothing: the signal stays `PROCESSING`, and a spot REVERSE already `REJECTED` `REVERSE_NEW_SIDE_UNHOLDABLE` stays untouched with no WARNING from the terminal guard (asserted with `caplog`); removing the REVERSE check turned both red.
- [x] 5c.4 RED continuation abandonments end `REJECTED`: `SIGNAL_SUPERSEDED`, `AWAITED_CLOSE_FAILED`, `CONTINUATION_TIMED_OUT`. A deleted signal writes nothing. A REVERSE whose close was dust (`NOT_CLOSABLE`) writes no attempt row, so its seeded continuation only abandons on timeout; the signal is already `REJECTED` `CLOSE_DUST_NOT_CLOSABLE` from 5b, and the late write is a silent no-op, NOT a warning (design.md addendum § A "The non-warning path" and § E, both corrected: the earlier claim that a late write "is a no-op, no WARNING" was wrong for differing codes). Done (unit G, gate green): `SignalOutcomePort.record_unless_terminal` (same fresh `FOR UPDATE` read; a terminal signal is left alone with no write and no WARNING, a non-terminal one is written as `record` would). `OpenAfterClose` takes `outcomes` (required, wired in `main.py`) and `_abandon` records `REJECTED` with the exact logged message as the detail: `SIGNAL_SUPERSEDED`, `AWAITED_CLOSE_FAILED`, and `CONTINUATION_TIMED_OUT` for the age bound (after the closes filled, or while one is unsettled) and the settle-timeout bound. A deleted signal writes nothing. The write rides `main.py::handle_signal_open_after_close`'s trailing `session.commit()`. Tests: `test_open_after_close_outcomes.py` (fakes; asserts `record_unless_terminal`, never `record`), `test_outcome_unless_terminal.py` (real PostgreSQL; terminal left alone silently, non-terminal written, `record` still warns on the same row, unknown signal raises, lock-hold `not task.done()`), `test_continuation_outcomes_integration.py` (production composition root; the dust, refused-close and already-`PROCESSED` cases assert no guard WARNING). Non-vacuous: routing the abandonment through `record` turned nine tests red, dropping the write turned eight red, delegating `record_unless_terminal` to the warning path turned four red.
- [x] 5c.5 RED the continuation's `open_now` reuses 5b's writes, rows 2–15, in the continuation job's own commits. Done (unit G, gate green): no production code was needed; `open_now` reaches the same `_reject`, `AllocateCapital` and `PlaceOrder` writes on the continuation's session. Proven end to end on real PostgreSQL through `main._build_process_signal_handler` (`test_continuation_outcomes_integration.py`): a REVERSE whose close FILLED and whose open is refused with `PAIR_NOT_ALLOWED` ends `REJECTED` `PAIR_NOT_ALLOWED` with a detail saying the close half already executed; a proceeding open ends `PROCESSING` (the signal starts `ACCEPTED`, so the status must come from the open half) with a new SUBMITTED reservation and an attempt linked to the REVERSE signal. Non-vacuous: dropping `_reject`'s write turned the refusal test red, dropping `PlaceOrder`'s `record_processing` turned the proceeding test red.
**Split, 2026-09-29 (owner, auto-chain).** PR 5c ships 5c.1–5c.5, about 2,400 authored lines.
Tasks 5c.6–5c.7 move to **PR 5c2**, cut from `main` after PR 5c merges. PR 5c2 changes
`queue.fail()`, which every failing job goes through, so it is reviewed and deployed on its own.
Its commit was written before the split (`8c90919`, never pushed) and replayed onto `main` at
`d9fb55d` after PR 5c merged.

### PR 5c2 — Exhausted jobs (tasks 5c.6–5c.7)

- [x] 5c.6 RED exhausted jobs: a signal whose `signal.process`, `signal.open_after_close` or `execution.settle` job ends `FAILED` becomes `REJECTED` `JOB_FAILED`, with `jobs.last_error` as the detail, exactly once. `job_queue` stays job-kind-agnostic: a separate reader resolves the job's payload to its signal. Done (unit H, gate green): trigger chosen and argued in design.md § F. A hook at the point `queue.fail()` marks a job `FAILED`, in the SAME transaction: `ExhaustedJobObserverPort` (shared, opaque job in, kind-agnostic), `PostgresJobQueue.fail()` split into `_record_failure` plus its commit, and `ExhaustionObservingJobQueue` (a subclass with a REQUIRED observer, wired only in `main.build_worker_runner`'s `queue_factory`) runs the observer between the two under a SAVEPOINT, so an observer failure is logged (ERROR, redacted) and never costs the job its `FAILED` status or the claim loop. `SqlAlchemyFailedJobSignalReader` resolves `signal.process`/`signal.open_after_close` by payload and `execution.settle` through the attempt (`execution_attempts.signal_id` for a close, `reservation.signal_id` for an open; NULL or another kind resolves to nothing; an unresolvable payload raises). `ExhaustedJobSignalRecorder` writes `REJECTED` `JOB_FAILED` through `record_unless_terminal` with the error REDACTED and truncated to 500 characters, adding nothing to it. Exactly once: a job reaches `FAILED` once (claim lock), the outcome and the status are one transaction (a failed commit loses both), two exhausted jobs of one signal write once (terminal guard, silent), and a held signal-row lock makes the write wait (`not task.done()`). Findings on `last_error` and on the log line are in design.md § F: no ERROR is logged when a job becomes `FAILED` (the runner WARNs per attempt, the watchdog ERRORs on its cadence), so none was added. Tests: `tests/shared/infrastructure/test_observed_job_queue.py`, `tests/signals/infrastructure/{test_failed_job_signal_reader,test_exhausted_job_recorder,test_exhausted_jobs_integration,test_exhausted_jobs_wiring}.py` (the last drives the runner `main.py` builds). Non-vacuous: running the observer after its own commit, dropping the savepoint, dropping the catch, resolving a close through the reservation, using `record` instead of the silent path, dropping redaction, dropping truncation, and reverting the `queue_factory` wiring each turned tests red.
- [x] 5c.7 GREEN. Every write in the outcome map's PR 5c rows is in place and the full gate is green after each of units F, G and H: rows 16-17 and the close linkage (unit F, `b2dec83`), the continuation abandonments and the open half (unit G, `a54973b`), and exhausted jobs (unit H). Design.md § B, § C, § E and the new § F carry the as-built notes and the corrections.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: real PostgreSQL for the settle, linkage and exhausted-job tests.
Rollback boundary: the writes only; the schema stays from 0025.
Forecast: 900–1,400 lines.

---

## PR 6 — Units 3a + 3b + 3c + 3d: pool capital at open, PnL, curve, stats (2,150–3,100 lines)

**Split, 2026-09-29 (auto-chain).** The PR is split into three sequential PRs, each cut from
`main` after the previous one merges:

- **PR 6a** holds unit 3a, with migration 0026. It ships first and alone because
  `pool_total_at_open` cannot be backfilled: every trade opened before 0026 is deployed is
  excluded from the curve forever.
- **PR 6b** holds units 3b and 3c: the fills source, `derive_trade`, and the curve.
- **PR 6c** holds unit 3d: per-strategy and per-pair stats.

The gate below applies to PR 6b, the first PR that reads fills.

**Gate before deploy**: `SELECT count(*) FROM ledger_entries WHERE exchange_fill_id LIKE 'fake-fill-%'` run and recorded (F2 — any rehearsal rows are excluded by design, this just confirms the count for the record).

### Unit 3a — `pool_total_at_open`, migration 0026 (350–500 lines)

**Files**: Create `backend/migrations/versions/0026_reservation_pool_total.py`; Modify
`backend/src/strategy_manager/allocation/domain/reservation.py`, `allocation/infrastructure/{models,repository}.py`, `allocate_capital.py`.

- [x] 3a.1 RED `backend/tests/migrations/test_0026_reservation_pool_total.py::test_pool_total_at_open_check_allows_null_or_positive`, `::test_downgrade_refuses_while_any_non_null_value_exists`.
  - Done 2026-09-29: `test_0026_reservation_pool_total.py` (6 tests). RED with the migration file absent: all 6 failed (UndefinedColumn; the accepted technique for a migration). GREEN with 0026. Non-vacuous: CHECK loosened to `>= 0` makes the zero-refusal test fail (DID NOT RAISE). Downgrade refusal names the count and offers no force flag; a NULL-only database downgrades cleanly and drops the column.
- [x] 3a.2 RED `backend/tests/allocation/application/test_allocate_capital.py::test_reservation_records_in_lock_pool_capital_not_prelock_read` — pool reads 510 pre-lock, 500 in-lock; asserts 500 stored, no extra read (F1).
  - Done 2026-09-29: RED on assertion (`None == Decimal('500')`). Pool reads 510 before the lock and 500 inside it; 500 is stored and `reads == 1`, so no read was added. Triangulated with total 1000 / available 700 (stores the total) and a zero-total case (stores NULL plus one ERROR, never 0). A PARTIAL grant records the total too (proven by breaking it for PARTIAL only).
- [x] 3a.3 RED same file `::test_pool_total_at_open_written_under_lock_survives_concurrent_allocation_on_same_pool` — **live PostgreSQL**.
  - Done 2026-09-29: `tests/allocation/infrastructure/test_pool_total_at_open_integration.py` (placed beside the other live-PG allocation tests, not in the unit file the task named). Real PostgreSQL, lock-hold harness: the second actor is `not task.done()` while the first holds the pool lock, then each reservation stores what it saw inside its own lock (1000 and 900). Negative control with a no-op lock proves the wait assertion is the advisory lock. A BTC pool reservation stores 0.5, not the USDT pool's value. RED on assertion (`None == Decimal('1000')`).
- [x] 3a.4 RED same file `::test_resume_of_retried_allocation_returns_existing_row_unchanged`.
  - Done 2026-09-29: passed on first run because the plumbing field already existed and `_resume` never wrote. Proven non-vacuous by removing the early `_resume` return in `allocate()`: the test failed (`resumed` False). Asserts no insert, no pool read, no lock, and the existing row's 500 untouched.
- [x] 3a.5 GREEN: `migrations/versions/0026_*.py` — `reservations.pool_total_at_open Numeric(38,18) NULL` + `CHECK (pool_total_at_open IS NULL OR pool_total_at_open > 0)`; downgrade refuses while non-null values exist.
  - Done 2026-09-29: `0026_reservation_pool_total.py`, `down_revision` 0025, `Numeric(38,18) NULL` + `ck_reservations_pool_total_at_open_positive`; downgrade refuses while non-null values exist, names the count, no force flag.
- [x] 3a.6 GREEN: `Reservation.pool_total_at_open: Decimal | None`; `AllocateCapital` writes it from the existing in-lock `pool_balance.total` read (`allocate_capital.py:131`), no new read.
  - Done 2026-09-29: `Reservation.pool_total_at_open`, ORM column, repository `_to_domain` and `insert`, and `AllocateCapital` writes the in-lock `pool_balance.total` (read at `allocate_capital.py:201`, no new read). Non-positive total stores NULL with an ERROR (unreachable from the production source: `decision.py:53` and `total >= available` CHECK). ERROR, not WARNING, after the independent verification: the trade is lost to the curve for good, and only ERROR reaches the operator's alerts. Gate: ruff clean, mypy clean, full suite 1888 tests, exit 0.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/migrations/test_0026_reservation_pool_total.py backend/tests/allocation/`.
Harness: real PostgreSQL, live concurrency test.
Rollback boundary: additive column; downgrade refuses while non-null values exist (values cannot be recomputed).
Forecast: 350–500 lines.

### Unit 3b — fills source, `derive_trade` (700–1,000 lines)

**Files**: Create `backend/src/strategy_manager/performance/domain/{closed_trade,derive_trade}.py`,
`performance/application/ports.py` (`AllocationFillsSourcePort`), `performance/infrastructure/allocation_fills_source.py`;
Modify `backend/src/strategy_manager/execution/domain/fill.py` (`REHEARSAL_FILL_ID_PREFIX`);
Modify `backend/src/strategy_manager/execution/infrastructure/fake_exchange.py`.

- [x] 3b.1 RED `backend/tests/execution/infrastructure/test_fake_exchange.py::test_fake_fill_ids_use_the_named_rehearsal_prefix_constant`.
  - Done 2026-09-29: RED on assertion (the fake minted `fake-fill-...` while the test patched the constant the adapter uses and expected `rehearsal-probe-...`; a stub of the constant plus an unused import made it importable). GREEN: `fake_exchange.py` mints with the constant. The test also pins the value `"fake-fill-"`, because ledger rows already carry it.
- [x] 3b.2 RED `backend/tests/performance/domain/test_derive_trade.py::test_realized_pnl_long_trade_100_to_106_with_settlement_fee`, `::test_third_currency_fee_flagged_fees_complete_false_not_converted`, `::test_base_currency_fee_not_subtracted_again_already_in_notional_diff`, `::test_open_allocation_yields_no_realized_pnl_counted_as_open`, `::test_partial_close_counted_as_open_not_closed`, `::test_rehearsal_fill_excluded_from_derivation`.
  - Done 2026-09-29: `tests/performance/domain/test_derive_trade.py`. All six named tests plus six more, 15 in the file. RED with a stub `derive_trade` on assertions (`None is not None`, `0 == 2`). Non-vacuous by mutation: tolerance `> 0.001` fails the exact-zero test; subtracting a base fee again fails the base-fee test; flagging a zero third-currency fee fails its test; a case-sensitive fee currency fails its test. `test_rehearsal_fill_excluded_from_derivation` tests the domain half of the rule: an allocation opened by a rehearsal fill and closed by a live one reaches the domain as a lone SELL and must stay OPEN, never a trade whose PnL is the whole sale. The exclusion itself is SQL (3b.4).
- [x] 3b.3 RED same file `::test_pair_derived_from_market_key_of_allocation_fills_spelling_merge` — fills spelled `SOLUSDT.P` on open and `SOLUSDT` on the booked close, asserts one pair `SOLUSDT` (F4, spelling rule).
  - Done 2026-09-29: parametrized over three close spellings (`SOLUSDT`, `SOLUSDT_PERP`, `solusdt`) against an open spelled `SOLUSDT.P`. Mutation `pair=first.symbol` fails all three. Repeated end to end through the real ledger in 3b.4.
- [x] 3b.4 RED `backend/tests/performance/infrastructure/test_allocation_fills_source.py::test_source_excludes_fake_fill_prefix_rows`, `::test_source_groups_by_allocation_strategy_side_fee_currency`, `::test_source_reads_pool_total_at_open_from_reservation_join`.
  - Done 2026-09-29: `tests/performance/infrastructure/test_allocation_fills_source.py`, 6 tests on real PostgreSQL, written through `RecordFill`. Beyond the three named: a fill id that only CONTAINS the prefix is not rehearsal; pool isolation across three pools sharing currency (one differs only by exchange); an empty pool. RED on assertions with a stub source. Mutations: no `NOT LIKE` fails the exclusion test; `contains` instead of `startswith` fails the prefix test; dropping the exchange filter fails the isolation test (it did NOT until the third pool was added: bybit vs pionex also differ by venue); dropping `fee_currency` from the grouping fails the grouping test.
- [x] 3b.5 GREEN: `REHEARSAL_FILL_ID_PREFIX = "fake-fill-"` moved into `execution/domain/fill.py`; `fake_exchange.py:144` mints with the constant.
  - Done 2026-09-29: `REHEARSAL_FILL_ID_PREFIX` in `execution/domain/fill.py`; `fake_exchange.py` mints with it.
- [x] 3b.6 GREEN: `ClosedTrade`, `derive_trade()` pure domain function (base-fee rule via `base_currency_of`, closed test, pnl, `fees_complete` flag).
  - Done 2026-09-29: `performance/domain/{closed_trade,derive_trade}.py`. `FillGroup` (input), `ClosedTrade`, `DerivedTrades`, `derive_trade` (one allocation), `derive_trades` (folds a pool). Closed = net base EXACTLY zero (ledger rule, no tolerance and no venue step) with a buy and a sell behind it. Fee table in the module docstring. A symbol with no base currency in the pool is returned in `unresolved_allocation_ids`, not raised and not dropped.
- [x] 3b.7 GREEN: `SqlAlchemyAllocationFillsSource` — the one SQL aggregate joining `ledger_entries` to `reservations`, `WHERE exchange_fill_id NOT LIKE :rehearsal_prefix || '%'`, grouped by `(allocation_id, strategy_id, side, fee_currency)`.
  - Done 2026-09-29: `SqlAlchemyAllocationFillsSource.pool_fills(pool) -> PoolFills(groups, rehearsal_fill_count)`. One grouped SELECT joined to `reservations`, plus a `count(*)` of the rehearsal fills it left out. `startswith(..., autoescape=True)` renders `NOT LIKE :p || '%' ESCAPE '/'`. Gate: ruff clean, mypy clean, full suite 1911 tests (1889 collected at HEAD + 22), exit 0.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/performance/ backend/tests/execution/`.
Harness: pure for `derive_trade`; real PostgreSQL for the SQL aggregate (rides `ix_ledger_pool_symbol`/`ix_ledger_allocation`).
Rollback boundary: new module, zero importers outside `performance/`; revert removes it entirely.
Forecast: 700–1,000 lines.

### Unit 3c — curve, drawdown, monthly grid, ranges, UTC (700–1,000 lines)

**Files**: Create `backend/src/strategy_manager/performance/domain/{daily_returns,compound,drawdowns,monthly_grid,range_summary}.py`
(or one `curve.py` module housing all five pure functions); Create
`backend/src/strategy_manager/performance/application/{read_pool_performance}.py`.

- [x] 3c.1 RED `backend/tests/performance/domain/test_curve.py::test_two_trades_different_days_compound_1_05_times_1_02` (the design worked example).
  - Done 2026-09-29: `tests/performance/domain/test_curve.py` (22 tests). RED with a stub module on assertions (`[] == [Decimal('1.05'), ...]`). `1.05 * 1.02` asserted as an exact `Decimal` (1.0710).
- [x] 3c.2 RED same file `::test_two_trades_same_utc_day_summed_not_chained_0_03_index_1_03` (the +20/+10 on a 1,000 USDT pool worked example — asserts 1.03, explicitly NOT 1.0302).
  - Done 2026-09-29: asserts 1.03 and `!= 1.0302`; triangulated with different capitals (20/1000 + 10/2000 = 0.025). Mutation: chaining inside a day fails this test and two others.
- [x] 3c.3 RED same file `::test_drawdown_from_previous_peak_1_20_to_1_14_is_5_percent`, `::test_no_drawdown_at_new_peak_is_zero`.
  - Done 2026-09-29: 1.20 -> 1.14 is exactly -0.05; a new peak is 0; plus the design's day-2 example (1.0094, -2%) and a first-day loss measured against `E_0 = 1`. Mutation: peak seeded from the first point fails the first-day-loss test.
- [x] 3c.4 RED same file `::test_utc_month_boundary_close_at_2026_08_31_22_30_minus_3_counts_september` (decision 16, UTC boundary case).
  - Done 2026-09-29: 22:30 at UTC-3 counts in September; triangulated with 20:59 (23:59 UTC, August) and 21:00 (00:00 UTC, September) at UTC-3. Mutation `closed_at.date()` (local) fails it, the UTC-day test and the naive-datetime test.
- [x] 3c.5 RED same file `::test_exclusions_reported_two_open_one_missing_capital_at_open`.
  - Done 2026-09-29: two open, one closed trade without capital: counts 2 and 1, curve has only the trade with capital, `total_pnl` still includes the 7. Also: an unconverted-fee trade stays in the curve and is counted. Mutation: treating a missing capital as a zero return adds a curve point and fails it.
- [x] 3c.6 RED same file `::test_range_summary_7d_30d_90d_1y_all_computed_independently`.
  - Done 2026-09-29: trades 3/20/60/200/500 days back; PnL 10/30/60/100/150 and compounded returns per window; window includes its start instant and excludes one second before. Mutations: exclusive start fails the boundary test; dropping a trade from All fails the range test.
- [x] 3c.7 RED `backend/tests/performance/domain/test_curve.py::test_no_qualifying_trades_yields_empty_result_not_error`, `::test_only_rehearsal_fills_yields_same_empty_result`.
  - Done 2026-09-29: empty input and rehearsal-only input give the same empty figures; the rehearsal count is the only difference. The empty test alone passes against the stub, so it is backed by the non-empty tests: the same functions produce non-empty output for the same shape of input.
- [x] 3c.8 GREEN: `daily_returns()`, `compound()`, `drawdowns()`, `monthly_grid()`, `range_summary()` — pure `Decimal`, UTC day taken via `closed_at.astimezone(UTC).date()`, never a database session time zone.
  - Done 2026-09-29: one module, `performance/domain/curve.py`, holding `daily_returns`, `compound`, `drawdowns`, `monthly_grid`, `range_summary` and `build_pool_performance`. UTC day from `closed_at.astimezone(UTC).date()`; a naive datetime raises. `build_pool_performance` raises on a trade from another pool (rule 7).
- [x] 3c.9 GREEN: `ReadPoolPerformance` application read composing the domain functions over `AllocationFillsSourcePort`.
  - Done 2026-09-29: `ReadPoolPerformance(fills, clock).read(pool)`, tests in `tests/performance/application/test_read_pool_performance.py` (10). Rule 7: one `PoolKey` per call, a port with no multi-pool method, and a check on every ROW the source returns before deriving (a stray opening leg would otherwise pass as an open trade). Logs: WARNING with allocation ids for unresolvable symbols, INFO counts for missing capital and unconverted fees, silence otherwise. Mutations: no row check, always-log, and wall-clock `now` each fail exactly their test. Gate: ruff clean, mypy clean, full suite 1943 tests, exit 0.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/performance/`.
Harness: pure, no DB.
Rollback boundary: pure domain functions with one application consumer; revert removes both, nothing else references them yet (endpoints land in PR 7).
Forecast: 700–1,000 lines.

### Unit 3d — per-strategy and per-pair stats (400–600 lines)

**Files**: Create `backend/src/strategy_manager/performance/domain/by_pair.py`; Create
`backend/src/strategy_manager/performance/application/{read_strategy_performance,read_strategy_trades}.py`.

- [x] 3d.1 RED `backend/tests/performance/domain/test_by_pair.py::test_solusdt_dot_p_and_solusdt_merge_into_one_pair` (F4, spelling rule).
  - Done 2026-09-29: `test_by_pair.py` (6 tests). RED with a stub `by_pair` returning `()` on assertions (`() == (PairStats(...),)`, and `KeyError` on the empty result for the dict-lookup tests). Two allocations, each leg under a different spelling (`SOLUSDT.P` / `SOLUSDT`, `SOLUSDT_PERP` / `solusdt`) go through the real `derive_trades` and come out as one pair with count 2, PnL 8 and return 0.008. Mutation: keying on the raw `trade.pair` instead of `market_key` fails the re-keying test.
- [x] 3d.2 RED same file `::test_per_pair_stats_include_pair_removed_from_allowlist` (allowlist independence).
  - Done 2026-09-29: RED on assertion (`set() == {'BTCUSDT', 'SOLUSDT'}`). The strategy's allowlist today is BTCUSDT; SOLUSDT (2 trades, PnL 3) still shows. In the domain the protection is structural (`by_pair` takes no allowlist), so the same rule is also asserted through `ReadStrategyPerformance` (`test_by_pair_merges_spellings_and_keeps_a_pair_that_is_no_longer_allowed`), which is likewise given none. Also in the file: per-pair return is the pair's own contribution; a pair of only pre-0026 trades has `value None`, not 0 (mutation to 0 fails it); alphabetical order.
- [x] 3d.3 RED `backend/tests/performance/application/test_read_strategy_performance.py::test_strategy_curve_uses_pool_capital_at_open_as_contribution`, `::test_strategy_stats_scoped_to_its_own_pool_settlement_currency`.
  - Done 2026-09-29: `test_read_strategy_performance.py` (13 tests). RED with a stub read returning an empty report on assertions (`[] == [Decimal('0.02'), Decimal('-0.01')]`). S1 +20 on 1000 then -10.3 on 1030 gives daily returns 0.02 and -0.01 and index 1.02 then 1.02 * 0.99, and S1's day-1 return plus S2's equals the POOL's `R_d` read through `ReadPoolPerformance` (the contribution property). Scope (rule 7, decision 1): one pool asked; rows of another pool are refused in three variants (other exchange, other venue, other currency) and a stray row of ANOTHER strategy in another pool is refused too (the check runs before the strategy filter); an allocation whose legs carry two strategy ids is refused. Exclusions are the strategy's own (open count, rehearsal count from `PoolFills.rehearsal_for`, no-capital); a strategy with nothing, or only rehearsal fills, gets the empty result. Logs: WARNING with the strategy's own ids only, INFO for no capital, silent when clean. Mutations: dropping the pool check fails 3, the split check 1, the strategy filter 8, a pool-wide rehearsal count 1.
- [x] 3d.4 RED `backend/tests/performance/application/test_read_strategy_trades.py::test_keyset_pagination_on_closed_at_and_allocation_id_two_trades_same_millisecond_across_page_boundary` (the "+1ms" lesson).
  - Done 2026-09-29: the named test in `test_read_strategy_trades.py` (fakes, 20 tests) and again, with the same name, on real PostgreSQL in `tests/performance/infrastructure/test_strategy_trades_integration.py` (placed beside the other live-PG performance tests, as 3a.3 did; 4 tests, trades written through `RecordFill`, so the instants are the ones `timestamptz` stores). RED on assertions (`[] == [UUID(...)]`, `None is not None`, `DID NOT RAISE`). Three trades close at the same instant with page size 2, plus one 1 ms later and one 1 ms earlier: every trade is served exactly once, newest first, ties by allocation id descending, with the cursor round-tripped through its ISO text and UUID text between pages. Also: a cursor inside a tie keeps the lower ids and drops the higher; a trade closing between two page reads neither repeats nor hides one; a booked close dated before the cursor is served once when reached. Mutations: `closed_at <` alone fails 7, `<=` fails 10, ascending tie-break fails 10, `>= limit` for the next cursor fails 2, no zone check on the cursor fails 1.
- [x] 3d.5 GREEN: `by_pair()` pure domain function grouped per allocation then by `market_key()`; `ReadStrategyPerformance`, `ReadStrategyTrades` application reads (keyset on `(closed_at, allocation_id)` descending, never `closed_at` alone).
  - Done 2026-09-29: `performance/domain/by_pair.py`, `performance/application/{scope,read_strategy_performance,read_strategy_trades}.py`. Pagination is applied over the derived trades in Python, not in SQL ("closed" is a domain rule, not a column; design.md section 11 "As built (PR 6c)" states what bounds the work and the cursor encoding). `ReadPoolPerformance` now shares `scope.require_single_pool` and `scope.log_exclusions` (messages unchanged, its tests untouched). The fills source counts rehearsal fills per strategy so a strategy's report states its own count; `curve.trade_return` is public. Gate: ruff clean, mypy clean, full suite 1985 tests (1943 + 42), exit 0. Gap for PR 7: the trades row wants `direction`, which `ClosedTrade` does not carry (design.md).

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/performance/`.
Harness: pure for `by_pair`; real PostgreSQL for the pagination boundary test.
Rollback boundary: two new application reads; revert removes both, no endpoint depends on them until PR 7.
Forecast: 400–600 lines.

---

## PR 6d — The `DRY_RUN` mode guard (decision 28) (300–500 lines)

Added 2026-09-29. The worker refuses to start when `DRY_RUN` does not match the origin of an
open position. It runs after PR 6c, cut from `main` once PR 6c merges.

**Files**: Create `execution/infrastructure/mode_origin_invariant.py` (or extend
`dry_run_invariant.py`, whichever reads better) and a read port for open allocations with the
origin of their fills; Modify `main.py::build_worker_runner` beside `assert_dry_run_safe`.

- [x] 6d.1 RED `DRY_RUN=false` with an open allocation that holds a `fake-fill-` fill: the worker refuses to start. It logs one ERROR naming the strategy, the pool and the symbol, and says to close the position with `DRY_RUN=true` first.
  - Done 2026-09-29: `tests/execution/domain/test_mode_origin.py::test_live_mode_refuses_an_open_allocation_holding_a_rehearsal_fill`, `tests/execution/application/test_assert_mode_matches_ledger.py::test_live_start_over_an_open_rehearsal_position_logs_one_error_and_refuses`, and composed on real PostgreSQL in `tests/ledger/infrastructure/test_mode_guard_startup_integration.py`. RED with stubs, on assertions (`() == (ModeMismatch(...),)`, `DID NOT RAISE InvariantViolation`, `'Alpha' in ''`). The ERROR names strategy, pool, symbol and allocation id, and the way out: close it in the mode that opened it, then flip. Mutation: swapping the two modes fails 13.
- [x] 6d.2 RED `DRY_RUN=true` with an open allocation that holds a live fill: the worker refuses to start. The ERROR says to close it with `DRY_RUN=false` first, since a fake close would leave the real position open on the venue.
  - Done 2026-09-29: `test_dry_run_refuses_an_open_allocation_holding_a_live_fill`, `test_dry_run_start_over_an_open_live_position_logs_one_error_and_refuses`, the composed PostgreSQL test, and `test_an_allocation_holding_both_kinds_refuses_in_either_mode` (a mixed allocation refuses in both modes; its line says neither mode can close it). RED on the same kinds of assertion. The dry-run ERROR adds that the real position would still be open on the venue. Mutation: ignoring the mixed case fails 1.
- [x] 6d.3 RED no open allocation, or only open allocations of the current mode: the worker starts, and the check logs nothing.
  - Done 2026-09-29: `test_nothing_open_starts_and_logs_nothing`, `test_only_positions_of_the_current_mode_start_and_log_nothing` (`caplog.records == []` at DEBUG, both modes), `test_a_clean_start_sends_no_alert`, and composed on PostgreSQL `test_a_start_in_the_matching_mode_logs_nothing` / `test_an_empty_ledger_starts_in_either_mode`. These pass against the stub by construction (a stub also starts and logs nothing). Proven non-vacuous by mutation: making the use case treat "no mismatch" as a refusal fails 6 of them.
- [x] 6d.4 RED "open" is a net base quantity that is not exactly zero, the same rule as `derive_trade` and `net_positions_by_symbol`. A closed rehearsal allocation never blocks a live start.
  - Done 2026-09-29: pure in `test_mode_origin.py` (a closed rehearsal round trip; a remainder of 1e-18 stays open; a base-currency fee leaves BUY 1 / SELL 1 open while SELL 0.999 is flat; a settlement-currency fee does not; `SOLUSDT.P` open and `SOLUSDT` close are one flat allocation; an unsplittable symbol fails closed as open) and on real PostgreSQL in `test_mode_origin_reader_integration.py` (the AAVE and SFP shape: a closed rehearsal round trip beside an open one; a Pionex spot BTC fee). RED on assertions (`() == (OpenAllocationOrigin,)`, `[] == [...]`). The rule is `derive_trade`'s base-fee rule (`fee_currency == base_currency_of(symbol)`), grouped by allocation and never by symbol. Mutations: nothing-is-flat fails 9, a sell that adds fails 9, base fee never subtracted fails 2, grouping by symbol too fails 15, an unsplittable symbol assumed flat fails 1.
- [x] 6d.5 GREEN the startup check, on real PostgreSQL, using `REHEARSAL_FILL_ID_PREFIX` (from PR 6b). The ERROR reaches Telegram through the alert bridge before the process exits.
  - Done 2026-09-29: `execution/domain/mode_origin.py` (pure decision), `execution/application/{ports,assert_mode_matches_ledger}.py`, `execution/infrastructure/mode_origin_reader.py` (SQL), `main.assert_dry_run_matches_ledger`, called from `worker._run_worker` before `build_worker_runner` (not inside it: that function is synchronous and is also built by tests with no database). The read covers every pool in the ledger, enabled or not (`test_a_pool_that_is_disabled_is_still_read`; mutation: filtering on `capital_pools.enabled` fails it) and tests the marker as a PREFIX (mutation: substring fails 1). Refusal mechanism: log one ERROR, then raise `InvariantViolation` out of `worker.run`, like `assert_dry_run_safe` and the lock-key check; `worker.main` catches only `KeyboardInterrupt`, so the process exits 1 (checked by running `worker.main()` with `run` patched to raise: exit code 1). Delivery: `test_the_refusal_reaches_the_alert_channel_before_the_context_exits` runs the check inside the real `operator_alerts` with a recording alerter and finds the alert after the context exits (`aclose` drains). Wiring pinned in `tests/test_mode_guard_wiring.py` (guard before the composition root and the seeding, inside `operator_alerts`, refusal not swallowed). Gate: ruff clean, mypy clean, full suite 2050 tests (1985 + 65), exit 0.
- [x] 6d.6 (added 2026-09-29 by the orchestrator, same purpose as decision 28) an execution attempt that is not terminal has no fills yet, so the open-allocation check cannot see it. A `SUBMITTED` attempt whose `exchange_order_id` is set has a determinable origin from data that already exists: the fake mints `fake-order-<uuid>` (new `REHEARSAL_ORDER_ID_PREFIX`, used by `FakeExchangeAdapter.place`, one definition), and no venue does (Bybit `orderId` is a UUID, Binance's an integer). No schema change.
  - Done 2026-09-29: `DRY_RUN=false` refuses a rehearsal order still waiting for `execution.settle`, and `DRY_RUN=true` refuses a live one (`test_live_mode_refuses_a_rehearsal_order_still_waiting_to_settle`, `test_dry_run_refuses_a_live_order_still_waiting_to_settle`: one RED test per direction, plus their use-case twins and the two accept cases). Same ERROR, listed beside the positions. Real PostgreSQL: `SUBMITTED` only (`FILLED`, `FAILED`, `ABORTED_EXPIRED` are terminal), opening and closing attempts both, strategy resolved through the reservation. Mutations: terminal statuses included fails 3, comparing the wrong way fails 8, in-flight orders ignored fails 5. `test_fake_order_ids_use_the_named_rehearsal_prefix_constant` pins that the fake mints with the constant (RED on assertion first).
  - **Gap, reported and not invented around**: a `SUBMITTED` attempt whose `exchange_order_id` is still NULL (the window between the pre-network commit and `mark_placed`, or a crash inside it) carries nothing that says which mode wrote it. It is not read (`test_a_submitted_attempt_the_exchange_has_not_yet_named_is_not_read` pins that). Closing it would need the mode recorded on the attempt, which is a schema change the owner has not decided.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: real PostgreSQL for the open-allocation read; fakes for the startup wiring.
Rollback boundary: the startup check only; reverting it restores today's start.
Deploy: pull, restart both. Production holds 4 `fake-fill-%` ledger rows. The owner checked
them on 2026-09-29: they are two rehearsal round trips, both closed (net base exactly 0, no live
fill). One is AAVE on `AAVEUSDT.P`, the other SFP on `SFPUSDT.P`, both on `binance/usdt-m/USDT`.
They are also the only two reservations in production. So none of them blocks a later
`DRY_RUN=false` start. A position still open on TradingView that the system never opened is not
in the ledger; its close ends `REJECTED` `NO_POSITION_TO_CLOSE` (decision 27).

---

## PR 6e — A startup refusal exits 78 (decision 29) (150–350 lines)

Added 2026-09-29. Every refusal the worker raises during its startup phase exits the process
with code 78, after the ERROR it already logs. The owner adds `RestartPreventExitStatus=78` to
the worker unit. A failure after startup keeps its current exit and keeps being restarted.

- [x] 6e.1 RED each startup refusal ends the process with exit code 78:
  - Done 2026-09-29: `tests/test_worker_startup_exit.py::test_every_startup_refusal_exits_78`, six cases through `worker.main`, the real `operator_alerts` and the real `_run_worker` sequence (only PostgreSQL and venue leaves replaced): vault self-test, pool lock-key collision, no enabled pools, unreadable `MASTER_ENCRYPTION_KEY`, the decision 28 mode guard (the real use case over a fake reader), and `assert_dry_run_safe` (the real `build_worker_runner` with a non-live adapter registered). RED on assertions: `assert 'InvariantViolation' == 78` (and `'PoolLockKeyCollisionError' == 78`) x6. Two refusals beyond the four named were found: no enabled pools, and the master key.
  - the vault self-test;
  - the pool advisory-lock key check (invariant 1);
  - `assert_dry_run_safe` (invariant 2);
  - the decision 28 mode guard;
  - any other refusal found in the startup sequence.
- [x] 6e.2 RED an exception raised AFTER startup, from the running loop, does NOT exit 78: it keeps today's non-zero exit, so systemd restarts it. The test must fail if startup and runtime failures share an exit path.
  - Done 2026-09-29: `test_a_failure_from_the_running_loop_is_not_a_startup_refusal` (`InvariantViolation`, `DecryptionFailed`, `PoolLockKeyCollisionError`, `RuntimeError` from `run_forever`), `test_a_failure_while_seeding_the_chains_is_not_a_startup_refusal`, `test_a_failure_from_the_running_loop_logs_no_startup_refusal`. These pass against today's code by construction (nothing maps to 78 yet). Proven non-vacuous by mutation: wrapping `run_forever` and the seeding in `_startup_refusal()` fails 5 of them.
- [x] 6e.3 RED each startup refusal still logs exactly one ERROR that reaches the alert bridge before the exit. A refusal that raises without an ERROR is a finding: it would stop the worker in silence.
  - Done 2026-09-29: `test_every_startup_refusal_logs_one_error_that_reaches_the_alert_channel` (one ERROR in `caplog` and one message on the recording alerter, per refusal, inside the real `operator_alerts`), `test_the_mode_guard_keeps_its_own_error_text`, `test_a_refusal_never_puts_the_master_key_or_a_traceback_in_the_alert`. RED on `assert 0 == 1` for the five refusals that logged nothing. **Finding: five of the six raised without any ERROR** (lock-key collision, no pools, master key, vault self-test, `assert_dry_run_safe`); only the mode guard logged. The worker now logs `refusing to start: <message>` with no `exc_info`. Mutation: logging unconditionally instead of honouring `logged` fails the mode guard cases (two ERRORs).
- [x] 6e.4 GREEN a dedicated startup-refusal type raised only by the startup phase. It is not the generic `InvariantViolation`, which runtime code also raises. `worker.main` maps it to `sys.exit(78)`.
  - Done 2026-09-29: `shared/domain/startup_refusal.py::StartupRefused` (stdlib only, `logged` flag); `worker._startup_refusal()` converts `InvariantViolation` and `PoolLockKeyCollisionError` around each startup check (wrap, not raise: the checks are shared with runtime code); `assert_mode_matches_ledger` raises it directly with `logged=True`; `worker.main` maps only it to `sys.exit(78)`. design.md addendum "a startup refusal exits 78 (decision 29)" gives the unit drop-in and the deploy-order answer. The six mode guard tests that expected `InvariantViolation` now expect `StartupRefused`.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Rollback boundary: the exit mapping only. Without the unit setting, 78 behaves like any other non-zero exit.
Deploy: pull, restart both. Then the owner adds the unit drop-in and reloads systemd.

**Known risk, accepted by the owner (2026-09-29).** The API unit has the same restart loop:
`Restart=always` and `RestartSec=5`, with no drop-in. Its lifespan refusals reach no alert channel.
Those refusals are a missing `WEBHOOK_SECRET` or `ADMIN_API_TOKEN`, or a pool lock-key collision.
They can only happen after an owner edit of `.env`, and every deploy command ends with
`systemctl is-active`, which shows it. While the API is down, TradingView's webhooks are lost.
Fixing it properly needs the API to compose the alert bridge, so it is left for a separate change.

---

## PR 7 — Read endpoints: pools, performance, `GET /webhook-secret` (950–1,350 lines)

**Files**: Create `backend/src/strategy_manager/accounts/infrastructure/{pools_router,pool_overview}.py`;
Create `backend/src/strategy_manager/performance/infrastructure/performance_router.py`; Create
`backend/src/strategy_manager/signals/infrastructure/webhook_secret_router.py`.

**Split, 2026-09-29 (auto-chain).** The PR is split in two sequential PRs, each cut from `main`
after the previous one merges.

- **PR 7a** holds tasks 7.1 and 7.2, and the pools and performance half of 7.4.
- **PR 7b** holds task 7.3 and the webhook-secret half of 7.4 (decision 23). It is the only endpoint
  that returns a secret, so it is reviewed and deployed on its own.

Two carry-overs from PR 6c land in PR 7a:

- `direction` is in the design's trades response but missing from `ClosedTrade`. It is added as the
  side of the allocation's earliest leg, through `derive_trade`.
- The strategy endpoints resolve the strategy first and return 404 for an unknown one. They then
  pass that strategy's own pool, because a wrong pool yields an empty result, not an error.

- [x] 7.1 RED `backend/tests/accounts/infrastructure/test_pools_router.py::test_get_pools_requires_bearer_token`, `::test_get_pools_computes_allocatable_as_max_zero_available_minus_reserved_server_side`, `::test_get_pools_never_sums_two_pools_on_same_exchange` (rule 7).
  - Done 2026-09-29 (PR 7a): `tests/accounts/infrastructure/test_pools_router.py` (7 tests, real PostgreSQL through `create_app()`, so the `/api` prefix is part of what is proven). RED against a stub router that had no auth and returned `[]`: every failure an assertion (`assert 200 == 401`, `assert 0 == 3`, and a `_Pools` lookup that raises `AssertionError` naming the missing pool rather than a bare `KeyError`). GREEN: `accounts/domain/pool_overview.py` (pure `allocatable`, `PoolOverview`), `accounts/infrastructure/{pool_overview,pools_router}.py`, mounted in `main.py`. "Reserved" is `SqlAlchemyReservationRepository.sum_active`, the allocator's own query (PENDING or SUBMITTED, `expires_at` in the future), so the panel and `AllocateCapital` cannot disagree. Mutations caught: auth dependency removed (1), no `max(0, ...)` clamp (1), `stale` hardwired false (1), reserved read for one fixed pool (3).
- [x] 7.2 RED `backend/tests/performance/infrastructure/test_performance_router.py::test_get_pool_performance_requires_bearer_token`, `::test_get_pool_performance_404_unknown_pool`, `::test_get_strategy_performance_includes_by_pair`, `::test_get_strategy_trades_keyset_pagination_422_half_a_cursor`, `::test_empty_ledger_returns_zeros_and_empty_arrays_never_an_error`.
  - Done 2026-09-29 (PR 7a): `tests/performance/infrastructure/test_performance_router.py` (20 tests, real PostgreSQL through `create_app()`, fixed clock), `tests/shared/infrastructure/test_wire.py`, and 7 domain tests for `direction` in `test_derive_trade.py`. RED against a stub router with no auth that returned `{"stub": true}`: every failure an assertion (`assert 200 == 401`, `assert 200 == 422`, a `_Json` lookup raising `AssertionError` naming the missing key, `assert [] == [PoolKey(...)]`); direction RED against `derive_trade` returning a fixed LONG (`LONG == SHORT` x4), the LONG/tie tests proven by mutation. Mutations caught: auth removed (2), wrong pool for a strategy (1), half-cursor check removed (1), `direction` hardwired (1), no ERROR log (2), `total_pnl`/`max_drawdown` as raw `Decimal` (1/3), `return` alias dropped (5), no 404 for an unknown pool (1), direction compared on `last_filled_at` (1, after adding a scale-out test). Not caught, and why: dropping the `Query(ge=1, le=200)` bounds, because `ReadStrategyTrades` refuses the same sizes with `InvalidPageRequest` and the router maps it to 422 (belt and braces, both kept). The half-cursor 422 test first used a random UUID against a tied timestamp and failed 1 run in 2; its cursor is now strictly older than the trade. Carry-overs: `ClosedTrade.direction` (LONG/SHORT, the side of the earliest leg by `first_filled_at`, ties to BUY) and strategy routes that load the strategy first (404) and read ITS pool. Gate: ruff, mypy clean; full suite 2122 tests, exit 0 (one intermittent PostgreSQL teardown `permission denied to terminate process` on the first run, gone on re-run). Latency: 1,000 closed trades in one pool, median 44 ms pool report, 46 ms strategy report, 39 ms trades page, 7 ms `GET /pools` (7 requests each, test database, not optimized).
- [x] 7.3 RED `backend/tests/signals/infrastructure/test_webhook_secret_router.py::test_get_webhook_secret_requires_bearer_token`, `::test_get_webhook_secret_returns_cache_control_no_store`, `::test_no_other_api_response_body_contains_the_configured_secret_value` (parametrized over every other `/api` route's response), `::test_access_log_never_records_the_secret_value`.
  - Done 2026-09-29 (PR 7b): `tests/signals/infrastructure/test_webhook_secret_router.py` (21 cases: 4 endpoint tests, 1 route-table sanity test, 15 parametrized payload cases, 1 access-log test). RED against a stub router (no auth, no headers, fixed body `stub`), every failure an assertion: `[200, 200, 200] == [401, 401, 401]`, `None == 'no-store'`, `200 == 503`, `{'secret': 'stub'} == {'secret': ...}`. The payload cases and the 405 test pass on the stub, so they were proven non-vacuous by mutation. Mutations caught: `no-store` dropped (1), auth dropped (1), secret logged once at DEBUG by the router (1, the access-log test), secret placed in `GET /api/pools` body (1), secret placed in a `GET /api/pools` response header (1), `POST` allowed on the secret route (1). The payload test is built from `fastapi.routing.iter_route_contexts(create_app().routes)` (FastAPI 0.141 includes routers lazily, so `app.routes` alone is empty of them) and cross-checked against `app.openapi()`; it seeds a strategy, a snapshot, a reservation, a closed trade and an enablement event, and requires every GET to answer 200 with a non-empty body except the two reconciliation lists, whose fixtures are heavy. The access-log test starts a REAL `uvicorn.Server` (uvicorn's own `LOGGING_CONFIG`, serving `strategy_manager.main:app`) and hits it over a socket; a capture handler sits on the root and every existing logger at DEBUG, plus `capsys` for uvicorn's stdout/stderr.
- [x] 7.4 GREEN: `SqlAlchemyPoolOverview`, `pools_router` (`GET /pools`); `performance_router` (`GET /performance/pools/{exchange}/{venue}/{ccy}`, `GET /performance/strategies/{id}`, `GET /performance/strategies/{id}/trades`); `webhook_secret_router` (`GET /webhook-secret`, reads `settings.webhook_secret` directly, `Cache-Control: no-store`).
  - PR 7a (2026-09-29): the pools and performance half is DONE (`SqlAlchemyPoolOverview`, `pools_router`, `performance_router`, plus `pool_lookup.py` and `shared/infrastructure/wire.py`). The webhook-secret half (`webhook_secret_router`) is PR 7b, task 7.3. PR 7b (2026-09-29) did the rest: `signals/infrastructure/webhook_secret_router.py`, mounted in `main.py` under `/api`. Body `{"secret": str}`; `Cache-Control: no-store` (no `Pragma`, since the spec asks for `no-store` alone); bearer auth on the router; an empty setting answers 503 `{"detail": "the webhook secret is not configured"}` with no `secret` key and no value. `Settings.webhook_secret` is a plain `str`, read at the response boundary. Decision 1: the webhook message never embeds the secret (its URL carries the placeholder `<your WEBHOOK_SECRET>`), so no payload needs it. Gate: ruff and mypy clean; full suite 2143 tests (2122 + 21), exit 0 on the second run (the first run hit the known PostgreSQL teardown `permission denied to terminate process`).

**Independent security verification of PR 7b (2026-09-29).** It found no critical issue and nothing that blocks.
- Auth is the router-level `require_admin_token`, and both admin and webhook tokens are compared with `hmac.compare_digest`.
- The route is mounted only under `/api`.
- No error, OpenAPI example, `/health` or log carries the secret.
- `no-store` is on both the 200 and the 503.

Follow-ups, left open with the owner's agreement:
- [ ] 7f.1 (W1) CORS is not pinned for production. `allow_credentials=True` with `settings.cors_origins`, whose default is `http://localhost:5173`. A broad or `*` origin would let any script on it that holds the token read the secret. It resolves itself in PR 9, where the SPA is served same-origin. Until then, `CORS_ORIGINS` must not be widened. Optionally, a settings check that refuses `*`.
- [ ] 7f.2 (W2) The secret sweep accepts a write route that answers a trivial 4xx body. Give each non-GET route a real body, as `_BODIES` does for three of them.
- [ ] 7f.3 (W3) The two reconciliation GETs may answer `[]`, so their row serializers are not proven secret-free. Seed one discrepancy and one booking proposal.
- [ ] 7f.4 (S1) The access-log test runs with `lifespan="off"`, so the alert bridge on the root logger is not exercised. Low risk: the route logs nothing.
- [ ] 7f.5 (S2) `/health` and `/webhook/tradingview` are outside the `/api` sweep. They were checked by reading the code, but no test pins them.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/accounts/infrastructure/ backend/tests/performance/infrastructure/ backend/tests/signals/infrastructure/test_webhook_secret_router.py`.
Harness: `httpx.AsyncClient` over the ASGI app.
Rollback boundary: three new routers, each self-contained; revert 404s their paths, nothing else depends on them until PR 11/12.
Forecast: 950–1,350 lines.

---

## PR 8a — Units 6a + 6b + 6c: key policy, inspectors, 0027, `SaveCredential`, trade-capability refusal (1,900–2,600 lines)

**Gate before rules are written**: PR 1's **P1–P3** recorded. No line of `key_policy.py` is
written before "PR 1 — Probe results" carries P1–P3.

**Stale against decision 24 (found 2026-09-29, before any 8a code).** Tasks 6a.1–6a.3 below were
written before the PR 1 probe, and three of their parts are now wrong:
- they test a Binance refusal on `enableWithdrawals`;
- they derive Binance trade capability from `enableFutures`;
- they have the Binance inspector call `GET /sapi/v1/account/apiRestrictions`, which answers
  HTTP 403 from the VPS (P3).

Decision 24 replaces the Binance withdraw check with an explicit owner confirmation, recorded
with its timestamp, and marks the key "withdraw not verified". It leaves Binance trade
capability "to be designed in PR 8a, never assumed". Migration 0027 does not yet record that
confirmation. A design addendum (8a.0b) settles both, and 6a, 6b, 6c, 10c and 10f are rewritten to match.

**Split (proposed in the addendum, § I).** Four sequential PRs to `main`: **8a-1** unit 6a, with migration 0027 (950-1,350); **8a-2** `SaveCredential` and the script fold, 6b.1/6b.4/6b.7 (450-650); **8a-3** the HTTP surface, 6b.2/6b.3/6b.5/6b.6 (400-600); **8a-4** unit 6c (350-500). Tasks below marked "rewritten" changed with decision 30.

**Research on Binance trade capability (2026-09-29, primary docs; verdict UNCERTAIN, leaning NO):**
- `GET /fapi/v2|v3/account` returns `canTrade`, `canDeposit` and `canWithdraw`. The only
  documentation is "Whether trading is enabled", and it does not say whether that is the API
  key's permission or the account's status
  (https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Account-Information-V3).
- No fapi endpoint reports the key's own permissions. The only documented one is SAPI
  `apiRestrictions`, which is unreachable from the VPS.
- `-2015` means "Invalid API-key, IP, or permissions for action". It does not separate a bad
  key from a missing permission
  (https://developers.binance.com/docs/derivatives/usds-margined-futures/error-code).
- Community reports, which are not primary, say a key without "Enable Futures" gets `-2015` on
  every signed fapi call, reads included (https://github.com/ccxt/ccxt/issues/7822).
- If that holds, the live fapi read that rule 8a already requires on save proves trade
  capability for Binance by itself. With one key per exchange (decision 18), there is no
  futures-readable read-only key.

- [x] 8a.0a Probe P6, GET-only, owner-run on the VPS. It compares the vault key (trade-enabled)
  with a temporary Binance key that has only "Enable Reading". It calls
  `GET /fapi/v3/account`, `/fapi/v2/account`, `/fapi/v3/balance`, `/fapi/v3/positionRisk`,
  `/fapi/v1/apiTradingStatus` and `/fapi/v1/account/permissions`. For each call it records the
  HTTP status, the code and msg, and `canTrade`/`canDeposit`/`canWithdraw`. It never sends
  anything but GET, prints each key's last four characters only, and never prints a payload
  beyond those fields. The owner deletes the temporary key afterwards.
  - **Results (owner ran it on the VPS, 2026-09-29, PR #25 merged as `5deb0fe`).** The vault key
    was `***3h2M`; the temporary key, with only "Enable Reading", was `***aWaE`.

    | Call | Vault key | Read-only key |
    | --- | --- | --- |
    | `GET /fapi/v3/account` | 200, no `can*` fields | 200, no `can*` fields |
    | `GET /fapi/v2/account` | 200, `canTrade`/`canDeposit`/`canWithdraw` all True | 200, **all True** |
    | `GET /fapi/v3/balance` | 200, 11 entries | 200, 11 entries |
    | `GET /fapi/v3/positionRisk` | 200, 0 entries | 200, 0 entries |
    | `GET /fapi/v1/apiTradingStatus` | 200 | 200 |
    | `GET /fapi/v1/account/permissions` | 404 | 404 |

  - **Verdict.** A key WITHOUT "Enable Futures" reads every fapi endpoint. The community reports
    were wrong, at least today. `canTrade` and `canWithdraw` are ACCOUNT-level: both are True on a
    key that can neither trade futures nor withdraw.
  - **Consequences.**
    - Nothing reachable from the VPS reveals a Binance key's trade or withdraw permission.
    - The save-time live read (8a) proves nothing about trading.
    - `canWithdraw` does not replace decision 24's confirmation.
    - v3 account no longer carries the `can*` fields.
  - The owner chose a manual confirmation for trade capability (decision 30).
- [x] 8a.0b Design addendum from P6. **Written 2026-09-29** as design.md "Addendum: key policy after probe P6 (decisions 24 and 30)". **Confirmed by the owner on 2026-09-29** with the recommended answers to Q1–Q3 and the four-PR split (§ J). It settles:
  - how Binance `trade_capable` is derived;
  - how decision 24's withdraw confirmation is stored (a column in 0027, with its timestamp);
  - how "withdraw not verified" reaches the credential view;
  - tasks 6a.1–6a.3 and 6a.8 rewritten to match.
  The owner confirms the addendum before 6a starts. Open questions Q1-Q3 (the existing Binance key's backfill, a confirm-only path, Pionex) are listed at its end.

### Unit 6a — key policy + inspectors + migration 0027 (800–1,100 lines)

**Files**: Create `backend/src/strategy_manager/accounts/domain/key_policy.py`; Create
`backend/src/strategy_manager/accounts/infrastructure/key_inspectors/{bybit,binance,registry}.py`;
Modify `backend/src/strategy_manager/accounts/domain/exchange_credential.py`; Create
`backend/migrations/versions/0027_credential_snapshot.py`.

- [x] 6a.1 RED `backend/tests/accounts/domain/test_key_policy.py` (rewritten 2026-09-29, decision 30), withdraw side: `::test_evaluate_key_refuses_withdraw_permission_bybit_wallet_withdraw` (P1 fixture), `::test_evaluate_key_allows_internal_transfer_only_accounttransfer`, `::test_evaluate_key_bybit_wallet_token_outside_the_transfer_allowlist_refused_fail_closed`, `::test_evaluate_key_bybit_missing_or_non_list_wallet_refused_permissions_unavailable`, `::test_evaluate_key_bybit_confirmation_true_refused_confirmation_not_applicable`, `::test_evaluate_key_binance_without_both_confirmations_refused_confirmation_required_naming_missing` (parametrised: neither, only withdrawals, only futures; `check_confirmations` refuses the same way before any venue call), `::test_evaluate_key_binance_with_both_confirmations_accepted_withdraw_check_owner_confirmed_never_verified`, `::test_evaluate_key_unserved_exchange_raises_no_fallback`. **Done:** RED seen on assertions against a wrong-answer stub, GREEN in `tests/accounts/domain/test_key_policy.py` (8a-1, commit 2); gate green.
- [x] 6a.2 RED same file (rewritten 2026-09-29, decision 30), trade side: `::test_evaluate_key_bybit_readonly_zero_trade_capable_true_source_verified` (P2), `::test_evaluate_key_bybit_readonly_one_trade_capable_false_verified_warning_read_only_key` (the P2 read-only fixture, whose permission lists still show `ContractTrade`), `::test_evaluate_key_bybit_never_reads_the_permission_lists_for_trade_capability`, `::test_evaluate_key_binance_trade_capable_true_source_owner_confirmed_from_the_futures_confirmation`. **Done:** RED and GREEN in the same file; `readOnly` alone decides, the snapshot cannot carry the permission lists (structural test). Gate green.
- [x] 6a.3 RED `backend/tests/accounts/infrastructure/test_key_inspectors.py` (rewritten 2026-09-29, decision 30): `::test_bybit_inspector_calls_wallet_balance_and_query_api_never_an_order` (`httpx.MockTransport`, probe-recorded shapes), `::test_binance_inspector_calls_fapi_v3_account_only_never_sapi_never_an_order`, `::test_binance_inspector_ignores_can_trade_and_can_withdraw_p6_fixture_snapshot_stays_empty` (the P6 v2 payload with all three `can*` True), `::test_binance_inspector_maps_2014_2015_1022_to_key_rejected_and_5xx_to_venue_unreachable`, `::test_registry_dispatches_by_exchange_unserved_raises`. **Done:** RED and GREEN in `tests/accounts/infrastructure/test_key_inspectors.py`, `httpx.MockTransport` recording every method and path; the P6 v2 payload leaves the snapshot empty. Gate green.
- [x] 6a.4 RED `backend/tests/migrations/test_0027_credential_snapshot.py` (rewritten 2026-09-29, decision 30): `::test_backfill_every_existing_row_trade_capable_true_both_sources_unrecorded_no_timestamps`, `::test_default_is_dropped_insert_without_trade_capable_or_sources_fails`, `::test_binance_row_cannot_be_verified_check_refuses`, `::test_bybit_row_cannot_be_owner_confirmed_check_refuses`, `::test_owner_confirmed_requires_its_timestamp_and_the_timestamp_requires_owner_confirmed_both_columns`, `::test_owner_confirmed_trade_source_requires_trade_capable_true`, `::test_validated_at_is_null_exactly_when_unrecorded`, `::test_downgrade_refuses_while_any_row_is_not_the_backfill_shape_naming_each_count`, `::test_downgrade_succeeds_on_a_pure_backfill_shape`. **Done:** RED against the missing migration (revision assertion fails, the rest UndefinedColumn), then GREEN: 28 tests in `tests/migrations/test_0027_credential_snapshot.py` on real PostgreSQL, each of the six constraints refusing its bad state asserted by name. Gate green.
- [x] 6a.5 GREEN (rewritten 2026-09-29, decision 30): `key_policy.py` with `PermissionSnapshot` (`wallet_permissions`, `read_only`, both `None` for Binance), `OwnerConfirmations`, `KeyVerdict` (`KeyAccepted` | `KeyRefused`), `check_confirmations`, `evaluate_key(exchange, snapshot, confirmations)` and `KEY_POLICIES`. Pure; 8a is the inspector's, not this function's. `canTrade`/`canWithdraw` appear nowhere. **Done:** `accounts/domain/key_policy.py` (pure; `canTrade`/`canWithdraw`/`ContractTrade`/`Derivatives` absent from the code, asserted by an AST test). Gate green.
- [x] 6a.6 GREEN (rewritten 2026-09-29, decision 30): RED first `backend/tests/accounts/domain/test_exchange_credential.py::test_key_facts_owner_confirmed_requires_its_timestamp`, `::test_key_facts_unrecorded_requires_no_timestamps_and_both_sources_together`, `::test_key_facts_has_no_default_every_constructor_names_every_field`. Then `KeyFacts` in `exchange_credential.py` (no secret; `__post_init__` enforces the same states as constraints 2-4; `KeyFacts.unrecorded(trade_capable)` is the only named constructor). `CredentialHint` gains `facts`. `ExchangeCredential` is unchanged. **Done:** RED on assertions, then GREEN: `KeyFacts` in `exchange_credential.py`, `CredentialHint.facts`, `ExchangeCredential` still secret-only (`hint(facts)` hands them through). Gate green.
- [x] 6a.7 GREEN (rewritten 2026-09-29, decision 30): `BybitKeyInspector` (wallet-balance read, then `query-api`, mapped to a `PermissionSnapshot`), `BinanceKeyInspector` (`GET /fapi/v3/account` only, returns an empty snapshot), `KeyInspectorRegistry`. Never an order. **Done:** `accounts/infrastructure/key_inspectors/{bybit,binance,registry}.py`, GET-only, no `trade_client` import (asserted). Gate green: ruff, mypy and the full suite, 2210 collected.
- [x] 6a.8 GREEN (rewritten 2026-09-29, decision 30): `migrations/versions/0027_credential_snapshot.py` adds `trade_capable`, `trade_capability_source`, `trade_confirmed_at`, `withdraw_check`, `withdraw_confirmed_at`, `validated_at`, `internal_transfer` and the six `ck_exchange_credentials_*` constraints of design § B; there is NO `permissions` column. `trade_capable` is added `DEFAULT true` and backfilled `true`; both sources are backfilled `UNRECORDED`; the defaults are then dropped. The downgrade refuses while any row is not the backfill shape, naming each count. Rehearse on a throwaway database restored from a fresh backup, before production migrates. **Done:** `migrations/versions/0027_credential_snapshot.py`, no `permissions` column, backfill true/UNRECORDED, defaults dropped, downgrade refuses naming four counts. Rehearsal on a restored production backup is the owner's deploy step (design § K). Gate green.
- [x] 6a.9 (added 2026-09-29, decision 30) RED `backend/tests/accounts/infrastructure/test_credential_vault.py::test_store_persists_facts_and_hints_return_them_never_ciphertext`, `::test_store_without_facts_is_a_type_error`. GREEN: `SqlAlchemyCredentialVault.store(credential, facts)`, `hints()` returning `facts`, and the ORM columns. The three `store_*_credentials.py` scripts pass `KeyFacts.unrecorded(trade_capable=True)` (one line each, exactly what they have always asserted), so they keep working once 0027 drops the default; 6b.7 replaces this. **Done:** RED then GREEN in `test_credential_vault_integration.py` (the file that exists); vault `store(credential, facts)`, `hints()` returns the facts; the three scripts pass `KeyFacts.unrecorded(trade_capable=True)` (pinned by `tests/scripts/test_store_scripts_pass_facts.py`). Gate green: ruff, mypy and the full suite, 2252 collected.

**Follow-up S2 (8a-1 verification), for PR 8a-3:** httpx and httpcore INFO logs render signed Binance URLs (the signature is in the query), and only the worker silences them to WARNING. PR 8a-3 must apply the same setting in the API startup before it runs any inspector. **Done (8a-3, commit 1):** `shared/infrastructure/http_logging.py::silence_http_client_info_logs`, called first in `create_app()` and by the worker's `_configure_logging`. `tests/shared/infrastructure/test_http_client_logging.py` (4 tests): a signed Binance inspector request in the API process logs no query string and no signature; RED on the assertion (the record carried `signature=`), and seen red again with the call removed from `create_app()`. The same request WITHOUT the setting does log the signature, so the test can fail.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/accounts/ backend/tests/migrations/test_0027_credential_snapshot.py`.
Harness: `httpx.MockTransport` for inspectors (no real credential, rule 1); real PostgreSQL for the migration.
Rollback boundary: migration 0027 (refuses downgrade while any row is not the backfill shape) + new domain/infra files; revert leaves every existing store script working unchanged.
Forecast: 950–1,350 lines (revised 2026-09-29: provenance columns, `KeyFacts`, the extra tests).

### Unit 6b — `SaveCredential`, credential endpoints, redacted 422, store scripts (750–1,000 lines)

**Files**: Create `backend/src/strategy_manager/accounts/application/save_credential.py`;
Modify `backend/src/strategy_manager/accounts/application/ports.py` (`CredentialWriterPort`, `KeyInspectorPort`);
Modify `backend/src/strategy_manager/accounts/infrastructure/{credential_vault,models,credentials_router}.py`;
Create `backend/src/strategy_manager/shared/infrastructure/validation_errors.py`; Modify
`backend/scripts/store_{bybit,binance,pionex}_credentials.py`.

- [x] 6b.1 RED `backend/tests/accounts/application/test_save_credential.py` (rewritten 2026-09-29, decision 30): `::test_key_rejected_by_venue_refuses_stores_nothing_422`, `::test_venue_unreachable_reported_distinctly_502`, `::test_withdraw_permission_refuses_stores_nothing_422`, `::test_readonly_key_stored_trade_capable_false_warning_returned_200`, `::test_trading_key_stored_no_warning_returned_200`, `::test_binance_without_confirmations_refused_before_any_venue_call_stores_nothing` (the fake inspector asserts it was never called), `::test_binance_with_both_confirmations_stores_owner_confirmed_with_server_clock_timestamps`, `::test_bybit_confirmation_true_refused_not_applicable_stores_nothing`, `::test_bybit_stores_verified_facts_and_no_confirmation_timestamps`, `::test_rotation_never_inherits_the_previous_keys_confirmations`, `::test_concurrent_save_second_refused_409_by_constraint_name_not_message` (imports `ux_exchange_credentials_one_active_per_exchange` as a named constant, following the CONCURRENT_SAVE constraint-name-matching precedent), `::test_rotation_deactivates_previous_row_retains_it`. **Done (8a-2, commit 1):** every named test is in `tests/accounts/application/test_save_credential.py` (they assert the typed OUTCOME; the 422/502/200/409 in the names are the router's mapping in 8a-3). RED on assertions against a wrong-answer stub that always answered `CONCURRENT_SAVE` (26 failed; the 3 that passed were the two negative vault cases and the no-`load` structural test, each broken by mutation and seen red). GREEN plus `tests/accounts/infrastructure/test_credential_vault_constraint_name.py`: 29 new tests. Added beyond the list: Binance missing one confirmation (parametrised), Bybit with either confirmation, `PERMISSIONS_UNAVAILABLE`, unserved exchange raises, one clock reading for every timestamp (a ticking clock), a Binance rotation refused for its confirmations leaves the active key untouched, and five logging tests. Mutations seen red: venue before `check_confirmations` (10 failed), CONCURRENT_SAVE matched on message text (3), the key in the INFO line (1), a second clock read (2), unreachable logged at ERROR (3), commit on a lost race (1), no savepoint (1). Gate green, 2286 collected (baseline 2257).
- [x] 6b.2 RED `backend/tests/accounts/infrastructure/test_credentials_router.py` (rewritten 2026-09-29, decision 30): `::test_put_credentials_returns_last4_and_facts_never_the_key_or_secret_or_a_raw_payload`, `::test_get_credentials_shows_source_and_confirmation_fields_never_live_requery`, `::test_get_credentials_entries_have_no_permissions_key`, `::test_put_binance_missing_confirmation_422_names_the_missing_field`, `::test_put_bybit_true_confirmation_422_not_applicable`. **Done (8a-3, commit 2):** the five named tests plus 34 more in the same file, and `test_credentials_logging.py` (one real-uvicorn test). PUT tests run the real `SaveCredential` over the fakes of `tests/accounts/fakes.py` (a recording inspector, so "zero venue calls" is an assertion); GET tests run on real PostgreSQL with the real vault and a cipher that raises on any decrypt. Added beyond the list: a Binance PUT missing a confirmation answers 422 `CONFIRMATION_REQUIRED` with `missing` and makes ZERO venue calls (four shapes); Bybit with either confirmation true is `CONFIRMATION_NOT_APPLICABLE`, with both false is fine; every refusal (KEY_REJECTED, VENUE_UNREACHABLE, WITHDRAW_PERMISSION, PERMISSIONS_UNAVAILABLE, CONCURRENT_SAVE) maps to its status with the one body shape; the outcome map covers every `SaveOutcome`; an unserved exchange is 404; a client cannot supply a fact or a time (`extra=forbid`); five bad bodies and a malformed one echo neither key nor secret; a missing or wrong token is 401 on both routes; an unusable master key is 503 plus one ERROR; the GET after a Binance save shows `OWNER_CONFIRMED` with both timestamps, makes no second venue call and never decrypts; the listing rule (enabled pool only, history only, neither, a rotation is one entry, a legacy row is `UNRECORDED`). RED on assertions against a stub router that answered a fixed wrong body: 35 of 39 failed (`200 == 422`, `[] == ['READ_ONLY_KEY']`, ...). The 4 that passed on the stub were proven by mutation: dropping the router's auth (2 failed), putting the key in the response (3), `extra=ignore` (5), CONCURRENT_SAVE mapped to 422 (2), VENUE_UNREACHABLE mapped to 422 (2), the pool union removed from the listing (2), the history rows removed (1), a ciphertext column selected (1). The log test: the body's secret logged (1 failed), the key logged (1), httpx INFO back (1), the 422 echoing `input` (1, plus 4 in the router file).
- [x] 6b.3 RED `backend/tests/shared/infrastructure/test_validation_errors.py::test_422_never_echoes_api_secret_input_or_ctx`. **Done (8a-3, commit 1):** parametrised over seven failure kinds (malformed JSON, an object as the secret, a list as the key, an extra field, a missing field, a `max_length` constraint that yields `ctx`, a validator whose own `ValueError` quotes the value), against a mini app with a credential-shaped body and against `create_app()`. RED on assertions against a stub that answered FastAPI's default (`input`/`ctx` present, sentinels echoed): 11 failed. Mutations seen red: `input` echoed (10 failed), the errors logged (6), the authored-`msg` guard removed (1). 18 tests.
- [x] 6b.4 GREEN (rewritten 2026-09-29, decision 30): `SaveCredential` runs `check_confirmations` (no venue call yet), then inspect, `evaluate_key`, stamps `KeyFacts` from the `ClockPort` (`validated_at`, and both confirmation timestamps when owner-confirmed), stores (supersede) and commits. `CredentialWriterPort` has no `load`. **Done (8a-2, commit 1):** `accounts/application/save_credential.py` (`SaveCredential.execute(credential, confirmations)` returning `Saved | SaveRefused`), `CredentialWriterPort` (no `load`) and `KeyInspectorRegistryPort` in `ports.py`, `ConcurrentCredentialSave` in `errors.py`, and the vault's `store` now translates the one-active constraint, by name, inside a SAVEPOINT. Design section K, 8a-2. Gate green.
- [x] 6b.5 GREEN: `redacted_validation_handler` — one `RequestValidationError` handler for the whole app, strips `input`/`ctx`. **Done (8a-3, commit 1):** `shared/infrastructure/validation_errors.py`, registered once in `create_app()`. Each error keeps only `type`, `loc`, `msg`; `msg` is replaced by "Invalid value" for `value_error` and `assertion_error` (a validator's own text can quote the value). It logs nothing. Design section K4.
- [x] 6b.6 GREEN (rewritten 2026-09-29, decision 30): `PUT /api/credentials/{exchange}` on `credentials_router`, body gaining `withdrawals_disabled_confirmed` and `futures_enabled_confirmed` (default false); outcomes `CONFIRMATION_REQUIRED` (with `missing`), `CONFIRMATION_NOT_APPLICABLE` and `PERMISSIONS_UNAVAILABLE` join the 422s. `GET /api/credentials` returns the entry of design § C (no `permissions`), with the same listing rule (one entry per exchange with an active credential, a history row, or an enabled pool). **Done (8a-3, commit 2):** `accounts/infrastructure/credentials_router.py` (`PUT` -> `SaveCredential`, `GET` -> `SqlAlchemyCredentialListing`), `credential_listing.py`, `accounts/domain/credential_overview.py`, mounted in `create_app()` under `/api`. Outcome map: KEY_REJECTED, WITHDRAW_PERMISSION, PERMISSIONS_UNAVAILABLE, CONFIRMATION_REQUIRED, CONFIRMATION_NOT_APPLICABLE 422; VENUE_UNREACHABLE 502; CONCURRENT_SAVE 409; an unserved exchange 404; an unusable master key 503. The route sweep (`test_webhook_secret_router.py`) gives the PUT a real body (must answer 200 with `last4`), seeds an active key so `GET /api/credentials` answers a STORED entry, and overrides the use case with a fake venue. The webhook secret appears in neither response (mutations that put it in `last4` and in `label` failed the sweep). Design section K5. Gate green.
**Independent security verification of PR 8a-3 (2026-09-30).** It found no blocker.

Checked clean:
- Auth is the router-level `require_admin_token` with `hmac.compare_digest`, mounted only under `/api`; an unserved exchange answers 404 only after authentication.
- The key and secret are absent from every response, header, OpenAPI schema and log.
- Refusal details are built from fixed strings with `from None`; the body is `extra="forbid"`.
- `GET` never decrypts and `PUT` never loads (`CredentialWriterPort` has no `load`).
- httpx does not follow redirects: a 302 from the venue is `VenueUnreachable`.
- A lost race uses a savepoint and answers 409, matched by constraint name.
- `credential_cli.py` still reads secrets with `getpass`.

Fixed in this PR (`cfeb888`):
- **W1** No `Cache-Control: no-store` on `/api/credentials`. Fixed with `shared/infrastructure/no_store.py::NoStoreMiddleware`, a pure ASGI middleware scoped to `/api/credentials` and registered in `create_app()`. A dependency would not reach answers built by exception handlers. Tests: every PUT answer (200, 401 missing and wrong token, 404, 409, 422 validation, 422 malformed JSON, 422 typed refusal, 502), GET 401 and GET 200 (PostgreSQL), the 503, and `/health` proven unchanged. RED on `None == 'no-store'`. Mutations seen red: middleware prefix pointed elsewhere (3 failed), middleware unscoped (1, the scope test).
- **W2** Non-ASCII, whitespace or control characters in the key or secret crashed the real inspector (`UnicodeEncodeError`, 500), or became a misleading 502, or produced a `last4` like `"AAA "`. Fixed declaratively in `CredentialBody`: `StringConstraints(pattern=^[\x21-\x7E]+$)` on both. The secret is now `Secret[...]` over the constrained `str`, because `SecretStr` cannot carry a pattern; `repr` stays masked. Tests: non-ASCII, space, trailing space, tab, newline and 257 characters, each for key and secret, answer 422 with zero venue calls, nothing stored and the value in neither the body nor the logs; exactly 256 printable characters is accepted; the body `repr` hides the secret. RED on `assert 200 == 422` (12 cases). Mutations seen red: pattern allowing `\n` (2), allowing non-ASCII (2), allowing a space (4), secret as a plain `str` (7, including the `repr` test).
- **S1** No `max_length`. Fixed with 256 on both. Mutation `max_length=255` turned the exactly-256 acceptance test red (2).

Follow-ups, left open with the owner's agreement:
- [ ] 8f.1 (S2) The SQLAlchemy engine does not set `hide_parameters`. A non-race `IntegrityError` or `DBAPIError` in `store()` would log bound parameters (ciphertexts, wrapped DEK, nonces, last4, label; never plaintext), and `alert_log_bridge.py` formats `exc_info` into Telegram messages for any root-logger ERROR. Pre-existing.
- [ ] 8f.2 (S3) A malformed JSON body answers 422 before authentication, because FastAPI parses the body before dependencies. The 422 is redacted, so nothing leaks; it only reveals that the route exists and makes the server buffer the body. Pre-existing framework behaviour.
- [ ] 8f.3 (S4) The production wiring (`get_save_credential` with the real `KeyInspectorRegistry.for_settings`) is covered only by the 503 test; the real inspectors are exercised only by the log test.

Gate after the fixes: ruff and mypy clean; full suite exit 0 on the second run (the first hit the known PostgreSQL teardown), 2447 collected.

- [x] 6b.7 GREEN (rewritten 2026-09-29, decision 30): fold `store_bybit_credentials.py` and `store_binance_credentials.py` onto `SaveCredential`. RED first `backend/tests/scripts/test_store_binance_credentials.py::test_without_both_confirmation_flags_exits_2_names_the_missing_one_prompts_for_nothing_stores_nothing`, `::test_with_both_flags_saves_owner_confirmed_and_prints_last4_only`, and `backend/tests/scripts/test_store_bybit_credentials.py::test_read_only_key_is_stored_with_a_warning_not_refused`. `store_binance_credentials.py` drops its `apiRestrictions` call and takes `--confirm-withdrawals-disabled` and `--confirm-futures-enabled` (no environment variable, no `--yes`, no default). `store_pionex_credentials.py` is NOT folded: it keeps sealing directly with `KeyFacts.unrecorded(trade_capable=True)` (design § J, Q3). **Done (8a-2, commit 2):** `store_binance_credentials.py` and `store_bybit_credentials.py` are thin over the new `scripts/credential_cli.py` (prompt, `vault_saver`, `run_store`, the report), which calls `SaveCredential`. Binance: the SAPI call is gone; `--confirm-withdrawals-disabled` and `--confirm-futures-enabled`, no env var, no `--yes`, no default, no abbreviation; without both it names only the missing flag(s) on stderr and exits 2 before the master-key check, the prompt and any saver. Bybit: no flags; a read-only key is stored with a `READ_ONLY_KEY` warning. Pionex is unchanged and pinned by the structural test. RED on assertions (exit code 99 from a stub `main`), then GREEN: 48 net new tests (`tests/scripts/test_store_binance_credentials.py`, `test_store_bybit_credentials.py`; the interim `test_store_scripts_pass_facts.py` now pins Pionex and forbids a direct `vault.store` in the folded scripts). Mutations seen red: prompt before the flag check (13 failed), an env var confirming (8), a flag defaulting true (3), abbreviations on (1), a `--yes` flag (1), the key printed (4), prompt before the master-key check (2), a read-only key refused by the script (1), confirmations bypassed (7). Gate green, 2334 collected.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/accounts/ backend/tests/shared/infrastructure/test_validation_errors.py`.
Harness: fakes for `SaveCredential`; `httpx.AsyncClient` for the router; real vault for rotation/supersede.
Rollback boundary: `save_credential.py` + router changes; revert leaves the store scripts' pre-fold behavior, no data loss (rotation history is retained regardless).
Forecast: 850–1,150 lines (revised 2026-09-29: confirmations, script flags).

### Unit 6c — `TradeCapabilityPort`, adapters, read-only/no-key opening refusal (350–500 lines)

**Files**: Create `backend/src/strategy_manager/accounts/infrastructure/trade_capability_adapter.py`;
Modify `backend/src/strategy_manager/signals/application/process_signal.py`, `application/ports.py` (`TradeCapabilityPort`); Modify `backend/src/strategy_manager/main.py` (DRY_RUN-based wiring).

- [x] 6c.1 RED `backend/tests/signals/application/test_process_signal.py::test_live_open_on_readonly_exchange_refused_before_lock_one_warning_names_exchange` (`DRY_RUN=false`, `READ_ONLY`). **Done (8a-4, commit 25b7636):** a shared helper drives both refusal tests over a Bybit `usdt-m` strategy with the signal spelled `STXUSDT.P` and the allowed pair spelled `STXUSDT`. It asserts: the handler asked the port about `bybit`; no lock, no engine entry (`SpyAllocateCapital.calls == []`), no reservation, no order, no balance refresh; the Existing-Position Guard is never consulted (an `_ExplodingGuard` fails the test if it is); exactly one WARNING, equal to `result.refused`, naming the exchange, the signal, the strategy and "cannot trade"; and one `REJECTED` outcome with code `EXCHANGE_KEY_READ_ONLY` whose detail is the logged text. The reason code was not fixed by the design, so it is new (see the discrepancy note under 6c.8). Also added: `test_a_trade_capable_exchange_opens_exactly_as_before`, `test_the_unlisted_pair_refusal_comes_before_the_capability_check` (an unlisted pair on a keyless exchange says `PAIR_NOT_ALLOWED` and the port is never asked), and `test_open_now_continuation_refuses_a_readonly_exchange_and_says_the_close_executed` (a REVERSE's open half, decision 26). RED on assertions against a handler that took the port and ignored it: the guard-ran assertion (2), `assert [] == ['bybit']` (1), `assert None is not None` on `result.refused` (1).
- [x] 6c.2 RED same file `::test_close_on_readonly_exchange_not_refused_by_this_rule`. **Done (8a-4, commit 25b7636):** runs a close for both `READ_ONLY` and `NO_KEY`; the close is placed, `refused is None`, the port is never asked (`asked == []`), zero WARNINGs. It passed against the pre-implementation stub, so it was proven by mutation: the check also run on the release path turned it red (1 failed).
- [x] 6c.3 RED same file `::test_dry_run_true_readonly_key_refuses_nothing`. **Done (8a-4, commit 25b7636):** the handler has no `dry_run` flag; `DRY_RUN=true` is expressed by wiring `DryRunTradeCapability`, exactly as design § 4a's table says ("`DryRunTradeCapability` is wired"). The test wires it, opens on an exchange that would be `READ_ONLY` live, and asserts the order is placed, the lock is taken once and no outcome is recorded. It passed immediately, so it was proven by mutation: `DryRunTradeCapability` answering `READ_ONLY` turned it red (this test and the adapter file's dry-run test, 2 failed). The wiring itself is pinned by `tests/test_main_trade_capability_wiring.py`.
- [x] 6c.4 RED same file `::test_live_open_on_keyless_no_key_exchange_refused_before_lock_one_warning_names_exchange` (decision 20's `NO_KEY` case). **Done (8a-4, commit 25b7636):** the same helper as 6c.1 with `NO_KEY`: code `EXCHANGE_HAS_NO_KEY`, WARNING text `... refused: bybit has no active key; store one (Settings); no capital reserved`, not the read-only wording. RED on the same assertions as 6c.1.
- [x] 6c.5 RED `backend/tests/accounts/infrastructure/test_trade_capability_adapter.py` (rewritten 2026-09-29, decision 30): `::test_vault_adapter_answers_trade_capable_without_decrypting` (a row with garbage ciphertext still answers: a single indexed column read, never `.load(`), `::test_owner_confirmed_binance_row_answers_trade_capable`, `::test_unrecorded_row_answers_from_the_trade_capable_column`. **Done (8a-4, commit 25b7636):** nine tests on real PostgreSQL. Every seeded row carries garbage in all six secret columns. The three named tests, plus: a read-only Bybit key answers `READ_ONLY`; an exchange with no row answers `NO_KEY`; another exchange's trade-capable key does not vouch for this one; a deactivated row answers `NO_KEY` (decision 22); a rotation answers from the new active row, not the history (decision 18); and `DryRunTradeCapability` answers `TRADE_CAPABLE` for any name. The "without decrypting" test also captures the SQL sent (`before_cursor_execute`): exactly one statement, naming `trade_capable` and none of `ciphertext`, `nonce`, `wrapped_dek`. RED on assertions against a stub adapter that always answered `NO_KEY` (7 failed, `assert NO_KEY is TRADE_CAPABLE`). The 2 that passed on the stub (no row, deactivated) were proven by mutation. A first run failed on the test's own seed (`ck_exchange_credentials_binance_not_verified`: a Binance row cannot be `VERIFIED`), fixed in the test before the RED count above.
- [x] 6c.6 RED `backend/tests/accounts/test_no_decrypt_in_api_path.py::test_credentials_router_and_save_credential_never_call_dot_load` — structural test (decision 5), grep/AST-based, asserting no reference to `.load(` under `credentials_router.py` or `save_credential.py`. **Done (8a-4, commit 25b7636):** AST-based, no database: it looks for any `Attribute` node named `load`, so a comment or docstring that mentions `.load(` does not trip it. It also guards `trade_capability_adapter.py` (design § "The API process decrypts": "`VaultTradeCapabilityAdapter` reads columns only"). Beside it: a self-test that the checker sees `vault.load(...)` in a call, in a bare reference, and ignores a comment and a docstring; and a parametrised test that each guarded file exists and parses, so a moved file cannot make the guard vacuous. It passed immediately (the modules never call `load`), so it was proven by mutation: a `vault.load('bybit')` added to `save_credential.py` (1 failed), to `credentials_router.py` (1) and to the adapter (1).
- [x] 6c.7 GREEN: `VaultTradeCapabilityAdapter` (`SELECT exchange, trade_capable WHERE is_active`, never decrypts), `DryRunTradeCapability` (always `TRADE_CAPABLE`); wired in `main.py` by `DRY_RUN` like the exchange adapters. **Done (8a-4, commit 25b7636):** `accounts/infrastructure/trade_capability_adapter.py`: `select(trade_capable).where(exchange == :e, is_active)`, `scalar_one_or_none()`; no row is `NO_KEY`, never a default of `TRADE_CAPABLE`. It selects no ciphertext column and has no cipher. Wired in `main.py::_build_process_signal_handler` (the worker's composition root: `handle_signal_process` and `handle_signal_open_after_close` both build the handler through it, and the API never builds one), `DryRunTradeCapability()` if `settings.dry_run` else `VaultTradeCapabilityAdapter(session)`. `tests/test_main_trade_capability_wiring.py` (no DB, an unconnected `AsyncSession`): dry-run wires the dry-run answer, live wires the vault adapter, and `build_worker_runner` names neither adapter (both call sites go through the one builder). RED on `isinstance(VaultTradeCapabilityAdapter, DryRunTradeCapability)` against a placeholder that always wired the vault adapter. Mutations seen red: the adapter ignoring `is_active` (2 failed), answering `TRADE_CAPABLE` for a missing row (3), also selecting a ciphertext column (1), inverting the column (6), `DryRunTradeCapability` answering `READ_ONLY` (2), and the `DRY_RUN` condition inverted in `main.py` (2).
- [x] 6c.8 GREEN: `ProcessSignalHandler._refuse_read_only_exchange` at the top of `_handle_consumes`, after the unlisted-pair refusal (2b) and before the Existing-Position Guard. **Done (8a-4, commit 25b7636):** `process_signal.py`: `ProcessSignalHandler` takes a required `trade_capability: TradeCapabilityPort` (no default: a missing wire fails loudly instead of guessing), asks it for `policy.exchange` right after the unlisted-pair refusal, and refuses anything but `TRADE_CAPABLE` through `_reject` (one WARNING, one `REJECTED` outcome, one commit, like the other pre-lock refusals). `TradeCapability` and `TradeCapabilityPort` live in `signals/application/ports.py`. It takes no lock. **Task-wording discrepancies and resolutions:** (1) design § B's reason-code table has no code for this refusal, and the task says only that it must not be silent, so two stable codes were added: `EXCHANGE_KEY_READ_ONLY` and `EXCHANGE_HAS_NO_KEY` (design rows 22 and 23). They are two codes because the owner's fix differs: store a key that can trade, versus store a key at all. (2) The WARNING text extends design § 4a's with the strategy id and "no capital reserved", to match the sibling refusals; it keeps the signal, the strategy name, the exchange and the Settings pointer. (3) The design table says `DRY_RUN=true` "proceeds" through `DryRunTradeCapability`, so the handler carries no `dry_run` flag. (4) The task list puts the port in `process_signal.py` (design table) and `application/ports.py` (task Files); it is in `ports.py`, beside the other signal-side ports. The four other constructions of `ProcessSignalHandler` in tests take a shared `FakeTradeCapability` (`tests/signals/fakes.py`). Mutations seen red: the check moved after the Existing-Position Guard (2 failed), moved before the unlisted-pair refusal (1), also run on the release path (1), the refusal logging but recording no outcome (3), the refusal writing no WARNING (3). **Gate:** `ruff check .` exit 0, `mypy src` exit 0 (263 files), `pytest --tb=short` exit 0 on the first run, 2471 collected (2447 + 24: 7 handler, 9 adapter, 5 structural, 3 wiring).

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/signals/ backend/tests/accounts/`.
Harness: fakes; the structural test runs with no DB.
Rollback boundary: one adapter pair + one refusal method; revert removes both, live opens on a read-only/keyless exchange fail at the venue as before this change (the accepted residual race, unchanged).
Forecast: 350–500 lines.

---

## PR 8b — Units 6d + 6e: pool auto-enable, `DeleteCredential` (1,000–1,450 lines)

**Needs**: PR 8a (`SaveCredential`'s transaction to hook into) and PR 5 (pool-lock adapter,
`StrategyExposurePort` query shape reused and widened).

### Unit 6d — `KNOWN_FUTURES_POOLS`, `CapitalPoolWriterPort`, pool auto-enable on save (300–450 lines)

**Files**: Create `backend/src/strategy_manager/accounts/domain/known_pools.py`; Modify
`backend/src/strategy_manager/accounts/application/{ports,save_credential}.py`; Create
`backend/src/strategy_manager/accounts/infrastructure/capital_pool_writer.py`.

- [x] 6d.1 RED `backend/tests/accounts/domain/test_known_pools.py::test_bybit_maps_to_usdt_m_usdt`, `::test_binance_maps_to_usdt_m_usdt`. **Done (8b-1, commit b7d1d1c):** both pin `(usdt-m, USDT)`. Also pinned: the constant names exactly `{bybit, binance}` (Pionex outside it), no entry is `spot` or `coin-m` (rule 5: one unified Bybit USDT balance must not back two pools), the mapping is immutable, `default_min_order_size` equals the seeded `usdt-m` row's 5 (migration 0003), `known_pool_for` reads by plain string, and an exchange without a pool raises with no fallback. **Discrepancy resolved:** decision 21 and the design say "Bybit linear/USDT"; `Venue` has only `spot`/`usdt-m`/`coin-m`, so the Bybit pool is venue `usdt-m`, the row production already holds (0017/0018). RED on assertions against a wrong-answer stub (`bybit -> spot`, min 10, plus a `pionex` entry): venue mismatch, set inequality, `SPOT not in ...`, `Decimal('10') == Decimal('5')`, `DID NOT RAISE` for pionex. Mutation: making the constant a plain `dict` turns the immutability test red.
- [x] 6d.2 RED `backend/tests/accounts/application/test_save_credential.py::test_first_key_saved_for_exchange_enables_its_pool_same_transaction` (Binance, no active credential, pool disabled → enabled). **Done (8b-1, commit b7d1d1c):** real PostgreSQL. A commit spy looks at the database at the instant of the commit, from the caller's own session (pool already `enabled`) and from a second connection (pool still disabled, zero credential rows), then commits: the pool write and the credential share one transaction and one commit. Fake-layer siblings: the call order is `store, enable, commit`; Binance enables only Binance; every refusal (`KEY_REJECTED`, `VENUE_UNREACHABLE`, `WITHDRAW_PERMISSION`, `CONFIRMATION_REQUIRED`, unserved exchange, lost race) leaves `enabled == []` and zero commits; a failing pool write propagates and never commits; on real PostgreSQL a failing pool write leaves no credential row. The lost race is proved on real PostgreSQL (`test_a_lost_race_leaves_the_pool_untouched_even_inside_the_open_transaction`): the loser waits behind the winner's open insert (`not task.done()`), and after `CONCURRENT_SAVE` its OWN still-open session reads the pool as disabled (a write made before the savepoint would still show there, because the savepoint does not cover it). Logging: a save that switches a pool on logs one extra INFO naming the exchange and `usdt-m/USDT`, never a key; a save into an already-enabled pool adds no line. RED (assertions): `[] == ['bybit']`, `[] == ['binance']`, `DID NOT RAISE` x2, `[20] == [20, 20]` (event log), `False is True` (own view of the pool). Mutations: enable before store reds the ordering, both lost-race and Binance tests; commit before enable reds the ordering, both failing-pool tests and the same-transaction test; enable inside the lost-race handler reds both lost-race tests; a `session.commit()` inside the writer reds the same-transaction test; dropping the INFO reds the log test.
- [x] 6d.3 RED same file `::test_resaving_key_for_already_enabled_pool_leaves_min_order_size_unchanged_idempotent`. **Done (8b-1, commit b7d1d1c):** real PostgreSQL; `bybit/usdt-m/USDT` seeded enabled at 7.25, two saves (a rotation), the table afterwards is that one row, enabled, 7.25. It passes against a no-op stub, so it was proven non-vacuous by mutation: an upsert that overwrites `min_order_size` and drops the `WHERE enabled = false` guard turns it red.
- [x] 6d.4 RED `backend/tests/accounts/infrastructure/test_capital_pool_writer.py::test_enable_upserts_from_known_futures_pools_constant_never_request_body`, `::test_enable_on_missing_row_inserts_with_default_min_order_size`. **Done (8b-1, commit b7d1d1c):** real PostgreSQL, ten tests. The first enables `binance` where no Binance row exists and asserts exactly one new row, the constant's identity, no other pool changed. Two tests monkeypatch `KNOWN_FUTURES_POOLS` (a `coin-m/ETH` entry, and a `usdt-m/USDT` entry with default 8.5) so a hard-coded venue, currency or minimum cannot pass by coincidence. Others: enabling a disabled row flips only `enabled` and keeps 7.25 (returns `True`); enabling an enabled row is a no-op returning `False`, twice; enable rolls back with the caller's transaction; `pionex`/`kraken` raise and change nothing; `disable` flips only the existing row (`True` then `False`) and never creates one. `enable` returns whether it changed anything, from `INSERT ... ON CONFLICT DO UPDATE SET enabled = true WHERE enabled = false RETURNING`; the use case uses it for the INFO line. RED against a no-op stub: `assert None == (True, Decimal('0.5'))`, `... (True, Decimal('8.5'))`, `False is True`, `DID NOT RAISE InvariantViolation` x2, `(False, False) == (True, False)`. Mutations: hard-coded venue and currency red the constant-at-call-time test; a hard-coded minimum reds it and the default-size test; `set_` overwriting `min_order_size` reds the disabled-row test; dropping the `WHERE` reds the no-op test; a commit inside `enable` reds the rollback and same-transaction tests.
- [x] 6d.5 RED `backend/tests/accounts/test_no_pool_management_surface.py::test_no_endpoint_or_view_enables_disables_or_configures_a_pool_directly` (a route-inventory test over `app.routes`). **Done (8b-1, commit b7d1d1c):** built from `fastapi.routing.iter_route_contexts(create_app().routes)` (FastAPI 0.141 includes routers lazily), like `test_webhook_secret_router.py`. No `/api` route with a method beyond GET/HEAD/OPTIONS has `pool`, `capital` or `min-order` in its path, and everything under `/api/pools` is read-only. A guard test asserts the walk sees `GET /api/pools` and `PUT /api/credentials/{exchange}`, so an empty walk cannot pass. It passes immediately by construction (the surface never existed); mutation: adding `POST /api/pools/enable` reds both the surface test and the read-only test.
- [x] 6d.6 GREEN: `KNOWN_FUTURES_POOLS` constant (`{bybit: (usdt-m, USDT, default_min_order_size), binance: (usdt-m, USDT, default_min_order_size)}`). **Done (8b-1, commit b7d1d1c):** `accounts/domain/known_pools.py`, a `MappingProxyType` of `Exchange -> KnownPool(venue, settlement_currency, default_min_order_size)` with default 5 for both, plus `known_pool_for(exchange: str)` that raises `InvariantViolation` for an exchange with no pool.
- [x] 6d.7 GREEN: `CapitalPoolWriterPort.enable(exchange)`/`.disable(exchange)`; `SqlAlchemyCapitalPoolWriter`; `SaveCredential` calls `.enable(exchange)` in the same transaction as the credential write. **Done (8b-1, commit b7d1d1c):** `SaveCredential(inspectors, writer, pools, commit, clock)` gains `pools` as its third argument and calls `enable` after `store` and before `commit`. The router's `get_save_credential` and `scripts/credential_cli.py` build `SqlAlchemyCapitalPoolWriter(session)` on the same session as the vault, so the Bybit and Binance store scripts enable the pool too (a source test pins it, and a Binance script run through `ScriptSession` records `pools.enabled == ['binance']`; a refused run records none). Pionex's script is not folded: a source test pins that it names neither `SaveCredential` nor a pool. `disable` is implemented and tested here but nothing calls it until unit 6e. **Lock: none needed for `enable`.** The pool advisory lock serializes an allocation's availability read, decision and reservation. Enabling changes none of them (a disabled pool is not read by the worker, so no allocation is in flight against it; an enabled one is left untouched), and it is one atomic upsert that takes only the pool row's lock as the last step before the commit and never asks for the advisory lock afterwards, so it cannot close a cycle with the lock order (advisory lock first, then row locks). `DeleteCredential` (6e) must take the advisory lock itself before it calls `disable`. **F11 (visibility):** the running worker's `_PoolSet` is refreshed at the start of each `balance.sync` run (the PR 3 fix, `_reload_pools()`), so a pool enabled through Settings gets its first balance read within one sync interval, about 60 seconds, with no restart. Until then an opening signal on that pool is refused as an absent or stale balance. That cadence is unchanged by this unit, and the panel must not promise an immediately tradable exchange. No migration is needed: the rows exist since 0017/0018 and the insert path covers a missing one.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/accounts/`.
Harness: real PostgreSQL (transaction atomicity with the credential write).
Rollback boundary: one constant + one port/adapter + one call site in `SaveCredential`; revert stops auto-enabling, existing enabled pools untouched.
Forecast: 300–450 lines.

### Unit 6e — `DeleteCredential`, `PoolExposurePort`, `DELETE` endpoint, concurrency test (700–1,000 lines)

**Files**: Create `backend/src/strategy_manager/accounts/application/delete_credential.py`;
Modify `backend/src/strategy_manager/accounts/application/ports.py` (`PoolExposurePort`); Create
`backend/src/strategy_manager/accounts/infrastructure/pool_exposure_adapter.py`; Modify
`backend/src/strategy_manager/accounts/infrastructure/credentials_router.py`.

- [x] 6e.1 RED `backend/tests/accounts/application/test_delete_credential_integration.py::test_deletion_refused_while_enabled_strategy_exists_names_it_409` — **live PostgreSQL**. **Done (8b-2):** real PostgreSQL, `tests/accounts/application/test_delete_credential_integration.py`. An enabled strategy on the pool refuses with `ExchangeNotFlat` naming it by id and name; the credential stays active and the pool enabled. The router test `test_delete_credentials_409_names_what_blocks_and_changes_nothing` pins the 409 body (`outcome`, `detail`, `enabled_strategies`, `symbols`, `allocations`, `live_reservations`, `in_flight_attempts`, ids and names only, no key fragment, `no-store`). RED on assertions against a wrong-answer stub that commits and returns success: `DID NOT RAISE ExchangeNotFlat` x5 and `assert ['commit'] == ['lock', ..., 'commit']`. The use-case file `test_delete_credential.py` (fakes sharing one event log) pins the step ORDER, that every refusal writes and commits nothing, and the logs.
- [x] 6e.2 RED same file `::test_deletion_refused_while_open_exposure_exists_names_symbols_allocations_reservations_attempts_409`. **Done (8b-2):** same file; open position, live reservation and SUBMITTED attempt across three different strategies, each alone (parametrized) and all together, name symbols, allocations, reservations and attempts. The reservation is read as `terminal_at IS NULL` (design 4b, `live_for_strategy`'s reading), which is a superset of the brief's "PENDING or SUBMITTED with `expires_at` in the future": a row past its TTL that the sweeper has not reached still says it holds capital, so the delete refuses (`test_a_reservation_past_its_expiry_but_not_yet_swept_still_blocks`). Mutations: ignoring SUBMITTED attempts reds the all-kinds test and the adapter test; filtering reservations to one strategy reds both too.
- [x] 6e.3 RED same file `::test_deletion_succeeds_when_flat_deactivates_credential_disables_pool_same_transaction`. **Done (8b-2):** real PostgreSQL. A flat exchange (one round-tripped allocation, every strategy disabled) deletes; the credential row is DEACTIVATED and kept (`[True]` becomes `[False]`, and a rotation's history rows stay `[False, False]`), the pool is disabled. A commit spy reads the database from a second connection at the instant of the commit (credential still active, pool still enabled) and then commits: one transaction, one commit. `test_a_failing_pool_write_rolls_the_credential_deactivation_back` proves a failing `disable` leaves both untouched. Mutations: `disable` skipped reds the same-transaction test, the failing-pool-write test and the deletion-first concurrency test; `deactivate` skipped reds four tests (`assert [True] == [False]`).
- [x] 6e.4 RED same file `::test_concurrent_allocation_and_deletion_on_same_pool_serialized_by_advisory_lock_both_orderings` — the same lesson as 2c.8/2c.9, widened exchange-wide. **Done (8b-2):** real PostgreSQL, both orderings, lock-hold harness (no `sleep(0)` barrier). Every wait is proven twice: `not task.done()` AND a poll of `pg_locks` until the other actor shows as a WAITING advisory lock. (a) `..._allocation_first`: the allocation holds the pool lock by pausing its commit after its whole body ran; the strategy is disabled only then; the delete waits, and after the commit refuses `ExchangeNotFlat` with `live_reservations == (the allocation's reservation,)` and nothing else blocking, so the refusal proves the exposure was read AFTER the allocation committed. (b) `..._deletion_first`: the delete holds the lock (paused right after acquiring it); the allocation's pre-lock read, paused, still saw `enabled=True`; the allocation heads for the lock, waits, and once the delete commits its in-lock re-read sees the strategy disabled: `SKIP STRATEGY_DISABLED`, no reservation, credential inactive, pool disabled. **What protects ordering (b):** `AllocateCapital` reads neither the pool's `enabled` flag nor the credential (its pool config is the worker's snapshot, F11, and the key check lives upstream in `ProcessSignalHandler`), so the thing the allocation finds after the delete is the strategy DISABLED, which is exactly the delete's precondition. Mutations: advisory lock removed reds both tests (`timed out waiting for an actor to wait on the advisory lock`) and the lock-order test; lock order reversed reds the lock-order test and the order test.
- [x] 6e.5 RED same file `::test_replacing_a_key_rotation_never_runs_this_precondition_even_with_enabled_strategy_and_open_position`. **Done (8b-2):** real PostgreSQL. A rotation through the real `SaveCredential` and vault, with an ENABLED strategy, an open position and a live reservation on the pool, is `Saved`, leaves `[False, True]` credential rows and the pool enabled. It passes against the code as written because rotation never had a precondition, so it was proven non-vacuous by mutation: a flatness check added to `SqlAlchemyCredentialVault.store` turns it red with `ExchangeNotFlat`.
- [x] 6e.6 RED `backend/tests/accounts/infrastructure/test_pool_exposure_adapter.py::test_exposure_sees_every_strategy_bound_to_pool_not_just_one` (widened from `StrategyExposurePort`'s one-strategy shape). **Done (8b-2):** real PostgreSQL, `test_pool_exposure_adapter.py`, nine tests. `test_exposure_sees_every_strategy_bound_to_pool_not_just_one` has one strategy holding a position, one a live reservation, one a SUBMITTED attempt and one enabled. Also: two allocations of two strategies on one market (one under the `STXUSDT.P` spelling) are reported once as a market and twice as allocations; a closed allocation and FILLED/EXPIRED/FAILED reservations are not exposure; another pool's exposure is not this pool's; the adapter writes nothing. RED on assertions against a stub returning an empty exposure (`assert () == (UUID(...),)`, `assert frozenset() == frozenset({'STXUSDT'})`, `assert not True`). Mutations: holdings filtered to the first strategy reds the two-allocations test; reservations filtered to one strategy reds the every-strategy test; attempts ignored reds it too.
- [x] 6e.7 RED `backend/tests/accounts/infrastructure/test_credentials_router.py::test_delete_credentials_404_when_no_active_row`, `::test_delete_credentials_200_status_empty_matches_never_configured_shape`. **Done (8b-2):** `test_credentials_router.py`, real PostgreSQL with the real use case over spies on the lock and the exposure. `..._404_when_no_active_row`; `..._200_status_empty_matches_never_configured_shape` (the body equals the `EMPTY` entry and equals what `GET /api/credentials` then shows for the exchange, history row kept). Decision 31: an ACTIVE Pionex row plus DELETE answers 404 `exchange 'pionex' is not served by this panel`, the row is still active, the lock spy and the exposure spy record zero calls (same for `kraken` with no row); an unauthenticated or wrong-token DELETE on `pionex` and on `bybit` is 401 with `{"detail": UNAUTHORIZED_DETAIL}` before anything is asked; `test_every_delete_answer_carries_no_store` covers 200, 404 (no row), 404 (not served), 401 x2 and 409 with `Cache-Control: no-store`. Also: a deleted key's pool is disabled and a new PUT enables it again. RED (assertions) against a route that never called the use case: `assert 200 == 404`, `assert 200 == 409`, `assert [] == [('bybit', 'usdt-m', 'USDT')]`. The 401 tests pass immediately, because auth is on the router; structural guards were extended instead (`test_no_decrypt_in_api_path.py` now guards `delete_credential.py` and `credential_revoker.py`, and a test pins that neither names a secret column or imports the cipher). The webhook-secret sweep enumerates routes from the route table, so `DELETE /api/credentials/{exchange}` joined it automatically; it now also asserts that this request really reached the pool check (409 `EXCHANGE_NOT_FLAT`, since its seed holds a live reservation) and that the secret is in no body or header.
- [x] 6e.8 RED `backend/tests/signals/application/test_process_signal.py::test_no_key_refused_live_immediately_after_delete_credential_commits_no_lock_no_cache` (the "key deleted just before this check" spec scenario). **Done (8b-2):** `test_process_signal.py::test_no_key_refused_live_immediately_after_delete_credential_commits_no_lock_no_cache`, real PostgreSQL and the REAL `VaultTradeCapabilityAdapter`. One adapter instance over one long-lived session lets a live open through while the key is stored (control), `DeleteCredential` then commits on another connection, and the next live open through the SAME instance is refused `EXCHANGE_HAS_NO_KEY`: one WARNING naming the exchange, a durable `REJECTED` outcome, the spy lock never touched, no order placed. It passes immediately (the adapter already reads the active row on every call); mutation: caching the answer per exchange inside the adapter turns it red (`assert True is False` on `executed`).
- [x] 6e.9 GREEN: `PoolExposurePort.exposure(pool)`, `PoolExposureAdapter` (reuses `ReadSymbolHoldings`, reservations, attempts like `StrategyExposureAdapter`, without a strategy filter). **Done (8b-2):** `PoolExposurePort.exposure(pool)` and `EnabledStrategy`/`PoolExposure` in `accounts/application/ports.py`; `PoolExposureAdapter` (`accounts/infrastructure/pool_exposure_adapter.py`) composes `ReadSymbolHoldings`, the reservation repository and the attempt repository like `StrategyExposureAdapter`, without a strategy filter, and adds the enabled strategies of the pool. Three new pool-wide repository reads beside their per-strategy twins: `SqlAlchemyLedgerRepository.distinct_symbols_for_pool`, `SqlAlchemyReservationRepository.live_for_pool`, `SqlAlchemyExecutionAttemptRepository.submitted_for_pool` (an attempt carries its own pool columns, so no join through the reservation). `PoolExposureAdapter.over(session)` is the real wiring.
- [x] 6e.10 GREEN: `DeleteCredential` — `SELECT ... FOR UPDATE`, 404 if no active row, `pg_advisory_xact_lock(LockKey(pool))` (same key `ArchiveStrategy`/`AllocateCapital` take), exposure check, 409 `EXCHANGE_NOT_FLAT`, else deactivate + `CapitalPoolWriterPort.disable(exchange)`, commit. **Done (8b-2):** `DeleteCredential(credentials, pool_lock, exposure, pools, commit)` in `accounts/application/delete_credential.py`. **Lock-order correction (binding):** the task text listed `SELECT ... FOR UPDATE` before `pg_advisory_xact_lock`, which violates the project rule (pool advisory lock first, then row locks) and is the deadlock `ArchiveStrategy`'s docstring documents. The pool's identity is known from `KNOWN_FUTURES_POOLS` by exchange without reading anything, so the order is: (1) `known_pool_for`, refusing an exchange without a pool as `ExchangeNotServed` before anything else (decision 31); (2) the advisory lock on the pool's `LockKey`, through the existing `PoolLockAdapter`, the same key `AllocateCapital` and `ArchiveStrategy` take; (3) `SELECT ... FOR UPDATE` of the active row through the new `SqlAlchemyCredentialRevoker` (no cipher, no secret column), `NoActiveCredential` when there is none; (4) the exposure check, `ExchangeNotFlat` naming what blocks; (5) deactivate the row (kept) and `CapitalPoolWriterPort.disable(exchange)`; (6) commit. Proof of the order: `test_deletion_takes_the_pool_lock_before_the_row_lock_so_a_waiting_delete_holds_no_row` holds the pool lock in one transaction, starts the delete, waits until `pg_locks` shows it WAITING on the advisory lock, and then takes the credential row with `FOR UPDATE NOWAIT` from a third connection, which succeeds because the waiting delete holds no row; reversed, the delete already holds it and `NOWAIT` raises `LockNotAvailableError`. Logging, never silent: a success logs one INFO naming the exchange, the last four characters and the disabled pool (`already disabled` when the pool was already off); a refusal logs one WARNING naming the exchange and what blocks (strategy names, symbols, allocation, reservation and attempt ids), never a key. Lock release on a refusal is the session closing (rollback), as in `ArchiveStrategy`. **Decision 31** (owner, 2026-09-30): an exchange with no `KNOWN_FUTURES_POOLS` entry answers 404 "not served by this panel" before any lock, read or query; no `known_pool_for` result is ever used to lock for it. Mutations on the use case: lock order reversed (red, including the `NOWAIT` test and the order tests), advisory lock removed (both concurrency tests red by timeout), `disable` skipped, the not-served check moved after the lock (the unit test's empty event log reds). `pool_seed.py` is the shared test seeding for unit 6e.
- [x] 6e.11 GREEN: `DELETE /api/credentials/{exchange}` on `credentials_router`. **Done (8b-2):** `DELETE /api/credentials/{exchange}` on `credentials_router`, behind the router's bearer auth and the `/api/credentials` no-store prefix. 404 (not served: decision 31, FastAPI's `{"detail": ...}`), 404 (no active credential), 409 `EXCHANGE_NOT_FLAT` with `{outcome, detail, enabled_strategies: [{id, name}], symbols, allocations, live_reservations, in_flight_attempts}`, 200 with the exchange's `EMPTY` entry. `get_delete_credential` builds every part over the request's one session (deactivation, pool write and commit are one transaction) and, unlike `get_save_credential`, takes no cipher, so an unusable master key cannot turn a delete into a 503.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/accounts/`.
Harness: real PostgreSQL, live concurrency test (advisory lock, both orderings — no meaningful fake per `rules.tasks`).
Rollback boundary: `delete_credential.py`, `pool_exposure_adapter.py`, one router method; revert removes the endpoint, keys already stored remain valid vault rows.
Forecast: 700–1,000 lines.

**Independent security verification of PR 8b-2 (2026-09-30).** It found no blocker.

Checked clean:
- Lock order: the advisory lock is taken through the same `LockKey` path as `AllocateCapital`, before the credential row lock; the `NOWAIT` test is meaningful (reversed, the delete would already hold the row and it would raise).
- The session is READ COMMITTED, so there is no stale snapshot across the wait.
- Decision 31: an exchange without a known pool answers 404 before any lock, read or query.
- Auth first, then `Cache-Control: no-store` on every status of `/api/credentials`.
- No cipher and no secret in the 409 body or in the logs.
- The row is deactivated rather than removed, and a second DELETE answers 404.
- No decrypted key is cached across jobs: the worker builds the registry per job.
- The pool-wide exposure covers disabled strategies that still hold positions, and expired-but-unswept reservations block the delete (the safe direction).
- The full gate passed on its first attempt.

Fixed in this branch (`6a4487e`):
- **W1** `UpdateStrategy` (the PATCH that sets `enabled`) takes only the strategy row lock, never the pool lock, so a strategy could be enabled while a delete held the pool lock after reading an empty exposure. A signal for it passed `NO_KEY` (the key was not yet deactivated), queued on the pool lock, and resumed after the delete committed: it reserved capital on a keyless exchange, held until its TTL. No position could open. Fixed in `AllocateCapital`: inside the advisory lock, in the same re-check that re-reads the policy, it now reads whether the pool is still enabled through a new `PoolStatusPort.is_disabled` (adapter `accounts/infrastructure/pool_status_adapter.py::SqlAlchemyPoolStatus`: a plain column SELECT on the allocation's session, no `FOR UPDATE`, because the delete's `disable()` updates that row). A disabled pool ends the allocation as the new skip `POOL_DISABLED`: one WARNING naming the signal, strategy and pool with "no capital reserved", the signal outcome recorded per decision 25, nothing reserved. Design.md reason-code table row 24, the row-8 list and the commit table, and a paragraph in section 4b. `UpdateStrategy`'s locking and the behaviour for an enabled pool are unchanged; DRY_RUN makes no difference. The one production construction site (`main.py::_build_process_signal_handler`, which serves `signal.process` and, through `open_now`, the open-after-close continuation) is wired, and so is every test site (a shared `AlwaysEnabledPool` fake; the refusal-outcomes integration test uses the real adapter).
  - Tests: `tests/allocation/application/test_allocate_capital_pool_disabled.py` (3 unit tests with fakes: the skip with its reason, zero reservations, one WARNING and the recorded outcome; the read comes after the lock and the skip is staged before the commit; an enabled pool is unchanged) and `tests/accounts/application/test_allocate_pool_disabled_integration.py` (3 tests on real PostgreSQL: a holder that disables the pool and deactivates the key inside the pool lock, with the strategy ENABLED in committed state; the same harness without disabling the pool, as the control, where the allocation reserves; and the exact W1 interleaving with the REAL `DeleteCredential`, paused inside its lock after the exposure read, the strategy enabled and committed meanwhile). Each proves the wait with `not task.done()` plus a NOT-granted `pg_locks` advisory lock on this pool's exact key (the two `hashtext` halves `LockKey` produces). RED on assertions before the check existed (`FULL is SKIP`, `['lock', 'commit'] == ['lock', 'pool_status', 'commit']`, `0 == 1`). No end-to-end sleep barrier.
  - Mutations seen red (each against the two new files): the pool read moved BEFORE the lock (3 failed: the ordering unit test and both integration tests that depend on the wait, because the pre-lock read sees the pool enabled); the check removed (5); the skip reserving anyway (4); the WARNING dropped (1); the outcome not recorded (3).

Follow-ups, left open:
- [ ] 8f.4 (S1) Pool exposure counts only ledger holdings, live reservations and SUBMITTED attempts, not `reconciliation_discrepancies` or `booking_proposals`. A position that exists at the venue but not in the ledger does not block a delete, and after the delete no key is left to close it. Decision 22 and design § 4b never listed these, and `ArchiveStrategy` has the same scope. Pre-existing.
- [ ] 8f.5 (S2) `_advisory_counts` in `test_delete_credential_integration.py` counts any waiting advisory lock rather than the pool's key, and `_policy_read_happened` is a fixed `sleep(0.2)`. It cannot give a false pass, only flake. (The new W1 tests match the pool's exact key.)

Gate after the fix: ruff and mypy clean; full suite exit 0 on the first run, 2574 collected (baseline 2568, plus 6).

**PR 8a+8b deploy runbook** (owner-run): `alembic upgrade head` then restart both processes. The
old code never inserts a credential row (only the store scripts do), so no ordering hazard exists;
run the store scripts only from the new code, because 0027 makes `trade_capable` mandatory.
Re-saving each already-active key through Settings is optional (rows sealed before 0027 stay
`trade_capable=true` with both sources `UNRECORDED`, shown as "not verified"; for Binance, re-saving
is how the two confirmations get recorded, design § J Q1); doing so for Bybit/Binance also runs `CapitalPoolWriterPort.enable`,
a no-op on their already-enabled pool rows (migrations 0017/0018).

---

## PR 9 — Unit 4b: SPA serving, fallback, CSP, invariant 5 (dropped, K5) (500–750 lines)

**Files**: Create `backend/src/strategy_manager/shared/infrastructure/spa.py`; Modify
`backend/src/strategy_manager/shared/config.py` (`panel_dist_dir`); Modify `main.py`
(`mount_panel()` call, startup invariant 5).

- [x] 4b.1 RED `backend/tests/shared/infrastructure/test_spa.py::test_get_api_unknown_returns_404_json_never_index_html`, `::test_get_api_bare_returns_404_json`, `::test_get_webhook_tradingview_via_get_returns_404_not_index_html` (the load-bearing method-mismatch case — Starlette's partial-match fallthrough).
- [x] 4b.2 RED same file `::test_deep_client_route_strategies_uuid_resolves_to_index_html`, `::test_settings_route_resolves_to_index_html_on_refresh`.
- [x] 4b.3 RED same file `::test_path_traversal_encoded_dot_dot_never_escapes_dist`, `::test_absolute_path_probe_never_escapes_dist`.
- [x] 4b.4 RED same file `::test_hashed_asset_served_with_immutable_cache_control`, `::test_index_html_served_with_no_cache_and_security_headers` (CSP string asserted verbatim, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`).
- [x] 4b.5 RED `backend/tests/shared/test_startup_invariants.py::test_panel_dist_dir_set_but_index_html_missing_refuses_to_start`. **Dropped (owner decision 2026-09-30, design K5): `::test_missing_master_encryption_key_refuses_to_start_invariant_5`.** K5 is the later decision and rejected invariant 5: a bad master key would refuse to boot the whole admin API, read-only routes included, for a fault only the PUT has, and the API process also hosts `POST /webhook/tradingview`, so refusing to boot would stop signal ingestion entirely and loop under `Restart=always`. The worker already refuses a bad key (exit 78) and alerts. In its place, `tests/accounts/infrastructure/test_lifespan_wiring.py::test_an_unusable_master_key_does_not_stop_the_api_from_starting` pins that the lifespan starts, `/health` and the webhook answer, and the PUT answers 503.
- [x] 4b.6 GREEN: `mount_panel(app, dist)` — `app.mount("/assets", ...)`; `@app.get("/{path:path}")` registered LAST, reserved-prefix check (`api`, `api/`, `webhook/`, `health` → 404), resolved-path containment check, else `index.html` with security headers.
- [x] 4b.7 GREEN: `Settings.panel_dist_dir: str = ""` (empty = unmounted, dev/tests) and the `panel_dist_dir` set-but-missing-`index.html` refusal. **Dropped (owner decision 2026-09-30, design K5): the startup invariant 5 half (`EnvelopeCipher.from_base64` must succeed).** Same reason as 4b.5; the per-request 503 plus one ERROR in `get_save_credential` stays.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/shared/infrastructure/test_spa.py backend/tests/shared/test_startup_invariants.py`.
Harness: `httpx.AsyncClient` over the ASGI app with a temp `dist` directory (built fixture, not a real Vite build).
Rollback boundary: `spa.py` + one `mount_panel()` call, gated by `panel_dist_dir` being unset in dev/test; revert removes the mount, `/api` is completely untouched.
Forecast: 500–750 lines.

**Done (2026-09-30, branch `feat/operator-panel-spa-serving`, `adfb8e3`, corrected by the commits after `8d0d4d0`; committed, not pushed).** **CORRECTION (owner decision 2026-09-30, design K5): startup invariant 5 was built here and then DROPPED; every mention of it below describes the dropped work.** 998 lines added, 4 removed (`spa.py` 196, invariant module 34, new tests 728, wiring and config about 40). Risk **medium**: a new surface, but mounted only when `PANEL_DIST_DIR` is set (unset in production until the prerequisites below are done), and the two new refusals can only stop the API from starting.
- Files: `shared/infrastructure/spa.py` (`mount_panel`, `assert_panel_dist_ready`), `shared/infrastructure/master_key_invariant.py` (`assert_master_key_usable`, invariant 5), `Settings.panel_dist_dir`, and `main.py` (mount last in `create_app`; both checks in the lifespan after invariants 3 and 4, inside `operator_alerts`). Tests: `tests/shared/infrastructure/test_spa.py` (22) and `tests/shared/test_startup_invariants.py` (14); the existing lifespan wiring fixture now sets a usable master key. (Correction: `master_key_invariant.py` and its 6 tests were removed again; 8 tests remain in `test_startup_invariants.py` for the `index.html` refusal, plus the pin below; suite total 2605 collected.)
- RED evidence: with a stub catch-all that served `index.html` for everything, and invariant stubs that accepted everything and logged nothing, 20 of the 36 new tests failed on an assertion (for example `_is_json_404(<Response [200 OK]>)` for `/api/nothing-here`; the refusal tests failed with `DID NOT RAISE`). The other 16 passed at once (15) or skipped (1, the symlink probe, because the account cannot make a symlink). They are the ones the stub cannot fail: traversal probes, since the stub never reads a path, and the positive cases. Each was proved non-vacuous by mutation, and the skipped one was rewritten to fall back to a directory junction so it runs.
- Mutations, each restored afterwards, each turned the suite red: catch-all registered first (5 tests); reserved-prefix check removed (5); reserved check without stripping leading slashes (1, the `/%2Fapi/x` probe); string-prefix containment (1, the `dist-evil` sibling); containment skipped (4); `resolve()` dropped (3, including the junction); CSP altered (2); `no-cache` dropped, `nosniff` dropped and `Referrer-Policy` dropped (1 each); immutable header dropped (1); GET-only route class removed (2); invariant-5 ERROR dropped (4); invariant-5 ERROR that includes the key (3); invariant-5 ERROR with `exc_info` (2); panel ERROR dropped (4); lifespan not calling invariant 5 (1) or the panel check (1); an unset `panel_dist_dir` still mounting (2).
- Never silent (decision 29, design note ~1572): the `index.html` refusal (and the dropped invariant 5) logs ONE ERROR, `refusing to start: <message>`, through the module's own logger (which propagates to root), BEFORE raising. The lifespan tests replace `operator_alerts` with a stand-in that installs a handler on the ROOT logger for its duration, so a record there was logged while the bridge was installed. No `exc_info`, and every sliding 8-character window of the sentinel key is asserted absent from every record.
- Invariant 5 (DROPPED): the owner decided to follow K5, which is later than 4b.5/4b.7. A bad `MASTER_ENCRYPTION_KEY` must not refuse to boot the API: it would take down the read-only admin routes for a fault only `PUT /api/credentials/{exchange}` has, and the API process also hosts `POST /webhook/tradingview`, so a refusal would stop signal ingestion entirely and loop under `Restart=always`. The per-request 503 with one ERROR stays, and the worker refuses a bad key on its own (exit 78) and alerts. `tests/accounts/infrastructure/test_lifespan_wiring.py::test_an_unusable_master_key_does_not_stop_the_api_from_starting` pins it (lifespan starts with an empty key, `/health` 200, webhook answers below 500, PUT 503). Mutation: re-adding `EnvelopeCipher.from_base64(settings.master_encryption_key)` to the lifespan turned it red. There is therefore NO pre-deploy master-key check for PR 9.
- **The API unit still has no `RestartPreventExitStatus`.** This PR changes no systemd unit. A refused API start therefore still loops under `Restart=always`, but it now sends an alert at each process start (the bridge's in-memory dedupe dies with each process, as decision 29 describes for the worker). Decision 29 left the API's unit fix out of scope and so does this PR.
- Discrepancies with the documents, and how each was settled:
  1. (Superseded.) This note first said invariant 5 was added against K5's "was NOT added". The owner then ruled that K5 stands, so the invariant is removed and there is no discrepancy left.
  2. Design 13 and 4b.6 register a plain `@app.get` catch-all. That would also answer method mismatches on the system's own surface: a partial match on the catch-all pre-empts the other routes' 405 and the trailing-slash redirect, so `POST /api/typo` would become 405 and `POST /webhook/tradingview/` would stop redirecting. The catch-all is a GET-only route class whose `matches` returns no match for any other method, so every non-GET request answers as it did before the mount (proved by an identical-request comparison with and without the panel, webhook POST and `/health` included).
  3. Reserved prefixes also cover bare `webhook` and a leading slash (`//api/x` reaches the handler as `/api/x`). Stricter than the design, never looser.
  4. Not preserved: a GET on a reserved path that differs only by a trailing slash (`GET /api/strategies/`) used to be redirected by Starlette and now answers 404 JSON, because the catch-all is a full GET match. Only with the panel mounted, and nothing calls it that way.
  5. The task's Gate line names `backend/tests/...` paths while running from `backend`; the gate was run from `backend` over the whole suite instead.
- 7f.1 (CORS): same-origin serving **does not close it by itself**. With the mount on, the panel needs no CORS, but `CORSMiddleware` with `allow_credentials=True` and `CORS_ORIGINS` (default `http://localhost:5173`) stays, because the Vite dev server still needs it, and a widened `CORS_ORIGINS` would still be honoured in production. 7f.1 stays open until the owner decides between removing CORS when `panel_dist_dir` is set and the optional refuse-`*` check. Until then `CORS_ORIGINS` must not be widened.
- Path safety: encoded `..` (upper and lower case), `%2f` and `%5c` forms, double-encoded `..`, backslashes, drive-absolute and root-absolute paths, a `dist-evil` sibling, and a directory junction inside `dist` pointing outside all answer the page or 404 and never the outside file.
- Harness note: `httpx` over ASGI with a temp `dist` fixture, as planned. No real Vite build and no rehearsal of the built bundle under the CSP was done; design 13 requires that rehearsal before PR 9 is deployed with `PANEL_DIST_DIR` set (PR 10 delivers the bundle).

**PR 9 deploy prerequisites** (owner-run, per design's rollout section): DuckDNS proxy forwards
only `/webhook/tradingview`; `cloudflared` routes `strategymanager.trade` to `127.0.0.1:8000`; a
Cloudflare Access policy scoped to the owner's identity; `PANEL_DIST_DIR` set; `BEHIND_CLOUDFLARE_TUNNEL`
stays `false`; owner's `curl` runbooks moved to `/api` (already done at PR 2).

---

## PR 10 — Router, shell, exchange scope, bookings re-homed, direction-A tokens (1,150–1,600 lines)

### Unit 7-router — router, shell, query hooks (600–850 lines)

**Files**: Create `frontend/src/app/router.tsx`; Modify `frontend/src/app/App.tsx`; Create
`frontend/src/shared/layout/*` (`AppShell`, `TopBar`, `SideNav`, `BottomNav`, `DryRunBadge`);
Modify `frontend/package.json` (+ `react-router`).

- [x] 7r.1 RED (Vitest) `frontend/src/app/router.test.tsx::test_route_map_renders_overview_strategies_strategy_detail_settings_in_memory_router`, `::test_unknown_path_renders_not_found_client_side`.
- [x] 7r.2 RED `frontend/src/shared/layout/AppShell.test.tsx::test_widescreen_shows_sidenav_narrow_shows_bottomnav`, `::test_dry_run_badge_reads_health_dry_run_field`.
- [x] 7r.3 GREEN: pin `react-router` at install, confirm its React 19 peer range; `router.tsx` route map (`/`, `/strategies`, `/strategies/:strategyId`, `/settings`, `*`); `AppShell` layout; `DryRunBadge` wired to `GET /health`.

Gate: `cd frontend && npm run lint && npm test`.
Harness: `MemoryRouter` for Vitest; N/A backend.
Rollback boundary: new `app/router.tsx` + `shared/layout/*`; revert restores the hash-based `App.tsx:17-34` nav.
Forecast: 600–850 lines.

### Unit 7s-scope — exchange scope, bookings re-homed (350–500 lines)

**Files**: Create `frontend/src/shared/scope/exchange-store.ts`; Modify `frontend/src/features/bookings/*`.

- [x] 7s.1 RED `frontend/src/shared/scope/exchange-store.test.ts::test_options_are_distinct_exchanges_from_pools_default_is_first`, `::test_persisted_through_safe_storage_key_sm_exchange`, `::test_settings_route_reads_no_exchange_scope`.
- [x] 7s.2 RED `frontend/src/features/bookings/BookingsListView.test.tsx::test_filtered_by_selected_exchange`.
- [x] 7s.3 GREEN: Zustand store `shared/scope/exchange-store.ts` over `safe-storage`; `BookingsListView` re-homed inside the shell, filtered by scope (client-side, decision 3).

Gate: `cd frontend && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: new store file + a filter prop on the existing bookings view; revert removes filtering, bookings view still renders unfiltered.
Forecast: 350–500 lines.

### Unit 7t-theme — direction-A `@theme` swap, self-hosted fonts (200–250 lines)

**Files**: Modify `frontend/src/index.css`; Modify `frontend/src/main.tsx`; Modify
`frontend/package.json` (+ `@fontsource/archivo`, `@fontsource/ibm-plex-sans`,
`@fontsource/ibm-plex-mono`; − `recharts`).

- [x] 7t.1 RED `frontend/src/shared/theme.test.ts::test_no_hex_colour_or_var_inside_classname_across_renamed_components` (grep-based Tailwind rule test).
- [x] 7t.2 RED `frontend/src/App.test.tsx::test_bookings_and_tokengate_use_renamed_tokens_not_removed_ones` (old `surface-*`/`edge`/`ink-100/300/500`/`accent`/`profit`/`loss`/`idle` tokens removed, renamed classes render).
- [x] 7t.3 GREEN: replace `@theme` in `index.css` with the direction-A palette (verbatim from design.md § Visual design); rename every existing class in bookings, `TokenGate`, `App`; import the three `@fontsource` packages in `main.tsx`; remove `recharts` from `package.json`.

Gate: `cd frontend && npm run lint && npm test`.
Harness: N/A — CSS/token change, asserted by grep-style Vitest tests.
Rollback boundary: `index.css` + `main.tsx` + class renames; revert restores the old palette, no logic changes.
Forecast: 200–250 lines.

**Done (PR 10a, commit `fc32683` on `feat/operator-panel-theme-tokens`, not pushed):**
- Split of PR 10 (about 1,150-1,600 lines) into three sequential PRs: **10a theme** (this, first, so the shell is built on the final tokens and nothing is renamed twice), **10b unit 7-router** (router, shell), **10c unit 7s-scope** (exchange scope, bookings filter).
- Token mapping: `surface-950`->`ground`, `surface-900`->`panel`, `surface-850` and `surface-800`->`panel-2`, `edge`->`rule`, `ink-100`->`ink`, `ink-300`->`ink-2`, `ink-500`->`ink-3`, `accent`->`gain`, `profit`->`gain`, `idle`->`decision` (the DRY RUN badge, one of the four amber places), `loss` kept (now ember). Primary buttons went from `text-ink-100` to `text-ground` on the teal `bg-gain` for contrast. Body is `bg-ground text-ink font-sans`.
- Fonts: `@fontsource/archivo` 600/700, `@fontsource/ibm-plex-sans` 400/500/600, `@fontsource/ibm-plex-mono` 400/500/600, latin subset, all pinned at exactly 5.3.0 (no peer dependencies declared). `recharts` removed; nothing imported it (only package.json and docs mentioned it).
- CSP: no change. `spa.py` serves `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:`, so `font-src` falls back to `'self'`. Every emitted font file is above Vite's 4 kB inline limit, so none is inlined as a `data:` URI (which `font-src` would refuse); the built CSS holds no `data:`. Fontsource also emits `.woff` fallbacks beside `.woff2` (about 160 kB of unused files in `dist`, never requested by modern browsers).
- Discrepancies: the tasks name `frontend/src/App.test.tsx`; the file is `frontend/src/app/App.test.tsx`. The theme test is a superset of 7t.1 (also removed-token and index.css assertions, plus a scanner self-check so it cannot pass vacuously). The existing nav tests asserted `bg-surface-800` and now assert `bg-panel-2`. No copy changed.
- RED (assertions): the removed-token scan listed `appApp.tsx: border-edge` and five more files, the index.css test failed on `--color-surface-`, and the five App class tests failed on the old classes. Mutations, each restored: a hex `bg-[#fff]` in a className (2 red), `bg-[var(--x)]` (1), one old token `text-ink-500` left in TokenGate (2), `--color-accent` restored in `@theme` (1), a palette hex altered (1).
- Gate: lint 0, `npm test` 0 (66 tests), `npm run build` 0. Backend untouched. Build output: JS 335.88 kB (gzip 104.81), CSS 12.43 kB; the 16 font files add about 290 kB to `dist`, loaded on demand.
- Local view: `cd backend && uv run uvicorn strategy_manager.main:app --reload` and `cd frontend && npm run dev` (http://localhost:5173, `/api` proxied to :8000); the bookings view is at `#bookings`.

**Done (PR 10b, unit 7-router, commit `2dbb20d` on `feat/operator-panel-router-shell`, not pushed):**
- Size: 814 lines added and 186 removed (1,000 changed, `package-lock.json` 42 of them), above the 850 forecast. About 490 of them are tests (`AppShell.test.tsx` 224, `router.test.tsx` 65, `App.test.tsx`, the harness, the config and gate tests) and 113 are the old hash-navigation `App.tsx` being deleted. The authored production code is about 330 lines.
- Router: `react-router` pinned at exactly **7.18.4**, the version design 15 names. Its peer range is `react >=18` and `react-dom >=18`, and the installed React is 19.2.8, so it is covered. The newest release, 8.4.0, peers `react >=19.2.7` and needs node 22.22, so it was not taken: a major the design never chose.
- Route map (`app/router.tsx`, declarative `<Routes>`; `App` wraps it in `BrowserRouter`, tests in `MemoryRouter`): `/` Overview, `/strategies`, `/strategies/:strategyId` (shows the id), `/settings`, `*` client-side not-found, all inside `AppShell`. The Overview, Strategies and Settings pages are placeholders that render their i18n title and nothing else until PRs 11-13.
- **Bookings stays reachable** where the design puts it: the Overview's decision rail (`aside` with "Needs your decision" and the existing `BookingsListView`), behind `TokenGate`. The `#bookings` nav item is gone. The exchange filter stays for 10c.
- Shell (`shared/layout/`): `AppShell`, `TopBar` (brand, `DryRunBadge`, language toggle), `SideNav` (`hidden ... lg:flex`), `BottomNav` (`lg:hidden`), both `NavLink`s with an active state (`aria-current`, `bg-panel-2`), plus `NotFoundPage` and `navItems`. The nav `aria-label` is "Sections", as in the design.
- **`DryRunBadge`** reads `GET /health` through `useHealth` (`['health']`, 60 s). The field is `dry_run` (`main.py`: `{"status": "ok", "dry_run": settings.dry_run}`), mounted outside `/api`, no token, so it uses a plain `fetch`, not `apiFetch`. Display, decided here: `dry_run: true` shows "Dry run" (amber); `false` shows "Live" (loss colour, real money); **loading shows a neutral "Checking mode" and any failure (network, non-2xx, a body without a boolean `dry_run`) shows a neutral "Mode unknown"; neither ever shows "Live"**. The design hides the badge when `dry_run` is false; a visible "Live" was chosen instead because an absent badge during loading or failure would be indistinguishable from live.
- **Vertical overflow fix (owner criterion).** `AppShell` is `flex h-full flex-col` (`#root` is 100% high): top bar, then a `flex min-h-0 flex-1` body, then `BottomNav`. `main` is `flex min-h-0 min-w-0 flex-1 flex-col overflow-auto`, so only it scrolls. `TokenGate` is `flex flex-1` instead of `min-h-full`, and lost its own `p-4`, which doubled `main`'s padding. The bottom bar is a flex row of the column, not `fixed`, so the `pb-20` spacer is gone and cannot overflow. jsdom computes no layout, so the tests pin the class contract (gate has `flex-1` and none of `min-h-full`/`h-full`/`h-screen`; root is `h-full`; `main` has `flex-col flex-1 min-h-0 overflow-auto`; no `fixed` nav, no `pb-20`).
- **Owner's visual check** (`npm run dev`, http://localhost:5173, no token stored): (1) wide window: the page must not scroll with only the token card showing, and no scrollbar on the page edge; resize the height small and only the content area (not the top bar) may scroll. (2) narrow (under 1024 px, or devtools phone mode): the bottom bar sits at the bottom, the token card is centred above it, still no page scrollbar. (3) After pasting a token, the Overview shows its title and the bookings rail; a long bookings list scrolls inside the content area while the bars stay put. (4) `/strategies/anything` refreshed stays on its page; `/nope` shows "Page not found" inside the shell. (5) Stop the backend: the badge must read "Mode unknown", never "Live".
- Discrepancies with the documents: (1) design 15 nests `TokenGate` around `AppShell`; it wraps the `Outlet` inside `main` instead, as the owner's overflow fix requires, which also keeps the badge and navigation visible while locked. (2) The tasks name `AppShell.test.tsx` for the viewport-visibility test; it is a class-contract test (jsdom has no media queries). (3) `nav.dashboard`/`nav.bookings` were replaced by `nav.overview`/`nav.sections` (and the locale test that read `nav.bookings` now reads `overview.decisionRail.title`). (4) Vite's `/health` proxy and `appType: "spa"` were added; the backend catch-all needed no change (PR 9's `test_deep_client_route_strategies_uuid_resolves_to_index_html` covers it).
- RED (assertions, never an import error: `router.tsx` and `AppShell.tsx` were stubs rendering an empty `div`): 24 of the new tests failed, among them every route and badge test (`Unable to find an accessible element with the role "heading"`), the `TokenGate` class test (`flex-1` missing), and the two Vite config tests (`['/api']` lacking `/health`, `appType` undefined). The 88 tests now pass (66 before).
- Mutations, each restored, each turned the suite red except the one noted: settings route removed (3); not-found route removed (2); detail param renamed (1); `SideNav` visibility flipped (1); `BottomNav` visibility flipped (1); badge hardcoded to "Dry run" (5); badge "Live" on error (3); badge without a loading state (26); `dry_run` shape unchecked (1); `/health` path changed to `/api/health` (1); `TokenGate` back to `min-h-full` (1); `main` without `min-h-0` (1); root `min-h-full` (2); `TokenGate` removed from the shell (3); `/health` proxy removed (1). Two survived at first: `if (!response.ok)` removed (the 500 test used an empty body that the shape check also rejected, so the test now answers 500 with `dry_run: false`, and the mutant dies), and dropping `end` from `SideNav`'s `NavLink` (equivalent: react-router special-cases `/`, so `end` is belt and braces).
- Gate: `npm run lint` 0, `npm test` 0 (88 tests, 11 files), `npm run build` 0 (JS 376.93 kB, gzip 118.82). Backend untouched. `dist` not committed, `tsconfig.tsbuildinfo` restored. Line endings preserved (CRLF files stayed CRLF; `git diff --stat` shows only real changes).
- Local view: `cd backend && uv run uvicorn strategy_manager.main:app --reload` and `cd frontend && npm run dev` (http://localhost:5173; `/api` and `/health` are proxied to :8000).

**Done (PR 10c, unit 7s-scope, commit `058411f` on `feat/operator-panel-exchange-scope`, not pushed). PR 10 is complete (10a theme, 10b router and shell, 10c exchange scope).**
- Size: 1,018 lines added and 21 removed across 15 files, above the 350-500 forecast. About 690 are tests (`ExchangeTabs.test.tsx` 260, `exchange-store.test.ts` 210, `OverviewPage.test.tsx` 139, the bookings filter tests 64) plus the harness; the authored production code is about 330 lines. Nothing was cut to fit.
- **Options come from `GET /api/pools`**: all rows, disabled pools included (decision 22 keeps an exchange with a deleted key in the bar), as the distinct `exchange` values in first-seen order; the default is the first. `shared/api/pools.ts` validates the body row by row: anything that is not a list of `{exchange, venue, settlement_currency, enabled}` throws `ApiError` and reads as an error, never as "no exchanges". Query key `['pools']`, refetch 60 s.
- **Store** (`shared/scope/exchange-store.ts`): Zustand `persist` over `createSafeStorage` (the existing `shared/auth/safe-storage`), key `sm.exchange`, only `selected` persisted. Storage is a preference, not truth: `resolveExchange(options, selected)` keeps the stored value only while it is an option, else the first option, so a stale, wrong-typed or corrupt value falls back without rewriting storage. `useExchangeScope()` returns `loading`, `error` or `ready {options, exchange, select}`; `loading` and `error` carry no exchange on purpose.
- **Routes**: `isExchangeScoped` (`matchPath`, `end: true`) is true for `/`, `/strategies`, `/strategies/:strategyId` and false for `/settings` and the not-found page. `TopBar` mounts `ExchangeTabs` only on those, so Settings never reads the scope and never requests pools. `ExchangeTabs` also renders nothing while the token gate is locked (nothing to scope, and `/pools` would only answer 401).
- **Layout**: `TopBar` is now a `shrink-0` header of two rows: the bar (tabs inline from `lg`, `hidden lg:flex`) and, on narrow screens, the tabs as their own row below it (`lg:hidden`, `overflow-x-auto`, buttons `shrink-0 whitespace-nowrap min-h-11`). Like the two navigations the tabs render twice, so tests use `getAllBy*`. The AppShell structural class test now covers the tabs row (header non-shrinking and not overlaid, tabs inside it, `main` still the only scroller).
- **Bookings**: `BookingsListView` takes an optional `exchange` and filters client-side on `proposal.exchange === exchange` (exact, no prefix or case folding). `BookingProposal` already carries `exchange`, the same identifier `GET /pools` reports, so nothing is derived. The endpoint has no exchange parameter; one shared `['bookings','pending']` query stays. Without the prop every row renders (the rollback behaviour).
- **Pools loading or failing (decided here)**: the tabs show a neutral "Loading exchanges" status or a loss-coloured "Exchanges could not be loaded" alert, with no tab to click, and the shell, navigation and mode badge are unaffected. The Overview's decision rail shows a message INSTEAD of bookings in both states, and also when the pool list is empty ("No exchange is configured"). It never falls back to unfiltered rows. Cost: a pools outage hides pending bookings until pools answer; the alternative would put an approve button on another exchange's proposal under a tab that claims a filter.
- **Discrepancies with the documents**: (1) The read-only and "no key" marks on the tabs (decisions 18 and 20, and their spec scenarios) are NOT built: they need the `['credentials']` query, which no 7s task owns and which has no frontend client yet. They belong with the Settings work (PR 13) and must be added to `ExchangeTabs`; the two spec scenarios stay open until then. (2) `StrategyDetailPage` setting the scope from the loaded strategy (design 15) is left to PR 12, where that page gets its data. (3) The design's pending-bookings count in the rail (amber, `decision`) is PR 11's `DecisionRail` (8o.2); no count was added here. (4) The tasks name `test_settings_route_reads_no_exchange_scope` in `exchange-store.test.ts`; it asserts `isExchangeScoped("/settings")` there, and the behavioural proof (no tabs, no `/pools` request) is in `ExchangeTabs.test.tsx`. (5) `safe-storage` lives in `shared/auth/`, not `shared/`. (6) `stubApi` in the harness gained a third argument for pools and defaults to one Bybit pool, so the scope is ready in the existing tests.
- RED (assertions, never an import error: the store was a stub returning `[]`/`null`/`loading`, `ExchangeTabs` rendered `null`, the prop was ignored): the store file 15 of 27 failed (for example `expected 'loading' to be 'ready'`, `expected [] to deeply equal [ 'b', 'a', 'c' ]`), `BookingsListView` 4 of 15 (the other exchange's row still rendered), `ExchangeTabs` 17 of 22, `OverviewPage` 8 of 10. The tests that passed at once (persistence, loading, unscoped routes against the stub) were proved non-vacuous by the mutations below.
- Mutations, each restored, each turned the suite red: options not deduplicated (7 tests); default not first (9); storage key `sm.exchange2` (4); stale persisted value kept (5); filter removed (7); filter by prefix (1); tabs shown on `/settings` (3); `end: true` dropped from the route match (9); pools failure shows unfiltered bookings (3); pools loading shows unfiltered bookings (1); malformed pools body accepted (1); pools error treated as an empty ready scope (8); tabs request pools while locked (1); header allowed to shrink (2); tab row wraps instead of scrolling (2); narrow row moved inside the top row (9); click not wired (4); nothing persisted (4); raw `localStorage` instead of `safe-storage` (1).
- Gate: `npm run lint` 0, `npm test` 0 (153 tests, 14 files; 88 before), `npm run build` 0 (JS 380.33 kB, gzip 119.74). Backend untouched. `dist` not committed, `tsconfig.tsbuildinfo` restored. CRLF files stayed CRLF.
- Local view: `cd backend && uv run uvicorn strategy_manager.main:app --reload` and `cd frontend && npm run dev` (http://localhost:5173). With a token stored: (1) `/` shows one tab per exchange with pools, the first pressed; clicking another changes the rail to that exchange's pending bookings and the choice survives a reload. (2) `/strategies` shows the same tabs; `/settings` and `/nope` show none. (3) Narrow (under 1024 px): the tabs are a row below the top bar, scrolling sideways, and the page still does not scroll. (4) Stop the backend or block `/api/pools` in devtools: the tabs read "Exchanges could not be loaded" and the rail shows its message, never bookings. (5) In devtools set `localStorage['sm.exchange']` to `{"state":{"selected":"nope"},"version":0}` and reload: the first exchange is selected.

### Owner polish (requested 2026-09-30, not urgent; implement with the next PR that touches the tabs)

- [ ] 7p.1 Exchange display names are capitalised: `binance` shows as "Binance", `bybit` as "Bybit", `pionex` as "Pionex". This is display only, through one map or i18n key per exchange used everywhere an exchange name is shown (tabs, Settings cards, messages). The API identifiers stay lowercase, and the bookings filter and the scope store keep comparing identifiers, never display names.
- [ ] 7p.2 The exchange tab text uses the exchange's logo colour: Binance `#EBB42B`, Bybit `#EFA100`, Pionex `#F76C28`. The colours become `@theme` tokens in `index.css` (for example `--color-brand-binance`), never hex in a `className` (CLAUDE.md, Conventions). **Open question for the owner before building:** all three colours are amber/orange, and design § Visual design reserves amber (`decision`) for "needs your decision" only. The tabs themselves carry the amber "read-only" / "no key" sub-label (10c.4). Brand-coloured tab text could blur that signal. Options: brand colour on the tab text with the sub-label kept distinct (for example a badge shape); brand colour only on a small logo mark or dot; or brand colour only on the active tab.
- [x] 7p.3 (owner, 2026-10-02) The scrolling content has no padding at its bottom edge. With enough strategies to overflow the Strategies page, the last row sits flush against the bottom of the viewport. Add bottom spacing to the scrolled content, in the shell if the cause is there (then it covers every page), and check Overview with several pools too. RED first: a test that pins the bottom padding on the scroll container's content. Not urgent; do it with the next frontend PR that touches the shell or the Strategies page. Done 2026-10-03, commit 03937f2. Cause found in the shell: the content column carried `min-h-0`, so on a long page it was capped at the space `main` leaves, its content overflowed it, and the padding of `main` sat under the capped column instead of under the last row. Removing `min-h-0` from that column fixes every page. RED `expect(element).not.toHaveClass("min-h-0")`; a second test renders Overview with three pools and asserts that no ancestor up to `main` caps the height (passed at once; mutation: `min-h-0` back on the column reds both). The one test that pinned `min-h-0` on the column lost that class from its expectation. jsdom has no layout, so the owner confirms it by eye.
- [x] 7p.4 (owner, 2026-10-03) The ledger line of Overview overflows horizontally on a small screen. Each label and value pair of `LedgerLine` is `whitespace-nowrap`, added so a wide screen never breaks a line inside a pair; under 1024px a pair that cannot break is wider than the panel. The pairs hold together from `lg` up only (`lg:whitespace-nowrap`); below that they wrap like any text. RED: `frontend/src/features/overview/LedgerLine.test.tsx::holds each label with its value from lg up: a narrow screen may break inside a pair` and `frontend/src/features/overview/OverviewPage.test.tsx::keeps the ledger line to its own row: four pairs, each held together from lg up`, both replacing the tests that pinned the unconditional class. Done 2026-10-03, commit 2ab2762. RED on the assertion `expect(element).toHaveClass("lg:whitespace-nowrap")` in both files, one test each. Below `lg` a label can now break from its value; the owner accepted that for a small screen. jsdom has no layout, so the owner confirms it by eye. Confirmed by the owner on a small screen before PR 12c was pushed.
- [x] 7p.5 (owner, 2026-10-03) The enable history's height cap goes from `max-h-100` to `max-h-18`. The owner decided it after seeing the detail page with the webhook block (PR 12c) under the history: at `max-h-100` the page overflows vertically and the delete control falls off the screen; at `max-h-18` the whole page fits, delete control included, and the last four rows of the history stay visible, which is enough for now. It supersedes the value of task 9d.8. RED: `frontend/src/features/strategies/StrategyDetailPage.test.tsx::test_the_history_list_has_a_fixed_max_height_scrolls_and_is_keyboard_reachable`, its expectation changed to `max-h-18`. Done 2026-10-03, commit f3144aa. RED on the assertion `expect(element).toHaveClass("max-h-18 overflow-y-auto")` against `max-h-100`.

---

## PR 11 — Overview: ledger line, return chart, monthly grid, decision rail (1,300–1,800 lines)

**Split (2026-09-30, auto-chain, sequential PRs each cut from an up-to-date `main`):** the forecast is 1,300-1,800 lines, over the 400-line budget, so PR 11 ships as three PRs. **11a** = 8c-geometry + 8r-chart (the geometry has no consumer without the chart, so they travel together). **11b** = 8g-grid (`MonthlyGrid`, `LedgerLine`, `RangeSelector`, `MonthlySummary`, `PoolEyebrow`, presentational with typed props). **11c** = 8o-overview (`OverviewPage` wiring, `PoolPanel`, `DecisionRail` with the amber pending count; the first PR that touches live data and mounts the chart).

### Unit 8c-geometry — pure chart geometry (300–400 lines)

**Files**: Create `frontend/src/shared/charts/scale.ts`.

- [x] 8c.1 RED `frontend/src/shared/charts/scale.test.ts::test_waterline_scale_upper_band_takes_62_percent_lower_38_percent`, `::test_waterline_scale_each_band_floors_at_10_percent`, `::test_waterline_scale_negative_cumulative_return_crosses_into_lower_band`, `::test_line_path_no_smoothing_one_point_per_utc_day`, `::test_drawdown_path_closed_from_waterline_to_dd`, `::test_month_ticks_first_utc_day_of_each_month`, `::test_grid_band_zero_boundary_2_5_percent_boundary_15_percent_and_beyond`.
- [x] 8c.2 GREEN: `waterlineScale(up, down, height, waterRatio)`, `linePath(points)`, `drawdownPath(points, waterY)`, `monthTicks(dates)`, `gridBand(value)` — pure functions.

Gate: `cd frontend && npm test`.
Harness: pure, no DOM.
Rollback boundary: one new file with no consumer yet; revert is trivial.
Forecast: 300–400 lines.

**Done (PR 11a, unit 8c-geometry, commit `98d89c7` on `feat/operator-panel-return-chart`, not pushed).**
- Size: 351 lines added across 2 files (`scale.ts` about 150, `scale.test.ts` about 200). Nothing cut.
- **Contracts** (all pure, UTC, ratios as numbers where 0.05 is 5%): `waterlineScale(up, down, height, waterRatio)` returns `{waterY, upperMax, lowerMax, y(value)}`; `up` is the largest positive extreme and `down` the magnitude of the deepest negative one; each band's extent is `max(extreme, 0.10)`; `waterY = height * waterRatio`; positive values map linearly into the upper band, negative ones into the lower. `linePath` writes `M x,y L x,y ...` (one vertex per point, two decimals, no curves; empty gives `""`, one point gives a bare `M`). `drawdownPath` writes `M first.x,waterY L ...points L last.x,waterY Z` (empty gives `""`). `monthTicks(dates)` returns `{date: "YYYY-MM-01", year, month}` for every first-of-month inside the series' span, parsed with `Date.UTC`. `gridBand(value)` is `min(6, ceil(|value| / 2.5%))`, 0 for exactly zero, with float noise rounded away. The tasks name five functions; two helpers were added because the chart needs them: `timeScale(dates, left, right)` (x linear in UTC time, the midpoint for one day) and `tickValues(max)` (the finest of 5/10/25/50% steps that keeps a band at five gridlines or fewer).
- **Discrepancies with the documents**: (1) `timeScale` and `tickValues` are extra exports. (2) x is proportional to the UTC date, not the point index, so a day with no closed trade does not distort the axis; the design says "one point per UTC day of `curve[]`" and does not say whether the backend emits every day. (3) `monthTicks` ticks only real 1sts: a series starting on 14 July gets no "Jul" label, unlike the mockup, which labels the start. A span inside one month has no labels.
- RED (assertions, against a stub returning `waterY: 0`, `""`, `[]`, `0`): 20 of 20 failed, for example `expected +0 to be close to 173.6` and `expected '' to be 'M0,10 L10,20.5 L20,5 L30,7.25'`.
- Mutations, each restored: the 62/38 split swapped (4 tests red); the 10% floor removed on the upper band (3) and on the lower band (2); smoothing (an `S` command) added (2); local time instead of UTC in the date parse (1, the test sets `TZ=America/Los_Angeles`); the drawdown path not closed, either the last edge or the `Z` (2 each). Removing the float-noise rounding in `gridBand` survived at first, because 0.075 and 0.15 round DOWN in binary, so the test `gridBand(0.025 * 3)` (0.07500000000000001) was added and kills it. One mutation is equivalent and survives: `getFullYear` for `getUTCFullYear` in `monthTicks`, because the "step to the first inside the span" branch compensates for the shifted start month.

### Unit 8r-chart — `ReturnChart` component (400–550 lines)

**Files**: Create `frontend/src/features/overview/ReturnChart.tsx`.

- [x] 8r.1 RED `frontend/src/features/overview/ReturnChart.test.tsx::test_renders_polyline_and_drawdown_path_from_curve_prop`, `::test_empty_state_no_closed_trades_yet_when_curve_is_empty`, `::test_chart_always_shows_all_range_selector_does_not_rebase_axis`, `::test_role_img_aria_label_from_i18n`.
- [x] 8r.2 GREEN: `ReturnChart` — one inline `<svg>`, `role="img"`, waterline at 0%, polyline via `linePath`, drawdown fill via `drawdownPath`, gridlines and tick labels, colours via utility classes only (`stroke-gain`, `fill-loss/20`, `stroke-rule-strong`).

Gate: `cd frontend && npm test`.
Harness: jsdom (no `ResponsiveContainer` measurement issue — this is exactly why recharts was rejected).
Rollback boundary: one component; revert removes it, Overview shows nothing where it was mounted.
Forecast: 400–550 lines.

**Done (PR 11a, unit 8r-chart, commit `06f46c5` on `feat/operator-panel-return-chart`, not pushed).**
- Size: 513 lines added across 5 files (`ReturnChart.tsx` about 215, `ReturnChart.test.tsx` about 270, the `CurvePoint` type and 7 lines per locale). Nothing cut. Nothing mounts `ReturnChart` yet; PR 11c does.
- **Sizing**: one inline `<svg role="img">` with `viewBox="0 0 796 330"`, `preserveAspectRatio="xMidYMid meet"`, `w-full h-auto`, no width or height attribute and no measurement, so it renders the same in jsdom. Inside an `overflow-x-auto` wrapper the svg has `min-w-[560px]`: on a phone it scrolls sideways instead of shrinking the 10 px ticks to about 4.5 px, and at 560 px wide it is about 232 px tall, close to the design's "about 220 px on a phone". Plot: x 44 to 790, y 16 to 304, waterline at 62% (y 194.56); a 44 px left gutter; month labels at y 322.
- **Payload**: `CurvePoint {date, daily_return, index, drawdown}` in `shared/api/types.ts`, from `CurvePointBody`; all strings. The cumulative return is `index - 1`; the lower extreme is the deepest of the drawdown and a negative cumulative return.
- **Behaviour**: curve and drawdown edge are `<path>` from `linePath`, the fill from `drawdownPath` (`fill-loss/20`, edge `stroke-loss` 1.4, curve `stroke-gain` 2.2 round joins, waterline `stroke-rule-strong` 1.5, gridlines `stroke-rule-soft`). Y labels are `+30%`, `0%`, `−5%` (U+2212). Month labels use `Intl.DateTimeFormat` in UTC in the active language, and a label closer than 28 units to the previous one is dropped. The curve is always the whole series: the component has no range prop and no button. An empty curve draws the waterline, the `0%` label and "No closed trades yet" (no gridlines, no fill). One day draws a dot at the centre. A flat series stays on the waterline without `NaN`.
- **Discrepancies with the documents**: (1) the caption and the title (design, "The signature") are rendered by the component, as a `<figure>` with an `<h2>`; PR 11c may wrap it but should not add them again. (2) The design says a phone height of about 220 px; the component scrolls under 560 px wide instead of switching to the Mobile mockup's 358x200 viewBox, which would need a media query or a measurement. Left for the owner's visual review in 11c. (3) A value that does not parse (a non-decimal `index` or `drawdown`, a malformed date) renders an `alert` ("The return curve could not be read.") instead of a line; the design does not define this. (4) Line paths use `<path>` rather than `<polyline>`, because `linePath` returns a path string. (5) The chart never rebases on the range selector, as designed.
- RED (assertions, against a stub rendering `<svg role="img" aria-label="">`): 13 of 13 failed (`Unable to find an element by: [data-testid="return-curve"]`, `toHaveAttribute("viewBox", "0 0 796 330")`). The locale keys existed before the run, so no failure was a missing key. Every test then passed at once against the real component, so the mutations below stand in for a second RED.
- Mutations, each restored: waterline ratio 0.38 (3 red); axis rebased to the last 30 days (1); drawdown fill not closed (1); a hex colour in a `className` (3, including `theme.test.ts`); a hex `stroke` attribute (2); `var()` in a `className` (2); month label without UTC (2, the test sets `TZ=America/Los_Angeles`); smoothing (3); `aria-label` hardcoded (2). Survivors: the month-label spacing filter (a test with four years of months was added and kills it); the lower extreme ignoring a negative cumulative return, which is equivalent for valid data, since the drawdown is never above `index - 1` when the first peak is 1.
- Gate: `npm run lint` 0, `npm test` 0 (188 tests, 16 files; 153 and 14 before), `npm run build` 0 (JS 380.94 kB, gzip 120.03). Backend untouched. `dist` not committed, `tsconfig.tsbuildinfo` restored. CRLF files stayed CRLF.
- Local view: nothing mounts the chart, so there is nothing to see in the running app until PR 11c. To look at it earlier, temporarily render `<ReturnChart curve={...} />` with a hand-written curve in `OverviewPage` and do not commit that change.

### Unit 8g-grid — `MonthlyGrid`, `LedgerLine`, `RangeSelector` (350–500 lines)

**Files**: Create `frontend/src/features/overview/{MonthlyGrid,MonthlySummary,LedgerLine,RangeSelector,PoolEyebrow}.tsx`.

- [x] 8g.1 RED `frontend/src/features/overview/MonthlyGrid.test.tsx::test_band_maps_to_gain_or_loss_utility_class_by_sign_and_magnitude`, `::test_month_with_no_closed_trade_renders_dashed_empty_cell`, `::test_bands_4_to_6_use_text_ground_for_contrast`.
- [x] 8g.2 RED `frontend/src/features/overview/LedgerLine.test.tsx::test_lead_figure_is_available_balance_pnl_and_return_by_sign_null_return_renders_em_dash`.
- [x] 8g.3 RED `frontend/src/features/overview/RangeSelector.test.tsx::test_default_range_is_30d_pressed_state_aria_pressed_44px_minimum_touch_target`.
- [x] 8g.4 GREEN: the four presentational components, money parsed only for `Intl.NumberFormat` display (never computed client-side).

Gate: `cd frontend && npm test`.
Harness: jsdom.
Rollback boundary: presentational components with no server dependency beyond typed props; revert removes them.
Forecast: 350–500 lines.

**Done (PR 11b, unit 8g-grid, commits `0b1c8df`, `6e09c71` and `e34e2fb` on `feat/operator-panel-monthly-grid`, not pushed).**
- Size: 1,082 lines added across 15 files, over the 400 advisory budget because half of it is tests (about 590 test lines; components and `format.ts` about 465; wire types 28; 32 lines per locale). Nothing cut. Three commits: pool eyebrow and range selector (with `format.ts`, the wire types and the locale keys), `LedgerLine`, then `MonthlyGrid`, `MonthlySummary` and the token guard. Nothing mounts these components yet; PR 11c does.
- **Payload each component consumes** (all from `GET /api/performance/pools/{exchange}/{venue}/{ccy}` unless noted; every money and ratio is a decimal string):
  - `PoolEyebrow { exchange, venue, currency }`: `pool.exchange`, `pool.venue`, `pool.settlement_currency`.
  - `RangeSelector { value?, onChange }`: no payload; it reports a wire name (`7D`, `30D`, `90D`, `1Y`, `All`).
  - `LedgerLine { currency, available, range, pnl, ret, maxDrawdown }`: `currency`; `available` is `balance.available` from `GET /api/pools` (null while nothing has synced); `pnl` and `ret` are one entry of `ranges[]` (`pnl`, `return`); `maxDrawdown` is `max_drawdown`.
  - `MonthlyGrid { monthly }`: `monthly[] {year, month, return}`.
  - `MonthlySummary { monthly, excluded }`: `monthly[]` plus `excluded.open_trade_count` and `excluded.no_capital_at_open`.
- **Money formatting**: every figure goes through `Intl.NumberFormat` in the UI locale (`i18n.resolvedLanguage`), in `features/overview/format.ts`. The strings are parsed with `/^-?\d+(\.\d+)?$/` and anything else is `null`, so a value never becomes NaN and every component shows an `alert` instead. Amounts use `style: "decimal"` with fixed decimals (2, or 8 for BTC and ETH) and the currency is written beside them as a word: USDT is not an ISO 4217 code, so `style: "currency"` would throw. Ratios use `style: "percent"` with one decimal and `signDisplay: "exceptZero"`. Nothing adds, subtracts or converts money; the only arithmetic is the compounded year figure below, which is a ratio.
- **Discrepancies with the documents**: (1) The wire key is `return` (a pydantic serialization alias), not `value`, for months and ranges; the types use `return`. (2) There is no range parameter: the endpoint returns all five `ranges` in one body, so the selector only chooses which entry `LedgerLine` shows and 11c fetches once, not per range. (3) The available balance is not in the performance body; it is `balance.available` of the same pool in `GET /api/pools`, which 11c must pass in (the frontend `Pool` type only has four fields today). (4) `RangeBody.return` is never null on the pool report ("a window with no trades returns zero"); `LedgerLine` accepts a null return anyway (em dash, never "0%") because the strategy and pair reports reuse it with `return: null`. (5) **The YEAR column is computed in the browser**: the server sends no yearly figure, so it is `product(1 + month) - 1` over the server's months, as a ratio, display only (design: "the compounded year return from the server's months"). A month with no closed trade leaves the index where it was, so it contributes nothing. If "never compute" is meant to cover ratios too, the answer is a server field, not a client change. (6) The design draws the grid as a CSS grid `48px repeat(12, 1fr) 64px`; it is a `<table>` with `table-fixed`, `border-spacing-1` and `w-12` and `w-16` end columns, which gives the same geometry and native table semantics (column headers carry the full month name as `aria-label`, the year is a row header). The phone layout of Mobile.dc.html was not specially built; the owner's visual review in 11c decides. (7) A cell shows the number without `%` (as the mockup does) and its accessible name carries the percentage. The minus sign is the locale's hyphen-minus; the chart's y labels use U+2212, so the two differ slightly. (8) `MonthlyGrid` renders its own `<section>` and `<h2>` "Month by month", as `ReturnChart` renders its title; 11c must not add it again. `MonthlySummary` is a separate `<p>` that 11c places under the grid; it renders nothing when there are no months and nothing is left out. (9) Extras beyond the tasks: `format.ts`, the exports `RANGES`, `DEFAULT_RANGE` and `RangeName`, the tests `MonthlySummary.test.tsx`, `PoolEyebrow.test.tsx` and `panel-tokens.test.ts` (no amber `decision` utility and no literal display text in the five components), and `RangeSelector` accepts an optional `value` so 11c's `PoolPanel` can own the state while the default stays 30D. (10) Spanish groups thousands from five digits (`1284,52` but `12.845,52`): that is the locale's rule, so the tests use a five-digit balance. The range buttons read 7D, 30D, 90D, 1A and Todo in Spanish while `onChange` still reports the wire names.
- RED (assertions, against stubs: `MonthlyGrid` rendered an empty `<table>`, `LedgerLine` and `MonthlySummary` a `<p>stub</p>`, `RangeSelector` an empty `<div>`): 34 of 35 failed, all `Unable to find an element by: [data-testid="ledger-line"]` or `... role "group" and name "Range"` or `expected 'stub' to be undefined`; none was an import error or a missing locale key (the keys existed before the run). The one test that passed at once, the amber guard, was proved non-vacuous by a mutation.
- Mutations, each restored, each turned at least one test red (22): band sign inverted; empty month rendered as 0%; `text-ground` dropped on band 5 and on bands 4 to 6; empty cell not dashed; null return shown as "0%"; currency fixed to USDT (the stand-in for "money combined across two pools", see below); default range 7D; `aria-pressed` removed (3 red); touch target `min-h-9`; a hardcoded title and a hardcoded "deepest" instead of i18n; local-time month names (4 red, the test sets `TZ=America/Los_Angeles`); years oldest first; year summed instead of compounded; zero counted as positive (3); BTC at two decimals; the amber `text-decision` in `PoolEyebrow`; the percent symbol kept in a cell; `onChange` reporting the translated label; the zero band painted as gain; the no-capital part always shown (5). "Money summed across two pools or two currencies" has no direct mutation because no component sums anything (the only arithmetic is the year's ratio); `LedgerLine` is tested with a USDT and a BTC pool side by side, each in its own decimals, with no total on the page, and the fixed-currency mutation kills it.
- Gate: `npm run lint` 0, `npm test` 0 (223 tests, 22 files; 188 and 16 before), `npm run build` 0 (JS 382.58 kB, gzip 120.47). Backend untouched. `dist` not committed, `tsconfig.tsbuildinfo` restored. The new files are LF in the index; the existing CRLF files stayed CRLF.
- Local view: nothing mounts these components, so there is nothing to see in the running app until PR 11c. To look earlier, temporarily render `<LedgerLine ... />`, `<RangeSelector onChange={...} />` and `<MonthlyGrid monthly={[...]} />` with hand-written props in `OverviewPage` and do not commit that change.

### Unit 8o-overview — `OverviewPage`, `PoolPanel`, `DecisionRail` (300–450 lines)

**Files**: Create `frontend/src/features/overview/{OverviewPage,PoolPanel,DecisionRail,BookingCard}.tsx`; Modify query hooks for `['pools']`, `['performance','pool',...]`.

- [x] 8o.1 RED `frontend/src/features/overview/OverviewPage.test.tsx::test_renders_one_poolpanel_per_pool_never_merged_rule_7`, `::test_empty_ledger_dry_run_shows_defined_empty_states_no_error`.
- [x] 8o.2 RED `frontend/src/features/overview/DecisionRail.test.tsx::test_pending_bookings_wide_viewport_right_rail`, `::test_pending_bookings_narrow_viewport_inflow_block_between_chart_and_grid` (Mobile.dc.html ordering), `::test_no_pending_bookings_shows_nothing_needs_your_decision_no_amber_count`.
- [x] 8o.3 GREEN: `OverviewPage` container wiring `['pools']`, `['performance','pool',ex,venue,ccy]`, `['bookings','pending']`; `PoolPanel` composing `PoolEyebrow`+`LedgerLine`+`RangeSelector`+`ReturnChart`+`MonthlyGrid`+`MonthlySummary`; `DecisionRail` reusing `ConfirmBookingDialog`/`RejectBookingDialog`.

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: the page container; revert leaves the route empty, the shell (PR 10) untouched.
Forecast: 300–450 lines.

**Done (PR 11c, unit 8o-overview, commits `57d1015`, `c5bef02` and `665d842` on `feat/operator-panel-overview-page`, not pushed). This completes PR 11 (11a, 11b and 11c).**
- Size: 1,231 lines added across 18 files, over the 400 advisory budget because about more than half of it is tests (`OverviewPage.test.tsx` about 290 added, `DecisionRail.test.tsx` about 230, `performance.test.ts` and `pools.test.ts` about 140, harness 74; components `PoolPanel` 136, `DecisionRail` 93, `OverviewPage` 65, `performance.ts` 65, `useIsWide` 25, `usePendingBookings` 29). Nothing cut. Three commits: the data layer (types, pools validation, `usePoolPerformance`, harness), the Overview wiring with the rail, and one test that closed a surviving mutation.
- **Queries**: `['pools']` (unchanged, 60 s refetch) gives the exchange scope and every pool row; `['performance','pool',exchange,venue,ccy]` is fetched once per panel (`staleTime` 60 s, no range in the key, path segments URL-escaped); `['bookings','pending']` is now read through one hook, `usePendingBookings`, shared by the list and the rail's count, so they are one request. Nothing is fetched until the scope is known: while pools load or have failed there is no panel, no performance request and no bookings request (asserted on the requests, not only on the screen).
- **Available balance** is the pools row's `balance.available`. `Pool` now carries `balance {total, available, observed_at, stale} | null`, `reserved` and `allocatable`, and `fetchPools` validates them: a row without `balance`, or with a malformed one, is now a pools error (it was accepted before). A pool nothing has synced shows an em dash.
- **Per-panel states**: loading is a `status` line under the eyebrow; a failed report (500, network, malformed body, non-2xx) is an `alert` in that panel only and its neighbours and the rail keep working; a 404 (`fetchPoolPerformance` answers `null`) is a `status` "No performance report exists for this pool yet." and never an error; an empty ledger (the DRY_RUN reality, a 200 with zeros) renders the whole panel: ledger line at zero, the chart's own "No closed trades yet", the grid's own "No closed months yet". A stale balance adds a neutral `ink-2` note "Balance is out of date: last synced {UTC time}".
- **Rail placement**: `OverviewPage` chooses it with `useIsWide()` (`matchMedia("(min-width: 1024px)")`, `lg`) and renders the rail in exactly ONE place, because two CSS-hidden copies would double the dialogs and the landmarks. Wide: the right-hand column (`lg:grid-cols-[minmax(0,1fr)_22.5rem]`), `data-placement="right-rail"`. Narrow: an in-flow block between the first panel's chart and its month grid, `data-placement="in-flow"` (Mobile.dc.html order: ledger line and selector, chart, rail, grid); with no panel to sit in (no pool, or scope not ready) it follows the page instead. `PoolPanel` is three slots (top, `betweenChartAndGrid`, bottom) so the rail keeps its place while the report loads.
- **Discrepancies with the documents**: (1) The task's Files list names a new `features/overview/BookingCard.tsx`; none was created. The rail reuses `BookingsListView` with the existing `BookingCard`, `ConfirmBookingDialog` and `RejectBookingDialog`. (2) Changes to `BookingsListView`: the query moved to `usePendingBookings`, an optional `emptyText` prop, and `min-h-11` on both actions (design: at least 44 px). The buttons still read "Approve" and "Reject", not the mockup's "Review and approve", and the card is not restyled to the mockup's symbol, expiry and mono details; that is polish. (3) The rail's empty line is now "Nothing needs your decision." (design) instead of "No pending bookings." for the rail only; `bookings.empty` stays the default, so `router.test.tsx` and three `OverviewPage` tests were updated to the new key. (4) The rail is a bordered, rounded `bg-panel` card inside `main`'s padding, not the full-height column with only a left border, and it is not sticky; the phone mockup's amber border around the block is not used (amber stays on the count alone). (5) With more than one pool on a phone the rail sits in the FIRST panel only. It remounts once when the first panel appears (the scope resolves first), which loses nothing because the list is cached. (6) `GET /pools` also lists disabled pools, and every pool of the exchange gets a panel, enabled or not. Locally the three Pionex pools are disabled and their balance snapshots are about 41 days old, so a Pionex tab shows three panels with a stale note. There is no "disabled" mark because no string is defined for it: follow-up for the owner's review. (7) The design says only that `stale` exists, not how it looks; it is a neutral note, because amber is reserved and a loss colour is for losses. (8) No "no balance synced" note beyond the em dash. (9) The Overview request set is 1 + pools + 1; `refetchInterval` was not added to the performance query (60 s `staleTime`, refetched on mount and on window focus). (10) `aria-label` of a panel is the raw `exchange · venue · ccy` identifier, like the eyebrow. (11) The grid still has no phone layout of its own, and the chart still scrolls sideways under 560 px; both stay for the owner's visual review. (12) The amber allow-list is now a real allow-list (`panel-tokens.test.ts` scans every non-test source and expects exactly `DecisionRail.tsx` and `DryRunBadge.tsx`), and `PoolPanel` and `OverviewPage` joined the deny-list of the ledger components. (13) The harness gained per-pool performance stubs (`stubApi` fourth argument, default: an empty ledger for any pool), `emptyPerformance`, a `balance` argument on `pool()` and `setViewport`; `useIsWide` reads as wide when `matchMedia` does not exist.
- RED (assertions, against stubs: `PoolPanel` rendered an empty `<section>`, `DecisionRail` an empty `<aside>`, `OverviewPage` was the placeholder; `performance.ts` returned `undefined` and `[]`): 22 of 39 in the two page files failed on a `Unable to find an element` for `pool-panel`, `ledger-lead`, the empty texts and the like, `performance.test.ts` 13 of 13 on values (`expected [] to deeply equal [...]`) and `pools.test.ts` 6 of 8 on `promise resolved ... instead of rejecting`. The locale keys existed before the run, so no failure was a missing key. Tests that passed at once (rail still shows the no-exchange text, the confirm dialog opens, a pending bookings list shows no count, no request while pools fail) were proved by mutation; the last one survived the first time and `665d842` fixed it.
- Mutations, each restored, each turned at least one test red (23 of 23, one of them only after an extra test): two pools merged into one panel (5); another exchange's pool shown (6); an empty ledger shown as an error (7); two pools sharing one performance query (6); the amber count at zero (4); the explainer at zero (2); narrow layout without the rail between chart and grid (1); wide layout with the rail inside the panel (5); bookings shown while pools fail (2, after `665d842`); available from `balance.total` (5) and from `allocatable` (1); a second performance fetch when the range changes (2, with the key carrying the range); a 404 read as an error (2); a malformed report accepted (7); the stale flag ignored (1), always shown (1) or in amber (3); the count not filtered by exchange (3); actions under 44 px (1); the rail's empty wording dropped (4); the range state shared across panels (2); the pools balance check dropped (6); the chart rebased on the range (1).
- Gate: `npm run lint` 0, `npm test` 0 (277 tests, 25 files; 223 and 22 before), `npm run build` 0 (JS 399.04 kB, gzip 125.80). Backend untouched. `dist` not committed (ignored), `tsconfig.tsbuildinfo` restored. New files are LF in the index, existing CRLF files stayed CRLF.
- Owner visual review (local): the local database has ONE closed Bybit `usdt-m` trade, but it has no capital at open (`excluded.no_capital_at_open` 1) and two rehearsal fills, so the curve and the months are empty and the chart shows "No closed trades yet". A populated chart needs a seed or a fixture; none was created or committed. Options that never touch production: restore a fresh backup into a throwaway database, insert closed round trips into its `ledger_entries` with a pool total at open, and start the API with `DATABASE_URL` pointing at it; or temporarily make `fetchPoolPerformance` return a hand-written report and do not commit it.

**Review fixes (decisions 33-35, owner visual review of PR 11c, commits `41f77df`, `2a09c3e` and `08e8d77`, not pushed).**
- Size: 1,074 lines added and 159 removed across 14 files, about 70% tests; over the 400 advisory budget and kept as one PR because the three pieces were reviewed together and ship together. Nothing cut. The removed lines are mostly the table's re-indentation inside its scroll wrapper and the superseded 8r test.
- **Chart follows the range (33)**: `PoolPanel` owns the range and passes it to `LedgerLine` and to `ReturnChart` (`range`, plus `asOf`, the report's `dataUpdatedAt`). Pure functions in `shared/charts/scale.ts`: `windowStartDate`, `sliceAndRebase`, `dayTicks`, `utcDate`. `All` is the full curve with the server's drawdown, unchanged. A shorter range keeps the curve days whose UTC date is on or after the UTC date of `now - N days` (7, 30, 90 and 365 days, the backend's `_RANGE_DAYS`), rebases them on the index of the last day BEFORE the window (1 when none, the server's E_0), and recomputes the drawdown from the running peak inside the window, starting at the rebased 1. Bounded windows run on their own axis, from the window start to today, so a quiet stretch at either end is empty space rather than a stretched line; All keeps the span of its data.
- **Consistency with `ranges[]`**: the rebased last point equals `ranges[].return` for every range when no UTC day straddles the window edge. Proven in `scale.test.ts` against a TypeScript port of the server's algorithm (`curve.py`: same-day returns summed, days compounded, each range built from the trades inside `[now - N days, now]`) and in `OverviewPage.test.tsx` through the DOM (`data-final-return` against the `ledger-return` source, all five ranges). ASSUMPTION, documented in the test: the server cuts a window on an INSTANT, the curve is whole UTC days, so a day holding trades both before and after the start instant is counted whole by the chart and partly by the server. This is a structural difference, not a bug; it only ever moves the edge day, and a test pins it. The browser clock stands in for the server's `now` (the report's fetch time), so a browser more than a day off shifts the window. The local fixture's `ranges[]` use the same whole-day window from the same points, so the owner sees exact agreement there.
- **Ticks, always UTC**: 7D one label per day (`Sep 23`); 30D one per week from the window start; 90D, 1Y and All one per month start (labels closer than 28 units are dropped, as before). A label on the right edge is anchored at its end so it is not clipped. Empty states: a curve with no days at all keeps "No closed trades yet"; a curve with days but none in the window shows "No closed trades in this range" (a plain message, not an `alert`, no flat line). One day in the window is a dot on the rebased scale. The 62/38 waterline and the 10% floor apply to the rebased series.
- **Grid (34)**: the three most recent UTC years that have a closed month are rows; older ones sit behind a real `<button>` ("Show earlier years" / "Hide earlier years", EN and ES) with `aria-expanded`, `aria-controls` and `min-h-11`. Only rows are cut: each year's total still compounds all of its months and `MonthlySummary` still reads the full history (an `OverviewPage` test with five years pins both).
- **Sizing (35)**: panel `max-w-[50rem]`, its column `xl:max-w-[50rem]`, so the chart is about 332 px tall and the rail sits next to it. Rail `xl:w-[clamp(15rem,25%,22.5rem)]`, fluid, in a flex row packed from the left (the old grid column held 22.5 rem and, with a `1fr` panel, pushed the rail to the far edge). **Breakpoint: the rail goes beside the panel only from `xl` (1280 px), not `lg`.** At 1024 px the content area is 744 px; a 15 rem rail would leave the panel under 500 px, less than the grid's 13 columns need, which is exactly the overlap the owner saw. Between 1024 and 1279 px the rail uses the existing in-flow placement between the chart and the grid. `useIsWide` takes an optional query (default unchanged). The month table has `min-w-[42rem]` inside an `overflow-x-auto` wrapper, like the chart's 560 px floor, so figures never overlap: the panel is at least 672 px wide from 768 px up, and narrower screens scroll sideways. Range selector: `flex-wrap`, `shrink-0`, `max-w-full`, and its row `md:flex-wrap`, so all five 44 px buttons stay visible down to 390 px (about 265 px wide) and the selector drops under the ledger line when the row is tight. Month cells went from 40 to 32 px.
- **Pixel budget (design target, NOT measured in a browser; jsdom has no layout)**: at 1440x900 the content height is 900 - 64 (top bar) - 56 (main padding) = 780 px. Needed: title and gap 56, eyebrow and gap 32, ledger row 46 and gap 16, chart 368 (title 24, gap 12, SVG 332) and gap 16, grid 170 (title 24, gap 10, header and three 32 px rows 136), summary and gap 24, about 728 px, so about 50 px spare. With more than three years the toggle adds about 54 px and overshoots by a few px at 900; at 1920x1080 (960 px available) everything fits with room. If the owner's real viewport is shorter than 900 (browser chrome), the first thing to give is the cell height.
- **Tests**: `scale.test.ts` +18 (window start, rebase, peak inside the window, day ticks, server-port consistency), `ReturnChart.test.tsx` rewritten around `range` and `asOf` (the 8r "does not rebase" test is replaced by the window tests, coverage kept: All still draws every day on its own peak), `MonthlyGrid.test.tsx` +10, `RangeSelector.test.tsx` +1, `OverviewPage.test.tsx` +15 and one removed (chart follows the range, agrees with the ledger line for all five ranges, per-panel independence, empty range, whole-history summary, the sizing class contract and the 1280 px query). Dates are faked with `vi.useFakeTimers({ toFake: ["Date"] })`.
- **RED** (each batch failed on assertions before its implementation, against stubs for the pure functions and with the range props ignored): `scale.test.ts` 17 of 39 (`expected '' to be '2026-09-23'`, `expected [] to deeply equal [...]`; five read an empty result and failed with "Cannot read properties of undefined"); `ReturnChart.test.tsx` 15 of 31 (`expected [ Array(6) ] to have a length of 4 but got 6`, empty label lists); `OverviewPage.test.tsx` 8 of 36 (`expected 101 to be 8`, the final return of All against each range's); `MonthlyGrid.test.tsx` 8 of 21 (`expected [ Array(5) ] to deeply equal [ '2026', '2025', '2024' ]`, the rest on the missing toggle and the missing wrapper class); the sizing batch 6 of 134 (a missing `max-w`, `rail-slot`, query and classes).
- **Mutations**, each restored, each turned at least one test red: rebase on the first point inside the window (7); peak carried in from before it (1); exclusive window start (6); local-time window date (4); range not passed to the chart (10); month ticks on 7D (4); weekly ticks as daily (1); day labels in local time (4); empty range drawn as an `alert` (4); 90D drawn as All (2); all years shown (8); toggle without `aria-expanded` (3); every table month list cut to its latest 14 entries (7); summary fed only the latest 3 months (1); no scroll wrapper on the table (1); toggle without its 44 px target (1); rail fixed at 22.5 rem (1); panel without a max width (1); panel column unbounded (1); rail beside the panel from 1024 px (1); selector `flex-nowrap` (2); selector allowed to shrink (2); its row without wrap (1); 40 px cells (1); the old grid-column layout back (1). Note: "the YEAR column limited to the visible years" has no separate mutant, because the year total is per row; its real risk is cutting months rather than rows, which the 14-month mutant covers.
- Gate: `npm run lint` 0, `npm test` 0 (337 tests, 25 files; 277 before), `npm run build` 0. Backend untouched; `dist` ignored, `tsconfig.tsbuildinfo` restored. `vite.fixture.config.ts` (local, in `.git/info/exclude`) now generates four years back so the toggle shows; it is not staged.
- Owner re-review: 1024, 1440, 1920 and 390 px; each range (the chart and the ledger line must agree, the last point of the line sits at the ledger's return); the year toggle (the fixture has five years, so it shows).

**Review fixes, round 2 (decisions 36 and 37, owner's second visual review of PR 11c, commits `10c644c`, `cf49809` and `67143bb`, not pushed).**
- Size: 553 lines added and 118 removed across 10 files, about 63% tests. Nothing cut. Three commits, one per piece.
- **Chart sizing (36)**: `shared/charts/useElementWidth.ts` is a `ResizeObserver` hook returning a callback ref and the width to draw at: the 796 px default before the first measurement and wherever there is no `ResizeObserver` (jsdom), an empty reading (0, a hidden box) ignored, the observer disconnected on unmount. `ReturnChart` draws `viewBox="0 0 {width} 280"` with `height="280"`, `block w-full`, no `preserveAspectRatio` and no `h-auto`; `width` is never below 280 (`MIN_WIDTH`). Vertical geometry: top 12, plot 244 (zero line at 163.28 with the 62/38 split), month labels at y 274; horizontal: left 44, right margin 6. Text sizes and strokes are the same at every width. The 560 px floor and the horizontal scroll wrapper are gone, because the box now follows the panel down to 280 px.
- **Layout (36)**: `PoolPanel` and its column have no `max-w`. `ReturnChart` takes `headerAction` and renders `data-testid="chart-header"`: title with its caption UNDER it on the left, the `RangeSelector` on the right, `flex-wrap justify-between`, so the 44 px selector sets the row height and the caption costs nothing; on a phone the header wraps the selector onto a second row rather than clip it (kept when the curve is unreadable, so the range still works). The stale note is a sibling of the eyebrow on one `flex-wrap justify-between` row. `LedgerLine` is four `Pair`s (`data-testid="ledger-pair"`, `whitespace-nowrap`, the " · " separator inside the pair so it never starts a line); the lead figure is `leading-none` and the line `leading-normal` (was 1.7), which takes the row from about 46 to about 30 px. Panel gaps `gap-4` to `gap-3`, the grid and summary `gap-2` to `gap-1.5`, the chart figure `gap-3` to `gap-2`.
- **Pool order (37)**: `features/overview/poolOrder.ts`, `orderPools()`, used by `OverviewPage`. Enabled first, then USDT by `balance.available` descending (a pool with no or unreadable balance last among them), then other currencies by code; stable, input untouched; no sum anywhere. Follow-up below.
- **Pixel budget (design target, an ESTIMATE from the classes, NOT measured in a browser; jsdom has no layout)**. Available height = viewport - 64 (top bar, `lg:h-16`; the owner counted 62) - 56 (`main` `py-7`). At 1920x915: 795 px; at 1440x900: 780 px. Needed, top to bottom: page title and gap 56; eyebrow row 17 and gap 12; ledger line 30 (one line; 52 if a line wraps) and gap 12; chart header 44 (the selector) and gap 8; SVG 280; gap 12; grid title 24, gap 10, table 133 (header 17 and three 32 px rows, with 4 px spacing) = 167; gap 6; summary 17. **Total 661 px**: spare 134 px at 1920x915 and 119 px at 1440x900. A wrapped ledger line costs 22 more; the "Show earlier years" toggle (four or more years) costs about 54, and both together still leave about 43 px at 1440x900. Widths: the content area is 1640 px at 1920 (rail 360, panel about 1252) and 1160 px at 1440 (rail about 290, panel about 842). At 1024 px the rail is in-flow (between the chart and the grid) and the page may scroll; that is not the criterion. Expanded "earlier years" may overflow (accepted). If the owner's real viewport is shorter than these, the chart's 280 px is the first thing to give (240 still reads).
- **Tests** (+24, 361 in 26 files; 337 before): `ReturnChart.test.tsx` +7 (the pixel viewBox, the redraw at a new width with the height fixed, constant strokes and fonts, an empty reading ignored, the 280 px floor, disconnect on unmount, the header action with the caption beneath, the action kept on an unreadable curve; the 796x330 scaling test is replaced and the geometry constants moved to the 280 box), `LedgerLine.test.tsx` +1 (four nowrap pairs), `OverviewPage.test.tsx` +8 net (no max width on panel or column; fixed chart height; selector in the chart header and still driving the ledger line and chart; header and group wrap and never shrink; stale note on the eyebrow's row; four nowrap pairs; panels in the interim order) and the decision-35 max-width test replaced, `poolOrder.test.ts` +10 (new file).
- **RED** (assertions, before each implementation): chart sizing 14 of 36 on values (`expected 194.56 to be close to 163.28`, `expected "spy" to be called at least once`, a `viewBox` of 796x330 against 796x280), with a stub hook that never measured; layout 9 of 147 (`expected [] to have a length of 4 but got +0`, `expected 'flex w-full min-w-0 max-w-[50rem] fle...' not to match /max-w-/`, `expected null not to be null` for the header, the stale note's parent being the panel itself, and the action missing from the header); pool order 9 of 57 on orderings (`expected [ 'coin-m/ETH', ... ] to deeply equal [ 'usdt-m/USDT', ... ]`) against a stub that kept the server's order. Tests that passed at once were proved by mutation, below.
- **Mutations**, each restored, each turned at least one test red: chart height scaling with width (4); the width hook ignoring resizes (3); strokes scaled with the width (1); an empty reading accepted as a width (1); the 280 px floor dropped (1); no disconnect on unmount (1); panel `max-w-[50rem]` put back (1); its column `xl:max-w-[50rem]` put back (1); a ledger pair allowed to split (2); the whole ledger line `whitespace-nowrap` (2); the chart header `flex-nowrap` (2); the selector `flex-nowrap` (2) and allowed to shrink (2); the stale row without `justify-between` (1); the stale note as a block of its own under the panel (1); the selector back on its own row under the ledger line (2); the selector not passed to the chart (14); the pool order ignoring `enabled` (2); ordering by currency code only (14); ranking by the SUM of a currency's pools (7); comparing the balance as text (5); ascending by balance (6); an unsynced pool ranked first (2); the order not wired into the page (1); the input array sorted in place (1, after an extra test: the first version of the test let a stable no-op sort pass).
- Gate: `npm run lint` 0, `npm test` 0 (361 tests, 26 files), `npm run build` 0 (JS 402.45 kB, gzip 126.89). Backend untouched; `dist` ignored and `tsconfig.tsbuildinfo` restored. `vite.fixture.config.ts` stays local and unstaged.
- Owner re-review: 1920x915 and 1440x900 with one pool (no page scroll, chart 280 px tall and as wide as the panel, selector at the top right of the chart header, nothing below the fold), then resize the window (the chart redraws at the new width); the stale note on the eyebrow's row (Bybit, whose local snapshot is about 33 days old); a BTC or ETH ledger line (no pair split); 1024 and 390 px (all five selector buttons visible); Pionex's three disabled pools (order: USDT, then BTC, then ETH).

### Unit 11f — follow-ups to PR 11 (not started)

- [ ] 11f.1 Order the Overview's pools by USD value, descending. The interim order (decision 37) cannot rank a BTC or ETH pool against a USDT one, because the system has no live price (`FixedUsdRateProvider` knows only USDT = 1). Needs a backend USD valuation per pool (for example the venue's mark price or ticker at read time) exposed as `usd_value` on `GET /api/pools`, for display and sort only and NEVER summed (rule 7); then `orderPools` sorts enabled pools by `usd_value` descending. It touches only multi-pool exchanges (Pionex today, whose pools are all disabled). RED first: a pools stub whose BTC pool outranks its USDT pool by `usd_value`.

---

## PR 12 — Strategies list + detail + dialogs + webhook message + Show secret (1,400–1,900 lines)

### Unit 9l-list — `StrategiesPage`, list, new-strategy dialog (400–550 lines)

**Files**: Create `frontend/src/features/strategies/{StrategiesPage,StrategyRow,ArchivedToggle,NewStrategyDialog}.tsx`.

- [x] 9l.1 RED `frontend/src/features/strategies/StrategiesPage.test.tsx::test_archived_excluded_by_default_toggle_shows_them`, `::test_row_shows_name_pool_enabled_toggle_uptime_trades_pnl_return`.
- [x] 9l.2 RED `frontend/src/features/strategies/NewStrategyDialog.test.tsx::test_id_generated_via_crypto_randomuuid`, `::test_submitting_with_zero_pairs_is_prevented`.
- [x] 9l.3 GREEN: list container + row + dialog, `['strategies',{includeArchived}]` query.
- [x] 9l.4 Row sub-line shows the venue and the allowed pairs (decision 39). RED `frontend/src/features/strategies/StrategiesPage.test.tsx::test_row_shows_name_pool_enabled_toggle_uptime_trades_pnl_return` (asserts the exchange and the bare currency are gone), `::shows the venue alone, with no trailing separator, when a strategy has no allowed pairs`.

Gate: `cd frontend && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: one page; revert leaves the route empty.
Forecast: 400–550 lines.

### Unit 9d-detail — `StrategyDetailPage`, lifecycle controls (500–700 lines)

**Files**: Create `frontend/src/features/strategies/{StrategyDetailPage,StrategyHeader,EnableToggle,UptimeSummary,AllowedPairsEditor,ArchiveDialog,EnablementHistory}.tsx`.

- [x] 9d.1 RED `frontend/src/features/strategies/StrategyDetailPage.test.tsx::test_shows_active_x_days_since_first_activation_date`, `::test_never_enabled_shows_no_activation_date`. Done 2026-10-03, commit 5ad262e. RED against the placeholder page: 13 of 13 failed on testing-library lookups (`Unable to find role="heading" and name "ETH Breakout"`). Uptime reads "active 10 days since Aug 12, 2026", or "active at least ..." for a baseline first activation; a never-enabled strategy shows `never enabled` and no `since`.
- [x] 9d.2 RED `frontend/src/features/strategies/ArchiveDialog.test.tsx::test_archive_requires_explicit_confirmation_not_single_click`, `::test_409_open_position_reasons_rendered_symbols_allocations_reservations_attempts`, `::test_409_still_enabled_rendered`. Done 2026-10-03, commit f8dc37d (the calls are in f1efb9f). The tests are in `ArchiveDialog.test.tsx`, the single-click one through `ArchiveControl`. RED against stubs: 17 of 18 failed (16 on lookups of the i18n key text, one on `expected [] to deeply equal [ Array(19) ]`); the archived-strategy case passed at once and was proved by mutation (offering the control anyway reds it). The dialog is a native `<dialog>`; Confirm is its own button. A malformed `OPEN_POSITION` body shows the main sentence alone.
- [x] 9d.3 RED `frontend/src/features/strategies/AllowedPairsEditor.test.tsx::test_removing_last_pair_without_replacement_prevented`, `::test_adding_a_pair_submits_full_updated_set`. Done 2026-10-03, commit 2cf37a1, driven through `PairSelector`. RED against a `<div />` stub: 11 of 11 on lookups. The last pair can be removed on screen but Save stays disabled with a text.
- [x] 9d.4 GREEN: the container + presentational tree per design's component list; `['strategy',id]`, `['strategy',id,'events']` queries. Done 2026-10-03: calls and hooks in f1efb9f (`['strategy',id]`, `['strategy',id,'events']`, 12 tests, 11 RED on assertions), `ArchiveControl`/`ArchiveDialog` in f8dc37d, `AllowedPairsEditor` in 2cf37a1, the page, `StrategyHeader`, `UptimeSummary`, `EnableToggle` and `EnablementHistory` in 5ad262e. The settings column holds the editor, the enable switch and archive, as in Strategy.dc.html; `WebhookMessage`, `StrategyPerformance`, `PairStatsTable` and `TradesTable` belong to units 9w and 9p. The exchange tabs follow the strategy's exchange (design § 15).
- [x] 9d.5 (added 2026-10-02, decision 41; needs PR 12v-4) `AllowedPairsEditor` is built on `PairSelector` (unit 9vd), never on a free-text field. RED `frontend/src/features/strategies/AllowedPairsEditor.test.tsx::test_stored_pair_missing_from_the_catalogue_is_kept_and_marked_no_longer_listed` (stored `SFPUSDT`, available pairs without it: the chip stays, and an untouched save sends it), `::test_a_removal_only_save_is_allowed_when_the_available_pairs_failed_to_load`, `::test_adding_is_blocked_while_the_available_pairs_failed_to_load`, `::test_409_pairs_changed_shows_the_review_and_save_again_text`, `::test_422_unknown_pairs_names_the_symbols`. 9d.3's two tests keep their names and meaning, driven through the selector. Done 2026-10-03, commit 2cf37a1. RED against a `<div />` stub: 11 of 11 on lookups (a failed pair list retries once after a second in the test client, so its tests wait up to 3 s). An edit made on a stored list that has since changed is dropped, so after `PAIRS_CHANGED` the operator reviews the stored list.
- [x] 9d.6 (added 2026-10-02, decision 42; needs PR 12x-5) Mount `<DeleteStrategyControl strategy={…} />` in its own block at the bottom of `StrategyDetailPage`, below the archive control (design addendum 9x § H). RED `frontend/src/features/strategies/StrategyDetailPage.test.tsx::test_the_delete_control_is_rendered_below_the_archive_control_for_the_loaded_strategy`. If unit 9d merges before PR 12x-5, this task is done there instead, as 9xe.5, and is ticked here with a pointer. Done 2026-10-03, commit 5ad262e: the control is in its own block below the grid, after the archive control in the settings column.
- [x] 9d.7 (added 2026-10-03, decision 42, owner answer after migration 0028) `DeleteStrategyDialog` stops naming enablement events among the reasons of a `HAS_HISTORY` refusal: since 0028 they do not block a delete, so "3 signals, 1 enablement event" suggested something the owner must resolve. The body still carries `enablement_events`; only the dialog stops rendering that kind, and the six counts are still all validated before any line is trusted. RED `frontend/src/features/strategies/DeleteStrategyDialog.test.tsx::test_a_refusal_with_a_signal_and_enablement_events_names_the_signal_and_not_the_events`, `::test_a_body_whose_only_nonzero_count_is_enablement_events_shows_the_main_sentence_alone`. The 9xe.2 test that pinned "enablement events named like any other kind" is replaced by these in the same commit, not deleted. The `strategies.delete.history.enablementEvents_*` keys become unused and are removed from EN and ES, and the key-set test follows. Done 2026-10-03: the decision and this task in 85831fd, the change in 62c3399. RED: 2 tests on assertions (`expected [ '3 signals', '2 enablement events' ] to deeply equal [ '3 signals' ]`, `expected [ <li></li> ] to have a length of +0 but got 1`) and the key-set test (`expected [ Array(25) ] to deeply equal [ Array(23) ]`). Renamed, not deleted: `renders a refusal naming enablement events like any other kind` became `names the signal and not the enablement events when a refusal carries both`; `shows the main sentence alone when the only non-zero count is enablement events` is new. One malformed-count case was added to the malformed-history table and proved by mutation. The `enablementEvents_*` keys left both locales.
- [x] 9d.8 (owner review by eye, 2026-10-03) The enable history no longer grows without bound: its `<ul>` has `max-h-96 overflow-y-auto`, is focusable (`tabIndex={0}`) and keeps its accessible name; a short list has no forced height; newest first stays. RED `frontend/src/features/strategies/StrategyDetailPage.test.tsx::test_the_history_list_has_a_fixed_max_height_scrolls_and_is_keyboard_reachable`. Done 2026-10-03, commit 7723eb1. RED on the assertion `expect(element).toHaveClass("max-h-96 overflow-y-auto")`. The owner then asked for `max-h-100` after looking at it in a browser: same test, RED on `expect(element).toHaveClass("max-h-100 overflow-y-auto")` against `max-h-96`, then GREEN.
- [x] 9d.9 (owner review by eye, 2026-10-03) The settings column overflowed the page from the start because the pair list of `PairSelector` was `max-h-60`; it is now `max-h-36` (the owner tried that value). `NewStrategyDialog` shares the component and gets the same height. RED `frontend/src/features/strategies/PairSelector.test.tsx::test_the_option_list_is_capped_at_max_h_36_and_scrolls_on_its_own`. Done 2026-10-03, commit 7723eb1. RED on the assertion `expect(element).toHaveClass("max-h-36 overflow-auto")`. No existing test pinned `max-h-60`.

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: one page; revert leaves `/strategies/:id` unreachable via the list (list still works).
Forecast: 500–700 lines. Actual: 1,858 changed lines in seven code commits (62c3399 41, 03937f2 53, f1efb9f 301, f8dc37d 529, 2cf37a1 352, 5ad262e 556, 7723eb1 26), of which about 330 are production code and the rest tests and locale keys, including 7p.3 and task 9d.7, which the forecast did not cover. Over the owner's 1,600-line stop threshold by about 14%; it was finished rather than split because the unit is one reviewable page, and the commits split cleanly after 2cf37a1 (the unmounted building blocks, then the page that mounts them) if the owner wants two PRs.

### Unit 9w-webhook — webhook message, Show secret (300–400 lines)

**Files**: Create `frontend/src/features/strategies/{WebhookMessage,webhook-message}.{tsx,fixture.json}`;
Create `backend/tests/signals/domain/test_webhook_message_fixture.py` (cross-language guard).

- [x] 9w.1 RED (backend) `backend/tests/signals/domain/test_webhook_message_fixture.py::test_frontend_fixture_parses_through_tradingview_alert_from_payload_after_placeholder_substitution` — reads `frontend/src/features/strategies/webhook-message.fixture.json` (read-only from this test's perspective) and parses it via `TradingViewAlert.from_payload` after substituting sample values for every `{{...}}` placeholder. Done 2026-10-03, commit 3fca0ed (line wrap in 2c956ef). RED on an assertion: against a stub fixture with `{{symbol}}` instead of `{{ticker}}`, the placeholder-set assertion failed (`Extra items in the left set: 'symbol'`). The test also asserts the fixture's placeholder set equals its sample set, so a new placeholder cannot slip in unparsed. Mutations proved it non-vacuous: `contracts` unquoted gives `AlertParsingError: data.contracts must be a string, got float`; `price` renamed gives `KeyError: 'price'`; `position_size` removed trips the placeholder-set assertion. All reverted. The fixture's `signal_type` holds `<strategy-id>`, deliberately not a `{{...}}` (TradingView would try to fill it); both sides replace whatever that field holds.
- [x] 9w.2 RED (frontend) `frontend/src/features/strategies/WebhookMessage.test.tsx::test_url_shows_placeholder_by_default_not_the_secret`, `::test_show_secret_click_fetches_get_webhook_secret_substitutes_in_place`, `::test_no_other_control_ever_requests_the_secret`, `::test_leaving_the_view_restores_placeholder_and_evicts_query_cache`. Done 2026-10-03, commits 2866928 (the pure function and its tests) and bc1db3b (component, query, locales, page). RED against a stub `<div />`: 17 of 17 component tests on testing-library lookups, and the four `webhookMessage` tests on assertions (`expected {} to deeply equal {...}`). Beyond the four named tests: Hide evicts, a strategy change starts from the placeholder, leaving while the request is in flight leaves nothing cached, no refetch on focus or reconnect, a refusal and three malformed bodies show the failure and no value, nothing reaches console, storage, a query key or a URL, and the page mounts it above the delete control. The first GREEN run caught a real defect: a view mounting while a cached secret still existed (moving between strategies) rendered it for one commit; `shown` now requires this view's own request. Mutations, each red and reverted: `useWebhookSecret(true)` (3 tests), no eviction on unmount (3), no eviction on Hide (1), default refetch policy (1), `shown` without `requested` (1), default retry (5), no `encodeURIComponent` (1), page mount removed (1).
- [x] 9w.3 GREEN: `webhookMessage(strategyId)` pure function rendering `signals/domain/alert.py:7-12`'s exact JSON shape with `signal_type` substituted; `WebhookMessage` component with local "revealed" state, `['webhook-secret']` fetched only on click, `queryClient.removeQueries` on unmount/navigate. Done 2026-10-03, commits 2866928 and bc1db3b. The secret is never copied into state: it is read from the query result while this view's request succeeded. The query sets `retry: false`, `staleTime: Infinity` and no refetch on focus, reconnect or mount.

Gate: `cd backend && uv run pytest --tb=short backend/tests/signals/domain/test_webhook_message_fixture.py` + `cd frontend && npm test`.
Harness: N/A backend (pure parse test reading a fixture file); `vi.stubGlobal("fetch")` frontend.
Rollback boundary: one shared fixture + one component; revert removes "Show secret", the placeholder-only message still renders.
Forecast: 300–400 lines. Actual: 738 changed lines in four code commits (3fca0ed 87, 2866928 77, bc1db3b 563, 2c956ef 11), of which about 150 are production code and locale keys and the rest tests; the tests are heavy because each way the secret could leak or linger has its own test.

### Unit 12f — follow-ups to PR 12b and PR 12c (decided 2026-10-03 and 2026-10-06; 12f.2, 12f.3 and 12f.7 closed with no work; 12f.1, 12f.4, 12f.5 and 12f.6 and the WIN RATE column are broken into tasks 12f.9.1 to 12f.10.32 in "PR 12f")

Recorded 2026-10-03. The design and the spec left these open, so the detail page was built
without them rather than with an invented answer. None is designed. Each one starts with the
owner's decision, recorded in owner-decisions.md, and only then gets a design note and tasks.

**Decided 2026-10-03 (owner-decisions.md, decision 44).** 12f.1: an editable field, a change
applies to the next allocation only. 12f.2: stays as built. 12f.3: stays a plain confirm button.
12f.4: a short "saved" text. 12f.5: two Copy buttons, URL and message, the URL's copying what is
on screen. 12f.6: the full URL, its host served by the backend from a setting. 12f.7: stays as
built. So 12f.2, 12f.3 and 12f.7 need no work and are closed; 12f.1, 12f.4, 12f.5 and 12f.6 wait
for their design note and tasks. The same decision settles unit 9p's gaps: a WIN RATE column in
By pair (needs the backend), no OPEN column, closed trades paged 20 at a time on a click, and
"LONG" / "SHORT" in Spanish too.

**Designed and tasked 2026-10-06 (design addendum "the detail page's follow-ups (unit 12f, decisions 44
and 48)"; owner-decisions.md, decisions 44 and 48).** The two paragraphs above, written on 2026-10-03,
no longer hold: every item is decided and designed, and nothing here waits for the owner. The tasks
are in "PR 12f — The detail page's follow-ups (decisions 44 and 48)", unit 12f.9 (backend, PR 12f-1)
and unit 12f.10 (panel, PR 12f-2). **The WIN RATE column of By pair** (the line above, from unit 9p's
gaps) is tasks 12f.9.1 and 12f.9.2 (backend) and 12f.10.2 to 12f.10.4 (panel); unit 9p's own ticked
task 9p.1 is not edited. The OPEN column stays dropped. 12f.2, 12f.3 and 12f.7 are closed below with no
work. Nothing is ticked on 12f.1, 12f.4, 12f.5 and 12f.6 until the tasks they point to are.

- [ ] 12f.1 (decisions 44 and 48, designed 2026-10-06; broken into tasks 12f.9.6 to 12f.9.12 backend and 12f.10.5, 12f.10.6, 12f.10.7, 12f.10.9, 12f.10.11 to 12f.10.24 panel; the questions this item raised were answered) **Share of the pool per trade.** `Strategy.dc.html` shows `allocation_percent` as an editable field in the settings column. No task of unit 9d covers it and the detail page does not show it. `PATCH /api/strategies/{id}` already accepts `allocation_percent`. To decide: whether it is editable from the panel, and what a change means for an allocation already reserved.
- [x] 12f.2 (closed by decision 44, 2026-10-03: stays as built, no work) **How an archived strategy looks on the detail page.** Unspecified. Built as read-only: the pairs editor and the enable switch are disabled, the archive control is hidden, the badge says "Archived", and the delete control is offered. To decide: whether that is the intended look.
- [x] 12f.3 (closed by decision 44, 2026-10-03: stays a plain confirm button, no work) **The archive confirmation.** A plain confirm button; the spec asks only for an explicit confirmation. The delete dialog makes the owner type the strategy's name. To decide: whether archiving, which is also permanent, should ask for the same.
- [ ] 12f.4 (decisions 44 and 48, designed 2026-10-06; tasks 12f.10.11, 12f.10.18 and 12f.10.19 panel; no backend) **Feedback after saving the allowed pairs.** There is none: the chips persist and the Save button disables. To decide: whether a "saved" confirmation is wanted, and in what form.
- [ ] 12f.5 (decisions 44 and 48, designed 2026-10-06; tasks 12f.10.10, 12f.10.11, 12f.10.26 and 12f.10.27 panel; no backend) **A Copy button beside the webhook URL.** `Strategy.dc.html` shows one; no task or spec scenario defines it, so it is not built and the text is selectable. To decide: what it copies (the URL with the placeholder, the URL with the secret, the alert message), since the second puts the secret on the clipboard.
- [ ] 12f.6 (decisions 44 and 5, designed 2026-10-06; tasks 12f.9.3 to 12f.9.5 backend and 12f.10.8 and 12f.10.25 panel) **The host in the webhook URL.** The mockup shows `https://[WEBHOOK HOST]/webhook/tradingview?...`; design.md says the path alone, and that is what was built, because the frontend does not know the public host. The owner prepends the host by hand when pasting into TradingView. To decide: whether the panel shows the full URL, and where the host comes from (a setting served by the API, never a value compiled into the bundle).
- [x] 12f.7 (closed by decision 44, 2026-10-03: stays as built, no work) **A revealed secret stays revealed.** There is no warning text beside it and no timer hides it; it goes when the owner hides it or leaves the view. To decide: whether either is wanted.
- [x] 12f.8 **Placement of the webhook block.** The mockup puts it last in the left column, after the "By pair" table, which belongs to unit 9p and does not exist yet. It sits after the enable history today. No decision needed: unit 9p (PR 12d) places it after the table it adds, and ticks this. Done 2026-10-03, commit 8b6e19e: the left column is now header, performance (ledger line, chart, month grid, By pair), closed trades, enable history, webhook block last. RED `StrategyDetailPage.test.tsx::test_left_column_runs_performance_by_pair_trades_history_and_ends_with_the_webhook_block` on a lookup (`Unable to find role="heading" and name "Contribution to the pool, compounded"`); the order is also pinned by mutation (webhook above the history: red). SUPERSEDED the same day by task 9p.9 (owner review by eye): the webhook block is no longer last in the left column; it is a disclosure opened from a button in the page header, closed by default.

### Unit 9p-pairs — `PairStatsTable`, `TradesTable`, `StrategyPerformance` (200–250 lines)

**Files**: Create `frontend/src/features/strategies/{PairStatsTable,TradesTable,StrategyPerformance}.tsx`.

- [x] 9p.1 RED `frontend/src/features/strategies/PairStatsTable.test.tsx::test_pair_removed_from_allowlist_still_shown_with_historical_stats`. Done 2026-10-03, commit d06340d (the API checks of `by_pair` are in 24dd6c4, the page-level twin `StrategyDetailPage.test.tsx::test_a_pair_removed_from_the_allowed_pairs_is_still_listed_with_its_stats_on_the_page` in 8b6e19e). RED against a `<div />` stub: 10 of 10 on testing-library lookups (`Unable to find an accessible element with the role "row" and name /^SOLUSDT/`). The table takes `by_pair` alone, so no allowed-pairs list can filter it. Columns: Pair, Trades, PnL {currency}, Return (the mockup's Win rate and Open columns are not served by `by_pair`: see the gaps).
- [x] 9p.2 RED `frontend/src/features/strategies/TradesTable.test.tsx::test_infinite_query_keyset_cursor_loads_more_on_scroll_or_click`. Done 2026-10-03, commit 25d7cb6 (`fetchStrategyTrades` and its validation in 24dd6c4). RED against a `<div />` stub: 16 of 16 on lookups (`Unable to find role="table"`). The keyset server double continues strictly after the row the cursor names, so a wrong cursor repeats or skips rows. LOADS ON A CLICK ONLY: the design says "infinite query, keyset cursor" and does not ask for scroll loading. Eight mutations red, all restored (cursor id rewritten 2, null return as zero 1, next-page failure unannounced 1, fees marker always on 3, first-page error as loading 2, null capital as zero 1, button with no cursor 2).
- [x] 9p.3 GREEN: both tables + the reuse of `LedgerLine`/`ReturnChart`/`MonthlyGrid` for one strategy's contribution. Done 2026-10-03, commits c1df70a (`StrategyPerformance`, reuse changes) and 8b6e19e (mounted). `LedgerLine` takes an optional `available` (omitted: no balance pair, the PnL leads) and `returnLabel`; `ReturnChart` takes an optional `title`; the Overview is unchanged (164 overview tests green). RED: `LedgerLine` 4 of 13 on value assertions (`expected 'The figures could not be read.' to be 'PnL 30D +41.20 · return 30D +3.4% · d…'`), `ReturnChart` 1 on a lookup, `StrategyPerformance` 12 of 12 on lookups against a stub.
- [x] 9p.4 (decision 43, designed 2026-10-04; merged and deployed 2026-10-05, PR #60) Backend, PR 12e-1: broken into tasks 9p.4.1 to 9p.4.38 in "PR 12e — A strategy's operations, listed and opened one by one (decision 43)", unit 9p.4 (figures, rehearsal rows on request, the fill-price classification, the fills route). Nothing is ticked here until that section's tasks are.
- [x] 9p.5 (decision 43, designed 2026-10-04; merged and deployed 2026-10-05, PR #61; tasks 9p.5.27 to 9p.5.33 were added by the owner's review) Frontend, PR 12e-2: broken into tasks 9p.5.1 to 9p.5.26 in "PR 12e — A strategy's operations, listed and opened one by one (decision 43)", unit 9p.5 (columns, the dry-run mark and sentences, the detail dialog and its fills table, the owner's review by eye). Nothing is ticked here until that section's tasks are.
- [x] 9p.6 (owner review by eye, 2026-10-03) The enable history moves into the settings `<aside>`, directly under the enable switch and before the archive control (archive, the terminal action, stays last); it leaves the left column and keeps `max-h-18`, its scroll and its keyboard focus. RED `StrategyDetailPage.test.tsx::test_enable_history_sits_in_the_settings_column_between_the_enable_switch_and_archive`; the old order test is renamed `test_left_column_runs_performance_by_pair_and_trades_and_holds_no_webhook_block_until_it_is_opened` (see 9p.9). Done 2026-10-03, commit c20d6ae. RED on a lookup (`Unable to find role="heading" and name "Enable history"` inside the settings column). Mutation: history after archive, red.
- [x] 9p.7 (owner review by eye, 2026-10-03) Two scrollbars: `main` is now `relative`, so it is the containing block of the `sr-only` spans of the two tables (the only `sr-only` in the app; the only other `fixed` elements are the dialogs, which are viewport-relative and unaffected). RED `AppShell.test.tsx::makes the scroll container the containing block of absolutely positioned content, so an sr-only span cannot stretch the document`. Done 2026-10-03, commit f1710c7. RED on `expect(element).toHaveClass("relative overflow-auto")`. THE CAUSE WAS NOT CONFIRMED in a browser (jsdom has no layout): it is reasoned from the CSS (an absolute element inside a non-positioned scroll container is laid out against the initial containing block), and the fix is pinned by a class test.
- [x] 9p.8 (owner review by eye, 2026-10-03; decision 44) Closed trades are real paging, 20 rows at a time: one page on screen, never an accumulating list, "Previous" and "Next" and the page number (`TRADES_PAGE_SIZE` 20, no page count because the server serves none). "Next" asks the server with the exact `next_cursor` only when that page is not loaded yet; "Previous" and a "Next" over loaded pages send nothing. Next is disabled where the cursor is null, Previous on page 1; a failed next page keeps the current page and says so; keyset only, never an offset. RED `TradesTable.test.tsx::test_keyset_paging_shows_one_page_at_a_time_and_next_asks_the_server_with_the_cursor` (renamed from `test_infinite_query_keyset_cursor_loads_more_on_scroll_or_click`), `::test_previous_uses_the_pages_already_loaded_and_sends_nothing`, `::disables Previous on the first page and Next on the last, where the cursor is null`, `::asks the server for 20 rows a page`, `::starts again at page 1 when the page is shown for another strategy`; three more were renamed, none deleted (see the report). Done 2026-10-03, commit 652d85f. RED: 3 on value assertions (`expected '50' to be '20'`), 8 on lookups (`Unable to find an accessible element with the role "button" and name "strategies.performance.trades.next"`). Eight mutations red, all restored.
- [x] 9p.9 (owner review by eye, 2026-10-03) "Connect a TradingView alert" is a disclosure opened from a button in `StrategyHeader`, closed by default, `aria-expanded` and `aria-controls`, expanding as a panel under the header in the page flow (not a popover). Closed, the block is unmounted, so the existing cleanup evicts a revealed secret; reopening shows the placeholder and sends no request. Supersedes 12f.8's placement. RED `StrategyHeader.test.tsx::test_the_webhook_block_is_closed_by_default_and_opened_by_a_button_in_the_header`, `::test_collapsing_after_a_reveal_leaves_nothing_in_the_cache_and_reopening_shows_the_placeholder_without_a_request`, `::opens in the page flow under the header's title, not as a floating popover`. Done 2026-10-03, commit eff7c98. RED 6 of 6 on lookups (`Unable to find an accessible element with the role "button" and name "Connect a TradingView alert"`). Six mutations red (always mounted, hidden by CSS instead of unmounted, floating, no aria-expanded, no aria-controls, open by default). `WebhookMessage.test.tsx::test_no_other_control_ever_requests_the_secret` now opens the disclosure first and no longer counts the toggle among the "other" controls: before that edit it passed by accident, because clicking every other button opened the block.
- [x] 9p.10 (owner review by eye, 2026-10-03) `PairSelector` (and so `NewStrategyDialog`) lists nothing until the operator types: an empty field says how many pairs can be searched, from the first character the matches show (cap 50, "Showing 50 of N"), the field has a placeholder, and the chips, the loading line and the error with Retry show whatever the field holds. RED `PairSelector.test.tsx::test_an_empty_search_field_renders_no_option_list_and_says_how_many_pairs_can_be_searched`, `::test_the_matches_show_from_the_first_character_and_hide_again_when_the_field_is_cleared`, `::test_selected_pairs_are_always_visible_whatever_the_search_field_holds`, `::gives the search field a placeholder`. Done 2026-10-03, commit ba5dbbc. RED on value assertions (`expected [ <input …(2)></input>, …(2) ] to have a length of +0 but got 3`) and one lookup. Existing tests updated to type first (listed in the report). Seven mutations red.
- [x] 9p.11 (owner review by eye, 2026-10-03) A "Try again" button when the strategy's performance fails to load, as the trades table has. RED `StrategyPerformance.test.tsx::offers Try again when the report fails, and shows the report once the second read succeeds`, `::keeps Try again visible and the error shown when the second read fails too`. Done 2026-10-03, commit 56ba102. RED 2 of 2 on lookups (`Unable to find an accessible element with the role "button" and name "strategies.performance.retry"`).
- [x] 9p.12 (owner review by eye, 2026-10-03; decision 44) In Spanish the side reads "LONG" and "SHORT", not "Largo" and "Corto". RED `TradesTable.test.tsx::is titled and labelled in Spanish` (its expectation changed from `Corto` to `SHORT`). Done 2026-10-03, commit 0e70ebc. RED on `expect(element).toHaveTextContent()`.

Gate: `cd frontend && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: two presentational tables; revert removes them, detail page renders without them.
Forecast: 200–250 lines. Actual: 2,326 changed lines in twelve code commits (24dd6c4 260, d06340d 250, 25d7cb6 610, c1df70a 385, 8b6e19e 123 for 9p.1 to 9p.3 and 12f.8; then, for the owner's review by eye, 0e70ebc 4, 56ba102 47, f1710c7 16, c20d6ae 28, 652d85f 246, eff7c98 199, ba5dbbc 158 for 9p.6 to 9p.12), of which about 800 are production code and locale keys and the rest tests. Over the forecast about six-fold: the forecast counted two tables and a wrapper, not the API read and its validation, the keyset test double, one test per way a figure could be read wrongly, or the changes that make the Overview instruments reusable.

### Unit 9v — allowed pairs validated against the catalogue (decisions 40 and 41, not started)

Designed 2026-10-02: design.md, "Addendum: allowed pairs validated against the venue
catalogue". The two placeholder tasks (9v.1 backend, 9v.2 frontend) are replaced by the six
units of **PR 12v** below. Unit 9d gains task 9d.5.

---

## PR 12v — Allowed pairs validated against the venue catalogue (decisions 40, 41) (2,600–3,800 lines)

Six sequential PRs to `main`, never stacked: **12v-0** (9v0) → owner runs P7 → **12v-1** (9va)
→ **12v-2** (9vb) → **12v-3** (9vc) → **12v-4** (9vd) → **12v-5** (9ve). Each merges and deploys
before the next branch is cut. No migration in any of them.

Rules that bind every unit here, on top of the cross-cutting rules:

- **RED fails on an ASSERTION.** A new constructor argument, class or module is first added as
  a stub that compiles and answers WRONGLY (an empty set, an accept-everything catalogue, a
  transport that returns the raw body), in the same commit as the RED test. The first failure is
  never an `ImportError` or a `TypeError`. Each task records the assertion it failed on. A test
  that passes at once is proven by the mutation its task names.
- **Symbol spelling across a boundary.** Venue fixtures list `STXUSDT`. A register request sends
  `STXUSDT.P`; a replace request sends `STXUSDT_PERP`; the stored and returned form is `STXUSDT`.
  The frontend types `stxusdt.p` and submits `STXUSDT`. Tests that stay inside the venue
  boundary (9va) use the venue spelling only, and say so.
- **No network, no credential.** Venue classes are driven by `httpx.MockTransport`; everything
  above them by a fake `PairCatalogPort`. No test in this PR reads the vault or builds a signer.
- **What fails here without a log line?** is answered per unit in design addendum § I. Every
  refusal and every skipped entry in the tasks below has a test asserting its log line.

### Unit 9v0 — probe P7, public catalogues from the VPS (200–300 lines) — PR 12v-0

**Files**: Create `backend/scripts/check_public_catalogue.py`; Create
`backend/tests/scripts/test_check_public_catalogue.py`.

- [x] 9v0.1 RED `backend/tests/scripts/test_check_public_catalogue.py::test_no_request_carries_an_auth_header_or_a_signature_parameter` (a recording `httpx.MockTransport`: no `X-BAPI-*` header, no `X-MBX-APIKEY`, no `signature` or `timestamp` query parameter on any request), `::test_report_counts_entries_by_contract_type_status_and_settle_coin`, `::test_bybit_cursor_is_followed_and_every_entry_is_counted_once` (two pages; an absent `nextPageCursor` and an empty one both end the read), `::test_report_says_whether_each_known_pair_is_available` (`SFPUSDT`, `AAVEUSDT`, `STXUSDT`), `::test_http_451_is_reported_as_a_location_refusal_not_as_an_empty_catalogue`, `::test_script_imports_no_signer_vault_or_cipher` (module source). RED against a `run()` stub that returns an empty report and sends one request with a dummy header.
- [x] 9v0.2 GREEN: the script. A bare `httpx.AsyncClient` on `settings.bybit_base_url` and `settings.binance_futures_base_url`; `GET /v5/market/instruments-info?category=linear&limit=1000` (and again with `limit=200` to exercise the cursor); `GET /fapi/v1/exchangeInfo`. It prints P7.1–P7.6 of design addendum § J: status, entry counts by contract type, status and settle or margin coin, cursor presence and page count, pairs surviving the USDT filter, the three known pairs, response size, elapsed time and the rate-limit headers. It prints no other header and no environment value.
- [x] 9v0.3 Owner step: run it on the VPS as the `strategy` user and record the output in "PR 12v-0 — Probe P7 results" below. PR 12v-1 does not start before this. Run 2026-10-02.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/scripts/test_check_public_catalogue.py`.
Harness: `httpx.MockTransport` locally; the real run is the owner's, GET-only, with no credential loaded.
Rollback boundary: one dev script and its test; nothing imports it.
Forecast: 200–300 lines.

#### PR 12v-0 — Probe P7 results

The owner ran it on the VPS on 2026-10-02, at `main` `c95a625`, against `https://api.bybit.com` and
`https://fapi.binance.com`:

| Item | Bybit `linear` | Binance USDⓈ-M |
|---|---|---|
| P7.1 HTTP status with no signature and no key header | 200 | 200 |
| P7.2 entries listed; by contract type; by status; by settle or margin coin | 891; `LinearFutures`=40, `LinearPerpetual`=851; `Trading`=891; USDC=68, USDT=823 | 920; `CURRENT_QUARTER`=2, `NEXT_QUARTER`=2, `PERPETUAL`=703, `TRADIFI_PERPETUAL`=213; `PENDING_TRADING`=1, `SETTLING`=131, `TRADING`=788; BTC=1, U=2, USD1=3, USDC=39, USDT=875 |
| P7.3 `nextPageCursor` at `limit=1000` (present? empty on the last page?); pages at `limit=200`; every entry once? | no further page at `limit=1000` (1 page; the last page's cursor is the EMPTY string, not an absent field); 5 pages at `limit=200`; every entry exactly once: yes | n/a |
| P7.4 pairs available to a USDT pool | 783 | 528 |
| P7.5 `SFPUSDT` / `AAVEUSDT` / `STXUSDT` available | not available / available / available | available / available / available |
| P7.6 response bytes; elapsed; rate-limit headers | 835,613; 3.04 s; none | 1,142,974; 0.27 s; `x-mbx-used-weight-1m: 1` |

What the run settles:

- Both catalogues answer without a signature and without a key from the VPS. The credential-free
  transports of unit 9va are viable for both venues.
- The filter strings hold: Bybit `LinearPerpetual` / `Trading`, Binance `PERPETUAL` / `TRADING`.
  Binance also reports `SETTLING` (131) and `PENDING_TRADING` (1), which the filter excludes, and
  margin assets `U` and `USD1`, which no pool settles in.
- Bybit ends its last page with an EMPTY `nextPageCursor`, so the cursor loop stops on an empty
  string as well as on an absent field (9va).
- Bybit lists **891** `linear` entries against the single page of 1,000 the ORDER path reads
  (follow-up 9vf.1). The margin is 109 entries, not the roughly 160 assumed from the 2026-08-26
  count of about 840.
- `SFPUSDT` is not listed on Bybit. That is informational: the SFP strategy runs on
  `binance/usdt-m/USDT`, where it is listed.
- Bybit's read took 3.04 s for 836 kB. A cold cache makes the first save or the first selector
  load on a Bybit pool wait about that long.

### Unit 9va — credential-free transports and public catalogue sources (500–700 lines) — PR 12v-1

**Needs**: P7 recorded.

**Files**: Modify `backend/src/strategy_manager/shared/infrastructure/bybit/{transport,read_client}.py`,
`backend/src/strategy_manager/shared/infrastructure/binance/{transport,read_client}.py`; Create
`backend/src/strategy_manager/shared/infrastructure/bybit/public_catalogue.py`,
`backend/src/strategy_manager/shared/infrastructure/binance/public_catalogue.py`; Create
`backend/tests/shared/infrastructure/bybit/{test_public_transport,test_public_catalogue}.py`,
`backend/tests/shared/infrastructure/binance/{test_public_transport,test_public_catalogue}.py`;
Modify `backend/tests/shared/infrastructure/bybit/test_read_client.py`,
`backend/tests/shared/infrastructure/binance/test_futures_rules.py` (new tests only).

- [x] 9va.1 RED `backend/tests/shared/infrastructure/bybit/test_public_transport.py::test_public_get_refuses_a_nonzero_retcode_over_http_200`, `::test_public_get_returns_the_result_object_not_the_envelope`, `::test_public_get_sends_no_bapi_header`, `::test_public_transport_constructor_takes_no_signer` (`inspect.signature`); `backend/tests/shared/infrastructure/binance/test_public_transport.py::test_public_get_refuses_a_negative_code_and_http_451_like_the_signed_transport`, `::test_public_get_sends_no_api_key_header_and_no_signature_parameter`, `::test_binance_transport_get_public_answers_through_the_public_transport`. RED against stubs that return the raw body. The two "sends no header" tests pass against any stub; mutation: adding an `X-BAPI-API-KEY` / `X-MBX-APIKEY` header reds them.
- [x] 9va.2 GREEN: `BybitPublicTransport(http)` and `BinancePublicTransport(http)`. Each transport file's `_send` body becomes ONE module-level function that the signed and the public class both call; `BinanceTransport.get_public` delegates. **Acceptance:** every existing test under `tests/shared/infrastructure/bybit` and `.../binance` passes UNMODIFIED. These two extractions are the only edits to code the worker runs.
- [x] 9va.3 RED `backend/tests/shared/infrastructure/bybit/test_read_client.py::test_settles_in_compares_the_settle_coin_case_insensitively`; `backend/tests/shared/infrastructure/binance/test_futures_rules.py::test_settles_in_compares_the_margin_asset_not_the_quote_asset` (a contract quoted in USDT and margined in USDC is not USDT-settled). GREEN in the same task: `PerpContract.settles_in(currency)` on both read models; Bybit's `_parse_contract` becomes public `parse_contract` (the private name stays as an alias so no caller changes); `is_usdt_settled` becomes `settles_in("USDT")`.
- [x] 9va.4 RED `backend/tests/shared/infrastructure/bybit/test_public_catalogue.py` (venue spelling only; reuses `BTC_PERP`, `BTC_DATED` from `test_read_client.py`): `::test_tradable_perpetuals_keeps_trading_perpetuals_settled_in_the_asked_currency_only` (a perpetual, a dated future, a USDC-settled perpetual, a perpetual that is not trading), `::test_a_dated_future_is_excluded_by_its_contract_type_not_by_its_symbol` (a `LinearFutures` entry with a plain symbol is excluded; the filter never inspects the symbol text), `::test_the_cursor_is_followed_until_empty_and_every_page_is_read`, `::test_an_absent_cursor_key_ends_the_read_like_an_empty_one`, `::test_the_page_cap_raises_instead_of_returning_a_partial_list`, `::test_one_malformed_entry_is_skipped_and_named_in_exactly_one_warning`, `::test_a_nonempty_listing_with_no_available_pair_raises_and_logs_one_error_naming_the_types_seen`, `::test_a_real_read_logs_one_info_with_counts_and_pages`, `::test_every_request_goes_to_the_instruments_path_with_category_linear_and_no_auth`. RED against a stub that returns the first page's symbols unfiltered.
- [x] 9va.5 RED `backend/tests/shared/infrastructure/binance/test_public_catalogue.py` (reuses `AAVE`, `TRADIFI`, `QUARTERLY` from `test_futures_rules.py`): `::test_tradable_perpetuals_excludes_tradifi_quarterly_and_usdc_margined`, `::test_a_perpetual_that_is_not_trading_is_excluded`, `::test_one_malformed_entry_is_skipped_and_named_in_exactly_one_warning`, `::test_a_nonempty_listing_with_no_available_pair_raises_and_logs_one_error`, `::test_http_451_raises_and_is_never_an_empty_listing`, `::test_a_real_read_logs_one_info_with_counts`. RED against a stub that returns every symbol.
- [x] 9va.6 GREEN: `BybitPublicCatalogue.tradable_perpetuals(settlement_currency)` (cursor loop, page cap 10, per-entry guard around `parse_contract`, the filter `is_perpetual and is_trading and settles_in(currency)`) and `BinancePublicCatalogue.tradable_perpetuals(settlement_currency)` (same guard and filter over `parse_contract`). The filter's literal strings are the ones P7.2 recorded; if P7 contradicts `LinearPerpetual` / `Trading` / `PERPETUAL` / `TRADING`, stop and record it before writing the filter. Both raise their venue's own `*ApiError`; neither imports anything from `strategies`.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: `httpx.MockTransport`.
Rollback boundary: four new classes nothing calls, `settles_in`, and two behaviour-preserving extractions; revert removes them and the worker's venue code is byte-for-byte what it was.
Forecast: 500–700 lines.

### Unit 9vb — `PairCatalogPort`, `VenuePairCatalog`, the read endpoint (550–800 lines) — PR 12v-2

**Files**: Create `backend/src/strategy_manager/strategies/domain/pair_catalog.py`,
`backend/src/strategy_manager/strategies/application/read_available_pairs.py`,
`backend/src/strategy_manager/strategies/infrastructure/{pair_catalog,pair_catalog_router}.py`;
Modify `backend/src/strategy_manager/strategies/application/ports.py`,
`backend/src/strategy_manager/strategies/infrastructure/pool_catalog.py`,
`backend/src/strategy_manager/shared/config.py`, `backend/src/strategy_manager/main.py`; Create
`backend/tests/strategies/domain/test_pair_catalog.py`,
`backend/tests/strategies/application/test_read_available_pairs.py`,
`backend/tests/strategies/infrastructure/{test_venue_pair_catalog,test_pair_catalog_router}.py`,
`backend/tests/strategies/test_pair_catalog_has_no_credential.py`.

- [x] 9vb.1 RED `backend/tests/strategies/domain/test_pair_catalog.py::test_unknown_pairs_is_the_sorted_difference_of_candidates_and_available`, `::test_unknown_pairs_error_carries_the_symbols_as_a_sorted_tuple`, `::test_the_four_errors_are_distinct_domain_errors`, `::test_domain_module_imports_no_framework`. GREEN in the same task: `UnknownPairs`, `PairCatalogUnavailable`, `PairCatalogNotServed`, `PairsChangedConcurrently`, `unknown_pairs()`.
- [x] 9vb.2 RED `backend/tests/strategies/infrastructure/test_venue_pair_catalog.py::test_venue_symbols_are_returned_in_market_key_form` (the fake source lists `STXUSDT_PERP`; the result equals `{market_key("STXUSDT.P")}`), `::test_a_pool_with_no_source_raises_not_served_and_never_an_empty_set` (`pionex/spot/USDT`), `::test_a_venue_error_becomes_pair_catalog_unavailable_with_one_warning_and_no_url`, `::test_a_second_call_within_the_ttl_makes_no_venue_read`, `::test_an_expired_entry_is_refetched`, `::test_an_expired_entry_is_never_served_when_the_refresh_fails`, `::test_a_failure_is_not_cached`, `::test_concurrent_misses_make_one_venue_read` (the source parks on an `asyncio.Event`; two tasks; the read count is 1 and both get the same set), `::test_each_pool_key_has_its_own_entry_and_its_own_settlement_currency_reaches_the_source`. Time is an injected monotonic callable. RED against a stub that asks the source on every call and returns its symbols unmapped.
- [x] 9vb.3 GREEN: `PairCatalogPort` in `ports.py`; `VenuePairCatalog` (registry keyed `(exchange, venue)` with `bybit/usdt-m` and `binance/usdt-m`, per-key `asyncio.Lock`, TTL from `Settings.pair_catalogue_ttl_seconds = 300.0`, `for_settings`).
- [x] 9vb.4 RED `backend/tests/strategies/application/test_read_available_pairs.py::test_an_unknown_pool_raises_before_the_catalogue_is_asked`, `::test_a_disabled_pool_is_answered`, `::test_pairs_are_returned_sorted`. GREEN in the same task: `PoolCatalogPort.exists(pool)`, `SqlAlchemyPoolCatalog.exists`, `ReadAvailablePairs`.
- [x] 9vb.5 RED `backend/tests/strategies/infrastructure/test_pair_catalog_router.py` (real PostgreSQL through the module's conftest; `dependency_overrides[get_pair_catalog]`): `::test_available_pairs_200_sorted_with_pool_and_count`, `::test_unknown_pool_404_and_the_catalogue_is_never_asked` (`bybit/usdt-m/BTC`), `::test_disabled_pool_200`, `::test_unserved_pool_404_pair_catalogue_not_served_not_an_empty_list` (`pionex/spot/USDT`), `::test_venue_unreachable_502_pair_catalogue_unavailable`, `::test_no_token_is_401_before_the_catalogue_is_asked`, `::test_one_pools_request_never_returns_another_pools_pairs`, `::test_the_real_catalogue_requests_only_the_configured_host_and_the_fixed_path` (the real `VenuePairCatalog` over `httpx.MockTransport`: the path values never reach the URL), `::test_n_concurrent_requests_make_one_venue_read`. RED against a route that returns an empty `pairs` for every pool.
- [x] 9vb.6 RED `backend/tests/strategies/test_pair_catalog_has_no_credential.py::test_public_catalogue_modules_import_no_signer_vault_or_cipher` (source of `bybit/public_catalogue.py`, `binance/public_catalogue.py`, `strategies/infrastructure/pair_catalog.py`, `pair_catalog_router.py`). It passes at once by construction; mutation: importing `BybitSigner` into `pair_catalog.py` reds it.
- [x] 9vb.7 GREEN: `pair_catalog_router` (prefix `/pools`, `dependencies=[Depends(require_admin_token)]`), `get_pair_catalog` reading `app.state.pair_catalog`, `get_read_available_pairs`; `create_app()` builds one `VenuePairCatalog.for_settings(settings)` and includes the router in `api_router`. Confirm the existing `/api` auth walk and `test_no_pool_management_surface.py` pass unmodified.
  - The secret sweep (`tests/signals/infrastructure/test_webhook_secret_router.py`) walks every `/api` GET route and demands a 200, so it was taught the new route: a `settlement_currency` entry in `_SAMPLE_PATH_PARAMS` and a fake `get_pair_catalog` override (no network from the suite). No assertion was relaxed. The auth walk and `test_no_pool_management_surface.py` pass unmodified.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: fakes and `httpx.MockTransport`; real PostgreSQL for the router (pool existence).
Rollback boundary: one GET route, one adapter, one setting; revert 404s the path. No save reads the catalogue yet.
Forecast: 550–800 lines.

### Unit 9vc — unlisted-pair refusals, venue call before the row lock (500–750 lines) — PR 12v-3

**Needs**: PR 12v-2. The `PairCatalogNotServed` assertions (in 9vc.2 and 9vc.7) need the owner's
answer to design addendum § L, Q1.

**Files**: Modify `backend/src/strategy_manager/strategies/application/{register_strategy,replace_allowed_pairs}.py`,
`backend/src/strategy_manager/strategies/infrastructure/router.py`; Modify
`backend/tests/strategies/application/{test_register_strategy,test_replace_allowed_pairs}.py`,
`backend/tests/strategies/infrastructure/{test_router,test_update_strategy_concurrency}.py`; Create
`backend/tests/strategies/infrastructure/test_replace_allowed_pairs_catalogue_integration.py`.

- [x] 9vc.1 Plumbing, no behaviour change: `RegisterStrategy` and `ReplaceAllowedPairs` take `pairs: PairCatalogPort` and do not call it yet; the two routes take their use case from `get_register_strategy` / `get_replace_allowed_pairs` (the `get_save_credential` pattern) instead of building it inline; `_build` in both application test files and the router tests pass an accept-everything fake. The whole existing suite stays green. This is the stub that lets every RED below fail on an assertion.
- [x] 9vc.2 RED `backend/tests/strategies/application/test_register_strategy.py::test_an_unlisted_symbol_refuses_the_registration_names_it_and_writes_nothing` (`YPF` beside a listed pair; no insert, no commit), `::test_a_listed_symbol_in_another_spelling_is_accepted` (the catalogue holds `STXUSDT`, the command sends `STXUSDT.P`, the stored list is `{STXUSDT}`), `::test_every_unknown_symbol_is_named_sorted`, `::test_the_catalogue_is_not_asked_for_a_duplicate_id_an_unavailable_pool_or_an_empty_list`, `::test_an_unreadable_catalogue_refuses_and_writes_nothing`, `::test_a_pool_with_no_catalogue_source_refuses_and_writes_nothing`, `::test_each_refusal_logs_one_warning_naming_the_strategy_the_pool_and_the_symbols`, `::test_the_catalogue_is_asked_for_the_commands_own_pool` (the fake records the pool key: exchange, venue AND settlement currency). RED: `DID NOT RAISE UnknownPairs` and the recorded-calls assertions.
- [x] 9vc.3 GREEN `RegisterStrategy`: steps 4 and 5 of design addendum § E.
  - 9vc.1 touched two files the unit did not list, each only to pass the new constructor argument: `tests/strategies/application/test_archive_strategy_integration.py` (one `ReplaceAllowedPairs(...)` call) and the secret sweep `tests/signals/infrastructure/test_webhook_secret_router.py` (its fake catalogue now also lists `ETHUSDT` and `SOLUSDT`, the symbols the sweep's own POST and PUT bodies send, so both still answer 201 and 200). No assertion changed.
  - 9vc.2 observed RED on assertions: `DID NOT RAISE UnknownPairs` (2), `DID NOT RAISE PairCatalogUnavailable`, `DID NOT RAISE PairCatalogNotServed`, `DID NOT RAISE DomainError` (3, the parametrized log test) and `assert [] == [('bybit', 'usdt-m', 'USDT')]`. Two passed at once and were proven by mutation: the spelling test reds when the comparison uses the raw command pairs instead of the normalized ones; the "not asked for a duplicate, unavailable pool or empty list" test reds when a catalogue call is added at the top of `register`.
- [x] 9vc.4 RED `backend/tests/strategies/application/test_replace_allowed_pairs.py::test_adding_an_unlisted_symbol_refuses_and_leaves_the_stored_list`, `::test_adding_a_listed_symbol_in_another_spelling_is_accepted` (`STXUSDT_PERP` → `STXUSDT`), `::test_a_stored_delisted_pair_can_be_kept_while_another_pair_is_added`, `::test_a_stored_delisted_pair_can_be_removed`, `::test_a_replacement_that_adds_nothing_never_asks_the_catalogue` (and succeeds with a fake that raises `PairCatalogUnavailable`), `::test_a_removed_delisted_pair_cannot_be_added_back`, `::test_an_unreadable_catalogue_refuses_when_a_pair_is_added`, `::test_unknown_strategy_and_archived_are_refused_before_the_catalogue_is_asked`, `::test_the_catalogue_is_asked_before_the_row_lock_is_taken` (one shared event log: `get_by_id`, `catalogue`, `get_by_id_for_update`, `update`, `commit`), `::test_a_strategy_archived_between_the_unlocked_read_and_the_lock_is_still_refused`, `::test_a_stored_list_that_changed_so_an_unvalidated_pair_becomes_an_addition_is_refused_and_nothing_is_written`, `::test_a_candidate_that_is_no_longer_an_addition_is_harmless`, `::test_each_refusal_logs_one_warning`. RED: `DID NOT RAISE`, and `['get_by_id_for_update', ...] == ['get_by_id', 'catalogue', 'get_by_id_for_update', ...]`.
- [x] 9vc.5 GREEN `ReplaceAllowedPairs`: the sequence of design addendum § E (unlocked read, candidates, catalogue only when candidates exist, row lock, re-check, `PairsChangedConcurrently`).
  - 9vc.4 observed RED on assertions (10 failures): `DID NOT RAISE UnknownPairs` (2), `DID NOT RAISE PairCatalogUnavailable`, `DID NOT RAISE PairsChangedConcurrently`, `DID NOT RAISE DomainError` (4, the parametrized log test), `assert [] == [('pionex', 'spot', 'USDT')]` (archived between reads) and `['get_by_id_for_update', ...] == ['get_by_id', 'catalogue', 'get_by_id_for_update', ...]`. Seven passed at once and were proven by mutation: validating every requested pair instead of only the additions reds the kept-delisted, removed-delisted and adds-nothing tests; a strict `added == candidates` re-check reds the harmless-drift test; skipping the archived check on the unlocked read reds the before-the-catalogue test; asking the catalogue before normalizing reds the empty-list test; comparing raw instead of normalized spellings reds the spelling test.
  - Two tests beyond the listed ones: `::test_an_empty_list_is_refused_before_the_catalogue_is_asked` (design § E order), and the `not-served` case of the parametrized log test.
- [x] 9vc.6 RED `backend/tests/strategies/infrastructure/test_replace_allowed_pairs_catalogue_integration.py` — **live PostgreSQL**, lock-hold harness, no `sleep(0)` barrier, the real repository and a fake catalogue that parks on an `asyncio.Event`:
  - `::test_the_strategy_row_is_lockable_by_another_transaction_while_the_catalogue_read_is_in_flight` — while the replace is parked inside `available_pairs`, a second connection runs `SELECT ... FOR UPDATE NOWAIT` on the row and succeeds. Mutation: moving the catalogue call after `get_by_id_for_update` makes it raise `LockNotAvailableError`.
  - `::test_replace_waits_for_a_held_row_lock_after_its_catalogue_read` — a holder keeps the row locked in an open transaction; the replace is released past its catalogue call; assert `not task.done()` AND poll `pg_locks` until the replace shows as waiting on that row; the holder commits a changed `enabled`; the replace completes and its write does not revert `enabled`.
  - `::test_a_concurrent_removal_of_a_requested_pair_refuses_with_pairs_changed` — stored `{ETHUSDT, SFPUSDT}`, request `{ETHUSDT, SFPUSDT, STXUSDT_PERP}`; while parked, another transaction stores `{ETHUSDT}` and commits; the replace raises `PairsChangedConcurrently` and the row is `{ETHUSDT}`.
  - `tests/strategies/infrastructure/test_update_strategy_concurrency.py::test_replace_allowed_pairs_and_update_strategy_serialize_on_the_same_row_lock` keeps passing with only its constructor call updated.
  - Observed (the use case already implemented, so these prove non-vacuity by mutation): moving the catalogue call after `get_by_id_for_update` makes all three red without hanging (`LockNotAvailableError` on the `NOWAIT`, "the replace never reached the catalogue call", and a `lock_timeout` on the competing write); replacing the locked read with a plain `get_by_id` reds the waiting test ("the replace never showed as waiting on the strategy row in pg_locks"); removing the re-check reds the `PAIRS_CHANGED` test (`DID NOT RAISE PairsChangedConcurrently`).
  - **A gap the unit did not name, found while writing these.** The use case now reads the strategy twice in one session (unlocked, then `FOR UPDATE`). A plain `SELECT ... FOR UPDATE` returns an ORM row the session still references with its OLD values, so the re-check would check nothing. Only garbage collection of the first read hid it. Added `::test_the_row_lock_read_refreshes_a_row_the_session_already_holds` (RED: `assert ['ETHUSDT'] == ['SOLUSDT']`) and fixed `SqlAlchemyStrategyRepository.get_by_id_for_update` with `populate_existing=True` (one file the unit did not list: `strategies/infrastructure/repository.py`). Every other caller reads the row first, so nothing else changes.
- [x] 9vc.7 RED `backend/tests/strategies/infrastructure/test_router.py::test_post_unknown_pairs_422_structured_and_names_the_symbols` (`detail == {"error": "UNKNOWN_PAIRS", "message": ..., "unknown": ["YPF"]}`, no row), `::test_put_unknown_pairs_422_names_only_the_added_symbols`, `::test_put_keeping_a_delisted_stored_pair_200`, `::test_post_unreadable_catalogue_502_pair_catalogue_unavailable_and_no_row`, `::test_post_unserved_pool_422_pair_catalogue_not_served`, `::test_put_pairs_changed_409`, `::test_existing_refusals_keep_their_status_and_shape` (404, 409 `STRATEGY_ARCHIVED`, 409 duplicate, 422 empty list, 422 unavailable pool), `::test_a_listed_pair_sent_as_tradingview_spells_it_is_stored_as_the_market_key` (`STXUSDT.P` in, `STXUSDT` out). RED: `assert 201 == 422`, `assert 200 == 502`.
- [x] 9vc.8 GREEN: the HTTP mapping of design addendum § E in `router.py`; the two dependency factories read `get_pair_catalog`.
  - 9vc.7 observed RED on assertions (7): `assert 500 == 422` (POST and PUT unknown pairs, POST and PUT not served), `assert 500 == 502` (POST and PUT unavailable), `assert 500 == 409` (`PAIRS_CHANGED`). The new tests use a client with `raise_app_exceptions=False`, so an unmapped domain error is a 500 the test asserts on instead of a raised exception. Three passed at once and were proven by mutation: validating every pair (not only additions) reds the keep-a-delisted-pair 200; changing the duplicate-registration 409 to 400 reds the existing-refusals test; comparing raw spellings reds the TradingView-spelling test.
  - Two cases beyond the listed ones: `::test_put_unreadable_or_unserved_catalogue_refuses_and_keeps_the_stored_list` (PUT 502 and PUT 422 `PAIR_CATALOGUE_NOT_SERVED`, so every new refusal is covered on both routes).

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: real PostgreSQL, lock-hold harness on the strategy ROW lock (`rules.tasks`: no fake for a lock). Neither use case takes the pool advisory lock, so the lock-order rule is untouched; the test proves no venue call runs under the one lock there is.
Rollback boundary: two use cases, their router mapping and two dependency factories; revert restores normalize-only saves. Pairs stored while the refusals were live stay valid.
Forecast: 500–750 lines.

### Unit 9vd — `ApiError` structured detail, `useAvailablePairs`, `PairSelector` (450–650 lines) — PR 12v-4

**Files**: Modify `frontend/src/shared/api/{client.ts,client.test.ts,types.ts}`; Create
`frontend/src/shared/api/{pairs.ts,pairs.test.ts}`,
`frontend/src/features/strategies/{PairSelector.tsx,PairSelector.test.tsx}`; Modify
`frontend/src/shared/i18n/locales/{en,es}.json`.

- [x] 9vd.1 RED `frontend/src/shared/api/client.test.ts::reads the error code and the fields from a structured detail`, `::uses the structured detail's message and never renders [object Object]`, `::keeps a string detail and an outcome exactly as before`. GREEN in the same task: `ApiError.code` and `ApiError.fields`.
  - Observed RED on assertions (6, against a stub that declared `code` and `fields` as `undefined`): `expected undefined to be 'UNKNOWN_PAIRS'`, `expected undefined to be 'PAIR_CATALOGUE_UNAVAILABLE'`, `expected '[object Object]' to be 'The pairs changed while you were editing.'`, `expected '[object Object]' to be 'Request failed with status 502'` and `... 422`, and the "exactly as before" test on its `code` assertion. GREEN: 18 tests in the file, the 12 existing ones unmodified.
  - The "exactly as before" test is partly a regression pin, so it was proven by mutation: ignoring a string `detail` reds it and four existing tests.
  - Three tests beyond the listed ones: a second structured code, a structured detail with no `message` (falls back to the status text, `detail` stays `undefined`), and a list `detail` (FastAPI validation) or a non-string `error` (both read as no structured detail).
- [x] 9vd.2 RED `frontend/src/shared/api/pairs.test.ts::requests /api/pools/{exchange}/{venue}/{ccy}/available-pairs for the chosen pool`, `::rejects a body whose pairs is not an array of strings`, `::does not fetch until a pool is chosen`, `::uses a query key that is not under ['pools']`. GREEN in the same task: `fetchAvailablePairs`, `useAvailablePairs` (`['available-pairs', exchange, venue, ccy]`, `staleTime` 5 minutes, `retry: 1`).
  - Observed RED on assertions (14 of 17, against a stub that read `/pools/{exchange}` and keyed `['pools', exchange]`): `expected '/api/pools/binance' to be '/api/pools/binance/usdt-m/USDT/availa…'`, `expected { …(2) } to be an instance of ApiError` (the eight malformed bodies), `expected 'fetching' to be 'idle'`, `expected [ [ 'pools', 'bybit' ] ] to deeply equal [ Array(1) ]`, `expected undefined to be 300000`. GREEN: 17 tests.
  - Three passed at once and were proven by mutation: refusing an empty list reds the "empty list is a list" test; rethrowing a refusal without its code reds the code test and the hook's error test; swallowing a failed read into an empty list reds the hook's error test.
  - Beyond the listed ones: segment encoding, one cache entry per pool, `staleTime`/`retry`, the response's `pool` echo and `count` must match the request and the list (so another pool's answer or a truncated list is an error), and a refusal keeps its `code`.
- [x] 9vd.3 RED `frontend/src/features/strategies/PairSelector.test.tsx::idle shows choose-a-pool and a disabled search field`, `::loading shows a status line and no option`, `::error shows an alert and a retry control that calls onRetry`, `::typing another spelling finds the pair` (types `stxusdt.p`, the option is `STXUSDT`), `::toggling an option with the keyboard calls onChange with the pair`, `::every selected pair has a remove control labelled with its symbol`, `::more than fifty matches renders fifty and says how many match`, `::no match says so`, `::a selected pair missing from the options is kept and marked no longer listed`, `::selected pairs stay removable in the error state`, `::the search field, every option and every remove control have an accessible name`, `::every key exists in en and es`. RED against a component that renders an empty fieldset.
- [x] 9vd.4 GREEN: `PairSelector` per design addendum § G: a `<fieldset>`, a labelled `<input type="search">`, native checkboxes in labels, chips with remove buttons, a polite live count. No new dependency. Palette tokens only; the "no longer listed" mark is `ink-3`, never `decision`.
  - 9vd.3 observed RED on assertions and element lookups (23 of 23, against a component that rendered an empty `<fieldset />`): `Unable to find an accessible element with the role "status"` / `"alert"` / `"searchbox"` / `"group"`, `expected [] to deeply equal [ 'AAVEUSDT', 'SFPUSDT', 'STXUSDT' ]`, `expected [] to have a length of 50 but got +0`, and `en strategies.pairs.search: expected undefined to deeply equal StringMatching /\S/`. Tests read their texts through `i18n.t`, so a missing key fails on its text, never on a `TypeError`. GREEN: 23 tests; the full suite is 30 files, 434 tests.
  - Seven mutations of the finished component each red at least one test: no `preventDefault` on Enter, 51 rendered matches, no `.P`/`_PERP` stripping, marking a pair "no longer listed" while the options are unknown, an enabled search field outside `ready`, a toggle that replaces the selection, and a selection filtered to the options.
  - Beyond the listed tests: Enter in the search field never submits an enclosing form (the dialog's form, unit 9ve), `disabled` and `describedBy` pass through, exactly 50 matches carry no "narrow" hint, a delisted pair already removed is not offered again, and the Spanish texts render. The keyboard test focuses a native checkbox and clicks it, because jsdom does not turn Space into a click; no `user-event` dependency was added.
  - Added i18n keys (`strategies.pairs.*`, EN and ES): `search`, `choosePool`, `loading`, `loadFailed`, `retry`, `noMatch`, `showing`, `narrow` (not in the design's list: the "typing narrows the list" half of the live region), `remove`, `notListed`, `selected`.

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")`; the selector is tested as a controlled component with props.
Rollback boundary: three new files and two added `ApiError` fields; nothing mounts the selector.
Forecast: 450–650 lines.

### Unit 9ve — the selector in `NewStrategyDialog` (400–600 lines) — PR 12v-5

**Files**: Modify `frontend/src/features/strategies/{NewStrategyDialog.tsx,NewStrategyDialog.test.tsx,StrategiesPage.test.tsx}`,
`frontend/src/test/harness.tsx`, `frontend/src/shared/i18n/locales/{en,es}.json`.

- [x] 9ve.1 Harness correction, no behaviour change: the default pool is `pool("bybit", "usdt-m")` (the venue `linear` does not exist, `accounts/domain/known_pools.py`); `stubApi` answers `/pools/{exchange}/{venue}/{ccy}/available-pairs`; every test that spells `linear/USDT` moves to `usdt-m/USDT`. The suite stays green.
- [x] 9ve.2 RED `frontend/src/features/strategies/NewStrategyDialog.test.tsx::test_pairs_are_chosen_from_the_pools_available_pairs_and_no_free_text_field_exists`, `::test_selected_pairs_are_submitted_in_market_key_form` (types `stxusdt.p`, the POST body carries `["STXUSDT"]`), `::test_changing_the_pool_clears_the_selection_and_reads_the_new_pools_pairs`, `::test_submit_is_disabled_until_the_available_pairs_are_loaded`, `::test_a_load_failure_shows_retry_and_never_a_free_text_field`, `::test_unknown_pairs_refusal_names_the_symbols`, `::test_a_502_shows_the_pair_list_could_not_be_read_text_even_without_a_body`, `::test_pair_catalogue_not_served_shows_its_own_text`, `::test_new_texts_render_in_es`. The two existing tests, `::test_id_generated_via_crypto_randomuuid` and `::test_submitting_with_zero_pairs_is_prevented`, keep their names and are driven through the selector.
- [x] 9ve.3 GREEN: `NewStrategyDialog` mounts `PairSelector` over `useAvailablePairs(pool)`; `parsePairs`, the textarea and `strategies.new.pairsHint` are removed; `errorKey` reads `error.code` first and the status second (design addendum § G table).

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: one dialog and the harness default; revert restores the textarea, and the server (12v-3) still refuses an unlisted pair.
Forecast: 400–600 lines.

### Unit 9vf — follow-ups to unit 9v (not started)

- [x] 9vf.1 The ORDER path reads one page of Bybit's catalogue: `bybit/trade_client.py:130` calls `BybitReadOnlyClient.perp_contracts()` (`limit=1000`, no cursor). Past 1,000 `linear` entries, a market on the second page is refused at order time as not listed (P7.2 records today's count). Reuse 9va's cursor loop in the signed client. Its own small PR, because it touches the order path; priority is design addendum § L, Q3. RED first: a two-page listing whose second page holds the ordered symbol.
- [x] 9vf.2 `tasks.md` "Production now" still names the Bybit pool `bybit/linear/USDT`; the row is `bybit/usdt-m/USDT` (task 6d.1). Correct the label on the next delivery-log update. Done with the PR 12a-2 entry (2026-10-02).

### Unit 9x — delete a strategy that has no history (decision 42, designed, not implemented)

- [x] 9x.1 Design first: list every table that references a strategy (signals, reservations, execution attempts, ledger entries, enablement events and any other), define the no-history check and its lock, and revise the spec requirement "Archive Is Terminal — Never Deleted, Never Reversed". No code before this. Done 2026-10-02: design.md, "Addendum: deleting a strategy that has no history (decision 42)"; specs `strategy-lifecycle`, `admin-api` and `operator-panel` revised. Two more references than decision 42 lists were found (`booking_proposals`, `strategy_enablement_events`), and three owner questions are open (design addendum 9x § L).

The two placeholder tasks (9x.2 backend, 9x.3 frontend) are replaced by the units of **PR 12x**
below. Unit 9d gains task 9d.6.

---

## PR 12x — Delete a strategy that has no history (decision 42) (2,000–2,950 lines; 2,400–3,550 with 12x-6)

Five sequential PRs to `main`, never stacked: **12x-1** (9xa) → **12x-2** (9xb) → **12x-3** (9xc)
→ **12x-4** (9xd) → **12x-5** (9xe). Each merges and deploys before the next branch is cut.
**12x-6** (9xf) was conditional on the owner's answer to Q1, which is now "they do not count"
(decision 42), so it is built, after 12x-3. No migration in 12x-1 to 12x-5; migration 0028 in
12x-6 only.

**Owner questions of design addendum 9x § L: all three ANSWERED 2026-10-02** (owner-decisions.md,
decision 42). Nothing is blocked on an answer any more.

| Question | Answer | Effect on the tasks |
|---|---|---|
| **Q1** Do enablement events count as history? | **No: they are deleted with the strategy.** | Unit 9xf (PR 12x-6) is in scope. Until it is deployed, events still block a delete (fail closed): 9xa–9xe keep `enablement_events` as a blocking kind, which is the only behaviour possible without a migration. |
| **Q2** Booking proposals as a fifth blocking kind | **Yes: they block.** | None. The foreign key forces it; it is already one of the six counts. |
| **Q3** May an archived strategy with no history be deleted? | **Yes.** An archived strategy is still never re-enabled or un-archived. | Task **9xc.6** and the archived cases of **9xd.1** and **9xe.3** are unblocked and take the "is deleted" branch. |

Rules that bind every unit here, on top of the cross-cutting rules:

- **RED fails on an ASSERTION.** A new port, class, method or route is first added as a stub that
  compiles and answers WRONGLY (a history that is always empty, a delete with no check and no
  lock, a route that always answers 204), in the same commit as the RED test. The first failure
  is never an `ImportError` or a `TypeError`. Where the wrong behaviour is "another exception is
  raised", the test captures the exception and asserts on its type, so the failure is still an
  assertion. Each task records the assertion it failed on. A test that passes at once is proven
  by the mutation its task names.
- **The `head` schema is mandatory wherever a foreign key or a trigger decides the outcome.** The
  ORM-built test database has no foreign key on `signals.strategy_id`,
  `booking_proposals.strategy_id` or `strategy_enablement_events.strategy_id`, and no append-only
  trigger (design addendum 9x § A, X2). A test that relies on one and runs on the ORM schema
  proves nothing. Such files use `tests/pg_head_schema.py` (task 9xa.1) and say why in their
  docstring.
- **Concurrency is proven on real PostgreSQL with a lock-hold harness.** The second actor is
  shown to WAIT: `assert not task.done()` after the first actor is parked on an `asyncio.Event`,
  AND a poll of `pg_locks` until the second actor shows as waiting, so "still pending" is never
  mistaken for "not started". Never a `sleep(0)` barrier. Precedents:
  `tests/strategies/application/test_archive_vs_allocate_concurrency.py` and
  `tests/strategies/infrastructure/test_replace_allowed_pairs_catalogue_integration.py`.
- **Lock order.** Pool advisory lock first, then the strategy row lock. One test asserts the order
  with fakes (9xc.2) and one proves it on PostgreSQL (9xc.5).
- **Symbol spelling across a boundary.** The alert sends `STXUSDT.P`; a row seeded on the venue
  side (attempt, ledger entry) is `STXUSDT`; a strategy's allowed pair is `STXUSDT`. No test uses
  the same spelling on both sides of the webhook or of a module boundary.
- **What fails here without a log line?** is answered in design addendum 9x § I. Every refusal,
  the successful delete and the database backstop have a test asserting their one log line and
  its level. No line carries a token, a credential, a DSN, the webhook secret or a raw payload.

### Unit 9xa — the webhook refuses an alert whose strategy is not registered (300–450 lines) — PR 12x-1

**Files**: Modify `backend/src/strategy_manager/signals/application/{ports,ingest_signal}.py`,
`backend/src/strategy_manager/signals/infrastructure/{repository,router}.py`; Create
`backend/tests/pg_head_schema.py`, `backend/tests/test_pg_head_schema.py`,
`backend/tests/signals/infrastructure/{test_repository_constraint_name,test_unknown_strategy_ingress}.py`;
Modify `backend/tests/signals/application/test_ingest_signal.py` (new tests only).

- [x] 9xa.1 Test plumbing, no production change: `tests/pg_head_schema.py` gives a module-scoped database created empty and migrated with `alembic upgrade head` in a subprocess, dropped afterwards (the pattern of `tests/migrations/test_0024_strategy_lifecycle.py:140-153`, extracted, not copied a tenth time). `backend/tests/test_pg_head_schema.py::test_the_head_database_has_the_three_foreign_keys_the_orm_schema_lacks` (`fk_signals_strategy`, `fk_booking_proposals_strategy`, `fk_strategy_enablement_events_strategy` in `pg_constraint`). It passes at once; mutation: building the database with `Base.metadata.create_all` instead of alembic reds it.
- [x] 9xa.2 RED `backend/tests/signals/infrastructure/test_repository_constraint_name.py` (a scripted session, the `tests/accounts/infrastructure/test_credential_vault_constraint_name.py` pattern): `::test_a_violation_of_fk_signals_strategy_raises_unknown_signal_strategy_carrying_the_id`, `::test_any_other_integrity_error_is_reraised_unchanged`, `::test_the_constraint_is_matched_by_name_and_never_by_message_text` (a message that contains the constraint name, with another `constraint_name`, is NOT translated). RED against `UnknownSignalStrategy` declared and the repository unchanged: `assert IntegrityError is UnknownSignalStrategy`.
- [x] 9xa.3 RED `backend/tests/signals/application/test_ingest_signal.py::test_an_unregistered_strategy_logs_one_warning_naming_the_id_and_the_alerts_symbol_and_reraises` (symbol `STXUSDT.P`), `::test_nothing_is_enqueued_and_nothing_is_committed_for_an_unregistered_strategy`, `::test_the_warning_carries_no_raw_payload`. RED: `assert 0 == 1` on the WARNING count. The other two pass at once; mutations: enqueueing before the insert reds the first, logging `command.raw_payload` reds the second.
- [x] 9xa.4 RED `backend/tests/signals/infrastructure/test_unknown_strategy_ingress.py` — **`head` database**, the ASGI app with `raise_app_exceptions=False`: `::test_an_alert_for_an_unregistered_strategy_is_422_unknown_strategy_and_persists_nothing` (`detail.error == "UNKNOWN_STRATEGY"`; zero rows in `signals` and `jobs`), `::test_the_same_alert_replayed_is_refused_again_and_still_persists_nothing`, `::test_a_valid_alert_after_a_refused_one_is_accepted` (the session and the app are usable after the rollback), `::test_an_alert_for_a_registered_strategy_is_still_accepted_and_enqueues_one_job` (the strategy allows `STXUSDT`, the alert sends `STXUSDT.P`), `::test_the_refusal_logs_one_warning_and_no_error`. RED: `assert 500 == 422`. The registered-strategy test passes at once; mutation: a pre-insert strategy lookup that always misses reds it.
- [x] 9xa.5 GREEN: `UnknownSignalStrategy` in `signals/application/ports.py` (documented on `SignalRepositoryPort.insert_or_get`); the repository translates by constraint name; `IngestSignal` logs and re-raises; the route rolls back and answers 422 `{"error": "UNKNOWN_STRATEGY", "message"}` (design addendum 9x § E). No lookup and no lock is added to the ingress path.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: a scripted session and fakes for the unit tests; real PostgreSQL migrated to `head` for the route.
Rollback boundary: one caught error, one log line and one HTTP mapping on the webhook; revert restores today's unhandled 500. The success path's code is not edited.
Forecast: 300–450 lines.

### Unit 9xb — `StrategyHistoryPort` and the six counts (450–650 lines) — PR 12x-2

**Files**: Modify `backend/src/strategy_manager/strategies/application/ports.py`,
`backend/src/strategy_manager/signals/infrastructure/repository.py`,
`backend/src/strategy_manager/allocation/infrastructure/repository.py`,
`backend/src/strategy_manager/execution/infrastructure/repository.py`,
`backend/src/strategy_manager/ledger/infrastructure/repository.py`,
`backend/src/strategy_manager/reconciliation/infrastructure/booking_proposal_repository.py`,
`backend/src/strategy_manager/strategies/infrastructure/enablement_log.py`; Create
`backend/src/strategy_manager/strategies/infrastructure/history_adapter.py`; Create
`backend/tests/strategies/application/test_strategy_history.py`,
`backend/tests/strategies/infrastructure/{test_history_adapter_integration,test_strategy_references_guard}.py`;
Modify `backend/tests/strategies/infrastructure/conftest.py` (register `BookingProposalRow` on the metadata).

- [x] 9xb.1 RED `backend/tests/strategies/application/test_strategy_history.py::test_is_empty_only_when_all_six_counts_are_zero` (parametrized: each kind alone non-zero), `::test_blocking_names_only_the_nonzero_kinds_in_a_fixed_order`, `::test_the_ports_module_imports_no_type_of_another_module` (module source: no `signals`, `allocation`, `execution`, `ledger` or `reconciliation` import). GREEN in the same task: `StrategyHistory`, `StrategyHistoryPort`. RED against `is_empty()` returning `True`: `assert True is False`.
- [x] 9xb.2 RED `backend/tests/strategies/infrastructure/test_history_adapter_integration.py` (real PostgreSQL, the module's conftest; the strategy is on `bybit/usdt-m/USDT`): `::test_a_strategy_with_nothing_counts_zero_in_every_kind`, `::test_one_row_of_each_kind_is_counted_in_its_own_kind` (parametrized over the six), `::test_an_execution_attempt_is_counted_through_its_reservation_its_closed_allocation_and_its_signal` (one of each: the count is 3, and each alone is 1), `::test_terminal_rows_count_too` (a REJECTED signal, a RELEASED reservation, a FAILED attempt, a REJECTED proposal), `::test_another_strategys_rows_are_never_counted`, `::test_a_reservation_in_another_pool_is_counted` (against `pionex/spot/USDT`), `::test_a_signal_spelled_as_tradingview_spells_it_counts_for_a_strategy_allowing_the_market_key` (signal `STXUSDT.P`, attempt `STXUSDT`, allowed pair `STXUSDT`). RED against an adapter stub that answers six zeros: `assert 0 == 1`. The first and the "another strategy" tests pass at once; mutation: dropping the `strategy_id` filter from one count reds both.
- [x] 9xb.3 GREEN: `count_for_strategy` on the five provider repositories, `SqlAlchemyEnablementLog.count_for`, `StrategyHistoryAdapter` (design addendum 9x § B, § C). Counts filter by strategy id only, never by pool.
- [x] 9xb.4 RED `backend/tests/strategies/infrastructure/test_strategy_references_guard.py` — **`head` database**: `::test_every_foreign_key_into_strategies_is_one_the_history_check_counts` (the set read from `pg_constraint` equals the five names of design addendum 9x § A, each `NO ACTION`), `::test_every_strategy_id_column_belongs_to_a_counted_table` (`information_schema.columns`), `::test_execution_attempts_reach_a_strategy_only_through_reservations_and_signals`, `::test_the_guard_reports_a_reference_added_in_a_transaction` (creates `x(strategy_id uuid REFERENCES strategies(id))` inside a transaction, runs the same check function, asserts it names the new constraint, rolls back). The first three pass at once by construction; the fourth is their mutation, kept as a test. The failure message tells the author to extend `StrategyHistory`.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: real PostgreSQL. The ORM schema is enough for the counts (they are plain reads); the guard needs `head`.
Rollback boundary: six read methods, one dataclass, one port and one adapter that nothing calls. The worker imports the edited repository files, so both services restart, with no behaviour change.
Forecast: 450–650 lines.

### Unit 9xc — `DeleteStrategy`, the delete statement, the lock-hold tests (550–800 lines) — PR 12x-3

**Needs**: PR 12x-1 and PR 12x-2. Task 9xc.6 was waiting on Q3, answered "yes" (decision 42).

**Files**: Create `backend/src/strategy_manager/strategies/application/delete_strategy.py`; Modify
`backend/src/strategy_manager/strategies/application/{ports,archive_strategy}.py`,
`backend/src/strategy_manager/strategies/infrastructure/repository.py`; Create
`backend/tests/strategies/application/test_delete_strategy.py`,
`backend/tests/strategies/infrastructure/{test_delete_strategy_integration,test_delete_strategy_concurrency}.py`.

- [x] 9xc.1 Plumbing: `StrategyRepositoryPort.delete`, `StrategyStillReferenced`, and a `DeleteStrategy` whose `delete()` removes the row with no lock and no check. This is the stub every RED below fails against on an assertion. Done 2026-10-02, commit 445f84d (stubs first; RED on assertions, see apply-progress).
- [x] 9xc.2 RED `backend/tests/strategies/application/test_delete_strategy.py` (fakes; one shared event log): `::test_an_unknown_id_raises_unknown_strategy_before_any_lock`, `::test_the_pool_lock_is_taken_before_the_row_lock_and_history_is_read_after_both` (`['get_by_id', 'pool_lock', 'get_by_id_for_update', 'history', 'delete', 'commit']`), `::test_the_pool_locked_is_the_strategys_own_exchange_venue_and_settlement_currency`, `::test_a_row_gone_after_the_lock_raises_unknown_strategy`, `::test_an_enabled_strategy_is_refused_before_history_is_read`, `::test_enabled_is_decided_from_the_locked_read_not_the_unlocked_one`, `::test_each_kind_of_history_alone_refuses_and_nothing_is_deleted` (parametrized over the six), `::test_the_refusal_carries_all_six_counts`, `::test_no_history_deletes_and_commits_exactly_once`, `::test_a_database_refusal_becomes_has_history_and_logs_one_error_naming_the_constraint`, `::test_a_successful_delete_logs_one_info_with_id_name_and_pool`, `::test_each_refusal_logs_exactly_one_warning` (parametrized: unknown, enabled, history), `::test_no_refusal_writes_or_commits_anything`. RED: `DID NOT RAISE`, and the event-log comparison. Done 2026-10-02, commit 445f84d: 25 tests red on assertions against the stub (`DID NOT RAISE`, the event-log comparison).
- [x] 9xc.3 GREEN `DeleteStrategy` per design addendum 9x § D, steps 1–4 and 6–8; `SqlAlchemyStrategyRepository.delete` (one `DELETE`, flushed; a foreign-key `IntegrityError` becomes `StrategyStillReferenced(constraint_name)`, by name). Done 2026-10-02, commit 445f84d. `SqlAlchemyStrategyRepository.delete` translates by SQLSTATE `23503` and constraint name; three scripted tests added beside it (`test_repository_delete_translation.py`), mutation-proven.
- [x] 9xc.4 RED `backend/tests/strategies/infrastructure/test_delete_strategy_integration.py` — **`head` database**, the real repository, lock adapter and history adapter: `::test_a_never_enabled_strategy_is_deleted_and_no_table_carries_its_id` (the five tables of § A are scanned), `::test_a_strategy_with_a_ledger_entry_is_refused_and_the_entry_is_byte_for_byte_unchanged`, `::test_the_database_refuses_a_delete_the_count_wrongly_allowed` (a history fake that answers zeros over a strategy with one enablement event: `StrategyHasHistory`, one ERROR naming `fk_strategy_enablement_events_strategy`, the row and the event remain, and the session is usable after the rollback), `::test_a_deleted_id_registers_again_with_no_event_and_zero_uptime`. RED against the 9xc.1 stub for the ledger test (`DID NOT RAISE`); the backstop test is RED until `delete` translates the error (`assert IntegrityError is StrategyHasHistory`). Done 2026-10-02, commit dde0191. Observed RED against the stub: `assert isinstance(IntegrityError, StrategyHasHistory)` (the foreign key refused it, not `DID NOT RAISE`).
- [x] 9xc.5 RED `backend/tests/strategies/infrastructure/test_delete_strategy_concurrency.py` — **`head` database**, lock-hold harness, no `sleep(0)` barrier:
  - `::test_delete_waits_for_a_signal_being_ingested_then_is_refused_with_one_signal` — a real `IngestSignal` for `STXUSDT.P` is parked before its commit, after its `INSERT`. The delete is started: `not task.done()`, and `pg_locks` shows it waiting on the strategy row. The ingest commits; the delete raises `StrategyHasHistory` with `signals == 1`; the strategy and the signal exist. Non-vacuity, recorded and not committed: with `fk_signals_strategy` dropped in the test database the delete does not wait and the test is red.
  - `::test_a_signal_waits_for_a_delete_in_flight_then_is_refused_and_nothing_is_persisted` — the delete is parked before its commit, after its `DELETE`. The ingest is started: `not task.done()`. The delete commits; the ingest raises `UnknownSignalStrategy`; `signals` and `jobs` are empty.
  - `::test_delete_waits_on_the_pool_advisory_lock_and_holds_no_row_lock_meanwhile` — a holder takes the advisory lock of `(bybit, usdt-m, USDT)` through allocation's own `PgAdvisoryLockAdapter`. The delete is started: `not task.done()`, `pg_locks` shows it waiting on an `advisory` lock, and a third connection takes the strategy row with `SELECT ... FOR UPDATE NOWAIT` and succeeds. Mutation: taking the row lock before the pool lock makes `NOWAIT` raise `LockNotAvailableError`. A second mutation: a `PoolLockAdapter` deriving another key makes the delete not wait.
  - `::test_delete_waits_for_an_enable_in_flight_then_is_refused_still_enabled` — an `UpdateStrategy` enabling the strategy is parked before its commit.
  - `::test_an_archive_waiting_behind_a_delete_answers_unknown_strategy` — the delete is parked before its commit; the archive waits; after the commit it raises `UnknownStrategy`.
  - `::test_two_concurrent_deletes_delete_once_and_the_second_answers_unknown_strategy`.
  - Done 2026-10-02, commit c10a0b6. Observed non-vacuity (not committed): with `fk_signals_strategy` dropped, tests 1 and 2 go red; row lock before pool lock reds the `NOWAIT` test and the two-deletes test; another lock key reds the advisory test.
- [x] 9xc.6 The archived branch (Q3 answered "yes", decision 42: unblocked). RED `backend/tests/strategies/application/test_delete_strategy.py::test_an_archived_strategy_with_no_history_is_deleted`, plus `::test_an_archived_strategy_with_history_is_refused_has_history`. GREEN: step 5 of § D: an archived strategy takes the same path as any other (it is disabled by construction), so the history count alone decides, and the INFO line carries `archived=True`. An archived strategy is still never re-enabled or un-archived. Done 2026-10-02, commit 445f84d.
- [x] 9xc.7 `archive_strategy.py:170`: remove `# pragma: no cover -- strategies are never deleted` and its comment; the branch is now reachable and is covered by 9xc.5's archive test. No other line of `ArchiveStrategy` changes. Done 2026-10-02, commit c10a0b6 (covered by 9xc.5's archive test; mutation: raising `RuntimeError` there reds it).

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: real PostgreSQL migrated to `head`; lock-hold harness on BOTH locks (`rules.tasks`: advisory locks have no meaningful fake). The row lock's partner is the foreign key's own `FOR KEY SHARE`, which exists only on `head`.
Rollback boundary: one use case, one repository method and one port method that no route calls; one deleted pragma. Revert removes them; nothing in production can delete a strategy before PR 12x-4.
Forecast: 550–800 lines. Actual: 1,627 lines over three code commits (445f84d 708, dde0191 410, c10a0b6 509), of which about 200 are production code and the rest tests. The owner approved a size exception on 2026-10-03: one PR, not split. The forecast missed because of the test files, so the 12x-4 and 12x-5 forecasts are likely low too.

### Unit 9xd — `DELETE /api/strategies/{id}` (300–450 lines) — PR 12x-4

**Needs**: PR 12x-3, and PR 12x-1 **deployed**. The archived case of 9xd.1 was waiting on Q3, answered "yes" (decision 42).

**Files**: Modify `backend/src/strategy_manager/strategies/infrastructure/router.py`; Modify
`backend/tests/strategies/infrastructure/test_router.py` (new tests only).

- [x] 9xd.1 RED `backend/tests/strategies/infrastructure/test_router.py` (a client with `raise_app_exceptions=False`): `::test_delete_a_strategy_with_no_history_204_no_body_and_get_is_404_afterwards`, `::test_delete_unknown_id_404`, `::test_delete_repeated_404`, `::test_delete_enabled_409_still_enabled_and_the_strategy_remains_enabled`, `::test_delete_with_history_409_has_history_carries_all_six_integer_counts` (one signal for `STXUSDT.P` on a strategy allowing `STXUSDT`; `detail.history == {"signals": 1, "reservations": 0, "execution_attempts": 0, "ledger_entries": 0, "booking_proposals": 0, "enablement_events": 0}`), `::test_delete_a_toggled_strategy_409_has_history_naming_its_enablement_events`, `::test_delete_database_refusal_is_409_has_history_never_500` (`dependency_overrides[get_delete_strategy]`), `::test_after_a_delete_events_performance_and_archive_answer_404`, `::test_a_deleted_id_registers_again_201_with_zero_uptime`, `::test_a_refused_delete_leaves_the_session_usable_for_the_next_request`. `::test_delete_archived_with_no_history_204` (Q3 answered "yes", decision 42). RED against a route that always answers 204: `assert 200 == 404`, `assert 204 == 409`. Done 2026-10-03, commit d0168e2 (the RED stub and the tests were committed together with the GREEN, so no commit is red). Observed RED against the 204 stub: all 11 tests failed on assertions (`assert 200 == 404`, `assert 204 == 404`, `assert (204, 204) == (204, 404)`, `assert 204 == 409` x5, `assert 409 == 201`, the follow-up 404 map). One extra test, `::test_a_refused_delete_releases_the_row_lock_before_the_session_closes` (still_enabled and has_history), proves the rollback on those branches with `FOR UPDATE NOWAIT`. `::test_a_refused_delete_leaves_the_session_usable_for_the_next_request` shares one session across two requests, so a missing rollback is visible. Mutations (reverted): no rollback in the HAS_HISTORY branch reds both of those (`assert 500 == 200`, `LockNotAvailableError`); no rollback in the STILL_ENABLED branch reds the NOWAIT test; swallowing `UnknownStrategy` reds the unknown, repeated and follow-up tests. The ORM names the reservations key `reservations_strategy_id_fkey`, so the database-refusal test asserts that name, not the migration's `fk_reservations_strategy`.
- [x] 9xd.2 GREEN: the route, `get_delete_strategy` (the `get_register_strategy` pattern), the mapping of design addendum 9x § F, and `session.rollback()` on every refusal. The module docstring's "nothing here executes a trade" stays true; add one sentence on the delete. Done 2026-10-03, commit d0168e2.
- [x] 9xd.3 Confirm, unmodified: `tests/strategies/infrastructure/test_router_auth.py::test_every_registered_route_refuses_a_request_without_a_token` enumerates the new route and it answers 401. If any route-inventory test must be taught the new `DELETE`, record the edit here; no assertion is relaxed. Done 2026-10-03: `test_router_auth.py` is unmodified. `_routes()` reads `strategies_router.routes`, which now holds `('DELETE', '/strategies/{strategy_id}')`, and the test passes (10 passed): the DELETE answers 401 without a token. No route-inventory test needed teaching.
- [ ] 9xd.4 Owner step, after the deploy and at the owner's choice: delete the two test strategies with `curl -X DELETE` against `/api/strategies/{id}` (the admin token is never pasted into a chat or a log), or wait for the panel control. A 409 `HAS_HISTORY` naming `enablement_events` is Q1 showing up in production; record what was answered in the delivery log. **2026-10-03: the owner chose to wait for the panel control** and did not run the `curl`. The two test strategies stay until the control is mounted (task 9d.6) and the panel can reach them.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: `httpx.AsyncClient` over ASGI, real PostgreSQL through the module's conftest. The ORM schema is enough here: the route maps what 9xc proved on `head`, and the database-refusal case is driven by a dependency override.
Rollback boundary: one route and its dependency factory; revert answers 405 on `DELETE`. Strategies deleted meanwhile stay deleted.
Forecast: 300–450 lines. Actual: 445 changed lines in one code commit (d0168e2: 442 insertions, 3 deletions; about 50 of them production code, the rest tests). Within the forecast and the 800-line limit.

### Unit 9xe — the panel's delete control (400–600 lines) — PR 12x-5

**Needs**: PR 12x-4. Not unit 9d. The archived case of 9xe.3 was waiting on Q3, answered "yes" (decision 42).

**Files**: Modify `frontend/src/shared/api/strategies.ts`; Create
`frontend/src/shared/api/strategies.delete.test.ts`,
`frontend/src/features/strategies/{DeleteStrategyControl,DeleteStrategyDialog}.tsx` and their
`.test.tsx`; Modify `frontend/src/shared/i18n/locales/{en,es}.json`.

- [x] 9xe.1 RED `frontend/src/shared/api/strategies.delete.test.ts::sends DELETE /api/strategies/{id} and resolves on a 204`, `::removes the deleted strategy's queries instead of refetching them`, `::invalidates both strategies lists on success`, `::treats a 404 as already deleted and runs the same cache effects`, `::keeps the code and the history counts of a 409`. GREEN in the same task: `deleteStrategy`, `useDeleteStrategy(strategyId)`. RED against a stub that sends a `GET` and touches no cache. Done 2026-10-03, commit 08fcf0b (stub, tests and GREEN committed together). Observed RED against the stub: 5 of 7 failed on assertions (`expected undefined to be 'DELETE'`, `expected { Object (id) } to be undefined`, `expected [] to deeply equal [ [ 'strategies' ] ]`, `expected false to be true` x2 on the invalidation and the 404 effects). The 409 test passed at once; mutation: `onSettled` instead of `onSuccess` reds it (`expected undefined to deeply equal { Object (id) }`), reverted. A seventh test, "sends nothing until asked", passed at once and was dropped as trivial. One test added: the deleted strategy's own query is never invalidated.
- [x] 9xe.2 RED `frontend/src/features/strategies/DeleteStrategyDialog.test.tsx::test_confirm_is_disabled_until_the_typed_text_equals_the_name`, `::test_enter_in_the_field_does_not_confirm_while_the_name_does_not_match`, `::test_cancel_and_escape_call_onCancel_and_never_onConfirm`, `::test_it_states_that_the_delete_cannot_be_undone`, `::test_still_enabled_refusal_is_rendered`, `::test_has_history_names_each_nonzero_kind_with_its_count_and_no_zero_kind` (3 signals, 2 ledger entries; no "reservations" line), `::test_has_history_says_the_strategy_can_be_archived_instead`, `::test_a_missing_or_malformed_history_shows_the_main_sentence_alone`, `::test_pending_disables_both_buttons`, `::test_every_control_has_an_accessible_name`, `::test_every_key_exists_in_en_and_es`. RED against a component that renders an empty `<dialog />`. Texts are read through `i18n.t`, so a missing key fails on its text. Done 2026-10-03, commit 7ccce16. RED against an empty `<dialog />`: 17 of 17 failed, mostly on testing-library lookups of the i18n key text (`Unable to find a label with the text of: strategies.delete.typeName`), one on a real assertion (`expected [] to deeply equal [ Array(25) ]`). Extra tests: enablement events named like any other kind, malformed history (4 cases), generic refusal, Escape ignored while pending, ES render. Mutations (reverted): dropping the match guard in the submit handler reds the Enter test; dropping `count > 0` reds the two kind-list tests; cancelling while pending reds the Escape-while-pending test.
- [x] 9xe.3 RED `frontend/src/features/strategies/DeleteStrategyControl.test.tsx::test_a_single_click_opens_the_confirmation_and_sends_no_request`, `::test_the_button_is_disabled_with_a_hint_while_the_strategy_is_enabled`, `::test_a_confirmed_delete_sends_the_request_and_navigates_to_the_list_with_replace`, `::test_a_404_navigates_to_the_list_without_showing_an_error`, `::test_a_refusal_keeps_the_dialog_open_and_does_not_navigate`, `::test_texts_render_in_es`. `::test_the_control_for_an_archived_strategy_is_offered` (Q3 answered "yes", decision 42). Done 2026-10-03, commit 075ef12. RED against a `<div />` stub: 8 of 8 failed, on testing-library lookups of the i18n key text, the same pattern as the dialog. Mutations (reverted): removing `replace: true` reds two tests; `disabled={false}` reds the enabled-strategy test; removing `deletion.reset()` reds the reopen test.
- [x] 9xe.4 GREEN: both components per design addendum 9x § H; `strategies.delete.*` keys in EN and ES. Native `<dialog>`, palette tokens only, no new dependency. Done 2026-10-03: the dialog and the keys in commit 7ccce16, the control in commit 075ef12. The existing dialogs are `div role="dialog"`; this one is a native `<dialog>` as the design says, calling `showModal` where the browser has it.
- [x] 9xe.5 Only if unit 9d merged before this PR: mount the control (task 9d.6) here and tick 9d.6 with a pointer. Otherwise this task is void and 9d.6 stands. VOID 2026-10-03: 9d.6 is unchecked and `StrategyDetailPage` is still the placeholder, so nothing mounts strategy controls; the control is mounted nowhere and 9d.6 stands.

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")`; the dialog is tested as a presentational component with props.
Rollback boundary: three new files, one hook and i18n keys; nothing mounts them until 9d.6. The server refuses on its own.
Forecast: 400–600 lines. Actual: 827 changed lines in three code commits (08fcf0b 166, 7ccce16 435, 075ef12 226), 27 over the 800 limit. The owner approved a size exception on 2026-10-03: one PR, not split.

### Unit 9xf — enablement events are deleted with their strategy, migration 0028 (400–600 lines) — PR 12x-6

**In scope: the owner answered Q1 with "enablement events do not block a delete" (decision 42,
owner-decisions.md, 2026-10-02). It was conditional on that answer, and the answer is recorded.
Not started until 12x-3 is merged and deployed.**

**Needs**: PR 12x-3. Independent of 12x-4 and 12x-5.

**Files**: Create `backend/migrations/versions/0028_enablement_events_cascade.py`,
`backend/tests/migrations/test_0028_enablement_events_cascade.py`; Modify
`backend/src/strategy_manager/strategies/application/{ports,delete_strategy}.py`,
`backend/tests/strategies/application/{test_strategy_history,test_delete_strategy}.py`,
`backend/tests/strategies/infrastructure/{test_strategy_references_guard,test_delete_strategy_integration,test_router}.py`;
Modify `specs/strategy-lifecycle/spec.md`, `specs/admin-api/spec.md` (the two "Open" notes become the decided text).

- [x] 9xf.0 The owner's answer is already recorded (owner-decisions.md, decision 42, Q1). Remaining: revise the two spec requirements (`specs/strategy-lifecycle/spec.md`, `specs/admin-api/spec.md`; the two "Open" notes become the decided text). No code before this. Done 2026-10-03, commit d013469. The Q1 notes became decided text, the stale Q3 notes in the same requirements (answered "yes" the same day) became decided text too, the log line of a successful delete now names the events deleted, the first enable time and the uptime, and three scenarios were added (events beside a signal, the append-only protection that survives, and the admin-api twin).
- [x] 9xf.1 RED `backend/tests/migrations/test_0028_enablement_events_cascade.py` (the `tests/migrations/` pattern): `::test_deleting_a_strategy_takes_its_enablement_events_with_it` — **this is the design's assumption** (inside the cascade the trigger no longer sees the parent row); if it cannot be made green with the `NOT EXISTS` condition, stop, record it, and amend design addendum 9x § G to the `pg_trigger_depth()` fallback before writing anything else; `::test_a_direct_delete_of_an_event_whose_strategy_exists_is_still_refused` (SQLSTATE `23001`), `::test_an_update_of_an_event_is_still_refused`, `::test_a_strategy_with_a_signal_is_still_refused_and_its_events_survive` (constraint name `fk_signals_strategy`), `::test_truncate_strategies_cascade_still_works` (the conftests rely on it), `::test_downgrade_restores_no_action_and_the_unconditional_trigger`, `::test_upgrade_downgrade_upgrade_is_clean`, `::test_the_migration_moves_no_row`. Done 2026-10-03, commit c36601c. **The design's assumption held: the `NOT EXISTS` condition is what shipped, and the `pg_trigger_depth()` fallback was not needed.** Observed RED against a no-op stub migration (5 of 10 on assertions: `assert 'fk_strategy_enablement_events_strategy' is None` x2, `assert 'a' == 'c'`, `assert 0 == 1` on the WARNI count, `assert ('a', 'fk_str…', 1, 1) == ('c', None, 0, 0)`). Five passed at once and were proven by mutation of the migration (each went red, each reverted): the trigger deleting unconditionally reds the direct-delete test, an `UPDATE` passthrough reds the update test, `fk_signals_strategy` recreated with `CASCADE` reds the signal test (`assert None == 'fk_signals_strategy'`), a `BEFORE TRUNCATE` guard on the events table reds the truncate test, an `UPDATE strategies` reds the no-row test. Two tests beyond the list: `::test_a_cascade_takes_only_the_deleted_strategys_events`, `::test_the_foreign_key_cascades_and_the_trigger_is_conditional_at_head`. `::test_truncate_strategies_cascade_still_works` drops `trg_ledger_no_truncate` in its own throwaway database, because the ledger's own TRUNCATE guard (migration 0005) refuses any cascade that reaches `ledger_entries` on `head`; the ORM conftest schemas, which the conftests really TRUNCATE, have no such trigger. The two head-schema tests that depended on the events key being `NO ACTION` moved in the same commit (the guard now expects `CASCADE` on that key and `NO ACTION` on the other four, observed RED `assert {'a', 'c'} == {'a'}`; the 9xc.4 backstop test is re-pointed at `fk_signals_strategy`, observed RED `assert isinstance(refusal, StrategyHasHistory)` with `refusal` None), and so did `test_0027_credential_snapshot.py`, which asserted that `head` is 0027.
- [x] 9xf.2 GREEN: migration 0028, `down_revision = "0027"` (design addendum 9x § G: `CREATE OR REPLACE FUNCTION`, then the foreign key recreated with `ON DELETE CASCADE`; the downgrade restores both and logs one WARNING). Done 2026-10-03, commit c36601c.
- [x] 9xf.3 RED: `test_strategy_history.py::test_enablement_events_alone_do_not_block`; `test_delete_strategy.py::test_a_strategy_with_only_enablement_events_is_deleted`, `::test_the_info_line_names_the_events_deleted_the_first_enable_time_and_the_uptime`; `test_delete_strategy_integration.py::test_a_strategy_enabled_and_disabled_once_is_deleted_with_its_events`; `test_router.py::test_delete_a_toggled_strategy_204`; `test_strategy_references_guard.py` expects `CASCADE` on the events key and `NO ACTION` on the other four. The tests they replace are renamed in the same commit, never deleted silently: 9xb.1's and 9xc.2's `enablement_events` parameter, 9xc.4's `::test_the_database_refuses_a_delete_the_count_wrongly_allowed` (re-pointed at a foreign key that is still `NO ACTION`), 9xd.1's `::test_delete_a_toggled_strategy_409_has_history_naming_its_enablement_events`. Done 2026-10-03, commit 0a5304b; the re-pointed guard and backstop tests are in c36601c, because the migration changes the key they asserted on. RED against stubs that accepted the new constructor parameters and ignored them: 8 tests failed on assertions (`assert False is True`, `assert 409 == 204`, `assert refusal is None`, `assert 'enablement_events=0' in "strategy deleted: ..."`, and captured `StrategyHasHistory` exceptions). Renamed, not deleted: `::test_is_empty_only_when_all_six_counts_are_zero` → `..._all_five_blocking_counts_are_zero`; `::test_blocking_names_only_the_nonzero_kinds_in_a_fixed_order` → `..._nonzero_blocking_kinds_...`; `::test_each_kind_of_history_alone_refuses_and_nothing_is_deleted` → `::test_each_blocking_kind_of_history_alone_refuses_and_nothing_is_deleted`; `::test_delete_a_toggled_strategy_409_has_history_naming_its_enablement_events` → `::test_delete_a_toggled_strategy_204`. Mutations (reverted): zeroing the events count in a refusal reds the router test that reports them beside a signal; `signals` added to `_NEVER_BLOCKING` reds four tests; an empty `_NEVER_BLOCKING` reds the two "events alone" tests.
- [x] 9xf.4 GREEN: `StrategyHistory.blocking()` no longer includes `enablement_events`; the count stays in the body for the other refusals and feeds the INFO line. Done 2026-10-03, commit 0a5304b. The INFO line needed a new `EnablementReaderPort` and a clock in `DeleteStrategy`: `strategy deleted: id=… name=… pool=… archived=… enablement_events=<n> first_enabled_at=<ISO-8601 | never> uptime_seconds=<int>`.
- [x] 9xf.5 Owner step: the 0028 rehearsal of "Migration rehearsal", on a throwaway database restored from a fresh backup, before production migrates. Then deploy: pull, `alembic upgrade head`, restart both services. Done 2026-10-03 by the owner: the rehearsal passed all seven steps and production is at 0028 (delivery log, PR 12x-6).

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: real PostgreSQL, migration up and down; the VPS rehearsal.
Rollback boundary: migration 0028's downgrade (schema only, no data discarded, no refusal clause) and one change to `blocking()`. Reverting the code alone, with 0028 applied, restores "events block" in the application; the cascade then never fires.
Forecast: 400–600 lines. Actual: 903 changed lines in two code commits (c36601c 622, of which about 105 are the migration and the rest tests; 0a5304b 281, about 60 of them production code), 103 over the 800 limit. The owner approved a size exception on 2026-10-03: one PR, not split. The owner also said the 800-line limit is not applied strictly: a unit that runs over without, for example, doubling it goes as one PR.

---

## PR 12e — A strategy's operations, listed and opened one by one (decision 43) (3,600–5,200 lines backend; 2,400–3,600 panel)

Two sequential PRs to `main`, never stacked: **12e-1** (unit 9p.4, backend) → **12e-2** (unit 9p.5,
panel). Each merges and deploys before the next branch is cut. Source of truth: design.md, "Addendum:
a strategy's operations, listed and opened one by one (decision 43) - 2026-10-04" (§§ A to L; every
question in § L is answered), and the requirements added on 2026-10-04 to
`specs/performance-reporting/spec.md`, `specs/admin-api/spec.md` and `specs/operator-panel/spec.md`.
This section turns tasks 9p.4 and 9p.5 into the tasks below; both stubs in unit 9p now point here.

**Why two PRs, and not for size** (design § I). (1) The panel refuses a page that lacks the new
fields and reads a route that must exist, so the API has to be merged and running before the panel
that asks for it. (2) The panel PR is the one the owner reviews by eye, and that review produced
seven follow-up tasks on PR 12d; they should not hold a finished backend change. The risks differ
too: 12e-1 is **medium** (it edits the aggregate every performance read shares, and adds a route),
12e-2 is **low**. The fills route does not get a PR of its own: inside 12e-1 it is its own tasks and
commits, so it can be reverted alone.

**No migration.** Every figure is derived from columns that exist (`ledger_entries`,
`reservations`, `signals`). The "Migration rehearsal" section does not change and nothing here is
rehearsed on the VPS.

**Decision 45 is a separate unit** (the simulated exchange fills at the alert's price; it touches
`execution`, not `performance`). This section does not wait for it and does not build any part of
it: a fill "at the alert's price" is written by the test fixture through the ledger's own write path,
never by the simulated exchange. Decision 45 is PR 12g (unit 9q, the section after this one) and is deployed
BEFORE 12e-1: every day of dry run at a fixed price writes history that can never be repriced, while
a delay here loses nothing. Neither waits for the other in code; the branch of whichever comes second
is cut from the updated `main`. Also out of scope, by design § J: WIN RATE in By
pair (decision 44) is its own unit, and no open position is shown anywhere on the page.

**Deploy order** is the reason for the order of the PRs: 12e-1 first (the older panel keeps working
against the new API, design § D), 12e-2 only after 12e-1 is deployed.

Rules that bind every unit here, on top of the cross-cutting rules:

- **RED fails on an ASSERTION.** A new function, field, port, route or query parameter is first
  added as a stub that compiles and answers WRONGLY (prices of zero, `rehearsal` always false, a
  classification that is always `UNDETERMINED`, a fills read that answers an empty list, a parameter
  that is accepted and ignored, a component that renders an empty `<dialog />`), in the same commit
  as the RED test. The first failure is never an `ImportError`, a `TypeError` or a type error. Where
  the wrong behaviour is "no exception is raised", the test captures the exception and asserts on its
  type, so the failure is still an assertion. In the frontend a RED asserts with
  `expect(screen.queryBy...(...)).toBeInTheDocument()` or `toEqual`, not with a `getBy` that throws
  before any expectation runs. **Each task records the assertion it failed on** (for example
  `assert Decimal('0') == Decimal('0.4512')`). A RED that cannot be written on a stub is a task that
  says so and names the mutation instead.
- **A test that passes at once is proven non-vacuous by the mutation its task names** (design § H's
  table). The mutation is applied, the test is seen red, and the mutation is reverted; it is never
  committed. The task records what was seen.
- **Where the `head` schema is needed, and why** (design § H). Only where a constraint or an index
  that the ORM schema lacks decides the outcome: task 9p.4.25 (`price`, `quantity` and `notional`
  are `CHECK > 0` only in migration 0005, finding T6; `ix_ledger_allocation` exists only in migration
  0012, finding T17). It uses `backend/tests/pg_head_schema.py` and says so in its docstring. Every
  other backend integration test runs on the ORM schema of `tests/performance/infrastructure/conftest.py`,
  because it reads and the read decides nothing by a constraint. The index is asserted from
  `pg_indexes`, never from a query plan: on a table of a few rows the planner scans whatever the
  indexes are.
- **No lock-hold harness applies.** The reads take no lock and write nothing, so there is no second
  actor to prove waiting. The one concurrency property of the list, a trade that closes between two
  page reads, is already tested on real PostgreSQL and must stay green with rehearsal rows in the
  fixture (task 9p.4.24).
- **Symbol spellings across the boundary.** The one fixture (task 9p.4.23) writes the real LONG as
  `STXUSDT.P` (TradingView's) on its opening side and `STXUSDT` (the venue's) on its closing side,
  and the rehearsal operation as `STXUSDT_PERP` (Pionex's) opening and `STXUSDT.P` closing; the
  strategy allows `STXUSDT`. Every assertion reads pair `STXUSDT` and base currency `STX`, and no
  assertion compares two spellings as text. One domain test pins that `STXUSDT.P` and `STXUSDT` on the
  two sides of one allocation are NOT a pair disagreement and that `STXUSDT` and `SOLUSDT` are
  (9p.4.2). The fills route is asked for the same operations and must answer the fills of BOTH
  spellings: it keys on the allocation, never on the symbol (9p.4.28, 9p.4.34).
- **Every failure mode of design § G has a test asserting its one log line and its level**, and no
  line carries a credential, a DSN, a token, a raw payload, a price, a quantity or a fee: ids, the
  pool label, counts and market keys only. The map of § G to tasks:

  | § G failure | Level and line | Test task |
  |---|---|---|
  | A side with no quantity or notional above zero; a division by zero | WARNING: pool, strategy, allocation id, the side | 9p.4.17 |
  | Fills naming two markets | WARNING: pool, strategy, allocation id, the market keys; two spellings of one market log nothing | 9p.4.17 |
  | The opener's last fill is not before the closer's first | WARNING: pool, strategy, allocation id | 9p.4.17 |
  | A mixed allocation in the list | WARNING: pool, strategy, allocation ids | 9p.4.15 |
  | A rehearsal group handed to a total | the existing 500 and one ERROR from `_guarded` | 9p.4.12, 9p.4.32 |
  | A non-positive pool capital on a rehearsal reservation | the existing 500 and ERROR | 9p.4.15, 9p.4.32 |
  | Rehearsal rows whose price is `UNDETERMINED` | INFO, one line per page with the count | 9p.4.19 |
  | Pricing facts missing for a rehearsal row | WARNING: pool, strategy, allocation ids | 9p.4.19 |
  | Fills asked for an unknown, foreign or empty allocation | WARNING: strategy id, allocation id; the 404 `no such operation` | 9p.4.26, 9p.4.34 |
  | More than 200 fills | WARNING: strategy id, allocation id, the cap | 9p.4.26, 9p.4.34 |
  | A mixed allocation in the fills read | WARNING: strategy id, allocation id | 9p.4.26 |
  | A fill of another pool in the fills read | the existing 500 and ERROR | 9p.4.26, 9p.4.34 |
  | The panel forgets `include_rehearsal`; a row with a missing or mistyped field; a fills body that is malformed or names another allocation | nothing can log it (the browser has no log); a test pins each | 9p.5.2, 9p.5.4, 9p.5.14 |
  | The list or the fills read degrades to one statement per row or per fill | cannot be logged; statement-count tests | 9p.4.24, 9p.4.28, 9p.4.34 |

- **Every total is identical with and without rehearsal groups**, proven by tests with a named
  mutation: the pool report, the strategy report, the curve, the monthly grid, the ranges, by-pair and
  `excluded.rehearsal_fill_count` in 9p.4.14 (units) and 9p.4.24 (the one ledger, on real
  PostgreSQL). The mutation is the read that concatenates `groups` and `rehearsal_groups`.
- **Rule 7 and the wire.** `fees` is in the settlement currency and a fee in any other currency is
  listed in its own currency and never converted. The fills route sums nothing, serves each fee with
  its currency and refuses a fill of another pool. Money, quantities, prices and ratios are JSON
  strings in plain notation, never a number and never an exponent: the new `Price` type, and a walk of
  every response of both routes (9p.4.36). The panel never computes a money figure from a string.
- **Existing tests of the list, the reports, the curve and by-pair are not edited**, except the
  recorded edits: the `FillGroup` builders (9p.4.1), the constructor argument of `ReadStrategyTrades`
  (9p.4.19) and the two sweeps (9p.4.36). Any other edit of an existing test is recorded in its task
  with the reason; nothing is deleted silently and no assertion is relaxed.
- **Commits.** One work-unit commit per task, or per RED/GREEN pair where a red commit would break the
  gate, as 9xd.1 did; the RED is observed and recorded either way. `git commit -F <file>`, conventional
  commits, no AI attribution.
- **No size rule.** The owner does not want work split by size. The forecasts below are information
  only.
- **What fails here without a log line?** is answered by the table above and by design § G. A figure
  that cannot be derived is null with a WARNING and the operation stays in the list; it is never zero.

### Unit 9p.4 — operations: figures, rehearsal rows on request, price source, fills route (backend) (3,600–5,200 lines) — PR 12e-1

**Needs**: nothing. It is independent of decision 45 and of unit 9d. It does NOT need the panel.

**Files**:
Create `backend/src/strategy_manager/performance/domain/operation.py`,
`backend/src/strategy_manager/performance/application/read_operation_fills.py`,
`backend/src/strategy_manager/performance/infrastructure/rehearsal_pricing_source.py`,
`backend/src/strategy_manager/performance/infrastructure/operation_fills_source.py`.
Modify `backend/src/strategy_manager/performance/domain/closed_trade.py` (`FillGroup.rehearsal`),
`backend/src/strategy_manager/performance/application/{ports,scope,read_pool_performance,read_strategy_performance,read_strategy_trades}.py`,
`backend/src/strategy_manager/performance/infrastructure/{allocation_fills_source,performance_router}.py`,
`backend/src/strategy_manager/shared/infrastructure/wire.py` (`Price`).
Create `backend/tests/performance/domain/{test_operation_figures,test_operation_fees,test_operation_overlap,test_rehearsal_pricing}.py`,
`backend/tests/performance/application/{test_require_live_only,test_read_operation_fills}.py`,
`backend/tests/performance/infrastructure/{test_rehearsal_pricing_source,test_operation_fills_source,test_operations_list_integration,test_operations_statement_counts,test_ledger_head_constraints,test_operations_router}.py`,
`backend/tests/shared/infrastructure/test_wire_price.py`.
Modify `backend/tests/performance/fakes.py`, `backend/tests/performance/infrastructure/conftest.py`
(the one fixture), `backend/tests/performance/infrastructure/test_allocation_fills_source.py` (new
tests only), `backend/tests/performance/application/{test_read_strategy_trades,test_read_pool_performance,test_read_strategy_performance}.py`
(new tests, and the builders of 9p.4.1), `backend/tests/performance/infrastructure/test_strategy_trades_integration.py`
(one new test), `backend/tests/signals/infrastructure/test_webhook_secret_router.py` (the sweep, 9p.4.36).

**The domain derivation** (design §§ A, B, D9)

- [x] 9p.4.1 Plumbing, no behaviour change: `FillGroup` in `performance/domain/closed_trade.py` gains `rehearsal: bool`, no default; `SqlAlchemyAllocationFillsSource` passes `rehearsal=False` (every group it returns is still non-rehearsal); the six builders of `FillGroup(` in `tests/performance/application/{test_read_strategy_trades,test_read_strategy_performance,test_read_pool_performance}.py`, `tests/performance/domain/{test_derive_trade,test_by_pair}.py` and `tests/performance/infrastructure/test_performance_router.py` gain `rehearsal=False` and nothing else. `ClosedTrade` is NOT changed. No RED: the proof is that `uv run mypy src tests` refuses a builder left without the argument (remove one, see it fail, restore) and the existing performance suites pass unmodified.
  - Evidence (commit `b8babc5`). `uv run mypy src tests` reported exactly seven `Missing positional argument "rehearsal" in call to "FillGroup"` errors with the field added and no builder touched, and none after. **Recorded gap in the task text:** the task names six builders; there is a seventh, `tests/signals/infrastructure/test_simulated_fill_webhook_to_ledger.py:285` (the decision 45 webhook-to-ledger test), which gained `rehearsal=False` and nothing else. Safety net before: 135 tests in `tests/performance` plus that file passed; collected in the whole suite before this batch: 2,992. After: the same 135 pass unmodified, `ruff` 0, `mypy src` clean.
- [x] 9p.4.2 RED `backend/tests/performance/domain/test_operation_figures.py`, with the stub module `performance/domain/operation.py` in the same commit: `FeeAmount`, `OperationFees`, `OperationFigures` (base currency, entry price, exit price, size), `operation_fees(groups) -> OperationFees`, `operation_figures(groups, direction) -> OperationFigures | None`, `sides_overlap(groups, direction) -> bool`; the stub answers `Decimal(0)` for every figure, an empty `base_currency`, zero fees, no other fees, and `False`. Imports `decimal`, `dataclasses`, `market_symbol` and `closed_trade` only (design § E). Hand-built `FillGroup`s. Tests: `::test_one_fill_per_side_gives_that_fills_prices_and_the_base_currency` (1250 `STXUSDT.P` at 0.4512, notional 564.0; 1250 `STXUSDT` at 0.4631), `::test_the_entry_price_is_weighted_by_quantity_not_a_mean_of_group_averages` (100 at 0.40, 300 at 0.44, 600 at 0.46 sold as 1000 at 0.50: entry 0.448 not 0.4333…, size 1000, exit 0.50), `::test_a_short_enters_on_its_sell_side` (sold 2 `SOLUSDT` at 150, bought 2 at 140: entry 150, exit 140, size 2), `::test_size_is_the_opening_quantity_when_a_base_currency_fee_makes_the_sides_differ` (bought 1000, sold 999), `::test_pnl_equals_exit_minus_entry_times_size_times_sign_minus_fees` (both directions, equal quantities, every fee in the settlement currency, against `derive_trades` for the pnl), `::test_a_quotient_is_computed_in_a_sixty_digit_context` (notional 1 over quantity 3 keeps sixty digits), `::test_a_side_whose_quantity_or_notional_is_not_above_zero_gives_none_and_never_divides` (parametrized: closing quantity 0, opening notional 0), `::test_fills_naming_two_markets_give_none` (`STXUSDT` and `SOLUSDT`), `::test_two_spellings_of_one_market_are_not_a_disagreement` (`STXUSDT.P` and `STXUSDT`). RED against the stub: `assert Decimal('0') == Decimal('0.4512')`, `assert Decimal('0') == Decimal('0.448')`, `assert OperationFigures(...) is None`. The last test passes at once; mutation: compare the raw symbols instead of `market_key`.
  - Evidence (RED observed against the stub, then committed with its GREEN in `f0f1591` because a red commit breaks the gate). First failures, all on assertions: `assert OperationFigures(base_currency='', entry_price=Decimal('0'), ...) == OperationFigures(base_currency='STX', ...)`, `assert Decimal('0') == Decimal('0.448')`, `assert Decimal('0') == Decimal('1000')` (base-fee size), `assert Decimal('0') == Decimal('0.333...')` (sixty digits, 60 threes), and `assert OperationFigures(...) is None` for the four parametrized sides and the two-markets case. **Deviations, recorded:** (1) `::test_two_spellings_of_one_market_are_not_a_disagreement` asserts the whole `OperationFigures` (base `STX`, entry 11, exit 12.5, size 2, with `STXUSDT.P`, `STXUSDT_PERP` and lower-case `stxusdt`), not only "is not None", so it also failed on the stub (`base_currency: '' != 'STX'`) rather than passing at once; its mutation (compare raw symbols instead of `market_key`) was applied after the GREEN commit and reds it: `assert None == OperationFigures(base_currency='STX', ...)`. (2) `::test_pnl_equals_exit_minus_entry_times_size_times_sign_minus_fees` needs `operation_fees`, so it cannot pass in the 9p.4.3 commit; its RED was observed against the stub (`assert ((((Decimal('0') - Decimal('0')) * Decimal('0')) * Decimal('1')) - Decimal('0')) == Decimal('28.9')`, both directions) and it lands in the 9p.4.5 commit. (3) The sixty-digit test also pins the rounding of a quotient that does not end: exit 2/3 is 59 sixes and a 7.
- [x] 9p.4.3 GREEN `operation_figures` (design § B): entry is `Σ notional / Σ quantity` of the side of the earliest fill (a tie to BUY, the rule `derive_trade` already uses), exit the same over the other side, size the opening quantity, base currency `base_currency_of(symbol, settlement_currency)` upper-cased, every quotient inside `decimal.localcontext` of 60 digits, the divisor checked before the division, and `None` for a side that is not above zero or for more than one `market_key`. Mutations that must red the 9p.4.2 tests, then reverted: the mean of the group averages (the weighting test); the entry always the BUY side (the SHORT test); the closing quantity as `size` (the base-fee test).
  - Evidence (commit `f0f1591`; the GREEN was committed BEFORE any mutation, each mutation reverted with `git checkout`). Mutations seen red: the mean of the group averages, `assert Decimal('0.4333...') == Decimal('0.448')` (the weighting test); the opening side always BUY, `assert OperationFigu... == OperationFigu...` (the SHORT test); the closing quantity as `size`, `assert Decimal('999') == Decimal('1000')` (the base-fee test). The `STXUSDT.P` / `STXUSDT_PERP` / `stxusdt` mutation is recorded under 9p.4.2.
- [x] 9p.4.4 RED `backend/tests/performance/domain/test_operation_fees.py`: `::test_fees_sum_every_fill_of_both_sides_in_the_settlement_currency` (0.31 and 0.32 give 0.63), `::test_the_fees_equal_the_amount_derive_trade_subtracts_from_pnl`, `::test_a_fee_in_another_currency_is_listed_once_per_currency_with_its_own_sum_sorted_by_currency` (0.00012 BNB in two fills of 0.00005 and 0.00007, and a lower-case `bnb` that merges with them), `::test_a_zero_sum_other_fee_is_not_listed`, `::test_nothing_is_converted_and_the_settlement_currency_is_not_among_the_other_fees`. RED against the zero-fee stub: `assert Decimal('0') == Decimal('0.63')`, `assert () == (FeeAmount(currency='BNB', amount=Decimal('0.00012')),)`. The last two pass at once; mutations: list every currency including a zero sum; list the settlement currency too.
  - Evidence (RED observed against the zero-fee stub, committed with its GREEN in `733b93e`). First failures: `assert Decimal('0') == Decimal('0.63')`, `assert () == (FeeAmount(currency='AAA', ...), FeeAmount(currency='BNB', amount=Decimal('0.00012')))` (the sorted test lists two currencies, `AAA` and a `bnb`/`BNB` merge, so the sort is observable). The derive_trade identity test (a base-currency fee in the BUY group is not in `fees`) was first observed red with a variant of its fixture (`assert Decimal('0') == Decimal('0.55')`); the committed fixture was corrected to one group per fill currency and was seen green only after the GREEN. **Deviations, recorded:** the zero-sum and the settlement-not-listed tests also assert `fees`, so they failed on the stub instead of passing at once; the long test name was shortened to `test_other_currency_fees_are_listed_once_per_currency_with_own_sum_sorted` to fit the 100-column lint limit.
- [x] 9p.4.5 GREEN `operation_fees` (design § B): plain sums, fee currencies compared and reported upper-cased, `fees` and `other_fees` never null. It does not touch `fees_complete`: a base-currency fee is listed and leaves the flag true, a third-currency fee is listed and makes it false, both as `derive_trade` already decides (test in 9p.4.17).
  - Evidence (commit `733b93e`, which also holds the pnl-identity test moved from 9p.4.2). Mutations seen red after the GREEN commit: listing a currency whose sum is zero, `assert (FeeAmount(...Decimal('0')),) == ()`; listing the settlement currency too, three tests red (`assert (FeeAmount(...Decimal('0.63')),) == ()`, `... Decimal('0.2')`, and the settlement-not-listed test).
- [x] 9p.4.6 RED `backend/tests/performance/domain/test_operation_overlap.py`: `::test_a_tie_between_the_openers_last_fill_and_the_closers_first_is_an_overlap` (both at the same instant, which `_direction` breaks in favour of BUY), `::test_an_opener_whose_last_fill_is_after_the_closers_first_is_an_overlap`, `::test_a_clean_round_trip_is_not_an_overlap`. RED against the stub (`False`): `assert False is True`. The clean test passes at once; mutation: `sides_overlap` always true.
  - Evidence (RED observed against the `False` stub, `assert False is True` three times: the tie, the opener-after-closer and a SHORT's overlap; the clean round trip and the clean SHORT passed at once. Committed with its GREEN in `16b3fe4`). One test beyond the task: `::test_a_shorts_opening_side_is_its_sell_side`.
- [x] 9p.4.7 GREEN `sides_overlap`: the opening side's last fill is not strictly earlier than the closing side's first fill (design § G).

**Rehearsal classification** (design § C, D16)

  - Evidence (commit `16b3fe4`). Mutation seen red after the GREEN commit: `sides_overlap` always true, `assert True is False` (the clean round trip and the clean SHORT).
- [x] 9p.4.8 RED `backend/tests/performance/domain/test_rehearsal_pricing.py`, with stubs in `operation.py` in the same commit: `RehearsalPricing` (`FIXED_ONE`, `ALERT`, `UNDETERMINED`), `PricingFacts` (the alert's price, and the lowest and highest fill price of each side, or none), `classify_rehearsal_pricing(direction, facts)` that answers `UNDETERMINED` always. Tests, each on exact `Decimal` values: `::test_filled_at_one_against_another_alert_price_is_fixed_one` (1 against 0.4512), `::test_filled_at_the_alerts_price_is_alert` (0.4512 against 0.4512), `::test_an_alert_priced_exactly_one_reads_alert` (1 against 1), `::test_a_fill_at_neither_price_is_undetermined` (0.45 against 0.4512), `::test_opening_fills_at_different_prices_are_undetermined` (lowest 1, highest 0.4512, alert 0.4512), `::test_only_the_opening_side_decides` (opened at 1, closed at 0.4512: `FIXED_ONE`), `::test_a_shorts_opening_side_is_its_sell_side`, `::test_missing_facts_are_undetermined`. RED against the stub: `assert <RehearsalPricing.UNDETERMINED: 'UNDETERMINED'> == <RehearsalPricing.FIXED_ONE: 'FIXED_ONE'>`. Passing at once, each with its mutation: the 0.45 test (mutation: "not 1" read as `ALERT`), the mixed-prices test (mutation: only the lowest price tested), the missing-facts test (mutation: a default of `ALERT`).
  - Evidence (RED observed against the always-`UNDETERMINED` stub: `assert <RehearsalPricing.UNDETERMINED: 'UNDETERMINED'> is <RehearsalPricing.FIXED_ONE: 'FIXED_ONE'>`, and the same against `ALERT`, five tests; committed with its GREEN in `b201932`). The tests compare with `is` (enum members), not `==`. Passed at once: the 0.45 test, the mixed-prices test (and a second mixed test, lowest equal to the alert and highest 1) and the missing-facts test. `PricingFacts(alert_price, buy, sell)` carries the price range of each side as `SidePrices(lowest, highest) | None`; a missing opening side is `UNDETERMINED`. Mutations seen red after the GREEN commit: "not 1" read as `ALERT` (the 0.45 test, `assert ALERT is UNDETERMINED`); only the lowest price tested (both mixed-price tests); a missing side defaulting to `ALERT` (the missing-facts test).
- [x] 9p.4.9 GREEN `classify_rehearsal_pricing`: `FIXED_ONE` when every opening fill is exactly 1 and the alert's price is not 1; `ALERT` when every opening fill is exactly the alert's price (which includes an alert of exactly 1); `UNDETERMINED` otherwise. It compares the fills' own `price`, never a derived average, and never reads the closing side. Mutations that must red 9p.4.8, then reverted: the alert comparison dropped (`price is 1` alone decides) reds the alert-of-1 test; the closing side tested instead of the opening one reds the opened-at-1 test.

**The source and the two walls** (design § C, E)

  - Evidence (commit `b201932`). Mutations seen red: the alert comparison dropped (three tests, including the alert-of-1 one: `assert FIXED_ONE is ALERT`); the closing side read instead of the opening one (five tests, including the opened-at-1 one).
- [x] 9p.4.10 RED `backend/tests/performance/infrastructure/test_allocation_fills_source.py`, new tests only, with the stub `PoolFills.rehearsal_groups: tuple[FillGroup, ...] = ()` in `performance/application/ports.py` in the same commit (real PostgreSQL, ORM schema, the module's fixtures and `_fill`/`_record`/`_seed_allocation`): `::test_rehearsal_groups_are_returned_in_their_own_set_marked_rehearsal`, `::test_groups_holds_the_non_rehearsal_groups_exactly_as_before`, `::test_an_allocation_written_under_two_spellings_on_one_side_yields_one_group_per_spelling` (symbol joins the GROUP BY, design § E), `::test_an_allocation_with_fills_of_both_origins_yields_groups_in_both_sets`. RED against the stub: `assert () == (FillGroup(...),)`. The existing `::test_a_fill_id_merely_containing_the_prefix_is_not_a_rehearsal_fill` and `::test_source_counts_rehearsal_fills_per_strategy` stay, untouched, and are the prefix-not-substring and unchanged-count checks; mutation for the first: `startswith` becomes `contains`. `::test_source_groups_by_allocation_strategy_side_fee_currency` asserts an allocation opened as `SOLUSDT.P` and closed as `SOLUSDT` (different sides, so its group count does not change); if it nevertheless needs a change because of the symbol column, the edit is recorded here with the reason.
  - Evidence (real PostgreSQL, ORM schema; RED observed with the `rehearsal_groups = ()` stub, committed with its GREEN in `a1d6bb3`). First failures: `assert [] == [(UUID(...), 'BUY', True), (UUID(...), 'SELL', True)]`, `assert [] == [UUID(...)]`, `assert [('SOLUSDT.P', Decimal('3'))] == [('SOLUSDT.P', Decimal('1')), ('SOLUSDT_PERP', Decimal('2'))]` (two spellings merged by `min(symbol)` today) and `assert [] == [('SELL', True)]`. **Deviation, recorded:** `::test_groups_holds_the_non_rehearsal_groups_exactly_as_before` also asserts `rehearsal_groups`, so it failed on the stub instead of passing at once. The existing tests, including `::test_source_groups_by_allocation_strategy_side_fee_currency` (all BUYs share a spelling), pass unmodified and nothing in them was edited.
- [x] 9p.4.11 GREEN `SqlAlchemyAllocationFillsSource.pool_fills` (design § C, E): the aggregate groups by the prefix test (`startswith(..., autoescape=True)`, as today) and by `symbol`, loses its `NOT LIKE` filter, and the adapter splits the rows into `groups` (rehearsal false) and `rehearsal_groups`; `FillGroup.rehearsal` is the grouped column. The count statement is unchanged, so `excluded.rehearsal_fill_count` keeps its meaning and its source. `derive_trades` sums across groups, so no existing result changes.
  - Evidence (commit `a1d6bb3`). The prefix test is a labelled expression (`is_rehearsal.label("is_rehearsal")`) used in both the select list and the GROUP BY, so PostgreSQL sees one expression and not two bind parameters. Mutations seen red after the GREEN commit: `startswith` becomes `contains`, the existing `::test_a_fill_id_merely_containing_the_prefix_is_not_a_rehearsal_fill` red on `assert 0 == 1`; every group appended to the live set, four tests red (`::test_source_excludes_fake_fill_prefix_rows`, the rehearsal-set test, the as-before test and the mixed-origin test).
- [x] 9p.4.12 RED `backend/tests/performance/application/test_require_live_only.py`, with the stub `require_live_only(groups)` (a no-op) in `performance/application/scope.py` in the same commit: `::test_a_rehearsal_group_in_the_live_set_is_refused_naming_the_allocation`, `::test_a_live_set_without_rehearsal_groups_is_accepted`; and in `test_read_pool_performance.py` and `test_read_strategy_performance.py`: `::test_a_source_that_puts_a_rehearsal_group_in_the_live_set_is_refused` (a `FakeFillsSource` whose live tuple holds one). RED against the no-op: `assert None is InvariantViolation` (the exception captured, its type asserted). The accept test passes at once; mutation: always raise.
  - Evidence (RED observed against the no-op: `assert <class 'NoneType'> is InvariantViolation` in all three tests; the exception is captured and its type asserted; committed with its GREEN in `be63472`). The accept test passed at once.
- [x] 9p.4.13 GREEN `require_live_only` raising `InvariantViolation`, and one call in each of `ReadPoolPerformance` and `ReadStrategyPerformance` after `require_single_pool` (design § C, second wall). No other change to either read. Mutation that must red 9p.4.12, then reverted: the call or the check removed.
  - Evidence (commit `be63472`; the call sits after `require_single_pool` in the pool read and after `strategy_groups` in the strategy read, over `pool_fills.groups`). Mutations seen red after the GREEN commit: the check always raising (`assert InvariantViolation('...') is None` on the accept test); both calls removed (`assert <class 'NoneType'> is InvariantViolation` in each read's test).
- [x] 9p.4.14 Plumbing, then tests that pass at once. `backend/tests/performance/fakes.py`: `FakeFillsSource` gains `rehearsal_groups` and passes it into `PoolFills`. Then `test_read_pool_performance.py::test_the_pool_report_is_identical_with_and_without_rehearsal_groups`, `test_read_strategy_performance.py::test_the_strategy_report_is_identical_with_and_without_rehearsal_groups`, and `::test_excluded_rehearsal_fill_count_still_counts_every_rehearsal_fill_of_the_scope` (4 fills of a closed rehearsal allocation, 1 of an open one, 2 inside a mixed one: 7, and no new `excluded` key). The whole report is compared, so the curve, the monthly grid, the ranges and by-pair are inside it. They pass at once; mutation: the read concatenates `groups` and `rehearsal_groups`.

  - Evidence (commit `f9a47ea`; `FakeFillsSource` gained `rehearsal_groups`). The three tests passed at once. Mutation seen red after the commit: both reads concatenate `groups` and `rehearsal_groups`, three tests red (`assert PoolPerforman... == PoolPerforman...`, `assert StrategyPerfo... == StrategyPerfo...`, and `assert 2 == 0` on `closed_trade_count` in the rehearsal-count test). The count test asserts the five `Exclusions` field names, so a new `excluded` key reds it.

**The list with rehearsal rows and the figures** (design §§ C, D, E, G)

- [x] 9p.4.15 RED `backend/tests/performance/application/test_read_strategy_trades.py`, new tests, with the stub parameter `include_rehearsal: bool = False` (accepted and ignored) on `ReadStrategyTrades.read` and `TradeItem.rehearsal: bool = False` in the same commit: `::test_include_rehearsal_lists_the_closed_rehearsal_operations_marked` (`assert 1 == 2` on the row count), `::test_a_rehearsal_only_strategy_lists_its_operations`, `::test_the_default_request_serves_no_rehearsal_row`, `::test_a_mixed_allocation_is_listed_once_from_its_real_fills_and_one_warning_names_it` (the warning names pool, strategy and allocation: `assert 0 == 1` on the WARNING count), `::test_a_real_and_a_rehearsal_operation_closing_at_the_same_instant_straddle_a_page_edge_and_each_is_served_once` (limit 1, the higher allocation id first), `::test_a_cursor_minted_without_rehearsal_rows_resumes_correctly_with_them`, `::test_a_rehearsal_operation_still_open_is_not_listed`, `::test_a_rehearsal_row_with_a_non_positive_pool_capital_is_refused_like_a_real_one`. Passing at once, each with its mutation: the default request (mutation: the parameter defaults to true), the straddle (rehearsal rows sorted after the real ones), the cursor (the cursor filter applied before the merge), the mixed test's "once" half (the mixed filter removed), the non-positive capital (`trade_return` skipped for a rehearsal row).
  - Evidence (commit `2458686`, RED and GREEN as one pair because a red commit breaks the gate). RED observed against the stub (`include_rehearsal` accepted and ignored, `TradeItem.rehearsal` always false), first failures on assertions: `assert 1 == 2` (row count), `assert [] == [UUID('...01')]` (rehearsal-only strategy), `assert None is not None` (the straddle's `next_cursor`), `assert [id2] == [id4, id2]` (the cursor test), `assert [] == [id8]` (open rehearsal beside a closed one), `assert [<class 'InvariantViolation'>, None] == [InvariantViolation, InvariantViolation]` (non-positive capital, exception captured). The mixed test first failed on its id list; I then moved its WARNING-count assertions first and did not re-run it against the stub. Passed at once: the default-request test only. **Deviation, recorded:** the straddle, cursor, open and non-positive-capital tests are listed as passing at once, but the stub ignores the parameter so each fails on it; their mutations were applied after the GREEN commit and each reds as the task says (below). Tests use a `_rehearsal_closed` helper (a `dataclasses.replace` of `_closed` output) so no existing helper was edited.
- [x] 9p.4.16 GREEN `ReadStrategyTrades.read` per design § E's sequence, steps 1 to 4: the live set through `strategy_groups`, `require_live_only` and `derive_trades` as today; only when asked, the rehearsal set through `strategy_groups` and `derive_trades` minus every allocation that also has a live group (one WARNING with the ids); merge, sort by `(closed_at, allocation_id.int)` descending, apply the cursor, slice, `next_cursor` by the look-one-past rule. `TradeItem` gains `rehearsal`. The cursor type and its wire form are unchanged.
  - Evidence (commit `2458686`). `read` follows design § E steps 1 to 4: the live set through `strategy_groups`, `require_live_only` and `derive_trades`; only when asked the rehearsal set through `strategy_groups` minus every allocation with a live group (one WARNING naming pool, strategy and the ids), then the merge, the `(closed_at, allocation_id.int)` descending sort, the cursor, the slice and the look-one-past `next_cursor`. Unresolvable-symbol ids of both sets share the one existing WARNING. Mutations seen red after the GREEN commit, each reverted with `git checkout`: the parameter defaults to true (default test and the cursor test, `assert [id1] == [id1]` lists differing); rehearsal rows sorted after the real ones (four tests, `assert ([id1], [False]) == ([id2], [True])`); the cursor applied to the live set only (straddle and cursor tests); the mixed filter removed (`assert [UUID(...)] == [UUID(...)]` on the mixed test's ids); `trade_return` skipped for a rehearsal row (`assert [InvariantViolation, None] == [InvariantViolation, InvariantViolation]`).
- [x] 9p.4.17 RED `test_read_strategy_trades.py`, new tests, with the stub fields `TradeItem.fees`, `TradeItem.figures` (both wrong: zero fees, `None` figures) in the same commit: `::test_a_row_carries_its_figures_and_fees_derived_from_its_own_fills`, `::test_the_figures_are_derived_for_the_rows_of_the_page_only` (a counter on `operation_figures`: limit 2 of 5 rows gives 2 calls), `::test_a_third_currency_fee_is_listed_and_fees_complete_is_false`, `::test_a_base_currency_fee_is_listed_and_fees_complete_stays_true`, `::test_a_figure_that_cannot_be_derived_logs_one_warning_naming_pool_strategy_allocation_and_both_markets_and_the_row_stays_listed` (`STXUSDT` and `SOLUSDT`), `::test_two_spellings_of_one_market_log_nothing`, `::test_a_side_with_no_quantity_logs_one_warning_and_the_row_stays_listed`, `::test_an_overlap_of_the_two_sides_logs_one_warning`, `::test_no_line_carries_a_price_a_payload_or_a_credential` (every record of the read is checked for ids, labels and market keys only). RED against the stub: `assert Decimal('0') == Decimal('0.63')`, `assert 0 == 1` on the WARNING count. The last test passes at once; mutation: log the groups' `repr`.
  - Evidence (commit `b661244`, RED and GREEN as one pair). RED observed against the stub (`fees` zero, `figures` None; the stub module imported the three domain functions with a temporary `noqa` so the counter test could patch `operation_figures` without an `AttributeError`, removed in the GREEN): `assert OperationFees(fees=Decimal('0'), ...) == OperationFees(fees=Decimal('0.63'), ...)`, `assert 0 == 2` (the page-only counter), `assert 0 == 1` (WARNING counts: market disagreement, side with no notional x2, overlap), `assert [False, False] == [True, True]` (two spellings: figures present). Ten tests in all, plus `::test_a_rehearsal_row_carries_the_figures_of_its_own_fills`. **Deviations, recorded:** (1) the no-quantity test is parametrized on a side with NOTIONAL zero (opening, closing), because a side with zero quantity cannot net to zero and so is never a closed row; (2) `::test_no_line_carries_...` asserts exactly two records, so it also failed on the stub (`assert 0 == 2`) instead of passing at once; it forbids a decimal point and the stored prices, fees and `Decimal`/`FillGroup` text, not bare digit runs, because a random strategy id can contain `564`. Mutation seen red after the GREEN commit: the market-disagreement WARNING logging `repr(groups)`, `assert ['564.0', '57..., 'FillGroup'] == []`.
- [x] 9p.4.18 GREEN design § E steps 5 of the sequence: for the rows of the page only, `operation_fees`, `operation_figures` and `sides_overlap` over that allocation's groups, the three WARNINGs of design § G (the unreadable side or the division, the market disagreement with its keys, the overlap), and `TradeItem` carrying `fees`, `figures`. A figure that cannot be derived is `None` together and never zero.
  - Evidence (commit `b661244`). For the rows of the page only: `operation_fees`, `operation_figures`, `sides_overlap` over that allocation's groups; `TradeItem` gains `rehearsal`, `fees`, `figures`, all without defaults. The domain answers only `None`, so `_log_underivable` tells the causes apart by `market_key` (WARNING with pool, strategy, allocation id and the market keys) and by per-side sums (WARNING naming the `opening` and/or `closing` side); a third WARNING for `sides_overlap`. Two spellings of one market log nothing. Messages carry ids, the pool label, sides and market keys only. Gate: ruff 0, mypy src 0, `tests/performance` green.
- [x] 9p.4.19 RED `test_read_strategy_trades.py`, new tests, with the stubs `RehearsalPricingSourcePort.pricing_facts(pool, strategy_id, allocation_ids)` in `performance/application/ports.py` (a fake that answers `{}`), `TradeItem.pricing: RehearsalPricing | None = None` and a second constructor argument `pricing` of `ReadStrategyTrades` in the same commit; `tests/performance/fakes.py` gains `FakePricingSource` recording each call: `::test_a_page_with_rehearsal_rows_asks_for_pricing_facts_once_with_their_ids_only` (`assert [] == [[id1, id2]]`), `::test_a_page_without_rehearsal_rows_never_asks_for_facts`, `::test_each_rehearsal_row_carries_its_classification_and_a_real_row_none`, `::test_missing_facts_read_undetermined_and_log_one_warning_naming_pool_strategy_and_allocation`, `::test_undetermined_rows_log_one_info_line_with_the_count_per_page` (one line per page, never per row, no WARNING). RED against the stub: `assert None == <RehearsalPricing.FIXED_ONE: 'FIXED_ONE'>`. The no-ask and the real-row tests pass at once; mutations: ask on every page; the classification run for every row. **Recorded edit of existing tests (a gap against design § H's "not edited", see the report):** the one-argument constructions `ReadStrategyTrades(fills)` in `test_read_strategy_trades.py` and `tests/performance/infrastructure/test_strategy_trades_integration.py` gain the second argument (`FakePricingSource()` or the real source); no assertion changes.
  - Evidence (commit `e78d5fb`, with 9p.4.20). RED observed against the stub (`RehearsalPricingSourcePort` in `ports.py`, `TradeItem.pricing = None`, a stored but unused second constructor argument): `assert [] == [(PoolKey(...), UUID(...), [id2, id3])]` (one call with the page's rehearsal ids), `assert [(id3, None)...] == [(id1, None), (id2, FIXED_ONE), (id3, ALERT)]` (as the assertion printed it), `assert [None, None, None] == [None, <RehearsalPricing.FIXED_ONE>, <RehearsalPricing.UNDETERMINED>]` (missing facts), `assert [None, None, None, None] == [None, UNDETERMINED, UNDETERMINED, FIXED_ONE]` (the INFO page). The no-ask test passed at once. Mutations seen red after the GREEN commit: the page-without-rehearsal guard removed (asks with an empty id list on every page, `assert [(PoolKey..., [])] == []`); the classification run for every row (a real row classified, several tests red, e.g. `assert 3 == 1`). **Recorded edit of existing tests:** every one-argument `ReadStrategyTrades(...)` construction in `test_read_strategy_trades.py` (36 sites, plus long lines re-wrapped for the 100-column limit) and in `tests/performance/infrastructure/test_strategy_trades_integration.py` (1 site, the real pricing source) gained the second argument and no assertion changed. **Deviations, recorded:** (1) `SqlAlchemyRehearsalPricingSource` exists as a stub returning `{}` in this commit, one task earlier than 9p.4.21, because the router builds `ReadStrategyTrades` and has to compile; (2) the rehearsal tests of 9p.4.15 to 9p.4.18 use `FakePricingSource(default=ALERT_FACTS)` so their WARNING counts are not disturbed by missing facts.
- [x] 9p.4.20 GREEN design § E's sequence, step 6, and `ReadStrategyTrades(fills, pricing)`: when the page holds a rehearsal row, ONE call of `pricing_facts` with the ids of those rows only, then `classify_rehearsal_pricing` for each; a row whose facts are missing reads `UNDETERMINED` with the WARNING; one INFO line per page with the count of `UNDETERMINED` rows. `TradeItem.pricing` is `None` on a real row.
  - Evidence (commit `e78d5fb`). `ReadStrategyTrades(fills, pricing)`; `_classify` makes ONE `pricing_facts` call with the ids of the page's rehearsal rows and none when there is no such row, classifies each with `classify_rehearsal_pricing`, reads a row with no facts as `UNDETERMINED` with one WARNING naming pool, strategy and the ids, and logs one INFO per page counting the `UNDETERMINED` rows (missing-facts rows included, a reading of design § G's "count of UNDETERMINED rows"). `TradeItem.pricing` is None on a real row. The router now builds the read with `SqlAlchemyRehearsalPricingSource(session)`.
- [x] 9p.4.21 RED `backend/tests/performance/infrastructure/test_rehearsal_pricing_source.py` (real PostgreSQL, ORM schema, real `signals` rows; fills written through the module's `_fill`/`_record`), with the stub `SqlAlchemyRehearsalPricingSource` answering `{}` in the same commit: `::test_it_answers_per_allocation_the_alerts_price_and_the_lowest_and_highest_price_of_each_side` (`assert {} == {allocation: PricingFacts(...)}`), `::test_two_opening_fills_at_different_prices_report_a_low_and_a_high`, `::test_the_alert_price_is_the_one_on_the_signal_the_reservation_names` (two signals of different prices in one strategy), `::test_an_allocation_of_another_strategy_is_not_answered`, `::test_it_issues_one_statement_for_one_id_and_for_twenty`, `::test_the_answer_is_keyed_by_allocation_whatever_the_spelling_of_each_symbol` (`STXUSDT_PERP` opening, `STXUSDT.P` closing). The other-strategy and statement-count tests pass at once; mutations: the strategy predicate removed; one statement per id.
  - Evidence (commit `fdcf34c`, RED and GREEN as one pair; real PostgreSQL, ORM schema, real `signals` rows whose price is set by an UPDATE of the signal the reservation names, because `seed_signal` fixes it at 1). RED observed against the `{}` stub: `assert {} == {UUID(...): PricingFacts(...)}`, `assert {} == {id1: ..., id2: ...}` (alert per signal), `assert [] == [UUID(...)]` (strategy, pool and spelling tests), `assert (0, 0) == (1, 20)` (the statement-count test fails on the stub rather than passing at once). The low/high test first failed on a `KeyError` and was reordered to assert the key list first. One test beyond the task: `::test_an_allocation_of_another_pool_is_not_answered`. Mutations seen red after the GREEN commit: the strategy predicate removed (`assert [id_other, ...] == [id_mine]`); the three pool predicates removed (`assert {...} == {}`; removing only the exchange left the venue and currency predicates doing the work, so all three go); one statement per id (`assert (2, 21) == (1, 1)`).
- [x] 9p.4.22 GREEN `performance/infrastructure/rehearsal_pricing_source.py`: one grouped SELECT of `ledger_entries` joined to `reservations` and `signals`, `WHERE allocation_id IN (:ids)` and the strategy and the pool, answering per `(allocation, side)` the lowest and highest `price` and the signal's `price` as `PricingFacts` (design § E). `performance/infrastructure` already imports `ReservationRow` and `LedgerEntryRow`; it adds `SignalRow`. No `signals`, `allocation` or `ledger` type crosses into `application/` or `domain/`.
  - Evidence (commit `fdcf34c`). One grouped SELECT of `ledger_entries` joined to `reservations` and `signals`, `WHERE allocation_id IN (...)` and strategy and the three pool columns, grouped by `(allocation, side, signal price)`, answering `min` and `max` of the fills' own `price`; the symbol is neither selected nor grouped. `SignalRow` is imported by the adapter only; `PricingFacts` is what crosses. An empty id list issues no statement.

**The one ledger, the integration tests and the head tests** (design § H)

- [x] 9p.4.23 Plumbing, no production change: the one fixture of design § H in `backend/tests/performance/infrastructure/conftest.py` (`operations_ledger`), built through the write path the module's helpers already use (`RecordFill`), never by the simulated exchange. For ONE strategy `S1` (allowed pair `STXUSDT`, pool `bybit/usdt-m/USDT`): a real LONG with three opening fills of different sizes and prices (opened `STXUSDT.P`, closed `STXUSDT`), a real SHORT, an open real position, an open rehearsal position, a mixed allocation (a full real round trip and a full rehearsal round trip), and four rehearsal round trips (opened `STXUSDT_PERP`, closed `STXUSDT.P`) whose signals carry an alert price: one filled at 1 against an alert of 0.4512 (`FIXED_ONE`), one filled at its alert's price with a quantity small enough that the derived average differs from the fill in its last places (`ALERT`), one filled at 1 against an alert of exactly 1 (`ALERT`), and one opened at 1 and closed at its alert's price (`FIXED_ONE`). A second strategy `S2` in the same pool holds one closed operation. `::test_the_operations_ledger_holds_what_the_design_says` passes at once; mutation: leave the mixed allocation out, see it red.
  - Evidence (commit `797677d`). `operations_ledger` in `tests/performance/infrastructure/conftest.py`, built through `RecordFill` in two halves (`build_real_operations`, then `add_rehearsal_operations`) so a test can read the reports before and after the rehearsal rows exist. Real operations open `STXUSDT.P` and close `STXUSDT`; rehearsal ones open `STXUSDT_PERP` and close `STXUSDT.P`. The small-quantity row uses an 18-place alert price and a quantity of 0.000007 so the stored notional rounds. 11 rehearsal fills in all. Two tests, both passed at once (`::test_the_operations_ledger_holds_what_the_design_says` and a second pinning the spellings and the strategies' allowed pair). Mutation seen red: the mixed allocation's two rehearsal fills left out, `assert {UUID(...)...} == {UUID(...)...}` on the rehearsal allocation ids. The tests sit in `test_operations_list_integration.py`.
- [x] 9p.4.24 Integration tests on the one ledger, `backend/tests/performance/infrastructure/test_operations_list_integration.py`, `test_operations_statement_counts.py`, and one test added to `test_strategy_trades_integration.py`. All pass at once (units 9p.4.2 to 9p.4.22 built the behaviour); each has its mutation. `::test_the_default_list_is_the_real_operations_only` (mutation: the parameter defaults to true), `::test_the_opted_in_list_adds_the_four_rehearsal_rows_with_their_classification` (`FIXED_ONE`, `ALERT`, `ALERT`, `FIXED_ONE`; mutation: the alert comparison dropped; and, separately, the derived `entry_price` compared instead of the fill's own price, which reds the small-quantity row), `::test_every_operation_reads_pair_stxusdt_and_base_currency_stx_under_every_spelling`, `::test_the_mixed_allocation_is_listed_once_as_a_real_row_and_one_warning_names_it` (mutation: the mixed filter removed), `::test_the_reports_are_identical_with_and_without_the_rehearsal_rows_in_the_ledger` (the pool report, the strategy report, the curve, the monthly grid, the ranges and by-pair, the ledger built twice in the module with and without its rehearsal rows; mutation: concatenate the two sets), `::test_the_rehearsal_fill_count_still_counts_every_rehearsal_fill`, `::test_the_cursor_pages_across_both_kinds_exactly_once` (mutation: rehearsal rows sorted after the real ones), `::test_a_trade_closing_between_two_page_reads_neither_repeats_nor_hides_any_with_rehearsal_rows_in_the_fixture` (the existing concurrency property, kept green), `::test_the_list_issues_the_same_number_of_statements_for_a_page_of_one_row_and_of_twenty_and_one_more_when_the_page_holds_a_rehearsal_row` (a `before_cursor_execute` listener, the pattern of `tests/accounts/infrastructure/test_trade_capability_adapter.py`; mutation: the pricing facts read once per row), `::test_a_strategys_list_never_contains_another_strategys_operation` (S2's operation absent).
  - Evidence (commit `7a056b3`; every test passed at once). `test_operations_list_integration.py` (the ledger tests of 9p.4.23 plus nine), `test_operations_statement_counts.py` (one test; 20 extra older real operations fill a page of twenty), and one test in `test_strategy_trades_integration.py` (the existing property, on the one ledger, with a trade closing between two page reads). The report-identity test builds the real half, reads, adds the rehearsal rows to the same database and reads again; only `rehearsal_fill_count` is normalised (0 before, 11 after), and it asserts the before-state is not vacuous (4 pool trades, 3 strategy trades). Mutations seen red after the commit, each reverted: the parameter defaults to true (the default-list test); the alert comparison dropped (the classification test); the fills' derived `notional / quantity` compared instead of their own price (the classification test, the small-quantity row); the mixed filter removed (four tests, e.g. `assert 8 == 7`); rehearsal rows sorted after the real ones (classification and cursor-walk tests); the pricing facts read once per row (`assert 6 == (2 + 1)` in the statement-count test); the read concatenating `groups` and `rehearsal_groups` in `ReadPoolPerformance` and, separately, in `ReadStrategyPerformance` (`assert PoolPerforman... == PoolPerforman...`). The concurrency test and the other-strategy test carry no mutation of their own: the first is the existing property kept green, the second is covered by 9p.4.21's strategy-predicate mutation.
- [x] 9p.4.25 `head` schema, `backend/tests/performance/infrastructure/test_ledger_head_constraints.py`, using `tests/pg_head_schema.py` and saying why in its docstring (the premise of design § G and T6, T17): `::test_a_non_positive_price_quantity_or_notional_cannot_be_stored` (parametrized over the three columns and over zero and a negative value; each insert raises the check violation of migration 0005), `::test_ix_ledger_allocation_exists_on_ledger_entries_allocation_id` (read from `pg_indexes`, never from a plan). Both pass at once; mutation for both: build the database with `Base.metadata.create_all` instead of alembic (the ORM schema has neither the CHECK nor the index) and see both red.
  - Evidence (commit `cd404d3`; passed at once, 8 tests: a positive control, the six parametrized refusals asserting the constraint name `ck_ledger_entries_<column>_positive`, and the index from `pg_indexes`). Mutation seen red: the head database swapped for one built with `Base.metadata.create_all` (plus the seeded pool the FK needs), six times `Failed: DID NOT RAISE IntegrityError` and `assert 0 == 1` on the index count.

**The fills read** (design §§ D, E, G)

- [x] 9p.4.26 RED `backend/tests/performance/application/test_read_operation_fills.py`, with stubs in the same commit: `OperationFill` in `performance/domain/operation.py` (instant, side, price, quantity, fee, fee currency, rehearsal flag, and the pool identity for the check), `OperationFillsSourcePort.operation_fills(strategy_id, allocation_id, limit)` in `ports.py` (consumer-declared, takes the strategy AND the allocation), `ReadOperationFills(source).read(strategy_id, pool, allocation_id)` in `performance/application/read_operation_fills.py` answering an empty, untruncated result, `OperationFills`, `UnknownOperation`, `MAX_OPERATION_FILLS = 200`. A fake source. Tests: `::test_it_asks_the_source_for_the_cap_plus_one` (`assert 0 == 201`), `::test_201_fills_answer_200_truncated_and_one_warning_naming_strategy_allocation_and_the_cap`, `::test_exactly_200_fills_are_not_truncated_and_log_nothing`, `::test_an_empty_answer_raises_unknown_operation_and_logs_one_warning` (the exception captured: `assert NoneType is UnknownOperation`), `::test_a_fill_of_another_pool_is_refused_as_an_invariant_violation_and_nothing_is_returned`, `::test_a_mixed_allocation_returns_every_fill_each_with_its_own_flag_and_one_warning`, `::test_the_source_is_called_with_the_strategy_and_the_allocation_together`, `::test_the_ports_module_imports_no_type_of_another_module`, `::test_no_line_carries_a_price_a_quantity_or_a_fee`. RED against the stub: `assert [] == [OperationFill(...), ...]`. The last two pass at once; mutations: import a `ledger` type into `ports.py`; log the fills. Cap mutations: the cap removed (the 201 test); `limit` asked as 200 (the first test).
  - Evidence (commit `beb5a83`, RED and GREEN as one pair because a red commit breaks the gate). RED observed against the stub (an empty, untruncated answer; `OperationFill`, `OperationFillsSourcePort`, `ReadOperationFills`, `OperationFills`, `UnknownOperation` and `MAX_OPERATION_FILLS` all existed), first failures on assertions: `assert [] == [201]` (the limit asked, recorded by the fake), `assert (0, False) == (200, True)`, `assert (0, False) == (200, False)`, `assert <class 'NoneType'> is UnknownOperation`, `assert <class 'NoneType'> is InvariantViolation` (three parametrized pools: exchange, venue, settlement currency; exceptions captured, types asserted) and `assert [] == [False, False, True, True]`. The 'no line carries a price' test failed on the stub with `Failed: DID NOT RAISE UnknownOperation` (a `pytest.raises` inside it) rather than on its own assertion. Passed at once: the ports-module test and the wholly-one-origin-logs-nothing test. **Deviation, recorded:** the fake source is `FakeOperationFillsSource` in `tests/performance/fakes.py`, keyed by `(strategy_id, allocation_id)`; the ports test forbids `signals`, `execution`, `ledger` and `reconciliation` modules and any `.infrastructure` module (not `allocation`: `ports.py` already imports `PoolKey` from it). Mutations seen red after the GREEN commit, each reverted with `git checkout`: a `ledger` import added to `ports.py` (`assert ['strategy_manager.ledger...'] == []`); the fills logged (`assert 5 == 3` on the record count, five tests red); the cap removed (`assert (201, True) == (200, True)`); `limit` asked as 200 (`assert [200] == [201]`).
- [x] 9p.4.27 GREEN `ReadOperationFills`: asks for `limit + 1`, serves the first 200 with `truncated` when it got 201, raises `UnknownOperation` on an empty answer (one WARNING with strategy and allocation), refuses a fill of another pool with `InvariantViolation` AFTER the read and never in a WHERE (design § D, D20), logs the truncation and the mixed case, derives nothing and needs no `base_currency_of`. It takes no lock and writes nothing.
  - Evidence (commit `beb5a83`). `ReadOperationFills.read` asks the source for `limit + 1` with the strategy and the allocation together, raises `UnknownOperation` on an empty answer with one WARNING (strategy id, allocation id), refuses a fill of another pool with `InvariantViolation` after the read (never in a WHERE), serves the first 200 with `truncated` and one WARNING (ids and the cap) when it got 201, and logs one WARNING for a mixed allocation. It derives nothing, takes no lock and writes nothing. The cap check and the mixed check run on the fills served, the pool check on every fill got. All 14 tests of the file green.
- [x] 9p.4.28 RED `backend/tests/performance/infrastructure/test_operation_fills_source.py` (real PostgreSQL, ORM schema, the one ledger), with the stub `SqlAlchemyOperationFillsSource` answering `[]` in the same commit: `::test_the_fills_come_in_filled_at_then_id_order` (the later fill inserted first; mutation: the ORDER BY removed), `::test_the_fills_of_both_spellings_are_returned` (`STXUSDT_PERP` and `STXUSDT.P`), `::test_each_fills_rehearsal_flag_comes_from_its_own_fill_id` (the mixed allocation; mutation: the flag taken from the operation), `::test_another_strategys_allocation_returns_nothing` (S1 asks for S2's allocation; mutation: the `strategy_id` predicate removed), `::test_the_limit_is_applied_in_sql` (201 rows when asked for 201, 3 when asked for 3), `::test_it_issues_one_statement_for_one_fill_and_for_fifty` (mutation: a lookup per fill), `::test_an_open_allocations_fill_is_returned`. RED against the stub: `assert [] == [OperationFill(...), OperationFill(...)]`. The other-strategy, statement-count and open tests pass at once.
  - Evidence (commit `efa1065`, RED and GREEN as one pair). RED observed against the stub that answers `[]` (real PostgreSQL, ORM schema, the one `operations_ledger`), first failures on assertions: `assert [] == [('BUY', ...), ('SELL', ...)]` (the order test, the later fill inserted first), `assert [] == ['BUY', 'SELL']` (both spellings), `assert [] == [False, False, True, True]` (the mixed allocation), `assert 0 == 2` (S2 reading its own allocation), `assert (0, 0) == (201, 3)` (the limit), `assert [(0, 0), (0, 0)] == [(1, 1), (50, 1)]` (statement count), `assert [] == [('BUY', False)]` (open). The stored-values test first failed on `ValueError: not enough values to unpack`; it was changed to `assert len(fills) == 1` and then failed on `assert 0 == 1`. **Deviations, recorded:** the other-strategy, statement-count and open tests failed on the stub instead of passing at once (the stub issues no statement and answers nothing); two tests are beyond the task (a fill carries its stored values, upper-cased fee currency and pool; a tie on `filled_at` answers in ascending row-id order: first written as a repeatability check, which passed with the ORDER BY removed, then strengthened in commit `c900c19` to read the ids from the table and compare the quantities in id order; with `LedgerEntryRow.id` removed from the `order_by` it went red twice, `assert [Decimal('1.0...')] == [Decimal('3.0...')]` and `assert [Decimal('1.0...')] == [Decimal('5.0...')]`, and the mutation was reverted). Mutations seen red after the GREEN commit: the ORDER BY removed (`assert [('SELL', ...)] == [('BUY', ...)]`); the flag fixed to true (`assert [True, True, True, True] == [False, False, True, True]`); the strategy predicate removed (`assert [OperationFill(...)] == []`); the limit ignored (`assert (205, 205) == (201, 3)`); a lookup per fill (`assert [(1, 2), (50, 51)] == [(1, 1), (50, 1)]`).
- [x] 9p.4.29 GREEN `performance/infrastructure/operation_fills_source.py`: one SELECT on `ledger_entries`, `WHERE allocation_id = :a AND strategy_id = :s ORDER BY filled_at, id LIMIT :n`, no join (design § E); the strategy predicate is in the statement, not in the application.
  - Evidence (commit `efa1065`). One SELECT on `ledger_entries`, `WHERE allocation_id = :a AND strategy_id = :s ORDER BY filled_at, id LIMIT :n`, no join, no pool predicate. The rehearsal flag is the labelled prefix expression of the aggregate (`startswith(..., autoescape=True)`), taken per fill; the fee currency is upper-cased. One statement for one fill and for fifty.

**The wire and the routes** (design § D)

- [x] 9p.4.30 RED `backend/tests/shared/infrastructure/test_wire_price.py`, with the stub `Price = Money` in `shared/infrastructure/wire.py` in the same commit: `::test_a_price_is_rounded_half_even_to_18_places_in_plain_notation`, `::test_a_price_is_never_written_with_an_exponent`, `::test_half_even_decides_at_the_nineteenth_place` (a tie goes to the even digit). RED against `Money`: `assert '0.4512' == '0.451200000000000000'` or the rounding value. The exponent test may pass at once; mutation: a bare `str(Decimal)`.
  - Evidence (commit `a77c171`, RED and GREEN as one pair). RED observed against `Price = Money`, first failures on assertions: `assert '0.4512' == '0.451200000000000000'`, `assert '1' == '1.000000000000000000'`, `assert '0.4512345678901234567891' == '0.451234567890123457'`, `assert '0.0000000000000000005' == '0.000000000000000000'` (and the three other ties), the 2/3 and 1/3 quotients and a 30-digit integer part. The exponent test (eight values) passed at once. **Deviation, recorded:** two of my first above/below-the-tie values were written with one place too few, so they failed after the GREEN as well; the values were corrected (`0.000000000000000000501` and `...499`) before the commit. Mutation seen red after the GREEN commit: `str(...)` instead of `plain(...)` in `price()` reds the exponent test (`assert '4E-18' == '0.000000000000000004'` and the value `1E-18`, `0E-18`, `-0E-18`), and a bare `str(value)` reds the rounding tests.
- [x] 9p.4.31 GREEN `Price`: a third annotated type beside `Money` and `Ratio`, rounds half-even to 18 places and writes plain notation (design § B, D4).
  - Evidence (commit `a77c171`). `Price` is a third annotated type beside `Money` and `Ratio`: it quantizes half-even to `1e-18` in a context of 80 digits, so the rounding cannot raise, and writes plain notation (a tiny negative rounds to a zero written without a sign). The module docstring describes it.
- [x] 9p.4.32 RED `backend/tests/performance/infrastructure/test_operations_router.py` (real PostgreSQL through the module's `client` pattern, the one ledger), with the stub in the same commit: `TradeBody` gains the eight fields filled with constants (`rehearsal` false, `rehearsal_fill_price` null, the four figures null, `fees` `"0"`, `other_fees` `[]`) and the route accepts `include_rehearsal` and ignores it. Tests: `::test_a_closed_real_operation_carries_every_new_field` (`pair` `"STXUSDT"`, `base_currency` `"STX"`, `entry_price` `"0.451200000000000000"`, `exit_price` `"0.463100000000000000"`, `size` `"1250.000000000000000000"`, `fees` `"0.630000000000000000"`, `other_fees` `[]`, `pnl` `"14.245000000000000000"`: `assert '0' == '0.630000000000000000'`), `::test_a_fee_in_another_currency_is_listed_with_its_own_currency` (`binance/usdt-m/USDT`, `[{"currency": "BNB", "amount": "0.000120000000000000"}]`, `fees_complete` false), `::test_figures_that_cannot_be_derived_are_null_together_and_the_row_is_served`, `::test_the_default_request_holds_no_rehearsal_row_and_every_row_says_rehearsal_false`, `::test_the_opted_in_request_holds_both_kinds_marked_and_the_classification_is_null_exactly_on_a_real_row`, `::test_a_fixed_price_row_is_served_with_entry_one_and_pnl_zero_and_fixed_one` (`"1.000000000000000000"`, `"0.000000000000000000"`), `::test_a_strategy_that_only_ran_in_dry_run_lists_its_operations_while_its_report_shows_zero`, `::test_the_cursor_pages_across_both_kinds_exactly_once_with_a_limit_of_two` (3 real and 2 rehearsal; `next_cursor` null on the last page only), `::test_include_rehearsal_that_is_not_a_boolean_is_422`, `::test_the_existing_refusals_are_unchanged` (404 `no such strategy`, 422 for half a cursor, 422 for a naive `before_closed_at`, 422 for `limit=201`), `::test_a_source_that_puts_a_rehearsal_group_in_the_live_set_is_a_500_and_one_logged_error` (the twin of `test_a_source_that_returns_another_pools_rows_is_a_500_and_one_logged_error`), `::test_a_rehearsal_row_with_a_non_positive_capital_is_the_existing_500`. RED on the stub's constants. The refusals test passes at once; mutation: `include_rehearsal` made required.
  - Evidence (commit `398a39d`, RED and GREEN as one pair). RED observed against the stub (`TradeBody` with the eight constant fields, `include_rehearsal` accepted and ignored), first failures on assertions: the whole-row equality of the real LONG (`assert {...} == {...}`), `assert ('SHORT', None, None, None) == ('SHORT', '0.5...', ...)`, `assert [] == [{'currency': 'BNB', ...}]`, `assert [...] == [...]` on the ids of the opted-in list and of the cursor walk, `assert [] == ['...']` for the dry-run-only strategy, and `assert 200 == 500` for the non-positive capital. Passed at once, as the task says: the default request, the 422 for a non-boolean, the existing refusals, and the rehearsal-group-in-the-live-set 500 (the existing wall). **Deviations, recorded:** (1) the task's numbers (entry 0.4512, fees 0.63) are not the one ledger's; the assertions use the ledger's own (the real LONG: entry 0.448 weighted by quantity, exit 0.5, size 1000, fees 0.4, PnL 51.6; the SHORT: entry 0.5, exit 0.45, fees 0.1, PnL 9.9). (2) The fee-in-another-currency test runs on the seeded `bybit/usdt-m/USDT` pool, because the `binance/usdt-m/USDT` pool is not seeded in the ORM schema (the foreign key `fk_strategies_capital_pool` refuses the strategy); the property tested is the fee's currency, not the pool. A strategy with no fee in the settlement currency serves `fees` as `"0"` (a sum of nothing), not an 18-place zero, so that test compares `Decimal`. (3) The cursor test walks 3 real and 4 rehearsal closed operations in pages of 2 (2, 2, 2, 1; `next_cursor` null on the last page only). (4) **An existing test is edited:** `tests/performance/infrastructure/test_performance_router.py::test_get_strategy_trades_item_shape_and_direction` asserted the whole nine-key row, so adding the eight keys necessarily changes its expectation; it now expects the eight additive keys (`rehearsal` false, `rehearsal_fill_price` null, `base_currency` STX, entry 100, exit 94, size 1, fees 0, `other_fees` empty) and every old assertion is kept, none relaxed. The task did not list this edit. Mutations seen red after the GREEN commit: `include_rehearsal` required (the default-request tests and `assert (422, {...}) == (404, {'detail': 'no such strategy'})`); defaulting to true (`assert [...] == [...]`, `assert ['...'] == []`); the parameter not passed to the read (four tests red); `require_live_only` removed from the read (`assert 200 == 500` on the live-set test).
- [x] 9p.4.33 GREEN in `performance_router.py`: `TradeBody` with `rehearsal`, `rehearsal_fill_price`, `base_currency`, `entry_price` and `exit_price` (`Price`), `size` (`Money`), `fees` (`Money`), `other_fees` (a list of `{currency, amount}`); `TradeBody.of` over the new `TradeItem`; the `include_rehearsal` query parameter, default false; a `get_pricing_source` dependency beside `get_fills_source`; `ReadStrategyTrades(fills, pricing)`. The four nullable figures are null together or not at all. The route still requires the bearer token through the router's own dependency.
  - Evidence (commit `398a39d`). `TradeBody` serves `rehearsal`, `rehearsal_fill_price`, `base_currency`, `entry_price` and `exit_price` (`Price`), `size` and `fees` (`Money`) and `other_fees` (`[{currency, amount}]`), built from the item's own fees, figures and pricing; the four figures are null together by construction (one `figures` object). `include_rehearsal` is a query parameter defaulting to false; `get_pricing_source` sits beside `get_fills_source`; `ReadStrategyTrades(fills, pricing)`. The router still carries the bearer dependency. The module docstring of `read_strategy_trades.py` now describes rehearsal rows, the page-only figures and the pricing classification, and the router's names the new fields.
- [x] 9p.4.34 RED `test_operations_router.py`, fills route, with the stub route in the same commit (`GET /api/performance/strategies/{strategy_id}/trades/{allocation_id}/fills` answering 200 with an empty `fills` and `truncated` false for any id): `::test_the_fills_of_a_closed_operation_are_served_in_order` (the first fill `{"side": "BUY", "price": "0.451200000000000000", "quantity": "1250.000000000000000000", "fee": "0.310000000000000000", "fee_currency": "USDT", "rehearsal": false}`: `assert [] == [{...}, {...}]`), `::test_a_rehearsal_operations_fills_are_served_without_an_opt_in_each_flagged_true`, `::test_a_mixed_allocation_answers_every_fill_with_its_own_flag`, `::test_the_fills_of_both_spellings_of_the_symbol_are_in_the_answer`, `::test_more_than_200_fills_are_cut_and_flagged_and_exactly_200_are_not` (201 and 200 seeded), `::test_an_unknown_id_another_strategys_operation_and_an_empty_one_answer_the_same_404_and_the_same_body` (parametrized over a random UUID, S2's allocation and a reservation of S1 with no fill; the body is `{"detail": "no such operation"}` and no fill of S2 is in any body), `::test_an_unknown_strategy_is_a_different_404` (`no such strategy`), `::test_an_allocation_id_that_is_not_a_uuid_is_422`, `::test_a_fill_in_another_pool_is_500_with_the_integrity_detail_and_no_fill_and_one_error`, `::test_an_open_allocations_fills_are_served`, `::test_the_body_carries_exactly_the_documented_keys` (no USD rate, venue order or fill id, notional or symbol), `::test_the_404s_log_one_warning_naming_strategy_and_allocation`, `::test_the_route_issues_the_same_number_of_statements_for_one_fill_and_for_fifty`. RED on the stub's empty list and the missing 404. Passing at once, each with its mutation: the 404 body test (the `strategy_id` predicate removed from the SQL, S1 reads S2's allocation), the key-set test (a `notional` key added), the statement count (a lookup per fill), the 200 cut (the cap removed; and, separately, `LIMIT 200` instead of 201, the flag never turning true).
  - Evidence (commit `58ef460`, RED and GREEN as one pair). RED observed against the stub route (200, empty `fills`, `truncated` false for any id; `FillBody`, `OperationFillsBody` and `get_operation_fills_source` existed), first failures on assertions: `assert {...} == {...}` (the closed operation), `assert [] == [('BUY', True), ('SELL', True)]`, `assert [] == ['BUY', 'BUY', 'BUY', 'SELL']`, `assert (0, False) == (200, False)`, `assert {'unknown': (200, ...)} == {'unknown': (404, ...)}`, `assert (200, {...}) == (404, {'detail': 'no such strategy'})`, `assert 0 == 2` (the statement count), `assert 200 == 404`, `assert 0 == 1`. **Deviations, recorded:** the 404-body, key-set, statement-count and cap tests failed on the stub instead of passing at once (it answers 200 and issues no statement); the 404 test also reads S2's own answer, so it is the predicate and not an empty ledger; the foreign-pool 500 overrides `get_operation_fills_source` with the fake. Mutations seen red after the GREEN commit: the `strategy_id` predicate removed (`assert {'unknown': ...} == {...}` on the 404 test, S1 reads S2's allocation); a `notional` key added (the key-set test and the whole-body test); the cap removed (`assert (201, True) == (200, True)`); `LIMIT 200` (`assert (200, False) == (200, True)`); a lookup per fill (`assert [3, 52] == [2, 2]`).
- [x] 9p.4.35 GREEN in `performance_router.py`: `FillBody`, `OperationFillsBody` (`allocation_id` the id asked for, `fills` never empty, `truncated`), the fills route resolving the strategy's pool with the existing `_strategy_pool` (the 404 `no such strategy`), `ReadOperationFills` through `_guarded`, `UnknownOperation` mapped to the 404 `{"detail": "no such operation"}`, a `get_operation_fills_source` dependency. `price`, `quantity` and `fee` are written with the existing `Money` type: nothing is averaged or rounded.
  - Evidence (commit `58ef460`). `FillBody` and `OperationFillsBody` (`allocation_id` the id asked for, `fills`, `truncated`); the route resolves the pool with `_strategy_pool` (the 404 `no such strategy`), reads through `_guarded`, maps `UnknownOperation` to the 404 `{"detail": "no such operation"}` (one body for an unknown, a foreign and an empty allocation, and one WARNING with strategy and allocation ids); `get_operation_fills_source` is a dependency. `price`, `quantity` and `fee` use `Money`: nothing averaged or rounded. `side` is cast to the literal and pydantic refuses any other value at runtime. The route count: the strategy row and the one SELECT, two statements for one fill and for fifty.
- [x] 9p.4.36 Auth and the sweeps (design § G, threat matrix; both rows). The router's own dependency already covers the new routes; the hand-written URL list of `test_get_pool_performance_requires_bearer_token` is NOT modified (no assertion relaxed, nothing added to it). Instead `test_operations_router.py::test_the_trades_and_fills_routes_require_the_bearer_token` (401 for a missing and a wrong token, 404 for the pre-`/api` path) passes at once; mutation: declare the fills route on a bare `APIRouter`. `::test_no_trades_or_fills_response_contains_a_json_float_or_an_exponent` walks every response of both routes over the one ledger (the walk of `test_no_response_contains_a_json_float_and_every_decimal_is_a_plain_string`, reused through its `_walk`); mutation: a bare `str(Decimal)` in `Price`. **Recorded edit of an existing test:** `backend/tests/signals/infrastructure/test_webhook_secret_router.py`, `_concrete_path` gives `{allocation_id}` a random UUID, so the new GET answers 404 and the sweep fails on "seed the data it needs"; the sweep is taught the allocation id of the trade it already seeds with `_trade` (which returns it), exactly as PR 12v-2 taught it its route; its assertions stay as they are, and `::test_the_route_table_walk_finds_the_routes_it_is_meant_to_cover` gains the new route in its `assert (...) in OTHER_API_ROUTES` list. The existing `::test_every_registered_route_refuses_a_request_without_a_token` of `tests/strategies/infrastructure/test_router_auth.py` is unmodified (it reads the strategies router only) and is run to confirm.
  - Evidence (commits `4632915` and `96b606a`). Passed at once, as the task says: `::test_the_trades_and_fills_routes_require_the_bearer_token` (the list, the list opted in and the fills route; 401 for a missing and a wrong token, the 404 for the pre-`/api` path, 200 admitted) and `::test_no_trades_or_fills_response_contains_a_json_float_or_an_exponent` (the list, opted in, paged by two, and the fills of ten operations: more than 300 leaves and 100 numbers walked). Mutations seen red: the router's `dependencies=[Depends(require_admin_token)]` dropped (`assert /api/performance/.../trades` red on the 401), and, as the task names it, the fills route declared on a bare `APIRouter` and included into `router` (red on the fills URL: FastAPI does NOT re-apply the parent's dependencies to an included router, so the sweep is what proves them). **Deviation, recorded:** the first commit's walk did NOT go red under a bare `str(Decimal)` in `Price` (`pytest` exit 0): no price of the one ledger is small enough to be written with an exponent. The walk now seeds one operation at a micro price (5E-7 and 6E-7) and pins its prices as `0.000000500000000000` and `0.000000600000000000`; with that, the mutation reds it (`assert ('5.00000000...E-7') == ('0.000000500...')`). **Recorded edit of an existing test:** `tests/signals/infrastructure/test_webhook_secret_router.py`, `_concrete_path` takes the allocation id of the trade the sweep already seeds (`_trade` returns it) for `{allocation_id}`, and `::test_the_route_table_walk_finds_the_routes_it_is_meant_to_cover` expects the new route; no assertion of the sweep changed. Before that edit the sweep failed with `GET /api/performance/strategies/{strategy_id}/trades/{allocation_id}/fills answered 404; seed the data it needs`, so the gate was red for that one case between commit `58ef460` and `4632915`. The hand-written URL list of `test_get_pool_performance_requires_bearer_token` is untouched, and `tests/strategies/infrastructure/test_router_auth.py` passes unmodified in the full run.
- [x] 9p.4.37 Confirm and gate: run `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`. Record that no existing test was edited beyond the three recorded edits (the builders, the `ReadStrategyTrades` constructor argument, the sweep), that the existing tests of the list, the reports, the curve, the ranges, the grid and by-pair pass unmodified, and the statement counts observed (the list's three statements and the fourth, the fills route's two). A backend suite on this machine prints no summary line: confirm by exit code and by summing `uv run pytest --co -q`.
  - Evidence (observed after commit `96b606a`). `cd backend && uv run ruff check .`: exit 0, all checks passed. `uv run mypy src`: exit 0, no issues in 284 source files. `uv run pytest --tb=short`: exit 0, 3160 passed in 281.70s (this shell printed the summary line this time). `uv run pytest --co -q` per-file counts sum to 3160 (3,085 before this batch, 3,034 before batch 2, 2,992 before batch 1: +75 in this batch). Existing tests edited in this batch: two, both recorded above (the item-shape test of `test_performance_router.py` under 9p.4.32, which the task did not list, and the secret sweep under 9p.4.36); the `FillGroup` builders and the `ReadStrategyTrades` constructor argument were batches 1 and 2. The existing tests of the list, the reports, the curve, the ranges, the grid and by-pair pass unmodified. Statement counts observed: the list issues the same number for a page of 1 and of 20 rows and exactly one more when the page holds a rehearsal row (asserted relative, in `test_operations_statement_counts.py`); the fills route issues two (the strategy row and the one SELECT) for one fill and for fifty.
- [x] 9p.4.38 Owner step, after the merge: deploy 12e-1. `sudo -u strategy -H git -C /opt/strategy-manager/app pull --ff-only`, then `systemctl restart strategy-api strategy-worker`. No migration, so no rehearsal and no `alembic upgrade`. Then a read-only check at the owner's choice: `GET /api/performance/strategies/{id}/trades?limit=3` answers rows with the eight new fields and no rehearsal row, and the same with `&include_rehearsal=true` lists the strategy's dry-run operations as production holds them once decision 45 (PR 12g, deployed before this PR) is live: rows whose fills were all written before decision 45 read `FIXED_ONE` with entry 1, exit 1, fees 0 and PnL 0; rows opened after it read `ALERT` with the alert's price and a fee; a position that straddles it reads `FIXED_ONE` with an exit at the alert's price and a non-zero PnL. The admin token is never pasted into a chat or a log. Update the delivery log after the merge (the standing working agreement; this list writes no entry).

  - Evidence. PR #60 merged 2026-10-05 02:51 UTC, merge commit `845f02a` (two parents, checked with `git rev-list --parents`). The owner reported the pull as `strategy`, the restart of both services and both services active. The read-only check of the list was not reported, so it is not recorded as done. The delivery log has the entry.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: fakes and `caplog` for the application units; real PostgreSQL on the ORM schema for the source, the two new adapters, the list end to end and both routes; real PostgreSQL migrated to `head` for the two constraint and index tests only.
Rollback boundary: three independent revert points. (1) The figures, the rehearsal split and the list parameter (9p.4.1 to 9p.4.25, 9p.4.30 to 9p.4.33): a revert restores the nine-field row. (2) The fills read (9p.4.26 to 9p.4.29, 9p.4.34, 9p.4.35): a revert removes the route and its path answers 404. (3) The sweep teaching (9p.4.36) goes with (2). No data is touched; there is no migration.
Forecast: 3,600–5,200 changed lines (design § I forecasts 1,500–2,200). Derived bottom-up: about 900 of production code (`operation.py` 220, the source and `PoolFills` 90, `scope` 20, `ReadStrategyTrades` 130, `ReadOperationFills` 90, the two adapters 130, the router 170, `Price` 30, plus the `FillGroup` plumbing), and tests at four times that, because in this change the test files have roughly doubled every earlier forecast (unit 9p's first forecast was low six-fold; 12x-3 was 1,627 against 550–800): the domain tests about 650, the list read units about 650, the fills read units 250, the two adapters' integration tests 550, the one fixture 250, the list integration and statement counts 450, the head tests 80, the router tests about 800, `Price` 70, fakes and sweeps 150. Information only.

### Unit 9p.5 — operations: columns, marks, detail dialog and fills table (panel) (2,400–3,600 lines) — PR 12e-2

**Needs**: PR 12e-1 merged AND deployed. The panel refuses a page that lacks the new fields and reads a
route that must exist (design § D). Not decision 45, not unit 9d.

**Files**:
Modify `frontend/src/shared/api/types.ts`, `frontend/src/shared/api/performance.ts`,
`frontend/src/features/strategies/{TradesTable,StrategyDetailPage,format}.ts(x)`,
`frontend/src/shared/i18n/locales/{en,es}.json` (under `strategies.performance.trades`).
Create `frontend/src/features/strategies/{TradeDetailDialog,OperationFillsTable}.tsx`.
Create `frontend/src/shared/api/{performance.operations,performance.fills}.test.ts`,
`frontend/src/features/strategies/{format,TradeDetailDialog,OperationFillsTable}.test.ts(x)`.
Modify `frontend/src/features/strategies/{TradesTable,StrategyDetailPage}.test.tsx` and
`frontend/src/shared/api/performance.strategy.test.ts` (the recorded edits only).

- [x] 9p.5.1 Plumbing, no behaviour change: `types.ts` — `StrategyTrade` gains `rehearsal: boolean`, `rehearsal_fill_price: string | null`, `base_currency: string | null`, `entry_price: string | null`, `exit_price: string | null`, `size: string | null`, `fees: string`, `other_fees: { currency: string; amount: string }[]`; new `OperationFill` (`filled_at`, `side`, `price`, `quantity`, `fee`, `fee_currency`, `rehearsal`) and `OperationFills` (`allocation_id`, `fills`, `truncated`). The trade builders of `TradesTable.test.tsx::trade()`, `StrategyDetailPage.test.tsx`, `performance.strategy.test.ts` and any other fixture that types a `StrategyTrade` gain the new fields (a real, non-rehearsal row: `rehearsal: false`, `rehearsal_fill_price: null`, the figures present, `fees: "0.63"`, `other_fees: []`); nothing else in those files changes. `npm run lint` passes; the existing suites pass unmodified apart from this. No RED. **Done (011aaff).** Builders of `TradesTable.test.tsx::trade()`, `StrategyDetailPage.test.tsx` and `performance.strategy.test.ts` gained the eight fields; no other line of those files changed. Gate before: 44 files, 655 tests; after: lint clean, 44 files, 655 tests, unmodified apart from the builders.
- [x] 9p.5.2 RED `frontend/src/shared/api/performance.operations.test.ts` (Create), `vi.stubGlobal("fetch")`: `::refuses a page whose row lacks <field>` for each of `rehearsal`, `rehearsal_fill_price`, `fees`, `other_fees`, `entry_price`, `exit_price`, `size`, `base_currency` (one case per field); `::refuses a number where a string is due` for each of `fees`, `size`, `entry_price`, `exit_price`, `base_currency` and an `other_fees` amount; `::refuses a rehearsal row whose rehearsal_fill_price is null`, `::refuses a real row whose rehearsal_fill_price is set`; `::refuses a page of the original nine fields`; `::accepts a rehearsal row whose rehearsal_fill_price is a value the panel does not know` (`"SLIPPED"`); `::accepts a row whose four figures are all null`; `::sends include_rehearsal=true on the first page and on every later page, with the limit and the cursor`. RED: the current check ignores unknown keys, so each refusal test fails on `promise resolved instead of rejecting` and the query test on `expected null to be 'true'`. The two accept tests pass at once; mutations: the `rehearsal_fill_price` known-value list made closed (reds the "SLIPPED" test); the `entry_price` check removed (reds the null-figures test's twin). The existing `performance.strategy.test.ts::asks for the first page with the limit alone and no cursor` asserts the query with the limit alone: **recorded edit**, renamed to `::asks for the first page with the limit and include_rehearsal and no cursor`, the old expectation replaced, not deleted. **Done (7c3961f, RED).** Failed on `promise resolved "{ trades: [ { …(16) } ], …(1) }" instead of rejecting` (every refusal, 8 + 6 + 3 cases) and `expected null to be 'true'` (the query tests, new and renamed). The two accept tests passed at once. Recorded edit: `performance.strategy.test.ts::asks for the first page with the limit alone and no cursor` renamed `::asks for the first page with the limit and include_rehearsal and no cursor`, the limit and cursor expectations kept and the `include_rehearsal` one added (its RED is the same `expected null to be 'true'`). Mutations seen after the GREEN commit: the known-value list of `rehearsal_fill_price` closed reds `accepts a rehearsal row whose rehearsal_fill_price is a value the panel does not know` ("Unexpected response shape"); `entry_price` narrowed to string-only (a check that rejects null; removing it outright cannot red an accept test) reds `accepts a row whose four figures are all null`. Both reverted, never committed.
- [x] 9p.5.3 GREEN `performance.ts`: `isTrade` checks every field of design § D by type, in the nine-name check plus the eight new ones; `rehearsal_fill_price` must be null exactly when `rehearsal` is false and, on a rehearsal row, any string (an unknown value is kept; the table reads it as the plain tag); a page with one bad row is refused whole (the existing throw). `fetchStrategyTrades` always sets `include_rehearsal=true`. No request shape other than the added parameter changes. **Done (91c95e6).** `isTrade` checks the eight fields; `rehearsal_fill_price` null exactly when `rehearsal` is false, any string on a rehearsal row; `fetchStrategyTrades` always sends `include_rehearsal=true`. All 20 + 1 tests of the two API files green; lint clean.
- [x] 9p.5.4 RED `frontend/src/shared/api/performance.fills.test.ts` (Create), with the stubs `fetchOperationFills` (answers `{ allocation_id, fills: [], truncated: false }` without a request) and `useOperationFills` in `performance.ts` in the same commit: `::requests GET /performance/strategies/{id}/trades/{allocationId}/fills` (`expected undefined to be '/api/performance/strategies/.../fills'`), `::refuses a body that names another allocation than the one asked for`, `::refuses an empty list`, `::refuses a side of HOLD`, `::refuses a price that is a JSON number` (and one case each for `filled_at`, `quantity`, `fee`, `fee_currency`, `rehearsal`, `truncated`), `::keeps truncated`, `::a 404 throws`, `::the query key is ['performance','strategy',id,'trade-fills',allocationId]`, `::makes no request until the hook is mounted`. The last test passes at once (the stub makes no request); mutation: the hook enabled without its two ids. The allocation test's mutation is the `allocation_id` comparison removed. The "no fills request until an operation is opened" test of the table is 9p.5.19. **Done (236f429, RED).** Stubs `fetchOperationFills` (empty list, no request) and `useOperationFills` (wrong key) in `performance.ts`. Failed on `expected undefined to be '/api/performance/strategies/.../fills'`, `promise resolved … instead of rejecting` (allocation, empty list, HOLD, one case each for price, filled_at, quantity, fee, fee_currency, rehearsal, a missing field, truncated, one bad fill among good ones, the 404), `expected false to be true` (keeps truncated) and a deep-equal of the query key. `makes no request until the hook is mounted with both ids` passed at once; mutation after GREEN: `enabled: true` reds it (`expected "spy" to not be called at all, but actually been called 2 times`); mutation: the `allocation_id` comparison replaced by a type check reds `refuses a body that names another allocation…` (`promise resolved … instead of rejecting`). Both reverted.
- [x] 9p.5.5 GREEN `fetchOperationFills(strategyId, allocationId)` validating the body (design § D and § F: every field by type, `side` BUY or SELL, a non-empty list, `allocation_id` equal to the one asked for; a failure is an error, never a partial table) and `useOperationFills(strategyId, allocationId)` with that query key, not enabled without both ids. **Done (22bfbe2).** `fetchOperationFills` and `useOperationFills` (key `['performance','strategy',id,'trade-fills',allocationId]`, enabled only with both ids, 60 s stale time like the other performance reads). 18 tests of `performance.fills.test.ts` green.
- [x] 9p.5.6 RED `frontend/src/features/strategies/format.test.ts` (Create), with the stub `figureText(value: string): string | null` returning its argument in `format.ts`: `::formats a stored 18-place string with up to eight significant digits and no trailing zeros` (`"0.451200000000000000"` gives `"0.4512"`, `"1250.000000000000000000"` gives `"1250"`, `"1.000000000000000000"` gives `"1"`, `"0.000000000000000000"` gives `"0"`, `"123456.789012000000000000"` gives `"123456.79"`), `::never writes an exponent`, `::a string that is not a number gives null`. RED: `expected '0.451200000000000000' to be '0.4512'`. It is a text operation over the server's string, not arithmetic (design § F, § 15 "Money is never computed in the browser"). **Done (c320b59, RED).** Stub `figureText` returns its argument. Failed on `expected '0.451200000000000000' to be '0.4512'` (and the other formatting cases) and `expected 'x' to be null`. `0.63`, `0`, a micro price and a 21-digit integer passed at once on the stub (they are fixed points of it).
- [x] 9p.5.7 GREEN `figureText` in `format.ts`. **Done (5f224ee).** `figureText` in `format.ts`: integer digits kept, fraction rounded half up at the eighth significant digit on the digit string with carry, trailing zeros removed, no exponent, a non-decimal string gives null. 23 tests green.
- [x] 9p.5.8 RED `TradesTable.test.tsx`, columns and tiers (the current component is the stub; each test asserts, never throws first): `::shows twelve columns in the order Opened, Closed, Pair, Side, Entry, Exit, Size, Fees USDT, PnL USDT, PnL %, Pool capital at open, Details` (**recorded edit:** this replaces `shows what the endpoint serves and no entry price, exit price, size or fees column (decision 43, pending)`, renamed and its expected list replaced, not deleted: `expected [7 headers] to deeply equal [12 headers]`), `::each column carries its width tier` (class assertions: Closed, Pair, Side, PnL, PnL % and Details carry no `hidden`; Entry and Exit carry `hidden md:table-cell`; Size, Fees and Pool capital at open carry `hidden xl:table-cell`; Opened carries `hidden min-[90rem]:table-cell`; every `th` and its `td`; mutation: one responsive class removed), `::the table sits in a wrapper that scrolls sideways` (`overflow-x-auto`), `::the heading Return reads PnL % in English and in Spanish`, `::a row shows the stored figures` (Entry 0.4512, Exit 0.4631, Size 1250, Fees 0.63, PnL 14.245), `::a null entry, exit and size show an em dash with the reason for a screen reader and no cell shows 0`, `::a fee in another currency follows the fees as "+ 0.00012 BNB"`, `::an incomplete-fee row keeps its mark on the PnL cell`, `::a figure that is not a number reads as unreadable`, `::a row with no recorded capital shows PnL % and Pool capital at open empty`. **Recorded edit:** the helper `pnls` of `TradesTable.test.tsx` reads cell index 4 and moves to the PnL cell's new index (8); no assertion changes. The side-in-Spanish test (`is titled and labelled in Spanish`, already LONG and SHORT) is run unmodified except for the heading `PnL %`, which is recorded. **Done (2326d0d, RED).** Failed on `expected [7 headers] to deeply equal [12 headers]` (replaces `shows what the endpoint serves and no entry price…`, renamed and its list replaced), `expected [ 'always', … ] to deeply equal [ 'min-[90rem]:table-cell', … ]` (tiers), `expected [ Array(7) ] to include 'PnL %'` (EN) and `expected [ 'Apertura (UTC)', …(6) ] to include 'PnL %'` (ES), `expected [ '+14.25', '+0.2%', '1,000.00' ] to deeply equal [ '0.4512', '0.4631', '1250', … ]`, `expected '+1.50' to contain '—'`, `expected '' to contain '0.63'`, `expected '' to contain 'fees incomplete'`, an unreadable-figures deep-equal and `expected '' to contain '—'` (no capital). `sits in a wrapper that scrolls sideways` passed at once. Deviation: the PnL of the stored-figures case is `14.25`, not `14.245`, because `amountText` writes USDT with two decimals and the task text does not say how 14.245 should round; no rounding behaviour is pinned here. Mutations after GREEN: `FROM_XL` removed from the Size `td` reds the tier test (deep-equal of the tiers); `overflow-x-auto` removed from the wrapper reds `sits in a wrapper that scrolls sideways` (`expected false to be true`). Both reverted.
- [x] 9p.5.9 GREEN `TradesTable.tsx` (design § F): the twelve columns with the tier classes on the `th` and the `td`, `Absent` for a null entry, exit or size with the new reason text, `figureText` for the figures, `+ {amount} {currency}` after the fee, `strategies.performance.trades.{entry,exit,size,fees,otherFee,notDerivable}` and the changed `return` ("PnL %") in EN and ES, and the Details column holding a real `<button>` with its accessible name and **no behaviour yet** (the stub 9p.5.19 fails against). **Gap carried here, not decided:** the Spanish wording for an unreadable cell is not fixed by the design; the cell reuses the existing `cellUnreadable` key and its existing Spanish text, and a new Spanish string is not invented. Every new key is in both locale files. **Done (56dc239).** Twelve columns with the tier classes on the `th` and the `td`, `Absent` with `notDerivable`, `figureText` for figures, `+ {amount} {currency}` after the fee, the Details `<button>` (accessible name from `detailsOf`, no behaviour) and the keys `entry`, `exit`, `size`, `fees`, `otherFee`, `notDerivable`, `details`, `detailsOf` and the changed `return` in both locale files. The unreadable cell reuses `cellUnreadable` and its existing Spanish text (gap carried, nothing invented). Recorded edits to existing tests, no assertion relaxed: the `pnls` helper reads cell 8; `writes the instants in UTC…` expects the twelve cells; `writes a coin-margined pool's figures…`, `shows an em dash, never a zero, for a trade with no capital…` and `says a cell cannot be read…` read the PnL, PnL % and capital cells at 8, 9 and 10; `is titled and labelled in Spanish` expects the twelve Spanish headers, with `PnL %` replacing `Rendimiento`. The task named only the helper index and the `PnL %` heading; the cell-index and header-list edits are the consequence of the new columns and are recorded here. Full suite: 47 files, 726 tests green.
- [x] 9p.5.10 RED `TradesTable.test.tsx`, the rehearsal mark: `::each rehearsal_fill_price value shows its own tag on its own line under the pair` (`FIXED_ONE`, `ALERT`, `UNDETERMINED`: "Dry run · fixed price", "Dry run · alert price", "Dry run"; mutation: every value mapped to the plain tag), `::the tags in Spanish` ("Simulación · precio fijo", "Simulación · precio de la alerta", "Simulación"), `::a value the panel does not know reads as the plain tag` (`"SLIPPED"`), `::a real row is unmarked`, `::a fixed-price row prints entry 1, exit 1 and fees 0 and no cell is blank` (mutation: those cells blanked on a rehearsal row), `::a rehearsal row's PnL and PnL % are in neutral ink and a real row's use the gain colour` (mutation: `toneClass` applied to a rehearsal row), `::the tag is text in the amber token of the dry-run badge and not colour alone`. RED against the 9p.5.9 component, which draws no tag: `expect(queryByText("Dry run · fixed price")).toBeInTheDocument()`. The real-row test passes at once; mutation: the tag drawn on every row. **Done (b63f115, RED).** Failed on `expect(received).toBeInTheDocument()` (the tag cases, English, Spanish, unknown value and amber token) and `expected [ [ 'gain', 'gain' ], …(3) ] to deeply equal [ [ 'neutral', 'neutral' ], …(3) ]`. `leaves a real row unmarked` and `prints entry 1, exit 1 and fees 0 on a fixed-price row, and no cell is blank` passed at once.
- [x] 9p.5.11 GREEN: the tag in the Pair cell on its own line, the `decision` token, neutral ink for a rehearsal row's PnL and PnL %, the stored numbers untouched, and the keys `rehearsal`, `rehearsalFixed`, `rehearsalAlert` in EN and ES (design § F's table). An unknown or `UNDETERMINED` value renders the plain tag. **Done (85fcea5).** Tag in the Pair cell as a `block` span in `text-decision`, worded by `rehearsal_fill_price` (`UNDETERMINED` and unknown values read as the plain tag), neutral ink for a rehearsal row's PnL and PnL %, keys `rehearsal`, `rehearsalFixed`, `rehearsalAlert` in EN and ES. Recorded edit to an existing test: the amber allow-list of `features/overview/panel-tokens.test.ts` gains `features/strategies/TradesTable.tsx` (design § F names the `decision` token for the tag; the guard otherwise reds). Mutations after the GREEN commit, each reverted: every value mapped to the plain tag reds the English, Spanish and amber-token cases; the entry cell blanked on a rehearsal row reds `prints entry 1, exit 1 and fees 0…`; `toneClass` applied to a rehearsal row reds the ink case; the tag drawn on every row reds `leaves a real row unmarked` (and `writes the instants…`). Full suite: 47 files, 733 tests green.
- [x] 9p.5.12 RED `TradesTable.test.tsx`, the sentences: `::each sentence appears only when a row of the page on screen makes it true` (no rehearsal row: none; one `FIXED_ONE`: sentences 1 and 2 and not 3; one `ALERT`: 1 and 3 and not 2; one `UNDETERMINED`: 1 only; `"SLIPPED"`: 1 only; mutation: the sentences shown unconditionally), `::the sentences follow the page on screen and never the pages visited before` (page 1 holds a `FIXED_ONE` row, page 2 only real rows: after "Next" none is shown; mutation: computed from every loaded page), `::the sentences in Spanish` (the exact texts of the spec), `::a rehearsal-only strategy shows rows and sentence 1 under a report that says zero trades` (at the page level in 9p.5.21). RED: `expect(queryByText(<sentence 1>)).toBeInTheDocument()` on a component that draws none. **Done (cc1207b, RED).** Seven cases failed on `expected [ false, false, false ] to deeply equal [ true, true, false ]` and its siblings (FIXED_ONE, ALERT, UNDETERMINED, `SLIPPED`, a mixed page, the page-on-screen case and the Spanish exact texts), asserted with `toEqual` over `queryByText`. The no-rehearsal-row case and the title case passed at once. The texts are those of the spec as amended on 2026-10-05, with the owner's added sentence in the `ALERT` one, in both languages. The page-level rehearsal-only case is in 9p.5.21. Mutations after the GREEN commit, each reverted: sentence 1 made unconditional reds `no rehearsal row` and the page-on-screen case; computed from every loaded page reds the page-on-screen case; `UNDETERMINED` and unknown values claiming the fixed-price sentence reds the ALERT, UNDETERMINED and unknown-value cases.
- [x] 9p.5.13 GREEN: the three sentences under the table's title, chosen from the rows of the page on screen only, with `rehearsalNote`, `rehearsalFixedNote`, `rehearsalAlertNote` in EN and ES. The section title stays "Closed trades" / "Operaciones cerradas". **Done (cc0fbf2).** Up to three `<p>` sentences under the title, chosen from `rows`, the one page on screen; keys `rehearsalNote`, `rehearsalFixedNote`, `rehearsalAlertNote` in EN and ES, exact texts of the spec. The section title is unchanged. Full suite: 48 files, 765 tests green. **Follow-up 9qf.3 stays unticked:** only the table's text is built; the dialog's (`detail.rehearsalAlertHint`) is 9p.5.16.
- [x] 9p.5.14 Confirm and pin, tests that pass at once. **(a) The paging requirement as the spec now states it was built in 9p.8:** add nothing for it and confirm that the existing paging tests pass unmodified apart from the recorded builder and helper edits: `::test_keyset_paging_shows_one_page_at_a_time_and_next_asks_the_server_with_the_cursor`, `::test_previous_uses_the_pages_already_loaded_and_sends_nothing`, `::disables Previous on the first page and Next on the last, where the cursor is null`, `::sends each next request the exact cursor the server answered, and never an offset`, `::asks the server for 20 rows a page`, `::shows the page number and no page count, since the server serves no total`, `::has both buttons disabled when the first page is the whole list`, `::disables Next and says it is loading while the next page is on its way, keeping the page`, `::keeps the current page on screen and says the next page failed, then moves on at a second click`, `::starts again at page 1 when the page is shown for another strategy`, `::says the first page failed and offers to try again, with no table`, `::says there are no closed trades yet for an empty list`. **What decision 43 changes and is added:** `::every request of the table carries include_rehearsal=true, the first page and the page after Next` (the server double of the file records each URL; mutation: the parameter dropped from `fetchStrategyTrades`), `::a page whose row lacks fees is refused whole, with the error state and Try again, and no row is rendered`, `::the nine-field rows of an older API show the error state and no invented figure`, `::Try again loads the page once the API serves the new fields` (the double changes its answer), `::a rehearsal row with a null rehearsal_fill_price refuses the page` (mutation: that check removed). **Done (bcc4797).** (a) The twelve listed paging tests pass unmodified apart from the recorded builder and helper edits (run in the full suite). (b) Five new tests in `TradesTable.test.tsx`, all passing at once: `carries include_rehearsal=true on every request, the first page and the page after Next`, `refuses a page whose row lacks fees, whole, with the error state and Try again and no row`, `shows the error state and no invented figure for the nine-field rows of an older API`, `loads the page on Try again once the API serves the new fields`, `refuses the page of a rehearsal row whose rehearsal_fill_price is null`. Mutations applied after the commit, seen red and reverted with `git checkout`: the `include_rehearsal` parameter dropped from `fetchStrategyTrades` reds the first; the rehearsal-mark check removed reds the last; the `fees` check removed reds the second.
- [x] 9p.5.15 RED `frontend/src/features/strategies/TradeDetailDialog.test.tsx` (Create), with the stub `TradeDetailDialog` rendering an empty `<dialog />` (props `trade`, `currency`, `locale`, `onClose`; presentational) in the same commit: `::shows the pair and the side in the title and every figure of the row` ("STXUSDT · LONG", both prices, "Size (STX)" 1250, "Fees paid (USDT)" 0.63, PnL, PnL %, the PnL % sentence "PnL over the pool's capital when the operation opened, not over the position's margin.", pool capital at open, the allocation id), `::shows fees in other currencies only when there are some`, `::a null figure shows the table's em dash`, `::its figures render with the fills request still pending, and no request was made for the figures`, `::a rehearsal dialog carries the tag in its title and the sentence of its kind` (the three texts of the spec in English, and `ALERT` in Spanish), `::an unknown value shows the general dry-run sentence`, `::a real operation shows no rehearsal sentence`, `::Close and Escape both call onClose`, `::it is modal: showModal is called and focus moves into it`, `::every key it uses exists in en and es`. RED against the empty dialog: `expect(queryByText("STXUSDT · LONG")).toBeInTheDocument()`. **Gap carried, not decided:** several labels exist only in design § F's i18n table (the `detail.*` keys); that table is the source and no wording is invented. **Done (9efddfc, RED).** Stub `TradeDetailDialog` renders an empty `<dialog />`; props `strategyId`, `trade`, `currency`, `locale`, `onClose`. **Deviation from the design's prop list:** `strategyId` is added, because the fills request needs it and the dialog mounts the fills table; the design lists four props. All 15 cases failed on an assertion: `expect(received).toBeInTheDocument()` (title, figures, sentences, Close, no-base-currency), `expected spy to be called 1 times, but got 0 times` (modal) and `expected [ 'detail.title', …(15) ] to deeply equal []` (keys in both languages). **Addition required by the owner's answer of 2026-10-05** (not an edit of an existing assertion): `opens an operation with no base currency: Size with an em dash and its reason, and Quantity in the fills table`. The sentence texts are literal in the tests, not read from the locale files. Also in the red commit: the keyboard helper is NOT here (see 9p.5.19).
- [x] 9p.5.16 GREEN `TradeDetailDialog.tsx` (design § F, D12): a native `<dialog>` opened with `showModal()` where the browser has it, Escape and the `cancel` event routed to one handler (the pattern of `ArchiveDialog` and `DeleteStrategyDialog`), a definition list of the figures, the rehearsal sentence by value, a Close button, palette tokens only (`decision`, `ink`, `ink-2`, `ink-3`, `rule`, `panel`, `gain`, `loss`; no hex and no `var()` in a `className`), and the `detail.*` keys in EN and ES. The dialog mounts `OperationFillsTable` under the figures (stubbed until 9p.5.18). **Done (5c8c5f1).** `TradeDetailDialog.tsx`: native `<dialog>` with `showModal()` where available (else the `open` attribute), Escape and `cancel` routed to one handler, focus moved to the Close button, a definition list of the row's figures with no request, the rehearsal sentence by kind (the alert-priced one carries the owner's added sentence, texts exactly as design § F's table), the fills table mounted in the dialog's own `overflow-y-auto` body, `open:flex` so a closed dialog stays hidden, palette tokens only. A null `base_currency` uses `detail.sizeNoBase` and is passed on to the fills table. All `detail.*` keys in EN and ES. One edit to my own red test before its green: the modal case now defines `showModal` on the prototype of a real `<dialog>` element (the first draft replaced the global class and could never be called). Recorded edit to an existing test: the amber allow-list of `panel-tokens.test.ts` gains `TradeDetailDialog.tsx` (the tag in the dialog's title, as the spec's scenario requires). Mutations after the commit, each reverted: the ALERT sentence mapped to the general one reds the English and Spanish ALERT cases; Escape ignored reds the Close-and-Escape case; the null base currency replaced by a guessed one reds the no-base-currency case. **Follow-up 9qf.3 is now built in both places** (table `cc0fbf2`, dialog `5c8c5f1`) and is ticked.
- [x] 9p.5.17 RED `frontend/src/features/strategies/OperationFillsTable.test.tsx` (Create), with the stub `OperationFillsTable` rendering nothing in the same commit (props `strategyId`, `allocationId`, `baseCurrency`, `operationRehearsal`): `::shows the loading line, then one line per fill in order` (BUY 1250 at 0.4512 fee 0.31 USDT, SELL 1250 at 0.4631 fee 0.32 USDT: Side "Buy", Price 0.4512, Quantity 1250, Fee "0.31 USDT"), `::says only the first 200 fills are shown when truncated is true`, `::a failed read shows the error with Try again and activating it repeats the request` (404, a network failure and a missing route), `::a malformed body shows the failed state and draws no line` (another allocation id, an empty list, a side of "HOLD", a price that is a JSON number), `::a fill whose rehearsal flag differs from the operation's carries the Dry run tag and the others do not`, `::it is a real table captioned Fills inside the dialog's scrolling body`, `::the labels in Spanish` ("Compra", "Venta", "Ejecuciones", "Reintentar", "Cargando las ejecuciones…"). RED against the empty component: `expect(queryByRole("table", { name: "Fills" })).toBeInTheDocument()`. **Done (1ca2d1b, RED).** Stub `OperationFillsTable` renders nothing (props `strategyId`, `allocationId`, `baseCurrency`, `operationRehearsal`). All 18 cases failed on `expect(received).toBeInTheDocument()` (loading line, table named Fills, errors, truncation sentence, tags, Spanish texts), asserted through `queryBy…` inside `waitFor`. A first run with `findBy` failed on `Unable to find…`, which is a throw, so those were rewritten before the commit. **Left for 9p.5.19 and the dialog tasks:** the table 'inside the dialog's scrolling body' needs the dialog and is not asserted here; the component alone proves the real captioned `<table>` and its own `overflow-x-auto` wrapper. **Gap carried to 9p.5.16 and 9p.5.20:** `baseCurrency` is typed `string` as the task says, but a row whose `base_currency` is null can still be opened, and the design fixes no Quantity heading for it; none was invented, so the dialog task must decide what it passes. **Also for the owner:** design § F says a fill whose flag differs from the operation's carries the Dry run tag, which read literally also tags a real fill inside a rehearsal operation; implemented literally, and only the real-operation case plus the equal case are pinned.
- [x] 9p.5.18 GREEN `OperationFillsTable.tsx`: `useOperationFills`, the three states, the truncation sentence, a real `<table>` with a caption, the Dry-run tag on a fill whose flag differs from the operation's, and the `detail.fills.*` keys in EN and ES. **Done (f04d4f5).** `OperationFillsTable.tsx` with `useOperationFills`, the three states, the truncation sentence (200), a real captioned `<table>`, the Dry run tag on a differing fill, and the `detail.fills.*` keys in EN and ES with the exact texts of design § F's table. The amber allow-list of `panel-tokens.test.ts` gains `OperationFillsTable.tsx` (same tag as the table's; recorded edit). Mutations after the commit, each reverted: the flag comparison replaced by true reds the tag cases; the truncation sentence made unconditional reds `says nothing about truncation when truncated is false`; Try again made a no-op reds the four retry cases. Full suite: 48 files, 756 tests green. **Follow-up of the owner's answer of 2026-10-05 (b85631e RED, 50d7ffb GREEN):** an operation whose figures cannot be derived has a null `base_currency` and still opens, so `baseCurrency` is `string | null` and, with null, the Quantity heading reads `detail.fills.quantityNoBase` ("Quantity" / "Cantidad"), never an empty parenthesis and never a currency guessed from the pair. RED: `expected [ 'Time (UTC)', 'Side', 'Price', …(2) ] to deeply equal [ 'Time (UTC)', 'Side', 'Price', …(2) ]` and `expected [ Array(5) ] to include 'Cantidad'`; mutation `baseCurrency === null` made `false` reds both.
- [x] 9p.5.19 RED `TradesTable.test.tsx`, opening an operation (the Details button of 9p.5.9 does nothing): `::no fills request is made until an operation is opened, and one is made when it is` (mutation: the fills fetched with the page), `::opening a dialog shows the loading line and then the fills`, `::a failed fills read leaves the figures on screen` (mutation: the dialog's body replaced by the error), `::only one dialog is open at a time` (opening another closes the first), `::focus returns to the Details button on Escape and on Close` (`document.activeElement`; mutation: the focus call removed), `::the Details controls are reachable with Tab and open with Enter and with Space`, `::twenty Details controls have twenty distinct accessible names` ("Details of STXUSDT LONG, closed …"; mutation: a constant name). RED: `expect(screen.queryByRole("dialog")).toBeInTheDocument()` against a no-op button. The keyboard test uses the keyboard helper the existing dialog tests use; where the harness has none, it is added and recorded. **Done (8da491d, RED).** Against a Details button that does nothing, 9 cases failed on `expect(received).toBeInTheDocument()` (opening, loading line, failed read keeps figures, fills table inside the dialog's scrolling body, one dialog at a time, focus return on Escape and on Close, Tab then Enter, Tab then Space). `twenty Details controls have twenty distinct accessible names` passed at once. **Keyboard helper added and recorded:** the project has no `@testing-library/user-event` and jsdom neither moves focus on Tab nor activates a button on Enter or Space, so `frontend/src/test/keyboard.ts` (`pressTab`, `pressEnter`, `pressSpace`) stands for those browser defaults; what the tests prove with it is a real, enabled, focusable `<button>` in document order. Carried from 9p.5.17 and asserted here: the fills table sits inside the dialog's `overflow-y-auto` body; the request is made only by the dialog being mounted. Mutations after the GREEN commit (6f0a108), each reverted: the fills fetched with the page reds `makes no fills request until an operation is opened`; the focus call removed reds both focus-return cases; a constant accessible name reds the distinct-names case; the figures removed from the dialog reds `keeps the figures on screen when the fills read fails`.
- [x] 9p.5.20 GREEN: `TradesTable` holds the open operation in local state, mounts `TradeDetailDialog` for it, keeps the opening button and focuses it on close, and gives each button the accessible name `detailsOf` with pair, side and close time. The dialog's figures come from the row and need no request; the fills request is made by mounting `OperationFillsTable`. **Done (6f0a108).** `TradesTable` holds the one open operation in local state, mounts `TradeDetailDialog` for it (opening another replaces it), keeps the opening button and focuses it once the dialog is gone (effect on the state), and each button's accessible name is `detailsOf`. The figures come from the row; the fills request is made by mounting `OperationFillsTable`. The keyboard helper now clicks through `fireEvent`, because a bare `click()` outside `act` left the state update unflushed. Full suite: 49 files, 794 tests green.
- [x] 9p.5.21 RED `StrategyDetailPage.test.tsx`: `::the closed trades table is a full-width section under the two-column grid and above the delete control` (mutation: the table back in the left column), `::a strategy that only ran in dry run shows its operations and sentence 1 under a report that says zero trades`. **Recorded edit:** `::test_left_column_runs_performance_by_pair_and_trades_and_holds_no_webhook_block_until_it_is_opened` asserts the closed trades are the last block of the left column; it is renamed `::test_left_column_runs_performance_and_by_pair_and_holds_no_webhook_block_until_it_is_opened`, its trades assertion moves to the new test, and the webhook assertion stays. RED: `expect(column).not.toContainElement(tradesSection)` fails while the table is still inside the column. **Done (63ba031, RED).** `puts the closed trades table in a full-width section under the two-column grid and above the delete control` failed on `expect(element).not.toContainElement(element)`. `shows the operations and sentence 1 of a strategy that only ran in dry run, under a report of zero trades` passed at once (the report is the default empty one with `trade_count` 0; the table's own empty message is asserted absent). Recorded edit: `test_left_column_runs_performance_by_pair_and_trades_and_holds_no_webhook_block_until_it_is_opened` renamed `test_left_column_runs_performance_and_by_pair_and_holds_no_webhook_block_until_it_is_opened`; its trades title and its 'last block of the column' assertion moved to the new test, the column is now read as the first child of the grid that holds the settings aside, and the webhook assertions stayed. Mutations after the GREEN commit, each reverted: the table put back in the left column reds the section test; sentence 1 dropped reds the dry-run-only test.
- [x] 9p.5.22 GREEN `StrategyDetailPage.tsx`: `TradesTable` leaves the left column and becomes a full-width section under the two-column grid, above `DeleteStrategyControl`. The header, the performance block and the settings column do not move. **Done (4f45614).** `StrategyDetailPage.tsx`: `TradesTable` leaves the left column and is a full-width section under the two-column grid, above `DeleteStrategyControl`; the header, the performance block and the settings column did not move. Full suite: 48 files, 767 tests green.
- [x] 9p.5.23 Tests that pass at once, in `TradesTable.test.tsx`: `::every visible string of the table, a rehearsal row's dialog and its fills table is Spanish and sourced from i18n, and the side stays LONG and SHORT` (the spec's localization scenario; mutation: one Spanish `detail.fills.*` value left in English), and `::every strategies.performance.trades key exists in both languages` (mutation: delete one Spanish key). The spec's `Every Panel String Is Localized EN/ES` requirement is covered here and by the per-component key tests. **Done (f712cf5, e210ff3).** Both cases pass at once: `every strategies.performance.trades key exists in both languages` (flattened key sets compared) and `reads Spanish from i18n in the table, a rehearsal row's dialog and its fills table, with LONG and SHORT unchanged` (every text node of the page is checked against the English texts that differ from their Spanish ones, and the Spanish headings of the fills table and the dialog's Close are required by name). Mutations, each reverted: a Spanish key deleted reds both and the Spanish title test; a Spanish `detail.fills.time` left in English did NOT turn the first version red, because an untranslated value equals its English twin, so e210ff3 adds the Spanish fills headings by name and the mutation then reds the case.
- [x] 9p.5.24 Confirm and gate: `cd frontend && npm run lint && npm test`. Record the observed totals, the three recorded edits groups (the builders and helper index, the renamed and replaced tests, the `include_rehearsal` query test), and that no other existing test changed. **Done.** `cd frontend && npm run lint`: `tsc -b --noEmit`, no errors. `cd frontend && npm test`: 49 files, 796 tests passed. Totals across the unit: 44 files and 655 tests before 9p.5.1, 49 files and 796 tests after (5 new test files, 141 new tests). **Recorded edits to existing tests, by group:** (1) the trade builders of `TradesTable.test.tsx`, `StrategyDetailPage.test.tsx` and `performance.strategy.test.ts`, and the `pnls` helper index (4 to 8); (2) renamed or replaced: `performance.strategy.test.ts` first-page query test (renamed, `include_rehearsal` added), the `TradesTable.test.tsx` column test (renamed, expected list replaced), five `TradesTable.test.tsx` cases whose cell indexes or header list moved with the new columns (instants, coin-margined, em dash, unreadable cell, Spanish title) and the `StrategyDetailPage.test.tsx` left-column test (renamed, its trades assertions moved to the new section test); (3) the amber allow-list of `panel-tokens.test.ts`, three additions (`TradesTable.tsx`, `OperationFillsTable.tsx`, `TradeDetailDialog.tsx`), each from design § F's `decision` token. **No other existing test changed:** `git diff --name-status` of the unit lists exactly four modified test files, the three above plus `panel-tokens.test.ts`; every other test file is new. Changed lines of the unit under `frontend/` (additions plus deletions, `tsconfig.tsbuildinfo` excluded): 2,508 in total, 728 production code and locale keys and 1,780 tests; the standing size exception applies.
- [x] 9p.5.25 Owner step, before the push: the review by eye. **Done 2026-10-05.** The owner's fixture was updated, at the owner's request, to serve the eight new fields, `include_rehearsal` and the fills route (it stays local and untracked), and was checked on a spare port: 20 rows a page, dry-run rows only on request, page 2 with none, and the fills cases (one fill per side, three opening fills, truncated, 404, slow, a mixed operation). The owner reviewed the page and approved it, with four changes to the table, recorded as tasks 9p.5.27 to 9p.5.30 below and as decision 46. Run the backend (the 12e-1 code) and `cd frontend; npx vite --config vite.fixture.config.ts`. **The fixture file is the owner's, untracked, and no task edits it.** Today it fakes the trades endpoint with nine-field rows, so with the new check the section would show its error state until the fixture serves: on `GET /api/performance/strategies/{id}/trades`, rows with the eight new fields (`rehearsal`, `rehearsal_fill_price`, `base_currency`, `entry_price`, `exit_price`, `size`, `fees`, `other_fees`), honouring `include_rehearsal=true`, and more than 20 rows so that paging shows (a rehearsal row of each of the three kinds, a real LONG and SHORT, a row with the four figures null, a row with a BNB fee, a row with no capital recorded, page 1 holding a rehearsal row and page 2 only real rows); and a new route `GET /api/performance/strategies/{id}/trades/{allocation_id}/fills` answering `{allocation_id, fills, truncated}` (an operation with one fill per side, one with three opening fills, a rehearsal operation at price 1, one with `truncated: true`, one answering 404 for the error state, one slow for the loading state). What to look at: (1) the table at 1440, 1280, 1024, 768, 600 and 390 px: twelve, eleven, eight and six columns by tier, no sideways scroll of the page, sideways scroll of the table only below about 560 px, the section full width under the grid and above the delete control; (2) the three tags and their sentences, the sentences vanishing on a page with no rehearsal row, PnL and PnL % in neutral ink on a dry-run row, entry 1 and exit 1 printed as 1; (3) the detail dialog from each tier: every figure that a narrow tier hides is in it, the PnL % sentence, the dry-run sentence of its kind, the fills table scrolling inside the dialog and not behind it, the loading, error, truncated and 404 states with the figures still on screen; (4) keyboard: Tab to a Details button, Enter and Space open it, Escape and Close return focus to that button; (5) Spanish: every string, and LONG and SHORT unchanged; (6) the header reads "PnL %". The owner's observations become tasks here; the review is not a gate the tests can pass.
- [x] 9p.5.26 Owner step, after the merge: deploy 12e-2. **Done 2026-10-05.** PR #61 merged 17:25 UTC, merge commit `3b54844` (two parents, checked with `git rev-list --parents`); the owner reported the deploy. The delivery log has the entry. `sudo -u strategy -H git -C /opt/strategy-manager/app pull --ff-only`; **no restart** (frontend only, and the panel is not served while `PANEL_DIST_DIR` is unset). 12e-1 must already be deployed. Update the delivery log after the merge (the standing working agreement; this list writes no entry).

**From the owner's review by eye (2026-10-05, task 9p.5.25; owner-decisions.md, decision 46).** The owner approved the table, the tags, the sentences, the dialog, the keyboard and the Spanish, and asked for four changes that make the table narrower. All four change the TABLE only: the detail dialog and its fills table keep what they show. Each is a RED/GREEN pair with the same rules as the tasks above; an existing test that pins the replaced behaviour is a recorded edit, renamed and its expectation replaced, never deleted. Where the spec or design § F states the replaced text or format, the same commit updates it.

- [x] 9p.5.27 The incomplete-fee mark leaves the PnL cell's width. RED then GREEN in `TradesTable.test.tsx` and `TradesTable.tsx`: a row with `fees_complete: false` shows an asterisk right after its PnL figure, in `ink-3`, carrying the existing `feesIncompleteHint` text as its `title` and as screen-reader text; the words of `feesIncomplete` are no longer in the cell. One note sits under the table's title, after the dry-run sentences, only when a row of the page ON SCREEN has `fees_complete: false`: the text of `feesIncompleteHint` preceded by `* `, as the new key `feesIncompleteNote` in EN and ES. It follows the page on screen, never the pages visited before (the rule of the dry-run sentences). The dialog keeps the words. **Recorded edit:** `::an incomplete-fee row keeps its mark on the PnL cell`. Mutations: the note shown unconditionally; the note computed from every loaded page; the asterisk drawn on every row. **Done (2aaecb4 RED, 53d62a7 GREEN).** RED failed on `expected 'fees incomplete' to contain '*'` and `expected false to be true` (the note cases) and `expect(received).toBeInTheDocument()` (note after the dry-run sentences). The asterisk is a `text-ink-3` span with the hint as its `title` and as `sr-only` text, right after the PnL figure; the note `feesIncompleteNote` (the hint preceded by `* `, EN and ES, not reworded) follows the page on screen, after the dry-run sentences. The dialog keeps its words. **Recorded edits:** `::an incomplete-fee row keeps its mark on the PnL cell` renamed `::shows an asterisk right after the PnL figure of an incomplete-fee row, in ink-3, with the hint as title and screen-reader text, and not the words`; and, not named by the task, `::marks a trade whose fees are incomplete and no other` (it looked for the words) renamed `::marks a trade whose fees are incomplete with an asterisk and no other` and now finds the asterisk by its title. Mutations after GREEN, each reverted: the note unconditional reds the no-incomplete-row and page-on-screen cases; the note computed from every loaded page reds the page-on-screen case; the asterisk drawn on every row reds the clean-row case and five more. Spec and design lines updated: spec.md, requirement 'The Closed Trades Table Shows Each Operation's Figures', the sentence on incomplete fees; design.md § F, the line 'fees_complete: false …'.
- [x] 9p.5.28 The capital column's heading is shorter. RED then GREEN: the table's `capital` heading reads "Pool at open" in English and "Pool al abrir" in Spanish. The dialog's `detail.capital` label is unchanged. **Recorded edit:** the twelve-header list of the column tests and the Spanish title test. **Done (776c976 RED, 3785fdd GREEN).** The table's `capital` key reads "Pool at open" / "Pool al abrir"; `detail.capital` is unchanged. RED: the two replaced expectations failed on a deep-equal of the headers. **Recorded edits:** the twelve-header list of `::shows twelve columns in the order …` (title renamed with `Pool at open`) and the Spanish title test `::is titled and labelled in Spanish`. Spec and design lines updated, see the report of this batch: spec.md in the column list, the width-tier list, the two scenarios that name the column and the empty-capital sentence; design.md § F in the tier table and the column order.
- [x] 9p.5.29 Opened and Closed are compact, on two lines. RED then GREEN, with new helpers in `format.ts` and their tests in `format.test.ts`: each cell shows the numeric date in the panel's language on its first line (`10/5/2026` in English, `5/10/2026` in Spanish, for 2026-10-05) and the time on its own line below, 24-hour `HH:mm`, in `ink-3`, both in UTC as the heading says. The date and the time come from the instant by `Intl` with `timeZone: "UTC"`; nothing is parsed from a formatted string. The dialog keeps its long format. **Recorded edit:** `::writes the instants in UTC…`. Mutation: the local time zone used instead of UTC (run with a fixed non-UTC instant near midnight so the date differs). **Done (350309d RED, ee0a2e0 GREEN).** `compactDateText(iso, locale)` and `clockText(iso)` in `format.ts` from the instant by `Intl` with `timeZone: "UTC"`; the Opened and Closed cells show the numeric date and, on a `block text-ink-3` line below, the 24-hour time; an unreadable instant shows raw with no time line. What `Intl` writes in the test runtime (Node 24.13.1), for 2026-10-05: `10/5/2026` in `en` and `5/10/2026` in `es`; the time `09:07`, `00:05` (never `24:05`), `01:30`; both agree with the task's examples, so nothing was hand-formatted. RED failed on `expected '2026-10-05T09:07:00Z' to be '10/5/2026'` (and its siblings), `expected null …` and `expected [] to deeply equal [ '10/5/2026', '01:30' ]`. **Recorded edit:** `::writes the instants in UTC, the venue's pair spelling, …` now reads the two lines of each instant cell (`9/29/2026 23:30`, `9/30/2026 00:15`); the rest of the row is as before. The dialog keeps `dateTimeText`, and so does the accessible name of the Details button (it names the close time in full). Mutation after GREEN, reverted: the local zone instead of UTC (this machine is UTC-3, offset 180, with the instant `2026-10-05T01:30:00Z`, which is still the 4th locally) reds 11 cases in `format.test.ts` and `TradesTable.test.tsx`. On a UTC machine this mutation would not be visible; it was seen here. No spec or design sentence stated the old date format, so none was changed.
- [x] 9p.5.30 The table's figures are shorter. RED then GREEN, a new `tableFigureText` in `format.ts` beside `figureText` (which the dialog and the fills table keep): at most 5 decimal places with no trailing zeros; when 5 decimal places would leave fewer than 4 significant digits, 4 significant digits instead, so a price below 0.00001 never reads 0; never an exponent; a string that is not a number gives null; it is the same text operation over the server's string that `figureText` is, with its rounding. Cases: `"0.705295610000000000"` gives `"0.7053"`, `"2515.952800000000000000"` gives `"2515.9528"`, `"0.429090380000000000"` gives `"0.42909"`, `"61250.123456000000000000"` gives `"61250.12346"`, `"1.000000000000000000"` gives `"1"`, `"0"` and `"0.000000000000000000"` give `"0"`, `"0.012345600000000000"` gives `"0.01235"`, `"0.001234560000000000"` gives `"0.001235"`, `"0.000005120000000000"` gives `"0.00000512"`. Entry, Exit and Size use it. Fees are written like the PnL beside them, with the pool currency's decimals (two for USDT, so a fee of `"0"` reads `0.00`) and no sign; a fee in another currency keeps `figureText` (`+ 0.00012 BNB`), because two decimals would print it as zero. **Recorded edits:** the stored-figures test and the fixed-price test of 9p.5.8 and 9p.5.10 where their expected Fees text changes. Mutations: the 4-significant-digit floor removed (reds the micro-price case); the fee written with `figureText` again. **Done (e210778 RED, b9158f2 GREEN).** `tableFigureText` beside `figureText`, both now over one shared `roundedFigure`; every case of the task is asserted (`0.7053`, `2515.9528`, `0.42909`, `61250.12346`, `1`, `0`, `0`, `0.01235`, `0.001235`, `0.00000512`) plus rounding to `1`, the sign, no exponent and null for non-numbers; `figureText` was meant to be unchanged in behaviour and pinned by its own tests plus a guard case, but see the defect below: for one commit it was NOT unchanged. Entry, Exit and Size use it; Fees use the PnL's `amountText` (two decimals for USDT, so a fee of `0` reads `0.00`, eight for BTC) with no sign; a fee in another currency keeps `figureText` (`+ 0.00012 BNB`). RED failed on `expected '0.705295610000000000' to be '0.7053'`, `expected '' to be null`, `expected [ '0.70529561', … ] to deeply equal [ '0.7053', … ]` and `expected '0' to be '0.00'`. **Recorded edit:** `::prints entry 1, exit 1 and fees 0 on a fixed-price row, and no cell is blank` renamed `… fees 0.00 …`, its expected Fees text replaced; the stored-figures test needed no change (fees `0.63` is unchanged). Mutations after GREEN, each reverted: the four-significant-digit floor removed reds the micro-price cases (4 tests); the fee written with `figureText` again reds the fixed-price, USDT zero and BTC cases. Spec and design lines updated: spec.md, the sentence on figure formats in 'The Closed Trades Table Shows Each Operation's Figures' (the eight-significant-digits clause moved to the dialog); design.md § F, the line on prices and sizes. **Defect found in review and fixed (7e2ecae RED, 325f6b9 GREEN):** the refactor of `figureText` into the shared `roundedFigure` (b9158f2) lost a backslash, so the expression that strips leading zeros of the integer part read `/^0+(?=d)/` instead of `/^0+(?=\d)/` and stripped nothing; `figureText` and `tableFigureText` stopped normalising an integer part with leading zeros (`"007.500"` gave `"007.5"`, not `"7.5"`), against the earlier claim that `figureText` was unchanged. The gate stayed green because no test fed a leading zero. RED, 12 cases on assertions: `expected '007.5' to be '7.5'`, `expected '00.5' to be '0.5'`, `expected '000' to be '0'` (twice), `expected '0012345.7' to be '12345.679'` and `expected '0012345.6789' to be '12345.6789'`, each for both functions. GREEN: the `\d` restored by hand. Full suite after: 49 files, 855 tests.
- [x] 9p.5.31 Confirm and gate again: `cd frontend && npm run lint && npm test`. Record the totals and the recorded edits of 9p.5.27 to 9p.5.30. **Done.** `cd frontend && npm run lint`: `tsc -b --noEmit`, no errors. `cd frontend && npm test`: 49 files, 843 tests passed (before 9p.5.27: 49 files, 796 tests; 47 new tests, no new test file). **Recorded edits of 9p.5.27 to 9p.5.30 to existing tests:** (a) renamed with a replaced expectation: the incomplete-fee PnL-cell test and the incomplete-fee-marking test (9p.5.27), the twelve-header test (9p.5.28), the fixed-price test (9p.5.30); (b) edited in place: the Spanish title test's header list (9p.5.28) and the instants-in-UTC test's two instant cells (9p.5.29). No test was deleted, no assertion relaxed, and no other existing test changed; `TradeDetailDialog.test.tsx` and `OperationFillsTable.test.tsx` are untouched.

**From the owner's second look (2026-10-05; owner-decisions.md, decision 46, last answer).** The four changes above were approved. One more: the notes move below the table.

- [x] 9p.5.32 The table's notes sit below it, not under its title. RED then GREEN in `TradesTable.test.tsx` and `TradesTable.tsx`: the three dry-run sentences and the incomplete-fee note are rendered AFTER the table and after the Previous and Next controls, in the order they have today (dry-run sentences 1, 2, 3, then the incomplete-fee note); nothing but the table follows the section's title. Which notes show does not change: each still appears only when a row of the page on screen makes it true. They sit after the paging controls so that those controls do not move when a page has no note. No text changes. **Recorded edits:** the existing tests that pin the notes "under the title" (`::each sentence appears only when a row of the page on screen makes it true` and its siblings of 9p.5.12, the note-order test of 9p.5.27, the page-level test of 9p.5.21 if it reads the position) keep every assertion about WHICH note shows and replace only the assertion about WHERE. Mutation: the notes rendered before the table again. Where the spec or design § F says "under the table's title", the same commit updates it, marked "(owner decision 46, 2026-10-05)". **Done (b6447d7 RED, 0cb7e63 GREEN).** RED: two cases failed on `expected false to be true`: the first note after the table and after the paging controls, with the notes keeping their order (sentences 1, 3, then the incomplete-fee note), and nothing but the table between the title and the table. GREEN moved the notes block after the `<nav>`; no key was added, removed or reworded and which notes show is unchanged. In the current code a note is drawn only in the branch that draws the table, never in the loading, error or empty state, and that is unchanged. **Recorded edits:** none to an assertion. The describe `TradesTable sentences under the title` was renamed `TradesTable sentences below the table` and its comment updated; no existing test pinned where a note sits, because they find notes by text, so the note-order test of 9p.5.27 and the page-level test of 9p.5.21 needed no change. Mutation after GREEN, applied with the Edit tool and reverted with `git checkout`: the notes rendered before the table again reds both new cases. Spec and design lines updated: spec.md, the incomplete-fee sentence of 'The Closed Trades Table Shows Each Operation's Figures' and the sentence that opens the three-sentence list ('Under the table's title …' now 'Below the table and its paging controls …'); design.md § F, the `fees_complete: false` line and the bullet 'The sentences under the title'.
- [x] 9p.5.33 Confirm and gate again: `cd frontend && npm run lint && npm test`. Record the totals and the recorded edits of 9p.5.32. **Done.** `cd frontend && npm run lint`: `tsc -b --noEmit`, no errors. `cd frontend && npm test`: 49 files, 857 tests passed (before 9p.5.32: 49 files, 855 tests; 2 new tests). The recorded edit of 9p.5.32 is the rename of one describe, with no assertion changed; no other existing test changed.

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")`; the dialog and the fills table are tested as components with props and a stubbed fetch.
Rollback boundary: a revert restores the seven-column table inside the left column, which still works against the new API (design § D); the new files are nothing's import once it is reverted. The server needs no change.
Forecast: 2,400–3,600 changed lines (design § I forecasts 1,400–2,000). Derived bottom-up: about 900 of production code and locale keys (`TradesTable.tsx` 250 net, `TradeDetailDialog.tsx` 200, `OperationFillsTable.tsx` 130, `performance.ts` 120, `types.ts` 50, `format.ts` 30, about 60 keys in two locale files 130), and tests at about twice that: `TradesTable.test.tsx` about 500, the dialog test 350, the fills table test 250, the two API test files 550, the format test 60, the page test 80, builders 40. Information only.

## PR 12g — The simulated exchange fills at the alert's price (decision 45) (2,800–4,200 lines)

One PR to `main`, backend only, unit **9q**, cut from an up-to-date `main` and never stacked. Source
of truth: design.md, "Addendum: the simulated exchange fills at the alert's price (decision 45) -
2026-10-04" (§§ A to N; both questions of § N are answered, nothing is open), and the eleven
requirements of this change's `specs/trade-execution/spec.md`. Owner decision 45 is binding and is not
reopened here.

**Why it is one PR, and not for size** (design § L). An exchange that prices opens at the alert and
cannot yet price closes has no honest state to be deployed in: its closes would have to be refused or
filled at 1. The opening half, the closing half, the refusals and the fee ship together.

**No migration.** No route, no frontend, no change to `performance`. The "Migration rehearsal" section
does not change and nothing here is rehearsed on the VPS.

**Deploy it BEFORE PR 12e-1, and why.** Every day of dry run at a fixed price of 1 writes fills that
can never be repriced (the ledger is append-only and decision 45 reprices nothing), while a delay of
PR 12e loses nothing: its list reads whatever the ledger holds. **Neither waits for the other in
code**: this unit edits `execution`, `signals` and `main.py`; 12e edits `performance`; no file is
shared. The one check in PR 12e that assumed the opposite order (the step after 12e-1's deploy, task
9p.4.38) was rewritten on 2026-10-04 to the rows production will hold once this unit is live.

**Task order is dependency order, not the order the design lists its sections.** `reference_price`
travels from the alert to the order spec (9q.4 to 9q.6) BEFORE the simulated exchange's default flips
to the alert's price (9q.9, 9q.10): once the default flips, a close that carries no price has nothing
to be filled at, and the 17 integration tests that close in default mode must already carry one.

Rules that bind this unit, on top of the cross-cutting rules:

- **RED fails on an ASSERTION.** A new argument, field, mode or refusal is first a stub that compiles
  and answers WRONGLY, in the same commit as the RED test: the price mode is first a default that
  still fills at 1 (`assert Decimal('1') == Decimal('0.123456789012345678')`); a refusal test captures
  the exception and asserts on its type, so a stub that does not raise fails on an assertion; the
  rates module is first a table with both rates at 0. **Where the stub is a plumbing task's own state**
  (`fee_rate` accepted and ignored in 9q.3; `reference_price` carried as `None` in 9q.4) the RED commit
  follows that task immediately and its task says so: those two arguments are REQUIRED, so they cannot
  exist without the 35 and 21 forced edits that make the gate pass. The first failure is never an
  `ImportError`, a `TypeError` or a type error. **Each task records the assertion it failed on.**
- **A test that passes at once is proven non-vacuous by the mutation its task names** (design § K's
  table). The mutation is applied, the test is seen red, and the mutation is reverted; it is never
  committed. The task records what was seen. A mutation of a real adapter's file is applied to the
  working tree only: no real adapter file is in any commit of this unit.
- **What a real adapter sends to a venue does not change.** Proven per registered adapter ON THE WIRE
  (method, path, query, body bytes, signature) with and without the new price on a close (9q.7), and
  per adapter at the built-order and recorded-call level for the four that exist (9q.8). The real
  adapter files and their existing tests are NOT edited: the default on `CloseOrderSpec.reference_price`
  is what leaves them as they are, and 9q.28 shows the diff names none of them. No order type carries a
  price; a test pins that.
- **No fallback price, ever.** An unusable price (absent, zero, negative, NaN, infinite) is refused in
  `place` through the existing "rejected by venue" path. Not to 1, not to the entry price, not to the
  last price seen. The mutation that proves it: a fallback to 1 in place of the refusal (9q.13).
- **The rate is required, with no default**, and a test proves an exchange with no rate is not served
  (9q.22). The constructor has no default, the composition root reads the table by key, and the
  mutation is the table read with a default of zero.
- **Every failure mode of design § J has a test asserting its one log line and its level**, and no
  line carries a credential, a DSN, a token or a raw payload: the exchange, the symbol, the side, the
  ids, and a simulated fill's quantity, price and fee only. The map of § J to tasks:

  | § J failure | Level and line | Test task |
  |---|---|---|
  | The price did not arrive (a close built with `reference_price=None`, or an order the simulated exchange did not build) | The caller's existing ERROR (`close rejected by venue…` or `order rejected by venue…`), the cause in its `error=` text; exactly one | 9q.11, 9q.13 |
  | A price of zero, negative, NaN or infinite on a close | The same ERROR; the text names the value | 9q.11, 9q.13 |
  | A price of zero, negative or NaN on an OPEN | Unchanged: the domain raises at build, the job is retried, the worker's existing exception line per attempt. Nothing new is logged; the test pins only that no fill exists and no price is substituted | 9q.11 |
  | A close with no alert, for an orphan | The same ERROR; the attempt FAILED; no outcome written by the close itself | 9q.13 |
  | Production builds the simulated exchange with a fixed price | WARNING at worker start naming the exchange and the price; INFO otherwise, with each exchange and its rate | 9q.22, 9q.23, 9q.24 (mutation) |
  | A later edit rounds the price | Nothing can log it at write time; the exactness tests go red | 9q.9, 9q.24 |
  | The moment the change took effect is not visible | The startup INFO and one INFO per simulated fill | 9q.20, 9q.22 |
  | An exchange has a pool and no fee rate | At start: the existing unserved-pools WARNING and one WARNING naming the exchange and the reason; per signal: the existing `UNTRADABLE_POOL` WARNING | 9q.22 |
  | A simulated fill is charged no fee | Cannot happen unnoticed: no default rate, the table read by key, both values pinned; the startup INFO names each rate | 9q.1, 9q.15, 9q.22 |
  | An order on a market not quoted in USDT | The caller's existing ERROR with the cause in its `error=` text | 9q.17, 9q.19 |
  | The account's fee tier changes and the constant does not; a remembered price is never used; a restart between place and settle | Nothing can log the first two (stated risks, design § M); the third is the existing WARNING, unchanged | none |

- **Symbol spellings across the boundary.** The webhook side uses TradingView's `STXUSDT.P`, the
  strategy's allowed pair is `STXUSDT`, and the venue book and Pionex use `STXUSDT` and
  `STXUSDT_PERP`. A ledger row is asserted through `market_key(symbol) == "STXUSDT"`, never by
  comparing two spellings as text, and the simulated venue book is asserted under the bare `STXUSDT`.
  The real-adapter tests hand the adapter `STXUSDT.P` and assert the request names `STXUSDT`; the Pionex
  adapters get `STXUSDT_PERP`.
- **No test needs a real credential or the network.** `DRY_RUN` is true everywhere except the one
  composition test that builds with it false and reads no secret; the real adapters are driven over
  `httpx.MockTransport` with the frozen clock their suites already use; the end-to-end test seeds a
  balance snapshot young enough for the refresh's fallback.
- **The `head` schema only where a constraint decides the outcome:** task 9q.14 (`ck_signals_price_positive`
  exists only in migration 0002, and what `signals.price` does with `NaN` and `Infinity` is exactly what
  that test settles). It uses `backend/tests/pg_head_schema.py` and says so in its docstring. Every other
  integration test runs on the ORM schema, because the read or write under test decides nothing by a
  constraint.
- **No lock-hold harness applies.** This unit adds no lock and no transaction boundary (design § K).
  Lock order is unchanged.
- **Existing tests.** No test is deleted and no assertion is relaxed. The recorded edits, each listed by
  name in its task: the explicit zero rate at every construction site (9q.3); the price on every
  `CloseCommand` and `CloseOrphans.close` call and the doubles of `CloseOrphansPort` (9q.4); a test
  found to depend on a fill of 1 given `fill_price=Decimal("1")` and a docstring line saying why
  (9q.10); a test that builds the worker with a pool on an exchange outside the rates table, moved to a
  Bybit or Binance pool or turned into a case of 9q.22 (9q.23). The rehearsal-prefix tests of
  `backend/tests/execution/infrastructure/test_fake_exchange.py` (the `fake-fill-` and `fake-order-`
  assertions) and `backend/tests/test_main_pool_reload.py`, `backend/tests/test_mode_guard_wiring.py` (they read `main.py` as text) are not edited.
- **Commits.** One work-unit commit per task, or per RED/GREEN pair where a red commit would break the
  gate (pairs: 9q.1-2, 9q.5-6, 9q.9-10, 9q.11-12, 9q.15-16, 9q.17-18, 9q.20-21, 9q.22-23); the RED is
  observed and recorded either way. `git commit -F <file>` written without a BOM, conventional commits,
  no AI attribution.
- **No size rule.** The owner does not want work split by size. The forecast below is information only.
- **What fails here without a log line?** is answered by the table above and by design § J.

### Unit 9q — the simulated exchange fills at the alert's price (2,800–4,200 lines) — PR 12g

**Needs**: nothing. It is independent of PR 12e and of unit 9d, and it should be merged and deployed
first.

**Files**:
Create `backend/src/strategy_manager/execution/infrastructure/simulated_fee_rates.py`.
Modify `backend/src/strategy_manager/execution/application/{ports,close_position,place_order}.py`,
`backend/src/strategy_manager/execution/domain/{fill,futures_order}.py` (docstrings only),
`backend/src/strategy_manager/execution/infrastructure/fake_exchange.py`,
`backend/src/strategy_manager/signals/application/{close_orphans,process_signal}.py`,
`backend/src/strategy_manager/main.py`.
Read, never edited: the real adapters `backend/src/strategy_manager/execution/infrastructure/{bybit_futures_exchange,binance_futures_exchange,pionex_exchange,pionex_futures_exchange}.py`,
`backend/src/strategy_manager/shared/infrastructure/{bybit,binance,pionex}/`, the four
`backend/scripts/check_*` scripts that build a `CloseOrderSpec` (the default leaves them as they are), and the real adapters' existing test files.
Create `backend/tests/execution/infrastructure/{test_simulated_fee_rates,test_real_adapters_ignore_reference_price}.py`,
`backend/tests/signals/infrastructure/{test_simulated_price_refusals_integration,test_signal_price_head_constraint,test_no_fee_rate_pool_refused,test_simulated_fill_webhook_to_ledger}.py`,
`backend/tests/test_main_simulated_exchanges.py`.
Modify `backend/tests/execution/infrastructure/{test_fake_exchange,test_dry_run_invariant}.py`,
`backend/tests/execution/application/test_close_position.py`,
`backend/tests/signals/application/{test_close_orphans,test_process_signal,test_process_signal_deferral_outcomes,test_open_after_close_integration,test_open_now_concurrent_redelivery}.py`,
`backend/tests/signals/infrastructure/{test_order_outcomes_integration,test_settle_outcomes_integration,test_continuation_outcomes_integration}.py`.

**The rates** (design § E)

- [x] 9q.1 RED `backend/tests/execution/infrastructure/test_simulated_fee_rates.py` (Create), with the stub module `backend/src/strategy_manager/execution/infrastructure/simulated_fee_rates.py` (Create) in the same commit: `SIMULATED_TAKER_FEE_RATES`, a `types.MappingProxyType` keyed by `Exchange.BYBIT.value` and `Exchange.BINANCE.value`, both at `Decimal("0")`; `SIMULATED_FEE_CURRENCY = "USDT"`. Layer: infrastructure/execution; imports `decimal`, `types` and `Exchange` only. Tests: `::test_the_table_holds_exactly_bybit_at_0_00055_and_binance_at_0_0005` (the whole mapping compared with `==` to the expected dict, so a missing or an extra entry fails too), `::test_no_other_exchange_has_a_rate` (Pionex), `::test_the_fee_currency_is_usdt`, `::test_the_table_is_read_only` (the assignment captured, the exception's type asserted), `::test_every_rate_is_a_decimal_that_is_not_negative_and_below_one`. RED against the stub: `assert {'bybit': Decimal('0'), 'binance': Decimal('0')} == {'bybit': Decimal('0.00055'), 'binance': Decimal('0.0005')}`. The other four pass at once; mutations: a `pionex` entry added; the currency `"USD"`; a plain `dict`; a float rate. Spec: "The rates table holds exactly the two verified rates". Done 2d40461 (with 9q.2). RED on `assert {'bybit': Decimal('0'), 'binance': Decimal('0')} == {...0.00055...0.0005}`; the other four passed at once. Mutations seen red then reverted: a `pionex` entry (3 tests red), currency `"USD"`, a plain `dict`, a float rate.
- [x] 9q.2 GREEN `simulated_fee_rates.py`: Bybit `Decimal("0.00055")`, Binance `Decimal("0.0005")`. Each entry's comment carries its source and date: Bybit, the real round trip of 2026-08-27 (its fees, 0.05883625 USDT, are exactly `0.00055 × 106.975`); Binance, **the owner's figure read on the account on 2026-10-04, not confirmed by a real round trip in this project** (the maker rate, 0.02%, is not used: a simulated fill is a market order). Mutation, then reverted (design § K, test 13): Binance at `Decimal("0.0002")` reds the exact-values test. Done 2d40461. Mutation: Binance at `Decimal("0.0002")` reds the exact-values test; reverted.

**The fee argument and the price carried to the order spec** (design §§ B, E)

- [x] 9q.3 Plumbing, no behaviour change, no assertion changed: `FakeExchangeAdapter.__init__` in `backend/src/strategy_manager/execution/infrastructure/fake_exchange.py` gains `fee_rate: Decimal`, keyword-only, **required, no default**, stored and not yet used. `backend/src/strategy_manager/main.py` passes `fee_rate=Decimal("0")` at its one construction, TEMPORARILY, with a comment saying 9q.23 replaces it; no commit of this unit is deployed before 9q.23. Every construction site gains `fee_rate=Decimal("0")` and nothing else, plus `from decimal import Decimal` where a file lacks it: `backend/tests/execution/infrastructure/test_dry_run_invariant.py` (3), `backend/tests/execution/infrastructure/test_fake_exchange.py` (10), `backend/tests/signals/infrastructure/test_continuation_outcomes_integration.py` (1), `backend/tests/signals/infrastructure/test_order_outcomes_integration.py` (4 of `FakeExchangeAdapter` and 2 instantiations of `_DustExchange`), `backend/tests/signals/infrastructure/test_settle_outcomes_integration.py` (13), `backend/tests/signals/application/test_open_now_concurrent_redelivery.py` (1 of `CountingFakeExchange`), `backend/tests/signals/application/test_open_after_close_integration.py` (1): 32 of `FakeExchangeAdapter`, 1 of `CountingFakeExchange`, 2 of `_DustExchange`, as design P14 counts (the module docstring of the last file only mentions the class; it is prose and stays). A site that passes `fill_price` keeps it; a site that takes the default keeps taking it. No test is about the fee, and none loses an assertion. No RED: the proof is that `cd backend && uv run mypy src tests` refuses a site left without the argument (remove one, see it fail, restore) and that the full suite passes unmodified apart from these lines. The task records the count it found against the design's 33. Done b7b4bcd. Found 35 sites (32 `FakeExchangeAdapter`, 1 `CountingFakeExchange`, 2 `_DustExchange`), the task's 33 of the first two plus the three subclass instantiations as the design counts; `mypy` refused a site left without the argument (seen, restored); the temporary zero in `main.py` was removed by 9q.23.
- [x] 9q.4 Plumbing, the stub of the next RED, no behaviour change: `backend/src/strategy_manager/execution/application/ports.py` — `CloseOrderSpec` gains `reference_price: Decimal | None = None`, its docstring saying it is the price of the alert that caused the close, is read only by the simulated exchange, sizes nothing and is sent nowhere. `backend/src/strategy_manager/execution/application/close_position.py` — `CloseCommand` gains `reference_price: Decimal | None`, **required, no default** (the rule `signal_id` already follows); `ClosePosition.close` does NOT yet pass it into the spec. `backend/src/strategy_manager/signals/application/close_orphans.py` and `.../process_signal.py` — `CloseOrphans.close` and `CloseOrphansPort.close` gain `reference_price: Decimal | None` as a required keyword-only argument; `CloseOrphans` passes `reference_price=None` into its `CloseCommand` and `_handle_releases` and the `_handle_consumes` call pass `reference_price=None` (the wrong answer 9q.6 replaces). Forced test edits, each gaining a price and losing no assertion: the 5 `CloseCommand` constructions (`backend/tests/execution/application/test_close_position.py`, 2; `backend/tests/signals/infrastructure/test_order_outcomes_integration.py`, `backend/tests/signals/infrastructure/test_settle_outcomes_integration.py` and `backend/tests/signals/application/test_open_after_close_integration.py`, 1 each) take a positive `Decimal`; the 16 calls of `CloseOrphans.close` in `backend/tests/signals/application/test_close_orphans.py` take `reference_price=Decimal("0.4633")`; the doubles of `CloseOrphansPort` accept it: `SpyCloseOrphans` in `backend/tests/signals/application/test_process_signal.py` records it in a NEW list `reference_prices` and leaves the six-tuples of `calls` as they are, `TimelineCloseOrphans` in `backend/tests/signals/application/test_process_signal_deferral_outcomes.py` passes it to `super()`, `NeverCalledCloseOrphans` in `backend/tests/signals/application/test_open_after_close_integration.py` accepts it; `SpyExchange` in `test_close_position.py` gains `built_closes: list[CloseOrderSpec]`, appended in `build_close_order`. Any other double found by `uv run mypy src tests` is edited the same way and recorded. The four `backend/scripts/check_*` scripts that build a `CloseOrderSpec` are not touched: the default keeps them valid. No RED: mypy refuses a call site left without the argument, and the existing suites pass unmodified apart from these lines. Done ca138eb. Edits: 5 `CloseCommand` constructions, 16 `CloseOrphans.close` calls, the doubles `SpyCloseOrphans`, `TimelineCloseOrphans`, `NeverCalledCloseOrphans` (open_after_close) and, found by the same search, `NeverCalledCloseOrphans` in `test_open_now_concurrent_redelivery.py`; `SpyExchange.built_closes`. No assertion changed.
- [x] 9q.5 RED carriage of the alert's price (design § B, P3, P4), against the 9q.4 state; each test records its assertion. `backend/tests/execution/application/test_close_position.py`: `::test_the_closing_alerts_price_reaches_the_order_spec` (`assert None == Decimal('0.4633')` on `exchange.built_closes[0].reference_price`), `::test_a_close_with_no_alert_price_builds_a_spec_with_none` (passes at once; mutation: `Decimal("1")` put in place of `None`), `::test_the_price_never_sizes_the_close` (the order's `base_size` is still the ledger's net with a price present; passes at once; mutation: the size computed from the price). `backend/tests/signals/application/test_close_orphans.py`: `::test_the_opening_alerts_price_is_the_reference_price_of_the_orphan_close` (`assert None == Decimal('0.4633')` on the `CloseCommand` its close-position double received), `::test_an_orphan_close_carries_no_signal_id_and_still_carries_the_price` (the same, plus `signal_id is None`), `::test_every_orphan_of_the_holdings_is_closed_at_the_same_alert_price` (two holdings). `backend/tests/signals/application/test_process_signal.py`: `::test_a_closing_alerts_price_is_the_close_commands_reference_price` (the context's symbol `STXUSDT.P`, its price 0.4633, the held position opened by a signal at 0.4512; `assert None == Decimal('0.4633')`), `::test_a_reversing_alerts_price_prices_the_close_half`, `::test_an_opening_alerts_price_is_handed_to_close_orphans` (`SpyCloseOrphans.reference_prices == [Decimal('0.4633')]`), `::test_the_close_is_never_priced_at_the_price_of_the_signal_that_opened_the_position`. Spec: Requirement 1, the REVERSE and orphan scenarios (the carriage half). Done 5f7b1a8 (with 9q.6). RED on `assert None == Decimal('0.4633')` (test_close_position, test_process_signal and the first two of test_close_orphans; the holdings case on `[None, None] == [...]`, the `SpyCloseOrphans` case on `[None] == [Decimal('0.4633')]`). Mutations red then reverted: `Decimal("1")` for `None`; size computed from the price.
- [x] 9q.6 GREEN: `ClosePosition.close` passes `command.reference_price` into the `CloseOrderSpec` it builds (design § B); `CloseOrphans.close` passes its `reference_price` into the `CloseCommand` and keeps `signal_id=None`; `_handle_releases` passes `context.price`, and the `_handle_consumes` call passes `context.price` to `close_orphans.close`. No other line of these files changes; the size of a close is still the ledger's net. Done 5f7b1a8.

**The real adapters are untouched** (design §§ B, K test 10; Requirement 8)

- [x] 9q.7 Tests that pass at once, on the wire: `backend/tests/execution/infrastructure/test_real_adapters_ignore_reference_price.py` (Create). Each REGISTERED adapter, `BybitFuturesExchangeAdapter` and `BinanceFuturesExchangeAdapter`, is built over its REAL trade client through `httpx.MockTransport` with the frozen clock and signer construction of `backend/tests/shared/infrastructure/bybit/test_trade_client_catalogue.py` and `backend/tests/shared/infrastructure/binance/test_trade_client.py` (the handler answers the leverage and instrument-rules reads that building a close makes, as those suites' handlers do). Tests: `::test_bybit_close_requests_are_byte_identical_with_and_without_a_reference_price` and `::test_binance_close_requests_are_byte_identical_with_and_without_a_reference_price` (the same close of `STXUSDT.P` built and placed once with `reference_price=None` and once with `Decimal("0.4633")`, parametrized again with `Decimal("9999999.5")`: the two orders are equal, and the recorded requests have the same count and identical method, path, query, body bytes and signature header), `::test_each_request_names_the_bare_venue_symbol` (`STXUSDT`, never `STXUSDT.P`). All pass at once. Mutation, applied to the adapter in the working tree only, then reverted and never committed: the adapter forwards `spec.reference_price` into its request (the body for Bybit, the query for Binance); each must red the body-bytes assertion. The adapters' existing test files are not edited. Spec: Requirement 8, the first two scenarios, and the request half of Requirement 10. Done 6b97f79. Passes at once; mutation (working tree only, reverted, never committed): Bybit and Binance forwarding the spec's price into the JSON body and the signed form each red the byte-identical tests (and the price-nowhere test).
- [x] 9q.8 Same new file, at the built-order and recorded-call level for the four adapters that exist: `::test_<adapter>_builds_equal_orders_and_records_identical_calls_with_and_without_a_reference_price` for Bybit, Binance, `PionexExchangeAdapter` and `PionexFuturesExchangeAdapter` (each through the `FakeTradeClient` its own suite defines, imported rather than copied where it is importable; Pionex gets `STXUSDT_PERP`); `::test_no_order_type_a_real_adapter_sends_carries_a_price` (the dataclass fields of `MarketBuy`, `MarketSell` and `FuturesMarketOrder` include neither `price` nor `reference_price`). All pass at once. Mutations, working tree only: an adapter forwards the field (reds its test); a `price` field added to `FuturesMarketOrder` (reds the last). Spec: Requirement 8, the Pionex scenario and its last sentence. Done 23cb457. Mutations (working tree only, reverted): Pionex futures forwarding the price to its client call, Bybit/Binance/Pionex spot letting the price change the built size, and a `price` field on `FuturesMarketOrder` each red their test.

**The simulated exchange prices a fill at the alert** (design §§ B, C, D, I)

- [x] 9q.9 RED `backend/tests/execution/infrastructure/test_fake_exchange.py` (new tests), with the stub in the same commit: `fill_price: Decimal | None = None` on the constructor and a read-only property `fixed_fill_price` (the argument as given); the stub answers a fill priced `Decimal("1")` when it is `None`. Tests: `::test_every_kind_of_order_fills_at_its_alert_price_to_the_last_place` (parametrized over the kinds of design § A: a spot buy that opens, a spot sell that opens, a futures open LONG and SHORT, a spot sell that closes, a futures reduce-only close; the price `Decimal("0.123456789012345678")`, compared as `Decimal` and as `str`; `assert Decimal('1') == Decimal('0.123456789012345678')`), `::test_a_19_decimal_price_is_filled_as_given_and_never_rounded_by_the_adapter` (the rounding to 18 places belongs to the column), `::test_a_binance_exchange_fills_at_the_alert_price` (0.4512), `::test_a_close_is_priced_at_the_closing_alert_not_the_opening_one` (opened at 0.4512, closed with `reference_price=0.4633`; `assert Decimal('1') == Decimal('0.4633')`), `::test_two_orders_built_before_either_is_placed_each_fill_at_their_own_price` (X at 0.4512, Y at 0.4633, placed Y then X), `::test_an_alert_priced_exactly_one_is_filled_at_one_and_the_later_close_is_not` (the close half is the assertion that fails on the stub), `::test_a_futures_open_is_sized_so_that_its_notional_equals_the_capital_granted` (564 USDT at 0.4512: quantity 1250, notional 564; `assert Decimal('1250') == Decimal('564')` on the notional), `::test_a_spot_buy_fills_the_granted_amount_over_the_alert_price` (100 at 0.4 on `STXUSDT`, no contract marker: quantity 250; `assert Decimal('100') == Decimal('250')`), `::test_a_dry_run_sizes_at_leverage_one_and_the_gross_result_is_what_the_capital_earns_without_leverage` (alerts 0.4512 then 0.4633 on 1250: gross 15.125, never the 45.375 of 3x; `FAKE_LEVERAGE == Decimal("1")`; the adapter holds no client and reads no leverage), `::test_the_default_is_the_alert_price_mode` (`fixed_fill_price is None`) and `::test_an_explicit_fill_price_is_the_fixed_mode_and_every_order_fills_at_it` (opens and closes, whatever was remembered). The last two pass at once; mutation for the second (design § K): the fixed price ignored whenever a price was remembered. Mutations for the others, after GREEN: the price quantised to 2 places in the adapter (reds the 18-place test); the close reusing the price remembered for the opening order (reds the closing-alert test); one "last price" attribute instead of a map keyed by client order id (reds the two-orders test). Spec: Requirement 1 in full, Requirement 6. Done af9633c (with 9q.10). RED on `assert Decimal('1') == Decimal('0.123456789012345678')` (and the 0.4512/0.4633/250/564 variants). Mutations red then reverted: fixed price ignored when one is remembered; price quantised to 2 places; close reusing the opening's remembered price; one last-price attribute instead of a map.
- [x] 9q.10 GREEN `fake_exchange.py` (design §§ B, C, D, I): `_reference_prices: dict[str, Decimal]` written by `build_open_order` (`spec.price`) and by `build_close_order` (`spec.reference_price`, only when it is not `None`) and popped by `place` with no default; `fill_price` defaults to `None` (the alert-price mode) and an explicit `Decimal` is the fixed mode, which wins; `fixed_fill_price`; a spot buy's quantity is `quote_amount / the price of that fill`. No rounding, no tick, no slippage. **The interim** (replaced by the definitive refusal in 9q.12): an order with nothing remembered raises the dict's own `KeyError`, which is a crash and never a fallback. Then run the full suite and RECORD each test that turned red (the design expects none to assert a price, and the 17 tests that fill orders in default mode now fill at 2); a test found to depend on a fill of 1 is given `fill_price=Decimal("1")` and a docstring line saying why, recorded by name; the 12 sites that already pass an explicit price are untouched. Done af9633c. Full suite run at this state: NO test turned red (none asserts a price; the 17 default-mode tests now fill at 2); no test needed `fill_price=Decimal("1")`.

**An order with no usable price is refused** (design § F)

- [x] 9q.11 RED `test_fake_exchange.py` (new tests), against the 9q.10 state. `::test_a_close_whose_reference_price_is_unusable_is_refused_in_place_and_no_fill_exists` parametrized over `None`, `Decimal("0")`, `Decimal("-0.4633")`, `Decimal("NaN")`, `Decimal("Infinity")`, `Decimal("-Infinity")`: the exception is captured and its type asserted (`assert KeyError is ExchangeError` for `None`, the interim crash; `assert NoneType is ExchangeError` for the rest, which the interim fills), then `fetch_fills` raises `OrderNotFound` for that client order id and the venue book received nothing. `::test_the_message_names_the_value_and_says_the_alert_carried_no_usable_price`. `::test_an_order_the_exchange_did_not_build_is_refused` (a futures order made by hand and placed). `::test_a_positive_absurd_price_is_filled_at` (9999999.5; passes at once; mutation: a ceiling added). `::test_an_opening_order_with_a_non_positive_price_never_reaches_a_fill_in_either_mode` (parametrized `0`, `-1`, `NaN`, in the alert-price and in the fixed mode: the build raises, the exception captured and its type recorded by the task, no fill exists, no price is substituted; **passes at once, it is today's behaviour, design P8**; mutation: the non-positive check of `futures_position_size` removed). **Carried, not decided:** an opening order with an unusable price is retried until the job's attempts run out, in both modes; that is pre-existing and not changed here, and this task pins only that no fill exists. Whether `NaN` raises `InvariantViolation` or the `decimal` module's own comparison error is unverified; the task records what it sees. Spec: Requirement 2, the close, unbuilt-order, opening and absurd-price scenarios (the adapter half). Done b137b14 (with 9q.12). RED: `assert <class 'KeyError'> is ExchangeError` for the absent price and `assert <class 'NoneType'> is ExchangeError` for the rest. Observed: an opening order with a NaN price raises `decimal.InvalidOperation` (not `InvariantViolation`) at build, in both modes and on spot and futures; 0 and -1 raise `InvariantViolation`; an infinite spot BUY builds. Mutations: a price ceiling reds the absurd-price test; removing the non-positive check of `futures_position_size` reds the zero cases.
- [x] 9q.12 GREEN: a private `_is_usable(price)` in the adapter (`price is not None and price.is_finite() and price > 0`, in that order, because comparing a NaN raises); `place` pops the remembered price with a default of `None` and raises `ExchangeError` before minting anything when it is unusable, the message naming the value and saying "the simulated exchange cannot price this order: its alert carried no usable price". The refusal is in `place`, not in `build_close_order` (design § F: a plain exception from the build is retried, and `OrderNotPlaceable` would be reported as dust). No new reason code. Done b137b14.
- [x] 9q.13 Tests that pass at once, on real PostgreSQL, ORM schema: `backend/tests/signals/infrastructure/test_simulated_price_refusals_integration.py` (Create), the fixtures and builders of `backend/tests/signals/infrastructure/test_order_outcomes_integration.py` (imported where public, otherwise copied once into this file, recorded). `::test_a_close_with_no_reference_price_fails_the_attempt_rejects_the_signal_and_leaves_the_ledger_unchanged` (attempt FAILED; signal `REJECTED` with `CLOSE_REJECTED_BY_VENUE`; ledger row count unchanged; exactly one ERROR, the caller's existing line, whose text names the cause and carries no credential, DSN or raw payload), `::test_zero_negative_nan_and_infinite_close_prices_are_each_refused_the_same_way`, `::test_a_refused_close_leaves_the_position_open_and_a_later_close_at_a_usable_price_nets_it_to_zero` (a second `ClosePosition.close` for the same allocation at 0.4633 is placed, its fill is priced 0.4633 and the allocation nets to zero), `::test_an_orphan_close_refused_for_its_price_writes_no_outcome_on_any_signal` (`signal_id` `None`: attempt FAILED, one ERROR), `::test_an_order_the_exchange_did_not_build_is_refused_and_an_opening_reservation_is_released` (a `FakeExchangeAdapter` subclass of this file whose build forgets the price; the signal `REJECTED` with `ORDER_REJECTED_BY_VENUE`, the reservation released, no ledger row, one ERROR). Mutation (design § K, test 7): a fallback to 1 in place of the refusal in `place` reds the ledger-unchanged and attempt-FAILED assertions. Spec: Requirement 2, every scenario but the opening non-positive one and the absurd price; the stack-level "refused close, then the next opening alert closes the orphan" is joined in 9q.25 when 9q.14 allows it. Done 0453566 (and f420978 for 9q.19's case in the same file). Mutation: a fallback to 1 in place of the refusal reds the ledger-unchanged and attempt-FAILED tests (20 tests across both files).
- [x] 9q.14 `backend/tests/signals/infrastructure/test_signal_price_head_constraint.py` (Create), **`head` schema** through `backend/tests/pg_head_schema.py`, said in the docstring. `::test_signals_price_refuses_zero_and_a_negative` (the `IntegrityError` names `ck_signals_price_positive`; passes at once; mutation: the database built with `Base.metadata.create_all`, which has no CHECK, reds it). `::test_what_the_database_does_with_nan_and_with_infinity` is run FIRST as a statement to see what happens, then pinned as what was seen: an assertion on the observed outcome (accepted and read back as NaN, or refused with a named error), never a branch on it. **Carried, not decided:** whether `NaN` or `Infinity` can be stored in `signals.price` is unverified (design § F); the design holds either way. The observation is recorded in this task and reported to the coordinator, who corrects § F's two rows; this task edits no design. If `NaN` CAN be stored, 9q.25 gains the stack-level refusal test. Done 5e702ec. OBSERVED on the `head` schema: `NaN` IS stored in `signals.price` and reads back as NaN (the CHECK `price > 0` does not exclude it); `Infinity` and `-Infinity` are REFUSED by the `NUMERIC(38, 18)` range (`NumericValueOutOfRangeError`), not by the CHECK; 0 and negatives are refused by `ck_signals_price_positive`. Mutation: the ORM schema (`create_all`) reds the refusal test.

**The fee** (design § E)

- [x] 9q.15 RED `test_fake_exchange.py` (new tests), against the stub that 9q.3 left (the rate accepted and ignored, so every fee is `Decimal("0")`). `::test_a_bybit_round_trip_is_charged_0_00055_on_both_sides_in_usdt` (granted 564, opened at 0.4512: 1250 `STXUSDT`, notional 564, fee 0.3102; closed at 0.4633: notional 579.125, fee 0.31851875; both `fee_currency` `"USDT"`; the base quantity is untouched and the close nets to zero; `assert Decimal('0') == Decimal('0.3102')`), `::test_a_binance_round_trip_is_charged_0_0005_on_both_sides` (0.282 and 0.2895625; mutation after GREEN: 0.0002), `::test_the_fee_is_on_the_notional_and_not_on_the_quantity`, `::test_the_fee_is_quantised_to_18_places_half_even` (quantity 10 at 0.123456789012345678 gives exactly `0.000679012339567901`, the unrounded product being `0.000679012339567901229`), `::test_a_tie_rounds_to_the_even_digit` (Binance, price 1: quantity `0.000000000000003` gives `0.000000000000000002` from `1.5e-18`, and `0.000000000000005` gives `0.000000000000000002` from `2.5e-18`), `::test_a_product_of_more_than_28_significant_digits_is_rounded_once_and_not_twice` (the numbers are chosen so that rounding to 28 digits first and to 18 places second disagrees with one rounding; the task records them), `::test_a_fee_below_half_the_last_place_quantises_to_zero`, `::test_a_spot_shaped_buy_is_charged_the_same_rate` (100 at 0.4 on `STXUSDT`: fee 0.055), `::test_a_rate_below_zero_or_of_one_or_more_is_refused_at_construction` (`-0.00055`, `1`, `1.5`: the exception captured and its type asserted; `assert NoneType is InvariantViolation`), `::test_a_rate_of_zero_and_one_just_below_one_are_accepted`, `::test_a_zero_rate_charges_nothing`. The last two pass at once; mutation: the rate replaced by a literal `0.00055`. **Carried, not decided:** the design says a bad rate is "refused" and names no exception type; the test asserts `InvariantViolation` (the project's own precondition error) and the task records the choice for review. Spec: Requirement 3. Done ff5b26c (with 9q.16). RED on `assert Decimal('0') == Decimal('0.3102')` and siblings; the constructor tests on `assert <class 'NoneType'> is InvariantViolation` (the type chosen, for review). Numbers for the >28-digit case: rate 0.5, quantity 1, price `2.99999999999999999999999999998e-18`: exact fee `1.49999999999999999999999999999e-18`; one rounding gives `1E-18`, rounding to 28 digits first gives 1.5e-18 and half-even then gives `2E-18`.
- [x] 9q.16 GREEN: in `place`, `fee = quantity × price × self._fee_rate` inside a local `decimal.localcontext()` of 60 digits, then quantised to `Decimal("1e-18")` with `ROUND_HALF_EVEN`, carried on the `Fill` with `fee_currency` from `SIMULATED_FEE_CURRENCY`; the constructor refuses `fee_rate < 0` and `fee_rate >= 1`; the base quantity is never touched. Mutations, each recorded and reverted (design § K): the fee computed from the quantity alone; the quantisation removed; separately, the product taken in the default 28-digit context. Done ff5b26c. Mutations red then reverted: rate as a literal 0.00055; constructor refusing 0; fee from the quantity alone; quantisation removed; 28-digit context.

**A market not quoted in USDT is refused** (design § E)

- [x] 9q.17 RED `test_fake_exchange.py` (new tests), against the 9q.16 state. `::test_a_market_not_quoted_in_usdt_is_refused_in_place` (parametrized `ETHBTC`, `BTCUSD`, usable price: the exception captured and its type asserted; no fill; the message says the fee is charged in USDT and the market is not quoted in it; `assert NoneType is ExchangeError`), `::test_each_usdt_spelling_is_filled_and_charged` (`STXUSDT`, `STXUSDT.P`, `STX_USDT`, `STX_USDT_PERP` at 0.4512: priced 0.4512, fee quantity × 0.4512 × 0.00055 in `"USDT"`; passes at once; mutation: the check replaced by `symbol.endswith("USDT")`, which reds `STXUSDT.P` and `STX_USDT_PERP`), `::test_a_refused_order_leaves_nothing_remembered`. Spec: Requirement 4, the first two scenarios. Done 8867e9d (with 9q.18). RED on `assert <class 'NoneType'> is ExchangeError`. Mutation: `symbol.endswith("USDT")` reds `STXUSDT.P` and `STX_USDT_PERP`.
- [x] 9q.18 GREEN: in `place`, before minting, `base_currency_of(order.symbol, SIMULATED_FEE_CURRENCY)` (the function the adapter's module already imports from); when it raises, `place` raises `ExchangeError` naming the cause, and the remembered price of that order is popped first so a refused order leaves nothing in memory. Mutation: the check removed reds the refusal test. Done 8867e9d. Mutation: the check removed reds the refusal tests.
- [x] 9q.19 Tests that pass at once, in `test_simulated_price_refusals_integration.py`: `::test_a_refused_opening_on_a_market_not_quoted_in_usdt_releases_its_reservation_and_rejects_the_signal` (`ETHBTC` for pool `(binance, usdt-m, USDT)`, `PlaceOrder` driven directly as `test_order_outcomes_integration.py` does: reservation released, signal `REJECTED` with `ORDER_REJECTED_BY_VENUE`, no ledger row, one ERROR naming the cause; if an earlier check refuses `ETHBTC` before `place`, the test seeds the market so that it reaches `place` and records what was needed). Mutation: the quote check removed. Spec: Requirement 4, the third scenario. Done f420978. The Binance pool row is inserted in the test (the ORM database seeds Bybit's only). Mutation: the quote check removed reds it.

**The per-fill log line** (design § J)

- [x] 9q.20 RED `test_fake_exchange.py` (new tests), `caplog`: `::test_each_simulated_fill_logs_one_info_line_with_exchange_symbol_side_quantity_price_fee_and_client_order_id` (1250 `STXUSDT` bought at 0.4512, fee 0.3102, `bybit`; one record at INFO; `assert 0 == 1` on the count), `::test_the_line_carries_those_seven_values_and_nothing_else` (the record's arguments are exactly them, so no order object, credential or payload can ride along; mutation after GREEN: the line logs `repr(order)`), `::test_a_refused_order_logs_no_fill_line` (the caller logs the ERROR). Spec: Requirement 11, the third scenario. Done 587b395 (with 9q.21). RED on `assert 0 == 1`. Mutation: the line logging `repr(order)` reds the seven-values test. The line is `simulated fill: exchange=%s symbol=%s side=%s quantity=%s price=%s fee=%s client_order_id=%s`, INFO, with quantity, price and fee as plain digits.
- [x] 9q.21 GREEN: one `logger.info` in `place`, after the fill is minted and never before a refusal, carrying the exchange, symbol, side, quantity, price, fee and client order id. Done 587b395.

**The composition root** (design §§ E, J)

- [x] 9q.22 RED, two new files, against the temporary zero of 9q.3 (`backend/src/strategy_manager/main.py` builds a simulated exchange for every exchange with a pool and charges nothing). `backend/tests/test_main_simulated_exchanges.py` (Create; the production composition root built under `DRY_RUN` the way `backend/tests/test_worker_startup_exit.py` builds it, no credential; if building needs a session factory the file uses the PostgreSQL fixture and is marked integration): `::test_a_dry_run_worker_logs_one_info_naming_each_exchange_and_its_taker_rate` (the sentence that each fill is priced at its alert's price, `bybit` with `0.00055` and `binance` with `0.0005`; `assert 0 == 1`), `::test_a_dry_run_worker_logs_no_warning_about_a_fixed_price`, `::test_a_simulated_exchange_built_with_a_fixed_price_is_one_startup_warning_naming_the_exchange_and_the_price` (the startup-line function takes the instances, so the test hands it one built with a fixed price of 1; production never passes one), `::test_an_exchange_with_a_pool_and_no_rate_has_no_simulated_exchange_and_two_warnings` (a Pionex pool in the startup pools: the existing unserved-pools WARNING and one more reading "no simulated taker fee rate is defined for 'pionex'", the worker still builds, `tradable_pools` holds the Bybit and Binance pairs and not Pionex's; `assert (bybit, usdt-m) in ...` passes and the Pionex absence fails), `::test_bybit_and_binance_have_a_simulated_exchange_even_when_no_pool_names_them` (passes at once; mutation: the unconditional pair dropped), `::test_with_dry_run_false_no_simulated_exchange_is_built_and_no_simulated_line_is_logged` (passes at once; mutation: the startup-line call made unconditional; the real adapters' side is 9q.7). `backend/tests/signals/infrastructure/test_no_fee_rate_pool_refused.py` (Create; real PostgreSQL through `main.build_worker_runner(..., session_factory_override=...)` and `run_once`, the pattern of `test_exhausted_jobs_wiring.py`): `::test_a_signal_on_a_pool_of_an_exchange_without_a_rate_ends_rejected_untradable_pool_with_no_reservation_and_no_ledger_row` (one WARNING for the signal), `::test_the_same_worker_still_fills_a_bybit_signal_and_a_binance_signal_each_on_its_own_simulated_exchange`. RED: the Pionex pool is served today, so the outcome is not `('REJECTED', 'UNTRADABLE_POOL')`. Mutation after GREEN (design § K): the table read with a default of zero reds the PostgreSQL test. Spec: Requirement 5, the first three scenarios; Requirement 10; Requirement 11, the first two scenarios. Done e5c8648 (with 9q.23). RED against the temporary zero: `assert 0 == 1`, `{'binance': Decimal('0'), ...} == {...}`, `['binance', 'bybit', 'pionex'] == ['binance', 'bybit']` and the signal outcome `('PROCESSING', None) == ('REJECTED', 'UNTRADABLE_POOL')`. NOT passing at once: the DRY_RUN=false test (the simulated exchanges were built unconditionally); it went red and 9q.23 gates the build on `settings.dry_run`.
- [x] 9q.23 GREEN `main.py`: `fakes_by_exchange` keeps its name and both `BYBIT_EXCHANGE` and `BINANCE_EXCHANGE`, and is built only for the exchanges of that set that are keys of `SIMULATED_TAKER_FEE_RATES`, each with `fee_rate=SIMULATED_TAKER_FEE_RATES[exchange]` read by key (this replaces 9q.3's temporary zero); one WARNING per excluded exchange, "no simulated taker fee rate is defined for '<exchange>'"; the existing unserved-pools WARNING is untouched, because `tradable_pools` is computed from the simulated exchanges that exist; the startup lines come from a function taking `fakes_by_exchange` (its name is chosen here and recorded; design says only that the lines are taken from each instance's own `fixed_fill_price` and rate): one INFO per process naming each exchange and its rate when none is fixed, one WARNING naming the exchange and the price for one that is. Then run the full suite and RECORD each existing test that built the worker with a pool on an exchange outside the table (the design did not count them; if they are many, say so): each is moved to a Bybit or Binance pool or turned into a case of 9q.22, none is deleted. `backend/tests/test_main_pool_reload.py` and `backend/tests/test_mode_guard_wiring.py` run unmodified. Mutation: the table read with a default of zero reds 9q.22. Done e5c8648. Startup-line function: `main.log_simulated_exchange_startup(fakes)`. NO existing test built the worker with a pool outside the table (none moved or changed); the full suite had no red. Mutations red then reverted: table read with a default of zero (and no exclusion); `fee_rate` zero; a fixed price of 1; build unconditional; the unconditional pair dropped.

**From the webhook to the ledger** (design § K, tests 2 to 5 and 16)

- [x] 9q.24 Tests that pass at once, real PostgreSQL on the ORM schema, the production composition root: `backend/tests/signals/infrastructure/test_simulated_fill_webhook_to_ledger.py` (Create). `DRY_RUN` on, no credential; the fixture seeds a balance snapshot young enough for the refresh's fallback (**unexercised in the design: read from the code, not run, so this task is where it is first proven**); a POST to `/webhook/tradingview` with symbol `STXUSDT.P` and price `"0.1234567890123456789"`; the strategy allows `STXUSDT`; `signal.process` and `execution.settle` run through `run_once`. `::test_the_opening_row_is_priced_at_the_stored_alert_price_exactly` (`ledger_entries.price` equals the stored `signals.price` of the signal its reservation names, `0.123456789012345679`; the market key is `STXUSDT`; `exchange_fill_id` starts with `fake-fill-` and the order id with `fake-order-`), `::test_the_opening_row_carries_the_taker_fee_in_usdt` (`fee_currency` `"USDT"`, the fee equal to quantity × price × 0.00055 quantised to 18 places, and strictly above zero), `::test_a_closing_alert_at_another_price_is_filled_at_that_alert_and_the_allocation_nets_to_zero`, `::test_derive_trade_over_the_two_rows_is_complete_and_net_of_both_fees` (`fees_complete` true; with the spec's figures, granted 564 at 0.4512 then 0.4633, the fees total `0.62871875` and the PnL is `14.49628125`), `::test_a_binance_pool_is_charged_0_0005_on_both_sides` (`0.282` and `0.2895625`), `::test_a_usdt_fee_moves_no_holding` (after the open the allocation's net base and the pool-wide net position both equal the quantity bought; after the close both are zero), `::test_a_profitable_round_trip_moves_no_availability` (snapshot 1000 USDT before and after, availability 1000, no reservation created or changed by a price or a fee), `::test_no_performance_total_counts_the_rehearsal_operation` (read as 9p.4.24 reads it). Mutations (design § K): `main.py` builds the simulated exchange with `fill_price=Decimal("1")` reds the price and the closing-alert tests; `main.py` passes `fee_rate=Decimal("0")` reds the fee tests; the fee written in the base currency reds the holding test. Spec: Requirement 1 (19-decimal, close, Binance), Requirement 3 (both round trips, PnL, holding), Requirement 6 (1x, in the figures), Requirement 7, Requirement 11 (the fee in the line, through caplog). Done b4c5121. The balance-snapshot fallback with no credential works as the design read it (first proven here). Mutations red then reverted: `fill_price=Decimal("1")` in `main.py`; `fee_rate=Decimal("0")`; the fee written in the base currency.
- [x] 9q.25 Same file, the two paths that need a position first: `::test_a_reverse_prices_the_close_and_the_new_open_at_the_reversing_alert` (a LONG opened at 0.4512, a reversing alert at 0.4633: the close fill and the new allocation's opening fill both read 0.4633, and the opening fill equals the stored price of the signal its reservation names), `::test_an_orphan_is_closed_at_the_price_of_the_alert_that_found_it_and_the_open_follows` (a REAL orphan on `STXUSDT` seeded through the ledger's own write path at 0.4512, an opening alert `STXUSDT.P` at 0.4633 finds it: the orphan's closing fill is priced 0.4633 although its attempt carries no signal id, then the open's own fill is 0.4633). Both pass at once; mutation (design § K): the simulated exchange reuses the price it remembered for the opening order. If `build_worker_runner` cannot reach either without more setup than the first task's fixture, the task uses the harness of `backend/tests/signals/application/test_open_after_close_integration.py` and records it. **If 9q.14 showed that `NaN` can be stored**, add `::test_a_stored_nan_closing_price_is_refused_and_the_next_opening_alert_closes_the_orphan_at_its_own_price` (Requirement 2's third scenario at stack level); otherwise that scenario is covered by its two halves, 9q.13 and the orphan test above, and the task says so. Spec: Requirement 1, the REVERSE and orphan scenarios. Done aebd9e8. The conditional NaN test WAS added (9q.14 shows NaN can be stored); it is organic: a NaN-priced closing alert is refused, then the next opening alert closes the position as an orphan. Mutation (the close reusing the opening's remembered price) reds the reverse and NaN tests but not the seeded-orphan test (no opening is remembered in its process).
- [x] 9q.26 Same file, Requirement 8 of the spec (nothing already in the ledger is repriced): `::test_a_row_written_before_the_change_keeps_price_one_and_fee_zero` (an opening rehearsal row of 1250 `STXUSDT` at 1, fee 0, written through the ledger's own write path; the worker is rebuilt and other fills are written; the row still reads 1 and 0), `::test_a_position_that_straddles_the_change_closes_at_the_alert_price_with_a_fee` (a closing alert at 0.4633: the closing fill is 1250 at exactly 0.4633 with fee `0.31851875`, the position nets to zero, the opening row is unchanged). Both pass at once; mutation: `main.py` builds the simulated exchange with `fill_price=Decimal("1")` reds the second; a statement that rewrites the opening row's price reds the first. Done 6c46dfa. Mutations red then reverted: `fill_price=Decimal("1")` in `main.py` reds the straddle test; an UPDATE of the opening row's price reds the first.

**Docstrings, gate, owner steps**

- [x] 9q.27 Docstring-only edits (design § I, last row): `backend/src/strategy_manager/execution/domain/fill.py` (`Fill`), `backend/src/strategy_manager/execution/domain/futures_order.py` (`futures_position_size`), `backend/src/strategy_manager/execution/application/place_order.py` (`PlaceCommand`), `backend/src/strategy_manager/execution/application/ports.py` (`OpenOrderSpec`): each says that a fill's price is never the alert's reference price, which stays true of a live fill and is now false of a rehearsal one. The module and class docstrings of `fake_exchange.py` ("a fixed reference price, with zero fee") are rewritten to what the adapter now does. No code changes in the domain files: `git diff -U0` shows comment and docstring lines only, and the gate passes. Done 36c6f70.
- [x] 9q.28 Confirm and gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`. Record: that no existing test was edited beyond the recorded groups (the explicit zero rate, the price on `CloseCommand` and `CloseOrphans.close` with the doubles, the tests given `fill_price=Decimal("1")`, the tests moved off an unrated pool); that the 12 explicit-price tests, the rehearsal-prefix tests and the two `main.py` text tests pass unmodified; that `git diff --stat main...HEAD` over `backend/src/strategy_manager/execution/infrastructure` and `backend/src/strategy_manager/shared/infrastructure` names only `fake_exchange.py` and `simulated_fee_rates.py` (no real adapter file, no real adapter test file), over `backend/src/strategy_manager/execution/domain` names only the two docstring edits, and that no migration file changed; the tests that turned red at 9q.10 and 9q.23 by name. A backend suite on this machine prints no summary line: confirm by exit code and by summing the per-file counts of `uv run pytest --co -q`. No frontend change, so no frontend gate. Done. Gate from `backend`: ruff exit 0, mypy `Success: no issues found in 280 source files`, pytest exit 0 (2,992 tests collected by the per-file sum of `--co -q`). One full run showed a teardown `InsufficientPrivilegeError` (permission denied to terminate process) and passed on re-run; the first baseline run, before any change, showed 4 order-dependent failures in `tests/accounts/application` that pass in isolation. Edited existing tests: the explicit zero rate at 35 construction sites, the price on 5 `CloseCommand` and 16 `CloseOrphans.close` calls with 4 doubles, none given `fill_price=Decimal("1")`, none moved off an unrated pool; the rehearsal-prefix tests and the two `main.py` text tests are unmodified. `git diff --stat 9c8fc6d HEAD` over `execution/infrastructure` and `shared/infrastructure` names only `fake_exchange.py` and `simulated_fee_rates.py`, over `execution/domain` only the two docstring edits; no migration, real adapter or real adapter test file changed.
- [x] 9q.29 **Done 2026-10-04 by the owner, before the restart:** no open rehearsal allocation on an exchange with no fee rate, no open rehearsal allocation at all, alembic 0028, and 4 rehearsal fills in the ledger, all at a price of 1 with a fee of 0 (delivery log, PR 12g). The script actually run was a variant of the one below: it read only the database NAME from the env file and connected as the `postgres` role over the local socket, so the DSN was never an argument of `psql` and the password never appeared in the process list. Prefer that form. Owner step, BEFORE the restart (design § G): the read-only check for an open rehearsal allocation on an exchange that has no fee rate. None is expected, because production's Pionex pools are disabled; if it prints a row, **stop and report it, do not restart**: that position could no longer be closed in dry run. The same script also lists every open rehearsal allocation, so the rows that straddle the change are known by id for the delivery log. Save as a scratch file and run `ssh root@159.195.148.136 "bash -s" < file`. It sets the session read-only, prints no DSN and no credential (it reads `DATABASE_URL` from the service's own env file into a shell variable, strips the `+asyncpg` driver suffix and the quotes, and never echoes it), and writes nothing:

  ```
  #!/usr/bin/env bash
  set -euo pipefail
  url=$(sed -n 's/^DATABASE_URL=//p' /opt/strategy-manager/app/backend/.env \
    | sed -e 's/^["'\'']//' -e 's/["'\'']$//' -e 's#^postgresql+asyncpg:#postgresql:#')
  export PGOPTIONS='-c default_transaction_read_only=on'
  open_rehearsal='
    SELECT allocation_id, exchange, venue, settlement_currency, symbol,
           SUM(CASE WHEN side = '"'"'BUY'"'"' THEN quantity ELSE -quantity END) AS net_base
    FROM ledger_entries
    WHERE exchange_fill_id LIKE '"'"'fake-fill-%'"'"'
    GROUP BY allocation_id, exchange, venue, settlement_currency, symbol
    HAVING SUM(CASE WHEN side = '"'"'BUY'"'"' THEN quantity ELSE -quantity END) <> 0'
  echo "== 1. open rehearsal allocations on an exchange with NO fee rate (must be empty) =="
  psql "$url" -X -A -F '|' -v ON_ERROR_STOP=1 -c \
    "SELECT * FROM ($open_rehearsal) t WHERE exchange NOT IN ('bybit', 'binance')"
  echo "== 2. every open rehearsal allocation (for the delivery log) =="
  psql "$url" -X -A -F '|' -v ON_ERROR_STOP=1 -c "$open_rehearsal ORDER BY 2, 1"
  ```

  If `psql` fails, it prints its own error, which never contains the password; read it before pasting anything anywhere.
- [ ] 9q.30 **Partly done 2026-10-04:** the owner pulled `4388590` as `strategy` and restarted both services; both are active. Point (1) is confirmed: the worker's journal has, at 2026-10-04 23:27:37 on the VPS clock, the INFO "dry run: the simulated exchange prices each fill at its alert's price and charges the venue's taker fee in USDT (binance=0.0005, bybit=0.00055)", and the same search returned no line naming a fixed price or a missing fee rate. Still to confirm, which is why this stays unticked: points (2) to (5), which need the first dry-run fill after the deploy. Owner step, after the merge: deploy 12g. `sudo -u strategy -H git -C /opt/strategy-manager/app pull --ff-only`, then `systemctl restart strategy-api strategy-worker`. No migration, so no rehearsal and no `alembic upgrade`. Only the worker's behaviour changes; the API process places no orders. Note the time of the first worker start on the new commit for the delivery log. **What to look at in the log after the first dry-run fill** (`journalctl -u strategy-worker --since <the restart time>`): (1) at start, one INFO saying each fill is priced at its alert's price and naming `bybit` with `0.00055` and `binance` with `0.0005`, and no WARNING naming a fixed price; if the startup pool list names a Pionex pool, expect the existing unserved-pools WARNING plus one reading "no simulated taker fee rate is defined for 'pionex'", once, and nothing else; (2) after the first dry-run open, one INFO per fill with the exchange, symbol, side, quantity, price, fee and client order id, where the price is the alert's own (compare it with the signal's price) and the fee is about quantity × price × the rate; (3) after the first close, the same line at the CLOSING alert's price; (4) no ERROR reading "close rejected by venue" or "order rejected by venue" with "no usable price" or "not quoted in it"; (5) the ledger agrees, with the same wrapper as 9q.29 and `SELECT price, quantity, fee, fee_currency, exchange_fill_id FROM ledger_entries WHERE exchange_fill_id LIKE 'fake-fill-%' ORDER BY filled_at DESC LIMIT 4`: price not 1, a non-zero fee in `USDT`, ids starting `fake-fill-`. A position that was open at the deploy reads entry 1 and closes at the alert's price: a large PnL that means nothing, marked and outside every total by decision 43. Update the delivery log after the merge and the deploy (the standing working agreement; this list writes no entry).

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: fakes and `caplog` for the unit tests of the adapter and the use cases; `httpx.MockTransport` with the frozen clock for the two registered real adapters; real PostgreSQL on the ORM schema for the refusals, the composition root and the webhook-to-ledger tests, through `main.build_worker_runner` and `run_once`; real PostgreSQL migrated to `head` for 9q.14 only. No test needs a credential or the network.
Rollback boundary: one revert of the whole PR; a partial revert would leave opens priced and closes refused. It restores the fixed price of 1 and the fee of 0 for NEW fills. The fills written meanwhile keep their alert price and their fee, and a dry-run position open across the revert has an alert-priced entry and an exit of 1, which decision 43's list reads `ALERT` (its § K names this case). No data is touched in either direction.
Actual: 3,546 changed lines in 19 code commits (3,494 net in `git diff`), about 480 of them production code and the rest tests; one unit, no size stop. Review Workload Forecast: 2,800–4,200 changed lines. `Decision needed before apply: No` · `Chained PRs recommended: No` (one PR, by design § L, and for a reason that is not size) · `Chain strategy: stacked-to-main` (sequential PRs to `main`, never stacked; this is the only PR of the unit) · `400-line budget risk: High`. Derived bottom-up: about 450 lines of production code (`fake_exchange.py` net 160, the rates module 30, the carriage through `ports`, `close_position`, `close_orphans` and `process_signal` 40, `main.py` 70, the docstrings 60, the arguments 30 and the glue 60), and tests at six to eight times that: the 35 one-line rate edits and imports 60, the 5 `CloseCommand` edits, 16 `CloseOrphans.close` calls and the doubles 90, the carriage tests 250, the rates tests 70, the real-adapter wire and built-order tests 380, the adapter's price, refusal, fee, quote and log tests about 850, the PostgreSQL refusals 330, the head test 90, the composition-root tests 380, the webhook-to-ledger, REVERSE, orphan and straddle tests 600. The design forecasts 900–1,400 assuming tests at four times 250 lines of code; in this change the test files have roughly doubled every earlier forecast (12e-1 was forecast 1,500–2,200 and re-derived to 3,600–5,200; 12x-3 was 1,627 against 550–800). Information only: no task stops, and none is split, for size.

### Unit 9qf — follow-ups to PR 12g (all eight built, 2026-10-05 and 2026-10-06; 9qf.5 to 9qf.8 were found while building the ones before them)

Recorded 2026-10-04. Found while building and deploying unit 9q; none was changed there.

- [x] 9qf.1 **The webhook accepts a price that is not a finite number.** `signals/domain/alert.py` converts the price with `Decimal(value)`, which accepts `"NaN"` without raising, and tests nothing for finiteness; the CHECK `price > 0` of migration 0002 does not exclude `NaN` (`Infinity` is refused by the column's range). Pinned by `backend/tests/signals/infrastructure/test_signal_price_head_constraint.py`. Consequence, in BOTH modes and older than PR 12g: an opening order with a `NaN` price raises `decimal.InvalidOperation` at build and its job is retried until its attempts run out. Since PR 12g a dry-run close with a `NaN` price is refused and the next opening alert closes the position. Fix: the ingress refuses a non-finite number with a 422 and persists nothing, for every numeric field of the alert, not only the price. RED first, on the route. Needs no owner decision; it is on the path that moves money, so it should not wait long. **Built on `fix/webhook-refuses-non-finite-numbers`, commit `3c8f08f`.** `_to_decimal` refuses `not number.is_finite()` with `NonFiniteNumberError` (an `AlertParsingError` carrying the field, message `<field> is not a finite number`, never the value); the route catches it first, logs ONE WARNING `webhook alert refused: <field> is not a finite number` (router logger) and answers 422; the requirement is the new delta `specs/signal-ingress/spec.md` of this change, "A Number That Is Not Finite Is Refused At The Webhook" (the first commit added a scenario to the MAIN spec `openspec/specs/signal-ingress/spec.md`, under the idempotency requirement; review moved it to the delta and left the main spec as it was, since a main spec changes only at archive). The other parse refusals (`AlertParsingError`) log NOTHING today and were left alone: a finding. **Before the fix, on the route** (registered strategy, head schema): `NaN` in `price`, `data.contracts` or `data.position_size` answered **200** and stored a signal and a job; `Infinity` in each answered **500** (the column's range refuses it, unhandled). A price of `"0"` or `"-1"` answers **500** too and stores nothing (the CHECK refuses it, unhandled): observed read-only, not changed. **RED:** route `assert 200 == 422` (NaN, 3 fields) and `assert 500 == 422` (Infinity, 3 fields), plus the name/log tests at `assert 200 == 422`; domain `assert None is not None` for 48 cases (3 fields x 8 spellings, two tests). **Mutations, each applied after the commit, seen red, reverted with `git checkout`:** check removed, 60 red (48 domain + 12 route); check on `price` only, 40 red (every `data.contracts`/`data.position_size` case); `is_nan()` instead of finiteness, 33 red (every infinity spelling in the domain, the 3 `Infinity` route cases). Docstring of `test_signal_price_head_constraint.py` updated (its assertions untouched). One existing test depended on the bug: `test_a_stored_nan_closing_price_is_refused_and_the_next_opening_alert_closes_the_orphan_at_its_own_price` posted a `NaN` price through the webhook to get it stored; it now posts a finite price and rewrites the row to `NaN` by SQL before the worker runs (a signal stored before the fix), every assertion unchanged (commit `d22e626`). Signals already stored with a `NaN` price, if any, are not read or rewritten.
- [x] 9qf.2 **CLAUDE.md, "Credentials: two keys, and they are not interchangeable", is stale.** Balance reads sign with the vault key (decision 18), not with a read-only key in `.env`. Found by the decision 45 design. Rewrite the section from the code as it is; a docs-only change, but CLAUDE.md is what every session reads first. **Done 2026-10-06.** The section is now "Credentials: one key per exchange, in the vault", written from the code and approved by the owner before the commit. Each claim was checked against its source: `shared/config.py` has no Bybit or Binance key field (only Pionex's pair, read by scripts alone), and `tests/shared/test_no_dotenv_credentials.py` pins it; every `vault.load` in `main.py` (orders, balance reads, `balance.sync`, reconciliation) reads the one vault key; `accounts/domain/key_policy.py` accepts a read-only key with `READ_ONLY_KEY`, refuses `WITHDRAW_PERMISSION`, and bases capability on the venue for Bybit and on the owner for Binance; `signals/application/process_signal.py` refuses an opening signal with `EXCHANGE_KEY_READ_ONLY` or `EXCHANGE_HAS_NO_KEY`; `accounts/application/ports.py` gives the API's write port no `load`; `worker.py` opens every sealed credential at startup; `backend/scripts/probe_credentials.py` prints `Signing as ***last4`. The key suffixes the old section named are gone: they could not be verified and the Binance key was rotated on 2026-09-30. **Also corrected, the same false statement in a second file:** `.env.example` said the Binance read-only key was load-bearing in live mode and that Binance's `balance.sync` signed with it; it listed `BINANCE_API_KEY` and `BYBIT_API_KEY` entries that nothing reads; and it said the worker never reads the vault under `DRY_RUN`, which `worker.py` contradicts (the startup self-test and `balance.sync` open the credential either way). It now says what the code does. Not established and so not written: the text of "decision 5", which the code cites for "the API never decrypts" and which is not the decision 5 of `owner-decisions.md`.
- [x] 9qf.3 **The panel's "alert price" sentence does not say what a dry-run result is.** It does not say that the row is sized at 1x or that its fee is simulated at the taker rate, so a dry-run PnL can be read as what the alert would have produced live. The wording is the owner's to decide; it belongs to unit 9p.5 (PR 12e-2), where the sentence is built. **Decided 2026-10-05** (owner-decisions.md, decision 45, last answer): both texts gain "It was sized at 1x and its fee is simulated at the taker rate, so its PnL is not what it would have made live." / "Se dimensionó a 1x y su comisión es simulada a la tasa taker, así que su PnL no es el que habría dado en real."; the spec and design § F's i18n table carry the full texts. Ticked when tasks 9p.5.13 and 9p.5.16 build them. **Built in both places:** the table's sentence in `cc0fbf2` (`rehearsalAlertNote`), the dialog's in `5c8c5f1` (`detail.rehearsalAlertHint`), texts exactly as design § F's table.
- [x] 9qf.4 A docstring left slightly stale by PR 12g: `test_a_close_carries_no_price_because_nothing_derives_a_size_from_one` still passes because the new field is named `reference_price`, but its text reads as if a close carried no price at all. Cosmetic. **Done 2026-10-06:** the docstring in `backend/tests/signals/application/test_process_signal.py` now says that `CloseCommand` has no field named `price`, that since PR 12g it carries `reference_price` (read only by the simulated exchange, sizing nothing, sent by no real adapter), and that the test pins the absence of a sizing price. Checked against `execution/application/close_position.py` and `ports.py`. No assertion and no name changed.
- [x] 9qf.5 **A price of zero or below answers 500 at the webhook.** Found building 9qf.1 (2026-10-05), observed on the route against a head-migrated database: an alert with `price` `"0"` or `"-1"` is refused by the CHECK `price > 0` at the insert, nothing catches the refusal, and the webhook answers an unhandled 500. Nothing is stored, so no money is at risk; but it is a bad request answered as a server fault, and a 500 is what the operator alerts are for. An infinity did the same until 9qf.1. Fix: the ingress refuses a price that is not above zero with a 422 that names the field, persists nothing and writes one WARNING, in the domain where 9qf.1 put the finiteness check. RED first, on the route (`assert 500 == 422`). To settle while building it: whether `data.contracts` and `data.position_size` have a sign rule of their own (a closing alert carries `position_size` `"0"`, so zero is valid there). Needs no owner decision. **Built on `fix/webhook-refusals-answer-422-and-log`, commit `7f8fc47`.** `TradingViewAlert.from_payload` refuses what the column would refuse, in the domain next to the finiteness check; `AlertParsingError` now carries an optional `field` and a fixed `reason` (a `log_text`), the router logs ONE WARNING `webhook alert refused: <field> <reason>` from it, and the requirements are two new ones in the delta `specs/signal-ingress/spec.md` (the main spec is untouched). **What migration 0002 says** (no later migration touches the table's numeric columns; 0003 adds the strategy FK, 0025 two status CHECKs): `price`, `contracts` and `position_size` are `NUMERIC(38, 18)`; the ONLY sign rule is `ck_signals_price_positive` (`price > 0`); `contracts` and `position_size` have no CHECK, so they keep accepting any finite number that fits (a test pins `"0"`, `"-1"` and `"-0.5"` accepted for each, on the route and in the domain). `symbol`, `action` and `signal_type` are unbounded `Text`. **Found while building (each answered 500 before):** a number with 21 integer digits (`"100000000000000000000"`, `"1E+20"`) in each of the three fields; a body that is not valid JSON (`request.json()` raises, nothing caught it: 5 spellings); a JSON body that is not an object (`[]`, `[{...}]`, `"alert"`, `5`, `null`, `true`: the parser called `.get` on it, 6 spellings). Beyond what the task listed, observed by a throwaway probe: `"1E-20000"`, `"0E+999999"` and `"0E-999999"` for a signed field answer 500 too (PostgreSQL's NUMERIC cannot receive a display scale above 16383), while `"0E+20"`, `"0E+140000"` and `"1E-16000"` are stored with a 200, so the exponent bound is 16383 and no tighter; a price above zero that rounds to zero at 18 decimals would hit the CHECK, and a value that rounds up past the last integer digit would overflow, so both are tested on the number as the column stores it (half away from zero). The 422 for invalid JSON and for a non-object body is chosen to match every other refusal of the route (and FastAPI's own `json_invalid`). **Before, on the route:** price `"0"`, `"-1"`, `"-0.5"`, `"0.0"` 500; 21 digits in each field 500; invalid JSON 500; non-object body 500. **RED (all assertions, none an import or constructor error):** route `assert 500 == 422` (4 price cases, 6 range cases, 6 exponent cases, 5 invalid-JSON, 6 non-object) plus the log tests at `assert 500 == 422`; domain `assert None is not None` (7 + 15 + 10 cases) and `assert False` for `isinstance(failure, AlertParsingError)` (8 non-object payloads, which raised `AttributeError`). The sign-rule, largest-number, exponent-accepted and above-zero-accepted tests passed at once and are proven by the mutations below. **Mutations, each applied AFTER the commit, seen red, reverted with `git checkout`:** `positive=True` on `contracts` made 16 red (the sign-rule tests, domain and route, and the exponent-accepted and largest-number tests that use `"0"`); the integer-digit bound lowered by one made 8 red (largest number, price accepted); the exponent bound lowered to 100 made 5 red; the router's range/price log call removed made 8 red; the invalid-JSON log call removed made 1 red. One existing test depended on the behaviour: `test_a_finite_number_is_still_accepted_for_every_field` (`test_alert_non_finite.py`) accepted `"-3.25"` for every field including the price, which the CHECK refuses; it now uses `"3.25"`, the assertion unchanged (negatives for the signed fields are pinned by the new tests). Not found by any test and left alone, the same class but outside this task: a NUL character (`\u0000`) in `symbol` or in `signal_param` answers 500, and a deeply nested body (100,000 `[`) answers 500; cause not investigated.
- [x] 9qf.6 **Every other refusal of a malformed alert is silent.** Found building 9qf.1 (2026-10-05): before it `signals/infrastructure/router.py` had no logger at all. A payload with no `data` object, a number that is not a string, a string that is not a decimal, a missing field and a `signal_type` that is not a UUID each answer 422 and write no line. TradingView shows the response of a webhook to nobody, so such an alert is lost without a trace; only the non-finite refusal (9qf.1) and an unknown strategy (unit 9xa) log today. Fix: one WARNING per refused alert, naming the reason and the field. It must not log the payload, and the existing "not a valid decimal string" message carries the raw value (`{value!r}`) in the 422 detail, which must not reach the log as it is. RED per refusal, asserting the line and its level. Needs no owner decision. **Built on `fix/webhook-refusals-answer-422-and-log`, commit `c811d25`** (after 9qf.5, `7f8fc47`). **How the log gets a safe text:** `AlertParsingError` now takes a REQUIRED `field` and a fixed `reason` next to its message, and `log_text` is `"<field> <reason>"` and nothing else; the message stays the 422 detail. Every raise in `alert.py` supplies both; missing keys go through one helper, `_required`, whose detail is the text it always had (`payload is missing required field 'price'`). The router logs `webhook alert refused: %s` with `exc.log_text`, and two more refusals of its own (a `signal_type` that is not a UUID, a blank idempotency key). **No existing 422 detail text changed**, and a test pins the unsafe one: `price is not a valid decimal string: 'MARKER-DECIMAL'` still answers in the response and never reaches the log. **The 401 path is untouched** (no line, tested). Unknown strategy keeps the one line unit 9xa gave it in `ingest_signal.py`, and the router adds none (tested). **Exact lines**, each ONE WARNING from the router logger unless noted: `webhook alert refused: body is not valid JSON` (router, 9qf.5); `body is not a JSON object`, `data is missing or not an object`, `<f> is missing`, `<f> is not a string`, `<f> is not a valid decimal string`, `<f> is not a finite number`, `<f> is not above zero` (price only), `<f> is out of range for the stored precision`, `<f> is empty or not a string`, `signal_type is not a valid UUID`, `idempotency key is missing`, where `<f>` is `data.action`, `data.contracts`, `data.position_size`, `price`, `symbol`, `signal_type` or `time` as each refusal applies. **Before, on the route:** each of the 24 malformed-alert cases answered 422 with no line. **RED (assertions):** route `assert [] == [('strategy_manager.signals.infrastructure.router', 30)]` for all 24 refusal cases and for the blank idempotency key (25); domain `assert None == '<field> <reason>'` for 31 cases (the log texts; the 2 detail-pin tests passed at once). The marker tests, the unknown-strategy count, the accepted-and-duplicate test, the 401 test and the detail-unchanged tests passed at once and are proven by the mutations below. **Mutations, each applied AFTER the commit, seen red, reverted with `git checkout`:** the raw exception text logged instead of `log_text` made 28 red (24 text tests, the 3 invalid-decimal marker tests and the detail test); a warning added before the 401 made 1 red; a second warning added to the unknown-strategy path made 2 red (this file's count test and `test_unknown_strategy_ingress.py`); a warning added on an accepted alert made 1 red; the decimal detail changed to omit the value made 1 red (the detail pin). Verification of the PR: ruff and mypy clean; `uv run pytest` 3,427 passed and 1 teardown error, the known `DROP DATABASE ... WITH (FORCE)` flake on `tests/migrations/test_0022_execution_attempt_origin.py`, which passed on re-run; collected 3,224 before, 3,427 after (+129 for 9qf.5, +74 for 9qf.6).
- [x] 9qf.7 **Two more inputs still answer 500 at the webhook.** Found building 9qf.5 (2026-10-05), observed on the route with a throwaway probe and not fixed there: (a) a NUL character (`\u0000`) in `symbol`, or inside the stored payload such as in `signal_param`, is refused by PostgreSQL at the insert (a `text` or `jsonb` value cannot hold it) and nothing catches the refusal; (b) a body nested 100,000 levels deep overflows the JSON parser's recursion before `from_payload` sees it. Both are the defect class of 9qf.5, a bad request answered as a server fault, and both need an authenticated sender, so neither is reachable from the open internet. Nothing is stored in either case. Fix: refuse each at ingress with a 422, persist nothing and write the one WARNING of 9qf.6, with no value in the line. RED first, on the route (`assert 500 == 422`). To settle while building it: whether the NUL is refused in every string field and anywhere in the payload that is stored raw, and whether the nesting is bounded by depth or the body by size. Needs no owner decision. **Built on `fix/webhook-refuses-unstorable-payload`, commit `861a196`.** The defect is a CLASS: a body that is authenticated, valid JSON and alert-shaped, and still cannot be STORED. `signals.raw_payload` is `JSONB` and `symbol`, `action` and `signal_type` are `text`; the idempotency key is hashed from `action` and `time` after parsing. **What was built:** `refuse_unstorable_body` in `signals/domain/alert.py`, called LAST in `TradingViewAlert.from_payload` so every refusal that already existed keeps its reason; one ITERATIVE pass with an explicit stack (a recursive walk would raise the `RecursionError` this removes), over every string, every object KEY and every float of the parsed body; the refusal is an `AlertParsingError` with `field` `body` and a fixed reason (`contains a character that cannot be stored`, `contains a number that is not finite`, `is nested too deeply`), the 422 detail is `body <reason>` and echoes no key and no value; the route catches `RecursionError` (that type only) where it calls `request.json()` and answers the depth refusal through the same `body_nested_too_deeply()` helper. The check is a NUL or a lone surrogate in a string (`"\x00" in s`, or `s.encode("utf-8")` raising), a float that is not `math.isfinite` (JSON `NaN`, the infinities and `1e999`, which Python parses to `inf`), or a container deeper than `MAX_BODY_DEPTH`. **No query, no lock and no migration were added.** The requirement is ADDED to the delta `specs/signal-ingress/spec.md` (the main spec is untouched) and the delta's introductory note was rewritten to say what the file now holds. **Observed BEFORE, on the route, database migrated to `head`, registered strategy, app raising so the exception type shows (status 500 below is that unhandled exception):** NUL (`\u0000`) in `data.action`, `symbol`, `time`, `signal_param`, an extra top-level key, an extra key inside `data`, a value nested in an object and in an array, a top-level object KEY and a nested object KEY: all **500** (`asyncpg UntranslatableCharacterError`, wrapped as SQLAlchemy `DBAPIError`), no row; NUL in `signal_type`: **422** `signal_type is not a valid UUID` (already refused, one line). Lone surrogate (`\ud800`): in `symbol` **500** (`asyncpg DataError`); in `signal_param`, an extra value, a nested value, `data` extra, a top-level key and a nested key **500** (`InvalidTextRepresentationError`, `jsonb` refuses the escape); in `data.action` and in `time` **500** as a `UnicodeEncodeError` raised by `derive_idempotency_key` (`str.encode("utf-8")`), a different layer; in `signal_type` **422** `signal_type is not a valid UUID`. `NaN`, `Infinity`, `-Infinity`, `1e999` and `-1e999` as an extra top-level value or inside an array: all **500** (`InvalidTextRepresentationError`; `json.dumps` emits the bare literal and `jsonb` refuses it). Already fine and still fine: `1e-999` (parses to `0.0`) **200**, `1e308` **200**, `-0.0` **200**, an integer of 4,000 digits **200** and of 5,000 digits **422** `body is not valid JSON` (Python's int-digit limit, a `ValueError`), the literal text `\\u0000` (a backslash and `u0000`, no NUL) **200**, non-ASCII text **200**, and the valid alert **200**. **Nesting, as arrays and as objects, through the route:** 10, 100, 1,000, 1,100, 1,500 and 2,000 levels **200** and stored; 3,000, 5,000, 7,000, 9,000, 9,500, 10,000, 12,000, 14,000 and 100,000 **500** (`RecursionError: maximum recursion depth exceeded while decoding a JSON array/object`). **Where each layer fails:** the JSON parser (`json.loads` inside `request.json()`) between 2,000 and 3,000 levels on the route (the request's own stack is already deep) and at 16,916 levels of arrays and 14,314 of objects outside it; the alert parser never (it is not recursive); the serialisation for the insert (`json.dumps`) at 15,506 levels of arrays and 9,304 of objects outside the request; the database was never reached past 2,000 levels, and accepted every body that reached it, so PostgreSQL's own limit was not found. **The bound chosen: `MAX_BODY_DEPTH = 64`** (the body is level 1, `data` level 2, so the alert's contract needs 2), with the reasoning in a comment next to the constant: 32 times the contract and about 30 times below the shallowest observed failure. An alert at 64 is accepted and one at 65 refused, as arrays and as objects, in the domain and on the route. **Size:** nothing in the application bounds the body. `request.json()` reads it whole, there is no middleware, no `Content-Length` check and no setting; an extra string of 1 MB and of 8 MB were both answered **200** and stored. Anything that bounds it today lives outside this repository (the tunnel or a proxy in front of the app), which was not inspected; observed and reported only, no limit added (see 9qf.8). **Observed AFTER (route, same inputs):** every row above that was a 500 now answers **422** and stores nothing (no signal, no job); the three exact lines, each ONE WARNING from the router logger and no value: `webhook alert refused: body contains a character that cannot be stored`, `webhook alert refused: body contains a number that is not finite`, `webhook alert refused: body is nested too deeply`. Nesting of 64 containers (a body 65 deep) and above, 1,000 and 2,000 included, answers 422 with the third line (those two answered 200 before: a body that deep is no longer accepted, by design); 10,000 and 100,000 are refused by the route's `RecursionError` catch with the same line. **One reason changed:** a NUL or a lone surrogate in `signal_type` still answers 422 with one line, but the line is now the body one rather than `signal_type is not a valid UUID`, because the new check runs inside `from_payload` before the router's UUID check; no assertion of an existing test depended on it. The `5000`-digit integer still answers `body is not valid JSON`. **RED (all assertions, no import, type or constructor error):** domain `assert None is not None` for 16 tests (NUL and surrogate placements 2, log text and detail 2, non-finite 3, one past the bound 2, far past the bound 6, depth refusal 1; the at-bound, valid-alert, wide-body and finite-number tests passed at once); route `assert 500 == 422` for 34 tests (NUL and surrogate in `data.action`, `symbol`, `time`, `signal_param`, extra values, keys and nested placements, the 5 non-finite literals, the 100,000 and 10,000 levels, the echo test and the parser test) and `assert 200 == 422` for 6 (1,000 and 2,000 levels, and 64), plus `AssertionError: 'webhook alert refused: signal_type is not a valid UUID' == 'webhook alert refused: body contains a character that cannot be stored'` for the 2 `signal_type` cases. The suite's collected count was 3,427 before this task and is 3,505 after it (+78: 27 domain, 51 route). **Mutations, each applied AFTER the commit with the Edit tool, seen red, reverted with `git checkout` of a clean tree:** the check removed (the call to `refuse_unstorable_body`): 53 red; the walk skipping object keys: 12 red (every key placement in both files, the log-text, detail and echo tests); the walk skipping nested values (not descending into containers): 37 red; the depth bound raised to 1,000,000: 15 red (1,000 and 2,000 levels, 64 and 65, and the 10,000 and 100,000 domain cases, which then recurse nowhere and are accepted); the raw key added to the log reason: 12 red; the route's `RecursionError` catch replaced by another type: 5 red (10,000 and 100,000 levels, arrays and objects, and the parser-detail test); the bound at 65: 5 red (one past the bound, and the depth refusal); the bound at 63: 5 red (every at-bound-accepted test); a check that refused non-ASCII text, `u0000` text, `{}` and numbers by mistake: every valid-alert, literal-backslash and finite-number test red, which proves those tests, all of which passed at once, are not vacuous. **Test files read back after writing, every escape confirmed:** `test_alert_unstorable_body.py` holds `NUL = "\x00"` and `SURROGATE = "\ud800"` as escapes; `test_unstorable_body_ingress.py` builds every body as explicit ASCII bytes with the escapes `\u0000` and `\ud800` written as raw strings and asserts that the bytes sent contain the six characters and no NUL byte (`b"\x00" not in body`), and the literal-backslash tests assert `b"\\\\u0000"` is in the body. The domain file's non-ASCII sample (`café 中文`) was stored by the Write tool as the characters themselves rather than as the `é` escapes written, which is equivalent for the test and valid UTF-8. **Existing files edited:** `alert.py`, `router.py` and the delta spec only; no existing test was edited. **Not built, recorded for the owner:** whether the route should also turn a database refusal at the insert into a 422 as a last line of defence. It would have to catch `sqlalchemy.exc.DBAPIError` (every case above arrived as that type, wrapping `asyncpg` `UntranslatableCharacterError`, `InvalidTextRepresentationError` or `DataError`, none of them an `IntegrityError`), which is also the base of a lost connection, a timeout and a deadlock, so a broad catch would answer a genuine server fault as a client error and hide it from the alerts a 500 raises. Narrowed to SQLSTATE class 22 (data exception) it would be safer, but it needs the asyncpg cause (`error.orig.__cause__.sqlstate`) and could still mask a bug of ours that builds a bad value. Recommendation: do not add it; every cause found so far is now refused by name in the domain and tested, and an unlisted case answering 500 is the signal that finds the next one. If the owner wants the net anyway: class 22 only, a rollback first, a distinct warning with the SQLSTATE and no value, and a counter so it is not silent. Verification: ruff and mypy clean; `uv run pytest` exit 0, collected 3,505.
- [x] 9qf.8 **Nothing in the application bounds the size of a webhook body.** Found by 9qf.7 (2026-10-06): `request.json()` reads the whole body, there is no `Content-Length` check, middleware or setting, and an extra string of 8 MB was stored with a 200 (the `raw_payload` column is `jsonb`, whose own limit is far above that). Any limit today is in front of the app (the Cloudflare tunnel or a proxy), which was not inspected. It needs an authenticated sender, and an alert is small, but a stored row of that size is read back by every query that selects `raw_payload`. Not a 500, so not part of 9qf.7. The limit and where it is enforced (the app or the edge) are the owner's to decide. **Decided 2026-10-06 (owner-decisions.md, decision 47): 65,536 bytes, enforced in the application.** **Built on `fix/webhook-bounds-body-size`, commit `c750933`** (the evidence below is the commit after it). **What was built:** `MAX_BODY_BYTES = 65_536` in `signals/infrastructure/router.py`, with its reasoning in a comment (a transport property, so not in the domain; a constant, not a setting, since the code has no setting pattern for a transport limit and the owner asked for none). `_read_bounded_body` reads `request.stream()` chunk by chunk with a running count of bytes received and raises `BodyTooLargeError` at the first chunk that takes the count past the limit; the body is never read whole and then measured. A declared `Content-Length` past the limit is refused before the stream is touched; a header that is absent, not an integer or smaller than what arrives is ignored by that shortcut and never raises (`int()` raising `ValueError` means "no early answer"), so the count is the authority. The bytes are parsed with `json.loads`, as `request.json()` does, so the existing 422s are unchanged. The refusal answers 413 with the fixed detail `request body is larger than 65536 bytes`, writes ONE WARNING from the router logger, `webhook alert refused: body is larger than 65536 bytes` (a fixed reason: no value from the sender, not the declared length), and stores nothing. Authentication is untouched and still first. The limit applies to this route only (no middleware). The requirement is ADDED to the delta `specs/signal-ingress/spec.md` ("A Body Larger Than 64 KiB Is Refused At The Webhook", 7 scenarios), the delta's introductory note and the warning requirement's list of refusals were updated, and the main spec is untouched. **Before, on the route (today's code), each input:** 65,537 bytes with `Content-Length`: **200**, stored; 8 MB: **200**, stored; streamed past the limit with no length: **200**, stored, the whole body pulled (4,096 chunks of 1,024 bytes for 4 MiB); declared 1 MiB with a generator body: **200**, stored, 1,024 chunks pulled; a lying-low or unparsable header on a body past the limit: **200**, stored. A body of exactly 65,536 bytes: **200**, stored (and still is). **After:** 65,537 bytes, 8 MB, streamed past the limit, declared past the limit and each lying or unparsable header on a body past the limit: **413**, no signal, no job, one WARNING; declared past the limit: 0 chunks pulled; streamed: exactly 65 chunks pulled, the 65th being the first to take the count past the limit (64 x 1,024 = 65,536 is within it), 4,031 never pulled; exactly 65,536 bytes, declared or streamed, and a body within the limit under any untrustworthy header: **200**, stored with a `raw_payload` equal to what was sent, no warning; an unauthenticated request (wrong or no secret) declaring or sending 8 MB or 128 KiB: **401**, 0 chunks pulled, no line. Invalid JSON (truncated, undecodable bytes, empty), a body that is not an object (`[]`, `null`) and a body nested 10,000 levels (the parser's `RecursionError`) answer the same 422 and the same one line as before. **What the test transport does with the header** (`httpx.ASGITransport`, read from its source): it feeds the application's `receive` from the request's stream, one chunk per call, and checks nothing about `Content-Length`, so a header passed by a test is delivered as written whatever the body is (a lying-low, empty, negative, `1e9`, `12 34` or 5,000-digit header all reach the route); a body built from an async generator carries NO `Content-Length` and `Transfer-Encoding: chunked`, which is how the streamed path is driven (`CountingBody` counts the chunks pulled, and the tests assert the header is absent and `transfer-encoding` is `chunked`). **What a real server does, observed with a throwaway probe (uvicorn 127.0.0.1, httptools parser, the production reader as the app, raw sockets; no file committed):** a `Content-Length` of `abc`, empty, `-5`, `1e9`, two conflicting `Content-Length` headers, or `Content-Length` together with `Transfer-Encoding: chunked`: **400 Bad Request** from the server, the application never runs; a header of 100 with 70,000 bytes sent: **400** (the 69,900 bytes after the 100 are parsed as a second request and refused, the application never sees an oversized body); a declared 70,000 with 100 bytes sent, or 8,000,000 with 100 sent: **413** at once, without waiting for the body; chunked with no length and 102,400 bytes: **413**. So the lying and unparsable header tests cannot happen against a real server and are pinned at the application's level only, as a defence that does not rely on the server; the streamed and declared paths do happen. **RED (all assertions, none an import, type or constructor error), 24 of 45 new tests:** `assert 200 == 413` (14: one byte past, 8 MB, a single first chunk past the limit, the 8 lying or unparsable header cases on a body past the limit, the echo test and the two one-warning tests), `assert 9 x 4096 == (65536 // 1024) + 1` (the streamed body pulled to its end: the plain streamed test, the 8 streamed-with-untrustworthy-header cases) and `assert 1024 == 0` (declared 1 MiB, the whole body pulled before any answer). Two more of the first draft failed on the draft's own wrong expectation of the existing detail text (`payload is not a JSON object`), fixed in the test before the GREEN. The other 21 passed at once and are proven by the mutations: exact limit (declared and streamed), the ordinary alert and its duplicate, a body within the limit under each of the 8 untrustworthy headers, the 4 unauthenticated cases and the 6 existing refusals. **Mutations, each applied AFTER the GREEN commit with the Edit tool, seen red, reverted with `git checkout` (never committed):** both checks removed: 24 red; `>` changed to `>=` in both: 19 red (exact-limit declared and streamed, the pulled-count of the streamed cases, the 8 within-limit cases); limit lowered by one (65,535): at least 30 red (every exact-limit test and every past-the-limit test that names the size); the streaming count removed so the early `Content-Length` refusal is the only check: 19 red (streamed, first-chunk, each lying or unparsable header on a past-limit body); whole body read with `request.body()` before measuring: 9 red, each on `assert 4096 == (65536 // 1024) + 1`; the bounded read moved before authentication (a crude mutation that also reads the body twice, so the whole file goes red), where the 4 unauthenticated tests are among the red ones, each on its own assertion (`assert 413 == 401` for the declared pair). **Existing tests edited, with the reason (no assertion relaxed, nothing deleted):** `test_unstorable_body_ingress.py` posted a body nested 100,000 levels deep (about 200 KB), which is now a 413 before it is parsed: the `levels` parameter `100_000` became `9_000` (a body of 9,000 levels of arrays or of objects is 18 KB or 54 KB, under the limit, and still overflows the JSON parser, which fails between 2,000 and 3,000 levels on the route) and the "beyond the JSON parser" detail test now sends 30,000 levels of arrays (60 KB) and asserts it is under the limit; a comment on each says so. The domain test of the same depth (`test_alert_unstorable_body.py`, 100,000 levels) does not go through the route and is unchanged. The delta spec's scenario for 9qf.7 now says 10,000 levels. **Verification:** ruff and mypy clean; `uv run pytest` exit 0 (no failure, no teardown flake this run); collected 3,505 before, 3,550 after (+45, all in `test_webhook_body_limit_ingress.py`). **Not built, recorded:** the accepted path gains no query and no lock; the limit is not a setting, so changing it is a code change. **Found and not fixed:** `request.stream()` is the only reader of the body now, so anything added later that reads `request.json()` or `request.body()` on this route after the stream is consumed would raise `RuntimeError: Stream consumed`; no such code exists and no test pins it. No other defect found.

### Unit tif — test infrastructure follow-ups (tif.1 done)

- [x] tif.1 **The teardown of a throwaway database fails more often than it used to, and two at a time.** Recorded 2026-10-09. The known flake, `asyncpg.exceptions.InsufficientPrivilegeError` ("permission denied to terminate process") on `DROP DATABASE ... WITH (FORCE)`, was one error in an occasional full run. On 2026-10-06 (the gate of 9qf.7) and again on 2026-10-09 (the gate of PR 12f-1's first batch) a single full run had TWO such teardown errors, each time in test files the branch did not touch, and each time the re-run was clean. No assertion failed in any of them. What is known: the server's own message says only a role with the privileges of the role that owns the backend may terminate it, so some backend connected to the throwaway database is NOT owned by the test role when the drop runs. What is NOT established: which backend. An autovacuum worker, which runs as the superuser, is the obvious candidate, and the number of throwaway databases per run has grown with every head-schema test, which would explain the rising rate; neither was measured. The drop helper `_drop_database_if_exists` is written out again in `tests/pg_head_schema.py` and in each migration test (`tests/migrations/test_0024` to `test_0027` at least), with no retry in any copy. To do: first find the backend (query `pg_stat_activity` for the database from the maintenance connection when the drop fails, and record its `usename` and `backend_type`), then fix the cause that shows: most likely one shared helper that retries the drop for a few seconds, or a throwaway database created with autovacuum off. Why it matters beyond the noise: a gate that goes red on its own teaches everyone to re-run without reading, and the day a teardown error hides a real one nobody will look. Needs no owner decision. **Done 2026-10-09, commits `92ffb26` (the helper and its tests) and `c10777b` (the 17 copies replaced).** **What the backend is (measured, not assumed):** an autovacuum worker. The test role is not a superuser and not a member of `pg_signal_backend`, so `pg_stat_activity` masks every column of a backend of another role but its pid, and the `backend_type` cannot be read directly. What was captured instead, with a plugin that logged `pg_stat_activity` and the `pg_stat_progress_analyze` / `pg_stat_progress_vacuum` views when the drop was refused, then retried the drop to time the refusal: 5 refusals over 30 runs (1 full run, which gave none, and 29 runs of the migration, reconciliation, ledger, allocation and webhook test files, 20 of them two processes at once), about one per 6 runs. Every one: exactly ONE row for the database, every column NULL (so a backend of a role the test role has no rights over, not one of its own); in the 4 cases where it was polled the pid showed first in `pg_stat_progress_analyze`, then in `pg_stat_progress_vacuum` (an ANALYZE then a VACUUM, which is what autovacuum does and nothing else connected to a database it was never told about does); and the refusal cleared by itself after 0.11, 0.14, 0.17 and 0.84 s. The 5 tests were `test_0024` (teardown, unpolled), `test_0020`, `test_0025`, `test_0028` and `test_0020` again. A synthetic provoker (684 short-lived clones, with and without the head schema, dropped at random times) never produced one: the window is the worker's few hundred milliseconds on a database that has just been migrated and written to. **Server facts (read-only):** PostgreSQL 17.9; `autovacuum` on, `autovacuum_naptime` 1min, `autovacuum_max_workers` 3, `autovacuum_vacuum_threshold` and `autovacuum_analyze_threshold` 50; the test role `strategy_manager` has `CREATEDB`, is NOT a superuser and is NOT a member of `pg_signal_backend`; the server's messages are localised (Spanish here). **The fix:** one helper, `backend/tests/pg_drop.py` (`drop_database_on(conn, name)` and `drop_database_if_exists(dsn, name)`), replacing every copy. It retries ONLY a refusal with SQLSTATE 42501 on a database the connected role owns (`pg_has_role(current_user, datdba, 'USAGE')`; recognised by state and ownership, never by message text, because the message is localised), every 0.1 s for at most 15 s (the largest measured clearing time was 0.84 s), and when the time runs out raises `DatabaseDropRefusedError` naming the database, the number of attempts and the backends `pg_stat_activity` lists (a backend the role cannot describe is named as "not visible to the test role: a backend of another role"), chained to the last refusal; the database is left behind and the test errors. Any other error, and a 42501 on a database the role does not own ("must be owner"), is raised at once and unchanged. No superuser, no grant, no server setting. **Refused:** creating the database so the worker does not connect (`ALLOW_CONNECTIONS false` would also stop the tests; autovacuum cannot be switched off per database, only per table, and the worker still connects), and `pg_signal_backend` for the role (it cannot signal a superuser's backend and would grant the role something). The only server-side alternatives are the owner's: `ALTER SYSTEM SET autovacuum = off; SELECT pg_reload_conf();` on a test-only cluster (it would switch autovacuum off for the dev database too, so it is NOT recommended). **Replaced copies (17) plus two inline statements:** `tests/pg_head_schema.py`, `tests/migrations/test_0020` to `test_0027`, `tests/ledger/infrastructure/test_append_only_guard.py`, `tests/reconciliation/infrastructure/test_discrepancy_repository_integration.py`, `test_booking_proposal_repository_integration.py`, `tests/reconciliation/application/test_scan_pools_integration.py`, `test_expire_booking_proposals.py`, `test_booking_prepare_integration.py`, `test_approve_booking_integration.py`, `test_reject_booking.py`; and the two inline `DROP DATABASE` statements of `tests/allocation/infrastructure/test_terminal_at_constraint.py` now call `drop_database_on` on the connection they already had. No other `DROP DATABASE` and no `_drop_database_if_exists` is left in any Python file under `backend/` (searched without regard to case; the only matches are the helper and its tests). Read back file by file: each diff is the copy deleted, each call renamed one for one, and one import added. **RED (assertions, against a stub that swallowed every error):** `assert 1 == 3` (retried until it works); `assert None is not None` (always refused: gives up and raises); `assert False` on `isinstance(None, BaseException)` (the error is chained); `isinstance(None, ObjectInUseError)` false (another error raised at once); `isinstance(None, InsufficientPrivilegeError)` false (a privilege error that is not the terminate refusal raised at once); `assert 1 == (1 + 1)` (works second time). **Mutations, each applied after the commit with the Edit tool, seen red, reverted with `git checkout`, never committed:** the retry removed (the deadline test forced true): 3 red; the bound removed (the deadline test forced false): the always-refused test red on `assert 'strategy_manager_test_fake_drop' in ''`, not hung, because the test wraps the helper in `asyncio.wait_for(..., 5.0)` and the 5 s cancel ended it; any `PostgresError` retried: 1 red (`isinstance(None, ObjectInUseError)`); the ownership check forced true: 1 red (the "must be owner" case). **Proof, with the fix in place:** three full runs in a row, exit 0, 0 errors each (3,672 tests collected per run, the 8 new ones included); no refusal occurred in them (observe-only plugin), so the retry was also exercised where it fires: 20 runs of the migration and reconciliation test files (10 and 10, run at the same time) saw 2 refusals (`test_0021` and `test_0025` teardowns) and all 20 exited 0. Before the fix those refusals were teardown errors.

### Unit whn — the webhook's name moves to the owner's domain (decision 49; owner-run, no code; whn.1 to whn.5 not started)

Every command here is run by the owner. The name `hook.strategymanager.trade` was confirmed by the owner on 2026-10-09.

**What the VPS looks like (read 2026-10-09 by the owner with a read-only script; values that could identify a secret were masked):**

- Debian 13. The API is `uvicorn ... --host 127.0.0.1 --port 8000 --proxy-headers`, with `FORWARDED_ALLOW_IPS=127.0.0.1` in the systemd unit.
- Not set in `backend/.env`: `BEHIND_CLOUDFLARE_TUNNEL`, `EXTRA_WEBHOOK_SOURCE_IPS`, `PANEL_DIST_DIR`, `WEBHOOK_PUBLIC_ORIGIN`, `CORS_ORIGINS`.
- Caddy v2.11.4 listens on 80 and 443, with no DNS module, so it gets its certificate over those ports. Its one site is the DuckDNS name: `/webhook/tradingview` and `/health` are forwarded to `127.0.0.1:8000`, everything else answers 404. The admin API is therefore not reachable from the internet.
- PostgreSQL and the API listen on the loopback only. The firewall (ufw) allows 22, 80 and 443 from anywhere and denies the rest.
- No DuckDNS updater was found in cron, systemd or `/opt`: the record was set by hand.
- Not installed: `cloudflared`, Node. `frontend/dist` is not built. These belong to the PR 9 prerequisites, not to this unit.

**How an alert is authenticated today, and after this unit (unchanged):** Caddy writes the client's address in `X-Forwarded-For`, uvicorn replaces the connection's address with it because the connection comes from `127.0.0.1`, and the allowlist judges that address. That Caddy overwrites a client's own `X-Forwarded-For` is its documented default and was not tested on this VPS.

- [ ] whn.1 **Create the DNS record.** In the Cloudflare dashboard, zone `strategymanager.trade`, DNS, Records: type `A`, name `hook`, IPv4 `159.195.148.136`, proxy status **DNS only** (the grey cloud). No `AAAA` record: TradingView has no IPv6. Check from any machine: `Resolve-DnsName hook.strategymanager.trade -Type A` must answer exactly `159.195.148.136`. An address of Cloudflare's means the record is proxied. Then Caddy would see Cloudflare's address as the client and every alert would be refused with a 401, which writes no line. Correct the record before going on.
- [ ] whn.2 **Add the name to Caddy, beside the DuckDNS name, and stop forwarding `/health`** (decision 49). As root on the VPS, one line at a time:

  ```bash
  cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-whn2
  sed -i -E '0,/^([A-Za-z0-9-]+\.duckdns\.org) \{/s//\1, hook.strategymanager.trade {/' /etc/caddy/Caddyfile
  grep -c 'duckdns.org, hook.strategymanager.trade {' /etc/caddy/Caddyfile
  sed -i -E 's#^([[:space:]]*@public path /webhook/tradingview) /health[[:space:]]*$#\1#' /etc/caddy/Caddyfile
  grep -c '/health' /etc/caddy/Caddyfile
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
  systemctl reload caddy
  ```

  The first `grep` must print `1` and the second `0`. Any other number means a line was not the shape expected: stop there and restore the copy. Reload only if `caddy validate` ends with `Valid configuration`. `/health` closes on BOTH names at this reload, because they share the site block. A reload keeps the existing site serving, and Caddy gets the new name's certificate by itself, which needs whn.1 to resolve first. To undo: `cp -a /etc/caddy/Caddyfile.before-whn2 /etc/caddy/Caddyfile && systemctl reload caddy`.
- [ ] whn.3 **Check the new name from the owner's machine.** No secret is involved:

  ```powershell
  curl.exe -sS -o NUL -w "%{http_code}\n" https://hook.strategymanager.trade/health
  curl.exe -sS -o NUL -w "%{http_code}\n" https://hook.strategymanager.trade/api/strategies
  curl.exe -sS -o NUL -w "%{http_code}\n" -X POST https://hook.strategymanager.trade/webhook/tradingview
  ```

  Expected, in order: `404`, `404`, `401`. The first is `/health`, closed by whn.2; the `401` comes from the application, so it also proves Caddy still reaches it. A certificate error instead of a number means Caddy has not obtained the certificate yet: wait a minute and repeat. These prove the name, the certificate and the path filter. They do not prove that an alert is accepted, because the owner's machine is not on the allowlist; only whn.4 proves that.
- [ ] whn.4 **Move the alerts in TradingView, one strategy at a time** (SFP, AAVE, STX). In each alert's webhook URL replace ONLY the host name; the path and the query string stay as they are. That URL holds the secret: it is never pasted into a chat, a ticket or a log. After each one, when its next signal fires, confirm it arrived, as root on the VPS:

  ```bash
  journalctl -u strategy-api --since "30 min ago" | grep 'POST /webhook/tradingview' | sed -E 's/\?[^" ]*//'
  ```

  It prints one access-log line per alert, ending in `200`, with the query string cut off (the application already masks the secret there; the cut is a second guard, so the output is safe to share). The line cannot say which name the request came through: the evidence is that the alert was edited before it fired. Do this while `DRY_RUN` is `true`, so an alert that goes missing costs nothing.
- [ ] whn.5 **Retire the DuckDNS name.** Only after every alert listed in TradingView's alert manager shows the new name and each strategy's alert has arrived once through it. As root, one line at a time:

  ```bash
  cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-whn5
  sed -i -E '0,/^[A-Za-z0-9-]+\.duckdns\.org, (hook\.strategymanager\.trade \{)/s//\1/' /etc/caddy/Caddyfile
  grep -c '^hook.strategymanager.trade {' /etc/caddy/Caddyfile
  grep -c 'duckdns' /etc/caddy/Caddyfile
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
  systemctl reload caddy
  ```

  The first `grep` must print `1` and the second `0`. Then watch each strategy's next signal arrive (the command of whn.4), and remove the domain at duckdns.org when convenient. **What fails silently here:** an alert left on the old name is refused at the TLS handshake and nothing on the VPS records it. TradingView's alert manager is the only list of what points where, which is why it is checked first and why this is done under dry run.
- [x] whn.6 **Tell the panel the new origin.** With the deploy of PR 12f-1 (task 12f.9.16), set `WEBHOOK_PUBLIC_ORIGIN=https://hook.strategymanager.trade` in `backend/.env` and restart the API. The setting does not exist before that deploy. **Done 2026-10-09 by the owner, with that deploy:** `GET /api/webhook-origin` answers the new origin. It was set BEFORE whn.1 to whn.5, so the name does not resolve yet; the setting is display only and no panel is served in production, and the alerts still arrive at the DuckDNS name.
- [x] whn.7 **Owner's question: whether `/health` stays public.** It answered `{"status": "ok", "dry_run": <bool>}` to anyone. **Answered 2026-10-09: close it.** The owner recalls no service outside the VPS that reads it. It is done inside whn.2, so the Caddyfile is edited once. The panel reads `/health` too, but through the tunnel, not through Caddy. If an outside monitor does exist and was forgotten, it will report the API down from that reload on; that is the symptom to recognise.

**Kept for the day the tunnel is taken up for the webhook (not planned):**

- `uvicorn` 0.52.1 (the version locked in `uv.lock`), with `FORWARDED_ALLOW_IPS=127.0.0.1`, takes the LAST address of `X-Forwarded-For` that is not a trusted one (`uvicorn/middleware/proxy_headers.py`, `get_trusted_client_address`). Cloudflare appends the real client's address at the end, so with the flag off the allowlist would work through the tunnel and through Caddy at the same time, and the alerts could be moved one by one.
- **Never set `FORWARDED_ALLOW_IPS` to `*`.** uvicorn then takes the FIRST address of the list, which a client can write itself when the proxy appends instead of overwriting. Harmless behind Caddy today; an allowlist bypass behind Cloudflare.
- The end state would still be `BEHIND_CLOUDFLARE_TUNNEL=true` with Caddy stopped and ports 80 and 443 closed: `CF-Connecting-IP` is the path this repository tests, and it is only trustworthy when the tunnel is the sole route to the port. The `X-Forwarded-For` path is a bridge for the move, pinned by no test here.
- Not verified: whether Cloudflare's bot protection lets TradingView's POST through. A test alert would show it.

---

### Unit alg — the API process writes its own log lines (found by the deploy of PR 12f-1; done and deployed 2026-10-10)

**Found 2026-10-09, by the check after the deploy of PR 12f-1 (#67).** The route `GET /api/webhook-origin` answered the configured origin, so the setting is read, and the journal of that same run of `strategy-api` held ZERO lines naming `WEBHOOK_PUBLIC_ORIGIN`, where task 12f.9.16 expected exactly one INFO.

**Cause, read in the code.** The worker configures logging at startup (`worker.py`, `_configure_logging`: `logging.basicConfig(level=INFO, ...)`). The API never does: `create_app()` in `main.py` installs the access-log redaction and silences the HTTP client's INFO lines, and nothing gives the root logger a level or a handler. uvicorn's default logging configuration (0.52.1, no `--log-config` in the unit) configures the `uvicorn`, `uvicorn.error` and `uvicorn.access` loggers only.

**Measured with a throwaway probe (not committed)**, after `logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)`: the root logger is at WARNING with no handler; an INFO line of a `strategy_manager.*` logger is dropped; a WARNING and an ERROR are written bare, through `logging.lastResort`; and once ANY handler is on the root logger, which is what `operator_alerts` installs when alerting is on, a WARNING and an ERROR are written nowhere by the process.

**What this means.**
- Every INFO line of the API is lost in production: the origin's startup line (12f.9.5), the line of a changed share (12f.9.6), the delete's line (9xf), the credential lines, "operator alerts are on".
- **Not established:** whether operator alerts are on in production. If they are, no WARNING of the API has reached the journal since they were turned on, the `webhook alert refused` lines of unit 9qf included, and an ERROR reaches Telegram only. The check recorded with fix 9qf.5 + 9qf.6 ("no `webhook alert refused` line in the last hour") would then prove nothing.
- The worker is not affected.

**Why the gate did not see it.** Every test of these lines uses `caplog`, which puts its own handler on the root logger and sets the level. The tests see a line production never writes.

- [x] alg.1 **Inventory before the fix.** List every line the API process starts writing once the root logger is at INFO with a handler: each `logger.info` reachable from the API (not the worker's), and each third-party logger that writes at INFO in this process (`sqlalchemy`, `asyncio`, `httpx`, `httpcore`, `starlette`, `fastapi`, `uvicorn`, any other imported). For each: when it is written (startup, per request, per write), and whether it can carry a value from a request, a credential, a DSN or a URL with a secret in it. **Stop and report, without deciding,** if a line is written per request on a route the panel polls, or if a line can carry any of those values. Record the list here.

  **Inventory, 2026-10-09 (read from the code; nothing stopped the unit).** Every `logger.info` and `logger.debug` under `backend/src` was listed with Grep, then checked for which process runs it, when it is written, and what it can carry. A throwaway probe (not committed) applied uvicorn's real logging configuration, put the root at INFO with a recording handler, built the real `create_app()` and ran `select 1` through the real engine: the only record seen was the probe's own.
  - **Startup, API, once per process:** the origin's line (`webhook_origin_check.py`: the normalised origin, or a fixed reason; never the raw value), "operator alerts are on" (`alerting.py`: a number of seconds). Nothing else logs at INFO in `lifespan`.
  - **Per write, API, operator-driven (never polled):** `save_credential` ("saved X credential (key ending last4)" and "enabled the pool"), `delete_credential` (the same hint and a pool key), `update_strategy` (a changed share, strategy id and two decimals), `delete_strategy` (id, the strategy's name, pool, counts, timestamps). The last4 hint is what rule 8 allows. The strategy name is the operator's own label read from the database, not a value of the request; the line was designed that way in unit 9xf.
  - **Per request, API, data-dependent:** `performance/application/scope.py` (`log_exclusions`, two INFO lines, counts only) and `read_strategy_trades.py` (one INFO, a pool label, a strategy id, a count). Written only when a read finds closed trades with no capital at open, an unconverted fee, or an undetermined rehearsal price. The panel does not poll these routes: the only `refetchInterval` in `frontend/src` are `/health` and the pools, 60 seconds each, and neither path reaches a `logger.info`.
  - **At most once per pool per TTL, API:** `binance/public_catalogue.py` and `bybit/public_catalogue.py` (a settlement currency, counts, elapsed milliseconds). A cache hit logs nothing, and the reads follow the strategy form's pair selector.
  - **Worker only (not the API):** everything in `worker.py`, `main.py` `log_simulated_exchange_startup`, `_track_degraded_exchanges` and the pool-transition line (called from the worker's builders), `fake_exchange.py` (the simulated fill, with an alert's symbol and `client_order_id`: the API places no orders), `settle_execution`, `approve_booking`, `booking_prepare_handler`, `prepare_booking`, `holding_guard`, `open_after_close`, `watchdog`.
  - **Third party at INFO, in this process:** `uvicorn.error` (its start-up lines) and `uvicorn.access` (one line per request, which uvicorn already writes today and whose query secrets `RedactQuerySecretsFilter` masks) both have `propagate: False` in uvicorn's configuration, so a root handler does not duplicate them. `sqlalchemy.engine` writes nothing at INFO with `echo` unset (measured). `httpx` and `httpcore` are set to WARNING by `silence_http_client_info_logs()`; their INFO lines carry the Telegram bot token and a Binance signature, so that call must keep running and the new function must not undo it. `asyncio`, `starlette`, `fastapi` and `pydantic` were not seen in the probe; the probe did not serve a request, so a line written only while serving one is not excluded by it.
  - **Verdict:** no line is written per request on a route the panel polls, and none can carry a credential, a DSN or a URL holding a secret. The unit goes on.
- [x] alg.2 **The API configures its logging.** One idempotent function in `shared/infrastructure/` gives the root logger a stream handler with the worker's format (`%(asctime)s %(levelname)-8s %(name)s: %(message)s`) and the level INFO. The API calls it before anything can log and before `operator_alerts` installs its bridge. It must NOT rely on `logging.basicConfig` doing nothing when the root logger already has a handler: pytest's capture handlers and the alert bridge are both such handlers. It recognises its OWN handler. The worker is not changed.
  RED first, on an assertion, against a stub of the function committed with the tests. **The tests run in a subprocess with a clean interpreter**, apply uvicorn's real logging configuration (through `uvicorn.Config`, so a uvicorn upgrade that changes it is followed), call what the API calls, and read the subprocess's stderr and stdout. `caplog` cannot test this unit. To pin:
  - an INFO line of an application logger is written, once, in the worker's format;
  - with a second handler on the root logger that writes nowhere (the alert bridge's stand-in), an INFO, a WARNING and an ERROR are each still written once;
  - the origin's startup line is written when `log_webhook_origin` runs under that configuration;
  - calling the function twice writes each line once;
  - an access line of uvicorn is written once, not twice, and the webhook's secret in its query string is still masked;
  - a line of `uvicorn.error` is written once;
  - an INFO line of `httpx` and of `httpcore` is NOT written (the Telegram URL holds the bot token, a Binance URL its signature), and a WARNING of each is;
  - the API calls the function before `operator_alerts` (the order, on the real `create_app` and `lifespan`).
  Tests that pass against the stub are proven by a named mutation applied after the GREEN commit, seen red, reverted with `git checkout`, never committed.

  **Evidence, 2026-10-09.**
  - **Built.** `shared/infrastructure/api_logging.py`: `configure_api_logging()` sets the root logger to INFO and installs one `ApiStreamHandler` (its own type, writing to the current `sys.stderr`, in the worker's format). It finds its own handler by type, so a handler already on the root logger (pytest's capture, the alert bridge) neither stops it nor is touched. `main.lifespan` calls it as its FIRST line, before `get_settings()` and before `operator_alerts`. The worker is unchanged.
  - **Why `lifespan` and not `create_app()`.** The order test passes with either place, so it does not decide. What decides: `app = create_app()` runs at IMPORT, and `worker.py` imports `main`, so the call would configure the worker's logging as a side effect of an import, and would put an INFO root logger and a stderr handler on every pytest session at collection. `lifespan` runs only when the API serves. Nothing logs between `create_app()` and `lifespan`.
  - **RED (commit `fda987c`, stub that does nothing, 20 tests).** 16 failed and 4 passed. Every failure is an assertion: `assert 0 == 1` on `len(lines)` for INFO in all three scenarios, for the WARNING and ERROR when a handler sits on the root logger, for the origin's line and for the twice-called INFO; `assert None is not None` on the worker's format for a WARNING and an ERROR the stub leaves to `logging.lastResort` (written bare), and for the `httpx` and `httpcore` WARNINGs; `assert {'own_handler': False, 'level': 30} == {'own_handler': True, 'level': 20}` in the order test; `0 != 1` handlers in the in-process idempotency test. None failed on an import, a constructor or a missing attribute.
  - **Passed against the stub, so proven by mutation** (applied after the GREEN commit `bfa8522`, seen red, reverted with `git checkout`, never committed):
    - an access line written once and masked: `uvicorn.access` `propagate = True` inside the function reds it (the line is written twice); removing `install_access_log_redaction()` from `create_app` reds it (the secret shows);
    - a `uvicorn.error` line written once: `uvicorn` `propagate = True` reds it;
    - the WARNING and ERROR of the twice-called test, and the in-process handler count: removing the "own handler already there" guard reds all four;
    - `httpx` and `httpcore` INFO not written: setting both to `NOTSET` inside the function reds both; removing `silence_http_client_info_logs()` from `create_app` reds both;
    - the order: moving the call to inside `async with operator_alerts(...)` reds the order test.
  - **GREEN (commit `bfa8522`).** 20 passed in about 5 seconds; `tests/shared` and the origin's test, 620 passed.
  - **Not covered, said plainly.** The tests do not serve a request through uvicorn's server: the access and error lines are emitted by hand on uvicorn's own loggers, which is the same path (`uvicorn.access` and `uvicorn.error`, their real handlers, their real filter). The alert bridge is a `NullHandler` stand-in, not the real bridge.
  - **Files.** Created `backend/src/strategy_manager/shared/infrastructure/api_logging.py` and `backend/tests/shared/infrastructure/test_api_logging.py`. Edited `backend/src/strategy_manager/main.py` (one import and the first lines of `lifespan`).
- [x] alg.3 **The requirement.** ADDED to the change's delta spec, under the capability that already owns the startup lines and operator alerting: the API process writes its own INFO, WARNING and ERROR lines to its standard streams whether alerting is on or off, each once. The main specs are untouched (`git diff main -- openspec/specs` is empty).

  **Evidence, 2026-10-09.** Added "The API Process Writes Its Own Log Lines" (eight scenarios) at the end of `openspec/changes/operator-panel/specs/admin-api/spec.md`. `admin-api` is the capability that already owns the origin's startup lines in this change's delta, and no spec in `openspec/specs/` or in the change's deltas names operator alerting, so there was no closer owner. The requirement says the lines are written whether alerting is on or off, each once; it keeps uvicorn's access and error lines once each with the secret masked; it keeps the HTTP client's INFO out. `git diff main --stat -- openspec/specs` is empty.
- [x] alg.4 **Gate.** `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`. Record the exit codes, the collected count before and after, and every existing test edited with its reason.

  **Evidence, 2026-10-09, run once at the end, in the foreground.** `uv run ruff check .` exit 0. `uv run mypy src` exit 0 (292 source files). `uv run pytest --tb=short` exit 0, `3784 passed in 346.31s`. Collected: 3,764 before this unit, 3,784 after (the sum of the per-file counts of `uv run pytest --co -q`; +20, all in `test_api_logging.py`). **No existing test was edited.** The lifespan tests of `test_startup_invariants.py`, which now run with the API's handler on the root logger, still pass.
- [x] alg.5 **Owner step, after the merge.** Pull as `strategy`, restart both services. No migration. Check: the journal of the new run of `strategy-api` holds exactly one line naming `WEBHOOK_PUBLIC_ORIGIN`; it holds "operator alerts are on" or it does not, which settles whether alerting is on in production; no line holds the webhook's secret or a token. **Done 2026-10-10 by the owner.** Merged as `2f4d738` (#68) with a merge commit, pulled as `strategy`, both services restarted. A read-only check on the VPS, over the journal of the new run of `strategy-api` (started 04:06:59 on the VPS clock): both services active on `2f4d738`; exactly ONE line naming `WEBHOOK_PUBLIC_ORIGIN`, INFO, in the worker's format, with the origin of decision 49; ONE "operator alerts are on" line, so **alerting IS on in production**; 6 lines in all, 2 of them the application's INFO, no WARNING, no ERROR and no `webhook alert refused`; no unmasked webhook secret, no Telegram URL and no database URL. **What that settles about the past:** for as long as alerting has been on (since when was not established), no WARNING of the API reached the journal before this deploy. If it was on by 2026-10-06, the check recorded with fix 9qf.5 + 9qf.6 ("no `webhook alert refused` line in the last hour") could not have shown one and proves nothing. Whether an alert was refused before this deploy is not known from the journal; a refused alert stores no row, so the database does not say either. The bridge forwards an ERROR to Telegram, so that channel was not affected.

Rollback boundary: one revert. It returns the API to writing no line of its own. No data is touched.

## PR 12f — The detail page's follow-ups (decisions 44 and 48) (2,000–3,000 lines backend; 4,500–6,500 panel)

Two sequential PRs to `main`, never stacked: **12f-1** (unit 12f.9, backend) → **12f-2** (unit 12f.10,
panel). Each merges and deploys before the next branch is cut. Source of truth: design.md, "Addendum:
the detail page's follow-ups (unit 12f, decisions 44 and 48) - 2026-10-06" (§§ A to O, with B2, C2 and
C3; no question is open), owner-decisions.md decisions 44 and 48, and the requirements added on
2026-10-06 to `specs/operator-panel/spec.md`, `specs/admin-api/spec.md`,
`specs/performance-reporting/spec.md`, `specs/capital-allocation/spec.md` and
`specs/strategy-lifecycle/spec.md`. This section turns tasks 12f.1, 12f.4, 12f.5, 12f.6 and the WIN RATE
column into the tasks below; the stub list of unit 12f points here, and 12f.2, 12f.3 and 12f.7 are closed
by decision 44 with no work.

**Why two PRs, and not for size** (design § L). (1) The panel refuses a `by_pair` entry that lacks the
new fields and reads two routes that must exist, so the API has to be merged and running before the
panel that asks. (2) The panel PR is the one the owner reviews by eye, and that review should not hold a
finished backend change. The risks differ too: 12f-1 is **low** (additive fields, two read-only routes,
a setting that cannot stop the start; the preview reads two rows, takes no lock and touches no code of
the allocation path), 12f-2 is **medium** (the first control of the panel that changes how much capital
a strategy asks for). Nothing is split to fit a line budget.

**No migration.** The share's column exists since migration 0007; a win is derived at read time; the host
is a setting; the pool's minimum and its snapshot are existing columns. The "Migration rehearsal" section
does not change and nothing here is rehearsed on the VPS. **No venue is read and no probe is needed.**

**Out of scope, by design** (§§ C, C3, M): a per-pair minimum order (a known limit of the unit: the
exchange's minimum for a pair needs a price and a leverage the API process does not have; the sentence
that says so is behind the amount's information button, and no later unit is recorded for it); the
share in the page's header line or in a Strategies list row (Q3, answered no); `NewStrategyDialog`,
which keeps registering with `"100"`; a history of share changes on screen (the INFO line is the only
trace); the OPEN column of By pair; a win rate on the strategy or pool report; any change to the
worker, `decide()` or the allocation path.

**Deploy order** is the reason for the order of the PRs: 12f-1 first (the older panel keeps working
against the new API, design § G), 12f-2 only after 12f-1 is deployed.

Rules that bind every unit here, on top of the cross-cutting rules:

- **RED fails on an ASSERTION.** A new function, field, route, hook or component is first added as a stub
  that compiles and answers WRONGLY (`win_count` 0 and `win_rate` 0; a parser that returns its input; a
  route that always answers `null`; a preview whose every amount is zero and whose
  `below_pool_minimum` is always false; a copy that reports success without writing; an input with a
  fixed `size` of 12 and the sign before it; a button rendered with `aria-expanded="false"` that never
  opens; an amount line that prints the first step's figure for every value), in the same commit as
  the RED test. The first failure is never an `ImportError`, a `TypeError`, a type error or, in the
  frontend, a `getBy` that throws before an expectation runs: a frontend RED asserts with
  `expect(screen.queryBy...(...)).toBeInTheDocument()`, `toEqual` or `toHaveAttribute`. Where the wrong
  behaviour is "no exception is raised", the test captures the exception and asserts on its type.
  **Each task records the assertion it failed on** (for example `assert 0 == 3`). A RED that cannot be
  written on a stub is a task that says so and names the mutation instead.
- **A test that passes at once is proven non-vacuous by the mutation its task names** (design § K's
  table). The mutation is applied AFTER the GREEN is committed, seen red, and reverted with
  `git checkout`; it is never committed. The task records what was seen.
- **Source and test files are changed only with the Edit and Write tools, never through `node -e`,
  `python -c`, a shell here-string or any script, mutations included.** A script-embedded rewrite dropped
  a backslash from a regular expression in this change with the gate green. The writer prompt of every
  delegated task says so.
- **A refactor of an existing function gets its regular expressions and escapes read in the diff;**
  "behaviour unchanged" is proven by tests that would notice. New code with a regular expression
  (`share-value.ts`, the origin parser) gets the same read of its diff.
- **No `style` prop anywhere in the panel**, and the source guard that pins it (12f.10.29). Every
  position that depends on a value is an SVG geometry attribute or a fixed class.
- **No money is computed in the browser.** The amount, the pool's minimum and the amount inside the
  warning are the strings the server served, cut down as text to the currency's decimals. The only
  arithmetic the control does is the handle's position and its rounding, which is not money.
- **Every string goes through i18n in EN and ES, with the exact texts of design § I**; no wording is
  invented. The two owner's own words are "Saved" / "Guardado" and "Copied" / "Copiado".
- **Palette tokens only** (`gain`, `rule`, `rule-strong`, `ink`, `ink-2`, `ink-3`, `loss`, `panel`,
  `ground`; no hex and no `var()` in a `className`). **The amber allow-list of `panel-tokens.test.ts`
  does not change**: none of the new components uses `decision` (design § I); if one does, the existing
  guard goes red and the task records why before touching the list.
- **A new requirement goes in this change's delta specs, never in a main spec.** None is expected: if
  building one of these tasks finds a behaviour no requirement states, the task adds it to the delta
  spec it belongs to and records it, as 9qf.5 did.
- **Existing tests are edited only as a task records;** nothing is deleted and no assertion is
  relaxed. The recorded edits of the unit are: the two `PairStats(` constructor calls of
  `test_by_pair.py` (12f.9.1); the `by_pair` builders of the panel tests and the header assertion of the
  By pair table (12f.10.1, 12f.10.4); the fetch doubles of the page tests, which must answer the two new
  GETs and a PATCH, and the one existing test that clicks every other button (12f.10.24); and the
  add-only line of the secret sweep's route walk (12f.9.13). Any other edit is recorded in its task with
  the reason.
- **Where the `head` schema is needed: nowhere.** Every integration test here reads rows by their keys or
  walks a ledger, and no constraint or index that the ORM schema lacks decides an outcome. They use the
  ORM schema of `tests/performance/infrastructure/conftest.py` (the by-pair end to end) and of
  `tests/ledger/infrastructure/conftest.py` (`pg_session_factory`, `seed_strategy`; the pool rows,
  snapshots and strategies of the preview), as `test_pools_router.py` does. If building one finds a
  constraint that decides the outcome, that test moves to `tests/pg_head_schema.py` and says why in its
  docstring.
- **The lock-hold harness applies once, the other way round.** The preview and a share change take no pool
  lock, so there is no second actor that must wait: the harness of
  `tests/strategies/infrastructure/test_delete_strategy_concurrency.py` holds the pool's advisory lock on
  a second connection and the test asserts the request COMPLETES (`task.done()`) while it is held; a later
  edit that makes either queue behind an allocation turns it red (12f.9.8, 12f.9.12). A barrier with
  `sleep(0)` is not used.
- **Symbol spellings across a module boundary.** The wins cross one (a closed operation is derived from
  fills): the real fills of the integration test are written `STXUSDT.P` on the opening side and
  `STXUSDT` on the closing side, a second strategy's as `STXUSDT_PERP`, and the report is asserted under
  the pair `STXUSDT`; no assertion compares two spellings as text (12f.9.2). The pool key
  `(exchange, venue, settlement_currency)` is the other boundary the preview crosses, and two strategies
  on two pools are always asserted against each other (12f.9.11, 12f.9.12).
- **One shared list of origin cases.** The backend's accepted cases, normalised, are the panel's accepted
  cases: one JSON file, `frontend/src/features/strategies/webhook-origin.cases.json` (the name is this
  list's; the precedent is `webhook-message.fixture.json`, which a backend test also reads), is asserted
  by `test_webhook_origin.py` (12f.9.3) and by `webhook-url.test.ts` (12f.10.8), so the two checks cannot
  drift apart silently.
- **The failure-mode table of design § J, mapped to the task that tests each line and its level.** No
  line carries the webhook secret, a credential, a DSN, the raw text of a refused setting, or a value
  from a sender: ids, counts, the setting's name, the reason and the share's old and new value only.

  | § J failure | Level and line | Test task |
  |---|---|---|
  | A share changes and nobody can tell when or from what | INFO from `UpdateStrategy`, only on a real change: strategy id, old value, new value | 12f.9.6 |
  | The same share written differently, another field patched, or a refused update | no share line | 12f.9.6 |
  | The PATCH refuses (archived, unknown id, out of range) | no line from the use case; the 4xx is in the access log | 12f.9.7 |
  | `WEBHOOK_PUBLIC_ORIGIN` unset | INFO at startup, once, saying the panel shows the path only | 12f.9.5 |
  | `WEBHOOK_PUBLIC_ORIGIN` malformed | **ERROR at startup, once**, naming the setting and the reason, never the value; the API starts; the route serves `null` | 12f.9.4, 12f.9.5 |
  | `WEBHOOK_PUBLIC_ORIGIN` well formed | INFO at startup with the normalised origin | 12f.9.5 |
  | The origin carries a credential | refused, the ERROR names no value; no log record contains it | 12f.9.5 |
  | A rehearsal trade reaches `by_pair` | the existing 500 and ERROR of `require_live_only` | 12f.9.2 (the existing tests run unmodified) |
  | A win is miscounted (a zero counted, a dry-run operation counted) | cannot be logged; a test with a mutation per case | 12f.9.1, 12f.9.2 |
  | A strategy's pool has no row in `capital_pools` | 500 and ONE ERROR naming the strategy and the pool | 12f.9.12 |
  | A stale snapshot, or a pool with no snapshot | nothing logged by this read: no line per page view | 12f.9.12 |
  | The preview and the engine disagree on the minimum | cannot be logged; an agreement test just under, at and just over the limit | 12f.9.9, 12f.9.12 |
  | The preview takes a lock, calls a venue or writes | cannot be logged; the lock-hold test and a row-count test | 12f.9.12 |
  | The new routes ship without auth | 401 before the handler | 12f.9.4, 12f.9.12, 12f.9.13 |
  | The panel sends a wrong value, "Saved" shows although nothing was saved, the clipboard holds something else, an information button does nothing, a win rate disagrees with its counts, a `style` prop is added | the browser has no log: each is pinned by a test and a mutation | 12f.10.16 to 12f.10.29 (the table in 12f.10.30) |

- **Commits.** One work-unit commit per task, or per RED/GREEN pair where a red commit would break the
  gate, as 9xd.1 and 9p.4.34 did; the RED is observed and recorded either way. `git commit -F <file>`
  with a fresh BOM-less message file written with the Write tool and read back before the commit;
  conventional commits; no AI attribution anywhere.
- **No size rule.** The owner does not want work split by size. The forecasts below are information only.
- **What fails here without a log line?** is answered by the table above and by design § J. A figure that
  cannot be derived is absent with the state that says why, never zero.

### Unit 12f.9 — backend: wins, the webhook's origin, the share's log line and notation, the share preview — PR 12f-1

**Needs**: nothing unmerged. It does NOT need the panel.

**Files**:
Create `backend/src/strategy_manager/signals/domain/webhook_origin.py`,
`backend/src/strategy_manager/signals/infrastructure/webhook_origin_router.py`,
`backend/src/strategy_manager/signals/infrastructure/webhook_origin_check.py`,
`backend/src/strategy_manager/allocation/domain/share_preview.py`,
`backend/src/strategy_manager/allocation/application/preview_share.py`,
`backend/src/strategy_manager/accounts/infrastructure/pool_sizing.py`.
Modify `backend/src/strategy_manager/performance/domain/by_pair.py` (`PairStats`),
`backend/src/strategy_manager/performance/infrastructure/performance_router.py` (`PairBody`),
`backend/src/strategy_manager/strategies/application/update_strategy.py`,
`backend/src/strategy_manager/strategies/infrastructure/router.py` (`StrategyView`, the `share-preview` route
and its dependency), `backend/src/strategy_manager/allocation/application/ports.py` (`PoolSizing`,
`PoolSizingPort`), `backend/src/strategy_manager/shared/config.py` (`webhook_public_origin`),
`backend/src/strategy_manager/main.py` (the origin router under `/api`, `log_webhook_origin` in `lifespan`),
`.env.example` (one documented line).
Create `backend/tests/signals/domain/test_webhook_origin.py`,
`backend/tests/signals/infrastructure/{test_webhook_origin_router,test_webhook_origin_check}.py`,
`backend/tests/allocation/domain/test_share_preview.py`,
`backend/tests/allocation/application/test_preview_share.py`,
`backend/tests/accounts/infrastructure/test_pool_sizing.py`,
`backend/tests/strategies/infrastructure/{test_share_preview_router,test_share_change_integration}.py`,
`backend/tests/performance/infrastructure/test_pair_wins_router.py`,
`frontend/src/features/strategies/webhook-origin.cases.json`.
Modify `backend/tests/performance/domain/test_by_pair.py` (new tests, and the two recorded constructor
edits of 12f.9.1), `backend/tests/strategies/application/test_update_strategy.py` and
`backend/tests/strategies/infrastructure/test_router.py` (new tests only),
`backend/tests/signals/application/test_open_after_close.py` (one new test),
`backend/tests/signals/infrastructure/test_webhook_secret_router.py` (add-only, 12f.9.13).

**Wins** (design § G; spec: performance-reporting "A Pair's Win Rate Counts Closed Operations With A PnL
Above Zero", admin-api "The Strategy Performance Route Serves Each Pair's Wins And Win Rate")

- [x] 12f.9.1 `PairStats.win_count` and `PairStats.win_rate` in `performance/domain/by_pair.py`. RED
  `backend/tests/performance/domain/test_by_pair.py`, new tests, with the stub in the same commit:
  `PairStats` gains `win_count: int` and `win_rate: Decimal`, no default, appended after `value`, and
  `by_pair` fills them with `0` and `Decimal(0)`. Tests, hand-built `ClosedTrade`s through the file's own
  `_trade`: `::test_a_win_is_a_pnl_above_zero_and_the_rate_is_wins_over_trades` (SOLUSDT +4.10, +0.80,
  +2.00, 0 and -1.25: 5 trades, 3 wins, rate `Decimal("0.6")`), `::test_199_wins_in_200_are_a_rate_below_one`
  (0.995), `::test_a_pair_with_no_win_has_a_zero_rate_and_a_pair_that_won_every_operation_has_a_rate_of_one`,
  `::test_a_trade_with_incomplete_fees_and_a_trade_with_no_capital_at_open_are_counted` (`fees_complete=False`
  and `capital=None`, each by the PnL it has), `::test_two_spellings_of_one_market_are_one_pair_with_its_wins`
  (through `derive_trades`, opened `SOLUSDT.P`, closed `SOLUSDT`, a second allocation `SOLUSDT_PERP` then
  `solusdt`), `::test_a_pair_removed_from_the_allowlist_keeps_its_wins`. RED against the stub:
  `assert 0 == 3`, `assert Decimal('0') == Decimal('0.6')`, `assert Decimal('0') == Decimal('0.995')`.
  **Passing at once** (the stub's zeros are the right answer): `::test_a_pnl_of_exactly_zero_is_not_a_win_and_counts_in_the_total`
  (two trades at 0: 2 trades, 0 wins, rate 0) and the zero-win half of the first test; mutations, applied
  after the GREEN: `>` becomes `>=` (reds the zero test and the 3-of-5 test), the zero trade dropped from
  the denominator (reds the 3-of-5 test: 3 of 4 is 0.75), and either the incomplete-fees trade or the
  no-capital trade filtered out of the count (reds the counted test). GREEN: `win_count` is the number of
  trades with `pnl > 0`, `win_rate` is `Decimal(win_count) / Decimal(trade_count)`, the divisor always at
  least 1 because a row is built from at least one trade; nothing is rounded here (the wire rounds).
  **Recorded edit of two existing tests** (the fields have no default, so the constructor needs them):
  `test_by_pair.py::test_solusdt_dot_p_and_solusdt_merge_into_one_pair` line 83 gains
  `win_count=2, win_rate=Decimal(1)` (its two allocations close at +5 and +3) and
  `::test_trades_without_capital_count_in_pnl_but_have_no_return` line 141 gains `1, Decimal(1)` (its one
  SOLUSDT trade closes at +7); no other line of either test changes, and both pass unmodified apart from
  that. Run `tests/performance` whole: every other existing suite passes unmodified.
  **Done (commit `c8afc19`).** RED against the stub, observed: `assert 0 == 3` (3-of-5 test, `win_count`),
  `assert 0 == 199`, `assert 0 == 2`, `assert 0 == 1`, and the two edited constructor tests failed on
  the PairStats equality. Passed at once, as predicted: the exactly-zero test. Mutations, each seen red
  and reverted with `git checkout`: `>` to `>=` reds the 3-of-5 test and the zero test; the zero trade dropped
  from the denominator reds the same two; `and t.fees_complete` on the count reds the counted test; `and
  t.pool_total_at_open is not None` reds the counted test and
  `test_trades_without_capital_count_in_pnl_but_have_no_return`. Edit recorded: the first constructor call
  now spans lines (`win_count=2, win_rate=Decimal(1)` on their own lines) because one line would pass the
  100-column limit; the second gains `1, Decimal(1)`. One new test name needs `# noqa: E501`. `tests/performance`
  whole passes.
- [x] 12f.9.2 `PairBody.wins` and `PairBody.win_rate` on the wire. RED
  `backend/tests/performance/infrastructure/test_pair_wins_router.py` (Create, real PostgreSQL, the ORM schema of
  `tests/performance/infrastructure/conftest.py`: the report is a read and no constraint decides it), with
  the stub in the same commit: `PairBody` gains `wins: int` (the count as an integer) and
  `win_rate: Ratio`, and `PairBody.of` fills them with `0` and `Decimal(0)`. One ledger fixture writes the
  real fills with the spellings of the rule above and asserts every entry under the pair `STXUSDT`.
  Tests: `::test_a_pair_carries_its_wins_and_its_rate` (5 closed operations: 3 above zero, 1 at exactly zero,
  1 below: `"trades": 5`, `"wins": 3`, `"win_rate": "0.6000000000"`, and `pair`, `pnl`, `return` still
  present), `::test_a_pair_with_no_win_has_a_zero_rate_not_a_null` (`"wins": 0`, `"0.0000000000"`),
  `::test_a_pair_that_won_every_operation_has_a_rate_of_one` (`"1.0000000000"`),
  `::test_a_win_count_never_exceeds_the_trade_count_in_any_entry`,
  `::test_no_pair_row_is_served_for_a_pair_with_no_closed_operation` (an open operation only),
  `::test_each_by_pair_entry_carries_exactly_the_documented_keys` (`pair`, `trades`, `wins`, `win_rate`,
  `pnl`, `return`: no other), `::test_the_strategy_and_pool_reports_gain_no_win_rate` (neither body carries
  `wins` or `win_rate` outside `by_pair`), `::test_two_strategies_on_two_pools_are_not_blended` (S1 on
  `bybit/usdt-m/USDT`, S2 on `binance/usdt-m/USDT`, both on `STXUSDT`, each rate from its own operations),
  `::test_the_wins_are_the_same_with_and_without_rehearsal_groups_in_the_ledger` (3 closed dry-run
  operations above zero on the same pair change nothing). RED: `assert 0 == 3` on `wins`,
  `assert '0.0000000000' == '0.6000000000'`. **Passing at once**: the key set, the no-win report test, the
  open-operation test, the two-pool test (the stub's zeros are right for a pair that never wins, so that
  test also asserts the winning pool) and the rehearsal test; mutations: a `wins` key renamed (key set), a
  `win_rate` added to `PerformanceBody` (no-win-rate test), the read concatenating `groups` and
  `rehearsal_groups` (decision 43's own mutation, the rehearsal test), the pool taken from the first
  strategy (two-pool test). GREEN: `PairBody.of` serves `stats.win_count` and `stats.win_rate`
  (`Ratio`: 10 places, half-even, plain). Existing performance router tests (including
  `test_get_strategy_performance_includes_by_pair` and the JSON-float walk) run unmodified; if one asserts the
  exact key set of a `by_pair` entry, the task records the edit and the reason.
  **Done (commit `f4fc849`).** RED against the stub, observed: `assert 0 == 3` on `wins`;
  `assert [(1, 0), (3, 0)] == [(1, 1), (3, 1)]`; the tuple comparisons of the two-pool and rehearsal
  tests failed on the stub's zeros (`wins` 0 against 1, `win_rate` `0.0000000000` against `0.5000000000`).
  Deviation: the rehearsal test and the two-pool test assert a winning pair, so they fail on the stub rather
  than passing at once (stronger, still mutation-proven). The Binance pool is not seeded by the shared
  fixtures, so the two-pool test inserts its row. No existing performance test was edited. Mutations seen red,
  each reverted: `wins` renamed `win_count` (key-set test and the others), `groups + rehearsal_groups` in
  `ReadStrategyPerformance.read` (rehearsal test only), `win_rate` added to `PerformanceBody` (no-win-rate test
  only), pool forced to Bybit in `_strategy_pool` (two-pool test only; the last two re-run on the clean tree
  after the interruption).

**The webhook's origin** (design § F; spec: admin-api "The Webhook's Origin Is Served By Its Own Route")

- [x] 12f.9.3 `parse_webhook_origin` in `signals/domain/webhook_origin.py`. RED
  `backend/tests/signals/domain/test_webhook_origin.py` (Create), with the stub in the same commit:
  `InvalidWebhookOrigin(Exception)` and `parse_webhook_origin(raw: str) -> str | None` that returns its
  input. The same commit creates `frontend/src/features/strategies/webhook-origin.cases.json`: `accepted`
  (`{"raw", "origin"}` pairs: `https://example.org` and `http://localhost:8000` as written; `HTTPS://Example.ORG`,
  `https://example.org/` and `https://example.org:443` to `https://example.org`), `unset` (`""`) and
  `refused` (no scheme `example.org`, `ftp://example.org`, `https://`, a path `https://example.org/hook`,
  a query `https://example.org?x=1`, a fragment `https://example.org#top`, a user `https://user@example.org`,
  `https://user:pass@example.org`, a space `https://exa mple.org`, a control character, a backslash
  `https://example.org\x`, a host outside ASCII `https://exämple.org`, a port out of range
  `https://example.org:99999`, a port that is not a number `https://example.org:abc`, and the three forms
  design § O settled: a bracketed IPv6 literal `https://[::1]`, a host that ends in a dot
  `https://example.org.` and a present-but-empty port `https://example.org:`). Tests, parametrized
  over the file (the test reads it through the repository root, as `test_webhook_message_fixture.py` does):
  `::test_an_accepted_origin_is_normalised`, `::test_an_empty_value_is_unset_and_not_an_error` (`None`),
  `::test_a_refused_value_raises_invalid_webhook_origin` (the test captures the exception and asserts on its
  type, so the stub's "no exception" is an assertion: `assert None is InvalidWebhookOrigin`),
  `::test_a_refusal_carries_a_fixed_reason_and_never_the_value` (the message contains none of the raw text,
  least of all `user:pass`). RED: `assert 'HTTPS://Example.ORG' == 'https://example.org'` and the capture
  assertion for every refused case. **Passing at once**: the as-written cases and the unset case (the stub
  returns its input); mutation: the lower-casing removed in one place and the empty value treated as
  malformed (reds the unset case); the reason test is proven by interpolating the raw value into the
  message. GREEN with `urllib.parse`: scheme `http` or `https`, a non-empty ASCII host, an optional port in
  range that is dropped when it is the scheme's default, nothing after the authority, no userinfo, no
  space, control character or backslash; scheme and host lower-cased; one trailing slash dropped.
  **Settled in design § O:** a bracketed IPv6 literal (TradingView does not post to IPv6), a host that ends
  in a dot and a port that is present and empty are each refused as malformed (the startup line is the ERROR
  of § J and the route serves null); the three are in the shared cases file's `refused` list and each is a
  case of the refusal tests above.
  **Done (commit `6f7c1db`).** RED against the stub, observed: `assert 'HTTPS://Example.ORG' == 'https://example.org'`
  (and `https://example.org/`, `https://example.org:443`), `assert <class 'NoneType'> is InvalidWebhookOrigin`
  for each of the 17 refused cases (35 failures with the reason test), and `assert '' is None` for the unset case
  (the stub returns its input, so the empty string is not `None`: that case did NOT pass at once as predicted).
  Mutations seen red, each reverted: `host.lower()` removed (the `HTTPS://Example.ORG` case); the empty value
  raising (the unset case); the raw value interpolated into the credential reason (two reason tests and the
  credential test). No regular expression is used; the parser is `urlsplit` plus character checks. The cases
  file was created with the Write tool; `\u0007`, `\\x` and `ä` are JSON escapes.
- [x] 12f.9.4 The setting, the route and their wiring. RED
  `backend/tests/signals/infrastructure/test_webhook_origin_router.py` (Create; `httpx.AsyncClient` over ASGI,
  the bearer fixture and `get_settings` patched with `monkeypatch.setattr(get_settings(), "webhook_public_origin", ...)`
  as `test_pools_router.py` patches the admin token), with the stubs in the same commit:
  `Settings.webhook_public_origin: str = Field(default="")` in `shared/config.py`, and
  `webhook_origin_router.py` with `GET /webhook-origin`, the router carrying
  `dependencies=[Depends(require_admin_token)]`, that always answers `{"origin": null}`; included under `/api`
  in `main.py`; one documented `WEBHOOK_PUBLIC_ORIGIN=` line in `.env.example` (the file exists and lists
  `WEBHOOK_SECRET`; the line documents the setting). Tests: `::test_a_configured_origin_is_served`
  (`https://example.duckdns.org`), `::test_every_case_of_the_shared_list_is_served_normalised_or_null`
  (parametrized over the file of 12f.9.3: accepted give their `origin`, refused give `null`),
  `::test_a_malformed_value_does_not_stop_the_route_and_is_served_as_null`,
  `::test_the_body_never_contains_the_webhook_secret` (a known `webhook_secret`, searched in the body),
  `::test_the_route_requires_the_bearer_token` (401 for a missing and for a wrong token),
  `::test_the_setting_defaults_to_empty`. RED: `assert {'origin': None} == {'origin': 'https://example.duckdns.org'}`.
  **Passing at once**: the unset case, the secret test, the auth test and the default test; mutations: the
  setting's default changed to a host; `webhook_secret` returned as `origin`; the router's dependency
  dropped (the route declared on a bare `APIRouter`, FastAPI does not re-apply the parent's, as 9p.4.36
  found); the raw value served instead of the parsed one (reds the normalised cases). GREEN: the route
  reads `settings.webhook_public_origin`, calls `parse_webhook_origin`, and answers `null` for unset and for
  an `InvalidWebhookOrigin`; `WebhookOriginBody(origin: str | None)`. `tests/accounts/test_no_decrypt_in_api_path.py`
  runs unmodified (the route reads a setting only).
  **Done (commit `2bb46f1`).** RED against the stub, observed: `assert {'origin': None} == {'origin': 'https://example.duckdns.org'}`
  and the same shape for every accepted case; `assert None == 'https://example.duckdns.org'` in the secret test
  (which also asserts the origin is served, so it failed on the stub instead of passing at once). Mutations seen
  red, each reverted: the setting's default changed to a host (the default test only); the secret returned as the
  origin (the secret test); the router's dependency dropped (the auth test); the raw value served instead of the
  parsed one (21 tests: the normalised cases and the refused ones). `test_no_decrypt_in_api_path.py` and
  `test_webhook_secret_router.py` pass unmodified (its route walk covers the new route without being told).
  The `.env.example` line is `WEBHOOK_PUBLIC_ORIGIN=` with a comment.
- [x] 12f.9.5 The startup line. RED `backend/tests/signals/infrastructure/test_webhook_origin_check.py`
  (Create), with the stub in the same commit: `log_webhook_origin(settings: Settings) -> None` in
  `signals/infrastructure/webhook_origin_check.py` that logs nothing. Tests (`caplog`, exactly one record from
  the module's logger each): `::test_an_unset_setting_logs_one_info_saying_the_panel_shows_the_path_only`,
  `::test_a_well_formed_value_logs_one_info_with_the_normalised_origin` (`HTTPS://Example.ORG` prints
  `https://example.org`), `::test_a_malformed_value_logs_one_error_naming_the_setting_and_the_reason`
  (names `WEBHOOK_PUBLIC_ORIGIN` and a reason), `::test_no_record_contains_the_raw_value` (`https://user:pass@example.org`
  searched in `message`, `args` and the formatted exception of every record), `::test_a_malformed_value_does_not_raise`
  (the exception captured and asserted `None`), and through the real lifespan, built like
  `tests/shared/test_startup_invariants.py::test_the_lifespan_passes_with_a_usable_key_and_no_panel` (its
  environment helper is copied unless it already lives in a conftest, which the task checks):
  `::test_the_lifespan_starts_with_a_malformed_origin_and_logs_the_one_error`. RED:
  `assert [] == [(INFO, ...)]` for the first three and the lifespan test. **Passing at once**: the no-raw-value
  test and the does-not-raise test (the stub logs nothing); mutations from design § K: the check raises
  (reds does-not-raise and the lifespan test), the value interpolated into the message (reds the raw-value
  test), an unset value treated as malformed (reds the INFO test: ERROR where INFO is due). GREEN:
  `log_webhook_origin` parses with `parse_webhook_origin` and logs INFO or ERROR as above, never raising;
  `main.py`'s `lifespan` calls it inside `operator_alerts` after `assert_panel_dist_ready(settings)`. It is
  deliberately NOT a startup invariant: the process that would refuse to start is the one that receives the
  alerts (rule 3).
  **Done (commit `cc62251`).** RED against the stub, observed: `assert [] == [(20, 'WEBHOO...k path only')]` (unset),
  `assert [] == [(20, ...example.org')]` (well formed), `assert [] == [(40, ...)]` (malformed), `assert 0 == 1`
  (the no-raw-value test asserts one record first, so it failed instead of passing at once) and
  `assert [] == [('strategy_m...n_check', 40)]` for the lifespan. The does-not-raise test passed at once. The
  lifespan helpers (`_startup_configured`, `alert_bridge_standin`) are copied into the test file, because they
  live in `tests/shared/test_startup_invariants.py` and not in a conftest. Mutations seen red, each reverted:
  the check re-raising (the malformed, no-raw-value, does-not-raise and lifespan tests); the setting's value
  appended to the logged argument (three tests); the unset value logged as ERROR (the unset test).
  **Exact lines** (logger `strategy_manager.signals.infrastructure.webhook_origin_check`):
  INFO `WEBHOOK_PUBLIC_ORIGIN is not set: the panel shows the webhook path only`;
  INFO `WEBHOOK_PUBLIC_ORIGIN is set: the panel builds the webhook URL on <normalised origin>`;
  ERROR `WEBHOOK_PUBLIC_ORIGIN is malformed (<fixed reason>): the panel shows the webhook path only`.

**The share's log line and notation** (design §§ C, J; spec: strategy-lifecycle "A Change Of A Strategy's
Share Of The Pool Is Logged", admin-api "The Strategy Update Takes The Share As A Plain Decimal And The
Strategy View Serves It In Plain Notation")

- [x] 12f.9.6 The INFO line of a changed share. RED `backend/tests/strategies/application/test_update_strategy.py`,
  new tests only, built on the file's `_build`, `FakeRepository` and `caplog`, with the stub in the same
  commit: the logger in `update_strategy.py` (`logging.getLogger(__name__)`) and the call that logs nothing.
  Tests: `::test_a_changed_share_logs_one_info_line_with_the_id_and_both_values` (30 to 33.5; one INFO naming
  the strategy id, `30` and `33.5`), `::test_the_same_value_written_differently_logs_nothing` (33.5 over 33.5,
  and `33.50` over 33.5: "changed" is decided on the decimal value), `::test_patching_another_field_logs_no_share_line`,
  `::test_a_refused_update_logs_no_share_line` (archived, a share the domain refuses, an unknown id),
  `::test_a_failed_commit_logs_no_share_line`. RED: `assert [] == [('strategy_manager.strategies.application.update_strategy', 20, ...)]`.
  **Passing at once** (the stub logs nothing): the other four; mutations: the comparison on the text instead
  of the value (reds the `33.50` case), the line written before the archived check (reds the refused case),
  the line written before `commit()` (reds the failed-commit case), the line written for a patch of
  `enabled`. GREEN: after `commit()` returns, when `updated.policy.allocation_percent.value !=
  strategy.policy.allocation_percent.value`, one INFO with the strategy id and the two values in plain
  notation. **Confirmed in design § O:** the line is written after the
  commit, so a rolled-back change leaves no line that says it happened; the test
  `::test_a_failed_commit_logs_no_share_line` above is the pin. No credential and no secret is in scope of this function.
  **Done (commit `4c8d499`).** RED against the stub (logger only, no call), observed:
  `assert [] == [('strategy_manager.strategies.application.update_strategy', 20, ...)]` for the 30 to 33.5 test
  and for an added test of a share below 1 (`100` to `0.0000001`, never an exponent). The other four tests
  passed at once. Mutations seen red, each reverted: the comparison on text (`str(after) != str(before)`: the
  `33.50` test); the line written in the archived branch (the refused test); a line written before `commit()`
  (the failed-commit test); a line also written when `enabled` changes (the other-field test).
  **Exact line** (INFO, logger `strategy_manager.strategies.application.update_strategy`):
  `strategy <uuid> share of the pool changed from <old> to <new>`, values in plain notation (`format(v, "f")`).
- [x] 12f.9.7 The share in plain notation, and the PATCH's contract. RED
  `backend/tests/strategies/infrastructure/test_router.py`, new tests only (the file's `client` fixture and
  `_register`, real PostgreSQL). No stub is needed: the code as it stands is the wrong answer
  (`StrategyView.allocation_percent` is a bare `Decimal`, and pydantic writes `Decimal("0.0000001")` as
  `1E-7`). Tests: `::test_a_very_small_share_is_never_served_with_an_exponent` (stored `0.0000001`, read by
  GET and answered by a PATCH of the same value: `"0.0000001"`, never `1E-7`),
  `::test_a_decimal_share_is_saved_and_served_as_it_is` (`33.5`), `::test_the_patch_answer_and_a_later_get_show_the_same_text`
  (a PATCH of `33.50`), `::test_a_share_below_one_is_accepted` (`0.5`), `::test_a_share_of_exactly_100_is_accepted`,
  `::test_zero_above_100_and_a_text_that_is_not_a_decimal_are_422_and_the_stored_share_is_unchanged`
  (`0`, `100.5`, `abc`), `::test_only_the_share_changes` (`enabled` and both allowed pairs unchanged),
  `::test_a_disabled_strategys_share_is_accepted_and_it_stays_disabled`,
  `::test_patching_an_unknown_strategy_is_404_with_its_existing_body` (the test pins what is there; the
  unit changes nothing). The archived 409 is `test_archived_strategy_patch_refused_409_at_http_layer`,
  which already exists and runs unmodified. RED: `assert '1E-7' == '0.0000001'` (two cases).
  **Passing at once**: all the others (the validation exists since PR 4); mutations: `ge=1` instead of
  `gt=0` on the PATCH body (reds `0.5`), `gt=0` to `ge=0` (reds the zero case), `le=100` to `lt=100`
  (reds the 100 case), an omitted `enabled` read as false (reds only-the-share), `allocation_percent`
  sent back as a float (reds the notation tests). GREEN: `StrategyView.allocation_percent: Money` from
  `shared/infrastructure/wire.py`; no other field and no request body changes. Run the router suites
  whole: any existing assertion on the text of a share is recorded with the reason (a stored `Decimal("100")`
  still writes `"100"`).
  **Done (commit `a715231`).** RED observed: `assert '1E-7' == '0.0000001'` (the GET assertion of the first test
  fails first, so the PATCH half is pinned by the same test after the fix and by the float mutation). The other
  tests passed at once. No existing assertion on a share's text changed; `tests/strategies`, `tests/performance`
  and `tests/signals` pass whole. Mutations seen red, each reverted: `ge=1` (the tiny-share and `0.5` tests);
  `ge=0` (the `0` 422 case); `lt=100` (the `100` test); `enabled=bool(body.enabled)` (only-the-share); the view's
  field typed `float` (nine tests). The shape of the 404 pinned: `{"detail": "no strategy registered under id <uuid>"}`.
- [x] 12f.9.8 A change of the share leaves everything already made untouched (spec: capital-allocation "A
  Changed Share Of The Pool Applies From The Next Allocation Only"). Tests that pass at once, because the
  code already behaves so (design § A U3), each with its mutation. Real PostgreSQL, the ORM schema,
  `backend/tests/strategies/infrastructure/test_share_change_integration.py` (Create):
  `::test_a_changed_share_leaves_an_existing_reservation_unchanged` (S1 with a share of 10 holds a
  reservation of 100 USDT with `pool_total_at_open` 1000; the share goes to 25 through the PATCH: the
  amount, the recorded pool capital, the status and the ledger rows are as they were; mutation: an
  `UPDATE reservations` added to `UpdateStrategy`), `::test_the_next_opening_is_sized_with_the_new_share`
  (the stored share read through the real policy adapter and `requested_from_percent(1000, 25)` is 250;
  mutation: the policy cached across the update), and `::test_a_share_change_completes_while_the_pools_advisory_lock_is_held`
  (the lock-hold harness used the other way round: the lock is held on a second connection, the PATCH
  completes with `task.done()` true; mutation: an `acquire` of the pool's lock added to the update).
  New test in `backend/tests/signals/application/test_open_after_close.py`:
  `::test_a_deferred_opening_is_sized_with_the_share_stored_when_it_finally_opens` (the share changes from 10 to
  25 while the opening waits for a close; on a total of 1000 the amount requested is 250; mutation: the
  amount computed when the opening is deferred and carried to the resume); it is built on that file's own
  fakes, and if its policy fake cannot change between the deferral and the resume the task records the
  smallest addition. An operation already open is not resized: the first test asserts the ledger rows of the
  open operation are unchanged.
  **Done (commit `09e9583`).** All four tests passed at once, as predicted. Mutations seen red, each reverted:
  an `UPDATE reservations` after the update in the route (the reservation test); the policy cached across the
  update in `StrategyPolicyAdapter` (the next-opening test); an advisory-lock `acquire` before the update in the
  route (the lock-hold test, which fails on `task.done()` after the 5 s ceiling); the policy kept from the
  deferral and reused by `open_now` (the deferred-opening test: `[Decimal('100...')] == [Decimal('250')]`).
  The lock-hold test also asserts, before the PATCH, that the holder's advisory lock is granted in `pg_locks`.
  **Deviation recorded.** `test_open_after_close.py` has no policy fake and no sizing (`OpenAfterClose` only
  calls `open_now`; the share is read in `ProcessSignalHandler`), so the deferred-opening test builds a real
  `ProcessSignalHandler` from the fakes of `test_process_signal.py` (imported, not edited) with its own
  `FakeStrategyPolicyPort` and `FakeInFlightWorkPort`, which it changes between `handle()` and `open_now()`.
  No existing test or helper was edited.

**The share preview** (design §§ C2, C3, H; spec: admin-api "The Share Preview Route Serves The Amount A
Share Asks For")

- [x] 12f.9.9 `share_amount` and `step_amounts` in `allocation/domain/share_preview.py`. RED
  `backend/tests/allocation/domain/test_share_preview.py` (Create), with the stub in the same commit:
  `ShareAmount` (`share`, `amount`, `below_pool_minimum`), `share_amount(total, share, minimum) -> ShareAmount`
  and `step_amounts(total, minimum) -> tuple[ShareAmount, ...]` that answer an amount of `Decimal(0)`,
  `below_pool_minimum` false, and a hundred such steps. Imports `decimal`, `dataclasses` and
  `allocation/domain/percent.py` only. Tests: `::test_the_amount_equals_requested_from_percent_for_a_table_of_totals_and_shares`
  (compared with `requested_from_percent` itself, never reimplemented: 333.33 at 33.5 is
  111.665550000000000000, 10 at 33.333333333333333333 is 3.333333333333333333),
  `::test_the_amount_is_rounded_down_never_up`, `::test_the_amount_is_of_the_total_the_function_is_given`,
  `::test_below_pool_minimum_is_strictly_below` (4.99 true, 5.00 false, 5.01 false),
  `::test_below_pool_minimum_agrees_with_decide_just_under_at_and_just_over_the_minimum` (a `CapitalPool` and
  `AllocationRules` through the real `decide()`: it skips `REQUEST_BELOW_MIN_ORDER_SIZE` for exactly the first),
  `::test_a_total_of_zero_gives_an_amount_of_zero_flagged_below_the_minimum`,
  `::test_the_hundred_steps_are_numbered_one_to_a_hundred_and_each_equals_share_amount`. RED:
  `assert Decimal('0') == Decimal('111.665550000000000000')`, `assert False is True` (4.99). **Passing at
  once** (the stub's hundred steps are numbered and equal to its own `share_amount`): the numbering and
  equality test; mutation: the steps built from 0 to 99. Mutations for the others, applied after the
  GREEN: the amount rounded half up (reds the round-down test), `<` become `<=` (reds the at-the-minimum
  agreement case), the amount computed from a second argument named `available`. GREEN: `share_amount` calls `requested_from_percent` and compares with
  `<`; `step_amounts` calls `share_amount` for `Decimal(n)`, n from 1 to 100.
  **Done (RED commit `60ff1b7`, GREEN commit `fbb5e93`).** RED against the stub, observed (12 failed, 3 passed):
  `assert Decimal('0') == Decimal('111.665550000000000000')` (and `3.333333333333333333`,
  `335.000000000000000000`, `0.000001000000000000`, `1E-18` for the other table rows),
  `assert Decimal('0') == Decimal('0.666666666666666666')` (round-down), `assert Decimal('0') == Decimal('100')`
  (of the total given), `assert False is True` (4.99 in the strict test, and the zero total),
  `assert (False, True) == (True, True)` (agreement at 4.99) and `assert (False, True) == (False, False)` (at 5.00
  and 5.01: the stub's amount of 0 is skipped by the real `decide()` while it flags nothing). **Passed at once**:
  the hundred-steps test, and the 5.00 and 5.01 cases of the strict test. Mutations, each seen red and reverted
  with `git checkout`: the steps built from 0 to 99 reds the hundred-steps test only; the amount rounded half up
  reds the round-down test only (the two totals the task names are exact or round the same either way, so the
  round-down test uses `2` at `33.3333333333333333335`, whose digits past the eighteenth place are `67`); `<`
  to `<=` reds the 5.00 case of the strict test and of the `decide()` agreement test; the amount computed from
  `minimum` instead of `total` reds ten tests (the signature has no `available` to substitute, so `minimum` is the
  nearest stand-in for "a second argument"). The row of the table that would have used a 27-digit total was
  dropped: `requested_from_percent` multiplies in the default 28-digit context, which is immaterial at any real
  pool size and is not this task's to change.
- [x] 12f.9.10 `PoolSizingPort`, `PoolSizing` and `PreviewShare`. RED
  `backend/tests/allocation/application/test_preview_share.py` (Create, a fake `PoolSizingPort` in the file),
  with the stubs in the same commit: `PoolSizing` (the pool's minimum order, and its snapshot: total, the
  instant it was read, `stale`; or no snapshot) and `PoolSizingPort.read(exchange, venue, settlement_currency)`
  in `allocation/application/ports.py`, consumer-declared and read-only by its shape (it has no write);
  `preview_share.py` with `PreviewShare(sizing).preview(pool, share)` answering `SharePreview` with no
  balance, no exact amount and no steps. Tests: `::test_a_snapshot_gives_the_exact_amount_and_the_hundred_steps`,
  `::test_the_amount_comes_from_the_total_not_from_what_is_available` (total 1000, available 400, share 10: 100),
  `::test_a_stale_snapshot_is_served_and_marked`, `::test_no_snapshot_gives_no_balance_no_exact_amount_no_steps_and_never_a_zero`,
  `::test_the_stored_share_is_the_default_and_an_asked_share_replaces_it`,
  `::test_the_port_is_read_once`, `::test_a_pool_with_no_row_raises_the_modules_invariant_error` (a fake port
  that answers nothing for that pool; the test captures the exception and asserts on its type, so the stub's
  "no exception" is an assertion). RED: `assert None ==
  ShareAmount(...)`. **Passing at once**: the no-snapshot test (the stub already answers nothing); mutations:
  a zero total substituted for the missing snapshot (reds it), the amount taken from `available` (reds the
  total test), a stale snapshot refused as the worker's reader does. GREEN: one read of the port, then
  `share_amount` and `step_amounts`; no lock, no commit and no clock of its own. **Settled in design § O:** the sizing port answers nothing
  (`None`) for a pool that has no row, `PreviewShare` raises the allocation module's existing invariant
  error, and the route answers the existing 500 with one ERROR (12f.9.12), as the performance routes do. The
  foreign key from strategies to pools makes that state unbuildable in a real database, so it is tested here
  with a fake port and at the route by overriding the port; no test bends the schema.
  **Done (RED commit `9aa8459`, GREEN commit `89520bb`).** The stubs: `SizingSnapshot` (total, observed_at,
  stale), `PoolSizing` and `PoolSizingPort.read` in `ports.py`, and a `PreviewShare` that reads nothing.
  RED against the stub, observed (7 failed, 1 passed): `assert Decimal('0') == Decimal('5')` (the minimum),
  `assert None is not None` (the `exact` and `balance` of the snapshot and stale tests),
  `assert None == ShareAmount(share=Decimal('33.5'), amount=Decimal('335'), below_pool_minimum=False)`,
  `assert [] == [('bybit', 'usdt-m', 'USDT')]` (read once), and `assert <class 'NoneType'> is UnknownPoolError`.
  **Passed at once**: the no-snapshot test. Mutations, each seen red and reverted: a zero total substituted for the
  missing snapshot reds the no-snapshot test only; a stale snapshot refused reds the stale test only; a port
  that answers nothing swallowed into an empty preview, together with a second read of the port, reds the
  no-row test and the read-once test. **The "amount taken from `available`" mutation cannot be built at this
  layer, by design**: the port's snapshot has no `available` field, so the use case has nothing to take it from.
  It is applied where the column is selected, at 12f.9.11 and 12f.9.12.
  **Interpretations to confirm.** (1) `preview(pool, share)` previews the share it is handed; "the stored share is
  the default and an asked share replaces it" is therefore tested here as "`exact` follows the share given and the
  steps do not", and the defaulting itself (stored share when no `share` is sent) sits in the route and is
  pinned by 12f.9.12's two first tests. (2) The "allocation module's existing invariant error" is
  `UnknownPoolError` (`allocation/application/allocate_capital.py`: "the strategy's pool is missing from
  `capital_pools`"), not `shared.domain.errors.InvariantViolation`, which the performance routes catch and which
  this route must not swallow by accident. One test beyond the task:
  `::test_a_pool_nothing_has_synced_still_carries_its_minimum` (RED: `assert Decimal('0') == Decimal('5')`).
- [x] 12f.9.11 `SqlAlchemyPoolSizing` in `accounts/infrastructure/pool_sizing.py`. RED
  `backend/tests/accounts/infrastructure/test_pool_sizing.py` (Create; real PostgreSQL on the ORM schema, the
  fixtures of `tests/ledger/infrastructure/conftest.py`: the adapter is one SELECT and no constraint decides
  it), with the stub in the same commit (an adapter that answers the minimum `Decimal(0)` and no snapshot for
  every pool). Tests: `::test_a_synced_pool_answers_its_minimum_and_its_total` (minimum 5, total 1000,
  available 400: the total, not the available), `::test_a_pool_never_synced_answers_its_minimum_and_no_snapshot`,
  `::test_a_snapshot_is_stale_by_the_allocators_own_age_limit` (the rule `SqlAlchemyPoolOverview` applies,
  `now - observed_at > max_age`, strictly: 91 s is stale and exactly 90 s is not, with the limit a constructor
  argument as there), `::test_two_pools_are_each_read_for_their_own_key` (`bybit/usdt-m/USDT` and
  `binance/usdt-m/USDT` with different minimums and totals), `::test_a_pool_with_no_row_answers_nothing`
  (the port answers `None`, as settled in 12f.9.10), `::test_the_adapter_issues_one_select` (a statement count). RED:
  `assert Decimal('0') == Decimal('5')`, `assert Decimal('0') == Decimal('1000')`; the two-pool test is RED
  too, because the stub answers the same wrong minimum for both pools. **Passing at once**: the
  never-synced snapshot half (the stub already answers no snapshot) and the statement count; mutations: `>` to `>=` (reds the exactly-90-s case),
  an inner join where the design says outer (reds the never-synced test: the pool vanishes), the pool key
  taken from the first row (reds the two-pool test), a second query for the snapshot (reds the count).
  GREEN: the `capital_pools` row outer-joined to its `pool_balance_snapshots` row on the three-part key.
  **Done (RED commit `3e9f7a8`, GREEN commit `2c01cdb`).** The constructor is `(session, clock,
  snapshot_max_age_seconds)`, as `SqlAlchemyPoolOverview`'s is: the stale rule needs a `now`. RED against the stub,
  observed (8 failed, none passed, stricter than predicted because the stub also answers the wrong minimum and
  issues no statement): `assert Decimal('0') == Decimal('5')`, `assert PoolSizing(...) == PoolSizing(...)`
  (differing `min_order_size`), `assert None is not None` (the snapshot, in all three age cases),
  `assert (Decimal('0'), None) == (Decimal('5'), Decimal('1000'))`,
  `assert PoolSizing(min_order_size=Decimal('0'), snapshot=None) is None` and `assert 0 == 1` (the statement
  count). Mutations, each seen red and reverted: `>` to `>=` reds the exactly-90-s case only; the outer join made
  an inner one reds the never-synced test only; the pool's key replaced by an `ORDER BY ... LIMIT 1` reds the
  two-pool test and the no-row test; a second query reds the statement count only; `snapshot.available` in place
  of `snapshot.total` reds the synced-pool test and the two-pool test. **Statement count observed: 1** (one
  SELECT).
- [x] 12f.9.12 `GET /api/strategies/{strategy_id}/share-preview`. RED
  `backend/tests/strategies/infrastructure/test_share_preview_router.py` (Create; `httpx.AsyncClient` over ASGI,
  real PostgreSQL on the ORM schema, `get_session` overridden as `test_pools_router.py` does), with the
  stub route in the same commit (a route that loads the strategy, declares `share` with its bound
  `Field(gt=0, le=100)` and answers a 200 with `pool_minimum` `"0"`, `balance` null, `exact` null, `steps` `[]`),
  its `get_preview_share` dependency in `strategies/infrastructure/router.py` building `PreviewShare` over
  `SqlAlchemyPoolSizing` with `get_settings().balance_snapshot_max_age_seconds`, and `SharePreviewBody`.
  Tests, field by field from the spec's scenarios: `::test_the_stored_share_is_previewed_against_the_pools_balance`
  (stored 33.5, minimum 5, total 1000: `currency` `"USDT"`, `pool_minimum` `"5.000000000000000000"`,
  `balance.total` `"1000.000000000000000000"` not stale, `exact` `{"share": "33.5", "amount":
  "335.000000000000000000", "below_pool_minimum": false}`, 100 `steps`, the first `{"share": 1, "amount":
  "10.000000000000000000", ...}`, the last `{"share": 100, ...}`), `::test_a_share_asked_for_is_served_as_exact` (`12.34`),
  `::test_the_exact_share_is_echoed_in_canonical_plain_notation` (`33.50` answers `33.5`),
  `::test_the_amount_is_the_allocations_own_rounded_down` (333.33 at 33.5, and 10 at 33.333333333333333333),
  `::test_the_amount_is_of_the_total_not_of_what_is_free` (1000 total, 400 available, share 10: 100),
  `::test_the_minimum_flag_agrees_with_the_allocation_on_both_sides_of_the_limit` (snapshots of 499, 500 and
  501 at share 1: true, false, false, and `decide()` skips a request as below the minimum for exactly the
  first), `::test_a_stale_balance_is_served_marked`, `::test_a_pool_nothing_has_synced_serves_no_amount`
  (`balance` null, `exact` null, `steps` `[]`, `pool_minimum` present, no zero anywhere),
  `::test_an_archived_strategy_is_served`, `::test_each_strategy_answers_its_own_pool` (S1 and S2 on two pools
  with different totals), `::test_an_unknown_strategy_is_404_no_such_strategy`,
  `::test_a_share_outside_the_range_is_422_and_no_body_repeats_it` (`0`, `100.5`, `abc`, the body searched for
  the rejected text), `::test_a_strategy_whose_pool_has_no_row_is_500_with_one_error_naming_both` (the
  foreign key makes that state unbuildable, so the test overrides the port's dependency with a fake that
  answers nothing for the pool and says so in its docstring; no test bends the schema), `::test_reading_a_stale_or_empty_pool_logs_nothing`
  (`caplog` empty at WARNING and above for the 200 cases: no line per page view),
  `::test_the_preview_completes_while_the_pools_advisory_lock_is_held` (the lock-hold harness the other way
  round, `task.done()` true), `::test_the_preview_writes_nothing_and_calls_no_exchange` (the row counts of
  `reservations`, `pool_balance_snapshots` and `capital_pools` before and after; the venue transports and the
  vault are never constructed), `::test_the_route_issues_the_same_number_of_statements_for_the_stored_share_and_an_asked_one`,
  `::test_no_share_preview_response_contains_a_json_float_or_an_exponent` (the walk of
  `test_performance_router.py::_walk`, over a micro share `0.0000001` on a small total; `share` of a step is
  a JSON integer, and every other number is a string). RED: `assert '0' == '5.000000000000000000'`,
  `assert None == {'total': '1000.000000000000000000', ...}`, `assert 0 == 100` (the number of steps). **Passing at once**: the
  404, the 422, the archived, the nothing-written, the logs-nothing and the no-float tests (the stub loads the
  strategy, bounds the parameter and writes nothing; the no-pool-row test is RED, `assert 200 == 500`); mutations from design § K: the pool taken from a query parameter or the first pool
  read (reds the two-strategy test), `acquire` of the pool's lock added to the read (reds the lock-hold
  test), a stale snapshot refused (reds the stale test), a zero total substituted for no snapshot (reds the
  empty test), the amount rounded half up and, separately, computed from `available` (reds the amount
  tests), a `str(Decimal)` in place of the wire's `Money` for an amount (reds the walk), a `share` echoed from
  the raw query text (reds the canonical echo). GREEN: the route loads the strategy (the 404), takes its pool
  and its stored share from the row the path names (never from the request), parses an optional `share`
  with `Field(gt=0, le=100)` through the existing handler that echoes no input, calls `PreviewShare`, and
  serves `SharePreview` with `Money` amounts, `share` an `int` in `steps` and a canonical plain string in
  `exact`. The router's bearer dependency is structural (spec: "MUST require the bearer token").
  **Done (RED commit `1d05fe6`, GREEN commit `599f034`, test-strengthening commit `4ea629f`).** The test app is
  `create_app()` (so the `/api` prefix and the application's redacted 422 handler are part of what is proven; the
  bare `FastAPI()` of `test_router.py` has no such handler and would echo the input), over the ORM schema of
  `tests/ledger/infrastructure/conftest.py`. RED against the stub, observed (21 failed, 9 passed):
  `assert '0' == '5.000000000000000000'` (`pool_minimum`), `assert None == {'share': '12.34', 'amount':
  '123.400000000000000000', 'below_pool_minimum': False}`, `AssertionError: no exact amount was served` /
  `no balance was served` (the `_exact` and `_balance` helpers assert before they subscript), `assert 200 == 500`
  (no pool row) and `assert 1 == 2` (statements: the stub reads only the strategy). **Passed at once**: the 404,
  the six 422 cases (`0`, `100.5`, `abc`, `-1`, `NaN`, `Infinity`: pydantic refuses `NaN` and `Infinity` before the
  bounds), the logs-nothing test and the writes-nothing test. **Deviations.** (1) The no-float test fails against
  the stub (it asserts `exact` first) instead of passing at once. (2) The first RED run had 11 tests failing on
  `TypeError: 'NoneType' object is not subscriptable`, which is not a RED; the tests were changed to assert
  through `_exact`/`_balance` before the RED commit, and a raw-text exponent regex that matched the hex `0e0` of a
  UUID was replaced by a check on each figure's own text. (3) After the GREEN, two mutations went unseen and
  the tests were strengthened in `4ea629f`: the half-up rounding (the task's two totals are exact or round the
  same either way: a third case, `2` at `33.3333333333333333335`, was added) and an `UPDATE` (a row count does not
  see it: the writes-nothing test now compares every whole row of `reservations`,
  `pool_balance_snapshots`, `capital_pools` and `strategies`). **Mutations, each seen red and reverted**: the pool
  hard-coded to the first one reds the each-strategy test only; an advisory-lock `acquire` of the pool in the
  route reds the lock-hold test (`task.done()` false after the 5 s ceiling) and the statement count (3 == 2); a
  stale snapshot answered 503 reds the stale test and the logs-nothing test; a zero total in place of no
  snapshot (in the adapter) reds the no-amount test; the amount rounded half up (in `share_preview.py`) reds the
  added `2`/`33.3333333333333333335` case only; `snapshot.available` for `snapshot.total` reds six tests (stored,
  asked, total-not-free, stale, each-own-pool, lock-hold); `amount: Decimal` in place of `Money` reds the
  no-float/no-exponent test only; `str(share)` in place of the canonical echo reds the four echo cases, the
  stored-share echo and the no-float test; an `UPDATE capital_pools` plus commit reds the writes-nothing test,
  the each-strategy test and the statement count; a `SqlAlchemyCredentialVault` built in the route reds the
  writes-nothing test (`the preview reached the credential vault`); an `httpx` call to a venue reds it (`the
  preview reached an exchange`); a WARNING for a stale or empty pool reds the logs-nothing test; the upper
  bound `le=100` removed reds the `100.5` case. **Not mutated**: the 404, the 500 test (it was RED against the
  stub and is green after, but no mutation of the ERROR line was run) and the 422 no-echo (the test asserts the
  body has no `input` key and no rejected text; the handler is the application's, proven in
  `tests/shared/infrastructure/test_validation_errors.py`). **Statement count observed: 2 per request**, for the
  stored share and for an asked one (the strategy by primary key, then the pool joined to its snapshot); nothing
  per step. The 500 is a fixed `{"detail": "share preview data failed an integrity check"}` and the one ERROR is
  `share preview refused for strategy <uuid>: pool (<exchange>, <venue>, <currency>) has no capital_pools row`.
  **Found, not fixed**: `share` has no bound on its decimals or exponent. `share=1e-1000000` is a valid decimal
  above 0 and answers an `exact.share` of 1,000,002 characters (`format(Decimal, "f")` writes every zero), and the
  PATCH's strategy view has the same exposure through `Money`. The caller is the single authenticated operator,
  so this is a nuisance and not an attack surface, and a bound on decimals (or a minimum share) is a product
  choice no requirement makes; it is reported, not decided.
- [x] 12f.9.13 Auth and the sweeps (design § J threat matrix, four rows). The strategies router's own
  dependency covers the new route, and `backend/tests/strategies/infrastructure/test_router_auth.py` enumerates
  that router's routes, so `share-preview` is covered without being listed: run it unmodified and record that
  it now includes the new route. For the origin route, 12f.9.4's auth test is the pin. **The secret sweep**,
  `backend/tests/signals/infrastructure/test_webhook_secret_router.py`: the route-table walk finds
  `GET /api/webhook-origin` and `GET /api/strategies/{strategy_id}/share-preview` by itself, and the sweep
  already seeds a strategy on `bybit/usdt-m/USDT` with a snapshot, so both answer 200 without being taught.
  **Recorded edit, add-only:** `::test_the_route_table_walk_finds_the_routes_it_is_meant_to_cover` gains the two
  routes in its `assert (...) in OTHER_API_ROUTES` list, as 9p.4.36 did for the fills route; no assertion of
  the sweep changes. If either route answers a 404 or a 500 inside the sweep, `_concrete_path` or the seed is
  taught the missing datum exactly as 9p.4.36 taught the allocation id, and the task records it. Passing at
  once, proven by mutation: `::test_no_other_api_response_body_contains_the_configured_secret_value[GET /api/webhook-origin]`
  (the route answers `settings.webhook_secret`). The existing "no response contains a JSON float" walk is
  taught the preview in 12f.9.12.
  **Done (commit `4fe6694`).** `test_router_auth.py` runs unmodified (all of its tests pass); its enumeration
  now holds 9 routes and includes `GET /strategies/<uuid>/share-preview`, so the new route is refused with the
  one 401 without being listed. The sweep needed no teaching: both new routes answer 200 inside it with the seed
  it already has (a bybit strategy with a snapshot), so neither `_concrete_path` nor the seed changed. **The
  recorded edit is exactly two added lines** in `::test_the_route_table_walk_finds_the_routes_it_is_meant_to_cover`:
  `assert ("GET", "/api/webhook-origin") in OTHER_API_ROUTES` and `assert ("GET",
  "/api/strategies/{strategy_id}/share-preview") in OTHER_API_ROUTES`; no assertion of the sweep changed.
  Passed at once (the added lines are true of the route table as it stands). Mutations, each seen red and
  reverted: `GET /api/webhook-origin` answering `settings.webhook_secret` as its origin reds `[GET
  /api/webhook-origin]` (`put the secret in its body`); the share-preview's `exact.share` answering the secret
  reds `[GET /api/strategies/{strategy_id}/share-preview]`. **Not mutated**: the two added assertions themselves
  (removing a route from the app would red them; it was not run).
- [x] 12f.9.14 The delta-spec check. For each requirement added on 2026-10-06 to
  `specs/admin-api/spec.md`, `specs/performance-reporting/spec.md`, `specs/capital-allocation/spec.md` and
  `specs/strategy-lifecycle/spec.md`, name in this task the test that covers each scenario, so none is left
  without one: the performance-reporting requirement and the admin-api win-rate requirement, 12f.9.1 and
  12f.9.2; the origin route, 12f.9.3 to 12f.9.5; the share update and its notation, 12f.9.7; the share's log
  line, 12f.9.6; "A Changed Share Of The Pool Applies From The Next Allocation Only", 12f.9.8; the share
  preview, 12f.9.9 to 12f.9.12; "Every Admin Route Requires the Bearer Token" for the two new routes,
  12f.9.4, 12f.9.12 and 12f.9.13. Any scenario with no test is written before the gate, and any behaviour no
  requirement states is added to the delta spec (never a main spec) and recorded here.
  **Done.** One scenario had no test and one was written (commit `c25ea78`); no delta spec was edited. The map
  (paths under `backend/tests/`; `::` names are test functions):
  - *admin-api, share preview* (`strategies/infrastructure/test_share_preview_router.py`): stored share previewed
    `::test_the_stored_share_is_previewed_against_the_pools_balance`; asked share
    `::test_a_share_asked_for_is_served_as_exact`; canonical echo
    `::test_the_exact_share_is_echoed_in_canonical_plain_notation` and `::test_the_stored_share_is_echoed_in_canonical_plain_notation_too`;
    the allocation's own rounding `::test_the_amount_is_the_allocations_own_rounded_down` (and
    `allocation/domain/test_share_preview.py::test_the_amount_is_rounded_down_never_up`); total not free
    `::test_the_amount_is_of_the_total_not_of_what_is_free`; minimum flag
    `::test_the_minimum_flag_agrees_with_the_allocation_on_both_sides_of_the_limit` (and
    `allocation/domain/test_share_preview.py::test_below_pool_minimum_agrees_with_decide_just_under_at_and_just_over_the_minimum`);
    stale `::test_a_stale_balance_is_served_marked`; not synced `::test_a_pool_nothing_has_synced_serves_no_amount`;
    archived `::test_an_archived_strategy_is_served`; own pool `::test_each_strategy_answers_its_own_pool`; 404
    `::test_an_unknown_strategy_is_404_no_such_strategy`; 422 without echo
    `::test_a_share_outside_the_range_is_422_and_no_body_repeats_it`; pool with no row
    `::test_a_strategy_whose_pool_has_no_row_is_500_with_one_error_naming_both`; reads the database only
    `::test_the_preview_writes_nothing_and_calls_no_exchange` and
    `::test_the_preview_completes_while_the_pools_advisory_lock_is_held`; the requirement's wire and logging
    clauses `::test_no_share_preview_response_contains_a_json_float_or_an_exponent`,
    `::test_reading_a_stale_or_empty_pool_logs_nothing` and
    `::test_the_route_issues_the_same_number_of_statements_for_the_stored_share_and_an_asked_one`.
  - *admin-api, bearer token for the two new routes*: the preview, `strategies/infrastructure/test_router_auth.py::test_every_registered_route_refuses_a_request_without_a_token`
    (its enumeration includes the route) and the secret sweep; the origin,
    `signals/infrastructure/test_webhook_origin_router.py::test_the_route_requires_the_bearer_token`.
  - *admin-api, webhook origin* (`signals/infrastructure/test_webhook_origin_router.py`, `_check.py`,
    `signals/domain/test_webhook_origin.py`): configured `::test_a_configured_origin_is_served`; unset
    `::test_an_unset_origin_is_served_as_null` and `_check.py::test_an_unset_setting_logs_one_info_saying_the_panel_shows_the_path_only`;
    local origin, normalisation, path/query/fragment, scheme, host, character and port cases
    `::test_every_accepted_case_of_the_shared_list_is_served_normalised` and
    `::test_every_refused_case_of_the_shared_list_is_served_as_null` (the shared cases file);
    credential not served and never logged `signals/domain/test_webhook_origin.py::test_a_credential_is_refused_with_a_reason_that_names_neither_part`
    and `_check.py::test_no_record_contains_the_raw_value`; the API still starts
    `_check.py::test_the_lifespan_starts_with_a_malformed_origin_and_logs_the_one_error`; well formed logged
    normalised `_check.py::test_a_well_formed_value_logs_one_info_with_the_normalised_origin`; no secret
    `::test_the_body_never_contains_the_webhook_secret`.
  - *admin-api, wins* (`performance/infrastructure/test_pair_wins_router.py`): all five scenarios, by
    `::test_a_pair_carries_its_wins_and_its_rate`, `::test_a_pair_with_no_win_has_a_zero_rate_not_a_null`,
    `::test_a_pair_that_won_every_operation_has_a_rate_of_one`,
    `::test_no_pair_row_is_served_for_a_pair_with_no_closed_operation` and
    `::test_the_strategy_and_pool_reports_gain_no_win_rate`.
  - *performance-reporting* (`performance/domain/test_by_pair.py` and the router file above): three in five
    `::test_a_win_is_a_pnl_above_zero_and_the_rate_is_wins_over_trades`; all at zero
    `::test_a_pnl_of_exactly_zero_is_not_a_win_and_counts_in_the_total`; 199 in 200
    `::test_199_wins_in_200_are_a_rate_below_one`; dry-run
    `test_pair_wins_router.py::test_the_wins_are_the_same_with_and_without_rehearsal_groups_in_the_ledger`;
    incomplete fees and no capital `::test_a_trade_with_incomplete_fees_and_a_trade_with_no_capital_at_open_are_counted`;
    no closed operation `test_pair_wins_router.py::test_no_pair_row_is_served_for_a_pair_with_no_closed_operation`;
    two spellings `::test_two_spellings_of_one_market_are_one_pair_with_its_wins`; removed from the allowlist
    `::test_a_pair_removed_from_the_allowlist_keeps_its_wins`; two pools
    `test_pair_wins_router.py::test_two_strategies_on_two_pools_are_not_blended`.
  - *admin-api, strategy update* (`strategies/infrastructure/test_router.py`): decimal share
    `::test_a_decimal_share_is_saved_and_served_as_it_is`; below 1 `::test_a_share_below_one_is_accepted`; exactly 100
    `::test_a_share_of_exactly_100_is_accepted`; 0, 100.5 and `abc`
    `::test_zero_above_100_and_a_text_that_is_not_a_decimal_are_422_and_the_stored_share_is_unchanged`; **archived
    (the gap) `::test_an_archived_strategys_share_is_refused_409_and_the_stored_share_is_unchanged`, written in
    this task: the existing `test_archived_strategy_patch_refused_409_at_http_layer` patches the NAME, so a
    share patched on an archived strategy was pinned by nothing. It passed at once; the mutation that skips the
    archived refusal for a patch that carries a share turned it red (`assert 200 == 409`) and was reverted**;
    disabled `::test_a_disabled_strategys_share_is_accepted_and_it_stays_disabled`; unknown
    `::test_patching_an_unknown_strategy_is_404_with_its_existing_body`; only the share
    `::test_only_the_share_changes`; tiny share `::test_a_very_small_share_is_never_served_with_an_exponent`; bearer
    `test_router_auth.py::test_every_registered_route_refuses_a_request_without_a_token` (PATCH is in its
    enumeration).
  - *strategy-lifecycle, the share's log line* (`strategies/application/test_update_strategy.py`): change
    `::test_a_changed_share_logs_one_info_line_with_the_id_and_both_values`; no-op
    `::test_the_same_value_written_differently_logs_nothing`; refused `::test_a_refused_update_logs_no_share_line`.
  - *capital-allocation* (`strategies/infrastructure/test_share_change_integration.py`, plus
    `signals/application/test_open_after_close.py`): reservation kept
    `::test_a_changed_share_leaves_an_existing_reservation_unchanged`; next opening
    `::test_the_next_opening_is_sized_with_the_new_share`; an open operation not resized, by the ledger rows of the
    first test; deferred opening `test_open_after_close.py::test_a_deferred_opening_is_sized_with_the_share_stored_when_it_finally_opens`;
    no pool lock and no reservation `::test_a_share_change_completes_while_the_pools_advisory_lock_is_held` (and
    the first test's untouched `reservations` rows).
  No behaviour was found that no requirement states, except the one recorded as "found, not fixed" in 12f.9.12
  (no bound on the decimals or the exponent of `share`), which is a product choice and was left out of the delta
  spec on purpose.
- [x] 12f.9.15 Confirm and gate: run `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
  Record: that no existing test was edited beyond the recorded edits (the two constructor calls of
  `test_by_pair.py`, the add-only line of the sweep, and whatever 12f.9.7 and 12f.9.13 recorded); that the
  existing performance, strategies, signals and accounts suites pass unmodified; the statement counts
  observed (the preview's, the adapter's); and the collected count before and after. A backend suite on
  this machine prints no summary line: confirm by exit code and by summing `uv run pytest --co -q`.
  **Done.** From `backend`: `uv run ruff check .` exit 0 ("All checks passed!"); `uv run mypy src` exit 0 ("no
  issues found in 290 source files"); `uv run pytest --tb=short` exit 0, and this run DID print a summary line:
  `3736 passed in 368.97s (0:06:08)`. **Collected** (sum of the per-file counts of `uv run pytest --co -q`):
  3,672 before this batch, 3,736 after (+64: 15 in `test_share_preview.py`, 8 in `test_preview_share.py`, 8 in
  `test_pool_sizing.py`, 31 in `test_share_preview_router.py`, 1 archived-share test in `test_router.py`, 1 sweep
  case for the share-preview route). **Existing files edited, and why**: `tests/signals/infrastructure/test_webhook_secret_router.py`
  (two added assertion lines, 12f.9.13, no existing line changed) and `tests/strategies/infrastructure/test_router.py`
  (one test appended after the last one, 12f.9.14; no existing test changed). Production: `allocation/application/ports.py`
  (three declarations added) and `strategies/infrastructure/router.py` (the route, its bodies and two dependencies; the
  module gained a logger, a constant and imports). No existing test was otherwise edited, and the performance,
  strategies, signals and accounts suites pass unmodified as part of the full run. `git diff main -- openspec/specs`
  is empty. Statement counts observed: the preview route issues 2 SELECTs per request (stored share or asked), the
  adapter 1. Deployment (12f.9.16) is the owner's and was not touched.
- [x] 12f.9.17 **A share has at most 18 decimal places** (owner decision 50, 2026-10-09; numbered after 12f.9.16 because it was added later, and built BEFORE the deploy). Found by 12f.9.12 and measured afterwards: `share=1e-999999999` passes `gt=0, le=100`, and `_canonical_share` then writes about 1 GB of text. Wherever the API takes a share (the `share` query of the preview, `allocation_percent` of the update and of the registration), a value whose written form has more than 18 decimal places is refused with the application's 422 that echoes no input, before anything is formatted, computed or stored. Judged on the value as written, with no `normalize()` (it rounds to 28 digits): `1e-18` and a value with exactly 18 decimals are accepted, `1e-19` and `1.5000000000000000000` (19 decimals, trailing zeros included) are refused, `1E+1` is still 10. RED first on each of the three inputs (`assert 200 == 422`, and for the two writes that the stored share is unchanged or no row exists), plus a test that the refusal of `1e-999999999` answers a small body. The delta spec `specs/admin-api/spec.md` replaces "with any number of decimals" and gains the scenarios; the main spec is untouched.
  **Done (RED commit `0b048ef`, GREEN commit `58345bb`).** `strategies/infrastructure/share_input.py` defines one `Share`
  type (`gt=0, le=100` plus an `AfterValidator` that reads `Decimal.as_tuple().exponent`: nothing is formatted or
  normalised), used by the preview's `share` query and by `allocation_percent` of `UpdateRequest` and `RegisterRequest`.
  Pydantic's `decimal_places` was not used and not measured: reading the exponent states the "as written" rule
  directly. RED, observed, in `tests/strategies/infrastructure/test_share_decimals.py` (12 failed, 15 passed): for each
  of `1e-19`, `0.0000000000000000001`, `1.5000000000000000000` the preview answered `assert 200 == 422`, the PATCH
  `assert 200 == 422`, the POST `assert 201 == 422`. **What the routes answered BEFORE the fix to `1e-20000`** (a scale
  above PostgreSQL's 16383): the preview 200, the PATCH **500** (`assert 500 == 422`) and the POST **500**
  (`assert 500 == 422`), with the app's `raise_app_exceptions=False`; `1e-999999999` was never sent to an unbounded
  route. **Passed at once**: the 15 accept cases (`1e-18`, `0.123456789012345678`, `1.500000000000000000`, `1E+1`,
  `0.5`, on each input). The `1e-999999999` test on all three inputs (small body, share unchanged, no row, and the
  preview's formatter patched to fail) was written with the GREEN, never run without the bound. Mutations after
  the GREEN (the `1e-999999999` test deselected, since a mutation that removes the bound would send it to a route
  that formats or stores it), each seen red and reverted: the bound removed from the preview alone reds only the 4
  preview refusals; from the update alone only its 4; from the registration alone only its 4; 18 become 19 reds the
  three 19-decimal cases of each input (9); 18 become 17 reds the three exactly-18 accept cases of each input (9);
  `normalize()` before reading the exponent reds the `1.5000000000000000000` case on each input (3); a check that
  also refuses `1E+1` and a single decimal reds the `1E+1` and `0.5` accept cases on each input (6). **Not
  mutated**: the `1e-999999999` test (by design), and "the check moved after the formatting or the write": the
  check is a pydantic validation of the request, which cannot be placed after the route's code. **Existing test
  edited, forced by the decision**: `test_share_preview_router.py::test_the_amount_is_the_allocations_own_rounded_down`,
  its added case used a share of 19 decimals (`33.3333333333333333335`) and is now refused; it is `2` at
  `33.333333333333333335` (18 decimals, the product has more), still red against a half-up rounding by
  construction (`2 * 33.333333333333333335 / 100 = 0.6666666666666666667`). Delta spec `specs/admin-api/spec.md`: the
  update requirement states the bound, the preview requirement states it, and a new requirement "A Share Has At Most 18
  Decimal Places" holds the seven scenarios, registration included; the only other "any number of decimals" in the change
  folder is `design.md` § A U1 (a finding of what the code was), left as written, and one dated paragraph at the end of §
  O records decision 50. Panel spec and `frontend/` untouched. Gate: `ruff` exit 0, `mypy src` exit 0, `pytest` exit 0
  (`3764 passed in 383.49s`); collected 3,736 before, 3,764 after (+28, all in `test_share_decimals.py`: 12
  refusals, 15 accepts and the `1e-999999999` test); `git diff main -- openspec/specs` empty.
- [x] 12f.9.16 Owner step, after the merge: deploy 12f-1. `sudo -u strategy -H git -C /opt/strategy-manager/app pull --ff-only`,
  then `systemctl restart strategy-api strategy-worker`. No migration, so no rehearsal and no `alembic upgrade`.
  Setting the new origin variable is the owner's step, **at any time**: put `WEBHOOK_PUBLIC_ORIGIN=<the
  webhook's origin, scheme and host and nothing else>` in the environment the API reads (the `.env` that
  `Settings` loads from the service's working directory, `backend/`) and restart `strategy-api`; until then
  the route answers `null`. The origin is the DuckDNS host TradingView posts to, not the panel's host. What
  to check after: (1) the journal of `strategy-api` holds exactly one startup line about the origin, INFO
  with the normalised origin when it is set and INFO saying the panel shows the path only when it is not; an
  ERROR naming `WEBHOOK_PUBLIC_ORIGIN` means the value is malformed (the line names the reason, never the
  value) and the API started anyway; (2) `GET /api/webhook-origin` answers `{"origin": "..."}` or
  `{"origin": null}`; (3) `GET /api/strategies/{id}/share-preview` answers a body with 100 `steps` and a
  `balance` for a pool the worker has synced, and `balance: null` for one it has not; (4) `GET /api/performance/strategies/{id}`
  carries `wins` and `win_rate` on each `by_pair` entry (the table is empty in production while it runs under
  `DRY_RUN`, so this is seen first on the owner's fixture); (5) the older panel, if served, shows what it
  showed. The admin token is never pasted into a chat or a log. Update the delivery log after the merge
  (the standing working agreement; this list writes no entry).
  **Done 2026-10-09 by the owner.** Merged as `06878b5` with a merge commit. Pulled as `strategy`,
  `WEBHOOK_PUBLIC_ORIGIN=https://hook.strategymanager.trade` appended to `backend/.env` (the name of decision 49,
  which also completes whn.6), both services restarted. A read-only check then ran on the VPS over loopback:
  both services active on `06878b5`; (2) `GET /api/webhook-origin` answered 200 with that origin; (3) the share
  preview of each of the three strategies answered 200 with 100 steps, a balance that is present and not stale,
  and an exact share of `3`; three steps of each are below the pool's minimum; (4) the performance report
  answered 200 with an empty `by_pair`, as expected under `DRY_RUN`, so `wins` and `win_rate` were not seen there;
  the share is served as `3`, in plain notation. **(1) was NOT met:** the journal of that run holds no line
  naming `WEBHOOK_PUBLIC_ORIGIN`. The setting is read (the route answers it); the API process writes none of its
  own INFO lines. That is unit alg. (5) was not checked: no panel is served in production.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: fakes and `caplog` for the application units; real PostgreSQL on the ORM schema for the adapter, both routes' integration tests, the ledger of the wins and the lock-hold tests; the lifespan for the startup lines; `httpx.AsyncClient` over ASGI; no credential, no network, no `head` schema.
Rollback boundary: two independent revert points. (1) The wins (12f.9.1, 12f.9.2): a revert removes two fields from each `by_pair` entry and the older panel is unaffected. (2) Everything else (12f.9.3 to 12f.9.13): a revert removes the origin route and its startup line, the share's log line and notation, and the preview route, and their paths answer 404. The setting stays in the environment, unread. No data is touched; there is no migration.
Forecast: 2,000–3,000 changed lines (design § L forecasts 1,000–1,500, of which the preview is 400 to 600). Derived bottom-up: about 600 of production code (`by_pair` 25, `PairBody` 15, the parser 90, the setting, route and startup check 100, `UpdateStrategy` 25, `StrategyView` 5, `share_preview.py` 70, the port and `PreviewShare` 90, `SqlAlchemyPoolSizing` 60, the router's route and body 110, the wiring and `.env.example` 15), and tests at three to four times that: the wins 450, the origin 450 (the shared file and its parametrized cases included), the share's line and notation 350, the reservation and lock tests 250, the preview 900. Information only.

### Unit 12f.10 — panel: the share control, "Saved", the Copy buttons, the full URL and the Win rate column — PR 12f-2

**Needs**: PR 12f-1 merged AND deployed. The panel refuses a `by_pair` entry that lacks `wins` and
`win_rate` and reads two routes that must exist (design § G). Nothing else is unmerged.

**Files**:
Create `frontend/src/features/strategies/{PoolShareEditor,ShareSlider,ShareAmount,InfoDisclosure,InlineStatus}.tsx`,
`frontend/src/features/strategies/{share-value,webhook-url}.ts`,
`frontend/src/shared/lib/{clipboard,useDebouncedValue}.ts`,
`frontend/src/shared/api/{share-preview,webhook-origin}.ts`.
Modify `frontend/src/shared/api/{types,performance,strategies}.ts`,
`frontend/src/features/strategies/{StrategyDetailPage,AllowedPairsEditor,WebhookMessage,PairStatsTable,format}.ts(x)`,
`frontend/src/shared/i18n/locales/{en,es}.json` (under `strategies.detail.share`, `strategies.detail.saved`,
`strategies.webhook` and `strategies.performance.byPair`), `frontend/src/test/keyboard.ts`,
`frontend/src/shared/theme.test.ts`. Whether `rateText` and the cut-amount helper live in
`features/strategies/format.ts` or `features/overview/format.ts` is open (12f.10.3, 12f.10.20).
Create the tests next to each file (`{share-value,webhook-url,clipboard,useDebouncedValue}.test.ts`,
`{PoolShareEditor,ShareSlider,ShareAmount,InfoDisclosure,InlineStatus}.test.tsx`),
`frontend/src/shared/api/{share-preview,webhook-origin,strategies.share,performance.pairs}.test.ts`,
`frontend/src/test/keyboard.test.ts`.
Modify `frontend/src/shared/api/performance.strategy.test.ts`, `frontend/src/features/strategies/{PairStatsTable,StrategyPerformance,StrategyDetailPage,WebhookMessage,AllowedPairsEditor,StrategiesPage,format}.test.ts(x)`,
`frontend/src/test/harness.tsx` (the recorded edits only, and new tests).

**The win rate column** (design § G; spec: operator-panel "By Pair Shows A Win Rate")

- [x] 12f.10.1 Plumbing, no behaviour change: `types.ts`, `PairStat` gains `wins: number` and `win_rate: string`; new
  types for the preview body (`SharePreview`, its `balance`, `exact` and `steps` entries) and the origin body.
  Every fixture that types a `PairStat` gains the two fields with values that agree with its `trades`:
  `PairStatsTable.test.tsx::stat()`, `StrategyPerformance.test.tsx` (the `satisfies PairStat[]` literal),
  `StrategyDetailPage.test.tsx` (`byPair`), `performance.strategy.test.ts` (its four `by_pair` literals) and
  `StrategiesPage.test.tsx` (its one); `harness.tsx` serves `by_pair: []` and needs none. Nothing else in
  those files changes. No RED: the proof is that `npm run lint` refuses a builder left without the fields
  (remove one, see `tsc` fail, restore) and the existing suites pass unmodified apart from the builders.
  **Done (commit `5061a3c`).** Baseline before the batch: `npm run lint` exit 0, `npm test`
  exit 0, 49 files and 857 tests. Added to `types.ts`: `wins` and `win_rate` on `PairStat`, and `SharePreview`,
  `SharePreviewBalance`, `SharePreviewExact`, `SharePreviewStep` and `WebhookOrigin`, read from the backend's
  `SharePreviewBody` and `WebhookOriginBody`. Proof: with the types changed and the builders untouched,
  `npm run lint` failed with TS2322 and TS2739 in `PairStatsTable.test.tsx`, `StrategyDetailPage.test.tsx` (three
  literals) and `StrategyPerformance.test.tsx` (three). The fixtures then gained the two fields, with values that
  agree with `trades` (24 trades, 15 wins, 0.6250000000; 3 and 2; 1 and 0; 19 and 12; 24 and 9; 2 and 1). Lint
  exit 0 again, and the `features/strategies` and `shared/api` suites passed (26 files, 520 tests). Existing
  files edited, all test builders and only for the two fields: `PairStatsTable.test.tsx::stat()`,
  `StrategyDetailPage.test.tsx` (two `byPair` literals), `StrategyPerformance.test.tsx` and
  `performance.strategy.test.ts` (the valid literal and the four rejection literals, which now carry the fields
  so they still fail for their own flaw once 12f.10.2 lands). `StrategiesPage.test.tsx` needed no edit: its one
  `by_pair` is `[]`, so it holds no `PairStat` to complete.
- [x] 12f.10.2 The pair-row check. RED `frontend/src/shared/api/performance.pairs.test.ts` (Create, `vi.stubGlobal("fetch")`).
  No stub is needed: the current `isPairStat` ignores keys it does not know, which is the wrong answer.
  Tests: `::refuses a by_pair entry lacking wins`, `::refuses a by_pair entry lacking win_rate`,
  `::refuses wins that is not an integer` (`1.5`, `"3"`), `::refuses wins below zero or above trades`,
  `::refuses a win_rate that is a JSON number`, `::refuses a body of the four old fields, and so the whole
  report` (a body whose entry is `pair`, `trades`, `pnl`, `return`), `::accepts an entry with the two new
  fields`, `::one bad entry among good ones refuses the lot`. RED: `promise resolved "{ ... }" instead of
  rejecting`. **Passing at once**: the accept test; mutation: the `wins` check removed in one case at a time
  (one case per field). GREEN: `isPairStat` requires `wins` an integer from 0 to `trades` and `win_rate` a
  string; the strategy report is refused whole as before. The Strategies list row reads the same report, so
  its figures read as unreadable against an older API (design § G, U14): `StrategiesPage.test.tsx` gets one
  new test for it, `::a report without the win fields makes the row's figures unreadable`.
  **Done (RED commit `16800db`, GREEN commit `eb8d7e3`).** RED, observed (10 failed, 2 passed in
  `performance.pairs.test.ts`): `AssertionError: promise resolved "{ …(12) }" instead of rejecting` for every
  refusal case; in `StrategiesPage.test.tsx` the new test failed with `Unable to find an element with the text:
  This strategy's figures could not be loaded.` (the old report was accepted, so no error line). No stub: the
  old `isPairStat` ignored the new keys. **Passed at once**: the accept test, and the extra test that accepts
  `wins` of 0 and of `trades` (the range ends). GREEN: `isPairStat` requires `wins` an integer from 0 to
  `trades` and `win_rate` a string. The strategies-list test needed its second assertion changed in the GREEN
  commit (`queryByTestId("strategy-pnl")` is null on an error row, so `.not.toBeInTheDocument()`, not
  `.not.toHaveTextContent`). Mutations after the GREEN, each seen red and reverted with `git checkout`:
  `Number.isInteger` become `typeof === "number"` reds the fraction case only; the `>= 0` check removed reds
  `wins below zero` only; the `<= trades` check removed reds `wins above trades` and `one bad entry among good
  ones`; the `win_rate` string check removed reds `lacking win_rate` and `win_rate that is a JSON number`; all
  three `wins` checks removed reds seven tests (lacking wins, the three not-an-integer cases, below zero, above
  trades, one bad entry among good ones); a validator that refuses every entry (`pair === null` added) reds the
  two accept tests. Existing file edited:
  `StrategiesPage.test.tsx` (one new test). Existing file edited in the GREEN: `performance.ts`
  (`isPairStat`, the reason of the task).
- [x] 12f.10.3 `rateText`. RED `frontend/src/features/strategies/format.test.ts`, new tests, with the stub
  `rateText(ratio: string, locale: string): string | null` returning its argument. Tests, each from a
  scenario of the spec: `::writes a rate with one decimal and no sign` (`"0.5833333333"` gives `"58.3%"`,
  `"0.6000000000"` gives `"60.0%"`), `::cuts the rate and never rounds it up` (`"0.9995000000"` gives
  `"99.9%"`, `"0.9950000000"` gives `"99.5%"`), `::only a rate of exactly one reads 100.0%`
  (`"1.0000000000"`), `::a rate of exactly zero and one win in five thousand read 0.0%` (`"0.0000000000"`,
  `"0.0002000000"`), `::never writes an exponent and a string that is not a plain ratio gives null`
  (`"abc"`, `"1e-3"`, `""`). RED: `expected '0.5833333333' to be '58.3%'`. **Passing at once** is none that the
  stub satisfies. GREEN: a text operation on the served string (the digits shifted two places, cut at one
  decimal of the percentage, then given to `Intl.NumberFormat` as a percentage with one fixed decimal), never
  a division and never `percentText`, which signs every figure. Mutation after the GREEN: the cut replaced by
  rounding (reds the 99.9 case). **Settled in design § O:** `rateText` lives in
  `frontend/src/features/strategies/format.ts`, beside `figureText`; it cuts first and formats second, and
  it writes the decimal separator and the percent sign the way the panel's existing percentage text
  (`percentText` in `features/overview/format.ts`) does in each language, so the Win rate column and the
  PnL % column of the page agree on form. What that form is in Spanish is READ from that existing function
  when the task is built, not chosen: the task records it here (the separator and whether a space precedes
  the sign) and asserts it with a literal in a Spanish test, `::writes the rate the way the PnL % column
  does in Spanish`. It is confirmed by eye in 12f.10.31.
  **Done (RED commit `b749578`, GREEN commit `838881e`).** The stub is in `format.ts`. RED, observed (13 failed,
  69 passed): `expected '0.5833333333' to be '58.3%'` (and the same shape for `0.6000000000`, `0.9995000000`,
  `0.9950000000`, `1.0000000000`, `0.0000000000`, `0.0002000000`), `expected 'abc' to be null` (and `1e-3`, the
  empty string, `-0.5000000000`, `0.5.0`), and `expected '0.5833333333' to be '58,3 %'` in Spanish. **Passed at
  once**: none of the new tests. The Spanish form, READ from `percentText` through `Intl` on this machine, not
  chosen: a decimal comma and a no-break space (U+00A0) before the percent sign, `58,3 %`, and `100,0 %`; in
  English `58.3%` with no space. The Spanish test writes the space as ` ` so it cannot be flattened by an
  editor. GREEN: the served string must match `^(\d+)(?:\.(\d+))?$`; the integer digits and the first three
  fraction digits (padded with zeros) make a count of tenths of a percent; `Intl.NumberFormat` writes that count
  over a thousand as a percentage with one fixed decimal. No division of the served ratio, no sign. A ratio
  above one (`1.5`) is not refused here and reads `150.0%`: refusing a rate outside 0 to 1 is the table's job
  in 12f.10.4. Mutation after the GREEN, seen red and reverted with `git checkout`: the cut replaced by a
  round-half-up of the fourth digit reds `cuts the rate and never rounds it up (0.9995)` and `only a rate of
  exactly one reads 100.0%` (its `0.9999999999` case). Existing files edited: `format.ts` and `format.test.ts`
  (one export and one `describe`).
- [x] 12f.10.4 The Win rate column. RED `PairStatsTable.test.tsx`, new tests (the file's `stat()` builder; the
  component as it is, the wrong answer for five columns). Tests: `::puts the Win rate column after Trades`
  (`queryAllByRole("columnheader")` text, `toEqual` Pair, Trades, Win rate, PnL, Return), `::writes the rate
  unsigned in neutral ink` (no `+`, no `text-gain` or `text-loss`), `::the heading is Win rate in English and
  % acierto in Spanish`, `::the OPEN column is not built`, `::hides no column and scrolls inside its own
  wrapper` (the `overflow-x-auto` wrapper), `::shows the could-not-be-read state, and draws no row, for a
  win_rate above 1 or below 0`, `::wins 0 with a rate above 0 is not drawn`, `::wins equal to trades with a rate
  below 1 is not drawn`, `::the rate is cut: 1,999 of 2,000 reads 99.9% and 2,000 of 2,000 reads 100.0%`,
  `::a ratio that does not match wins over trades is not drawn` (the spec's scenario: 5 trades, 3 wins, served
  `0.7000000000`: no row, the could-not-be-read state; also 3 of 5 as `0.6000000002`, one unit past the
  tolerance), and `::a ratio within one unit of its last place either way is drawn` (the cases that must be
  ACCEPTED, so the check is not too strict: 7 of 12 as `0.5833333333`; 1,999 of 2,000 as `0.9995000000`; 1
  of 3 as `0.3333333333` and as `0.3333333334`, one unit either way; 3 of 5 as `0.6000000001`, the edge).
  **Recorded edit of one existing test:** `::names the columns and says which currency the PnL is in` asserts
  the table's headings; its expected list gains Win rate (read it first and record what it held), renamed
  only if its name says four. RED: `expected [ 'Pair', 'Trades', 'PnL USDT', 'Return' ] to deeply equal ...`.
  **Passing at once**: the OPEN test, the wrapper test and the within-tolerance cases (the component as it
  is draws every row); mutations: a column added; `overflow-x-auto` removed, and a `hidden` utility put on
  the new column. GREEN: the column and its key `strategies.performance.byPair.winRate` ("Win rate" /
  "% acierto") in both locale files; the component reads the served ratio and shows the existing
  could-not-be-read state when a check fails. **Settled in design § O (the spec stands):** the end checks
  stay as the first, cheap test (a rate of 0 exactly when there are no wins, 1 exactly when every operation
  won, and the ratio between 0 and 1); then the ratio's digits are read as an integer `r` (the ratio times
  10^10) and the row is accepted only when `|r × trades − wins × 10^10| ≤ trades`, with integers of arbitrary
  size (`BigInt`). That is one unit of the ratio's last place either way, so it holds whichever way the
  server rounds; it divides nothing and computes no rate. It supersedes design § G's "the ends only" for this
  check. **Mutations, applied after the GREEN:** the comparison removed (reds the 3-of-5-at-`0.7000000000` and
  the `0.6000000002` cases); the tolerance set to zero (reds the one-unit cases: 7 of 12, 1 of 3 as
  `0.3333333333` and as `0.3333333334`, and the `0.6000000001` edge); a floating-point division used instead
  (`wins / trades` against `Number(rate)`): an exact float equality reds 7 of 12 and the 1-of-3 cases, and a
  float multiply-and-compare is expected to disagree once `trades` is above about 10^6, where
  `r × trades` passes 2^53. **No counts for that last disagreement were computed in this breakdown:** the
  task finds a case (trades above 10^6, the served ratio the correctly rounded one) by running the mutation
  and records it, or records that none was found and why; the mutation above is named either way.
  **Done (RED commit `776afbd`, GREEN commit `be99cc1`, the large-count test in the commit after it).** RED
  against the component as it was, observed (21 failed, 7 passed of 28): `expected [ 'Pair', 'Trades', 'PnL
  USDT', …(1) ] to deeply equal [ 'Pair', 'Trades', 'Win rate', …(2) ]` (English, twice), the Spanish list
  without `% acierto`, `expected [ <th …> ] to have a length of 5 but got 4` (OPEN and the hidden-column test),
  seven `toHaveTextContent` failures where the rate cell is the wrong cell or absent, six `Unable to find an
  accessible element with the role "alert"` (a rate the component drew without complaint) and one `Unable to
  find an accessible element with the role "columnheader" and name "Win rate"`. **Not passing at once** as the
  task predicted: the OPEN test and the hidden-column test assert five columns, so they were red too; the
  wrapper assertion alone passes against the old component, and so does every refusal-free pre-existing test.
  **Recorded edits of existing tests (all in the RED or the GREEN commit):** `::names the columns and says which
  currency the PnL is in` held `["Pair", "Trades", "PnL USDT", "Return"]` and now holds the five (the name says
  nothing about a count, so it keeps its name); `::is titled and labelled in Spanish` held `Par`, `Operaciones`,
  `PnL USDT`, `Rendimiento` and gains `% acierto`; `::shows an em dash, never a zero, for a pair with no
  return` read the Return cell at index 3 and reads index 4; `StrategyPerformance.test.tsx::lists the by-pair
  table of the same report, a pair without a return as a dash` made the same index change; and
  `::test_pair_removed_from_allowlist_still_shown_with_historical_stats` overrode `trades` alone, which now
  disagrees with the builder's `wins` and rate, so it also overrides `wins` and `win_rate` (12 of 19, 9 of 24).
  A test written for the Spanish form found that `toHaveTextContent` folds the no-break space into a plain
  one, so that assertion compares `textContent` with `toBe`. GREEN: `winRate` key in both locale files; a
  `<th>` and a `<td>` after Trades, neutral ink (no tone class); `rateAgrees` in `PairStatsTable.tsx` takes the
  served ratio's digits as a whole number `r` over 10^scale (the scale is its own count of decimals, ten on the
  wire), refuses a ratio above one, refuses 0 unless there are no wins and 1 unless every trade won, then
  accepts `|r * trades - wins * 10^scale| <= trades` in `BigInt`; a row that fails, or whose rate `rateText`
  cannot write, makes the whole table the could-not-be-read state, as for any other figure. Guarded against a
  trade or win count that is not an integer, which would make `BigInt` throw. The tolerance is one unit of the
  ratio's last place either way, so it needs no knowledge of the server's rounding. **Mutations after the GREEN,
  each seen red and reverted with `git checkout`:** the comparison made always true reds the 3-of-5-at-
  `0.7000000000` case and the `0.6000000002` case only; the tolerance set to exactly zero reds the 7-of-12,
  the two 1-of-3 and the 3-of-5-at-the-edge cases, the neutral-ink test and the pair-removed test (their
  builders hold rates that are not exact); `overflow-x-auto` replaced by `overflow-hidden` reds the wrapper
  test; a `hidden sm:table-cell` on the new heading reds the same test; an extra `Open` heading reds the OPEN
  test, the two column-list tests, the Spanish list and the five-column test. **The float case, found:** at
  5,000,000 trades and 7,920 wins the served ratio `0.0015840001` is exactly one unit of its last place off,
  the edge the integer check accepts. Multiplying floats (`Math.abs(Number(rate) * trades - wins) * 10^10 <=
  trades`) puts it a hair past the edge and refuses it. A scan of 1,264 edge cases at 5,000,000 trades
  (`wins` stepping by 7,919, a unit either side) found 912 disagreements, all in the direction of
  refusing a ratio the integer check accepts; the first is `7920` and `0.0015840001`. That case is a new test, `::checks a trade count above a million in whole numbers`, which
  passed at once against the GREEN and is committed on its own; the float mutation reds it and also reds the
  3-of-5 edge case. A mutation to exact float equality (`Number(rate) === wins / trades`) reds seven tests (the
  7-of-12, the two 1-of-3, the 3-of-5 edge, the large-count test, the neutral-ink test and the pair-removed
  test). Existing files edited: `PairStatsTable.tsx` (the column, the check), `PairStatsTable.test.tsx` and
  `StrategyPerformance.test.tsx` (the edits above), `locales/en.json` and `locales/es.json` (one key each).

**The pure helpers and the API** (design §§ C, C2, E, F)

- [x] 12f.10.5 The value model, `share-value.ts`. RED `frontend/src/features/strategies/share-value.test.ts`
  (Create), with the stub module in the same commit: `readStored(text)` returning its input,
  `parseDraft(text)` answering a valid draft for every text, `roundToHandle(canonical)` returning 0, and
  `handlePosition(step)` returning `"0%"`. Tests, tables of cases, one per row of design § C:
  `::reads a stored share into its canonical form` (`33.50` is `33.5`, `100.000` is `100`, `0.5`, `0.50` is
  `0.5`), `::a stored text that is not a plain decimal is unreadable` (`1E-7`, `+5`, `-5`, the empty string),
  `::one comma is a decimal separator` (`33,5` is `33.5`), `::zero is above 0 and 100.5 and 150 are at most 100`
  (`0`, `0.0`), `::not a number is not a value` (empty, `abc`, `1e1`, `-5`, `25%`, `1.000,5`, `33.`, `.5`, a wide
  digit, whitespace around a number: nothing is guessed and nothing is trimmed into a value; a value needs
  digits on both sides of its separator, the rule that refuses `33.`), `::leading zeros change no value`
  (`007` reads as `7`, `0033.50` as `33.5`; the canonical form drops them, as for a stored value),
  `::0.5 is valid and 100 is valid`, `::the handle is the value rounded half up and clamped from 1 to 100`
  (`33.5` gives 34, `0.5` gives 1, `0.4` gives 1, `99.5` gives 100, `24.5` gives 25, `100` gives 100),
  `::the handle's position is (v - 1) / 99` (`1` gives `0%`, `25` gives `24.2424%`, `50` gives `49.4949%`, `75`
  gives `74.7475%`, `100` gives `100%`), `::a draft is canonical so the stored value typed back is unchanged`.
  RED: `expected '33.50' to be '33.5'`, `expected 0 to be 34`. **Passing at once**: none the stub satisfies
  except the empty-text and zero cases; mutation after the GREEN: the comma rule removed, the half-up
  rounding replaced by truncation. GREEN: a pure module; no money, no arithmetic on a share beyond the
  position and the rounding. **Settled in design § O:** `.5` is refused and `007` is read as 7 (both are cases above;
  mutation: the digits-on-both-sides rule removed reds `.5`, the leading-zero drop removed reds `007`). The regular expressions and
  escapes of the diff are read once the GREEN is written.
  **Done (RED commit `65a9c4f`, GREEN commit `4374f15`).** The task fixes the stub's four answers; it leaves the
  return types open, so these were chosen from design § C and record no product decision: `readStored(text):
  string | null` (null is unreadable), `parseDraft(text): DraftReading` where `DraftReading` is `{ valid: true;
  canonical }` or `{ valid: false; refusal }` and `refusal` is `"not-a-number"`, `"not-above-zero"` or
  `"above-hundred"` (the three states of the design's table, so the field can word each), `roundToHandle(canonical):
  number`, `handlePosition(step): string` (a CSS length such as `"24.2424%"`). The stub answers `{ valid: true,
  canonical: text }` for `parseDraft`. RED, observed (56 failed, 11 passed of 67): `expected { valid: true,
  canonical: '33,5' } to deeply equal { valid: true, canonical: '33.5' }`, `expected { valid: true, canonical:
  'abc' } to deeply equal { valid: false, … }` (and the same for `1e1`, `25%`, `1.000,5`, `33.`, `33,`, `3,3,5`,
  Arabic-Indic and full-width digits, text with a space either side), `expected { valid: true, canonical: '150'
  } to deeply equal { valid: false, … }` (and `1000`, `100.5`, and `100.000000000000000001`, which a float
  comparison would call 100). **Passed at once**: the three stored forms that are already canonical (`0.5`,
  `33.5`, `7`), the valid cases `100`, `100.0`, `99.999` and `0.5` (the stub answers valid for every text), two of
  the typed-back cases (`0.5`, `7.25`, already canonical) and the position of step 1. The typed-back test first
  compared `parseDraft(x)` with `readStored(x)`, which the stub satisfied on both sides; it now compares both
  with a literal. GREEN: a pure module, regular expressions on the digits (`STORED_TEXT` dot only,
  `TYPED_TEXT` dot or comma, digits on both sides), a canonical form without leading zeros or trailing
  fractional zeros, "above 100" decided on the digit strings, the handle rounded half up on the first
  fraction digit and clamped 1 to 100, the position `(step - 1) / 99 * 100` cut to four decimals with the
  trailing zeros dropped. Backslashes of all four patterns read back in the file. The maximum length of the
  field (12 characters) bounds the text, so the 18-decimal bound of decision 50 is never reachable from a
  typed value and this module does not test it. Mutations after the GREEN, each seen red and reverted: the
  comma removed from `TYPED_TEXT` reds `reads one comma as a decimal separator` and `0,00`; the half-up digit
  made to round nothing up reds four handle cases (`33.5`, `99.5`, `24.5`, `7.5`); digits-on-both-sides removed
  (`(\d*)` on the integer side) reds the empty string and `.5`; the leading-zero drop removed reds `007.250`,
  `007` and `0033.50`; `integer > "100"` become `>= "100"` reds `100`, `100.0` and the typed-back `100.000`.
  Files created: `share-value.ts`, `share-value.test.ts`; no existing file edited.
- [x] 12f.10.6 `setStrategyAllocationPercent` and `useSetAllocationPercent`. RED
  `frontend/src/shared/api/strategies.share.test.ts` (Create, `vi.stubGlobal("fetch")`), with the stubs in
  `strategies.ts` in the same commit (the function resolves a fixed strategy without a request; the hook
  with no cache write). Tests: `::sends PATCH /api/strategies/{id} with exactly {"allocation_percent":"33.5"}`
  (`expected undefined to be '/api/strategies/...'`), `::sends the value as a string and no other field`
  (mutation: `enabled` added to the body; and, separately, the value sent as a number), `::refuses an answer
  that is not a strategy` (the existing `isStrategy`), `::a refusal throws an ApiError with its status`
  (422, 409, 404, 500), `::on success writes the checked answer into ['strategy', id]` (so the stored value is
  the confirmed one even if the refetch that follows fails), `::on settle invalidates ['strategies'] and
  ['strategy', id] and returns that promise` (as the two hooks of the file do). GREEN as the tests say.
  The control's own tests assert the request body again (12f.10.16), at the place the owner's slip would
  matter.
  **Done (RED commit `948a33c`, GREEN commit `7990124`).** The stubs are in `strategies.ts`: the function
  answers a blank strategy without a request, the hook has a `mutationFn` and no `onSuccess` or `onSettled`.
  RED, observed (14 failed, none passed): `expected "spy" to be called 1 times, but got 0 times` (the request
  tests), `expected '0' to be '12.25'`, `promise resolved "{ id: '', name: '', exchange: '', …(8) }" instead of
  rejecting`, `expected null to be an instance of ApiError` (the four refusals), `expected { …(11) } to deeply
  equal { …(11) }` (the cache write), `expected false to be true` (the refused save never errors against the
  stub) and `expected "invalidateQueries" to be called at least once`. **Passed at once**: none. GREEN:
  `setStrategyAllocationPercent` sends `PATCH /strategies/{id}` with `JSON.stringify({ allocation_percent:
  value })` and the JSON content type, and checks the answer with `isStrategy`; `useSetAllocationPercent`
  writes the checked answer into `['strategy', id]` on success and, on settle, awaits the invalidation of
  `['strategies']` and then of `['strategy', id]` (which also covers the share preview under it). Two tests
  beyond the task's list: `::writes nothing when the save is refused` and `::on a refusal still invalidates
  both keys`. Mutations after the GREEN, each seen red and reverted: `enabled: true` added to the body reds the
  exact-body test and the three value tests (4); the value sent as `Number(value)` reds the same four; the
  invalidations made fire-and-forget (the hook no longer returns their promise) reds `on settle invalidates …
  and returns that promise` only; the `onSuccess` cache write removed reds `on success writes the checked
  answer` only; the `isStrategy` check removed reds `refuses an answer that is not a strategy` only. Existing
  file edited: `strategies.ts` (the function and the hook, additions only); created `strategies.share.test.ts`.
- [x] 12f.10.7 `fetchSharePreview` and `useSharePreview`, `shared/api/share-preview.ts`. RED
  `frontend/src/shared/api/share-preview.test.ts` (Create), with stubs that answer a well-formed body whose
  amounts are all zero. Tests: `::requests GET /strategies/{id}/share-preview with no query for the stored
  share` and `::with ?share= for an asked one`, `::refuses a body with a balance and no steps`, `::refuses
  exact without a balance`, `::refuses 99 steps and steps not numbered 1 to 100 in order`, `::refuses an amount
  that is a JSON number`, `::refuses a pool_minimum that is null`, `::accepts the null, null and empty body of a
  pool nothing has synced` (**passing at once**; mutation: the pairing check removed in one case at a time),
  `::the query key is ['strategy', id, 'share-preview'] and, for an asked share, [..., 'share-preview', share]`
  (sitting under the strategy's own key, so a save that invalidates it refreshes it), `::reads again every
  60 seconds` (fake timers), `::makes no request until the hook is mounted`. RED: `expected [...] to deeply
  equal`, `promise resolved ... instead of rejecting`. GREEN: every field checked by type, `steps` exactly
  100 entries numbered 1 to 100, `balance`, `exact` and `steps` present together or absent together; a
  failing check is an error, never a partial table.
  **Done (RED commit `37198a7`, GREEN commit `9a91195`).** The stubs: `fetchSharePreview` answers a body of
  `balance` null, `exact` null and `steps` empty with a `pool_minimum` of `"0"` and sends nothing;
  `useSharePreview` runs it under a key no other query shares. RED, observed (29 failed, none passed):
  `expected "spy" to be called 1 times, but got 0 times` (the request, `?share=` and encoding tests),
  `expected '0' to be '5.000000000000000000'` (the stub's minimum, so the unsynced accept test was red, not
  passing at once as the task predicted), `promise resolved "{ …(7) }" instead of rejecting` (every refusal),
  `expected undefined to match object { strategy_id }` (the two key tests), `expected null to be an instance of
  ApiError` and `expected false to be true` (the server refusal and the error state). One test first failed on
  a `TypeError` (it indexed the first fetch call without asserting a call was made); an assertion was put before
  it and the RED was re-run before the commit. **Passed at once**: none. GREEN: `isSharePreview` checks every
  field by type, `balance` null needs `exact` null and `steps` empty, `balance` set needs a valid `exact` and
  exactly 100 steps whose `share` is the JSON integer equal to the place (1 to 100); the query is
  `GET /strategies/{id}/share-preview`, with `?share=` percent-encoded when one is asked; `useSharePreview` uses
  key `['strategy', id, 'share-preview']` (plus the share when asked) and `refetchInterval` 60 000. Tests beyond
  the list: the encoding of `?share=`, the server refusal as an `ApiError`, 101 steps, a step whose share is a
  string, a stale flag that is a string, the hook reading a bad body as an error with no data, and the key
  test checks that invalidating `['strategy', id]` refetches the preview. Mutations after the GREEN, each seen
  red and reverted: the `steps.length === 0` pairing removed from the null case reds `steps without a
  balance`; the `exact === null` pairing removed reds `exact without a balance`; the `isExact` check removed
  reds `a balance and no exact value`, the two JSON-number exact cases and the `below_pool_minimum` case; the
  100-step count removed reds `a balance and no steps`, 99 steps, 101 steps and the hook's error test; the
  numbering check made a bare type check reds `steps numbered from 0` and `steps out of order`; the interval
  removed reds `reads again every 60 seconds`; the share left out of the key reds the asked-share key test.
  Files created: `share-preview.ts`, `share-preview.test.ts`; no existing file edited.
- [x] 12f.10.8 The webhook's origin and the URL's assembly. RED `frontend/src/shared/api/webhook-origin.test.ts` and
  `frontend/src/features/strategies/webhook-url.test.ts` (Create), with stubs in `webhook-origin.ts` and
  `webhook-url.ts`: `fetchWebhookOrigin` and `useWebhookOrigin` (key `['webhook-origin']`) answering `null`,
  `acceptedOrigin(value)` returning its input and `webhookUrl(origin, value)` returning the path alone.
  Tests: `::requests GET /webhook-origin`, `::accepts {"origin": null}`, `::refuses a body without origin`,
  `::refuses an origin that is a number`, `::the panel accepts every normalised case of the shared list`
  (`webhook-origin.cases.json`, the same file `test_webhook_origin.py` reads: `acceptedOrigin(case.origin)`
  equals `case.origin`), `::the panel refuses what is not an origin` (a path, a query, a fragment, a user, a
  trailing slash, upper case, the default port: `new URL(value).origin === value` is the whole check),
  `::the URL is the origin plus /webhook/tradingview?secret= plus the placeholder or the percent-encoded
  secret`, `::with no origin the URL is the path alone, as today` (an empty origin never renders as `null` or
  `undefined`; mutation: the empty origin concatenated). RED: `expected 'https://example.org/hook' to be
  null`, `expected '/webhook/tradingview?secret=...' to be 'https://example.org/webhook/...'`. GREEN: the check
  is the one comparison; the URL is plain concatenation of a checked origin, a constant path and the value.
  **Done (RED commit `9708501`, GREEN commit `8c081ff`).** The stubs are as the task names them, with two
  details it left open: `acceptedOrigin` and the hook live in `shared/api/webhook-origin.ts` (the API module
  that checks the answer), `webhookUrl` in `features/strategies/webhook-url.ts`, and `webhookUrl(origin, value)`
  takes `value` already prepared (the translated placeholder, which is not encoded, or the percent-encoded
  secret), as `WebhookMessage` already builds it. `fetchWebhookOrigin` returns `string | null` and applies
  `acceptedOrigin` to what the server served, so a served string that is not an origin reads as no host. RED,
  observed (24 failed, 8 passed of 32): `expected "spy" to be called 1 times, but got 0 times`, `promise
  resolved "null" instead of rejecting` (a body without `origin`, a number, a boolean, a list, null), `expected
  'https://example.org/hook' to be null` (and the query, fragment, user, user and password, trailing slash,
  upper case, default port, no scheme, empty text, port 99999), `expected '/webhook/tradingview?secret=<your
  WEB…' to be 'https://example.org/webhook/tradingvi…'`. **Passed at once**: the five normalised cases of the
  shared list (the stub accepts every text), the two path-alone cases of `webhookUrl` (null and the empty text,
  which the stub never prefixes) and the served non-origin text, which the stub reads as `null`. GREEN:
  `acceptedOrigin` is `new URL(value).origin === value` inside a `try`; the fetch answers `null` for a null
  origin, throws for anything that is not a string, and returns `acceptedOrigin(origin)`; `webhookUrl` is
  `${origin ?? ""}/webhook/tradingview?secret=${value}`. Mutations after the GREEN, each seen red and
  reverted: `String(origin)` in the URL reds the null case (the empty-text case holds, as `""` concatenates
  to nothing); `new URL(value).origin === value` weakened to `new URL(value)` reds eight refusals (path,
  query, fragment, user, user and password, trailing slash, upper case, default port) and the served-non-origin
  test; the fetch no longer applying `acceptedOrigin` reds the served-non-origin test only; the type guard
  removed reds the five body refusals. The shared list's `refused` entries are NOT asserted against the panel:
  the design's single comparison accepts three of the seventeen that the server refuses, found by running the
  list through it (`ftp://example.org`, `https://[::1]`, `https://example.org.`). That is acceptable because the
  server never serves a refused value; the panel must accept everything the server accepts, which it does. If
  the owner wants the panel to refuse those three too, it is a scheme and host rule beyond the one comparison
  the design settles, and it is not added. Files created: `webhook-origin.ts`, `webhook-origin.test.ts`,
  `webhook-url.ts`, `webhook-url.test.ts`; no existing file edited. `WebhookMessage.tsx` does not use any of it
  yet.
- [x] 12f.10.9 `useDebouncedValue`. RED `frontend/src/shared/lib/useDebouncedValue.test.ts` (Create, `renderHook`, fake
  timers), with a stub that returns its input at once. Tests: `::keeps the old value until the pause has
  passed` (299 ms), `::takes the new value at 300 ms`, `::two changes in quick succession give one update, for
  the last`. RED: `expected 'b' to be 'a'`. GREEN: a `setTimeout` cleared on change and on unmount; the delay
  is a parameter and the control passes 300.
  **Done (RED commit `df8e9b5`, GREEN commit `407b604`).** The stub returns its input. RED, observed (4 failed,
  2 passed of 6): `expected 'b' to be 'a'` (299 ms, and the delay of 50 ms), `expected 'c' to be 'a'` (two quick
  changes: the stub already showed the last), `expected +0 to be 1` (the timer count after a change). **Passed
  at once**: the initial value and `takes the new value at 300 ms` (the stub is already at the new value).
  GREEN: `useState` for the debounced value and a `useEffect` that sets a `setTimeout` for the delay and clears
  it on every change and on unmount. Tests beyond the list: the initial value, the delay being a parameter, and
  no timer left after unmount (`vi.getTimerCount()`). Mutations after the GREEN, each seen red and reverted:
  the `clearTimeout` removed reds `two changes in quick succession` and `leaves no timer behind`; the delay
  fixed at 300 reds `uses the delay it is given` only; the delay shortened by a millisecond reds `keeps the old
  value until the pause has passed`, the two-changes test and the delay test; the delay multiplied by a
  thousand (so the value never arrives in time) reds `takes the new value at 300 ms`, the two-changes test and
  the delay test. Files created: `useDebouncedValue.ts`, `useDebouncedValue.test.ts`;
  no existing file edited.
- [x] 12f.10.10 `copyText`, `shared/lib/clipboard.ts`. RED `frontend/src/shared/lib/clipboard.test.ts` (Create), with the
  stub that answers `true` without writing. Tests: `::writes exactly the text to navigator.clipboard.writeText`
  (`expected "spy" to be called with arguments: [ 'text' ]`), `::answers false when navigator.clipboard is
  missing` (`expected true to be false`), `::answers false when writeText is missing`, `::answers false when the
  write rejects` and never throws, `::never logs anything, the text may be the secret` (every console method;
  **passing at once** against the stub, so mutation: a `console.error` in the catch). GREEN: no
  `document.execCommand` fallback (design § E: it writes the secret into a second place).
  **Done (RED commit `c69c48d`, GREEN commit `36f492a`).** The stub answers `true` without writing. RED,
  observed (6 failed, 3 passed of 9): `expected "spy" to be called 1 times, but got 0 times` and `expected "spy"
  to be called with arguments` (the write, the encoded URL, and the two failing writes), `expected true to be
  false` (clipboard missing, `writeText` missing). **Passed at once**: the three never-logs cases, as the task
  predicted. GREEN: `copyText` reads `navigator.clipboard` as possibly missing, answers `false` when it or
  `writeText` is missing, awaits `writeText(text)` and answers `true`, and a `catch` with no binding and no
  call answers `false`; no `execCommand`. Tests beyond the list: a URL with an encoded secret written
  untouched, and a `writeText` that throws at once instead of rejecting. Mutations after the GREEN, each seen
  red and reverted: a `console.error(error)` in the catch reds the never-logs case for a rejecting write; the
  catch answering `true` reds both failing-write tests. **An equivalent mutation, said plainly:** removing the
  `typeof clipboard.writeText !== "function"` check changes nothing a test can see, because calling a missing
  `writeText` throws inside the `try` and the catch answers `false`. The check is kept so the code states the
  case; it is not proven by a test. Files created: `clipboard.ts`, `clipboard.test.ts`; no existing file edited.

**The small shared pieces** (design §§ B2, D)

- [x] 12f.10.11 `InlineStatus`. RED `InlineStatus.test.tsx` (Create), with the stub that renders a bare `<span>` with no
  role. Tests: `::is in the document before it has anything to say, empty`
  (`expect(screen.queryByRole("status")).toBeInTheDocument()`; mutation: rendered only with its text),
  `::announces politely` (`aria-live="polite"`), `::shows its message`, `::a failure tone is loss and the
  default is neutral ink-2, never gain` (the gain colour is for money made and the primary action),
  `::two instances are independent`. RED: `expected null to be in the document`. GREEN: a presentational
  component taking a message or nothing and a tone; no store.
  **Done (RED commit `9302dcf`, GREEN commit `80d8174`).** Props chosen where the task left them open:
  `message: string | null` and `tone?: "neutral" | "failure"`. The stub is a bare `<span>{message}</span>`.
  RED, observed (7 failed of 7): `expected null to be in the document`-style failure for the first test
  (`expect(received).toBeInTheDocument()`), and `Unable to find an accessible element with the role "status"`
  for the other six. **Passed at once**: none. GREEN: `<span role="status" aria-live="polite">` always
  rendered, `text-sm` with `text-loss` for a failure and `text-ink-2` otherwise; no store. A test beyond the
  list: the same element survives from empty to a message and back. The colour assertions are on the class
  names because the task asks for the tone by colour. Mutations after the GREEN, each seen red and
  reverted: rendering nothing for a null message reds the empty-in-document, polite, same-element and
  two-instances tests; the failure tone made `text-gain` reds the failure test; the default made `text-gain`
  reds the default-tone test; `aria-live` made `assertive` reds the polite test. Files created:
  `InlineStatus.tsx`, `InlineStatus.test.tsx`; no existing file edited.
- [x] 12f.10.12 `InfoDisclosure`. RED `InfoDisclosure.test.tsx` (Create), with the stub design § K names: a button
  rendered with `aria-expanded="false"` that never opens. The shared piece is a hook that owns the open state
  and the ids, and two presentational parts, the button and the container. Tests: `::is closed at mount and
  no explanation is in the document` (**passes at once**; mutation: open by default, and separately a
  paragraph rendered outside its container), `::activating the button shows the text and aria-expanded is
  true` (RED: `expected null to be in the document`), `::activating again closes it`, `::Enter and Space toggle
  it` (`pressEnter`, `pressSpace`), `::Escape on the button or inside the text closes it and leaves focus on
  the button` (mutation: the handler removed; and, separately, focus left on the body), `::tabbing away
  from an open explanation leaves it open and so does a press elsewhere` (mutation: a close on blur), `::two
  disclosures open together and closing one leaves the other` (mutation: one shared state), `::aria-controls
  names an element present while closed and the paragraphs are rendered only while open` (mutation: the
  container rendered only while open), `::the button's name does not change with its state` (mutation: both
  named "Info"), `::the button is never disabled`, `::the box is 44 by 44 px by class and the glyph is an
  aria-hidden SVG with no style attribute` (mutation: the box class removed; and, separately, the glyph
  replaced by a text character). GREEN: `InfoDisclosure.tsx` beside `InlineStatus`; the glyph is a circle, a
  dot and a stem drawn with attributes, `currentColor` from a text class (`ink-3` at rest, `ink-2` on hover,
  `ink` while open).
  **Done (RED commit `23dbf3f`, GREEN commit `6d53035`, a test fix in the commit after it).** Names chosen where
  the task left them open: `useInfoDisclosure()` returns `{ open, textId, buttonRef, toggle, close }`;
  `InfoButton({ disclosure, label })` and `InfoText({ disclosure, children })` are the two parts. The stub is
  the one design § K names: a button with `aria-expanded="false"` that never opens, and an empty container.
  RED, observed (11 failed, 5 passed of 16): `expect(received).toBeInTheDocument()` (activation, Enter and
  Space, Escape inside the text, two disclosures, tabbing away), `Unable to find an element with the text`,
  `expected '' to match /(^|\s)size-11(\s|$)/` and `expected '' to match /(^|\s)text-ink-3(\s|$)/`. **Passed at
  once**: closed at mount, the two names, the button never disabled, the two different containers, and the
  name not changing with the state. Two Escape tests first passed at once because the stub never opens, so
  they were made to assert the text IS open before pressing Escape, and re-run before the RED commit.
  GREEN: the hook keeps the open state and a `useId` for the container; `close()` sets it false and focuses
  the button; Escape on the button or inside the text calls `close()` while open; the container is always in
  the document with `id` and its children only while open; the button has `aria-label`, `aria-expanded`,
  `aria-controls`, never `disabled`, `size-11`, `-my-3` (the box adds no height to its row, design § B2,
  confirmed by eye in 12f.10.31), `text-ink-3 hover:text-ink-2` at rest and `text-ink` open; the glyph is an
  `aria-hidden` SVG of a circle, a dot and a stem in `currentColor`. A test beyond the list: another key does
  not close it, and the two buttons name two different containers. **A test defect found by its mutation:**
  the tab-away test passed against a close-on-blur mutation, because `pressTab` moves focus with `.focus()`
  outside `act`, so React had not flushed the close when the test read the DOM. The test now wraps `pressTab`
  in `act`; the mutation then reds it. Any later test that moves focus with `pressTab` and asserts straight
  after needs the same wrapper. Mutations after the GREEN, each seen red and reverted: open by default reds
  eleven tests; the paragraphs rendered outside the container reds `aria-controls … only while open` and
  `Escape inside the text`; the container rendered only while open reds `aria-controls`; the Escape handler
  made a no-op reds both Escape tests; focus not returned reds `Escape inside the text` only; a close on blur
  reds the tab-away test; one state shared by every disclosure (a module variable) reds `activating again
  closes it`, the tab-away test, the two-disclosures test and the colour test; both names made `Info` reds
  the names tests (all sixteen, the lookups by name fail); `disabled` while open reds six tests including `never
  disabled`; the box class removed reds the box test; the glyph replaced by the character `ⓘ` reds the box
  test; a `style` attribute on the SVG reds the box test. Files created: `InfoDisclosure.tsx`,
  `InfoDisclosure.test.tsx`; no existing file edited.
- [x] 12f.10.13 `pressRangeKey`, the arrow-key helper design § K says is needed. RED `frontend/src/test/keyboard.test.ts`
  (Create), with the stub in `keyboard.ts` that does nothing. Tests: `::an arrow adds or removes one step`
  (34 to 35 and to 33), `::Home sets min and End sets max`, `::the result is clamped to min and max`,
  `::fires the input and change events`, `::does nothing when the keydown was prevented or the input is
  disabled`. RED: `expected '34' to be '35'`. GREEN: a stand-in for the browser's default action on a focused
  range input, as `pressEnter` stands for a button's. Page Up and Page Down are not modelled: their step is
  the browser's. What a test proves with it is the markup's side: a real, enabled range input with the right
  `min`, `max` and `step`, and no handler that swallows the key.
  **Done (RED commit `8a95c5a`, GREEN commit `b603a0a`).** The signature is `pressRangeKey(key: string):
  void`, acting on `document.activeElement` as `pressEnter` does; the stub is an empty function in
  `keyboard.ts`. RED, observed (11 failed, 4 passed of 15): `expected '34' to be '35'` (and `'33'`, `'100'`,
  `'10' to be '15'`, `'98' to be '100'`, `'99' to be '100'`, `'50' to be '51'`) and `expected [] to deeply equal
  [ '35' ]` (the React `onChange`). **Passed at once**: the prevented keydown, the disabled input, the key that is
  not an arrow, Home or End, and the focused text input, as the do-nothing stub satisfies them. GREEN: the
  helper returns unless the focused element is an enabled `<input type="range">`, fires `keydown` and stops if
  it was prevented, reads `min`, `max` and `step` (defaults 0, 100 and 1), moves by the key (arrows by one
  `step`, Home to `min`, End to `max`), clamps, then fires `input` (through the native value setter, so a
  React `onChange` sees it) and `change`. Page Up and Page Down are not modelled. Tests beyond the list: the
  declared step, a step that would pass the end, a React `onChange` receiving the value once, a key that is
  not modelled, a focused text input, and three presses in a row. The disabled input cannot take focus, so
  that test stubs `document.activeElement` for the one call and removes the stub in a `finally`. Mutations
  after the GREEN, each seen red and reverted: the `disabled` check removed reds the disabled test; the
  prevented-keydown check removed reds the prevented test; the step fixed at 1 reds the declared-step and the
  past-the-end tests; the `change` event removed reds the events test; the `type !== "range"` check removed
  reds the text-input test. **An equivalent mutation, said plainly:** removing the helper's own clamp changes
  nothing a test can see, because jsdom sanitises a range input's value to `min` and `max` itself, as a
  browser does; the clamp is kept so the helper states the rule, and it is not proven by a test. Existing file
  edited: `frontend/src/test/keyboard.ts` (one export and two private helpers added); created
  `keyboard.test.ts`.

**The share control, built up in steps a test can see** (design §§ B, C, C2, C3, B2; spec: operator-panel
requirements 947 to 1700)

- [x] 12f.10.13b **A typed share with more than 18 decimal places is refused in the field** (owner decision 50, which was taken after this unit's tasks were written; added 2026-10-10 after batch 1). The API refuses such a share with a 422 on the update and on the preview. As the tasks stood, `parseDraft` reads `33.3333333333333333333` (19 decimals, in range) as valid: the preview is asked and refused, and Save would show "The share must be above 0 and at most 100.", which is false for that value. Fix, in `share-value.ts`: a fourth refusal, `too-many-decimals`, when the CANONICAL form has more than 18 decimal places. Judged on the canonical form because that is what the panel sends: `1.5000000000000000000` typed (19 written decimals) is `1.5` and is valid; `0.123456789012345678` (18) is valid; `0.1234567890123456789` (19) is refused. Compared on the digits, never through a number. Order of the refusals: not a number, not above zero, above 100, then too many decimals. RED `share-value.test.ts`, new tests, against `parseDraft` as it is (`expected { valid: true, ... } to deeply equal { valid: false, refusal: 'too-many-decimals' }`). Tests that pass at once (the 18-decimal and the trailing-zeros cases) are proven by a mutation: the bound at 17, and the bound judged on the typed text. The control shows this refusal exactly as it shows the other three (tasks 12f.10.14 to 12f.10.17), with its own text, EN "A share has at most 18 decimal places." and the ES equivalent in the wording the other share texts use; no request is sent for it, neither the preview nor the save. The panel's delta spec gains the scenario; the main specs are untouched.
  **Done (RED `b3974a6`, GREEN `6cee667`).** `DraftRefusal` gained `too-many-decimals` and `parseDraft` checks the
  canonical fraction's length against a constant 18, after the three older refusals. RED as observed: the three
  19-decimal cases failed with `expected { valid: true, …(1) } to deeply equal { valid: false, …(1) }`. Passed at
  once: the 18-decimal case, the trailing-zeros case and the order case. Mutations after GREEN, each reverted with
  `git checkout`: the bound at 17 reds `18 decimal places is the longest valid share`; the bound judged on the
  typed text reds `the bound is judged on the canonical form, so trailing zeros do not count`. The order case has
  no mutant of its own that I tried; it is guarded only by the three early returns sitting above the new one.
  Existing files edited: `share-value.ts` and `share-value.test.ts` (the task), and the panel delta spec
  `specs/operator-panel/spec.md` (the refusal class and one scenario). The text for the field is wired in 12f.10.14
  to 12f.10.17.
- [x] 12f.10.14 Step 1, the field and its value. RED `ShareSlider.test.tsx` (Create), with the stub design § K names: an
  input with a fixed `size` of 12 and the `%` sign placed before it. `ShareSlider` is presentational: it takes
  the text, the handle, the disabled flag and its callbacks. Tests: `::the field is a text input with
  inputMode decimal and maxLength 12`, `::size is the number of characters typed, and 1 when empty` (`5`, `33.5`,
  `100`, twelve characters: RED `expected '12' to be '4'`; mutation: a constant `size`, and separately `size="0"`
  for the empty field), `::the input carries the field-sizing class and the one-character minimum width` (a
  class assertion, since jsdom cannot see the width; mutation: either class removed; if the pinned Tailwind has
  no utility for `field-sizing` the rule goes into `index.css` and the test asserts the class that uses it),
  `::the percent sign is the input's next sibling, aria-hidden, and not part of the value` (RED:
  `expected input.nextElementSibling to be the sign`; mutation: the sign appended to the value, and separately
  the sign at the wrapper's far end), `::a press on the wrapper outside the input focuses the input, and on a
  disabled control does not` (mutation: the handler removed; the handler ignoring `disabled`), `::an invalid
  value marks the field aria-invalid and tied by aria-describedby to its text, and turns the border loss`,
  `::the text shows a dot in both languages`, `::typing a % is not a number`, `::no element carries a style
  attribute` (**passes at once**; mutation: one `style={{}}`). GREEN: the wrapper carries the field look
  (`min-h-11`, border, `ground` fill, padding, `cursor-text`, `focus-within` ring), the input has no border, no
  fill and 2 px of right padding, then the sign in the same font and ink.
  **Done (RED `ebef9cf`, GREEN `6cc4cda`, one added assertion `e0c826d`).** `ShareSlider.tsx` is created with its full
  props (`fieldId`, `labelId`, `text`, `handle`, `value`, `disabled`, `invalid`, `describedBy`, `onText`, `onHandle`,
  `onStop`); this step draws the field only. `value` is the canonical share the text reads as, or `null`; the track
  and the stops of the next step use it. RED as observed, against the stub (size 12, sign before the input, no
  attributes): `expected '12' to be '4'` (and for `5`, `100`, and the empty field), `toHaveAttribute("inputmode",
  "decimal")`, `toHaveClass("field-sizing-content")`, `expected null not to be null` (the sign as next sibling),
  `toHaveClass("min-h-11")`, `toHaveFocus()`, `toBeDisabled()`, `toHaveAttribute("aria-invalid", "true")` and
  `"false"`. Passed at once: the twelve-character size (the stub's constant), the label name, the dot in both languages,
  `%` passed on as typed, a keystroke reaching only `onText`, and no `style` attribute. `field-sizing-content` is a
  utility in the pinned Tailwind 4.3.3, so `index.css` is untouched. Mutations after GREEN, each reverted with
  `git checkout`: a constant `size` reds the four size cases; `text.length` without the minimum reds the empty case;
  `field-sizing-content` removed and `min-w-[1ch]` removed each red the class test; the sign appended to the value
  reds the sibling test, both dot tests and the `%` test; a spacer put between input and sign reds the sibling test
  (this stands for the sign "at the far end"); the press handler removed reds both press tests; the handler
  ignoring `disabled` passed at first, because jsdom cannot focus a disabled input either way, so `e0c826d` asserts
  that the press on a disabled control is not default-prevented, and that mutation then reds it; a non-empty
  `style` on the wrapper reds the style test (`style={{}}` renders no attribute, so it is an equivalent mutant and
  was not used). Differences from the approved prototype: the focus ring is the panel's `gain` outline, as every
  other control of the panel has it, where the prototype draws it in `ink`; the wrapper is `rounded-md`. No existing
  file edited.
- [x] 12f.10.15 Step 2, the track and the stops. RED `ShareSlider.test.tsx`, with the stub track a bare `<input
  type="range">` with no attributes. Tests: `::the track is a range input with min 1, max 100, step 1` and named
  by the visible label (`queryByRole("slider", { name: "Share of the pool per trade" })`), `::its value text is
  the exact value while the handle sits at the rounded step` (`33.5% of the pool` at 34), `::the filled part's
  x2 and the four stops' cx are the positions that `share-value.ts` gives`, `::a stop at or below the handle takes the
  gain class and the others rule-strong`, `::the four stops are buttons named "Set the share to 25%" and so on,
  aria-pressed exactly when the value equals the stop`, `::Enter or Space activates a stop`, `::each stop and
  each box is 44 by 44 px by class and the track is 44 px tall`, `::each stop sits at one fixed class (left-[24.2424%]
  and so on)` (mutation: the stop turned into a `<span>`; and, separately, the box class removed), `::the
  vendor thumb classes and appearance-none are one constant` (class assertion), `::an arrow, Home and End move
  the handle through pressRangeKey` (35, 1, 100), `::the rendered tree has no style attribute`. RED:
  `expected null to be in the document`, `expected '1' to be '34'`. GREEN: the native range input over an
  `aria-hidden` inline SVG drawn with attributes, inset by half the thumb on each side, the stops stacked
  above the input from the handle's lower edge so none covers the handle. The legend is 12 px closer to the
  track than the first prototype, and that distance is approved (decision 48).
  **Done (RED `fc5accf`, GREEN `5b225d0`).** `ShareSlider.tsx` now draws the track, the drawing and the four stops
  under the field. It exports `RANGE_CLASS` (the one constant) and keeps the stops' four fixed `left-[...]` classes
  in a table; a test holds each class to `handlePosition`. RED as observed against the stub (a bare
  `<input type="range" />` and `RANGE_CLASS = "appearance-none"`): 26 of 47 failed. The first test of the step fails
  on `expect(queryByRole("slider", ...)).toBeInTheDocument()` (received null); the rest fail on Testing Library's
  "Unable to find an accessible element with the role slider / button" or on "the track has no drawing", which is the
  same absence read through `getByRole` (I kept `getByRole` in the helpers so a later failure names the missing
  part). No RED was an import, a type or a constructor error. Passed at once: everything of step 1, since the
  field is untouched. Mutations after GREEN, each reverted with `git checkout`: the stops turned into `<span>` reds
  12 tests; `size-11` removed from the stops reds the 44 px test; the track box `h-10` reds it too; every reached
  stop in the gain class reds the gain/rule-strong test; `x2` fixed at 50 reds the three position tests; `aria-pressed`
  given as "at or below the handle" reds the pressed test; the value text from the handle only reds the value-text
  and both translation tests; a fixed class `left-[50%]` for the 50 stop reds that stop's position test; `step={2}`
  reds the attribute test and both arrow cases; a `style` on the track box reds both style tests; `appearance-none`
  removed from the constant, and the thumb's `bg-gain` changed, each red the constant test. Differences, none visible
  in the tests: the value text of the track is the exact value when the text reads as one and the handle's step when
  it does not (the design leaves the invalid case open); a stop is `aria-pressed` only for a valid text equal to it;
  disabled draws the fill and the reached stops in `rule-strong`, as the prototype does. The generated stylesheet was
  checked by building the bundle to a scratch folder: the thumb, track, `disabled:` and `focus-visible:` variants
  compile to the selectors `...::-webkit-slider-thumb`, `:disabled::-webkit-slider-thumb` and
  `:focus-visible::-moz-range-thumb`, `field-sizing-content`, `min-w-[1ch]`, the four `left-[...]` classes and
  `w-[calc(...)]` are all present. Existing files edited: `locales/en.json` and `locales/es.json`, two keys under
  `strategies.detail.share` (`valueText`, `stop`), in the wording of design § I.
- [x] 12f.10.16 Step 3, `PoolShareEditor`: the value and Save. RED `PoolShareEditor.test.tsx` (Create,
  `vi.stubGlobal("fetch")`), with the stub container that renders `ShareSlider` over the stored value and a
  Save that never sends. The container holds the draft as `{ base, text, handle }` or nothing. Tests: `::a
  stored 33.5 shows 33.5 in the field and the handle at 34` (mutation: the field given the handle's value),
  `::moving the handle writes a whole number into the field` (from 33.5, one arrow gives 35; mutation: the
  decimal kept on a move), `::a stop jumps to its value`, `::typing keeps the text as typed and the handle
  follows only a valid value`, `::33,5 is sent as 33.5` (mutation: the comma rule removed), `::0, 100.5, an empty
  field and abc each leave Save disabled` (one case each; mutation: that case's check removed),
  `::0.5 is valid and can be saved`, `::the stored value typed back leaves Save disabled`, `::Save is enabled
  only for a valid value that differs from the stored one on an unarchived strategy`, `::no request is made
  before Save, whatever is moved, activated or typed` (mutation: a save on the change event), `::leaving the page
  after a change sends nothing` (mutation: a save on unmount), `::the request body is exactly
  {"allocation_percent":"33.5"}` (mutation: `enabled` added; the value as a number; the sign read into the
  value), `::a draft made on a stored value is dropped when the stored value moves` (mutation: the `base`
  comparison removed), `::the control makes no request but the share preview and the save` (no venue, no
  pair contract: spec "No Venue Is Read For The Check"). RED: `expected "spy" to be called with arguments`,
  `expected '30' to be '33.5'`. GREEN: the container over `share-value.ts` and `setStrategyAllocationPercent`.
  **Done (RED `460a5f9`, GREEN `b46f2e5`, test hardening `cd3abb2`).** `PoolShareEditor.tsx` holds the draft as
  `{ base, text, handle }` or nothing, reads the stored share with `readStored`, shows each refusal of `parseDraft`
  as a `text-xs text-loss` line tied to the field (`aria-describedby`, `aria-invalid`, never an alert), and saves
  `reading.canonical` through `useSetAllocationPercent`. The refusal of 13b is shown like the other three, with its
  own text, and the editor adds a test that a 19-decimal text sends nothing and an 18-decimal one can be saved. A
  stored value `readStored` cannot read renders nothing for now; 12f.10.17 puts its text there. RED as observed,
  against the stub (a field over the stored value that never changes and a Save that is enabled and does nothing):
  `expected '33.5' to be '35'`, `expected '33.5' to be '33'`, `expected '33.5' to be '75'`, `expected '33.5' to be
  '62.5'`, `expected '30' to be '33,5'`, `expected '30' to be '1'`, `expected '30' to be '40'`, `expect(element)
  .toBeDisabled()` for the cases that must leave Save disabled, `expected [] to have a length of 1 but got +0` for the
  body test, and `expect(received).toBeInTheDocument()` for each refusal text. 24 of 29 failed; the five that passed
  at once are the stored 33.5 case, the stored 0.5 case, the two no-request cases (the stub never sends) and the
  valid value with no refusal. Mutations after GREEN, each reverted with `git checkout`: the field given the
  handle's value reds the three stored-value tests; the decimal kept on a move reds the move, the left arrow and the
  stop tests; the handle following an invalid text reds the typing test; the comma rule removed (the typed text sent)
  reds `33,5 is sent as 33.5`; the `reading.canonical !== stored` comparison removed reds four tests; the `base`
  comparison removed reds the stale-draft test; a save on the change event reds eleven tests, including both no-request
  tests; a save on unmount reds `leaving the page after a change sends nothing`; `reading.valid` removed from the
  `changed` test reds the four invalid cases and three more; `archived` removed from Save reds the archived-draft
  test; `archived` removed from the field's `disabled` reds the archived test. Two things the first pass of the tests
  did not catch and `cd3abb2` fixed: the no-request tests asserted at once, a tick before a mutation calls `fetch`, so
  a save on the change event passed them (`settle()` now waits); and an archived strategy whose Save was not disabled
  passed, because an unchanged draft disables Save anyway (the new test makes a change and then archives).
  Not run: the task's mutations on the request body (`enabled` added, the value as a number, the sign read into the
  value), which live in `setStrategyAllocationPercent` (batch 1, task 12f.10.3) and in the field (12f.10.14); the
  tests that pin them are the exact body string here and the sibling test there. Existing files edited:
  `locales/en.json` and `locales/es.json` (label, notNumber, outOfRange, tooManyDecimals, save, saving) and
  `ShareSlider.tsx` (`describedBy?: string | undefined`, because `exactOptionalPropertyTypes` refuses `undefined`).
- [x] 12f.10.17 Step 3b, the states and the refusals. RED `PoolShareEditor.test.tsx`, new tests. Tests: `::while
  saving, Save reads Saving... and the track, the stops and the field are disabled`, `::a 422 shows "The share
  must be above 0 and at most 100." as an alert`, `::a 409 STRATEGY_ARCHIVED shows the archived text and the
  page re-reads the strategy, and the control turns read-only`, `::a 404 shows "This strategy no longer exists."
  and the page shows its not-found state`, `::a network failure, a 5xx and a 200 whose body is not a strategy
  each show "The share was not saved. Try again." and keep the draft`, `::an archived strategy's track, stops,
  field and Save are disabled` (mutation: the `disabled` removed from one of them, one case each),
  `::a stored value that cannot be read shows "The stored share could not be read, so it cannot be edited here."
  and no track, no field, no Save` (`1E-7`, an empty string), `::each refusal is a role=alert line`. RED: `expected
  null to be in the document`. **Passing at once** is the 5xx half, if the stub already surfaces any failure;
  mutation: the failure text dropped. GREEN: the states of design § C.
  **Done (RED `060a833`, GREEN `1899fa1`).** `PoolShareEditor.tsx` maps a failed save by status: 422 to the
  out-of-range text, 409 with code `STRATEGY_ARCHIVED` to the archived text, 404 to the gone text, anything else (a
  network failure, a 5xx, a 200 whose body is not a strategy, which `setStrategyAllocationPercent` throws on) to
  the failure text; one `role="alert"` line, the draft untouched. A stored value `readStored` cannot read renders the
  label and the unreadable text and no control. RED as observed: 16 of 48 failed, all on `expect(received)
  .toBeInTheDocument()` (the alert line, or the unreadable text, absent), except the one-line check that no alert
  exists before a save, which failed as `Unable to find role="alert"` after the helper's own presence assertion. The
  alert helper `alertLine()` asserts presence with `queryByRole` so a missing line fails on an assertion. Passed at
  once: the saving state and the archived state, because 12f.10.16's container already disabled everything on
  `busy` and `archived`; they are proven by mutation. Mutations after GREEN, each reverted with `git checkout`: the
  generic failure text turned into another text reds the four failure cases and the Spanish one; the 409 test
  changed reds the archived cases; the 404 test changed reds the gone case; `role="alert"` removed reds ten tests;
  `disabled` removed from the field's wrapper props reds the saving test; the saving label dropped reds the same
  test; the unreadable branch returning nothing reds the six unreadable cases; the draft dropped on error reds the
  five keep-the-draft cases. One case each for the archived disabling, done in `ShareSlider.tsx` and reverted:
  `disabled` removed from the track reds three tests, from the four stops reds three, from the field reds five
  (it is also the only one that reds the Save-on-archived test written in 12f.10.16). The tests use two hosts: the
  editor over a prop, and the editor under `useStrategy` as the page has it, which is what lets the 409 test see
  the strategy served archived on the re-read, and the 404 test see the second `GET`. What the editor cannot show
  by itself is the page's not-found state: with data cached, the page swaps its content for the not-found view
  when the re-read answers 404, which unmounts the editor, so its alert is on screen only until the re-read lands.
  That swap is the page's existing behaviour; 12f.10.24 mounts the editor and its test covers the page.
  Existing files edited: `locales/en.json` and `locales/es.json` (four keys: saveFailed, archived, gone,
  unreadable).

**"Saved"** (design § D; spec: "A Save Of The Share Or Of The Allowed Pairs Shows 'Saved'")

- [x] 12f.10.18 "Saved" for the share. RED `PoolShareEditor.test.tsx`, new tests, with the stub that mounts
  `InlineStatus` beside Save and never fills it. Tests: `::Saved shows when the PATCH answers 200 with a strategy`
  (RED: `expected null to be in the document`), `::the live region exists before the save, empty` (mutation: the
  region rendered only with its text), `::Saved is still there ten minutes later` (fake timers, 600,000 ms;
  mutation: a timer that clears it), `::Saved goes at the next movement of the handle, activation of a stop or
  keystroke in the field, tried in turn` (mutation: the reset removed), `::no Saved after a 422, a 409, a 404, a
  5xx or a body that is not a strategy` (one per status; mutation: the flag set on settle instead of on
  success), `::a refusal and Saved are never on screen together and a new save clears Saved before it is sent`,
  `::Saved is neutral ink, not gain`, `::Saved is gone when the page is left and the control is shown again`.
  GREEN: a boolean local to the control; no store; no timer.
  **Done (RED `4c49534`, GREEN `da14ed4`, test hardening `9a25f64`).** `PoolShareEditor.tsx` keeps one `saved`
  boolean: set by the per-call `onSuccess` of the save (so only on a 200 with a strategy, and after the hook has
  invalidated and the page holds the new state), cleared by any edit (handle, stop, key) and again when Save is
  pressed, before the request is sent. `InlineStatus` was already always mounted; the editor feeds it
  `strategies.detail.saved` ("Saved" / "Guardado", the owner's words). RED as observed against the stub (an
  `InlineStatus` that is never filled): 11 of 65 failed, all on `expect(element).toHaveTextContent()` (the region
  stayed empty). Passed at once: the six "no Saved after ..." cases and the neutral-ink case's region, the stub
  having no text to show. Mutations after GREEN, each reverted with `git checkout`: the region rendered only with
  its text reds 13 tests; the flag set on settle (`onSettled`) reds the six refusal cases and the
  refusal-and-Saved case; the reset removed from the edit path reds the three "goes when" cases; the reset removed
  from the Save path reds the "new save clears Saved" and "refusal and Saved" cases; `text-gain` in `InlineStatus`
  reds the neutral-ink case; a five-second timer that clears the flag reds `Saved is still there ten minutes later`
  once the fake clock is installed BEFORE the save (the first version of the test installed it after, so a timer
  started during the save was a real one and the test could not see it: `9a25f64` fixes that). The "refusal and
  Saved are never together" case and "a new save clears Saved" need the stored value NOT to move, which is why they
  use the editor over a prop; with the page above it, a changed stored value empties the draft and Save is disabled.
  Existing files edited: `locales/en.json` and `locales/es.json` (`strategies.detail.saved`); the GREEN commit also
  carries a one-line fix to the test helper `savedRegion()`, which has to find Save under its second name, "Saving...".
- [x] 12f.10.19 "Saved" for the allowed pairs. RED `AllowedPairsEditor.test.tsx`, new tests, with the stub that
  mounts `InlineStatus` and never fills it; the hook is NOT changed. Tests: `::Saved shows when the PUT answers
  200 and the list on screen is the saved one`, `::Saved goes at the next pair added or removed, and typing in
  the search box changes no pair and leaves it`, `::no Saved after a 409 or a 422`, `::if the re-read after a 200
  fails, so the list on screen is the old one, Saved is not shown` (the safe side; a limit of the existing hook,
  design § D), `::Saved stays ten minutes`, and, in `StrategyDetailPage.test.tsx`, `::the share's Saved and the
  pairs' Saved are two flags: a pair change leaves the share's, and the reverse` (mutation: one flag shared
  by both). RED: `expected null to be in the document`. GREEN: a local boolean next to the existing mutation,
  set from the settled success once the list on screen is the saved one.
  **Done in part (RED `dd51d58`, GREEN `f652c37`, one added test in the next commit).** The page-level test
  `StrategyDetailPage.test.tsx::the share's Saved and the pairs' Saved are two flags` is NOT written here: the page
  does not mount the share control until 12f.10.24, so the test cannot exist yet. It moves to 12f.10.24, which lists
  it as an added test. Everything else of the task is done. `AllowedPairsEditor.tsx` keeps `savedKey`, the list the
  last successful PUT answered; "Saved" shows while the stored list (the page's `strategy.allowed_pairs`) is that
  list, so a 200 followed by a failed re-read, which leaves the stored list old, shows nothing (the safe side the
  design names). A pair added or removed, and a new Save, clear `savedKey`; the search box never reaches the
  selector's `onChange`, so it leaves "Saved". A 200 whose body carries no list of pairs (the hook does not check it)
  sets nothing, so it never shows "Saved". The save button and the `InlineStatus` now share a wrapping row. The hook
  is not changed. RED as observed against the stub (the row and an `InlineStatus` that is never filled): 5 of 22
  failed on `expect(element).toHaveTextContent()`; passed at once: the empty-region test, the 409 and 422 cases, the
  failed-re-read case and the non-strategy case, all of which a never-filled region satisfies. Mutations after GREEN,
  each reverted with `git checkout`: the reset removed from the pairs' `onChange` reds the two "goes" tests; the
  stored-list comparison removed reds the failed-re-read test; the saved key taken from the client's list instead of
  the answer reds the non-strategy test; the flag set on settle reds eight tests; the clear removed from the Save
  handler passed at first, because after a 200 Save is disabled until a pair changes, which resets the key anyway.
  The path that matters is a 200 the page never received (Save stays enabled), then a refusal on the next Save, then
  the page catching up: the added test `a refusal and Saved are never on screen together` covers it and that
  mutation reds it. One condition of the first draft, "and the list on screen equals the saved key", was removed
  as unreachable: a draft is dropped once the stored list moves and any later edit clears the key, so no test could
  red it. Silent failure found, not fixed because the hook is out of this task: a 200 whose body is not a
  strategy shows no "Saved" and no error either; the owner sees nothing. Existing files edited:
  `AllowedPairsEditor.tsx` and `AllowedPairsEditor.test.tsx` (the task).

**The amount, the warning and the explanations** (design §§ C2, C3, B2)

- [x] 12f.10.20 The amount under the track. RED `ShareAmount.test.tsx` and `PoolShareEditor.test.tsx`, new tests, with the
  stub design § K names: an amount line that prints the first step's figure for every value. `ShareAmount` is
  presentational and takes strings from the preview and nothing from `['pools']`. Tests: `::a known amount reads
  "Asks for about 335.00 USDT per operation" from the served exact` (RED: `expected '10.00' to be '335.00'`),
  `::every whole value shows the amount of its own step` (1, 25, 34 and 100 with four different figures;
  mutation: an off-by-one in the lookup, and separately the first step for all), `::dragging the handle and
  activating a stop send no request and the figure follows at once` (mutation: the amount asked per value),
  `::the stored share with decimals shows the first read's exact and sends no second request`, `::the amount is
  cut down as text to the currency's decimals and never rounded up` (`4.996` reads `4.99`, not `5.00`; mutation:
  `Intl` given the unrounded number), `::a coin-margined pool uses its own decimals` (BTC, 8, from the existing
  `AMOUNT_DECIMALS` table), `::a stale balance shows the same line and "The pool's balance was last read at 14:03
  UTC and may be out of date."` (`HH:MM UTC`), `::no balance shows "The pool's balance has not been read yet, so
  the amount cannot be shown." and no figure, never a zero`, `::loading shows "Calculating the amount..." and no
  figure`, `::a failed read or a refused body shows "The amount could not be loaded." and the track, the stops,
  the field and Save stay usable` (mutation: the control disabled on the error), `::the row, and so its button
  slot, is present with a figure, with the em dash, with no balance and with a failed read`, `::the figure is the
  served string, never the pool's balance multiplied` (render with a `['pools']` balance that would give another
  figure and assert the served one; mutation: the component reading `['pools']` and multiplying), `::two pools
  are never summed or converted`. GREEN: `ShareAmount.tsx` and the lookup of design § C2. **Settled in design §
  O:** the figure is cut down as text and then given to `Intl`, by a helper in the same file as `rateText`,
  `frontend/src/features/strategies/format.ts`, using the decimals the trades table already uses for the
  pool's currency (the existing `AMOUNT_DECIMALS` in `features/overview/format.ts`, not a second table); the
  task records the helper's name, chosen in the neighbours' style.
  **Done (RED `83d8054`, GREEN `363a78b`).** The helper is `cutAmountText(amount, currency, locale)` in
  `features/strategies/format.ts`, beside `rateText` (the choice that was open: the cut-amount helper lives in
  `strategies/format.ts`, and it takes its decimals from `amountDecimals`, a new export of `overview/format.ts`
  that `amountText` now calls too, so there is still one table). It cuts the served digits at the currency's
  decimals as text, then gives them to `amountText`. `ShareAmount.tsx` (presentational: a `view` of known, loading,
  noBalance, failed or none, and a `trailing` slot for the amount's button, which 12f.10.23 fills) writes one line
  per state, the stale line under a stale figure with `HH:MM UTC` from `clockText`, and treats a served amount that
  is not a plain decimal as a failed read. `PoolShareEditor.tsx` reads the preview with `useSharePreview` and derives
  the view in `amountView`: a whole value from 1 to 100 reads `steps[n - 1]`, the stored share reads the first
  read's `exact` (when `exact.share` is that value; while the re-read after a save is in flight it shows the loading
  mark, and after it fails the failed line), no balance shows the sentence, and a typed decimal shows the loading
  mark for now, because the request for it is 12f.10.21. A figure that is already known stays on screen when only the
  background refresh fails. RED as observed against the stub (a `ShareAmount` that printed only a known figure,
  uncut, and an editor that gave it step 1 for every value): `cutAmountText` returned its input, so 19 cut tests
  failed with `expected '4.996000000000000000' to be '4.99'` and the like; 19 `ShareAmount` tests and 16 editor tests
  failed on `expect(received).toBeInTheDocument()`. Passed at once: the 18 editor tests that do not read the amount
  and, in the new ones, none (every new editor test asserts a text the stub could not write). Mutations after
  GREEN, each reverted with `git checkout`: an off-by-one in the step lookup reds five tests; the first step for
  every value reds the same five; `Intl` given the unrounded number reds 16 (the cut tests, the Spanish and BTC
  cases, in `format`, `ShareAmount` and the editor); the control disabled while the amount failed reds the
  failed-read test and two `Saved` tests; a `usePools` read multiplied into the figure reds the "never multiplied"
  test and four no-request tests. The test double for the editor keeps the preview reads apart from the other
  requests (`previews`), so the no-request assertions of 12f.10.16 still mean "no save". Existing files edited:
  `overview/format.ts` (the `amountDecimals` export, no behaviour change), `strategies/format.ts` and
  `format.test.ts` (the helper), `PoolShareEditor.tsx`, `PoolShareEditor.test.tsx` (the double), the two locale
  files (five keys: amount, amountStale, amountNoBalance, amountLoading, amountError).
- [x] 12f.10.21 A typed decimal's amount. RED `PoolShareEditor.test.tsx`, new tests (fake timers), with the stub that
  asks at once for every value. Tests: `::a typed 33.5 shows no figure, only the loading mark, until its
  answer, and then that answer's` (mutation: the previous amount kept on screen while loading),
  `::two typed values in quick succession send one request, for the last, 300 ms after the last keystroke`
  (mutation: the debounce removed; uses `useDebouncedValue`), `::an answer whose exact.share is not the value
  asked is refused` (compared in canonical form; mutation: the comparison removed), `::a value below 1 asks
  once at rest`, `::a text that is not a valid value sends no request and shows the em dash`, `::the request
  for a typed value carries ?share= with the canonical text`. RED: `expected null to be in the document`
  (the loading mark), `expected 2 to be 1` (the requests). GREEN: the third row of the table in design § C2.
  **Done (RED `b82bc43`, GREEN `27f495b`).** `PoolShareEditor.tsx` works out which value no served table covers
  (not a whole step from 1 to 100, not the stored share), holds it through `useDebouncedValue` for 300 ms and only
  then calls `useSharePreview(id, share)`; a value that is not yet the settled one shows the loading mark, so no
  figure stands beside a percentage it does not belong to, and an answer counts only when its `exact.share` read in
  plain form is the value (a different one is the failed line). The tests use the fake clock installed AFTER the
  first read, and a preview double that holds each asked answer until the test releases it. RED as observed against
  the stub (the same call with no pause and no comparison): four tests failed, `expected [ null, '12.34' ] to deeply
  equal [ null ]`, `expected [ null, '12.3', '12.34' ] to deeply equal [ null ]`, `expected [ null, '0.5' ] to deeply
  equal [ null ]` and `expect(received).toBeInTheDocument()` for the refused answer. The task's named
  `expected 2 to be 1` has no counterpart here because the RED asserts the request list; the same fact. Passed at
  once: the answer for a value no longer held, the em dash, the canonical `?share=`, the 18-decimal case and the
  whole-values-ask-nothing case, which a call with no pause satisfies. Mutations after GREEN, each reverted with
  `git checkout`: the previous amount kept on screen while loading reds the loading test and the stale-answer
  test; the pause removed reds three; the `exact.share` comparison replaced by true reds the refused-answer test;
  the "waiting for its own value" guard removed reds the loading and stale-answer tests. The amount view now reads
  one source per value, so the first read's lookup of 12f.10.20 and this one share a function. Existing files
  edited: `PoolShareEditor.tsx` and `PoolShareEditor.test.tsx` only.
- [x] 12f.10.22 The warning. RED `PoolShareEditor.test.tsx`, new tests, with the stub that never warns. Tests: `::a share
  that asks for less than the pool's minimum order shows the warning with the minimum, cut down as text`
  (`At this balance the share asks for less than the pool's minimum order, 5.00 USDT. Openings would be skipped
  until the share or the balance is larger.`), `::it is a role=status line in the loss colour, not an alert and
  never amber` (class assertions), `::it shows for a stored share under the minimum with no change made`
  (mutation: the warning tied to the draft), `::Save stays enabled while it shows` (mutation: Save disabled on
  `below_pool_minimum`), `::it shows for a typed 0.5 once its answer arrives and not while loading`, `::it is
  in the document with both information buttons closed`, `::a share the pool's minimum accepts shows no warning
  and neither does one too small for a pair: the panel checks no pair` (the spec's "A Share Too Small For A
  Pair Passes The Panel"). RED: `expected null to be in the document`. GREEN: from `below_pool_minimum` of the
  step or the exact amount, and `pool_minimum` of the body.
  **Done (RED `87a499d`, GREEN `a134cb6`).** The view of a known figure gained `belowMinimum`: the body's
  `pool_minimum` when the served step or `exact` says `below_pool_minimum`, otherwise `null`; the panel decides
  nothing, it carries the server's word. `ShareAmount.tsx` writes the line under the figure (and under the stale
  line) as `<p role="status" class="text-xs text-loss">`, with the minimum cut down as text by `cutAmountText`
  (`5.99` for a served `5.999999999999999999`). It reads the value in the field, not the stored one, so it also
  shows for the stored share on load, and it follows the handle. It gates nothing: Save, the field and the track
  keep their own conditions. No balance means no figure and no warning. RED as observed against the stub (the
  field in the view, never rendered): 9 of 105 failed, all on `expect(received).toBeInTheDocument()`; passed at
  once: the exactly-at-the-minimum case, the no-balance case, and the "accepts, and no pair checked" case, which a
  never-warning stub satisfies. Mutations after GREEN, each reverted with `git checkout`: the warning tied to a
  changed draft reds four tests (the stored-value, status, balance-falls and Spanish ones); Save disabled while the
  warning shows reds two; `role="alert"` reds the status test; `text-decision` (amber) reds the same test; the
  minimum not cut (the served 18-digit text) reds eight tests. The "less than the minimum" boundary
  (`amount < minimum`) is the server's, so the panel has no `<` to mutate; the exactly-at-the-minimum test holds the
  served flag. The task's "both information buttons closed" is asserted in 12f.10.23, where the buttons exist.
  Existing files edited: `ShareAmount.tsx`, `ShareAmount.test.tsx` (the new field in its fixture),
  `PoolShareEditor.tsx`, `PoolShareEditor.test.tsx` (a `unit` for the served steps and an exposed query client), the
  two locale files (`belowPoolMinimum`).
- [x] 12f.10.23 The two information buttons in the control. RED `PoolShareEditor.test.tsx`, new tests, using `InfoDisclosure`.
  Tests: `::at mount none of the three explanatory sentences is in the document, in English and in Spanish`
  (**passes at once**; mutations: open by default; a sentence outside its container), `::the label's button
  shows the hint and only that, and the amount's shows the first paragraph with the time as HH:MM UTC and then
  "Each pair also has a minimum order at the exchange..." in that order` (mutation: the contents swapped; the
  second paragraph dropped), `::the warning, the stale line, the validation text and a refused save are in the
  document with both buttons closed` (one case each; mutation: that line moved inside a container), `::both can
  be open together`, `::an open explanation survives a save, a refused save and a change of language, and is
  closed for another strategy` (mutation: the open state reset on every render; the control not keyed by the
  strategy), `::both buttons are enabled on an archived strategy and while saving` (mutation: `disabled`
  passed to them), `::Tab goes: the label's button, the field, the track, 25, 50, 75, 100, the amount's button,
  Save` (nine stops, with Save enabled by a change; with Save disabled the order ends at the amount's button,
  as the spec says, so a disabled button is no stop; mutation: the field rendered after the track; an
  information button given `tabIndex={-1}`), `::the stored 33.5 is read as "33.5% of the pool" with the handle
  at 34`. RED: `expected null to be in the document`. GREEN: the buttons sit right after the label and right
  after the amount; the explanation is rendered under its own row, in the flow, never a popover.
  **Done (RED `d80a2ff`, GREEN `2d103b3`; helper fix RED `aa44adb`, GREEN `6bc202d`).** `PoolShareEditor.tsx` puts
  `InfoButton` right after the label and, through a new `trailing` slot of `ShareAmount`, right after the amount;
  each has its own `useInfoDisclosure`, so each state is local, closed on every visit and kept through a save, a
  refusal and a change of language (the open text is simply re-rendered in the other language). Button 1 opens the
  hint under the label's row; button 2 opens, through a new `explanation` slot placed between the amount's row and
  the stale line and the warning (the prototype's order), the estimate with `HH:MM UTC` and then the pair note.
  The estimate is left out when no balance has been read: the approved prototype writes it only when a balance
  exists and always writes the pair note, and the spec is silent, so I followed the prototype. Neither button is
  ever given `disabled`. `InfoText` gained `flex flex-col gap-1.5 empty:hidden`, so a closed (empty) container takes
  no row and no gap; a class test pins it. RED as observed (no stub: there were no buttons): 22 of 129 failed, one
  on `expect(received).toBeInTheDocument()` for the buttons and the rest on Testing Library's "Unable to find an
  accessible element with the role button and name ...". Passed at once: the 107 earlier tests; of the new ones,
  none, since each asks for a button. Mutations after GREEN, each reverted with `git checkout`: open by default
  reds 16; the hint rendered outside its container reds nine; the two contents swapped reds six; the pair note
  dropped reds five; the amount's explanation reset when a save starts reds `an open explanation survives a save`.
  Not run, said plainly: "the field rendered after the track" (the field is in `ShareSlider`, and moving a whole block
  with a one-line edit was not safe), "a sentence outside its container" for the amount's two paragraphs, "the open
  state reset on every render" (the survive-a-save reset above stands for it), "disabled passed to the buttons"
  (`InfoButton` has no `disabled` prop; the two enabled-state tests hold that), and "the control not keyed by the
  strategy", which is the page's `key` and is tested in 12f.10.24. One defect of the test tooling found and fixed
  here: `pressTab` treated a button with `tabindex="-1"` as tabbable, so the first tab-order test passed against a
  button given `tabIndex={-1}` (the task's own mutation). `keyboard.test.ts` gained four `pressTab` tests, one RED
  on `expected <button tabindex="-1"></button> to be <button></button>`; `keyboard.ts` now filters on that attribute;
  with it the mutation reds both tab-order tests. Existing files edited: `InfoDisclosure.tsx` (the class),
  `ShareAmount.tsx` (the `explanation` slot), `PoolShareEditor.tsx`, `PoolShareEditor.test.tsx`, `keyboard.ts` and
  `keyboard.test.ts`, the two locale files (five keys: info, hint, amountInfo, amountHint, pairMinimumNote).
- [x] 12f.10.24 Mount in the page. RED `StrategyDetailPage.test.tsx`, new tests. Tests: `::the share control is the first of
  the settings column, under its heading and above the allowed pairs` (RED:
  `expected null to be in the document`; mutation: the control after the pairs), `::no text of the page's header
  line contains the share or "per trade"` (**passes at once**; mutation: the share printed in the header),
  `::the Strategies list shows no row's share` (in `StrategiesPage.test.tsx`; **passes at once**; mutation: the
  share printed in a row), `::an archived strategy shows the control read-only`. GREEN: `StrategyDetailPage.tsx`
  mounts `PoolShareEditor` keyed by the strategy's id as the first child of the `<aside>` after its heading.
  **Recorded edits of existing tests**, each listed with its reason: the fetch doubles of the page tests
  (`harness.tsx` `stubApi`, `strategyRoute`, and the local doubles of `StrategyDetailPage.test.tsx` and
  `StrategiesPage.test.tsx`) answer `GET .../share-preview`, `GET /api/webhook-origin` and a `PATCH`, because
  the page now asks for them; and `WebhookMessage.test.tsx::test_no_other_control_ever_requests_the_secret`
  clicks every other button of the page, which now includes the stops, the two information buttons, Save and
  both Copy buttons, so its fetch double must answer a PATCH; its assertion, that no request for the secret
  was made, does not change. The task reads every existing test that indexes the settings column's children
  (`test_enable_history_sits_in_the_settings_column_between_the_enable_switch_and_archive`) and records what
  moved; no assertion is relaxed.
  **Done (RED `0347e29`, GREEN `fb1198b`, extra test `641e879`).** `StrategyDetailPage.tsx` mounts
  `<PoolShareEditor key={subject.id} />` as the first child of the `<aside>` after its heading. No stub was needed:
  the control did not exist on the page. RED as observed: two of the four new tests failed, both on
  `expect(received).toBeInTheDocument()` with `received` null (the first-in-column test and the archived test);
  the header test and the list test passed at once, as the task said. Mutations after GREEN, each reverted with
  `git checkout`: the control after the pairs; `{allocation_percent}% per trade` printed in the header; the same
  text in a list row. They were applied together in one run and exactly three tests failed: the first-in-column
  test, the header test and the list test. I did not run them one by one. Added beyond the task: `::the share control starts over for another strategy
  and a typed value is not carried to it` (two strategies that store the same share; a value typed and an
  explanation opened on the first are gone on the second). It passes against the page with the `key` removed too:
  the page unmounts the whole editor while the next strategy loads, so the `key` is an equivalent mutant at page
  level. The key is kept as the cheap guard against a future placeholder-data read; the editor's own test of
  "closed for another strategy" (12f.10.23) pins the keyed behaviour. Recorded edits of existing tests:
  `harness.tsx` gained `unsyncedSharePreview`, `strategyRoute` answers `GET .../share-preview` with it, and
  `stubApi` answers `GET /webhook-origin` with `{"origin": null}`; the local double of `StrategyDetailPage.test.tsx`
  answers the preview. Not needed, said plainly: a PATCH answer in `strategyRoute` (it already answers the strategy
  for any method on `/strategies/{id}`, so `test_no_other_control_ever_requests_the_secret` clicks the stops and
  Save and passes unchanged, its assertion untouched); a preview answer in `StrategiesPage.test.tsx` (the list does
  not mount the control); and any change to `test_enable_history_sits_in_the_settings_column_...`, which compares
  positions between the switch, the history and archive and none moved. No test indexes the settings column's
  children by number. Gate after GREEN: lint 0, 63 files, 1,343 tests.

**The webhook block** (design §§ E, F; spec: "The Webhook Block Has Two Copy Buttons", "The Webhook URL Is
Shown And Copied With Its Host")

- [x] 12f.10.25 The full URL. RED `WebhookMessage.test.tsx`, new tests, with the stub that keeps showing the path alone.
  Tests: `::a configured host is shown in front of the path and no sentence about a missing host shows`
  (RED: `expected '/webhook/tradingview?secret=<your WEBHOOK_SECRET>' to be 'https://example.duckdns.org/webhook/...'`),
  `::a revealed secret goes after the host, percent-encoded`, `::while the host loads the path alone is
  shown`, `::{"origin": null} shows the path alone and "No public host is configured for the webhook, so only
  the path is shown. Put your webhook's host in front of it."`, `::a failed read, a 404 from an older API, or an
  origin the panel does not accept shows the path alone and "The webhook's host could not be loaded, so only
  the path is shown."` (mutation: the `new URL(value).origin === value` check removed), `::the URL is text,
  never inside an anchor, and no request starts with the origin` (mutation: the `<code>` turned into a link),
  `::the origin is read when the block is opened and not before` (the block is unmounted while closed; mutation:
  the read at the page's mount). Existing tests that assert the placeholder URL as a bare path
  (`PLACEHOLDER_URL`) keep passing while the double answers the origin route with a body the panel refuses;
  the task records any that needs an answer for `/webhook-origin`. GREEN: `useWebhookOrigin` and
  `webhookUrl` in `WebhookMessage.tsx`; `connect-src 'self'` is untouched (the origin is displayed and copied,
  never requested).
  **Done (RED `6077ea5`, GREEN `782d35d`).** `WebhookMessage.tsx` reads `useWebhookOrigin()` in the view that
  mounts when the block opens, builds the URL once with `webhookUrl(origin, value)` into one constant that the
  `<code>` prints, and shows one small sentence under the URL row: `hostUnset` for a settled `{"origin": null}`,
  `hostError` for a settled error, nothing while loading. Two keys added to both locale files with the design's
  exact texts (`strategies.webhook.hostUnset`, `hostError`). No stub was needed: the component already showed the
  path alone. **A defect of the earlier work, found here:** `fetchWebhookOrigin` (12f.10.8) turned a served string
  that is not a serialised origin into `null`, which the page cannot tell from `{"origin": null}`, so it would
  have said "No public host is configured" where the spec says "could not be loaded". It now throws an `ApiError`
  for such a string; the one test that pinned the old behaviour (`webhook-origin.test.ts`, "reads a served value
  that is not a serialised origin as no host") was rewritten to expect the rejection, RED on `promise resolved
  "null" instead of rejecting`. The decision between the two readings is the spec's own scenarios, so no product
  question arose. RED as observed: 13 failed of 57 in the two files. The four host tests failed on
  `expected '/webhook/tradingview?secret=<your WEB…' to be 'https://example.duckdns.org/webhook/t…'` (configured
  host, revealed secret, no anchor, read-when-opened, the last two because they wait for the host first); the
  null case and the seven failure cases failed on `expect(received).toBeInTheDocument()` with a null `received`
  (the sentence is absent). **Passed at once:** `::while the host loads the path alone is shown`, the only one
  that is true of the old code. Mutations after GREEN, each reverted with `git checkout`: the
  `new URL(value).origin === value` check replaced by `new URL(value) ? value : null` reds the three cases that
  serve a path, a trailing slash and upper case; the `<code>` text wrapped in `<a href>` reds the anchor test; the
  origin read added to the page's mount reds `::the origin is read when the block is opened and not before`.
  Existing tests edited, with their reasons: `WebhookMessage.test.tsx::setup` and the local fetch double of
  `test_leaving_the_view_...` answer the origin route with `{"origin": null}`, because the block now asks for it
  and their `answer` was for the secret; four assertions that counted every query in the cache
  (`findAll()` length 1 then 0) now count the secret's entries (`findAll({ queryKey: ["webhook-secret"] })`),
  since the host is cached too and an eviction removes only the secret; the same change in
  `StrategyHeader.test.tsx::test_collapsing_after_a_reveal_...`, whose double also stopped counting the origin
  request as a call for the secret. No assertion about the secret was relaxed: the eviction is still asserted
  for the secret's own entries, and the cache-key, console and request-URL checks are unchanged. Gate after GREEN:
  lint 0, 63 files, 1,357 tests. Said plainly: the application's `QueryClient` (`main.tsx`) has the library's
  default retry of three, so a failed read of the origin shows the path alone for about seven seconds before the
  sentence appears; the hook was not given `retry: false` because no task asked for it.
- [x] 12f.10.26 The two Copy buttons. RED `WebhookMessage.test.tsx`, new tests (`navigator.clipboard` stubbed), with
  the stub that renders both buttons and writes nothing. Tests: `::Copy URL sits beside Show secret and Copy
  message under the alert message`, `::the copied text equals the text of the <code> element, hidden and
  revealed` (RED: `expected "spy" to be called with arguments`; mutation: a second assembly of the URL in the
  handler), `::the message copied is the message shown`, `::a copy makes no request and never asks for the secret`
  (mutation: the handler calling the secret's refetch), `::with the secret hidden it copies the URL with the
  placeholder`, `::a missing clipboard and a rejected write both show "Could not copy. Select the text and
  copy it by hand." in the loss colour` (mutation: the `false` branch reporting success), `::the secret is in
  no query key, no console call and no request URL` (extends the existing test). GREEN: the URL is built once
  per render into one constant that the `<code>` prints and the handler is given; component state holds only
  which button was used, whether it worked and, for the URL, whether the secret was shown and whether a host
  was part of it, never the text. There is no `execCommand` fallback.
  **Done (RED `4e1cf1a`, GREEN `6cf5241`).** The stub (in the RED commit) renders both buttons and a status region
  beside each, with no handler. `WebhookMessage.tsx` now builds the alert message once per render into `message`;
  the `<code>` prints `url` and the `<pre>` prints `message`, and each button's handler is given the same
  constant. State is `copied: { button, ok } | null`: one value, so there can only be one "Copied" on screen, and
  no text. `copyText` answers; `ok` false shows the failure text through `InlineStatus tone="failure"` (the loss
  colour). The URL's button sits in the URL's row beside Show secret; the message's button sits in its own row
  under the `<pre>`. Four keys added to both locale files (`copyUrl`, `copyMessage`, `copied`, `copyFailed`) with
  the design's texts. The handler touches neither the secret's `requested` flag nor its query. The record of the
  secret's booleans for the URL ("was it shown", "was a host in it") is left to 12f.10.27, whose stub is exactly
  this behaviour. RED as observed (10 failed of 40, in `WebhookMessage.test.tsx`): `expected "spy" to be called 1
  times, but got 0 times` (and 2, 4 and 0 times, for the copied-text, message and no-request tests),
  `expected "spy" to be called with arguments` (the placeholder URL and the path alone), and
  `expect(element).toHaveTextContent()` (the three failure cases and the working "Copied"). The extended
  `never lets the secret reach a console call...` test failed on `expected "spy" to be called 2 times`. **Passed at
  once:** `::Copy URL sits beside Show secret and Copy message under the alert message` (the stub already places
  them); no mutation was run for it, said plainly. Mutations after GREEN, each reverted with `git checkout`: the
  URL assembled a second time in the handler, always with the placeholder, reds the copied-text test and the
  extended secret test; `void secret.refetch()` in the handler reds `::a copy makes no request...` and
  `test_no_other_control_ever_requests_the_secret`; the `false` branch reporting success (`ok: true`) reds the
  three failure cases; `console.log(text)` in the handler reds the extended secret test. Existing tests edited:
  `never lets the secret reach...` now stubs the clipboard and presses both Copy buttons while the secret is
  revealed before its unchanged assertions; the file's `afterEach` removes `navigator.clipboard`; the host helpers
  were moved from inside the host `describe` to module scope so both groups use them (no assertion changed).
  `test_no_other_control_ever_requests_the_secret` clicks both Copy buttons now (they are in the "every other
  button" list) and passes without an edit, since jsdom has no clipboard and the copy fails quietly. Gate after
  GREEN: lint 0, 63 files, 1,367 tests.
- [ ] 12f.10.27 The rule for "Copied". RED `WebhookMessage.test.tsx`, new tests, with the stub that shows "Copied"
  after any copy and never removes it. Tests: `::Copied shows beside the button that was used and only one
  Copied is on screen` (a copy with the other button moves it; mutation: two independent flags),
  `::closing the block removes it` (mutation: the block hidden with CSS instead of unmounted), `::the URL copied
  with the placeholder, then Show secret: Copied is gone` and the reverse, `::copied revealed, then Hide secret:
  Copied is gone` (mutations: the clearing removed from the Show handler, and separately from the Hide handler),
  `::after that, showing or hiding the secret again does not bring Copied back` (mutation: the state kept and
  only hidden by the render check), `::the URL copied as the path alone, then the host loads: Copied is gone`
  (mutation: the render check of the recorded booleans removed), `::the message's Copied survives showing and
  hiding the secret` (mutation: the handlers clearing every copy state instead of the URL's), `::the clipboard
  never holds something the screen does not show next to "Copied"`. RED: `expected "Copied" to be gone`.
  GREEN: the Show and Hide handlers clear the URL's copy state, and the render shows "Copied" only while both
  recorded booleans still equal the present. The panel does not claim to clear the clipboard when the secret is
  hidden or the view is left (design § E, accepted by the owner).

**Texts, the guard and the gate**

- [ ] 12f.10.28 Localization. Tests that pass at once, in `frontend/src/features/strategies/PoolShareEditor.test.tsx` and
  `WebhookMessage.test.tsx` (the page-level one in `StrategyDetailPage.test.tsx`): `::every text of design § I
  reads exactly as written in English and in Spanish, with each state brought on screen` (a table of both
  columns held in the test, so a reworded locale value is red; the spec's "The Detail Page's Follow-Up Texts
  Are Exactly These" and the Spanish scenario of "Every Panel String Is Localized"), `::every new key exists
  in both languages` (the flattened key sets of `strategies.detail.share`, `strategies.detail.saved`, the six
  new `strategies.webhook` keys and `strategies.performance.byPair.winRate`), `::the owner's own words are
  unchanged` ("Saved" / "Guardado", "Copied" / "Copiado"). Mutations, each reverted: one Spanish value left
  in English and, because an untranslated value equals its English twin (the lesson of 9p.5.23), the Spanish
  texts are required BY NAME, so a value left in English reds the case; one Spanish key deleted.
- [ ] 12f.10.29 The source guard. RED-less test in `frontend/src/shared/theme.test.ts`, one new test:
  `::test_no_non_test_source_file_has_a_style_prop` (a search of every non-test file under `frontend/src` for
  `style=`; it passes at once today, U8). Mutation: one `style={{}}` on any element, seen red. The test also
  searches `.style.`, `setProperty`, `cssText` and `setAttribute("style"`, because the spec forbids "a style
  attribute or a style property" and not only the prop; if a legitimate non-test use of one exists today the
  test lists it and the task records the exception rather than weakening the guard. The slider's own
  "no style attribute in the rendered tree" is asserted in 12f.10.14 and 12f.10.15. The amber allow-list of
  `frontend/src/features/overview/panel-tokens.test.ts` is not edited.
- [ ] 12f.10.30 Confirm and gate: `cd frontend && npm run lint && npm test`. Record the observed totals before and after, the
  recorded edits by group (the `by_pair` builders; the By pair header assertion; the fetch doubles and the one
  every-other-button test; any settings-column order test that moved), and that no other existing test
  changed (`git diff --name-status` lists exactly the modified test files named in this unit). Then the spec
  check, each requirement of `specs/operator-panel/spec.md` added on 2026-10-06 to the task that covers it:
  the share is first and only in the settings column, 12f.10.24; a field above a track with four stops,
  12f.10.14 and 12f.10.15; the exact value and what it refuses, 12f.10.5 and 12f.10.16; Save only on an
  explicit press, 12f.10.16 to 12f.10.18; the amount, 12f.10.7, 12f.10.20 and 12f.10.21; the warning,
  12f.10.22; the per-pair limit not checked and stated, 12f.10.22 and 12f.10.23; the two information buttons,
  12f.10.12 and 12f.10.23; the keyboard and the names, 12f.10.15 and 12f.10.23; "Saved", 12f.10.11, 12f.10.18
  and 12f.10.19; the two Copy buttons, 12f.10.10, 12f.10.26 and 12f.10.27; the URL with its host, 12f.10.8
  and 12f.10.25; By pair's win rate, 12f.10.2 to 12f.10.4 (the integer comparison of design § O); no browser money, no inline style,
  no relaxed policy, 12f.10.20 and 12f.10.29 and the CSP check of 12f.10.31; the texts, 12f.10.28. **The
  table of what the browser cannot log, each with its pin:**

  | Failure | Pinned by |
  |---|---|
  | A wrong value sent (a field other than the share, a number instead of a string) | the exact-body test, 12f.10.16 |
  | A slip of the handle saves | no request before Save, and none on unmount, 12f.10.16 |
  | "Saved" shows although nothing was saved | one test per refusal, 12f.10.18 |
  | The stored share is not a plain decimal | the unreadable state, 12f.10.17 |
  | The clipboard holds something other than what the owner believes | both directions and the late host, 12f.10.27 |
  | A copy requests the secret | the request count and the every-other-button test, 12f.10.24 and 12f.10.26 |
  | The origin becomes something the browser requests | no request starts with the origin, 12f.10.25 |
  | A win rate disagrees with its counts | the end checks and the integer comparison of 12f.10.4 |
  | The amount is not what the next operation asks for, or the panel multiplies | the served-string test, 12f.10.20 |
  | A typed decimal's answer arrives after the value changed | the `exact.share` comparison, 12f.10.21 |
  | An information button does nothing, or its text is on screen from the start | closed-at-mount and open-on-activation, 12f.10.12 and 12f.10.23 |
  | A `style` prop is added | the source guard, 12f.10.29 |
  | The slider is drawn wrongly in one browser, or the sign stands off the number | not testable in jsdom: the owner's review by eye, 12f.10.31 |
- [ ] 12f.10.31 Owner step, before the push: the review by eye. **The fixture file `frontend/vite.fixture.config.ts` is the owner's,
  untracked, and no task edits it.** Today it serves a `by_pair` without `wins` and `win_rate`, so with the new
  check the performance block would show its error state until the fixture serves them; that is the check
  working, not a defect. What the owner's fixture must serve for the review: (a) on
  `GET /api/performance/strategies/{id}`, each `by_pair` entry with `wins` and `win_rate` that agree with
  `trades`: 3 of 5 `"0.6000000000"`, 7 of 12 `"0.5833333333"`, 199 of 200 `"0.9950000000"`, 1,999 of 2,000
  `"0.9995000000"`, 4 of 4 `"1.0000000000"`, 0 of 3 `"0.0000000000"`, 1 of 5,000 `"0.0002000000"`; (b)
  `GET /api/webhook-origin` answering `{"origin": "https://example.duckdns.org"}`, and, by a switch of the
  fixture's own (a strategy id or a query value), `{"origin": null}`, a 404 (an older API), a 500 and a slow
  answer for the loading state; (c) `GET /api/strategies/{id}/share-preview` with `steps` numbered 1 to 100
  whose amounts are the pool's total times the step over 100 to 18 places (the fixture's own stand-in
  arithmetic, never the panel's), `exact` for the stored share and, honouring `?share=`, for the share asked
  (canonical in `exact.share`), `pool_minimum` `"5.000000000000000000"`, and these cases: a pool of 300 USDT so
  the warning shows at 1% and at a typed 0.5, a stale balance (`observed_at` five minutes ago, `stale` true),
  a pool never read (`balance` null, `exact` null, `steps` `[]`), a failing preview (a 500, and a body with 99
  steps), a slow preview, and a pool of 1000 USDT as the ordinary case; (d) `PATCH /api/strategies/{id}`
  answering the strategy view with the `allocation_percent` it was sent, in plain notation, and the failures
  worth seeing (422, 409 `STRATEGY_ARCHIVED`, 404, a 500, a 200 whose body is not a strategy, a slow answer for
  "Saving..."); (e) strategies whose stored share is `30`, `33.5` (a stored decimal), `0.5`, `0.0000001` (the
  plain notation), `1E-7` or `abc` (the unreadable state) and an archived one; (f) the allowed pairs `PUT`
  answering 200 for "Saved" and a failing one. Run the backend (the 12f-1 code) and `cd frontend; npx vite --config
  vite.fixture.config.ts`. **What to look at, everything design § K's by-eye list and its third revision say
  jsdom cannot show.** The owner already reviewed the PROTOTYPE on 2026-10-06 in Firefox and by keyboard
  (owner-decisions.md, decision 48): in Firefox it works and the percent sign follows the text, Tab goes
  through the stops, and Enter, Space and Escape behave. So a second browser and the keyboard are items to
  CONFIRM on the real panel, not items never seen (design § O). **It leads with the three things only the
  real panel can show, none of which the prototype had:** (L1) the panel's own fonts (Archivo and IBM Plex,
  not the prototype's system font), including the height of the control (item 3b) and the sign against the
  number (item 3c); (L2) **the Content-Security-Policy with the built bundle served by FastAPI and the
  console free of violations** (item 4); (L3) a screen reader on the two information buttons, their names,
  their expanded state and the opened text (item 3e). Then the rest: (1) confirm the look of the slider in
  Chromium and in Firefox (Safari if the owner uses it): the handle, the filled part, the stops under the
  handle's centre; (2) confirm dragging by pointer and by touch, the arrow, Home, End and Page keys, the
  focus ring; (3) the
  field above the track and the legend close under it, that a press just under the handle at a stop takes the
  stop and never blocks grabbing the handle, and that the four targets never touch at 300 px; (3a) the amount
  under the legend following the handle as it is dragged; (3b) **the height of the control with both
  explanations closed, in the panel's own fonts** (Archivo and IBM Plex, not the prototype's system font):
  the third prototype measured 252 px from the label to the Save row at 300 px, against about 450 px with the
  three paragraphs on screen, and no test can measure it; (3c) **the `%` sign, with the panel's font**: in a Chromium-based browser,
  touching the number at one digit, at `33.5`, at `100` and at twelve characters, an empty field with the
  sign one character from the left and the caret at the end not clipped; in Firefox, confirm that it follows
  the text as it did in the prototype, at those same lengths and with the sign inside the field at twelve
  characters in a 300 px column (what mechanism Firefox applied to the field's width was not measured). **If
  the sign stands a character off in a browser without `field-sizing` on the real panel, a task for the
  design's fallback (§ B: the mirrored span, applied only where the property is missing, measured in that
  engine before it is trusted) is added.** (3d) each
  information button's 44 px box touching its neighbours and covering none, the glyph, the page moving DOWN and
  not sideways when an explanation opens; (3e) **the keyboard alone, confirmed on the real panel** (Tab through the nine stops, Enter, Space and
  Escape on each information button, the arrow keys on the track), **and a screen reader on the two
  buttons** (their names, their expanded state and the opened text), which the prototype review did not
  cover; (4) **the CSP: the built bundle served by FastAPI.** `cd frontend && npm run build`, then the
  backend with `PANEL_DIST_DIR` set to the absolute path of `frontend/dist` and the usual local settings
  (this is the real local backend, not the fixture, whose dev server sends no policy); open the strategy page
  with the browser console visible: no Content-Security-Policy violation, the slider dragged and driven by
  keys, the return chart and the fonts as § 13 already asked to rehearse; (5) the clipboard in a real secure
  context (`localhost`) and its failure text over plain HTTP on another address; (6) the By pair table's width
  in English and in Spanish (the Spanish heading is `% acierto`; the table scrolls sideways inside its wrapper
  where it does not fit); (7) every text of design § I in both languages, and the Spanish form of the win
  rate. The owner's observations become tasks here, as 9p.5.27 to 9p.5.33 did; the review is not a gate the
  tests can pass.
- [ ] 12f.10.32 Owner step, after the merge: deploy 12f-2. `sudo -u strategy -H git -C /opt/strategy-manager/app pull --ff-only`; **no restart**
  (frontend only, and the panel is not served while `PANEL_DIST_DIR` is unset). 12f-1 must already be deployed.
  Update the delivery log after the merge (the standing working agreement; this list writes no entry).

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")` and a stubbed `navigator.clipboard`; fake timers for the 300 ms and the ten minutes; `renderHook` for the hooks; the owner's review by eye with `vite.fixture.config.ts`, and the built bundle served by FastAPI for the CSP.
Rollback boundary: a revert restores the page as it is today (no share control, no "Saved", no Copy buttons, the path alone, four columns), which works against the new API: the older panel's check ignores keys it does not know. The two new routes and the setting stay unread.
Forecast: 4,500–6,500 changed lines (design § L forecasts 2,800–4,100, of which the amount and its warning are 600 to 800 and the information buttons and the field's wrapper 250 to 350). Derived bottom-up: about 1,600 of production code and locale keys (types and API 250, `share-value.ts` 120, `ShareSlider` 250, `PoolShareEditor` 250, `ShareAmount` 120, `InfoDisclosure` 100, `InlineStatus` 30, the clipboard, debounce and URL helpers 90, `WebhookMessage` 120, `AllowedPairsEditor` 30, `PairStatsTable` and `format.ts` 100, both locale files 140), and tests at about two and a half times that, because in this change the test files have roughly doubled every earlier forecast. Information only.

---

## PR 13 — Settings: exchange key cards, form, delete flow (900–1,300 lines)

### Unit 10c-card — `ExchangeKeyCard`, read-only and no-key marks (350–500 lines)

**Files**: Create `frontend/src/features/settings/{SettingsPage,ExchangeKeyCard}.tsx`.

- [ ] 10c.1 RED `frontend/src/features/settings/SettingsPage.test.tsx::test_no_exchange_tabs_lists_every_exchange` (Settings.dc.html).
- [ ] 10c.2 RED `frontend/src/features/settings/ExchangeKeyCard.test.tsx` (rewritten 2026-09-29, decision 30): `::test_no_key_ever_stored_shows_neutral_empty_state_no_amber_border`, `::test_readonly_key_shows_amber_border_and_cannot_trade_sentence`, `::test_degraded_no_key_but_enabled_pool_shows_amber_border_and_no_key_stored_sentence` (decision 20: amber "no key" versus neutral "no key", by whether the pool is enabled), `::test_verified_key_shows_last4_reads_and_trades_or_reads_only_no_withdrawal_checked_date`, `::test_owner_confirmed_key_shows_trade_not_verified_and_withdraw_not_verified_with_confirm_dates_and_never_no_withdrawal`, `::test_not_verified_marks_are_neutral_not_amber`, `::test_unrecorded_key_shows_not_validated_and_both_marks`, `::test_card_never_renders_a_raw_permissions_payload`.
- [ ] 10c.3 GREEN (rewritten 2026-09-29, decision 30): `SettingsPage` (`['credentials']` query, no exchange scope per 7s.1); `ExchangeKeyCard` per design's three-state rendering (neutral / read-only amber / DEGRADED amber) plus the source-driven marks (`VERIFIED` / `OWNER_CONFIRMED` / `UNRECORDED`) and the i18n keys of design § G (`settings.card.tradeNotVerified`, `settings.card.withdrawNotVerified`, `settings.card.confirmedOn`).
- [ ] 10c.4 RED + GREEN (added 2026-09-30, deferred from PR 10c with the owner's agreement): the exchange tabs' read-only and no-key marks (decisions 18 and 20; design § Visual design, amber sub-label on the tab). `ExchangeTabs` reads the same `['credentials']` query `SettingsPage` introduces. A READ_ONLY key gives the tab an amber "read-only" sub-label, and an exchange with no active key (DEGRADED) gives an amber "no key" sub-label; a trade-capable key gives none. While credentials load or fail, the tab shows no mark and never claims the key is fine. Both marks are in EN and ES, and `decision` stays on the component allow-list. RED tests go in `frontend/src/shared/layout/ExchangeTabs.test.tsx`. Why deferred: PR 10c had no credentials client, and this unit builds one.

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: two components; revert removes Settings' card rendering, the route stays reachable but empty.
Forecast: 350–500 lines.

### Unit 10f-form — `KeyEntryForm` (300–450 lines)

**Files**: Create `frontend/src/features/settings/KeyEntryForm.tsx`.

- [ ] 10f.1 RED `frontend/src/features/settings/KeyEntryForm.test.tsx` (rewritten 2026-09-29, decision 30): `::test_fields_cleared_in_finally_regardless_of_outcome`, `::test_submitted_via_plain_async_handler_not_use_mutation_secret_never_in_mutation_cache`, `::test_password_type_autocomplete_off_on_secret_field`, `::test_readonly_key_warning_shown_on_200_with_read_only_key_warning`, `::test_422_502_409_outcome_reason_shown_i18n`, `::test_binance_form_shows_two_unchecked_confirmation_checkboxes_submit_disabled_until_both_ticked`, `::test_bybit_form_shows_no_confirmation_checkboxes_and_sends_none`, `::test_binance_submit_sends_both_confirmations_true`, `::test_confirmations_are_reset_in_finally_with_the_fields`, `::test_422_confirmation_required_reason_shown_i18n`.
- [ ] 10f.2 GREEN (rewritten 2026-09-29, decision 30): `KeyEntryForm`: local component state, plain `apiFetch` call, no `useMutation`; for Binance only, the two checkboxes `settings.key.confirm.withdrawals` and `settings.key.confirm.futures` with the help text `settings.key.confirm.help`, and the error keys `settings.key.error.confirmationRequired`, `.confirmationNotApplicable`, `.permissionsUnavailable` (EN/ES).

Gate: `cd frontend && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: one form; revert removes add/replace, existing keys are unaffected.
Forecast: 300–450 lines.

### Unit 10d-delete — `DeleteKeyButton`, `DeleteKeyDialog` (250–350 lines)

**Files**: Create `frontend/src/features/settings/{DeleteKeyButton,DeleteKeyDialog}.tsx`.

- [ ] 10d.1 RED `frontend/src/features/settings/DeleteKeyDialog.test.tsx::test_delete_requires_explicit_confirmation_not_single_click`, `::test_409_exchange_not_flat_reasons_rendered_enabled_strategies_symbols_allocations_reservations_attempts`, `::test_confirmed_successful_delete_shows_same_empty_state_as_never_configured`.
- [ ] 10d.2 GREEN: `DeleteKeyButton` (shown only when a key is active) → `DeleteKeyDialog`, invalidates `['credentials']` on success.

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: two components; revert removes the delete control, the card's other content is unaffected.
Forecast: 250–350 lines.

---

## Cross-PR test sweep (run once, after PR 13)

- [ ] X.1 `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short` — full suite.
- [ ] X.2 `cd frontend && npm run lint && npm test` — full suite.
- [ ] X.3 `cd frontend && npm run build` — the production build the CSP rehearsal (design decision 13, "font-src falls back to default-src 'self'") must load without a console CSP violation, checked manually by the owner against the deployed `PANEL_DIST_DIR` bundle.
- [ ] X.4 Grep sweep: no remaining reference to `bybit_api_key`, `bybit_api_secret`, `binance_api_key`, `binance_api_secret`, `credentials_from_settings`, or `recharts` anywhere under `backend/src` or `frontend/src`/`package.json`.
- [ ] X.5 i18n sweep: every key referenced by a new component exists in both `frontend/src/shared/i18n/locales/en.json` and `es.json` — a RED test per feature already covers this per-unit; this is the final cross-feature confirmation.
