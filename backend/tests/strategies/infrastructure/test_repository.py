"""Integration test: SqlAlchemyStrategyRepository insert + get_by_id round
trip (supplemental RED coverage for tasks.md 3.7 — SqlAlchemyStrategyRepository
implementation, mirroring tests/signals/infrastructure/test_repository.py)."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.domain.strategy import AllocationPolicy, FillMode, Strategy
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.owner import OWNER_ID, secret_hash, seed_user

pytestmark = pytest.mark.integration


def _strategy(strategy_id: object, author_id: UUID = OWNER_ID) -> Strategy:
    return Strategy(
        id=strategy_id,  # type: ignore[arg-type]
        name=f"strategy-{strategy_id}",
        policy=AllocationPolicy(exchange=Exchange.PIONEX,
            venue=Venue.SPOT, settlement_currency=Currency.USDT, fill_mode=FillMode.PARTIAL
        ),
        author_id=author_id,
        enabled=True,
    )


async def test_insert_then_get_by_id_round_trips_the_strategy(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()

    async with pg_session_factory() as session:
        repository = SqlAlchemyStrategyRepository(session)
        await repository.insert(_strategy(strategy_id), secret_hash("round-trip"))
        await session.commit()

    async with pg_session_factory() as session:
        repository = SqlAlchemyStrategyRepository(session)
        found = await repository.get_by_id(strategy_id)

    assert found is not None
    assert found.id == strategy_id
    assert found.enabled is True
    assert found.policy.fill_mode == FillMode.PARTIAL
    assert found.policy.venue == Venue.SPOT
    assert found.policy.settlement_currency == Currency.USDT


async def test_a_registered_strategy_round_trips_its_author(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Multi-user design AD2: a strategy carries its author. A second user, not
    the owner every other seed defaults to, so a read that returned the owner
    (or any constant) is told apart."""
    strategy_id = uuid4()
    async with pg_session_factory() as session:
        author = await seed_user(session, f"author-{strategy_id}@example.com")
        await SqlAlchemyStrategyRepository(session).insert(
            _strategy(strategy_id, author), secret_hash("author")
        )
        await session.commit()

    async with pg_session_factory() as session:
        found = await SqlAlchemyStrategyRepository(session).get_by_id(strategy_id)
        listed = await SqlAlchemyStrategyRepository(session).list_all()

    assert found is not None
    assert found.author_id == author
    assert [s.author_id for s in listed if s.id == strategy_id] == [author]


async def test_get_by_id_returns_none_for_unknown_id(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        repository = SqlAlchemyStrategyRepository(session)
        found = await repository.get_by_id(uuid4())

    assert found is None


async def _stored_hash(
    factory: async_sessionmaker[AsyncSession], strategy_id: UUID
) -> str | None:
    async with factory() as session:
        value = await session.scalar(
            text("SELECT webhook_secret_hash FROM strategies WHERE id = :id"),
            {"id": strategy_id},
        )
    return None if value is None else str(value)


async def test_insert_stores_the_hash_it_is_given(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    async with pg_session_factory() as session:
        await SqlAlchemyStrategyRepository(session).insert(
            _strategy(strategy_id), secret_hash("stored")
        )
        await session.commit()

    assert await _stored_hash(pg_session_factory, strategy_id) == secret_hash("stored")


async def test_replacing_the_hash_changes_only_the_hash(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    async with pg_session_factory() as session:
        await SqlAlchemyStrategyRepository(session).insert(
            _strategy(strategy_id), secret_hash("before")
        )
        await session.commit()
    async with pg_session_factory() as session:
        before = await SqlAlchemyStrategyRepository(session).get_by_id(strategy_id)

    async with pg_session_factory() as session:
        await SqlAlchemyStrategyRepository(session).replace_webhook_secret_hash(
            strategy_id, secret_hash("after")
        )
        await session.commit()

    async with pg_session_factory() as session:
        after = await SqlAlchemyStrategyRepository(session).get_by_id(strategy_id)
    assert await _stored_hash(pg_session_factory, strategy_id) == secret_hash("after")
    assert before is not None and after is not None
    assert (after.name, after.enabled, after.policy, after.author_id) == (
        before.name,
        before.enabled,
        before.policy,
        before.author_id,
    )


async def test_replacing_the_hash_of_a_missing_row_raises(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        with pytest.raises(LookupError):
            await SqlAlchemyStrategyRepository(session).replace_webhook_secret_hash(
                uuid4(), secret_hash("nobody")
            )


async def test_no_strategy_read_carries_the_hash(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The hash is the repository's argument and never a field of ``Strategy``, so
    nothing built from a read can serialize it."""
    strategy_id = uuid4()
    async with pg_session_factory() as session:
        await SqlAlchemyStrategyRepository(session).insert(
            _strategy(strategy_id), secret_hash("hidden")
        )
        await session.commit()

    async with pg_session_factory() as session:
        repository = SqlAlchemyStrategyRepository(session)
        reads = [
            await repository.get_by_id(strategy_id),
            await repository.get_by_id_for_update(strategy_id),
            *await repository.list_all(),
        ]

    assert reads and all(read is not None for read in reads)
    for read in reads:
        assert secret_hash("hidden") not in repr(read)
        assert not hasattr(read, "webhook_secret_hash")
