"""Integration: ``pool_balance_snapshots`` round-trip against real PostgreSQL.

Covers the write (upsert), the read (``DbBalanceSource``) and the constraints
that keep the table honest. The staleness tests are the important ones: they
are the difference between halting and trading against a balance that no
longer exists.

Every seeded pool is the owner's (``tests.owner``). A snapshot belongs to one
user's pool (migration ``0030``), so the cross-user tests at the end put a second
user's pool on the SAME market beside the owner's and prove that neither the
write nor either read ever crosses from one to the other (multi-user design AD8).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.ports import PoolBalanceReading
from strategy_manager.accounts.domain.errors import StaleBalanceSnapshot
from strategy_manager.accounts.infrastructure.balance_snapshot_repository import (
    SqlAlchemyBalanceSnapshotRepository,
)
from strategy_manager.accounts.infrastructure.db_balance_source import (
    DbBalanceSnapshotAge,
    DbBalanceSource,
)
from strategy_manager.accounts.infrastructure.models import PoolBalanceSnapshotRow
from strategy_manager.shared.domain.errors import InvariantViolation
from tests.owner import OWNER_ID, seed_other_user, seed_pool, seed_snapshot

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
            OWNER_ID, [_reading(SPOT, "600.529840783767852939")]
        )
        await session.commit()

        funds = await _source(session, FrozenClock()).read_balance(OWNER_ID, *SPOT)

    assert funds.available == Decimal("600.529840783767852939")


async def test_total_and_availability_round_trip_separately(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A futures pool with open positions holds more than it can still grant.
    Reading one figure back as the other is how sizing starts compounding."""
    async with pg_session_factory() as session:
        await SqlAlchemyBalanceSnapshotRepository(session).upsert(
            OWNER_ID, [_reading(("bybit", "usdt-m", "USDT"), "400", total="1000")]
        )
        await session.commit()

        funds = await _source(session, FrozenClock()).read_balance(
            OWNER_ID, "bybit", "usdt-m", "USDT"
        )

    assert (funds.total, funds.available) == (Decimal("1000"), Decimal("400"))


