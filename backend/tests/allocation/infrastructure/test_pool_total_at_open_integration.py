"""Real-PostgreSQL proof that ``reservations.pool_total_at_open`` is the capital
each allocation saw INSIDE its own advisory lock (design.md section 10, finding
F1; tasks.md 3a.3).

**Deterministic, not scheduler luck.** The same lock-hold-open pattern as
``tests/strategies/application/test_archive_vs_allocate_concurrency.py``:
the first actor's commit is paused, so its transaction -- and the advisory lock
it took -- stays open after its in-lock balance read and its reservation
insert. The second actor is started against the SAME pool and the test asserts
it is still blocked (``not task.done()``) after a real wait. The pool's balance
is then changed on the shared source while the first actor still holds the
lock, so the second actor's in-lock read can only see the new value. A fake
lock would prove nothing here: advisory locks have no meaningful fake.

The value belongs to the reservation's OWN pool (CLAUDE.md rule 5): the two
reservations below are in ``pionex/spot/USDT``, and a third in a different
settlement-currency pool proves the value is that pool's, never a shared one
(rule 7: nothing sums it across pools).
"""

import asyncio
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
from strategy_manager.allocation.application.ports import AdvisoryLockPort
from strategy_manager.allocation.domain.decision import DecisionOutcome
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.allocation.fakes import AlwaysEnabledPool, RecordingSkipRecorder
from tests.allocation.infrastructure.conftest import seed_signal, seed_strategy

pytestmark = pytest.mark.integration

_POOLS = {
    ("pionex", "spot", "USDT"): PoolConfig(
        exchange=Exchange.PIONEX,
        venue=Venue.SPOT,
        settlement_currency=Currency.USDT,
        min_order_size=Decimal("1"),
    ),
    ("pionex", "coin-m", "BTC"): PoolConfig(
        exchange=Exchange.PIONEX,
        venue=Venue.COIN_M,
        settlement_currency=Currency.BTC,
        min_order_size=Decimal("0.0001"),
    ),
}


class _PausingCommit:
    """Signals that the transaction body is done (balance read, decision and
    insert all ran under the lock), then holds the commit -- and with it the
    advisory lock -- until told to resume."""

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


def _build(
    session: AsyncSession,
    source: FakeBalanceSource,
    commit: object,
    lock: AdvisoryLockPort | None = None,
) -> AllocateCapital:
    return AllocateCapital(
        strategy_policy=StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
        pool_balance=PoolBalanceAdapter(_POOLS, source),
        lock=lock or PgAdvisoryLockAdapter(session),
        reservations=SqlAlchemyReservationRepository(session),
        commit=commit,  # type: ignore[arg-type]
        clock=SystemClock(),
        reservation_ttl_seconds=30,
        skip_recorder=RecordingSkipRecorder(),
        pool_status=AlwaysEnabledPool(),
    )


async def _stored_total(
    factory: async_sessionmaker[AsyncSession], signal_id: UUID
) -> Decimal | None:
    async with factory() as session:
        row = (
            await session.execute(
                select(ReservationRow).where(ReservationRow.signal_id == signal_id)
            )
        ).scalar_one()
        return row.pool_total_at_open


