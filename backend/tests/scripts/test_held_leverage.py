"""The leverage a probe opens at: the one the pair already holds.

Since decision 38 the production adapter SETS the spec's leverage before an
opening, so a probe that builds through it must ask for the leverage the pair
already holds, or its preview would change the account.
"""

from decimal import Decimal

import pytest
from held_leverage import held_leverage

from strategy_manager.shared.domain.leverage import Leverage


@pytest.mark.parametrize(
    ("venue", "expected"),
    [(Decimal("1"), 1), (Decimal("3.00"), 3), (Decimal("20"), 20)],
)
def test_a_whole_leverage_from_one_to_twenty_is_asked_as_it_is(
    venue: Decimal, expected: int
) -> None:
    assert held_leverage(venue) == Leverage(expected)


@pytest.mark.parametrize("venue", [Decimal("2.5"), Decimal("21"), Decimal("0"), Decimal("125")])
def test_a_leverage_this_system_cannot_ask_for_is_none(venue: Decimal) -> None:
    """Asking for anything else would make the adapter change the pair."""
    assert held_leverage(venue) is None
