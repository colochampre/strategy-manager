# Strategy Manager

Manage TradingView strategies and execute their webhook signals directly against
the Pionex API, so strategies compete for available account capital instead of
each locking a fixed share inside a Pionex bot.

## Status

Scaffold. No exchange-facing code yet — the allocation engine is the first
feature to be built.

## Requirements

- Python 3.12 (installed automatically by `uv`)
- Node.js 20+
- PostgreSQL 17 (a local `postgresql-x64-17` service, or `docker-compose.yml`)

## Setup

```bash
# 1. Create the database (once)
createdb strategy_manager        # or: psql -U postgres -c "CREATE DATABASE strategy_manager;"

# 2. Configure
cp .env.example backend/.env     # then fill DATABASE_URL, WEBHOOK_SECRET, MASTER_ENCRYPTION_KEY

# 3. Backend
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn strategy_manager.main:app --reload

# 4. Frontend (separate terminal)
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
