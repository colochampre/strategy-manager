"""Which credential a live probe is running as.

Not a probe itself: shared by the ones that write.

**Why this exists.** A probe read the futures leverage successfully, wrote it
back, and got ``AUTH_UNAVAILABLE``. That looked like "the venue does not allow
this write" and it was not: the probe had loaded its key from the environment,
where the READ-ONLY key lives, while the trade-permission key sits in the
encrypted vault the worker actually uses. A refusal that means "wrong key" and
one that means "wrong venue capability" are opposite conclusions, and nothing
in the output distinguished them.

So two rules, both enforced here rather than remembered:

1. A probe that WRITES loads from the vault, because that is the credential
   production signs with. Testing a write path with a different key than the
   one production uses proves nothing about production.
2. Every probe prints which key it is running as, before it does anything.
   The last four characters are the most that may ever be rendered
   (CLAUDE.md rule 8), and they are enough to tell two keys apart.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from strategy_manager.accounts.infrastructure.credential_vault import (
    SqlAlchemyCredentialVault,
)
from strategy_manager.shared.config import Settings
from strategy_manager.shared.db import session_factory
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import EnvelopeCipher
from strategy_manager.shared.infrastructure.pionex import EXCHANGE as PIONEX_EXCHANGE
from strategy_manager.shared.infrastructure.pionex.factory import (
    credentials_from_settings,
)
from strategy_manager.shared.infrastructure.pionex.signer import PionexCredentials


@asynccontextmanager
async def vault_credentials(settings: Settings) -> AsyncIterator[PionexCredentials]:
    """The credential the worker signs with, decrypted for the length of this
    context and no longer (CLAUDE.md rule 8)."""
    cipher = EnvelopeCipher.from_base64(settings.master_encryption_key)
    async with session_factory() as session:
        credential = await SqlAlchemyCredentialVault(
            session, cipher, SystemClock()
        ).load(PIONEX_EXCHANGE)
        yield PionexCredentials(
            api_key=credential.api_key, api_secret=credential.api_secret
        )


def environment_credentials(settings: Settings) -> PionexCredentials:
    """The developer-convenience key. Read-only by intent; never used to
    prove a write path works."""
    return credentials_from_settings(settings)


def announce(credentials: PionexCredentials, source: str) -> None:
    """Says which key is about to be used, before it is used.

    Not decoration. An unattributed refusal already cost one wrong conclusion.
    """
    print(f"Signing as ***{credentials.api_key[-4:]}  (from the {source})")
