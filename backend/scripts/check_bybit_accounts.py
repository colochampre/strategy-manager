"""Manual check: where is the money, and can this key move it?

This is NOT a test. It needs real API credentials and reads the live account
(CLAUDE.md rule 1: no test may require a real API credential).

**It is GET-only. It moves nothing.** Whether to transfer capital between
account types is a decision with consequences, and it belongs to a person who
has seen these numbers first.

**Why it exists.** Bybit splits money across account types. A deposit lands in
FUND; trading collateral lives in UNIFIED. They are not the same pot, and
reading only UNIFIED reports zero for an account that has just been funded —
which looks identical to an account with no money in it. This system's pool
availability reads one of them, so which one is not a detail.

It also answers a question that has been open since Bybit entered the picture:
whether a Unified Trading Account pools collateral across products. This
project's rule 5 says spot and USDT-M are separate balances that cannot fund
each other, and that rule was written for Pionex's segregated wallets. If
UNIFIED reports account-level equity rather than per-product wallets, the rule
does not describe this venue and the pool model has to say so.

And it reports whether the key carries ``Wallet: AccountTransfer``, because a
transfer this system cannot perform is a manual step someone has to remember.

Usage:
    cd backend
    uv run python scripts/check_bybit_accounts.py
"""

import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from probe_credentials import announce, vault_credentials

