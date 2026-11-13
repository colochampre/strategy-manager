"""``ConfirmProtectiveStop`` for a venue that places its stop AFTER the fill
(subscriber-safety SS.6, Binance).

The opening order carries no stop, so the job does what the order could not: it reads the
opening's fills, takes their volume-weighted average as the entry, works out the trigger,
RECORDS it, sends the stop, and records the id the venue gave it. The recorded trigger is
what makes a retry safe: with one on the row, an earlier request may have reached the venue,
so the job reads the stop back by its ``client_stop_id`` before it sends anything again.

The outcomes that must never happen: a position left open with no stop, a protected position
closed because the venue timed out, and a second stop placed over a first.
"""

import logging
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.application.close_position import (
    CloseCommand,
    NothingRecordedYet,
)
from strategy_manager.execution.application.confirm_protective_stop import (
    ConfirmProtectiveStop,
    FillsNotPublishedYet,
)
from strategy_manager.execution.application.ports import ExchangeError, RestingStop
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.futures_order import protective_stop_price
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.domain.protective_stop import (
    PositionSide,
    ProtectiveStop,
    StopStatus,
)
from strategy_manager.execution.infrastructure.exchange_registry import (
    VenueExchangeRegistry,
)
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.mode import Mode
from tests.allocation.fakes import RecordedModes
from tests.execution.application.test_confirm_protective_stop import (
    ALLOCATION_ID,
    ATTEMPT_ID,
    CLIENT_ORDER_ID,
    OWNER,
    STRATEGY_ID,
    SYMBOL,
    FakeAttempts,
    FakeReservations,
    SpyCloser,
    SpyCommit,
    _attempt,
    _messages,
)
from tests.execution.fakes import OneRegistry

CLIENT_STOP_ID = "9b2f4c1e-6d3a-4f7b-8a15-2c9e0d4b7a61"
ALGO_ID = "3000000123456"
TICK = Decimal("0.000010")


def _fill(quantity: str, price: str, fill_id: str) -> Fill:
    return Fill(
        exchange_order_id="778899",
        exchange_fill_id=fill_id,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal("0.01"),
        fee_currency="USDT",
        filled_at=datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC),
    )


# Two pieces of one opening, averaging exactly 0.066340: the spec's example.
FILLS = [_fill("38", "0.066330", "1"), _fill("38", "0.066350", "2")]


class StatefulStops:
    """One stop row that moves as the use case moves it, with every write in the shared
    ``log`` so a test can prove what happened before what."""

    def __init__(
        self,
        log: list[str],
        *,
        status: StopStatus = StopStatus.PENDING,
        trigger: Decimal | None = None,
        side: PositionSide = PositionSide.LONG,
        client_stop_id: str | None = CLIENT_STOP_ID,
    ) -> None:
        self.log = log
        self.stop = ProtectiveStop(
            id=uuid4(),
            execution_attempt_id=ATTEMPT_ID,
            allocation_id=ALLOCATION_ID,
            exchange="binance",
            venue="usdt-m",
            symbol=SYMBOL,
            position_side=side,
            stop_loss_pct=Decimal("10"),
            trigger_price=trigger,
            status=status,
            client_stop_id=client_stop_id,
        )
        self.marked: list[tuple[UUID, UUID, StopStatus, str | None]] = []
        self.recorded: list[tuple[UUID, UUID, Decimal]] = []

    async def insert(self, user_id: UUID, stop: ProtectiveStop) -> None:  # pragma: no cover
        raise NotImplementedError

    async def for_attempt(self, user_id: UUID, attempt_id: UUID) -> ProtectiveStop | None:
        return self.stop

    async def mark(
        self,
        user_id: UUID,
        attempt_id: UUID,
        status: StopStatus,
        venue_stop_id: str | None = None,
    ) -> None:
        self.marked.append((user_id, attempt_id, status, venue_stop_id))
        self.log.append(f"stop.mark {status.value}")
        self.stop = replace(
            self.stop, status=status, venue_stop_id=venue_stop_id or self.stop.venue_stop_id
        )

    async def record_trigger_price(
        self, user_id: UUID, attempt_id: UUID, trigger_price: Decimal
    ) -> None:
        self.recorded.append((user_id, attempt_id, trigger_price))
        self.log.append("stop.record_trigger_price")
        self.stop = replace(self.stop, trigger_price=trigger_price)


