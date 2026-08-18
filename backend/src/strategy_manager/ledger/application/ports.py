"""``LedgerRepositoryPort``: internal to ``ledger`` — ``execution`` never sees
it, only ``execution.application.ports.FillRecorderPort`` (design.md's
component inventory § ledger/application/ports.py).
"""

from typing import Protocol

from strategy_manager.ledger.domain.ledger_entry import LedgerEntry


class LedgerRepositoryPort(Protocol):
    """Insert-only by contract; the database enforces it below the
    application layer too (spec: trade-ledger § Append-Only Enforcement)."""

    async def insert(self, entry: LedgerEntry) -> None: ...
