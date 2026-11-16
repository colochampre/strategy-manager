"""``CloseByHand``: a user closes one of their own open positions from the panel
(subscriber-safety SS.9, spec ``safety-close``, "A user can close their own position from
the panel").

The API never opens a key, so it never places the order: it checks that the allocation is the
user's, enqueues one ``MANUAL_CLOSE`` job and answers. This is that job's use case, run by the
worker with the user's own exchanges. It decides the way ``CloseStoppedPositions`` decides each
position:

- the allocation is read scoped by the signed-in user's id, so another user's reads exactly
  like one that does not exist, and sends nothing;
- the decision takes that user's pool lock first, then reads the position again and checks
  that no close of the allocation is already SUBMITTED. A SUBMITTED close is never repeated;
  a FAILED one is tried again (``ux_execution_attempts_live_close`` is the backstop in the
  database);
- ``ClosePosition`` commits (and so gives the lock back) before it contacts the venue. Every
  other exit commits or rolls back here, so no lock outlives its decision;
- the close is sized from the ledger, on the side opposite the ledger's net, with no signal and
  no delivery, and its cause is ``MANUAL``. The mode is the one the reservation records, which
  ``ClosePosition`` reads itself.

The seat is left as it is: an ACTIVE seat takes the strategy's next opening.

What fails silently here is a click that does nothing, so every path that does not send a close
says so: a flat ledger and a close already in flight are the only ones that are not errors. An
unexpected failure is logged at ERROR and raised again, so the queue retries it.
"""

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from uuid import UUID

from strategy_manager.execution.application.close_position import (
    CloseCommand,
    CloseResult,
    NothingRecordedYet,
)
from strategy_manager.execution.application.close_stopped_positions import (
    ClosingAttemptsPort,
    PositionCloserPort,
    closing_side,
)
from strategy_manager.execution.application.ports import (
    OwnPositionReaderPort,
    PoolLockPort,
    StoppedPosition,
    UnitOfWorkPort,
)
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionCause,
    ExecutionStatus,
)

logger = logging.getLogger(__name__)


class CloseByHand:
    def __init__(
        self,
        positions: OwnPositionReaderPort,
        closing_attempts: ClosingAttemptsPort,
        pool_lock: PoolLockPort,
        closer_for: Callable[[UUID], AbstractAsyncContextManager[PositionCloserPort]],
        unit_of_work: UnitOfWorkPort,
    ) -> None:
        self._positions = positions
        self._closing_attempts = closing_attempts
        self._pool_lock = pool_lock
        self._closer_for = closer_for
        self._uow = unit_of_work

    async def close(self, user_id: UUID, allocation_id: UUID) -> bool:
        """Returns whether a close was sent. Raises only on an unexpected failure, after
        ending the transaction, so the job is retried."""
        try:
            async with self._closer_for(user_id) as closer:
                return await self._decide(closer, user_id, allocation_id)
        except Exception:
            await self._uow.rollback()
            logger.error(
                "close asked for from the panel failed, the position stays open: user=%s "
                "allocation=%s",
                user_id,
                allocation_id,
                exc_info=True,
            )
            raise

    async def _decide(self, closer: PositionCloserPort, user_id: UUID, allocation_id: UUID) -> bool:
        found = await self._positions.position_of(user_id, allocation_id)
        if found is None:
            return await self._not_theirs(user_id, allocation_id)
        await self._pool_lock.acquire(
            user_id, found.exchange, found.venue, found.settlement_currency
        )
        # The first read was a plain one: it only found the pool to lock. The size and the
        # side are read again under the lock.
        position = await self._positions.position_of(user_id, allocation_id)
        if position is None:
            return await self._not_theirs(user_id, allocation_id)
        if position.net_base == 0:
            await self._uow.commit()
            logger.info(
                "close asked for from the panel found the position flat, nothing sent: "
                "user=%s allocation=%s symbol=%s",
                user_id,
                allocation_id,
                position.symbol,
            )
            return False
        latest = await self._closing_attempts.latest_close_for(user_id, allocation_id)
        if latest is not None and latest.status is ExecutionStatus.SUBMITTED:
            await self._uow.commit()
            logger.info(
                "close asked for from the panel already in flight, none sent: user=%s "
                "allocation=%s symbol=%s attempt=%s",
                user_id,
                allocation_id,
                position.symbol,
                latest.id,
            )
            return False
        try:
            result = await closer.close(_command(position))
        except NothingRecordedYet:
            # The ledger went flat since the read: nothing is left to close.
            await self._uow.commit()
            logger.info(
                "close asked for from the panel found the position flat, nothing sent: "
                "user=%s allocation=%s symbol=%s",
                user_id,
                allocation_id,
                position.symbol,
            )
            return False
        return self._report(position, result)

    async def _not_theirs(self, user_id: UUID, allocation_id: UUID) -> bool:
        await self._uow.commit()
        logger.error(
            "close asked for from the panel names an allocation the user does not hold, "
            "nothing sent: user=%s allocation=%s",
            user_id,
            allocation_id,
        )
        return False

    @staticmethod
    def _report(position: StoppedPosition, result: CloseResult) -> bool:
        where = (
            f"user={position.user_id} allocation={position.allocation_id} "
            f"symbol={position.symbol}"
        )
        if result.status == "PLACED":
            logger.warning(
                "close asked for from the panel sent: %s side=%s size=%s attempt=%s",
                where,
                closing_side(position).value,
                result.base_size,
                result.execution_attempt_id,
            )
            return True
        if result.status == "FAILED":
            logger.error(
                "close asked for from the panel refused by the venue, the position stays "
                "open: %s attempt=%s error=%s",
                where,
                result.execution_attempt_id,
                result.error,
            )
            return False
        if result.status == "NOT_CLOSABLE":
            logger.warning(
                "close asked for from the panel is dust no order can close: %s size=%s",
                where,
                result.base_size,
            )
            return False
        if result.status in {"ALREADY_CLOSED_BY_STOP", "ALREADY_FLAT"}:
            logger.info(
                "close asked for from the panel needs no close (%s): %s", result.status, where
            )
            return False
        logger.error(
            "close asked for from the panel ended in an unknown state %r: %s",
            result.status,
            where,
        )
        return False


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
        # No signal asked for this close: no outcome is recorded.
        signal_id=None,
        delivery_id=None,
        reference_price=None,
        # The user asked for it from the panel.
        cause=ExecutionCause.MANUAL,
    )
