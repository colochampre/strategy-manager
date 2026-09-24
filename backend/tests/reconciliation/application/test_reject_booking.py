"""Tier B: ``RejectBooking`` against a real ``alembic upgrade head`` database
(design.md § 11 "Rejection semantics and suppression"; spec: venue-close-
booking's "Rejection Writes Nothing and Requires a Reason" and
venue-reconciliation's "Rejection Suppresses Identical Re-Proposal"
requirements).

Only the clock is faked. Every write path exercised here --
``SqlAlchemyBookingProposalRepository`` and, for the suppression tests,
``PrepareBooking`` with the exact same production adapters
``test_booking_prepare_integration.py`` already proves (``ReadRecordedFillIds``,
``AllocationOwnerAdapter``, ``SqlAlchemyDiscrepancyRepository``) -- is real,
matching this file's own precedent (``test_approve_booking_integration.py``).
"""

import asyncio
import logging
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.ledger.application.read_recorded_fill_ids import ReadRecordedFillIds
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.application.ports import (
    BookingProposalRecord,
    NewBookingProposal,
    PoolKey,
    ProposedFillSnapshot,
    VenueFill,
)
from strategy_manager.reconciliation.application.prepare_booking import PrepareBooking
from strategy_manager.reconciliation.application.reject_booking import (
    RejectBooking,
    RejectOutcome,
    RejectResult,
)
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind
from strategy_manager.reconciliation.infrastructure.allocation_owner_adapter import (
    AllocationOwnerAdapter,
)
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from strategy_manager.shared.config import get_settings
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

_BACKEND_DIR = Path(__file__).resolve().parents[3]
_DB_NAME = "strategy_manager_test_reject_booking"

POOL: PoolKey = ("bybit", "usdt-m", "USDT")
LEDGER_FILLED_AT = datetime(2026, 9, 23, 10, 0, 0, tzinfo=UTC)
VENUE_FILLED_AT = datetime(2026, 9, 23, 11, 0, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)


def _maintenance_dsn(dev_url: str) -> str:
    dsn = dev_url.replace("postgresql+asyncpg://", "postgresql://")
    return re.sub(r"/[^/?]+(\?.*)?$", r"/postgres\1", dsn)


def _database_url(dev_url: str, name: str) -> str:
    return re.sub(r"/[^/?]+(\?.*)?$", rf"/{name}\1", dev_url)


