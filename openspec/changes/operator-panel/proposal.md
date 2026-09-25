# Proposal: Operator panel

SDD phase PROPOSE, 2026-09-24. HEAD `a7f3297`. Preflight: auto / hybrid / auto-chain / 400.
Inputs: [[sdd-operator-panel-explore]] (`exploration.md`, Engram #261); owner decisions 1–9 (`project/frontend-decisions`), 10 (`project/frontend-decisions-routing`), 11 (`project/frontend-decisions-archived-signals`), 12 (`project/frontend-decisions-curve`); facts `project/frontend-serving-and-design`. This file is the record; Engram `sdd/operator-panel/proposal` is the mirror.

## Intent

The owner operates this system through scripts, `curl` against the admin API and SSH. There is no way to see what the strategies are earning, which pairs they trade, how long they have been live, what capital is available per pool, or which API keys are loaded and with what permissions. The only UI (the pending-bookings view from `book-venue-closes`) is built but not served anywhere. Meanwhile three gaps sit in the money path: any symbol a TradingView alert names is traded (no per-strategy allowlist), a retired strategy can only be disabled, never retired, and Bybit signs every READ with the TRADE key while Binance's read key lives in plaintext `.env`.

This change delivers a single-user operator panel — Overview, Strategies, Settings — served same-origin by FastAPI behind Cloudflare Access, plus the backend it needs: strategy allowed-pairs, archive and an enable/disable audit log; READ/TRADE key purposes in the vault with validated key management; and read-only performance projections over the append-only ledger.

**Why now**: `DRY_RUN=false` is close (archive-report open item 3). The allowlist, the key split and the per-trade return denominator all get more expensive once live history exists — the last one cannot be backfilled at all.

## Owner decisions (binding, not reopened)

1. One strategy per pool (existing model: a strategy is bound to exactly one `(exchange, venue, settlement_currency)` pool; several strategies still share a pool) + an **allowed-pairs list**; unlisted pairs refused with WARNING; stats by pair. Archive, never delete. Webhook message shown copy-ready.
2. Existing React SPA, shared layout shell (top exchange bar; sidebar Overview/Strategies/Settings, bottom bar on mobile), served by FastAPI same origin.
3. Pending-bookings panel on the right of Overview (filtered by exchange; below on mobile).
4. Cloudflare Access in front; single user; no `user_id`. Multi-user and fee charging are a separate change.
5. Domain `strategymanager.trade` via Cloudflare Tunnel; webhook stays on DuckDNS, its proxy forwarding only `/webhook/tradingview`.
6. Dashboard: strategy return in % from realized ledger PnL, unaffected by deposits/withdrawals; drawdown from previous peak; monthly textured grid; current available balance; PnL for 7D/30D/90D/1Y/All. No manual contributions register.
7. Settings manages BOTH keys per exchange (READ + TRADE) in the vault; `.env` stops holding keys. Keys never return to the browser beyond last-4 + permissions.
8. Validation on save: (a) a live read succeeds; (b) any key with WITHDRAW permission is refused (internal transfer, e.g. Bybit `AccountTransfer`, allowed); (c) the READ key cannot trade, the TRADE key can trade futures.
9. Uptime = cumulative enabled time from a recorded enable/disable event log (also an audit trail), shown as "active X days" + first activation date.
10. Clean path routes (`/strategies/<uuid>`, `/settings`) via FastAPI SPA fallback; ALL admin API moves under `/api/...`; `/webhook/tradingview` and `/health` do not move.
11. A signal for an ARCHIVED strategy is persisted by the webhook as usual and refused in processing with one WARNING naming the strategy and telling the owner to remove the alert. No database lookup is added to the webhook.
12. The return curve is COMPOUNDED (geometric chaining). Each closed trade's return is measured against the pool capital at open; concurrent trades are chained per day so the same capital is not counted twice (design shows the detail to the owner).

Standing: rule 7 (no blended cross-pool totals; several settlement currencies on one exchange show per pool), i18n EN/ES, Tailwind tokens only, the frontend-design plugin is used for visual design.

## Scope

### In scope

**Backend — credentials**
- Vault `purpose` (`READ` | `TRADE`): existing rows backfilled `TRADE`; the partial unique becomes one active row per `(exchange, purpose)`; `load` / `store` / `hints` and the worker's startup self-test gain `purpose`.
- Every venue READ (balance sync and refresh, venue-position reads, reconciliation scan, booking prepare) signs with the READ key; orders sign with the TRADE key. Bybit's six `main.py` call sites and Binance's `.env` read path both move. No fallback from READ to TRADE: a missing READ key refuses loudly where the key is loaded.
- `.env` key settings (`bybit_api_key/secret`, Binance read key) and `binance_credentials_from_settings` are removed; `scripts/store_*_credentials.py` gain a purpose argument; diagnostic scripts that read keys from `.env` load from the vault and print which key (last-4, purpose) they run as.
- A GET-only permission probe script (Bybit `/v5/user/query-api`, Binance `/sapi/v1/account/apiRestrictions`), run by the owner on the VPS BEFORE validation logic is written (see "Unverified items and how they get verified").
- Validated key management: a key-permission port with Bybit and Binance adapters; add/rotate use case enforcing decision 8; the permission snapshot and last-4 are stored with the row.

**Backend — strategies**
- Allowed-pairs storage per strategy, stored in `market_key()` canonical form; a pre-lock refusal in `ProcessSignalHandler.handle()` next to the untradable-pool guard, one WARNING per refused signal.
- `archived_at` (null while live, set once). Archive requires the strategy disabled (and see Q2). Enabling an archived strategy is refused. Archived signals are refused in processing with one WARNING (decision 11). Lists exclude archived by default; detail still loads.
- Enable/disable event log written in the same transaction as the `enabled` change, only when the value actually changes; creation writes the first event when created enabled. Uptime is a derived query, never a stored running total.

**Backend — performance (read-only over the ledger)**
- Record the pool capital at open on the reservation, inside the existing locked allocation transaction, from the same `pool_balance.total` already read to compute `requested` (decision 12's denominator is not persisted today and cannot be derived later: `PARTIAL` outcomes and a mutable `allocation_percent` both break `granted / allocation_percent`).
- Realized PnL per closed allocation in native settlement currency (opening and closing fills share `allocation_id`).
- Per pool and per strategy: compounded return curve, drawdown from previous peak, month×year grid, PnL for 7D/30D/90D/1Y/All, trade count, stats by pair (`GROUP BY symbol` over the ledger, independent of the current allowlist), uptime.
- Current available balance per pool from `pool_balance_snapshots`.

**Backend — API and serving**
- Every admin router under `/api` (`/api/strategies`, `/api/reconciliation`, new routers). `/webhook/tradingview` and `/health` unchanged.
- New endpoints (all behind `require_admin_token`): pools/balances, performance reads, strategy stats, allowed-pairs edit, archive, credential list / add / rotate.
- FastAPI serves the built SPA: `/assets/*` static, and an `index.html` fallback for GETs outside `/api`, `/webhook`, `/health`. An unknown `/api/*` path returns 404 JSON, never `index.html`.

**Frontend**
- A router library and the shared layout shell (exchange bar, sidebar / bottom bar), routes `/`, `/strategies`, `/strategies/<uuid>`, `/settings`; the existing bookings view re-homed inside the shell with its paths moved to `/api`.
- Overview: available balance per pool, PnL ranges, compounded curve with drawdown, monthly grid, pending-bookings panel filtered by exchange.
- Strategies: list, detail with stats and uptime, enable/disable, allowed-pairs edit, archive with confirm, copy-ready webhook message (a pure frontend template over `signals/domain/alert.py`'s documented shape).
- Settings: READ and TRADE slot per exchange with last-4 + permissions; add/rotate with the validation outcome shown.
- EN/ES for every string; Tailwind tokens only; empty states everywhere (the ledger is empty under DRY_RUN); Vitest.

**Owner-run steps (infrastructure, not code)** — listed under Dependencies.

### Out of scope
- Multi-user, `user_id`, login, and fee charging (decision 4: separate, possibly regulated change).
- Deleting strategies. Un-archiving (archive is terminal, matching the `terminal_at` pattern; assumption stated, not a new decision).
- A manual deposits/contributions register (declined, decision 6) and a pool-balance equity history table.
- Writing leverage or margin mode from the panel.
- COIN-M, Pionex execution, a REVERSE that flips.
- Any ledger write, compensating entry or correction mechanism.
- Notifications.
- Visual design detail (layout, typography, chart styling) — belongs to design with the frontend-design plugin.
- Terraform/automation of Cloudflare or DuckDNS configuration.

### Left to design (stated, not decided here)
Allowed pairs as an array column vs a child table; the exact return formula and how concurrent trades chain per day (decision 12 says design shows it to the owner); fee-currency conversion when `fee_currency != settlement_currency`; router library; recharts vs dependency-free inline SVG; whether the API process validates and encrypts a new key itself or hands it to the worker; how uptime treats strategies that predate the event log; status codes and refusal wording; whether the bookings exchange filter is server- or client-side.

## Capabilities

### New Capabilities
- `exchange-credentials`: vault purposes READ/TRADE, one active key per `(exchange, purpose)`, which key signs which call, no keys in `.env`, startup self-test, validated add/rotate (decision 8), last-4 + permission snapshot as the only data returned.
- `strategy-lifecycle`: allowed pairs and their refusal, archive and its refusals, enable/disable event log, uptime.
- `performance-reporting`: pool capital at open, realized PnL per allocation, compounded curve, drawdown, monthly grid, PnL ranges, stats by strategy and pair — all per pool, native currency, read-only.
- `admin-api`: the `/api` namespace, bearer token on every admin route, the endpoint surface for panel reads and writes.
- `panel-serving`: same-origin static serving, SPA fallback, reserved paths (`/api`, `/webhook`, `/health`), unknown API path is 404.
- `operator-panel`: the UI behaviour — shell, routes, views, empty states, EN/ES, secrets never rendered.

### Modified Capabilities
- `capital-allocation`: signal processing refuses an unlisted pair and an archived strategy before the pool lock; a reservation records the pool capital at open inside the same serialized transaction.
- `venue-close-booking`: only if design adds a server-side exchange filter to the pending-bookings list; otherwise none.

`signal-ingress`, `trade-ledger`, `trade-execution`, `job-queue`, `venue-reconciliation`: no requirement change (existing specs name no literal paths, so the `/api` move is not a spec delta).

## Approach

Backend foundations first, in the order they touch money paths, then the API and serving, then the frontend. Each PR merges to `main` and leaves it deployable.

- **Credentials**: extend the vault with `purpose` exactly as migration 0013 set the precedent. The read/trade split is a rewiring of live, verified call sites, so it ships with a startup self-test per `(exchange, purpose)` and an owner-run key-storage step between migrate and restart.
- **Validation is built on probed shapes, not docs.** This codebase has been burned by venue docs (CLAUDE.md, "Where the futures docs are wrong"). No refusal rule is coded until the probe output is recorded.
- **Allowlist and archive** reuse the existing pre-lock guard pattern in `process_signal.py`; no new lock, no ingress lookup.
- **Performance** is pure queries plus pure domain math over the ledger; the one write is a column on `reservations` filled inside the existing allocation transaction.
- **API move** is mechanical: `apiFetch` centralizes the base URL; the frontend makes three calls today.
- **Frontend** layers views on the shell; TanStack Query gets its first real consumer.

### Unverified items and how they get verified

| Item | Why it matters | Verification | Blocks |
| --- | --- | --- | --- |
| Bybit withdraw flag on `/v5/user/query-api` | Decision 8(b) cannot be coded without knowing whether the key object exposes withdraw at all, or whether Bybit governs it by address allowlist outside the key | GET-only probe, owner-run on the VPS, against the Bybit TRADE key (vault) and the new READ key once created; raw `permissions` (and `readOnly`, if present) recorded in design/tasks | 8(b)/(c) for Bybit (PR 6) |
| Binance `/sapi/v1/account/apiRestrictions` live shape | Web-verified only | Same probe against the Binance READ key (today in `.env`) and TRADE key (vault) | 8(b)/(c) for Binance (PR 6) |
| Can a Binance READ key read USDT-M futures with `enableFutures=false`? | If futures reads need `enableFutures=true`, 8(c) "READ key cannot trade" cannot be proven by that flag | Probe records the current working read key's `enableFutures`; if `true`, the owner is told 8(c) needs another signal before PR 6 is designed | 8(c) for Binance |
| Is Bybit "cannot trade" visible without placing an order? | Validation must never place an order | Probe records whether `permissions`/`readOnly` distinguishes a read-only key | 8(c) for Bybit |
| Whether `settings.bybit_api_key/secret` have callers beyond `bybit/factory.py` | Decides what "`.env` stops holding keys" removes | Code read at design time | PR 1c |
| Current DuckDNS proxy rules | If it forwards more than the webhook, the panel is exposed without Cloudflare Access | Owner inspects the proxy config before PR 4 deploys | PR 4 deploy |

The probe is GET-only, prints the key it runs as (last-4 + purpose) and never prints a secret, following `scripts/probe_credentials.py`. Resolved during this proposal: a pending-bookings list endpoint already exists (`GET /reconciliation/bookings?state=pending`).

## Impact on the non-negotiables

| Rule | Impact |
| --- | --- |
| **DRY_RUN (1)** | Default unchanged. Key validation only calls read and permission-introspection endpoints; it never places an order under any DRY_RUN value. No test needs a real credential: the permission port has a fake. `MASTER_ENCRYPTION_KEY` is already mandatory at worker start regardless of DRY_RUN (`main.py:632`); this change adds no new DRY_RUN coupling. The performance views render empty states, because the ledger is empty under DRY_RUN. |
| **Idempotency (2)** | Webhook untouched. An archived-strategy or unlisted-pair signal is persisted with its key, then refused, so a replay still deduplicates at ingress and the refusal is not repeated. An enable event is written only on a real state change, so a replayed PATCH writes nothing. Key add/rotate follows the existing supersede rotation. |
| **Webhook never executes (3)** | Unchanged; no lookup added before the 200 (decision 11). The webhook path does not move under `/api`. |
| **Allocation is a transaction (4)** | The allowlist and archive checks run pre-lock and write nothing. Pool capital at open is written inside the existing `pg_advisory_xact_lock` transaction from the balance already read there; no new read, no new lock. |
| **Pool isolation (5)** | Every read model is keyed by `(exchange, venue, settlement_currency)`. Bybit's single USDT pool is shown once. |
| **Append-only ledger (6)** | Nothing writes `ledger_entries`. Performance is a projection over it. The enable event log is append-only too (design confirms the trigger). |
| **Native-currency PnL (7)** | Every figure is per pool, in its settlement currency. No cross-pool or cross-currency total anywhere, including the exchange bar. `usd_rate_at_fill` is not used to blend. |
| **Credentials (8)** | Still envelope-encrypted; still only the worker decrypts. NEW: the API process receives a plaintext key on save, validates it in memory and encrypts it — so it needs the master key to encrypt, never to decrypt. The browser gets last-4 + the stored permission snapshot, never a secret. Permissions shown are the snapshot recorded at save time, because re-querying them would require decrypting in the API process. |

## The `/api` move — what it breaks

- Frontend: `BookingsListView.tsx`, `ConfirmBookingDialog.tsx`, `RejectBookingDialog.tsx` and their tests; `client.test.ts` fixtures.
- Backend tests: `strategies/infrastructure/test_router_auth.py`, `reconciliation/infrastructure/test_router.py` and its conftest, `shared/infrastructure/test_admin_auth.py`, `test_access_log.py`, `test_smoke.py`, and any other test that hard-codes a prefix.
- The startup message in `admin_token_invariant.py`.
- The owner's own `curl` commands and runbooks against `/strategies` and `/reconciliation`. No script under `backend/scripts/` calls the HTTP API (grepped).
- Not affected: `/webhook/tradingview` (TradingView alerts need no reconfiguration), `/health`.

## Delivery: sequential PRs, ordered by risk

Sequential to `main` (branch, PR, merge, next branch from the updated `main`); never stacked (convention #243). One work-unit commit per unit.

| PR | Units | Ends at | Forecast |
| --- | --- | --- | --- |
| 1 | 1a permission probe (GET-only) · 1b vault `purpose` migration + port + self-test + store scripts · 1c READ/TRADE rewiring of every venue call, `.env` keys removed, missing READ key refuses | Every read signs with the READ key. Owner stores keys between migrate and restart. | 1,550–2,150 |
| 2 | 2a schema (allowed pairs, `archived_at`, enable events) · 2b allowlist refusal in processing · 2c archive + its refusals · 2d enable event log + uptime query · 2e admin endpoints for pairs/archive/list filter | Money path gains the allowlist and archive. **2b waits on Q1; 2c waits on Q2.** | 2,150–2,900 |
| 3 | 3a pool capital at open on reservations (live-PG test) · 3b realized PnL per allocation · 3c compounded curve, drawdown, monthly grid, PnL ranges · 3d per-strategy/per-pair stats | Read models exist; nothing exposes them. | 1,850–2,600 |
| 4 | 4a admin API under `/api` + frontend paths + tests · 4b SPA static serving + fallback + reserved paths | The existing bookings view is served same-origin. | 700–1,000 |
| 5 | Read endpoints: pools/balances, performance, strategy stats | Panel read contract complete. | 600–850 |
| 6 | 6a key-permission port + Bybit/Binance adapters (from probe output) · 6b add/rotate use case + credential endpoints | Keys managed over the API. **Needs 1a's recorded output.** | 1,200–1,600 |
| 7 | Router library, layout shell, routes, bookings view re-homed, query hooks | Navigable shell. | 800–1,100 |
| 8 | Overview view | | 1,000–1,400 |
| 9 | Strategies list + detail | | 1,000–1,400 |
| 10 | Settings view | | 600–850 |

Bottom-up total **11,450–15,850** authored changed lines. `book-venue-closes` planned 9,000–13,000 after a ~2x overrun on the change before it, concentrated in `main.py` wiring and integration tests. PR 1c and PR 3a sit in exactly that territory, and frontend views have no estimating history here. **Plan for 16,000–22,000.** Expect PRs 1, 2, 8 and 9 to split again at `sdd-tasks`.

Every PR exceeds the 400-line review budget. The review unit is the work-unit commit (250–1,000 lines each). Holding every PR under 400 would mean roughly 40 PRs; the cut above follows the risk seams the owner accepted for the last change (#243).

## Affected areas

| Area | Impact | Description |
| --- | --- | --- |
| `backend/src/strategy_manager/accounts/` (vault, ports, models) + new migration | Modified | `purpose`, per-purpose unique, permission snapshot, key-permission port and adapters |
| `backend/src/strategy_manager/main.py` | Modified | Six Bybit `.load(BYBIT_EXCHANGE)` sites and the Binance read path rewired by purpose; new routers; `/api` prefix; static mount |
| `backend/src/strategy_manager/worker.py` | Modified | Self-test per `(exchange, purpose)` |
| `backend/src/strategy_manager/shared/config.py`, `shared/infrastructure/{bybit,binance}/factory.py`, `.env.example` | Modified | `.env` key settings removed; production origin and static path config |
| `backend/scripts/store_*_credentials.py`, `check_*` / `probe_credentials.py`, new permission probe | Modified/New | Purpose argument; vault-loaded keys; GET-only probe |
| `backend/src/strategy_manager/strategies/` | Modified | Allowed pairs, `archived_at`, enable event log, uptime, new endpoints |
| `backend/src/strategy_manager/signals/application/process_signal.py`, `allocation/application/ports.py` | Modified | Pre-lock allowlist and archive refusals; `StrategyPolicySnapshot` fields |
| `backend/src/strategy_manager/allocation/` (`allocate_capital.py`, reservation model) + migration | Modified | Pool capital at open |
| `backend/src/strategy_manager/ledger/application/` + repository | New reads | Realized PnL, curve, drawdown, grid, ranges, by-pair |
| `backend/src/strategy_manager/reconciliation/infrastructure/router.py`, `strategies/infrastructure/router.py` | Modified | Moved under `/api` |
| `frontend/src/` (`app/`, `shared/api/`, `features/bookings/`, new `features/overview|strategies|settings`), `package.json` | Modified/New | Router, shell, views, i18n EN/ES |
| `backend/tests/**`, `frontend/src/**/*.test.*` | Modified/New | Prefix moves; new coverage |

## Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Rewiring six live, verified Bybit call sites signs a read with the wrong key; it surfaces as `AUTH_UNAVAILABLE`, which reads like a venue refusal | Med | Startup self-test per `(exchange, purpose)`; no READ→TRADE fallback; the probe prints which key it is; `.env` values kept on the VPS until PR 1 is proven in production |
| Owner deploys PR 1 before storing the READ keys | Med | The worker refuses to start, loudly, naming the missing `(exchange, purpose)`; the deploy runbook orders migrate → store → restart |
| Bybit exposes no withdraw flag per key | Med | Probe first; if absent, 8(b) cannot be enforced for Bybit as stated and goes back to the owner before PR 6 |
| Binance futures reads need `enableFutures=true` | Med | Probe first; 8(c) for Binance returns to the owner if so |
| Master key present in the API process | Med | Encrypt-only use there; decryption stays worker-only; design weighs the alternative of handing the key to the worker |
| Allowlist ships with empty lists and refuses every signal | High if unaddressed | Q1 below; 2b does not merge until answered |
| Archiving a strategy with an open position strands it (if archived closes are refused) | Med | Q2 below; 2c's refusal rule waits on it |
| SPA fallback swallows an API 404 or the webhook | Low | Fallback excludes `/api`, `/webhook`, `/health`; tests assert a 404 JSON for an unknown `/api/*` path |
| DuckDNS proxy exposes the panel without Cloudflare Access | Med | Owner verifies the proxy forwards only `/webhook/tradingview` before PR 4 deploys; `ADMIN_API_TOKEN` stays as defence in depth |
| The compounded curve, per-day chaining, is misread | Med | Design presents the formula to the owner (decision 12); pure-function tests with hand-computed fixtures |
| Charts built on zero data (DRY_RUN) hide shape bugs | Med | Fixture-driven tests; empty states tested separately |
| Line overrun | High | Forecast above already corrected for history; `main.py` wiring isolated in 1c |
| Engram shows #263 and #264 as mutually "contested" (pending) | Low | They answer different questions (archived signals vs curve); the orchestrator should resolve the flag as `not_conflict` |

## Rollback plan

- **PR 1**: code revert restores single-key reads, provided the Binance read key is still in `.env` (keep it until PR 1 is proven). The `purpose` downgrade REFUSES while any active `READ` row exists, because collapsing to one-active-per-exchange would violate the old unique; the owner deactivates the READ rows, then downgrades. No key material is lost.
- **PR 2**: revert removes the allowlist and archive checks; signals flow as today. Downgrade drops pairs, `archived_at` and the event log. That DELETES audit history, so the downgrade should refuse while events exist, following the 0012/0021 precedent; design confirms.
- **PR 3**: read models are pure; revert removes them. The pool-capital-at-open column is additive; its values cannot be recomputed, so the downgrade refuses while non-null values exist.
- **PR 4**: revert the backend and frontend together (same PR); prefixes return to `/strategies` and `/reconciliation`. Infrastructure is untouched by a code revert.
- **PR 5**: revert; endpoints 404; views that use them come later.
- **PR 6**: revert; keys already stored remain valid vault rows, and the scripts still manage them.
- **PRs 7–10**: revert; the views disappear. Nothing server-side depends on them.
- This change writes nothing to `ledger_entries`, so there is no ledger data to roll back.

## Dependencies (owner-run steps, not code)

1. **Before PR 1c deploys**: create a Bybit READ-only key (no trade, no withdraw); store it in the vault as `READ`; store the Binance read key (today in `.env`) as `READ`; then restart. Remove the `.env` key values only after PR 1 is proven.
2. **PR 1a**: run the GET-only permission probe on the VPS against each of the four keys; the output is recorded before PR 6 is designed.
3. **Before PR 4 deploys**: confirm the DuckDNS proxy forwards only `/webhook/tradingview`.
4. **For PR 4 onward**: `strategymanager.trade` on Cloudflare; a Cloudflare Tunnel (`cloudflared` on the VPS) routing it to the FastAPI process; a Cloudflare Access policy for the owner's identity. The frontend build lands where FastAPI serves it (design fixes the path).
5. Update personal `curl` runbooks to the `/api` prefix.

## Success criteria

- [ ] With both keys stored, every venue read logs/uses the READ key and every order the TRADE key; with a READ key missing, the worker refuses to start and names `(exchange, purpose)`.
- [ ] `.env` holds no exchange API key; `rg` finds no production reader of one.
- [ ] Saving a key with withdraw permission, a READ key that can trade, or a TRADE key that cannot trade futures is refused with a stated reason and nothing stored; a valid key stores and shows last-4 + permissions only.
- [ ] A signal for an unlisted pair and a signal for an archived strategy are each persisted, refused with exactly one WARNING, and create no reservation.
- [ ] Enabling an archived strategy is refused; toggling `enabled` twice writes two events, a no-op PATCH writes none; uptime equals the summed intervals.
- [ ] Every new reservation carries the pool capital at open; `ledger_entries` is byte-identical before and after any panel read.
- [ ] The compounded curve, drawdown and grid match hand-computed fixtures; no response or view contains a cross-pool total.
- [ ] `GET /api/strategies` works; `GET /strategies/<uuid>` returns `index.html`; `GET /api/unknown` returns 404 JSON; `POST /webhook/tradingview` behaves exactly as before.
- [ ] Under `DRY_RUN=true`, the panel loads with empty states and no test needs a real credential.
- [ ] Every view renders in EN and ES with no hardcoded display text; backend and frontend gates pass.
- [ ] The panel is reachable only through Cloudflare Access at `strategymanager.trade`; DuckDNS serves only the webhook.

## Open owner questions (genuinely open; each blocks only what it names)

**Q1 — What allowed pairs do existing strategies start with? Blocks unit 2b.** Decision 1 refuses unlisted pairs, and no strategy has a list today, so enforcement shipping alone refuses EVERY signal. *Recommendation*: the migration seeds each strategy's list from the distinct symbols (canonical `market_key`) it has already received in `signals`, logs what it seeded, and the owner prunes in the panel. Alternative: ship empty and let the owner fill the lists through the PR 2e endpoints before enforcement is enabled.

**Q2 — May a strategy be archived while it holds an open position?** Decision 11 says an archived strategy's signal is "refused", with "the same treatment as a disabled strategy". Those two halves diverge for a CLOSE: today a disabled strategy is skipped only on the opening (CONSUMES) path (`allocate_capital.py:104-110`), so its close signals still run. If an archived strategy's closes are refused, archiving with a position open strands that position. *Recommendation*: archive requires the strategy disabled AND flat (no open position in the ledger, no live reservation), refused otherwise with a reason; then every archived signal can be refused with no stranded capital, and the divergence never arises. Alternative: allow archiving with a position open and let close signals through, as disabled does.
