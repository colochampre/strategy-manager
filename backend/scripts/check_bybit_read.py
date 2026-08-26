"""Manual check: read live Bybit state before anything is designed on top of it.

This is NOT a test. It needs real API credentials and it talks to the live
exchange, which is why it lives here and not under tests/ (CLAUDE.md rule 1:
no test may require a real API credential).

It is GET-only. The client it uses has no method that could place, amend or
cancel anything.

**Why read first, again.** The Pionex adapter was written against published
documentation and the venue disagreed with it twice — a contract-type field
that did not exist, and a single-symbol query that answered with a list. Both
failed silently. So the first thing this venue gets asked is not "place an
order", it is "what do you actually say".

What each read decides:

  CATALOGUE     Whether ``qty`` really is base-denominated, what the step and
                minimums are, and whether a symbol is a PERPETUAL or a dated
                future wearing the same category.
  BALANCE       What a capital pool would read as available.
  POSITIONS     The live position shape a close is sized from, and how
                direction is encoded — Bybit puts it in ``side`` where Pionex
                signs ``netSize``.
  LEVERAGE      Whether it is readable per symbol at all, which is what an
                opening order's size depends on.
  ACCOUNT       Margin mode and account type, printed verbatim because this is
                the read whose shape is least certain.

Usage:
    cd backend
    # BYBIT_API_KEY / BYBIT_API_SECRET must be set
    uv run python scripts/check_bybit_read.py
    uv run python scripts/check_bybit_read.py --symbol ETHUSDT
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.factory import (
    credentials_from_settings,
    read_only_client,
)
from strategy_manager.shared.infrastructure.bybit.read_client import (
    BybitReadOnlyClient,
    CoinBalance,
    PerpContract,
    Position,
)

DEFAULT_SYMBOL = "BTCUSDT"


@dataclass(frozen=True, slots=True)
class Probed[T]:
    """The outcome of one read: a value, or the fact that it failed.

    A plain ``T | None`` cannot express this. Several of these reads answer
    legitimately with an empty list, and a read that FAILED must never be
    mistaken for an account that simply holds nothing — that is the
    difference between "unknown" and "flat".
    """

    ok: bool
    value: T | None = None

    def render(self) -> str:
        return "unknown" if not self.ok else str(self.value)


async def probe[T](label: str, read: Callable[[], Awaitable[T]]) -> Probed[T]:
    """Runs one read and reports the outcome without aborting the others.

    An account read that fails must not hide a catalogue read that worked:
    when most of the surface is unknown, partial answers are the whole point.
    """
    try:
        value = await read()
    except BybitApiError as exc:
        print(f"\n{label}\n  FAILED -- code={exc.code!r} http={exc.http_status!r}: {exc}")
        return Probed[T](ok=False)
    print(f"\n{label}")
    return Probed(ok=True, value=value)


def _render_catalogue(contracts: list[PerpContract], symbol: str) -> None:
    perps = [c for c in contracts if c.is_perpetual]
    dated = [c for c in contracts if not c.is_perpetual]
    settles = sorted({c.settle_coin.upper() for c in contracts})

    print(f"  {len(contracts)} linear contracts: {len(perps)} perpetual, {len(dated)} dated")
    print(f"  contract types: {', '.join(sorted({c.contract_type for c in contracts}))}")
    print(f"  settlement currencies: {', '.join(settles)}")
    if dated:
        print("  DATED contracts share the 'linear' category and EXPIRE under a")
        print(f"  position. Examples: {', '.join(c.symbol for c in dated[:5])}")

    match = next((c for c in contracts if c.symbol == symbol.upper()), None)
    if match is None:
        print(f"  {symbol} is NOT listed")
        return

    print(f"\n  {match.symbol}: {match.contract_type}, status={match.status}")
    print(f"    base={match.base_coin} quote={match.quote_coin} settle={match.settle_coin}")
    print(f"    qtyStep={match.qty_step}   <- the step an order size truncates to")
    print(f"    minOrderQty={match.min_order_qty}  maxOrderQty={match.max_order_qty}")
    print(f"    minNotionalValue={match.min_notional}")
    print(f"    tickSize={match.tick_size}  maxLeverage={match.max_leverage}x")


def _render_balance(balances: list[CoinBalance]) -> None:
    funded = [b for b in balances if b.wallet_balance]
    print(f"  {len(balances)} coins reported, {len(funded)} with a balance")
    for balance in funded:
        print(
            f"    {balance.coin:<8} wallet={balance.wallet_balance} "
            f"equity={balance.equity} withdrawable={balance.available_to_withdraw}"
        )


def _render_positions(positions: list[Position]) -> None:
    open_positions = [p for p in positions if p.size]
    print(f"  {len(positions)} reported, {len(open_positions)} actually open")
    for position in open_positions:
        print(
            f"    {position.symbol:<12} {position.side:<4} size={position.size} "
            f"signed={position.signed_size} @ {position.avg_price} "
            f"{position.leverage}x idx={position.position_idx}"
        )


def _verdict(label: str, answer: Probed[str], note: str) -> None:
    print(f"  {label:<24} {answer.render()}")
    print(f"  {'':<24} {note}")


def _qty_denomination(contracts: Probed[list[PerpContract]], symbol: str) -> Probed[str]:
    """The one number that cannot be got wrong quietly.

    If ``qty`` were denominated in contracts rather than base coin, every
    order this system builds would be wrong by the contract multiplier. The
    catalogue settles it: a base coin whose step is a fraction of a coin is
    a base-denominated quantity, not a contract count.
    """
    if not contracts.ok or contracts.value is None:
        return Probed[str](ok=False)

    match = next((c for c in contracts.value if c.symbol == symbol.upper()), None)
    if match is None:
        return Probed[str](ok=False)

    reads_as_base = match.qty_step < 1
    return Probed(
        ok=True,
        value=(
            f"step {match.qty_step} in {match.base_coin} -> "
            + ("BASE coin" if reads_as_base else "REVIEW: step >= 1, check for a multiplier")
        ),
    )


async def _run(symbol: str, client: BybitReadOnlyClient) -> bool:
    contracts = await probe(
        "CATALOGUE  GET /v5/market/instruments-info?category=linear",
        client.perp_contracts,
    )
    if contracts.value is not None:
        _render_catalogue(contracts.value, symbol)

    price = await probe(
        f"TICKER     GET /v5/market/tickers?symbol={symbol}",
        lambda: client.last_price(symbol),
    )
    if price.value is not None:
        print(f"  last price {price.value}")

    balances = await probe(
        "BALANCE    GET /v5/account/wallet-balance?accountType=UNIFIED",
        client.wallet_balance,
    )
    if balances.value is not None:
        _render_balance(balances.value)

    positions = await probe(
        "POSITIONS  GET /v5/position/list?category=linear&settleCoin=USDT",
        client.positions,
    )
    if positions.value is not None:
        _render_positions(positions.value)

    leverage = await probe(
        f"LEVERAGE   GET /v5/position/list?symbol={symbol}",
        lambda: client.leverage_for(symbol),
    )
    if leverage.value is not None:
        print(f"  {symbol} is configured at {leverage.value}x")

    account = await probe("ACCOUNT    GET /v5/account/info", client.account_info)
    if account.value is not None:
        print("  " + json.dumps(account.value, indent=2).replace("\n", "\n  "))

    print("\n--- what this settles ---")
    _verdict(
        "qty denomination",
        _qty_denomination(contracts, symbol),
        "the number that would be wrong by a whole multiplier if assumed.",
    )
    _verdict(
        "leverage readable",
        Probed(ok=leverage.ok, value=f"{leverage.value}x" if leverage.ok else None),
        "an opening order's size is granted * leverage / price.",
    )
    _verdict(
        "futures orders reachable",
        Probed(ok=True, value="not tested here - this probe never writes"),
        "that is the next probe, and Bybit has a testnet for it.",
    )
    return contracts.ok


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    args = parser.parse_args()

    settings = get_settings()
    credentials = credentials_from_settings(settings)

    print(f"Bybit base URL: {settings.bybit_base_url}")
    print(f"Signing as ***{credentials.api_key[-4:]}  (from the environment)")
    print(f"Symbol under inspection: {args.symbol}")
    print("This probe is GET-only: it places nothing and changes no setting.")

    async with read_only_client(settings, credentials) as client:
        catalogue_ok = await _run(args.symbol, client)

    return 0 if catalogue_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
