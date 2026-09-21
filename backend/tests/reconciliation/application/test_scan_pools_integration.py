"""Tier B: ``ScanPools`` driven end to end against a real ``alembic upgrade
head`` database (spec: reconcile-venue-fills, unit 1 phase 6).

Only the venue reader is faked — no test here requires a real API credential
(CLAUDE.md rule 1). Everything downstream of it is the real production wiring:
``ReadSymbolPositions``/``SqlAlchemyLedgerRepository`` project real
``ledger_entries`` rows into ``LedgerPosition``s, and
``SqlAlchemyDiscrepancyRepository`` writes the verdict through the real
partial unique index and CHECK constraints migration ``0020`` installs.

Follows the same throwaway-database pattern as
``tests/reconciliation/infrastructure/test_discrepancy_repository_integration
.py`` and ``tests/migrations/test_0020_reconciliation_discrepancies.py``: a
dedicated database, migrated to head, dropped at teardown.

The two scenarios in the first half of this file are exactly the two the
spec phase originally shipped without any end-to-end coverage at all
(``ATTRIBUTABLE_FULL_CLOSE`` and ``NO_MATCHING_ALLOCATION``); the third
section drives the ``OBSERVED`` -> ``CONFIRMED`` transition, and the
consecutive-scans reset, across three real scans against the same repository.
"""

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import UTC, datetime
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
from strategy_manager.ledger.application.read_symbol_positions import ReadSymbolPositions
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.application.ports import (
    DiscrepancyRecord,
    PoolKey,
)
from strategy_manager.reconciliation.application.scan_pools import ScanPools
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
)
from strategy_manager.reconciliation.domain.positions import (
    LedgerPosition,
    OpenAllocation,
    VenuePosition,
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
_DB_NAME = "strategy_manager_test_reconciliation_scan"

# Migration 0003 seeds this pool (backfilled to ``exchange='bybit'`` by
# migration 0017/0018) -- no additional pool needs inserting.
POOL: PoolKey = ("bybit", "usdt-m", "USDT")
FILLED_AT = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 18, 13, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 18, 14, 0, 0, tzinfo=UTC)
EVEN_LATER = datetime(2026, 9, 18, 15, 0, 0, tzinfo=UTC)


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
        await conn.execute(text("TRUNCATE reconciliation_discrepancies"))


# --- Test doubles: only the venue is fake -----------------------------------


class _FakeVenueReader:
    def __init__(self, positions: Sequence[VenuePosition] = ()) -> None:
        self._positions = list(positions)

    async def open_positions(self, pool: PoolKey) -> list[VenuePosition]:
        return list(self._positions)


class _FakeVenueReaderRegistry:
    def __init__(self, reader: _FakeVenueReader) -> None:
        self._reader = reader

    def for_pool(self, exchange: str, venue: str) -> _FakeVenueReader:
        return self._reader


class _FakeLedgerPositions:
    """Used only by the OBSERVED -> CONFIRMED scenario, so the ledger side of
    the comparison can be held fixed across scans while only the venue's
    report changes -- isolating what moved."""

    def __init__(self, positions: Sequence[LedgerPosition]) -> None:
        self._positions = list(positions)

    async def net_positions_by_symbol(self, pool: PoolKey) -> list[LedgerPosition]:
        return list(self._positions)


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
    symbol: str,
    side: str,
    quantity: str,
) -> FillRecord:
    price = Decimal("50000")
    return FillRecord(
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        execution_attempt_id=attempt_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=symbol,
        side=side,
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


async def _delta_base(
    session_factory: async_sessionmaker[AsyncSession], record_id: UUID
) -> Decimal:
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT delta_base FROM reconciliation_discrepancies WHERE id = :id"),
            {"id": record_id},
        )
        return result.scalar_one()


async def _open_records(
    session_factory: async_sessionmaker[AsyncSession], *, symbol: str
) -> list[DiscrepancyRecord]:
    async with session_factory() as session:
        records = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(
            pool=POOL, open_only=True
        )
    return [record for record in records if record.symbol == symbol]


_FORBIDDEN_TABLES = (
    "ledger_entries",
    "execution_attempts",
    # A pool's available capital is not a stored column: it is derived from the
    # latest balance snapshot minus the active reservations. So "MUST NOT alter
    # available" is asserted against the two tables it is actually derived
    # from, which is where a violation would have to land.
    "pool_balance_snapshots",
    "reservations",
)


