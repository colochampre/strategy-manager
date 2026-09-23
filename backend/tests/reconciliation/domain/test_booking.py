"""Unit tests for the pure booking domain (design.md's component inventory §
reconciliation/domain/booking.py; design decisions 4, 5, 13; Unit 4a of
tasks.md).

No DB, no I/O -- mirrors ``test_classify.py``'s pure-function shape exactly.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from strategy_manager.reconciliation.domain.booking import (
    BOOKABLE_KINDS,
    BookingState,
    MatchedBooking,
    MatchRefusalReason,
    MatchRefused,
    ProposedFill,
    build_client_order_id,
    canonical_order,
    match_fills,
)
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind
from strategy_manager.shared.domain.errors import InvariantViolation

_FILLED_AT = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)


def _fill(
    *,
    exchange_fill_id: str,
    exchange_order_id: str | None = "ORDER-1",
    side: str = "BUY",
    quantity: str = "0.5",
    price: str = "142.37",
    fee: str = "0",
    fee_currency: str = "USDT",
    filled_at: datetime = _FILLED_AT,
) -> ProposedFill:
    return ProposedFill(
        exchange_fill_id=exchange_fill_id,
        exchange_order_id=exchange_order_id,
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal(fee),
        fee_currency=fee_currency,
        filled_at=filled_at,
    )


# --- BOOKABLE_KINDS -----------------------------------------------------


def test_bookable_kinds_excludes_ambiguous_and_unmatched() -> None:
    """design.md § 14: only the two attributable verdicts are ever
    proposable; the database's own CHECK is the real guard, this constant
    is what a caller checks first."""
    assert BOOKABLE_KINDS == {
        DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
        DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
    }
    assert DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE not in BOOKABLE_KINDS
    assert DiscrepancyKind.NO_MATCHING_ALLOCATION not in BOOKABLE_KINDS


def test_booking_state_mirrors_the_five_database_states() -> None:
    assert {state.value for state in BookingState} == {
        "PENDING",
        "APPROVED",
        "REJECTED",
        "SUPERSEDED",
        "EXPIRED",
    }


# --- match_fills: the happy path and the four refusals ------------------


def test_match_fills_sum_equals_delta() -> None:
    """The unrecorded fills' signed sum equals the observed delta exactly:
    a long grew by 0.5, so two BUY fills summing to 0.5 match."""
    fills = [
        _fill(exchange_fill_id="F1", side="BUY", quantity="0.3"),
        _fill(exchange_fill_id="F2", side="BUY", quantity="0.2"),
    ]

    result = match_fills(Decimal("0.5"), fills, frozenset(), "USDT")

    assert isinstance(result, MatchedBooking)
    assert result.side == "BUY"
    assert [f.exchange_fill_id for f in result.fills] == ["F1", "F2"]


def test_match_fills_refuses_mixed_sides() -> None:
    fills = [
        _fill(exchange_fill_id="F1", side="BUY", quantity="0.3"),
        _fill(exchange_fill_id="F2", side="SELL", quantity="0.1"),
    ]

    result = match_fills(Decimal("0.2"), fills, frozenset(), "USDT")

    assert isinstance(result, MatchRefused)
    assert result.reason == MatchRefusalReason.MIXED_SIDES


def test_match_fills_refuses_zero_unrecorded() -> None:
    """Every candidate fill is already in ``already_recorded_ids`` -- there
    is nothing left to match, and this is a refusal, not a vacuous match."""
    fills = [_fill(exchange_fill_id="F1", side="BUY", quantity="0.5")]

    result = match_fills(Decimal("0.5"), fills, frozenset({"F1"}), "USDT")

    assert isinstance(result, MatchRefused)
    assert result.reason == MatchRefusalReason.ZERO_UNRECORDED


def test_match_fills_refuses_nonpositive_quantity() -> None:
    fills = [_fill(exchange_fill_id="F1", side="BUY", quantity="0")]

    result = match_fills(Decimal("0"), fills, frozenset(), "USDT")

    assert isinstance(result, MatchRefused)
    assert result.reason == MatchRefusalReason.NONPOSITIVE_QUANTITY


def test_match_fills_refuses_when_unrecorded_side_contradicts_delta_sign() -> None:
    """design.md § 5's fourth condition, made explicit: a delta demanding a
    SELL (a short growing more negative, or a long shrinking) can never be
    satisfied by unrecorded fills that are all BUY -- a sum of same-signed
    contributions cannot equal an oppositely-signed delta. This is still a
    ``SUM_MISMATCH``, not a separate refusal reason."""
    fills = [_fill(exchange_fill_id="F1", side="BUY", quantity="0.5")]

    result = match_fills(Decimal("-0.5"), fills, frozenset(), "USDT")

    assert isinstance(result, MatchRefused)
    assert result.reason == MatchRefusalReason.SUM_MISMATCH


def test_match_fills_excludes_already_recorded_fills_before_summing() -> None:
    """A fill the ledger already holds must not be double-counted into the
    sum -- if it were, this would wrongly match on a sum of 1.0 instead of
    refusing on the true unrecorded sum of 0.3."""
    fills = [
        _fill(exchange_fill_id="ALREADY-RECORDED", side="BUY", quantity="0.7"),
        _fill(exchange_fill_id="F1", side="BUY", quantity="0.3"),
    ]

    result = match_fills(Decimal("0.3"), fills, frozenset({"ALREADY-RECORDED"}), "USDT")

    assert isinstance(result, MatchedBooking)
    assert [f.exchange_fill_id for f in result.fills] == ["F1"]


# --- match_fills: the fee rule, identical to ReadSymbolPositions's own ---


def test_match_fills_fee_is_a_no_op_when_paid_in_the_settlement_currency() -> None:
    """Design decision 5, provably a no-op on USDT-M: a fee paid in the
    pool's OWN settlement currency must not touch the matched sum."""
    fills = [
        _fill(
            exchange_fill_id="F1",
            side="BUY",
            quantity="0.5",
            fee="0.05",
            fee_currency="USDT",
        )
    ]

    result = match_fills(Decimal("0.5"), fills, frozenset(), "USDT")

    assert isinstance(result, MatchedBooking)


