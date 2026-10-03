"""Real-PostgreSQL proof that ``DeleteStrategy`` serializes against every actor that
can change what it decided on (design.md addendum 9x, § D and § J; tasks.md 9xc.5;
``rules.tasks``: a lock has no meaningful fake).

Runs on a database migrated to ``head``: the strategy row's partner in every
property below is ``fk_signals_strategy``'s own ``FOR KEY SHARE``, and the ORM-built
test schema has no such foreign key, so on it the delete would not wait for anything
and the tests would pass or fail for the wrong reason.

**Lock-hold harness, never a ``sleep(0)`` barrier.** The first actor is PARKED on an
``asyncio.Event`` at a known point (``entered`` says it got there). The second actor
is started, and the test asserts ``not task.done()`` AND polls ``pg_locks`` until the
second shows as waiting on the lock in question, so "still pending" is never
mistaken for "not started yet". Ceilings (``_WAIT``) only stop a hung test.

**Non-vacuity, observed and not committed.**

- With ``fk_signals_strategy`` dropped from the test database, the delete no longer
  waits for the parked ingest (the signal ``INSERT`` takes no row lock then): the
  first test goes red.
- Taking the row lock before the pool lock makes the ``FOR UPDATE NOWAIT`` of
  ``test_delete_waits_on_the_pool_advisory_lock_and_holds_no_row_lock_meanwhile``
  raise ``LockNotAvailableError``; a ``PoolLockAdapter`` deriving another key makes
  the delete not wait at all.

Spelling across the boundary: the alert is ``STXUSDT.P``, the strategy allows
``STXUSDT``.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.signals.application.ingest_signal import IngestCommand, IngestSignal
from strategy_manager.signals.application.ports import UnknownSignalStrategy
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository
from strategy_manager.strategies.application.archive_strategy import ArchiveStrategy, StillEnabled
from strategy_manager.strategies.application.delete_strategy import (
    DeleteStrategy,
    StrategyHasHistory,
)
from strategy_manager.strategies.application.update_strategy import (
    UnknownStrategy,
    UpdateCommand,
    UpdateStrategy,
)
from strategy_manager.strategies.infrastructure.enablement_log import SqlAlchemyEnablementLog
from strategy_manager.strategies.infrastructure.exposure_adapter import StrategyExposureAdapter
from strategy_manager.strategies.infrastructure.history_adapter import StrategyHistoryAdapter
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.pg_head_schema import migrated_head_database

pytestmark = pytest.mark.integration

_POOL = ("bybit", "usdt-m", "USDT")
_WAIT = 5.0  # seconds; only ever a ceiling for a hung test, never a pacing delay

Factory = async_sessionmaker[AsyncSession]

# What ``pg_stat_activity.query`` shows for the statement each actor is blocked in.
_ROW_LOCK_OF_STRATEGIES = "%FROM strategies%FOR UPDATE%"
_SIGNAL_INSERT = "%INSERT INTO signals%"


@pytest.fixture(scope="module")
def head_database_url() -> Iterator[str]:
    with migrated_head_database("strategy_manager_test_delete_concurrency") as url:
        yield url


@pytest.fixture
async def engine(head_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(head_database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO capital_pools (exchange, venue, settlement_currency, min_order_size) "
                "VALUES ('bybit', 'usdt-m', 'USDT', 5) ON CONFLICT DO NOTHING"
            )
        )
    yield engine
    await engine.dispose()


@pytest.fixture
def factory(engine: AsyncEngine) -> Factory:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


class _PausingCommit:
    """Wraps a real session's ``commit()``. Both locks are released only by commit
    or rollback, so pausing it -- after every write already ran -- keeps them held
    across the whole body. ``entered`` is set when the actor reaches the pause."""

    def __init__(self, session: AsyncSession, entered: asyncio.Event, resume: asyncio.Event):
        self._session = session
        self._entered = entered
        self._resume = resume

    async def commit(self) -> None:
        self._entered.set()
        await self._resume.wait()
        await self._session.commit()


class _Gate:
    """One parked actor: ``entered`` once it holds its locks, ``resume`` to let it
    commit."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.resume = asyncio.Event()

    def commit_for(self, session: AsyncSession) -> _PausingCommit:
        return _PausingCommit(session, self.entered, self.resume)

    async def wait_until_parked(self, what: str) -> None:
        try:
            await asyncio.wait_for(self.entered.wait(), _WAIT)
        except TimeoutError:
            pytest.fail(f"{what} never reached its commit")


def _history(session: AsyncSession) -> StrategyHistoryAdapter:
    return StrategyHistoryAdapter(
        signals=SqlAlchemySignalRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        ledger=SqlAlchemyLedgerRepository(session),
        proposals=SqlAlchemyBookingProposalRepository(session),
        enablement_log=SqlAlchemyEnablementLog(session),
    )


