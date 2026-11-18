"""``SqlAlchemyStoppedPositionsReader``: which open allocations belong to a strategy that is
disabled or archived (subscriber-safety SS.8b). Read-only: this class has no method that
writes.

The net of an allocation is the ledger's own: BUY adds, any other side subtracts, and a fee
charged in the BASE currency subtracts because that much of a purchase never arrived
(``net_base_quantity`` and ``fold_open_allocations`` read it the same way). It is summed per
allocation, never per symbol, so an allocation opened as ``SOLUSDT.P`` and closed as
``SOLUSDT`` nets to zero and vanishes instead of surviving as two non-zero spellings.
"""

import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.application.ports import StoppedPosition
from strategy_manager.execution.domain.market_symbol import base_currency_of
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.strategies.infrastructure.models import StrategyRow

logger = logging.getLogger(__name__)

_BUY = "BUY"
_STOPPED = or_(StrategyRow.enabled.is_(False), StrategyRow.archived_at.is_not(None))


@dataclass(frozen=True, slots=True)
class _Group:
    """One aggregate row: what one allocation did on one side, under one spelling, with one
    fee currency."""

    user_id: UUID
    strategy_id: UUID
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    side: str
    fee_currency: str
    quantity: Decimal
    fee: Decimal
    first_filled_at: datetime


class SqlAlchemyStoppedPositionsReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def stopped_positions(self) -> Sequence[StoppedPosition]:
        return await self._positions(stopped_only=True, keep_flat=False)

    async def open_of(self, user_id: UUID) -> Sequence[StoppedPosition]:
        """Every allocation ``user_id``'s ledger still holds, whatever state its strategy is
        in, flat ones left out (account-deletion L9). A symbol whose base cannot be split
        from the pool's currency raises, as ``position_of`` does."""
        return await self._positions(
            LedgerEntryRow.user_id == user_id, stopped_only=False, keep_flat=False
        )

    async def position_of(self, user_id: UUID, allocation_id: UUID) -> StoppedPosition | None:
        """One allocation as ``user_id``'s ledger holds it (SS.9), whatever state its strategy
        is in. ``None`` when that user has no ledger row under the id, which is how another
        user's allocation, an unknown id and one that never filled all read. A flat one is
        returned with a zero net."""
        found = await self._positions(
            LedgerEntryRow.user_id == user_id,
            LedgerEntryRow.allocation_id == allocation_id,
            stopped_only=False,
            keep_flat=True,
        )
        return found[0] if found else None

    async def _positions(
        self, *conditions: ColumnElement[bool], stopped_only: bool, keep_flat: bool
    ) -> Sequence[StoppedPosition]:
        fee_currency = func.upper(LedgerEntryRow.fee_currency).label("fee_currency")
        query = (
            select(
                LedgerEntryRow.allocation_id,
                LedgerEntryRow.user_id,
                LedgerEntryRow.strategy_id,
                LedgerEntryRow.exchange,
                LedgerEntryRow.venue,
                LedgerEntryRow.settlement_currency,
                LedgerEntryRow.symbol,
                LedgerEntryRow.side,
                fee_currency,
                func.sum(LedgerEntryRow.quantity),
                func.sum(LedgerEntryRow.fee),
                func.min(LedgerEntryRow.filled_at),
            )
            .where(*conditions)
            .group_by(
                LedgerEntryRow.allocation_id,
                LedgerEntryRow.user_id,
                LedgerEntryRow.strategy_id,
                LedgerEntryRow.exchange,
                LedgerEntryRow.venue,
                LedgerEntryRow.settlement_currency,
                LedgerEntryRow.symbol,
                LedgerEntryRow.side,
                fee_currency,
            )
        )
        if stopped_only:
            query = query.join(StrategyRow, StrategyRow.id == LedgerEntryRow.strategy_id).where(
                _STOPPED
            )
        result = await self._session.execute(query)

        by_allocation: dict[UUID, list[_Group]] = defaultdict(list)
        for row in result.all():
            by_allocation[row[0]].append(
                _Group(
                    user_id=row[1],
                    strategy_id=row[2],
                    exchange=row[3],
                    venue=row[4],
                    settlement_currency=row[5],
                    symbol=row[6],
                    side=row[7],
                    fee_currency=row[8],
                    quantity=Decimal(row[9]),
                    fee=Decimal(row[10]),
                    first_filled_at=row[11],
                )
            )

        positions: list[StoppedPosition] = []
        for allocation_id, groups in by_allocation.items():
            try:
                net = _net_base(groups)
            except InvariantViolation:
                if not stopped_only:
                    # A close asked for by one user: the caller sees the failure, and the
                    # job that asked is retried and logged.
                    raise
                # A symbol whose base cannot be split from the pool's currency cannot be
                # sized, and a close would refuse the same way. It is not flat: say so, so
                # it is never one more position nobody looks at.
                logger.error(
                    "position on a stopped strategy cannot be sized, its base currency is "
                    "unknown, so it is not closed: allocation=%s symbols=%s",
                    allocation_id,
                    ", ".join(sorted({group.symbol for group in groups})),
                )
                continue
            if net == 0 and not keep_flat:
                continue
            opening = min(groups, key=lambda group: group.first_filled_at)
            positions.append(
                StoppedPosition(
                    user_id=opening.user_id,
                    allocation_id=allocation_id,
                    strategy_id=opening.strategy_id,
                    exchange=opening.exchange,
                    venue=opening.venue,
                    settlement_currency=opening.settlement_currency,
                    symbol=opening.symbol,
                    net_base=net,
                )
            )
        return positions

    async def is_stopped(self, strategy_id: UUID) -> bool:
        found = await self._session.execute(
            select(StrategyRow.id).where(StrategyRow.id == strategy_id, _STOPPED)
        )
        return found.first() is not None


def _net_base(groups: Sequence[_Group]) -> Decimal:
    net = Decimal(0)
    for group in groups:
        net += group.quantity if group.side == _BUY else -group.quantity
        base = base_currency_of(group.symbol, group.settlement_currency).upper()
        if group.fee_currency == base:
            net -= group.fee
    return net
