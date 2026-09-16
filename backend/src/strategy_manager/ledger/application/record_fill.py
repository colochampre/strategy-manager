"""``RecordFill``: implements ``execution.application.ports.FillRecorderPort``
by mapping the consumer-owned ``FillRecord`` DTO to a ``LedgerEntry`` and
writing it through ``LedgerRepositoryPort`` (design.md § Interfaces /
Contracts; spec: trade-ledger § Ledger Row Content).

``usd_rate_at_fill`` arrives already resolved on ``FillRecord`` — this class
only maps and inserts, it never fetches the rate itself (CLAUDE.md rule 7:
the rate is recorded at fill time by the caller and can never be
backfilled).
"""

from uuid import uuid4

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.ledger.application.ports import LedgerRepositoryPort
from strategy_manager.ledger.domain.ledger_entry import LedgerEntry


class RecordFill:
    """Implements ``execution.application.ports.FillRecorderPort``."""

    def __init__(self, repository: LedgerRepositoryPort) -> None:
        self._repository = repository

    async def record(self, fill: FillRecord) -> None:
        entry = LedgerEntry(
            id=uuid4(),
            strategy_id=fill.strategy_id,
            allocation_id=fill.allocation_id,
            execution_attempt_id=fill.execution_attempt_id,
            exchange=fill.exchange,
            venue=fill.venue,
            settlement_currency=fill.settlement_currency,
            symbol=fill.symbol,
            side=fill.side,
            quantity=fill.quantity,
            price=fill.price,
            fee=fill.fee,
            fee_currency=fill.fee_currency,
            notional=fill.notional,
            exchange_order_id=fill.exchange_order_id,
            exchange_fill_id=fill.exchange_fill_id,
            filled_at=fill.filled_at,
            usd_rate_at_fill=fill.usd_rate_at_fill,
        )
        await self._repository.insert(entry)
