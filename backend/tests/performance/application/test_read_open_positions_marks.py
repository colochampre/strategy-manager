"""The mark price and the unrealized PnL of each open position (RD.3b), through
``ReadOpenPositions`` over fakes of its ports.

Symbols (rule R7): the guard's element spells a market ``STXUSDT / STXUSDT.P``,
the ledger's fills ``STXUSDT.P``, and the mark port is asked for the market key
``STXUSDT``.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.domain.mode_origin import OpenAllocationOrigin
from strategy_manager.performance.application.ports import PositionFacts, PositionMarkPort
from strategy_manager.performance.application.read_open_positions import ReadOpenPositions
from strategy_manager.performance.domain.open_position import OpenPosition, PoolLabel
from tests.owner import OWNER_ID
from tests.performance.fakes import (
    FakeDisagreementSource,
    FakeFactsSource,
    FakeMarkPrices,
    FakeOpenStateReader,
)
from tests.performance.open_state_cases import (
    fill_aggregate,
    open_element,
    position_facts,
)

LOGGER = "strategy_manager.performance"
STRATEGY = UUID("11111111-aaaa-bbbb-cccc-000000000001")


@dataclass(frozen=True)
class _Case:
    element: OpenAllocationOrigin
    allocation: UUID
    facts: dict[UUID, PositionFacts]


def _position(
    *,
    exchange: str = "bybit",
    market_symbol: str = "STXUSDT.P",
    side: str = "BUY",
    rehearsal: bool = False,
    extra_symbol: str | None = None,
) -> _Case:
    allocation = uuid4()
    pool = PoolLabel(exchange, "usdt-m", "USDT")
    reader_symbol = (
        f"{market_symbol.removesuffix('.P')} / {market_symbol}"
        if extra_symbol is None
        else f"{market_symbol} / {extra_symbol}"
    )
    element = open_element(
        rehearsal=rehearsal, live=not rehearsal, allocation_id=allocation,
        exchange=exchange, symbol=reader_symbol,
    )  # fmt: skip
    groups = (
        fill_aggregate(
            allocation, STRATEGY, side=side, quantity="100", price="0.45",
            symbol=market_symbol, pool=pool,
        ),
    )  # fmt: skip
    if extra_symbol is not None:
        groups += (
            fill_aggregate(
                allocation, STRATEGY, side=side, quantity="1", price="9",
                symbol=extra_symbol, pool=pool,
            ),
        )  # fmt: skip
    return _Case(
        element,
        allocation,
        {allocation: position_facts(allocation, STRATEGY, groups, reservation_pool=pool)},
    )


async def _read(cases: Sequence[_Case], marks: PositionMarkPort) -> dict[UUID, OpenPosition]:
    facts: dict[UUID, PositionFacts] = {}
    for case in cases:
        facts.update(case.facts)
    answer = await ReadOpenPositions(
        FakeOpenStateReader([case.element for case in cases]),
        FakeFactsSource(facts),
        FakeDisagreementSource(),
        marks,
    ).read(OWNER_ID)
    return {p.allocation_id: p for p in answer.positions}


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name.startswith(LOGGER)]


async def test_a_long_position_carries_the_mark_and_what_it_would_make_at_it() -> None:
    case = _position()
    marks = FakeMarkPrices({("bybit", "STXUSDT"): Decimal("0.47")})

    positions = await _read([case], marks)

    position = positions[case.allocation]
    assert (position.mark_price, position.unrealized_pnl) == (Decimal("0.47"), Decimal("2.00"))


async def test_a_short_position_gains_when_the_mark_falls() -> None:
    case = _position(side="SELL")
    marks = FakeMarkPrices({("bybit", "STXUSDT"): Decimal("0.44")})

    positions = await _read([case], marks)

    assert positions[case.allocation].unrealized_pnl == Decimal("1.00")


async def test_the_mark_is_asked_for_the_market_key_never_the_ledgers_spelling() -> None:
    marks = FakeMarkPrices({("bybit", "STXUSDT"): Decimal("0.47")})

    await _read([_position()], marks)

    assert marks.asked == [("bybit", "STXUSDT")]


async def test_a_rehearsal_position_gets_the_figures_too() -> None:
    case = _position(rehearsal=True)
    marks = FakeMarkPrices({("bybit", "STXUSDT"): Decimal("0.47")})

    positions = await _read([case], marks)

    assert positions[case.allocation].unrealized_pnl == Decimal("2.00")


async def test_two_positions_on_one_market_read_that_market_once() -> None:
    first, second = _position(), _position()
    marks = FakeMarkPrices({("bybit", "STXUSDT"): Decimal("0.47")})

    positions = await _read([first, second], marks)

    assert marks.asked == [("bybit", "STXUSDT")]
    assert [positions[first.allocation].mark_price, positions[second.allocation].mark_price] == [
        Decimal("0.47"),
        Decimal("0.47"),
    ]


async def test_the_same_market_on_two_exchanges_is_read_once_per_exchange() -> None:
    bybit, binance = _position(), _position(exchange="binance")
    marks = FakeMarkPrices(
        {("bybit", "STXUSDT"): Decimal("0.47"), ("binance", "STXUSDT"): Decimal("0.48")}
    )

    positions = await _read([bybit, binance], marks)

    assert sorted(marks.asked) == [("binance", "STXUSDT"), ("bybit", "STXUSDT")]
    assert positions[bybit.allocation].mark_price == Decimal("0.47")
    assert positions[binance.allocation].mark_price == Decimal("0.48")


async def test_an_exchange_with_no_public_source_has_no_mark_and_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    case = _position(exchange="pionex")
    caplog.set_level(logging.DEBUG)

    positions = await _read([case], FakeMarkPrices())

    position = positions[case.allocation]
    assert (position.mark_price, position.unrealized_pnl) == (None, None)
    assert [r for r in _records(caplog) if r.levelno >= logging.WARNING] == []


async def test_a_failed_read_leaves_that_market_null_and_names_it_in_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    case = _position()
    marks = FakeMarkPrices({("bybit", "STXUSDT"): RuntimeError("venue said no")})
    caplog.set_level(logging.DEBUG)

    positions = await _read([case], marks)

    position = positions[case.allocation]
    assert (position.mark_price, position.unrealized_pnl) == (None, None)
    warnings = [r for r in _records(caplog) if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "bybit" in message and "STXUSDT" in message
    assert not [r for r in _records(caplog) if r.levelno >= logging.ERROR]


async def test_a_timed_out_read_is_a_warning_and_a_null_too(
    caplog: pytest.LogCaptureFixture,
) -> None:
    case = _position()
    marks = FakeMarkPrices({("bybit", "STXUSDT"): TimeoutError()})
    caplog.set_level(logging.DEBUG)

    positions = await _read([case], marks)

    assert positions[case.allocation].mark_price is None
    assert len([r for r in _records(caplog) if r.levelno == logging.WARNING]) == 1


async def test_one_failing_market_never_blanks_the_others() -> None:
    good, bad = _position(), _position(exchange="binance")
    marks = FakeMarkPrices(
        {("bybit", "STXUSDT"): Decimal("0.47"), ("binance", "STXUSDT"): ValueError("boom")}
    )

    positions = await _read([good, bad], marks)

    assert positions[good.allocation].mark_price == Decimal("0.47")
    assert positions[bad.allocation].mark_price is None


async def test_a_position_with_no_figures_is_not_priced_and_its_market_is_not_read() -> None:
    allocation = uuid4()
    element = open_element(
        rehearsal=False, live=True, allocation_id=allocation, symbol="STXUSDT / STXUSDT.P"
    )
    marks = FakeMarkPrices({("bybit", "STXUSDT"): Decimal("0.47")})

    answer = await ReadOpenPositions(
        FakeOpenStateReader([element]), FakeFactsSource(), FakeDisagreementSource(), marks
    ).read(OWNER_ID)

    [position] = answer.positions
    assert (position.mark_price, position.unrealized_pnl) == (None, None)
    assert marks.asked == []


async def test_a_position_on_several_markets_has_no_mark() -> None:
    case = _position(extra_symbol="ETHUSDT.P")
    marks = FakeMarkPrices(
        {("bybit", "STXUSDT"): Decimal("0.47"), ("bybit", "ETHUSDT"): Decimal("3000")}
    )

    positions = await _read([case], marks)

    position = positions[case.allocation]
    assert (position.mark_price, position.unrealized_pnl) == (None, None)
    assert marks.asked == []


async def test_the_reads_run_concurrently() -> None:
    gate = asyncio.Event()
    started: list[str] = []

    class _Waiting:
        async def mark_price(self, exchange: str, market: str) -> Decimal | None:
            started.append(exchange)
            if len(started) == 2:
                gate.set()
            await asyncio.wait_for(gate.wait(), timeout=1)
            return Decimal("0.47")

    bybit, binance = _position(), _position(exchange="binance")

    positions = await _read([bybit, binance], _Waiting())

    assert [p.mark_price for p in positions.values()] == [Decimal("0.47"), Decimal("0.47")]


async def test_a_read_without_a_mark_port_serves_the_positions_as_before() -> None:
    case = _position()

    answer = await ReadOpenPositions(
        FakeOpenStateReader([case.element]),
        FakeFactsSource(case.facts),
        FakeDisagreementSource(),
    ).read(OWNER_ID)

    [position] = answer.positions
    assert (position.mark_price, position.unrealized_pnl) == (None, None)
