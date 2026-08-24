"""Manual check: read live Pionex FUTURES state through the read-only adapter.

This is NOT a test. It needs real API credentials and it talks to the live
exchange, which is why it lives here and not under tests/ (CLAUDE.md rule 1:
no test may require a real API credential).

It places nothing, cancels nothing and changes no setting. Every call it makes
is a GET, and the client it uses has no method that could do otherwise.

It exists to answer, before the futures execution adapter is designed, the
questions that the spot adapter proved cannot be answered from the docs:

  1. LEVERAGE -- logged as an open risk ("no leverage-setting endpoint is
     documented"). The published reference now documents GET/POST
     /uapi/v1/account/leverage. This reads it. A successful read is what
     turns that risk into a fact; it does not prove the write works, and this
     script deliberately does not try.
  2. COIN-M -- logged as an open risk ("coverage via the API is unconfirmed").
     The perpetual catalogue settles it: a coin-margined contract would list
     a non-USDT quote currency.
  3. POSITION MODE -- BUYSELL or OPENCLOSE. This decides whether a REVERSE is
     one order or two, so it is not a detail.
  4. MARGIN MODE -- the earlier note recorded CROSS/ISOLATED as an order
     parameter. The reference puts it on /uapi/v1/trade/isolatedMode, which
     makes it a per-symbol setting instead. This reads which one the account
     actually reports.
  5. PRECISION -- the numbers that silently rejected every spot order until
     they were enforced. Better to learn the futures equivalents now.

Usage:
    cd backend
    # PIONEX_API_KEY / PIONEX_API_SECRET must be set
    uv run python scripts/check_pionex_futures.py
    uv run python scripts/check_pionex_futures.py --symbol ETH_USDT_PERP
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.factory import (
    credentials_from_settings,
    futures_read_only_client,
)
from strategy_manager.shared.infrastructure.pionex.futures_read_client import (
    FuturesPosition,
    LeverageTier,
    PerpContract,
    PionexFuturesReadClient,
)

DEFAULT_SYMBOL = "BTC_USDT_PERP"


@dataclass(frozen=True, slots=True)
class Probed[T]:
    """The outcome of one read: a value, or the fact that it failed.

    A plain ``T | None`` cannot express this. Several of these reads answer
    legitimately with an empty list or no value at all, and a read that
    failed must never be mistaken for an account that simply holds no
    positions -- that is the difference between "unknown" and "flat".
    """

    ok: bool
    value: T | None = None

    def render(self) -> str:
        return "unknown" if not self.ok else str(self.value)


async def probe[T](label: str, read: Callable[[], Awaitable[T]]) -> Probed[T]:
    """Runs one read and reports the outcome without aborting the others.

    A futures account read that fails must not hide the catalogue read that
    worked -- when half the surface is unknown, partial answers are the whole
    point of running this.
    """
    try:
        value = await read()
    except PionexApiError as exc:
        print(f"\n{label}\n  FAILED -- {exc}")
        return Probed[T](ok=False)
    print(f"\n{label}")
    return Probed(ok=True, value=value)


def _render_catalogue(contracts: list[PerpContract], symbol: str) -> None:
    trading = [c for c in contracts if c.is_trading]
    quotes = sorted({c.quote_currency.upper() for c in contracts})
    non_usdt = [c for c in contracts if not c.is_usdt_margined]

    print(f"  {len(contracts)} perpetual contracts, {len(trading)} TRADING")
    print(f"  settlement currencies: {', '.join(quotes)}")
    print(f"  non-USDT-margined contracts: {len(non_usdt)}")
    for contract in non_usdt[:10]:
        print(f"    {contract.symbol:<20} quote={contract.quote_currency}")

    match = next((c for c in contracts if c.symbol == symbol.upper()), None)
    if match is None:
        print(f"  {symbol} is NOT listed as a perpetual market")
        return

    print(f"  {match.symbol}: {match.contract_type}, status={match.status}")
    print(
        f"    basePrecision={match.base_precision}  "
        f"quotePrecision={match.quote_precision}"
    )
    print(f"    baseStep={match.base_step}  quoteStep={match.quote_step}")
    print(f"    minNotional={match.min_notional}")
    print(
        f"    minSizeMarket={match.min_size_market}  "
        f"maxSizeMarket={match.max_size_market}"
    )


def _render_tiers(tiers: list[LeverageTier]) -> None:
    print(f"  {len(tiers)} notional bands")
    for tier in tiers[:5]:
        print(
            f"    row {tier.row_num}: up to {tier.notional_limit} "
            f"-> max {tier.max_leverage}x, maint margin {tier.maint_margin_ratio}"
        )
    if len(tiers) > 5:
        print(f"    ... {len(tiers) - 5} more")


def _render_positions(positions: list[FuturesPosition]) -> None:
    print(f"  {len(positions)} open")
    for position in positions:
        print(
            f"    {position.symbol:<20} {position.position_side:<6} "
            f"net={position.net_size} @ {position.avg_price} "
            f"{position.leverage}x {position.isolated_mode}"
        )


def _verdict(label: str, answer: Probed[str], note: str) -> None:
    print(f"  {label:<26} {answer.render()}")
    print(f"  {'':<26} {note}")


def _coin_m_answer(contracts: Probed[list[PerpContract]]) -> Probed[str]:
    """Reduces the catalogue to the one fact the COIN-M open risk asks for."""
    if not contracts.ok or contracts.value is None:
        return Probed[str](ok=False)
    non_usdt = sorted(
        {c.quote_currency.upper() for c in contracts.value if not c.is_usdt_margined}
    )
    return Probed(ok=True, value=", ".join(non_usdt) or "no, USDT-margined only")


async def _run(symbol: str, client: PionexFuturesReadClient) -> bool:
    contracts = await probe(
        "CATALOGUE     GET /api/v1/common/symbols?type=PERP", client.perp_contracts
    )
    if contracts.value is not None:
        _render_catalogue(contracts.value, symbol)

    tiers = await probe(
        f"RISK TABLE    GET /api/v1/common/riskTable?symbol={symbol}",
        lambda: client.leverage_tiers(symbol),
    )
    if tiers.value is not None:
        _render_tiers(tiers.value)

    positions = await probe(
        "POSITIONS     GET /uapi/v1/account/positions", client.positions
    )
    if positions.value is not None:
        _render_positions(positions.value)

    leverage = await probe(
        f"LEVERAGE      GET /uapi/v1/account/leverage?symbol={symbol}",
        lambda: client.leverage_for(symbol),
    )
    if leverage.value is not None:
        print(f"  {symbol} is configured at {leverage.value}x")

    margin_mode = await probe(
        f"MARGIN MODE   GET /uapi/v1/trade/isolatedMode?symbol={symbol}",
        lambda: client.margin_mode_for(symbol),
    )
    if margin_mode.value is not None:
        print(f"  {symbol} is on {margin_mode.value} margin")

    position_mode = await probe(
        "POSITION MODE GET /uapi/v1/account/positionMode", client.position_mode
    )
    if position_mode.value is not None:
        print(f"  account is in {position_mode.value} mode")

    print("\n--- what this settles ---")
    _verdict(
        "leverage readable",
        Probed(ok=leverage.ok, value=f"{leverage.value}x" if leverage.ok else None),
        "a read proves the endpoint exists; the WRITE is still unproven.",
    )
    _verdict(
        "COIN-M reachable",
        _coin_m_answer(contracts),
        "any non-USDT quote currency in the catalogue means COIN-M is listed.",
    )
    _verdict(
        "position mode",
        position_mode,
        "BUYSELL = one-way, a REVERSE is one order. OPENCLOSE = hedged, two.",
    )
    _verdict(
        "margin mode is a setting",
        margin_mode,
        "read per symbol, so it is NOT an order parameter as first recorded.",
    )

    return contracts.ok


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbol",
        default=DEFAULT_SYMBOL,
        help=f"perpetual symbol to inspect (default: {DEFAULT_SYMBOL})",
    )
    args = parser.parse_args()

    settings = get_settings()
    print(f"Pionex base URL: {settings.pionex_base_url}")
    print(f"Symbol under inspection: {args.symbol}")
    print("This probe is GET-only: it places nothing and changes no setting.")

    credentials = credentials_from_settings(settings)
    async with futures_read_only_client(settings, credentials) as client:
        catalogue_ok = await _run(args.symbol, client)

    return 0 if catalogue_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
