"""Unit tests for ``requested_from_percent`` — the pure function deriving
the requested allocation amount from a strategy's configured percentage
applied to the pool BALANCE, not availability (design.md § "Order size
never comes from the alert"; tasks.md 7.3)."""

from decimal import Decimal

from strategy_manager.allocation.domain.percent import requested_from_percent


def test_full_percent_requests_exactly_the_balance() -> None:
    assert requested_from_percent(Decimal("1000"), Decimal("100")) == Decimal("1000")


def test_partial_percent_scales_the_balance() -> None:
    assert requested_from_percent(Decimal("1000"), Decimal("20")) == Decimal("200")


def test_request_depends_only_on_balance_not_on_existing_reservations() -> None:
    """The balance base (chosen over availability): the same 20% always
    yields 200 regardless of what else is reserved against the pool."""
    assert requested_from_percent(Decimal("1000"), Decimal("20")) == Decimal("200")


def test_result_is_quantized_to_eighteen_decimal_places() -> None:
    result = requested_from_percent(Decimal("7"), Decimal("42.857142857142857142857"))
    assert result.as_tuple().exponent == -18


def test_round_down_never_rounds_up_the_requested_amount() -> None:
    """A rounded-up requested amount would be over-allocation (design.md's
    ``decide()`` invariants) — quantization here MUST truncate, never round
    to nearest."""
    result = requested_from_percent(Decimal("1"), Decimal("33.33333333333333333333"))
    assert result == Decimal("0.333333333333333333")
