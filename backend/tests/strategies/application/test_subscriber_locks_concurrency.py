"""Archive and delete against EVERY subscriber, on real PostgreSQL (multi-user
tasks.md C.9, finding e; the template is
``tests/allocation/infrastructure/test_pool_lock_per_user.py``).

The lock-hold harness: one actor holds a lock (or a use case is paused right before
its commit, which is where the transaction's locks are still held) and the test
asserts the other actor is STILL BLOCKED, ``not task.done()``, after a real wait
-- never a ``sleep(0)`` barrier. Each wait is bounded by ``asyncio.wait`` with a
timeout, and every task is awaited in a ``finally`` so a red test leaves no lock
held.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocationResult,
)
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository
from strategy_manager.strategies.application.archive_strategy import ArchiveStrategy
from strategy_manager.strategies.application.delete_strategy import DeleteStrategy
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.application.subscriber_locks import SubscribersChanged
from strategy_manager.strategies.infrastructure.enablement_log import SqlAlchemyEnablementLog
from strategy_manager.strategies.infrastructure.exposure_adapter import StrategyExposureAdapter
from strategy_manager.strategies.infrastructure.history_adapter import StrategyHistoryAdapter
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from strategy_manager.strategies.infrastructure.subscribers_adapter import (
    StrategySubscribersAdapter,
)
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow
from tests.allocation.fakes import AlwaysEnabledPool, RecordingSkipRecorder
from tests.ledger.infrastructure.conftest import seed_strategy
from tests.owner import OWNER_ID, allocate_command, ensure_author_subscription
from tests.strategies.wiring import real_subscribers
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]
MARKET = seeds.MARKET
POOL_KEY = PoolKey(exchange=Exchange.BYBIT, venue=Venue.USDT_M, settlement_currency=Currency.USDT)
FIXED_NOW = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
_WAIT = 0.5
_FINISH = 10.0


class _Clock:
    def now(self) -> datetime:
        return FIXED_NOW


class _PausedCommit:
    """Wraps a session's ``commit()``: everything the use case did is written but
    uncommitted, so every lock it took is still held, until ``resume`` is set."""

    def __init__(
        self, session: AsyncSession, reached: asyncio.Event, resume: asyncio.Event
    ) -> None:
        self._session = session
        self._reached = reached
        self._resume = resume

    async def commit(self) -> None:
        self._reached.set()
        await self._resume.wait()
        await self._session.commit()


class _PausedAfterFirstPolicyRead:
    """Wraps the real policy adapter: the PRE-LOCK read answers (the strategy is
    still enabled), then the allocation waits for ``resume`` before it goes for the
    lock, which is the window ``test_archive_vs_allocate_concurrency`` uses."""

    def __init__(
        self, inner: StrategyPolicyAdapter, reached: asyncio.Event, resume: asyncio.Event
    ) -> None:
        self._inner = inner
        self._reached = reached
        self._resume = resume
        self._calls = 0

    async def policy_for(self, strategy_id: UUID) -> object:
        snapshot = await self._inner.policy_for(strategy_id)
        self._calls += 1
        if self._calls == 1:
            self._reached.set()
            await self._resume.wait()
        return snapshot


class _ReportsFirstRead:
    """Wraps the real subscribers adapter and reports when ``live_pools`` first
    answered, so a test can change the world exactly between that read and the
    locks."""

    def __init__(self, inner: StrategySubscribersAdapter, first_read: asyncio.Event) -> None:
        self._inner = inner
        self._first_read = first_read
        self._reads = 0

    async def live_pools(self, strategy_id: UUID) -> list[object]:
        pools = await self._inner.live_pools(strategy_id)
        self._reads += 1
        if self._reads == 1:
            self._first_read.set()
        return pools  # type: ignore[return-value]

    async def holders(self, strategy_id: UUID, subscribers: object) -> list[UUID]:
        return await self._inner.holders(strategy_id, subscribers)  # type: ignore[arg-type]

    async def end_all(self, strategy_id: UUID, now: datetime) -> int:
        return await self._inner.end_all(strategy_id, now)


def _archive(
    session: AsyncSession,
    *,
    commit: object | None = None,
    subscribers: object | None = None,
) -> ArchiveStrategy:
    ledger = SqlAlchemyLedgerRepository(session)
    return ArchiveStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        pool_lock=PoolLockAdapter(session),
        subscribers=subscribers if subscribers is not None else real_subscribers(session),  # type: ignore[arg-type]
        exposure=StrategyExposureAdapter(
            ledger=ledger,
            symbol_holdings=ReadSymbolHoldings(ledger),
            reservations=SqlAlchemyReservationRepository(session),
            attempts=SqlAlchemyExecutionAttemptRepository(session),
        ),
        commit=commit if commit is not None else session,  # type: ignore[arg-type]
        clock=_Clock(),
    )


def _delete(session: AsyncSession, *, commit: object | None = None) -> DeleteStrategy:
    return DeleteStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        pool_lock=PoolLockAdapter(session),
        subscribers=real_subscribers(session),
        history=StrategyHistoryAdapter(
            signals=SqlAlchemySignalRepository(session),
            reservations=SqlAlchemyReservationRepository(session),
            attempts=SqlAlchemyExecutionAttemptRepository(session),
            ledger=SqlAlchemyLedgerRepository(session),
            proposals=SqlAlchemyBookingProposalRepository(session),
            enablement_log=SqlAlchemyEnablementLog(session),
            session=session,
        ),
        enablement_log=SqlAlchemyEnablementLog(session),
        clock=SystemClock(),
        commit=commit if commit is not None else session,  # type: ignore[arg-type]
    )


async def _strategy(factory: Factory, *, enabled: bool = False) -> UUID:
    """A strategy of the owner's on ``MARKET`` (DISABLED unless asked), with the
    author's own subscription (what ``RegisterStrategy`` makes)."""
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id, enabled=enabled)
    author_subscribes = True
    if author_subscribes:
        async with factory() as session:
            await ensure_author_subscription(session, strategy_id)
            await session.commit()
    return strategy_id


