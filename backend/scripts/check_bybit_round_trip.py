"""Manual check: one real futures round trip, through the production adapter.

This is NOT a test. It needs real API credentials and it OPENS A REAL
LEVERAGED POSITION with real money (CLAUDE.md rule 1: no test may require a
real API credential).

**It previews by default and only trades with ``--confirm``.**

**Why it has to exist.** Every other surface of this system is verified
against live data: sizing, rounding, limits, leverage, symbol resolution, pool
availability. One is not, and never has been in this project's history — the
order POST and the FILL that comes back. No futures order has ever been placed
by this code, on any venue.

The fill matters more than the order. It feeds the append-only ledger, so a
field this system reads wrongly is written wrongly forever, and every PnL
number after it inherits the error. That is why this prints the RAW execution
payload beside the parsed one: a parser agreeing with itself proves nothing,
and on the other venue exactly this comparison caught two documented fields
that did not exist.

**It closes what it opens.** Open, read the fill, close reduce-only at the
quantity that actually filled, read that fill, then confirm the position is
flat. Both directions get exercised and the account ends where it started,
minus fees.

**The close is sized from the FILL, not from the order.** They differ: an
order asks for a quantity, a fill reports what was actually acquired. Sizing a
close from the request is how a position is left half-open — which is exactly
what the ledger exists to prevent in production, where the size comes from
recorded fills rather than from a number someone hoped for.

Guards, all of which refuse rather than warn:
  - a position already open on this symbol
  - granted above a hard ceiling
  - availability below what is being asked for

Usage:
    cd backend
    uv run python scripts/check_bybit_round_trip.py                  # preview
    uv run python scripts/check_bybit_round_trip.py --confirm
    uv run python scripts/check_bybit_round_trip.py --granted 20 --confirm
"""

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from typing import Any
from uuid import uuid4

from probe_credentials import announce, vault_credentials

from strategy_manager.accounts.infrastructure.bybit_balance_reader import (
    BybitBalanceReader,
)
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
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.infrastructure.bybit import EXCHANGE
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.factory import (
    read_only_client,
    signed_transport,
    trade_client,
)
from strategy_manager.shared.infrastructure.bybit.read_client import BybitReadOnlyClient
from strategy_manager.shared.infrastructure.bybit.signer import BybitCredentials
from strategy_manager.shared.infrastructure.clock import SystemClock

DEFAULT_SYMBOL = "SOLUSDT.P"
DEFAULT_GRANTED = Decimal("20")

# A ceiling this script will not cross whatever the arguments say. Not a
# business rule -- a guard against a typo in a number typed at a terminal that
# opens a leveraged position.
MAX_GRANTED = Decimal("50")

# Fills are published asynchronously. Long enough that a market order has
# normally settled, and it reports rather than gives up if not.
FILL_POLL_ATTEMPTS = 10
FILL_POLL_SECONDS = 1.5


def _venue_symbol(symbol: str) -> str:
    return symbol.upper().removesuffix(".P")


async def _open_position(client: BybitReadOnlyClient, symbol: str) -> Decimal:
    for position in await client.positions():
        if position.symbol == symbol and position.size:
            return position.signed_size
    return Decimal(0)


async def _raw_executions(
    settings: Settings, credentials: BybitCredentials, order_link_id: str
) -> list[dict[str, Any]]:
    """The execution payload exactly as Bybit sends it.

    Read through the bare transport rather than the typed client on purpose:
    the point is to see what arrived, not what the parser made of it.
    """
    async with signed_transport(settings, credentials) as transport:
        data = await transport.get(
            "/v5/execution/list",
            {"category": "linear", "orderLinkId": order_link_id},
        )
    entries = (data or {}).get("list")
    return entries if isinstance(entries, list) else []