class AfterFillExchange:
    """An adapter that places its stop after the fill. The trigger is the real rule at the
    spec's tick, so the example's "0.059700" is asserted end to end."""

    is_live = True
    exchange = "binance"
    venues = frozenset({"usdt-m"})
    places_stop_after_fill = True

    def __init__(
        self,
        log: list[str],
        *,
        fills: list[Fill] | None = None,
        found: list[RestingStop | None | Exception] | None = None,
        place_raises: Exception | None = None,
        trigger_raises: Exception | None = None,
    ) -> None:
        self.log = log
        self.fills = FILLS if fills is None else fills
        self.found = list(found or [])
        self.place_raises = place_raises
        self.trigger_raises = trigger_raises
        self.fill_reads: list[tuple[str, str]] = []
        self.trigger_asks: list[tuple[str, PositionSide, Decimal, Decimal]] = []
        self.placed: list[tuple[str, PositionSide, Decimal, str]] = []
        self.finds: list[tuple[str, str]] = []

    async def fetch_fills(self, client_order_id: str, symbol: str) -> list[Fill]:
        self.log.append("exchange.fetch_fills")
        self.fill_reads.append((client_order_id, symbol))
        return self.fills

    async def stop_trigger_price(
        self, symbol: str, position_side: PositionSide, entry: Decimal, stop_loss_pct: Decimal
    ) -> Decimal:
        self.trigger_asks.append((symbol, position_side, entry, stop_loss_pct))
        if self.trigger_raises is not None:
            raise self.trigger_raises
        return protective_stop_price(
            side=OrderSide.BUY if position_side is PositionSide.LONG else OrderSide.SELL,
            entry=entry,
            stop_loss_pct=stop_loss_pct,
            tick=TICK,
        )

    async def place_stop(
        self, symbol: str, position_side: PositionSide, trigger_price: Decimal, client_stop_id: str
    ) -> str:
        self.log.append("exchange.place_stop")
        self.placed.append((symbol, position_side, trigger_price, client_stop_id))
        if self.place_raises is not None:
            raise self.place_raises
        return ALGO_ID

    async def find_stop(self, symbol: str, client_stop_id: str) -> RestingStop | None:
        self.log.append("exchange.find_stop")
        self.finds.append((symbol, client_stop_id))
        answer = self.found.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def find_resting_stop(  # pragma: no cover - the parent-order lookup is Bybit's
        self, client_order_id: str, symbol: str
    ) -> RestingStop | None:
        raise ExchangeError("a Binance opening carries no stop")

    async def place(self, order: object) -> object:  # pragma: no cover
        raise NotImplementedError

    async def build_open_order(self, spec: object) -> object:  # pragma: no cover
        raise NotImplementedError

    async def build_close_order(self, spec: object) -> object:  # pragma: no cover
        raise NotImplementedError


class Rig:
    def __init__(
        self,
        *,
        status: StopStatus = StopStatus.PENDING,
        trigger: Decimal | None = None,
        side: OrderSide = OrderSide.BUY,
        fills: list[Fill] | None = None,
        found: list[RestingStop | None | Exception] | None = None,
        place_raises: Exception | None = None,
        trigger_raises: Exception | None = None,
        close_raises: Exception | None = None,
    ) -> None:
        self.log: list[str] = []
        self.stops = StatefulStops(
            self.log,
            status=status,
            trigger=trigger,
            side=PositionSide.LONG if side is OrderSide.BUY else PositionSide.SHORT,
        )
        attempt: ExecutionAttempt = replace(_attempt(side), exchange="binance")
        self.attempts = FakeAttempts(attempt)
        self.reservations = FakeReservations()
        self.exchange = AfterFillExchange(
            self.log,
            fills=fills,
            found=found,
            place_raises=place_raises,
            trigger_raises=trigger_raises,
        )
        self.closer = SpyCloser(self.log, close_raises)
        self.use_case = ConfirmProtectiveStop(
            stops=self.stops,
            attempts=self.attempts,  # type: ignore[arg-type]
            reservations=self.reservations,
            exchanges=OneRegistry(
                VenueExchangeRegistry([self.exchange]),  # type: ignore[list-item]
                [],
            ),
            allocation_modes=RecordedModes(Mode.LIVE),
            closer=self.closer,
            commit=SpyCommit(self.log),
        )


# ---- the first pass: fills, trigger, recorded, sent ----


