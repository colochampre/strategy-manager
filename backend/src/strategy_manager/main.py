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

from strategy_manager.accounts.application.balance_sync_handler import BalanceSyncHandler
from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.application.sync_balances import SyncBalances
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.balance_snapshot_repository import (
    SqlAlchemyBalanceSnapshotRepository,
)
from strategy_manager.accounts.infrastructure.credential_vault import (
    SqlAlchemyCredentialVault,
)
from strategy_manager.accounts.infrastructure.db_balance_source import DbBalanceSource
from strategy_manager.accounts.infrastructure.pionex_balance_reader import (
    PionexBalanceReader,
)
from strategy_manager.accounts.infrastructure.pool_repository import CapitalPoolRepository
from strategy_manager.allocation.application.allocate_capital import AllocateCapital
from strategy_manager.allocation.application.expire_reservations import ExpireReservations
from strategy_manager.allocation.application.sweep_handler import SweepHandler
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.lock_key_invariant import (
    assert_pool_lock_keys_distinct,
)
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.allocation.infrastructure.reservation_gateway import (
    ReservationGatewayAdapter,
)
from strategy_manager.execution.application.place_order import PlaceOrder
from strategy_manager.execution.application.ports import ExchangePort
from strategy_manager.execution.application.settle_execution import SettleExecution
from strategy_manager.execution.infrastructure.dry_run_invariant import assert_dry_run_safe
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.db import engine, session_factory
from strategy_manager.shared.domain.money import Currency
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import EnvelopeCipher
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.pionex import EXCHANGE as PIONEX_EXCHANGE
from strategy_manager.shared.infrastructure.pionex.factory import read_only_client
from strategy_manager.shared.infrastructure.pionex.signer import PionexCredentials
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
    settings: Settings,
    exchange: ExchangePort,
) -> ProcessSignalHandler:
    """Composes ``AllocateCapital`` (slice 4) and ``ExecuteReservation``
    (slice 5) into the ``signal.process`` job handler (design.md's job
    handlers table).

    ``BalanceSourcePort`` is now bound to ``DbBalanceSource``, which reads the
    snapshot the ``balance.sync`` job writes. It reads locally on purpose:
    this runs inside the pool's advisory lock, where a remote call would
    serialize every allocation on that pool behind exchange latency.

    ``ExchangePort`` is still ``FakeExchangeAdapter`` — order submission
    against a real venue is future scope, kept swappable behind the port. It
    is passed in rather than built here because one instance is shared with
    the ``execution.settle`` handler: placing and settling are two jobs
    talking about the same order."""

    strategy_repository = SqlAlchemyStrategyRepository(session)
    signal_repository = SqlAlchemySignalRepository(session)
    reservation_repository = SqlAlchemyReservationRepository(session)

    signal_context = SignalContextAdapter(
        signals=signal_repository,
        strategies=strategy_repository,
        reservations=reservation_repository,
    )

    strategy_policy = StrategyPolicyAdapter(strategy_repository)
    pool_balance = PoolBalanceAdapter(
        pools_by_key,
        DbBalanceSource(
            session,
            SystemClock(),
            max_age_seconds=settings.balance_snapshot_max_age_seconds,
        ),
    )

    allocate_capital = AllocateCapital(
        strategy_policy=strategy_policy,
        pool_balance=pool_balance,
        lock=PgAdvisoryLockAdapter(session),
        reservations=reservation_repository,
        commit=session,
        clock=SystemClock(),
        reservation_ttl_seconds=settings.reservation_ttl_seconds,
    )

    place_order = PlaceOrder(
        reservations=ReservationGatewayAdapter(reservation_repository),
        exchange=exchange,
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        queue=PostgresJobQueue(session),
        clock=SystemClock(),
        commit=session,
        settle_delay_seconds=settings.execution_settle_delay_seconds,
    )

    return ProcessSignalHandler(
        signal_context=signal_context,
        strategy_policy=strategy_policy,
        pool_balance=pool_balance,
        allocate_capital=allocate_capital,
        place_order=place_order,
    )


def _build_settle_execution(
    session: AsyncSession, exchange: ExchangePort
) -> SettleExecution:
    """Composes the ``execution.settle`` job's use case: ask the exchange what
    the order became, and write it to the append-only ledger."""
    return SettleExecution(
        reservations=ReservationGatewayAdapter(
            SqlAlchemyReservationRepository(session)
        ),
        exchange=exchange,
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        fill_recorder=RecordFill(SqlAlchemyLedgerRepository(session)),
        usd_rate_provider=FixedUsdRateProvider({Currency.USDT: Decimal("1")}),
        clock=SystemClock(),
        commit=session,
    )


