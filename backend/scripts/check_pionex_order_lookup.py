"""Manual check: what does Pionex answer when an order does not exist?

This is NOT a test. It needs real API credentials and talks to the live
exchange, which is why it lives here and not under tests/ (CLAUDE.md rule 1:
no test may require a real API credential).

**It places nothing.** It performs one GET, looking up a freshly generated
UUID that no order can possibly carry, and prints the exact envelope that
comes back. Nothing here can move money.

``trade_client.ORDER_NOT_FOUND_CODES`` decides which failures mean "the order
never reached the exchange" — and that answer makes ``SettleExecution``
release the capital a reservation is holding. Get it wrong in that direction
and the system releases capital backing a position that is really open, then
forgets the position exists.

That set was seeded from three plausible-sounding names and this probe, run
against the live account on 2026-08-21, disproved all three. The real answer
is HTTP 200 with::

    {"result": false, "code": "TRADE_ORDER_NOT_EXIST", "message": "order not found"}

So this script has done its original job. Keep it as the regression check:
Pionex can rename a code, and the day it does, the "never placed" recovery
path stops working silently — reservations would retry forever instead of
being released. Re-run it after any Pionex API change, and before trusting
live settlement again.

Usage:
    cd backend
    # PIONEX_API_KEY / PIONEX_API_SECRET must be set
    uv run python scripts/check_pionex_order_lookup.py
"""

import asyncio
import sys
from uuid import uuid4

from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.pionex.errors import (
    PionexApiError,
    PionexOrderNotFound,
)
from strategy_manager.shared.infrastructure.pionex.factory import (
    credentials_from_settings,
    trade_client,
)
from strategy_manager.shared.infrastructure.pionex.trade_client import (
    ORDER_NOT_FOUND_CODES,
)


async def main() -> int:
    settings = get_settings()
    unknown = str(uuid4())

    print(f"Pionex base URL: {settings.pionex_base_url}")
    print(f"Looking up a client order id that cannot exist: {unknown}")
    print(f"Codes currently read as 'no such order': {sorted(ORDER_NOT_FOUND_CODES)}\n")

    async with trade_client(settings, credentials_from_settings(settings)) as client:
        try:
            order_id = await client.order_id_for(unknown)
        except PionexOrderNotFound as exc:
            print(f"OK -- classified as not found: {exc}")
            print(
                "\nThe 'never placed' recovery path still works: settlement can\n"
                "still tell a missing order from a failed call, and release the\n"
                "capital a reservation is holding for an order that never was."
            )
            return 0
        except PionexApiError as exc:
            print("REGRESSION -- this lookup is no longer classified as not found.")
            print(f"  message:     {exc}")
            print(f"  code:        {exc.code!r}")
            print(f"  http_status: {exc.http_status!r}")
            print(
                "\nSettlement can no longer conclude an order was never placed:\n"
                "those reservations will retry forever instead of being released.\n"
                "\nIf that code genuinely means 'no such order', add it to\n"
                "ORDER_NOT_FOUND_CODES in "
                "shared/infrastructure/pionex/trade_client.py.\n"
                "If it is ambiguous, LEAVE IT OUT: retrying forever is\n"
                "recoverable, releasing capital behind a live position is not."
            )
            return 1

    print(f"Pionex returned an order id for an id that cannot exist: {order_id!r}")
    print("That is not a result this protocol accounts for. Investigate before trading.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
