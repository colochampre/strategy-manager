"""T12, every WARNING of design section K, and the row it must not cost (design
addendum "open positions", sections C and K rows 4, 9, 10, 11, 12, 16 and 17).

With fakes and the log captured, one case each. Asserted for each: the row IS in
the answer with its own pool (never the reservation's); exactly one WARNING is
written; it is a WARNING and never an ERROR; it carries the allocation or attempt
id; and it carries no price, quantity, fee or margin. A case with nothing wrong
logs nothing, and a standing fault logs once per read.

Symbols (rule R7): the ledger's fills are ``STXUSDT.P``, the discrepancy row is
``STXUSDT``, an attempt is ``STXUSDT.P``.
"""

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    OpenAllocationOrigin,
)
from strategy_manager.performance.application.ports import PositionFacts, SubmittedOrder
from strategy_manager.performance.application.read_open_positions import ReadOpenPositions
from strategy_manager.performance.domain.open_position import (
    DiscrepancyRow,
    FiguresMissing,
    FillAggregate,
    OpenState,
    PoolLabel,
)
from tests.performance.fakes import FakeDisagreementSource, FakeFactsSource, FakeOpenStateReader
from tests.performance.open_state_cases import (
    POOL,
    fill_aggregate,
    in_flight_element,
    open_element,
    position_facts,
    submitted_order,
)

LOGGER = "strategy_manager.performance"
STRATEGY = UUID("11111111-aaaa-bbbb-cccc-000000000001")
OTHER_STRATEGY = UUID("22222222-aaaa-bbbb-cccc-000000000002")
BINANCE = PoolLabel("binance", "usdt-m", "USDT")

# Distinctive amounts, so a log line that leaks one is found by its text.
MARGIN, PRICE, QUANTITY, FEE = "1234.5", "987.6", "3.21", "0.0777"
FORBIDDEN = (MARGIN, PRICE, QUANTITY, FEE, "3170.196")


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name.startswith(LOGGER)]


async def _read(
    opened: Sequence[OpenAllocationOrigin] = (),
    in_flight: Sequence[InFlightAttemptOrigin] = (),
    *,
    facts: Mapping[UUID, PositionFacts] | None = None,
    submitted: Sequence[SubmittedOrder] = (),
    rows: Sequence[DiscrepancyRow] = (),
) -> OpenState:
    return await ReadOpenPositions(
        FakeOpenStateReader(opened, in_flight),
        FakeFactsSource(facts, submitted),
        FakeDisagreementSource(rows),
    ).read()


def _good(
    allocation: UUID | None = None,
    *,
    symbol: str = "STXUSDT.P",
    element_pool: PoolLabel = POOL,
    status: str = "FILLED",
    reservation_pool: PoolLabel = POOL,
    groups_override: tuple[FillAggregate, ...] | None = None,
    side: str = "BUY",
    reader_symbol: str | None = None,
) -> tuple[OpenAllocationOrigin, dict[UUID, PositionFacts]]:
    allocation = allocation or uuid4()
    element = open_element(
        rehearsal=False,
        live=True,
        allocation_id=allocation,
        exchange=element_pool.exchange,
        venue=element_pool.venue,
        settlement_currency=element_pool.settlement_currency,
        symbol=reader_symbol or symbol,
    )
    groups = groups_override or (
        fill_aggregate(
            allocation,
            STRATEGY,
            side=side,
            quantity=QUANTITY,
            price=PRICE,
            symbol=symbol,
            fee=FEE,
            pool=element_pool,
        ),
    )
    facts = position_facts(
        allocation,
        STRATEGY,
        groups,
        margin=MARGIN,
        status=status,
        reservation_pool=reservation_pool,
    )
    return element, {allocation: facts}


def _assert_one_warning(
    caplog: pytest.LogCaptureFixture, *must_contain: object
) -> logging.LogRecord:
    records = _records(caplog)
    messages = [r.getMessage() for r in records]
    assert len(records) == 1, f"expected exactly one record, got {messages}"
    (record,) = records
    assert record.levelno == logging.WARNING, f"expected a WARNING, got {record.levelname}"
    message = record.getMessage()
    for needle in must_contain:
        assert str(needle) in message, f"{needle!r} is not in the WARNING: {message}"
    for amount in FORBIDDEN:
        assert amount not in message, f"the WARNING leaks an amount ({amount}): {message}"
    return record


# --- nothing wrong, nothing logged ----------------------------------------------


