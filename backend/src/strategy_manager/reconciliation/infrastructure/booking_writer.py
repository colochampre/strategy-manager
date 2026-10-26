"""``SqlAlchemyBookingWriter``: implements
``reconciliation.application.ports.BookingWritePort`` -- the ONE place a
booking's ``execution_attempts`` row and its ``ledger_entries`` rows are
written (design.md § 6, "``ApproveBooking`` -- transaction boundary and the
two expected IntegrityErrors").

Reuses the EXISTING write paths rather than opening a second one:
``SqlAlchemyExecutionAttemptRepository.insert`` for the attempt,
``ledger.application.record_fill.RecordFill`` for each ledger row -- the
same class ``SettleExecution`` already calls for a SYSTEM-origin fill.
Everything here runs inside its own SAVEPOINT
(``session.begin_nested()``), nested in the caller's (``ApproveBooking``'s)
still-open outer transaction, mirroring
``SqlAlchemyBookingProposalRepository.insert``'s identical reasoning: an
aborted Postgres transaction would otherwise take the caller's subsequent
``mark_state`` call down with it, turning an expected outcome into the
failure the proposal forbids.
"""

from collections.abc import Sequence
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt
from strategy_manager.execution.infrastructure.repository import (
    CLIENT_ORDER_ID_UNIQUE_CONSTRAINT,
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.application.ports import (
    BookingWriteOutcome,
    BookingWriteResult,
)
from strategy_manager.shared.domain.errors import InvariantViolation

# The live name of ``ledger_entries.ux_ledger_exchange_fill`` (migrations
# ``0019``, ``0030``; the name survived the per-user rebuild), verified against
# ``ledger/infrastructure/repository.py``'s own ``_FILL_INDEX`` constant and the
# migration itself -- recorded here (this module's own copy, not an import of
# that module-private name) so this writer can identify the collision by
# CONSTRAINT NAME, never message text, the same discipline
# ``CLIENT_ORDER_ID_UNIQUE_CONSTRAINT`` already applies.
LEDGER_EXCHANGE_FILL_UNIQUE_CONSTRAINT = "ux_ledger_exchange_fill"

_EXPECTED_CONSTRAINTS = frozenset(
    {CLIENT_ORDER_ID_UNIQUE_CONSTRAINT, LEDGER_EXCHANGE_FILL_UNIQUE_CONSTRAINT}
)


def _constraint_name(error: IntegrityError) -> str | None:
    """Identical helper to
    ``booking_proposal_repository._constraint_name``: reading
    ``error.orig.__cause__.constraint_name`` (asyncpg's shape, not
    psycopg's ``.orig.diag``) is the only way this project's driver exposes
    a violated constraint's NAME rather than its message text."""

    cause = error.orig.__cause__  # type: ignore[union-attr]
    return getattr(cause, "constraint_name", None)


class SqlAlchemyBookingWriter:
    """Implements ``reconciliation.application.ports.BookingWritePort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._attempts = SqlAlchemyExecutionAttemptRepository(session)
        self._record_fill = RecordFill(SqlAlchemyLedgerRepository(session))

    async def write(
        self, attempt: ExecutionAttempt, fill_records: Sequence[FillRecord]
    ) -> BookingWriteResult:
        # The attempt is its reservation's user's, whichever side it is on (an
        # open through ``reservation_id``, a close through
        # ``closes_allocation_id``). Read, not scoped: reconciliation per user
        # is a later unit of PR B (multi-user design AD10).
        user_id = (
            await self._session.execute(
                select(ReservationRow.user_id).where(
                    ReservationRow.id
                    == (
                        attempt.reservation_id
                        if attempt.reservation_id is not None
                        else attempt.closes_allocation_id
                    )
                )
            )
        ).scalar_one_or_none()
        if user_id is None:
            raise InvariantViolation(
                f"booking attempt {attempt.id} names a reservation that does not exist"
            )
        try:
            # A SAVEPOINT, not the outer transaction -- see module
            # docstring. ``ApproveBooking`` still needs to call
            # ``mark_state`` in the SAME transaction after either outcome.
            async with self._session.begin_nested():
                await self._attempts.insert(user_id, attempt)
                for fill in fill_records:
                    # The ledger row is the reservation's user's, like the attempt.
                    await self._record_fill.record(replace(fill, user_id=user_id))
        except IntegrityError as error:
            name = _constraint_name(error)
            if name not in _EXPECTED_CONSTRAINTS:
                raise
            return BookingWriteResult(
                outcome=BookingWriteOutcome.ALREADY_RECORDED,
                execution_attempt_id=attempt.id,
                fills_written=0,
                reason=name,
            )
        return BookingWriteResult(
            outcome=BookingWriteOutcome.WRITTEN,
            execution_attempt_id=attempt.id,
            fills_written=len(fill_records),
        )
