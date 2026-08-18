"""A statically-configured implementation of ``UsdRateProviderPort``.

This is the only USD rate source in this change. A live-rate adapter is a
future concern; the port is defined now so callers never depend on the
concrete implementation.
"""

from collections.abc import Mapping
from decimal import Decimal

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency


class FixedUsdRateProvider:
    """Returns a fixed, pre-configured USD rate per currency."""

    def __init__(self, rates: Mapping[Currency, Decimal]) -> None:
        self._rates = dict(rates)

    async def usd_rate(self, currency: Currency) -> Decimal:
        try:
            return self._rates[currency]
        except KeyError as exc:
            raise InvariantViolation(
                f"No USD rate configured for currency '{currency}'"
            ) from exc
