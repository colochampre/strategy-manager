"""Integration: the credential vault against real PostgreSQL.

Proves the two properties the table exists for — that what is written is
unreadable without the master key, and that exactly one credential per
exchange can ever be active, so the worker's lookup is never ambiguous.
"""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.domain.exchange_credential import (
    ExchangeCredential,
    FactSource,
    KeyFacts,
)
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

# What the store scripts have always asserted, and nothing more.
LEGACY_FACTS = KeyFacts.unrecorded(trade_capable=True)
CONFIRMED_AT = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def master_key() -> bytes:
    return os.urandom(MASTER_KEY_BYTES)


def _vault(session: AsyncSession, master_key: bytes) -> SqlAlchemyCredentialVault:
    return SqlAlchemyCredentialVault(session, EnvelopeCipher(master_key), SystemClock())


def _credential(api_key: str = KEY, label: str = "default") -> ExchangeCredential:
    return ExchangeCredential(
        exchange=EXCHANGE, label=label, api_key=api_key, api_secret=SECRET
    )


def _credential_on(exchange: str, api_key: str = "SOME-KEY-abcd") -> ExchangeCredential:
    return ExchangeCredential(
        exchange=exchange, label="default", api_key=api_key, api_secret=SECRET
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
        await vault.store(_credential(), LEGACY_FACTS)
        await session.commit()

        loaded = await vault.load(EXCHANGE)

    assert loaded.api_key == KEY
    assert loaded.api_secret == SECRET


async def test_nothing_readable_reaches_the_table(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    """The whole point of the table. Only the last-4 hint is plaintext."""
    async with pg_session_factory() as session:
        await _vault(session, master_key).store(_credential(), LEGACY_FACTS)
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
        await _vault(session, master_key).store(_credential(), LEGACY_FACTS)
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
        await vault.store(_credential(api_key="OLD-KEY-0000"), LEGACY_FACTS)
        await session.commit()
        await vault.store(_credential(api_key="NEW-KEY-1111"), LEGACY_FACTS)
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
        await vault.store(_credential(api_key="OLD-KEY-0000"), LEGACY_FACTS)
        await session.commit()
        await vault.store(_credential(api_key="NEW-KEY-1111"), LEGACY_FACTS)
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
        await vault.store(_credential(), LEGACY_FACTS)
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
            await vault.store(_credential(api_key=api_key), LEGACY_FACTS)
            await session.commit()

        loaded = await vault.load(EXCHANGE)
        rows = (await session.execute(select(ExchangeCredentialRow))).scalars().all()

    assert loaded.api_key == "KEY-THREE-0003"
    assert len(rows) == 3
    assert [row.is_active for row in rows].count(True) == 1
    assert sorted(row.api_key_last4 for row in rows) == ["0001", "0002", "0003"]


async def test_store_persists_facts_and_hints_return_them_never_ciphertext(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    facts = KeyFacts(
        trade_capable=True,
        trade_capability_source=FactSource.OWNER_CONFIRMED,
        trade_confirmed_at=CONFIRMED_AT,
        withdraw_check=FactSource.OWNER_CONFIRMED,
        withdraw_confirmed_at=CONFIRMED_AT,
        validated_at=CONFIRMED_AT,
        internal_transfer=None,
    )
    async with pg_session_factory() as session:
        stored = await _vault(session, master_key).store(
            _credential_on("binance", api_key="BINANCE-KEY-abcd"), facts
        )
        await session.commit()

    async with pg_session_factory() as session:
        hints = await _vault(session, master_key).hints()
        row = (await session.execute(select(ExchangeCredentialRow))).scalar_one()

    assert stored.facts == facts
    assert [hint.facts for hint in hints] == [facts]
    assert row.trade_capable is True
    assert row.trade_capability_source == "OWNER_CONFIRMED"
    assert row.trade_confirmed_at == CONFIRMED_AT
    assert row.withdraw_check == "OWNER_CONFIRMED"
    assert row.withdraw_confirmed_at == CONFIRMED_AT
    assert row.validated_at == CONFIRMED_AT
    assert row.internal_transfer is None
    # A hint is the last four and the facts: nothing of the secret or its
    # ciphertext reaches a value a client can be given.
    rendered = repr(hints[0])
    assert "BINANCE-KEY-abcd" not in rendered
    assert SECRET not in rendered
    assert repr(row.api_key_ciphertext) not in rendered
    assert repr(row.wrapped_dek) not in rendered


async def test_hints_report_verified_bybit_facts_including_internal_transfer(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    facts = KeyFacts(
        trade_capable=False,
        trade_capability_source=FactSource.VERIFIED,
        trade_confirmed_at=None,
        withdraw_check=FactSource.VERIFIED,
        withdraw_confirmed_at=None,
        validated_at=CONFIRMED_AT,
        internal_transfer=True,
    )
    async with pg_session_factory() as session:
        vault = _vault(session, master_key)
        await vault.store(_credential_on("bybit", api_key="BYBIT-KEY-wxyz"), facts)
        await session.commit()
        (hint,) = await vault.hints()

    assert hint.facts == facts


async def test_store_without_facts_is_a_type_error(
    pg_session_factory: async_sessionmaker[AsyncSession], master_key: bytes
) -> None:
    async with pg_session_factory() as session:
        with pytest.raises(TypeError):
            await _vault(session, master_key).store(_credential())  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("exchange", "facts", "constraint"),
    [
        (
            "binance",
            KeyFacts(
                True, FactSource.VERIFIED, None, FactSource.VERIFIED, None, CONFIRMED_AT, None
            ),
            "ck_exchange_credentials_binance_not_verified",
        ),
        (
            "bybit",
            KeyFacts(
                True,
                FactSource.OWNER_CONFIRMED,
                CONFIRMED_AT,
                FactSource.OWNER_CONFIRMED,
                CONFIRMED_AT,
                CONFIRMED_AT,
                None,
            ),
            "ck_exchange_credentials_bybit_not_owner_confirmed",
        ),
    ],
)
async def test_the_orm_mirrors_the_venue_constraints_the_domain_cannot_see(
    pg_session_factory: async_sessionmaker[AsyncSession],
    master_key: bytes,
    exchange: str,
    facts: KeyFacts,
    constraint: str,
) -> None:
    """``KeyFacts`` has no exchange, so constraints 5 and 6 are the table's
    alone. This proves the ORM schema (what these tests build) carries them."""
    async with pg_session_factory() as session:
        with pytest.raises(IntegrityError) as raised:
            await _vault(session, master_key).store(_credential_on(exchange), facts)

    assert getattr(raised.value.orig.__cause__, "constraint_name", None) == constraint
