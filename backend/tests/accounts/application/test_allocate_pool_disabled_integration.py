"""W1 of the independent verification of PR 8b-2, against real PostgreSQL: an
allocation that waited for the pool lock while ``DeleteCredential`` disabled the
pool must skip with ``POOL_DISABLED`` and reserve nothing.

``UpdateStrategy`` (the PATCH that sets ``enabled``) takes only the strategy row
lock, never the pool lock. So a strategy can be enabled and committed WHILE a
delete holds the pool lock, after the delete already read an empty exposure. A
signal for that strategy then passes every pre-lock check (its key is not yet
deactivated), queues on the pool lock, and -- without the in-lock pool re-read --
resumes after the delete's commit and reserves capital on a keyless exchange.

**Deterministic.** Each "the allocation waits" assertion is ``not task.done()``
plus a poll of ``pg_locks`` for a NOT-granted advisory lock on THIS pool's exact
key (classid/objid are the two ``hashtext`` halves ``LockKey`` produces), so an
unrelated waiter cannot satisfy it. Nothing relies on ``sleep`` as a barrier.
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.delete_credential import DeleteCredential
from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.infrastructure.capital_pool_writer import (
    SqlAlchemyCapitalPoolWriter,
)
from strategy_manager.accounts.infrastructure.credential_revoker import (
    SqlAlchemyCredentialRevoker,
)
from strategy_manager.accounts.infrastructure.pool_exposure_adapter import PoolExposureAdapter
from strategy_manager.accounts.infrastructure.pool_status_adapter import SqlAlchemyPoolStatus
from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocationResult,
)
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.accounts.application.test_delete_credential_integration import (
    _POOL_CONFIG,
    WAIT_SECONDS,
    FixedClock,
    _allocate_command,
    _balance_source,
    _credential_flags,
    _pool_enabled,
    _reservation_count,
    _store_key,
    _strategy,
    _until,
)
from tests.accounts.pool_seed import POOL, seed_signal, set_strategy_enabled
from tests.allocation.fakes import RecordingSkipRecorder
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def factory(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> async_sessionmaker[AsyncSession]:
    """The test database with no credential rows left by another test."""
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE exchange_credentials CASCADE"))
        await session.commit()
    return pg_session_factory


_POOL_KEY = LockKey.from_pool_key(
    PoolKey(
        exchange=Exchange(POOL[0]),
        venue=Venue(POOL[1]),
        settlement_currency=Currency(POOL[2]),
    )
)


async def _waiting_on_this_pools_lock(factory: async_sessionmaker[AsyncSession]) -> bool:
    """A NOT-granted advisory lock whose two key halves are this pool's own."""
    async with factory() as session:
        return bool(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM pg_locks "
                        "WHERE locktype = 'advisory' AND NOT granted "
                        "AND classid::bigint = (hashtext(:first)::bigint & 4294967295) "
                        "AND objid::bigint = (hashtext(:second)::bigint & 4294967295)"
                    ),
                    {"first": _POOL_KEY.first, "second": _POOL_KEY.second},
                )
            ).scalar_one()
        )


async def _allocation_is_queued_on_the_pool_lock(
    factory: async_sessionmaker[AsyncSession], task: asyncio.Task[Any]
) -> None:
    async def queued() -> bool:
        return await _waiting_on_this_pools_lock(factory)

    await _until(queued, "the allocation to wait on this pool's advisory lock")
    assert not task.done(), (
        "AllocateCapital completed without waiting for the held pool lock: the harness "
        "is not proving the interleaving"
    )


class _Allocation:
    """One ``AllocateCapital`` run on its own session, started as a task."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        strategy_id: UUID,
        signal_id: UUID,
    ) -> None:
        self.recorder = RecordingSkipRecorder()
        self.signal_id = signal_id
        self._factory = factory
        self._strategy_id = strategy_id
        self.result: AllocationResult | None = None
        self.task: asyncio.Task[None] = asyncio.create_task(self._run())

    async def _run(self) -> None:
        async with self._factory() as session:
            use_case = AllocateCapital(
                strategy_policy=StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
                pool_balance=PoolBalanceAdapter(_POOL_CONFIG, _balance_source()),
                lock=PgAdvisoryLockAdapter(session),
                reservations=SqlAlchemyReservationRepository(session),
                commit=session,
                clock=FixedClock(),  # type: ignore[arg-type]
                reservation_ttl_seconds=30,
                skip_recorder=self.recorder,
                pool_status=SqlAlchemyPoolStatus(session),
            )
            self.result = await use_case.allocate(
                _allocate_command(self.signal_id, self._strategy_id)
            )


async def _seed(factory: async_sessionmaker[AsyncSession]) -> tuple[UUID, UUID]:
    """An ENABLED strategy (committed) with a signal, on a pool with a live key."""
    await _store_key(factory)
    strategy_id = await _strategy(factory, enabled=True)
    signal_id = uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    return strategy_id, signal_id


async def test_allocation_that_waited_while_the_pool_was_disabled_skips_pool_disabled_and_reserves_nothing(  # noqa: E501
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """Actor A mimics ``DeleteCredential``: it holds the pool advisory lock in an
    open transaction and, inside it, disables the pool and deactivates the key. The
    strategy is ENABLED in committed state. The allocation must genuinely queue on
    this pool's lock, and once A commits it must skip -- not reserve."""
    strategy_id, signal_id = await _seed(factory)

    async with factory() as held:
        await PoolLockAdapter(held).acquire(*POOL)
        await held.execute(
            text("UPDATE capital_pools SET enabled = false WHERE exchange = :e"),
            {"e": POOL[0]},
        )
        await SqlAlchemyCredentialRevoker(held, FixedClock()).deactivate(POOL[0])

        allocation = _Allocation(factory, strategy_id, signal_id)
        await _allocation_is_queued_on_the_pool_lock(factory, allocation.task)
        assert allocation.result is None

        await held.commit()  # releases the pool lock; the allocation resumes

    await asyncio.wait_for(allocation.task, WAIT_SECONDS)

    result = allocation.result
    assert result is not None
    assert result.outcome.value == "SKIP"
    assert result.skip_reason == "POOL_DISABLED"
    assert result.reservation_id is None
    assert await _reservation_count(factory, strategy_id) == 0
    assert [(call[0], call[1]) for call in allocation.recorder.calls] == [
        (signal_id, "POOL_DISABLED")
    ]
    assert await _pool_enabled(factory) is False


