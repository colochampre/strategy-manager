"""Suspending an account against the openings of its strategies' subscribers, on real
PostgreSQL (public-site LS9, PS.13 S4; the template is
``tests/strategies/application/test_subscriber_locks_concurrency.py``).

``SuspendAccount`` takes the advisory lock of every subscriber's pool BEFORE the author's
user row, the order ``SubscriberLocks`` and ``DeleteAccount`` use, so:

- an opening in flight in a subscriber's pool makes the suspension wait, and the opening
  went first: it reserves;
- an opening after the suspension reads it in the lock (the policy's ``author_suspended``)
  and reserves nothing;
- an opening that reaches the lock while the suspension holds it waits, then reads it;
- the author's own opening, which holds its pool lock and then asks for its own user row
  ``FOR SHARE``, is not caught in a deadlock by a suspension that took the row first.

The lock-hold harness: one actor is paused where its locks are held and the test asserts
the other is STILL BLOCKED, ``not task.done()``, after a real wait. Every task is awaited in
a ``finally`` so a red test leaves no lock held.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
    AllocationResult,
)
from strategy_manager.allocation.domain.decision import DecisionOutcome
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.allocation.infrastructure.user_mode import SqlAlchemyUserMode
from strategy_manager.identity.application.suspend_account import SuspendAccount
from strategy_manager.identity.infrastructure.account_deletion import (
    SqlAlchemyAuthoredStrategies,
)
from strategy_manager.identity.infrastructure.user_repository import SqlAlchemyUserRepository
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.application.author_standing_policy import AuthorStandingPolicy
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.author_standing import SqlAlchemyAuthorStanding
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.allocation.fakes import (
    ActiveSubscription,
    AlwaysEnabledPool,
    AnyKeyTrades,
    RecordingSkipRecorder,
)
from tests.allocation.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_signal,
    seed_strategy,
)
from tests.owner import (
    OWNER_ID,
    allocate_command,
    ensure_author_subscription,
    ensure_pool,
    seed_other_user,
)
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]
MARKET = ("pionex", "spot", "USDT")
WAIT_SECONDS = 5.0
_BLOCKED_FOR = 0.5


@pytest.fixture(autouse=True)
async def _nobody_stays_suspended(pg_session_factory: Factory) -> AsyncIterator[None]:  # noqa: F811
    """``users`` outlives a fixture's truncate: a suspension left behind would refuse
    the openings of the next test."""
    await _lift_everyone(pg_session_factory)
    yield
    await _lift_everyone(pg_session_factory)


async def _lift_everyone(factory: Factory) -> None:
    async with factory() as session:
        await session.execute(text("UPDATE users SET suspended_at = NULL"))
        await session.commit()


class _Held:
    """Holds a use case at its commit, with everything written and every lock still
    held, until the test releases it."""

    def __init__(self) -> None:
        self.reached = asyncio.Event()
        self.released = asyncio.Event()

    def on(self, session: AsyncSession) -> "_HeldCommit":
        return _HeldCommit(self, session)


class _HeldCommit:
    def __init__(self, held: _Held, session: AsyncSession) -> None:
        self._held = held
        self._session = session

    async def commit(self) -> None:
        self._held.reached.set()
        await self._held.released.wait()
        await self._session.commit()


class _PausedAfterAcquire:
    """The real pool lock, then a pause: the opening holds its pool lock and has not yet
    asked for its user row, the window in which a row-first suspension would deadlock it."""

    def __init__(self, inner: PgAdvisoryLockAdapter, held: _Held) -> None:
        self._inner = inner
        self._held = held

    async def acquire(self, key: LockKey) -> None:
        await self._inner.acquire(key)
        self._held.reached.set()
        await self._held.released.wait()


class _World:
    def __init__(
        self,
        strategy_id: UUID,
        other: UUID,
        pools: dict[tuple[UUID, tuple[str, str, str]], PoolConfig],
    ) -> None:
        self.strategy_id = strategy_id
        self.other = other
        self.pools = pools


async def _world(factory: Factory) -> _World:
    """A strategy of the owner's with the owner's own seat, and another user's seat in
    that user's own pool: two pools, two locks."""
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    async with factory() as session:
        other = await seed_other_user(session)
        other_pool = await ensure_pool(session, MARKET, user_id=other)
        await ensure_author_subscription(session, strategy_id)
        await session.commit()
    await seeds.subscription(factory, other, strategy_id, other_pool)
    pools = {
        (user, MARKET): PoolConfig(
            exchange=Exchange.PIONEX,
            venue=Venue.SPOT,
            settlement_currency=Currency.USDT,
            user_id=user,
            min_order_size=Decimal("10"),
        )
        for user in (OWNER_ID, other)
    }
    return _World(strategy_id, other, pools)


