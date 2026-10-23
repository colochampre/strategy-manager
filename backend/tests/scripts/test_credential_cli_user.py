"""The store scripts' ``--user-email``, as the real saver resolves it
(multi-user design AD8).

The script tests drive ``main`` with a fake saver; this file proves the REAL
``vault_saver`` refuses an e-mail no user is registered with before anything is
prompted for, and that the lookup it uses finds a user by e-mail on real
PostgreSQL. No real credential (rule 1).
"""

import base64
from uuid import UUID

import credential_cli
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.crypto import MASTER_KEY_BYTES
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.owner import seed_other_user


@pytest.fixture
def usable_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        get_settings(), "master_encryption_key", base64.b64encode(bytes(MASTER_KEY_BYTES)).decode()
    )


async def test_an_unknown_email_builds_no_saver_and_says_so(
    usable_master_key: None, capsys: pytest.CaptureFixture[str]
) -> None:
    asked: list[str] = []

    async def nobody(email: str) -> UUID | None:
        asked.append(email)
        return None

    saver = await credential_cli.vault_saver("nobody@example.com", resolve=nobody)

    err = capsys.readouterr().err
    assert saver is None
    assert asked == ["nobody@example.com"]
    assert "no user is registered with the e-mail 'nobody@example.com'" in err
    assert "Nothing was stored" in err


async def test_a_known_email_builds_a_saver(usable_master_key: None) -> None:
    async def the_owner(email: str) -> UUID | None:
        return UUID("0a1b2c3d-0000-4000-8000-00000000a0a0")

    saver = await credential_cli.vault_saver("owner@example.com", resolve=the_owner)

    assert saver is not None


@pytest.mark.integration
async def test_the_lookup_finds_the_user_by_email_and_nobody_else(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with pg_session_factory() as session:
        user_id = await seed_other_user(session)
        email = (
            await session.execute(text("SELECT email FROM users WHERE id = :id"), {"id": user_id})
        ).scalar_one()
        await session.commit()

    async with pg_session_factory() as session:
        found = await credential_cli.user_id_by_email(session, email)
        missing = await credential_cli.user_id_by_email(session, "nobody@example.com")

    assert (found, missing) == (user_id, None)
