"""The live Binance futures ``ExchangePort`` adapter.

The same three things its Bybit twin pins — the sizing (margin times leverage,
truncated down, refused rather than guessed), the definitive-versus-ambiguous
rule that decides whether a failed order releases reserved capital, and the
separation of "no fills yet" from "no such order" — plus the two that are
Binance's own:

  * settlement takes a lookup hop, because ``userTrades`` is keyed by symbol
    and a numeric order id rather than by the id this system chose;
  * the catalogue carries 191 ``TRADIFI_PERPETUAL`` contracts beside the
    perpetuals, and an unrecognised contract type must never read as tradable.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    ExchangeError,
    LeverageConflict,
    LeverageNotApplied,
    MarginNotIsolated,
    OpenOrderSpec,
    OrderNotFound,
    OrderNotPlaceable,
)
from strategy_manager.execution.domain.futures_order import FuturesMarketOrder
from strategy_manager.execution.domain.order import MarketBuy, OrderSide
from strategy_manager.execution.infrastructure.binance_futures_exchange import (
    BinanceFuturesExchangeAdapter,
)
from strategy_manager.shared.domain.leverage import Leverage
from strategy_manager.shared.domain.money import Exchange, Venue
from strategy_manager.shared.infrastructure.binance.errors import (
    BinanceApiError,
    BinanceOrderNotFound,
)
from strategy_manager.shared.infrastructure.binance.read_client import (
    PerpContract,
    Position,
    SymbolConfig,
)
from strategy_manager.shared.infrastructure.binance.trade_client import (
    BinanceExecution,
    BinanceOrderAck,
)

# str(uuid4()) is exactly 36 characters, which is exactly Binance's
# newClientOrderId limit -- it fits with nothing to spare.
CLIENT_ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
SYMBOL = "AAVEUSDT"
PRICE = Decimal("124.02")

# AAVEUSDT exactly as the live catalogue reported it on 2026-09-16: step 0.1,
# MARKET ceiling 9000 (against a limit ceiling of 78000), minimum notional 5.
LIVE_RULES = PerpContract(
    symbol=SYMBOL,
    contract_type="PERPETUAL",
    base_asset="AAVE",
    quote_asset="USDT",
    margin_asset="USDT",
    status="TRADING",
    qty_step=Decimal("0.1"),
    min_qty=Decimal("0.1"),
    market_max_qty=Decimal("9000"),
    min_notional=Decimal("5"),
    tick_size=Decimal("0.010"),
)

DATED_RULES = replace(
    LIVE_RULES, symbol="BTCUSDT_251226", contract_type="CURRENT_QUARTER"
)

# Binance-specific, with no Bybit equivalent: 191 of the catalogue's 897
# contracts are tokenised equities carrying this type.
TRADIFI_RULES = replace(
    LIVE_RULES, symbol="AAPLUSDT", contract_type="TRADIFI_PERPETUAL"
)


class FakeTradeClient:
    def __init__(
        self,
        *,
        leverage: Decimal = Decimal("2"),
        rules: PerpContract = LIVE_RULES,
        leverage_raises: Exception | None = None,
        rules_raises: Exception | None = None,
        place_raises: Exception | None = None,
        executions: list[BinanceExecution] | None = None,
        order_id: int = 778899,
        order_id_raises: Exception | None = None,
        mark_price: Decimal = PRICE,
        price_raises: Exception | None = None,
        margin_type: str = "ISOLATED",
        position: Decimal = Decimal("0"),
        leverage_write_raises: Exception | None = None,
        margin_write_raises: Exception | None = None,
        writes_apply: bool = True,
    ) -> None:
        # Every call that reads or writes an account setting, in order: what
        # proves that nothing is written before the size is known to be placeable.
        self.calls: list[str] = []
        self._margin_type = margin_type
        self._position = position
        self._leverage_write_raises = leverage_write_raises
        self._margin_write_raises = margin_write_raises
        self._writes_apply = writes_apply
        self.orders: list[dict[str, object]] = []
        self.lookups: list[tuple[str, str]] = []
        self.fill_reads: list[tuple[str, int]] = []
        self.leverage_reads: list[str] = []
        self.price_reads: list[str] = []
        self._mark_price = mark_price
        self._price_raises = price_raises
        self._leverage = leverage
        self._rules = rules
        self._leverage_raises = leverage_raises
        self._rules_raises = rules_raises
        self._place_raises = place_raises
        self._executions = executions or []
        self._order_id = order_id
        self._order_id_raises = order_id_raises

    async def leverage_for(self, symbol: str) -> Decimal:
        self.leverage_reads.append(symbol)
        if self._leverage_raises is not None:
            raise self._leverage_raises
        return self._leverage

    async def symbol_config(self, symbol: str) -> SymbolConfig:
        self.calls.append("read config")
        self.leverage_reads.append(symbol)
        if self._leverage_raises is not None:
            raise self._leverage_raises
        return SymbolConfig(
            symbol=symbol,
            leverage=self._leverage,
            margin_type=self._margin_type,
            is_auto_add_margin=False,
        )

    async def position_for(self, symbol: str) -> Position | None:
        self.calls.append("read position")
        if self._position == 0:
            return None
        return Position(
            symbol=symbol,
            position_side="BOTH",
            signed_size=self._position,
            entry_price=PRICE,
            mark_price=PRICE,
            notional=self._position * PRICE,
            unrealized_profit=Decimal("0"),
            liquidation_price=None,
        )

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        self.calls.append(f"set leverage {leverage}")
        if self._leverage_write_raises is not None:
            raise self._leverage_write_raises
        if self._writes_apply:
            self._leverage = Decimal(leverage)

    async def set_margin_type_isolated(self, symbol: str) -> None:
        self.calls.append("set isolated")
        if self._margin_write_raises is not None:
            raise self._margin_write_raises
        if self._writes_apply:
            self._margin_type = "ISOLATED"

    async def mark_price(self, symbol: str) -> Decimal:
        self.price_reads.append(symbol)
        if self._price_raises is not None:
            raise self._price_raises
        return self._mark_price

    async def perp_rules(self, symbol: str) -> PerpContract:
        if self._rules_raises is not None:
            raise self._rules_raises
        return self._rules

    async def place_market_order(
        self,
        *,
        symbol: str,
        client_order_id: str,
        side: str,
        qty: Decimal,
        reduce_only: bool,
    ) -> BinanceOrderAck:
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
        return BinanceOrderAck(
            order_id=self._order_id, client_order_id=client_order_id
        )

    async def order_id_for(self, client_order_id: str, symbol: str) -> int:
        self.lookups.append((client_order_id, symbol))
        if self._order_id_raises is not None:
            raise self._order_id_raises
        return self._order_id

    async def fills_for(self, *, symbol: str, order_id: int) -> list[BinanceExecution]:
        self.fill_reads.append((symbol, order_id))
        return self._executions


def _adapter(client: FakeTradeClient) -> BinanceFuturesExchangeAdapter:
    return BinanceFuturesExchangeAdapter(client)  # type: ignore[arg-type]


def _open(
    side: OrderSide = OrderSide.BUY,
    granted: str = "100",
    symbol: str = SYMBOL,
    leverage: int = 2,
) -> OpenOrderSpec:
    """At 2x by default, the fake account's own leverage, so a test about
    something else writes no setting."""
    return OpenOrderSpec(
        client_order_id=CLIENT_ORDER_ID,
        symbol=symbol,
        side=side,
        granted=Decimal(granted),
        price=PRICE,
        leverage=Leverage(leverage),
    )


def _close(side: OrderSide = OrderSide.SELL, base_size: str = "1.6") -> CloseOrderSpec:
    return CloseOrderSpec(
        client_order_id=CLIENT_ORDER_ID,
        symbol=SYMBOL,
        side=side,
        base_size=Decimal(base_size),
    )


def _order(
    reduce_only: bool = False, side: OrderSide = OrderSide.BUY
) -> FuturesMarketOrder:
    return FuturesMarketOrder(
        client_order_id=CLIENT_ORDER_ID,
        symbol=SYMBOL,
        side=side,
        base_size=Decimal("1.6"),
        leverage=Decimal("2"),
        reduce_only=reduce_only,
    )


def _execution(**overrides: object) -> BinanceExecution:
    """One leg of a real USDⓈ-M fill. The fee is charged in USDT on both
    sides, never in the base asset."""
    fields: dict[str, object] = {
        "trade_id": 5150,
        "order_id": 778899,
        "symbol": SYMBOL,
        "side": "BUY",
        "price": Decimal("123.97"),
        "qty": Decimal("0.5"),
        "commission": Decimal("0.03409175"),
        "commission_asset": "USDT",
        "trade_time_ms": 1789560000000,
    }
    fields.update(overrides)
    return BinanceExecution(**fields)  # type: ignore[arg-type]


def test_the_adapter_is_live_and_serves_only_binance_usdt_m() -> None:
    """A venue alone stopped identifying an adapter the moment two exchanges
    offered ``usdt-m``; the pool's money only exists on one of them."""
    assert BinanceFuturesExchangeAdapter.is_live is True
    assert BinanceFuturesExchangeAdapter.exchange == Exchange.BINANCE.value
    assert BinanceFuturesExchangeAdapter.venues == frozenset({Venue.USDT_M.value})