def _delete_use_case(
    session: AsyncSession, *, commit: object | None = None, pool_lock: object | None = None
) -> DeleteStrategy:
    return DeleteStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        pool_lock=pool_lock if pool_lock is not None else PoolLockAdapter(session),  # type: ignore[arg-type]
        history=_history(session),
        commit=commit if commit is not None else session,  # type: ignore[arg-type]
    )


async def _seed_strategy(factory: Factory) -> UUID:
    strategy_id = uuid4()
    exchange, venue, currency = _POOL
    async with factory() as session:
        session.add(
            StrategyRow(
                id=strategy_id,
                name=f"strategy-{strategy_id}",
                exchange=exchange,
                venue=venue,
                settlement_currency=currency,
                enabled=False,
                fill_mode="PARTIAL",
                allowed_pairs=["STXUSDT"],
            )
        )
        await session.commit()
    return strategy_id


async def _scalar(factory: Factory, sql: str, **params: object) -> object:
    async with factory() as session:
        return await session.scalar(text(sql), params)


async def _strategies_named(factory: Factory, strategy_id: UUID) -> object:
    return await _scalar(factory, "SELECT count(*) FROM strategies WHERE id = :id", id=strategy_id)


async def _signals_of(factory: Factory, strategy_id: UUID) -> object:
    return await _scalar(
        factory, "SELECT count(*) FROM signals WHERE strategy_id = :id", id=strategy_id
    )


async def _outcome(session_factory: Factory, action: object) -> object:
    """Runs ``action(session)`` in a session of its own and returns what it raised
    (after rolling back, as the route does) or ``None``. A wrong exception then
    fails an assertion on its TYPE, not the harness."""
    async with session_factory() as session:
        try:
            await action(session)  # type: ignore[operator]
        except Exception as error:  # noqa: BLE001 -- captured for the assertions
            await session.rollback()
            return error
    return None


async def _wait_until_waiting(
    factory: Factory, *, locktypes: tuple[str, ...], query_like: str, what: str
) -> None:
    """Polls ``pg_locks`` until some other backend is blocked, not granted, on one
    of ``locktypes`` while running a statement that matches ``query_like``."""
    deadline = asyncio.get_running_loop().time() + _WAIT
    while True:
        waiting = await _scalar(
            factory,
            "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
            "WHERE NOT l.granted AND l.locktype = ANY(:locktypes) "
            "AND a.pid <> pg_backend_pid() AND a.query ILIKE :query_like",
            locktypes=list(locktypes),
            query_like=query_like,
        )
        if waiting:
            return
        assert asyncio.get_running_loop().time() < deadline, (
            f"{what} never showed as waiting in pg_locks"
        )
        await asyncio.sleep(0.05)


async def _wait_for_row_lock(factory: Factory, query_like: str, what: str) -> None:
    await _wait_until_waiting(
        factory, locktypes=("transactionid", "tuple"), query_like=query_like, what=what
    )


async def _wait_for_advisory_lock(factory: Factory, what: str) -> None:
    await _wait_until_waiting(
        factory, locktypes=("advisory",), query_like="%pg_advisory_xact_lock%", what=what
    )


@contextlib.asynccontextmanager
async def _reaping(
    gates: list[_Gate], tasks: "list[asyncio.Task[object]]", holder: AsyncSession | None = None
) -> AsyncIterator[None]:
    """Whatever the test does, let every parked actor go, release the holder's lock
    and reap the tasks, so a failed assertion fails the test instead of hanging it
    or leaving a transaction open. The holder goes first: a task blocked on its lock
    can only finish once the lock is gone."""
    try:
        yield
    finally:
        for gate in gates:
            gate.resume.set()
        if holder is not None:
            await holder.rollback()
        for task in tasks:
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(task, _WAIT)


def _command(strategy_id: UUID) -> IngestCommand:
    return IngestCommand(
        strategy_id=strategy_id,
        idempotency_key=f"bar-{uuid4()}",
        action="buy",
        contracts=Decimal("1"),
        position_size=Decimal("1"),
        price=Decimal("1"),
        symbol="STXUSDT.P",
        signal_type=str(strategy_id),
        raw_payload={},
    )


def _ingest(command: IngestCommand, gate: _Gate | None = None):  # type: ignore[no-untyped-def]
    async def run(session: AsyncSession) -> None:
        await IngestSignal(
            repository=SqlAlchemySignalRepository(session),
            job_queue=PostgresJobQueue(session),
            uow=gate.commit_for(session) if gate is not None else session,  # type: ignore[arg-type]
        ).ingest(command)

    return run


