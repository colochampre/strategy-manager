"""Manual check: place ONE real round trip through the live trade adapter.

This is NOT a test. It moves real money, which is exactly why it lives here and
not under tests/ (CLAUDE.md rule 1: no test may require a real API credential).

It exists because everything the trade adapter does that cannot be proven
against a mock is still unproven: whether the vault's credentials carry trade
permission at all, whether a POST signature is accepted by the real endpoint,
what a real fill payload actually looks like, and whether the symbol rounding
produces orders Pionex accepts.

**It previews by default and sends nothing.** ``--execute`` is required to
place. Read the preview first: it prints the exact JSON body, already rounded,
that would go on the wire.

It buys and then sells back, so the account ends flat rather than holding a
position nobody asked for. Two things will NOT balance and both are expected:
the exchange takes a fee on each leg, and the sell is rounded DOWN to the
symbol's base precision, so a dust amount of the base currency stays behind.
Both are reported.

Credentials come from the VAULT, not the environment, because the vault is
what the worker signs live orders with. Proving the environment's read-only key
works would prove nothing about the path that matters.

Usage:
    cd backend
    uv run python scripts/check_pionex_trade.py --symbol ETH_USDT --amount 10
    uv run python scripts/check_pionex_trade.py --symbol ETH_USDT --amount 10 --execute
"""

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from uuid import uuid4

from strategy_manager.accounts.infrastructure.credential_vault import (
    SqlAlchemyCredentialVault,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import engine, session_factory
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import EnvelopeCipher
from strategy_manager.shared.infrastructure.pionex import EXCHANGE as PIONEX_EXCHANGE
from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.factory import (
    read_only_client,
    trade_client,
)
from strategy_manager.shared.infrastructure.pionex.signer import PionexCredentials
from strategy_manager.shared.infrastructure.pionex.trade_client import (
    PionexFill,
    PionexTradeClient,
)

# A typo in --amount must not be able to do real damage. This script exists to
# prove a code path works, and the smallest order the venue accepts proves it
# exactly as well as a large one does.
MAX_AMOUNT = Decimal("25")

FILL_POLL_ATTEMPTS = 10
FILL_POLL_SECONDS = 1.5


async def _load_credentials() -> PionexCredentials:
    settings = get_settings()
    cipher = EnvelopeCipher.from_base64(settings.master_encryption_key)
    async with session_factory() as session:
        credential = await SqlAlchemyCredentialVault(
            session, cipher, SystemClock()
        ).load(PIONEX_EXCHANGE)
    return PionexCredentials(
        api_key=credential.api_key, api_secret=credential.api_secret
    )


async def _await_fills(
    client: PionexTradeClient, client_order_id: str, leg: str
) -> list[PionexFill]:
    """Settlement in the worker is a scheduled job; here it is a poll. Same
    two hops, same client order id."""
    for attempt in range(1, FILL_POLL_ATTEMPTS + 1):
        order_id = await client.order_id_for(client_order_id)
        fills = await client.fills_for_order(order_id)
        if fills:
            print(f"  {leg} filled after {attempt} poll(s), order {order_id}")
            return fills
        await asyncio.sleep(FILL_POLL_SECONDS)

    raise RuntimeError(
        f"{leg}: Pionex knows order {client_order_id} but published no fills "
        f"after {FILL_POLL_ATTEMPTS} polls. Check the account before re-running."
    )


def _render_fills(leg: str, fills: list[PionexFill]) -> None:
    print(f"\n  --- {leg} fills ({len(fills)}) ---")
    for fill in fills:
        print(
            f"    {fill.side} size={fill.size} price={fill.price} "
            f"fee={fill.fee} {fill.fee_coin} id={fill.fill_id}"
        )


def _base_received(fills: list[PionexFill], base_currency: str) -> Decimal:
    """The same projection the ledger performs: bought minus fees charged in
    the base currency, because that much never arrived."""
    total = sum((fill.size for fill in fills), Decimal(0))
    base_fees = sum(
        (fill.fee for fill in fills if fill.fee_coin.upper() == base_currency.upper()),
        Decimal(0),
    )
    return total - base_fees


def _quote_spent(fills: list[PionexFill], quote_currency: str) -> Decimal:
    gross = sum((fill.size * fill.price for fill in fills), Decimal(0))
    quote_fees = sum(
        (fill.fee for fill in fills if fill.fee_coin.upper() == quote_currency.upper()),
        Decimal(0),
    )
    return gross + quote_fees


def _quote_returned(fills: list[PionexFill], quote_currency: str) -> Decimal:
    gross = sum((fill.size * fill.price for fill in fills), Decimal(0))
    quote_fees = sum(
        (fill.fee for fill in fills if fill.fee_coin.upper() == quote_currency.upper()),
        Decimal(0),
    )
    return gross - quote_fees


async def main() -> int:
    """Disposes the engine inside this event loop.

    Doing it from a second ``asyncio.run`` leaves asyncpg holding transports
    that belong to a loop which has already closed, and on Windows that
    surfaces as an AttributeError traceback printed over the actual output.
    """
    try:
        return await _run()
    finally:
        await engine.dispose()


async def _run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="ETH_USDT")
    parser.add_argument("--amount", type=Decimal, default=Decimal("10"))
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually place the orders; without it nothing is sent",
    )
    args = parser.parse_args()

    if args.amount > MAX_AMOUNT:
        print(f"--amount {args.amount} exceeds this script's cap of {MAX_AMOUNT}.")
        return 1

    settings = get_settings()
    base_currency, _, quote_currency = args.symbol.partition("_")
    credentials = await _load_credentials()

    print(f"Pionex base URL: {settings.pionex_base_url}")
    print(f"Credentials:     from the vault, {credentials!r}")
    print(f"Symbol:          {args.symbol}  (base {base_currency}, quote {quote_currency})")
    print(f"Amount:          {args.amount} {quote_currency}\n")

    async with read_only_client(settings, credentials) as reader:
        balances = {b.coin: b for b in await reader.spot_balances()}
    free_quote = balances[quote_currency].free if quote_currency in balances else Decimal(0)
    print(f"Free {quote_currency}: {free_quote}")
    if free_quote < args.amount:
        print(f"Not enough {quote_currency} to run this. Nothing was sent.")
        return 1

    async with trade_client(settings, credentials) as client:
        rules = await client.symbol_rules(args.symbol)
        rounded = rules.round_amount(args.amount)
        print(
            f"\nSymbol rules: basePrecision={rules.base_precision} "
            f"amountPrecision={rules.amount_precision} "
            f"minAmount={rules.min_amount} minTradeSize={rules.min_trade_size}"
        )
        print(f"Rounded buy amount: {rounded}")

        if not args.execute:
            body = {
                "symbol": args.symbol,
                "side": "BUY",
                "type": "MARKET",
                "clientOrderId": "<uuid4 generated at send time>",
                "amount": format(rounded.normalize(), "f"),
            }
            print("\nPREVIEW ONLY. This is the exact body that would be signed and sent:")
            print("  " + json.dumps(body, separators=(",", ":")))
            print(
                "\nThe sell leg is sized from the buy's fills and cannot be "
                "previewed.\nRe-run with --execute to place both."
            )
            return 0

        print("\n=== BUY ===")
        try:
            buy_id = await _place_buy(client, args.symbol, rounded)
        except PionexApiError as exc:
            return _report_refused_buy(exc)

        buy_fills = await _await_fills(client, buy_id, "buy")
        _render_fills("buy", buy_fills)

        received = _base_received(buy_fills, base_currency)
        spent = _quote_spent(buy_fills, quote_currency)
        print(f"\n  {base_currency} received (net of base fees): {received}")

        print("\n=== SELL ===")
        try:
            sell_id = await _place_sell(client, args.symbol, received)
        except PionexApiError as exc:
            print(f"  SELL REFUSED: {exc}")
            print(
                f"\n  !! {received} {base_currency} is still in the account. "
                "Sell it manually."
            )
            return 1

        sell_fills = await _await_fills(client, sell_id, "sell")
        _render_fills("sell", sell_fills)

        returned = _quote_returned(sell_fills, quote_currency)
        sold = sum((fill.size for fill in sell_fills), Decimal(0))

        print("\n=== ROUND TRIP ===")
        print(f"  {quote_currency} out:     {spent}")
        print(f"  {quote_currency} back:    {returned}")
        print(f"  net cost:      {spent - returned} {quote_currency}")
        print(f"  {base_currency} dust left: {received - sold}")
        print(
            "\n  Dust is expected: the sell is rounded DOWN to "
            f"basePrecision={rules.base_precision}, because rounding up would "
            "ask for more\n  than the account holds."
        )

    return 0


