"""Unit tests for the reconciliation position value objects (spec:
reconciliation-scan; design.md's component inventory §
reconciliation/domain/positions.py).
"""

from decimal import Decimal
from uuid import uuid4

from strategy_manager.reconciliation.domain.positions import (
    LedgerPosition,
    OpenAllocation,
    VenuePosition,
)


def test_venue_position_carries_a_signed_net_base() -> None:
    short = VenuePosition(symbol="BTCUSDT.P", net_base=Decimal("-0.5"))

    assert short.net_base == Decimal("-0.5")


def test_ledger_position_net_base_sums_every_open_allocation() -> None:
    allocation_a = OpenAllocation(allocation_id=uuid4(), net_base=Decimal("0.3"))
    allocation_b = OpenAllocation(allocation_id=uuid4(), net_base=Decimal("0.2"))
    ledger = LedgerPosition(symbol="SOLUSDT.P", open_allocations=(allocation_a, allocation_b))

    assert ledger.net_base == Decimal("0.5")


def test_ledger_position_net_base_is_zero_when_nothing_is_open() -> None:
    ledger = LedgerPosition(symbol="SFPUSDT.P", open_allocations=())

    assert ledger.net_base == Decimal("0")


def test_ledger_position_net_base_sums_signed_quantities_for_a_short() -> None:
    """Positions are signed; a short reduces the aggregate below zero."""
    allocation = OpenAllocation(allocation_id=uuid4(), net_base=Decimal("-0.4"))
    ledger = LedgerPosition(symbol="ETHUSDT.P", open_allocations=(allocation,))

    assert ledger.net_base == Decimal("-0.4")


def test_ledger_position_allocation_ids_preserves_order() -> None:
    id_a, id_b = uuid4(), uuid4()
    ledger = LedgerPosition(
        symbol="SOLUSDT.P",
        open_allocations=(
            OpenAllocation(allocation_id=id_a, net_base=Decimal("0.1")),
            OpenAllocation(allocation_id=id_b, net_base=Decimal("0.2")),
        ),
    )

    assert ledger.allocation_ids == (id_a, id_b)