def _delete(strategy_id: UUID, gate: _Gate | None = None):  # type: ignore[no-untyped-def]
    async def run(session: AsyncSession) -> None:
        commit = gate.commit_for(session) if gate is not None else None
        await _delete_use_case(session, commit=commit).delete(strategy_id)

    return run


def _archive(session: AsyncSession) -> ArchiveStrategy:
    return ArchiveStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        pool_lock=PoolLockAdapter(session),
        exposure=StrategyExposureAdapter(
            ledger=SqlAlchemyLedgerRepository(session),
            symbol_holdings=ReadSymbolHoldings(SqlAlchemyLedgerRepository(session)),
            reservations=SqlAlchemyReservationRepository(session),
            attempts=SqlAlchemyExecutionAttemptRepository(session),
        ),
        commit=session,  # type: ignore[arg-type]
        clock=_FixedClock(),  # type: ignore[arg-type]
    )


async def test_delete_waits_for_a_signal_being_ingested_then_is_refused_with_one_signal(
    factory: Factory,
) -> None:
    """The ingest is parked before its commit, after its ``INSERT``: that ``INSERT``
    holds ``FOR KEY SHARE`` on the strategy row through ``fk_signals_strategy``. The
    delete must WAIT for it, then re-read and count the signal."""
    strategy_id = await _seed_strategy(factory)
    ingest = _Gate()
    ingest_task = asyncio.create_task(_outcome(factory, _ingest(_command(strategy_id), ingest)))
    async with _reaping([ingest], [ingest_task]):
        await ingest.wait_until_parked("the ingest")

        delete_task = asyncio.create_task(_outcome(factory, _delete(strategy_id)))
        await _wait_for_row_lock(factory, _ROW_LOCK_OF_STRATEGIES, "the delete")
        assert not delete_task.done(), "the delete did not wait for the ingest"

        ingest.resume.set()
        assert await asyncio.wait_for(ingest_task, _WAIT) is None
        refusal = await asyncio.wait_for(delete_task, _WAIT)

    assert isinstance(refusal, StrategyHasHistory), repr(refusal)
    assert refusal.history.blocking() == {"signals": 1}
    assert refusal.constraint is None  # the count caught it, the foreign key was not needed
    assert await _strategies_named(factory, strategy_id) == 1
    assert await _signals_of(factory, strategy_id) == 1


async def test_a_signal_waits_for_a_delete_in_flight_then_is_refused_and_nothing_is_persisted(
    factory: Factory,
) -> None:
    """The delete is parked before its commit, after its ``DELETE``. The ingest's
    ``INSERT`` needs ``FOR KEY SHARE`` on the row the delete removed, so it waits for
    the delete, then fails on the foreign key and is refused."""
    strategy_id = await _seed_strategy(factory)
    jobs_before = await _scalar(factory, "SELECT count(*) FROM jobs")
    delete = _Gate()
    delete_task = asyncio.create_task(_outcome(factory, _delete(strategy_id, delete)))
    async with _reaping([delete], [delete_task]):
        await delete.wait_until_parked("the delete")

        ingest_task = asyncio.create_task(_outcome(factory, _ingest(_command(strategy_id))))
        async with _reaping([], [ingest_task]):
            await _wait_for_row_lock(factory, _SIGNAL_INSERT, "the ingest")
            assert not ingest_task.done(), "the ingest did not wait for the delete"

            delete.resume.set()
            assert await asyncio.wait_for(delete_task, _WAIT) is None
            refusal = await asyncio.wait_for(ingest_task, _WAIT)

    assert isinstance(refusal, UnknownSignalStrategy), repr(refusal)
    assert await _strategies_named(factory, strategy_id) == 0
    assert await _signals_of(factory, strategy_id) == 0
    assert await _scalar(factory, "SELECT count(*) FROM jobs") == jobs_before


