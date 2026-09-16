"""Integration: ``pool_balance_snapshots`` round-trip against real PostgreSQL.

Covers the write (upsert), the read (``DbBalanceSource``) and the constraints
that keep the table honest. The staleness tests are the important ones: they
are the difference between halting and trading against a balance that no
longer exists.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.ports import PoolBalanceReading
from strategy_manager.accounts.domain.errors import StaleBalanceSnapshot
from strategy_manager.accounts.infrastructure.balance_snapshot_repository import (
    SqlAlchemyBalanceSnapshotRepository,
)
from strategy_manager.accounts.infrastructure.db_balance_source import DbBalanceSource
from strategy_manager.accounts.infrastructure.models import PoolBalanceSnapshotRow

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
MAX_AGE = 90.0
SPOT = ("pionex", "spot", "USDT")


class FrozenClock:
    def __init__(self, at: datetime = NOW) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


def _reading(
    pool: tuple[str, str, str],
    available: str,
    observed_at: datetime = NOW,
    total: str | None = None,
) -> PoolBalanceReading:
    exchange, venue, currency = pool
    return PoolBalanceReading(
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        total=Decimal(available if total is None else total),
        available=Decimal(available),
        observed_at=observed_at,
    )


def _source(session: AsyncSession, clock: FrozenClock) -> DbBalanceSource:
    return DbBalanceSource(session, clock, max_age_seconds=MAX_AGE)


async def test_a_written_snapshot_reads_back_exactly(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The 26-decimal precision the live API returns must survive the round
    trip up to the column's own scale."""
    async with pg_session_factory() as session:
        await SqlAlchemyBalanceSnapshotRepository(session).upsert(
            [_reading(SPOT, "600.529840783767852939")]
        )
        await session.commit()

        funds = await _source(session, FrozenClock()).read_balance(*SPOT)

    assert funds.available == Decimal("600.529840783767852939")


async def test_total_and_availability_round_trip_separately(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A futures pool with open positions holds more than it can still grant.
    Reading one figure back as the other is how sizing starts compounding."""
    async with pg_session_factory() as session:
        await SqlAlchemyBalanceSnapshotRepository(session).upsert(
            [_reading(("bybit", "usdt-m", "USDT"), "400", total="1000")]
        )
        await session.commit()

        funds = await _source(session, FrozenClock()).read_balance("bybit", "usdt-m", "USDT")

    assert (funds.total, funds.available) == (Decimal("1000"), Decimal("400"))


async def test_availability_above_the_total_is_rejected_by_the_database(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Availability is the total minus what is committed. A row claiming more
    free capital than the pool holds was mapped from the wrong fields."""
    async with pg_session_factory() as session:
        with pytest.raises(IntegrityError):
            await SqlAlchemyBalanceSnapshotRepository(session).upsert(
                [_reading(SPOT, "600", total="500")]
            )
            await session.commit()


async def test_a_second_sync_overwrites_rather_than_appends(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        repository = SqlAlchemyBalanceSnapshotRepository(session)
        await repository.upsert([_reading(SPOT, "100")])
        await repository.upsert([_reading(SPOT, "250")])
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(PoolBalanceSnapshotRow).where(PoolBalanceSnapshotRow.venue == "spot")
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    assert rows[0].available == Decimal("250")


async def test_a_batch_covering_several_pools_lands_in_one_statement(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        await SqlAlchemyBalanceSnapshotRepository(session).upsert(
            [_reading(SPOT, "100"), _reading(("bybit", "usdt-m", "USDT"), "50")]
        )
        await session.commit()

        rows = (await session.execute(select(PoolBalanceSnapshotRow))).scalars().all()

    assert len(rows) == 2


async def test_a_snapshot_past_the_age_limit_refuses_to_answer(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The sync job died two minutes ago. Sizing a trade against this figure
    is exactly the failure the whole snapshot design exists to prevent."""
    async with pg_session_factory() as session:
        await SqlAlchemyBalanceSnapshotRepository(session).upsert([_reading(SPOT, "600")])
        await session.commit()

        much_later = FrozenClock(NOW + timedelta(seconds=MAX_AGE + 1))

        with pytest.raises(StaleBalanceSnapshot, match="refusing to size a trade"):
            await _source(session, much_later).read_balance(*SPOT)


async def test_a_snapshot_inside_the_age_limit_still_answers(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A couple of transient API failures must not halt trading — that is why
    the limit is several sync intervals wide."""
    async with pg_session_factory() as session:
        await SqlAlchemyBalanceSnapshotRepository(session).upsert([_reading(SPOT, "600")])
        await session.commit()

        just_inside = FrozenClock(NOW + timedelta(seconds=MAX_AGE - 1))

        funds = await _source(session, just_inside).read_balance(*SPOT)

    assert funds.available == Decimal("600")


async def test_a_pool_that_was_never_synced_refuses_to_answer(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A missing row is not a zero balance. Returning zero would silently
    convert 'we never asked' into 'there is no money', which reads as a
    healthy skip instead of a broken sync."""
    async with pg_session_factory() as session:
        with pytest.raises(StaleBalanceSnapshot, match="has ever been synced"):
            await _source(session, FrozenClock()).read_balance(*SPOT)


async def test_a_snapshot_for_an_unconfigured_pool_is_rejected(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """capital_pools stays the single source of truth for which pools exist."""
    async with pg_session_factory() as session:
        with pytest.raises(IntegrityError):
            await SqlAlchemyBalanceSnapshotRepository(session).upsert(
                [_reading(("pionex", "spot", "DOGE"), "1")]
            )
            await session.commit()


async def test_a_negative_balance_is_rejected_by_the_database(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        with pytest.raises(IntegrityError):
            await SqlAlchemyBalanceSnapshotRepository(session).upsert([_reading(SPOT, "-1")])
            await session.commit()


async def test_an_empty_batch_is_a_no_op(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        await SqlAlchemyBalanceSnapshotRepository(session).upsert([])
        await session.commit()

        rows = (await session.execute(select(PoolBalanceSnapshotRow))).scalars().all()

    assert rows == []
