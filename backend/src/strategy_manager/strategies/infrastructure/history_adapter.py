"""Implements ``strategies.application.ports.StrategyHistoryPort`` by
composing one narrow count per provider repository, following the
``StrategyExposureAdapter`` precedent (design.md addendum 9x, § B and § C):
the consumer (``strategies``) declared the port, each provider module owns
the read over its own table, and this adapter only assembles the answer.

Read-only: six ``SELECT count(...)`` statements, no lock, nothing written.
Locking is ``DeleteStrategy``'s job.
"""

from uuid import UUID

from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository
from strategy_manager.strategies.application.ports import StrategyHistory
from strategy_manager.strategies.infrastructure.enablement_log import SqlAlchemyEnablementLog

COUNTED_STRATEGY_REFERENCES: dict[str, tuple[str, str]] = {
    "fk_signals_strategy": ("signals", "signals"),
    "fk_reservations_strategy": ("reservations", "reservations"),
    "fk_ledger_entries_strategy": ("ledger_entries", "ledger_entries"),
    "fk_booking_proposals_strategy": ("booking_proposals", "booking_proposals"),
    "fk_strategy_enablement_events_strategy": (
        "strategy_enablement_events",
        "enablement_events",
    ),
}
"""Every foreign key into ``strategies`` that the history check counts:
constraint name -> ``(table, StrategyHistory field)``. Read by
``test_strategy_references_guard``, which compares it with ``pg_constraint``
on a database migrated to ``head``, so a migration that adds a reference
cannot leave the delete check silently stale.

``execution_attempts`` has no entry: it carries no ``strategy_id`` and reaches
a strategy through ``reservations`` and ``signals``, which the guard also pins.
"""


class StrategyHistoryAdapter:
    """Implements ``StrategyHistoryPort``."""

    def __init__(
        self,
        signals: SqlAlchemySignalRepository,
        reservations: SqlAlchemyReservationRepository,
        attempts: SqlAlchemyExecutionAttemptRepository,
        ledger: SqlAlchemyLedgerRepository,
        proposals: SqlAlchemyBookingProposalRepository,
        enablement_log: SqlAlchemyEnablementLog,
    ) -> None:
        self._signals = signals
        self._reservations = reservations
        self._attempts = attempts
        self._ledger = ledger
        self._proposals = proposals
        self._enablement_log = enablement_log

    async def history(self, strategy_id: UUID) -> StrategyHistory:
        return StrategyHistory(
            signals=await self._signals.count_for_strategy(strategy_id),
            reservations=await self._reservations.count_for_strategy(strategy_id),
            execution_attempts=await self._attempts.count_for_strategy(strategy_id),
            ledger_entries=await self._ledger.count_for_strategy(strategy_id),
            booking_proposals=await self._proposals.count_for_strategy(strategy_id),
            enablement_events=await self._enablement_log.count_for(strategy_id),
        )
