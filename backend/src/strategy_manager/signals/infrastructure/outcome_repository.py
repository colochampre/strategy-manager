"""SQLAlchemy implementation of ``SignalOutcomePort`` (decision 25,
design.md "Addendum: signal outcomes (decision 25)" § A, § D).

A separate adapter from ``SqlAlchemySignalRepository`` (rather than a new
method on it): every existing call site constructs that repository as
``SqlAlchemySignalRepository(session)``, with no clock, and this port needs
one to stamp ``decided_at``. Wiring a use case to both ports (PR 5b.6/5b.7)
is future work; this unit only creates the port and its adapter.
"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.domain.signal import SignalStatus
from strategy_manager.signals.infrastructure.models import SignalRow

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({SignalStatus.PROCESSED, SignalStatus.REJECTED})


class SqlAlchemySignalOutcomeAdapter:
    """Implements ``SignalOutcomePort`` against the ``signals`` table.

    ``record`` stages its write on the caller's own session and never calls
    ``commit()`` -- the same-commit rule (design.md § C) requires the
    outcome write to land in the SAME flushed unit of work as the step that
    decided it, staged immediately before that step's own commit.

    The terminal-state guard reads the current row and decides inside this
    one method, with no second round trip: ``PROCESSED``/``REJECTED`` are
    never overwritten. A DIFFERENT second outcome for an already-terminal
    signal is a no-op that logs exactly one WARNING naming the signal, the
    outcome already recorded, and the one refused. An IDENTICAL repeat is a
    silent no-op -- the ordinary case a duplicate webhook delivery or an
    idempotent close replay produces (design.md § A, rows 19-20). Writing
    ``PROCESSING`` is never a terminal write, so it always succeeds,
    including ``PROCESSING`` over an existing ``PROCESSING``.
    """

    def __init__(self, session: AsyncSession, clock: ClockPort) -> None:
        self._session = session
        self._clock = clock

    async def record(self, signal_id: UUID, outcome: SignalOutcome) -> None:
        row = await self._session.get(SignalRow, signal_id)
        if row is None:
            raise InvariantViolation(f"cannot record an outcome for unknown signal {signal_id}")

        current_status = SignalStatus(row.status)
        if current_status in _TERMINAL_STATUSES:
            if (
                current_status == outcome.status
                and row.outcome_reason == outcome.reason
                and row.outcome_detail == outcome.detail
            ):
                return  # identical repeat: silent no-op
            logger.warning(
                "signal %s already terminal at %s (reason=%s); refused to overwrite with "
                "%s (reason=%s)",
                signal_id,
                current_status.value,
                row.outcome_reason,
                outcome.status.value,
                outcome.reason,
            )
            return

        row.status = outcome.status.value
        row.outcome_reason = outcome.reason
        row.outcome_detail = outcome.detail
        if outcome.status in _TERMINAL_STATUSES:
            row.decided_at = self._clock.now()
