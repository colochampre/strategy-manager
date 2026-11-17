"""Subscriber-safety SS.10 on real PostgreSQL: each safety event is written in the SAME
transaction as the change it reports, once.

The production ``SettleExecution``, ``ClosePosition``, ``ConfirmProtectiveStop`` and
``WatchProtectiveStops`` run on real sessions with the production repositories and the
production event writer; only the venue is replaced. What the unit tests cannot show is shown
here:

* ``STOP_FIRED`` rides the commit that books the stop's fills, and a second pass over the same
  stop writes no second row;
* ``MANUAL_CLOSE``, ``STOP_FAILED_CLOSED`` and ``STRATEGY_STOPPED_CLOSED`` ride the commit that
  books a closing attempt's fills, are told apart by the attempt's cause and the allocation's
  stop, and a re-run of the settle writes no second row;
* a close the signal asked for writes nothing;
* a commit that fails loses the event with the fills, and writing the same source twice is a
  no-op, not an error;
* an opening refused for its leverage names its delivery as its source, with no allocation.
"""

import logging
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.close_position import CloseCommand
from strategy_manager.execution.application.ports import StopFired
from strategy_manager.execution.domain.execution_attempt import ExecutionCause
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.domain.protective_stop import StopStatus
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.safety.infrastructure.models import SafetyEventRow
from strategy_manager.safety.infrastructure.repository import SqlAlchemySafetyEventWriter
from strategy_manager.shared.domain.safety_event import NewSafetyEvent, SafetyEventKind
from strategy_manager.shared.infrastructure.clock import SystemClock
from tests.owner import OWNER_ID
from tests.signals.infrastructure.test_protective_stop_flow_integration import (
    _confirm,
    _StopExchange,
    _stops,
)
from tests.signals.infrastructure.test_protective_stop_watch_integration import (
    _STOP_ORDER,
    _net,
    _resting,
    _stop_fills,
    _WatchedExchange,
    _watcher,
)
from tests.signals.infrastructure.test_settle_outcomes_integration import (
    _attempts,
    _close_position,
    _delivery_of,
    _FaultyCommit,
    _place_open,
    _seed_open,
    _seed_position,
    _settle,
)

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]


async def _events(factory: Factory) -> list[SafetyEventRow]:
    async with factory() as session:
        return list(
            (
                await session.execute(select(SafetyEventRow).order_by(SafetyEventRow.occurred_at))
            ).scalars()
        )


async def _opened_position(factory: Factory, exchange: FakeExchangeAdapter) -> tuple[UUID, UUID]:
    """An opening placed and settled: ``(strategy_id, allocation_id)``."""
    strategy_id, _, allocation_id = await _seed_open(factory)
    await _place_open(factory, exchange, allocation_id)
    [attempt] = await _attempts(factory)
    async with factory() as session:
        await _settle(session, _FaultyCommit(session, fail_on=None), exchange).settle(
            OWNER_ID, attempt.id
        )
    return strategy_id, allocation_id


async def _close_as(
    factory: Factory,
    exchange: FakeExchangeAdapter,
    strategy_id: UUID,
    allocation_id: UUID,
    cause: ExecutionCause,
) -> ExecutionAttemptRow:
    """Places the close the way ``cause`` asks for it, and answers its SUBMITTED attempt."""
    async with factory() as session:
        result = await _close_position(session, exchange).close(
            CloseCommand(
                user_id=OWNER_ID,
                allocation_id=allocation_id,
                strategy_id=strategy_id,
                exchange="bybit",
                venue="usdt-m",
                settlement_currency="USDT",
                symbol="STXUSDT.P",
                side=OrderSide.SELL,
                signal_id=None,
                delivery_id=None,
                reference_price=None,
                cause=cause,
            )
        )
    assert result.status == "PLACED"
    [closing] = [a for a in await _attempts(factory) if a.closes_allocation_id == allocation_id]
    return closing


