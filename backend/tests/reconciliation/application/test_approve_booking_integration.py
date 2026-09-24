"""Tier B: ``ApproveBooking`` against a real ``alembic upgrade head``
database -- the FIRST unit in this change that writes to
``execution_attempts``/``ledger_entries`` (design.md § 6 "``ApproveBooking``
-- transaction boundary and the two expected IntegrityErrors"; § 7 "The
freshness re-check"; § 8 "``usd_rate`` provenance"; § 14 "Interaction with
``open-position-safely``"; § 16 "DRY_RUN"; spec: venue-close-booking,
trade-execution, trade-ledger).

Only the clock and the USD rate provider are faked (design.md § 16: the
REAL branch cannot be rehearsed under DRY_RUN, so this is proven against
real PostgreSQL, not a fake). Every write path -- ``SqlAlchemyBookingWriter``,
``SqlAlchemyExecutionAttemptRepository``, ``ledger.application.record_fill.
RecordFill``, ``SqlAlchemyBookingProposalRepository`` -- is the real
production adapter, matching this file's own precedent
(``test_booking_prepare_integration.py``).
"""

import asyncio
import logging
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.application.approve_booking import (
    ApproveBooking,
    ApproveOutcome,
    ApproveResult,
)
from strategy_manager.reconciliation.application.ports import (
    BookingProposalRecord,
    BookingWriteOutcome,
    NewBookingProposal,
    PoolKey,
    ProposedFillSnapshot,
)
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind
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
_DB_NAME = "strategy_manager_test_approve_booking"

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
        # ``ledger_entries``/``execution_attempts`` are append-only (migration
        # ``0005``'s triggers refuse a TRUNCATE) -- every scenario below uses
        # a freshly randomised symbol and id, the same discipline
        # ``test_booking_prepare_integration.py`` already established, so
        # nothing here needs those two tables cleared between tests.
        await conn.execute(text("TRUNCATE reconciliation_discrepancies CASCADE"))


# --- Fakes: only the clock and the USD rate provider ------------------------


class _FrozenClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class _FixedUsdRate:
    def __init__(self, rate: Decimal) -> None:
        self._rate = rate
        self.calls: list[str] = []

    async def usd_rate(self, currency: object) -> Decimal:
        self.calls.append(str(currency))
        return self._rate


class _SessionCommit:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()


# --- Scenario builder ---------------------------------------------------


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
    """Seeds a strategy + a FILLED reservation (the allocation) + one OPEN
    ledger fill (+0.5 base, BUY) under ``ledger_symbol`` -- the position a
    booked VENUE close is expected to net flat (design.md § 14)."""

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
    # Deliberately the BARE venue spelling -- different from the ledger's
    # own TradingView-suffixed spelling, design.md § 13's cross-boundary
    # testing rule.
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


async def _approve(
    session_factory: async_sessionmaker[AsyncSession],
    proposal_id: UUID,
    *,
    at: datetime = NOW,
    dry_run: bool = False,
    decided_by: str = "owner",
) -> ApproveResult:
    async with session_factory() as session:
        use_case = ApproveBooking(
            proposals=SqlAlchemyBookingProposalRepository(session),
            discrepancies=SqlAlchemyDiscrepancyRepository(session),
            in_flight_close=InFlightCloseAdapter(SqlAlchemyExecutionAttemptRepository(session)),
            writer=SqlAlchemyBookingWriter(session),
            usd_rate_provider=_FixedUsdRate(Decimal("1")),
            clock=_FrozenClock(at),
            commit=_SessionCommit(session),
            dry_run=dry_run,
        )
        return await use_case.approve(proposal_id, decided_by)


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


