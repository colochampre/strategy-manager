# Strategy Manager

Personal web app that manages TradingView strategies and executes their webhook
signals directly against the Pionex API, replacing Pionex signal bots so that
capital is no longer locked per bot.

## The problem this solves

Pionex bots require assigning a fixed share of account capital per bot, locked
for that bot's exclusive use. With several strategies signalling alternately,
each one can only push the account with its own fraction while the rest sits
idle. This app lets every strategy compete for up to 100% of *available*
capital instead.

## Commands

| Task | Command |
| --- | --- |
| Backend tests | `cd backend && uv run pytest` |
| Backend lint | `cd backend && uv run ruff check .` |
| Backend typecheck | `cd backend && uv run mypy src` |
| Backend dev server | `cd backend && uv run uvicorn strategy_manager.main:app --reload` |
| Worker process | `cd backend && uv run python -m strategy_manager.worker` |
| Migrations | `cd backend && uv run alembic upgrade head` |
| Frontend tests | `cd frontend && npm test` |
| Frontend typecheck | `cd frontend && npm run lint` |
| Frontend dev server | `cd frontend && npm run dev` |

## Stack

- **Backend:** FastAPI, Python 3.12 (pinned via uv), SQLAlchemy 2.0 async,
  Alembic, PostgreSQL 17, pytest, ruff, mypy strict.
- **Frontend:** Vite 6, React 19, TypeScript strict, Tailwind 4, TanStack Query,
  Zustand, react-i18next (EN/ES), Recharts 3, Vitest.
- **Job queue:** PostgreSQL `FOR UPDATE SKIP LOCKED`. No Redis, no Celery.
- **Database:** the local `postgresql-x64-17` Windows service. `docker-compose.yml`
  exists only as an alternative for machines without it.

## Architecture

Modular monolith, hexagonal per module, screaming at the top level:

```
backend/src/strategy_manager/
  strategies/   allocation/   execution/
  ledger/       accounts/     signals/     shared/
```

Each module has `domain/`, `application/`, `infrastructure/`.

**Layering rules:**

- `domain/` imports no framework — no FastAPI, no SQLAlchemy, no httpx.
- `application/` orchestrates domain objects through ports.
- `infrastructure/` holds adapters: Pionex clients, SQLAlchemy models, routers.
- Pionex and TradingView are adapters, never the centre. The allocation engine
  must survive swapping the exchange.

## Non-negotiable rules

These exist because this system moves real money.

1. **`DRY_RUN` defaults to true.** No test may require a real API credential.
2. **Every signal carries an idempotency key.** A duplicated webhook without one
   is a doubled position.
3. **The webhook endpoint never executes trades.** TradingView cancels any
   request over 3 seconds. Ingress validates, persists, returns 200. A worker
   does the rest.
4. **Allocation is a transaction, not a calculation.** Availability read,
   allocation decision and reservation write happen inside one transaction,
   serialized with `pg_advisory_xact_lock` keyed by `(venue, settlement_currency)`.
5. **Capital pools are per settlement currency.** Spot USDT, USDT-M margin and
   COIN-M wallets are separate balances that cannot fund each other. There is no
   single "account capital" number.
6. **The ledger is append-only.** Every fill records `strategy_id` and
   `allocation_id`. Positions are a projection. PnL and every dashboard
   timeframe are queries over it.
7. **PnL is read in native settlement currency.** USDT-M in USDT, COIN-M in
   BTC/ETH. No blended cross-pool total. The USD rate at fill time is stored
   anyway — it can never be backfilled.
8. **API credentials are envelope-encrypted at rest**, decrypted only in the
   worker at signing time, and never returned to the client beyond a last-4 hint.

## External constraints (verified 2026-08-11)

- **TradingView:** cancels requests over 3s; ports 80/443 only; no IPv6; posts
  from `52.89.214.238`, `34.212.75.30`, `54.218.53.128`, `52.32.178.7`; requires
  2FA and a paid plan; provides no request signing.
- **Pionex spot:** `https://api.pionex.com`, paths `/api/v1/`. HMAC-SHA256,
  headers `PIONEX-KEY` / `PIONEX-SIGNATURE`, `timestamp` in ms valid ±20s.
- **Pionex futures:** account and trade paths `/uapi/v1/` — a different base
  path, so a separate adapter. But the perpetual catalogue and risk table are
  served from the *spot* namespace: `/api/v1/common/symbols?type=PERP` and
  `/api/v1/common/riskTable`. Symbols are suffixed `_PERP`.
  Margin mode CROSS / ISOLATED is a **per-symbol setting**
  (`/uapi/v1/trade/isolatedMode`), not an order parameter. Leverage is
  per symbol too (`/uapi/v1/account/leverage`). Position mode
  (`/uapi/v1/account/positionMode`) is account-wide: `BUYSELL` one-way or
  `OPENCLOSE` hedged.

### Where the futures docs are wrong (verified live 2026-08-24)

The published reference disagrees with the venue in two places, and both fail
silently rather than loudly:

- Contract type arrives as `type: "PERP"`, **not** `contractType: "PERPETUAL"`.
  Reading the documented name yields `None` for all 603 markets.
