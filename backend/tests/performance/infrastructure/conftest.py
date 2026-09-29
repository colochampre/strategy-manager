"""Real-PostgreSQL fixtures for the fills-source tests. They are the ledger
tests' own (``strategies``, ``signals``, ``reservations``,
``execution_attempts`` and ``ledger_entries`` from ``create_all``, plus the
seeded pools), re-exported rather than copied so the two cannot drift.
"""

from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)
