"""Tier B: ``ExpireBookingProposals`` against a real ``alembic upgrade head``
database (design.md § 11 "Expiry"; spec: venue-close-booking's "Proposal
Expiry" requirement).

Also proves, through the REAL repository chain (not by re-implementing
``ApproveBooking``'s own branch), that an expired-but-unswept proposal is
still refused by approval (binding requirement 5: 6a's own branch (h)).

Only the clock is faked. Every write path exercised here --
``SqlAlchemyBookingProposalRepository``, and for the re-proposability half,
``PrepareBooking`` with the same production adapters
``test_reject_booking.py``/``test_booking_prepare_integration.py`` already
prove -- is real.
"""

import asyncio
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
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_recorded_fill_ids import ReadRecordedFillIds
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.application.approve_booking import (
    ApproveBooking,
    ApproveOutcome,
)
from strategy_manager.reconciliation.application.expire_booking_proposals import (
    ExpireBookingProposals,
    ExpireBookingProposalsResult,
)
from strategy_manager.reconciliation.application.ports import (
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
from strategy_manager.shared.config import get_settings
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

_BACKEND_DIR = Path(__file__).resolve().parents[3]
_DB_NAME = "strategy_manager_test_expire_booking_proposals"

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


# --- Fakes: only the clock (and, for the re-propose half, the venue) -------


class _FrozenClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class _RealClock:
    """``reconciliation_discrepancies.first_observed_at`` defaults to the
    DATABASE's own ``now()`` (migration ``0020``), so ``PrepareBooking``'s
    clock must read close to that same real wall-clock instant for its
    window-span check not to refuse -- same reasoning as
    ``test_reject_booking.py``'s own ``_RealClock``."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class _FixedUsdRate:
    def __init__(self, rate: Decimal) -> None:
        self._rate = rate

    async def usd_rate(self, currency: object) -> Decimal:
        return self._rate


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


# --- Scenario builder (mirrors test_reject_booking.py) ---------------------


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
    expires_at: datetime,
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
                expires_at=expires_at,
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


async def _expire(
    session_factory: async_sessionmaker[AsyncSession], *, at: datetime = NOW
) -> ExpireBookingProposalsResult:
    async with session_factory() as session:
        use_case = ExpireBookingProposals(
            proposals=SqlAlchemyBookingProposalRepository(session),
            clock=_FrozenClock(at),
            commit=_SessionCommit(session),
        )
        return await use_case.expire()


async def _get_proposal_state(
    session_factory: async_sessionmaker[AsyncSession], proposal_id: UUID
) -> str:
    async with session_factory() as session:
        record = await SqlAlchemyBookingProposalRepository(session).get_for_update(proposal_id)
        return record.state


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


# --------------------------------------------------------------------------
# 6b.3 -- past-window PENDING proposals expire; a fresh sweep re-proposes
# --------------------------------------------------------------------------


async def test_pending_past_24h_expires_and_is_reproposable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Money-critical: exactly the past-due row is marked EXPIRED (a still-
    fresh PENDING proposal must survive untouched), ``expire`` never writes
    to ``ledger_entries``/``execution_attempts``, and -- unlike a rejection
    -- the expired proposal is fully re-proposable on the very next sweep,
    because ``has_matching_rejection`` never matches an EXPIRED row."""

    past_due = await _seed_scenario(session_factory, expires_at=NOW - timedelta(seconds=1))
    still_fresh = await _seed_scenario(session_factory, expires_at=NOW + timedelta(hours=1))

    ledger_before = await _snapshot(session_factory)

    result = await _expire(session_factory, at=NOW)

    assert result.expired == 1
    assert (await _snapshot(session_factory)) == ledger_before  # zero ledger/attempt writes

    assert (await _get_proposal_state(session_factory, past_due.proposal_id)) == "EXPIRED"
    assert (await _get_proposal_state(session_factory, still_fresh.proposal_id)) == "PENDING"

    # Re-proposable: a fresh sweep over the SAME (unchanged) observation
    # produces a NEW PENDING proposal for the expired discrepancy -- an
    # EXPIRED row carries no suppression, unlike a REJECTED one.
    fresh_fill = VenueFill(
        exchange_fill_id=f"VFILL2-{past_due.discrepancy_id}",
        exchange_order_id=f"VORD2-{past_due.discrepancy_id}",
        symbol=past_due.market_symbol,
        side="SELL",
        quantity=Decimal("0.5"),
        price=Decimal("2.6"),
        fee=Decimal("0"),
        fee_currency="USDT",
        filled_at=VENUE_FILLED_AT,
    )
    fake_reader = _FakeVenueFillReader([fresh_fill])
    async with session_factory() as session:
        prepare = PrepareBooking(
            discrepancies=SqlAlchemyDiscrepancyRepository(session),
            proposals=SqlAlchemyBookingProposalRepository(session),
            venue_fills=_FakeVenueFillReaderRegistry(fake_reader),
            recorded_fill_ids=ReadRecordedFillIds(SqlAlchemyLedgerRepository(session)),
            allocation_owner=AllocationOwnerAdapter(session),
            clock=_RealClock(),
            commit=_SessionCommit(session),
            window_pad_seconds=300,
            max_span_seconds=604_800,
            proposal_expiry_seconds=86_400,
            dry_run=False,
        )
        sweep_result = await prepare.sweep(uuid4())

    assert sweep_result.proposals_suppressed == 0
    assert sweep_result.proposals_prepared == 1

    async with session_factory() as session:
        pending = await SqlAlchemyBookingProposalRepository(session).list_pending()
    fresh_for_discrepancy = [p for p in pending if p.discrepancy_id == past_due.discrepancy_id]
    assert len(fresh_for_discrepancy) == 1
    assert fresh_for_discrepancy[0].id != past_due.proposal_id


# --------------------------------------------------------------------------
# 6b.4 -- approving an expired-but-unswept proposal still refuses EXPIRED
# --------------------------------------------------------------------------


async def test_approve_refuses_expired_but_unswept_proposal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Binding requirement 5: this asserts ``ApproveBooking``'s own already-
    implemented branch (h) through the REAL repository, deliberately WITHOUT
    running ``ExpireBookingProposals`` first -- the proposal is still
    PENDING at the database level (the expiry sweep has not reached it yet),
    and ``ApproveBooking`` must still refuse it as EXPIRED, zero writes,
    purely from comparing ``proposal.expires_at`` against its own clock."""

    scenario = await _seed_scenario(session_factory, expires_at=NOW - timedelta(seconds=1))

    async with session_factory() as session:
        pre_state = (
            await SqlAlchemyBookingProposalRepository(session).get_for_update(
                scenario.proposal_id
            )
        ).state
    assert pre_state == "PENDING"  # unswept: nothing has marked it EXPIRED yet

    ledger_before = await _snapshot(session_factory)

    async with session_factory() as session:
        use_case = ApproveBooking(
            proposals=SqlAlchemyBookingProposalRepository(session),
            discrepancies=SqlAlchemyDiscrepancyRepository(session),
            in_flight_close=InFlightCloseAdapter(SqlAlchemyExecutionAttemptRepository(session)),
            writer=SqlAlchemyBookingWriter(session),
            usd_rate_provider=_FixedUsdRate(Decimal("1")),
            clock=_FrozenClock(NOW),
            commit=_SessionCommit(session),
            dry_run=False,
        )
        result = await use_case.approve(scenario.proposal_id, "owner")

    assert result.outcome is ApproveOutcome.EXPIRED
    assert result.execution_attempt_id is None
    assert result.ledger_rows == 0
    assert (await _snapshot(session_factory)) == ledger_before

    assert (await _get_proposal_state(session_factory, scenario.proposal_id)) == "EXPIRED"