- `GET /uapi/v1/account/leverage` answers with a `leverages` **list** even for
  a single-symbol query, not the documented flat `{symbol, leverage}` object.
  Match the entry by symbol; taking index 0 reads another market's leverage.
- The `POST` to that same path answers the flat `{symbol, leverage}` object the
  GET was documented to return. Read and write shapes are not symmetric.
- `POST /uapi/v1/trade/isolatedMode` accepts `ISOLATED`, the value the GET
  reports — not the `ISOLATED_BOTH` the models page lists.
- The same concept is spelled differently by endpoint. `GET
  /uapi/v1/trade/isolatedMode` answers `ISOLATED` for a symbol, while a
  POSITION object from `/uapi/v1/account/positions` reports `ISOLATED_BOTH`.
  Do not compare the two values for equality.

## Futures execution (USDT-M)

Futures orders are `MARKET_QTY`, sized in **base size** both ways — there is
no quote-amount market order as on spot. So futures has its own order type
(`FuturesMarketOrder`), not extra variants of spot's `MarketBuy | MarketSell`.

**The granted amount is MARGIN.** Pool availability is read from the futures
wallet, which holds margin, so `size = granted * leverage / price` at the
leverage the venue reports for that symbol. Reading it as notional would
deploy one leverage-th of the reserved capital. The leverage is read at
order-build time, recorded on the execution attempt, and the order is refused
if it cannot be read — never defaulted.

Confirmed against Pionex's own interface (2026-08-25). A position opened by
hand at 7.50 USDT of margin and 2x on ETH at 2467 became `0.006` ETH —
`7.50 * 2 / 2467 = 0.00608`, floored to the `0.001` step. The adapter
reproduces that number exactly, so the venue sizes a margin amount the same
way this system does.

Under ISOLATED margin the open position's margin leaves `free`, and
`PionexBalanceReader` reads `free - debts`, so capital backing an open
position is correctly excluded from pool availability.

Every use case selects its adapter through `VenueExchangeRegistry`, keyed by
`venue`. An unserved venue raises; there is no fallback, because a fallback is
the failure being prevented.

The account must be in `BUYSELL` (one-way) mode. A hedged account is refused
before any order is sent: `reduceOnly` only applies in one-way mode, and
without it every close can open a fresh position on the other side.

## Credentials: two keys, and they are not interchangeable

`.env` holds the **read-only** key (`***Swka`). The encrypted vault holds the
**trade** key (`***nedr`), and that is the one the worker signs with. A write
refused because the wrong key was used answers `AUTH_UNAVAILABLE` — exactly
what a venue that forbids the write answers — so any probe that writes must
load from the vault (`scripts/probe_credentials.py`) and print which key it is
running as. That confusion already produced one wrong conclusion.

## Open risks

- **Pionex does not allow this user to trade futures over the API.** An
  order is refused with `TRADE_TYPE_DENIED` / "user denied not in whitelist"
  (verified 2026-08-25). Funding the wallet changes nothing: the gate is
  reached before the payload or the balance is consulted.

  It is NOT the key and NOT an IP allowlist. `scripts/check_pionex_trade_
  permission.py` sends the same key at both APIs with deliberately unfillable
  orders and separates the cases:

  ```
  SPOT     TRADE_AMOUNT_FILTER_DENIED   -> reached field validation
  FUTURES  TRADE_TYPE_DENIED            -> refused earlier, per user
  ```

  Spot parsed and validated its order, so the key trades from this IP over the
  API. Futures never mentioned the size, which was itself below the minimum.
  The key carries every permission Pionex offers and no IP restriction, and
  the owner trades futures by hand — so this is an account-level API
  entitlement, consistent with the docs index labelling the futures section
  "Internal". It has to be requested from Pionex; there is no toggle for it.
- **No futures order has ever reached validation.** Sizing, rounding, limits,
  the order-not-found code and both close directions are verified against live
  reads (`scripts/check_pionex_futures_sizing.py` builds the real order and
  prints it without sending). `MARKET_QTY`, `size` and `reduceOnly` are still
  unexercised on the wire, as is the futures fill payload.
- Leverage and margin mode ARE writable, verified 2026-08-25 with the vault's
  trade key against an empty wallet with no open positions. The system still
  only reads them; nothing sets them.
- A REVERSE still ends flat, not flipped. The venue is no longer the blocker —
  futures holds either side. The close's proceeds are not spendable until it
  settles and the balance snapshot refreshes, so the second half needs a job
  after settlement, not a retry.
- COIN-M is reachable: the catalogue lists 43 non-USDT-settled perpetuals
  across 22 settlement currencies. It reaches the same `/uapi/v1/` API, but
  those currencies are not in the `Currency` enum or the `capital_pools`
  CHECK constraint, so the futures adapter declares `usdt-m` only.

## Conventions

- All code, comments, identifiers, UI copy and docs are in English.
- UI strings go through i18n (EN/ES); never hardcode display text.
- Tailwind: no hex colours and no `var()` inside `className`. The palette is
  defined once in `frontend/src/index.css` under `@theme`.
