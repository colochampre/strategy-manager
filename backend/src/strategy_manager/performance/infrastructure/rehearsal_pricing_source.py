"""``SqlAlchemyRehearsalPricingSource``: how the opening fills of rehearsal
operations were priced, from stored rows alone (design.md, addendum "a
strategy's operations", sections C and E).

**One statement, however many ids.** A grouped SELECT of ``ledger_entries``
joined to ``reservations`` (an allocation IS its reservation) and to ``signals``
(the signal the reservation names), ``WHERE allocation_id IN (:ids)`` and the
strategy and the pool, answering per ``(allocation, side)`` the lowest and the
highest fill ``price`` next to the price the alert carried. It is not three more
columns of the shared aggregate on purpose: that aggregate is what every report
reads, and a join to another module's table has no business under a total. This
statement runs only when a rehearsal row is on the page.

**The strategy and the pool are in the WHERE.** An allocation of another
strategy, or of another pool, is simply absent from the answer: the port cannot
be used to read what the caller's path does not own.

**The answer is keyed by allocation.** The symbol is neither selected nor
grouped, so an operation opened as ``STXUSDT_PERP`` and closed as ``STXUSDT.P``
is one entry. Prices are the fills' own ``price``, never a derived average.

``performance/infrastructure`` already reads ``ReservationRow`` and
``LedgerEntryRow``; this adapter also reads ``SignalRow``. No signal, allocation
or ledger type crosses into ``application/`` or ``domain/``: the answer is
``PricingFacts``.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.performance.domain.operation import BUY, SELL, PricingFacts, SidePrices
from strategy_manager.signals.infrastructure.models import SignalRow


class SqlAlchemyRehearsalPricingSource:
    """Implements ``RehearsalPricingSourcePort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def pricing_facts(
        self, pool: PoolKey, strategy_id: UUID, allocation_ids: Sequence[UUID]
    ) -> Mapping[UUID, PricingFacts]:
        if not allocation_ids:
            return {}

        rows = await self._session.execute(
            select(
                LedgerEntryRow.allocation_id,
                LedgerEntryRow.side,
                func.min(LedgerEntryRow.price),
                func.max(LedgerEntryRow.price),
                SignalRow.price,
            )
            .join(ReservationRow, ReservationRow.id == LedgerEntryRow.allocation_id)
            .join(SignalRow, SignalRow.id == ReservationRow.signal_id)
            .where(
                LedgerEntryRow.allocation_id.in_(allocation_ids),
                LedgerEntryRow.strategy_id == strategy_id,
                LedgerEntryRow.exchange == pool.exchange.value,
                LedgerEntryRow.venue == pool.venue.value,
                LedgerEntryRow.settlement_currency == pool.settlement_currency.value,
            )
            .group_by(LedgerEntryRow.allocation_id, LedgerEntryRow.side, SignalRow.price)
        )

        alert_prices: dict[UUID, Decimal] = {}
        sides: dict[UUID, dict[str, SidePrices]] = {}
        for allocation_id, side, lowest, highest, alert_price in rows.all():
            alert_prices[allocation_id] = Decimal(alert_price)
            sides.setdefault(allocation_id, {})[side] = SidePrices(
                lowest=Decimal(lowest), highest=Decimal(highest)
            )
        return {
            allocation_id: PricingFacts(
                alert_price=alert_price,
                buy=sides[allocation_id].get(BUY),
                sell=sides[allocation_id].get(SELL),
            )
            for allocation_id, alert_price in alert_prices.items()
        }