async def test_a_state_with_nothing_wrong_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    allocation, attempt = uuid4(), uuid4()
    element, facts = _good(allocation)
    row = DiscrepancyRow(
        discrepancy_id=uuid4(),
        pool=POOL,
        symbol="STXUSDT",  # the venue's spelling; the fills say STXUSDT.P
        status="CONFIRMED",
        venue_net_base=Decimal(0),
        ledger_net_base=Decimal("0.82"),
        open_allocation_ids=(allocation,),
        last_observed_at=datetime(2026, 10, 12, 11, 30, tzinfo=UTC),
        resolved_at=None,
    )

    state = await _read(
        [element],
        [in_flight_element(rehearsal=False, attempt_id=attempt)],
        facts=facts,
        submitted=[submitted_order(attempt, strategy_id=STRATEGY)],
        rows=[row],
    )

    assert _records(caplog) == []
    assert state.positions[0].venue_disagreement is not None


# --- K row 4: a reservation that is not FILLED -----------------------------------


async def test_a_reservation_that_reads_expired_is_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation = uuid4()
    element, facts = _good(allocation, status="EXPIRED")

    state = await _read([element], facts=facts)

    _assert_one_warning(caplog, allocation, "EXPIRED")
    (position,) = state.positions
    assert position.reservation_status == "EXPIRED"
    assert position.pool == POOL


async def test_a_standing_fault_is_one_warning_per_read(caplog: pytest.LogCaptureFixture) -> None:
    allocation = uuid4()
    element, facts = _good(allocation, status="RELEASED")

    await _read([element], facts=facts)
    await _read([element], facts=facts)

    assert len(_records(caplog)) == 2


# --- K row 9: the fold says open, the display net is zero -------------------------


async def test_the_fold_calling_open_what_the_display_net_calls_zero_is_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation = uuid4()
    groups = (
        fill_aggregate(allocation, STRATEGY, side="BUY", quantity=QUANTITY, price=PRICE, fee=FEE),
        fill_aggregate(allocation, STRATEGY, side="SELL", quantity=QUANTITY, price=PRICE),
    )
    element, facts = _good(allocation, groups_override=groups)

    state = await _read([element], facts=facts)

    _assert_one_warning(caplog, allocation)
    (position,) = state.positions
    assert position.figures_missing is FiguresMissing.INCONSISTENT
    assert position.pool == POOL


# --- K row 10: the facts do not answer for an open allocation ---------------------


async def test_an_open_allocation_the_facts_do_not_answer_for_is_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation = uuid4()
    element = open_element(rehearsal=False, live=True, allocation_id=allocation)

    state = await _read([element], facts={})

    _assert_one_warning(caplog, allocation)
    (position,) = state.positions
    assert position.figures_missing is FiguresMissing.NO_FACTS
    assert position.pool == POOL


# --- K row 11: an unresolved symbol ---------------------------------------------


async def test_an_unresolved_symbol_is_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    allocation = uuid4()
    element, facts = _good(allocation, symbol="XYZBTC")

    state = await _read([element], facts=facts)

    _assert_one_warning(caplog, allocation)
    (position,) = state.positions
    assert position.figures_missing is FiguresMissing.UNRESOLVED_SYMBOL
    assert position.pool == POOL


# --- K row 12: a mark about another market --------------------------------------


async def test_a_confirmed_row_naming_the_allocation_under_another_market_is_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation = uuid4()
    element, facts = _good(allocation, symbol="STXUSDT.P")
    row = DiscrepancyRow(
        discrepancy_id=uuid4(),
        pool=POOL,
        symbol="AAVEUSDT",
        status="CONFIRMED",
        venue_net_base=Decimal(0),
        ledger_net_base=Decimal("0.82"),
        open_allocation_ids=(allocation,),
        last_observed_at=datetime(2026, 10, 12, 11, 30, tzinfo=UTC),
        resolved_at=None,
    )

    state = await _read([element], facts=facts, rows=[row])

    _assert_one_warning(caplog, allocation, row.discrepancy_id, "STXUSDT", "AAVEUSDT")
    (position,) = state.positions
    assert position.venue_disagreement is not None  # the mark stays: the allocation id is the key
    assert position.pool == POOL


# --- K row 16: an in-flight element with no submitted row -------------------------


async def test_an_in_flight_element_with_no_submitted_row_is_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempt = uuid4()
    element = in_flight_element(rehearsal=False, attempt_id=attempt, exchange="binance")

    state = await _read(in_flight=[element], submitted=[])

    _assert_one_warning(caplog, attempt)
    (order,) = state.orders
    assert order.attempt_id == attempt
    assert order.pool == BINANCE