def build_worker_runner(
    pools: Sequence[PoolConfig],
    *,
    session_factory_override: async_sessionmaker[AsyncSession] | None = None,
) -> WorkerRunner:
    """Registers ``signal.process``, ``reservation.sweep`` and
    ``balance.sync``. One fresh session per claimed job, independent of the
    claim session (design.md § Transaction Boundaries: the claim's row lock
    must die with its own connection).

    Both recurring chains keep themselves alive by enqueuing their own
    successor, so each needs an initial job before it runs at all. Seeding is
    ``RecurringJobSeeder``'s job, called by the worker entrypoint — registering
    a handler here does not start its chain."""

    settings = get_settings()
    factory = session_factory_override or session_factory
    pools_by_key = {
        (pool.venue.value, pool.settlement_currency.value): pool for pool in pools
    }

    # One adapter instance for the worker's whole life: placing and settling
    # are separate jobs that must agree about the same order.
    exchange: ExchangePort = FakeExchangeAdapter()

    # This is the composition root the DRY_RUN invariant names: the one place
    # that knows which ExchangePort adapter is actually registered
    # (spec: trade-execution § DRY_RUN Safety).
    assert_dry_run_safe(dry_run=settings.dry_run, exchange=exchange)

    # Built once at startup so a missing or malformed MASTER_ENCRYPTION_KEY
    # fails here rather than on the first job that needs a credential.
    cipher = EnvelopeCipher.from_base64(settings.master_encryption_key)

    async def handle_signal_process(job: ClaimedJob) -> None:
        signal_id = UUID(str(job.payload["signal_id"]))
        async with factory() as session:
            handler = _build_process_signal_handler(
                session, pools_by_key, settings, exchange
            )
            await handler.handle(signal_id)

    async def handle_execution_settle(job: ClaimedJob) -> None:
        attempt_id = UUID(str(job.payload["execution_attempt_id"]))
        async with factory() as session:
            await _build_settle_execution(session, exchange).settle(attempt_id)

    async def handle_balance_sync(job: ClaimedJob) -> None:
        # The HTTP client is built per job rather than held open across the
        # worker's life: a sync runs every few seconds, so the reconnect is
        # cheap, and no socket outlives the job that opened it.
        async with factory() as session:
            # Decrypted here and used immediately — the plaintext lives only
            # for the length of this call (CLAUDE.md rule 8).
            credential = await SqlAlchemyCredentialVault(
                session, cipher, SystemClock()
            ).load(PIONEX_EXCHANGE)

            async with read_only_client(
                settings,
                PionexCredentials(
                    api_key=credential.api_key, api_secret=credential.api_secret
                ),
            ) as client:
                handler = BalanceSyncHandler(
                    sync_balances=SyncBalances(
                        pools=list(pools_by_key),
                        reader=PionexBalanceReader(client, SystemClock()),
                        snapshots=SqlAlchemyBalanceSnapshotRepository(session),
                        commit=session,
                    ),
                    queue=PostgresJobQueue(session),
                    clock=SystemClock(),
                    interval_seconds=settings.balance_sync_interval_seconds,
                )
                await handler.handle(job)
                await session.commit()

    async def handle_reservation_sweep(job: ClaimedJob) -> None:
        # The sweep and its self-re-enqueue share one session, so a successor
        # is never committed unless the sweep it follows committed too.
        async with factory() as session:
            handler = SweepHandler(
                expire_reservations=ExpireReservations(
                    reservations=SqlAlchemyReservationRepository(session),
                    clock=SystemClock(),
                    commit=session,
                ),
                queue=PostgresJobQueue(session),
                clock=SystemClock(),
                poll_interval_seconds=settings.worker_poll_interval_seconds,
            )
            await handler.handle(job)
            await session.commit()

    @asynccontextmanager
    async def queue_factory() -> AsyncIterator[PostgresJobQueue]:
        async with factory() as session:
            yield PostgresJobQueue(session)

    handlers: Mapping[JobKind, JobHandler] = {
        JobKind.SIGNAL_PROCESS: handle_signal_process,
        JobKind.RESERVATION_SWEEP: handle_reservation_sweep,
        JobKind.BALANCE_SYNC: handle_balance_sync,
        JobKind.EXECUTION_SETTLE: handle_execution_settle,
    }
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
