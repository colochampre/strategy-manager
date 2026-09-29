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
| 6a+6b+6c | Key policy, inspectors, 0027, `SaveCredential`, `TradeCapabilityPort` | PR 8a | `cd backend && uv run pytest --tb=short backend/tests/accounts/` | `httpx.MockTransport` for inspectors, real vault for the migration, gated by PR 1's P1–P3 | Migration 0027 (refuses downgrade while any `trade_capable=false` row exists) + new use case; revert leaves scripts working unchanged |
| 6d+6e | Pool auto-enable, `DeleteCredential`, exposure adapter | PR 8b | `cd backend && uv run pytest --tb=short backend/tests/accounts/application/test_delete_credential_integration.py` | Real PostgreSQL, concurrent delete-vs-allocate test (advisory lock) | `CapitalPoolWriterPort` + `DeleteCredential`; revert removes both, keys already stored remain valid |
| 4b | SPA serving, fallback, CSP, invariant 5 | PR 9 | `cd backend && uv run pytest --tb=short backend/tests/shared/infrastructure/test_spa.py` | `httpx.AsyncClient` over ASGI with a temp `dist` directory | `shared/infrastructure/spa.py` + `mount_panel()` call; revert removes the mount, `/api` untouched |
| 7-shell | Router, shell, exchange scope, bookings re-homed, theme swap | PR 10 | `cd frontend && npm test -- router AppShell exchange-store` | N/A — frontend-only, `vi.stubGlobal("fetch")` | New `app/router.tsx`, `shared/layout/*`; revert restores the hash-based nav |
| 8-overview | Overview: ledger line, chart, grid, decision rail | PR 11 | `cd frontend && npm test -- OverviewPage ReturnChart MonthlyGrid` | N/A — frontend-only, pure geometry unit tests | New `features/overview/*`; revert removes the route content, shell untouched |
| 9-strategies | Strategies list + detail + dialogs + webhook message | PR 12 | `cd frontend && npm test -- StrategiesPage StrategyDetailPage WebhookMessage` | N/A — frontend-only | New `features/strategies/*`; revert removes the route content |
| 10-settings | Settings: key card, form, delete flow | PR 13 | `cd frontend && npm test -- SettingsPage ExchangeKeyCard DeleteKeyDialog` | N/A — frontend-only | New `features/settings/*`; revert removes the route content |

## Delivery log

Updated after every merge and deploy. With this and `git log`, the state can be resumed from
any machine.

**Production now** (2026-09-29, VPS time): `main` at `a969e40`, alembic `0026`, `DRY_RUN=true`, the
frontend is not served. Enabled pools: `bybit/linear/USDT` and `binance/usdt-m/USDT`. The vault
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
| PR 6e | — | — | — | — | Decision 29, on `feat/operator-panel-startup-exit-code`. In review. No migration: pull, restart both, then the owner adds the `RestartPreventExitStatus=78` drop-in to the worker unit and reloads systemd. |

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

---

## PR 7 — Read endpoints: pools, performance, `GET /webhook-secret` (950–1,350 lines)

**Files**: Create `backend/src/strategy_manager/accounts/infrastructure/{pools_router,pool_overview}.py`;
Create `backend/src/strategy_manager/performance/infrastructure/performance_router.py`; Create
`backend/src/strategy_manager/signals/infrastructure/webhook_secret_router.py`.

