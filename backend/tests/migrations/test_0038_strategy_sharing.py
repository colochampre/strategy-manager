"""Migration ``0038`` -- sharing a strategy off the public list, by a link or by
single-use invitation codes (multi-user decision 41; tasks.md K.1).

* ``strategies.visibility`` takes ``LINK`` beside ``PUBLIC`` and ``PRIVATE``.
* ``strategies.share_token`` is the link's token: set exactly while the strategy is
  ``LINK``, shaped as ``secrets.token_urlsafe(32)`` writes one, and never shared by
  two strategies. Existing strategies keep their visibility and get none.
* ``invite_codes`` holds a strategy's codes: a SHA-256 hash, never the code; a hint
  of its last four characters; an expiry after its creation; revoked or redeemed,
  never both; a redemption recorded whole (who, when and the seat it made), and
  one code per seat. A strategy's deletion takes its codes with it, as it takes its
  subscriptions.
* The downgrade refuses while a strategy is ``LINK`` or a code exists, rather than
  dropping them, and otherwise restores ``0037``'s schema.

Real PostgreSQL, one database per scenario, seeded at ``0037``.
"""

import asyncio
import hashlib
import os
import secrets
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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
_DB_NAME = "strategy_manager_test_strategy_sharing"
_VISIBILITY = "ck_strategies_visibility"
_TOKEN_IFF_LINK = "ck_strategies_share_token_iff_link"
_TOKEN_SHAPE = "ck_strategies_share_token_shape"
_TOKEN_UNIQUE = "ux_strategies_share_token"
_HASH_SHAPE = "ck_invite_codes_code_hash_shape"
_HINT_SHAPE = "ck_invite_codes_hint_shape"
_EXPIRY = "ck_invite_codes_expiry_after_creation"
_REDEMPTION_WHOLE = "ck_invite_codes_redemption_whole"
_REVOKED_OR_REDEEMED = "ck_invite_codes_revoked_or_redeemed"
_HASH_UNIQUE = "ux_invite_codes_code_hash"
_ONE_CODE_PER_SEAT = "ux_invite_codes_subscription"
_STRATEGY_COLUMNS = "id, author_id, name, visibility, description, created_at"
T0 = datetime(2026, 11, 7, 12, tzinfo=UTC)


def _alembic(database_url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url, "DRY_RUN": "false"},
        capture_output=True,
        text=True,
        check=False,
    )
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


def _violated(database_url: str, sql: str, params: dict[str, Any]) -> str | None:
    """The constraint a write trips, BY NAME, never by message text."""
    with pytest.raises(DBAPIError) as caught:
        _query(database_url, sql, params)
    return getattr(caught.value.orig.__cause__, "constraint_name", None)  # type: ignore[union-attr]


def _exists(database_url: str, sql: str, params: dict[str, Any]) -> bool:
    return bool(_query(database_url, sql, params))


def _has_column(database_url: str, table: str, column: str) -> bool:
    return _exists(
        database_url,
        "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c",
        {"t": table, "c": column},
    )


def _has_table(database_url: str, table: str) -> bool:
    return _exists(
        database_url, "SELECT 1 FROM information_schema.tables WHERE table_name = :t", {"t": table}
    )


def _token() -> str:
    return secrets.token_urlsafe(32)


def _hash() -> str:
    return hashlib.sha256(secrets.token_bytes(8)).hexdigest()