# --- K row 17: a pool or a strategy that is not the reservation's -------------------


async def test_a_position_whose_fills_name_one_pool_and_whose_reservation_another(
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation = uuid4()
    element, facts = _good(allocation, reservation_pool=BINANCE)

    state = await _read([element], facts=facts)

    _assert_one_warning(caplog, allocation, "bybit/usdt-m/USDT", "binance/usdt-m/USDT")
    (position,) = state.positions
    assert position.pool == POOL  # the guard's, never the reservation's
    assert position.strategy_id == STRATEGY


@pytest.mark.parametrize("element_in", [POOL, BINANCE], ids=["element-bybit", "element-binance"])
@pytest.mark.parametrize("bybit_first", [True, False], ids=["bybit-first", "binance-first"])
async def test_an_allocation_whose_fills_are_in_two_pools_is_one_warning_whatever_the_order(
    caplog: pytest.LogCaptureFixture, element_in: PoolLabel, bybit_first: bool
) -> None:
    """The reader's order is not fixed and its element takes one group's pool: the
    check compares EVERY group, so the fault is logged whichever one it took."""
    allocation = uuid4()
    in_bybit = fill_aggregate(allocation, STRATEGY, pool=POOL, quantity=QUANTITY, fee=FEE)
    in_binance = fill_aggregate(allocation, STRATEGY, pool=BINANCE, quantity=QUANTITY, fee=FEE)
    groups = (in_bybit, in_binance) if bybit_first else (in_binance, in_bybit)
    element, facts = _good(allocation, element_pool=element_in, groups_override=groups)

    state = await _read([element], facts=facts)

    _assert_one_warning(caplog, allocation, "bybit/usdt-m/USDT", "binance/usdt-m/USDT")
    (position,) = state.positions
    assert position.pool == element_in
    assert position.strategy_id == STRATEGY


async def test_an_allocation_whose_fills_belong_to_another_strategy_is_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation = uuid4()
    groups = (
        fill_aggregate(allocation, STRATEGY, quantity=QUANTITY, price=PRICE, fee=FEE),
        fill_aggregate(allocation, OTHER_STRATEGY, quantity=QUANTITY, price=PRICE, fee=FEE),
    )
    element, facts = _good(allocation, groups_override=groups)

    state = await _read([element], facts=facts)

    _assert_one_warning(caplog, allocation, STRATEGY, OTHER_STRATEGY)
    (position,) = state.positions
    assert position.strategy_id == STRATEGY


async def test_an_order_whose_attempt_names_one_pool_and_whose_reservation_another(
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempt = uuid4()
    element = in_flight_element(rehearsal=False, attempt_id=attempt)
    submitted = [submitted_order(attempt, strategy_id=STRATEGY, reservation_pool=BINANCE)]

    state = await _read(in_flight=[element], submitted=submitted)

    _assert_one_warning(caplog, attempt, "bybit/usdt-m/USDT", "binance/usdt-m/USDT")
    (order,) = state.orders
    assert order.pool == POOL
    assert order.strategy_id == STRATEGY


async def test_a_submitted_attempt_with_no_reservation_is_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempt = uuid4()
    element = in_flight_element(rehearsal=False, attempt_id=attempt)
    submitted = [
        submitted_order(
            attempt, strategy_id=None, name=None, archived=None, reservation_pool=None
        )
    ]

    state = await _read(in_flight=[element], submitted=submitted)

    _assert_one_warning(caplog, attempt)
    (order,) = state.orders
    assert order.pool == POOL


async def test_an_attempt_the_reader_did_not_return_with_a_pool_difference_is_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    attempt = uuid4()
    submitted = [submitted_order(attempt, strategy_id=STRATEGY, reservation_pool=BINANCE)]

    state = await _read(submitted=submitted)

    _assert_one_warning(caplog, attempt, "bybit/usdt-m/USDT", "binance/usdt-m/USDT")
    (order,) = state.orders
    assert order.pool == POOL


async def test_the_pool_check_changes_nothing_in_the_answer() -> None:
    """The same state with and without a fault: identical but for the pool the
    fault is about. The check logs; it never reorders, drops or rewrites."""
    allocation = uuid4()
    clean_element, clean_facts = _good(allocation)
    faulty_element, faulty_facts = _good(allocation, reservation_pool=BINANCE)

    clean = await _read([clean_element], facts=clean_facts)
    faulty = await _read([faulty_element], facts=faulty_facts)

    assert faulty == clean
