"""Manual check: one real USDⓈ-M round trip on Binance, through the production adapter.

This is NOT a test. It needs the real trade credential and it OPENS A REAL
LEVERAGED POSITION with real money (CLAUDE.md rule 1: no test may require a
real API credential).

**It previews by default and only trades with ``--confirm``.**

**What it proves that a read cannot.** Every Binance surface this system reads
has been verified live -- wallet segregation, the per-asset pool figures, the
contract table, the account's leverage and margin type, the position mode. Two
things remain unverified because no read can reach them: the order POST and the
FILL that comes back. No Binance order has ever been placed by this code.

The fill matters more than the order. It feeds the append-only ledger, so a
field read wrongly is written wrongly forever and every PnL number after it
inherits the error. That is why this prints the RAW ``userTrades`` payload
beside the parsed one: a parser agreeing with itself proves nothing, and
exactly this comparison caught two documented-but-absent fields on Pionex.

The specific Binance question is ``commission`` / ``commissionAsset``. The
trade client's docstring claims a USDⓈ-M contract charges the fee in USDT on
BOTH sides, leaving the base quantity untouched -- the opposite of Pionex spot,
where a buy's fee came out of the holding and stranded a position. That claim is
inherited from Bybit's behaviour and from Binance's documentation. Here it is
either confirmed against the wire or it is not.

**It closes what it opens.** Open, read the fill, close reduce-only at the
quantity that actually filled, read that fill, then confirm the position reads
back flat.

**The close is sized from the FILL, not from the order.** They differ: an order
asks for a quantity, a fill reports what was actually acquired. Sizing a close
from the request is how a position is left half-open -- which is what the
ledger exists to prevent in production, where the size comes from recorded fills
rather than from a number someone hoped for.

**The credential comes from the vault, never from ``.env``.** ``.env`` holds the
read-only key; the vault holds the key the worker signs orders with. A write
refused for using the wrong key answers ``-2015``, which also means a revoked
key and a host outside the IP allowlist -- indistinguishable from the venue
forbidding the write. So the key is announced before anything else happens.

Guards, all of which refuse rather than warn:
  - the account is in hedge mode
  - a position is already open on this symbol
  - the pool holds less than is being asked for
  - the size would be rejected by the venue's own limits
  - granted above a hard ceiling

Usage:
    cd backend
    uv run python scripts/check_binance_round_trip.py                  # preview
    uv run python scripts/check_binance_round_trip.py --confirm
    uv run python scripts/check_binance_round_trip.py --symbol SOLUSDT --granted 6 --confirm
"""

import argparse
import asyncio
import io
import json
import sys
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_UP, Decimal
from typing import Any
from uuid import uuid4

from probe_credentials import announce, vault_credentials

from strategy_manager.accounts.application.ports import PoolKey
from strategy_manager.accounts.infrastructure.binance_balance_reader import (
    BinanceBalanceReader,
)
from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    ExchangeError,
    OpenOrderSpec,
)
from strategy_manager.execution.domain.futures_order import (
    FuturesMarketOrder,
    futures_position_size,
)
from strategy_manager.execution.domain.market_symbol import strip_contract_marker
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.binance_futures_exchange import (
    BinanceFuturesExchangeAdapter,
)
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.binance import EXCHANGE
from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.factory import (
    futures_transport,
    read_only_client,
    trade_client,
)
from strategy_manager.shared.infrastructure.binance.read_client import PerpContract
from strategy_manager.shared.infrastructure.binance.signer import BinanceCredentials
from strategy_manager.shared.infrastructure.binance.transport import BinanceTransport
from strategy_manager.shared.infrastructure.clock import SystemClock

# A cheap perpetual: one lot costs little, so the minimum viable position is
# genuinely small. Change it freely -- nothing below is symbol-specific, and
# every limit that decides the size is read from the venue.
DEFAULT_SYMBOL = "STXUSDT"

