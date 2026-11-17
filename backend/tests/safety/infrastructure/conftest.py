"""Fixtures for the safety-events integration tests: the database the signals tests use
(it already seeds the owner, a pool and the cascade-truncated tables), plus the
``safety_events`` model, so ``create_all`` builds its table."""

from strategy_manager.safety.infrastructure.models import SafetyEventRow  # noqa: F401
from tests.signals.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