async def test_an_opening_order_is_margin_times_leverage_over_price() -> None:
    """100 USDT of margin at 2x on a 124.02 market is 200 USDT of notional,
    which is 1.6126 AAVE -- truncated to 1.6 at a step of 0.1."""
    order = await _adapter(FakeTradeClient()).build_open_order(_open())

    assert isinstance(order, FuturesMarketOrder)
    assert order.base_size == Decimal("1.6")
    assert order.leverage == Decimal("2")
    assert order.reduce_only is False


async def test_the_leverage_actually_changes_the_size() -> None:
    """The regression that costs the whole multiple. The subscription's
    leverage sizes it, whatever the account was at before (decision 38)."""
    at_2x = await _adapter(FakeTradeClient(leverage=Decimal("4"))).build_open_order(
        _open(leverage=2)
    )
    at_4x = await _adapter(FakeTradeClient(leverage=Decimal("2"))).build_open_order(
        _open(leverage=4)
    )

    assert isinstance(at_2x, FuturesMarketOrder)
    assert isinstance(at_4x, FuturesMarketOrder)
    assert at_2x.base_size == Decimal("1.6")
    assert at_4x.base_size == Decimal("3.2")


async def test_an_unreadable_leverage_refuses_the_order_rather_than_guessing() -> None:
    """A default would size a position at the wrong multiple of the capital
    the allocation engine actually reserved, silently. A live-call failure
    during build is not a rule refusal: it must NOT be translated into
    ``OrderNotPlaceable``, so ``PlaceOrder`` retries rather than releasing the
    reservation on something merely unknown."""
    adapter = _adapter(FakeTradeClient(leverage_raises=BinanceApiError("unavailable")))

    with pytest.raises(BinanceApiError) as caught:
        await adapter.build_open_order(_open())

    assert not isinstance(caught.value, OrderNotPlaceable)


