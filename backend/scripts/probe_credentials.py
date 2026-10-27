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

A key belongs to a user (multi-user design AD8), so every vault probe takes a
required ``--user-email`` and signs with THAT user's key, never another's. An
e-mail nobody is registered with is refused before any key is opened.
"""

import argparse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from credential_cli import user_id_by_email
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


def add_user_email_argument(parser: argparse.ArgumentParser) -> None:
    """The required ``--user-email`` every vault probe takes: whose key it
    signs as (multi-user design AD8)."""
    parser.add_argument(
        "--user-email",
        required=True,
        help="the e-mail of the user whose vault key this probe signs as",
    )


def unknown_user_refusal(email: str) -> str:
    return (
        f"no user is registered with the e-mail {email!r}; a probe signs as a "
        "user's key, so name one who has signed in to the panel once. "
        "Nothing was sent."
    )


@asynccontextmanager
async def vault_credentials(
    settings: Settings,
    exchange: str = PIONEX_EXCHANGE,
    *,
    user_email: str,
    sessions: async_sessionmaker[AsyncSession] = session_factory,
) -> AsyncIterator[PionexCredentials]:
    """The credential the worker signs with, decrypted for the length of this
    context and no longer (CLAUDE.md rule 8).

    ``exchange`` defaults to Pionex only because that is what existed first.
    It is a parameter rather than a constant because the vault now holds more
    than one, and loading the wrong venue's key would produce an
    authentication failure that looks exactly like a venue refusing the call —
    the confusion this module exists to prevent, one level up.

    The return type is a ``PionexCredentials`` for every venue, which is
    honest rather than sloppy: it is a redacting key/secret pair and nothing
    about it is Pionex-specific. Callers that need a venue's own credential
    type construct it from these two fields.

    ``user_email`` names whose key it is; an unknown one ends the run with a
    ``SystemExit`` that carries the reason, before anything is decrypted.
    ``sessions`` is injectable for the tests, which run on their own database.
    """
    cipher = EnvelopeCipher.from_base64(settings.master_encryption_key)
    async with sessions() as session:
        user_id = await user_id_by_email(session, user_email)
        if user_id is None:
            raise SystemExit(unknown_user_refusal(user_email))
        credential = await SqlAlchemyCredentialVault(
            session, cipher, SystemClock()
        ).load(user_id, exchange)
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
