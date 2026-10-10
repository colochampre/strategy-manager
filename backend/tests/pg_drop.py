"""Drop a throwaway test database, waiting out a backend the test role cannot end.

``DROP DATABASE ... WITH (FORCE)`` terminates every backend connected to the
database. The test role may terminate only backends of its own role, so an
autovacuum worker that is looking at the throwaway database at that moment (it
runs as no ordinary role, and PostgreSQL gives a new database an early visit)
makes the drop fail with ``permission denied to terminate process``. Measured on
2026-10-09: the backend is invisible to the test role (``pg_stat_activity``
masks every column but its pid), it shows in ``pg_stat_progress_analyze`` and then
``pg_stat_progress_vacuum``, and the refusal cleared within 0.84 s in every
captured case. The helper therefore retries that one refusal for a bounded time.

What it does NOT do, on purpose:

- It retries nothing else. A drop refused for another reason, including another
  ``InsufficientPrivilegeError`` (the role does not own the database), raises at
  once and unchanged.
- It never swallows the failure. When the time runs out it raises
  ``DatabaseDropRefusedError`` naming the database and what ``pg_stat_activity``
  shows for it, chained to the last refusal. A leftover database is an error.
- It needs no superuser and grants nothing. Every message is built from the
  database name and backend metadata; no DSN, password or query text is in it.

The refusal is recognised by its SQLSTATE (42501) AND by the test role owning the
database, never by the message text: the server's message is localised.
"""

import asyncio
import time
from typing import Protocol

import asyncpg

DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_INTERVAL_SECONDS = 0.1

_MASKED = "<not visible to the test role: a backend of another role>"


class DatabaseDropRefusedError(RuntimeError):
    """The drop kept being refused until the time ran out."""


class _Connection(Protocol):
    async def execute(self, query: str, /) -> str: ...

    async def fetch(self, query: str, /, *args: object) -> list[asyncpg.Record]: ...

    async def fetchval(self, query: str, /, *args: object) -> object: ...


async def _owned_by_the_test_role(conn: _Connection, name: str) -> bool:
    """True when the database exists and the connected role has the owner's privileges.

    Only then can a 42501 on ``DROP DATABASE`` mean "a backend I may not
    terminate": for a database the role does not own, 42501 means "must be owner".
    """
    owned = await conn.fetchval(
        "SELECT pg_catalog.pg_has_role(current_user, datdba, 'USAGE') "
        "FROM pg_catalog.pg_database WHERE datname = $1",
        name,
    )
    return owned is True


async def _describe_backends(conn: _Connection, name: str) -> str:
    try:
        rows = await conn.fetch(
            "SELECT backend_type, usename, state FROM pg_catalog.pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_catalog.pg_backend_pid()",
            name,
        )
    except Exception as error:  # noqa: BLE001 - the diagnosis must never hide the refusal
        return f"backends unknown ({type(error).__name__})"
    if not rows:
        return "no backend listed any more"
    return "; ".join(
        f"{row['backend_type'] or _MASKED} (role {row['usename'] or 'unknown'})" for row in rows
    )


async def drop_database_on(
    conn: _Connection,
    name: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
) -> None:
    """``DROP DATABASE IF EXISTS`` on an open maintenance connection, with the bounded retry."""
    statement = f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'
    deadline = time.monotonic() + timeout_seconds
    attempts = 0
    while True:
        attempts += 1
        try:
            await conn.execute(statement)
            return
        except asyncpg.exceptions.InsufficientPrivilegeError as refusal:
            if not await _owned_by_the_test_role(conn, name):
                raise
            if time.monotonic() >= deadline:
                backends = await _describe_backends(conn, name)
                raise DatabaseDropRefusedError(
                    f'DROP DATABASE "{name}" was refused {attempts} times in '
                    f"{timeout_seconds:g} s because a backend connected to it could not be "
                    f"terminated; backends listed: {backends}. The database is left behind."
                ) from refusal
        await asyncio.sleep(interval_seconds)


async def drop_database_if_exists(
    maintenance_dsn: str,
    name: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
) -> None:
    """Connect to the maintenance database, drop ``name`` if it exists, disconnect."""
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await drop_database_on(
            conn, name, timeout_seconds=timeout_seconds, interval_seconds=interval_seconds
        )
    finally:
        await conn.close()