async def _scenario_write_counts(
    session_factory: async_sessionmaker[AsyncSession], scenario: _Scenario
) -> tuple[int, int]:
    """How many ``execution_attempts``/``ledger_entries`` rows exist for
    THIS scenario's own allocation -- scoped, unlike ``_snapshot``, because
    both tables are append-only and shared across every test in this
    module. Ledger rows are further scoped to ``side = 'SELL'`` to exclude
    the scenario's own seeded OPEN (BUY) row and count only what a booking
    approval could have written."""

    async with session_factory() as session:
        attempts = (
            await session.execute(
                text(
                    "SELECT count(*) FROM execution_attempts WHERE closes_allocation_id = :aid"
                ),
                {"aid": scenario.allocation_id},
            )
        ).scalar_one()
        ledger_rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM ledger_entries WHERE allocation_id = :aid "
                    "AND side = 'SELL'"
                ),
                {"aid": scenario.allocation_id},
            )
        ).scalar_one()
        return int(attempts), int(ledger_rows)


# --------------------------------------------------------------------------
# The happy path -- WRITTEN, APPROVED, and the strategy nets flat
# --------------------------------------------------------------------------


async def test_approval_writes_a_venue_execution_attempt_and_ledger_rows_and_nets_flat(
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    scenario = await _seed_scenario(session_factory)

    with caplog.at_level(
        logging.INFO, logger="strategy_manager.reconciliation.application.approve_booking"
    ):
        result = await _approve(session_factory, scenario.proposal_id, at=NOW)

    assert result.outcome is ApproveOutcome.APPROVED
    assert result.execution_attempt_id is not None
    assert result.ledger_rows == 1
    # Binding requirement 8: the successful approval logs one loud line
    # naming the proposal, the attempt id and the row count.
    assert any(
        "approved" in record.message and str(scenario.proposal_id) in record.message
        for record in caplog.records
    )

    async with session_factory() as session:
        attempt_row = (
            await session.execute(
                text(
                    "SELECT origin, status, closes_allocation_id, reservation_id, "
                    "client_order_id, symbol, quantity, side, exchange_order_id "
                    "FROM execution_attempts WHERE id = :id"
                ),
                {"id": result.execution_attempt_id},
            )
        ).mappings().one()
    assert attempt_row["origin"] == "VENUE"
    assert attempt_row["status"] == "FILLED"
    assert attempt_row["closes_allocation_id"] == scenario.allocation_id
    assert attempt_row["reservation_id"] is None
    assert attempt_row["client_order_id"] == f"vnu:{POOL[0]}:fill:VFILL-{scenario.discrepancy_id}"
    assert attempt_row["symbol"] == scenario.market_symbol
    assert attempt_row["quantity"] == Decimal("0.5")
    assert attempt_row["side"] == "SELL"

    async with session_factory() as session:
        ledger_rows = (
            await session.execute(
                text(
                    "SELECT strategy_id, allocation_id, symbol, side, quantity, "
                    "usd_rate_at_fill FROM ledger_entries WHERE execution_attempt_id = :id"
                ),
                {"id": result.execution_attempt_id},
            )
        ).mappings().all()
    assert len(ledger_rows) == 1
    row = ledger_rows[0]
    assert row["strategy_id"] == scenario.strategy_id
    assert row["allocation_id"] == scenario.allocation_id
    assert row["symbol"] == scenario.market_symbol
    assert row["side"] == "SELL"
    assert row["quantity"] == Decimal("0.5")
    assert row["usd_rate_at_fill"] == Decimal("1")

    proposal = await _get_proposal(session_factory, scenario.proposal_id)
    assert proposal.state == "APPROVED"
    assert proposal.execution_attempt_id == result.execution_attempt_id
    assert proposal.decided_by == "owner"

    # design.md § 14: GHOST stops recurring because the strategy nets flat.
    # Proven with a DIFFERENT spelling for the open (``ledger_symbol``,
    # TradingView's ``.P`` suffix) and the booked close
    # (``market_symbol``, the bare venue spelling) -- design.md § 13.
    async with session_factory() as session:
        holdings = await SqlAlchemyLedgerRepository(session).symbol_holdings(
            POOL[0], POOL[1], POOL[2], scenario.market_symbol
        )
    assert [h for h in holdings if h.strategy_id == scenario.strategy_id] == []


# --------------------------------------------------------------------------
# 6a.5 -- DRY_RUN refuses at the use-case level, zero writes
# --------------------------------------------------------------------------


async def test_dry_run_refuses_at_use_case_level(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await _seed_scenario(session_factory)
    before = await _snapshot(session_factory)

    result = await _approve(session_factory, scenario.proposal_id, at=NOW, dry_run=True)

    assert result.outcome is ApproveOutcome.DRY_RUN_REFUSED
    assert result.execution_attempt_id is None
    assert result.ledger_rows == 0

    after = await _snapshot(session_factory)
    assert after == before

    proposal = await _get_proposal(session_factory, scenario.proposal_id)
    assert proposal.state == "PENDING"  # untouched, eligible for a live retry


# --------------------------------------------------------------------------
# 6a.1 -- every freshness branch (a)-(h) plus the single-allocation re-check
# --------------------------------------------------------------------------


async def _mutate_discrepancy(
    session_factory: async_sessionmaker[AsyncSession], discrepancy_id: UUID, sql: str
) -> None:
    async with session_factory() as session:
        await session.execute(text(sql), {"id": discrepancy_id})
        await session.commit()


async def _case_a_resolved(
    session_factory: async_sessionmaker[AsyncSession], scenario: _Scenario
) -> None:
    await _mutate_discrepancy(
        session_factory,
        scenario.discrepancy_id,
        "UPDATE reconciliation_discrepancies SET resolved_at = now() WHERE id = :id",
    )


async def _case_b_not_confirmed(
    session_factory: async_sessionmaker[AsyncSession], scenario: _Scenario
) -> None:
    await _mutate_discrepancy(
        session_factory,
        scenario.discrepancy_id,
        "UPDATE reconciliation_discrepancies SET status = 'OBSERVED' WHERE id = :id",
    )


async def _case_c_kind_changed(
    session_factory: async_sessionmaker[AsyncSession], scenario: _Scenario
) -> None:
    await _mutate_discrepancy(
        session_factory,
        scenario.discrepancy_id,
        "UPDATE reconciliation_discrepancies SET kind = 'ATTRIBUTABLE_SINGLE_ALLOCATION' "
        "WHERE id = :id",
    )


async def _case_d_venue_net_base_changed(
    session_factory: async_sessionmaker[AsyncSession], scenario: _Scenario
) -> None:
    await _mutate_discrepancy(
        session_factory,
        scenario.discrepancy_id,
        "UPDATE reconciliation_discrepancies SET venue_net_base = 0.1 WHERE id = :id",
    )


async def _case_e_ledger_net_base_changed(
    session_factory: async_sessionmaker[AsyncSession], scenario: _Scenario
) -> None:
    await _mutate_discrepancy(
        session_factory,
        scenario.discrepancy_id,
        "UPDATE reconciliation_discrepancies SET ledger_net_base = 0.6 WHERE id = :id",
    )


async def _case_f_open_allocation_ids_changed(
    session_factory: async_sessionmaker[AsyncSession], scenario: _Scenario
) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE reconciliation_discrepancies SET open_allocation_ids = "
                "ARRAY[:other]::uuid[] WHERE id = :id"
            ),
            {"id": scenario.discrepancy_id, "other": uuid4()},
        )
        await session.commit()


