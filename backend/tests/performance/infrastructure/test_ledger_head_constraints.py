"""What ``ledger_entries`` can hold and which index serves it, on the schema
production runs (design.md, addendum "a strategy's operations", section G, T6
and T17) [DB].

Runs on a database built with ``alembic upgrade head`` through
``tests/pg_head_schema.py``, NOT on the ORM-built test schema. Two facts that the
operations list and the fills read rest on exist only in migrations:

* ``price``, ``quantity`` and ``notional`` are ``CHECK > 0`` only in migration
  0005 (T6). The ORM model declares none, so on the ORM schema a zero would be
  stored and a test of the refusal would pass for the wrong reason. This is why
  "a fill with a non-positive price cannot be stored" is a premise of the design
  and not a case the read handles.
* ``ix_ledger_allocation`` on ``ledger_entries(allocation_id)`` is created only
  by migration 0012 (T17). The ORM model declares no index. The index is read
  from ``pg_indexes``, never from a query plan: on a table of a few rows the
  planner scans whatever indexes exist.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests.pg_head_schema import migrated_head_database
from tests.signals.infrastructure.conftest import seed_strategy

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]

_INSERT = text(
    "INSERT INTO ledger_entries (strategy_id, allocation_id, execution_attempt_id, exchange, "
    "venue, settlement_currency, symbol, side, quantity, price, fee, fee_currency, notional, "
    "exchange_order_id, exchange_fill_id, filled_at, usd_rate_at_fill) "
    "VALUES (:strategy_id, :allocation_id, :attempt_id, 'bybit', 'usdt-m', 'USDT', 'STXUSDT', "
    "'BUY', :quantity, :price, 0, 'USDT', :notional, :order_id, :fill_id, :filled_at, 1)"
)


@pytest.fixture(scope="module")
def head_database_url() -> Iterator[str]:
    with migrated_head_database("strategy_manager_test_ledger_head") as url:
        yield url


@pytest.fixture
async def engine(head_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(head_database_url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.fixture
async def factory(engine: AsyncEngine) -> Factory:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_allocation(factory: Factory) -> tuple[UUID, UUID, UUID]:
    """A strategy, the signal it ordered, the reservation (the allocation) and its
    opening attempt, on the head schema (foreign keys and all)."""
    from tests.performance.infrastructure.conftest import (
        seed_execution_attempt,
        seed_reservation,
        seed_signal,
    )

    strategy_id, signal_id, allocation_id, attempt_id = uuid4(), uuid4(), uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    await seed_reservation(
        factory, reservation_id=allocation_id, strategy_id=strategy_id, signal_id=signal_id
    )
    await seed_execution_attempt(factory, attempt_id=attempt_id, reservation_id=allocation_id)
    return strategy_id, allocation_id, attempt_id


async def _insert(
    factory: Factory,
    ids: tuple[UUID, UUID, UUID],
    *,
    quantity: str = "1",
    price: str = "0.4512",
    notional: str = "0.4512",
) -> None:
    strategy_id, allocation_id, attempt_id = ids
    async with factory() as session:
        await session.execute(
            _INSERT,
            {
                "strategy_id": strategy_id,
                "allocation_id": allocation_id,
                "attempt_id": attempt_id,
                "quantity": Decimal(quantity),
                "price": Decimal(price),
                "notional": Decimal(notional),
                "order_id": f"EX-{uuid4()}",
                "fill_id": f"F-{uuid4()}",
                "filled_at": datetime(2026, 9, 21, 12, tzinfo=UTC),
            },
        )
        await session.commit()


async def test_a_positive_fill_is_stored(factory: Factory) -> None:
    """The control for the refusals below: the same insert with usable values
    succeeds, so they are refusals of the VALUE and not of the statement."""
    ids = await _seed_allocation(factory)

    await _insert(factory, ids)

    async with factory() as session:
        stored = (
            await session.execute(
                text("SELECT count(*) FROM ledger_entries WHERE allocation_id = :a"),
                {"a": ids[1]},
            )
        ).scalar_one()
    assert stored == 1


@pytest.mark.parametrize("column", ["price", "quantity", "notional"])
@pytest.mark.parametrize("value", ["0", "-1"])
async def test_a_non_positive_price_quantity_or_notional_cannot_be_stored(
    factory: Factory, column: str, value: str
) -> None:
    ids = await _seed_allocation(factory)

    with pytest.raises(IntegrityError) as refused:
        await _insert(factory, ids, **{column: value})

    assert f"ck_ledger_entries_{column}_positive" in str(refused.value)


async def test_ix_ledger_allocation_exists_on_ledger_entries_allocation_id(
    factory: Factory,
) -> None:
    async with factory() as session:
        definitions = (
            await session.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE tablename = 'ledger_entries' AND indexname = 'ix_ledger_allocation'"
                )
            )
        ).scalars().all()

    assert len(definitions) == 1
    assert "ON public.ledger_entries" in definitions[0]
    assert "(allocation_id)" in definitions[0]
