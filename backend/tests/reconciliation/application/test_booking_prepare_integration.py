"""Tier B: ``PrepareBooking`` driven end to end, scan -> CONFIRMED -> prepare
-> one PENDING ``booking_proposals`` row, against a real ``alembic upgrade
head`` database (design.md's component inventory; Unit 5, tasks.md 5.4).

Only the venue is faked -- no test here requires a real API credential
(CLAUDE.md rule 1). Everything downstream is the real production wiring:
``ScanPools``/``SqlAlchemyDiscrepancyRepository`` land the CONFIRMED row the
same way ``test_scan_pools_integration.py`` proves, and
``SqlAlchemyBookingProposalRepository``/``ReadRecordedFillIds``/
``AllocationOwnerAdapter`` are the exact adapters ``main.py``'s
``handle_reconciliation_prepare_booking`` wires.

The proposal's whole point is that NOTHING reaches the ledger at prepare
time -- this file's central assertion is that ``ledger_entries`` and
``execution_attempts`` are byte-identical (same row counts, same content)
before and after a sweep that DID produce a proposal.

Follows the same throwaway-database, real-Postgres pattern as
``test_scan_pools_integration.py``, with its own dedicated database so the
two files never race each other's schema.
"""

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator, Sequence
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
from strategy_manager.ledger.application.read_symbol_positions import ReadSymbolPositions
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.application.ports import (
    PoolKey,
    VenueFill,
)
from strategy_manager.reconciliation.application.prepare_booking import (
    PrepareBooking,
    PrepareBookingResult,
)
from strategy_manager.reconciliation.application.scan_pools import ScanPools
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind, DiscrepancyStatus
from strategy_manager.reconciliation.domain.positions import VenuePosition
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
_DB_NAME = "strategy_manager_test_booking_prepare"

# Migration 0003 seeds this pool (backfilled to ``exchange='bybit'`` by
# migration 0017/0018) -- no additional pool needs inserting.
POOL: PoolKey = ("bybit", "usdt-m", "USDT")
FILLED_AT = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
SCAN_1_AT = datetime(2026, 9, 23, 13, 0, 0, tzinfo=UTC)
SCAN_2_AT = datetime(2026, 9, 23, 13, 0, 30, tzinfo=UTC)
PREPARE_AT = datetime(2026, 9, 23, 13, 1, 0, tzinfo=UTC)

# Spelling regression rule (design.md § 13): the ledger fixture uses
# TradingView's perpetual spelling, the fake venue answers with its own bare
# spelling -- every cross-boundary test in this slice uses a DIFFERENT
# spelling on each side.
LEDGER_SYMBOL = "STXUSDT.P"
VENUE_SYMBOL = "STXUSDT"


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
        raise RuntimeError(
            f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
        )


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
        # CASCADE: booking_proposals FKs into this table (no ON DELETE
        # CASCADE on that FK itself, per 0023's own docstring, but a plain
        # TRUNCATE still refuses without one here).
        await conn.execute(text("TRUNCATE reconciliation_discrepancies CASCADE"))


# --- Test doubles: only the venue is fake -----------------------------------


class _FakeVenuePositionReader:
    def __init__(self, positions: Sequence[VenuePosition]) -> None:
        self._positions = list(positions)

    async def open_positions(self, pool: PoolKey) -> list[VenuePosition]:
        return list(self._positions)


class _FakeVenuePositionReaderRegistry:
    def __init__(self, reader: _FakeVenuePositionReader) -> None:
        self._reader = reader

    def for_pool(self, exchange: str, venue: str) -> _FakeVenuePositionReader:
        return self._reader


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


class _FrozenClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class _SessionCommit:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()


async def _seed_allocation(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID, UUID]:
    strategy_id, signal_id = uuid4(), uuid4()
    reservation_id, attempt_id = uuid4(), uuid4()

    await seed_strategy(session_factory, strategy_id=strategy_id)
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
    )
    await seed_execution_attempt(
        session_factory, attempt_id=attempt_id, reservation_id=reservation_id
    )
    return strategy_id, reservation_id, attempt_id


def _fill(
    *,
    strategy_id: UUID,
    allocation_id: UUID,
    attempt_id: UUID,
    quantity: str,
    symbol: str = LEDGER_SYMBOL,
) -> FillRecord:
    price = Decimal("2.5")
    return FillRecord(
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        execution_attempt_id=attempt_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=symbol,
        side="BUY",
        quantity=Decimal(quantity),
        price=price,
        fee=Decimal("0"),
        fee_currency="USDT",
        notional=Decimal(quantity) * price,
        exchange_order_id=f"EX-{uuid4()}",
        exchange_fill_id=f"F-{uuid4()}",
        filled_at=FILLED_AT,
        usd_rate_at_fill=Decimal("1"),
    )


async def _scan(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    venue_positions: Sequence[VenuePosition],
    scan_id: UUID,
    at: datetime,
) -> None:
    async with session_factory() as session:
        use_case = ScanPools(
            pools=[POOL],
            venue_readers=_FakeVenuePositionReaderRegistry(
                _FakeVenuePositionReader(venue_positions)
            ),
            ledger_positions=ReadSymbolPositions(SqlAlchemyLedgerRepository(session)),
            discrepancies=SqlAlchemyDiscrepancyRepository(session),
            clock=_FrozenClock(at),
            commit=_SessionCommit(session),
            confirmations_required=2,
        )
        await use_case.scan(scan_id)


