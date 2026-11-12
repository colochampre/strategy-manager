"""Manual check: a protective stop loss at Binance USDⓈ-M, through the production adapter.

This is NOT a test. It needs the real trade credential and it OPENS A REAL
LEVERAGED POSITION with real money (CLAUDE.md rule 1: no test may require a
real API credential).

**It previews by default and only trades with ``--confirm``.**

**Why it has to exist.** ``openspec/changes/subscriber-safety`` puts a stop
loss at the exchange beside every live opening (decision D1). Bybit's was
verified live on 2026-11-12 (``scripts/check_bybit_stop.py``); this asks
Binance the same questions. Binance is different in kind, not in detail:
since 2025-12-09 its conditional orders live in a separate Algo Service.
``STOP_MARKET`` on ``/fapi/v1/order`` answers ``-4120 STOP_ORDER_SWITCH_ALGO``;
the stop goes to ``POST /fapi/v1/algoOrder`` (``algoType=CONDITIONAL``), is
read at ``GET /fapi/v1/algoOrder`` and ``/fapi/v1/openAlgoOrders``, and is
cancelled with ``DELETE /fapi/v1/algoOrder``. When it triggers, it creates
an ordinary order whose id comes back as ``actualOrderId``. That id is what
the ledger would key the fill by, because ``userTrades`` is read by
``orderId``.

The stop is ``closePosition=true``: it closes whatever the position holds,
the equivalent of Bybit's Full mode. Binance offers no stop on the opening
order itself, so there is no ``attach`` mode here: the gap between the fill
and the stop is a fact of this venue, and this run measures it.

**Three modes, as on Bybit:**

  ``--mode trigger``      open, set the stop close to the price, wait for the
                          market to hit it, print the algo order and the
                          trades of the order it created. If it is not hit in
                          time, cancel it and close.
  ``--mode close-first``  open, set the stop, close reduce-only as a strategy
                          would, then check whether the stop is still open.
  ``--mode cancel``       open, set the stop, cancel it, check it is gone,
                          then close.

Every mode ends by checking the account is flat with no open algo order.

**The default symbol is not STXUSDT.** A live strategy trades it, and a
signal arriving mid-run would land on this probe's position. Any pair works:
it must already be ISOLATED at a whole leverage from 1 to 20 (the same guard
``check_binance_round_trip.py`` uses, whose helpers this reuses), so the
preview changes nothing.

Usage:
    cd backend
    uv run python scripts/check_binance_stop.py --user-email <e-mail>                 # preview
    uv run python scripts/check_binance_stop.py --user-email <e-mail> --stop-pct 0.05 --confirm
    uv run python scripts/check_binance_stop.py --user-email <e-mail> --mode close-first --confirm
"""

import argparse
import asyncio
import io
import json
import sys
import time
from collections.abc import Mapping
from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import uuid4

import httpx
from check_binance_round_trip import (
    MAX_GRANTED,
    POOL,
    _await_fills,
    _last_price,
    _minimum_granted,
    _order_qty,
    _panic,
    _venue_symbol,
    adapter_order,
)
from held_leverage import held_leverage
from probe_credentials import add_user_email_argument, announce, vault_credentials

from strategy_manager.accounts.infrastructure.binance_balance_reader import (
    BinanceBalanceReader,
)
from strategy_manager.execution.application.ports import CloseOrderSpec, ExchangeError
from strategy_manager.execution.domain.futures_order import FuturesMarketOrder
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.binance_futures_exchange import (
    BinanceFuturesExchangeAdapter,
)
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.infrastructure.binance import EXCHANGE
from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.factory import (
    futures_transport,
    read_only_client,
    trade_client,
)
from strategy_manager.shared.infrastructure.binance.read_client import PerpContract
from strategy_manager.shared.infrastructure.binance.signer import (
    BinanceCredentials,
    BinanceSigner,
)
from strategy_manager.shared.infrastructure.binance.transport import send_request
from strategy_manager.shared.infrastructure.clock import SystemClock

DEFAULT_SYMBOL = "DOGEUSDT"

ALGO_ORDER_PATH = "/fapi/v1/algoOrder"
OPEN_ALGO_ORDERS_PATH = "/fapi/v1/openAlgoOrders"
USER_TRADES_PATH = "/fapi/v1/userTrades"

DEFAULT_STOP_PCT = Decimal("0.15")
MIN_STOP_PCT = Decimal("0.05")
MAX_STOP_PCT = Decimal("2")

DEFAULT_WAIT_MINUTES = 15
MAX_WAIT_MINUTES = 60
WAIT_POLL_SECONDS = 10

MODES = ("trigger", "close-first", "cancel")
WORKING_TYPES = ("CONTRACT_PRICE", "MARK_PRICE")


