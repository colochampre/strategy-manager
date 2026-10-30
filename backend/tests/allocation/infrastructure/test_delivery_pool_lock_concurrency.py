"""Each delivery of a signal is allocated under its OWN subscriber's pool lock
(multi-user tasks.md C.11, design AD5), proven on real PostgreSQL with the
lock-hold harness.

The holder is a real ``AllocateCapital`` run whose commit is paused, so the lock
it holds is the one the use case took for its delivery, not one the test took
by hand. A second delivery then either completes while the first is still
paused (another user's pool) or genuinely queues on the same pool's advisory
lock (``not task.done()`` plus a NOT-granted row in ``pg_locks`` for that
pool's exact key).
"""

import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.accounts.infrastructure.pool_status_adapter import SqlAlchemyPoolStatus
from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
    AllocationResult,
)
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.accounts.application.test_delete_credential_integration import FixedClock
from tests.accounts.pool_seed import POOL, seed_signal, seed_strategy
from tests.allocation.fakes import FixedUserMode, RecordingSkipRecorder
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.owner import (
    OWNER_ID,
    allocate_command,
    ensure_author_subscription,
    ensure_pool,
    seed_other_user,
)

pytestmark = pytest.mark.integration

WAIT_SECONDS = 5.0
REQUEST = Money(amount=Decimal("200"), currency=Currency.USDT)
_MARKET = PoolKey(
    exchange=Exchange(POOL[0]), venue=Venue(POOL[1]), settlement_currency=Currency(POOL[2])
)


class _PausedCommit:
    """The commit port of the holding allocation: it reports that the use case
    reached its commit, with the pool lock held, and commits only when released."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def commit(self) -> None:
        self.reached.set()
        await self.release.wait()
        await self._session.commit()


async def _allocate(
    factory: async_sessionmaker[AsyncSession],
    command: AllocateCommand,
    users: tuple[UUID, ...],
    paused: list[_PausedCommit] | None = None,
) -> AllocationResult:
    """One ``AllocateCapital`` run on its own session. With ``paused``, its commit
    is a ``_PausedCommit`` appended there for the test to release."""
    source = FakeBalanceSource()
    source.set_balance(*POOL, Decimal("1000"))
    pools = {
        (user, POOL): PoolConfig(
            exchange=_MARKET.exchange,
            venue=_MARKET.venue,
            settlement_currency=_MARKET.settlement_currency,
            user_id=user,
            min_order_size=Decimal("1"),
        )
        for user in users
    }
    async with factory() as session:
        commit: AsyncSession | _PausedCommit = session
        if paused is not None:
            commit = _PausedCommit(session)
            paused.append(commit)
        use_case = AllocateCapital(
            strategy_policy=StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
            pool_balance=PoolBalanceAdapter(pools, source),
            lock=PgAdvisoryLockAdapter(session),
            reservations=SqlAlchemyReservationRepository(session),
            commit=commit,
            clock=FixedClock(),
            reservation_ttl_seconds=30,
            skip_recorder=RecordingSkipRecorder(),
            pool_status=SqlAlchemyPoolStatus(session),
            user_mode=FixedUserMode(),
        )
        return await use_case.allocate(command)


async def _enabled_strategy(factory: async_sessionmaker[AsyncSession]) -> UUID:
    """An owner-authored enabled strategy with its author's ACTIVE subscription."""
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id, enabled=True)
    async with factory() as session:
        await ensure_author_subscription(session, strategy_id)
        await session.commit()
    return strategy_id


async def _signal(factory: async_sessionmaker[AsyncSession], strategy_id: UUID) -> UUID:
    signal_id = uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    return signal_id


async def _subscriber(factory: async_sessionmaker[AsyncSession], strategy_id: UUID) -> UUID:
    """A second user with an ACTIVE subscription to ``strategy_id`` in their own
    pool on the same market."""
    async with factory() as session:
        user_id = await seed_other_user(session)
        pool_id = await ensure_pool(session, POOL, user_id=user_id)
        await session.execute(
            text(
                "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, "
                "allocation_percent, status) "
                "VALUES (:id, :user_id, :strategy_id, :pool_id, 30, 'ACTIVE')"
            ),
            {"id": uuid4(), "user_id": user_id, "strategy_id": strategy_id, "pool_id": pool_id},
        )
        await session.commit()
    return user_id


async def _waiting_on_the_pool_lock_of(
    factory: async_sessionmaker[AsyncSession], user_id: UUID
) -> bool:
    """A NOT-granted advisory lock whose two key halves are ``user_id``'s pool's."""
    key = LockKey.from_pool_key(user_id, _MARKET)
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
                    {"first": key.first, "second": key.second},
                )
            ).scalar_one()
        )


