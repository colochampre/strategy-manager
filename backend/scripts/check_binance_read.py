"""Manual check: read live Binance state before anything is designed on top of it.

This is NOT a test. It needs real API credentials and talks to the live
exchange, which is why it lives here and not under tests/ (CLAUDE.md rule 1).

It is GET-only. The transport it uses has no way to send anything else.

**Why read first, again.** Pionex's documentation disagreed with the venue in
four places, and every one of them failed silently. So Binance is asked "what
do you actually say" before an adapter is written against what its docs claim.

What each read decides:

  KEY           Whether the key in the environment really is read-only. A key
                with trading or transfer permissions has no business in .env.
  CLOCK         The skew against Binance's clock. A timestamp 1000ms ahead is
                rejected, which would look like a signature problem.
  WALLETS       Whether the account really keeps spot, futures, funding and
                the rest apart -- the fact the pool design rests on.
  FUTURES       The USDT figures a USDⓈ-M pool would size from and cap at:
                walletBalance, availableBalance, committed margin, unrealized PnL.
  MULTI-ASSETS  Must be OFF. In Multi-Assets Mode the totals are USD and USDT
                and USDC collateral is shared, which breaks rule 7.
  POSITION MODE Must be one-way. A hedged account lets a close open the other
                side, the same reason Pionex requires BUYSELL.
  CATALOGUE     Per symbol: PERPETUAL or dated, lot step, minimum notional.
  SYMBOL CONFIG Per symbol: the leverage and margin type an order would use.
  COMMISSION    Per symbol: the maker and taker rates actually charged.

Usage:
    cd backend
    # BINANCE_API_KEY / BINANCE_API_SECRET must be set
    uv run python scripts/check_binance_read.py
    uv run python scripts/check_binance_read.py --symbol ETHUSDT --symbol SOLUSDT
"""

import argparse
import asyncio
import io
import json
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.factory import (
    credentials_from_settings,
    futures_transport,
    spot_transport,
)
from strategy_manager.shared.infrastructure.binance.transport import BinanceTransport

DEFAULT_SYMBOL = "BTCUSDT"

# Permissions that let a key change something. Reading is the only one allowed.
WRITE_PERMISSIONS = (
    "enableWithdrawals",
    "enableInternalTransfer",
    "permitsUniversalTransfer",
    "enableMargin",
    "enableFutures",
    "enableSpotAndMarginTrading",
    "enableVanillaOptions",
    "enablePortfolioMarginTrading",
    "enableFixApiTrade",
)

# Binance rejects a request timestamped this far ahead of its own clock.
MAX_AHEAD_MS = 1000


@dataclass(frozen=True, slots=True)
class Probed:
    """One read's outcome. A failed read must never pass for an empty answer."""

    ok: bool
    value: Any = None


async def probe(label: str, read: Callable[[], Awaitable[Any]]) -> Probed:
    """Runs one read without letting its failure hide the others."""
    try:
        value = await read()
    except BinanceApiError as exc:
        print(f"\n{label}\n  FAILED -- code={exc.code!r} http={exc.http_status!r}: {exc}")
        return Probed(ok=False)
    print(f"\n{label}")
    return Probed(ok=True, value=value)


def _dump(value: Any) -> None:
    print("  " + json.dumps(value, indent=2).replace("\n", "\n  "))


def _render_key(permissions: dict[str, Any]) -> list[str]:
    for name in ("enableReading", *WRITE_PERMISSIONS, "ipRestrict"):
        print(f"  {name:<30} {permissions.get(name)}")
    return [name for name in WRITE_PERMISSIONS if permissions.get(name) is True]


def _render_clock(server: dict[str, Any], sent_at_ms: int, received_at_ms: int) -> int:
    local_mid = (sent_at_ms + received_at_ms) // 2
    skew = local_mid - int(server["serverTime"])
    print(f"  server {server['serverTime']}  local {local_mid}  local-minus-server {skew} ms")
    print(f"  round trip {received_at_ms - sent_at_ms} ms")
    return skew


def _render_wallets(wallets: list[dict[str, Any]]) -> None:
    print("  balances valued in USDT, one row per wallet Binance reports")
    for wallet in wallets:
        print(
            f"    {wallet.get('walletName', '?'):<20} activate={wallet.get('activate')!s:<5} "
            f"balance={wallet.get('balance')}"
        )


