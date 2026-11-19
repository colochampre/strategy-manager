"""A key saved while the account is being deleted, on real PostgreSQL (account-deletion
S4, the verifier's A1).

The deletion holds the user row ``FOR UPDATE`` and then deletes the user's keys. A
save that touched a key row before the user row took the two locks in the opposite
order: the two deadlocked, or, the other way round, a new active key landed on an
account that had just been deleted. So a save takes the user row first, and refuses
once the account is deleted.
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError

from strategy_manager.accounts.application.save_credential import SaveOutcome, SaveRefused
from strategy_manager.accounts.infrastructure.models import ExchangeCredentialRow
from strategy_manager.identity.infrastructure.models import UserRow
from tests.accounts.application.test_save_key_over_real_exposure_integration import (
    Factory,
    _save,
    _trader,
)
from tests.accounts.fakes import READ_ONLY_SNAPSHOT, TRADING_SNAPSHOT
from tests.strategies.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)

pytestmark = pytest.mark.integration

_FINISH = 10.0
_DELETED_AT = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


async def _until_a_lock_wait(factory: Factory) -> None:
    """Until some session waits on a row lock: the save has reached the user row."""
    deadline = asyncio.get_running_loop().time() + _FINISH
    while True:
        async with factory() as session:
            waiting = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM pg_locks WHERE NOT granted AND locktype <> 'advisory'"
                    )
                )
            ).scalar_one()
        if waiting > 0:
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the save never waited on a row lock")
        await asyncio.sleep(0.02)


async def _keys(factory: Factory, user_id: UUID) -> int:
    async with factory() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(ExchangeCredentialRow)
                .where(ExchangeCredentialRow.user_id == user_id)
            )
        ).scalar_one()


def _wipe(user_id: UUID):  # noqa: ANN202
    return (
        update(UserRow)
        .where(UserRow.id == user_id)
        .values(email=f"deleted-{user_id}@invalid", display_name=None, deleted_at=_DELETED_AT)
    )


@pytest.mark.parametrize(
    "snapshot", [TRADING_SNAPSHOT, READ_ONLY_SNAPSHOT], ids=["trading", "read-only"]
)
async def test_a_save_waits_for_a_deletion_in_flight_and_is_then_refused(
    pg_session_factory: Factory,  # noqa: F811
    snapshot: object,
) -> None:
    factory = pg_session_factory
    user_id, _ = await _trader(factory)

    outcome: dict[str, object] = {}
    async with factory() as deletion:
        # What ``DeleteAccount`` holds once it has the user's pool locks.
        await deletion.execute(select(UserRow.id).where(UserRow.id == user_id).with_for_update())
        save = asyncio.create_task(_save(factory, user_id, snapshot))  # type: ignore[arg-type]
        await _until_a_lock_wait(factory)
        assert not save.done()
        try:
            # A save holding a key row here would deadlock this statement.
            await asyncio.wait_for(
                deletion.execute(
                    delete(ExchangeCredentialRow).where(ExchangeCredentialRow.user_id == user_id)
                ),
                _FINISH,
            )
            await deletion.execute(_wipe(user_id))
            await deletion.commit()
            outcome["deletion"] = "committed"
        except DBAPIError as error:
            outcome["deletion"] = type(error.orig.__cause__).__name__
            await deletion.rollback()

    try:
        result = await asyncio.wait_for(save, _FINISH)
        outcome["save"] = result.outcome if isinstance(result, SaveRefused) else "saved"
    except DBAPIError as error:
        outcome["save"] = type(error.orig.__cause__).__name__

    assert outcome == {"deletion": "committed", "save": SaveOutcome.ACCOUNT_DELETED}
    assert await _keys(factory, user_id) == 0


async def test_a_save_on_an_account_already_deleted_is_refused_and_stores_nothing(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    factory = pg_session_factory
    user_id, _ = await _trader(factory)
    async with factory() as session:
        await session.execute(
            delete(ExchangeCredentialRow).where(ExchangeCredentialRow.user_id == user_id)
        )
        await session.execute(_wipe(user_id))
        await session.commit()

    result = await _save(factory, user_id, TRADING_SNAPSHOT)

    assert isinstance(result, SaveRefused)
    assert result.outcome is SaveOutcome.ACCOUNT_DELETED
    assert await _keys(factory, user_id) == 0
