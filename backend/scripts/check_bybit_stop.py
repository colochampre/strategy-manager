"""Manual check: a protective stop loss at Bybit, through the production adapter.

This is NOT a test. It needs real API credentials and it OPENS A REAL
LEVERAGED POSITION with real money (CLAUDE.md rule 1: no test may require a
real API credential).

**It previews by default and only trades with ``--confirm``.**

**Why it has to exist.** ``openspec/changes/subscriber-safety`` puts a stop
loss at the exchange beside every live opening (decision D1), so that a
subscriber is protected when nobody signs in, the author vanishes and this app
is down. Nothing in this system has ever placed one. Before the specs are
written, four things have to be seen on the real venue rather than read in
its documentation:

  - the shape ``POST /v5/position/trading-stop`` accepts, and what the stop
    looks like once it rests (``GET /v5/order/realtime``, ``StopOrder``);
  - what a TRIGGERED stop's execution reports. It carries no ``orderLinkId``
    of ours, and the ledger keys fills by that id, so how this system can
    recognise such a fill is the open question the specs depend on;
  - whether the stop disappears by itself when the position closes first,
    which is how almost every position will end in production: by the
    strategy's own signal;
  - whether ``stopLoss: "0"`` cancels it.

**Three modes, one per question:**

  ``--mode trigger``      open, set the stop close to the price, wait for the
                          market to hit it, print what the venue reports. If
                          it is not hit in time, cancel it and close.
  ``--mode close-first``  open, set the stop, close reduce-only as a strategy
                          would, then check the stop is gone.
  ``--mode cancel``       open, set the stop, cancel it with ``"0"``, check it
                          is gone, then close.

Every mode ends flat and checks it. Raw payloads are printed beside what was
sent: a parser agreeing with itself proves nothing.

Guards, all of which refuse rather than warn:
  - a position already open on this symbol
  - granted above a hard ceiling, stop distance or wait outside their bounds
  - availability below what is being asked for

Usage:
    cd backend
    uv run python scripts/check_bybit_stop.py --user-email <e-mail>                 # preview
    uv run python scripts/check_bybit_stop.py --user-email <e-mail> --confirm
    uv run python scripts/check_bybit_stop.py --user-email <e-mail> --mode close-first --confirm
"""

import argparse
import asyncio
import json
import sys
import time
from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import uuid4

from held_leverage import held_leverage
from probe_credentials import add_user_email_argument, announce, vault_credentials

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
MAX_GRANTED = Decimal("50")

# How far below the fill the stop rests, in percent of the price. Close enough
# that ordinary volatility reaches it within minutes in ``trigger`` mode; the
# bounds keep a typo from setting a stop that is meaningless or never near.
DEFAULT_STOP_PCT = Decimal("0.15")
MIN_STOP_PCT = Decimal("0.05")
MAX_STOP_PCT = Decimal("2")

DEFAULT_WAIT_MINUTES = 15
MAX_WAIT_MINUTES = 60
WAIT_POLL_SECONDS = 10

FILL_POLL_ATTEMPTS = 10
FILL_POLL_SECONDS = 1.5

MODES = ("trigger", "close-first", "cancel")
TRIGGER_BY = ("LastPrice", "MarkPrice")


def _venue_symbol(symbol: str) -> str:
    return symbol.upper().removesuffix(".P")


def _dump(title: str, payload: Any) -> None:
    print(f"\n  {title}:")
    print("  " + json.dumps(payload, indent=2, default=str).replace("\n", "\n  "))


async def _open_position(client: BybitReadOnlyClient, symbol: str) -> Decimal:
    for position in await client.positions():
        if position.symbol == symbol and position.size:
            return position.signed_size
    return Decimal(0)


async def _get(
    settings: Settings, credentials: BybitCredentials, path: str, params: dict[str, str]
) -> list[dict[str, Any]]:
    """A raw signed read, so the probe sees what arrived, not what a parser made of it."""
    async with signed_transport(settings, credentials) as transport:
        data = await transport.get(path, params)
    entries = (data or {}).get("list")
    return entries if isinstance(entries, list) else []


