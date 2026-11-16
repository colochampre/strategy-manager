"""Subscriber-safety SS.7 on real PostgreSQL: a stop that fired at the venue is booked by the
stop watcher under the stop's allocation, in ONE transaction, and two runs that both read the
fired stop book it once.

The production ``WatchProtectiveStops`` runs on real sessions with the production
repositories, the production pool lock and the production ledger recorder; only the venue is
replaced, by a simulated exchange whose ``read_stop`` answers what the test scripts. What the
unit tests cannot show is shown here: the attempt, the ledger rows and the ``FIRED`` mark land
on one commit, the booked allocation reads flat in the ledger's own projection, and the
second of two concurrent runs WAITS on the pool lock and then finds the stop already decided
(proved with the lock-hold harness: ``not task.done()``, never a ``sleep(0)`` barrier).
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.allocation.infrastructure.reservation_gateway import (
    ReservationGatewayAdapter,
)
from strategy_manager.execution.application.ports import (
    StopFired,
    StopNotResting,
    StopReading,
)
from strategy_manager.execution.application.watch_protective_stops import (
    WatchProtectiveStops,
    WatchResult,
)
from strategy_manager.execution.domain.execution_attempt import ExecutionCause
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.protective_stop import ProtectiveStop, StopStatus
from strategy_manager.execution.infrastructure.exchange_registry import VenueExchangeRegistry
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
    SqlAlchemyProtectiveStopRepository,
)
from strategy_manager.ledger.application.read_held_base import ReadHeldBase
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.main import _end_leaving
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.usd_rate import FixedUsdRateProvider
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from tests.allocation.fakes import RecordedModes
from tests.execution.fakes import OneRegistry
from tests.owner import OWNER_ID
from tests.signals.infrastructure.test_protective_stop_flow_integration import (
    _confirm,
    _opened_and_settled,
    _StopExchange,
    _stops,
)

pytestmark = pytest.mark.integration

_BASE = "STX"
_STOP_ORDER = "STOP-ORDER-77"
_FILLED_AT = datetime(2026, 11, 13, 12, 30, 0, tzinfo=UTC)
_POOL_KEY = LockKey.from_pool_key(
    OWNER_ID,
    PoolKey(
        exchange=Exchange("bybit"), venue=Venue("usdt-m"), settlement_currency=Currency("USDT")
    ),
)


class _WatchedExchange(_StopExchange):
    """The simulated venue, with what ``read_stop`` answers scripted by the test."""

    def __init__(self) -> None:
        super().__init__(resting="STOP-1")
        self.reading: StopReading | None = None
        self.reads = 0

    async def read_stop(self, stop: ProtectiveStop, parent_client_order_id: str) -> StopReading:
        self.reads += 1
        assert self.reading is not None
        return self.reading


def _watcher(session: AsyncSession, exchange: _WatchedExchange) -> WatchProtectiveStops:
    @asynccontextmanager
    async def exchanges_for(user_id: UUID) -> AsyncIterator[OneRegistry]:
        assert user_id == OWNER_ID
        yield OneRegistry(VenueExchangeRegistry([exchange]))

    return WatchProtectiveStops(
        stops=SqlAlchemyProtectiveStopRepository(session),
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        reservations=ReservationGatewayAdapter(SqlAlchemyReservationRepository(session)),
        held=ReadHeldBase(SqlAlchemyLedgerRepository(session)),
        fill_recorder=RecordFill(SqlAlchemyLedgerRepository(session)),
        usd_rates=FixedUsdRateProvider({Currency.USDT: Decimal("1")}),
        pool_lock=PoolLockAdapter(session),
        leaving=_end_leaving(session),
        allocation_modes=RecordedModes(),
        exchanges_for=exchanges_for,  # type: ignore[arg-type]
        unit_of_work=session,
    )


async def _net(factory: async_sessionmaker[AsyncSession], allocation_id: UUID) -> Decimal:
    async with factory() as session:
        return await ReadHeldBase(SqlAlchemyLedgerRepository(session)).net_base(
            OWNER_ID, allocation_id, _BASE
        )


async def _resting(
    factory: async_sessionmaker[AsyncSession], exchange: _WatchedExchange
) -> tuple[UUID, UUID, Decimal]:
    """An opening placed, settled and confirmed: ``(allocation, attempt, held quantity)``."""
    allocation_id, attempt_id = await _opened_and_settled(factory, exchange)
    async with factory() as session:
        result = await _confirm(session, exchange).confirm(OWNER_ID, attempt_id)
    assert result.status == "RESTING"
    held = await _net(factory, allocation_id)
    assert held > 0
    return allocation_id, attempt_id, held


def _stop_fills(quantity: Decimal, parts: int = 2) -> list[Fill]:
    first = (quantity / parts).quantize(Decimal("0.000001"))
    quantities = [first] * (parts - 1) + [quantity - first * (parts - 1)]
    return [
        Fill(
            exchange_order_id=_STOP_ORDER,
            exchange_fill_id=f"stop-fill-{index}",
            quantity=part,
            price=Decimal("1.8"),
            fee=Decimal("0.001") * (index + 1),
            fee_currency="USDT",
            filled_at=_FILLED_AT,
        )
        for index, part in enumerate(quantities)
    ]


async def _ledger(factory: async_sessionmaker[AsyncSession]) -> list[LedgerEntryRow]:
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(LedgerEntryRow).order_by(LedgerEntryRow.exchange_fill_id)
                )
            ).scalars()
        )


async def _attempts(factory: async_sessionmaker[AsyncSession]) -> list[ExecutionAttemptRow]:
    async with factory() as session:
        return list((await session.execute(select(ExecutionAttemptRow))).scalars())


async def test_a_fired_stop_is_booked_in_one_transaction_and_the_allocation_reads_flat(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    exchange = _WatchedExchange()
    allocation_id, attempt_id, held = await _resting(pg_session_factory, exchange)
    ledger_before = len(await _ledger(pg_session_factory))
    exchange.reading = StopFired(exchange_order_id=_STOP_ORDER, fills=_stop_fills(held))

    with caplog.at_level(logging.INFO):
        async with pg_session_factory() as session:
            result = await _watcher(session, exchange).watch()

    assert result == WatchResult(read=1, fired=1)

    # The stop is FIRED, and the allocation reads flat in the ledger's own projection.
    [stop] = await _stops(pg_session_factory)
    assert stop.status == StopStatus.FIRED.value
    assert await _net(pg_session_factory, allocation_id) == 0

    # The attempt carries the fills with cause STOP, as the user, on the stop's allocation.
    [opening, closing] = sorted(
        await _attempts(pg_session_factory), key=lambda row: row.closes_allocation_id is not None
    )
    assert opening.id == attempt_id
    assert opening.cause == ExecutionCause.SIGNAL.value
    assert closing.cause == ExecutionCause.STOP.value
    assert (closing.user_id, closing.status, closing.origin) == (OWNER_ID, "FILLED", "SYSTEM")
    assert closing.closes_allocation_id == allocation_id
    assert closing.reservation_id is None
    assert closing.client_order_id == f"stop-{stop.id}"
    assert closing.exchange_order_id == _STOP_ORDER
    assert (closing.side, closing.quantity) == ("SELL", held)

    # One ledger row per fill, under the allocation and the closing attempt.
    ledger = await _ledger(pg_session_factory)
    rows = [row for row in ledger if row.execution_attempt_id == closing.id]
    assert len(ledger) == ledger_before + 2
    assert [(row.exchange_fill_id, row.side, row.allocation_id) for row in rows] == [
        ("stop-fill-0", "SELL", allocation_id),
        ("stop-fill-1", "SELL", allocation_id),
    ]
    assert [row.fee for row in rows] == [Decimal("0.001"), Decimal("0.002")]
    assert all(row.fee_currency == "USDT" for row in rows)
    assert all(row.exchange_order_id == _STOP_ORDER for row in rows)

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and warnings[0].startswith("protective stop fired")


async def test_a_stop_gone_with_its_position_books_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    exchange = _WatchedExchange()
    allocation_id, _, held = await _resting(pg_session_factory, exchange)
    exchange.reading = StopNotResting()
    ledger_before = len(await _ledger(pg_session_factory))

    async with pg_session_factory() as session:
        result = await _watcher(session, exchange).watch()

    assert result == WatchResult(read=1, gone=1)
    [stop] = await _stops(pg_session_factory)
    assert stop.status == StopStatus.GONE.value
    assert len(await _ledger(pg_session_factory)) == ledger_before
    assert len(await _attempts(pg_session_factory)) == 1
    assert await _net(pg_session_factory, allocation_id) == held


async def _blocked_on_the_pool_lock(
    factory: async_sessionmaker[AsyncSession], waiters: int
) -> bool:
    async with factory() as session:
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM pg_locks "
                    "WHERE locktype = 'advisory' AND NOT granted "
                    "AND classid::bigint = (hashtext(:first)::bigint & 4294967295) "
                    "AND objid::bigint = (hashtext(:second)::bigint & 4294967295)"
                ),
                {"first": _POOL_KEY.first, "second": _POOL_KEY.second},
            )
        ).scalar_one()
    return int(count) >= waiters


async def _until_blocked(factory: async_sessionmaker[AsyncSession], waiters: int) -> None:
    deadline = asyncio.get_running_loop().time() + 15
    while not await _blocked_on_the_pool_lock(factory, waiters):
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for {waiters} run(s) on the pool lock")
        await asyncio.sleep(0.02)


async def test_two_runs_that_both_read_the_fired_stop_book_it_once(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Both runs read FIRED outside the lock, then queue on the user's pool lock. The first
    through books it; the second takes the lock after the commit, finds the stop no longer
    RESTING and books nothing."""
    exchange = _WatchedExchange()
    allocation_id, _, held = await _resting(pg_session_factory, exchange)
    exchange.reading = StopFired(exchange_order_id=_STOP_ORDER, fills=_stop_fills(held))
    ledger_before = len(await _ledger(pg_session_factory))
    results: list[WatchResult] = []

    async def run() -> None:
        async with pg_session_factory() as session:
            results.append(await _watcher(session, exchange).watch())

    async with pg_session_factory() as holder:
        # The pool lock, held by a third transaction: both runs get past the venue read and
        # then WAIT, which is the interleaving the test is about.
        await PoolLockAdapter(holder).acquire(OWNER_ID, "bybit", "usdt-m", "USDT")
        first: asyncio.Task[Any] = asyncio.create_task(run())
        second: asyncio.Task[Any] = asyncio.create_task(run())
        await _until_blocked(pg_session_factory, 2)
        assert not first.done() and not second.done(), (
            "a run decided a stop without the pool lock: the harness proves nothing"
        )
        assert exchange.reads == 2
        assert await _net(pg_session_factory, allocation_id) == held
        await holder.rollback()

    await asyncio.wait_for(asyncio.gather(first, second), timeout=15)

    assert sorted((r.fired, r.skipped) for r in results) == [(0, 1), (1, 0)]
    assert await _net(pg_session_factory, allocation_id) == 0
    assert len(await _ledger(pg_session_factory)) == ledger_before + 2
    closing = [row for row in await _attempts(pg_session_factory) if row.cause == "STOP"]
    assert len(closing) == 1
    [stop] = await _stops(pg_session_factory)
    assert stop.status == StopStatus.FIRED.value
