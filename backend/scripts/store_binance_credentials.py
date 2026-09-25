"""Seals a Binance trade credential into the vault, after checking what it can do.

**It prompts. It does not read the environment, and that is the point.**

The vault holds ONE active key per exchange, and that key signs every read and
every order (decision 18). Nothing reads a Binance key from ``.env`` any more.
So the key given here must be the TRADING key: sealing the old ``.env``
read-only key would supersede the trading key and leave Binance able to read
and unable to trade. That confusion has already cost this project one wrong
conclusion, on Pionex, where a write refused for using the read-only key looked
identical to a write the venue forbade.

So a trading key goes from your clipboard to the vault without ever being
written to a file. The secret is read with ``getpass`` and never echoed.

**It refuses to seal a key that can withdraw.** ``GET
/sapi/v1/account/apiRestrictions`` reports the granted permissions, and
``enableWithdrawals`` on a key this system signs with is not a risk to be
weighed -- it is the one permission that turns a compromised key into a
drained account. This system never withdraws, so the permission has no upside
to trade against.

**It also refuses a key that cannot trade futures.** Such a key seals and
authenticates cleanly and then fails on the first live signal, which is the
worst place to find out.

Idempotent: running it again supersedes the stored credential rather than
duplicating it, so it doubles as the key-rotation path.

Usage -- run it yourself, in your own terminal, since it prompts:
    cd backend
    uv run python scripts/store_binance_credentials.py
"""

import asyncio
import sys
from collections.abc import Mapping
from getpass import getpass
from typing import Any

from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential
from strategy_manager.accounts.infrastructure.credential_vault import (
    SqlAlchemyCredentialVault,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import engine, session_factory
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.binance import EXCHANGE
from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.factory import spot_transport
from strategy_manager.shared.infrastructure.binance.signer import BinanceCredentials
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import EnvelopeCipher

LABEL = "default"

API_RESTRICTIONS_PATH = "/sapi/v1/account/apiRestrictions"

# The one permission that turns a compromised key into a drained account.
WITHDRAW = "enableWithdrawals"

# Without this the key cannot place a futures order at all.
FUTURES = "enableFutures"

# Not needed by this system. A key holding one of these can move money between
# your own wallets -- not out of the account, but out of the wallet the pool
# reads, which stops trading just as effectively.
TRANSFER_PERMISSIONS = ("permitsUniversalTransfer", "enableInternalTransfer")

REPORTED = (
    "enableReading",
    FUTURES,
    "enableSpotAndMarginTrading",
    "enableMargin",
    *TRANSFER_PERMISSIONS,
    WITHDRAW,
    "enablePortfolioMarginTrading",
    "ipRestrict",
)


def _prompt() -> BinanceCredentials | None:
    """Reads the credential from a terminal, or explains why it cannot.

    ``sys.stdin.isatty()`` is checked but not trusted: some runners report a
    TTY and then hand the prompt an immediate EOF. Catching ``EOFError`` is
    what actually distinguishes "a person is typing" from "something is
    piping", and the difference matters -- the alternative is a traceback
    where an instruction belongs.
    """
    if not sys.stdin.isatty():
        _explain_needs_a_terminal()
        return None

    print("Paste the Binance TRADE credential. The secret is not echoed.\n")
    try:
        api_key = input("API key:    ").strip()
        api_secret = getpass("API secret: ").strip()
    except (EOFError, KeyboardInterrupt):
        _explain_needs_a_terminal()
        return None

    try:
        return BinanceCredentials(api_key=api_key, api_secret=api_secret)
    except InvariantViolation as exc:
        print(f"\n{exc}", file=sys.stderr)
        return None


def _explain_needs_a_terminal() -> None:
    print(
        "\n\nThis script prompts for the credential rather than reading it from\n"
        "a file, so it needs a real terminal. Nothing was stored.\n\n"
        "Run it yourself:\n"
        "    cd backend\n"
        "    uv run python scripts/store_binance_credentials.py",
        file=sys.stderr,
    )


def _report(permissions: Mapping[str, Any]) -> bool:
    """Prints what the key can do and answers whether it is safe to seal."""
    print("\n--- what this key can do ---")
    for name in REPORTED:
        print(f"  {name:<28} {permissions.get(name)}")
    print(f"  {'createTime':<28} {permissions.get('createTime')}")

    if permissions.get(WITHDRAW) is True:
        print(
            f"\nREFUSING: this key carries {WITHDRAW}.\n"
            "  This system never withdraws, so the permission has no upside to\n"
            "  trade against, and it is the one that turns a compromised key\n"
            "  into a drained account. Remove it in Binance and run this again.",
            file=sys.stderr,
        )
        return False

    if permissions.get(FUTURES) is not True:
        print(
            f"\nREFUSING: this key does not carry {FUTURES}.\n"
            "  It would seal and authenticate cleanly, and then fail on the\n"
            "  first live signal. Read-only keys belong in .env, not the vault.",
            file=sys.stderr,
        )
        return False

    granted_transfers = [
        name for name in TRANSFER_PERMISSIONS if permissions.get(name) is True
    ]
    if granted_transfers:
        print(
            f"\nNOTE: this key can transfer ({', '.join(granted_transfers)}).\n"
            "  Nothing here uses that. A compromised key could move funds out of\n"
            "  the USDⓈ-M wallet the pool reads, which halts trading as surely as\n"
            "  a withdrawal would. Consider removing it."
        )

    if permissions.get("ipRestrict") is not True:
        print(
            "\nNOTE: no IP restriction. Once the worker runs from the VPS, binding\n"
            "  this key to that address is the cheapest protection available for\n"
            "  a key that can open positions."
        )

    return True


async def main() -> int:
    settings = get_settings()

    try:
        cipher = EnvelopeCipher.from_base64(settings.master_encryption_key)
    except InvariantViolation as exc:
        print(f"MASTER_ENCRYPTION_KEY problem: {exc}", file=sys.stderr)
        return 1

    credentials = _prompt()
    if credentials is None:
        return 1

    # Verify against the venue BEFORE sealing. A credential that seals but
    # cannot trade is worse than none, because the failure surfaces on the
    # first live signal rather than here.
    try:
        async with spot_transport(settings, credentials) as transport:
            permissions = await transport.get_signed(API_RESTRICTIONS_PATH)
    except BinanceApiError as exc:
        print(f"\nBinance rejected this credential: {exc}", file=sys.stderr)
        return 1

    if not isinstance(permissions, dict):
        print(f"\n{API_RESTRICTIONS_PATH} returned no permission object", file=sys.stderr)
        return 1

    if not _report(permissions):
        return 1

    credential = ExchangeCredential(
        exchange=EXCHANGE,
        label=LABEL,
        api_key=credentials.api_key,
        api_secret=credentials.api_secret,
    )

    async with session_factory() as session:
        vault = SqlAlchemyCredentialVault(session, cipher, SystemClock())
        hint = await vault.store(credential)
        await session.commit()

        # Prove the round trip before reporting success: a credential that
        # seals but cannot be opened is worse than no credential at all.
        reopened = await vault.load(EXCHANGE)

    await engine.dispose()

    if reopened.api_key != credential.api_key:
        print("stored credential did not survive a decrypt round trip", file=sys.stderr)
        return 1

    print(f"\nsealed {hint.exchange}/{hint.label} (key ending {hint.api_key_last4})")
    print("the worker reads this credential from the database, never the environment")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
