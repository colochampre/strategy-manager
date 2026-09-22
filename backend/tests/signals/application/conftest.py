"""Fixtures for ``signals/application`` integration tests: reuses the
``signals/infrastructure`` suite's real-PostgreSQL setup rather than
duplicating it, since it already creates every table this unit's timing
test needs (``strategies``, ``signals``, ``reservations``,
``execution_attempts``, ``jobs``) and seeds the one ``capital_pools`` row
these tests share.
"""

from tests.signals.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