async def _case_g_in_flight_close(
    session_factory: async_sessionmaker[AsyncSession], scenario: _Scenario
) -> None:
    await seed_execution_attempt(
        session_factory,
        attempt_id=uuid4(),
        closes_allocation_id=scenario.allocation_id,
        exchange=POOL[0],
        venue=POOL[1],
        settlement_currency=POOL[2],
        symbol=scenario.market_symbol,
        status="SUBMITTED",
    )


async def _case_i_second_allocation_appeared(
    session_factory: async_sessionmaker[AsyncSession], scenario: _Scenario
) -> None:
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE reconciliation_discrepancies SET open_allocation_ids = "
                "ARRAY[:allocation_id, :other]::uuid[] WHERE id = :id"
            ),
            {
                "id": scenario.discrepancy_id,
                "allocation_id": scenario.allocation_id,
                "other": uuid4(),
            },
        )
        await session.commit()


_FRESHNESS_CASES: list[
    tuple[
        str,
        Callable[[async_sessionmaker[AsyncSession], _Scenario], Awaitable[None]] | None,
        str,
        str | None,
    ]
] = [
    ("a_resolved", _case_a_resolved, "SUPERSEDED", "resolved_at"),
    ("b_not_confirmed", _case_b_not_confirmed, "SUPERSEDED", "status is"),
    ("c_kind_changed", _case_c_kind_changed, "SUPERSEDED", "kind moved"),
    (
        "d_venue_net_base_changed",
        _case_d_venue_net_base_changed,
        "SUPERSEDED",
        "venue_net_base moved",
    ),
    (
        "e_ledger_net_base_changed",
        _case_e_ledger_net_base_changed,
        "SUPERSEDED",
        "ledger_net_base moved",
    ),
    (
        "f_open_allocation_ids_changed",
        _case_f_open_allocation_ids_changed,
        "SUPERSEDED",
        "open_allocation_ids moved",
    ),
    ("g_in_flight_close", _case_g_in_flight_close, "SUPERSEDED", "already has a SUBMITTED closing"),
    ("h_expired", None, "EXPIRED", None),
    (
        "i_second_allocation_appeared",
        _case_i_second_allocation_appeared,
        "SUPERSEDED",
        "no longer the discrepancy's only open allocation",
    ),
]


