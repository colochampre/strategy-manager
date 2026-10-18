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
- A null `entry_price`, `exit_price` or `size` renders the existing `Absent` em dash with its reason for a screen reader. A fee in another currency renders after the fee as "+ 0.00012 BNB". `fees_complete: false` puts an asterisk after the PnL figure, explained by one note below the table and its paging controls for the page on screen (owner decision 46, 2026-10-05; the dialog keeps the words).

**How a rehearsal row is marked** (decision 43, answered 2026-10-04: the stored numbers are shown as they are, beside the mark and a sentence that says how the row was filled).
- A text tag in the Pair cell, on its own line under the pair, in the words of the mode badge (`DryRunBadge`, "Modo simulación") and in the same amber `decision` token. It is text, so it does not rest on colour. Its wording follows `rehearsal_fill_price`, and that is what tells the rows apart:

  | `rehearsal_fill_price` | Tag (EN / ES) |
  | --- | --- |
  | `FIXED_ONE` | "Dry run · fixed price" / "Simulación · precio fijo" |
  | `ALERT` | "Dry run · alert price" / "Simulación · precio de la alerta" |
  | `UNDETERMINED`, or a value this panel does not know | "Dry run" / "Simulación" |

- **Every cell of a rehearsal row shows the stored number.** Entry 1 and exit 1 are printed as 1. No cell of a rehearsal row is blanked or special-cased.
- Its PnL and PnL % are drawn in neutral ink, never in the gain or loss colour. Green and red stay reserved for money that was made or lost.
- **The sentences below the table and its paging controls (owner decision 46, 2026-10-05; under the title before)** appear by what the page on screen holds, so each one is true of a row the reader can see:
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
| The Binance rate is not confirmed by a real round trip | It is the owner's figure read on the account | Said where the rate is defined (§ E). The first real Binance round trip confirms or corrects it; a correction is a one-line commit and applies to new fills only. **Confirmed 2026-10-18** by that round trip (`tasks.md` p17f.4): a taker fee of exactly 0.0005 on both legs, charged in USDT. |
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

## Addendum: the detail page's follow-ups (unit 12f, decisions 44 and 48) - 2026-10-06

Unit 12f, tasks 12f.1, 12f.4, 12f.5 and 12f.6, and the WIN RATE column that decision 44 moved out of unit 9p. HEAD `cacea20`. Decisions 44 and 48 are binding and are not reopened here. This addendum settles what they left to the design: which element the slider is and how it is drawn under the panel's CSP, the exact value it holds, the two confirmation texts, how a copy is made and how it fails, where the webhook's host comes from, and how a win is counted and served. 12f.2, 12f.3 and 12f.7 stay as built and are not designed. It adds two read-only endpoints and two fields to an existing one, changes no other response, and needs **no migration**.

> **Revised 2026-10-06.** The owner answered Q1 and Q2 of § N the same day and handled the prototype (`visual/project/PoolShareSlider.html`) with the Binance order form as the reference (decision 48's lines of 2026-10-06). Folded in: "Copied" beside the URL follows the URL on screen (§ E); the field sits above the track, the stops read as a legend, and the amount the share means sits under the track (§ B, § C, § C2); a share below 1% is allowed; and the owner's new requirement, that a share be enough to trade the strategy's pairs, is answered in § C3 with the branch the design can deliver honestly, the warning. §§ H to N are revised to match. The findings of § A are extended with U18 to U27, verified at HEAD `7751a9a`.

> **Revised again 2026-10-06 (HEAD `d58ea85`).** The owner handled the second prototype and answered Q5 (decision 48's last lines). Folded in: the explanatory sentences leave the screen and go behind two information buttons, a disclosure in place (§ B2); the number and the `%` sign sit together at the left of the field (§ B); the legend's distance from the track is approved and § B's legend is unchanged; and the warning on the pool's minimum order is enough, so no unit is recorded for a warning per pair. What is not checked stays in this addendum as a known limit of the unit (§ C3, § M), not as later work. No question is open.

> **Revised a third time 2026-10-06 (HEAD `1de0b6e`), for one measured fact.** The `size` attribute alone leaves a gap of about one character before the `%` sign in Chromium, so the claim of the previous revision is withdrawn and the field's sizing is chosen again: `size` plus `field-sizing: content` where the browser has it, which is the mechanism of the third prototype (§ B). Recorded with it: the owner approved the third prototype the same day (decision 48), and the control measures 252 px from the label to the Save row at 300 px with both explanations closed, against about 450 px with the three paragraphs on screen (§ K, § M). Nothing else changes, and no question is open.

**The answer in one paragraph.** The share is edited with the browser's own `<input type="range">`, restyled, over an inline SVG that draws the track, the filled part and the four stops with geometry ATTRIBUTES. No `style` prop is written anywhere, so the question of what `style-src 'self'` allows at runtime never arises for this control; it rests on the same mechanism as the return chart. The value is one decimal string: the field, above the track, shows it exactly, the handle sits at its nearest whole step, and only Save sends it, as `{"allocation_percent": "33.5"}` to the PATCH that already exists. Under the track the panel shows the amount that share asks for, which the SERVER computes with the function allocation itself uses, served once as a table of the hundred whole steps so that dragging makes no request; the browser still computes no money. The same answer says whether that amount is below the pool's own minimum order, the one figure about "enough to trade" that the API process knows exactly; that is a warning and never blocks a save. The exchange's minimum per pair needs a price and a leverage the API process does not have, so it is not checked, and that is a known limit of this unit (§ C3). The explanations of the control are not on screen: two information buttons, each a disclosure in place beside the thing it explains, show them when activated (§ B2). "Saved" and "Copied" are one small live text, mounted before it has anything to say. A copy writes the exact string the page is showing and never asks for the secret. The webhook's host is a new setting served by a new authenticated route, because the webhook does not live on the panel's origin (decision 5), and a malformed value is never served and never stops the API. A win is counted in `by_pair` and served as a count and a ratio; the panel formats the ratio and computes nothing. Two sequential PRs, backend then panel, split by deploy order. No question holds a task back.

### A. Findings from the code (verified at HEAD `cacea20`)

| # | Finding | Where | Consequence |
| --- | --- | --- | --- |
| U1 | The share is a `Decimal` with `0 < value <= 100` in three places: the value object, both request bodies (`gt=0, le=100`) and a CHECK on an unscaled `Numeric` column. Decimals are unbounded. | `strategies/domain/strategy.py:27-44`; `strategies/infrastructure/router.py:201, 214`; `migrations/versions/0007_allocation_percent.py:25-41` | Zero cannot be stored, so the track cannot start at 0 (decision 48). A stored value may have any number of decimals and may be below 1. |
| U2 | `PATCH /api/strategies/{id}` already takes `allocation_percent`. It locks the strategy row (`FOR UPDATE`), takes no advisory lock, refuses an archived strategy with 409 `STRATEGY_ARCHIVED`, accepts a disabled one, and answers the strategy view. **It logs nothing.** | `strategies/infrastructure/router.py:428-461`; `strategies/application/update_strategy.py:100-141` | No new write endpoint. A change of how much capital a strategy asks for leaves no trace today (§ J). |
| U3 | The share is read through `policy_for` when a signal is processed, and again when a deferred opening resumes. `requested` is computed from it BEFORE `AllocateCapital`, and `AllocateCommand` carries the amount, never the percent. | `signals/application/process_signal.py:354, 447, 617-635` | "Applies to the next allocation only" is already how the code behaves. Nothing after `requested` can re-read the share, so a reservation already made cannot be recomputed. |
| U4 | `StrategyView.allocation_percent` is a bare `Decimal`, not one of the wire types. The PATCH answers from the in-memory object, the GET from the stored row. | `strategies/infrastructure/router.py:156, 461`; `shared/infrastructure/wire.py:8-12` | Its text is whatever `str(Decimal)` gives, which `wire.py` documents as unstable. The panel must refuse a text it cannot read, and the backend should stop being able to write one (§ C). |
| U5 | The panel types and checks the field as a string and shows it nowhere. Its only PATCH sends `enabled`. A new strategy is registered with `"100"`. | `frontend/src/shared/api/types.ts:187`; `shared/api/strategies.ts:28, 71-77`; `features/strategies/NewStrategyDialog.tsx:15` | The control, its API function and its hook are all new. |
| U6 | The settings column holds the heading, `AllowedPairsEditor`, then a group with `EnableToggle`, `EnablementHistory` and `ArchiveControl`. The mockup puts the share FIRST, above the allowed pairs, and also prints it in the header line ("30% per trade"). | `features/strategies/StrategyDetailPage.tsx:73-84`; `visual/project/Strategy.dc.html:42, 77-80` | § C places the control. The header line is not one of this unit's pieces (§ N, Q3). |
| U7 | `AllowedPairsEditor` keeps a draft together with the stored list it was made on and drops it when the stored list moves. It has an error line and no success state. Its hook's `onSettled` returns the invalidation's promise. | `features/strategies/AllowedPairsEditor.tsx:15-19, 61-81, 100-112`; `shared/api/strategies.ts:181-203` | The share control copies the stale-draft rule. "Saved" is new state in both (§ D). |
| U8 | **No `style` prop exists in `frontend/src`.** A search for `style=`, `.style.`, `setProperty`, `cssText`, `type="range"`, `role="slider"` and `clipboard` finds nothing outside tests. The only value-dependent geometry is SVG attributes in the return chart, and its test asserts that no element carries a `style` attribute. A position that depends on state is a fixed class per state. | `features/overview/ReturnChart.tsx:190-273`; `features/overview/ReturnChart.test.tsx:95-110`; `features/strategies/StrategyRow.tsx:136-141` | The panel has one proven way to draw something whose position depends on a value: attributes on SVG elements. § B uses it. |
| U9 | The CSP is `style-src 'self'` with no `'unsafe-inline'`, sent on `index.html` only, with no `Permissions-Policy`. The comment beside it says React sets styles through the CSSOM, which the policy does not block. Nothing in the code relies on that (U8). `vite.config.ts` sets no response header. | `shared/infrastructure/spa.py:58-63, 128-134`; § 13; `frontend/vite.config.ts` | **No browser has ever loaded this panel under its policy**: production does not serve it (`PANEL_DIST_DIR` is unset) and the dev server sends no CSP. A control that needed a runtime style would be the first, and its failure would show only on the day the panel is served. |
| U10 | The webhook block shows the PATH only. The secret is read from the query result while rendering and is never copied into component state; it is evicted on hide and on unmount, and the block is unmounted while closed. | `features/strategies/WebhookMessage.tsx:8, 45-66, 83`; `features/strategies/StrategyHeader.tsx:67-69` | A copy must take the string already rendered, not build one from a stored value. |
| U11 | **The webhook is not on the panel's origin.** The panel and the admin API are on `strategymanager.trade` through a Cloudflare Tunnel; the webhook stays on a DuckDNS host whose proxy forwards only `/webhook/tradingview`. | owner-decisions.md, decision 5; design.md "Technical approach" diagram | `window.location.origin` is the wrong host. This is why the host must be told to the panel, and why it cannot be compiled in. |
| U12 | `Settings` has no field for a public host. `/health` is unauthenticated, answers `status` and `dry_run`, and is read by the mode badge with a strict shape check. Every startup invariant runs inside `operator_alerts` and REFUSES the start. | `shared/config.py` (whole class); `main.py:299-307, 1839-1841`; `frontend/src/shared/api/health.ts:16-27` | § F adds the setting and chooses where it is served, and does not make it an invariant. |
| U13 | `by_pair` groups one strategy's closed trades by `market_key` and has each pair's `ClosedTrade` list in hand. `PairStats` carries pair, count, PnL and return. It is fed `derived.closed`, the live set, after `require_live_only`. | `performance/domain/by_pair.py:45-75`; `performance/application/read_strategy_performance.py:62-76`; `performance/infrastructure/performance_router.py:247-257` | Wins are counted where the trades already are. Dry-run operations cannot reach the count (decision 43 addendum § C). |
| U14 | The panel checks every `by_pair` entry inside the check of the whole strategy report: one bad entry refuses the report. That report is read by the detail page AND by every row of the Strategies list. | `frontend/src/shared/api/performance.ts:66-84`; `features/strategies/StrategyPerformance.tsx:74`; `features/strategies/StrategyRow.tsx:41` | A panel that requires the new fields refuses more than the By pair table against an older API (§ G). |
| U15 | `PairStatsTable` has four columns, no width tier, and writes every percentage with a sign. | `features/strategies/PairStatsTable.tsx:60-98`; `features/overview/format.ts:40-51` | A win rate needs its own unsigned format. |
| U16 | The keyboard helper presses Tab, Enter and Space on buttons. jsdom lays nothing out and performs no default action of a range input. One existing test clicks every other button of the page to prove that none asks for the secret. | `frontend/src/test/keyboard.ts`; `features/strategies/WebhookMessage.test.tsx:126-151` | § K says what a test can prove about the slider and what is left to the eye. That existing test will click the new Copy, stop and Save buttons. |
| U17 | Production runs with `DRY_RUN=true` and does not serve the panel. | tasks.md delivery log | The By pair table is empty there, so the new column is first seen on the owner's local fixture. The compatibility rules of § G still bind `main`. |

**Added 2026-10-06, for the amount and for the minimum to trade (verified at HEAD `7751a9a`).**

| # | Finding | Where | Consequence |
| --- | --- | --- | --- |
| U18 | The pool's total balance is in the database, in `pool_balance_snapshots`, and the API process already serves it: `GET /api/pools` answers each pool's `balance` as `{total, available, observed_at, stale}`, or null for a pool nothing has synced. `stale` uses the allocator's own age limit (90 s by default). The worker's `balance.sync` rewrites the snapshot every 60 s. | `accounts/infrastructure/pools_router.py:38-85`; `accounts/infrastructure/pool_overview.py:48-99`; `shared/config.py` (`balance_sync_interval_seconds`, `balance_snapshot_max_age_seconds`) | The API process can read the total with no venue call and no credential. |
| U19 | The panel validates that body row by row and refetches it every 60 s under `['pools']`. The strategy page already has it in hand: the exchange scope the page uses is built from the same query. A strategy names its pool with `exchange`, `venue` and `settlement_currency`. | `frontend/src/shared/api/pools.ts:6-57`; `shared/scope/exchange-store.ts:69-79`; `features/strategies/StrategyDetailPage.tsx:35`; `shared/api/types.ts:180-192` | The page could find the pool's total without a request. It still may not multiply it (§ C2). |
| U20 | The amount a strategy asks for is `total * percent / 100`, quantised DOWN to 18 places, by one pure function. The worker calls it with the total it has just read, after an on-demand refresh of the balance. | `allocation/domain/percent.py:24-31`; `signals/application/process_signal.py:591-620` | A preview that calls the same function cannot disagree with the request on arithmetic. It can still differ on the balance, which is read again when a signal is sized. |
| U21 | **The pool has its own minimum order**, `capital_pools.min_order_size`, in the settlement currency. It is not the venue's minimum: it is the smallest position that survives a round trip, 5 USDT by default for the Bybit and Binance pools. `decide()` checks it FIRST: a request below it is skipped as `REQUEST_BELOW_MIN_ORDER_SIZE`, whatever the pair, the price or the leverage. `GET /api/pools` does not serve it. | `accounts/domain/pool_config.py:5-16, 39`; `accounts/domain/known_pools.py:44-49`; `allocation/domain/decision.py:44-48`; `allocation/application/allocate_capital.py:250-253` | One minimum is in the database, known to the API process exactly, and decides with certainty at a given balance. § C3 builds on it. |
| U22 | The venue's rules per pair are parsed by the public catalogue the API process already reads, and then thrown away. Bybit's `PerpContract` holds `qty_step`, `min_order_qty`, `max_order_qty`, `min_notional` (from `minNotionalValue`, optional) and `max_leverage`. Binance's holds `qty_step`, `min_qty`, `market_max_qty` and `min_notional` (optional), and no leverage limit. Both public catalogues return `contract.symbol` only, and `VenuePairCatalog` caches a set of market keys. | `shared/infrastructure/bybit/read_client.py:78-97, 501-523`; `shared/infrastructure/binance/read_client.py:88-112, 258-282`; `shared/infrastructure/bybit/public_catalogue.py:97-103`; `shared/infrastructure/binance/public_catalogue.py:88-94`; `strategies/infrastructure/pair_catalog.py:100, 171-189` | The minimum quantity, the step and the minimum notional are one change of a cache away, with no new venue read. They are quantities and notionals, not amounts of margin. |
| U23 | **The API process has no price.** No public ticker is read anywhere. `last_price` exists on Bybit's key-bearing read client and nothing in `src` calls it; Binance's client has no ticker read at all. The only prices in the database are the alert's (`signals.price`) and the fills'. | `shared/infrastructure/bybit/read_client.py:367-372` (no caller); `shared/infrastructure/binance/read_client.py`; decision 43 addendum, T15 | A minimum quantity cannot be turned into an amount without a price. A current price would be a venue read the API process does not make today. |
| U24 | **The API process cannot know the account's leverage.** It is read per symbol with the stored key, in the worker, when the order is built: from the position record on Bybit, from the symbol's configuration on Binance. The API process seals keys and never opens one. The leverage an order was sized at is recorded on its execution attempt. | `execution/infrastructure/bybit_futures_exchange.py:108-110`; `execution/infrastructure/binance_futures_exchange.py:111-113`; `shared/infrastructure/bybit/read_client.py:394-409`; `execution/application/place_order.py:183-199`; CLAUDE.md, "Credentials" | The margin a pair needs is its minimum notional divided by a leverage the API process does not have. What it can have is a bound (1x), and for traded pairs a past value. |
| U25 | **What the worker does today with an allocation that is too small. Three guards, in this order.** (1) A request that is not positive is refused before the pool lock: outcome `REJECTED`, `NOTHING_TO_ALLOCATE`, one WARNING, nothing reserved. (2) A request below the pool's minimum is skipped inside the lock by `decide()`: `REQUEST_BELOW_MIN_ORDER_SIZE` (or `PARTIAL_BELOW_MIN_ORDER_SIZE` for a partial grant), one WARNING, the outcome recorded on the signal, no reservation written. (3) A grant that the venue's rules make unplaceable is refused when the order is built: the size is `granted * leverage / price` floored to the step, and a size of zero, below the minimum quantity, above the maximum or below the minimum notional raises `OrderNotPlaceable`; `PlaceOrder` then releases the reservation, records `REJECTED` `ORDER_NOT_PLACEABLE` with the numbers, commits both together and logs one WARNING. Nothing is sent to the venue and no attempt row is written. | `signals/application/process_signal.py:621-629, 848-859`; `allocation/domain/decision.py:44-48, 66-70`; `allocation/application/allocate_capital.py:273-286`; `execution/infrastructure/bybit_futures_exchange.py:112-138`; `execution/infrastructure/binance_futures_exchange.py:115-141`; `execution/application/place_order.py:150-182` | The protection is sound for the money: no order, no capital left reserved, no retry. It is weak for the owner's notice: every one of the three is a WARNING, and only ERROR reaches the alert channel, so a strategy whose share is too small skips every signal quietly (§ C3). |
| U26 | The simulated exchange sizes at 1x and applies no step, no minimum quantity and no minimum notional. | `execution/infrastructure/fake_exchange.py:152-181` | Under `DRY_RUN`, which is production today, guard (3) of U25 never fires. A share too small for a pair rehearses without a complaint and would be refused live. |
| U27 | The prototype the owner handled keeps each stop as a 44 by 44 px `<button>` whose visible face is a small label, and centres the WebKit thumb with an explicit top margin because the track is given the full 44 px height. | `visual/project/PoolShareSlider.html:133-201` | A mark that reads as a legend and a button with a full target are already the same element there. § B keeps that and moves it closer to the track. |

### B. The slider: the element, and how it is drawn (12f.1)

**The element.**

| Option | For | Against |
| --- | --- | --- |
| **The native `<input type="range">`, restyled, over an SVG drawing (chosen)** | Pointer, touch and keyboard behaviour are the browser's, with no code: dragging, a press on the track, arrows, Home and End. The role is `slider` and the value is exposed without an ARIA attribute to keep in step. The handle is positioned by the browser, so it needs no style from this code. | The track and handle are styled through vendor pseudo-elements, which differ by engine and cannot be seen in jsdom. The filled part is not drawn by WebKit or Blink once the default appearance is removed. |
| The native control left as the browser draws it, with `accent-gain` and a `<datalist>` for the stops | The least code. The filled part and the tick marks are the browser's. | The marks cannot be styled or made activatable, the look differs by browser, and nothing of the panel's visual direction (decision 19) reaches it. Kept as the fallback if the chosen drawing fails the owner's review. |
| A custom element with `role="slider"` | Full control of the look | Every key, the drag arithmetic, touch and focus are written by hand. The drag needs `getBoundingClientRect`, which jsdom answers with zeros, so the behaviour could not be tested at all. The handle would need a value-dependent position, which is the one thing the CSP question is about. |

- **The handle** is the native thumb, given a fixed size and the `gain` colour through Tailwind 4 arbitrary variants on the input (`[&::-webkit-slider-thumb]:…` and `[&::-moz-range-thumb]:…`), with `appearance-none` and a transparent native track. These compile into the stylesheet the panel already serves from its own origin. The class list is one constant, so a test can assert it.
- **The track, the filled part and the four stop marks** are one `aria-hidden` inline `<svg>` under the input: a line for the track, a line whose `x2` attribute is the handle's position as a percentage, and four circles whose `cx` are the four fixed positions. Percentages in SVG coordinate attributes are measured against the SVG's own box, so nothing is measured and no `ResizeObserver` is needed. A stop at or below the handle takes the `gain` class, the others `rule-strong`.
- **Alignment.** A native thumb's centre travels from half its width to the full width minus half its width. The SVG is inset by exactly half the thumb on each side (thumb `size-5`, inset `2.5`), so a position of `p` percent in the SVG is under the thumb's centre at that value. This holds only because the thumb's size is set explicitly, in both engines.
- **The position of a value** on a track from 1 to 100 is `(v − 1) / 99`: 25 is 24.2424%, 50 is 49.4949%, 75 is 74.7475%, 100 is 100%. One pure function gives it; it is a control position, not money.
- **The stops read as a legend and are still buttons** (decision 48, after the prototype). Each is a `<button>` placed with one fixed class (`left-[24.2424%]` and so on, `-translate-x-1/2`) inside the same inset box; they are the four fixed positions, so they need no runtime value at all. What changes is the face, not the element:
  - The visible face is a small mono label ("25%") in `ink-3`, with no border and no fill at rest. The stop that equals the value is drawn in `ink`. It looks like the legend of the track.
  - **The target stays 44 by 44 px.** The button's box is transparent and larger than its label, as in the prototype (U27).
  - **It sits closer to the track.** The legend row is pulled up by 12 px, so each label is about 4 px under the handle instead of a row away. The track's box is 44 px tall and the handle is the middle 20 px of it, so the 12 px under the handle belong to the track's box and hold nothing to grab. The buttons are stacked above the input and begin exactly at the handle's lower edge: they never cover the handle, and their whole 44 px is reachable. A press in that 12 px band at a stop sets that stop, which is what a press on the track at that point would do within a step.
  - **The keyboard path is unchanged:** the four are in the tab order after the track, each with a name that says what it does and `aria-pressed`, and each shows the panel's focus ring.

**The CSP.** The question was whether a value-dependent position can be set at runtime under `style-src 'self'`. The design does not need the answer, and that is deliberate.

| What a browser checks against `style-src` | Does this control use it? |
| --- | --- |
| A `<style>` block, and a `style` ATTRIBUTE, whether parsed from markup or set with `setAttribute` | No. No `style` prop is written. |
| A property set through the CSSOM (`element.style.x = …`), which is how React applies a `style` prop on a tree it rendered in the browser. By the policy's definition this is not blocked, and § 13 says so. | No. The claim is believed and is not relied on. |
| Geometry and presentation attributes of SVG elements (`x2`, `cx`, `stroke-width`) | Yes. They are attributes, not styles, and no directive governs them. |
| Rules in a stylesheet served from the panel's origin, vendor pseudo-elements included | Yes. That is `'self'`. |

- **Verified in the code:** no `style` prop exists anywhere (U8); the return chart draws every value-dependent coordinate with SVG attributes and its test forbids a `style` attribute; the policy string and the fact that only `index.html` carries it (U9).
- **Not verified, and said plainly:** no browser has loaded the panel under this policy (U9). So the statements in the table are read from how the policy is defined, not observed here. What the choice buys is that the slider stands on exactly the ground the return chart stands on: if SVG attributes were refused, the panel's main instrument would fail first and visibly.
- **A guard so that it stays true.** `frontend/src/shared/theme.test.ts` gains one test: no non-test source file contains a `style=` prop. It passes at once today; the mutation is one `style={{}}` on any element. With it, the day somebody reaches for a runtime style is a red test, not a broken page in production.
- **To check in a real browser, before this is called done** (§ K): the built bundle served by FastAPI with `PANEL_DIST_DIR` set, so the header is really sent; the strategy page opened with the console showing no policy violation; the slider dragged and driven by keys. This can be done locally and does not wait for production.

**Layout** (revised 2026-10-06, decision 48, with the Binance order form as the reference). Top to bottom, each on the full width of the column:

1. The label, with its information button right after it (§ B2).
2. **The field**, as wide as the column, with the number and the `%` sign together at its left (below). It is above the track, not beside it.
3. **The track**, 44 px tall, with the handle.
4. **The legend of the four stops**, close under the track. Its distance from the track is approved as the second prototype has it (decision 48) and is not changed.
5. **The amount** that share asks for, in the pool's own currency (§ C2), with its information button right after it, and under it the warning when the amount is below the pool's minimum (§ C3).
6. The validation or refusal text. No helper sentence is on screen (revised 2026-10-06, § B2).
7. The Save button with "Saved" beside it.

- With the field on its own row, the track always has the whole column: about 360 px on a desktop and about 300 px on a phone, so the four 44 px targets are about 86 px and about 70 px apart and never touch. Nothing wraps, and the minimum-width rule of the first layout is gone.
- The rightmost target is centred on the end of the track and runs 12 px past the inset box, inside the column's own padding.
- These widths are read from the classes and are confirmed by eye.
- `visual/project/PoolShareSlider.html` now holds the THIRD prototype: the number and its sign together at the left of the field, two information buttons, no paragraph on screen. **The owner approved it on 2026-10-06** (decision 48): each information button works, the sign follows the text, nothing more is changed for now. It is the visual review the standing constraints ask for before tasks. What that approval does not cover is in § M.

**The field's inside: the number and the `%` sign together at the left** (revised 2026-10-06, decision 48; the mechanism revised again the same day, after a measurement). The sign must follow the last character typed, so the input has to be as wide as its text, and this panel sets no width through a `style` prop (F2).

> **Corrected 2026-10-06, by measurement.** The previous revision chose the `size` attribute alone and said that, in a monospaced font, an input with `size` equal to its text's length is as wide as its text. **That is false in Chromium.** The third prototype was built that way and rendered in headless Edge, with Consolas at 14 px: `size="4"` gave an input 40 px wide for a text of 30.8 px, and `size="12"` gave 104 px for 92.4 px. The engine sizes a text input as about the average character width times `size`, plus about one more character. So `size` alone leaves a gap of about one character before the sign. The statement was this design's belief, marked as unverified; it is now measured, in one engine, and withdrawn. Firefox and Safari were not measured.

| Option | What the owner sees | Cost |
| --- | --- | --- |
| **The `size` attribute, plus `field-sizing: content` where the browser has it (chosen)** | Where the property exists the input is exactly as wide as its text and the sign touches the number: measured in Chromium at `33.5` and at twelve characters, with an empty field leaving the sign one character from the left. Where it does not exist only `size` applies, and the sign stands about one character off: "33.5 %". | One attribute and one declaration; the text is in the document once. Exactness depends on the browser. It is the mechanism of the prototype the owner approved. |
| A hidden span mirroring the text, sharing a grid cell with the input, and nothing else | In principle the cell is exactly as wide as the text in every engine, with no measuring and no `style` prop | The text is rendered twice. The span must be hidden from assistive technology (`aria-hidden`), from sight (`invisible`, which keeps its width) and from selection (`select-none`). It must keep spaces as typed (`whitespace-pre`), or a trailing space would make the cell narrower than the input's text. An empty field gives an empty span and a cell of no width, so a minimum of one character is still needed for the caret. A long paste is bounded by `maxLength` either way. And the cell is only as narrow as the span if the INPUT contributes nothing to it; the measurement above shows an input carries more intrinsic width than its text, so that rests on how each engine treats an input with a percentage width in an automatic track, which nobody here has measured. **Not seen by the owner.** |
| The sign as part of the field's own text (`33.5%`) | One element; a screen reader hears the unit | The value is rewritten on every keystroke, which moves the caret unless it is set by hand each time; that misbehaves with mobile keyboards and with composition. A selection of everything includes the sign, a deletion can remove it, a paste carries its own. The sign would count against `maxLength` and every reader of the text would have to strip it. It turns a text field into a mask. |
| `size` alone | A gap of about one character in Chromium, measured | Refused: it does not meet "together" in the one engine that was looked at. |

- **Why the first.** It is exact in the engine where it was measured, and it is what the owner handled and approved ("the percent sign follows the text correctly"). The mirrored span promises more, exactness everywhere, and has been measured nowhere; choosing it now would replace an approved, measured behaviour with an unseen one that rests on a second unmeasured sizing rule, one day after the first unmeasured rule proved wrong.
- **Is a gap of about one character acceptable where the property is missing?** As a degradation, yes: the sign is still at the left, still right after the number, one character away, and nothing is misread. It is not what the owner sent back, which was the number at one edge and the sign at the other. It is also not "together", and the design does not pretend otherwise: in such a browser the field reads "33.5 %".
- **Which browsers those are was not verified.** To this design's knowledge the property is in Chromium-based browsers and not in every other current one. Only Chromium was rendered. The by-eye review of the panel PR must look at an engine without it, Firefox at least, and the owner says there whether that gap may stay (§ K).
- **The fallback, if it may not stay:** the mirrored span, applied only where the property is missing (`@supports not (field-sizing: content)`), so the approved behaviour is untouched where it was approved. It is then measured in that engine before it is trusted.
- **jsdom tests the two options equally, and neither's width.** It lays nothing out. With the chosen option a test can assert the `size` attribute and the class; with the span, that the span's text equals the input's value. Both prove the markup and nothing about where the sign stands.

- **The markup.** A wrapper `<div>` carries everything that made the field look like a field: the full width, `min-h-11`, the border, the `ground` fill, the horizontal padding. Inside it, at the left: the `<input>`, with no border, no fill, no horizontal padding of its own except 2 px at the right for the caret, then a `<span aria-hidden="true">%</span>` in the same font and the same ink. The rest of the wrapper is empty.
- **`size` is the number of characters in the field, and at least 1.** `size="0"` is not valid. It is what sizes the input where `field-sizing` is missing, and it is ignored where the property applies.
- **`field-sizing: content` and a minimum width of one character** are two classes on the input, compiled into the stylesheet the panel serves; a browser that does not know the property ignores the declaration, so no `@supports` test is needed for the chosen option. The minimum width is what leaves an empty field one character wide, with the sign one character from the left, which shows where to type. If the pinned Tailwind has no utility for the property, it is one rule in `index.css`.
- **The font.** The field is in `font-mono`, whose stack is IBM Plex Mono and then `ui-monospace`, Menlo, Consolas and `monospace` (`frontend/src/index.css`, `@theme`). With `field-sizing` the font no longer matters: the width is the text's own. With `size` alone a monospaced font keeps the gap constant, at about one character, instead of growing with the text. A pasted wide character (a CJK digit, an emoji) is not a number; the validation says so.
- **A long text.** `maxLength` is 12. With the property the input is twelve characters wide, about 92 px in the measurement; with `size` alone about 104 px. Either is a third of a 300 px column, so the sign cannot leave the field. A paste is cut to 12 by the browser, and `size` follows the value on the next render.
- **The focus ring is the wrapper's**, with `focus-within`, and the input's own outline is removed. A text input always shows focus, by mouse or by key, so `focus-within` here is the same moments as `focus-visible`. An invalid value turns the wrapper's border `loss`; a disabled control dims the wrapper.
- **A press anywhere in the wrapper puts the caret in the input.** The wrapper has `cursor-text` and one handler that focuses the input when the press was not on the input itself. It is not a second `<label>` around the input: that would join the field's accessible name, which the visible label already gives.
- **What § C says about the value does not change:** `type="text"`, `inputMode="decimal"`, one comma accepted, the validation, `maxLength` 12, the dot shown in both languages. Typing a `%` is still "not a number": the sign is already there. The field's name and the track's `aria-valuetext` are unchanged.
- **To check by eye** (§ K): in a Chromium-based browser, with the panel's own font, that the sign touches the number at one digit, at `33.5`, at `100` and at twelve characters, and that the caret at the end of the text is not clipped; and in a browser without `field-sizing`, that the gap is about one character and no more, and whether the owner accepts it.

### B2. The information buttons (decision 48, added 2026-10-06)

The owner's ruling: the explanations do not stay on screen. Three paragraphs under the amount were taller than the control and pushed the card past one screen at 300 px. At most an information button, the usual "i" in a circle, where each detail belongs; activating it shows the information.

**The mechanism.**

| Option | CSP and the no-`style` rule | Keyboard and screen reader | Touch | jsdom | Verdict |
| --- | --- | --- | --- | --- | --- |
| **A disclosure in place: a `<button>` with `aria-expanded` and `aria-controls` that reveals the text in the flow, under its line (chosen)** | Nothing is positioned, so nothing is computed | A real button: Enter and Space. The state is announced, and the text is the next thing in reading order. | A tap | Fully testable: the click, the attribute, the text in the document | The panel already has two (`features/overview/MonthlyGrid.tsx:196-204`, `features/strategies/StrategyHeader.tsx:53-61`), so it is the pattern, not a new one. |
| The native `popover` attribute | A popover is drawn in the top layer. Without an anchor it appears in the middle of the viewport, away from the detail it explains. Anchoring it needs either CSS anchor positioning, which this design did not verify in every current browser, or a position computed in script and written as a style, which F2 forbids. | Good: Escape and light dismiss come free | A tap | To this design's knowledge jsdom does not implement the popover API, so opening and closing could not be tested | Refused |
| A `<details>` element | No positioning | Good | A tap | Partly | Refused. The text is a child of the same element as its summary, so a button that sits INSIDE a row cannot reveal a block UNDER that row without layout tricks; and its state lives in the DOM, not in the component. |
| A `title` tooltip | None | Not reachable by keyboard in most browsers; read unevenly | **Hover does not exist on a phone** | Only the attribute | Refused. It does not meet "activating it shows the information". The panel has two `title` hints today, on the incomplete-fee mark (`TradesTable.tsx:124`, `TradeDetailDialog.tsx:161`); they are not the model. |

**How many, and where.** Two.

| Button | Sits | Reveals, under its row | Its text (§ I) |
| --- | --- | --- | --- |
| 1 | Right after the label | What the share is, and that a change applies from the next operation | `…share.hint` |
| 2 | Right after the amount | First: that the amount is an estimate, that it is margin, and when the balance was read. Second: that the exchange's minimum per pair is not checked. | `…share.amountHint`, then `…share.pairMinimumNote` |

- **The per-pair limit shares the amount's button; it does not get a third.** It is a statement about the amount: whether that much is enough. It has no line of its own to sit beside, since the sentence WAS the line. And a second glyph on the amount's row would differ from the first only in a name that sighted users do not see. One button, two paragraphs: whoever asks what the figure means is told, in the same place, what it does not guarantee.
- **The amount's row is always there, so its button is always there.** With no valid value in the field the figure is an em dash, the panel's existing mark for an absent figure; with no balance or a failed read it is that state's line (§ C2). The button never appears and disappears with the figure.

**What is always visible, and what is behind a button.**

| Line | Where |
| --- | --- |
| The label, the field with its sign, the track, the legend | Always visible |
| The amount, or its loading mark, or the em dash | Always visible |
| "The pool's balance was last read at … and may be out of date." | **Always visible.** It changes what the figure means. |
| "The pool's balance has not been read yet…" and "The amount could not be loaded." | **Always visible.** Each stands where the figure would be. |
| **The warning that the share asks for less than the pool's minimum order** | **Always visible.** It is the one thing this control checks. |
| The validation text (not a number; out of range) | Always visible |
| A refused save; the unreadable stored value | Always visible |
| "Saved" | Always visible |
| What the share is; a change applies from the next operation | Behind button 1 |
| The amount is an estimate, is margin, and was read at a given time | Behind button 2 |
| The exchange's minimum per pair is not checked; too small an order is refused and nothing opens | Behind button 2 |

- **What is lost, said plainly.** In the last revision the sentence about the per-pair minimum was always on screen, so that the absence of a warning could not be read as "enough for every pair". It is now one activation away. Without a click, nothing on the control says that a minimum exists which the panel does not check. This is the owner's choice (decision 48), made after seeing the alternative bury the control.
- **What still shows without a click:** the word "about" in the amount; the warning on the pool's minimum whenever it applies; the stale-balance line. And the protection itself does not depend on any text: the worker refuses an order that would be too small and opens nothing (U25).
- The time of the balance's read also moves behind button 2, except when the balance is stale, where the always-visible line carries it.

**Behaviour.**
- **Each button opens and closes its own text. Both may be open at once.** They are independent: closing one because the other opened would move the page under the reader.
- **What closes one:** the same button; and Escape, while focus is on the button or inside its text, which leaves focus on the button. Focus LEAVING does not close it, and neither does a press elsewhere: the text is part of the page, not a floating layer, and the owner must be able to read it while moving the handle.
- **Closed by default, on every visit.** The state is local to the component. It survives a save and a change of language, because neither remounts the control; the open text is then simply in the other language. It is reset when another strategy's page is shown. Nothing is stored.
- **They are never disabled.** On an archived strategy and during a save, reading is still allowed.
- **Names.** Each says what it explains, not "info", and does not change with the state, which `aria-expanded` carries: "About the share of the pool" and "About this amount and what is not checked" (§ I).
- **The text's container** is always in the document, empty while closed, so `aria-controls` always points at something. The paragraphs are rendered only while open, so a closed explanation is neither read nor found.
- **The target.** The button's box is 44 by 44 px, transparent, centred on a 16 px glyph. It adds no height to its row: the box extends 12 px above and below a line of text, and the rows around it are 12 px apart, so it touches its neighbours and overlaps none. Confirmed by eye.
- **The glyph** is an inline `<svg aria-hidden="true">`: a circle, a dot and a stem, drawn with attributes and coloured through `currentColor` from a text class, as the rest of this control. `ink-3` at rest, `ink-2` on hover, `ink` while open. No icon font, no external file, and no text character: the circled "i" of Unicode is drawn differently by each system's fallback font.
- **One small shared piece.** `InfoDisclosure.tsx` in `features/strategies/`, beside `InlineStatus` (§ D): a hook that owns the open state and the two ids, and two presentational parts, the button and the container, because the two sit in different places of the layout. It is the first control of its kind in the panel. It lives with the feature that uses it, as `InlineStatus` does; no shared folder is created for one feature, and moving both is a rename on the day a second feature needs one. The two pieces are not merged: one is a live status, the other a disclosure.

### C. The slider: the value, the keyboard, the states, the API (12f.1)

**One value, three views.** The control holds one decimal string. Nothing is added, multiplied or converted; the only arithmetic is the handle's position and its rounding.

| Name | What it is |
| --- | --- |
| stored | `strategy.allocation_percent` as the server wrote it, read into canonical form: digits, an optional fraction, no leading zeros, no trailing fractional zeros (`100.000` is `100`, `33.50` is `33.5`). A text that is not a plain decimal (an exponent, a sign, an empty string) is unreadable. |
| draft | `{ base, text, handle }` or nothing. `base` is the stored value the edit was made on; when the stored value moves, the draft is dropped, the rule `AllowedPairsEditor` already follows (U7). `text` is exactly what the field holds. `handle` is the last whole position the track was given. |
| handle | A whole number from 1 to 100: the value rounded half up and clamped. It is what the range input and the SVG receive, always a valid step, so no browser has to repair it. |

| Event | Result |
| --- | --- |
| The page shows a stored `33.5` | Field `33.5`, handle at 34, `aria-valuetext` "33.5% of the pool". Save disabled. |
| The page shows a stored `0.5` | Field `0.5`, handle at 1, the end of the track. Save disabled. |
| The handle is moved, by pointer or by key, to `N` | Field `N`, a whole number. This is the only moment a decimal is rounded (decision 48). From a stored `33.5` the handle is at 34, so one press of the right arrow gives 35 and one of the left gives 33. |
| A stop is activated | The same, with 25, 50, 75 or 100. |
| The field is typed in | The text is kept as typed. When it reads as a valid value the handle follows it; when it does not, the handle stays where it was. |
| `33,5` is typed | Read as `33.5`. One comma is a decimal separator; Spanish keyboards produce it. The value is sent with a dot. |
| `0`, `0.0` | Not valid: "above 0". Save disabled. |
| `100.5`, `150` | Not valid: "at most 100". Save disabled. |
| An empty field, `abc`, `1e1`, `-5`, `25%`, `1.000,5`, `33.` | Not a number. Save disabled. Nothing is guessed and nothing is trimmed into a value. |
| `0.5` | Valid. A share below 1% is allowed (decision 48, answered 2026-10-06); the API accepts it (U1). The track still runs from 1 to 100, so the handle sits at 1. The warning of § C3 says when its amount is too small. |
| The stored value is typed back | Valid and unchanged. Save disabled. |

- **Save is enabled** when the strategy is not archived, no save is in flight, the text reads as a value above 0 and at most 100, and its canonical form differs from the stored one.
- **The field** is `type="text"` with `inputMode="decimal"`, not `type="number"`: a number input answers an empty string for anything it dislikes (so "empty" and "not a number" cannot be told apart), treats a comma differently by browser, and changes its value on a stray wheel turn. `maxLength` is 12 characters, a bound on the text, not a rule about the number.
- **The field shows a dot in both languages**, and accepts a comma. An input echoes what is typed; rewriting the separator on load but not while typing would change the field under the owner's hands. Reviewed by eye.
- **The value goes to the API as a string**: `{"allocation_percent": "33.5"}`, and nothing else in the body. The other fields are omitted, which the PATCH reads as unchanged.

**Keyboard and accessibility.**
- Tab order, which is the order on screen (revised 2026-10-06 for the information buttons): the label's information button, the field, the track, the four stops in order, the amount's information button, Save. Nine stops. The amount, the warning and an opened explanation are text and take no stop.
- On the track the browser's own keys apply: an arrow moves one step, Home goes to 1, End to 100. Page Up and Page Down move by a larger step in the browsers that implement them; the size is the browser's and is not specified here.
- The track and the field are both named by the visible label. The track carries `min` 1, `max` 100, `step` 1 and an `aria-valuetext` with the exact value, so a screen reader hears "33.5% of the pool" while the handle sits at 34.
- Each stop is a `<button>` showing "25%" with a name that says what it does ("Set the share to 25%"), and `aria-pressed` when the value is exactly that stop. It reads as a legend and behaves as a button (§ B): Tab reaches it, Enter or Space activates it.
- The validation text is tied to the field with `aria-describedby` and `aria-invalid`. It is not an alert: it would otherwise be announced on every keystroke of an unfinished number.
- The track is 44 px tall, each stop and each information button at least 44 by 44 px, the field's wrapper and Save `min-h-11`, as every control of the panel.
- The `%` sign beside the number is `aria-hidden`, as it was at the right edge: the label and the track's value text already say it is a percentage (§ B).

**States.**

| State | What shows |
| --- | --- |
| Unchanged | The stored value. Save disabled. |
| Changed, not saved | The new value. Save enabled. Leaving the page discards it; nothing was sent. |
| Saving | Save reads "Saving…" and the track, the stops and the field are disabled, so the value cannot move under a request in flight. |
| Saved | "Saved" beside Save (§ D). The field shows the value the server answered. |
| Refused, 422 | "The share must be above 0 and at most 100." The panel validates first, so this means the two disagree. |
| Refused, 409 `STRATEGY_ARCHIVED` | "This strategy is archived and can no longer be changed." The page then reads the strategy again and the control turns read-only. |
| Refused, 404 | "This strategy no longer exists." The page then shows its not-found state. |
| A network failure, a 5xx, or a 200 whose body is not a strategy | "The share was not saved. Try again." The draft is kept. |
| An archived strategy | The value is shown; the track, the stops, the field and Save are disabled, as the rest of the column. The two information buttons are not: reading is still allowed (§ B2). |
| An explanation is open | Its text is under its row, in any of the states above. It stays open through a save, a refusal and a change of language, and closes with its button or Escape (§ B2). |
| A stored value that cannot be read | "The stored share could not be read, so it cannot be edited here." No track, no field, no Save. Never a guess. |

Save refusals are a `role="alert"` line, as in `AllowedPairsEditor`. A 401 clears the token and the token gate takes over, as on every call.

**Where it sits.** First in the settings column, under the heading and above the allowed pairs, as the mockup has it (U6). Its label is "Share of the pool per trade", the mockup's words. What the number means and when a change counts is said behind the label's information button, not on screen (§ B2, § I). The number is a share of the pool's TOTAL balance, not of what is free (`strategies/domain/strategy.py:28-34`), and that text says so.

**What "the next operation" means.** The share is read when an opening is sized (U3). An alert already received whose opening was deferred, because it waits for a close to settle, is sized with the share stored when it finally opens. An operation already open is not resized, and a reservation already made is not touched: nothing after `requested` reads the share.

**Out of scope, and said so.**
- **The Strategies list does not show the share.** § 15 lists what a row shows (name, pool, switch, uptime, trades, all-time PnL and return) and the share is not among them.
- **`NewStrategyDialog` is not touched.** It keeps registering with `"100"`. A new strategy is always disabled, so the owner sets the share on its page before enabling it.

**The API layer.**
- `setStrategyAllocationPercent(strategyId, value)` in `shared/api/strategies.ts`: the PATCH above. It checks the answer with the existing `isStrategy` and throws on a body that is not a strategy.
- `useSetAllocationPercent(strategyId)`: on success it writes the checked answer into `['strategy', id]`, so the stored value is the confirmed one even if the refetch that follows fails; on settle it invalidates `['strategies']` and `['strategy', id]`, as the other two hooks do, and returns that promise.
- **Backend, two small changes in the strategies module.** `StrategyView.allocation_percent` is written with the wire's plain notation (the `Money` annotation of `wire.py`), so the answer can never be an exponent (U4). `UpdateStrategy` logs one INFO line when the share actually changes, with the strategy id, the old value and the new one (§ J).

```
 owner              PoolShareEditor                PATCH /api/strategies/{id}            worker, next opening
   | move, stop or type  |                                   |                                   |
   |-------------------->| draft only, nothing sent          |                                   |
   | Save                |                                   |                                   |
   |-------------------->| {"allocation_percent": "25"} ---->| lock the strategy row              |
   |                     |                                   | 0 < value <= 100, not archived     |
   |                     |                                   | UPDATE, INFO old -> new, COMMIT    |
   |                     |<--------- 200, strategy view -----|                                   |
   |                     | cache <- the answer, then refetch |                                   |
   |<------ "Saved" -----|                                   |                                   |
   |                     |                                   |      policy_for(strategy) -> 25   |
   |                     |                                   |      requested = total * 25 / 100 |
   |                     |                                   |      AllocateCapital (pool lock)  |
```

### C2. The amount under the track (decision 48, added 2026-10-06)

**What the figure is, exactly.** The margin the next operation would ASK the pool for: the pool's total balance, as last read, times the share. Three things it is not. The text that says each is behind the amount's information button, not on screen (revised 2026-10-06, § B2, § I):

- **Not what is free.** The request is sized from the total (U20), so the same share asks for the same amount whether or not other strategies hold positions. What is GRANTED is capped by what is free, and can be less or nothing.
- **Not the position's size.** It is margin. The position is that margin times the account's leverage for the pair, divided by the price (CLAUDE.md, "Futures execution").
- **Not a promise.** The balance is read again, after an on-demand refresh, when a signal is sized (U20). The figure is an estimate of the next request at the balance on screen.

**Who multiplies.** The panel never computes a money figure (§ 15), and `total * share / 100` is one. The total is already in the page's hands (U19), so the temptation is real; the design does not take it.

| Option | Verdict |
| --- | --- |
| **One route that answers a table of the hundred whole steps, plus one exact value (chosen)** | The handle and the stops only ever land on a whole number from 1 to 100, so every position the track can show has its amount already in the browser: dragging makes NO request and the figure follows the handle at once, as on an exchange. A typed decimal is the one case that asks. The server computes every amount with `requested_from_percent`, the function the worker uses, from one read of the balance. |
| A preview per value, debounced | Every position needs a request. While the handle moves, the panel shows either nothing or the last figure beside a new percentage, which is a wrong number on screen. |
| The table as fields of the strategy view | A figure that changes every minute with the balance would ride on every strategy payload, the list's included, and the strategies read would depend on the snapshot table. |
| Multiplying in the browser from `['pools']` | No route at all. It breaks the panel's standing rule and makes a second implementation of the engine's rounding, in another language. Revisiting that rule is the owner's call; the design does not need it revisited, so it is not asked. |

**The route.** `GET /api/strategies/{id}/share-preview`, new, read-only, behind the bearer token on the strategies router.

```
GET /api/strategies/{id}/share-preview
      ?share=<decimal>     optional: above 0 and at most 100. Default: the stored share.

200
{
  "strategy_id":  "0b6f…",                                          string (uuid)
  "pool":         { "exchange": "bybit", "venue": "usdt-m", "settlement_currency": "USDT" },
  "currency":     "USDT",                                           string
  "pool_minimum": "5.000000000000000000",                           string, never null
  "balance":      { "total": "1000.00…", "observed_at": "…Z", "stale": false },      or null
  "exact":        { "share": "33.5", "amount": "335.00…", "below_pool_minimum": false },   or null
  "steps": [                                                        100 entries, or []
    { "share": 1, "amount": "10.00…", "below_pool_minimum": false },
    …
    { "share": 100, "amount": "1000.00…", "below_pool_minimum": false }
  ]
}
```

- `balance` is the pool's snapshot, with the same `stale` rule as `GET /api/pools` (U18). It is null for a pool nothing has synced, and then `exact` is null and `steps` is empty: with no balance there is no amount, never a zero.
- `amount` is `requested_from_percent(total, share)`: 18 places, rounded DOWN, written with the wire's `Money`. `share` in `steps` is the whole number of the step, a JSON integer like a count; in `exact` it is the share as a plain decimal string.
- `below_pool_minimum` is `amount < pool_minimum`, the comparison `decide()` makes first (U21, § C3).
- A stale balance is still served, marked. The worker would refuse to size against it; the preview shows it and says when it was read.
- An archived strategy is served: its page still shows what its stored share means.
- Refusals: 404 `no such strategy`; 422 for a `share` that is not a decimal above 0 and at most 100 (FastAPI's own, with the existing handler that echoes no input).
- It reads two rows of the database and calls no venue. Nothing is locked and nothing is written.

**The panel.**
- `useSharePreview(strategyId)`, query key `['strategy', id, 'share-preview']`, read when the control mounts and again every 60 s, the cadence of the balance. It sits under the strategy's own key, so a save, which invalidates that key, refreshes it.
- **Which amount is shown** for the value in the field:

  | The value | The amount comes from | Request |
  | --- | --- | --- |
  | A whole number from 1 to 100 (every handle position, every stop) | `steps`, by its number | none |
  | The stored share, when it has decimals | `exact` of the first read | none |
  | Any other valid value: a typed decimal, or a value below 1 | A second read with `?share=`, sent 300 ms after the last keystroke, key `[…, 'share-preview', share]` | one, at rest |
  | A text that is not a valid value | nothing | none |

- **While that second read is pending the line shows no figure**, only a mark that it is loading. The previous amount is never left beside a new percentage.
- An answer is used only when its `exact.share` is the share that was asked, compared in canonical form. An answer for another value is refused.
- **The check of the body:** `balance`, `exact` and `steps` are present together or absent together; `steps` has exactly 100 entries numbered 1 to 100 in order; every amount is a string. A body that fails is an error, never a partial table.
- **The figure is cut DOWN to the currency's decimals, as text**, then given to `Intl` with those decimals fixed. The engine never rounds a request up, and a figure rounded up could read "5.00" beside a warning that it is under 5. Cutting digits off a string is not arithmetic.
- **Volume.** One read when the page opens, one a minute, one per typed decimal at rest. A drag from one end of the track to the other is zero requests.

| State of the amount | What shows under the track |
| --- | --- |
| Known | The amount and its currency. When the balance was read is behind the information button (§ B2). |
| The balance is stale | The same, with a sentence saying the balance may be out of date |
| The pool has no balance yet | "The pool's balance has not been read yet, so the amount cannot be shown." |
| Loading: the first read, or a typed decimal's | A loading mark, no figure |
| The read failed, or its body was refused | "The amount could not be loaded." The slider, the field and Save are NOT disabled: the amount is information, and its failure must not stop a save. |
| The field holds no valid value | An em dash where the figure would be, the panel's existing mark for an absent figure. The row and its information button stay (§ B2). |

In every state the row ends with the amount's information button. The stale line, the two lines that replace the figure, and the warning of § C3 are always visible; only the explanation of what the figure is sits behind the button.

### C3. The minimum to trade (decision 48, answered 2026-10-06)

The owner asked for a share that is enough to trade the strategy's pairs, refused when it is not, or warned about if the refusal cannot be made in this unit. **The design delivers the warning, for the one minimum the API process knows exactly, and says plainly which minimum it does not check.**

**What decides whether an allocation is enough, and who knows it.**

| Input | Where the system has it today | In which process |
| --- | --- | --- |
| The pool's own minimum order | `capital_pools.min_order_size` (U21) | Both. The API process can read it. |
| The pool's total balance | `pool_balance_snapshots` (U18) | Both |
| The pair's minimum quantity, step and minimum notional | The venue's catalogue. The worker reads it with the key when it builds an order. The API process reads the public one and keeps only the symbols (U22). | Worker: yes. API: parsed, then dropped. |
| The pair's price | The alert carries it, and the order is sized with it. No current price is read anywhere (U23). | Worker: the alert's. API: none. |
| The account's leverage for the pair | Read with the key when the order is built (U24) | Worker only. The API process decrypts nothing, so it cannot read it. |
| The venue's maximum leverage for the pair | Bybit's public catalogue (parsed, then dropped). Binance's public catalogue does not carry it (U22). | API: Bybit only, after a change |

For a pair with minimum quantity `q`, step `s`, minimum notional `n`, at price `p` and leverage `L`, the smallest margin that opens a position is `max(q, n / p rounded UP to s) * p / L`. Two of those five numbers, `p` and `L`, are not in the API process.

**What protects the system today** is U25, and the design rests on it: whatever the panel adds stands in front of those three guards, never in their place.
- **For the money it is sound.** A request that is too small never reaches the venue. Guard (2) writes no reservation. Guard (3) releases the reservation in the same commit that records the refusal. Nothing is retried, because nothing can change without the grant, the leverage or the price changing.
- **For the owner's notice it is weak.** Each guard writes one WARNING and an outcome on the signal. Only ERROR is forwarded to the alert channel (`shared/config.py`, "Operator alerting"), and the panel shows signal outcomes nowhere. A strategy whose share is too small therefore looks like a strategy that never fires. That is the gap the owner's requirement points at.
- **Under `DRY_RUN` guard (3) does not exist** (U26), so production today cannot reveal a share that is too small for a pair.

**The refusal, and why it is not chosen.**

| What a refusal would need | What is true |
| --- | --- |
| To be true when it is made | The per-pair minimum needs a price and a leverage the API process does not have. Without them a refusal would be a guess. |
| To stay true | The minimum moves with the price, and the amount moves with the balance. A share accepted at save time can fall under the minimum later with no save at all; a share refused today can be enough after a deposit. A refusal at save time cannot promise anything about the next operation. |
| To be available when the owner needs the control | A per-pair refusal reads the venue. Saving pairs does, and fails closed when the venue cannot be read (decision 40): right there, because an unchecked pair is a typo waiting to be traded. For the share it would mean that a venue outage stops the owner from lowering how much capital a strategy asks for, on a control that needs no venue today. |
| To mean what an accepted save would be taken to mean | A refusal on the pool's minimum alone IS possible: it needs no venue. But a save it accepts would be read as "enough for the pairs", which nothing established. It would also tie the PATCH to the balance: with no snapshot it must either refuse every save, so a dead `balance.sync` freezes the control, or let everything through, which is no guarantee. |

- **A bound that would make a refusal true** exists in principle: a share so small that not even the venue's maximum leverage reaches a pair's smallest order. It needs the same price read, and the maximum leverage, which only Bybit's public catalogue has (U22). And it refuses almost nothing the pool's minimum does not already skip: it would only bite on a pair whose smallest order is worth more than the pool's minimum times that maximum leverage. It is not worth its cost.

**What this unit delivers: a warning that is exact about what it claims.**
- **The pool's minimum.** When `below_pool_minimum` is true for the value in the field, one sentence under the amount says that at this balance the share asks for less than the pool's minimum order, and that openings would be skipped (§ I). It is the comparison `decide()` makes first, with the function the worker sizes with, on the balance shown; a test asserts that the preview and `decide()` agree on both sides of the limit. It is true of the balance on screen and makes no claim about a later one.
- **It never blocks.** Save stays enabled. A value below 1% is allowed, and so is a value under the minimum: the owner may be setting the share before a deposit.
- **It shows on the stored value too**, not only on a change. A share that was fine can fall under the minimum because the balance fell, and the page then says so on its next visit.
- **The warning is always visible.** It is not one of the explanations that moved behind a button (§ B2).
- **The colour** is `loss`, the palette's colour for refusals, because what it announces is a refusal to come. It is not amber: amber is reserved for what needs the owner's decision and its allow-list is not widened. It is a `role="status"` line, not an alert: it changes while the handle moves.

**The known limit of this unit: the exchange's minimum per pair is not checked** (decision 48, answered 2026-10-06: the warning on the pool's minimum is enough for now, and no unit is recorded for a warning per pair).
- **What is not checked.** Each pair has a minimum order at the exchange, which depends on its price and on the account's leverage. The API process has neither (U23, U24), so the panel does not compare the share with it. A share can show no warning and still be too small for a pair whose smallest order is large.
- **What happens then.** Live, the worker refuses the order when it builds it, records the refusal on the signal, releases the reservation and opens nothing (U25, guard 3). Under dry run nothing refuses it, because the simulated exchange applies no minimum (U26).
- **Where the owner can read it.** In the panel, as the second paragraph behind the amount's information button (§ B2, `…share.pairMinimumNote`). It was always on screen in the previous revision; the owner chose to put explanations behind a button, and § B2 says what that costs. And here, and in § M.
- **Alternatives weighed and not built.** Estimating from the last alert's price in `signals` has no price for a pair that never fired, which is the new strategy whose share is being set for the first time. A current price is a venue read the API process does not make. Neither is in this unit.

### D. "Saved" after a save (12f.4)

- **One shared piece, local state.** `InlineStatus` is a presentational component in `features/strategies/`: a `<span role="status" aria-live="polite">` that takes a message or nothing, and a tone. It is ALWAYS mounted, empty until it has something to say: a live region that appears together with its text is not reliably announced. Each control keeps its own boolean; there is no shared store, because the two saves have nothing else in common.
- **The same piece carries "Copied"** and its failure text (§ E), so there is one pattern for a short confirmation in the panel.
- **It has a neighbour, and they are two pieces** (added 2026-10-06). `InfoDisclosure`, the information button of § B2, lives in the same folder. `InlineStatus` speaks when something happened; `InfoDisclosure` shows a text when asked. Neither renders the other, and "Saved" is never placed behind a button.

| Control | "Saved" appears | "Saved" disappears |
| --- | --- | --- |
| The share | When the PATCH answers 200 with a strategy | On the next movement of the handle, activation of a stop or keystroke in the field; and when the page is left |
| The allowed pairs | When the PUT answers 200 | On the next pair added or removed; and when the page is left. Typing in the search box changes no pair and leaves it. |

- **No timer.** It stays until the owner changes something in that control (decision 48). A test advances the clock by ten minutes and still finds it.
- A failed save shows the refusal and never "Saved". The two are never on screen together: a new save clears the flag before it is sent.
- It is neutral ink (`ink-2`), not the gain colour: teal is for money made and for the primary action.
- **The allowed pairs' hook is not changed.** It still waits for its refetch. If that refetch fails after a 200, the list on screen is the old one, so "Saved" is not shown although the save happened. That errs on the safe side and is a limit of the existing hook, not something this unit widens (§ M).

### E. Two Copy buttons (12f.5)

- **Where.** "Copy URL" beside "Show secret", on the URL's row; "Copy message" under the alert message. Each has its own `InlineStatus` beside it.
- **How.** `copyText(text)` in `frontend/src/shared/lib/clipboard.ts` calls `navigator.clipboard.writeText` and answers true or false. It answers false when `navigator.clipboard` or `writeText` does not exist, and when the promise rejects. It never throws and never logs: the text may be the secret.
- **The secure context.** The clipboard API exists only on HTTPS and on `localhost`. Production is HTTPS and local development is `localhost`, so it is available on both. The panel opened over plain HTTP on another address has no `navigator.clipboard`, and the button then says it could not copy. No `Permissions-Policy` is sent (U9), and without one a page may write to the clipboard from a click; the CSP has no directive for it.
- **No fallback to `document.execCommand("copy")`.** It is deprecated, and it works by putting the text into a temporary field in the document, which for the revealed URL means a second place the secret is written. One mechanism, one failure text; the text stays selectable by hand, as it is today.
- **What is copied is what is on screen, by construction.** The URL is built once per render into one constant; the `<code>` element prints it and the button's handler is given the same constant. There is no second assembly that could differ.
- **Copying never asks for the secret.** The handler touches neither the "requested" flag nor the query. With the secret hidden it copies the URL with the placeholder.
- **The secret is not put in component state to enable a copy.** State holds only which button was used, whether it worked and, for the URL, whether the secret was shown at that moment: two tags and a boolean, never the text.
- **With the secret revealed the clipboard holds the real URL**, secret included, percent-encoded as shown. This is the owner's decision (44, 12f.5, and 48). The panel cannot take it back: "Hide secret" and leaving the view do not clear the clipboard, and a clipboard history kept by the operating system may hold it longer (§ M).
- **The URL is text, never a link.** It is not rendered in an anchor and is never passed to `fetch`: a click on a link would send a GET to the webhook with the secret in the address.

| Result | Text beside the button | Until |
| --- | --- | --- |
| The alert message was copied | "Copied" | Something else is copied, or the block is closed (decision 48). Closing unmounts the block, so reopening shows nothing. The message never changes, so nothing else removes it. |
| The URL was copied | "Copied" | The same, AND the URL on screen stops being the one that was copied: showing or hiding the secret removes it (decision 48, answered 2026-10-06). |
| The browser refused, or has no clipboard | "Could not copy. Select the text and copy it by hand.", in the `loss` colour | As the row of the button it belongs to |

- A second copy with the other button moves the text to that button. Only one of the two is ever shown.
- **"Copied" beside the URL is shown only while the URL on screen is the one that was copied** (decision 48, answered 2026-10-06; it was Q1 of this addendum). The case it closes: the owner copies the URL with the placeholder, then presses "Show secret"; without this rule "Copied" would sit beside the real URL while the clipboard still held the placeholder, and that URL pasted into TradingView fails authentication on every alert. The reverse case is closed the same way.
  - **How, without keeping the text.** The state of a URL copy records whether the secret was shown when the copy was made, and whether a host was part of the URL. Two things act on it. The "Show secret" and "Hide secret" handlers clear a URL copy's state, so "Copied" is removed for good and does not come back when the secret is shown again. And the render shows "Copied" only while both recorded booleans still equal the present, which covers what no handler sees.
  - **The host arriving late is the case no handler sees.** If the URL was copied as the path alone and the host then loads (§ F), the URL on screen is no longer the one copied, and the render check removes the text.
  - The alert message's "Copied" is not touched by either: showing or hiding the secret changes nothing in the message.

### F. The full webhook URL (12f.6)

**The setting.** `Settings.webhook_public_origin`, read from `WEBHOOK_PUBLIC_ORIGIN`. Default: empty, which means unset. Its value is the origin TradingView posts to, for example `https://example.duckdns.org`. It is the webhook's host, which is not the panel's (U11).

**Its form: an origin and nothing more.** A pure function, `parse_webhook_origin`, reads it:

| Input | Result |
| --- | --- |
| Empty | Unset. Not an error. |
| `https://example.org`, `http://localhost:8000` | Accepted as written. |
| `HTTPS://Example.ORG`, `https://example.org/`, `https://example.org:443` | Accepted and normalised to `https://example.org`: scheme and host in lower case, one trailing slash dropped, the scheme's default port dropped. |
| No scheme, a scheme other than `http` or `https`, an empty host | Refused |
| Anything after the authority: a path, a query, a fragment | Refused. The path is the panel's to add. |
| A user or a password (`https://user:pass@host`) | Refused. It would put a credential on screen and in the clipboard. |
| A space, a control character, a backslash, a host with characters outside ASCII, a port that is not a number in range | Refused |

- **`http` is accepted** because TradingView posts to ports 80 and 443 and a local rehearsal uses `http://localhost`. The setting describes where the webhook is; it does not make it safer or less safe.
- **A refused value is never served and never stops the API.** It is treated as unset, and one ERROR is logged at startup (§ J). It is deliberately NOT a startup invariant: the process that would refuse to start is the one that receives the alerts (rule 3), and a typo in a display setting must not cost a signal.
- **The raw value is never logged.** A refused value may be refused exactly because it holds a credential. The line names the setting and the reason.

**Which route serves it.**

| Option | Verdict |
| --- | --- |
| **A new route, `GET /api/webhook-origin`, behind the bearer token (chosen)** | One fact, one place, structural auth like every other `/api` router. Body: `{"origin": "https://example.org"}` or `{"origin": null}`. |
| A field on `/health` | Refused. `/health` is unauthenticated and is a liveness answer with a strict shape (U12). The host is not a secret, but nothing is gained by telling an anonymous caller which webhook belongs to this panel. |
| A field on `GET /api/webhook-secret` | Refused. The host must be on screen before any click, and that route is called only on "Show secret". |
| A field on every strategy | Refused. It is a fact about the deployment, not about a strategy. |

- **It needs the admin token** for two reasons: the admin API's own rule is that every `/api` route does, enforced on the router so that no route can forget it; and the page that shows it already holds the token.
- `null` means "no usable value": unset and refused read the same to the panel. Only the startup log tells them apart, which is why that line is an ERROR.
- The body never contains the secret. The existing sweep that reads the application's own route table covers the new route without being told (`tests/signals/infrastructure/test_webhook_secret_router.py`).

**In the panel.**
- `useWebhookOrigin()`, query key `['webhook-origin']`, read when the block is opened. The answer is checked again: the value is used only if `new URL(value).origin === value`, the browser's own definition of a serialised origin. That one comparison rejects a path, a query, a fragment, a user, a trailing slash and upper case. Anything else is treated as no host.
- **The URL** is `origin + "/webhook/tradingview?secret=" + value`, plain concatenation of a checked origin, a constant path and the placeholder or the percent-encoded secret. With no origin it is the path alone, exactly as today.
- **While the host is loading**, the path alone is shown, and that is what a copy would take.
- **When there is no host**, one sentence under the URL says why: none is configured, or it could not be loaded (§ I). An older API answers 404 for the route, which reads as "could not be loaded".
- **`connect-src 'self'` stays as it is.** The origin is displayed and copied. It is never requested, never a link, never a form target. The only request this adds goes to the panel's own `/api`.

### G. WIN RATE in "By pair"

**The domain.** `by_pair` counts wins where it already holds each pair's trades (U13).

- `PairStats` gains `win_count: int`, the trades of the pair whose `pnl` is above zero, and `win_rate: Decimal`, `win_count / trade_count`.
- **A PnL of exactly zero is not a win and counts in the total** (decision 44, answered 2026-10-06): 3 wins, 1 at zero and 1 loss are 3 of 5, `0.6`.
- **Every closed trade of the pair counts**, as it does in `trade_count` and `pnl`: one with no capital at open (its PnL is real), and one with incomplete fees, by the PnL it has.
- **Dry-run operations stay out**, with no new code: `by_pair` receives the live set only (U13).
- **A pair with no closed operation has no row.** The rows are built from the trades, so `trade_count` is at least 1 and the division is always defined. Nothing is served as null and no zero is invented. A strategy with no closed trade keeps the table's existing empty state.

**The wire.** `GET /api/performance/strategies/{id}`, the existing route; two new fields on each `by_pair` entry, nothing removed or renamed.

```
"by_pair": [
  {
    "pair":     "SOLUSDT",          string     unchanged
    "trades":   5,                  integer    unchanged
    "wins":     3,                  integer    NEW, 0 <= wins <= trades
    "win_rate": "0.6000000000",     string     NEW, never null, the Ratio type: 10 places
    "pnl":      "41.200000…",       string     unchanged
    "return":   "0.0312000000"      string or null, unchanged
  }
]
```

- **Both are served.** The ratio is what the panel shows, in the wire type every other percentage of the panel uses, so the browser divides nothing. The count makes the figure checkable by hand ("3 of 5") and lets the panel refuse a body whose two fields contradict each other.
- **The strategy report and the pool report are NOT given a win rate.** The existing design asked for one nowhere but in the mockup's By pair table, and decision 44 names that table only.

**The panel.**
- **Column order:** Pair, Trades, Win rate, PnL, Return. It follows the mockup, which puts it after Trades.
- **Format:** an unsigned percentage with one decimal ("60.0%", "58.3%"), through a new `rateText`, because `percentText` signs every figure (U15). One decimal and not a whole number: a whole number rounds 199 wins of 200 to "100%", which must mean every trade won (§ N, Q4).
- **Neutral ink.** A rate is not money made or lost.
- **Width.** The values are narrower than the heading, so the heading sets the column's width. No column is hidden. Estimated from the classes, the five columns need about 316 px in English and about 387 px in Spanish, where the existing headings "Operaciones" and "Rendimiento" are already the widest cells; the left column is about 308 px at a 1024 px viewport and about 343 px on a phone. So in Spanish, and for a narrow band in English, the table scrolls sideways inside the `overflow-x-auto` wrapper it already has. Following decision 46's preference, the Spanish heading proposed is short (§ I). Confirmed by eye.
- **The shape check** (`isPairStat`) requires `wins` to be an integer from 0 to `trades` and `win_rate` to be a string. `PairStatsTable` then reads the ratio, requires it between 0 and 1, and requires the two fields to agree at the ends: `wins` is 0 exactly when the rate is 0, and equals `trades` exactly when the rate is 1. A body that fails shows the table's existing "could not be read" state. No comparison computes a rate.

**Backward compatibility, and the order of deploy.**

| Order | What a reader sees | Why |
| --- | --- | --- |
| Backend first, panel later (the order of § L) | The older panel shows exactly what it shows today | Its check ignores keys it does not know. |
| Panel first, backend later | The strategy's performance block shows its error with "Try again", AND each row of the Strategies list shows its figures as unreadable. The rest of both pages works. | The new check refuses a `by_pair` entry without the fields, and that check is part of the whole report's (U14). A refusal, not a crash, and it ends when the API restarts. |

The second row is wider than decision 43's, which lost one section. It is accepted because the alternative is a table that prints a rate it was not given. It cannot happen in production under the order of § L, and not at all today (U17).

### H. Layering, and the non-negotiable rules

| Component | Layer | File | Change |
| --- | --- | --- | --- |
| `PairStats.win_count`, `PairStats.win_rate` | **domain**/performance | `performance/domain/by_pair.py` | Two fields, no default. Pure `Decimal`, no new import. |
| `PairBody.wins`, `PairBody.win_rate` | **infrastructure**/performance | `performance/infrastructure/performance_router.py` | § G. `win_rate` is the existing `Ratio`. |
| `parse_webhook_origin(raw)`, `InvalidWebhookOrigin` | **domain**/signals | `signals/domain/webhook_origin.py` (new) | Pure: a string in, a normalised origin, "unset" or a refusal with its reason out. Imports `urllib.parse` from the standard library and nothing else. |
| `Settings.webhook_public_origin` | shared configuration | `shared/config.py` | One field, default empty. No validator on the class: a validator would fail at import, with a traceback and no alert. |
| `webhook_origin_router`, `WebhookOriginBody` | **infrastructure**/signals | `signals/infrastructure/webhook_origin_router.py` (new) | `GET /webhook-origin`, the bearer dependency on the router. Included under `/api` in `main.py`. |
| `log_webhook_origin(settings)` | **infrastructure**/signals | `signals/infrastructure/webhook_origin_check.py` (new) | Called in `lifespan` inside `operator_alerts`, after `assert_panel_dist_ready`. Logs; never raises. |
| The INFO line of a changed share | **application**/strategies | `strategies/application/update_strategy.py` | § J. No new port. |
| `StrategyView.allocation_percent` in plain notation | **infrastructure**/strategies | `strategies/infrastructure/router.py` | The `Money` annotation of `shared/infrastructure/wire.py`. |
| `ShareAmount`, `share_amount(total, share, minimum)`, `step_amounts(total, minimum)` (added 2026-10-06) | **domain**/allocation | `allocation/domain/share_preview.py` (new) | Pure. The amount is `requested_from_percent`, imported from `allocation/domain/percent.py`, never rewritten. `below_pool_minimum` is `amount < minimum`. `step_amounts` is the same function for 1 to 100. Imports `decimal` and `dataclasses`. |
| `PoolSizing`, `PoolSizingPort.read(exchange, venue, settlement_currency)` | **application**/allocation | `allocation/application/ports.py` | Consumer-declared. Answers the pool's minimum order and its snapshot (total, instant read, stale), or no snapshot. Read-only by its shape: it has no write. |
| `PreviewShare(sizing).preview(pool, share)`, `SharePreview` | **application**/allocation | `allocation/application/preview_share.py` (new) | One read of the port, then the domain functions. No lock, no commit, no clock of its own. |
| `SqlAlchemyPoolSizing` | **infrastructure**/accounts | `accounts/infrastructure/pool_sizing.py` (new) | One SELECT: the `capital_pools` row outer-joined to its `pool_balance_snapshots` row. `stale` by `balance_snapshot_max_age_seconds`, the rule `SqlAlchemyPoolOverview` applies. The provider owns the adapter, as with `PoolBalancePort`. |
| The `share-preview` route, `SharePreviewBody` | **infrastructure**/strategies | `strategies/infrastructure/router.py` | § C2. It loads the strategy (the 404), takes its pool and its stored share, and calls `PreviewShare`. The bearer dependency is the router's. |

- **No use case and no port for the origin.** The route reads a setting through a pure function, as `webhook_secret_router` reads its setting directly. A class between them would hold nothing.
- **`domain/` gains no framework import.** The win count is arithmetic over dataclasses; the origin parser is the standard library; the share's amount is the existing pure function.
- **Why the preview does not reuse `PoolBalancePort`.** The worker's adapter REFUSES a stale snapshot, by raising, and reads a pool map the worker keeps (`accounts/application/pool_balance_adapter.py`; `accounts/infrastructure/db_balance_source.py:43-56`). That refusal is right for sizing a trade and wrong for a display, which must show a stale figure and say it is stale. So the preview has its own read-only port. `decide()` and the allocation path are not touched.
- **The API process still decrypts nothing and signs nothing.** The preview reads two database rows. No venue is called, no vault row is opened, no transport is built. The per-pair minimum, which would need a venue read, is not in this unit (§ C3).
- **Frontend**, container and presentational: `PoolShareEditor` (container: the draft, the save, the states, the preview) over `ShareSlider` (presentational: the field, the track, the legend) and `ShareAmount` (presentational: the amount, its state lines, the warning); `share-value.ts` (pure: read, parse, round, position); `InlineStatus`; `InfoDisclosure` (a hook and two presentational parts, § B2, added 2026-10-06); `shared/lib/clipboard.ts`; `shared/lib/useDebouncedValue.ts`; `shared/api/webhook-origin.ts`; `shared/api/share-preview.ts`; `webhook-url.ts` (pure: the assembly). Modified: `shared/api/strategies.ts`, `shared/api/types.ts`, `shared/api/performance.ts`, `StrategyDetailPage.tsx`, `AllowedPairsEditor.tsx`, `WebhookMessage.tsx`, `PairStatsTable.tsx`, `features/overview/format.ts`, `features/strategies/format.ts`, both locale files, `test/keyboard.ts`, `shared/theme.test.ts`.

| Rule | Impact |
| --- | --- |
| `DRY_RUN` (rule 1) | Nothing here differs by mode and nothing needs a credential. No test needs one. |
| Idempotency (rule 2), webhook (rule 3) | Untouched. The webhook's route, its authentication and its 3-second budget do not change; the new setting is display only and cannot stop the process that serves it. |
| Allocation transaction (rule 4) | Untouched. The PATCH takes the strategy's row lock and no advisory lock, as today, so no lock order changes. The share is read before the pool lock and only an amount enters it (U3). The preview is OUTSIDE that transaction by design: it takes no lock, reserves nothing and decides nothing. It is an estimate, and the read, the decision and the reservation of a real allocation still happen together under the pool's lock. |
| Pools (rule 5), PnL in native currency (rule 7) | A win is the sign of a PnL in its pool's own currency. A win rate is a ratio of counts within one strategy, which is one pool; nothing is summed across pools or converted. The preview reads ONE pool, the strategy's own, and every amount in it is in that pool's settlement currency. |
| Ledger (rule 6) | Read only. |
| Credentials (rule 8) | Untouched. The webhook secret is not a vault credential; § E and § F keep it out of every log, state and request. The preview needs no key (§ C2). |

### I. Texts (proposed, for the owner's review)

Two are the owner's own words (decision 48): "Saved" / "Guardado" and "Copied" / "Copiado". Every other line is a proposal.

| Key | EN | ES |
| --- | --- | --- |
| `strategies.detail.share.label` | Share of the pool per trade | Porcentaje del pool por operación |
| `…share.info` (added 2026-10-06; the NAME of information button 1) | About the share of the pool | Acerca del porcentaje del pool |
| `…share.hint` (**behind button 1**) | Each new operation asks for this share of the pool's total balance. A change applies from the next operation; one already open keeps its size. | Cada nueva operación pide este porcentaje del saldo total del pool. Un cambio se aplica desde la próxima operación; una ya abierta mantiene su tamaño. |
| `…share.amountInfo` (added 2026-10-06; the NAME of information button 2) | About this amount and what is not checked | Acerca de este importe y de lo que no se comprueba |
| `…share.amount` (added 2026-10-06) | Asks for about {{amount}} {{currency}} per operation | Pide alrededor de {{amount}} {{currency}} por operación |
| `…share.amountHint` (**behind button 2**, first paragraph) | An estimate: this share of the pool's total balance, read at {{time}} UTC. The balance is read again when an operation opens, and the pool grants less when less is free. It is margin; the position is this amount times the account's leverage. | Es una estimación: este porcentaje del saldo total del pool, leído a las {{time}} UTC. El saldo se vuelve a leer cuando se abre una operación, y el pool concede menos cuando hay menos disponible. Es margen; la posición es este importe por el apalancamiento de la cuenta. |
| `…share.amountStale` | The pool's balance was last read at {{time}} UTC and may be out of date. | El saldo del pool se leyó por última vez a las {{time}} UTC y puede estar desactualizado. |
| `…share.amountNoBalance` | The pool's balance has not been read yet, so the amount cannot be shown. | El saldo del pool todavía no se ha leído, por lo que no se puede mostrar el importe. |
| `…share.amountLoading` | Calculating the amount… | Calculando el importe… |
| `…share.amountError` | The amount could not be loaded. | No se pudo cargar el importe. |
| `…share.belowPoolMinimum` | At this balance the share asks for less than the pool's minimum order, {{minimum}} {{currency}}. Openings would be skipped until the share or the balance is larger. | Con este saldo, el porcentaje pide menos que la orden mínima del pool, {{minimum}} {{currency}}. Las aperturas se omitirían hasta que el porcentaje o el saldo sean mayores. |
| `…share.pairMinimumNote` (**behind button 2**, second paragraph) | Each pair also has a minimum order at the exchange, which depends on its price and on the account's leverage. The panel does not check it. A signal whose order would be too small is refused and nothing is opened. | Cada par tiene además una orden mínima en el exchange, que depende de su precio y del apalancamiento de la cuenta. El panel no la comprueba. Una señal cuya orden fuera demasiado pequeña se rechaza y no se abre nada. |
| `…share.valueText` | {{value}}% of the pool | {{value}} % del pool |
| `…share.stop` | Set the share to {{value}}% | Fijar el porcentaje en {{value}} % |
| `…share.notNumber` | Enter a number, for example 25 or 33.5. | Escriba un número, por ejemplo 25 o 33,5. |
| `…share.outOfRange` | The share must be above 0 and at most 100. | El porcentaje debe ser mayor que 0 y como máximo 100. |
| `…share.save` | Save share | Guardar porcentaje |
| `…share.saving` | Saving… | Guardando… |
| `…share.saveFailed` | The share was not saved. Try again. | El porcentaje no se guardó. Inténtelo de nuevo. |
| `…share.archived` | This strategy is archived and can no longer be changed. | Esta estrategia está archivada y ya no se puede modificar. |
| `…share.gone` | This strategy no longer exists. | Esta estrategia ya no existe. |
| `…share.unreadable` | The stored share could not be read, so it cannot be edited here. | No se pudo leer el porcentaje guardado, por lo que no se puede editar aquí. |
| `strategies.detail.saved` | Saved | Guardado |
| `strategies.webhook.copyUrl` | Copy URL | Copiar URL |
| `strategies.webhook.copyMessage` | Copy message | Copiar mensaje |
| `strategies.webhook.copied` | Copied | Copiado |
| `strategies.webhook.copyFailed` | Could not copy. Select the text and copy it by hand. | No se pudo copiar. Seleccione el texto y cópielo a mano. |
| `strategies.webhook.hostUnset` | No public host is configured for the webhook, so only the path is shown. Put your webhook's host in front of it. | No hay un host público configurado para el webhook, por lo que solo se muestra la ruta. Anteponga el host de su webhook. |
| `strategies.webhook.hostError` | The webhook's host could not be loaded, so only the path is shown. | No se pudo cargar el host del webhook, por lo que solo se muestra la ruta. |
| `strategies.performance.byPair.winRate` | Win rate | % acierto |

The existing keys are reused unchanged. **Revised 2026-10-06 (decision 48):** the three explanatory sentences are no longer on screen. Their wording is unchanged; each is now the content of the information button named beside it in the table, and the only new texts are the two buttons' names. Every other line of the table is always visible when its state applies (§ B2). Palette tokens only: `gain` for the handle, the filled track and the reached stops, `rule` and `rule-strong` for the rest of the track, `ink`, `ink-2`, `ink-3`, `loss`, `panel`, `ground`; no hex and no `var()` in a `className`. The warning under the amount is `loss` (§ C3). None of the new components uses the amber `decision` colour, so the allow-list of `panel-tokens.test.ts` does not change.

### J. What fails here without a log line?

Backend lines carry ids, counts and reasons. None carries the webhook secret, a credential, a DSN or the raw text of a refused setting. The browser has no log, so a panel failure must be visible on screen or pinned by a test.

| Failure | What the owner sees | The line, or why none |
| --- | --- | --- |
| **The share is changed and nobody can tell when or from what** | The new value | INFO in `UpdateStrategy`, only when the value actually changed: strategy id, old value, new value. Today the PATCH logs nothing (U2). |
| The PATCH refuses: archived, unknown id, out of range | The refusal's text (§ C) | None, as for every other refusal of this router today. The 4xx is in the access log, and the owner is looking at the reason. |
| The panel sends a wrong value (a field other than the share, a number instead of a string, a value the owner did not see) | A wrong position size at the next opening | Nothing can log it: the server sees a valid request. Pinned by a test of the exact request body, and by the field and the handle being views of the one value that is sent. |
| The handle is moved by a slip and never saved | Nothing changes | None needed. This is why the control has a Save button (decision 48). A test pins that no request is made before Save. |
| "Saved" shows although nothing was saved | A false confirmation | Cannot be logged. The flag is set only from a 200 whose body passed the strategy check; one test per refusal asserts its absence. |
| The stored share is not a plain decimal | "The stored share could not be read", no control | The browser has no log. The backend change of § C removes the one known way to produce it. |
| A refetch after a successful save fails | The share shows the confirmed value, because the answer was written to the cache. The allowed pairs show the old list and no "Saved" (§ D). | None. The query's own error state covers the page. |
| **The clipboard holds something other than what the owner believes** | Prevented: "Copied" beside the URL goes when the secret is shown or hidden, or when the host arrives (§ E, decision 48) | Cannot be logged. Pinned by tests in both directions, each with its mutation (§ K). |
| The browser refuses the copy, or has no clipboard | "Could not copy…" instead of "Copied" | The browser has no log, and the text must never be written to a console. The failure text is the trace. |
| A copy triggers a request for the secret | The secret would be fetched without "Show secret" | Cannot be logged. The existing test that clicks every other button (U16) now clicks both Copy buttons, and a dedicated test counts the requests. |
| `WEBHOOK_PUBLIC_ORIGIN` is unset | The path alone, and the sentence that says no host is configured | INFO at startup, once: the setting is not set and the panel shows the path only. |
| `WEBHOOK_PUBLIC_ORIGIN` is malformed | The same as unset | **ERROR at startup, once**, naming the setting and the reason, never the value. ERROR so that it reaches the alert channel: on screen it cannot be told from unset. The API starts. |
| `WEBHOOK_PUBLIC_ORIGIN` is well formed and wrong (another host, a typo that is still a host) | A full URL that TradingView will post to the wrong place | Nothing can know. INFO at startup prints the normalised origin, so the journal shows what is being served. The sentence a failed alert leaves is TradingView's, not ours. Stated as a limit (§ M). |
| The origin's route fails, or does not exist on an older API | The path alone, and "could not be loaded" | None in the browser. A 404 is in the API's access log. |
| The panel is given an origin it does not accept | The path alone, and "could not be loaded" | None. The backend's normalisation is tested to produce only values the panel's check accepts, with one shared list of cases. |
| A win is miscounted (zero counted as a win, a dry-run operation counted) | A wrong percentage that looks right | Cannot be logged: no data is at fault. Pinned by tests with their mutations (§ K). |
| `wins` and `win_rate` disagree, or a row lacks one | "The figures by pair could not be read", or the report's error | The browser has no log. A wrong figure is never drawn. |
| A rehearsal trade reaches `by_pair` | The existing 500 | The existing ERROR of `require_live_only`. |
| A `style` prop is added later and the CSP silently drops it on the day the panel is served | A control drawn in the wrong place, in production only | Cannot be logged. The source guard of § B turns it into a red test. |
| The slider is drawn wrongly in one browser (a misplaced handle, no filled part) | A control that works and looks broken | Cannot be logged or tested in jsdom. It is on the list of the owner's review by eye (§ K). The value in the field is always the truth. |

**Added 2026-10-06, for the amount and the minimum.**

| Failure | What the owner sees | The line, or why none |
| --- | --- | --- |
| **The amount on screen is not what the next operation asks for** | A figure that was true of the balance shown | Nothing is at fault and nothing can log it: the balance is read again when a signal is sized (U20). The amount says "about" on screen; that it is an estimate, and when the balance was read, are behind its information button (§ B2). |
| The balance behind the amount is stale | The amount, with the sentence that the balance may be out of date | Nothing in this read. A snapshot that stays old is already an ERROR of the watchdog (`watchdog_snapshot_max_age_seconds`), and the worker refuses to size against it. A line per page view would be noise. |
| The pool has no snapshot at all | "The pool's balance has not been read yet…" and no amount | None here: `balance: null` is a normal answer for a pool nothing has synced. The same watchdog reports it. |
| The strategy's pool has no row in `capital_pools` | The amount's error line; the slider still works | 500 with one ERROR naming the strategy and the pool. A strategy cannot be registered on a pool that does not exist, so this is a fault in stored data. |
| The preview fails, or its body is refused, while the owner works | "The amount could not be loaded." The field, the track and Save keep working. | The browser has no log. A 5xx is in the API's log. A drag sends no request, so a drag cannot fail (§ C2). |
| A typed decimal's amount arrives after the value has changed again | The figure of the value now in the field, or the loading mark; never the earlier one | Cannot be logged. The answer is used only when its `exact.share` is the value asked, and a test with its mutation pins it. |
| The preview and the engine disagree on the minimum | A warning on a share that would be granted, or none on one that would be skipped | Cannot be logged: neither side is wrong alone. A test asserts that `below_pool_minimum` and `decide()`'s first rule agree just under, at and just over the minimum. |
| **A share is under the pool's minimum** | The warning under the amount, on a change AND on the stored value | Nothing at save time: it is a legitimate state and the save is allowed. When a signal then arrives, the existing WARNING of the skipped allocation (U25). |
| **A share is too small for one pair at the exchange** | No warning on the panel: it is not checked. The sentence that says so is behind the amount's information button, no longer on screen (§ B2). | The existing WARNING `ORDER_NOT_PLACEABLE` when a live signal arrives (U25). Under `DRY_RUN` nothing at all (U26). This is the known limit of this unit (§ C3, § M). |
| **The owner never opens the information button** (added 2026-10-06) | Nothing says that a minimum per pair exists and is not checked | Nothing can log what was not read. It is the cost of the owner's choice to take the explanations off the screen (decision 48), stated in § B2. The worker's refusal does not depend on the text. |
| An information button does nothing, or its text is on screen from the start | A dead glyph, or the three paragraphs back and the control buried again | The browser has no log. Tests pin both: closed at mount with none of the three sentences in the document, and each sentence present after its button is activated (§ K). |
| The `%` sign stands off the number in a browser without `field-sizing` | A field that works and reads "33.5 %", about one character apart; measured as the behaviour of `size` alone in Chromium | Cannot be logged or seen in jsdom. Tests pin the `size` attribute and the `field-sizing` class; the look is on the list of the review by eye, in an engine without the property, with the mirrored span as the fallback there (§ B). |
| A press in the empty part of the field does not reach the input | The owner taps the field and no caret appears | The browser has no log. A test presses the wrapper outside the input and asserts that the input has focus. |
| A strategy with no allowed pair | Nothing changes: the amount and the pool's minimum do not depend on the pairs | None needed here. Every opening of such a strategy is already refused with its own WARNING, and saving an empty list is refused by the pairs editor. |
| A venue that cannot be read | Nothing: this unit reads no venue for the share, so the control, the amount and the warning do not depend on one | None. A check per pair would need such a read, which is why this unit has none. |
| The panel multiplies the balance itself | A second, unreviewed money computation | Cannot be logged. The amount component takes strings from the preview and nothing from `['pools']`; a test renders it with a pool balance that would give another figure and asserts the served one. |

**Threat matrix.** The skill's matrix stays N/A: no shell, subprocess, VCS automation or process integration. Four project rows (the fourth added 2026-10-06):

| Threat | Safe behaviour | RED test |
| --- | --- | --- |
| The new `/api` route ships without auth | The bearer dependency is on the router | 401 without the token and with a wrong one, in the pattern of the webhook-secret router's test. |
| The origin's value carries a credential, or the route's body carries the webhook secret | A value with a user or a password is refused and its text is never logged; the body is the origin or null | The parser's refusal case, a log capture that searches every record for the raw value, and the existing secret sweep over the route table. |
| The origin becomes something the browser requests | It is rendered as text and written to the clipboard only | No request made by the page starts with the origin, and the URL is not inside an anchor. |
| The preview route ships without auth, or serves another strategy's pool | It is a route of the strategies router, whose bearer dependency is structural; the pool is taken from the strategy row the path names, never from the request | `tests/strategies/infrastructure/test_router_auth.py` enumerates that router's routes, so the new one is covered without being listed. Two strategies on two pools: each path answers its own pool's currency and balance. |

### K. Testing strategy

| Layer | What | How |
| --- | --- | --- |
| Unit, domain | The win count and rate in `by_pair`; `parse_webhook_origin` | Pure. Hand-built `ClosedTrade`s; a table of origin cases. |
| Unit, application | The INFO line of `UpdateStrategy`: written on a real change, absent when the share is unchanged or another field is patched | The existing fakes, `caplog` |
| Router | `PairBody`'s two fields; the origin route (set, unset, malformed, 401); the startup line of each case, and that a malformed value does not raise; the PATCH's plain notation | `httpx.AsyncClient` over ASGI |
| Integration, real PostgreSQL | The strategy report end to end with wins; a PATCH of the share leaves every existing reservation row unchanged | The existing fixtures of `tests/performance/infrastructure` and of the strategies router |
| Frontend, pure | `share-value.ts` (read, parse, round, position); `webhook-url.ts`; `rateText` | Vitest, tables of cases |
| Frontend, components | `ShareSlider`, `PoolShareEditor`, `InlineStatus`, the two Copy buttons, the URL with its host, the Win rate column | Vitest, `vi.stubGlobal("fetch")`, a stubbed `navigator.clipboard` |
| Unit, domain (added 2026-10-06) | `share_amount` and `step_amounts`: the amount equals `requested_from_percent` for the same inputs; the hundred steps; a total of zero; the minimum's edge | Pure. A table of totals, shares and minimums. |
| Unit, application | `PreviewShare`: a snapshot, a stale one, none; the default share and an asked one | A fake `PoolSizingPort` |
| Integration, real PostgreSQL | `SqlAlchemyPoolSizing` against real `capital_pools` and `pool_balance_snapshots` rows: a synced pool, a pool never synced, a stale snapshot, a pool with no row. The route end to end for two strategies on two pools. | The existing fixtures of `tests/accounts/infrastructure` |
| Router | The `share-preview` body field by field; `balance` null with `exact` null and `steps` empty; the 404; the 422 of a bad `share`; no JSON float in the body | `httpx.AsyncClient` over ASGI. The existing walk for a JSON float or an exponent is taught the new route. |
| Frontend | `fetchSharePreview` and its check; the lookup of § C2 row by row; the debounce; the six states of the amount; the warning; `useDebouncedValue` | Vitest with fake timers, `vi.stubGlobal("fetch")` |
| Frontend (added 2026-10-06, second revision) | `InfoDisclosure`: closed at mount, open on activation, the attribute, Escape, both open at once, the names. The field's wrapper: the `size` attribute, the sign as the input's next sibling, the press that focuses the input. | Vitest, the existing `pressTab`, `pressEnter` and `pressSpace` |

**Rules that bind the task breakdown.**

- **Strict TDD.** Each RED fails on an ASSERTION. New fields and functions are first added as stubs that compile and answer WRONGLY: `win_count` 0 and `win_rate` 0; a parser that returns its input; a route that always answers null; a slider whose field never follows the handle; a copy that reports success without writing; a preview whose every amount is zero and whose `below_pool_minimum` is always false; an amount line that prints the first step's figure for every value.
- **The stubs of the second revision.** For the disclosure: a button that is rendered with `aria-expanded="false"` and never opens, so "after activation the sentence is in the document" and "`aria-expanded` is true" fail on their assertions. For the field: an input with a fixed `size` of 12 and the sign placed before it, so "`size` equals the length of the text" and "the sign is the input's next sibling" fail on theirs. "Closed at mount" passes at once against that stub and is proven by its mutation in the table below.
- **No lock-hold harness applies.** This unit takes no new lock and has no second actor that must wait. The PATCH's row lock and its serialisation against a concurrent toggle are already tested (`tests/strategies/infrastructure/test_update_strategy_concurrency.py`). The preview takes no lock at all, and one test asserts exactly that: on real PostgreSQL, a preview completes while another connection still HOLDS the pool's advisory lock. It is the lock-hold harness used the other way round: here the second actor must NOT wait, so a later edit that makes the preview queue behind an allocation turns the test red.
- **The preview and the engine are tested against each other, not each alone.** For amounts just under, at and just over the pool's minimum, `below_pool_minimum` must equal "`decide()` answers `REQUEST_BELOW_MIN_ORDER_SIZE`" for the same request and rules. And for a table of totals and shares, the preview's amount must equal what `requested_from_percent` returns. Neither function is reimplemented in a test.
- **Symbol spellings.** The win count crosses a module boundary on a symbol, so the fills are written as `STXUSDT.P` (TradingView's) on the opening side and `STXUSDT` (the venue's) on the closing side, a second strategy's as `STXUSDT_PERP` (Pionex's), and the report is asserted under the pair `STXUSDT`. No assertion compares two spellings as text.
- **One shared list of origin cases.** The backend's accepted cases, normalised, are the panel's accepted cases; the same list of strings is asserted on both sides, so the two checks cannot drift apart silently.
- **A new test helper is needed.** `frontend/src/test/keyboard.ts` gains `pressRangeKey(key)`, which stands for the browser's default action on a focused range input, as `pressEnter` stands for a button's: an arrow adds or removes one `step`, Home sets `min`, End sets `max`, the result is clamped, and nothing happens when the keydown was prevented or the input is disabled. It then fires the input and change events. What a test proves with it is the markup's side: a real, enabled range input with the right `min`, `max` and `step`, and no handler that swallows the key. Page Up and Page Down are not modelled: their step is the browser's.
- **The existing test that clicks every other button** (U16) will now click the stops, the two information buttons, Save and both Copy buttons, so it can send a PATCH. Its fetch double must answer one; the assertion, that no request for the secret was made, does not change.
- **Mutations that prove the tests which pass at once.**

  | Test | Mutation that must turn it red |
  | --- | --- |
  | A PnL of exactly zero is not a win (3 wins, 1 zero, 1 loss read 3 and `0.6`) | `>` becomes `>=` |
  | A zero still counts in the total | The zero trade dropped from the denominator |
  | A trade with incomplete fees and one with no capital at open are counted | Either filtered out of the count |
  | The report's wins are the same with and without rehearsal groups in the ledger | The read concatenates the two sets (decision 43's own mutation) |
  | A malformed origin does not stop the start | The check raises |
  | The ERROR of a malformed origin does not contain its text | The value interpolated into the message |
  | An unset origin logs INFO, not ERROR | Unset treated as malformed |
  | No request is made until Save, whatever is moved, activated or typed | A save on the change event |
  | Leaving the page after a change sends nothing | A save on unmount |
  | The request body is exactly `{"allocation_percent": "33.5"}` | `enabled` added to the body; and, separately, the value sent as a number |
  | A stored `33.5` shows `33.5` in the field with the handle at 34 | The field given the handle's value |
  | Moving the handle from a stored `33.5` writes a whole number | The decimal kept on a move |
  | `33,5` is sent as `33.5` | The comma rule removed |
  | `0`, `100.5`, an empty field and `abc` each leave Save disabled | That case's check removed (one case each) |
  | A stale draft is dropped when the stored value moves | The `base` comparison removed |
  | "Saved" is still there ten minutes later | A timer that clears it |
  | "Saved" goes at the next change of that control, and only of that control | The reset removed; and, separately, one flag shared by both controls |
  | No "Saved" after each refusal (one per status) | The flag set on settle instead of on success |
  | The live region exists before the save | The region rendered only with its text |
  | An archived strategy's track, stops, field and Save are disabled | The `disabled` removed from one of them |
  | The copied text equals the text of the `<code>` element, hidden and revealed | A second assembly of the URL in the handler |
  | A copy makes no request | The handler calling the secret's refetch |
  | A missing clipboard and a rejected write both show the failure text | The `false` branch reporting success |
  | "Copied" moves to the other button and goes when the block is closed | Two independent flags; and, separately, the block hidden with CSS instead of unmounted |
  | The URL is copied with the placeholder, then the secret is shown: "Copied" is gone. And the reverse: copied revealed, then hidden. | The clearing removed from the Show handler; and, separately, from the Hide handler |
  | After that, showing the secret again does not bring "Copied" back | The state kept and only hidden by the render check |
  | The URL is copied as the path alone, then the host loads: "Copied" is gone | The render check of the recorded booleans removed |
  | The alert message's "Copied" survives showing and hiding the secret | The handlers clearing every copy state instead of the URL's |
  | The preview's amount equals `requested_from_percent` for the same total and share | The amount rounded half up; and, separately, computed from `available` instead of `total` |
  | `below_pool_minimum` agrees with `decide()` at the minimum itself | `<` becomes `<=` |
  | A pool with no snapshot answers `balance` null, `exact` null and no steps | A zero total substituted for the missing snapshot |
  | A stale snapshot is served and marked | The stale snapshot refused, as the worker's reader does |
  | Each strategy's preview is its own pool's | The pool taken from a query parameter, or the first pool read |
  | The preview is answered while the pool's advisory lock is held elsewhere | An `acquire` of that lock added to the read |
  | A drag across the track sends no request | The amount asked per value |
  | Every whole value shows the amount of its own step (asserted for 1, 25, 34 and 100 with four different figures) | An off-by-one in the lookup; and, separately, the first step shown for all |
  | A typed `33.5` shows no figure until its answer, and then that answer's | The previous amount kept on screen while loading |
  | Two typed values in quick succession send one request, for the last | The debounce removed |
  | An answer whose `exact.share` is not the value asked is refused | That comparison removed |
  | A body with 99 steps, or with a balance and no steps, is an error | The pairing check removed (one case each) |
  | A failed preview leaves the field, the track and Save usable | The control disabled on the preview's error |
  | The amount shown is the served string cut down, never the pool's balance multiplied | The component reading `['pools']` and multiplying |
  | `4.996` reads "4.99", not "5.00" | `Intl` given the unrounded number |
  | The warning shows for a stored share under the minimum, with no change made | The warning tied to the draft |
  | Save is enabled while the warning shows | Save disabled on `below_pool_minimum` |
  | `0.5` is accepted and can be saved | A lower bound of 1 on the field |
  | At mount none of the three explanatory sentences is in the document, in English and in Spanish | A disclosure open by default; and, separately, a sentence rendered outside its container |
  | Activating the label's button shows `…share.hint` and only that; activating the amount's shows `…share.amountHint` and then `…share.pairMinimumNote`, in that order | The two contents swapped; and, separately, the per-pair sentence dropped from the second |
  | The warning on the pool's minimum, the stale line, the validation text and a refused save are in the document with both buttons closed (one case each) | That line moved inside a disclosure's container |
  | Each button has `aria-expanded`, an `aria-controls` that names an element present while closed, and a name that says what it explains | The container rendered only while open; and, separately, both buttons named "Info" |
  | Both explanations can be open together; closing one leaves the other | One shared open state |
  | Escape on a button, or inside its text, closes that one and leaves focus on its button | The key handler removed; and, separately, focus left on the body |
  | An open explanation is still open after a save, after a refused save and after the language changes, and is closed for another strategy | The open state reset on every render; and, separately, the control not keyed by strategy |
  | Tabbing away from an open explanation leaves it open | A close on blur |
  | Both buttons are enabled on an archived strategy and while saving | `disabled` passed to them with the rest of the control |
  | The amount's button is present with a figure, with the em dash, with no balance and with a failed read | The button rendered with the figure only |
  | Each information button has the 44 px box classes and an `aria-hidden` SVG glyph with no `style` attribute | The box class removed; and, separately, the glyph replaced by a text character |
  | The field's `size` is the number of characters typed, for `5`, `33.5`, `100` and twelve characters, and 1 when empty | A constant `size`; and, separately, `size="0"` for the empty field |
  | The input carries the `field-sizing` class and the one-character minimum width (a class assertion; jsdom cannot see the width either gives) | Either class removed |
  | The `%` sign is the input's next sibling inside the wrapper, is `aria-hidden`, and is not part of the input's value | The sign appended to the value; and, separately, the sign rendered at the wrapper's far end |
  | A press on the wrapper outside the input moves focus to the input; on a disabled control it does not | The handler removed; and, separately, the handler ignoring `disabled` |
  | The request body is still `{"allocation_percent": "33.5"}` with the sign beside the number | The sign read into the value |
  | Tab goes label's information button, field, track, 25, 50, 75, 100, amount's information button, Save | The field rendered after the track; and, separately, an information button given `tabIndex={-1}` |
  | Each stop is a button with a 44 px box, a name and `aria-pressed`, though it reads as a legend | The stop turned into a `<span>`; and, separately, the box class removed |
  | An origin with a path, a query, a user or a trailing slash is not used by the panel | The `new URL(value).origin === value` check removed |
  | With no origin the URL is the path alone, as today | An empty origin rendered as `null` or `undefined` text |
  | The URL is not inside an anchor and no request starts with the origin | The `<code>` turned into a link |
  | A `by_pair` row without `wins` or `win_rate` refuses the report (one case per field) | That field's check removed |
  | `wins` 0 with a rate above 0, and `wins` equal to `trades` with a rate below 1, read as unreadable | The agreement check removed |
  | The win rate has no sign and is in neutral ink | `percentText` and `toneClass` applied to it |
  | No source file has a `style=` prop | One `style={{}}` added anywhere |
  | The slider's rendered tree has no `style` attribute | The same, inside the slider |

- **What jsdom cannot prove, left to the owner's review by eye and to a real browser.**
  1. The look of the slider in Chrome, Firefox and Safari: the handle, the filled part, the stops under the handle's centre.
  2. Dragging by pointer and by touch; the arrow, Home, End and Page keys; the focus ring.
  3. The field above the track; the legend close under it; that a press just under the handle at a stop takes the stop and never blocks grabbing the handle; that the four targets never touch at 300 px.
  3a. The amount under the legend following the handle as it is dragged.
  3b. **The height of the control with both explanations closed**, which is what the owner sent the second prototype back for. Measured on the third prototype at 300 px: 252 px from the label to the Save row, against about 450 px with the three paragraphs on screen. That is the prototype, in system fonts; the panel's own must be looked at, and no test can measure it.
  3c. **The `%` sign, in two engines at least** (revised 2026-10-06 after the measurement of § B). In a Chromium-based browser, with the panel's font and not the prototype's system font: the sign touching the number at one digit, at `33.5`, at `100` and at twelve characters; an empty field with the sign one character from the left; the caret at the end not clipped. In a browser WITHOUT `field-sizing`, Firefox at least, and Safari if the owner uses the panel there: that the gap is about one character and no more at those same lengths, that the sign stays inside the field at twelve characters in a 300 px column, and **the owner's word on whether that gap may stay**. If it may not, the mirrored span is added for those engines and looked at there before it is trusted. jsdom knows the `size` attribute and the class, and nothing of the width either gives.
  3e. **What the approval of the third prototype did not cover** (§ M): the control in a second browser; the panel's fonts; the keyboard alone (Tab through the nine stops, Enter, Space and Escape on each information button, the arrow keys on the track); and a screen reader's reading of the two buttons' names, their expanded state and the opened text.
  3d. Each information button's 44 px box touching its neighbours and covering none; the glyph; the page moving down, not sideways, when an explanation opens.
  4. **The CSP**: the built bundle served by FastAPI with `PANEL_DIST_DIR` set, the strategy page open, no policy violation in the console (§ B).
  5. The clipboard in a real secure context, and its failure text over plain HTTP on another address.
  6. The By pair table's width in English and Spanish.
  7. Every text of § I, in both languages.
- **The owner's local fixture** (`vite.fixture.config.ts`, unstaged) must serve `wins` and `win_rate` on each `by_pair` entry, the `webhook-origin` route, a PATCH that answers the share it was sent, and the `share-preview` route with its hundred steps, one case under the pool's minimum and one pool with no balance. Without the first, the new panel refuses the report on that fixture (§ G), which would look like a defect and is the check working.
- **Gate after every unit.** Backend: `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`. Frontend: `npm run lint` and `npm test`.

### L. Delivery

Two sequential PRs to `main`, never stacked, split by deploy order and not by size.

```
 12f-1 backend: wins in by_pair, the webhook origin    ─►   12f-2 panel: the slider and its save, the amount
       setting and route, the share's log line and            and its warning, "Saved", the two Copy
       plain notation, the share-preview route                buttons, the full URL, the Win rate column
```

| PR | Contents | What changes for a user at deploy | Deploy | Risk | Rollback boundary |
| --- | --- | --- | --- | --- | --- |
| **12f-1** | `PairStats` and `PairBody` with wins; `parse_webhook_origin`, the setting, the route and the startup line; the INFO line of a changed share; the share written in plain notation; **(added 2026-10-06)** `share_preview.py`, `PoolSizingPort` and its adapter, `PreviewShare` and the `share-preview` route | Nothing visible. Two more fields on each `by_pair` entry, two new GETs, one more startup line. | Pull as `strategy`, restart both services. Setting `WEBHOOK_PUBLIC_ORIGIN` in the environment is the owner's step, at any time; until then the route answers null. | **Low.** Additive fields, two read-only routes, a setting that cannot stop the start. The preview reads two rows, takes no lock and touches no code of the allocation path: `percent.py` is imported, `decide()` is only called from a test. | A revert removes the two fields and both routes (their paths then answer 404). No data is touched. |
| **12f-2** | Everything of §§ B to G on the panel side, the amount and the warning of §§ C2 and C3, the texts, the keyboard helper, the source guard | Locally, and in production once the panel is served: the share can be changed and shows the amount it asks for, a share under the pool's minimum is warned about, a save and a copy are confirmed, the URL carries its host, By pair shows the win rate. | Pull as `strategy`, no restart (the panel is not served while `PANEL_DIST_DIR` is unset). | **Medium.** It is the first control of the panel that changes how much capital a strategy asks for. The value is a string, sent only on Save, checked at three layers on the server, and its request body is pinned by a test. The amount is display only: its failure cannot block or alter a save. | A revert restores the page as it is today, which works against the new API. |

- **Why two.** The panel refuses a `by_pair` entry without the new fields and reads routes that must exist, so the API is merged and running before the panel that asks (§ G). The panel PR is also the one the owner reviews by eye, and that review should not hold a finished backend change.
- **The preview against an older API.** The route answers 404 there, so the amount line reads "could not be loaded" and the slider works (§ C2). That is the same degradation as the host's, and narrower than the win rate's.
- **Why not three.** The slider, "Saved" and Copy need nothing from 12f-1 and could ship before it. Putting them in a PR of their own would be a split by size, which the owner does not want; and the win rate column, the URL and now the amount would then be a third PR for one page.
- **One PR for everything is possible**, because the panel is not served in production and the order hazard exists only on a developer machine today. The recommendation stays two, for the review-by-eye reason.
- **No migration.** The share's column exists since migration 0007. A win is derived at read time. The host is a setting. The pool's minimum and its snapshot are existing columns. So no rehearsal on a restored backup is needed for this unit.
- **No venue read is added, and no probe is needed.** The per-pair minimum, which would need both, is not in this unit (§ C3).
- **Forecast, as information only** (revised 2026-10-06, twice). 12f-1: 1,000 to 1,500 authored lines, of which the preview is about 400 to 600; the second revision changes nothing in the backend. 12f-2: 2,800 to 4,100, of which the amount and its warning are about 600 to 800 and the information buttons and the field's wrapper about 250 to 350, most of it tests. Both assume tests at about twice the production code, the ratio the last panel units ran at. `Decision needed before apply: No` (Q1 to Q5 are all answered) · `Chained PRs recommended: Yes` · `400-line budget risk: High`.

**Design decisions made here** (not owner decisions; each has its reason above):

| # | Decision | Section |
| --- | --- | --- |
| F1 | The slider is the native range input, restyled; the track, the filled part and the stops are an SVG drawn with attributes | B |
| F2 | No `style` prop is written anywhere in the panel, and a source test keeps it so | B |
| F3 | The stops are real buttons placed with one fixed class each. Revised 2026-10-06: they read as a legend, keep a 44 px box and their place in the tab order, and sit 12 px closer to the track | B, C |
| F4 | One decimal string is the value; the handle is its rounding, clamped to the track; a stale draft is dropped | C |
| F5 | The field is text with a decimal keypad, accepts one comma, and shows a dot in both languages | C |
| F6 | The save sends the share alone, as a string, and writes the checked answer into the cache | C |
| F7 | `UpdateStrategy` logs a changed share; the strategy view writes the share in plain notation | C, J |
| F8 | The Strategies list and the new-strategy dialog are not touched | C |
| F9 | One shared live text, always mounted, for "Saved", "Copied" and the copy failure; each control keeps its own flag | D, E |
| F10 | A copy takes the string already rendered; no `execCommand` fallback; the URL is never a link | E |
| F11 | The host is `WEBHOOK_PUBLIC_ORIGIN`, an origin and nothing more, parsed by a pure domain function | F |
| F12 | A malformed host is an ERROR at startup and is served as null; it is not a startup invariant | F, J |
| F13 | The host has its own authenticated route; `/health` is not widened | F |
| F14 | The panel accepts only a value equal to its own `URL.origin` and concatenates | F |
| F15 | Wins are counted in `by_pair`; the wire carries the count and the ratio; no report but By pair gains one | G |
| F16 | The win rate is unsigned, one decimal, neutral ink; no column is hidden | G |
| F17 | A `by_pair` entry without the fields refuses the report, at the cost of the list's figures against an older API | G |
| F18 | Two PRs, backend then panel | L |
| F19 | (2026-10-06) The field is above the track on its own row; nothing wraps. Revised the same day: the number and the `%` sign sit together at its left, inside a wrapper drawn as the field. Revised a third time after a measurement: the input is sized by `field-sizing: content` where the browser has it and by its `size` attribute elsewhere, which leaves about one character of gap there; a mirrored span is the fallback for those engines only | B |
| F20 | The amount is computed by the server with `requested_from_percent`; the browser multiplies nothing and the panel's rule is not revisited | C2 |
| F21 | One route serves the hundred whole steps and one exact value, so a drag sends no request; a typed decimal asks once, 300 ms after the last keystroke, and shows no figure meanwhile | C2 |
| F22 | The preview has its own read-only port and adapter; it does not reuse the worker's balance reader, which refuses a stale snapshot | C2, H |
| F23 | The figure is cut down to the currency's decimals as text, the direction the engine rounds | C2 |
| F24 | The minimum is a WARNING, not a refusal: on the pool's own minimum order, exact for the balance shown, on the stored value too, never blocking a save | C3 |
| F25 | The exchange's minimum per pair is not checked. It is a known limit of this unit, said behind the amount's information button and in §§ C3 and M. No later unit is recorded for it (decision 48) | C3, M |
| F27 | (2026-10-06, second revision) The explanations are behind two information buttons, each a disclosure in place; the per-pair limit shares the amount's button; warnings, validation, refusals and the lines that change what the figure means stay on screen | B2 |
| F28 | An explanation closes with its button or Escape, not on blur; both may be open; closed on every visit; never disabled | B2 |
| F29 | `InfoDisclosure` is one small piece beside `InlineStatus` in `features/strategies/`; its glyph is an inline SVG drawn with attributes | B2, D |
| F26 | "Copied" beside the URL is cleared by the Show and Hide handlers and guarded by a render check on two recorded booleans; the text is never kept | E |

### M. Risks, and what could be wrong in this design

| Risk | Why it matters | Mitigation or honest limit |
| --- | --- | --- |
| The panel has never been loaded under its CSP | A wrong belief about the policy would show only on the day the panel is served | The slider needs no runtime style (§ B). The check in a real browser is a task of 12f-2 and can be made locally. It also covers the fonts and the chart, which § 13 already asked to rehearse. |
| The restyled native control differs by browser | Vendor pseudo-elements are the least portable part of CSS; the filled part depends on the SVG lining up with a thumb whose size each engine must honour | The handle is the browser's and is always where the value is; a misalignment is cosmetic and at most a few pixels. The fallback is the unstyled native control with `accent-gain` (§ B). Reviewed by eye in three browsers. |
| The reference image was described to this design in words | Decision 48 records that the Binance order form reached the session on 2026-10-06. This addendum was revised from its description (a wide field on top, a thin track with a handle and four marks, the amounts under it), not from the image itself. | The three changes the owner named are the ones built. Proportions and spacing are the owner's review by eye; the structure does not depend on them. |
| **The owner's approval of the third prototype covers less than the control** | It was handled in ONE browser. It falls back to system fonts, not the panel's Archivo and IBM Plex. It had no pass with the keyboard alone and none with a screen reader. | Recorded as what is approved and what is not (decision 48). The panel PR's review by eye takes up exactly these: a second engine, the real fonts, the keyboard, a screen reader (§ K, 3c and 3e). The prototype is no longer behind the design: it shows both changes of the second revision. |
| **The `%` sign is exact only where `field-sizing` exists** | Measured in Chromium: with the property the sign touches the number; with `size` alone it stands about one character off. A browser without the property shows "33.5 %", which is not the "together" the owner asked for. Which browsers lack it was not verified, and none of them was rendered. | Accepted as a degradation, not as the result: nothing is misread and the sign stays beside the number. The review by eye looks at an engine without the property and the owner decides there. The fallback is the mirrored span for those engines only, measured before it is trusted (§ B). |
| A claim of this design was wrong until it was measured | The previous revision said `size` in a monospaced font makes an input as wide as its text. It does not in Chromium. | Withdrawn in § B with the numbers. The same caution applies to what is still unmeasured here: the mirrored span's cell width, and every engine but Chromium. |
| **The explanations are one activation away** | An owner who never opens the amount's button is told nowhere that the exchange's minimum per pair is unchecked, nor that the amount is margin and an estimate | The owner's choice (decision 48), after the alternative buried the control. The warning on the pool's minimum, the stale line and the word "about" stay on screen, and the worker's refusal protects the money whatever was read (§ B2). |
| A disclosure in place moves the page when it opens | Opening the label's explanation pushes the field and the track down under the pointer | **Accepted for now by the owner**, who saw it in the third prototype (decision 48, 2026-10-06). It opens only on the owner's own activation, never by itself, and nothing closes on its own. A floating layer would not move the page, and would need a computed position, which this panel does not write (§ B2). |
| The legend's targets overlap the lower 12 px of the track's box | A press there at a stop takes the stop instead of the track | It is the same value within a step, the handle itself is never covered, and it is on the list of the review by eye (§ K). If it feels wrong, the legend moves down 12 px and nothing else changes. |
| A value below 1 sits at the end of the track | The handle shows 1 for a share of 0.5 | Decided: a share below 1% is allowed (decision 48). The field and the screen-reader text show the exact value, and the warning says when its amount is too small. |
| **The warning covers the pool's minimum, not each pair's** | The owner asked for a share that is enough for the strategy's pairs. A share can pass the pool's minimum and still be too small for a pair with a large minimum quantity, and the panel then shows no warning. | A known limit of this unit, accepted by the owner: the warning on the pool's minimum is enough for now (decision 48, answered 2026-10-06). It is said behind the amount's information button (§ B2) and in § C3. The worker refuses such an order and reserves nothing (U25). |
| **Under `DRY_RUN` nothing refuses a share that is too small for a pair** | The simulated exchange applies no minimum (U26), so production today rehearses such a share without a complaint, and the first refusal would come live | Not caused by this unit and not fixed by it. It is part of the same known limit, and it is said here so that a quiet dry run is not read as proof. |
| The three guards that refuse a small allocation are WARNINGs | A strategy that skips every signal looks like one that never fires; nothing reaches the alert channel | Outside this unit. Raising the level, or showing signal outcomes in the panel, would be its own change. Flagged, not designed. |
| The amount is an estimate and reads like a figure | The balance moves, the grant can be less than the request, and the position is the amount times a leverage the panel cannot show | On screen the line says "about". That it is an estimate, when the balance was read and that it is margin are behind its information button (§ B2, § I); a stale balance is always said on screen. |
| The preview and the real request use different reads of the balance | The worker refreshes the balance on demand before it sizes; the preview shows the last snapshot, up to a minute old | Stated. Both use the same function on the same column, so they differ only by the balance's movement. |
| The table of a hundred steps is one read of the balance | An amount looked up a minute later is a minute old | It is refetched every 60 s, the cadence the balance itself is written at, and the line shows the time of the read. |
| The preview is a new place a strategy's pool is read | A wrong pool would show another pool's money | The pool comes from the strategy row the path names; a test with two strategies on two pools pins it (§ J). |
| The clipboard keeps the secret after it is hidden | "Hide secret" and leaving the view clear the screen and the cache, not the clipboard; a clipboard history may keep it longer | The owner's decision. The panel has no way to take a copy back. Stated in § E. |
| A well-formed, wrong host is shown with full confidence | The owner pastes it into TradingView and every alert goes elsewhere | The startup INFO prints what is served. No check can know the right host. A full URL is still less error-prone than a path the owner completes by hand. |
| The webhook host is now told to whoever holds the admin token | It links the panel to the webhook's address | The token already arms strategies and reveals the webhook secret. The host is public DNS. |
| The win rate near zero PnL | An operation with incomplete fees may be counted on the wrong side | Decision 44 accepts it and says so. The count follows the PnL the ledger gives. |
| One decimal can still round a loss away | At 2,000 closed operations of one pair, 1,999 wins read "100.0%" | `wins` is served, so the exact count is always available. Far beyond this system's volume per pair. |
| The new check refuses the list's figures against an older API | Wider than decision 43's degradation | Deploy order (§ L). Not reachable in production today. |
| A changed share has a log line and no history on screen | The owner reads the panel, not the journal | The enable switch has an event log; the share does not, and a table for it would be a migration and its own unit. Flagged, not designed. |
| The allowed pairs' "Saved" is not shown when the refetch after a successful save fails | A true save is not confirmed | It errs on the safe side. Fixing it means changing the existing hook, which is outside this unit. |
| The Spanish By pair table scrolls sideways | Five columns under long Spanish headings | The table already could. The lever is the existing headings, which decision 46's precedent would shorten; not done here. |

### N. Open questions for the owner

**No question is open.** Q1 to Q5 are all answered (owner-decisions.md, decisions 44 and 48), and the second revision of 2026-10-06 raised none: the information buttons, the sign beside the number and the legend's distance are the owner's own rulings, and what was left to the design (the mechanism, how many buttons, how the field is sized) is settled in § B and § B2. The questions are kept below with their answers so that the reasoning stays beside the design.

**Answered 2026-10-06, and removed from the list** (the record is owner-decisions.md, decision 48):
- **Q1, "Copied" after the URL changes: answered, option (b).** "Copied" beside the URL is shown only while the URL on screen is the one that was copied. Folded into § E.
- **Q2, a share below 1%: answered, with a new requirement.** A share below 1% is allowed. The share should be enough to trade the strategy's pairs, refused if not, or warned about if a refusal cannot be made in this unit. The design delivers the warning, on the pool's own minimum, and says why a refusal would not be true (§ C3). What it could not deliver was asked as Q5.

- **Q3. Should the header line of the page show the share?** The mockup prints it there ("Bybit USDT pool · 30% per trade · active 41 days…"). The page built in PR 12b does not, and it is not one of this unit's five pieces.
  - Default built: no. The share is shown and edited in the settings column only.
  - If wanted, it is one figure in the header, read from the same strategy and updated by the same save.
  - **Answered 2026-10-06: no.** The share is shown in the settings column only.
- **Q4. Win rate with one decimal, or whole as in the mockup?** The mockup shows "58%". The design proposes "58.3%".
  - Reason: a whole percentage rounds 199 wins of 200 to "100%", which reads as a perfect record. One decimal costs no width, because the heading is wider than the figure.
  - Default built: one decimal. Changing it is one argument of one function.
  - **Answered 2026-10-06: one decimal.**
- **Q5 (new, 2026-10-06). The exchange's minimum per pair: its own unit after this one, or is the pool's minimum enough?** The owner asked for a share that is enough to trade the strategy's pairs. This unit warns when the share asks for less than the POOL's minimum order, which the system knows exactly. It does not check each PAIR's minimum at the exchange, because that needs the pair's current price, which the API process does not read today, and the account's leverage, which it cannot read without the key. So a share can pass with no warning and still be too small for a pair whose smallest order is large; the worker then refuses that order and opens nothing, and under dry run nothing refuses it at all.
  - **Answered 2026-10-06: the warning on the pool's minimum order is enough for now.** No unit is recorded for a warning per pair.
  - What stands is the finding, as a known limit of this unit and not as later work: the exchange's minimum for each pair is not checked by the panel, the worker refuses an order that would be too small and opens nothing, and under dry run nothing refuses it (§ C3, § M).
  - The same day the owner moved the explanations behind information buttons, so the sentence that says this is no longer always on screen: it is the second paragraph behind the amount's button (§ B2).

### O. Points the specification raised, and how each is settled (2026-10-06)

Writing the delta specs showed nine things neither a decision nor the sections above stated. None is a product question; each is settled here so that the tasks do not have to guess.

- **The win rate is cut to one decimal, never rounded up.** The owner chose one decimal so that an imperfect record cannot read as a perfect one (decision 44). Rounding would undo that one step later: 1,999 wins of 2,000 is 99.95%, which rounds to "100.0%". So the figure is truncated toward zero at one decimal of the percentage: 99.95% reads "99.9%", and only a pair whose every closed operation is a win reads "100.0%". It is a text operation on the ratio the server serves, not arithmetic on money. The mirror case, a pair with one win in several thousand reading "0.0%", is accepted: it misleads nobody about a loss.
- **The amount is written with the pool currency's decimals**, as the PnL and the fees of the trades table are: two for USDT. It is cut, not rounded up, so the figure never shows more than the server computed.
- **The time of the balance's read** is written as hours and minutes in UTC, `HH:MM UTC`, the form the panel's dates already use for a time of day.
- **The server answers the wins and the trades as well as the ratio**, so the panel can refuse a row whose three figures disagree, and the ratio is the wire's `Ratio` type at its existing scale and rounding.
- **`PATCH /api/strategies/{id}` on an unknown strategy** keeps the 404 it answers today, with its existing body; this unit does not change it and the tests pin what is there.
- **The share-preview route echoes the exact share in canonical plain notation**: no exponent, no trailing fractional zeros, so `33.50` is answered `33.5`.
- **A share saved as the same value written differently logs nothing.** "Changed" is decided on the decimal value, so `33.50` over a stored `33.5` is not a change and writes no INFO line.
- **A typed decimal waits 300 ms** after the last keystroke before the amount is asked for. The number is this design's (§ C2) and is now a requirement.
- **The worker's refusal of an order too small for the exchange is stated by no requirement of this change or of the main specs.** It is real and was read in the code (U25: `OrderNotPlaceable`, the reservation released, `REJECTED` `ORDER_NOT_PLACEABLE`, nothing sent). The panel's sentence "a signal whose order would be too small is refused and nothing is opened" therefore rests on the code and on this design, not on a requirement. No requirement about the worker is written by this unit, which changes nothing in the worker; the gap is recorded here so that whoever next specifies order placement closes it.

**Points the task breakdown raised, settled the same day.** None is a product question.

- **The panel checks that a pair's ratio agrees with its counts, by comparing integers.** § G said the panel checks only the ends (a rate of 0 exactly when there are no wins, a rate of 1 exactly when every operation is a win) and that "no comparison computes a rate". The specification then required a row whose `win_rate` is not its `wins` over its `trades` to be refused, and the two cannot both stand: a row of 3 wins in 5 served as `0.7000000000` passes the end checks. **The specification stands, and it is met without computing a rate:** the ratio's digits are read as an integer `r` (the ratio times 10^10), and the row is accepted only when `|r × trades − wins × 10^10| ≤ trades`, with integers of arbitrary size. That is one unit of the ratio's last place either way, so it holds whichever way the server rounds, and it divides nothing. It supersedes § G's "the ends only" for this check; the end checks remain, as the cheap first test. Why it is worth its few lines: a wrong ratio would otherwise be drawn with full confidence, and the browser has no log.
- **The webhook origin's parser refuses three forms the table of § F did not list**: a bracketed IPv6 literal (TradingView does not post to IPv6, CLAUDE.md "External constraints"), a host that ends in a dot, and a port that is present and empty (`https://host:`). Each is malformed: the startup line is the ERROR of § J and the route serves null.
- **A strategy whose pool has no row** is told to the application by the sizing port answering nothing for that pool; the use case raises the module's invariant error, and the route answers the existing 500 with one ERROR, as the performance routes do. The foreign key from strategies to pools makes that state unbuildable in a real database, so it is tested at the use case with a fake port, and at the route by overriding the port; no test bends the schema to reach it.
- **`rateText` lives in `frontend/src/features/strategies/format.ts`**, beside `figureText`. It cuts first and formats second, and it writes the decimal separator and the percent sign the way the panel's existing percentage text does in each language, so the Win rate column and the PnL % column of the same page do not disagree on form. What that form is in Spanish is read from the existing function, not chosen here.
- **The amount under the track is cut by a helper in the same file**, using the decimals the trades table already uses for the pool's currency.
- **In the share's field, `.5` is refused and `007` is read as 7.** A value needs digits on both sides of its separator, the rule that already refuses `33.`; leading zeros change no value and the canonical form drops them, as it does for a stored value.
- **The INFO line of a changed share is written after the commit**, so that it never reports a change that was rolled back.
- **The owner reviewed the prototype in Firefox and by keyboard on 2026-10-06** (owner-decisions.md, decision 48): in Firefox it works and the percent sign follows the text; Tab goes through the stops, and Enter, Space and Escape behave. So the by-eye review of the panel PR no longer starts from "never seen in a second browser or by keyboard". It CONFIRMS both on the real panel, where three things differ from the prototype and were not seen: the panel's own fonts, the Content-Security-Policy with the built bundle served, and a screen reader. What mechanism Firefox applied to the field's width was not measured; if the sign stands a character off on the real panel there, § B's fallback is the answer.

**Added 2026-10-09 (decision 50).** Task 12f.9.12 found that the API took a share with any number of decimals, and that `1e-999999999` (12 characters) passes the range check and, written in plain notation for the preview, is a text of about 1 GB. Decision 50 settled it: a share has at most 18 decimal places on every input that takes one (the preview's `share`, the update's `allocation_percent` and the registration's), counted on the value as written and refused with the 422 that echoes no input before anything is formatted, computed or stored (task 12f.9.17). § A U1's "a stored value may have any number of decimals" is true only of values stored before this bound.

**Added 2026-10-10 (decision 52).** § D's "Saved" and § E's "Copied" are no longer texts beside their buttons: they are the buttons' own text (task 12f.10.30d). The owner saw "Saved" push the paragraphs and "Copied" narrow its row. When each shows and goes is unchanged, and so is the rule of one "Copied" on screen. A new `StatusButton` renders every text the button can show in one grid cell and shows one, with the others `invisible` and `aria-hidden`; the button is as wide as its longest text in the current language and its accessible name is the text shown. A Save button that reads "Saved" is disabled, so `handleSave` no longer clears "Saved" itself: a change has already done it. Because a change of a button's text is not announced, the always-mounted `InlineStatus` after each button is visually hidden (`sr-only`) and says "Saved" or "Copied" in the same states; it keeps its place and is the only status region of the button. A copy that failed is the one visible text left: "Could not copy" stays beside its button, in the loss colour, through the same region, and the button keeps its ordinary text. The region now follows the button in the document, where "Saved" used to precede it. This session chose the single width, the hidden region and the visible failure; the owner sees them in the next review by eye. The copy state still holds only which button and whether it worked.

**Added 2026-10-10 (decision 53).** § E's "each button writes exactly the text on screen" no longer holds for the URL (task 12f.10.30e). With the secret hidden the screen shows the placeholder, which does not work in TradingView, so "Copy URL" now asks the server for the secret at the click and writes the URL that works. `copyUrl` calls `fetchWebhookSecret` directly, not through `useWebhookSecret`, builds `webhookUrl(origin, encodeURIComponent(secret))` and hands it to `copyText`; the secret is a local value of that one handler, so it is in no state, no ref, no query-cache entry and no message, and "Show secret" is still the only thing that reveals it or puts it in the cache. A failed request, or a refused write, writes nothing and reads as a failed copy, so the placeholder URL never reaches the clipboard; the error is caught and dropped with no text. A `copyingUrl` flag, which holds no secret, disables the button while the request is in flight, so a second click sends no second request. With no host "Copy URL" is disabled (the path alone does not work either), while the host is loading, unset or unreadable. Because the clipboard now holds the same URL whether the secret is shown or hidden, "Copied" no longer goes when the secret is shown or hidden: the copy state records the host that was copied in place of whether the secret was shown, and "Copied" goes when the host on screen is no longer that one, or when the other button is used. "Show secret" and "Copy URL" are therefore the two clicks that ask for the secret, where one did; the rule of decision 23 stands, the secret is revealed only by "Show secret". What jsdom cannot say: whether Firefox lets the clipboard write through after an awaited request, since the browser may require the write to follow the user's click closely.

## Addendum: Settings, the exchange keys (PR 13, decisions 18, 20 to 22, 24, 30, 31 and 54) - 2026-10-10

PR 13, designed again by decision 54. HEAD `d926e71`. It supersedes, for the Settings page only: the Settings bullets of § 15 ("Key entry" and the `ExchangeKeyCard` line), the Settings paragraph of § Visual design, § G of the addendum "key policy after probe P6", and the mockup `visual/project/Settings.dc.html`. The tasks of PR 13 written on 2026-09-29 and 2026-09-30 (units 10c-card, 10f-form, 10d-delete) are superseded once new ones exist. Decisions 18, 20, 21, 22, 24, 30, 31, 52 and 54 are binding and are not reopened here. **Revised the same day by decisions 55, 57 and 58** (the owner's review of the prototype, and his answers to the two questions of § O): § D, § E, the end of a save in § F, § I, § J, § O and what follows from them. The list of what changed closes the addendum. The prototype for the owner's eye is `visual/project/SettingsKeys.html`; every English text in it is a text of § J, and its Spanish examples use the Spanish of § J's second table.

**The answer in one paragraph.** The API does not change. The page reads two routes that exist, `GET /api/credentials` and `GET /api/pools`, and one small list kept in the panel of the exchanges whose key the panel manages; a backend test keeps that list equal to the server's. `ApiError` gains one field, the response's own body, so the panel can read the lists the API already sends at the top level. One pure function decides the state of an exchange, and both the card and the tab draw from it, so they cannot disagree. The key form opens inside its card, one at a time, and closes by itself after a save that worked, with the result said on the card (decision 57). The typed key and secret are never React state: the two fields are uncontrolled, read once at the click, sent once, and emptied after every attempt (decision 54). The save is a plain function, not a mutation, that never throws and never keeps the error. The text of every refusal is chosen by the outcome or the status, never by the server's wording. After every attempt both lists are read again, and an attempt that got no readable answer is said to be unknown, because the key may have been stored. Deleting is a dialog with a plain button (decision 54). Six units, each one revertible, in one PR (decision 59): first what only reads, then what writes. No question is left open: the two of § O were answered by decisions 57 and 58. The revised prototype is reviewed before the tasks are written.

**The SDD threat matrix does not apply:** no routing, shell, subprocess, VCS or process boundary is touched. § H is this unit's own matrix, for the typed secret. **No migration.** **`DRY_RUN`, idempotency and the capital pools are not touched:** the unit adds no write path on the server, and the panel writes only through the two routes built in PR 8a and 8b.

### A. Findings (verified at HEAD `d926e71`)

The first eight are the readiness check's, each verified in the code. One of them was wrong in a way that matters (R6).

| # | Finding | Where | Verdict and consequence |
| --- | --- | --- | --- |
| R1 | `ApiError.fields` is filled only when `detail` is an object. The delete's 409 carries `outcome`, a string `detail` and five lists at the TOP level. The save's `CONFIRMATION_REQUIRED` carries `missing` the same way. | `frontend/src/shared/api/client.ts:35-47`; `accounts/infrastructure/credentials_router.py:216-221, 280-290, 293-302, 373-385` | **Confirmed.** The panel cannot read them today. § C. |
| R2 | `GET /api/credentials` lists an exchange only when it has a credential row (active or not) or an enabled pool. | `accounts/infrastructure/credential_listing.py:48-54, 66-69` | **Confirmed.** An exchange with none of the three is absent. § B. |
| R3 | An `EMPTY` entry is `exchange` and `status`, and everything else null. | `credentials_router.py:243-257` | **Confirmed.** "No key, pool on" cannot be told from "no key, pool off" without the pools. § B. |
| R4 | `PUT` and `DELETE` for an exchange with no known pool answer 404, FastAPI's `{"detail": "..."}`. The listing still shows such an exchange when it has a row. | `credentials_router.py:331-334, 364-368`; `accounts/domain/known_pools.py:44-49` | **Confirmed.** § D, state "not served". |
| R5 | A save ends in one of seven refusals (422, 422, 422, 422, 422, 502, 409), or 404, or 503 "credential storage is not configured", or a pydantic 422 whose `detail` is a list of `{type, loc, msg}`. | `accounts/application/save_credential.py:70-78`; `credentials_router.py:106-114, 124-131, 166-185`; `shared/infrastructure/validation_errors.py:52-60` | **Confirmed, and three more exist:** a 401, a 5xx that is none of these, and no answer at all. The September design names KEYS for three refusals and an English text for none. § F has all of them. |
| R6 | `stubApi` rejects an unknown URL and has no `/credentials` route. | `frontend/src/test/harness.tsx:149-205` (the rejection is line 201) | **Half right, and the wrong half is the dangerous one.** The stub does reject. But `apiFetch` catches every rejection of `fetch` and throws `ApiError(0)` (`client.ts:72-77`), so the query would only fail, the tabs would show no mark (the rule for a failed read), and **every shell test would stay green with the credentials read failing inside it**. Nothing would break; that is the problem. A default answer is still needed, and a test must prove it is used. § K. Read from the code, not run. |
| R7 | A save enables the exchange's pool in the same transaction, and a delete disables it. | `save_credential.py:148`; `accounts/application/delete_credential.py:144-145` | **Confirmed.** `['pools']` is read again with `['credentials']`. § F, § G. |
| R8 | Nothing pins anything about the typed key and secret. | `frontend/src/features/settings/` holds one file, the stub `SettingsPage.tsx` | **Confirmed.** § H pins each point. |

Found while verifying:

| # | Finding | Where | Consequence |
| --- | --- | --- | --- |
| N1 | **`GET /api/pools` lists every ROW of `capital_pools`, enabled or not. It does not list every KNOWN pool.** A row exists only if a migration seeded it or a save created it. Migration 0003 seeds four pools, and 0017 gives `usdt-m` to Bybit and the rest to Pionex. No migration inserts a Binance row: a search of `migrations/versions` for `binance` finds only CHECK constraints. The Binance row is created by the first save of a Binance key. | `accounts/infrastructure/pool_overview.py:12-16, 50-68`; `accounts/infrastructure/capital_pool_writer.py:36-59`; `migrations/versions/0003_strategies_pools.py:32-37, 97-103`; `0017_pool_exchange_column.py:43-46` | On a database where Binance never had a key, Binance is in neither route. The pools cannot be the list of exchanges. § B. |
| N2 | `known_pools.py:11-12` says production holds `binance/usdt-m/USDT (0018)`. Migration 0018 inserts no row. | `accounts/domain/known_pools.py:11-12`; `0018_pool_identity_includes_exchange.py:54-97` | The comment may be true of production and is not true of a fresh database. Whether production has the row was **not verified**. The design does not depend on it. |
| N3 | The tabs are built from every pool, enabled or not. | `frontend/src/shared/scope/exchange-store.ts:36-38, 77` | The tab of an exchange whose key was deleted stays with no code change, as decision 22 wants. The Pionex-era pools make a Pionex tab wherever their rows exist. |
| N4 | A test pins that `/settings` never asks for the pools. | `frontend/src/shared/layout/ExchangeTabs.test.tsx:49-57` | Settings now reads the pools. That test keeps "no tabs on `/settings`" and loses "never asks". § K. |
| N5 | Any 401 clears the token, and the token gate then replaces the whole page with its form. | `client.ts:79-81`; `shared/auth/TokenGate.tsx:21-23`; `shared/layout/AppShell.tsx:43-45` | A 401 in the middle of a save unmounts the form. The fields go with it. § H pins it. |
| N6 | The test that lists who may use amber already expects two more files from PR 13. | `frontend/src/features/overview/panel-tokens.test.ts:53-66` | The list grows by exactly the files of § D and § E. |
| N7 | `client.test.ts` pins that a flat body leaves `fields` undefined, and that a list `detail` leaves `detail`, `code` and `fields` undefined. | `frontend/src/shared/api/client.test.ts:122-148` | `fields` cannot be widened to mean the top level without changing pinned behaviour. § C adds a field and changes none. |
| N8 | Migration 0027 wrote every key that existed then as `trade_capable = true` with both sources `UNRECORDED`, and its text says production held one active key each for Binance, Bybit and Pionex. | `migrations/versions/0027_credential_snapshot.py:29-32` | A production key not entered again since then shows as "not validated". That state is likely the FIRST thing the owner sees, so it gets a sentence of its own (§ D). What production holds today was **not verified**. |
| N9 | The worker calls an exchange DEGRADED when it has ANY enabled pool and no active key. | `strategy_manager/worker.py:364-366` | The panel uses the same rule, per exchange, not per known pool. § B. |
| N10 | As built, a tab is one line: the exchange's name as the API spells it (`bybit`), no sub-label, no underline. The "pool summary" sub-label of § Visual design was never built. | `frontend/src/shared/layout/ExchangeTabs.tsx:49-63` | § E adds a mark only where there is something to say. The neutral pool summary is not added by this unit. |
| N11 | **The September help text for the Binance confirmations says more than is true.** It reads "If a confirmation is wrong, Binance rejects the first live order". That holds for Enable Futures only. Nothing catches a wrong withdrawals confirmation, as § H of that same addendum says. | this file, addendum "key policy after probe P6", § G and § H | The text is rewritten (§ J). |
| N12 | The three idioms Settings reuses live under `features/strategies/`. | `StatusButton.tsx`, `InlineStatus.tsx`, `InfoDisclosure.tsx` | A second feature now needs them. § L moves them, as a unit of its own. |
| N13 | **A controlled React input writes its value into the element's `value` ATTRIBUTE.** React keeps `defaultValue` in step with `value`, and `defaultValue` is the attribute. | React DOM's input handling. **From memory of React's source, not run here.** | A controlled secret field would put the typed secret in the document's markup. § F makes both fields uncontrolled, and § H pins it with a test that settles the question either way. |

### B. Where the page's data comes from

**No backend change.** Three sources:

| Source | Query key | What it gives |
| --- | --- | --- |
| `GET /api/credentials` | `['credentials']` | Per listed exchange: `STORED` with last-4 and facts, or `EMPTY`. |
| `GET /api/pools` | `['pools']` (exists, re-read every 60 s) | Which exchanges have a pool, and whether any of them is enabled. |
| `frontend/src/shared/credentials/served-exchanges.json` | none: a file of the panel | Which exchanges the panel manages a key for, in display order, and which confirmations each asks for. |

```json
{
  "bybit": { "confirmations": [] },
  "binance": { "confirmations": ["withdrawals_disabled_confirmed", "futures_enabled_confirmed"] }
}
```

**Why the panel keeps that list.** Neither route lists Binance before its first key (N1), so "Add key" would have nowhere to appear. And the form must know that Binance asks for two confirmations and Bybit for none; the API says that only by refusing. The list mirrors two server tables, `KNOWN_FUTURES_POOLS` and `KEY_POLICIES`. **A backend test keeps them equal**, `backend/tests/accounts/domain/test_served_exchanges_fixture.py`: the file's exchanges are exactly the keys of both tables, and an exchange has confirmations exactly when its policy is `OWNER_CONFIRMED`, named `WITHDRAWALS_CONFIRMATION` and `FUTURES_CONFIRMATION` (`accounts/domain/key_policy.py:26-27, 51-54`). The same device already guards the webhook message (`backend/tests/signals/domain/test_webhook_message_fixture.py`). It is a test, not a change of the API.

**Rejected: making `GET /api/credentials` list every known exchange and say `managed`, `pool_enabled` and `confirmations`.** It is the tidier contract. It is also a change to a specified route, a backend PR that must deploy first, and a new spec delta, to say three things the panel can already know. If a third exchange is ever added, that is the moment to reconsider it.

**The list of exchanges on the page** is the union of three sets, without repeats: the served exchanges, in the file's order; then every other exchange in `['credentials']`; then every other exchange that has a pool. The last two are sorted by name. So every tab has a card (§ E), and a stored key is always shown (decision 54).

**Inputs of one exchange's state:**

- `served`: the exchange is in the file.
- `entry`: its entry in `['credentials']`, or none. `EMPTY` and "not listed" mean the same: no active key.
- `poolOn`: at least one of its pools has `enabled: true` (N9). Unknown while the pools are loading or failed.

| `entry` | `trade_capable` | `poolOn` | State | Card shows (§ D) | Mark (card and tab) |
| --- | --- | --- | --- | --- | --- |
| `STORED` | `true` | any | **key** | The key hint and the tags, by its facts. Neutral. | none |
| `STORED` | `false` | any | **read-only** | The key hint, the tags, the amber sentence, amber border. | `read-only`, amber |
| none or `EMPTY` | - | `true` | **degraded** (decision 20) | The amber sentence, amber border. | `no key`, amber |
| none or `EMPTY` | - | `false` | **empty**: never had a key, or it was deleted (decision 22) | The neutral sentence. | `no key`, neutral |
| none or `EMPTY` | - | unknown | **empty**, with the page's notice that the pools could not be loaded | The neutral sentence. | `no key`, neutral |

`served` is a second axis, not a state: it decides only whether the card has buttons. An exchange that is not served has none and adds one sentence (decision 54), whatever its state.

**The page's own states.** While `['credentials']` has no data: "Loading exchange keys…" and no card. When it failed with no data: the error and "Try again", and **no card**, because a card drawn from the file alone would say "No key stored" about a key the panel could not read. When it has data and a later read failed: the cards stay, under a line that says the list may be out of date, with "Try again" (the data-first rule of `PoolShareEditor`). When the pools failed: the cards are drawn, no exchange is marked amber for lack of a key, and one line says why.

**One pure module decides all of it:** `frontend/src/shared/credentials/key-state.ts` exports `exchangeList(served, entries, pools)`, `keyState(entry, poolOn)` and `keyMark(state)`. The card and the tab both call it. It holds no React and no text.

**A row of `['credentials']` is checked before it is believed**, as `pools.ts` checks a pool. `exchange` is a non-empty string; `status` is `STORED` or `EMPTY`; a `STORED` row has a `last4` of **exactly four characters**, a boolean `trade_capable`, two source strings, and timestamps and `internal_transfer` that are a string or null and a boolean or null. A body that is not a list of such rows is an error, never "no keys". The four-character rule is a security rule: a server fault that put a whole key in `last4` would otherwise be drawn on the page (§ H, row 14).

### C. `ApiError`: one new field

```ts
export class ApiError extends Error {
  // status, outcome, detail, code, fields: exactly as today
  /** The RESPONSE's JSON body when it is an object, as the server sent it. Never anything of the request. */
  readonly responseBody: Readonly<Record<string, unknown>> | undefined;
}
```

- The constructor sets it with the existing `isRecord` check on the body it is already given. `apiFetch` does not change.
- **What it must not break:** nothing existing is touched. `fields` stays "the structured `detail`, whole"; `code`, `outcome`, `detail` and `message` are computed as today. So the eleven readers keep their meaning (`ArchiveDialog`, `DeleteStrategyDialog`, `AllowedPairsEditor`, `NewStrategyDialog`, `PoolShareEditor`, `outcomeMessage.ts`, `pairs.ts` and the three API test files that read them), and every assertion of `client.test.ts:122-148` still holds (N7).
- **It never keeps a request body.** The constructor receives the status and the parsed response, and nothing else; `apiFetch` never hands it `init`. A test pins it: a `PUT` whose body holds a sentinel is answered 422, 500 and with a network failure, and no own property of the thrown error, nor its `message`, holds the sentinel.
- **Rejected: letting `fields` fall back to the top-level body.** It would change `fields` from undefined to an object for every flat refusal, against N7, and make one name mean two shapes.
- **Rejected: changing the credentials routes to a structured `detail`.** The API as built is the contract, it is specified, and it works.

A response can still echo what it was sent, if the server ever did. That is why the form never renders and never keeps the error (§ F, § H row 5).

### D. The card

Laid out again by decision 55. One `<article>` per exchange: `bg-panel`, `border border-rule`, `rounded-lg`, `p-5`. A grid, `grid-cols-1` below `sm` and `sm:grid-cols-[minmax(0,1fr)_auto]` from it, `items-start`, with four areas in this order in the document:

| Area | Holds | Placement |
| --- | --- | --- |
| **head** | the name, and under it the key line | column 1, row 1 |
| **facts** | the notice of a save (§ F), the tags, the opened information text, the sentences | the card's full width, `sm:col-span-2` |
| **actions** | the buttons | `sm:col-start-2 sm:row-start-1` |
| **form** | the key form, when open (§ F) | the card's full width, `sm:col-span-2` |

So from `sm` the name, the key hint and the buttons share the card's first band, and the facts run under it on the whole width. On a phone the card is one column in the document's order: name, key, tags, sentences, buttons, form.

**The name** is the exchange's proper name, from `exchanges.<id>` (`Bybit`, `Binance`, `Pionex`); an id with no entry is shown as the API spells it. Display type, 17 px, weight 600. The tabs keep the API's spelling they have today (N10).

**The key line** is the head's second line: a row (`flex flex-wrap items-baseline gap-x-3 gap-y-0.5`) of two paragraphs, each `whitespace-nowrap`, so when both do not fit the date goes under the hint whole.

- **The key hint**, `font-mono text-xl font-semibold`: the label `key` (`text-[13px] font-normal text-ink-3`), four dots (`font-normal text-ink-3`) and the last four characters (`text-ink tracking-wider`). At 20 px it is the largest text of the card, above the name's 17 px and under the page's 24 px title, and the four characters are the only part of it in `ink`: the eye lands on what has to be compared with the exchange's own page (decision 55). The label, the dots and the characters are hidden from assistive technology, and a hidden text says "key ending in {last4}".
- **The date**, `font-mono text-xs text-ink-3`: `checked {date}`, a UTC day through the existing `dayText`, when `validated_at` is set; `not validated` when it is null. It stands beside the key because it is the day the KEY was tried with a real read. It is not among the tags, where it would read as the date of every tag, the owner's confirmations included.

With no key stored, the key line holds the `no key` mark as a tag, and nothing else.

**The hint is a paragraph, not a heading.** It is a value, not the title of a part of the page: nothing is filed under it. The card stays named by its `h3` alone, so a button is still "Replace key Bybit" and a list of the page's headings is still one line per exchange. The order of headings does not change: `h1`, `h2`, the card's `h3`, and the `h4` of an open form. The hint looks like a second title; it is one only to the eye.

**The hint never grows.** It is the four characters of `last4`, drawn larger. Nothing in this revision holds more of a key: no attribute, no hidden text, no test fixture. § B's four-character rule and § H row 14 stand.

**The tags.** Every fact of a stored key is a tag. They are one `<ul>` (`flex flex-wrap items-center gap-1.5`, named "What is known about this key" for a screen reader), and each tag is an `<li>` with `whitespace-nowrap rounded border px-2 py-0.5 font-mono text-xs`. **There is no separator character anywhere on the card.** That is what makes the layout hold at every width, by construction and not by measuring: a tag cannot break inside (`whitespace-nowrap`), a line cannot begin with a separator (there is none), and when the width runs out a whole tag moves to the next line (`flex-wrap`), with the list's gap between the lines.

| Look | Classes | Says | Tags |
| --- | --- | --- | --- |
| **checked** | `border-rule bg-panel-2 text-ink-2` (filled) | the exchange itself showed this to the application | `trades`, `reads`, `no withdrawal`, `transfers`, `no transfers` |
| **confirmed** | `border-dashed border-rule-strong text-ink-2` (hollow, dashed) | the owner's word, with the day he gave it | `trade confirmed {date}`, `withdraw confirmed {date}` |
| **not on record** | `border-dashed border-rule-strong text-ink-3` (hollow, dashed, dimmer) | nothing was recorded about this fact | `trade not verified`, `withdraw not verified` |
| **mark** | amber: `border-decision text-decision`; grey: `border-rule-strong text-ink-3` (hollow, solid) | the state's mark, the word the tab carries (§ E) | `read-only`, `no key` |

The tags of a stored key, in the order they are drawn:

| # | Fact | When | EN tag | Look |
| --- | --- | --- | --- | --- |
| 1 | the mark | the state is **read-only** (§ B) | `read-only` | mark, amber |
| 2 | capability | trade source `VERIFIED` and `trade_capable` true | `trades` | checked |
| | | trade source `VERIFIED` and `trade_capable` false | no tag: the mark says it | - |
| | | trade source not `VERIFIED`, and `validated_at` set | `reads` | checked |
| | | `validated_at` null | no tag | - |
| 3 | withdrawal | withdraw source `VERIFIED` | `no withdrawal` | checked |
| | | any other source | no tag here; row 6. **Never "no withdrawal"** (decisions 24 and 30). | - |
| 4 | transfers | `internal_transfer` true | `transfers` | checked |
| | | `internal_transfer` false | `no transfers` | checked |
| | | null | no tag | - |
| 5 | trade, not checked by the venue | trade source `OWNER_CONFIRMED` and `trade_confirmed_at` set | `trade confirmed {date}` | confirmed |
| | | any other source that is not `VERIFIED`: `UNRECORDED`, a value the panel does not know, or `OWNER_CONFIRMED` with no date | `trade not verified` | not on record |
| 6 | withdraw, not checked by the venue | withdraw source `OWNER_CONFIRMED` and `withdraw_confirmed_at` set | `withdraw confirmed {date}` | confirmed |
| | | any other source that is not `VERIFIED` | `withdraw not verified` | not on record |
| 7 | the information button | a tag carries a confirmation date | the last `<li>` of the list, a button and not a tag | - |

**One phrase per fact** (decision 55). Trade is said by exactly one of `trades`, `read-only`, `trade confirmed {date}` and `trade not verified`; withdrawal by exactly one of `no withdrawal`, `withdraw confirmed {date}` and `withdraw not verified`. "confirmed" and "not verified" are two rows of the same fact, so they can never be drawn together. A confirmation with no date is drawn as not verified: "confirmed on a day" cannot be said without the day. A source value the panel does not know is drawn as not verified. An unknown value is never drawn as checked.

**The widths, measured once.** At 360 px the card's content is 286 px wide (the page's `p-4`, the card's `p-5` and its border). The longest tag is the Spanish `retiros: confirmado el 30 sept 2026`, 35 characters: 252 px of IBM Plex Mono at 12 px, 270 px with its padding and border. It fits, alone on its line. Below a 344 px viewport it would not; no narrower width is designed for.

**What a Binance card says, and why.** Its key line is `key ••••mK4x` and `checked Oct 2, 2026`. Its tags are `reads`, `trade confirmed Oct 2, 2026` and `withdraw confirmed Oct 2, 2026`, and after them the information button. It does not say `trades`. The system DOES trade with that key: `trade_capable` is true, on the owner's word. But decisions 24 and 30 forbid showing a confirmed fact as one the application checked, and `trades` is exactly how a checked Bybit key reads. The one thing Binance itself showed is that the key reads: the signed account read passed. So `reads` is its only filled tag, and the two facts that rest on the owner's word are dashed and say "confirmed", each with the day he gave it.

**"confirmed" is the owner's word and "checked" is the application's.** The card holds the two apart in three ways, and with no sentence: the word itself; the look of the tag, dashed and hollow against filled; and the place of the date, since a confirmation carries its own day and what was checked shares the one date beside the key. `withdraw confirmed` means that the owner confirmed withdrawals are disabled; the card never says `no withdrawal` for it. The explanation is where the owner asks for it, behind the information button (the `InfoDisclosure` built in unit 12f), named "About what you confirmed": "'Confirmed' is what you told this panel on that day. Binance does not let the panel check what a key may do, so orders are sent on your confirmation. If the key cannot trade futures, Binance rejects the first live order and you get a Telegram alert. Nothing checks the withdrawal setting."

**Every state, with its exact EN text.** `{x}` is the exchange's name.

| State | Key line | Tags, in order | Sentences | Amber | Buttons |
| --- | --- | --- | --- | --- | --- |
| **Key, checked by the venue, trades** (Bybit) | `key ••••7Q2d`, `checked Oct 2, 2026` | `trades`, `no withdrawal`, `transfers` (or `no transfers`) | none | nothing | Replace key, Delete key |
| **Read-only** | `key ••••Rf90`, `checked Oct 2, 2026` | `read-only`, `no withdrawal`, `no transfers` | "This key cannot trade. With dry run off, opening signals for {x} are refused until you add a key that can trade futures." | the `read-only` tag, the border, the sentence | Replace key, Delete key |
| **Confirmed by the owner** (Binance) | `key ••••mK4x`, `checked Oct 2, 2026` | `reads`, `trade confirmed Oct 2, 2026`, `withdraw confirmed Oct 2, 2026`, the information button | none; the information text while it is open | nothing | Replace key, Delete key |
| **No recorded facts** (`UNRECORDED`) | `key ••••7Q2d`, `not validated` | `trade not verified`, `withdraw not verified` | on a served exchange, in `ink-3`: "Stored before the system recorded how a key was checked. Enter it again to have it checked." | nothing | Replace key, Delete key |
| **Degraded** (no key, a pool on) | the `no key` tag | none | "No key stored. With dry run off, opening signals for {x} are refused until a key is added." | the `no key` tag, the border, the sentence | Add key |
| **Empty** (no key, no pool on: never had one, or deleted) | the `no key` tag, grey | none | "No key stored. Add one to read and trade on {x} from here." | nothing | Add key |
| **Not served, with a key** (Pionex) | as its state | as its state | those of its state; then, in `ink-3`: "The {x} key is managed outside this panel, on the server. It cannot be added, replaced or deleted here." | only what its state makes amber | none |
| **Not served, no key** (decision 58: it is shown) | the `no key` tag, which is its only second line: there is no hint to show | none | "No key stored."; then the same sentence in `ink-3` | amber only if a pool of it is on | none |
| **Just saved** (§ F, decision 57) | as its state, or the saved key's hint alone while the list has not been read again | as its state, or none but the `read-only` tag while the list has not been read again | first of all, the notice "Key ending in {last4} saved." | only what its state makes amber | Replace key; Delete key once the list is read |

**The no-recorded-facts card stays apart from the confirmed one.** It has no confirmation date, so it cannot say "confirmed": it says `not validated` beside the key, `trade not verified` and `withdraw not verified` as tags, and the sentence that tells what to do, which is to enter the key again. It has no information button. Its two tags are dimmer than a confirmation's (`ink-3` against `ink-2`): both looks are dashed, and the dimmer one is what tells "nothing on record" from "your word". It is still neutral, not amber: the system trades with such a key, and nothing is refused because of it.

**Amber, in one line:** the `read-only` tag, the `no key` tag of a degraded exchange, and with each of them the card's border and its sentence. Everything else is neutral: the `no key` tag of an empty exchange (`ink-3`), "not validated", the "confirmed" and the "not verified" tags, and the not-served sentence. Amber means the owner has something to do; a fact that is confirmed, or merely unverified, is state (the spec's words).

**Buttons.** "Add key" is the filled teal button (`bg-gain text-ground`): it is the one thing to do on that card. "Replace key" is outlined (`border-rule`). "Delete key" is outlined in `loss`, as "Delete strategy" is. All are at least 44 px tall. "Add key" and "Replace key" are one element that opens and closes the form: it carries `aria-expanded` and `aria-controls`, and it is the SAME element under both texts, kept mounted when the text changes, so it can hold the focus across a first save (§ F). It reads "Replace key" when a key is stored or was just saved on this card. While that card's form is open, its "Delete key" is disabled. While any save is in flight, every button of the page is disabled (§ F).

**Files that use an amber utility:** `shared/credentials/KeyMark.tsx` (the mark, as a tab's word and as a card's tag) and `features/settings/ExchangeKeyCard.tsx` (the border and the sentence). Both are "a read-only key" or "a keyless exchange", two of the four places amber is allowed. `AMBER_ALLOWED` gains exactly these two. The form has no amber: since decision 57 the warning of a read-only save is the card's own (§ F).

**The structure a test pins**, because jsdom has no layout (§ K): the facts are a `<ul>` with `flex flex-wrap`; every tag is an `<li>` with `whitespace-nowrap`; the card's text holds no ` · `; for each of trade and withdrawal exactly one tag is in the list; the key hint is a `<p>`, not a heading, with `whitespace-nowrap`; and the card has exactly one heading, its `h3`, while no form is open.

### E. The tab marks

`ExchangeTabs` reads `['credentials']` and, for each tab, asks `keyMark(keyState(entry, poolOn))`: the same function the card uses, with the same inputs.

| The exchange has | Tab |
| --- | --- |
| a key that trades | the name alone |
| a key that cannot trade | the name, and under it `read-only` in amber |
| no key, and a pool that is on | the name, and under it `no key` in amber |
| no key, and no pool on: **a deleted key**, or an exchange never keyed | the name, and under it `no key` in `ink-3` |
| anything, while `['credentials']` is loading or failed | the name alone. No mark is a claim of nothing, and never "the key is fine". |

**The name is at the same place in every tab** (decision 55). The first drawing stacked the name and the mark and centred the pair, so a tab with a mark held its name higher than a tab without one. Now every tab, marked or not, holds the same grid, and the mark has a cell of its own:

```tsx
<button type="button" aria-pressed={selected} className="min-w-fit flex-1 whitespace-nowrap rounded-md px-3.5 text-sm lg:flex-none ...">
  <span className="grid min-h-13 grid-rows-[minmax(0,1fr)_auto_minmax(0,1fr)] justify-items-center">
    <span className="row-start-2 leading-5">{exchange}</span>{" "}
    {mark !== null && <KeyMark mark={mark} className="row-start-3 self-start" />}
  </span>
</button>
```

- **Three rows, and the name is always the middle one.** Rows 1 and 3 are the same track, `minmax(0,1fr)`. Their minimum is zero, so what row 3 holds cannot make it taller than row 1: the two always halve the free height, and row 2 is on the tab's centre line whether row 3 is empty or not. Row 1 is always empty; it is the mirror of the row that holds the mark.
- **The mark never shares a track with the name**, so it takes no part in placing it. Sideways the two are centred each on its own in the one column: a mark wider than its name widens its tab and leaves the name on the tab's centre.
- **The grid is a `<span>` inside the button**, as `StatusButton` holds its texts, so nothing depends on how a browser lays out a `<button>` that is itself a grid.
- **Every tab is 52 px tall** (`min-h-13`), not 44: each outer row is then 16 px, room for the mark's 14 px line (`KeyMark` on a tab: `font-mono text-[11px] leading-3.5 whitespace-nowrap`). The height is on every tab, never only on a marked one. The bar from `lg` is 64 px and does not change. **The tabs' own row on a phone grows from 44 to 52 px**, with marks or without.
- **On a phone the tabs share the row's whole width, each one the same** (decision 59). The first revision left them at their own width against the row's left edge, with the rest of the row empty. A tab is `flex-1 min-w-fit` below `lg` and `lg:flex-none` from it, where the bar holds them at their own width as before. `flex-1` gives every tab the same share, so the names are spread evenly and each is centred in its share; `min-w-fit` keeps a tab from being squeezed under its own name or mark, so with more exchanges than the width holds the row still scrolls sideways and never wraps (`ExchangeTabs` keeps `overflow-x-auto`). It replaces `shrink-0`, which the first of the two makes redundant. The two surfaces need no second component: the row below `lg` and the bar from `lg` are never drawn together.
- **The accessible name** is "binance no key": the mark is inside the button, and the space between the two spans is a real text node. A grid does not draw a text node that is only white space, so it changes nothing to the eye.
- **The tab of a deleted key** stays, because its pool row stays (N3), and reads `no key` in grey, the same as its card. Decision 22 asks for the mark; decision 20 keeps amber for the degraded case; a deleted key has its pool off, so it is not degraded.
- The mark is a word, never colour alone. On a tab it is plain text; on a card the same word is a tag (§ D).
- Both surfaces of the tabs (the bar from `lg`, the row below it on a phone) get it, because both are the same component.
- `ExchangeTabs` itself gains no amber class: the mark carries it.

**The structure a test pins** (§ K): every tab's inner `<span>` carries the same three grid classes, with a mark and without one; the name is the element with `row-start-2` in every tab, with one class list everywhere; a mark, when present, has `row-start-3`; a tab without a mark has exactly one element in its grid; the button's accessible name is the name, a space and the mark; and every tab carries `flex-1`, `min-w-fit` and `lg:flex-none`, and none carries `shrink-0`.

### F. The form

**Where.** Inside its card, under the facts and the buttons, spanning the card: a section with a 1 px dashed `rule-strong` border, as in September's mockup. Not a dialog. **One at a time:** the page holds which exchange's form is open, or none. Pressing "Add key" or "Replace key" on another card closes the open one, which unmounts it and empties it. Pressing the button that opened it closes it too.

**Parts, in order.**

1. Title: "Add a {x} key", or "Replace the {x} key" when a key is stored.
2. Two fields side by side from `sm`, stacked below it: "API key" (text, mono) and "API secret" (password). Each at least 44 px, `bg-ground`, `border-rule`.
3. Help, `ink-3` 13 px. For an exchange with no confirmations: "Before saving, the key is tried with a real read at {x}. A key that can withdraw funds is refused. A key that cannot trade is saved with a warning." For one with confirmations: "Before saving, the key is tried with a real read at {x}. {x} does not let this panel check what the key may do, so you confirm it here."
4. Only when a key is stored: "Saving replaces the key stored now, also when the new key cannot trade." This is the panel's one defence against replacing the trading key with a read-only one (CLAUDE.md, "Never seal a read-only key"): the panel cannot know what a key may do before the venue is asked, and by then the old key is superseded.
5. Only for an exchange with confirmations (Binance): a group titled "What you checked in {x}" with one checkbox per name in the file, both unticked: "I confirmed in {x} that this key has withdrawals disabled" and "I confirmed in {x} that this key has Enable Futures". Under them: "If the key lacks Enable Futures, {x} rejects the first live order and you get a Telegram alert. Nothing checks the withdrawal setting: it rests on your word." (N11)
6. The refusal, when there is one.
7. The buttons: "Check and save" (filled teal) and "Close".

**The fields are uncontrolled.** No `value` and no `defaultValue` prop. The typed text lives in the two elements and nowhere else: not in state, not in a ref's copy, not in a store. Component state holds only: whether each field has text, which boxes are ticked, the phase, and the result of the last attempt as `{ reason, missing, status }`. Why: N13, and because what is not in React state cannot be read from it.

| Attribute | API key | API secret | Why |
| --- | --- | --- | --- |
| `type` | `text` | `password` | The owner can check the key he pasted; the secret is masked and kept out of a phone keyboard's learning. |
| `autoComplete` | `off` | `new-password` | Browsers ignore `off` on a password field and may fill a saved password into it. `new-password` is the value that asks them not to fill one. `off` is honoured for a plain text field's history. |
| `name` | none | none | A field with no name is not part of a native form submission, so even a submit that escaped the handler would put nothing in a URL or a body. |
| `spellCheck` | `false` | - | A text field's content can be sent to a spell-check service. |
| `autoCapitalize`, `autoCorrect` | `off` | - | A phone must not alter or learn the key. |

No attribute stops a browser or a password manager from OFFERING to save what was typed. That is said in § K and § N, and checked by eye.

**The button.** It is a `StatusButton` with two texts, "Check and save" and "Checking…", so its width never changes. It never reads "Saved": decision 52 is about a button that stays on screen after the save, and by decision 57 this form does not.

| Moment | Button reads | Button is | Elsewhere |
| --- | --- | --- | --- |
| A field is empty, or a box is unticked | Check and save | disabled | - |
| Both fields have text and every box is ticked | Check and save | enabled | - |
| The request is in flight | Checking… | disabled | "Close" is disabled, and so is every button of every card. The fields are read-only. |
| It was saved | - | - | **The form closes by itself** (decision 57). The card says the result: "After a save that worked", below. |
| It was refused, or no answer could be read | Check and save | disabled (the fields are empty) | **The form stays open.** Both fields are empty and both boxes unticked. The text of the table below, in `loss`, with `role="alert"`, followed by "The fields were emptied. Enter the key again to retry." in `ink-3`. The focus moves to "API key". |

The refusal stays until the next attempt starts or the form closes; typing does not remove it, so the owner can read it while he types.

**The attempt, step by step.** (1) If an attempt is in flight, return: a ref holds that, not only the disabled attribute. (2) Read both fields and trim them. (3) Call `saveCredential`. (4) In `finally`: empty BOTH elements, untick the boxes, clear the two "has text" flags. (5) Unless the answer was a 401: start the re-read of `['credentials']` and `['pools']`, also when the form was unmounted meanwhile. The owner may have gone to another page during the check, and the exchange tabs of that page read the keys before the save ended; without this re-read a tab would go on saying `no key` about an exchange whose key was just stored (changed in the review of unit 13.5, task 13.5.15b; this step used to skip the re-read for an unmounted form). (6) Unless the form was unmounted meanwhile: for a save that worked, hand `{ last4, readOnly }` to the page, which closes the form; for anything else, record the result and move the focus to "API key". The body sent is `{api_key, api_secret}` for Bybit and the same plus the two confirmations as `true` for Binance; no `label`, and for Bybit no confirmation field at all.

**After a save that worked (decision 57).** The form closes at once, on the answer, without waiting for the lists. The page keeps one thing about it, `lastSave`: the exchange, the answer's `last4`, whether the answer said the key cannot trade, and `listStamp`, the `dataUpdatedAt` of `['credentials']` at that moment. `last4` is kept only when it is a string of exactly four characters (§ B's rule); otherwise it is absent. `saveCredential` applies that rule itself, so no `SaveResult` ever holds more of a key than four characters. `readOnly` comes from the answer itself (`warnings` holds `READ_ONLY_KEY`, or `facts.trade_capable` is false), not from the list read after it, because that read can fail. A 200 whose body cannot be read is still a save, with no `last4` and `readOnly` false.

- **What the card shows once the list has been read again** (`dataUpdatedAt` is past `listStamp`): the card of its state (§ D), and as the first line of its facts the notice "Key ending in {last4} saved.", or "Key saved." with no `last4`. It is a plain paragraph in `ink-2`.
- **What the card shows until then, and when that read fails:** it is drawn from the save's answer, never from the list's old entry. The key line is the SAVED key's hint, with no date; there is no tag but `read-only` when the answer said so; the notice reads "Key ending in {last4} saved. The rest of this card appears when the list has been read again." The key stored before is not drawn at all, so the card can never show the old key as if nothing had happened. When the read failed, § B's line stands above the cards as well, "This list could not be refreshed and may be out of date." with "Try again", and the card stays in this view until a read succeeds.
- **The read-only warning is the card's own state, and nothing is added to it.** A key that cannot trade makes the card read-only: the amber `read-only` tag, the amber border and the sentence "This key cannot trade. With dry run off, opening signals for {x} are refused until you add a key that can trade futures." While the list is behind, those three are drawn from the answer's `readOnly`; afterwards from the list, as for any read-only key. The tab shows `read-only` once the list is read. The form's own warning text is gone with the form that held it.
- **Focus.** It goes to the card's toggle, the element that opened the form. For a key that was replaced it reads "Replace key", as before. For a first key it read "Add key" and now reads "Replace key": it is the same element (§ D), and it shows "Replace key" from `lastSave` alone, before the list is read. The page moves the focus explicitly, after the form has left the document; jsdom and a browser would both leave it on the body otherwise. "Delete key" appears when the list is read, and never takes the focus.
- **What a screen reader is told.** The page has one status region, `role="status"`, hidden from sight and always in the document. On a save it is given "Key ending in {last4} saved.", and for a key that cannot trade the card's read-only sentence after it, so the warning is heard at the moment of the save and not only found later on the card. It is the region that says "{x} key deleted." (§ G). The visible notice is not a live region, so nothing is read twice.
- **How long the notice stays.** Until the next thing the owner does on the page: opening a form, opening the delete dialog, another save, or leaving. No timer.

**An attempt whose answer could not be read is not a save that worked.** For `noAnswer` and `unknown` (the table below) the form STAYS OPEN, emptied, with its text in `loss`: the owner needs the message, and the key may or may not have been stored. Both lists are read again behind it, so the card above the form shows what is stored now.

**`saveCredential` never throws and never returns the error.**

```ts
// frontend/src/shared/api/credentials.ts
export type SaveResult =
  | { kind: "saved"; last4: string | null; readOnly: boolean }
  | { kind: "refused"; reason: SaveRefusal; missing: readonly string[]; status: number }
  | { kind: "unauthorized" };
export function saveCredential(
  exchange: string, apiKey: string, apiSecret: string, confirmations: readonly string[],
): Promise<SaveResult>;
```

It is a plain function over `apiFetch`, called from a plain handler. **It is not a `useMutation`**: a mutation keeps its `variables`, which would be the secret, in the mutation cache. It catches everything, maps it, and lets the error object go. The mapping, first match wins: a 2xx whose body is JSON is saved (a 2xx whose body cannot be read is `unknown` with status 200, never a save: the route always answers JSON, so the panel does not know what happened; found on reading unit 13.2's diff, 2026-10-10); a 401 is `unauthorized` (the page is being replaced by the token gate, and the form does nothing); a known `outcome`; a 404; a 503; a 422 whose `detail` is a list; status 0; anything else.

**Every answer and its text.** The panel chooses the text by the outcome or the status. **It never renders the server's `detail`.** After each of them the form does what the last row of the table above says; the last column names only what differs.

| Answer | Key (`settings.form.error.`) | EN text | Also |
| --- | --- | --- | --- |
| 422 `KEY_REJECTED` | `keyRejected` | "{x} did not accept this key. Check that the key and the secret were copied whole, that the key has not expired, and that it allows this server's IP address. Nothing was saved." | - |
| 422 `WITHDRAW_PERMISSION` | `withdrawPermission` | "This key can take funds out of the account, so it was refused. Create a key without withdrawal permission and enter that one. Nothing was saved." | - |
| 422 `PERMISSIONS_UNAVAILABLE` | `permissionsUnavailable` | "{x} did not say what this key is allowed to do, so it was not saved. Try again in a moment." | - |
| 502 `VENUE_UNREACHABLE` | `venueUnreachable` | "{x} could not be reached, so the key was not checked and not saved. Nothing is known to be wrong with it. Try again." | - |
| 409 `CONCURRENT_SAVE` | `concurrentSave` | "Another save for {x} finished first, so this one was not stored. The card shows the key that is stored now. Check it before saving again." | - |
| 422 `CONFIRMATION_REQUIRED` | `confirmationRequired` | "The key was not saved, and nothing was sent to {x}, because a confirmation is missing:" then one line per name in `missing`, each the checkbox's own label | If `missing` is not a list of known names: `confirmationRequiredUnlisted`, "The key was not saved, and nothing was sent to {x}, because a confirmation is missing. Tick both and enter the key again." |
| 422 `CONFIRMATION_NOT_APPLICABLE` | `confirmationNotApplicable` | "The panel sent a confirmation that {x} does not take, so the key was not saved. Reload the page and enter the key again." | Only a stale page sends it. |
| 404 | `notServed` | "{x} keys are not managed by this panel, so nothing was saved." | Only a stale page reaches it: a card that is not served has no form. |
| 503 | `storageUnavailable` | "The server cannot store keys right now, so nothing was saved. If this repeats, the server's encryption key is missing or unusable and has to be fixed there." | The text does not claim the cause: a 503 from in front of the API reads the same. |
| 422, `detail` a list, an entry whose `loc` ends in `api_key` | `invalidKey` | "The API key cannot be stored as typed. A key has 4 to 256 characters and no spaces or accented letters. Nothing was sent to {x}." | - |
| 422, `detail` a list, an entry whose `loc` ends in `api_secret` (and none for the key) | `invalidSecret` | "The API secret cannot be stored as typed. A secret has at most 256 characters and no spaces or accented letters. Nothing was sent to {x}." | - |
| 422, `detail` a list, neither | `invalidRequest` | "The server refused the request as malformed, so nothing was saved. Reload the page and enter the key again." | - |
| no answer (status 0) | `noAnswer` | "No answer came back from the server, so it is not known whether the key was saved. The card shows what is stored now." | **The key may have been stored.** The form stays open; the re-read is what tells. |
| any other status, a 500 included | `unknown` | "The save ended in a way this panel cannot read (status {status}), so it is not known whether the key was saved. The card shows what is stored now." | The same. |
| 401 | none | none | The token gate takes the page. |

**The panel checks nothing about the key before sending it**, beyond "both fields have text". The server's rule (4 to 256 printable ASCII characters) is not copied into the panel: a second copy can drift, and the server's refusal has a text.

### G. The delete

**The control.** "Delete key", on a served card that has a stored key. It is always enabled when shown: the panel does not guess whether the server will allow it, the server says (decision 22). One click only opens the dialog.

**The dialog** is `ArchiveDialog`'s shape: a native `<dialog>` opened with `showModal`, Escape and the browser's `cancel` routed to one handler, nothing closing while the request is in flight. Its buttons are 44 px tall, which the two existing dialogs are not; the rule of § Visual design is 44 px.

- Title: "Delete the {x} key?"
- Body, `ink-2`: "The key ending in {last4} is removed from this system. {x} is no longer read or traded from here until a key is added again. Its history stays." Then: "The server allows this only while every {x} strategy is disabled and nothing is open on it."
- Buttons, in this order in the document: "Cancel" (outlined), then "Delete key" (filled `loss`). **A plain button, nothing to type** (decision 54). It reads "Deleting…" while the request is in flight, and both buttons are then disabled.

**The request** is a `useMutation` over `DELETE /api/credentials/{exchange}`, as archiving is: it carries no secret, so nothing sensitive can sit in the mutation cache. On every settled attempt it re-reads `['credentials']` and `['pools']` and waits for them before it reports, as the strategy hooks do, so when the dialog closes the card behind it is already the new one.

**What the dialog shows for each answer.**

| Answer | What the owner sees |
| --- | --- |
| 200 | The dialog closes. The card is the empty card (§ D). The page's hidden status region (§ F) says "{x} key deleted." The focus goes to that card's "Add key". |
| 409 `EXCHANGE_NOT_FLAT` | In `loss`, `role="alert"`: "The {x} key cannot be deleted yet. This is in the way:" and the list below. Both buttons stay, so the owner can fix it elsewhere and press "Delete key" again. |
| 409 whose five lists cannot all be read | "The {x} key cannot be deleted yet: a strategy is still enabled, a position is open or an order is in progress." No list. Never half a list, the rule of `ArchiveDialog`. |
| 404 | "The server found no {x} key to delete. Close this: the card shows what is stored now." It is not treated as a success: the same status also means "not served". |
| no answer, or any other status | "The delete ended in a way this panel cannot read. Close this: the card shows whether the key is still stored." **The key may have been deleted.** |
| 401 | The token gate takes the page. |

**The five lists, each rendered so the owner knows what to do.** Read from `error.responseBody` (§ C). Only a kind that has entries gets a line. Every line says what it is and what ends it.

| Field of the body | EN text (`settings.delete.reasons.`) |
| --- | --- |
| `enabled_strategies` (`{id, name}`) | one: "{count} enabled strategy: {names}. Disable it first." · other: "{count} enabled strategies: {names}. Disable them first." |
| `symbols` | "Open position on: {symbols}. It has to be closed first." |
| `allocations` | one: "{count} open allocation. It ends when its position is closed." · other: "{count} open allocations. They end when their positions are closed." |
| `live_reservations` | one: "{count} live reservation: capital held for an order. Wait for it to finish, then try again." · other: "{count} live reservations: capital held for orders. Wait for them to finish, then try again." |
| `in_flight_attempts` | one: "{count} order being placed right now. Wait for it to finish, then try again." · other: "{count} orders being placed right now. Wait for them to finish, then try again." |

The names of the strategies are text, not links: a link would leave a modal dialog. The symbols are shown as the server sends them. The ids of allocations, reservations and attempts are counted, never listed: they tell the owner nothing.

**After a delete**, the page shows the empty card with "Add key", and that exchange's tab reads `no key` in grey (§ E). Its strategies stay, disabled, and its history stays viewable (decision 22). Adding a key again turns its pool back on (decision 21).

### H. The secret, as a threat matrix

`K` and `S` are two sentinel strings a test types into "API key" and "API secret". Unless a row says otherwise, its test lives in `frontend/src/features/settings/KeyEntryForm.secret.test.tsx` and runs once per ending: a save, each refusal, a network failure and a 401. The eight points the readiness check found unpinned are rows 1, 2, 4, 5, 6, 9, 10, 11 and 12.

| # | Where the typed key or secret could end up | Why it must not | The rule that prevents it | The test that pins it |
| --- | --- | --- | --- | --- |
| 1 | A react-query **query** cache | The cache outlives the form, is shared by the whole panel and is readable from the dev tools. | The save is not a query. Nothing typed is ever part of a query key or of a query's data. | `::test_no_query_cache_entry_holds_the_key_or_the_secret`: after each ending, a walk of every query's key, data and error finds neither `K` nor `S`. |
| 2 | The react-query **mutation** cache | A mutation keeps its `variables` after it settles. | The save is a plain function, not `useMutation` (§ F). | `::test_no_mutation_cache_entry_exists_for_a_save`, and a source test that `KeyEntryForm.tsx` and `credentials.ts` never pass the save to `useMutation`. |
| 3 | React state, and so the React dev tools | State is readable, and survives until the unmount. | The fields are uncontrolled (§ F). State holds two booleans about them, never their text. | A source test: `KeyEntryForm.tsx` has no `value=` and no `defaultValue=` on either field. Row 4's test catches a regression from the other side. |
| 4 | A **DOM attribute** | The markup can be read by an extension, copied from the inspector and saved with the page. | The same: an uncontrolled field's text is the element's value, never its attribute (N13). | `::test_no_attribute_of_the_document_holds_the_key_or_the_secret`: after typing, and again after each ending, `document.body.innerHTML` holds neither and both fields' `value` attribute is absent. **Its RED is the controlled field**: a form written with `value={...}` must fail this on its assertion. If it passes instead, N13 is wrong for this React and the row still stands by row 3. |
| 5 | A **rendered error text**, on a refusal and on a network failure | The text is on screen, and is read aloud. | The text is chosen by outcome or status. The server's `detail` is never rendered, and the error object is never kept (§ F). | `::test_no_text_on_screen_holds_what_was_typed_even_when_the_server_echoes_it`: every refusal is answered with a `detail` that CONTAINS `K` and `S`, the pydantic one with an `input` field that does, and the document's text holds neither. The network failure is the same test with a rejected `fetch` whose message holds them. |
| 6 | The **console** | It is kept for the session and shown to whoever opens the dev tools. An unhandled rejection is printed there by the browser. | Nothing in the settings feature or the credentials client writes to the console, and `saveCredential` catches everything (§ F). | `::test_nothing_is_written_to_the_console`, with the spies `WebhookMessage.test.tsx` already uses, per ending; a source test for `console.` in `features/settings/` and `shared/api/credentials.ts`; and `saveCredential` resolving, never rejecting, for a `fetch` that throws a plain `Error`. |
| 7 | The `ApiError` object | It is passed around, and § C gives it the response's body. | It is built from the response only (§ C). `saveCredential` drops it before it returns. | `client.test.ts::test_an_error_never_holds_the_request_body`; `credentials.test.ts::test_a_save_result_is_a_plain_object_of_known_fields`. |
| 8 | The **URL**, the history, a query string | They are logged by proxies and kept by the browser. | The key and the secret travel in the PUT's body only. The fields have no `name`, so a native submission would carry nothing. The handler prevents it anyway. | `::test_the_request_is_one_put_to_the_exchange_path_with_the_key_only_in_its_body`; `::test_neither_field_has_a_name`. |
| 9 | The fields, after **Cancel** (here "Close", and the button that opened the form) | The next person at the screen finds them. | Closing unmounts the form. | `::test_closing_the_form_and_opening_it_again_shows_two_empty_fields`. |
| 10 | The fields, after **leaving the page**, after **switching exchange**, and after a **401 in the middle of a save** | The same. | Each unmounts the form: the route changes, the page's "open form" moves to another exchange, or the token gate replaces the page (N5). After the 401 nothing is recorded, re-read or focused. | `::test_leaving_settings_and_coming_back_shows_no_open_form`; `::test_opening_another_exchange_closes_and_empties_this_one`; `::test_a_401_during_a_save_leaves_the_token_gate_and_nothing_typed`, which unlocks again and finds no form and neither sentinel in the document. |
| 11 | The network, **twice** | A second request is a second signed read at the venue and a second chance to lose the race for the one active key. | A ref marks the attempt in flight; the button is disabled; `saveCredential` never retries. | `::test_a_second_click_and_an_enter_while_checking_send_nothing`: one PUT. `::test_a_failed_save_is_not_retried`: one PUT. |
| 12 | **One** of the fields, left filled after an attempt | Half a credential left on screen, and decision 54 says the form is emptied. | `finally` empties both elements, whatever happened. | `::test_both_fields_are_empty_after_every_ending`: the `value` of each is `""`, asserted on both, per ending. After a save that worked the form is gone (decision 57), so there the test asserts that neither field is in the document, opens the form again and finds both empty. Its RED is a `finally` that empties only the secret. |
| 13 | The browser's own stores: saved passwords, form history, a password manager, a spell-check service, a phone keyboard | They are outside the panel and outlive the session. | The attributes of § F. | `::test_the_fields_carry_the_attributes_that_ask_the_browser_to_keep_nothing`, attribute by attribute. **What a browser does with them cannot be tested here** (§ K). |
| 14 | The page, through the SERVER: a fault that answered a whole key as `last4` | It would be drawn on every card and tab. | A `last4` that is not exactly four characters makes the whole list unreadable (§ B). | `credentials.test.ts::test_a_last4_that_is_not_four_characters_is_refused_and_never_rendered`. |
| 15 | `localStorage`, `sessionStorage`, a persisted store | They survive the tab. | Nothing typed is ever given to a store. | `::test_no_storage_holds_what_was_typed`. |
| 16 | A status region or an `aria-label` | It is read aloud. | The status, the card's notice and the hint drawn before the list is read all say the last four characters taken from the SERVER's answer, never cut from what was typed, and only when the answer's `last4` is exactly four characters (§ F). | `::test_the_saved_status_reads_the_last4_of_the_answer_not_of_the_field`: the answer's `last4` differs from `K`'s ending, and the answer's is what is said and drawn. `::test_an_answer_whose_last4_is_not_four_characters_is_said_as_key_saved`: the answer's `last4` is the whole of `K`, and the document holds no `K`. |
| 17 | The request already sent, when the form is closed or the page left | - | Nothing can call a sent request back. "Close" is disabled while it is in flight, so only leaving the page abandons it, and then the save still happens and the card shows it on the next visit. | `::test_close_is_disabled_while_checking`. The rest is a known limit. |
| 18 | Transit, and the server's logs | - | Outside this unit. The panel and the admin API are reached over HTTPS through the tunnel of decision 5, which ends TLS before the API (unit 12f's finding U11; **not verified here**). The server's side is pinned already: the redacted 422 and the log test of § K4 and § K5. | none here |

JavaScript cannot wipe a string from memory. The rules above end every REFERENCE the panel holds; the memory itself is the engine's.

### I. Accessibility and keyboard

- **Structure.** `h1` "Settings" (unchanged, three existing tests find it). `h2` "Exchange keys" with the intro. The cards are a list; each is an `<article>` named by its `h3`, the exchange's name. The key hint is a paragraph (§ D), so it adds no level: the order stays `h1`, `h2`, `h3`, and `h4` for an open form's title.
- **Reading order in a card** is the document's order: name, key hint, date (or the `no key` tag), the notice of a save, the tags, the information button, the sentences, "Add key" or "Replace key", "Delete key", then the form. On a phone that is also the visual order. From `sm` the buttons are DRAWN beside the head and stay after the facts in the document, so the information button, the one control among the facts, is reached before them although it is drawn lower. It is kept that way on purpose: the other order would put the buttons between the key and its tags on a phone, and the buttons belong beside the form they open.
- **The key** is read as "key ending in 7Q2d": the label, the dots and the characters are hidden from assistive technology and a hidden text says it in words.
- **The tags are a list**, named "What is known about this key", and each tag is text. What tells a confirmed fact from a checked one for the eye is the tag's look; for a screen reader it is the tag's own words, "confirmed" with its date against the bare fact. Nothing is said by the look alone.
- **A mark is a word.** No state is carried by colour alone. On a tab the mark is part of the button's name: "binance no key" (§ E).
- **Buttons are named with their exchange:** each is labelled by its own text and the card's heading ("Replace key Bybit"), so a list of buttons is not three times "Replace key". The visible text stays the start of the name.
- **The form.** A section named by its title. Each field has a `<label>`; both are described by the help text. The confirmations are a `<fieldset>` with a `<legend>`; each box is a real checkbox with its label, 44 px tall. Enter in a field submits, through a `<form noValidate>` whose handler prevents the native submission.
- **Focus.** Opening the form puts the focus in "API key". Closing it, by "Close" or by the button that opened it, returns the focus to that button. After a refusal the focus goes to "API key", where the owner types next. After a save that worked the form closes and the focus goes to the card's toggle, the element that opened it, which then reads "Replace key" (§ F). There is no Escape on the form: it is not a dialog, and Escape is the key a browser uses to dismiss its own suggestions over a field.
- **What a screen reader is told.** A refusal is a `role="alert"`, so it is read when it appears. A save that worked is said through the page's hidden status region, as "Key ending in 7Q2d saved.", followed by the card's read-only sentence when the key cannot trade (§ F). The card's visible notice is not a live region. While the request is in flight the button's own text, "Checking…", is its name.
- **The dialog.** `aria-labelledby` its title. "Cancel" is first in the document, so it has the focus when the dialog opens: the safe button. Escape cancels, except while deleting. Closing returns the focus to "Delete key"; after a delete that worked, "Delete key" is gone, so the focus goes to the card's "Add key". jsdom restores no focus by itself, so the control does it explicitly.
- **Targets** are at least 44 px. **Focus rings** are the panel's own.
- **Dates** are UTC days in the panel's language, through `dayText`.

### J. Localization

Every text is a key in `en.json` and `es.json`. `{{exchange}}` is the proper name. The ES texts are written at build time, in the wording `es.json` already uses: "exchange" and "pool" stay as they are, and the reader is addressed as "usted" ("Desactive", "Pegue", "Use").

| Key | EN |
| --- | --- |
| `exchanges.bybit` · `exchanges.binance` · `exchanges.pionex` | Bybit · Binance · Pionex |
| `scope.mark.readOnly` | read-only |
| `scope.mark.noKey` | no key |
| `settings.keys.title` | Exchange keys |
| `settings.keys.intro` | One key per exchange. Keys are encrypted on the server and never shown again; you only see the last four characters. |
| `settings.keys.loading` | Loading exchange keys… |
| `settings.keys.error` | Exchange keys could not be loaded. |
| `settings.keys.retry` | Try again |
| `settings.keys.stale` | This list could not be refreshed and may be out of date. |
| `settings.keys.poolsUnknown` | The pools could not be loaded, so an exchange without a key is not marked here. |
| `settings.card.keyLabel` | key |
| `settings.card.keyEnding` | key ending in {{last4}} |
| `settings.card.checkedOn` | checked {{date}} |
| `settings.card.notValidated` | not validated |
| `settings.card.facts` | What is known about this key |
| `settings.card.tag.trades` | trades |
| `settings.card.tag.reads` | reads |
| `settings.card.tag.noWithdrawal` | no withdrawal |
| `settings.card.tag.transfers` | transfers |
| `settings.card.tag.noTransfers` | no transfers |
| `settings.card.tag.tradeConfirmed` | trade confirmed {{date}} |
| `settings.card.tag.withdrawConfirmed` | withdraw confirmed {{date}} |
| `settings.card.tag.tradeNotVerified` | trade not verified |
| `settings.card.tag.withdrawNotVerified` | withdraw not verified |
| `settings.card.confirmedInfo` | About what you confirmed |
| `settings.card.confirmedHint` | "Confirmed" is what you told this panel on that day. {{exchange}} does not let the panel check what a key may do, so orders are sent on your confirmation. If the key cannot trade futures, {{exchange}} rejects the first live order and you get a Telegram alert. Nothing checks the withdrawal setting. |
| `settings.card.saved` | Key ending in {{last4}} saved. |
| `settings.card.savedNoHint` | Key saved. |
| `settings.card.savedPending` | The rest of this card appears when the list has been read again. |
| `settings.card.unrecordedHint` | Stored before the system recorded how a key was checked. Enter it again to have it checked. |
| `settings.card.readOnly` | This key cannot trade. With dry run off, opening signals for {{exchange}} are refused until you add a key that can trade futures. |
| `settings.card.degraded` | No key stored. With dry run off, opening signals for {{exchange}} are refused until a key is added. |
| `settings.card.empty` | No key stored. Add one to read and trade on {{exchange}} from here. |
| `settings.card.emptyNotServed` | No key stored. |
| `settings.card.notServed` | The {{exchange}} key is managed outside this panel, on the server. It cannot be added, replaced or deleted here. |
| `settings.card.add` · `.replace` · `.delete` | Add key · Replace key · Delete key |
| `settings.form.addTitle` | Add a {{exchange}} key |
| `settings.form.replaceTitle` | Replace the {{exchange}} key |
| `settings.form.apiKey` · `.apiSecret` | API key · API secret |
| `settings.form.helpVerified` | Before saving, the key is tried with a real read at {{exchange}}. A key that can withdraw funds is refused. A key that cannot trade is saved with a warning. |
| `settings.form.helpConfirmed` | Before saving, the key is tried with a real read at {{exchange}}. {{exchange}} does not let this panel check what the key may do, so you confirm it here. |
| `settings.form.replaceNote` | Saving replaces the key stored now, also when the new key cannot trade. |
| `settings.form.confirm.legend` | What you checked in {{exchange}} |
| `settings.form.confirm.withdrawals_disabled_confirmed` | I confirmed in {{exchange}} that this key has withdrawals disabled |
| `settings.form.confirm.futures_enabled_confirmed` | I confirmed in {{exchange}} that this key has Enable Futures |
| `settings.form.confirm.help` | If the key lacks Enable Futures, {{exchange}} rejects the first live order and you get a Telegram alert. Nothing checks the withdrawal setting: it rests on your word. |
| `settings.form.submit` · `.submitting` · `.close` | Check and save · Checking… · Close |
| `settings.form.emptied` | The fields were emptied. Enter the key again to retry. |
| `settings.form.error.*` | the fifteen texts of § F's table, under the keys it names |
| `settings.delete.confirmTitle` | Delete the {{exchange}} key? |
| `settings.delete.confirmBody` | The key ending in {{last4}} is removed from this system. {{exchange}} is no longer read or traded from here until a key is added again. Its history stays. |
| `settings.delete.condition` | The server allows this only while every {{exchange}} strategy is disabled and nothing is open on it. |
| `settings.delete.confirm` · `.cancel` · `.pending` | Delete key · Cancel · Deleting… |
| `settings.delete.deletedStatus` | {{exchange}} key deleted. |
| `settings.delete.errors.notFlat` | The {{exchange}} key cannot be deleted yet. This is in the way: |
| `settings.delete.errors.notFlatUnlisted` | The {{exchange}} key cannot be deleted yet: a strategy is still enabled, a position is open or an order is in progress. |
| `settings.delete.errors.gone` | The server found no {{exchange}} key to delete. Close this: the card shows what is stored now. |
| `settings.delete.errors.unknown` | The delete ended in a way this panel cannot read. Close this: the card shows whether the key is still stored. |
| `settings.delete.reasons.*` | the nine texts of § G's table: `enabledStrategies`, `allocations`, `liveReservations` and `inFlightAttempts` each `_one` and `_other`, and `symbols` |

`settings.title` exists and does not change. The three keys September named under `settings.key.*` and `settings.card.confirmedOn` are replaced by the names above; none was ever built. Decision 55 removed `keyMasked`, `readsAndTrades`, `readsOnly`, `readingVerified`, `internalTransfer`, `noInternalTransfer`, `confirmedOn`, `notVerifiedInfo` and `notVerifiedHint`; decision 57 removed `settings.form.saved`, `.savedStatus`, `.savedStatusNoHint` and `.readOnlySaved`. None of them was built either.

**The marks, the tags and the texts that changed, in both languages.** These are short, sit in a narrow place and were chosen at their Spanish length, so their Spanish is fixed here and not at build time.

| Key | EN | ES |
| --- | --- | --- |
| `scope.mark.readOnly` | read-only | solo lectura |
| `scope.mark.noKey` | no key | sin clave |
| `settings.card.keyLabel` | key | clave |
| `settings.card.keyEnding` | key ending in {{last4}} | clave terminada en {{last4}} |
| `settings.card.checkedOn` | checked {{date}} | comprobada el {{date}} |
| `settings.card.notValidated` | not validated | sin validar |
| `settings.card.facts` | What is known about this key | Lo que se sabe de esta clave |
| `settings.card.tag.trades` | trades | opera |
| `settings.card.tag.reads` | reads | lee |
| `settings.card.tag.noWithdrawal` | no withdrawal | sin retiros |
| `settings.card.tag.transfers` | transfers | transfiere |
| `settings.card.tag.noTransfers` | no transfers | sin transferencias |
| `settings.card.tag.tradeConfirmed` | trade confirmed {{date}} | operar: confirmado el {{date}} |
| `settings.card.tag.withdrawConfirmed` | withdraw confirmed {{date}} | retiros: confirmado el {{date}} |
| `settings.card.tag.tradeNotVerified` | trade not verified | operar: sin verificar |
| `settings.card.tag.withdrawNotVerified` | withdraw not verified | retiros: sin verificar |
| `settings.card.confirmedInfo` | About what you confirmed | Sobre lo que usted confirmó |
| `settings.card.confirmedHint` | (the text above) | «Confirmado» es lo que usted indicó a este panel ese día. {{exchange}} no permite que el panel compruebe qué puede hacer una clave, así que las órdenes se envían con su confirmación. Si la clave no puede operar futuros, {{exchange}} rechaza la primera orden real y usted recibe una alerta de Telegram. Nada comprueba el ajuste de retiros. |
| `settings.card.saved` | Key ending in {{last4}} saved. | Clave terminada en {{last4}} guardada. |
| `settings.card.savedNoHint` | Key saved. | Clave guardada. |
| `settings.card.savedPending` | The rest of this card appears when the list has been read again. | El resto de esta tarjeta aparece cuando la lista se haya leído de nuevo. |

- **The abbreviations** (decision 55 asks for the shortest text). `trades` for "reads and trades": a key that trades was read first. `reads` for "reading verified". `transfers` and `no transfers` for "internal transfers allowed" and "no internal transfers": on a key's card, beside `no withdrawal`, a transfer is one inside the account. `read-only` for "reads only": it is the mark's own word, said once.
- **Spanish uses a colon where English sets two words side by side.** "operar confirmado" is not Spanish, and "operación confirmada" would read as one of the panel's "operaciones", a trade. So the fact is named and then its state: `operar: confirmado el 2 oct 2026`, `retiros: sin verificar`. The pair stays parallel across the two states.
- **Lengths.** The longest mark is `solo lectura`, 12 characters, about 79 px under a tab's name; three marked tabs are about 290 px and fit the 328 px of a 360 px phone's row, and a longer list scrolls sideways, as today. The longest tag is in § D.
- **A date in a tag has no "on" in English and keeps "el" in Spanish.** It is `dayText`'s medium date in both.

**EN texts that will be awkward in Spanish, to settle when the rest are written:**

- **"Enable Futures".** It is the name of a setting on Binance's own page, and Binance's Spanish page names it differently. The text should name what the owner will actually see there, which depends on the language he uses Binance in.
- **"With dry run off".** The locale's word for dry run is "Modo simulación", so the phrase is longer in Spanish and comes twice in one text.
- **"it rests on your word".** An idiom; say it plainly in Spanish.
- **The lines of § G that end "Disable it first" / "Disable them first", "It ends…" / "They end…".** They agree in number and, in Spanish, in gender with the noun before them. The `_one` and `_other` keys carry that; the two sentences of each line stay in ONE key.

### K. Test strategy

**The harness.** `stubApi` gains a seventh argument, `credentials`, and a default: when the pools stub is a list, one `STORED`, `VERIFIED`, trade-capable entry per distinct exchange in it; otherwise an empty list. So in every existing shell test each exchange has a key that trades, no tab gains a mark, and no existing assertion on a tab's text or name moves. The default answers `GET` only: a `PUT` or a `DELETE` to `/credentials/...` stays an unexpected request unless the test's own route answers it, so **no test can save or delete a key by accident**. Two builders are added beside `pool()`: `storedKey(exchange, overrides)` and `emptyKey(exchange)`.

**Proving the default is used (R6).** `stubApi`'s mock records every URL it rejected, as `fetchMock.unexpected`. The new tests assert it is empty. One test in `ExchangeTabs.test.tsx` asserts that a shell render asked for `/credentials` and was answered. Without this the whole suite would pass with the read failing.

**Existing test files this touches.**

| File | What changes |
| --- | --- |
| `frontend/src/test/harness.tsx` | The argument, the default, the two builders, `unexpected`. |
| `frontend/src/shared/api/client.test.ts` | New cases for `responseBody`; none changed. |
| `frontend/src/shared/layout/ExchangeTabs.test.tsx` | The test at lines 49-57 keeps "no tabs on `/settings`" and loses "never asks for pools" (N4). New: one case per row of § E, in both surfaces. |
| `frontend/src/features/overview/panel-tokens.test.ts` | `AMBER_ALLOWED` gains two files (§ D). |
| `frontend/src/app/router.test.tsx`, `frontend/src/app/App.test.tsx`, `frontend/src/shared/layout/AppShell.test.tsx` | Expected to need nothing: they find the `h1` "Settings", which stays, and the default answers the new reads. To be confirmed by running them, not assumed. |
| the tests of `StatusButton`, `InlineStatus`, `InfoDisclosure`, and every file that imports the three | Moved or re-pointed by unit 13.0 (§ L). No assertion changes. |

**New test files.** `shared/api/credentials.test.ts` (the row check, the mapping of § F answer by answer, the five lists); `shared/credentials/key-state.test.ts` (a table: every row of § B, and the list's order); `features/settings/SettingsPage.test.tsx` (the page's states, the list, one form at a time, and the end of a save that worked: the form gone, the notice, the status region, the focus on the toggle, and the card while the list is behind and when its read fails); `ExchangeKeyCard.test.tsx` (every row of § D, tag by tag, with each tag's look, which are amber, and the structure § D pins); `KeyEntryForm.test.tsx` (the button's states, the confirmations, every answer's text, the focus, the re-reads, and that the form stays open for every answer that is not a save); `KeyEntryForm.secret.test.tsx` (§ H); `DeleteKeyDialog.test.tsx` and `DeleteKeyControl.test.tsx` (§ G); and the backend's `test_served_exchanges_fixture.py` (§ B).

**Rules that bind the task breakdown.**

- **Strict TDD: each RED fails on an assertion.** The stubs that compile and answer wrongly: a `keyState` that always answers "key"; a `KeyMark` that always renders nothing; a card that prints `trades` and `no withdrawal` for every stored key (so the Binance test fails on its text, and "never no withdrawal" fails on its assertion); a card that prints `trade not verified` beside `trade confirmed {date}` (so "one phrase per fact" fails on its count); a tab that puts its mark in the name's row; a page that keeps the form open after a 200, and one that closes it and leaves the focus on the body; a card that draws the list's old entry while the list is behind; a form whose fields are controlled and whose `finally` empties only the secret (§ H rows 4 and 12); a `saveCredential` that returns the server's `detail` as its text (row 5); a dialog that sends the delete on the click that opened it.
- **The tests that pass at once are proven by breaking what they guard**: "no mutation cache entry" (wrap the save in `useMutation` and watch it go red), "nothing in the console" (add one `console.error(error)`), "no storage" (write the key to `sessionStorage`), "a second click sends nothing" (remove the ref and the disabled attribute).
- **The names worth keeping from the old tasks**, re-homed: `test_no_exchange_tabs_lists_every_exchange`, `test_owner_confirmed_key_shows_trade_confirmed_and_withdraw_confirmed_with_their_dates_and_never_not_verified_nor_no_withdrawal`, `test_confirmed_and_not_verified_tags_are_neutral_not_amber`, `test_unrecorded_key_shows_not_validated_and_both_not_verified_tags_and_never_confirmed` (the three renamed by decision 55), `test_card_never_renders_a_raw_permissions_payload`, `test_bybit_form_shows_no_confirmation_checkboxes_and_sends_none`, `test_binance_submit_sends_both_confirmations_true`, `test_delete_requires_explicit_confirmation_not_single_click`, `test_confirmed_successful_delete_shows_same_empty_state_as_never_configured`.
- **No lock-hold harness applies.** The unit adds no lock and no second actor; the server's race is tested where it lives (PR 8b-2).
- **No symbol crosses a module boundary here.** The symbols of a refused delete are printed as sent.
- **Both languages.** Every new key exists in both files, and one test renders the page, an open form and an open dialog in Spanish and finds no English text of § J.

**What jsdom cannot show**, and the review by eye must:

- What a browser does with the fields: whether it offers to save the key and the secret as a login, whether it fills a saved password into the secret, whether it offers a generated password because of `new-password`. Chrome and Firefox, and the owner's password manager if he uses one. **If a browser offers to save, the answer is "never for this site"**; no attribute removes the offer.
- The layout: the tags wrapping as whole tags at each width and in both languages, the date going under the hint whole, the buttons going under the facts on a phone, the name at the same height in every tab with a mark and without one, the top bar's height unchanged from `lg`, and the tabs' own row 52 px tall on a phone. The tests pin the STRUCTURE that makes these true (§ D, § E); only the eye sees the result.
- That a tag's look reads as intended: filled for what was checked, dashed for what the owner confirmed, dashed and dimmer for what is not on record.
- The focus ring, the native dialog's backdrop and its own focus return, and that 44 px is 44 px.
- What a screen reader says, and in what order, after a refusal that also moves the focus.
- The panel's fonts and its Content-Security-Policy with the built bundle served.

### L. Units and forecast

Each unit is one or more commits that can be reverted without the ones before it breaking.

| Unit | Contents | A revert leaves | Production lines | Test lines |
| --- | --- | --- | --- | --- |
| **13.0** | `StatusButton`, `InlineStatus` and `InfoDisclosure`, with their tests, move from `features/strategies/` to `shared/ui/`; imports follow. No behaviour changes. Done with `git mv` and `Edit`, never a script. | the three where they are | about 40 changed (imports) | 0 |
| **13.1** | `ApiError.responseBody` (§ C) | the error as today; nothing reads the field yet | about 15 | about 90 |
| **13.2** | `shared/api/credentials.ts`; the served list and its backend test; the harness default (§ B, § F's function, § K) | no credentials client; nothing renders from it yet | about 330 | about 800 |
| **13.3** | `key-state.ts`, `KeyMark`, the tab marks, their texts (§ B, § E) | tabs with no marks, as today | about 200 | about 520 |
| **13.4** | The page and the cards, with no button (§ D) | the stub page | about 420, and about 120 of texts | about 900 |
| **13.5** | The form, "Add key" and "Replace key", and the end of a save on the page and its card: the notice, the status region, the focus, the card while the list is behind (§ F, § H) | cards that only show | about 380, and about 90 of texts | about 1,500 |
| **13.6** | "Delete key" and its dialog (§ G) | no delete; the form still works | about 260, and about 60 of texts | about 650 |

**One PR, PR 13, for the six units** (decision 59, 2026-10-10). The design recommended two sequential PRs, one that only reads (units 13.0 to 13.4) and one that writes (units 13.5 and 13.6); the owner chose one. Nothing is lost by it: the panel is not served in production, and nothing here deploys in an order. The units stay as they are, each one revertible and each with its own commits, in the order of the table.

- **Units 13.0 to 13.4 only read.** Nothing in them can change a key. Their review by eye is the cards and the tab marks against the prototype.
- **Units 13.5 and 13.6 are the first controls of the panel that write a key.** Their review by eye is the form in a real browser (§ K), and one real save and one real delete on the owner's local database. Their diff is read apart from the rest, commit by commit, because it is where the typed secret lives.

**Forecast, as information only.** About 1,900 lines of production code and texts and about 4,500 of tests: **4,500 to 7,000 authored lines** in all, about 2,500 to 3,800 for the units that read and 2,000 to 3,200 for the two that write. September's tasks said 900 to 1,300 for the same page. This is four to five times that, which is where the recent units of this panel ended up against their own forecasts, and the upper end is the likelier one: § H alone is some twenty tests that run once per ending. `Decision needed before apply: No` (the owner approved the revised prototype and chose one PR, decision 59; § O holds no open question) · `Chained PRs recommended: Yes, and declined by the owner` · `400-line budget risk: High`.

**Design decisions made here** (not owner decisions; each has its reason above):

| # | Decision | Rejected | Section |
| --- | --- | --- | --- |
| S1 | No API change. The panel keeps the list of served exchanges, and a backend test keeps it equal to the server's two tables | Extending `GET /api/credentials` | B |
| S2 | `ApiError` gains `responseBody`; nothing else of it moves | Widening `fields`; restructuring the routes' bodies | C |
| S3 | The page lists the served exchanges, then every other with a key row, then every other with a pool | The credentials list alone (no place for "Add key"); the pools alone (N1) | B |
| S4 | One pure function gives the state and the mark to both the card and the tab | Each deciding for itself | B, E |
| S5 | A Binance key's one filled tag is `reads`, and never `trades` | `trades` (a confirmed fact shown as checked); no filled tag at all (the date beside the key would then say "checked" about nothing). `reads` alone was rejected in the first drawing because it read like "reads only"; as a tag beside `trade confirmed {date}` it no longer does, and a key that only reads has its own amber tag | D |
| S6 | An unknown source value is drawn as not verified | Drawing it as the nearest known value | D |
| S7 | The form is inside its card, one open at a time, and its fields are uncontrolled | A dialog; controlled fields (N13) | F |
| S8 | The save is a plain function that never throws and never keeps the error | `useMutation` | F |
| S9 | The text of a refusal is chosen by outcome or status; the server's wording is never rendered | Showing `detail` | F, H |
| S10 | After every attempt both lists are read again; an attempt with no readable answer is said to be unknown | Treating a network failure as "not saved" | F, G |
| S11 | The panel checks nothing about a key before sending it | Copying the server's 4-to-256 rule into the panel | F |
| S12 | "Delete key" is always enabled; the dialog says what is in the way | Disabling it from a second read of the strategies | G |
| S13 | A 404 on a delete is said, not treated as done | Closing the dialog as a success | G |
| S14 | The three shared idioms move to `shared/ui/` | A feature importing from another feature | L |
| S15 | The harness answers `GET /credentials` by default with a key that trades for every exchange, never answers a write, and records what it rejected | No default (R6) | K |
| S16 | A tab is a three-row grid with the name in the middle row and the mark in the third; the two outer rows are one `minmax(0,1fr)` track | A stacked pair centred together (the first drawing: the mark moved the name); a mark taken out of the flow with `absolute` (it would not widen its tab and would run over the next one); a row kept free under every name (the name would sit above the centre when no tab has a mark) | E |
| S17 | The facts are tags in a wrapping list, with no separator character | The dotted run of the first drawing (it breaks anywhere and can start a line with a dot); a table of facts (taller, and empty cells for what an exchange does not report) | D |
| S18 | The key hint is a large paragraph, not a heading, and the date stands beside it | An `h4` (a heading with nothing filed under it, and a second name for the card); the hint inside the `h3` (every button would be named with the key); the date as a tag (it would date the owner's confirmations too) | D |
| S19 | Three looks of a tag: filled for checked, dashed for confirmed, dashed and dimmer for not on record | One look and the difference in the words alone; a visible label over each group (text the owner asked to cut) | D |
| S20 | A confirmation with no date is drawn as not verified | "confirmed" with no day | D |
| S21 | After a save the form closes on the answer, and the card is drawn from the answer until the list is read again | Waiting for the lists before closing (a read that never answers would hold the form open on a save that worked); drawing the list's old entry meanwhile (the old key shown as if nothing had happened) | F |
| S22 | One hidden status region on the page says a save and a delete; the card's notice is a plain paragraph | A live region per card (the notice read twice); the button's own text (decision 57 leaves no button) | F, G |
| S23 | The form's second button stays "Close" | "Cancel": after an attempt whose answer could not be read it would read as undoing a save that may have happened | F |

### M. What stays as designed in September, and what does not

**Stays:**

- One key per exchange, and one card per exchange. Settings has no exchange tabs.
- The intro text, word for word.
- What a card says of a key, in mono: the last four, the capability, the withdrawal fact, the date. "no withdrawal", "not validated".
- "trade not verified" and "withdraw not verified" for a fact with nothing on record, and the owner's confirmation with its date, all neutral and not amber. Never "no withdrawal" for a confirmed key.
- The three renderings: neutral, read-only in amber, degraded in amber; and the amber border with its sentence. The read-only and the degraded sentences, which now say "opening signals", as the spec does.
- "Add key", "Replace key", "Delete key". "Delete key" only where a key is active.
- The form inline, with a dashed `rule-strong` border, not a dialog. "API key", "API secret". "Check and save".
- For Binance only, two checkboxes, unticked, the button disabled until both are ticked, both sent as `true`. Bybit shows none and sends none.
- The submit by a plain handler, not `useMutation`. The fields emptied in `finally`, whatever happened. Nothing logged.
- The read-only warning after a 200, taken from the answer and not from the list.
- The 409's reasons rendered in the delete dialog, in `loss`. After a delete, the same card as an exchange never keyed.
- `['credentials']`, also read by the exchange tabs, re-read after a save or a delete.
- Amber only where it is allowed, with a test that lists the files.
- Tailwind tokens only; EN and ES for every text; 44 px targets.

**Changes, each with its reason:**

| September | Now | Why |
| --- | --- | --- |
| The delete is confirmed by "an explicit confirmation" | a plain button in a dialog | decision 54 |
| Pionex is one more card | no Replace, no Delete, one sentence; shown also when it has no key | decisions 54, 31 and 58 |
| The page title is "Exchange keys" | `h1` "Settings", `h2` "Exchange keys" | The `h1` is found by three existing tests and names the route in the navigation |
| `autoComplete="off"` on both fields | `off` on the key, `new-password` on the secret, no `name`, no spell check | Browsers ignore `off` on a password field |
| Local component state for the fields | no state: uncontrolled fields | N13, and § H row 3 |
| "a 422/502/409 shows the outcome's i18n reason" | a text for every answer, the unknown ones included | R5 |
| The Binance key line reads as before, with marks | its one filled tag is `reads` | S5 |
| One mono key line, its parts joined by dots | the last four as a large line beside the name and the buttons, the facts as tags under it | decision 55, S17, S18 |
| "reads and trades", "reads only", "internal transfers allowed", "no internal transfers" | `trades`, `read-only`, `transfers`, `no transfers` | decision 55: the shortest text |
| "trade not verified" and "withdraw not verified", each with "you confirmed on {date}" | `trade confirmed {date}` and `withdraw confirmed {date}`; "not verified" only when nothing is on record | decision 55: one phrase per fact |
| A tab's mark under its name, the pair centred | the name on the tab's centre line in every tab, the mark in a row of its own | decision 55, S16 |
| The read-only warning of a save, in the form | on the card, as its read-only state | decision 57: the form closes after a save |
| "If a confirmation is wrong, Binance rejects the first live order" | true of Enable Futures only, and said so | N11 |
| "Cancel" in the form | "Close" | After an attempt whose answer could not be read, "Cancel" would read as undoing a save that may have happened (S23). One word, and no button whose text changes. |
| A tab stacks the name over a pool summary | the name alone, with a mark only when there is one | N10: the summary was never built and is not part of this unit |
| `settings.key.*` keys | `settings.form.*` | One name for the form everywhere; none was built |
| Binding and expiry on the card (§ 15) | not shown | The addendum "key policy" already dropped them: they are not stored |

### N. Layering, risks, and what was verified and what was assumed

**Layering.** `shared/api/` talks to the server. `shared/credentials/` is the pure decision and the mark, used by a layout component and a feature. `features/settings/` is the page. Nothing in `shared/` imports from `features/`. The server's layers are not touched.

**What fails here without a log line?** The browser has no log, so every silent failure must be on screen.

| Failure | Where it shows |
| --- | --- |
| A save whose answer never arrived stored the key | The form says it does not know, and the card is read again (S10). |
| A read-only key replaced the trading key | Said before, in the form ("Saving replaces…"), and after, in amber, on the card (from the save's own answer, so also when the list is not read again) and on the tab, and said to a screen reader at the save. On the server: one WARNING per refused opening signal, as today. **It cannot be prevented from the panel:** what a key may do is known only once the venue is asked, and the save is the asking. A check-only call would need a new route; it is not designed here. |
| A save worked, the form closed, and the list was not read again or its read failed | The card is drawn from the save's answer and says the rest is not read yet; the old key is not drawn. A failed read adds the line above the cards (§ F). |
| The form closes and nothing takes the focus | The page puts it on the card's toggle, and a test asserts the active element (§ F). |
| The credentials read fails behind a page that still has data | A line above the cards. |
| The pools read fails | A line above the cards, and no exchange is called degraded on a guess. |
| The panel's list of served exchanges drifts from the server's | A backend test fails at the gate. |
| A new source value appears in the API | Drawn as not verified (S6). |
| The harness swallows an unexpected request | `fetchMock.unexpected` (S15). |
| A wrong Binance confirmation | Trade: the venue rejects the first live order, with an ERROR to Telegram. Withdraw: nothing catches it, and the card and the form now say so. |

**Verified in the code at HEAD `d926e71`:** every row of § A marked "Confirmed", and N1, N3 to N7, N9, N10, N12; the API's bodies and statuses, line by line; the existing idioms; the two locales' wording.

**Read but not run:** R6's correction (that the shell tests would stay green); that `router.test.tsx`, `App.test.tsx` and `AppShell.test.tsx` need no change.

**Assumed, and it matters:**

- **N13**, how React writes a controlled field's value. § H row 4's RED settles it on the first day of unit 13.5. The design holds either way.
- **What browsers do** with `new-password`, with a field that has no `name`, and with the offer to save. From the browsers' documentation as remembered, not checked in this session. The review by eye of units 13.5 and 13.6 is where it is seen.
- **What production holds**: whether it has a Binance pool row (N2), whether its keys are still `UNRECORDED` (N8), whether a Pionex key is stored (decision 54 says this is not known). The design covers every case.
- **That the panel is still not served in production** (unit 12f's finding U9). If it now is, the first save from the panel is a production act, and the owner's review of units 13.5 and 13.6 comes before it.
- **The tunnel's TLS** (§ H row 18).
- **That `dataUpdatedAt` moves on every successful read of `['credentials']`**, also when the data read is equal to what was held (§ F's `listStamp`). From memory of TanStack Query, not run. If it does not, the card would stay in its "not read again" view after a read that changed nothing; the test of unit 13.5 that re-reads an identical list settles it on its first day.
- **The Tailwind 4 spellings** `min-h-13`, `leading-3.5` and `grid-rows-[minmax(0,1fr)_auto_minmax(0,1fr)]` (§ E). From memory, not built here. The values they stand for are 52 px, 14 px and three rows; a different spelling changes nothing of the design.
- **The widths of § D and § J** are arithmetic on IBM Plex Mono's advance, not a measurement. The prototype is drawn with the reviewer's system fonts, which are narrower, so a line may wrap one tag later there than in the built panel.

**Other risks.**

- **A short "confirmed" tag can still be read as the application's own check.** Decision 55 asked for "trade confirmed on…" with no "you" in it, and for no explaining sentence on the card. What holds the two apart is the dashed look, the confirmation's own date and the information button. If the owner's review finds that is not enough, the fix is one word, "you confirmed", at the cost of length.
- **"withdraw confirmed" names the fact and not its direction.** What the owner confirmed is that withdrawals are DISABLED; the tag can be read as "withdrawal allowed, confirmed". It is the owner's own wording, and the card may not say "no withdrawal" for a confirmed key (decisions 24 and 30). The Spanish `retiros: confirmado` carries the same doubt.
- **`transfers` and `no transfers` drop the word "internal".** Beside `no withdrawal` it reads as a movement inside the account; alone it could be read as any transfer.
- **The tabs' row on a phone is 8 px taller**, for every exchange and at all times, so that a mark has room under a centred name.
- A password manager that fills the "API key" field with a saved user name. The attributes ask it not to; if it does, the owner sees it before he presses the button, and the venue refuses the key.
- The forecast. It is four to five times September's, and it may still be low.
- The move of unit 13.0 touches files of a feature that was reviewed by eye this week. It is import paths only, and its own commit.

### O. Questions for the owner (both answered)

The two questions no decision settled when this addendum was written. The owner answered both on 2026-10-10; none is open.

**Q1. After a save that worked, does the form stay open or close by itself?**
**Answered by decision 57: it closes by itself.** The design had recommended the other answer. What follows from it is in § F, "After a save that worked": the card says the result, the read-only warning is the card's own state, the focus goes to the card's toggle, and a refusal or an unreadable answer still keeps the form open.

**Q2. Is an exchange the panel does not serve shown when it has NO key?**
**Answered by decision 58: yes, it is shown**, as recommended. This is Pionex wherever no Pionex key is stored and only its old pools remain. Its card has the `no key` tag as its second line, "No key stored.", the sentence that its key is managed outside the panel, and no button (§ D). So every tab has a card, and one rule covers every exchange.

Never asked, because a decision or the spec answers it: the plain delete button and Pionex's missing buttons (54), the emptied form (54), the wording and the neutral tone of the facts (24, 30, 55 and the spec), the amber of a keyless exchange (20), the tab that stays after a delete (22), that replacing is always allowed (22).

### Revision of 2026-10-10: the owner's review (decisions 55, 57 and 58)

**Changed.**

- **Tabs (§ E).** The name is the middle row of a three-row grid in every tab and the mark has the third row, so a mark cannot move the name. Every tab is 52 px tall.
- **The card (§ D).** Four areas: head, facts, actions, form. The key hint is a 20 px paragraph under the name, with its date beside it; the facts are tags in a wrapping list with no separator; the mark of a card is a tag.
- **The texts (§ J).** `trades`, `reads`, `transfers`, `no transfers` replace the longer phrases. A confirmed fact reads `trade confirmed {date}` or `withdraw confirmed {date}`, and "not verified" is left to a fact with nothing on record: one phrase per fact. The Spanish of every mark and tag is fixed.
- **Three looks of a tag** hold "checked" (filled) apart from "confirmed" (dashed) and from "not on record" (dashed, dimmer, `ink-3` where it was `ink-2`).
- **After a save that worked (§ F, decision 57)** the form closes. The card says "Key ending in {last4} saved.", is drawn from the save's answer until the list is read again, and carries the read-only warning as its own state. The focus goes to the card's toggle; one hidden status region tells a screen reader. "Saved" on the form's button, the form's own saved and read-only texts and its amber are removed. A refused or unreadable attempt keeps the form open.
- **An unserved exchange with no key is shown (§ D, decision 58).** § O holds no open question.
- § I, § K, § L (S5, S16 to S23), § M and § N follow.

**Not changed.** The API and § B's sources; `ApiError` (§ C); the form's fields, help, confirmations and refusals (§ F), approved as drawn; the delete (§ G); the secret's threat matrix (§ H), but for rows 12 and 16; the states and which of them are amber; the six units (§ L). The key hint is still four characters.

**After the owner saw the revised prototype (decision 59, the same day).** It is approved, with one change: on a phone the tabs share the row's whole width instead of sitting against its left edge (§ E). The texts of the tags stand as drawn, "withdraw confirmed {date}" among them, which the owner read with the risk of § N in front of them. And the six units go in one PR, not two (§ L).

## Addendum: open positions, a mark and a list read from the ledger (decision 65) - 2026-10-11

> **Revised 2026-10-12 after the owner's review of the prototype.** The prototype is approved as
> drawn at commit `6603dea` (decision 65, the bullets dated 2026-10-12). It is the visual reference
> for the implementation, its Spanish included, and this addendum now describes what it draws.
>
> - **The Overview part is in.** It is a unit of the delivery like the others, no longer separable
>   (§ H, § L, § M; § O, Q1 and Q2).
> - **The Strategies page shows nothing of another exchange.** Everything it draws is selected by
>   the exchange of the selected tab. No screen states the whole system's answer any more; § B says
>   what still holds, what no longer does, and what protects a mode change.
> - **The summary above the list is three labelled figures**, not a sentence: `Open: 2 · Orders in
>   flight: 1 · Last read: 21:40:03 UTC` (§ H, § I). The sentence forms and their keys are gone.
> - **The marks follow one rule**: the shape says what a mark is, the colour says the origin, red
>   says that something needs the owner (§ H).
> - **The top bar's "Live" badge changes from `loss` to `gain`**, in this delivery (§ H, § L, § M).
> - **The venue mark on the detail page is one line**, built from the same component as the line
>   of an order in flight (§ E, § H).
> - **The texts are the prototype's**, each with its key (§ I), and § J describes the prototype as
>   it is.
> - **The backend keeps its route, its body and its reuse of the guard's reader.** One thing is
>   added: a WARNING when an element's pool is not its reservation's, because the pool's exchange
>   now decides which tab shows an element (§ C; § K, row 17).
> - **Found in the code while revising**: the live-only count has a second caller, on the strategy
>   detail page (§ A, P27); the router does not scroll to an anchor by itself (P29); the figures'
>   helpers write a decimal point in every language (P30). Four questions followed from the
>   revision (§ O, Q6 to Q9); the owner answered all four on 2026-10-13, each as its default.
> - **Corrected after validation** (2026-10-12, on top of commit `ae684d3`; an independent
>   validation returned "pass with corrections", and each finding was checked against the code
>   before it was written here). Two existing tests and the test harness would have gone red and
>   are now steps of op.2: the amber allow-list and the harness's answer for the new route (P31; §
>   L, § M). A position the facts cannot decorate has no fees either, and its empty cells are
>   drawn as dashes (§ D, § F, § H). The leverage is written without its stored zeros (P32; § H).
>   The pool check compares every group of fills, not one (P33; § C). The pairs of every element
>   are market keys (§ C). A row's marks are selected inside its exchange, in so many words (§ H).
>   Two cases the panel shows nowhere are named as such (§ H; § K, rows 25 and 26), and Q7 and Q9
>   were reworded for the owner, their defaults unchanged (§ O; answered on 2026-10-13). What was marked "not verified" in
>   P25, P26 and P29 now cites the lines that settle it. The forecast moved by about 250 lines
>   (§ M).
> - **Answered 2026-10-13** (decision 65, the four bullets of that date; § O). Q6: the detail
>   page's count stays live-only. Q7: the panel says nothing of an item on no exchange tab; the
>   count-only line was declined and the WARNING stays. Q8: the Overview's list shows no orders in
>   flight. Q9: in Spanish, prices and sizes of open positions are written with a point (`184.3`),
>   money keeps the language's separator and the currency's decimals (`0,17`, `121.80`): the one
>   place where what is built does not follow the prototype's Spanish example 25. Every default
>   this addendum built to is confirmed; nothing is re-applied.
> - **Corrected during the build:** the port speaks performance's own protocols. The first writing
>   gave `OpenStateSourcePort` the guard's port's signatures and types; that contradicted
>   `test_the_ports_module_imports_no_type_of_another_module`. As built (commit `6889987`),
>   `performance/domain/open_position.py` owns two read-only `typing.Protocol`s (§ C, § G).
> - **Three points of the tasks answered by the orchestrator** (§ H, § F): the names of the two
>   `format.ts` files after their move, the item for an order whose strategy name is null, and
>   where a null `submitted_at` sorts.
> - **Corrected after the final review, 2026-10-13:** the count for one dry-run position, the
>   unmatched sentence, the Read again button, with the owner's agreement (§ H, § I, § K, § N).
>
> Rewritten: §§ H, I, J and O. Amended: the two paragraphs below, § A (P8, P18 and P20, and P24 to
> P35 added), § B (point 4 and the two blocks after it), § C (two statements and two blocks), § D
> (one row), § E (what the mark carries, its two forms, where it leads), § F (why the route keeps
> no parameter, five cells and one paragraph), § G (one bullet), §§ K, L, M and N. P24 to P35 and
> every file and line this revision cites were read in the working tree at HEAD `3cc7a4d` and
> again at `ae684d3`, the code being the same; the findings P1 to P23 keep the HEAD they were
> verified at, and were not re-read.

HEAD `24f52d7`, branch `feat/operator-panel-open-positions`. Decision 65 and its four recorded
answers are binding and are not reopened here: scope B (a mark and a list read from the ledger, no
current price, no unrealised PnL, no new read of the venue); rehearsal and live positions always
shown together, each marked with its origin; the fields of a row, with "margin granted" and the
leverage as recorded and no notional column; the places they show (the strategies list, the detail
page and, agreed on 2026-10-12, the Overview's list and the Overview's count); the selected
exchange as the scope of the Strategies page; a disabled strategy's position shown like any other; and the row's own mark when
the reconciliation has confirmed that the venue disagrees. This addendum settles what they left to
the design. It is design only: it writes no task, no code and no spec file. The unit's identifier
is for the tasks to choose; "unit op" below is a placeholder.

> **Revised 2026-10-11**, on top of commit `a0ad994`. The owner answered three of § O's five
> questions the same day, and a fresh-context validation returned "pass with corrections"; the
> invariant argument of § B held. Both are folded into §§ A to O below. What changed: a position
> or an order the facts cannot decorate has no strategy id and is always named in the page's
> sentence (§ C, § F, § H); six served fields that nothing drew are gone (§ F); every WARNING of
> § K has a test (§ L, T12); the shared formatting helpers move to `shared/` (§ H); the Overview
> part owns its helper and its text (§ H, § I, § M); each unit has its gate, its first red test and
> its revert (§ L, § M). Two questions stay open, both for the prototype review (§ O, Q1 and Q2).

**The answer in one paragraph.** The panel reads one new route, `GET /api/positions/open`, which
answers for the WHOLE system and takes no parameter. Its two lists are built by iterating over the
output of the mode guard's own reader, `SqlAlchemyModeOriginReader`: the same class, the same two
SQL statements and the same domain fold (`fold_open_allocations`) that decide whether the worker
may start. Every element that reader returns becomes one row, unconditionally; the figures, the
margin, the leverage and the venue mark only decorate a row and can never remove one. In-flight
orders the guard cannot judge (no exchange order id yet) are added on top. So an empty answer means
that the guard's two inputs were empty at that instant, for either value of `DRY_RUN`. No file of
the guard changes, so its 27 domain tests, the 16 integration tests of its reader and its wiring
tests keep pinning it as they do today. Every page of the panel is a selection from that one answer, held in one
query cache: the row marks, the detail page's section, and the Overview's list and count. The
Strategies page draws only what the selected exchange holds: three labelled figures above the list
(how many positions are open, how many orders are in flight, when that was read) and, under them,
the names of what that exchange holds and its list does not show. No screen answers for the whole
system; the worker's guard does, at every start (§ B). No migration, no lock, no write.

### A. Findings from the code (verified at HEAD `24f52d7`)

| # | Finding | Where | Consequence |
| --- | --- | --- | --- |
| P1 | The guard's "open" is decided in the domain: per allocation, net base (BUY adds, any other side subtracts, a fee in the BASE currency subtracts) not exactly zero. An allocation with a row whose symbol cannot be split against the pool's currency is open whatever its net. | `execution/domain/mode_origin.py:100-150` | This is the one definition the panel reads (§ B). |
| P2 | The guard's reader aggregates the whole ledger with no `WHERE`: every pool, enabled or not, and every strategy, archived or not. The origin of a fill is a PREFIX test on `exchange_fill_id`, grouped in SQL. | `execution/infrastructure/mode_origin_reader.py:56-119`; `execution/domain/fill.py:16` | A view filtered by exchange can show nothing while the guard refuses (§ B, § H). |
| P3 | The guard refuses on an in-flight order too: a `SUBMITTED` attempt whose `exchange_order_id` is recorded, judged by the `fake-order-` prefix. A `SUBMITTED` attempt with a NULL order id is skipped: nothing in the row says which mode wrote it. | `mode_origin_reader.py:121-169` (the `WHERE` at 144-147); `mode_origin.py:83-85, 191-203` | The panel shows both kinds (§ B). |
| P4 | An opening attempt is inserted `SUBMITTED` and committed BEFORE the order is sent; the order id is written afterwards. So a NULL order id is a normal, short state, and a lasting one after a crash in between. | `execution/application/place_order.py:186-215, 222, 252` | "Origin unknown" is a real row state, not a fault. |
| P5 | Fills and the attempt's `FILLED` status are written in one commit. | `execution/application/settle_execution.py:113-145` | No instant exists at which an order is neither in flight nor in the ledger (§ G). |
| P6 | The guard is a pure use case over a two-method port, called from the worker's start with its own short session. | `execution/application/assert_mode_matches_ledger.py:33-49`; `execution/application/ports.py:386-403`; `main.py:771-792` | The same adapter can be given to a second caller without touching the guard. |
| P7 | The performance path derives "open" on the LIVE groups only, from the first row's symbol only, and requires both a buy and a sell for "closed". An unresolved allocation is counted apart and logged, not listed. | `performance/domain/derive_trade.py:94-96, 122, 153-158`; `performance/application/read_pool_performance.py:53-58`; `allocation_fills_source.py:135` | `excluded.open_trade_count` can read 0 while the guard refuses. |
| P8 | The panel shows that count in `MonthlySummary` and in no other component; it shows neither the rehearsal count nor the unresolved count. The first writing said "on the Overview and nowhere else", which is inexact: the component has two callers (P27). | `frontend/src/features/overview/MonthlySummary.tsx:43-48`; `en.json:79-80` | The owner has no sign of a rehearsal or unresolved position today. |
| P9 | Three more implementations of the rule exist: `net_base_quantity` (one allocation, base-fee rule), `symbol_holdings` (one market, base-fee rule, `HAVING net <> 0`; it raises on an unsplittable symbol) and `net_positions_by_symbol` (per raw symbol, a DIFFERENT fee rule: any fee not in the settlement currency subtracts). | `ledger/infrastructure/repository.py:56-88, 149-214, 90-147` | They feed closes, the archive check, the key delete and the reconciliation. This design changes none of them (§ N). |
| P10 | No route serves an open operation. `operation_figures` needs a closing side and answers `None` without one. | `performance/infrastructure/performance_router.py:402-487`; `performance/domain/operation.py:200-205` | The figures of an open position need their own pure function (§ D). |
| P11 | The margin an opening order is built with is `reservations.amount`. An allocation IS its reservation (`ledger_entries.allocation_id` is a foreign key to `reservations.id`). | `place_order.py:150-159`; `allocation/infrastructure/models.py:45`; `ledger/infrastructure/models.py:42-44` | "Margin granted" is that column, never recomputed. |
| P12 | The leverage is recorded on the OPENING attempt, which is unique per reservation. It is NULL for a spot order; a close records none. The simulated exchange sizes at 1 and that 1 is recorded. | `place_order.py:183-198, 265-282`; `execution/infrastructure/models.py:60-62, 86-88`; `close_position.py:223-226`; `fake_exchange.py:108, 167` | A rehearsal position shows 1x because 1 is stored; a spot position shows no leverage. |
| P13 | The reconciliation's ledger side has NO origin filter: rehearsal fills count. The scan is skipped whole under `DRY_RUN`, and so is the preparation of booking proposals. | `repository.py:129-138`; `reconciliation/application/reconciliation_scan_handler.py:110-119`; `prepare_booking.py:112-118` | See § E for whether a rehearsal position can carry the venue mark. |
| P14 | A discrepancy row is keyed by pool and MARKET KEY, stores the ids of the allocations open at that observation, has a lifecycle `status` (`OBSERVED` or `CONFIRMED`) and is open while `resolved_at` is NULL. Under `DRY_RUN` nothing updates or resolves it. | `reconciliation/application/scan_pools.py:165-172, 229-238`; `reconciliation/infrastructure/models.py:57-67, 82-84`; `reconciliation/domain/positions.py:57-64` | The mark can be keyed by allocation id, which a stale row cannot fake (§ E). |
| P15 | The panel reads pending booking PROPOSALS only (`['bookings','pending']`), filtered by exchange on the client, in the Overview's rail. No frontend file reads `/reconciliation/discrepancies`. | `frontend/src/features/bookings/usePendingBookings.ts:24-29`; `BookingsListView.tsx:62-65`; `DecisionRail.tsx:19-23` | "Leads to the pending decision" has a target only while a proposal is `PENDING` (§ E, § O). |
| P16 | Only the two attributable kinds are ever proposed; `AMBIGUOUS_PARTIAL_REDUCE` (two or more open allocations on one market) and `NO_MATCHING_ALLOCATION` never are. | `prepare_booking.py:130-136`; `reconciliation/domain/classify.py:71-92` | A confirmed disagreement on a market two strategies hold has no decision to lead to. |
| P17 | Each row of the strategies list already makes its own request, `GET /performance/strategies/{id}`, and each of those runs the pool-wide aggregate on the server. | `frontend/src/features/strategies/StrategyRow.tsx:41`; `performance/application/read_strategy_performance.py:62` | The new read must not add a second request per row (§ F). |
| P18 | The performance hooks have a stale time of 60 s and NO refetch interval; the pools and health hooks refetch every 60 s. Approving a booking invalidates `['bookings','pending']` only, and so does rejecting one. | `frontend/src/shared/api/performance.ts:240-279`; `pools.ts:48-56`; `health.ts:29-38`; `ConfirmBookingDialog.tsx:35, 43`; `RejectBookingDialog.tsx:36, 42` | § H sets the new hook's freshness and what invalidates it. |
| P19 | The closed-trades table always asks for rehearsal rows and marks them with the mode badge's words in the `decision` token. | `performance.ts:177-178`; `TradesTable.tsx:41-45, 100-104`; `DryRunBadge.tsx:30-36` | The origin tag of an open position reuses those words and that token. |
| P20 | The list is one grid from `lg`; each row is a subgrid of five tracks, and the name, pool line and uptime sit in the first track. The detail page's closed trades are a full-width section under the two-column grid. | `StrategiesPage.tsx:68-76`; `StrategyRow.tsx:99-121`; `StrategyDetailPage.tsx:68-89` | The marks are a fourth child of the row, its second grid row in the first track, as the prototype draws them (the first writing put them inside the name block); the new section sits above `TradesTable`. |
| P21 | The API's sessions use the engine's default isolation. No file under `backend/src` sets an isolation level. | `shared/db.py:21-28`; grep for `isolation_level`, `REPEATABLE READ`, `SERIALIZABLE`: no match | The snapshot of § G is the first of its kind here. |
| P22 | The fills of one CLOSED operation are served by a route keyed by strategy and allocation. Whether that read also answers for an allocation that is still open is **not verified**: no statement either way was found in `performance_router.py` or in `read_operation_fills.py`. | `performance_router.py:459-487` | Nothing in this design calls that route or depends on it. An open position does not open onto its fills in this delivery (§ O, Q5; § N, follow-up F2). |
| P23 | Production held 4 `fake-fill-` ledger rows on 2026-09-29. No later count is recorded in the repository. | `tasks.md:151` | The cost figures of § G are stated by statement, not by measured time. |
| P24 | The exchange tabs are the distinct exchanges of `GET /pools`, and that route lists every pool, enabled or not. The Strategies page and the Overview draw nothing pool-scoped until that scope is known, and each filters by the selected exchange on the client, as the pending bookings do. A strategy's exchange cannot be changed after it is created. | `frontend/src/shared/scope/exchange-store.ts:36-38, 69-79`; `accounts/infrastructure/pool_overview.py:12-13`; `StrategiesPage.tsx:36-49, 63`; `OverviewPage.tsx:41-44`; `BookingsListView.tsx:62-65`; `strategies/infrastructure/router.py:16` | An exchange has a tab exactly when it has a row in `capital_pools`. The scope of 2026-10-12 is this same client-side filter, applied to the one answer (§ H). |
| P25 | Every element carries an exchange: the three columns are `NOT NULL` on a fill and on an attempt. A reservation's pool is a row of `capital_pools` by foreign key, an opening attempt takes its pool from its reservation, and a fill takes its pool from its attempt. No source file deletes a pool row: a pool is only ever disabled. | `ledger/infrastructure/models.py:48-50`; `execution/infrastructure/models.py:74-76`; `allocation/infrastructure/models.py:22-30`; `place_order.py:191-193`; `settle_execution.py:225-227`; `accounts/infrastructure/capital_pool_writer.py:55-71`; grep for `delete(` under `backend/src`: strategies, jobs and credentials only | A position opened by this system sits on an exchange that has a tab. An element whose exchange has no tab has a pool that is not its reservation's, which the read can detect without a new statement (§ C). |
| P26 | Where each pool comes from, traced on 2026-10-12 (the validation's findings, re-read here). A reservation takes its pool from its strategy's policy. A closing attempt names its command's pool, and both callers build that command from the strategy's policy or from the pool the close was asked for. A booked fill takes its proposal's pool, which is its discrepancy's. Only `reservations` and `strategies` carry the composite foreign key to `capital_pools`; a fill and an attempt carry three text columns and no key. | `allocation/application/allocate_capital.py:123, 161-166, 261-272`; `signals/application/process_signal.py:506, 768-773`; `signals/application/close_orphans.py:174, 219-224`; `close_position.py:216-218`; `reconciliation/application/approve_booking.py:302-304, 319-321`; `prepare_booking.py:168-172, 270-272`; `allocation/infrastructure/models.py:22-30`; `strategies/infrastructure/models.py:32-40` | P25's "has a tab" holds by CODE PATH, not by schema: nothing in the database stops a fill or an attempt from naming a pool that is not its reservation's. § C's check is what notices if one ever does. |
| P27 | `MonthlySummary` has two callers: the Overview's pool panel, with the pool's report, and the strategy detail page's performance block, with the strategy's report. The second one writes "N open trades not in the curve" for ONE strategy, live positions only, and a test pins it. | `PoolPanel.tsx:146`; `features/strategies/StrategyPerformance.tsx:56`; `StrategyPerformance.test.tsx:107-115` | Decision 65 changes the Overview's count. It says nothing of the detail page's, which nobody had seen was there; the owner chose on 2026-10-13 to leave it live-only (§ H; § O, Q6). |
| P28 | The "Live" badge is `border-loss text-loss`, with the comment "because real money moves", and one test pins `text-loss` (it does not assert the border). No spec file names the badge's colour. | `frontend/src/shared/layout/DryRunBadge.tsx:14, 35`; `AppShell.test.tsx:117-124`; grep of `specs/` for "loss colour": no line about the badge | The change to `gain` is two lines, one comment and one test (§ H, § L). |
| P29 | The app runs under a plain `BrowserRouter` of react-router 7.18.4 and never renders `<ScrollRestoration>`. No source file reads the location's hash or scrolls an element into view. | `frontend/src/app/App.tsx:1-9`; `frontend/package.json:25`; grep of `frontend/src` for `ScrollRestoration`, `scrollIntoView`, `location.hash`: no match outside tests | A link to an anchor on another page lands at the top of that page. The rail has to bring itself into view (§ E, § H), and T19 pins that it does. |
| P30 | `tableFigureText` and `figureText` write a decimal POINT in every language: they take no locale. `amountText` takes one and writes the language's separator. `clockText` writes hours and minutes, never seconds. | `features/strategies/format.ts:51, 60-77, 135-139`; `features/overview/format.ts:32` | In Spanish the closed trades table already reads `184.3` beside `0,17`. Example 25 of the prototype draws a comma in both; the owner chose the point on 2026-10-13 (§ I; § O, Q9). A time with seconds needs a helper (§ H). |
| P31 | Two things in the frontend's tests answer to a new file or a new request. One test asserts, with `toEqual`, that the files using a `decision` class are exactly a list of seven. And the harness's `stubApi` rejects every URL it does not know with "unexpected fetch", which a page shows as an alert; existing tests assert one alert, or none. | `frontend/src/features/overview/panel-tokens.test.ts:18-19, 52-81`; `frontend/src/test/harness.tsx:198-199, 268-270`; `StrategiesPage.test.tsx:217, 227`; `OverviewPage.test.tsx:279, 292` | A positions file that writes `text-decision` turns the first red, and a page that asks for `/positions/open` turns the others red. Both are steps of op.2, each before the code that needs it (§ H, § L, § M). |
| P32 | The leverage is stored as `Numeric(18, 8)` and written by `wire.plain`, which is `format(value, "f")`: `2.00000000`. `figureText` drops trailing zeros and answers `2`. | `execution/infrastructure/models.py:88`; `shared/infrastructure/wire.py:38-41`; `features/strategies/format.ts:32-53, 60-64` | The cell is `figureText(leverage)` and an `x`, never the served string as it is (§ H). |
| P33 | The guard's element is built from ONE row of the allocation's groups: `first = rows[0]` gives its strategy name and its pool, and the reader's statement has no `ORDER BY`. Its `symbol` joins the RAW spellings of the fills, not market keys. Its strategy name is read through `ledger_entries.strategy_id`. `market_key` strips the contract marker, upper-cases, and never raises. | `mode_origin.py:124-132`; `mode_origin_reader.py:62-88`; `execution/domain/market_symbol.py:65-77` | An allocation whose fills name two pools, or a strategy other than its reservation's, shows one of them, and which one is not fixed. The read compares every group and logs a difference (§ C). The pairs the panel draws are normalised by the route, not by the guard (§ C). |
| P34 | The app's query client is `new QueryClient()`, with no option: three retries at TanStack's default delays before a query reads as failed. | `frontend/src/main.tsx:18` | The first-failure state follows about 7 s of "Reading open positions…" (the delays are the library's defaults and were not measured). § H's state table says so. |
| P35 | Hex colours, `var()` in a class and style properties are already refused across every source file by one test. SQLAlchemy opens a transaction on asyncpg with an isolation level and a read-only flag when they are given as execution options, and its pre-ping runs in a transaction of its own. | `frontend/src/shared/theme.test.ts:51-62, 150-175`; `backend/.venv/Lib/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:820-831, 838-848` | T11 does not repeat the first (§ L). The second is the idiomatic alternative to a raw `SET TRANSACTION` (§ G; § L, T6). |

**Verified since the first writing** (the validation of 2026-10-11, the first two re-read for this
revision): the archived mark is `strategies.archived_at`
(`strategies/infrastructure/models.py:62`); `require_admin_token` depends on the settings only, not
on a session (`shared/infrastructure/admin_auth.py:86-87`), so it issues no statement before the
snapshot's; the migration files 0011, 0012, 0015, 0020 to 0022, 0024 and 0025 exist;
`frontend/vite.fixture.config.ts` exists and is excluded from git.

**Still not verified**, and said so where it matters:

- `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY` as the first statement of a
  session's transaction. No code under `backend/` sets an isolation level; `get_session` yields a
  plain session (`shared/db.py:26-28`), and `pool_pre_ping=True` pings the connection when it is
  checked out, outside the session's transaction (§ G; § L, T6).
- A reservation that is not `FILLED` under a position. It is plausible: `SUBMITTED` may go to
  `EXPIRED` or `RELEASED`, both terminal, and the sweeper treats `SUBMITTED` as sweepable
  (`allocation/domain/reservation.py:36-52`). Whether a fill can then still be recorded was not
  established (§ K, row 4).
- `holding_guard.py` was not re-read (decision 64 records that it looks at one strategy on one
  symbol).
- Whether the fills route answers for an open allocation (P22). Nothing here depends on it.
- Added on 2026-10-12: whether i18next falls back to a key with no plural suffix when it is given
  a `count`. No key of § I depends on it: a key that takes `count` has both suffixed forms, and
  the others name their variable otherwise. The three other points this bullet first listed are
  settled, with their lines, in P26 and P29.

**Where the inputs were inexact.** (6, found on 2026-10-12) The live-only count is not on the
Overview alone: the strategy detail page draws it too, for the strategy (P27). (1) "SUBMITTED attempts judged by their order id" leaves out
the attempt whose order id is still NULL: the guard skips it (P3). (2) Closed rehearsal operations
are served on request by the API, but the panel always asks, so on screen they are always listed
and marked (P19). (3) The panel shows booking proposals, not discrepancies (P15). (4) The existing
performance hooks do not poll; only pools and health do (P18). (5) The performance path does not
drop an unresolved allocation without a trace: it counts it in the body and logs a WARNING; it is
the PANEL that shows nothing of it (P7, P8).

### B. What the guard refuses on, and what the panel must therefore show

The guard refuses a start when `find_mismatches` is not empty (`mode_origin.py:153-216`). Every
mismatch is made from one element of one of two sequences, and from nothing else: an element of
`reader.open_allocations()` (kind `POSITION`) or of `reader.in_flight_attempts()` (kind `ORDER`).

| What the tables hold | Guard, `DRY_RUN=false` | Guard, `DRY_RUN=true` | The panel |
| --- | --- | --- | --- |
| Open allocation, rehearsal fills only | refuses | starts | position, origin "Dry run" |
| Open allocation, live fills only | starts | refuses | position, origin "Live" |
| Open allocation holding fills of both | refuses | refuses | position, origin "Dry run and live" |
| Allocation with an unsplittable symbol, any net | as its fills' origin says | as its fills' origin says | position, figures empty with the reason |
| Allocation whose net is exactly zero | not seen | not seen | not shown |
| `SUBMITTED` attempt, order id `fake-order-...` | refuses | starts | order in flight, "Dry run" |
| `SUBMITTED` attempt, any other order id | starts | refuses | order in flight, "Live" |
| `SUBMITTED` attempt, order id NULL | not seen | not seen | order in flight, "origin unknown" |
| A reservation with no attempt yet | not seen | not seen | not shown |

**The invariant.** If the answer of `GET /api/positions/open` has an empty `positions` and an empty
`orders`, then, on the same database state, `assert_mode_matches_ledger` raises for neither value
of `DRY_RUN`.

**How it is guaranteed: one definition, read by both, and nothing in between that can drop a row.**

1. The definition of "open" stays where it is, `fold_open_allocations` in
   `execution/domain/mode_origin.py`. It is not moved, copied or wrapped.
2. The panel's use case receives the guard's reader through a port of the same two methods (typed
   with performance's own read-only protocols, which the reader satisfies structurally), and the
   router gives it `SqlAlchemyModeOriginReader`, the class the worker's start uses
   (`main.py:790-792`). So the SQL that feeds the fold is the same statement too, not a second one
   that could gain a filter.
3. The use case emits exactly one row per element of each sequence. The facts it reads afterwards
   (§ C) are looked up by id and attached; an id with no facts keeps its row with empty figures.
   No branch of the use case filters, groups or merges the two sequences.
4. The client draws every element of the answer on the tab of the element's own exchange, and on
   no other (owner, 2026-10-12): in a row's mark when its strategy's row is on screen, otherwise
   by name under the figures (§ H). The figures `Open: 0 · Orders in flight: 0` are drawn for a
   tab only from a successful read that holds no element of that tab's exchange.

Points 2 and 3 are pinned by tests (§ L, T1 to T4); point 4 by frontend tests (T9, T10, T15).

**What the scope change of 2026-10-12 does to this section.**

- **What still holds, unchanged.** The invariant above is a statement about the ROUTE's answer,
  and the route still answers for the whole system (§ F). Points 1 to 3 and their tests do not
  change. The guard does not change.
- **What no longer holds.** The first writing gave the panel one sentence for the whole system:
  "Nothing is open on any exchange". The owner does not want the Strategies page to speak of an
  exchange other than the selected one, so that sentence is gone, and no screen of the panel now
  says that nothing is open anywhere.
- **The rule that is true now, per exchange.** For the selected exchange X, a successful read
  draws `Open: 0 · Orders in flight: 0` exactly when the answer holds no element whose
  `pool.exchange` is X. And every element whose `pool.exchange` is X is in a row on screen or is
  named under the figures. The page is complete for ONE exchange at a time.
- **What the whole system's answer is made of now.** Nothing is open anywhere exactly when every
  tab reads zero and zero AND every element's exchange is one of the tabs. The second half is not
  something the owner can see. It holds for every position this system opens (P24, P25), by code
  path and not by a constraint of the database (P26); where it does not hold, the stored data is
  at fault, the read says so in the log at WARNING (§ C; § K, row 17), and the panel shows that
  element on no tab, and says nothing of it, as the owner decided on 2026-10-13 (§ H; § K, row
  25; § O, Q7).
- **What protects a mode change.** Not the panel. The worker refuses to start in a mode that
  cannot close what the ledger holds, whether or not anyone looked: `assert_mode_matches_ledger`
  runs at the worker's start (P6), over a reader that aggregates the whole ledger with no `WHERE`,
  every pool enabled or not and every strategy archived or not (P2), and over every `SUBMITTED`
  attempt that has an order id (P3); the fold reports as open anything it cannot prove flat (P1).
  The table above is its behaviour, case by case. The owner was told this before answering
  (decision 65, 2026-10-12: "It is not a risk to money"). What the panel adds is the way to find
  WHAT is open before the worker refuses: the owner reads each exchange's tab, with the
  strategies disabled or the worker stopped (decision 63).
- **The one thing the guard does not judge** is an attempt with no order id yet (P3, P4). The
  panel shows it, on its exchange's tab, as an order in flight of unknown origin.

**The guard itself does not change.** Not one line of `mode_origin.py`, `mode_origin_reader.py`,
`assert_mode_matches_ledger.py` or `main.assert_dry_run_matches_ledger`, and not one line of their
tests (`tests/execution/domain/test_mode_origin.py`,
`tests/ledger/infrastructure/test_mode_origin_reader_integration.py`,
`tests/execution/application/test_assert_mode_matches_ledger.py`, `tests/test_mode_guard_wiring.py`).
Its observable behaviour is unchanged because its code is unchanged. The reviewer's check is that
the PR's diff names none of the guard's three source files and none of those four test files, and
that its only change to `main.py` is two lines: the import of the new router and the
`api_router.include_router(...)` call that registers it (§ G). `assert_dry_run_matches_ledger` is
not among the changed lines. The reader gains a second caller, which reads and writes nothing more
than the first.

**The alternative not taken: move the fold to a shared module and let both import it.** It would
change the guard's file to reach the same result, and it would still leave two SQL statements
feeding one fold, with their parity resting on a test. Reusing the reader removes the second
statement instead.

**What the invariant does not cover, said so that it is not read as more than it is.**

- **Time.** The panel's read and the worker's start are two instants. A signal processed between
  them opens something. The figures carry the time they were read, and the procedure of decision 63
  (change the mode while nothing is open) is done with the strategies disabled or the worker
  stopped.
- **Other refusals.** A start can still be refused for a reason that is not an open position or an
  in-flight order (a key that does not open, decision 20's checks). Those are not this view's.
- **The panel shows more than the guard refuses on**: positions of the CURRENT mode, and orders
  with no order id. That is the safe direction, and it is why no text of the panel is worded as
  "the mode can be changed".
- **One database.** The API and the worker are assumed to read the same database, as they do in
  production.
- **Other exchanges.** Since 2026-10-12 a tab's figures say nothing of another exchange. Zero and
  zero on one tab is not "nothing is open" (the block above).

### C. The read model

One use case, `ReadOpenPositions`, in `performance/application/read_open_positions.py`. It answers
an `OpenState`: every open position and every in-flight order of the system.

**The sequence.** All of it inside one read-only snapshot (§ G).

1. `in_flight = state.in_flight_attempts()`: the guard's statement.
2. `opened = state.open_allocations()`: the guard's statement and fold.
3. `submitted = facts.submitted_orders()`: every `SUBMITTED` attempt, with or without an order id.
4. Only when `opened` is not empty: `facts.position_facts(ids)` (two statements) and
   `disagreements.confirmed_open()` (one statement).
5. Build. One `OpenPosition` per element of `opened`. One `InFlightOrder` per element of
   `in_flight`, decorated from `submitted` by attempt id; then one more per row of `submitted`
   that step 1 did not return.

**A row the facts cannot decorate stays.** Two cases, both possible only if the snapshot is lost or
the stored data is at fault, and both kept because dropping the row is the failure § B forbids.

- An element of `opened` with no facts: the position is built from the reader's own element (the
  strategy's NAME, the pool, the symbols, the two origin flags) with `figures_missing = NO_FACTS`
  and no strategy id, no date, no fee, no margin and no leverage: each of those is null, never a
  zero.
- An element of `in_flight` with no row in `submitted`: the order is built from the reader's own
  element (the attempt id, the strategy's name, the pool, the symbol, the order id that gives its
  origin) with no strategy id, no `action` and no `submitted_at`.

**The pairs are market keys, on every element.** The reader's element spells its symbols as the
ledger wrote them: `fold_open_allocations` joins the RAW spellings with ` / `
(`mode_origin.py:132`), so one market opened as `STXUSDT.P` and booked as `STXUSDT` reads
`STXUSDT / STXUSDT.P` there. That is right for the guard's log and wrong for a pair on screen.
A decorated position takes its `markets` from the fills' groups (§ D). A position with `NO_FACTS`
has only the reader's string, so the use case splits it on that same separator, passes each piece
through `market_key`, drops the duplicates and sorts: one market, written once. An order's
`market` is `market_key` of its symbol, from either source. This is the route's own code, in
`performance`; `market_key` is imported as `derive_trade` already imports it, and no guard file
changes. § L, T8 and T12 pin it.

Each logs one WARNING with its id (§ K, rows 10 and 16) and is pinned (§ L, T12). § H says where a
row without a strategy id is drawn.

Steps 1 and 2 are in that order on purpose. Should the snapshot ever be lost, an order read as
in flight at step 1 and filled before step 2 is shown twice for one refresh, never missing (P5).

**The statements of step 3 and step 4.** Each is one statement; none is issued per row.

```sql
-- submitted_orders: LEFT joins, so no SUBMITTED attempt can be dropped by a missing parent
SELECT a.id, a.reservation_id IS NOT NULL AS opening,
       a.exchange, a.venue, a.settlement_currency, a.symbol,
       a.exchange_order_id, a.created_at,
       r.strategy_id, s.name, s.archived_at IS NOT NULL AS archived,
       r.exchange, r.venue, r.settlement_currency   -- the reservation's pool, for the check below
FROM execution_attempts a
LEFT JOIN reservations r ON r.id = coalesce(a.reservation_id, a.closes_allocation_id)
LEFT JOIN strategies s ON s.id = r.strategy_id
WHERE a.status = 'SUBMITTED';

-- position_facts, 1 of 2: the fills of the open allocations, served by ix_ledger_allocation
SELECT allocation_id, strategy_id, exchange, venue, settlement_currency, symbol, side,
       upper(fee_currency), sum(quantity), sum(notional), sum(fee),
       min(filled_at), count(*)
FROM ledger_entries
WHERE allocation_id = ANY(:open_ids)
GROUP BY allocation_id, strategy_id, exchange, venue, settlement_currency, symbol, side,
         upper(fee_currency);

-- position_facts, 2 of 2: the grant, the leverage of the opening order, the strategy
SELECT r.id, r.strategy_id, s.name, s.archived_at IS NOT NULL AS archived,
       r.amount, r.status, a.leverage,
       r.exchange, r.venue, r.settlement_currency   -- the reservation's pool, for the check below
FROM reservations r
JOIN strategies s ON s.id = r.strategy_id
LEFT JOIN execution_attempts a ON a.reservation_id = r.id
WHERE r.id = ANY(:open_ids);
```

The fills statement does not test the rehearsal prefix. A position's origin comes from the guard's
own flags and from nowhere else, so the prefix is tested in one statement for both readers.

**The pool of an element, and the one check added on 2026-10-12.** An element's `pool` is the
guard's own: the pool of the allocation's fills for a position (`OpenAllocationOrigin.exchange`,
`.venue` and `.settlement_currency`, `mode_origin.py:59-67`) and the attempt's own columns for an
order (`mode_origin.py:71-81`, and the same columns in `submitted_orders`). It is the label the
guard's refusal prints (`_pool_label`, `mode_origin.py:219-220`), so the panel and the refusal
name the same pool. It is never replaced by the reservation's.

Until 2026-10-12 that pool was a label: every element was named on every view. It is now the key
that decides which tab shows an element (§ H), so a wrong key hides one. The two facts statements
therefore also read the reservation's pool, three columns each and no new statement, and the use
case compares. A position or an order whose pool is not its reservation's keeps its row and its
own pool, and the read logs one WARNING with the allocation or attempt id and both pools (§ K,
row 17; § L, T12). So does a `SUBMITTED` attempt that joins to no reservation at all; both of its
parent columns are foreign keys to `reservations` (`execution/infrastructure/models.py:60-65`),
so that needs an attempt with neither set. A `NO_FACTS` position and an undecorated order have no
reservation row to compare with and are already logged (rows 10 and 16). A reservation's pool
always has a tab (P24, P25), so an element that no tab can show is one of these four cases, and
each of them leaves a line in the log.

**What is compared for a position: every group of its fills, not one** (corrected after
validation). The guard's element takes its pool and its strategy name from ONE row of the
allocation's groups, whichever the database returns first (P33). Comparing that one pool with the
reservation's would miss an allocation whose fills name two pools, and would show one of them
with no fixed rule for which. The fills statement above already groups by `strategy_id`,
`exchange`, `venue` and `settlement_currency`, so the use case has every group at hand and
compares each of them with two things:

- the element's own pool and the reservation's pool: a group that names another pool is a
  difference;
- the reservation's `strategy_id`, which is the `strategy_id` the answer serves: a group whose
  fills belong to another strategy is a difference.

One WARNING per allocation with a difference, with the allocation id, the pools found and the
strategy ids found, and nothing else. It changes NOTHING in the answer: the row stays, its pool
stays the guard's element's, its strategy id stays the reservation's. The panel therefore still
shows such an allocation under one pool, and the log is where the other one is named. An order
has one attempt and one reservation, so its comparison is of those two pools. No statement is
added and no guard file changes.

**Domain types**, in `performance/domain/open_position.py` (new). Pure dataclasses and functions;
the imports are the standard library, `execution.domain.mode_origin`,
`execution.domain.market_symbol`, `performance.domain.closed_trade` and
`performance.domain.operation`.

| Type or function | What it is |
| --- | --- |
| `OpenPosition` | One open allocation: the allocation id, the strategy's id (absent with `NO_FACTS`), name and archived mark, pool, `markets`, `origin`, `figures` or the reason they are absent, `opened_at`, `fill_count`, `fees`, `margin_granted`, `leverage`, `reservation_status`, `venue_disagreement`. |
| `FillAggregate` | One row of the fills statement: `symbol`, `side`, `fee_currency`, `settlement_currency`, summed `quantity`, `notional` and `fee`, the first `filled_at`, the row count. It is NOT a `FillGroup`: that type requires a `rehearsal` flag, and this read has none to give (the origin is the guard's). |
| `OpenPositionFigures` | `side`, `base_currency`, `size`, `opened_size`, `entry_price`: derived together or not at all. |
| `FiguresMissing` | Why they are absent: `UNRESOLVED_SYMBOL`, `SEVERAL_MARKETS`, `FLIPPED`, `NO_FACTS`, `INCONSISTENT`. |
| `open_position_figures(groups)` | § D. Answers the figures or a `FiguresMissing`; never raises for a row. |
| `OpenAllocationElement`, `InFlightAttemptElement` | Two read-only `typing.Protocol`s, owned by `performance` and carrying exactly the attributes the read uses (allocation or attempt id, strategy name, `exchange`, `venue`, `settlement_currency`, `symbol`, and, for an allocation, `holds_rehearsal_fill` and `holds_live_fill`, for an attempt `rehearsal`). The guard's `OpenAllocationOrigin` and in-flight record satisfy them structurally, unchanged; `OpenStateSourcePort`, `ReadOpenPositions` and `origin_of` take them, so `ports.py` imports no `execution` type and nothing is translated or copied (corrected during the build, commit `6889987`). |
| `origin_of(open)` | `mode_origin.Origin` from the two flags of an `OpenAllocationElement` (the guard's `OpenAllocationOrigin` satisfies it): both, `MIXED`; rehearsal only, `REHEARSAL`; otherwise `LIVE`. The mapping `find_mismatches` applies at lines 172-177. |
| `InFlightOrder` | One `SUBMITTED` attempt: the attempt id, the strategy's id, name and archived mark, pool, market, `action` (`OPEN` or `CLOSE`), `origin` (`rehearsal`, `live` or `unknown`), `submitted_at`. The strategy's id, `action` and `submitted_at` are absent on an order the facts could not decorate. |
| `VenueDisagreement` | § E. |
| `OpenState` | `positions`, `orders`. |

**Ports**, in `performance/application/ports.py`, declared by the consumer as that file's ports
are.

| Port | Methods | Adapter |
| --- | --- | --- |
| `OpenStateSourcePort` | `open_allocations()` returning `Sequence[OpenAllocationElement]`, `in_flight_attempts()` returning `Sequence[InFlightAttemptElement]`: two read-only `typing.Protocol`s owned by `performance/domain/open_position.py`, carrying exactly the attributes the read uses (corrected during the build; the guard's `execution` types are not imported, which the layering test `test_the_ports_module_imports_no_type_of_another_module` forbids) | `SqlAlchemyModeOriginReader`, unchanged; it satisfies the port structurally and nothing is translated or copied |
| `OpenPositionFactsSourcePort` | `position_facts(allocation_ids)`, `submitted_orders()` | `SqlAlchemyOpenPositionFactsSource` (new) |
| `ConfirmedDisagreementSourcePort` | `confirmed_open()` | a thin adapter over `SqlAlchemyDiscrepancyRepository.list_discrepancies(status=CONFIRMED, open_only=True)`, the call `PrepareBooking` already makes |

**Which module owns it: `performance`.** It is where decision 43's operations live and where
`FillGroup`, `operation_fees`, the wire types and the router's conventions already are; its
infrastructure already reads `ledger_entries` and `reservations`. `ledger` was considered, since a
position is a projection of the ledger (rule 6), and not taken: `performance/infrastructure`
imports `ledger/infrastructure`, so a `ledger` domain that imported `FillGroup` would close a cycle
between the two packages. `execution` was considered, since the definition lives there, and not
taken: the read joins four modules' tables for a panel view, which is what `performance` exists
for. No new top-level module.

### D. How each figure is derived

All of it is pure `Decimal` arithmetic over the groups of ONE allocation, in the domain. Nothing is
converted and nothing sums two pools (rule 7). "Held side" below is BUY for a LONG and SELL for a
SHORT.

| Field | Derivation | Columns | Unit |
| --- | --- | --- | --- |
| `origin` | `origin_of` over the guard's flags | `ledger_entries.exchange_fill_id` (prefix, in the guard's statement) | - |
| `markets` | the distinct `market_key(symbol)` of the groups, sorted | `ledger_entries.symbol` | market key |
| `side` | `LONG` when the net base is above zero, `SHORT` when below | `side`, `quantity`, `fee`, `fee_currency` | - |
| `size` | the absolute net base: `Σ quantity(BUY) - Σ quantity(SELL) - Σ fee charged in the base currency` | the same | base currency |
| `opened_size` | `Σ quantity(held side)` | `quantity` | base currency |
| `entry_price` | `Σ notional(held side) / Σ quantity(held side)` | `notional`, `quantity` | settlement currency per unit of base |
| `base_currency` | `base_currency_of(symbol, settlement_currency)`, upper-cased | `symbol`, `settlement_currency` | the unit of `size` |
| `opened_at` | the earliest `filled_at` of the allocation | `filled_at` | UTC instant |
| `fill_count` | the number of ledger rows | - | - |
| `fees` | `Σ fee` of every fill, both sides, charged in the settlement currency | `fee`, `fee_currency` | settlement currency |
| `other_fees` | one `{currency, amount}` per other fee currency whose sum is above zero | the same | each in its own currency |
| `margin_granted` | the reservation's amount, as stored | `reservations.amount` where `id` is the allocation id | settlement currency |
| `leverage` | the opening attempt's leverage, as stored | `execution_attempts.leverage` where `reservation_id` is the allocation id | a multiple |

- **Which net.** The base-fee rule, the one the fold applies (P1). It is the same arithmetic written
  a second time, for display only: the DECISION that a row exists is the fold's. § L, T5 pins that
  the two agree on every case; § K, row 9 says what a row shows if they ever do not.
- **Which average.** The quantity-weighted average of the held side, taken from `notional` in a
  60-digit context and written with the existing `Price` type, exactly as a closed operation's
  entry price is (`performance/domain/operation.py:30-32, 208-211`). The divisor is checked before
  the division.
- **A position opened by more than one fill** is one row. Its entry price is the average of those
  fills, `opened_at` is the first of them, and `fill_count` lets the row say "average of 3 fills".
- **A position closed in part.** The system never asks for a partial close; one exists only as a
  venue's partial fill of a close, or as dust. `size` is what remains and `opened_size` what was
  opened; the row shows both when they differ. The entry price is still the average of the held
  side's fills: a close does not change what the position was opened at. `fees` includes the
  closing fills' fees: they are the fees so far. `margin_granted` stays the whole grant, as
  recorded: it is not scaled down.
- **Fees.** `fees` and `other_fees` are `operation_fees(groups)`, the function the closed
  operations use (`operation.py:121-151`), so the two tables cannot count a fee differently. It
  reads three attributes of a group (`settlement_currency`, `fee_currency`, `fee`); its parameter's
  type widens from `FillGroup` to a protocol of those three, which `FillGroup` already satisfies.
  Its body and its tests do not change. A fee in the base currency is listed in `other_fees` and is
  already inside `size`. There is no `fees_complete` flag here: that flag says whether a PnL is complete,
  and an open position has no PnL.
- **Margin granted.** Never recomputed and never compared with the venue. For a futures position it
  is the margin the order was sized from; for a spot position it is the quote amount granted. The
  column's label is "Margin granted" for both: it is what the share took from the pool.
- **Leverage.** Shown as stored. NULL (a spot order, or a row that has none) is an empty cell with
  its reason for a screen reader, never "1x". A rehearsal position shows 1x because the simulated
  exchange records 1 (P12).
- **When the figures cannot be derived**, `side`, `base_currency`, `size`, `opened_size` and
  `entry_price` are null together, `figures_missing` says why, and the row stays, with everything
  else it has.

| `figures_missing` | When | Still shown |
| --- | --- | --- |
| `UNRESOLVED_SYMBOL` | `base_currency_of` refuses a symbol of the allocation | markets, origin, the opening date, fees by currency, margin, leverage |
| `SEVERAL_MARKETS` | the fills name more than one market key | the same, with every market |
| `FLIPPED` | the net's sign is the opposite of the earliest fill's side: the "held side" would be the closes | the same |
| `NO_FACTS` | the facts read answered nothing for an id the guard's reader returned | the strategy's name, the pool, the markets and the origin, from the reader's own element, its symbols normalised to market keys (§ C); no strategy id, no date, no fee, no margin, no leverage: `opened_at`, `fees`, `margin_granted` and `leverage` are null and `other_fees` is an empty list |
| `INCONSISTENT` | the net computed here is zero, or the held side has no quantity or notional above zero | the same as `UNRESOLVED_SYMBOL` |

### E. The discrepancy mark

**What is joined.** The open `CONFIRMED` rows of `reconciliation_discrepancies`, read once per
request through the repository's existing method. No new venue read, no new table, no write.

**The key: the allocation, inside the pool.** A position carries the mark when an open `CONFIRMED`
row of ITS pool lists ITS allocation id in `open_allocation_ids`. The market is not the key.

- **Why not pool and market alone.** Rows are not updated or resolved while `DRY_RUN` is on (P13,
  P14). A row confirmed in a live period can outlive the allocation it named: the booking is
  approved, the worker is stopped before the next scan, the mode is changed. A rehearsal position
  opened later on the same market would then inherit a mark that was never about it. The
  allocation id cannot be inherited.
- **A rehearsal position and the mark.** No filter on origin is added. In practice a rehearsal
  position cannot carry the mark: under `DRY_RUN` nothing is compared, and a live worker cannot
  start with a rehearsal position open (P1, P13). If a stored row names a rehearsal allocation
  anyway, the reconciliation did compare it with the venue, and the mark says so.
- **A market held through more than one allocation**, by two strategies or by one. The row lists
  every allocation open on the market, so every one of those positions carries the mark, and
  `allocation_count` lets each row say that the disagreement is shared: the reconciliation knows
  that the venue's net differs from the ledger's, not which position moved (P16).
- **A market the ledger holds nothing on** (`NO_MATCHING_ALLOCATION`): there is no row to mark. It
  is not this view's; it stays where it is today, in the log and in
  `GET /api/reconciliation/discrepancies`.
- **A row that is only `OBSERVED`** marks nothing: the owner's decision says CONFIRMED.

**What the mark carries** (`venue_disagreement`, null when there is none), and what draws each:
the discrepancy's id, which only matches the row to a pending proposal; the venue's net and the
ledger's net as the reconciliation stored them, drawn in the venue line as "exchange {x}, ledger
{y}"; `allocation_count`, drawn as "shared by N positions on this pair" when it is above one; and
`last_observed_at`, drawn as "last compared": it is what tells a mark of two minutes ago from one
frozen since the mode was changed, which is why a time of another day is written with its date
(§ H). The discrepancy's kind and the instant it was first confirmed are not served: no text of
the panel reads them.

**Two forms of one mark** (owner, 2026-10-12). On a row of the strategies list it is a chip, "Venue
disagrees", beside its position's chip, followed by the link or by "No booking is proposed for
it.". On the detail page and in the Overview's list it is ONE line under its position's row,
across the table's width, in the type of the line of an order in flight and with a solid red
border; § H gives its parts and the component the two lines share.

**Where it leads.** The panel already holds the pending proposals (P15). The mark links to the
Overview's "Needs your decision" rail when a pending proposal names this allocation and this
discrepancy. The rail gains an anchor id, and, because the router does not scroll to an anchor by
itself (P29), an effect that brings the rail into view when the location's hash names it. When no
proposal is pending (the kind is never proposed, the proposal expired or was rejected, or none is
prepared yet), the mark states the disagreement and that no booking is proposed, and leads
nowhere. While the proposals are still loading, or their read failed, the mark draws neither the
link nor those words: it does not know, and "no booking is proposed" would be a claim. The owner confirmed the form without a link on
2026-10-11 (§ O, Q3). A view of the confirmed discrepancies is not in this delivery: it is the next
unit, with a design of its own, and the row's mark will link to it once it exists (§ N, follow-up
F1).

### F. The API

One route, in a router of its own: `performance/infrastructure/open_positions_router.py`, prefix
`/positions`, authentication attached to the ROUTER as on every admin router, registered beside the
others in `main.py:1875-1882`.

```
GET /api/positions/open        no path parameter, no query parameter
```

**Why one route for the whole system, and not one per strategy and one per pool.**

1. The invariant is a statement about the whole system (P2). A route scoped by strategy or by pool
   cannot make it; the whole-system read has to exist anyway.
2. The list renders many rows. One answer shared by every row is one request for the page, where
   the existing figures make one per row (P17).
3. One answer in one cache cannot disagree with itself. With a route per page, the list could show
   a mark that the detail page, read a minute later, does not.
4. The answer is small: one element per open allocation. A strategy holds at most one per pair.

**Whether the scope of 2026-10-12 changes the route: it does not.** The Strategies page now
draws one exchange, and the route could take an `exchange` parameter. It keeps none, for these
reasons.

1. The invariant of § B is about the whole answer, and T1 to T3 compare the route's answer with
   the guard's reader's, whole. A parameter would put a filter between the reader's output and the
   answer, which is the one thing point 3 of § B forbids ("no branch of the use case filters").
2. Which exchange is selected is a state of the panel, not of the system. The panel already
   filters the pending bookings by exchange on the client, from an endpoint with no exchange
   parameter (owner decision 3; P24). The same filter over the same kind of answer is one pattern,
   not two.
3. Three views select from the answer by three different keys: the Strategies page by exchange,
   the detail page by strategy, the Overview by pool. One answer in one cache serves the three
   and cannot disagree with itself; a tab change is a new selection of an answer already held,
   not a request.
4. It would save nothing. The heavy statement is the guard's aggregate, which has no `WHERE` and
   must not gain one (§ G).

Serving the other exchanges' elements to the browser does not go against the owner's decision,
which is about what the page shows. What the page shows is pinned by a test (§ L, T15).

The performance router's rule "every body is one pool" is the reason this is a router of its own.
The answer lists positions of several pools the way `GET /api/reconciliation/discrepancies` lists
rows of several pools (`reconciliation/infrastructure/router.py:162-199`): each element carries its
own pool and its own currency, and no field adds two of them. There is no count and no total in the
body; the client counts what it draws.

**200.** Money, quantities and the leverage are JSON strings in plain notation, prices are rounded
to 18 places, instants are UTC, as `shared/infrastructure/wire.py` writes them.

| Field | Type | Meaning |
| --- | --- | --- |
| `as_of` | instant | the server's clock when the snapshot was read |
| `positions` | list | one per open allocation; sorted by strategy name, pool, market, allocation id |
| `orders` | list | one per `SUBMITTED` attempt; sorted by `submitted_at`, attempt id; an order with a null `submitted_at` (one the facts could not decorate) sorts LAST, and ties go by attempt id |

One element of `positions`:

| Field | Type | Meaning |
| --- | --- | --- |
| `allocation_id` | uuid | the position's identity; rows are grouped by it and never by symbol |
| `strategy_id` | uuid or null | the owner of the allocation; null only with `NO_FACTS`, because the guard's element names the strategy and carries no id |
| `strategy_name` | string | never null: the guard's element carries it |
| `strategy_archived` | boolean or null | so the line under the figures can say why a position is not on the list; null only with `NO_FACTS` |
| `pool` | `{exchange, venue, settlement_currency}` | the pool of the fills, as the guard labels it; three non-empty strings, always. Its `exchange` decides which tab shows the element (§ H) |
| `currency` | string | the pool's settlement currency: the unit of `entry_price`, `fees`, `margin_granted` |
| `markets` | list of strings | market keys, sorted; one element unless the data is at fault. Market keys with `NO_FACTS` too, where they are normalised from the reader's own string (§ C) |
| `origin` | `"rehearsal"`, `"live"` or `"mixed"` | the guard's `Origin` values |
| `figures_missing` | string or null | § D's reason; null when the five figures are present |
| `side` | `"LONG"`, `"SHORT"` or null | |
| `base_currency` | string or null | the unit of `size` and `opened_size` |
| `size` | money or null | what is held now |
| `opened_size` | money or null | what was opened; differs from `size` after a partial close |
| `entry_price` | price or null | |
| `opened_at` | instant or null | null only with `NO_FACTS` |
| `fill_count` | integer | 0 only with `NO_FACTS`; above 1, the detail section writes "average of N fills" under the entry price |
| `fees` | money or null | in `currency`; null only with `NO_FACTS`, where no fill was read: a zero would say that the position paid no fee |
| `other_fees` | list of `{currency, amount}` | never converted; empty with `NO_FACTS` |
| `margin_granted` | money or null | null only with `NO_FACTS` |
| `leverage` | plain decimal string or null | null where none was recorded. It is written with its stored scale, `2.00000000`; the panel drops the zeros (P32; § H) |
| `reservation_status` | string or null | the reservation's status, as stored; the detail section writes a note when it is not `FILLED`; null only with `NO_FACTS` |
| `venue_disagreement` | object or null | § E: `discrepancy_id`, `venue_net_base`, `ledger_net_base`, `allocation_count`, `last_observed_at` |

One element of `orders`:

| Field | Type | Meaning |
| --- | --- | --- |
| `attempt_id` | uuid | the order's identity |
| `strategy_id`, `strategy_archived` | uuid or null, boolean or null | null on an order the facts could not decorate (§ C), and if the attempt's parent row is missing |
| `strategy_name` | string or null | null only if the attempt's parent row is missing |
| `pool` | object | the attempt's own pool columns; three non-empty strings, always. Its `exchange` decides which tab shows the order |
| `market` | string | `market_key` of the attempt's symbol |
| `action` | `"OPEN"`, `"CLOSE"` or null | which of the attempt's two origins is set; null on an order the facts could not decorate |
| `origin` | `"rehearsal"`, `"live"` or `"unknown"` | by the order id's prefix; `unknown` when no order id is recorded |
| `submitted_at` | instant or null | the attempt's `created_at`: how long it has been in flight; null on an order the facts could not decorate |

**Nothing is served that the panel does not draw.** Every field above is read by a component of
§ H: the ids as keys and to match a row to its strategy or to a proposal; the pool by every view's
selection (its exchange by the Strategies page, its three values by the Overview); the names and
`strategy_archived` by the line that names what the list does not show; `currency` and
`base_currency` by the headings and the units; the figures, `opened_at`, `fees`, `other_fees`,
`margin_granted`, `leverage`, `opened_size`, `fill_count` and `reservation_status` by the detail
section; `figures_missing` by the reason under a dash. Six fields of the first writing had no
reader and are not served: a position's `last_fill_at`, the disagreement's `kind` and
`confirmed_at`, and an order's `allocation_id`, `side` and `margin_reserved`.

**Other answers.** 401 without the token, as on every admin route. No 404: the route has no
subject. A failure of the read is a 500 with the usual trace; the client shows it as an error and
never as an empty list (§ H).

**Compatibility.** A route nobody calls yet: a bundle that predates it is unaffected. A bundle that
asks an API that predates it gets a 404, which the client treats as a failure (§ H), unlike the
pool report's 404, which means "no report" (`performance.ts:50-52`).

### G. Layering, consistency and cost

| Component | Layer | File | Change |
| --- | --- | --- | --- |
| `OpenPosition`, `FillAggregate`, `OpenPositionFigures`, `FiguresMissing`, `InFlightOrder`, `VenueDisagreement`, `OpenState`, `OpenAllocationElement`, `InFlightAttemptElement` (read-only protocols, the types `OpenStateSourcePort`, `ReadOpenPositions` and `origin_of` take), `open_position_figures`, `origin_of` | **domain**/performance | `performance/domain/open_position.py` (new) | § C, § D |
| `operation_fees` | **domain**/performance | `performance/domain/operation.py` | Its parameter's type widens to a protocol (§ D). No behaviour changes. |
| `OpenStateSourcePort`, `OpenPositionFactsSourcePort`, `ConfirmedDisagreementSourcePort`, `PositionFacts`, `SubmittedOrderFacts` | **application**/performance | `performance/application/ports.py` | three protocols, two records; `OpenStateSourcePort` is typed with the domain's two protocols, not with `execution` types |
| `ReadOpenPositions` | **application**/performance | `performance/application/read_open_positions.py` (new) | § C's sequence and § K's WARNINGs |
| `SqlAlchemyOpenPositionFactsSource` | **infrastructure**/performance | `performance/infrastructure/open_position_facts_source.py` (new) | § C's three statements |
| `ConfirmedDisagreementSource` | **infrastructure**/performance | `performance/infrastructure/confirmed_disagreement_source.py` (new) | maps `DiscrepancyRecord` to the port's record |
| the router, its bodies, the snapshot dependency | **infrastructure**/performance | `performance/infrastructure/open_positions_router.py` (new) | § F |
| the router's import and `api_router.include_router(...)` | composition root | `main.py` | two lines, and nothing else in that file |
| `SqlAlchemyModeOriginReader`, `mode_origin.py`, the guard's use case, the reconciliation, the ledger repository | - | - | **not changed** |

- **`domain/` gains no framework import.** The new module is dataclasses and `Decimal` arithmetic.
  It imports another module's domain (`execution.domain.mode_origin`), as `derive_trade` already
  imports `execution.domain.market_symbol`. The port module does not: `performance/application/
  ports.py` imports no `execution` type, as `test_the_ports_module_imports_no_type_of_another_module`
  requires. `OpenStateSourcePort` speaks the two protocols that `performance/domain/open_position.py`
  owns, and the guard's reader satisfies them structurally (corrected during the build).
- **Adapters read other modules' tables; the application does not.** The facts adapter imports the
  ORM rows of `ledger`, `allocation`, `execution` and `strategies`, as the performance adapters
  already do. The disagreement adapter is the only file that knows the reconciliation's record.

**Consistency: no lock, one snapshot.** The read writes nothing, takes no advisory lock and no row
lock, so the lock order (pool advisory lock first, then row locks) has nothing to order. What it
needs is that its statements see one state. The first statement of the request's transaction is

```sql
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY;
```

issued by a dependency of the new router, so the use case and the ports know nothing of it. Under
it every statement of § C sees the database as of the first read. A read-only transaction at that
level takes no lock that a writer waits for and cannot fail with a serialization error, so it
cannot delay a settle or an allocation.

- **What a concurrent fill can make it show.** The state of one instant, whole: either the order is
  in flight and the position is not yet there, or the position is there and the order is gone
  (P5). Never both, never neither. The instant is `as_of`; the next refresh shows the next one.
- **Without the snapshot**, at the default level, a fill committed between two statements could
  show a position with the figures of a later state, or an order and its position together. The
  order of § C's steps keeps even that case from showing less than there is.
- **Not verified, and the first thing the tasks prove:** that the session opens its transaction
  with this statement first, on this stack (SQLAlchemy's async session over asyncpg). § L, T6 is
  the proof, on real PostgreSQL. It is the first non-default isolation in the code base (P21).
  What is known: `get_session` yields a plain session (`shared/db.py:26-28`), the router's
  authentication issues no statement (§ A), and `pool_pre_ping=True` pings the connection when it
  is checked out, before the session's transaction begins, so it is not "a query" of that
  transaction. What is not known is whether anything else on this stack issues one first.
- **The idiomatic alternative, recorded after validation.** SQLAlchemy can open the transaction
  at that level itself: `session.connection(execution_options={"isolation_level": "REPEATABLE
  READ", "postgresql_readonly": True})`. On asyncpg the dialect then starts the transaction with
  `isolation` and `readonly` set, and its pre-ping runs in a transaction of its own (P35). It
  asks for the same snapshot without a hand-written first statement, so nothing can slip in
  before it. The dependency of the router uses whichever of the two T6 shows to hold; T6 decides,
  and the use case and the ports know nothing of either.

**Cost.** With nothing open: four statements (the `SET`, the guard's two, the submitted orders).
With something open: seven. The count does not grow with the number of positions (§ L, T7).

- The heaviest is the guard's aggregate over the whole ledger, with no `WHERE`: the statement the
  worker already runs at each start. It is the same order of work as the pool aggregate that every
  row of the strategies list triggers today (P17), issued once for the page instead of once per
  row. Production's ledger is small (P23); no time was measured.
- The facts statements are bounded by the number of OPEN allocations and are served by
  `ix_ledger_allocation` and by the unique index on `execution_attempts.reservation_id`.
- The two statements over `execution_attempts` filter on `status` with no index of their own, as
  the guard's read and `submitted_for_pool` already do.
- § N says when this stops being cheap and what the answer would be.

| Rule | Impact |
| --- | --- |
| `DRY_RUN` (rule 1) | The read is the same in both modes and needs no credential. No test needs one. |
| Idempotency (2), webhook (3), allocation transaction (4) | Untouched. No lock, no write. |
| Pools (5), native currency (7) | Each position is in its own pool and currency. No field, on the server or in the panel, adds two positions' money. The count the panel draws is a number of positions, never an amount. |
| Ledger (6) | Read only. Positions are a projection of it, grouped by allocation. |
| Credentials (8) | Untouched. Nothing is read from a venue. |

### H. Frontend

Rewritten on 2026-10-12. The prototype (`visual/project/OpenPositions.html`, commit `6603dea`) is
the reference for every layout below. Where this section and the picture differ, the difference
is named and has its reason; where the picture draws nothing for a case, the section says so and
builds the case from parts the picture does draw.

**The data.** `frontend/src/shared/api/positions.ts` (new): `fetchOpenPositions`, a shape check of
every element in the manner of `performance.ts` (a body that is not this shape is an error, never
an empty list; a 404 is an error), and `useOpenPositions()`.

| | |
| --- | --- |
| Query key | `['positions','open']`: one key, read by every component below |
| Stale time | 60 s, as the performance hooks |
| Refetch interval | 60 s, as the pools hook: this is a state the owner acts on, not a history |
| On window focus | TanStack's default, which the app's client keeps (`frontend/src/main.tsx:18`): a stale answer is read again when the tab is looked at |
| Invalidated by | a booking approved or rejected (beside `['bookings','pending']`), and the "Read again" button |
| Not invalidated by | the enable switch, a share change, an archive: none of them opens or closes anything |

The shape check requires `pool.exchange`, `pool.venue` and `pool.settlement_currency` to be
non-empty strings on every element, as `fetchPools` requires them of a pool (`pools.ts:17-30`). An
element without them refuses the whole answer: a position that no tab could claim must be an
error on screen, never a row that silently belongs nowhere.

Five pure functions in the same file select from the one answer. Each takes an `OpenState` and
answers an `OpenState`, so they compose, and none of them asks the server anything.

| Selector | What it keeps | Who calls it |
| --- | --- | --- |
| `ofExchange(state, exchange)` | the positions and the orders whose `pool.exchange` is exactly that string | the Strategies page, for everything it draws; the detail page, for its unmatched count |
| `ofStrategy(state, strategyId)` | the positions and the orders of that strategy; a null `strategy_id` belongs to no strategy | `OpenMarks`, always composed as `ofStrategy(ofExchange(state, strategy.exchange), strategy.id)`, never over the whole answer; `OpenPositionsSection`, over the whole answer |
| `ofPool(state, pool)` | the elements whose pool has those three values, never the exchange alone (rule 7) | `PoolOpenPositions` and the Overview's count |
| `notShown(state, visibleStrategyIds)` | the elements whose `strategy_id` is null or is not in the set | `OpenStateLine`, over the result of `ofExchange` |
| `unmatched(state)` | the elements whose `strategy_id` is null | the detail page, over the result of `ofExchange` |

`ofPool` lived in the Overview's own file while that part could be dropped. It is here now, with
the others.

**The scope rule (owner, 2026-10-12): the Strategies page shows nothing of another exchange.**
Everything that page draws is selected from `ofExchange(state, exchange)`, where `exchange` is the
selected tab's, and from nothing else:

- the two counts are the lengths of its two lists;
- a row's marks are `ofStrategy(ofExchange(state, strategy.exchange), strategy.id)`. A row is on
  screen only when its strategy's exchange is the selected one (`StrategiesPage.tsx:63`), so this
  is the same selection, written from what the row has;
- the line under the figures is `notShown` of it, for the ids of the rows on screen.

So the count "Open" always equals the position chips on screen plus the positions named under
the figures, and no pair, name or count of another exchange can reach the page. Changing the tab
selects again from the answer already held; it asks the server nothing. § L, T15 pins it.

**Why the composition is written out, and not left to "the row's strategy".** Take a stored
fault: a strategy of exchange X whose position's fills name a pool of exchange Y. `ofStrategy`
alone would draw Y's pair on X's tab, and X's count would be one less than its chips. With the
composition the position is not on X's row; it is counted on Y's tab and named under Y's
figures, since its strategy has no row there. The fault itself is logged by § C's check. T15's
fixture holds exactly this element.

The other two pages keep their own key. The detail page selects by strategy id over the whole
answer: a strategy's page shows that strategy's positions wherever the ledger put them, and the
tabs follow the strategy's exchange (`StrategyDetailPage.tsx:38-44`). The Overview selects by
pool, among the pools of the selected exchange (`OverviewPage.tsx:41-44`).

**Components.** New files under `frontend/src/features/positions/`; the three pages only place
them. `features/positions` imports from `shared/` and, for the pending proposals,
`usePendingBookings` from `features/bookings`, as `features/overview` already does
(`DecisionRail.tsx:3-4`). Nothing imports back into it but the three pages.

| Component | File | Where it sits | Props | What it is |
| --- | --- | --- | --- | --- |
| `OpenStateLine` | `OpenStateLine.tsx` | `StrategiesPage`, between the title row and the list, and on no other page (§ O, Q4). Drawn only once the scope is ready and an exchange is selected | `exchange`, the selected tab's; `visibleStrategyIds`, a set, or null while the strategies list is loading | The three figures of that exchange, the lines under them and the "Read again" button |
| `OpenMarks` | `OpenMarks.tsx` | `StrategyRow`, as a fourth child of the row: from `lg` the row's second grid row, in the first track only; below `lg` a full-width last line of the wrapping row | `strategy` | One chip per position and per order of that strategy on its exchange, the venue chip after its position's chip. Nothing at all when there is none |
| `Mark` | `Mark.tsx` | inside `OpenMarks` | `kind`: position, order or venue; `origin` | The chip: one base class and the variants of the table below |
| `MarkLine`, with `OrderLine` and `VenueLine` | `MarkLine.tsx` | under a table, in a table's sub-row, in a card | `variant`: order or venue; `origin` for an order | The one line component, and the two lines made from it |
| `OriginTag`, `origin.ts` | `OriginTag.tsx`, `origin.ts` | in a chip, a line, a table cell, a card | `origin` | The origin's word in its token. `origin.ts` is the ONE table from an origin to its text key, its text class and its border class; the chip, the line and the tag all read it. It is the ONLY file under `features/positions` that writes a `decision` class as a literal (see "Amber" below) |
| `PositionsTable` | `PositionsTable.tsx` | inside the two components below | `positions`; `variant`: strategy or pool; `proposals` | The table from `md` and the cards below it, each row with its sub-rows |
| `OpenPositionsSection` | `OpenPositionsSection.tsx` | `StrategyDetailPage`, a full-width section between the two-column grid and `TradesTable` | `strategy` | The heading, the strategy's positions, its orders as lines, the notes |
| `PoolOpenPositions` | `PoolOpenPositions.tsx` | `PoolPanel`, under the month grid and its summary, OUTSIDE the `report !== null` condition that wraps those two (`PoolPanel.tsx:143-148`) | `pool` | The heading and the pool's positions, the strategy's name first |
| the count | `features/overview/MonthlySummary.tsx` | where today's "open trades" part is | a new optional prop, `open` | "N open, M of them dry run" |
| the badge | `shared/layout/DryRunBadge.tsx` | the top bar | - | "Live" in `gain` |
| the rail | `features/overview/DecisionRail.tsx` | the Overview | - | an `id`, and an effect that brings it into view |

Reused as they are: `cn`, `Link`, `usePendingBookings`, the trades table's column words, and the
formatting helpers below.

**The summary: `OpenStateLine`** (examples 1 to 12, 25a to 25c, 26a).

- **What it counts.** "Open" is the number of positions of the selected exchange and "Orders in
  flight" the number of its orders: the two lengths of `ofExchange(state, exchange)`. They count
  what the exchange holds, not what the list shows, so a position of an archived strategy is in
  the count and is named on the second line (example 10: `Open: 2`, with no position chip on any
  row). The figures name no exchange: the selected tab does.
- **"Last read"** is the answer's `as_of`, with seconds.
- **The layout, as drawn.** One wrapping line: the figures and, under them, the lines; then the
  button. The figures are mono, 12 px, tabular, `text-ink-2`; each label is `text-ink-3` and is
  followed by a colon; a `·` in `text-ink-3` separates them. Below `sm` the figures wrap and no
  separator is drawn, so that none starts a line. The button is bordered (`border-rule`) and 44 px
  tall.
- **The second line, "Not on this list: {items}."**, is drawn when `notShown` is not empty, in
  `text-ink-2`. It names what the selected exchange holds and its list does not show, and only
  that (owner, 2026-10-12): a position or an order of an archived strategy while archived ones are
  hidden; one that could not be matched to a strategy; and, by the same rule, every element of
  the exchange when the strategies list failed to load, since then the list shows none. It never
  names anything of another exchange: `notShown` is given `ofExchange`'s result.
- **One item** is these parts joined by ` · `, in this order: the strategy's name; "archived" when
  the strategy is; the pair (the element's market keys, joined by ` / ` when it has several; they
  are market keys for every element, § C, so one market is never written under two spellings);
  "order in flight" for an order; the origin's word; "figures not readable" for a position whose
  `figures_missing` is not null. Items are joined by `; `, positions first, then orders, each in
  the answer's order. Example 10 draws two positions; an ORDER as an item is not drawn in the
  prototype and is built from the chip's own words. **An order whose strategy name is null** (its
  parent rows are missing: a stored-data fault, logged by the backend, § K) has no first part, so
  its item is the order's own mark text with no name in front: `{market} · order in flight ·
  {origin}`, the same words the approved order chip uses (prototype examples 6 and 10), through the
  existing keys `positions.order.inFlight` and `positions.origin.*` in both languages. An order
  that has a name keeps the item format above. This wording is composed from approved parts, not
  drawn by the prototype, and is shown to the owner at the by-eye review (task op.4.13).
- **While the strategies list is loading** the second line is withheld (`visibleStrategyIds` is
  null): every element would otherwise be named for an instant and then move to its row. The
  figures are drawn all the same, since they do not depend on the list.
- **A failed refresh** keeps the last figures, with "Last read" still the last good answer's time,
  and adds "Could not be refreshed since {time} UTC." in `text-loss` as the last line (examples
  11c and 11d). It is detected as an error on a query that still holds data.
- **The live region.** The two counts and the lines under them are inside one `role="status"`
  region; the "Last read" figure sits on the same visual line and OUTSIDE that region. The
  prototype puts the role on the whole block. This is the one difference in markup, and it has no
  visual effect: the time changes at every refresh, and a region that holds it would be announced
  once a minute for a state that did not change (§ L, T10). The loading text is a `role="status"`
  and the first failure a `role="alert"`, as drawn in example 11.
- **Before the scope is known**, or when no exchange exists, the component is not drawn and asks
  for nothing: figures for an exchange nobody can name would be unfiltered data under a tab, the
  failure the scope exists to prevent (`exchange-store.ts:58-67`). The page's own text already
  says why the list is absent (`StrategiesPage.tsx:36-49`).

**The marks: one rule** (owner, 2026-10-12; the key "Reading the marks" of the prototype). The
shape says what a mark is, the colour says the origin, and red says one thing only: something is
wrong and needs the owner. No mark says a result.

| Mark | Fill | Border | Words |
| --- | --- | --- | --- |
| Position, dry run | `bg-panel-2` | solid, `border-decision` | pair and side in `text-ink`, "Dry run" in `text-decision` |
| Position, live | `bg-panel-2` | solid, `border-gain` | pair and side in `text-ink`, "Live" in `text-gain` |
| Position holding fills of both origins | `bg-panel-2` | solid, `border-loss` | pair and side in `text-ink`, "Dry run and live" in `text-loss` |
| Position, origin unknown | `bg-panel-2` | solid, `border-rule-strong` | "origin unknown" in `text-ink-3`. The key draws it; no answer produces it today, since a position's origin is one of three values (§ F) |
| Order in flight, dry run | `bg-transparent` | `border-dashed`, `border-decision` | pair and "order in flight" in `text-ink`, "Dry run" in `text-decision` |
| Order in flight, live | `bg-transparent` | `border-dashed`, `border-gain` | the same, "Live" in `text-gain` |
| Order in flight, origin unknown | `bg-transparent` | `border-dashed`, `border-rule-strong` | the same, "origin unknown" in `text-ink-3` |
| Venue disagrees, the chip | `bg-transparent` | solid, `border-loss` | "Venue disagrees" in `text-loss` |
| The separator ` · ` inside any mark | - | - | `text-ink-3` |

- **The chip's base**, common to every row above: mono, 12 px on a 16 px line, 2 px by 8 px of
  padding, a 4 px radius, a 1 px border, one line (`whitespace-nowrap`). Below `lg` a chip may
  break anywhere, so a long pair cannot push the row wider than a phone.
- **What a chip reads.** A position: pair, then `LONG` or `SHORT`, or "side not readable" when
  the side is null, then the origin. An order: pair, "order in flight", the origin. Whether an
  order opens or closes is on its line on the detail page, not on the chip.
- **The venue chip** follows its position's chip, and after it comes the link "See the pending
  decision" or the words "No booking is proposed for it." in `text-ink-2`, 12 px. The three wrap
  together as one group (example 7).
- **Dashed means an order in flight and nothing else.** No other element of these components uses
  `border-dashed`.
- **Red means "needs the owner" and nothing else**: a position of both origins, the venue
  disagreeing, a read that failed. Always with its words.
- **Cyan is the origin "Live"**, the colour of the "Live" badge. `LONG` and `SHORT` stay in ink:
  `gain` and `loss` mean a result elsewhere on this panel, and a side is not one.
- **Only palette tokens**, from `frontend/src/index.css` `@theme`: `panel-2`, `rule`,
  `rule-strong`, `ink`, `ink-2`, `ink-3`, `gain`, `loss`, `decision`. No hex and no `var()` in a
  class: `shared/theme.test.ts` already refuses both in every source file (P35), so the new files
  are covered the day they exist. The prototype's own style sheet uses `var()` because it is one
  HTML file with no build; its header maps each of its names to the Tailwind token.
- **Amber, and the test that guards it.** `panel-tokens.test.ts` asserts that the files using a
  `decision` class are exactly its list `AMBER_ALLOWED`, and its comment says why each one is
  there (P31). The marks add one user, and only one: `features/positions/origin.ts`, the table
  that maps the origin "Dry run" to `text-decision` and `border-decision`. `Mark`, `MarkLine` and
  `OriginTag` take their classes from that table and write no `decision` class themselves, not
  even in a comment (the test reads each file's whole text), and no other positions file may. The origin's tag is amber for the reason decision 43's tag is: the
  words and the colour of the mode badge. So op.2 has a step BEFORE `origin.ts` is written: add
  `features/positions/origin.ts` to `AMBER_ALLOWED`, in its sorted place, and extend the comment
  with decision 65. That step is red on its assertion (the list names a file that does not use
  amber yet) and goes green when `origin.ts` exists, the way task 13.4.3 added
  `ExchangeKeyCard.tsx` (§ L, T21). The first block of the same test stays as it is:
  `MonthlySummary`, `PoolPanel` and `OverviewPage` are on its never-amber list, and op.4 puts no
  `decision` class in them, since the Overview's origin tags come from `origin.ts` too.

**One component for the two lines.** The prototype draws the line of an order in flight and the
line of the venue mark from one base class and two modifiers, so that the two cannot drift apart.
`MarkLine` is that base, written once: the full width of its container, wrapping, 8 px by 12 px
of padding, a 6 px radius, a 1 px border, a transparent fill, mono, 12 px, left-aligned,
`text-ink`, the ` · ` separator in `text-ink-3`. It has exactly two variants.

| Line | Border | Its parts, in order, separated by ` · ` |
| --- | --- | --- |
| `OrderLine` (example 19) | `border-dashed`, in the origin's colour as on a chip | the pair; "order in flight"; "opening" or "closing", left out when `action` is null; the origin's word in its token; "sent {time} UTC", left out when `submitted_at` is null |
| `VenueLine` (examples 18, 24, 25e) | solid, `border-loss` | the pair; "venue disagrees" in `text-loss`; "exchange {x}, ledger {y}"; "last compared {time} UTC"; "shared by N positions on this pair", only when `allocation_count` is above one; then the link "See the pending decision", or the words "no booking is proposed" |

- `{x}` and `{y}` are the two nets as stored, each followed by the position's base currency when
  it has one (`exchange 0 AAVE, ledger 0.82 AAVE`).
- The venue line is a `role="group"` named "Venue disagrees, {pair}", and its link is a real link
  named "See the pending decision, {pair}".
- Its last part follows § E: the link when a pending proposal names this allocation and this
  discrepancy, the words when the proposals were read and none does, and neither while the
  proposals are loading or their read failed.
- The chip-sized venue mark of the strategies list is a `Mark`, not a `MarkLine`, and is
  unchanged by the owner's second review.

**The detail section: `OpenPositionsSection`** (examples 13 to 21, 25d, 25e, 26b). Heading "Open
positions". It selects `ofStrategy(state, strategy.id)` over the whole answer.

| Column | What the cell holds |
| --- | --- |
| Opened (UTC) | the date and, under it in `text-ink-3`, the time: the trades table's `Instant` |
| Pair | the market keys, in `text-ink`; under them the origin's word in its token, 11 px, sans, as the trades table tags a rehearsal row (`TradesTable.tsx:100-104`) |
| Side | `LONG` or `SHORT`; a dash with "figures not readable" for a screen reader when it is null |
| Size | the size and its base currency as a unit (sans, 11 px, `text-ink-3`); under it "of {opened} opened" when `opened_size` differs from `size` |
| Entry | the price; under it "average of N fills" when `fill_count` is above one |
| Fees {currency} | the fees, and each fee in another currency beside them, as the trades table writes them |
| Margin granted {currency} | the margin |
| Leverage | `figureText(leverage)` followed by `x`: the route serves `2.00000000` and the cell reads `2x` (P32). A dash with "not recorded" for a screen reader when it is null, never "1x" |

- **From `md` a table, below it one card per position** (example 20): the pair and the side in
  the card's head with the origin's word at its right, then the same six labels and values in two
  columns. A card is an `article` named by its pair and side.
- **A null is a dash with its reason, in every cell and in every card** (corrected after
  validation). `PositionsTable` writes each cell through the shared `Absent` when its value is
  null, as the trades table does (`TradesTable.tsx:51-58, 89-90`), and never passes a null on.
  `Instant` takes a string and cannot take a null, so the Opened cell is `Absent` or `Instant`,
  one or the other. The reason read by a screen reader is "figures not readable" for the side,
  the size and the entry of any position whose figures are missing, and for EVERY empty cell of a
  `NO_FACTS` position: Opened, Side, Size, Entry, Fees, Margin granted and Leverage. "not
  recorded" is kept for the one case it is true of, a position that has its facts and no
  leverage. A `NO_FACTS` position has no strategy id, so it never reaches a detail page: its row
  is drawn by the Overview's list and its cards, which have no Fees column, so six dashes are
  seen there, beside the strategy's name, the pair and the origin. The TypeScript
  type says the same as § F: `opened_at`, `fees`, `margin_granted` and `leverage` are `string |
  null`, and the shape check accepts a null there and refuses a missing field.
- **Sub-rows**, each a row of one cell across the eight columns, directly under its position's
  row and in this order: the venue line; the reason the figures are missing, in sans, 12 px,
  `text-ink-2` (example 17); the reservation's note when its status is not `FILLED`. In a card
  they are the card's last elements, in the same order (example 24 draws the venue line there).
- **The orders** of the strategy are `OrderLine`s in a list under the table, or under "No open
  position." when it holds no position (example 19b).
- **The notes** come last, each drawn only when a row on screen makes it true, in this order: the
  dry-run note, the note of a position of both origins, the margin note (examples 15, 17, 19a).
  The margin note is true of any position. Examples 18b and 18c leave it out; that is the
  picture's shorthand, not a rule.
- **Unmatched elements.** While `unmatched(ofExchange(state, strategy.exchange))` is not empty,
  the section says "N open positions or orders could not be matched to a strategy. The Strategies
  page names them." (corrected 2026-10-13: the count adds orders to positions): in place of "No open position." when the strategy has no position of its own
  (example 26b), and above the notes otherwise. See "A row with no strategy id" below for why the
  strategy's exchange bounds it.
- **Figures.** Prices and sizes are written by `tableFigureText`, the two nets by `figureText`,
  fees and margin by `amountText`: the helpers of the closed trades table, which sits right under
  this section, so one page writes a figure one way. Two consequences, decided in § O, Q9 on
  2026-10-13: in
  Spanish a price reads `184.3`, with a point, where example 25 draws a comma (P30); and a margin
  reads `121.80`, with the currency's decimals, where some of the prototype's samples read
  `121.8`. The prototype's numbers are samples (its review bar says so), not a format.

**The Overview part: `PoolOpenPositions` and the count** (examples 22 to 24). It ships with the
rest.

- **The list.** `ofPool(state, pool)`, under the month grid and its summary. The same
  `PositionsTable` in its pool variant: the strategy's name is the first column, a link to the
  strategy's page, or plain text when the position has no strategy id; there is no Fees column.
  Eight columns, as drawn: Strategy, Opened (UTC), Pair, Side, Size, Entry, Margin granted,
  Leverage. Below `md` it is cards, the strategy's name under the card's head. The sub-rows are
  the table's own, so a position the venue disagrees on carries its line here too (example 24).
- **No notes** under the Overview's list, as drawn.
- **It does not depend on the pool's performance report.** `PoolPanel` draws the month grid and
  its summary only when a report exists. The list is placed after that block and outside its
  condition: a pool whose report is missing or failed can still hold a position.
- **Its states** are not drawn in the prototype and are the detail section's, with the same
  texts: "Reading open positions…", the error sentence with "Read again", "No open position.". The
  heading is always drawn. This matters for the count: an absent count means "nothing open" (example
  23c), and a failed read also leaves it absent, so the error sentence right under it is what
  keeps that from being read as zero.
- **Orders in flight are not drawn on the Overview.** The first writing listed them there. The
  prototype draws none, the owner's words for this part are "every open position", and the
  approved order line has no place for a strategy's name, which a line on the Overview would
  need. They stay on the Strategies page and on the detail page; the owner confirmed this on
  2026-10-13 (§ O, Q8).

**The Overview's count.** `MonthlySummary` gains an optional prop, `open`, and has two callers
(P27).

| `open` | Who passes it | What the summary writes |
| --- | --- | --- |
| absent | the strategy detail page, unchanged | today's part, "N open trades not in the curve", from `excluded.open_trade_count` |
| null | the Overview, while the read is loading or failed | no part about open positions, old or new |
| `{total, rehearsal}` | the Overview, from `ofPool`'s positions | nothing when `total` is zero; "N open" when `rehearsal` is zero; "1 open, dry run" for exactly one position that is a dry run; otherwise "N open, M of them dry run" |

`rehearsal` counts the positions whose origin is `rehearsal`. A position of both origins is in
`total` and not in `rehearsal`; its row says what it is. The part sits where today's sits, after
the worst month. On the Overview the live-only sentence is no longer drawn;
`excluded.open_trade_count` stays in the API, true as "what the curve leaves out". The detail
page's sentence is not touched: decision 65 speaks of the Overview's count, nobody had seen that
the detail page writes one too, and the owner chose on 2026-10-13 to keep it live-only (§ O, Q6).

**The count needs the pool's report; the list does not** (corrected after validation).
`MonthlySummary` is drawn only inside `report !== null` (`PoolPanel.tsx:143-148`), and the count
is a part of that line. So a pool that holds a position and has no report, or whose report
failed, shows the list with its rows and NO count. That is accepted and said here: the count is
a part of the month's summary, which does not exist without a report, and the list under it is
the complete statement. The count is not moved out of the summary to cover the case; that would
be a layout the owner has not seen.

**The "Live" badge** (owner, 2026-10-12). In `DryRunBadge.tsx` the last branch becomes
`"border-gain text-gain"`, and the comment's line for `dry_run: false` says that "Live" is drawn
in `gain`, the colour the marks give the origin "Live", and that the badge states the mode and is
not an alarm. Nothing else of the component changes: the neutral states stay neutral, so a failed
or pending read still cannot be read as either mode. The comment beside `--color-gain` in
`index.css` gains "the Live mode"; the token's value does not change. In Spanish the badge reads
"Modo simulación" (`status.dryRun`) where a mark reads "Simulación", the trades table's word;
both exist today and neither changes.

**The rail.** `DecisionRail`'s `aside` gains `id="decision-rail"`. The marks link to
`{ pathname: "/", hash: "#decision-rail" }`. The router does nothing with a hash (P29), so the
rail reads the location and, when the hash is its id, scrolls itself into view once it is
mounted, and again when the hash changes while it is on screen. The link is drawn from op.2 on
(the list's venue chip has it), so the rail's change belongs to op.2.

**Times.** Three kinds, each with `UTC` written after it.

| Time | Written as | Helper |
| --- | --- | --- |
| "Last read", "could not be refreshed since", "last compared" | hours, minutes and seconds | `clockSecondsText`, new, beside `clockText` |
| "sent" | hours and minutes | `clockText` |
| "Opened" | the date and the time on two lines | `Instant` |

A time that is not on the UTC day of the answer's `as_of` is written with its date before it, by
`compactDateText`. The prototype draws no such case, and without the date it would be the silent
one: an order sent yesterday at 21:12 would read as sent minutes ago, and a venue mark frozen
since the mode was changed would read as compared today (§ E; § K, row 20).

**The formatting helpers move to `shared/`, in a commit of their own.** `amountText` and
`parseDecimal` live in `features/overview/format.ts`; `figureText`, `tableFigureText`,
`compactDateText`, `clockText` and `dateTimeText` live in `features/strategies/format.ts`; `Absent`
and `Instant` are local to `TradesTable.tsx` (lines 51-73). A new `features/positions` would import
from two other features, and the Overview part would make `features/overview` import it back.
These helpers are shared in fact already: fifteen files hold eighteen imports of the two format
modules, and `features/strategies` reads `features/overview/format` (`StrategyRow.tsx:4`). So the two format
files move whole to `shared/lib/`, with their tests, and the two cells to `shared/ui/`, as unit
13.0 moved three shared idioms for Settings: import paths only, no assertion changed, one commit
that opens op.2. Importing them where they are was the alternative, and was not taken: it would
add a third feature to a dependency that is already crossed. The move adds no helper:
`clockSecondsText` and the rule for a time of another day are written afterwards, with their
tests, in op.2 proper.

**The two files' new names** (answered by the orchestrator, 2026-10-13). They cannot both be
`shared/lib/format.ts`, and the folder's files are named kebab-case by what they hold (`day-text.ts`,
`clipboard.ts`, `cn.ts`). `features/overview/format.ts` (`amountDecimals`, `parseDecimal`,
`amountText`, `percentText`, `toneClass`: money, percentages and their tone) becomes
`frontend/src/shared/lib/amount-text.ts`. `features/strategies/format.ts` (`figureText`,
`tableFigureText`, `rateText`, `cutAmountText`, `compactDateText`, `clockText`, `dateTimeText`:
the trades table's figures, rates, dates and times) becomes `frontend/src/shared/lib/figure-text.ts`.
The move stays mechanical: `git mv`, imports updated, no behaviour change. The strategies file
has a test, `features/strategies/format.test.ts`, which moves with it to
`frontend/src/shared/lib/figure-text.test.ts`. The overview file has NO test file, and the move
adds none.

**Why each token**, for the marks' table above.

| What | Token | Why |
| --- | --- | --- |
| Origin "Dry run" | `decision` | the mode badge's and the trades table's (P19) |
| Origin "Live" | `gain` | owner, 2026-10-12: the colour of the "Live" badge, which takes it in this delivery. The first writing drew it in `ink-2`; the owner asked that the badge and the marks agree and preferred cyan to red |
| Origin "Dry run and live" | `loss` | it needs the owner: neither mode can close it |
| Origin "origin unknown" | `ink-3`, with a `rule-strong` border | nothing is claimed |
| Venue disagrees | `loss` border and text | it needs the owner: the position may no longer exist |
| LONG, SHORT | `ink` | `gain` and `loss` mean PnL on this panel, and there is none here |
| Figures | `ink-2`, mono, tabular | as the trades table |

**Every state.**

| State | `OpenStateLine` (Strategies) | `OpenMarks` (a row) | `OpenPositionsSection` (detail) | `PoolOpenPositions` and the count (Overview) |
| --- | --- | --- | --- | --- |
| The scope is loading or failed, or no exchange exists | not drawn; the page's own text says why | no row | the section does not wait for the scope: it selects by strategy id | no panel (`OverviewPage.tsx:41-44`) |
| Loading, nothing read yet | "Reading open positions…", `role="status"`, `text-ink-3`, no button | a decorative "…" with `aria-hidden`, and the translated `positions.state.loading` as its `sr-only` name; the row's figures already draw the same literal while they load (`StrategyRow.tsx:65`) | "Reading open positions…" | the same text under the heading; no count |
| Failed, nothing read yet. It follows about 7 s of the loading state: the app's query client keeps TanStack's default of three retries (P34) | the error sentence, `role="alert"`, `text-loss`, and "Read again" | nothing, and the line above says why a row without a mark means nothing | the error sentence and "Read again" | the error sentence and "Read again"; no count |
| Read, then a refresh failed | the last figures and "Could not be refreshed since {time} UTC." in `text-loss` | the last answer | the last answer and the same sentence | the last answer and the same sentence |
| Nothing open on the selected exchange | `Open: 0 · Orders in flight: 0 · Last read: {time} UTC` | nothing | "No open position." | "No open position."; no count |
| One live | `Open: 1` | `AAVEUSDT · LONG · Live`, cyan | one row, every figure, the margin note | one row; "1 open" |
| One rehearsal | `Open: 1` | `SFPUSDT · SHORT · Dry run`, amber | one row, 1x, the dry-run note | one row; "1 open, dry run" (corrected 2026-10-13) |
| Both origins | `Open: 1` | `STXUSDT · LONG · Dry run and live`, red | one row and its note | one row; counted in N, not in M |
| Unresolved symbol | `Open: 1` | `XYZBTC · side not readable · Live` | one row, the side, size and entry as dashes, the reason under it | the same row |
| Order in flight | `Orders in flight: 1` | `SFPUSDT · order in flight · Live`, dashed and unfilled | a dashed line under the table, with its time | not drawn (§ O, Q8) |
| The venue disagrees | counted as any position | the position's chip, the red chip, then the link or "No booking is proposed for it." | the red line under the position's row | the same line, under the row or in the card |
| A disabled strategy holding one | counted | the chip, in a row whose switch is off | as any other | as any other |
| Several positions on one strategy | `Open: 3` | the chips wrap in their own grid row; the figures and the switch do not move | several rows | several rows |
| An archived strategy's, while archived ones are hidden | counted, and named under the figures with "archived" | no row to sit on | its own page shows it | listed in its pool |
| A position or an order with no strategy id (§ C: the facts could not decorate it) | counted on the tab of its own exchange, and named there: the strategy's name, the pair, the origin and, for a position, "figures not readable" | it cannot be placed on a row | "N open positions or orders could not be matched to a strategy", on the pages of that exchange's strategies; "No open position." is never drawn while one exists | a position is listed in its pool, its strategy's name as plain text and its six empty cells as dashes |
| An element of another exchange | nothing: not counted, not named | nothing | - | nothing |
| An element whose exchange has no tab, WITH a strategy id | on no tab (§ O, Q7, answered 2026-10-13) | nothing | shown on its strategy's page, which selects by id | nothing. Logged by the read at WARNING, at every request (§ C) |
| An element whose exchange has no tab, with NO strategy id (a `NO_FACTS` position, an undecorated order) | on no tab | nothing | on no strategy's page: the unmatched sentence counts only the strategy's own exchange | nothing. **The panel shows it NOWHERE, by the owner's decision of 2026-10-13.** Logged at WARNING at every request (§ K, rows 10, 16 and 25), which reaches no alert. § O, Q7 |
| An element whose exchange HAS a tab and whose pool is not one of `GET /pools`' pools | counted on its exchange's tab, and drawn on its strategy's row or named under the figures, like any other | its chip, on its strategy's row | shown on its strategy's page | **in no pool's list and in no count**: `ofPool` matches three values and no panel has them. Logged at WARNING (§ K, row 26) |
| A pool that holds a position and has no performance report | counted and drawn as any other | as any other | as any other | the list with its rows; NO count, since the summary line is not drawn without a report |
| The strategies list is still loading | the figures; the second line is withheld | no row yet | - | - |
| The strategies list failed | the figures, and every element of the exchange named under them | no row | - | - |
| Phone width | the figures wrap and lose their separators; the button is 44 px tall | the chips are the row's last line | cards, one per position | cards, the strategy's name under each head |

**What the scope change does to the rules of the first writing.** Each rule is stated as it is
true now, with what it replaces.

- **The rule that makes the list page complete is now a rule per exchange.** It was: every
  element of the answer is drawn in a row on screen or named in the page's sentence, so the page
  shows nothing open only when the answer is empty. It is: every element of the SELECTED
  exchange is drawn in a row on screen or named under the figures, so a tab reads zero and zero
  only when the answer holds nothing of that exchange. An element of another exchange is neither
  drawn nor named nor counted. Three kinds are still named rather than drawn: a position or an
  order of an archived strategy while archived ones are hidden, one with no strategy id, and any
  element of the exchange when the strategies list failed to load.
- **A row with no strategy id is named on the tab of its own exchange, and only there.** It was
  named on every exchange's view. A `NO_FACTS` position and an undecorated order (§ C) carry no
  strategy id, but each carries its pool: the guard's element has it (`mode_origin.py:59-81`), and
  the body always serves it (§ F). So `ofExchange` places it like any other element, and
  `notShown` then names it, since a null id is never on screen. Which exchange names it is
  therefore decided by the read model, from the guard's own label, and not by the panel. A name
  is still not matched to a row: names are unique in the table
  (`strategies/infrastructure/models.py:44`), but the strategies list and this answer are two
  reads of two instants, and a row is keyed by its id.
- **When an element's exchange cannot be told.** It always can, as a string: the columns are
  `NOT NULL` (P25) and the shape check refuses an answer without it. What can happen is a string
  that is no tab. That element is then on NO tab: by the owner's rule it is "another exchange"
  for every tab, and there is no tab to move to. This design does not decide that it should be
  shown, because showing it means writing about an exchange other than the selected one, which is
  what the owner asked not to read (§ O, Q7). What it does decide: such an element can only be
  one of the four cases of § C, each of which the read logs at every request; and its strategy's
  detail page shows it when it has a strategy id, because that page selects by id. **What that
  leaves, said plainly:** when it has NO strategy id (a `NO_FACTS` position, an undecorated
  order), no page of the panel shows it at all. Its only trace is a
  WARNING a minute, and § K's own rule is that a read model never logs ERROR, so no alert
  carries it. Money is not at risk, since the worker's guard reads the same element and refuses
  the start; the panel is silent. The validation recommended closing that with a count-only line
  (§ N); the owner declined it on 2026-10-13 (§ O, Q7), so the silence stands as decided.
- **A pool that is no pool of the exchange.** A second case of the same family, with a tab: an
  element whose exchange has a tab and whose three-value pool is not among `GET /pools`' pools.
  The Strategies page and the detail page show it, because they do not select by pool. The
  Overview does not: `ofPool` matches three values and no panel has them, so it is in no list
  and in no count. It is logged by § C's check, since its pool cannot be its reservation's
  (§ K, row 26).
- **What the strategy detail page says when the answer holds an unmatched element.** It was:
  while the answer holds one, no strategy's section says "No open position.". It is: while the
  STRATEGY'S OWN EXCHANGE holds one. An unmatched element of another exchange cannot be this
  strategy's in any stored data that is not at fault (a strategy's exchange never changes, P24),
  and the sentence "The Strategies page names it" is true only on that exchange's tab, which is
  the tab the detail page selects. The count is of unmatched positions and orders together; the
  approved sentence says "position" for both.
- **What the owner read before a mode change, and no longer reads.** The first writing said that
  the sentence "Nothing is open on any exchange" is the one the owner reads before changing
  `DRY_RUN`. That reading no longer exists on one screen. Before a mode change the owner looks at
  each exchange's tab (decision 65, 2026-10-12). What protects the change is the guard, and § B
  gives the evidence: the worker does not start in a mode that cannot close what the ledger
  holds, on any exchange, enabled pool or not, archived strategy or not.
- **Disabled is not hidden.** `OpenMarks` does not read `strategy.enabled`.
- **Accessibility.** Each mark is text, not colour or shape alone: the origin is a word, and so
  are "order in flight" and "venue disagrees". The venue mark's link is a real link with the pair
  in its name. The dashes carry their reason in `sr-only` text, as in the trades table. The list
  of a row's marks is named "Open positions of {name}". The figures' live region is described
  above.
- **The Overview part is part of the delivery.** It was separable. `PoolOpenPositions`, the
  count's prop and `ofPool` are ordinary parts of op.4, which ships with the rest (§ M).

### I. Texts and i18n keys (approved with the prototype, 2026-10-12)

These are the texts. The owner approved the prototype as drawn, its Spanish included (decision 65,
2026-10-12), so every English text below is the prototype's, letter for letter, and so is every
Spanish text that example 25 draws. The last column names the examples that draw each text, the
English ones first and the Spanish ones after the semicolon; a dash means that the prototype does
not draw the text in that language. The notes under the tables say what that leaves.

A `positions.*` group holds what the three places share; the Overview keeps its two texts in its
own group.

**The summary above the strategies list, and the states.**

| Key | English | Spanish | Drawn in |
| --- | --- | --- | --- |
| `positions.state.figures.open` | Open | Abiertas | 1 to 12, 26a; 25a to 25c |
| `positions.state.figures.orders` | Orders in flight | Órdenes en curso | 1 to 12, 26a; 25a to 25c |
| `positions.state.figures.lastRead` | Last read | Última lectura | 1 to 12, 26a; 25a to 25c |
| `positions.state.figures.time` | {{time}} UTC | {{time}} UTC | the same |
| `positions.state.notShown` | Not on this list: {{items}}. | Fuera de esta lista: {{items}}. | 10, 12d, 26a; 25c |
| `positions.state.archived` | archived | archivada | 10, 12d; 25c |
| `positions.state.unreadable` | figures not readable | cifras no legibles | 10, 17, 26a; 25c |
| `positions.state.refresh` | Read again | Leer de nuevo | 1 to 12, 21; 25a to 25c |
| `positions.state.loading` | Reading open positions… | Leyendo posiciones abiertas… | 11a, 21; - |
| `positions.state.error` | Open positions could not be read. A row without a mark does not mean that nothing is open. | No se pudieron leer las posiciones abiertas. Una fila sin marca no significa que no haya nada abierto. | 11b, 21; - |
| `positions.state.stale` | Could not be refreshed since {{time}} UTC. | No se pudo actualizar desde las {{time}} UTC. | 11c, 11d; - |

The colon after a label and the ` · ` between two figures are punctuation written by the
component, the same in both languages, as the summary under the month grid already joins its parts
(`MonthlySummary.tsx:53`). So are the ` · ` between the parts of a mark, of a line and of an item,
and the `; ` between two items.

**The marks, the order line and the venue mark.**

| Key | English | Spanish | Drawn in |
| --- | --- | --- | --- |
| `positions.marks.name` | Open positions of {{name}} | Posiciones abiertas de {{name}} | 2 to 10, as the accessible name of a row's marks; - |
| `positions.origin.rehearsal` | Dry run | Simulación | 3, 15, 19, 22; 25a |
| `positions.origin.live` | Live | En vivo | 2, 14, 22; 25b, 25d |
| `positions.origin.mixed` | Dry run and live | Simulación y en vivo | 4, 17; - |
| `positions.origin.unknown` | origin unknown | origen desconocido | 6; - |
| `positions.sideUnreadable` | side not readable | lado no legible | 5; - |
| `positions.order.inFlight` | order in flight | orden en curso | 6, 10, 19; 25c |
| `positions.order.open` / `.close` | opening / closing | apertura / cierre | 19; - |
| `positions.order.sent` | sent {{time}} UTC | enviada {{time}} UTC | 19; - |
| `positions.venue.disagrees` | Venue disagrees | El exchange no coincide | 7, 12b, the key; 25b |
| `positions.venue.noProposal` | No booking is proposed for it. | No hay un registro propuesto para esta diferencia. | 7, 12b; 25b |
| `positions.venue.link` | See the pending decision | Ver la decisión pendiente | 7, 18a, 18c, 24; 25b, 25e |
| `positions.venue.linkName` | See the pending decision, {{pair}} | Ver la decisión pendiente, {{pair}} | the same, as the link's accessible name |
| `positions.venue.groupName` | Venue disagrees, {{pair}} | El exchange no coincide, {{pair}} | 18, 24, as the line's accessible name; 25e |
| `positions.venue.line.disagrees` | venue disagrees | el exchange no coincide | 18, 24; 25e |
| `positions.venue.line.nets` | exchange {{venue}}, ledger {{ledger}} | exchange {{venue}}, libro mayor {{ledger}} | 18, 24; 25e |
| `positions.venue.line.compared` | last compared {{time}} UTC | última comparación {{time}} UTC | 18, 24; 25e |
| `positions.venue.line.shared` | shared by {{positions}} positions on this pair | compartida por {{positions}} posiciones en este par | 18c; 25e |
| `positions.venue.line.noProposal` | no booking is proposed | no hay un registro propuesto para esta diferencia | 18b; 25e |

The chip and the line say the same thing in two cases of the first letter and with or without a
full stop, as drawn: a chip is a label and its follow-up a sentence; a line is one run of parts.
So they are two sets of keys, not one transformed in code. `positions.venue.line.shared` is drawn
only above one, has no singular, and its variable is not named `count`, so i18next resolves no
plural for it.

**The table, its cells and its notes.**

| Key | English | Spanish | Drawn in |
| --- | --- | --- | --- |
| `positions.table.title` | Open positions | Posiciones abiertas | 13 to 24; 25d, 25e |
| `positions.table.empty` | No open position. | Sin posiciones abiertas. | 13, 19b; - |
| `positions.table.margin` | Margin granted {{currency}} | Margen otorgado {{currency}} | 14 to 20, 22, 24; 25d, 25e |
| `positions.table.leverage` | Leverage | Apalancamiento | 14 to 20, 22, 24; 25d, 25e |
| `positions.table.leverageValue` | {{value}}x | {{value}}x | the same |
| `positions.table.notRecorded` | not recorded | no registrado | 15, for a screen reader; - |
| `positions.table.ofOpened` | of {{opened}} opened | de {{opened}} abiertas | 16; - |
| `positions.table.averageOf` | average of {{fills}} fills | promedio de {{fills}} ejecuciones | 16; - |
| `positions.table.unmatched_one` / `_other` | {{count}} open position or order could not be matched to a strategy. The Strategies page names it. / {{count}} open positions or orders could not be matched to a strategy. The Strategies page names them. | {{count}} posición u orden abierta no se pudo asociar a una estrategia. La página Estrategias la nombra. / {{count}} posiciones u órdenes abiertas no se pudieron asociar a una estrategia. La página Estrategias las nombra. (Corrected 2026-10-13: the count adds orders to positions, so the words say both.) | 26b; - |
| `positions.reason.UNRESOLVED_SYMBOL` | The pair's base currency cannot be told from the pool's currency, so the side and the size are not derived. | La moneda base del par no se puede determinar a partir de la moneda del pool, por lo que el lado y el tamaño no se calculan. | 17; - |
| `positions.reason.SEVERAL_MARKETS` | The fills of this position name more than one pair. | Las ejecuciones de esta posición nombran más de un par. | -; - |
| `positions.reason.FLIPPED` | The fills sold more than was bought, or bought more than was sold. The entry price is not derived. | Las ejecuciones vendieron más de lo comprado, o compraron más de lo vendido. El precio de entrada no se calcula. | -; - |
| `positions.reason.other` | The figures could not be derived from the fills. | Las cifras no se pudieron calcular a partir de las ejecuciones. | -; - |
| `positions.note.margin` | Margin granted is what the share took from the pool when the position opened. It is not what the exchange holds now. | El margen otorgado es lo que la participación tomó del pool al abrir la posición. No es lo que el exchange retiene ahora. | 14 to 17, 18a, 19a, 20; 25d |
| `positions.note.rehearsal` | A dry-run position was filled by the simulated exchange, at 1x. It is not at the exchange and enters no total. | Una posición de simulación fue ejecutada por el exchange simulado, a 1x. No está en el exchange real y no entra en ningún total. | 15, 19a; - |
| `positions.note.mixed` | This position holds dry-run and live fills. Neither mode can close it safely: check it against the exchange by hand. | Esta posición tiene ejecuciones de simulación y en vivo. Ningún modo puede cerrarla con seguridad: verifíquela a mano contra el exchange. | 17; - |
| `positions.note.reservation` | Its reservation reads {{status}}, not FILLED. | Su reserva figura como {{status}}, no FILLED. | -; - |

**The Overview's own texts.**

| Key | English | Spanish | Drawn in |
| --- | --- | --- | --- |
| `overview.open.strategy` | Strategy | Estrategia | 22; - |
| `overview.monthlySummary.openAll_one` / `_other` | {{count}} open / {{count}} open | {{count}} abierta / {{count}} abiertas | 23a; - |
| `overview.monthlySummary.openWithRehearsal_one` / `_other` | {{count}} open, dry run / {{count}} open, {{rehearsal}} of them dry run | {{count}} abierta, en simulación / {{count}} abiertas, {{rehearsal}} de ellas en simulación | 22, 23b, 24; - |

Corrected after the final review, 2026-10-13, with the owner's agreement: `openWithRehearsal` has
the two plural forms, with `count` set to the total and `rehearsal` kept as a variable, so that
exactly one open position that is a dry run reads "1 open, dry run" / "1 abierta, en simulación".
Two or more read as approved. (The first writing named the variable `total` and had no suffixed
forms, which wrote "1 abiertas" in Spanish.) `openAll` keeps `count` and has both of its forms.

**Existing keys the prototype draws, reused and not changed.** Each was read in both locale files
on 2026-10-12 and matches the picture.

| What is drawn | Keys | English | Spanish |
| --- | --- | --- | --- |
| The Overview list's and the detail table's column headings (14 to 24; 25d, 25e) | `strategies.performance.trades.opened`, `.pair`, `.side`, `.size`, `.entry`, `.fees` | Opened (UTC), Pair, Side, Size, Entry, Fees {{currency}} | Apertura (UTC), Par, Sentido, Tamaño, Entrada, Comisiones {{currency}} |
| The side | `strategies.performance.trades.direction.LONG`, `.SHORT` | LONG, SHORT | LONG, SHORT |
| A fee in another currency | `strategies.performance.trades.otherFee` | + {{amount}} {{currency}} | + {{amount}} {{currency}} |
| The rail of example 24: its title, its count, its explainer | `overview.decisionRail.title`, `.pending_one` / `_other`, `.explainer` | Needs your decision; {{count}} pending; Closes the venue made that the ledger has not recorded. Approving writes them to the ledger for good. | Requiere su decisión; {{count}} pendiente / pendientes; Cierres que hizo el exchange y que el libro mayor todavía no registró. Aprobarlos los escribe en el libro mayor de forma definitiva. |
| The rail's card of example 24 | `bookings.card.side`, `.quantity`, `.observedVenueNet`, `.observedLedgerNet` | Side, Quantity, Venue net, Ledger net | not re-read |
| The badge of the top bar | `status.live`, `status.dryRun` | Live, Dry run | En vivo, Modo simulación |

- **The Overview list's column headings** are the first row of this table plus
  `overview.open.strategy`, `positions.table.margin` and `positions.table.leverage`. It has no
  Fees column.
- **The rail's card is `BookingCard`, unchanged.** Example 24 draws four of its fields. The real
  card also writes when the proposal expires, the strategy's id, the allocation's id and each
  fill, and has its two buttons, "Reject" and "Approve" (`BookingCard.tsx:21-59`;
  `BookingsListView.tsx:76-91`). The picture is a shortened drawing of it, not a new card: this
  delivery changes the rail's `id` and its scroll, and nothing of the card.
- **The units next to a size or a net** (`0.82 AAVE`) are the position's base currency, not a
  text.
- **A card's accessible name** is the pair and the side (`AAVEUSDT LONG`), composed in the
  component as `PoolPanel` composes its own (`PoolPanel.tsx:128`), not a key.

**Keys of the first writing that no longer exist.** None was ever added to a locale file.

| Key | Why |
| --- | --- |
| `positions.state.none`, `positions.state.some` | the summary is three figures, not a sentence, and names no exchange |
| `positions.state.positions_one` / `_other`, `positions.state.orders_one` / `_other` | they were the two halves of the sentence; a figure is a number beside a label |
| `positions.venue.detail`, `positions.venue.shared` | the venue mark of the detail page is one line of parts, not stacked sentences; `positions.venue.line.*` replaces them |

`overview.monthlySummary.open_one` / `_other` ("N open trades not in the curve") is NOT removed:
the strategy detail page still writes it, by the owner's decision of 2026-10-13 (§ H; § O, Q6).

**What the last column leaves, said plainly.**

- **Spanish that the prototype does not draw.** Every row whose last column ends in a dash. Their
  Spanish is the first writing's, the same table example 25 was drawn from, with one new text:
  "Posiciones abiertas de {{name}}", the accessible name of a row's marks, which example 25 has no
  attribute for. The owner's "the Spanish is fine" was said of what example 25 draws.
- **English that the prototype does not draw**: three of the four reasons and the reservation's
  note. They are the first writing's.
- **One oddity in the count (corrected 2026-10-13).** With one open position that is a dry run, the
  approved form read "1 open, 1 of them dry run" and "1 abiertas, 1 de ellas en simulación". The
  prototype draws it for two and for three. The owner has since agreed to the singular form, and
  `openWithRehearsal` has `_one` and `_other` forms: "1 open, dry run" and "1 abierta, en
  simulación" for exactly one, the approved text for two or more (§ N).
- **Numbers are not texts.** The prototype's Spanish draws every number with a decimal comma. The
  panel's helpers do not all do that (P30; § H). Prices and sizes of open positions are written with
  a point in Spanish, by the owner's decision of 2026-10-13 (§ O, Q9).
- **One text that is NOT a key.** "{N} open items are on no exchange tab" was the alternative Q7
  offered the owner (§ O). The owner declined it on 2026-10-13: it is in no table above, has no
  Spanish, and is written into no locale file.

A note is drawn only when a row on screen makes it true, as the trades table's notes are. No text
of this section says that nothing is open anywhere, and none is worded as a permission to change
the mode (§ B).

### J. The visual prototype, as approved

One file, `openspec/changes/operator-panel/visual/project/OpenPositions.html`, at commit
`6603dea`, approved by the owner on 2026-10-12 ("Está muy bien. Queda así"). It is the visual
reference for the implementation, its Spanish included. It is not product code: one HTML file, no
script, no network, every example a still picture. Nobody edits it from here on; a later change
to what it draws is a new decision.

**What the page holds, in its own order.**

1. **The review bar**, which is not part of the product: a note on what the page is, the key
   "Reading the marks", and the list of examples.
2. **Group A, the Strategies page**: examples 1 to 12.
3. **Group B, the strategy detail page**: examples 13 to 21.
4. **Group C, Spanish and the unmatched position**: examples 25 and 26.
5. **Group D, the Overview**: examples 22 to 24. They are drawn last, after 25 and 26, and keep
   their numbers.

**The key, "Reading the marks".** Seven sample marks, each with one line of explanation, and the
rule under them. It is where the marks' rule of § H can be checked at a glance.

| Sample | What the key says of it |
| --- | --- |
| `AAVEUSDT · LONG · Dry run` | a position opened in dry run: filled, solid amber border, amber word |
| `AAVEUSDT · LONG · Live` | a position opened live: filled, solid cyan border, cyan word |
| `AAVEUSDT · LONG · Dry run and live` | a position holding fills of both origins: red, because neither mode can close it |
| `AAVEUSDT · LONG · origin unknown` | origin not known: grey border and grey words, solid on a position |
| `AAVEUSDT · order in flight · Dry run` | an order in flight, dry run: unfilled, dashed amber border |
| `AAVEUSDT · order in flight · Live` | an order in flight, live: unfilled, dashed cyan border |
| `Venue disagrees` | the exchange disagrees with the ledger: red, with its words; it needs the owner |

**The 26 examples.** Every English text is § I's, and every Spanish text of example 25.

1. The Strategies page, desktop, with its top bar (the tabs `binance` and `bybit`, the "Live"
   badge in cyan): `Open: 0 · Orders in flight: 0 · Last read: 21:40:03 UTC` and "Read again",
   above three rows that carry no mark.
2. A row with one live position: `AAVEUSDT · LONG · Live`, in cyan.
3. A row with one rehearsal position: `SFPUSDT · SHORT · Dry run`, in amber, under the amber "Dry
   run" badge.
4. A row with a position holding fills of both origins: `STXUSDT · LONG · Dry run and live`, in
   red.
5. A row with a position whose symbol cannot be resolved: `XYZBTC · side not readable · Live`.
6. Three rows, each with an order in flight and no fill yet, dashed and unfilled: dry run, live,
   origin unknown. `Open: 0 · Orders in flight: 3`.
7. Two rows with a position the venue disagrees on: the position's chip, the red chip "Venue
   disagrees", then the link "See the pending decision" on one and "No booking is proposed for
   it." on the other.
8. A DISABLED strategy's row (switch off) that carries a position's chip.
9. A row with three positions on three pairs, the chips wrapping in their own grid row, beside a
   row with none: the figures and the switch sit at the same height in both.
10. "Something is open, and not on this list": `Open: 2 · Orders in flight: 1`, with the order on a
    row of the page and neither position on one. Under the figures: "Not on this list: LINK 4h -
    RSI Divergences · archived · LINKUSDT · Dry run; STX 4h - RSI Divergences · XYZBTC · Live ·
    figures not readable." Both are held by the selected exchange; nothing of another exchange is
    named.
11. The summary in four states: 11a loading; 11b the first read failed, in red, with the button;
    11c a refresh failed after a good read, the last figures kept and "Could not be refreshed
    since 21:38:12 UTC." in red under them; 11d the same when the last good answer was empty. No
    failed form can be read as zero open.
12. Examples 2, 7, 9 and 10 at phone width (390 px): the figures wrap, the button stays 44 px
    tall, and the chips are the row's last line.
13. The detail page, desktop, with its top bar: the section "Open positions" between the
    two-column grid and "Closed trades", empty: "No open position."
14. The section with one live position and every column: Opened (UTC), Pair with the origin's word
    under it, Side, Size with its unit, Entry, Fees USDT, Margin granted USDT, Leverage; and the
    margin note under the table.
15. A rehearsal position at 1x with the dry-run note, and a row whose leverage is a dash ("not
    recorded" for a screen reader).
16. A position closed in part ("0.3 AAVE", "of 0.5 opened") and a position opened by three fills
    ("average of 3 fills" under its entry).
17. A position of both origins with its note, and an unresolved position: the side, the size and
    the entry as dashes, the reason in a sub-row under it, the fees, margin and leverage shown.
18. A position the venue disagrees on, as ONE red line under its row across the table: 18a with
    the link; 18b ending "no booking is proposed"; 18c with "shared by 2 positions on this pair"
    before the link.
19. An order in flight as a dashed line under the table: 19a under a position, "SFPUSDT · order in
    flight · closing · Dry run · sent 21:12 UTC"; 19b with no position, under "No open position.".
20. Three positions, as a table at desktop width and as cards at phone width.
21. The section while loading, and when the read failed, with the button.
22. An Overview pool panel with its list of open positions under the month grid and its summary:
    three positions of two strategies, the strategy's name the first column and a link; no Fees
    column. The summary line ends "3 open, 1 of them dry run".
23. The count in its three forms, beside today's sentence for comparison: "1 open"; "2 open, 1 of
    them dry run"; and absent when nothing is open.
24. Example 22 at phone width: the "Needs your decision" rail between the chart and the month
    grid, the positions as cards with the strategy's name under each head, and the venue line
    inside the card of the position the venue disagrees on, its link leading to the rail.
25. Examples 3, 7, 10, 14 and 18 in Spanish (25a to 25e).
26. A position the facts could not decorate: 26a the Strategies page, `Open: 1` and "Not on this
    list: STX 4h - RSI Divergences · XYZBTC · Live · figures not readable.", with no chip on any
    row; 26b the detail section reading "1 open position or order could not be matched to a
    strategy. The Strategies page names it." where "No open position." would be.

**What the prototype does not draw, and where this design says what is built instead.** None of
these is a disagreement with the picture; each is a case it has no example for.

| Not drawn | Built as | Section |
| --- | --- | --- |
| An order in flight as an item of "Not on this list" | the chip's own words: name, pair, "order in flight", origin | H |
| A time that is not of today | its date before it | H |
| The Overview's list while loading, when the read failed, and empty | the detail section's three states and texts | H |
| An order in flight on the Overview | not drawn there, as the owner decided on 2026-10-13 | H; O, Q8 |
| The unmatched sentence when the strategy also has positions | above the notes | H |
| A position with both a venue line and a reason | the venue line first | H |
| The reservation's note | a sub-row under its position, in the reason's type | H |
| The Spanish of the texts example 25 does not hold | § I's Spanish column | I |

**Four places where the picture is its own shorthand**, and the rule is what is built.

- Examples 18b and 18c leave out the margin note that 18a draws. The note is true of any
  position (§ H).
- In example 25e the third venue line, the one shared by two positions, ends at "compartida por 2
  posiciones en este par" and draws neither the link nor the words. The English of the same case,
  18c, ends with the link. The rule is 18c's: once the proposals are read, the line ends with one
  of the two (§ H).
- The numbers are samples, as the review bar says: some margins read `121.8` where the panel's
  money helper writes `121.80`.
- The order of the Overview's rows is illustrative. Example 22's caption says "sorted by strategy
  name, then market", and the picture draws STXUSDT above APTUSDT under one strategy; example 24
  draws SFP, STX, AAVE. What is built is the route's order (§ F): strategy name, pool, market,
  allocation id.

**One place where what is built departs from the approved picture, said as such.**
Example 25, which the owner approved with its Spanish, draws a price as `184,3` and a size as
`0,82 AAVE`, with a comma. What is built writes them `184.3` and `0.82 AAVE` in Spanish, with a
point, because that is how the closed trades table on the same page writes a price today (P30).
That is not shorthand in the picture: it is a difference, and the owner decided it on 2026-10-13
(Q9 of § O: "Sí, con punto"). The implementation follows the table, not the picture, on this one
point.

**The earlier answers still hold.** No example draws the summary in the header or on another page
(§ O, Q4), and none draws a position opening onto its fills (Q5). The forms without a link of
examples 7 and 18 are what this delivery ships (Q3).

### K. What fails here without a log line?

| # | Path | What the owner would see with no trace | What this design does |
| --- | --- | --- | --- |
| 1 | The ledger holds a position the venue already closed (liquidation, a close by hand, a stop) | A row with every figure for a position that does not exist | The venue mark, once the reconciliation has CONFIRMED it. Before that, nothing marks it: the window is the reconciliation's confirmations times its interval (both are settings, not re-read). Under `DRY_RUN` nothing is compared at all. § N. |
| 2 | The reconciliation's chain has died (its handler's own docstring calls that silent) | Rows with no mark, read as "the venue agrees" | Not solved here. A marked row shows "Last compared"; an unmarked row has nothing to show it. Flagged in § N as work of its own. |
| 3 | An order sent and not yet filled, or stuck | Nothing: the performance path has no fill to count | A row of its own, with the time it was sent, so an order in flight for hours is visible as such. One with no order id reads "origin unknown". |
| 4 | A position whose reservation is not `FILLED` (expired or released while its order filled) | A margin shown as granted for capital the pool counts as free | `reservation_status` is served; the row says so and the read logs one WARNING with the allocation id. Plausible and not proven: `SUBMITTED` may go to `EXPIRED` or `RELEASED` (`allocation/domain/reservation.py:36-52`). § L, T12. |
| 5 | A rehearsal position shown as live, or the reverse | The owner changes the mode on a wrong reading | The origin is the guard's own two flags, from the guard's own statement. No second prefix test exists. § L, T3 seeds a live id that only CONTAINS the marker. |
| 6 | A stale answer | `Open: 0` from ten minutes ago | The figures carry "Last read"; the hook refetches every 60 s and on focus; a failed refresh keeps the last figures and says since when in `loss`, also when they are zero (example 11d); "Read again" asks now. |
| 7 | One position written under two spellings (`STXUSDT.P` opened, `STXUSDT` booked) | Two rows, or one open and one "short" | Rows are per allocation. The fold nets every spelling; `markets` is the set of market keys, so the row says `STXUSDT` once. That holds for a `NO_FACTS` position too: the reader's own string joins the raw spellings (`STXUSDT / STXUSDT.P`), and the route normalises each piece before it serves them (§ C). § L, T8. |
| 8 | A disabled or archived strategy's position | Nothing, if the view followed the switch or the archived filter | Disabled: the chip is drawn. Archived and hidden: counted in the figures and named under them, on its exchange's tab. Another exchange: not shown on this tab, by the owner's decision of 2026-10-12 (row 18). |
| 9 | The figures and the fold disagree (the fold says open, the net computed for display is zero) | A row dropped, or a size of 0 | The row stays, `figures_missing` is `INCONSISTENT`, one WARNING names the allocation. § L, T5 is what keeps this from happening. |
| 10 | An allocation the guard's reader returned and the facts read did not | A row dropped | The row stays with `NO_FACTS` and no strategy id, counted and named under the figures on the tab of its own exchange (§ H); one WARNING with the allocation id. § L, T12. |
| 11 | An unresolved symbol | Nothing on the panel today (P8) | The row, with its reason; one WARNING with the allocation id, as the performance reads log it. § L, T12. |
| 12 | A confirmed row whose market is not among the position's markets | A mark about another market | The mark stays (the allocation id is the key) and one WARNING names both. § L, T12. |
| 13 | A body that is not the expected shape, or a 404 from an older API | An empty list | An error state. The shape check refuses the whole answer; a 404 is a failure here. |
| 14 | A confirmed disagreement with no proposal to decide | A link that leads to an empty rail | No link: the row says that no booking is proposed. § O, Q3. |
| 15 | The snapshot is not in force (the statement is not the first of the transaction) | Figures of two instants in one row | PostgreSQL refuses a `SET TRANSACTION` issued after a query: an error, hence a 500 and the error state, not a silent degradation. § L, T6 proves the happy path. |
| 16 | An order the guard's reader returned and the submitted-orders read did not (possible only if the snapshot is lost) | An order dropped: the one case the guard refuses on and the panel would not show | The row STAYS, built from the reader's element, with no strategy id, action or time; it is counted and named under the figures on the tab of its own exchange. One WARNING with the attempt id. § L, T12. |
| 17 | An element whose pool is not its reservation's, or a `SUBMITTED` attempt with no reservation: its exchange may be no tab at all (added 2026-10-12) | Nothing, on any tab: the exchange is now the key that decides which tab shows an element, and no tab has that key | The row stays in the answer with its own pool; one WARNING with the allocation or attempt id and the pools found, at every read. For a position EVERY group of its fills is compared, with the element's pool, the reservation's pool and the reservation's strategy (§ C), so an allocation whose fills name two pools, or another strategy, is logged too, where the guard's element would show one of them without a word. Its strategy's detail page shows it when it has a strategy id. The owner decided on 2026-10-13 that the Strategies page does not name it (§ O, Q7). § L, T12. |
| 18 | The selected tab reads zero and zero while another exchange holds a position | "Nothing is open", read as the whole system's answer before a mode change | By the owner's decision the page speaks of one exchange. No text says "nothing is open" without a tab above it, none is worded as a permission, and the guard refuses the start whatever was read (§ B). § L, T15 pins that the other exchange's elements are absent, so that the absence is the rule and not a defect. |
| 19 | The strategies list failed, or is filtered, while positions exist | Rows with no mark, read as "no strategy holds anything" | The figures do not depend on the list, and every element of the exchange that no row carries is named under them. |
| 20 | An order sent, or a disagreement last compared, on an earlier day | "sent 21:12 UTC", read as minutes ago | A time that is not on the day of the read is written with its date (§ H). § L, T18. |
| 21 | The Overview's read failed | No count under the month grid, which is also how "nothing open" looks (example 23c) | The list's heading is always drawn, with the error sentence and "Read again" under it. § L, T13. |
| 22 | The pending proposals are loading or their read failed, on a position the venue disagrees on | "no booking is proposed", a claim nobody checked | Neither the link nor the words is drawn until the proposals are read (§ E). § L, T19. |
| 23 | The link "See the pending decision" lands at the top of the Overview | A link that seems to lead nowhere, on a phone where the rail is below the chart | The rail brings itself into view when the hash names it (P29). § L, T19. |
| 24 | A pool with no performance report holds a position | Nothing on the Overview: the month grid and its summary are not drawn without a report | The list is placed outside that condition (`PoolPanel.tsx:143-148`), so the rows are drawn. The COUNT is not: it is a part of the summary line, which stays inside the condition. Such a pool shows its list and no count, and that is accepted (§ H). § L, T13. |
| 25 | An element with NO strategy id on an exchange that has no tab: a `NO_FACTS` position or an undecorated order whose own pool names such an exchange (added after validation) | **Nothing, anywhere on the panel.** No tab selects it, no strategy's page can (it has no id), and the Overview has no panel for it | Not solved on the panel, by the owner's decision, and said so. It is logged at WARNING at every read (rows 10 and 16), and a WARNING reaches no alert, by the rule under this table. Money is safe: the worker's guard reads the same element and refuses the start. The panel is silent by the owner's decision of 2026-10-13 (§ O, Q7): the count-only line that would have ended the silence without naming an exchange was declined. |
| 26 | An element whose exchange has a tab and whose pool is not one of `GET /pools`' pools (added after validation) | Nothing on the Overview: no panel has that pool's three values, so it is in no list and in no count | The Strategies page counts it and draws or names it, and its strategy's page shows it: neither selects by pool. The Overview stays without it. Logged at WARNING by § C's check, since such a pool cannot be its reservation's. § L, T13 pins that it is in no panel, so that the absence is known and not discovered. |
| 27 | The first read fails | "Reading open positions…" for about 7 s before any error, read as a slow page | Not a silent failure, a late one: the query client keeps TanStack's three retries (P34). The loading text is a `role="status"`, the error a `role="alert"`, and neither can be read as zero. Not changed here: a retry policy for one query is a choice nobody asked for. |

**Levels**, the ones `performance/application/scope.py:18-24` gives for read models: WARNING with
the ids for a fault in stored data, nothing when nothing is wrong, never ERROR, because a read
model fires once per page view and only ERROR reaches the operator's alerts. No price, quantity,
fee or margin is ever logged. Rows 4, 9, 10, 11, 12, 16 and 17 repeat on every read while the fault
exists, and each has a test that reads the log record (§ L, T12; T5 keeps row 9 from arising);
with a 60 s poll that is one line a minute per open tab, which is the accepted cost of a fault that
is otherwise invisible.

**What that rule costs, since 2026-10-12.** "Never ERROR" was written when every element was
named on some screen, so a WARNING was a second trace. Rows 25 and 26 are cases where, as the
panel stands, it is the only one for part of the panel or for all of it. The rule is not
changed here: a read model that logged ERROR once a minute per open tab would bury the alerts it
is meant to protect. The owner was offered an answer on the panel for row 25 and
declined it on 2026-10-13 (§ O, Q7), so the log is its only trace.

### L. Testing strategy

Strict TDD: each test is seen failing on an ASSERTION before the code exists. A test that passes at
once is proven by breaking what it guards and watching it go red; T1 and T2 are of that kind and
say how.

| # | Test | Layer | What it pins |
| --- | --- | --- | --- |
| T1 | **The invariant, table-driven.** A fake reader holds a case table: rehearsal, live, mixed, unresolved, rehearsal order, live order, and every pair of them. For each case and for both values of `DRY_RUN`, the SAME reader instance is given to `find_mismatches` and to `ReadOpenPositions`. Asserted: every mismatch's identifier is the id of a row of the answer; and when the answer is empty, `assert_mode_matches_ledger` does not raise. | application, fakes | § B. Non-vacuity: make the use case skip an unresolved allocation, then an order; each must turn it red. |
| T2 | **The same, generated.** A seeded `random.Random` builds a few hundred ledger group sets (sides, quantities, base and settlement fees, two spellings, both origins) and asserts the same inclusion, plus: the answer's allocation ids EQUAL the reader's. `hypothesis` is not a dependency of the backend (`pyproject.toml`), so the generator is the standard library's with a fixed seed. | application, fakes | No case table can be complete. |
| T3 | **The same on real PostgreSQL.** The cases the guard's integration test seeds (a disabled pool, two pools, a base-currency fee, two spellings, a live id that contains the marker, a closing attempt, a terminal attempt, an attempt with no order id) are seeded through a shared helper; the route's answer is compared with `SqlAlchemyModeOriginReader`'s two answers on the same database: equal ids for positions, a superset for orders, the attempt with no order id present as `unknown`. The guard's own test file is not edited. | infrastructure | The SQL, the joins and the wiring together. |
| T4 | **Wiring.** The router's source names `SqlAlchemyModeOriginReader`, in the manner of `tests/test_mode_guard_wiring.py:63-67`. | structural | That the reader is not replaced by a look-alike. |
| T5 | **The net for display agrees with the fold.** Over T2's generated sets: `open_position_figures` answers figures with a size above zero exactly when the fold calls the allocation open and its symbol resolves. | domain | § D, § K row 9. |
| T6 | **The snapshot.** On real PostgreSQL, a harness holds the read between its first and second statement, a second connection commits a closing fill, and the read is released. Asserted: the answer is the state BEFORE the fill, whole. Then the same harness with the snapshot statement removed must show the mixed state, which proves the test can fail. | infrastructure | § G. It is also the proof that the statement is accepted as the transaction's first, and it decides between the raw statement and SQLAlchemy's execution options (§ G; P35): the dependency keeps whichever of the two this test passes with. |
| T7 | **Statement counts.** Four with nothing open, seven with one position and with twenty, in the manner of `test_operations_statement_counts.py`. | infrastructure | No statement per row. |
| T8 | Domain tables for `open_position_figures` (one fill, several fills, a partial close, a base-currency fee, a flip, two markets, an unresolved symbol, a SHORT, and the two `INCONSISTENT` cases: a net of exactly zero, and a held side with no quantity or notional above zero), for `origin_of` against the origin `find_mismatches` reports, and for the mark's key (a row naming the allocation, a row of the same market naming another, an `OBSERVED` row, a resolved row, a row of another pool, a row naming two allocations). Router tests for the body, field by field, for a `NO_FACTS` position and an undecorated order (their nullable fields are written as JSON null, never omitted and never a zero: `strategy_id`, `opened_at`, `fees`, `margin_granted` and `leverage` for the position, with `other_fees` an empty list), and for 401. Corrected after validation: a `NO_FACTS` position whose reader element spells its symbols `STXUSDT / STXUSDT.P` is served with ONE market, `STXUSDT`, and an order's `market` is a market key whichever source built it; a leverage stored as 2 is served as the string `2.00000000`. | domain, infrastructure | § C, § D, § E, § F. |
| T9 | Frontend, the API module (`shared/api/positions.test.ts`): a well-formed body; a body with one bad element refused whole, an element with no `pool.exchange` among them; a 404 as an error; the five selectors: `ofExchange` keeps exactly the elements of that exchange and matches the string exactly; `ofPool` selects by the three values and never by exchange alone; `notShown` returns an element whose `strategy_id` is null whatever ids are on screen; and, over one fixture, the positions of `ofExchange` equal the union of `ofStrategy` for the visible ids and `notShown`, with nothing in both. | Vitest | § H, § K row 13. Changed on 2026-10-12: five selectors, not two. |
| T10 | Frontend, the components: every state of § H's table for `OpenStateLine`, `OpenMarks` and `OpenPositionsSection`. For `OpenStateLine`: the three figures with their labels; that a failed first read draws no figure at all, so never `Open: 0`; that a failed refresh keeps the last figures and adds the red sentence, also when they are zero; that every element of the selected exchange in a fixture is drawn in a row or named under the figures, and that the count equals the two together; the item of an archived strategy's position and of one with no strategy id, letter for letter as example 10; the second line withheld while the strategies list loads; that a refetch which changes only `as_of` changes no text inside the `role="status"` region. For the rest: the link only with a matching pending proposal; a disabled row keeps its chip; `['positions','open']` is invalidated after a booking is approved AND after one is rejected, one test in each of `ConfirmBookingDialog.test.tsx` and `RejectBookingDialog.test.tsx`; an unmatched element of the strategy's exchange keeps the detail's "No open position." from being drawn, and one of another exchange does not; the loading mark of a row has the translated accessible name. Corrected after validation: the leverage cell reads `2x` for a served `"2.00000000"` and `1x` for `"1.00000000"`, and never the served string; a null leverage on a position that has its facts is a dash named "not recorded". | Vitest, Testing Library | § H. Changed on 2026-10-12: the figures replace the sentence, and the selected exchange bounds every assertion. |
| T11 | Frontend, the texts, **incremental by unit** (corrected after validation: the first writing put the whole assertion in op.2, where two thirds of the keys do not exist yet). One test file holds the list of § I's keys and asserts that each is in both locale files with a non-empty text. The list GROWS with the units: op.2 adds the keys it draws (`positions.state.*`, `positions.marks.*`, `positions.origin.*`, `positions.sideUnreadable`, the chip's `positions.order.inFlight`, and the chip's four `positions.venue.*` keys); op.3 adds `positions.order.*`, `positions.venue.line.*`, `positions.venue.groupName`, `positions.table.*`, `positions.reason.*` and `positions.note.*`; op.4 adds the three `overview.*` keys. Each unit's keys go into the locale files in that unit, with their test. The assertion that NO key of § I's "no longer exist" table is in either file is written in op.2 and stays. op.4 closes it: there the list is compared with § I whole. No assertion about hex or `var()`: `shared/theme.test.ts` already makes it for every source file (P35). | Vitest | § I. |
| T12 | **Every WARNING of § K, and the row it must not cost.** With fakes and the log captured, one case each: a position whose reservation reads `EXPIRED` (row 4); the fold calling an allocation open while the display net is zero (row 9); an open allocation the facts read does not answer for (row 10); an unresolved symbol (row 11); a confirmed row that names the allocation under another market (row 12); an in-flight element with no submitted row (row 16); and, added on 2026-10-12, a position whose fills name one pool and whose reservation another, an order whose attempt names one pool and whose reservation another, and a `SUBMITTED` attempt with no reservation (row 17), the two pools spelled as two different exchanges. Corrected after validation, two more for row 17, because every group of fills is compared and not one: an allocation whose fills are in TWO pools, the element built from either of them (the case is run with the groups in both orders, since the reader's order is not fixed), and an allocation whose fills carry a `strategy_id` that is not its reservation's. Asserted for each: the row IS in the answer with the fields § C and § F give it, its `pool` its own and not the reservation's; exactly one WARNING is logged; it carries the allocation or attempt id; it carries no price, quantity, fee or margin. And a case with nothing wrong logs nothing. | application, fakes | § K rows 4, 9, 10, 11, 12, 16, 17; § C "a row the facts cannot decorate stays". |
| T13 | **The Overview part** (`PoolOpenPositions.test.tsx`, `MonthlySummary.test.tsx`, `PoolPanel`'s tests). `PoolOpenPositions` draws no position of another pool of the same exchange; the strategy's name is a link, and plain text for a position with no strategy id; there is no Fees column; no order in flight is drawn; the venue line is drawn under its row. Its three states: loading, failed with "Read again", empty; and the list is drawn for a pool that has no performance report. The count: "N open" with no rehearsal position, "N open, M of them dry run" with some, a position of both origins in N and not in M, no part at zero, and no part at all while the read is loading or failed. Corrected after validation: a pool with a position and NO report draws its list and no count; a `NO_FACTS` position is a row whose Opened, Side, Size, Entry, Margin granted and Leverage cells are each a dash named "figures not readable", with no "Invalid Date" and no `x` alone; a position whose pool is none of the panel's pools is in no list and in no count. | Vitest, Testing Library | § H, the Overview part; § K rows 21, 24 and 26; rule 7. Changed on 2026-10-12: no longer separable. |
| T14 | **The "Live" badge** (`shared/layout/AppShell.test.tsx`). The test "says Live, in the loss colour, when the server reports dry_run false" is renamed "says Live, in the gain colour, when the server reports dry_run false" and asserts `text-gain` and `border-gain` on the badge, and that it has neither `text-loss` nor `border-loss`. The four other tests of that `describe` do not change: the neutral states stay neutral. | Vitest, Testing Library | § H; decision 65. Changed test. |
| T15 | **The Strategies page shows nothing of another exchange** (`features/strategies/StrategiesPage.test.tsx`). One answer holds, on `binance`, one position on a visible strategy; and on `bybit`, a position on a visible strategy, a position of an archived strategy, a position with no strategy id and an order in flight, each with a pair and a strategy name found nowhere else in the fixture; and, added after validation, the stored fault of § H: a position whose `strategy_id` is the visible `binance` strategy's and whose `pool.exchange` is `bybit`, with a pair of its own. With `binance` selected: the figures read `Open: 1` and `Orders in flight: 0`; the `binance` row carries ONE chip, not two; no "Not on this list" line is drawn; and none of `bybit`'s pairs or names is in the document, the faulty position's pair among them. Then the scope selects `bybit`, with no new request: the figures read `Open: 4` and `Orders in flight: 1`, the faulty position is named under them (its strategy has no row on this tab), and `binance`'s pair is gone. Non-vacuity: make `OpenStateLine` read the whole answer and watch it go red. | Vitest, Testing Library | § B point 4; § H, the scope rule; § K row 18. New. |
| T16 | **The marks' rule, as a table** (`features/positions/Mark.test.tsx`). For every kind and origin of § H's table: a position has `bg-panel-2` and no `border-dashed`; an order has `border-dashed` and `bg-transparent`; `border-dashed` is on no mark that is not an order; `border-loss` and `text-loss` are on the position of both origins and on the venue chip and on no other; a live mark has `border-gain` and its word `text-gain`; a dry-run mark `border-decision` and `text-decision`; an unknown origin `border-rule-strong` and `text-ink-3`; and every mark holds its origin, or "Venue disagrees", as text. | Vitest, Testing Library | § H, the marks. New. |
| T17 | **One line, two variants** (`features/positions/MarkLine.test.tsx`). `OrderLine` and `VenueLine` render the same element with the same class list but for the border's style and colour; the order line's parts and the venue line's parts in § H's order, letter for letter as examples 19 and 18, in both languages for the venue line (25e); a part with no value is left out with its separator (`action` null, `submitted_at` null, a count of one). | Vitest, Testing Library | § H, the two lines. New. |
| T18 | **A time of another day carries its date.** `clockSecondsText`; and "sent", "last compared" and "could not be refreshed since" given an instant of the day before the read's `as_of`. | Vitest | § H, times; § K row 20. New. |
| T19 | **The link and the rail.** The venue mark, as a chip and as a line: the link with a matching pending proposal; the words with the proposals read and none matching; neither while the proposals are loading and when their read failed. `DecisionRail` has the id, and scrolls into view when rendered at a location whose hash is that id, and not otherwise (`scrollIntoView` is stubbed: jsdom has none). | Vitest, Testing Library | § E; § K rows 22 and 23. New. |
| T20 | **`MonthlySummary` keeps its second caller.** With no `open` prop it writes "N open trades not in the curve" as today; `StrategyPerformance.test.tsx:107-115` is not edited and passes. | Vitest, Testing Library | § H; P27. New. |
| T21 | **The amber allow-list** (`features/overview/panel-tokens.test.ts`, an EXISTING test, changed). `AMBER_ALLOWED` gains `features/positions/origin.ts`, in its sorted place between `features/overview/DecisionRail.tsx` and `features/settings/ExchangeKeyCard.tsx`, and the comment above the list gains decision 65: the origin "Dry run" of an open position, in the words and the amber of the mode badge. The list is compared with `toEqual`, so the same assertion pins that NO other file under `features/positions` writes a `decision` class. The test's first block is not edited: `MonthlySummary`, `PoolPanel` and `OverviewPage` stay on its never-amber list and must keep passing after op.4. | Vitest | § H, "Amber"; P31. Added after validation. |
| T22 | **The harness answers the new route** (`frontend/src/test/harness.tsx`, test infrastructure, changed). `stubApi` gains a branch for a URL ending in `/positions/open`: by default a well-formed empty body, `{as_of, positions: [], orders: []}`; an eighth optional argument overrides it with the same four kinds the other stubs have (ok, a status, pending, a network error), and `extra`, which is asked first, can still take the URL. Its proof is the gate, not a new assertion: with the branch in and no page asking yet, every existing test passes unchanged; and once the pages ask, `StrategiesPage.test.tsx:217, 227` still find ONE alert and `OverviewPage.test.tsx:279, 292` still find none. | Vitest | P31; § M. Added after validation. |

- **Symbols.** Every test that crosses a boundary uses a different spelling on each side: the
  ledger's fills as `STXUSDT.P`, the discrepancy row as `STXUSDT`, a booked fill as `STXUSDT`, an
  attempt as `STXUSDT.P`.
- **Concurrency.** No lock is added, so there is no second actor to prove waiting. T6 is the one
  concurrent test, and it is a held read, not a barrier with `sleep(0)`.
- **The fixture server.** `frontend/vite.fixture.config.ts` is the owner's untracked file and no
  agent edits it. What the owner would add is one handler, `GET /api/positions/open`, answering a
  body with § J's examples: one live, one rehearsal, one mixed, one unresolved, one order in
  flight, one with a `venue_disagreement` whose `discrepancy_id` and `allocation_id` match a
  proposal the fixture's bookings handler already serves, one on an archived strategy, and one on
  another exchange, so that changing the tab is seen to change the figures. The tasks
  hand that body over as a JSON file under `openspec/`, ready to paste.
- **Gate.** Each unit has its own, named in § M.

**The first red test of each unit.** Each is seen failing on an ASSERTION, with the code under test
already importable and returning the wrong thing, never on an import or a constructor error.

| Unit | The test seen failing first | Why it fails before the code exists |
| --- | --- | --- |
| op.1 | T6, the snapshot. The route's dependency is first written as a pass-through that yields a plain session, and the use case as a stub that reads the two lists in two statements. | The held read then shows the state AFTER the concurrent fill; the assertion "the state before the fill, whole" fails. It is also the unit's riskiest assumption, so it is settled before anything is built on it. |
| op.1, next | T1, with `ReadOpenPositions` stubbed to answer an empty state. | The guard's mismatch identifiers are not among the answer's ids. |
| op.2, the badge | T14, renamed and asserting `text-gain`, before `DryRunBadge.tsx` is touched. | The badge still has `text-loss`: the assertion fails, on a class and not on an import. |
| op.2, amber | T21: `features/positions/origin.ts` is added to `AMBER_ALLOWED` before the file exists. | `toEqual` fails: the list names eight files and seven use amber. It goes green when `origin.ts` is written with its `decision` classes, and not before. |
| op.2 | T10: `OpenStateLine` given a FAILED read, with a stub that draws `Open: 0` whenever it has no data. | The assertion that no figure is drawn fails. This is the panel's version of the invariant, so it is the first thing pinned. |
| op.2, next | T15, with `OpenStateLine` and `OpenMarks` first written over the whole answer. | The other exchange's pair is in the document and the count is too high. |
| op.3 | T10: `OpenPositionsSection` given one position whose `leverage` is null, with a stub that writes every cell from a default. | The assertion that the cell holds a dash with "not recorded", and not "1x", fails. |
| op.4 | T13: `PoolOpenPositions` given positions of two pools of one exchange, with a stub that draws all it is given. | The assertion that the other pool's position is absent fails. |

Two commits of op.2 have no red test, and the same proof: every existing test passes unchanged.
They are the harness's default answer (T22), which is test infrastructure and comes first, and
the mechanical move (§ H), which changes import paths only. The badge's change, the third commit
of op.2, does have one (T14), and so does the amber step (T21).

### M. Delivery

**Before the tasks are written: nothing is pending.** The prototype is approved (§ J) and the two
points decision 65 left for it are answered (§ O, Q1 and Q2). Four questions are open in § O, each
with the default the tasks build; none of them holds the tasks back.

| Unit | Contents, in the order they are built | Forecast, authored lines |
| --- | --- | --- |
| op.1 | Backend: the domain module, the ports, `ReadOpenPositions` with the pool check of § C over every group of fills and the market keys of a `NO_FACTS` position, the two adapters, the router and its snapshot dependency, the two lines in `main.py`, T1 to T8 and T12 | 1,850 to 2,600 |
| op.2 | The Strategies page. **Three commits open it, each on its own, in this order.** First the harness: `frontend/src/test/harness.tsx` answers `/positions/open` with an empty, well-formed body by default and takes an override (T22); gate, every existing test passes unchanged (20 to 40). Second the mechanical move: the two format files with their tests to `shared/lib/`, `Absent` and `Instant` to `shared/ui/`, about twenty import lines, no assertion changed; same gate (60 to 120). Third the badge: `DryRunBadge.tsx`, its test, one comment in `index.css` (15 to 25). Then the unit proper, whose FIRST step is the amber allow-list: `features/positions/origin.ts` added to `AMBER_ALLOWED` in `panel-tokens.test.ts`, with its comment, seen red, before `origin.ts` is written (T21). After it: the API module, its shape check, the hook and the five selectors; `origin.ts`, `OriginTag`, `Mark`; `OpenStateLine`; `OpenMarks` in `StrategyRow`; the rail's id and scroll; the time helper; the invalidation in the two booking dialogs; this unit's texts and their part of T11; T9, T10, T14 to T16, T18, and the chip's half of T19 | 1,750 to 2,550 |
| op.3 | The detail page: `PositionsTable` in its strategy variant, with a null drawn as a dash in every cell, `MarkLine` with `OrderLine` and `VenueLine`, `OpenPositionsSection`, its texts and their part of T11; T17, the line's half of T19, the section's part of T10 | 1,350 to 2,050 |
| op.4 | The Overview: the pool variant of `PositionsTable`, `PoolOpenPositions` in `PoolPanel`, the `open` prop of `MonthlySummary`, the three `overview.*` texts; T13, T20, and the closing of T11 against § I whole | 650 to 1,000 |
| | **The four units** | **5,600 to 8,200** |

**How the forecast was recomputed, and why it grew.** The first writing gave 3,600 to 5,300 for
op.1 to op.3 and 500 to 800 for op.4, so 4,100 to 6,100. The revision of 2026-10-12 put it at
5,350 to 7,950, counted component by component with the tests at about twice the production
code, as the last units ran. The corrections after validation add about 250 lines: it is now
5,600 to 8,200. The ranges are rounded to 50.

| | Production | Tests | Why it differs from the first writing |
| --- | --- | --- | --- |
| op.1 | 650 to 900 | 1,200 to 1,700 | three columns in two statements; every group of fills compared; a `NO_FACTS` position's symbols normalised; five cases in T12 where there were none for row 17 |
| op.2, the three opening commits | 50 to 100 | 45 to 85 | the badge and the harness's branch are new; the move was already counted |
| op.2 proper | 650 to 850 | 1,000 to 1,500 | the marks' one table and its test, five selectors where there were two, T15 with the stored fault in its fixture, the rail's scroll, the time of another day, the amber list; and the first figure was low for five components and their states |
| op.3 | 520 to 720 | 830 to 1,330 | the shared line and its test, the table written once for two pages, a dash for every null, the leverage's two cases, the proposals' loading state |
| op.4 | 170 to 270 | 480 to 730 | its three states, the list for a pool with no report and no count, the six dashes of a `NO_FACTS` row, the pool that is in no panel, the count's three values, the summary's second caller |

About 500 to 700 lines are what the owner's review added, and about 250 what the validation
found. The rest is that the first frontend figures were low, which is said here and not hidden in
the range. Nothing was removed to make the number smaller, and the summary as three figures is
somewhat cheaper than the sentence it replaces.

The rail's id and scroll are op.2's, not op.3's as first written: the list's venue chip carries
the link, so the first unit that draws a link owns its target.

**The gate of each unit**, run after it and before its commits are closed.

| Unit | Gate |
| --- | --- |
| op.1 | `cd backend && uv run ruff check . && uv run mypy src && uv run pytest --tb=short`. It touches no frontend file. |
| op.2 | `cd frontend && npm run lint && npm test`, run four times: after the harness's commit alone and after the mechanical move alone (each time every existing test passes unchanged, and no test file but `harness.tsx` and the moved ones is edited), after the badge's commit, and after the unit. Inside the unit, `panel-tokens.test.ts` is seen red after its list is extended and green once `origin.ts` exists. It touches no backend file. |
| op.3 | `cd frontend && npm run lint && npm test`. |
| op.4 | `cd frontend && npm run lint && npm test`. |
| the PR | both gates, on the branch's head, before it is opened. |

pytest prints no summary line in this shell: the backend gate is read from its exit code and from
the per-file counts of `uv run pytest --co -q`, as the working agreements say.

- **Order.** op.1 first: the panel refuses an answer it cannot read, so the route exists before the
  code that asks for it. Then op.2, opened by its three commits; then op.3; then op.4. op.4 is last
  because it reuses op.3's table, not because it might be dropped: the owner agreed to it on
  2026-10-12.
- **One PR for the four units**, cut from an up-to-date `main`, each unit its own work-unit
  commits with its tests. The owner's standing preference is one PR per unit of work unless there
  is a specific reason to split, and none holds here: the four units are one feature, the backend
  alone shows nothing, and the one order hazard is harmless (a new bundle against an older API
  shows the error sentence, never a figure of zero). The reason the first writing gave for a
  second PR, that the Overview part might be dropped or changed, is gone. The size is far above
  the 400-line review budget; the owner has said that the budget is soft.
- **If the tasks slice it all the same** (the session's delivery strategy is `auto-chain`), the
  slices are the four units in this order, each a PR cut from an up-to-date `main` after the one
  before it is merged: sequential, never stacked, as the working agreements say. Each is safe to
  ship alone. op.1 adds a route nobody calls. op.2 gives the Strategies page its figures and
  marks; its venue chip's link already reaches the rail. op.3 adds the detail section. op.4 adds
  the Overview's list and changes its count. The badge's commit could ship first of all, alone.
- `Decision needed before apply: No` (§ O holds no open question; Q6 to Q9 were answered on 2026-10-13) · `Chained
  PRs recommended: No` (one PR; if sliced, sequential by unit, never stacked) · `400-line budget
  risk: High`.

**Migration: none.** Every column the read uses exists and is populated by code that runs today:
`ledger_entries` (`ledger/infrastructure/models.py:36-64`), `reservations.amount` and `.status`
(`allocation/infrastructure/models.py:45-46`), `execution_attempts.leverage`, `.status`,
`.exchange_order_id`, `.reservation_id` and `.closes_allocation_id`
(`execution/infrastructure/models.py:60-65, 88-98`), and the discrepancy's `open_allocation_ids`,
`status` and `resolved_at` (`reconciliation/infrastructure/models.py:57-84`). No column, index,
constraint or enum value is added, and nothing is written. The indexes the facts statements ride
already exist (§ G). So no migration is rehearsed and none runs.

**Deploy.** The owner runs every command.

1. Pull as `strategy`; restart `strategy-api`. The worker runs no new code: restarting it is not
   needed and is harmless (it runs the guard once more).
2. `curl` the new route with the admin token (never pasted into a chat or a log) and read the two
   lists against what the owner knows to be open.
3. The bundle step of task pps.6, since `frontend/` changed: built on the owner's machine from a
   clean checkout of `origin/main`, copied to a release directory of its own.
4. Read the panel: `https://strategymanager.trade/build.txt` names the commit; then the figures on
   EACH exchange's tab of the Strategies page, the marks, one strategy's section, the Overview's
   list and count, and the badge's colour.
5. The delivery log of the active change's `tasks.md`.

**Rollback.** Revert the PR's merge commit, pull, restart `strategy-api`, and point the panel back
at the previous release directory. Nothing was written and no schema changed, so there is no data
to undo. Rolling back only the bundle is also safe: the older panel never asks for the route.

**Reverting one part alone.** Each is frontend only, so no service is restarted; each is followed
by the bundle step of pps.6.

- **The Overview part (op.4).** It is no longer separable by design, and it is still revertible:
  revert its work-unit commits, in reverse order. They touch `PoolOpenPositions`, the pool variant
  of `PositionsTable`, `PoolPanel`, the `open` prop of `MonthlySummary`, the three `overview.*`
  keys, T13 and T20. The Overview returns to today's count; the list, the detail page and the
  route keep working, since nothing of op.1 to op.3 imports op.4.
- **The badge.** Revert its one commit: two lines, a comment and a test. The marks keep their
  colours; the badge and the live marks would then disagree, which is the state the owner asked
  to end, so this is a revert for a defect and not a choice of taste.
- **The mechanical move** is not reverted alone: everything after it imports from `shared/`.

**Design decisions made here** (not owner decisions; each has its reason above):

| # | Decision | Section |
| --- | --- | --- |
| D1 | One definition of "open": the guard's fold, where it is. Nothing of the guard changes | B |
| D2 | The panel's lists are built by iterating over the guard's own reader's output; facts only decorate | B, C |
| D3 | In-flight orders are listed, the ones with no order id too, as "origin unknown" | B, C |
| D4 | One whole-system route with no parameter, in a router of its own; every view filters it | F |
| D5 | The read model lives in `performance`; a new domain module beside `operation.py` | C, G |
| D6 | One read-only snapshot per request; no lock | G |
| D7 | Side from the net's sign; size is what remains; entry is the average of the held side's fills | D |
| D8 | Figures that cannot be derived are null with a reason; the row always stays | D, K |
| D9 | The venue mark is keyed by allocation id inside the pool, on open CONFIRMED rows only; no origin filter | E |
| D10 | The mark links only when a pending proposal names the allocation and the discrepancy | E |
| D11 | **Superseded on 2026-10-12 by the owner.** It was: a sentence on the Strategies page states the whole system's answer. It is: three labelled figures, on the Strategies page and only there (§ O, Q4), for the selected exchange and no other, with the names of what that exchange holds and its list does not show | B, H |
| D12 | One query key, 60 s stale time and refetch interval; invalidated by a booking decision | H |
| D13 | **Superseded on 2026-10-12 by the owner.** It was: "Live" in neutral ink. It is: "Dry run" in `decision`, "Live" in `gain`, and `loss` only for what needs the owner | H |
| D14 | **Withdrawn**: the Overview part is in. It stays revertible (§ M) | H, M |
| D15 | One PR for the four units | M |
| D16 | A row the facts cannot decorate stays, without a strategy id. Amended on 2026-10-12: it is named on the tab of its own exchange, not on every view | C, F, H |
| D17 | The body serves only what a component draws | F |
| D18 | The formatting helpers and the two cells move to `shared/` in a commit of their own | H |
| D19 | **Withdrawn**: `ofPool` is with the other selectors, and the Overview's texts are ordinary keys | H, I, M |
| D20 | The route stays whole-system and takes no parameter; the selected exchange is a selection on the client | F, H |
| D21 | Everything the Strategies page draws is selected from `ofExchange` first, so the count equals what is drawn plus what is named | H |
| D22 | An element belongs to the exchange of its own pool, the guard's label. The read compares EVERY group of a position's fills with that pool, with the reservation's pool and with the reservation's strategy, and logs a difference; it never changes the answer | C, K |
| D23 | An element whose exchange has no tab is shown on no tab, as the owner decided on 2026-10-13 (§ O, Q7); it is always logged | C, H, K |
| D24 | One table from an origin to its word and its two classes; one line component with two variants | H |
| D25 | The live region holds the counts and not the time of the read | H |
| D26 | A time that is not of the read's day is written with its date | H, K |
| D27 | The link's last part is drawn only from a successful read of the proposals; the rail scrolls itself into view | E, H, K |
| D28 | The Overview's list does not depend on the pool's report, always draws its heading, and draws no order in flight (§ O, Q8) | H |
| D29 | `MonthlySummary` takes the new count as an optional prop; its second caller, the detail page, is not changed (§ O, Q6) | H |
| D30 | Figures are written by the closed trades table's helpers (§ O, Q9). The leverage is `figureText` and an `x` | H |
| D31 | After validation: `origin.ts` is the only positions file that writes a `decision` class, and it joins the amber allow-list in a red step before it exists | H, L, M |
| D32 | After validation: the test harness answers the new route by default, in the first commit of op.2 | L, M |
| D33 | After validation: a `NO_FACTS` position has null fees, date, margin and leverage, and every null cell is a dash with its reason | C, D, F, H |
| D34 | After validation: the pairs of every element are market keys, normalised by the route and never by the guard | C |
| D35 | After validation: a row's marks are `ofStrategy` inside `ofExchange`, never `ofStrategy` alone | H |
| D36 | After validation: T11 grows with the units and closes in op.4; the Overview's count stays inside the summary line and is absent without a report | H, L |
| D37 | After validation: the count-only line was recommended; the owner declined it on 2026-10-13 (Q7), so the panel says nothing about an item on no tab | N, O |

**Threat matrix.** N/A: no routing of commands, shell, subprocess, VCS or PR automation,
executable-file classification or process integration. The new HTTP route is read-only, sits
behind the router-level bearer token and takes no input.

### N. Risks, and what could be wrong in this design

| Risk | Why it could matter | What limits it |
| --- | --- | --- |
| The panel still shows a position the venue no longer has, for as long as the reconciliation takes to confirm it, and for ever if its chain has died | The list is the ledger's, by the owner's choice of scope B | The mark, its time, and § K rows 1 and 2. A "last compared" time for a pool that has NO disagreement needs something the system does not store; it is not designed here. |
| The whole-ledger aggregate runs once a minute per open tab | It grows with the ledger, which only grows | It is the statement the worker runs at each start and the order of work the list already does per row. If it becomes slow, the answer is to bound the guard's statement itself, for both readers at once, which is a change to the guard and so a design of its own. |
| Five implementations of the rule become six readers of two definitions, not one | The archive check, the key delete, the closes and the reconciliation keep their own SQL (P9) | Out of scope by choice: each feeds a write or a refusal with its own tests. This design adds no implementation of the DECISION; it adds one of the display arithmetic, pinned to the fold by T5. |
| `SET TRANSACTION` as the session's first statement may not behave as assumed on this stack | It is the first use of a non-default isolation here | T6 is the first test written. If it cannot be made to hold, the fallback is the default level with § C's order of statements, which never shows less than there is; the tasks say so before building on it. |
| Zero and zero on one tab is read as "nothing is open anywhere", or as a permission to change the mode | It states a fact about one exchange at one instant, and since 2026-10-12 no screen states the whole system's | The owner chose this knowing it (decision 65: before a mode change the owner looks at each exchange's tab). The figures carry their time and sit under the tab that scopes them. The guard remains the control and refuses the start whatever was read (§ B); the panel is the view. |
| A cyan mark is read as "winning" | Cyan is also the colour of a gain in the figures of this panel, so a live position that is losing carries a "winning" colour: the mirror of the owner's first misreading, a red mark read as "losing" | Said to the owner before the answer, and accepted. What answers it: every mark says "Live" as a word, the top bar's badge is the same cyan and says the same word, and no mark holds a number. `LONG` and `SHORT` stay in ink, and red is never an origin. To be judged again in live use. |
| The "Live" badge stops being an alarm | It was red "because real money moves"; in cyan it is a statement of the mode | The owner's decision, with that consequence stated. The badge is still always visible (decision 32), and a failed or pending read still shows neither mode. |
| An open position or order on an exchange that has no tab | No tab shows it, and the owner has nowhere to look | It needs stored data at fault (P25, P26). The read logs it at every request (§ K, row 17), its strategy's page shows it, and the guard still refuses on it. Whether the Strategies page should name it was answered on 2026-10-13: it does not (§ O, Q7). |
| The detail page writes a live-only count above a section that lists every position | "1 open trade not in the curve" beside two rows, one of them a dry run | Not changed: decision 65 names the Overview's count, this second caller was found on 2026-10-12 (P27), and the owner chose on 2026-10-13 to leave it live-only. The two statements are both true as worded. § O, Q6. |
| In Spanish, numbers do not all read as the prototype draws them | Example 25 draws a comma in prices and sizes; the helpers write a point there and a comma in fees, as the closed trades table does today | The open positions follow the table under them, so one page is consistent; the owner chose this on 2026-10-13. § O, Q9. |
| "1 open, 1 of them dry run" | The approved form was awkward for one position, and ungrammatical in Spanish ("1 abiertas") | Corrected after the final review, 2026-10-13, with the owner's agreement: `openWithRehearsal` has `_one` and `_other` forms, and one dry-run position reads "1 open, dry run" / "1 abierta, en simulación". |
| The Overview shows no order in flight | A pool whose only open thing is an order reads "No open position." | True as worded, and the Strategies page counts and marks the order. § O, Q8. |
| The API and the worker could disagree about `DRY_RUN` | The panel shows the mode from `/health`, the API's own setting | Not changed here. The read does not depend on the mode at all. |
| A strategy with many pairs open draws many chips | The row grows taller | Bounded by its allowed pairs; the chips wrap inside the first track (§ J, example 9). |
| Reusing `strategies.performance.trades.*` for the column words ties two tables' texts | A later change of one changes both | Intended: the same word for the same figure. The prototype shows both tables on one page. |
| The forecast | The last units ran above theirs, and this one grew by more than a third between the first writing and the corrected one (4,100 to 6,100, then 5,600 to 8,200) | It was recounted component by component on 2026-10-12, with tests at twice the code, and § M says which part of the growth is the review's, which the validation's, and which was an earlier undercount. |
| The validation's recommendation on Q7 was declined | An open position or order with no strategy id on an exchange with no tab is on NO page of the panel, and its only trace is a WARNING that reaches no alert (§ K, row 25) | **The validation had recommended a count-only line**: "{N} open items are on no exchange tab", under the figures, drawn only when N is above zero. The owner declined it on 2026-10-13 (§ O, Q7): the panel says nothing about such an item. The silence is therefore decided, not a gap; the WARNING at every read stays. Money is safe either way, since the guard refuses the start. |
| An allocation whose fills name two pools is shown under one of them | The guard's element takes its pool from one row, and which row is not fixed (P33), so the pool on screen could differ between two reads | It needs stored data at fault. The read compares every group and logs the difference (§ C); the answer is not changed, so that the panel and the guard's refusal keep naming the same pool. Fixing the order would be a change to the guard's reader, which this design does not touch. |
| Two shared test files are touched by this delivery | `panel-tokens.test.ts` and `harness.tsx` are shared by every frontend test; a careless edit to either reddens the suite | Each is its own step with its own gate (§ M): the harness's branch first, with every existing test unchanged; the amber list as a red step before the one file it names. |
| The `leverage` of an old position may be NULL for a reason other than "spot" | The cell is empty and the reason reads "not recorded" | Correct by the owner's rule: never filled in. |

**Follow-ups, recorded and not designed here.**

| # | Follow-up | Why it is not in this delivery |
| --- | --- | --- |
| F1 | A view of the CONFIRMED discrepancies, including those that have no booking to decide. Once it exists, the row's venue mark links to it. | Owner, 2026-10-11 (§ O, Q3): it is the next unit, with a design of its own. Until then the row says "No booking is proposed for it" and links nowhere. |
| F2 | An open position opening onto its individual fills, as a closed operation does. | Owner, 2026-10-11 (§ O, Q5): not in this delivery. Its design starts by establishing whether the fills read answers for an allocation that is not closed, which is not verified (P22). |
| F3 | A sign, on a row with NO venue mark, of when its pool was last compared with the venue, so that a dead reconciliation chain is not read as agreement. | It needs a fact the system does not store (§ K, row 2). |

**What was assumed and not verified** is listed at the end of § A. The two that most affect the
design are the session's behaviour under `SET TRANSACTION` (T6) and whether a reservation can be
other than `FILLED` under a position (§ K, row 4).

### O. Questions for the owner: all nine answered (2026-10-13)

The two points decision 65 left for the prototype review were answered on 2026-10-12, and the
three this addendum raised on 2026-10-11. The revision of 2026-10-12 surfaced four more (Q6 to
Q9); the owner answered them on 2026-10-13, each as the default this design had proposed, so
nothing that was built to a default changes. No question of this addendum is open.

**Answered.**

**Q1 (carried). Does the Overview list every open position of the selected exchange, pool by
pool?**
**Answered 2026-10-12: yes** ("Lo de Overview me parece bien, lo incorporamos"). It is a unit of
the delivery, no longer a separable part (§ H, § M).

**Q2 (carried). Does the Overview's count change from "N open trades not in the curve", which
counts live positions only, to "N open, M of them dry run"?**
**Answered 2026-10-12: yes**, with Q1 (§ H). What the answer did not cover is Q6 below, answered on 2026-10-13.

**Q3. When the reconciliation has confirmed that the venue disagrees and there is no booking to
decide, is the row's own statement enough?**
**Answered 2026-10-11: yes, for this delivery.** The row says so and links nowhere: "No booking is
proposed for it". That happens when two positions share the pair (it is never proposed), and when
a proposal was rejected, expired or is not prepared yet. A view of the confirmed discrepancies is
NOT in this delivery: it is the next unit, with a design of its own, and the row's mark will link
to it once it exists (§ E; § N, follow-up F1).

**Q4. Is the Strategies page the only place for the sentence that answers for the whole system
("Nothing is open on any exchange" / "Open now, on every exchange: …")?**
**Answered 2026-10-11: yes, the Strategies page only.** There is no variant in the header, beside
the mode badge or on any other page (§ H).
**Changed on 2026-10-12, by the owner, in two steps.** First its scope: the Strategies page shows
nothing of another exchange, so the summary answers for the selected exchange only, and "Not on
this list" names only what that same exchange holds. Then its form: three labelled figures,
`Open: 0 · Orders in flight: 0 · Last read: 21:40:03 UTC`, that name no exchange, in place of a
sentence. The place did not change: the Strategies page, and only there. No screen now answers
for the whole system (§ B).

**Also decided by the owner on 2026-10-12, without a question of this section** (decision 65):
the marks' rule, shape for what a mark is, colour for the origin, red for what needs the owner;
the "Live" badge in `gain`, in this delivery; the venue mark of the detail page as one line in the
type of the order line, with a solid red border; and the prototype approved as drawn at commit
`6603dea`, its texts and its Spanish included.

**Q5. Should an open position open onto its individual fills, as a closed operation does?**
**Answered 2026-10-11: not in this delivery.** It is recorded as a follow-up (§ N, F2). Nothing in
this design calls the fills route, and the first writing's remark that the route "does not require
the operation to be closed" is withdrawn: it was not found in the code (P22).

**Q6. The strategy detail page writes "N open trades not in the curve" for that strategy, counting
live positions only. Should it change as the Overview's count does, stay as it is, or go?**
**Answered 2026-10-13: it stays as it is** ("No, solo reales"). The sentence keeps counting live
positions only and does not take the Overview's new form. The section "Open positions" below it
lists every position, dry-run ones included, so the two can read differently; that was said to the
owner with the question.

**Q7. If something is open that belongs under none of the exchange tabs, should the Strategies
page say so with one line under the figures, or say nothing?**
**Answered 2026-10-13: nothing.** The panel says nothing about an open item that belongs under no
exchange tab; the count-only line the validation of this design recommended was declined. The
item stays logged at WARNING at every read (§ C, § K), and the worker's guard still refuses the
start in the wrong mode, so money is not at risk.

**Q8. Should a pool's list on the Overview also show that pool's orders in flight?**
**Answered 2026-10-13: no** ("Sí, queda así"). Orders in flight are on the Strategies page and on
the strategy's page, as the approved prototype draws them.

**Q9. In Spanish, should a price in the open positions read `184,3`, as the picture you approved
draws it, or `184.3`, as the closed trades table writes it today?**
**Answered 2026-10-13: `184.3`** ("Sí, con punto"). Prices and sizes of open positions are written
with a point in both languages, as the closed trades table writes them; money keeps the language's
separator (`0,17`) and the currency's decimals (`121.80`). This is the one place where what is
built does not follow the approved prototype's Spanish example 25 (§ J).

Never asked, because a decision or the code answers it: that in-flight orders are shown (the
invariant requires it, § B); that rehearsal positions are shown and marked (decision 65); the
words "Dry run" and "Live" (the mode badge's, decision 32); that no notional is shown (decision
65); that a disabled strategy's position is shown (decision 65); that a rehearsal position shows
1x (it is what is recorded, P12); UTC for every time (decision 16 allows local time for trade
times, and the trades table shows UTC).

## Addendum: PR 15 — Confirmed discrepancies (owner decision 66)

HEAD `14ef3b9`, branch `feat/operator-panel-discrepancies`, written 2026-10-16. Decision 66 is
binding and is not reopened here: a view of the CONFIRMED discrepancies as an item of the
navigation bar, with a badge counting those that need the owner and nothing at zero; automatic
booking of `ATTRIBUTABLE_FULL_CLOSE` and `ATTRIBUTABLE_SINGLE_ALLOCATION` when the venue fills sum
exactly to the observed difference, each listed in the view; no booking of any kind for
`AMBIGUOUS_PARTIAL_REDUCE` and `NO_MATCHING_ALLOCATION`, shown in the view and told to the owner;
"Needs your decision" out of the Overview, and the open position's venue line linking to the new
view. The owner's goal, verbatim: "Prefiero que el sistema no me pida intervención si la idea es
dejarlo correr indefinidamente sin necesidad de monitorearlo a diario." This addendum is design
only: it writes no task, no code and no spec file. "Unit dc" below is a placeholder for the
tasks to name.

> **Revised 2026-10-16 after the owner's answers.** The owner answered all ten questions of § O
> the same day, each as its recommended option, and Q3 with one addition (decision 66, the
> sub-list "The design's questions (design.md, PR 15 addendum), answered 2026-10-16"). Every
> "pending" mark is resolved in place. Four answers changed the design beyond removing a mark:
>
> - **Q3: the alert carries the reason.** The reason is still not stored, so there is no
>   migration. Instead the sweep returns each refusal's CODE in memory, and the announcement
>   writes it into the message as an argument, so the message template stays the same and so
>   does the throttle key (§ C6, § E, § J; § K row 2; § L, T2 and T7).
> - **Q4: a daily reminder**, logged under its own template so that the throttle cannot fold it
>   into an announcement; and a check before the deploy, run by the owner, that prints only a
>   count to show whether alerts are on in production (§ E, § M, § N).
> - **Q8: the venue mark says "being booked automatically"** while a booking is under way. The
>   venue line and chip therefore read the confirmed-discrepancies query, and PR 14's rule
>   "until it is read, neither the link nor the words" stays, applied to that query (§ H; § K
>   row 15; § L, T11).
> - **Q10: the first automatic booking is a deliberate live test**, recorded as the first step
>   once the owner decides to go live (decision 63, not taken) (§ M, § N).

**The answer in one paragraph.** Automatic booking adds no second writer. The existing
`reconciliation.prepare_booking` job, after `PrepareBooking.sweep` has committed its proposals,
calls the existing `ApproveBooking.approve` for every proposal still `PENDING`, with a fixed
actor, one transaction per proposal: the same code the approve route runs today. So every guard
of the manual path still holds because it is the same code: the exact sum, the single
allocation, the venue order id, the freshness re-check, the in-flight close, both UNIQUEs, and
`DRY_RUN` refused at the handler and in the use case. The only lock is the proposal's row lock;
no pool advisory lock is taken, for the reasons `book-venue-closes` gave, which still hold now
that no human sits between prepare and approve, so no lock order can be broken. No migration: an
automatic booking is an `APPROVED` proposal whose `decided_by` names the system. One pure
predicate, `needs_owner`, decides which confirmed discrepancies need the owner. The nav badge,
the view's first list and a new Telegram announcement all use it, so they cannot disagree.
Nothing alerts on a confirmed discrepancy today (§ B). The view reads one new admin route,
`GET /reconciliation/confirmed`. The decision rail leaves the Overview, and so do the three
scope messages it also carried, which must move into the page (P14).

### A. Findings from the code (verified at HEAD `14ef3b9`)

| # | Finding | Where | Consequence |
| --- | --- | --- | --- |
| P1 | Booking is two steps today: a worker job prepares a `PENDING` proposal every 60 s, and a human approves it through an API route. | `reconciliation/application/prepare_booking.py:112-309`; `booking_prepare_handler.py:179-208`; `reconciliation/infrastructure/router.py:396-442`; `shared/config.py:315` | Automation only needs to join the two steps in the worker. Nothing about how proposals are matched or written has to change. |
| P2 | `PrepareBooking` only ever inserts. Its comment "Deliberately nothing further" says calling `mark_state` there "would be exactly the accidental auto-approval the money-critical test in this unit exists to catch". | `prepare_booking.py:288-306` | Approval stays OUT of the sweep. It becomes a separate step after the sweep's commit (§ C1), so that test and the spec's "prepare writes nothing to the ledger" stay true. |
| P3 | `ApproveBooking.approve(proposal_id, decided_by)` is one transaction: `FOR UPDATE`, not-PENDING → `ALREADY_DECIDED`, `DRY_RUN` refusal, expiry, freshness (a)-(g) plus the single-allocation re-check, the writer's SAVEPOINT, `mark_state`, commit. Every outcome except `APPROVED` logs a WARNING. | `approve_booking.py:111-268` | It is reused unchanged. `decided_by` is already a parameter, so the automatic actor is just a value. |
| P4 | The proposal row lock lives in `get_for_update`. Its own comment says the lock protects the caller's freshness-and-write gap. There is already a real-PostgreSQL concurrent double-approval test. | `booking_proposal_repository.py:171-192`; `tests/reconciliation/application/test_approve_booking_integration.py:935` | The automatic step's concurrency test reuses that harness (§ L, T6). |
| P5 | Booking takes no pool advisory lock, by design: it reads no availability and writes no reservation, the race is between two writers of one fill, which the UNIQUEs settle, and `SettleExecution` takes no lock either. The pool lock is taken by `AllocateCapital`, archive, delete strategy and delete credential. | archived `book-venue-closes/design.md:227-234`; `allocation/application/allocate_capital.py:169`; `strategies/application/archive_strategy.py:163`; `delete_strategy.py:118`; `accounts/application/delete_credential.py:123` | Kept (§ C3). Of the four reasons, only item 3 (approval was human-paced) no longer applies. The other three still do. |
| P6 | Prepare refuses an `ATTRIBUTABLE_FULL_CLOSE` over more than one open allocation, with a WARNING, and the database refuses such a row too. | `prepare_booking.py:248-263`; `migrations/versions/0023_booking_proposals.py:112` | Decision 66's "a full liquidation is `ATTRIBUTABLE_FULL_CLOSE` whatever the number of allocations" is true of the VERDICT, not of the booking. A full liquidation of two strategies on one pair is booked neither automatically nor by hand. It needs the owner, with its alert (§ D rule 3; Q9, answered (a): this corrects what the owner was told before the design). |
| P7 | Prepare skips `AMBIGUOUS_PARTIAL_REDUCE` and `NO_MATCHING_ALLOCATION` with a bare `continue`, without a log line. | `prepare_booking.py:131-136` | Nothing on the booking path says such a discrepancy exists. |
| P8 | `match_fills` takes every UNRECORDED venue fill in `[first_observed_at - 300 s, now]`. It requires one side and an exact signed sum. It does not check whether the difference moves the allocation toward zero, nor whether a fill belongs to an order this system placed. | `reconciliation/domain/booking.py:136-219`; `prepare_booking.py:153-213`; `shared/config.py:325` | An exact sum can still be the wrong attribution. Example: strategy B opens 0.3 and its settle exhausts its retries, so B's fills are unrecorded and B has no open allocation. Strategy A holds 0.5. The venue reads 0.8 and the verdict is `ATTRIBUTABLE_SINGLE_ALLOCATION` for A, with delta +0.3. B's fills sum exactly and would be booked to A permanently. Check (g) looks at A's strategy only (`approve_booking.py:260-267`). Today a human reads the fills first; automatic booking removes that read. Hence Q2's two refusals (answered (a), § C8). |
| P9 | The scan writes a confirmation without a log line. Its only log line is the WARNING for a failed venue read. The scan handler logs only its `DRY_RUN` skip. | `scan_pools.py:227-239`, `:117`; `reconciliation_scan_handler.py:110-118` | A discrepancy can reach `CONFIRMED` with no line in the journal. |
| P10 | Operator alerts forward ERROR and above only, from the root logger, to Telegram. They are opt-in (`ALERTS_ENABLED`, default `False`) and throttled to one per (logger, message template) per 900 s. A misconfigured channel says so once at WARNING. | `shared/infrastructure/alert_log_bridge.py:114`, `:207`, `:227-231`; `alerting.py:40-60`, `:87-100`; `shared/config.py:365`, `:389`; owner-decisions.md:67, :142 (ERRORs reach Telegram in production) | An alert for a discrepancy has to be an ERROR record. Two different discrepancies announced with the same template inside 900 s become ONE alert plus a "+1 suppressed" note, and that note arrives only with the next admitted alert (§ E, § N). |
| P11 | `HoldingGuard` refuses a GHOST or AMBIGUOUS holding at WARNING. | `signals/application/holding_guard.py:195-204` | A strategy blocked by an unbooked close is not alerted either. |
| P12 | The watchdog logs ERROR for FAILED jobs and for recurring kinds with no live job, and `RECONCILIATION_PREPARE_BOOKING` is one of those kinds. | `shared/application/watchdog.py:283-310`; `shared/infrastructure/recurring_jobs.py:55-61` | A dead booking chain is already loud. The automatic step adds no new chain. |
| P13 | `booking_proposals.decided_by` is nullable free text. `state` takes five values, `APPROVED` requires `decided_at`, and only `APPROVED` carries an `execution_attempt_id`. | `0023_booking_proposals.py:93-106`, `:163` | An automatic booking needs no migration (§ F). |
| P14 | The decision rail is also where the Overview says the exchange scope is loading, failed, or has no exchanges. The page's docstring says "The rail says why". | `features/overview/DecisionRail.tsx:93-105`; `OverviewPage.tsx:30-33`, `:45-67` | Removing the rail without moving those three messages would leave an Overview that shows only its title when pools fail to load: a silent failure (§ H, § K row 7). |
| P15 | Only the rail mounts `BookingsListView` and the two dialogs. The venue line and the venue chip read `usePendingBookings` for one purpose: choosing between "See the pending decision" and "no booking is proposed". `DecisionRail.tsx` is on the amber allow-list. | `DecisionRail.tsx:5`, `:49`; `features/positions/MarkLine.tsx:106-130`; `OpenMarks.tsx:35-50`; `features/overview/panel-tokens.test.ts:64-65` | Once the rail goes, the bookings feature has no other caller and is removed (Q1, answered (a)). Both links point to the new view and read the confirmed discrepancies instead of proposals (Q8, § H). |
| P16 | The navigation has three items, typed by a `labelKey` union. `SideNav` and `BottomNav` draw them with no badge. The routes live in one file. | `shared/layout/navItems.ts:1-13`; `SideNav.tsx`; `BottomNav.tsx`; `app/router.tsx:15-27` | One more item and one badge component, drawn in both navs. |
| P17 | Production has always run in dry run, and under `DRY_RUN` both the scan and the prepare job skip. | owner-decisions.md:449; `reconciliation_scan_handler.py:110-118`; `booking_prepare_handler.py:180-187` | No discrepancy and no proposal is expected in production. This was NOT verified on the VPS; § M hands the owner a read-only count. |
| P18 | The approve route builds `ApproveBooking` with `FixedUsdRateProvider({USDT: 1})`. | `router.py:348-365` | The worker's automatic step uses the same provider, so a booking's `usd_rate_at_fill` does not depend on which process wrote it. |
| P19 | `GET /reconciliation/discrepancies` reads every open row and filters in Python. The open set is small by construction: one row per disagreeing pool and symbol. | `router.py:162-199` | The new read route can use the same `list_discrepancies(status=CONFIRMED, open_only=True)` call that `PrepareBooking` and `ConfirmedDisagreementSource` already make. |

### B. Does anything alert on a confirmed discrepancy today? No.

Nothing does: no Telegram message, no ERROR, not even a WARNING. Followed end to end:

1. The scan writes `CONFIRMED` without a log line (P9).
2. Prepare logs nothing for the two kinds it never books (P7). For a bookable kind it refuses, it
   logs a WARNING on every sweep, once a minute.
3. The guard that then refuses the strategy's signals logs a WARNING too (P11).
4. Only ERROR reaches the bridge, and alerting itself is opt-in (P10). The watchdog's ERRORs
   cover a dead chain or a FAILED job (P12), never the data those chains find.

So today a confirmed `NO_MATCHING_ALLOCATION` stays a journal-only fact, unless the owner
happens to read `GET /reconciliation/discrepancies` or sees the red venue mark on a position.
`NO_MATCHING_ALLOCATION` has no position row to carry that mark. What is added is described in
§ E (Q4, answered (b)).

### C. Automatic booking

**C1. Where it runs.** In the `reconciliation.prepare_booking` handler, in this order:

```
handle(job):
  if dry_run: skip, as today (no expire, no sweep, no auto-book, no announcement)
  else:
    expire()              # unchanged
    sweep(job.id)         # plus Q2's two refusals and refusal codes; commits once
    auto_book.run()       # NEW: ApproveBooking.approve for every PENDING proposal
    announce.run()        # NEW: § E, with this run's refusal codes and approval outcomes
  enqueue the successor   # unchanged
```

`AutoBookPending`, a new use case in `reconciliation/application/auto_book_pending.py`, lists
`PENDING` proposals with the existing `list_pending(limit=...)` (`booking_proposal_repository.py:222`).
For each one, in list order, it calls `approve(proposal.id, decided_by=AUTO_BOOKING_ACTOR)`, where
`AUTO_BOOKING_ACTOR = "system:auto-booking"` is defined once, beside the route's `ADMIN_ACTOR`
(`router.py:96`). It depends on a `Protocol` with `approve`'s signature, not on the class, the
same way the handler depends on `PrepareBookingPort` (`booking_prepare_handler.py:112-116`). It
returns counts per outcome, and the handler logs one INFO summary when anything moved, otherwise
DEBUG, following the existing `_log_summary` (`booking_prepare_handler.py:137-159`).

Why approval is not done inside `sweep`: `sweep` commits once, at its end
(`prepare_booking.py:308`), while `approve` commits on every outcome. Approving inside the loop
would commit half a sweep, and it would make prepare a ledger writer, which P2 forbids.

Why EVERY `PENDING` proposal, not only those this job prepared: a crash between the sweep's
commit and the approvals leaves rows `PENDING`, and the next run must pick them up. Proposals
left from the manual era are also caught (Q1, answered (a)). An unbounded list is impossible: the
partial unique index keeps at most one `PENDING` proposal per discrepancy (`0023`,
`ux_booking_proposals_pending_per_discrepancy`).

**C2. Transaction boundaries.** The handler keeps the one session it has today
(`main.py:1604-1715`). The worker builds `ApproveBooking` the way `_approve_use_case` does
(`router.py:348-365`): the same session, `SqlAlchemyBookingWriter`, `InFlightCloseAdapter`, the
same fixed USD rate (P18), `SystemClock`, and `dry_run=settings.dry_run`.

| Step | Transaction | Committed by |
| --- | --- | --- |
| expire | one | `ExpireBookingProposals` (unchanged) |
| sweep | one for the whole sweep | `PrepareBooking.sweep` (`prepare_booking.py:308`) |
| each automatic approval | one per proposal: row lock, freshness, SAVEPOINT write, `mark_state` | `ApproveBooking.approve` (every return path commits, `approve_booking.py:121-212`) |
| announcement | none (it reads, logs and writes nothing) | — |
| successor | the handler's final enqueue | `main.py`'s `await session.commit()` |

**C3. Locks and their order.** The only lock is the proposal row's `FOR UPDATE`, held from
`get_for_update` to the commit of the same proposal's approval. No pool advisory lock is taken,
and that keeps P5's reasoning. A booking reads no availability and writes no reservation, so rule
4 does not govern it. The race that matters, two writers recording one venue fill, is settled
by `ux_ledger_exchange_fill` and `execution_attempts_client_order_id_key`, and a pool lock would
not remove it, because `SettleExecution` records fills without a lock. The one reason that no
longer applies is that approval used to wait for a human.

Since only a row lock is taken, the rule "pool advisory lock first, then row locks" has nothing
to order. A system close racing a booking of the same allocation needs no lock either: the fills
are distinct, the venue order is `reduceOnly`, and the two leave the ledger net where the venue
is, in either order. The freshness check (g) is a best-effort early refusal, not the guarantee.
If a later change makes booking write a reservation or move availability, it takes the pool lock
FIRST, before `get_for_update`. That is the order every other path uses, and the change's tests
would then need the pool-lock harness of `test_archive_vs_allocate_concurrency.py`.

**C4. Idempotency.**

| Replay | What happens |
| --- | --- |
| The job runs twice (a retry after a crash, or two live jobs of the kind) | Prepare inserts at most one `PENDING` row per discrepancy; a second insert is `ON CONFLICT DO NOTHING` and logs INFO (`prepare_booking.py:288-299`). The second approver waits on the row lock, then reads `APPROVED` and returns `ALREADY_DECIDED` with a WARNING, writing nothing (`approve_booking.py:114-122`). |
| Crash after the sweep's commit, before approval | The row stays `PENDING`; the next run approves it if it is still fresh, otherwise `SUPERSEDED` or `EXPIRED`. |
| Crash after an approval's commit | It is `APPROVED`; `list_pending` no longer returns it. |
| The same fills reach the ledger by another path first | The writer's SAVEPOINT catches the named collision, and the proposal becomes `SUPERSEDED` with a WARNING (`approve_booking.py:198-213`; `booking_writer.py:73-90`). |

**C5. `DRY_RUN`.** Refused at three layers, as today plus one: the handler skips everything
(`booking_prepare_handler.py:180-187`), `PrepareBooking` refuses (`prepare_booking.py:113-118`),
and `ApproveBooking` refuses with `DRY_RUN_REFUSED` and a WARNING (`approve_booking.py:124-131`).
The automatic step adds no `DRY_RUN` check of its own: the handler never reaches it under
`DRY_RUN`, and if it ever did, the use case refuses.

**C6. Every failure branch, and its line.**

| Branch | Outcome | Log line |
| --- | --- | --- |
| A refusal at prepare (sum, sides, zero unrecorded, window, market, fetch, several allocations, no order id, and Q2's two) | No row; retried next sweep. The refusal's CODE is returned in `PrepareBookingResult.refusals` (§ E). | WARNING per discrepancy per sweep (existing, spec "Refusal Logging"). After the grace, also the one ERROR of § E, carrying that code (Q3). |
| `ALREADY_DECIDED`, `SUPERSEDED`, `EXPIRED`, `DRY_RUN_REFUSED` at approval | State committed as today | WARNING (existing, `approve_booking.py:115`, `:125`, `:144`, `:161`, `:206`), plus the handler's INFO summary |
| `APPROVED` | One attempt and N ledger rows | INFO (existing, `approve_booking.py:184-189`), plus the summary |
| `BookingProposalNotFound`, `InvariantViolation`, an unexpected `IntegrityError`, any other exception | It propagates. The session is discarded, the job fails and is retried by the queue, and no successor is enqueued for that run. | The queue records the failure. An exhausted job reaches the watchdog's ERRORs, "ended FAILED" and "nothing scheduled" (P12), which reach Telegram. Deliberately NOT caught per proposal: an unexpected fault in a ledger writer stops the writer rather than continuing past it, the rule this handler already follows (`booking_prepare_handler.py:45-53`). The cost is that one poisoned proposal halts every booking until it is fixed, and it does so loudly. |
| The approval loop is cut by `list_pending`'s limit | The rest are approved on the next run | INFO summary names the count |

**C7. How long the GHOST refusal lasts now.** It lasts from the venue's close to two equal
scans 30 s apart (`shared/config.py:300`, `:307`), then up to one prepare interval of 60 s, then
the approval itself: typically under two and a half minutes, against "until the owner approves"
today. A signal arriving in that window is still refused GHOST, as it is today.

**C8. Narrowing the automatic boundary (Q2, answered (a)).** Two more refusal conditions in
`PrepareBooking`, each with one WARNING and no row, as the spec's "Refusal Logging" requires of
every condition. Either one leaves the discrepancy unbooked, so after the grace it needs the
owner, with its alert and its reason code (§ D rule 4, § E). The cost, said to the owner: adding
to a position by hand is never booked automatically.

- **The difference reduces the position.** `venue_net_base` lies between zero and
  `ledger_net_base`, inclusive of zero: same sign or flat, and smaller in size. A liquidation, a
  stop or a close by hand only ever reduces. An increase or a flip is a fill this system cannot
  explain. `ATTRIBUTABLE_FULL_CLOSE` always passes this test.
- **No matched fill belongs to an order this system placed.** No matched `exchange_order_id`
  equals the `exchange_order_id` of an `execution_attempts` row of the same pool, read through a
  new read port over `SqlAlchemyExecutionAttemptRepository`. Such fills are the system's own and
  are recorded by `SettleExecution` or its recovery, never as a venue-originated close. This
  closes P8's example.

Both go in prepare, not in the automatic step, so `PENDING` keeps meaning "approvable". A
proposal that the automatic step would refuse to touch would sit for 24 h, expire, and be
prepared again forever.

### D. The `needs_owner` rule

One pure function in `reconciliation/domain/attention.py` (no framework). It sorts every open
`CONFIRMED` discrepancy into exactly one of three groups; an `OBSERVED` or resolved row belongs
to none. It reads the confirmation STATE, never the presence of `confirmed_at`, as the
venue-reconciliation spec requires. Its inputs are the row, `now`, the grace, and whether an
`APPROVED` proposal for that discrepancy froze the row's CURRENT observation (kind and both nets,
by `Decimal` value).

| # | Condition, first match wins | Group | Reason code |
| --- | --- | --- | --- |
| 1 | `kind` is `AMBIGUOUS_PARTIAL_REDUCE` or `NO_MATCHING_ALLOCATION` | NEEDS_OWNER | `NOT_BOOKABLE` |
| 2 | An `APPROVED` proposal froze the current observation | BOOKED (waiting for the next scan to resolve it) | — |
| 3 | More than one open allocation (P6) | NEEDS_OWNER (Q9, answered (a)) | `SEVERAL_ALLOCATIONS` |
| 4 | `now - confirmed_at` is more than the grace | NEEDS_OWNER (Q3, answered (a)) | `NOT_BOOKED` |
| 5 | otherwise | BEING_BOOKED | — |

Rule 2 compares the observation rather than only asking whether a booking exists. If a booking
was written and the venue moved again afterwards, the row's observation changes and the earlier
booking no longer hides it (§ K row 12). `confirmed_at` survives a demotion (spec "Confirmation
State And Its Timestamp Are Not The Same Question"), so a row confirmed long ago, demoted and
confirmed again counts at once. That is intended: it has been unbooked that long.

The grace is a new setting, `reconciliation_auto_booking_grace_seconds`, with a
default of 300 s (five prepare intervals; Q3, answered (a): 5 minutes). Rule 4 covers every
way a bookable discrepancy can stay unbooked: the fills did not sum, the venue read failed,
either refusal of Q2, a stale approval. The view shows each of them as "Could not be booked
automatically" (`NOT_BOOKED`), and the reason is not stored. The badge counts NEEDS_OWNER and nothing
else. Automatic bookings never count, as decision 66 says.

### E. Telling the owner (Q4, answered (b); Q3's addition)

A new use case, `AnnounceNeedsOwner`, runs after the automatic step. It reads the open
`CONFIRMED` rows and the `APPROVED` proposals of those discrepancies, and applies § D. A
discrepancy that is NEEDS_OWNER and was not yet announced in this process is collected. If any
were collected, ONE ERROR record is logged, naming each one by pool, symbol, kind, reason code
with its fixed English phrase, and discrepancy id. It contains no quantity, price or fee. The
bridge carries it to Telegram (P10).

**Where the reason comes from (Q3's addition: "the alert that announces it carries the reason").**
The reason is not stored, so the announcement can only know the reasons of the run it belongs
to.

- **The codes.** One closed vocabulary, `BookingRefusal`, a `StrEnum` in
  `reconciliation/domain/booking.py`:
  - from `MatchRefusalReason`: `SUM_MISMATCH`, `MIXED_SIDES`, `ZERO_UNRECORDED`,
    `NONPOSITIVE_QUANTITY`;
  - from prepare's other refusals: `WINDOW_TOO_LONG`, `MARKET_MISMATCH`, `VENUE_READ_FAILED`,
    `NO_ORDER_ID`, `SEVERAL_ALLOCATIONS`, `SUPPRESSED_BY_REJECTION`;
  - from Q2: `GROWS_OR_FLIPS`, `SYSTEM_ORDER_FILL`;
  - from approval: `STALE_AT_APPROVAL` for `SUPERSEDED`, `EXPIRED`.
- **Collecting them.** `PrepareBookingResult` gains `refusals: Mapping[UUID, BookingRefusal]`,
  keyed by discrepancy id and filled by every refusal branch next to its existing WARNING. The
  result of `AutoBookPending` maps each proposal that was not approved to its discrepancy id and
  code.
- **Remembering them.** The handler merges both into a module-level `last_reason_by_discrepancy`,
  which drops an id once it is booked or resolved.
- **Reasons that need no memory.** Rules 1 and 3 of § D take their reason from the row:
  `NOT_BOOKABLE` with the kind, and `SEVERAL_ALLOCATIONS`.
- **After a restart.** The first sweep of a fresh process refuses again, and refills the memory
  before its own announcement runs.
- **When no reason is known.** A NOT_BOOKED item whose reason this process has not seen is
  announced as `REASON_UNKNOWN`, "see the worker log". It is never left out of the announcement.

**The throttle key stays one key.** The bridge throttles per (logger, message TEMPLATE)
(`alert_log_bridge.py:227`, `:291-297`). The announcement's template is a constant,
`"confirmed discrepancies need the owner: %s"`, and the list of items, reasons included, is its
single argument. So a reason never mints a new throttle key, and the throttle still does its
job: one message per 900 s.

- **Once per start.** The memory of what was announced is process-scoped and module-level, for the
  reason `_SkipAnnouncement` gives (`booking_prepare_handler.py:82-109`: `main.py` builds a
  fresh handler for every job). An id that stops being NEEDS_OWNER is dropped from it, so a
  recurrence is announced again. Each start of the worker announces everything still open once
  (decision 66, Q4: "one message per discrepancy per start of the worker").
- **The daily reminder.** While anything is NEEDS_OWNER, one ERROR at most every 24 h lists every
  such item with its reason. It is timed from the process's last announcement or reminder,
  through a new setting, `reconciliation_needs_owner_reminder_seconds`, default 86400. It uses its
  OWN constant template, `"reminder: %d confirmed discrepancies still need the owner: %s"`, so
  the throttle cannot fold it into an announcement made in the same window. That closes the gap
  the throttle leaves: a second announcement within 900 s of the first may never arrive alone,
  and the reminder lists it within a day.
- **Logger name.** The module's own `strategy_manager.reconciliation...` logger. It must never sit
  under `strategy_manager.alerts`, which the bridge drops (`alert_log_bridge.py:52-58`).
- **Alerts must be on.** Alerting is opt-in (P10), and whether it is on in production is not
  verified. § M's check before the deploy settles that. Without it, the badge is the only signal
  (§ K row 10).
- **Automatic bookings are not announced.** Decision 66 lists them in the view "to be read when
  the owner wants to". Their INFO lines (C6) are their trace in the journal.
- **Under `DRY_RUN`** nothing runs, and nothing can exist to announce (P17).

### F. The approve and reject routes, `PENDING` proposals, the bookings UI, and the migration

With C1, a proposal is `PENDING` for the seconds between the sweep's commit and its approval, so
a human approve or reject has nothing left to act on. Answered Q1 (a). As the owner was told,
no manual path is lost: only an attributable discrepancy with one allocation could ever be
approved by hand, and that is exactly the kind that becomes automatic.

- Remove `GET /reconciliation/bookings`, `POST .../approve` and `POST .../reject`
  (`router.py:378-504`), the frontend `features/bookings/` folder (`BookingsListView`,
  `BookingCard`, both dialogs, `usePendingBookings`, `format.ts`, `outcomeMessage.ts`, and their
  tests), `features/positions/pendingProposal.ts`, and the `BookingProposal` types the panel no
  longer reads.
- Keep `ApproveBooking`, now called by the worker. Remove `RejectBooking`, whose only caller is
  the route. Keep prepare's `has_matching_rejection`: a historical `REJECTED` row still
  suppresses its identical observation, which then reaches NEEDS_OWNER through the grace (rule
  4). None is expected in production (P17).
- A `PENDING` proposal still present at deploy is approved by the first non-dry-run run if it is
  still fresh. Otherwise it becomes `SUPERSEDED` or `EXPIRED` and is prepared again.

**No migration.** An automatic booking is `state='APPROVED'` with
`decided_by='system:auto-booking'` (P13). The read route tells it apart from a manual approval
by `decided_by` alone. Q3 was answered (a): the refusal reason is not stored. It travels in
memory from the sweep to the alert (§ E), so no column is added and nothing is rehearsed.

**Spec deltas, for the tasks to write.**
- venue-close-booking: "Approval Is Manual and Freshness-Checked" becomes "Approval Is Automatic
  and Freshness-Checked". "Admin Endpoints Require the Bearer Token" is reduced to the read
  route, and "Endpoint Status Codes" is removed (Q1). "Rejection Writes Nothing and Requires a
  Reason" is removed (Q1). Added: the automatic actor; Q2's two refusals in "Refusal Logging";
  every refusal returning its code (§ E).
- venue-reconciliation: added "Confirmed Discrepancies Needing the Owner Are Announced" (§ E) and
  "Confirmed Discrepancy Read Endpoint" (§ G).
- `book-venue-closes`' proposal item 1, "Booking is never automatic", is recorded as reversed
  by decision 66.

### G. The API

`GET /reconciliation/confirmed`. It is mounted on the existing reconciliation router, so the
admin bearer applies at router level (`router.py:100-104`). It is read-only and takes no
parameter. It answers for the whole system (Q6, answered (a)).

```
{
  "read_at": "2026-10-16T21:40:03Z",
  "dry_run": false,
  "needs_owner_count": 1,
  "needs_owner": [Discrepancy],
  "being_booked": [Discrepancy],
  "booked": [Booking]
}
Discrepancy = {
  "discrepancy_id", "exchange", "venue", "settlement_currency", "symbol",
  "kind", "reason": "NOT_BOOKABLE" | "SEVERAL_ALLOCATIONS" | "NOT_BOOKED" | null,
  "venue_net_base": "0", "ledger_net_base": "0.5",
  "allocations": [{"allocation_id", "strategy_id", "strategy_name"}],
  "confirmed_at", "last_observed_at"
}
Booking = {
  "proposal_id", "discrepancy_id", "exchange", "venue", "settlement_currency", "symbol",
  "kind", "strategy_id", "strategy_name", "allocation_id", "side", "quantity": "0.5",
  "fill_count", "decided_at", "decided_by": "automatic" | "owner",
  "execution_attempt_id", "discrepancy_open": true
}
```

- `needs_owner_count` equals `len(needs_owner)`. It is served anyway, so the badge does not need
  to know the list's shape, and a test pins the equality.
- Money and quantities are strings, under the rule `BookingProposalView` states
  (`router.py:241-252`).
- `booked` holds every `APPROVED` proposal decided within the retention window, newest first,
  bounded at 100: the last 30 days (Q5, answered (a)), with nothing to mark as seen. `discrepancy_open` says whether the scan has resolved its
  discrepancy yet.
- `dry_run` is `settings.dry_run`, so the view can say that the comparison does not run, rather
  than an all-clear (§ H).
- **Statements.** One for the open `CONFIRMED` discrepancies (the call P19 names); one for
  `APPROVED` proposals that are either within the window or whose discrepancy is open (a new
  read method on the proposal repository); one for strategy names by allocation id (a new
  read-only adapter in `reconciliation/infrastructure`, in the manner of
  `allocation_owner_adapter.py`). There is no statement per row, and T8 pins the count.
- **Levels.** Those of a read model (`performance/application/scope.py:18-24`): WARNING with the
  ids for a fault in stored data, such as an allocation whose strategy row is missing, which is
  then served with `strategy_name: null`. Never ERROR: this route is polled every 60 s per open
  tab, and an ERROR here would flood the alerts that § E relies on.
- `GET /reconciliation/discrepancies` is unchanged.

### H. Frontend

Content and states only; the visual design is prototyped and reviewed with the owner later.

- **API module.** `shared/api/discrepancies.ts`: the fetch, a shape check that refuses the whole
  body if any element is malformed (the rule of `usePendingBookings.ts:7-17` and PR 14's T9), and
  `useConfirmedDiscrepancies` under query key `["reconciliation", "confirmed"]`, refetched every
  60 s and on focus like the open positions. The badge and the page read this one query, so
  they cannot disagree.
- **Navigation.** A fourth item, `{ to: "/discrepancies", labelKey: "discrepancies", end: false }`,
  with a recommended order of Overview, Strategies, Discrepancies, Settings (for the prototype to
  confirm). `SideNav` and `BottomNav` draw a `NavBadge` beside its label. It draws nothing while
  loading, nothing on a failed read, and nothing at zero; otherwise it shows the count, with a
  translated accessible name ("2 discrepancies need you"). It is red (`loss`) with its number
  (Q7, answered (a)). Under decision 65's rule its words are its accessible name and the view
  itself; amber was set aside because it already means dry run. On a phone
  the bottom bar gets four `flex-1` cells, and the Spanish label, "Discrepancias", has to fit;
  the prototype checks it at 375 px.
- **Route.** `discrepancies` in `app/router.tsx`, inside the shell.
- **Page** `features/discrepancies/DiscrepanciesPage.tsx`, in this order: the read state; "Needs
  you" (NEEDS_OWNER); "Being booked" (BEING_BOOKED, only when not empty); "Booked automatically"
  (the `booked` list). Within each list, items are grouped by exchange, whatever exchange tab is
  selected (Q6, answered (a)). The page reads no exchange scope, so a badge of 2 can never sit
  above an empty page. Each discrepancy item carries `id="discrepancy-<discrepancy_id>"` and
  scrolls into view when the hash names it, as the rail does today (`DecisionRail.tsx:72-77`).

| State | What the page says |
| --- | --- |
| First read loading | "Reading discrepancies…" (`role="status"`) |
| First read failed | The error sentence and "Read again" (`role="alert"`), and no list: never "nothing needs you" |
| A later refresh failed | The last lists stay, with "Last read" and since when, in `loss`, as PR 14's example 11d |
| `dry_run` | "The comparison with the venue does not run in dry run, so nothing is checked here." Lists empty. Never an all-clear. |
| Nothing at all | "Nothing needs you. The venue agrees with the ledger on every confirmed comparison." |
| A NEEDS_OWNER item | Pair, pool, the kind in words, both nets, the strategies involved (a name links to the strategy), confirmed since, last compared, and what the owner can do: for `NO_MATCHING_ALLOCATION`, close it on the venue by hand, and the next scan resolves it; for the rest, "Ask for a manual reconciliation" (wording pending the prototype). Red, with these words beside it (decision 65). |
| A BEING_BOOKED item | Neutral in the view: "Being booked automatically." Nothing here needs the owner. The position's venue mark stays red meanwhile (Q8, below), because the position row is what is wrong. |
| A booking | Neutral: side, quantity, pair, strategy, when, "automatically", and "the venue agrees again" once its discrepancy is resolved |

- **Overview.** `DecisionRail` and its slot leave `OverviewPage`. Its three scope messages move
  into the page: scope loading, scope failed, no exchanges (P14). `PoolPanel`'s
  `betweenChartAndGrid` prop goes, since nothing else passes it. The single-column layout is for
  the prototype.
- **The venue line and the venue chip** (`MarkLine.tsx` `VenueLine`, `OpenMarks.tsx` `VenueNote`)
  always link to `{ pathname: "/discrepancies", hash: "#discrepancy-<discrepancy_id>" }`. They no
  longer read proposals; they read `useConfirmedDiscrepancies` (Q8, answered (a)).
  - **While a booking is under way,** the mark stays red, and its words say so: "being booked
    automatically". The row still shows open a position the venue no longer holds.
  - **When the booking lands,** the position leaves the list.
  - **When it cannot be booked,** the mark is already red, and the words become those of its
    NEEDS_OWNER reason.

  The two lines find their discrepancy by `discrepancy_id` in `being_booked` or `needs_owner`.
  PR 14 § K row 22's rule, "until it is read, neither the link nor the words", stays, now applied
  to this query: while it loads, or after it failed, the line draws its red "venue disagrees"
  and its nets, but no claim about booking. A `discrepancy_id` found in neither list, for
  instance one the scan resolved between the two reads, also draws no claim (§ K row 15).
- **Palette.** Tokens only (`index.css:6-34`). Red (`loss`) appears in three places, each
  always with its words: a NEEDS_OWNER item, the nav badge (its words are its accessible name),
  and the venue mark (decision 65). A booking, a result, is never red. `DecisionRail.tsx` leaves
  `AMBER_ALLOWED`, and nothing joins it (Q7).

### I. Texts and i18n keys (draft; approved with the prototype)

Keys under `nav.discrepancies` and `discrepancies.*`, in both locales; the `overview.decisionRail.*`
keys move to `overview.scope.*` for the three messages that stay, and the others are deleted;
`positions.venue.link` is reworded and `positions.venue.noProposal` and
`positions.venue.line.noProposal` are deleted. Draft English, with Spanish written in the
prototype review:

| Key | EN |
| --- | --- |
| `nav.discrepancies` | Discrepancies |
| `discrepancies.badgeName` | {{count}} discrepancy needs you / {{count}} discrepancies need you |
| `discrepancies.kind.NO_MATCHING_ALLOCATION` | The venue holds a position no strategy opened. |
| `discrepancies.kind.AMBIGUOUS_PARTIAL_REDUCE` | The venue reduced a position several strategies share; which one cannot be told. |
| `discrepancies.reason.SEVERAL_ALLOCATIONS` | The venue closed a position several strategies share; one booking cannot split it. |
| `discrepancies.reason.NOT_BOOKED` | Could not be booked automatically. |
| `discrepancies.beingBooked` | Being booked automatically. |
| `discrepancies.booked` | Booked automatically |
| `positions.venue.link` | See the discrepancy |
| `positions.venue.line.beingBooked` | being booked automatically (Q8) |

### J. Layering

- `reconciliation/domain/attention.py`: § D, pure `Decimal` and `datetime`, no framework.
- `reconciliation/application/`: `auto_book_pending.py`, `announce_needs_owner.py`,
  `read_confirmed.py`. Each depends on ports in `application/ports.py`, and none imports
  `ApproveBooking` as a class (C1).
- `reconciliation/domain/booking.py` gains the `BookingRefusal` codes (§ E), pure.
- `reconciliation/infrastructure/`: the route; a strategy-name adapter; and, for Q2, a
  system-order-id adapter over `SqlAlchemyExecutionAttemptRepository`, a type the router already
  imports from `execution` (`router.py:52-54`).
- No module outside `reconciliation` changes on the backend except `main.py`'s wiring and one
  setting.

### K. What fails here without a log line?

| # | Path | What the owner would see with no trace | What this design does |
| --- | --- | --- | --- |
| 1 | A confirmed `AMBIGUOUS` or `NO_MATCHING` | Nothing at all, today (§ B) | One ERROR per discrepancy per process, to Telegram (§ E); the badge |
| 2 | A bookable discrepancy that prepare keeps refusing | A WARNING a minute, which nobody reads | After the grace: NEEDS_OWNER, the badge, and one ERROR carrying the refusal's code (Q3, § E). If no code is known to the process, `REASON_UNKNOWN` points to the log; the item is never dropped. |
| 3 | The booking chain dies | Nothing, and the GHOST refusals go on | The watchdog's ERRORs (P12). The badge does not depend on the chain: the route computes rule 4 from the rows. |
| 4 | An unexpected exception in one approval | — | Propagates, and the job FAILED reaches the watchdog's ERROR (C6) |
| 5 | An approval refused as stale over and over | A WARNING a minute | The same grace: NEEDS_OWNER and one ERROR |
| 6 | **A wrong attribution whose fills sum exactly** (P8) | **Nothing, ever: the booking looks right** | Q2's two refusals (§ C8); every booking listed in the view with its strategy. What is left is § N's first risk. |
| 7 | The Overview with its scope failed, once the rail is gone | The title alone | The three scope messages move into the page (P14); a test per message (T11) |
| 8 | The badge's read fails | No badge, read as "nothing needs you" | The nav cannot say "failed" without becoming a permanent alarm; the page says it; Telegram (§ E) does not depend on the panel |
| 9 | A second announcement inside the throttle window | One alert and a "+1 suppressed" that arrives later, if at all | The daily reminder under its own template (Q4 (b), § E); the badge |
| 10 | Alerting off, or its token missing | No Telegram message | The composition WARNING (`alerting.py:51-60`); the badge; and § M's check before the deploy, which prints only a count |
| 11 | A NEEDS_OWNER discrepancy that resolves itself before the owner looks | An alert about something the page no longer shows | Accepted; the view lists open items only. Its resolution is in the journal (the scan's resolved count). |
| 12 | A booking written, then the venue moves again | The item hidden as "booked" forever | Rule 2 compares the frozen observation with the current one (§ D) |
| 13 | An allocation whose strategy row is missing | An item with no name | `strategy_name: null`, drawn as "unknown strategy"; one WARNING with the allocation id (§ G) |
| 14 | `DRY_RUN` | "Nothing needs you", read as an all-clear | The page says the comparison does not run (§ H) |
| 15 | The venue line before the confirmed-discrepancies read has arrived, after it failed, or for an id in neither list | "Being booked automatically", or a reason nobody read | No claim about booking is drawn; the red "venue disagrees" and the nets stay (§ H, Q8; T11) |

### L. Testing strategy

Strict TDD: each test is seen failing on an ASSERTION before the code exists. A test that passes
at once is proven by breaking what it guards and watching it go red. Symbols cross a module
boundary with a different spelling on each side (`SOLUSDT.P` in, `SOLUSDT` stored).

| # | Test | Layer | What it pins |
| --- | --- | --- | --- |
| T1 | `needs_owner`, table-driven: each kind × one or two allocations × booked current, booked stale observation, unbooked × inside or past the grace × `OBSERVED` or resolved. | domain | § D, rules 1-5; K row 12 |
| T2 | Q2: prepare refuses an increase, a flip, and a fill whose order id a system attempt holds. One WARNING each, no row. The reducing case still prepares. Every refusal branch, old and new, puts its `BookingRefusal` code in `PrepareBookingResult.refusals`. | application, fakes | C8; P8's example; § E |
| T3 | `AutoBookPending` calls `approve` once per `PENDING` proposal, with `system:auto-booking`, and counts outcomes. | application, fakes | C1 |
| T4 | The handler's order: expire, sweep, auto-book, announce, enqueue. Under `DRY_RUN` none of the four is called and the successor is still enqueued. An exception from auto-book propagates and enqueues no successor. | application, fakes | C1, C5, C6 |
| T5 | **End to end on real PostgreSQL:** a confirmed `ATTRIBUTABLE_FULL_CLOSE`, a fake venue fill reader, one job. The proposal is `APPROVED` with `decided_by='system:auto-booking'`; one `VENUE` attempt and N ledger rows exist; the strategy nets to zero. Running the job again writes zero rows. A `PENDING` row left as by a crash is approved by the next run. | integration | C1, C4; spec "Approved Booking Clears the Existing-Position Guard" |
| T6 | **Concurrency, lock-hold harness, real PostgreSQL:** connection 1 holds `SELECT ... FOR UPDATE` on a `PENDING` proposal; the automatic step starts in a task; after a bounded wait `not task.done()`; connection 1 marks it `APPROVED` and commits; the task returns `ALREADY_DECIDED`; exactly one attempt row exists. Proven non-vacuous by removing `with_for_update()` from a copy of the call and watching the wait assertion go red. | integration | C3, C4; reuses `test_approve_booking_integration.py:935`'s harness |
| T7 | The announcement: one ERROR record listing two new NEEDS_OWNER items, each with its reason code and phrase (a `SUM_MISMATCH` from this run's sweep, a `NOT_BOOKABLE` from the row, a `REASON_UNKNOWN` when nothing is known); nothing on the second run; announced again after the item is dropped and returns. Two announcements with different reasons share ONE `record.msg` (the throttle key). The reminder fires after the reminder interval with an injected clock, has a different `record.msg`, lists everything still needing the owner, and does not fire when nothing does. The record's logger is not under `strategy_manager.alerts`, and the message holds no quantity. With a fake `AlertPort` behind a real `AlertLogBridge`, the record is delivered. | application + bridge | § E; K rows 1, 2, 9 |
| T8 | The route: 401 without the bearer; the body's shape; money as strings; `needs_owner_count == len(needs_owner)`; the retention window (30 days, at most 100: Q5); `dry_run`; a missing strategy row gives `strategy_name: null` and one WARNING; statement count is constant in the number of rows. | infrastructure | § G |
| T9 | Q1: approve, reject and the bookings list answer 404/405. | infrastructure | § F |
| T10 | Frontend API module: a well-formed body; a body with one bad element refused whole; a 404 is an error. | frontend | § H |
| T11 | Frontend: `NavBadge` draws nothing at zero, while loading, or on error, and the count with its accessible name otherwise, in both navs. The page in every state of § H's table. `OverviewPage` draws no rail and does draw each of the three scope messages. `VenueLine` and `VenueNote` link to `/discrepancies#discrepancy-<id>` and read no proposals. They say "being booked automatically" for an id in `being_booked`, and the reason's words for an id in `needs_owner`; they make no claim while the query loads, after it failed, or for an id in neither list. The page groups by exchange and ignores the selected tab. The badge is red. | frontend | § H; K rows 7, 8, 14, 15 |
| T12 | `panel-tokens.test.ts`'s allow-list without `DecisionRail.tsx`, with nothing added; every new key present in both locales. | frontend | Palette and i18n rules |

### M. Delivery

One PR, in work units, each gated by `cd backend && uv run ruff check . && uv run mypy src && uv
run pytest --tb=short` and by `npm run lint` and `npm test`:

- **dc.1** The domain rule, the refusal codes, Q2's two refusals, the automatic step, the
  announcement and its reminder, the two settings, and `main.py`'s wiring (T1-T7).
- **dc.2** The read route and the removal of the decision routes (Q1) (T8, T9).
- **dc.3** The API module, the nav item and badge, the page (T10, T11 in part, T12).
- **dc.4** The Overview without the rail, the venue links, and the removal of the bookings feature
  (T11 in part).

Before the deploy, the owner runs a read-only count of `booking_proposals` by state and of open
`reconciliation_discrepancies` by status on the VPS, from a script the tasks hand over, to
confirm P17.

**Are alerts on in production?** Decision 66, Q4, records that this is not verified. Before the
deploy, the owner runs a read-only check that prints only COUNTS, never a line of the file or of
the journal. The tasks write the exact commands; the two forms are:

- a count of the lines of the worker's environment file that set `ALERTS_ENABLED` true and that
  give `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` a non-empty value, for example with
  `grep -c`;
- a count, in the worker's journal since its last start, of the INFO line "operator alerts are
  on" (`alerting.py:101-105`) and of the composition WARNING naming a missing setting
  (`alerting.py:54-59`).

Zero alerts-on lines means § E's messages would reach nobody. Turning alerts on is then the
owner's step, before relying on this unit (§ N, risk 4).

There is no migration (§ F). The deploy that changes `frontend/` repeats task pps.6 (the panel
bundle), and `build.txt` is checked afterwards. While production stays in dry run, everything on
the backend is inert (C5).

**The first automatic booking is a deliberate live test** (Q10, answered (a)): a minimal position
opened through the system and closed by hand on Bybit, with the owner watching the confirmation,
the booking, the view, the badge and the alert. It needs `DRY_RUN=false`, since the scan does not
run in dry run. So it is tied to the owner's separate decision to go live (decision 63), which
Q10 does not take; this design only records it as the first step once live.

### N. Risks, and what could be wrong in this design

1. **A permanent wrong attribution, written with no human read.** The ledger is append-only and
   has no compensating entry (the reason `book-venue-closes` gave for manual booking). The exact
   sum is a strong filter, not proof: P8's example passes it. Q2's two refusals close the cases
   found. Any case not found stays possible, and it would be silent (K row 6).
2. **One poisoned proposal stops every booking** (C6). It is loud, through the watchdog, but
   while it lasts every close is unbooked and GHOST refusals go on. That is preferred over a
   ledger writer that continues past a fault it does not understand.
3. **The alert throttle can swallow a second announcement** for up to 15 min, or until the next
   admitted one (K row 9). The daily reminder, under its own template, bounds that loss to a
   day (Q4).
4. **The owner's "needs you" signal depends on Telegram being configured** (K rows 8, 10). If
   alerts are off on the VPS, the badge is the only signal, which contradicts the owner's goal.
   § M's count check settles it before the deploy.
5. **A NEEDS_OWNER discrepancy has no remedy in the app**: a close by hand on the venue for
   `NO_MATCHING_ALLOCATION`, and assisted manual reconciliation for the rest. No manual path is
   lost, as Q1 recorded: only the kind that is now automatic was ever approvable by hand.
6. **The grace is a judgement.** Too short, and the badge flashes for a booking that would have
   succeeded a minute later. Too long, and a blocked strategy waits unannounced. It is 5 minutes,
   five prepare intervals (Q3), and it is a setting.
7. **An alert's reason is only as good as the process's memory** (§ E). A reason seen by no
   sweep of this process is announced as `REASON_UNKNOWN`. It is never omitted, but then the
   owner needs the log after all.
8. **No live proof yet.** Every test runs against fakes or the local database. Q10 makes the
   first real automatic booking a deliberate one, but only once the owner decides to go live
   (decision 63).

### O. Questions for the owner — answered 2026-10-16

All ten were answered the same day, each as its recommended option, and Q3 with one addition.
The source of truth is decision 66's sub-list "The design's questions (design.md, PR 15
addendum), answered 2026-10-16". The options and tradeoffs that were put to the owner are in
this file's history (the addendum's first writing).

- **Q1 (a)** Remove the approve and reject routes and the bookings screen. A proposal still
  PENDING at deploy is booked automatically if still current, otherwise discarded and prepared
  again. No manual path is lost (§ F).
- **Q2 (a)** Refuse a difference that grows or flips the position, and fills whose order id
  belongs to an order this system placed. Either refusal makes the discrepancy need the owner,
  with its alert (§ C8, § D rule 4).
- **Q3 (a), plus one addition.** Counts after a 5-minute grace, shown as "Could not be booked
  automatically". The reason is not stored, so there is no migration, but the alert that
  announces it carries the reason (§ D, § E).
- **Q4 (b)** One Telegram message per discrepancy per start of the worker, plus a daily reminder
  while anything needs the owner. Whether alerts are on in production is checked before the
  deploy with a command that prints only a count (§ E, § M).
- **Q5 (a)** Automatic bookings of the last 30 days, at most 100. Nothing to mark as seen (§ G).
- **Q6 (a)** The whole system, grouped by exchange, whatever tab is selected (§ G, § H).
- **Q7 (a)** A red badge with its number; its words are its accessible name and the view (§ H).
- **Q8 (a)** The venue mark stays red while being booked, its words saying "being booked
  automatically" (§ H).
- **Q9 (a)** A full close over several open allocations stays unbookable and needs the owner,
  with its alert. This corrects what the owner was told before the design (P6, § D rule 3).
- **Q10 (a)** The first automatic booking is a deliberate live test. It is tied to the owner's
  decision to go live (decision 63), which this answer does not take (§ M).

Never asked, because a decision or the code answers it: that only CONFIRMED discrepancies are
shown (decision 66); that automatic bookings never count in the badge (decision 66); that
nothing is booked for the two ambiguous kinds (decision 66); that booking stays refused in dry
run (spec "DRY_RUN Refuses Booking Entirely"); that no pool lock is taken (P5, C3); that no
quantity or price is written to an alert (§ G levels, PR 14 § K).

