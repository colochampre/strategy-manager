"""Shared scaffolding of the automatic-booking integration tests (PR 15,
design T5 and T6, spec "Approval Is Automatic and Freshness-Checked").

Only the clock, the USD rate, the venue's fill reader and the job queue are
fakes. Every adapter is the production one, wired exactly as
``main.py``'s ``reconciliation.prepare_booking`` handler wires it, so a test
that drives ``build_handler`` exercises the same objects the worker runs.

Symbols follow R21 on purpose: the ledger's open fill and its execution
attempt are ``STXUSDT.P``, the discrepancy row and the venue's fills are
``STXUSDT``. Every id and fill id is random, because ``ledger_entries`` and
``execution_attempts`` are append-only (migration 0005 refuses a TRUNCATE) and
are never cleared between tests.
"""

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.ledger.application.read_recorded_fill_ids import ReadRecordedFillIds
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.application.announce_needs_owner import (
    AnnounceNeedsOwner,
    reset_announcements,
)
from strategy_manager.reconciliation.application.approve_booking import ApproveBooking
from strategy_manager.reconciliation.application.auto_book_pending import AutoBookPending
from strategy_manager.reconciliation.application.booking_prepare_handler import (
    BookingPrepareHandler,
    last_reason_by_discrepancy,
)
from strategy_manager.reconciliation.application.expire_booking_proposals import (
    ExpireBookingProposals,
)
from strategy_manager.reconciliation.application.ports import (
    BookingProposalRecord,
    NewBookingProposal,
    PoolKey,
    ProposedFillSnapshot,
    VenueFill,
)
from strategy_manager.reconciliation.application.prepare_booking import PrepareBooking
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind
from strategy_manager.reconciliation.infrastructure.allocation_owner_adapter import (
    AllocationOwnerAdapter,
)
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.reconciliation.infrastructure.booking_writer import (
    SqlAlchemyBookingWriter,
)
from strategy_manager.reconciliation.infrastructure.in_flight_close_adapter import (
    InFlightCloseAdapter,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from strategy_manager.reconciliation.infrastructure.system_order_ids_adapter import (
    SystemOrderIdsAdapter,
)
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.config import get_settings
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)
from tests.owner import OWNER_ID
from tests.pg_drop import drop_database_if_exists

BACKEND_DIR = Path(__file__).resolve().parents[3]

POOL: PoolKey = ("bybit", "usdt-m", "USDT")

# R21: the ledger's open fill and its attempt are TradingView's spelling, the
# discrepancy row and the venue's fills are the bare market key.
LEDGER_SYMBOL = "STXUSDT.P"
MARKET_SYMBOL = "STXUSDT"

LEDGER_FILLED_AT = datetime(2026, 9, 23, 10, 0, 0, tzinfo=UTC)
VENUE_FILLED_AT = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
FIRST_OBSERVED_AT = datetime(2026, 9, 23, 12, 30, 0, tzinfo=UTC)
CONFIRMED_AT = datetime(2026, 9, 23, 12, 59, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 23, 13, 0, 0, tzinfo=UTC)

GRACE_SECONDS = 3600
REMINDER_SECONDS = 86400


# --- A throwaway database per test module ------------------------------------


def _maintenance_dsn(dev_url: str) -> str:
    dsn = dev_url.replace("postgresql+asyncpg://", "postgresql://")
    return re.sub(r"/[^/?]+(\?.*)?$", r"/postgres\1", dsn)


def _database_url(dev_url: str, name: str) -> str:
    return re.sub(r"/[^/?]+(\?.*)?$", rf"/{name}\1", dev_url)