async def _write_boundary_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, int]:
    """Everything the scan is forbidden to touch, in one reading."""

    async with session_factory() as session:
        return {
            table: (
                await session.execute(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
            ).scalar_one()
            for table in _FORBIDDEN_TABLES
        }


async def _scan(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    venue_positions: Sequence[VenuePosition],
    scan_id: UUID,
    at: datetime,
    confirmations_required: int = 2,
    ledger_positions: _FakeLedgerPositions | None = None,
) -> None:
    async with session_factory() as session:
        use_case = ScanPools(
            pools=[POOL],
            venue_readers=_FakeVenueReaderRegistry(_FakeVenueReader(venue_positions)),
            ledger_positions=(
                ledger_positions
                if ledger_positions is not None
                else ReadSymbolPositions(SqlAlchemyLedgerRepository(session))
            ),
            discrepancies=SqlAlchemyDiscrepancyRepository(session),
            clock=_FrozenClock(at),
            commit=_SessionCommit(session),
            confirmations_required=confirmations_required,
        )
        await use_case.scan(scan_id)


# --- Scenario: ATTRIBUTABLE_FULL_CLOSE, two allocations, venue at zero ------


async def test_two_open_allocations_and_a_zero_venue_report_land_a_full_close(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    symbol = "BTCUSDT"
    # ``ledger_entries.allocation_id`` FKs to ``reservations.id`` -- the
    # reservation IS the allocation, mirroring
    # ``test_symbol_positions_integration.py``'s own ``_seed_position``.
    strategy_id_a, allocation_id_a, attempt_id_a = await _seed_allocation(session_factory)
    strategy_id_b, allocation_id_b, attempt_id_b = await _seed_allocation(session_factory)

    async with session_factory() as session:
        recorder = RecordFill(SqlAlchemyLedgerRepository(session))
        await recorder.record(
            _fill(
                strategy_id=strategy_id_a,
                allocation_id=allocation_id_a,
                attempt_id=attempt_id_a,
                symbol=symbol,
                side="BUY",
                quantity="0.002",
            )
        )
        await recorder.record(
            _fill(
                strategy_id=strategy_id_b,
                allocation_id=allocation_id_b,
                attempt_id=attempt_id_b,
                symbol=symbol,
                side="BUY",
                quantity="0.003",
            )
        )
        await session.commit()

    scan_id = uuid4()
    await _scan(
        session_factory,
        venue_positions=[VenuePosition(symbol, Decimal("0"))],
        scan_id=scan_id,
        at=NOW,
    )

    records = await _open_records(session_factory, symbol=symbol)
    assert len(records) == 1
    record = records[0]
    assert record.kind is DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE
    assert set(record.open_allocation_ids) == {allocation_id_a, allocation_id_b}
    assert record.venue_net_base == Decimal("0")
    assert record.ledger_net_base == Decimal("0.005")
    assert record.first_scan_id == scan_id
    assert record.last_scan_id == scan_id

    delta = await _delta_base(session_factory, record.id)
    assert delta == Decimal("0") - Decimal("0.005")


# --- Scenario: NO_MATCHING_ALLOCATION, venue open, ledger has nothing -------


async def test_a_venue_position_with_no_open_allocation_lands_unattributable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    symbol = "ETHUSDT"
    scan_id = uuid4()

    await _scan(
        session_factory,
        venue_positions=[VenuePosition(symbol, Decimal("1.2"))],
        scan_id=scan_id,
        at=NOW,
    )

    records = await _open_records(session_factory, symbol=symbol)
    assert len(records) == 1
    record = records[0]
    assert record.kind is DiscrepancyKind.NO_MATCHING_ALLOCATION
    assert record.open_allocation_ids == ()
    assert record.venue_net_base == Decimal("1.2")
    assert record.ledger_net_base == Decimal("0")


# --- Scenario: OBSERVED -> CONFIRMED -> reset, three real scans ------------


async def test_the_transition_to_confirmed_and_the_reset_on_a_changed_quantity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    symbol = "ADAUSDT"
    scan_id_1, scan_id_2, scan_id_3 = uuid4(), uuid4(), uuid4()
    # One open allocation, held fixed across every scan below -- only the
    # venue's own report changes, so the observation's movement (or lack of
    # it) is attributable to the venue side alone.
    allocation_id = uuid4()
    ledger = _FakeLedgerPositions(
        [LedgerPosition(symbol, (OpenAllocation(allocation_id, Decimal("1.5")),))]
    )

    # Scan 1: the disagreement appears for the first time.
    await _scan(
        session_factory,
        venue_positions=[VenuePosition(symbol, Decimal("2.0"))],
        scan_id=scan_id_1,
        at=NOW,
        ledger_positions=ledger,
    )

    records = await _open_records(session_factory, symbol=symbol)
    assert len(records) == 1
    first_record = records[0]
    assert first_record.kind is DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION
    assert first_record.consecutive_scans == 1
    assert first_record.status is DiscrepancyStatus.OBSERVED
    assert first_record.confirmed_at is None
    row_id = first_record.id

    # Scan 2: the SAME disagreement, identical in kind and both quantities.
    # The partial unique index means this lands on the SAME row.
    await _scan(
        session_factory,
        venue_positions=[VenuePosition(symbol, Decimal("2.0"))],
        scan_id=scan_id_2,
        at=LATER,
        ledger_positions=ledger,
    )

    records = await _open_records(session_factory, symbol=symbol)
    assert len(records) == 1
    second_record = records[0]
    assert second_record.id == row_id
    assert second_record.consecutive_scans == 2
    assert second_record.status is DiscrepancyStatus.CONFIRMED
    assert second_record.confirmed_at is not None
    confirmed_at = second_record.confirmed_at

    # Scan 3: still a disagreement, but the venue quantity differs. Design
    # decision 6: a changing quantity is movement, so the count resets to 1.
    await _scan(
        session_factory,
        venue_positions=[VenuePosition(symbol, Decimal("2.5"))],
        scan_id=scan_id_3,
        at=EVEN_LATER,
        ledger_positions=ledger,
    )

    records = await _open_records(session_factory, symbol=symbol)
    assert len(records) == 1
    third_record = records[0]
    assert third_record.id == row_id
    assert third_record.consecutive_scans == 1
    # The demotion itself, asserted against the database rather than inferred
    # from the counter: a moved observation puts the row back to OBSERVED, and
    # only a CONFIRMED row is ever acted on.
    assert third_record.status is DiscrepancyStatus.OBSERVED
    # ``confirmed_at`` is set exactly once and never overwritten or cleared
    # by a later scan (``ck_reconciliation_discrepancies_confirmed_at`` and
    # the repository's own coalesce). This row is the pair the CHECK's one-way
    # implication exists to permit: OBSERVED, still carrying the timestamp of
    # the confirmation it earned earlier.
    assert third_record.confirmed_at == confirmed_at


# --- The detection-only write boundary, asserted rather than assumed ---------


async def test_a_scan_that_records_a_discrepancy_writes_nowhere_else(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The scan MUST NOT write to ledger_entries or execution_attempts, and
    MUST NOT alter a pool's available balance.

    ``ScanPools`` holds no port capable of any of those writes, so today the
    violation is undeclarable rather than merely discouraged. This test exists
    for the day someone widens that constructor: a structural guarantee that
    nothing asserts is one refactor away from being no guarantee at all.

    The scan is made to DO something first -- it lands a real discrepancy row
    -- because "nothing changed" proves nothing about a scan that did nothing.
    """
    symbol = "DOTUSDT"
    strategy_id, allocation_id, attempt_id = await _seed_allocation(session_factory)

    async with session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                symbol=symbol,
                side="BUY",
                quantity="0.004",
            )
        )
        await session.commit()

    before = await _write_boundary_snapshot(session_factory)

    await _scan(
        session_factory,
        venue_positions=[VenuePosition(symbol, Decimal("0.009"))],
        scan_id=uuid4(),
        at=NOW,
    )

    # The scan really did land a row, so the assertions below mean something.
    records = await _open_records(session_factory, symbol=symbol)
    assert len(records) == 1
    assert records[0].ledger_net_base == Decimal("0.004")

    assert await _write_boundary_snapshot(session_factory) == before


# --- The spelling regression, against the real ledger projection -------------
#
# Production's ledger stores the SIGNAL's symbol (``STXUSDT.P``, TradingView's
# perpetual form); the venue reports its own (``STXUSDT``). Every earlier test
# in this file used one spelling on both sides, which is how the scan shipped
# producing two false discrepancies per open position.


async def _record_open_position(
    session_factory: async_sessionmaker[AsyncSession], *, symbol: str, quantity: str
) -> UUID:
    strategy_id, allocation_id, attempt_id = await _seed_allocation(session_factory)
    async with session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                symbol=symbol,
                side="BUY",
                quantity=quantity,
            )
        )
        await session.commit()
    return allocation_id


async def _open_records_for_market(
    session_factory: async_sessionmaker[AsyncSession], *spellings: str
) -> list[DiscrepancyRecord]:
    """Every open row under ANY of ``spellings``. The ledger is not truncated
    between tests in this module, so earlier tests' positions are still in
    the pool; filtering by this market keeps their rows out of the count."""
    async with session_factory() as session:
        records = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(
            pool=POOL, open_only=True
        )
    return [record for record in records if record.symbol in spellings]


async def test_a_ledger_in_tradingview_spelling_agrees_with_the_venue_spelling(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _record_open_position(session_factory, symbol="STXUSDT.P", quantity="0.5")

    await _scan(
        session_factory,
        venue_positions=[VenuePosition("STXUSDT", Decimal("0.5"))],
        scan_id=uuid4(),
        at=NOW,
    )

    assert await _open_records_for_market(session_factory, "STXUSDT", "STXUSDT.P") == []


async def test_a_real_mismatch_across_spellings_lands_under_the_market_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation_id = await _record_open_position(
        session_factory, symbol="LINKUSDT.P", quantity="0.5"
    )

    await _scan(
        session_factory,
        venue_positions=[VenuePosition("LINKUSDT", Decimal("0.3"))],
        scan_id=uuid4(),
        at=NOW,
    )

    records = await _open_records_for_market(session_factory, "LINKUSDT", "LINKUSDT.P")
    assert len(records) == 1
    record = records[0]
    assert record.symbol == "LINKUSDT"
    assert record.kind is DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION
    assert record.venue_net_base == Decimal("0.3")
    assert record.ledger_net_base == Decimal("0.5")
    assert record.open_allocation_ids == (allocation_id,)
