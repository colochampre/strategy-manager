"""SQLAlchemy implementation of ``LedgerRepositoryPort`` against the
``ledger_entries`` table (migration ``0005``). Insert-only by contract; the
database enforces the same rule below the application layer with two
triggers (spec: trade-ledger § Append-Only Enforcement).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.ledger.domain.ledger_entry import LedgerEntry
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow


class SqlAlchemyLedgerRepository:
    """Implements ``ledger.application.ports.LedgerRepositoryPort``. No
    ``update``/``delete``/``mark`` method exists on this class — there is
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
