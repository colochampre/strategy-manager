"""``CloseStoppedPositions``: the reservation sweep's safety close (subscriber-safety SS.8b,
spec ``safety-close``, "A stopped strategy's positions are closed at once").

A strategy that is disabled or archived while someone still holds a position on it has no
signal left that would ever close that position. Disabling is refused while exposure
exists (SS.8a), but an operator action or a state that predates that guard can still leave
one behind. So every sweep run lists them and closes each one at market, through
``ClosePosition``, sized from the ledger, with no signal and the cause ``SAFETY_CLOSE``.

Each position is decided on its own, as ``EndFlatLeaving`` decides each subscription:

- the listing is a plain read, so a stale row costs one lock and a re-read;
- the decision takes that user's pool lock first, then re-checks under it that the strategy
  is still stopped and that no close of the allocation is already SUBMITTED. A SUBMITTED close
  is never repeated; a FAILED one is tried again on the next run
  (``ux_execution_attempts_live_close`` is the backstop in the database);
- ``ClosePosition`` commits (and so gives the lock back) before it contacts the venue. Every
  other exit commits or rolls back here, so no lock outlives its decision;
- the close is signed with the key of the user who holds the position, never another's:
  ``closer_for`` opens that user's exchanges.

One position failing, for any reason, is logged at ERROR and never stops the others nor the
sweep's successor. What fails silently here would be a position left open on a strategy
nobody watches, so every path that does not send a close says so: a flat ledger and dust are
the only ones that are not errors.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID

from strategy_manager.execution.application.close_position import (
    CloseCommand,
    CloseResult,
    NothingRecordedYet,
)
from strategy_manager.execution.application.ports import (
    PoolLockPort,
    StoppedPosition,
    StoppedPositionsReaderPort,
    UnitOfWorkPort,
)
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionCause,
    ExecutionStatus,
)
from strategy_manager.execution.domain.order import OrderSide

logger = logging.getLogger(__name__)


class PositionCloserPort(Protocol):
    """What this use case needs of ``ClosePosition``."""

    async def close(self, command: CloseCommand) -> CloseResult: ...


class ClosingAttemptsPort(Protocol):
    """The latest closing attempt of an allocation, in any status."""

    async def latest_close_for(
        self, user_id: UUID, allocation_id: UUID
    ) -> ExecutionAttempt | None: ...


class CloseStoppedPositions:
    def __init__(
        self,
        stopped: StoppedPositionsReaderPort,
        closing_attempts: ClosingAttemptsPort,
        pool_lock: PoolLockPort,
        closer_for: Callable[[UUID], AbstractAsyncContextManager[PositionCloserPort]],
        unit_of_work: UnitOfWorkPort,
    ) -> None:
        self._stopped = stopped
        self._closing_attempts = closing_attempts
        self._pool_lock = pool_lock
        self._closer_for = closer_for
        self._uow = unit_of_work

    async def sweep(self) -> int:
        """Returns how many closes it sent. Never raises: a failed listing is logged and
        the next run lists again, and a failed position is logged and the others go on."""
        try:
            positions = await self._stopped.stopped_positions()
        except Exception:
            await self._uow.rollback()
            logger.error(
                "positions on stopped strategies could not be listed, none was closed this "
                "run: the next sweep lists them again",
                exc_info=True,
            )
            return 0

        by_user: dict[UUID, list[StoppedPosition]] = {}
        for position in positions:
            by_user.setdefault(position.user_id, []).append(position)

        sent = 0
        for user_id, owned in by_user.items():
            sent += await self._close_for_user(user_id, owned)
        return sent

    async def _close_for_user(self, user_id: UUID, owned: list[StoppedPosition]) -> int:
        """One user's positions, closed with that user's key alone."""
        sent = 0
        decided = 0
        try:
            async with self._closer_for(user_id) as closer:
                for position in owned:
                    if await self._close_one(closer, position):
                        sent += 1
                    decided += 1
        except Exception:
            # The user's exchanges could not be opened (their key does not open, say) or
            # closed. Every position not yet decided is still open and is listed again.
            await self._uow.rollback()
            logger.error(
                "positions on stopped strategies not closed, they stay open and are listed "
                "again: user=%s undecided_allocations=%s",
                user_id,
                ", ".join(str(position.allocation_id) for position in owned[decided:]),
                exc_info=True,
            )
        return sent

    async def _close_one(self, closer: PositionCloserPort, position: StoppedPosition) -> bool:
        """Decides one position under its holder's pool lock. Returns whether a close was
        sent. Never raises: a failure ends the transaction, which gives the lock back."""
        try:
            await self._pool_lock.acquire(
                position.user_id,
                position.exchange,
                position.venue,
                position.settlement_currency,
            )
            # The listing was a plain read: the strategy may have been enabled, and a close
            # sent in the meantime is already SUBMITTED, so both are read again under the lock.
            if not await self._stopped.is_stopped(position.strategy_id):
                await self._uow.commit()
                logger.info(
                    "strategy is running again, its position is left open: user=%s "
                    "allocation=%s strategy=%s symbol=%s",
                    position.user_id,
                    position.allocation_id,
                    position.strategy_id,
                    position.symbol,
                )
                return False
            latest = await self._closing_attempts.latest_close_for(
                position.user_id, position.allocation_id
            )
            if latest is not None and latest.status is ExecutionStatus.SUBMITTED:
                await self._uow.commit()
                logger.info(
                    "safety close already in flight, none sent: user=%s allocation=%s "
                    "strategy=%s symbol=%s attempt=%s",
                    position.user_id,
                    position.allocation_id,
                    position.strategy_id,
                    position.symbol,
                    latest.id,
                )
                return False
            result = await closer.close(_command(position))
        except NothingRecordedYet:
            # The ledger went flat since the listing: nothing is left to close.
            await self._uow.commit()
            logger.info(
                "position on a stopped strategy is already flat: user=%s allocation=%s "
                "strategy=%s symbol=%s",
                position.user_id,
                position.allocation_id,
                position.strategy_id,
                position.symbol,
            )
            return False
        except Exception:
            await self._uow.rollback()
            logger.error(
                "safety close of a position on a stopped strategy failed, it stays open and "
                "is tried again: user=%s allocation=%s strategy=%s symbol=%s",
                position.user_id,
                position.allocation_id,
                position.strategy_id,
                position.symbol,
                exc_info=True,
            )
            return False
        return self._report(position, result)

    @staticmethod
    def _report(position: StoppedPosition, result: CloseResult) -> bool:
        where = (
            f"user={position.user_id} allocation={position.allocation_id} "
            f"strategy={position.strategy_id} symbol={position.symbol}"
        )
        if result.status == "PLACED":
            logger.warning(
                "safety close sent for a position on a stopped strategy: %s side=%s size=%s "
                "attempt=%s",
                where,
                closing_side(position).value,
                result.base_size,
                result.execution_attempt_id,
            )
            return True
        if result.status == "FAILED":
            logger.error(
                "safety close of a position on a stopped strategy refused by the venue, it "
                "stays open and is tried again: %s attempt=%s error=%s",
                where,
                result.execution_attempt_id,
                result.error,
            )
            return False
        if result.status == "NOT_CLOSABLE":
            logger.warning(
                "position on a stopped strategy is dust no order can close: %s size=%s",
                where,
                result.base_size,
            )
            return False
        if result.status in {"ALREADY_CLOSED_BY_STOP", "ALREADY_FLAT"}:
            logger.info(
                "position on a stopped strategy needs no close (%s): %s", result.status, where
            )
            return False
        logger.error(
            "safety close of a position on a stopped strategy ended in an unknown state %r: %s",
            result.status,
            where,
        )
        return False


def closing_side(position: StoppedPosition) -> OrderSide:
    """The side that unwinds the position: SELL for a long, BUY for a short."""
    return OrderSide.SELL if position.net_base > 0 else OrderSide.BUY


def _command(position: StoppedPosition) -> CloseCommand:
    return CloseCommand(
        user_id=position.user_id,
        allocation_id=position.allocation_id,
        strategy_id=position.strategy_id,
        exchange=position.exchange,
        venue=position.venue,
        settlement_currency=position.settlement_currency,
        symbol=position.symbol,
        side=closing_side(position),
        # No signal asked for this close: none outcome is recorded.
        signal_id=None,
        delivery_id=None,
        reference_price=None,
        # The system closes by itself: no strategy asked for this.
        cause=ExecutionCause.SAFETY_CLOSE,
    )
