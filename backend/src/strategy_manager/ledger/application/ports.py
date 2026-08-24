"""Ports internal to ``ledger``. ``execution`` never sees these — it knows
only ``execution.application.ports.FillRecorderPort`` and
``HeldPositionPort``, which ``RecordFill`` and ``ReadHeldBase`` implement
(design.md's component inventory § ledger/application/ports.py).
"""

from decimal import Decimal
from typing import Protocol
from uuid import UUID

from strategy_manager.ledger.domain.ledger_entry import LedgerEntry


class LedgerRepositoryPort(Protocol):
    """Insert-only by contract; the database enforces it below the
    application layer too (spec: trade-ledger § Append-Only Enforcement)."""

    async def insert(self, entry: LedgerEntry) -> None: ...


class LedgerPositionReaderPort(Protocol):
    """Reading the ledger is not in tension with its append-only rule — that
    rule governs writes, and rule 6 says positions are a projection *over*
    these rows. This port is deliberately separate from the write port so the
    insert-only guarantee stays visible in ``LedgerRepositoryPort``: no adapter
    gains a mutating method by acquiring a read.
    """

    async def net_base_quantity(
        self, allocation_id: UUID, base_currency: str
    ) -> Decimal: ...
