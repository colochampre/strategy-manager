"""``SqlAlchemyPoolSizing``: a pool's minimum order and latest snapshot, read for the
share preview (design.md, unit 12f addendum, section H; tasks.md 12f.9.11).

The adapter is ONE SELECT: the ``capital_pools`` row outer-joined to its
``pool_balance_snapshots`` row on the three-part key. No constraint or index decides
what it answers, so the ORM schema of ``tests/ledger/infrastructure/conftest.py`` on
a real PostgreSQL is enough.

The join is OUTER for the reason ``SqlAlchemyPoolOverview`` and
``SqlAlchemyStaleSnapshotReader`` give: a pool nothing has synced is the worst-off
one, and an inner join would make it vanish and read like a pool that does not exist.
``stale`` is the rule the overview applies, strictly: ``now - observed_at > max_age``.
The amount a share asks for is of the TOTAL, never of what is free, so the adapter
hands over ``total`` and never ``available``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.accounts.infrastructure.pool_sizing import SqlAlchemyPoolSizing
from strategy_manager.allocation.application.ports import PoolSizing, SizingSnapshot
from tests.ledger.infrastructure.conftest import pg_engine, pg_session_factory  # noqa: F401

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)
MAX_AGE = 90.0

BYBIT = ("bybit", "usdt-m", "USDT")
BINANCE = ("binance", "usdt-m", "USDT")


class FrozenClock:
    def now(self) -> datetime:
        return NOW


async def _snapshot(
    factory: async_sessionmaker[AsyncSession],
    pool: tuple[str, str, str],
    *,
    total: str,
    available: str,
    age: timedelta = timedelta(seconds=1),
) -> None:
    exchange, venue, currency = pool
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO pool_balance_snapshots "
                "(exchange, venue, settlement_currency, total, available, observed_at) "
                "VALUES (:e, :v, :c, :total, :available, :observed_at)"
            ),
            {
                "e": exchange,
                "v": venue,
                "c": currency,
                "total": Decimal(total),
                "available": Decimal(available),
                "observed_at": NOW - age,
            },
        )
        await session.commit()


async def _add_pool(
    factory: async_sessionmaker[AsyncSession], pool: tuple[str, str, str], minimum: str
) -> None:
    exchange, venue, currency = pool
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO capital_pools (exchange, venue, settlement_currency, min_order_size) "
                "VALUES (:e, :v, :c, :minimum)"
            ),
            {"e": exchange, "v": venue, "c": currency, "minimum": Decimal(minimum)},
        )
        await session.commit()


async def _read(
    factory: async_sessionmaker[AsyncSession],
    pool: tuple[str, str, str],
    max_age: float = MAX_AGE,
) -> PoolSizing | None:
    async with factory() as session:
        return await SqlAlchemyPoolSizing(session, FrozenClock(), max_age).read(*pool)


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


async def test_a_synced_pool_answers_its_minimum_and_its_total(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """Minimum 5, total 1000, available 400: the TOTAL, not the available."""
    await _snapshot(pg_session_factory, BYBIT, total="1000", available="400")

    sizing = await _read(pg_session_factory, BYBIT)

    assert sizing is not None
    assert sizing.min_order_size == Decimal("5")
    assert sizing.snapshot == SizingSnapshot(
        total=Decimal("1000"), observed_at=NOW - timedelta(seconds=1), stale=False
    )


async def test_a_pool_never_synced_answers_its_minimum_and_no_snapshot(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    sizing = await _read(pg_session_factory, BYBIT)

    assert sizing == PoolSizing(min_order_size=Decimal("5"), snapshot=None)


@pytest.mark.parametrize(
    ("age_seconds", "stale"), [(89, False), (90, False), (91, True)]
)
async def test_a_snapshot_is_stale_by_the_allocators_own_age_limit(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    age_seconds: int,
    stale: bool,
) -> None:
    """The rule ``SqlAlchemyPoolOverview`` applies, strictly: 91 s old is stale and
    exactly 90 s is not. The limit is a constructor argument, as there."""
    await _snapshot(
        pg_session_factory,
        BYBIT,
        total="1000",
        available="400",
        age=timedelta(seconds=age_seconds),
    )

    sizing = await _read(pg_session_factory, BYBIT, max_age=90.0)

    assert sizing is not None
    assert sizing.snapshot is not None
    assert sizing.snapshot.stale is stale


async def test_two_pools_are_each_read_for_their_own_key(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    await _add_pool(pg_session_factory, BINANCE, "7.5")
    await _snapshot(pg_session_factory, BYBIT, total="1000", available="400")
    await _snapshot(pg_session_factory, BINANCE, total="250.5", available="250.5")

    bybit = await _read(pg_session_factory, BYBIT)
    binance = await _read(pg_session_factory, BINANCE)

    assert bybit is not None
    assert binance is not None
    assert (bybit.min_order_size, bybit.snapshot and bybit.snapshot.total) == (
        Decimal("5"),
        Decimal("1000"),
    )
    assert (binance.min_order_size, binance.snapshot and binance.snapshot.total) == (
        Decimal("7.5"),
        Decimal("250.5"),
    )


async def test_a_pool_with_no_row_answers_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """``binance/usdt-m/USDT`` is not among the seeded pools. The port answers
    ``None``; the use case turns that into the module's invariant error."""
    assert await _read(pg_session_factory, BINANCE) is None


async def test_the_adapter_issues_one_select(
    pg_engine: AsyncEngine,  # noqa: F811
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    await _snapshot(pg_session_factory, BYBIT, total="1000", available="400")

    with _captured_sql(pg_engine) as statements:
        await _read(pg_session_factory, BYBIT)

    assert len(statements) == 1
    assert statements[0].lstrip().upper().startswith("SELECT")