async def test_an_unreadable_perp_rules_refuses_the_order_rather_than_guessing() -> None:
    """Same proof as the leverage read, for the catalogue read ``build_open_
    order`` makes right after it. A network failure fetching the contract's
    own rules must not be mistaken for the venue having evaluated and refused
    the order."""
    adapter = _adapter(FakeTradeClient(rules_raises=BinanceApiError("gateway timeout")))

    with pytest.raises(BinanceApiError) as caught:
        await adapter.build_open_order(_open())

    assert not isinstance(caught.value, OrderNotPlaceable)


async def test_a_dated_quarterly_is_refused_before_any_order() -> None:
    """It shares the catalogue with the perpetuals and settles underneath any
    position held in it. Refused as ``OrderNotPlaceable`` -- the venue's own
    catalogue decided, definitively -- not the raw ``BinanceApiError``
    ``assert_tradable`` itself raises."""
    adapter = _adapter(FakeTradeClient(rules=DATED_RULES))

    with pytest.raises(OrderNotPlaceable, match="not a PERPETUAL"):
        await adapter.build_open_order(_open())


async def test_a_tradifi_perpetual_is_refused_before_any_order() -> None:
    """191 of the 897 listed contracts are tokenised equities carrying this
    type. It is a different product, and an unrecognised type must never read
    as tradable."""
    adapter = _adapter(FakeTradeClient(rules=TRADIFI_RULES))

    with pytest.raises(OrderNotPlaceable, match="TRADIFI_PERPETUAL"):
        await adapter.build_open_order(_open())


