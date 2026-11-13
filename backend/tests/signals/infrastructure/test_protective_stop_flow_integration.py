"""Subscriber-safety SS.5 on real PostgreSQL: an opening that carries a stop writes its
row with the attempt, settle enqueues the confirm job on the commit that records the fills,
and the confirm job either records the stop that rests or closes the position at once.

The production ``PlaceOrder``, ``SettleExecution``, ``ConfirmProtectiveStop`` and
``ClosePosition`` run on real sessions with the production repositories; only the venue is
replaced, by a simulated exchange that puts a stop on its opening and answers the lookup
for it. What the unit tests cannot show is shown here: the ``FAILED`` mark and the closing
attempt land on ONE commit, and a close that cannot be built rolls the mark back.
"""

import logging
from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.allocation.infrastructure.reservation_gateway import (
    ReservationGatewayAdapter,
)
from strategy_manager.execution.application.confirm_protective_stop import (
    ConfirmProtectiveStop,
)
from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    ExchangeError,
    OpenOrderSpec,
    RestingStop,
)
from strategy_manager.execution.domain.futures_order import FuturesMarketOrder
from strategy_manager.execution.domain.placeable import PlaceableOrder
from strategy_manager.execution.domain.protective_stop import PositionSide, StopStatus
from strategy_manager.execution.infrastructure.exchange_registry import VenueExchangeRegistry
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.models import (
    ExecutionAttemptRow,
    ProtectiveStopRow,
)
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
    SqlAlchemyProtectiveStopRepository,
)
from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.infrastructure.models import JobRow
from tests.allocation.fakes import RecordedModes
from tests.execution.fakes import OneRegistry
from tests.owner import OWNER_ID
from tests.signals.infrastructure.test_settle_outcomes_integration import (
    _attempts,
    _close_position,
    _FaultyCommit,
    _place_open,
    _seed_open,
    _settle,
)

pytestmark = pytest.mark.integration

_STOP_PRICE = Decimal("1.8")


class _StopExchange(FakeExchangeAdapter):
    """A simulated exchange that behaves like a venue taking the stop on the opening:
    the order it builds carries a stop price, and the lookup answers ``resting`` (or
    nothing). ``close_raises`` is an unknown failure reading the venue's rules, which a
    close's build can meet."""

    def __init__(
        self, *, resting: str | None, close_raises: Exception | None = None
    ) -> None:
        super().__init__(exchange="bybit", fee_rate=Decimal("0"), fill_price=Decimal("2"))
        self._resting = resting
        self._close_raises = close_raises

    async def build_open_order(self, spec: OpenOrderSpec) -> PlaceableOrder:
        order = await super().build_open_order(spec)
        assert isinstance(order, FuturesMarketOrder)
        return replace(order, stop_price=_STOP_PRICE)

    async def build_close_order(self, spec: CloseOrderSpec) -> PlaceableOrder:
        if self._close_raises is not None:
            raise self._close_raises
        return await super().build_close_order(spec)

    async def find_resting_stop(self, client_order_id: str, symbol: str) -> RestingStop | None:
        return None if self._resting is None else RestingStop(venue_stop_id=self._resting)