async def _subscriber(
    factory: Factory, strategy_id: UUID, *, status: str = "ACTIVE"
) -> tuple[UUID, int]:
    user_id, pool_id = await seeds.user(factory)
    assert pool_id is not None
    await seeds.subscription(factory, user_id, strategy_id, pool_id, status=status)
    return user_id, pool_id


async def _hold(factory: Factory, user_id: UUID) -> AsyncSession:
    """A session holding ``user_id``'s pool lock on ``MARKET`` until it rolls back."""
    holder = factory()
    session = await holder.__aenter__()
    await PgAdvisoryLockAdapter(session).acquire(LockKey.from_pool_key(user_id, POOL_KEY))
    return session


async def _release(holder: AsyncSession) -> None:
    await holder.rollback()
    await holder.close()


async def _take_pool_lock(factory: Factory, user_id: UUID) -> tuple[bool, asyncio.Task[None]]:
    """Starts an actor taking ``user_id``'s pool lock the way a delivery does, and
    reports whether it finished within ``_WAIT``."""

    async def take() -> None:
        async with factory() as session:
            await PgAdvisoryLockAdapter(session).acquire(LockKey.from_pool_key(user_id, POOL_KEY))
            await session.rollback()

    task = asyncio.create_task(take())
    await asyncio.wait({task}, timeout=_WAIT)
    return task.done(), task


async def _settle(*tasks: asyncio.Task[object] | asyncio.Task[None]) -> None:
    """Lets every task end (bounded) and cancels what does not, so no lock outlives
    the test."""
    pending = [task for task in tasks if not task.done()]
    if pending:
        await asyncio.wait(pending, timeout=_FINISH)
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def _statuses(factory: Factory, strategy_id: UUID) -> dict[UUID, str]:
    async with factory() as session:
        result = await session.execute(
            select(SubscriptionRow.user_id, SubscriptionRow.status).where(
                SubscriptionRow.strategy_id == strategy_id
            )
        )
        return {user_id: status for user_id, status in result.all()}