# The USDⓈ-M USDT pool, the only one this adapter serves.
POOL: PoolKey = (Exchange.BINANCE.value, Venue.USDT_M.value, Currency.USDT.value)

TICKER_PATH = "/fapi/v1/ticker/price"
USER_TRADES_PATH = "/fapi/v1/userTrades"

# A ceiling this script will not cross whatever the arguments say. Not a
# business rule -- a guard against a typo in a number typed at a terminal that
# opens a leveraged position.
MAX_GRANTED = Decimal("50")

CENT = Decimal("0.01")

# Binance sizes from a quotient, and the adapter then floors that quotient to
# the contract's step. A margin computed as "exactly the minimum" can therefore
# floor one step short, so the search adds a cent at a time. Bounded: a run
# that cannot clear the minimum within a dollar is reporting a real problem,
# not a rounding one.
MAX_GRANTED_BUMPS = 100

# Fills are published asynchronously. Long enough that a market order has
# normally settled, and it reports rather than gives up if not.
FILL_POLL_ATTEMPTS = 10
FILL_POLL_SECONDS = 1.5


@dataclass(frozen=True, slots=True)
class Leg:
    """One side of the round trip, summed across its fills.

    Summed rather than averaged because a market order can fill in pieces at
    several prices -- which is precisely why the ledger keeps one row per fill.
    """

    quantity: Decimal
    notional: Decimal
    fee: Decimal
    fee_currencies: tuple[str, ...]

    @property
    def average_price(self) -> Decimal:
        return self.notional / self.quantity if self.quantity else Decimal(0)


def _venue_symbol(symbol: str) -> str:
    """What Binance calls this market, stripped exactly as the adapter strips
    it: an order placed as ``STXUSDT`` cannot be looked up as ``STXUSDT.P``."""
    return strip_contract_marker(symbol).upper()


async def _last_price(transport: BinanceTransport, symbol: str) -> Decimal:
    """The reference price an order is sized from.

    Public, unsigned, and parsed as a string: this number multiplies into a
    position size, so a float would round it before it got there.
    """
    payload = await transport.get_public(TICKER_PATH, {"symbol": symbol})
    if not isinstance(payload, dict):
        raise BinanceApiError(f"{TICKER_PATH} returned a non-object body for {symbol}")
    price = payload.get("price")
    if not isinstance(price, str) or not price:
        raise BinanceApiError(f"{TICKER_PATH} reported no price for {symbol}")
    return Decimal(price)


