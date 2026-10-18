"""The engine must not carry bound parameters into an error's text.

``alert_log_bridge`` formats ``exc_info`` into Telegram messages for any
root-logger ERROR, so a ``DBAPIError`` that prints its parameters would ship a
ciphertext, a wrapped DEK or a nonce off the machine (follow-up 8f.1).
"""

import sqlalchemy.exc as sa_exc

from strategy_manager.shared.db import create_engine_for

_BOUND_VALUE = "ciphertext-bytes-that-must-not-leak"


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