async def _await_fills(
    adapter: BybitFuturesExchangeAdapter,
    settings: Settings,
    credentials: BybitCredentials,
    order_link_id: str,
    symbol: str,
) -> tuple[Decimal, Decimal]:
    """Polls until the venue publishes fills, then prints raw beside parsed.

    Returns the filled quantity and the notional, both summed across fills:
    a market order can fill in pieces at several prices, which is precisely
    why the ledger keeps one row per fill rather than an average.
    """
    for attempt in range(1, FILL_POLL_ATTEMPTS + 1):
        fills = await adapter.fetch_fills(order_link_id, symbol)
        if fills:
            raw = await _raw_executions(settings, credentials, order_link_id)
            print(f"\n  RAW execution payload ({len(raw)} entr(y/ies)):")
            print("  " + json.dumps(raw, indent=2).replace("\n", "\n  "))

            print(f"\n  PARSED by this system ({len(fills)} fill(s)):")
            quantity = Decimal(0)
            notional = Decimal(0)
            for fill in fills:
                print(
                    f"    qty={fill.quantity} price={fill.price} "
                    f"fee={fill.fee} {fill.fee_currency} at {fill.filled_at}"
                )
                quantity += fill.quantity
                notional += fill.quantity * fill.price
            print(f"    total qty={quantity}  notional={notional}")
            return quantity, notional

        print(f"  no fills yet (attempt {attempt}/{FILL_POLL_ATTEMPTS})")
        await asyncio.sleep(FILL_POLL_SECONDS)

    raise RuntimeError(
        "the venue published no fills. The order may still be live -- check "
        f"orderLinkId {order_link_id} before running this again."
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--granted", type=Decimal, default=DEFAULT_GRANTED)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    granted: Decimal = args.granted

    if granted <= 0 or granted > MAX_GRANTED:
        print(
            f"REFUSING: granted must be between 0 and {MAX_GRANTED}, got {granted}",
            file=sys.stderr,
        )
        return 1

    settings = get_settings()
    symbol = _venue_symbol(args.symbol)

    print(f"Bybit base URL: {settings.bybit_base_url}")
    print(f"Alert symbol {args.symbol} -> venue symbol {symbol}")
    print(f"Granted margin: {granted} USDT\n")

    async with vault_credentials(settings, EXCHANGE) as vaulted:
        announce(vaulted, f"vault ({EXCHANGE})")
        credentials = BybitCredentials(
            api_key=vaulted.api_key, api_secret=vaulted.api_secret
        )

        async with read_only_client(settings, credentials) as reader:
            held = await _open_position(reader, symbol)
            if held:
                print(
                    f"REFUSING: {symbol} already holds {held}. This probe closes "
                    "what it opens, and it will not act on a position it did "
                    "not create.",
                    file=sys.stderr,
                )
                return 1

            available = (
                await BybitBalanceReader(reader, SystemClock()).read(
                    [("usdt-m", "USDT")]
                )
            )[0].available
            price = await reader.last_price(symbol)
            print(f"  available {available} USDT   last price {price}")

            if available < granted:
                print(
                    f"REFUSING: the pool has {available} USDT, less than the "
                    f"{granted} being asked for.",
                    file=sys.stderr,
                )
                return 1

        async with trade_client(settings, credentials) as client:
            adapter = BybitFuturesExchangeAdapter(client)
            open_id = str(uuid4())

            try:
                order = await adapter.build_open_order(
                    OpenOrderSpec(
                        client_order_id=open_id,
                        symbol=args.symbol,
                        side=OrderSide.BUY,
                        granted=granted,
                        price=price,
                    )
                )
            except (ExchangeError, BybitApiError) as exc:
                print(f"\nBUILD REFUSED -- {exc}", file=sys.stderr)
                return 1

            assert isinstance(order, FuturesMarketOrder)
            leverage = order.leverage or Decimal(1)
            print("\nORDER BUILT BY THE PRODUCTION ADAPTER")
            print("  side       LONG")
            print(f"  size       {order.base_size} SOL")
            print(f"  leverage   {leverage}x   <- read from the account")
            print(f"  notional   {order.base_size * price}")
            print(f"  margin     {order.base_size * price / leverage}")
            print(f"  reduceOnly {order.reduce_only}")

            if not args.confirm:
                print("\nPREVIEW ONLY. Nothing was placed.")
                return 0

            print("\nOPENING...")
            placed = await adapter.place(order)
            print(f"  accepted, exchange order {placed.exchange_order_id}")

            filled, notional = await _await_fills(
                adapter, settings, credentials, open_id, symbol
            )

            # Sized from the FILL, not from the order. An order asks; a fill
            # reports what was actually acquired, and closing the request
            # rather than the acquisition is how a position is left half open.
            print(f"\nCLOSING {filled} SOL (from the fill, not the order)")
            close_id = str(uuid4())
            close = await adapter.build_close_order(
                CloseOrderSpec(
                    client_order_id=close_id,
                    symbol=args.symbol,
                    side=OrderSide.SELL,
                    base_size=filled,
                )
            )
            assert isinstance(close, FuturesMarketOrder)
            print(f"  size {close.base_size}  reduceOnly {close.reduce_only}")

            closed = await adapter.place(close)
            print(f"  accepted, exchange order {closed.exchange_order_id}")

            closed_qty, closed_notional = await _await_fills(
                adapter, settings, credentials, close_id, symbol
            )

        async with read_only_client(settings, credentials) as reader:
            remaining = await _open_position(reader, symbol)
            after = (
                await BybitBalanceReader(reader, SystemClock()).read(
                    [("usdt-m", "USDT")]
                )
            )[0].available

        print("\n--- round trip ---")
        print(f"  opened   {filled} SOL for {notional} USDT")
        print(f"  closed   {closed_qty} SOL for {closed_notional} USDT")
        print(f"  position now {remaining}")
        print(f"  available before {available} -> after {after}")
        print(f"  difference {after - available} USDT (fees and price move)")

        if remaining:
            print(
                f"\nWARNING: {symbol} still holds {remaining}. The account is "
                "NOT flat. Check it before running this again.",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
