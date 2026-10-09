"""Migration ``0027`` -- how each fact about a key was established (design
addendum "key policy after probe P6", section B; tasks.md unit 6a).

Real PostgreSQL, following ``test_0026_reservation_pool_total.py``. Two kinds of
database:

- one module-scoped database at ``head``, for the constraint tests. Every row
  they insert is inactive, so the one-active-per-exchange index never gets in
  the way and nothing needs cleaning between tests;
- throwaway databases, for the tests that need a database BEFORE 0027 (the
  backfill) or that complete a downgrade (which drops columns every other test
  depends on).

Rule 1: no real credential. Ciphertexts are junk bytes; nothing here decrypts.
"""

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from strategy_manager.shared.config import get_settings
from tests.pg_drop import drop_database_if_exists

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_NAME = "strategy_manager_test_credential_snapshot"
_THROWAWAY_DB_PREFIX = "strategy_manager_test_credential_snapshot_throwaway"

_TABLE = "exchange_credentials"
_NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)

_SOURCES_KNOWN = "ck_exchange_credentials_sources_known"
_CONFIRMATION_HAS_TIMESTAMP = "ck_exchange_credentials_confirmation_has_timestamp"
_CONFIRMED_TRADE_IS_CAPABLE = "ck_exchange_credentials_confirmed_trade_is_capable"
_RECORDED_OR_LEGACY = "ck_exchange_credentials_recorded_or_legacy"
_BINANCE_NOT_VERIFIED = "ck_exchange_credentials_binance_not_verified"
_BYBIT_NOT_OWNER_CONFIRMED = "ck_exchange_credentials_bybit_not_owner_confirmed"

_NEW_COLUMNS = [
    "trade_capable",
    "trade_capability_source",
    "trade_confirmed_at",
    "withdraw_check",
    "withdraw_confirmed_at",
    "validated_at",
    "internal_transfer",
]


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


def _run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Runs alembic in a subprocess so its own ``asyncio.run`` never collides
    with the test's running loop."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )


def _run_alembic_ok(database_url: str, *args: str) -> None:
    result = _run_alembic(database_url, *args)
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")


def _constraint_name(error: IntegrityError) -> str | None:
    """The violated constraint BY NAME, never by message text (binding testing
    rule; same helper as ``test_0025_signal_outcomes.py``)."""
    return getattr(error.orig.__cause__, "constraint_name", None)  # type: ignore[union-attr]


def _column_name(error: IntegrityError) -> str | None:
    return getattr(error.orig.__cause__, "column_name", None)  # type: ignore[union-attr]


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    dev_url = get_settings().database_url
    maintenance_dsn = _maintenance_dsn(dev_url)
    url = _database_url(dev_url, _DB_NAME)

    asyncio.run(drop_database_if_exists(maintenance_dsn, _DB_NAME))
    asyncio.run(_create_database(maintenance_dsn, _DB_NAME))
    _run_alembic_ok(url, "upgrade", "head")

    yield url

    asyncio.run(drop_database_if_exists(maintenance_dsn, _DB_NAME))


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


@pytest.fixture
def throwaway_db_factory() -> Iterator[Callable[[str, str], str]]:
    """``make(suffix, upgrade_to)`` -> a fresh database migrated to ``upgrade_to``."""
    dev_url = get_settings().database_url
    maintenance_dsn = _maintenance_dsn(dev_url)
    created: list[str] = []

    def make(suffix: str, upgrade_to: str) -> str:
        name = f"{_THROWAWAY_DB_PREFIX}_{suffix}"
        url = _database_url(dev_url, name)
        asyncio.run(drop_database_if_exists(maintenance_dsn, name))
        asyncio.run(_create_database(maintenance_dsn, name))
        _run_alembic_ok(url, "upgrade", upgrade_to)
        created.append(name)
        return url

    yield make

    for name in created:
        asyncio.run(drop_database_if_exists(maintenance_dsn, name))


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------

_JUNK = b"not-a-ciphertext"


async def _insert_legacy(
    conn: AsyncConnection, *, exchange: str, is_active: bool, last4: str
) -> None:
    """A row exactly as a store script wrote it BEFORE 0027: none of the new
    columns is named."""
    await conn.execute(
        text(
            "INSERT INTO exchange_credentials "
            "(exchange, label, is_active, wrapped_dek, dek_nonce, api_key_ciphertext, "
            "api_key_nonce, api_secret_ciphertext, api_secret_nonce, api_key_last4) "
            "VALUES (:exchange, 'default', :is_active, :junk, :junk, :junk, :junk, :junk, "
            ":junk, :last4)"
        ),
        {"exchange": exchange, "is_active": is_active, "junk": _JUNK, "last4": last4},
    )


