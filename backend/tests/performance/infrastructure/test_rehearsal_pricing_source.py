"""Integration test: ``SqlAlchemyRehearsalPricingSource``, the one statement that
says how the opening fills of rehearsal operations were priced (design.md,
addendum "a strategy's operations", sections C and E) [DB].

Real PostgreSQL on the ORM schema, with real ``signals`` rows: the alert's price
is the ``price`` of the signal a reservation names, so it is set on that row and
fills are written through ``RecordFill`` (the production write path), never by
the simulated exchange. The classification itself is tested in the domain; this
file tests only what the statement answers and how many statements it takes.

**Binding testing lesson**: a symbol has three spellings. The operation below
opens as Pionex's ``STXUSDT_PERP`` and closes as TradingView's ``STXUSDT.P``, and
the answer is keyed by allocation, never by symbol.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
from strategy_manager.performance.domain.operation import PricingFacts, SidePrices
from strategy_manager.performance.infrastructure.rehearsal_pricing_source import (
    SqlAlchemyRehearsalPricingSource,
)
from tests.performance.infrastructure.test_allocation_fills_source import (
    BYBIT,
    PIONEX,
    T0,
    _fill,
    _record,
    _seed_allocation,
)

pytestmark = pytest.mark.integration


async def _set_alert_price(
    factory: async_sessionmaker[AsyncSession], allocation_id: UUID, price: str
) -> None:
    """The price the alert carried: ``signals.price`` of the signal the
    reservation names."""
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE signals SET price = :price WHERE id = "
                "(SELECT signal_id FROM reservations WHERE id = :id)"
            ),
            {"price": Decimal(price), "id": allocation_id},
        )
        await session.commit()


async def _rehearsal_round_trip(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    allocation_id: UUID,
    attempt_id: UUID,
    *,
    alert: str,
    opening_prices: tuple[str, ...] = ("1",),
    closing_price: str = "0.4631",
    pool: PoolKey = BYBIT,
) -> None:
    """An operation opened as ``STXUSDT_PERP`` (one fill per opening price) and
    closed as ``STXUSDT.P``, every fill carrying the rehearsal prefix."""
    await _set_alert_price(factory, allocation_id, alert)
    opening = [
        _fill(
            strategy_id=strategy_id,
            allocation_id=allocation_id,
            attempt_id=attempt_id,
            side="BUY",
            quantity="100",
            price=price,
            symbol="STXUSDT_PERP",
            filled_at=T0 + timedelta(seconds=n),
            fill_id=f"{REHEARSAL_FILL_ID_PREFIX}{uuid4()}",
            pool=pool,
        )
        for n, price in enumerate(opening_prices)
    ]
    closing = _fill(
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        attempt_id=attempt_id,
        side="SELL",
        quantity=str(100 * len(opening_prices)),
        price=closing_price,
        symbol="STXUSDT.P",
        filled_at=T0 + timedelta(hours=1),
        fill_id=f"{REHEARSAL_FILL_ID_PREFIX}{uuid4()}",
        pool=pool,
    )
    await _record(factory, *opening, closing)


async def _facts(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    allocation_ids: list[UUID],
    pool: PoolKey = BYBIT,
) -> dict[UUID, PricingFacts]:
    async with factory() as session:
        answer = await SqlAlchemyRehearsalPricingSource(session).pricing_facts(
            pool, strategy_id, allocation_ids
        )
        return dict(answer)


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


async def test_it_answers_per_allocation_the_alerts_price_and_the_lowest_and_highest_price_of_each_side(  # noqa: E501
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_allocation(pg_session_factory)
    await _rehearsal_round_trip(
        pg_session_factory, strategy_id, allocation_id, attempt_id, alert="0.4512"
    )

    answer = await _facts(pg_session_factory, strategy_id, [allocation_id])

    assert answer == {
        allocation_id: PricingFacts(
            alert_price=Decimal("0.4512"),
            buy=SidePrices(lowest=Decimal("1"), highest=Decimal("1")),
            sell=SidePrices(lowest=Decimal("0.4631"), highest=Decimal("0.4631")),
        )
    }


async def test_two_opening_fills_at_different_prices_report_a_low_and_a_high(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_allocation(pg_session_factory)
    await _rehearsal_round_trip(
        pg_session_factory,
        strategy_id,
        allocation_id,
        attempt_id,
        alert="0.4512",
        opening_prices=("0.4512", "1", "0.45"),
    )

    answer = await _facts(pg_session_factory, strategy_id, [allocation_id])

    assert list(answer) == [allocation_id]
    assert answer[allocation_id].buy == SidePrices(Decimal("0.45"), Decimal("1"))
    assert answer[allocation_id].alert_price == Decimal("0.4512")


async def test_the_alert_price_is_the_one_on_the_signal_the_reservation_names(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two allocations of ONE strategy, each ordered by its own signal."""
    strategy_id, first, first_attempt = await _seed_allocation(pg_session_factory)
    _, second, second_attempt = await _seed_allocation(
        pg_session_factory, strategy_id=strategy_id
    )
    await _rehearsal_round_trip(
        pg_session_factory, strategy_id, first, first_attempt, alert="0.5"
    )
    await _rehearsal_round_trip(
        pg_session_factory, strategy_id, second, second_attempt, alert="0.7"
    )

    answer = await _facts(pg_session_factory, strategy_id, [first, second])

    assert {key: facts.alert_price for key, facts in answer.items()} == {
        first: Decimal("0.5"),
        second: Decimal("0.7"),
    }