async def _drop_database_if_exists(maintenance_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()


async def _create_database(maintenance_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def _run_alembic(database_url: str, *args: str) -> None:
    """Runs an alembic subcommand in a subprocess so alembic's own
    ``asyncio.run`` never collides with the test's already-running loop."""

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    dev_url = get_settings().database_url
    maintenance_dsn = _maintenance_dsn(dev_url)
    url = _database_url(dev_url, _DB_NAME)

    asyncio.run(_drop_database_if_exists(maintenance_dsn, _DB_NAME))
    asyncio.run(_create_database(maintenance_dsn, _DB_NAME))
    _run_alembic(url, "upgrade", "head")

    yield url

    asyncio.run(_drop_database_if_exists(maintenance_dsn, _DB_NAME))


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def _clean_table(engine: AsyncEngine) -> AsyncIterator[None]:
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE reconciliation_discrepancies CASCADE"))


# --- Fakes: only the clock ----------------------------------------------


class _FrozenClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class _RealClock:
    """For the suppression tests: ``reconciliation_discrepancies
    .first_observed_at`` defaults to the DATABASE's own ``now()`` (migration
    ``0020``), so ``PrepareBooking``'s own clock must read close to that same
    real wall-clock instant for its window-span check not to refuse."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class _SessionCommit:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()


class _FakeVenueFillReader:
    def __init__(self, fills: Sequence[VenueFill]) -> None:
        self._fills = list(fills)
        self.calls: list[tuple[PoolKey, str, datetime, datetime]] = []

    async def fills_in_window(
        self, pool: PoolKey, symbol: str, start: datetime, end: datetime
    ) -> list[VenueFill]:
        self.calls.append((pool, symbol, start, end))
        return list(self._fills)


class _FakeVenueFillReaderRegistry:
    def __init__(self, reader: _FakeVenueFillReader) -> None:
        self._reader = reader

    def for_pool(self, exchange: str, venue: str) -> _FakeVenueFillReader:
        return self._reader


# --- Scenario builder (mirrors test_approve_booking_integration.py) --------


@dataclass(frozen=True, slots=True)
class _Scenario:
    strategy_id: UUID
    allocation_id: UUID
    discrepancy_id: UUID
    proposal_id: UUID
    market_symbol: str
    ledger_symbol: str


def _venue_fill_snapshot(*, fill_id: str, order_id: str | None) -> ProposedFillSnapshot:
    return ProposedFillSnapshot(
        exchange_fill_id=fill_id,
        exchange_order_id=order_id,
        side="SELL",
        quantity=Decimal("0.5"),
        price=Decimal("2.6"),
        fee=Decimal("0"),
        fee_currency="USDT",
        filled_at=VENUE_FILLED_AT,
    )


async def _seed_open_allocation(
    session_factory: async_sessionmaker[AsyncSession], *, ledger_symbol: str
) -> tuple[UUID, UUID]:
    strategy_id, signal_id, reservation_id, attempt_id = uuid4(), uuid4(), uuid4(), uuid4()
    await seed_strategy(
        session_factory,
        strategy_id=strategy_id,
        exchange=POOL[0],
        venue=POOL[1],
        settlement_currency=POOL[2],
    )
    await seed_signal(
        session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        session_factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        exchange=POOL[0],
        venue=POOL[1],
        settlement_currency=POOL[2],
        status="FILLED",
    )
    await seed_execution_attempt(
        session_factory,
        attempt_id=attempt_id,
        reservation_id=reservation_id,
        exchange=POOL[0],
        venue=POOL[1],
        settlement_currency=POOL[2],
        symbol=ledger_symbol,
        status="FILLED",
    )
    async with session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            FillRecord(
                strategy_id=strategy_id,
                allocation_id=reservation_id,
                execution_attempt_id=attempt_id,
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                symbol=ledger_symbol,
                side="BUY",
                quantity=Decimal("0.5"),
                price=Decimal("2.5"),
                fee=Decimal("0"),
                fee_currency="USDT",
                notional=Decimal("1.25"),
                exchange_order_id=f"OPEN-{attempt_id}",
                exchange_fill_id=f"OPENFILL-{attempt_id}",
                filled_at=LEDGER_FILLED_AT,
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()
    return strategy_id, reservation_id


async def _seed_scenario(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    expires_at: datetime | None = None,
) -> _Scenario:
    suffix = uuid4().hex[:10].upper()
    ledger_symbol = f"STX{suffix}USDT.P"
    market_symbol = f"STX{suffix}USDT"

    strategy_id, allocation_id = await _seed_open_allocation(
        session_factory, ledger_symbol=ledger_symbol
    )

    discrepancy_id, scan_id = uuid4(), uuid4()
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO reconciliation_discrepancies "
                "(id, exchange, venue, settlement_currency, symbol, kind, "
                "venue_net_base, ledger_net_base, open_allocation_ids, status, "
                "confirmed_at, first_scan_id, last_scan_id) "
                "VALUES (:id, :exchange, :venue, :settlement_currency, :symbol, "
                "'ATTRIBUTABLE_FULL_CLOSE', 0, 0.5, ARRAY[:allocation_id]::uuid[], "
                "'CONFIRMED', now(), :scan_id, :scan_id)"
            ),
            {
                "id": discrepancy_id,
                "exchange": POOL[0],
                "venue": POOL[1],
                "settlement_currency": POOL[2],
                "symbol": market_symbol,
                "allocation_id": allocation_id,
                "scan_id": scan_id,
            },
        )
        await session.commit()

    fill = _venue_fill_snapshot(
        fill_id=f"VFILL-{discrepancy_id}", order_id=f"VORD-{discrepancy_id}"
    )
    async with session_factory() as session:
        inserted = await SqlAlchemyBookingProposalRepository(session).insert(
            NewBookingProposal(
                discrepancy_id=discrepancy_id,
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                symbol=market_symbol,
                kind=DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
                allocation_id=allocation_id,
                strategy_id=strategy_id,
                side="SELL",
                quantity=Decimal("0.5"),
                observed_venue_net_base=Decimal("0"),
                observed_ledger_net_base=Decimal("0.5"),
                observed_allocation_ids=[allocation_id],
                fills=[fill],
                client_order_id=f"vnu:{POOL[0]}:fill:{fill.exchange_fill_id}",
                expires_at=expires_at or (NOW + timedelta(hours=24)),
                prepared_by_job_id=uuid4(),
            )
        )
        await session.commit()
    assert inserted is not None

    return _Scenario(
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        discrepancy_id=discrepancy_id,
        proposal_id=inserted.id,
        market_symbol=market_symbol,
        ledger_symbol=ledger_symbol,
    )


async def _reject(
    session_factory: async_sessionmaker[AsyncSession],
    proposal_id: UUID,
    *,
    reason: str,
    at: datetime = NOW,
    dry_run: bool = False,
    decided_by: str = "owner",
) -> RejectResult:
    async with session_factory() as session:
        use_case = RejectBooking(
            proposals=SqlAlchemyBookingProposalRepository(session),
            clock=_FrozenClock(at),
            commit=_SessionCommit(session),
            dry_run=dry_run,
        )
        return await use_case.reject(proposal_id, decided_by, reason)


async def _get_proposal(
    session_factory: async_sessionmaker[AsyncSession], proposal_id: UUID
) -> BookingProposalRecord:
    async with session_factory() as session:
        return await SqlAlchemyBookingProposalRepository(session).get_for_update(proposal_id)


_LEDGER_TABLES = ("ledger_entries", "execution_attempts")


async def _snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, list[tuple[object, ...]]]:
    async with session_factory() as session:
        snapshot: dict[str, list[tuple[object, ...]]] = {}
        for table in _LEDGER_TABLES:
            result = await session.execute(text(f"SELECT * FROM {table} ORDER BY id"))  # noqa: S608
            snapshot[table] = [tuple(row) for row in result.all()]
        return snapshot


async def _discrepancy_snapshot(
    session_factory: async_sessionmaker[AsyncSession], discrepancy_id: UUID
) -> tuple[object, ...]:
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT resolved_at, status, kind, venue_net_base, ledger_net_base, "
                    "open_allocation_ids, consecutive_scans, confirmed_at "
                    "FROM reconciliation_discrepancies WHERE id = :id"
                ),
                {"id": discrepancy_id},
            )
        ).one()
        return tuple(row)


# --------------------------------------------------------------------------
# 6b.1 -- rejection writes zero rows, leaves the discrepancy OPEN/CONFIRMED
# --------------------------------------------------------------------------


async def test_reject_writes_zero_rows_leaves_discrepancy_open_confirmed(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Money-critical: rejecting a PENDING proposal must never touch
    ``ledger_entries``/``execution_attempts`` and must leave the
    discrepancy row byte-for-byte untouched -- still open
    (``resolved_at IS NULL``), still CONFIRMED, same Observation. This is
    what design.md § 11 means by "a rejected-but-real discrepancy means the
    ledger is knowingly wrong": rejection is a statement about the
    ATTRIBUTION, never about the disagreement itself.
    """

    scenario = await _seed_scenario(session_factory)

    ledger_before = await _snapshot(session_factory)
    discrepancy_before = await _discrepancy_snapshot(session_factory, scenario.discrepancy_id)

    with caplog.at_level(
        logging.WARNING, logger="strategy_manager.reconciliation.application.reject_booking"
    ):
        result = await _reject(session_factory, scenario.proposal_id, reason="not our trade")

    assert result.outcome is RejectOutcome.REJECTED
    assert result.reason == "not our trade"

    ledger_after = await _snapshot(session_factory)
    discrepancy_after = await _discrepancy_snapshot(session_factory, scenario.discrepancy_id)
    assert ledger_after == ledger_before
    assert discrepancy_after == discrepancy_before
    assert discrepancy_after[0] is None  # resolved_at
    assert discrepancy_after[1] == "CONFIRMED"  # status

    proposal = await _get_proposal(session_factory, scenario.proposal_id)
    assert proposal.state == "REJECTED"
    assert proposal.decided_by == "owner"
    assert proposal.decision_reason == "not our trade"

    # Binding requirement 1: exactly ONE WARNING naming the proposal, the
    # discrepancy and the reason.
    matches = [
        record
        for record in caplog.records
        if str(scenario.proposal_id) in record.message
        and str(scenario.discrepancy_id) in record.message
        and "not our trade" in record.message
    ]
    assert len(matches) == 1
    assert matches[0].levelname == "WARNING"


# --------------------------------------------------------------------------
# 6b.2 -- a blank reason is refused before any write
# --------------------------------------------------------------------------


@pytest.mark.parametrize("blank_reason", ["", "   ", "\t\n"])
async def test_reject_without_reason_refused(
    session_factory: async_sessionmaker[AsyncSession],
    blank_reason: str,
) -> None:
    scenario = await _seed_scenario(session_factory)
    ledger_before = await _snapshot(session_factory)

    result = await _reject(session_factory, scenario.proposal_id, reason=blank_reason)

    assert result.outcome is RejectOutcome.REASON_REQUIRED
    assert (await _snapshot(session_factory)) == ledger_before

    proposal = await _get_proposal(session_factory, scenario.proposal_id)
    assert proposal.state == "PENDING"  # untouched, eligible for a real retry


# --------------------------------------------------------------------------
# DRY_RUN refuses too (design.md § 16) -- binding requirement 1
# --------------------------------------------------------------------------


async def test_reject_dry_run_refuses_at_use_case_level(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await _seed_scenario(session_factory)
    ledger_before = await _snapshot(session_factory)

    result = await _reject(
        session_factory, scenario.proposal_id, reason="irrelevant", dry_run=True
    )

    assert result.outcome is RejectOutcome.DRY_RUN_REFUSED
    assert (await _snapshot(session_factory)) == ledger_before

    proposal = await _get_proposal(session_factory, scenario.proposal_id)
    assert proposal.state == "PENDING"


# --------------------------------------------------------------------------
# A non-PENDING proposal is ALREADY_DECIDED, never re-processed
# --------------------------------------------------------------------------


async def test_reject_of_non_pending_proposal_is_already_decided(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await _seed_scenario(session_factory)

    first = await _reject(session_factory, scenario.proposal_id, reason="first reason")
    assert first.outcome is RejectOutcome.REJECTED

    second = await _reject(
        session_factory,
        scenario.proposal_id,
        reason="second reason",
        at=NOW + timedelta(seconds=1),
    )
    assert second.outcome is RejectOutcome.ALREADY_DECIDED

    proposal = await _get_proposal(session_factory, scenario.proposal_id)
    assert proposal.decision_reason == "first reason"  # the SECOND call changed nothing


# --------------------------------------------------------------------------
# Rejection suppression, end to end, through the REAL repository
# (venue-reconciliation spec: "Rejection Suppresses Identical Re-Proposal")
# --------------------------------------------------------------------------


def _prepare_booking(
    session: AsyncSession, venue_fills: _FakeVenueFillReaderRegistry
) -> PrepareBooking:
    return PrepareBooking(
        discrepancies=SqlAlchemyDiscrepancyRepository(session),
        proposals=SqlAlchemyBookingProposalRepository(session),
        venue_fills=venue_fills,
        recorded_fill_ids=ReadRecordedFillIds(SqlAlchemyLedgerRepository(session)),
        allocation_owner=AllocationOwnerAdapter(session),
        clock=_RealClock(),
        commit=_SessionCommit(session),
        window_pad_seconds=300,
        max_span_seconds=604_800,
        proposal_expiry_seconds=86_400,
        dry_run=False,
    )


async def test_rejection_suppresses_a_fresh_sweep_over_the_same_observation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await _seed_scenario(session_factory)
    rejected = await _reject(session_factory, scenario.proposal_id, reason="not our trade")
    assert rejected.outcome is RejectOutcome.REJECTED

    fake_reader = _FakeVenueFillReader([])
    async with session_factory() as session:
        result = await _prepare_booking(
            session, _FakeVenueFillReaderRegistry(fake_reader)
        ).sweep(uuid4())

    assert result.proposals_suppressed == 1
    assert result.proposals_prepared == 0
    # Suppression short-circuits BEFORE the venue fetch (design.md § 11:
    # the suppression key is the Observation triple, checked first).
    assert fake_reader.calls == []

    async with session_factory() as session:
        pending = await SqlAlchemyBookingProposalRepository(session).list_pending()
    assert [p for p in pending if p.discrepancy_id == scenario.discrepancy_id] == []


async def test_rejection_does_not_suppress_after_the_observation_moves(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await _seed_scenario(session_factory)
    rejected = await _reject(session_factory, scenario.proposal_id, reason="not our trade")
    assert rejected.outcome is RejectOutcome.REJECTED

    # The venue net moved: 0 -> 0.2 (ledger stays 0.5), a genuinely
    # different Observation triple from the one that was rejected.
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE reconciliation_discrepancies SET venue_net_base = 0.2 "
                "WHERE id = :id"
            ),
            {"id": scenario.discrepancy_id},
        )
        await session.commit()

    fresh_fill = VenueFill(
        exchange_fill_id=f"VFILL2-{scenario.discrepancy_id}",
        exchange_order_id=f"VORD2-{scenario.discrepancy_id}",
        symbol=scenario.market_symbol,
        side="SELL",
        quantity=Decimal("0.3"),
        price=Decimal("2.6"),
        fee=Decimal("0"),
        fee_currency="USDT",
        filled_at=VENUE_FILLED_AT,
    )
    fake_reader = _FakeVenueFillReader([fresh_fill])
    async with session_factory() as session:
        result = await _prepare_booking(
            session, _FakeVenueFillReaderRegistry(fake_reader)
        ).sweep(uuid4())

    assert result.proposals_suppressed == 0
    assert result.proposals_prepared == 1
    assert fake_reader.calls  # the venue WAS fetched this time

    async with session_factory() as session:
        pending = await SqlAlchemyBookingProposalRepository(session).list_pending()
    fresh = [p for p in pending if p.discrepancy_id == scenario.discrepancy_id]
    assert len(fresh) == 1
    assert fresh[0].id != scenario.proposal_id
    assert fresh[0].quantity == Decimal("0.3")