def _dump(title: str, payload: Any) -> None:
    print(f"\n  {title}:")
    print("  " + json.dumps(payload, indent=2, default=str).replace("\n", "\n  "))


def _stop_price(reference: Decimal, pct: Decimal, tick: Decimal) -> Decimal:
    """Below a LONG's price, on the venue's tick, never rounded towards the price."""
    raw = reference * (1 - pct / 100)
    return (raw / tick).to_integral_value(rounding=ROUND_DOWN) * tick


async def _get(
    settings: Settings, credentials: BinanceCredentials, path: str, params: Mapping[str, str]
) -> Any:
    async with futures_transport(settings, credentials) as transport:
        return await transport.get_signed(path, params)


async def _delete(
    settings: Settings, credentials: BinanceCredentials, path: str, params: Mapping[str, str]
) -> Any:
    """A signed DELETE. The production transport has no DELETE because nothing
    in the application cancels; Binance signs it exactly like a GET."""
    signer = BinanceSigner(
        credentials, SystemClock(), recv_window_ms=settings.binance_recv_window_ms
    )
    async with httpx.AsyncClient(
        base_url=settings.binance_futures_base_url, timeout=settings.binance_timeout_seconds
    ) as http:
        signed = signer.sign_get(path, params)
        return await send_request(
            "DELETE",
            path,
            lambda: http.delete(signed.path_with_query, headers=dict(signed.headers)),
        )


def _as_list(payload: Any) -> list[Any]:
    """``openAlgoOrders``' envelope is not pinned down by the docs read so far:
    a bare list, or an object holding one. The raw payload is printed either way."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list):
                return value
    return []


async def _open_algo_orders(
    settings: Settings, credentials: BinanceCredentials, symbol: str, when: str | None = None
) -> list[Any]:
    payload = await _get(settings, credentials, OPEN_ALGO_ORDERS_PATH, {"symbol": symbol})
    orders = _as_list(payload)
    if when is not None:
        _dump(f"RAW openAlgoOrders {when} ({len(orders)})", payload)
    return orders


async def _algo_order(
    settings: Settings, credentials: BinanceCredentials, algo_id: str, when: str
) -> dict[str, Any]:
    payload = await _get(settings, credentials, ALGO_ORDER_PATH, {"algoId": algo_id})
    _dump(f"RAW algoOrder {algo_id} {when}", payload)
    return payload if isinstance(payload, dict) else {}


async def _close(
    adapter: BinanceFuturesExchangeAdapter,
    settings: Settings,
    credentials: BinanceCredentials,
    symbol: str,
    quantity: Decimal,
) -> None:
    close_id = str(uuid4())
    close = await adapter.build_close_order(
        CloseOrderSpec(
            client_order_id=close_id, symbol=symbol, side=OrderSide.SELL, base_size=quantity
        )
    )
    assert isinstance(close, FuturesMarketOrder)
    print(f"\nCLOSING {close.base_size} reduce-only (as a strategy's signal would)")
    closed = await adapter.place(close)
    print(f"  accepted, exchange order {closed.exchange_order_id}")
    await _await_fills(adapter, settings, credentials, close_id, closed.exchange_order_id, symbol)


async def _cancel(settings: Settings, credentials: BinanceCredentials, algo_id: str) -> None:
    print(f"\nCANCELLING algo order {algo_id}")
    answer = await _delete(settings, credentials, ALGO_ORDER_PATH, {"algoId": algo_id})
    _dump("ANSWER", answer)


def _bounded(args: argparse.Namespace) -> str | None:
    if not MIN_STOP_PCT <= args.stop_pct <= MAX_STOP_PCT:
        return f"--stop-pct must be between {MIN_STOP_PCT} and {MAX_STOP_PCT}, got {args.stop_pct}"
    if not 1 <= args.wait_minutes <= MAX_WAIT_MINUTES:
        return f"--wait-minutes must be between 1 and {MAX_WAIT_MINUTES}, got {args.wait_minutes}"
    return None


async def _after_open(  # noqa: PLR0913 -- the run's whole state, named
    args: argparse.Namespace,
    settings: Settings,
    credentials: BinanceCredentials,
    adapter: BinanceFuturesExchangeAdapter,
    symbol: str,
    rules: PerpContract,
    filled: Decimal,
    entry: Decimal,
) -> str:
    """Everything after the fill. Returns the stop's algoId for the final check."""
    stop = _stop_price(entry, args.stop_pct, rules.tick_size)
    client_algo_id = str(uuid4())
    params = {
        "algoType": "CONDITIONAL",
        "symbol": symbol,
        "side": "SELL",
        "type": "STOP_MARKET",
        "triggerPrice": format(stop, "f"),
        "workingType": args.working_type,
        "closePosition": "true",
        "clientAlgoId": client_algo_id,
    }
    print(f"\nSETTING THE STOP at {stop} (entry {entry})")
    _dump(f"SENT to {ALGO_ORDER_PATH}", params)
    set_at = time.monotonic()
    async with futures_transport(settings, credentials) as transport:
        answer = await transport.post(ALGO_ORDER_PATH, params)
    print(f"  the position was unprotected for about {time.monotonic() - set_at:.2f}s "
          "of this call, plus the fill polling before it")
    _dump("ANSWER", answer)
    algo_id = str((answer or {}).get("algoId", "")) if isinstance(answer, dict) else ""
    if not algo_id:
        raise BinanceApiError("the stop was not acknowledged with an algoId")
    await _algo_order(settings, credentials, algo_id, "after setting")
    await _open_algo_orders(settings, credentials, symbol, "after setting")

    if args.mode == "close-first":
        await _close(adapter, settings, credentials, symbol, filled)
        await _algo_order(settings, credentials, algo_id, "after the close")
        left = await _open_algo_orders(settings, credentials, symbol, "after the close")
        print("\n  RESULT: the stop " + (
            "is GONE with the position." if not left
            else "is STILL OPEN after the position closed. Cancelling it."
        ))
        if left:
            await _cancel(settings, credentials, algo_id)

    elif args.mode == "cancel":
        await _cancel(settings, credentials, algo_id)
        await _algo_order(settings, credentials, algo_id, "after cancelling")
        left = await _open_algo_orders(settings, credentials, symbol, "after cancelling")
        print("\n  RESULT: cancelling " + (
            "removed the stop." if not left else "did NOT remove the stop."
        ))
        await _close(adapter, settings, credentials, symbol, filled)

    else:
        print(f"\nWAITING up to {args.wait_minutes} min for the market to reach {stop}")
        deadline = time.monotonic() + args.wait_minutes * 60
        hit = False
        async with read_only_client(settings, credentials) as reader:
            while time.monotonic() < deadline:
                held = await reader.position_for(symbol)
                print(f"  {time.strftime('%H:%M:%S')}  "
                      f"position {'FLAT' if held is None else held.signed_size}")
                if held is None:
                    hit = True
                    break
                await asyncio.sleep(WAIT_POLL_SECONDS)
        if hit:
            print("\n  RESULT: the stop FIRED. What the venue reports:")
            order = await _algo_order(settings, credentials, algo_id, "after firing")
            actual = str(order.get("actualOrderId", ""))
            if actual:
                _dump(
                    f"RAW userTrades of actualOrderId {actual}",
                    await _get(
                        settings, credentials, USER_TRADES_PATH,
                        {"symbol": symbol, "orderId": actual},
                    ),
                )
            else:
                print("  the algo order names no actualOrderId", file=sys.stderr)
        else:
            print("\n  RESULT: the market did not reach the stop in time. "
                  "Cancelling it and closing.")
            await _cancel(settings, credentials, algo_id)
            await _close(adapter, settings, credentials, symbol, filled)
    return algo_id


