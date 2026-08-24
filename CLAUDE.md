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

## Open risks

- Futures order sizing is by **base size** (`size`) with order type
  `MARKET_QTY`. There is no quote-amount market order as on spot, where a BUY
  sends `amount`. `OrderRequest` cannot be reused unchanged.
- Setting leverage and margin mode is unproven. Reading both works against a
  live account; neither `POST` has been exercised.
- COIN-M is reachable after all: the catalogue lists 43 non-USDT-settled
  perpetuals across 22 settlement currencies (BTC, ETH, SOL and others). Still
  implement USDT-M first, but the venue abstraction now has a confirmed second
  settlement currency to serve, not a hypothetical one.

## Conventions

- All code, comments, identifiers, UI copy and docs are in English.
- UI strings go through i18n (EN/ES); never hardcode display text.
- Tailwind: no hex colours and no `var()` inside `className`. The palette is
  defined once in `frontend/src/index.css` under `@theme`.