from strategy_manager.accounts.infrastructure.bybit_balance_reader import (
    BybitBalanceReader,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.bybit import EXCHANGE
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.factory import read_only_client
from strategy_manager.shared.infrastructure.bybit.read_client import BybitReadOnlyClient
from strategy_manager.shared.infrastructure.bybit.signer import BybitCredentials
from strategy_manager.shared.infrastructure.clock import SystemClock

COINS = "USDT,USDC"

# The account types money can sit in. FUND is where a deposit lands.
ACCOUNT_TYPES = ("FUND", "UNIFIED")

# Account-level fields. Their presence and non-emptiness is the evidence that
# collateral is pooled rather than held per product.
POOLED_COLLATERAL_FIELDS = (
    "totalEquity",
    "totalWalletBalance",
    "totalMarginBalance",
    "totalAvailableBalance",
)

# The per-coin fields that decide what a pool may allocate. Printed verbatim,
# including the empty ones, because which of these Bybit actually populates is
# the whole question -- and an empty field that looks like a zero is how a
# pool ends up reporting capital it does not have.
AVAILABILITY_FIELDS = (
    "walletBalance",
    "equity",
    "usdValue",
    "availableToWithdraw",
    "totalPositionIM",
    "totalOrderIM",
    "locked",
    "unrealisedPnl",
    "collateralSwitch",
    "marginCollateral",
)


async def _balances(client: BybitReadOnlyClient, account_type: str) -> None:
    print(f"\n{account_type} account")
    try:
        balances = await client.account_coins_balance(account_type, COINS)
    except BybitApiError as exc:
        print(f"  FAILED -- code={exc.code!r}: {exc}")
        return

    funded = [b for b in balances if b.wallet_balance]
    if not funded:
        print(f"  no {COINS} balance")
        return
    for balance in funded:
        print(
            f"  {balance.coin:<6} wallet={balance.wallet_balance}  "
            f"transferable={balance.available_to_withdraw}"
        )


def _report_collateral(account: Mapping[str, Any]) -> None:
    print("\nUNIFIED account, as reported")
    if not account:
        print("  empty -- nothing has been moved into the trading account yet")
        return

    reported = {
        field: account.get(field)
        for field in POOLED_COLLATERAL_FIELDS
        if account.get(field) not in (None, "")
    }
    for field, value in reported.items():
        print(f"  {field:<24} {value}")

    # Present-but-zero is not evidence. An empty account reports account-level
    # fields too, and reading their mere presence as "collateral is pooled"
    # would be a conclusion drawn from an account that holds nothing.
    evidence = {
        field: value for field, value in reported.items() if _nonzero(value)
    }

    coins = account.get("coin")
    pooled = False
    if isinstance(coins, list):
        for entry in coins:
            if not isinstance(entry, dict) or not _nonzero(entry.get("walletBalance")):
                continue
            pooled = pooled or bool(entry.get("collateralSwitch"))
            print(f"\n    {entry.get('coin')}")
            for field in AVAILABILITY_FIELDS:
                print(f"      {field:<20} {entry.get(field)!r}")

    print("\n  --- does this account pool collateral across products? ---")
    if not evidence:
        print("  UNKNOWN. The account-level fields are present but ZERO, which")
        print("  an empty account reports too. Nothing can be concluded from a")
        print("  wallet that holds nothing -- move capital into UNIFIED and run")
        print("  this again.")
        return

    if pooled:
        print("  YES. The coin carries collateralSwitch=true, equity is reported")
        print("  at the ACCOUNT level, and there is no per-product wallet in the")
        print("  payload at all. One USDT balance stands behind spot and linear")
        print("  perpetuals together.")
        print("\n  CLAUDE.md rule 5 does not describe this venue. It was written")
        print("  for Pionex's segregated wallets, where spot USDT and USDT-M")
        print("  margin genuinely cannot fund each other. Configuring BOTH as")
        print("  pools here would let the same money be reserved twice.")
        print("  On Bybit there is ONE USDT pool.")
    else:
        print("  Account-level equity is non-zero but no coin reports")
        print("  collateralSwitch. Read the raw object below before concluding.")

    print("\n  --- which field is pool availability? ---")
    print("  NOT totalEquity: it is a USD VALUATION. usdValue differs from")
    print("  walletBalance by the USDT/USD rate, and reading it would silently")
    print("  convert a settlement-currency amount into dollars, against rule 7.")
    print("  availableToWithdraw comes back EMPTY on this account, so it cannot")
    print("  be the source either.")
    print("  What is left, in the coin's own units:")
    print("      walletBalance - totalPositionIM - totalOrderIM - locked")


def _nonzero(value: Any) -> bool:
    try:
        return Decimal(str(value)) != 0
    except ArithmeticError:
        return False


def _granted(permissions: Mapping[str, Any], group: str) -> Sequence[str]:
    value = permissions.get(group)
    return [str(item) for item in value] if isinstance(value, list) else []


def _report_transfer_permission(info: Mapping[str, Any]) -> None:
    permissions = info.get("permissions")
    permissions = permissions if isinstance(permissions, dict) else {}
    wallet = _granted(permissions, "Wallet")

    print("\nCAN THIS KEY MOVE CAPITAL BETWEEN ACCOUNTS?")
    print(f"  Wallet permissions: {', '.join(wallet) or 'none'}")
    if "AccountTransfer" in wallet:
        print("  YES -- AccountTransfer is granted, so FUND -> UNIFIED can be")
        print("  automated. Nothing in this system does it yet.")
    else:
        print("  NO -- AccountTransfer is not granted. Moving a deposit from")
        print("  FUND into UNIFIED stays a manual step, and a deposit that is")
        print("  never moved is capital the allocation engine cannot see.")
    if "Withdraw" in wallet:
        print("  WARNING: this key can WITHDRAW. Nothing here needs that.")


async def _report_pool_view(client: BybitReadOnlyClient) -> None:
    """What the allocation engine would actually see, through the real reader.

    The point of running the production adapter here rather than repeating its
    arithmetic is that a probe agreeing with itself proves nothing.
    """
    reader = BybitBalanceReader(client, SystemClock())
    readings = await reader.read([("usdt-m", "USDT")])

    print("\nWHAT A POOL WOULD SEE (through BybitBalanceReader)")
    for reading in readings:
        print(
            f"  {reading.venue}/{reading.settlement_currency}  "
            f"available={reading.available}"
        )
    print("  = walletBalance - totalPositionIM - totalOrderIM - locked,")
    print("    in USDT, not converted to USD.")


async def main() -> int:
    settings = get_settings()

    print(f"Bybit base URL: {settings.bybit_base_url}")
    print("This probe is GET-only: it moves nothing.")

    # The VAULT key, and Bybit's specifically: it is the one that would
    # perform a transfer, so it is the one whose permissions matter here. The
    # environment holds the read-only key, which would answer a different
    # question and look like the same one.
    async with vault_credentials(settings, EXCHANGE) as credentials:
        bybit = BybitCredentials(
            api_key=credentials.api_key, api_secret=credentials.api_secret
        )
        announce(credentials, f"vault ({EXCHANGE})")

        async with read_only_client(settings, bybit) as client:
            for account_type in ACCOUNT_TYPES:
                await _balances(client, account_type)

            try:
                account = await client.unified_account_raw()
            except BybitApiError as exc:
                print(f"\nUNIFIED read FAILED -- {exc}")
                account = {}
            _report_collateral(account)

            try:
                info = await client.api_key_info()
            except BybitApiError as exc:
                print(f"\nkey info FAILED -- {exc}")
                return 1
            _report_transfer_permission(info)

            await _report_pool_view(client)

            print("\nraw unified account object:")
            print("  " + json.dumps(account, indent=2).replace("\n", "\n  "))

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
