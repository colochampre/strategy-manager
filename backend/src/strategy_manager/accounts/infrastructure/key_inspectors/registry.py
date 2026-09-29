"""Selects the key inspector for an exchange.

An exchange with no inspector raises. There is no fallback: inspecting a
Binance key with Bybit's rules, or not inspecting it at all, is the failure
this registry exists to prevent (the same reasoning as
``VenueExchangeRegistry``).
"""

from collections.abc import Mapping

from strategy_manager.accounts.application.ports import KeyInspectorPort
from strategy_manager.accounts.domain.key_policy import UnservedExchange


class KeyInspectorRegistry:
    def __init__(self, inspectors: Mapping[str, KeyInspectorPort]) -> None:
        self._inspectors = dict(inspectors)

    def for_exchange(self, exchange: str) -> KeyInspectorPort:
        try:
            return self._inspectors[exchange]
        except KeyError:
            raise UnservedExchange(
                f"no key inspector is registered for exchange {exchange!r}; "
                f"served: {sorted(self._inspectors)}"
            ) from None
