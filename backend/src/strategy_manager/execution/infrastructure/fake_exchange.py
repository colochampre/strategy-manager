"""``FakeExchangeAdapter``: the ``ExchangePort`` adapter used whenever
``DRY_RUN`` is on (design.md § Purpose; spec: trade-execution § DRY_RUN
Safety). ``is_live = False`` so the startup invariant never allows
``dry_run=false`` against it (CLAUDE.md rule 1).
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from strategy_manager.execution.application.ports import OrderNotFound, PlacedOrder
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import MarketBuy, MarketSell, OrderRequest


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

    def __init__(self, fill_price: Decimal = Decimal("1")) -> None:
        self._fill_price = fill_price
        self._placed: dict[str, Fill] = {}

    async def place(self, order: OrderRequest) -> PlacedOrder:
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

    def _base_quantity(self, order: OrderRequest) -> Decimal:
        """A fill is always reported in the base currency, whichever way the
        order was denominated — so a buy's quote amount is converted here at
        the fake's own fill price, exactly as a real venue would convert it at
        the real one."""
        match order:
            case MarketBuy():
                return order.quote_amount / self._fill_price
            case MarketSell():
                return order.base_size