async def _set_stop(
    settings: Settings, credentials: BybitCredentials, payload: dict[str, str]
) -> None:
    _dump("SENT to /v5/position/trading-stop", payload)
    async with signed_transport(settings, credentials) as transport:
        answer = await transport.post("/v5/position/trading-stop", payload)
    _dump("ANSWER (result)", answer)


async def _resting_stops(
    settings: Settings, credentials: BybitCredentials, symbol: str
) -> list[dict[str, Any]]:
    return await _get(
        settings,
        credentials,
        "/v5/order/realtime",
        {"category": "linear", "symbol": symbol, "orderFilter": "StopOrder"},
    )


async def _show_stop_state(
    settings: Settings, credentials: BybitCredentials, symbol: str, when: str
) -> list[dict[str, Any]]:
    stops = await _resting_stops(settings, credentials, symbol)
    _dump(f"RESTING stop orders {when} ({len(stops)})", stops)
    positions = await _get(
        settings, credentials, "/v5/position/list", {"category": "linear", "symbol": symbol}
    )
    for position in positions:
        print(
            f"  position size={position.get('size')} stopLoss={position.get('stopLoss')!r} "
            f"tpslMode={position.get('tpslMode')!r}"
        )
    return stops


async def _await_fills(
    adapter: BybitFuturesExchangeAdapter,
    settings: Settings,
    credentials: BybitCredentials,
    order_link_id: str,
    symbol: str,
) -> tuple[Decimal, Decimal]:
    for attempt in range(1, FILL_POLL_ATTEMPTS + 1):
        fills = await adapter.fetch_fills(order_link_id, symbol)
        if fills:
            quantity = sum((fill.quantity for fill in fills), Decimal(0))
            notional = sum((fill.quantity * fill.price for fill in fills), Decimal(0))
            print(f"  {len(fills)} fill(s): qty={quantity} notional={notional}")
            return quantity, notional
        print(f"  no fills yet (attempt {attempt}/{FILL_POLL_ATTEMPTS})")
        await asyncio.sleep(FILL_POLL_SECONDS)
    raise RuntimeError(
        f"the venue published no fills for orderLinkId {order_link_id}. "
        "Check the account before running this again."
    )


async def _close(
    adapter: BybitFuturesExchangeAdapter,
    settings: Settings,
    credentials: BybitCredentials,
    alert_symbol: str,
    symbol: str,
    quantity: Decimal,
) -> None:
    close_id = str(uuid4())
    close = await adapter.build_close_order(
        CloseOrderSpec(
            client_order_id=close_id,
            symbol=alert_symbol,
            side=OrderSide.SELL,
            base_size=quantity,
        )
    )
    assert isinstance(close, FuturesMarketOrder)
    print(f"\nCLOSING {close.base_size} reduce-only (as a strategy's signal would)")
    placed = await adapter.place(close)
    print(f"  accepted, exchange order {placed.exchange_order_id}")
    await _await_fills(adapter, settings, credentials, close_id, symbol)


async def _wait_for_trigger(
    reader: BybitReadOnlyClient, symbol: str, minutes: int
) -> bool:
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        held = await _open_position(reader, symbol)
        price = await reader.last_price(symbol)
        print(f"  {time.strftime('%H:%M:%S')}  last {price}  position {held}")
        if not held:
            return True
        await asyncio.sleep(WAIT_POLL_SECONDS)
    return False


def _bounded(args: argparse.Namespace) -> str | None:
    if args.granted <= 0 or args.granted > MAX_GRANTED:
        return f"granted must be between 0 and {MAX_GRANTED}, got {args.granted}"
    if not MIN_STOP_PCT <= args.stop_pct <= MAX_STOP_PCT:
        return f"--stop-pct must be between {MIN_STOP_PCT} and {MAX_STOP_PCT}, got {args.stop_pct}"
    if not 1 <= args.wait_minutes <= MAX_WAIT_MINUTES:
        return f"--wait-minutes must be between 1 and {MAX_WAIT_MINUTES}, got {args.wait_minutes}"
    return None