async def test_a_grant_too_small_to_reach_one_step_is_refused_by_name() -> None:
    """10 USDT at 1x on a 124.02 market is 0.08 AAVE, which truncates to
    nothing at a step of 0.1. Also pins the symbol-spelling rule: the spec
    carries TradingView's ``.P`` marker, and the exception must report the
    venue's own spelling."""
    adapter = _adapter(FakeTradeClient(leverage=Decimal("1")))

    with pytest.raises(OrderNotPlaceable, match="too small to open a position") as caught:
        await adapter.build_open_order(_open(granted="10", symbol=f"{SYMBOL}.P", leverage=1))

    exc = caught.value
    assert exc.symbol == SYMBOL
    assert exc.size == Decimal("0")
    assert exc.minimum == LIVE_RULES.min_qty
    assert exc.step == LIVE_RULES.qty_step


async def test_a_notional_below_the_minimum_is_refused() -> None:
    """On AAVEUSDT the real floor of 5 USDT is unreachable -- minQty 0.1 at
    124.02 is already 12.4 -- so the quantity check fires first. The two floors
    are independent and another contract can invert that relationship; this
    uses one that does."""
    binding = replace(LIVE_RULES, min_notional=Decimal("500"))
    adapter = _adapter(FakeTradeClient(rules=binding))

    with pytest.raises(OrderNotPlaceable, match="notional of at least 500"):
        await adapter.build_open_order(_open())


# ---- the venue's price, never the alert's (decision 35) ----


async def test_an_opening_is_sized_from_the_venues_price_never_the_alerts() -> None:
    """An author who posts a tenth of the market price would otherwise open
    every live subscriber at ten times the margin granted. 100 USDT at 2x over
    the venue's 124.02 is 1.6 AAVE; over the alert's 12.402 it would be 16.1.
    The price is asked for under the venue's spelling, not TradingView's."""
    client = FakeTradeClient(mark_price=PRICE)
    spec = replace(_open(symbol=f"{SYMBOL}.P"), price=PRICE / 10)

    order = await _adapter(client).build_open_order(spec)

    assert isinstance(order, FuturesMarketOrder)
    assert order.base_size == Decimal("1.6")
    assert client.price_reads == [SYMBOL]


async def test_an_unreadable_price_refuses_the_opening_rather_than_using_the_alerts() -> None:
    """As the leverage: the raw ``BinanceApiError`` propagates, never an
    ``OrderNotPlaceable``, so ``PlaceOrder`` retries instead of releasing the
    reservation on something merely unknown."""
    adapter = _adapter(FakeTradeClient(price_raises=BinanceApiError("unavailable")))

    with pytest.raises(BinanceApiError) as caught:
        await adapter.build_open_order(_open())

    assert not isinstance(caught.value, OrderNotPlaceable)


async def test_the_minimum_notional_is_checked_at_the_venues_price() -> None:
    """An alert at ten times the market must not carry an order past the
    venue's floor: 1.6 AAVE is 198 USDT at 124.02, under a floor of 500, and
    would read 1984 at the alert's 1240.2."""
    binding = replace(LIVE_RULES, min_notional=Decimal("500"))
    adapter = _adapter(FakeTradeClient(rules=binding, mark_price=PRICE))

    with pytest.raises(OrderNotPlaceable, match="notional of at least 500"):
        await adapter.build_open_order(replace(_open(), price=PRICE * 10))