async def _create_database(maintenance_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def _run_alembic(database_url: str, *args: str) -> None:
    """Runs alembic in a subprocess so its own ``asyncio.run`` never collides
    with the test's already-running loop."""

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")


def throwaway_database(name: str) -> Iterator[str]:
    """Yields the URL of a freshly migrated database called ``name`` and drops
    it afterwards. A module's ``database_url`` fixture delegates to it."""

    dev_url = get_settings().database_url
    maintenance_dsn = _maintenance_dsn(dev_url)
    url = _database_url(dev_url, name)

    asyncio.run(drop_database_if_exists(maintenance_dsn, name))
    asyncio.run(_create_database(maintenance_dsn, name))
    _run_alembic(url, "upgrade", "head")

    yield url

    asyncio.run(drop_database_if_exists(maintenance_dsn, name))


def reset_process_memory() -> None:
    """The announcement memory and the last-reason map are process-wide by
    design (one handler is built per job), so every test starts them empty."""

    reset_announcements()
    last_reason_by_discrepancy.clear()


# --- Fakes -------------------------------------------------------------------


class FrozenClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class FixedUsdRate:
    async def usd_rate(self, currency: object) -> Decimal:
        return Decimal("1")


class SessionCommit:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()


class RecordingQueue:
    """Records the successor the handler enqueues; the job table is not under
    test here."""

    def __init__(self) -> None:
        self.enqueued: list[Job] = []

    async def enqueue(self, job: Job) -> UUID:
        self.enqueued.append(job)
        return uuid4()


class FakeVenueFillReader:
    """The venue's fills for the market. ``fills`` can be replaced between runs."""

    def __init__(self, fills: Sequence[VenueFill]) -> None:
        self.fills = list(fills)
        self.calls = 0

    async def fills_in_window(
        self, pool: PoolKey, symbol: str, start: datetime, end: datetime
    ) -> list[VenueFill]:
        self.calls += 1
        return list(self.fills)


class FakeVenueFillReaderRegistry:
    def __init__(self, reader: FakeVenueFillReader) -> None:
        self._reader = reader

    def for_pool(self, exchange: str, venue: str) -> FakeVenueFillReader:
        return self._reader


def venue_fill(quantity: str, *, side: str = "SELL", price: str = "2.6") -> VenueFill:
    """A fill spelled the way the venue spells the market (``STXUSDT``)."""

    return VenueFill(
        exchange_fill_id=f"VF-{uuid4()}",
        exchange_order_id=f"VO-{uuid4()}",
        symbol=MARKET_SYMBOL,
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal("0"),
        fee_currency="USDT",
        filled_at=VENUE_FILLED_AT,
    )


def claimed_job() -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(),
        kind=JobKind.RECONCILIATION_PREPARE_BOOKING,
        payload={},
        attempts=1,
        max_attempts=5,
    )


# --- The real wiring ---------------------------------------------------------


def build_approve_booking(
    session: AsyncSession,
    *,
    at: datetime = NOW,
    dry_run: bool = False,
    commit: object | None = None,
    proposals: SqlAlchemyBookingProposalRepository | None = None,
) -> ApproveBooking:
    """``ApproveBooking`` wired as ``main.py`` wires it. ``commit`` and
    ``proposals`` can be replaced by a test that needs to hold or alter one
    step; every other collaborator stays the production adapter."""

    return ApproveBooking(
        proposals=proposals or SqlAlchemyBookingProposalRepository(session),
        discrepancies=SqlAlchemyDiscrepancyRepository(session),
        in_flight_close=InFlightCloseAdapter(session),
        writer=SqlAlchemyBookingWriter(session),
        usd_rate_provider=FixedUsdRate(),
        clock=FrozenClock(at),
        commit=commit or SessionCommit(session),  # type: ignore[arg-type]
        dry_run=dry_run,
    )


def build_prepare_booking(
    session: AsyncSession, reader: FakeVenueFillReader, *, at: datetime = NOW
) -> PrepareBooking:
    return PrepareBooking(
        discrepancies=SqlAlchemyDiscrepancyRepository(session),
        proposals=SqlAlchemyBookingProposalRepository(session),
        venue_fills=FakeVenueFillReaderRegistry(reader),
        recorded_fill_ids=ReadRecordedFillIds(SqlAlchemyLedgerRepository(session)),
        allocation_owner=AllocationOwnerAdapter(session),
        clock=FrozenClock(at),
        commit=SessionCommit(session),
        window_pad_seconds=300,
        max_span_seconds=604800,
        proposal_expiry_seconds=86400,
        dry_run=False,
        system_order_ids=SystemOrderIdsAdapter(session),
        pool_users={POOL: OWNER_ID},
    )


def build_handler(
    session: AsyncSession,
    reader: FakeVenueFillReader,
    queue: RecordingQueue,
    *,
    at: datetime = NOW,
    dry_run: bool = False,
    approve_at: datetime | None = None,
) -> BookingPrepareHandler:
    """``BookingPrepareHandler`` with the object graph of ``main.py``'s
    ``handle_reconciliation_prepare_booking``: one session, the production
    adapters, the clock frozen at ``at``. ``approve_at`` moves only the
    approval's clock later, which models a proposal that goes stale between
    the expiry step and the automatic step of one job."""

    return BookingPrepareHandler(
        prepare_booking=build_prepare_booking(session, reader, at=at),
        expire_booking_proposals=ExpireBookingProposals(
            proposals=SqlAlchemyBookingProposalRepository(session),
            clock=FrozenClock(at),
            commit=SessionCommit(session),
        ),
        auto_book=AutoBookPending(
            proposals=SqlAlchemyBookingProposalRepository(session),
            approver=build_approve_booking(session, at=approve_at or at, dry_run=dry_run),
        ),
        announce_needs_owner=AnnounceNeedsOwner(
            discrepancies=SqlAlchemyDiscrepancyRepository(session),
            approved=SqlAlchemyBookingProposalRepository(session),
            clock=FrozenClock(at),
            grace_seconds=GRACE_SECONDS,
            reminder_seconds=REMINDER_SECONDS,
        ),
        queue=queue,
        clock=FrozenClock(at),
        interval_seconds=60,
        dry_run=dry_run,
    )


