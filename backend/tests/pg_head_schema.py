"""A throwaway database migrated to ``head`` with Alembic.

The ORM-built test database (``tests/pg_schema.py``, ``Base.metadata.create_all``)
has no foreign key on ``signals.strategy_id``, ``booking_proposals.strategy_id``
or ``strategy_enablement_events.strategy_id``, and none of the append-only
triggers: those exist only in the migrations. A test whose outcome is decided by
one of them proves nothing on the ORM schema, so it runs on a database built
here instead.

``migrated_head_database(name)`` is a context manager:

1. derives the database URL from ``get_settings().database_url`` by swapping the
   database name (the dev database itself is never touched),
2. drops any leftover database of that name, creates it empty,
3. runs ``alembic upgrade head`` against it in a subprocess (alembic calls
   ``asyncio.run`` itself, which must not collide with a running test loop),
4. yields the SQLAlchemy URL, and
5. drops the database (``WITH (FORCE)``) on exit, success or failure.

The URL is the only thing that carries credentials. It is never printed: a failed
migration reports alembic's output with the URL and the password scrubbed, and
the yielded URL's ``repr``, which pytest uses to report a failing assertion,
is ``<throwaway database url>``.

A test module uses it through a module-scoped fixture of its own::

    @pytest.fixture(scope="module")
    def head_database_url() -> Iterator[str]:
        with migrated_head_database("strategy_manager_test_my_module") as url:
            yield url

Pick a name unique to the module: two modules sharing one would drop each
other's database.
"""

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import asyncpg

from strategy_manager.shared.config import get_settings
from tests.pg_drop import drop_database_if_exists

_BACKEND_DIR = Path(__file__).resolve().parents[1]


class _ThrowawayUrl(str):
    """The URL as text, for alembic, asyncpg and SQLAlchemy, with a repr that
    names no credential. pytest reports a failing assertion through ``repr``,
    arguments of the calls inside it included, so ``assert _scalar(url, ...)
    == x`` printed the local password before this (seen 2026-10-27)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<throwaway database url>"


def _maintenance_dsn(dev_url: str) -> str:
    dsn = dev_url.replace("postgresql+asyncpg://", "postgresql://")
    return re.sub(r"/[^/?]+(\?.*)?$", r"/postgres\1", dsn)


def _database_url(dev_url: str, name: str) -> str:
    return re.sub(r"/[^/?]+(\?.*)?$", rf"/{name}\1", dev_url)


async def _create_database(maintenance_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def _scrub(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


def _upgrade(database_url: str, revision: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        password = re.sub(r"^[^:]+://[^:/@]*:([^@]*)@.*$", r"\1", database_url)
        secrets = [database_url, password if password != database_url else ""]
        raise RuntimeError(
            f"alembic upgrade {revision} failed on a throwaway database:\n"
            f"{_scrub(result.stdout, secrets)}\n{_scrub(result.stderr, secrets)}"
        )


@contextmanager
def migrated_head_database(name: str) -> Iterator[str]:
    """Create ``name`` empty, migrate it to ``head``, yield its URL, drop it."""
    with migrated_database(name, "head") as url:
        yield url


@contextmanager
def migrated_database(name: str, revision: str) -> Iterator[str]:
    """Create ``name`` empty, migrate it to ``revision``, yield its URL, drop it.

    For a migration's own tests, which seed rows at the revision before it and
    then upgrade."""
    dev_url = get_settings().database_url
    url = _database_url(dev_url, name)
    if url == dev_url:
        raise RuntimeError("the head database must not be the dev database")
    maintenance_dsn = _maintenance_dsn(dev_url)

    asyncio.run(drop_database_if_exists(maintenance_dsn, name))
    asyncio.run(_create_database(maintenance_dsn, name))
    try:
        _upgrade(url, revision)
        yield _ThrowawayUrl(url)
    finally:
        asyncio.run(drop_database_if_exists(maintenance_dsn, name))
