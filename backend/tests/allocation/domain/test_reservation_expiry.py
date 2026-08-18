"""Domain rules the sweeper depends on: which reservations are sweepable, and
what expiring one actually records (spec: capital-allocation § Reservation
Expiry; tasks.md 6.1).

A reservation that was granted but never executed keeps counting against
``reserved_active`` until it passes ``expires_at``. Giving it a terminal status
is what makes that visible instead of silent.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.reservation import (
    ReleaseReason,
    Reservation,
    ReservationStatus,
)
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Venue

NOW = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
POOL = PoolKey(venue=Venue.SPOT, settlement_currency=Currency.USDT)


def _reservation(
    status: ReservationStatus, *, expires_at: datetime = NOW - timedelta(seconds=1)
) -> Reservation:
    return Reservation(
        id=uuid4(),
        strategy_id=uuid4(),
        signal_id=uuid4(),
        pool_key=POOL,
        amount=Decimal("100"),
        status=status,
        expires_at=expires_at,
    )


@pytest.mark.parametrize("status", [ReservationStatus.PENDING, ReservationStatus.SUBMITTED])
def test_active_reservation_past_its_ttl_is_sweepable(status: ReservationStatus) -> None:
    assert _reservation(status).is_sweepable(NOW) is True


@pytest.mark.parametrize("status", [ReservationStatus.PENDING, ReservationStatus.SUBMITTED])
def test_active_reservation_still_within_its_ttl_is_not_sweepable(
    status: ReservationStatus,
) -> None:
    reservation = _reservation(status, expires_at=NOW + timedelta(seconds=1))
    assert reservation.is_sweepable(NOW) is False


@pytest.mark.parametrize(
    "status",
    [ReservationStatus.FILLED, ReservationStatus.RELEASED, ReservationStatus.EXPIRED],
)
def test_a_terminal_reservation_is_never_sweepable(status: ReservationStatus) -> None:
    """Constraint 5: never touch a reservation that already reached a terminal
    status, however far past its ``expires_at`` it is."""

    reservation = _reservation(status, expires_at=NOW - timedelta(days=365))
    assert reservation.is_sweepable(NOW) is False


def test_expiring_exactly_at_expires_at_is_sweepable() -> None:
    """The boundary belongs to the sweeper: ``sum_active`` already excludes a
    reservation once ``expires_at > now`` is false, so a row sitting exactly on
    the boundary is no longer holding capital and must be able to reach a
    terminal status."""

    assert _reservation(ReservationStatus.PENDING, expires_at=NOW).is_sweepable(NOW) is True


def test_expire_records_the_terminal_timestamp_and_reason() -> None:
    expired = _reservation(ReservationStatus.PENDING).expire(NOW)

    assert expired.status is ReservationStatus.EXPIRED
    assert expired.terminal_at == NOW
    assert expired.release_reason is ReleaseReason.EXPIRED_BY_SWEEPER


def test_expire_leaves_the_original_untouched() -> None:
    original = _reservation(ReservationStatus.SUBMITTED)
    original.expire(NOW)

    assert original.status is ReservationStatus.SUBMITTED
    assert original.terminal_at is None


@pytest.mark.parametrize(
    "status",
    [ReservationStatus.FILLED, ReservationStatus.RELEASED, ReservationStatus.EXPIRED],
)
def test_expiring_a_terminal_reservation_is_an_invariant_violation(
    status: ReservationStatus,
) -> None:
    """Re-expiring must raise, not silently no-op — a sweeper that can
    resurrect a FILLED reservation would rewrite settled history."""

    with pytest.raises(InvariantViolation):
        _reservation(status).expire(NOW)
