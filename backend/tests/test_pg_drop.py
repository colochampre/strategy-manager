"""The shared drop of a throwaway database retries ONE refusal, and only that one.

``DROP DATABASE ... WITH (FORCE)`` terminates every backend connected to the
database. The test role may terminate only its own backends, so a backend it does
not own (an autovacuum worker that connected to the database) makes the drop fail
with ``permission denied to terminate process`` until that backend goes away.
The helper waits for a bounded time for exactly that refusal and raises, loudly,
for anything else and when the time runs out.

A fake connection stands in for the server, so these tests need no database.
"""

import asyncio
from collections.abc import Sequence
from typing import Any

import asyncpg
import pytest

from tests.pg_drop import drop_database_on

_NAME = "strategy_manager_test_fake_drop"
_TERMINATE_REFUSAL = "permission denied to terminate process"


class FakeConnection:
    """Raises the scripted errors, one per ``execute``, then succeeds."""

    def __init__(
        self,
        errors: Sequence[BaseException] = (),
        *,
        forever: BaseException | None = None,
        backends: Sequence[str | None] = ("autovacuum worker",),
        owned: bool = True,
    ) -> None:
        self._errors = list(errors)
        self._forever = forever
        self._backends = list(backends)
        self._owned = owned
        self.statements: list[str] = []

    async def execute(self, statement: str) -> str:
        self.statements.append(statement)
        if self._forever is not None:
            raise self._forever
        if self._errors:
            raise self._errors.pop(0)
        return "DROP DATABASE"

    async def fetch(self, statement: str, *args: Any) -> list[dict[str, Any]]:
        return [
            {"backend_type": backend, "usename": None, "state": None} for backend in self._backends
        ]

    async def fetchval(self, statement: str, *args: Any) -> bool:
        """Whether the connected role owns the database."""
        return self._owned


def _terminate_refused() -> asyncpg.exceptions.InsufficientPrivilegeError:
    return asyncpg.exceptions.InsufficientPrivilegeError(_TERMINATE_REFUSAL)


async def _capture(coro: Any) -> BaseException | None:
    try:
        await coro
    except Exception as error:  # noqa: BLE001 - the test inspects the type
        return error
    return None


async def test_a_refused_drop_is_retried_until_it_succeeds() -> None:
    conn = FakeConnection([_terminate_refused(), _terminate_refused()])

    raised = await _capture(
        drop_database_on(conn, _NAME, timeout_seconds=5.0, interval_seconds=0.001)  # type: ignore[arg-type]
    )

    assert raised is None
    assert len(conn.statements) == 3
    assert conn.statements[-1] == f'DROP DATABASE IF EXISTS "{_NAME}" WITH (FORCE)'


async def test_a_drop_that_is_always_refused_gives_up_and_names_the_database() -> None:
    conn = FakeConnection(forever=_terminate_refused(), backends=("autovacuum worker",))

    raised = await asyncio.wait_for(
        _capture(
            drop_database_on(conn, _NAME, timeout_seconds=0.2, interval_seconds=0.01)  # type: ignore[arg-type]
        ),
        timeout=5.0,
    )

    assert raised is not None
    assert _NAME in str(raised)
    assert "autovacuum worker" in str(raised)
    assert len(conn.statements) > 1


async def test_a_backend_the_role_cannot_describe_is_named_as_such() -> None:
    conn = FakeConnection(forever=_terminate_refused(), backends=(None,))

    raised = await asyncio.wait_for(
        _capture(
            drop_database_on(conn, _NAME, timeout_seconds=0.1, interval_seconds=0.01)  # type: ignore[arg-type]
        ),
        timeout=5.0,
    )

    assert raised is not None
    assert "another role" in str(raised)
    assert _NAME in str(raised)


async def test_the_refusal_that_ends_the_wait_is_chained_to_the_error() -> None:
    conn = FakeConnection(forever=_terminate_refused())

    raised = await asyncio.wait_for(
        _capture(
            drop_database_on(conn, _NAME, timeout_seconds=0.1, interval_seconds=0.01)  # type: ignore[arg-type]
        ),
        timeout=5.0,
    )

    assert isinstance(raised, BaseException)
    assert isinstance(raised.__cause__, asyncpg.exceptions.InsufficientPrivilegeError)


async def test_any_other_error_is_raised_at_once_and_not_retried() -> None:
    conn = FakeConnection([asyncpg.exceptions.ObjectInUseError("database is being accessed")])

    raised = await _capture(
        drop_database_on(conn, _NAME, timeout_seconds=5.0, interval_seconds=0.001)  # type: ignore[arg-type]
    )

    assert isinstance(raised, asyncpg.exceptions.ObjectInUseError)
    assert len(conn.statements) == 1


async def test_a_privilege_error_about_anything_else_is_raised_at_once() -> None:
    conn = FakeConnection(
        [asyncpg.exceptions.InsufficientPrivilegeError("must be owner of database")],
        owned=False,
    )

    raised = await _capture(
        drop_database_on(conn, _NAME, timeout_seconds=5.0, interval_seconds=0.001)  # type: ignore[arg-type]
    )

    assert isinstance(raised, asyncpg.exceptions.InsufficientPrivilegeError)
    assert len(conn.statements) == 1


@pytest.mark.parametrize("fails", [0, 1])
async def test_a_drop_that_works_first_or_second_time_leaves_no_error(fails: int) -> None:
    conn = FakeConnection([_terminate_refused()] * fails)

    raised = await _capture(
        drop_database_on(conn, _NAME, timeout_seconds=5.0, interval_seconds=0.001)  # type: ignore[arg-type]
    )

    assert raised is None
    assert len(conn.statements) == fails + 1
