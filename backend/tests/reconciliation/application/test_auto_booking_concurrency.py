"""Tier B, design T6: the automatic step against a concurrent approver, on
real PostgreSQL (spec "Automatic Approval Takes Only The Proposal's Row Lock";
R13).

The lock-hold harness of ``test_approve_booking_integration.py`` (line 935)
races two approvals through a ``sleep(0)`` barrier. This file does not: the
first actor is a real ``ApproveBooking`` whose commit waits on an event the
TEST controls, so it holds the proposal's ``FOR UPDATE`` row lock, with its
attempt and ledger rows already written, for exactly as long as the test
wants. The automatic step then starts in a task, the test waits a bounded time,
asserts ``not task.done()``, and only then releases the first actor.

``_waits_on_the_row_lock`` is what makes the wait mean something: a task that
is merely slow, or that blocks LATER on the table's own CAS, is not waiting on
the row lock. It reads ``pg_stat_activity`` for a session that is waiting on a
lock inside a ``SELECT ... FOR UPDATE``.

Nothing here needs a credential, and the venue is not involved: the proposal is
frozen by hand, the way a sweep freezes it.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.reconciliation.application.approve_booking import ApproveOutcome
from strategy_manager.reconciliation.application.auto_book_pending import (
    AUTO_BOOKING_ACTOR,
    AutoBookPending,
    AutoBookResult,
)
from strategy_manager.reconciliation.application.ports import BookingProposalRecord
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
    _Row,
    _to_domain,
)
from tests.reconciliation.application.auto_booking_support import (
    build_approve_booking,
    insert_pending_proposal,
    proposals_of,
    reset_process_memory,
    seed_scenario,
    throwaway_database,
    write_counts,
)

pytestmark = pytest.mark.integration

_WAIT_SECONDS = 10.0
_BOUNDED_WAIT_SECONDS = 0.5


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from throwaway_database("strategy_manager_test_auto_booking_concurrency")


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def _clean(engine: AsyncEngine) -> AsyncIterator[None]:
    reset_process_memory()
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE reconciliation_discrepancies CASCADE"))


class _GatedCommit:
    """A commit that waits for the test before committing: the first actor
    keeps its row lock, with everything written, until ``release`` is set."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def commit(self) -> None:
        self.reached.set()
        await self.release.wait()
        await self._session.commit()


class _UnlockedProposals(SqlAlchemyBookingProposalRepository):
    """A copy of ``get_for_update`` WITHOUT ``with_for_update()``: the
    mutation the spec's "the wait is not vacuous" scenario names."""

    async def get_for_update(self, proposal_id: UUID) -> BookingProposalRecord:
        row = (
            await self._session.execute(
                select(_Row).where(_Row.id == proposal_id)  # no .with_for_update()
            )
        ).scalar_one()
        return _to_domain(row)


async def _await_event(event: asyncio.Event) -> None:
    await asyncio.wait_for(event.wait(), timeout=_WAIT_SECONDS)


