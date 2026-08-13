"""Integration test: main.py's lifespan wires CapitalPoolRepository +
assert_pool_lock_keys_distinct together at startup (tasks.md 3.15 — invariant
1). Placed here because it needs the seeded-pools ``pg_engine`` fixture.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from strategy_manager import main

pytestmark = pytest.mark.integration


async def test_lifespan_passes_against_real_seeded_pools(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "engine", pg_engine)

    async with main.lifespan(main.app):
        pass  # no exception raised means the invariant passed
