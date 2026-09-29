"""Decision 25, tasks 5b.6 and 5b.7 on real PostgreSQL: the outcome a
``PlaceOrder`` / ``ClosePosition`` step records lands in the SAME commit as
the write that decided it, or not at all (design.md "Addendum: signal
outcomes" section C, the same-commit rule).

A fake commit cannot prove that, so these run the production use cases and the
production outcome adapter on ONE real session, with a commit that can be told
to fail. A failing commit is modelled the way the driver leaves it: the
transaction is rolled back and the error raised. Each scenario is asserted
both ways -- fault on the deciding commit (nothing lands) and no fault (both
land, with the exact commit count) -- because the second is what catches an
outcome moved onto a commit of its own: a fault on the first commit would roll
back an outcome that had not been written yet and still look atomic.

Three spellings of one market cross the module boundaries on purpose:
TradingView ``STXUSDT.P`` reaches the venue-facing commands, the signal row
keeps Pionex's ``STXUSDT_PERP``, and the ledger holds the bare ``STXUSDT``.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.allocation.infrastructure.reservation_gateway import (
    ReservationGatewayAdapter,
)
from strategy_manager.execution.application.close_position import CloseCommand, ClosePosition
from strategy_manager.execution.application.place_order import PlaceCommand, PlaceOrder
from strategy_manager.execution.application.ports import FillRecord, OrderNotPlaceable
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.exchange_registry import VenueExchangeRegistry
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_held_base import ReadHeldBase
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.models import JobRow
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.order_outcome_recorder import (
    SignalOrderOutcomeRecorder,
)
from strategy_manager.signals.infrastructure.outcome_repository import (
    SqlAlchemySignalOutcomeAdapter,
)
from tests.signals.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal_row,
    seed_strategy,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)
_TRADINGVIEW = "STXUSDT.P"
_PIONEX = "STXUSDT_PERP"
_VENUE_BARE = "STXUSDT"


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


class _FaultyCommit:
    """Commits for real, except on the ``fail_on``-th call: there it rolls the
    session back and raises, which is what a failed COMMIT leaves behind."""

    def __init__(self, session: AsyncSession, fail_on: int | None) -> None:
        self._session = session
        self._fail_on = fail_on
        self.calls = 0

    async def commit(self) -> None:
        self.calls += 1
        if self.calls == self._fail_on:
            await self._session.rollback()
            raise RuntimeError("injected commit failure")
        await self._session.commit()


class _DustExchange(FakeExchangeAdapter):
    """A venue whose catalogue makes the held residual impossible to close."""

    async def build_close_order(self, spec):  # type: ignore[no-untyped-def]
        raise OrderNotPlaceable(
            "STXUSDT residual is below one tradable unit",
            symbol="STXUSDT",
            size=Decimal("0"),
            minimum=Decimal("1"),
            step=Decimal("1"),
        )


def _place_order(
    session: AsyncSession, commit: _FaultyCommit, exchange: FakeExchangeAdapter | None = None
) -> PlaceOrder:
    return PlaceOrder(
        reservations=ReservationGatewayAdapter(SqlAlchemyReservationRepository(session)),
        exchanges=VenueExchangeRegistry([exchange or FakeExchangeAdapter(exchange="bybit")]),
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        queue=PostgresJobQueue(session, clock=_FixedClock()),
        clock=_FixedClock(),
        commit=commit,
        settle_delay_seconds=0.0,
        outcomes=SignalOrderOutcomeRecorder(
            SqlAlchemySignalOutcomeAdapter(session, _FixedClock())
        ),
    )


def _close_position(
    session: AsyncSession, commit: _FaultyCommit, exchange: FakeExchangeAdapter
) -> ClosePosition:
    return ClosePosition(
        exchanges=VenueExchangeRegistry([exchange]),
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        held=ReadHeldBase(SqlAlchemyLedgerRepository(session)),
        queue=PostgresJobQueue(session, clock=_FixedClock()),
        clock=_FixedClock(),
        commit=commit,
        settle_delay_seconds=0.0,
        outcomes=SignalOrderOutcomeRecorder(
            SqlAlchemySignalOutcomeAdapter(session, _FixedClock())
        ),
    )


async def _signal(
    factory: async_sessionmaker[AsyncSession], signal_id: UUID
) -> SignalRow:
    async with factory() as session:
        return (
            await session.execute(select(SignalRow).where(SignalRow.id == signal_id))
        ).scalar_one()


async def _reservation(
    factory: async_sessionmaker[AsyncSession], reservation_id: UUID
) -> ReservationRow:
    async with factory() as session:
        return (
            await session.execute(
                select(ReservationRow).where(ReservationRow.id == reservation_id)
            )
        ).scalar_one()


async def _attempts(
    factory: async_sessionmaker[AsyncSession],
) -> list[ExecutionAttemptRow]:
    async with factory() as session:
        return list((await session.execute(select(ExecutionAttemptRow))).scalars())


async def _seed_open(
    factory: async_sessionmaker[AsyncSession], *, expires_at: datetime
) -> tuple[UUID, UUID, UUID]:
    """A strategy, the signal that wants to open, and its PENDING reservation."""
    strategy_id, signal_id, reservation_id = uuid4(), uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await seed_signal_row(
        factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"open-{signal_id}",
        symbol=_PIONEX,
    )
    await seed_reservation(
        factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        status="PENDING",
        expires_at=expires_at,
    )
    return strategy_id, signal_id, reservation_id


def _place_command(reservation_id: UUID) -> PlaceCommand:
    return PlaceCommand(
        reservation_id=reservation_id,
        symbol=_TRADINGVIEW,
        side=OrderSide.BUY,
        price=Decimal("2"),
    )


# ---- 5b.6: PlaceOrder ------------------------------------------------------


async def test_an_expired_reservation_release_and_rejection_land_in_one_commit(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, signal_id, reservation_id = await _seed_open(
        pg_session_factory, expires_at=_NOW - timedelta(minutes=1)
    )

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=None)
        result = await _place_order(session, commit).place(_place_command(reservation_id))

    assert result.status == "ABORTED_EXPIRED"
    assert commit.calls == 1  # the outcome is NOT on a commit of its own
    signal = await _signal(pg_session_factory, signal_id)
    assert signal.status == "REJECTED"
    assert signal.outcome_reason == "RESERVATION_EXPIRED_BEFORE_SUBMIT"
    assert signal.outcome_detail is not None and str(reservation_id) in signal.outcome_detail
    assert signal.decided_at == _NOW
    assert (await _reservation(pg_session_factory, reservation_id)).status == "RELEASED"


async def test_a_failed_commit_loses_the_release_and_the_rejection_together(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, signal_id, reservation_id = await _seed_open(
        pg_session_factory, expires_at=_NOW - timedelta(minutes=1)
    )

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=1)
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await _place_order(session, commit).place(_place_command(reservation_id))

    signal = await _signal(pg_session_factory, signal_id)
    assert signal.status == "ACCEPTED"
    assert signal.outcome_reason is None and signal.decided_at is None
    assert (await _reservation(pg_session_factory, reservation_id)).status == "PENDING"


async def test_a_placed_order_and_processing_land_in_the_same_final_commit(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, signal_id, reservation_id = await _seed_open(
        pg_session_factory, expires_at=_NOW + timedelta(hours=1)
    )

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=None)
        result = await _place_order(session, commit).place(_place_command(reservation_id))

    assert result.status == "PLACED"
    assert commit.calls == 2  # pre-network SUBMITTED, then placed + PROCESSING
    signal = await _signal(pg_session_factory, signal_id)
    assert signal.status == "PROCESSING"
    assert signal.decided_at is None  # interim, not decided
    [attempt] = await _attempts(pg_session_factory)
    assert attempt.exchange_order_id == result.exchange_order_id


async def test_a_failed_final_commit_loses_the_placed_mark_and_processing_together(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The pre-network commit (attempt SUBMITTED, reservation SUBMITTED) is
    durable by then; only the placed mark and the signal move together."""
    _, signal_id, reservation_id = await _seed_open(
        pg_session_factory, expires_at=_NOW + timedelta(hours=1)
    )

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=2)
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await _place_order(session, commit).place(_place_command(reservation_id))

    assert (await _signal(pg_session_factory, signal_id)).status == "ACCEPTED"
    [attempt] = await _attempts(pg_session_factory)
    assert attempt.status == "SUBMITTED"
    assert attempt.exchange_order_id is None
    assert (await _reservation(pg_session_factory, reservation_id)).status == "SUBMITTED"


