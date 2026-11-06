"""The leverage a probe opens at: the one the pair already holds on the venue.

Since decision 38 the production adapter SETS the spec's leverage before a
live opening. A probe that previews through that adapter asks for the leverage
the pair already holds, so the preview changes nothing on the account and the
order is sized as before, at the account's own leverage.
"""

from decimal import Decimal

from strategy_manager.shared.domain.leverage import MAX_LEVERAGE, Leverage


def held_leverage(venue: Decimal) -> Leverage | None:
    """The pair's own leverage as a ``Leverage``, or None when it sits at one
    this system cannot ask for (a fraction, or outside 1..20): asking for any
    other would make the adapter change the pair."""
    if venue != venue.to_integral_value() or not 1 <= venue <= MAX_LEVERAGE:
        return None
    return Leverage(int(venue))
