"""Unit tests: ``ReadOperationFills`` -- the individual fills of one operation
(design.md, addendum "a strategy's operations", sections D, E and G).

The source is a fake that holds fills by ``(strategy_id, allocation_id)``. The
same read is proven against real PostgreSQL in
``tests/performance/infrastructure/test_operation_fills_source.py`` and through
the route in ``test_operations_router.py``.

The read derives nothing: it asks for the cap plus one, serves the first 200
with a flag, raises for an operation with no fill, and refuses a fill of
another pool AFTER the read. Every log line carries ids and the cap only; a
price, a quantity or a fee never appears in one.
"""

import ast
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application import ports as ports_module
from strategy_manager.performance.application.read_operation_fills import (
    MAX_OPERATION_FILLS,
    OperationFills,
    ReadOperationFills,
    UnknownOperation,
)
from strategy_manager.performance.domain.operation import OperationFill
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from tests.performance.fakes import FakeOperationFillsSource

POOL = PoolKey(Exchange.BYBIT, Venue.USDT_M, Currency.USDT)
T0 = datetime(2026, 9, 21, 12, 0, 0, 123456, tzinfo=UTC)
LOGGER = "strategy_manager.performance.application.read_operation_fills"
STRATEGY = UUID(int=1)
OTHER_STRATEGY = UUID(int=2)
ALLOCATION = UUID(int=10)


def _fill(
    n: int = 0,
    *,
    side: str = "BUY",
    rehearsal: bool = False,
    exchange: str = "bybit",
    venue: str = "usdt-m",
    settlement_currency: str = "USDT",
) -> OperationFill:
    return OperationFill(
        filled_at=T0 + timedelta(seconds=n),
        side=side,
        price=Decimal("7391.25"),
        quantity=Decimal("6283.5"),
        fee=Decimal("0.8447"),
        fee_currency="USDT",
        rehearsal=rehearsal,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
    )


def _source(fills: list[OperationFill]) -> FakeOperationFillsSource:
    return FakeOperationFillsSource({(STRATEGY, ALLOCATION): fills})



async def test_it_asks_the_source_for_the_cap_plus_one() -> None:
    source = _source([_fill()])

    await ReadOperationFills(source).read(STRATEGY, POOL, ALLOCATION)

    assert [limit for _, _, limit in source.calls] == [MAX_OPERATION_FILLS + 1]
    assert MAX_OPERATION_FILLS == 200


async def test_the_source_is_called_with_the_strategy_and_the_allocation_together() -> None:
    source = _source([_fill()])

    await ReadOperationFills(source).read(STRATEGY, POOL, ALLOCATION)

    assert [(strategy, allocation) for strategy, allocation, _ in source.calls] == [
        (STRATEGY, ALLOCATION)
    ]


async def test_it_serves_the_fills_in_the_order_the_source_gave_them() -> None:
    fills = [_fill(0), _fill(1, side="SELL")]

    result = await ReadOperationFills(_source(fills)).read(STRATEGY, POOL, ALLOCATION)

    assert result == OperationFills(
        allocation_id=ALLOCATION, fills=tuple(fills), truncated=False
    )


async def test_201_fills_answer_200_truncated_and_one_warning_naming_strategy_allocation_and_the_cap(  # noqa: E501
    caplog: pytest.LogCaptureFixture,
) -> None:
    fills = [_fill(n) for n in range(201)]

    with caplog.at_level(logging.INFO, logger=LOGGER):
        result = await ReadOperationFills(_source(fills)).read(STRATEGY, POOL, ALLOCATION)

    assert (len(result.fills), result.truncated) == (200, True)
    assert result.fills == tuple(fills[:200])
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert str(STRATEGY) in message
    assert str(ALLOCATION) in message
    assert "200" in message
    assert [r for r in caplog.records if r.levelno != logging.WARNING] == []


async def test_exactly_200_fills_are_not_truncated_and_log_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fills = [_fill(n) for n in range(200)]

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        result = await ReadOperationFills(_source(fills)).read(STRATEGY, POOL, ALLOCATION)

    assert (len(result.fills), result.truncated) == (200, False)
    assert caplog.records == []