async def run_job(
    session_factory: async_sessionmaker[AsyncSession],
    reader: FakeVenueFillReader,
    queue: RecordingQueue,
    *,
    at: datetime = NOW,
    dry_run: bool = False,
    approve_at: datetime | None = None,
) -> None:
    """One claimed job, the way the worker runs it: one session, the handler,
    a final commit."""

    async with session_factory() as session:
        handler = build_handler(
            session, reader, queue, at=at, dry_run=dry_run, approve_at=approve_at
        )
        await handler.handle(claimed_job())
        await session.commit()


# --- Seeding -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scenario:
    strategy_id: UUID
    allocation_id: UUID
    discrepancy_id: UUID


async def seed_open_allocation(
    session_factory: async_sessionmaker[AsyncSession], *, quantity: str
) -> tuple[UUID, UUID]:
    """A strategy, its FILLED reservation (the allocation) and one OPEN ledger
    BUY of ``quantity`` under ``LEDGER_SYMBOL``."""

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
        symbol=LEDGER_SYMBOL,
        status="FILLED",
    )
    async with session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            FillRecord(
                user_id=OWNER_ID,
                strategy_id=strategy_id,
                allocation_id=reservation_id,
                execution_attempt_id=attempt_id,
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                symbol=LEDGER_SYMBOL,
                side="BUY",
                quantity=Decimal(quantity),
                price=Decimal("2.5"),
                fee=Decimal("0"),
                fee_currency="USDT",
                notional=Decimal(quantity) * Decimal("2.5"),
                exchange_order_id=f"OPEN-{attempt_id}",
                exchange_fill_id=f"OPENFILL-{attempt_id}",
                filled_at=LEDGER_FILLED_AT,
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()
    return strategy_id, reservation_id


async def seed_confirmed_discrepancy(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    allocation_id: UUID,
    kind: DiscrepancyKind,
    venue_net: str,
    ledger_net: str,
    confirmed_at: datetime = CONFIRMED_AT,
    symbol: str = MARKET_SYMBOL,
) -> UUID:
    """A CONFIRMED, open discrepancy row for ``symbol`` (``MARKET_SYMBOL`` by
    default; only one open row exists per market, so a second one in the same
    test names another)."""

    discrepancy_id, scan_id = uuid4(), uuid4()
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO reconciliation_discrepancies "
                "(id, exchange, venue, settlement_currency, symbol, kind, "
                "venue_net_base, ledger_net_base, open_allocation_ids, status, "
                "first_observed_at, last_observed_at, confirmed_at, "
                "first_scan_id, last_scan_id) "
                "VALUES (:id, :exchange, :venue, :settlement_currency, :symbol, :kind, "
                ":venue_net, :ledger_net, ARRAY[:allocation_id]::uuid[], 'CONFIRMED', "
                ":first_observed_at, :first_observed_at, :confirmed_at, :scan_id, :scan_id)"
            ),
            {
                "id": discrepancy_id,
                "exchange": POOL[0],
                "venue": POOL[1],
                "settlement_currency": POOL[2],
                "symbol": symbol,
                "kind": kind.value,
                "venue_net": Decimal(venue_net),
                "ledger_net": Decimal(ledger_net),
                "allocation_id": allocation_id,
                "first_observed_at": FIRST_OBSERVED_AT,
                "confirmed_at": confirmed_at,
                "scan_id": scan_id,
            },
        )
        await session.commit()
    return discrepancy_id


async def seed_scenario(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    ledger_net: str = "0.5",
    venue_net: str = "0",
    kind: DiscrepancyKind = DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
    symbol: str = MARKET_SYMBOL,
) -> Scenario:
    strategy_id, allocation_id = await seed_open_allocation(
        session_factory, quantity=ledger_net
    )
    discrepancy_id = await seed_confirmed_discrepancy(
        session_factory,
        allocation_id=allocation_id,
        kind=kind,
        venue_net=venue_net,
        ledger_net=ledger_net,
        symbol=symbol,
    )
    return Scenario(strategy_id, allocation_id, discrepancy_id)


