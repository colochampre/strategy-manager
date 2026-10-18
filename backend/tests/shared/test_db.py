"""The engine must not carry bound parameters into an error's text.

``alert_log_bridge`` formats ``exc_info`` into Telegram messages for any
root-logger ERROR, so a ``DBAPIError`` that prints its parameters would ship a
ciphertext, a wrapped DEK or a nonce off the machine (follow-up 8f.1).
"""

import re
from pathlib import Path

import sqlalchemy.exc as sa_exc
from sqlalchemy.pool import NullPool

from strategy_manager.shared.db import create_engine_for

_BOUND_VALUE = "ciphertext-bytes-that-must-not-leak"

_BACKEND = Path(__file__).resolve().parents[2]
_ENGINE_FACTORIES = re.compile(r"\b(create_async_engine|async_engine_from_config|create_engine)\(")


def test_a_database_error_does_not_print_its_bound_parameters() -> None:
    engine = create_engine_for("postgresql+asyncpg://user:pw@127.0.0.1:1/none")

    # The same constructor SQLAlchemy's execution path calls when a driver
    # raises; it takes the engine's own setting, so no network is needed.
    error = sa_exc.DBAPIError.instance(
        "INSERT INTO exchange_credentials (ciphertext) VALUES ($1)",
        (_BOUND_VALUE,),
        Exception("driver failure"),
        Exception,
        hide_parameters=engine.sync_engine.hide_parameters,
    )

    assert _BOUND_VALUE not in str(error)


def test_every_engine_outside_the_tests_is_built_by_create_engine_for() -> None:
    """The application, the migrations and the scripts (follow-up p17f.1: a
    failed data migration printed its bound values to the owner's terminal)."""
    builders = [
        f"{path.relative_to(_BACKEND).as_posix()}:{number}"
        for root in ("src", "migrations", "scripts")
        for path in sorted((_BACKEND / root).rglob("*.py"))
        if path.name != "db.py" or path.parent.name != "shared"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _ENGINE_FACTORIES.search(line)
    ]

    assert builders == []


def test_the_migrations_engine_holds_no_pool_and_hides_its_parameters() -> None:
    engine = create_engine_for("postgresql+asyncpg://user:pw@127.0.0.1:1/none", poolclass=NullPool)

    assert isinstance(engine.sync_engine.pool, NullPool)
    assert engine.sync_engine.hide_parameters is True