async def _opening(factory: Factory, world: _World, user: UUID) -> AllocateCommand:
    signal_id = uuid4()
    await seed_signal(
        factory,
        signal_id=signal_id,
        strategy_id=world.strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    return await allocate_command(
        factory,
        signal_id=signal_id,
        strategy_id=world.strategy_id,
        requested=Money(amount=Decimal("200"), currency=Currency.USDT),
        user_id=user,
        pre_checked_mode=Mode.SIMULATION,
    )


async def _allocate(
    factory: Factory,
    world: _World,
    command: AllocateCommand,
    *,
    held: _Held | None = None,
    paused_after_lock: _Held | None = None,
) -> AllocationResult:
    source = FakeBalanceSource()
    source.set_balance(*MARKET, Decimal("1000"))
    async with factory() as session:
        real_lock = PgAdvisoryLockAdapter(session)
        lock: PgAdvisoryLockAdapter | _PausedAfterAcquire = real_lock
        if paused_after_lock is not None:
            lock = _PausedAfterAcquire(real_lock, paused_after_lock)
        use_case = AllocateCapital(
            strategy_policy=AuthorStandingPolicy(
                StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
                SqlAlchemyAuthorStanding(session),
            ),
            pool_balance=PoolBalanceAdapter(world.pools, source),
            lock=lock,
            reservations=SqlAlchemyReservationRepository(session),
            commit=session if held is None else held.on(session),
            clock=SystemClock(),
            reservation_ttl_seconds=30,
            skip_recorder=RecordingSkipRecorder(),
            pool_status=AlwaysEnabledPool(),
            user_mode=SqlAlchemyUserMode(session, brake=False),
            trade_capability=AnyKeyTrades(),
            subscription_state=ActiveSubscription(),
        )
        return await use_case.allocate(command)


async def _suspend_owner(factory: Factory, *, held: _Held | None = None) -> None:
    async with factory() as session:
        await SuspendAccount(
            SqlAlchemyUserRepository(session),
            SqlAlchemyAuthoredStrategies(session, OWNER_ID),
            PoolLockAdapter(session),
            session if held is None else held.on(session),
        ).execute(
            admin_id=uuid4(), user_id=OWNER_ID, suspended=True, now=datetime.now(UTC)
        )


async def _is_suspended(factory: Factory) -> bool:
    async with factory() as session:
        return (
            await session.execute(
                text("SELECT suspended_at IS NOT NULL FROM users WHERE id = :id"),
                {"id": OWNER_ID},
            )
        ).scalar_one()


async def _until_waiting_on_an_advisory_lock(factory: Factory) -> None:
    deadline = asyncio.get_running_loop().time() + WAIT_SECONDS
    while True:
        async with factory() as session:
            waiting = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM pg_locks "
                        "WHERE locktype = 'advisory' AND NOT granted"
                    )
                )
            ).scalar_one()
        if waiting:
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("no backend ever waited on an advisory lock")
        await asyncio.sleep(0.02)


