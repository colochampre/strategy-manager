"""``FakeExchangeAdapter``: the ``ExchangePort`` adapter used whenever
``DRY_RUN`` is on (design.md § Purpose; spec: trade-execution § DRY_RUN
Safety). ``is_live = False`` so the startup invariant never allows
``dry_run=false`` against it (CLAUDE.md rule 1).
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    OpenOrderSpec,
    OrderNotFound,
    PlacedOrder,
)
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.futures_order import (
    FuturesMarketOrder,
    close_futures_order,
    open_futures_order,
)
from strategy_manager.execution.domain.market_symbol import is_perpetual
from strategy_manager.execution.domain.order import (
    MarketBuy,
    MarketSell,
    OrderSide,
    market_order,
)
from strategy_manager.execution.domain.placeable import PlaceableOrder
from strategy_manager.shared.domain.money import Exchange, Venue


class FakeExchangeAdapter:
    """Implements ``execution.application.ports.ExchangePort``.

    Accepts every order and fills it immediately at a fixed reference price,
    with zero fee — enough to exercise the flow without a real API
    credential.

    It keeps what it was told, keyed by client order id, so the two-step
    place-then-settle flow can be exercised end to end: an order nobody placed
    raises ``OrderNotFound`` here exactly as it would against Pionex.
    """

    is_live = False

    # A fake fills anything anywhere, so it constrains no venue. That is not a
    # loophole: DRY_RUN is what stands between this adapter and a real
    # exchange, and nothing it "trades" reaches one.
    venues = frozenset({Venue.SPOT.value, Venue.USDT_M.value, Venue.COIN_M.value})

    # A dry run rehearses the real shapes, so the fake sizes a perpetual the
    # way the live futures adapter does. Leverage is 1 because there is no
    # account to read one from -- what a dry run exercises is the ORDER SHAPE
    # and the routing, not the multiple.
    FAKE_LEVERAGE = Decimal("1")

    def __init__(
        self, exchange: str = Exchange.BYBIT.value, fill_price: Decimal = Decimal("1")
    ) -> None:
        """``exchange`` is per instance, not per class: the registry is keyed by
        it, so a dry run needs one fake standing in for each configured
        exchange rather than one fake claiming to be all of them. Each also
        keeps its own placed orders, which is what a real pair of adapters
        would do."""
        self.exchange = exchange
        self._fill_price = fill_price
        self._placed: dict[str, Fill] = {}

    async def build_open_order(self, spec: OpenOrderSpec) -> PlaceableOrder:
        """Builds whichever shape the symbol implies.

        Branching on the symbol rather than always building a spot order is
        what makes a dry run worth running: otherwise DRY_RUN would exercise
        a code path that never runs live for a futures strategy, and the
        first real exercise of the futures shape would be with real money.
        """
        if is_perpetual(spec.symbol):
            return open_futures_order(
                side=spec.side,
                client_order_id=spec.client_order_id,
                symbol=spec.symbol,
                granted=spec.granted,
                leverage=self.FAKE_LEVERAGE,
                price=spec.price,
            )
        return market_order(
            side=spec.side,
            client_order_id=spec.client_order_id,
            symbol=spec.symbol,
            granted=spec.granted,
            price=spec.price,
        )

    async def build_close_order(self, spec: CloseOrderSpec) -> PlaceableOrder:
        if is_perpetual(spec.symbol):
            return close_futures_order(
                side=spec.side,
                client_order_id=spec.client_order_id,
                symbol=spec.symbol,
                base_size=spec.base_size,
            )
        if spec.side is not OrderSide.SELL:
            # Mirrors the live spot adapter: a spot market buy cannot be sized
            # in the base currency, so a dry run must refuse what production
            # refuses. A fake that accepts more than the real thing hides the
            # bug until it is expensive.
            raise OrderNotFound(
                "closing a short is not supported on spot; that position "
                "belongs on the futures venue"
            )
        return MarketSell(
            client_order_id=spec.client_order_id,
            symbol=spec.symbol,
            base_size=spec.base_size,
        )

    async def place(self, order: PlaceableOrder) -> PlacedOrder:
        exchange_order_id = f"fake-order-{uuid4()}"
        self._placed[order.client_order_id] = Fill(
            exchange_order_id=exchange_order_id,
            exchange_fill_id=f"fake-fill-{uuid4()}",
            quantity=self._base_quantity(order),
            price=self._fill_price,
            fee=Decimal("0"),
            fee_currency="USDT",
            filled_at=datetime.now(UTC),
        )
        return PlacedOrder(
            exchange_order_id=exchange_order_id,
            client_order_id=order.client_order_id,
        )

    async def fetch_fills(self, client_order_id: str, symbol: str) -> list[Fill]:
        del symbol  # the fake needs no symbol to find an order it recorded
        fill = self._placed.get(client_order_id)
        if fill is None:
            raise OrderNotFound(f"no fake order under client order id {client_order_id}")
        return [fill]

    def _base_quantity(self, order: PlaceableOrder) -> Decimal:
        """A fill is always reported in the base currency, whichever way the
        order was denominated — so a buy's quote amount is converted here at
        the fake's own fill price, exactly as a real venue would convert it at
        the real one."""
        match order:
            case MarketBuy():
                return order.quote_amount / self._fill_price
            case MarketSell():
                return order.base_size
            case FuturesMarketOrder():
                return order.base_size