async def main() -> int:  # noqa: PLR0911, PLR0915 -- a linear script, one refusal per guard
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--granted", type=Decimal, default=None,
                        help="MARGIN in USDT. Defaults to the smallest that clears the "
                        "contract's minimum notional at the pair's leverage.")
    parser.add_argument("--mode", choices=MODES, default="trigger")
    parser.add_argument("--stop-pct", type=Decimal, default=DEFAULT_STOP_PCT)
    parser.add_argument("--working-type", choices=WORKING_TYPES, default="CONTRACT_PRICE")
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

    async with vault_credentials(settings, EXCHANGE, user_email=args.user_email) as vaulted:
        announce(vaulted, f"vault ({EXCHANGE})")
        credentials = BinanceCredentials(api_key=vaulted.api_key, api_secret=vaulted.api_secret)
        print(f"Binance futures URL: {settings.binance_futures_base_url}")
        print(f"Alert symbol {args.symbol} -> venue symbol {symbol}")
        print(f"Mode {args.mode}   stop {args.stop_pct}% below the fill, "
              f"working type {args.working_type}")

        async with trade_client(settings, credentials) as client:
            try:
                await client.assert_one_way_mode()
            except BinanceApiError as exc:
                print(f"\nREFUSING: {exc}", file=sys.stderr)
                return 1

            async with (
                read_only_client(settings, credentials) as reader,
                futures_transport(settings, credentials) as public,
            ):
                held = await reader.position_for(symbol)
                if held is not None:
                    print(f"\nREFUSING: {symbol} already holds {held.signed_size}. This "
                          "probe acts only on a position it opened itself.", file=sys.stderr)
                    return 1
                funds = (await BinanceBalanceReader(reader, SystemClock()).read([POOL]))[0]
                price = await _last_price(public, symbol)

            # Read before anything is placed: if this endpoint's path or shape
            # is wrong, the preview fails, not a run with a position open.
            if await _open_algo_orders(settings, credentials, symbol, "before opening"):
                print(f"\nREFUSING: {symbol} already has an open algo order. Clear it "
                      "first, so what this probe reads is its own.", file=sys.stderr)
                return 1

            try:
                config = await client.symbol_config(symbol)
                rules = await client.perp_rules(symbol)
            except BinanceApiError as exc:
                print(f"\nREFUSING: {exc}", file=sys.stderr)
                return 1
            asked = held_leverage(config.leverage)
            if config.margin_type.upper() != "ISOLATED" or asked is None:
                print(f"\nREFUSING: {symbol} is on {config.margin_type} margin at "
                      f"{config.leverage}x. This probe only opens a pair already ISOLATED "
                      "at a whole leverage from 1 to 20, so that its preview changes "
                      "nothing. Set it in Binance first.", file=sys.stderr)
                return 1

            minimum = _minimum_granted(rules, config.leverage, price)
            granted = args.granted if args.granted is not None else minimum
            if granted is None or granted <= 0 or granted > MAX_GRANTED:
                print(f"\nREFUSING: margin {granted} is not between 0 and {MAX_GRANTED} "
                      f"(minimum viable at {config.leverage}x: {minimum}).", file=sys.stderr)
                return 1
            if funds.available < granted:
                print(f"\nREFUSING: the pool has {funds.available} USDT available, less "
                      f"than the {granted} being asked for.", file=sys.stderr)
                return 1
            qty = _order_qty(rules, granted, config.leverage, price)
            try:
                rules.assert_tradable(qty, price)
                order = await adapter_order(client, symbol, OrderSide.BUY, granted, price, asked)
            except (ExchangeError, BinanceApiError) as exc:
                print(f"\nBUILD REFUSED -- {exc}", file=sys.stderr)
                return 1

            preview_stop = _stop_price(price, args.stop_pct, rules.tick_size)
            print("\nPLAN")
            print(f"  available {funds.available} USDT   last price {price}")
            print(f"  open LONG {order.base_size} {rules.base_asset} with {granted} USDT "
                  f"at {config.leverage}x")
            print(f"  stop at about {preview_stop} (tick {rules.tick_size}), "
                  f"{args.stop_pct}% below, closePosition")
            print(f"  loss if the stop fills there: about "
                  f"{order.base_size * (price - preview_stop)} USDT, plus fees")
            if not args.confirm:
                print("\nPREVIEW ONLY. Nothing was placed, nothing was changed.")
                return 0

            adapter = BinanceFuturesExchangeAdapter(client)
            print("\nOPENING...")
            try:
                placed = await adapter.place(order)
            except ExchangeError as exc:
                print(f"\nREFUSED -- {exc}. Definitive: nothing is open.", file=sys.stderr)
                return 1
            except Exception as exc:
                _panic(symbol, order.base_size, order.client_order_id,
                       f"the opening POST returned no decision ({exc})")
                return 1
            print(f"  accepted, exchange order {placed.exchange_order_id}")

            algo_id = ""
            try:
                leg = await _await_fills(
                    adapter, settings, credentials, order.client_order_id,
                    placed.exchange_order_id, symbol,
                )
                algo_id = await _after_open(
                    args, settings, credentials, adapter, symbol, rules,
                    leg.quantity, leg.average_price,
                )
            except Exception as exc:
                _panic(symbol, order.base_size, order.client_order_id,
                       f"{exc} (a stop may also be resting: algoId {algo_id or 'unknown'})")
                return 1

        async with read_only_client(settings, credentials) as reader:
            remaining = await reader.position_for(symbol)
            after = (await BinanceBalanceReader(reader, SystemClock()).read([POOL]))[0]
        leftover = await _open_algo_orders(settings, credentials, symbol)

        print("\n--- end ---")
        print(f"  position now {'FLAT' if remaining is None else remaining.signed_size}   "
              f"open algo orders {len(leftover)}")
        print(f"  available before {funds.available} -> after {after.available}")
        print(f"  difference {after.available - funds.available} USDT (fees and price move)")
        if remaining is not None or leftover:
            print(f"\nWARNING: {symbol} is NOT clean. Check it before running this again.",
                  file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    # Binance names a wallet "USDⓈ-M Futures"; a cp1252 console cannot print it.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