class _AfterFillExchange(FakeExchangeAdapter):
    """A live venue with no stop on the opening order (Binance, SS.6): the stop is placed
    after the fill, under the id the row recorded. ``place_raises`` is what the request
    meets, and ``found`` what the read-back by the id answers."""

    is_live = True
    places_stop_after_fill = True

    def __init__(
        self,
        *,
        place_raises: Exception | None = None,
        found: str | None = None,
        close_raises: Exception | None = None,
    ) -> None:
        super().__init__(exchange="bybit", fee_rate=Decimal("0"), fill_price=Decimal("2"))
        self.placed: list[tuple[str, PositionSide, Decimal, str]] = []
        self.finds: list[str] = []
        self._place_raises = place_raises
        self._found = found
        self._close_raises = close_raises

    async def build_close_order(self, spec: CloseOrderSpec) -> PlaceableOrder:
        if self._close_raises is not None:
            raise self._close_raises
        return await super().build_close_order(spec)

    async def stop_trigger_price(
        self, symbol: str, position_side: PositionSide, entry: Decimal, stop_loss_pct: Decimal
    ) -> Decimal:
        return (entry * (1 - stop_loss_pct / 100)).quantize(Decimal("0.1"))

    async def place_stop(
        self, symbol: str, position_side: PositionSide, trigger_price: Decimal, client_stop_id: str
    ) -> str:
        self.placed.append((symbol, position_side, trigger_price, client_stop_id))
        if self._place_raises is not None:
            raise self._place_raises
        return "ALGO-1"

    async def find_stop(self, symbol: str, client_stop_id: str) -> RestingStop | None:
        self.finds.append(client_stop_id)
        return None if self._found is None else RestingStop(venue_stop_id=self._found)


def _confirm(session: AsyncSession, exchange: FakeExchangeAdapter) -> ConfirmProtectiveStop:
    return ConfirmProtectiveStop(
        stops=SqlAlchemyProtectiveStopRepository(session),
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        reservations=ReservationGatewayAdapter(SqlAlchemyReservationRepository(session)),
        exchanges=OneRegistry(VenueExchangeRegistry([exchange])),
        allocation_modes=RecordedModes(),
        closer=_close_position(session, exchange),
        commit=session,
    )


async def _stops(factory: async_sessionmaker[AsyncSession]) -> list[ProtectiveStopRow]:
    async with factory() as session:
        return list((await session.execute(select(ProtectiveStopRow))).scalars())


async def _jobs(factory: async_sessionmaker[AsyncSession], kind: JobKind) -> list[JobRow]:
    async with factory() as session:
        return list(
            (await session.execute(select(JobRow).where(JobRow.kind == kind.value))).scalars()
        )


async def _opened_and_settled(
    factory: async_sessionmaker[AsyncSession], exchange: FakeExchangeAdapter
) -> tuple[UUID, UUID]:
    """An opening placed and settled: ``(reservation_id, attempt_id)``."""
    _, _, reservation_id = await _seed_open(factory)
    await _place_open(factory, exchange, reservation_id)
    [attempt] = await _attempts(factory)
    async with factory() as session:
        await _settle(session, _FaultyCommit(session, fail_on=None), exchange).settle(
            OWNER_ID, attempt.id
        )
    return reservation_id, attempt.id


async def test_an_opening_with_a_stop_writes_its_pending_row_with_the_attempt(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    exchange = _StopExchange(resting="STOP-1")
    _, _, reservation_id = await _seed_open(pg_session_factory)

    await _place_open(pg_session_factory, exchange, reservation_id)

    [attempt] = await _attempts(pg_session_factory)
    [stop] = await _stops(pg_session_factory)
    assert stop.execution_attempt_id == attempt.id
    assert stop.allocation_id == reservation_id
    assert stop.user_id == OWNER_ID
    assert (stop.exchange, stop.venue, stop.symbol) == ("bybit", "usdt-m", "STXUSDT.P")
    assert stop.position_side == PositionSide.LONG.value
    assert stop.stop_loss_pct == Decimal("10")
    assert stop.trigger_price == _STOP_PRICE
    assert (stop.status, stop.venue_stop_id) == (StopStatus.PENDING.value, None)


async def test_settle_enqueues_the_confirm_job_on_the_commit_that_records_the_fills(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    exchange = _StopExchange(resting="STOP-1")
    _, _, reservation_id = await _seed_open(pg_session_factory)
    await _place_open(pg_session_factory, exchange, reservation_id)
    [attempt] = await _attempts(pg_session_factory)

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=1)
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await _settle(session, commit, exchange).settle(OWNER_ID, attempt.id)

    # The failed commit took the job with the fills: neither landed.
    assert await _jobs(pg_session_factory, JobKind.PROTECTIVE_STOP_CONFIRM) == []

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=None)
        await _settle(session, commit, exchange).settle(OWNER_ID, attempt.id)

    [job] = await _jobs(pg_session_factory, JobKind.PROTECTIVE_STOP_CONFIRM)
    assert job.payload == {"execution_attempt_id": str(attempt.id)}
    assert commit.calls == 1


