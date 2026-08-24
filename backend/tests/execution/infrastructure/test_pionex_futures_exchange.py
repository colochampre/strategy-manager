"""The live futures ``ExchangePort`` adapter.

Two things are being pinned here. One is the sizing: margin times leverage,
truncated down, refused rather than guessed if the leverage cannot be read.
The other is the definitive-versus-ambiguous rule inherited from spot, which
decides whether a failed order releases reserved capital or leaves it held.
"""

from decimal import Decimal

import pytest

from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    ExchangeError,
    OpenOrderSpec,
    OrderNotFound,
)
from strategy_manager.execution.domain.futures_order import FuturesMarketOrder
from strategy_manager.execution.domain.order import MarketBuy, OrderSide
from strategy_manager.execution.infrastructure.pionex_futures_exchange import (
    PionexFuturesExchangeAdapter,
)
from strategy_manager.shared.domain.money import Venue
from strategy_manager.shared.infrastructure.pionex.errors import (
    PionexApiError,
    PionexOrderNotFound,
)
from strategy_manager.shared.infrastructure.pionex.fills import PionexFill
from strategy_manager.shared.infrastructure.pionex.futures_trade_client import (
    PionexOrderAck,
)
from strategy_manager.shared.infrastructure.pionex.perp_symbols import PerpRules

CLIENT_ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
SYMBOL = "BTC_USDT_PERP"

# BTC_USDT_PERP exactly as the live account reported it on 2026-08-24.
LIVE_RULES = PerpRules(
    symbol=SYMBOL,
    base_precision=4,
    base_step=Decimal("0.0001"),
    min_notional=Decimal("1"),
    min_size_market=Decimal("0.0001"),
    max_size_market=Decimal("100"),
    status="TRADING",
)


class FakeFuturesClient:
    def __init__(
        self,
        *,
        leverage: Decimal = Decimal("5"),
        rules: PerpRules = LIVE_RULES,
        leverage_raises: Exception | None = None,
        place_raises: Exception | None = None,
        lookup_raises: Exception | None = None,
        fills: list[PionexFill] | None = None,
    ) -> None:
        self.orders: list[dict[str, object]] = []
        self._leverage = leverage
        self._rules = rules
        self._leverage_raises = leverage_raises
        self._place_raises = place_raises
        self._lookup_raises = lookup_raises
        self._fills = fills or []

    async def leverage_for(self, symbol: str) -> Decimal:
        if self._leverage_raises is not None:
            raise self._leverage_raises
        return self._leverage

    async def perp_rules(self, symbol: str) -> PerpRules:
        return self._rules

    async def place_market_order(
        self,
        *,
        symbol: str,
        client_order_id: str,
        side: str,
        base_size: Decimal,
        reduce_only: bool,
        reference_price: Decimal | None,
    ) -> PionexOrderAck:
        if self._place_raises is not None:
            raise self._place_raises
        self.orders.append(
            {
                "symbol": symbol,
                "side": side,
                "base_size": base_size,
                "reduce_only": reduce_only,
                "reference_price": reference_price,
            }
        )
        return PionexOrderAck(order_id="FX-1", client_order_id=client_order_id)

    async def order_id_for(self, client_order_id: str) -> str:
        if self._lookup_raises is not None:
            raise self._lookup_raises
        return "FX-1"

    async def fills_for_order(self, order_id: str) -> list[PionexFill]:
        return self._fills


def _adapter(client: FakeFuturesClient) -> PionexFuturesExchangeAdapter:
    return PionexFuturesExchangeAdapter(client)  # type: ignore[arg-type]


def _open(side: OrderSide = OrderSide.BUY, granted: str = "100") -> OpenOrderSpec:
    return OpenOrderSpec(
        client_order_id=CLIENT_ORDER_ID,
        symbol=SYMBOL,
        side=side,
        granted=Decimal(granted),
        price=Decimal("64000"),
    )


def test_the_adapter_is_live_and_serves_only_usdt_m() -> None:
    """Coin-margined perpetuals reach the same API, but they settle in
    currencies no capital pool can hold yet. Declaring coin-m here would let a
    signal route to an adapter whose orders nothing can fund."""
    assert PionexFuturesExchangeAdapter.is_live is True
    assert PionexFuturesExchangeAdapter.venues == frozenset({Venue.USDT_M.value})