async def test_a_close_reads_no_price_and_an_unreadable_one_does_not_stop_it() -> None:
    """A close is sized from the ledger. Reading a price there would let a
    venue's market-data outage keep a real position open."""
    client = FakeTradeClient(price_raises=BinanceApiError("unavailable"))

    order = await _adapter(client).build_close_order(_close())

    assert order.base_size == Decimal("1.6")
    assert client.price_reads == []


async def test_a_close_is_reduce_only_and_carries_no_leverage() -> None:
    order = await _adapter(FakeTradeClient()).build_close_order(
        _close(base_size="1.63")
    )

    assert isinstance(order, FuturesMarketOrder)
    assert order.reduce_only is True
    assert order.leverage is None
    assert order.base_size == Decimal("1.6")


async def test_a_short_can_be_closed_by_buying_back() -> None:
    """The whole reason a futures venue exists here."""
    order = await _adapter(FakeTradeClient()).build_close_order(
        _close(side=OrderSide.BUY)
    )

    assert order.side is OrderSide.BUY


async def test_a_close_never_reads_an_account_setting() -> None:
    """A close that fails because a descriptive field could not be read leaves
    a real position open at the venue."""
    client = FakeTradeClient(leverage_raises=BinanceApiError("unavailable"))

    order = await _adapter(client).build_close_order(_close())

    assert order.base_size == Decimal("1.6")
    assert client.leverage_reads == []


async def test_a_position_smaller_than_one_step_cannot_be_closed_by_an_order() -> None:
    adapter = _adapter(FakeTradeClient())

    with pytest.raises(OrderNotPlaceable, match="smaller than one tradable unit") as caught:
        await adapter.build_close_order(_close(base_size="0.05"))

    exc = caught.value
    assert exc.symbol == SYMBOL
    assert exc.size == Decimal("0")
    assert exc.minimum == LIVE_RULES.min_qty


async def test_a_close_of_a_dated_quarterly_is_refused_as_not_placeable() -> None:
    """``assert_tradable`` on the close path runs the same rule checks as the
    open path (minus the notional check, since a close carries no price)."""
    adapter = _adapter(FakeTradeClient(rules=DATED_RULES))

    with pytest.raises(OrderNotPlaceable, match="not a PERPETUAL"):
        await adapter.build_close_order(_close(base_size="1.6"))


@pytest.mark.parametrize(
    ("side", "expected"),
    [(OrderSide.BUY, "BUY"), (OrderSide.SELL, "SELL")],
)
async def test_the_side_reaches_binance_unchanged(
    side: OrderSide, expected: str
) -> None:
    """Binance spells it BUY/SELL, which is already what the domain says --
    unlike Bybit, which wants Buy/Sell. Pinned so nobody "fixes" this one to
    match its twin and sends a side Binance does not accept."""
    client = FakeTradeClient()

    await _adapter(client).place(_order(side=side))

    assert client.orders[0]["side"] == expected


async def test_a_close_is_sent_reduce_only() -> None:
    client = FakeTradeClient()

    await _adapter(client).place(_order(reduce_only=True))

    assert client.orders[0]["reduce_only"] is True


async def test_the_exchange_order_id_reaches_the_domain_as_a_string() -> None:
    """Binance answers with a JSON integer where Bybit sends a string, and the
    domain's handle is a string."""
    client = FakeTradeClient(order_id=778899)

    placed = await _adapter(client).place(_order())

    assert placed.exchange_order_id == "778899"
    assert placed.client_order_id == CLIENT_ORDER_ID


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


@pytest.mark.parametrize(
    "failure",
    [
        BinanceApiError("order rejected", code="-2010", http_status=400),
        BinanceApiError("below minimum notional", code="-4164", http_status=400),
    ],
)
async def test_a_business_rejection_is_definitive(failure: BinanceApiError) -> None:
    """Binance saw the order and said no, so PlaceOrder may release the
    reservation."""
    adapter = _adapter(FakeTradeClient(place_raises=failure))

    with pytest.raises(ExchangeError):
        await adapter.place(_order())