- [ ] 7.1 RED `backend/tests/accounts/infrastructure/test_pools_router.py::test_get_pools_requires_bearer_token`, `::test_get_pools_computes_allocatable_as_max_zero_available_minus_reserved_server_side`, `::test_get_pools_never_sums_two_pools_on_same_exchange` (rule 7).
- [ ] 7.2 RED `backend/tests/performance/infrastructure/test_performance_router.py::test_get_pool_performance_requires_bearer_token`, `::test_get_pool_performance_404_unknown_pool`, `::test_get_strategy_performance_includes_by_pair`, `::test_get_strategy_trades_keyset_pagination_422_half_a_cursor`, `::test_empty_ledger_returns_zeros_and_empty_arrays_never_an_error`.
- [ ] 7.3 RED `backend/tests/signals/infrastructure/test_webhook_secret_router.py::test_get_webhook_secret_requires_bearer_token`, `::test_get_webhook_secret_returns_cache_control_no_store`, `::test_no_other_api_response_body_contains_the_configured_secret_value` (parametrized over every other `/api` route's response), `::test_access_log_never_records_the_secret_value`.
- [ ] 7.4 GREEN: `SqlAlchemyPoolOverview`, `pools_router` (`GET /pools`); `performance_router` (`GET /performance/pools/{exchange}/{venue}/{ccy}`, `GET /performance/strategies/{id}`, `GET /performance/strategies/{id}/trades`); `webhook_secret_router` (`GET /webhook-secret`, reads `settings.webhook_secret` directly, `Cache-Control: no-store`).

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/accounts/infrastructure/ backend/tests/performance/infrastructure/ backend/tests/signals/infrastructure/test_webhook_secret_router.py`.
Harness: `httpx.AsyncClient` over the ASGI app.
Rollback boundary: three new routers, each self-contained; revert 404s their paths, nothing else depends on them until PR 11/12.
Forecast: 950–1,350 lines.

---

## PR 8a — Units 6a + 6b + 6c: key policy, inspectors, 0027, `SaveCredential`, trade-capability refusal (1,900–2,600 lines)

**Gate before rules are written**: PR 1's **P1–P3** recorded. No line of `key_policy.py` is
written before "PR 1 — Probe results" carries P1–P3.

### Unit 6a — key policy + inspectors + migration 0027 (800–1,100 lines)

**Files**: Create `backend/src/strategy_manager/accounts/domain/key_policy.py`; Create
`backend/src/strategy_manager/accounts/infrastructure/key_inspectors/{bybit,binance,registry}.py`;
Modify `backend/src/strategy_manager/accounts/domain/exchange_credential.py`; Create
`backend/migrations/versions/0027_credential_snapshot.py`.

- [ ] 6a.1 RED `backend/tests/accounts/domain/test_key_policy.py::test_evaluate_key_refuses_withdraw_permission_bybit_wallet_withdraw` (using the P1-recorded fixture), `::test_evaluate_key_allows_internal_transfer_only_accounttransfer`, `::test_evaluate_key_refuses_withdraw_binance_enable_withdrawals`, `::test_evaluate_key_allows_internal_transfer_binance`.
- [ ] 6a.2 RED same file `::test_evaluate_key_derives_trade_capable_true_bybit_readonly_zero_and_permission_present` (using the P2-recorded field), `::test_evaluate_key_derives_trade_capable_false_readonly_key`, `::test_evaluate_key_derives_trade_capable_binance_enablefutures_true` (P3), `::test_evaluate_key_derives_trade_capable_false_binance_enablefutures_false`.
- [ ] 6a.3 RED `backend/tests/accounts/infrastructure/test_key_inspectors.py::test_bybit_inspector_calls_wallet_balance_and_query_api_never_an_order` (`httpx.MockTransport`, probe-recorded payload shapes), `::test_binance_inspector_calls_api_restrictions_never_an_order`, `::test_registry_dispatches_by_exchange_unserved_raises`.
- [ ] 6a.4 RED `backend/tests/migrations/test_0027_credential_snapshot.py::test_permissions_and_validated_at_check_constraint_paired`, `::test_backfill_sets_trade_capable_true_for_every_existing_row`, `::test_default_is_dropped_insert_without_trade_capable_fails`, `::test_downgrade_refuses_while_any_trade_capable_false_row_exists_naming_count`.
- [ ] 6a.5 GREEN: `PermissionSnapshot`, `KeyVerdict`, `evaluate_key(snapshot)` — pure, 8(a)/8(b) refusals and trade-capability derivation.
- [ ] 6a.6 GREEN: `trade_capable`, `validated_at`, `permissions` on `ExchangeCredential`/`CredentialHint` (`trade_capable` has no default — every constructor call names it).
- [ ] 6a.7 GREEN: `BybitKeyInspector`, `BinanceKeyInspector`, `KeyInspectorRegistry` — a GET balance read plus permission introspection, never an order.
- [ ] 6a.8 GREEN: `migrations/versions/0027_*.py` — `permissions JSONB NULL`, `validated_at timestamptz NULL`, `CHECK ((permissions IS NULL) = (validated_at IS NULL))`, `trade_capable boolean NOT NULL` added `DEFAULT true`, backfilled, default dropped; downgrade refuses while any `false` row exists.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/accounts/ backend/tests/migrations/test_0027_credential_snapshot.py`.
Harness: `httpx.MockTransport` for inspectors (no real credential, rule 1); real PostgreSQL for the migration.
Rollback boundary: migration 0027 (refuses downgrade while `trade_capable=false` rows exist) + new domain/infra files; revert leaves every existing store script working unchanged.
Forecast: 800–1,100 lines.

### Unit 6b — `SaveCredential`, credential endpoints, redacted 422, store scripts (750–1,000 lines)

**Files**: Create `backend/src/strategy_manager/accounts/application/save_credential.py`;
Modify `backend/src/strategy_manager/accounts/application/ports.py` (`CredentialWriterPort`, `KeyInspectorPort`);
Modify `backend/src/strategy_manager/accounts/infrastructure/{credential_vault,models,credentials_router}.py`;
Create `backend/src/strategy_manager/shared/infrastructure/validation_errors.py`; Modify
`backend/scripts/store_{bybit,binance,pionex}_credentials.py`.

- [ ] 6b.1 RED `backend/tests/accounts/application/test_save_credential.py::test_key_rejected_by_venue_refuses_stores_nothing_422`, `::test_venue_unreachable_reported_distinctly_502`, `::test_withdraw_permission_refuses_stores_nothing_422`, `::test_readonly_key_stored_trade_capable_false_warning_returned_200`, `::test_trading_key_stored_no_warning_returned_200`, `::test_concurrent_save_second_refused_409_by_constraint_name_not_message` (imports `ux_exchange_credentials_one_active_per_exchange` as a named constant, following the CONCURRENT_SAVE constraint-name-matching precedent), `::test_rotation_deactivates_previous_row_retains_it`.
- [ ] 6b.2 RED `backend/tests/accounts/infrastructure/test_credentials_router.py::test_put_credentials_returns_last4_trade_capable_permissions_validated_at_never_the_key_or_secret`, `::test_get_credentials_shows_snapshot_never_live_requery`.
- [ ] 6b.3 RED `backend/tests/shared/infrastructure/test_validation_errors.py::test_422_never_echoes_api_secret_input_or_ctx`.
- [ ] 6b.4 GREEN: `SaveCredential` — inspect → `evaluate_key` → store (supersede) → commit; `CredentialWriterPort` has no `load`.
- [ ] 6b.5 GREEN: `redacted_validation_handler` — one `RequestValidationError` handler for the whole app, strips `input`/`ctx`.
- [ ] 6b.6 GREEN: `PUT /api/credentials/{exchange}` on `credentials_router`; `GET /api/credentials` listing rule (one entry per exchange with an active credential, a history row, or an enabled pool).
- [ ] 6b.7 GREEN: fold `store_bybit_credentials.py`, `store_binance_credentials.py`, `store_pionex_credentials.py` onto `SaveCredential`, accepting a read-only key with a warning instead of refusing it outright.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/accounts/ backend/tests/shared/infrastructure/test_validation_errors.py`.
Harness: fakes for `SaveCredential`; `httpx.AsyncClient` for the router; real vault for rotation/supersede.
Rollback boundary: `save_credential.py` + router changes; revert leaves the store scripts' pre-fold behavior, no data loss (rotation history is retained regardless).
Forecast: 750–1,000 lines.

### Unit 6c — `TradeCapabilityPort`, adapters, read-only/no-key opening refusal (350–500 lines)

**Files**: Create `backend/src/strategy_manager/accounts/infrastructure/trade_capability_adapter.py`;
Modify `backend/src/strategy_manager/signals/application/process_signal.py`, `application/ports.py` (`TradeCapabilityPort`); Modify `backend/src/strategy_manager/main.py` (DRY_RUN-based wiring).

- [ ] 6c.1 RED `backend/tests/signals/application/test_process_signal.py::test_live_open_on_readonly_exchange_refused_before_lock_one_warning_names_exchange` (`DRY_RUN=false`, `READ_ONLY`).
- [ ] 6c.2 RED same file `::test_close_on_readonly_exchange_not_refused_by_this_rule`.
- [ ] 6c.3 RED same file `::test_dry_run_true_readonly_key_refuses_nothing`.
- [ ] 6c.4 RED same file `::test_live_open_on_keyless_no_key_exchange_refused_before_lock_one_warning_names_exchange` (decision 20's `NO_KEY` case).
- [ ] 6c.5 RED `backend/tests/accounts/infrastructure/test_trade_capability_adapter.py::test_vault_adapter_answers_trade_capable_without_decrypting` — a row with garbage ciphertext still answers (single indexed column read, never `.load(`).
- [ ] 6c.6 RED `backend/tests/accounts/test_no_decrypt_in_api_path.py::test_credentials_router_and_save_credential_never_call_dot_load` — structural test (decision 5), grep/AST-based, asserting no reference to `.load(` under `credentials_router.py` or `save_credential.py`.
- [ ] 6c.7 GREEN: `VaultTradeCapabilityAdapter` (`SELECT exchange, trade_capable WHERE is_active`, never decrypts), `DryRunTradeCapability` (always `TRADE_CAPABLE`); wired in `main.py` by `DRY_RUN` like the exchange adapters.
- [ ] 6c.8 GREEN: `ProcessSignalHandler._refuse_read_only_exchange` at the top of `_handle_consumes`, after the unlisted-pair refusal (2b) and before the Existing-Position Guard.

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

- [ ] 6d.1 RED `backend/tests/accounts/domain/test_known_pools.py::test_bybit_maps_to_usdt_m_usdt`, `::test_binance_maps_to_usdt_m_usdt`.
- [ ] 6d.2 RED `backend/tests/accounts/application/test_save_credential.py::test_first_key_saved_for_exchange_enables_its_pool_same_transaction` (Binance, no active credential, pool disabled → enabled).
- [ ] 6d.3 RED same file `::test_resaving_key_for_already_enabled_pool_leaves_min_order_size_unchanged_idempotent`.
- [ ] 6d.4 RED `backend/tests/accounts/infrastructure/test_capital_pool_writer.py::test_enable_upserts_from_known_futures_pools_constant_never_request_body`, `::test_enable_on_missing_row_inserts_with_default_min_order_size`.
- [ ] 6d.5 RED `backend/tests/accounts/test_no_pool_management_surface.py::test_no_endpoint_or_view_enables_disables_or_configures_a_pool_directly` (a route-inventory test over `app.routes`).
- [ ] 6d.6 GREEN: `KNOWN_FUTURES_POOLS` constant (`{bybit: (usdt-m, USDT, default_min_order_size), binance: (usdt-m, USDT, default_min_order_size)}`).
- [ ] 6d.7 GREEN: `CapitalPoolWriterPort.enable(exchange)`/`.disable(exchange)`; `SqlAlchemyCapitalPoolWriter`; `SaveCredential` calls `.enable(exchange)` in the same transaction as the credential write.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/accounts/`.
Harness: real PostgreSQL (transaction atomicity with the credential write).
Rollback boundary: one constant + one port/adapter + one call site in `SaveCredential`; revert stops auto-enabling, existing enabled pools untouched.
Forecast: 300–450 lines.

### Unit 6e — `DeleteCredential`, `PoolExposurePort`, `DELETE` endpoint, concurrency test (700–1,000 lines)

**Files**: Create `backend/src/strategy_manager/accounts/application/delete_credential.py`;
Modify `backend/src/strategy_manager/accounts/application/ports.py` (`PoolExposurePort`); Create
`backend/src/strategy_manager/accounts/infrastructure/pool_exposure_adapter.py`; Modify
`backend/src/strategy_manager/accounts/infrastructure/credentials_router.py`.

- [ ] 6e.1 RED `backend/tests/accounts/application/test_delete_credential_integration.py::test_deletion_refused_while_enabled_strategy_exists_names_it_409` — **live PostgreSQL**.
- [ ] 6e.2 RED same file `::test_deletion_refused_while_open_exposure_exists_names_symbols_allocations_reservations_attempts_409`.
- [ ] 6e.3 RED same file `::test_deletion_succeeds_when_flat_deactivates_credential_disables_pool_same_transaction`.
- [ ] 6e.4 RED same file `::test_concurrent_allocation_and_deletion_on_same_pool_serialized_by_advisory_lock_both_orderings` — the same lesson as 2c.8/2c.9, widened exchange-wide.
- [ ] 6e.5 RED same file `::test_replacing_a_key_rotation_never_runs_this_precondition_even_with_enabled_strategy_and_open_position`.
- [ ] 6e.6 RED `backend/tests/accounts/infrastructure/test_pool_exposure_adapter.py::test_exposure_sees_every_strategy_bound_to_pool_not_just_one` (widened from `StrategyExposurePort`'s one-strategy shape).
- [ ] 6e.7 RED `backend/tests/accounts/infrastructure/test_credentials_router.py::test_delete_credentials_404_when_no_active_row`, `::test_delete_credentials_200_status_empty_matches_never_configured_shape`.
- [ ] 6e.8 RED `backend/tests/signals/application/test_process_signal.py::test_no_key_refused_live_immediately_after_delete_credential_commits_no_lock_no_cache` (the "key deleted just before this check" spec scenario).
- [ ] 6e.9 GREEN: `PoolExposurePort.exposure(pool)`, `PoolExposureAdapter` (reuses `ReadSymbolHoldings`, reservations, attempts like `StrategyExposureAdapter`, without a strategy filter).
- [ ] 6e.10 GREEN: `DeleteCredential` — `SELECT ... FOR UPDATE`, 404 if no active row, `pg_advisory_xact_lock(LockKey(pool))` (same key `ArchiveStrategy`/`AllocateCapital` take), exposure check, 409 `EXCHANGE_NOT_FLAT`, else deactivate + `CapitalPoolWriterPort.disable(exchange)`, commit.
- [ ] 6e.11 GREEN: `DELETE /api/credentials/{exchange}` on `credentials_router`.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/accounts/`.
Harness: real PostgreSQL, live concurrency test (advisory lock, both orderings — no meaningful fake per `rules.tasks`).
Rollback boundary: `delete_credential.py`, `pool_exposure_adapter.py`, one router method; revert removes the endpoint, keys already stored remain valid vault rows.
Forecast: 700–1,000 lines.

**PR 8a+8b deploy runbook** (owner-run): `alembic upgrade head` then restart both processes. The
old code never inserts a credential row (only the store scripts do), so no ordering hazard exists;
run the store scripts only from the new code, because 0027 makes `trade_capable` mandatory.
Re-saving each already-active key through Settings is optional (unvalidated rows remain
trade-capable by construction); doing so for Bybit/Binance also runs `CapitalPoolWriterPort.enable`,
a no-op on their already-enabled pool rows (migrations 0017/0018).

---

## PR 9 — Unit 4b: SPA serving, fallback, CSP, invariant 5 (500–750 lines)

**Files**: Create `backend/src/strategy_manager/shared/infrastructure/spa.py`; Modify
`backend/src/strategy_manager/shared/config.py` (`panel_dist_dir`); Modify `main.py`
(`mount_panel()` call, startup invariant 5).

- [ ] 4b.1 RED `backend/tests/shared/infrastructure/test_spa.py::test_get_api_unknown_returns_404_json_never_index_html`, `::test_get_api_bare_returns_404_json`, `::test_get_webhook_tradingview_via_get_returns_404_not_index_html` (the load-bearing method-mismatch case — Starlette's partial-match fallthrough).
- [ ] 4b.2 RED same file `::test_deep_client_route_strategies_uuid_resolves_to_index_html`, `::test_settings_route_resolves_to_index_html_on_refresh`.
- [ ] 4b.3 RED same file `::test_path_traversal_encoded_dot_dot_never_escapes_dist`, `::test_absolute_path_probe_never_escapes_dist`.
- [ ] 4b.4 RED same file `::test_hashed_asset_served_with_immutable_cache_control`, `::test_index_html_served_with_no_cache_and_security_headers` (CSP string asserted verbatim, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`).
- [ ] 4b.5 RED `backend/tests/shared/test_startup_invariants.py::test_missing_master_encryption_key_refuses_to_start_invariant_5`, `::test_panel_dist_dir_set_but_index_html_missing_refuses_to_start`.
- [ ] 4b.6 GREEN: `mount_panel(app, dist)` — `app.mount("/assets", ...)`; `@app.get("/{path:path}")` registered LAST, reserved-prefix check (`api`, `api/`, `webhook/`, `health` → 404), resolved-path containment check, else `index.html` with security headers.
- [ ] 4b.7 GREEN: `Settings.panel_dist_dir: str = ""` (empty = unmounted, dev/tests); startup invariant 5 (`EnvelopeCipher.from_base64` must succeed) and the `panel_dist_dir` set-but-missing-`index.html` refusal.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/shared/infrastructure/test_spa.py backend/tests/shared/test_startup_invariants.py`.
Harness: `httpx.AsyncClient` over the ASGI app with a temp `dist` directory (built fixture, not a real Vite build).
Rollback boundary: `spa.py` + one `mount_panel()` call, gated by `panel_dist_dir` being unset in dev/test; revert removes the mount, `/api` is completely untouched.
Forecast: 500–750 lines.

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

- [ ] 7r.1 RED (Vitest) `frontend/src/app/router.test.tsx::test_route_map_renders_overview_strategies_strategy_detail_settings_in_memory_router`, `::test_unknown_path_renders_not_found_client_side`.
- [ ] 7r.2 RED `frontend/src/shared/layout/AppShell.test.tsx::test_widescreen_shows_sidenav_narrow_shows_bottomnav`, `::test_dry_run_badge_reads_health_dry_run_field`.
- [ ] 7r.3 GREEN: pin `react-router` at install, confirm its React 19 peer range; `router.tsx` route map (`/`, `/strategies`, `/strategies/:strategyId`, `/settings`, `*`); `AppShell` layout; `DryRunBadge` wired to `GET /health`.

Gate: `cd frontend && npm run lint && npm test`.
Harness: `MemoryRouter` for Vitest; N/A backend.
Rollback boundary: new `app/router.tsx` + `shared/layout/*`; revert restores the hash-based `App.tsx:17-34` nav.
Forecast: 600–850 lines.

### Unit 7s-scope — exchange scope, bookings re-homed (350–500 lines)

**Files**: Create `frontend/src/shared/scope/exchange-store.ts`; Modify `frontend/src/features/bookings/*`.

- [ ] 7s.1 RED `frontend/src/shared/scope/exchange-store.test.ts::test_options_are_distinct_exchanges_from_pools_default_is_first`, `::test_persisted_through_safe_storage_key_sm_exchange`, `::test_settings_route_reads_no_exchange_scope`.
- [ ] 7s.2 RED `frontend/src/features/bookings/BookingsListView.test.tsx::test_filtered_by_selected_exchange`.
- [ ] 7s.3 GREEN: Zustand store `shared/scope/exchange-store.ts` over `safe-storage`; `BookingsListView` re-homed inside the shell, filtered by scope (client-side, decision 3).

Gate: `cd frontend && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: new store file + a filter prop on the existing bookings view; revert removes filtering, bookings view still renders unfiltered.
Forecast: 350–500 lines.

### Unit 7t-theme — direction-A `@theme` swap, self-hosted fonts (200–250 lines)

**Files**: Modify `frontend/src/index.css`; Modify `frontend/src/main.tsx`; Modify
`frontend/package.json` (+ `@fontsource/archivo`, `@fontsource/ibm-plex-sans`,
`@fontsource/ibm-plex-mono`; − `recharts`).

- [ ] 7t.1 RED `frontend/src/shared/theme.test.ts::test_no_hex_colour_or_var_inside_classname_across_renamed_components` (grep-based Tailwind rule test).
- [ ] 7t.2 RED `frontend/src/App.test.tsx::test_bookings_and_tokengate_use_renamed_tokens_not_removed_ones` (old `surface-*`/`edge`/`ink-100/300/500`/`accent`/`profit`/`loss`/`idle` tokens removed, renamed classes render).
- [ ] 7t.3 GREEN: replace `@theme` in `index.css` with the direction-A palette (verbatim from design.md § Visual design); rename every existing class in bookings, `TokenGate`, `App`; import the three `@fontsource` packages in `main.tsx`; remove `recharts` from `package.json`.

Gate: `cd frontend && npm run lint && npm test`.
Harness: N/A — CSS/token change, asserted by grep-style Vitest tests.
Rollback boundary: `index.css` + `main.tsx` + class renames; revert restores the old palette, no logic changes.
Forecast: 200–250 lines.

---

## PR 11 — Overview: ledger line, return chart, monthly grid, decision rail (1,300–1,800 lines)

### Unit 8c-geometry — pure chart geometry (300–400 lines)

**Files**: Create `frontend/src/shared/charts/scale.ts`.

- [ ] 8c.1 RED `frontend/src/shared/charts/scale.test.ts::test_waterline_scale_upper_band_takes_62_percent_lower_38_percent`, `::test_waterline_scale_each_band_floors_at_10_percent`, `::test_waterline_scale_negative_cumulative_return_crosses_into_lower_band`, `::test_line_path_no_smoothing_one_point_per_utc_day`, `::test_drawdown_path_closed_from_waterline_to_dd`, `::test_month_ticks_first_utc_day_of_each_month`, `::test_grid_band_zero_boundary_2_5_percent_boundary_15_percent_and_beyond`.
- [ ] 8c.2 GREEN: `waterlineScale(up, down, height, waterRatio)`, `linePath(points)`, `drawdownPath(points, waterY)`, `monthTicks(dates)`, `gridBand(value)` — pure functions.

Gate: `cd frontend && npm test`.
Harness: pure, no DOM.
Rollback boundary: one new file with no consumer yet; revert is trivial.
Forecast: 300–400 lines.

### Unit 8r-chart — `ReturnChart` component (400–550 lines)

**Files**: Create `frontend/src/features/overview/ReturnChart.tsx`.

- [ ] 8r.1 RED `frontend/src/features/overview/ReturnChart.test.tsx::test_renders_polyline_and_drawdown_path_from_curve_prop`, `::test_empty_state_no_closed_trades_yet_when_curve_is_empty`, `::test_chart_always_shows_all_range_selector_does_not_rebase_axis`, `::test_role_img_aria_label_from_i18n`.
- [ ] 8r.2 GREEN: `ReturnChart` — one inline `<svg>`, `role="img"`, waterline at 0%, polyline via `linePath`, drawdown fill via `drawdownPath`, gridlines and tick labels, colours via utility classes only (`stroke-gain`, `fill-loss/20`, `stroke-rule-strong`).

Gate: `cd frontend && npm test`.
Harness: jsdom (no `ResponsiveContainer` measurement issue — this is exactly why recharts was rejected).
Rollback boundary: one component; revert removes it, Overview shows nothing where it was mounted.
Forecast: 400–550 lines.

### Unit 8g-grid — `MonthlyGrid`, `LedgerLine`, `RangeSelector` (350–500 lines)

**Files**: Create `frontend/src/features/overview/{MonthlyGrid,MonthlySummary,LedgerLine,RangeSelector,PoolEyebrow}.tsx`.

- [ ] 8g.1 RED `frontend/src/features/overview/MonthlyGrid.test.tsx::test_band_maps_to_gain_or_loss_utility_class_by_sign_and_magnitude`, `::test_month_with_no_closed_trade_renders_dashed_empty_cell`, `::test_bands_4_to_6_use_text_ground_for_contrast`.
- [ ] 8g.2 RED `frontend/src/features/overview/LedgerLine.test.tsx::test_lead_figure_is_available_balance_pnl_and_return_by_sign_null_return_renders_em_dash`.
- [ ] 8g.3 RED `frontend/src/features/overview/RangeSelector.test.tsx::test_default_range_is_30d_pressed_state_aria_pressed_44px_minimum_touch_target`.
- [ ] 8g.4 GREEN: the four presentational components, money parsed only for `Intl.NumberFormat` display (never computed client-side).

Gate: `cd frontend && npm test`.
Harness: jsdom.
Rollback boundary: presentational components with no server dependency beyond typed props; revert removes them.
Forecast: 350–500 lines.

### Unit 8o-overview — `OverviewPage`, `PoolPanel`, `DecisionRail` (300–450 lines)

**Files**: Create `frontend/src/features/overview/{OverviewPage,PoolPanel,DecisionRail,BookingCard}.tsx`; Modify query hooks for `['pools']`, `['performance','pool',...]`.

- [ ] 8o.1 RED `frontend/src/features/overview/OverviewPage.test.tsx::test_renders_one_poolpanel_per_pool_never_merged_rule_7`, `::test_empty_ledger_dry_run_shows_defined_empty_states_no_error`.
- [ ] 8o.2 RED `frontend/src/features/overview/DecisionRail.test.tsx::test_pending_bookings_wide_viewport_right_rail`, `::test_pending_bookings_narrow_viewport_inflow_block_between_chart_and_grid` (Mobile.dc.html ordering), `::test_no_pending_bookings_shows_nothing_needs_your_decision_no_amber_count`.
- [ ] 8o.3 GREEN: `OverviewPage` container wiring `['pools']`, `['performance','pool',ex,venue,ccy]`, `['bookings','pending']`; `PoolPanel` composing `PoolEyebrow`+`LedgerLine`+`RangeSelector`+`ReturnChart`+`MonthlyGrid`+`MonthlySummary`; `DecisionRail` reusing `ConfirmBookingDialog`/`RejectBookingDialog`.

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: the page container; revert leaves the route empty, the shell (PR 10) untouched.
Forecast: 300–450 lines.

---

## PR 12 — Strategies list + detail + dialogs + webhook message + Show secret (1,400–1,900 lines)

### Unit 9l-list — `StrategiesPage`, list, new-strategy dialog (400–550 lines)

**Files**: Create `frontend/src/features/strategies/{StrategiesPage,StrategyRow,ArchivedToggle,NewStrategyDialog}.tsx`.

- [ ] 9l.1 RED `frontend/src/features/strategies/StrategiesPage.test.tsx::test_archived_excluded_by_default_toggle_shows_them`, `::test_row_shows_name_pool_enabled_toggle_uptime_trades_pnl_return`.
- [ ] 9l.2 RED `frontend/src/features/strategies/NewStrategyDialog.test.tsx::test_id_generated_via_crypto_randomuuid`, `::test_submitting_with_zero_pairs_is_prevented`.
- [ ] 9l.3 GREEN: list container + row + dialog, `['strategies',{includeArchived}]` query.

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

---

## PR 13 — Settings: exchange key cards, form, delete flow (900–1,300 lines)

### Unit 10c-card — `ExchangeKeyCard`, read-only and no-key marks (350–500 lines)

**Files**: Create `frontend/src/features/settings/{SettingsPage,ExchangeKeyCard}.tsx`.

- [ ] 10c.1 RED `frontend/src/features/settings/SettingsPage.test.tsx::test_no_exchange_tabs_lists_every_exchange` (Settings.dc.html).
- [ ] 10c.2 RED `frontend/src/features/settings/ExchangeKeyCard.test.tsx::test_no_key_ever_stored_shows_neutral_empty_state_no_amber_border`, `::test_readonly_key_shows_amber_border_and_cannot_trade_sentence`, `::test_degraded_no_key_but_enabled_pool_shows_amber_border_and_no_key_stored_sentence` (decision 20 — distinguishing amber "no key" from neutral "no key" by whether the pool is enabled), `::test_active_key_shows_last4_reads_and_trades_or_reads_only_no_withdrawal_checked_date`, `::test_key_sealed_before_0027_shows_not_validated`.
- [ ] 10c.3 GREEN: `SettingsPage` (`['credentials']` query, no exchange scope per 7s.1); `ExchangeKeyCard` per design's three-state rendering (neutral / read-only amber / DEGRADED amber).

Gate: `cd frontend && npm run lint && npm test`.
Harness: `vi.stubGlobal("fetch")`.
Rollback boundary: two components; revert removes Settings' card rendering, the route stays reachable but empty.
Forecast: 350–500 lines.

### Unit 10f-form — `KeyEntryForm` (300–450 lines)

**Files**: Create `frontend/src/features/settings/KeyEntryForm.tsx`.

- [ ] 10f.1 RED `frontend/src/features/settings/KeyEntryForm.test.tsx::test_fields_cleared_in_finally_regardless_of_outcome`, `::test_submitted_via_plain_async_handler_not_use_mutation_secret_never_in_mutation_cache`, `::test_password_type_autocomplete_off_on_secret_field`, `::test_readonly_key_warning_shown_on_200_with_read_only_key_warning`, `::test_422_502_409_outcome_reason_shown_i18n`.
- [ ] 10f.2 GREEN: `KeyEntryForm` — local component state, plain `apiFetch` call, no `useMutation`.

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