async def test_the_confirm_job_records_the_stop_that_rests(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    exchange = _StopExchange(resting="STOP-1")
    _, attempt_id = await _opened_and_settled(pg_session_factory, exchange)

    async with pg_session_factory() as session:
        result = await _confirm(session, exchange).confirm(OWNER_ID, attempt_id)

    assert result.status == "RESTING"
    [stop] = await _stops(pg_session_factory)
    assert (stop.status, stop.venue_stop_id) == (StopStatus.RESTING.value, "STOP-1")
    assert len(await _attempts(pg_session_factory)) == 1  # no close was placed


async def test_a_missing_stop_closes_the_position_on_the_same_commit_that_fails_it(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    exchange = _StopExchange(resting=None)
    reservation_id, attempt_id = await _opened_and_settled(pg_session_factory, exchange)

    with caplog.at_level(logging.INFO):
        async with pg_session_factory() as session:
            result = await _confirm(session, exchange).confirm(OWNER_ID, attempt_id)

    assert result.status == "CLOSING"
    [stop] = await _stops(pg_session_factory)
    assert stop.status == StopStatus.FAILED.value
    [opening, closing] = sorted(
        await _attempts(pg_session_factory), key=lambda row: row.closes_allocation_id is not None
    )
    assert opening.id == attempt_id
    assert closing.closes_allocation_id == reservation_id
    assert (closing.side, closing.status, closing.signal_id, closing.delivery_id) == (
        "SELL",
        "SUBMITTED",
        None,
        None,
    )
    assert closing.user_id == OWNER_ID
    assert len(await _jobs(pg_session_factory, JobKind.EXECUTION_SETTLE)) == 2
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert str(OWNER_ID) in errors[0] and "STXUSDT.P" in errors[0] and str(attempt_id) in errors[0]


async def test_a_close_that_cannot_be_built_rolls_the_failed_mark_back_so_the_retry_looks_again(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    exchange = _StopExchange(resting=None, close_raises=TimeoutError("venue rules unreadable"))
    _, attempt_id = await _opened_and_settled(pg_session_factory, exchange)

    async with pg_session_factory() as session:
        with pytest.raises(TimeoutError):
            await _confirm(session, exchange).confirm(OWNER_ID, attempt_id)

    [stop] = await _stops(pg_session_factory)
    assert stop.status == StopStatus.PENDING.value
    assert len(await _attempts(pg_session_factory)) == 1

    # The retry finds the stop PENDING and asks the venue again; this time the close builds.
    healthy = _StopExchange(resting=None)
    async with pg_session_factory() as session:
        result = await _confirm(session, healthy).confirm(OWNER_ID, attempt_id)
    assert result.status == "CLOSING"
    [stop] = await _stops(pg_session_factory)
    assert stop.status == StopStatus.FAILED.value


# ---- a stop placed after the fill (SS.6, Binance) ----


async def test_an_opening_on_a_venue_that_places_its_stop_later_records_the_id_first(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    exchange = _AfterFillExchange()
    _, _, reservation_id = await _seed_open(pg_session_factory)

    await _place_open(pg_session_factory, exchange, reservation_id)

    [attempt] = await _attempts(pg_session_factory)
    [stop] = await _stops(pg_session_factory)
    assert stop.execution_attempt_id == attempt.id
    assert (stop.status, stop.venue_stop_id) == (StopStatus.PENDING.value, None)
    assert stop.trigger_price is None
    assert stop.client_stop_id is not None and len(stop.client_stop_id) == 36


async def test_the_confirm_job_prices_places_and_records_the_stop(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    exchange = _AfterFillExchange()
    _, attempt_id = await _opened_and_settled(pg_session_factory, exchange)

    async with pg_session_factory() as session:
        result = await _confirm(session, exchange).confirm(OWNER_ID, attempt_id)

    assert result.status == "RESTING"
    [stop] = await _stops(pg_session_factory)
    assert (stop.status, stop.venue_stop_id) == (StopStatus.RESTING.value, "ALGO-1")
    # The fake fills at 2, so 10% below is 1.8, committed on the row.
    assert stop.trigger_price == Decimal("1.8")
    assert exchange.placed == [
        ("STXUSDT.P", PositionSide.LONG, Decimal("1.8"), stop.client_stop_id)
    ]
    assert len(await _attempts(pg_session_factory)) == 1  # no close was placed


async def test_a_request_with_an_unknown_outcome_keeps_the_trigger_and_the_retry_reads_it_back(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The trigger was committed before the request, so the timeout's rollback does not take
    it, and the retry finds the stop by its id instead of placing a second one."""
    timing_out = _AfterFillExchange(place_raises=TimeoutError("venue timed out"))
    _, attempt_id = await _opened_and_settled(pg_session_factory, timing_out)
    async with pg_session_factory() as session:
        with pytest.raises(TimeoutError):
            await _confirm(session, timing_out).confirm(OWNER_ID, attempt_id)
    [stop] = await _stops(pg_session_factory)
    assert (stop.status, stop.trigger_price) == (StopStatus.PENDING.value, Decimal("1.8"))
    assert len(await _attempts(pg_session_factory)) == 1

    retry = _AfterFillExchange(found="ALGO-1")
    async with pg_session_factory() as session:
        result = await _confirm(session, retry).confirm(OWNER_ID, attempt_id)

    assert result.status == "RESTING"
    assert retry.finds == [stop.client_stop_id] and retry.placed == []
    [stop] = await _stops(pg_session_factory)
    assert (stop.status, stop.venue_stop_id) == (StopStatus.RESTING.value, "ALGO-1")


async def test_a_refused_stop_closes_the_position_on_the_same_commit_that_fails_it(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    exchange = _AfterFillExchange(place_raises=ExchangeError("Binance refused the stop"))
    reservation_id, attempt_id = await _opened_and_settled(pg_session_factory, exchange)

    with caplog.at_level(logging.INFO):
        async with pg_session_factory() as session:
            result = await _confirm(session, exchange).confirm(OWNER_ID, attempt_id)

    assert result.status == "CLOSING"
    [stop] = await _stops(pg_session_factory)
    assert stop.status == StopStatus.FAILED.value
    assert stop.trigger_price == Decimal("1.8")
    [_, closing] = sorted(
        await _attempts(pg_session_factory), key=lambda row: row.closes_allocation_id is not None
    )
    assert (closing.closes_allocation_id, closing.side) == (reservation_id, "SELL")
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1 and "Binance refused the stop" in errors[0]


async def test_a_confirm_job_run_twice_closes_once(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The second run finds the stop FAILED, not PENDING, and sends nothing."""
    exchange = _StopExchange(resting=None)
    _, attempt_id = await _opened_and_settled(pg_session_factory, exchange)
    async with pg_session_factory() as session:
        await _confirm(session, exchange).confirm(OWNER_ID, attempt_id)

    async with pg_session_factory() as session:
        again = await _confirm(session, exchange).confirm(OWNER_ID, attempt_id)

    assert again.status == "SKIPPED"
    closes: list[ExecutionAttemptRow] = [
        row for row in await _attempts(pg_session_factory) if row.closes_allocation_id
    ]
    assert len(closes) == 1
