"""``DeleteCredential`` against real PostgreSQL (tasks.md 6e.1-6e.5; owner
decisions 22 and 31; design.md § 4b).

The REAL vault rows, the REAL exposure adapter and the REAL pool lock are wired,
not fakes: the point is that the exposure query and the lock key derivation are
correct against a real schema, and that the lock genuinely serializes against
``AllocateCapital`` (``rules.tasks``: an advisory lock has no meaningful fake).

**Deterministic, not scheduler-luck.** Every "the second actor waits" assertion
follows the lock-hold harness of ``test_archive_vs_allocate_concurrency.py``: the
holder pauses INSIDE its transaction on an ``asyncio.Event`` while Postgres has
granted it the lock, and the test then polls ``pg_locks`` until the other actor
shows as a WAITING advisory lock (proof it is blocked on the lock itself, not
merely slow) and asserts ``not task.done()``. A barrier with ``sleep(0)`` passed
against unlocked code once and is not used.
"""

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.delete_credential import (
    DeleteCredential,
    ExchangeNotFlat,
    NoActiveCredential,
)
from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.application.save_credential import SaveCredential, Saved
from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential, KeyFacts
from strategy_manager.accounts.domain.key_policy import OwnerConfirmations
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.capital_pool_writer import (
    SqlAlchemyCapitalPoolWriter,
)
from strategy_manager.accounts.infrastructure.credential_revoker import (
    SqlAlchemyCredentialRevoker,
)
from strategy_manager.accounts.infrastructure.credential_vault import SqlAlchemyCredentialVault
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.accounts.infrastructure.models import (  # noqa: F401
    CapitalPoolRow,
    ExchangeCredentialRow,
)
from strategy_manager.accounts.infrastructure.pool_exposure_adapter import PoolExposureAdapter
from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
    AllocationResult,
)
from strategy_manager.allocation.application.ports import StrategyPolicySnapshot
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.ledger.domain.ledger_entry import LedgerEntry
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.shared.infrastructure.crypto import MASTER_KEY_BYTES, EnvelopeCipher
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.accounts.fakes import (
    BYBIT_KEY,
    BYBIT_SECRET,
    TRADING_SNAPSHOT,
    RecordingInspector,
    TickingClock,
    registry_for,
)
from tests.accounts.pool_seed import (
    POOL,
    seed_execution_attempt,
    seed_live_reservation,
    seed_open_position,
    seed_signal,
    seed_strategy,
    set_strategy_enabled,
)
from tests.allocation.fakes import AlwaysEnabledPool, RecordingSkipRecorder
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)

pytestmark = pytest.mark.integration

FIXED_NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
REQUEST_AMOUNT = Decimal("200")
POOL_BALANCE = Decimal("1000")
WAIT_SECONDS = 5.0

_POOL_CONFIG = {
    POOL: PoolConfig(
        exchange=Exchange.BYBIT,
        venue=Venue.USDT_M,
        settlement_currency=Currency.USDT,
        min_order_size=Decimal("1"),
    )
}


class FixedClock:
    def now(self) -> datetime:
        return FIXED_NOW


@pytest.fixture
async def factory(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> async_sessionmaker[AsyncSession]:
    """The test database with no credential rows left by another test."""
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE exchange_credentials CASCADE"))
        await session.commit()
    return pg_session_factory


def _cipher() -> EnvelopeCipher:
    return EnvelopeCipher(os.urandom(MASTER_KEY_BYTES))


async def _store_key(
    factory: async_sessionmaker[AsyncSession], exchange: str = "bybit"
) -> None:
    async with factory() as session:
        await SqlAlchemyCredentialVault(session, _cipher(), TickingClock()).store(
            ExchangeCredential(
                exchange=exchange, label="default", api_key=BYBIT_KEY, api_secret=BYBIT_SECRET
            ),
            KeyFacts.unrecorded(trade_capable=True),
        )
        await session.commit()


async def _credential_flags(
    factory: async_sessionmaker[AsyncSession], exchange: str = "bybit"
) -> list[bool]:
    async with factory() as session:
        rows = await session.execute(
            text(
                "SELECT is_active FROM exchange_credentials WHERE exchange = :e "
                "ORDER BY created_at, id"
            ),
            {"e": exchange},
        )
        return [row[0] for row in rows.all()]


async def _pool_enabled(
    factory: async_sessionmaker[AsyncSession], exchange: str = "bybit"
) -> bool:
    async with factory() as session:
        return bool(
            (
                await session.execute(
                    text("SELECT enabled FROM capital_pools WHERE exchange = :e"),
                    {"e": exchange},
                )
            ).scalar_one()
        )


async def _strategy(
    factory: async_sessionmaker[AsyncSession], *, enabled: bool = False
) -> UUID:
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id, enabled=enabled)
    return strategy_id