def _usdt_asset(account: dict[str, Any]) -> dict[str, Any] | None:
    return next((a for a in account.get("assets", []) if a.get("asset") == "USDT"), None)


def _render_futures(account: dict[str, Any]) -> None:
    print("  account-level totals (USDT in single-asset mode, USD in multi-assets mode):")
    for name in (
        "totalWalletBalance",
        "totalMarginBalance",
        "totalUnrealizedProfit",
        "availableBalance",
        "totalPositionInitialMargin",
        "totalOpenOrderInitialMargin",
        "maxWithdrawAmount",
    ):
        print(f"    {name:<28} {account.get(name)}")

    funded = [a for a in account.get("assets", []) if Decimal(str(a.get("walletBalance", "0")))]
    print(f"  assets with a wallet balance: {', '.join(a['asset'] for a in funded) or 'none'}")

    usdt = _usdt_asset(account)
    if usdt is None:
        print("  no USDT asset reported")
    else:
        print("  USDT asset:")
        for name in (
            "walletBalance",
            "marginBalance",
            "unrealizedProfit",
            "availableBalance",
            "positionInitialMargin",
            "openOrderInitialMargin",
            "maxWithdrawAmount",
        ):
            print(f"    {name:<24} {usdt.get(name)}")

    open_positions = [
        p for p in account.get("positions", []) if Decimal(str(p.get("positionAmt", "0")))
    ]
    print(f"  open positions: {len(open_positions)}")
    for position in open_positions:
        print(
            f"    {position.get('symbol'):<14} side={position.get('positionSide')} "
            f"amt={position.get('positionAmt')} notional={position.get('notional')} "
            f"isolatedWallet={position.get('isolatedWallet')}"
        )


def _filter(symbol: dict[str, Any], kind: str) -> dict[str, Any]:
    return next((f for f in symbol.get("filters", []) if f.get("filterType") == kind), {})


def _render_catalogue(info: dict[str, Any], symbols: list[str]) -> None:
    listed = info.get("symbols", [])
    by_type: dict[str, int] = {}
    for entry in listed:
        kind = entry.get("contractType") or "?"
        by_type[kind] = by_type.get(kind, 0) + 1
    print(f"  {len(listed)} symbols; by contractType: {by_type}")

    for wanted in symbols:
        match = next((s for s in listed if s.get("symbol") == wanted), None)
        if match is None:
            print(f"\n  {wanted} is NOT listed")
            continue
        lot = _filter(match, "LOT_SIZE")
        market_lot = _filter(match, "MARKET_LOT_SIZE")
        price = _filter(match, "PRICE_FILTER")
        notional = _filter(match, "MIN_NOTIONAL")
        print(
            f"\n  {wanted}: contractType={match.get('contractType')} "
            f"status={match.get('status')}"
        )
        print(
            f"    base={match.get('baseAsset')} quote={match.get('quoteAsset')} "
            f"margin={match.get('marginAsset')}"
        )
        print(
            f"    LOT_SIZE        step={lot.get('stepSize')} "
            f"min={lot.get('minQty')} max={lot.get('maxQty')}"
        )
        print(
            f"    MARKET_LOT_SIZE step={market_lot.get('stepSize')} min={market_lot.get('minQty')} "
            f"max={market_lot.get('maxQty')}"
        )
        print(f"    MIN_NOTIONAL    {notional.get('notional')}   tickSize={price.get('tickSize')}")


def _verdict(label: str, value: str, note: str) -> None:
    print(f"  {label:<22} {value}")
    print(f"  {'':<22} {note}")


