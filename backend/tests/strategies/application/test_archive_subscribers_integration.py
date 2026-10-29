"""Archive against every subscriber, on real PostgreSQL (multi-user tasks.md C.9,
owner decision 5): it refuses while ANY subscriber holds an open allocation, and
when it archives it ends every subscription in the same transaction.

A symbol crossing a module boundary wears a different spelling on each side: the
alert says ``STXUSDT.P``, the venue and the ledger say ``STXUSDT``, Pionex says
``STXUSDT_PERP``. The ledger rows below are written under each in turn.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.strategies.application.archive_strategy import ArchiveStrategy, OpenPosition
from strategy_manager.strategies.infrastructure.exposure_adapter import StrategyExposureAdapter
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow
from tests.ledger.infrastructure.conftest import seed_strategy
from tests.owner import OWNER_ID, ensure_author_subscription
from tests.strategies.wiring import real_subscribers
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]
FIXED_NOW = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
LOGGER = "strategy_manager.strategies.application.archive_strategy"


class _Clock:
    def now(self) -> datetime:
        return FIXED_NOW


def _archive(session: AsyncSession) -> ArchiveStrategy:
    ledger = SqlAlchemyLedgerRepository(session)
    return ArchiveStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        pool_lock=PoolLockAdapter(session),
        subscribers=real_subscribers(session),
        exposure=StrategyExposureAdapter(
            ledger=ledger,
            symbol_holdings=ReadSymbolHoldings(ledger),
            reservations=SqlAlchemyReservationRepository(session),
            attempts=SqlAlchemyExecutionAttemptRepository(session),
        ),
        commit=session,  # type: ignore[arg-type]
        clock=_Clock(),
    )


async def _strategy(factory: Factory) -> UUID:
    """A disabled strategy of the owner's with the author's own subscription."""
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id, enabled=False)
    async with factory() as session:
        await ensure_author_subscription(session, strategy_id)
        await session.commit()
    return strategy_id


async def _subscriber(factory: Factory, strategy_id: UUID, status: str) -> UUID:
    user_id, pool_id = await seeds.user(factory)
    assert pool_id is not None
    await seeds.subscription(factory, user_id, strategy_id, pool_id, status=status)
    return user_id


async def _states(factory: Factory, strategy_id: UUID) -> dict[UUID, tuple[str, datetime | None]]:
    async with factory() as session:
        result = await session.execute(
            select(SubscriptionRow.user_id, SubscriptionRow.status, SubscriptionRow.ended_at).where(
                SubscriptionRow.strategy_id == strategy_id
            )
        )
        return {user_id: (status, ended_at) for user_id, status, ended_at in result.all()}


async def _archived_at(factory: Factory, strategy_id: UUID) -> datetime | None:
    async with factory() as session:
        row = await session.get(StrategyRow, strategy_id)
        assert row is not None
        return row.archived_at


async def test_archiving_ends_every_live_subscription_of_every_user_and_only_those(
    pg_session_factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    active = await _subscriber(pg_session_factory, strategy_id, "ACTIVE")
    leaving = await _subscriber(pg_session_factory, strategy_id, "LEAVING")
    ended_before = datetime(2026, 10, 1, tzinfo=UTC)
    gone, gone_pool = await seeds.user(pg_session_factory)
    assert gone_pool is not None
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, "
                "allocation_percent, status, ended_at) "
                "VALUES (:id, :user_id, :strategy_id, :pool_id, 30, 'ENDED', :ended_at)"
            ),
            {
                "id": uuid4(),
                "user_id": gone,
                "strategy_id": strategy_id,
                "pool_id": gone_pool,
                "ended_at": ended_before,
            },
        )
        await session.commit()

    with caplog.at_level(logging.INFO, logger=LOGGER):
        async with pg_session_factory() as session:
            result = await _archive(session).archive(strategy_id)

    assert result.already_archived is False
    assert await _archived_at(pg_session_factory, strategy_id) == FIXED_NOW
    states = await _states(pg_session_factory, strategy_id)
    assert states[OWNER_ID] == ("ENDED", FIXED_NOW)
    assert states[active] == ("ENDED", FIXED_NOW)
    assert states[leaving] == ("ENDED", FIXED_NOW)
    assert states[gone] == ("ENDED", ended_before)  # a finished one is left as it was
    info = [r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelno == 20]
    assert len(info) == 1
    assert str(strategy_id) in info[0]
    assert "subscriptions_ended=3" in info[0]


@pytest.mark.parametrize("status", ["ACTIVE", "LEAVING"])
@pytest.mark.parametrize("symbol", ["STXUSDT", "STXUSDT.P", "STXUSDT_PERP"])
async def test_a_non_author_subscriber_holding_a_position_refuses_the_archive_whatever_the_spelling(
    pg_session_factory: Factory, status: str, symbol: str
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    holder = await _subscriber(pg_session_factory, strategy_id, status)
    await _subscriber(pg_session_factory, strategy_id, "ACTIVE")  # flat: never named
    await seeds.open_allocation(pg_session_factory, holder, strategy_id, symbol=symbol)
    before = (
        await seeds.rows(pg_session_factory),
        await _archived_at(pg_session_factory, strategy_id),
    )

    async with pg_session_factory() as session:
        with pytest.raises(OpenPosition) as refused:
            await _archive(session).archive(strategy_id)

    message = str(refused.value)
    assert str(strategy_id) in message
    assert f"user {str(holder)[:8]}" in message
    assert str(holder) not in message
    assert "author" not in message
    # Nothing moved: no archive, every subscription as it was.
    assert (
        await seeds.rows(pg_session_factory),
        await _archived_at(pg_session_factory, strategy_id),
    ) == before
    assert before[1] is None


async def test_the_authors_own_position_is_still_named_the_author(
    pg_session_factory: Factory,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    await seeds.open_allocation(pg_session_factory, OWNER_ID, strategy_id)

    async with pg_session_factory() as session:
        with pytest.raises(OpenPosition) as refused:
            await _archive(session).archive(strategy_id)

    assert "held_by=['author']" in str(refused.value)


async def test_a_refusal_logs_one_warning_naming_the_strategy_and_the_holder(
    pg_session_factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    holder = await _subscriber(pg_session_factory, strategy_id, "ACTIVE")
    await seeds.live_reservation(pg_session_factory, holder, strategy_id)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        async with pg_session_factory() as session:
            with pytest.raises(OpenPosition):
                await _archive(session).archive(strategy_id)

    warnings = [r.getMessage() for r in caplog.records if r.name == LOGGER]
    assert len(warnings) == 1
    assert str(strategy_id) in warnings[0]
    assert f"user {str(holder)[:8]}" in warnings[0]
    assert str(holder) not in warnings[0]


async def test_replaying_an_archive_ends_a_subscription_left_live_and_keeps_archived_at(
    pg_session_factory: Factory,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    earlier = datetime(2026, 10, 1, tzinfo=UTC)
    async with pg_session_factory() as session:
        await session.execute(
            text("UPDATE strategies SET archived_at = :at WHERE id = :id"),
            {"at": earlier, "id": strategy_id},
        )
        await session.commit()
    leftover = await _subscriber(pg_session_factory, strategy_id, "ACTIVE")

    async with pg_session_factory() as session:
        result = await _archive(session).archive(strategy_id)

    assert result.already_archived is True
    assert await _archived_at(pg_session_factory, strategy_id) == earlier
    assert (await _states(pg_session_factory, strategy_id))[leftover] == ("ENDED", FIXED_NOW)
