"""``SqlAlchemyProtectiveStopRepository`` against a real PostgreSQL database
(subscriber-safety SS.5): one row per opening attempt, written and marked as the user whose
attempt it is, with the venue id kept across a later mark.
"""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.domain.protective_stop import (
    PositionSide,
    ProtectiveStop,
    StopStatus,
)
from strategy_manager.execution.infrastructure.models import ProtectiveStopRow
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyProtectiveStopRepository,
)
from tests.execution.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)
from tests.owner import OWNER_ID, seed_other_user

pytestmark = pytest.mark.integration


async def _opening(
    factory: async_sessionmaker[AsyncSession], user_id: UUID = OWNER_ID
) -> tuple[UUID, UUID]:
    """A reservation of ``user_id`` and the opening attempt that spent it:
    ``(allocation_id, attempt_id)``."""
    strategy_id, signal_id, allocation_id, attempt_id = uuid4(), uuid4(), uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id, author_id=user_id)
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    await seed_reservation(
        factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        user_id=user_id,
    )
    await seed_execution_attempt(factory, attempt_id=attempt_id, reservation_id=allocation_id)
    return allocation_id, attempt_id


def _stop(
    allocation_id: UUID,
    attempt_id: UUID,
    *,
    status: StopStatus = StopStatus.PENDING,
    trigger: Decimal | None = Decimal("0.059706"),
) -> ProtectiveStop:
    return ProtectiveStop(
        id=uuid4(),
        execution_attempt_id=attempt_id,
        allocation_id=allocation_id,
        exchange="bybit",
        venue="usdt-m",
        symbol="DOGEUSDT.P",
        position_side=PositionSide.LONG,
        stop_loss_pct=Decimal("7.50"),
        trigger_price=trigger,
        status=status,
    )


async def test_a_stop_is_written_and_read_back_as_it_was(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation_id, attempt_id = await _opening(pg_session_factory)
    written = _stop(allocation_id, attempt_id)

    async with pg_session_factory() as session:
        repository = SqlAlchemyProtectiveStopRepository(session)
        await repository.insert(OWNER_ID, written)
        await session.commit()

    async with pg_session_factory() as session:
        read = await SqlAlchemyProtectiveStopRepository(session).for_attempt(
            OWNER_ID, attempt_id
        )

    assert read == written


async def test_a_simulated_stop_with_no_trigger_price_round_trips(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation_id, attempt_id = await _opening(pg_session_factory)
    written = _stop(allocation_id, attempt_id, status=StopStatus.SIMULATED, trigger=None)

    async with pg_session_factory() as session:
        await SqlAlchemyProtectiveStopRepository(session).insert(OWNER_ID, written)
        await session.commit()

    async with pg_session_factory() as session:
        read = await SqlAlchemyProtectiveStopRepository(session).for_attempt(
            OWNER_ID, attempt_id
        )

    assert read == written


async def test_an_attempt_with_no_stop_reads_none(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, attempt_id = await _opening(pg_session_factory)

    async with pg_session_factory() as session:
        assert (
            await SqlAlchemyProtectiveStopRepository(session).for_attempt(OWNER_ID, attempt_id)
            is None
        )


async def test_the_stop_is_written_with_the_flush_the_next_write_depends_on(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Not committed, yet visible to the same transaction: the confirm job's row
    lock and ``mark`` read it before anything is committed."""
    allocation_id, attempt_id = await _opening(pg_session_factory)

    async with pg_session_factory() as session:
        repository = SqlAlchemyProtectiveStopRepository(session)
        await repository.insert(OWNER_ID, _stop(allocation_id, attempt_id))

        assert await repository.for_attempt(OWNER_ID, attempt_id) is not None


async def test_an_attempt_has_at_most_one_stop(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation_id, attempt_id = await _opening(pg_session_factory)
    async with pg_session_factory() as session:
        repository = SqlAlchemyProtectiveStopRepository(session)
        await repository.insert(OWNER_ID, _stop(allocation_id, attempt_id))
        await session.commit()

    async with pg_session_factory() as session:
        with pytest.raises(IntegrityError):
            await SqlAlchemyProtectiveStopRepository(session).insert(
                OWNER_ID, _stop(allocation_id, attempt_id)
            )


async def test_a_mark_moves_the_status_and_records_the_venue_id(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation_id, attempt_id = await _opening(pg_session_factory)
    async with pg_session_factory() as session:
        repository = SqlAlchemyProtectiveStopRepository(session)
        await repository.insert(OWNER_ID, _stop(allocation_id, attempt_id))
        await repository.mark(OWNER_ID, attempt_id, StopStatus.RESTING, venue_stop_id="STOP-1")
        await session.commit()

    async with pg_session_factory() as session:
        read = await SqlAlchemyProtectiveStopRepository(session).for_attempt(
            OWNER_ID, attempt_id
        )

    assert read is not None
    assert (read.status, read.venue_stop_id) == (StopStatus.RESTING, "STOP-1")


async def test_a_later_mark_keeps_the_venue_id_it_was_found_under(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation_id, attempt_id = await _opening(pg_session_factory)
    async with pg_session_factory() as session:
        repository = SqlAlchemyProtectiveStopRepository(session)
        await repository.insert(OWNER_ID, _stop(allocation_id, attempt_id))
        await repository.mark(OWNER_ID, attempt_id, StopStatus.RESTING, venue_stop_id="STOP-1")
        await repository.mark(OWNER_ID, attempt_id, StopStatus.GONE)
        await session.commit()

    async with pg_session_factory() as session:
        read = await SqlAlchemyProtectiveStopRepository(session).for_attempt(
            OWNER_ID, attempt_id
        )

    assert read is not None
    assert (read.status, read.venue_stop_id) == (StopStatus.GONE, "STOP-1")


async def test_a_mark_moves_updated_at_and_leaves_created_at(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation_id, attempt_id = await _opening(pg_session_factory)
    async with pg_session_factory() as session:
        repository = SqlAlchemyProtectiveStopRepository(session)
        await repository.insert(OWNER_ID, _stop(allocation_id, attempt_id))
        await session.commit()
    async with pg_session_factory() as session:
        before = (await session.execute(select(ProtectiveStopRow))).scalar_one()
        created, updated = before.created_at, before.updated_at
    async with pg_session_factory() as session:
        await SqlAlchemyProtectiveStopRepository(session).mark(
            OWNER_ID, attempt_id, StopStatus.VOID
        )
        await session.commit()

    async with pg_session_factory() as session:
        after = (await session.execute(select(ProtectiveStopRow))).scalar_one()

    assert after.created_at == created
    assert after.updated_at > updated


async def test_another_users_stop_is_neither_read_nor_marked(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Multi-user design AD8: the same attempt id under another user finds nothing."""
    allocation_id, attempt_id = await _opening(pg_session_factory)
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    async with pg_session_factory() as session:
        repository = SqlAlchemyProtectiveStopRepository(session)
        await repository.insert(OWNER_ID, _stop(allocation_id, attempt_id))
        await session.commit()

    async with pg_session_factory() as session:
        repository = SqlAlchemyProtectiveStopRepository(session)
        assert await repository.for_attempt(other, attempt_id) is None
        await repository.mark(other, attempt_id, StopStatus.FAILED)
        await session.commit()

    async with pg_session_factory() as session:
        read = await SqlAlchemyProtectiveStopRepository(session).for_attempt(
            OWNER_ID, attempt_id
        )
    assert read is not None and read.status is StopStatus.PENDING
