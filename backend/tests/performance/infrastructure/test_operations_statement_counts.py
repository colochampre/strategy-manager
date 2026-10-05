"""Integration test: the trades list never degrades to one statement per row
(design.md, addendum "a strategy's operations", sections E and H) [DB].

A ``before_cursor_execute`` listener counts the statements one read issues, on
the one ledger plus enough extra real operations to fill a page of twenty. Real
PostgreSQL, ORM schema.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.performance.application.read_strategy_trades import ReadStrategyTrades
from strategy_manager.performance.infrastructure.allocation_fills_source import (
    SqlAlchemyAllocationFillsSource,
)
from strategy_manager.performance.infrastructure.rehearsal_pricing_source import (
    SqlAlchemyRehearsalPricingSource,
)
from tests.performance.infrastructure.conftest import OPERATIONS_T0, OperationsLedger
from tests.performance.infrastructure.test_allocation_fills_source import (
    BYBIT,
    _fill,
    _record,
    _seed_allocation,
)

pytestmark = pytest.mark.integration


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


async def _add_real_operations(
    factory: async_sessionmaker[AsyncSession], strategy_id: UUID, count: int
) -> None:
    for n in range(count):
        _, allocation_id, attempt_id = await _seed_allocation(factory, strategy_id=strategy_id)
        closed_at = OPERATIONS_T0 - timedelta(days=1, minutes=n)
        await _record(
            factory,
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="BUY",
                quantity="1",
                symbol="STXUSDT.P",
                filled_at=closed_at - timedelta(minutes=30),
            ),
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="SELL",
                quantity="1",
                price="101",
                symbol="STXUSDT",
                filled_at=closed_at,
            ),
        )


async def _statements(
    factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    strategy_id: UUID,
    *,
    limit: int,
    include_rehearsal: bool,
) -> tuple[int, int, int]:
    """``(statements, rows, rehearsal rows)`` of one page read."""
    async with factory() as session:
        reader = ReadStrategyTrades(
            SqlAlchemyAllocationFillsSource(session), SqlAlchemyRehearsalPricingSource(session)
        )
        with _captured_sql(engine) as statements:
            page = await reader.read(
                strategy_id, BYBIT, limit=limit, include_rehearsal=include_rehearsal
            )
    return len(statements), len(page.trades), sum(item.rehearsal for item in page.trades)


async def test_the_list_issues_the_same_number_of_statements_for_a_page_of_one_row_and_of_twenty_and_one_more_when_the_page_holds_a_rehearsal_row(  # noqa: E501
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
    operations_ledger: OperationsLedger,
) -> None:
    ledger = operations_ledger
    await _add_real_operations(pg_session_factory, ledger.strategy_id, 20)

    one = await _statements(
        pg_session_factory, pg_engine, ledger.strategy_id, limit=1, include_rehearsal=False
    )
    twenty = await _statements(
        pg_session_factory, pg_engine, ledger.strategy_id, limit=20, include_rehearsal=False
    )
    # The extra real operations are older than the ledger's, so opted in the newest
    # rows are the four rehearsal ones: their facts are read once.
    with_one_rehearsal = await _statements(
        pg_session_factory, pg_engine, ledger.strategy_id, limit=1, include_rehearsal=True
    )
    with_four_rehearsal = await _statements(
        pg_session_factory, pg_engine, ledger.strategy_id, limit=20, include_rehearsal=True
    )

    assert (one[1], twenty[1]) == (1, 20)
    assert (with_one_rehearsal[1:], with_four_rehearsal[1:]) == ((1, 1), (20, 4))
    assert twenty[0] == one[0]
    assert with_one_rehearsal[0] == one[0] + 1
    assert with_four_rehearsal[0] == one[0] + 1
