"""Registering a strategy subscribes its author, in the same transaction (tasks.md
C.4b), on real PostgreSQL.

``RegisterStrategy`` is driven through its real repository and the real adapter.
The venue catalogue and the pool catalogue are fakes: they decide only whether a
registration gets as far as the write.
"""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.application.register_strategy import (
    PoolNotAvailable,
    RegisterCommand,
    RegisterStrategy,
)
from strategy_manager.strategies.domain.strategy import FillMode
from strategy_manager.strategies.infrastructure.author_subscription_adapter import (
    SqlAlchemyAuthorSubscription,
)
from strategy_manager.strategies.infrastructure.enablement_log import SqlAlchemyEnablementLog
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.owner import OWNER_ID, seed_other_user
from tests.strategies.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]

MARKET = (Exchange.BYBIT, Venue.USDT_M, Currency.USDT)


class _Pools:
    """Says the author's pool is enabled, whatever the database holds: how a pool
    deleted between the check and the write is played."""

    async def enabled_pools(self, user_id: UUID) -> list[tuple[Exchange, Venue, Currency]]:
        return [MARKET]


class _Catalog:
    async def available_pairs(self, pool: tuple[str, str, str]) -> frozenset[str]:
        return frozenset({"ETHUSDT"})


def _use_case(session: AsyncSession) -> RegisterStrategy:
    return RegisterStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        pools=_Pools(),
        pairs=_Catalog(),
        commit=session,
        enablement_log=SqlAlchemyEnablementLog(session),
        clock=SystemClock(),
        author_subscriptions=SqlAlchemyAuthorSubscription(session),
    )


def _command(strategy_id: UUID, author_id: UUID, share: str = "40") -> RegisterCommand:
    return RegisterCommand(
        strategy_id=strategy_id,
        name=f"strategy-{strategy_id}",
        exchange=MARKET[0],
        venue=MARKET[1],
        settlement_currency=MARKET[2],
        fill_mode=FillMode.PARTIAL,
        allocation_percent=Decimal(share),
        allowed_pairs=["ETHUSDT"],
        author_id=author_id,
    )


async def _count(factory: Factory, table: str, strategy_id: UUID) -> int:
    column = "id" if table == "strategies" else "strategy_id"
    async with factory() as session:
        found = await session.scalar(
            text(f"SELECT count(*) FROM {table} WHERE {column} = :id"),  # noqa: S608
            {"id": strategy_id},
        )
    assert isinstance(found, int)
    return found


async def test_registering_writes_the_authors_active_subscription_in_their_pool_at_the_share(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    strategy_id = uuid4()
    async with pg_session_factory() as session:
        pool_id = await session.scalar(
            text(
                "SELECT id FROM capital_pools WHERE user_id = :user AND exchange = 'bybit' "
                "AND venue = 'usdt-m' AND settlement_currency = 'USDT'"
            ),
            {"user": OWNER_ID},
        )
        await _use_case(session).register(_command(strategy_id, OWNER_ID, "40"))

    async with pg_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT user_id, pool_id, allocation_percent, status FROM subscriptions "
                    "WHERE strategy_id = :id"
                ),
                {"id": strategy_id},
            )
        ).all()
        strategy_share = await session.scalar(
            text("SELECT allocation_percent FROM strategies WHERE id = :id"), {"id": strategy_id}
        )
    assert len(rows) == 1
    [row] = rows
    assert (row.user_id, row.pool_id, row.allocation_percent, row.status) == (
        OWNER_ID,
        pool_id,
        Decimal("40"),
        "ACTIVE",
    )
    # Until C.6 the strategy keeps its own copy, which is what sizing still reads.
    assert strategy_share == Decimal("40")


async def test_a_pool_that_vanished_before_the_write_leaves_neither_row(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The pool catalogue still says the author's pool is enabled, but the author
    holds none: the strategy row is flushed, the subscription cannot be written,
    and nothing is committed."""
    async with pg_session_factory() as session:
        author = await seed_other_user(session)
        await session.commit()
    strategy_id = uuid4()

    async with pg_session_factory() as session:
        with pytest.raises(PoolNotAvailable):
            await _use_case(session).register(_command(strategy_id, author))

    assert await _count(pg_session_factory, "strategies", strategy_id) == 0
    assert await _count(pg_session_factory, "subscriptions", strategy_id) == 0