async def _settle_attempt(factory: Factory, exchange: FakeExchangeAdapter, attempt_id: UUID) -> str:
    async with factory() as session:
        result = await _settle(session, _FaultyCommit(session, fail_on=None), exchange).settle(
            OWNER_ID, attempt_id
        )
    return result.status


async def _close_fills(factory: Factory, attempt_id: UUID) -> list[LedgerEntryRow]:
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(LedgerEntryRow).where(LedgerEntryRow.execution_attempt_id == attempt_id)
                )
            ).scalars()
        )


# ---- STOP_FIRED ------------------------------------------------------------------------


async def test_a_fired_stop_writes_stop_fired_with_the_commit_that_books_it_and_only_once(
    pg_session_factory: Factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    exchange = _WatchedExchange()
    allocation_id, opening_id, held = await _resting(pg_session_factory, exchange)
    [stop_before] = await _stops(pg_session_factory)
    exchange.reading = StopFired(exchange_order_id=_STOP_ORDER, fills=_stop_fills(held))
    assert await _events(pg_session_factory) == []

    with caplog.at_level(logging.INFO):
        async with pg_session_factory() as session:
            await _watcher(session, exchange).watch()
        async with pg_session_factory() as session:
            second = await _watcher(session, exchange).watch()

    assert second.read == 0
    [event] = await _events(pg_session_factory)
    [booked] = [a for a in await _attempts(pg_session_factory) if a.cause == "STOP"]
    opening = next(a for a in await _attempts(pg_session_factory) if a.id == opening_id)
    assert (event.user_id, event.kind, event.allocation_id) == (
        OWNER_ID,
        "STOP_FIRED",
        allocation_id,
    )
    assert event.execution_attempt_id == booked.id and event.delivery_id is None
    assert opening.symbol == "STXUSDT.P"
    assert (event.exchange, event.venue, event.symbol) == ("bybit", "usdt-m", "STXUSDT")
    assert event.detail == {
        "quantity": format(held, "f"),
        "trigger_price": format(stop_before.trigger_price, "f"),
    }
    assert event.occurred_at is not None
    assert await _net(pg_session_factory, allocation_id) == 0


async def test_a_stop_fired_commit_that_fails_loses_the_event_with_the_fills(
    pg_session_factory: Factory,
) -> None:
    exchange = _WatchedExchange()
    allocation_id, _, held = await _resting(pg_session_factory, exchange)
    exchange.reading = StopFired(exchange_order_id=_STOP_ORDER, fills=_stop_fills(held))

    class FailingUnitOfWork:
        def __init__(self, session: AsyncSession) -> None:
            self._session = session

        async def commit(self) -> None:
            await self._session.rollback()
            raise RuntimeError("injected commit failure")

        async def rollback(self) -> None:
            await self._session.rollback()

    async with pg_session_factory() as session:
        watcher = _watcher(session, exchange)
        watcher._uow = FailingUnitOfWork(session)  # type: ignore[assignment]
        result = await watcher.watch()

    assert result.failed == 1
    assert await _events(pg_session_factory) == []
    [stop] = await _stops(pg_session_factory)
    assert stop.status == StopStatus.RESTING.value
    assert await _net(pg_session_factory, allocation_id) == held


# ---- the three closes -----------------------------------------------------------------


async def test_a_manual_close_writes_manual_close_on_the_fills_commit_and_a_rerun_adds_none(
    pg_session_factory: Factory,
) -> None:
    exchange = _StopExchange(resting="STOP-1")
    strategy_id, allocation_id = await _opened_position(pg_session_factory, exchange)
    closing = await _close_as(
        pg_session_factory, exchange, strategy_id, allocation_id, ExecutionCause.MANUAL
    )

    assert await _settle_attempt(pg_session_factory, exchange, closing.id) == "FILLED"
    assert await _settle_attempt(pg_session_factory, exchange, closing.id) == "ALREADY_SETTLED"

    [event] = await _events(pg_session_factory)
    fills = await _close_fills(pg_session_factory, closing.id)
    assert len(fills) == 1
    assert (event.user_id, event.kind, event.strategy_id, event.allocation_id) == (
        OWNER_ID,
        "MANUAL_CLOSE",
        strategy_id,
        allocation_id,
    )
    assert event.execution_attempt_id == closing.id
    # The attempt carries the alert's spelling; the event carries the bare market.
    assert closing.symbol == "STXUSDT.P"
    assert (event.exchange, event.venue, event.symbol) == ("bybit", "usdt-m", "STXUSDT")
    # The ledger stores scaled numerics, the event the plain text of the fill's own figure.
    assert set(event.detail) == {"quantity", "price"}
    assert Decimal(event.detail["quantity"]) == fills[0].quantity
    assert Decimal(event.detail["price"]) == fills[0].price


async def test_a_safety_close_after_a_stop_that_could_not_be_shown_writes_stop_failed_closed(
    pg_session_factory: Factory,
) -> None:
    """The confirm job marks the stop FAILED and closes the position at once; its close
    carries cause SAFETY_CLOSE, and the allocation's stop is what tells the two safety
    closes apart."""
    exchange = _StopExchange(resting=None)
    _, allocation_id = await _opened_position(pg_session_factory, exchange)
    [opening] = await _attempts(pg_session_factory)
    async with pg_session_factory() as session:
        assert (await _confirm(session, exchange).confirm(OWNER_ID, opening.id)).status == "CLOSING"
    [closing] = [
        a for a in await _attempts(pg_session_factory) if a.closes_allocation_id == allocation_id
    ]
    assert closing.cause == ExecutionCause.SAFETY_CLOSE.value
    assert await _events(pg_session_factory) == []

    await _settle_attempt(pg_session_factory, exchange, closing.id)

    [event] = await _events(pg_session_factory)
    assert (event.kind, event.allocation_id) == ("STOP_FAILED_CLOSED", allocation_id)
    assert event.execution_attempt_id == closing.id
    assert set(event.detail) == {"quantity", "price"}


async def test_a_safety_close_of_a_position_whose_stop_rests_is_strategy_stopped_closed(
    pg_session_factory: Factory,
) -> None:
    exchange = _StopExchange(resting="STOP-1")
    strategy_id, allocation_id = await _opened_position(pg_session_factory, exchange)
    closing = await _close_as(
        pg_session_factory, exchange, strategy_id, allocation_id, ExecutionCause.SAFETY_CLOSE
    )

    await _settle_attempt(pg_session_factory, exchange, closing.id)

    [event] = await _events(pg_session_factory)
    assert (event.kind, event.allocation_id) == ("STRATEGY_STOPPED_CLOSED", allocation_id)
    assert event.execution_attempt_id == closing.id


async def test_a_close_the_signal_asked_for_and_an_opening_write_no_event(
    pg_session_factory: Factory,
) -> None:
    exchange = FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))
    strategy_id, _, closing_signal, allocation_id = await _seed_position(
        pg_session_factory, closing_position_size="0"
    )
    delivery_id = await _delivery_of(pg_session_factory, closing_signal)
    async with pg_session_factory() as session:
        await _close_position(session, exchange).close(
            CloseCommand(
                user_id=OWNER_ID,
                allocation_id=allocation_id,
                strategy_id=strategy_id,
                exchange="bybit",
                venue="usdt-m",
                settlement_currency="USDT",
                symbol="STXUSDT.P",
                side=OrderSide.SELL,
                signal_id=closing_signal,
                delivery_id=delivery_id,
                reference_price=Decimal("0.4633"),
                cause=ExecutionCause.SIGNAL,
            )
        )
    [closing] = [
        a for a in await _attempts(pg_session_factory) if a.closes_allocation_id == allocation_id
    ]

    assert await _settle_attempt(pg_session_factory, exchange, closing.id) == "FILLED"

    assert await _events(pg_session_factory) == []


