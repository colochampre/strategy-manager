"""Implements ``allocation.application.PoolStatusPort`` over ``capital_pools``.

A plain column SELECT on the caller's session: no ``FOR UPDATE`` and no ORM
entity. The session is READ COMMITTED, so the statement sees whatever was
committed when it runs -- which, called after ``AllocateCapital`` has acquired
the pool advisory lock, includes a ``DeleteCredential`` that held that lock
first and has just committed. A row lock here would be wrong: the delete's
``disable()`` updates this same row, and a waiting allocation must not hold a
lock the delete needs (lock order: advisory first, then row locks).

Selecting the column rather than the entity also keeps the ORM identity map out
of it, so a value cached earlier in the session can never answer for a fresh
read.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.models import CapitalPoolRow


class SqlAlchemyPoolStatus:
    """Implements ``allocation.application.PoolStatusPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_disabled(self, exchange: str, venue: str, settlement_currency: str) -> bool:
        enabled = (
            await self._session.execute(
                select(CapitalPoolRow.enabled).where(
                    CapitalPoolRow.exchange == exchange,
                    CapitalPoolRow.venue == venue,
                    CapitalPoolRow.settlement_currency == settlement_currency,
                )
            )
        ).scalar_one_or_none()
        # No row is not "disabled": the balance read owns that failure.
        return enabled is False
