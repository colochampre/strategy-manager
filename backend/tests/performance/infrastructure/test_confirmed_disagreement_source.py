"""Integration test: ``ConfirmedDisagreementSource``, the thin adapter over the
reconciliation's repository [DB] (design addendum "open positions", sections E
and G; tasks.md op.1.22).

Real PostgreSQL: an ``OBSERVED`` row, a ``CONFIRMED`` open row and a resolved
``CONFIRMED`` row sit in the table; only the open ``CONFIRMED`` one is answered,
mapped to the port's record. The reconciliation's own record is known to the
adapter's file alone.

The discrepancy row spells its market ``STXUSDT`` (the venue's), as the
reconciliation stores it.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.performance.domain.open_position import DiscrepancyRow, PoolLabel
from strategy_manager.performance.infrastructure.confirmed_disagreement_source import (
    ConfirmedDisagreementSource,
)
from strategy_manager.reconciliation.infrastructure.models import ReconciliationDiscrepancyRow
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from tests.owner import OWNER_ID, ensure_pool, seed_other_user
from tests.performance.infrastructure.conftest import pg_session_factory  # noqa: F401

pytestmark = pytest.mark.integration

OBSERVED_AT = datetime(2026, 10, 12, 8, 30, 15, 250000, tzinfo=UTC)
RESOLVED_AT = datetime(2026, 10, 12, 9, 0, 0, tzinfo=UTC)


async def _insert(
    factory: async_sessionmaker[AsyncSession],
    *,
    status: str,
    allocations: list[UUID],
    resolved: bool = False,
    symbol: str = "STXUSDT",
    pool: tuple[str, str, str] = ("bybit", "usdt-m", "USDT"),
    user_id: UUID = OWNER_ID,
) -> UUID:
    row_id = uuid4()
    async with factory() as session:
        pool_id = await ensure_pool(session, pool, user_id=user_id)
        session.add(
            ReconciliationDiscrepancyRow(
                id=row_id,
                user_id=user_id,
                pool_id=pool_id,
                exchange=pool[0],
                venue=pool[1],
                settlement_currency=pool[2],
                symbol=symbol,
                kind="ATTRIBUTABLE_SINGLE_ALLOCATION",
                venue_net_base=Decimal("0"),
                ledger_net_base=Decimal("12.5"),
                open_allocation_ids=allocations,
                consecutive_scans=3,
                status=status,
                first_observed_at=OBSERVED_AT,
                last_observed_at=OBSERVED_AT,
                confirmed_at=OBSERVED_AT if status == "CONFIRMED" else None,
                resolved_at=RESOLVED_AT if resolved else None,
                first_scan_id=uuid4(),
                last_scan_id=uuid4(),
                resolved_by_scan_id=uuid4() if resolved else None,
            )
        )
        await session.commit()
    return row_id


@pytest.fixture(autouse=True)
async def _empty_discrepancies(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """The table is not truncated by the shared fixture."""
    async with pg_session_factory() as session:
        await session.execute(text("DELETE FROM reconciliation_discrepancies"))
        await session.commit()


async def _read(
    factory: async_sessionmaker[AsyncSession], user_id: UUID = OWNER_ID
) -> list[DiscrepancyRow]:
    async with factory() as session:
        source = ConfirmedDisagreementSource(SqlAlchemyDiscrepancyRepository(session))
        return list(await source.confirmed_open(user_id))


async def test_only_the_open_confirmed_row_is_answered_mapped_to_the_ports_record(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    a, b = uuid4(), uuid4()
    await _insert(pg_session_factory, status="OBSERVED", allocations=[uuid4()])
    confirmed = await _insert(pg_session_factory, status="CONFIRMED", allocations=[a, b])
    await _insert(pg_session_factory, status="CONFIRMED", allocations=[uuid4()], resolved=True)

    rows = await _read(pg_session_factory)

    assert rows == [
        DiscrepancyRow(
            discrepancy_id=confirmed,
            pool=PoolLabel("bybit", "usdt-m", "USDT"),
            symbol="STXUSDT",
            status="CONFIRMED",
            venue_net_base=Decimal("0"),
            ledger_net_base=Decimal("12.5"),
            open_allocation_ids=(a, b),
            last_observed_at=OBSERVED_AT,
            resolved_at=None,
        )
    ]


async def test_an_empty_table_answers_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    assert await _read(pg_session_factory) == []


async def test_a_second_users_confirmed_row_on_the_same_market_and_symbol_is_not_answered(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """Multi-user design AD8: both users hold an open CONFIRMED row on the same
    market and symbol (two partial unique indexes, one per user). Each reads
    only their own."""
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    mine = await _insert(pg_session_factory, status="CONFIRMED", allocations=[uuid4()])
    theirs = await _insert(
        pg_session_factory, status="CONFIRMED", allocations=[uuid4()], user_id=other
    )

    owner_rows = await _read(pg_session_factory)
    other_rows = await _read(pg_session_factory, other)

    assert [row.discrepancy_id for row in owner_rows] == [mine]
    assert [row.discrepancy_id for row in other_rows] == [theirs]


async def test_confirmed_rows_of_every_pool_are_answered(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    one = await _insert(pg_session_factory, status="CONFIRMED", allocations=[uuid4()])
    two = await _insert(
        pg_session_factory,
        status="CONFIRMED",
        allocations=[uuid4()],
        pool=("pionex", "coin-m", "BTC"),
        symbol="ETH_BTC",
    )

    rows = await _read(pg_session_factory)

    assert {row.discrepancy_id for row in rows} == {one, two}
    assert {row.pool.exchange for row in rows} == {"bybit", "pionex"}
