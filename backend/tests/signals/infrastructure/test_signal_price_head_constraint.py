"""What ``signals.price`` can hold, on the schema production runs (decision 45;
design § F, test 11).

Runs on a database built with ``alembic upgrade head`` through
``tests/pg_head_schema.py``, NOT on the ORM-built test schema:
``ck_signals_price_positive`` exists only in migration 0002 and the ORM model
declares no such CHECK, so on the ORM schema a price of zero is stored and the
test would pass for the wrong reason.

The two values the design left unverified are PINNED here as observed on
2026-10-04 (task 9q.14), by a statement run first and then asserted:

* ``NaN`` IS stored and read back as ``NaN``: PostgreSQL's numeric ordering
  puts NaN above every number, so ``price > 0`` does not exclude it. Since
  task 9qf.1 the webhook refuses an alert carrying ``"NaN"`` before anything is
  stored, so this pins what the database would do if anything else wrote one.
* ``Infinity`` and ``-Infinity`` are refused: a ``NUMERIC(38, 18)`` column
  cannot hold them (numeric value out of range).
"""

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.signals.infrastructure.models import SignalRow
from tests.pg_head_schema import migrated_head_database
from tests.signals.infrastructure.conftest import seed_strategy

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture(scope="module")
def head_database_url() -> Iterator[str]:
    with migrated_head_database("strategy_manager_test_signal_price") as url:
        yield url


@pytest.fixture
async def engine(head_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(head_database_url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.fixture
async def factory(engine: AsyncEngine) -> Factory:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _insert(factory: Factory, strategy_id: UUID, price: Decimal) -> UUID:
    signal_id = uuid4()
    async with factory() as session:
        session.add(
            SignalRow(
                id=signal_id,
                strategy_id=strategy_id,
                idempotency_key=f"price-{signal_id}",
                raw_payload={},
                action="buy",
                contracts=Decimal("1"),
                position_size=Decimal("1"),
                price=price,
                symbol="STXUSDT.P",
                signal_type="probe",
            )
        )
        await session.commit()
    return signal_id


async def _read_price(factory: Factory, signal_id: UUID) -> Decimal:
    async with factory() as session:
        return (
            await session.execute(select(SignalRow.price).where(SignalRow.id == signal_id))
        ).scalar_one()


async def _strategy(factory: Factory) -> UUID:
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    return strategy_id


@pytest.mark.parametrize("price", [Decimal("0"), Decimal("-1"), Decimal("-0.4633")])
async def test_signals_price_refuses_zero_and_a_negative(factory: Factory, price: Decimal) -> None:
    strategy_id = await _strategy(factory)

    with pytest.raises(IntegrityError) as refused:
        await _insert(factory, strategy_id, price)

    assert "ck_signals_price_positive" in str(refused.value)


async def test_a_positive_price_is_stored_exactly_as_the_column_scales_it(
    factory: Factory,
) -> None:
    """The control for the refusals above: the same insert with a usable price
    succeeds, so they are refusals of the VALUE and not of the statement. A
    19-place price is rounded to 18 once, here, by the column."""
    strategy_id = await _strategy(factory)

    signal_id = await _insert(factory, strategy_id, Decimal("0.1234567890123456789"))

    assert await _read_price(factory, signal_id) == Decimal("0.123456789012345679")


async def test_what_the_database_does_with_nan_and_with_infinity(factory: Factory) -> None:
    strategy_id = await _strategy(factory)

    # NaN: accepted, and read back as NaN.
    nan_signal = await _insert(factory, strategy_id, Decimal("NaN"))
    assert (await _read_price(factory, nan_signal)).is_nan()

    # Infinity, either sign: refused by the column's own range, not by the CHECK.
    for infinite in (Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(DBAPIError) as refused:
            await _insert(factory, strategy_id, infinite)
        cause = refused.value.orig.__cause__  # type: ignore[union-attr]
        assert isinstance(cause, asyncpg.exceptions.NumericValueOutOfRangeError)
        assert not isinstance(refused.value, IntegrityError)
