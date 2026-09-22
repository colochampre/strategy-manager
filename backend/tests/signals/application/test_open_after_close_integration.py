"""MANDATORY timing/integration test (design.md § S5, "Testing" -- Timing).

Real ``PostgresJobQueue`` and ``WorkerRunner.run_once``, driven by one
shared frozen clock, prove the S5 continuation genuinely WAITS for an
awaited close to settle before opening -- not just that
``OpenAfterClose``'s branch precedence is correct in isolation
(``test_open_after_close.py`` already proves that with fakes).

``FakeExchangeAdapter(fill_latency_polls=3)`` answers ``fetch_fills`` with
no fills for the first three calls per order and only then reveals one --
the ordinary case for a real venue, and the one this continuation exists to
wait out. Every failed answer routes through ``execution.settle``'s own
``NotSettledYet`` -> ``queue.fail()`` backoff (unaffected by this unit); the
continuation itself never touches that path (design.md § "Why not reuse
``fail()`` backoff").

**Binding testing lesson**: a symbol has three spellings (TradingView
``STXUSDT.P``, venue bare ``STXUSDT``, Pionex ``STXUSDT_PERP``). This test
uses a DIFFERENT one on every side that crosses a module boundary: the
original ledger fill is recorded as ``STXUSDT``, the close command's own
symbol is ``STXUSDT.P``, and the new opening signal is recorded as
``STXUSDT_PERP``.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.application.ports import PoolBalanceReading
from strategy_manager.accounts.application.ports import PoolKey as AccountsPoolKey
from strategy_manager.accounts.application.refresh_pool_balance import RefreshPoolBalance
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.balance_snapshot_repository import (
    SqlAlchemyBalanceSnapshotRepository,
)
from strategy_manager.accounts.infrastructure.db_balance_source import (
    DbBalanceSnapshotAge,
    DbBalanceSource,
)
from strategy_manager.accounts.infrastructure.models import PoolBalanceSnapshotRow
from strategy_manager.allocation.application.allocate_capital import AllocateCapital
from strategy_manager.allocation.domain.pool_key import PoolKey as AllocationPoolKey
from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.allocation.infrastructure.reservation_gateway import (
    ReservationGatewayAdapter,
)
from strategy_manager.execution.application.close_position import CloseCommand, ClosePosition
from strategy_manager.execution.application.place_order import PlaceOrder
from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.application.settle_execution import SettleExecution
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt, ExecutionStatus
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.exchange_registry import VenueExchangeRegistry
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_held_base import ReadHeldBase
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.worker_runner import JobHandler, WorkerRunner
from strategy_manager.signals.application.holding_guard import HoldingGuard
from strategy_manager.signals.application.open_after_close import OpenAfterClose
from strategy_manager.signals.application.process_signal import ProcessSignalHandler
from strategy_manager.signals.infrastructure.in_flight_work import InFlightWorkAdapter
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository
from strategy_manager.signals.infrastructure.signal_context import SignalContextAdapter
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.signals.infrastructure.conftest import seed_strategy

pytestmark = pytest.mark.integration

POOL = ("bybit", "usdt-m", "USDT")
# ``execution_attempts.created_at``/``updated_at`` are DB server timestamps
# (real wall-clock, migration 0005's ``server_default=func.now()``), so the
# simulated clock this test steps by hand must start near REAL "now" too --
# otherwise comparing the two (``OpenAfterClose``'s settle-timeout check)
# would measure the gap between an arbitrary fixed date and the actual
# moment the close row was written, rather than genuine elapsed time.
START = datetime.now(UTC)
BEFORE_REVEAL_BALANCE = Decimal("999")  # a deliberately WRONG stale snapshot
AFTER_REVEAL_BALANCE = Decimal("150")   # what the pool actually holds once freed
POLL_INTERVAL_SECONDS = 1.0
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 8.0


class SteppableClock:
    """A clock the test moves by hand (mirrors
    ``tests/shared/infrastructure/test_job_queue_backoff.py``)."""

    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, seconds: float) -> None:
        self._at += timedelta(seconds=seconds)


class FixedUsdRate:
    async def usd_rate(self, currency: Currency) -> Decimal:
        return Decimal("1")


@dataclass
class FakeSettlementBalanceReader:
    """Moves a pool's reported funds only once the close's own fill has
    been revealed on the SAME ``FakeExchangeAdapter`` driving it -- derived
    from that adapter's own state rather than a moment the test picks by
    hand."""

    close_exchange: FakeExchangeAdapter
    close_client_order_id: str
    pool: AccountsPoolKey
    before: Decimal
    after: Decimal
    clock: SteppableClock

    async def read(self, pools: Sequence[AccountsPoolKey]) -> list[PoolBalanceReading]:
        amount = (
            self.after
            if self.close_exchange.is_revealed(self.close_client_order_id)
            else self.before
        )
        return [
            PoolBalanceReading(
                exchange=pool[0],
                venue=pool[1],
                settlement_currency=pool[2],
                total=amount,
                available=amount,
                observed_at=self.clock.now(),
            )
            for pool in pools
            if pool == self.pool
        ]


class NeverCalledVenueNetPosition:
    async def net_position(self, pool: object, symbol: str) -> Decimal | None:
        raise AssertionError(
            "the divergent branch must never run -- the strategy nets to zero "
            "once the close settles"
        )


class NeverCalledClosePosition:
    async def close(self, command: CloseCommand) -> object:
        raise AssertionError("open_now must never route through the RELEASES branch")


class NeverCalledSeeder:
    async def seed(self, signal_id: UUID, awaited_allocation_ids: list[UUID]) -> None:
        raise AssertionError(
            "the open must proceed once the close is FILLED -- it must never "
            "re-defer"
        )


class NeverCalledCloseOrphans:
    async def close(
        self, signal_id: UUID, pool: object, strategy_id: UUID, symbol: str, holdings: object
    ) -> None:
        raise AssertionError(
            "open_now's guard never finds a REAL orphan once the close it "
            "awaited has settled -- the strategy nets to zero"
        )


async def _seed_signal(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    signal_id: UUID,
    strategy_id: UUID,
    symbol: str,
    price: Decimal,
    position_size: Decimal,
    received_at: datetime,
) -> None:
    """Raw insert with an EXPLICIT ``received_at`` -- ``insert_or_get``
    always lets the server default (real wall-clock ``now()``) decide it,
    which would fight this test's simulated timeline."""
    async with session_factory() as session:
        await session.execute(
            insert(SignalRow).values(
                id=signal_id,
                strategy_id=strategy_id,
                idempotency_key=f"k-{signal_id}",
                raw_payload={},
                action="buy",
                contracts=position_size,
                position_size=position_size,
                price=price,
                symbol=symbol,
                signal_type=str(strategy_id),
                received_at=received_at,
            )
        )
        await session.commit()