class World:
    """One user with a pool and strategies at ``0037``."""

    def __init__(self, url: str, email: str = "owner@example.com") -> None:
        self.url = url
        self.user = self.new_user(email)
        self.pool = int(
            _query(
                url,
                "INSERT INTO capital_pools (user_id, exchange, venue, settlement_currency, "
                "min_order_size) VALUES (:u, 'binance', 'usdt-m', 'USDT', 5) RETURNING id",
                {"u": self.user},
            )[0][0]
        )

    def new_user(self, email: str) -> UUID:
        user = uuid4()
        _query(self.url, "INSERT INTO users (id, email) VALUES (:id, :e)", {"id": user, "e": email})
        return user

    def strategy(self, name: str = "first", visibility: str = "PRIVATE") -> UUID:
        strategy = uuid4()
        _query(
            self.url,
            "INSERT INTO strategies (id, author_id, name, exchange, venue, settlement_currency, "
            "fill_mode, webhook_secret_hash, webhook_secret_last4, visibility) VALUES (:id, :u, "
            ":n, 'binance', 'usdt-m', 'USDT', 'PARTIAL', 'fixture-hash', 'fxtr', :v)",
            {"id": strategy, "u": self.user, "n": name, "v": visibility},
        )
        return strategy

    def subscription(self, strategy: UUID) -> UUID:
        subscription = uuid4()
        _query(
            self.url,
            "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, allocation_percent) "
            "VALUES (:id, :u, :s, :p, 20)",
            {"id": subscription, "u": self.user, "s": strategy, "p": self.pool},
        )
        return subscription

    def code(self, strategy: UUID, **columns: Any) -> UUID:
        """A live code on ``strategy``; ``columns`` override any of its values."""
        code = uuid4()
        values: dict[str, Any] = {
            "id": code,
            "strategy_id": strategy,
            "code_hash": _hash(),
            "hint": "K7QM",
            "created_at": T0,
            "expires_at": T0 + timedelta(days=7),
            "revoked_at": None,
            "redeemed_by": None,
            "redeemed_at": None,
            "subscription_id": None,
            **columns,
        }
        names = ", ".join(values)
        _query(
            self.url,
            f"INSERT INTO invite_codes ({names}) VALUES ({', '.join(':' + n for n in values)})",  # noqa: S608
            values,
        )
        return code

    def insert_code(self, strategy: UUID, **columns: Any) -> str | None:
        """The constraint a code with ``columns`` trips."""
        with pytest.raises(DBAPIError) as caught:
            self.code(strategy, **columns)
        return getattr(caught.value.orig.__cause__, "constraint_name", None)  # type: ignore[union-attr]


@pytest.fixture
def at_0037() -> Iterator[str]:
    with migrated_database(_DB_NAME, "0037") as url:
        yield url


# --- strategies -------------------------------------------------------------------


def test_every_existing_strategy_keeps_its_visibility_and_gets_no_token(at_0037: str) -> None:
    world = World(at_0037)
    world.strategy("public", "PUBLIC")
    world.strategy("private", "PRIVATE")
    before = _query(at_0037, f"SELECT {_STRATEGY_COLUMNS} FROM strategies ORDER BY id")

    _alembic(at_0037, "upgrade", "0038")

    assert _query(at_0037, f"SELECT {_STRATEGY_COLUMNS} FROM strategies ORDER BY id") == before
    assert _query(at_0037, "SELECT count(*) FROM strategies WHERE share_token IS NULL") == [(2,)]


def test_a_strategy_turns_link_with_a_token_and_back_without_one(at_0037: str) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    _alembic(at_0037, "upgrade", "0038")
    token = _token()

    _query(
        at_0037,
        "UPDATE strategies SET visibility = 'LINK', share_token = :t WHERE id = :id",
        {"t": token, "id": strategy},
    )
    assert _query(at_0037, "SELECT visibility, share_token FROM strategies") == [("LINK", token)]

    _query(
        at_0037,
        "UPDATE strategies SET visibility = 'PRIVATE', share_token = NULL WHERE id = :id",
        {"id": strategy},
    )
    assert _query(at_0037, "SELECT visibility, share_token FROM strategies") == [("PRIVATE", None)]


def test_the_visibility_check_refuses_anything_else(at_0037: str) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    _alembic(at_0037, "upgrade", "0038")

    assert (
        _violated(
            at_0037, "UPDATE strategies SET visibility = 'INVITE' WHERE id = :id", {"id": strategy}
        )
        == _VISIBILITY
    )


@pytest.mark.parametrize(
    ("visibility", "with_token"),
    [("LINK", False), ("PRIVATE", True), ("PUBLIC", True)],
    ids=["link-without-token", "private-with-token", "public-with-token"],
)
def test_a_token_is_set_exactly_while_the_strategy_is_link(
    at_0037: str, visibility: str, with_token: bool
) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    _alembic(at_0037, "upgrade", "0038")

    assert (
        _violated(
            at_0037,
            "UPDATE strategies SET visibility = :v, share_token = :t WHERE id = :id",
            {"v": visibility, "t": _token() if with_token else None, "id": strategy},
        )
        == _TOKEN_IFF_LINK
    )