async def test_a_geo_refusal_is_definitive() -> None:
    """451 is a decision Binance made before the order existed. Retrying it
    changes nothing, so holding the reservation open would strand capital."""
    adapter = _adapter(
        FakeTradeClient(
            place_raises=BinanceApiError("unavailable for legal reasons", http_status=451)
        )
    )

    with pytest.raises(ExchangeError):
        await adapter.place(_order())


@pytest.mark.parametrize(
    "failure",
    [
        BinanceApiError("disconnected", code="-1001", http_status=500),
        BinanceApiError("send status unknown", code="-1007", http_status=503),
        BinanceApiError("connection reset"),
        BinanceApiError("internal error", http_status=500),
        BinanceApiError("gateway", http_status=502),
        BinanceApiError("timeout", http_status=408),
        BinanceApiError("throttled", http_status=429),
    ],
)
async def test_an_ambiguous_failure_is_never_reported_as_definitive(
    failure: BinanceApiError,
) -> None:
    """A request that timed out may well have opened a leveraged position.
    Reporting it as ExchangeError would release the capital behind it and shut
    the only door left to finding it."""
    adapter = _adapter(FakeTradeClient(place_raises=failure))

    with pytest.raises(BinanceApiError) as caught:
        await adapter.place(_order())

    assert not isinstance(caught.value, ExchangeError)


async def test_fills_are_read_through_the_lookup_hop() -> None:
    """userTrades takes a symbol and a NUMERIC order id, so our own id has to
    be resolved into Binance's first."""
    client = FakeTradeClient(executions=[_execution()])

    fills = await _adapter(client).fetch_fills(CLIENT_ORDER_ID, SYMBOL)

    assert client.lookups == [(CLIENT_ORDER_ID, SYMBOL)]
    assert client.fill_reads == [(SYMBOL, 778899)]
    assert fills[0].quantity == Decimal("0.5")
    assert fills[0].price == Decimal("123.97")
    assert fills[0].fee == Decimal("0.03409175")
    assert fills[0].fee_currency == "USDT"
    assert fills[0].filled_at.year == 2026


async def test_the_perpetual_marker_is_stripped_before_the_lookup() -> None:
    """An order that reached the venue as AAVEUSDT cannot be looked up as
    AAVEUSDT.P -- both endpoints scope the lookup to one market, and the
    suffixed name matches none."""
    client = FakeTradeClient(executions=[_execution()])

    await _adapter(client).fetch_fills(CLIENT_ORDER_ID, "AAVEUSDT.P")

    assert client.lookups == [(CLIENT_ORDER_ID, SYMBOL)]
    assert client.fill_reads == [(SYMBOL, 778899)]


async def test_the_integer_ids_become_strings_on_the_fill() -> None:
    """The ledger's UNIQUE index is (exchange, venue, exchange_fill_id), so
    str(trade_id) is what keeps a fill unique."""
    client = FakeTradeClient(executions=[_execution(trade_id=5150, order_id=778899)])

    fills = await _adapter(client).fetch_fills(CLIENT_ORDER_ID, SYMBOL)

    assert fills[0].exchange_fill_id == "5150"
    assert fills[0].exchange_order_id == "778899"


async def test_no_fills_on_an_existing_order_is_transient_not_missing() -> None:
    """Existence was already settled by the lookup hop, so an empty list means
    "accepted, not yet published" and the settle job retries."""
    client = FakeTradeClient(executions=[])

    fills = await _adapter(client).fetch_fills(CLIENT_ORDER_ID, SYMBOL)

    assert fills == []
    assert client.fill_reads == [(SYMBOL, 778899)]


async def test_an_order_the_venue_does_not_know_becomes_order_not_found() -> None:
    """The answer that releases the capital behind an order that never reached
    the exchange."""
    client = FakeTradeClient(
        order_id_raises=BinanceOrderNotFound("no such order"),
    )

    with pytest.raises(OrderNotFound):
        await _adapter(client).fetch_fills(CLIENT_ORDER_ID, SYMBOL)