def _stop_price(reference: Decimal, pct: Decimal, tick: Decimal) -> Decimal:
    """Below a LONG's price, on the venue's tick, never rounded towards the price."""
    raw = reference * (1 - pct / 100)
    return (raw / tick).to_integral_value(rounding=ROUND_DOWN) * tick


async def main() -> int:  # noqa: PLR0911, PLR0912, PLR0915 -- a linear script, one refusal per guard
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--granted", type=Decimal, default=DEFAULT_GRANTED)
    parser.add_argument("--mode", choices=MODES, default="trigger")
    parser.add_argument("--stop-pct", type=Decimal, default=DEFAULT_STOP_PCT)
    parser.add_argument("--trigger-by", choices=TRIGGER_BY, default="LastPrice")
    parser.add_argument("--wait-minutes", type=int, default=DEFAULT_WAIT_MINUTES)
    parser.add_argument("--confirm", action="store_true")
    add_user_email_argument(parser)
    args = parser.parse_args()

    refusal = _bounded(args)
    if refusal:
        print(f"REFUSING: {refusal}", file=sys.stderr)
        return 1

    settings = get_settings()
    symbol = _venue_symbol(args.symbol)
    print(f"Bybit base URL: {settings.bybit_base_url}")
    print(f"Alert symbol {args.symbol} -> venue symbol {symbol}")
    print(f"Mode {args.mode}   granted {args.granted} USDT   stop {args.stop_pct}% "
          f"below the fill, triggered by {args.trigger_by}\n")

    async with vault_credentials(settings, EXCHANGE, user_email=args.user_email) as vaulted:
        announce(vaulted, f"vault ({EXCHANGE})")
        credentials = BybitCredentials(api_key=vaulted.api_key, api_secret=vaulted.api_secret)

        async with read_only_client(settings, credentials) as reader:
            held = await _open_position(reader, symbol)
            if held:
                print(
                    f"REFUSING: {symbol} already holds {held}. This probe acts only "
                    "on a position it opened itself.",
                    file=sys.stderr,
                )
                return 1
            if await _resting_stops(settings, credentials, symbol):
                print(
                    f"REFUSING: {symbol} already has a resting stop order. Clear it "
                    "first, so what this probe reads is its own.",
                    file=sys.stderr,
                )
                return 1

            available = (
                await BybitBalanceReader(reader, SystemClock()).read([(EXCHANGE, "usdt-m", "USDT")])
            )[0].available
            price = await reader.last_price(symbol)
            venue_leverage = await reader.leverage_for(symbol)
            asked = held_leverage(venue_leverage)
            if asked is None:
                print(
                    f"REFUSING: {symbol} is at {venue_leverage}x, which this system "
                    "cannot ask for (a whole number from 1 to 20). Set it in Bybit first.",
                    file=sys.stderr,
                )
                return 1
            if available < args.granted:
                print(
                    f"REFUSING: the pool has {available} USDT, less than the "
                    f"{args.granted} being asked for.",
                    file=sys.stderr,
                )
                return 1
            print(f"  available {available} USDT   last price {price}")

        async with trade_client(settings, credentials) as client:
            adapter = BybitFuturesExchangeAdapter(client)
            rules = await client.perp_rules(symbol)
            open_id = str(uuid4())
            try:
                order = await adapter.build_open_order(
                    OpenOrderSpec(
                        client_order_id=open_id,
                        symbol=args.symbol,
                        side=OrderSide.BUY,
                        granted=args.granted,
                        price=price,
                        leverage=asked,
                    )
                )
            except (ExchangeError, BybitApiError) as exc:
                print(f"\nBUILD REFUSED -- {exc}", file=sys.stderr)
                return 1
            assert isinstance(order, FuturesMarketOrder)

            leverage = order.leverage or Decimal(1)
            preview_stop = _stop_price(price, args.stop_pct, rules.tick_size)
            loss = order.base_size * (price - preview_stop)
            print("\nPLAN")
            print(f"  open LONG {order.base_size} at about {price}, {leverage}x")
            print(f"  stop at about {preview_stop} (tick {rules.tick_size}), "
                  f"{args.stop_pct}% below")
            print(f"  loss if the stop fills there: about {loss} USDT, plus fees")
            if args.mode == "trigger":
                print(f"  wait up to {args.wait_minutes} min; if not hit, cancel and close")

            if not args.confirm:
                print("\nPREVIEW ONLY. Nothing was placed.")
                return 0

            started_ms = str(int(time.time() * 1000))
            print("\nOPENING...")
            placed = await adapter.place(order)
            print(f"  accepted, exchange order {placed.exchange_order_id}")
            filled, notional = await _await_fills(
                adapter, settings, credentials, open_id, symbol
            )
            entry = notional / filled
            stop = _stop_price(entry, args.stop_pct, rules.tick_size)
            if stop >= entry:
                print("  stop rounded onto the entry; closing and refusing to go on",
                      file=sys.stderr)
                await _close(adapter, settings, credentials, args.symbol, symbol, filled)
                return 1

            print(f"\nSETTING THE STOP at {stop} (entry {entry})")
            await _set_stop(
                settings,
                credentials,
                {
                    "category": "linear",
                    "symbol": symbol,
                    "tpslMode": "Full",
                    "positionIdx": "0",
                    "stopLoss": str(stop),
                    "slTriggerBy": args.trigger_by,
                    "slOrderType": "Market",
                },
            )
            await _show_stop_state(settings, credentials, symbol, "after setting")

            if args.mode == "close-first":
                await _close(adapter, settings, credentials, args.symbol, symbol, filled)
                left = await _show_stop_state(settings, credentials, symbol, "after the close")
                print("\n  RESULT: the stop " + (
                    "is GONE with the position." if not left
                    else "is STILL RESTING after the position closed. Cancel it by hand."
                ))

            elif args.mode == "cancel":
                print("\nCANCELLING THE STOP")
                await _set_stop(
                    settings,
                    credentials,
                    {"category": "linear", "symbol": symbol, "tpslMode": "Full",
                     "positionIdx": "0", "stopLoss": "0"},
                )
                left = await _show_stop_state(settings, credentials, symbol, "after cancelling")
                print("\n  RESULT: cancelling " + (
                    "removed the stop." if not left else "did NOT remove the stop."
                ))
                await _close(adapter, settings, credentials, args.symbol, symbol, filled)

            else:
                print(f"\nWAITING up to {args.wait_minutes} min for the market to reach {stop}")
                async with read_only_client(settings, credentials) as reader:
                    hit = await _wait_for_trigger(reader, symbol, args.wait_minutes)
                if hit:
                    print("\n  RESULT: the stop FIRED. What the venue reports:")
                    _dump(
                        "RAW executions since the opening",
                        await _get(
                            settings, credentials, "/v5/execution/list",
                            {"category": "linear", "symbol": symbol, "startTime": started_ms},
                        ),
                    )
                    _dump(
                        "RAW order history since the opening",
                        await _get(
                            settings, credentials, "/v5/order/history",
                            {"category": "linear", "symbol": symbol, "startTime": started_ms},
                        ),
                    )
                    await _show_stop_state(settings, credentials, symbol, "after firing")
                else:
                    print("\n  RESULT: the market did not reach the stop in time. "
                          "Cancelling it and closing.")
                    await _set_stop(
                        settings,
                        credentials,
                        {"category": "linear", "symbol": symbol, "tpslMode": "Full",
                         "positionIdx": "0", "stopLoss": "0"},
                    )
                    await _close(adapter, settings, credentials, args.symbol, symbol, filled)

        async with read_only_client(settings, credentials) as reader:
            remaining = await _open_position(reader, symbol)
            after = (
                await BybitBalanceReader(reader, SystemClock()).read([(EXCHANGE, "usdt-m", "USDT")])
            )[0].available
        leftover = await _resting_stops(settings, credentials, symbol)

        print("\n--- end ---")
        print(f"  position now {remaining}   resting stops {len(leftover)}")
        print(f"  available before {available} -> after {after}")
        print(f"  difference {after - available} USDT (fees and price move)")
        if remaining or leftover:
            print(
                f"\nWARNING: {symbol} is NOT clean (position {remaining}, "
                f"{len(leftover)} resting stop(s)). Check it before running this again.",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
