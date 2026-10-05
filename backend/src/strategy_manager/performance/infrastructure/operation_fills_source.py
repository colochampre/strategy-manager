"""``SqlAlchemyOperationFillsSource``: the fills of one operation (design.md,
addendum "a strategy's operations", sections D and E).

**One SELECT, no join.** ``WHERE allocation_id = :a AND strategy_id = :s ORDER BY
filled_at, id LIMIT :n`` on ``ledger_entries``, which ``ix_ledger_allocation``
(migration 0012) serves. The statement count does not grow with the fills.

**The strategy predicate is in the statement.** ``ledger_entries.strategy_id`` is
on every fill (CLAUDE.md rule 6), so no row of another strategy leaves the
database: there is nothing for the application to filter and nothing to leak by
forgetting to. There is deliberately no pool predicate: a WHERE on the pool would
drop a fill written under another pool and leave a shorter list with no trace, so
the read refuses such a fill after the fact instead.

**The key is the allocation, never the symbol.** An operation opened as
``STXUSDT_PERP`` and closed as ``STXUSDT.P`` answers the fills of both spellings,
and the fill it answers carries no symbol at all.

**Each fill's origin comes from its own fill id**: the same prefix test, with the
same escaping, as the aggregate that feeds the list. A mixed allocation therefore
answers each fill with its own flag. The order is ``(filled_at, id)`` ascending,
the order the fills happened in, with the row id as a stable tie-break.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.performance.domain.operation import OperationFill


class SqlAlchemyOperationFillsSource:
    """Implements ``OperationFillsSourcePort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def operation_fills(
        self, strategy_id: UUID, allocation_id: UUID, limit: int
    ) -> Sequence[OperationFill]:
        is_rehearsal = LedgerEntryRow.exchange_fill_id.startswith(
            REHEARSAL_FILL_ID_PREFIX, autoescape=True
        )
        rows = await self._session.execute(
            select(
                LedgerEntryRow.filled_at,
                LedgerEntryRow.side,
                LedgerEntryRow.price,
                LedgerEntryRow.quantity,
                LedgerEntryRow.fee,
                LedgerEntryRow.fee_currency,
                is_rehearsal.label("is_rehearsal"),
                LedgerEntryRow.exchange,
                LedgerEntryRow.venue,
                LedgerEntryRow.settlement_currency,
            )
            .where(
                LedgerEntryRow.allocation_id == allocation_id,
                LedgerEntryRow.strategy_id == strategy_id,
            )
            .order_by(LedgerEntryRow.filled_at, LedgerEntryRow.id)
            .limit(limit)
        )
        return [
            OperationFill(
                filled_at=filled_at,
                side=side,
                price=price,
                quantity=quantity,
                fee=fee,
                fee_currency=fee_currency.upper(),
                rehearsal=bool(rehearsal),
                exchange=exchange,
                venue=venue,
                settlement_currency=settlement_currency,
            )
            for (
                filled_at,
                side,
                price,
                quantity,
                fee,
                fee_currency,
                rehearsal,
                exchange,
                venue,
                settlement_currency,
            ) in rows.all()
        ]
