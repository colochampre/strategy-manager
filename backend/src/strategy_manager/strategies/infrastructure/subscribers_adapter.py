"""Implements ``strategies.application.ports.StrategySubscribersPort`` by composing
the subscriptions module's own repository and its open-allocation read, following
the ``StrategyExposureAdapter`` precedent: the consumer (``strategies``) declared
the port, the provider's adapters do the work.

**Why the pool comes from the pool's own row.** ``subscriptions.pool_id`` and
``user_id`` reference ``capital_pools (id, user_id)`` (``fk_subscriptions_pool``,
no ``ON DELETE``), so a live subscription always has its pool row and the inner
join below cannot lose one: the database refuses to delete a pool a subscription
still names. The exchange, venue and currency are read from that row, so the lock
taken is derived from the very pool ``AllocateCapital`` locks for that user, never
from a market the strategy is assumed to share with it.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import CapitalPoolRow
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.strategies.application.ports import SubscriberPool
from strategy_manager.subscriptions.infrastructure.adapters import OpenAllocationAdapter
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow
from strategy_manager.subscriptions.infrastructure.repository import (
    SqlAlchemySubscriptionRepository,
)

_LIVE = ("ACTIVE", "LEAVING")


class StrategySubscribersAdapter:
    """Implements ``StrategySubscribersPort``."""

    def __init__(
        self,
        session: AsyncSession,
        ledger: SqlAlchemyLedgerRepository,
        symbol_holdings: ReadSymbolHoldings,
    ) -> None:
        self._session = session
        self._subscriptions = SqlAlchemySubscriptionRepository(session)
        self._allocations = OpenAllocationAdapter(session, ledger, symbol_holdings)

    async def live_pools(self, strategy_id: UUID) -> list[SubscriberPool]:
        result = await self._session.execute(
            select(
                CapitalPoolRow.id,
                CapitalPoolRow.user_id,
                CapitalPoolRow.exchange,
                CapitalPoolRow.venue,
                CapitalPoolRow.settlement_currency,
            )
            .join(
                SubscriptionRow,
                (SubscriptionRow.pool_id == CapitalPoolRow.id)
                & (SubscriptionRow.user_id == CapitalPoolRow.user_id),
            )
            .where(
                SubscriptionRow.strategy_id == strategy_id,
                SubscriptionRow.status.in_(_LIVE),
            )
            .order_by(CapitalPoolRow.id)
        )
        return [
            SubscriberPool(
                pool_id=int(pool_id),
                user_id=user_id,
                pool=(exchange, venue, currency),
            )
            for pool_id, user_id, exchange, venue, currency in result.all()
        ]

    async def holders(
        self, strategy_id: UUID, subscribers: Sequence[SubscriberPool]
    ) -> list[UUID]:
        return [
            subscriber.user_id
            for subscriber in subscribers
            if await self._allocations.holds_open_allocation(
                subscriber.user_id, strategy_id, subscriber.pool
            )
        ]

    async def end_all(self, strategy_id: UUID, now: datetime) -> int:
        live = await self._subscriptions.live_for_strategy_for_update(strategy_id)
        for subscription in live:
            await self._subscriptions.update(subscription.end(now))
        return len(live)
