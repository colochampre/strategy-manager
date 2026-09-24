"""The live Bybit futures ``ExchangePort`` adapter.

Three things are pinned here. The sizing (margin times leverage, truncated
down, refused rather than guessed). The definitive-versus-ambiguous rule,
which decides whether a failed order releases reserved capital or holds it.
And the separation of "no fills yet" from "no such order", which on this venue
are two different calls because an empty execution list means both.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    ExchangeError,
    OpenOrderSpec,
    OrderNotFound,
    OrderNotPlaceable,
)
from strategy_manager.execution.domain.futures_order import FuturesMarketOrder
from strategy_manager.execution.domain.order import MarketBuy, OrderSide
from strategy_manager.execution.infrastructure.bybit_futures_exchange import (
    BybitFuturesExchangeAdapter,
)
from strategy_manager.shared.domain.money import Venue
from strategy_manager.shared.infrastructure.bybit.errors import (
    BybitApiError,
    BybitOrderNotFound,
)
from strategy_manager.shared.infrastructure.bybit.read_client import PerpContract
from strategy_manager.shared.infrastructure.bybit.trade_client import (
    BybitExecution,
    BybitOrderAck,
)

# str(uuid4()) is exactly 36 characters, which is exactly Bybit's limit.
CLIENT_ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
SYMBOL = "BTCUSDT"

# BTCUSDT exactly as the live account reported it on 2026-08-26.
LIVE_RULES = PerpContract(
    symbol=SYMBOL,
    contract_type="LinearPerpetual",
    base_coin="BTC",
    quote_coin="USDT",
    settle_coin="USDT",
    status="Trading",
    qty_step=Decimal("0.001"),
    min_order_qty=Decimal("0.001"),
    max_order_qty=Decimal("1500.000"),
    min_notional=Decimal("5"),
    tick_size=Decimal("0.10"),
    max_leverage=Decimal("150.00"),
)

DATED_RULES = replace(
    LIVE_RULES, symbol="BTCUSDT-25DEC26", contract_type="LinearFutures"
)


class FakeTradeClient:
    def __init__(
        self,
        *,
        leverage: Decimal = Decimal("10"),
        rules: PerpContract = LIVE_RULES,
        leverage_raises: Exception | None = None,
        rules_raises: Exception | None = None,
        place_raises: Exception | None = None,
        executions: list[BybitExecution] | None = None,
        order_exists: bool = True,
        exists_raises: Exception | None = None,
    ) -> None:
        self.orders: list[dict[str, object]] = []
        self.existence_checks = 0
        self._leverage = leverage
        self._rules = rules
        self._leverage_raises = leverage_raises
        self._rules_raises = rules_raises
        self._place_raises = place_raises
        self._executions = executions or []
        self._order_exists = order_exists
        self._exists_raises = exists_raises

    async def leverage_for(self, symbol: str) -> Decimal:
        if self._leverage_raises is not None:
            raise self._leverage_raises
        return self._leverage

    async def perp_rules(self, symbol: str) -> PerpContract:
        if self._rules_raises is not None:
            raise self._rules_raises
        return self._rules

    async def place_market_order(
        self,
        *,
        symbol: str,
        order_link_id: str,
        side: str,
        qty: Decimal,
        reduce_only: bool,
    ) -> BybitOrderAck:
        if self._place_raises is not None:
            raise self._place_raises
        self.orders.append(
            {
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "reduce_only": reduce_only,
            }
        )
        return BybitOrderAck(order_id="BY-1", order_link_id=order_link_id)

    async def fills_for(self, order_link_id: str) -> list[BybitExecution]:
        return self._executions

    async def assert_order_placed(self, order_link_id: str) -> None:
        self.existence_checks += 1
        if self._exists_raises is not None:
            raise self._exists_raises
        if not self._order_exists:
            raise BybitOrderNotFound("no such order")


def _adapter(client: FakeTradeClient) -> BybitFuturesExchangeAdapter:
    return BybitFuturesExchangeAdapter(client)  # type: ignore[arg-type]


def _open(
    side: OrderSide = OrderSide.BUY, granted: str = "100", symbol: str = SYMBOL
) -> OpenOrderSpec:
    return OpenOrderSpec(
        client_order_id=CLIENT_ORDER_ID,
        symbol=symbol,
        side=side,
        granted=Decimal(granted),
        price=Decimal("78000"),
    )


def _order(reduce_only: bool = False) -> FuturesMarketOrder:
    return FuturesMarketOrder(
        client_order_id=CLIENT_ORDER_ID,
        symbol=SYMBOL,
        side=OrderSide.BUY,
        base_size=Decimal("0.012"),
        leverage=Decimal("10"),
        reduce_only=reduce_only,
    )


def test_the_adapter_is_live_and_serves_only_usdt_m() -> None:
    """Bybit also settles linear perpetuals in USDC, which no capital pool
    can hold yet."""
    assert BybitFuturesExchangeAdapter.is_live is True
    assert BybitFuturesExchangeAdapter.venues == frozenset({Venue.USDT_M.value})


async def test_an_opening_order_is_margin_times_leverage_over_price() -> None:
    """100 USDT of margin at 10x on a 78000 market is 1000 USDT of notional,
    which is 0.01282 BTC -- truncated to 0.012 at a step of 0.001."""
    order = await _adapter(FakeTradeClient()).build_open_order(_open())

    assert isinstance(order, FuturesMarketOrder)
    assert order.base_size == Decimal("0.012")
    assert order.leverage == Decimal("10")
    assert order.reduce_only is False


async def test_the_leverage_actually_changes_the_size() -> None:
    """The regression that costs the whole multiple."""
    at_10x = await _adapter(FakeTradeClient(leverage=Decimal("10"))).build_open_order(_open())
    at_20x = await _adapter(FakeTradeClient(leverage=Decimal("20"))).build_open_order(_open())

    assert isinstance(at_10x, FuturesMarketOrder)
    assert isinstance(at_20x, FuturesMarketOrder)
    assert at_20x.base_size == Decimal("0.025")


async def test_an_unreadable_leverage_refuses_the_order_rather_than_guessing() -> None:
    """A live-call failure during build is not a rule refusal: it keeps
    propagating as the raw ``BybitApiError`` and is NOT translated into
    ``OrderNotPlaceable``, so ``PlaceOrder`` treats it as ambiguous and
    retries rather than releasing the reservation."""
    adapter = _adapter(FakeTradeClient(leverage_raises=BybitApiError("unavailable")))

    with pytest.raises(BybitApiError) as caught:
        await adapter.build_open_order(_open())

    assert not isinstance(caught.value, OrderNotPlaceable)


async def test_an_unreadable_perp_rules_refuses_the_order_rather_than_guessing() -> None:
    """Same proof as the leverage read, for the OTHER live call ``build_open_
    order`` makes before it ever reaches a rule check. A network failure
    fetching the contract's own rules must not be mistaken for the venue
    having evaluated and refused the order."""
    adapter = _adapter(FakeTradeClient(rules_raises=BybitApiError("gateway timeout")))

    with pytest.raises(BybitApiError) as caught:
        await adapter.build_open_order(_open())

    assert not isinstance(caught.value, OrderNotPlaceable)


async def test_a_dated_future_is_refused_before_any_order() -> None:
    """Bybit lists 40 dated contracts alongside 800 perpetuals under one
    category. A dated contract traded as a perpetual settles underneath the
    position. Refused as ``OrderNotPlaceable`` -- the venue's own catalogue
    decided, definitively -- not the raw ``BybitApiError`` ``assert_tradable``
    itself raises."""
    adapter = _adapter(FakeTradeClient(rules=DATED_RULES))

    with pytest.raises(OrderNotPlaceable, match="not a perpetual"):
        await adapter.build_open_order(_open())


async def test_a_grant_too_small_to_reach_one_step_is_refused_by_name() -> None:
    """Also pins the symbol-spelling rule: the spec carries TradingView's
    ``.P`` marker, and the exception must report the venue's own spelling."""
    adapter = _adapter(FakeTradeClient(leverage=Decimal("1")))

    with pytest.raises(OrderNotPlaceable, match="too small to open a position") as caught:
        await adapter.build_open_order(_open(granted="20", symbol=f"{SYMBOL}.P"))

    exc = caught.value
    assert exc.symbol == SYMBOL
    assert exc.size == Decimal("0")
    assert exc.minimum == LIVE_RULES.min_order_qty
    assert exc.step == LIVE_RULES.qty_step


