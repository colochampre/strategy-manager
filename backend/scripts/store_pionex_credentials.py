"""Seals the Pionex credentials from the environment into the vault.

The environment is where a key lands when you first paste it in; the vault is
where it belongs. This moves it across, envelope-encrypted (CLAUDE.md rule 8),
and is what the worker reads from then on.

Idempotent: running it again supersedes the stored credential rather than
duplicating it, so it doubles as the key-rotation path. The superseded row is
kept, deactivated, so a rotation that turns out to be wrong is recoverable.

The key is a user's (multi-user design AD8): ``--user-email`` is required,
names a user who has signed in to the panel once, and is refused when nobody
is registered with it.

Usage:
    cd backend
    # PIONEX_API_KEY, PIONEX_API_SECRET and MASTER_ENCRYPTION_KEY must be set
    uv run python scripts/store_pionex_credentials.py --user-email <e-mail>

Once it succeeds, the PIONEX_API_KEY and PIONEX_API_SECRET entries in .env are
only needed by scripts/check_pionex_read.py.
"""

import argparse
import asyncio
import sys

from credential_cli import USER_EMAIL_HELP, explain_unknown_user, user_id_by_email

from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential, KeyFacts
from strategy_manager.accounts.infrastructure.credential_vault import (
    SqlAlchemyCredentialVault,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import engine, session_factory
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import EnvelopeCipher
from strategy_manager.shared.infrastructure.pionex import EXCHANGE

LABEL = "default"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-email", required=True, help=USER_EMAIL_HELP)
    args = parser.parse_args()

    settings = get_settings()

    if not settings.pionex_api_key or not settings.pionex_api_secret:
        print("PIONEX_API_KEY and PIONEX_API_SECRET must be set", file=sys.stderr)
        return 1

    try:
        cipher = EnvelopeCipher.from_base64(settings.master_encryption_key)
    except InvariantViolation as exc:
        print(f"MASTER_ENCRYPTION_KEY problem: {exc}", file=sys.stderr)
        return 1

    credential = ExchangeCredential(
        exchange=EXCHANGE,
        label=LABEL,
        api_key=settings.pionex_api_key,
        api_secret=settings.pionex_api_secret,
    )

    try:
        async with session_factory() as session:
            user_id = await user_id_by_email(session, args.user_email)
            if user_id is None:
                explain_unknown_user(args.user_email)
                return 1
            vault = SqlAlchemyCredentialVault(session, cipher, SystemClock())
            hint = await vault.store(
                user_id, credential, KeyFacts.unrecorded(trade_capable=True)
            )
            await session.commit()

            # Prove the round trip before reporting success: a credential that
            # seals but cannot be opened is worse than no credential at all,
            # because the failure would surface on the first live signal.
            reopened = await vault.load(user_id, EXCHANGE)
    finally:
        await engine.dispose()

    if reopened.api_key != credential.api_key:
        print("stored credential did not survive a decrypt round trip", file=sys.stderr)
        return 1

    print(f"sealed {hint.exchange}/{hint.label} (key ending {hint.api_key_last4})")
    print("the worker now reads this credential from the database, not the environment")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
