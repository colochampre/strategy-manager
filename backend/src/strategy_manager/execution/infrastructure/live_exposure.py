"""``SqlAlchemyLiveExposure``: what a user holds that is real, by market, for the
flat check behind ``POST /api/me/mode`` (decision 6). Reconciliation also asks it
over every user, whether anything real exists at all (tasks.md E2.1).

Real means one of three things, and each covers a moment the others miss:

- **A reservation** recorded ``LIVE`` and not yet finished. ``expires_at`` is not
  read: it says what capital is counted, while a reservation the sweeper has not
  reached may still have a worker placing its order.
- **An attempt** in ``SUBMITTED`` whose reservation is ``LIVE``, opening or
  closing, with or without an order id: the order may be on its way to the venue.
- **An open allocation** holding a real fill, the same definition of "open" the
  guard and the panel use (``SqlAlchemyModeOriginReader``). The fill is the fact
  here, so nothing is asked of the reservation.

**The order of the reads is part of the check.** Each runs in its own READ
COMMITTED snapshot, and exposure only ever moves forward, from the reservation to
the attempt to the ledger. Reading in that same order, whatever left one read has
already reached the next. Read the other way, a settle committing in between
leaves the fill unseen and the attempt gone, and a user with a real position
reads as flat.

A market is listed once whatever the spelling: the signal carries TradingView's,
the attempt and the ledger the venue's.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.domain.reservation import ReservationStatus
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.domain.execution_attempt import ExecutionStatus
from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.execution.domain.mode_origin import SPELLING_SEPARATOR
from strategy_manager.execution.infrastructure.mode_origin_reader import (
    SqlAlchemyModeOriginReader,
)
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.signals.infrastructure.models import SignalRow

_UNFINISHED = (ReservationStatus.PENDING.value, ReservationStatus.SUBMITTED.value)


class SqlAlchemyLiveExposure:
    """Read-only: this class has no method that writes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def symbols(self, user_id: UUID) -> Sequence[str]:
        return await self._symbols(user_id)

    async def symbols_of_everyone(self) -> Sequence[str]:
        return await self._symbols(None)

    async def _symbols(self, user_id: UUID | None) -> Sequence[str]:
        spellings: set[str] = set()
        spellings.update(await self._reserved(user_id))
        spellings.update(await self._submitted(user_id))
        spellings.update(await self._open(user_id))
        return sorted({market_key(spelling) for spelling in spellings})

    async def _reserved(self, user_id: UUID | None) -> Sequence[str]:
        owner = () if user_id is None else (ReservationRow.user_id == user_id,)
        result = await self._session.execute(
            select(SignalRow.symbol)
            .select_from(ReservationRow)
            .join(SignalRow, SignalRow.id == ReservationRow.signal_id)
            .where(
                *owner,
                ReservationRow.mode == Mode.LIVE.value,
                ReservationRow.status.in_(_UNFINISHED),
            )
        )
        return result.scalars().all()

    async def _submitted(self, user_id: UUID | None) -> Sequence[str]:
        owner = () if user_id is None else (ExecutionAttemptRow.user_id == user_id,)
        result = await self._session.execute(
            select(ExecutionAttemptRow.symbol)
            .join(
                ReservationRow,
                ReservationRow.id
                == func.coalesce(
                    ExecutionAttemptRow.reservation_id,
                    ExecutionAttemptRow.closes_allocation_id,
                ),
            )
            .where(
                *owner,
                ExecutionAttemptRow.status == ExecutionStatus.SUBMITTED.value,
                ReservationRow.mode == Mode.LIVE.value,
            )
        )
        return result.scalars().all()

    async def _open(self, user_id: UUID | None) -> Sequence[str]:
        allocations = await SqlAlchemyModeOriginReader(self._session).open_allocations(user_id)
        return [
            spelling
            for allocation in allocations
            if allocation.holds_live_fill
            for spelling in allocation.symbol.split(SPELLING_SEPARATOR)
        ]