async def test_delete_waits_on_the_pool_advisory_lock_and_holds_no_row_lock_meanwhile(
    factory: Factory,
) -> None:
    """A holder takes the advisory lock of ``bybit/usdt-m/USDT`` through allocation's
    own adapter. The delete must wait on an ``advisory`` lock, and while it does it
    holds NO row lock: a third connection takes the strategy row with ``NOWAIT`` and
    succeeds. That is the lock order (pool lock first, row lock second) on PostgreSQL;
    a delete that took the row first would make the ``NOWAIT`` raise."""
    strategy_id = await _seed_strategy(factory)
    exchange, venue, currency = _POOL
    pool_key = PoolKey(Exchange(exchange), Venue(venue), Currency(currency))

    async with factory() as holder:
        await PgAdvisoryLockAdapter(holder).acquire(LockKey.from_pool_key(pool_key))

        delete_task = asyncio.create_task(_outcome(factory, _delete(strategy_id)))
        async with _reaping([], [delete_task], holder):
            await _wait_for_advisory_lock(factory, "the delete")
            assert not delete_task.done(), "the delete completed without the pool lock"

            async with factory() as third:
                try:
                    await third.execute(
                        text("SELECT id FROM strategies WHERE id = :id FOR UPDATE NOWAIT"),
                        {"id": strategy_id},
                    )
                except DBAPIError as error:  # pragma: no cover - only on a regression
                    pytest.fail(f"the delete held the row lock while waiting: {error!r}")
                await third.rollback()

            await holder.rollback()  # releases the pool lock
            assert await asyncio.wait_for(delete_task, _WAIT) is None

    assert await _strategies_named(factory, strategy_id) == 0


async def test_delete_waits_for_an_enable_in_flight_then_is_refused_still_enabled(
    factory: Factory,
) -> None:
    """An ``UpdateStrategy`` enabling the strategy is parked before its commit,
    holding the row lock. The delete waits for it, re-reads ``enabled = true`` under
    the lock and is refused: the unlocked read could not have seen it."""
    strategy_id = await _seed_strategy(factory)
    enable = _Gate()

    async def run_enable(session: AsyncSession) -> None:
        await UpdateStrategy(
            repository=SqlAlchemyStrategyRepository(session),
            commit=enable.commit_for(session),  # type: ignore[arg-type]
            enablement_log=SqlAlchemyEnablementLog(session),
            clock=_FixedClock(),  # type: ignore[arg-type]
        ).update(UpdateCommand(strategy_id=strategy_id, enabled=True))

    enable_task = asyncio.create_task(_outcome(factory, run_enable))
    async with _reaping([enable], [enable_task]):
        await enable.wait_until_parked("the enable")

        delete_task = asyncio.create_task(_outcome(factory, _delete(strategy_id)))
        async with _reaping([], [delete_task]):
            await _wait_for_row_lock(factory, _ROW_LOCK_OF_STRATEGIES, "the delete")
            assert not delete_task.done(), "the delete did not wait for the enable"

            enable.resume.set()
            assert await asyncio.wait_for(enable_task, _WAIT) is None
            refusal = await asyncio.wait_for(delete_task, _WAIT)

    assert isinstance(refusal, StillEnabled), repr(refusal)
    still = await _scalar(factory, "SELECT enabled FROM strategies WHERE id = :id", id=strategy_id)
    assert still is True


async def test_an_archive_waiting_behind_a_delete_answers_unknown_strategy(
    factory: Factory,
) -> None:
    """The delete is parked before its commit, holding the pool lock. The archive
    read the row unlocked (still there), then waits for the same pool lock. When the
    delete commits, the archive's locked read finds no row and answers 404 -- the
    branch that used to be marked unreachable."""
    strategy_id = await _seed_strategy(factory)
    delete = _Gate()
    delete_task = asyncio.create_task(_outcome(factory, _delete(strategy_id, delete)))
    async with _reaping([delete], [delete_task]):
        await delete.wait_until_parked("the delete")

        async def run_archive(session: AsyncSession) -> None:
            await _archive(session).archive(strategy_id)

        archive_task = asyncio.create_task(_outcome(factory, run_archive))
        async with _reaping([], [archive_task]):
            await _wait_for_advisory_lock(factory, "the archive")
            assert not archive_task.done(), "the archive completed without waiting for the delete"

            delete.resume.set()
            assert await asyncio.wait_for(delete_task, _WAIT) is None
            refusal = await asyncio.wait_for(archive_task, _WAIT)

    assert isinstance(refusal, UnknownStrategy), repr(refusal)


async def test_two_concurrent_deletes_delete_once_and_the_second_answers_unknown_strategy(
    factory: Factory,
) -> None:
    strategy_id = await _seed_strategy(factory)
    first = _Gate()
    first_task = asyncio.create_task(_outcome(factory, _delete(strategy_id, first)))
    async with _reaping([first], [first_task]):
        await first.wait_until_parked("the first delete")

        second_task = asyncio.create_task(_outcome(factory, _delete(strategy_id)))
        async with _reaping([], [second_task]):
            await _wait_for_advisory_lock(factory, "the second delete")
            assert not second_task.done(), "the second delete did not wait"

            first.resume.set()
            first_outcome = await asyncio.wait_for(first_task, _WAIT)
            second_outcome = await asyncio.wait_for(second_task, _WAIT)

    assert first_outcome is None
    assert isinstance(second_outcome, UnknownStrategy), repr(second_outcome)
    assert await _strategies_named(factory, strategy_id) == 0