async def test_the_stop_follows_the_fill(caplog: pytest.LogCaptureFixture) -> None:
    """The spec's scenario: an average fill of 0.066340 on DOGEUSDT, a 0.000010 tick and a
    strategy at 10 send a SELL stop at "0.059700" (0.059706 rounded down to the tick), under
    the id that was stored before the request."""
    rig = Rig()

    with caplog.at_level(logging.INFO):
        result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "RESTING"
    assert rig.exchange.fill_reads == [(CLIENT_ORDER_ID, SYMBOL)]
    assert rig.exchange.trigger_asks == [
        (SYMBOL, PositionSide.LONG, Decimal("0.066340"), Decimal("10"))
    ]
    assert rig.stops.recorded == [(OWNER, ATTEMPT_ID, Decimal("0.059700"))]
    assert str(rig.stops.recorded[0][2]) == "0.059700"
    assert rig.exchange.placed == [(SYMBOL, PositionSide.LONG, Decimal("0.059700"), CLIENT_STOP_ID)]
    assert rig.stops.marked == [(OWNER, ATTEMPT_ID, StopStatus.RESTING, ALGO_ID)]
    assert rig.closer.commands == []
    [info] = _messages(caplog, logging.INFO)
    assert ALGO_ID in info and SYMBOL in info and str(ATTEMPT_ID) in info


async def test_the_trigger_is_committed_before_the_request_and_the_algo_id_after_it() -> None:
    """With the trigger committed, a crash between the request and its answer leaves a
    retry that knows an earlier request may have reached the venue."""
    rig = Rig()

    await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert rig.log == [
        "exchange.fetch_fills",
        "stop.record_trigger_price",
        "commit",
        "exchange.place_stop",
        "stop.mark RESTING",
        "commit",
    ]


async def test_a_short_is_stopped_above_its_entry() -> None:
    rig = Rig(side=OrderSide.SELL)

    await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    # 0.066340 * 1.10 = 0.072974, rounded up to the tick.
    assert rig.exchange.placed == [
        (SYMBOL, PositionSide.SHORT, Decimal("0.072980"), CLIENT_STOP_ID)
    ]


async def test_the_entry_is_the_volume_weighted_average_of_every_fill() -> None:
    rig = Rig(fills=[_fill("75", "100", "1"), _fill("25", "104", "2")])

    await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert [ask[2] for ask in rig.exchange.trigger_asks] == [Decimal("101")]


async def test_fills_not_yet_published_retry_the_job_and_change_nothing() -> None:
    rig = Rig(fills=[])

    with pytest.raises(FillsNotPublishedYet):
        await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert rig.log == ["exchange.fetch_fills"]
    assert rig.exchange.placed == [] and rig.closer.commands == []


async def test_a_stop_that_cannot_be_priced_closes_the_position() -> None:
    """No position may stay open without its stop: a level the tick rounds to nothing is a
    stop that cannot rest."""
    rig = Rig(trigger_raises=InvariantViolation("the stop price must be positive"))

    result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "CLOSING"
    assert rig.exchange.placed == []
    assert rig.stops.marked == [(OWNER, ATTEMPT_ID, StopStatus.FAILED, None)]
    assert rig.stops.recorded == []
    assert len(rig.closer.commands) == 1


# ---- a refusal and an unknown outcome ----


async def test_a_definitive_refusal_fails_the_stop_and_closes_the_position_at_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The spec's scenario "Binance refuses the stop"."""
    rig = Rig(place_raises=ExchangeError("Binance refused the stop (code=-2021)"))

    with caplog.at_level(logging.INFO):
        result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "CLOSING"
    assert result.close is not None and result.close.status == "PLACED"
    [command] = rig.closer.commands
    assert command == CloseCommand(
        user_id=OWNER,
        allocation_id=ALLOCATION_ID,
        strategy_id=STRATEGY_ID,
        exchange="binance",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=SYMBOL,
        side=OrderSide.SELL,
        signal_id=None,
        delivery_id=None,
        reference_price=None,
    )
    assert rig.stops.marked == [(OWNER, ATTEMPT_ID, StopStatus.FAILED, None)]
    # The trigger was committed; the FAILED mark rides the close's own commit.
    assert rig.log[-2:] == ["stop.mark FAILED", "close"]
    [error] = _messages(caplog, logging.ERROR)
    assert str(OWNER) in error and SYMBOL in error and str(ATTEMPT_ID) in error
    assert "-2021" in error


async def test_a_short_whose_stop_is_refused_is_closed_by_buying_back() -> None:
    rig = Rig(side=OrderSide.SELL, place_raises=ExchangeError("refused"))

    await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    [command] = rig.closer.commands
    assert command.side is OrderSide.BUY


