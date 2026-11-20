"""Migration ``0046`` -- the identity given at sign-up and the acceptance record
(openspec/changes/public-site, LS3, LS5).

* Six nullable columns on ``users``, nothing backfilled: the four existing users
  meet the sign-up form on their next visit (LS2).
* A profile is whole or absent, its CUIT is eleven digits and its country is
  Argentina.
* A deleted row names nobody: the identity goes with the e-mail and the name, until
  LQ6 says otherwise.
* ``legal_acceptances`` is append-only, like the ledger: no UPDATE, DELETE or
  TRUNCATE.
* The downgrade refuses while any acceptance is recorded, and otherwise leaves the
  users as 0045 had them.

Real PostgreSQL, one database per scenario, seeded at ``0045``.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.pg_head_schema import migrated_database

pytestmark = pytest.mark.integration

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_NAME = "strategy_manager_test_user_profile"
_WHOLE = "ck_users_profile_whole"
_CUIT = "ck_users_cuit_shape"
_COUNTRY = "ck_users_country_served"
_DELETED = "ck_users_deleted_names_nobody"
_PROFILE_COLUMNS = (
    "first_name",
    "last_name",
    "cuit",
    "country",
    "adult_declared_at",
    "truthful_declared_at",
)
_VALID_CUIT = "20123456786"
_DECLARED_AT = datetime(2026, 11, 19, 12, tzinfo=UTC)
#: SQLSTATE ``restrict_violation``, what the append-only trigger raises.
_RESTRICT_VIOLATION = "23001"


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url, "DRY_RUN": "false"},
        capture_output=True,
        text=True,
        check=False,
    )


def _migrate(database_url: str, *args: str) -> None:
    result = _alembic(database_url, *args)
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")


def _query(
    database_url: str, sql: str, params: dict[str, Any] | None = None
) -> list[tuple[Any, ...]]:
    async def run() -> list[tuple[Any, ...]]:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.begin() as connection:
                result = await connection.execute(text(sql), params or {})
                return [tuple(row) for row in result] if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _seed_user(database_url: str, email: str = "owner@example.com") -> UUID:
    user_id = uuid4()
    _query(
        database_url,
        "INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Owner')",
        {"id": user_id, "email": email},
    )
    return user_id


def _set_profile(database_url: str, user_id: UUID, **overrides: Any) -> None:
    values: dict[str, Any] = {
        "first_name": "Ana",
        "last_name": "Pérez",
        "cuit": _VALID_CUIT,
        "country": "AR",
        "adult_declared_at": _DECLARED_AT,
        "truthful_declared_at": _DECLARED_AT,
    }
    values.update(overrides)
    assignments = ", ".join(f"{column} = :{column}" for column in _PROFILE_COLUMNS)
    _query(
        database_url,
        f"UPDATE users SET {assignments} WHERE id = :id",
        {**values, "id": user_id},
    )


def _accept(database_url: str, user_id: UUID) -> UUID:
    acceptance_id = uuid4()
    _query(
        database_url,
        "INSERT INTO legal_acceptances (id, user_id, terms_version, privacy_version, accepted_at) "
        "VALUES (:id, :user_id, 't-1', 'p-1', now())",
        {"id": acceptance_id, "user_id": user_id},
    )
    return acceptance_id


def _refusal(database_url: str, sql: str, params: dict[str, Any]) -> tuple[str | None, str | None]:
    """The constraint the write trips BY NAME, and its SQLSTATE; never the message."""
    with pytest.raises(DBAPIError) as caught:
        _query(database_url, sql, params)
    cause = caught.value.orig.__cause__  # type: ignore[union-attr]
    return getattr(cause, "constraint_name", None), getattr(cause, "sqlstate", None)


def _profile_refusal(database_url: str, user_id: UUID, **overrides: Any) -> str | None:
    with pytest.raises(DBAPIError) as caught:
        _set_profile(database_url, user_id, **overrides)
    return getattr(caught.value.orig.__cause__, "constraint_name", None)  # type: ignore[union-attr]


def _columns(database_url: str) -> set[str]:
    rows = _query(
        database_url,
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'",
    )
    return {row[0] for row in rows}


def _has_table(database_url: str) -> bool:
    return bool(
        _query(database_url, "SELECT 1 FROM pg_tables WHERE tablename = 'legal_acceptances'")
    )


def _check_definition(database_url: str, name: str) -> str:
    rows = _query(
        database_url,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n",
        {"n": name},
    )
    return str(rows[0][0]) if rows else ""


@pytest.fixture
def at_0045() -> Iterator[str]:
    with migrated_database(_DB_NAME, "0045") as url:
        yield url


@pytest.fixture
def at_0046(at_0045: str) -> str:
    _migrate(at_0045, "upgrade", "0046")
    return at_0045


def test_upgrade_gives_nobody_a_profile_and_changes_no_user(at_0045: str) -> None:
    _seed_user(at_0045)
    columns = "id, email, created_at, last_seen_at, mode, display_name, deleted_at"
    before = _query(at_0045, f"SELECT {columns} FROM users")

    _migrate(at_0045, "upgrade", "0046")

    assert _query(at_0045, f"SELECT {columns} FROM users") == before
    assert _query(at_0045, f"SELECT {', '.join(_PROFILE_COLUMNS)} FROM users") == [
        (None,) * len(_PROFILE_COLUMNS)
    ]
    assert _query(at_0045, "SELECT count(*) FROM legal_acceptances") == [(0,)]


def test_a_whole_profile_is_stored(at_0046: str) -> None:
    user_id = _seed_user(at_0046)

    _set_profile(at_0046, user_id)

    assert _query(
        at_0046,
        "SELECT first_name, last_name, cuit, country FROM users WHERE id = :id",
        {"id": user_id},
    ) == [("Ana", "Pérez", _VALID_CUIT, "AR")]


@pytest.mark.parametrize("missing", _PROFILE_COLUMNS)
def test_a_profile_missing_any_part_is_refused(at_0046: str, missing: str) -> None:
    user_id = _seed_user(at_0046)

    assert _profile_refusal(at_0046, user_id, **{missing: None}) == _WHOLE


@pytest.mark.parametrize("cuit", ["2012345678", "201234567861", "20-12345678-6", "2O123456786"])
def test_a_cuit_that_is_not_eleven_digits_is_refused(at_0046: str, cuit: str) -> None:
    user_id = _seed_user(at_0046)

    assert _profile_refusal(at_0046, user_id, cuit=cuit) == _CUIT


def test_a_country_other_than_argentina_is_refused(at_0046: str) -> None:
    user_id = _seed_user(at_0046)

    assert _profile_refusal(at_0046, user_id, country="US") == _COUNTRY


def test_a_deleted_row_keeping_its_identity_is_refused(at_0046: str) -> None:
    user_id = _seed_user(at_0046)
    _set_profile(at_0046, user_id)

    refused = _refusal(
        at_0046,
        "UPDATE users SET deleted_at = now(), email = :email, display_name = NULL WHERE id = :id",
        {"email": f"deleted-{user_id}@invalid", "id": user_id},
    )

    assert refused[0] == _DELETED


def test_a_deleted_row_that_names_nobody_is_still_accepted(at_0046: str) -> None:
    user_id = _seed_user(at_0046)
    _set_profile(at_0046, user_id)

    _query(
        at_0046,
        "UPDATE users SET deleted_at = now(), email = :email, display_name = NULL, "
        "first_name = NULL, last_name = NULL, cuit = NULL, country = NULL, "
        "adult_declared_at = NULL, truthful_declared_at = NULL WHERE id = :id",
        {"email": f"deleted-{user_id}@invalid", "id": user_id},
    )

    assert _query(at_0046, "SELECT cuit FROM users WHERE id = :id", {"id": user_id}) == [(None,)]


def test_an_acceptance_is_recorded_for_a_user(at_0046: str) -> None:
    user_id = _seed_user(at_0046)

    acceptance_id = _accept(at_0046, user_id)

    assert _query(
        at_0046,
        "SELECT user_id, terms_version, privacy_version FROM legal_acceptances WHERE id = :id",
        {"id": acceptance_id},
    ) == [(user_id, "t-1", "p-1")]


def test_an_acceptance_for_nobody_is_refused(at_0046: str) -> None:
    refused = _refusal(
        at_0046,
        "INSERT INTO legal_acceptances (id, user_id, terms_version, privacy_version, accepted_at) "
        "VALUES (:id, :user_id, 't-1', 'p-1', now())",
        {"id": uuid4(), "user_id": uuid4()},
    )

    assert refused[0] == "fk_legal_acceptances_user"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE legal_acceptances SET terms_version = 't-2' WHERE id = :id",
        "DELETE FROM legal_acceptances WHERE id = :id",
    ],
)
def test_an_acceptance_is_never_changed_or_removed(at_0046: str, statement: str) -> None:
    acceptance_id = _accept(at_0046, _seed_user(at_0046))

    refused = _refusal(at_0046, statement, {"id": acceptance_id})

    assert refused[1] == _RESTRICT_VIOLATION
    assert _query(
        at_0046, "SELECT terms_version FROM legal_acceptances WHERE id = :id", {"id": acceptance_id}
    ) == [("t-1",)]


def test_the_acceptances_cannot_be_truncated(at_0046: str) -> None:
    _accept(at_0046, _seed_user(at_0046))

    refused = _refusal(at_0046, "TRUNCATE legal_acceptances", {})

    assert refused[1] == _RESTRICT_VIOLATION
    assert _query(at_0046, "SELECT count(*) FROM legal_acceptances") == [(1,)]


def test_downgrade_removes_everything_and_keeps_the_users(at_0046: str) -> None:
    _seed_user(at_0046)
    before = _query(at_0046, "SELECT id, email, display_name FROM users")
    deleted_check_at_0045 = (
        "CHECK (((deleted_at IS NULL) OR ((display_name IS NULL) AND "
        "(email = (('deleted-'::text || (id)::text) || '@invalid'::text)))))"
    )

    _migrate(at_0046, "downgrade", "0045")

    assert not _has_table(at_0046)
    assert _columns(at_0046).isdisjoint(_PROFILE_COLUMNS)
    assert _check_definition(at_0046, _DELETED) == deleted_check_at_0045
    assert _check_definition(at_0046, _WHOLE) == ""
    assert _query(at_0046, "SELECT id, email, display_name FROM users") == before


def test_downgrade_refuses_while_an_acceptance_is_recorded(at_0046: str) -> None:
    user_id = _seed_user(at_0046)
    _set_profile(at_0046, user_id)
    _accept(at_0046, user_id)

    result = _alembic(at_0046, "downgrade", "0045")

    assert result.returncode != 0
    assert "legal_acceptances holds 1 row" in result.stdout + result.stderr
    assert _has_table(at_0046)
    assert _query(at_0046, "SELECT cuit FROM users WHERE id = :id", {"id": user_id}) == [
        (_VALID_CUIT,)
    ]
