"""Integration test: ``SqlAlchemyOperationFillsSource``, the one SELECT behind the
fills of an operation [DB] (design.md, addendum "a strategy's operations",
sections D, E and H).

Real PostgreSQL on the ORM schema, over the one ledger of unit 9p.4
(``operations_ledger``) plus the extra operations a test needs. Every fill is
written through ``RecordFill``.

**Binding testing lesson**: a symbol has three spellings. The rehearsal
operation of the one ledger opens as ``STXUSDT_PERP`` (Pionex's) and closes as
``STXUSDT.P`` (TradingView's); the real one opens as ``STXUSDT.P`` and closes as
``STXUSDT``. The source keys on the allocation, so it answers the fills of BOTH
spellings, and the fill it answers carries no symbol at all.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.performance.domain.operation import OperationFill
from strategy_manager.performance.infrastructure.operation_fills_source import (
    SqlAlchemyOperationFillsSource,
)
from tests.performance.infrastructure.conftest import (
    OPERATIONS_T0,
    OperationsLedger,
    _rehearsal_id,
)
from tests.performance.infrastructure.test_allocation_fills_source import (
    _fill,
    _record,
    _seed_allocation,
)

pytestmark = pytest.mark.integration


async def _read(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    allocation_id: UUID,
    limit: int = 201,
) -> list[OperationFill]:
    async with factory() as session:
        return list(
            await SqlAlchemyOperationFillsSource(session).operation_fills(
                strategy_id, allocation_id, limit
            )
        )


@contextmanager
def _captured_sql(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record_statement(conn: object, cursor: object, statement: str, *rest: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record_statement)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record_statement)


async def test_the_fills_come_in_filled_at_then_id_order(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The later fill is inserted FIRST, so insertion order is not the answer."""
    strategy_id, allocation_id, attempt_id = await _seed_allocation(pg_session_factory)
    later = _fill(
        strategy_id=strategy_id, allocation_id=allocation_id, attempt_id=attempt_id,
        side="SELL", quantity="3", price="101", filled_at=OPERATIONS_T0 + timedelta(hours=1),
    )
    earlier = _fill(
        strategy_id=strategy_id, allocation_id=allocation_id, attempt_id=attempt_id,
        side="BUY", quantity="3", price="100", filled_at=OPERATIONS_T0,
    )
    await _record(pg_session_factory, later, earlier)

    fills = await _read(pg_session_factory, strategy_id, allocation_id)

    assert [(fill.side, fill.filled_at) for fill in fills] == [
        ("BUY", earlier.filled_at),
        ("SELL", later.filled_at),
    ]