@pytest.mark.parametrize(
    "case_id, mutate, expected_state, reason_substring",
    _FRESHNESS_CASES,
    ids=[case[0] for case in _FRESHNESS_CASES],
)
async def test_stale_snapshot_refused_marks_superseded(
    session_factory: async_sessionmaker[AsyncSession],
    case_id: str,
    mutate: Callable[[async_sessionmaker[AsyncSession], _Scenario], Awaitable[None]] | None,
    expected_state: str,
    reason_substring: str | None,
) -> None:
    """design.md § 7's freshness branches (a)-(g), the single-allocation
    re-check added during apply (design.md § 5), and (h) the expiry branch
    -- which design.md § 6 gives a DIFFERENT outcome (``EXPIRED``, not
    ``SUPERSEDED``), so this parametrization asserts the PROPOSAL's terminal
    ``state`` rather than a single hardcoded outcome. Every case is
    money-critical: none may write to ``execution_attempts``/
    ``ledger_entries``."""

    if case_id == "h_expired":
        scenario = await _seed_scenario(session_factory, expires_at=NOW - timedelta(seconds=1))
    else:
        scenario = await _seed_scenario(session_factory)
        assert mutate is not None
        await mutate(session_factory, scenario)

    before = await _snapshot(session_factory)
    result = await _approve(session_factory, scenario.proposal_id, at=NOW)
    after = await _snapshot(session_factory)

    assert result.outcome.value == expected_state
    assert result.execution_attempt_id is None
    assert result.ledger_rows == 0
    if reason_substring is not None:
        assert result.reason is not None
        assert reason_substring in result.reason
    assert after == before  # zero writes, every branch

    proposal = await _get_proposal(session_factory, scenario.proposal_id)
    assert proposal.state == expected_state


# --------------------------------------------------------------------------
# 6a.2 -- replay: exactly one attempt, second call ALREADY_DECIDED
# --------------------------------------------------------------------------


