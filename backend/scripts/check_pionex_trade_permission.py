"""Manual check: is a trade refusal about the KEY, or about the venue?

This is NOT a test. It needs real API credentials and it sends two real order
requests to the live exchange (CLAUDE.md rule 1: no test may require a real
API credential).

**Neither order can be filled, by construction.** Both are sized an order of
magnitude BELOW the symbol's published minimum, so a venue that gets as far as
looking at the numbers must refuse them. That is the point: the refusal each
one comes back with is the measurement.

**The question it answers.** A futures order was refused with
`TRADE_TYPE_DENIED` / "user denied not in whitelist". Three explanations fit
that equally well from the outside:

  1. the API key lacks trade permission
  2. the key is blocked by an IP allowlist
  3. the key trades fine, and the futures API specifically does not accept
     this user

Sending the SAME key at both APIs separates them in one run. If spot answers
with a filter error, the venue parsed and validated that order -- so the key
trades, from this IP, over the API. Any futures refusal after that is about
futures, not about the key.

VERIFIED 2026-08-25 on the owner's account, whose key carries every permission
Pionex offers and no IP restriction:

    SPOT     TRADE_AMOUNT_FILTER_DENIED   "amount filter dendied"
    FUTURES  TRADE_TYPE_DENIED            "user denied not in whitelist"

Spot reached field validation. Futures did not reach it at all -- the size sent
was below the contract minimum and the venue never mentioned the size. So the
gate precedes validation and is decided per USER, which is consistent with the
docs index labelling the futures section "Internal": API access to futures
trading appears to be an allowlist Pionex grants, not a key permission or an
account setting the owner can toggle.

Keep this script. It is the reproducible evidence for asking them.

Usage:
    cd backend
    uv run python scripts/check_pionex_trade_permission.py
"""

import asyncio
import sys
from typing import Any
from uuid import uuid4

from probe_credentials import announce, vault_credentials

from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.factory import signed_transport

SPOT_ORDER_PATH = "/api/v1/trade/order"
FUTURES_ORDER_PATH = "/uapi/v1/trade/order"

# Both are far below the published minimums (BTC_USDT minAmount is 10 USDT;
# ETH_USDT_PERP minSizeMarket is 0.001 ETH). Nothing here can be bought.
UNFILLABLE_SPOT_AMOUNT = "0.1"
UNFILLABLE_FUTURES_SIZE = "0.000001"

# A refusal naming the ORDER's numbers means the venue parsed and validated it,
# which is only reachable once the caller is allowed to trade at all.
VALIDATION_CODES = frozenset(
    {"TRADE_AMOUNT_FILTER_DENIED", "TRADE_SIZE_FILTER_DENIED"}
)


async def _attempt(
    transport: Any, label: str, path: str, payload: dict[str, Any]
) -> str | None:
    print(f"\n{label}")
    print(f"  POST {path}")
    try:
        data = await transport.post(path, payload)
    except PionexApiError as exc:
        reached = "reached field validation" if exc.code in VALIDATION_CODES else "refused earlier"
        print(f"  REJECTED  code={exc.code!r}: {exc}")
        print(f"            -> {reached}")
        return exc.code

    print(f"  ACCEPTED  {data!r}")
    print("            -> UNEXPECTED. Check the account: an order may exist.")
    return None


async def main() -> int:
    settings = get_settings()
    print(f"Pionex base URL: {settings.pionex_base_url}")
    print("Both orders are below the venue minimums and cannot fill.\n")

    async with vault_credentials(settings) as credentials:
        announce(credentials, "vault")
        async with signed_transport(settings, credentials) as transport:
            spot = await _attempt(
                transport,
                "SPOT     BTC_USDT, amount far below minAmount",
                SPOT_ORDER_PATH,
                {
                    "symbol": "BTC_USDT",
                    "side": "BUY",
                    "type": "MARKET",
                    "clientOrderId": str(uuid4()),
                    "amount": UNFILLABLE_SPOT_AMOUNT,
                },
            )
            futures = await _attempt(
                transport,
                "FUTURES  ETH_USDT_PERP, size far below minSizeMarket",
                FUTURES_ORDER_PATH,
                {
                    "symbol": "ETH_USDT_PERP",
                    "side": "BUY",
                    "type": "MARKET_QTY",
                    "clientOrderId": str(uuid4()),
                    "size": UNFILLABLE_FUTURES_SIZE,
                    "reduceOnly": False,
                },
            )

    print("\n--- what this settles ---")
    if spot in VALIDATION_CODES and futures not in VALIDATION_CODES:
        print("  The KEY trades. Spot parsed and validated the order, from this")
        print("  IP, over the API. So the futures refusal is not about the key's")
        print("  permissions and not about an IP allowlist.")
        print(f"\n  Futures answered {futures!r} without ever mentioning the size,")
        print("  which was itself invalid -- the gate is decided before validation")
        print("  and per user. Ask Pionex for API access to futures trading; it is")
        print("  not a toggle in the key's permissions.")
    elif spot not in VALIDATION_CODES:
        print(f"  Spot did NOT reach validation either ({spot!r}). The problem is")
        print("  the key or its access, not futures specifically.")
    else:
        print(f"  spot={spot!r}  futures={futures!r} -- read both messages above.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
