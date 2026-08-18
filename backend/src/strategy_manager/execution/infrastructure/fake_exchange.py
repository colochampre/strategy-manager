"""``FakeExchangeAdapter``: the only registered ``ExchangePort`` adapter in
this change (design.md § Purpose; spec: trade-execution § DRY_RUN Safety).
``is_live = False`` so the startup invariant never allows ``dry_run=false``
against it (CLAUDE.md rule 1).
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import OrderRequest


class FakeExchangeAdapter:
    """Implements ``execution.application.ports.ExchangePort``. Always fills
    the order immediately at the requested quantity, at a fixed reference
    price, with zero fee — good enough to exercise the execution flow
    without a real API credential."""

    is_live = False

    def __init__(self, fill_price: Decimal = Decimal("1")) -> None:
        self._fill_price = fill_price

    async def submit(self, order: OrderRequest) -> Fill:
        return Fill(
            exchange_order_id=f"fake-order-{uuid4()}",
            exchange_fill_id=f"fake-fill-{uuid4()}",
            quantity=order.quantity,
            price=self._fill_price,
            fee=Decimal("0"),
            fee_currency="USDT",
            filled_at=datetime.now(UTC),
        )