async def _archived_at(factory: Factory, strategy_id: UUID) -> datetime | None:
    async with factory() as session:
        row = await session.get(StrategyRow, strategy_id)
        assert row is not None
        return row.archived_at


async def _reservations(factory: Factory, strategy_id: UUID) -> list[UUID]:
    async with factory() as session:
        result = await session.execute(
            select(ReservationRow.id).where(ReservationRow.strategy_id == strategy_id)
        )
        return [row[0] for row in result.all()]


async def _author_pool_id(factory: Factory) -> int:
    async with factory() as session:
        found = (
            await session.execute(
                text(
                    "SELECT id FROM capital_pools WHERE user_id = :u AND exchange = 'bybit' "
                    "AND venue = 'usdt-m' AND settlement_currency = 'USDT'"
                ),
                {"u": OWNER_ID},
            )
        ).scalar_one()
        return int(found)


# --------------------------------------------- an opening in a subscriber's pool waits


async def test_an_opening_in_a_subscribers_pool_waits_for_archive_and_is_then_refused_as_archived(
    pg_session_factory: Factory,
) -> None:
    strategy_id = await _strategy(pg_session_factory, enabled=True)
    subscriber, _ = await _subscriber(pg_session_factory, strategy_id)
    signal_id = uuid4()
    async with pg_session_factory() as session:
        session.add(
            SignalRow(
                id=signal_id,
                strategy_id=strategy_id,
                idempotency_key=f"k-{signal_id}",
                raw_payload={},
                action="buy",
                contracts=Decimal("1"),
                position_size=Decimal("1"),
                price=Decimal("1"),
                symbol="SEED",
                signal_type=str(strategy_id),
            )
        )
        await session.commit()
    # The delivery is the SUBSCRIBER's, never the author's.
    command = await allocate_command(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        requested=Money(amount=Decimal("200"), currency=Currency.USDT),
        user_id=subscriber,
    )
    assert command.user_id == subscriber != OWNER_ID

    reached, resume = asyncio.Event(), asyncio.Event()
    policy_read, policy_resume = asyncio.Event(), asyncio.Event()
    balances = FakeBalanceSource()
    balances.set_balance(*MARKET, Decimal("1000"))
    config = {
        (subscriber, MARKET): PoolConfig(
            exchange=Exchange.BYBIT,
            venue=Venue.USDT_M,
            settlement_currency=Currency.USDT,
            user_id=subscriber,
            min_order_size=Decimal("1"),
        )
    }
    outcome: dict[str, AllocationResult] = {}

    async def run_archive() -> None:
        async with pg_session_factory() as session:
            await _archive(session, commit=_PausedCommit(session, reached, resume)).archive(
                strategy_id
            )

    async def run_allocate() -> None:
        async with pg_session_factory() as session:
            use_case = AllocateCapital(
                strategy_policy=_PausedAfterFirstPolicyRead(  # type: ignore[arg-type]
                    StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
                    policy_read,
                    policy_resume,
                ),
                pool_balance=PoolBalanceAdapter(config, balances),
                lock=PgAdvisoryLockAdapter(session),
                reservations=SqlAlchemyReservationRepository(session),
                commit=session,  # type: ignore[arg-type]
                clock=_Clock(),  # type: ignore[arg-type]
                reservation_ttl_seconds=30,
                skip_recorder=RecordingSkipRecorder(),
                pool_status=AlwaysEnabledPool(),
            )
            outcome["value"] = await use_case.allocate(command)

    # The opening read the strategy while it was still enabled and stops right
    # before the lock; only then is the strategy disabled and archived.
    allocating = asyncio.create_task(run_allocate())
    archiving: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(policy_read.wait(), _FINISH)
        async with pg_session_factory() as session:
            await session.execute(
                text("UPDATE strategies SET enabled = false WHERE id = :id"), {"id": strategy_id}
            )
            await session.commit()
        archiving = asyncio.create_task(run_archive())
        await asyncio.wait_for(reached.wait(), _FINISH)  # archive holds every lock it took
        policy_resume.set()
        await asyncio.wait({allocating}, timeout=_WAIT)
        assert not allocating.done(), (
            "an opening in a subscriber's pool did not wait for the archive's lock"
        )
    finally:
        policy_resume.set()
        resume.set()
        await _settle(allocating, *([archiving] if archiving else []))

    assert archiving is not None
    archiving.result()
    allocating.result()
    assert outcome["value"].outcome.value == "SKIP"
    assert outcome["value"].skip_reason == "STRATEGY_ARCHIVED"
    assert await _reservations(pg_session_factory, strategy_id) == []


