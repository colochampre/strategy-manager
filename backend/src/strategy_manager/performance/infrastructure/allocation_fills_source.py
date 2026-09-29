"""``SqlAlchemyAllocationFillsSource``: the one SQL aggregate behind every
performance read (design.md section 11; tasks.md 3b.7).

Joins ``ledger_entries`` to ``reservations`` (an allocation IS its
reservation) to bring ``pool_total_at_open`` along, and folds fills into
``(allocation_id, strategy_id, side, fee_currency)`` groups. The domain does
the rest (``derive_trades``); this class only reads.

**Rehearsal fills are excluded here**, by the prefix constant that the fake
exchange mints with. ``startswith(..., autoescape=True)`` renders
``NOT LIKE :prefix || '%' ESCAPE '/'`` so the LIKE wildcards ``%`` and ``_``
in a prefix could never widen the match.

**One pool per call.** The WHERE is the pool's full identity, so the read
rides ``ix_ledger_pool_symbol`` (leading columns exchange, venue,
settlement_currency, migration 0020) and never sees another pool's money
(CLAUDE.md rule 7). ``ix_ledger_allocation`` (0012) serves the per-allocation
grouping and the join.

**Timestamps are returned as stored** (timezone-aware ``timestamptz``). The
UTC day of ``closed_at`` is taken in the domain, never by a session time zone.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.performance.application.ports import PoolFills
from strategy_manager.performance.domain.closed_trade import FillGroup


class SqlAlchemyAllocationFillsSource:
    """Implements ``AllocationFillsSourcePort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def pool_fills(self, pool: PoolKey) -> PoolFills:
        exchange = pool.exchange.value
        venue = pool.venue.value
        settlement_currency = pool.settlement_currency.value

        in_pool = (
            LedgerEntryRow.exchange == exchange,
            LedgerEntryRow.venue == venue,
            LedgerEntryRow.settlement_currency == settlement_currency,
        )
        is_rehearsal = LedgerEntryRow.exchange_fill_id.startswith(
            REHEARSAL_FILL_ID_PREFIX, autoescape=True
        )

        grouped = await self._session.execute(
            select(
                LedgerEntryRow.allocation_id,
                LedgerEntryRow.strategy_id,
                LedgerEntryRow.side,
                LedgerEntryRow.fee_currency,
                func.min(LedgerEntryRow.symbol),
                func.sum(LedgerEntryRow.quantity),
                func.sum(LedgerEntryRow.notional),
                func.sum(LedgerEntryRow.fee),
                func.min(LedgerEntryRow.filled_at),
                func.max(LedgerEntryRow.filled_at),
                ReservationRow.pool_total_at_open,
            )
            .join(ReservationRow, ReservationRow.id == LedgerEntryRow.allocation_id)
            .where(*in_pool, ~is_rehearsal)
            .group_by(
                LedgerEntryRow.allocation_id,
                LedgerEntryRow.strategy_id,
                LedgerEntryRow.side,
                LedgerEntryRow.fee_currency,
                ReservationRow.pool_total_at_open,
            )
            .order_by(
                LedgerEntryRow.allocation_id,
                LedgerEntryRow.side,
                LedgerEntryRow.fee_currency,
            )
        )
        groups = tuple(
            FillGroup(
                allocation_id=allocation_id,
                strategy_id=strategy_id,
                exchange=exchange,
                venue=venue,
                settlement_currency=settlement_currency,
                symbol=symbol,
                side=side,
                fee_currency=fee_currency,
                quantity=Decimal(quantity),
                notional=Decimal(notional),
                fee=Decimal(fee),
                first_filled_at=first_filled_at,
                last_filled_at=last_filled_at,
                pool_total_at_open=(
                    None if pool_total_at_open is None else Decimal(pool_total_at_open)
                ),
            )
            for (
                allocation_id,
                strategy_id,
                side,
                fee_currency,
                symbol,
                quantity,
                notional,
                fee,
                first_filled_at,
                last_filled_at,
                pool_total_at_open,
            ) in grouped.all()
        )

        rehearsal = await self._session.execute(
            select(LedgerEntryRow.strategy_id, func.count())
            .where(*in_pool, is_rehearsal)
            .group_by(LedgerEntryRow.strategy_id)
        )
        by_strategy = tuple((strategy_id, int(count)) for strategy_id, count in rehearsal.all())
        return PoolFills(
            groups=groups,
            rehearsal_fill_count=sum(count for _, count in by_strategy),
            rehearsal_by_strategy=by_strategy,
        )
