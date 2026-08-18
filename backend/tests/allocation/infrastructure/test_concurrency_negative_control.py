"""**[HIGHEST VALUE]** Negative control: the same concurrency scenario against
a ``NoOpAdvisoryLock`` stub, for up to 50 iterations. Proves the positive race
test (tasks.md 4.12) is not passing vacuously — the lock is what enforces the
invariant, and this test must actually observe an over-allocation breach on
this codebase today (spec: capital-allocation § Concurrency Safety Invariant,
negative-control scenario; tasks.md 4.14, 4.15).
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.lock_key import LockKey
from tests.allocation.infrastructure._concurrency_harness import (
    CONCURRENCY,
    POOL_BALANCE,
    reset_reservations,
    run_concurrent_allocations,
    sum_active_reservations,
)
from tests.allocation.infrastructure.conftest import seed_signal, seed_strategy

pytestmark = pytest.mark.integration


class NoOpAdvisoryLock:
    """Stubs ``AdvisoryLockPort``: the lock is gone. Every concurrent request
    reads the same stale ``reserved_active`` and decides independently, which
    is exactly the race the real lock exists to prevent."""

    def __init__(self, session: AsyncSession) -> None:
        del session  # unused: this stub deliberately never touches the DB lock

    async def acquire(self, key: LockKey) -> None:
        return None


async def test_invariant_breaks_without_the_advisory_lock(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Proves the positive test is not passing vacuously."""

    for _ in range(50):
        await reset_reservations(pg_session_factory)
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

        await run_concurrent_allocations(
            pg_session_factory,
            strategy_id=strategy_id,
            signal_ids=signal_ids,
            lock_factory=NoOpAdvisoryLock,
        )

        committed = await sum_active_reservations(pg_session_factory)
        if committed > POOL_BALANCE:
            return  # breach observed: the lock is load-bearing

    pytest.fail(
        "50 lock-free iterations never over-allocated: the race is not being "
        "exercised, so the positive test proves nothing."
    )
