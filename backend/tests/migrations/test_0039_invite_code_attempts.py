"""Migration ``0039`` -- the failed invitation-code attempts of each user (multi-user
decision 41; tasks.md K.4).

* ``invite_code_attempts`` holds one row per code a user got wrong: who and when,
  nothing of the code. A user's rows go with the user.
* The read the limit makes, a user's rows since an instant, is served by an index on
  ``(user_id, attempted_at)``.
* The downgrade drops the table: the rows only ever count the last hour.

Real PostgreSQL, one database per scenario, seeded at ``0038``.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from tests.migrations.test_0038_strategy_sharing import (
    _alembic,
    _has_table,
    _query,
    _violated,
)
from tests.pg_head_schema import migrated_database

pytestmark = pytest.mark.integration

_DB_NAME = "strategy_manager_test_invite_code_attempts"
_USER_FK = "fk_invite_code_attempts_user"
_INDEX = "ix_invite_code_attempts_user_attempted_at"
T0 = datetime(2026, 11, 7, 12, tzinfo=UTC)


@pytest.fixture
def at_0038() -> Iterator[str]:
    with migrated_database(_DB_NAME, "0038") as url:
        yield url


def _user(url: str, email: str) -> UUID:
    user = uuid4()
    _query(url, "INSERT INTO users (id, email) VALUES (:id, :e)", {"id": user, "e": email})
    return user


def _attempt(url: str, user: UUID, at: datetime = T0) -> None:
    _query(
        url,
        "INSERT INTO invite_code_attempts (user_id, attempted_at) VALUES (:u, :at)",
        {"u": user, "at": at},
    )


def test_an_attempt_is_who_and_when_and_nothing_else(at_0038: str) -> None:
    _alembic(at_0038, "upgrade", "0039")
    user = _user(at_0038, "guesser@example.com")

    _attempt(at_0038, user)

    columns = _query(
        at_0038,
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_name = 'invite_code_attempts' ORDER BY ordinal_position",
    )
    assert columns == [
        ("id", "bigint", "NO"),
        ("user_id", "uuid", "NO"),
        ("attempted_at", "timestamp with time zone", "NO"),
    ]
    assert _query(at_0038, "SELECT user_id, attempted_at FROM invite_code_attempts") == [
        (user, T0)
    ]


def test_an_attempt_belongs_to_a_user_who_exists(at_0038: str) -> None:
    _alembic(at_0038, "upgrade", "0039")

    assert (
        _violated(
            at_0038,
            "INSERT INTO invite_code_attempts (user_id, attempted_at) VALUES (:u, :at)",
            {"u": uuid4(), "at": T0},
        )
        == _USER_FK
    )


def test_a_users_attempts_go_with_the_user_and_leave_the_others(at_0038: str) -> None:
    _alembic(at_0038, "upgrade", "0039")
    gone, kept = _user(at_0038, "gone@example.com"), _user(at_0038, "kept@example.com")
    _attempt(at_0038, gone)
    _attempt(at_0038, kept)

    _query(at_0038, "DELETE FROM users WHERE id = :id", {"id": gone})

    assert _query(at_0038, "SELECT user_id FROM invite_code_attempts") == [(kept,)]


def test_the_limits_read_has_its_index(at_0038: str) -> None:
    _alembic(at_0038, "upgrade", "0039")

    [(definition,)] = _query(
        at_0038, "SELECT indexdef FROM pg_indexes WHERE indexname = :n", {"n": _INDEX}
    )
    assert definition.endswith("(user_id, attempted_at)")


def test_downgrade_drops_the_table_and_the_upgrade_runs_again(at_0038: str) -> None:
    _alembic(at_0038, "upgrade", "0039")
    _attempt(at_0038, _user(at_0038, "guesser@example.com"))

    _alembic(at_0038, "downgrade", "0038")

    assert not _has_table(at_0038, "invite_code_attempts")
    assert _has_table(at_0038, "invite_codes")

    _alembic(at_0038, "upgrade", "0039")

    assert _has_table(at_0038, "invite_code_attempts")
