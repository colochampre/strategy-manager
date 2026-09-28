"""Real-Postgres proof that ``ArchiveStrategy`` and ``AllocateCapital``
genuinely serialize on the SAME advisory lock (design.md § 8, "The race this
closes"; tasks.md 2c.8, 2c.9; ``rules.tasks``: advisory locks have no
meaningful fake).

Placed under ``strategies/application/`` per tasks.md's own path, mirroring
``tests/allocation/infrastructure/test_concurrency_race.py``'s convention of
proving lock behaviour only against a real database -- a fake
``AdvisoryLockPort``/``PoolLockPort`` can always be made to "block" by
construction, which would prove nothing about whether the two use cases
actually reach for the same ``pg_advisory_xact_lock`` key.

**Deterministic, not scheduler-luck.** Both scenarios below use the SAME
lock-hold-open pattern ``test_update_strategy_concurrency.py`` established:
wrap the real lock so that, once Postgres has GENUINELY granted it, the
wrapped call waits on an ``asyncio.Event`` before returning -- keeping the
transaction (and the lock) open long enough for the test to assert the
second actor is STILL BLOCKED (``not task.done()``) after a real wait,
rather than merely hoping one coroutine happened to run before the other.

**Binding requirement 1 (same lock key, proven wrong).** Both tests below
were re-run with ``PoolLockAdapter.acquire`` temporarily deriving a
DIFFERENT key, unrelated to the pool. The "archive wins" scenario's
``assert not task_allocate.done()`` failed immediately -- AllocateCapital's
own real advisory-lock attempt no longer collided with ArchiveStrategy's
mutated one, so it sailed straight through instead of blocking. That is
the clean, unconfounded proof of this requirement (its own exposure query
never runs a locking read, so nothing else could have serialized it).

The "allocation wins" scenario's block held anyway under the SAME
mutation, for a reason worth recording rather than hiding: ``ArchiveStrategy
.archive()`` takes its ``SELECT ... FOR UPDATE`` row lock on ``strategies``
BEFORE it ever reaches the pool lock, and Postgres itself places an
implicit ``FOR KEY SHARE`` lock on that SAME parent row for the whole
lifetime of AllocateCapital's in-flight reservation INSERT (which carries a
foreign key to it) -- so ArchiveStrategy's row lock genuinely blocks on
THAT, independent of whether the two advisory-lock keys agree. This is a
real, incidental second layer of serialization for this one ordering, not
a substitute for requirement 1: only the "archive wins" scenario isolates
the advisory lock cleanly, and it is what this suite treats as the proof.
Neither mutated run is committed; both outputs are reproduced verbatim in
this unit's apply-progress report as the RED evidence for requirement 1.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
    AllocationResult,
)
from strategy_manager.allocation.application.ports import StrategyPolicySnapshot
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.strategies.application.archive_strategy import ArchiveStrategy, OpenPosition
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.exposure_adapter import StrategyExposureAdapter
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.allocation.fakes import RecordingSkipRecorder

pytestmark = pytest.mark.integration

POOL = ("pionex", "spot", "USDT")
POOL_BALANCE = Decimal("1000")
REQUEST_AMOUNT = Decimal("200")
FIXED_NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)

_POOL_CONFIG = {
    POOL: PoolConfig(
        exchange=Exchange.PIONEX,
        venue=Venue.SPOT,
        settlement_currency=Currency.USDT,
        min_order_size=Decimal("1"),
    )
}


class FixedClock:
    def now(self) -> datetime:
        return FIXED_NOW


class _PausingCommit:
    """Wraps a real session's ``commit()``. The advisory lock is released
    ONLY by commit or rollback (design.md § Interfaces / Contracts), so
    pausing commit -- after every write inside the transaction already ran,
    including the in-lock re-check -- keeps the lock held open through
    AllocateCapital's ENTIRE transaction body, not merely its
    ``lock.acquire()`` call. That is what lets a concurrent disable
    committed on a SEPARATE connection be observed by a LATER read (the
    in-lock re-check already ran before this pause, so it correctly still
    saw ``enabled=True`` -- exactly the race window design.md describes),
    while still proving a genuinely held lock blocks ``ArchiveStrategy``."""

    def __init__(self, session: AsyncSession, resume: asyncio.Event) -> None:
        self._session = session
        self._resume = resume

    async def commit(self) -> None:
        await self._resume.wait()
        await self._session.commit()


class _PausingPoolLock:
    """Same pattern, for ``ArchiveStrategy``'s lock (``PoolLockPort`` shape,
    ``acquire(exchange, venue, settlement_currency)``)."""

    def __init__(self, inner: object, resume: asyncio.Event) -> None:
        self._inner = inner
        self._resume = resume

    async def acquire(self, exchange: str, venue: str, settlement_currency: str) -> None:
        inner: object = self._inner
        await inner.acquire(exchange, venue, settlement_currency)  # type: ignore[attr-defined]
        await self._resume.wait()


class _PausingPolicyAfterFirstCall:
    """Wraps the REAL ``StrategyPolicyAdapter``. Pauses only after the
    FIRST call (the pre-lock read) returns, before handing it back to
    ``AllocateCapital`` -- so the test can deterministically disable the
    strategy in the window between AllocateCapital's pre-lock read (which
    must still see ``enabled=True``, exactly the race design.md describes)
    and its attempt to acquire the advisory lock. The SECOND call (the
    in-lock re-check) is never paused, so it reads whatever is truly in the
    database at that moment."""

    def __init__(self, inner: StrategyPolicyAdapter, pause_after_first: asyncio.Event) -> None:
        self._inner = inner
        self._pause_after_first = pause_after_first
        self.calls = 0

    async def policy_for(self, strategy_id: UUID) -> StrategyPolicySnapshot:
        result = await self._inner.policy_for(strategy_id)
        self.calls += 1
        if self.calls == 1:
            await self._pause_after_first.wait()
        return result


class _PausingPolicyAfterSecondCall:
    """Wraps the REAL ``StrategyPolicyAdapter``. Pauses only after the
    SECOND call (the in-lock re-check) returns, before handing it back to
    ``AllocateCapital`` -- holding it exactly where the deadlock test
    (tasks.md 2c.15) needs it: the advisory lock already acquired, the
    in-lock re-read already done (still ``enabled=True``, since the
    strategy is disabled only AFTER this pause begins), but the reservation
    INSERT -- and the implicit ``FOR KEY SHARE`` lock it takes on
    ``strategies`` -- has not happened yet."""

    def __init__(self, inner: StrategyPolicyAdapter, pause_after_second: asyncio.Event) -> None:
        self._inner = inner
        self._pause_after_second = pause_after_second
        self.calls = 0

    async def policy_for(self, strategy_id: UUID) -> StrategyPolicySnapshot:
        result = await self._inner.policy_for(strategy_id)
        self.calls += 1
        if self.calls == 2:
            await self._pause_after_second.wait()
        return result


async def _seed_strategy(
    session_factory: async_sessionmaker[AsyncSession], *, strategy_id: UUID
) -> None:
    async with session_factory() as session:
        session.add(
            StrategyRow(
                id=strategy_id,
                name=f"strategy-{strategy_id}",
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                enabled=True,
                fill_mode="PARTIAL",
            )
        )
        await session.commit()


async def _seed_signal(
    session_factory: async_sessionmaker[AsyncSession], *, signal_id: UUID, strategy_id: UUID
) -> None:
    """``reservations.signal_id`` has a real FK into ``signals`` (migration
    ``0004``) -- ``AllocateCapital.allocate`` needs a real row to reference."""
    async with session_factory() as session:
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


async def _disable_strategy(
    session_factory: async_sessionmaker[AsyncSession], *, strategy_id: UUID
) -> None:
    async with session_factory() as session:
        row = await session.get(StrategyRow, strategy_id)
        assert row is not None
        row.enabled = False
        await session.commit()


def _build_archive_strategy(session: AsyncSession, pool_lock: object) -> ArchiveStrategy:
    return ArchiveStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        pool_lock=pool_lock,  # type: ignore[arg-type]
        exposure=StrategyExposureAdapter(
            ledger=SqlAlchemyLedgerRepository(session),
            symbol_holdings=ReadSymbolHoldings(SqlAlchemyLedgerRepository(session)),
            reservations=SqlAlchemyReservationRepository(session),
            attempts=SqlAlchemyExecutionAttemptRepository(session),
        ),
        commit=session,  # type: ignore[arg-type]
        clock=FixedClock(),  # type: ignore[arg-type]
    )


async def _reservation_ids_for(
    session_factory: async_sessionmaker[AsyncSession], strategy_id: UUID
) -> list[UUID]:
    async with session_factory() as session:
        result = await session.execute(
            select(ReservationRow.id).where(ReservationRow.strategy_id == strategy_id)
        )
        return [row[0] for row in result.all()]


async def test_allocation_wins_lock_first_archive_then_refused_sees_live_reservation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """AllocateCapital reaches the pool's advisory lock first, runs its
    ENTIRE transaction body -- including the in-lock re-check, which still
    sees ``enabled=True`` at that point -- and then holds the lock open by
    pausing its own ``commit()`` (``_PausingCommit``; the lock is released
    only by commit or rollback, design.md § Interfaces / Contracts).
    Meanwhile ``ArchiveStrategy`` -- run against the now-disabled,
    still-flat strategy -- must genuinely BLOCK trying to acquire the SAME
    lock, not merely lose a race. Once AllocateCapital's commit finally
    runs (writing its reservation and releasing the lock), ``ArchiveStrategy``
    unblocks, reads exposure, sees the live reservation AllocateCapital just
    wrote, and refuses with ``OpenPosition``."""
    strategy_id = uuid4()
    signal_id = uuid4()
    await _seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await _seed_signal(pg_session_factory, signal_id=signal_id, strategy_id=strategy_id)

    resume_allocate_commit = asyncio.Event()
    allocate_result: dict[str, AllocationResult] = {}

    async def run_allocate() -> None:
        async with pg_session_factory() as session:
            use_case = AllocateCapital(
                strategy_policy=StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
                pool_balance=PoolBalanceAdapter(_POOL_CONFIG, _seeded_balance_source()),
                lock=PgAdvisoryLockAdapter(session),
                reservations=SqlAlchemyReservationRepository(session),
                commit=_PausingCommit(session, resume_allocate_commit),  # type: ignore[arg-type]
                clock=FixedClock(),  # type: ignore[arg-type]
                reservation_ttl_seconds=30,
                skip_recorder=RecordingSkipRecorder(),
            )
            allocate_result["value"] = await use_case.allocate(
                AllocateCommand(
                    signal_id=signal_id,
                    strategy_id=strategy_id,
                    requested=Money(amount=REQUEST_AMOUNT, currency=Currency.USDT),
                )
            )

    task_allocate = asyncio.create_task(run_allocate())
    await asyncio.sleep(0.2)  # AllocateCapital ran its whole transaction body (pre-lock
    # read, lock acquire, in-lock re-check still enabled=True, balance read, insert) and
    # is now paused right before its own commit -- the lock is still held.

    # The strategy is disabled only NOW, after AllocateCapital's in-lock
    # re-check already ran and saw enabled=True (exactly the race window
    # design.md describes) -- on a SEPARATE connection, so it commits
    # immediately without touching the still-held advisory lock.
    await _disable_strategy(pg_session_factory, strategy_id=strategy_id)

    archive_exc: dict[str, BaseException] = {}

    async def run_archive() -> None:
        async with pg_session_factory() as session:
            use_case = _build_archive_strategy(session, PoolLockAdapter(session))
            try:
                await use_case.archive(strategy_id)
            except BaseException as exc:  # noqa: BLE001 -- captured for the assertion below
                archive_exc["value"] = exc

    task_archive = asyncio.create_task(run_archive())
    await asyncio.sleep(0.3)  # ArchiveStrategy should now be genuinely blocked on the
    # SAME advisory lock AllocateCapital holds.
    assert not task_archive.done(), (
        "ArchiveStrategy completed without waiting for AllocateCapital's held "
        "pool lock -- the two are not serializing on the same key"
    )

    resume_allocate_commit.set()  # let AllocateCapital's commit run, releasing the lock
    await asyncio.gather(task_allocate, task_archive)

    result = allocate_result["value"]
    assert result.outcome.value in ("FULL", "PARTIAL")
    assert result.reservation_id is not None

    assert "value" in archive_exc, "ArchiveStrategy did not refuse"
    assert isinstance(archive_exc["value"], OpenPosition)
    assert archive_exc["value"].exposure.live_reservations == (result.reservation_id,)


async def test_archive_wins_lock_first_allocation_in_lock_reread_sees_archived_skips_no_reservation(  # noqa: E501
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``ArchiveStrategy`` reaches the pool's advisory lock first and holds
    it open (paused, via ``_PausingPoolLock``), on a strategy that is
    already disabled and flat. AllocateCapital's PRE-LOCK read (paused via
    ``_PausingPolicyAfterFirstCall``, before the strategy is disabled) still
    sees ``enabled=True`` and proceeds toward the lock -- where it must
    genuinely BLOCK on the SAME key ArchiveStrategy holds. Once
    ArchiveStrategy commits ``archived_at`` and releases the lock,
    AllocateCapital's IN-LOCK re-read (the second, unpaused call) sees
    ``archived=True`` and skips, inserting no reservation."""
    strategy_id = uuid4()
    signal_id = uuid4()
    await _seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await _seed_signal(pg_session_factory, signal_id=signal_id, strategy_id=strategy_id)

    resume_policy = asyncio.Event()
    allocate_result: dict[str, AllocationResult] = {}

    async def run_allocate() -> None:
        async with pg_session_factory() as session:
            real_policy = StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session))
            paused_policy: object = _PausingPolicyAfterFirstCall(real_policy, resume_policy)
            use_case = AllocateCapital(
                strategy_policy=paused_policy,  # type: ignore[arg-type]
                pool_balance=PoolBalanceAdapter(_POOL_CONFIG, _seeded_balance_source()),
                lock=PgAdvisoryLockAdapter(session),  # type: ignore[arg-type]
                reservations=SqlAlchemyReservationRepository(session),
                commit=session,  # type: ignore[arg-type]
                clock=FixedClock(),  # type: ignore[arg-type]
                reservation_ttl_seconds=30,
                skip_recorder=RecordingSkipRecorder(),
            )
            allocate_result["value"] = await use_case.allocate(
                AllocateCommand(
                    signal_id=signal_id,
                    strategy_id=strategy_id,
                    requested=Money(amount=REQUEST_AMOUNT, currency=Currency.USDT),
                )
            )

    task_allocate = asyncio.create_task(run_allocate())
    await asyncio.sleep(0.2)  # AllocateCapital's pre-lock read (enabled=True) has run and
    # is now paused, BEFORE it ever tries the lock.

    await _disable_strategy(pg_session_factory, strategy_id=strategy_id)

    resume_archive = asyncio.Event()
    archive_done = asyncio.Event()

    async def run_archive() -> None:
        async with pg_session_factory() as session:
            real_lock = PoolLockAdapter(session)
            use_case = _build_archive_strategy(session, _PausingPoolLock(real_lock, resume_archive))
            await use_case.archive(strategy_id)
            archive_done.set()

    task_archive = asyncio.create_task(run_archive())
    await asyncio.sleep(0.2)  # ArchiveStrategy acquires the lock first and is now paused,
    # holding it.

    resume_policy.set()  # let AllocateCapital proceed toward the SAME lock
    await asyncio.sleep(0.3)  # it should now be genuinely blocked behind ArchiveStrategy
    assert not task_allocate.done(), (
        "AllocateCapital completed without waiting for ArchiveStrategy's held "
        "pool lock -- the two are not serializing on the same key"
    )
    assert not archive_done.is_set()

    resume_archive.set()  # let ArchiveStrategy finish (archived_at + commit), releasing the lock
    await asyncio.gather(task_allocate, task_archive)

    result = allocate_result["value"]
    assert result.outcome.value == "SKIP"
    assert result.skip_reason == "STRATEGY_ARCHIVED"
    assert result.reservation_id is None

    assert await _reservation_ids_for(pg_session_factory, strategy_id) == []


