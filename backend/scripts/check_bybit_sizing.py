"""Manual check: what order WOULD the Bybit adapter send, against live data?

This is NOT a test. It needs real API credentials and reads the live exchange
(CLAUDE.md rule 1: no test may require a real API credential).

**It places nothing.** There is no ``--execute`` flag and no path that reaches
``place``: it calls ``build_open_order`` and ``build_close_order`` and prints
what came back.

It exists because the sizing rule is the one line that cannot be made safe by
care alone — ``granted * leverage / price`` reads a leverage from the account,
and getting that factor wrong produces an order off by the whole multiple.
Mocks prove the arithmetic; only this proves it against the leverage, the step
and the limits the venue is reporting right now.

**The symbol is deliberately the one a TradingView alert actually sends.**
Charted on Bybit, ``{{ticker}}`` produces ``SOLUSDT.P``. Bybit lists that
market as ``SOLUSDT``. If the adapter did not normalise the marker, every
signal would be refused for naming a market that plainly exists — so passing
the raw alert form here is the point, not a convenience.

What to look at:
  - NOTIONAL should be roughly granted x leverage.
  - MARGIN should come back to the granted amount, slightly under after the
    size truncates to the contract's step. Never over.
  - The step, the minimums and the leverage are live, so an order the venue
    would refuse is refused here with the numbers in the message.

Usage:
    cd backend
    uv run python scripts/check_bybit_sizing.py
    uv run python scripts/check_bybit_sizing.py --symbol BATUSDT.P --granted 3
"""

import argparse
import asyncio
import sys
from decimal import Decimal

from probe_credentials import announce, vault_credentials

from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    ExchangeError,
    OpenOrderSpec,
)
from strategy_manager.execution.domain.futures_order import FuturesMarketOrder
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.bybit_futures_exchange import (
    BybitFuturesExchangeAdapter,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.bybit import EXCHANGE
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.factory import (
    read_only_client,
    trade_client,
)
from strategy_manager.shared.infrastructure.bybit.signer import BybitCredentials

# Exactly what TradingView sends from a Bybit chart.
DEFAULT_SYMBOL = "SOLUSDT.P"
CLIENT_ORDER_ID = "00000000-0000-0000-0000-000000000000"


def _render_open(order: FuturesMarketOrder, granted: Decimal, price: Decimal) -> None:
    leverage = order.leverage or Decimal("1")
    notional = order.base_size * price
    margin = notional / leverage

    print(f"    venue symbol {order.symbol}   <- '.P' removed")
    print(f"    size         {order.base_size}")
    print(f"    leverage     {leverage}x   <- read live from the account")
    print(f"    notional     {notional} at {price}")
    print(f"    margin       {margin}  (granted was {granted})")
    print(f"    reduceOnly   {order.reduce_only}")
    if margin > granted:
        print("    WARNING: margin exceeds the granted amount. Rounding must")
        print("             never go up -- that spends capital never granted.")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--granted", default="5", type=Decimal)
    args = parser.parse_args()

    settings = get_settings()
    print(f"Bybit base URL: {settings.bybit_base_url}")
    print(f"Alert symbol: {args.symbol}")
    print("This probe builds orders and prints them. It places NOTHING.\n")

    async with vault_credentials(settings, EXCHANGE) as vaulted:
        announce(vaulted, f"vault ({EXCHANGE})")
        credentials = BybitCredentials(
            api_key=vaulted.api_key, api_secret=vaulted.api_secret
        )

        async with read_only_client(settings, credentials) as reader:
            venue_symbol = args.symbol.upper().removesuffix(".P")
            price = await reader.last_price(venue_symbol)
            print(f"last price {price}")

        async with trade_client(settings, credentials) as client:
            adapter = BybitFuturesExchangeAdapter(client)

            opened: Decimal | None = None
            for side in (OrderSide.BUY, OrderSide.SELL):
                print(f"\nOPEN {side.value}  granted={args.granted}  price={price}")
                try:
                    order = await adapter.build_open_order(
                        OpenOrderSpec(
                            client_order_id=CLIENT_ORDER_ID,
                            symbol=args.symbol,
                            side=side,
                            granted=args.granted,
                            price=price,
                        )
                    )
                except (ExchangeError, BybitApiError) as exc:
                    print(f"    REFUSED -- {exc}")
                    continue
                assert isinstance(order, FuturesMarketOrder)
                opened = order.base_size
                _render_open(order, args.granted, price)

            if opened is None:
                print("\nno order could be built, so there is nothing to close")
                return 1

            # The close is rehearsed against what the OPEN actually produced,
            # not against granted/price. Those differ by the leverage, and a
            # rehearsal that closes a size no open would ever create tests
            # nothing -- it just trips the step check.
            #
            # A short is closed by buying back the same quantity. That both
            # directions build is the whole reason a futures venue is here.
            held = opened
            for side in (OrderSide.SELL, OrderSide.BUY):
                print(f"\nCLOSE {side.value}  held={held} (from the ledger)")
                try:
                    close = await adapter.build_close_order(
                        CloseOrderSpec(
                            client_order_id=CLIENT_ORDER_ID,
                            symbol=args.symbol,
                            side=side,
                            base_size=held,
                        )
                    )
                except (ExchangeError, BybitApiError) as exc:
                    print(f"    REFUSED -- {exc}")
                    continue
                assert isinstance(close, FuturesMarketOrder)
                print(f"    venue symbol {close.symbol}")
                print(f"    size         {close.base_size} (truncated down)")
                print(f"    leverage     {close.leverage}   <- None: none sized this")
                print(f"    reduceOnly   {close.reduce_only}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
