# Strategy Manager

Manage TradingView strategies and execute their webhook signals directly against
the Pionex API, so strategies compete for available account capital instead of
each locking a fixed share inside a Pionex bot.

## Status

**Backend allocation engine complete** (239 tests, ruff and mypy strict clean).
Webhook ingress, job queue, capital allocation, execution and the append-only
ledger are all built and covered.

Not built yet:

- **The frontend.** Strategies view, dashboard and settings are still the Vite
  scaffold.
- **Live trading by default.** `DRY_RUN` defaults to true, and it is a brake
  for everyone: every opening runs in simulation against `FakeExchangeAdapter`,
  while a real position already open still closes for real. With it false, each
  user's mode decides, and a new user starts in simulation. The live Bybit and
  Binance futures adapters are always registered; the Pionex adapters are
  complete but deliberately not registered, because Pionex offers no futures
  order placement over its API.

See [the archived change](./openspec/changes/archive/2026-08-18-allocation-engine/archive-report.md)
for what shipped, the decisions behind it, and the known gaps.

## Requirements

- Python 3.12 (installed automatically by `uv`)
- Node.js 20+
- PostgreSQL 17 (a local `postgresql-x64-17` service, or `docker-compose.yml`)

## Setup

```bash
# 1. Create the role and databases (once, as a superuser)
#
#    Create the ROLE FIRST and let it own everything. Migrations run
#    ALTER TABLE ... ADD CONSTRAINT, and the integration tests run TRUNCATE.
#    PostgreSQL requires table OWNERSHIP for both — write privileges are not
#    enough. If the tables are created by one role and the app then connects
#    as another, migrations fail with "must be owner of table".
psql -U postgres -c "CREATE ROLE strategy_manager WITH LOGIN CREATEDB PASSWORD 'pick-a-strong-one';"
psql -U postgres -c "CREATE DATABASE strategy_manager OWNER strategy_manager;"
psql -U postgres -c "CREATE DATABASE strategy_manager_test OWNER strategy_manager;"
psql -U postgres -d strategy_manager      -c "ALTER SCHEMA public OWNER TO strategy_manager;"
psql -U postgres -d strategy_manager_test -c "ALTER SCHEMA public OWNER TO strategy_manager;"

#    Already have tables owned by postgres? Transfer them instead:
#    ALTER TABLE <each> OWNER TO strategy_manager;

# 2. Configure
cp .env.example backend/.env     # then fill DATABASE_URL, WEBHOOK_SECRET,
#                                  ADMIN_EMAIL, MASTER_ENCRYPTION_KEY —
#                                  the API refuses to start without them.
#                                  The panel is signed in by Cloudflare
#                                  Access: production sets ACCESS_TEAM_DOMAIN
#                                  and ACCESS_AUD; a local dry run sets
#                                  DEV_USER_EMAIL (to ADMIN_EMAIL) instead

# 3. Backend
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn strategy_manager.main:app --reload

# 4. Worker (separate terminal) — the API only persists signals and returns
#    inside TradingView's 3-second budget. Allocation, execution, ledger
#    writes, reservation expiry and balance syncing all happen here, so
#    nothing is traded while this process is not running.
cd backend
uv run python -m strategy_manager.worker

# 5. Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Backend runs on `http://localhost:8000`, frontend on `http://localhost:5173`
with `/api` proxied to the backend.

## Tests

```bash
cd backend  && uv run pytest && uv run ruff check . && uv run mypy src
cd frontend && npm run lint && npm test
```

`DRY_RUN` defaults to true and no test requires a real API credential.

## Documentation

Architecture, layering rules and the non-negotiable safety rules live in
[CLAUDE.md](./CLAUDE.md).