async def test_a_close_settle_whose_commit_fails_loses_the_event_with_the_fills(
    pg_session_factory: Factory,
) -> None:
    exchange = _StopExchange(resting="STOP-1")
    strategy_id, allocation_id = await _opened_position(pg_session_factory, exchange)
    closing = await _close_as(
        pg_session_factory, exchange, strategy_id, allocation_id, ExecutionCause.MANUAL
    )
    fills_before = len(await _close_fills(pg_session_factory, closing.id))

    async with pg_session_factory() as session:
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await _settle(session, _FaultyCommit(session, fail_on=1), exchange).settle(
                OWNER_ID, closing.id
            )

    assert await _events(pg_session_factory) == []
    assert len(await _close_fills(pg_session_factory, closing.id)) == fills_before == 0
    [still] = [a for a in await _attempts(pg_session_factory) if a.id == closing.id]
    assert still.status == "SUBMITTED"


# ---- the writer, and a refused opening -----------------------------------------------


async def test_writing_the_same_source_twice_writes_one_row_and_raises_nothing(
    pg_session_factory: Factory,
) -> None:
    exchange = _StopExchange(resting="STOP-1")
    strategy_id, allocation_id = await _opened_position(pg_session_factory, exchange)
    closing = await _close_as(
        pg_session_factory, exchange, strategy_id, allocation_id, ExecutionCause.MANUAL
    )
    event = NewSafetyEvent(
        user_id=OWNER_ID,
        kind=SafetyEventKind.MANUAL_CLOSE,
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        exchange="bybit",
        venue="usdt-m",
        symbol="STXUSDT",
        detail={"quantity": "1", "price": "2"},
        execution_attempt_id=closing.id,
    )

    async with pg_session_factory() as session:
        writer = SqlAlchemySafetyEventWriter(session, SystemClock())
        await writer.record(event)
        await writer.record(event)
        await session.commit()

    assert len(await _events(pg_session_factory)) == 1


