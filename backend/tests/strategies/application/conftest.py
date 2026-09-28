"""Fixtures for ``strategies/application`` integration tests: reuses the
``strategies/infrastructure`` suite's real-PostgreSQL setup rather than
duplicating it (mirrors ``tests/signals/application/conftest.py``'s own
precedent), since it already creates every table ``ArchiveStrategy``'s own
exposure check needs (``strategies``, ``capital_pools``, ``reservations``,
``execution_attempts``, ``ledger_entries``) once this suite's own imports
register those ORM models on ``Base.metadata``.
"""

from tests.strategies.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