async def test_archive_takes_pool_lock_before_row_lock_no_deadlock_with_inflight_allocation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """tasks.md 2c.15 -- the lock-order-inversion deadlock a reviewer found
    in the first cut of this unit, and the fix: ``ArchiveStrategy`` MUST
    take the pool's advisory lock BEFORE the strategy row's ``FOR UPDATE``
    lock -- the same order AllocateCapital's own explicit advisory lock and
    its reservation INSERT's IMPLICIT ``FOR KEY SHARE`` row lock already
    impose. Reversed (row lock first, as the original cut had it), the
    following genuinely deadlocks:

    1. AllocateCapital acquires the advisory lock and re-reads policy:
       still enabled.
    2. The owner disables the strategy (a separate, already-committed
       transaction).
    3. ArchiveStrategy takes the row ``FOR UPDATE`` lock, passes the
       (now-disabled) enabled check, and waits on the advisory lock
       AllocateCapital holds.
    4. AllocateCapital's reservation INSERT then waits on the SAME row's
       implicit ``FOR KEY SHARE`` lock, which ArchiveStrategy now holds.

    Circular wait -- Postgres detects it and aborts one side with
    ``DeadlockDetected``. With the fix (advisory lock first, row lock
    second, re-reading everything decided on -- ``enabled``,
    ``archived_at`` -- from that locked read), ArchiveStrategy instead
    blocks cleanly on step 3 behind the still-held advisory lock, never
    reaching the row lock until AllocateCapital's transaction has already
    committed and released it -- no cycle is ever formed.

    **Deterministic**: ``_PausingPolicyAfterSecondCall`` holds
    AllocateCapital open exactly after its in-lock re-read (still
    ``enabled=True``) and before its INSERT -- the precise window the race
    above needs. Against the ORIGINAL (row-lock-first) order, this test
    failed with a genuine ``DeadlockDetected`` from Postgres, raised on
    whichever side lost -- captured verbatim in this unit's apply-progress
    report as the RED evidence for this fix, rather than merely
    ``not task_archive.done()`` failing early (both are named as the
    possible RED shapes here because which one appears depends on exactly
    when Postgres's deadlock detector runs relative to this test's own
    waits)."""
    strategy_id = uuid4()
    signal_id = uuid4()
    await _seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await _seed_signal(pg_session_factory, signal_id=signal_id, strategy_id=strategy_id)

    resume_allocate_policy = asyncio.Event()
    allocate_result: dict[str, AllocationResult] = {}
    allocate_exc: dict[str, BaseException] = {}

    async def run_allocate() -> None:
        async with pg_session_factory() as session:
            real_policy = StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session))
            paused_policy: object = _PausingPolicyAfterSecondCall(
                real_policy, resume_allocate_policy
            )
            use_case = AllocateCapital(
                strategy_policy=paused_policy,  # type: ignore[arg-type]
                pool_balance=PoolBalanceAdapter(_POOL_CONFIG, _seeded_balance_source()),
                lock=PgAdvisoryLockAdapter(session),
                reservations=SqlAlchemyReservationRepository(session),
                commit=session,  # type: ignore[arg-type]
                clock=FixedClock(),  # type: ignore[arg-type]
                reservation_ttl_seconds=30,
                skip_recorder=RecordingSkipRecorder(),
            )
            try:
                allocate_result["value"] = await use_case.allocate(
                    AllocateCommand(
                        signal_id=signal_id,
                        strategy_id=strategy_id,
                        requested=Money(amount=REQUEST_AMOUNT, currency=Currency.USDT),
                    )
                )
            except BaseException as exc:  # noqa: BLE001 -- captured for the assertion below
                allocate_exc["value"] = exc

    task_allocate = asyncio.create_task(run_allocate())
    await asyncio.sleep(0.2)  # pre-lock read, advisory lock acquired, in-lock re-read
    # (still enabled=True) all done -- paused right before the INSERT.

    # Disabled only NOW, after the in-lock re-read already saw enabled=True
    # -- on a separate, already-committed connection.
    await _disable_strategy(pg_session_factory, strategy_id=strategy_id)

    archive_result: dict[str, object] = {}
    archive_exc: dict[str, BaseException] = {}

    async def run_archive() -> None:
        async with pg_session_factory() as session:
            use_case = _build_archive_strategy(session, PoolLockAdapter(session))
            try:
                archive_result["value"] = await use_case.archive(strategy_id)
            except BaseException as exc:  # noqa: BLE001 -- captured for the assertion below
                archive_exc["value"] = exc

    task_archive = asyncio.create_task(run_archive())
    await asyncio.sleep(0.3)  # with the fix, ArchiveStrategy is now genuinely blocked on
    # the advisory lock AllocateCapital holds -- it has not touched the row lock yet.
    assert not task_archive.done(), (
        "ArchiveStrategy completed without waiting for AllocateCapital's held "
        "advisory lock -- expected it to block on the pool lock BEFORE ever "
        "attempting the strategy row lock (lock-order-inversion regression)"
    )

    resume_allocate_policy.set()  # let AllocateCapital's INSERT + commit run
    await asyncio.gather(task_allocate, task_archive)

    assert "value" not in allocate_exc, (
        f"AllocateCapital raised unexpectedly (deadlock regression?): "
        f"{allocate_exc.get('value')!r}"
    )
    result = allocate_result["value"]
    assert result.reservation_id is not None  # its reservation committed

    # ArchiveStrategy MUST refuse -- AllocateCapital's reservation is live --
    # and it must refuse cleanly with OpenPosition, never a DeadlockDetected
    # (or any other) error, and never silently succeed.
    assert "value" not in archive_result, (
        "ArchiveStrategy archived a strategy that still holds a live "
        "reservation -- it should have refused with OpenPosition"
    )
    assert "value" in archive_exc, "ArchiveStrategy neither refused nor raised"
    assert isinstance(archive_exc["value"], OpenPosition), (
        f"ArchiveStrategy raised something other than a clean OpenPosition "
        f"(deadlock regression?): {archive_exc['value']!r}"
    )


def _seeded_balance_source() -> FakeBalanceSource:
    source = FakeBalanceSource()
    source.set_balance(*POOL, POOL_BALANCE)
    return source
