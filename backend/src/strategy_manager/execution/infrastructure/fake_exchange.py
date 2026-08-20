"""``FakeExchangeAdapter``: the only registered ``ExchangePort`` adapter until
a live one exists (design.md § Purpose; spec: trade-execution § DRY_RUN
Safety). ``is_live = False`` so the startup invariant never allows
``dry_run=false`` against it (CLAUDE.md rule 1).
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from strategy_manager.execution.application.ports import OrderNotFound, PlacedOrder
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import OrderRequest


class FakeExchangeAdapter:
    """Implements ``execution.application.ports.ExchangePort``.

    Accepts every order and fills it immediately at the requested quantity, at
    a fixed reference price, with zero fee — enough to exercise the flow
    without a real API credential.

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
            quantity=order.quantity,
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