async def test_the_same_holder_without_disabling_the_pool_lets_the_allocation_reserve(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """Control for the test above: identical harness, but A commits WITHOUT
    disabling the pool. The allocation queues the same way and then reserves, so the
    skip above is caused by the pool flag and by nothing else in the harness."""
    strategy_id, signal_id = await _seed(factory)

    async with factory() as held:
        await PoolLockAdapter(held).acquire(*POOL)
        allocation = _Allocation(factory, strategy_id, signal_id)
        await _allocation_is_queued_on_the_pool_lock(factory, allocation.task)
        await held.commit()

    await asyncio.wait_for(allocation.task, WAIT_SECONDS)

    assert allocation.result is not None
    assert allocation.result.reservation_id is not None
    assert allocation.result.skip_reason is None
    assert await _reservation_count(factory, strategy_id) == 1
    assert allocation.recorder.calls == []


async def test_w1_interleaving_with_the_real_delete_credential_enabling_a_strategy_under_the_delete_lock(  # noqa: E501
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """The exact W1 sequence, with the REAL ``DeleteCredential``:

    1. the delete takes the pool lock and reads an empty exposure (the strategy is
       disabled); it then pauses, inside the lock, right before it disables the pool
       (its key is already deactivated in its open transaction);
    2. the owner enables the strategy and that commits -- ``UpdateStrategy`` never
       takes the pool lock, so nothing stops it;
    3. a signal for that strategy passes its pre-lock checks and queues on the pool
       lock;
    4. the delete resumes and commits.

    The allocation then sees an enabled strategy and a disabled pool. It must skip
    with ``POOL_DISABLED`` and reserve nothing."""
    await _store_key(factory)
    strategy_id = await _strategy(factory, enabled=False)
    signal_id = uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )

    exposure_read = asyncio.Event()
    resume_delete = asyncio.Event()
    deleted: dict[str, Any] = {}

    class _PausingPools:
        """Wraps the real writer; pauses once the exposure was read and the key
        deactivated, before the pool flips."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner

        async def enable(self, exchange: str) -> bool:
            raise AssertionError

        async def disable(self, exchange: str) -> bool:
            exposure_read.set()
            await resume_delete.wait()
            return bool(await self._inner.disable(exchange))

    async def run_delete() -> None:
        async with factory() as session:
            deleted["value"] = await DeleteCredential(
                SqlAlchemyCredentialRevoker(session, FixedClock()),
                PoolLockAdapter(session),
                PoolExposureAdapter.over(session),
                _PausingPools(SqlAlchemyCapitalPoolWriter(session)),
                session,
            ).execute("bybit")

    task_delete = asyncio.create_task(run_delete())
    await asyncio.wait_for(exposure_read.wait(), WAIT_SECONDS)
    assert not task_delete.done()

    await set_strategy_enabled(factory, strategy_id, True)  # step 2: commits under the lock

    allocation = _Allocation(factory, strategy_id, signal_id)
    await _allocation_is_queued_on_the_pool_lock(factory, allocation.task)
    assert not task_delete.done()

    resume_delete.set()
    await asyncio.wait_for(asyncio.gather(task_delete, allocation.task), WAIT_SECONDS)

    assert deleted["value"].pool_disabled is True
    result = allocation.result
    assert result is not None
    assert result.skip_reason == "POOL_DISABLED"
    assert result.reservation_id is None
    assert await _reservation_count(factory, strategy_id) == 0
    assert await _credential_flags(factory) == [False]
    assert await _pool_enabled(factory) is False
    assert [(call[0], call[1]) for call in allocation.recorder.calls] == [
        (signal_id, "POOL_DISABLED")
    ]
