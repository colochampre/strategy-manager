"""Tier B: the database probes of the independent verifier of PR 15's backend
(tasks.md cd.1.37; owner decision 66 Q2, 2026-10-16), committed as regression
tests because the PostgreSQL settings only exist in the workspace.

Each probe drives one full ``reconciliation.prepare_booking`` job through the
real wiring of ``auto_booking_support`` and compares whole-table snapshots:

1. a refused prepare writes nothing, whatever the refusal;
2. a SINGLE_ALLOCATION flip is not booked, reaches the owner after the grace
   and the ERROR record names no quantity (R19);
3. DRY_RUN books and announces nothing, and still schedules its successor.

Symbols follow R21: the ledger's fills and the attempt are ``STXUSDT.P``, the
discrepancy row and the venue's fills are ``STXUSDT``. The job queue is the
recording fake of the support module, so "the queue differs only by the
successor" is asserted on what was enqueued.
"""

import logging
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
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

from strategy_manager.reconciliation.application.booking_prepare_handler import (
    last_reason_by_discrepancy,
)
from strategy_manager.reconciliation.domain.booking import BookingRefusal
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind
from strategy_manager.reconciliation.infrastructure.router import (
    router as reconciliation_router,
)
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.config import get_settings
from tests.ledger.infrastructure.conftest import seed_execution_attempt
from tests.reconciliation.application.auto_booking_support import (
    LEDGER_SYMBOL,
    MARKET_SYMBOL,
    NOW,
    POOL,
    FakeVenueFillReader,
    RecordingQueue,
    Scenario,
    build_handler,
    claimed_job,
    insert_pending_proposal,
    proposals_of,
    reset_process_memory,
    run_job,
    seed_scenario,
    snapshot_tables,
    throwaway_database,
    venue_fill,
    write_counts,
)

pytestmark = pytest.mark.integration

_ANNOUNCER = "strategy_manager.reconciliation.application.announce_needs_owner"
_TOKEN = "adm1n-t0ken"


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    yield from throwaway_database("strategy_manager_test_auto_booking_probes")


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
    monkeypatch.setattr(get_settings(), "admin_api_token", _TOKEN)
    monkeypatch.setattr(get_settings(), "dry_run", False)
    monkeypatch.setattr(get_settings(), "reconciliation_auto_booking_grace_seconds", 300)


async def _one_job(
    session_factory: async_sessionmaker[AsyncSession],
    reader: FakeVenueFillReader,
    queue: RecordingQueue,
    **kwargs: object,
) -> dict[UUID, BookingRefusal]:
    async with session_factory() as session:
        handler = build_handler(session, reader, queue, **kwargs)  # type: ignore[arg-type]
        result = await handler.handle(claimed_job())
        await session.commit()
    assert result is not None
    return dict(result.refusals)


async def _a_system_order_for(
    session_factory: async_sessionmaker[AsyncSession], scenario: Scenario
) -> str:
    """An attempt THIS system placed on the pool, with a venue order id; the
    venue's fill is then the fill of that order (spelled ``STXUSDT.P`` here
    and ``STXUSDT`` on the venue's side, R21)."""

    order_id = f"SYS-{uuid4()}"
    await seed_execution_attempt(
        session_factory,
        attempt_id=uuid4(),
        closes_allocation_id=scenario.allocation_id,
        exchange=POOL[0],
        venue=POOL[1],
        settlement_currency=POOL[2],
        symbol=LEDGER_SYMBOL,
        status="FILLED",
        exchange_order_id=order_id,
    )
    return order_id


# --- 1. A refused prepare writes nothing ---------------------------------------


@pytest.mark.parametrize(
    "refusal",
    [
        BookingRefusal.GROWS_OR_FLIPS,
        BookingRefusal.SYSTEM_ORDER_FILL,
        BookingRefusal.SUM_MISMATCH,
    ],
)
async def test_a_refused_prepare_leaves_every_table_exactly_as_it_found_it(
    session_factory: async_sessionmaker[AsyncSession], refusal: BookingRefusal
) -> None:
    if refusal is BookingRefusal.GROWS_OR_FLIPS:
        scenario = await seed_scenario(
            session_factory,
            ledger_net="0.5",
            venue_net="0.8",
            kind=DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
        )
        # A BUY of 0.3 adds up to the difference exactly: only the Q2 rule
        # stands between it and a booked "close".
        fills = [venue_fill("0.3", side="BUY")]
    elif refusal is BookingRefusal.SYSTEM_ORDER_FILL:
        scenario = await seed_scenario(session_factory)
        order_id = await _a_system_order_for(session_factory, scenario)
        # The fills add up to the difference exactly and reduce the position:
        # only the system-order check stands between them and a booked close.
        fills = [replace(venue_fill("0.5"), exchange_order_id=order_id)]
    else:
        scenario = await seed_scenario(session_factory)
        fills = [venue_fill("0.3")]  # the venue's fills do not add up to -0.5

    assert {f.symbol for f in fills} == {MARKET_SYMBOL}
    before = await snapshot_tables(session_factory)
    # R21: a different spelling on each side of the module boundary.
    market, ledger = f'"symbol": "{MARKET_SYMBOL}"', f'"symbol": "{LEDGER_SYMBOL}"'
    assert any(market in row for row in before["reconciliation_discrepancies"])
    assert any(ledger in row for row in before["ledger_entries"])
    assert any(ledger in row for row in before["execution_attempts"])
    queue = RecordingQueue()

    refusals = await _one_job(session_factory, FakeVenueFillReader(fills), queue)

    assert refusals == {scenario.discrepancy_id: refusal}
    assert last_reason_by_discrepancy[scenario.discrepancy_id] is refusal
    assert await snapshot_tables(session_factory) == before
    assert await proposals_of(session_factory, scenario.discrepancy_id) == []
    assert await write_counts(session_factory, scenario.allocation_id) == (
        (1, 0) if refusal is BookingRefusal.SYSTEM_ORDER_FILL else (0, 0)
    )
    # The queue differs by the successor, and by nothing else.
    assert [job.kind for job in queue.enqueued] == [JobKind.RECONCILIATION_PREPARE_BOOKING]


