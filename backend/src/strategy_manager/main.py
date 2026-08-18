"""FastAPI application entrypoint.

Module routers are mounted here as they are built. The application owns all
business logic, authentication and secrets; the frontend is a pure client.
"""

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.accounts.infrastructure.pool_repository import CapitalPoolRepository
from strategy_manager.allocation.application.allocate_capital import AllocateCapital
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.lock_key_invariant import (
    assert_pool_lock_keys_distinct,
)
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.allocation.infrastructure.reservation_gateway import (
    ReservationGatewayAdapter,
)
from strategy_manager.execution.application.execute_reservation import ExecuteReservation
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import engine, session_factory
from strategy_manager.shared.domain.money import Currency
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.usd_rate import FixedUsdRateProvider
from strategy_manager.shared.infrastructure.worker_runner import JobHandler, WorkerRunner
from strategy_manager.signals.application.process_signal import ProcessSignalHandler
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository
from strategy_manager.signals.infrastructure.router import router as signals_router
from strategy_manager.signals.infrastructure.signal_context import SignalContextAdapter
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository


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


def _build_process_signal_handler(
    session: AsyncSession,
    pools_by_key: Mapping[tuple[str, str], PoolConfig],
    reservation_ttl_seconds: int,
) -> ProcessSignalHandler:
    """Composes ``AllocateCapital`` (slice 4) and ``ExecuteReservation``
    (slice 5) into the ``signal.process`` job handler (design.md's job
    handlers table). Only ``FakeExchangeAdapter``/``FakeBalanceSource`` are
    registered in this change — a real Pionex adapter is future scope, kept
    swappable behind ``ExchangePort``/``BalanceSourcePort``."""

    strategy_repository = SqlAlchemyStrategyRepository(session)
    signal_repository = SqlAlchemySignalRepository(session)
    reservation_repository = SqlAlchemyReservationRepository(session)

    signal_context = SignalContextAdapter(
        signals=signal_repository,
        strategies=strategy_repository,
        reservations=reservation_repository,
    )

    allocate_capital = AllocateCapital(
        strategy_policy=StrategyPolicyAdapter(strategy_repository),
        pool_balance=PoolBalanceAdapter(pools_by_key, FakeBalanceSource()),
        lock=PgAdvisoryLockAdapter(session),
        reservations=reservation_repository,
        commit=session,
        clock=SystemClock(),
        reservation_ttl_seconds=reservation_ttl_seconds,
    )

    execute_reservation = ExecuteReservation(
        reservations=ReservationGatewayAdapter(reservation_repository),
        exchange=FakeExchangeAdapter(),
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        fill_recorder=RecordFill(SqlAlchemyLedgerRepository(session)),
        usd_rate_provider=FixedUsdRateProvider({Currency.USDT: Decimal("1")}),
        clock=SystemClock(),
        commit=session,
    )

    return ProcessSignalHandler(
        signal_context=signal_context,
        allocate_capital=allocate_capital,
        execute_reservation=execute_reservation,
    )


def build_worker_runner(
    pools: Sequence[PoolConfig],
    *,
    session_factory_override: async_sessionmaker[AsyncSession] | None = None,
) -> WorkerRunner:
    """Registers ``signal.process`` — the only job kind this change adds a
    handler for (``reservation.sweep`` is slice 6). One fresh session per
    claimed job, independent of the claim session (design.md § Transaction
    Boundaries: the claim's row lock must die with its own connection)."""

    settings = get_settings()
    factory = session_factory_override or session_factory
    pools_by_key = {
        (pool.venue.value, pool.settlement_currency.value): pool for pool in pools
    }

    async def handle_signal_process(job: ClaimedJob) -> None:
        signal_id = UUID(str(job.payload["signal_id"]))
        async with factory() as session:
            handler = _build_process_signal_handler(
                session, pools_by_key, settings.reservation_ttl_seconds
            )
            await handler.handle(signal_id)

    @asynccontextmanager
    async def queue_factory() -> AsyncIterator[PostgresJobQueue]:
        async with factory() as session:
            yield PostgresJobQueue(session)

    handlers: Mapping[JobKind, JobHandler] = {JobKind.SIGNAL_PROCESS: handle_signal_process}
    return WorkerRunner(
        queue_factory=queue_factory,
        handlers=handlers,
        poll_interval_seconds=settings.worker_poll_interval_seconds,
    )


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