def _build(
    session: AsyncSession,
    *,
    pool_lock: Any = None,
    commit: Any = None,
) -> DeleteCredential:
    return DeleteCredential(
        SqlAlchemyCredentialRevoker(session, FixedClock()),
        pool_lock if pool_lock is not None else PoolLockAdapter(session),
        PoolExposureAdapter.over(session),
        SqlAlchemyCapitalPoolWriter(session),
        commit if commit is not None else session,
    )


async def _delete(factory: async_sessionmaker[AsyncSession], exchange: str = "bybit") -> Any:
    async with factory() as session:
        return await _build(session).execute(exchange)


# --- 6e.1, 6e.2: refusals ------------------------------------------------------------------


async def test_deletion_refused_while_enabled_strategy_exists_names_it_409(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _store_key(factory)
    strategy_id = await _strategy(factory, enabled=True)

    with pytest.raises(ExchangeNotFlat) as caught:
        await _delete(factory)

    exposure = caught.value.exposure
    assert [(s.id, s.name) for s in exposure.enabled_strategies] == [
        (strategy_id, f"strategy-{strategy_id}")
    ]
    assert await _credential_flags(factory) == [True]
    assert await _pool_enabled(factory) is True


async def test_deletion_refused_while_open_exposure_exists_names_symbols_allocations_reservations_attempts_409(  # noqa: E501
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _store_key(factory)
    holder = await _strategy(factory)
    reserver = await _strategy(factory)
    submitter = await _strategy(factory)
    allocation = await seed_open_position(factory, strategy_id=holder, symbol="ETHUSDT")
    reservation = await seed_live_reservation(factory, strategy_id=reserver)
    submitted = await seed_live_reservation(factory, strategy_id=submitter, status="SUBMITTED")
    attempt = uuid4()
    await seed_execution_attempt(factory, attempt_id=attempt, reservation_id=submitted)

    with pytest.raises(ExchangeNotFlat) as caught:
        await _delete(factory)

    exposure = caught.value.exposure
    assert exposure.enabled_strategies == ()
    assert exposure.symbols == frozenset({"ETHUSDT"})
    assert exposure.allocations == (allocation,)
    assert set(exposure.live_reservations) == {reservation, submitted}
    assert exposure.in_flight_attempts == (attempt,)
    assert await _credential_flags(factory) == [True]
    assert await _pool_enabled(factory) is True


@pytest.mark.parametrize("kind", ["position", "reservation", "attempt"])
async def test_each_kind_of_exposure_alone_blocks_deletion(
    factory: async_sessionmaker[AsyncSession], kind: str
) -> None:
    await _store_key(factory)
    strategy_id = await _strategy(factory)
    if kind == "position":
        await seed_open_position(factory, strategy_id=strategy_id, symbol="ETHUSDT")
    elif kind == "reservation":
        await seed_live_reservation(factory, strategy_id=strategy_id)
    else:
        reservation = await seed_live_reservation(
            factory, strategy_id=strategy_id, status="SUBMITTED"
        )
        await seed_execution_attempt(factory, attempt_id=uuid4(), reservation_id=reservation)

    with pytest.raises(ExchangeNotFlat):
        await _delete(factory)

    assert await _credential_flags(factory) == [True]


async def test_no_active_credential_raises_and_leaves_the_pool_enabled(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(NoActiveCredential):
        await _delete(factory)

    assert await _pool_enabled(factory) is True


async def test_a_second_deletion_finds_no_active_credential(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _store_key(factory)
    await _delete(factory)

    with pytest.raises(NoActiveCredential):
        await _delete(factory)


# --- 6e.3: success, one transaction ---------------------------------------------------------


class _SpyCommit:
    """Looks at the database from ANOTHER connection at the instant of the commit,
    then commits: what a concurrent reader sees just before the transaction ends."""

    def __init__(
        self, session: AsyncSession, factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self._session = session
        self._factory = factory
        self.seen_before: tuple[list[bool], bool] | None = None

    async def commit(self) -> None:
        self.seen_before = (
            await _credential_flags(self._factory),
            await _pool_enabled(self._factory),
        )
        await self._session.commit()


async def test_deletion_succeeds_when_flat_deactivates_credential_disables_pool_same_transaction(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _store_key(factory)
    disabled_strategy = await _strategy(factory)
    closed = await seed_open_position(factory, strategy_id=disabled_strategy, symbol="ETHUSDT")
    await _close(factory, disabled_strategy, closed, "ETHUSDT")

    async with factory() as session:
        spy = _SpyCommit(session, factory)
        result = await _build(session, commit=spy).execute("bybit")

    assert result.exchange == "bybit"
    assert result.last4 == BYBIT_KEY[-4:]
    assert result.pool_disabled is True
    # One transaction: nothing was visible to anyone else before the commit...
    assert spy.seen_before == ([True], True)
    # ...and both writes are there after it. The row is kept, not removed.
    assert await _credential_flags(factory) == [False]
    assert await _pool_enabled(factory) is False


async def test_a_failing_pool_write_rolls_the_credential_deactivation_back(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _store_key(factory)

    class _ExplodingPools:
        async def enable(self, exchange: str) -> bool:
            raise AssertionError

        async def disable(self, exchange: str) -> bool:
            raise RuntimeError("pool write failed")

    async with factory() as session:
        use_case = DeleteCredential(
            SqlAlchemyCredentialRevoker(session, FixedClock()),
            PoolLockAdapter(session),
            PoolExposureAdapter.over(session),
            _ExplodingPools(),
            session,
        )
        with pytest.raises(RuntimeError):
            await use_case.execute("bybit")

    assert await _credential_flags(factory) == [True]
    assert await _pool_enabled(factory) is True


async def test_the_deleted_row_is_kept_inactive_and_the_history_is_untouched(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _store_key(factory)  # the old key
    await _store_key(factory)  # a rotation: the old one is now inactive history

    await _delete(factory)

    assert await _credential_flags(factory) == [False, False]


async def _close(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    allocation_id: UUID,
    symbol: str,
) -> None:
    """A SELL of the same quantity on the same allocation: nets it to zero."""
    attempt_id = uuid4()
    await seed_execution_attempt(
        factory,
        attempt_id=attempt_id,
        closes_allocation_id=allocation_id,
        symbol=symbol,
        status="FILLED",
        exchange_order_id=f"ord-{attempt_id}",
    )
    async with factory() as session:
        await SqlAlchemyLedgerRepository(session).insert(
            LedgerEntry(
                id=uuid4(),
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                execution_attempt_id=attempt_id,
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                symbol=symbol,
                side="SELL",
                quantity=Decimal("1"),
                price=Decimal("1"),
                fee=Decimal("0"),
                fee_currency=POOL[2],
                notional=Decimal("1"),
                exchange_order_id=f"ord-{attempt_id}",
                exchange_fill_id=f"fill-{attempt_id}",
                filled_at=FIXED_NOW,
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()


# --- 6e.5: rotation never runs the precondition ---------------------------------------------


async def test_replacing_a_key_rotation_never_runs_this_precondition_even_with_enabled_strategy_and_open_position(  # noqa: E501
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _store_key(factory)
    strategy_id = await _strategy(factory, enabled=True)
    await seed_open_position(factory, strategy_id=strategy_id, symbol="ETHUSDT")
    await seed_live_reservation(factory, strategy_id=strategy_id)

    async with factory() as session:
        clock = TickingClock()
        result = await SaveCredential(
            registry_for(RecordingInspector(TRADING_SNAPSHOT)),
            SqlAlchemyCredentialVault(session, _cipher(), clock),
            SqlAlchemyCapitalPoolWriter(session),
            session,
            clock,
        ).execute(
            ExchangeCredential(
                exchange="bybit", label="default", api_key=BYBIT_KEY, api_secret=BYBIT_SECRET
            ),
            OwnerConfirmations(),
        )

    assert isinstance(result, Saved)
    assert await _credential_flags(factory) == [False, True]
    assert await _pool_enabled(factory) is True


# --- 6e.10: lock order ----------------------------------------------------------------------


async def _advisory_counts(factory: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    """``(granted, waiting)`` advisory locks, straight from ``pg_locks``."""
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT count(*) FILTER (WHERE granted), count(*) FILTER (WHERE NOT granted) "
                    "FROM pg_locks WHERE locktype = 'advisory'"
                )
            )
        ).one()
        return int(row[0]), int(row[1])


async def _until(
    condition: Callable[[], Awaitable[bool]], what: str, timeout: float = WAIT_SECONDS
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not await condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.02)


async def _a_waiter_is_blocked_on_the_advisory_lock(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async def waiting() -> bool:
        return (await _advisory_counts(factory))[1] >= 1

    await _until(waiting, "an actor to wait on the advisory lock")


async def test_deletion_takes_the_pool_lock_before_the_row_lock_so_a_waiting_delete_holds_no_row(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """Tasks.md 6e.10 listed ``SELECT ... FOR UPDATE`` first; CLAUDE.md's rule is
    the pool advisory lock first, row locks after. While another transaction holds
    the pool lock, a delete must wait on it WITHOUT having locked the credential
    row: a third connection takes that row with ``FOR UPDATE NOWAIT`` and gets it.
    Reversed, the delete would already hold the row and ``NOWAIT`` would raise."""
    await _store_key(factory)

    holder = factory()
    async with holder as held:
        await PoolLockAdapter(held).acquire(*POOL)
        task = asyncio.create_task(_delete(factory))
        await _a_waiter_is_blocked_on_the_advisory_lock(factory)
        assert not task.done()

        async with factory() as probe:
            row = await probe.execute(
                text(
                    "SELECT id FROM exchange_credentials "
                    "WHERE exchange = 'bybit' AND is_active FOR UPDATE NOWAIT"
                )
            )
            assert row.first() is not None
            await probe.rollback()
        await held.rollback()  # releases the pool lock

    result = await asyncio.wait_for(task, WAIT_SECONDS)
    assert result.exchange == "bybit"


# --- 6e.4: the concurrency with AllocateCapital, both orderings ----------------------------


class _HoldingCommit:
    """Holds a transaction (and its advisory lock) open by pausing its commit, once
    the whole body, including the reservation INSERT, has run."""

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


class _HoldingPoolLock:
    """Takes the real pool lock, then holds it: the transaction stays open until
    ``resume`` is set."""

    def __init__(self, inner: PoolLockAdapter, acquired: asyncio.Event, resume: asyncio.Event):
        self._inner = inner
        self._acquired = acquired
        self._resume = resume

    async def acquire(self, exchange: str, venue: str, settlement_currency: str) -> None:
        await self._inner.acquire(exchange, venue, settlement_currency)
        self._acquired.set()
        await self._resume.wait()


class _PausingPolicyAfterFirstCall:
    """Pauses ``AllocateCapital`` after its PRE-lock policy read (which must still
    see ``enabled=True``) and before it reaches the lock. The in-lock re-read, the
    second call, is never paused."""

    def __init__(self, inner: StrategyPolicyAdapter, resume: asyncio.Event) -> None:
        self._inner = inner
        self._resume = resume
        self.calls = 0

    async def policy_for(self, strategy_id: UUID) -> StrategyPolicySnapshot:
        result = await self._inner.policy_for(strategy_id)
        self.calls += 1
        if self.calls == 1:
            await self._resume.wait()
        return result


def _balance_source() -> FakeBalanceSource:
    source = FakeBalanceSource()
    source.set_balance(*POOL, POOL_BALANCE)
    return source


def _allocate_command(signal_id: UUID, strategy_id: UUID) -> AllocateCommand:
    return AllocateCommand(
        signal_id=signal_id,
        strategy_id=strategy_id,
        requested=Money(amount=REQUEST_AMOUNT, currency=Currency.USDT),
    )


def _allocator(session: AsyncSession, policy: Any, commit: Any) -> AllocateCapital:
    return AllocateCapital(
        strategy_policy=policy,
        pool_balance=PoolBalanceAdapter(_POOL_CONFIG, _balance_source()),
        lock=PgAdvisoryLockAdapter(session),
        reservations=SqlAlchemyReservationRepository(session),
        commit=commit,
        clock=FixedClock(),  # type: ignore[arg-type]
        reservation_ttl_seconds=30,
        skip_recorder=RecordingSkipRecorder(),
        pool_status=AlwaysEnabledPool(),
    )


async def _reservation_count(
    factory: async_sessionmaker[AsyncSession], strategy_id: UUID
) -> int:
    async with factory() as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM reservations WHERE strategy_id = :s"),
                    {"s": strategy_id},
                )
            ).scalar_one()
        )


async def test_concurrent_allocation_and_deletion_on_same_pool_serialized_by_advisory_lock_allocation_first(  # noqa: E501
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """The allocation reaches the pool lock first and runs its whole body, then
    holds the lock open by pausing its commit. The strategy is disabled only NOW
    (after the allocation's in-lock re-read saw ``enabled=True``), so the key is
    deletable as far as the strategy rows go. The delete must genuinely WAIT on the
    advisory lock, and once the allocation commits it must see that reservation and
    refuse. Nothing but the reservation is left to block it, so the refusal proves
    the exposure was read AFTER the allocation's commit."""
    await _store_key(factory)
    strategy_id = await _strategy(factory, enabled=True)
    signal_id = uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )

    reached = asyncio.Event()
    resume_allocation = asyncio.Event()
    allocated: dict[str, AllocationResult] = {}

    async def run_allocation() -> None:
        async with factory() as session:
            use_case = _allocator(
                session,
                StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
                _HoldingCommit(session, reached, resume_allocation),
            )
            allocated["value"] = await use_case.allocate(_allocate_command(signal_id, strategy_id))

    task_allocation = asyncio.create_task(run_allocation())
    await asyncio.wait_for(reached.wait(), WAIT_SECONDS)
    assert (await _advisory_counts(factory))[0] >= 1  # the allocation holds the pool lock

    await set_strategy_enabled(factory, strategy_id, False)

    deleted: dict[str, Any] = {}
    failed: dict[str, BaseException] = {}

    async def run_delete() -> None:
        async with factory() as session:
            try:
                deleted["value"] = await _build(session).execute("bybit")
            except BaseException as exc:  # noqa: BLE001 -- captured for the assertion
                failed["value"] = exc

    task_delete = asyncio.create_task(run_delete())
    await _a_waiter_is_blocked_on_the_advisory_lock(factory)
    assert not task_delete.done(), (
        "DeleteCredential completed without waiting for AllocateCapital's held pool "
        "lock: the two are not serializing on the same key"
    )

    resume_allocation.set()
    await asyncio.wait_for(asyncio.gather(task_allocation, task_delete), WAIT_SECONDS)

    result = allocated["value"]
    assert result.reservation_id is not None
    assert "value" not in deleted, "the key was deleted under a live reservation"
    error = failed["value"]
    assert isinstance(error, ExchangeNotFlat), repr(error)
    assert error.exposure.enabled_strategies == ()
    assert error.exposure.live_reservations == (result.reservation_id,)
    assert await _credential_flags(factory) == [True]
    assert await _pool_enabled(factory) is True


async def test_concurrent_allocation_and_deletion_on_same_pool_serialized_by_advisory_lock_deletion_first(  # noqa: E501
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """The mirror: the delete reaches the lock first and holds it. The allocation's
    pre-lock read (paused) still saw ``enabled=True``; the strategy is disabled
    after it, which is the precondition that lets the delete through. The
    allocation must genuinely WAIT on the same lock, and once the delete commits,
    its in-lock re-read sees the strategy disabled: it skips and reserves nothing.
    The key is gone and the pool is disabled by then."""
    await _store_key(factory)
    strategy_id = await _strategy(factory, enabled=True)
    signal_id = uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )

    resume_policy = asyncio.Event()
    allocated: dict[str, AllocationResult] = {}

    async def run_allocation() -> None:
        async with factory() as session:
            policy = _PausingPolicyAfterFirstCall(
                StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)), resume_policy
            )
            use_case = _allocator(session, policy, session)
            allocated["value"] = await use_case.allocate(_allocate_command(signal_id, strategy_id))

    task_allocation = asyncio.create_task(run_allocation())
    await _until(_policy_read_happened(factory), "the allocation's pre-lock read")
    await set_strategy_enabled(factory, strategy_id, False)

    acquired = asyncio.Event()
    resume_delete = asyncio.Event()
    deleted: dict[str, Any] = {}

    async def run_delete() -> None:
        async with factory() as session:
            lock = _HoldingPoolLock(PoolLockAdapter(session), acquired, resume_delete)
            deleted["value"] = await _build(session, pool_lock=lock).execute("bybit")

    task_delete = asyncio.create_task(run_delete())
    await asyncio.wait_for(acquired.wait(), WAIT_SECONDS)  # the delete holds the pool lock

    resume_policy.set()  # the allocation now heads for the SAME lock
    await _a_waiter_is_blocked_on_the_advisory_lock(factory)
    assert not task_allocation.done(), (
        "AllocateCapital completed without waiting for DeleteCredential's held pool "
        "lock: the two are not serializing on the same key"
    )

    resume_delete.set()
    await asyncio.wait_for(asyncio.gather(task_allocation, task_delete), WAIT_SECONDS)

    assert deleted["value"].pool_disabled is True
    result = allocated["value"]
    assert result.outcome.value == "SKIP"
    assert result.skip_reason == "STRATEGY_DISABLED"
    assert result.reservation_id is None
    assert await _reservation_count(factory, strategy_id) == 0
    assert await _credential_flags(factory) == [False]
    assert await _pool_enabled(factory) is False


def _policy_read_happened(
    factory: async_sessionmaker[AsyncSession],
) -> Callable[[], Awaitable[bool]]:
    """The allocation's pre-lock read is a plain SELECT on ``strategies`` with no
    lock, so nothing in ``pg_locks`` marks it; a short, bounded settle is the
    honest signal that it reached its pause. The ordering it protects is asserted
    from the database afterwards, not from this wait."""

    async def settled() -> bool:
        await asyncio.sleep(0.2)
        return True

    return settled


async def test_the_lock_hold_harness_would_notice_an_unlocked_delete(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """Self-check of the harness: with no pool lock held by anyone, a delete
    finishes at once, so ``not task.done()`` in the tests above is caused by the
    lock and not by a slow path."""
    await _store_key(factory)

    result = await asyncio.wait_for(_delete(factory), WAIT_SECONDS)

    assert result.exchange == "bybit"
    assert (await _advisory_counts(factory)) == (0, 0)
