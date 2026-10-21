"""Tier B, design § K (owner decision 66, 2026-10-16): the rows of "what fails
here without a log line?" that need a whole job on real PostgreSQL.

* row 2 (cd.3.2): a refusal the sweep repeats reaches the owner after the
  grace, once, with its code, and is never dropped by a restart;
* row 4 (cd.3.4): an unexpected exception in one approval fails the job;
* row 5 (cd.3.5): a proposal that goes stale at approval is told to the owner
  with ``STALE_AT_APPROVAL``;
* row 11 (cd.3.11): a discrepancy the scan resolved is in no list.

Symbols follow R21: the ledger's fills are ``STXUSDT.P``, the discrepancy row
and the venue's fills are ``STXUSDT``. Only the clock, the venue's readers and
the job queue are fakes.
"""

import logging
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.reconciliation.application.announce_needs_owner import AnnounceNeedsOwner
from strategy_manager.reconciliation.application.auto_book_pending import AutoBookPending
from strategy_manager.reconciliation.application.booking_prepare_handler import (
    last_reason_by_discrepancy,
)
from strategy_manager.reconciliation.application.ports import PoolKey
from strategy_manager.reconciliation.application.scan_pools import ScanPools
from strategy_manager.reconciliation.domain.booking import BookingRefusal
from strategy_manager.reconciliation.domain.positions import LedgerPosition, VenuePosition
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from strategy_manager.reconciliation.infrastructure.router import (
    router as reconciliation_router,
)
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.errors import InvariantViolation
from tests.identity_auth import ADMIN_HEADERS, sign_in_as_admin
from tests.reconciliation.application.auto_booking_support import (
    GRACE_SECONDS,
    MARKET_SYMBOL,
    NOW,
    POOL,
    REMINDER_SECONDS,
    FakeVenueFillReader,
    FrozenClock,
    RecordingQueue,
    SessionCommit,
    build_approve_booking,
    build_handler,
    claimed_job,
    insert_pending_proposal,
    proposals_of,
    reset_process_memory,
    seed_scenario,
    throwaway_database,
    venue_fill,
    write_counts,
)

pytestmark = pytest.mark.integration

_ANNOUNCER = "strategy_manager.reconciliation.application.announce_needs_owner"
_SCANNER = "strategy_manager.reconciliation.application.scan_pools"

_PAST_THE_GRACE = NOW + timedelta(seconds=GRACE_SECONDS) + timedelta(hours=1)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from throwaway_database("strategy_manager_test_k_rows")


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


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)
    monkeypatch.setattr(get_settings(), "dry_run", False)
    monkeypatch.setattr(get_settings(), "reconciliation_auto_booking_grace_seconds", 3600)


def _announcements(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _ANNOUNCER and r.levelno >= logging.ERROR]


async def _job(
    session_factory: async_sessionmaker[AsyncSession],
    reader: FakeVenueFillReader,
    queue: RecordingQueue,
    **kwargs: object,
) -> dict[UUID, BookingRefusal]:
    """One claimed job as the worker runs it; returns the sweep's refusals."""

    async with session_factory() as session:
        handler = build_handler(session, reader, queue, **kwargs)  # type: ignore[arg-type]
        result = await handler.handle(claimed_job())
        await session.commit()
    assert result is not None
    return dict(result.refusals)


# --- cd.3.2, K row 2: a bookable discrepancy that prepare keeps refusing ------