async def _confirmed_discrepancy_id(
    session_factory: async_sessionmaker[AsyncSession], *, symbol: str
) -> UUID:
    async with session_factory() as session:
        records = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(
            pool=POOL, status=DiscrepancyStatus.CONFIRMED, open_only=True
        )
    matching = [record for record in records if record.symbol == symbol]
    assert len(matching) == 1
    return matching[0].id


async def _prepare(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    fill_reader: _FakeVenueFillReader,
    job_id: UUID,
    at: datetime,
) -> PrepareBookingResult:
    async with session_factory() as session:
        use_case = PrepareBooking(
            discrepancies=SqlAlchemyDiscrepancyRepository(session),
            proposals=SqlAlchemyBookingProposalRepository(session),
            venue_fills=_FakeVenueFillReaderRegistry(fill_reader),
            recorded_fill_ids=ReadRecordedFillIds(SqlAlchemyLedgerRepository(session)),
            allocation_owner=AllocationOwnerAdapter(session),
            clock=_FrozenClock(at),
            commit=_SessionCommit(session),
            window_pad_seconds=300,
            max_span_seconds=604800,
            proposal_expiry_seconds=86400,
            dry_run=False,
        )
        return await use_case.sweep(job_id)


_LEDGER_TABLES = ("ledger_entries", "execution_attempts")


async def _snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, list[tuple[object, ...]]]:
    """Every row of both tables, ordered by ``id`` -- content, not only a
    count, so a byte-identical claim actually means something."""

    async with session_factory() as session:
        snapshot: dict[str, list[tuple[object, ...]]] = {}
        for table in _LEDGER_TABLES:
            result = await session.execute(text(f"SELECT * FROM {table} ORDER BY id"))  # noqa: S608
            snapshot[table] = [tuple(row) for row in result.all()]
        return snapshot


async def _pending_proposals(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[object]:
    async with session_factory() as session:
        return await SqlAlchemyBookingProposalRepository(session).list_pending()


# --- The end-to-end path: scan -> CONFIRMED -> prepare -> one proposal ------


async def test_end_to_end_scan_to_prepared_proposal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_allocation(session_factory)

    async with session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                quantity="0.5",
            )
        )
        await session.commit()

    # Two scans, confirmations_required=2, so the second lands CONFIRMED --
    # exactly ``test_scan_pools_integration.py``'s own OBSERVED -> CONFIRMED
    # transition, reused here rather than re-proven.
    await _scan(
        session_factory,
        venue_positions=[VenuePosition(VENUE_SYMBOL, Decimal("0"))],
        scan_id=uuid4(),
        at=SCAN_1_AT,
    )
    await _scan(
        session_factory,
        venue_positions=[VenuePosition(VENUE_SYMBOL, Decimal("0"))],
        scan_id=uuid4(),
        at=SCAN_2_AT,
    )

    discrepancy_id = await _confirmed_discrepancy_id(session_factory, symbol=VENUE_SYMBOL)

    before = await _snapshot(session_factory)

    fill_reader = _FakeVenueFillReader(
        [
            VenueFill(
                exchange_fill_id=f"VF-{uuid4()}",
                exchange_order_id=f"VO-{uuid4()}",
                symbol=VENUE_SYMBOL,
                side="SELL",
                quantity=Decimal("0.5"),
                price=Decimal("2.6"),
                fee=Decimal("0"),
                fee_currency="USDT",
                filled_at=FILLED_AT + timedelta(hours=1),
            )
        ]
    )
    job_id = uuid4()
    result = await _prepare(
        session_factory, fill_reader=fill_reader, job_id=job_id, at=PREPARE_AT
    )

    assert result.discrepancies_considered == 1
    assert result.proposals_prepared == 1
    assert result.proposals_skipped == 0
    assert result.proposals_suppressed == 0

    pending = await _pending_proposals(session_factory)
    assert len(pending) == 1
    proposal = pending[0]
    assert proposal.discrepancy_id == discrepancy_id
    assert proposal.exchange == "bybit"
    assert proposal.venue == "usdt-m"
    assert proposal.settlement_currency == "USDT"
    # The frozen symbol is the MARKET KEY, never the venue's own spelling
    # nor the ledger's TradingView spelling -- design.md § 13.
    assert proposal.symbol == VENUE_SYMBOL
    assert proposal.kind is DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE
    assert proposal.allocation_id == allocation_id
    assert proposal.strategy_id == strategy_id
    assert proposal.side == "SELL"
    assert proposal.quantity == Decimal("0.5")
    assert proposal.state == "PENDING"
    assert proposal.prepared_by_job_id == job_id
    assert len(proposal.fills) == 1

    # The whole point of PREPARE: nothing reached the ledger. Row-for-row
    # identical, not merely equal counts.
    after = await _snapshot(session_factory)
    assert after == before

    # A second sweep over the SAME still-open, still-CONFIRMED discrepancy
    # must not produce a second proposal --
    # ``ux_booking_proposals_pending_per_discrepancy`` (migration 0023) is
    # prepare's own idempotency, and ``insert() -> None`` is the expected,
    # non-raising outcome ``PrepareBooking`` logs at INFO rather than WARNING.
    # Reusing THIS test's own discrepancy (rather than a second, separately
    # seeded one) deliberately avoids any cross-test dependence on the
    # append-only ledger tables, which nothing here can truncate between
    # tests (migration 0005's ``trg_ledger_no_truncate``).
    second = await _prepare(
        session_factory,
        fill_reader=fill_reader,
        job_id=uuid4(),
        at=PREPARE_AT + timedelta(minutes=1),
    )
    assert second.discrepancies_considered == 1
    assert second.proposals_prepared == 0

    pending_after_second = await _pending_proposals(session_factory)
    assert len(pending_after_second) == 1
    assert pending_after_second[0].id == proposal.id