@pytest.mark.parametrize(
    "token",
    ["short", "a" * 42, "a" * 44, "a" * 42 + "=", "a" * 42 + "+", "a" * 42 + "/", "a" * 42 + " "],
    ids=["short", "42", "44", "padding", "plus", "slash", "space"],
)
def test_the_token_has_the_shape_token_urlsafe_writes(at_0037: str, token: str) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    _alembic(at_0037, "upgrade", "0038")

    assert (
        _violated(
            at_0037,
            "UPDATE strategies SET visibility = 'LINK', share_token = :t WHERE id = :id",
            {"t": token, "id": strategy},
        )
        == _TOKEN_SHAPE
    )


def test_two_strategies_never_share_a_token(at_0037: str) -> None:
    world = World(at_0037)
    first, second = world.strategy("first"), world.strategy("second")
    _alembic(at_0037, "upgrade", "0038")
    token = _token()
    _query(
        at_0037,
        "UPDATE strategies SET visibility = 'LINK', share_token = :t WHERE id = :id",
        {"t": token, "id": first},
    )

    assert (
        _violated(
            at_0037,
            "UPDATE strategies SET visibility = 'LINK', share_token = :t WHERE id = :id",
            {"t": token, "id": second},
        )
        == _TOKEN_UNIQUE
    )


# --- invite codes -----------------------------------------------------------------


def test_a_live_code_and_a_redeemed_one_are_written_as_given(at_0037: str) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    seat = world.subscription(strategy)
    _alembic(at_0037, "upgrade", "0038")

    live = world.code(strategy)
    redeemed = world.code(
        strategy, redeemed_by=world.user, redeemed_at=T0 + timedelta(days=1), subscription_id=seat
    )
    revoked = world.code(strategy, revoked_at=T0 + timedelta(hours=1))

    assert _query(
        at_0037,
        "SELECT id, redeemed_by, subscription_id, revoked_at IS NOT NULL FROM invite_codes "
        "ORDER BY created_at, id",
    ) == sorted(
        [
            (live, None, None, False),
            (redeemed, world.user, seat, False),
            (revoked, None, None, True),
        ]
    )


@pytest.mark.parametrize(
    "code_hash",
    ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "K7QM-4XPD"],
    ids=["empty", "63", "65", "upper", "not-hex", "the-code-itself"],
)
def test_a_code_is_stored_only_as_a_sha256_hex_hash(at_0037: str, code_hash: str) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    _alembic(at_0037, "upgrade", "0038")

    assert world.insert_code(strategy, code_hash=code_hash) == _HASH_SHAPE


@pytest.mark.parametrize(
    "hint", ["", "K7Q", "K7QMX", "k7qm", "K7QI", "K7QL", "K7QO", "K7QU", "K-QM"],
    ids=["empty", "3", "5", "lower", "I", "L", "O", "U", "dash"],
)
def test_the_hint_is_four_crockford_base32_characters(at_0037: str, hint: str) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    _alembic(at_0037, "upgrade", "0038")

    assert world.insert_code(strategy, hint=hint) == _HINT_SHAPE


@pytest.mark.parametrize("expires_at", [T0, T0 - timedelta(seconds=1)], ids=["equal", "before"])
def test_a_code_expires_after_it_was_made(at_0037: str, expires_at: datetime) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    _alembic(at_0037, "upgrade", "0038")

    assert world.insert_code(strategy, expires_at=expires_at) == _EXPIRY


@pytest.mark.parametrize(
    "missing", ["redeemed_by", "redeemed_at", "subscription_id"], ids=lambda name: f"no-{name}"
)
def test_a_redemption_is_recorded_whole(at_0037: str, missing: str) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    seat = world.subscription(strategy)
    _alembic(at_0037, "upgrade", "0038")
    redemption = {"redeemed_by": world.user, "redeemed_at": T0, "subscription_id": seat}

    assert world.insert_code(strategy, **{**redemption, missing: None}) == _REDEMPTION_WHOLE


