"""The vault recognises a lost save race by the violated constraint's NAME.

A scripted session raises an ``IntegrityError`` whose driver cause carries a
chosen ``constraint_name`` and a chosen message. Two cases pin the rule from
both sides: the name decides even when the message says nothing about it, and a
message that merely MENTIONS the index does not, when the name is another
constraint. Real Postgres proves the race itself (test_save_credential.py).
"""

import os
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, cast

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.domain.errors import ConcurrentCredentialSave
from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential, KeyFacts
from strategy_manager.accounts.infrastructure.credential_vault import (
    ONE_ACTIVE_PER_EXCHANGE_CONSTRAINT,
    SqlAlchemyCredentialVault,
)
from strategy_manager.shared.infrastructure.crypto import MASTER_KEY_BYTES, EnvelopeCipher

OTHER_CONSTRAINT = "ck_exchange_credentials_last4_length"


class _DriverError(Exception):
    """Stands in for asyncpg's ``PostgresError``, which carries the name."""

    def __init__(self, message: str, constraint_name: str | None) -> None:
        super().__init__(message)
        self.constraint_name = constraint_name


def _integrity_error(message: str, constraint_name: str | None) -> IntegrityError:
    wrapper = Exception("dbapi wrapper")
    wrapper.__cause__ = _DriverError(message, constraint_name)
    return IntegrityError("INSERT ...", {}, wrapper)


class _Nested:
    async def __aenter__(self) -> "_Nested":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False


class _ScriptedSession:
    """Deactivating the previous key flushes once; the insert's flush is the
    second, and is the one that raises."""

    def __init__(self, error: IntegrityError) -> None:
        self._error = error
        self._flushes = 0
        self.added: list[Any] = []

    def begin_nested(self) -> _Nested:
        return _Nested()

    async def execute(self, statement: object) -> None:
        return None

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self._flushes += 1
        if self._flushes == 2:
            raise self._error


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


def _vault(error: IntegrityError) -> SqlAlchemyCredentialVault:
    session = cast(AsyncSession, _ScriptedSession(error))
    return SqlAlchemyCredentialVault(
        session, EnvelopeCipher(os.urandom(MASTER_KEY_BYTES)), _FixedClock()
    )


async def _store(vault: SqlAlchemyCredentialVault) -> None:
    await vault.store(
        ExchangeCredential(
            exchange="pionex", label="default", api_key="PIONEX-FAKE-KEY-abcd", api_secret="s"
        ),
        KeyFacts.unrecorded(trade_capable=True),
    )


async def test_the_one_active_constraint_by_name_is_a_lost_race_whatever_the_message() -> None:
    error = _integrity_error("something the driver reworded", ONE_ACTIVE_PER_EXCHANGE_CONSTRAINT)

    with pytest.raises(ConcurrentCredentialSave):
        await _store(_vault(error))


async def test_another_constraint_is_not_a_lost_race_even_if_the_message_names_the_index() -> None:
    error = _integrity_error(
        f'violates check constraint, see also "{ONE_ACTIVE_PER_EXCHANGE_CONSTRAINT}"',
        OTHER_CONSTRAINT,
    )

    with pytest.raises(IntegrityError):
        await _store(_vault(error))


async def test_an_integrity_error_with_no_constraint_name_is_not_a_lost_race() -> None:
    error = _integrity_error(ONE_ACTIVE_PER_EXCHANGE_CONSTRAINT, None)

    with pytest.raises(IntegrityError):
        await _store(_vault(error))