async def test_an_opening_order_is_margin_times_leverage_over_price() -> None:
    """100 USDT of margin at 5x on a 64000 market is 500 USDT of notional,
    which is 0.0078125 BTC -- truncated to 0.0078 at a step of 0.0001."""
    adapter = _adapter(FakeFuturesClient(leverage=Decimal("5")))

    order = await adapter.build_open_order(_open())

    assert isinstance(order, FuturesMarketOrder)
    assert order.base_size == Decimal("0.0078")
    assert order.leverage == Decimal("5")
    assert order.reduce_only is False


async def test_the_leverage_actually_changes_the_size() -> None:
    """The regression that costs the whole multiple: at 20x the same grant
    must buy four times the position it buys at 5x."""
    at_5x = await _adapter(FakeFuturesClient(leverage=Decimal("5"))).build_open_order(
        _open()
    )
    at_20x = await _adapter(FakeFuturesClient(leverage=Decimal("20"))).build_open_order(
        _open()
    )

    assert isinstance(at_5x, FuturesMarketOrder)
    assert isinstance(at_20x, FuturesMarketOrder)
    assert at_20x.base_size == Decimal("0.0312")
    assert at_20x.base_size == at_5x.base_size * 4


async def test_an_unreadable_leverage_refuses_the_order_rather_than_guessing() -> None:
    """A default here would size a position at the wrong multiple of the
    capital actually reserved, silently, visible only as an inexplicable
    balance."""
    adapter = _adapter(
        FakeFuturesClient(leverage_raises=PionexApiError("leverage unavailable"))
    )

    with pytest.raises(PionexApiError):
        await adapter.build_open_order(_open())


async def test_a_short_is_opened_with_the_same_arithmetic_as_a_long() -> None:
    adapter = _adapter(FakeFuturesClient())

    long_order = await adapter.build_open_order(_open(OrderSide.BUY))
    short_order = await adapter.build_open_order(_open(OrderSide.SELL))

    assert isinstance(long_order, FuturesMarketOrder)
    assert isinstance(short_order, FuturesMarketOrder)
    assert long_order.base_size == short_order.base_size
    assert short_order.side is OrderSide.SELL


async def test_the_size_is_final_at_build_time(
) -> None:
    """``PlaceOrder`` commits the size to its own transaction before the
    network call, so the number it records has to be the number that goes on
    the wire."""
    client = FakeFuturesClient()
    adapter = _adapter(client)

    order = await adapter.build_open_order(_open())
    await adapter.place(order)

    assert isinstance(order, FuturesMarketOrder)
    assert client.orders[0]["base_size"] == order.base_size


async def test_a_grant_too_small_to_reach_one_step_is_refused_by_name() -> None:
    adapter = _adapter(FakeFuturesClient(leverage=Decimal("1")))

    with pytest.raises(ExchangeError, match="too small to open a position"):
        await adapter.build_open_order(_open(granted="0.5"))


async def test_a_size_over_the_market_cap_is_refused() -> None:
    adapter = _adapter(FakeFuturesClient(leverage=Decimal("100")))

    with pytest.raises(PionexApiError, match="caps a market order"):
        await adapter.build_open_order(_open(granted="100000000"))


async def test_a_close_is_reduce_only_and_carries_no_leverage() -> None:
    adapter = _adapter(FakeFuturesClient())

    order = await adapter.build_close_order(
        CloseOrderSpec(
            client_order_id=CLIENT_ORDER_ID,
            symbol=SYMBOL,
            side=OrderSide.SELL,
            base_size=Decimal("0.00781234"),
        )
    )

    assert isinstance(order, FuturesMarketOrder)
    assert order.reduce_only is True
    assert order.leverage is None
    assert order.base_size == Decimal("0.0078")


async def test_a_short_can_be_closed_by_buying_back() -> None:
    """The whole reason a futures venue exists here: spot refuses this,
    because a market buy cannot be sized in the base currency."""
    adapter = _adapter(FakeFuturesClient())

    order = await adapter.build_close_order(
        CloseOrderSpec(
            client_order_id=CLIENT_ORDER_ID,
            symbol=SYMBOL,
            side=OrderSide.BUY,
            base_size=Decimal("0.0078"),
        )
    )

    assert order.side is OrderSide.BUY