_VALID_BYBIT: dict[str, Any] = {
    "exchange": "bybit",
    "trade_capable": True,
    "trade_capability_source": "VERIFIED",
    "trade_confirmed_at": None,
    "withdraw_check": "VERIFIED",
    "withdraw_confirmed_at": None,
    "validated_at": _NOW,
    "internal_transfer": True,
}

_VALID_BINANCE: dict[str, Any] = {
    "exchange": "binance",
    "trade_capable": True,
    "trade_capability_source": "OWNER_CONFIRMED",
    "trade_confirmed_at": _NOW,
    "withdraw_check": "OWNER_CONFIRMED",
    "withdraw_confirmed_at": _NOW,
    "validated_at": _NOW,
    "internal_transfer": None,
}

_LEGACY: dict[str, Any] = {
    "exchange": "pionex",
    "trade_capable": True,
    "trade_capability_source": "UNRECORDED",
    "trade_confirmed_at": None,
    "withdraw_check": "UNRECORDED",
    "withdraw_confirmed_at": None,
    "validated_at": None,
    "internal_transfer": None,
}


async def _insert(
    conn: AsyncConnection, base: dict[str, Any], *, omit: tuple[str, ...] = (), **overrides: Any
) -> None:
    """An INACTIVE row with every new column named, except those in ``omit``."""
    values = {**base, **overrides}
    names = ["exchange", *[c for c in _NEW_COLUMNS if c not in omit]]
    columns = ", ".join([*names, "label", "is_active"])
    placeholders = ", ".join([*[f":{n}" for n in names], "'default'", "false"])
    await conn.execute(
        text(
            f"INSERT INTO exchange_credentials ({columns}, wrapped_dek, dek_nonce, "  # noqa: S608
            "api_key_ciphertext, api_key_nonce, api_secret_ciphertext, api_secret_nonce, "
            f"api_key_last4) VALUES ({placeholders}, :junk, :junk, :junk, :junk, :junk, :junk, "
            "'abcd')"
        ),
        {**{n: values[n] for n in names}, "junk": _JUNK},
    )


async def _rows(conn: AsyncConnection) -> list[Any]:
    return list(
        (
            await conn.execute(
                text(
                    "SELECT exchange, is_active, trade_capable, trade_capability_source, "
                    "trade_confirmed_at, withdraw_check, withdraw_confirmed_at, validated_at, "
                    "internal_transfer FROM exchange_credentials ORDER BY exchange, is_active"
                )
            )
        ).all()
    )


# --------------------------------------------------------------------------
# The upgrade
# --------------------------------------------------------------------------


async def test_upgrade_reaches_0027(conn: AsyncConnection) -> None:
    version = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()

    # ``head`` moves on with every later migration (0028 now); zero-padded revisions sort.
    assert version >= "0027"


async def test_the_seven_columns_exist_with_the_types_and_nullability_of_the_addendum(
    conn: AsyncConnection,
) -> None:
    rows = (
        await conn.execute(
            text(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_name = 'exchange_credentials'"
            )
        )
    ).all()
    by_name = {row.column_name: row for row in rows}

    expected = {
        "trade_capable": ("boolean", "NO"),
        "trade_capability_source": ("text", "NO"),
        "trade_confirmed_at": ("timestamp with time zone", "YES"),
        "withdraw_check": ("text", "NO"),
        "withdraw_confirmed_at": ("timestamp with time zone", "YES"),
        "validated_at": ("timestamp with time zone", "YES"),
        "internal_transfer": ("boolean", "YES"),
    }
    for name, (data_type, nullable) in expected.items():
        assert name in by_name, name
        assert (by_name[name].data_type, by_name[name].is_nullable) == (data_type, nullable), name
    # The addendum drops the raw payload: it would keep whitelisted IPs, the
    # user id and the KYC region at rest with no reader.
    assert "permissions" not in by_name