async def test_a_notional_below_the_minimum_is_refused() -> None:
    """On BTCUSDT this check is unreachable in practice — minOrderQty 0.001 at
    78000 is 78 USDT of notional, always above the 5 USDT floor, so the
    quantity check fires first. It is still enforced, because the two floors
    are independent and another contract can invert that relationship. This
    uses one that does."""
    binding = replace(LIVE_RULES, min_notional=Decimal("500"))
    adapter = _adapter(FakeTradeClient(leverage=Decimal("1"), rules=binding))

    with pytest.raises(OrderNotPlaceable, match="notional of at least 500"):
        await adapter.build_open_order(_open(granted="100"))


async def test_a_close_is_reduce_only_and_carries_no_leverage() -> None:
    order = await _adapter(FakeTradeClient()).build_close_order(
        CloseOrderSpec(
            client_order_id=CLIENT_ORDER_ID,
            symbol=SYMBOL,
            side=OrderSide.SELL,
            base_size=Decimal("0.012345"),
        )
    )

    assert isinstance(order, FuturesMarketOrder)
    assert order.reduce_only is True
    assert order.leverage is None
    assert order.base_size == Decimal("0.012")


async def test_a_short_can_be_closed_by_buying_back() -> None:
    """The whole reason a futures venue exists here."""
    order = await _adapter(FakeTradeClient()).build_close_order(
        CloseOrderSpec(
            client_order_id=CLIENT_ORDER_ID,
            symbol=SYMBOL,
            side=OrderSide.BUY,
            base_size=Decimal("0.012"),
        )
    )

    assert order.side is OrderSide.BUY


