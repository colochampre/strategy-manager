"""``SqlAlchemyReservationRepository`` scoped by user (multi-user design AD2 and
AD8; tasks.md B.3, B.5, B.9).

Every scoped method is exercised with a SECOND user's reservation on the SAME
market, and for the strategy-level reads on the same strategy too, so the
market and strategy filters alone would still match it: only the user filter
keeps it out. The database's own refusal of a reservation in another user's
pool (the composite FK of migration ``0030``) is pinned here as well.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from tests.allocation.infrastructure.conftest import seed_signal, seed_strategy
from tests.owner import (
    OWNER_ID,
    ensure_delivery,
    ensure_pool,
    seed_other_user,
    seed_pool,
    seed_reservation_row,
)

pytestmark = pytest.mark.integration

MARKET = ("pionex", "spot", "USDT")
NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=UTC)


async def _other_user_with_a_pool(factory: async_sessionmaker[AsyncSession]) -> UUID:
    """A second user holding a pool on ``MARKET``, the owner's market too."""
    async with factory() as session:
        other = await seed_other_user(session)
        await seed_pool(session, MARKET, user_id=other)
        await session.commit()
    return other


async def _strategy(factory: async_sessionmaker[AsyncSession]) -> UUID:
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    return strategy_id


async def _reservation(
    factory: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    strategy_id: UUID,
    amount: Decimal = Decimal("100"),
    status: str = "PENDING",
    expires_at: datetime = NOW + timedelta(minutes=5),
    mode: str = "LIVE",
) -> tuple[UUID, UUID]:
    """One reservation of ``user_id`` on ``MARKET`` for ``strategy_id``, with a
    signal of its own. Returns ``(reservation_id, signal_id)``."""
    reservation_id, signal_id = uuid4(), uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    async with factory() as session:
        await seed_reservation_row(
            session,
            reservation_id=reservation_id,
            strategy_id=strategy_id,
            signal_id=signal_id,
            market=MARKET,
            amount=amount,
            status=status,
            expires_at=expires_at,
            user_id=user_id,
            mode=mode,
        )
        await session.commit()
    return reservation_id, signal_id


async def _row(factory: async_sessionmaker[AsyncSession], reservation_id: UUID) -> ReservationRow:
    async with factory() as session:
        return (
            await session.execute(select(ReservationRow).where(ReservationRow.id == reservation_id))
        ).scalar_one()


async def test_find_by_signal_id_never_returns_another_users_reservation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _other_user_with_a_pool(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory)
    reservation_id, signal_id = await _reservation(
        pg_session_factory, user_id=other, strategy_id=strategy_id
    )

    async with pg_session_factory() as session:
        repository = SqlAlchemyReservationRepository(session)
        mine = await repository.find_by_signal_id(OWNER_ID, signal_id)
        theirs = await repository.find_by_signal_id(other, signal_id)

    assert mine is None
    assert theirs is not None and theirs.id == reservation_id


async def test_get_for_update_never_locks_another_users_reservation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _other_user_with_a_pool(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory)
    reservation_id, _ = await _reservation(
        pg_session_factory, user_id=other, strategy_id=strategy_id
    )

    async with pg_session_factory() as session:
        repository = SqlAlchemyReservationRepository(session)
        with pytest.raises(NoResultFound):
            await repository.get_for_update(OWNER_ID, reservation_id)
        await session.rollback()
        assert (await repository.get_for_update(other, reservation_id)).id == reservation_id


