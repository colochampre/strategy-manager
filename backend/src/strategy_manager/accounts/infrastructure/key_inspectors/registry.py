"""Selects the key inspector for an exchange.

An exchange with no inspector raises. There is no fallback: inspecting a
Binance key with Bybit's rules, or not inspecting it at all, is the failure
this registry exists to prevent (the same reasoning as
``VenueExchangeRegistry``).
"""

from collections.abc import Mapping

from strategy_manager.accounts.application.ports import KeyInspectorPort
from strategy_manager.accounts.domain.key_policy import UnservedExchange
from strategy_manager.accounts.infrastructure.key_inspectors.binance import BinanceKeyInspector
from strategy_manager.accounts.infrastructure.key_inspectors.bybit import BybitKeyInspector
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.config import Settings


class KeyInspectorRegistry:
    def __init__(self, inspectors: Mapping[str, KeyInspectorPort]) -> None:
        self._inspectors = dict(inspectors)

    @classmethod
    def for_settings(cls, settings: Settings, clock: ClockPort) -> "KeyInspectorRegistry":
        """The two venues that can execute, inspected against their live APIs.
        Pionex is not here on purpose: it has no inspector (design § J, Q3)."""
        return cls(
            {
                "bybit": BybitKeyInspector.from_settings(settings, clock),
                "binance": BinanceKeyInspector.from_settings(settings, clock),
            }
        )

    def for_exchange(self, exchange: str) -> KeyInspectorPort:
        try:
            return self._inspectors[exchange]
        except KeyError:
            raise UnservedExchange(
                f"no key inspector is registered for exchange {exchange!r}; "
                f"served: {sorted(self._inspectors)}"
            ) from None
