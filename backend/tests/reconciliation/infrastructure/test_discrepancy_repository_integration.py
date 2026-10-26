"""Tier B: ``SqlAlchemyDiscrepancyRepository`` against a real ``alembic
upgrade head`` database (spec: reconcile-venue-fills).

Follows ``tests/migrations/test_0020_reconciliation_discrepancies.py``'s own
pattern: a throwaway database, migrated to head, dropped at teardown. That
file already proves the raw SQL shape of every constraint; this one proves
the REPOSITORY drives them correctly -- the partial unique index's upsert
behaviour, the generated column surviving a round trip, a CHECK refusing a
write the repository itself could otherwise produce, and the FK's
non-cascading refusal, all exercised through ``upsert_open``/
``resolve_absent``/``list_discrepancies`` rather than through raw SQL. No
fake can prove any of this: a fake ``DiscrepancyRepositoryPort`` would only
ever prove that this file's own assumptions about Postgres are self-consistent.
"""

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
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

from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.errors import InvariantViolation
from tests.owner import OWNER_ID, ensure_pool, seed_other_user, seed_owner
from tests.pg_drop import drop_database_if_exists

pytestmark = pytest.mark.integration

_BACKEND_DIR = Path(__file__).resolve().parents[3]
_DB_NAME = "strategy_manager_test_reconciliation_repo"

POOL = ("pionex", "spot", "USDT")
NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)


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

    asyncio.run(drop_database_if_exists(maintenance_dsn, _DB_NAME))
    asyncio.run(_create_database(maintenance_dsn, _DB_NAME))
    _run_alembic(url, "upgrade", "head")

    yield url

    asyncio.run(drop_database_if_exists(maintenance_dsn, _DB_NAME))


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
    # Migration 0030 leaves a database nobody signed into with no pools: the
    # owner and the pool the tests write against are seeded here.
    async with engine.begin() as conn:
        await seed_owner(conn)
        await ensure_pool(conn, POOL)
    yield
    async with engine.begin() as conn:
        # CASCADE: migration 0023's booking_proposals FKs into this table
        # (no ON DELETE CASCADE on that FK itself -- see 0023's docstring --
        # but a plain TRUNCATE still refuses without one here). This fixture
        # runs against a real `alembic upgrade head` database, so the table
        # exists here even though this file never writes to it directly.
        await conn.execute(text("TRUNCATE reconciliation_discrepancies CASCADE"))
        # DELETE, not TRUNCATE: TRUNCATE ... CASCADE would reach the append-only
        # ledger. Nothing else here references a pool once the discrepancies
        # (and their proposals) are gone.
        await conn.execute(text("DELETE FROM capital_pools"))


def _observation(
    kind: DiscrepancyKind = DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
    venue_net_base: Decimal = Decimal("2.0"),
    ledger_net_base: Decimal = Decimal("1.5"),
) -> Observation:
    return Observation(kind=kind, venue_net_base=venue_net_base, ledger_net_base=ledger_net_base)


