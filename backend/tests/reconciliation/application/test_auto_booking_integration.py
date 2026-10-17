"""Tier B, design T5: the whole automatic path on real PostgreSQL.

A CONFIRMED discrepancy, a fake venue fill reader and one ``reconciliation.
prepare_booking`` job: the handler expires, sweeps, books on its own, announces
and enqueues its successor, with the object graph ``main.py`` builds (owner
decision 66 Q1, 2026-10-16; spec "Approval Is Automatic and
Freshness-Checked", "Approved Booking Clears the Existing-Position Guard").

Symbols follow R21: the ledger's open fill is ``STXUSDT.P``, the discrepancy
row and the venue's fills are ``STXUSDT``. No test needs a credential and the
handler runs with ``dry_run=False`` only because the venue is a fake.
"""

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.reconciliation.application.auto_book_pending import AUTO_BOOKING_ACTOR
from strategy_manager.reconciliation.application.booking_prepare_handler import (
    last_reason_by_discrepancy,
)
from strategy_manager.reconciliation.application.ports import PoolKey
from strategy_manager.reconciliation.domain.booking import BookingRefusal
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind
from strategy_manager.shared.application.job import JobKind
from tests.reconciliation.application.auto_booking_support import (
    FakeVenueFillReader,
    RecordingQueue,
    build_handler,
    build_prepare_booking,
    claimed_job,
    held_base,
    proposals_of,
    reset_process_memory,
    run_job,
    seed_scenario,
    throwaway_database,
    venue_fill,
    write_counts,
)

pytestmark = pytest.mark.integration

_POOL: PoolKey = ("bybit", "usdt-m", "USDT")


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from throwaway_database("strategy_manager_test_auto_booking")


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
        # ``ledger_entries``/``execution_attempts`` are append-only and are
        # never cleared: every scenario owns random ids.
        await conn.execute(text("TRUNCATE reconciliation_discrepancies CASCADE"))


async def test_a_confirmed_close_is_booked_by_one_job_and_the_strategy_nets_to_zero(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await seed_scenario(session_factory)
    # Two venue fills of the one close: N = 2 ledger rows.
    reader = FakeVenueFillReader([venue_fill("0.3"), venue_fill("0.2")])
    queue = RecordingQueue()

    await run_job(session_factory, reader, queue)

    proposals = await proposals_of(session_factory, scenario.discrepancy_id)
    assert len(proposals) == 1
    _, state, decided_by = proposals[0]
    assert state == "APPROVED"
    assert decided_by == AUTO_BOOKING_ACTOR == "system:auto-booking"

    async with session_factory() as session:
        attempts = (
            (
                await session.execute(
                    text(
                        "SELECT origin, status, closes_allocation_id, symbol FROM "
                        "execution_attempts WHERE closes_allocation_id = :aid"
                    ),
                    {"aid": scenario.allocation_id},
                )
            )
            .mappings()
            .all()
        )
    assert len(attempts) == 1
    assert attempts[0]["origin"] == "VENUE"
    assert attempts[0]["status"] == "FILLED"
    assert attempts[0]["symbol"] == "STXUSDT"

    assert await write_counts(session_factory, scenario.allocation_id) == (1, 2)
    assert await held_base(session_factory, scenario.strategy_id) == Decimal("0")

    # The job also scheduled its successor.
    assert [job.kind for job in queue.enqueued] == [JobKind.RECONCILIATION_PREPARE_BOOKING]


async def test_running_the_job_again_writes_zero_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await seed_scenario(session_factory)
    reader = FakeVenueFillReader([venue_fill("0.3"), venue_fill("0.2")])

    await run_job(session_factory, reader, RecordingQueue())
    after_first = await write_counts(session_factory, scenario.allocation_id)
    proposals_after_first = await proposals_of(session_factory, scenario.discrepancy_id)
    assert after_first == (1, 2)

    # The discrepancy row is still CONFIRMED and open (a scan resolves it, not
    # this job), and the venue still reports the same fills.
    await run_job(session_factory, reader, RecordingQueue())

    assert await write_counts(session_factory, scenario.allocation_id) == after_first
    assert await proposals_of(session_factory, scenario.discrepancy_id) == proposals_after_first
    assert await held_base(session_factory, scenario.strategy_id) == Decimal("0")


async def test_a_pending_row_left_by_a_crash_is_approved_by_the_next_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await seed_scenario(session_factory)
    reader = FakeVenueFillReader([venue_fill("0.5")])

    # A previous worker prepared the proposal and died before booking it: only
    # the sweep ran, so nothing reached the ledger.
    async with session_factory() as session:
        swept = await build_prepare_booking(session, reader).sweep(claimed_job().id)
    assert swept.proposals_prepared == 1
    left_behind = await proposals_of(session_factory, scenario.discrepancy_id)
    assert [state for _, state, _ in left_behind] == ["PENDING"]
    assert await write_counts(session_factory, scenario.allocation_id) == (0, 0)

    await run_job(session_factory, reader, RecordingQueue())

    proposals = await proposals_of(session_factory, scenario.discrepancy_id)
    assert [(state, decided_by) for _, state, decided_by in proposals] == [
        ("APPROVED", AUTO_BOOKING_ACTOR)
    ]
    assert await write_counts(session_factory, scenario.allocation_id) == (1, 1)


async def test_a_single_allocation_reduction_is_booked(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # The ledger holds 1.0, the venue 0.6: the venue sold 0.4 and the position
    # only shrank.
    scenario = await seed_scenario(
        session_factory,
        ledger_net="1.0",
        venue_net="0.6",
        kind=DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
    )
    reader = FakeVenueFillReader([venue_fill("0.4")])

    await run_job(session_factory, reader, RecordingQueue())

    proposals = await proposals_of(session_factory, scenario.discrepancy_id)
    assert [(state, decided_by) for _, state, decided_by in proposals] == [
        ("APPROVED", AUTO_BOOKING_ACTOR)
    ]
    assert await write_counts(session_factory, scenario.allocation_id) == (1, 1)
    assert await held_base(session_factory, scenario.strategy_id) == Decimal("0.6")


async def test_an_increase_is_not_booked_and_carries_a_refusal_code(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # The ledger holds 0.5, the venue 0.8: a fill this system cannot explain.
    # The venue's BUY of 0.3 would add up to the difference exactly, so only
    # the Q2 rule stands between it and a booked "close".
    scenario = await seed_scenario(
        session_factory,
        ledger_net="0.5",
        venue_net="0.8",
        kind=DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
    )
    reader = FakeVenueFillReader([venue_fill("0.3", side="BUY")])

    async with session_factory() as session:
        handler = build_handler(session, reader, RecordingQueue())
        result = await handler.handle(claimed_job())
        await session.commit()

    assert result is not None
    assert result.refusals == {scenario.discrepancy_id: BookingRefusal.GROWS_OR_FLIPS}
    assert last_reason_by_discrepancy[scenario.discrepancy_id] is BookingRefusal.GROWS_OR_FLIPS
    assert await proposals_of(session_factory, scenario.discrepancy_id) == []
    assert await write_counts(session_factory, scenario.allocation_id) == (0, 0)
    assert await held_base(session_factory, scenario.strategy_id) == Decimal("0.5")
