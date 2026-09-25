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
| 3a+3b+3c+3d | Pool capital at open, PnL, curve/drawdown/grid, stats | PR 6 | `cd backend && uv run pytest --tb=short backend/tests/allocation/ backend/tests/performance/` | Real PostgreSQL for 3a; pure for 3b–3d | `reservations.pool_total_at_open` (additive) + new `performance/` module; downgrade refuses while non-null values exist |
| 5-reads | Pools/performance/webhook-secret read endpoints | PR 7 | `cd backend && uv run pytest --tb=short backend/tests/accounts/infrastructure/test_pools_router.py backend/tests/performance/infrastructure/test_performance_router.py backend/tests/signals/infrastructure/test_webhook_secret_router.py` | `httpx.AsyncClient` over ASGI | New routers only; revert 404s the paths, no view depends on them yet |
| 6a+6b+6c | Key policy, inspectors, 0026, `SaveCredential`, `TradeCapabilityPort` | PR 8a | `cd backend && uv run pytest --tb=short backend/tests/accounts/` | `httpx.MockTransport` for inspectors, real vault for the migration, gated by PR 1's P1–P3 | Migration 0026 (refuses downgrade while any `trade_capable=false` row exists) + new use case; revert leaves scripts working unchanged |
| 6d+6e | Pool auto-enable, `DeleteCredential`, exposure adapter | PR 8b | `cd backend && uv run pytest --tb=short backend/tests/accounts/application/test_delete_credential_integration.py` | Real PostgreSQL, concurrent delete-vs-allocate test (advisory lock) | `CapitalPoolWriterPort` + `DeleteCredential`; revert removes both, keys already stored remain valid |
| 4b | SPA serving, fallback, CSP, invariant 5 | PR 9 | `cd backend && uv run pytest --tb=short backend/tests/shared/infrastructure/test_spa.py` | `httpx.AsyncClient` over ASGI with a temp `dist` directory | `shared/infrastructure/spa.py` + `mount_panel()` call; revert removes the mount, `/api` untouched |
| 7-shell | Router, shell, exchange scope, bookings re-homed, theme swap | PR 10 | `cd frontend && npm test -- router AppShell exchange-store` | N/A — frontend-only, `vi.stubGlobal("fetch")` | New `app/router.tsx`, `shared/layout/*`; revert restores the hash-based nav |
| 8-overview | Overview: ledger line, chart, grid, decision rail | PR 11 | `cd frontend && npm test -- OverviewPage ReturnChart MonthlyGrid` | N/A — frontend-only, pure geometry unit tests | New `features/overview/*`; revert removes the route content, shell untouched |
| 9-strategies | Strategies list + detail + dialogs + webhook message | PR 12 | `cd frontend && npm test -- StrategiesPage StrategyDetailPage WebhookMessage` | N/A — frontend-only | New `features/strategies/*`; revert removes the route content |
| 10-settings | Settings: key card, form, delete flow | PR 13 | `cd frontend && npm test -- SettingsPage ExchangeKeyCard DeleteKeyDialog` | N/A — frontend-only | New `features/settings/*`; revert removes the route content |

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

## Migration rehearsal (0024, 0025, 0026)

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
- **0025** (PR 6, `pool_total_at_open`): rehearse; additive column, no seeding to review.
- **0026** (PR 8a, credential snapshot): rehearse; confirm the backfill sets every existing
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