def test_match_fills_fee_reduces_the_sum_when_paid_off_the_settlement_currency() -> None:
    """The load-bearing half of the identical rule: a fee NOT in the
    settlement currency subtracts from the signed contribution -- here a
    0.5 BUY with a 0.002 fee in the base currency nets to 0.498, so a delta
    of exactly 0.5 must now REFUSE rather than match."""
    fills = [
        _fill(
            exchange_fill_id="F1",
            side="BUY",
            quantity="0.5",
            fee="0.002",
            fee_currency="SOL",
        )
    ]

    result = match_fills(Decimal("0.5"), fills, frozenset(), "USDT")
    assert isinstance(result, MatchRefused)
    assert result.reason == MatchRefusalReason.SUM_MISMATCH

    matched = match_fills(Decimal("0.498"), fills, frozenset(), "USDT")
    assert isinstance(matched, MatchedBooking)


def test_match_fills_fee_currency_comparison_is_case_insensitive() -> None:
    """Mirrors ``SqlAlchemyLedgerRepository.net_positions_by_symbol``'s own
    ``func.upper(...)`` comparison -- a lowercase echo of the settlement
    currency must still be treated as a match, not as "different", or the
    fee would be wrongly subtracted."""
    fills = [
        _fill(
            exchange_fill_id="F1",
            side="BUY",
            quantity="0.5",
            fee="0.05",
            fee_currency="usdt",
        )
    ]

    result = match_fills(Decimal("0.5"), fills, frozenset(), "USDT")

    assert isinstance(result, MatchedBooking)


# --- canonical_order: the (len, id) tiebreak, both venues' id shapes ----


def test_canonical_fill_ordering_len_then_id_tiebreak_binance_integer_ids() -> None:
    """Binance trade ids are integer-valued strings: a plain string compare
    puts "10" before "9" (``"1" < "9"``), which is wrong order. The
    ``(len(id), id)`` tiebreak restores numeric order."""
    fills = [
        _fill(exchange_fill_id="10", filled_at=_FILLED_AT),
        _fill(exchange_fill_id="9", filled_at=_FILLED_AT),
        _fill(exchange_fill_id="100", filled_at=_FILLED_AT),
    ]

    ordered = canonical_order(fills)

    assert [f.exchange_fill_id for f in ordered] == ["9", "10", "100"]


def test_canonical_fill_ordering_len_then_id_tiebreak_bybit_string_ids() -> None:
    """Bybit ``execId`` strings are opaque, same-length numeric-looking
    strings with no ordering guarantee of their own -- the tiebreak still
    produces a TOTAL, deterministic order (here, equal to lexicographic
    order because both ids share one length)."""
    fills = [
        _fill(exchange_fill_id="2290000000068668501", filled_at=_FILLED_AT),
        _fill(exchange_fill_id="2290000000068668500", filled_at=_FILLED_AT),
    ]

    ordered = canonical_order(fills)

    assert [f.exchange_fill_id for f in ordered] == [
        "2290000000068668500",
        "2290000000068668501",
    ]


def test_canonical_fill_ordering_is_primarily_by_filled_at() -> None:
    later = _FILLED_AT.replace(minute=5)
    fills = [
        _fill(exchange_fill_id="ZZZ", filled_at=later),
        _fill(exchange_fill_id="AAA", filled_at=_FILLED_AT),
    ]

    ordered = canonical_order(fills)

    assert [f.exchange_fill_id for f in ordered] == ["AAA", "ZZZ"]


# --- build_client_order_id: the vnu: id and its fallback ----------------


def test_client_order_id_is_the_earliest_fill_even_when_an_order_id_exists() -> None:
    fills = [_fill(exchange_fill_id="F1", exchange_order_id="ORDER-123")]

    client_order_id = build_client_order_id("bybit", fills)

    assert client_order_id == "vnu:bybit:fill:F1"


def test_client_order_id_keys_off_the_earliest_fill_under_canonical_order() -> None:
    later = _FILLED_AT.replace(minute=5)
    fills = [
        _fill(exchange_fill_id="LATER", exchange_order_id=None, filled_at=later),
        _fill(exchange_fill_id="EARLIER", exchange_order_id=None, filled_at=_FILLED_AT),
    ]

    client_order_id = build_client_order_id("binance", fills)

    assert client_order_id == "vnu:binance:fill:EARLIER"


def test_two_bookings_of_one_partially_filled_order_get_distinct_ids() -> None:
    """One venue order filling across two scans yields two bookings. Keyed
    on the order id they would share one client_order_id, and the second
    approval would collide and be read as a harmless replay: SUPERSEDED,
    zero writes, that close never bookable. A fill is recorded at most once,
    so the earliest unrecorded fill identifies exactly one booking."""
    later = _FILLED_AT.replace(minute=5)
    first_booking = [_fill(exchange_fill_id="F1", exchange_order_id="ORDER-X")]
    second_booking = [
        _fill(exchange_fill_id="F2", exchange_order_id="ORDER-X", filled_at=later)
    ]

    assert build_client_order_id("bybit", first_booking) != build_client_order_id(
        "bybit", second_booking
    )


def test_client_order_id_raises_on_empty_fills() -> None:
    with pytest.raises(InvariantViolation):
        build_client_order_id("bybit", [])