async def test_replayed_approval_writes_nothing_further_marks_superseded(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Money-critical: approve the SAME proposal twice.

    The second call's outcome is ``ALREADY_DECIDED``, not ``SUPERSEDED``
    (the name tasks.md gave this test) -- **why**: the first call's
    ``mark_state(APPROVED, ...)`` already moved the proposal's ``state`` out
    of ``PENDING`` before the second call's ``get_for_update`` even runs
    (this use case's own step 1), so the second call never reaches the
    freshness re-check that produces ``SUPERSEDED`` at all. Whichever name,
    the money-critical assertion below -- exactly ONE execution attempt and
    ONE ledger row after both calls, not two -- is unchanged: no state that
    was reachable within this use case's single transaction can ever
    double-book the same proposal.
    """

    scenario = await _seed_scenario(session_factory)

    first = await _approve(session_factory, scenario.proposal_id, at=NOW)
    assert first.outcome is ApproveOutcome.APPROVED
    assert first.ledger_rows == 1

    attempts_after_first, ledger_rows_after_first = await _scenario_write_counts(
        session_factory, scenario
    )
    assert attempts_after_first == 1
    assert ledger_rows_after_first == 1

    second = await _approve(
        session_factory, scenario.proposal_id, at=NOW + timedelta(seconds=1)
    )
    assert second.outcome is ApproveOutcome.ALREADY_DECIDED
    assert second.execution_attempt_id is None
    assert second.ledger_rows == 0

    attempts_after_second, ledger_rows_after_second = await _scenario_write_counts(
        session_factory, scenario
    )
    assert attempts_after_second == 1
    assert ledger_rows_after_second == 1

    proposal = await _get_proposal(session_factory, scenario.proposal_id)
    assert proposal.state == "APPROVED"
    assert proposal.execution_attempt_id == first.execution_attempt_id


# --------------------------------------------------------------------------
# 6a.3 -- the two named IntegrityError translations, by CONSTRAINT NAME,
# proven directly against the writer (the object that owns them), plus an
# unrelated violation that must still propagate.
# --------------------------------------------------------------------------


def _attempt(
    scenario: _Scenario, *, client_order_id: str, quantity: Decimal = Decimal("0.5")
) -> ExecutionAttempt:
    return ExecutionAttempt(
        id=uuid4(),
        reservation_id=None,
        closes_allocation_id=scenario.allocation_id,
        exchange=POOL[0],
        venue=POOL[1],
        settlement_currency=POOL[2],
        symbol=scenario.market_symbol,
        side=OrderSide.SELL,
        quantity=quantity,
        quote_amount=None,
        leverage=None,
        status=ExecutionStatus.FILLED,
        origin=ExecutionOrigin.VENUE,
        client_order_id=client_order_id,
    )


def _fill_record(scenario: _Scenario, *, attempt_id: UUID, exchange_fill_id: str) -> FillRecord:
    return FillRecord(
        strategy_id=scenario.strategy_id,
        allocation_id=scenario.allocation_id,
        execution_attempt_id=attempt_id,
        exchange=POOL[0],
        venue=POOL[1],
        settlement_currency=POOL[2],
        symbol=scenario.market_symbol,
        side="SELL",
        quantity=Decimal("0.5"),
        price=Decimal("2.6"),
        fee=Decimal("0"),
        fee_currency="USDT",
        notional=Decimal("1.3"),
        exchange_order_id=f"VORD-{exchange_fill_id}",
        exchange_fill_id=exchange_fill_id,
        filled_at=VENUE_FILLED_AT,
        usd_rate_at_fill=Decimal("1"),
    )


async def test_client_order_id_collision_treated_as_expected_superseded(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await _seed_scenario(session_factory)
    shared_client_order_id = f"vnu:{POOL[0]}:fill:{uuid4()}"

    async with session_factory() as session:
        writer = SqlAlchemyBookingWriter(session)

        attempt_a = _attempt(scenario, client_order_id=shared_client_order_id)
        fill_a = _fill_record(scenario, attempt_id=attempt_a.id, exchange_fill_id=f"F-{uuid4()}")
        first = await writer.write(attempt_a, [fill_a])
        assert first.outcome is BookingWriteOutcome.WRITTEN

        # A replayed approval: same frozen client_order_id, a DIFFERENT
        # fill id (so this collision is isolated to the attempt insert,
        # never reaching the ledger insert at all).
        attempt_b = _attempt(scenario, client_order_id=shared_client_order_id)
        fill_b = _fill_record(scenario, attempt_id=attempt_b.id, exchange_fill_id=f"F-{uuid4()}")
        second = await writer.write(attempt_b, [fill_b])

        assert second.outcome is BookingWriteOutcome.ALREADY_RECORDED
        assert second.reason == "execution_attempts_client_order_id_key"
        assert second.fills_written == 0

        # The SAME transaction is still usable -- the SAVEPOINT, not the
        # whole transaction, absorbed the aborted insert.
        changed = await SqlAlchemyBookingProposalRepository(session).mark_state(
            scenario.proposal_id, "SUPERSEDED", NOW, decision_reason="collision test"
        )
        await session.commit()
    assert changed is True


async def test_ux_ledger_exchange_fill_collision_treated_as_expected_superseded(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await _seed_scenario(session_factory)
    shared_fill_id = f"VFILL-collision-{uuid4()}"

    async with session_factory() as session:
        writer = SqlAlchemyBookingWriter(session)

        attempt_a = _attempt(scenario, client_order_id=f"vnu:{POOL[0]}:fill:{uuid4()}")
        fill_a = _fill_record(scenario, attempt_id=attempt_a.id, exchange_fill_id=shared_fill_id)
        first = await writer.write(attempt_a, [fill_a])
        assert first.outcome is BookingWriteOutcome.WRITTEN

        # A DIFFERENT client_order_id (so the attempt insert succeeds), but
        # the SAME exchange_fill_id -- someone else already recorded this
        # fill (design.md § 14's "booking vs a signal" race).
        attempt_b = _attempt(scenario, client_order_id=f"vnu:{POOL[0]}:fill:{uuid4()}")
        fill_b = _fill_record(scenario, attempt_id=attempt_b.id, exchange_fill_id=shared_fill_id)
        second = await writer.write(attempt_b, [fill_b])

        assert second.outcome is BookingWriteOutcome.ALREADY_RECORDED
        assert second.reason == "ux_ledger_exchange_fill"
        assert second.fills_written == 0

        changed = await SqlAlchemyBookingProposalRepository(session).mark_state(
            scenario.proposal_id, "SUPERSEDED", NOW, decision_reason="collision test"
        )
        await session.commit()
    assert changed is True


async def test_writer_of_an_unrelated_integrity_violation_propagates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Only the two named constraints are swallowed. ``quantity > 0``
    (``ck_execution_attempts_quantity_positive``) is a bug and must still
    raise, never be silently folded into ``ALREADY_RECORDED``."""

    scenario = await _seed_scenario(session_factory)

    async with session_factory() as session:
        writer = SqlAlchemyBookingWriter(session)
        bad_attempt = _attempt(
            scenario, client_order_id=f"vnu:{POOL[0]}:fill:{uuid4()}", quantity=Decimal("0")
        )
        with pytest.raises(IntegrityError):
            await writer.write(bad_attempt, [])


# --------------------------------------------------------------------------
# 6a.4 -- concurrent double approval: the second transaction sees non-PENDING
# --------------------------------------------------------------------------


async def test_concurrent_double_approval_second_sees_non_pending(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two genuinely separate sessions race to approve the SAME proposal.
    ``get_for_update``'s row lock -- proven load-bearing here, not merely
    for the table's own CAS (review carryover) -- serializes them: the
    loser's ``get_for_update`` blocks until the winner commits, then reads
    APPROVED and returns ``ALREADY_DECIDED`` having written nothing.
    Removing ``FOR UPDATE`` was proven, during apply, to let the loser pass
    the PENDING check concurrently and crash in ``_require_marked`` instead
    of cleanly refusing -- see this unit's apply-progress for the captured
    RED evidence; reverted before this file was left in its final state.
    """

    scenario = await _seed_scenario(session_factory)
    barrier = asyncio.Event()

    async def decide(decided_by: str) -> ApproveResult:
        await barrier.wait()
        return await _approve(session_factory, scenario.proposal_id, at=NOW, decided_by=decided_by)

    tasks = [asyncio.create_task(decide(f"racer-{i}")) for i in range(2)]
    await asyncio.sleep(0)  # let both tasks reach the barrier before releasing it
    barrier.set()
    results = await asyncio.gather(*tasks)

    outcomes = sorted(result.outcome.value for result in results)
    assert outcomes == ["ALREADY_DECIDED", "APPROVED"]

    winner = next(result for result in results if result.outcome is ApproveOutcome.APPROVED)
    assert winner.ledger_rows == 1

    attempts, ledger_rows = await _scenario_write_counts(session_factory, scenario)
    assert attempts == 1
    assert ledger_rows == 1

    proposal = await _get_proposal(session_factory, scenario.proposal_id)
    assert proposal.state == "APPROVED"
    assert proposal.execution_attempt_id == winner.execution_attempt_id