async def test_a_failed_lookup_is_not_evidence_of_absence() -> None:
    """SettleExecution reads OrderNotFound as "release the capital". A lookup
    that merely failed is not that."""
    client = FakeTradeClient(
        order_id_raises=BinanceApiError("gateway", http_status=502),
    )

    with pytest.raises(BinanceApiError) as caught:
        await _adapter(client).fetch_fills(CLIENT_ORDER_ID, SYMBOL)

    assert not isinstance(caught.value, OrderNotFound)
    assert client.fill_reads == []


# --- the subscription's leverage, set before the opening (PR H, H.5) ------------------


async def test_a_pair_already_isolated_at_the_chosen_leverage_writes_nothing() -> None:
    """The common case costs nothing beyond the read it already made."""
    client = FakeTradeClient(leverage=Decimal("3"), margin_type="ISOLATED")

    order = await _adapter(client).build_open_order(_open(leverage=3))

    assert client.calls == ["read config"]
    assert isinstance(order, FuturesMarketOrder)
    assert order.leverage == Decimal("3")


async def test_another_leverage_is_set_then_read_back_then_sized_at() -> None:
    """The PNUT incident (2026-11-05): a pair never traded sat at Binance's 20x
    default while the user believed it was at 2x. The chosen leverage is set,
    and the order is sized at what the venue reads back."""
    client = FakeTradeClient(leverage=Decimal("20"), margin_type="ISOLATED")

    order = await _adapter(client).build_open_order(_open(leverage=2))

    assert client.calls == ["read config", "read position", "set leverage 2", "read config"]
    assert isinstance(order, FuturesMarketOrder)
    assert order.leverage == Decimal("2")
    assert order.base_size == Decimal("1.6")


async def test_cross_margin_is_switched_to_isolated_and_read_back() -> None:
    client = FakeTradeClient(leverage=Decimal("2"), margin_type="CROSSED")

    await _adapter(client).build_open_order(_open(leverage=2))

    assert client.calls == ["read config", "read position", "set isolated", "read config"]


async def test_both_are_set_when_both_differ_margin_first() -> None:
    client = FakeTradeClient(leverage=Decimal("20"), margin_type="CROSSED")

    order = await _adapter(client).build_open_order(_open(leverage=5))

    assert client.calls == [
        "read config",
        "read position",
        "set isolated",
        "set leverage 5",
        "read config",
    ]
    assert isinstance(order, FuturesMarketOrder)
    assert order.leverage == Decimal("5")


async def test_isolated_is_recognised_whatever_its_case() -> None:
    """How ``symbolConfig`` spells an isolated symbol is not documented; it is
    compared ignoring case until the owner's probe reads it (H.9)."""
    client = FakeTradeClient(leverage=Decimal("2"), margin_type="isolated")

    await _adapter(client).build_open_order(_open(leverage=2))

    assert client.calls == ["read config"]


async def test_an_opening_refused_for_its_size_changes_no_setting() -> None:
    """The order of an opening: sized and checked first, written only after."""
    client = FakeTradeClient(leverage=Decimal("20"), margin_type="CROSSED")

    with pytest.raises(OrderNotPlaceable):
        await _adapter(client).build_open_order(_open(granted="0.01", leverage=2))

    assert not any(call.startswith("set") for call in client.calls)


async def test_a_leverage_the_venue_does_not_read_back_refuses_the_opening() -> None:
    client = FakeTradeClient(leverage=Decimal("20"), writes_apply=False)

    with pytest.raises(LeverageNotApplied) as caught:
        await _adapter(client).build_open_order(_open(leverage=2))

    assert "20" in str(caught.value)
    assert caught.value.reason_code == "LEVERAGE_NOT_APPLIED"


async def test_a_margin_the_venue_does_not_read_back_as_isolated_refuses_the_opening() -> None:
    client = FakeTradeClient(margin_type="CROSSED", writes_apply=False)

    with pytest.raises(MarginNotIsolated) as caught:
        await _adapter(client).build_open_order(_open(leverage=2))

    assert caught.value.reason_code == "MARGIN_NOT_ISOLATED"


