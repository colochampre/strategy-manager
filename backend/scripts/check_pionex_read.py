"""Manual check: read live Pionex account state through the read-only adapter.

This is NOT a test. It needs real read-only API credentials and it talks to
the live exchange, which is exactly why it lives here and not under tests/
(CLAUDE.md rule 1: no test may require a real API credential).

It exists to answer the open risks in CLAUDE.md against a real account before
anything is built on top of the adapter: whether the futures base path works,
and whether COIN-M wallets are reported at all.

Usage:
    cd backend
    # PIONEX_API_KEY / PIONEX_API_SECRET must be set, read-only permissions
    uv run python scripts/check_pionex_read.py
"""

import asyncio
import sys
from collections.abc import Awaitable, Callable

from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.factory import (
    credentials_from_settings,
    read_only_client,
)
from strategy_manager.shared.infrastructure.pionex.read_client import CoinBalance


def _render(label: str, balances: list[CoinBalance]) -> None:
    non_zero = [b for b in balances if b.free or b.frozen]
    print(f"\n{label}: {len(balances)} coins reported, {len(non_zero)} non-zero")
    for balance in non_zero:
        debts = "" if balance.debts is None else f"  debts={balance.debts}"
        print(f"  {balance.coin:<8} free={balance.free}  frozen={balance.frozen}{debts}")


async def _probe(label: str, read: Callable[[], Awaitable[list[CoinBalance]]]) -> bool:
    """Runs one read and reports the outcome without aborting the other probes
    -- a futures failure must not hide a working spot read."""
    try:
        balances = await read()
    except PionexApiError as exc:
        print(f"\n{label}: FAILED -- {exc}")
        return False
    _render(label, balances)
    return True


async def main() -> int:
    settings = get_settings()
    print(f"Pionex base URL: {settings.pionex_base_url}")

    async with read_only_client(settings, credentials_from_settings(settings)) as client:
        spot_ok = await _probe("SPOT      /api/v1/account/balances", client.spot_balances)
        futures_ok = await _probe(
            "FUTURES   /uapi/v1/account/balances", client.futures_balances
        )

    print("\n--- open risks ---")
    print(f"spot readable:    {spot_ok}")
    print(f"futures readable: {futures_ok}")
    print("COIN-M: check whether any BTC/ETH-settled wallet appears above at all.")
    return 0 if spot_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
