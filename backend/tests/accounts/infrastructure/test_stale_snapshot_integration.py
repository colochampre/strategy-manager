"""``SqlAlchemyStaleSnapshotReader`` — the watchdog's first condition, in SQL.

An outer join is the behaviour here, not an implementation detail. The pool
that matters most is the one with NO row in ``pool_balance_snapshots`` at all,
and an inner join answers that case by returning nothing — which reads exactly
like health. ``balance.sync`` writing nothing for a pool and ``balance.sync``
never having run for it are the same outage seen at two different ages, so both
have to come back from one query.

Enablement is the other half. ``capital_pools`` is the source of truth for
which pools exist, and a disabled one is money this system was told to ignore:
alerting on its snapshot would train the operator to ignore the alert.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.infrastructure.stale_snapshot_reader import (
    SqlAlchemyStaleSnapshotReader,
)
from strategy_manager.shared.application.watchdog import StalePool

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
MAX_AGE = 600.0

BYBIT = ("bybit", "usdt-m", "USDT")
SPOT = ("pionex", "spot", "USDT")


class FrozenClock:
    def now(self) -> datetime:
        return NOW


async def _write_snapshot(
    factory: async_sessionmaker[AsyncSession],
    pool: tuple[str, str, str],
    observed_at: datetime,
) -> None:
    exchange, venue, currency = pool
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO pool_balance_snapshots "
                "(exchange, venue, settlement_currency, total, available, observed_at) "
                "VALUES (:exchange, :venue, :currency, :total, :available, :observed_at)"
            ),
            {
                "exchange": exchange,
                "venue": venue,
                "currency": currency,
                "total": Decimal("100"),
                "available": Decimal("100"),
                "observed_at": observed_at,
            },
        )
        await session.commit()


async def _disable(
    factory: async_sessionmaker[AsyncSession], pool: tuple[str, str, str]
) -> None:
    exchange, venue, currency = pool
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE capital_pools SET enabled = false WHERE exchange = :exchange "
                "AND venue = :venue AND settlement_currency = :currency"
            ),
            {"exchange": exchange, "venue": venue, "currency": currency},
        )
        await session.commit()


async def _stale(
    factory: async_sessionmaker[AsyncSession], max_age_seconds: float = MAX_AGE
) -> list[StalePool]:
    async with factory() as session:
        reader = SqlAlchemyStaleSnapshotReader(session, FrozenClock())
        return list(await reader.stale_pools(max_age_seconds))


def _keys(pools: list[StalePool]) -> set[tuple[str, str, str]]:
    return {
        (pool.exchange, pool.venue, pool.settlement_currency) for pool in pools
    }


async def test_a_pool_that_has_never_synced_is_reported_with_no_age(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The case an inner join answers with silence."""
    stale = await _stale(pg_session_factory)

    assert BYBIT in _keys(stale)
    never = next(pool for pool in stale if pool.exchange == "bybit")
    assert never.age_seconds is None


async def test_a_fresh_snapshot_takes_its_pool_off_the_list(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _write_snapshot(pg_session_factory, BYBIT, NOW - timedelta(seconds=30))

    assert BYBIT not in _keys(await _stale(pg_session_factory))


async def test_a_snapshot_past_the_bound_is_reported_with_its_age(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The age is what separates "a sync was missed" from "the chain is
    dead", so the message has to carry it rather than just the pool."""
    await _write_snapshot(
        pg_session_factory, BYBIT, NOW - timedelta(seconds=MAX_AGE + 60)
    )

    stale = await _stale(pg_session_factory)
    reported = next(pool for pool in stale if pool.exchange == "bybit")

    assert reported.age_seconds == pytest.approx(MAX_AGE + 60)


async def test_a_snapshot_exactly_at_the_bound_is_still_fresh(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The bound is a ceiling on acceptable age, not the first age that is
    unacceptable. One sync landing on the boundary is not an incident."""
    await _write_snapshot(
        pg_session_factory, BYBIT, NOW - timedelta(seconds=MAX_AGE)
    )

    assert BYBIT not in _keys(await _stale(pg_session_factory))


async def test_a_disabled_pool_is_never_reported(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _disable(pg_session_factory, SPOT)

    assert SPOT not in _keys(await _stale(pg_session_factory))


async def test_one_stale_pool_does_not_hide_behind_a_fresh_one(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _write_snapshot(pg_session_factory, SPOT, NOW - timedelta(seconds=10))
    await _write_snapshot(
        pg_session_factory, BYBIT, NOW - timedelta(seconds=MAX_AGE + 1)
    )

    keys = _keys(await _stale(pg_session_factory))

    assert BYBIT in keys
    assert SPOT not in keys
