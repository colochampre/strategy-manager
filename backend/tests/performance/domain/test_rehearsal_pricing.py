"""Unit tests: ``classify_rehearsal_pricing`` -- how a rehearsal operation's
opening fills were priced, told from the fills' own ``price`` and the price its
alert carried (design.md, addendum "a strategy's operations", section C).

Every case is an exact ``Decimal`` comparison on stored values. The derived
average entry price is never involved: it can differ from its only fill in the
last places, and an exact comparison would then fail for a small quantity.
"""

from decimal import Decimal

from strategy_manager.performance.domain.closed_trade import Direction
from strategy_manager.performance.domain.operation import (
    PricingFacts,
    RehearsalPricing,
    SidePrices,
    classify_rehearsal_pricing,
)

ONE = Decimal("1")
ALERT_PRICE = Decimal("0.4512")


def _prices(lowest: str, highest: str | None = None) -> SidePrices:
    return SidePrices(lowest=Decimal(lowest), highest=Decimal(highest or lowest))


def test_filled_at_one_against_another_alert_price_is_fixed_one() -> None:
    facts = PricingFacts(alert_price=ALERT_PRICE, buy=_prices("1"), sell=_prices("1"))

    assert classify_rehearsal_pricing(Direction.LONG, facts) is RehearsalPricing.FIXED_ONE


def test_filled_at_the_alerts_price_is_alert() -> None:
    facts = PricingFacts(alert_price=ALERT_PRICE, buy=_prices("0.4512"), sell=_prices("0.4512"))

    assert classify_rehearsal_pricing(Direction.LONG, facts) is RehearsalPricing.ALERT


def test_an_alert_priced_exactly_one_reads_alert() -> None:
    facts = PricingFacts(alert_price=ONE, buy=_prices("1"), sell=_prices("1"))

    assert classify_rehearsal_pricing(Direction.LONG, facts) is RehearsalPricing.ALERT


def test_a_fill_at_neither_price_is_undetermined() -> None:
    facts = PricingFacts(alert_price=ALERT_PRICE, buy=_prices("0.45"), sell=_prices("0.45"))

    assert classify_rehearsal_pricing(Direction.LONG, facts) is RehearsalPricing.UNDETERMINED


def test_opening_fills_at_different_prices_are_undetermined() -> None:
    """Lowest 1 and highest 0.4512 with an alert of 0.4512: not every opening fill
    is at 1 and not every one is at the alert's price."""
    facts = PricingFacts(alert_price=ALERT_PRICE, buy=_prices("1", "0.4512"), sell=_prices("1"))

    assert classify_rehearsal_pricing(Direction.LONG, facts) is RehearsalPricing.UNDETERMINED


def test_opening_fills_whose_lowest_is_the_alert_and_highest_is_one_are_undetermined() -> None:
    facts = PricingFacts(alert_price=ALERT_PRICE, buy=_prices("0.4512", "1"), sell=_prices("1"))

    assert classify_rehearsal_pricing(Direction.LONG, facts) is RehearsalPricing.UNDETERMINED


def test_only_the_opening_side_decides() -> None:
    """Opened at 1 and closed at the alert's price (a position that straddles the
    day the simulated exchange began to fill at the alert's price)."""
    facts = PricingFacts(alert_price=ALERT_PRICE, buy=_prices("1"), sell=_prices("0.4512"))

    assert classify_rehearsal_pricing(Direction.LONG, facts) is RehearsalPricing.FIXED_ONE


def test_a_shorts_opening_side_is_its_sell_side() -> None:
    fixed = PricingFacts(alert_price=ALERT_PRICE, buy=_prices("0.4512"), sell=_prices("1"))
    alert = PricingFacts(alert_price=ALERT_PRICE, buy=_prices("1"), sell=_prices("0.4512"))

    assert classify_rehearsal_pricing(Direction.SHORT, fixed) is RehearsalPricing.FIXED_ONE
    assert classify_rehearsal_pricing(Direction.SHORT, alert) is RehearsalPricing.ALERT


def test_missing_facts_are_undetermined() -> None:
    no_opening_side = PricingFacts(alert_price=ALERT_PRICE, buy=None, sell=_prices("1"))
    no_opening_side_for_a_short = PricingFacts(alert_price=ALERT_PRICE, buy=_prices("1"), sell=None)

    assert (
        classify_rehearsal_pricing(Direction.LONG, no_opening_side) is RehearsalPricing.UNDETERMINED
    )
    assert (
        classify_rehearsal_pricing(Direction.SHORT, no_opening_side_for_a_short)
        is RehearsalPricing.UNDETERMINED
    )
