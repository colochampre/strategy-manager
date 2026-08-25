"""Manual check: can this system WRITE the futures account settings?

This is NOT a test. It needs real API credentials and it writes to the live
account (CLAUDE.md rule 1: no test may require a real API credential).

**It is idempotent by construction.** It reads the current leverage and margin
mode, writes those exact values back, and reads again to confirm nothing
moved. There is no value to supply and no flag to change one: the numbers come
from the account, never from this script. If a read fails, it aborts rather
than guessing -- writing a guessed leverage is precisely the thing that must
never happen.

**Why write at all.** Two things were logged as unproven: `POST
/uapi/v1/account/leverage` and `POST /uapi/v1/trade/isolatedMode`. Reading both
works. Neither write has ever been exercised, so nothing is known about the
request shape it accepts, the response it returns, or whether the values it
takes are even spelled the same way the read returns them -- the reference
lists margin modes as CROSS / ISOLATED_BOTH / ISOLATED_LONG / ISOLATED_SHORT,
while the read answers a plain ISOLATED. That mismatch is exactly the kind
this venue has already produced twice.

**Why it is safe right now.** The futures wallet is empty and holds no
positions, so leverage and margin mode govern nothing. This refuses to run if
that stops being true: with a position open, changing either setting is a real
risk decision and belongs to a human, not to a probe.

Usage:
    cd backend
    # PIONEX_API_KEY / PIONEX_API_SECRET must be set
    uv run python scripts/check_pionex_futures_settings.py
    uv run python scripts/check_pionex_futures_settings.py --symbol ETH_USDT_PERP
"""

import argparse
import asyncio
import json
import sys
from typing import Any

from probe_credentials import announce, vault_credentials

from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.factory import (
    futures_read_only_client,
    signed_transport,
)
from strategy_manager.shared.infrastructure.pionex.futures_read_client import (
    LEVERAGE_PATH,
    MARGIN_MODE_PATH,
    PionexFuturesReadClient,
)

DEFAULT_SYMBOL = "BTC_USDT_PERP"


async def _assert_no_open_positions(client: PionexFuturesReadClient) -> None:
    """With a position open, changing leverage or margin mode is a real risk
    decision. A probe does not get to make it."""
    positions = await client.positions()
    if positions:
        held = ", ".join(f"{p.symbol} {p.net_size}" for p in positions)
        raise SystemExit(
            f"REFUSING: the futures account holds open positions ({held}). "
            "Changing leverage or margin mode with a position open changes its "
            "liquidation price. Close them first, or make this change by hand."
        )


async def _round_trip(
    transport: Any,
    label: str,
    path: str,
    read: Any,
    body: dict[str, Any],
    field: str,
) -> bool:
    before = await read()
    print(f"\n{label}")
    print(f"  before   {before}")

    payload = {**body, field: str(before)}
    print(f"  POST {path}")
    print(f"       {json.dumps(payload, separators=(',', ':'))}")

    try:
        data = await transport.post(path, payload)
    except PionexApiError as exc:
        print(f"  WRITE FAILED -- code={exc.code!r} http={exc.http_status!r}: {exc}")
        return False

    print(f"  response {json.dumps(data) if data is not None else 'no data object'}")

    after = await read()
    print(f"  after    {after}")
    if str(after) != str(before):
        print("  WARNING: the value CHANGED. It was written back as read, so the")
        print("           venue interprets this field differently than it reports it.")
        return False

    print("  round trip clean: written back as read, unchanged.")
    return True


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    args = parser.parse_args()

    settings = get_settings()

    print(f"Pionex base URL: {settings.pionex_base_url}")
    print(f"Symbol: {args.symbol}")
    print("This probe writes back exactly what it reads. It places no orders.")

    # From the VAULT, not the environment. The environment holds the read-only
    # key, and a write refused for the wrong key looks identical to one refused
    # because the venue does not allow it. That mistake has already been made
    # once here.
    async with vault_credentials(settings) as credentials:
        announce(credentials, "vault")
        return await _run(args.symbol, settings, credentials)


async def _run(symbol: str, settings: Any, credentials: Any) -> int:
    async with futures_read_only_client(settings, credentials) as reader:
        await _assert_no_open_positions(reader)
        print("\nno open positions: leverage and margin mode govern nothing right now")

        async with signed_transport(settings, credentials) as transport:
            leverage_ok = await _round_trip(
                transport,
                f"LEVERAGE     {symbol}",
                LEVERAGE_PATH,
                lambda: reader.leverage_for(symbol),
                {"symbol": symbol},
                "leverage",
            )
            margin_ok = await _round_trip(
                transport,
                f"MARGIN MODE  {symbol}",
                MARGIN_MODE_PATH,
                lambda: reader.margin_mode_for(symbol),
                {"symbol": symbol},
                "isolatedMode",
            )

    print("\n--- what this settles ---")
    print(f"  leverage is writable:    {leverage_ok}")
    print(f"  margin mode is writable: {margin_ok}")
    print(
        "  A failure here is information, not a defect: it means the system "
        "cannot own\n  these settings and must read whatever the owner "
        "configures in Pionex's UI."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
