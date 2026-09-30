"""Implements ``CredentialRevokerPort`` over ``exchange_credentials`` (owner
decision 22).

Like the listing, it has no cipher and selects none of the columns that hold a
secret: deleting a key never needs to open it. The row is DEACTIVATED, never
removed, because rotation history is retained (a superseded key is a row to
reactivate, not a secret that no longer exists anywhere).

Both methods run in the caller's transaction and never commit.
"""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.application.ports import ActiveCredential
from strategy_manager.accounts.infrastructure.models import ExchangeCredentialRow
from strategy_manager.shared.application.ports import ClockPort

_ROW = ExchangeCredentialRow


class SqlAlchemyCredentialRevoker:
    def __init__(self, session: AsyncSession, clock: ClockPort) -> None:
        self._session = session
        self._clock = clock

    async def lock_active(self, exchange: str) -> ActiveCredential | None:
        row = (
            await self._session.execute(
                select(_ROW.exchange, _ROW.label, _ROW.api_key_last4)
                .where(_ROW.exchange == exchange, _ROW.is_active.is_(True))
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            return None
        return ActiveCredential(exchange=row.exchange, label=row.label, last4=row.api_key_last4)

    async def deactivate(self, exchange: str) -> None:
        await self._session.execute(
            update(_ROW)
            .where(_ROW.exchange == exchange, _ROW.is_active.is_(True))
            .values(is_active=False, updated_at=self._clock.now())
        )