async def test_a_close_floored_to_zero_is_refused_as_not_placeable() -> None:
    """A residual smaller than one tradable unit is dust: no order can close
    it, and that is a rule refusal too, not an ``ExchangeError`` a retry could
    somehow resolve."""
    adapter = _adapter(FakeTradeClient())

    with pytest.raises(OrderNotPlaceable, match="smaller than one tradable unit") as caught:
        await adapter.build_close_order(
            CloseOrderSpec(
                client_order_id=CLIENT_ORDER_ID,
                symbol=SYMBOL,
                side=OrderSide.SELL,
                base_size=Decimal("0.0002"),
            )
        )

    exc = caught.value
    assert exc.symbol == SYMBOL
    assert exc.size == Decimal("0")
    assert exc.minimum == LIVE_RULES.min_order_qty


async def test_a_close_of_a_dated_future_is_refused_as_not_placeable() -> None:
    """``assert_tradable`` on the close path runs the same rule checks as the
    open path (minus the notional check, since a close carries no price) --
    proven here with the same ``LinearFutures`` fixture the open-side test
    uses."""
    adapter = _adapter(FakeTradeClient(rules=DATED_RULES))

    with pytest.raises(OrderNotPlaceable, match="not a perpetual"):
        await adapter.build_close_order(
            CloseOrderSpec(
                client_order_id=CLIENT_ORDER_ID,
                symbol=SYMBOL,
                side=OrderSide.SELL,
                base_size=Decimal("0.012"),
            )
        )


async def test_a_close_never_reads_an_account_setting() -> None:
    """A close that fails because a descriptive field could not be read
    leaves a real position open."""
    adapter = _adapter(FakeTradeClient(leverage_raises=BybitApiError("unavailable")))

    order = await adapter.build_close_order(
        CloseOrderSpec(
            client_order_id=CLIENT_ORDER_ID,
            symbol=SYMBOL,
            side=OrderSide.SELL,
            base_size=Decimal("0.012"),
        )
    )

    assert order.base_size == Decimal("0.012")


async def test_the_side_is_translated_to_bybits_spelling() -> None:
    """Bybit says Buy/Sell; the domain says BUY/SELL. Translated at the
    boundary rather than by storing Bybit's spelling in the domain."""
    client = FakeTradeClient()

    await _adapter(client).place(_order())

    assert client.orders[0]["side"] == "Buy"


