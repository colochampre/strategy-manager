"""Races of a suspension (PS.13): a plain subscriber's suspension against its own opening, and
ACCOUNT_CHANGED when a seat appears while the suspension holds its pool locks."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from strategy_manager.allocation.domain.decision import DecisionOutcome
from strategy_manager.identity.application.suspend_account import (
    SuspendAccount,
    SuspensionRefusal,
    SuspensionRefusedError,
)
from strategy_manager.identity.infrastructure.account_deletion import (
    SqlAlchemyAuthoredStrategies,
)
from strategy_manager.identity.infrastructure.user_repository import SqlAlchemyUserRepository
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from tests.allocation.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.identity.application.test_suspend_account_fence import (  # noqa: F401
    _BLOCKED_FOR,
    MARKET,
    WAIT_SECONDS,
    Factory,
    _allocate,
    _Held,
    _nobody_stays_suspended,
    _opening,
    _settle,
    _world,
)
from tests.owner import OWNER_ID, ensure_pool, seed_other_user
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration


async def _suspend(factory: Factory, user_id: UUID, author: UUID, lock: object = None) -> None:
    async with factory() as session:
        await SuspendAccount(
            SqlAlchemyUserRepository(session),
            SqlAlchemyAuthoredStrategies(session, author),
            lock or PoolLockAdapter(session),  # type: ignore[arg-type]
            session,
        ).execute(admin_id=uuid4(), user_id=user_id, suspended=True, now=datetime.now(UTC))


async def _suspended(factory: Factory, user_id: UUID) -> bool:
    async with factory() as session:
        return (
            await session.execute(
                text("SELECT suspended_at IS NOT NULL FROM users WHERE id = :id"), {"id": user_id}
            )
        ).scalar_one()


async def _reservations(factory: Factory, user_id: UUID) -> int:
    async with factory() as session:
        return (
            await session.execute(
                text("SELECT count(*) FROM reservations WHERE user_id = :id"), {"id": user_id}
            )
        ).scalar_one()


async def test_a_subscribers_suspension_waits_for_its_opening_in_flight_then_the_next_is_refused(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    command = await _opening(pg_session_factory, world, world.other)
    held = _Held()
    opening = asyncio.create_task(_allocate(pg_session_factory, world, command, held=held))
    await asyncio.wait_for(held.reached.wait(), WAIT_SECONDS)
    suspension = asyncio.create_task(_suspend(pg_session_factory, world.other, world.other))
    try:
        await asyncio.wait({suspension}, timeout=_BLOCKED_FOR * 2)
        assert not suspension.done(), "suspension landed while the opening held the row FOR SHARE"
        held.released.set()
        first = await asyncio.wait_for(opening, WAIT_SECONDS)
        await asyncio.wait_for(suspension, WAIT_SECONDS)
    finally:
        held.released.set()
        await _settle(opening, suspension)
    assert first.outcome is DecisionOutcome.FULL
    assert await _suspended(pg_session_factory, world.other)
    before = await _reservations(pg_session_factory, world.other)

    opening = await _opening(pg_session_factory, world, world.other)
    second = await _allocate(pg_session_factory, world, opening)
    assert second.skip_reason == "ACCOUNT_SUSPENDED"
    assert second.reservation_id is None
    assert await _reservations(pg_session_factory, world.other) == before
    # The author is not suspended: the author's own opening still reserves.
    own = await _opening(pg_session_factory, world, OWNER_ID)
    third = await _allocate(pg_session_factory, world, own)
    assert third.outcome is DecisionOutcome.FULL


class _PauseOnFirstAcquire:
    def __init__(self, inner: PoolLockAdapter, held: _Held) -> None:
        self._inner = inner
        self._held = held
        self._paused = False

    async def acquire(self, user_id: UUID, exchange: str, venue: str, currency: str) -> None:
        await self._inner.acquire(user_id, exchange, venue, currency)
        if not self._paused:
            self._paused = True
            self._held.reached.set()
            await self._held.released.wait()


async def test_a_seat_added_while_the_suspension_holds_its_pools_refuses_it_account_changed(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    held = _Held()

    async def run() -> None:
        async with pg_session_factory() as session:
            await SuspendAccount(
                SqlAlchemyUserRepository(session),
                SqlAlchemyAuthoredStrategies(session, OWNER_ID),
                _PauseOnFirstAcquire(PoolLockAdapter(session), held),
                session,
            ).execute(admin_id=uuid4(), user_id=OWNER_ID, suspended=True, now=datetime.now(UTC))

    suspension = asyncio.create_task(run())
    try:
        await asyncio.wait_for(held.reached.wait(), WAIT_SECONDS)
        async with pg_session_factory() as session:
            third = await seed_other_user(session)
            pool = await ensure_pool(session, MARKET, user_id=third)
            await session.commit()
        await seeds.subscription(pg_session_factory, third, world.strategy_id, pool)
        held.released.set()
        with pytest.raises(SuspensionRefusedError) as refused:
            await asyncio.wait_for(suspension, WAIT_SECONDS)
    finally:
        held.released.set()
        await _settle(suspension)
    assert refused.value.refusal is SuspensionRefusal.ACCOUNT_CHANGED
    assert not await _suspended(pg_session_factory, OWNER_ID)
    # Trying again reads the larger set and lands.
    await _suspend(pg_session_factory, OWNER_ID, OWNER_ID)
    assert await _suspended(pg_session_factory, OWNER_ID)