async def test_fills_tied_on_filled_at_come_back_in_ascending_row_id_order(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Five fills at one instant answer in ascending ``ledger_entries.id`` order:
    the ``id`` half of ``ORDER BY filled_at, id``. The ids are random, so the
    expected order is read from the table itself and sorted by the UUID's integer
    value, which is the byte order PostgreSQL uses for ``uuid``."""
    strategy_id, allocation_id, attempt_id = await _seed_allocation(pg_session_factory)
    await _record(
        pg_session_factory,
        *(
            _fill(
                strategy_id=strategy_id, allocation_id=allocation_id, attempt_id=attempt_id,
                side="BUY", quantity=str(n), filled_at=OPERATIONS_T0,
            )
            for n in range(1, 6)
        ),
    )

    async with pg_session_factory() as session:
        stored = (
            await session.execute(
                text("SELECT id, quantity FROM ledger_entries WHERE allocation_id = :a"),
                {"a": allocation_id},
            )
        ).all()
    expected = [quantity for _, quantity in sorted(stored, key=lambda row: row[0].int)]

    first = await _read(pg_session_factory, strategy_id, allocation_id)
    second = await _read(pg_session_factory, strategy_id, allocation_id)

    assert [fill.quantity for fill in first] == expected
    assert [fill.quantity for fill in first] == [fill.quantity for fill in second]
    assert len(first) == 5


async def test_the_fills_of_both_spellings_are_returned(
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    rehearsal = await _read(pg_session_factory, ledger.strategy_id, ledger.fixed_one)
    real = await _read(pg_session_factory, ledger.strategy_id, ledger.real_long)

    # ``STXUSDT_PERP`` opened and ``STXUSDT.P`` closed the rehearsal operation;
    # ``STXUSDT.P`` opened and ``STXUSDT`` closed the real one.
    assert [fill.side for fill in rehearsal] == ["BUY", "SELL"]
    assert [fill.side for fill in real] == ["BUY", "BUY", "BUY", "SELL"]
    assert [str(fill.quantity) for fill in real] == [
        "100.000000000000000000",
        "300.000000000000000000",
        "600.000000000000000000",
        "1000.000000000000000000",
    ]


async def test_each_fills_rehearsal_flag_comes_from_its_own_fill_id(
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    mixed = await _read(pg_session_factory, ledger.strategy_id, ledger.mixed)
    rehearsal = await _read(pg_session_factory, ledger.strategy_id, ledger.alert_small)
    real = await _read(pg_session_factory, ledger.strategy_id, ledger.real_short)

    # The mixed allocation: a real round trip at 05:00 and 05:30, a rehearsal one
    # at 06:00 and 06:30.
    assert [fill.rehearsal for fill in mixed] == [False, False, True, True]
    assert [fill.rehearsal for fill in rehearsal] == [True, True]
    assert [fill.rehearsal for fill in real] == [False, False]


async def test_another_strategys_allocation_returns_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    asked_by_s1 = await _read(pg_session_factory, ledger.strategy_id, ledger.other)
    asked_by_s2 = await _read(pg_session_factory, ledger.other_strategy_id, ledger.other)

    assert asked_by_s1 == []
    assert len(asked_by_s2) == 2


async def test_an_unknown_allocation_returns_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    assert await _read(pg_session_factory, operations_ledger.strategy_id, UUID(int=7)) == []


async def test_the_limit_is_applied_in_sql(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_allocation(pg_session_factory)
    await _record(
        pg_session_factory,
        *(
            _fill(
                strategy_id=strategy_id, allocation_id=allocation_id, attempt_id=attempt_id,
                side="BUY", quantity="1", filled_at=OPERATIONS_T0 + timedelta(seconds=n),
            )
            for n in range(205)
        ),
    )

    cap_plus_one = await _read(pg_session_factory, strategy_id, allocation_id, 201)
    three = await _read(pg_session_factory, strategy_id, allocation_id, 3)

    assert (len(cap_plus_one), len(three)) == (201, 3)
    assert [fill.filled_at for fill in three] == [
        OPERATIONS_T0 + timedelta(seconds=n) for n in range(3)
    ]


async def test_it_issues_one_statement_for_one_fill_and_for_fifty(
    pg_session_factory: async_sessionmaker[AsyncSession], pg_engine: AsyncEngine
) -> None:
    strategy_id, one, one_attempt = await _seed_allocation(pg_session_factory)
    _, fifty, fifty_attempt = await _seed_allocation(pg_session_factory, strategy_id=strategy_id)
    await _record(
        pg_session_factory,
        _fill(strategy_id=strategy_id, allocation_id=one, attempt_id=one_attempt,
              side="BUY", quantity="1"),
        *(
            _fill(
                strategy_id=strategy_id, allocation_id=fifty, attempt_id=fifty_attempt,
                side="BUY", quantity="1", filled_at=OPERATIONS_T0 + timedelta(seconds=n),
            )
            for n in range(50)
        ),
    )

    counts: list[tuple[int, int]] = []
    for allocation_id in (one, fifty):
        async with pg_session_factory() as session:
            with _captured_sql(pg_engine) as statements:
                fills = await SqlAlchemyOperationFillsSource(session).operation_fills(
                    strategy_id, allocation_id, 201
                )
        counts.append((len(fills), len(statements)))

    assert counts == [(1, 1), (50, 1)]


async def test_an_open_allocations_fill_is_returned(
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    fills = await _read(pg_session_factory, ledger.strategy_id, ledger.open_real)
    open_rehearsal = await _read(pg_session_factory, ledger.strategy_id, ledger.open_rehearsal)

    assert [(fill.side, fill.rehearsal) for fill in fills] == [("BUY", False)]
    assert [(fill.side, fill.rehearsal) for fill in open_rehearsal] == [("BUY", True)]


async def test_a_fill_carries_its_stored_values_and_its_pool(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_allocation(pg_session_factory)
    await _record(
        pg_session_factory,
        _fill(
            strategy_id=strategy_id, allocation_id=allocation_id, attempt_id=attempt_id,
            side="SELL", quantity="2.5", price="0.4512", fee="0.00012", fee_currency="bnb",
            filled_at=OPERATIONS_T0, fill_id=_rehearsal_id(),
        ),
    )

    fills = await _read(pg_session_factory, strategy_id, allocation_id)

    assert len(fills) == 1
    fill = fills[0]
    assert fill == OperationFill(
        filled_at=OPERATIONS_T0,
        side="SELL",
        price=fill.price,
        quantity=fill.quantity,
        fee=fill.fee,
        fee_currency="BNB",
        rehearsal=True,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
    )
    assert (str(fill.price), str(fill.quantity), str(fill.fee)) == (
        "0.451200000000000000",
        "2.500000000000000000",
        "0.000120000000000000",
    )
