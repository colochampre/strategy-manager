"""Value objects describing one symbol's position on both sides of a
reconciliation scan (design.md's component inventory § reconciliation/domain
/positions.py; spec: reconciliation-scan).

No framework imports, no I/O, no clock: everything a caller needs is passed
in, mirroring ``allocation.domain.decision``'s pure-function shape.

Positions are SIGNED — short is negative. The venue runs one-way
(``BUYSELL``) position mode (CLAUDE.md's futures execution notes), so it
holds exactly ONE net position per symbol; that single number is what
``VenuePosition.net_base`` carries.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class OpenAllocation:
    """One allocation still open against a symbol, as the ledger sees it.

    ``net_base`` is that allocation's own signed net base quantity — the sum
    of its fills so far, long positive and short negative.
    """

    allocation_id: UUID
    net_base: Decimal


@dataclass(frozen=True, slots=True)
class VenuePosition:
    """The venue's own reported net position for one symbol, read live from
    the exchange at scan time."""

    symbol: str
    net_base: Decimal


@dataclass(frozen=True, slots=True)
class LedgerPosition:
    """The ledger's view of the same symbol: every allocation still open on
    it. ``net_base`` is the sum of every ``OpenAllocation.net_base`` — the
    single number ``classify()`` compares against the venue's, never
    re-derived anywhere else.
    """

    symbol: str
    open_allocations: tuple[OpenAllocation, ...]

    @property
    def net_base(self) -> Decimal:
        return sum((a.net_base for a in self.open_allocations), start=_ZERO)

    @property
    def allocation_ids(self) -> tuple[UUID, ...]:
        """Mirrors ``reconciliation_discrepancies.open_allocation_ids`` —
        the allocations open at the moment of this observation, captured so
        a later scan's ledger state cannot retroactively change what an
        earlier CONFIRMED row says it acted on."""

        return tuple(allocation.allocation_id for allocation in self.open_allocations)