async def test_sum_active_counts_only_the_users_own_reservations(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _other_user_with_a_pool(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory)
    await _reservation(
        pg_session_factory, user_id=OWNER_ID, strategy_id=strategy_id, amount=Decimal("100")
    )
    await _reservation(
        pg_session_factory, user_id=other, strategy_id=strategy_id, amount=Decimal("250")
    )

    async with pg_session_factory() as session:
        repository = SqlAlchemyReservationRepository(session)
        mine = await repository.sum_active(OWNER_ID, *MARKET, Mode.LIVE, NOW)
        theirs = await repository.sum_active(other, *MARKET, Mode.LIVE, NOW)

    assert mine == Decimal("100")
    assert theirs == Decimal("250")


async def test_sum_active_counts_only_reservations_of_the_asked_mode(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Decision 26: a simulated reservation holds no real capital and a real one
    no simulated capital, for the same user on the same market. A second user's
    reservation of either mode stays out as well."""
    other = await _other_user_with_a_pool(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory)
    for user_id, amount, mode in (
        (OWNER_ID, "100", "LIVE"),
        (OWNER_ID, "30", "SIMULATION"),
        (other, "250", "LIVE"),
        (other, "7", "SIMULATION"),
    ):
        await _reservation(
            pg_session_factory,
            user_id=user_id,
            strategy_id=strategy_id,
            amount=Decimal(amount),
            mode=mode,
        )

    async with pg_session_factory() as session:
        repository = SqlAlchemyReservationRepository(session)
        owner_live = await repository.sum_active(OWNER_ID, *MARKET, Mode.LIVE, NOW)
        owner_simulation = await repository.sum_active(OWNER_ID, *MARKET, Mode.SIMULATION, NOW)
        other_simulation = await repository.sum_active(other, *MARKET, Mode.SIMULATION, NOW)

    assert owner_live == Decimal("100")
    assert owner_simulation == Decimal("30")
    assert other_simulation == Decimal("7")


async def test_insert_writes_the_reservations_mode(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    signal_id = uuid4()
    await seed_signal(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    async with pg_session_factory() as session:
        await ensure_pool(session, MARKET, user_id=OWNER_ID)
        delivery_id = await ensure_delivery(session, signal_id=signal_id, strategy_id=strategy_id)
        await session.commit()
    reservation = Reservation(
        id=uuid4(),
        strategy_id=strategy_id,
        signal_id=signal_id,
        delivery_id=delivery_id,
        pool_key=PoolKey(
            exchange=Exchange.PIONEX, venue=Venue.SPOT, settlement_currency=Currency.USDT
        ),
        amount=Decimal("100"),
        status=ReservationStatus.PENDING,
        mode=Mode.SIMULATION,
        expires_at=NOW + timedelta(minutes=5),
    )

    async with pg_session_factory() as session:
        await SqlAlchemyReservationRepository(session).insert(OWNER_ID, reservation)
        await session.commit()

    assert (await _row(pg_session_factory, reservation.id)).mode == "SIMULATION"
    async with pg_session_factory() as session:
        found = await SqlAlchemyReservationRepository(session).find_by_signal_id(
            OWNER_ID, signal_id
        )
    assert found is not None and found.mode is Mode.SIMULATION


async def test_insert_writes_the_user_and_that_users_pool_on_the_market(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Both users hold a pool on the market: the reservation lands in the
    inserting user's, never in the other one."""
    other = await _other_user_with_a_pool(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory)
    signal_id = uuid4()
    await seed_signal(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    async with pg_session_factory() as session:
        other_pool = await ensure_pool(session, MARKET, user_id=other)
        owner_pool = await ensure_pool(session, MARKET, user_id=OWNER_ID)
        delivery_id = await ensure_delivery(
            session, signal_id=signal_id, strategy_id=strategy_id, user_id=other
        )
        await session.commit()
    reservation = Reservation(
        id=uuid4(),
        strategy_id=strategy_id,
        signal_id=signal_id,
        delivery_id=delivery_id,
        pool_key=PoolKey(
            exchange=Exchange.PIONEX, venue=Venue.SPOT, settlement_currency=Currency.USDT
        ),
        amount=Decimal("100"),
        status=ReservationStatus.PENDING,
        mode=Mode.LIVE,
        expires_at=NOW + timedelta(minutes=5),
    )

    async with pg_session_factory() as session:
        await SqlAlchemyReservationRepository(session).insert(other, reservation)
        await session.commit()

    row = await _row(pg_session_factory, reservation.id)
    assert other_pool != owner_pool
    assert (row.user_id, row.pool_id) == (other, other_pool)
    assert row.delivery_id == delivery_id


async def test_insert_refuses_a_reservation_that_names_no_delivery(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Every reservation serves one delivery (migration 0032): refused before any
    write, naming the reservation, rather than left to the database's NOT NULL."""
    strategy_id = await _strategy(pg_session_factory)
    signal_id = uuid4()
    await seed_signal(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    reservation = Reservation(
        id=uuid4(),
        strategy_id=strategy_id,
        signal_id=signal_id,
        pool_key=PoolKey(
            exchange=Exchange.PIONEX, venue=Venue.SPOT, settlement_currency=Currency.USDT
        ),
        amount=Decimal("100"),
        status=ReservationStatus.PENDING,
        mode=Mode.LIVE,
        expires_at=NOW + timedelta(minutes=5),
    )

    async with pg_session_factory() as session:
        with pytest.raises(InvariantViolation, match=str(reservation.id)):
            await SqlAlchemyReservationRepository(session).insert(OWNER_ID, reservation)


async def test_insert_refuses_a_market_the_user_holds_no_pool_on(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Another user's pool on that market is no substitute."""
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    strategy_id = await _strategy(pg_session_factory)
    signal_id = uuid4()
    await seed_signal(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    reservation = Reservation(
        id=uuid4(),
        strategy_id=strategy_id,
        signal_id=signal_id,
        # Never written: the repository refuses on the pool first.
        delivery_id=uuid4(),
        pool_key=PoolKey(
            exchange=Exchange.PIONEX, venue=Venue.SPOT, settlement_currency=Currency.USDT
        ),
        amount=Decimal("100"),
        status=ReservationStatus.PENDING,
        mode=Mode.LIVE,
        expires_at=NOW + timedelta(minutes=5),
    )

    async with pg_session_factory() as session:
        with pytest.raises(InvariantViolation, match=str(other)[:8]):
            await SqlAlchemyReservationRepository(session).insert(other, reservation)


async def test_a_reservation_cannot_reference_another_users_pool(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The composite FK of migration 0030 refuses it, whatever the code does."""
    other = await _other_user_with_a_pool(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory)
    signal_id = uuid4()
    await seed_signal(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    async with pg_session_factory() as session:
        owner_pool = await ensure_pool(session, MARKET, user_id=OWNER_ID)
        delivery_id = await ensure_delivery(
            session, signal_id=signal_id, strategy_id=strategy_id, user_id=other
        )
        session.add(
            ReservationRow(
                id=uuid4(),
                user_id=other,
                pool_id=owner_pool,
                strategy_id=strategy_id,
                signal_id=signal_id,
                delivery_id=delivery_id,
                exchange=MARKET[0],
                venue=MARKET[1],
                settlement_currency=MARKET[2],
                amount=Decimal("100"),
                status="PENDING",
                mode="LIVE",
                expires_at=NOW + timedelta(minutes=5),
            )
        )
        with pytest.raises(IntegrityError, match="fk_reservations_capital_pool"):
            await session.flush()


async def test_mark_never_changes_another_users_reservation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _other_user_with_a_pool(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory)
    reservation_id, _ = await _reservation(
        pg_session_factory, user_id=other, strategy_id=strategy_id
    )

    async with pg_session_factory() as session:
        with pytest.raises(InvariantViolation, match=str(reservation_id)):
            await SqlAlchemyReservationRepository(session).mark(
                OWNER_ID, reservation_id, ReservationStatus.SUBMITTED, NOW
            )
        await session.commit()

    assert (await _row(pg_session_factory, reservation_id)).status == "PENDING"


async def test_mark_changes_the_users_own_reservation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _other_user_with_a_pool(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory)
    reservation_id, _ = await _reservation(
        pg_session_factory, user_id=other, strategy_id=strategy_id
    )

    async with pg_session_factory() as session:
        await SqlAlchemyReservationRepository(session).mark(
            other, reservation_id, ReservationStatus.SUBMITTED, NOW
        )
        await session.commit()

    assert (await _row(pg_session_factory, reservation_id)).status == "SUBMITTED"


async def test_has_pending_for_strategy_ignores_another_users_reservation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Same strategy, same market: only the user filter keeps it out."""
    other = await _other_user_with_a_pool(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory)
    await _reservation(pg_session_factory, user_id=other, strategy_id=strategy_id)

    async with pg_session_factory() as session:
        repository = SqlAlchemyReservationRepository(session)
        mine = await repository.has_pending_for_strategy(OWNER_ID, *MARKET, strategy_id, NOW)
        theirs = await repository.has_pending_for_strategy(other, *MARKET, strategy_id, NOW)

    assert mine is False
    assert theirs is True


async def test_live_for_pool_lists_only_the_users_own_reservations(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _other_user_with_a_pool(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory)
    mine_id, _ = await _reservation(pg_session_factory, user_id=OWNER_ID, strategy_id=strategy_id)
    theirs_id, _ = await _reservation(pg_session_factory, user_id=other, strategy_id=strategy_id)

    async with pg_session_factory() as session:
        repository = SqlAlchemyReservationRepository(session)
        mine = await repository.live_for_pool(OWNER_ID, *MARKET)
        theirs = await repository.live_for_pool(other, *MARKET)

    assert mine == [mine_id]
    assert theirs == [theirs_id]


async def test_expire_due_stays_global_and_sweeps_every_users_reservation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The worker's sweep has no user context: expiry is the row's own."""
    other = await _other_user_with_a_pool(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory)
    past = NOW - timedelta(seconds=1)
    mine_id, _ = await _reservation(
        pg_session_factory, user_id=OWNER_ID, strategy_id=strategy_id, expires_at=past
    )
    theirs_id, _ = await _reservation(
        pg_session_factory, user_id=other, strategy_id=strategy_id, expires_at=past
    )

    async with pg_session_factory() as session:
        expired = await SqlAlchemyReservationRepository(session).expire_due(NOW, limit=10)
        await session.commit()

    assert expired == 2
    assert (await _row(pg_session_factory, mine_id)).status == "EXPIRED"
    assert (await _row(pg_session_factory, theirs_id)).status == "EXPIRED"