async def test_upsert_open_inserts_a_fresh_row_with_the_generated_delta(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The generated column, proven through the repository: ``delta_base``
    is never in ``upsert_open``'s own INSERT column list, and Postgres
    computes it anyway."""
    allocation_id = uuid4()
    scan_id = uuid4()

    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        await repo.upsert_open(
            OWNER_ID,
            POOL,
            "BTCUSDT",
            _observation(),
            [allocation_id],
            consecutive_scans=1,
            status=DiscrepancyStatus.OBSERVED,
            scan_id=scan_id,
            at=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        records = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(pool=POOL)

    assert len(records) == 1
    record = records[0]
    assert record.symbol == "BTCUSDT"
    assert record.kind is DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION
    assert record.open_allocation_ids == (allocation_id,)
    assert record.consecutive_scans == 1
    assert record.status is DiscrepancyStatus.OBSERVED
    assert record.confirmed_at is None
    assert record.resolved_at is None
    assert record.venue_net_base - record.ledger_net_base == Decimal("0.5")


async def test_upsert_open_a_second_time_updates_the_same_row_in_place(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The partial unique index, driven by the repository: a second call for
    the same pool+symbol must not create a second row."""
    allocation_id = uuid4()
    scan_id_1, scan_id_2 = uuid4(), uuid4()

    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        await repo.upsert_open(
            OWNER_ID,
            POOL,
            "ETHUSDT",
            _observation(venue_net_base=Decimal("2.0")),
            [allocation_id],
            consecutive_scans=1,
            status=DiscrepancyStatus.OBSERVED,
            scan_id=scan_id_1,
            at=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        await repo.upsert_open(
            OWNER_ID,
            POOL,
            "ETHUSDT",
            _observation(venue_net_base=Decimal("2.0")),
            [allocation_id],
            consecutive_scans=2,
            status=DiscrepancyStatus.OBSERVED,
            scan_id=scan_id_2,
            at=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        records = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(pool=POOL)

    assert len(records) == 1
    assert records[0].consecutive_scans == 2
    assert records[0].last_scan_id == scan_id_2
    assert records[0].first_scan_id == scan_id_1


async def test_upsert_open_sets_confirmed_at_exactly_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``ck_reconciliation_discrepancies_confirmed_at``, driven by the
    repository: CONFIRMED requires a timestamp, and a later call must not
    move it once it is set."""
    allocation_id = uuid4()

    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        await repo.upsert_open(
            OWNER_ID,
            POOL,
            "SOLUSDT",
            _observation(),
            [allocation_id],
            consecutive_scans=2,
            status=DiscrepancyStatus.CONFIRMED,
            scan_id=uuid4(),
            at=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        records = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(pool=POOL)
    first_confirmed_at = records[0].confirmed_at
    assert first_confirmed_at is not None

    later = datetime(2026, 9, 18, 13, 0, 0, tzinfo=UTC)
    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        await repo.upsert_open(
            OWNER_ID,
            POOL,
            "SOLUSDT",
            _observation(),
            [allocation_id],
            consecutive_scans=3,
            status=DiscrepancyStatus.CONFIRMED,
            scan_id=uuid4(),
            at=later,
        )
        await session.commit()

    async with session_factory() as session:
        records = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(pool=POOL)

    assert records[0].confirmed_at == first_confirmed_at
    assert records[0].consecutive_scans == 3


async def test_resolve_absent_closes_the_open_row_and_a_fresh_one_can_reopen(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The partial index's other half: a RESOLVED row (``resolved_at`` set)
    must not block a brand-new OPEN row for the same pool+symbol."""
    allocation_id = uuid4()
    scan_id = uuid4()

    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        await repo.upsert_open(
            OWNER_ID,
            POOL,
            "AVAXUSDT",
            _observation(),
            [allocation_id],
            consecutive_scans=1,
            status=DiscrepancyStatus.OBSERVED,
            scan_id=scan_id,
            at=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        resolved_count = await repo.resolve_absent(OWNER_ID, POOL, ["AVAXUSDT"], scan_id, NOW)
        await session.commit()

    assert resolved_count == 1

    async with session_factory() as session:
        open_records = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(
            pool=POOL, open_only=True
        )
    assert open_records == []

    # A brand-new discrepancy for the same pool+symbol must be accepted.
    new_scan_id = uuid4()
    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        await repo.upsert_open(
            OWNER_ID,
            POOL,
            "AVAXUSDT",
            _observation(),
            [allocation_id],
            consecutive_scans=1,
            status=DiscrepancyStatus.OBSERVED,
            scan_id=new_scan_id,
            at=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        all_records = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(
            pool=POOL
        )
    assert len(all_records) == 2


async def test_resolve_absent_on_a_symbol_with_no_open_row_is_a_no_op(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        resolved_count = await repo.resolve_absent(OWNER_ID, POOL, ["NEVERUSDT"], uuid4(), NOW)
        await session.commit()

    assert resolved_count == 0


async def test_deleting_a_pool_with_an_open_discrepancy_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The composite FK's non-cascading refusal, driven by the repository's
    own write rather than raw SQL: a discrepancy the repository just wrote
    must still block the delete."""
    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        await repo.upsert_open(
            OWNER_ID,
            POOL,
            "XRPUSDT",
            _observation(),
            [uuid4()],
            consecutive_scans=1,
            status=DiscrepancyStatus.OBSERVED,
            scan_id=uuid4(),
            at=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "DELETE FROM capital_pools WHERE exchange = :exchange "
                    "AND venue = :venue AND settlement_currency = :settlement_currency"
                ),
                {"exchange": POOL[0], "venue": POOL[1], "settlement_currency": POOL[2]},
            )
            await session.commit()


async def test_list_discrepancies_filters_by_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        await repo.upsert_open(
            OWNER_ID,
            POOL,
            "OBSERVEDCOIN",
            _observation(),
            [uuid4()],
            consecutive_scans=1,
            status=DiscrepancyStatus.OBSERVED,
            scan_id=uuid4(),
            at=NOW,
        )
        await repo.upsert_open(
            OWNER_ID,
            POOL,
            "CONFIRMEDCOIN",
            _observation(),
            [uuid4()],
            consecutive_scans=2,
            status=DiscrepancyStatus.CONFIRMED,
            scan_id=uuid4(),
            at=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        confirmed = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(
            status=DiscrepancyStatus.CONFIRMED
        )

    assert [r.symbol for r in confirmed] == ["CONFIRMEDCOIN"]


async def test_list_discrepancies_with_no_filters_reads_everything(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        await repo.upsert_open(
            OWNER_ID,
            POOL,
            "ALLCOIN",
            _observation(),
            [uuid4()],
            consecutive_scans=1,
            status=DiscrepancyStatus.OBSERVED,
            scan_id=uuid4(),
            at=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        records = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies()

    assert any(r.symbol == "ALLCOIN" for r in records)


# -- Multi-user ownership (migration 0030; design AD8, AD10) ------------------


async def _two_users_each_with_an_open_discrepancy(
    session_factory: async_sessionmaker[AsyncSession], symbol: str
) -> tuple[UUID, UUID]:
    """The owner and a second user, each holding a pool on ``POOL`` and an open
    discrepancy on ``symbol``. Returns the second user's id and that user's
    discrepancy id."""
    async with session_factory() as session:
        other = await seed_other_user(session)
        await ensure_pool(session, POOL, user_id=other)
        await session.commit()
    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        for user_id in (OWNER_ID, other):
            await repo.upsert_open(
                user_id,
                POOL,
                symbol,
                _observation(),
                [uuid4()],
                consecutive_scans=1,
                status=DiscrepancyStatus.OBSERVED,
                scan_id=uuid4(),
                at=NOW,
            )
        await session.commit()
    async with session_factory() as session:
        theirs = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(
            user_id=other
        )
    return other, theirs[0].id


async def test_two_users_may_each_hold_an_open_discrepancy_on_the_same_symbol(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``ux_reconciliation_open_per_symbol`` is per user (0030), and the upsert's
    ON CONFLICT target follows it: the second user's first observation is a new
    row, not an update of the owner's, and each user's next observation updates
    their own."""
    other, _ = await _two_users_each_with_an_open_discrepancy(session_factory, "SHAREDUSDT")

    async with session_factory() as session:
        await SqlAlchemyDiscrepancyRepository(session).upsert_open(
            other,
            POOL,
            "SHAREDUSDT",
            _observation(),
            [uuid4()],
            consecutive_scans=2,
            status=DiscrepancyStatus.OBSERVED,
            scan_id=uuid4(),
            at=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        records = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(pool=POOL)
    by_user = {record.user_id: record for record in records}
    assert len(records) == 2
    assert by_user[OWNER_ID].consecutive_scans == 1
    assert by_user[other].consecutive_scans == 2


async def test_list_discrepancies_with_a_user_returns_only_that_users_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other, _ = await _two_users_each_with_an_open_discrepancy(session_factory, "LISTUSDT")

    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        owners = await repo.list_discrepancies(pool=POOL, open_only=True, user_id=OWNER_ID)
        everyone = await repo.list_discrepancies(pool=POOL, open_only=True)

    assert [record.user_id for record in owners] == [OWNER_ID]
    # The admin's view (decision 16) is global, and says whose each row is.
    assert {record.user_id for record in everyone} == {OWNER_ID, other}


async def test_resolve_absent_resolves_only_the_given_users_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other, _ = await _two_users_each_with_an_open_discrepancy(session_factory, "RESOLVEUSDT")

    async with session_factory() as session:
        resolved = await SqlAlchemyDiscrepancyRepository(session).resolve_absent(
            OWNER_ID, POOL, ["RESOLVEUSDT"], uuid4(), NOW
        )
        await session.commit()

    assert resolved == 1
    async with session_factory() as session:
        still_open = await SqlAlchemyDiscrepancyRepository(session).list_discrepancies(
            pool=POOL, open_only=True
        )
    assert [record.user_id for record in still_open] == [other]


async def test_get_finds_only_the_given_users_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other, others_id = await _two_users_each_with_an_open_discrepancy(
        session_factory, "GETUSDT"
    )

    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        found = await repo.get(other, others_id)
        with pytest.raises(InvariantViolation):
            await repo.get(OWNER_ID, others_id)

    assert found.user_id == other


async def test_upsert_open_for_a_user_without_a_pool_there_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        stranger = await seed_other_user(session)
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(InvariantViolation, match="has no pool"):
            await SqlAlchemyDiscrepancyRepository(session).upsert_open(
                stranger,
                POOL,
                "NOPOOLUSDT",
                _observation(),
                [uuid4()],
                consecutive_scans=1,
                status=DiscrepancyStatus.OBSERVED,
                scan_id=uuid4(),
                at=NOW,
            )
