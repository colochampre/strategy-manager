"""Manual check: what does the FUTURES API answer when an order does not exist?

This is NOT a test. It needs real API credentials and talks to the live
exchange (CLAUDE.md rule 1: no test may require a real API credential).

It is read-only. It looks up a random UUID as a client order id -- an id no
order can possibly carry, because client order ids are generated per order and
this one was generated here and never sent with anything. It places nothing.

**Why this matters more than it looks.** ``SettleExecution`` reads
``OrderNotFound`` as "the order never reached the exchange, release the
capital". Every other failure means "we do not know, retry". Mistaking a
failed call for "no such order" releases the capital backing a live position
and closes the only door left to discovering it.

Spot's answer was ``TRADE_ORDER_NOT_EXIST``, over HTTP 200, in the envelope --
and three plausible-sounding names had been guessed before that probe ran, all
three wrong. The futures API is a different base path, so its answer is a
different fact and gets its own probe rather than an assumption.

Usage:
    cd backend
    # PIONEX_API_KEY / PIONEX_API_SECRET must be set
    uv run python scripts/check_pionex_futures_lookup.py
"""

import asyncio
import sys
from uuid import uuid4

from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.factory import (
    credentials_from_settings,
    signed_transport,
)
from strategy_manager.shared.infrastructure.pionex.futures_trade_client import (
    ORDER_BY_CLIENT_ORDER_ID_PATH,
    ORDER_NOT_FOUND_CODES,
)


async def main() -> int:
    settings = get_settings()
    client_order_id = str(uuid4())

    print(f"Pionex base URL: {settings.pionex_base_url}")
    print(f"GET {ORDER_BY_CLIENT_ORDER_ID_PATH}")
    print(f"clientOrderId: {client_order_id}  (random, never sent with an order)")
    print("This probe is read-only: it places nothing.\n")

    credentials = credentials_from_settings(settings)
    async with signed_transport(settings, credentials) as transport:
        try:
            data = await transport.get(
                ORDER_BY_CLIENT_ORDER_ID_PATH, {"clientOrderId": client_order_id}
            )
        except PionexApiError as exc:
            print("REJECTED")
            print(f"  code:        {exc.code!r}")
            print(f"  http_status: {exc.http_status!r}")
            print(f"  message:     {exc}")
            listed = exc.code in ORDER_NOT_FOUND_CODES
            print(
                f"\n  code is in ORDER_NOT_FOUND_CODES: {listed}"
                if exc.code
                else "\n  no code in the envelope"
            )
            if not listed:
                print(
                    "  ACTION REQUIRED: add this exact code to "
                    "futures_trade_client.ORDER_NOT_FOUND_CODES, or the "
                    "settle job will retry forever instead of releasing."
                )
            return 0

    print("ACCEPTED -- Pionex answered a successful envelope")
    print(f"  data: {data!r}")
    print(
        "\n  An empty or absent data object IS the not-found answer; the "
        "client already reads it that way."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
