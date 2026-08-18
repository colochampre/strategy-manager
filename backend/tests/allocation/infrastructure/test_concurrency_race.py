"""**[HIGHEST VALUE]** Concurrency race test: 8 concurrent 200-unit requests
against a 1000-balance pool, parametrized over 30 iterations. Asserts
committed reservations never exceed 1000, every result resolves to
FULL/PARTIAL/SKIP, and there is no phantom grant (spec: capital-allocation
§ Concurrency Safety Invariant; design.md's Concurrency test design;
tasks.md 4.12, 4.13).
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.decision import DecisionOutcome
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from tests.allocation.infrastructure._concurrency_harness import (
    CONCURRENCY,
    POOL_BALANCE,
    run_concurrent_allocations,
    sum_active_reservations,
)
from tests.allocation.infrastructure.conftest import seed_signal, seed_strategy

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("iteration", range(30))
async def test_concurrent_allocations_never_exceed_pool_balance(
    pg_session_factory: async_sessionmaker[AsyncSession], iteration: int
) -> None:
    strategy_id = uuid4()
    signal_ids = [uuid4() for _ in range(CONCURRENCY)]
    await seed_strategy(pg_session_factory, strategy_id=strategy_id, fill_mode="PARTIAL")
    for i, signal_id in enumerate(signal_ids):
        await seed_signal(
            pg_session_factory,
            signal_id=signal_id,
            strategy_id=strategy_id,
            idempotency_key=f"k{i}",
        )

    results = await run_concurrent_allocations(
        pg_session_factory,
        strategy_id=strategy_id,
        signal_ids=signal_ids,
        lock_factory=PgAdvisoryLockAdapter,
    )

    committed = await sum_active_reservations(pg_session_factory)

    assert committed <= POOL_BALANCE  # THE invariant
    assert len(results) == CONCURRENCY  # every request accounted for
    assert all(
        r.outcome in {DecisionOutcome.FULL, DecisionOutcome.PARTIAL, DecisionOutcome.SKIP}
        for r in results
    )
    granted_total = sum((r.granted for r in results), Decimal("0"))
    assert granted_total == committed  # no phantom grants
