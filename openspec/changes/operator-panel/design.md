# Design: Operator panel

SDD phase DESIGN, 2026-09-24. HEAD `a7f3297`. Preflight: auto / hybrid / auto-chain / 400.
Inputs: `proposal.md` (Engram `sdd/operator-panel/proposal`), `owner-decisions.md` (1–18, binding, none reopened), decision 19 (Engram `sdd/operator-panel/visual-design`: visual direction A), `exploration.md`, and the seven specs under `specs/`. This file is the record; Engram `sdd/operator-panel/design` is the mirror.

> **Revised 2026-09-24 (revision pass before `sdd-tasks`).** Applied: owner decision 18 (ONE key per exchange; supersedes decision 7, rule 8(c) and OQ4), decisions 15–17 (OQ1–OQ3 resolved), decision 19 (visual direction A), the spec realignment of findings F1–F4 and F8, the removal of the wrong finding F10, the smaller unit-1a probe, and a recomputed PR plan and forecast. Migrations are renumbered because the purpose migration is gone: lifecycle is now **0024**, pool capital at open **0026**, credential snapshot **0027**. Each changed section carries its own "Revised 2026-09-24" note.
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

> **Revised 2026-10-02 (decisions 40 and 41, unit 9v).** Allowed pairs are validated against the venue's public catalogue, and the dialog's free text becomes a selector. The design is the last addendum of this file, "Addendum: allowed pairs validated against the venue catalogue". It changes three rows of the § 14 endpoint table (marked there) and the `NewStrategyDialog` and `AllowedPairsEditor` entries of § 15. Nothing else in this file is reopened.

> **Revised 2026-10-02 (decision 42, unit 9x).** A strategy with no history can be deleted; one with any history can only be archived. The design is the last addendum of this file, "Addendum: deleting a strategy that has no history". It adds one row to the § 14 endpoint table (marked there), one control to the strategy detail view of § 15, and it corrects § 8's "strategies are never deleted". Archive itself is unchanged: still terminal, still never reversed. Three questions for the owner are open in its § L.

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
| `pool_total_at_open` on `Reservation` | **domain**/allocation (`reservation.py`) | `Decimal \| None`. `None` only on rows written before 0026 |
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

**Choice**: keep `exchange_credentials` as it is, with `ux_exchange_credentials_one_active_per_exchange` as the one-active rule. `load(exchange)`, `store(credential)` and `hints()` keep their signatures. The only schema change to credentials is the save-time snapshot (migration **0027**, decision 4).

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

> **Superseded in part, 2026-09-29 (decisions 24 and 30).** Probe P6 showed that nothing reachable from the VPS reveals a Binance key's trade or withdraw permission. The trade-capability derivation (`enableFutures`), the Binance `apiRestrictions` read and the migration 0027 bullets below are replaced by "Addendum: key policy after probe P6 (decisions 24 and 30)": `permissions JSONB` is not stored, provenance columns are, and the `PUT`/`GET /credentials` shapes in § 14 change with it. Where they disagree, the addendum wins.

> **Revised 2026-09-24 (decision 18).** One slot per exchange; rule 8(c) and its two refusals are removed; a key that cannot trade is accepted with a warning. Migration renumbered 0027 → 0026, and again 0026 → **0027** on 2026-09-28 (decision 25's signal-outcome migration took 0025, shifting every later one), and it now also adds `trade_capable`.
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
- **Migration 0027** adds to `exchange_credentials`: `permissions JSONB NULL`, `validated_at timestamptz NULL`, `CHECK ((permissions IS NULL) = (validated_at IS NULL))`, and `trade_capable boolean NOT NULL`, added with `DEFAULT true`, backfilled, and then the **default dropped**.
  - **The backfill to `true` is correct by construction.** Every existing row was sealed by a `store_*_credentials.py` that refuses keys that cannot trade (`store_bybit_credentials.py:136-143`, `store_binance_credentials.py:137-144`). Pionex rows are backfilled too; nothing reads them.
  - **The default is dropped on purpose.** An insert that forgets `trade_capable` must fail. Defaulting to `true` would let a read-only key through to the venue, the failure decision 18 moves up front.
  - **The downgrade refuses while any row has `trade_capable = false`**, naming the count: dropping the column would make a read-only key look trade-capable to nothing and silently lose the fact. The 0013 precedent: the owner deletes rows by hand if that is really wanted.
- Rows sealed before 0027 show `permissions: null`, rendered as "not validated", and `trade_capable: true`.
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

**An exchange with no known pool (owner decision 31).** `DELETE /api/credentials/{exchange}` for an exchange outside `KNOWN_FUTURES_POOLS` (Pionex today) answers 404 "not served by this panel", like the `PUT` (K5). It is decided before anything below runs: no advisory lock, no row read, no exposure query, and never a 500. The key stays active and is managed only through its store script. The downside, accepted: the key is listed in Settings but cannot be removed from the panel.

Preconditions, both must hold:
- no strategy bound to that exchange's one pool is currently enabled;
- the pool holds no open exposure: no allocation with ledger net ≠ 0 (all spellings merged), no live reservation (`PENDING`/`SUBMITTED`, `terminal_at NULL`), no `SUBMITTED` in-flight attempt (opens via `reservation.strategy_id`, closes via `closes_allocation_id` → reservation) — decision 8's `StrategyExposurePort` query shape, widened from one strategy to every strategy bound to the pool.

```
DELETE /api/credentials/{exchange}
DeleteCredential ─ exchange in KNOWN_FUTURES_POOLS? no ─► 404 not served (decision 31), nothing taken
   pg_advisory_xact_lock(LockKey(pool)) ─────────────────────────────────────────────────────┐ same key ArchiveStrategy and AllocateCapital take, taken FIRST
   SELECT exchange_credentials WHERE exchange=... AND is_active FOR UPDATE ──────────────────┤ the row lock, SECOND (lock order: pool advisory lock, then row locks)
   no active row? ─► 404 no active credential
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

**The allocation's own pool re-check (W1, added after the PR 8b-2 verification).** `UpdateStrategy` (the PATCH that sets `enabled`) takes only the strategy row lock, never the pool lock, so a strategy can be enabled and committed while a delete holds the pool lock, after the delete already read an empty exposure. A signal for that strategy passes decision 4a's `NO_KEY` check (the key is not yet deactivated) and queues on the pool lock; the delete then commits, and the allocation would resume, see an enabled strategy, and reserve capital on a keyless exchange that `PlaceOrder` can never use. So, in the same in-lock re-check that re-reads the policy, `AllocateCapital` also reads whether the pool is still enabled, through `PoolStatusPort.is_disabled` (adapter: `SqlAlchemyPoolStatus`, a plain column SELECT on the allocation's session, READ COMMITTED, **no `FOR UPDATE`**: the delete's `disable()` updates that row, and a waiting allocation must not hold a lock the delete needs). The read MUST follow `acquire`; a read before the wait sees the pool enabled. A disabled pool ends the allocation as the skip `POOL_DISABLED` (reason-code table, row 24): one WARNING, the outcome recorded per decision 25, nothing reserved. A pool with no row is not reported disabled; the balance read keeps failing loudly for that misconfiguration as before. `UpdateStrategy`'s locking is unchanged, and DRY_RUN makes no difference: the pool flag is real state in both modes.

**Replacing a key is unaffected.** A `PUT` that supersedes an active key (rotation, decision 4) never runs this precondition; only `DELETE` does. Saving a new key for an exchange whose pool was disabled by a prior delete re-enables it (decision 21's upsert), exactly like a first save.

**The `capital_pools.enabled` write and the worker.** Per F11, the worker's own allocation path reads `capital_pools` once, at startup. `DeleteCredential`'s write is correct and immediately visible to `GET /pools` and to decision 4a's per-signal credential check — both of what actually refuses a live open and what the panel shows. It is not immediately visible to an already-running worker's in-memory `PoolConfig` map. This is an accepted rollout cost, not a race: the credential deactivation alone already refuses every opening signal on that exchange from the next signal on, regardless of whether the worker has reloaded its pool snapshot.

**Response**: 200 with the exchange's `GET /credentials` entry now `status: EMPTY` (last4/permissions/trade_capable all `null`) — the same shape an exchange that was never keyed already returns.

**Rejected**: refusing the delete only on `enabled` and ignoring open exposure — decision 14's same reasoning as archive: a position stranded with no key left to close it is unrecoverable through this app. Also rejected: deleting the row outright — decision 22 keeps history, following decision 4's rotation precedent (a supersede never deletes either).

### 5. Where encryption happens: in the API process, seal-only by type

**Choice**: the API process validates and seals. `SaveCredential` depends on `CredentialWriterPort` (`store`, `hints`), which has **no `load`**, so mypy strict makes a decrypt from the API path a type error. A structural test asserts that no module under `accounts/infrastructure/credentials_router.py` or `accounts/application/save_credential.py` references `.load(`. The API lifespan gains **startup invariant 5**: `EnvelopeCipher.from_base64(settings.master_encryption_key)` must succeed, so a misconfiguration fails at boot, as it does in the worker (`main.py:632`). **Dropped (owner decision 2026-09-30, design K5):** this invariant was NOT built; see K5 (line ~1809).

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

### 10. Pool capital at open: migration 0026

`reservations.pool_total_at_open Numeric(38,18) NULL`, `CHECK (pool_total_at_open IS NULL OR pool_total_at_open > 0)`. It is safe as `> 0` because a reservation exists only when `granted > 0` and `granted ≤ available ≤ total`.

**Written**: inside `AllocateCapital`'s locked transaction, `Reservation(..., pool_total_at_open=pool_balance.total)` from the `self._pool_balance.read(...)` call in `allocate()` (`allocate_capital.py:201` after PR 5b's additions; the line drifts, the call does not) (F1). It is the same balance the decision was made from, and there is no new read or lock. The value belongs to the reservation's own pool, in that pool's settlement currency (rule 5), and is never summed across pools (rule 7).

**Never zero (as built, PR 6a).** `AllocateCapital._pool_total_to_record` stores the total only when it is `> 0`; otherwise it stores `NULL` and logs one ERROR. ERROR, not WARNING: the trade is lost to the curve for good (the value cannot be backfilled), and only ERROR reaches the operator's alerts. A non-positive total cannot reach a granted insert from the production source: `decide()` grants only when `available > 0` (`decision.py:53`), and the snapshot the source reads has `CHECK total >= available` (`accounts/infrastructure/models.py:67-68`, migration 0016). `PoolBalancePort` does not promise that on its own, so the guard keeps a broken source from aborting a granted allocation on the column's CHECK.

**Why this read and not the pre-lock one** used to size `requested`. The pre-lock and in-lock reads can differ by one snapshot refresh. The in-lock value is the one consistent with `granted` under rule 4. So `granted / pool_total_at_open` may differ slightly from `allocation_percent`, and that is correct: the denominator is the pool, not the policy.

- `_resume` (a retried allocation) returns the existing row unchanged.
- Rows written before 0026 have `NULL`. Their trades count in PnL amounts and are excluded from % figures, with the count reported (spec: "treat as absent, never reconstruct").
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

**As built (PR 6b, unit 3b).**
- The port is `AllocationFillsSourcePort.pool_fills(pool: PoolKey) -> PoolFills`. It takes exactly ONE pool and there is no method that reads several, so a cross-pool total cannot be requested (rule 7). `PoolFills` holds the `FillGroup` aggregates and `rehearsal_fill_count`, a second `count(*)` over the same pool of the fills the `NOT LIKE` left out. Without it a rehearsal fill could never be reported as excluded, because the aggregate never sees it.
- **Closed** is net base EXACTLY zero (no tolerance, no venue step) with a BUY and a SELL behind it. It is the ledger's own rule (`net_positions_by_symbol` drops a group only at exact zero, and `ClosePosition` sizes from that net), so a trade is closed precisely when it has left the open positions. A tolerance would book a realized PnL for money still at risk.
- Fee rules in `derive_trade`: a settlement-currency fee is subtracted; a base-currency fee is not subtracted from PnL but IS part of the net-base test; a third-currency fee with `fee > 0` sets `fees_complete=False` and is omitted; a zero fee in any currency changes nothing.
- An allocation opened by a rehearsal fill and closed by a live one reaches the domain as a lone SELL. It is OPEN, not a trade.
- A symbol that has no base currency in the pool's settlement currency cannot be tested. `derive_trades` returns those allocation ids in `unresolved_allocation_ids` instead of raising for the whole pool or dropping them silently.

**As built (PR 6b, unit 3c).**
- The five pure functions and `build_pool_performance` live in one module, `performance/domain/curve.py`. `ReadPoolPerformance(fills, clock).read(pool)` composes them; "now" comes from `ClockPort`.
- Drawdown takes `E_0 = 1` as the first peak, so a loss on the very first day is already a drawdown.
- The monthly grid has one entry per UTC month that has at least one closing day. A month with no closing trade is absent, not a fabricated 0%.
- A range includes its start instant and `now`, and is compounded from the trades inside it, not sliced from the all-time curve. `pnl` counts trades without capital; `return` cannot.
- Exclusions as built: `open_trade_count`, `rehearsal_fill_count`, `no_capital_at_open`, `unconverted_fee`, `unresolved_allocation_count`. The design listed the middle two only as prose; the rehearsal count needed the source to count what it filtered.
- Rule 7 in the read: the signature takes one `PoolKey`; the port has no multi-pool method; every source row is checked against the requested pool before deriving; `build_pool_performance` re-checks every trade. Either check raises `InvariantViolation`.
- A naive `closed_at` raises, because `astimezone` would read it in the host zone.

**As built (PR 6c, unit 3d).**
- `by_pair(trades)` (`performance/domain/by_pair.py`) is pure and takes trades only, no allowlist, so a pair removed from the allowlist keeps its history (decision 15). Trades arrive already one per allocation (`derive_trades` groups by `allocation_id`); `by_pair` then re-keys with `market_key`, so a trade carrying any raw spelling still lands in the one row of its market. Per pair: `trade_count`, `pnl` (every closed trade, including those without capital), and `value`, the pair's contribution (the pool's algorithm over that pair's trades), or `None` when no trade of the pair has a return (never a fabricated 0).
- `ReadStrategyPerformance(fills, clock).read(strategy_id, pool)` runs `build_pool_performance` over the strategy's trades only, so `r_i = pnl_i / pool_total_at_open_i` is the POOL's capital, as in § 11. It returns `StrategyPerformance(strategy_id, performance, by_pair)`. Its exclusions are the strategy's own; the rehearsal count is per strategy (`PoolFills.rehearsal_for`), which needed the source's rehearsal `count(*)` to `GROUP BY strategy_id`. The pool total stays the sum, so `ReadPoolPerformance` is unchanged.
- **Rule 7 and decision 1 for a strategy.** A strategy lives in one pool, so the read takes the strategy AND its `PoolKey` (the PR 7 router resolves both from the same strategy row and answers 404 first) and asks the source for that one pool. `scope.strategy_groups` refuses a row of any other pool before it filters by strategy, and refuses an allocation whose legs carry two strategy ids. `build_pool_performance`'s own per-trade pool check stays as a second wall. A wrong pool passed by a caller yields an empty result rather than an error, because the ledger cannot tell "no trades" from "not this pool's strategy"; the router is what binds them.
- **Where pagination happens: over the derived trades, in Python.** "Closed" is not a column. It is net base exactly zero under the base-fee rule, and the base currency of a symbol is `base_currency_of`, a domain rule SQL does not have. A SQL keyset would have to replicate both and could disagree with the pool figures on which trades exist. **What bounds the work:** the read is the same single grouped aggregate every performance read already makes, for one pool (about four rows per allocation, riding `ix_ledger_pool_symbol`), sliced to the strategy in memory. It is bounded by the pool's allocation count (hundreds to low thousands, the same premise as § 11 "The read"), not by the page size; the page size (`MAX_PAGE_SIZE` 200, default 50, else `InvalidPageRequest`) bounds the response. If a pool's trade count ever makes that aggregate slow, the step is a materialized trades table written at close, not a SQL re-derivation.
- **Cursor.** `TradeCursor(closed_at, allocation_id)`, always both, on the wire two query parameters: `before_closed_at` (ISO-8601 with zone and full microseconds, `timestamptz`'s own precision) and `before_allocation_id` (UUID text). A page holds the trades strictly below the cursor in the order `(closed_at, allocation_id.int)` descending; `next_cursor` is the last trade served and is `None` on the last page (the read looks one past the limit, so a last page that is exactly full has no cursor). A cursor `closed_at` with no zone is refused. Half a cursor is unrepresentable here; PR 7's 422 covers the query string.
- **A trade that closes between two page reads** sorts before page 1 (it has the newest `closed_at`), so the walk in progress neither repeats nor loses anything and the trade shows on the next read from the top. A trade that lands after the cursor in the order (a booked close dated earlier) is served once when the walk reaches it. Only a trade landing before the cursor, that did not exist when that part was served, is missed until the walk restarts. Tested on real PostgreSQL.
- `ReadStrategyTrades` returns `TradeItem(trade, value)` where `value = pnl / pool_total_at_open` or `None`. **Closed in PR 7a:** the § 14 trades row lists `direction`, which `ClosedTrade` did not carry. It now does: `Direction.LONG` when the allocation's earliest leg is a BUY, `SHORT` when it is a SELL (`derive_trade._direction`; earliest = smallest `first_filled_at`, not the first group in the list; a tie goes to BUY).
- Logging: as for the pool read. `ReadStrategyPerformance` shares `scope.log_exclusions` (WARNING with ids for an unresolvable symbol, INFO counts for no capital and unconverted fee, nothing on a clean read), with the strategy id in the label. `ReadStrategyTrades` logs only the WARNING, since the INFO counts belong to the report and not to every page of a list.

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
| `POST /strategies` | `RegisterRequest` + `allowed_pairs: [str] (min 1)` | 201 `StrategyView` | 409 duplicate id/name; 422 no pairs / bad pool; **(unit 9v, decision 41)** 422 `UNKNOWN_PAIRS` (+ `unknown`), 422 `PAIR_CATALOGUE_NOT_SERVED`, 502 `PAIR_CATALOGUE_UNAVAILABLE` | `RegisterStrategy` (+ `PairCatalogPort`, addendum 9v § E) |
| `PATCH /strategies/{id}` | `{name?, fill_mode?, allocation_percent?, enabled?}` | `StrategyView` | 404; 409 `STRATEGY_ARCHIVED`; 409 name taken | `UpdateStrategy` (+ event) |
| `PUT /strategies/{id}/allowed-pairs` | `{pairs: [str] (min 1)}` | `StrategyView` | 404; 409 `STRATEGY_ARCHIVED`; 422 empty/invalid; **(unit 9v, decision 41)** for ADDED pairs only: 422 `UNKNOWN_PAIRS` (+ `unknown`), 422 `PAIR_CATALOGUE_NOT_SERVED`, 502 `PAIR_CATALOGUE_UNAVAILABLE`; 409 `PAIRS_CHANGED` | `ReplaceAllowedPairs` (+ `PairCatalogPort`, addendum 9v § E) |
| `GET /pools/{exchange}/{venue}/{ccy}/available-pairs` **(unit 9v, decision 41)** | — | `{pool: {exchange, venue, settlement_currency}, pairs: [str], count}`; `pairs` sorted, in `market_key` form | 404 `no such pool`; 404 `PAIR_CATALOGUE_NOT_SERVED`; 502 `PAIR_CATALOGUE_UNAVAILABLE` | `ReadAvailablePairs` (addendum 9v § F) |
| `POST /strategies/{id}/archive` | — | `StrategyView` (idempotent) | 404; 409 `STILL_ENABLED`; 409 `OPEN_POSITION` (+ `symbols`, `allocations`, `live_reservations`, `in_flight_attempts`) | `ArchiveStrategy` |
| `DELETE /strategies/{id}` **(unit 9x, decision 42)** | — | **204**, no body | 404 unknown id (also a repeated delete); 409 `STILL_ENABLED`; 409 `HAS_HISTORY` (+ `history: {signals, reservations, execution_attempts, ledger_entries, booking_proposals, enablement_events}`, six counts) | `DeleteStrategy` (addendum 9x § D, § F) |
| `GET /strategies/{id}/events` | — | `[{enabled, occurred_at, origin}]` | 404 | `SqlAlchemyEnablementLog` |
| `GET /pools` | — | `[{exchange, venue, settlement_currency, enabled, balance: {total, available, observed_at, stale} \| null, reserved, allocatable}]` | — | `capital_pools` ⋈ `pool_balance_snapshots` + `sum_active` (`allocatable = max(0, available − reserved)`, computed server-side) |
| `GET /performance/pools/{exchange}/{venue}/{ccy}` | — | `PoolPerformance` (below) | 404 unknown pool | `ReadPoolPerformance` |
| `GET /performance/strategies/{id}` | — | `PoolPerformance` + `by_pair: [{pair, trades, pnl, return}]` | 404 | `ReadStrategyPerformance` |
| `GET /performance/strategies/{id}/trades?limit=50&before_closed_at=&before_allocation_id=` | — | `{trades: [{allocation_id, pair, direction, opened_at, closed_at, pnl, capital_at_open\|null, return\|null, fees_complete}], next_cursor: {before_closed_at, before_allocation_id}\|null}` | 404; 422 half a cursor, naive `before_closed_at`, `limit` outside 1..200 | `ReadStrategyTrades` |
| `GET /credentials` | — | `[{exchange, status: STORED\|EMPTY, last4\|null, label, stored_at, validated_at\|null, trade_capable\|null, permissions\|null}]`, one entry per exchange that has an active credential, a credential history row (any superseded or deactivated row), **or** an enabled pool (decision 20's DEGRADED case) | — | `vault.hints()` (all rows, not only active; no decrypt) |
| `DELETE /credentials/{exchange}` | — | 200, exchange view with `status: EMPTY` | 404 not served (an exchange with no known pool, decision 31, checked first); 404 no active credential; 409 `EXCHANGE_NOT_FLAT` (+ `enabled_strategies`, `symbols`, `allocations`, `live_reservations`, `in_flight_attempts`) | `DeleteCredential` (§ 4b) |
| `PUT /credentials/{exchange}` | `{api_key, api_secret: SecretStr, label?}` | exchange view + `warnings: ["READ_ONLY_KEY"]` when `trade_capable=false` | 404 unserved exchange; 422 `KEY_REJECTED` / `WITHDRAW_PERMISSION` (+ `permissions`); 502 `VENUE_UNREACHABLE`; 409 `CONCURRENT_SAVE` | `SaveCredential` (also enables the exchange's pool, decision 21) |
| `GET /webhook-secret` | — | `{secret}`, `Cache-Control: no-store`; **503** `{detail}` (also `no-store`, no `secret` key) when the setting is empty | 401 (bearer), 503 | reads `settings.webhook_secret` directly (decision 23). **As built (PR 7b):** no `Pragma` header (the spec asks for `Cache-Control: no-store` alone); the setting is a plain `str`, not a `SecretStr`; an unset secret is refused with a 503 rather than returned as `""`; non-GET methods answer 405 |
| existing `GET /reconciliation/bookings`, `POST .../approve`, `.../reject` | unchanged | unchanged | unchanged (404/409/422/503) | unchanged |

`PoolPerformance` = `{pool: {exchange, venue, settlement_currency}, currency, day_boundary: "UTC", trade_count, total_pnl, max_drawdown, excluded: {open_trade_count, rehearsal_fill_count, no_capital_at_open, unconverted_fee, unresolved_allocation_count}, ranges: [{range: "7D"|"30D"|"90D"|"1Y"|"All", pnl, return, trade_count}], curve: [{date, daily_return, index, drawdown}], monthly: [{year, month, return}]}`. An empty ledger returns zeros and empty arrays, never an error (spec).

**As built (PR 7a), `GET /pools`.**
- One object per row of `capital_pools`, enabled or not (`enabled` says which), ordered by `(exchange, venue, settlement_currency)`. The body is a bare list with no envelope, so there is no place for a total (rule 7). Each pool: `{exchange, venue, settlement_currency, enabled, balance, reserved, allocatable}`; `settlement_currency` is the design's own name for the pool's currency, and no separate `currency` field exists.
- `balance` is `{total, available, observed_at, stale}` from `pool_balance_snapshots` (OUTER join), or `null` for a pool nothing has synced. `stale` uses the allocator's own limit, `balance_snapshot_max_age_seconds` (`DbBalanceSource`), so a snapshot the allocator would refuse is flagged. `observed_at` is ISO-8601 with an explicit offset.
- `reserved` is `SqlAlchemyReservationRepository.sum_active` (allocation/infrastructure/repository.py), called per pool with the request time: reservations in PENDING or SUBMITTED whose `expires_at` is still in the future. It is the query `AllocateCapital` runs under the lock (`reserved_active`), reused rather than rewritten.
- `allocatable = max(0, available - reserved)` (`accounts/domain/pool_overview.allocatable`). **When `balance` is `null`, `allocatable` is `null` too**, not `0`: with no available balance the honest answer is unknown, and the design table did not say. `reserved` is still reported.

**As built (PR 7a), the performance endpoints.**
- **Shape corrections to the table above.** All five exclusions are in `excluded` (the design kept `open_trade_count` beside it and listed two); the range name is `All`, as in the domain and decision 6 (the design wrote `ALL`); a range `return` is never null, a window with no trades returns `0.0000000000`; the curve carries `daily_return` too; the strategy report is the pool report plus `strategy_id` and `by_pair: [{pair, trades, pnl, return|null}]`. The trades response is an object, not a bare list: a bare list has no way to say where the next page starts or that there is none, so `next_cursor` carries the two query parameters to send back.
- **Pool 404.** A pool is unknown when it is not a row of `capital_pools` (`SqlAlchemyPoolLookup`), so a non-existent exchange, a wrong-case currency and a well-formed but unconfigured pool all answer 404 `no such pool`; the path values are strings, not enums, so none of them is a 422. A disabled pool is found.
- **Strategy routes bind strategy to pool.** They take no pool. The router loads the strategy (404 `no such strategy`; archived strategies are found) and reads `PoolKey(strategy.exchange, venue, settlement_currency)`. A test records the pool each read asked for.
- **Wire** (`shared/infrastructure/wire.py`): money and ratios are JSON strings in positional notation (`format(d, 'f')`, never `0E-18`, never `-0`); ratios are rounded half-even to 10 places; instants are UTC and pydantic writes them with `Z`, which the cursor accepts back without URL-encoding a `+`. `return` is a `serialization_alias`. One test walks every response of every read route and fails on any JSON float or exponent.
- **Pagination** as designed: `limit` 1..200 default 50 (else 422), the cursor is both query parameters or neither (half a cursor and a naive `before_closed_at` are 422 with the reason in the body).
- **A refused read** (`InvariantViolation`: another pool's row, an allocation split over two strategies, a non-positive capital) is a fixed 500 `performance data failed an integrity check` and one ERROR with the reason.
- **Cost.** Every request runs the pool aggregate (PR 6c). Measured on the test database with 1,000 closed trades in one pool: median 44 ms (pool report), 46 ms (strategy report), 39 ms (trades page).

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
- **Overview** (sizing: the panel fills the width and the chart is 280 px tall at its measured width, decision 36; pools are ordered by the interim rule of decision 37, which task 11f.1 replaces with USD value): `OverviewPage` (container: pools, performance and credentials for the scoped exchange) → `PoolPanel` ×N, one per pool and never merged (rule 7) → `PoolEyebrow`, `LedgerLine` (with its `RangeSelector`), `ReturnChart` (curve and drawdown as one instrument), `MonthlyGrid` + `MonthlySummary`. Alongside it sits `DecisionRail` (“Needs your decision”): the existing `BookingsListView` logic, filtered by exchange, rendering `BookingCard` with the existing `ConfirmBookingDialog` and `RejectBookingDialog`.
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
- **The chart always shows All.** The range selector drives the ledger line only; in Main.dc.html "30D" is pressed while the axis runs July to November. This avoids rebasing ratios in the browser. **Superseded by decision 33:** the chart follows the selected range, rebased to 0% at the range's start.
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
- Grid rows `64px 1fr`. The top bar (bottom border `rule`, padding 0 28 px, gap 32 px) holds the brand, then `ExchangeTabs` (`nav aria-label="Exchanges"`), a spacer, and the `DRY RUN` badge (amber outline, mono 12 px, `0.12em`, radius 4) shown only when `/health` says `dry_run`. **Superseded by decision 32:** the badge is always visible and reads "Dry run", "Live", "Checking mode" or "Mode unknown".
- Each exchange tab stacks the name (Archivo 15/600) over a mono 11 px sub-label: the pool summary in `ink-3` (for example "USDT pool"), or, for a read-only key, "{category} · read-only key" in `decision`, or, **for a DEGRADED exchange with no key at all** (revised 2026-09-25, decision 20), "no key" in `decision`. Active tab: 2 px `gain` bottom border and `ink`; inactive `ink-2`.
- Body grid `208px 1fr` (Settings, Strategies) or `208px 1fr 360px` (Overview). The left rail (`nav aria-label="Sections"`, padding 24/12, right border `rule`) lists Overview, Strategies, Settings; items padding 12/14, radius 6; active = `bg-panel-2`, `ink`, weight 600.

**Overview** — Main.dc.html. Main column padding 28/36, gap 28. Per pool: the eyebrow and ledger line (left) with the range selector (right, bottom-aligned); the return chart; "Month by month" with the grid and summary. The right rail, `aside aria-label="Needs your decision"` (`bg-panel`, left border `rule`, padding 28/24, gap 14): title "Needs your decision" with the amber "{n} pending" count; a one-line explainer in `ink-2` 13 px ("Closes the venue made that the ledger has not recorded. Approving writes them to the ledger for good."); then one `BookingCard` per proposal (`bg-ground`, `rule` border, radius 8, padding 16): symbol (Archivo 15/600) and expiry (mono 11, `ink-3`); mono 12 px details (strategy, side and size, fill count and last price); "Review and approve" (teal filled, opens the existing confirm dialog) and "Reject" (outlined `rule`), both at least 44 px tall. Empty: "Nothing needs your decision", no amber count.

**Strategies and strategy detail** — Strategy.dc.html, reusing the Overview instruments (`LedgerLine`, `ReturnChart`, `MonthlyGrid`) for one strategy's contribution, plus the lifecycle controls of § 15. Its per-element detail is taken from the mockup at `sdd-tasks`.

**Settings** — Settings.dc.html. No exchange tabs in the top bar. Main column padding 28/36, gap 22, max width 900 px:
- Title "Exchange keys" (Archivo 30/700) and the intro "One key per exchange. Keys are encrypted on the server and never shown again; you only see the last four characters."
- One `ExchangeKeyCard` per exchange (`bg-panel`, `rule` border, radius 10, padding 20, grid `1fr auto`): the name (Archivo 17/600) over a mono 13 px `ink-2` line `key ••••{last4} · reads and trades | reads only · no withdrawal · checked {date}` ("not validated" for keys sealed before 0027); a "Replace key" button (outlined, at least 44 px) and, when a key is active, a "Delete key" button (outlined `loss`, at least 44 px) that opens `DeleteKeyDialog` with an explicit confirmation, rendering the 409 `EXCHANGE_NOT_FLAT` reasons below it in `loss` on refusal (decision 22, revised 2026-09-25). **A read-only key** turns the card border `decision` and adds, in `decision` 13 px: "This key cannot trade. With dry run off, signals for {exchange} are refused until you add a key that can trade futures."
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
| `backend/migrations/versions/0026_reservation_pool_total.py` | Create | `pool_total_at_open` |
| `backend/migrations/versions/0027_credential_snapshot.py` | Create | `permissions JSONB`, `validated_at`, `trade_capable` (backfill true, default dropped), refusing downgrade |
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
| `main.py` | Modify | Five Binance read sites onto the vault; trade-capability wiring; `/api` router, new routers, `mount_panel`, invariant 5 (dropped, K5); skips registering read adapters for a DEGRADED exchange (decision 20) |
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
| Integration (real PG) | 0024–0027 up/down/refusals (Tier B, `alembic upgrade head`); seeding with **different spellings per signal**; the enablement trigger refusing UPDATE/DELETE; 0027 backfills `true` and an insert without `trade_capable` fails; `CONCURRENT_SAVE` by the name `ux_exchange_credentials_one_active_per_exchange`; `VaultTradeCapabilityAdapter` answers without decrypting (a row with garbage ciphertext still answers); `pool_total_at_open` written under the lock; **concurrent archive vs allocation on one pool** (both orders); **concurrent `DeleteCredential` vs allocation on one pool** (both orders, decision 22); `PoolExposureAdapter` sees every strategy bound to the pool, not just one; FOR UPDATE toggle race | Live PostgreSQL (`rules.tasks`) |
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
| **A read-only key reaches the venue on a live open** (added 2026-09-24) | Refused before the lock with one WARNING (decision 4a); a missing `trade_capable` value cannot be inserted | The residual race fails at the venue as today | `ProcessSignalHandler` read-only refusal; 0027 insert without the value fails |
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

**PR 8 (key validation, 0027)**: `alembic upgrade head` then restart both processes. The old code never inserts credentials (only the store scripts do), so no ordering is needed; run the store scripts only from the new code, because 0027 makes `trade_capable` mandatory. After deploy, re-saving each key through Settings records its snapshot (optional; unvalidated rows remain trade-capable by construction). **Revised 2026-09-25 (decision 21):** re-saving Bybit's and Binance's already-active keys through Settings also runs `CapitalPoolWriterPort.enable`, which is a no-op on their already-enabled pool rows (migrations 0017/0018) — nothing to rehearse beyond the existing key-save flow.

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
| 6 | 3a `pool_total_at_open` 0026, live PG (350–500) · 3b fills source + `derive_trade` (700–1,000) · 3c curve/drawdown/grid/ranges, UTC (700–1,000) · 3d strategy + pair stats (400–600) | 2,150–3,100 | Rehearsal-fill count recorded |
| 7 | Read endpoints: pools, performance pool/strategy/trades, `GET /webhook-secret` (decision 23, 150–250) | 950–1,350 | — |
| 8 | 6a key policy + inspectors + 0027 (800–1,100) · 6b `SaveCredential`, credential endpoints, redacted 422, store scripts onto the use case (750–1,000) · 6c `TradeCapabilityPort`, adapters, read-only opening refusal (350–500) · 6d `KNOWN_FUTURES_POOLS`, `CapitalPoolWriterPort`, pool auto-enable on save (decision 21, 300–450) · 6e `DeleteCredential`, `PoolExposurePort`/adapter, `DELETE` endpoint, concurrency test (decision 22, 700–1,000) | 2,900–4,050 | PR 1's P1–P3 recorded |
| 9 | 4b SPA serving, fallback, CSP, invariant 5 (dropped, K5), `panel_dist_dir` | 500–750 | Owner infra steps |
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

## Addendum: signal outcomes (decision 25) — 2026-09-28

Task 5b.1. Verified against the code at HEAD `ea2adb5` (the outcome map in `tasks.md`
was built read-only from `17681ef`; nothing changed on the routing paths below
between those two commits). Covers the status machine, the reason-code table,
the same-commit rule with its two zero-commit exceptions, the 0025 schema, and
the REVERSE rule the owner confirmed as decision 26. Only PR 5b's rows (1–15,
plus the deferrals) are implemented here; PR 5c's rows are listed for
completeness because the Rules block in `tasks.md` binds both PRs at once.

### A. Status machine

```
ACCEPTED → PROCESSING → PROCESSED | REJECTED
ACCEPTED →              PROCESSED | REJECTED     (direct; no interim PROCESSING)
```

`PROCESSED` and `REJECTED` are terminal and are never overwritten. A write
against a terminal signal is a no-op; it logs one WARNING when the outcome it
would have written differs from the one already recorded (same shape as the
guard `AllocateCapital.allocate` already applies to a resumed reservation —
`allocate_capital.py:106-109` — except that guard resumes silently and this
one must also log, because a *different* second outcome for the same signal
is exactly the class of bug decision 25 exists to catch).

*Correction to 5b.3:* the guard reads the row fresh and `FOR UPDATE`
(`populate_existing=True, with_for_update=True`), because the run's shared
session caches the row from `get_by_id` and a plain `get` would read a stale,
non-terminal status. Every `record` call is staged immediately before its
commit, so the signals row lock is always the LAST lock a transaction takes
(after any pool advisory lock and reservation/attempt row locks), which keeps
the lock order.

**The non-warning path (PR 5c unit G).** Two callers meet an already-terminal
signal as the ORDINARY case, not a conflict: a continuation abandoning a signal
that `signal.process` already ended (a REVERSE whose close was refused is
`REJECTED` `CLOSE_REJECTED_BY_VENUE` / `CLOSE_DUST_NOT_CLOSABLE`, and its
seeded continuation later abandons as `AWAITED_CLOSE_FAILED` or
`CONTINUATION_TIMED_OUT`; a signal already `PROCESSED`), and a job that
exhausted its retries after the signal was decided (`JOB_FAILED`). Routed
through `record`, each would log a WARNING for a differing code. So
`SignalOutcomePort` has a second method, `record_unless_terminal(signal_id,
outcome)`: the same fresh `FOR UPDATE` read, a terminal signal is left alone
silently whatever it holds, a non-terminal one is written exactly as `record`
would. It was chosen over "read the status in the caller" because "terminal or
not" must be decided on the LOCKED row: a status read outside the lock races
with a concurrent writer, and the test holds a second session's row lock and
asserts the writer waits (`not task.done()`) and then stays silent. `settle` and
`signal.process` keep `record` and still WARN on a genuine conflict; both sides
are tested on one terminal row.

A signal reaches `PROCESSED` or `REJECTED` directly, with no `PROCESSING` in
between, whenever nothing was ever submitted to an exchange (every refusal
and skip, rows 1–8 below). It passes through `PROCESSING` only when an order
was placed and its fate is still open (rows 9–15 landing on `PLACED`).
Signals ingested before migration 0025 stay `ACCEPTED` forever; nothing
reconstructs their outcome.

### B. Reason-code table

| # | Reason code | Decided by | Job | Recorded in |
|---|---|---|---|---|
| 1 | `UNTRADABLE_POOL` | `process_signal.py::_refuse_untradable_pool` | signal.process | 5b |
| 2 | `STRATEGY_ARCHIVED` | `process_signal.py::_refuse_archived_strategy` (`handle`, `open_now`) | signal.process or continuation | 5b writes it; 5c.5 reuses the same write inside the continuation's own commit |
| 3 | `PAIR_NOT_ALLOWED` | `process_signal.py::_refuse_unlisted_pair` | signal.process or continuation | 5b writes it; 5c.5 reuses it |
| 4 | `DIVERGENT_HOLDING_GHOST` / `DIVERGENT_HOLDING_AMBIGUOUS` | `holding_guard.py::_classify_divergence` | signal.process | 5b |
| 5 | `IN_FLIGHT_TIMEOUT` | `holding_guard.py::_on_in_flight`, past the age bound | signal.process | 5b |
| 6 | `BALANCE_UNAVAILABLE` | `process_signal.py`, balance refresh UNAVAILABLE | signal.process | 5b |
| 7 | `NOTHING_TO_ALLOCATE` | `process_signal.py::_refuse_non_positive_request` | signal.process | 5b |
| 8 | the existing `skip_reason` value (`STRATEGY_DISABLED`, `STRATEGY_ARCHIVED`, `POOL_DISABLED`, `NO_AVAILABILITY`, `INSUFFICIENT_AVAILABILITY`, `REQUEST_BELOW_MIN_ORDER_SIZE`, `PARTIAL_BELOW_MIN_ORDER_SIZE`) | `allocate_capital.py`, four SKIP sites (pre-lock, in-lock strategy re-check, in-lock pool re-check, `decide()`) | signal.process | 5b |
| 9 | `RESERVATION_EXPIRED_BEFORE_SUBMIT` | `place_order.py`, `ABORTED_EXPIRED` | signal.process | 5b |
| 10 | `ORDER_NOT_PLACEABLE` | `place_order.py`, `REFUSED` (`OrderNotPlaceable`) | signal.process | 5b |
| 11 | `ORDER_REJECTED_BY_VENUE` | `place_order.py`, `FAILED` (venue `ExchangeError`) | signal.process | 5b |
| 12 | — (`PLACED` → `PROCESSING`, not final) | `place_order.py` | signal.process | 5b |
| 13 | `CLOSE_DUST_NOT_CLOSABLE` | `close_position.py`, `NOT_CLOSABLE` | signal.process | 5b |
| 14 | `CLOSE_REJECTED_BY_VENUE` | `close_position.py`, `FAILED` | signal.process | 5b |
| 15 | — (`PLACED` → `PROCESSING`, not final) | `close_position.py` | signal.process | 5b |
| 16 | — (`FILLED` → `PROCESSED`; a REVERSE's close writes nothing, decision 26) | `settle_execution.py`, `settle()` | execution.settle | 5c (unit F) |
| 17 | `ORDER_NEVER_REACHED_EXCHANGE` | `settle_execution.py::_release_never_placed` (an open, and a close linked to a signal) | execution.settle | 5c (unit F) |
| 18 | `REVERSE_NEW_SIDE_UNHOLDABLE` (added by decision 26; the map recorded none, see "Map corrections") | `process_signal.py::_note_unexecuted_tail` | signal.process | 5b |
| 21 | `NO_POSITION_TO_CLOSE` (decision 27: a releasing CLOSE or REVERSE with no prior reservation; a REVERSE's detail says the new side was not opened) | `process_signal.py::_handle_releases`, the `prior_reservation_id is None` early return | signal.process | 5b |
| 22 | `EXCHANGE_KEY_READ_ONLY` (added by unit 6c, decision 18: a live open whose exchange's active key cannot trade) | `process_signal.py::_refuse_read_only_exchange` | signal.process or continuation | 8a-4 |
| 23 | `EXCHANGE_HAS_NO_KEY` (added by unit 6c, decision 20: a live open on an exchange with no active key) | `process_signal.py::_refuse_read_only_exchange` | signal.process or continuation | 8a-4 |
| 24 | `POOL_DISABLED` (added after the PR 8b-2 verification, W1: a pool disabled by `DeleteCredential` while an allocation, whose strategy was enabled under the delete's lock, waited for that same lock) | `allocate_capital.py`, the in-lock re-check (`PoolStatusPort.is_disabled`, read after `acquire`) | signal.process or continuation | PR 8b-2 (W1 fix) |
| — | `SIGNAL_SUPERSEDED` | `open_after_close.py::poll`, a newer signal for the same strategy/symbol arrived | signal.open_after_close | 5c (unit G) |
| — | `AWAITED_CLOSE_FAILED` | `open_after_close.py::poll`, an awaited close is FAILED | signal.open_after_close | 5c (unit G) |
| — | `CONTINUATION_TIMED_OUT` | `open_after_close.py::poll`, past `max_signal_age_seconds` (branch 3 after the closes filled, or branch 4) or `settle_timeout_seconds` | signal.open_after_close | 5c (unit G) |
| — | `JOB_FAILED` | any of `signal.process` / `signal.open_after_close` / `execution.settle` exhausting retries to `FAILED` | (a job-kind-agnostic queue tells an observer; a separate reader resolves the signal, § F) | 5c (unit H) |

Rows 19–20 (a duplicate webhook delivery, an idempotent close replay) never
produce a *second* outcome for a signal; they are the ordinary case the
terminal-write guard in § A already covers, not new codes.

**`refused` vs. `failed`.** `ProcessSignalResult` carries these as two
separate fields (`process_signal.py:289-293`). Rows 1–7 and row 18 set
`refused`; rows 9–11 and 13–14 set `failed`. The 5b.10 writer must read
whichever field the result actually populated for that branch and pick the
reason code from the table above accordingly — the two fields are not
interchangeable and neither is ever set with the other in the same result.

### C. Same-commit rule

Every write in the table below is staged on the SAME SQLAlchemy session,
immediately before the specific `commit()` call named, never a separate
later transaction. Two rows have no existing commit to attach to at all;
5b.10 must add one, right at that point, rather than folding the write into
a neighbouring commit.

| Rows | Physical commit | Notes |
|---|---|---|
| 1, 2, 3, 6, 7 | **none exists** on these `signal.process` paths (added in 5b.4: `ProcessSignalHandler._reject` stages the write and commits) | not listed by the original map; nothing else is written on them |
| 4, 5 | inside `HoldingGuard` / its caller before `AllocateCapital` is ever reached — no reservation exists yet; 5b.4 commits in `_reject`, the caller | no schema write beyond the signal row itself |
| 8, pre-lock (`STRATEGY_DISABLED`) | **none exists** — `allocate_capital.py:113-131` returns before acquiring the lock or calling `commit()` | 5b.10 must add a commit here |
| 8, in-lock (`STRATEGY_DISABLED` / `STRATEGY_ARCHIVED`) | `allocate_capital.py:180` | |
| 8, in-lock pool re-check (`POOL_DISABLED`) | `allocate_capital.py`, right after the strategy re-check and before the balance read: staged, then the commit that releases the pool lock | one WARNING, the logged message is the detail; nothing is reserved |
| 8, `decide()` SKIP | `allocate_capital.py:235` (the same commit a granted reservation's insert would use) | |
| 9 | `place_order.py:111-112` (`mark(RELEASED)` + commit, pre-submit) | |
| 10 | `place_order.py:155-156` (`mark(RELEASED)` + commit, before the network call) | |
| 11 | `place_order.py:208-210` (`mark(RELEASED)` + `mark_failed` + commit, after the network call) | |
| 12 (PROCESSING) | `place_order.py:228-229` (`mark_placed` + commit) | not the earlier pre-network commit at line 196, which only records `SUBMITTED` to the attempt table, not that the exchange accepted the order |
| 13 (`NOT_CLOSABLE`) | **none exists** — `close_position.py:178-183` returns before `self._attempts.insert(...)` or any `commit()` | 5b.10 must add a commit here |
| 14 | `close_position.py:225-226` (`mark_failed` + commit, after the network call) | |
| 15 (PROCESSING) | `close_position.py:246-247` (`mark_placed` + commit) | |
| 21 (`NO_POSITION_TO_CLOSE`) | **none exists** on this path: `_handle_releases` returned with no write; it now goes through `_reject`, which stages the outcome and commits | one WARNING, the logged message is the detail; nothing closes or opens |
| 16 (`PROCESSED`) | `settle_execution.py`: the one commit after `mark_filled` and the reservation mark | the outcome is staged last, so the signals row lock is the last one taken; an open resolves the signal through `reservation.signal_id`, a close through `execution_attempts.signal_id` |
| 17 (`ORDER_NEVER_REACHED_EXCHANGE`) | `settle_execution.py::_release_never_placed`: the release commit | the message is built once, recorded as the detail, then logged with `"%s"` |
| Continuation abandonments (`SIGNAL_SUPERSEDED`, `AWAITED_CLOSE_FAILED`, `CONTINUATION_TIMED_OUT`) | `main.py::handle_signal_open_after_close`: the trailing `session.commit()` after `open_after_close.poll(job)` | `poll` never commits and nothing else is written on these paths, so the staged outcome rides that one commit. A deleted signal writes nothing. Written with `record_unless_terminal` (§ A) |
| Continuation `open_now` (rows 2-15 reused) | the same commits as in `signal.process` (`_reject`, `AllocateCapital`, `PlaceOrder`, `ClosePosition`), on the continuation job's own session | no new write: `open_now` reaches the same `_handle_consumes`; proven end to end on real PostgreSQL |
| `JOB_FAILED` | `job_queue.py::fail()`'s own commit: the observer runs between the `FAILED` status `UPDATE` and the `commit()`, on the queue's session, under a SAVEPOINT | staged with the status, so the two commit together or not at all (§ F). Written with `record_unless_terminal` (§ A) |
| Deferral: in-flight wait | `process_signal.py`, `_handle_consumes`: the `commit()` that follows `open_after_close.seed(...)` | `PROCESSING` is staged between the seed and that commit, so the status and the continuation row are durable together (also on the `open_now` re-deferral, at `poll + 1`) |
| Deferral: real orphan | the FIRST commit inside `CloseOrphans.close`: a close's own first commit (`SUBMITTED`, or the NOT_CLOSABLE commit), or the final commit when no close was placed | `PROCESSING` is staged in `_handle_consumes` immediately BEFORE `close_orphans.close(...)`, so it rides the same commit as the seed `CloseOrphans` stages first |
| 18 | **none exists** on the handler side: `signal.process` commits right after `ClosePosition` returns (PR 5b2 added `await self._commit.commit()` in `_note_unexecuted_tail`) | written only when the close was placed (`result.executed`); a refused close already ended the signal with the CLOSE's code |

**As built in PR 5b2 (unit C).** The rows above landed as designed, with these
differences, all verified against the code:

- Row 13's added commit sits at the `OrderNotPlaceable` branch of
  `ClosePosition.close` and runs **whether or not a signal is attached**: with
  `signal_id=None` (an orphan close) nothing is recorded, but the commit still
  makes durable whatever the caller staged before the call (a continuation
  seed). Before this the seed of a dust close rode the handler's trailing
  commit.
- `PlaceOrder` and `ClosePosition` do not take `SignalOutcomePort` directly.
  `execution` declares `OrderOutcomeRecorderPort` (`record_processing`,
  `record_rejected`) in `execution/application/ports.py`, adapted by
  `signals/infrastructure/order_outcome_recorder.py`, the same consumer-side
  shape as `SkipRecorderPort`. `ReservationSnapshot` gained `signal_id`: the
  domain `Reservation` had it, the execution-side snapshot did not.
- `CloseCommand.signal_id` is `UUID | None`, required with no default (the map
  said `UUID`). The two callers: `ProcessSignalHandler._handle_releases` passes
  the signal; `CloseOrphans` passes `None` on purpose, because a dust or
  refused orphan close must not REJECT the open that is deferred behind it.
- Row 18's detail is the logged partial-REVERSE message plus "the close was
  submitted and spot cannot hold the new short". A second delivery stages the
  identical outcome, so the terminal guard treats it as a silent repeat.
- `outcome_detail` for rows 9-11 and 13-14 is the exact message already
  logged: each message is built once, recorded, and logged with `"%s"`.
- **Lock order on the orphan deferral.** Every other write in this table
  takes the signals row lock LAST, right before its commit. The orphan
  deferral cannot: the commit that makes the seed durable is inside
  `CloseOrphans` (inside `ClosePosition.close`), so `PROCESSING` is staged
  first and the close's own inserts follow. This is safe because the only
  other path that locks THAT signal's row is another delivery of the same
  `signal.process` job, which takes it in the same order, so the two queue on
  the signals row and never cross-wait; every other actor's locks are on
  different rows. Do not "fix" it by moving the write after the close: the
  close's commit would then make the seed durable without the status.
- **Rows 19-20 needed no production code.** A duplicate delivery
  (`insert_or_get` -> `inserted=False`, `ON CONFLICT DO NOTHING`) never touches
  the row, and the idempotent close replay and the FAILED-reverse replay in
  `_handle_releases` stage nothing. The proof is negative and therefore lives
  in tests that hold a terminal outcome, replay, and assert the row and the
  terminal guard's WARNING channel are both untouched.

**As built in PR 5c (unit F, rows 16-17 and the close linkage).**

- `execution` declares `SettleOutcomeRecorderPort` (`record_open_filled`,
  `record_close_filled`, `record_never_placed`) in `execution/application/ports.py`,
  adapted by `signals/infrastructure/settle_outcome_recorder.py`: the same
  consumer-side shape as `OrderOutcomeRecorderPort`. `SettleExecution` takes it as a
  required constructor argument, wired in `main.py::_build_settle_execution`.
- `ExecutionAttempt.signal_id` (default `None`) is written on the attempt insert by
  `PlaceOrder` and `ClosePosition`. A close resolves its signal through this link,
  never through `reservation.signal_id`: for a close `allocation_id` is the OPENING
  allocation, so its reservation names the opening signal. A NULL link (an orphan
  close, or any attempt written before 5c) records nothing at settle.
- **How settle learns a signal is a REVERSE (decision 26).** The kind is stored on
  neither the signal row nor the attempt; it is derived by `SignalContextAdapter` at
  routing time from the signal's `position_size` against the previous signal's.
  `SignalSettleOutcomeRecorder._is_reverse` repeats that derivation
  (`find_prior` + `PositionTransition.classify`), so settle stays kind-agnostic and
  the answer cannot differ from the one routing used (both inputs are immutable).
  A filled REVERSE close writes nothing, which covers both the `PROCESSING` case
  (its open half decides) and a spot REVERSE already `REJECTED`
  `REVERSE_NEW_SIDE_UNHOLDABLE`, where a differing `PROCESSED` would reach the
  terminal guard and warn on every such trade. A REVERSE close that ends
  `NEVER_PLACED` does end `REJECTED` `ORDER_NEVER_REACHED_EXCHANGE`: nothing
  executed and no open half follows.
- The open half of a REVERSE, placed from the continuation, is an ordinary open, so
  its settle reaches `PROCESSED` through `reservation.signal_id` like any other.

**As built in PR 5c (unit G, the continuation).**

- `OpenAfterClose` takes `outcomes: SignalOutcomePort` (required, wired in
  `main.py::_build_process_signal_handler`). Each abandonment builds its message once,
  records it as the detail through `record_unless_terminal`, and logs it with `"%s"`.
  The commit is `handle_signal_open_after_close`'s trailing `session.commit()`.
- A deleted signal writes nothing (its row is gone) and keeps its existing ERROR.
- The two `CONTINUATION_TIMED_OUT` messages were made exact: branch 4 now says which
  bound fired (the age bound, or the settle timeout), where before it always said "has
  not settled within Ns" even when the age bound fired. Branch 3 (every awaited close
  FILLED, then past the age bound) appends that the awaited close(s) already settled and
  this signal's own open was not placed, when the continuation awaited any close: for a
  REVERSE that is decision 26's "the close executed", and a vacuous await (the in-flight
  deferral) never claims it.
- 5c.5 needed no production code: `open_now` reuses `_reject`, `AllocateCapital` and
  `PlaceOrder` on the continuation's session. It is proven on real PostgreSQL through the
  production composition root: a REVERSE whose close FILLED and whose open is refused
  (`PAIR_NOT_ALLOWED`) ends `REJECTED` with the OPEN's code and a detail saying the close
  executed; one whose open proceeds ends `PROCESSING` with a new SUBMITTED reservation and
  an attempt linked to the REVERSE signal.

**A dependency this implies.** `PlaceOrder` can already reach `signal_id`
without a new parameter: the `Reservation` it loads carries `signal_id`
(`reservation.py:61`, populated at `allocate_capital.py:216`), so
`SignalOutcomePort.record(reservation.signal_id, outcome)` needs only a new
port dependency on `PlaceOrder`, not a `PlaceCommand` field. `ClosePosition`
has no such route — `CloseCommand` (`close_position.py:66-78`) carries
`allocation_id` but never `signal_id`, and nothing else it reads does either
— so `CloseCommand` needs a new `signal_id: UUID` field, threaded in by
`_handle_releases` (which already has it as a parameter). Both use cases need
the same `SignalOutcomePort` handed in and called immediately before each of
their own existing `commit()` calls, which is what makes 5b.6/5b.7's
atomicity test ("inject a failing commit, assert the status and the
reservation mark land together or not at all") meaningful: the outcome write
and the reservation/attempt write must be part of the same flushed unit of
work, not two round trips.

### D. Schema (migration 0025)

Per task 5b.2/5b.3:

- `signals.outcome_reason TEXT NULL` — the stable code from § B.
- `signals.outcome_detail TEXT NULL` — the human-readable message already
  logged for that branch (`refused` or `failed`, § B).
- `signals.decided_at timestamptz NULL`.
- CHECK `status <> 'REJECTED' OR outcome_reason IS NOT NULL`.
- CHECK `status NOT IN ('PROCESSED','REJECTED') OR decided_at IS NOT NULL`.
- `execution_attempts.signal_id UUID NULL`, FK to `signals`, filled starting
  5c (rows 16–17, and via the new `CloseCommand.signal_id` above for closes);
  `NULL` for every attempt written before 5c.

`signals.status` CHECK already allows all four values
(`0002_signals.py:65-66`); 0025 adds no new status value, only the three
columns and their two guards.

**Domain and port (5b.3):**

- `SignalOutcome` — a frozen value object in `signals/domain/`, importing no
  framework: `status: SignalStatus`, `reason: str | None`,
  `detail: str | None`, constructed only through named factories
  (`SignalOutcome.processing()`, `.processed()`,
  `.rejected(reason, detail)`) so an invalid combination (e.g. `REJECTED`
  with no reason) cannot be built at all, ahead of the CHECK constraint.
- `SignalOutcomePort.record(signal_id: UUID, outcome: SignalOutcome) -> None`
  — declared on the signal repository's port in `signals/application/ports.py`,
  implemented by the SQLAlchemy adapter in `signals/infrastructure/`. The
  terminal-state guard (§ A) lives in the adapter, since it is the one place
  that can read the current row and write the new one inside the same
  flushed unit of work without a second round trip.

### E. REVERSE rule — CONFIRMED (decision 26, 2026-09-28)

**The rule:** the close half moves the signal to `PROCESSING`; the open half
decides the final status. If the open is refused after the close executed,
the signal is `REJECTED` with the open's reason, and the detail says the
close executed. The alternative below was offered and declined: the status
column must tell a partial REVERSE (flat, not flipped) from a complete one,
which is the distinction decision 25 exists to make.

**What the rule requires of the implementation:**

- **A REVERSE's close fill never writes a terminal status** while its open
  half is pending. The terminal guard (§ A) never overwrites, so a
  `PROCESSED` written at the close's settle would permanently block the
  open half's `REJECTED`. The close's settle leaves the signal `PROCESSING`;
  only the open half (`open_now`, inside the continuation) ends it. This
  binds 5c.1 and 5c.3.
- **A REVERSE whose close is refused** (rows 13/14) ends `REJECTED` with the
  close's own code, synchronously, in `signal.process`. The open half never
  runs (see below), so there is nothing else to wait for.
- **A spot REVERSE whose new side cannot be held** (row 18,
  `_note_unexecuted_tail`) ends `REJECTED` `REVERSE_NEW_SIDE_UNHOLDABLE`,
  written by `signal.process` after the close is placed. Its detail says
  the close was submitted and spot cannot hold the new short. No pool is
  on spot today, so this path is dormant, but it still gets its code.

**How a REVERSE actually flows today.**
`PositionTransition.classify` gives a REVERSE `effects = (RELEASES,
CONSUMES)` — releases always first (`position_transition.py:57-61`).
`ProcessSignalHandler.handle` routes on `effects[0]`, so a REVERSE always
runs `_handle_releases` before anything else (`process_signal.py:362-365`).
(The file's own module docstring at the top, lines 50-54, still says "a
REVERSE transition is routed through the CONSUMES branch only" — that text
is stale; the routing above has closed the prior leg first since before this
map was written. Not part of this addendum's scope to fix, flagged for
whoever next touches that docstring.)

Inside `_handle_releases` (`process_signal.py:571-698`):

1. `is_reverse_wiring = kind is REVERSE and _new_side_holdable(symbol, next_position_size)`
   — `True` on a perpetual pool, or on spot when the new side is a LONG;
   `False` only for a spot REVERSE whose new side is a SHORT (spot cannot
   hold one).
2. When `is_reverse_wiring` is `True`, the `signal.open_after_close`
   continuation is seeded (`seed(signal_id, [prior_reservation_id], poll=0,
   replay_expected=True)`) **before** `close_position.close()` is even
   called (`process_signal.py:664-674`). `seed()` itself never commits; it
   rides on whichever of `ClosePosition`'s own commits lands first — the
   pre-network `SUBMITTED` commit at `close_position.py:205-213` — so the
   continuation row becomes durable **regardless of how the close turns
   out**: PLACED, FAILED, or NOT_CLOSABLE all commit that same seed.
3. `close_position.close()` runs. `NOT_CLOSABLE` never writes an attempt row
   at all (§ C); `FAILED` writes and commits `mark_failed`; `PLACED` writes
   and commits `mark_placed`.
4. Back in `handle()`: with two effects, `kind is REVERSE and
   _new_side_holdable(...)` (line 369) returns whatever `_handle_releases`
   returned, unchanged, whenever the new side is holdable. Otherwise
   `_note_unexecuted_tail` (line 859) sets `refused` on that same result via
   `dataclasses.replace`, **without touching `executed`**.

**On the three flagged questions, with evidence:**

- **Does `REJECTED` for a REVERSE whose close executed misrepresent that the
  position changed?** Yes, in two places the proposed rule does not name.
  First, the spot-short case (`is_reverse_wiring` `False`): a successful
  close (`PLACED`, later `FILLED`) leaves `ProcessSignalResult.executed =
  True` intact — a real order was placed and a real position change is in
  flight — while `_note_unexecuted_tail` still sets `refused` on it
  (`process_signal.py:886-896`). Whatever writer reads `refused != None` and
  maps it to `REJECTED` (the pattern every row 1–7 follows) would record
  `REJECTED` on a signal that DID move real capital. Second, the case the
  proposed rule's own second sentence names ("the open is refused after the
  close executed") is real but only reachable through the
  `is_reverse_wiring = True` path, where the open runs inside the
  continuation (`open_now` → `_handle_consumes`, 5c.5) — a close that
  genuinely filled, followed by an open refused for an ordinary reason such
  as `PAIR_NOT_ALLOWED`, ends `REJECTED` by design under the proposed rule,
  and that status alone cannot tell an operator "the position moved to flat"
  from "nothing happened at all" — decision 25's own stated goal
  ("the panel can then answer what happened to this signal") is exactly the
  thing this ambiguity defeats.
- **What happens if the close itself is refused (rows 13/14) — does the open
  half ever run?** No. Because the continuation is seeded BEFORE
  `close_position.close()` runs (point 2 above), a FAILED or NOT_CLOSABLE
  close still leaves a durable continuation row awaiting exactly that
  allocation. When that row is later polled, `open_after_close.py:239-244`
  finds the awaited close's status is `FAILED` and abandons with one ERROR
  ("an awaited close failed"), returning without ever calling `self._open_now`
  — `_handle_consumes`/`open_now` never runs. So for rows 13/14 inside a
  REVERSE, the outcome is entirely decided, synchronously, by the close
  itself, inside `signal.process` — there is no "open half" to defer to, and
  the eventual continuation abandonment (5c.4, `AWAITED_CLOSE_FAILED`) will
  find the signal already terminal. *Corrected in PR 5c unit G:* the original
  text called that write "a benign no-op WARNING" and later "a no-op, no
  WARNING", and the second was wrong for differing codes: the terminal guard
  warns on any DIFFERENT second outcome, and `AWAITED_CLOSE_FAILED` differs from
  `CLOSE_REJECTED_BY_VENUE`, so every such abandonment would have logged a
  WARNING and the WARNING would have stopped meaning "two writers disagreed".
  The abandonment therefore goes through the explicit non-warning path of
  § A ("The non-warning path"), silent by construction. One caveat this
  addendum cannot verify without running the code: whether `NOT_CLOSABLE`
  persists as `ExecutionStatus.FAILED` on the (nonexistent) attempt row —
  since `close_position.py:178-183` writes NO attempt row at all for
  `NOT_CLOSABLE`, `latest_close_for(prior_reservation_id)` finds nothing,
  which is `close is None`, not `close.status is FAILED`
  (`open_after_close.py:239, 251-253`). That is neither branch (2)'s
  abandon-on-FAILED nor branch (3)'s all-filled — it falls to branch (4),
  which only abandons past the hard age/settle-timeout bound. **So a REVERSE
  whose close is dust (`NOT_CLOSABLE`) leaves its seeded continuation
  waiting for a close that will never exist, until it times out and 5c.4's
  `CONTINUATION_TIMED_OUT` fires minutes later** — even though
  `signal.process` already knew, synchronously, that this signal was
  definitively `REJECTED CLOSE_DUST_NOT_CLOSABLE`. The abandonment's write
  (`CONTINUATION_TIMED_OUT`, a DIFFERENT code) is a silent no-op through
  `record_unless_terminal` (§ A), so the recorded status stays harmless and
  nothing warns, but it is a live queue row
  sitting idle for no reason for the whole timeout window. Worth a
  cross-reference note on 5c.4, not a blocker for 5b.
- **What is the status while the close is PLACED but not settled, and who
  decides the final status?** `PROCESSING`, written at `close_position.py`'s
  `mark_placed` commit (§ C, row 15). When `is_reverse_wiring` is `True`,
  the FINAL status is decided later, in the `signal.open_after_close`
  continuation's own job and commits, once every awaited close is `FILLED`
  and `open_now` runs `_handle_consumes` again (`open_after_close.py:256-266`,
  `process_signal.py:380-437`) — landing on rows 2–15 a second time, this
  time inside the continuation's transaction rather than the original
  `signal.process` run. That is 5c territory (5c.5: "the continuation's
  `open_now` reuses 5b's writes ... in the continuation job's own commits"),
  even though the reused code is unmodified 5b code. When
  `is_reverse_wiring` is `False` (spot short target), there is no
  continuation and no open half at all; the close's own eventual settlement
  (`execution.settle`, row 16) is what resolves `PROCESSING` away — and it
  is 5c.1's job, resolving through `reservation.signal_id`, exactly like any
  other close settle.

**The alternative, offered because of the evidence above, and declined by
the owner (decision 26):**

Keep `PROCESSING` as the close's interim status (unchanged from the proposed
rule), but classify the FINAL status by whether any order actually executed
and changed the position, not by whether the intended REVERSE completed in
full. Concretely: `REJECTED` only when nothing at all was placed (rows 13/14
— the close never executed, so nothing changed); `PROCESSED` whenever the
close settled `FILLED`, whether or not the open half ever ran or ran and was
itself refused, with `outcome_detail` naming exactly what happened (which
half ran, which half did not and why — e.g. "closed 0.5 SOL; the new short
cannot be held on spot" or "closed the prior long; the open was refused:
PAIR_NOT_ALLOWED"). This also gives row 18's currently code-less
`_note_unexecuted_tail` branch a defined outcome for the first time (see
"Map corrections" below), where the proposed rule as written leaves it
undefined.

Tradeoff: this reads correctly at the status level — `PROCESSED` never lies
about a position that moved — but it gives up the proposed rule's one
advantage, which is that `REJECTED` currently doubles as a visual flag on
the panel for "look at this signal, something needs attention." Under the
alternative, a partially-completed reverse (a real, deliberate, product-level
gap — the position ends flat rather than flipped) looks identical, at the
status column, to a fully successful one; only the detail text (which
requires opening the row) tells them apart. The proposed rule keeps that
visual flag at the cost of the misrepresentation risk above; the alternative
removes the misrepresentation at the cost of the flag. Both are internally
consistent with the status machine in § A — neither needs a third terminal
value.

### F. Exhausted jobs (PR 5c unit H, task 5c.6)

A signal whose `signal.process`, `signal.open_after_close` or `execution.settle`
job ends `FAILED` becomes `REJECTED` `JOB_FAILED`, with `jobs.last_error` as the
detail, exactly once and never over a terminal signal.

**The trigger: a hook at the point `queue.fail()` marks a job `FAILED`, in the
same transaction.** The alternatives, and why they lost:

- *A recurring sweep* of `FAILED` jobs. Level-triggered and crash-safe, but it
  leaves a window (up to its interval) in which a job is `FAILED` and its signal
  still looks alive, which is exactly the silence decision 25 exists to remove;
  it also adds a second recurring chain that must itself stay alive, and the
  `FAILED` rows it would rescan are kept forever (`jobs.purge` never deletes one).
- *A hook in `WorkerRunner` after `queue.fail()` returns.* `fail()` commits
  internally, so the outcome would be a separate later transaction: a crash
  between the two leaves the job `FAILED` and the signal undecided, with nothing
  scheduled to notice.

The hook keeps `PostgresJobQueue` job-kind-agnostic:

- `shared/application/ports.py` declares `ExhaustedJobObserverPort.on_exhausted(job,
  last_error)`. The queue passes the job through opaquely (kind, payload, attempts)
  and never interprets it.
- `PostgresJobQueue.fail()` is unchanged in behaviour; its body split into
  `_record_failure` (stage, return the job when this failure spent the last
  attempt) plus the commit. `ExhaustionObservingJobQueue` (a subclass) runs the
  observer between the two.
- It is a SUBCLASS with a REQUIRED observer, not an optional parameter on
  `PostgresJobQueue`: that class is built at dozens of enqueue-only sites where
  nothing can exhaust, and an optional observer defaulting to "nobody" would be a
  silent no-op on exactly the queue where it matters. Only
  `main.build_worker_runner`'s `queue_factory` builds the worker's queue (the one
  queue whose `fail()` is ever called), so that is the one wiring site; a test
  drives the production runner to pin it.
- `signals/infrastructure/failed_job_signal_reader.py` is the separate reader:
  `signal.process` and `signal.open_after_close` carry `signal_id`;
  `execution.settle` goes through the attempt, `execution_attempts.signal_id` for a
  close (never the opening reservation's signal) and `reservation.signal_id` for an
  open. A NULL link, or a kind that decides no signal, resolves to nothing. A
  payload that cannot be resolved RAISES, and the queue logs it.
- `signals/infrastructure/exhausted_job_recorder.py` writes the outcome through
  `record_unless_terminal` (§ A).

**"Exactly once", by construction, under redelivery and concurrency.**

1. A job reaches `FAILED` once: `claim()` takes `FOR UPDATE SKIP LOCKED` and only
   `PENDING` rows are claimable, so no second worker holds the row, and a `FAILED`
   row is never claimed again.
2. The outcome and the `FAILED` status are ONE transaction. A crash or a failed
   commit before it loses both; the job is then reclaimed and its next failure
   stages the same write again. It is never written twice and never half-written
   (`test_a_failed_commit_loses_the_failed_status_and_the_rejection_together`).
3. Two exhausted jobs of ONE signal (say `signal.process` and the `execution.settle`
   of its open) write once: the second finds the signal terminal and is a silent
   no-op, so the first error is the recorded one.
4. Concurrent writers serialise on the signals row (`FOR UPDATE`): a held lock makes
   the exhaustion write wait (`not task.done()`), and once the holder commits it
   sees the terminal row and stays silent.

**A SAVEPOINT around the observer.** `run_once` calls `fail()` from an `except`
block, so an observer exception escaping it would leave the job `CLAIMED`, out of
the retry chain and never reported, and would escape `run_forever`. The savepoint
rolls back only what the observer staged; the job is still marked `FAILED`; the
failure is logged at ERROR (`str(exc)` only, redacted, no traceback). A signal
left undecided that way is loud, not silent.

**What `jobs.last_error` can carry, now that it is panel-visible.** Read from how
errors are formatted today:

- Adapter errors (`pionex`/`bybit`/`binance` transports) are `"{METHOD} {path}
  failed: {exc}"`: the PATH only, never the query string, which is where the
  signature, the api key and the timestamp travel. The venue's own `retMsg`/`msg`
  text follows, and httpx transport errors (`ConnectError`, `ReadTimeout`) carry no
  headers or body.
- Database errors carry SQLAlchemy's `[SQL: ...]` and `[parameters: ...]`: order
  sizes, ids, client order ids. None of these three job kinds touches a credential
  table. Connection errors name host and port; an authentication failure names the
  user, never the password.
- Domain errors are prose with ids. Nothing stores a traceback: the runner passes
  `str(exc)`, and the DSN incident recorded in `alert_redaction.py` was a traceback
  with locals.

So nothing here is EXPECTED to carry a credential or a DSN, but the panel is a new
consumer and the shapes are pattern-dependent, so the detail is passed through the
same `redact()` the alert channel uses (it removes: DSN passwords, URL query strings,
`name=value` secrets, bearer tokens; it adds nothing) and truncated to 500
characters with a trailing ellipsis. The recorded detail adds NOTHING to the error:
no job id, no payload, no attempt count. The raw `jobs.last_error` column is
unchanged and stays outside the panel.

**Log lines.** A job reaching `FAILED` does NOT log an ERROR at that moment.
`WorkerRunner` logs one WARNING per failed attempt, including the last, with the
same string `fail()` stores; the ERROR comes from the watchdog, on its cadence, as
one combined line naming the kinds and counts that ended `FAILED` since its previous
run (`watchdog.py`, condition 3). Nothing is added here: the recorded detail is that
same WARNING string, and a duplicate ERROR per exhaustion would defeat the watchdog's
one-ERROR-per-condition throttling. The one new log is ERROR when the observer
itself fails (above), which is a branch that would otherwise fail without a line.

**Limits, stated.** Jobs that exhausted before this shipped are not back-filled
(nothing reconstructs history, same as § A). If the ONLY job of a signal to die is
an `execution.settle` whose order in fact filled (the exchange published fills but
settle kept failing), the signal is recorded `JOB_FAILED` while the position is
real: that is the honest outcome for the job, the ledger is untouched, and a later
successful settle of that attempt would meet the terminal guard and WARN, which is a
genuine conflict worth seeing.

### Map corrections

- **Row 18 has no reason code of its own, and neither proposed REVERSE rule
  fully defines one for it.** The outcome map (`tasks.md`, row 18) states
  this explicitly ("none of its own"); this addendum's own REVERSE analysis
  above confirms the gap is real rather than an oversight — whichever
  REVERSE rule the owner picks, `_note_unexecuted_tail`'s branch (a spot
  REVERSE whose new side cannot be held) needs a first reason code. Under
  decision 26 it is `REJECTED` `REVERSE_NEW_SIDE_UNHOLDABLE` (§ E).
- **A REVERSE whose close is dust (`NOT_CLOSABLE`) leaves a dead continuation
  row behind it until it times out**, even though `signal.process` already
  knows the definitive outcome synchronously (see the second flagged
  question above). Not a defect in the outcome map itself — the map's rows
  13 and 15 are both accurate — but a behaviour 5c.4's implementer should
  know about before treating every `CONTINUATION_TIMED_OUT` as a genuine
  "still waiting on the venue" case.
- No other discrepancy was found: the routing, commit counts, and job
  ownership for rows 1–17 and 19–20 match the map exactly, including the two
  zero-commit branches (row 8's pre-lock skip, row 13's `NOT_CLOSABLE`) the
  map itself does not call out as needing a new commit — that is new
  information from this addendum, not a correction of a wrong claim.

## Addendum: the `DRY_RUN` mode guard (decision 28) - as built in PR 6d

The worker refuses to start when `DRY_RUN` does not match the origin of what the ledger holds.

- **Layering.** `execution/domain/mode_origin.py` is the pure decision (`fold_open_allocations`, `find_mismatches`, `describe_refusal`). `ModeOriginReaderPort` is declared in `execution/application/ports.py`. `execution/infrastructure/mode_origin_reader.py` holds the SQL. `execution/application/assert_mode_matches_ledger.py` logs and refuses. `main.assert_dry_run_matches_ledger` composes them.
- **Where it runs.** Called from `worker._run_worker` right after the "worker starting" line, not from inside `build_worker_runner` as tasks.md first said: that function is synchronous, and it is also built by tests that have no database. The worker calls it inside `operator_alerts`, so the bridge exists when the ERROR is logged.
- **"Open".** Net base quantity not exactly zero, with `derive_trade`'s base-fee rule (`fee_currency == base_currency_of(symbol, settlement)`), grouped by allocation and never by symbol. SQL only aggregates by side, fee currency and fill origin; the fold is Python because the base currency of a symbol is not a column. Every pool in the ledger is read, enabled or not. A symbol whose base currency cannot be split fails closed: the allocation is reported as open.
- **Origin of a fill.** A PREFIX test on `exchange_fill_id` with `REHEARSAL_FILL_ID_PREFIX`. An allocation holding both kinds, while open, refuses in either mode.
- **In-flight orders (task 6d.6).** A `SUBMITTED` attempt with an `exchange_order_id` is judged by `REHEARSAL_ORDER_ID_PREFIX` (`fake-order-`), which the fake mints and no venue does. The origin of a `SUBMITTED` attempt with a NULL `exchange_order_id` is not recorded anywhere; that gap is left open and reported, not closed with a new column.
- **Exit.** One ERROR (its own record, because an exception is not a log record and only a log record reaches the alert bridge), then `InvariantViolation` out of `worker.run`. That is the mechanism `assert_dry_run_safe` and the pool lock-key check already use, and it ends the process with exit status 1. **Superseded by decision 29 (PR 6e, next addendum):** the exception is now `StartupRefused` and the exit status is 78. Exit status 1 was the defect: under `Restart=always` the worker looped on it.
- **Not covered, deliberately.** An allocation that is FLAT by the ledger's rule but holds both kinds of fill (a live open closed by a fake close, the exact incident this guard prevents) is not open and is not read. The guard prevents that state; it does not audit past ones. The fake exchange keeps its placed orders in memory, so any restart already turns a rehearsal order still in flight into `NEVER_PLACED`; the guard does not change that.

## Addendum: a startup refusal exits 78 (decision 29) - as built in PR 6e

- **The type.** `shared/domain/startup_refusal.py::StartupRefused`, standard library only. It is not an `InvariantViolation`: that class is raised by runtime code too (`Money`, the signers, `EnvelopeCipher`, `CredentialNotFound`), and a runtime failure must keep exiting non-zero and being restarted. It carries `logged`, whether the refusal already wrote its own ERROR.
- **Wrap, do not raise.** `worker._startup_refusal()` is a context manager around each refusal-capable call in `_run_worker`. It converts `InvariantViolation` and `PoolLockKeyCollisionError` into `StartupRefused` and logs the ERROR. Raising `StartupRefused` from inside the checks was rejected because most of them are shared with code that runs after startup: `EnvelopeCipher.from_base64` runs per job, `assert_pool_lock_keys_distinct` re-runs every `balance.sync` cycle, and `assert_dry_run_safe` sits in `build_worker_runner`. A running worker would then exit 78 too. The wrapper cannot catch a runtime failure: it is lexical, and it is over before `run_forever`. It is deliberately not around the whole startup phase, or around seeding: a database outage there raises other exceptions, and one raising `InvariantViolation` would be a bug, not a configuration to wait on. The one exception is `assert_mode_matches_ledger`, which only the worker's startup calls and which raises `StartupRefused(logged=True)` itself.
- **Exit.** `worker.main` catches `StartupRefused` and only that, and calls `sys.exit(78)` (`EX_CONFIG`). Nothing is printed by `main`: the ERROR was logged inside `operator_alerts`, which drains the bridge on the way out. Every other exception escapes unhandled and exits 1, as before.
- **Refusals, and how each now ends.**

  | Refusal | Raised as | ERROR before this PR | Now |
  | --- | --- | --- | --- |
  | pool lock-key collision | `PoolLockKeyCollisionError` (not even an `InvariantViolation`) | none | wrapper logs it, exit 78 |
  | no enabled capital pools | `InvariantViolation` | none | `StartupRefused`, wrapper logs it, exit 78 |
  | mode guard (decision 28) | `InvariantViolation` | one, its own | `StartupRefused(logged=True)`, no second ERROR, exit 78 |
  | `MASTER_ENCRYPTION_KEY` unset, not base64 or the wrong length | `InvariantViolation` | none | wrapper logs it, exit 78 |
  | vault self-test | `InvariantViolation` | none | wrapper logs it, exit 78 |
  | `assert_dry_run_safe`, inside `build_worker_runner`; also the cipher built there | `InvariantViolation` | none | wrapper logs it, exit 78 |

  Five of the six raised without logging an ERROR. Each would have stopped the worker in silence once 78 prevented the restart, so the wrapper writes the ERROR: `refusing to start: <the exception message>`, no `exc_info`, no traceback.
- **Not a refusal, on purpose.** `get_settings()` runs before alerting can be installed: a settings validation error escapes as today and cannot alert. Seeding and everything after it keep their current exit. A database outage during startup raises SQLAlchemy or driver errors, which are not converted, so the restart that recovers from it still happens.
- **The unit drop-in the owner adds.**

  ```
  /etc/systemd/system/strategy-worker.service.d/startup-refusal.conf
  [Service]
  RestartPreventExitStatus=78
  ```

  then `systemctl daemon-reload`. Order does not matter for safety. The drop-in before the deploy is inert, because the old code never exits 78. The deploy before the drop-in leaves today's behaviour: a refusal exits 78, which systemd treats as any other failure and restarts. The protection exists only once both are in place. After a refusal the unit stays `failed` (`status=78`) until the owner starts it; a manual `systemctl restart strategy-worker` is unaffected by the setting.
- **The API has the same loop, unfixed.** The lifespan in `main.py` raises `InvariantViolation` for `WEBHOOK_SECRET` and `ADMIN_API_TOKEN`. It logs no ERROR of its own, and uvicorn's lifespan ERROR goes to the `uvicorn` logger, which has `propagate=False`, so it never reaches the root logger the alert bridge is installed on. Those two refusals therefore do not reach any alert channel. Uvicorn ends the process with exit status 3 on a failed lifespan. If `strategy-api.service` also runs `Restart=always` it loops the same way, silently. Decision 29 does not cover it and this PR does not touch it.

## Addendum: key policy after probe P6 (decisions 24 and 30) - 2026-09-29

Task 8a.0b. Probes P1-P6 are recorded in tasks.md, and decisions 24 and 30 are binding. This addendum settles what they left open: how each venue satisfies the key rules, what 0027 records, and what the API, the scripts and the Settings screen do with it. It supersedes the trade-capability and migration-0027 bullets of § 4, the `GET`/`PUT /credentials` rows of § 14 and the key card and form of § 15. Those sections carry a pointer. Nothing here changes decision 18 (one key, read-only accepted with a warning), 20, 21 or 22.

The principle: **the record says how each fact was established, and never claims more than was.** A fact the venue could not prove is not "false", not "true" by default, and not silently dropped. It is stored with the name of who vouched for it.

### A. The per-venue verdict table

| Rule | Bybit | Binance |
| --- | --- | --- |
| **8a, live read** | `GET /v5/account/wallet-balance?accountType=UNIFIED` (P4). Auth failure (`retCode` 10003/10004/33004) is `KEY_REJECTED`. | `GET /fapi/v3/account`, signed (P4). Auth failure (-2014/-2015/-1022) is `KEY_REJECTED`. -2015 also covers a wrong IP or a missing permission, so its detail says so. |
| **8b, no withdraw** | **VERIFIED**, server-side and fail-closed. `GET /v5/user/query-api`: `permissions.Wallet` must be a list and a subset of `{AccountTransfer, SubMemberTransfer}` (P1). Any other token, or a missing or non-list `Wallet`, is refused. | **OWNER_CONFIRMED** (decision 24). Nothing reachable reveals it: SAPI `apiRestrictions` answers 403 from the VPS (P3) and `canWithdraw` is account-level (P6). The owner confirms "withdrawals disabled" and the confirmation is stored with its timestamp. |
| **Trade capability** | **VERIFIED**: `readOnly == 0` on the same call (P2). The permission lists are never used: a read-only key still lists `ContractTrade` and `Derivatives`. | **OWNER_CONFIRMED** (decision 30). The owner confirms "Enable Futures" and the confirmation is stored with its timestamp. A key without it still reads every fapi endpoint (P6), so 8a proves nothing about trading. |
| **Shown as** | Nothing extra. | "trade not verified" and "withdraw not verified", each with the date the owner confirmed. |

Pionex has no inspector and is outside `KNOWN_FUTURES_POOLS`; `SaveCredential` does not serve it (see Q3).

**`canTrade` and `canWithdraw` are never read, for any purpose.** P6 found them on `GET /fapi/v2/account` at the ACCOUNT level: both were `True` on a key that could neither trade futures nor withdraw. Reading them would record a false "verified" and turn a wrong belief into a stored fact. `/fapi/v3/account` no longer returns them, and the Binance inspector calls only that endpoint. A test feeds it the P6 v2 payload and asserts the snapshot stays empty.

### B. The data model: migration 0027, revised

**`permissions JSONB` is dropped from the plan.** Decision 24 says a raw payload is never displayed, because it carries whitelisted IPs, the userID and the KYC region. Storing it would keep that data at rest with no reader: the card needs the derived facts below, and they satisfy the spec's "permission snapshot". A minimal derived snapshot is the smaller and safer choice, and it removes a column the API would otherwise have to remember never to serialise. P5 (binding, expiry) is not stored: it gates nothing and Binance cannot supply it. A later additive column can carry it if PR 13 wants it.

Columns added to `exchange_credentials`:

| Column | Type | Meaning |
| --- | --- | --- |
| `trade_capable` | `boolean NOT NULL` | What the system acts on. Added `DEFAULT true`, backfilled, then the default is dropped (unchanged from § 4). |
| `trade_capability_source` | `text NOT NULL` | `VERIFIED` (the venue said so), `OWNER_CONFIRMED` (the owner said so), `UNRECORDED` (a row sealed before 0027). |
| `trade_confirmed_at` | `timestamptz NULL` | When the owner confirmed "Enable Futures". |
| `withdraw_check` | `text NOT NULL` | How "this key cannot withdraw" was established. Same three values. |
| `withdraw_confirmed_at` | `timestamptz NULL` | When the owner confirmed "withdrawals disabled". |
| `validated_at` | `timestamptz NULL` | When the 8a live read passed. |
| `internal_transfer` | `boolean NULL` | Bybit `AccountTransfer` present. `NULL` means unknown. Shown, never a refusal. |

There is no `withdraw_capable` column: a key that can withdraw is refused and never stored, so `withdraw_check` describes how "cannot" was established.

CHECK constraints (all named `ck_exchange_credentials_*`):

1. Both source columns are in `{VERIFIED, OWNER_CONFIRMED, UNRECORDED}`.
2. `(trade_capability_source = 'OWNER_CONFIRMED') = (trade_confirmed_at IS NOT NULL)`, and the same pairing for `withdraw_check` and `withdraw_confirmed_at`. A confirmation without its timestamp, or a timestamp without a confirmation, cannot exist.
3. `trade_capability_source <> 'OWNER_CONFIRMED' OR trade_capable`. The owner confirms a capability, never an incapability.
4. `(trade_capability_source = 'UNRECORDED') = (withdraw_check = 'UNRECORDED')`, and `(validated_at IS NULL) = (withdraw_check = 'UNRECORDED')`. A row is either fully recorded or fully legacy.
5. `exchange <> 'binance' OR (trade_capability_source <> 'VERIFIED' AND withdraw_check <> 'VERIFIED')`. A Binance row cannot claim a verification the venue does not allow.
6. `exchange <> 'bybit' OR (trade_capability_source <> 'OWNER_CONFIRMED' AND withdraw_check <> 'OWNER_CONFIRMED')`. Bybit is verified server-side; an owner confirmation on a Bybit row would mean the code took the wrong branch.

If SAPI ever becomes reachable, constraint 5 is relaxed by a new migration. The constraint guards a policy, and a policy change is a migration.

**Backfill.** Every existing row (production holds one active key each for binance, bybit and pionex, plus any history) becomes `trade_capable = true`, `trade_capability_source = 'UNRECORDED'`, `withdraw_check = 'UNRECORDED'`, with every timestamp and `internal_transfer` `NULL`.

Why this is honest:
- `true` is the value the system already acts on. Every one of these rows was sealed by a `store_*_credentials.py` that refused a key it could not see trading (the spec's sentence about pre-0027 rows), and the worker signs with them today. Setting `false` would assert something nobody knows.
- `UNRECORDED` states what is true: no record exists of how the key was checked. A migration cannot decrypt a key or call a venue, so it must not write `VERIFIED`. It must not write `OWNER_CONFIRMED` either: the owner has not confirmed anything, and a fabricated timestamp cannot be told apart from a real one later.
- The Binance key is the sharp case. It is the key the worker trades with, and it has NO confirmation on record. The card shows it as "not validated" with both "not verified" marks until the owner re-saves it with the two confirmations. What to do about it is an open question (Q1); the migration ships the neutral answer.

**Downgrade.** Refuses while any row is not the backfill shape: `trade_capable = false`, or either source not `UNRECORDED`. It names the count of each. Dropping the columns would erase who vouched for a key and could make a read-only key look trade-capable, the same reasoning as 0025 and 0026. The owner deletes rows by hand if that is really wanted (the 0013 precedent). After the first save through Settings, the refusal is permanent, by design.

Rehearsal follows the standing rule: a throwaway database restored from a fresh backup, the upgrade, each constraint refusal, and the downgrade refusal once a recorded row exists.

### C. The API

**`PUT /api/credentials/{exchange}`** body:
`{api_key, api_secret: SecretStr, label?, withdrawals_disabled_confirmed: bool = false, futures_enabled_confirmed: bool = false}`.

- **Binance: both are REQUIRED true.** A missing or false value answers 422 `CONFIRMATION_REQUIRED` with `{outcome, detail, missing: ["withdrawals_disabled_confirmed", ...]}` naming exactly what is absent. It is a use-case refusal, not a pydantic error, so it has the same shape as every other outcome. It is checked BEFORE the venue is called: nothing is sent to Binance for a key that cannot be stored.
- **Bybit: a `true` confirmation is refused**, 422 `CONFIRMATION_NOT_APPLICABLE`, naming the field. Absent or false is fine. Refused, not ignored: Bybit is verified server-side, and a confirmation the server silently drops leaves the owner believing one was recorded. A silent drop is the failure this project keeps finding. Only a stale or wrong client sends it, and it should hear so.
- Timestamps are the server clock (`ClockPort`) at save, both the same instant. A client never supplies one.
- A confirmation belongs to the key it was given for. A rotation stores the new row with its own confirmations and inherits nothing.
- New 422 outcome `PERMISSIONS_UNAVAILABLE`: the Bybit `query-api` answer lacked `readOnly` or `Wallet`. Fail-closed, nothing stored, one WARNING.
- `WITHDRAW_PERMISSION` names the offending tokens, not the payload. It no longer carries `permissions`.
- `warnings` stays `["READ_ONLY_KEY"]` when `trade_capable=false`. Only Bybit can produce it, verified. "Not verified" is not a warning; it is state, carried by the view.

**`GET /api/credentials`** entry, replacing `permissions`:

`{exchange, status, last4|null, label, stored_at, validated_at|null, trade_capable|null, trade_capability_source|null, trade_confirmed_at|null, withdraw_check|null, withdraw_confirmed_at|null, internal_transfer|null}`

`status: EMPTY` nulls all of them. The view carries no raw payload and nothing of the key or secret beyond the last four characters. Nothing is re-queried live (the API never decrypts).

### D. `evaluate_key`, pure domain

```python
def check_confirmations(exchange: str, c: OwnerConfirmations) -> KeyRefused | None  # before any venue call
def evaluate_key(exchange: str, snapshot: PermissionSnapshot,
                 confirmations: OwnerConfirmations) -> KeyVerdict
```

- **`PermissionSnapshot`** holds only what the venue said: `wallet_permissions: frozenset[str] | None` and `read_only: bool | None`. Both are `None` for Binance, whose inspector cannot observe them. **Verified inputs** are the snapshot; **confirmed inputs** are `OwnerConfirmations(withdrawals_disabled, futures_enabled)`. The two never mix: a Binance snapshot is empty, and a Bybit confirmation is refused.
- 8a is not in `evaluate_key`. The inspector raises `KeyRejected` or `VenueUnreachable`; the function only sees a key the venue already accepted.
- A per-exchange policy table (`KEY_POLICIES`) maps `bybit` to server-verified and `binance` to owner-confirmed. An unserved exchange raises: there is no fallback.
- **`KeyVerdict` outcomes:**
  - `KeyAccepted(trade_capable, trade_capability_source, withdraw_check, internal_transfer, warnings)`. No timestamps: `SaveCredential` stamps them from the clock, so the function stays pure. A read-only Bybit key is `KeyAccepted(trade_capable=False, ..., warnings=("READ_ONLY_KEY",))` (decision 18).
  - `KeyRefused(outcome, detail, missing=())`, with `outcome` one of `WITHDRAW_PERMISSION`, `PERMISSIONS_UNAVAILABLE`, `CONFIRMATION_REQUIRED`, `CONFIRMATION_NOT_APPLICABLE`.
- The domain value `KeyFacts` (in `exchange_credential.py`, no secret) is what `vault.store(credential, facts)` writes and `CredentialHint.facts` returns. It has no defaults, and its `__post_init__` enforces constraints 2-4, so the domain and the database refuse the same states. `ExchangeCredential` stays secret-only and is unchanged. This departs from § 4's "fields on `ExchangeCredential`": the object that carries the secret should not also carry the record about it.

### E. Trade-capability refusal (6c)

`VaultTradeCapabilityAdapter` still reads `exchange, trade_capable WHERE is_active` and never decrypts. It does not look at the source. A Binance key whose capability was only confirmed answers `TRADE_CAPABLE`: the confirmation is the source, and the owner has vouched for it. An `UNRECORDED` row answers from its column (`true` today). The backstop is the venue: a wrong confirmation makes the first live order end `REJECTED` `ORDER_REJECTED_BY_VENUE`, with an ERROR that reaches Telegram (PR 5b2, decision 30). `TradeCapability` keeps its three values. A fourth "unconfirmed" state was rejected: it would refuse live opens on a key the owner has said can trade.

### F. The store scripts (6b.7)

- `store_binance_credentials.py` drops its `apiRestrictions` call (403 from the VPS). It takes two flags, `--confirm-withdrawals-disabled` and `--confirm-futures-enabled`. Without both it prints which is missing to stderr, exits 2, and stores nothing. This is checked before the secret prompt, so no secret is typed for a run that cannot succeed. There is no environment variable, no `--yes` and no default: the flags are the owner's statement, made on the command line.
- It then calls `SaveCredential` with the fapi inspector, like the endpoint, so both paths record the same facts.
- `store_bybit_credentials.py` folds onto `SaveCredential` and takes no confirmation flags. A read-only key is stored with a warning instead of refused (decision 18).
- `store_pionex_credentials.py` keeps sealing directly, passing `KeyFacts.unrecorded(trade_capable=True)`. It is the only caller of that constructor besides the interim edits in PR 8a-1.
- The scripts run on the VPS, where the keys are IP-bound. They print last-4 only.

### G. Frontend

- **`KeyEntryForm` (10f), Binance only:** two checkboxes, unchecked, with submit disabled until both are ticked (a convenience; the server enforces). They are sent as booleans and reset in `finally` with the other fields. Bybit shows none and sends none.
- **`ExchangeKeyCard` (10c):** the line keeps its shape. For `VERIFIED` it reads as before ("no withdrawal", "checked {date}"). For `OWNER_CONFIRMED` it never states "no withdrawal" as a fact: it shows two neutral `ink-2` marks, "trade not verified" and "withdraw not verified", each with "you confirmed on {date}". They are not amber, because amber means an action is needed. `UNRECORDED` shows "not validated" plus both marks.
- **i18n keys** (EN/ES, in `en.json` and `es.json`):
  - `settings.key.confirm.withdrawals`: "I confirmed in Binance that this key has withdrawals disabled"
  - `settings.key.confirm.futures`: "I confirmed in Binance that this key has Enable Futures"
  - `settings.key.confirm.help`: "Binance does not let this panel check either setting. If a confirmation is wrong, Binance rejects the first live order and you get a Telegram alert."
  - `settings.key.error.confirmationRequired`, `settings.key.error.confirmationNotApplicable`, `settings.key.error.permissionsUnavailable`
  - `settings.card.tradeNotVerified`: "trade not verified"
  - `settings.card.withdrawNotVerified`: "withdraw not verified"
  - `settings.card.confirmedOn`: "you confirmed on {{date}}"

### H. Failure modes (what fails here without a log line?)

| Failure | Guard |
| --- | --- |
| A wrong confirmation (the key lacks Enable Futures, or can withdraw) | Trade: the venue rejects the first live order, `ORDER_REJECTED_BY_VENUE`, ERROR to Telegram. Withdraw: mitigated by Binance's IP-restriction requirement and the VPS binding (decision 24); nothing in this system withdraws. |
| The code claims a verification it did not make | Constraints 5 and 6, the `KeyFacts` invariants, and the P6-payload inspector test. |
| An old row looks verified | `UNRECORDED` is a distinct value; the card shows it as such. |
| A raw payload leaks | It is never stored and never in a view; the redacted 422 handler strips `input`/`ctx`. |
| A Bybit field disappears from the venue's answer | `PERMISSIONS_UNAVAILABLE`: refused, nothing stored, one WARNING. |

### I. The PR split for 8a

The forecast grows from 1,900-2,600 to about 2,150-3,100 lines (the provenance columns, the confirmations and the extra tests), so 8a splits into four sequential PRs to `main`. Order is by blast radius, and each PR merges and deploys before the next branch is cut.

| PR | Contents | Forecast | Deploy |
| --- | --- | --- | --- |
| **8a-1** | Unit 6a: `key_policy.py`, `KeyFacts`, inspectors, **migration 0027**, vault `store(credential, facts)` and `hints`. The three store scripts change by one line each to pass `KeyFacts.unrecorded(trade_capable=True)`, so they keep working once the default is dropped. The spec realignment (see below) is its first commit. | 950-1,350 | `alembic upgrade head`, restart both. Rehearsed first. |
| **8a-2** | `SaveCredential` and the script fold: 6b.1, 6b.4, 6b.7. No HTTP. | 450-650 | Pull, restart both. |
| **8a-3** | The surface: 6b.2, 6b.3, 6b.5, 6b.6 (router, redacted 422, view). | 400-600 | Pull, restart the API. |
| **8a-4** | Unit 6c: `TradeCapabilityPort`, adapters, the up-front opening refusal. | 350-500 | Pull, restart both. |

Why this order:
- 0027 ships first, as required. 8a-1 must include the vault change and the one-line script edits, or the mandatory column breaks the scripts the moment the default is dropped.
- `SaveCredential` follows before any endpoint, so the scripts are its first user and its behaviour is proven on real keys before HTTP exposes it.
- The signal-path change (6c) goes last: it is the only PR that alters what a live signal does, and by then the recorded facts it reads exist.
- 8a-2 and 8a-3 can merge into one PR of about 850-1,250 lines if the owner prefers fewer deploys. 8a-4 needs only 8a-1's column, so it may move ahead of 8a-2 without changing anything else.

**Spec realignment (first commit of 8a-1).** `specs/exchange-credentials/spec.md` and `specs/operator-panel/spec.md` say "permission snapshot" and give `enableWithdrawals` and `enableFutures` scenarios for Binance. They are reworded to the derived facts, the two confirmations and the `UNRECORDED` state. `specs/admin-api/spec.md` needs only the body and view fields. The specs are outside this docs task's edit roots, so they are not touched here.

### J. Open questions for the owner

**Resolved 2026-09-29.** The owner confirmed the addendum as written:
- Q1: A. The existing Binance key stays `trade_capable = true` and `UNRECORDED` until it is re-saved with both confirmations.
- Q2: no confirm-only path.
- Q3: Pionex keeps sealing directly with `UNRECORDED` facts.
- The four-PR split of § I stands.

**Q1. What does the existing Binance key become?** It is the key the worker trades with, and no confirmation is on record. The migration backfills `trade_capable = true` with both sources `UNRECORDED`. The choices:
- **A (planned, recommended).** Keep that. The card shows "not validated" and both "not verified" marks until the owner re-saves the key with the two confirmations. Live behaviour does not change, and the record never claims a confirmation that was not given. The cost: a re-save means pasting the key and secret again.
- **B.** Backfill it as `OWNER_CONFIRMED` in the migration, on the owner's instruction now. The card would look clean at once, but the timestamp would be the migration's, not the moment the owner looked at Binance. Not recommended.
- **C.** Backfill it `trade_capable = false`, so live opens are refused until the key is re-saved. It forces the confirmation before `DRY_RUN=false`, at the cost of calling "cannot trade" something nobody knows, and of a surprise refusal on the flip.

**Q2. Should the owner be able to confirm an existing key without pasting it again?** It needs a confirm-only endpoint or script that updates the active row's confirmation columns. Recommend **no**: it adds a write path that changes a security fact on a stored key, and Q1-A reaches the same result with the paste Settings already asks for. Tradeoff: the owner pastes the key once more.

**Q3. Pionex.** It has no inspector and no futures pool. Recommend that `store_pionex_credentials.py` keeps sealing directly with `UNRECORDED` facts, instead of folding onto `SaveCredential`, which would need an inspector nothing else uses. This deviates from task 6b.7's "fold all three". Tradeoff: Pionex rows can never show a recorded fact, which is true today.

### K. Implementation notes, PR 8a-1 (2026-09-29): where the code differs from the text above

Written as the code landed, so the addendum and the repository do not disagree silently.

- **`KeyRejected` and `VenueUnreachable` did not exist.** § A and § D name them as if they did. They are defined in `accounts/domain/errors.py` (both `DomainError`), and their messages carry the venue's own code and never a payload or a secret.
- **The inspector contract is `inspect(credential) -> PermissionSnapshot`,** declared as `KeyInspectorPort` in `accounts/application/ports.py`. Task 6b lists that port for 8a-2; it is declared in 8a-1 because the registry needs its type. The candidate credential is passed in because it is not stored yet.
- **The `PERMISSIONS_UNAVAILABLE` WARNING is logged by the Bybit inspector,** not by `evaluate_key`. § H says "one WARNING". The inspector is the only place that knows which field was unusable, and `evaluate_key` stays pure. It names the exchange and the unusable field (`permissions.Wallet`, `readOnly`), never a value.
- **`readOnly` is trusted only as the integers 0 and 1** (the shape P2 recorded). A bool, a string or any other value is treated as missing, so it fails closed.
- **A Binance `PermissionSnapshot` that is not empty is an `InvariantViolation`,** not a quiet pass. § D says a Binance snapshot is empty; this enforces it, so a verified input that reaches the confirmed branch is a loud bug and not a stored fact the venue never supplied.
- **`FactSource` is a `StrEnum`** in `exchange_credential.py` (`VERIFIED`, `OWNER_CONFIRMED`, `UNRECORDED`), spelled exactly as the database CHECK spells them. `KeyAccepted` and `KeyFacts` share it.
- **The Bybit auth codes are the three § A lists (10003, 10004, 33004) plus 10010.** An unmatched source IP is the likeliest mistake when saving a new key, and as "unreachable" it would invite a retry that can never succeed, so it is `KeyRejected` with a static message naming the IP binding (added after verification). Any other `retCode`, a non-200 status, a transport failure or a body of the wrong shape is `VenueUnreachable` with a code or status in the message. Nothing is stored either way.
- **`SqlAlchemyCredentialVault.store` refuses constraints 5 and 6 in code,** raising `InvariantViolation` for a Binance `VERIFIED` source or a Bybit `OWNER_CONFIRMED` source before the previous active key is deactivated, so a wrong-branch write fails before anything changes instead of at flush.

Migration 0027 and `KeyFacts` (same PR, third commit):

- **The migration file keeps the name the task gives, `0027_credential_snapshot.py`,** although the addendum withdrew the snapshot. The revision id is `0027`. Renaming it later would rename an applied revision's file for no gain.
- **The six constraints are named** `ck_exchange_credentials_sources_known`, `..._confirmation_has_timestamp` (both pairings, trade and withdraw), `..._confirmed_trade_is_capable`, `..._recorded_or_legacy` (both clauses of constraint 4), `..._binance_not_verified` and `..._bybit_not_owner_confirmed`. `models.py` spells the same SQL, because the integration tests build their schema from the ORM.
- **The downgrade counts four things, not three.** § B lists `trade_capable = false` and either source not `UNRECORDED`. It also counts rows with a non-null `internal_transfer`: no CHECK ties that column to a source, so a row can be legacy in every other respect and still hold a fact that dropping the column would discard.
- **`CredentialHint.facts` is required, with no default,** and `ExchangeCredential.hint(facts)` now takes the facts. `ExchangeCredential` is still secret-only; it merely hands the facts through to the hint. Every test that built a `CredentialHint` or called `vault.store` was updated.
- **`KeyFacts` also refuses a source that is not a `FactSource`,** so a stray string cannot reach the database as a fourth value. Constraints 5 and 6 need the exchange, which lives on the row and not on `KeyFacts`, so the table enforces those alone; the ORM mirror is tested in `test_credential_vault_integration.py`.
- **Task 6a.9 names `tests/accounts/infrastructure/test_credential_vault.py`,** which does not exist. The vault's tests live in `test_credential_vault_integration.py`, so the new tests are there.
- **A structural test pins the three store scripts** (`tests/scripts/test_store_scripts_pass_facts.py`): each passes exactly `KeyFacts.unrecorded(trade_capable=True)`. The scripts need a database, a master key and a venue, so they cannot be run in a test (rule 1). 6b.7 replaces this test when it folds the Bybit and Binance scripts.
- **What the backfill does to production's rows.** Every row, active or superseded, becomes `trade_capable = true`, both sources `UNRECORDED`, every timestamp and `internal_transfer` NULL. The live behaviour is unchanged. The Binance key, which the worker trades with, shows as "not validated" with both "not verified" marks until the owner re-saves it with the two confirmations (Q1-A).
- **The addendum was not wrong about the data model.** The only gaps were the two above (`KeyRejected` and `VenueUnreachable` did not exist; the downgrade omitted `internal_transfer`).

### K2. Implementation notes, PR 8a-2 (2026-09-29): SaveCredential

- **The result type is a union, not one bag of optionals.** `SaveCredential.execute(credential, confirmations)` returns `Saved(last4, facts, warnings)` (its `outcome` is always `SAVED`) or `SaveRefused(outcome, detail, missing=())`. `SaveOutcome` is a `StrEnum` of the eight outcomes of section C, spelled as the API will spell them. `detail` names tokens or fields, never a payload; `missing` is filled only for `CONFIRMATION_REQUIRED`.
- **Two ports joined `ports.py`,** not one: `CredentialWriterPort` (only `store`, no `load`, asserted by a structural test) and `KeyInspectorRegistryPort` (`for_exchange`). The application layer must not import the infrastructure registry. `KeyInspectorPort` was already there from 8a-1.
- **`ConcurrentCredentialSave` is a domain error** raised by the vault, so the use case never imports SQLAlchemy. `SqlAlchemyCredentialVault.store` recognises the loss by the violated constraint's NAME (`ONE_ACTIVE_PER_EXCHANGE_CONSTRAINT`, the same asyncpg `__cause__.constraint_name` reading the booking repository uses). Three tests pin it from both sides: the name decides whatever the message says, a message that only mentions the index does not, and an `IntegrityError` with no name does not.
- **`store` now runs the deactivation and the insert in a SAVEPOINT.** A lost race undoes its own deactivation and leaves the caller's transaction usable. The row is built and sealed before the transaction touches the table, so a sealing failure changes nothing.
- **`check_confirmations` runs twice on the success path,** once in the use case (before any venue call, which is the point) and once inside `evaluate_key`. It is pure and cheap; `evaluate_key` keeps its own call so it cannot be used without the check.
- **`PERMISSIONS_UNAVAILABLE` logs two WARNINGs,** by design: the Bybit inspector names the unusable field (section K), and the use case names the exchange and the outcome, as it does for every refusal.
- **Where the race is decided.** The loser waits on Postgres's unique index while the winner's transaction is open, and gets the constraint error when the winner commits. Because the test holds the winner's insert uncommitted and asserts `not task.done()`, it is a lock-hold test in the project's sense, with Postgres's own index wait as the lock and no wrapper.

### K3. Implementation notes, PR 8a-2 (2026-09-29): the script fold

- **A shared module, `scripts/credential_cli.py`,** holds what the Binance and Bybit scripts have in common: the terminal prompt, `vault_saver` (the real wiring), `run_store` and the report. Section F said each script "calls `SaveCredential`"; through one module the two cannot drift, and both reach the same use case as the API will. `main(argv, *, prompt, make_saver)` takes both as arguments, which is what makes the scripts testable with fakes (rule 1).
- **Order inside a script:** parse the arguments, check the Binance flags, build the saver (which finds an unusable `MASTER_ENCRYPTION_KEY`), then prompt. Section F says the flag check precedes the secret prompt; the master-key check also precedes it now, so no secret is typed for a run that cannot succeed. Both are pinned by tests that assert the prompt fake was never called.
- **Exit codes:** 2 for a usage problem (missing flag, unknown flag), 1 for any refusal or failed prompt or master key, 0 for a save. A refusal prints `REFUSED (<OUTCOME>): <detail>`, one line of guidance and "Nothing was stored", all on stderr. Only the last four characters of the key are ever printed.
- **The post-save decrypt round trip stays,** in `vault_saver`, after the use case commits. If it fails the script raises `RoundTripFailed` and exits 1; the row is already committed, and the message says so.
- **`BinanceCredentials`/`BybitCredentials` are no longer used by the scripts:** `ExchangeCredential` validates the same things (non-empty, at least four characters), so the prompt builds it directly.
- **A read-only Bybit key** supersedes the previous active key like any other. The script says so in its warning ("it replaces the previous active key"), because decision 18's "one key per exchange" makes that the cost of accepting it.
- **The interim structural test** (`test_store_scripts_pass_facts.py`) now pins Pionex to `KeyFacts.unrecorded(trade_capable=True)` and asserts the folded scripts contain no direct `.store(` call and no `KeyFacts.unrecorded`.

### K4. Implementation notes, PR 8a-3 (2026-09-30): the redacted 422 and the client logs

- **`msg` is not always safe to keep.** Section H says the handler "strips `input`/`ctx`". Those are the two fields that hold submitted values, but pydantic's `msg` for a CUSTOM validator is the text of the `ValueError` (or failed `assert`) its author wrote, and that text often interpolates the value (`wire.Instant` does: `f"{value.isoformat()} has no time zone"`). The handler therefore keeps only `type`, `loc` and `msg`, and replaces `msg` with "Invalid value" for the two error types `value_error` and `assertion_error`. The field and the kind of mistake are still named by `loc` and `type`. A test feeds a validator that quotes the secret and watched it fail before this guard.
- **The handler takes `exc: Exception`,** not `RequestValidationError`: Starlette types every handler that way and mypy strict refuses the narrower signature. A different exception is re-raised, which cannot happen for a handler registered under `RequestValidationError`.
- **It logs nothing, on purpose.** A 422 is the client's mistake, and the only things a log line could add (the errors, the request) are what must not leave the response. A test drives seven kinds of bad body with a capture at DEBUG on every logger and finds no sentinel; a handler that logs `exc.errors()` failed six of them.
- **The handler is app-wide, so it also answers the webhook's and every other route's 422.** The shape is unchanged (`{"detail": [{type, loc, msg}]}`) but `input` and `ctx` no longer appear. No existing test read them.
- **S2 is one shared helper, `shared/infrastructure/http_logging.py`,** used by `create_app()` (first, before the app object exists) and by the worker's `_configure_logging`, which used to hold the loop itself.

### K5. Implementation notes, PR 8a-3 (2026-09-30): the credentials router

- **Wiring lives in the router module, not in `main.py`.** `get_save_credential` (a FastAPI dependency in `credentials_router.py`) builds the cipher, the live inspectors (`KeyInspectorRegistry.for_settings`, new, and now also used by `scripts/credential_cli.py`) and the vault over the request's session, the same way `pools_router` builds its adapter. `create_app()` only includes the router. Tests replace the dependency with a real `SaveCredential` over fakes. The API still never decrypts: `SaveCredential` receives the vault as a `CredentialWriterPort`, and no `.load(` call was added (6c.6 keeps its structural test).
- **The refusal body is `{outcome, detail, missing?}`, and `missing` is absent, not empty,** for every outcome but `CONFIRMATION_REQUIRED`. The success body is `{last4, facts, warnings}` with no `outcome` field: the status code is the discriminator, as section C wrote it.
- **The 404 for an unserved exchange is FastAPI's `{"detail": "..."}`, not the refusal shape.** It is not a save outcome (nothing was inspected), and `SaveOutcome` has no member for it. Pionex has no inspector, so `PUT /api/credentials/pionex` is 404.
- **`GET /credentials` has its own query and does NOT use `vault.hints()`.** Section 14 said `hints()` would include history rows (decision 21). `hints()` still returns active rows only, because the worker's startup check reads "which exchanges have a key" from it (`main.py`), and widening it would make a superseded key look like a present one. The listing selects the snapshot columns only (no ciphertext, no nonce, no wrapped key), and a test pins that the module names none of them and imports no cipher.
- **On an `EMPTY` entry `label` and `stored_at` are null too.** The task text lists them without `|null`, but says `EMPTY` nulls everything: a label or a stored time from a superseded key would describe a key that is not active. The `facts_of` mapping in the vault became public and takes a small `RecordedFacts` protocol, so the ORM row and the listing's column row are read by the one function.
- **Body limits.** `api_key` at least 4 characters (the same floor as `ExchangeCredential`), `api_secret` at least 1, `label` 1 to 64 characters and `default` when absent, `extra="forbid"`. The body is not stripped of whitespace; the CLI strips because `getpass` returns a trailing newline, and the frontend form (10f) will trim.
- **An unusable `MASTER_ENCRYPTION_KEY` is a 503 with one ERROR** (which reaches Telegram through the alert bridge), raised by the dependency before the use case runs. Section 5's "startup invariant 5" (fail the API lifespan on a bad key) was NOT added: it would refuse to boot the whole admin API, including the read-only routes, for a fault only the PUT has. The per-request 503 names the fault at the moment it matters.
- **The log test.** One real `uvicorn.Server` with uvicorn's own logging, the module's `create_app()` and the real Binance inspector over a mock transport, so the signed request is really made. Two PUTs (a save and a refused body), every logger hooked at DEBUG: `uvicorn.access`, `uvicorn.error`, `strategy_manager.*` (including `SaveCredential`'s own INFO line), `httpx`, `httpcore` and the root, plus stdout and stderr. The key, the secret and any `signature=` are absent, and no `httpx` or `httpcore` record exists.

## Addendum: allowed pairs validated against the venue catalogue (decisions 40 and 41) - 2026-10-02

Unit 9v. HEAD `05e8c0a`. Decision 41 is binding and is not reopened here. This addendum settles what it left to the design: the port, the public clients, the cache, where each check sits, the HTTP contract, the selector, and the PR split. It supersedes the `POST /strategies` and `PUT /strategies/{id}/allowed-pairs` rows of § 14 (already marked there) and the `NewStrategyDialog` and `AllowedPairsEditor` entries of § 15.

**The answer in one paragraph.** The `strategies` module declares a `PairCatalogPort` that answers "which pairs may a strategy on this capital pool trade". Its adapter reads each venue's PUBLIC catalogue with a transport that has no signer, keeps the result in memory for five minutes per pool, and reuses the read clients' own contract parser, so "available" means exactly "the order path could parse and would accept this market". `RegisterStrategy` checks every pair; `ReplaceAllowedPairs` checks only the pairs being added, and makes its venue call BEFORE it takes the strategy's row lock. A new read endpoint feeds a native, searchable selector that replaces the dialog's textarea.

### A. Findings from the code (verified at HEAD `05e8c0a`)

| # | Finding | Where | Consequence |
| --- | --- | --- | --- |
| V1 | No port returns a venue's symbol list. `ExchangePort` is per order. | `execution/application/ports.py` | A new port, declared by its consumer (`strategies`). |
| V2 | `BybitTransport.get` always signs, and the class cannot be built without a `BybitSigner`. | `shared/infrastructure/bybit/transport.py:37-49` | A credential-free Bybit transport is new work. |
| V3 | `BinanceTransport.get_public` does not sign, but the constructor still demands a `BinanceSigner`. | `shared/infrastructure/binance/transport.py:37-45` | A credential-free Binance transport is new work too. |
| V4 | `BybitReadOnlyClient.perp_contracts(limit=1000)` reads ONE page and ignores `nextPageCursor`. It parses eagerly: one malformed entry raises for the whole list. `bybit/trade_client.py:130` calls it on the order path. | `shared/infrastructure/bybit/read_client.py:335-344` | The new public read pages until the cursor is empty. The order path's own truncation risk is recorded as follow-up 9vf.1; this unit does not change a line the worker executes for an order. |
| V5 | `BinanceReadOnlyClient.perp_catalogue()` returns RAW entries on purpose, and `parse_contract` is public. | `shared/infrastructure/binance/read_client.py:250-274, 348-362` | The public read parses per entry inside a guard, with the same function. |
| V6 | The API process builds no venue client today except the key inspectors, which sign with the plaintext the operator submits. Their wiring is a `Depends(get_...)` factory. | `accounts/infrastructure/credentials_router.py:117-163` | The same injection pattern, so tests override the dependency. |
| V7 | `RegisterStrategy` takes no lock. `ReplaceAllowedPairs` takes the strategy row lock FIRST (`get_by_id_for_update`), before every other check. | `strategies/application/register_strategy.py:110-157`, `replace_allowed_pairs.py:52-77` | Replace is reordered so the venue call runs with no row lock held (§ E). |
| V8 | The pool venue id is `usdt-m` for both Bybit and Binance. `linear` is only Bybit's API category. | `accounts/domain/known_pools.py:44-49` | The source registry is keyed `(exchange, venue)` with `usdt-m`. The frontend harness's `pool("bybit", "linear")` describes a pool that cannot exist and is corrected in the frontend PR. |
| V9 | `ApiError` types `detail` as a string and builds its message from it. The API's structured refusals arrive as `{"detail": {"error", "message", ...}}`, an object. | `frontend/src/shared/api/client.ts:14-26` | `ApiError` learns to read a structured detail (§ G). Today the dialog decides by status alone, so nothing renders `[object Object]`, but nothing can name a symbol either. |

### B. Components, with hexagonal layer

| Component | Layer | File | Notes |
| --- | --- | --- | --- |
| `UnknownPairs`, `PairCatalogUnavailable`, `PairCatalogNotServed`, `PairsChangedConcurrently`; `unknown_pairs(candidates, available)` | **domain**/strategies | `strategies/domain/pair_catalog.py` | `DomainError`s and one pure set rule. No framework import. `UnknownPairs.unknown` is a sorted tuple. |
| `PairCatalogPort.available_pairs(pool: PoolKey) -> frozenset[str]` | **application**/strategies | `strategies/application/ports.py` | Returns `market_key` forms. Raises `PairCatalogNotServed` or `PairCatalogUnavailable`. No `execution` or `accounts` type appears in it. |
| `PoolCatalogPort.exists(pool: PoolKey) -> bool` (new method) | **application**/strategies | same file | A pool that is a row of `capital_pools`, enabled or not. Used only by the read endpoint. |
| `RegisterStrategy`, `ReplaceAllowedPairs` (changed); `ReadAvailablePairs` (new) | **application**/strategies | `register_strategy.py`, `replace_allowed_pairs.py`, `read_available_pairs.py` | § E and § F. |
| `VenuePairCatalog` (source registry, TTL cache, single flight); `PerpetualSymbolSource` protocol | **infrastructure**/strategies | `strategies/infrastructure/pair_catalog.py` | Implements `PairCatalogPort`. The only place that maps a venue symbol through `market_key`. |
| `pair_catalog_router`, `get_pair_catalog`, `get_read_available_pairs` | **infrastructure**/strategies | `strategies/infrastructure/pair_catalog_router.py` | `GET /api/pools/{exchange}/{venue}/{ccy}/available-pairs`. |
| `BybitPublicTransport`, `BybitPublicCatalogue` | **infrastructure**/shared | `shared/infrastructure/bybit/transport.py`, `bybit/public_catalogue.py` | No signer in either constructor. |
| `BinancePublicTransport`, `BinancePublicCatalogue` | **infrastructure**/shared | `shared/infrastructure/binance/transport.py`, `binance/public_catalogue.py` | Same. |
| `PerpContract.settles_in(currency)` on both venue read models; Bybit's `_parse_contract` made public as `parse_contract` | **infrastructure**/shared | `bybit/read_client.py`, `binance/read_client.py` | § C. |
| `Settings.pair_catalogue_ttl_seconds: float = 300.0` | shared config | `shared/config.py` | The only new setting. Base URLs and timeouts already exist (`bybit_base_url`, `bybit_timeout_seconds`, `binance_futures_base_url`, `binance_timeout_seconds`). |
| `scripts/check_public_catalogue.py` | dev tool, GET-only | `backend/scripts/` | Probe P7 (§ J). Loads no credential. |
| `PairSelector`, `useAvailablePairs`, `ApiError.code` / `.fields` | frontend | `features/strategies/PairSelector.tsx`, `shared/api/pairs.ts`, `shared/api/client.ts` | § G. |

**Why the port lives in `strategies` and not in `execution`.** The question is a strategy-configuration question ("may this strategy list this pair on its pool"), and the consumer declares the port (`strategies/application/ports.py` header; `strategies/infrastructure/pool_catalog.py` header). `ExchangePort` is the worker's order port; widening it would pull the API process toward the signed adapters, which is the boundary rule 8 protects.

**Why the venue clients live in `shared/infrastructure`.** That is where `BybitReadOnlyClient` and `BinanceReadOnlyClient` already live, next to the parser they must share. `shared` cannot import `strategies`, so the venue classes raise their own `BybitApiError` / `BinanceApiError`, and `VenuePairCatalog` translates them into the port's `PairCatalogUnavailable`.

### C. The credential-free transports and the shared parsing

**A transport that cannot sign, by type.** Each venue gains a second transport class whose constructor takes only `httpx.AsyncClient`:

```python
class BybitPublicTransport:      # shared/infrastructure/bybit/transport.py
    def __init__(self, http: httpx.AsyncClient) -> None: ...
    async def get(self, path: str, params: Mapping[str, str] | None = None) -> Any: ...

class BinancePublicTransport:    # shared/infrastructure/binance/transport.py
    def __init__(self, http: httpx.AsyncClient) -> None: ...
    async def get(self, path: str, params: Mapping[str, str] | None = None) -> Any: ...
```

- The envelope handling is not duplicated. Each `_send` method body becomes one module-level function in the same file, and both the signed and the public class call it. So a Bybit `retCode != 0` over HTTP 200, a Binance negative `code`, and Binance's HTTP 451 are read identically with or without a signature.
- `BinanceTransport.get_public` keeps its signature and delegates to the public class.
- These two extractions and the rename in the next paragraph are the ONLY edits to files the worker imports. They change no behaviour, and the existing tests of both venue packages must pass unmodified. That is stated as a task acceptance criterion, because it is what keeps this unit off the order path.

**Rejected:**
- Making the signer optional (`BybitSigner | None`) on the existing transports. A `None` signer that reaches `get()` is a runtime failure on the worker's order path, and the type would stop saying "this object can sign".
- A fake or empty credential passed to the existing clients. It would put a credential-shaped object in the API process, and a signed request with a junk key is refused by the venue.
- A separate parser for the catalogue that reads only `symbol`, `contractType`, `status` and the settle coin. Lighter, but it would list a market whose trading rules the order path cannot parse, so the selector would offer a pair that every order then refuses.

**One filter, reused.** The public catalogues parse each entry with the read clients' own function and apply the read models' own properties:

```python
contract.is_perpetual and contract.is_trading and contract.settles_in(settlement_currency)
```

- `is_perpetual` and `is_trading` are the properties `assert_tradable` already uses before every order (`bybit/read_client.py:94-106, 133-141`; `binance/read_client.py:114-128`). Bybit: `contractType == "LinearPerpetual"`. Binance: `contractType == "PERPETUAL"`, which already excludes `TRADIFI_PERPETUAL` and the quarterlies.
- `settles_in(currency)` is new on both models: Bybit compares `settle_coin`, Binance compares `margin_asset`, both case-insensitively. Bybit's existing `is_usdt_settled` becomes `settles_in("USDT")`.
- The symbol string is never the criterion. `BTCUSDT-25DEC26` and `BTCUSDT_251226` are excluded because of their contract type, not their suffix (decision 41).

**Bybit pagination.** `BybitPublicCatalogue` requests `category=linear&limit=1000` and follows `nextPageCursor` until it is empty, exactly as `fills_in_window` does (`read_client.py:300-333`). A hard page cap (10) raises `BybitApiError` instead of returning a partial list. Probe P7 records whether the cursor is present and how many pages today's listing takes.

**Malformed entries.** Each entry is parsed inside its own guard:
- An entry that fails to parse is skipped and counted. After the read, ONE WARNING names the venue, the count and up to ten of the symbols (`<no symbol>` when even that is unreadable). It is one line per read, not one per entry, so a venue-wide shape change cannot flood the log.
- If the listing is non-empty and NO pair survives the filter, the read raises instead of returning an empty set, and one ERROR names the contract types and statuses that were seen. This is the Pionex lesson (`type: "PERP"` against the documented `contractType: "PERPETUAL"`): a renamed field would otherwise turn every valid symbol into an "unknown pair", which is a wrong message, not a refusal. The ERROR reaches Telegram through the alert bridge.
- A skipped entry is treated as not available. That is fail-closed and consistent: the order path could not parse it either.

### D. `VenuePairCatalog`: registry, cache and concurrency

```python
class PerpetualSymbolSource(Protocol):
    async def tradable_perpetuals(self, settlement_currency: str) -> tuple[str, ...]: ...

class VenuePairCatalog:                       # implements PairCatalogPort
    def __init__(self, sources: Mapping[tuple[str, str], _Source],
                 ttl_seconds: float, monotonic: Callable[[], float]) -> None: ...
    @classmethod
    def for_settings(cls, settings: Settings) -> "VenuePairCatalog": ...
    async def available_pairs(self, pool: PoolKey) -> frozenset[str]: ...
```

**Registry.** Keyed `(exchange, venue)`: `("bybit", "usdt-m")` and `("binance", "usdt-m")`. Each entry pairs a source with the venue error type it raises. A pool with no entry raises `PairCatalogNotServed`: there is no fallback and no empty list, the same rule as `VenueExchangeRegistry`. Today that means every Pionex pool (no public unsigned transport exists for it, and it has no adapter).

**Cache.**

| Property | Choice | Why |
| --- | --- | --- |
| Where | In memory, in the one `VenuePairCatalog` instance of the API process | Decision 41 rejected a table. The data is public, small and cheap to refetch. |
| Key | The full pool key `(exchange, venue, settlement_currency)` | Capital-pool isolation: one pool's list can never answer for another, even on the same venue. |
| Value | `frozenset` of `market_key(symbol)` plus the monotonic time of the read | Decision 41: comparison is always in `market_key` form. |
| TTL | 300 s, `Settings.pair_catalogue_ttl_seconds` | Long enough that opening the dialog and saving use one read; short enough that a new listing appears within minutes. |
| A stale entry means | A pair delisted less than one TTL ago is still accepted; a pair listed less than one TTL ago is refused as unknown until the entry expires | Both are bounded by the TTL. The first is caught loudly at order time by `assert_tradable`; the second is fixed by retrying. |
| Expired entry and the refresh fails | The call raises `PairCatalogUnavailable`. An expired entry is never served | Decision 41: fail closed. |
| Failures | Never cached | The next request retries the venue. |
| Lifetime | Lost on restart; one cache per process | Nothing depends on it surviving. |
| Bound | At most one entry per served pool | The read endpoint checks that the pool is a `capital_pools` row before it asks, and an unserved `(exchange, venue)` raises before anything is stored. |

**Concurrent requests.** One `asyncio.Lock` per pool key, with a check before and after acquiring it. Two requests that miss the cache together make ONE venue call; the second waits and reads the fresh entry. This lock is an in-process lock, not a database lock. The request that holds it holds no row lock and no advisory lock (§ E), so it cannot join a database lock cycle.

**The HTTP client.** One `httpx.AsyncClient` per read, built with the venue's base URL and timeout from `Settings`, as the key inspectors do (`key_inspectors/bybit.py:82-84`). Reads are rare (at most one per pool per TTL), so no connection is kept open. `transport` is injectable for `httpx.MockTransport`.

**What is logged.**

| Event | Level | Content |
| --- | --- | --- |
| A real venue read | INFO | exchange, venue, settlement currency, entries listed, pairs available, entries skipped, pages, elapsed ms |
| Entries skipped as malformed | WARNING | venue, count, up to ten symbols |
| A non-empty listing with no available pair | ERROR | venue, contract types and statuses seen |
| The venue could not be read | WARNING | exchange, venue, the venue's code or HTTP status; never a URL |
| A cache hit | nothing | It would be one line per keystroke of the operator's work |

### E. Where the checks sit

**`RegisterStrategy`** gains `pairs: PairCatalogPort`. It takes no lock, so the order is only about not calling a venue for a request that would be refused anyway:

1. already registered → `StrategyAlreadyRegistered` (unchanged)
2. pool enabled → `PoolNotAvailable` (unchanged)
3. normalize with `market_key`, at least one pair → `EmptyAllowedPairs` (unchanged)
4. **new:** `available = await pairs.available_pairs(pool)` → `PairCatalogNotServed` or `PairCatalogUnavailable`
5. **new:** `unknown_pairs(normalized, available)` not empty → `UnknownPairs`, one WARNING naming the strategy id, the pool and the symbols
6. insert, commit (unchanged)

**`ReplaceAllowedPairs`** gains `pairs: PairCatalogPort`. Today its first statement takes the row lock. The venue call must not run under it: a venue timeout is ten seconds, and the same row lock serializes the `enabled` toggle (`UpdateStrategy`).

```
 Panel            ReplaceAllowedPairs          Repository            PairCatalogPort      Venue
   │ PUT pairs N          │                        │                       │                │
   ├─────────────────────►│ get_by_id (NO lock)    │                       │                │
   │                      ├───────────────────────►│ stored S1             │                │
   │                      │  unknown id → 404 · archived → 409             │                │
   │                      │  normalize N → 422 if empty                    │                │
   │                      │  candidates = N − S1   │                       │                │
   │                      │  (empty → skip the catalogue entirely)         │                │
   │                      ├───────────────────────────────────────────────►│ cache or GET   │
   │                      │                        │                       ├───────────────►│
   │                      │  available             │                       │◄───────────────┤
   │                      │◄───────────────────────────────────────────────┤                │
   │                      │  candidates − available ≠ ∅ → 422 UNKNOWN_PAIRS│                │
   │                      │ get_by_id_for_update   │                       │                │
   │                      ├───────────────────────►│ ROW LOCK, stored S2   │                │
   │                      │  re-check: gone → 404 · archived → 409         │                │
   │                      │  added = N − S2                                │                │
   │                      │  added ⊄ candidates → 409 PAIRS_CHANGED        │                │
   │                      │ update, commit (lock released)                 │                │
   │◄─────────────────────┤                        │                       │                │
```

- **Only added pairs are validated** (decision 41). `candidates` is the request minus what is stored. A pair already stored is never looked up, so a delisted pair can be kept or removed.
- **A replace that adds nothing never calls the venue.** Removing a pair therefore works while the venue is down. This follows from "only added pairs are validated" and costs nothing.
- **The re-check under the lock closes the one gap the reorder opens.** Between the unlocked read and the row lock, another request can change the stored list. If the list under the lock makes a pair "added" that was not in `candidates`, that pair was never validated, and storing it would break decision 41's "nothing is stored unvalidated". The request is refused with `PairsChangedConcurrently` (409 `PAIRS_CHANGED`), nothing is written, and the operator retries against the current list. The opposite drift (a candidate that is no longer an addition) is harmless: it was validated anyway.
- **Lock order.** The project rule is "pool advisory lock first, then row locks". This use case takes no advisory lock, exactly one row lock, and takes it after the last external call. No venue call runs while any PostgreSQL lock is held, in either use case.
- **Accepted cost.** The unlocked read opens the request's transaction, which stays open, idle, during a venue read (at most the venue timeout, and only on a cache miss). It holds no row lock. Its table-level `ACCESS SHARE` conflicts only with DDL, so a migration started in that window waits for it.
- The existing row-lock guarantee is unchanged: the write still happens under `get_by_id_for_update`, so the PUT cannot revert a concurrent `PATCH enabled` (`replace_allowed_pairs.py:14-24`).

**Error types and HTTP mapping** (both routes; the body is FastAPI's `{"detail": {...}}`, as `STRATEGY_ARCHIVED` is today):

| Error | Status | `detail` | Why this status |
| --- | --- | --- | --- |
| `UnknownPairs` | 422 | `{"error": "UNKNOWN_PAIRS", "message", "unknown": [...]}`, `unknown` sorted, in `market_key` form | The input is the problem (§ 14 conventions; decision 41). |
| `PairCatalogNotServed` | 422 | `{"error": "PAIR_CATALOGUE_NOT_SERVED", "message"}` | The request names a pool this system cannot validate pairs for. It is the same class as "bad pool", which is already 422. |
| `PairCatalogUnavailable` | **502** | `{"error": "PAIR_CATALOGUE_UNAVAILABLE", "message"}` | § 14: "502: the upstream venue failed", the status `VENUE_UNREACHABLE` already uses on `PUT /credentials`. 503 stays reserved for "this deployment is configured not to", and 422 would tell the operator their input was wrong when it was not. The body carries its own code, so the dialog does not depend on the status alone. |
| `PairsChangedConcurrently` | 409 | `{"error": "PAIRS_CHANGED", "message"}` | A state conflict: the request is well-formed and the target changed underneath it. |

Each refusal logs one WARNING in the use case (strategy, pool, and the symbols or the reason). The existing 404, 409 and 422 answers keep their shapes.

**Wiring.** Both routes stop building their use case inline (`router.py:206-216, 293-299`) and take it from a dependency, `get_register_strategy` and `get_replace_allowed_pairs`, in the same style as `get_save_credential`. Both read the catalogue from `get_pair_catalog`, which returns the single `VenuePairCatalog` that `create_app()` builds once and keeps on `app.state.pair_catalog`. Tests override `get_pair_catalog` with a fake, so no router test needs a network. `main.py` gains only the construction and the `include_router` line.

### F. The read endpoint

`GET /api/pools/{exchange}/{venue}/{settlement_currency}/available-pairs`

- **Why this path.** The resource is a property of a capital pool, and the path names the pool's settlement currency explicitly, as `/performance/pools/{exchange}/{venue}/{ccy}` does. It lives in the `strategies` module (it serves the port `strategies` declares) in its own router with prefix `/pools`. A path under `/strategies/...` was rejected: a literal segment beside `/{strategy_id}` depends on declaration order, and a late declaration turns it into a 422 on the UUID.
- **Auth.** The router carries `dependencies=[Depends(require_admin_token)]`, like every admin router, and is included in `api_router`. The existing walk over every `/api` route covers it without edits; so does the pool-management inventory test, because the route is a GET.
- **Response.** `{"pool": {"exchange", "venue", "settlement_currency"}, "pairs": ["AAVEUSDT", ...], "count": N}`. `pairs` is sorted and in `market_key` form, which is the form the save accepts back. No money, quantity or ratio is in it.
- **Size.** One string per perpetual: about 800 for Bybit and several hundred for Binance (P7.4 records the real counts), in the order of 10 to 15 KB. It is returned whole. Search is client-side, and there is no pagination or `q` parameter, because the list is already in the server's memory and the selector needs all of it to mark a stored pair as no longer listed.

| Case | Answer | Notes |
| --- | --- | --- |
| The pool is not a row of `capital_pools` (unknown exchange, wrong-case currency, unconfigured triple) | 404 `{"detail": "no such pool"}` | Path values are strings, as on the performance routes, so none of these is a 422. Checked BEFORE the catalogue, so a made-up path never causes a venue call or a cache entry. |
| The pool exists but is disabled | 200, the list | The catalogue is public and needs no key. An existing strategy on a pool that was later disabled can still have its pairs edited (`ReplaceAllowedPairs` never checked the pool's flag). |
| The pool exists and has no catalogue source (Pionex) | 404 `{"detail": {"error": "PAIR_CATALOGUE_NOT_SERVED", "message"}}` | Never an empty list: an empty list would read as "this venue lists nothing". The structured body distinguishes it from an unknown pool. On a save the same condition is a 422, because there the input names the pool. |
| The venue cannot be read | 502 `{"detail": {"error": "PAIR_CATALOGUE_UNAVAILABLE", "message"}}` | Same code as on a save. |

`ReadAvailablePairs(pools: PoolCatalogPort, pairs: PairCatalogPort)` is the use case: `exists` → `available_pairs` → sorted. The router only maps errors.

### G. Frontend

**`ApiError` reads a structured detail** (`shared/api/client.ts`). Two fields are added and nothing is removed:

- `code`: `detail.error` when `detail` is an object, else `outcome`.
- `fields`: the `detail` object when it is one, else `undefined`.
- When `detail` is an object, `detail` (the string property) becomes `detail.message`, so the error's `message` is never `[object Object]`.

**`useAvailablePairs(pool | null)`** (`shared/api/pairs.ts`).
- Query key `['available-pairs', exchange, venue, settlement_currency]`. It is deliberately not under `['pools']`, which refetches every 60 s.
- `enabled` only when a pool is chosen. `staleTime` 5 minutes, matching the server's TTL. `retry: 1`.
- It validates the top-level shape (`pairs` is an array of strings), like every other call function.

**`PairSelector`** (`features/strategies/PairSelector.tsx`), presentational and controlled, built on native elements only:

```ts
interface PairSelectorProps {
  id: string;
  label: string;
  value: readonly string[];                 // selected pairs, market_key form
  onChange: (next: string[]) => void;
  options: readonly string[] | undefined;   // the pool's available pairs
  status: "idle" | "loading" | "error" | "ready";
  onRetry: () => void;
  describedBy?: string;
  disabled?: boolean;
}
```

- **Structure.** A `<fieldset>` with a `<legend>`; a labelled `<input type="search">`; a scrollable list of native checkboxes, each inside its own `<label>`; and the selected pairs as chips, each with a remove `<button>` whose accessible name contains the symbol. Native checkboxes give Tab and Space for free; no ARIA combobox pattern is hand-built.
- **Search.** A case-insensitive substring match after the typed text is upper-cased and stripped of `.P` or `_PERP`, so pasting TradingView's `STXUSDT.P` finds `STXUSDT`. This is a display filter; the server decides what is valid.
- **Many results.** At most 50 matches are rendered. A polite live region says how many match and that typing narrows the list. No virtualisation is needed.

| State | What renders |
| --- | --- |
| `idle` (no pool chosen yet) | The search input disabled, with "Choose a pool first" |
| `loading` | A `role="status"` line; the list is absent |
| `error` | A `role="alert"` line and a Retry button; chips stay and stay removable |
| `ready`, the filter matches nothing | "No pair matches" |
| `ready`, more than 50 matches | The first 50 and the count line |

- **A selected pair that is not in `options`** (status `ready`) is shown as a chip marked "no longer listed", in neutral `ink-3`, and stays selected until the operator removes it. It is never dropped silently: a silent drop would turn the next PUT into an unintended removal. Once removed it cannot be re-added, which matches the server (a re-add is an addition and is refused). It is neutral, not amber, because amber means an action is needed (addendum key policy § G) and keeping a delisted pair is allowed (decision 15).

**`NewStrategyDialog`.** The textarea, `parsePairs` and `pairsHint` go. The selector's `options` come from `useAvailablePairs` for the chosen pool. Changing the pool clears the selection, because pairs belong to one pool's catalogue. Submit stays disabled until the status is `ready`. The error text is chosen by `error.code`, then by status as a fallback:

| `code` (fallback) | i18n key | Text (EN) |
| --- | --- | --- |
| `UNKNOWN_PAIRS` | `strategies.pairs.errors.unknown` | "The exchange does not list: {{symbols}}." (from `fields.unknown`) |
| `PAIR_CATALOGUE_UNAVAILABLE` (or any 502) | `strategies.pairs.errors.venueUnavailable` | "The exchange's pair list could not be read, so nothing was saved. Try again." |
| `PAIR_CATALOGUE_NOT_SERVED` | `strategies.pairs.errors.notServed` | "Pairs cannot be checked for this pool, so a strategy cannot be created on it." |
| `PAIRS_CHANGED` (editor only) | `strategies.pairs.errors.changed` | "The list changed while you were editing. Review it and save again." |

Other new keys, EN and ES: `strategies.pairs.search`, `.choosePool`, `.loading`, `.loadFailed`, `.retry`, `.noMatch`, `.showing` (`{{shown}}` of `{{total}}`), `.remove` (`{{symbol}}`), `.notListed`, `.selected`.

**`AllowedPairsEditor` (unit 9d)** reuses `PairSelector` with the strategy's pool and its stored pairs as the initial `value`. Two differences from the dialog, both following § E: in status `error` the editor still allows a save that only removes pairs (the server needs no catalogue for it), and the "no longer listed" chips are where a seeded or delisted pair shows up. Unit 9d's two existing RED tests keep their meaning; its files are not created by unit 9v.

**The harness.** `frontend/src/test/harness.tsx` defaults to `pool("bybit", "linear")`, a venue that does not exist (V8). The frontend PR changes it to `usdt-m`, adds an available-pairs route to `stubApi`, and updates the tests that spell `linear/USDT`.

### H. Impact on `DRY_RUN`, idempotency and capital-pool isolation

| Rule | Impact |
| --- | --- |
| **`DRY_RUN` (rule 1)** | The API process makes real, public, unsigned GETs to Bybit and Binance in both modes. No order, no key, no account data. The flag does not gate them, because the validation must be true before the system goes live, not after. No test needs the network: sources are driven by `httpx.MockTransport`, and everything above them by a fake `PairCatalogPort`. |
| **Idempotency (rule 2)** | Untouched. The signal path, the idempotency key and the job queue do not call the catalogue. A strategy's id is still the alert's `signalType`. A register retried with the same id is still refused by `StrategyAlreadyRegistered` before any venue call. |
| **Webhook (rule 3)** | Untouched. The catalogue is called only from admin routes, never from ingress or the worker. A slow venue can slow a save in the panel and nothing else. |
| **Allocation transaction (rule 4)** | Untouched. Neither use case takes the pool advisory lock, and no venue call runs under a row lock. |
| **Capital-pool isolation (rule 5)** | The catalogue is keyed and cached by the full pool key, and filtered by the pool's settlement currency. No balance is read, nothing is reserved, and no pool's list is ever merged with another's. A USDC-settled contract is not offered to a USDT pool. |
| **Ledger and PnL (rules 6, 7)** | Untouched. No write outside `strategies.allowed_pairs`. |
| **Credentials (rule 8)** | The public transports take no signer by type. A structural test asserts that the new modules import no signer, no vault and no cipher. |
| **Existing data** | No migration. Pairs already stored are never revalidated: production's `SFPUSDT`, `AAVEUSDT` and `STXUSDT` stay as they are, listed or not. |

### I. Failure modes (what fails here without a log line?)

| Failure | Guard |
| --- | --- |
| Bybit's listing grows past one page and the tail is silently missing, so valid pairs are refused as unknown | The cursor is followed to its end; a page cap raises rather than truncating; the INFO line records pages and counts |
| One malformed market makes the whole catalogue unreadable | Per-entry guard; the entry is skipped |
| A malformed market is dropped and nobody learns why its pair is "unknown" | One WARNING per read naming the count and the symbols |
| The venue renames a field or value and every market is filtered out, so every save says "unknown pair" | A non-empty listing with no available pair raises `PairCatalogUnavailable` and logs an ERROR with the values seen |
| The venue is down and the save stores the pair anyway | Fail closed: 502, nothing written; one WARNING |
| An expired cache entry is served as if fresh | Never served; the refresh either succeeds or raises |
| One pool's list answers for another pool | The cache key is the full triple; a test reads two settlement currencies on one venue |
| A pool with no source (Pionex) is accepted unvalidated | `PairCatalogNotServed`: refused on save, structured 404 on read, never an empty list |
| The venue call runs under the strategy row lock and a slow venue freezes the enabled toggle | The call precedes the lock; proven on real PostgreSQL (§ K) |
| A concurrent edit makes an unvalidated pair "added" under the lock | 409 `PAIRS_CHANGED`, nothing written, one WARNING |
| A delisted stored pair vanishes from the editor and the next save removes it | The selector keeps it as a marked chip until the operator removes it |
| The dialog shows "invalid" and never names the symbol | `ApiError.code` and `fields.unknown`; the message lists the symbols |
| A proxy replaces the 502 body | The dialog falls back to the status: any 502 reads as "the pair list could not be read" |
| A credential reaches the API's venue client | No signer parameter exists; structural import test |

**Threat matrix.** The skill's matrix stays N/A (no shell, subprocess or VCS automation). Three project-specific rows extend the table of § Threat matrix (they are recorded here, not there):

| Threat | Safe behaviour | RED test |
| --- | --- | --- |
| The new `/api` route ships without auth | Auth is a router dependency | The existing parametrized walk over `app.routes` |
| A path value steers the outbound request (SSRF) | Base URLs come from `Settings`; the three path values only select a registry entry and a filter value, and never become part of a URL; an unknown pool is refused before any venue call | A request for an unknown pool makes zero transport calls; the recorded request URL is the configured host and the fixed path |
| An authenticated caller makes the API hammer a venue | One read per pool per TTL, single flight, and only for pools that exist | N concurrent requests produce one transport call |

### J. Probe P7 (owner-run, before the adapters are written)

`backend/scripts/check_public_catalogue.py`, in the style of `check_key_permissions.py`. GET-only. It builds a bare `httpx` client from `bybit_base_url` and `binance_futures_base_url` and loads no credential at all: no vault, no signer, no API-key header.

It answers, for each venue:

| # | Question | Why the adapters depend on it |
| --- | --- | --- |
| P7.1 | Does the endpoint answer 200 with NO signature and NO key header, from the VPS? | The whole design assumes it. Binance answers 451 by location, so "it works from a laptop" proves nothing. |
| P7.2 | How many entries are listed, and how many by contract type, by status and by settle or margin coin? | The exact strings for the filter (`LinearPerpetual`, `Trading`, `PERPETUAL`, `TRADING`) and the count the page cap must clear. |
| P7.3 | Bybit: is `nextPageCursor` present at `limit=1000`, and is it empty on the last page? With a small limit, does following the cursor return every entry exactly once? | The loop's termination condition. An absent key and an empty string must both end it. |
| P7.4 | How many pairs survive the filter for `USDT`? | The expected size of the selector, and the non-empty guard. |
| P7.5 | Are `SFPUSDT`, `AAVEUSDT` and `STXUSDT` available on each venue? | Informational: it tells the owner whether a stored pair will show as "no longer listed". It gates nothing. |
| P7.6 | Response size and elapsed time; the rate-limit headers the venue returns | Confirms the timeout and the TTL are sane. |

The script prints counts and symbols only. There is nothing secret to redact, and it still never prints a header or an environment value. The results are recorded in tasks.md before task 9va.3.

### K. Testing strategy

| Layer | What | How |
| --- | --- | --- |
| Unit, shared infra | Public transports send no auth header and unwrap envelopes like the signed ones; catalogue filter; pagination; malformed entries; the non-empty guard | `httpx.MockTransport`, reusing the wire fixtures `BTC_PERP`, `BTC_DATED` (`tests/shared/infrastructure/bybit/test_read_client.py`) and `AAVE`, `TRADIFI`, `QUARTERLY` (`binance/test_futures_rules.py`) |
| Unit, strategies infra | `VenuePairCatalog`: registry, `market_key` mapping, TTL, no stale-on-error, failures not cached, single flight, pool-keyed isolation | Fake sources, an injected monotonic clock |
| Unit, application | Register and Replace: order of checks, added-only rule, no catalogue call for a pure removal, every refusal and its WARNING | Fakes; existing tests gain a fake catalogue in `_build` |
| Integration, real PostgreSQL | No venue call under the row lock; the write still serializes on the row lock; `PAIRS_CHANGED` | Lock-hold harness (below) |
| Router | Status and body of every refusal; the read endpoint's four cases; auth | `httpx.AsyncClient` over ASGI with `dependency_overrides[get_pair_catalog]` |
| Structural | The new modules import no signer, vault or cipher | Module-source test, as `test_no_decrypt_in_api_path.py` |
| Frontend | `ApiError` structured detail; `PairSelector` states, keyboard, the "no longer listed" chip; the dialog's submit body and error text in EN and ES | Vitest, `vi.stubGlobal("fetch")` |

**Rules that bind the task breakdown.**
- **Strict TDD.** Each RED fails on an ASSERTION. A new constructor argument or a new module is first added as a stub that compiles and answers wrongly (an empty set, an accept-everything catalogue), so the first failure is never an import or a `TypeError`. A test that passes at once is proven by a named mutation.
- **Symbol spelling.** A test that crosses a boundary uses a different spelling on each side. The venue fixture lists `STXUSDT`; the request sends `STXUSDT.P` (register) or `STXUSDT_PERP` (replace); the stored and returned form is `STXUSDT`. The frontend types `stxusdt.p` and selects `STXUSDT`.
- **The lock property is proven on real PostgreSQL, with a lock-hold harness, never a `sleep(0)` barrier.**
  - *No venue call under the row lock:* a fake catalogue parks the replace inside `available_pairs` on an `asyncio.Event`. While it is parked, a second connection takes the strategy row with `SELECT ... FOR UPDATE NOWAIT` and succeeds. Mutation: moving the catalogue call after `get_by_id_for_update` makes `NOWAIT` raise `LockNotAvailableError`.
  - *The second actor still waits for the write:* a holder keeps the row lock in an open transaction; the replace, already past its catalogue call, is started; the test asserts `not task.done()` and polls `pg_locks` until the replace shows as waiting; the holder commits; the replace then completes against the row it re-read.
  - *`PAIRS_CHANGED`:* while the replace is parked in the catalogue, another transaction removes a pair the request also contains and commits; the replace resumes and is refused, and the row is unchanged.
- **Gate after every unit.** Backend: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`. Frontend: `npm run lint` and `npm test`.

### L. Delivery, forecasts and open questions

**The PR split.** Decision 41 names two deliveries, backend then frontend, after a probe. The backend delivery forecasts at about 1,550 to 2,250 authored lines with the measured bias applied, four times the review budget, so it is split into three sequential PRs to `main`. The frontend delivery forecasts at about 850 to 1,250 and is split into two. The probe script is its own small PR, as P6 was (PR 8a-0). None is stacked: each branch is cut from `main` after the previous one merged and deployed.

```
 PR 12a-2 ─► 12v-0 probe ─► [owner runs P7] ─► 12v-1 sources ─► 12v-2 catalogue + read
                                                                        │
                              12v-5 dialog ◄─ 12v-4 selector ◄─ 12v-3 refusals
```

| PR | Unit | Contents | Forecast | Deploy | Rollback boundary |
| --- | --- | --- | --- | --- | --- |
| **12v-0** | 9v0 | `scripts/check_public_catalogue.py` and its unit test | 200-300 | Pull only. The owner runs P7. | One dev script, imported by nothing |
| **12v-1** | 9va | Public transports (the two `_send` extractions), `settles_in`, `parse_contract` made public, `BybitPublicCatalogue` with the cursor loop, `BinancePublicCatalogue`, their tests | 500-700 | Pull, restart both (the worker imports the two transport files) | New classes that nothing calls yet, plus two behaviour-preserving extractions pinned by the existing venue tests |
| **12v-2** | 9vb | Domain errors, `PairCatalogPort`, `PoolCatalogPort.exists`, `VenuePairCatalog` with the cache, `ReadAvailablePairs`, the router, `Settings` field, wiring, the structural test | 550-800 | Pull, restart the API | One GET route and its adapter; revert 404s the path, and nothing else reads the catalogue yet |
| **12v-3** | 9vc | The refusals in `RegisterStrategy` and `ReplaceAllowedPairs`, the reorder, the dependency factories, the HTTP mapping, the real-PostgreSQL lock tests | 500-750 | Pull, restart the API | Two use cases and their router mapping; revert restores normalize-only saves, and pairs stored meanwhile stay valid |
| **12v-4** | 9vd | `ApiError` structured detail, `useAvailablePairs`, `PairSelector` (not mounted), i18n keys | 450-650 | Pull, no restart | New files and two added fields; nothing mounts the selector |
| **12v-5** | 9ve | The selector in `NewStrategyDialog`, the error texts, the harness correction | 400-600 | Pull, no restart | One dialog; revert restores the textarea, and the server still validates |

Total 2,600 to 3,800 authored lines.

- **Why 12v-3 is alone.** It is the only PR that changes what a save does, and the only one with a concurrency boundary. By then the catalogue has been live behind the read endpoint, so its counts and logs have been seen in production before any save depends on it.
- **Between 12v-3 and 12v-5** the textarea is still there. A typo is now refused with a 422 the old dialog reports as "the pairs were refused", without the symbol. That is safe and brief.
- `Decision needed before apply: No` · `Chained PRs recommended: Yes` · `400-line budget risk: High`.

**Design decisions made here** (not owner decisions; each has its reason above):

| # | Decision | Section |
| --- | --- | --- |
| D1 | The port is `PairCatalogPort.available_pairs(pool) -> frozenset[str]`, declared in `strategies` | B |
| D2 | A public transport class without a signer, sharing the envelope function with the signed one | C |
| D3 | The catalogue reuses the read clients' full contract parser and `is_perpetual` / `is_trading`, plus a new `settles_in` | C |
| D4 | The Bybit read follows `nextPageCursor`, with a page cap that raises | C |
| D5 | A malformed entry is skipped with one WARNING; a non-empty listing with no available pair is unreadable, with an ERROR | C |
| D6 | In-memory cache, keyed by the full pool key, 300 s, no stale-on-error, failures not cached, single flight | D |
| D7 | Replace: unlocked read, catalogue, then the row lock and a re-check; a pure removal never calls the venue | E |
| D8 | 409 `PAIRS_CHANGED` when a concurrent edit would make an unvalidated pair an addition | E |
| D9 | Venue unreachable is 502 `PAIR_CATALOGUE_UNAVAILABLE` | E |
| D10 | A pool with no source is refused: 422 on save, structured 404 on read | E, F |
| D11 | `GET /api/pools/{exchange}/{venue}/{ccy}/available-pairs`, whole list, served for a disabled pool too | F |
| D12 | The selector is native checkboxes with a search input, 50 rendered matches, and a "no longer listed" chip that is never dropped | G |
| D13 | Query key `['available-pairs', exchange, venue, ccy]`, `staleTime` 5 minutes | G |
| D14 | Six PRs: probe, three backend, two frontend | L |

**Open questions for the owner.** None blocks the probe (12v-0) or 12v-1.

- **Q1. A pool with no catalogue source refuses every new strategy (D10).** Today that is every Pionex pool, and all of them are disabled, so nothing changes in production. But if a Pionex spot pool were ever enabled again, no strategy could be registered on it until a catalogue source exists for it. The alternative is to accept pairs unvalidated on such a pool, which is the silent acceptance decision 40 removes. Recommended: refuse. This is a product choice about Pionex's future, so it is asked. It blocks only the `PairCatalogNotServed` tasks of 12v-3.
- **Q2. The split into six PRs (D14).** Decision 41 said a backend PR and a frontend PR. The forecast puts the backend at four times the review budget. Recommended: the split above. The alternative is two PRs with an explicit size exception. Under `auto-chain` the split proceeds unless the owner says otherwise.
- **Q3. Follow-up 9vf.1, outside this unit.** The ORDER path has the truncation risk V4 describes: `bybit/trade_client.py:130` reads one page of 1,000. If Bybit's `linear` listing passes 1,000 entries, a market on the second page is refused at order time as not listed. It fails closed and loudly, but it would refuse a valid signal. Probe P7.2 records today's count (about 840 on 2026-08-26: 800 perpetuals and 40 dated futures). The question is priority: fix it right after 12v-1 (the paged read already exists by then and the change is small), or leave it as a recorded follow-up. Recommended: right after 12v-1, as its own small PR, because it touches the order path and deserves its own review.

## Addendum: deleting a strategy that has no history (decision 42) - 2026-10-02

Unit 9x. HEAD `d162fe6`. Decision 42 is binding and is not reopened here. This addendum settles what it left to the design: every table that references a strategy, the no-history check and its locks, hard delete versus a tombstone, the endpoint, the panel control, and the PR split. It adds the `DELETE /strategies/{id}` row to § 14 (marked there) and corrects § 8, whose archive sequence assumed that a strategy row is never deleted.

**The answer in one paragraph.** `DeleteStrategy` is `ArchiveStrategy`'s sibling: an unlocked read for the 404 and the pool, the pool's advisory lock, the strategy's row lock, then a count of every kind of row that references the strategy, and a hard `DELETE` of the row only when every count is zero. The database is the backstop: every reference is a `NO ACTION` foreign key, so a delete that the count wrongly allowed still fails, loudly. A signal that arrives during the delete is serialized by that same foreign key's row lock, and a signal that arrives after it is refused at the webhook with one WARNING. The base design needs **no migration**. One migration (0028) is needed only if the owner answers that enablement events must not block a delete (§ L, Q1).

### A. Findings from the code (verified at HEAD `d162fe6`)

**Every table and column that references a strategy.** "ORM" is the SQLAlchemy model; "migration" is what production actually has. Where they differ, the migration is the truth and the difference matters for tests (finding X2).

| # | Table · column | Foreign key | Nullable | `ON DELETE` | Protected |
| --- | --- | --- | --- | --- | --- |
| R1 | `signals.strategy_id` | **Migration only:** `fk_signals_strategy` (`migrations/versions/0003_strategies_pools.py:93-95`). The ORM column carries no `ForeignKey` (`signals/infrastructure/models.py:29`). | NOT NULL (`0002_signals.py:39`) | none stated: `NO ACTION` | No. Unique `(strategy_id, idempotency_key)` (`0002_signals.py:70-75`) |
| R2 | `reservations.strategy_id` | `fk_reservations_strategy` (`0004_reservations.py:56-58`; ORM `allocation/infrastructure/models.py:36-38`) | NOT NULL (`0004_reservations.py:32`) | `NO ACTION` | No |
| R3 | `ledger_entries.strategy_id` | `fk_ledger_entries_strategy` (`0005_ledger_execution.py:122-124`; ORM `ledger/infrastructure/models.py:39-41`) | NOT NULL (`0005_ledger_execution.py:92`) | `NO ACTION` | **Append-only:** `trg_ledger_no_update_delete` and `trg_ledger_no_truncate` (`0005_ledger_execution.py:158-171`) |
| R4 | `booking_proposals.strategy_id` | **Migration only:** `fk_booking_proposals_strategy` (`0023_booking_proposals.py:182-186`). The ORM column carries no `ForeignKey` (`reconciliation/infrastructure/models.py:129`). | NOT NULL (`0023_booking_proposals.py:139`) | `NO ACTION` | Frozen by repository discipline, no trigger (`0023_booking_proposals.py:6-13`) |
| R5 | `strategy_enablement_events.strategy_id` | **Migration only:** `fk_strategy_enablement_events_strategy` (`0024_strategy_lifecycle.py:171`). The ORM column carries no `ForeignKey` (`strategies/infrastructure/enablement_log.py:37`). | NOT NULL (`0024_strategy_lifecycle.py:161`) | `NO ACTION` | **Append-only:** row trigger `trg_strategy_enablement_events_no_update_delete`, `BEFORE UPDATE OR DELETE` (`0024_strategy_lifecycle.py:177-194`). No `TRUNCATE` guard, on purpose (`0024_strategy_lifecycle.py:41-49`) |

Those five are the only `strategy_id` columns in the schema (a search of every migration finds the name in `0002`, `0004`, `0005`, `0023` and `0024` only). **In production no `strategy_id` column lacks a foreign key.** The dangerous case the task asked about (a column that nothing stops from becoming an orphan) exists only in the ORM-built test schema, for R1, R4 and R5.

**Tables that reach a strategy only through another row.** None of them can exist for a strategy that has no signal and no reservation.

| # | Table · column | Reaches a strategy through | Evidence |
| --- | --- | --- | --- |
| I1 | `execution_attempts.reservation_id`, `.closes_allocation_id` | `reservations.strategy_id`. Exactly one of the two is set. | FKs `0005_ledger_execution.py:79-81`, `0012_closing_execution_attempts.py:69`; CHECK `0012_closing_execution_attempts.py:77-81`. The table has no `strategy_id` (`execution/infrastructure/models.py:60-73`) |
| I2 | `execution_attempts.signal_id` | `signals.strategy_id` | Nullable FK, `0025_signal_outcomes.py:97-107` |
| I3 | `reservations.signal_id` | `signals.strategy_id`. NOT NULL and UNIQUE, so **a reservation cannot exist without a signal** | `0004_reservations.py:33, 59` |
| I4 | `ledger_entries.allocation_id`, `.execution_attempt_id` | reservations, attempts | `0005_ledger_execution.py:125-132` |
| I5 | `booking_proposals.allocation_id`, `.execution_attempt_id` | reservations, attempts | `0023_booking_proposals.py:177-193` |
| I6 | `reconciliation_discrepancies.open_allocation_ids` (`uuid[]`) | reservation ids, **no foreign key**, no strategy id | `0020_reconciliation_discrepancies.py:121-126`; ORM `reconciliation/infrastructure/models.py:57-61` |
| I7 | `reservations.pool_total_at_open` | a column of the reservation row, not a reference | `0026_reservation_pool_total.py:52-55` |
| I8 | `jobs.payload` (JSONB) | **No payload carries a strategy id.** `signal.process` carries `signal_id` (`signals/application/ingest_signal.py:81`); the settle job carries `execution_attempt_id` (`execution/application/place_order.py:207`, `close_position.py:230`); the continuation carries `signal_id` and allocation ids (`signals/application/open_after_close.py:178, 214-216`); the watchdog carries a timestamp (`shared/application/watchdog_handler.py:61`) | `shared/infrastructure/models.py:25` |
| I9 | Performance reporting | No table. The reads take the pool from the strategy row and answer 404 when the row is missing | `performance/infrastructure/performance_router.py:299-306` |

`capital_pools`, `pool_balance_snapshots` and `exchange_credentials` reference no strategy (`accounts/infrastructure/models.py`).

**Other findings.**

| # | Finding | Where | Consequence |
| --- | --- | --- | --- |
| X1 | A strategy's webhook identity IS its primary key: the webhook reads `UUID(alert.signal_type)` as `strategy_id`. The id has no server default and a second registration under it is refused. | `signals/infrastructure/router.py:76-79`; `strategies/infrastructure/models.py:43`; `strategies/application/register_strategy.py:123-129` | A deleted id can be registered again. It inherits nothing only if the delete left no row behind, which is why the check must be exhaustive (§ C). |
| X2 | The integration test database is built from the ORM (`Base.metadata.create_all`), so it has **no** foreign key on R1, R4 and R5 and no append-only trigger. | `tests/pg_schema.py:1-22`; `tests/strategies/infrastructure/conftest.py:97-100` | Every delete test that relies on a foreign key or a trigger must run on a database migrated to `head` (§ J). On the ORM schema those tests would pass or fail for the wrong reason. |
| X3 | The webhook does no strategy lookup. In production the signal `INSERT` itself fails on `fk_signals_strategy` when the id is not registered, and nothing catches it: the request ends as an unhandled 500. | `signals/application/ingest_signal.py:57-86`; `signals/infrastructure/repository.py:45-69`; `signals/infrastructure/router.py:98-101` | Today a mistyped alert id is already a 500 per alert. After a delete, the strategy's leftover alert would be one. Unit 9xa turns it into a refusal with one WARNING (§ E). |
| X4 | The alert bridge forwards every ERROR record to Telegram. An unhandled exception in a request is logged at ERROR with a traceback. Whether the API process's `uvicorn.error` logger is behind the bridge was NOT verified here. | `shared/infrastructure/alert_log_bridge.py:101-114` | At best a leftover alert of a deleted strategy writes a traceback on every bar; at worst it also pages the owner each time. Either way the refusal must be a WARNING with no traceback. |
| X5 | Registering writes no enablement event; the first enable writes the first one. | `strategies/application/register_strategy.py:159-168`; `strategies/infrastructure/router.py:317-319` | A strategy that was never enabled owns only its own row. |
| X6 | `ArchiveStrategy` treats "the row is gone after the lock" as unreachable. | `strategies/application/archive_strategy.py:169-171` (`# pragma: no cover -- strategies are never deleted`) | It becomes reachable: an archive that waits behind a delete must answer 404. The pragma goes and a test covers it. |
| X7 | `ArchiveStrategy` gets its exposure facts through `StrategyExposurePort`, whose adapter composes the provider modules' own repositories. | `strategies/application/ports.py:125-166`; `strategies/infrastructure/exposure_adapter.py:30-85` | The history check reuses that shape (§ B). |
| X8 | `apiFetch` already returns `undefined` for a 204. | `frontend/src/shared/api/client.ts:88-90` | The delete call needs no client change. |
| X9 | `StrategyDetailPage` is a placeholder. | `frontend/src/features/strategies/StrategyDetailPage.tsx:4` | The delete control is built unmounted, and unit 9d mounts it (§ H). |

**Which rows does a never-used strategy actually own?**

- **Never enabled:** exactly one row, its own `strategies` row. The allowed pairs are a column of that row (`0024_strategy_lifecycle.py:128-136`), and so is `archived_at`. Nothing else in the database names it.
- **Enabled and disabled at least once, never signalled:** that row plus one `strategy_enablement_events` row per toggle (X5). Decision 42 does not list this kind of row, the database protects it twice (R5), and what to do with it is the owner's call (§ L, Q1).

`GET /api/strategies/{id}/events` answers `[]` for the first case (`strategies/infrastructure/router.py:354-362`), and both performance routes answer a zero report with empty arrays (§ 14). After a delete all of them answer 404, because each loads the strategy row first.

### B. Components, with hexagonal layer

| Component | Layer | File | Notes |
| --- | --- | --- | --- |
| `StrategyHistory` (six counts, `is_empty()`, `blocking()`) | **application**/strategies | `strategies/application/ports.py` | A frozen dataclass of integers, the sibling of `StrategyExposure`. No `signals`, `allocation`, `execution`, `ledger` or `reconciliation` type appears in it. |
| `StrategyHistoryPort.history(strategy_id) -> StrategyHistory` | **application**/strategies | same file | Consumer-declared. Takes no pool: see § C. |
| `StrategyStillReferenced(constraint)` | **application**/strategies | same file | Raised by the repository adapter when the database refuses the delete. Keeps `IntegrityError` out of the application layer. |
| `StrategyRepositoryPort.delete(strategy_id)` (new method) | **application**/strategies | same file | |
| `DeleteStrategy`, `StrategyHasHistory` | **application**/strategies | `strategies/application/delete_strategy.py` | § D. Reuses `StillEnabled` (`archive_strategy.py`) and `UnknownStrategy` (`update_strategy.py`), as `ArchiveStrategy` already does. |
| `StrategyHistoryAdapter` | **infrastructure**/strategies | `strategies/infrastructure/history_adapter.py` | Implements the port by composing the five provider repositories, the `StrategyExposureAdapter` precedent. |
| `count_for_strategy(strategy_id) -> int` on each provider repository | **infrastructure**/signals, allocation, execution, ledger, reconciliation | the five `infrastructure/repository.py` files (`booking_proposal_repository.py` for reconciliation) | One narrow read each, owned by the module that owns the table. |
| `SqlAlchemyEnablementLog.count_for(strategy_id) -> int` | **infrastructure**/strategies | `strategies/infrastructure/enablement_log.py` | |
| `SqlAlchemyStrategyRepository.delete` | **infrastructure**/strategies | `strategies/infrastructure/repository.py` | One `DELETE` statement, flushed. Translates a foreign-key `IntegrityError` into `StrategyStillReferenced`, reading the constraint NAME (the `reconciliation/infrastructure/booking_writer.py:51` helper pattern), never the message text. |
| `DELETE /strategies/{id}` route, `get_delete_strategy` | **infrastructure**/strategies | `strategies/infrastructure/router.py` | § F. The router already carries `require_admin_token` for every route in it (`router.py:108-112`). |
| `UnknownSignalStrategy` | **application**/signals | `signals/application/ports.py` | Unit 9xa, § E. |
| `SqlAlchemySignalRepository.insert_or_get` (changed), `IngestSignal` (changed), the webhook route (changed) | **infrastructure** and **application**/signals | `signals/infrastructure/repository.py`, `signals/application/ingest_signal.py`, `signals/infrastructure/router.py` | § E. No lookup is added to the ingress path. |
| `useDeleteStrategy`, `DeleteStrategyControl`, `DeleteStrategyDialog` | frontend | `shared/api/strategies.ts`, `features/strategies/` | § H. |

No new domain component: the rule "no history" is a count compared with zero, and it lives on `StrategyHistory`.

### C. The no-history check

**It counts six kinds, not four.** Decision 42 names signals, reservations, execution attempts and ledger entries. The schema has two more direct references, R4 and R5.

| Kind (`history` key) | Counted as | Blocks a delete |
| --- | --- | --- |
| `signals` | rows of `signals` with this `strategy_id` | Yes (decision 42) |
| `reservations` | rows of `reservations` with this `strategy_id` | Yes (decision 42) |
| `execution_attempts` | attempts whose `COALESCE(reservation_id, closes_allocation_id)` is one of the strategy's reservations, or whose `signal_id` is one of its signals | Yes (decision 42) |
| `ledger_entries` | rows of `ledger_entries` with this `strategy_id` | Yes (decision 42, rule 6) |
| `booking_proposals` | rows of `booking_proposals` with this `strategy_id` | Yes (R4; § L, Q2) |
| `enablement_events` | rows of `strategy_enablement_events` with this `strategy_id` | Yes in the base design; § L, Q1 decides whether it stays so |

- **Counts are by strategy id alone, across every capital pool.** A strategy lives in exactly one pool `(exchange, venue, settlement_currency)` and cannot be moved (`strategies/application/update_strategy.py:4-25`), so a row for it in another pool should not exist. If one does, it must still block. A pool-scoped count would hide exactly the row that proves something is wrong.
- **`execution_attempts` and `booking_proposals` are redundant today** (I1, I3 and I5 make them impossible without a reservation), and they are counted anyway. The count is what the operator reads in the refusal, and the redundancy costs two indexed reads on a rare admin action.
- **The count is the readable refusal. The foreign keys are the guarantee.** If the count is ever incomplete, the `DELETE` fails on a `NO ACTION` foreign key instead of orphaning a row (§ D, step 7).

**Exhaustiveness is pinned by a test, not by this table.** One test on a `head`-migrated database reads `pg_constraint` for every foreign key whose target is `strategies`, and `information_schema.columns` for every column named `strategy_id`. It fails when either set differs from the five names of § A, with a message that tells the author to extend `StrategyHistory`. A later migration that adds a reference cannot merge with the check silently out of date.

### D. `DeleteStrategy`: the sequence and the locks

```
 Panel        DeleteStrategy        Repository       PoolLockPort     StrategyHistoryPort
   │ DELETE {id}    │                    │                 │                  │
   ├───────────────►│ 1 get_by_id (NO lock)                │                  │
   │                ├───────────────────►│ none → 404      │                  │
   │                │   pool = the strategy's own (exchange, venue, settlement_currency)
   │                │ 2 acquire(pool)    │                 │                  │
   │                ├─────────────────────────────────────►│ pg_advisory_xact_lock
   │                │ 3 get_by_id_for_update               │                  │
   │                ├───────────────────►│ ROW LOCK, fresh read; gone → 404   │
   │                │ 4 enabled? → 409 STILL_ENABLED       │                  │
   │                │ 5 archived? → see § L, Q3            │                  │
   │                │ 6 history(id)      │                 │                  │
   │                ├────────────────────────────────────────────────────────►│ six counts
   │                │   any count > 0 → 409 HAS_HISTORY    │                  │
   │                │ 7 delete(id)       │                 │                  │
   │                ├───────────────────►│ DELETE; FK refuses → 409 HAS_HISTORY + ERROR
   │                │ 8 commit (both locks released), INFO │                  │
   │◄───────────────┤ 204                │                 │                  │
```

1. **Unlocked read.** It answers the 404 and gives the pool. The pool of a strategy is immutable, so reading it before any lock is safe, exactly as in `ArchiveStrategy` (`archive_strategy.py:143-157`).
2. **The pool's advisory lock, first.** The same key `AllocateCapital` takes, through the existing `PoolLockPort` and `PoolLockAdapter` (`strategies/infrastructure/pool_lock_adapter.py:23-35`). Nothing new is written for it.
3. **The row lock, second,** with `SELECT ... FOR UPDATE` and a fresh read (`repository.py:46-67`). Every decision below comes from this read. A row that disappeared between steps 1 and 3 was deleted by a concurrent request: 404.
4. **Still enabled:** refused in the application, before any write.
5. **Archived:** an owner question (§ L, Q3). The tasks that depend on the answer are marked.
6. **History,** read inside both locks.
7. **The delete.** A foreign-key refusal here means the count missed something. It is translated to `StrategyStillReferenced`, logged at ERROR with the constraint name, and answered as `HAS_HISTORY`. It must never be a 500.
8. **Commit,** then one INFO line.

**Lock order.** Pool advisory lock, then the row lock, as everywhere (CLAUDE.md "Review"). No venue call and no other external call happens at any point. The row lock is held only for steps 3 to 8, which are six indexed counts and one statement. While the use case waits for the advisory lock (step 2) it holds no row lock, so it never makes the webhook wait behind an allocation.

**What each lock is for.**

| Concurrent actor | What serializes it against the delete | Outcome in each order |
| --- | --- | --- |
| **Webhook ingress** (takes no advisory lock, and must not) | The signal `INSERT` takes `FOR KEY SHARE` on the strategy row through `fk_signals_strategy`. That conflicts with the delete's `FOR UPDATE`. | Ingress first: the delete waits at step 3, then counts one signal and is refused. Delete first: the `INSERT` waits on the row, then fails on the foreign key and is refused at the webhook (§ E). |
| **`AllocateCapital`** | The pool advisory lock (the archive precedent, `archive_strategy.py:59-73`). Also, a reservation needs a signal (I3), which already blocks. | Allocation first: the delete waits at step 2, then counts a reservation and is refused. Delete first: cannot happen with a signal present; see the row above. |
| **`UpdateStrategy`** (enable) and **`ReplaceAllowedPairs`** | The strategy row lock (`update_strategy.py:101`, `replace_allowed_pairs.py:98-100`) | Enable first: the delete re-reads `enabled = true` and is refused. Delete first: the update finds no row and answers 404 (`update_strategy.py:102-105`, `replace_allowed_pairs.py:127-128`). |
| **`ArchiveStrategy`** | Both locks, in the same order | Archive first: § L, Q3. Delete first: the archive finds no row after its lock and answers 404 (X6). |
| **The worker's `signal.process`** | Nothing is needed. A job names a signal (I8), and a signal blocks the delete. | No pending job can name a deleted strategy. |

**The window the task asked about, closed.** "The check says no history, a signal is ingested, the row is deleted" cannot happen:

```
 Ingress first                                 Delete first
 ─────────────                                 ────────────
 INSERT signals (KEY SHARE on the row)         FOR UPDATE on the row
                 DELETE: FOR UPDATE waits       counts: all zero
 COMMIT                                                        INSERT signals: waits on the row
                 lock granted                  DELETE row, COMMIT
                 counts: signals = 1                           FK check fails: no such strategy
                 409 HAS_HISTORY                               422 UNKNOWN_STRATEGY, one WARNING
 the signal is processed normally              nothing persisted, no job enqueued
```

Under `READ COMMITTED` each count is a new statement, so it sees what was committed while the delete waited. A signal is therefore either in the strategy's history before the delete decides, or refused after the row is gone. It is never attributed to another strategy, because the only key it carries is the id that no longer exists.

**Why the delete takes the advisory lock when the foreign key already protects it.** Three reasons, in order of weight: the project rule is one lock order everywhere; the reservation and attempt counts are then read under the same lock `AllocateCapital` writes them under, instead of resting only on the argument "a reservation needs a signal"; and the two serializers are independent, so a future change to either does not silently remove the protection. The cost is a few milliseconds of one pool's allocation lock on a rare admin action.

**Rejected:**
- *Taking only the row lock.* Correct today (I3), but it breaks the lock-order rule and rests the whole guarantee on one transitive argument.
- *A strategy lookup or lock at ingress.* Rule 3: ingress validates, persists and returns. The foreign key already does the lookup inside the `INSERT`, at no extra round trip.
- *Catching `IntegrityError` in the use case.* The application layer imports no SQLAlchemy type; the repository adapter translates it.

### E. A signal for a strategy that is not registered (unit 9xa)

This is finding X3, and it is delivered **before** the delete endpoint, as its own PR. It is a defect today, and delete would make it routine.

- `SqlAlchemySignalRepository.insert_or_get` catches the `IntegrityError` of its `INSERT`. When the violated constraint is named `fk_signals_strategy` it raises `UnknownSignalStrategy(strategy_id)`. Any other integrity error is re-raised unchanged.
- `IngestSignal` logs **one WARNING** and re-raises: the strategy id, the symbol as the alert spelled it, and "remove its TradingView alert or register the strategy". No payload, no secret (the secret is a query parameter and never reaches the use case).
- The route rolls the session back and answers **422** `{"detail": {"error": "UNKNOWN_STRATEGY", "message": ...}}`. Nothing is persisted and no job is enqueued.

| Choice | Why |
| --- | --- |
| 422, not 404 or 200 | The route already answers 422 for an alert it cannot accept (`signals/infrastructure/router.py:73-79, 100-101`). A 404 on this path reads as "the proxy route is gone". A 200 would claim a signal was accepted. TradingView ignores the status either way. |
| WARNING, not ERROR | It is a configuration state the owner fixes in TradingView, the same class as the archived-strategy refusal (`process_signal.py:885-892`). An ERROR is what the alert bridge forwards (X4), and this would fire on every bar. |
| No lookup added | The "no ingress lookup" requirement of strategy-lifecycle stands. The check is the foreign key the `INSERT` already carries. |
| Constraint identified by name | The project's rule since `booking_writer.py`; a message-text match breaks on a PostgreSQL locale. |

**What a signal after the delete does, in full.** It reaches the webhook, the `INSERT` fails on the foreign key, the request ends 422 with one WARNING naming the id, and that is all. No signal row, no job, no worker involvement, no attribution to any strategy. A replay of the same alert does the same thing again: the refusal is idempotent because nothing is ever stored.

**The worker.** `SignalContextAdapter` and `StrategyPolicyAdapter` raise `UnknownStrategyError` for a signal whose strategy is missing (`signals/infrastructure/signal_context.py:43`, `strategies/application/policy_adapter.py:26-27`). With the foreign key in place that state is unreachable, and this design does not change those lines: if it ever happened, the job would fail, retry and end in the exhausted-job path that already records it.

### F. The endpoint

`DELETE /api/strategies/{strategy_id}`, in the existing strategies router, behind `require_admin_token` like every route there.

| Case | Status | Body | Log |
| --- | --- | --- | --- |
| Deleted | **204** | none | INFO `strategy deleted: id=… name=… pool=…/…/… archived=…` |
| Unknown id, or a repeated delete | 404 | `{"detail": "no strategy registered under id …"}` (the existing shape) | WARNING `strategy delete refused, unknown id: …` |
| Still enabled | 409 | `{"detail": {"error": "STILL_ENABLED", "message"}}` (the archive route's code, `router.py:454-457`) | WARNING naming id and name |
| Any history | 409 | `{"detail": {"error": "HAS_HISTORY", "message", "history": {"signals": n, "reservations": n, "execution_attempts": n, "ledger_entries": n, "booking_proposals": n, "enablement_events": n}}}` | WARNING naming id, name and the six counts |
| The database refused the delete although every count was zero | 409 | `HAS_HISTORY`, the same shape, with the counts as read; `message` names the constraint | **ERROR** naming id and constraint: the check is incomplete, and that is a defect to fix |
| Archived | § L, Q3 | | |

- **204, not 200.** There is no strategy left to describe. The panel needs only the outcome.
- **`history` always carries all six keys,** as JSON integers. They are counts, not money or quantities, so the string rule of the cross-cutting rules does not apply (`trade_count` is an integer too). A fixed shape lets the panel render without guessing which key is absent.
- **`STILL_ENABLED` is checked first** and answers alone. A strategy must be disabled before anything else matters, and the panel already knows `enabled` and disables the control (§ H).
- **Idempotency.** A repeated `DELETE` answers 404. It is not a 204: the precedent for an id that is not there is 404 on every route of this router, and a 204 for an id that never existed would hide a wrong id. The panel treats a 404 on delete as "already gone" (§ H).
- **The refusal says why, always.** No refusal of this route is a bare status.
- **Wiring.** `get_delete_strategy(session)` builds the use case from the session, as `get_register_strategy` does (`router.py:262-272`), so router tests override one dependency. On any refusal the route calls `session.rollback()`, which releases both locks at once and clears the aborted transaction of the backstop case.

### G. Hard delete, and no migration

**Decision: a hard `DELETE` of the `strategies` row.**

| | Hard delete (chosen) | Tombstone (`deleted_at`) |
| --- | --- | --- |
| What remains | Nothing | The row, hidden |
| The id and the name | Free again. The owner can register a real strategy under a test's name. | Kept forever: `name` is UNIQUE and the id is refused as already registered |
| Readers | Unchanged | Every list, detail, policy and performance read must filter it, and one that forgets shows a deleted strategy |
| Migration | None | A column and a CHECK, rehearsed |
| Difference from archive | Real | Almost none: a second, stricter archive. It does not do what decision 42 asks for. |
| Audit | One INFO line (§ I) | The row |

- **Rule 6 (append-only ledger) holds.** A delete is refused when the strategy has one ledger entry, and the database refuses it independently: `fk_ledger_entries_strategy` is `NO ACTION`, and the ledger triggers forbid removing the entry. No ledger row is ever touched.
- **Rule 2 (idempotency keys) holds.** A delete is refused when the strategy has one signal, so no idempotency key is ever removed. After the delete no signal can be stored under the id until it is registered again, and a strategy registered again starts with no signal, so there is no key to collide with.
- **Nothing is inherited on re-registration.** After a delete, no row in any table carries the id (§ C plus the foreign keys). A strategy registered again under it is new in every respect.

**Dependent rows.** In the base design nothing is deleted with the strategy, because a strategy with any dependent row is refused. The allowed pairs and `archived_at` go with the row they are columns of.

**Migration: none.** No table, column, constraint or trigger changes. This holds as long as enablement events block a delete.

**If the owner answers Q1 with "events must not block": migration 0028.** The events cannot be removed by the application at all today: the foreign key refuses the strategy delete while they exist, and the trigger refuses deleting them first (R5).

- **Mechanism: `ON DELETE CASCADE`, not an explicit delete.** An explicit delete in the use case needs a way around the append-only trigger, and any such switch can be flipped by a future bug. With a cascade the rule stays structural.
- **Upgrade.** (1) `CREATE OR REPLACE FUNCTION fn_strategy_enablement_events_append_only()`: `UPDATE` always raises, as now; `DELETE` raises unless the parent strategy row no longer exists (`NOT EXISTS (SELECT 1 FROM strategies WHERE id = OLD.strategy_id)`). (2) Drop `fk_strategy_enablement_events_strategy` and recreate it with `ON DELETE CASCADE`.
- **Why that condition.** An event can then be deleted only as part of its strategy's deletion. A direct `DELETE` of an event whose strategy exists is still refused, and an event without a strategy cannot exist. The strategy's own deletion is still refused by the other four `NO ACTION` foreign keys.
- **Downgrade.** Restore the function body of 0024 and the foreign key without the cascade. It discards no data, so it has no refusal clause; it logs one WARNING that strategies deleted meanwhile are not restored.
- **Assumption to prove before anything else is written (task 9xf.1).** Inside the cascade, the trigger's `SELECT` must no longer see the parent row. PostgreSQL runs the cascade as a later command of the same transaction, so it should not. If the RED test shows otherwise, the fallback condition is `pg_trigger_depth() > 1`, and the design is amended before the GREEN. **Proven 2026-10-03 (task 9xf.1, commit c36601c): the `NOT EXISTS` condition holds on PostgreSQL 17, and it is what migration 0028 ships. The fallback is not needed.**
- **Rehearsal.** As every migration: locally on a `head` database (up, down, the trigger's three behaviours), then on the VPS against a throwaway restore of a fresh backup (tasks.md "Migration rehearsal").
- **What is lost.** The enable and disable times of a strategy that never received a signal. Nothing about money. The delete's INFO line records the number of events, the first enable time and the cumulative uptime, so the fact survives in the log.

### H. Frontend

**Where the control sits.** At the bottom of the strategy detail page, in a separated "Delete strategy" block below the archive control: a short text and one button. It is a different act from archive and must not sit beside the enable toggle.

**Ordering with unit 9d.** The detail page is a placeholder (X9) and unit 9d (PR 12b) builds it. The delete control does not wait for it:
- PR 12x-5 builds `useDeleteStrategy`, `DeleteStrategyControl` and `DeleteStrategyDialog`, tested on their own, **mounted nowhere** (the `PairSelector` precedent, PR 12v-4).
- Unit 9d gains task **9d.6**: mount `<DeleteStrategyControl strategy={…} />` at the bottom of `StrategyDetailPage`.
- If unit 9d merges first, task 9d.6 moves into PR 12x-5. It is one edit, done once, by whichever PR is second.

| Component | Kind | Props | Does |
| --- | --- | --- | --- |
| `DeleteStrategyControl` | container | `strategy: Strategy` | The block, the button, the dialog's open state, the mutation, the navigation |
| `DeleteStrategyDialog` | presentational | `name`, `pending`, `error`, `onConfirm`, `onCancel` | The confirmation and the refusal |

**The button.** Disabled while `strategy.enabled` is true, with the hint "Disable the strategy first". The server still decides.

**The confirmation.** A native `<dialog>`, like the existing dialogs. It says what will happen and that it cannot be undone. The owner must **type the strategy's name** into a labelled field; the destructive button stays disabled until the typed text equals the name exactly. Enter in the field submits only when it matches. Cancel and Escape close it and send nothing. Typing the name is chosen over a second "Are you sure" button because the action is irreversible and the detail page of one strategy looks like the detail page of another.

**The refusal, rendered inside the dialog** (chosen by `error.code`, then by status):

| `code` (fallback) | i18n key | Text (EN) |
| --- | --- | --- |
| `STILL_ENABLED` | `strategies.delete.errors.stillEnabled` | "This strategy is still enabled. Disable it first." |
| `HAS_HISTORY` | `strategies.delete.errors.hasHistory` | "This strategy has history, so it cannot be deleted. Archive it instead." followed by one line per non-zero kind of `fields.history` |
| 404 | — | Not an error: the strategy is already gone. Same path as success. |
| anything else | `strategies.delete.errors.generic` | "The strategy was not deleted. Try again." |

Kind lines, one key each with a count: `strategies.delete.history.signals` ("{{count}} signal(s)"), `.reservations`, `.executionAttempts`, `.ledgerEntries`, `.bookingProposals`, `.enablementEvents`. A kind with count zero is not shown. A `history` object that is missing or malformed shows the main sentence alone, never a crash.

**After a successful delete** (204, or 404):
1. `queryClient.removeQueries({ queryKey: ['strategy', id] })`. Removed, not invalidated: an invalidation would refetch a detail that now answers 404 and flash an error. The prefix covers `['strategy', id, 'events']` and the strategy's performance queries of § 15.
2. `queryClient.invalidateQueries({ queryKey: ['strategies'] })`, which covers both `includeArchived` variants (`shared/api/strategies.ts:80-83`).
3. Navigate to `/strategies` with `replace`, so Back does not return to a page that no longer exists.

**i18n.** Every string in EN and ES under `strategies.delete.*`: `title`, `description`, `button`, `disabledHint`, `confirmTitle`, `confirmBody` (`{{name}}`), `typeName`, `confirm`, `cancel`, `pending`, the three `errors.*` and the six `history.*`. Tailwind palette tokens only; the destructive button uses the palette's existing loss or danger token, never a hex value.

### I. Logging (what fails here without a log line?)

| Event | Level | Content |
| --- | --- | --- |
| A strategy was deleted | **INFO** | id, name, pool `(exchange/venue/settlement_currency)`, whether it was archived. It is irreversible, and this line is the only record that the strategy existed. |
| Delete refused: unknown id | WARNING | the id |
| Delete refused: still enabled | WARNING | id, name |
| Delete refused: history | WARNING | id, name, the six counts |
| The database refused a delete the count allowed | **ERROR** | id, name, the constraint name. ERROR on purpose, so it reaches the owner wherever the alert bridge is installed (X4): the no-history check has a hole. |
| An alert for a strategy that is not registered (§ E) | WARNING | strategy id, the alert's symbol, the instruction |

No line carries a token, a credential, a DSN or the webhook secret. The name is logged with `%r`, as the archive refusals already do.

| Failure | Guard |
| --- | --- |
| A new table references a strategy and the check does not count it | The foreign key refuses the delete; one ERROR names the constraint; the exhaustiveness test fails in CI before that |
| The count runs on a schema without the foreign keys and "proves" a delete is safe | Every such test runs on a `head` database (§ J); stated per task |
| A signal arrives during the delete and is orphaned | The row lock and `fk_signals_strategy` (§ D); proven with a lock-hold harness |
| The leftover alert of a deleted strategy is a 500 with a traceback on every bar | Unit 9xa: 422 and one WARNING, delivered before the endpoint |
| A deleted strategy leaves no trace | The INFO line |
| A delete is refused and the operator sees only "failed" | Every 409 carries a code and, for history, the counts; the dialog renders them |
| An archive that waited behind a delete crashes on a missing row | X6: it answers 404, covered by a test |
| The panel refetches a deleted strategy and shows an error | `removeQueries`, then navigate |
| A double click sends two deletes | The button is disabled while pending; a second request answers 404, which the panel reads as done |

**Threat matrix.** The skill's matrix stays N/A (no shell, subprocess or VCS automation). Two project rows:

| Threat | Safe behaviour | RED test |
| --- | --- | --- |
| The new `/api` route ships without auth | Auth is a router dependency | The existing parametrized walk over `app.routes` (`tests/strategies/infrastructure/test_router_auth.py`) covers a `DELETE` |
| A destructive request is forged from another origin | The bearer token travels in a header set by script, never in a cookie, so a cross-site form cannot carry it | N/A, unchanged from every other admin write |

### J. Testing strategy

| Layer | What | How |
| --- | --- | --- |
| Unit, application | `DeleteStrategy`: order of steps, each refusal and its log line, the backstop, the lock order | Fakes and one shared event log, as `test_replace_allowed_pairs.py` |
| Integration, ORM schema | Each provider `count_for_strategy`; the adapter's six counts | Real PostgreSQL through the modules' own conftests |
| Integration, **`head` schema** | The exhaustiveness guard; the backstop; ingress refusal; every concurrency property | A database migrated with `alembic upgrade head` (below) |
| Router | Status and body of each case; auth | `httpx.AsyncClient` over ASGI with `dependency_overrides` |
| Migration (only if 9xf) | Trigger behaviour, cascade, downgrade | The `tests/migrations/` pattern |
| Frontend | The hook's request and cache effects; the dialog's confirmation, refusals, EN and ES | Vitest, `vi.stubGlobal("fetch")` |

**Rules that bind the task breakdown.**

- **Strict TDD.** Each RED fails on an ASSERTION. A new port, class or route is first added as a stub that compiles and answers WRONGLY (a history that is always empty, a delete that always succeeds, a route that always answers 204), in the same commit as the RED test. A test that passes at once is proven by the mutation its task names.
- **The `head` schema is mandatory for anything that depends on a foreign key or a trigger** (X2). A shared helper, `tests/pg_head_schema.py`, creates one throwaway database per test module and runs `alembic upgrade head` on it, following `tests/migrations/test_0024_strategy_lifecycle.py:140-153`. Each such test file says in its docstring why the ORM schema would not do.
- **The concurrency properties are proven on real PostgreSQL with a lock-hold harness, never a `sleep(0)` barrier.** The precedents are `tests/strategies/application/test_archive_vs_allocate_concurrency.py` (pausing commit, pausing pool lock) and `tests/strategies/infrastructure/test_replace_allowed_pairs_catalogue_integration.py` (polling `pg_locks`).
  - *The delete waits for a signal being ingested:* an ingest is paused before its commit, after its `INSERT`. The delete is started. The test asserts `not task.done()` AND polls `pg_locks` until the delete shows as waiting on the strategy row. The ingest commits. The delete is refused with `signals = 1`, and the strategy and the signal both exist. Non-vacuity: with `fk_signals_strategy` dropped inside the test database, the delete does not wait and the test goes red.
  - *A signal waits for a delete in flight:* the delete is paused before its commit, after its `DELETE`. An ingest is started. `not task.done()`. The delete commits. The ingest raises `UnknownSignalStrategy`; `signals` and `jobs` hold no row for it.
  - *The delete waits for an allocation:* an allocation is paused holding the pool advisory lock. The delete is started. `not task.done()`, and `pg_locks` shows it waiting on an `advisory` lock, not on a row. Mutation: taking the row lock before the advisory lock reds it (the archive deadlock test's method, `archive_strategy.py:36-40`).
  - *The delete waits for an enable in flight:* an `UpdateStrategy` enabling the strategy is paused before commit. The delete waits, then is refused `StillEnabled`.
- **Symbol spelling.** A test that crosses a module boundary on a symbol uses a different spelling on each side: the alert sends `STXUSDT.P`, a seeded reservation or attempt on the venue side is `STXUSDT`, and no assertion depends on the two matching textually. The counts key on the strategy id, and one test proves that a signal spelled `STXUSDT.P` blocks the delete of a strategy whose allowed pairs hold `STXUSDT`.
- **Gate after every unit.** Backend: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`. Frontend: `npm run lint` and `npm test`.

### K. Impact on `DRY_RUN`, idempotency and capital-pool isolation

| Rule | Impact |
| --- | --- |
| **`DRY_RUN` (rule 1)** | The delete behaves the same in both modes: it reads and writes the local database only, contacts no venue and needs no credential. A strategy that acted only under `DRY_RUN` still has signals and rehearsal fills, and they block the delete like any other history. No test needs a credential or the network. |
| **Idempotency (rule 2)** | No signal and no idempotency key is ever deleted. A signal for an unregistered id is refused before it is stored, so a replay cannot double anything. A strategy registered again under a deleted id has no signal to collide with. |
| **Webhook (rule 3)** | The webhook still only validates, persists and returns. No lookup and no lock is added. Its one new branch is an early refusal, faster than the success path. While a delete holds the row lock the `INSERT` waits for it, for the few milliseconds of six counts and one statement. |
| **Allocation transaction (rule 4)** | Unchanged. The delete takes the strategy's own pool's advisory lock, `(exchange, venue, settlement_currency)`, in the standard order, and reads reservations under it. It writes no reservation and reads no balance. |
| **Capital-pool isolation (rule 5)** | The delete locks exactly one pool, the strategy's own. It touches no pool row, no balance snapshot and no other pool's lock. The history counts are deliberately not pool-scoped (§ C), and no count is a sum of money. |
| **Ledger (rule 6)** | No ledger row is read for anything but a count, and none is written, updated or removed. A strategy with a ledger entry cannot be deleted, by the check and by the database. |
| **PnL (rule 7)** | Unaffected. A deleted strategy had no fill, so no figure of any pool changes. |
| **Credentials (rule 8)** | Unaffected. |
| **Existing data** | Nothing changes until someone calls the endpoint. The two test strategies stay until the owner deletes them. |

### L. Delivery, forecasts and open questions

**The PR split.** One PR would be about 2,000 to 2,950 authored lines, five to seven times the review budget, so it is five sequential PRs to `main`, plus one conditional. None is stacked: each branch is cut from `main` after the previous one merged and deployed.

```
 12x-1 ingress refusal ─► 12x-2 history read ─► 12x-3 DeleteStrategy ─► 12x-4 endpoint ─► 12x-5 panel control
                                                        │
                                                        └─► 12x-6 migration 0028  (only if Q1 = "events do not block")
```

| PR | Unit | Contents | Forecast | Deploy | Rollback boundary |
| --- | --- | --- | --- | --- | --- |
| **12x-1** | 9xa | The webhook refuses an alert whose strategy is not registered: 422, one WARNING; `tests/pg_head_schema.py` | 300–450 | Pull, restart the API | One caught error and its mapping; revert restores the 500 |
| **12x-2** | 9xb | `StrategyHistory`, `StrategyHistoryPort`, five provider counts, `count_for`, `StrategyHistoryAdapter`, the exhaustiveness guard | 450–650 | Pull, restart both (the worker imports the repositories) | Read methods nothing calls |
| **12x-3** | 9xc | `DeleteStrategy`, `repository.delete`, `StrategyStillReferenced`, the four lock-hold tests, the archive 404 | 550–800 | Pull, restart the API | A use case nothing routes to |
| **12x-4** | 9xd | `DELETE /api/strategies/{id}`, the HTTP mapping, router tests | 300–450 | Pull, restart the API | One route; revert answers 405 |
| **12x-5** | 9xe | `useDeleteStrategy`, `DeleteStrategyControl`, `DeleteStrategyDialog`, i18n | 400–600 | Pull, no restart | New files; nothing mounts them until 9d.6 |
| **12x-6** | 9xf | Migration 0028, the events kind stops blocking, the INFO line gains the uptime facts | 400–600 | Rehearsal, pull, migrate, restart both | The migration's downgrade; the use case change reverts alone |

Total 2,000 to 2,950 authored lines without 12x-6, 2,400 to 3,550 with it.

- **Why 12x-1 is first and alone.** It changes the webhook, the one path that must not regress, and it is correct and useful with no delete at all. It must be live before a strategy can be deleted.
- **After 12x-4 the feature is usable** through the API (`curl -X DELETE`), which is enough for the owner's two test strategies. The panel control follows.
- `Decision needed before apply: No` (the three questions below block only the tasks named with each) · `Chained PRs recommended: Yes` · `400-line budget risk: High`.

**Design decisions made here** (not owner decisions; each has its reason above):

| # | Decision | Section |
| --- | --- | --- |
| D1 | Hard delete of the row; no tombstone | G |
| D2 | No migration in the base design; 0028 (cascade plus a narrowed trigger) only under Q1 | G |
| D3 | `StrategyHistoryPort` in `strategies`, its adapter composing the provider repositories; counts by strategy id across every pool | B, C |
| D4 | Six kinds are counted; `execution_attempts` and `booking_proposals` although redundant today | C |
| D5 | The exhaustiveness of the check is pinned by a test over `pg_constraint` on a `head` database | C |
| D6 | Lock order: unlocked read, pool advisory lock, row lock, counts, delete | D |
| D7 | The signal race is closed by the row lock and `fk_signals_strategy`; ingress gains no lookup and no lock | D |
| D8 | A foreign-key refusal of the delete is a 409 `HAS_HISTORY` and one ERROR, never a 500 | D, F |
| D9 | An alert for an unregistered strategy is a 422 `UNKNOWN_STRATEGY` and one WARNING, delivered first | E |
| D10 | 204 on success; a repeated delete is a 404 | F |
| D11 | `STILL_ENABLED` is checked before history; `history` always carries all six counts | F |
| D12 | The confirmation requires typing the strategy's name | H |
| D13 | The control is built unmounted; unit 9d mounts it (task 9d.6) | H |
| D14 | After a delete: `removeQueries(['strategy', id])`, invalidate `['strategies']`, navigate with `replace` | H |
| D15 | Every FK- or trigger-dependent test runs on a `head` database | J |
| D16 | Five PRs, plus one conditional on Q1 | L |

**Open questions for the owner.** None blocks 12x-1 or 12x-2.

- **Q1. Do enablement events count as history?** A test strategy that was switched on and off has them; decision 42's list does not mention them.
  - *If they count (the base design, no migration):* a strategy that was ever enabled can only be archived. The owner's test strategies are deletable only if they were never enabled.
  - *If they do not count:* they must be deleted with the strategy, which needs migration 0028 (§ G) and its rehearsal. What is lost is that strategy's enable and disable times; the delete's log line keeps the count, the first enable time and the uptime.
  - **Recommended: they do not count.** That is the literal reading of decision 42, and its motive (test strategies) is exactly the case of a strategy someone switched on to look at it. The events of a strategy that never received a signal record nothing about money.
  - Until answered, the fail-closed behaviour ships: events block. It is the only behaviour possible without a migration, so nothing built before the answer is thrown away.
  - **Blocks:** unit 9xf (PR 12x-6) only.
- **Q2. A fifth kind decision 42 does not list: booking proposals.** `booking_proposals.strategy_id` is a mandatory foreign key (R4). A proposal is the record of a venue close shown to the owner for approval.
  - **Recommended: it blocks, like the other four.** There is no real alternative: a proposal cannot exist without a reservation, which already blocks, and removing one would erase the record of a human decision.
  - **Blocks:** nothing. The design counts it; this is asked so the owner knows the list is six, not four.
- **Q3. May an archived strategy with no history be deleted?**
  - *Yes:* a test strategy the owner already archived can still be removed, and it also frees its name and id. Archive stays irreversible: a delete is not an un-archive.
  - *No:* the delete answers 409 `STRATEGY_ARCHIVED`, and an archived test strategy stays in the archive for good.
  - **Recommended: yes.** An archived strategy is disabled by construction (`ck_strategies_archived_requires_disabled`), and without history there is nothing the archive preserves. Refusing would defeat decision 42 for any strategy archived before this feature existed.
  - **Blocks:** task 9xc.6 (use case), the archived case of 9xd.1 (router) and of 9xe.3 (control). Everything else in those units proceeds.

## Addendum: a strategy's operations, listed and opened one by one (decision 43) - 2026-10-04

Unit 9p, tasks 9p.4 (backend) and 9p.5 (frontend). HEAD `9c8fc6d`. Decision 43 with its two answers of 2026-10-03, and the paging and LONG/SHORT answers of decision 44, are binding and are not reopened here. This addendum settles what they left to the design: what an operation is in terms of the tables that exist, how each new figure is derived, how a rehearsal operation is recognised, served and kept out of every total, the response shape, the detail view, and the delivery. It extends the trades row of § 14 and the "As built (PR 6c)" notes of § 11. It adds one read-only endpoint, the fills of one operation, changes no other, and needs **no migration**.

> **Revised 2026-10-04.** The owner answered the three questions of § L the same day (decision 43's lines of 2026-10-04, and decision 45). The answers are folded into §§ C to L below. Nothing in this addendum is open.

**The answer in one paragraph.** An operation is one allocation: one row of `reservations` and the ledger rows that carry its id. The grouped aggregate that every performance read already makes holds, per side, the summed quantity, notional and fee, so entry price, exit price, size and fees are derived from it in the domain with no new statement. The source stops discarding rehearsal fills and returns them as a second, separate set of groups. Only the trades list reads that set, and only when the request asks with `include_rehearsal=true`; every total keeps reading the first set, so no figure of any report changes. A rehearsal operation is an allocation every one of whose fills carries the `fake-fill-` prefix. It is served in the same list and the same keyset order, with `rehearsal: true`. The row carries every figure, so the detail view is a dialog that opens with no request; it then reads the operation's individual fills from one new endpoint, in one indexed statement. The code also shows something decision 43 could not know: the simulated exchange fills every order at a fixed price of 1 with no fee, so today a rehearsal operation reads entry 1, exit 1 and PnL 0 (finding T9). The owner answered that such a row shows its stored numbers and says how it was filled, and that the simulated exchange will fill at the alert's price from decision 45 on. So a dry-run row also says how its opening fill was priced, derived from stored data alone: the fill's price is compared with the price of the alert that ordered it, which the `signals` table holds (§ C).

### A. What an operation is (findings from the code, verified at HEAD `9c8fc6d`)

| # | Finding | Where | Consequence |
| --- | --- | --- | --- |
| T1 | A trade is derived per `allocation_id`, never per symbol. An allocation IS its reservation: the source joins `ledger_entries.allocation_id` to `reservations.id`. | `performance/domain/derive_trade.py:141-168`; `performance/infrastructure/allocation_fills_source.py:71` | An operation is one `reservations` row plus the ledger rows that name it. No other table is needed to list it. |
| T2 | One opening order per allocation: `execution_attempts.reservation_id` is UNIQUE. Closing orders name the allocation in `closes_allocation_id`; several may exist over time, one live at most. | `execution/infrastructure/models.py:33-65` | The opening side is filled by one order (several fills possible). The closing side may be filled by several orders. |
| T3 | A close is always sized at the allocation's whole net base (`base_size = abs(net)`). The system never asks for a partial close. | `execution/application/close_position.py:142-152` | A partial close exists only as a venue's partial fill, a close that left dust, or a booked venue close. In each case the allocation is OPEN until its net is exactly zero. |
| T4 | The read does not join `execution_attempts`. LONG or SHORT is the side of the allocation's earliest fill; a tie goes to BUY. | `derive_trade.py:72-83` | "Opening fills" are the fills on that side, "closing fills" the fills on the other. One rule decides direction, entry and exit together. |
| T5 | A ledger row stores `quantity`, `price`, `fee`, `fee_currency`, `notional` (written as `quantity * price` by both writers) and `usd_rate_at_fill`. One row per venue fill. | `ledger/infrastructure/models.py:53-61`; `execution/application/settle_execution.py:220-240`; `reconciliation/application/approve_booking.py:314-335` | Every figure decision 43 names is in the ledger already. Decision 43's "no migration" holds. |
| T6 | `quantity > 0`, `price > 0`, `fee >= 0` and `notional > 0` are CHECK constraints of migration 0005. The ORM model declares none of them. | `migrations/versions/0005_ledger_execution.py:114-118`; `ledger/infrastructure/models.py:19-64` | In production a null or non-positive price cannot be stored. A test that relies on that must run on a `head` schema (§ H). |
| T7 | The aggregate already returns, per `(allocation, strategy, side, fee currency)`: `sum(quantity)`, `sum(notional)`, `sum(fee)`, `min` and `max(filled_at)`. | `allocation_fills_source.py:57-85` | Entry price, exit price, size and fees need no new column and no new statement. |
| T8 | Rehearsal fills are dropped in SQL (`~is_rehearsal`) and counted by a second statement. Nothing downstream ever sees one. | `allocation_fills_source.py:53-55, 72, 120-125` | To list them the source must return them. § C says how, without letting one reach a total. |
| T9 | **The simulated exchange fills every order at a fixed price of 1, with a fee of 0 in `USDT`.** Production builds it with that default. The SIZE is realistic (`granted * 1 / alert price`), the price is not. | `execution/infrastructure/fake_exchange.py:62, 67, 143-154`; `main.py:853-854`; `execution/domain/futures_order.py:92-111` | A rehearsal operation reads entry 1, exit 1, fees 0 and PnL exactly 0. Listing it shows that the strategy acted, when and on which pair. It says nothing about price or result (§ C; decision 45). |
| T10 | An allocation cannot normally hold fills of both origins: decision 28's guard refuses a start on a mismatch, and approving a booked close is refused under `DRY_RUN`. The guard still names the leftover case, `Origin.MIXED`. | `execution/domain/mode_origin.py:29-32, 153-189`; `reconciliation/infrastructure/router.py:421-430` | A mixed allocation is a data fault from before PR 6d or from a manual act. The design must say what it does (§ C), not assume it away. |
| T11 | `AllocateCapital` has no `DRY_RUN` branch (no occurrence of `dry_run` in `allocation/`). | `allocation/` | A rehearsal allocation records `pool_total_at_open` like a live one, from migration 0026 on. Production's two rehearsal round trips predate it and have none (tasks.md delivery log, PR 6a and PR 6b). |
| T12 | The panel's shape check reads nine named fields by type and ignores any other key. It sends `limit` and the cursor, nothing else. | `frontend/src/shared/api/performance.ts:107-120, 144-161` | New fields on a row do not break a bundle that predates them (§ D). |
| T13 | The trades table sits in the left column of a `minmax(0,1fr) 25rem` grid. With the 13rem side rail and `lg:px-9`, that column is about 724 px wide at a 1440 px viewport and about 308 px at 1024 px. | `frontend/src/features/strategies/StrategyDetailPage.tsx:67-72`; `shared/layout/SideNav.tsx:14`; `shared/layout/AppShell.tsx:41-42` | Eleven columns do not fit there at any width. § F moves the table. |
| T14 | The panel is not served in production (`PANEL_DIST_DIR` is unset); the owner reviews it locally, usually with `vite.fixture.config.ts`, a local unstaged file that fakes the reports and the trades. | tasks.md delivery log ("Production now", PR 12d) | There is no deployed bundle to break today. The compatibility rules of § D still bind `main` and the day the panel is served. |
| T15 | The alert's price is stored on the signal (`signals.price`, NOT NULL), and it is the price the opening order is built with. A reservation names its signal (`reservations.signal_id`, NOT NULL and UNIQUE). | `signals/infrastructure/models.py:42`; `signals/infrastructure/signal_context.py:53`; `signals/application/process_signal.py:642`; `execution/application/place_order.py:149-155`; `allocation/infrastructure/models.py:39-40` | The price an opening fill has when it is "filled at the alert's price" is already in the database and is reachable from the allocation. A fixed-price row can be told from an alert-priced one without a new column (§ C). |
| T16 | A closing order is built without a price (`CloseOrderSpec` carries the client order id, the symbol, the side and the base size). A closing fill reaches its alert only through `execution_attempts.signal_id`, which is NULL on every close written before PR 5c and on a close no signal asked for. | `execution/application/ports.py:124-129`; `execution/application/close_position.py:159-165, 220-224`; `execution/infrastructure/models.py:66-73` | The EXIT of an operation cannot be compared with its alert for every row. § C tests the opening side and says why that is enough. |
| T17 | `ix_ledger_allocation` (`ledger_entries.allocation_id`) is created by migration 0012. The ORM model declares no index. | `migrations/versions/0012_closing_execution_attempts.py:61, 82`; `ledger/infrastructure/models.py` | The fills read of § D is one indexed statement in production. A test that pins the index must run on a `head` schema (§ H). |

**Definition.** An **operation** is one allocation of the strategy: the `reservations` row whose `id` is the allocation id, and every `ledger_entries` row with that `allocation_id`. Its **opening fills** are its fills on the side of its earliest fill (T4); its **closing fills** are its fills on the other side. It is **closed** when its net base quantity is exactly zero under the base-fee rule with at least one fill on each side, which is `derive_trade`'s existing test, unchanged (§ 11, "As built (PR 6b)"). The list is the list of closed operations.

| Case | What the tables hold | What the list does |
| --- | --- | --- |
| Several fills on one side | Several ledger rows, one per venue fill | One operation. Each price is an average over that side (§ B). |
| A close that filled in part, or left dust | Net base is not zero | Not in the list: the operation is open. It appears when a later close brings the net to exactly zero, with every closing fill averaged into the exit and `closed_at` at the last fill. Dust that no order can close never appears; `ClosePosition` already logs that ERROR. |
| A close retried after a failure, or a booked venue close | Closing fills from more than one attempt, possibly under another spelling of the symbol | One operation. Attempts are not part of the definition; the allocation id is. |
| A REVERSE that flips | The close's fills carry the OLD allocation's id; the new position is a NEW reservation | Two operations. The first is closed now, the second when it closes. |
| A REVERSE that ends flat (decision 26) | Only the old allocation has fills | One operation, the closed one. A reservation without a fill is not an operation. |
| Still open | A BUY or a SELL, not both, or a net that is not zero | Not in the list. A live one is counted in the report's `excluded.open_trade_count`, as today. It enters the list at the top when it closes (the newest `closed_at`). Open positions are shown nowhere on this page; decision 44 dropped the OPEN column, and this design does not add one. |
| A reservation that expired or was released before any fill | No ledger row | Not an operation. |

### B. How each new figure is derived

All of it is pure `Decimal` arithmetic in `performance/domain`, over the groups of ONE allocation that the source already returns. "Opening side" and "closing side" are those of § A.

| Field | Derivation | Unit |
| --- | --- | --- |
| `entry_price` | `Σ notional(opening side) / Σ quantity(opening side)` | settlement currency per one unit of base |
| `exit_price` | `Σ notional(closing side) / Σ quantity(closing side)` | the same |
| `size` | `Σ quantity(opening side)` | base currency |
| `base_currency` | `base_currency_of(symbol, settlement_currency)`, upper-cased | the unit of `size` |
| `fees` | `Σ fee` of every fill, both sides, whose `fee_currency` is the settlement currency | settlement currency |
| `other_fees` | one `{currency, amount}` per OTHER fee currency whose summed fee is above zero, sorted by currency | each amount in its own currency, never converted |

- **Which average.** The quantity-weighted average price: `Σ(qᵢ·pᵢ) / Σqᵢ`, because `notional` is `q·p` per fill (T5). It is taken from `notional`, not from the `price` column, for two reasons: the aggregate already carries the sum, and it is the same number `pnl` is built from. So a row is self-consistent and can be checked by hand: when both sides have the same quantity and every fee is in the settlement currency, `pnl = (exit_price − entry_price) × size × (+1 for LONG, −1 for SHORT) − fees`. A test asserts that identity.
- **Size when the two quantities differ.** They differ only when a fee was charged in the base coin, which is Pionex spot's behaviour on a BUY: less was sold than was bought. `size` is the OPENING quantity, the number a venue shows for the position it opened. The closing quantity is not a second field; the difference is the base-currency fee, and that fee is in `other_fees`. On Bybit the two are equal, because the fee is charged in USDT on both sides (CLAUDE.md, "The first real futures round trip").
- **Fees.** `fees` is exactly the amount `derive_trade` subtracts from `pnl`. Nothing is converted (rule 7). A fee in the base currency is listed in `other_fees` and leaves `fees_complete` TRUE, because `pnl` already contains it (§ 11). A fee in a third currency is listed in `other_fees` and makes `fees_complete` FALSE, as today. So a non-empty `other_fees` does not by itself mean the PnL is incomplete; `fees_complete` keeps that meaning and is unchanged. Fee currencies are compared and reported upper-cased, as `derive_trade` compares them.
- **Precision and JSON form.** `size`, `fees` and each `other_fees` amount are exact sums, written with the existing `Money` type (a plain-notation string). The two prices are quotients. The domain divides inside a local context of 60 digits (`decimal` is the standard library, so `domain/` gains no framework import), and a new wire type `Price` in `shared/infrastructure/wire.py` rounds half-even to 18 places, the ledger's own scale, and writes plain notation. With one fill per side the price equals that fill's price up to the rounding of the stored `notional` (at most `1e-18 / quantity`).
- **`return` and `capital_at_open` are not touched.** `return` stays `pnl / pool_total_at_open`, null when no capital was recorded (decisions 17 and 43).
- **`usd_rate_at_fill` is still never read** (§ 11).
- **When a figure cannot be derived**, `base_currency`, `entry_price`, `exit_price` and `size` are null together and the operation stays in the list, because it is in the totals. § G says when and what is logged. `fees` and `other_fees` are plain sums and are never null.

### C. Rehearsal operations

- **Recognised from stored data alone.** A fill is a rehearsal fill when its `exchange_fill_id` starts with `REHEARSAL_FILL_ID_PREFIX` (`"fake-fill-"`, `execution/domain/fill.py:16`), the same prefix test, with the same escaping, that the source and the mode guard use today. A **rehearsal operation** is an allocation EVERY one of whose fills is a rehearsal fill, closed under the same rule as any other. An operation is therefore wholly real or wholly rehearsal. There is no partly-rehearsal row.
- **A mixed allocation** (fills of both origins, T10) is not a rehearsal operation. Its live fills are derived exactly as today: a closed real trade if they net to zero alone, an open trade otherwise. Its rehearsal fills are never listed, and the read logs one WARNING with the allocation ids. This rule is also what keeps an allocation id from appearing twice in the list, which would break the keyset.
- **How the source returns them.** The aggregate gains the prefix test as a grouped column and loses its `NOT LIKE` filter. The adapter splits the rows: `PoolFills.groups` keeps the non-rehearsal groups, exactly what it holds today, and a new `PoolFills.rehearsal_groups` holds the rest. `FillGroup` gains `rehearsal: bool`.
- **How they stay out of every total. Two walls.**
  1. By construction: `ReadPoolPerformance` and `ReadStrategyPerformance` read `PoolFills.groups` and nothing else. `rehearsal_groups` has one reader, `ReadStrategyTrades`.
  2. By refusal: a new `scope.require_live_only(groups)` raises `InvariantViolation` when a group in the live set is marked rehearsal. Both performance reads and the list call it, so a source that puts a rehearsal group in the wrong set ends as the existing fixed 500 and one ERROR, never as a figure.
- **What changes in the reports: nothing.** The pool report, the strategy report, the curve, the monthly grid, the ranges and `by_pair` are the same bytes for the same ledger. `excluded.rehearsal_fill_count` is unchanged in meaning and in source (the count statement stays); it still counts every rehearsal fill of the scope, including those of open and of mixed allocations. No new `excluded` key is added.
- **How a rehearsal row is marked.** `"rehearsal": true` on the row. It is a required boolean on every row, `false` for a real one.
- **What its figures carry.** The same derivations over its own fills: `entry_price`, `exit_price`, `size`, `fees`, `pnl`, and `return = pnl / pool_total_at_open` with the pool capital its reservation recorded (T11), null when none was. They are that operation's own figures and are never summed with anything. Today that means entry 1, exit 1, fees 0, PnL 0 (T9). The API serves what the ledger holds, and the panel shows those numbers as they are (§ L, Q1, answered).
- **How a fixed-price row is told from an alert-priced one, from stored data alone** (decision 43, answered 2026-10-04). Nothing in a ledger row says which version of the simulated exchange wrote it: the fill id is `fake-fill-<uuid>` either way. What IS stored is the price the fill would have if it had been filled at the alert's price: `signals.price`, on the signal the operation's reservation names (T15). So, for each rehearsal row of the page, the read compares the price of its OPENING fills with that alert's price and serves the result as `rehearsal_fill_price`:

  | Value | Rule (exact `Decimal` equality on the stored values) | What the panel may say |
  | --- | --- | --- |
  | `FIXED_ONE` | every opening fill is priced exactly 1, and the alert's price is not 1 | opened at a fixed price of 1, not at a market price |
  | `ALERT` | every opening fill is priced exactly at the alert's price | opened at the price its alert carried |
  | `UNDETERMINED` | anything else | filled by the simulated exchange, with no claim about the price |

  - It compares the fills' own `price`, not the derived `entry_price`. An average can differ from its only fill in the last places (§ B), and an exact comparison would then fail for a small quantity.
  - **The one case stored data cannot separate.** When the alert's price was itself exactly 1, a fixed-price fill and an alert-priced one are the same row in every column. It reads `ALERT`, and that is true whichever code wrote it: 1 IS the alert's price. It is also the one case where the difference does not matter to a reader.
  - **Only the opening side is tested**, for two reasons. A closing fill has no guaranteed path to its alert (T16). And time runs one way: fixed-price fills are written before decision 45 takes effect and alert-priced ones after, so a row whose entry is alert-priced has an alert-priced exit. The mixed row that CAN exist is a dry-run position that is open when decision 45 is deployed: entry 1, exit at the alert's price. It reads `FIXED_ONE`, which is the right answer: its entry is not a price, so its PnL is not a result.
  - **`UNDETERMINED` is the fallback, never a guess.** It is what a row reads if decision 45's design prices an opening fill at anything other than the stored alert price exactly (a rounding to the tick, a simulated slippage), or if the comparison cannot be made. The panel then says only that the row was simulated, which is the smallest sentence that is true of every rehearsal row.
  - **No marker is invented and no migration is needed.** The value is derived at read time from `ledger_entries.price`, `reservations.signal_id` and `signals.price`. It is null on a real row.
- **Opt-in.** Rehearsal rows are served only for `include_rehearsal=true`. The default request is byte-for-byte today's list. So a client that does not know the marker never receives a row it would show as real (§ D).
- **Order and cursor when both kinds are in one list.** One list, one total order: `(closed_at, allocation_id)` descending over the union of real and rehearsal closed operations. An allocation is in at most one of the two sets (the mixed rule above), so the pair stays a unique position. The cursor is unchanged, the same two parameters. A cursor minted by a request without rehearsal rows is a valid position in the list with them, and the reverse: both lists are the same order with or without some members. `next_cursor` is still the last row served, and the look-one-past-the-limit rule still decides whether it is null.
- **A strategy that only ran in dry run** shows its operations in the list and still shows a zero report above it. The panel says why in one sentence (§ F).

### D. The API

`GET /api/performance/strategies/{id}/trades`, the existing route. One new query parameter, new fields on each row, nothing removed or renamed.

```
GET /api/performance/strategies/{id}/trades
      ?limit=1..200                        default 50 (the panel asks for 20)
      &before_closed_at=<ISO-8601, zone>   both or neither, as today
      &before_allocation_id=<uuid>
      &include_rehearsal=true|false        NEW, default false

200
{
  "trades": [
    {
      "allocation_id":   "0b6f…",                         string (uuid)        unchanged
      "pair":            "STXUSDT",                       string               unchanged
      "direction":       "LONG",                          "LONG" or "SHORT"    unchanged
      "opened_at":       "2026-09-30T12:00:00Z",          string (UTC instant) unchanged
      "closed_at":       "2026-09-30T14:30:00.123456Z",   string (UTC instant) unchanged
      "rehearsal":       false,                           boolean              NEW, never null
      "rehearsal_fill_price": null,                       string or null       NEW, see below
      "base_currency":   "STX",                           string or null       NEW
      "entry_price":     "0.451200000000000000",          string or null       NEW, 18 places
      "exit_price":      "0.463100000000000000",          string or null       NEW, 18 places
      "size":            "1250.000000000000000000",       string or null       NEW, base units
      "fees":            "0.630000000000000000",          string               NEW, never null
      "other_fees":      [],                              list                 NEW, never null
      "pnl":             "14.245000000000000000",         string               unchanged
      "capital_at_open": "1000.000000000000000000",       string or null       unchanged
      "return":          "0.0142450000",                  string or null       unchanged
      "fees_complete":   true                             boolean              unchanged
    }
  ],
  "next_cursor": { "before_closed_at": "…Z", "before_allocation_id": "…" }   or null, unchanged
}
```

- `other_fees` entries are `{"currency": "BNB", "amount": "0.000120000000000000"}`: `currency` an upper-cased string, `amount` a string above zero.
- `base_currency`, `entry_price`, `exit_price` and `size` are null TOGETHER or not at all. Null means "cannot be derived from this operation's fills" (§ G), never "zero" and never "not loaded". A healthy operation has all four.
- `capital_at_open` and `return` are null for an operation opened before `pool_total_at_open` was recorded, as today.
- `rehearsal` is `false` on every row of a request that did not ask for rehearsal rows.
- `rehearsal_fill_price` is null exactly when `rehearsal` is false. On a rehearsal row it is `"FIXED_ONE"`, `"ALERT"` or `"UNDETERMINED"`, by the rule of § C.
- Money, quantities, prices and ratios are JSON strings. The existing test that walks every response of every route for a JSON float or an exponent covers the new fields (`tests/performance/infrastructure/test_performance_router.py:800-827`).
- Refusals are unchanged: 404 `no such strategy`; 422 for half a cursor, a naive `before_closed_at` or a `limit` outside 1..200. A value of `include_rehearsal` that is not a boolean is FastAPI's own 422.

**The figures of the detail view need no endpoint.** The row carries every figure decision 43 names, so the dialog renders them from the row it was opened from (§ F), with no request. No `GET …/trades/{allocation_id}` is added: there is no cold-load path to serve, and a second read of the same figures would be a second place they could disagree.

**The individual fills have their own read** (decision 43, answered 2026-10-04: the detail view shows each fill's time, side, price, quantity and fee).

```
GET /api/performance/strategies/{id}/trades/{allocation_id}/fills

200
{
  "allocation_id": "0b6f…",                           string (uuid)        never null, the id asked for
  "fills": [                                          list                 never null, never empty
    {
      "filled_at":    "2026-09-30T12:00:00.123456Z",  string (UTC instant) never null
      "side":         "BUY",                          "BUY" or "SELL"      never null
      "price":        "0.451200000000000000",         string               never null, the fill's own price
      "quantity":     "1250.000000000000000000",      string               never null, base units
      "fee":          "0.310000000000000000",         string               never null, may be zero
      "fee_currency": "USDT",                         string               never null, upper-cased
      "rehearsal":    false                           boolean              never null
    }
  ],
  "truncated": false                                  boolean              never null
}
```

- **No field is nullable.** Every one is a NOT NULL column of `ledger_entries` or a boolean derived from one.
- `fee_currency` travels with `fee`. The owner asked for the fee; an amount without its currency is not a fee, and nothing is converted (rule 7).
- `price`, `quantity` and `fee` are the stored values, written with the existing `Money` type. Nothing is averaged or rounded here: these rows are what the list's averages are made of.
- Fills are ordered by `(filled_at, id)` ascending, the order they happened in, with the row id as a stable tie-break.
- **Capped at 200 fills.** The statement asks for 201; when it gets them, the first 200 are served with `truncated: true`. An operation of this system has a handful of fills, so the cap bounds a response, it does not page one.
- **A rehearsal operation** answers its fills, each with `rehearsal: true`. No opt-in parameter is needed: the route is new, so no client that predates the marker can call it. A real operation's fills carry `false`. A mixed allocation (§ C) answers ALL its fills, each with its own flag, so the one place a mixed allocation can be looked at hides nothing.
- **Any allocation of the strategy that has a fill is served,** closed or still open. The panel links only closed operations; the read has no reason to derive closure, so it needs no `base_currency_of` and cannot fail on a symbol.
- Not served: `usd_rate_at_fill` (§ 11), the venue's order and fill ids, `notional` (it is `quantity × price`) and the symbol (the dialog has the pair).

| Case | Status | Body | Log |
| --- | --- | --- | --- |
| Fills found | 200 | above | nothing; WARNING when truncated or mixed (§ G) |
| No such strategy | 404 | `{"detail": "no such strategy"}`, the existing shape | — (as the other routes) |
| No fill carries BOTH this allocation id and this strategy's id | 404 | `{"detail": "no such operation"}` | WARNING: strategy id, allocation id |
| `allocation_id` is not a UUID | 422 | FastAPI's own | — |
| A fill of this allocation and strategy sits in another pool than the strategy's | 500 | `performance data failed an integrity check`, the existing answer | ERROR with the reason, the existing `_guarded` line |

- **An operation of another strategy is not readable through this strategy's path.** The statement itself carries both predicates, `allocation_id = :allocation AND strategy_id = :strategy`, and `ledger_entries.strategy_id` is on every fill (rule 6). No row of another strategy leaves the database, so there is nothing for the application to filter and nothing to leak by forgetting to.
- **One 404 for three cases:** an id that does not exist, an allocation of ANOTHER strategy, and an allocation of this strategy that never had a fill. Same status, same body. The answer does not say whether the id exists somewhere else.
- **Why the pool is checked after the read and not in the WHERE.** A pool predicate would silently drop a fill written under another pool, and the reader would see a shorter list with no trace. Reading by allocation and strategy and then refusing a foreign-pool row is the rule `scope.require_single_pool` already applies to the list.

**Backward compatibility, and the order of deploy.**

| Order | What a reader sees | Why |
| --- | --- | --- |
| Backend first, panel later (the order of § I) | The older panel shows exactly what it shows today | Its check ignores keys it does not know (T12), it never sends `include_rehearsal`, so it never receives a rehearsal row, and it never calls the fills route. |
| Panel first, backend later | The trades section shows its existing error state with "Try again"; the rest of the page works | The older API ignores `include_rehearsal` and serves rows without the new fields, and the new check rejects such a page rather than render a row with an invented figure. This is a refusal, not a crash, and it ends when the API restarts. The fills route does not exist there either; the dialog cannot be reached, because the list did not load. |

The order is therefore backend, then panel, and the reverse order degrades one section and corrupts nothing. Today the second row cannot happen in production, because the panel is not served there (T14).

**Rejected.**
- *Always serving rehearsal rows.* A client that predates the marker would list them as real operations. The opt-in also keeps the current spec scenario literally true for the default request (§ J).
- *A separate endpoint for rehearsal operations.* Two lists cannot be paged as one by a keyset.
- *Nulling `pnl` and `return` on a rehearsal row.* They are derived from the ledger like any other. A null would hide them the day the simulated exchange fills at the alert's price (decision 45), and the owner chose to see the stored numbers (§ L, Q1).
- *A marker for "written before decision 45"* (a new column, a second fill-id prefix, a deploy date compiled into the code). The first is a migration, and no backfill could mark the rows already written honestly. The second is a choice of decision 45's design, which is not made here, and this design must not rest on a marker the ledger does not carry today. The third is not stored data. The comparison with the alert's price needs none of them (§ C).
- *Paging the fills.* A cap with a flag is enough for a list of a handful of rows, and a keyset over fills would be a second cursor contract for nothing.

### E. Layering and cost

| Component | Layer | File | Change |
| --- | --- | --- | --- |
| `FillGroup` | **domain**/performance | `performance/domain/closed_trade.py` | Gains `rehearsal: bool`, no default. `ClosedTrade` is NOT changed. |
| `OperationFees`, `FeeAmount`, `OperationFigures`, `operation_fees(groups)`, `operation_figures(groups, direction)`, `sides_overlap(groups, direction)` | **domain**/performance | `performance/domain/operation.py` (new) | Pure functions of one allocation's groups. `operation_figures` returns `None` when the figures cannot be derived (§ G). Imports `decimal`, `dataclasses`, `market_symbol` and `closed_trade` only. |
| `RehearsalPricing` (`FIXED_ONE`, `ALERT`, `UNDETERMINED`), `PricingFacts`, `classify_rehearsal_pricing(direction, facts)` | **domain**/performance | `performance/domain/operation.py` | Pure: the rule of § C over the alert's price and the lowest and highest fill price of each side. |
| `OperationFill` | **domain**/performance | `performance/domain/operation.py` | One fill as the detail view shows it: instant, side, price, quantity, fee, fee currency, rehearsal flag, and its pool identity for the check of § D. |
| `PoolFills.rehearsal_groups` | **application**/performance | `performance/application/ports.py` | A second tuple, default `()`. `AllocationFillsSourcePort.pool_fills(pool)` keeps its signature: still exactly one pool per call (rule 7). |
| `RehearsalPricingSourcePort.pricing_facts(pool, strategy_id, allocation_ids)` | **application**/performance | `performance/application/ports.py` | Consumer-declared. Answers `{allocation_id: PricingFacts}` for the ids given, in one call. |
| `OperationFillsSourcePort.operation_fills(strategy_id, allocation_id, limit)` | **application**/performance | `performance/application/ports.py` | Consumer-declared. Takes the strategy AND the allocation, never the allocation alone, so a read without the strategy predicate cannot be requested through it. |
| `require_live_only(groups)` | **application**/performance | `performance/application/scope.py` | The second wall of § C. |
| `ReadPoolPerformance`, `ReadStrategyPerformance` | **application**/performance | their own files | One added call, `require_live_only`. No other change. |
| `ReadStrategyTrades(fills, pricing).read(..., include_rehearsal=False)`, `TradeItem` | **application**/performance | `performance/application/read_strategy_trades.py` | `TradeItem` gains `rehearsal`, `fees`, `figures`, `pricing`. The read merges the two sets, pages, then derives the figures of the rows on the page only, and classifies the rehearsal rows of the page. |
| `ReadOperationFills(source).read(strategy_id, pool, allocation_id)`, `OperationFills`, `UnknownOperation` | **application**/performance | `performance/application/read_operation_fills.py` (new) | Asks for `limit + 1`, refuses a foreign-pool row (`InvariantViolation`), raises `UnknownOperation` on an empty answer, logs (§ G). `MAX_OPERATION_FILLS = 200`. |
| `SqlAlchemyAllocationFillsSource` | **infrastructure**/performance | `performance/infrastructure/allocation_fills_source.py` | The aggregate groups by the prefix test and by `symbol` as well, and drops the `NOT LIKE` filter. The count statement is unchanged. |
| `SqlAlchemyRehearsalPricingSource` | **infrastructure**/performance | `performance/infrastructure/rehearsal_pricing_source.py` (new) | One grouped SELECT: `ledger_entries` joined to `reservations` and `signals`, `WHERE allocation_id IN (:ids)` and the strategy and pool, answering per `(allocation, side)` the lowest and highest `price` and the signal's `price`. |
| `SqlAlchemyOperationFillsSource` | **infrastructure**/performance | `performance/infrastructure/operation_fills_source.py` (new) | One SELECT on `ledger_entries`: `WHERE allocation_id = :a AND strategy_id = :s ORDER BY filled_at, id LIMIT :n`. No join. |
| `TradeBody`, the `include_rehearsal` query parameter, the fills route, `FillBody`, `OperationFillsBody` | **infrastructure**/performance | `performance/infrastructure/performance_router.py` | § D. The fills route resolves the strategy's pool with the existing `_strategy_pool` (the 404) and maps `UnknownOperation` to the 404 of § D. |
| `Price` | **infrastructure**/shared | `shared/infrastructure/wire.py` | A third annotated type beside `Money` and `Ratio`. |

- **`domain/` gains no framework import.** The new module is arithmetic and comparisons over dataclasses. The division's local context is `decimal.localcontext`.
- **Adapters read other modules' tables; the application never does.** `performance/infrastructure` already imports `ReservationRow` and `LedgerEntryRow`; the pricing adapter also imports `SignalRow`. The ports speak in `performance`'s own types (`PricingFacts`, `OperationFill`), so no `signals`, `allocation` or `ledger` type crosses into `application/` or `domain/`.
- **Why the figures live beside `ClosedTrade` and not on it.** `ClosedTrade` is what the curve, the ranges, the grid and `by_pair` consume. Leaving it untouched means no total path can change by accident, and no existing test of those paths is edited. The figures are a display derivation with one consumer.
- **Why `symbol` joins the GROUP BY.** Today each group reports `min(symbol)`, which hides an allocation whose fills name two markets. With the symbol grouped, the domain sees every spelling and can tell two spellings of one market (`market_key` equal) from two markets (§ G). `derive_trade` sums across groups, so its results do not change; the row count grows only for an allocation written under more than one spelling on the same side.
- **The sequence of the list read.** (1) `pool_fills(pool)`. (2) `strategy_groups` and `require_live_only` over the live set, then `derive_trades`: today's list. (3) Only when asked: `strategy_groups` over the rehearsal set, minus every allocation that also has a live group (WARNING with the ids), then `derive_trades`. (4) Merge, sort by `(closed_at, allocation_id.int)` descending, apply the cursor, slice. (5) For the rows of the page only, `operation_fees`, `operation_figures`, `sides_overlap`. (6) Only when the page holds a rehearsal row: ONE call of `pricing_facts` with the ids of those rows, then `classify_rehearsal_pricing` for each.
- **Cost of the list.** Three statements per page, the same three as today (the strategy row, the grouped aggregate, the rehearsal count), plus a fourth only when the page holds a rehearsal row: the pricing facts of those rows, at most `limit` ids in one `IN`. None is issued per row. The work is still bounded by the pool's allocation count (§ 11, "What bounds the work"), now counting rehearsal allocations too, which the SQL used to drop and Python now folds. In production today that is the whole ledger, a handful of rows. The figures are computed for at most `limit` rows.
- **Why the pricing facts are a statement of their own and not three more columns of the shared aggregate.** The aggregate is what every report reads. A join to `signals` there would put another module's table under every total for the sake of a sentence on a rehearsal row. A separate statement keeps that out of the reports' path and runs only when a rehearsal row is on screen.
- **Cost of the fills read.** Two statements: the strategy row, and one SELECT with `LIMIT 201` that `ix_ledger_allocation` serves (T17). Never one per fill. It derives nothing, so its cost does not grow with the pool.
- **Paging stays in Python, over derived operations**, for the reason § 11 gives: "closed" is a domain rule SQL does not have.

| Rule | Impact |
| --- | --- |
| `DRY_RUN` (rule 1) | The read is the same in both modes and needs no credential. No test needs one. |
| Idempotency (rule 2), webhook (rule 3), allocation transaction (rule 4) | Untouched. The read takes no advisory lock and no row lock and writes nothing. |
| Pools (rule 5), PnL in native currency (rule 7) | One pool per read, as today. `fees` is in the settlement currency; a fee in any other currency is listed in its own currency and never converted. No figure sums two pools or two currencies. The fills read sums nothing, serves each fee with its currency, and refuses a fill of another pool. |
| Ledger (rule 6) | Read only. No row is written, updated or removed. |
| Credentials (rule 8) | Untouched. |

### F. Frontend

**Where the table sits.** `TradesTable` leaves the left column and becomes a full-width section under the two-column grid, above the delete control. It is the widest thing on the page, and the left column cannot hold it (T13). The header, the performance block and the settings column do not move.

**Columns.** Eleven figures and the control that opens the detail. Each tier is a Tailwind viewport variant on the `th` and the `td` (`hidden md:table-cell`, and so on); the page chrome is fixed, so the viewport decides the width the table gets. The pixel budgets are estimates from the classes (jsdom has no layout) and are confirmed by the owner by eye, like every table of unit 9p.

| Shown from | Columns added | Estimated row width |
| --- | --- | --- |
| every width | Closed (UTC), Pair (with the rehearsal tag), Side, PnL {currency}, PnL %, Details | about 530 px |
| `md` (768 px) | Entry, Exit | about 690 px |
| `xl` (1280 px) | Size, Fees {currency}, Pool at open | about 930 px |
| `min-[90rem]` (1440 px) | Opened (UTC) | about 1,090 px |

- **At 1440 px and above** every column shows: the section is about 1,160 px wide there.
- **Under 1024 px** the page is one column with no side rail. From 768 px the table shows eight columns; below it, six. Below about 560 px the six columns scroll sideways inside the `overflow-x-auto` wrapper the table already has. Every figure a tier hides is in the detail view, which is the reason the Details control is in the first tier.
- Column order on a wide screen: Opened, Closed, Pair, Side, Entry, Exit, Size, Fees, PnL, PnL %, Pool at open, Details.
- The header "Return" becomes **"PnL %"** in both languages, decision 43's own words. The section title stays "Closed trades" / "Operaciones cerradas".
- Prices and sizes are formatted for display from the server's string: in the table at most five decimals and no trailing zeros, or four significant digits when five would leave fewer, and fees like the PnL beside them with the pool currency's decimals; in the dialog up to eight significant digits and no trailing zeros (owner decision 46, 2026-10-05). Nothing is computed from them (§ 15, "Money is never computed in the browser").
- A null `entry_price`, `exit_price` or `size` renders the existing `Absent` em dash with its reason for a screen reader. A fee in another currency renders after the fee as "+ 0.00012 BNB". `fees_complete: false` puts an asterisk after the PnL figure, explained by one note under the title for the page on screen (owner decision 46, 2026-10-05; the dialog keeps the words).

**How a rehearsal row is marked** (decision 43, answered 2026-10-04: the stored numbers are shown as they are, beside the mark and a sentence that says how the row was filled).
- A text tag in the Pair cell, on its own line under the pair, in the words of the mode badge (`DryRunBadge`, "Modo simulación") and in the same amber `decision` token. It is text, so it does not rest on colour. Its wording follows `rehearsal_fill_price`, and that is what tells the rows apart:

  | `rehearsal_fill_price` | Tag (EN / ES) |
  | --- | --- |
  | `FIXED_ONE` | "Dry run · fixed price" / "Simulación · precio fijo" |
  | `ALERT` | "Dry run · alert price" / "Simulación · precio de la alerta" |
  | `UNDETERMINED`, or a value this panel does not know | "Dry run" / "Simulación" |

- **Every cell of a rehearsal row shows the stored number.** Entry 1 and exit 1 are printed as 1. No cell of a rehearsal row is blanked or special-cased.
- Its PnL and PnL % are drawn in neutral ink, never in the gain or loss colour. Green and red stay reserved for money that was made or lost.
- **The sentences under the title** appear by what the page on screen holds, so each one is true of a row the reader can see:
  1. At least one rehearsal row: those operations were filled by the simulated exchange, not at the venue, and are not counted in any figure of the page. This is what explains a list with rows under a report that says zero trades.
  2. At least one `FIXED_ONE` row: a row marked "fixed price" was opened at a fixed price of 1 whatever the market price was, so its prices and its PnL are not a result.
  3. At least one `ALERT` row: a row marked "alert price" was opened at the price its alert carried, was sized at 1x and carries a fee simulated at the taker rate, so its PnL is not what it would have made live (the owner's wording of 2026-10-05, follow-up 9qf.3; the exact texts are in the i18n table below).
- An `UNDETERMINED` row gets sentence 1 only. Nothing is claimed about its price, because stored data supports no claim (§ C).
- The request always carries `include_rehearsal=true`.

**The detail view: a dialog.**

| Option | For | Against |
| --- | --- | --- |
| **A dialog (chosen)** | The row already holds every figure, so it opens at once and only its fills table loads. The list keeps its page (the page index is local state). The app has the pattern: a native `<dialog>` opened with `showModal()`, Escape and the `cancel` event routed to one handler (`ArchiveDialog`, `DeleteStrategyDialog`). On a narrow screen it has the whole viewport for the figures the table hides. One at a time is what "one by one" says. | No link to a single operation. |
| A route (`/strategies/:id/trades/:allocationId`) | A link that survives a refresh | A refresh needs an endpoint that serves one operation by id, which nothing else needs. Leaving the page loses the list's page. A single-operator panel has nobody to send the link to. |
| An expanding row | Keeps the context | The detail would be squeezed into the same narrow table whose missing columns it exists to show, and a table inside a table row reads badly with a screen reader. |

- **`TradeDetailDialog`** is presentational: `trade`, `currency`, `locale`, `onClose`. It renders a title (pair, side, and the rehearsal tag when it applies) and a definition list: opened and closed (UTC), entry price, exit price, size with its base currency, fees paid, fees in other currencies when there are any, PnL, PnL % with one sentence saying it is measured against the pool's capital at open and not against the position's margin, pool capital at open, and the operation id (the allocation id, to find it in the logs). A rehearsal operation adds the sentence of its `rehearsal_fill_price` (fixed price, alert price, or simulated with no claim) and says it is in no total. Values are the server's strings with trailing zeros removed, which is a text operation, not arithmetic.
- **The fills table** (decision 43, answered 2026-10-04) sits under the figures, in `OperationFillsTable`, a small container mounted inside the dialog. Being mounted is what asks for the fills, so the request is made when an operation is opened and never before: no fills are fetched for a row nobody opened.
  - `useOperationFills(strategyId, allocationId)`, query key `['performance','strategy',id,'trade-fills',allocationId]`, over `fetchOperationFills`, which validates the body: every field of § D by type, `side` one of BUY and SELL, a non-empty list, and `allocation_id` equal to the one asked for. A body that fails is an error, never a partial table.
  - Columns: Time (UTC), Side, Price, Quantity (with the base currency), Fee (the amount and its currency). A fill whose `rehearsal` differs from the operation's own mark carries the "Dry run" tag on its line; that can only be a mixed allocation.
  - States: a loading line; an error with "Try again", under figures that stay on screen because they came from the row; the table; and, when `truncated` is true, one sentence saying only the first 200 fills are shown.
  - It is a real `<table>` with a caption, inside the dialog's scrolling body, so a long list scrolls inside the dialog and not behind it.
- **Keyboard.** The Details control is a real `<button>` in each row, so Tab reaches it and Enter or Space opens the dialog. Its visible text is "Details"; a screen-reader suffix names the pair, the side and the close time, so twenty buttons are not twenty identical names. The dialog is modal and focus moves into it. Escape or its Close button closes it, and focus returns to the button that opened it (the table keeps that element and focuses it on close; a test asserts `document.activeElement`). "Try again" in the fills table is a button in the same tab order.
- `TradesTable` holds the open operation in local state. The figures need no request; the fills need one.

**i18n**, under `strategies.performance.trades`:

| Key | EN | ES |
| --- | --- | --- |
| `return` (text changed) | PnL % | PnL % |
| `entry` | Entry | Entrada |
| `exit` | Exit | Salida |
| `size` | Size | Tamaño |
| `fees` | Fees {{currency}} | Comisiones {{currency}} |
| `otherFee` | + {{amount}} {{currency}} | + {{amount}} {{currency}} |
| `notDerivable` | This figure cannot be derived from the operation's fills. | Esta cifra no se puede derivar de las ejecuciones de la operación. |
| `rehearsal` | Dry run | Simulación |
| `rehearsalFixed` | Dry run · fixed price | Simulación · precio fijo |
| `rehearsalAlert` | Dry run · alert price | Simulación · precio de la alerta |
| `rehearsalNote` | Operations marked "Dry run" were filled by the simulated exchange, not at the venue. They are not counted in any figure on this page. | Las operaciones marcadas "Simulación" fueron ejecutadas por el exchange simulado, no en el exchange real. No se cuentan en ninguna cifra de esta página. |
| `rehearsalFixedNote` | A row marked "fixed price" was opened at a fixed price of 1, whatever the market price was. Its prices and its PnL are not a result. | Una fila marcada "precio fijo" se abrió a un precio fijo de 1, cualquiera fuera el precio de mercado. Sus precios y su PnL no son un resultado. |
| `rehearsalAlertNote` | A row marked "alert price" was opened at the price its alert carried. It was sized at 1x and its fee is simulated at the taker rate, so its PnL is not what it would have made live. | Una fila marcada "precio de la alerta" se abrió al precio que traía su alerta. Se dimensionó a 1x y su comisión es simulada a la tasa taker, así que su PnL no es el que habría dado en real. |
| `details` | Details | Detalle |
| `detailsOf` | Details of {{pair}} {{side}}, closed {{closed}} | Detalle de {{pair}} {{side}}, cierre {{closed}} |
| `detail.title` | {{pair}} · {{side}} | {{pair}} · {{side}} |
| `detail.entryPrice` | Entry price | Precio de entrada |
| `detail.exitPrice` | Exit price | Precio de salida |
| `detail.size` | Size ({{base}}) | Tamaño ({{base}}) |
| `detail.sizeNoBase` | Size | Tamaño |
| `detail.fees` | Fees paid ({{currency}}) | Comisiones pagadas ({{currency}}) |
| `detail.otherFees` | Fees in other currencies | Comisiones en otras monedas |
| `detail.pnl` | PnL ({{currency}}) | PnL ({{currency}}) |
| `detail.pnlPercent` | PnL % | PnL % |
| `detail.returnHint` | PnL over the pool's capital when the operation opened, not over the position's margin. | PnL sobre el capital del pool al abrir la operación, no sobre el margen de la posición. |
| `detail.capital` | Pool capital at open ({{currency}}) | Capital del pool al abrir ({{currency}}) |
| `detail.rehearsalHint` | Dry run: filled by the simulated exchange, not at the venue. It is not counted in any total. | Simulación: ejecutada por el exchange simulado, no en el exchange real. No se cuenta en ningún total. |
| `detail.rehearsalFixedHint` | Dry run at a fixed price: it was opened at a fixed price of 1, whatever the market price was. Its prices and its PnL are not a result. It is not counted in any total. | Simulación a precio fijo: se abrió a un precio fijo de 1, cualquiera fuera el precio de mercado. Sus precios y su PnL no son un resultado. No se cuenta en ningún total. |
| `detail.rehearsalAlertHint` | Dry run at the alert's price: opened by the simulated exchange at the price its alert carried, not at the venue. It was sized at 1x and its fee is simulated at the taker rate, so its PnL is not what it would have made live. It is not counted in any total. | Simulación al precio de la alerta: abierta por el exchange simulado al precio que traía su alerta, no en el exchange real. Se dimensionó a 1x y su comisión es simulada a la tasa taker, así que su PnL no es el que habría dado en real. No se cuenta en ningún total. |
| `detail.operationId` | Operation id | Id de la operación |
| `detail.close` | Close | Cerrar |
| `detail.fills.title` | Fills | Ejecuciones |
| `detail.fills.time` | Time (UTC) | Hora (UTC) |
| `detail.fills.side` | Side | Lado |
| `detail.fills.sides.BUY` / `.SELL` | Buy / Sell | Compra / Venta |
| `detail.fills.price` | Price | Precio |
| `detail.fills.quantity` | Quantity ({{base}}) | Cantidad ({{base}}) |
| `detail.fills.quantityNoBase` | Quantity | Cantidad |
| `detail.fills.fee` | Fee | Comisión |
| `detail.fills.loading` | Loading the fills… | Cargando las ejecuciones… |
| `detail.fills.error` | The fills could not be loaded. | No se pudieron cargar las ejecuciones. |
| `detail.fills.retry` | Try again | Reintentar |
| `detail.fills.truncated` | Only the first {{count}} fills are shown. | Solo se muestran las primeras {{count}} ejecuciones. |

The existing keys (`opened`, `closed`, `pair`, `side`, `direction.*`, `pnl`, `capital`, `noValue`, `feesIncomplete`, the pager) are reused. The side of an OPERATION stays "LONG" and "SHORT" in both languages (decision 44). The side of a FILL is a buy or a sell, translated; like every string of unit 9p it is confirmed by the owner's review by eye. The fixed-price sentences say "opened at", not "every fill", because that is what `FIXED_ONE` establishes (§ C): an operation open when decision 45 lands has an entry of 1 and an exit at the alert's price, and its fills table shows both. Tailwind palette tokens only: `decision` for the tag, `ink`, `ink-2`, `ink-3`, `rule`, `panel`, `gain`, `loss`; no hex and no `var()` in a `className`.

**Files.** Modify `shared/api/types.ts`, `shared/api/performance.ts` (the page check, the query parameter, `fetchOperationFills`, `useOperationFills`), `features/strategies/TradesTable.tsx`, `features/strategies/StrategyDetailPage.tsx`, `features/strategies/format.ts`, both locale files. Create `features/strategies/TradeDetailDialog.tsx`, `features/strategies/OperationFillsTable.tsx` and their tests. The local `vite.fixture.config.ts` must serve the new fields, rehearsal rows of each of the three kinds and the fills route for the owner's review by eye; it is updated and stays unstaged.

### G. What fails here without a log line?

The domain reports and the application logs, the pattern `derive_trades` already follows for an allocation it cannot test. Levels are those of `performance/application/scope.py`: WARNING with ids for a data fault, never ERROR from a per-page read except for the refused read that already exists.

| Failure | What the reader sees | What is logged |
| --- | --- | --- |
| **A fill is missing** and the allocation no longer nets to zero | The operation is not in the list. A live one is in the report's `open_trade_count`. | Nothing per page, as today: an open position is a normal state, and the read cannot tell it from a missing fill. |
| **A fill is missing and the rest still nets to zero** (a part of the open and the same part of the close) | A closed operation with a smaller size | Nothing here. The ledger alone cannot show it. The control is the reconciliation of venue against ledger, not this read. Stated as a limit (§ K). |
| **A fill with a null or non-positive price** | Cannot be stored: `price` and `notional` are NOT NULL with `CHECK > 0` (T6), and `LedgerEntry` refuses it before the insert. | — |
| **A side whose summed quantity or notional is not above zero** (unreachable through those CHECKs; reachable only from a broken source) | The row is listed with `base_currency`, `entry_price`, `exit_price` and `size` null: an em dash with "cannot be derived" | WARNING: pool, strategy, allocation id, which side. No division is attempted. |
| **A division by zero in an average** | The same row as above. The quotient is taken only after the divisor is checked. | The same WARNING |
| **Fills that disagree in pair**: more than one `market_key` among the allocation's groups | The row is listed, its four figures null. `pair` and `pnl` are what they are today. | WARNING: pool, strategy, allocation id, the market keys. Two SPELLINGS of one market are not a disagreement and log nothing. |
| **Fills that disagree in side**: the opening side's last fill is not earlier than the closing side's first fill, which includes the tie that `_direction` breaks in favour of BUY | The row is listed with its figures; the averages are still well defined. LONG or SHORT, and with it entry and exit, rest on the tie-break. | WARNING: pool, strategy, allocation id. The system cannot produce it (T2, T3); a line is the only way it would ever be noticed. |
| **An ambiguous rehearsal marker: a mixed allocation** | Its live fills as today; its rehearsal fills never listed (§ C) | WARNING: pool, strategy, allocation ids |
| **A rehearsal group handed to a total** | 500 `performance data failed an integrity check`, the existing answer | ERROR with the reason, the existing `_guarded` line |
| **A live id that starts with the prefix** | Would be read as a rehearsal. Cannot be minted: Bybit ids are UUIDs, Binance ids are integers (§ 12). The test is a prefix test, not a substring test. | — |
| **A non-positive pool capital on a rehearsal reservation** | The existing 500, as for a live one | The existing ERROR |
| **The panel forgets `include_rehearsal`** | The list silently shows no rehearsal row, which under `DRY_RUN` is an empty list | Nothing can log it. A frontend test pins the parameter on every request, first page and next page. |
| **A row arrives with a new field missing or mistyped** | The whole page is refused and the section shows its error with "Try again" | The browser has no log. One bad row never renders with a wrong figure. |
| **A new field arrives as a string that is not a number** | That cell reads "unreadable", as the PnL cell does today | — |
| **A rehearsal row whose opening fills are neither at 1 nor at its alert's price** | The plain "Dry run" tag and the general sentence; no claim about its price | INFO, one line per page with the count: it is a steady state if decision 45 prices a fill at anything but the stored alert price, and a WARNING per row per page view would be noise. |
| **The pricing facts of a rehearsal row are missing** (no row came back for its allocation, which the NOT NULL foreign keys to `reservations` and `signals` forbid) | The same plain tag: `UNDETERMINED` | WARNING: pool, strategy, allocation ids |
| **A fixed-price row is read as a real price** | Prevented by the tag and sentence 2 (§ F). Their one input is `rehearsal_fill_price`. | A test per value pins tag and sentence; the mutation that maps every value to the plain tag turns it red. |
| **`rehearsal_fill_price` is null on a rehearsal row, or set on a real one** | The page is refused: the two fields contradict each other | The browser has no log |
| **`rehearsal_fill_price` holds a value this panel does not know** | The plain "Dry run" tag. A later value cannot make an older panel say something false. | — |
| **Fills asked for an allocation that is unknown, belongs to another strategy, or has no fill** | 404 `no such operation`; the dialog keeps its figures and shows the fills error with "Try again" | WARNING: strategy id, allocation id. The panel only asks for ids the list just served, and a closed operation never leaves the list, so this is a hand-typed id or a defect. |
| **More than 200 fills** | The first 200, `truncated: true`, and a sentence saying so | WARNING: strategy id, allocation id, the cap |
| **A fill of the allocation sits in another pool than the strategy's** | The existing 500 | The existing ERROR, with the reason |
| **A mixed allocation, in the fills read** | Every fill, each with its own `rehearsal` flag; the dialog tags the odd ones | WARNING: strategy id, allocation id |
| **The fills body is malformed, or names another allocation than the one asked for** | The fills error with "Try again"; the figures stay | The browser has no log. No partial table is ever drawn. |
| **The fills request fails or the route does not exist** (an older API) | The same fills error; the figures stay | — |
| **The fills read degrades to one statement per fill** | Nothing visible; a slow dialog | Cannot be logged. A test counts the statements of the route for 1 fill and for 50 and requires the same number (§ H). |

No line of this unit carries a credential, a DSN, a token or a raw payload. They carry ids, the pool label, counts and market keys. The fills read logs no price, quantity or fee.

**Threat matrix.** The skill's matrix stays N/A: no shell, subprocess, VCS automation or process integration. Two project rows, as in the decision 42 addendum:

| Threat | Safe behaviour | RED test |
| --- | --- | --- |
| The new `/api` route ships without auth | Auth is a dependency of the performance router, so every route in it carries it | The existing parametrized walk over `app.routes` covers the new GET; the sweeps that enumerate routes (the JSON-float walk, the secret sweep) are taught the new path, as PR 12v-2 did for its route. |
| One strategy's path reads another strategy's operation | The statement carries `allocation_id` AND `strategy_id`; the port cannot be called without the strategy | Two strategies in one pool; S1's path asked for S2's allocation answers 404 with the same body as an unknown id. Mutation: the `strategy_id` predicate removed. |

### H. Testing strategy

| Layer | What | How |
| --- | --- | --- |
| Unit, domain | `operation_figures`, `operation_fees`, `sides_overlap`, `classify_rehearsal_pricing` | Pure. Hand-built `FillGroup`s and `PricingFacts`. |
| Unit, application | `ReadStrategyTrades` with and without rehearsal rows; both performance reads unchanged; `require_live_only`; `ReadOperationFills` (cap, unknown, foreign pool, mixed, each log line) | `FakeFillsSource` (extended with `rehearsal_groups`), fakes of the two new ports, `caplog` |
| Integration, **real PostgreSQL, ORM schema** | The aggregate's new grouping; the split into the two sets; the list end to end; the pricing facts against real `signals` rows; the fills statement (order, cap, the strategy predicate) | The existing fixtures (`tests/performance/infrastructure/conftest.py`), fills written through `RecordFill`, the production write path |
| Integration, **`head` schema** | The premise of § G: a non-positive `price`, `quantity` or `notional` cannot be stored. And `ix_ledger_allocation` exists on `ledger_entries(allocation_id)`. | `tests/pg_head_schema.py`. The ORM schema has no such CHECK (T6) and no such index (T17), so on it these tests would prove nothing. The index is asserted from `pg_indexes`, not from a query plan: on a table of a few rows the planner scans whatever the indexes are. |
| Router | The shapes of § D field by field; the default; the 422; the fills route's three 404 cases with one body; the statement count | `httpx.AsyncClient` over ASGI |
| Frontend | The checks, the requests, the columns, the three tags and their sentences, the dialog and its fills table | Vitest, `vi.stubGlobal("fetch")` |

**Rules that bind the task breakdown.**

- **Strict TDD.** Each RED fails on an ASSERTION. New functions, fields and the query parameter are first added as stubs that compile and answer WRONGLY (prices of zero, `rehearsal` always false, a parameter that is accepted and ignored), in the same commit as the RED test.
- **No lock-hold harness applies.** The read takes no lock and writes nothing, so there is no second actor to prove waiting. The one concurrency property of the list, a trade that closes between two page reads, is already tested on real PostgreSQL (§ 11) and must stay green with rehearsal rows in the fixture.
- **One fixture holds both kinds.** The integration fixture of the list has, for one strategy: a real LONG with three opening fills of different sizes and prices, a real SHORT, an open real position, an open rehearsal position, a mixed allocation, and four rehearsal round trips whose signals carry an alert price: one filled at 1 against an alert of 0.4512 (`FIXED_ONE`), one filled at its alert's price with a quantity small enough that the derived average differs from the fill in its last places (`ALERT`), one filled at 1 against an alert of exactly 1 (`ALERT`), and one opened at 1 and closed at its alert's price, the position that was open when decision 45 landed (`FIXED_ONE`). A second strategy in the same pool holds one closed operation, for the fills route's foreign case. Every assertion on the list, on the report and on the fills is made against that one ledger.
- **No test depends on decision 45 being built.** A fill "at the alert's price" is written by the fixture through `RecordFill`, not by the simulated exchange. The classification is tested on stored rows, which is all it reads.
- **Statement counts.** One test per route counts the statements a request issues (a SQLAlchemy `before_cursor_execute` listener): the list issues the same number for a page of 1 row and of 20, and one more when the page holds a rehearsal row; the fills route issues the same number for 1 fill and for 50. This is what pins "never one per row" and "never one per fill".
- **Symbol spellings.** The fills are written under one spelling and asserted under another, and no assertion compares the two as text. The real LONG opens as `STXUSDT.P` (TradingView's) and closes as `STXUSDT` (the venue's); the rehearsal operation opens as `STXUSDT_PERP` (Pionex's) and closes as `STXUSDT.P`. On the performance side every one of them is asserted as pair `STXUSDT` with base currency `STX`. One domain test pins that `STXUSDT.P` and `STXUSDT` on the two sides of one allocation are NOT a pair disagreement, and that `STXUSDT` and `SOLUSDT` are. The fills route is asked for that same operation and must answer the fills of BOTH spellings: it keys on the allocation, never on the symbol.
- **Mutations that prove the tests which pass at once.**

  | Test | Mutation that must turn it red |
  | --- | --- |
  | The pool report and the strategy report are identical with and without rehearsal groups in the ledger | The read concatenates `groups` and `rehearsal_groups` |
  | The default request serves no rehearsal row | The parameter defaults to true |
  | A fill id that merely contains the prefix is a real fill (existing) | `startswith` becomes `contains` |
  | The entry price is weighted by quantity (three fills of different sizes) | The mean of the group averages |
  | A SHORT's entry is its SELL side | The entry is always the BUY side |
  | The identity `pnl = (exit − entry) × size × sign − fees` | The closing side's quantity used as `size` in a base-fee fixture |
  | A real and a rehearsal operation that close at the same instant straddle a page edge and each is served once | Rehearsal rows sorted after the real ones |
  | A cursor minted without rehearsal rows resumes correctly with them | The cursor filter applied before the merge |
  | An allocation that holds a full rehearsal round trip AND a full live one appears once | The mixed filter removed |
  | `require_live_only` refuses a rehearsal group in the live set | The check removed |
  | A row filled at 1 against an alert of 0.4512 is `FIXED_ONE`; against an alert of exactly 1 it is `ALERT` | The alert comparison dropped ("price is 1" alone decides) |
  | A row filled at its alert's price with a small quantity is `ALERT` | The derived `entry_price` compared instead of the fills' own price |
  | A row opened at 1 and closed at its alert's price is `FIXED_ONE` | The closing side tested instead of the opening side |
  | A fill at 0.45 against an alert of 0.4512 is `UNDETERMINED` | "Not 1" read as `ALERT` |
  | A real row carries a null `rehearsal_fill_price` | The classification run for every row |
  | The list issues the same number of statements for 1 row and for 20 | The pricing facts read once per row |
  | S1's path asked for S2's allocation answers 404, with the body of an unknown id | The `strategy_id` predicate removed |
  | 201 fills answer 200 of them and `truncated: true` | The cap removed; and, separately, `LIMIT 200` instead of 201 (the flag never turns true) |
  | The fills come in `(filled_at, id)` order | The ORDER BY removed, with the fixture inserting the later fill first |
  | A rehearsal operation's fills each carry `rehearsal: true`; a mixed allocation's carry their own | The flag taken from the operation instead of from each fill |
  | The fills route issues the same number of statements for 1 fill and for 50 | A lookup per fill |
  | The panel refuses a page whose row lacks `rehearsal`, `fees`, `other_fees`, or carries a number where a string is due (one case per field) | That field's check removed |
  | A rehearsal row's PnL is in neutral ink | `toneClass` applied to it |
  | A rehearsal row filled at 1 prints "1" in its entry and exit cells | Those cells blanked on a rehearsal row |
  | Each `rehearsal_fill_price` value shows its own tag, and its sentence appears only when such a row is on the page | Every value mapped to the plain tag; and, separately, the sentences shown unconditionally |
  | No fills request is made until an operation is opened, and one is made when it is | The fills prefetched with the page |
  | A fills body naming another allocation than the one asked for is refused | The `allocation_id` comparison removed |
  | A failed fills read leaves the figures on screen | The dialog's body replaced by the error |
  | Focus returns to the Details button on close | The focus call removed |
  | Each column's tier | Its responsive class removed (a class assertion, as task 9p.7) |

- **The existing tests of the list, the reports, the curve and `by_pair` are not edited**, except their `FillGroup` builders, which gain the `rehearsal` argument. A test of the source that asserts the exact groups of an allocation written under two spellings on one side changes with the GROUP BY, and its task says so.
- **Gate after every unit.** Backend: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`. Frontend: `npm run lint` and `npm test`.

### I. Delivery

Two sequential PRs to `main`, never stacked. They are split for a reason that is not size.

```
 12e-1 backend: figures, rehearsal rows on request,   ─►   12e-2 panel: columns, marks and sentences,
       the price-source value, the fills route               detail dialog with its fills table

 decision 45 (its own unit, its own design): independent of both; first if it is ready first
```

| PR | Task | Contents | What changes for a user at deploy | Deploy | Rollback boundary |
| --- | --- | --- | --- | --- | --- |
| **12e-1** | 9p.4 | `operation.py`, `FillGroup.rehearsal`, the source's grouping and split, `require_live_only`, `ReadStrategyTrades` with `include_rehearsal`, the pricing facts and `rehearsal_fill_price`, `ReadOperationFills` and the fills route, `TradeBody`, `Price` | Nothing visible. The trades route serves eight more fields per row (§ D), and rehearsal rows to a request that asks. A new GET serves one operation's fills. Every report is unchanged. | Pull as `strategy`, restart both services | A revert restores the nine-field row and removes the fills route (its path then answers 404). No data is touched and there is no migration. |
| **12e-2** | 9p.5 | The checks and the parameter, the table's columns and tiers, the three tags and their sentences, `TradeDetailDialog`, `OperationFillsTable`, the table moved to full width, i18n | Locally, and in production once the panel is served: the list shows the new columns, lists dry-run operations marked by how they were priced, and each row opens onto its figures and its fills. | Pull as `strategy`, no restart (the panel is not served while `PANEL_DIST_DIR` is unset) | A revert restores the seven-column table, which still works against the new API (§ D). |

- **Why two.** (1) The panel refuses a page without the new fields and reads a route that must exist, so the API must be merged and running before the panel that asks for it (§ D). (2) The panel PR is the one the owner reviews by eye, and that review produced seven follow-up tasks on PR 12d; they should not hold a finished backend change. The two also differ in risk: 12e-1 is **medium** (it edits the aggregate that every performance read shares, and adds a route), 12e-2 is **low**.
- **Why the fills route does not get a PR of its own.** It has no order to respect against the list change: both precede the panel, and neither needs the other deployed. A third PR would be a split by size, which the owner does not want. Inside 12e-1 it is its own work-unit commits, so it can be reverted alone.
- **One PR for everything is possible** if the owner prefers it: the panel is not served in production, so the order hazard of § D exists only on a developer machine today. The recommendation stays two, for reason (2).
- **Decision 45 and this unit: independent, and decision 45 first if it is ready first.** They share no file: decision 45 changes `execution`, this unit changes `performance` and the panel. Neither needs the other deployed (§ J). The reason to put decision 45 first is the owner's own: every day of dry run without it writes fills at 1 that can never be repriced, while a day without this unit loses nothing, since the ledger keeps what the list will later show. Decision 45 still needs its design, so this unit does not wait for it: 12e-1 can be cut now. Whichever is ready is merged and deployed, then the next branch is cut from the updated `main`, never stacked.
- **Forecast.** 12e-1: 1,500 to 2,200 authored lines. 12e-2: 1,400 to 2,000. Unit 9p's first forecast was low six-fold, so these already assume tests at about twice the production code. `Decision needed before apply: No` (the three questions of § L are answered and none is open) · `Chained PRs recommended: Yes` · `400-line budget risk: High`.

**Design decisions made here** (not owner decisions; each has its reason above):

| # | Decision | Section |
| --- | --- | --- |
| D1 | An operation is an allocation; opening and closing fills are told apart by side, with the existing earliest-fill rule | A |
| D2 | Prices are quantity-weighted averages taken from `notional`; `size` is the opening quantity | B |
| D3 | `fees` is the settlement-currency amount; other currencies are listed, never converted; `fees_complete` keeps its meaning | B |
| D4 | Prices are rounded half-even to 18 places on the wire, through a new `Price` type | B |
| D5 | A rehearsal operation is an allocation whose fills are ALL rehearsal fills; a mixed allocation's rehearsal fills are never listed | C |
| D6 | Rehearsal groups travel in a separate tuple that only the list reads, and a refusal guards the live set | C, E |
| D7 | Rehearsal rows are served only on `include_rehearsal=true`; the default response is today's | C, D |
| D8 | One list, one keyset order over both kinds; the cursor is unchanged | C |
| D9 | The figures live in a new domain module beside `ClosedTrade`, which is not changed | E |
| D10 | `symbol` joins the aggregate's GROUP BY so that two markets in one allocation are detectable | E, G |
| D11 | A figure that cannot be derived is null with a WARNING; the operation stays in the list | B, G |
| D12 | The detail view is a dialog; its figures come from the row, with no endpoint, and its fills from their own read | D, F |
| D13 | The table moves to a full-width section, with four column tiers | F |
| D14 | A rehearsal row is marked with the mode badge's words and token, and its PnL is in neutral ink | F |
| D15 | Two PRs, backend then panel; the fills route rides in the backend PR | I |
| D16 | A fixed-price row is told from an alert-priced one by comparing its opening fills' price with `signals.price`; three values, `UNDETERMINED` when stored data supports no claim; no marker, no migration | C |
| D17 | The pricing facts are one statement of their own, issued only when the page holds a rehearsal row | E |
| D18 | The fills read is keyed by allocation AND strategy in the statement; unknown, foreign and empty answer one identical 404 | D |
| D19 | The fills are capped at 200 with a `truncated` flag, not paged; a rehearsal operation's fills are served without an opt-in, each flagged | D |
| D20 | A fill of another pool is refused after the read rather than filtered in the WHERE | D |
| D21 | This unit and decision 45 are independent; decision 45 goes first if it is ready first | I, J |

### J. Adjacent work, flagged and not designed

- **WIN RATE in By pair (decision 44).** It should stay a separate unit. It is another endpoint (`GET /performance/strategies/{id}`) and another domain function (`by_pair`), it shares no code with this change beyond `ClosedTrade`, and it needs one definition this design must not invent: whether a trade with a PnL of exactly zero is a win. Rehearsal operations cannot reach it, by § C. Its backend may ride in PR 12e-1 as its own commit only if its design note exists before that PR is cut; otherwise it follows as its own small backend-then-panel pair.
- **The simulated exchange's fill price (T9): decided as decision 45 on 2026-10-04, its own unit with its own design. It is not designed here.** What this addendum fixes is only the boundary between the two units.
  - **What this design assumes about it.** (1) Every simulated fill keeps the `fake-fill-` prefix on its id, and every simulated order the `fake-order-` prefix. They are data contracts (§ 12); § C and the mode guard rest on them. (2) It reprices nothing: fills already in the ledger stay at 1, as decision 45 itself says. (3) It takes effect once: fixed-price fills are written before it, alert-priced ones after. That order in time is why § C tests the opening side only; rolling it back with a dry-run position open is the one way to an alert-priced entry with a fixed-price exit (§ K). (4) Nothing about HOW it prices. This design does NOT assume that an opening fill is priced at the stored alert price exactly, nor how a close is priced, nor what fee is simulated. If the opening fill equals `signals.price`, the row reads `ALERT`; if decision 45's design does anything else, the row reads `UNDETERMINED` and the panel makes no claim (§ C). The read is correct under either.
  - **What changes for the operations list once it lands: nothing in the read, the API or the panel.** The same derivations run over the same columns. Operations opened after it carry the alert's price, so their entry, exit, PnL and PnL % become a simulated result, their tag reads "alert price", and they are still `rehearsal: true` and still outside every total. Operations already written keep an entry of 1 and the tag "fixed price", for good. A simulated fee, if decision 45's design adds one, arrives in `fees` and in `pnl` like any fee, with no change here.
  - **One thing for decision 45's design to weigh, not decided here.** A dry-run position that is open when it is deployed will close at the alert's price against an entry of 1. Its PnL is then `size × (alert price − 1)` in one direction or the other, a number with no meaning. This list marks that row "fixed price" and keeps it out of every total (§ C), so nothing is corrupted; but the cleaner deploy is one made while no dry-run position is open.
  - **Order.** § I.
- **Open positions on the strategy page.** Nothing on the page shows an open operation, live or rehearsal. Decision 44 dropped the OPEN column. This design does not add one.
- **The spec.** `specs/performance-reporting/spec.md`, "Rehearsal Fills Are Excluded From Every Figure", says every read model MUST exclude rehearsal fills, and "A ledger holding only rehearsal fills yields empty performance data" says any read model returns the empty result. Decision 43's answer revises both for the trades list. The spec phase must add the delta: figures still exclude them; the list serves them, marked, on request. It must also specify what the answers of 2026-10-04 added: the price-source value of a rehearsal row and its three wordings, and the fills read with its one 404 for an unknown, a foreign and an empty operation (admin-api and operator-panel).

### K. Risks, and what could be wrong in this design

| Risk | Why it matters | Mitigation or honest limit |
| --- | --- | --- |
| A rehearsal row's price and PnL are artefacts of a fixed fill price of 1 (T9) | The owner's answer expects a strategy in dry run to "show its operations". It will, with entry 1, exit 1, PnL 0. | Decided: the stored numbers are shown, the row is tagged "fixed price" and a sentence says its prices are not a result (§ F). Decision 45 is the real fix, and it cannot repair rows already written. |
| The fixed-or-alert value rests on the OPENING side only | An operation with an alert-priced entry and a fixed-price exit would read "alert price" although its exit is 1 | It needs decision 45 rolled back while a dry-run position is open. The exit cannot be tested for every row from stored data (T16). The fills table shows the exit fill at 1 to anyone who opens the row. Accepted limit. |
| The `ALERT` value needs decision 45 to price an opening fill at exactly `signals.price` | If its design rounds to the tick or simulates slippage, every new row reads `UNDETERMINED` and the "alert price" tag never appears | Nothing false is shown: the row keeps the plain tag and the general sentence. The INFO count per page makes it visible in the log (§ G). The remedy would then be a marker minted by the simulated exchange, which is decision 45's design to make, not this one's. |
| A dry-run position open across decision 45's deploy shows a large meaningless PnL | Entry 1, exit at the alert's price: `size × (alert − 1)` | Tagged "fixed price", in neutral ink, in no total. Flagged to decision 45's design (§ J). |
| The fills route is a new way to read the ledger by id | A missing predicate would let one strategy's path read another's operation | The predicate is in the statement, the port cannot be called without the strategy, and a test with its mutation pins it (§ G, § H). The panel is single-user behind one token today (decision 4), so this guards a defect and the day the panel has more than one owner. |
| The fills cap hides fills beyond 200 | An operation with more would show an incomplete table | It says so on screen and in a WARNING. No operation of this system comes near it: one opening order, a few closing ones. |
| The shared aggregate changes (grouped by origin and by symbol) | Every performance read depends on it; a wrong split would move a total | Two walls (§ C), the "identical with and without rehearsal groups" tests and their mutation, and the existing suites unedited |
| LONG or SHORT, and so entry and exit, rest on the earliest-fill rule (T4), not on which order was the opening one | Fills at the same instant on both sides would label a SHORT as LONG and swap entry and exit. PnL is not affected. | A WARNING on the overlap (§ G). Rejected for now: joining `execution_attempts` to read the opening order, which would add a join to every performance read and a second definition of direction. |
| A fill missing symmetrically from both sides is invisible here | The list would show a smaller size and a smaller PnL as if they were right | A limit of any read over the ledger alone. Reconciliation against the venue is the control. |
| An average price differs from a single fill's own price in the last places | `notional` is stored rounded to 18 places | Bounded by `1e-18 / quantity`, far below anything displayed |
| The estimated column widths are wrong | A tier could overflow or hide a column the owner wants at 1440 px, including "Pool capital at open", which decision 43 keeps | jsdom has no layout. The classes are pinned by tests, the widths by the owner's review by eye; the tiers are four class names to move. |
| Moving the table to full width changes the page the owner approved on PR 12d | It is a visible change nobody asked for by name | It follows from eleven columns in a 724 px column. It is reviewed by eye, and reverting it is one edit. |
| The opt-in parameter is one more thing a client can forget | A panel that forgets it shows an empty list under `DRY_RUN` | Pinned by a test on every request the panel makes |
| Mixed allocations are logged, not shown | The owner reads the panel, not the log | They cannot be created since PR 6d, and the startup guard reports an open one as an ERROR. If production holds one, the first page view logs it. |
| The compatibility argument was made for a bundle that is not deployed | § D's table matters only once the panel is served | Stated (T14). The rules still keep `main` coherent at every commit. |

### L. Questions for the owner: all answered (2026-10-04)

Three were asked, and the owner answered the three on 2026-10-04. They are kept here with their answers so that the reasoning stays beside the design. The record is owner-decisions.md: decision 43's lines of 2026-10-04, and decision 45. **No question is open, and folding the answers in raised no new one.**

- **Q1. What do the price, fee and PnL cells of a dry-run row show?** The simulated exchange fills at a fixed price of 1 with no fee (T9), so such a row holds entry 1, exit 1, fees 0, PnL 0, PnL % 0. The choice was between *(a)* the stored numbers as they are, beside the mark and a sentence saying how the row was filled, and *(b)* those cells empty, with the stored numbers only in the detail view. The design recommended (a).
  - **Answered 2026-10-04: (a).** A dry-run row shows the stored numbers as they are. The panel shows what the ledger holds and hides nothing.
  - **With one requirement the owner added:** the sentence must tell apart the rows filled at the fixed price of 1 from those filled at the alert's price, so that an entry of 1 is never read as a real price.
  - **How it is met, from stored data alone:** the opening fills' price is compared with the price of the alert that ordered them, `signals.price` (§ C). A row reads `FIXED_ONE`, `ALERT` or `UNDETERMINED`, and the tag and the sentence follow that value (§ F). No marker is invented and there is no migration. The one case stored data cannot separate, an alert whose price was itself exactly 1, is the case where the two are the same number.
  - **Unblocked:** the rendering of a rehearsal row in 9p.5. It adds `rehearsal_fill_price` and one statement to 9p.4 (§ D, § E).
- **Q2. Beyond the figures of the list, should the detail view show anything more?** The choice was between *(a)* nothing more in this unit, *(b)* the operation's individual fills, and *(c)* the margin reserved and the leverage of the opening order. The design recommended (a).
  - **Answered 2026-10-04: (b).** The detail view also shows each fill's time, side, price, quantity and fee. They are what explains an average entry or exit price.
  - **(c) is not wanted in this unit.** The margin reserved and the leverage are not shown; that would need its own design.
  - **How it is met:** `GET /api/performance/strategies/{id}/trades/{allocation_id}/fills` (§ D), one indexed statement keyed by allocation and strategy (§ E), a fills table mounted in the dialog (§ F), its failure modes (§ G), its tests (§ H). It rides in the two PRs of § I and adds none.
- **Q3. Should the simulated exchange fill at the alert's price from now on, so that future dry-run operations show a simulated result?** The design recommended yes, as its own unit.
  - **Answered 2026-10-04: yes, recorded as decision 45.** It is its own unit with its own design and touches `execution`, not this read. It reprices nothing already in the ledger.
  - **It is not designed here.** What this addendum assumes about it, what changes for the list when it lands (nothing in the read), and the order of the two units are in § J and § I.

## Addendum: the simulated exchange fills at the alert's price (decision 45) - 2026-10-04

Proposed unit 9q, one PR (proposed name PR 12g; the tasks phase fixes both names). HEAD `929d1f0`. Decision 45 is binding and is not reopened here: from this unit on a dry-run fill is priced at the price its alert carried, nothing already in the ledger is repriced, rehearsal fills keep the `fake-fill-` prefix and stay out of every total, and the unit is delivered before or beside decision 43's (PR 12e), which does not wait for it. This addendum settles what decision 45 left to its design: where the price comes from for each kind of order, how it reaches the simulated exchange, whether the fill can equal the stored alert price exactly, what an unusable price does, the fee, the transition, and the delivery. It changes the `execution` module and two call sites in `signals`. It adds **no migration**, no route and no frontend change.

> **Revised 2026-10-04.** The owner answered the two questions of § N the same day (decision 45's lines of 2026-10-04). A simulated fill carries the venue's taker fee, and a dry run keeps sizing at 1x. The answers are folded into §§ A to N below. Nothing in this addendum is open.

**The answer in one paragraph.** An opening order already carries the alert's price: `OpenOrderSpec.price` is `signals.price`, read back from the database, on every opening path. The simulated exchange receives it in `build_open_order` and then loses it, because `place` is handed only the order and no order type carries a price. So the simulated exchange remembers the price between its own `build_*` call and its own `place` call, keyed by the client order id, and mints the fill at exactly that `Decimal`. Nothing outside `FakeExchangeAdapter` changes for an open. A closing order carries no price today, so `CloseOrderSpec` gains one optional field, `reference_price`, filled from the alert that caused the close; the two callers that build a close both have that alert in hand. The real adapters never read the field, and `place` cannot see it, so what they send to a venue is unchanged, and a test pins the request bytes. The simulated exchange never rounds, never quantises to a tick and never simulates slippage, so an opening fill equals `signals.price` exactly and decision 43's list reads `ALERT`. An order with no usable price is refused through the existing "rejected by venue" path. There is no fallback, and in particular none to 1. Each simulated fill carries the venue's taker fee on its notional, in USDT: `0.00055` on Bybit and `0.0005` on Binance, constants of an infrastructure module. An exchange with no rate gets no simulated exchange, so its signals are refused before any capital is reserved, and a market not quoted in USDT is refused rather than charged in a currency the rate was never verified for. A dry run keeps sizing at 1x. A simulated profit or loss cannot move a pool's availability, because dry-run balances are read from the real venue and nothing in `allocation` or `accounts` reads a fill's price.

### A. Findings from the code (verified at HEAD `929d1f0`)

**How a simulated fill is priced today, per kind of order.** `place` mints one `Fill` per order with `price=self._fill_price`, `fee=Decimal("0")`, `fee_currency="USDT"` (`execution/infrastructure/fake_exchange.py:143-154`). `_fill_price` is the constructor argument, default `Decimal("1")` (`:67, :88`), and `main.py:853-854` builds every fake without it.

| Order | Built at | Size on the order | Fill quantity | Fill price | Fee |
| --- | --- | --- | --- | --- | --- |
| Spot buy that opens (`MarketBuy`) | `fake_exchange.py:112-118`, `domain/order.py:117-120` | `quote_amount = granted` | `quote_amount / fill price`, so `granted` (`fake_exchange.py:197-198`) | 1 | 0 USDT |
| Spot sell that opens (`MarketSell`) | the same, `order.py:121-125` | `granted / alert price` | the order's base size (`:199-200`) | 1 | 0 USDT |
| Spot sell that closes | `fake_exchange.py:137-141` | the ledger's net | the order's base size | 1 | 0 USDT |
| Spot buy that would close a short | refused, as the live spot adapter refuses it (`:128-136`) | — | — | — | — |
| Futures open (`FuturesMarketOrder`) | `fake_exchange.py:103-111`, `domain/futures_order.py:92-143` | `granted × 1 / alert price`, at `FAKE_LEVERAGE = 1` (`:62`) | the order's base size (`:201-202`) | 1 | 0 USDT |
| Futures close, reduce-only | `fake_exchange.py:121-127` | the ledger's net | the order's base size | 1 | 0 USDT |

| # | Finding | Where | Consequence |
| --- | --- | --- | --- |
| P1 | The alert's price reaches every opening order. `signals.price` is read back from the database, then `SignalContext.price`, `PlaceCommand.price`, `OpenOrderSpec.price`. Every opening path (a plain open, the open half of a REVERSE, an open deferred behind an orphan close or in-flight work) goes through `_handle_consumes`, and the continuation reloads the signal first. | `signals/infrastructure/signal_context.py:37, 53`; `signals/application/process_signal.py:436, 637-644`; `execution/application/place_order.py:146-156` | An open needs no new plumbing. The reservation names the same signal (`reservations.signal_id`), which is the one decision 43's classification compares with. |
| P2 | `ExchangePort.place` receives the ORDER, not the spec, and no order type carries a price. | `execution/application/ports.py:189`; `domain/order.py:43-77`; `domain/futures_order.py:57-83` | The simulated exchange has the price in `build_open_order` and has lost it by `place`, where the fill is minted. § B closes that gap inside the adapter. |
| P3 | A closing order carries no price anywhere. `CloseCommand` and `CloseOrderSpec` hold the client order id, the symbol, the side and the base size. | `execution/application/close_position.py:67-86, 159-166`; `ports.py:124-137` | A close needs one new field (§ B). |
| P4 | A close is built in two places only, and both hold an alert. `_handle_releases` closes for the closing or reversing signal. `CloseOrphans` closes for an OPENING signal that found a real orphan; it passes `signal_id=None` on purpose, so that a dust orphan cannot reject the open waiting behind it. | `process_signal.py:764-775`; `signals/application/close_orphans.py:216-232` | "No `signal_id` on the close" does not mean "no alert". The price travels separately from the signal id (§ B). |
| P5 | No order exists without an alert behind it. `PlaceCommand` and `CloseCommand` are constructed nowhere else in `src`. A reconciliation booking writes venue fills straight to the ledger, never through `ExchangePort`, and is refused or skipped under `DRY_RUN`. No route places or closes an order by hand. A retried `signal.process` job and the continuation both reload the signal from the database. A retried `execution.settle` builds nothing: it reads the fill minted at `place`. | grep of `src`; `reconciliation/application/approve_booking.py:124`; `reconciliation_scan_handler.py:111`; `main.py:1435-1448, 1490`; `process_signal.py:436`; `execution/application/settle_execution.py:101-104` | The "no alert at all" case is unreachable today. § F still says what it does, because a later caller could create it. |
| P6 | `signals.price` and `ledger_entries.price` are both `NUMERIC(38, 18)`. `signals.price` has `CHECK (price > 0)` in migration 0002. The ORM model declares no such CHECK. | `signals/infrastructure/models.py:42`; `ledger/infrastructure/models.py:54`; `migrations/versions/0002_signals.py:58, 68` | The price is stored once, at ingress, at the same scale as the column the fill is written to. In production a zero or negative price cannot be stored. A test that relies on that must run on a `head` schema. |
| P7 | The ingress validates only that `price` is a string `Decimal` can parse. A value the CHECK refuses raises `IntegrityError`, which the repository re-raises for every constraint except the strategy foreign key, so the webhook answers 500 and stores nothing. | `signals/domain/alert.py:53, 76-82`; `signals/infrastructure/repository.py:78-87`; `signals/infrastructure/router.py:99-115` | See § F for what each kind of value does. |
| P8 | For an OPEN, the domain already refuses a non-positive price, in both modes: `market_order` and `futures_position_size` raise `InvariantViolation`. `PlaceOrder` catches only `OrderNotPlaceable` around the build, so it propagates and the job is retried. | `domain/order.py:114-115`; `domain/futures_order.py:108-109`; `place_order.py:147-178` | An open with an unusable price never reaches `place`, live or simulated. This unit does not change that (§ F, § M). |
| P9 | The simulated exchange's state is in memory, per instance, for the life of the process: the fills it minted, the signed deltas waiting to be shown to the book, and the fetch counters. One instance per exchange is shared by every job. The book holds signed base quantities only, never a price. | `fake_exchange.py:91-93`; `main.py:853-859, 1012-1014`; `execution/infrastructure/fake_venue_book.py:38, 56-61` | The build and the place of one order run on the same instance, inside one use-case call (`place_order.py:146, 218`; `close_position.py:157, 241`). A price kept between them is safe. |
| P10 | A fill becomes a ledger row unchanged: `price=fill.price`, `notional = fill.quantity * fill.price`, `usd_rate_at_fill` from `FixedUsdRateProvider({USDT: 1})`. | `settle_execution.py:119-124, 220-240`; `main.py:526` | No step between the simulated exchange and the ledger rounds or converts the price. |
| P11 | **Under `DRY_RUN`, balances are read from the real venue.** `balance.sync` and the on-demand refresh have no `dry_run` branch and sign with the vault credential. Availability is the snapshot minus the active reservations. Nothing under `allocation/` or `accounts/` reads the ledger's `price`, `notional` or a PnL. | `main.py:1047-1131, 1278-1385`; `allocation/application/allocate_capital.py:248`; grep of both modules; `specs/exchange-credentials/spec.md:111` | § H. |
| P12 | Neither real adapter reads anything from `CloseOrderSpec` beyond `symbol`, `base_size`, `side` and `client_order_id`, and both `place` methods read the order only. | `execution/infrastructure/bybit_futures_exchange.py:149-221`; `binance_futures_exchange.py:152-234` | A new field on the spec is invisible to what they send (§ B). |
| P13 | `ledger_entries.price` has no reader in `src` today. `notional` has one (the performance aggregate, which drops rehearsal fills in SQL). `fee` has four: the same aggregate; the allocation's net base, which subtracts a fee whose currency is the BASE currency; the pool-wide net positions, which subtract a fee whose currency is NOT the settlement currency; and the mode-origin reader, which groups by fee currency for the same base-fee rule. | grep of `LedgerEntryRow.(price\|notional\|fee)`; `ledger/infrastructure/repository.py:71-88, 116-127`; `execution/infrastructure/mode_origin_reader.py:60-87` | A realistic price changes no existing read. A fee in USDT on a USDT-settled fill is netted by none of them; a USDT fee in any other pool would be subtracted from a base holding (§ E). |
| P14 | 33 construction sites of the simulated exchange in 7 test files (32 of `FakeExchangeAdapter`, 1 of its subclass `CountingFakeExchange`). 12 pass an explicit `fill_price` (9 at 100, 3 at 2). 21 take the default. No test asserts a fill priced 1, and **no test asserts a simulated fee of 0**: every assertion on a fee is on a real adapter's fill, a performance fixture or a booking. The five `fee=Decimal("0")` under `tests/signals` are ledger rows a fixture writes through `RecordFill`. | grep of `backend/tests` | § K. |
| P15 | A fee charged in the settlement currency is subtracted from `pnl` and leaves `fees_complete` true. A fee in the base currency is netted from the holding. A fee above zero in any third currency is left out of `pnl` and turns `fees_complete` false. Currencies are compared upper-cased, and no rate is read. | `performance/domain/derive_trade.py:104-120, 135` | A USDT fee on a USDT-settled fill is complete (§ E). |
| P16 | A fill in a pool that does not settle in USDT cannot be recorded today, in either mode. Settlement asks for the settlement currency's USD rate, and the provider is built with USDT alone, so it raises and the job is retried. | `settle_execution.py:120-122`; `main.py:526`; `shared/infrastructure/usd_rate.py:21-27` | Refusing a simulated fill outside USDT takes nothing away that works (§ E). |
| P17 | The product enables two pools only: Bybit `usdt-m`/USDT and Binance `usdt-m`/USDT. Under `DRY_RUN` a simulated exchange is built for every exchange with a pool at startup plus those two, `tradable_pools` is computed from them, and a pool none serves is warned about at startup and refused per signal as `UNTRADABLE_POOL` before any reservation. | `accounts/domain/known_pools.py:44-49`; `main.py:853-859, 882-903`; `process_signal.py:364-367` | An exchange with no fee rate can be left without a simulated exchange through machinery that exists (§ E). |

### B. Where the alert's price comes from, and how it reaches the simulated exchange

**The opening order: it already carries it (P1). The change is inside the adapter.**

```
webhook ─► signals.price ─► SignalContextAdapter.load ─► _handle_consumes ─► PlaceCommand.price
   PlaceOrder.place
     ├─ exchange.build_open_order(OpenOrderSpec(price=…))    simulated exchange REMEMBERS spec.price
     │                                                         under spec.client_order_id
     ├─ attempt + settle job committed (unchanged)
     └─ exchange.place(order)                                 simulated exchange TAKES the price back
                                                               and mints the Fill at it
   execution.settle ─► fetch_fills ─► FillRecord.price ─► ledger_entries.price     (unchanged)
```

- `FakeExchangeAdapter` gains `_reference_prices: dict[str, Decimal]`, written by its two `build_*` methods and popped by `place`.
- `OpenOrderSpec`, `PlaceCommand`, `PlaceOrder`, every order type and `ExchangePort` are not changed for an open.

**The closing order: one optional field.**

```
closing or reversing alert ─► signals.price ─► SignalContext.price
   _handle_releases ─► CloseCommand(reference_price=context.price)                    NEW field
   _handle_consumes ─► CloseOrphans.close(…, reference_price=context.price)           NEW argument
                          └─► CloseCommand(signal_id=None, reference_price=…)
   ClosePosition.close
     ├─ exchange.build_close_order(CloseOrderSpec(reference_price=…))                 NEW field
     │                                                         simulated exchange remembers it
     └─ exchange.place(order)                                 mints the Fill at it
```

```python
# execution/application/ports.py
@dataclass(frozen=True, slots=True)
class CloseOrderSpec:
    client_order_id: str
    symbol: str
    side: OrderSide
    base_size: Decimal
    reference_price: Decimal | None = None      # NEW

# execution/application/close_position.py
@dataclass(frozen=True, slots=True)
class CloseCommand:
    ...
    signal_id: UUID | None
    reference_price: Decimal | None              # NEW, required, no default
```

- **`reference_price` is the price of the alert that caused this close.** For a plain close and for a REVERSE it is the closing signal's price. For an orphan close it is the price of the opening signal that found the orphan: the same market, at the moment that alert fired. It is never the price of the signal that opened the position.
- **It sizes nothing and is sent nowhere.** The size of a close is still the ledger's net (`close_position.py:143-152`). The field's docstring says it is read only by the simulated exchange.
- **`CloseCommand.reference_price` is required with no default**, the rule `signal_id` already follows (`close_position.py:73-77`): a caller that closes for an alert says so, and one that closes for none says `None` explicitly. `CloseOrphans.close` and `CloseOrphansPort.close` gain it as a required keyword argument, for the same reason.
- **`CloseOrderSpec.reference_price` has a default.** It is constructed once in `src` (`close_position.py:160`), and 10 times in the real adapters' tests. The default is what leaves those tests unedited, which is itself evidence that the real adapters' inputs did not move.

**What each real adapter does with the change: nothing.**

| Adapter | `OpenOrderSpec` | `CloseOrderSpec.reference_price` | `place` |
| --- | --- | --- | --- |
| `BybitFuturesExchangeAdapter` | unchanged type, unchanged use | never read (`build_close_order` reads four fields, P12) | receives the same `FuturesMarketOrder`; cannot see the spec |
| `BinanceFuturesExchangeAdapter` | the same | never read | the same |
| `PionexExchangeAdapter`, `PionexFuturesExchangeAdapter` (not registered) | the same | never read | the same |

- No file under `execution/infrastructure/{bybit,binance,pionex}*` or `shared/infrastructure/{bybit,binance,pionex}/` is edited, and none of their test files is.
- **How a test proves the request bytes are unchanged** (§ K): each real adapter builds and places the same close twice, once with `reference_price=None` and once with a price, and the two runs must produce equal orders and an identical sequence of requests. For the two registered adapters the comparison is made on the wire, through the real trade client over `httpx.MockTransport` with the frozen clock those suites already use, so method, path, query, body bytes and signature are compared byte for byte.

**An order with no alert behind it.** Unreachable today (P5). If a later caller builds one, it passes `reference_price=None`; a real adapter places it as before, and the simulated exchange refuses it (§ F).

**Rejected.**
- *A price field on `MarketBuy`, `MarketSell` or `FuturesMarketOrder`.* Those are the domain objects the real adapters build and send. A price on them is one edit away from a limit order.
- *The simulated exchange reads the price from the database by client order id.* It needs a session inside a process-lifetime adapter, makes `execution/infrastructure` read the `signals` table, and finds nothing for an orphan close, whose attempt has no signal id (P4).
- *A separate price port injected into the simulated exchange.* A second path for a number the spec already carries.
- *A last-known price per market kept by the simulated exchange.* It prices a close at some earlier alert's price and forgets everything at a restart.

### C. The exact price

- **No step between the alert and the fill rounds, quantises or converts it.** The alert's string becomes a `Decimal` (`alert.py:80`). PostgreSQL stores it in `NUMERIC(38, 18)`; a price with more than 18 decimal places is rounded there, once, at ingress. Every later step reads the STORED value: the order is built from `signals.price` read back from the database (P1), the simulated exchange keeps that `Decimal` object, the fill carries it, and the ledger column has the same scale (P6, P10).
- **The simulated exchange applies no tick size, no rounding and no slippage.** It has no instrument rules to round with, and this design adds none. That is a rule of the unit, not an accident: decision 43's classification reads `ALERT` only on exact equality.
- **So the opening fill equals `signals.price` exactly on every opening path** of P1, and the signal it equals is the one the allocation's reservation names. New rows read `ALERT`.
- **The paths where the comparison is not made or not exact:**

  | Case | What the ledger holds | What decision 43's list shows |
  | --- | --- | --- |
  | The alert's price was itself exactly 1 | a fill at 1 | `ALERT`, which is true (decision 43 § C) |
  | A dry-run position open at the deploy | entry 1, exit at the alert's price | `FIXED_ONE` (§ G) |
  | A CLOSING fill | the closing alert's price, exactly | not classified; the list tests the opening side only |
  | The simulated exchange built with an explicit fixed price | that price | `UNDETERMINED`. Tests only; production never passes one (§ J, § K) |

- **A test pins exactness to the last place** with an 18-decimal price and with a 19-decimal one (§ K).

### D. Quantity and size

- **Leverage is 1.** `FAKE_LEVERAGE = Decimal("1")` (`fake_exchange.py:62`): "there is no account to read one from". A futures position is `granted × 1 / alert price` in base units, so its notional equals the capital granted.
- **There is no step size, minimum quantity or minimum notional.** The simulated exchange has no instrument rules. The quantity is the full `Decimal` quotient, where a live adapter truncates down to the contract's step.
- **The quantity filled is the quantity the order asked for**, in full, in one fill, for a spot sell and for every futures order (`fake_exchange.py:199-202`).
- **What changes: only the spot buy.** Its quantity is `quote_amount / fill price` (`:197-198`): `granted` today, `granted / alert price` after this unit, which is the quantity a venue would return. Decision 43's finding T9 ("the SIZE is realistic") held for futures and for a spot sell, not for a spot buy. No spot pool is enabled in production.
- **What does not change: every futures quantity.** It was already sized with the alert's price. With the fill also at that price, `notional = quantity × price` now equals the capital granted, where today it equals the base quantity.
- **A close still nets to zero.** It is sized from the ledger's stored net and filled at exactly that quantity. A simulated fee is charged in USDT, never in the base coin, so it does not move the holding (§ E).
- **A dry run keeps sizing at 1x** (decision 45, answered 2026-10-04; § N, Q2). Nothing is built for it: `FAKE_LEVERAGE` stays 1. A dry-run operation's PnL and PnL % are what the reserved capital earns without leverage, one leverage-th of what the same alert would produce live at the venue's leverage (3x on the real round trip). The fee scales the same way, because it is charged on the notional. Sizing at the leverage the venue reports would be its own unit with its own design, and positions already written at 1x would keep their size.

### E. The fee: the venue's taker rate, on both sides, in USDT

Decided by the owner on 2026-10-04 (decision 45; § N, Q1). A simulated fill carries the venue's TAKER fee on the fill's notional, on the opening fill and on the closing fill, in USDT. A maker rate is never used: a simulated fill is a market order.

**The rates.**

| Exchange | Rate | Where the number comes from |
| --- | --- | --- |
| Bybit | `0.00055` (0.055%) | Verified: the real round trip of 2026-08-27 was charged it on both legs. Its fees, 0.05883625 USDT, are exactly `0.00055 × 106.975`, which is what two legs of 0.5 SOL at about 107 add up to. |
| Binance | `0.0005` (0.05%) | The owner's figure, read on the account on 2026-10-04. **Not confirmed by a real round trip in this project.** Its maker rate, 0.02%, is not used. |

**Where they live: a constant in infrastructure.** A new module, `execution/infrastructure/simulated_fee_rates.py` (layer: **infrastructure**/execution), holds `SIMULATED_TAKER_FEE_RATES`, a read-only mapping from exchange to `Decimal`, and `SIMULATED_FEE_CURRENCY = "USDT"`. Each entry carries its source and date in a comment; the Binance entry's comment says it is the owner's figure and is not yet confirmed by a real round trip. A test pins both values exactly.

- **Why a constant and not configuration.** The repository is the record. A rate changes only when the account's fee tier does, and that should be a dated, reviewed commit, so that a ledger row's fee can be explained from history. A setting would live in the VPS's `.env`, outside the repository, where a typo silently changes every simulated result, and it would add one more value whose absence has to be handled.
- **Why infrastructure.** It is a fact about two venues, read by an infrastructure adapter and wired by the composition root. `domain/` and `application/` gain nothing.

**How the fee is computed.**

- `fee = quantity × fill price × fee_rate`, on every fill. `fee_rate` is a constructor argument of `FakeExchangeAdapter`: **required, keyword-only, no default**, and refused when below 0 or when 1 or more. `main.py` passes `SIMULATED_TAKER_FEE_RATES[exchange]`.
- **Why no default.** A default of zero would be a way to charge nothing without anyone deciding to. With a required argument a construction that forgets the rate does not type-check. A test that does not care about fees says `fee_rate=Decimal("0")` in so many words (§ K).
- **Precision.** The product is taken inside a local `decimal` context of 60 digits and quantised to 18 decimal places, half-even: the scale of `ledger_entries.fee` (`NUMERIC(38, 18)`). So the fill carries exactly the value the column stores, and PostgreSQL rounds nothing. No venue rounding is imitated. A fee below `0.5e-18` quantises to 0, which the column's `fee >= 0` CHECK allows. A reader who recomputes `stored notional × rate` can differ from the stored fee by at most `1e-18`, because `notional` is itself stored rounded.
- **The base quantity is untouched.** The fee is in USDT on both sides, as on the real round trip, so a close sized from the ledger equals the open exactly and the allocation nets to zero.

**An exchange with no rate gets no simulated exchange. It is refused per signal, and the worker still starts.**

- Today a simulated exchange is built for every exchange that has a pool at startup, plus Bybit and Binance (`main.py:853-859`). After this unit it is built only for the exchanges of that set that have a rate. Bybit and Binance both have one, so the standing requirement that both are always covered still holds, and a test pins that the table contains both.
- An exchange left out is absent from the dry-run registry and from `tradable_pools`, which is computed from the simulated exchanges (`main.py:882-894`). So its pools are reported at startup by the existing unserved-pools WARNING, a second WARNING says why ("no simulated taker fee rate is defined for '<exchange>'"), and every signal on them ends `REJECTED` `UNTRADABLE_POOL` with its WARNING, before any capital is reserved (`process_signal.py:364-367`).
- **Why refuse per signal and not refuse the start.** It is the rule the composition root already follows for a pool nothing serves: a pool nobody trades is not a reason to stop the pools somebody does (`main.py:861-867`). It is also what live does: today the only exchange without a rate is Pionex, which has no live adapter either, so a dry run now refuses exactly what live refuses. A refused start would take Bybit's and Binance's rehearsal down over a pool that cannot trade in any mode.
- **It never charges zero silently.** The three ways to a zero fee are closed: the constructor has no default, the composition root reads the table by key, and an exchange outside the table has no simulated exchange to fill anything.
- **One thing this takes away, checked at deploy.** A rehearsal position open on an exchange with no rate could no longer be closed in dry run. Production's Pionex pools are disabled, so none is expected; the deploy's query of open rehearsal allocations (§ G) confirms it before the restart.

**A market not quoted in USDT is refused, not charged.** This is what happens to a simulated fill in a pool that does not settle in USDT.

- The simulated exchange is handed a symbol and never the pool, so it cannot know the settlement currency. What it can check is the market: before minting a fill it requires the symbol to be quoted in `SIMULATED_FEE_CURRENCY`, with the domain's own `base_currency_of(symbol, "USDT")`, which accepts `STXUSDT`, `STXUSDT.P`, `STX_USDT` and `STX_USDT_PERP` and raises for anything else. When it raises, `place` raises `ExchangeError`: no fill, the reservation released or the close marked FAILED, the signal `REJECTED`, one ERROR (the path of § F).
- **Why not a fee in the pool's settlement currency.** Rule 7: a fee is recorded in its own currency and never converted. The two rates are the venues' USDT-M futures rates; there is no verified rate for a BTC- or ETH-settled market, and on an inverse contract the fee is not `quantity × price × rate` at all. Inventing one would write a number no venue charges.
- **Why not a USDT fee in such a pool.** It would be a fee in a currency that is not the pool's. The performance read would leave it out of `pnl` and mark the row `fees_complete: false`, and the pool-wide position read would subtract it from the BASE holding as if it were coin, because that read nets every fee whose currency is not the settlement currency (P13). That is a wrong net position written on purpose.
- **Nothing that works today stops working.** A fill in a pool not settled in USDT cannot be recorded in either mode today: settlement asks for the settlement currency's USD rate, and the provider knows only USDT (P16). The refusal moves that failure from an endlessly retried settle job to one definitive ERROR at placement.
- **The limit that remains.** A USDT-quoted market traded from a pool that settles in another currency passes this check. That is a misconfiguration the opening path does not catch in either mode; its settlement fails as today (P16).
- **A spot-shaped order on Bybit or Binance** (a symbol with no contract marker) is charged the same rate. No spot pool exists on either: the only pools the product enables are the two USDT-M ones (P17). Stated as a limit (§ M).

**What the fee changes elsewhere.**

- **The ledger and `fees_complete`.** A USDT fee on a USDT-settled fill is complete. `derive_trade` subtracts a fee whose currency is the settlement currency from `pnl` and leaves `fees_complete` true (P15). None of the three position reads nets it (P13): it is neither in the base currency nor outside the settlement currency. So a USDT fee moves no holding, a close still equals its open, and the simulated venue book, which is seeded from the pool-wide read, is unaffected.
- **The USD rate at fill time.** Unchanged. `usd_rate_at_fill` is the settlement currency's rate, 1 for USDT, recorded once per settlement (P10). The fee is in that same currency, so the one rate on the row covers it. No performance read uses the rate.
- **Pool availability.** Unchanged (§ H). No real money pays a simulated fee.
- **Decision 43's list.** A rehearsal operation written after this unit shows a non-zero `fees`, and its `pnl` and PnL % are net of it. Its design expected this: "a simulated fee … arrives in `fees` and in `pnl` like any fee, with no change here" (its § J). Its classification reads prices only. Nothing in that design assumes a rehearsal fee of 0. Two places in its spec and tasks are narrower than the rows production will now hold; they are reported to the coordinator, not edited here (§ M).
- **Decision 28's mode guard.** Unchanged: it decides from origins and net base quantities, and a fee in USDT enters neither.

### F. An alert with no usable price

**What `signals.price` can hold, and what the ingress does today (P6, P7).**

| Alert's `price` | Ingress today | Reaches the worker? |
| --- | --- | --- |
| Missing, not a string, or not a number (`"abc"`, `""`) | 422 from the parser | no |
| `"0"` or negative | The row is refused by `ck_signals_price_positive`; the `IntegrityError` is re-raised; the webhook answers 500 and stores nothing | no, in production. Yes on an ORM-schema test database, which has no such CHECK. |
| `"NaN"` | `Decimal` parses it. PostgreSQL's numeric ordering puts NaN above every number, so `price > 0` does not exclude it. **Not verified against this database**; a test on a `head` schema settles it (§ K). | possibly |
| `"Infinity"` | `Decimal` parses it. A `NUMERIC(38, 18)` column cannot hold an infinity, so the insert should fail like the CHECK does. Not verified; the same test settles it. | expected no |
| Positive but absurd (the wrong chart, a mistyped alert) | stored | yes |

**What the simulated exchange does.** A price is **usable** when it is a finite `Decimal` above zero. The test is `price.is_finite() and price > 0`, in that order, because comparing a NaN raises.

| Case | Behaviour | Path |
| --- | --- | --- |
| An OPEN whose price is zero, negative or NaN | Unchanged, and the same in both modes: the domain refuses to size the order before the simulated exchange is asked to fill anything (P8) | `build_open_order` raises; no fill |
| A CLOSE whose `reference_price` is `None`, zero, negative, NaN or infinite | **Refused. No fill is minted.** | `place` raises `ExchangeError`; `ClosePosition` marks the attempt FAILED, records `CLOSE_REJECTED_BY_VENUE` on the signal when there is one, and logs its existing ERROR, which reaches Telegram (`close_position.py:242-266`). The position stays open in the ledger. TradingView believes it flat, so no second closing alert comes; the strategy's next OPENING alert on that market finds the holding, the simulated venue book still shows it, and the existing real-orphan path closes it at that alert's price before opening (`process_signal.py:521-558`). |
| Any order the simulated exchange did not build itself (no price was remembered for its client order id) | Refused the same way | `place` raises `ExchangeError`; for an open, `PlaceOrder` releases the reservation and records `ORDER_REJECTED_BY_VENUE` (`place_order.py:219-246`) |
| An order on a market not quoted in USDT, whatever its price | Refused the same way: the fee has no verified rate outside USDT (§ E) | `place` raises `ExchangeError`, with the two outcomes above |
| A positive but absurd price | Filled at it. It is the price the alert carried, which is what decision 45 asks for. | — |

- **There is no fallback: not to 1, not to the entry price, not to the last price seen.** A fallback to 1 would silently write the rows this decision exists to stop writing. Any other fallback would write a price no alert carried, and decision 43's list would call it nothing in particular.
- **The refusal is raised in `place`, not in `build_close_order`.** A plain exception from the build is retried by the job until its attempts run out, and `OrderNotPlaceable` would be reported as dust with a venue minimum. `ExchangeError` from `place` is the definitive-rejection path both use cases already handle: one ERROR, an outcome on the signal, no retry storm.
- **No new reason code.** The detail carries the cause ("the simulated exchange cannot price this order: its alert carried no usable price"), under the existing codes.
- **Where a rehearsal now differs from live.** A live close ignores the alert's price entirely; a simulated close needs it. In production the only stored value that can be unusable is a NaN (if the test of § K shows it can be stored). Stated as a risk (§ M).

### G. The transition

- **What happens.** A dry-run position that is open when this unit is deployed was entered at 1 and will be closed at its closing alert's price. Its quantity is `granted / entry alert price`, so its PnL is `quantity × (exit alert price − 1)` for a long and the negative of that for a short: of the order of the granted amount, with a sign that depends on whether the market trades above or below 1. Its closing fill also carries a fee and its opening fill, written before this unit, does not. It is a number with no meaning.
- **Who reads that PnL.** Decision 43's list, which marks the row "fixed price", draws it in neutral ink and keeps it out of every total (its § C, § K). Nothing else: every performance total drops rehearsal fills, and no other module reads a fill's price (P11, P13).
- **Nothing is corrupted and nothing needs repair.** The ledger is right about what the simulated exchange did.
- **Should the owner do anything before the deploy? No.** The alternative is to wait for a moment when no dry-run position is open. Waiting costs alert-priced history that can never be recovered, which is the reason decision 45 exists, and it buys the absence of rows that are already marked and counted nowhere. The owner can still choose the moment: it is a deploy, and the owner runs it.
- **What the deploy records.** The delivery log notes the commit, the time of the first worker start on it, and the rehearsal allocations open at that moment (a read-only query the tasks phase writes), so the rows that straddle the change are known by id. The same query is run BEFORE the restart and gates it on one point: if any open rehearsal allocation sits on an exchange that has no fee rate, the deploy stops and the case is reported, because that position could no longer be closed in dry run (§ E). None is expected: production's Pionex pools are disabled.
- **An order in flight at the restart** (placed, not yet settled) is lost with the simulated exchange's memory and ends `ORDER_NEVER_REACHED_EXCHANGE`, as at every restart today (P9). Unchanged by this unit.

### H. Impact on `DRY_RUN`, idempotency and capital-pool isolation

| Rule | Impact |
| --- | --- |
| `DRY_RUN` (rule 1) | The default stays true. `DRY_RUN` still selects the adapter and nothing else does (`main.py:809-815`). `is_live`, `assert_dry_run_safe`, the mode guard and both rehearsal id prefixes are untouched. No test needs a credential or the network. |
| `DRY_RUN=false` | Behaves exactly as before. The simulated exchange is not registered. The real adapters receive one field they never read (§ B), and a test pins their requests. |
| Idempotency (rule 2) | Untouched. The client order id is still minted before any network call; the remembered price is keyed by it. The signal's idempotency key and the unique constraints on reservations and attempts are not involved. |
| Webhook (rule 3) | Untouched. The ingress is not edited. |
| Allocation transaction (rule 4), lock order | Untouched. No new lock, no new transaction boundary, no new read inside the advisory lock. |
| **Capital pools (rule 5)** | **A simulated profit or loss cannot change a pool's availability, a balance snapshot, a reservation or anything the allocation engine reads.** Dry-run balances come from the real venue, read with the stored key, in both modes (P11). Availability is that snapshot minus the active reservations. A rehearsal fill moves no real money, so the snapshot does not move, and nothing in `allocation/` or `accounts/` reads `ledger_entries.price`, `notional` or a PnL. What follows is already true today and stays true: in dry run an open rehearsal position does not reduce availability once its reservation is FILLED, so a dry run rehearses routing and results, not capital contention. |
| Ledger (rule 6) | Append-only, unchanged. A rehearsal fill is still one row per fill with its `strategy_id` and `allocation_id`. No row is rewritten. |
| PnL in native currency (rule 7) | The price is in the settlement currency per unit of base, as a live fill's is. `usd_rate_at_fill` is recorded exactly as today. The simulated fee is in USDT and is charged only on a USDT-quoted market; any other market is refused, never charged in another currency and never converted (§ E). Nothing is summed across pools. |
| What a dry run serves | Narrower than today in one respect: an exchange with no fee rate has no simulated exchange, so its pools are refused per signal, as they are live (§ E). Bybit and Binance are unaffected. |
| Credentials (rule 8) | Untouched. The simulated exchange signs nothing. |
| A rehearsal fill never looks like a real one | The `fake-fill-` and `fake-order-` prefixes are unchanged, and the tests that pin them are not edited (`tests/execution/infrastructure/test_fake_exchange.py:191-256`). One thing does change: a rehearsal row used to be recognisable by its price of 1 as well. After this unit the prefix is the ONLY marker, so every reader must use it. The two that total anything already do (decision 43 § C). |
| Reconciliation | Skipped under `DRY_RUN` (P5). The simulated venue book is fed signed base quantities, never a price (P9). No discrepancy can come from a simulated price. |

### I. Layering

| Component | Layer | File | Change |
| --- | --- | --- | --- |
| `CloseOrderSpec.reference_price` | **application**/execution | `execution/application/ports.py` | One optional field, default `None`. `ExchangePort` itself is not changed. |
| `CloseCommand.reference_price`; `ClosePosition.close` | **application**/execution | `execution/application/close_position.py` | One required field; passed into the spec. No other line. |
| `_handle_releases`; the `CloseOrphansPort` protocol; the call in `_handle_consumes` | **application**/signals | `signals/application/process_signal.py` | `context.price` passed to both. |
| `CloseOrphans.close` | **application**/signals | `signals/application/close_orphans.py` | A required keyword argument, passed into `CloseCommand`. |
| `FakeExchangeAdapter` | **infrastructure**/execution | `execution/infrastructure/fake_exchange.py` | `fill_price` becomes `Decimal` or `None`, default `None`; the remembered prices; the usable-price refusal; `fee_rate`, required and keyword-only; the fee and its quantisation; the USDT-quote refusal; a read-only `fixed_fill_price`; one INFO per fill (§ J). |
| `SIMULATED_TAKER_FEE_RATES`, `SIMULATED_FEE_CURRENCY` | **infrastructure**/execution | `execution/infrastructure/simulated_fee_rates.py` (new) | The two rates and the fee currency, each with its source (§ E). |
| The simulated exchanges built per exchange that has a rate; the two startup lines | **composition root** | `main.py` | `fee_rate=SIMULATED_TAKER_FEE_RATES[exchange]`; an exchange outside the table gets none and a WARNING (§ E, § J). The block keeps the name `fakes_by_exchange` and still names Bybit and Binance. |
| `Fill`, `futures_position_size`, `PlaceCommand`, `OpenOrderSpec` | domain and application | their files | Docstrings only. They say a fill's price is never the alert's reference price; that stays true of a live fill and is now false of a rehearsal one. |

- **`domain/` gains no import and no code.** No order type, no domain function and no domain class changes.
- **No new component in `domain/` or `application/`.** The usable-price test and the fee product are private functions of the adapter that uses them. The USDT-quote check calls the existing domain function `base_currency_of`, which the adapter's module already imports from.
- **The two modes of the simulated exchange.**

  | `fill_price` | Meaning | Who uses it |
  | --- | --- | --- |
  | `None` (the default) | Each order fills at the price remembered for it | production, and any test that wants production's behaviour |
  | a `Decimal` | Every order fills at that price, as today | tests that pin a price explicitly |

### J. What fails here without a log line?

| Failure | What happens | What is logged |
| --- | --- | --- |
| **The price did not arrive**: a close built with `reference_price=None`, or an order the simulated exchange did not build | Refused in `place`; no fill; the attempt is FAILED; the signal, when there is one, ends `REJECTED` | The existing ERROR of the caller (`close rejected by venue…` or `order rejected by venue…`), with the cause in its `error=` text. It reaches Telegram. |
| **A price of zero, negative or NaN on a close** | The same refusal | The same ERROR; the text names the value |
| **A price of zero, negative or NaN on an open** | The domain raises at build; the job is retried until its attempts run out; the signal then ends `REJECTED` through the exhausted-job recorder | The worker's existing exception line per attempt. Not changed here (§ M). |
| **A close with no alert, for an orphan** | The same refusal; the attempt is FAILED; the continuation sees the FAILED close and ends the waiting open with its own outcome | The same ERROR. No outcome is written by the close itself, by design (P4). |
| **Production builds the simulated exchange with a fixed price** (a later edit of `main.py`) | Every fill is priced at it and decision 43's list reads `UNDETERMINED` or `FIXED_ONE` | One line at worker start, per process, taken from each instance's own `fixed_fill_price` and rate: INFO "the simulated exchange prices each fill at its alert's price", with each exchange and its taker rate, when none is fixed; WARNING naming the exchange and the price when one is. And the end-to-end test of § K goes red. |
| **A later edit rounds the price** | Rows read `UNDETERMINED` | Nothing at write time can know. The exactness tests of § K go red, and decision 43's list logs an INFO count of `UNDETERMINED` rows per page (its § G). |
| **The moment the change took effect is not visible** | — | The startup INFO above, and one INFO per simulated fill: exchange, symbol, side, quantity, price, fee, client order id. |
| **An exchange has a pool and no fee rate** | It gets no simulated exchange; every signal on its pools ends `REJECTED` `UNTRADABLE_POOL` before any reservation | At worker start: the existing unserved-pools WARNING, and one WARNING naming the exchange and the reason ("no simulated taker fee rate is defined"). Per signal: the existing `UNTRADABLE_POOL` WARNING. |
| **A simulated fill is charged no fee** | Cannot happen unnoticed: the constructor has no default rate, the composition root reads the table by key, and the table's two values are pinned by a test | The startup INFO line names each simulated exchange with its rate, so the journal shows what was charged from which start |
| **An order on a market not quoted in USDT** | Refused in `place`; no fill | The caller's existing ERROR, with the cause in its `error=` text ("the simulated exchange charges its fee in USDT and this market is not quoted in it") |
| **The account's fee tier changes and the constant does not** | New rehearsal fills carry the old rate | Nothing can log it. The constant's comment carries its date and source, and the per-fill INFO shows the fee charged. Stated as a risk (§ M). |
| **A remembered price is never used** (the build succeeded and the place never ran) | One `Decimal` stays in memory until the process restarts | Nothing. Bounded by the number of such failures; the fills kept per order already grow the same way (P9). |
| **A worker restart between place and settle** | The order is forgotten; the existing `ORDER_NEVER_REACHED_EXCHANGE` | The existing WARNING. Unchanged. |

No line of this unit carries a credential, a DSN, a token or a raw payload. They carry ids, the exchange, the symbol, the side, and a quantity, a price and a fee of a simulated fill.

**Threat matrix.** N/A: no routing, shell, subprocess, VCS automation, executable-file classification or process integration. No route is added.

### K. Testing strategy

| Layer | What | How |
| --- | --- | --- |
| Unit, infrastructure | The simulated exchange in both modes: the price per kind of order, the refusals, the fee, the quantity of a spot buy | `tests/execution/infrastructure/test_fake_exchange.py`, no database |
| Unit, application | `ClosePosition` passes the price into the spec; `_handle_releases` and `CloseOrphans` pass the alert's price | The existing stub exchanges and fakes of those suites |
| Unit and wire, real adapters | The requests are unchanged | A new test file; the adapters' existing doubles, and `httpx.MockTransport` with the frozen clock |
| Integration, **real PostgreSQL** | From the webhook to the ledger, through the production composition root | `build_worker_runner(session_factory_override=…)` and `run_once`, as `tests/signals/infrastructure/test_exhausted_jobs_wiring.py` does |
| Integration, **`head` schema** | What `signals.price` can hold | `tests/pg_head_schema.py` |

**The tests.**

1. **An opening fill equals the alert's price to the last decimal place.** A futures open built with `price=Decimal("0.123456789012345678")` and placed: `fill.price == Decimal("0.123456789012345678")`, compared as `Decimal` and as `str`. One case per kind of order of § A.
2. **From the webhook to the ledger, the stored price is read back.** A POST to `/webhook/tradingview` with `"price": "0.1234567890123456789"` (19 places) and `"symbol": "STXUSDT.P"`; the worker's `signal.process` and `execution.settle` jobs run through `build_worker_runner` with `DRY_RUN` on. Then, read from the database: the opening row's `ledger_entries.price` equals `signals.price` of the signal its reservation names, exactly, and its `exchange_fill_id` starts with `fake-fill-`. A closing alert at another price follows; the closing row's price equals that second signal's price, and the allocation nets to zero. Each of the two rows carries `fee_currency` `"USDT"` and a fee equal to its quantity times its price times `0.00055`, quantised to 18 places, and `derive_trade` over the two rows answers `fees_complete` true and a `pnl` net of both fees. The fixture seeds a balance snapshot young enough for the refresh's fallback, because no credential exists in a test.
3. **A close is priced at the closing alert, not at the opening one.** Opening alert 0.4512, closing alert 0.4633: the closing fill is 0.4633.
4. **A REVERSE.** The close of the old allocation and the open of the new one are both priced at the reversing alert's price, and the new allocation's opening fill equals the price of the signal its reservation names.
5. **An orphan close** is priced at the price of the signal that found the orphan, although its `signal_id` is `None`.
6. **Two orders built before either is placed, placed in the other order,** each fill at its own price.
7. **The refusals of § F**, one case each: `None`, 0, a negative, NaN, infinity, and an order the adapter did not build. Each asserts the exception type, that no fill exists for the client order id, and, through `ClosePosition` on real PostgreSQL, that the attempt is FAILED, the signal `REJECTED` `CLOSE_REJECTED_BY_VENUE`, the ledger unchanged and the ERROR line present. Then a second `ClosePosition.close` for the same allocation, with a usable price, is placed and nets it to zero, which is what the orphan path does at the next opening alert.
8. **The fee.** With `fee_rate=Decimal("0.00055")`: `fill.fee` equals `quantity × price × 0.00055` quantised to 18 places, in `"USDT"`, on an open and on a close; the base quantity is untouched and the close nets to zero. A case whose product has more than 18 decimal places pins the half-even quantisation, and one whose product exceeds 28 significant digits pins that nothing was rounded before it. With `fee_rate=Decimal("0")` the fee is 0. A rate below 0 or of 1 is refused by the constructor.
9. **A spot buy** fills `granted / alert price` in base units.
10. **The real adapters are untouched** (§ B). Per real adapter: the same close built from a spec with and without `reference_price` gives equal orders and identical recorded calls. Per registered adapter, on the wire: identical method, path, query, body bytes and signature.
11. **`head` schema.** `signals.price` refuses 0 and a negative. The same test records what the database does with `NaN` and with `Infinity`; the design holds either way, and the result corrects § F's two unverified rows.
12. **The startup line** says INFO with no fixed price, naming each exchange and its rate, and WARNING with a fixed price.
13. **The rates table.** `SIMULATED_TAKER_FEE_RATES` holds exactly Bybit at `Decimal("0.00055")` and Binance at `Decimal("0.0005")`, and `SIMULATED_FEE_CURRENCY` is `"USDT"`.
14. **An exchange with no rate.** A worker built under `DRY_RUN` with a pool on an exchange outside the table: no simulated exchange exists for it, both WARNINGs are logged at build time, Bybit and Binance still have theirs, and a signal on that pool, run on real PostgreSQL, ends `REJECTED` `UNTRADABLE_POOL` with no reservation and no ledger row.
15. **A market not quoted in USDT** is refused in `place` (`ETHBTC`, `BTCUSD`), with no fill; each of the four USDT spellings (`STXUSDT`, `STXUSDT.P`, `STX_USDT`, `STX_USDT_PERP`) is filled and charged.
16. **A USDT fee is complete and moves no holding.** Through the production write path on real PostgreSQL: after a simulated open with a non-zero fee, the allocation's net base equals the quantity bought, the pool-wide net position equals it too, and after the close both are zero.

**Rules that bind the task breakdown.**

- **Strict TDD.** Each RED fails on an ASSERTION. The new default is first a stub that still fills at 1 (`assert Decimal('1') == Decimal('0.123456789012345678')`); `reference_price` is first a field the simulated exchange accepts and ignores; `fee_rate` is first accepted and ignored, so the fee test fails on `assert Decimal('0') == …`; the rates module is first a table with both rates at 0. A refusal test captures the exception and asserts on its type, so a stub that does not raise fails on an assertion.
- **The tests that take today's default.** 33 construction sites (P14).

  | Group | Sites | What happens |
  | --- | --- | --- |
  | Pass an explicit `fill_price` (100 or 2) | 12 | **Kept as they are.** An explicit price is the fixed mode, which is today's behaviour. |
  | Take the default and never produce a fill | 4 (`test_fake_exchange.py:48`, `test_dry_run_invariant.py:27, 42, 49`) | Unchanged, apart from the rate argument below. |
  | Take the default and fill orders | 17 (`test_order_outcomes_integration.py`, 4; `test_settle_outcomes_integration.py`, 13) | Their opens go through `PlaceOrder` with `price=Decimal("2")` and now fill at 2 instead of 1. None asserts a price, so none changes for an open. Their closes go through `CloseCommand`, which gains the required field. |

  - **The rule.** No test is deleted. A test whose subject is not the price keeps its assertions. A test found, when the suite runs, to depend on a fill of 1 is given `fill_price=Decimal("1")` explicitly, and its docstring says why. The task records each such test by name.
  - **The fee: no assertion changes, every construction site says its rate.** The number of tests that assert a simulated fee of 0 today is **zero** (P14). `fee_rate` is required, so all 33 construction sites, and each instantiation of the two test subclasses (`CountingFakeExchange`, `_DustExchange`), gain `fee_rate=Decimal("0")`: they are kept with an explicit zero rate, because none of them is about the fee. No test is deleted and none loses an assertion. A test found, when the suite runs, to depend on a zero fee without asserting it (a PnL or a balance computed from fills) keeps its explicit zero rate and is recorded by name. The new fee tests pass their own non-zero rate.
  - **Edits that the new required field forces:** the 5 constructions of `CloseCommand` in tests (`test_close_position.py`, 2; the three integration files, 1 each), every call of `CloseOrphans.close` in `tests/signals/application/test_close_orphans.py`, and the doubles of `CloseOrphansPort`. Each gains a price; none loses an assertion.
  - **Two tests read `main.py` as text** (`tests/test_main_pool_reload.py:260-267`, `tests/test_mode_guard_wiring.py:28`). This unit edits the `fakes_by_exchange` block. The first of those tests reads the text between `fakes_by_exchange = {` and `tradable_pools` and requires both `BYBIT_EXCHANGE` and `BINANCE_EXCHANGE` in it, so the block keeps its name and both names, and test 13 is what now guarantees that both have a rate.
  - **Tests that build the worker with a pool on an exchange outside the table** (a Pionex pool under `DRY_RUN`) change behaviour: that pool is no longer served. They were not counted here; the task finds them by running the suite, and each is either moved to a Bybit or Binance pool or turned into a case of test 14. None is deleted.
- **No lock-hold harness applies.** This unit adds no lock and no transaction boundary. The remembered price is written and popped inside one use-case call on one instance, with distinct keys per order.
- **Symbol spellings.** The webhook side uses TradingView's `STXUSDT.P`. The strategy's allowed pair is stored as `STXUSDT`. The ledger row is asserted through `market_key(symbol) == "STXUSDT"`, never by comparing the two spellings as text, and the simulated venue book is asserted under the venue's bare `STXUSDT`. The real-adapter test hands the adapter `STXUSDT.P` and asserts the request names `STXUSDT`.
- **Mutations that prove the tests which pass at once.**

  | Test | Mutation that must turn it red |
  | --- | --- |
  | The real adapters' requests are identical with and without `reference_price` (10) | The adapter forwards `spec.reference_price` into its request |
  | The 12 tests with an explicit `fill_price` still fill at it | The fixed price ignored whenever a price was remembered |
  | Two orders, each at its own price (6) | One "last price" attribute instead of a map keyed by client order id |
  | Exactness at 18 places (1) | The price quantised to 2 places in the adapter |
  | Webhook to ledger (2) | `main.py` builds the simulated exchange with `fill_price=Decimal("1")` |
  | A close at the closing alert's price (3) | The simulated exchange reuses the price it remembered for the opening order |
  | A refused close writes no ledger row (7) | A fallback to 1 in place of the refusal |
  | The fee is on the notional (8) | The fee computed from the quantity alone |
  | The fee is quantised to 18 places, half-even (8) | The quantisation removed; and, separately, the product taken in the default 28-digit context |
  | Binance is charged the taker rate (13) | `0.0002`, the maker rate, in its place |
  | An exchange with no rate has no simulated exchange (14) | The table read with a default of zero |
  | A market not quoted in USDT is refused (15) | The quote check removed |
  | A USDT fee moves no holding (16) | The fee written in the base currency |
  | The webhook-to-ledger fee (2) | `main.py` passes `fee_rate=Decimal("0")` |
  | The rehearsal prefix tests (existing, unedited) | Their own, already recorded |

- **Gate after the unit.** `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`. No frontend change.

### L. Delivery

**One PR** to `main`, cut from an up-to-date `main`, never stacked. It is not split, and the reason is not size: an exchange that prices opens at the alert and cannot yet price closes has no honest state to be deployed in. Its closes would have to be refused or filled at 1.

| | |
| --- | --- |
| Contents | The simulated exchange's two modes, the remembered price, the refusals, `fee_rate` and the fee; the rates module; `CloseOrderSpec.reference_price`; `CloseCommand.reference_price` and its two callers; the composition root's wiring of the rates and its startup lines; the docstrings; the tests of § K. |
| Risk | **Medium.** It edits a DTO of `ExchangePort` and the two use cases that close a position, in the module that sends real orders when `DRY_RUN` is false. What bounds it: no order type changes, no real adapter file is edited, and the request test. |
| Migration | None. |
| Deploy | First the read-only query of open rehearsal allocations, which gates the restart (§ G). Then pull as `strategy`, restart both services. Only the worker's behaviour changes; the API process places no orders. |
| From which moment | The first worker start on the new commit. Every fill minted after it carries its alert's price and its venue's taker fee. The startup INFO line marks the moment in the journal and names the rates. |
| What the operator sees | In the log: the startup line, then one INFO per simulated fill with its price and fee. In the panel: nothing until decision 43's list is served (PR 12e-2); then operations opened after this deploy read "alert price" and show a simulated result net of fees, those opened before it read "fixed price", for good. |
| Rollback boundary | A revert restores the fixed price of 1 and the fee of 0 for NEW fills. The fills written meanwhile keep their alert price and their fee. A dry-run position open across the revert has an alert-priced entry and an exit of 1, and decision 43's list reads it `ALERT` (its § K names this case). No data is touched in either direction. |
| Order against PR 12e | Independent (decision 43 § I). No shared file: this unit edits `execution` and `signals`, 12e-1 edits `performance`. Whichever is ready is merged and deployed first, then the next branch is cut from the updated `main`. This one should go first if it is ready, for the owner's reason: each day without it writes fills at 1. |

- **Forecast.** 900 to 1,400 authored lines, tests about four times the production code; the 33 one-line `fee_rate=Decimal("0")` edits are part of it. `Decision needed before apply: No` (both questions of § N are answered) · `Chained PRs recommended: No` · `400-line budget risk: High`.
- **The spec.** No spec of this change speaks of how a simulated fill is priced or charged, and `openspec/specs/trade-execution/spec.md` § "DRY_RUN Safety" says only which adapter is used. The spec phase must add a trade-execution delta to this change, each requirement naming its pool:
  - a simulated fill in pool `(bybit, usdt-m, USDT)` or `(binance, usdt-m, USDT)` is priced at the stored price of its alert, exactly, and a close at the alert that caused it;
  - it carries the taker fee on its notional in USDT, `0.00055` in the first pool and `0.0005` in the second, on both sides, quantised to 18 places, and never a maker rate;
  - an order with no usable price, or on a market not quoted in USDT, is refused and never filled at a default;
  - under `DRY_RUN` an exchange with no fee rate serves no pool, and its signals are refused as untradable before any reservation;
  - a dry run sizes at 1x;
  - rehearsal ids keep their prefixes, and a real adapter's requests do not depend on the price.

  The performance and admin-api specs need no new requirement. Two existing statements there, and one in tasks.md, are narrower than what production will hold; see § M.

**Design decisions made here** (not owner decisions; each has its reason above):

| # | Decision | Section |
| --- | --- | --- |
| E1 | The simulated exchange remembers the price between its own build and its own place, keyed by client order id; nothing outside it changes for an open | B |
| E2 | A close carries the price as `CloseOrderSpec.reference_price`, optional on the spec, required on `CloseCommand` | B |
| E3 | A close is priced at the alert that caused it; an orphan close at the alert that found the orphan | B |
| E4 | No order type and no real adapter is edited; a test pins the real adapters' requests | B, K |
| E5 | No rounding, tick or slippage in the simulated exchange; the fill equals the stored alert price exactly | C |
| E6 | No instrument rule is simulated in this unit. (Leverage stays 1 by the owner's answer, not by this design.) | D |
| E7 | The fee is `quantity × price × fee_rate`, quantised to 18 places half-even, in USDT; `fee_rate` is a required constructor argument with no default | E |
| E12 | The two rates are constants of an infrastructure module, not configuration | E |
| E13 | An exchange with no rate gets no simulated exchange and is refused per signal; the worker still starts | E |
| E14 | A market not quoted in USDT is refused in `place`, never charged in another currency | E |
| E8 | An order with no usable price is refused in `place` through the existing rejection path; no fallback | F |
| E9 | An explicit `fill_price` stays as a fixed mode for tests; the default becomes the alert's price | I, K |
| E10 | The deploy does not wait for dry-run positions to close | G |
| E11 | One PR | L |

### M. Risks, and what could be wrong in this design

| Risk | Why it matters | Mitigation or honest limit |
| --- | --- | --- |
| The real adapters now receive a field that carries a price | A later edit could send it, turning a market order into something else | They never read it today; the request test and its mutation; the field's name and docstring; no order type carries it, and `place` sees only the order |
| A rehearsal fill is now plausible | Its price of 1 was an incidental second marker. Any reader that forgets the prefix would take a rehearsal row for a result. | The prefix contract is unchanged and pinned. Both totalling readers use it. Stated in § H so a new reader is written with it. |
| The simulated result is at 1x, with no step, no spread and no slippage, filled in full at the bar's close | It is what the alert's own prices imply, not what a venue would have filled. A live market order fills after the alert, at the book. At 3x a live PnL is three times the simulated one, and so is a live fee. | Stated (§ D). The owner chose 1x (§ N, Q2). The rest is the meaning of "the price the alert carried". |
| A delayed open is filled at an old price | The open half of a REVERSE and a deferred open are placed after their close settles, up to the continuation's timeout later, at the alert's price | By decision 45 the price is the alert's. Live, the same order would fill at the market of that later moment. |
| A simulated close can be refused where a live one would not be | A live close never reads the alert's price | Reachable in production only through a stored NaN, if one can be stored (§ F, test 11). The refusal is an ERROR that reaches Telegram, and the strategy's next opening alert closes the position through the orphan path. Until then the rehearsal position stays open, which also keeps decision 28's guard from allowing a switch to live. |
| One class, two modes | A fixed price wired in production silently restores the old behaviour | The startup line reads each instance's own mode; the end-to-end test runs the production composition root (§ J, § K) |
| The simulated fee exists only in USDT | A pool settled in another currency cannot be rehearsed | Its fills are refused, not charged in a currency no rate was verified for (§ E). Nothing is lost: such a pool cannot settle a fill in either mode today (P16), and the product enables none (P17). |
| A USDT-quoted market traded from a pool that settles in another currency | The quote check passes and a USDT fee is minted | A misconfiguration the opening path does not catch in either mode; its settlement fails as today (P16), so no such row reaches the ledger. |
| The Binance rate is not confirmed by a real round trip | It is the owner's figure read on the account | Said where the rate is defined (§ E). The first real Binance round trip confirms or corrects it; a correction is a one-line commit and applies to new fills only. |
| A rate is a constant and an account's fee tier can change | New rehearsal fills would carry a stale rate, and rows already written keep theirs | The comment carries the date and source; the per-fill INFO shows what was charged. A change is a dated commit, which is the point of a constant (§ E). |
| A spot-shaped order on Bybit or Binance is charged the futures taker rate | A symbol with no contract marker builds a spot order in the simulated exchange, and a spot taker rate is higher | No spot pool exists on either exchange (P17). An alert that names a futures market without its `.P` is the one way there, and its fee is then the right one. |
| A dry run serves fewer pools than before | An exchange with no rate is refused per signal, where today it is filled | It is what live does, and today that exchange is Pionex, whose pools are disabled. The deploy checks that no rehearsal position is open on such an exchange (§ G). |
| Rehearsal fills written before this unit have a fee of 0 and those after it do not | A reader comparing two rehearsal rows compares a result with fees against one without | Decision 43's "fixed price" mark already separates them: every fee-less rehearsal fill is a fixed-price one, except the opening fill of a position that straddles the deploy (§ G). |
| The remembered prices and the minted fills live in memory | A restart between place and settle loses the order | Existing behaviour, with its existing WARNING and outcome (§ G) |
| A dry-run position open at the deploy shows a large meaningless PnL | Of the order of the granted amount, in either direction | Marked and outside every total by decision 43; recorded by id in the delivery log (§ G) |
| A revert with a dry-run position open | An alert-priced entry with an exit of 1 reads `ALERT` | Named in decision 43 § K. The fills table shows the exit at 1. |
| Dry run does not rehearse capital contention | A rehearsal position does not reduce availability, so two strategies never compete in dry run as they would live | Existing, and not changed here (§ H). A result per operation is simulated; the allocation between strategies is not. |

**What could be wrong here.**
- **Nothing was run.** Every count in P14 and § K comes from a search of the test tree, not from the suite. The task that changes the default must run the suite and record what turned red.
- **The two unverified rows of § F** (`NaN`, `Infinity`) rest on PostgreSQL's documented behaviour, not on a statement run against this database. Test 11 settles them; the design refuses both either way.
- **The end-to-end test's fixture** (a balance snapshot that lets the refresh fall back with no credential) was read from `main.py:1047-1131` and `process_signal.py:588-605`, not exercised.
- **Binance's taker rate** is the owner's figure. Nothing in this repository confirms it.
- **The tests that build the worker with a pool outside the rates table** were not counted (§ K). If there are many, E13 costs more test edits than this design says.
- **The real round trip's two notionals** are inferred: its fees divided by the rate give 106.975, which fits two legs of 0.5 SOL. The legs' own prices are not in the repository's documents.

**What the fee does to decision 43's unit. Reported, not edited.** Its design holds: § J of that addendum expected a simulated fee to arrive in `fees` and `pnl`, and its classification reads prices only. Three statements outside this addendum are narrower than the rows production will hold once this unit is deployed:
- `specs/admin-api/spec.md`, scenario "A rehearsal row's classification is served as stored data implies": its GIVEN fixes only the opening fill (priced 1 against an alert of 0.4512) and its THEN requires `pnl` 0. That holds only when the closing fill is also at 1 with no fee. A position that straddles this unit's deploy is `FIXED_ONE` too, with an alert-priced exit, a fee on its closing fill and a `pnl` that is not 0. The GIVEN needs "and whose closing fill is priced 1 with no fee".
- `specs/performance-reporting/spec.md`, "Rehearsal Operations Are Listed Only On Request": "while the simulated exchange fills every order at a price of 1 with no fee, a rehearsal row reads … fees 0 and PnL 0". True as a conditional, and dated from this unit's deploy. Its scenario and the panel spec's "A fixed-price row shows its stored numbers" state their fills in the GIVEN and stay correct.
- `tasks.md`, the check after PR 12e-1's deploy: it expects every dry-run operation to read `FIXED_ONE` with entry 1, exit 1 and PnL 0. If this unit is deployed first, as § L recommends, production may by then hold `ALERT` rows with fees and a non-zero PnL, and a straddling `FIXED_ONE` row.

**Adjacent, flagged and not designed.**
- **An opening alert with an unusable price is retried, not refused** (P8): the `InvariantViolation` leaves `PlaceOrder` uncaught after the reservation was taken, so the job repeats until its attempts run out and the reservation waits for its TTL. It is the same in both modes and predates this unit. In production the CHECK on `signals.price` makes it nearly unreachable.
- **The webhook answers 500, not 422, to a price of zero or a negative** (P7). An ingress matter.
- **The panel's sentence for an alert-priced row** ("opened at the price its alert carried", decision 43 § F) does not say that the row is sized without leverage or that its fees are simulated at the venue's taker rate. With 1x now decided, unit 9p.5 may want to say both. It is copy of that unit, not of this one, and no part of this unit waits for it.

### N. Questions for the owner: all answered (2026-10-04)

Two were asked, and the owner answered both on 2026-10-04. They are kept here with their answers so that the reasoning stays beside the design. The record is owner-decisions.md, decision 45's lines of 2026-10-04. No migration is needed, so no question about one was asked. **No question is open, and folding the answers in raised no new one.**

- **Q1. What fee does a simulated fill carry?** The choice was between *(a)* none, as before this unit, and *(b)* the venue's taker rate on the fill's notional, on both sides, in USDT. The design recommended (b) and asked for a Binance rate, because none was verified in this project.
  - **Answered 2026-10-04: (b), with both rates given.** A simulated fill carries the venue's TAKER fee, on the fill's notional, on both sides, in USDT. **Bybit `0.00055`** (0.055%), the rate of the real round trip of 2026-08-27. **Binance `0.0005`** (0.05%), the futures taker rate the owner reads on the account. Binance's maker rate, 0.02%, is not used: a simulated fill is a market order.
  - **The Binance rate is the owner's figure**, not confirmed by a real round trip in this project. That is said where the rate is defined (§ E).
  - **Why:** a result with no fee overstates every operation, and a fee, like a price, is written once.
  - **How it is met:** two constants in a new infrastructure module, a required `fee_rate` on the simulated exchange, and a fee of `quantity × price × rate` quantised to 18 places (§ E). The fee is no longer optional anywhere in this design.
  - **What the answer left to the design, and how it was settled:** an exchange with no rate gets no simulated exchange and is refused per signal, with the worker still starting; a market not quoted in USDT is refused rather than charged in another currency (§ E). Neither is a product decision: the first follows the composition root's own rule for a pool nothing serves, the second follows rule 7.
- **Q2. At what leverage does a dry run size a position?** The simulated exchange sizes at 1x: the position's notional equals the capital granted. The choice was between *(a)* keeping 1x, *(b)* a fixed multiple per exchange set in configuration, and *(c)* the leverage the venue reports, read with the stored key. The design recommended (a) for this unit.
  - **Answered 2026-10-04: (a).** A dry run keeps sizing a position at 1x. A dry-run operation's PnL and PnL % are one leverage-th of what the same alert would produce live at the venue's leverage (3x on the real round trip). A result at 1x is exact, depends on no venue read, and can be scaled by eye.
  - **Nothing is built for it** (§ D). Sizing at the leverage the venue reports would be its own unit with its own design, and positions already written at 1x would keep their size.
