"""``SqlAlchemyStrategyRepository.delete`` translates a foreign-key refusal into
``StrategyStillReferenced``, by SQLSTATE and by constraint NAME.

A scripted session raises an ``IntegrityError`` whose driver cause carries a chosen
SQLSTATE, constraint name and message (the pattern of
``tests/accounts/infrastructure/test_credential_vault_constraint_name.py``). Real
PostgreSQL proves the refusal itself in ``test_delete_strategy_integration.py``.
"""

from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.strategies.application.ports import StrategyStillReferenced
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository


class _DriverError(Exception):
    """Stands in for asyncpg's ``PostgresError``, which carries both fields."""

    def __init__(self, message: str, sqlstate: str, constraint_name: str | None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name


def _integrity_error(message: str, sqlstate: str, constraint_name: str | None) -> IntegrityError:
    wrapper = Exception("dbapi wrapper")
    wrapper.__cause__ = _DriverError(message, sqlstate, constraint_name)
    return IntegrityError("DELETE ...", {}, wrapper)


class _ScriptedSession:
    def __init__(self, error: IntegrityError) -> None:
        self._error = error

    async def execute(self, statement: object) -> None:
        raise self._error

    async def flush(self) -> None:  # pragma: no cover -- execute raises first
        return None


def _repository(error: IntegrityError) -> SqlAlchemyStrategyRepository:
    return SqlAlchemyStrategyRepository(cast(AsyncSession, cast(Any, _ScriptedSession(error))))


async def test_a_foreign_key_violation_raises_still_referenced_with_the_constraint_name() -> None:
    error = _integrity_error("any text", "23503", "fk_booking_proposals_strategy")

    with pytest.raises(StrategyStillReferenced) as raised:
        await _repository(error).delete(uuid4())

    assert raised.value.constraint == "fk_booking_proposals_strategy"


async def test_the_constraint_is_read_from_its_name_and_never_from_the_message_text() -> None:
    error = _integrity_error(
        'violates foreign key constraint "fk_signals_strategy"',
        "23503",
        "fk_ledger_entries_strategy",
    )

    with pytest.raises(StrategyStillReferenced) as raised:
        await _repository(error).delete(uuid4())

    assert raised.value.constraint == "fk_ledger_entries_strategy"


async def test_any_other_integrity_error_is_reraised_unchanged() -> None:
    error = _integrity_error("duplicate", "23505", "uq_strategies_name")

    with pytest.raises(IntegrityError) as raised:
        await _repository(error).delete(uuid4())

    assert raised.value is error