def _report_refused_buy(error: PionexApiError) -> int:
    """A refused buy is the expected outcome of several ordinary setup
    mistakes, so it gets a diagnosis rather than a traceback. This script is
    run at the one moment nobody wants to read a stack trace.

    Nothing was placed: Pionex answered before creating an order. That is worth
    stating plainly, because the natural fear on seeing an error here is that
    something half-happened.
    """
    print(f"  REFUSED: {error}")
    print(f"  code={error.code!r} http_status={error.http_status!r}")
    print("\n  Nothing was placed. Pionex refused the request itself.")

    if _looks_like_a_permission_problem(error):
        print(
            "\n  This reads as a PERMISSIONS refusal, not a signature one -- "
            "Pionex had to\n  authenticate the key before it could decide the "
            "key lacks rights, so the POST\n  signature was accepted."
        )
        print(
            "\n  The stored credential is almost certainly read-only. Create a "
            "Pionex API key\n  with trade permission enabled, then replace the "
            "stored one:\n"
            "      uv run python scripts/store_pionex_credentials.py"
        )
    return 1


def _looks_like_a_permission_problem(error: PionexApiError) -> bool:
    """Matched loosely and on purpose. This only selects which advice to print
    -- it never decides whether an order was placed, so a false positive costs
    a misleading hint and nothing more."""
    haystack = f"{error} {error.code or ''}".lower()
    return any(word in haystack for word in ("right", "permission", "forbidden", "auth"))


async def _place_buy(client: PionexTradeClient, symbol: str, amount: Decimal) -> str:
    client_order_id = str(uuid4())
    print(f"  clientOrderId: {client_order_id}")
    ack = await client.place_market_buy(
        symbol=symbol, client_order_id=client_order_id, quote_amount=amount
    )
    print(f"  accepted as orderId {ack.order_id}")
    return ack.client_order_id


async def _place_sell(client: PionexTradeClient, symbol: str, size: Decimal) -> str:
    client_order_id = str(uuid4())
    print(f"  clientOrderId: {client_order_id}")
    ack = await client.place_market_sell(
        symbol=symbol, client_order_id=client_order_id, base_size=size
    )
    print(f"  accepted as orderId {ack.order_id}")
    return ack.client_order_id


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
