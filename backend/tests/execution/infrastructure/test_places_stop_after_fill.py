"""``places_stop_after_fill`` on the adapter contract (subscriber-safety SS.6).

Binance has no stop on the opening order, so it places one after the fill. Every other
adapter either carries the stop on the order (Bybit), is outside the protective stop (Pionex
spot, D9), cannot run (Pionex futures) or places nothing (the simulated exchange). A flag
that defaulted to True anywhere else would make ``PlaceOrder`` write a ``PENDING`` row nobody
confirms, which reads as a protected position.

The after-fill calls of an adapter that does not place one are refused loudly rather than
answering something: they are never asked.
"""

from decimal import Decimal

import pytest

from strategy_manager.execution.application.ports import ExchangeError
from strategy_manager.execution.domain.protective_stop import PositionSide
from strategy_manager.execution.infrastructure.binance_futures_exchange import (
    BinanceFuturesExchangeAdapter,
)
from strategy_manager.execution.infrastructure.bybit_futures_exchange import (
    BybitFuturesExchangeAdapter,
)
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.pionex_exchange import PionexExchangeAdapter
from strategy_manager.execution.infrastructure.pionex_futures_exchange import (
    PionexFuturesExchangeAdapter,
)

_NOT_AFTER_FILL = [
    BybitFuturesExchangeAdapter,
    PionexExchangeAdapter,
    PionexFuturesExchangeAdapter,
    FakeExchangeAdapter,
]


@pytest.mark.parametrize("adapter", _NOT_AFTER_FILL, ids=lambda a: a.__name__)
def test_every_other_adapter_places_no_stop_after_the_fill(adapter: type) -> None:
    assert getattr(adapter, "places_stop_after_fill", None) is False


def test_binance_is_the_only_adapter_that_does() -> None:
    assert BinanceFuturesExchangeAdapter.places_stop_after_fill is True


@pytest.mark.parametrize("adapter", _NOT_AFTER_FILL, ids=lambda a: a.__name__)
async def test_an_adapter_that_places_none_refuses_the_after_fill_calls(adapter: type) -> None:
    # The calls refuse before they touch ``self``, so no client is needed to build one.
    instance = adapter.__new__(adapter)

    with pytest.raises(ExchangeError):
        await instance.stop_trigger_price(
            "DOGEUSDT", PositionSide.LONG, Decimal("1"), Decimal("10")
        )
    with pytest.raises(ExchangeError):
        await instance.place_stop("DOGEUSDT", PositionSide.LONG, Decimal("1"), "id")
    with pytest.raises(ExchangeError):
        await instance.find_stop("DOGEUSDT", "id")
