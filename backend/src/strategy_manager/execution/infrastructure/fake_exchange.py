"""``FakeExchangeAdapter``: the ``ExchangePort`` adapter used whenever
``DRY_RUN`` is on (design.md § Purpose; spec: trade-execution § DRY_RUN
Safety). ``is_live = False`` so the startup invariant never allows
``dry_run=false`` against it (CLAUDE.md rule 1).
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import TypeGuard
from uuid import uuid4

from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    ExchangeError,
    OpenOrderSpec,
    OrderNotFound,
    PlacedOrder,
)
from strategy_manager.execution.domain.fill import (
    REHEARSAL_FILL_ID_PREFIX,
    REHEARSAL_ORDER_ID_PREFIX,
    Fill,
)
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
from strategy_manager.execution.infrastructure.fake_venue_book import FakeVenueBook
from strategy_manager.shared.domain.money import Exchange, Venue


def _is_usable(price: Decimal | None) -> TypeGuard[Decimal]:
    """A price is usable when it is a finite ``Decimal`` above zero. The order
    of the tests matters: comparing a NaN raises."""
    return price is not None and price.is_finite() and price > 0


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
        self,
        exchange: str = Exchange.BYBIT.value,
        fill_price: Decimal | None = None,
        book: FakeVenueBook | None = None,
        fill_latency_polls: int = 0,
        *,
        fee_rate: Decimal,
    ) -> None:
        """``exchange`` is per instance, not per class: the registry is keyed by
        it, so a dry run needs one fake standing in for each configured
        exchange rather than one fake claiming to be all of them. Each also
        keeps its own placed orders, which is what a real pair of adapters
        would do.

        ``book`` is optional (design.md § S4, DRY_RUN paragraph) so every
        caller that predates it -- and every test that does not care about
        orphan classification -- keeps today's behaviour unchanged.

        ``fill_latency_polls`` (design.md § S5 testing, "Timing") rehearses
        an order whose fill is not published on the exchange's first few
        answers -- the ordinary case for a real venue, and the one the S5
        continuation exists to wait out. ``0`` (the default) preserves every
        caller that predates it: ``fetch_fills`` reveals immediately, exactly
        as before."""
        self.exchange = exchange
        self._fixed_fill_price = fill_price
        self._book = book
        self._fill_latency_polls = fill_latency_polls
        self._fee_rate = fee_rate
        # The price each order was built with, keyed by client order id: ``place``
        # is handed only the order, and no order type carries a price (design
        # § B). Written by the two ``build_*`` methods, popped by ``place``.
        self._reference_prices: dict[str, Decimal] = {}
        self._placed: dict[str, Fill] = {}
        self._signed_deltas: dict[str, Decimal] = {}
        self._fetch_calls: dict[str, int] = {}

    async def build_open_order(self, spec: OpenOrderSpec) -> PlaceableOrder:
        """Builds whichever shape the symbol implies.

        Branching on the symbol rather than always building a spot order is
        what makes a dry run worth running: otherwise DRY_RUN would exercise
        a code path that never runs live for a futures strategy, and the
        first real exercise of the futures shape would be with real money.
        """
        order: PlaceableOrder
        if is_perpetual(spec.symbol):
            order = open_futures_order(
                side=spec.side,
                client_order_id=spec.client_order_id,
                symbol=spec.symbol,
                granted=spec.granted,
                leverage=self.FAKE_LEVERAGE,
                price=spec.price,
            )
        else:
            order = market_order(
                side=spec.side,
                client_order_id=spec.client_order_id,
                symbol=spec.symbol,
                granted=spec.granted,
                price=spec.price,
            )
        # Remembered only once the domain accepted the order, so a refused
        # build leaves nothing behind.
        self._reference_prices[spec.client_order_id] = spec.price
        return order

    async def build_close_order(self, spec: CloseOrderSpec) -> PlaceableOrder:
        order: PlaceableOrder
        if is_perpetual(spec.symbol):
            order = close_futures_order(
                side=spec.side,
                client_order_id=spec.client_order_id,
                symbol=spec.symbol,
                base_size=spec.base_size,
            )
            self._remember_close_price(spec)
            return order
        if spec.side is not OrderSide.SELL:
            # Mirrors the live spot adapter: a spot market buy cannot be sized
            # in the base currency, so a dry run must refuse what production
            # refuses. A fake that accepts more than the real thing hides the
            # bug until it is expensive.
            raise OrderNotFound(
                "closing a short is not supported on spot; that position "
                "belongs on the futures venue"
            )
        order = MarketSell(
            client_order_id=spec.client_order_id,
            symbol=spec.symbol,
            base_size=spec.base_size,
        )
        self._remember_close_price(spec)
        return order

    def _remember_close_price(self, spec: CloseOrderSpec) -> None:
        # A close with no price remembers nothing: absent stays absent here,
        # and ``place`` is where that is answered.
        if spec.reference_price is not None:
            self._reference_prices[spec.client_order_id] = spec.reference_price

    async def place(self, order: PlaceableOrder) -> PlacedOrder:
        exchange_order_id = f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}"
        price = self._price_for(order)
        base_quantity = self._base_quantity(order, price)
        self._placed[order.client_order_id] = Fill(
            exchange_order_id=exchange_order_id,
            exchange_fill_id=f"{REHEARSAL_FILL_ID_PREFIX}{uuid4()}",
            quantity=base_quantity,
            price=price,
            fee=Decimal("0"),
            fee_currency="USDT",
            filled_at=datetime.now(UTC),
        )
        # Recorded here, revealed in ``fetch_fills`` -- ``record_fill`` is the
        # book's word for "this fill became visible", and a placed order is
        # not yet visible to anything that settles it (design.md § S4,
        # DRY_RUN paragraph).
        sign = Decimal("1") if order.side is OrderSide.BUY else Decimal("-1")
        self._signed_deltas[order.client_order_id] = sign * base_quantity
        return PlacedOrder(
            exchange_order_id=exchange_order_id,
            client_order_id=order.client_order_id,
        )

    async def fetch_fills(self, client_order_id: str, symbol: str) -> list[Fill]:
        fill = self._placed.get(client_order_id)
        if fill is None:
            raise OrderNotFound(f"no fake order under client order id {client_order_id}")

        calls = self._fetch_calls.get(client_order_id, 0) + 1
        self._fetch_calls[client_order_id] = calls
        if calls <= self._fill_latency_polls:
            return []

        if self._book is not None:
            delta = self._signed_deltas.pop(client_order_id, None)
            if delta is not None:
                self._book.record_fill(self.exchange, symbol, delta)

        return [fill]

    def is_revealed(self, client_order_id: str) -> bool:
        """Whether ``fetch_fills`` has shown this order's fill yet -- past
        ``fill_latency_polls`` calls (design.md § S5 testing, "Timing"). Lets
        a balance-reader test double move a pool's funds in lockstep with
        one specific order's own settlement, rather than at a moment the
        test picks by hand."""
        return self._fetch_calls.get(client_order_id, 0) > self._fill_latency_polls

    @property
    def fixed_fill_price(self) -> Decimal | None:
        """The price every order fills at, or ``None`` when each order fills at
        the price of its own alert (the production mode)."""
        return self._fixed_fill_price

    def _price_for(self, order: PlaceableOrder) -> Decimal:
        """The price this order fills at. An explicit fixed price (tests only)
        wins; otherwise the price remembered for the order's client order id.

        An order with no usable price is REFUSED, here and not at build (design
        § F): a plain exception from the build is retried by the job, and
        ``OrderNotPlaceable`` would be reported as dust. ``ExchangeError`` is
        the definitive-rejection path both use cases already handle. There is
        no fallback: not 1, not the entry price, not the last price seen."""
        remembered = self._reference_prices.pop(order.client_order_id, None)
        if self._fixed_fill_price is not None:
            return self._fixed_fill_price
        if not _is_usable(remembered):
            raise ExchangeError(
                "the simulated exchange cannot price this order: its alert "
                f"carried no usable price (reference price: {remembered})"
            )
        return remembered

    def _base_quantity(self, order: PlaceableOrder, price: Decimal) -> Decimal:
        """A fill is always reported in the base currency, whichever way the
        order was denominated — so a buy's quote amount is converted here at
        the fake's own fill price, exactly as a real venue would convert it at
        the real one."""
        match order:
            case MarketBuy():
                return order.quote_amount / price
            case MarketSell():
                return order.base_size
            case FuturesMarketOrder():
                return order.base_size