async def test_the_open_waits_for_the_close_to_settle_then_grants_the_freed_balance(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await seed_strategy(
        pg_session_factory,
        strategy_id=strategy_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        fill_mode="PARTIAL",
        enabled=True,
    )

    # ---- the position about to be closed: opened under yet another spelling ----
    prior_signal_id, allocation_id, opening_attempt_id = uuid4(), uuid4(), uuid4()
    await _seed_signal(
        pg_session_factory,
        signal_id=prior_signal_id,
        strategy_id=strategy_id,
        symbol="STXUSDT",
        price=Decimal("2"),
        position_size=Decimal("1"),
        received_at=START - timedelta(hours=1),
    )
    async with pg_session_factory() as session:
        reservations = SqlAlchemyReservationRepository(session)
        await reservations.insert(
            Reservation(
                id=allocation_id,
                strategy_id=strategy_id,
                signal_id=prior_signal_id,
                pool_key=AllocationPoolKey(
                    exchange=Exchange("bybit"),
                    venue=Venue("usdt-m"),
                    settlement_currency=Currency("USDT"),
                ),
                amount=Decimal("100"),
                status=ReservationStatus.FILLED,
                expires_at=START,
            )
        )
        await session.commit()
    async with pg_session_factory() as session:
        attempts = SqlAlchemyExecutionAttemptRepository(session)
        await attempts.insert(
            ExecutionAttempt(
                id=opening_attempt_id,
                reservation_id=allocation_id,
                closes_allocation_id=None,
                exchange="bybit",
                venue="usdt-m",
                settlement_currency="USDT",
                symbol="STXUSDT",
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                quote_amount=None,
                leverage=Decimal("1"),
                status=ExecutionStatus.FILLED,
                client_order_id=f"opening-{opening_attempt_id}",
            )
        )
        await session.commit()
    async with pg_session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            FillRecord(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                execution_attempt_id=opening_attempt_id,
                exchange="bybit",
                venue="usdt-m",
                settlement_currency="USDT",
                symbol="STXUSDT",
                side="BUY",
                quantity=Decimal("1"),
                price=Decimal("2"),
                fee=Decimal("0"),
                fee_currency="USDT",
                notional=Decimal("2"),
                exchange_order_id=f"opening-order-{opening_attempt_id}",
                exchange_fill_id=f"opening-fill-{opening_attempt_id}",
                filled_at=START - timedelta(hours=1),
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()

    # ---- a stale, deliberately WRONG snapshot -- proves the on-demand
    # refresh (S3) overwrites it rather than the open reading it directly ----
    async with pg_session_factory() as session:
        await session.execute(
            insert(PoolBalanceSnapshotRow).values(
                exchange="bybit",
                venue="usdt-m",
                settlement_currency="USDT",
                total=BEFORE_REVEAL_BALANCE,
                available=BEFORE_REVEAL_BALANCE,
                observed_at=START - timedelta(hours=1),
            )
        )
        await session.commit()

    clock = SteppableClock(START)
    exchange = FakeExchangeAdapter(exchange="bybit", fill_price=Decimal("2"), fill_latency_polls=3)
    registry = VenueExchangeRegistry([exchange])

    # ---- submit the close for real, through the production use case ----
    async with pg_session_factory() as session:
        close_position = ClosePosition(
            exchanges=registry,
            attempts=SqlAlchemyExecutionAttemptRepository(session),
            held=ReadHeldBase(SqlAlchemyLedgerRepository(session)),
            queue=PostgresJobQueue(
                session,
                clock=clock,
                backoff_base_seconds=BACKOFF_BASE_SECONDS,
                backoff_max_seconds=BACKOFF_MAX_SECONDS,
            ),
            clock=clock,
            commit=session,
            settle_delay_seconds=0.0,
        )
        close_result = await close_position.close(
            CloseCommand(
                allocation_id=allocation_id,
                strategy_id=strategy_id,
                exchange="bybit",
                venue="usdt-m",
                settlement_currency="USDT",
                symbol="STXUSDT.P",
                side=OrderSide.SELL,
            )
        )
    assert close_result.status == "PLACED"
    close_attempt_id = close_result.execution_attempt_id

    async with pg_session_factory() as session:
        close_attempt = await SqlAlchemyExecutionAttemptRepository(session).get(close_attempt_id)
    close_client_order_id = close_attempt.client_order_id

    # ---- the new opening signal, and the continuation seeded to await the close ----
    signal_id = uuid4()
    await _seed_signal(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        symbol="STXUSDT_PERP",
        price=Decimal("2"),
        position_size=Decimal("1"),
        received_at=START,
    )
    async with pg_session_factory() as session:
        await PostgresJobQueue(
            session,
            clock=clock,
            backoff_base_seconds=BACKOFF_BASE_SECONDS,
            backoff_max_seconds=BACKOFF_MAX_SECONDS,
        ).enqueue_unique(
            Job(
                kind=JobKind.SIGNAL_OPEN_AFTER_CLOSE,
                payload={
                    "signal_id": str(signal_id),
                    "awaited_allocation_ids": [str(allocation_id)],
                    "poll": 0,
                },
                run_after=clock.now(),
                dedupe_key=f"signal.open_after_close:{signal_id}:0",
            )
        )
        await session.commit()

    balance_reader = FakeSettlementBalanceReader(
        close_exchange=exchange,
        close_client_order_id=close_client_order_id,
        pool=POOL,
        before=BEFORE_REVEAL_BALANCE,
        after=AFTER_REVEAL_BALANCE,
        clock=clock,
    )
    pools_by_key = {
        POOL: PoolConfig(
            exchange=Exchange("bybit"),
            venue=Venue("usdt-m"),
            settlement_currency=Currency("USDT"),
            min_order_size=Decimal("1"),
        )
    }

    def _build_process_signal_handler(
        session: AsyncSession,
    ) -> tuple[ProcessSignalHandler, OpenAfterClose]:
        strategy_repository = SqlAlchemyStrategyRepository(session)
        signal_repository = SqlAlchemySignalRepository(session)
        reservation_repository = SqlAlchemyReservationRepository(session)
        attempts_repository = SqlAlchemyExecutionAttemptRepository(session)

        holding_guard = HoldingGuard(
            holdings=ReadSymbolHoldings(SqlAlchemyLedgerRepository(session)),
            in_flight_work=InFlightWorkAdapter(
                attempts=attempts_repository, reservations=reservation_repository
            ),
            venue_net_position=NeverCalledVenueNetPosition(),  # type: ignore[arg-type]
            clock=clock,
            delayed_open_max_signal_age_seconds=600.0,
        )
        balance_refresh = RefreshPoolBalance(
            reader=balance_reader,  # type: ignore[arg-type]
            snapshots=SqlAlchemyBalanceSnapshotRepository(session),
            age=DbBalanceSnapshotAge(session, clock),
            commit=session,
            timeout_seconds=3.0,
            fallback_max_age_seconds=90.0,
        )
        allocate_capital = AllocateCapital(
            strategy_policy=StrategyPolicyAdapter(strategy_repository),
            pool_balance=PoolBalanceAdapter(
                pools_by_key, DbBalanceSource(session, clock, max_age_seconds=999_999.0)
            ),
            lock=PgAdvisoryLockAdapter(session),
            reservations=reservation_repository,
            commit=session,
            clock=clock,
            reservation_ttl_seconds=30,
        )
        place_order = PlaceOrder(
            reservations=ReservationGatewayAdapter(reservation_repository),
            exchanges=registry,
            attempts=attempts_repository,
            queue=PostgresJobQueue(
                session,
                clock=clock,
                backoff_base_seconds=BACKOFF_BASE_SECONDS,
                backoff_max_seconds=BACKOFF_MAX_SECONDS,
            ),
            clock=clock,
            commit=session,
            settle_delay_seconds=0.0,
        )

        async def _open_now(this_signal_id: UUID, this_poll: int) -> object:
            return await handler.open_now(this_signal_id, this_poll)

        open_after_close = OpenAfterClose(
            signals=signal_repository,
            attempts=attempts_repository,
            queue=PostgresJobQueue(
                session,
                clock=clock,
                backoff_base_seconds=BACKOFF_BASE_SECONDS,
                backoff_max_seconds=BACKOFF_MAX_SECONDS,
            ),
            clock=clock,
            open_now=_open_now,
            settle_timeout_seconds=300.0,
            poll_interval_seconds=POLL_INTERVAL_SECONDS,
            max_signal_age_seconds=600.0,
        )
        handler = ProcessSignalHandler(
            signal_context=SignalContextAdapter(
                signals=signal_repository,
                strategies=strategy_repository,
                reservations=reservation_repository,
            ),
            strategy_policy=StrategyPolicyAdapter(strategy_repository),
            pool_balance=PoolBalanceAdapter(
                pools_by_key, DbBalanceSource(session, clock, max_age_seconds=999_999.0)
            ),
            holding_guard=holding_guard,
            balance_refresh=balance_refresh,
            allocate_capital=allocate_capital,
            place_order=place_order,
            close_position=NeverCalledClosePosition(),  # type: ignore[arg-type]
            open_after_close=NeverCalledSeeder(),
            commit=session,
            closing_attempts=attempts_repository,
            close_orphans=NeverCalledCloseOrphans(),
            tradable_pools=frozenset({("bybit", "usdt-m")}),
        )
        return handler, open_after_close

    async def handle_execution_settle(job: ClaimedJob) -> None:
        async with pg_session_factory() as session:
            settle = SettleExecution(
                reservations=SqlAlchemyReservationRepository(session),
                exchanges=registry,
                attempts=SqlAlchemyExecutionAttemptRepository(session),
                fill_recorder=RecordFill(SqlAlchemyLedgerRepository(session)),
                usd_rate_provider=FixedUsdRate(),
                clock=clock,
                commit=session,
            )
            await settle.settle(UUID(str(job.payload["execution_attempt_id"])))

    async def handle_signal_open_after_close(job: ClaimedJob) -> None:
        async with pg_session_factory() as session:
            _, open_after_close = _build_process_signal_handler(session)
            await open_after_close.poll(job)
            await session.commit()

    handlers: dict[JobKind, JobHandler] = {
        JobKind.EXECUTION_SETTLE: handle_execution_settle,
        JobKind.SIGNAL_OPEN_AFTER_CLOSE: handle_signal_open_after_close,
    }

    @asynccontextmanager
    async def queue_factory() -> AsyncIterator[PostgresJobQueue]:
        async with pg_session_factory() as session:
            yield PostgresJobQueue(
                session,
                clock=clock,
                backoff_base_seconds=BACKOFF_BASE_SECONDS,
                backoff_max_seconds=BACKOFF_MAX_SECONDS,
            )

    runner = WorkerRunner(
        queue_factory=queue_factory, handlers=handlers, poll_interval_seconds=POLL_INTERVAL_SECONDS
    )

    mid_flight_checked = False
    for round_index in range(20):
        if round_index > 0:
            clock.advance(1.0)
        while await runner.run_once():
            pass

        if round_index == 3:
            # fill_latency_polls=3 has consumed exactly its three empty
            # answers by now (t=3) -- the close must still be SUBMITTED,
            # and nothing must have opened yet.
            async with pg_session_factory() as session:
                mid_close = await SqlAlchemyExecutionAttemptRepository(session).get(
                    close_attempt_id
                )
                mid_reservation = await SqlAlchemyReservationRepository(session).find_by_signal_id(
                    signal_id
                )
            assert mid_close.status.value == "SUBMITTED"
            assert mid_reservation is None
            mid_flight_checked = True

    assert mid_flight_checked is True

    async with pg_session_factory() as session:
        final_close = await SqlAlchemyExecutionAttemptRepository(session).get(close_attempt_id)
        final_reservation = await SqlAlchemyReservationRepository(session).find_by_signal_id(
            signal_id
        )

    assert final_close.status.value == "FILLED"
    assert final_reservation is not None
    # The grant reflects the FRESH, post-reveal availability -- never the
    # stale 999 snapshot seeded before the close ever settled.
    assert final_reservation.amount == AFTER_REVEAL_BALANCE

    # The opening attempt PlaceOrder inserted, keyed by the reservation it
    # spends -- proves the open's own row was created strictly after the
    # close's row was marked FILLED.
    async with pg_session_factory() as session:
        opened_row = (
            await session.execute(
                select(ExecutionAttemptRow).where(
                    ExecutionAttemptRow.reservation_id == final_reservation.id
                )
            )
        ).scalar_one()

    assert opened_row.created_at > final_close.updated_at
