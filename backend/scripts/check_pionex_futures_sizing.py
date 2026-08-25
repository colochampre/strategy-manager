"""Manual check: what order WOULD the futures adapter send, against live data?

This is NOT a test. It needs real API credentials and reads the live exchange
(CLAUDE.md rule 1: no test may require a real API credential).

**It places nothing.** There is no ``--execute`` flag and no code path that
could send an order: it calls ``build_open_order`` and ``build_close_order``
and prints what came back. ``place`` is never reached.

It exists because the sizing rule is the one line in the futures adapter that
cannot be made safe by care alone. ``size = granted * leverage / price``
reads a leverage from the account, and getting that factor wrong does not
produce a slightly wrong order -- it produces one off by the whole multiple.
A dry run against mocks proves the arithmetic; only this proves the
arithmetic against the leverage, the step and the limits the venue is
actually reporting right now.

What to look at in the output:
  - NOTIONAL should be roughly granted x leverage. If it equals the granted
    amount instead, the margin/notional distinction has been lost somewhere.
  - MARGIN should come back to the granted amount, slightly under after the
    size is truncated down to the contract's step. Never over.
  - The step and the limits are the live ones, so a size that would be
    refused is refused here, with the numbers in the message.

Usage:
    cd backend
    # PIONEX_API_KEY / PIONEX_API_SECRET must be set
    uv run python scripts/check_pionex_futures_sizing.py
    uv run python scripts/check_pionex_futures_sizing.py --symbol ETH_USDT_PERP \
        --granted 250 --price 3175.5
"""

import argparse
import asyncio
import sys
from decimal import Decimal

from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    ExchangeError,
    OpenOrderSpec,
)
from strategy_manager.execution.domain.futures_order import FuturesMarketOrder
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.pionex_futures_exchange import (
    PionexFuturesExchangeAdapter,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.factory import (
    credentials_from_settings,
    futures_trade_client,
)

DEFAULT_SYMBOL = "BTC_USDT_PERP"
CLIENT_ORDER_ID = "preview-0000-0000-0000-000000000000"


def _render_open(order: FuturesMarketOrder, granted: Decimal, price: Decimal) -> None:
    notional = order.base_size * price
    leverage = order.leverage or Decimal("1")
    margin = notional / leverage

    print(f"    size        {order.base_size} (base)")
    print(f"    leverage    {leverage}x   <- read live from the account")
    print(f"    notional    {notional} at {price}")
    print(f"    margin      {margin}  (granted was {granted})")
    print(f"    reduceOnly  {order.reduce_only}")
    if margin > granted:
        print("    WARNING: margin exceeds the granted amount. Rounding must")
        print("             never go up -- that spends capital never granted.")


async def _preview_open(
    adapter: PionexFuturesExchangeAdapter,
    symbol: str,
    side: OrderSide,
    granted: Decimal,
    price: Decimal,
) -> None:
    print(f"\nOPEN {side.value}  granted={granted}  price={price}")
    try:
        order = await adapter.build_open_order(
            OpenOrderSpec(
                client_order_id=CLIENT_ORDER_ID,
                symbol=symbol,
                side=side,
                granted=granted,
                price=price,
            )
        )
    except (ExchangeError, PionexApiError) as exc:
        print(f"    REFUSED -- {exc}")
        return

    assert isinstance(order, FuturesMarketOrder)
    _render_open(order, granted, price)


async def _preview_close(
    adapter: PionexFuturesExchangeAdapter,
    symbol: str,
    side: OrderSide,
    base_size: Decimal,
) -> None:
    print(f"\nCLOSE {side.value}  held={base_size} (from the ledger)")
    try:
        order = await adapter.build_close_order(
            CloseOrderSpec(
                client_order_id=CLIENT_ORDER_ID,
                symbol=symbol,
                side=side,
                base_size=base_size,
            )
        )
    except (ExchangeError, PionexApiError) as exc:
        print(f"    REFUSED -- {exc}")
        return

    assert isinstance(order, FuturesMarketOrder)
    print(f"    size        {order.base_size} (base, truncated down)")
    print(f"    leverage    {order.leverage}   <- None: no leverage sized this")
    print(f"    reduceOnly  {order.reduce_only}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--granted", default="100", type=Decimal)
    parser.add_argument("--price", default="64000", type=Decimal)
    args = parser.parse_args()

    settings = get_settings()
    print(f"Pionex base URL: {settings.pionex_base_url}")
    print(f"Symbol: {args.symbol}")
    print("This probe builds orders and prints them. It places NOTHING.")

    credentials = credentials_from_settings(settings)
    async with futures_trade_client(settings, credentials) as client:
        adapter = PionexFuturesExchangeAdapter(client)

        rules = await client.perp_rules(args.symbol)
        print(f"\nLIVE CONTRACT RULES for {rules.symbol}")
        print(f"    baseStep       {rules.base_step}")
        print(f"    minSizeMarket  {rules.min_size_market}")
        print(f"    maxSizeMarket  {rules.max_size_market}")
        print(f"    minNotional    {rules.min_notional}")
        print(f"    status         {rules.status}")

        await _preview_open(adapter, args.symbol, OrderSide.BUY, args.granted, args.price)
        await _preview_open(
            adapter, args.symbol, OrderSide.SELL, args.granted, args.price
        )

        # A short is closed by buying back the same base quantity. Spot cannot
        # express that at all, which is the whole reason this venue exists.
        held = rules.round_base_size(args.granted / args.price)
        await _preview_close(adapter, args.symbol, OrderSide.SELL, held)
        await _preview_close(adapter, args.symbol, OrderSide.BUY, held)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
