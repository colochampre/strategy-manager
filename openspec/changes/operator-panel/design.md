# Design: Operator panel

SDD phase DESIGN, 2026-09-24. HEAD `a7f3297`. Preflight: auto / hybrid / auto-chain / 400.
Inputs: `proposal.md` (Engram `sdd/operator-panel/proposal`), `owner-decisions.md` (1–18, binding, none reopened), decision 19 (Engram `sdd/operator-panel/visual-design`: visual direction A), `exploration.md`, and the seven specs under `specs/`. This file is the record; Engram `sdd/operator-panel/design` is the mirror.

> **Revised 2026-09-24 (revision pass before `sdd-tasks`).** Applied: owner decision 18 (ONE key per exchange; supersedes decision 7, rule 8(c) and OQ4), decisions 15–17 (OQ1–OQ3 resolved), decision 19 (visual direction A), the spec realignment of findings F1–F4 and F8, the removal of the wrong finding F10, the smaller unit-1a probe, and a recomputed PR plan and forecast. Migrations are renumbered because the purpose migration is gone: lifecycle is now **0024**, pool capital at open **0025**, credential snapshot **0026**. Each changed section carries its own "Revised 2026-09-24" note.
>
> **Revised 2026-09-25 (decisions 20–23, new and binding).** Applied: decision 20 (a keyless exchange with an enabled pool is DEGRADED, not a startup refusal — F7 and decision 2's startup self-test are corrected again), decision 21 (`SaveCredential` auto-enables that exchange's single futures pool from a fixed constant table; new finding F11 on the worker's own startup-snapshot of `capital_pools.enabled`), decision 22 (new `DeleteCredential` use case and `DELETE /api/credentials/{exchange}` endpoint, refused unless the exchange is flat, decision 4b), decision 23 (the webhook secret is revealed only on an explicit request through its own endpoint — overrides the earlier "never rendered" text). Each changed section below carries its own "Revised 2026-09-25" note.

> **Orchestrator correction (2026-09-25, binding for tasks): F11 is NOT an accepted cost. It is fixed.** F11 argues that the worker reading `capital_pools.enabled` only at startup is safe. That holds only in the DISABLE direction. In the ENABLE direction it breaks the owner's primary flow (decision 21) without a single log line that names the cause:
> - The owner saves a key for a new exchange.
> - The exchange appears in the top bar, and a strategy is created on it.
> - But the running worker never starts `balance.sync` reads for that pool.
> - So every opening signal is refused as a stale or absent balance until someone happens to restart the worker.
>
> **Required fix:** the worker re-reads the enabled pools on every recurring cycle, at the start of each `balance.sync` run (and wherever else the in-memory `PoolConfig` map is consulted), instead of only in the lifespan. A pool enabled through Settings then gets its first balance read within one sync interval. A pool disabled through Settings stops being read on the next cycle. No restart is needed in either direction.
>
> **Test requirement:** enable a pool in the database while the worker is running, then assert that the next cycle reads its balance.
>
> This belongs in PR 3 (the degradation work) or PR 8 (`SaveCredential`), whichever lands first.

Style follows `archive/2026-09-24-book-venue-closes/design.md`. Every new component names its hexagonal layer (`rules.design`). Complex flows have sequence diagrams.

## Technical approach

This is a modular-monolith change in four layers of risk: credentials, strategy lifecycle, read-only performance, and then the API, serving and frontend on top.

1. **Credentials** (revised 2026-09-24, decision 18; revised 2026-09-25, decisions 20–22). The vault keeps its current shape: **one active key per exchange**, enforced by the existing `ux_exchange_credentials_one_active_per_exchange`. That one key signs reads and orders. Binance's read paths stop reading `.env` and load the vault key, and `.env` holds no Bybit or Binance key. Keys are validated in the API process by a key-inspection port against a pure domain policy: a live read (8a) and no withdraw permission (8b). A key that cannot trade is **accepted with a warning** and recorded as `trade_capable=false`; with `DRY_RUN=false` the opening signals of that exchange are refused up front. An exchange with an enabled pool and **no key at all is DEGRADED, not a startup refusal** (decision 20): the worker starts, logs one ERROR naming it (reaching Telegram through the existing alert bridge), attempts no balance or position read for it, and refuses its opening signals through the same up-front check as a read-only key; every other exchange, closes included, is unaffected. Saving a key also **enables that exchange's one futures pool**, in the same transaction, from a fixed constant table (decision 21); deleting a key is refused unless the exchange is disabled and flat, and disables the pool on success (decision 22).
2. **Lifecycle.** Strategies gain an `allowed_pairs` array, `archived_at`, and an append-only enablement log. The refusals reuse the existing pre-lock guard in `ProcessSignalHandler.handle()`. Archive serializes on the pool advisory lock, and `AllocateCapital` re-checks `enabled` inside that lock. Together they close the one race that could leave an archived strategy holding a position.
3. **Performance.** A new `performance/` module holds pure domain math over aggregates read from `ledger_entries` joined to `reservations`. The only write is `reservations.pool_total_at_open`. It is filled from the balance that `AllocateCapital` already reads inside the lock.
4. **Surface.** Every admin router mounts under `/api`. FastAPI serves the built SPA through a GET fallback that refuses the reserved prefixes and answers them with 404 JSON. The frontend gets React Router, a layout shell, TanStack Query hooks and three views in visual direction A.

```
 TradingView ──► DuckDNS proxy (/webhook/tradingview ONLY) ──┐
                                                             ▼
 Browser ──► Cloudflare Access ──► Tunnel ──► FastAPI 127.0.0.1:8000
                                                ├─ /webhook/tradingview   (unchanged)
                                                ├─ /health                (unchanged)
                                                ├─ /api/*   bearer token  (strategies, reconciliation,
                                                │                          pools, performance, credentials)
                                                ├─ /assets/*  static, hashed (JS, CSS, self-hosted fonts)
                                                └─ GET /*   → index.html  (never for /api, /webhook, /health)
 Worker ── vault.load(exchange) ──► venue reads (balance, positions, scan, fills) AND venue orders
        └─ trade_capable (no decrypt) ──► live opening signals refused up front on a read-only exchange
 API ───── vault.store(exchange) after KeyInspector (live read + permissions)   [seal only]
```

## Findings that correct the inputs (read these first)

These changed what the specs said. **Revised 2026-09-24:** the spec realignment is done (see § Spec realignment). F10 is removed: its claim was wrong.

| # | Input claim | What the code says | Design response |
| --- | --- | --- | --- |
| F1 | The performance spec said the pool capital is "the same `pool_balance.total` already read inside the allocation transaction to compute the requested amount". | `requested` is computed from a read made **before** the lock (`process_signal.py:503-513`). `AllocateCapital` reads the pool again **inside** the lock (`allocate_capital.py:129-133`). | Record the **in-lock** read. That satisfies rule 4, adds no new read, and is the value consistent with the decision. Spec corrected. |
| F2 | "The ledger is empty under DRY_RUN." | Not as a code property. Under DRY_RUN, `FakeExchangeAdapter.place` mints fills (`fake_exchange.py:139-150`, price 1, fee 0, id `fake-fill-<uuid>`). `SettleExecution` records them in the ledger. | Performance reads exclude rehearsal fills by the named domain constant `REHEARSAL_FILL_ID_PREFIX` (decision 12). Spec corrected: "no qualifying trades" yields the empty result. |
| F3 | The performance spec said fees are "converted to the pool's settlement currency when `fee_currency` differs". | A fee paid in the base currency is already inside the notional difference: it shrank the base that was later sold (`repository.py:56-88`, the base-fee rule). Subtracting it again double-counts it. A fee in a third currency (for example BNB) has no stored rate. | Subtract only fees in the settlement currency. A third-currency fee is flagged `fees_complete=false` and counted. There is no conversion (decision 11). Spec corrected. |
| F4 | Stats by pair used `GROUP BY symbol` over the ledger. | A booked close is written under the MARKET KEY while its open may carry `.P` (book-venue-closes decision 13). Grouping the raw symbol splits one trade across two "pairs". | Group per allocation first, then by `market_key` of the allocation (decision 11). Specs corrected. |
| F5 | Proposal/explore: the Bybit withdraw flag is "unverified". | `store_bybit_credentials.py:57,113` already refuses `"Withdraw" in permissions.Wallet` read from `/v5/user/query-api` (`read_client.py:432-444`). | The expected shape is already coded, but it has never been observed on a key that CAN withdraw. The probe keeps that as item P1 (decision 3). |
| F6 | Explore: `settings.bybit_api_key/secret` may have hidden callers. | Grepped. The only reader is `bybit/factory.py:33-47` `credentials_from_settings`, which `scripts/check_bybit_read.py:233` uses. Per CLAUDE.md this is the read-only `***Swka` key. | Remove it together with the Binance pair. **Revised 2026-09-24:** under decision 18 the `***Swka` key is simply retired; it is not stored anywhere (the vault already holds Bybit's one key). |
| F7 | Exchange-credentials spec: "refuse to start if any configured (exchange, purpose) the worker depends on is missing". | A missing key is a deliberate, documented per-exchange degradation (`main.py:454-492`). | **Revised 2026-09-24:** per exchange, not per purpose. A key is required for every exchange with an enabled Bybit/Binance pool, in both modes, because `balance.sync` reads real balances under DRY_RUN (`worker.py:114-121`) and Binance's reads now depend on the vault too. Spec corrected. **Revised 2026-09-25 (decision 20):** corrected again, the other way. The worker MUST NOT refuse to start over a missing key at all. `_vault_credential` (`main.py:454-492`) already treats a missing key as a per-exchange degradation for ORDER placement; decision 20 generalizes that same posture to balance/position reads and to startup itself: one ERROR names the exchange (reaching Telegram via the existing `AlertLogBridge`), no read is attempted for it, and its opening signals are refused by decision 4a's `NO_KEY` case. Spec corrected again. |
| F8 | Strategy-lifecycle spec: "creating with `enabled=true` writes the first event". | POST cannot create an enabled strategy (`strategies/infrastructure/router.py:8-12`). | `RegisterStrategy` still appends the event if `enabled` is ever true, as defensive code. Spec corrected: creation writes no event; the first enable writes the first one. |
| F9 | — | The master key is symmetric AES-GCM (`crypto.py:63-72`), so "encrypt-only in the API process" cannot be a cryptographic boundary. It is also already in the API process's memory, because both processes load the same `Settings`/`.env` (`config.py:84`). | Decision 5 states the actual boundary honestly: a seal-only port, enforced by typing and a structural test. |
| F11 (added 2026-09-25, decisions 21–22) | — | `capital_pools.enabled` reaches the worker's own allocation path exactly once, at startup: `CapitalPoolRepository.list_enabled()`, loaded in `main.py`'s lifespan into the in-memory map `PoolBalanceAdapter` reads from (`pool_balance_adapter.py:15-42`). An already-running worker never re-reads it. | The flag is panel-visible, live bookkeeping, not the mechanism that blocks a keyless exchange's opens: that is decision 4a's per-signal `exchange_credentials` read, which is unaffected by the worker's snapshot. `GET /pools` (API-side, `SqlAlchemyPoolOverview`) also reads the table live, so the panel is never stale. **Accepted cost**, stated under decision 4b: a pool enabled or disabled through Settings takes full effect in the worker's own snapshot only after its next restart; nothing unsafe follows from the delay, because the credential write alone already refuses every opening signal on that exchange from the next signal on. |

**Removed 2026-09-24 — former F10.** It claimed the `operator-panel` and `capital-allocation` specs were missing. Both exist (`specs/operator-panel/spec.md`, `specs/capital-allocation/spec.md`). What the capital-allocation delta actually lacked, the in-lock strategy re-check (decision 8) and the read-only refusal (decision 4a), has been added to it.

## Component inventory, with hexagonal layer

**Revised 2026-09-24:** `CredentialPurpose` and every purpose-keyed port are gone; `trade_capable` and the trade-capability port are new.

**Revised 2026-09-25 (decisions 21–23):** `KNOWN_FUTURES_POOLS`, `CapitalPoolWriterPort`, `DeleteCredential`, `PoolExposurePort` and the webhook-secret router are new.

| Component | Layer | Notes |
| --- | --- | --- |
| `trade_capable`, `validated_at`, `permissions` on `ExchangeCredential` / `CredentialHint` | **domain**/accounts (`exchange_credential.py`) | `trade_capable` has no default: every constructor call names it |
| `PermissionSnapshot`, `KeyVerdict`, `evaluate_key(snapshot)` | **domain**/accounts (`key_policy.py`) | Pure. Rules 8(a)–8(b) and the trade-capability derivation live here once, used by the API and the scripts |
| `CredentialVaultPort.load(exchange)`, `hints()` (unchanged signatures); `CredentialWriterPort.store(...)`, `hints()`; `KeyInspectorPort`, `KeyInspectorRegistryPort` | **application**/accounts (`ports.py`) | The writer port has no `load`. That is the API's seal-only boundary |
| `SaveCredential` | **application**/accounts | Inspect → evaluate → store (supersede) → commit |
| `SqlAlchemyCredentialVault` (snapshot-aware), `BybitKeyInspector`, `BinanceKeyInspector`, `KeyInspectorRegistry` | **infrastructure**/accounts | Inspectors call a GET balance read plus permission introspection, never an order |
| `TradeCapabilityPort`, `TradeCapability` (`TRADE_CAPABLE` \| `READ_ONLY` \| `NO_KEY`) | **application**/signals (`process_signal.py` ports) | What the signal path asks before an open (decision 4a) |
| `VaultTradeCapabilityAdapter` (reads `exchange, trade_capable WHERE is_active`, never decrypts), `DryRunTradeCapability` (always `TRADE_CAPABLE`) | **infrastructure**/accounts (`trade_capability_adapter.py`) | Chosen in `main.py` by DRY_RUN, like the exchange adapters |
| `pools_router` (`/api/pools`), `credentials_router` (`/api/credentials`, now also `DELETE`), `SqlAlchemyPoolOverview` | **infrastructure**/accounts | |
| `KNOWN_FUTURES_POOLS` (`bybit`, `binance` → `venue`, `settlement_currency`, `default_min_order_size`) | **domain**/accounts (`known_pools.py`) | Decision 21. The one place naming which pool a saved key enables and its starting minimum; never user input |
| `CapitalPoolWriterPort.enable(exchange)`, `.disable(exchange)` | **application**/accounts (`ports.py`) | Decision 21/22. `enable` upserts from `KNOWN_FUTURES_POOLS`; `disable` flips only the existing row |
| `SqlAlchemyCapitalPoolWriter` | **infrastructure**/accounts | |
| `DeleteCredential` | **application**/accounts | Decision 22 (4b). Pool-wide exposure check → deactivate credential → disable pool, inside the pool's advisory lock |
| `PoolExposurePort.exposure(pool)` | **application**/accounts | Decision 22. Same shape as `StrategyExposurePort` (decision 8), widened from one strategy to every strategy bound to the pool |
| `PoolExposureAdapter` | **infrastructure**/accounts | Reuses `ReadSymbolHoldings`, reservations and attempts like `StrategyExposureAdapter`, without a strategy filter |
| `webhook_secret_router` (`GET /api/webhook-secret`) | **infrastructure**/signals (`webhook_secret_router.py`, beside the existing `webhook_secret_invariant.py`) | Decision 23. The only place `settings.webhook_secret` is ever returned |
| `AllowedPairs` VO, `archived_at` on `Strategy`, `EnablementEvent`, `EnablementOrigin`, `uptime(events, now)` | **domain**/strategies (`allowed_pairs.py`, `enablement.py`) | `AllowedPairs` asserts entries are non-empty and upper-case. Normalizing is application work |
| `ArchiveStrategy`, `ReplaceAllowedPairs`; changed `UpdateStrategy` and `RegisterStrategy`; `EnablementLogPort`, `StrategyExposurePort`, `PoolLockPort` | **application**/strategies | |
| `SqlAlchemyEnablementLog`, `StrategyExposureAdapter`, `PoolLockAdapter`, `StrategyEnablementEventRow` | **infrastructure**/strategies | The exposure adapter composes ledger `ReadSymbolHoldings`, reservations and attempts, following the `InFlightWorkAdapter` precedent |
| `market_key()` moved beside `strip_contract_marker` | **domain**/execution (`market_symbol.py`) | `reconciliation/application/market_key.py` becomes a re-export, so existing imports are unchanged |
| `REHEARSAL_FILL_ID_PREFIX = "fake-fill-"` | **domain**/execution (`fill.py`) | Minted by `FakeExchangeAdapter` and excluded by performance reads |
| `StrategyPolicySnapshot.archived`, `.allowed_pairs`; in-lock re-check in `AllocateCapital` | **application**/allocation | |
| `pool_total_at_open` on `Reservation` | **domain**/allocation (`reservation.py`) | `Decimal \| None`. `None` only on rows written before 0025 |
| Archived, allowlist and read-only-exchange refusals | **application**/signals (`process_signal.py`) | Named refusal methods, one WARNING each |
| `ClosedTrade`, `derive_trade()`, `daily_returns()`, `compound()`, `drawdowns()`, `monthly_grid()`, `range_summary()`, `by_pair()` | **domain**/performance (NEW module) | Pure `Decimal`, no I/O |
| `AllocationFillsSourcePort`, `ReadPoolPerformance`, `ReadStrategyPerformance`, `ReadStrategyTrades` | **application**/performance | |
| `SqlAlchemyAllocationFillsSource`, `performance_router` (`/api/performance`) | **infrastructure**/performance | The only place that joins `ledger_entries` to `reservations` |
| `api_router` (`/api` prefix), `mount_panel()` (static + fallback + security headers), `redacted_validation_handler` | **infrastructure**/shared (`shared/infrastructure/spa.py`, `validation_errors.py`) + `main.py` | |
| `scripts/check_key_permissions.py` | dev tool, GET-only | Unit 1a |
| `app/router.tsx`, `shared/layout/*`, `shared/api/*`, `shared/scope/exchange-store.ts`, `shared/charts/*`, `features/{overview,strategies,settings,bookings}` | frontend | See § Frontend architecture and § Visual design |

**Why a `performance/` module and not `ledger/`.** Rule 6 makes PnL a query over the ledger. The denominator, though, lives on `reservations` (allocation), and the spec treats `performance-reporting` as a capability of its own. Putting it in `ledger/` would make the ledger depend on allocation's table. A read-side module that reads through its own port follows the precedent reconciliation already set, and it names the capability at the top level (screaming).

## Decisions

### 1. One key per exchange: the vault schema stays

> **Revised 2026-09-24 (decision 18).** Replaces "Vault `purpose`: migration 0024". There is no `purpose` column, no per-purpose unique index, no refusing downgrade over READ rows, and no `--purpose` argument on any script.

**Choice**: keep `exchange_credentials` as it is, with `ux_exchange_credentials_one_active_per_exchange` as the one-active rule. `load(exchange)`, `store(credential)` and `hints()` keep their signatures. The only schema change to credentials is the save-time snapshot (migration **0026**, decision 4).

**Why** (the owner's reasoning in decision 18, confirmed against the code):
- Both keys would sit in the same vault, sealed by the same master key, decrypted by the same worker. The split bought separation of *use*, not of *exposure*.
- 8(b) already rules out withdrawal on every key, so the worst a leaked key can do is trade, and a read key would have lived beside the trade key anyway.
- Bybit already runs on one key today (`main.py:681,742,808,919,1024,1098` all load `vault.load(BYBIT_EXCHANGE)`).
- It removes the purpose migration, the 12-site rewiring, the "old worker must not run while READ rows exist" deploy hazard (`credential_vault.py:118-125` uses `scalar_one_or_none`), and rule 8(c)'s dependence on venue flags that the probe had not yet proven.

**Accepted cost** (decision 18): the trade-capable key is decrypted for every read, not only when placing orders.

**Rejected**: the READ/TRADE split (former decision 1–2), for the reasons above.

### 2. Binance reads move into the vault; `.env` holds no Bybit or Binance key

> **Revised 2026-09-24 (decision 18).** Replaces "Rewiring every venue call". Only Binance's five read sites change; Bybit's are already on the vault.

The five Binance read sites stop calling `binance_credentials_from_settings(settings)` and load the vault key, with the exact lazy pattern Bybit's read factories already use (`main.py:739-751`):

| Site | Today | After |
| --- | --- | --- |
| `main.py:756` balance refresh Binance | `.env` | `vault.load(BINANCE_EXCHANGE)` inside the lazy factory |
| `main.py:822` venue position Binance | `.env` | same |
| `main.py:960` balance sync Binance | `.env` | same |
| `main.py:1039` reconciliation scan Binance | `.env` | same |
| `main.py:1119` booking prepare Binance | `.env` | same |
| Bybit read sites (`742`, `808`, `919`, `1024`, `1098`) and both `exchange_for` sites (`681`, `693`) | vault | unchanged |

**Why the lazy readers stay correct.** The factories run only when their exchange is asked for (`main.py:737-769`, `803-839`). A missing or undecryptable Binance key raises inside the factory and degrades through FALLBACK/UNAVAILABLE and AMBIGUOUS exactly as a missing Bybit key does today. No other key is tried.

**Which Binance key serves the reads.** The vault's active Binance key, which today is the trade key `exchange_for` already signs orders and settlement `userTrades` with (`main.py:693`, `binance/trade_client.py:62`). The `.env` read key is **retired, not stored**: storing it would supersede the trade key under the one-active rule and turn Binance read-only. The probe's P4 (decision 3) proves the vault key performs every Binance read GET before PR 3 deploys.

**Startup self-test.** `_assert_sealed_credentials_open` is unchanged (it already opens every active row by exchange).

> **Revised 2026-09-25 (decision 20).** Replaces the refusal below entirely. A new `_assert_keys_present(hints, pools) -> frozenset[str]` **does not raise**. For every exchange in `{bybit, binance}` that has an enabled pool and no active credential, it calls `logger.error(...)` naming the exchange and how to store a key (panel Settings or `scripts/store_<exchange>_credentials.py`). `AlertLogBridge` already forwards every ERROR to Telegram (`shared/infrastructure/alert_log_bridge.py`) — the same channel the "`balance.sync` dead for three days" defect exists to fix, so this reuses it rather than adding a second alerting path. It returns the set of DEGRADED exchange names, which the caller (`main.py`) uses to skip registering `RefreshPoolBalance`/venue-read adapters for them, leaving their `ExchangePort` unregistered exactly as `_vault_credential` already does for order placement (`main.py:454-492` — decision 20 generalizes that existing per-exchange-degradation posture from orders to reads and to startup itself). No balance or position read is attempted for a DEGRADED exchange; every other exchange starts and trades normally, closes included. **Both modes still apply** (F7): under DRY_RUN, `balance.sync` still reads real balances, so a DEGRADED exchange gets no reads under DRY_RUN either. The empty-vault allowance is unchanged: no Bybit/Binance pool enabled at all is still not an error. In practice a DEGRADED exchange with an open position arises only from a fresh deployment before any key is ever saved, or a manual database edit — decision 22's flat precondition on `DELETE /credentials/{exchange}` (§ 4b) stops the ordinary UI path from ever reaching that state on a pool that already has a position open. See F11 for what `capital_pools.enabled` toggling does and does not make visible to an already-running worker.

**Removed**: `Settings.bybit_api_key/secret` and `binance_api_key/secret` (`config.py:117-118,137-138`), plus `credentials_from_settings` in `bybit/factory.py:33-47` and `binance/factory.py:29-40`. `extra="ignore"` means stale values left in `.env` do not break startup (rollout removes them). `CredentialNotFound`'s message stops naming `store_pionex_credentials.py` and names the exchange's own store script.

**Pionex carve-out.** Pionex `.env` keys and `pionex/factory.py:37` stay: no Pionex adapter is registered (`main.py:538-543`), their only readers are Pionex diagnostic scripts, and the spec's settings rule is scoped to Bybit and Binance. Recorded as a deliberate carve-out, not an oversight.

**Scripts**: `probe_credentials.vault_credentials(settings, exchange)` is the one loader, and `announce()` prints `***last4 (vault)`. `check_bybit_read`, `check_binance_read`, `measure_reconciliation_rate_limits` and `check_venue_fill_windows` switch from `.env` to it. The store scripts keep their current behaviour until PR 8 folds them onto `SaveCredential` (decision 4), where they adopt "accepted with a warning" for keys that cannot trade.

### 3. Unit 1a: the permission probe, `backend/scripts/check_key_permissions.py`

> **Revised 2026-09-24.** Scope reduced by decision 18: the READ/TRADE capability rules (old P2/P3 slot rules), the account-identity item (old P5, for OQ4) and the "does a Binance read key read futures with `enableFutures=false`" question are gone. What remains is the Bybit withdraw flag, how to detect trade capability per venue, Binance `apiRestrictions`, and proof that the Binance vault key serves every Binance read.

GET-only, and it places nothing. It runs on the VPS, because the keys are IP-bound there. It loads the Bybit and Binance keys from the vault, and, for their last use before removal, the Bybit (`***Swka`) and Binance read keys from `.env`; optionally `--prompt` for a key stored nowhere (via `getpass`). Before each call it prints `Signing as ***last4 (source)`.

It **never prints a secret**. Bybit's `query-api` payload echoes `apiKey`, so the probe redacts every field named `apiKey`/`secret`, and any string equal to the key or the secret, down to the last 4. A unit test pins the redaction.

| Item | Call | Gates |
| --- | --- | --- |
| P1 Bybit withdraw shape | `GET /v5/user/query-api` → `permissions.Wallet` | 8(b) for Bybit. If `Wallet` lists `Withdraw` for a key that has it (optional step: the owner creates a throwaway key with Withdraw, IP-bound, probes it and deletes it), the rule is `"Withdraw" in Wallet`. If not observable, it goes back to the owner before PR 8 |
| P2 Bybit trade capability | same call → `readOnly`, `permissions.ContractTrade`, `permissions.Derivatives` on the vault key (can trade) and on `***Swka` (cannot) | Which field proves "can trade linear perpetuals". Expected: `readOnly == 0` and the linear-perpetual permission non-empty; P2 records which of `ContractTrade`/`Derivatives` carries it on this UTA account |
| P3 Binance restrictions | `GET /sapi/v1/account/apiRestrictions` on the vault key and the `.env` read key | 8(b): `enableWithdrawals`. Trade capability: `enableFutures`. Shown only: `enableInternalTransfer`, `permitsUniversalTransfer`, `ipRestrict` |
| P4 live reads | Bybit `wallet-balance UNIFIED` (the 8(a) read); Binance, **with the vault key**: `GET /fapi/v3/account`, `/fapi/v3/positionRisk`, `/fapi/v1/symbolConfig` | 8(a) per venue. **Gates PR 3's deploy**: every Binance read GET that moves from the `.env` key to the vault key must succeed with the vault key first (`userTrades` already runs on it in settlement) |
| P5 binding / expiry | Bybit `ips`, `expiredAt`, `deadlineDay`; Binance `ipRestrict`, `tradingAuthorityExpirationTime` | Shown in Settings as snapshot fields |

The output is pasted into `tasks.md` § Probe results. **No rule in `key_policy.py` is written before that section exists**, the book-venue-closes unit 2a precedent.

### 4. Key validation flow

> **Revised 2026-09-24 (decision 18).** One slot per exchange; rule 8(c) and its two refusals are removed; a key that cannot trade is accepted with a warning. Migration renumbered 0027 → **0026**, and it now also adds `trade_capable`.
>
> **Revised 2026-09-25 (decision 21).** `SaveCredential` also enables that exchange's one futures pool, in the SAME transaction as the credential write, through a new `CapitalPoolWriterPort.enable(exchange)`. The pool's identity — `(venue, settlement_currency)` — and the `min_order_size` a newly-created row gets both come from one fixed constant, `KNOWN_FUTURES_POOLS` (`accounts/domain/known_pools.py`): `{bybit: (usdt-m, USDT), binance: (usdt-m, USDT)}`, one linear/USDT-margined perpetual pool per exchange, never taken from the request body. Bybit's and Binance's usdt-m/USDT rows already exist (migrations 0017/0018), so `enable` on either today only flips `enabled` to `true` if it was `false` and leaves the row's configured `min_order_size` untouched; a row that does not exist yet is inserted with `enabled=true` and `min_order_size` from the same constant's `default_min_order_size` field, so there is exactly one place that names both a pool's identity and its starting minimum. There is no pool-management endpoint or screen: the owner activates a pool only by saving a key, never directly. See F11 for what this write does and does not make visible to an already-running worker.

```
Browser           API (credentials_router)     SaveCredential          KeyInspector(venue)        Vault (seal only)
  │ PUT /api/credentials/bybit       │                  │                       │                        │
  │ {api_key, api_secret(SecretStr)} │                  │                       │                        │
  ├─────────────────────────────────►│ save(cmd) ──────►│ inspect(key,secret) ─►│ GET wallet-balance     │
  │                                  │                  │                       │ GET query-api          │
  │                                  │                  │◄── PermissionSnapshot ┤ (timeout 10s)          │
  │                                  │                  │ evaluate_key(snapshot)  [domain, pure]          │
  │                                  │                  │  refuse? ─► KeyRefused(outcome) ─► 422 {outcome,detail,permissions}
  │                                  │                  │ store(credential, snapshot, trade_capable) ────►│ deactivate (exchange)
  │                                  │                  │                                                 │ seal (row-id context) + insert
  │                                  │                  │ CapitalPoolWriterPort.enable(exchange)          │  (decision 21; own table, same txn)
  │                                  │                  │ commit                                          │
  │◄── 200 {exchange,last4,trade_capable,permissions,validated_at,warnings} ────────────────────────────────┘
```

- **8(a)** A venue auth failure (Bybit `retCode` 10003/10004/33004, Binance -2014/-2015/-1022) → `KEY_REJECTED`, 422. A network error, timeout or venue 5xx → `VENUE_UNREACHABLE`, 502. Nothing is stored in either case.
- **8(b)** `can_withdraw` → `WITHDRAW_PERMISSION`, 422. `can_transfer_internal` (Bybit `AccountTransfer`, Binance `enableInternalTransfer`/`permitsUniversalTransfer`) is allowed and shown.
- **Trade capability** is derived, never a refusal: Bybit `readOnly == 0` and the linear-perpetual permission non-empty (exact field per probe P2); Binance `enableFutures == true` (P3). `trade_capable=false` → stored, 200 with `warnings: ["READ_ONLY_KEY"]`.
- **Migration 0026** adds to `exchange_credentials`: `permissions JSONB NULL`, `validated_at timestamptz NULL`, `CHECK ((permissions IS NULL) = (validated_at IS NULL))`, and `trade_capable boolean NOT NULL`, added with `DEFAULT true`, backfilled, and then the **default dropped**.
  - **The backfill to `true` is correct by construction.** Every existing row was sealed by a `store_*_credentials.py` that refuses keys that cannot trade (`store_bybit_credentials.py:136-143`, `store_binance_credentials.py:137-144`). Pionex rows are backfilled too; nothing reads them.
  - **The default is dropped on purpose.** An insert that forgets `trade_capable` must fail. Defaulting to `true` would let a read-only key through to the venue, the failure decision 18 moves up front.
  - **The downgrade refuses while any row has `trade_capable = false`**, naming the count: dropping the column would make a read-only key look trade-capable to nothing and silently lose the fact. The 0013 precedent: the owner deletes rows by hand if that is really wanted.
- Rows sealed before 0026 show `permissions: null`, rendered as "not validated", and `trade_capable: true`.
- The snapshot is what Settings shows later. There is never a live re-query, which would need the API process to decrypt (spec).
- Concurrent saves for one exchange: the second `UPDATE ... WHERE is_active` does not see the first's insert, so its insert violates `ux_exchange_credentials_one_active_per_exchange`. The `IntegrityError` on **that index name** becomes 409 `CONCURRENT_SAVE`. Any other `IntegrityError` propagates, the book-venue-closes rule on catching by constraint name.
- **Rotation is live.** The worker loads per job, so the next job signs with the new key and no restart is needed.
- **Replacing a trade-capable key with a read-only one is allowed** (decision 18). The response's warning and the Settings card say what it costs: live opening signals for that exchange are refused from the next signal on; closes still go to the venue and will fail there until a trading key returns.

### 4a. Read-only keys: refused up front for live opening signals

> **Added 2026-09-24 (decision 18).**

**Where the check lives**: `ProcessSignalHandler._refuse_read_only_exchange`, at the top of `_handle_consumes`, immediately **after** the unlisted-pair refusal (decision 7) and **before** the Existing-Position Guard, the balance refresh and the lock. Because `open_now()` also enters `_handle_consumes`, the REVERSE continuation is covered: the close runs, the open half is refused, the strategy ends flat.

**How trade capability is known**: from the value recorded at save time, through `TradeCapabilityPort.capability(exchange) -> TradeCapability`. `VaultTradeCapabilityAdapter` answers with one indexed read of `exchange_credentials (exchange, trade_capable) WHERE is_active`; it **never decrypts**. It does not depend on the probe at signal time: the probe (P2/P3) only decides which venue field `evaluate_key` reads when the value is recorded.

| Capability | `DRY_RUN=false` | `DRY_RUN=true` |
| --- | --- | --- |
| `TRADE_CAPABLE` | proceeds | proceeds |
| `READ_ONLY` | refused, one WARNING: `signal <id> for strategy <name> refused: the active <exchange> key cannot trade; store a key that can trade futures (Settings)` | proceeds (`DryRunTradeCapability` is wired; the fake exchange places nothing) |
| `NO_KEY` | refused, one WARNING naming the exchange: `signal <id> for strategy <name> refused: <exchange> has no active key; store one (Settings)` | proceeds |

> **Revised 2026-09-25 (decision 20).** The `NO_KEY` row's WARNING is no longer defensive: decision 20 removes the startup refusal, so this check is now the SOLE, ordinary mechanism that refuses a live open on a DEGRADED exchange. It also does the work decision 22's key deletion needs: whether the key was deactivated by `DeleteCredential` (§ 4b) or never existed, this is the same live read, with no lock and no cache, and it refuses from the very next signal.

**Closes are never refused by this rule** (decision 18 scopes it to opening signals): refusing a close strands the position, the same reasoning as decision 7.

**The residual race, accepted.** A key replaced by a read-only one, or deleted outright, between this check and `PlaceOrder` fails at the venue (or, for a deletion, fails locally with `CredentialNotFound`) as any refused write does today (`AUTH_UNAVAILABLE`); the reservation is released the same way an unplaceable open's reservation already is. The check is an early refusal, not a guarantee, and it needs no lock — which is exactly why `DeleteCredential` (§ 4b) does not need to serialize against THIS check either: whichever of the two commits its own write first is what the other observes.

**Rejected**: asking the venue at signal time (a network call on the hot path, against the TradingView 3 s budget's spirit and the "ingress never trades" rule's intent), and refusing at ingress (the webhook performs no lookup, rule 3).

### 4b. Deleting a key: refused unless the exchange is flat, pool disabled on success

> **Added 2026-09-25 (decision 22).**

**Endpoint**: `DELETE /api/credentials/{exchange}`. **Use case**: `DeleteCredential`, application/accounts.

Preconditions, both must hold:
- no strategy bound to that exchange's one pool is currently enabled;
- the pool holds no open exposure: no allocation with ledger net ≠ 0 (all spellings merged), no live reservation (`PENDING`/`SUBMITTED`, `terminal_at NULL`), no `SUBMITTED` in-flight attempt (opens via `reservation.strategy_id`, closes via `closes_allocation_id` → reservation) — decision 8's `StrategyExposurePort` query shape, widened from one strategy to every strategy bound to the pool.

```
DELETE /api/credentials/{exchange}
DeleteCredential ─ SELECT exchange_credentials WHERE exchange=... AND is_active FOR UPDATE ─┐
   no active row? ─► 404 CREDENTIAL_NOT_FOUND
   pg_advisory_xact_lock(LockKey(pool)) ─────────────────────────────────────────────────────┤ same key ArchiveStrategy and AllocateCapital take
   PoolExposurePort.exposure(pool):                                                          │
     any strategy on pool with enabled=true                                                  │
     ledger net ≠ 0 per allocation (ReadSymbolHoldings, all spellings merged)                 │
     live reservations                                                                        │
     SUBMITTED in-flight attempts                                                             │
   any? ─► 409 EXCHANGE_NOT_FLAT {enabled_strategies, symbols, allocations, live_reservations, in_flight_attempts}
   deactivate the active row (history kept -- there is no replacement key to insert,
     unlike a rotation's supersede, decision 4)
   CapitalPoolWriterPort.disable(exchange)
   commit  (lock released) ──────────────────────────────────────────────────────────────────┘
```

**Why the pool lock.** The exposure check reads across every strategy bound to the pool, and the write disables the pool itself — the same resource `AllocateCapital` and `ArchiveStrategy` already serialize on (decision 8). Taking a narrower lock (or none) would reopen exactly the race decision 8 closed for one strategy, this time exchange-wide: an allocation that wins the lock first commits its reservation and is then correctly seen by the exposure check and refuses the delete; an allocation that has not yet reached the lock either sees `NO_KEY` from decision 4a's check before it ever tries (because the credential row is already deactivated by the time it looks), or wins the race to the lock and proceeds — in which case its later `PlaceOrder` hits the accepted residual race described in decision 4a, exactly as a mid-flight rotation does.

**Replacing a key is unaffected.** A `PUT` that supersedes an active key (rotation, decision 4) never runs this precondition; only `DELETE` does. Saving a new key for an exchange whose pool was disabled by a prior delete re-enables it (decision 21's upsert), exactly like a first save.

**The `capital_pools.enabled` write and the worker.** Per F11, the worker's own allocation path reads `capital_pools` once, at startup. `DeleteCredential`'s write is correct and immediately visible to `GET /pools` and to decision 4a's per-signal credential check — both of what actually refuses a live open and what the panel shows. It is not immediately visible to an already-running worker's in-memory `PoolConfig` map. This is an accepted rollout cost, not a race: the credential deactivation alone already refuses every opening signal on that exchange from the next signal on, regardless of whether the worker has reloaded its pool snapshot.

**Response**: 200 with the exchange's `GET /credentials` entry now `status: EMPTY` (last4/permissions/trade_capable all `null`) — the same shape an exchange that was never keyed already returns.

**Rejected**: refusing the delete only on `enabled` and ignoring open exposure — decision 14's same reasoning as archive: a position stranded with no key left to close it is unrecoverable through this app. Also rejected: deleting the row outright — decision 22 keeps history, following decision 4's rotation precedent (a supersede never deletes either).

### 5. Where encryption happens: in the API process, seal-only by type

**Choice**: the API process validates and seals. `SaveCredential` depends on `CredentialWriterPort` (`store`, `hints`), which has **no `load`**, so mypy strict makes a decrypt from the API path a type error. A structural test asserts that no module under `accounts/infrastructure/credentials_router.py` or `accounts/application/save_credential.py` references `.load(`. The API lifespan gains **startup invariant 5**: `EnvelopeCipher.from_base64(settings.master_encryption_key)` must succeed, so a misconfiguration fails at boot, as it does in the worker (`main.py:632`).

**What this does and does not protect, stated plainly (F9).** AES-GCM is symmetric, so any holder of the master key can decrypt. The API process already holds the key in memory today, because it loads the same `Settings` from the same `.env`. This design **changes the key's use, not its exposure**. The boundary is code discipline enforced by types, not cryptography. The new key's plaintext is in API memory during validation no matter where it is sealed, because the live read needs it.

**Rejected**:
- **Hand the plaintext to the worker as a job.** It persists a plaintext secret in `jobs.payload`.
- **Hand the worker a job sealed with the master key.** The API needs the key anyway.
- **Asymmetric sealing** (the API holds a public key, the worker the private one). This is the only option that makes "API cannot decrypt" true. It needs a second envelope scheme, re-sealing every row, and separate env files per process so the API never loads the symmetric key. It is recorded as a follow-up hardening, not built here.
- **A synchronous API→worker RPC.** No channel exists, and building one is a new process-integration surface.

### 6. Allowed pairs: an array column, migration 0024

`strategies.allowed_pairs TEXT[] NOT NULL DEFAULT '{}'`, `CHECK (array_position(allowed_pairs, NULL) IS NULL)`. The domain holds `AllowedPairs(frozenset[str])`, which is stored sorted.

**Choice over a child table.**
- The allowlist is read on the hot path in the SAME row snapshot as `enabled` and `archived_at` (`policy_adapter.py:24-37`, one `session.get`).
- The panel replaces the list as a unit (PUT).
- Nothing per pair was asked for.
- A child table adds a second query to `policy_for`, and a place where the list and the flags can be read at different instants, for metadata nobody requested.
- Per-pair stats do not need it (F4).

**Rejected**: `strategy_allowed_pairs(strategy_id, pair)`. It becomes worth it the day a per-pair setting exists, and migrating the array into it then is mechanical.

**Normalization.** Pairs are stored as `market_key()`: marker stripped, upper-cased. `market_key` moves into `execution/domain/market_symbol.py`, and the reconciliation module re-exports it. The application layer (`ReplaceAllowedPairs`, `RegisterStrategy`) normalizes. The domain VO only asserts that entries are non-empty, upper-case and free of whitespace. Note that `BTC_USDT_PERP` → `BTC_USDT` and `BTCUSDT.P` → `BTCUSDT`. That is correct, because pools are per exchange and each exchange has one spelling family.

**Seeding (decision 13).** 0024 selects `DISTINCT strategy_id, symbol FROM signals` and normalizes in Python with a **frozen copy** of the normalization inside the migration. Migrations must not import application code that can change later. It writes each list and logs `seeded allowed pairs for <id> (<name>): [...]` at WARNING, so it shows in `alembic upgrade` output. A strategy with no signals is seeded empty (spec).

**The ≥1 rule** is application-level (`RegisterStrategy`, `ReplaceAllowedPairs`), not a DB CHECK, because seeded rows may legitimately be empty.

### 7. Where the allowlist applies: opens only (confirmed, decision 15)

> **Revised 2026-09-24.** OQ1 is resolved by owner decision 15; this section no longer blocks unit 5a.

**Choice**: the allowlist gates the **opening effect** (`CONSUMES`). The check is `_refuse_unlisted_pair` at the top of `_handle_consumes`, before the read-only-exchange refusal (decision 4a), the Existing-Position Guard, the balance refresh and the lock. It therefore covers both `handle()` and the `open_now()` continuation.

A **releasing** signal is never refused by the allowlist. When the pair is no longer listed, it logs one WARNING and closes anyway. A REVERSE on an unlisted pair closes and then refuses the open, ending flat.

**Why not gate every signal.** A close for an unlisted pair exists only because the pair WAS listed when the position opened. Refusing it strands the position, which is exactly what decision 14 was taken to prevent for archive. Making "gate everything" safe would need a serialization the schema cannot express: a reservation carries no symbol (`ReservationRow` has none), so between `AllocateCapital`'s insert and `PlaceOrder`'s attempt nothing records which pair an in-flight open is for. Gating opens only removes the race instead of guarding it.

### 8. Archived strategies: refusal, archive preconditions and the race

**Signal refusal (decision 11).** It runs in `handle()` immediately after `policy_for`, **before** the untradable-pool check: the owner's instruction for a retired strategy is "remove the alert", whatever its pool. It also runs in `open_now()`. The WARNING reads `signal <id> for ARCHIVED strategy <name> (<id>) refused; remove its TradingView alert`. The webhook is untouched (`ingest_signal.py` performs no lookup), so ingest-level idempotency still deduplicates replays.

**Archive preconditions (decision 14)** live in `ArchiveStrategy.archive(id)`:

```
PATCH enabled=false (earlier, separate request)
                                  POST /api/strategies/{id}/archive
ArchiveStrategy ─ SELECT strategies ... FOR UPDATE ─┐
   archived already? ─► 200 (idempotent, same archived_at)
   enabled? ─► 409 STILL_ENABLED
   pg_advisory_xact_lock(LockKey(pool)) ────────────┤  same key AllocateCapital takes
   StrategyExposurePort.exposure(strategy, pool):   │
     ledger net ≠ 0 per allocation (ReadSymbolHoldings, all spellings merged, every allocation)
     live reservations  (status PENDING|SUBMITTED, terminal_at NULL)
     SUBMITTED attempts (opens via reservation.strategy_id, closes via closes_allocation_id → reservation)
   any? ─► 409 OPEN_POSITION {symbols, allocations, live_reservations, in_flight_attempts}
   archived_at = now; commit  (lock released) ──────┘
```

**The race this closes.** Take a signal job that read `enabled=true` **pre-lock** (`allocate_capital.py:102-110`). If the owner then disables and archives it before the job reaches the lock, the job would reserve and open a position on an archived strategy. Every later signal for it is refused, so the position would be stranded.

Two pieces close it:
- (i) Archive holds the pool lock while checking and writing.
- (ii) **`AllocateCapital` re-reads the policy inside the lock**, right after `acquire` and before the balance read, and skips with `STRATEGY_DISABLED` / `STRATEGY_ARCHIVED` if the strategy is no longer enabled or is archived.

Either the allocation commits first, in which case archive waits on the lock and then sees the live reservation and refuses, or archive commits first, in which case the allocation's in-lock re-read sees `enabled=false` and skips. The extra read is one local row read and takes no new lock. Rule 4 concerns availability and is untouched. (Now also in the `capital-allocation` delta, revised 2026-09-24.)

**Rejected**: checking "flat" without the lock, because the window above is real. Also rejected: a lock on the strategy row alone, because the signal path never locks that row. Proven by a **live-PostgreSQL concurrency test** (`rules.tasks`).

- **Dust counts as open.** A residual that `ClosePosition` reports `NOT_CLOSABLE` (`close_position.py:157-183`) keeps the ledger net ≠ 0, so archive refuses and names it. A human resolves it on the venue, and the booking flow brings the ledger to flat. This follows decision 14 literally.
- **DB guarantee**: `CHECK (archived_at IS NULL OR enabled = false)`.
- **Archived strategies are read-only.** Any PATCH, and any pairs PUT, → 409 `STRATEGY_ARCHIVED`. That is stricter than the spec's "enabling refused", and simpler: archive is terminal, following the `terminal_at` precedent.
- **Lists** exclude archived by default (`?include_archived=true` includes them). The detail endpoint always loads.

### 9. Enablement event log and uptime

The table is `strategy_enablement_events(id uuid pk, strategy_id FK strategies NOT NULL, enabled bool NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now(), origin text NOT NULL CHECK IN ('OBSERVED','BASELINE'))`, with index `(strategy_id, occurred_at)`. It ships in migration **0024** with the rest of the lifecycle schema.

- **Written** in `UpdateStrategy`, which now takes `SELECT ... FOR UPDATE` on the strategy row. Two concurrent toggles otherwise both read `false` and both append an "enabled" event. An event is written **only when the value changes**, in the same transaction as the `enabled` write. `UpdateStrategy` gains a `ClockPort`.
- **Creation writes no event** (F8): the API always creates disabled. `RegisterStrategy` appends one defensively if `enabled` is ever true.
- **Append-only**: a `BEFORE UPDATE OR DELETE` row trigger with its own function, `fn_strategy_enablement_events_append_only`. There is deliberately **no TRUNCATE trigger**, unlike the ledger. Eight integration conftests `TRUNCATE strategies ... CASCADE` (for example `tests/strategies/infrastructure/conftest.py:93`), and a TRUNCATE guard would break every Tier B suite. The threat to an audit trail is an application bug updating or deleting a row, not an operator truncating. The ledger keeps the stronger guard because it is money.
- **Before the log existed.** 0024 writes one `BASELINE` event at migration time for every strategy enabled at that moment. For strategies disabled then, prior uptime is lost, and the design says so rather than inventing it. `uptime()` returns `{seconds, first_enabled_at, baseline}`, where `baseline=true` means the first event is BASELINE, so the UI renders "active ≥ X days, since at least <date>".
  - **Rejected**: back-dating from `strategies.updated_at` (it moves on any rename) or from the first reservation (that is a lower bound on activity, not on enablement).
- **Uptime is a pure domain function**: sum `(next event or now) − enable` over enable events, ignoring repeated same-state events defensively. It is never stored (spec).
- **Downgrade** refuses while any OBSERVED event exists, the 0012/0021 precedent. BASELINE rows carry no information the migration did not create.

### 10. Pool capital at open: migration 0025

`reservations.pool_total_at_open Numeric(38,18) NULL`, `CHECK (pool_total_at_open IS NULL OR pool_total_at_open > 0)`. It is safe as `> 0` because a reservation exists only when `granted > 0` and `granted ≤ available ≤ total`.

**Written**: inside `AllocateCapital`'s locked transaction, `Reservation(..., pool_total_at_open=pool_balance.total)` from the read at `allocate_capital.py:131` (F1). It is the same balance the decision was made from, and there is no new read or lock.

**Why this read and not the pre-lock one** used to size `requested`. The pre-lock and in-lock reads can differ by one snapshot refresh. The in-lock value is the one consistent with `granted` under rule 4. So `granted / pool_total_at_open` may differ slightly from `allocation_percent`, and that is correct: the denominator is the pool, not the policy.

- `_resume` (a retried allocation) returns the existing row unchanged.
- Rows written before 0025 have `NULL`. Their trades count in PnL amounts and are excluded from % figures, with the count reported (spec: "treat as absent, never reconstruct").
- The downgrade refuses while any non-null value exists, because they cannot be recomputed.
- A live-PG test asserts that the value is written under the lock and survives a concurrent allocation on the same pool.

### 11. The per-trade return and the compounded curve (decision 12; confirmed by decision 17)

> **Revised 2026-09-24.** The formula below is **confirmed by the owner** (decision 17; former OQ3). Day and month boundaries are **UTC** (decision 16; former OQ2). Nothing here is pending.

Everything below is per pool `(exchange, venue, settlement_currency)`, in its settlement currency (rule 7). A **closed trade** is one allocation whose ledger net base is exactly zero under the base-fee rule (`repository.py:56-88`), counting **non-rehearsal** fills only (F2).

For allocation *i*:

```
pnl_i  = Σ notional(SELL fills) − Σ notional(BUY fills) − Σ fee(fills whose fee_currency = settlement_currency)
         # base-currency fees are already inside the notional difference (F3)
         # a third-currency fee is omitted and the trade is flagged fees_complete=false
C_i    = reservations.pool_total_at_open        # NULL → no return, counted as excluded
r_i    = pnl_i / C_i
closed_at_i = max(filled_at) of the allocation's fills;  opened_at_i = min(filled_at)
pair_i = market_key(symbol of the allocation's fills)    # spellings merged (F4)
```

Per day *d*, a **UTC** calendar day (decision 16):

```
R_d  = Σ r_i  over trades with closed_at_i on day d        # summed, NOT chained, within a day
E_0  = 1
E_d  = E_{d−1} × (1 + R_d)                                 # chained across days (geometric)
DD_d = E_d / max_{s≤d} E_s − 1                             # drawdown from the previous peak, ≤ 0
Month m (UTC):  M_m = E(last day ≤ end of m) / E(last day ≤ end of m−1) − 1
Range W (7D/30D/90D/1Y=365D/All), ending now:
          pnl_W = Σ pnl_i with closed_at in W;   return_W = Π_{d∈W} (1 + R_d) − 1
```

**Worked example.** A 1,000 USDT pool:
- Day 1: A (C=1000, +20) and B (C=1000, +10) both close. R₁ = 0.02 + 0.01 = 0.03, E₁ = 1.03. The pool made 30 on 1,000 = 3%. Chaining the two trades would give 1.0302, compounding B on capital that A's gain never reached, which is the double count decision 12 forbids.
- Day 2: C (C=1030, −20.6) closes. r = −0.02, E₂ = 1.03 × 0.98 = 1.0094, DD₂ = −2.00%.

**Per strategy**: the same algorithm over that strategy's trades, still with r_i = pnl_i / C_i, the POOL capital. A strategy's curve is its **contribution** to the pool. Daily contributions add up exactly to the pool's R_d; the compounded strategy curves do not multiply to the pool curve.

**The one approximation, accepted (decision 17).** A trade that opens on day 1 and closes on day 3, overlapping another that closes on day 2, is compounded on day 2's result although its C was measured before it. The error is the second-order term r₂·r₃. The exact alternative needs a daily pool-equity history. None is stored (`pool_balance_snapshots` keeps one row per pool, `balance_snapshot_repository.py`), and decision 6 declined a contributions register.

**Excluded, and reported rather than hidden**:
- open and partially closed allocations (`open_trade_count`);
- rehearsal fills;
- trades without C (`excluded.no_capital_at_open`);
- trades with an unconverted fee, which stay in the curve but are counted (`excluded.unconverted_fee`).

`usd_rate_at_fill` is never read. All math is `Decimal`. Ratios are quantized to 10 places on the wire.

**The read** is one SQL aggregate per scope. `SqlAlchemyAllocationFillsSource` does `SELECT allocation_id, strategy_id, side, fee_currency, min(symbol), sum(quantity), sum(notional), sum(fee), min(filled_at), max(filled_at)` from `ledger_entries` joined to `reservations` for `pool_total_at_open`, `WHERE pool = ... AND exchange_fill_id NOT LIKE :rehearsal_prefix || '%'` (bound from `REHEARSAL_FILL_ID_PREFIX`), grouped by `(allocation_id, strategy_id, side, fee_currency)`. The domain then folds the rows into `ClosedTrade`s: net base with the base-fee rule via `base_currency_of`, the closed test, pnl and flags. The work is bounded by the trade count (hundreds to thousands), and it rides `ix_ledger_pool_symbol` / `ix_ledger_allocation`. The UTC day of `closed_at` is taken in the domain (`closed_at.astimezone(UTC).date()`), never with a database-session time zone.

### 12. Rehearsal fills excluded by a named marker

`REHEARSAL_FILL_ID_PREFIX = "fake-fill-"` moves into `execution/domain/fill.py`. `FakeExchangeAdapter` mints ids with it (`fake_exchange.py:144`), and the performance source excludes it.

**Why a prefix is safe.** Bybit `execId` values are UUIDs and Binance trade ids are integers, so no live fill can carry it. A test pins that the fake mints with the constant.

**Rejected**: a new `origin='REHEARSAL'` on `execution_attempts`. That means a CHECK change plus threading `is_live` into `PlaceOrder` and `ClosePosition` for a marker the fill id already carries. Ledger rows cannot be marked afterwards anyway (rule 6).

### 13. The `/api` move and SPA serving

- **`/api`**: `api_router = APIRouter(prefix="/api")` includes `strategies_router`, `reconciliation_router` and the new routers. Each keeps its own `dependencies=[Depends(require_admin_token)]`, so auth stays structural per router (`strategies/infrastructure/router.py:56-75`). `signals_router` (`/webhook/tradingview`) and `/health` stay on `app`. The Vite dev proxy already forwards `/api` (`vite.config.ts:15-20`).
- **Frontend**: `shared/api/config.ts` gains `API_PREFIX = "/api"`, and `apiFetch` builds `${API_BASE_URL}${API_PREFIX}${path}`. Callers keep `/reconciliation/...`, the smallest possible diff.
- **Serving**: `Settings.panel_dist_dir: str = ""`. Empty means no SPA is mounted (dev and tests). When set, `mount_panel(app, dist)` runs **after** every router:
  - `app.mount("/assets", StaticFiles(directory=dist/"assets"))`: hashed files (JS, CSS and the self-hosted font files) served with `Cache-Control: public, max-age=31536000, immutable`.
  - `@app.get("/{path:path}")`, registered LAST. If `path == "api"`, or it starts with `api/`, `webhook/` or `health`, it raises `HTTPException(404)` and FastAPI answers 404 JSON. If `dist/path` resolves to a regular file **inside** `dist` (the resolved-path containment check guards against traversal), that file is served (favicon, robots). Anything else gets `index.html` with `Cache-Control: no-cache` and the security headers below.
  - The reserved-prefix check inside the catch-all is **load-bearing**. Starlette records a method mismatch as a partial match and keeps looking, so without it `GET /webhook/tradingview` (POST-only) would fall through to a full GET match and be served `index.html`. With the check it gets 404 JSON.
  - An unknown `/api/*` path never reaches a handler, and the catch-all refuses it too, so the answer is always FastAPI's `{"detail":"Not Found"}`.
  - **Startup**: if `panel_dist_dir` is set but `index.html` is missing, the API refuses to start (fail loud, like invariants 3 and 4).
- **Security headers** on `index.html`: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`, plus `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. React sets styles through the CSSOM, which `style-src` does not block. **Fonts are self-hosted** (§ Visual design), so `font-src` falls back to `default-src 'self'` and the CSP is unchanged by decision 19. The rehearsal must load the built bundle, fonts included, under this CSP before PR 9 deploys.

**Rejected**:
- `StaticFiles(html=True)` mounted at `/`. Its 404 is plain text, so an unknown `/api/*` would not be JSON, and it does no SPA fallback.
- Hash routes, the explore's third option. Decision 10 chose clean paths.

**Validation errors never echo input.** One `RequestValidationError` handler for the whole app strips `input` and `ctx` from each error. Without it, a malformed `api_secret` would come back in the 422 body, and anything logging responses would record it. Nothing in the panel needs the echoed input.

### 14. Endpoints (all under `/api`, all behind the bearer token)

> **Revised 2026-09-24 (decision 18).** Credentials are addressed by exchange only; the 8(c) refusals are gone; the slot view gains `trade_capable` and `warnings`.
>
> **Revised 2026-09-25 (decisions 21–23).** `GET /credentials`'s listing rule changes (decision 21); `DELETE /credentials/{exchange}` is new (decision 22, § 4b); `GET /webhook-secret` is new (decision 23).

Money, quantities and ratios are **JSON strings** (pydantic v2 serializes `Decimal` as a string, and the existing `_amount()` rule applies). Timestamps are ISO-8601 UTC. Every non-2xx response returns the flat `RefusalBody {outcome, detail}` established in book-venue-closes (`reconciliation/infrastructure/router.py:320`), except FastAPI's own 401/404/422 validation shapes.

| Method · path | Request | 200/201 response | Refusals | Backed by |
| --- | --- | --- | --- | --- |
| `GET /strategies?include_archived=false` | — | `[StrategyView]` | — | `SqlAlchemyStrategyRepository.list_all(include_archived)` + one events query → `uptime()` |
| `GET /strategies/{id}` | — | `StrategyView` (archived included) | 404 | repository + events |
| `POST /strategies` | `RegisterRequest` + `allowed_pairs: [str] (min 1)` | 201 `StrategyView` | 409 duplicate id/name; 422 no pairs / bad pool | `RegisterStrategy` |
| `PATCH /strategies/{id}` | `{name?, fill_mode?, allocation_percent?, enabled?}` | `StrategyView` | 404; 409 `STRATEGY_ARCHIVED`; 409 name taken | `UpdateStrategy` (+ event) |
| `PUT /strategies/{id}/allowed-pairs` | `{pairs: [str] (min 1)}` | `StrategyView` | 404; 409 `STRATEGY_ARCHIVED`; 422 empty/invalid | `ReplaceAllowedPairs` |
| `POST /strategies/{id}/archive` | — | `StrategyView` (idempotent) | 404; 409 `STILL_ENABLED`; 409 `OPEN_POSITION` (+ `symbols`, `allocations`, `live_reservations`, `in_flight_attempts`) | `ArchiveStrategy` |
| `GET /strategies/{id}/events` | — | `[{enabled, occurred_at, origin}]` | 404 | `SqlAlchemyEnablementLog` |
| `GET /pools` | — | `[{exchange, venue, settlement_currency, enabled, balance: {total, available, observed_at, stale} \| null, reserved, allocatable}]` | — | `capital_pools` ⋈ `pool_balance_snapshots` + `sum_active` (`allocatable = max(0, available − reserved)`, computed server-side) |
| `GET /performance/pools/{exchange}/{venue}/{ccy}` | — | `PoolPerformance` (below) | 404 unknown pool | `ReadPoolPerformance` |
| `GET /performance/strategies/{id}` | — | `PoolPerformance` + `by_pair: [{pair, trades, pnl, return}]` | 404 | `ReadStrategyPerformance` |
| `GET /performance/strategies/{id}/trades?limit=50&before_closed_at=&before_allocation_id=` | — | `[{allocation_id, pair, direction, opened_at, closed_at, pnl, capital_at_open\|null, return\|null, fees_complete}]` | 404; 422 half a cursor | `ReadStrategyTrades` |
| `GET /credentials` | — | `[{exchange, status: STORED\|EMPTY, last4\|null, label, stored_at, validated_at\|null, trade_capable\|null, permissions\|null}]`, one entry per exchange that has an active credential, a credential history row (any superseded or deactivated row), **or** an enabled pool (decision 20's DEGRADED case) | — | `vault.hints()` (all rows, not only active; no decrypt) |
| `DELETE /credentials/{exchange}` | — | 200, exchange view with `status: EMPTY` | 404 no active credential; 409 `EXCHANGE_NOT_FLAT` (+ `enabled_strategies`, `symbols`, `allocations`, `live_reservations`, `in_flight_attempts`) | `DeleteCredential` (§ 4b) |
| `PUT /credentials/{exchange}` | `{api_key, api_secret: SecretStr, label?}` | exchange view + `warnings: ["READ_ONLY_KEY"]` when `trade_capable=false` | 404 unserved exchange; 422 `KEY_REJECTED` / `WITHDRAW_PERMISSION` (+ `permissions`); 502 `VENUE_UNREACHABLE`; 409 `CONCURRENT_SAVE` | `SaveCredential` (also enables the exchange's pool, decision 21) |
| `GET /webhook-secret` | — | `{secret}`, `Cache-Control: no-store` | — | reads `settings.webhook_secret` directly (decision 23) |
| existing `GET /reconciliation/bookings`, `POST .../approve`, `.../reject` | unchanged | unchanged | unchanged (404/409/422/503) | unchanged |

`PoolPerformance` = `{pool, currency, day_boundary: "UTC", trade_count, open_trade_count, excluded: {no_capital_at_open, unconverted_fee}, ranges: [{range: "7D"|"30D"|"90D"|"1Y"|"ALL", pnl, return|null}], curve: [{date, index, drawdown}], max_drawdown, monthly: [{year, month, return}]}`. An empty ledger returns zeros and empty arrays, never an error (spec).

`StrategyView` = today's fields + `archived_at|null`, `allowed_pairs` (sorted), `uptime: {seconds, first_enabled_at|null, baseline}`.

**Status-code conventions, carried from book-venue-closes.**
- 404: the addressed resource does not exist.
- 409: a state conflict. The request is well-formed and the target's state forbids it.
- 422: the input is the problem. A key the venue rejects, or one with withdraw permission, is bad input.
- 502: the upstream venue failed.
- 503: stays reserved for "this deployment is configured not to" (DRY_RUN).

Key saving is **not** refused under DRY_RUN, because `balance.sync` needs the key there. A read-only key is a 200 with a warning, never a 4xx: it is accepted input (decision 18).

**Pagination** is keyset on the tuple `(closed_at, allocation_id)` descending, never on `closed_at` alone. This is the lesson of the "+1ms" correction: two trades closing in the same millisecond must not be dropped at a page boundary.

**Bookings exchange filter** (decision 3): **client-side**. `BookingProposalView` already carries `exchange` (`router.py:256`), and the list is capped at 500. No `venue-close-booking` delta is needed.

### 15. Frontend architecture (structure; visuals in § Visual design)

**Router: React Router v7 (`react-router`, declarative `BrowserRouter`).** It gives:
- nested layout routes (`<Outlet/>`), which map one-to-one onto the shell;
- `NavLink` active state for both the sidebar and the bottom bar;
- `useParams` for `/strategies/:strategyId`;
- `MemoryRouter` for Vitest;
- React 19 support.

**Rejected**:
- TanStack Router: typed search params are attractive, but they need a route-tree codegen or plugin and a larger API for four routes.
- wouter: the smallest option and viable, but nested layouts are less idiomatic.
- The hand-rolled `hashchange` state in `App.tsx:17-34`: it cannot express clean paths, which decision 10 requires.

Pin the version at install and confirm its React 19 peer range then.

**Route map**:

```
<BrowserRouter>
  <Route element={<TokenGate><AppShell/></TokenGate>}>      layout: TopBar(ExchangeTabs?) · SideNav(lg) · BottomNav(<lg) · DryRunBadge
    /                       → OverviewPage          (exchange tabs shown)
    /strategies             → StrategiesPage        (exchange tabs shown)
    /strategies/:strategyId → StrategyDetailPage    (exchange tabs shown)
    /settings               → SettingsPage          (no exchange tabs; revised 2026-09-24, Settings.dc.html)
    *                       → NotFoundPage   (client-side; the server already served index.html)
```

The old `#bookings` nav item goes away. The bookings list becomes the Overview's right-hand rail (decision 3). `DryRunBadge` reads `GET /health` (`dry_run`) instead of the hard-coded badge at `App.tsx:71-73`.

**Exchange scope**: a Zustand store, `shared/scope/exchange-store.ts`, persisted through the existing `safe-storage` under `sm.exchange`. The options are the distinct exchanges from `GET /pools`, and the default is the first one. Overview and Strategies filter by it. `StrategyDetailPage` sets it from the loaded strategy. **Revised 2026-09-24:** Settings is not scoped; it lists every exchange (Settings.dc.html). The exchange tabs read `['credentials']` to mark an exchange whose key has `trade_capable=false` as read-only (decision 18). **Revised 2026-09-25 (decision 20):** the same query also marks a DEGRADED exchange (`status: EMPTY` with an enabled pool) as "no key", amber, distinct from the teal read-only mark.

**Rejected**: a `?exchange=` search param. Every internal link would have to carry it, and the exchange is a view preference, not resource identity.

**Data fetching**: TanStack Query, whose first real consumer this is (`main.tsx:9`). Typed call functions live in each feature's `api.ts`, over `apiFetch`, and each one validates the top-level shape, following the existing `Array.isArray` guard in `BookingsListView.tsx:16-21`.

| Query key | Endpoint | Freshness |
| --- | --- | --- |
| `['health']` | `/health` (no token) | 60 s |
| `['pools']` | `/pools` | `refetchInterval` 60 s (matches `balance.sync`) |
| `['performance','pool',ex,venue,ccy]` | `/performance/pools/...` | `staleTime` 60 s |
| `['strategies',{includeArchived}]` | `/strategies` | invalidated by every strategy mutation |
| `['strategy',id]`, `['strategy',id,'events']` | detail, events | same |
| `['performance','strategy',id]`, `[...,'trades']` | performance, trades (infinite query, keyset cursor) | `staleTime` 60 s |
| `['credentials']` | `/credentials` | invalidated by a key save or delete; also read by the exchange tabs |
| `['bookings','pending']` | existing | existing |
| `['webhook-secret']` (revised 2026-09-25, decision 23) | `/webhook-secret` | fetched only on "Show secret"; never in the default query cache, evicted with `queryClient.removeQueries` on leaving the strategy detail view |

**Component tree, container / presentational.**

- **Shell**: `AppShell` → `TopBar` (`Brand`, `ExchangeTabs` on scoped routes, `DryRunBadge`), `SideNav` (≥ `lg`), `BottomNav` (< `lg`), `<Outlet/>`.
- **Overview**: `OverviewPage` (container: pools, performance and credentials for the scoped exchange) → `PoolPanel` ×N, one per pool and never merged (rule 7) → `PoolEyebrow`, `LedgerLine` (with its `RangeSelector`), `ReturnChart` (curve and drawdown as one instrument), `MonthlyGrid` + `MonthlySummary`. Alongside it sits `DecisionRail` (“Needs your decision”): the existing `BookingsListView` logic, filtered by exchange, rendering `BookingCard` with the existing `ConfirmBookingDialog` and `RejectBookingDialog`.
- **Strategies**:
  - `StrategiesPage` → `ArchivedToggle`, `NewStrategyDialog` (the id comes from `crypto.randomUUID()`, pairs are required, decision 13), `StrategyList` → `StrategyRow` (name, pool, enabled toggle, uptime, trades, all-time PnL and return).
  - `StrategyDetailPage` → `StrategyHeader` (status, `ArchiveButton` → `ArchiveDialog`, which renders the 409 reasons), `EnableToggle`, `UptimeSummary`, `AllowedPairsEditor`, `WebhookMessage`, `StrategyPerformance` (reuses `LedgerLine`, `ReturnChart` and `MonthlyGrid`), `PairStatsTable`, `TradesTable`, `EnablementHistory`.
- **Settings** (revised 2026-09-24; revised 2026-09-25, decisions 20 and 22): `SettingsPage` → `ExchangeKeyCard` ×N, one per exchange (last-4, "reads and trades" / "reads only", "no withdrawal", checked date, binding and expiry; read-only or no-key marked) with a `DeleteKeyButton` → `DeleteKeyDialog` (renders the 409 `EXCHANGE_NOT_FLAT` reasons, decision 22), → `KeyEntryForm`, an inline section as in Settings.dc.html, not a dialog.

**Reuse**: `apiFetch` (typed `ApiError`; a 401 clears the token), `TokenGate`, `token-store`, `safe-storage`, `cn`, `i18n` (EN/ES keys namespaced per feature) and the `@theme` tokens. **Money is never computed in the browser.** Server strings are parsed only to display them with `Intl.NumberFormat`; the chart turns server ratios into coordinates and the grid picks a colour band, neither of which computes money.

**Charts: dependency-free inline SVG. Recommended over recharts, and recharts is removed from `package.json`.**
- The owner asked to match the pairs report, which is inline SVG (Engram #254), and decision 19 makes the curve-plus-drawdown instrument the signature of the panel.
- Recharts measures the DOM through `ResponsiveContainer`, which renders at zero size in jsdom and makes Vitest awkward.
- Recharts is a dependency today with zero consumers.

The geometry is pure, tested functions in `shared/charts/scale.ts`: `waterlineScale(up, down, height, waterRatio)`, `linePath(points)`, `drawdownPath(points, waterY)`, `monthTicks(dates)` and `gridBand(value)`. **Revised 2026-09-24:** the earlier `logScale` is dropped; the axis is the piecewise-linear waterline scale of § Visual design. Each band maps to a token utility class, so the Tailwind rule (no hex, no `var()` in `className`) holds.

**Webhook message** (decision 1): `webhookMessage(strategyId)` is a pure function that renders the exact JSON from `signals/domain/alert.py:7-12` with `signal_type` substituted.
- A shared fixture, `frontend/src/features/strategies/webhook-message.fixture.json`, is also parsed by a **backend** test through `TradingViewAlert.from_payload` after its `{{...}}` placeholders are replaced with samples. That cross-language guard stops the template from drifting away from the parser.
- The URL is shown by default as `/webhook/tradingview?secret=<your WEBHOOK_SECRET>`, a placeholder.

> **Revised 2026-09-25 (decision 23).** Replaces "**The panel never renders the webhook secret**" (aligned 2026-09-24). The owner reversed that: a "Show secret" button calls `GET /api/webhook-secret` on click only (never prefetched, never in the default query cache), substitutes the real value into the URL placeholder in place, and a "Hide" control (or leaving the view) restores the placeholder and evicts the query. The response carries `Cache-Control: no-store` and is never logged (§ 14, § Threat matrix). No other payload — `/credentials`, `/strategies`, any list or detail — ever carries `webhook_secret`; this stays a dedicated, explicit-click-only endpoint.

**Key entry**:
- `KeyEntryForm` uses local component state, `type="password"` and `autoComplete="off"` for the secret, and `autoComplete="off"` for the key.
- It is submitted by a plain async handler calling `apiFetch`, **not `useMutation`**, whose `variables` would keep the secret in the mutation cache.
- The fields are cleared in `finally` whatever the outcome. Nothing is logged.
- A 200 with `READ_ONLY_KEY` shows the read-only warning; a 422/502/409 shows the outcome's i18n reason.

## Visual design — direction A (decision 19)

> **Revised 2026-09-24.** Replaces "Visual design — pending owner review". The owner chose **direction A, "the pairs report, live"**, with no mixing from direction B. Canvas: https://claude.ai/artifact/HFZmFGY5kT3ubgouYVKEgQ. Normative mockups: `openspec/changes/operator-panel/visual/project/Main.dc.html` (Overview), `Strategy.dc.html` (strategy detail), `Settings.dc.html`, `Mobile.dc.html`. `MainB.dc.html` and `MobileB.dc.html` ("Nocturne", direction B) are the rejected alternative and must not be used. Where a mockup shows sample figures, they are illustrative; the rules below are normative. This pass read Main and Settings in full; `sdd-tasks` must read Strategy and Mobile for their per-view detail.

**Why A**: the owner reads live numbers against backtests, so the panel uses the same visual language as the pairs report.

### Tokens: `frontend/src/index.css` `@theme` (replaces the current block)

The current tokens (`surface-*`, `edge`, `ink-100/300/500`, `accent` blue, `profit` green, `loss` red, `idle` yellow) are **removed**, and PR 10 renames every existing class that uses them (bookings, `TokenGate`, `App`). Hex values live here and nowhere else.

```css
@import "tailwindcss";

/* Direction A (owner decision 19): the pairs report, live. Defined once here so
   no component ever needs a raw hex value or a var() inside className. */
@theme {
  --color-ground: #0C1116;       /* page background */
  --color-panel: #141B22;        /* rails, cards */
  --color-panel-2: #1B242C;      /* active nav item, pressed segment */
  --color-rule: #28333C;         /* borders */
  --color-rule-soft: #1E272F;    /* chart gridlines, empty grid base */
  --color-rule-strong: #3D4E5C;  /* the waterline, the key form's dashed border */

  --color-ink: #E7EDF1;          /* primary text */
  --color-ink-2: #A9B8C3;        /* secondary text */
  --color-ink-3: #7A8C99;        /* captions, ticks, eyebrows */

  --color-gain: #1FA6B8;         /* teal: gains, the equity curve, primary action, links */
  --color-gain-bright: #6FD0DC;  /* link hover */
  --color-loss: #E0644B;         /* ember: losses, drawdown, refusals */
  --color-decision: #CE8018;     /* amber: ONLY "needs your decision" */

  /* Monthly grid bands: fixed ±15% scale, 6 bands of 2.5 points each. */
  --color-gain-1: color-mix(in srgb, #1FA6B8 20%, #1E272F);
  --color-gain-2: color-mix(in srgb, #1FA6B8 32%, #1E272F);
  --color-gain-3: color-mix(in srgb, #1FA6B8 44%, #1E272F);
  --color-gain-4: color-mix(in srgb, #1FA6B8 56%, #1E272F);
  --color-gain-5: color-mix(in srgb, #1FA6B8 68%, #1E272F);
  --color-gain-6: color-mix(in srgb, #1FA6B8 80%, #1E272F);
  --color-loss-1: color-mix(in srgb, #E0644B 20%, #1E272F);
  --color-loss-2: color-mix(in srgb, #E0644B 32%, #1E272F);
  --color-loss-3: color-mix(in srgb, #E0644B 44%, #1E272F);
  --color-loss-4: color-mix(in srgb, #E0644B 56%, #1E272F);
  --color-loss-5: color-mix(in srgb, #E0644B 68%, #1E272F);
  --color-loss-6: color-mix(in srgb, #E0644B 80%, #1E272F);

  --font-display: "Archivo", system-ui, sans-serif;
  --font-sans: "IBM Plex Sans", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
}
```

`body` becomes `@apply bg-ground text-ink font-sans antialiased;`. The `.tabular` helper stays. The grid bands are literal `color-mix()` values because a `var()` inside a `className` is forbidden and Tailwind needs a named colour to emit `bg-gain-3`.

**Colour roles, strictly:**
- **Teal (`gain`)**: positive values, the equity curve, the primary action (`Review and approve`, `Check and save`), links, the active exchange tab underline, focus rings.
- **Ember (`loss`)**: negative values, the drawdown, and refusal messages (a key refused, an archive refused).
- **Amber (`decision`) is reserved for "needs your decision"** and appears in exactly four places: the `DRY RUN` badge, the pending-bookings count in the decision rail, a read-only key, and a no-key (DEGRADED) exchange (the exchange tab's sub-label and the Settings card's border and sentence, in both of the last two cases — revised 2026-09-25, decision 20). It is never used for losses, errors, hover or decoration. A test lists the components allowed to use `decision` utilities.

### Type roles and font loading

| Role | Family | Use |
| --- | --- | --- |
| Display | Archivo 600/700 (restrained) | Brand 17/700; page title 30/700, `-0.015em`; section title 16/600; card title and exchange tab 15–17/600 |
| Body | IBM Plex Sans 400/500/600 | Prose 13–14; nav items; buttons; form labels 13 |
| Numbers | IBM Plex Mono 400/500/600, `tabular-nums` | Every figure; the ledger line 15 with a 26/600 lead figure; eyebrows 11, uppercase, `0.14em`; chart ticks 10; badges 12, `0.12em` |

**Loading: self-hosted, not the Google Fonts CDN.** The mockups link `fonts.googleapis.com` only because they are standalone files. The panel imports `@fontsource/archivo`, `@fontsource/ibm-plex-sans` and `@fontsource/ibm-plex-mono` (latin subset, only the weights above, `font-display: swap`) from `main.tsx`; Vite emits the `.woff2` files hashed under `/assets`.
- **CSP**: unchanged. `font-src` falls back to `default-src 'self'` and `style-src 'self'` needs no exception.
- **Rejected: the Google Fonts CDN.** It would need `style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com`, widening the CSP of the page that holds the bearer token and accepts exchange keys; it would call a third party on every panel load; and the panel would lose its fonts when Google is unreachable. The rendered result is identical either way.

### The signature: curve and drawdown as one instrument

One inline `<svg>` (`ReturnChart`), `role="img"`, `aria-label` from i18n, width 100% via `viewBox`, 330 px tall on wide viewports and about 220 px on a phone.

- **One waterline, one axis.** The waterline is `0%`: zero cumulative return and zero drawdown at once, drawn in `rule-strong` at 1.5 px and labelled `0%`. The y-axis is **piecewise linear** around it: above, cumulative return `E − 1`; below, the negative side of both series. The band above takes about 62% of the plot height and the band below about 38% (Main.dc.html: 180 px above, 100 px below). Each band's scale is `max(|extreme|, 10%)`, so a small drawdown never looks catastrophic, and each band gets its own tick step (5% or 10%).
- **Why linear, not log** (supersedes the explore's log-scale note): return and drawdown share one unit, which is what makes a single waterline readable; a log band above would make the `%` gridlines unequal next to a linear band below. Over the ranges this panel shows, the difference is small.
- **The curve**: a polyline in `stroke-gain`, 2.2 px, round joins, one point per UTC day of `curve[]`, no smoothing (smoothing invents values). If the cumulative return goes negative, the curve crosses into the lower band on the same scale, where it meets the drawdown series.
- **The drawdown**: a closed path from the waterline down to `DD_d`, `fill-loss/20` with a 1.4 px `stroke-loss` edge.
- **Gridlines**: `stroke-rule-soft`, 1 px, at each tick. Tick labels in mono 10 px `ink-3` in a 44 px left gutter.
- **X axis**: month labels (mono 10 px `ink-3`) at the first UTC day of each month.
- **Caption** above the chart, right-aligned in mono 11 px `ink-3`: "UTC days · deposits and withdrawals excluded". Title: "Return of the strategies, compounded".
- **The chart always shows All.** The range selector drives the ledger line only; in Main.dc.html "30D" is pressed while the axis runs July to November. This avoids rebasing ratios in the browser.
- **Empty state** (the DRY_RUN reality): the waterline alone, with a centred caption "No closed trades yet".
- Colours come from utility classes on SVG elements (`stroke-gain`, `fill-loss/20`, `stroke-rule-strong`), never from hex attributes.

### Monthly grid texture

- CSS grid: `48px repeat(12, minmax(0, 1fr)) 64px`, gap 4 px; a header row `J F M A M J J A S O N D YEAR` in mono 11 px `ink-3`; one row per UTC year, most recent first, year label in `ink-2`.
- Cells are 40 px tall, radius 3 px, mono 11 px, the value as a signed percentage with one decimal.
- **Band**: `gridBand(r) = min(6, ceil(|r| / 2.5%))` on a **fixed ±15% scale**, so a colour means the same size of month everywhere and over time; anything beyond ±12.5% sits in band 6. Positive → `bg-gain-{band}`, negative → `bg-loss-{band}`, exactly zero → `bg-rule-soft`. Bands 4–6 switch the text to `text-ground` at weight 600 for contrast.
- A month with no closed trade is an empty cell with a 1 px dashed `rule` border and no value.
- The `YEAR` column is text only (no fill), coloured `gain`/`loss` by sign, weight 600: the compounded year return from the server's months.
- **Summary line** under the grid, mono 11 px `ink-3`: "{positive} of {n} months positive · best {x} · worst {y} · {open} open trades not in the curve", plus "{k} trades without capital at open" when `excluded.no_capital_at_open > 0`.

### The ledger-line summary (instead of KPI cards)

Per pool, never merged (rule 7):
- **Eyebrow**, mono 11 px, uppercase, `0.14em`, `ink-3`: `{EXCHANGE} · {CATEGORY} · {CCY}`, for example `BYBIT · LINEAR · USDT`.
- **The ledger line**, one `<p>` in mono 15 px `ink-2`, line-height 1.7: the **available balance** as the lead figure (26 px, 600, `ink`) + `{CCY} available` · `PnL {range}` value · `return {range}` value · `deepest` value. Separators are ` · ` in `rule`. PnL and return are `gain`/`loss` by sign at weight 600; `deepest` is the all-time `max_drawdown` in `loss`. A `null` return renders as `—`.
- **Range selector** to its right: a segmented group (`role="group"`), `7D 30D 90D 1Y All`, mono 12 px, each button at least 44 px tall; pressed = `bg-panel-2 text-ink` with `aria-pressed`, others `ink-2` on transparent, one `rule` border around the group. Each `PoolPanel` owns its range state; the default is 30D.

### Layout per view

**Shell, wide (≥ `lg`, 1024 px)** — Main.dc.html:
- Grid rows `64px 1fr`. The top bar (bottom border `rule`, padding 0 28 px, gap 32 px) holds the brand, then `ExchangeTabs` (`nav aria-label="Exchanges"`), a spacer, and the `DRY RUN` badge (amber outline, mono 12 px, `0.12em`, radius 4) shown only when `/health` says `dry_run`.
- Each exchange tab stacks the name (Archivo 15/600) over a mono 11 px sub-label: the pool summary in `ink-3` (for example "USDT pool"), or, for a read-only key, "{category} · read-only key" in `decision`, or, **for a DEGRADED exchange with no key at all** (revised 2026-09-25, decision 20), "no key" in `decision`. Active tab: 2 px `gain` bottom border and `ink`; inactive `ink-2`.
- Body grid `208px 1fr` (Settings, Strategies) or `208px 1fr 360px` (Overview). The left rail (`nav aria-label="Sections"`, padding 24/12, right border `rule`) lists Overview, Strategies, Settings; items padding 12/14, radius 6; active = `bg-panel-2`, `ink`, weight 600.

**Overview** — Main.dc.html. Main column padding 28/36, gap 28. Per pool: the eyebrow and ledger line (left) with the range selector (right, bottom-aligned); the return chart; "Month by month" with the grid and summary. The right rail, `aside aria-label="Needs your decision"` (`bg-panel`, left border `rule`, padding 28/24, gap 14): title "Needs your decision" with the amber "{n} pending" count; a one-line explainer in `ink-2` 13 px ("Closes the venue made that the ledger has not recorded. Approving writes them to the ledger for good."); then one `BookingCard` per proposal (`bg-ground`, `rule` border, radius 8, padding 16): symbol (Archivo 15/600) and expiry (mono 11, `ink-3`); mono 12 px details (strategy, side and size, fill count and last price); "Review and approve" (teal filled, opens the existing confirm dialog) and "Reject" (outlined `rule`), both at least 44 px tall. Empty: "Nothing needs your decision", no amber count.

**Strategies and strategy detail** — Strategy.dc.html, reusing the Overview instruments (`LedgerLine`, `ReturnChart`, `MonthlyGrid`) for one strategy's contribution, plus the lifecycle controls of § 15. Its per-element detail is taken from the mockup at `sdd-tasks`.

**Settings** — Settings.dc.html. No exchange tabs in the top bar. Main column padding 28/36, gap 22, max width 900 px:
- Title "Exchange keys" (Archivo 30/700) and the intro "One key per exchange. Keys are encrypted on the server and never shown again; you only see the last four characters."
- One `ExchangeKeyCard` per exchange (`bg-panel`, `rule` border, radius 10, padding 20, grid `1fr auto`): the name (Archivo 17/600) over a mono 13 px `ink-2` line `key ••••{last4} · reads and trades | reads only · no withdrawal · checked {date}` ("not validated" for keys sealed before 0026); a "Replace key" button (outlined, at least 44 px) and, when a key is active, a "Delete key" button (outlined `loss`, at least 44 px) that opens `DeleteKeyDialog` with an explicit confirmation, rendering the 409 `EXCHANGE_NOT_FLAT` reasons below it in `loss` on refusal (decision 22, revised 2026-09-25). **A read-only key** turns the card border `decision` and adds, in `decision` 13 px: "This key cannot trade. With dry run off, signals for {exchange} are refused until you add a key that can trade futures."
  - **Revised 2026-09-25 (decision 20).** An exchange with an enabled pool but no key (DEGRADED) uses the same amber `decision` treatment as a read-only key: card border `decision`, and in `decision` 13 px: "No key stored. With dry run off, opening signals for {exchange} are refused until a key is added." — plus the existing "Add key" primary button, no "Delete key" (there is nothing to delete). An exchange with no enabled pool and no key ever stored keeps the neutral `ink-2` "No key stored" text with no amber border, since nothing there is degraded yet.
- `KeyEntryForm`, an inline section with a 1 px dashed `rule-strong` border, radius 10, padding 20: title "Replace the {exchange} key"; two columns, "API key" (mono input) and "API secret" (password input), both at least 44 px, `bg-ground`, `rule` border; helper text in `ink-3` 13 px: "Before saving, the key is tried with a real read. A key that can withdraw funds is refused."; buttons "Check and save" (teal filled) and "Cancel". A refusal renders below it in `loss` with the outcome's reason.

**Phone (< `lg`)** — Mobile.dc.html:
- The left rail becomes a fixed **bottom navigation** (`nav aria-label="Sections"`, three items, each at least 44 px tall, safe-area inset padding); the content gets matching bottom padding.
- The top bar keeps the brand and the `DRY RUN` badge; the exchange tabs sit in their own horizontally scrollable row below it.
- Overview becomes one column, in this order: exchange tabs, range selector and ledger line, the return chart, **the decision rail as an in-flow block** (`bg-panel`, full width, same cards), then "Month by month". The spec's small-viewport placement was aligned to this order on 2026-09-24.
- The month grid's phone layout follows Mobile.dc.html.

### Constraints that still hold

- The route map, component tree, query keys and pure chart geometry above.
- Tailwind tokens only: no hex and no `var()` in `className`.
- EN/ES for every string, including chart labels, captions and the ledger line's words.
- Every view has loading, empty, error and data states, and the empty state is the DRY_RUN reality.
- Touch targets are at least 44 px, as in every mockup.

## Data flow: a signal after this change

```
signal.process ─ load context ─ policy_for (enabled, archived, allowed_pairs — one row)
   archived?            ─► WARNING "remove its TradingView alert", refused   (no lock, no reservation)
   untradable pool?     ─► WARNING, refused                                    (unchanged)
   effects[0] CONSUMES:
     market_key(symbol) ∉ allowed_pairs ─► WARNING, refused                   (no lock, no reservation)
     DRY_RUN=false and exchange READ_ONLY | NO_KEY ─► WARNING, refused        (no lock, no reservation; decision 4a)
     HoldingGuard ─ refresh ─ pre-lock sizing read ─ AllocateCapital:
        find_by_signal_id ─ policy.enabled? ─ LOCK(pool) ─ policy_for again (enabled/archived) ─ balance read
        ─ decide ─ INSERT reservation(amount=granted, pool_total_at_open=balance.total) ─ COMMIT
   effects[0] RELEASES:  unlisted pair ─► WARNING "pair no longer listed; closing anyway" ─ ClosePosition (unchanged)
                         read-only key ─► not refused here; the close goes to the venue (decision 4a)
```

## File changes

> **Revised 2026-09-24.** The purpose migration, the purpose-aware vault/ports and the 12-site rewiring are gone; the trade-capability port and adapter are new; migrations renumbered; frontend gains the direction-A tokens and self-hosted fonts.
>
> **Revised 2026-09-25 (decisions 20–23).** `worker.py`/`main.py`'s startup check no longer refuses; new `known_pools.py`, `delete_credential.py`, `pool_exposure_adapter.py` and a webhook-secret router.

| File | Action | Description |
| --- | --- | --- |
| `backend/scripts/check_key_permissions.py` (+ test) | Create | Unit 1a probe, GET-only, redacting |
| `backend/migrations/versions/0024_strategy_lifecycle.py` | Create | `allowed_pairs` + seeding, `archived_at` + CHECK, enablement events + trigger + BASELINE |
| `backend/migrations/versions/0025_reservation_pool_total.py` | Create | `pool_total_at_open` |
| `backend/migrations/versions/0026_credential_snapshot.py` | Create | `permissions JSONB`, `validated_at`, `trade_capable` (backfill true, default dropped), refusing downgrade |
| `accounts/domain/exchange_credential.py` | Modify | `trade_capable`, `validated_at`, `permissions` fields |
| `accounts/domain/key_policy.py` | Create | 8(a)–8(b) and trade-capability derivation, pure |
| `accounts/domain/known_pools.py` | Create | `KNOWN_FUTURES_POOLS` constant (decision 21) |
| `accounts/application/ports.py` | Modify | `CredentialWriterPort`; `KeyInspectorPort`; hint fields; `CapitalPoolWriterPort`; `PoolExposurePort` (decisions 21–22) |
| `accounts/application/save_credential.py` | Create | Validate + seal + enable-pool use case (decision 21) |
| `accounts/application/delete_credential.py` | Create | Exposure check + deactivate + disable-pool use case (decision 22, § 4b) |
| `accounts/infrastructure/{credential_vault,models}.py` | Modify | Snapshot columns; `CredentialNotFound` message names the exchange's store script; `hints()` includes history rows (decision 21) |
| `accounts/infrastructure/key_inspectors/{bybit,binance,registry}.py` | Create | Inspection adapters |
| `accounts/infrastructure/trade_capability_adapter.py` | Create | `VaultTradeCapabilityAdapter`, `DryRunTradeCapability` |
| `accounts/infrastructure/capital_pool_writer.py` | Create | `SqlAlchemyCapitalPoolWriter` (decision 21/22) |
| `accounts/infrastructure/pool_exposure_adapter.py` | Create | `PoolExposureAdapter` (decision 22) |
| `accounts/infrastructure/{pools_router,credentials_router,pool_overview}.py` | Create/Modify | `/api/pools`, `/api/credentials` (+ `DELETE`, decision 22) |
| `signals/infrastructure/webhook_secret_router.py` | Create | `GET /api/webhook-secret` (decision 23) |
| `strategies/domain/{strategy,allowed_pairs,enablement}.py` | Modify/Create | Archived, pairs VO, events, uptime |
| `strategies/application/{ports,register_strategy,update_strategy,policy_adapter}.py` | Modify | Pairs, events, FOR UPDATE, archived refusal, snapshot fields |
| `strategies/application/{archive_strategy,replace_allowed_pairs}.py` | Create | |
| `strategies/infrastructure/{models,repository,router}.py` | Modify | Columns, `get_for_update`, `list_all(include_archived)`, new routes |
| `strategies/infrastructure/{enablement_log,exposure_adapter,pool_lock_adapter}.py` | Create | |
| `allocation/application/{ports,allocate_capital}.py` | Modify | Snapshot fields; in-lock re-check; `pool_total_at_open` |
| `allocation/domain/reservation.py`, `allocation/infrastructure/{models,repository}.py` | Modify | New column mapped |
| `signals/application/process_signal.py` | Modify | Archived refusal (`handle`, `open_now`); unlisted-pair and read-only-exchange refusals (`_handle_consumes`); release-side WARNING; `TradeCapabilityPort` |
| `execution/domain/{market_symbol,fill}.py`, `execution/infrastructure/fake_exchange.py`, `reconciliation/application/market_key.py` | Modify | `market_key` relocated, rehearsal prefix constant |
| `performance/{domain,application,infrastructure}/…` | Create | New module (decision 11) |
| `shared/config.py` | Modify | Remove the Bybit/Binance key fields; add `panel_dist_dir` |
| `shared/infrastructure/{bybit,binance}/factory.py` | Modify | Remove `credentials_from_settings` |
| `shared/infrastructure/{spa,validation_errors}.py` | Create | Serving, fallback, headers; redacted 422 |
| `main.py` | Modify | Five Binance read sites onto the vault; trade-capability wiring; `/api` router, new routers, `mount_panel`, invariant 5; skips registering read adapters for a DEGRADED exchange (decision 20) |
| `worker.py` | Modify | `_assert_keys_present` logs one ERROR per DEGRADED exchange and returns the set, never raises (revised 2026-09-25, decision 20) |
| `strategies/infrastructure/admin_token_invariant.py` | Modify | Message names `/api` |
| `backend/scripts/{probe_credentials,check_bybit_read,check_binance_read,check_venue_fill_windows,measure_reconciliation_rate_limits}.py` | Modify | Load from the vault; `announce` prints `***last4 (vault)` |
| `backend/scripts/store_{bybit,binance,pionex}_credentials.py` | Modify | Fold onto `SaveCredential` (PR 8): accept a read-only key with a warning |
| `backend/tests/**` | Modify/Create | `/api` paths (`test_router_auth`, reconciliation `test_router` + conftest, `test_admin_auth`, `test_access_log`, `test_smoke`), `test_booking_prepare_wiring.py:61-82` (asserts the vault, not `binance_credentials_from_settings`), `test_worker.py`, new suites |
| `frontend/package.json` | Modify | + `react-router`, `@fontsource/archivo`, `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono`; − `recharts` |
| `frontend/src/index.css` | Modify | Direction-A `@theme` replaces the current tokens |
| `frontend/src/main.tsx` | Modify | Font imports |
| `frontend/src/app/{App,router}.tsx`, `shared/layout/*`, `shared/scope/*`, `shared/charts/*`, `shared/api/config.ts` | Modify/Create | Shell, router, scope, charts, `/api` prefix |
| `frontend/src/features/{overview,strategies,settings}/*`, `features/bookings/*`, `shared/auth/*` | Create/Modify | Views; bookings re-homed; existing classes renamed to the new tokens; `DeleteKeyDialog` (decision 22); "Show secret" control (decision 23) |
| `frontend/src/shared/i18n/locales/{en,es}.json` | Modify | Every new string |

## Testing strategy

| Layer | What | How |
| --- | --- | --- |
| Unit (domain) | `evaluate_key` for 8(a), 8(b) and the trade-capability derivation (trading key, read-only key, transfer-only key) using probe-recorded payload fixtures; `AllowedPairs`; `uptime()` (closed and open intervals, BASELINE, repeated events); `derive_trade` (long, short, base-fee spot, third-currency fee, partial = open, rehearsal excluded); `daily_returns`/`compound`/`drawdowns`/`monthly_grid`/`range_summary` against the **hand-computed worked example above**, with a UTC month-boundary case; `by_pair` merging `SOLUSDT.P` + `SOLUSDT` | Pure, no DB |
| Unit (application) | `SaveCredential`: refusals store nothing; a read-only key is stored with `trade_capable=false` and a warning; **also enables the exchange's pool, idempotently on a second save (decision 21)**; `DeleteCredential`: refused when a strategy on the exchange is enabled, refused when open exposure exists, succeeds when flat (deactivates + disables the pool), replacing a key never runs this check (decision 22); `ArchiveStrategy` refusal reasons; `UpdateStrategy` event only on change; `ProcessSignalHandler`: archived, unlisted and read-only-exchange refusals each log exactly one WARNING and never call `allocate`; `NO_KEY` refused live, **both for a never-keyed exchange and immediately after `DeleteCredential` commits**; nothing refused under `DryRunTradeCapability`; the release path is never refused by the allowlist or the read-only rule; `_assert_keys_present` logs one ERROR per DEGRADED exchange, via a fake `AlertPort`, and returns without raising (decision 20) | Fakes for every port, `caplog` |
| Integration (real PG) | 0024–0026 up/down/refusals (Tier B, `alembic upgrade head`); seeding with **different spellings per signal**; the enablement trigger refusing UPDATE/DELETE; 0026 backfills `true` and an insert without `trade_capable` fails; `CONCURRENT_SAVE` by the name `ux_exchange_credentials_one_active_per_exchange`; `VaultTradeCapabilityAdapter` answers without decrypting (a row with garbage ciphertext still answers); `pool_total_at_open` written under the lock; **concurrent archive vs allocation on one pool** (both orders); **concurrent `DeleteCredential` vs allocation on one pool** (both orders, decision 22); `PoolExposureAdapter` sees every strategy bound to the pool, not just one; FOR UPDATE toggle race | Live PostgreSQL (`rules.tasks`) |
| Integration (wiring) | Each of the five Binance read sites signs with the vault key (`test_booking_prepare_wiring` style); **the worker starts and logs one ERROR naming the exchange whose enabled pool has no key, then still accepts jobs, and every other exchange trades normally (revised 2026-09-25, decision 20)**; no Bybit/Binance `credentials_from_settings` left (grep test) | Fakes + real vault |
| Integration (HTTP) | Every `/api` route answers 401 without the token (a parametrized test over `app.routes`); `GET /strategies/<uuid>` → `index.html`; `GET /api/unknown` → 404 JSON; `GET /webhook/tradingview` → not HTML; `POST /webhook/tradingview` unchanged; traversal `GET /..%2f..%2fbackend%2f.env` → index or 404, never the file; CSP header present and unchanged; a font file under `/assets` is served; a 422 never echoes `api_secret`; `DELETE /api/credentials/{exchange}` returns 409 `EXCHANGE_NOT_FLAT` with an enabled strategy or an open position, and 200 with `status: EMPTY` when flat (decision 22); `GET /api/webhook-secret` returns `Cache-Control: no-store`, and no other `/api` response body ever contains the configured webhook secret's value (decision 23) | `httpx.AsyncClient` over the ASGI app with a temp `dist` |
| Integration (venue) | Key inspectors against `httpx.MockTransport` using probe-recorded payloads | No real credential (rule 1) |
| Cross-language | The webhook-message fixture parses through `TradingViewAlert.from_payload` | Backend test reads the frontend fixture |
| Frontend | Route rendering in `MemoryRouter`; the exchange scope filters, and Settings shows no exchange tabs; the read-only mark and the no-key (DEGRADED) mark on a tab and a card, and that they are visually distinct only in sub-label wording, not colour (decision 20); the "Delete key" control is refused-state-aware and renders the 409 reasons (decision 22); "Show secret" fetches only on click, restores the placeholder and evicts the query on leaving the view, and the secret never appears in the default query cache (decision 23); loading/empty/error/data per view; the key form clears in `finally` and never uses a mutation cache; 401 clears the token; `waterlineScale` (both bands, a negative cumulative return, the 10% floor), `drawdownPath`, `gridBand` (0, ±2.5 boundary, ±15, beyond); only the allowed components use `decision` utilities; EN and ES render with no missing keys | Vitest + `vi.stubGlobal("fetch")` (existing convention) |

TDD is strict (`openspec/config.yaml` `strict_tdd: true`): RED before every production change.

## Threat matrix

The skill's matrix, per `references/threat-matrix.md`:

| Boundary | Applicability | Reason |
| --- | --- | --- |
| Documentation-like paths | N/A | No file is classified or executed by name; the SPA fallback serves bytes, it does not execute them (covered below as HTTP traversal) |
| Git repository selection | N/A | No VCS automation |
| Commit state | N/A | No VCS automation |
| Push state | N/A | No VCS automation |
| PR commands | N/A | No VCS automation |

The change does touch **HTTP routing and secrets**, so these project-specific threats are design requirements. Each carries a planned RED test:

| Threat | Safe behaviour | Failure behaviour | RED test |
| --- | --- | --- | --- |
| The SPA fallback shadows `/api`, `/webhook`, `/health` | Reserved prefixes → 404 JSON; own routes win | Never `index.html` | `GET /api/unknown`, `GET /api`, `GET /webhook/tradingview`, `GET /healthz`-style prefixes |
| Path traversal through the fallback file serving | Only regular files whose resolved path is inside `dist` | `index.html` or 404 | Encoded `../` and absolute-path probes |
| A new `/api` route ships without auth | Auth is a router dependency; a parametrized test walks `app.routes` | 401 | Every `/api/*` route without the token |
| A secret is echoed or logged | `SecretStr`; the redacted 422 handler; no body logging; httpx at WARNING in the API process (Binance puts its signature in the query string) | — | A 422 with a bad `api_secret` contains no part of it; `caplog` holds no secret |
| A secret is retained in the browser | Local state, cleared in `finally`; no `useMutation`; never in the query cache or `localStorage` | — | Vitest: the query cache and store after submit hold no secret |
| A secret is returned by the API | Responses carry only last-4, `trade_capable` and the snapshot | — | The list and PUT responses contain no `api_key`/`api_secret` |
| The API process decrypts | `CredentialWriterPort` has no `load`; `VaultTradeCapabilityAdapter` reads columns only | Type error / test failure | Structural test (decision 5) |
| **A read-only key reaches the venue on a live open** (added 2026-09-24) | Refused before the lock with one WARNING (decision 4a); a missing `trade_capable` value cannot be inserted | The residual race fails at the venue as today | `ProcessSignalHandler` read-only refusal; 0026 insert without the value fails |
| **One key signs reads and orders** (added 2026-09-24) | Accepted by decision 18: 8(b) forbids withdraw on every key; plaintext lives only for one signing call (rule 8) | — | 8(b) refusal tests |
| **A DEGRADED exchange trades or is silently invisible** (added 2026-09-25, decision 20) | One ERROR at startup reaches Telegram (`AlertLogBridge`); no balance/position read is attempted for it; every opening signal logs one WARNING naming it; the panel marks it "no key" in amber | Silent: no ERROR, no WARNING, no panel mark, or an order placed with no key | Startup ERROR asserted via a fake `AlertPort`/`caplog`; `GET /credentials` shows `status: EMPTY` with an enabled pool; the read-only-exchange refusal test's `NO_KEY` case |
| **Deleting a key strands a position with no key left to close it** (added 2026-09-25, decision 22) | `DELETE /credentials/{exchange}` refused (409) unless every strategy on the exchange is disabled and the pool holds no open exposure | A position open with no active key on that exchange | `DeleteCredential` refusal tests (enabled strategy, open exposure); concurrent delete-vs-allocate test |
| **The webhook secret leaks through a list/detail payload or a log** (added 2026-09-25, decision 23) | Served only by `GET /api/webhook-secret`, on an explicit "Show secret" click; `Cache-Control: no-store`; excluded from access logging; the UI restores the placeholder on leaving the view | Present in `/credentials`, `/strategies`, any other body, or a log line | A test asserts no `/api` response other than `/api/webhook-secret` contains the configured secret's value; header assertion; Vitest state-restore-on-navigate test |
| XSS steals the bearer token from `localStorage` | Strict CSP on `index.html`; no third-party scripts, styles or fonts (fonts self-hosted) | — | Header assertion; rehearsal loads the built bundle under the CSP |
| The panel is exposed without Cloudflare Access through the DuckDNS proxy | The proxy forwards only `/webhook/tradingview` (owner step); uvicorn binds `127.0.0.1`; the bearer token stays as defence in depth | 401 | Owner-run check (rollout) |
| **`BEHIND_CLOUDFLARE_TUNNEL` flipped for the panel tunnel** | The flag stays `false`. It describes the **webhook's** path (`signals/infrastructure/auth.py:62`). If set while the webhook still arrives through DuckDNS, any client could forge `CF-Connecting-IP` and walk past the TradingView IP allowlist | — | Runbook line; startup INFO log that names the flag's meaning |
| Cloudflare sees plaintext keys | TLS terminates at Cloudflare's edge, so a key typed into Settings transits Cloudflare in plaintext. **An accepted assumption**: Cloudflare is trusted with it. The alternative is the store scripts over SSH, which remain available | — | Documented in Settings help text (i18n) |
| Access JWT not verified by the app | Not in this change. The bearer token is the application's own copy of the judgement (`admin_auth.py:15-22`). Verifying `Cf-Access-Jwt-Assertion` is a follow-up | — | — |

## Migration / rollout

Every migration is rehearsed first **locally** (Tier B tests: up, down, refusals) and then **on the VPS against a throwaway copy**: `pg_dump` production → `createdb sm_rehearsal` → restore → `DATABASE_URL=…/sm_rehearsal uv run alembic upgrade head` → read the 0024 seeding log and BASELINE count → `downgrade` to prove the refusals → `dropdb`. The copy never leaves the VPS. The owner reads the seeded pairs **before** production migrates.

**PR 3 deploy (revised 2026-09-24: much simpler).** No migration, no schema change, no old/new worker overlap hazard.

```
0. Gate: tasks.md § Probe results shows P4 passing with the VAULT Binance key
   (/fapi/v3/account, /fapi/v3/positionRisk, /fapi/v1/symbolConfig).
1. Deploy code; restart the worker and the API.
2. Worker log: the vault self-test lists bybit and binance opened; a missing key for an
   exchange with an enabled pool logs one ERROR by name (reaching Telegram) and the worker
   still starts and accepts jobs -- it does not refuse to start (revised 2026-09-25, decision 20).
3. Watch one balance.sync cycle for the Binance pool succeed.
4. After PR 3 is proven: delete BYBIT_API_KEY/SECRET and BINANCE_API_KEY/SECRET from .env.
   Do NOT store the .env Binance read key in the vault: under one-active-per-exchange it
   would supersede the trade key and make Binance read-only.
```

Rollback: revert the code and restart. Keep the `.env` lines until step 4, so a revert still has the Binance read key.

**PR 5 (allowlist enforcement)**: 0024 has already seeded the lists (PR 4). The owner reviews them through `GET /api/strategies` and adjusts with `PUT …/allowed-pairs` **before** PR 5 deploys.

**PR 6 (performance)**: before deploying, the owner runs `SELECT count(*) FROM ledger_entries WHERE exchange_fill_id LIKE 'fake-fill-%'` (F2). Any rehearsal rows are excluded by design. The count is recorded in `tasks.md`.

**PR 8 (key validation, 0026)**: `alembic upgrade head` then restart both processes. The old code never inserts credentials (only the store scripts do), so no ordering is needed; run the store scripts only from the new code, because 0026 makes `trade_capable` mandatory. After deploy, re-saving each key through Settings records its snapshot (optional; unvalidated rows remain trade-capable by construction). **Revised 2026-09-25 (decision 21):** re-saving Bybit's and Binance's already-active keys through Settings also runs `CapitalPoolWriterPort.enable`, which is a no-op on their already-enabled pool rows (migrations 0017/0018) — nothing to rehearse beyond the existing key-save flow.

**PR 9 (serving) prerequisites**, all owner-run:
- the DuckDNS proxy forwards only `/webhook/tradingview`;
- `cloudflared` routes `strategymanager.trade` to `http://127.0.0.1:8000`;
- an Access policy restricted to the owner's identity;
- `PANEL_DIST_DIR` points at the built `frontend/dist`;
- `BEHIND_CLOUDFLARE_TUNNEL` stays `false`;
- the owner's `curl` runbooks move to `/api` (from PR 2 onward).

## Unit split, PR boundaries and honest forecasts

> **Revised 2026-09-24.** Recomputed after decision 18. Removed: the purpose migration and vault/port/script purpose plumbing (old 1b), the 12-site rewiring (old 1c), rule 8(c), OQ4 and probe item P5. Added: the read-only opening refusal (6c) and the direction-A token swap and fonts (inside PR 10). PR 13 shrinks to one card per exchange. The old bottom-up low figure was also mis-summed (16,400, not 16,300); the table below is re-added from its rows.
>
> **Revised 2026-09-25 (decisions 20–23).** PR 3's startup-check unit shrinks slightly (a log call replaces a raise, but gains the read-adapter skip); PR 7 gains the webhook-secret endpoint; PR 8 gains two units (6d pool auto-enable, 6e `DeleteCredential`) and now also depends on PR 5's pool-lock adapter; PR 13 gains the delete-key control and the no-key card state. Nothing is removed. The bottom-up total moves from 15,100–21,150 to **16,550–23,300**.

**Revisions to the proposal's PR table** (still valid):
- 1a is **its own PR**. The owner must run it before PR 3 deploys (P4) and before PR 8's rules are written (P1–P3).
- The mechanical `/api` move (4a) is **PR 2**, so every new endpoint is born at its final path.
- Lifecycle enforcement (PR 5) lands after the schema and endpoints the owner needs in order to prune pairs. It is no longer gated on an owner question (decision 15).

The forecasts already apply the last change's measured bias: per-unit actuals ran about 2× their forecasts, concentrated in `main.py` wiring and integration tests.

| PR | Units | Forecast (authored lines) | Gate |
| --- | --- | --- | --- |
| 1 | 1a probe + redaction test | 250–400 | Owner runs it; output recorded in `tasks.md` |
| 2 | 4a `/api` move (backend + frontend paths + tests) | 550–800 | — |
| 3 | 1b Binance reads onto the vault (5 sites), Bybit/Binance `.env` fields and `credentials_from_settings` removed, diagnostic scripts onto the vault, `_assert_keys_present` logs and degrades rather than raises (decision 20), wiring + grep tests | 600–900 | PR 1's P4 on the vault Binance key |
| 4 | 2a 0024 + ORM + VOs + seeding tests (900–1,200) · 2d enablement log + uptime (600–850) · 2e pairs PUT, POST requires pairs, list filter, view fields, events GET (600–800) | 2,100–2,850 | VPS rehearsal of seeding |
| 5 | 2b archived + unlisted refusals (opens only), snapshot fields, `market_key` move (700–1,000) · 2c `ArchiveStrategy`, exposure adapter, pool lock, in-lock re-check, concurrency tests, archive endpoint (1,100–1,500) | 1,800–2,500 | Owner pruned the seeded pairs |
| 6 | 3a `pool_total_at_open` 0025, live PG (350–500) · 3b fills source + `derive_trade` (700–1,000) · 3c curve/drawdown/grid/ranges, UTC (700–1,000) · 3d strategy + pair stats (400–600) | 2,150–3,100 | Rehearsal-fill count recorded |
| 7 | Read endpoints: pools, performance pool/strategy/trades, `GET /webhook-secret` (decision 23, 150–250) | 950–1,350 | — |
| 8 | 6a key policy + inspectors + 0026 (800–1,100) · 6b `SaveCredential`, credential endpoints, redacted 422, store scripts onto the use case (750–1,000) · 6c `TradeCapabilityPort`, adapters, read-only opening refusal (350–500) · 6d `KNOWN_FUTURES_POOLS`, `CapitalPoolWriterPort`, pool auto-enable on save (decision 21, 300–450) · 6e `DeleteCredential`, `PoolExposurePort`/adapter, `DELETE` endpoint, concurrency test (decision 22, 700–1,000) | 2,900–4,050 | PR 1's P1–P3 recorded |
| 9 | 4b SPA serving, fallback, CSP, invariant 5, `panel_dist_dir` | 500–750 | Owner infra steps |
| 10 | Router, shell, exchange scope, bookings re-homed, query hooks, `DryRunBadge`, direction-A `@theme` swap + class renames, self-hosted fonts | 1,150–1,600 | — |
| 11 | Overview: ledger line, return chart + geometry, monthly grid, decision rail | 1,300–1,800 | — (visual review done, decision 19) |
| 12 | Strategies list + detail + dialogs + webhook message + "Show secret" control (decision 23) | 1,400–1,900 | — |
| 13 | Settings: one card per exchange, key form, read-only and no-key marks, delete-key control + dialog (decision 22) | 900–1,300 | — |

Bottom-up **16,550–23,300** authored changed lines (revised 2026-09-25; was 15,100–21,150 after decision 18). **Units certain to exceed 1,000 if not split further at `sdd-tasks`**: 2a, 2c, PR 8 as a whole (now four figures even before splitting further), and every PR from 4 to 8 plus 10–12 as a whole. Every PR except PR 1 exceeds 400 even at its low end (PR 3 is the smallest at 600). The review unit is the work-unit commit (roughly 250–900 lines each), sequential chained PRs to `main`, never stacked.

**PR boundaries** (auto-chain, sequential to `main`): each PR starts from `main` after the previous one merged, holds only its own units, and is independently deployable and revertible. PR 3 is the only one with an owner-run gate before deploy; PR 8's rules wait for the probe section.

Dependencies:
- 1 ⟂ 2; 3's deploy needs 1's P4 output.
- 4 → 5; 6 needs 5's snapshot fields only for 3d; 7 needs 6.
- 8 needs 1 (P1–P3), 3, and **5** (revised 2026-09-25: `DeleteCredential`'s 6e reuses PR 5's pool-lock adapter and `StrategyExposurePort` query shape); 9 ⟂ the rest of the backend.
- 10 needs 2 and 9; 11–13 need 10 and their endpoints (7, 4/5, 8).

`Decision needed before apply: No` · `Chained PRs recommended: Yes` · `400-line budget risk: High`

(`Decision needed before apply` is now **No**: OQ1–OQ3 are resolved by decisions 15–17, OQ4 is moot by decision 18, and the visual review is done by decision 19. The owner-run probe and deploy gates remain, but they are operational steps, not open decisions.)

## Lessons applied from book-venue-closes' apply-time corrections

- **Multiplicity** (the multi-allocation full close): every check here iterates **all** allocations, not the first. That covers archive exposure, per-trade derivation, and by-pair stats grouped per allocation. A test uses a strategy with two open allocations on one market.
- **Pagination** (+1ms): keyset on `(closed_at, allocation_id)`, with a test of two trades closing in the same millisecond across a page boundary.
- **Identity keys** (the order-id-keyed `client_order_id`): nothing new is keyed on a value that can repeat. Events are keyed by UUID. `CONCURRENT_SAVE` is identified by the constraint **name**, and an integration test asserts that name against the live schema before any code relies on it.

## Open questions

> **Revised 2026-09-24.** None open.

- ~~OQ1 — Does the allowlist refuse closes?~~ **Resolved by decision 15**: opens only (decision 7).
- ~~OQ2 — Day boundary.~~ **Resolved by decision 16**: UTC.
- ~~OQ3 — Confirm the return formula.~~ **Resolved by decision 17**: confirmed as in decision 11.
- ~~OQ4 — Same-account rule 8(d).~~ **Moot by decision 18**: one key per exchange.

Recorded carve-outs, not questions: Pionex `.env` keys stay (decision 2); `NO_KEY` is refused live by the same check as a read-only key (decision 4a) — **revised 2026-09-25 (decision 20)**: no longer defensive, since the startup refusal it used to back up is gone; this check is now the sole mechanism.

## Spec realignment

> **Revised 2026-09-24: done.** The specs were edited in place, each change carrying a dated note:
> - `exchange-credentials`: rewritten for decision 18 (one key per exchange, no purpose, Binance reads on the vault, 8(a)+8(b), read-only accepted with a warning, live opening signals refused up front, startup per exchange).
> - `strategy-lifecycle`: decision 15 (opens only, with close and reverse scenarios), F4 (pairs by `market_key` per allocation), F8 (creation writes no event).
> - `performance-reporting`: F1 (in-lock read), F2 (rehearsal-fill exclusion by the named constant; "no qualifying trades" empty result), F3 (settlement-currency fees only, no conversion), F4, decision 16 (UTC), decision 17 (formula confirmed, same-day summing scenario).
> - `capital-allocation`: allowlist opens only, F1 wording, plus the in-lock strategy re-check and the read-only pre-lock refusal.
> - `operator-panel`: one key per exchange in Settings, the read-only mark, Settings without exchange tabs and the phone placement of the decision rail (decision 19 mockups), and the webhook secret never rendered (aligned to the proposal).
> - `admin-api` and `panel-serving`: unchanged.
>
> **Revised 2026-09-25 (decisions 20–23): done again.**
> - `exchange-credentials`: startup no longer refuses (decision 20, replaces the 2026-09-24 text above); new delete-credential requirement (decision 22).
> - `admin-api`: new requirement for the webhook-secret endpoint's own contract (decision 23).
> - `operator-panel`: the no-key (DEGRADED) mark alongside read-only (decision 20); the delete-key control (decision 22); the webhook secret revealed only on explicit request, superseding the 2026-09-24 "never rendered" text (decision 23).
> - `capital-allocation`: the read-only-exchange requirement retitled and widened to cover `NO_KEY` explicitly, not only by cross-reference (decision 20).
> - `strategy-lifecycle`: unchanged — none of decisions 20–23 touch allowed pairs, archive, or the enablement log.
> - `performance-reporting`: unchanged.