async def test_an_allocation_of_another_strategy_is_not_answered(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    mine, my_allocation, my_attempt = await _seed_allocation(pg_session_factory)
    theirs, their_allocation, their_attempt = await _seed_allocation(pg_session_factory)
    await _rehearsal_round_trip(
        pg_session_factory, mine, my_allocation, my_attempt, alert="0.4512"
    )
    await _rehearsal_round_trip(
        pg_session_factory, theirs, their_allocation, their_attempt, alert="0.4512"
    )

    answer = await _facts(pg_session_factory, mine, [my_allocation, their_allocation])

    assert list(answer) == [my_allocation]


async def test_an_allocation_of_another_pool_is_not_answered(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_allocation(pg_session_factory)
    await _rehearsal_round_trip(
        pg_session_factory, strategy_id, allocation_id, attempt_id, alert="0.4512"
    )

    in_its_pool = await _facts(pg_session_factory, strategy_id, [allocation_id], BYBIT)
    in_another = await _facts(pg_session_factory, strategy_id, [allocation_id], PIONEX)

    assert list(in_its_pool) == [allocation_id]
    assert in_another == {}


async def test_it_issues_one_statement_for_one_id_and_for_twenty(
    pg_session_factory: async_sessionmaker[AsyncSession], pg_engine: AsyncEngine
) -> None:
    strategy_id, first, first_attempt = await _seed_allocation(pg_session_factory)
    await _rehearsal_round_trip(
        pg_session_factory, strategy_id, first, first_attempt, alert="0.4512"
    )
    ids = [first]
    for _ in range(19):
        _, allocation_id, attempt_id = await _seed_allocation(
            pg_session_factory, strategy_id=strategy_id
        )
        await _rehearsal_round_trip(
            pg_session_factory, strategy_id, allocation_id, attempt_id, alert="0.4512"
        )
        ids.append(allocation_id)

    with _captured_sql(pg_engine) as for_one:
        one = await _facts(pg_session_factory, strategy_id, ids[:1])
    with _captured_sql(pg_engine) as for_twenty:
        twenty = await _facts(pg_session_factory, strategy_id, ids)

    assert (len(one), len(twenty)) == (1, 20)
    assert (len(for_one), len(for_twenty)) == (1, 1)


async def test_the_answer_is_keyed_by_allocation_whatever_the_spelling_of_each_symbol(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_allocation(pg_session_factory)
    await _rehearsal_round_trip(
        pg_session_factory, strategy_id, allocation_id, attempt_id, alert="0.4512"
    )

    answer = await _facts(pg_session_factory, strategy_id, [allocation_id])

    assert list(answer) == [allocation_id]
    facts = answer[allocation_id]
    assert (facts.buy is not None, facts.sell is not None) == (True, True)