async def insert_pending_proposal(
    session_factory: async_sessionmaker[AsyncSession],
    scenario: Scenario,
    *,
    kind: DiscrepancyKind = DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
    venue_net: str = "0",
    ledger_net: str = "0.5",
    quantity: str = "0.5",
    expires_at: datetime | None = None,
    without_order_id: bool = False,
) -> BookingProposalRecord:
    """A PENDING proposal frozen the way a sweep freezes it, for a test that
    needs one "left behind" without running a sweep. ``without_order_id``
    freezes a fill the venue gave no order id, which approval refuses with an
    ``InvariantViolation`` (the ledger column is NOT NULL)."""

    fill_id = f"VFILL-{uuid4()}"
    async with session_factory() as session:
        inserted = await SqlAlchemyBookingProposalRepository(session).insert(
            NewBookingProposal(
                discrepancy_id=scenario.discrepancy_id,
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                symbol=MARKET_SYMBOL,
                kind=kind,
                allocation_id=scenario.allocation_id,
                strategy_id=scenario.strategy_id,
                side="SELL",
                quantity=Decimal(quantity),
                observed_venue_net_base=Decimal(venue_net),
                observed_ledger_net_base=Decimal(ledger_net),
                observed_allocation_ids=[scenario.allocation_id],
                fills=[
                    ProposedFillSnapshot(
                        exchange_fill_id=fill_id,
                        exchange_order_id=None if without_order_id else f"VORD-{fill_id}",
                        side="SELL",
                        quantity=Decimal(quantity),
                        price=Decimal("2.6"),
                        fee=Decimal("0"),
                        fee_currency="USDT",
                        filled_at=VENUE_FILLED_AT,
                    )
                ],
                client_order_id=f"vnu:{POOL[0]}:fill:{fill_id}",
                expires_at=expires_at or (NOW + timedelta(hours=24)),
                prepared_by_job_id=uuid4(),
            )
        )
        await session.commit()
    assert inserted is not None
    return inserted


# --- Reading -----------------------------------------------------------------

# The tables a refused or skipped job must leave exactly as it found them.
# The names are constants of this module, never user input.
WRITE_TABLES = (
    "booking_proposals",
    "execution_attempts",
    "ledger_entries",
    "reconciliation_discrepancies",
)


async def snapshot_tables(
    session_factory: async_sessionmaker[AsyncSession], tables: Sequence[str] = WRITE_TABLES
) -> dict[str, list[str]]:
    """Every row, every column, of each table, as sorted JSON text. Two
    snapshots are equal only when no row was added, removed or altered."""

    snapshot: dict[str, list[str]] = {}
    async with session_factory() as session:
        for table in tables:
            rows = await session.execute(
                text(f"SELECT to_jsonb(t)::text FROM {table} t ORDER BY 1")  # noqa: S608
            )
            snapshot[table] = [row[0] for row in rows.all()]
    return snapshot


async def proposals_of(
    session_factory: async_sessionmaker[AsyncSession], discrepancy_id: UUID
) -> list[tuple[UUID, str, str | None]]:
    """``(id, state, decided_by)`` of every proposal of a discrepancy, oldest
    first."""

    async with session_factory() as session:
        rows = await session.execute(
            text(
                "SELECT id, state, decided_by FROM booking_proposals "
                "WHERE discrepancy_id = :id ORDER BY created_at, id"
            ),
            {"id": discrepancy_id},
        )
        return [(row[0], row[1], row[2]) for row in rows.all()]


async def write_counts(
    session_factory: async_sessionmaker[AsyncSession], allocation_id: UUID
) -> tuple[int, int]:
    """``(attempts, ledger rows)`` a booking could have written for this
    allocation: ledger rows are scoped to ``SELL`` to leave out the seeded
    OPEN ``BUY``."""

    async with session_factory() as session:
        attempts = (
            await session.execute(
                text("SELECT count(*) FROM execution_attempts WHERE closes_allocation_id = :aid"),
                {"aid": allocation_id},
            )
        ).scalar_one()
        ledger_rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM ledger_entries "
                    "WHERE allocation_id = :aid AND side = 'SELL'"
                ),
                {"aid": allocation_id},
            )
        ).scalar_one()
    return int(attempts), int(ledger_rows)


async def held_base(
    session_factory: async_sessionmaker[AsyncSession], strategy_id: UUID
) -> Decimal:
    """What the strategy still holds of the market, read the way the
    Existing-Position Guard reads it (any spelling of the market)."""

    async with session_factory() as session:
        holdings = await SqlAlchemyLedgerRepository(session).symbol_holdings(
            OWNER_ID, POOL[0], POOL[1], POOL[2], MARKET_SYMBOL
        )
    return sum(
        (h.net_base for h in holdings if h.strategy_id == strategy_id), start=Decimal("0")
    )