async def test_a_delivery_in_a_subscribers_pool_waits_for_delete(
    pg_session_factory: Factory,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    subscriber, _ = await _subscriber(pg_session_factory, strategy_id)
    reached, resume = asyncio.Event(), asyncio.Event()

    async def run_delete() -> None:
        async with pg_session_factory() as session:
            await _delete(session, commit=_PausedCommit(session, reached, resume)).delete(
                strategy_id
            )

    deleting = asyncio.create_task(run_delete())
    probe: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(reached.wait(), _FINISH)
        done, probe = await _take_pool_lock(pg_session_factory, subscriber)
        assert not done, "a subscriber's pool lock was free while the delete held its locks"
    finally:
        resume.set()
        await _settle(deleting, *([probe] if probe else []))

    deleting.result()
    assert probe is not None
    probe.result()
    assert await _statuses(pg_session_factory, strategy_id) == {}


# ------------------------------------------------------------------- the lock order


async def test_the_locks_are_taken_lowest_pool_first_and_the_highest_is_waited_on_last(
    pg_session_factory: Factory,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    first, _ = await _subscriber(pg_session_factory, strategy_id)
    second, highest = await _subscriber(pg_session_factory, strategy_id)
    assert highest > await _author_pool_id(pg_session_factory)

    holder = await _hold(pg_session_factory, second)  # the HIGHEST pool's lock
    archiving: asyncio.Task[None] | None = None
    probes: list[asyncio.Task[None]] = []
    try:

        async def run_archive() -> None:
            async with pg_session_factory() as session:
                await _archive(session).archive(strategy_id)

        archiving = asyncio.create_task(run_archive())
        await asyncio.wait({archiving}, timeout=_WAIT)
        assert not archiving.done(), "archive did not wait for a subscriber's held pool lock"

        # Blocked on the highest pool, it already holds every lower one: ascending.
        for lower in (OWNER_ID, first):
            done, probe = await _take_pool_lock(pg_session_factory, lower)
            probes.append(probe)
            assert not done, "a lower pool's lock was free while archive waited on the highest"
    finally:
        await _release(holder)
        await _settle(*([archiving] if archiving else []), *probes)

    assert archiving is not None
    archiving.result()
    assert set((await _statuses(pg_session_factory, strategy_id)).values()) == {"ENDED"}


async def test_two_archivers_of_strategies_sharing_pools_do_not_deadlock(
    pg_session_factory: Factory,
) -> None:
    one = await _strategy(pg_session_factory)
    other = await _strategy(pg_session_factory)
    shared: list[tuple[UUID, int]] = []
    for _ in range(2):
        user_id, pool_id = await seeds.user(pg_session_factory)
        assert pool_id is not None
        for strategy_id in (one, other):
            await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id)
        shared.append((user_id, pool_id))
    highest_user = max(shared, key=lambda pair: pair[1])[0]

    holder = await _hold(pg_session_factory, highest_user)
    results: dict[UUID, BaseException | None] = {}

    async def run_archive(strategy_id: UUID) -> None:
        async with pg_session_factory() as session:
            try:
                await _archive(session).archive(strategy_id)
                results[strategy_id] = None
            except BaseException as error:  # noqa: BLE001 -- the test asserts on it
                results[strategy_id] = error

    tasks = [asyncio.create_task(run_archive(one)), asyncio.create_task(run_archive(other))]
    try:
        await asyncio.wait(tasks, timeout=_WAIT)
        assert not any(task.done() for task in tasks), (
            "an archive finished while a subscriber's pool lock was held by someone else"
        )
    finally:
        await _release(holder)
        await _settle(*tasks)

    assert results == {one: None, other: None}, results
    for strategy_id in (one, other):
        assert await _archived_at(pg_session_factory, strategy_id) == FIXED_NOW


# ---------------------------------------------- a subscriber joins between read and locks


async def test_a_subscriber_who_joins_between_the_read_and_the_locks_refuses_the_archive(
    pg_session_factory: Factory,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    holder = await _hold(pg_session_factory, OWNER_ID)  # the only pool read so far
    first_read = asyncio.Event()
    archiving: asyncio.Task[None] | None = None
    try:

        async def run_archive() -> None:
            async with pg_session_factory() as session:
                subscribers = _ReportsFirstRead(real_subscribers(session), first_read)
                await _archive(session, subscribers=subscribers).archive(strategy_id)

        archiving = asyncio.create_task(run_archive())
        await asyncio.wait_for(first_read.wait(), _FINISH)
        late, _ = await _subscriber(pg_session_factory, strategy_id)  # committed
    finally:
        await _release(holder)
        await _settle(*([archiving] if archiving else []))

    assert archiving is not None
    with pytest.raises(SubscribersChanged):
        archiving.result()
    assert await _archived_at(pg_session_factory, strategy_id) is None
    assert (await _statuses(pg_session_factory, strategy_id))[late] == "ACTIVE"


async def test_a_subscription_being_inserted_makes_the_row_lock_wait_and_is_then_seen(
    pg_session_factory: Factory,
) -> None:
    """The claim ``subscriber_locks`` rests on: an INSERT in flight holds ``FOR KEY
    SHARE`` on the strategy row (``fk_subscriptions_strategy``), so the archive's
    ``FOR UPDATE`` waits for it to commit and the re-read then sees it."""
    strategy_id = await _strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    first_read = asyncio.Event()
    inserter = pg_session_factory()
    session_in_flight = await inserter.__aenter__()
    await session_in_flight.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, allocation_percent, "
            "status) VALUES (:id, :user_id, :strategy_id, :pool_id, 30, 'ACTIVE')"
        ),
        {"id": uuid4(), "user_id": user_id, "strategy_id": strategy_id, "pool_id": pool_id},
    )
    archiving: asyncio.Task[None] | None = None
    try:

        async def run_archive() -> None:
            async with pg_session_factory() as session:
                subscribers = _ReportsFirstRead(real_subscribers(session), first_read)
                await _archive(session, subscribers=subscribers).archive(strategy_id)

        archiving = asyncio.create_task(run_archive())
        await asyncio.wait_for(first_read.wait(), _FINISH)
        await asyncio.wait({archiving}, timeout=_WAIT)
        assert not archiving.done(), "the row lock did not wait for the insert in flight"
        await session_in_flight.commit()
    finally:
        await inserter.close()
        await _settle(*([archiving] if archiving else []))

    assert archiving is not None
    with pytest.raises(SubscribersChanged):
        archiving.result()


# --------------------------------------------------------------------- delete cascades


async def test_delete_takes_the_subscriptions_of_several_users_with_it(
    pg_session_factory: Factory,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    await _subscriber(pg_session_factory, strategy_id, status="ACTIVE")
    await _subscriber(pg_session_factory, strategy_id, status="LEAVING")
    await _subscriber(pg_session_factory, strategy_id, status="ENDED")
    untouched = await _strategy(pg_session_factory)
    before = await _statuses(pg_session_factory, untouched)

    async with pg_session_factory() as session:
        await _delete(session).delete(strategy_id)

    assert await _statuses(pg_session_factory, strategy_id) == {}
    assert await _statuses(pg_session_factory, untouched) == before
