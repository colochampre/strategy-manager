"""``SqlAlchemyModeOriginReader``: implements
``execution.application.ports.ModeOriginReaderPort`` for the ``DRY_RUN`` mode
guard (owner decision 28).

Two reads, both over the WHOLE database. Neither filters on a pool, and in
particular neither joins ``capital_pools.enabled``: a position stays open at a
venue whether or not anyone still trades the pool it sits in.

**Open allocations.** The SQL only aggregates; whether an allocation is open is
the domain's call (``fold_open_allocations``), because the base-fee rule needs
the base currency of a symbol and that is Python (``base_currency_of``), not a
column. The aggregate is grouped by side, fee currency and the ORIGIN of the
fill, which is all the fold needs and keeps the row count near the number of
allocations rather than the number of fills.

The origin is a PREFIX test on ``exchange_fill_id``. ``REHEARSAL_FILL_ID_PREFIX``
is the same constant the fake exchange mints with and the performance reads
exclude on, so the definition of "a rehearsal fill" lives in one place. A
substring test would let a live id that merely contains the marker read as a
rehearsal.

**In-flight attempts.** ``SUBMITTED`` is the only non-terminal status
(``FILLED``, ``FAILED`` and ``ABORTED_EXPIRED`` are all final). Its origin is
the order id the exchange returned: the fake mints ``fake-order-...``, and no
venue does. A ``SUBMITTED`` attempt whose ``exchange_order_id`` is still NULL
is skipped, because nothing in that row says which mode wrote it; see the
guard's design note for the gap.
"""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.domain.execution_attempt import ExecutionStatus
from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    LedgerGroup,
    OpenAllocationOrigin,
    fold_open_allocations,
)
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.strategies.infrastructure.models import StrategyRow


class SqlAlchemyModeOriginReader:
    """Read-only: this class has no method that writes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def open_allocations(self) -> Sequence[OpenAllocationOrigin]:
        rehearsal = LedgerEntryRow.exchange_fill_id.startswith(
            REHEARSAL_FILL_ID_PREFIX, autoescape=True
        ).label("rehearsal")
        fee_currency = func.upper(LedgerEntryRow.fee_currency).label("fee_currency")

        result = await self._session.execute(
            select(
                LedgerEntryRow.allocation_id,
                StrategyRow.name,
                LedgerEntryRow.exchange,
                LedgerEntryRow.venue,
                LedgerEntryRow.settlement_currency,
                LedgerEntryRow.symbol,
                LedgerEntryRow.side,
                fee_currency,
                rehearsal,
                func.sum(LedgerEntryRow.quantity),
                func.sum(LedgerEntryRow.fee),
            )
            .join(StrategyRow, StrategyRow.id == LedgerEntryRow.strategy_id)
            .group_by(
                LedgerEntryRow.allocation_id,
                StrategyRow.name,
                LedgerEntryRow.exchange,
                LedgerEntryRow.venue,
                LedgerEntryRow.settlement_currency,
                LedgerEntryRow.symbol,
                LedgerEntryRow.side,
                fee_currency,
                rehearsal,
            )
        )

        return fold_open_allocations(
            [
                LedgerGroup(
                    allocation_id=allocation_id,
                    strategy_name=name,
                    exchange=exchange,
                    venue=venue,
                    settlement_currency=settlement_currency,
                    symbol=symbol,
                    side=side,
                    fee_currency=fee_currency_value,
                    rehearsal=bool(is_rehearsal),
                    quantity=Decimal(quantity),
                    fee=Decimal(fee),
                )
                for (
                    allocation_id,
                    name,
                    exchange,
                    venue,
                    settlement_currency,
                    symbol,
                    side,
                    fee_currency_value,
                    is_rehearsal,
                    quantity,
                    fee,
                ) in result.all()
            ]
        )

    async def in_flight_attempts(self) -> Sequence[InFlightAttemptOrigin]:
        result = await self._session.execute(
            select(
                ExecutionAttemptRow.id,
                StrategyRow.name,
                ExecutionAttemptRow.exchange,
                ExecutionAttemptRow.venue,
                ExecutionAttemptRow.settlement_currency,
                ExecutionAttemptRow.symbol,
                ExecutionAttemptRow.exchange_order_id,
            )
            # An opening attempt names its reservation, a closing one the
            # allocation it unwinds; both are reservation ids and both carry
            # the strategy.
            .join(
                ReservationRow,
                ReservationRow.id
                == func.coalesce(
                    ExecutionAttemptRow.reservation_id,
                    ExecutionAttemptRow.closes_allocation_id,
                ),
            )
            .join(StrategyRow, StrategyRow.id == ReservationRow.strategy_id)
            .where(
                ExecutionAttemptRow.status == ExecutionStatus.SUBMITTED.value,
                ExecutionAttemptRow.exchange_order_id.is_not(None),
            )
        )

        return [
            InFlightAttemptOrigin(
                attempt_id=attempt_id,
                strategy_name=name,
                exchange=exchange,
                venue=venue,
                settlement_currency=settlement_currency,
                symbol=symbol,
                exchange_order_id=exchange_order_id,
            )
            for (
                attempt_id,
                name,
                exchange,
                venue,
                settlement_currency,
                symbol,
                exchange_order_id,
            ) in result.all()
        ]