async def _settle(*tasks: asyncio.Task[object] | asyncio.Task[None]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_the_suspension_waits_for_a_subscribers_opening_in_flight_which_then_reserves(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    command = await _opening(pg_session_factory, world, world.other)
    held = _Held()

    opening = asyncio.create_task(_allocate(pg_session_factory, world, command, held=held))
    await asyncio.wait_for(held.reached.wait(), WAIT_SECONDS)
    suspension = asyncio.create_task(_suspend_owner(pg_session_factory))
    try:
        await _until_waiting_on_an_advisory_lock(pg_session_factory)
        done, _ = await asyncio.wait({suspension}, timeout=_BLOCKED_FOR)
        assert not suspension.done(), "the suspension finished while an opening held the pool"
        assert not done
        held.released.set()
        result = await asyncio.wait_for(opening, WAIT_SECONDS)
        await asyncio.wait_for(suspension, WAIT_SECONDS)
    finally:
        held.released.set()
        await _settle(opening, suspension)

    assert result.outcome is DecisionOutcome.FULL
    assert await _is_suspended(pg_session_factory)


async def test_an_opening_after_the_suspension_reads_it_in_the_lock_and_reserves_nothing(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    command = await _opening(pg_session_factory, world, world.other)
    await _suspend_owner(pg_session_factory)

    result = await _allocate(pg_session_factory, world, command)

    assert result.outcome is DecisionOutcome.SKIP
    assert result.skip_reason == "AUTHOR_SUSPENDED"
    assert result.reservation_id is None


async def test_an_opening_that_reaches_the_pool_while_the_suspension_holds_it_waits_then_skips(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    command = await _opening(pg_session_factory, world, world.other)
    held = _Held()

    suspension = asyncio.create_task(_suspend_owner(pg_session_factory, held=held))
    await asyncio.wait_for(held.reached.wait(), WAIT_SECONDS)
    opening = asyncio.create_task(_allocate(pg_session_factory, world, command))
    try:
        await _until_waiting_on_an_advisory_lock(pg_session_factory)
        await asyncio.wait({opening}, timeout=_BLOCKED_FOR)
        assert not opening.done(), "the opening finished while the suspension held its pool"
        held.released.set()
        await asyncio.wait_for(suspension, WAIT_SECONDS)
        result = await asyncio.wait_for(opening, WAIT_SECONDS)
    finally:
        held.released.set()
        await _settle(suspension, opening)

    assert result.skip_reason == "AUTHOR_SUSPENDED"
    assert result.reservation_id is None


async def test_the_authors_own_opening_is_not_deadlocked_by_the_suspension(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The opening holds the owner's pool lock and has not yet asked for the owner's user
    row ``FOR SHARE``. A suspension that took the row ``FOR UPDATE`` first would hold it
    while waiting for that pool, and the opening would wait for the row: a deadlock
    Postgres breaks by aborting one. Pool locks first means the suspension waits at the
    pool, holding no row, and the opening finishes."""
    world = await _world(pg_session_factory)
    command = await _opening(pg_session_factory, world, OWNER_ID)
    paused = _Held()

    opening = asyncio.create_task(
        _allocate(pg_session_factory, world, command, paused_after_lock=paused)
    )
    await asyncio.wait_for(paused.reached.wait(), WAIT_SECONDS)
    suspension = asyncio.create_task(_suspend_owner(pg_session_factory))
    try:
        await _until_waiting_on_an_advisory_lock(pg_session_factory)
        await asyncio.wait({suspension}, timeout=_BLOCKED_FOR)
        assert not suspension.done()
        paused.released.set()
        result = await asyncio.wait_for(opening, WAIT_SECONDS)
        await asyncio.wait_for(suspension, WAIT_SECONDS)
    finally:
        paused.released.set()
        await _settle(opening, suspension)

    assert result.outcome is DecisionOutcome.FULL
    assert await _is_suspended(pg_session_factory)