async def test_a_refused_opening_is_an_event_of_its_delivery_with_no_allocation(
    pg_session_factory: Factory,
) -> None:
    strategy_id, _, closing_signal, _ = await _seed_position(
        pg_session_factory, closing_position_size="0"
    )
    delivery_id = await _delivery_of(pg_session_factory, closing_signal)
    event = NewSafetyEvent(
        user_id=OWNER_ID,
        kind=SafetyEventKind.OPENING_REFUSED_LEVERAGE_CAP,
        strategy_id=strategy_id,
        allocation_id=None,
        exchange="bybit",
        venue="usdt-m",
        symbol="STXUSDT",
        detail={"requested_leverage": "9", "max_leverage": "6", "stop_loss_pct": "15"},
        delivery_id=delivery_id,
    )

    async with pg_session_factory() as session:
        writer = SqlAlchemySafetyEventWriter(session, SystemClock())
        await writer.record(event)
        await writer.record(event)
        await session.commit()

    [row] = await _events(pg_session_factory)
    assert (row.kind, row.allocation_id, row.execution_attempt_id) == (
        "OPENING_REFUSED_LEVERAGE_CAP",
        None,
        None,
    )
    assert row.delivery_id == delivery_id
    assert row.detail == {"requested_leverage": "9", "max_leverage": "6", "stop_loss_pct": "15"}


async def test_an_event_that_is_rolled_back_leaves_no_row(pg_session_factory: Factory) -> None:
    strategy_id, _, closing_signal, _ = await _seed_position(
        pg_session_factory, closing_position_size="0"
    )
    delivery_id = await _delivery_of(pg_session_factory, closing_signal)

    async with pg_session_factory() as session:
        await SqlAlchemySafetyEventWriter(session, SystemClock()).record(
            NewSafetyEvent(
                user_id=OWNER_ID,
                kind=SafetyEventKind.OPENING_REFUSED_LEVERAGE_CAP,
                strategy_id=strategy_id,
                allocation_id=None,
                exchange="bybit",
                venue="usdt-m",
                symbol="STXUSDT",
                detail={},
                delivery_id=delivery_id,
            )
        )
        await session.rollback()

    async with pg_session_factory() as session:
        counted = await session.execute(select(func.count()).select_from(SafetyEventRow))
        count = counted.scalar_one()
    assert count == 0
