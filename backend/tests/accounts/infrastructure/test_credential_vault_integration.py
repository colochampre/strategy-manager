"""Integration: the credential vault against real PostgreSQL.

Proves the two properties the table exists for — that what is written is
unreadable without the master key, and that exactly one credential per
exchange can ever be active, so the worker's lookup is never ambiguous.
"""

import os

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential
from strategy_manager.accounts.infrastructure.credential_vault import (
    CredentialNotFound,
    SqlAlchemyCredentialVault,
)
from strategy_manager.accounts.infrastructure.models import ExchangeCredentialRow
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.crypto import (
    MASTER_KEY_BYTES,
    DecryptionFailed,
    EnvelopeCipher,
)

pytestmark = pytest.mark.integration

EXCHANGE = "pionex"
KEY = "PIONEX-KEY-abcd"
SECRET = "PIONEX-SECRET-wxyz"


@pytest.fixture
def master_key() -> bytes:
    return os.urandom(MASTER_KEY_BYTES)


def _vault(session: AsyncSession, master_key: bytes) -> SqlAlchemyCredentialVault:
    return SqlAlchemyCredentialVault(session, EnvelopeCipher(master_key), SystemClock())


def _credential(api_key: str = KEY, label: str = "default") -> ExchangeCredential:
    return ExchangeCredential(
        exchange=EXCHANGE, label=label, api_key=api_key, api_secret=SECRET
    )


@pytest.fixture(autouse=True)
async def _clean(pg_session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE exchange_credentials CASCADE"))
        await session.commit()


async def test_a_stored_credential_round_trips(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    async with pg_session_factory() as session:
        vault = _vault(session, master_key)
        await vault.store(_credential())
        await session.commit()

        loaded = await vault.load(EXCHANGE)

    assert loaded.api_key == KEY
    assert loaded.api_secret == SECRET


async def test_nothing_readable_reaches_the_table(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    """The whole point of the table. Only the last-4 hint is plaintext."""
    async with pg_session_factory() as session:
        await _vault(session, master_key).store(_credential())
        await session.commit()

        row = (
            await session.execute(select(ExchangeCredentialRow))
        ).scalar_one()

    stored = (
        row.wrapped_dek
        + row.api_key_ciphertext
        + row.api_secret_ciphertext
    )
    assert KEY.encode() not in stored
    assert SECRET.encode() not in stored
    assert row.api_key_last4 == "abcd"


async def test_the_wrong_master_key_cannot_read_a_stored_credential(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    async with pg_session_factory() as session:
        await _vault(session, master_key).store(_credential())
        await session.commit()

        stranger = _vault(session, os.urandom(MASTER_KEY_BYTES))

        with pytest.raises(DecryptionFailed):
            await stranger.load(EXCHANGE)


async def test_storing_again_supersedes_rather_than_duplicating(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    """Rotation, under the SAME label — which is the only rotation that
    actually happens, because ``store_pionex_credentials.py`` uses a fixed one.

    This test used to pass a new label on the second store. It therefore
    exercised a scenario no caller performs, and missed that a UNIQUE on
    (exchange, label) made real rotation raise a constraint violation. The
    partial unique index allows one active row per exchange, so the old one
    steps down before the new one lands; nothing else may constrain the row
    that steps down.
    """
    async with pg_session_factory() as session:
        vault = _vault(session, master_key)
        await vault.store(_credential(api_key="OLD-KEY-0000"))
        await session.commit()
        await vault.store(_credential(api_key="NEW-KEY-1111"))
        await session.commit()

        loaded = await vault.load(EXCHANGE)
        rows = (await session.execute(select(ExchangeCredentialRow))).scalars().all()

    assert loaded.api_key == "NEW-KEY-1111"
    assert len(rows) == 2, "the superseded row is kept for recovery"
    assert [row.is_active for row in rows].count(True) == 1


async def test_a_superseded_credential_is_kept_not_deleted(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    async with pg_session_factory() as session:
        vault = _vault(session, master_key)
        await vault.store(_credential(api_key="OLD-KEY-0000"))
        await session.commit()
        await vault.store(_credential(api_key="NEW-KEY-1111"))
        await session.commit()

        inactive = (
            await session.execute(
                select(ExchangeCredentialRow).where(
                    ExchangeCredentialRow.is_active.is_(False)
                )
            )
        ).scalar_one()

    assert inactive.api_key_last4 == "0000"


async def test_loading_an_exchange_with_no_credential_fails_clearly(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    async with pg_session_factory() as session:
        with pytest.raises(CredentialNotFound, match="no active credential"):
            await _vault(session, master_key).load("kraken")


async def test_hints_expose_only_the_last_four(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    async with pg_session_factory() as session:
        vault = _vault(session, master_key)
        await vault.store(_credential())
        await session.commit()

        hints = await vault.hints()

    assert len(hints) == 1
    assert hints[0].api_key_last4 == "abcd"
    assert not hasattr(hints[0], "api_secret")


async def test_a_credential_can_be_rotated_more_than_once(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    """Every key this system has ever held stays recoverable.

    Two rotations under one label is what a year of ordinary key hygiene looks
    like, and it is precisely what the dropped UNIQUE forbade — the second
    store collided with the first superseded row rather than joining it.
    """
    async with pg_session_factory() as session:
        vault = _vault(session, master_key)
        for api_key in ("KEY-ONE-0001", "KEY-TWO-0002", "KEY-THREE-0003"):
            await vault.store(_credential(api_key=api_key))
            await session.commit()

        loaded = await vault.load(EXCHANGE)
        rows = (await session.execute(select(ExchangeCredentialRow))).scalars().all()

    assert loaded.api_key == "KEY-THREE-0003"
    assert len(rows) == 3
    assert [row.is_active for row in rows].count(True) == 1
    assert sorted(row.api_key_last4 for row in rows) == ["0001", "0002", "0003"]
