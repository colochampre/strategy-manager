"""Moves capital between Bybit account types. FUND -> UNIFIED by default.

This is NOT a test. It needs real API credentials and it MOVES REAL MONEY
between your own Bybit accounts (CLAUDE.md rule 1: no test may require a real
API credential).

Nothing leaves the exchange: this is an internal transfer, and the key it
signs with has no Withdraw permission — verified before it was ever sealed
into the vault.

**It previews by default and only moves with ``--confirm``.** An accidental
run reads balances and prints what it would do. That asymmetry is deliberate:
the cost of an unintended preview is nothing, and the cost of an unintended
transfer is a number you then have to move back.

**Why this exists at all.** A deposit lands in FUND. Trading collateral lives
in UNIFIED. Pool availability reads the trading account, so a deposit nobody
moves is capital the allocation engine cannot see — indistinguishable, from
inside this system, from having no money at all. Automating it eventually is
the point; this is the step that proves the call works first.

**``PENDING`` is not ``SUCCESS``.** Bybit answers with a status of
``SUCCESS``, ``PENDING``, ``FAILED`` or ``STATUS_UNKNOWN``, and only the first
means the money has moved. The others are reported as what they are rather
than flattened into "done", and the balances are re-read afterwards so the
answer comes from the account rather than from the acknowledgement.

The ``transferId`` is a UUID this script generates — the same idempotency
discipline every order in this system uses, and for the same reason: a
retried request that carries the id of the first one cannot become a second
transfer.

Usage — run it yourself:
    cd backend
    uv run python scripts/transfer_bybit_funds.py                # preview
    uv run python scripts/transfer_bybit_funds.py --confirm      # moves 5 USDT
    uv run python scripts/transfer_bybit_funds.py --amount 100 --confirm
"""

import argparse
import asyncio
import sys
from decimal import Decimal
from uuid import uuid4

from probe_credentials import announce, vault_credentials

from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.infrastructure.bybit import EXCHANGE
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.factory import (
    read_only_client,
    signed_transport,
)
from strategy_manager.shared.infrastructure.bybit.read_client import BybitReadOnlyClient
from strategy_manager.shared.infrastructure.bybit.signer import BybitCredentials

TRANSFER_PATH = "/v5/asset/transfer/inter-transfer"

FROM_ACCOUNT = "FUND"
TO_ACCOUNT = "UNIFIED"
COIN = "USDT"

DEFAULT_AMOUNT = Decimal("5")

# A ceiling this script will not cross whatever the arguments say. Not a
# business rule — a guard against a typo in a number typed at a terminal that
# moves money. Raise it deliberately when there is a reason to.
MAX_AMOUNT = Decimal("1000")

SUCCESS = "SUCCESS"


async def _balance(client: BybitReadOnlyClient, account_type: str) -> Decimal:
    balances = await client.account_coins_balance(account_type, COIN)
    for balance in balances:
        if balance.coin.upper() == COIN:
            return balance.wallet_balance
    return Decimal(0)


async def _show(client: BybitReadOnlyClient, label: str) -> tuple[Decimal, Decimal]:
    fund = await _balance(client, FROM_ACCOUNT)
    unified = await _balance(client, TO_ACCOUNT)
    print(f"  {label:<8} {FROM_ACCOUNT}={fund} {COIN}   {TO_ACCOUNT}={unified} {COIN}")
    return fund, unified


async def _transfer(
    settings: Settings, credentials: BybitCredentials, amount: Decimal
) -> str | None:
    transfer_id = str(uuid4())
    payload = {
        "transferId": transfer_id,
        "coin": COIN,
        "amount": format(amount.normalize(), "f"),
        "fromAccountType": FROM_ACCOUNT,
        "toAccountType": TO_ACCOUNT,
    }
    print(f"\n  POST {TRANSFER_PATH}")
    print(f"       transferId {transfer_id}")

    async with signed_transport(settings, credentials) as transport:
        try:
            data = await transport.post(TRANSFER_PATH, payload)
        except BybitApiError as exc:
            print(f"  REJECTED  code={exc.code!r}: {exc}", file=sys.stderr)
            return None

    status = str(data.get("status")) if isinstance(data, dict) else "STATUS_UNKNOWN"
    print(f"  status     {status}")
    return status


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amount", type=Decimal, default=DEFAULT_AMOUNT)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually move the money. Without it this only previews.",
    )
    args = parser.parse_args()
    amount: Decimal = args.amount

    if amount <= 0:
        print("amount must be positive", file=sys.stderr)
        return 1
    if amount > MAX_AMOUNT:
        print(
            f"REFUSING: {amount} exceeds this script's ceiling of {MAX_AMOUNT} "
            f"{COIN}. Raise MAX_AMOUNT deliberately if that is really intended.",
            file=sys.stderr,
        )
        return 1

    settings = get_settings()
    print(f"Bybit base URL: {settings.bybit_base_url}")
    print(f"Moving {amount} {COIN}: {FROM_ACCOUNT} -> {TO_ACCOUNT}")
    print("Nothing leaves the exchange. This key cannot withdraw.\n")

    async with vault_credentials(settings, EXCHANGE) as vaulted:
        credentials = BybitCredentials(
            api_key=vaulted.api_key, api_secret=vaulted.api_secret
        )
        announce(vaulted, f"vault ({EXCHANGE})")

        async with read_only_client(settings, credentials) as client:
            fund, _ = await _show(client, "before")

            if fund < amount:
                print(
                    f"\nREFUSING: {FROM_ACCOUNT} holds {fund} {COIN}, which is "
                    f"less than the {amount} requested.",
                    file=sys.stderr,
                )
                return 1

            if not args.confirm:
                print(
                    f"\nPREVIEW ONLY. Nothing was moved.\n"
                    f"  Re-run with --confirm to move {amount} {COIN}."
                )
                return 0

            status = await _transfer(settings, credentials, amount)
            if status is None:
                return 1

            # The acknowledgement is not the outcome. Ask the account.
            print()
            await _show(client, "after")

    if status != SUCCESS:
        print(
            f"\n{status} is not {SUCCESS}. The transfer may still complete;\n"
            "re-read the balances before concluding anything.",
            file=sys.stderr,
        )
        return 1

    print(f"\nmoved {amount} {COIN} into {TO_ACCOUNT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
