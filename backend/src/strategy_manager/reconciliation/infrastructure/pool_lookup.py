"""The id of a user's pool on a market, for the rows reconciliation writes.

A discrepancy and a booking proposal point at their pool by ``(pool_id,
user_id)`` (migration ``0030``), so the database itself refuses a row in another
user's pool. Looking the id up here, scoped to the user, fails earlier and says
which user and which market: the composite FK would only name a constraint.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import CapitalPoolRow
from strategy_manager.reconciliation.application.ports import PoolKey
from strategy_manager.shared.domain.errors import InvariantViolation


async def pool_id_for(session: AsyncSession, user_id: UUID, pool: PoolKey) -> int:
    """The id of ``user_id``'s pool on ``pool``. Raises ``InvariantViolation``,
    naming the user and the market, when that user holds none there."""
    exchange, venue, settlement_currency = pool
    pool_id = (
        await session.execute(
            select(CapitalPoolRow.id).where(
                CapitalPoolRow.user_id == user_id,
                CapitalPoolRow.exchange == exchange,
                CapitalPoolRow.venue == venue,
                CapitalPoolRow.settlement_currency == settlement_currency,
            )
        )
    ).scalar_one_or_none()
    if pool_id is None:
        raise InvariantViolation(
            f"user {str(user_id)[:8]} has no pool on ({exchange}, {venue}, "
            f"{settlement_currency}); a reconciliation row cannot belong to a pool "
            "that does not exist"
        )
    return int(pool_id)
