"""FastAPI application entrypoint.

Module routers are mounted here as they are built. The application owns all
business logic, authentication and secrets; the frontend is a pure client.
"""

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.balance_sync_handler import BalanceSyncHandler
from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.application.ports import ExchangeBalanceReaderPort
from strategy_manager.accounts.application.refresh_pool_balance import RefreshPoolBalance
from strategy_manager.accounts.application.sync_balances import (
    CompositeBalanceSync,
    SyncBalances,
)
from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.balance_snapshot_repository import (
    SqlAlchemyBalanceSnapshotRepository,
)
from strategy_manager.accounts.infrastructure.binance_balance_reader import (
    BinanceBalanceReader,
)
from strategy_manager.accounts.infrastructure.bybit_balance_reader import (
    BybitBalanceReader,
)
from strategy_manager.accounts.infrastructure.credential_vault import (
    CredentialNotFound,
    SqlAlchemyCredentialVault,
)
from strategy_manager.accounts.infrastructure.credentials_router import (
    router as credentials_router,
)
from strategy_manager.accounts.infrastructure.db_balance_source import (
    DbBalanceSnapshotAge,
    DbBalanceSource,
)
from strategy_manager.accounts.infrastructure.key_coverage import (
    UserExchange,
    read_key_coverage,
)
from strategy_manager.accounts.infrastructure.pool_repository import CapitalPoolRepository
from strategy_manager.accounts.infrastructure.pool_status_adapter import SqlAlchemyPoolStatus
from strategy_manager.accounts.infrastructure.pools_router import router as pools_router
from strategy_manager.accounts.infrastructure.reader_by_exchange import (
    ReaderByExchange,
    ReaderFactory,
)
from strategy_manager.accounts.infrastructure.stale_snapshot_reader import (
    SqlAlchemyStaleSnapshotReader,
)
from strategy_manager.accounts.infrastructure.trade_capability_adapter import (
    DryRunTradeCapability,
    VaultTradeCapabilityAdapter,
)
from strategy_manager.allocation.application.allocate_capital import AllocateCapital
from strategy_manager.allocation.application.expire_reservations import ExpireReservations
from strategy_manager.allocation.application.sweep_handler import SweepHandler
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.lock_key_invariant import (
    PoolLockKeyCollisionError,
    assert_pool_lock_keys_distinct,
)
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.allocation.infrastructure.reservation_gateway import (
    ReservationGatewayAdapter,
)
from strategy_manager.execution.application.assert_mode_matches_ledger import (
    assert_mode_matches_ledger,
)
from strategy_manager.execution.application.close_position import ClosePosition
from strategy_manager.execution.application.place_order import PlaceOrder
from strategy_manager.execution.application.ports import (
    ExchangePort,
    ExchangeRegistryPort,
)
from strategy_manager.execution.application.settle_execution import SettleExecution
from strategy_manager.execution.infrastructure.binance_futures_exchange import (
    BinanceFuturesExchangeAdapter,
)
from strategy_manager.execution.infrastructure.bybit_futures_exchange import (
    BybitFuturesExchangeAdapter,
)
from strategy_manager.execution.infrastructure.dry_run_invariant import assert_dry_run_safe
from strategy_manager.execution.infrastructure.exchange_registry import (
    VenueExchangeRegistry,
)
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.fake_venue_book import FakeVenueBook
from strategy_manager.execution.infrastructure.mode_origin_reader import (
    SqlAlchemyModeOriginReader,
)
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.execution.infrastructure.simulated_fee_rates import (
    SIMULATED_TAKER_FEE_RATES,
)
from strategy_manager.execution.infrastructure.venue_support import (
    describe_unserved,
    unserved_pools,
)
from strategy_manager.identity.infrastructure.identity_invariant import (
    assert_identity_configured,
)
from strategy_manager.identity.infrastructure.me_router import router as me_router
from strategy_manager.ledger.application.read_held_base import ReadHeldBase
from strategy_manager.ledger.application.read_recorded_fill_ids import ReadRecordedFillIds
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.application.read_symbol_positions import ReadSymbolPositions
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.performance.infrastructure.open_positions_router import (
    router as open_positions_router,
)
from strategy_manager.performance.infrastructure.performance_router import (
    router as performance_router,
)
from strategy_manager.reconciliation.application.announce_needs_owner import AnnounceNeedsOwner
from strategy_manager.reconciliation.application.approve_booking import ApproveBooking
from strategy_manager.reconciliation.application.auto_book_pending import AutoBookPending
from strategy_manager.reconciliation.application.booking_prepare_handler import (
    BookingPrepareHandler,
)
from strategy_manager.reconciliation.application.expire_booking_proposals import (
    ExpireBookingProposals,
)
from strategy_manager.reconciliation.application.ports import (
    PoolKey,
    VenueFill,
    VenueFillReaderPort,
    VenueFillReaderRegistryPort,
    VenueFillReadError,
    VenuePositionReaderPort,
    VenuePositionReaderRegistryPort,
)
from strategy_manager.reconciliation.application.prepare_booking import PrepareBooking
from strategy_manager.reconciliation.application.reconciliation_scan_handler import (
    ReconciliationScanHandler,
    ScanPoolsPort,
)
from strategy_manager.reconciliation.application.scan_pools import ScanPools
from strategy_manager.reconciliation.application.scan_users import ScanUsers
from strategy_manager.reconciliation.infrastructure.allocation_owner_adapter import (
    AllocationOwnerAdapter,
)
from strategy_manager.reconciliation.infrastructure.binance_venue_fill_reader import (
    BinanceVenueFillReader,
)
from strategy_manager.reconciliation.infrastructure.binance_venue_position_reader import (
    BinanceVenuePositionReader,
)
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.reconciliation.infrastructure.booking_writer import SqlAlchemyBookingWriter
from strategy_manager.reconciliation.infrastructure.bybit_venue_fill_reader import (
    BybitVenueFillReader,
)
from strategy_manager.reconciliation.infrastructure.bybit_venue_position_reader import (
    BybitVenuePositionReader,
)
from strategy_manager.reconciliation.infrastructure.fake_venue_position_reader import (
    FakeVenuePositionReader,
)
from strategy_manager.reconciliation.infrastructure.in_flight_close_adapter import (
    InFlightCloseAdapter,
)
from strategy_manager.reconciliation.infrastructure.lazy_venue_position_reader import (
    LazyVenuePositionReader,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from strategy_manager.reconciliation.infrastructure.router import (
    router as reconciliation_router,
)
from strategy_manager.reconciliation.infrastructure.system_order_ids_adapter import (
    SystemOrderIdsAdapter,
)
from strategy_manager.reconciliation.infrastructure.user_venue_fill_readers import (
    UserVenueFillReaders,
)
from strategy_manager.reconciliation.infrastructure.venue_fill_reader_registry import (
    VenueFillReaderRegistry,
)
from strategy_manager.reconciliation.infrastructure.venue_position_reader_registry import (
    VenuePositionReaderRegistry,
)
from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.application.jobs_purge_handler import JobsPurgeHandler
from strategy_manager.shared.application.purge_jobs import PurgeJobs
from strategy_manager.shared.application.watchdog import AlertChannelPort, Watchdog
from strategy_manager.shared.application.watchdog_handler import WatchdogHandler
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.db import engine, session_factory
from strategy_manager.shared.domain.money import Currency
from strategy_manager.shared.infrastructure.access_log import (
    install_access_log_redaction,
)
from strategy_manager.shared.infrastructure.alerting import operator_alerts
from strategy_manager.shared.infrastructure.api_logging import configure_api_logging
from strategy_manager.shared.infrastructure.binance import EXCHANGE as BINANCE_EXCHANGE
from strategy_manager.shared.infrastructure.binance.factory import (
    read_only_client as binance_read_only_client,
)
from strategy_manager.shared.infrastructure.binance.factory import (
    trade_client as binance_trade_client,
)
from strategy_manager.shared.infrastructure.binance.signer import BinanceCredentials
from strategy_manager.shared.infrastructure.bybit import EXCHANGE as BYBIT_EXCHANGE
from strategy_manager.shared.infrastructure.bybit.factory import (
    read_only_client,
    trade_client,
)
from strategy_manager.shared.infrastructure.bybit.signer import BybitCredentials
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import EnvelopeCipher
from strategy_manager.shared.infrastructure.heartbeat import build_heartbeat
from strategy_manager.shared.infrastructure.http_logging import silence_http_client_info_logs
from strategy_manager.shared.infrastructure.job_health import PostgresJobHealth
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.job_retention import PostgresJobRetention
from strategy_manager.shared.infrastructure.no_store import NoStoreMiddleware
from strategy_manager.shared.infrastructure.observed_job_queue import (
    ExhaustionObservingJobQueue,
)
from strategy_manager.shared.infrastructure.recurring_jobs import RECURRING_KINDS
from strategy_manager.shared.infrastructure.spa import (
    assert_panel_dist_ready,
    mount_panel,
)
from strategy_manager.shared.infrastructure.usd_rate import FixedUsdRateProvider
from strategy_manager.shared.infrastructure.validation_errors import (
    redacted_validation_handler,
)
from strategy_manager.shared.infrastructure.worker_runner import JobHandler, WorkerRunner
from strategy_manager.signals.application.close_orphans import CloseOrphans
from strategy_manager.signals.application.holding_guard import HoldingGuard
from strategy_manager.signals.application.open_after_close import OpenAfterClose
from strategy_manager.signals.application.process_signal import (
    ProcessSignalHandler,
    ProcessSignalResult,
)
from strategy_manager.signals.infrastructure.exhausted_job_recorder import (
    ExhaustedJobSignalRecorder,
)
from strategy_manager.signals.infrastructure.failed_job_signal_reader import (
    SqlAlchemyFailedJobSignalReader,
)
from strategy_manager.signals.infrastructure.in_flight_work import InFlightWorkAdapter
from strategy_manager.signals.infrastructure.job_owner import attempt_owner, signal_owner
from strategy_manager.signals.infrastructure.order_outcome_recorder import (
    SignalOrderOutcomeRecorder,
)
from strategy_manager.signals.infrastructure.outcome_repository import (
    SqlAlchemySignalOutcomeAdapter,
)
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository
from strategy_manager.signals.infrastructure.router import router as signals_router
from strategy_manager.signals.infrastructure.settle_outcome_recorder import (
    SignalSettleOutcomeRecorder,
)
from strategy_manager.signals.infrastructure.signal_context import SignalContextAdapter
from strategy_manager.signals.infrastructure.skip_recorder import SignalSkipRecorder
from strategy_manager.signals.infrastructure.venue_net_position import VenueNetPositionAdapter
from strategy_manager.signals.infrastructure.webhook_origin_check import log_webhook_origin
from strategy_manager.signals.infrastructure.webhook_origin_router import (
    router as webhook_origin_router,
)
from strategy_manager.signals.infrastructure.webhook_secret_invariant import (
    assert_webhook_secret_configured,
)
from strategy_manager.signals.infrastructure.webhook_secret_router import (
    router as webhook_secret_router,
)
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.pair_catalog import VenuePairCatalog
from strategy_manager.strategies.infrastructure.pair_catalog_router import (
    router as pair_catalog_router,
)
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from strategy_manager.strategies.infrastructure.router import (
    router as strategies_router,
)
from strategy_manager.subscriptions.infrastructure.router import (
    router as subscriptions_router,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup invariants 1, 3 and 4 (design.md § Composition Root).

    1: ``capital_pools`` is the single source of truth for which pools exist —
    enumerate it and assert every pool's advisory-lock key pair is distinct
    before accepting traffic.

    3: ``WEBHOOK_SECRET`` must be configured, or this process mounts an
    endpoint that answers 401 to every alert it was deployed to receive.

    4: the API must know who is signed in and who the admin is
    (``assert_identity_configured``, multi-user design AD1), or this process
    mounts routers whose guard has nothing to compare against. It replaced the
    bearer-token check. 3 and 4 are one invariant per mounted surface, which is
    why both live here: this function is where the routers this process serves
    become reachable.

    Invariant 2 (``DRY_RUN`` vs. the registered adapter) is not repeated here:
    it belongs to ``build_worker_runner``, which is the only place that decides
    which ``ExchangePort`` is registered, and this process places no orders.

    Operator alerting wraps all three, for the reason the worker gives: every
    invariant below refuses to serve traffic, and a process that never came up
    is the one least likely to be noticed. It is a no-op when alerting is off,
    and it needs nothing but the settings token to install.
    """

    # First, so that nothing this process says is lost and so that the bridge
    # installed below finds a root logger that already writes. Here and not in
    # ``create_app``: that runs at IMPORT (``app = create_app()``), and the
    # worker imports this module, so it would configure the worker's logging as
    # a side effect of an import.
    configure_api_logging()
    settings = get_settings()
    async with operator_alerts(settings):
        async with engine.connect() as conn:
            pools = await CapitalPoolRepository(conn).list_enabled()
            await assert_pool_lock_keys_distinct(conn, pools)
        assert_webhook_secret_configured(settings)
        assert_identity_configured(settings)
        assert_panel_dist_ready(settings)
        # A line, not an invariant: a typo in a display setting must not stop
        # the process that receives the alerts (rule 3). Never raises.
        log_webhook_origin(settings)
        yield


def log_simulated_exchange_startup(fakes: Mapping[str, FakeExchangeAdapter]) -> None:
    """The two startup lines of decision 45 (design § J), taken from each
    instance's OWN mode and rate: one INFO per process, so the journal shows
    from which start fills carry their alert's price and which taker rate was
    charged; and one WARNING per simulated exchange built with a fixed price,
    which would silently restore the old behaviour (every fill at one price).

    Production never builds a fixed-price exchange; the function takes the
    instances so a later edit of this module cannot do it quietly."""
    alert_priced: dict[str, FakeExchangeAdapter] = {}
    for name, fake in sorted(fakes.items()):
        if fake.fixed_fill_price is None:
            alert_priced[name] = fake
        else:
            logger.warning(
                "the simulated exchange '%s' is built with a fixed price of %s: every "
                "fill is priced at it, not at its alert's price",
                name,
                format(fake.fixed_fill_price.normalize(), "f"),
            )
    if alert_priced:
        logger.info(
            "dry run: the simulated exchange prices each fill at its alert's price "
            "and charges the venue's taker fee in USDT (%s)",
            ", ".join(
                f"{name}={format(fake.fee_rate.normalize(), 'f')}"
                for name, fake in alert_priced.items()
            ),
        )


def _job_queue(session: AsyncSession, settings: Settings) -> PostgresJobQueue:
    """The queue adapter with its retry backoff wired from configuration.

    ``PostgresJobQueue`` carries defaults equal to the settings' own so that the
    many construction sites that only enqueue keep working, but this is the
    composition root and the composition root is where the real values belong —
    the adapter never reads ``Settings`` itself.
    """
    return PostgresJobQueue(
        session,
        backoff_base_seconds=settings.job_retry_backoff_base_seconds,
        backoff_max_seconds=settings.job_retry_backoff_max_seconds,
    )


def _build_process_signal_handler(
    session: AsyncSession,
    pools_by_key: Mapping[tuple[UUID, tuple[str, str, str]], PoolConfig],
    settings: Settings,
    exchanges: ExchangeRegistryPort,
    tradable_pools: frozenset[tuple[str, str]],
    balance_refresh_reader: ExchangeBalanceReaderPort,
    venue_position_readers: VenuePositionReaderRegistryPort,
) -> tuple[ProcessSignalHandler, OpenAfterClose]:
    """Composes ``AllocateCapital`` (slice 4) and ``ExecuteReservation``
    (slice 5) into the ``signal.process`` job handler (design.md's job
    handlers table).

    ``BalanceSourcePort`` is now bound to ``DbBalanceSource``, which reads the
    snapshot the ``balance.sync`` job writes. It reads locally on purpose:
    this runs inside the pool's advisory lock, where a remote call would
    serialize every allocation on that pool behind exchange latency.

    The exchange REGISTRY is passed in rather than built here: which
    adapters are registered is a ``DRY_RUN`` decision that belongs to the
    composition root, and the same registry is handed to the
    ``execution.settle`` handler because placing and settling are two jobs
    talking about the same order -- on the same venue."""

    strategy_repository = SqlAlchemyStrategyRepository(session)
    signal_repository = SqlAlchemySignalRepository(session)
    reservation_repository = SqlAlchemyReservationRepository(session)
    # Decision 25: one outcome adapter on the run's session, so every outcome
    # write is staged on the same unit of work as the commit that decides it.
    signal_outcomes = SqlAlchemySignalOutcomeAdapter(session, SystemClock())

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

    # The Existing-Position Guard (spec: capital-allocation § Existing-
    # Position Guard). ``ReadSymbolHoldings`` and ``InFlightWorkAdapter``
    # each compose repositories from more than one module -- neither
    # ``ledger`` nor ``signals`` alone knows a strategy's whole in-flight
    # picture, since attempts carry no ``strategy_id`` and reservations carry
    # no ``symbol``.
    holding_guard = HoldingGuard(
        holdings=ReadSymbolHoldings(SqlAlchemyLedgerRepository(session)),
        in_flight_work=InFlightWorkAdapter(
            attempts=SqlAlchemyExecutionAttemptRepository(session),
            reservations=reservation_repository,
        ),
        # The divergent branch's ONE remote read (spec: capital-allocation §
        # Orphan Classification; design.md § S4) -- built from a registry the
        # caller already assembled, exactly like ``balance_refresh`` below
        # reuses ``balance_refresh_reader``.
        venue_net_position=VenueNetPositionAdapter(
            venue_position_readers,
            timeout_seconds=settings.venue_net_position_timeout_seconds,
        ),
        clock=SystemClock(),
        delayed_open_max_signal_age_seconds=settings.delayed_open_max_signal_age_seconds,
    )

    # On-Demand Balance Refresh Before Allocation (spec: capital-allocation §
    # On-Demand Balance Refresh Before Allocation; design.md § S3). Runs right
    # after the guard above and right before the sizing read below --
    # ``_handle_consumes``'s last remote call before ``AllocateCapital``
    # acquires the advisory lock. ``balance_refresh_reader`` is built once per
    # job by ``handle_signal_process``, the same way ``handle_balance_sync``
    # builds its own readers, but able to answer for any configured exchange
    # since which pool a given signal needs is not known until here.
    balance_refresh = RefreshPoolBalance(
        reader=balance_refresh_reader,
        snapshots=SqlAlchemyBalanceSnapshotRepository(session),
        age=DbBalanceSnapshotAge(session, SystemClock()),
        commit=session,
        timeout_seconds=settings.balance_refresh_timeout_seconds,
        fallback_max_age_seconds=settings.balance_snapshot_max_age_seconds,
    )

    allocate_capital = AllocateCapital(
        strategy_policy=strategy_policy,
        pool_balance=pool_balance,
        lock=PgAdvisoryLockAdapter(session),
        reservations=reservation_repository,
        commit=session,
        clock=SystemClock(),
        reservation_ttl_seconds=settings.reservation_ttl_seconds,
        skip_recorder=SignalSkipRecorder(signal_outcomes),
        pool_status=SqlAlchemyPoolStatus(session),
    )

    place_order = PlaceOrder(
        reservations=ReservationGatewayAdapter(reservation_repository),
        exchanges=exchanges,
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        queue=_job_queue(session, settings),
        clock=SystemClock(),
        commit=session,
        settle_delay_seconds=settings.execution_settle_delay_seconds,
        outcomes=SignalOrderOutcomeRecorder(signal_outcomes),
    )

    # A close shares the exchange and the attempt repository with placement,
    # but nothing else: no reservation gateway, no advisory lock, and its size
    # comes from the ledger rather than from a granted amount and a price.
    close_position = ClosePosition(
        exchanges=exchanges,
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        held=ReadHeldBase(SqlAlchemyLedgerRepository(session)),
        queue=_job_queue(session, settings),
        clock=SystemClock(),
        commit=session,
        settle_delay_seconds=settings.execution_settle_delay_seconds,
        outcomes=SignalOrderOutcomeRecorder(signal_outcomes),
    )

    # The S5 continuation (design.md § S5) and this handler need each other:
    # the handler seeds it from the rewired in-flight branch (design.md § S5,
    # amending S2), and it calls back into the handler's own ``open_now``
    # once every awaited close settles. Neither constructor can hand the
    # other object in directly since neither exists yet -- ``_open_now``
    # closes over the ``handler`` name below, which is only ever CALLED
    # later, by which point this function has already returned it.
    async def _open_now(signal_id: UUID, poll: int) -> ProcessSignalResult:
        return await handler.open_now(signal_id, poll)

    open_after_close = OpenAfterClose(
        signals=signal_repository,
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        queue=_job_queue(session, settings),
        clock=SystemClock(),
        open_now=_open_now,
        settle_timeout_seconds=settings.open_after_close_settle_timeout_seconds,
        poll_interval_seconds=settings.open_after_close_poll_interval_seconds,
        max_signal_age_seconds=settings.delayed_open_max_signal_age_seconds,
        # Decision 25 (5c.4): abandonments write their outcome through the
        # silent-on-terminal path, on this run's session.
        outcomes=signal_outcomes,
    )

    # The REAL branch of the Existing-Position Guard (design.md § S6): shares
    # ``close_position`` and ``open_after_close`` with the rest of this
    # composition root -- closing a REAL orphan and closing the reverse-
    # wiring release half's own allocation are the same underlying action,
    # composed once each and reused.
    close_orphans = CloseOrphans(
        close_position=close_position,
        closing_attempts=SqlAlchemyExecutionAttemptRepository(session),
        open_after_close=open_after_close,
        commit=session,
    )

    handler = ProcessSignalHandler(
        signal_context=signal_context,
        strategy_policy=strategy_policy,
        pool_balance=pool_balance,
        holding_guard=holding_guard,
        balance_refresh=balance_refresh,
        allocate_capital=allocate_capital,
        place_order=place_order,
        close_position=close_position,
        open_after_close=open_after_close,
        commit=session,
        # The reverse-wiring release half's own idempotency check
        # (design.md § S5, S5b): shares the same repository/session the rest
        # of this composition root already uses for ``attempts``.
        closing_attempts=SqlAlchemyExecutionAttemptRepository(session),
        close_orphans=close_orphans,
        tradable_pools=tradable_pools,
        outcomes=signal_outcomes,
        # Decisions 18 and 20 (design.md § 4a): chosen by DRY_RUN like the
        # exchange adapters. A rehearsal places nothing, so no key is needed
        # and none can be missing; live, the answer is one column read of the
        # active row, never a decrypt.
        trade_capability=(
            DryRunTradeCapability()
            if settings.dry_run
            else VaultTradeCapabilityAdapter(session)
        ),
    )
    return handler, open_after_close


def _build_settle_execution(
    session: AsyncSession, exchanges: ExchangeRegistryPort
) -> SettleExecution:
    """Composes the ``execution.settle`` job's use case: ask the exchange what
    the order became, and write it to the append-only ledger."""
    return SettleExecution(
        reservations=ReservationGatewayAdapter(
            SqlAlchemyReservationRepository(session)
        ),
        exchanges=exchanges,
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        fill_recorder=RecordFill(SqlAlchemyLedgerRepository(session)),
        usd_rate_provider=FixedUsdRateProvider({Currency.USDT: Decimal("1")}),
        clock=SystemClock(),
        commit=session,
        # Decision 25, rows 16-17: one outcome adapter on this job's session,
        # so the signal's outcome is staged on the same unit of work as the
        # fills (or the release) it is decided by.
        outcomes=SignalSettleOutcomeRecorder(
            SqlAlchemySignalOutcomeAdapter(session, SystemClock()),
            SqlAlchemySignalRepository(session),
        ),
    )


async def _vault_credential(
    vault: SqlAlchemyCredentialVault, user_id: UUID, exchange: str
) -> ExchangeCredential | None:
    """One user's trade credential for one exchange, or ``None`` if that user
    has none stored. Another user's key on the same exchange is never a
    substitute (multi-user design AD8).

    A missing credential is a degradation, not a failure, and it is scoped to
    the exchange that is missing it. Raising here would let an exchange nobody
    has sealed a key for stop the exchange that has one -- the same
    disproportion the unserved-pool warning refuses one level up: halting the
    worker over an unused pool would take working trading down with it.

    What the caller does instead is register the exchanges that DID load, and
    that is the whole of what this buys: the exchange holding a key keeps
    trading.

    Be exact about the cost to the one WITHOUT a key, because the obvious
    reading is wrong. Its signals are NOT refused by name. ``tradable_pools``
    is computed at startup from the registered CLASSES and knows nothing about
    credentials, so such a signal passes that check, reserves capital, and only
    then fails in ``PlaceOrder`` -- where ``for_pool`` raises OUTSIDE the block
    that releases a reservation on a definitive rejection. The job retries and
    the capital stays held until the reservation expires on its own.

    Survivable, and deliberately not repaired here: repairing it means deciding
    that an unserved pool is a definitive rejection, which is an execution-layer
    decision rather than a wiring one. What must not happen is someone reading
    this helper and believing the missing exchange fails cleanly.
    """
    try:
        return await vault.load(user_id, exchange)
    except CredentialNotFound:
        logger.warning(
            "no active credential is stored for '%s' of user %s; its adapter will "
            "not be registered, so that user's signals on its pools will reserve "
            "capital and then fail to place, holding it until the reservation "
            "expires. Trading on every other exchange, and every other user's, is "
            "unaffected.",
            exchange,
            _user_prefix(user_id),
        )
        return None


def _track_degraded_exchanges(
    tracker: set[UserExchange],
    *,
    configured: frozenset[UserExchange],
    active: frozenset[UserExchange],
) -> None:
    """Mutates the shared, process-lifetime DEGRADED set and logs each
    transition EXACTLY once: an ERROR the instant a configured exchange's key
    disappears while running, an INFO the instant it comes back. Steady state
    -- the common case, since ``balance.sync`` alone calls this every 60s --
    logs nothing at all.

    Keyed by ``(user_id, exchange)`` (multi-user design AD9): one user's
    missing key degrades that user's pair only, and every line names the
    user by the first 8 hex of their id, never an e-mail, because an ERROR
    reaches Telegram.

    No flood, by construction: ``tracker`` is the only thing consulted to
    decide whether an exchange is ALREADY known degraded, so a repeated call
    with the same ``active`` set is a no-op every time after the first. That
    set is also what lets ``build_worker_runner``'s ``initial_degraded``
    (``worker._assert_keys_present``'s own startup report) be SEEDED in
    rather than re-discovered: an exchange already known missing at boot is
    not re-logged by the first per-job check that runs after it.

    Every caller passes ``configured`` and ``active`` from ONE
    ``read_key_coverage`` statement, read fresh on every job: a key saved or
    deleted while the worker runs is seen on the next job, not only after a
    restart. Both must describe the same moment. Deleting a key from the panel
    disables its pool in the same commit; when ``configured`` came from the
    shared pool set, which only catches up on the next balance.sync reload,
    that delete read as an enabled pool with no key and sent a false ERROR
    (2026-10-21).

    An exchange can also leave ``configured`` entirely -- its last pool
    disabled. That exchange is
    dropped from ``tracker`` SILENTLY if it was degraded there: it did not
    recover, it simply stopped needing a key at all, and logging "reads
    resume" for it would be actively misleading.
    """
    newly_degraded = (configured - active) - tracker
    for pair in sorted(newly_degraded, key=_pair_order):
        user_id, exchange = pair
        logger.error(
            "'%s' has an enabled pool but no active vault credential for user %s; "
            "that user's reads are skipped until one is stored "
            "(uv run python scripts/store_%s_credentials.py --user-email <theirs>)",
            exchange,
            _user_prefix(user_id),
            exchange,
        )
        tracker.add(pair)

    recovered = tracker & active
    for pair in sorted(recovered, key=_pair_order):
        user_id, exchange = pair
        logger.info(
            "'%s' has an active vault credential again for user %s; reads resume",
            exchange,
            _user_prefix(user_id),
        )
        tracker.discard(pair)

    tracker.difference_update(tracker - configured)


def _user_prefix(user_id: UUID) -> str:
    """How a user is named in a log line that may reach Telegram: the first 8
    hex of their id, never an e-mail (multi-user design AD9)."""
    return str(user_id)[:8]


def _pair_order(pair: UserExchange) -> tuple[str, str]:
    """Exchange first, then user: a UUID does not sort against a string."""
    return pair[1], str(pair[0])


class _PoolSet:
    """The mutable, process-lifetime pool configuration every consumer in
    ``build_worker_runner`` reads through (design.md's F11 fix, binding for
    PR 3 unit 1b.9/1b.10).

    Refreshed ONLY by ``handle_balance_sync``, on its own ~60s cadence,
    rather than by every job independently: ``signal.process`` runs once per
    claimed signal -- far more often than an operator ever changes which
    pools are enabled -- and a fresh ``CapitalPoolRepository.list_enabled()``
    query on every one of them would be needless DB load for a change that
    happens, at most, a few times a day. Every consumer reads the SAME
    shared instance, so a refresh lands for all of them the instant it
    happens, with no restart and no per-consumer plumbing.

    ``by_key`` is keyed by ``(user_id, market)`` (multi-user design AD8): two
    users may each hold a pool on one market, with their own minimum and their
    own money, so the market alone no longer names a pool.
    """

    def __init__(self, pools: Sequence[PoolConfig]) -> None:
        self.pools: tuple[PoolConfig, ...] = ()
        self.by_key: dict[tuple[UUID, tuple[str, str, str]], PoolConfig] = {}
        self.configured_exchanges: frozenset[str] = frozenset()
        self.replace(pools)

    def replace(self, pools: Sequence[PoolConfig]) -> None:
        self.pools = tuple(pools)
        self.by_key = {
            (
                pool.user_id,
                (pool.exchange.value, pool.venue.value, pool.settlement_currency.value),
            ): pool
            for pool in pools
        }
        self.configured_exchanges = frozenset(market[0] for _, market in self.by_key)


def _track_pool_changes(
    previous: frozenset[tuple[UUID, tuple[str, str, str]]],
    current: frozenset[tuple[UUID, tuple[str, str, str]]],
) -> None:
    """Logs a pool's enable/disable transition exactly once, the moment
    ``_PoolSet.replace`` adopts a new set (design.md's F11 fix, binding
    requirement 2): INFO for a newly enabled pool, WARNING for a newly
    disabled one. Comparing the PREVIOUS adopted set to the new one is what
    makes this a transition log rather than a snapshot dump -- a steady
    state (no change between two reloads) produces an empty difference on
    both sides, so it stays silent, the same property
    ``_track_degraded_exchanges`` already has for exchanges. The very first
    reload after startup compares against the STARTUP set itself (``_PoolSet``
    is constructed from it), so nothing is re-logged there either.

    A pool is a user's pool on a market, so the line names the market and the
    user's id prefix, never an e-mail (multi-user design AD9).
    """
    for user_id, market in sorted(current - previous, key=_pool_order):
        logger.info(
            "pool %s of user %s newly enabled; reads resume within one sync interval",
            market,
            str(user_id)[:8],
        )
    for user_id, market in sorted(previous - current, key=_pool_order):
        logger.warning(
            "pool %s of user %s newly disabled; reads stop from this cycle",
            market,
            str(user_id)[:8],
        )


def _pool_order(key: tuple[UUID, tuple[str, str, str]]) -> tuple[tuple[str, str, str], str]:
    """Market first, then user: a UUID does not sort against a tuple."""
    return key[1], str(key[0])


def _markets_per_user(
    by_key: Mapping[tuple[UUID, tuple[str, str, str]], PoolConfig], exchange: str
) -> dict[UUID, list[tuple[str, str, str]]]:
    """Each user's enabled markets on one exchange, for one balance sync per
    ``(user, exchange)`` (multi-user design AD9). A user with no pool on the
    exchange is absent, so no sync is built that would read nothing."""
    per_user: dict[UUID, list[tuple[str, str, str]]] = {}
    for user_id, market in sorted(by_key, key=_pool_order):
        if market[0] == exchange:
            per_user.setdefault(user_id, []).append(market)
    return per_user


def _holds_pool(
    by_key: Mapping[tuple[UUID, tuple[str, str, str]], PoolConfig],
    user_id: UUID | None,
    exchange: str,
) -> bool:
    """Whether ``user_id`` holds an enabled pool on ``exchange``. ``None`` -- a
    job whose owner could not be resolved -- holds none, so it is read with
    nobody's key."""
    return user_id is not None and any(
        owner == user_id and market[0] == exchange for owner, market in by_key
    )


def _reconciliation_markets_per_user(
    by_key: Mapping[tuple[UUID, tuple[str, str, str]], PoolConfig],
    active: frozenset[UserExchange],
    *,
    warn: bool,
) -> dict[UUID, list[tuple[str, str, str]]]:
    """Each user's markets that reconciliation can read, with THAT user's key
    (multi-user design AD10, tasks.md B.8): the enabled pools of a user on an
    exchange where the user also holds an active key.

    A venue's net position is an account's, so the same market held by two
    users is two reads, each with its owner's key. A user with a pool but no
    active key on an exchange is skipped for that exchange only (and logged
    when ``warn``, naming the user by the first 8 hex of the id and the
    exchange); the other users, and the same user's other exchanges, still
    run. A user with no readable market is absent. Markets are sorted and
    users are ordered by id, so the order is stable from job to job."""
    per_user: dict[UUID, list[tuple[str, str, str]]] = {}
    unkeyed: set[UserExchange] = set()
    for user_id, market in sorted(by_key, key=lambda key: (str(key[0]), key[1])):
        exchange = market[0]
        if exchange not in (BYBIT_EXCHANGE, BINANCE_EXCHANGE):
            continue
        if (user_id, exchange) not in active:
            unkeyed.add((user_id, exchange))
            continue
        per_user.setdefault(user_id, []).append(market)
    if warn:
        for user_id, exchange in sorted(unkeyed, key=lambda pair: (str(pair[0]), pair[1])):
            logger.warning(
                "reconciliation: user %s has a pool on %s but no active key there; "
                "skipping this user on this exchange this cycle",
                str(user_id)[:8],
                exchange,
            )
    return per_user


async def _user_position_readers(
    *,
    vault: SqlAlchemyCredentialVault,
    clients: AsyncExitStack,
    settings: Settings,
    user_id: UUID,
    exchanges: Sequence[str],
) -> list[VenuePositionReaderPort]:
    """The venue position readers of ONE user's account, one per exchange in
    ``exchanges``, each signed with that user's own vault key. The clients are
    entered on ``clients``, which the caller closes."""
    readers: list[VenuePositionReaderPort] = []
    if BYBIT_EXCHANGE in exchanges:
        credential = await vault.load(user_id, BYBIT_EXCHANGE)
        bybit = await clients.enter_async_context(
            read_only_client(
                settings,
                BybitCredentials(api_key=credential.api_key, api_secret=credential.api_secret),
            )
        )
        readers.append(BybitVenuePositionReader(bybit))
    if BINANCE_EXCHANGE in exchanges:
        credential = await vault.load(user_id, BINANCE_EXCHANGE)
        binance = await clients.enter_async_context(
            binance_read_only_client(
                settings,
                BinanceCredentials(api_key=credential.api_key, api_secret=credential.api_secret),
            )
        )
        readers.append(BinanceVenuePositionReader(binance))
    return readers


class _DegradedVenueFillReader:
    """Stands in for a REAL ``VenueFillReaderPort`` when its exchange has no
    active vault credential this cycle.

    Registered in place of the real reader rather than omitted: unlike
    ``ReaderByExchange``/``VenuePositionReaderRegistry`` (whose consumers
    catch a broad ``Exception`` and so tolerate a plain missing entry),
    ``PrepareBooking.sweep`` reads CONFIRMED discrepancies straight from the
    database rather than from a pool list this composition root controls --
    so a discrepancy on this exchange left over from before it lost its key
    would still reach ``VenueFillReaderRegistry.for_pool`` and raise
    ``UnservedFillPoolError``, which ``sweep`` does NOT swallow (that
    registry's own docstring: "never swallowed... must propagate loud enough
    to kill the job"). Raising ``VenueFillReadError`` instead reuses the
    swallow path ``sweep`` already has for an ordinary failed fetch: the
    discrepancy is skipped and logged as a WARNING, not crashed -- the same
    "no read and no raise" outcome, reached the only way this port allows.
    """

    def __init__(self, exchange: str, venues: frozenset[str]) -> None:
        self.exchange = exchange
        self.venues = venues

    async def fills_in_window(
        self, pool: PoolKey, symbol: str, start: datetime, end: datetime
    ) -> list[VenueFill]:
        del pool, symbol, start, end
        raise VenueFillReadError(
            f"'{self.exchange}' has no active vault credential this cycle; "
            "no fetch was attempted"
        )


def _degraded_fill_readers(exchanges: Sequence[str]) -> list[VenueFillReaderPort]:
    """A ``_DegradedVenueFillReader`` for each of ``exchanges``."""
    venues = {
        BYBIT_EXCHANGE: BybitVenueFillReader.venues,
        BINANCE_EXCHANGE: BinanceVenueFillReader.venues,
    }
    return [_DegradedVenueFillReader(exchange, venues[exchange]) for exchange in exchanges]


async def _user_fill_readers(
    *,
    vault: SqlAlchemyCredentialVault,
    clients: AsyncExitStack,
    settings: Settings,
    user_id: UUID,
    keyed: Sequence[str],
) -> list[VenueFillReaderPort]:
    """The fill readers of ONE user's account (multi-user design AD10): a real
    reader signed with that user's own vault key for each exchange in
    ``keyed``, and a ``_DegradedVenueFillReader`` for every other reconciled
    exchange, so a CONFIRMED discrepancy of this user on an exchange they have
    lost the key for is skipped (a tolerated ``VenueFillReadError``) instead of
    reaching an unserved pool."""
    readers: list[VenueFillReaderPort] = []
    if BYBIT_EXCHANGE in keyed:
        credential = await vault.load(user_id, BYBIT_EXCHANGE)
        bybit = await clients.enter_async_context(
            read_only_client(
                settings,
                BybitCredentials(api_key=credential.api_key, api_secret=credential.api_secret),
            )
        )
        readers.append(
            BybitVenueFillReader(
                bybit,
                page_limit=settings.reconciliation_booking_prepare_page_limit,
                max_pages=settings.reconciliation_booking_prepare_max_pages,
            )
        )
    if BINANCE_EXCHANGE in keyed:
        credential = await vault.load(user_id, BINANCE_EXCHANGE)
        binance = await clients.enter_async_context(
            binance_read_only_client(
                settings,
                BinanceCredentials(api_key=credential.api_key, api_secret=credential.api_secret),
            )
        )
        readers.append(
            BinanceVenueFillReader(
                binance,
                page_limit=settings.reconciliation_booking_prepare_page_limit,
                max_pages=settings.reconciliation_booking_prepare_max_pages,
            )
        )
    readers.extend(
        _degraded_fill_readers(
            [e for e in (BYBIT_EXCHANGE, BINANCE_EXCHANGE) if e not in keyed]
        )
    )
    return readers


async def assert_dry_run_matches_ledger(
    *,
    dry_run: bool,
    session_factory_override: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Owner decision 28: refuse to start when ``DRY_RUN`` does not match the
    origin of an open position or an unsettled order in the ledger.

    Async, so it cannot live inside ``build_worker_runner``: the ledger read
    needs the event loop, and that function is synchronous and is also built by
    tests that have no database. The worker calls it from its own startup
    sequence, inside ``operator_alerts``, so the ERROR it logs reaches the
    alert bridge before the process exits.

    Its own short-lived session, closed before any job is claimed. Every pool
    is covered, enabled or not (``SqlAlchemyModeOriginReader``).
    """
    factory = session_factory_override or session_factory
    async with factory() as session:
        await assert_mode_matches_ledger(
            dry_run=dry_run, reader=SqlAlchemyModeOriginReader(session)
        )


def build_worker_runner(
    pools: Sequence[PoolConfig],
    *,
    session_factory_override: async_sessionmaker[AsyncSession] | None = None,
    alert_channel: AlertChannelPort | None = None,
    initial_degraded: frozenset[UserExchange] = frozenset(),
) -> WorkerRunner:
    """Registers ``signal.process``, ``reservation.sweep``, ``balance.sync``,
    ``execution.settle`` and ``reconciliation.scan``. One fresh session per
    claimed job, independent of the claim session (design.md § Transaction
    Boundaries: the claim's row lock must die with its own connection).

    Both recurring chains keep themselves alive by enqueuing their own
    successor, so each needs an initial job before it runs at all. Seeding is
    ``RecurringJobSeeder``'s job, called by the worker entrypoint — registering
    a handler here does not start its chain.

    ``alert_channel`` is the live ``AlertLogBridge`` when the calling process
    installed one, and it is passed in rather than reached for because it is
    owned by the ``operator_alerts`` context this function runs inside. The
    watchdog asks it one thing — how many alerts it has thrown away — and
    ``None`` simply means alerting is off, which is not a fault: the watchdog
    still runs and still logs, because delivery is the bridge's problem and
    this check is not.

    ``initial_degraded`` seeds the per-job DEGRADED tracker
    (``_track_degraded_exchanges``) from the worker's own startup report
    (``worker._assert_keys_present``), so the FIRST per-job active-key check
    after boot never re-logs an exchange startup already reported missing.
    Every read site below re-checks the vault's active-key listing on its
    OWN cadence from there on — DEGRADED is never a fixed, startup-only
    snapshot (the orchestrator's binding correction to this unit): a key
    saved or deleted while the worker runs is seen on the very next job that
    asks, not only after a restart."""

    settings = get_settings()
    factory = session_factory_override or session_factory

    # The shared, mutable, process-lifetime pool configuration every
    # consumer below reads through -- see ``_PoolSet``'s own docstring for
    # why it is refreshed only by ``handle_balance_sync`` rather than per
    # job (design.md's F11 fix, binding requirement 1).
    pool_set = _PoolSet(pools)

    # DRY_RUN is what selects the adapter, and it is the only thing that does.
    # This is the composition root the DRY_RUN invariant names: the one place
    # that knows which ExchangePort adapter is actually registered
    # (spec: trade-execution § DRY_RUN Safety). The check runs against the
    # class because the live adapter cannot exist yet — it needs a decrypted
    # credential and an open socket, and neither belongs to startup.
    #
    # Bybit and Binance, not Pionex. Binance now joins Bybit as a venue that can
    # actually execute: both place futures orders over their API, each against
    # its own account, and the registry keyed by (exchange, venue) is what keeps
    # one exchange's signal from reaching the other's wallet.
    #
    # The Pionex adapters are complete, tested and correct, and they are
    # deliberately NOT registered: Pionex does not offer futures order placement
    # over its API to public users, so the futures one cannot execute, and
    # splitting capital across two exchanges to keep the spot one would defeat
    # what this system is for. They stay in the repository as the second
    # implementation that proves this port is the right shape.
    registered: tuple[type[ExchangePort], ...] = (
        (FakeExchangeAdapter,)
        if settings.dry_run
        else (BybitFuturesExchangeAdapter, BinanceFuturesExchangeAdapter)
    )
    for adapter in registered:
        assert_dry_run_safe(dry_run=settings.dry_run, exchange=adapter)

    # One fake per configured exchange, not one fake for all of them. The
    # registry is keyed by (exchange, venue) now, and a single instance
    # claiming every exchange would route a Binance pool's rehearsal through
    # the same object as a Bybit one -- the very collapse this key exists to
    # prevent, rehearsed wrongly.
    #
    # Each holds its own placed orders, so place and settle must share the
    # instance for a given exchange; that is why they are built here, once,
    # rather than per job.
    # Process-lifetime, exactly like ``fakes_by_exchange`` below: a DRY_RUN
    # venue-side net must survive across many ``signal.process`` jobs, not
    # just one, or every job would seed it fresh and never see a fill from an
    # earlier one (design.md § S4, DRY_RUN paragraph). Its own ledger reader
    # opens a short-lived session per call rather than sharing one job's --
    # there is no job session yet at this point in composition, and each pool
    # is seeded from it at most once over the life of this process anyway.
    async def _fake_venue_book_ledger_reader(
        pool: tuple[str, str, str],
    ) -> list[tuple[str, Decimal]]:
        # One book per exchange, not per user: it is seeded from every user's
        # rows on the pool, summed per symbol.
        async with factory() as seed_session:
            repository = SqlAlchemyLedgerRepository(seed_session)
            net_by_symbol: dict[str, Decimal] = {}
            for seed_user in sorted(await repository.distinct_users_for_pool(*pool)):
                for position in await ReadSymbolPositions(repository).net_positions_by_symbol(
                    seed_user, pool
                ):
                    net_by_symbol[position.symbol] = (
                        net_by_symbol.get(position.symbol, Decimal("0")) + position.net_base
                    )
            return list(net_by_symbol.items())

    fake_venue_book = FakeVenueBook(_fake_venue_book_ledger_reader)

    # BYBIT_EXCHANGE and BINANCE_EXCHANGE are unconditional, on top of
    # whatever else the startup pool list names (e.g. Pionex's spot pools):
    # decision 21 auto-enables a futures pool for either one the moment a
    # key is saved, at ANY point while the worker is already running, so a
    # deployment that started with neither configured still needs a DRY_RUN
    # adapter ready for it (binding requirement 6) -- the live path already
    # has this for free, since ``registered`` above is the fixed
    # ``(BybitFuturesExchangeAdapter, BinanceFuturesExchangeAdapter)`` tuple
    # regardless of ``pools``.
    #
    # Decision 45: a simulated exchange exists only for an exchange that has a
    # simulated taker fee rate, and its rate is read BY KEY from the table --
    # never with a default, because a default of zero would charge nothing
    # without anyone deciding to. Bybit and Binance both have one. Under
    # DRY_RUN=false nothing is built: the real adapters above are the only
    # ones registered.
    fakes_by_exchange = {
        exchange: FakeExchangeAdapter(
            exchange=exchange,
            book=fake_venue_book,
            fee_rate=SIMULATED_TAKER_FEE_RATES[exchange],
        )
        for exchange in {pool.exchange.value for pool in pools} | {
            BYBIT_EXCHANGE,
            BINANCE_EXCHANGE,
        }
        if settings.dry_run and exchange in SIMULATED_TAKER_FEE_RATES
    }
    if settings.dry_run:
        # An exchange with a pool and no rate gets no simulated exchange. It is
        # reported here, and its signals are refused per signal as untradable
        # (the unserved-pools warning below covers the pools themselves): a
        # pool nobody trades is not a reason to stop the pools somebody does.
        for unrated in sorted(
            {pool.exchange.value for pool in pools} - set(SIMULATED_TAKER_FEE_RATES)
        ):
            logger.warning(
                "no simulated taker fee rate is defined for '%s': it has no simulated "
                "exchange in a dry run, so its signals are refused as untradable",
                unrated,
            )
        log_simulated_exchange_startup(fakes_by_exchange)

    # ``venue`` reaches the reservation, the attempt and the ledger row without
    # ever selecting an adapter, so a strategy on a venue this adapter does not
    # serve would be sized against one wallet and executed against another.
    #
    # Warned about here and REFUSED per signal, not here. A pool nobody is
    # trading is not a reason to stop the pools somebody is: halting the worker
    # over an unused coin-m pool would take spot trading down with it.
    # The UNION across every registered adapter. Asking each one separately
    # would report every futures pool as untradable merely because the spot
    # adapter does not serve it -- noise that trains an operator to ignore the
    # one warning that matters.
    #
    # The two branches ask the same question of genuinely different KINDS of
    # thing, which is why the answer is computed per branch rather than through
    # one tuple of adapters. A dry run's fakes are INSTANCES: ``exchange`` is
    # per instance there, so one fake stands in for each configured exchange.
    # The live adapters are CLASSES, because a live one cannot exist at startup
    # -- it needs a decrypted credential and an open socket, and neither belongs
    # here. Both kinds carry ``exchange`` and ``venues``, which is everything
    # this computation reads, so nothing is gained by forcing them together and
    # the pairs come out identical either way.
    tradable_pools: frozenset[tuple[str, str]] = (
        frozenset(
            (fake.exchange, venue)
            for fake in fakes_by_exchange.values()
            for venue in fake.venues
        )
        if settings.dry_run
        else frozenset(
            (adapter.exchange, venue)
            for adapter in registered
            for venue in adapter.venues
        )
    )
    unserved = unserved_pools(served=tradable_pools, pools=pools)
    if unserved:
        logger.warning(
            describe_unserved(
                served=tradable_pools,
                by=" + ".join(adapter.__name__ for adapter in registered),
                unserved=unserved,
            )
        )

    # Built once at startup so a missing or malformed MASTER_ENCRYPTION_KEY
    # fails here rather than on the first job that needs a credential.
    cipher = EnvelopeCipher.from_base64(settings.master_encryption_key)

    # Unserved-pools is a STARTUP-only sanity warning (a pool whose venue no
    # adapter serves at all -- a genuine misconfiguration, not a credential
    # or enablement state), deliberately left unrefreshed by the per-cycle
    # reload below: re-running it every cycle for a persistently-unserved
    # pool would flood the log the same way an undeduped ERROR would, and
    # this unit's binding requirements do not ask for it. A pool enabled at
    # runtime for a venue nothing serves would not get this warning until
    # the next restart -- a known, accepted gap, not a silent one.

    # The shared, process-lifetime DEGRADED set every read site below
    # consults and updates via ``_track_degraded_exchanges``, fed by
    # ``read_key_coverage`` on every job (one statement for pools and keys)
    # so an exchange enabled or fully disabled at runtime is seen
    # immediately (binding requirement 3). Seeded from the worker's own
    # startup report (``worker._assert_keys_present``) so the very first
    # per-job check never re-logs what startup already did. Keyed by
    # ``(user_id, exchange)`` (multi-user design AD9).
    _degraded: set[UserExchange] = set(initial_degraded)

    # The last lock-key collision message reported by ``_reload_pools``, or
    # ``None`` once a reload has succeeded since. Compared against on every
    # refusal so the SAME collision is reported once, not every cycle
    # (binding requirement 4) -- reset the moment a reload succeeds, so a
    # collision that reappears later (a different pair, or the same one
    # again) is reported again.
    _last_lock_collision: str | None = None

    async def _reload_pools() -> None:
        """Re-reads ``capital_pools`` at the start of every ``balance.sync``
        cycle (design.md's F11 fix) and, if lock keys stay distinct, adopts
        the new set for every consumer sharing ``pool_set``.

        On a collision the PREVIOUS set is kept -- adopting a colliding set
        would silently serialize two unrelated pools against each other,
        exactly the invariant ``worker._run_worker`` already refuses to
        start over -- and the refusal is logged once, not every cycle, by
        comparing the collision's own message against the last one already
        reported.

        Uses ``engine`` (the module-level connection pool), not the job's
        own ORM ``session``: this is the SAME raw-connection check
        ``worker._run_worker``/``lifespan`` already run at startup, over a
        query ``CapitalPoolRepository`` only accepts a raw connection for.
        """
        nonlocal _last_lock_collision
        async with engine.connect() as conn:
            reloaded = await CapitalPoolRepository(conn).list_enabled()
            try:
                await assert_pool_lock_keys_distinct(conn, reloaded)
            except PoolLockKeyCollisionError as exc:
                message = str(exc)
                if message != _last_lock_collision:
                    logger.error(
                        "reloaded pool set refused, keeping the previous %d "
                        "pool(s): %s",
                        len(pool_set.pools),
                        message,
                    )
                    _last_lock_collision = message
                return

        _last_lock_collision = None
        previous_keys = frozenset(pool_set.by_key)
        pool_set.replace(reloaded)
        _track_pool_changes(previous_keys, frozenset(pool_set.by_key))

    async def _open_balance_reader(
        clients: AsyncExitStack,
        vault: SqlAlchemyCredentialVault,
        user_id: UUID,
        exchange: str,
    ) -> ExchangeBalanceReaderPort:
        """``user_id``'s balance reader on ``exchange``, signed with
        ``user_id``'s own VAULT key: the one key per exchange that trades too
        (design decision 18), so a green sync proves the trading key can read.
        It does not prove the order path; the first order can still surface a
        venue-side rejection this read never exercised.

        Decrypted here and used immediately: the plaintext lives only for the
        length of this call (CLAUDE.md rule 8). The client closes with
        ``clients``."""
        credential = await vault.load(user_id, exchange)
        if exchange == BYBIT_EXCHANGE:
            bybit = await clients.enter_async_context(
                read_only_client(
                    settings,
                    BybitCredentials(
                        api_key=credential.api_key, api_secret=credential.api_secret
                    ),
                )
            )
            return BybitBalanceReader(bybit, SystemClock())
        binance = await clients.enter_async_context(
            binance_read_only_client(
                settings,
                BinanceCredentials(api_key=credential.api_key, api_secret=credential.api_secret),
            )
        )
        return BinanceBalanceReader(binance, SystemClock())

    # The fakes above hold their placed orders in memory, so place and settle
    # have to share the same instance per exchange or settlement finds
    # nothing. The live adapter is the opposite: it is stateless, the venue
    # itself is the shared state, and it needs a per-job credential and socket
    # — so it is built per job, exactly like the balance reader, and the
    # plaintext dies with the call (CLAUDE.md rule 8).

    @asynccontextmanager
    async def exchange_for(
        session: AsyncSession, user_id: UUID | None
    ) -> AsyncIterator[ExchangeRegistryPort]:
        """Every venue ``user_id`` can trade, built fresh for one job.

        ``user_id`` is the job's owner: the author of the strategy whose signal
        or attempt this job works on (multi-user design AD8, tasks.md B.5/B.7).
        Every adapter is signed with THAT user's key, never another user's on
        the same exchange. An owner that could not be resolved (``None``) gets
        an empty registry: the job then fails on the missing row, not on
        somebody else's account.

        The registry is complete before the venue is known, so selection never
        has to fall back -- and a fallback is precisely the failure it exists
        to prevent.

        Each credential is decrypted here and dies with this context
        (CLAUDE.md rule 8), and each adapter is signed with its OWN exchange's
        key: authenticating against the wrong venue fails in a way that looks
        exactly like the venue refusing the call.

        The two are loaded INDEPENDENTLY. A Binance key nobody has sealed must
        cost Binance signals and nothing else -- it may not take Bybit trading
        down with it, which is the same rule the unserved-pool warning follows.
        That, and only that, is what loading them separately buys.

        An exchange left out is not in the registry, and a signal for it fails
        inside ``PlaceOrder`` rather than being refused by name up front. See
        ``_vault_credential`` for why, and for the capital that stays reserved
        until it expires. The same holds when NEITHER loads: an empty registry
        is not a clean stop, it is every signal taking that path. Yielding it
        anyway is still right, because manufacturing an outage at job start
        would take down the exchange that DOES have a key.

        The exit stack is what lets both HTTP clients nest and close in order,
        however many of them were actually opened.
        """
        if settings.dry_run:
            yield VenueExchangeRegistry(list(fakes_by_exchange.values()))
            return

        if user_id is None:
            yield VenueExchangeRegistry([])
            return

        vault = SqlAlchemyCredentialVault(session, cipher, SystemClock())

        async with AsyncExitStack() as clients:
            adapters: list[ExchangePort] = []

            bybit = await _vault_credential(vault, user_id, BYBIT_EXCHANGE)
            if bybit is not None:
                futures = await clients.enter_async_context(
                    trade_client(
                        settings,
                        BybitCredentials(
                            api_key=bybit.api_key, api_secret=bybit.api_secret
                        ),
                    )
                )
                adapters.append(BybitFuturesExchangeAdapter(futures))

            binance = await _vault_credential(vault, user_id, BINANCE_EXCHANGE)
            if binance is not None:
                binance_futures = await clients.enter_async_context(
                    binance_trade_client(
                        settings,
                        BinanceCredentials(
                            api_key=binance.api_key, api_secret=binance.api_secret
                        ),
                    )
                )
                adapters.append(BinanceFuturesExchangeAdapter(binance_futures))

            yield VenueExchangeRegistry(adapters)

    @asynccontextmanager
    async def balance_refresh_reader_for(
        session: AsyncSession, user_id: UUID | None
    ) -> AsyncIterator[ExchangeBalanceReaderPort]:
        """A ``ReaderByExchange`` whose per-exchange factories build NOTHING
        until ``RefreshPoolBalance`` actually asks for a pool on that
        exchange -- and only that one exchange's credential is decrypted and
        HTTP client opened, into this job's own ``AsyncExitStack`` so it
        closes when the job does.

        Laziness here is a correctness requirement, not an optimization
        (design.md § S3 correction, 2026-09-21): a RELEASES signal never
        calls the refresh at all, and a CONSUMES signal only ever needs its
        OWN pool's exchange -- which is not known until ``_handle_consumes``
        reads the strategy's policy, well after this context manager has to
        be entered. Building both exchanges' credentials/clients
        UNCONDITIONALLY here, the way ``exchange_for`` above does for trade
        clients, would cost a close -- or a signal on the other exchange -- a
        credential problem it never needed. That is exactly the failure mode
        ``_vault_credential`` already exists to prevent for trade clients;
        this mirrors it for the refresh's own reader.

        A factory's own failure (a missing or undecryptable credential, a
        client that cannot be constructed) is left to propagate out of the
        factory and into ``ReaderByExchange.read`` uncaught: it surfaces
        INSIDE ``RefreshPoolBalance.refresh`` as an ordinary reader error,
        which is exactly what lets it degrade through FALLBACK/UNAVAILABLE
        instead of raising out of job entry.

        Which exchange gets a factory AT ALL is now decided PER JOB, from the
        vault's active-key listing (``read_key_coverage``, no decrypt) rather
        than from pool configuration alone: a DEGRADED exchange is skipped
        here -- no factory, so no read and no raise -- rather than reaching
        the lazy ``.load()`` above only to fail the moment it is actually
        invoked. Checked before the closures below so this context manager's
        one ``read_key_coverage`` query serves both exchanges, not two.

        Per user (multi-user design AD9): only ``user_id``'s own pools and
        ``user_id``'s own active key count, and the key decrypted is theirs.
        An owner that could not be resolved (``None``) gets no factory at all.
        """

        vault = SqlAlchemyCredentialVault(session, cipher, SystemClock())
        coverage = await read_key_coverage(session)
        active = coverage.active
        _track_degraded_exchanges(_degraded, configured=coverage.configured, active=active)
        if user_id is None:
            yield ReaderByExchange({})
            return
        owner: UUID = user_id

        async with AsyncExitStack() as clients:

            async def bybit_reader() -> ExchangeBalanceReaderPort:
                credential = await vault.load(owner, BYBIT_EXCHANGE)
                bybit = await clients.enter_async_context(
                    read_only_client(
                        settings,
                        BybitCredentials(
                            api_key=credential.api_key, api_secret=credential.api_secret
                        ),
                    )
                )
                return BybitBalanceReader(bybit, SystemClock())

            async def binance_reader() -> ExchangeBalanceReaderPort:
                credential = await vault.load(owner, BINANCE_EXCHANGE)
                binance = await clients.enter_async_context(
                    binance_read_only_client(
                        settings,
                        BinanceCredentials(
                            api_key=credential.api_key, api_secret=credential.api_secret
                        ),
                    )
                )
                return BinanceBalanceReader(binance, SystemClock())

            factories: dict[str, ReaderFactory] = {}

            if (
                _holds_pool(pool_set.by_key, owner, BYBIT_EXCHANGE)
                and (owner, BYBIT_EXCHANGE) in active
            ):
                factories[BYBIT_EXCHANGE] = bybit_reader

            if (
                _holds_pool(pool_set.by_key, owner, BINANCE_EXCHANGE)
                and (owner, BINANCE_EXCHANGE) in active
            ):
                factories[BINANCE_EXCHANGE] = binance_reader

            yield ReaderByExchange(factories)

    @asynccontextmanager
    async def venue_net_position_reader_for(
        session: AsyncSession, user_id: UUID | None
    ) -> AsyncIterator[VenuePositionReaderRegistryPort]:
        """The registry ``VenueNetPositionAdapter`` asks for the ONE pool the
        Existing-Position Guard's divergent branch actually reads -- built
        fresh per job, exactly like ``balance_refresh_reader_for`` above and
        for the same reason: which exchange (if any) is ever asked is not
        known until deep inside ``_handle_consumes``, well after this context
        manager is entered. Most jobs never call it at all.

        Real readers are wrapped in ``LazyVenuePositionReader`` so a
        credential is decrypted and a client opened only if that exchange's
        pool is actually read (design.md § S4 correction, replaying S3's own
        correction for this port).

        Under DRY_RUN every reader wraps the shared, process-lifetime
        ``fake_venue_book`` instead of a real client -- so a rehearsed REAL
        orphan is reachable without a credential, exactly like every other
        DRY_RUN path.

        Live, which exchange gets a ``LazyVenuePositionReader`` AT ALL is
        decided PER JOB from the vault's active-key listing
        (``read_key_coverage``, no decrypt), exactly like
        ``balance_refresh_reader_for`` above: a DEGRADED exchange is skipped
        here rather than reaching its own lazy ``.load()`` only to fail when
        actually invoked.

        Per user, like ``balance_refresh_reader_for``: the venue position read
        is ``user_id``'s own account, with ``user_id``'s own key.
        """
        if settings.dry_run:
            yield VenuePositionReaderRegistry(
                [
                    FakeVenuePositionReader(
                        exchange=fake.exchange, venues=fake.venues, book=fake_venue_book
                    )
                    for fake in fakes_by_exchange.values()
                ]
            )
            return

        vault = SqlAlchemyCredentialVault(session, cipher, SystemClock())
        coverage = await read_key_coverage(session)
        active = coverage.active
        _track_degraded_exchanges(_degraded, configured=coverage.configured, active=active)
        if user_id is None:
            yield VenuePositionReaderRegistry([])
            return
        owner: UUID = user_id

        async with AsyncExitStack() as clients:

            async def bybit_position_reader() -> VenuePositionReaderPort:
                credential = await vault.load(owner, BYBIT_EXCHANGE)
                bybit = await clients.enter_async_context(
                    read_only_client(
                        settings,
                        BybitCredentials(
                            api_key=credential.api_key, api_secret=credential.api_secret
                        ),
                    )
                )
                return BybitVenuePositionReader(bybit)

            async def binance_position_reader() -> VenuePositionReaderPort:
                credential = await vault.load(owner, BINANCE_EXCHANGE)
                binance = await clients.enter_async_context(
                    binance_read_only_client(
                        settings,
                        BinanceCredentials(
                            api_key=credential.api_key, api_secret=credential.api_secret
                        ),
                    )
                )
                return BinanceVenuePositionReader(binance)

            readers: list[VenuePositionReaderPort] = []
            if (
                _holds_pool(pool_set.by_key, owner, BYBIT_EXCHANGE)
                and (owner, BYBIT_EXCHANGE) in active
            ):
                readers.append(
                    LazyVenuePositionReader(
                        BYBIT_EXCHANGE, frozenset({"usdt-m"}), bybit_position_reader
                    )
                )
            if (
                _holds_pool(pool_set.by_key, owner, BINANCE_EXCHANGE)
                and (owner, BINANCE_EXCHANGE) in active
            ):
                readers.append(
                    LazyVenuePositionReader(
                        BINANCE_EXCHANGE, frozenset({"usdt-m"}), binance_position_reader
                    )
                )
            yield VenuePositionReaderRegistry(readers)

    async def handle_signal_process(job: ClaimedJob) -> None:
        signal_id = UUID(str(job.payload["signal_id"]))
        async with factory() as session:
            # The strategy author's key, and nobody else's (AD8, B.5).
            owner = await signal_owner(session, signal_id)
            async with (
                exchange_for(session, owner) as exchanges,
                balance_refresh_reader_for(session, owner) as balance_refresh_reader,
                venue_net_position_reader_for(session, owner) as venue_position_readers,
            ):
                handler, _ = _build_process_signal_handler(
                    session,
                    pool_set.by_key,
                    settings,
                    exchanges,
                    tradable_pools,
                    balance_refresh_reader,
                    venue_position_readers,
                )
                # The returned ProcessSignalResult is intentionally discarded here:
                # the handler owns every outcome (refused, failed, executed) and
                # logs it itself. The result exists for tests and for the S5
                # continuation -- do not "fix" this by branching on it.
                await handler.handle(signal_id)
                # Required since S5: the guard's in-flight branch may seed a
                # continuation (``enqueue_unique``, which never commits) without
                # otherwise writing anything through this handler. Every other
                # path already committed via its own sub-use-case, so this is a
                # harmless no-op for them.
                await session.commit()

    async def handle_signal_open_after_close(job: ClaimedJob) -> None:
        async with factory() as session:
            # The continuation opens for the same signal's author (AD8, B.5).
            owner = await signal_owner(session, UUID(str(job.payload["signal_id"])))
            async with (
                exchange_for(session, owner) as exchanges,
                balance_refresh_reader_for(session, owner) as balance_refresh_reader,
                venue_net_position_reader_for(session, owner) as venue_position_readers,
            ):
                _, open_after_close = _build_process_signal_handler(
                    session,
                    pool_set.by_key,
                    settings,
                    exchanges,
                    tradable_pools,
                    balance_refresh_reader,
                    venue_position_readers,
                )
                await open_after_close.poll(job, owner)
                await session.commit()

    async def handle_execution_settle(job: ClaimedJob) -> None:
        attempt_id = UUID(str(job.payload["execution_attempt_id"]))
        async with factory() as session:
            # Settled with the key the order was placed with: its author's, and
            # the reservation read and marked is that same user's (AD8, B.5).
            owner = await attempt_owner(session, attempt_id)
            if owner is None:
                raise LookupError(
                    f"execution attempt {attempt_id} has no owner: the attempt, its "
                    "reservation or its strategy is gone"
                )
            async with exchange_for(session, owner) as exchanges:
                await _build_settle_execution(session, exchanges).settle(owner, attempt_id)

    async def handle_balance_sync(job: ClaimedJob) -> None:
        """One sync per exchange that has enabled pools AND an active vault
        credential right now.

        Each exchange answers for its own account only, so a reader is never
        handed a pool whose money it does not hold -- the same rule the
        registry enforces for orders, applied to balances.

        The HTTP clients are built per job rather than held open across the
        worker's life: a sync runs every few seconds, so the reconnect is
        cheap, and no socket outlives the job that opened it.

        A DEGRADED exchange is OMITTED from ``syncs`` (no read, no raise)
        rather than included with a credential load that would raise --
        this is the fix for the bug that motivated this unit: the OLD code
        loaded unconditionally, BEFORE ``handler.handle(job)`` ran, so a
        missing key raised out of this function entirely and the successor
        job -- enqueued only INSIDE ``handler.handle`` -- was never
        scheduled, silently killing the whole recurring chain (Bybit's sync
        included, even though Bybit's own key was fine). Omitting the
        exchange instead means ``handler.handle(job)`` always runs, and
        ``CompositeBalanceSync`` over a partial (or even empty) ``syncs``
        list still succeeds and still enqueues the next cycle.

        This is also THE reload point (design.md's F11 fix, binding for
        unit 1b.9/1b.10): ``_reload_pools()`` re-reads ``capital_pools`` and
        adopts the new set into ``pool_set`` before anything else below
        runs, so ``bybit_pools``/``binance_pools`` and every other
        consumer's own read of ``pool_set`` see the CURRENT configuration,
        not a startup snapshot.

        One ``SyncBalances`` per ``(user, exchange)`` with an active key
        (multi-user design AD9, tasks.md B.7), each reading that user's
        account with that user's own key and storing that user's snapshots.

        A failure degrades its pair only. A key that does not open, or a client
        that cannot be built, skips that pair with a WARNING naming the
        exchange and the user's id prefix; a read that fails is isolated the
        same way by ``CompositeBalanceSync``. Every other pair is still synced
        and the successor is still scheduled: one user's broken key must not
        stall every user's balances. The skipped pair's snapshot keeps ageing,
        which the staleness watchdog reports.
        """
        await _reload_pools()

        async with factory() as session:
            snapshots = SqlAlchemyBalanceSnapshotRepository(session)

            vault = SqlAlchemyCredentialVault(session, cipher, SystemClock())
            coverage = await read_key_coverage(session)
            active = coverage.active
            _track_degraded_exchanges(_degraded, configured=coverage.configured, active=active)

            async with AsyncExitStack() as clients:
                syncs: list[SyncBalances] = []

                for exchange in (BYBIT_EXCHANGE, BINANCE_EXCHANGE):
                    for user_id, markets in _markets_per_user(pool_set.by_key, exchange).items():
                        if (user_id, exchange) not in active:
                            continue
                        try:
                            reader = await _open_balance_reader(
                                clients, vault, user_id, exchange
                            )
                        except Exception as exc:  # noqa: BLE001 -- isolated per pair, by design
                            # The class only: a message could carry venue text,
                            # and no traceback (its locals could hold a key).
                            logger.warning(
                                "balance sync skipped for '%s' of user %s: its key could "
                                "not be opened (%s); every other pair is still synced",
                                exchange,
                                _user_prefix(user_id),
                                type(exc).__name__,
                            )
                            continue
                        syncs.append(
                            SyncBalances(
                                user_id=user_id,
                                pools=markets,
                                reader=reader,
                                snapshots=snapshots,
                                commit=session,
                            )
                        )

                handler = BalanceSyncHandler(
                    sync_balances=CompositeBalanceSync(syncs),
                    queue=_job_queue(session, settings),
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
                queue=_job_queue(session, settings),
                clock=SystemClock(),
                interval_seconds=settings.reservation_sweep_interval_seconds,
            )
            await handler.handle(job)
            await session.commit()

    async def handle_reconciliation_scan(job: ClaimedJob) -> None:
        """Wraps ``ScanPools`` behind ``ReconciliationScanHandler``, which
        owns the DRY_RUN hard skip and the successor enqueue (design
        decisions 8, 11 -- see that handler's own docstring).

        The scan and its self-re-enqueue share one session, exactly as
        ``handle_reservation_sweep`` does, so a successor is never committed
        unless the scan that preceded it committed too.

        A real venue position reader is built only when DRY_RUN is off:
        building one means decrypting a trade credential and opening a
        socket, and the handler below never calls ``scan()`` under DRY_RUN
        anyway, so doing that work first would decrypt a credential for a
        scan that is about to be skipped outright.

        Per user's pool (multi-user design AD10): every user with an enabled
        pool AND an active key on an exchange is scanned with a position
        reader built from THAT user's vault key, so two users on one market
        are two reads and two discrepancies. A user with a pool but no key is
        filtered out of the scan for that exchange BEFORE ``ScanPools`` sees
        its pools (``_reconciliation_markets_per_user``, which logs a WARNING
        naming the user), not only skipped when building readers:
        ``ScanPools`` never swallows ``UnservedPoolError`` (only
        ``VenuePositionReadError``, per pool, for a live call that merely
        FAILED), so a pool with no registered reader would kill this chain,
        the same failure mode this unit fixes for balance.sync. The other
        users still scan, and one ``ScanPools`` per user shares this one
        session and the handler's single successor enqueue.
        """
        async with factory() as session:
            vault = SqlAlchemyCredentialVault(session, cipher, SystemClock())
            markets_by_user: dict[UUID, list[tuple[str, str, str]]] = {}
            if not settings.dry_run:
                coverage = await read_key_coverage(session)
                active = coverage.active
                _track_degraded_exchanges(
                    _degraded, configured=coverage.configured, active=active
                )
                markets_by_user = _reconciliation_markets_per_user(
                    pool_set.by_key, active, warn=True
                )

            async with AsyncExitStack() as clients:
                scans: list[ScanPoolsPort] = []
                for user_id, markets in markets_by_user.items():
                    readers = await _user_position_readers(
                        vault=vault,
                        clients=clients,
                        settings=settings,
                        user_id=user_id,
                        exchanges=sorted({market[0] for market in markets}),
                    )
                    scans.append(
                        ScanPools(
                            pools=markets,
                            pool_users={market: user_id for market in markets},
                            venue_readers=VenuePositionReaderRegistry(readers),
                            ledger_positions=ReadSymbolPositions(
                                SqlAlchemyLedgerRepository(session)
                            ),
                            discrepancies=SqlAlchemyDiscrepancyRepository(session),
                            clock=SystemClock(),
                            commit=session,
                            confirmations_required=settings.reconciliation_confirmations,
                        )
                    )

                handler = ReconciliationScanHandler(
                    scan_pools=ScanUsers(scans),
                    queue=_job_queue(session, settings),
                    clock=SystemClock(),
                    interval_seconds=settings.reconciliation_scan_interval_seconds,
                    dry_run=settings.dry_run,
                )
                await handler.handle(job)
                await session.commit()

    async def handle_reconciliation_prepare_booking(job: ClaimedJob) -> None:
        """Wraps ``PrepareBooking`` behind ``BookingPrepareHandler``, which
        owns the DRY_RUN hard skip and the successor enqueue (design
        decisions 1, 11, 16 -- see that handler's own docstring).

        The sweep and its self-re-enqueue share one session, exactly as
        ``handle_reconciliation_scan`` does, so a successor is never
        committed unless the sweep that preceded it committed too.

        A real venue FILL reader is built only when DRY_RUN is off, mirroring
        ``handle_reconciliation_scan``'s identical guard around its own
        venue POSITION readers: building one means decrypting a trade
        credential and opening a socket, and the handler below never calls
        ``sweep()`` under DRY_RUN anyway, so doing that work first would
        decrypt a credential for a sweep that is about to be skipped
        outright.

        Both venues sign with their VAULT credential (design decision 18,
        ONE key per exchange -- superseding decision 9's earlier
        Bybit-vault/Binance-``.env`` split), the same source
        ``handle_reconciliation_scan`` already uses above.

        A DEGRADED exchange gets a ``_DegradedVenueFillReader`` stand-in
        instead of being omitted: ``PrepareBooking.sweep`` reads CONFIRMED
        discrepancies straight from the database, not from the pool list
        below, so a discrepancy already on record for this exchange could
        still reach the registry even though this cycle scans none of its
        pools. Omitting the reader would raise ``UnservedFillPoolError`` --
        never swallowed by ``sweep`` -- and kill this chain; the stand-in
        raises the ``VenueFillReadError`` ``sweep`` already tolerates per
        discrepancy instead (see that class's own docstring).

        Per user (multi-user design AD10): each CONFIRMED discrepancy is read
        with the fill reader of the user it belongs to, signed with that
        user's own vault key. The stand-in is per user and exchange: a user
        with no active key on an exchange (or no pool there any more, or no
        longer known at all) resolves to stand-ins, never to another user's
        reader.
        """
        async with factory() as session:
            vault = SqlAlchemyCredentialVault(session, cipher, SystemClock())
            markets_by_user: dict[UUID, list[tuple[str, str, str]]] = {}
            if not settings.dry_run:
                coverage = await read_key_coverage(session)
                active = coverage.active
                _track_degraded_exchanges(
                    _degraded, configured=coverage.configured, active=active
                )
                # The scan already warns about a user without a key; here the
                # stand-in reader reports it per discrepancy.
                markets_by_user = _reconciliation_markets_per_user(
                    pool_set.by_key, active, warn=False
                )

            async with AsyncExitStack() as clients:
                fill_registries: dict[UUID, VenueFillReaderRegistryPort] = {}
                for user_id, markets in markets_by_user.items():
                    fill_registries[user_id] = VenueFillReaderRegistry(
                        await _user_fill_readers(
                            vault=vault,
                            clients=clients,
                            settings=settings,
                            user_id=user_id,
                            keyed=sorted({market[0] for market in markets}),
                        )
                    )

                handler = BookingPrepareHandler(
                    prepare_booking=PrepareBooking(
                        discrepancies=SqlAlchemyDiscrepancyRepository(session),
                        proposals=SqlAlchemyBookingProposalRepository(session),
                        # A discrepancy is read with its own user's key. A user
                        # without one (or none any more) gets stand-ins that
                        # fail with the tolerated ``VenueFillReadError``.
                        venue_fills=UserVenueFillReaders(
                            fill_registries,
                            unkeyed=VenueFillReaderRegistry(
                                _degraded_fill_readers([BYBIT_EXCHANGE, BINANCE_EXCHANGE])
                            ),
                        ),
                        recorded_fill_ids=ReadRecordedFillIds(
                            SqlAlchemyLedgerRepository(session)
                        ),
                        allocation_owner=AllocationOwnerAdapter(session),
                        clock=SystemClock(),
                        commit=session,
                        window_pad_seconds=(
                            settings.reconciliation_booking_prepare_window_pad_seconds
                        ),
                        max_span_seconds=(
                            settings.reconciliation_booking_prepare_max_span_seconds
                        ),
                        proposal_expiry_seconds=(
                            settings.reconciliation_booking_proposal_expiry_seconds
                        ),
                        dry_run=settings.dry_run,
                        # Owner decision 66 Q2: never optional.
                        system_order_ids=SystemOrderIdsAdapter(session),
                    ),
                    expire_booking_proposals=ExpireBookingProposals(
                        proposals=SqlAlchemyBookingProposalRepository(session),
                        clock=SystemClock(),
                        commit=session,
                    ),
                    # Owner decision 66 Q1: the worker approves what it prepared,
                    # with the use case the admin route used to build (design
                    # C2): the same adapters, the same fixed USD rate, the same
                    # DRY_RUN refusal. One transaction per proposal, committed
                    # by ``ApproveBooking`` itself.
                    auto_book=AutoBookPending(
                        proposals=SqlAlchemyBookingProposalRepository(session),
                        approver=ApproveBooking(
                            proposals=SqlAlchemyBookingProposalRepository(session),
                            discrepancies=SqlAlchemyDiscrepancyRepository(session),
                            in_flight_close=InFlightCloseAdapter(
                                SqlAlchemyExecutionAttemptRepository(session)
                            ),
                            writer=SqlAlchemyBookingWriter(session),
                            usd_rate_provider=FixedUsdRateProvider({Currency.USDT: Decimal("1")}),
                            clock=SystemClock(),
                            commit=session,
                            dry_run=settings.dry_run,
                        ),
                    ),
                    # Owner decision 66 Q3 and Q4: reads, logs, writes nothing.
                    announce_needs_owner=AnnounceNeedsOwner(
                        discrepancies=SqlAlchemyDiscrepancyRepository(session),
                        approved=SqlAlchemyBookingProposalRepository(session),
                        clock=SystemClock(),
                        grace_seconds=settings.reconciliation_auto_booking_grace_seconds,
                        reminder_seconds=settings.reconciliation_needs_owner_reminder_seconds,
                    ),
                    queue=_job_queue(session, settings),
                    clock=SystemClock(),
                    interval_seconds=settings.reconciliation_booking_prepare_interval_seconds,
                    dry_run=settings.dry_run,
                )
                await handler.handle(job)
                await session.commit()

    async def handle_jobs_purge(job: ClaimedJob) -> None:
        # The purge and its self-re-enqueue share one session, exactly as
        # ``handle_reservation_sweep`` does, so a successor is never committed
        # unless the purge that preceded it committed. ``PurgeJobs`` commits
        # each batch through this same session; the commit below covers the
        # successor.
        async with factory() as session:
            handler = JobsPurgeHandler(
                purge_jobs=PurgeJobs(
                    retention=PostgresJobRetention(session),
                    clock=SystemClock(),
                    commit=session,
                    retention_days=settings.job_retention_days,
                ),
                queue=_job_queue(session, settings),
                clock=SystemClock(),
                interval_seconds=settings.jobs_purge_interval_seconds,
            )
            await handler.handle(job)
            await session.commit()

    async def handle_watchdog_check(job: ClaimedJob) -> None:
        """The periodic check for SILENCE (``shared.application.watchdog``).

        Reads the DATABASE ONLY — no vault, no credential, no venue client.
        That is the point of it: a watchdog that can hang on an exchange's
        socket stops watching precisely when something is wrong, and its own
        failure would then kill the chain it rides on. The heartbeat below is
        the one socket in here and it is not a read: it carries no answer the
        check depends on, it is sent after everything has already been decided
        and reported, and it cannot raise.

        Its session is the usual per-job one, and the commit covers the
        successor exactly as ``handle_jobs_purge`` does.

        The heartbeat is the one thing here that leaves the deployment, and it
        is built per run rather than held for the life of the worker. A ping
        every few minutes does not need a pooled connection, and a client built
        inside the run is a client that cannot outlive it — this is the chain
        nothing else is watching, so it gets the lifecycle with nothing to leak.
        ``None`` when no URL is configured, which is simply the feature off.
        """
        heartbeat = build_heartbeat(settings)
        try:
            async with factory() as session:
                handler = WatchdogHandler(
                    watchdog=Watchdog(
                        jobs=PostgresJobHealth(session),
                        snapshots=SqlAlchemyStaleSnapshotReader(session, SystemClock()),
                        alert_channel=alert_channel,
                        heartbeat=heartbeat,
                        clock=SystemClock(),
                        # The same tuple the seeder revives, so "should be
                        # scheduled" means one thing in this system, not two.
                        recurring_kinds=RECURRING_KINDS,
                        snapshot_max_age_seconds=(
                            settings.watchdog_snapshot_max_age_seconds
                        ),
                        lookback_seconds=settings.watchdog_interval_seconds,
                    ),
                    queue=_job_queue(session, settings),
                    clock=SystemClock(),
                    interval_seconds=settings.watchdog_interval_seconds,
                )
                await handler.handle(job)
                await session.commit()
        finally:
            if heartbeat is not None:
                await heartbeat.aclose()

    @asynccontextmanager
    async def queue_factory() -> AsyncIterator[PostgresJobQueue]:
        async with factory() as session:
            # The one queue whose ``fail()`` is ever called: WorkerRunner claims
            # through this factory, so this is where the retry backoff decides
            # whether a transient fault costs a chain its life -- and where a
            # job that spends its LAST attempt ends its signal (decision 25,
            # 5c.6). ``ExhaustionObservingJobQueue`` requires its observer, so
            # this queue cannot be built without one; the observer stages on
            # this same session, inside the transaction that marks the job
            # FAILED.
            yield ExhaustionObservingJobQueue(
                session,
                observer=ExhaustedJobSignalRecorder(
                    SqlAlchemySignalOutcomeAdapter(session, SystemClock()),
                    SqlAlchemyFailedJobSignalReader(session),
                ),
                backoff_base_seconds=settings.job_retry_backoff_base_seconds,
                backoff_max_seconds=settings.job_retry_backoff_max_seconds,
            )

    handlers: Mapping[JobKind, JobHandler] = {
        JobKind.SIGNAL_PROCESS: handle_signal_process,
        JobKind.SIGNAL_OPEN_AFTER_CLOSE: handle_signal_open_after_close,
        JobKind.RESERVATION_SWEEP: handle_reservation_sweep,
        JobKind.BALANCE_SYNC: handle_balance_sync,
        JobKind.EXECUTION_SETTLE: handle_execution_settle,
        JobKind.RECONCILIATION_SCAN: handle_reconciliation_scan,
        JobKind.RECONCILIATION_PREPARE_BOOKING: handle_reconciliation_prepare_booking,
        JobKind.JOBS_PURGE: handle_jobs_purge,
        JobKind.WATCHDOG_CHECK: handle_watchdog_check,
    }
    return WorkerRunner(
        queue_factory=queue_factory,
        handlers=handlers,
        poll_interval_seconds=settings.worker_poll_interval_seconds,
    )


def create_app() -> FastAPI:
    settings = get_settings()

    # The webhook secret rides in the query string, and uvicorn's access
    # logger writes request lines verbatim. Install this before the router
    # that can log one.
    install_access_log_redaction()

    # From PR 8a-3 this process runs key inspectors, and httpx would log the
    # signed Binance URL (signature included) at INFO for each one. The worker
    # applies the same setting. This must run before any inspector does.
    silence_http_client_info_logs()

    app = FastAPI(
        title="Strategy Manager",
        version="0.1.0",
        summary="Capital-allocation engine for TradingView strategies executing on Pionex",
        lifespan=lifespan,
    )

    # One handler for the whole app: a 422 never echoes a submitted value
    # (design 8a section H, task 6b.5). The credential body is a key and secret.
    app.add_exception_handler(RequestValidationError, redacted_validation_handler)

    # The credentials answers (last4, facts, label) must not be cached. A
    # middleware, because an exception handler's answer never sees a dependency.
    app.add_middleware(NoStoreMiddleware, prefix="/api/credentials")
    # Nor the answer that names who is signed in (multi-user design AD1).
    app.add_middleware(NoStoreMiddleware, prefix="/api/me")

    @app.get("/health")
    async def health() -> dict[str, str | bool]:
        return {"status": "ok", "dry_run": settings.dry_run}

    app.include_router(signals_router)

    # ONE catalogue for the whole process, so its cache and its single-flight
    # lock are shared by every request (decision 41). It reads the venues'
    # PUBLIC catalogues with transports that cannot sign: no vault, no signer,
    # no credential in this process. ``get_pair_catalog`` reads it back from here
    # and tests override that dependency with a fake.
    app.state.pair_catalog = VenuePairCatalog.for_settings(settings)

    # Every administrative router lives under one prefix (design.md §13, spec:
    # admin-api). Each included router keeps its OWN
    # ``dependencies=[Depends(require_admin)]`` (``/me`` keeps
    # ``verified_email``, multi-user design AD1), so authentication stays
    # structural per router rather than becoming a property of this wrapper --
    # wrapping never removes or replaces a router's own guard, it only moves
    # where its routes are reachable from. ``/webhook/tradingview`` and
    # ``/health`` are deliberately mounted above this line, on ``app``
    # directly, and never inside ``api_router``.
    api_router = APIRouter(prefix="/api")
    api_router.include_router(strategies_router)
    api_router.include_router(subscriptions_router)
    api_router.include_router(pair_catalog_router)
    api_router.include_router(reconciliation_router)
    api_router.include_router(pools_router)
    api_router.include_router(performance_router)
    api_router.include_router(open_positions_router)
    api_router.include_router(webhook_secret_router)
    api_router.include_router(webhook_origin_router)
    api_router.include_router(credentials_router)
    api_router.include_router(me_router)
    app.include_router(api_router)

    # LAST, after every router: the panel's catch-all matches any GET path, so
    # anything registered after it would be unreachable for GET.
    if settings.panel_dist_dir:
        mount_panel(app, Path(settings.panel_dist_dir))

    return app


app = create_app()
