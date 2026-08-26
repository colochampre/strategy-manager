"""Seals a Bybit trade credential into the vault, after checking what it can do.

**It prompts. It does not read the environment, and that is the point.**

``store_pionex_credentials.py`` takes its credential from ``PIONEX_API_KEY`` /
``PIONEX_API_SECRET``, which was fine when those were the only keys. It is not
fine here: ``BYBIT_API_KEY`` / ``BYBIT_API_SECRET`` hold the READ-ONLY key that
the probes sign with, and overwriting them with a trading key would make every
read probe run as a key that can move money. That confusion has already cost
this project one wrong conclusion, on the other venue, where a write refused
for using the read-only key looked identical to a write the venue forbade.

So a trading key goes from your clipboard to the vault without ever being
written to a file. The secret is read with ``getpass`` and never echoed.

**It refuses to seal a key that can withdraw.** ``GET /v5/user/query-api``
reports the granted permissions, and ``Wallet.Withdraw`` on a key this system
signs with is not a risk to be weighed — it is the one permission that turns a
compromised key into a drained account. This system never withdraws, so the
permission has no upside to trade against.

It also reports what it found before sealing: whether the key can trade at all
(a read-only key would authenticate and then fail on the first signal), whether
it is bound to an IP, and when it expires. A key that expires in 90 days on an
unattended worker is a scheduled outage, and better known now than on the day.

Idempotent: running it again supersedes the stored credential rather than
duplicating it, so it doubles as the key-rotation path.

Usage — run it yourself, in your own terminal, since it prompts:
    cd backend
    uv run python scripts/store_bybit_credentials.py
"""

import asyncio
import sys
from collections.abc import Mapping, Sequence
from getpass import getpass
from typing import Any

from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential
from strategy_manager.accounts.infrastructure.credential_vault import (
    SqlAlchemyCredentialVault,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import engine, session_factory
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.bybit import EXCHANGE
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.factory import read_only_client
from strategy_manager.shared.infrastructure.bybit.signer import BybitCredentials
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import EnvelopeCipher

LABEL = "default"

WITHDRAW = "Withdraw"
TRADING_PERMISSIONS = ("ContractTrade", "Derivatives", "Spot")


def _prompt() -> BybitCredentials | None:
    """Reads the credential from a terminal, or explains why it cannot.

    ``sys.stdin.isatty()`` is checked but not trusted: some runners report a
    TTY and then hand the prompt an immediate EOF. Catching ``EOFError`` is
    what actually distinguishes "a person is typing" from "something is
    piping", and the difference matters — the alternative is a traceback where
    an instruction belongs.
    """
    if not sys.stdin.isatty():
        _explain_needs_a_terminal()
        return None

    print("Paste the Bybit TRADE credential. The secret is not echoed.\n")
    try:
        api_key = input("API key:    ").strip()
        api_secret = getpass("API secret: ").strip()
    except (EOFError, KeyboardInterrupt):
        _explain_needs_a_terminal()
        return None

    try:
        return BybitCredentials(api_key=api_key, api_secret=api_secret)
    except InvariantViolation as exc:
        print(f"\n{exc}", file=sys.stderr)
        return None


def _explain_needs_a_terminal() -> None:
    print(
        "\n\nThis script prompts for the credential rather than reading it from\n"
        "a file, so it needs a real terminal. Nothing was stored.\n\n"
        "Run it yourself:\n"
        "    cd backend\n"
        "    uv run python scripts/store_bybit_credentials.py",
        file=sys.stderr,
    )


def _granted(permissions: Mapping[str, Any], group: str) -> Sequence[str]:
    value = permissions.get(group)
    return [str(item) for item in value] if isinstance(value, list) else []


def _report(info: Mapping[str, Any]) -> bool:
    """Prints what the key can do and answers whether it is safe to seal."""
    permissions = info.get("permissions")
    permissions = permissions if isinstance(permissions, dict) else {}

    read_only = str(info.get("readOnly")) == "1"
    ips = info.get("ips") if isinstance(info.get("ips"), list) else []
    can_trade = any(_granted(permissions, group) for group in TRADING_PERMISSIONS)
    can_withdraw = WITHDRAW in _granted(permissions, "Wallet")

    print("\n--- what this key can do ---")
    print(f"  note          {info.get('note')!r}")
    print(f"  readOnly      {info.get('readOnly')}   (1 = cannot trade)")
    for group in (*TRADING_PERMISSIONS, "Wallet", "Exchange"):
        granted = _granted(permissions, group)
        if granted:
            print(f"  {group:<13} {', '.join(granted)}")
    print(f"  ips           {ips or 'NONE - not bound to an IP'}")
    print(f"  expiredAt     {info.get('expiredAt') or 'not reported'}")
    print(f"  deadlineDay   {info.get('deadlineDay')}")

    if can_withdraw:
        print(
            "\nREFUSING: this key carries Wallet/Withdraw.\n"
            "  This system never withdraws, so the permission has no upside to\n"
            "  trade against, and it is the one that turns a compromised key\n"
            "  into a drained account. Remove it in Bybit and run this again.",
            file=sys.stderr,
        )
        return False

    if read_only or not can_trade:
        print(
            "\nREFUSING: this key cannot trade.\n"
            "  It would seal and authenticate cleanly, and then fail on the\n"
            "  first live signal. Read-only keys belong in .env, not the vault.",
            file=sys.stderr,
        )
        return False

    if not ips:
        print(
            "\nNOTE: no IP binding. Bybit expires unbound keys, so this one has\n"
            "  a deadline (see deadlineDay above). On an unattended worker that\n"
            "  is a scheduled outage — bind an IP if you have a static one."
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
        async with read_only_client(settings, credentials) as client:
            info = await client.api_key_info()
    except BybitApiError as exc:
        print(f"\nBybit rejected this credential: {exc}", file=sys.stderr)
        return 1

    if not _report(info):
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