def test_a_code_is_never_both_revoked_and_redeemed(at_0037: str) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    seat = world.subscription(strategy)
    _alembic(at_0037, "upgrade", "0038")

    assert (
        world.insert_code(
            strategy,
            revoked_at=T0,
            redeemed_by=world.user,
            redeemed_at=T0,
            subscription_id=seat,
        )
        == _REVOKED_OR_REDEEMED
    )


def test_two_codes_never_share_a_hash(at_0037: str) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    _alembic(at_0037, "upgrade", "0038")
    code_hash = _hash()
    world.code(strategy, code_hash=code_hash)

    assert world.insert_code(world.strategy("second"), code_hash=code_hash) == _HASH_UNIQUE


def test_one_seat_is_made_by_one_code_at_most(at_0037: str) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    seat = world.subscription(strategy)
    _alembic(at_0037, "upgrade", "0038")
    redemption = {"redeemed_by": world.user, "redeemed_at": T0, "subscription_id": seat}
    world.code(strategy, **redemption)

    assert world.insert_code(strategy, **redemption) == _ONE_CODE_PER_SEAT


def test_deleting_a_strategy_takes_its_codes_and_leaves_the_others(at_0037: str) -> None:
    world = World(at_0037)
    gone, kept = world.strategy("gone"), world.strategy("kept")
    seat = world.subscription(gone)
    _alembic(at_0037, "upgrade", "0038")
    world.code(gone)
    world.code(gone, redeemed_by=world.user, redeemed_at=T0, subscription_id=seat)
    survivor = world.code(kept)

    _query(at_0037, "DELETE FROM strategies WHERE id = :id", {"id": gone})

    assert _query(at_0037, "SELECT id FROM invite_codes") == [(survivor,)]


# --- downgrade --------------------------------------------------------------------


def test_downgrade_refuses_while_a_strategy_is_link_and_changes_nothing(at_0037: str) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    _alembic(at_0037, "upgrade", "0038")
    token = _token()
    _query(
        at_0037,
        "UPDATE strategies SET visibility = 'LINK', share_token = :t WHERE id = :id",
        {"t": token, "id": strategy},
    )

    with pytest.raises(RuntimeError, match="shared by a link"):
        _alembic(at_0037, "downgrade", "0037")

    assert _query(at_0037, "SELECT version_num FROM alembic_version") == [("0038",)]
    assert _query(at_0037, "SELECT visibility, share_token FROM strategies") == [("LINK", token)]


def test_downgrade_refuses_while_a_code_exists_and_changes_nothing(at_0037: str) -> None:
    world = World(at_0037)
    strategy = world.strategy()
    _alembic(at_0037, "upgrade", "0038")
    code = world.code(strategy, revoked_at=T0)

    with pytest.raises(RuntimeError, match="invitation code"):
        _alembic(at_0037, "downgrade", "0037")

    assert _query(at_0037, "SELECT version_num FROM alembic_version") == [("0038",)]
    assert _query(at_0037, "SELECT id FROM invite_codes") == [(code,)]


def test_downgrade_restores_0037_and_the_upgrade_runs_again(at_0037: str) -> None:
    world = World(at_0037)
    public = world.strategy("public", "PUBLIC")
    private = world.strategy("private", "PRIVATE")
    _alembic(at_0037, "upgrade", "0038")

    _alembic(at_0037, "downgrade", "0037")

    assert not _has_column(at_0037, "strategies", "share_token")
    assert not _has_table(at_0037, "invite_codes")
    for name in (_TOKEN_IFF_LINK, _TOKEN_SHAPE, _TOKEN_UNIQUE):
        assert not _exists(
            at_0037, "SELECT 1 FROM pg_class WHERE relname = :n "
            "UNION SELECT 1 FROM pg_constraint WHERE conname = :n", {"n": name}
        )
    assert (
        _violated(
            at_0037, "UPDATE strategies SET visibility = 'LINK' WHERE id = :id", {"id": private}
        )
        == _VISIBILITY
    )
    assert _query(at_0037, "SELECT id, visibility FROM strategies ORDER BY name") == [
        (private, "PRIVATE"),
        (public, "PUBLIC"),
    ]

    _alembic(at_0037, "upgrade", "0038")

    assert _has_table(at_0037, "invite_codes")