async def test_availability_above_the_total_is_rejected_by_the_database(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Availability is the total minus what is committed. A row claiming more
    free capital than the pool holds was mapped from the wrong fields."""
    async with pg_session_factory() as session:
        with pytest.raises(IntegrityError):
            await SqlAlchemyBalanceSnapshotRepository(session).upsert(
                OWNER_ID, [_reading(SPOT, "600", total="500")]
            )
            await session.commit()


async def test_a_second_sync_overwrites_rather_than_appends(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        repository = SqlAlchemyBalanceSnapshotRepository(session)
        await repository.upsert(OWNER_ID, [_reading(SPOT, "100")])
        await repository.upsert(OWNER_ID, [_reading(SPOT, "250")])
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
            OWNER_ID, [_reading(SPOT, "100"), _reading(("bybit", "usdt-m", "USDT"), "50")]
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
        await SqlAlchemyBalanceSnapshotRepository(session).upsert(
            OWNER_ID, [_reading(SPOT, "600")]
        )
        await session.commit()

        much_later = FrozenClock(NOW + timedelta(seconds=MAX_AGE + 1))

        with pytest.raises(StaleBalanceSnapshot, match="refusing to size a trade"):
            await _source(session, much_later).read_balance(OWNER_ID, *SPOT)


async def test_a_snapshot_inside_the_age_limit_still_answers(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A couple of transient API failures must not halt trading — that is why
    the limit is several sync intervals wide."""
    async with pg_session_factory() as session:
        await SqlAlchemyBalanceSnapshotRepository(session).upsert(
            OWNER_ID, [_reading(SPOT, "600")]
        )
        await session.commit()

        just_inside = FrozenClock(NOW + timedelta(seconds=MAX_AGE - 1))

        funds = await _source(session, just_inside).read_balance(OWNER_ID, *SPOT)

    assert funds.available == Decimal("600")


async def test_a_pool_that_was_never_synced_refuses_to_answer(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A missing row is not a zero balance. Returning zero would silently
    convert 'we never asked' into 'there is no money', which reads as a
    healthy skip instead of a broken sync."""
    async with pg_session_factory() as session:
        with pytest.raises(StaleBalanceSnapshot, match="has ever been synced"):
            await _source(session, FrozenClock()).read_balance(OWNER_ID, *SPOT)


async def test_a_snapshot_for_an_unconfigured_pool_is_rejected(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """capital_pools stays the single source of truth for which pools exist.
    Since 0030 the repository refuses it itself, by looking the pool up, before
    the database is asked to write anything."""
    async with pg_session_factory() as session:
        with pytest.raises(InvariantViolation, match="has no pool on"):
            await SqlAlchemyBalanceSnapshotRepository(session).upsert(
                OWNER_ID, [_reading(("pionex", "spot", "DOGE"), "1")]
            )
            await session.commit()


async def test_a_negative_balance_is_rejected_by_the_database(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        with pytest.raises(IntegrityError):
            await SqlAlchemyBalanceSnapshotRepository(session).upsert(
                OWNER_ID, [_reading(SPOT, "-1")]
            )
            await session.commit()


async def test_an_empty_batch_is_a_no_op(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        await SqlAlchemyBalanceSnapshotRepository(session).upsert(OWNER_ID, [])
        await session.commit()

        rows = (await session.execute(select(PoolBalanceSnapshotRow))).scalars().all()

    assert rows == []


# --- DbBalanceSnapshotAge: the age RefreshPoolBalance reads on failure -------
#
# Deliberately answers WITHOUT the freshness refusal DbBalanceSource applies:
# RefreshPoolBalance needs the raw age to decide FALLBACK vs UNAVAILABLE, not
# an exception.


async def test_age_seconds_reports_how_old_a_real_snapshot_is(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        await SqlAlchemyBalanceSnapshotRepository(session).upsert(
            OWNER_ID, [_reading(SPOT, "600", observed_at=NOW)]
        )
        await session.commit()

        later = FrozenClock(NOW + timedelta(seconds=125))
        age = await DbBalanceSnapshotAge(session, later).age_seconds(OWNER_ID, *SPOT)

    assert age == 125.0


async def test_age_seconds_is_none_for_a_pool_that_was_never_synced(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        age = await DbBalanceSnapshotAge(session, FrozenClock()).age_seconds(OWNER_ID, *SPOT)

    assert age is None


async def test_age_seconds_never_refuses_even_when_the_snapshot_is_ancient(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The one behavioural difference from ``DbBalanceSource``: an age this old
    would make that class raise ``StaleBalanceSnapshot``. This one just reports
    the number -- ``RefreshPoolBalance`` is the one that decides what it means."""
    async with pg_session_factory() as session:
        await SqlAlchemyBalanceSnapshotRepository(session).upsert(
            OWNER_ID, [_reading(SPOT, "600", observed_at=NOW)]
        )
        await session.commit()

        much_later = FrozenClock(NOW + timedelta(hours=6))
        age = await DbBalanceSnapshotAge(session, much_later).age_seconds(OWNER_ID, *SPOT)

    assert age == timedelta(hours=6).total_seconds()


# --- Two users, one market (multi-user design AD8) ----------------------------
#
# The owner's spot pool exists (conftest). The second user's pool on the SAME
# market is created after it, so it has the higher id: a read or a lookup that
# forgets the user and takes "the" row for the market lands on it.


async def _second_user_with_spot_pool(factory: async_sessionmaker[AsyncSession]) -> UUID:
    async with factory() as session:
        other = await seed_other_user(session)
        await seed_pool(session, SPOT, user_id=other)
        await session.commit()
    return other


async def _snapshots(
    factory: async_sessionmaker[AsyncSession],
) -> dict[UUID, Decimal]:
    """Every spot snapshot, by its row's user."""
    async with factory() as session:
        rows = (
            await session.execute(
                select(PoolBalanceSnapshotRow.user_id, PoolBalanceSnapshotRow.available).where(
                    PoolBalanceSnapshotRow.venue == "spot"
                )
            )
        ).all()
    return {user_id: available for user_id, available in rows}


async def test_an_upsert_writes_only_its_own_users_snapshot(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _second_user_with_spot_pool(pg_session_factory)

    async with pg_session_factory() as session:
        await SqlAlchemyBalanceSnapshotRepository(session).upsert(
            OWNER_ID, [_reading(SPOT, "600")]
        )
        await session.commit()

    snapshots = await _snapshots(pg_session_factory)
    assert snapshots == {OWNER_ID: Decimal("600")}
    assert other not in snapshots


async def test_one_users_upsert_never_overwrites_the_other_users_snapshot(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _second_user_with_spot_pool(pg_session_factory)
    async with pg_session_factory() as session:
        await seed_snapshot(
            session,
            SPOT,
            user_id=other,
            total=Decimal("999"),
            available=Decimal("999"),
            observed_at=NOW,
        )
        await session.commit()

    async with pg_session_factory() as session:
        await SqlAlchemyBalanceSnapshotRepository(session).upsert(
            OWNER_ID, [_reading(SPOT, "600")]
        )
        await session.commit()

    assert await _snapshots(pg_session_factory) == {
        OWNER_ID: Decimal("600"),
        other: Decimal("999"),
    }


async def test_an_upsert_refuses_a_market_its_user_has_no_pool_on(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The owner holds a spot pool; the second user holds none. The second
    user's reading is refused, and nothing lands on the owner's pool."""
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()

    async with pg_session_factory() as session:
        with pytest.raises(InvariantViolation, match="has no pool on"):
            await SqlAlchemyBalanceSnapshotRepository(session).upsert(
                other, [_reading(SPOT, "777")]
            )
            await session.commit()

    assert await _snapshots(pg_session_factory) == {}


async def test_read_balance_reads_only_its_own_users_snapshot(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _second_user_with_spot_pool(pg_session_factory)
    async with pg_session_factory() as session:
        await seed_snapshot(
            session, SPOT, total=Decimal("600"), available=Decimal("600"), observed_at=NOW
        )
        await seed_snapshot(
            session,
            SPOT,
            user_id=other,
            total=Decimal("999"),
            available=Decimal("999"),
            observed_at=NOW,
        )
        await session.commit()

        funds = await _source(session, FrozenClock()).read_balance(OWNER_ID, *SPOT)

    assert (funds.total, funds.available) == (Decimal("600"), Decimal("600"))


async def test_read_balance_never_answers_with_another_users_snapshot(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The owner's pool was never synced; the second user's was, just now. The
    owner's read refuses: another user's balance is not this pool's money."""
    other = await _second_user_with_spot_pool(pg_session_factory)
    async with pg_session_factory() as session:
        await seed_snapshot(
            session,
            SPOT,
            user_id=other,
            total=Decimal("999"),
            available=Decimal("999"),
            observed_at=NOW,
        )
        await session.commit()

        with pytest.raises(StaleBalanceSnapshot, match="has ever been synced"):
            await _source(session, FrozenClock()).read_balance(OWNER_ID, *SPOT)


async def test_age_seconds_never_reports_another_users_snapshot(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _second_user_with_spot_pool(pg_session_factory)
    async with pg_session_factory() as session:
        await seed_snapshot(
            session,
            SPOT,
            user_id=other,
            total=Decimal("999"),
            available=Decimal("999"),
            observed_at=NOW,
        )
        await session.commit()

        age = await DbBalanceSnapshotAge(
            session, FrozenClock(NOW + timedelta(seconds=30))
        ).age_seconds(OWNER_ID, *SPOT)

    assert age is None