def _ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Rounds UP to the venue's step.

    The opposite of what an order does. An order floors, because rounding up
    spends capital nobody granted; a MINIMUM floors nothing -- the smallest
    tradable size is by definition the first step at or above the floor.
    """
    if step <= 0:
        return value
    steps = (value / step).to_integral_value(rounding=ROUND_CEILING)
    return steps * step


def _order_qty(
    rules: PerpContract, granted: Decimal, leverage: Decimal, price: Decimal
) -> Decimal:
    """The size the production adapter would arrive at, derived the same way it
    derives it -- the domain's own sizing, then the contract's step."""
    return rules.round_qty(
        futures_position_size(granted=granted, leverage=leverage, price=price)
    )


def _smallest_tradable_qty(rules: PerpContract, price: Decimal) -> Decimal:
    """The smallest quantity this contract accepts: above the lot floor AND
    worth at least the minimum notional, on a step boundary."""
    qty = _ceil_to_step(rules.min_qty, rules.qty_step)
    if rules.min_notional is not None and price > 0:
        qty = max(qty, _ceil_to_step(rules.min_notional / price, rules.qty_step))
    return qty


def _minimum_granted(
    rules: PerpContract, leverage: Decimal, price: Decimal
) -> Decimal | None:
    """The smallest margin that still opens a position the venue will accept.

    Computed, never hardcoded: it is a function of the contract's floors, the
    price right now and the leverage the ACCOUNT is on -- and the last of those
    is a setting the owner can change from Binance's UI between two runs.

    ``None`` when no margin within the bump ceiling clears the floors, which
    means the caller has a real problem to report rather than a number to use.
    """
    wanted = _smallest_tradable_qty(rules, price)
    granted = (wanted * price / leverage).quantize(CENT, rounding=ROUND_UP)
    for _ in range(MAX_GRANTED_BUMPS):
        if granted > 0 and _order_qty(rules, granted, leverage, price) >= wanted:
            return granted
        granted += CENT
    return None


def _panic(symbol: str, size: Decimal, client_order_id: str, reason: str) -> None:
    """Says, unmissably, that real money is exposed and nothing here will fix it.

    Printed instead of a traceback because the operator's next action is at the
    venue, not in this file.
    """
    print("\n" + "!" * 72, file=sys.stderr)
    print("A REAL POSITION MAY BE OPEN RIGHT NOW. CLOSE IT BY HAND.", file=sys.stderr)
    print(f"  symbol          {symbol}", file=sys.stderr)
    print(f"  size            {size}", file=sys.stderr)
    print(f"  clientOrderId   {client_order_id}", file=sys.stderr)
    print(f"  what failed     {reason}", file=sys.stderr)
    print(
        "  Check the position on Binance and flatten it with a reduce-only\n"
        "  order before running this again.",
        file=sys.stderr,
    )
    print("!" * 72, file=sys.stderr)


async def _raw_executions(
    settings: Settings, credentials: BinanceCredentials, symbol: str, order_id: str
) -> list[Any]:
    """The execution payload exactly as Binance sends it.

    Read through the bare transport rather than the typed client on purpose:
    the point is to see what arrived, not what the parser made of it.

    Keyed by Binance's own ``orderId`` because ``/fapi/v1/userTrades`` takes no
    ``origClientOrderId`` -- the same two-hop shape the adapter documents.
    """
    async with futures_transport(settings, credentials) as transport:
        payload = await transport.get_signed(
            USER_TRADES_PATH, {"symbol": symbol, "orderId": order_id}
        )
    return payload if isinstance(payload, list) else []


async def _await_fills(
    adapter: BinanceFuturesExchangeAdapter,
    settings: Settings,
    credentials: BinanceCredentials,
    client_order_id: str,
    exchange_order_id: str,
    symbol: str,
) -> Leg:
    """Polls until the venue publishes fills, then prints raw beside parsed."""
    for attempt in range(1, FILL_POLL_ATTEMPTS + 1):
        fills = await adapter.fetch_fills(client_order_id, symbol)
        if fills:
            raw = await _raw_executions(
                settings, credentials, symbol, exchange_order_id
            )
            print(f"\n  RAW userTrades payload ({len(raw)} entr(y/ies)):")
            print("  " + json.dumps(raw, indent=2).replace("\n", "\n  "))

            print(f"\n  PARSED by this system ({len(fills)} fill(s)):")
            quantity = Decimal(0)
            notional = Decimal(0)
            fee = Decimal(0)
            currencies: list[str] = []
            for fill in fills:
                print(
                    f"    qty={fill.quantity} price={fill.price} "
                    f"fee={fill.fee} {fill.fee_currency} at {fill.filled_at}"
                )
                quantity += fill.quantity
                notional += fill.quantity * fill.price
                fee += fill.fee
                if fill.fee_currency not in currencies:
                    currencies.append(fill.fee_currency)
            print(f"    total qty={quantity}  notional={notional}  fees={fee}")
            return Leg(
                quantity=quantity,
                notional=notional,
                fee=fee,
                fee_currencies=tuple(currencies),
            )

        print(f"  no fills yet (attempt {attempt}/{FILL_POLL_ATTEMPTS})")
        await asyncio.sleep(FILL_POLL_SECONDS)

    raise RuntimeError(
        f"the venue published no fills for order {exchange_order_id} within "
        f"{FILL_POLL_ATTEMPTS} attempts"
    )


def _describe_order(
    order: FuturesMarketOrder, rules: PerpContract, price: Decimal, granted: Decimal
) -> None:
    leverage = order.leverage or Decimal(1)
    notional = order.base_size * price
    print("\nORDER BUILT BY THE PRODUCTION ADAPTER")
    print(f"  symbol       {order.symbol}")
    print(f"  side         {order.side.value}")
    print(f"  size         {order.base_size} {rules.base_asset}")
    print(f"  leverage     {leverage}x   <- read from the account, never defaulted")
    print(f"  notional     {notional} USDT")
    print(f"  margin       {granted} USDT (what the allocation engine would grant)")
    print(f"  step / floor {rules.qty_step} / {rules.min_qty} {rules.base_asset}")
    print(
        f"  min notional {rules.min_notional if rules.min_notional is not None else 'not reported'}"
        f"   -> this order is {notional}"
    )
    print(f"  reduceOnly   {order.reduce_only}")


def _report(open_leg: Leg, close_leg: Leg, side: OrderSide, base_asset: str) -> None:
    """Closes the accounting, the way the Bybit round trip closed its own."""
    fees = open_leg.fee + close_leg.fee
    # A long earns the rise; a short earns the fall. Both legs traded the same
    # quantity, so this is that quantity times the price difference.
    if side is OrderSide.BUY:
        price_move = close_leg.notional - open_leg.notional
    else:
        price_move = open_leg.notional - close_leg.notional
    net = price_move - fees

    print("\n--- the accounting ---")
    print(f"  opened     {open_leg.quantity} {base_asset} at {open_leg.average_price}")
    print(f"  closed     {close_leg.quantity} {base_asset} at {close_leg.average_price}")
    print(f"  open fee   {open_leg.fee} {', '.join(open_leg.fee_currencies)}")
    print(f"  close fee  {close_leg.fee} {', '.join(close_leg.fee_currencies)}")
    print(f"  fees       {fees}")
    print(f"  price move {price_move}")
    print(f"  net        {net}   (price move minus fees, in USDT)")
    print(f"  closes exactly: {price_move - fees == net}")

    currencies = set(open_leg.fee_currencies) | set(close_leg.fee_currencies)
    print("\n--- what this settles ---")
    print(
        f"  fee charged in   {', '.join(sorted(currencies))}"
        + (
            "   <- USDT on BOTH sides, as the trade client claims"
            if currencies == {Currency.USDT.value}
            else "   <- NOT USDT on both sides. The trade client's docstring is "
            "wrong, and a close sized from the ledger will not equal its open."
        )
    )
    print(
        f"  base quantity    opened {open_leg.quantity}, closed {close_leg.quantity}"
        + (
            "   <- untouched by fees"
            if open_leg.quantity == close_leg.quantity
            else "   <- the fee moved the holding; sizing a close from the "
            "ledger needs the fee subtracted"
        )
    )


async def _round_trip(
    settings: Settings,
    credentials: BinanceCredentials,
    adapter: BinanceFuturesExchangeAdapter,
    order: FuturesMarketOrder,
    symbol: str,
    rules: PerpContract,
) -> int:
    """Everything from the order POST onwards. Real money from here."""
    print("\nOPENING...")
    # Guarded, and the two failures are NOT the same thing. A definitive
    # rejection means Binance saw the order and refused it, so nothing exists
    # and this can exit clean. An ambiguous one -- -1001, -1007, a transport
    # failure -- means it never said what happened, and the adapter re-raises
    # those untouched precisely so they are never mistaken for a decision. A
    # position may be open, so it gets the same panic every other post-open
    # failure gets.
    try:
        placed = await adapter.place(order)
    except ExchangeError as exc:
        print(file=sys.stderr)
        print(f"REFUSED -- {exc}", file=sys.stderr)
        print(
            "  Definitive: the venue saw this order and rejected it. "
            "Nothing is open.",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        _panic(
            symbol,
            order.base_size,
            order.client_order_id,
            f"the opening POST returned no decision ({exc}) -- it may still "
            "have reached the matching engine",
        )
        return 1
    print(f"  accepted, exchange order {placed.exchange_order_id}")

    # From this line on the failure mode changes: a position may exist, so
    # nothing may fail quietly. Every path out of here either closes it or says
    # loudly that it did not.
    try:
        open_leg = await _await_fills(
            adapter,
            settings,
            credentials,
            order.client_order_id,
            placed.exchange_order_id,
            symbol,
        )
    except Exception as exc:
        _panic(symbol, order.base_size, order.client_order_id, str(exc))
        return 1

    close_id = str(uuid4())
    try:
        # Sized from the FILL, not from the order. An order asks; a fill reports
        # what was actually acquired, and closing the request rather than the
        # acquisition is how a position is left half open.
        print(
            f"\nCLOSING {open_leg.quantity} {rules.base_asset} "
            "(from the fill, not the order)"
        )
        closing_side = OrderSide.SELL if order.side is OrderSide.BUY else OrderSide.BUY
        close = await adapter.build_close_order(
            CloseOrderSpec(
                client_order_id=close_id,
                symbol=symbol,
                side=closing_side,
                base_size=open_leg.quantity,
            )
        )
        assert isinstance(close, FuturesMarketOrder)
        print(
            f"  side {close.side.value}  size {close.base_size}  "
            f"reduceOnly {close.reduce_only}"
        )

        closed = await adapter.place(close)
        print(f"  accepted, exchange order {closed.exchange_order_id}")

        close_leg = await _await_fills(
            adapter, settings, credentials, close_id, closed.exchange_order_id, symbol
        )
    except Exception as exc:
        _panic(symbol, open_leg.quantity, close_id, str(exc))
        return 1

    _report(open_leg, close_leg, order.side, rules.base_asset)

    async with read_only_client(settings, credentials) as reader:
        remaining = await reader.position_for(symbol)
        funds = (await BinanceBalanceReader(reader, SystemClock()).read([POOL]))[0]

    print(f"\n  position now     {'FLAT' if remaining is None else remaining.signed_size}")
    print(f"  wallet after     {funds.total} USDT (available {funds.available})")

    if remaining is not None:
        _panic(
            symbol,
            remaining.signed_size,
            close_id,
            "the close filled but the position did NOT read back flat",
        )
        return 1
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument(
        "--granted",
        type=Decimal,
        default=None,
        help="MARGIN in USDT. Defaults to the smallest amount that clears this "
        "contract's minimum notional at the account's leverage.",
    )
    parser.add_argument(
        "--side",
        default=OrderSide.BUY.value,
        choices=[OrderSide.BUY.value, OrderSide.SELL.value],
    )
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    side = OrderSide(args.side)
    settings = get_settings()
    symbol = _venue_symbol(args.symbol)

    async with vault_credentials(settings, EXCHANGE) as vaulted:
        # Before anything else, including the URLs: an unattributed refusal has
        # already cost this project one wrong conclusion.
        announce(vaulted, f"vault ({EXCHANGE})")
        credentials = BinanceCredentials(
            api_key=vaulted.api_key, api_secret=vaulted.api_secret
        )

        print(f"Binance futures URL: {settings.binance_futures_base_url}")
        print(f"Alert symbol {args.symbol} -> venue symbol {symbol}")
        print(f"Opening side: {side.value}")

        async with trade_client(settings, credentials) as client:
            # Asserted first, and through the production call: in hedge mode
            # reduceOnly cannot be sent at all, so every close could open a
            # fresh position on the other side.
            try:
                await client.assert_one_way_mode()
            except BinanceApiError as exc:
                print(f"\nREFUSING: {exc}", file=sys.stderr)
                return 1
            print("  position mode: one-way")

            async with (
                read_only_client(settings, credentials) as reader,
                futures_transport(settings, credentials) as public,
            ):
                held = await reader.position_for(symbol)
                if held is not None:
                    print(
                        f"\nREFUSING: {symbol} already holds {held.signed_size}. This "
                        "probe closes what it opens, and it will not act on a "
                        "position it did not create.",
                        file=sys.stderr,
                    )
                    return 1

                funds = (await BinanceBalanceReader(reader, SystemClock()).read([POOL]))[0]
                price = await _last_price(public, symbol)

            print(f"  wallet {funds.total} USDT   available {funds.available} USDT")
            print(f"  last price {price}")

            try:
                leverage = await client.leverage_for(symbol)
                rules = await client.perp_rules(symbol)
            except BinanceApiError as exc:
                print(f"\nREFUSING: {exc}", file=sys.stderr)
                return 1

            minimum = _minimum_granted(rules, leverage, price)
            granted = args.granted if args.granted is not None else minimum
            if granted is None:
                print(
                    f"\nREFUSING: no margin under {MAX_GRANTED_BUMPS * CENT} USDT "
                    f"opens a position {symbol} would accept at {leverage}x and a "
                    f"price of {price}. Its floors are {rules.min_qty} "
                    f"{rules.base_asset} and a notional of {rules.min_notional}.",
                    file=sys.stderr,
                )
                return 1
            print(
                f"  minimum viable margin at {leverage}x: "
                f"{minimum if minimum is not None else 'unreachable'} USDT"
            )

            if granted <= 0 or granted > MAX_GRANTED:
                print(
                    f"\nREFUSING: granted must be between 0 and {MAX_GRANTED}, "
                    f"got {granted}",
                    file=sys.stderr,
                )
                return 1

            if funds.available < granted:
                print(
                    f"\nREFUSING: the pool has {funds.available} USDT available, "
                    f"less than the {granted} being asked for.",
                    file=sys.stderr,
                )
                return 1

            # The venue's own limits, checked before the order exists rather
            # than discovered as a -4164 on the wire. Run through the same
            # PerpContract the adapter uses, so this cannot disagree with it.
            qty = _order_qty(rules, granted, leverage, price)
            try:
                if qty <= 0:
                    raise BinanceApiError(
                        f"{granted} USDT at {leverage}x and a price of {price} "
                        f"rounds down to {qty} at a step of {rules.qty_step}"
                    )
                rules.assert_tradable(qty, price)
            except BinanceApiError as exc:
                print(f"\nREFUSING: {exc}", file=sys.stderr)
                print(
                    f"  --granted {minimum} would clear it at {leverage}x and a "
                    f"price of {price}.",
                    file=sys.stderr,
                )
                return 1

            try:
                order = await adapter_order(client, symbol, side, granted, price)
            except (ExchangeError, BinanceApiError) as exc:
                print(f"\nBUILD REFUSED -- {exc}", file=sys.stderr)
                return 1

            _describe_order(order, rules, price, granted)

            if not args.confirm:
                print("\nPREVIEW ONLY. Nothing was placed, nothing was changed.")
                print("Add --confirm to open and close this position for real.")
                return 0

            adapter = BinanceFuturesExchangeAdapter(client)
            return await _round_trip(
                settings, credentials, adapter, order, symbol, rules
            )


async def adapter_order(
    client: Any, symbol: str, side: OrderSide, granted: Decimal, price: Decimal
) -> FuturesMarketOrder:
    """Builds the opening order through the adapter the worker runs.

    Separated only so the preview and the trade path cannot diverge: whatever
    is printed is the object that gets placed.
    """
    adapter = BinanceFuturesExchangeAdapter(client)
    order = await adapter.build_open_order(
        OpenOrderSpec(
            client_order_id=str(uuid4()),
            symbol=symbol,
            side=side,
            granted=granted,
            price=price,
        )
    )
    assert isinstance(order, FuturesMarketOrder)
    return order


if __name__ == "__main__":
    # Binance names a wallet "USDⓈ-M Futures". A Windows console defaults to
    # cp1252, which cannot encode that character and would abort the probe
    # midway -- after an order, if it landed in the wrong half.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
