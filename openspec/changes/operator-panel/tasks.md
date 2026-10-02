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

## Delivery log

Updated after every merge and deploy. With this and `git log`, the state can be resumed from
any machine.

**Production now** (2026-10-02, VPS time): `main` at `ed4c9f1`, alembic `0027`, `DRY_RUN=true`, the
frontend is not served. Enabled pools: `bybit/usdt-m/USDT` and `binance/usdt-m/USDT`. The vault
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

## Migration rehearsal (0024, 0025, 0026, 0027)

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

- [ ] 9d.1 RED `frontend/src/features/strategies/StrategyDetailPage.test.tsx::test_shows_active_x_days_since_first_activation_date`, `::test_never_enabled_shows_no_activation_date`.
- [ ] 9d.2 RED `frontend/src/features/strategies/ArchiveDialog.test.tsx::test_archive_requires_explicit_confirmation_not_single_click`, `::test_409_open_position_reasons_rendered_symbols_allocations_reservations_attempts`, `::test_409_still_enabled_rendered`.
- [ ] 9d.3 RED `frontend/src/features/strategies/AllowedPairsEditor.test.tsx::test_removing_last_pair_without_replacement_prevented`, `::test_adding_a_pair_submits_full_updated_set`.
- [ ] 9d.4 GREEN: the container + presentational tree per design's component list; `['strategy',id]`, `['strategy',id,'events']` queries.
- [ ] 9d.5 (added 2026-10-02, decision 41; needs PR 12v-4) `AllowedPairsEditor` is built on `PairSelector` (unit 9vd), never on a free-text field. RED `frontend/src/features/strategies/AllowedPairsEditor.test.tsx::test_stored_pair_missing_from_the_catalogue_is_kept_and_marked_no_longer_listed` (stored `SFPUSDT`, available pairs without it: the chip stays, and an untouched save sends it), `::test_a_removal_only_save_is_allowed_when_the_available_pairs_failed_to_load`, `::test_adding_is_blocked_while_the_available_pairs_failed_to_load`, `::test_409_pairs_changed_shows_the_review_and_save_again_text`, `::test_422_unknown_pairs_names_the_symbols`. 9d.3's two tests keep their names and meaning, driven through the selector.

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: one page; revert leaves `/strategies/:id` unreachable via the list (list still works).
Forecast: 500–700 lines.

### Unit 9w-webhook — webhook message, Show secret (300–400 lines)

**Files**: Create `frontend/src/features/strategies/{WebhookMessage,webhook-message}.{tsx,fixture.json}`;
Create `backend/tests/signals/domain/test_webhook_message_fixture.py` (cross-language guard).