async def _run_two_actors_on_one_pool(
    factory: async_sessionmaker[AsyncSession],
    *,
    second_lock: AdvisoryLockPort | None = None,
) -> tuple[UUID, UUID, AllocationResult, AllocationResult, bool]:
    """First actor reads 1000 in its lock and holds it; the pool then drops to
    900 on the shared source; the second actor allocates on the same pool.
    Returns both signal ids, both results, and whether the second actor was
    still blocked while the first held the lock."""

    strategy_id, first_signal, second_signal = uuid4(), uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await seed_signal(
        factory, signal_id=first_signal, strategy_id=strategy_id, idempotency_key="k1"
    )
    await seed_signal(
        factory, signal_id=second_signal, strategy_id=strategy_id, idempotency_key="k2"
    )

    source = FakeBalanceSource()
    source.set_balance("pionex", "spot", "USDT", Decimal("1000"))
    reached, resume = asyncio.Event(), asyncio.Event()
    resume_immediately = asyncio.Event()
    resume_immediately.set()

    async def first() -> AllocationResult:
        async with factory() as session:
            use_case = _build(session, source, _PausingCommit(session, reached, resume))
            return await use_case.allocate(
                AllocateCommand(
                    signal_id=first_signal,
                    strategy_id=strategy_id,
                    requested=Money(amount=Decimal("200"), currency=Currency.USDT),
                )
            )

    async def second() -> AllocationResult:
        async with factory() as session:
            use_case = _build(
                session,
                source,
                _PausingCommit(session, asyncio.Event(), resume_immediately),
                second_lock,
            )
            return await use_case.allocate(
                AllocateCommand(
                    signal_id=second_signal,
                    strategy_id=strategy_id,
                    requested=Money(amount=Decimal("200"), currency=Currency.USDT),
                )
            )

    task_first = asyncio.create_task(first())
    await asyncio.wait_for(reached.wait(), timeout=10)  # first holds the lock now

    source.set_balance("pionex", "spot", "USDT", Decimal("900"))
    task_second = asyncio.create_task(second())
    await asyncio.sleep(0.5)
    second_was_blocked = not task_second.done()

    resume.set()
    first_result = await asyncio.wait_for(task_first, timeout=10)
    second_result = await asyncio.wait_for(task_second, timeout=10)
    return first_signal, second_signal, first_result, second_result, second_was_blocked


async def test_pool_total_at_open_written_under_lock_survives_concurrent_allocation_on_same_pool(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_signal, second_signal, first, second, second_was_blocked = (
        await _run_two_actors_on_one_pool(pg_session_factory)
    )

    assert second_was_blocked  # the second actor genuinely waited on the pool lock
    assert first.outcome is DecisionOutcome.FULL
    assert second.outcome is DecisionOutcome.FULL
    # Each reservation stores the capital it saw INSIDE its own lock.
    assert await _stored_total(pg_session_factory, first_signal) == Decimal("1000")
    assert await _stored_total(pg_session_factory, second_signal) == Decimal("900")


async def test_second_actor_that_skips_the_lock_is_not_blocked_control(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Negative control for the wait assertion above: with a lock that does
    not lock, the second actor finishes while the first still holds its
    transaction open, so ``second_was_blocked`` would be False. This is what
    makes ``not task.done()`` above evidence of the advisory lock rather than
    of a slow test."""

    class _NoLock:
        async def acquire(self, key: object) -> None:
            return None

    _, _, _, _, second_was_blocked = await _run_two_actors_on_one_pool(
        pg_session_factory,
        second_lock=_NoLock(),  # type: ignore[arg-type]
    )

    assert not second_was_blocked


async def test_pool_total_at_open_is_the_capital_of_the_reservations_own_pool(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    usdt_strategy, btc_strategy = uuid4(), uuid4()
    usdt_signal, btc_signal = uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=usdt_strategy)
    await seed_strategy(
        pg_session_factory,
        strategy_id=btc_strategy,
        exchange="pionex",
        venue="coin-m",
        settlement_currency="BTC",
    )
    await seed_signal(
        pg_session_factory, signal_id=usdt_signal, strategy_id=usdt_strategy, idempotency_key="u"
    )
    await seed_signal(
        pg_session_factory, signal_id=btc_signal, strategy_id=btc_strategy, idempotency_key="b"
    )
    source = FakeBalanceSource()
    source.set_balance("pionex", "spot", "USDT", Decimal("1000"))
    source.set_balance("pionex", "coin-m", "BTC", Decimal("0.5"))

    async with pg_session_factory() as session:
        await _build(session, source, session).allocate(
            AllocateCommand(
                signal_id=usdt_signal,
                strategy_id=usdt_strategy,
                requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            )
        )
    async with pg_session_factory() as session:
        await _build(session, source, session).allocate(
            AllocateCommand(
                signal_id=btc_signal,
                strategy_id=btc_strategy,
                requested=Money(amount=Decimal("0.1"), currency=Currency.BTC),
            )
        )

    assert await _stored_total(pg_session_factory, usdt_signal) == Decimal("1000")
    assert await _stored_total(pg_session_factory, btc_signal) == Decimal("0.5")
