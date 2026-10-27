"""Which user's key a live probe signs as (multi-user design AD8).

``vault_credentials`` used to open THE key of an exchange. A key is now a
user's, so a probe names the user with ``--user-email``, signs with that user's
key and never another's, and refuses an e-mail nobody is registered with
before anything is decrypted. No real credential (rule 1): the keys here are
fixtures sealed with a throwaway master key.
"""

import argparse
import base64
import os

import pytest
from probe_credentials import add_user_email_argument, vault_credentials
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential, KeyFacts
from strategy_manager.accounts.infrastructure.credential_vault import SqlAlchemyCredentialVault
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import MASTER_KEY_BYTES, EnvelopeCipher
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.owner import OWNER_EMAIL, OWNER_ID, seed_other_user, seed_owner


async def _two_users_with_a_bybit_key(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> str:
    """The owner and a second user each hold a Bybit key; returns the second
    user's e-mail."""
    master_key = os.urandom(MASTER_KEY_BYTES)
    monkeypatch.setattr(
        get_settings(), "master_encryption_key", base64.b64encode(master_key).decode()
    )
    async with session_factory() as session:
        await seed_owner(session)
        other_id = await seed_other_user(session)
        vault = SqlAlchemyCredentialVault(session, EnvelopeCipher(master_key), SystemClock())
        for user_id, api_key in ((OWNER_ID, "OWNER-KEY-1111"), (other_id, "OTHER-KEY-2222")):
            await vault.store(
                user_id,
                ExchangeCredential(
                    exchange="bybit", label="default", api_key=api_key, api_secret="s"
                ),
                KeyFacts.unrecorded(trade_capable=True),
            )
        email = (
            await session.execute(text("SELECT email FROM users WHERE id = :id"), {"id": other_id})
        ).scalar_one()
        await session.commit()
    return str(email)


@pytest.mark.integration
async def test_a_probe_signs_with_the_named_users_key_never_another_users(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other_email = await _two_users_with_a_bybit_key(pg_session_factory, monkeypatch)

    signed_as: list[str] = []
    for email in (other_email, OWNER_EMAIL):
        async with vault_credentials(
            get_settings(), "bybit", user_email=email, sessions=pg_session_factory
        ) as credentials:
            signed_as.append(credentials.api_key)

    assert signed_as == ["OTHER-KEY-2222", "OWNER-KEY-1111"]


@pytest.mark.integration
async def test_an_unknown_email_is_refused_before_any_key_is_opened(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _two_users_with_a_bybit_key(pg_session_factory, monkeypatch)
    opened: list[str] = []

    with pytest.raises(SystemExit) as refusal:
        async with vault_credentials(
            get_settings(), "bybit", user_email="nobody@example.com", sessions=pg_session_factory
        ) as credentials:
            opened.append(credentials.api_key)

    assert opened == []
    assert "no user is registered with the e-mail 'nobody@example.com'" in str(refusal.value)
    assert "Nothing was sent" in str(refusal.value)


def test_the_user_email_argument_is_required() -> None:
    parser = argparse.ArgumentParser()
    add_user_email_argument(parser)

    with pytest.raises(SystemExit) as missing:
        parser.parse_args([])

    assert missing.value.code == 2
    assert parser.parse_args(["--user-email", "a@example.com"]).user_email == "a@example.com"
