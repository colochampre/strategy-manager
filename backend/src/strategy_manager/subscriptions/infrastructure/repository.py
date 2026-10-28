"""SQLAlchemy implementation of ``SubscriptionRepositoryPort``.

**Every read and every write filters by ``user_id``** (multi-user design AD8):
another user's subscription is simply not found, never forbidden, so its
existence is not revealed.
"""

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.strategies.domain.strategy import AllocationPercent
from strategy_manager.subscriptions.application.errors import AlreadySubscribed
from strategy_manager.subscriptions.domain.subscription import Subscription, SubscriptionStatus
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow

ONE_LIVE_PER_STRATEGY_CONSTRAINT = "ux_subscriptions_one_live_per_strategy"
_LIVE = (SubscriptionStatus.ACTIVE.value, SubscriptionStatus.LEAVING.value)


class SqlAlchemySubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, subscription: Subscription) -> None:
        row = SubscriptionRow(
            id=subscription.id,
            user_id=subscription.user_id,
            strategy_id=subscription.strategy_id,
            pool_id=subscription.pool_id,
            allocation_percent=subscription.allocation_percent.value,
            status=subscription.status.value,
            left_at=subscription.left_at,
            ended_at=subscription.ended_at,
        )
        if subscription.created_at is not None:
            # Otherwise the column's server default stamps it.
            row.created_at = subscription.created_at
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as error:
            if _constraint_name(error) == ONE_LIVE_PER_STRATEGY_CONSTRAINT:
                await self._session.rollback()
                raise AlreadySubscribed(
                    f"user already holds a live subscription to strategy "
                    f"{subscription.strategy_id}"
                ) from None
            raise

    async def get(self, user_id: UUID, subscription_id: UUID) -> Subscription | None:
        row = (
            await self._session.execute(
                select(SubscriptionRow).where(
                    SubscriptionRow.id == subscription_id, SubscriptionRow.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        return None if row is None else _to_domain(row)

    async def get_for_update(self, user_id: UUID, subscription_id: UUID) -> Subscription | None:
        """``SELECT ... FOR UPDATE``. ``populate_existing`` makes it return what the
        database holds NOW even when this session already loaded the row, which is
        the point: the decision under the lock must not use the unlocked read."""
        row = (
            await self._session.execute(
                select(SubscriptionRow)
                .where(SubscriptionRow.id == subscription_id, SubscriptionRow.user_id == user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return None if row is None else _to_domain(row)

    async def get_live_for_update(
        self, user_id: UUID, strategy_id: UUID
    ) -> Subscription | None:
        """``SELECT ... FOR UPDATE`` of the user's ACTIVE or LEAVING row for the
        strategy, re-read as the database holds it now (see ``get_for_update``)."""
        row = (
            await self._session.execute(
                select(SubscriptionRow)
                .where(
                    SubscriptionRow.user_id == user_id,
                    SubscriptionRow.strategy_id == strategy_id,
                    SubscriptionRow.status.in_(_LIVE),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return None if row is None else _to_domain(row)

    async def update(self, subscription: Subscription) -> None:
        """Writes the mutable fields of the user's own row; a row of another user
        matches nothing and is left alone."""
        await self._session.execute(
            update(SubscriptionRow)
            .where(
                SubscriptionRow.id == subscription.id,
                SubscriptionRow.user_id == subscription.user_id,
            )
            .values(
                allocation_percent=subscription.allocation_percent.value,
                status=subscription.status.value,
                left_at=subscription.left_at,
                ended_at=subscription.ended_at,
            )
            .execution_options(synchronize_session="fetch")
        )
        await self._session.flush()

    async def list_for_user(self, user_id: UUID) -> list[Subscription]:
        result = await self._session.execute(
            select(SubscriptionRow)
            .where(SubscriptionRow.user_id == user_id)
            .order_by(SubscriptionRow.created_at, SubscriptionRow.id)
        )
        return [_to_domain(row) for row in result.scalars().all()]

    async def live_for_strategies(
        self, user_id: UUID, strategy_ids: Sequence[UUID]
    ) -> dict[UUID, Subscription]:
        """The user's ACTIVE or LEAVING subscription to each of ``strategy_ids``, by
        strategy id, in ONE query; a strategy the user holds none of is absent. The
        partial unique index allows one live row per (user, strategy), so the map
        never loses one."""
        if not strategy_ids:
            return {}
        result = await self._session.execute(
            select(SubscriptionRow).where(
                SubscriptionRow.user_id == user_id,
                SubscriptionRow.strategy_id.in_(strategy_ids),
                SubscriptionRow.status.in_(_LIVE),
            )
        )
        return {row.strategy_id: _to_domain(row) for row in result.scalars().all()}

    async def has_live(self, user_id: UUID, strategy_id: UUID) -> bool:
        found = (
            await self._session.execute(
                select(SubscriptionRow.id)
                .where(
                    SubscriptionRow.user_id == user_id,
                    SubscriptionRow.strategy_id == strategy_id,
                    SubscriptionRow.status.in_(_LIVE),
                )
                .limit(1)
            )
        ).first()
        return found is not None


def _to_domain(row: SubscriptionRow) -> Subscription:
    return Subscription(
        id=row.id,
        user_id=row.user_id,
        strategy_id=row.strategy_id,
        pool_id=row.pool_id,
        allocation_percent=AllocationPercent(Decimal(row.allocation_percent)),
        status=SubscriptionStatus(row.status),
        created_at=row.created_at,
        left_at=row.left_at,
        ended_at=row.ended_at,
    )


def _constraint_name(error: IntegrityError) -> str | None:
    """The violated constraint's NAME, from the driver's own error (asyncpg's
    ``PostgresError`` is the ``__cause__`` of SQLAlchemy's DBAPI wrapper). Message
    text is never consulted."""
    cause = error.orig.__cause__  # type: ignore[union-attr]
    return getattr(cause, "constraint_name", None)