async def test_an_empty_answer_raises_unknown_operation_and_logs_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caught: BaseException | None = None

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        try:
            await ReadOperationFills(_source([])).read(STRATEGY, POOL, ALLOCATION)
        except UnknownOperation as exc:
            caught = exc

    assert type(caught) is UnknownOperation
    assert [(r.levelno, str(STRATEGY) in r.getMessage(), str(ALLOCATION) in r.getMessage())
            for r in caplog.records] == [(logging.WARNING, True, True)]


async def test_an_operation_of_another_strategy_is_unknown_and_reads_nothing_of_it() -> None:
    source = FakeOperationFillsSource({(OTHER_STRATEGY, ALLOCATION): [_fill()]})
    caught: BaseException | None = None

    try:
        await ReadOperationFills(source).read(STRATEGY, POOL, ALLOCATION)
    except UnknownOperation as exc:
        caught = exc

    assert type(caught) is UnknownOperation


@pytest.mark.parametrize(
    "foreign",
    [
        {"exchange": "pionex"},
        {"venue": "spot"},
        {"settlement_currency": "BTC"},
    ],
    ids=["exchange", "venue", "settlement_currency"],
)
async def test_a_fill_of_another_pool_is_refused_as_an_invariant_violation_and_nothing_is_returned(
    foreign: dict[str, str],
) -> None:
    fills = [_fill(0), _fill(1, **foreign)]
    result: OperationFills | None = None
    caught: BaseException | None = None

    try:
        result = await ReadOperationFills(_source(fills)).read(STRATEGY, POOL, ALLOCATION)
    except InvariantViolation as exc:
        caught = exc

    assert type(caught) is InvariantViolation
    assert result is None


async def test_a_mixed_allocation_returns_every_fill_each_with_its_own_flag_and_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fills = [
        _fill(0, rehearsal=False),
        _fill(1, side="SELL", rehearsal=False),
        _fill(2, rehearsal=True),
        _fill(3, side="SELL", rehearsal=True),
    ]

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        result = await ReadOperationFills(_source(fills)).read(STRATEGY, POOL, ALLOCATION)

    assert [fill.rehearsal for fill in result.fills] == [False, False, True, True]
    assert result.fills == tuple(fills)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(STRATEGY) in warnings[0].getMessage()
    assert str(ALLOCATION) in warnings[0].getMessage()
    assert len(caplog.records) == 1


async def test_an_operation_wholly_of_one_origin_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        rehearsal = _source([_fill(0, rehearsal=True), _fill(1, rehearsal=True)])
        await ReadOperationFills(rehearsal).read(STRATEGY, POOL, ALLOCATION)
        live = _source([_fill(0), _fill(1)])
        await ReadOperationFills(live).read(STRATEGY, POOL, ALLOCATION)

    assert caplog.records == []


def test_the_ports_module_imports_no_type_of_another_module() -> None:
    """``ports.py`` speaks in ``performance``'s own types: no ``signals``,
    ``execution``, ``ledger`` or ``reconciliation`` type crosses into it, and no
    infrastructure module of any module does."""
    tree = ast.parse(Path(ports_module.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    leaked = sorted(
        name
        for name in imported
        if any(
            name.startswith(f"strategy_manager.{module}")
            for module in ("signals", "execution", "ledger", "reconciliation")
        )
        or name.endswith(".infrastructure")
        or ".infrastructure." in name
    )

    assert leaked == []


async def test_no_line_carries_a_price_a_quantity_or_a_fee(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every line of the read, on the three paths that log (truncated, mixed,
    unknown), is checked for the stored numbers: ids and the cap only."""
    truncated = [_fill(n) for n in range(201)]
    mixed = [_fill(0), _fill(1, rehearsal=True)]

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await ReadOperationFills(_source(truncated)).read(STRATEGY, POOL, ALLOCATION)
        await ReadOperationFills(_source(mixed)).read(STRATEGY, POOL, ALLOCATION)
        with pytest.raises(UnknownOperation):
            await ReadOperationFills(_source([])).read(STRATEGY, POOL, ALLOCATION)

    assert len(caplog.records) == 3
    for record in caplog.records:
        message = record.getMessage()
        assert "." not in message
        for stored in ("7391", "6283", "8447", "USDT"):
            assert stored not in message
