"""Unit tests for ``Reservation`` state transitions — legal moves accepted,
illegal moves rejected (tasks.md 4.5)."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue

_KEY = PoolKey(exchange=Exchange.PIONEX, venue=Venue.SPOT, settlement_currency=Currency.USDT)


def _reservation(status: ReservationStatus = ReservationStatus.PENDING) -> Reservation:
    return Reservation(
        id=uuid4(),
        strategy_id=uuid4(),
        signal_id=uuid4(),
        pool_key=_KEY,
        amount=Decimal("100"),
        status=status,
        expires_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (ReservationStatus.PENDING, ReservationStatus.SUBMITTED),
        (ReservationStatus.PENDING, ReservationStatus.RELEASED),
        (ReservationStatus.PENDING, ReservationStatus.EXPIRED),
        (ReservationStatus.SUBMITTED, ReservationStatus.FILLED),
        (ReservationStatus.SUBMITTED, ReservationStatus.RELEASED),
        (ReservationStatus.SUBMITTED, ReservationStatus.EXPIRED),
    ],
)
def test_legal_transitions_are_accepted(
    start: ReservationStatus, target: ReservationStatus
) -> None:
    reservation = _reservation(start)

    transitioned = reservation.transition_to(target)

    assert transitioned.status is target
    assert transitioned.id == reservation.id  # identity preserved


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (ReservationStatus.PENDING, ReservationStatus.FILLED),  # must go through SUBMITTED
        (ReservationStatus.SUBMITTED, ReservationStatus.PENDING),  # never backward
        (ReservationStatus.FILLED, ReservationStatus.RELEASED),  # terminal
        (ReservationStatus.RELEASED, ReservationStatus.PENDING),  # terminal
        (ReservationStatus.EXPIRED, ReservationStatus.SUBMITTED),  # terminal
    ],
)
def test_illegal_transitions_are_rejected(
    start: ReservationStatus, target: ReservationStatus
) -> None:
    reservation = _reservation(start)

    with pytest.raises(InvariantViolation):
        reservation.transition_to(target)


def test_transition_returns_a_new_object_original_is_unchanged() -> None:
    reservation = _reservation(ReservationStatus.PENDING)

    transitioned = reservation.transition_to(ReservationStatus.SUBMITTED)

    assert reservation.status is ReservationStatus.PENDING
    assert transitioned.status is ReservationStatus.SUBMITTED