- [ ] 9w.1 RED (backend) `backend/tests/signals/domain/test_webhook_message_fixture.py::test_frontend_fixture_parses_through_tradingview_alert_from_payload_after_placeholder_substitution` — reads `frontend/src/features/strategies/webhook-message.fixture.json` (read-only from this test's perspective) and parses it via `TradingViewAlert.from_payload` after substituting sample values for every `{{...}}` placeholder.
- [ ] 9w.2 RED (frontend) `frontend/src/features/strategies/WebhookMessage.test.tsx::test_url_shows_placeholder_by_default_not_the_secret`, `::test_show_secret_click_fetches_get_webhook_secret_substitutes_in_place`, `::test_no_other_control_ever_requests_the_secret`, `::test_leaving_the_view_restores_placeholder_and_evicts_query_cache`.
- [ ] 9w.3 GREEN: `webhookMessage(strategyId)` pure function rendering `signals/domain/alert.py:7-12`'s exact JSON shape with `signal_type` substituted; `WebhookMessage` component with local "revealed" state, `['webhook-secret']` fetched only on click, `queryClient.removeQueries` on unmount/navigate.

Gate: `cd backend && uv run pytest --tb=short backend/tests/signals/domain/test_webhook_message_fixture.py` + `cd frontend && npm test`.
Harness: N/A backend (pure parse test reading a fixture file); `vi.stubGlobal("fetch")` frontend.
Rollback boundary: one shared fixture + one component; revert removes "Show secret", the placeholder-only message still renders.
Forecast: 300–400 lines.

### Unit 9p-pairs — `PairStatsTable`, `TradesTable`, `StrategyPerformance` (200–250 lines)

**Files**: Create `frontend/src/features/strategies/{PairStatsTable,TradesTable,StrategyPerformance}.tsx`.

- [ ] 9p.1 RED `frontend/src/features/strategies/PairStatsTable.test.tsx::test_pair_removed_from_allowlist_still_shown_with_historical_stats`.
- [ ] 9p.2 RED `frontend/src/features/strategies/TradesTable.test.tsx::test_infinite_query_keyset_cursor_loads_more_on_scroll_or_click`.
- [ ] 9p.3 GREEN: both tables + the reuse of `LedgerLine`/`ReturnChart`/`MonthlyGrid` for one strategy's contribution.

Gate: `cd frontend && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: two presentational tables; revert removes them, detail page renders without them.
Forecast: 200–250 lines.

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
- [ ] 9v0.3 Owner step: run it on the VPS as the `strategy` user and record the output in "PR 12v-0 — Probe P7 results" below. PR 12v-1 does not start before this.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/scripts/test_check_public_catalogue.py`.
Harness: `httpx.MockTransport` locally; the real run is the owner's, GET-only, with no credential loaded.
Rollback boundary: one dev script and its test; nothing imports it.
Forecast: 200–300 lines.

#### PR 12v-0 — Probe P7 results

Not run yet. To be filled by the owner's run (9v0.3):

| Item | Bybit `linear` | Binance USDⓈ-M |
|---|---|---|
| P7.1 HTTP status with no signature and no key header | | |
| P7.2 entries listed; by contract type; by status; by settle or margin coin | | |
| P7.3 `nextPageCursor` at `limit=1000` (present? empty on the last page?); pages at `limit=200`; every entry once? | | n/a |
| P7.4 pairs available to a USDT pool | | |
| P7.5 `SFPUSDT` / `AAVEUSDT` / `STXUSDT` available | | |
| P7.6 response bytes; elapsed; rate-limit headers | | |

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

- [ ] 9va.1 RED `backend/tests/shared/infrastructure/bybit/test_public_transport.py::test_public_get_refuses_a_nonzero_retcode_over_http_200`, `::test_public_get_returns_the_result_object_not_the_envelope`, `::test_public_get_sends_no_bapi_header`, `::test_public_transport_constructor_takes_no_signer` (`inspect.signature`); `backend/tests/shared/infrastructure/binance/test_public_transport.py::test_public_get_refuses_a_negative_code_and_http_451_like_the_signed_transport`, `::test_public_get_sends_no_api_key_header_and_no_signature_parameter`, `::test_binance_transport_get_public_answers_through_the_public_transport`. RED against stubs that return the raw body. The two "sends no header" tests pass against any stub; mutation: adding an `X-BAPI-API-KEY` / `X-MBX-APIKEY` header reds them.
- [ ] 9va.2 GREEN: `BybitPublicTransport(http)` and `BinancePublicTransport(http)`. Each transport file's `_send` body becomes ONE module-level function that the signed and the public class both call; `BinanceTransport.get_public` delegates. **Acceptance:** every existing test under `tests/shared/infrastructure/bybit` and `.../binance` passes UNMODIFIED. These two extractions are the only edits to code the worker runs.
- [ ] 9va.3 RED `backend/tests/shared/infrastructure/bybit/test_read_client.py::test_settles_in_compares_the_settle_coin_case_insensitively`; `backend/tests/shared/infrastructure/binance/test_futures_rules.py::test_settles_in_compares_the_margin_asset_not_the_quote_asset` (a contract quoted in USDT and margined in USDC is not USDT-settled). GREEN in the same task: `PerpContract.settles_in(currency)` on both read models; Bybit's `_parse_contract` becomes public `parse_contract` (the private name stays as an alias so no caller changes); `is_usdt_settled` becomes `settles_in("USDT")`.
- [ ] 9va.4 RED `backend/tests/shared/infrastructure/bybit/test_public_catalogue.py` (venue spelling only; reuses `BTC_PERP`, `BTC_DATED` from `test_read_client.py`): `::test_tradable_perpetuals_keeps_trading_perpetuals_settled_in_the_asked_currency_only` (a perpetual, a dated future, a USDC-settled perpetual, a perpetual that is not trading), `::test_a_dated_future_is_excluded_by_its_contract_type_not_by_its_symbol` (a `LinearFutures` entry with a plain symbol is excluded; the filter never inspects the symbol text), `::test_the_cursor_is_followed_until_empty_and_every_page_is_read`, `::test_an_absent_cursor_key_ends_the_read_like_an_empty_one`, `::test_the_page_cap_raises_instead_of_returning_a_partial_list`, `::test_one_malformed_entry_is_skipped_and_named_in_exactly_one_warning`, `::test_a_nonempty_listing_with_no_available_pair_raises_and_logs_one_error_naming_the_types_seen`, `::test_a_real_read_logs_one_info_with_counts_and_pages`, `::test_every_request_goes_to_the_instruments_path_with_category_linear_and_no_auth`. RED against a stub that returns the first page's symbols unfiltered.
- [ ] 9va.5 RED `backend/tests/shared/infrastructure/binance/test_public_catalogue.py` (reuses `AAVE`, `TRADIFI`, `QUARTERLY` from `test_futures_rules.py`): `::test_tradable_perpetuals_excludes_tradifi_quarterly_and_usdc_margined`, `::test_a_perpetual_that_is_not_trading_is_excluded`, `::test_one_malformed_entry_is_skipped_and_named_in_exactly_one_warning`, `::test_a_nonempty_listing_with_no_available_pair_raises_and_logs_one_error`, `::test_http_451_raises_and_is_never_an_empty_listing`, `::test_a_real_read_logs_one_info_with_counts`. RED against a stub that returns every symbol.
- [ ] 9va.6 GREEN: `BybitPublicCatalogue.tradable_perpetuals(settlement_currency)` (cursor loop, page cap 10, per-entry guard around `parse_contract`, the filter `is_perpetual and is_trading and settles_in(currency)`) and `BinancePublicCatalogue.tradable_perpetuals(settlement_currency)` (same guard and filter over `parse_contract`). The filter's literal strings are the ones P7.2 recorded; if P7 contradicts `LinearPerpetual` / `Trading` / `PERPETUAL` / `TRADING`, stop and record it before writing the filter. Both raise their venue's own `*ApiError`; neither imports anything from `strategies`.

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

- [ ] 9vb.1 RED `backend/tests/strategies/domain/test_pair_catalog.py::test_unknown_pairs_is_the_sorted_difference_of_candidates_and_available`, `::test_unknown_pairs_error_carries_the_symbols_as_a_sorted_tuple`, `::test_the_four_errors_are_distinct_domain_errors`, `::test_domain_module_imports_no_framework`. GREEN in the same task: `UnknownPairs`, `PairCatalogUnavailable`, `PairCatalogNotServed`, `PairsChangedConcurrently`, `unknown_pairs()`.
- [ ] 9vb.2 RED `backend/tests/strategies/infrastructure/test_venue_pair_catalog.py::test_venue_symbols_are_returned_in_market_key_form` (the fake source lists `STXUSDT_PERP`; the result equals `{market_key("STXUSDT.P")}`), `::test_a_pool_with_no_source_raises_not_served_and_never_an_empty_set` (`pionex/spot/USDT`), `::test_a_venue_error_becomes_pair_catalog_unavailable_with_one_warning_and_no_url`, `::test_a_second_call_within_the_ttl_makes_no_venue_read`, `::test_an_expired_entry_is_refetched`, `::test_an_expired_entry_is_never_served_when_the_refresh_fails`, `::test_a_failure_is_not_cached`, `::test_concurrent_misses_make_one_venue_read` (the source parks on an `asyncio.Event`; two tasks; the read count is 1 and both get the same set), `::test_each_pool_key_has_its_own_entry_and_its_own_settlement_currency_reaches_the_source`. Time is an injected monotonic callable. RED against a stub that asks the source on every call and returns its symbols unmapped.
- [ ] 9vb.3 GREEN: `PairCatalogPort` in `ports.py`; `VenuePairCatalog` (registry keyed `(exchange, venue)` with `bybit/usdt-m` and `binance/usdt-m`, per-key `asyncio.Lock`, TTL from `Settings.pair_catalogue_ttl_seconds = 300.0`, `for_settings`).
- [ ] 9vb.4 RED `backend/tests/strategies/application/test_read_available_pairs.py::test_an_unknown_pool_raises_before_the_catalogue_is_asked`, `::test_a_disabled_pool_is_answered`, `::test_pairs_are_returned_sorted`. GREEN in the same task: `PoolCatalogPort.exists(pool)`, `SqlAlchemyPoolCatalog.exists`, `ReadAvailablePairs`.
- [ ] 9vb.5 RED `backend/tests/strategies/infrastructure/test_pair_catalog_router.py` (real PostgreSQL through the module's conftest; `dependency_overrides[get_pair_catalog]`): `::test_available_pairs_200_sorted_with_pool_and_count`, `::test_unknown_pool_404_and_the_catalogue_is_never_asked` (`bybit/usdt-m/BTC`), `::test_disabled_pool_200`, `::test_unserved_pool_404_pair_catalogue_not_served_not_an_empty_list` (`pionex/spot/USDT`), `::test_venue_unreachable_502_pair_catalogue_unavailable`, `::test_no_token_is_401_before_the_catalogue_is_asked`, `::test_one_pools_request_never_returns_another_pools_pairs`, `::test_the_real_catalogue_requests_only_the_configured_host_and_the_fixed_path` (the real `VenuePairCatalog` over `httpx.MockTransport`: the path values never reach the URL), `::test_n_concurrent_requests_make_one_venue_read`. RED against a route that returns an empty `pairs` for every pool.
- [ ] 9vb.6 RED `backend/tests/strategies/test_pair_catalog_has_no_credential.py::test_public_catalogue_modules_import_no_signer_vault_or_cipher` (source of `bybit/public_catalogue.py`, `binance/public_catalogue.py`, `strategies/infrastructure/pair_catalog.py`, `pair_catalog_router.py`). It passes at once by construction; mutation: importing `BybitSigner` into `pair_catalog.py` reds it.
- [ ] 9vb.7 GREEN: `pair_catalog_router` (prefix `/pools`, `dependencies=[Depends(require_admin_token)]`), `get_pair_catalog` reading `app.state.pair_catalog`, `get_read_available_pairs`; `create_app()` builds one `VenuePairCatalog.for_settings(settings)` and includes the router in `api_router`. Confirm the existing `/api` auth walk and `test_no_pool_management_surface.py` pass unmodified.

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

- [ ] 9vc.1 Plumbing, no behaviour change: `RegisterStrategy` and `ReplaceAllowedPairs` take `pairs: PairCatalogPort` and do not call it yet; the two routes take their use case from `get_register_strategy` / `get_replace_allowed_pairs` (the `get_save_credential` pattern) instead of building it inline; `_build` in both application test files and the router tests pass an accept-everything fake. The whole existing suite stays green. This is the stub that lets every RED below fail on an assertion.
- [ ] 9vc.2 RED `backend/tests/strategies/application/test_register_strategy.py::test_an_unlisted_symbol_refuses_the_registration_names_it_and_writes_nothing` (`YPF` beside a listed pair; no insert, no commit), `::test_a_listed_symbol_in_another_spelling_is_accepted` (the catalogue holds `STXUSDT`, the command sends `STXUSDT.P`, the stored list is `{STXUSDT}`), `::test_every_unknown_symbol_is_named_sorted`, `::test_the_catalogue_is_not_asked_for_a_duplicate_id_an_unavailable_pool_or_an_empty_list`, `::test_an_unreadable_catalogue_refuses_and_writes_nothing`, `::test_a_pool_with_no_catalogue_source_refuses_and_writes_nothing`, `::test_each_refusal_logs_one_warning_naming_the_strategy_the_pool_and_the_symbols`, `::test_the_catalogue_is_asked_for_the_commands_own_pool` (the fake records the pool key: exchange, venue AND settlement currency). RED: `DID NOT RAISE UnknownPairs` and the recorded-calls assertions.
- [ ] 9vc.3 GREEN `RegisterStrategy`: steps 4 and 5 of design addendum § E.
- [ ] 9vc.4 RED `backend/tests/strategies/application/test_replace_allowed_pairs.py::test_adding_an_unlisted_symbol_refuses_and_leaves_the_stored_list`, `::test_adding_a_listed_symbol_in_another_spelling_is_accepted` (`STXUSDT_PERP` → `STXUSDT`), `::test_a_stored_delisted_pair_can_be_kept_while_another_pair_is_added`, `::test_a_stored_delisted_pair_can_be_removed`, `::test_a_replacement_that_adds_nothing_never_asks_the_catalogue` (and succeeds with a fake that raises `PairCatalogUnavailable`), `::test_a_removed_delisted_pair_cannot_be_added_back`, `::test_an_unreadable_catalogue_refuses_when_a_pair_is_added`, `::test_unknown_strategy_and_archived_are_refused_before_the_catalogue_is_asked`, `::test_the_catalogue_is_asked_before_the_row_lock_is_taken` (one shared event log: `get_by_id`, `catalogue`, `get_by_id_for_update`, `update`, `commit`), `::test_a_strategy_archived_between_the_unlocked_read_and_the_lock_is_still_refused`, `::test_a_stored_list_that_changed_so_an_unvalidated_pair_becomes_an_addition_is_refused_and_nothing_is_written`, `::test_a_candidate_that_is_no_longer_an_addition_is_harmless`, `::test_each_refusal_logs_one_warning`. RED: `DID NOT RAISE`, and `['get_by_id_for_update', ...] == ['get_by_id', 'catalogue', 'get_by_id_for_update', ...]`.
- [ ] 9vc.5 GREEN `ReplaceAllowedPairs`: the sequence of design addendum § E (unlocked read, candidates, catalogue only when candidates exist, row lock, re-check, `PairsChangedConcurrently`).
- [ ] 9vc.6 RED `backend/tests/strategies/infrastructure/test_replace_allowed_pairs_catalogue_integration.py` — **live PostgreSQL**, lock-hold harness, no `sleep(0)` barrier, the real repository and a fake catalogue that parks on an `asyncio.Event`:
  - `::test_the_strategy_row_is_lockable_by_another_transaction_while_the_catalogue_read_is_in_flight` — while the replace is parked inside `available_pairs`, a second connection runs `SELECT ... FOR UPDATE NOWAIT` on the row and succeeds. Mutation: moving the catalogue call after `get_by_id_for_update` makes it raise `LockNotAvailableError`.
  - `::test_replace_waits_for_a_held_row_lock_after_its_catalogue_read` — a holder keeps the row locked in an open transaction; the replace is released past its catalogue call; assert `not task.done()` AND poll `pg_locks` until the replace shows as waiting on that row; the holder commits a changed `enabled`; the replace completes and its write does not revert `enabled`.
  - `::test_a_concurrent_removal_of_a_requested_pair_refuses_with_pairs_changed` — stored `{ETHUSDT, SFPUSDT}`, request `{ETHUSDT, SFPUSDT, STXUSDT_PERP}`; while parked, another transaction stores `{ETHUSDT}` and commits; the replace raises `PairsChangedConcurrently` and the row is `{ETHUSDT}`.
  - `tests/strategies/infrastructure/test_update_strategy_concurrency.py::test_replace_allowed_pairs_and_update_strategy_serialize_on_the_same_row_lock` keeps passing with only its constructor call updated.
- [ ] 9vc.7 RED `backend/tests/strategies/infrastructure/test_router.py::test_post_unknown_pairs_422_structured_and_names_the_symbols` (`detail == {"error": "UNKNOWN_PAIRS", "message": ..., "unknown": ["YPF"]}`, no row), `::test_put_unknown_pairs_422_names_only_the_added_symbols`, `::test_put_keeping_a_delisted_stored_pair_200`, `::test_post_unreadable_catalogue_502_pair_catalogue_unavailable_and_no_row`, `::test_post_unserved_pool_422_pair_catalogue_not_served`, `::test_put_pairs_changed_409`, `::test_existing_refusals_keep_their_status_and_shape` (404, 409 `STRATEGY_ARCHIVED`, 409 duplicate, 422 empty list, 422 unavailable pool), `::test_a_listed_pair_sent_as_tradingview_spells_it_is_stored_as_the_market_key` (`STXUSDT.P` in, `STXUSDT` out). RED: `assert 201 == 422`, `assert 200 == 502`.
- [ ] 9vc.8 GREEN: the HTTP mapping of design addendum § E in `router.py`; the two dependency factories read `get_pair_catalog`.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`.
Harness: real PostgreSQL, lock-hold harness on the strategy ROW lock (`rules.tasks`: no fake for a lock). Neither use case takes the pool advisory lock, so the lock-order rule is untouched; the test proves no venue call runs under the one lock there is.
Rollback boundary: two use cases, their router mapping and two dependency factories; revert restores normalize-only saves. Pairs stored while the refusals were live stay valid.
Forecast: 500–750 lines.

### Unit 9vd — `ApiError` structured detail, `useAvailablePairs`, `PairSelector` (450–650 lines) — PR 12v-4

**Files**: Modify `frontend/src/shared/api/{client.ts,client.test.ts,types.ts}`; Create
`frontend/src/shared/api/{pairs.ts,pairs.test.ts}`,
`frontend/src/features/strategies/{PairSelector.tsx,PairSelector.test.tsx}`; Modify
`frontend/src/shared/i18n/locales/{en,es}.json`.

- [ ] 9vd.1 RED `frontend/src/shared/api/client.test.ts::reads the error code and the fields from a structured detail`, `::uses the structured detail's message and never renders [object Object]`, `::keeps a string detail and an outcome exactly as before`. GREEN in the same task: `ApiError.code` and `ApiError.fields`.
- [ ] 9vd.2 RED `frontend/src/shared/api/pairs.test.ts::requests /api/pools/{exchange}/{venue}/{ccy}/available-pairs for the chosen pool`, `::rejects a body whose pairs is not an array of strings`, `::does not fetch until a pool is chosen`, `::uses a query key that is not under ['pools']`. GREEN in the same task: `fetchAvailablePairs`, `useAvailablePairs` (`['available-pairs', exchange, venue, ccy]`, `staleTime` 5 minutes, `retry: 1`).
- [ ] 9vd.3 RED `frontend/src/features/strategies/PairSelector.test.tsx::idle shows choose-a-pool and a disabled search field`, `::loading shows a status line and no option`, `::error shows an alert and a retry control that calls onRetry`, `::typing another spelling finds the pair` (types `stxusdt.p`, the option is `STXUSDT`), `::toggling an option with the keyboard calls onChange with the pair`, `::every selected pair has a remove control labelled with its symbol`, `::more than fifty matches renders fifty and says how many match`, `::no match says so`, `::a selected pair missing from the options is kept and marked no longer listed`, `::selected pairs stay removable in the error state`, `::the search field, every option and every remove control have an accessible name`, `::every key exists in en and es`. RED against a component that renders an empty fieldset.
- [ ] 9vd.4 GREEN: `PairSelector` per design addendum § G: a `<fieldset>`, a labelled `<input type="search">`, native checkboxes in labels, chips with remove buttons, a polite live count. No new dependency. Palette tokens only; the "no longer listed" mark is `ink-3`, never `decision`.

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")`; the selector is tested as a controlled component with props.
Rollback boundary: three new files and two added `ApiError` fields; nothing mounts the selector.
Forecast: 450–650 lines.

### Unit 9ve — the selector in `NewStrategyDialog` (400–600 lines) — PR 12v-5

**Files**: Modify `frontend/src/features/strategies/{NewStrategyDialog.tsx,NewStrategyDialog.test.tsx,StrategiesPage.test.tsx}`,
`frontend/src/test/harness.tsx`, `frontend/src/shared/i18n/locales/{en,es}.json`.

- [ ] 9ve.1 Harness correction, no behaviour change: the default pool is `pool("bybit", "usdt-m")` (the venue `linear` does not exist, `accounts/domain/known_pools.py`); `stubApi` answers `/pools/{exchange}/{venue}/{ccy}/available-pairs`; every test that spells `linear/USDT` moves to `usdt-m/USDT`. The suite stays green.
- [ ] 9ve.2 RED `frontend/src/features/strategies/NewStrategyDialog.test.tsx::test_pairs_are_chosen_from_the_pools_available_pairs_and_no_free_text_field_exists`, `::test_selected_pairs_are_submitted_in_market_key_form` (types `stxusdt.p`, the POST body carries `["STXUSDT"]`), `::test_changing_the_pool_clears_the_selection_and_reads_the_new_pools_pairs`, `::test_submit_is_disabled_until_the_available_pairs_are_loaded`, `::test_a_load_failure_shows_retry_and_never_a_free_text_field`, `::test_unknown_pairs_refusal_names_the_symbols`, `::test_a_502_shows_the_pair_list_could_not_be_read_text_even_without_a_body`, `::test_pair_catalogue_not_served_shows_its_own_text`, `::test_new_texts_render_in_es`. The two existing tests, `::test_id_generated_via_crypto_randomuuid` and `::test_submitting_with_zero_pairs_is_prevented`, keep their names and are driven through the selector.
- [ ] 9ve.3 GREEN: `NewStrategyDialog` mounts `PairSelector` over `useAvailablePairs(pool)`; `parsePairs`, the textarea and `strategies.new.pairsHint` are removed; `errorKey` reads `error.code` first and the status second (design addendum § G table).

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: one dialog and the harness default; revert restores the textarea, and the server (12v-3) still refuses an unlisted pair.
Forecast: 400–600 lines.

### Unit 9vf — follow-ups to unit 9v (not started)

- [ ] 9vf.1 The ORDER path reads one page of Bybit's catalogue: `bybit/trade_client.py:130` calls `BybitReadOnlyClient.perp_contracts()` (`limit=1000`, no cursor). Past 1,000 `linear` entries, a market on the second page is refused at order time as not listed (P7.2 records today's count). Reuse 9va's cursor loop in the signed client. Its own small PR, because it touches the order path; priority is design addendum § L, Q3. RED first: a two-page listing whose second page holds the ordered symbol.
- [x] 9vf.2 `tasks.md` "Production now" still names the Bybit pool `bybit/linear/USDT`; the row is `bybit/usdt-m/USDT` (task 6d.1). Correct the label on the next delivery-log update. Done with the PR 12a-2 entry (2026-10-02).

### Unit 9x — delete a strategy that has no history (decision 42, not started)

- [ ] 9x.1 Design first: list every table that references a strategy (signals, reservations, execution attempts, ledger entries, enablement events and any other), define the no-history check and its lock, and revise the spec requirement "Archive Is Terminal — Never Deleted, Never Reversed". No code before this.
- [ ] 9x.2 Backend: `DELETE /api/strategies/{id}`, allowed only for a disabled strategy with no history; any history refuses with the reasons, and archive stays the only path. RED first: a strategy with one signal is refused, and a strategy with none is deleted.
- [ ] 9x.3 Frontend: the delete control on the strategy detail page (unit 9d), behind an explicit confirmation, showing the refusal reasons. Depends on 9x.2.

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
