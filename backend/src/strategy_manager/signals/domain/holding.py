"""Domain types for the Existing-Position Guard (spec: capital-allocation §
Existing-Position Guard; design.md's component inventory §
signals/domain/holding.py).

Pure Decimal arithmetic, no I/O -- this module never imports SQLAlchemy or
any port, so the classification logic that will live here (S4's
``classify_orphan``, not this slice) can be exhaustively unit-tested without
a database or a venue call.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from uuid import UUID


@dataclass(frozen=True, slots=True)
class HeldAllocation:
    """One allocation still open on a symbol, as the ledger sees it -- one
    row per ``(strategy_id, allocation_id)`` group returned by
    ``SqlAlchemyLedgerRepository.symbol_holdings()``.

    ``net_base`` is that allocation's own signed net base quantity, using the
    same fee rule ``ClosePosition`` and ``ReadHeldBase`` use
    (``base_currency_of``) -- so this number is exactly what a close of that
    allocation would size against. Positive is long, negative is short,
    never zero: a fully closed allocation is dropped by the query's
    ``HAVING`` filter rather than surfacing here with nothing in it.
    """

    strategy_id: UUID
    allocation_id: UUID
    net_base: Decimal


class OrphanKind(Enum):
    """How a divergent holding (ledger and venue disagree) is classified.

    Only ``REAL`` is ever acted on. The arithmetic that tells the three
    apart (``classify_orphan``) is S4 scope and is not declared here.
    """

    REAL = "REAL"
    GHOST = "GHOST"
    AMBIGUOUS = "AMBIGUOUS"
