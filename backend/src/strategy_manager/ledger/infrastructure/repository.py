"""SQLAlchemy implementation of ``LedgerRepositoryPort`` against the
``ledger_entries`` table (migration ``0005``). Insert-only by contract; the
database enforces the same rule below the application layer with two
triggers (spec: trade-ledger § Append-Only Enforcement).
"""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.ledger.domain.ledger_entry import LedgerEntry
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow


class SqlAlchemyLedgerRepository:
    """Implements ``LedgerRepositoryPort`` and ``LedgerPositionReaderPort``.
    No ``update``/``delete``/``mark`` method exists on this class — there is
    nothing here that could even attempt to mutate a written row."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, entry: LedgerEntry) -> None:
        self._session.add(
            LedgerEntryRow(
                id=entry.id,
                strategy_id=entry.strategy_id,
                allocation_id=entry.allocation_id,
                execution_attempt_id=entry.execution_attempt_id,
                venue=entry.venue,
                settlement_currency=entry.settlement_currency,
                symbol=entry.symbol,
                side=entry.side,
                quantity=entry.quantity,
                price=entry.price,
                fee=entry.fee,
                fee_currency=entry.fee_currency,
                notional=entry.notional,
                exchange_order_id=entry.exchange_order_id,
                exchange_fill_id=entry.exchange_fill_id,
                filled_at=entry.filled_at,
                usd_rate_at_fill=entry.usd_rate_at_fill,
            )
        )
        await self._session.flush()

    async def net_base_quantity(
        self, allocation_id: UUID, base_currency: str
    ) -> Decimal:
        """Implements ``LedgerPositionReaderPort``.

        One aggregate over one allocation's rows: buys add, sells subtract, and
        fees charged in the base currency subtract because that much of the
        purchase never arrived. The comparison is case-insensitive on both
        sides — the fee currency is whatever the exchange called it, and a
        mismatch of case would silently skip the subtraction and oversize every
        close.

        Backed by ``ix_ledger_allocation`` (migration ``0012``); without it
        this is a sequential scan of a table that only ever grows.
        """
        signed_quantity = case(
            (LedgerEntryRow.side == "BUY", LedgerEntryRow.quantity),
            else_=-LedgerEntryRow.quantity,
        )
        base_fee = case(
            (
                func.upper(LedgerEntryRow.fee_currency) == base_currency.upper(),
                LedgerEntryRow.fee,
            ),
            else_=0,
        )

        result = await self._session.execute(
            select(
                func.coalesce(func.sum(signed_quantity - base_fee), 0)
            ).where(LedgerEntryRow.allocation_id == allocation_id)
        )
        return Decimal(result.scalar_one())