async def _waits_on_the_row_lock(engine: AsyncEngine) -> bool:
    """Whether some session is, right now, waiting on a lock inside a
    ``SELECT ... FOR UPDATE``. Polls for a bounded time, so a slow start is
    not mistaken for the absence of the wait."""

    query = text(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() AND pid <> pg_backend_pid() "
        "AND wait_event_type = 'Lock' AND query ILIKE '%FOR UPDATE%'"
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 3.0
    while loop.time() < deadline:
        async with engine.connect() as conn:
            if (await conn.execute(query)).scalar_one() > 0:
                return True
        await asyncio.sleep(0.05)
    return False


async def _automatic_step(
    session_factory: async_sessionmaker[AsyncSession], *, unlocked: bool = False
) -> AutoBookResult:
    """One run of the automatic step on its own session, as a job runs it."""

    async with session_factory() as session:
        proposals: SqlAlchemyBookingProposalRepository = (
            _UnlockedProposals(session)
            if unlocked
            else SqlAlchemyBookingProposalRepository(session)
        )
        step = AutoBookPending(
            proposals=SqlAlchemyBookingProposalRepository(session),
            approver=build_approve_booking(session, proposals=proposals),
        )
        return await step.run()


async def _hold_the_lock_with_a_booking(
    session_factory: async_sessionmaker[AsyncSession], proposal: BookingProposalRecord
) -> tuple[asyncio.Task[Any], _GatedCommit, AsyncSession]:
    """Starts a real approval and returns once it has written everything and
    stands at its commit, still holding the proposal's row lock."""

    session = session_factory()
    gate = _GatedCommit(await session.__aenter__())
    approval = build_approve_booking(session, commit=gate)
    task = asyncio.create_task(approval.approve(proposal.id, decided_by="owner"))
    await _await_event(gate.reached)
    return task, gate, session


async def _finish(
    first: asyncio.Task[Any], gate: _GatedCommit, session: AsyncSession, *others: asyncio.Task[Any]
) -> None:
    gate.release.set()
    await asyncio.gather(first, *others, return_exceptions=True)
    await session.__aexit__(None, None, None)


async def test_the_automatic_step_waits_for_the_row_lock_then_answers_already_decided(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    scenario = await seed_scenario(session_factory)
    proposal = await insert_pending_proposal(session_factory, scenario)

    first, gate, first_session = await _hold_the_lock_with_a_booking(session_factory, proposal)
    try:
        task = asyncio.create_task(_automatic_step(session_factory))

        assert await _waits_on_the_row_lock(engine)
        done, _pending = await asyncio.wait({task}, timeout=_BOUNDED_WAIT_SECONDS)
        assert not task.done()
        assert not done

        # Nothing of the second actor is visible while the first holds the lock.
        assert await write_counts(session_factory, scenario.allocation_id) == (0, 0)

        gate.release.set()
        result = await asyncio.wait_for(task, timeout=_WAIT_SECONDS)
        await asyncio.wait_for(first, timeout=_WAIT_SECONDS)
    finally:
        await _finish(first, gate, first_session)

    assert dict(result.outcomes) == {ApproveOutcome.ALREADY_DECIDED.value: 1}
    assert result.approved == ()
    # Exactly one attempt row and its one ledger row: the first actor's.
    assert await write_counts(session_factory, scenario.allocation_id) == (1, 1)
    decided = await proposals_of(session_factory, scenario.discrepancy_id)
    assert [(state, by) for _, state, by in decided] == [("APPROVED", "owner")]


async def test_the_wait_assertion_fails_without_the_row_lock(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """The wait is not vacuous: against a copy of the call without
    ``with_for_update()`` the second actor is not waiting on a row lock."""

    scenario = await seed_scenario(session_factory)
    proposal = await insert_pending_proposal(session_factory, scenario)

    first, gate, first_session = await _hold_the_lock_with_a_booking(session_factory, proposal)
    task = asyncio.create_task(_automatic_step(session_factory, unlocked=True))
    try:
        assert not await _waits_on_the_row_lock(engine)
    finally:
        await _finish(first, gate, first_session, task)


async def test_two_concurrent_runs_do_not_double_book(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Two job runs over one PENDING proposal. Run A is held at its commit
    (its row lock taken, its rows written); run B has listed the same PENDING
    row and must wait, then find it decided."""

    scenario = await seed_scenario(session_factory)
    await insert_pending_proposal(session_factory, scenario)

    async with session_factory() as session_a:
        gate = _GatedCommit(session_a)
        run_a = asyncio.create_task(
            AutoBookPending(
                proposals=SqlAlchemyBookingProposalRepository(session_a),
                approver=build_approve_booking(session_a, commit=gate),
            ).run()
        )
        try:
            await _await_event(gate.reached)
            run_b = asyncio.create_task(_automatic_step(session_factory))
            try:
                assert await _waits_on_the_row_lock(engine)
                done, _pending = await asyncio.wait({run_b}, timeout=_BOUNDED_WAIT_SECONDS)
                assert not done
            finally:
                gate.release.set()
            results = await asyncio.wait_for(
                asyncio.gather(run_a, run_b), timeout=_WAIT_SECONDS * 3
            )
        finally:
            gate.release.set()
            await asyncio.gather(run_a, return_exceptions=True)

    result_a, result_b = results
    assert dict(result_a.outcomes) == {ApproveOutcome.APPROVED.value: 1}
    assert dict(result_b.outcomes) == {ApproveOutcome.ALREADY_DECIDED.value: 1}
    assert await write_counts(session_factory, scenario.allocation_id) == (1, 1)
    decided = await proposals_of(session_factory, scenario.discrepancy_id)
    assert [(state, by) for _, state, by in decided] == [("APPROVED", AUTO_BOOKING_ACTOR)]


async def test_no_advisory_lock_is_held_during_the_booking(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Design C3: a booking reads no availability and writes no reservation,
    so the pool's advisory lock is deliberately not taken and the lock order
    of CLAUDE.md ("pool advisory lock first, then row locks") has nothing to
    order. Read from ``pg_locks`` while a booking stands at its commit."""

    scenario = await seed_scenario(session_factory)
    proposal = await insert_pending_proposal(session_factory, scenario)

    session = session_factory()
    open_session = await session.__aenter__()
    gate = _GatedCommit(open_session)
    approval = build_approve_booking(open_session, commit=gate)
    task = asyncio.create_task(approval.approve(proposal.id, decided_by=AUTO_BOOKING_ACTOR))
    try:
        await _await_event(gate.reached)
        # The booking's own backend: the same session that is about to commit.
        pid = (await open_session.execute(text("SELECT pg_backend_pid()"))).scalar_one()

        async with engine.connect() as conn:
            advisory = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = :pid"
                    ),
                    {"pid": pid},
                )
            ).scalar_one()
            # The same read sees the row lock's transaction lock, so a zero
            # above means "none taken", not "this query sees nothing".
            transaction_locks = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM pg_locks WHERE locktype = 'transactionid' "
                        "AND granted AND pid = :pid"
                    ),
                    {"pid": pid},
                )
            ).scalar_one()
        assert transaction_locks >= 1
        assert advisory == 0
    finally:
        gate.release.set()
        await asyncio.gather(task, return_exceptions=True)
        await session.__aexit__(None, None, None)

    assert await write_counts(session_factory, scenario.allocation_id) == (1, 1)