- [ ] 1b.1 RED `backend/tests/main/test_booking_prepare_wiring.py::test_binance_booking_prepare_signs_with_vault_key_not_settings` (design flags this exact test at `test_booking_prepare_wiring.py:61-82` as needing the assertion swap).
- [ ] 1b.2 RED four more wiring tests, one per remaining site, each named `test_binance_<site>_signs_with_vault_key` — balance refresh, venue position, balance sync, reconciliation scan.
- [ ] 1b.3 RED `backend/tests/worker/test_worker.py::test_missing_key_for_enabled_pool_logs_one_error_and_still_starts` — via a fake `AlertPort`/`caplog`, asserting `_assert_keys_present` returns the DEGRADED set and does **not** raise.
- [ ] 1b.4 RED same file `::test_degraded_exchange_does_not_affect_any_other_exchange` — Binance DEGRADED, Bybit's reads/orders proceed unaffected, closes included.
- [ ] 1b.5 RED `backend/tests/shared/test_no_dotenv_credentials.py::test_settings_carries_no_bybit_or_binance_key_field` and `::test_grep_finds_no_production_reader_of_env_bybit_or_binance_key` (a repo-grep test, following the design's own "no Bybit/Binance `credentials_from_settings` left" line).
- [ ] 1b.6 GREEN: rewire the five Binance sites onto `vault.load(BINANCE_EXCHANGE)` inside the same lazy-factory pattern Bybit already uses; remove `Settings.bybit_api_key/secret`, `binance_api_key/secret`, and both factories' `credentials_from_settings`.
- [ ] 1b.7 GREEN: `_assert_keys_present(hints, pools) -> frozenset[str]` in `worker.py` — logs one ERROR per DEGRADED exchange (name + how to store a key), never raises, returns the DEGRADED set; caller (`main.py`) skips registering `RefreshPoolBalance`/venue-read adapters for those exchanges, mirroring `_vault_credential`'s existing per-exchange degradation for orders.
- [ ] 1b.8 GREEN: fold the five diagnostic/probe scripts onto `probe_credentials.vault_credentials`; each `announce()` prints `***last4 (vault)`.
- [ ] 1b.9 RED `backend/tests/accounts/application/test_balance_sync_reloads_pools.py::test_pool_enabled_while_running_is_read_on_the_next_cycle`. It is added by the orchestrator correction on F11 (design.md, near the top), which the tasks phase missed. Run on real Postgres: start with only the Bybit pool enabled, run one `balance.sync` cycle, then flip the Binance pool to `enabled=true` in the database without restarting anything, run the next cycle, and assert that the Binance balance was read. Add the mirror scenario, `::test_pool_disabled_while_running_stops_being_read_on_the_next_cycle`.
- [ ] 1b.10 GREEN: the worker re-reads the enabled pools (`CapitalPoolRepository.list_enabled()`) at the start of every `balance.sync` run, and wherever the in-memory `PoolConfig` map feeds allocation, instead of only in the lifespan. Each newly enabled pool is logged once at INFO and each newly disabled pool once at WARNING, so the change is visible. A pool whose exchange is DEGRADED (no key, decision 20) still gets no reads. No restart is needed in either direction.

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

- [ ] 2a.1 RED `backend/tests/execution/domain/test_market_symbol.py::test_market_key_moved_reconciliation_reexport_still_works` — imports `reconciliation/application/market_key.py`'s `market_key` and asserts identity with `execution/domain/market_symbol.py`'s.
- [ ] 2a.2 RED `backend/tests/strategies/domain/test_allowed_pairs.py::test_allowed_pairs_rejects_empty_string_entry`, `::test_allowed_pairs_rejects_lowercase_entry`, `::test_allowed_pairs_stores_sorted`.
- [ ] 2a.3 RED `backend/tests/migrations/test_0024_strategy_lifecycle.py::test_seeding_uses_distinct_market_key_normalized_symbols_from_signals` — strategy with prior signals spelled `ETHUSDT` and `ETHUSDT.P` (same canonical pair) plus `SOLUSDT`; asserts seeded set `{ETHUSDT, SOLUSDT}` and a WARNING log line naming the strategy and the seeded set.
- [ ] 2a.4 RED same file `::test_strategy_with_no_signals_seeded_empty`.
- [ ] 2a.5 RED same file `::test_seeding_uses_a_frozen_normalization_copy_not_application_import` — asserts the migration module imports no `strategy_manager.execution` code (migrations must not import application code that can change later).
- [ ] 2a.6 RED same file `::test_archived_at_check_constraint_refuses_archived_and_enabled`, `::test_enablement_events_table_and_index_created`, `::test_append_only_trigger_refuses_update`, `::test_append_only_trigger_refuses_delete`, `::test_no_truncate_trigger_exists` (the deliberate omission — eight integration conftests `TRUNCATE ... CASCADE`).
- [ ] 2a.7 RED same file `::test_baseline_event_written_for_every_currently_enabled_strategy_at_migration_time`.
- [ ] 2a.8 RED same file `::test_downgrade_refuses_while_any_observed_event_exists_naming_count`.
- [ ] 2a.9 GREEN: `allowed_pairs.py` (`AllowedPairs(frozenset[str])`, asserts non-empty entries, upper-case, no whitespace), `enablement.py` (`EnablementEvent`, `EnablementOrigin`, `uptime(events, now)`), `strategy.py` (`archived_at` field).
- [ ] 2a.10 GREEN: `execution/domain/market_symbol.py` gains `market_key()`; `reconciliation/application/market_key.py` re-exports it; every existing import path verified unchanged.
- [ ] 2a.11 GREEN: `migrations/versions/0024_strategy_lifecycle.py` — `strategies.allowed_pairs TEXT[] NOT NULL DEFAULT '{}'` + `CHECK (array_position(allowed_pairs, NULL) IS NULL)`; `archived_at timestamptz NULL` + `CHECK (archived_at IS NULL OR enabled = false)`; `strategy_enablement_events` table + `(strategy_id, occurred_at)` index + `fn_strategy_enablement_events_append_only` trigger (UPDATE/DELETE only, no TRUNCATE guard); seeding loop over `DISTINCT strategy_id, symbol FROM signals`; BASELINE event insert for every currently-enabled strategy; downgrade refusal counting OBSERVED rows.
- [ ] 2a.12 GREEN: ORM columns on `strategies/infrastructure/models.py`.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/migrations/test_0024_strategy_lifecycle.py backend/tests/strategies/domain/ backend/tests/execution/domain/test_market_symbol.py`.
Harness: real PostgreSQL (`rules.tasks`: advisory-lock and trigger behavior have no meaningful fake), Tier B up/down/refusal.
Rollback boundary: `migrations/versions/0024_*.py` + the new domain files; downgrade refuses while any OBSERVED event exists (0012/0021 precedent — BASELINE rows carry no information the migration did not create, so a downgrade with only BASELINE rows is allowed).
Forecast: 900–1,200 lines.

### Unit 2d — enablement log wiring + uptime query (600–850 lines)

**Files**: Modify `backend/src/strategy_manager/strategies/application/update_strategy.py`,
`register_strategy.py`; Create `backend/src/strategy_manager/strategies/infrastructure/enablement_log.py`.

- [ ] 2d.1 RED `backend/tests/strategies/application/test_update_strategy.py::test_toggling_enabled_twice_writes_two_events_same_transaction_as_enabled_write`.
- [ ] 2d.2 RED same file `::test_noop_patch_setting_enabled_true_again_writes_no_event`.
- [ ] 2d.3 RED same file `::test_update_strategy_takes_for_update_lock_on_strategy_row` (two concurrent toggles must not both read `false` and both append an "enabled" event).
- [ ] 2d.4 RED `backend/tests/strategies/application/test_register_strategy.py::test_creation_writes_no_event_and_first_enable_writes_the_first_one` (F8 — POST cannot create enabled; this replaces the withdrawn "creating enabled writes the first event" scenario).
- [ ] 2d.5 RED `backend/tests/strategies/domain/test_enablement.py::test_uptime_sums_closed_and_open_intervals`, `::test_never_enabled_strategy_has_zero_uptime_no_activation_date`, `::test_uptime_ignores_repeated_same_state_events_defensively`, `::test_uptime_baseline_flag_renders_as_active_at_least_x_days`.
- [ ] 2d.6 GREEN: `SqlAlchemyEnablementLog`, `StrategyEnablementEventRow`; `UpdateStrategy` gains `ClockPort` and `SELECT ... FOR UPDATE`, appends an event only when `enabled` actually changes, in the same transaction; `RegisterStrategy` appends defensively if `enabled` is ever true (dead code path today, kept for safety per F8).
- [ ] 2d.7 GREEN: `uptime(events, now)` pure function in `enablement.py`.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/strategies/`.
Harness: real PostgreSQL for the FOR-UPDATE race test; pure for `uptime()`.
Rollback boundary: `enablement_log.py` + the two modified use cases; revert stops writing events, existing rows are untouched.
Forecast: 600–850 lines.

### Unit 2e — pairs endpoints, POST requires pairs, list filter, view fields, events GET (600–800 lines)

**Files**: Modify `backend/src/strategy_manager/strategies/infrastructure/router.py`,
`repository.py`; Modify `backend/src/strategy_manager/strategies/application/ports.py`; Create
`backend/src/strategy_manager/strategies/application/replace_allowed_pairs.py`.

- [ ] 2e.1 RED `backend/tests/strategies/application/test_register_strategy.py::test_creating_with_empty_allowed_pairs_is_refused`, `::test_creating_with_at_least_one_pair_succeeds`.
- [ ] 2e.2 RED `backend/tests/strategies/application/test_replace_allowed_pairs.py::test_replace_pairs_normalizes_via_market_key`, `::test_replace_pairs_with_empty_list_refused`.
- [ ] 2e.3 RED `backend/tests/strategies/infrastructure/test_router.py::test_get_strategies_excludes_archived_by_default`, `::test_get_strategies_include_archived_true_shows_archived`, `::test_get_strategy_detail_by_id_always_loads_archived`, `::test_put_allowed_pairs_endpoint`, `::test_post_strategies_requires_min_one_pair_422`, `::test_get_strategy_events_endpoint`.
- [ ] 2e.4 GREEN: `ReplaceAllowedPairs` use case; `POST /strategies` requires `allowed_pairs: [str] (min 1)`; `PUT /strategies/{id}/allowed-pairs`; `GET /strategies?include_archived=false`; `GET /strategies/{id}/events`; `StrategyView` gains `archived_at|null`, `allowed_pairs` (sorted), `uptime: {seconds, first_enabled_at|null, baseline}`.
- [ ] 2e.5 GREEN: `list_all(include_archived)` on the repository.

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

- [ ] 2b.1 RED `backend/tests/signals/application/test_process_signal.py::test_listed_pair_proceeds_normally`.
- [ ] 2b.2 RED same file `::test_unlisted_pair_opening_signal_refused_before_lock_no_reservation_one_warning`.
- [ ] 2b.3 RED same file `::test_close_on_pair_removed_from_list_still_closes_with_one_warning`.
- [ ] 2b.4 RED same file `::test_reverse_on_unlisted_pair_closes_then_refuses_open_ends_flat`.
- [ ] 2b.5 RED same file `::test_spelling_variant_ethusdt_dot_p_matches_allowed_pair_ethusdt` (spelling rule: allowed pair stored as `ETHUSDT`, signal spelled `ETHUSDT.P`).
- [ ] 2b.6 RED same file `::test_archived_strategy_signal_refused_before_untradable_pool_check_one_warning` — WARNING text asserted verbatim: "signal `<id>` for ARCHIVED strategy `<name>` (`<id>`) refused; remove its TradingView alert".
- [ ] 2b.7 RED same file `::test_archived_strategy_refusal_also_applies_in_open_now_continuation`.
- [ ] 2b.8 RED `backend/tests/signals/infrastructure/test_ingest_signal.py::test_archived_strategy_webhook_persists_signal_unchanged_no_lookup_added` — asserts no strategy lookup at ingress.
- [ ] 2b.9 GREEN: `_refuse_unlisted_pair` and the archived-strategy refusal at the top of `handle()`/`_handle_consumes` (archived check first — "whatever its pool" — then unlisted-pair, per design's ordering); each refusal logs exactly one WARNING and never calls `allocate`.
- [ ] 2b.10 GREEN: `StrategyPolicySnapshot.archived`, `.allowed_pairs` fields threaded through `policy_adapter.py`.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/signals/`.
Harness: fakes for every port.
Rollback boundary: two named refusal methods in `process_signal.py`; revert removes both, signals flow as today.
Forecast: 700–1,000 lines.

### Unit 2c — `ArchiveStrategy`, exposure adapter, pool lock, in-lock re-check, concurrency (1,100–1,500 lines)

**Files**: Create `backend/src/strategy_manager/strategies/application/archive_strategy.py`;
Create `backend/src/strategy_manager/strategies/infrastructure/{exposure_adapter,pool_lock_adapter}.py`;
Modify `backend/src/strategy_manager/allocation/application/allocate_capital.py`; Modify
`backend/src/strategy_manager/strategies/infrastructure/router.py`.

- [ ] 2c.1 RED `backend/tests/strategies/application/test_archive_strategy_integration.py::test_archiving_disabled_flat_strategy_succeeds`.
- [ ] 2c.2 RED same file `::test_archiving_enabled_strategy_refused_409_still_enabled`.
- [ ] 2c.3 RED same file `::test_archiving_disabled_strategy_with_open_position_refused_409_names_symbols`.
- [ ] 2c.4 RED same file `::test_dust_that_close_position_reports_not_closable_keeps_ledger_net_nonzero_archive_refuses`.
- [ ] 2c.5 RED same file `::test_archive_is_idempotent_same_archived_at_on_second_call`.
- [ ] 2c.6 RED same file `::test_archived_strategy_patch_refused_409_strategy_archived`, `::test_archived_strategy_pairs_put_refused_409_strategy_archived`.
- [ ] 2c.7 RED same file `::test_enabling_archived_strategy_refused_enabled_unchanged`.
- [ ] 2c.8 RED `backend/tests/strategies/application/test_archive_vs_allocate_concurrency.py::test_allocation_wins_lock_first_archive_then_refused_sees_live_reservation` — **live PostgreSQL, both orderings**.
- [ ] 2c.9 RED same file `::test_archive_wins_lock_first_allocation_in_lock_reread_sees_archived_skips_no_reservation`.
- [ ] 2c.10 RED `backend/tests/allocation/application/test_allocate_capital.py::test_in_lock_reread_skips_with_strategy_disabled_when_disabled_after_prelock_read`, `::test_in_lock_reread_skips_with_strategy_archived_when_archived_after_prelock_read`.
- [ ] 2c.11 GREEN: `ArchiveStrategy.archive(id)` — `SELECT ... FOR UPDATE`, idempotent if already archived, 409 `STILL_ENABLED`, `pg_advisory_xact_lock(LockKey(pool))`, `StrategyExposurePort.exposure` (ledger net ≠ 0 per allocation across every allocation — the multiplicity lesson — live reservations, SUBMITTED attempts), 409 `OPEN_POSITION` naming symbols/allocations/live_reservations/in_flight_attempts, else `archived_at = now`.
- [ ] 2c.12 GREEN: `StrategyExposureAdapter` (composes `ReadSymbolHoldings`, reservations, attempts, following the `InFlightWorkAdapter` precedent), `PoolLockAdapter`.
- [ ] 2c.13 GREEN: `AllocateCapital` re-reads policy right after `acquire`, before the balance read; skips with `STRATEGY_DISABLED`/`STRATEGY_ARCHIVED`.
- [ ] 2c.14 GREEN: `POST /api/strategies/{id}/archive` endpoint; PATCH and pairs-PUT refuse 409 `STRATEGY_ARCHIVED` for an archived strategy.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/strategies/ backend/tests/allocation/`.
Harness: **real PostgreSQL, live concurrency test** (`rules.tasks`: advisory locks have no meaningful fake) — both lock-win orderings proven.
Rollback boundary: `archive_strategy.py`, the two new infra adapters, and the in-lock re-check in `allocate_capital.py`; revert removes archive entirely, `AllocateCapital` returns to its pre-check shape. `DB CHECK (archived_at IS NULL OR enabled = false)` was already added in 2a and stays.
Forecast: 1,100–1,500 lines.

---

## PR 6 — Units 3a + 3b + 3c + 3d: pool capital at open, PnL, curve, stats (2,150–3,100 lines)

**Gate before deploy**: `SELECT count(*) FROM ledger_entries WHERE exchange_fill_id LIKE 'fake-fill-%'` run and recorded (F2 — any rehearsal rows are excluded by design, this just confirms the count for the record).

### Unit 3a — `pool_total_at_open`, migration 0025 (350–500 lines)

**Files**: Create `backend/migrations/versions/0025_reservation_pool_total.py`; Modify
`backend/src/strategy_manager/allocation/domain/reservation.py`, `allocation/infrastructure/{models,repository}.py`, `allocate_capital.py`.

- [ ] 3a.1 RED `backend/tests/migrations/test_0025_reservation_pool_total.py::test_pool_total_at_open_check_allows_null_or_positive`, `::test_downgrade_refuses_while_any_non_null_value_exists`.
- [ ] 3a.2 RED `backend/tests/allocation/application/test_allocate_capital.py::test_reservation_records_in_lock_pool_capital_not_prelock_read` — pool reads 510 pre-lock, 500 in-lock; asserts 500 stored, no extra read (F1).
- [ ] 3a.3 RED same file `::test_pool_total_at_open_written_under_lock_survives_concurrent_allocation_on_same_pool` — **live PostgreSQL**.
- [ ] 3a.4 RED same file `::test_resume_of_retried_allocation_returns_existing_row_unchanged`.
- [ ] 3a.5 GREEN: `migrations/versions/0025_*.py` — `reservations.pool_total_at_open Numeric(38,18) NULL` + `CHECK (pool_total_at_open IS NULL OR pool_total_at_open > 0)`; downgrade refuses while non-null values exist.
- [ ] 3a.6 GREEN: `Reservation.pool_total_at_open: Decimal | None`; `AllocateCapital` writes it from the existing in-lock `pool_balance.total` read (`allocate_capital.py:131`), no new read.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/migrations/test_0025_reservation_pool_total.py backend/tests/allocation/`.
Harness: real PostgreSQL, live concurrency test.
Rollback boundary: additive column; downgrade refuses while non-null values exist (values cannot be recomputed).
Forecast: 350–500 lines.

### Unit 3b — fills source, `derive_trade` (700–1,000 lines)

**Files**: Create `backend/src/strategy_manager/performance/domain/{closed_trade,derive_trade}.py`,
`performance/application/ports.py` (`AllocationFillsSourcePort`), `performance/infrastructure/allocation_fills_source.py`;
Modify `backend/src/strategy_manager/execution/domain/fill.py` (`REHEARSAL_FILL_ID_PREFIX`);
Modify `backend/src/strategy_manager/execution/infrastructure/fake_exchange.py`.

- [ ] 3b.1 RED `backend/tests/execution/infrastructure/test_fake_exchange.py::test_fake_fill_ids_use_the_named_rehearsal_prefix_constant`.
- [ ] 3b.2 RED `backend/tests/performance/domain/test_derive_trade.py::test_realized_pnl_long_trade_100_to_106_with_settlement_fee`, `::test_third_currency_fee_flagged_fees_complete_false_not_converted`, `::test_base_currency_fee_not_subtracted_again_already_in_notional_diff`, `::test_open_allocation_yields_no_realized_pnl_counted_as_open`, `::test_partial_close_counted_as_open_not_closed`, `::test_rehearsal_fill_excluded_from_derivation`.
- [ ] 3b.3 RED same file `::test_pair_derived_from_market_key_of_allocation_fills_spelling_merge` — fills spelled `SOLUSDT.P` on open and `SOLUSDT` on the booked close, asserts one pair `SOLUSDT` (F4, spelling rule).
- [ ] 3b.4 RED `backend/tests/performance/infrastructure/test_allocation_fills_source.py::test_source_excludes_fake_fill_prefix_rows`, `::test_source_groups_by_allocation_strategy_side_fee_currency`, `::test_source_reads_pool_total_at_open_from_reservation_join`.
- [ ] 3b.5 GREEN: `REHEARSAL_FILL_ID_PREFIX = "fake-fill-"` moved into `execution/domain/fill.py`; `fake_exchange.py:144` mints with the constant.
- [ ] 3b.6 GREEN: `ClosedTrade`, `derive_trade()` pure domain function (base-fee rule via `base_currency_of`, closed test, pnl, `fees_complete` flag).
- [ ] 3b.7 GREEN: `SqlAlchemyAllocationFillsSource` — the one SQL aggregate joining `ledger_entries` to `reservations`, `WHERE exchange_fill_id NOT LIKE :rehearsal_prefix || '%'`, grouped by `(allocation_id, strategy_id, side, fee_currency)`.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/performance/ backend/tests/execution/`.
Harness: pure for `derive_trade`; real PostgreSQL for the SQL aggregate (rides `ix_ledger_pool_symbol`/`ix_ledger_allocation`).
Rollback boundary: new module, zero importers outside `performance/`; revert removes it entirely.
Forecast: 700–1,000 lines.

### Unit 3c — curve, drawdown, monthly grid, ranges, UTC (700–1,000 lines)

**Files**: Create `backend/src/strategy_manager/performance/domain/{daily_returns,compound,drawdowns,monthly_grid,range_summary}.py`
(or one `curve.py` module housing all five pure functions); Create
`backend/src/strategy_manager/performance/application/{read_pool_performance}.py`.

- [ ] 3c.1 RED `backend/tests/performance/domain/test_curve.py::test_two_trades_different_days_compound_1_05_times_1_02` (the design worked example).
- [ ] 3c.2 RED same file `::test_two_trades_same_utc_day_summed_not_chained_0_03_index_1_03` (the +20/+10 on a 1,000 USDT pool worked example — asserts 1.03, explicitly NOT 1.0302).
- [ ] 3c.3 RED same file `::test_drawdown_from_previous_peak_1_20_to_1_14_is_5_percent`, `::test_no_drawdown_at_new_peak_is_zero`.
- [ ] 3c.4 RED same file `::test_utc_month_boundary_close_at_2026_08_31_22_30_minus_3_counts_september` (decision 16, UTC boundary case).
- [ ] 3c.5 RED same file `::test_exclusions_reported_two_open_one_missing_capital_at_open`.
- [ ] 3c.6 RED same file `::test_range_summary_7d_30d_90d_1y_all_computed_independently`.
- [ ] 3c.7 RED `backend/tests/performance/domain/test_curve.py::test_no_qualifying_trades_yields_empty_result_not_error`, `::test_only_rehearsal_fills_yields_same_empty_result`.
- [ ] 3c.8 GREEN: `daily_returns()`, `compound()`, `drawdowns()`, `monthly_grid()`, `range_summary()` — pure `Decimal`, UTC day taken via `closed_at.astimezone(UTC).date()`, never a database session time zone.
- [ ] 3c.9 GREEN: `ReadPoolPerformance` application read composing the domain functions over `AllocationFillsSourcePort`.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/performance/`.
Harness: pure, no DB.
Rollback boundary: pure domain functions with one application consumer; revert removes both, nothing else references them yet (endpoints land in PR 7).
Forecast: 700–1,000 lines.

### Unit 3d — per-strategy and per-pair stats (400–600 lines)

**Files**: Create `backend/src/strategy_manager/performance/domain/by_pair.py`; Create
`backend/src/strategy_manager/performance/application/{read_strategy_performance,read_strategy_trades}.py`.

- [ ] 3d.1 RED `backend/tests/performance/domain/test_by_pair.py::test_solusdt_dot_p_and_solusdt_merge_into_one_pair` (F4, spelling rule).
- [ ] 3d.2 RED same file `::test_per_pair_stats_include_pair_removed_from_allowlist` (allowlist independence).
- [ ] 3d.3 RED `backend/tests/performance/application/test_read_strategy_performance.py::test_strategy_curve_uses_pool_capital_at_open_as_contribution`, `::test_strategy_stats_scoped_to_its_own_pool_settlement_currency`.
- [ ] 3d.4 RED `backend/tests/performance/application/test_read_strategy_trades.py::test_keyset_pagination_on_closed_at_and_allocation_id_two_trades_same_millisecond_across_page_boundary` (the "+1ms" lesson).
- [ ] 3d.5 GREEN: `by_pair()` pure domain function grouped per allocation then by `market_key()`; `ReadStrategyPerformance`, `ReadStrategyTrades` application reads (keyset on `(closed_at, allocation_id)` descending, never `closed_at` alone).

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/performance/`.
Harness: pure for `by_pair`; real PostgreSQL for the pagination boundary test.
Rollback boundary: two new application reads; revert removes both, no endpoint depends on them until PR 7.
Forecast: 400–600 lines.

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

## PR 8a — Units 6a + 6b + 6c: key policy, inspectors, 0026, `SaveCredential`, trade-capability refusal (1,900–2,600 lines)

**Gate before rules are written**: PR 1's **P1–P3** recorded. No line of `key_policy.py` is
written before "PR 1 — Probe results" carries P1–P3.

### Unit 6a — key policy + inspectors + migration 0026 (800–1,100 lines)

**Files**: Create `backend/src/strategy_manager/accounts/domain/key_policy.py`; Create
`backend/src/strategy_manager/accounts/infrastructure/key_inspectors/{bybit,binance,registry}.py`;
Modify `backend/src/strategy_manager/accounts/domain/exchange_credential.py`; Create
`backend/migrations/versions/0026_credential_snapshot.py`.

- [ ] 6a.1 RED `backend/tests/accounts/domain/test_key_policy.py::test_evaluate_key_refuses_withdraw_permission_bybit_wallet_withdraw` (using the P1-recorded fixture), `::test_evaluate_key_allows_internal_transfer_only_accounttransfer`, `::test_evaluate_key_refuses_withdraw_binance_enable_withdrawals`, `::test_evaluate_key_allows_internal_transfer_binance`.
- [ ] 6a.2 RED same file `::test_evaluate_key_derives_trade_capable_true_bybit_readonly_zero_and_permission_present` (using the P2-recorded field), `::test_evaluate_key_derives_trade_capable_false_readonly_key`, `::test_evaluate_key_derives_trade_capable_binance_enablefutures_true` (P3), `::test_evaluate_key_derives_trade_capable_false_binance_enablefutures_false`.
- [ ] 6a.3 RED `backend/tests/accounts/infrastructure/test_key_inspectors.py::test_bybit_inspector_calls_wallet_balance_and_query_api_never_an_order` (`httpx.MockTransport`, probe-recorded payload shapes), `::test_binance_inspector_calls_api_restrictions_never_an_order`, `::test_registry_dispatches_by_exchange_unserved_raises`.
- [ ] 6a.4 RED `backend/tests/migrations/test_0026_credential_snapshot.py::test_permissions_and_validated_at_check_constraint_paired`, `::test_backfill_sets_trade_capable_true_for_every_existing_row`, `::test_default_is_dropped_insert_without_trade_capable_fails`, `::test_downgrade_refuses_while_any_trade_capable_false_row_exists_naming_count`.
- [ ] 6a.5 GREEN: `PermissionSnapshot`, `KeyVerdict`, `evaluate_key(snapshot)` — pure, 8(a)/8(b) refusals and trade-capability derivation.
- [ ] 6a.6 GREEN: `trade_capable`, `validated_at`, `permissions` on `ExchangeCredential`/`CredentialHint` (`trade_capable` has no default — every constructor call names it).
- [ ] 6a.7 GREEN: `BybitKeyInspector`, `BinanceKeyInspector`, `KeyInspectorRegistry` — a GET balance read plus permission introspection, never an order.
- [ ] 6a.8 GREEN: `migrations/versions/0026_*.py` — `permissions JSONB NULL`, `validated_at timestamptz NULL`, `CHECK ((permissions IS NULL) = (validated_at IS NULL))`, `trade_capable boolean NOT NULL` added `DEFAULT true`, backfilled, default dropped; downgrade refuses while any `false` row exists.

Gate: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short backend/tests/accounts/ backend/tests/migrations/test_0026_credential_snapshot.py`.
Harness: `httpx.MockTransport` for inspectors (no real credential, rule 1); real PostgreSQL for the migration.
Rollback boundary: migration 0026 (refuses downgrade while `trade_capable=false` rows exist) + new domain/infra files; revert leaves every existing store script working unchanged.
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
run the store scripts only from the new code, because 0026 makes `trade_capable` mandatory.
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
- [ ] 10c.2 RED `frontend/src/features/settings/ExchangeKeyCard.test.tsx::test_no_key_ever_stored_shows_neutral_empty_state_no_amber_border`, `::test_readonly_key_shows_amber_border_and_cannot_trade_sentence`, `::test_degraded_no_key_but_enabled_pool_shows_amber_border_and_no_key_stored_sentence` (decision 20 — distinguishing amber "no key" from neutral "no key" by whether the pool is enabled), `::test_active_key_shows_last4_reads_and_trades_or_reads_only_no_withdrawal_checked_date`, `::test_key_sealed_before_0026_shows_not_validated`.
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
