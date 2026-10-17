"""Tier B: a proposal still PENDING when the automatic booking is deployed
(owner decision 66 Q1, 2026-10-16; spec "A Proposal Still PENDING At Deploy Is
Booked If Current, Otherwise Discarded And Prepared Again").

Before this change nothing booked a proposal but the owner, so the first
non-dry-run job after the deploy meets PENDING rows nobody will ever approve.
Fresh ones are booked; stale ones are discarded (SUPERSEDED by the freshness
re-check, EXPIRED by the expiry step) and a later sweep prepares a new proposal
for what is still wrong. A historical REJECTED row keeps suppressing its
identical observation and the discrepancy reaches the owner through the grace
of the rule of attention.

Symbols follow R21 (see ``auto_booking_support``). The venue is a fake and
every run uses a frozen clock.
"""

import logging
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
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
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from tests.reconciliation.application.auto_booking_support import (
    NOW,
    FakeVenueFillReader,
    RecordingQueue,
    build_prepare_booking,
    claimed_job,
    held_base,
    insert_pending_proposal,
    proposals_of,
    reset_process_memory,
    run_job,
    seed_scenario,
    throwaway_database,
    venue_fill,
    write_counts,
)

pytestmark = pytest.mark.integration

_ANNOUNCER = "strategy_manager.reconciliation.application.announce_needs_owner"


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from throwaway_database("strategy_manager_test_auto_booking_deploy")


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


async def _move_the_discrepancy(
    engine: AsyncEngine, discrepancy_id: object, *, kind: str, venue_net: str
) -> None:
    """What a later scan does to a row the proposal was frozen from: the venue
    reports something else now."""

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE reconciliation_discrepancies "
                "SET kind = :kind, venue_net_base = :venue_net WHERE id = :id"
            ),
            {"kind": kind, "venue_net": Decimal(venue_net), "id": discrepancy_id},
        )


async def test_a_fresh_pending_proposal_is_approved_by_the_first_non_dry_run_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await seed_scenario(session_factory)
    await insert_pending_proposal(session_factory, scenario)
    reader = FakeVenueFillReader([venue_fill("0.5")])

    # Under DRY_RUN the handler skips the whole run: the leftover stays put.
    await run_job(session_factory, reader, RecordingQueue(), dry_run=True)
    assert [s for _, s, _ in await proposals_of(session_factory, scenario.discrepancy_id)] == [
        "PENDING"
    ]
    assert await write_counts(session_factory, scenario.allocation_id) == (0, 0)

    await run_job(session_factory, reader, RecordingQueue())

    decided = await proposals_of(session_factory, scenario.discrepancy_id)
    assert [(state, by) for _, state, by in decided] == [("APPROVED", AUTO_BOOKING_ACTOR)]
    assert await write_counts(session_factory, scenario.allocation_id) == (1, 1)
    assert await held_base(session_factory, scenario.strategy_id) == Decimal("0")


async def test_a_stale_pending_proposal_is_superseded_and_prepared_again(
    engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    scenario = await seed_scenario(session_factory)
    leftover = await insert_pending_proposal(session_factory, scenario)
    # The venue moved since the proposal was prepared: it still holds 0.1, so
    # the close the proposal describes is no longer the difference.
    await _move_the_discrepancy(
        engine,
        scenario.discrepancy_id,
        kind="ATTRIBUTABLE_SINGLE_ALLOCATION",
        venue_net="0.1",
    )
    reader = FakeVenueFillReader([venue_fill("0.4")])

    await run_job(session_factory, reader, RecordingQueue())

    after_first = await proposals_of(session_factory, scenario.discrepancy_id)
    assert [(pid, state, by) for pid, state, by in after_first][0] == (
        leftover.id,
        "SUPERSEDED",
        AUTO_BOOKING_ACTOR,
    )
    assert await write_counts(session_factory, scenario.allocation_id) == (0, 0)

    # A later sweep prepares a new proposal for what is still wrong.
    async with session_factory() as session:
        swept = await build_prepare_booking(session, reader).sweep(claimed_job().id)
    assert swept.proposals_prepared == 1
    states = [(state, by) for _, state, by in await proposals_of(
        session_factory, scenario.discrepancy_id
    )]
    assert states == [("SUPERSEDED", AUTO_BOOKING_ACTOR), ("PENDING", None)]

    # ... and the job after that books it.
    await run_job(session_factory, reader, RecordingQueue())
    final = await proposals_of(session_factory, scenario.discrepancy_id)
    assert [(state, by) for _, state, by in final] == [
        ("SUPERSEDED", AUTO_BOOKING_ACTOR),
        ("APPROVED", AUTO_BOOKING_ACTOR),
    ]
    assert await write_counts(session_factory, scenario.allocation_id) == (1, 1)
    assert await held_base(session_factory, scenario.strategy_id) == Decimal("0.1")


async def test_an_expired_pending_proposal_is_discarded_and_prepared_again(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await seed_scenario(session_factory)
    leftover = await insert_pending_proposal(
        session_factory, scenario, expires_at=NOW - timedelta(minutes=1)
    )
    reader = FakeVenueFillReader([venue_fill("0.5")])

    await run_job(session_factory, reader, RecordingQueue())

    decided = await proposals_of(session_factory, scenario.discrepancy_id)
    assert [(pid, state, by) for pid, state, by in decided] == [
        (leftover.id, "EXPIRED", None),
        (decided[1][0], "APPROVED", AUTO_BOOKING_ACTOR),
    ]
    assert decided[1][0] != leftover.id
    assert await write_counts(session_factory, scenario.allocation_id) == (1, 1)


async def test_a_historical_rejection_keeps_suppressing_and_reaches_the_owner_after_the_grace(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    scenario = await seed_scenario(session_factory)
    rejected = await insert_pending_proposal(session_factory, scenario)
    async with session_factory() as session:
        changed = await SqlAlchemyBookingProposalRepository(session).mark_state(
            rejected.id, "REJECTED", NOW, decided_by="owner", decision_reason="by hand"
        )
        await session.commit()
    assert changed is True
    reader = FakeVenueFillReader([venue_fill("0.5")])

    # Inside the grace: suppressed, nothing booked, nothing announced.
    with caplog.at_level(logging.ERROR, logger=_ANNOUNCER):
        await run_job(session_factory, reader, RecordingQueue())
    assert [r for r in caplog.records if r.name == _ANNOUNCER] == []
    assert [s for _, s, _ in await proposals_of(session_factory, scenario.discrepancy_id)] == [
        "REJECTED"
    ]

    # Past the grace: still suppressed, and now the owner is told, once, with
    # the reason the sweep knew.
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger=_ANNOUNCER):
        await run_job(session_factory, reader, RecordingQueue(), at=NOW + timedelta(hours=2))
    announced = [r.getMessage() for r in caplog.records if r.name == _ANNOUNCER]
    assert len(announced) == 1
    assert str(scenario.discrepancy_id) in announced[0]
    assert "SUPPRESSED_BY_REJECTION" in announced[0]

    assert [s for _, s, _ in await proposals_of(session_factory, scenario.discrepancy_id)] == [
        "REJECTED"
    ]
    assert await write_counts(session_factory, scenario.allocation_id) == (0, 0)
