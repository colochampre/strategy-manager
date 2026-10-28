"""``signal_owner`` and ``attempt_owner`` against real PostgreSQL.

A worker job trades and reads with its strategy author's key (multi-user design
AD8, tasks.md B.5 and B.7). Two authors each own a strategy with a signal, a
reservation and attempts, so an answer that picked the wrong row, or the first
row, names the wrong user.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.signals.infrastructure.job_owner import attempt_owner, signal_owner
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)
from tests.owner import OWNER_ID, ensure_delivery, seed_other_user
from tests.signals.infrastructure.conftest import (
    seed_execution_attempt as seed_delivered_attempt,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Authored:
    signal_id: UUID
    open_attempt: UUID
    close_attempt: UUID


async def _authored(factory: async_sessionmaker[AsyncSession], author: UUID) -> Authored:
    strategy_id, signal_id, reservation_id = uuid4(), uuid4(), uuid4()
    open_attempt, close_attempt = uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id, author_id=author)
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    await seed_reservation(
        factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        status="FILLED",
        user_id=author,
    )
    await seed_execution_attempt(
        factory, attempt_id=open_attempt, reservation_id=reservation_id, status="FILLED"
    )
    await seed_execution_attempt(
        factory, attempt_id=close_attempt, closes_allocation_id=reservation_id
    )
    return Authored(signal_id, open_attempt, close_attempt)


@pytest.fixture
async def two_authors(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> tuple[Authored, Authored, UUID]:
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    owners = await _authored(pg_session_factory, OWNER_ID)
    others = await _authored(pg_session_factory, other)
    return owners, others, other


async def test_a_signal_belongs_to_its_strategys_author_never_another_users(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    two_authors: tuple[Authored, Authored, UUID],
) -> None:
    owners, others, other = two_authors

    async with pg_session_factory() as session:
        answers = [
            await signal_owner(session, owners.signal_id),
            await signal_owner(session, others.signal_id),
        ]

    assert answers == [OWNER_ID, other]


async def test_an_opening_and_a_closing_attempt_belong_to_their_strategys_author(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    two_authors: tuple[Authored, Authored, UUID],
) -> None:
    owners, others, other = two_authors

    async with pg_session_factory() as session:
        answers = [
            await attempt_owner(session, owners.open_attempt),
            await attempt_owner(session, owners.close_attempt),
            await attempt_owner(session, others.open_attempt),
            await attempt_owner(session, others.close_attempt),
        ]

    assert answers == [OWNER_ID, OWNER_ID, other, other]


async def test_a_subscribers_attempts_belong_to_the_subscriber_not_the_strategys_author(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """C.8: ``execution.settle`` is owned by whoever the delivery that placed the
    attempt is for. The strategy is the owner's; the open, the close and an orphan
    close (no delivery at all) were all written as the subscriber, and the settle job
    must trade with the subscriber's key."""
    strategy_id, signal_id, reservation_id = uuid4(), uuid4(), uuid4()
    open_attempt, close_attempt, orphan_close = uuid4(), uuid4(), uuid4()
    async with pg_session_factory() as session:
        subscriber = await seed_other_user(session)
        await session.commit()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id, author_id=OWNER_ID)
    await seed_signal(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    async with pg_session_factory() as session:
        delivery_id = await ensure_delivery(
            session, signal_id=signal_id, strategy_id=strategy_id, user_id=subscriber
        )
        await session.commit()
    await seed_reservation(
        pg_session_factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        status="FILLED",
        user_id=subscriber,
    )
    # Only one close of an allocation may be live at once: the delivery's is FILLED.
    for attempt_id, closes, link, status in (
        (open_attempt, None, delivery_id, "FILLED"),
        (close_attempt, reservation_id, delivery_id, "FILLED"),
        (orphan_close, reservation_id, None, "SUBMITTED"),
    ):
        await seed_delivered_attempt(
            pg_session_factory,
            attempt_id=attempt_id,
            reservation_id=None if closes else reservation_id,
            closes_allocation_id=closes,
            delivery_id=link,
            status=status,
        )

    async with pg_session_factory() as session:
        answers = [
            await attempt_owner(session, attempt)
            for attempt in (open_attempt, close_attempt, orphan_close)
        ]

    assert answers == [subscriber, subscriber, subscriber]
    assert OWNER_ID not in answers


async def test_an_unknown_signal_or_attempt_has_no_owner(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    two_authors: tuple[Authored, Authored, UUID],
) -> None:
    async with pg_session_factory() as session:
        answers = [await signal_owner(session, uuid4()), await attempt_owner(session, uuid4())]

    assert answers == [None, None]