async def _run(symbols: list[str], spot: BinanceTransport, futures: BinanceTransport) -> bool:
    key = await probe(
        "KEY           GET /sapi/v1/account/apiRestrictions",
        lambda: spot.get_signed("/sapi/v1/account/apiRestrictions"),
    )
    write_permissions = _render_key(key.value) if key.ok else []

    sent_at = int(time.time() * 1000)
    clock = await probe(
        "CLOCK         GET /fapi/v1/time", lambda: futures.get_public("/fapi/v1/time")
    )
    skew = _render_clock(clock.value, sent_at, int(time.time() * 1000)) if clock.ok else None

    wallets = await probe(
        "WALLETS       GET /sapi/v1/asset/wallet/balance?quoteAsset=USDT",
        lambda: spot.get_signed("/sapi/v1/asset/wallet/balance", {"quoteAsset": "USDT"}),
    )
    if wallets.ok:
        _render_wallets(wallets.value)

    account = await probe(
        "FUTURES       GET /fapi/v3/account", lambda: futures.get_signed("/fapi/v3/account")
    )
    if account.ok:
        _render_futures(account.value)

    multi_assets = await probe(
        "MULTI-ASSETS  GET /fapi/v1/multiAssetsMargin",
        lambda: futures.get_signed("/fapi/v1/multiAssetsMargin"),
    )
    if multi_assets.ok:
        _dump(multi_assets.value)

    position_mode = await probe(
        "POSITION MODE GET /fapi/v1/positionSide/dual",
        lambda: futures.get_signed("/fapi/v1/positionSide/dual"),
    )
    if position_mode.ok:
        _dump(position_mode.value)

    catalogue = await probe(
        "CATALOGUE     GET /fapi/v1/exchangeInfo",
        lambda: futures.get_public("/fapi/v1/exchangeInfo"),
    )
    if catalogue.ok:
        _render_catalogue(catalogue.value, symbols)

    for symbol in symbols:
        config = await probe(
            f"SYMBOL CONFIG GET /fapi/v1/symbolConfig?symbol={symbol}",
            lambda symbol=symbol: futures.get_signed("/fapi/v1/symbolConfig", {"symbol": symbol}),
        )
        if config.ok:
            _dump(config.value)

        commission = await probe(
            f"COMMISSION    GET /fapi/v1/commissionRate?symbol={symbol}",
            lambda symbol=symbol: futures.get_signed("/fapi/v1/commissionRate", {"symbol": symbol}),
        )
        if commission.ok:
            _dump(commission.value)

    print("\n--- what this settles ---")
    _verdict(
        "key is read-only",
        ("YES" if not write_permissions else f"NO: {write_permissions}")
        if key.ok
        else "unknown",
        "a key that can trade or transfer does not belong in .env.",
    )
    _verdict(
        "clock skew",
        "unknown"
        if skew is None
        else f"{skew} ms" + (" -- TOO FAR AHEAD" if skew >= MAX_AHEAD_MS else ""),
        "Binance rejects a timestamp 1000 ms or more ahead of its clock.",
    )
    _verdict(
        "single-asset mode",
        "unknown"
        if not multi_assets.ok
        else (
            "YES"
            if multi_assets.value.get("multiAssetsMargin") is False
            else "NO -- multi-assets ON"
        ),
        "required: multi-assets mode reports USD totals and shares collateral.",
    )
    _verdict(
        "one-way position mode",
        "unknown"
        if not position_mode.ok
        else (
            "YES"
            if position_mode.value.get("dualSidePosition") is False
            else "NO -- hedge mode ON"
        ),
        "required: in hedge mode a close can open the opposite side.",
    )
    usdt = _usdt_asset(account.value) if account.ok else None
    _verdict(
        "USDⓈ-M USDT pool",
        "unknown"
        if usdt is None
        else (
            f"total(walletBalance)={usdt.get('walletBalance')} "
            f"available={usdt.get('availableBalance')}"
        ),
        "what the pool would size from and cap at, before the adapter decides.",
    )
    return key.ok and account.ok


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append", dest="symbols")
    args = parser.parse_args()
    symbols = [s.upper() for s in (args.symbols or [DEFAULT_SYMBOL])]

    settings = get_settings()
    credentials = credentials_from_settings(settings)

    print(f"Binance futures URL: {settings.binance_futures_base_url}")
    print(f"Binance spot URL:    {settings.binance_spot_base_url}")
    print(f"Signing as ***{credentials.api_key[-4:]}  (from the environment)")
    print(f"Symbols under inspection: {', '.join(symbols)}")
    print("This probe is GET-only: it places nothing and changes no setting.")

    async with (
        spot_transport(settings, credentials) as spot,
        futures_transport(settings, credentials) as futures,
    ):
        ok = await _run(symbols, spot, futures)

    return 0 if ok else 1


if __name__ == "__main__":
    # Binance names a wallet "USDⓈ-M Futures". A Windows console defaults to
    # cp1252, which cannot encode that character and would abort the probe
    # halfway through its reads.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