async def test_default_is_dropped_insert_without_trade_capable_or_sources_fails(
    conn: AsyncConnection,
) -> None:
    defaults = (
        await conn.execute(
            text(
                "SELECT column_name, column_default FROM information_schema.columns "
                "WHERE table_name = 'exchange_credentials' AND column_name = ANY(:names)"
            ),
            {"names": ["trade_capable", "trade_capability_source", "withdraw_check"]},
        )
    ).all()
    assert {row.column_name: row.column_default for row in defaults} == {
        "trade_capable": None,
        "trade_capability_source": None,
        "withdraw_check": None,
    }

    for omitted in ("trade_capable", "trade_capability_source", "withdraw_check"):
        with pytest.raises(IntegrityError) as raised:
            await _insert(conn, _VALID_BYBIT, omit=(omitted,))
        assert _column_name(raised.value) == omitted
        await conn.rollback()


async def test_a_valid_row_of_each_kind_is_accepted(conn: AsyncConnection) -> None:
    """Without this, every refusal below would also pass against a constraint
    that refuses everything."""
    await _insert(conn, _VALID_BYBIT)
    await _insert(conn, _VALID_BYBIT, trade_capable=False)  # a read-only Bybit key
    await _insert(conn, _VALID_BINANCE)
    await _insert(conn, _LEGACY)
    await conn.rollback()


# --------------------------------------------------------------------------
# The backfill
# --------------------------------------------------------------------------