async def test_a_sum_mismatch_refused_every_sweep_reaches_the_owner_once_after_the_grace(
    session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    scenario = await seed_scenario(session_factory)
    # The venue's fills (0.3) do not add up to the difference (0.5).
    reader = FakeVenueFillReader([venue_fill("0.3")])
    queue = RecordingQueue()

    with caplog.at_level(logging.ERROR, logger=_ANNOUNCER):
        # Inside the grace: refused, and nothing is told to the owner yet.
        inside = await _job(session_factory, reader, queue)
        assert inside == {scenario.discrepancy_id: BookingRefusal.SUM_MISMATCH}
        assert _announcements(caplog) == []

        # Past the grace the same refusal makes it NEEDS_OWNER: one ERROR.
        await _job(session_factory, reader, queue, at=_PAST_THE_GRACE)
        [announced] = _announcements(caplog)
        message = announced.getMessage()
        assert "SUM_MISMATCH" in message
        assert str(scenario.discrepancy_id) in message

        # Every later sweep refuses it again, and it is announced no more.
        for minutes in (1, 2, 3):
            again = await _job(
                session_factory, reader, queue, at=_PAST_THE_GRACE + timedelta(minutes=minutes)
            )
            assert again == {scenario.discrepancy_id: BookingRefusal.SUM_MISMATCH}
        assert len(_announcements(caplog)) == 1

    assert await proposals_of(session_factory, scenario.discrepancy_id) == []
    assert await write_counts(session_factory, scenario.allocation_id) == (0, 0)


async def test_after_a_restart_the_item_is_announced_again_with_the_code_its_first_sweep_produced(
    session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    scenario = await seed_scenario(session_factory)
    reader = FakeVenueFillReader([venue_fill("0.3")])

    with caplog.at_level(logging.ERROR, logger=_ANNOUNCER):
        await _job(session_factory, reader, RecordingQueue(), at=_PAST_THE_GRACE)
        assert len(_announcements(caplog)) == 1

        # A worker restart: a fresh handler, and an empty memory of what was
        # announced and of the last refusal seen for each discrepancy.
        reset_process_memory()
        assert scenario.discrepancy_id not in last_reason_by_discrepancy
        caplog.clear()

        await _job(
            session_factory,
            reader,
            RecordingQueue(),
            at=_PAST_THE_GRACE + timedelta(minutes=1),
        )

    [announced] = _announcements(caplog)
    message = announced.getMessage()
    assert "SUM_MISMATCH" in message
    assert "REASON_UNKNOWN" not in message
    assert str(scenario.discrepancy_id) in message


async def test_when_no_sweep_ran_in_the_process_the_item_is_announced_as_reason_unknown(
    session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    scenario = await seed_scenario(session_factory)

    async with session_factory() as session:
        use_case = AnnounceNeedsOwner(
            discrepancies=SqlAlchemyDiscrepancyRepository(session),
            approved=SqlAlchemyBookingProposalRepository(session),
            clock=FrozenClock(_PAST_THE_GRACE),
            grace_seconds=GRACE_SECONDS,
            reminder_seconds=REMINDER_SECONDS,
        )
        with caplog.at_level(logging.ERROR, logger=_ANNOUNCER):
            # An empty memory: no sweep has run in this process.
            await use_case.run({})
            await use_case.run({})

    # Never dropped, and announced once however often it is looked at.
    [announced] = _announcements(caplog)
    message = announced.getMessage()
    assert "REASON_UNKNOWN" in message
    assert str(scenario.discrepancy_id) in message


# --- cd.3.4, K row 4: an unexpected exception in one approval ------------------


async def test_an_approval_that_raises_fails_the_job_and_leaves_every_proposal_pending(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Listed first (the list is ordered by ``expires_at``): the fill the
    # venue gave no order id, which approval refuses with an InvariantViolation.
    bad = await seed_scenario(session_factory, symbol=MARKET_SYMBOL)
    bad_proposal = await insert_pending_proposal(
        session_factory, bad, expires_at=NOW + timedelta(hours=1), without_order_id=True
    )
    # Another market (one open row per market), healthy, listed second.
    good = await seed_scenario(session_factory, symbol="OTHERUSDT")
    good_proposal = await insert_pending_proposal(
        session_factory, good, expires_at=NOW + timedelta(hours=2)
    )
    reader = FakeVenueFillReader([venue_fill("0.5")])
    queue = RecordingQueue()

    async with session_factory() as session:
        handler = build_handler(session, reader, queue)
        with pytest.raises(InvariantViolation):
            await handler.handle(claimed_job())
        await session.rollback()

    # The job failed: no successor was enqueued.
    assert queue.enqueued == []
    assert JobKind.RECONCILIATION_PREPARE_BOOKING not in [job.kind for job in queue.enqueued]
    # The proposal stays PENDING, and so does the other one of the list: the
    # run stopped at the fault and touched nothing after it.
    assert await proposals_of(session_factory, bad.discrepancy_id) == [
        (bad_proposal.id, "PENDING", None)
    ]
    assert await proposals_of(session_factory, good.discrepancy_id) == [
        (good_proposal.id, "PENDING", None)
    ]
    assert await write_counts(session_factory, bad.allocation_id) == (0, 0)
    assert await write_counts(session_factory, good.allocation_id) == (0, 0)


# --- cd.3.5, K row 5: an approval refused as stale --------------------------


async def _stale_at_approval(
    session_factory: async_sessionmaker[AsyncSession], stale: str, *, at_grace_end: bool
) -> tuple[UUID, UUID]:
    """A PENDING proposal that goes stale between the expiry step and the
    automatic step of one job. Returns ``(discrepancy_id, proposal_id)``."""

    scenario = await seed_scenario(session_factory)
    at = _PAST_THE_GRACE if at_grace_end else NOW
    if stale == "EXPIRED":
        proposal = await insert_pending_proposal(
            session_factory, scenario, expires_at=at + timedelta(seconds=1)
        )
    else:
        # The venue net moved from the frozen 0.1 back to the row's 0.
        proposal = await insert_pending_proposal(
            session_factory, scenario, venue_net="0.1", expires_at=at + timedelta(hours=1)
        )
    reader = FakeVenueFillReader([venue_fill("0.5")])
    async with session_factory() as session:
        handler = build_handler(
            session, reader, RecordingQueue(), at=at, approve_at=at + timedelta(minutes=30)
        )
        await handler.handle(claimed_job())
        await session.commit()
    return scenario.discrepancy_id, proposal.id


@pytest.mark.parametrize("stale", ["EXPIRED", "SUPERSEDED"])
async def test_a_proposal_stale_at_approval_is_remembered_as_stale_and_announced_after_the_grace(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
    stale: str,
) -> None:
    with caplog.at_level(logging.ERROR, logger=_ANNOUNCER):
        discrepancy_id, proposal_id = await _stale_at_approval(
            session_factory, stale, at_grace_end=True
        )

    assert [s for _, s, _ in await proposals_of(session_factory, discrepancy_id)][0] == stale
    assert last_reason_by_discrepancy[discrepancy_id] is BookingRefusal.STALE_AT_APPROVAL
    [announced] = _announcements(caplog)
    message = announced.getMessage()
    assert "STALE_AT_APPROVAL" in message
    assert str(discrepancy_id) in message
    assert str(proposal_id) not in message


@pytest.mark.parametrize("stale", ["EXPIRED", "SUPERSEDED"])
async def test_a_proposal_stale_at_approval_is_not_announced_inside_the_grace(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
    stale: str,
) -> None:
    with caplog.at_level(logging.ERROR, logger=_ANNOUNCER):
        discrepancy_id, _ = await _stale_at_approval(session_factory, stale, at_grace_end=False)

    assert last_reason_by_discrepancy[discrepancy_id] is BookingRefusal.STALE_AT_APPROVAL
    assert _announcements(caplog) == []


async def test_auto_book_names_the_stale_code_for_an_expired_and_a_superseded_proposal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The automatic step alone, without the sweep that precedes it in a job:
    both stale outcomes come back as ``STALE_AT_APPROVAL``."""

    expired = await seed_scenario(session_factory)
    await insert_pending_proposal(
        session_factory, expired, expires_at=NOW - timedelta(minutes=1)
    )
    superseded = await seed_scenario(session_factory, symbol="OTHERUSDT")
    await insert_pending_proposal(
        session_factory, superseded, venue_net="0.1", expires_at=NOW + timedelta(hours=1)
    )

    async with session_factory() as session:
        auto_book = AutoBookPending(
            proposals=SqlAlchemyBookingProposalRepository(session),
            approver=build_approve_booking(session),
        )
        result = await auto_book.run()

    assert result.not_approved == {
        expired.discrepancy_id: BookingRefusal.STALE_AT_APPROVAL,
        superseded.discrepancy_id: BookingRefusal.STALE_AT_APPROVAL,
    }
    assert result.approved == ()


# --- cd.3.11, K row 11: resolved by the scan before the owner looked ----------


class _VenueReader:
    def __init__(self, positions: Sequence[VenuePosition]) -> None:
        self._positions = list(positions)

    async def open_positions(self, pool: PoolKey) -> list[VenuePosition]:
        return list(self._positions)


class _NothingOpenInTheLedger:
    """``ledger_entries`` is append-only and shared by every test of this
    module, so the ledger's side of the comparison is held fixed: no open
    position at all."""

    async def net_positions_by_symbol(self, pool: PoolKey) -> list[LedgerPosition]:
        return []


class _VenueReaders:
    def __init__(self, reader: _VenueReader) -> None:
        self._reader = reader

    def for_pool(self, exchange: str, venue: str) -> _VenueReader:
        return self._reader


async def test_a_discrepancy_resolved_by_the_scan_is_in_no_list_and_the_scan_counts_it(
    session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    scenario = await seed_scenario(session_factory)  # ledger 0.5, venue 0: CONFIRMED
    app = FastAPI()
    app.include_router(reconciliation_router, prefix="/api")

    async def _session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session

    async def read() -> dict[str, object]:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            response = await api.get("/api/reconciliation/confirmed", headers=ADMIN_HEADERS)
        assert response.status_code == 200
        body: dict[str, object] = response.json()
        return body

    # Past the grace and unbooked: it needs the owner, and the badge counts it.
    seen = await read()
    assert seen["needs_owner_count"] == 1

    # Neither side reports the market any more: the next scan resolves the row.
    scan_id = uuid4()
    async with session_factory() as session:
        with caplog.at_level(logging.INFO, logger=_SCANNER):
            result = await ScanPools(
                pools=[POOL],
                venue_readers=_VenueReaders(_VenueReader([])),  # type: ignore[arg-type]
                ledger_positions=_NothingOpenInTheLedger(),
                discrepancies=SqlAlchemyDiscrepancyRepository(session),
                clock=FrozenClock(_PAST_THE_GRACE),
                commit=SessionCommit(session),
                confirmations_required=2,
            ).scan(scan_id)

    assert result.discrepancies_resolved == 1
    # Owner decision 66 (2026-10-17): the scan says so, once, for the pool.
    resolution_lines = [
        r.getMessage() for r in caplog.records if r.name == _SCANNER and r.levelno == logging.INFO
    ]
    assert len(resolution_lines) == 1
    for expected in (*POOL, "1", str(scan_id)):
        assert expected in resolution_lines[0]
    async with session_factory() as session:
        resolved_by = (
            await session.execute(
                text("SELECT resolved_by_scan_id FROM reconciliation_discrepancies WHERE id = :i"),
                {"i": scenario.discrepancy_id},
            )
        ).scalar_one()
    assert resolved_by == scan_id

    body = await read()
    assert body["needs_owner"] == []
    assert body["being_booked"] == []
    assert body["booked"] == []
    assert body["needs_owner_count"] == 0

    # Nothing about it is announced either: it no longer needs the owner.
    async with session_factory() as session:
        with caplog.at_level(logging.ERROR, logger=_ANNOUNCER):
            await AnnounceNeedsOwner(
                discrepancies=SqlAlchemyDiscrepancyRepository(session),
                approved=SqlAlchemyBookingProposalRepository(session),
                clock=FrozenClock(_PAST_THE_GRACE),
                grace_seconds=GRACE_SECONDS,
                reminder_seconds=REMINDER_SECONDS,
            ).run({})
    assert _announcements(caplog) == []