async def test_a_flat_ledger_after_a_refusal_marks_the_stop_gone() -> None:
    rig = Rig(
        place_raises=ExchangeError("refused"),
        close_raises=NothingRecordedYet("the ledger holds no DOGE"),
    )

    result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "GONE"
    assert [m[2] for m in rig.stops.marked] == [StopStatus.FAILED, StopStatus.GONE]
    assert rig.log[-1] == "commit"


async def test_an_unknown_outcome_placing_the_stop_retries_and_closes_nothing() -> None:
    """A timeout is not a refusal: the stop may well be resting, and closing a protected
    position over it is the failure this prevents."""
    rig = Rig(place_raises=TimeoutError("venue timed out"))

    with pytest.raises(TimeoutError):
        await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert rig.stops.marked == []
    assert rig.closer.commands == []
    # The trigger was committed before the request, so the retry reads the stop back.
    assert rig.log == [
        "exchange.fetch_fills",
        "stop.record_trigger_price",
        "commit",
        "exchange.place_stop",
    ]
    assert rig.stops.stop.trigger_price == Decimal("0.059700")


# ---- a retry: the trigger is already recorded, so a request may have reached the venue ----


async def test_a_recorded_trigger_reads_the_stop_back_by_its_id_before_anything_is_sent() -> None:
    rig = Rig(trigger=Decimal("0.059700"), found=[RestingStop(venue_stop_id=ALGO_ID)])

    result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "RESTING"
    assert rig.exchange.finds == [(SYMBOL, CLIENT_STOP_ID)]
    assert rig.exchange.placed == []
    assert rig.exchange.fill_reads == [] and rig.exchange.trigger_asks == []
    assert rig.stops.marked == [(OWNER, ATTEMPT_ID, StopStatus.RESTING, ALGO_ID)]
    assert rig.log == ["exchange.find_stop", "stop.mark RESTING", "commit"]


async def test_a_stop_the_venue_does_not_hold_is_sent_again_with_the_same_id_and_trigger() -> None:
    """Absent after the adapter's retries: the earlier request never arrived. It is sent
    once more under the SAME id, so a request that was merely slow cannot become a second
    stop, and at the SAME recorded trigger, never one worked out afresh."""
    rig = Rig(trigger=Decimal("0.059700"), found=[None])

    result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "RESTING"
    assert rig.exchange.placed == [(SYMBOL, PositionSide.LONG, Decimal("0.059700"), CLIENT_STOP_ID)]
    assert rig.exchange.fill_reads == [] and rig.exchange.trigger_asks == []
    assert rig.stops.recorded == []
    assert rig.log == [
        "exchange.find_stop",
        "exchange.place_stop",
        "stop.mark RESTING",
        "commit",
    ]


async def test_an_unknown_outcome_reading_the_stop_back_retries_and_sends_nothing() -> None:
    rig = Rig(trigger=Decimal("0.059700"), found=[TimeoutError("venue timed out")])

    with pytest.raises(TimeoutError):
        await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert rig.exchange.placed == []
    assert rig.stops.marked == []
    assert rig.closer.commands == []


async def test_a_definitive_refusal_reading_the_stop_back_closes_the_position() -> None:
    rig = Rig(trigger=Decimal("0.059700"), found=[ExchangeError("no permission to read")])

    result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "CLOSING"
    assert rig.exchange.placed == []
    assert rig.stops.marked == [(OWNER, ATTEMPT_ID, StopStatus.FAILED, None)]


async def test_a_retry_whose_second_request_is_refused_closes_the_position() -> None:
    rig = Rig(
        trigger=Decimal("0.059700"), found=[None], place_raises=ExchangeError("refused")
    )

    result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "CLOSING"
    assert rig.stops.marked == [(OWNER, ATTEMPT_ID, StopStatus.FAILED, None)]


# ---- what is not this job's to do ----


@pytest.mark.parametrize(
    "status",
    [
        StopStatus.RESTING,
        StopStatus.FAILED,
        StopStatus.GONE,
        StopStatus.VOID,
        StopStatus.SIMULATED,
    ],
)
async def test_a_stop_already_decided_is_neither_read_nor_sent(status: StopStatus) -> None:
    rig = Rig(status=status, trigger=Decimal("0.059700"))

    result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "SKIPPED"
    assert rig.log == []
    assert rig.exchange.placed == []


async def test_the_users_own_rows_are_the_only_ones_read_and_written() -> None:
    rig = Rig()

    await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert rig.attempts.users == [OWNER]
    assert [row[0] for row in rig.stops.recorded] == [OWNER]
    assert [row[0] for row in rig.stops.marked] == [OWNER]