async def test_a_close_never_reads_an_account_setting() -> None:
    """A close that fails because a descriptive field could not be read
    leaves a real position open."""
    adapter = _adapter(
        FakeFuturesClient(leverage_raises=PionexApiError("leverage unavailable"))
    )

    order = await adapter.build_close_order(
        CloseOrderSpec(
            client_order_id=CLIENT_ORDER_ID,
            symbol=SYMBOL,
            side=OrderSide.SELL,
            base_size=Decimal("0.0078"),
        )
    )

    assert order.base_size == Decimal("0.0078")


async def test_a_position_smaller_than_one_step_is_named_rather_than_sent() -> None:
    adapter = _adapter(FakeFuturesClient())

    with pytest.raises(ExchangeError, match="smaller than one tradable unit"):
        await adapter.build_close_order(
            CloseOrderSpec(
                client_order_id=CLIENT_ORDER_ID,
                symbol=SYMBOL,
                side=OrderSide.SELL,
                base_size=Decimal("0.00001"),
            )
        )


async def test_a_spot_order_is_refused_rather_than_mis_sent() -> None:
    """Routing should never do this. If it ever does, the failure it guards is
    an order sized against one wallet and placed against another."""
    adapter = _adapter(FakeFuturesClient())

    with pytest.raises(ExchangeError, match="not a futures order"):
        await adapter.place(
            MarketBuy(
                client_order_id=CLIENT_ORDER_ID,
                symbol="BTC_USDT",
                quote_amount=Decimal("100"),
            )
        )


async def test_a_rejection_envelope_becomes_a_definitive_exchange_error() -> None:
    """Pionex answered and said no, so PlaceOrder may release the
    reservation."""
    adapter = _adapter(
        FakeFuturesClient(
            place_raises=PionexApiError("bad size", code="TRADE_BAD_SIZE")
        )
    )
    order = FuturesMarketOrder(
        client_order_id=CLIENT_ORDER_ID,
        symbol=SYMBOL,
        side=OrderSide.BUY,
        base_size=Decimal("0.0078"),
        leverage=Decimal("5"),
    )

    with pytest.raises(ExchangeError):
        await adapter.place(order)


@pytest.mark.parametrize(
    "failure",
    [
        PionexApiError("connection reset"),
        PionexApiError("gateway", http_status=502),
        PionexApiError("timeout", http_status=408),
        PionexApiError("throttled", http_status=429),
    ],
)
async def test_an_ambiguous_failure_is_never_reported_as_definitive(
    failure: PionexApiError,
) -> None:
    """A request that timed out may well have opened a leveraged position.
    Reporting it as ExchangeError would release the capital behind it and shut
    the only door left to finding it."""
    adapter = _adapter(FakeFuturesClient(place_raises=failure))
    order = FuturesMarketOrder(
        client_order_id=CLIENT_ORDER_ID,
        symbol=SYMBOL,
        side=OrderSide.BUY,
        base_size=Decimal("0.0078"),
        leverage=Decimal("5"),
    )

    with pytest.raises(PionexApiError) as caught:
        await adapter.place(order)

    assert not isinstance(caught.value, ExchangeError)


async def test_a_missing_order_becomes_order_not_found() -> None:
    adapter = _adapter(
        FakeFuturesClient(lookup_raises=PionexOrderNotFound("no such order"))
    )

    with pytest.raises(OrderNotFound):
        await adapter.fetch_fills(CLIENT_ORDER_ID, SYMBOL)


async def test_a_failed_lookup_is_not_evidence_the_order_never_existed() -> None:
    adapter = _adapter(FakeFuturesClient(lookup_raises=PionexApiError("gateway")))

    with pytest.raises(PionexApiError) as caught:
        await adapter.fetch_fills(CLIENT_ORDER_ID, SYMBOL)

    assert not isinstance(caught.value, OrderNotFound)


async def test_fills_map_onto_the_ledgers_own_shape() -> None:
    fill = PionexFill(
        fill_id="5150",
        order_id="FX-1",
        symbol=SYMBOL,
        side="BUY",
        price=Decimal("64012.3"),
        size=Decimal("0.0078"),
        fee=Decimal("0.2496"),
        fee_coin="USDT",
        timestamp_ms=1787313600000,
    )
    adapter = _adapter(FakeFuturesClient(fills=[fill]))

    mapped = await adapter.fetch_fills(CLIENT_ORDER_ID, SYMBOL)

    assert mapped[0].quantity == Decimal("0.0078")
    assert mapped[0].price == Decimal("64012.3")
    assert mapped[0].fee_currency == "USDT"
    assert mapped[0].filled_at.year == 2026