async def test_a_close_is_sent_reduce_only() -> None:
    client = FakeTradeClient()

    await _adapter(client).place(_order(reduce_only=True))

    assert client.orders[0]["reduce_only"] is True


async def test_a_spot_order_is_refused_rather_than_mis_sent() -> None:
    adapter = _adapter(FakeTradeClient())

    with pytest.raises(ExchangeError, match="not a futures order"):
        await adapter.place(
            MarketBuy(
                client_order_id=CLIENT_ORDER_ID,
                symbol=SYMBOL,
                quote_amount=Decimal("100"),
            )
        )


async def test_a_business_rejection_is_definitive() -> None:
    """110007 is "Available balance is insufficient" -- Bybit saw the order
    and said no, so PlaceOrder may release the reservation."""
    adapter = _adapter(
        FakeTradeClient(place_raises=BybitApiError("insufficient", code="110007"))
    )

    with pytest.raises(ExchangeError):
        await adapter.place(_order())


@pytest.mark.parametrize(
    "failure",
    [
        BybitApiError("server timeout", code="10000"),
        BybitApiError("time window", code="10002"),
        BybitApiError("rate limited", code="10006"),
        BybitApiError("server error", code="10016"),
        BybitApiError("ip rate limit", code="10018"),
        BybitApiError("connection reset"),
        BybitApiError("gateway", http_status=502),
        BybitApiError("timeout", http_status=408),
        BybitApiError("throttled", http_status=429),
    ],
)
async def test_an_ambiguous_failure_is_never_reported_as_definitive(
    failure: BybitApiError,
) -> None:
    """A request that timed out may well have opened a leveraged position.
    Reporting it as ExchangeError would release the capital behind it and
    shut the only door left to finding it."""
    adapter = _adapter(FakeTradeClient(place_raises=failure))

    with pytest.raises(BybitApiError) as caught:
        await adapter.place(_order())

    assert not isinstance(caught.value, ExchangeError)


async def test_fills_are_read_in_one_hop_from_our_own_id() -> None:
    """Pionex needed clientOrderId -> orderId -> fills. Bybit's execution
    endpoint takes orderLinkId directly, so nothing can go stale in between."""
    execution = BybitExecution(
        exec_id="EX-1",
        order_id="BY-1",
        order_link_id=CLIENT_ORDER_ID,
        symbol=SYMBOL,
        side="Buy",
        price=Decimal("78012.30"),
        qty=Decimal("0.012"),
        fee=Decimal("0.5148"),
        fee_currency="USDT",
        exec_time_ms=1787762883000,
    )
    client = FakeTradeClient(executions=[execution])

    fills = await _adapter(client).fetch_fills(CLIENT_ORDER_ID, SYMBOL)

    assert fills[0].quantity == Decimal("0.012")
    assert fills[0].price == Decimal("78012.30")
    assert fills[0].fee_currency == "USDT"
    assert fills[0].filled_at.year == 2026
    # No existence check was needed: fills are proof the order exists.
    assert client.existence_checks == 0


async def test_no_fills_on_an_existing_order_is_transient_not_missing() -> None:
    """An empty execution list means "not published yet" OR "never placed",
    and those lead to opposite decisions. Only the second releases capital."""
    client = FakeTradeClient(executions=[], order_exists=True)

    fills = await _adapter(client).fetch_fills(CLIENT_ORDER_ID, SYMBOL)

    assert fills == []
    assert client.existence_checks == 1


async def test_no_fills_and_no_order_becomes_order_not_found() -> None:
    client = FakeTradeClient(executions=[], order_exists=False)

    with pytest.raises(OrderNotFound):
        await _adapter(client).fetch_fills(CLIENT_ORDER_ID, SYMBOL)


async def test_a_failed_existence_check_is_not_evidence_of_absence() -> None:
    """SettleExecution reads OrderNotFound as "release the capital". A lookup
    that merely failed is not that."""
    client = FakeTradeClient(
        executions=[], exists_raises=BybitApiError("gateway", http_status=502)
    )

    with pytest.raises(BybitApiError) as caught:
        await _adapter(client).fetch_fills(CLIENT_ORDER_ID, SYMBOL)

    assert not isinstance(caught.value, OrderNotFound)