async def _until_queued(factory: async_sessionmaker[AsyncSession], user_id: UUID) -> None:
    deadline = asyncio.get_running_loop().time() + WAIT_SECONDS
    while not await _waiting_on_the_pool_lock_of(factory, user_id):
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting for a delivery to queue on the pool lock")
        await asyncio.sleep(0.02)


async def _reservations_of(
    factory: async_sessionmaker[AsyncSession], signal_ids: tuple[UUID, ...]
) -> list[tuple[UUID, UUID]]:
    async with factory() as session:
        rows = await session.execute(
            text(
                "SELECT user_id, delivery_id FROM reservations "
                "WHERE signal_id = ANY(:signals) ORDER BY created_at"
            ),
            {"signals": list(signal_ids)},
        )
        return [(UUID(str(row[0])), UUID(str(row[1]))) for row in rows.all()]


async def _release(
    paused: list[_PausedCommit], task: "asyncio.Task[AllocationResult]"
) -> None:
    """Lets the holding allocation commit, and never leaves its task running."""
    if paused:
        paused[0].release.set()
        await asyncio.wait({task}, timeout=WAIT_SECONDS)
    if not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("holder_is_the_author", [True, False])
async def test_two_users_deliveries_of_one_signal_take_different_pool_locks(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
    holder_is_the_author: bool,
) -> None:
    """One signal, two deliveries: the author's and a subscriber's, each in its
    own user's pool on the same market. While one delivery's allocation holds
    its pool lock (paused at its commit), the other completes. Both orders are
    run, so neither waits for the other."""
    factory = pg_session_factory
    strategy_id = await _enabled_strategy(factory)
    subscriber = await _subscriber(factory, strategy_id)
    signal_id = await _signal(factory, strategy_id)
    users = (OWNER_ID, subscriber)
    holder, other = users if holder_is_the_author else (subscriber, OWNER_ID)
    holding = await allocate_command(
        factory, signal_id=signal_id, strategy_id=strategy_id, requested=REQUEST, user_id=holder
    )
    second = await allocate_command(
        factory, signal_id=signal_id, strategy_id=strategy_id, requested=REQUEST, user_id=other
    )

    paused: list[_PausedCommit] = []
    first_task = asyncio.create_task(_allocate(factory, holding, users, paused))
    try:
        await asyncio.wait_for(_reached(paused), WAIT_SECONDS)

        second_result = await asyncio.wait_for(_allocate(factory, second, users), WAIT_SECONDS)

        assert not first_task.done(), "the holding allocation finished before it was released"
        assert second_result.reservation_id is not None
    finally:
        await _release(paused, first_task)

    assert first_task.result().reservation_id is not None
    reservations = await _reservations_of(factory, (signal_id,))
    assert sorted(reservations) == sorted(
        [(holder, holding.delivery_id), (other, second.delivery_id)]
    )
    assert holding.delivery_id != second.delivery_id


async def test_two_deliveries_for_one_users_pool_serialize(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """Two strategies on one market, both subscribed by the same user: their
    deliveries are allocated in that user's one pool, so the second queues on
    the pool lock until the first commits."""
    factory = pg_session_factory
    first_strategy = await _enabled_strategy(factory)
    second_strategy = await _enabled_strategy(factory)
    first_signal = await _signal(factory, first_strategy)
    second_signal = await _signal(factory, second_strategy)
    users = (OWNER_ID,)
    holding = await allocate_command(
        factory, signal_id=first_signal, strategy_id=first_strategy, requested=REQUEST
    )
    waiting = await allocate_command(
        factory, signal_id=second_signal, strategy_id=second_strategy, requested=REQUEST
    )

    paused: list[_PausedCommit] = []
    first_task = asyncio.create_task(_allocate(factory, holding, users, paused))
    second_task: asyncio.Task[AllocationResult] | None = None
    try:
        await asyncio.wait_for(_reached(paused), WAIT_SECONDS)
        second_task = asyncio.create_task(_allocate(factory, waiting, users))
        await _until_queued(factory, OWNER_ID)
        assert not second_task.done(), "the second delivery did not wait for the pool lock"
        assert await _reservations_of(factory, (first_signal, second_signal)) == []
    finally:
        await _release(paused, first_task)
        if second_task is not None:
            await asyncio.wait({second_task}, timeout=WAIT_SECONDS)
            if not second_task.done():
                second_task.cancel()
                await asyncio.gather(second_task, return_exceptions=True)

    assert second_task is not None
    assert first_task.result().reservation_id is not None
    assert second_task.result().reservation_id is not None
    assert sorted(await _reservations_of(factory, (first_signal, second_signal))) == sorted(
        [(OWNER_ID, holding.delivery_id), (OWNER_ID, waiting.delivery_id)]
    )


async def _reached(paused: list[_PausedCommit]) -> None:
    """Waits until the holding allocation exists and has reached its commit."""
    while not paused:
        await asyncio.sleep(0.01)
    await paused[0].reached.wait()