def test_backfill_every_existing_row_trade_capable_true_both_sources_unrecorded_no_timestamps(
    throwaway_db_factory: Callable[[str, str], str],
) -> None:
    """Production holds one active key each for binance, bybit and pionex. Add
    superseded history rows too: the backfill must not care whether a row is
    active."""
    url = throwaway_db_factory("backfill", "0026")

    async def seed() -> None:
        engine = create_async_engine(url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                for exchange in ("binance", "bybit", "pionex"):
                    await _insert_legacy(
                        connection, exchange=exchange, is_active=True, last4="wxyz"
                    )
                await _insert_legacy(connection, exchange="bybit", is_active=False, last4="0001")
                await _insert_legacy(connection, exchange="binance", is_active=False, last4="0002")
                await connection.commit()
        finally:
            await engine.dispose()

    async def read() -> list[Any]:
        engine = create_async_engine(url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                return await _rows(connection)
        finally:
            await engine.dispose()

    asyncio.run(seed())
    _run_alembic_ok(url, "upgrade", "head")
    rows = asyncio.run(read())

    assert len(rows) == 5
    for row in rows:
        assert row.trade_capable is True, row.exchange
        assert row.trade_capability_source == "UNRECORDED", row.exchange
        assert row.withdraw_check == "UNRECORDED", row.exchange
        assert row.trade_confirmed_at is None
        assert row.withdraw_confirmed_at is None
        assert row.validated_at is None
        assert row.internal_transfer is None


# --------------------------------------------------------------------------
# The six constraints, each refusing its bad state BY NAME
# --------------------------------------------------------------------------

_BAD_STATES: list[tuple[str, dict[str, Any], dict[str, Any], str]] = [
    # (case id, base row, overrides, the constraint that must refuse it)
    ("1-trade-source-unknown", _VALID_BYBIT, {"trade_capability_source": "BOGUS"}, _SOURCES_KNOWN),
    ("1-withdraw-source-unknown", _VALID_BYBIT, {"withdraw_check": "BOGUS"}, _SOURCES_KNOWN),
    (
        "2-trade-confirmation-without-timestamp",
        _VALID_BINANCE,
        {"trade_confirmed_at": None},
        _CONFIRMATION_HAS_TIMESTAMP,
    ),
    (
        "2-trade-timestamp-without-confirmation",
        _VALID_BYBIT,
        {"trade_confirmed_at": _NOW},
        _CONFIRMATION_HAS_TIMESTAMP,
    ),
    (
        "2-withdraw-confirmation-without-timestamp",
        _VALID_BINANCE,
        {"withdraw_confirmed_at": None},
        _CONFIRMATION_HAS_TIMESTAMP,
    ),
    (
        "2-withdraw-timestamp-without-confirmation",
        _VALID_BYBIT,
        {"withdraw_confirmed_at": _NOW},
        _CONFIRMATION_HAS_TIMESTAMP,
    ),
    (
        "3-owner-confirmed-incapability",
        _VALID_BINANCE,
        {"trade_capable": False},
        _CONFIRMED_TRADE_IS_CAPABLE,
    ),
    (
        "4-trade-legacy-withdraw-recorded",
        _VALID_BYBIT,
        {"trade_capability_source": "UNRECORDED"},
        _RECORDED_OR_LEGACY,
    ),
    (
        "4-withdraw-legacy-trade-recorded",
        _VALID_BYBIT,
        {"withdraw_check": "UNRECORDED"},
        _RECORDED_OR_LEGACY,
    ),
    ("4-recorded-without-validated-at", _VALID_BYBIT, {"validated_at": None}, _RECORDED_OR_LEGACY),
    ("4-legacy-with-validated-at", _LEGACY, {"validated_at": _NOW}, _RECORDED_OR_LEGACY),
    (
        "5-binance-trade-verified",
        _VALID_BINANCE,
        {"trade_capability_source": "VERIFIED", "trade_confirmed_at": None},
        _BINANCE_NOT_VERIFIED,
    ),
    (
        "5-binance-withdraw-verified",
        _VALID_BINANCE,
        {"withdraw_check": "VERIFIED", "withdraw_confirmed_at": None},
        _BINANCE_NOT_VERIFIED,
    ),
    (
        "6-bybit-trade-owner-confirmed",
        _VALID_BYBIT,
        {"trade_capability_source": "OWNER_CONFIRMED", "trade_confirmed_at": _NOW},
        _BYBIT_NOT_OWNER_CONFIRMED,
    ),
    (
        "6-bybit-withdraw-owner-confirmed",
        _VALID_BYBIT,
        {"withdraw_check": "OWNER_CONFIRMED", "withdraw_confirmed_at": _NOW},
        _BYBIT_NOT_OWNER_CONFIRMED,
    ),
]


@pytest.mark.parametrize(
    ("base", "overrides", "constraint"),
    [pytest.param(b, o, c, id=case) for case, b, o, c in _BAD_STATES],
)
async def test_each_bad_state_is_refused_by_exactly_its_own_named_constraint(
    conn: AsyncConnection, base: dict[str, Any], overrides: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError) as raised:
        await _insert(conn, base, **overrides)

    assert _constraint_name(raised.value) == constraint
    await conn.rollback()


async def test_owner_confirmed_requires_its_timestamp_and_the_timestamp_requires_owner_confirmed_both_columns(  # noqa: E501
    conn: AsyncConnection,
) -> None:
    """Constraint 2 covers BOTH columns and BOTH directions: four bad states."""
    cases = [c for c in _BAD_STATES if c[0].startswith("2-")]
    assert len(cases) == 4
    for case, base, overrides, constraint in cases:
        with pytest.raises(IntegrityError) as raised:
            await _insert(conn, base, **overrides)
        assert _constraint_name(raised.value) == constraint, case
        await conn.rollback()


async def test_owner_confirmed_trade_source_requires_trade_capable_true(
    conn: AsyncConnection,
) -> None:
    with pytest.raises(IntegrityError) as raised:
        await _insert(conn, _VALID_BINANCE, trade_capable=False)
    assert _constraint_name(raised.value) == _CONFIRMED_TRADE_IS_CAPABLE
    await conn.rollback()

    # A VERIFIED read-only key is fine: the venue said so (decision 18).
    await _insert(conn, _VALID_BYBIT, trade_capable=False)
    await conn.rollback()


async def test_validated_at_is_null_exactly_when_unrecorded(conn: AsyncConnection) -> None:
    for base, overrides in (
        (_VALID_BYBIT, {"validated_at": None}),  # recorded, but never validated
        (_LEGACY, {"validated_at": _NOW}),  # legacy, yet validated
    ):
        with pytest.raises(IntegrityError) as raised:
            await _insert(conn, base, **overrides)
        assert _constraint_name(raised.value) == _RECORDED_OR_LEGACY
        await conn.rollback()


async def test_binance_row_cannot_be_verified_check_refuses(conn: AsyncConnection) -> None:
    for column, timestamp in (
        ("trade_capability_source", "trade_confirmed_at"),
        ("withdraw_check", "withdraw_confirmed_at"),
    ):
        with pytest.raises(IntegrityError) as raised:
            await _insert(conn, _VALID_BINANCE, **{column: "VERIFIED", timestamp: None})
        assert _constraint_name(raised.value) == _BINANCE_NOT_VERIFIED
        await conn.rollback()


async def test_bybit_row_cannot_be_owner_confirmed_check_refuses(conn: AsyncConnection) -> None:
    for column, timestamp in (
        ("trade_capability_source", "trade_confirmed_at"),
        ("withdraw_check", "withdraw_confirmed_at"),
    ):
        with pytest.raises(IntegrityError) as raised:
            await _insert(conn, _VALID_BYBIT, **{column: "OWNER_CONFIRMED", timestamp: _NOW})
        assert _constraint_name(raised.value) == _BYBIT_NOT_OWNER_CONFIRMED
        await conn.rollback()


# --------------------------------------------------------------------------
# The downgrade
# --------------------------------------------------------------------------


def _run_sql(url: str, statements: Callable[[AsyncConnection], Any]) -> Any:
    """Runs ``statements`` on its own connection and returns what it returns."""

    async def go() -> Any:
        engine = create_async_engine(url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                result = await statements(connection)
                await connection.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _scalar(url: str, sql: str) -> Any:
    async def read(connection: AsyncConnection) -> Any:
        return (await connection.execute(text(sql))).scalar_one()

    return _run_sql(url, read)


async def _new_column_count(conn: AsyncConnection) -> int:
    return (
        await conn.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'exchange_credentials' AND column_name = ANY(:names)"
            ),
            {"names": _NEW_COLUMNS},
        )
    ).scalar_one()


def test_downgrade_succeeds_on_a_pure_backfill_shape(
    throwaway_db_factory: Callable[[str, str], str],
) -> None:
    url = throwaway_db_factory("clean", "0026")

    async def seed(connection: AsyncConnection) -> None:
        await _insert_legacy(connection, exchange="binance", is_active=True, last4="wxyz")
        await _insert_legacy(connection, exchange="bybit", is_active=True, last4="abcd")

    _run_sql(url, seed)
    _run_alembic_ok(url, "upgrade", "head")
    columns_before = _run_sql(url, _new_column_count)
    assert columns_before == len(_NEW_COLUMNS)

    result = _run_alembic(url, "downgrade", "0026")

    assert result.returncode == 0, result.stdout + result.stderr
    columns_after = _run_sql(url, _new_column_count)
    rows_kept = _scalar(url, "SELECT count(*) FROM exchange_credentials")
    assert columns_after == 0
    assert rows_kept == 2, "the rows themselves are kept"


def test_downgrade_refuses_while_any_row_is_not_the_backfill_shape_naming_each_count(
    throwaway_db_factory: Callable[[str, str], str],
) -> None:
    url = throwaway_db_factory("recorded", "head")

    async def seed(connection: AsyncConnection) -> None:
        # A VERIFIED read-only Bybit key with a recorded internal_transfer.
        await _insert(connection, _VALID_BYBIT, trade_capable=False, internal_transfer=True)
        # An owner-confirmed Binance key.
        await _insert(connection, _VALID_BINANCE)
        # And a legacy row, which alone would not block.
        await _insert(connection, _LEGACY)

    _run_sql(url, seed)
    version_before = _scalar(url, "SELECT version_num FROM alembic_version")

    refused = _run_alembic(url, "downgrade", "0026")

    assert refused.returncode != 0
    output = refused.stdout + refused.stderr
    assert "Refusing to downgrade 0027_credential_snapshot" in output
    assert "1 row(s) with trade_capable = false" in output
    assert "2 row(s) whose trade_capability_source is not UNRECORDED" in output
    assert "2 row(s) whose withdraw_check is not UNRECORDED" in output
    assert "1 row(s) with a recorded internal_transfer" in output
    assert "no force flag" in output
    # Nothing was dropped and the revision did not move.
    columns_left = _run_sql(url, _new_column_count)
    version = _scalar(url, "SELECT version_num FROM alembic_version")
    assert columns_left == len(_NEW_COLUMNS)
    assert version == version_before
    # A refused downgrade leaves the constraints in place too.
    constraint_count = _scalar(
        url,
        "SELECT count(*) FROM pg_constraint "
        "WHERE conrelid = 'exchange_credentials'::regclass "
        "AND conname LIKE 'ck_exchange_credentials_%'",
    )
    assert constraint_count == 7, "the six new checks and the 0010 last4 check"


def test_downgrade_refuses_for_a_recorded_internal_transfer_alone(
    throwaway_db_factory: Callable[[str, str], str],
) -> None:
    """``internal_transfer`` is the one recorded fact no CHECK ties to a source,
    so a row can be legacy in every other respect and still hold it. Dropping
    the column would discard it."""
    url = throwaway_db_factory("transfer", "head")

    async def seed(connection: AsyncConnection) -> None:
        await _insert(connection, _LEGACY, internal_transfer=True)

    _run_sql(url, seed)

    refused = _run_alembic(url, "downgrade", "0026")

    assert refused.returncode != 0
    output = refused.stdout + refused.stderr
    assert "1 row(s) with a recorded internal_transfer" in output
    assert "0 row(s) with trade_capable = false" in output
    assert "0 row(s) whose trade_capability_source is not UNRECORDED" in output
