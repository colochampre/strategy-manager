"""Seals the Pionex credentials from the environment into the vault.

The environment is where a key lands when you first paste it in; the vault is
where it belongs. This moves it across, envelope-encrypted (CLAUDE.md rule 8),
and is what the worker reads from then on.

Idempotent: running it again supersedes the stored credential rather than
duplicating it, so it doubles as the key-rotation path. The superseded row is
kept, deactivated, so a rotation that turns out to be wrong is recoverable.

Usage:
    cd backend
    # PIONEX_API_KEY, PIONEX_API_SECRET and MASTER_ENCRYPTION_KEY must be set
    uv run python scripts/store_pionex_credentials.py

Once it succeeds, the PIONEX_API_KEY and PIONEX_API_SECRET entries in .env are
only needed by scripts/check_pionex_read.py.
"""

import asyncio
import sys

from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential
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

    async with session_factory() as session:
        vault = SqlAlchemyCredentialVault(session, cipher, SystemClock())
        hint = await vault.store(credential)
        await session.commit()

        # Prove the round trip before reporting success: a credential that
        # seals but cannot be opened is worse than no credential at all,
        # because the failure would surface on the first live signal.
        reopened = await vault.load(EXCHANGE)

    await engine.dispose()

    if reopened.api_key != credential.api_key:
        print("stored credential did not survive a decrypt round trip", file=sys.stderr)
        return 1

    print(f"sealed {hint.exchange}/{hint.label} (key ending {hint.api_key_last4})")
    print("the worker now reads this credential from the database, not the environment")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