async def test_a_leverage_the_venue_refuses_ends_the_opening_definitively() -> None:
    client = FakeTradeClient(
        leverage=Decimal("20"),
        leverage_write_raises=BinanceApiError(
            "Leverage 15 is not valid", code="-4028", http_status=400
        ),
    )

    with pytest.raises(LeverageNotApplied) as caught:
        await _adapter(client).build_open_order(_open(leverage=15))

    assert "-4028" in str(caught.value)


@pytest.mark.parametrize("code", ["-4047", "-4048", "-4168"])
async def test_a_margin_type_the_venue_refuses_ends_the_opening_definitively(code: str) -> None:
    client = FakeTradeClient(
        margin_type="CROSSED",
        margin_write_raises=BinanceApiError("refused", code=code, http_status=400),
    )

    with pytest.raises(MarginNotIsolated) as caught:
        await _adapter(client).build_open_order(_open(leverage=2))

    assert code in str(caught.value)


@pytest.mark.parametrize(
    "failure",
    [
        BinanceApiError("timeout", code="-1007", http_status=408),
        BinanceApiError("gateway", http_status=502),
        BinanceApiError("throttled", http_status=429),
        BinanceApiError("no answer"),
    ],
    ids=["unknown-status", "5xx", "429", "transport"],
)
async def test_a_write_whose_outcome_is_unknown_is_retried_not_refused(
    failure: BinanceApiError,
) -> None:
    client = FakeTradeClient(leverage=Decimal("20"), leverage_write_raises=failure)

    with pytest.raises(BinanceApiError) as caught:
        await _adapter(client).build_open_order(_open(leverage=2))

    assert not isinstance(caught.value, ExchangeError)
    assert caught.value is failure


@pytest.mark.parametrize(
    "failure",
    [
        BinanceApiError("timeout", code="-1007", http_status=408),
        BinanceApiError("gateway", http_status=502),
    ],
    ids=["unknown-status", "5xx"],
)
async def test_a_margin_write_whose_outcome_is_unknown_is_retried_not_refused(
    failure: BinanceApiError,
) -> None:
    client = FakeTradeClient(margin_type="CROSSED", margin_write_raises=failure)

    with pytest.raises(BinanceApiError) as caught:
        await _adapter(client).build_open_order(_open(leverage=2))

    assert not isinstance(caught.value, ExchangeError)
    assert caught.value is failure


@pytest.mark.parametrize("held", [Decimal("1.5"), Decimal("-0.3")], ids=["long", "short"])
async def test_a_pair_held_at_another_leverage_is_a_conflict_and_nothing_is_written(
    held: Decimal,
) -> None:
    """Changing the venue's leverage would change the position already open
    under it, whichever strategy opened it (decision 38)."""
    client = FakeTradeClient(leverage=Decimal("3"), position=held)

    with pytest.raises(LeverageConflict) as caught:
        await _adapter(client).build_open_order(_open(leverage=2))

    assert caught.value.reason_code == "LEVERAGE_CONFLICT"
    assert not any(call.startswith("set") for call in client.calls)


async def test_a_pair_held_on_cross_margin_is_refused_and_nothing_is_written() -> None:
    client = FakeTradeClient(margin_type="CROSSED", position=Decimal("1"))

    with pytest.raises(MarginNotIsolated):
        await _adapter(client).build_open_order(_open(leverage=2))

    assert not any(call.startswith("set") for call in client.calls)


async def test_a_pair_held_at_the_same_settings_opens_without_a_write() -> None:
    client = FakeTradeClient(leverage=Decimal("2"), position=Decimal("1"))

    order = await _adapter(client).build_open_order(_open(leverage=2))

    assert client.calls == ["read config"]
    assert isinstance(order, FuturesMarketOrder)


async def test_an_unreadable_position_before_a_write_is_retried_not_refused() -> None:
    class _NoPosition(FakeTradeClient):
        async def position_for(self, symbol: str) -> Position | None:
            raise BinanceApiError("gateway", http_status=502)

    client = _NoPosition(leverage=Decimal("20"))

    with pytest.raises(BinanceApiError) as caught:
        await _adapter(client).build_open_order(_open(leverage=2))

    assert not isinstance(caught.value, ExchangeError)
    assert not any(call.startswith("set") for call in client.calls)