# --- 2. A SINGLE_ALLOCATION flip is not booked ---------------------------------


async def test_a_flip_is_not_booked_and_reaches_the_owner_without_a_quantity(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The ledger holds 0.5 and the venue is short 0.2: a SELL of 0.7 explains
    # the difference exactly, yet the position flipped instead of shrinking.
    scenario = await seed_scenario(
        session_factory,
        ledger_net="0.5",
        venue_net="-0.2",
        kind=DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
    )
    reader = FakeVenueFillReader([venue_fill("0.7", side="SELL")])
    before = await snapshot_tables(session_factory)

    # Inside the grace: refused, nothing written, nothing announced.
    with caplog.at_level(logging.ERROR, logger=_ANNOUNCER):
        refusals = await _one_job(session_factory, reader, RecordingQueue())
    assert refusals == {scenario.discrepancy_id: BookingRefusal.GROWS_OR_FLIPS}
    assert [r for r in caplog.records if r.name == _ANNOUNCER] == []
    assert await snapshot_tables(session_factory) == before
    assert await proposals_of(session_factory, scenario.discrepancy_id) == []
    assert await write_counts(session_factory, scenario.allocation_id) == (0, 0)

    # Past the grace (the injected clock): the same refusal, now told to the owner.
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger=_ANNOUNCER):
        refusals = await _one_job(
            session_factory, reader, RecordingQueue(), at=NOW + timedelta(hours=2)
        )
    assert refusals == {scenario.discrepancy_id: BookingRefusal.GROWS_OR_FLIPS}
    assert await snapshot_tables(session_factory) == before

    async with AsyncClient(
        transport=ASGITransport(app=_app(session_factory)), base_url="http://test"
    ) as api:
        response = await api.get(
            "/api/reconciliation/confirmed", headers={"Authorization": f"Bearer {_TOKEN}"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["needs_owner_count"] == 1
    [item] = body["needs_owner"]
    assert item["discrepancy_id"] == str(scenario.discrepancy_id)
    assert item["reason"] == "NOT_BOOKED"
    assert body["booked"] == []

    announced = [r for r in caplog.records if r.name == _ANNOUNCER]
    assert [r.levelno for r in announced] == [logging.ERROR]
    message = announced[0].getMessage()
    assert str(scenario.discrepancy_id) in message
    assert "GROWS_OR_FLIPS" in message
    for quantity in ("0.5", "-0.2", "0.7"):
        assert quantity not in message


def _app(session_factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = FastAPI()
    app.include_router(reconciliation_router, prefix="/api")

    async def _session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    return app


# --- 4. DRY_RUN books and announces nothing ------------------------------------
# ``test_auto_booking_deploy_integration`` only asserts that the leftover stays
# PENDING and that nothing reached the ledger; it neither compares whole
# tables, nor watches the log for an ERROR, nor looks at the successor.


async def test_a_dry_run_job_writes_and_announces_nothing_and_still_schedules_its_successor(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    pending = await seed_scenario(session_factory)
    await insert_pending_proposal(session_factory, pending)
    # Another market (one open row per market), past the grace: told to the
    # owner by a job that is not dry.
    needing_the_owner = await seed_scenario(session_factory, symbol="OTHERUSDT")
    reader = FakeVenueFillReader([venue_fill("0.5")])
    before = await snapshot_tables(session_factory)
    queue = RecordingQueue()

    # Past the grace, so a job that was NOT dry would both book and announce.
    with caplog.at_level(logging.ERROR):
        await run_job(session_factory, reader, queue, at=NOW + timedelta(hours=2), dry_run=True)

    assert await snapshot_tables(session_factory) == before
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
    assert reader.calls == 0
    assert [job.kind for job in queue.enqueued] == [JobKind.RECONCILIATION_PREPARE_BOOKING]
    assert [s for _, s, _ in await proposals_of(session_factory, pending.discrepancy_id)] == [
        "PENDING"
    ]
    assert await proposals_of(session_factory, needing_the_owner.discrepancy_id) == []