# ---- 5b.7: ClosePosition ---------------------------------------------------


async def _seed_close(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID, UUID]:
    """An open long of 1 STX under one allocation, and the NEW signal that
    asks to close it. Returns (strategy_id, closing_signal_id, allocation_id)."""
    strategy_id, opening_signal_id, closing_signal_id = uuid4(), uuid4(), uuid4()
    allocation_id, opening_attempt_id = uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await seed_signal_row(
        factory,
        signal_id=opening_signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"opening-{opening_signal_id}",
        symbol=_PIONEX,
    )
    await seed_signal_row(
        factory,
        signal_id=closing_signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"closing-{closing_signal_id}",
        symbol=_PIONEX,
    )
    await seed_reservation(
        factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=opening_signal_id,
        status="FILLED",
    )
    await seed_execution_attempt(
        factory,
        attempt_id=opening_attempt_id,
        reservation_id=allocation_id,
        symbol=_VENUE_BARE,
        status="FILLED",
    )
    async with factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            FillRecord(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                execution_attempt_id=opening_attempt_id,
                exchange="bybit",
                venue="usdt-m",
                settlement_currency="USDT",
                symbol=_VENUE_BARE,
                side="BUY",
                quantity=Decimal("1"),
                price=Decimal("2"),
                fee=Decimal("0"),
                fee_currency="USDT",
                notional=Decimal("2"),
                exchange_order_id=f"opening-order-{opening_attempt_id}",
                exchange_fill_id=f"opening-fill-{opening_attempt_id}",
                filled_at=_NOW - timedelta(hours=1),
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()
    return strategy_id, closing_signal_id, allocation_id


def _close_command(
    strategy_id: UUID, allocation_id: UUID, signal_id: UUID | None
) -> CloseCommand:
    return CloseCommand(
        allocation_id=allocation_id,
        strategy_id=strategy_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=_TRADINGVIEW,
        side=OrderSide.SELL,
        signal_id=signal_id,
    )


async def _closing_attempts(
    factory: async_sessionmaker[AsyncSession], allocation_id: UUID
) -> list[ExecutionAttemptRow]:
    return [
        a
        for a in await _attempts(factory)
        if a.closes_allocation_id == allocation_id
    ]


async def test_a_placed_close_and_processing_land_in_the_same_final_commit(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, signal_id, allocation_id = await _seed_close(pg_session_factory)

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=None)
        result = await _close_position(
            session, commit, FakeExchangeAdapter(exchange="bybit")
        ).close(_close_command(strategy_id, allocation_id, signal_id))

    assert result.status == "PLACED"
    assert commit.calls == 2
    signal = await _signal(pg_session_factory, signal_id)
    assert signal.status == "PROCESSING"
    [attempt] = await _closing_attempts(pg_session_factory, allocation_id)
    assert attempt.exchange_order_id == result.exchange_order_id


async def test_a_failed_final_commit_loses_the_close_placed_mark_and_processing_together(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, signal_id, allocation_id = await _seed_close(pg_session_factory)

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=2)
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await _close_position(
                session, commit, FakeExchangeAdapter(exchange="bybit")
            ).close(_close_command(strategy_id, allocation_id, signal_id))

    assert (await _signal(pg_session_factory, signal_id)).status == "ACCEPTED"
    [attempt] = await _closing_attempts(pg_session_factory, allocation_id)
    assert attempt.status == "SUBMITTED"
    assert attempt.exchange_order_id is None


async def test_a_dust_close_rejection_and_the_staged_seed_land_in_the_added_commit(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Row 13 has no attempt to write; the commit added at this branch makes
    the outcome durable together with whatever the caller staged before the
    call. A job stands in for the continuation seed a REVERSE stages."""
    strategy_id, signal_id, allocation_id = await _seed_close(pg_session_factory)

    async with pg_session_factory() as session:
        await PostgresJobQueue(session, clock=_FixedClock()).enqueue(
            Job(kind=JobKind.SIGNAL_PROCESS, payload={"staged": "before the close"})
        )
        commit = _FaultyCommit(session, fail_on=None)
        result = await _close_position(
            session, commit, _DustExchange(exchange="bybit")
        ).close(_close_command(strategy_id, allocation_id, signal_id))

    assert result.status == "NOT_CLOSABLE"
    assert commit.calls == 1
    signal = await _signal(pg_session_factory, signal_id)
    assert signal.status == "REJECTED"
    assert signal.outcome_reason == "CLOSE_DUST_NOT_CLOSABLE"
    assert signal.decided_at == _NOW
    assert await _closing_attempts(pg_session_factory, allocation_id) == []
    async with pg_session_factory() as session:
        jobs = (await session.execute(select(JobRow))).scalars().all()
    assert len(jobs) == 1


async def test_a_failed_dust_commit_loses_the_rejection_and_the_staged_seed_together(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, signal_id, allocation_id = await _seed_close(pg_session_factory)

    async with pg_session_factory() as session:
        await PostgresJobQueue(session, clock=_FixedClock()).enqueue(
            Job(kind=JobKind.SIGNAL_PROCESS, payload={"staged": "before the close"})
        )
        commit = _FaultyCommit(session, fail_on=1)
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await _close_position(
                session, commit, _DustExchange(exchange="bybit")
            ).close(_close_command(strategy_id, allocation_id, signal_id))

    assert (await _signal(pg_session_factory, signal_id)).status == "ACCEPTED"
    async with pg_session_factory() as session:
        assert (await session.execute(select(JobRow))).scalars().all() == []


async def test_a_close_with_no_signal_leaves_every_signal_untouched(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An orphan close (``signal_id=None``) places its order and commits, and
    no signal row changes."""
    strategy_id, signal_id, allocation_id = await _seed_close(pg_session_factory)

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=None)
        result = await _close_position(
            session, commit, FakeExchangeAdapter(exchange="bybit")
        ).close(_close_command(strategy_id, allocation_id, None))

    assert result.status == "PLACED"
    assert commit.calls == 2
    signal = await _signal(pg_session_factory, signal_id)
    assert (signal.status, signal.outcome_reason) == ("ACCEPTED", None)
