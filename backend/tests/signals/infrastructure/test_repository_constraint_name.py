"""The signals repository recognises an unregistered strategy by constraint NAME.

A scripted session raises an ``IntegrityError`` whose driver cause carries a
chosen ``constraint_name`` and a chosen message, on the ``INSERT``. Three cases
pin the rule from both sides: the foreign key's name is translated, any other
constraint is re-raised unchanged, and a message that merely MENTIONS the
foreign key is not enough when the name says another constraint. Real
PostgreSQL proves the translation end to end (test_unknown_strategy_ingress.py).
"""

from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.signals.application.ports import UnknownSignalStrategy
from strategy_manager.signals.domain.signal import IdempotencyKey, SignalStatus, WebhookSignal
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository

FK_CONSTRAINT = "fk_signals_strategy"
OTHER_CONSTRAINT = "uq_signals_strategy_idempotency"


class _DriverError(Exception):
    """Stands in for asyncpg's ``PostgresError``, which carries the name."""

    def __init__(self, message: str, constraint_name: str | None) -> None:
        super().__init__(message)
        self.constraint_name = constraint_name


def _integrity_error(message: str, constraint_name: str | None) -> IntegrityError:
    wrapper = Exception("dbapi wrapper")
    wrapper.__cause__ = _DriverError(message, constraint_name)
    return IntegrityError("INSERT ...", {}, wrapper)


class _ScriptedSession:
    def __init__(self, error: IntegrityError) -> None:
        self._error = error

    async def execute(self, statement: object) -> None:
        raise self._error


def _repository(error: IntegrityError) -> SqlAlchemySignalRepository:
    return SqlAlchemySignalRepository(cast(AsyncSession, _ScriptedSession(error)))


def _signal() -> WebhookSignal:
    return WebhookSignal(
        strategy_id=uuid4(),
        idempotency_key=IdempotencyKey("k" * 64),
        action="buy",
        contracts=Decimal("1"),
        position_size=Decimal("1"),
        price=Decimal("1"),
        symbol="STXUSDT.P",
        signal_type="irrelevant",
        raw_payload={},
        status=SignalStatus.ACCEPTED,
    )


async def test_a_violation_of_fk_signals_strategy_raises_unknown_signal_strategy_carrying_the_id() -> None:  # noqa: E501
    signal = _signal()
    error = _integrity_error("something the driver reworded", FK_CONSTRAINT)

    with pytest.raises(BaseException) as raised:  # noqa: PT011 -- asserted on the type below
        await _repository(error).insert_or_get(signal)

    assert raised.type is UnknownSignalStrategy
    assert getattr(raised.value, "strategy_id", None) == signal.strategy_id


async def test_any_other_integrity_error_is_reraised_unchanged() -> None:
    error = _integrity_error("duplicate key value", OTHER_CONSTRAINT)

    with pytest.raises(BaseException) as raised:  # noqa: PT011 -- asserted on identity below
        await _repository(error).insert_or_get(_signal())

    assert raised.value is error


async def test_the_constraint_is_matched_by_name_and_never_by_message_text() -> None:
    error = _integrity_error(
        f'insert violates foreign key constraint "{FK_CONSTRAINT}" (reworded)',
        OTHER_CONSTRAINT,
    )

    with pytest.raises(BaseException) as raised:  # noqa: PT011 -- asserted on identity below
        await _repository(error).insert_or_get(_signal())

    assert raised.value is error
