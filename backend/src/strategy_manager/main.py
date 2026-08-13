"""FastAPI application entrypoint.

Module routers are mounted here as they are built. The application owns all
business logic, authentication and secrets; the frontend is a pure client.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from strategy_manager.accounts.infrastructure.pool_repository import CapitalPoolRepository
from strategy_manager.allocation.infrastructure.lock_key_invariant import (
    assert_pool_lock_keys_distinct,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import engine
from strategy_manager.signals.infrastructure.router import router as signals_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup invariant 1 (design.md § Composition Root): ``capital_pools``
    is the single source of truth for which pools exist — enumerate it and
    assert every pool's advisory-lock key pair is distinct before accepting
    traffic."""

    async with engine.connect() as conn:
        pools = await CapitalPoolRepository(conn).list_enabled()
        await assert_pool_lock_keys_distinct(conn, pools)
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Strategy Manager",
        version="0.1.0",
        summary="Capital-allocation engine for TradingView strategies executing on Pionex",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str | bool]:
        return {"status": "ok", "dry_run": settings.dry_run}

    app.include_router(signals_router)

    return app


app = create_app()
