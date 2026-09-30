"""Implements ``CapitalPoolWriterPort`` over ``capital_pools`` (owner decisions 21, 22).

Both methods write through the CALLER's session and never commit, so the pool
change lands in the same transaction as the credential write that asked for it
and rolls back with it. That is the whole point of the port: a save that is
refused, that loses the race for the one-active-key slot, or whose venue read
fails never reaches this class, and one that reaches it and then fails later
takes the pool write down with it.

Identity comes from ``KNOWN_FUTURES_POOLS`` alone, never from a caller.

**No advisory lock, on purpose.** The pool advisory lock serializes an
allocation's availability read, decision and reservation (rule 4). Enabling a
pool changes none of those: a disabled pool is not read by the worker, so no
allocation can be in flight against it, and an enabled one is left as it is.
``enable`` is one atomic upsert statement; it takes only the pool's row lock,
as the LAST step of a transaction that then commits, and never goes on to ask
for the advisory lock, so it cannot close a cycle with the project's lock order
(pool advisory lock first, then row locks). ``DeleteCredential`` (unit 6e),
which does have exposure to read, takes the advisory lock itself before it
calls ``disable``.
"""

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.domain.known_pools import known_pool_for
from strategy_manager.accounts.infrastructure.models import CapitalPoolRow


class SqlAlchemyCapitalPoolWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enable(self, exchange: str) -> bool:
        pool = known_pool_for(exchange)
        insertion = insert(CapitalPoolRow).values(
            exchange=exchange,
            venue=pool.venue.value,
            settlement_currency=pool.settlement_currency.value,
            enabled=True,
            min_order_size=pool.default_min_order_size,
        )
        # ``min_order_size`` is deliberately absent from the update: an existing
        # row keeps whatever it was configured with. The WHERE makes the
        # statement return a row only when it changed something (inserted, or
        # flipped from disabled), which is how the caller knows to log it.
        upsert = insertion.on_conflict_do_update(
            index_elements=[
                CapitalPoolRow.exchange,
                CapitalPoolRow.venue,
                CapitalPoolRow.settlement_currency,
            ],
            set_={"enabled": True},
            where=CapitalPoolRow.enabled.is_(False),
        ).returning(CapitalPoolRow.exchange)
        result = await self._session.execute(upsert)
        return result.first() is not None

    async def disable(self, exchange: str) -> bool:
        pool = known_pool_for(exchange)
        flip = (
            update(CapitalPoolRow)
            .where(
                CapitalPoolRow.exchange == exchange,
                CapitalPoolRow.venue == pool.venue.value,
                CapitalPoolRow.settlement_currency == pool.settlement_currency.value,
                CapitalPoolRow.enabled.is_(True),
            )
            .values(enabled=False)
            .returning(CapitalPoolRow.exchange)
        )
        result = await self._session.execute(flip)
        return result.first() is not None
