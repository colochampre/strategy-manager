"""Seeding helpers for the unit-6e tests: a pool with positions, reservations and
attempts across several strategies, written through the real repositories.

All of it is on ``bybit/usdt-m/USDT`` by default, the seeded futures pool.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.ledger.domain.ledger_entry import LedgerEntry
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.infrastructure.models import ReconciliationDiscrepancyRow
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

__all__ = [
    "POOL",
    "clear_discrepancies",
    "seed_discrepancy",
    "seed_execution_attempt",
    "seed_live_reservation",
    "seed_open_position",
    "seed_reservation",
    "seed_signal",
    "seed_strategy",
    "set_strategy_enabled",
]

POOL = ("bybit", "usdt-m", "USDT")
NOW = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)


async def clear_discrepancies(factory: async_sessionmaker[AsyncSession]) -> None:
    """The shared fixture's TRUNCATE does not name this table, and a row left by
    the previous test would read as this pool's open discrepancy."""
    async with factory() as session:
        await session.execute(text("TRUNCATE reconciliation_discrepancies"))
        await session.commit()


async def seed_discrepancy(
    factory: async_sessionmaker[AsyncSession],
    *,
    symbol: str,
    status: str = "OBSERVED",
    resolved: bool = False,
    pool: tuple[str, str, str] = POOL,
) -> None:
    observed_at = datetime(2026, 10, 12, 8, 0, 0, tzinfo=UTC)
    async with factory() as session:
        session.add(
            ReconciliationDiscrepancyRow(
                id=uuid4(),
                exchange=pool[0],
                venue=pool[1],
                settlement_currency=pool[2],
                symbol=symbol,
                kind="ATTRIBUTABLE_SINGLE_ALLOCATION",
                venue_net_base=Decimal("1"),
                ledger_net_base=Decimal("0"),
                open_allocation_ids=[],
                consecutive_scans=1,
                status=status,
                first_observed_at=observed_at,
                last_observed_at=observed_at,
                confirmed_at=observed_at if status == "CONFIRMED" else None,
                resolved_at=observed_at + timedelta(hours=1) if resolved else None,
                first_scan_id=uuid4(),
                last_scan_id=uuid4(),
                resolved_by_scan_id=uuid4() if resolved else None,
            )
        )
        await session.commit()


async def seed_live_reservation(
    factory: async_sessionmaker[AsyncSession],
    *,
    strategy_id: UUID,
    status: str = "PENDING",
    pool: tuple[str, str, str] = POOL,
) -> UUID:
    reservation_id = uuid4()
    signal_id = uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    await seed_reservation(
        factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        exchange=pool[0],
        venue=pool[1],
        settlement_currency=pool[2],
        status=status,
    )
    return reservation_id


async def seed_open_position(
    factory: async_sessionmaker[AsyncSession],
    *,
    strategy_id: UUID,
    symbol: str,
    quantity: Decimal = Decimal("1"),
    pool: tuple[str, str, str] = POOL,
) -> UUID:
    """One FILLED reservation, one FILLED opening attempt and one BUY ledger row:
    an allocation open on ``symbol``. Returns the allocation id."""
    exchange, venue, currency = pool
    allocation_id = await seed_live_reservation(
        factory, strategy_id=strategy_id, status="FILLED", pool=pool
    )
    attempt_id = uuid4()
    await seed_execution_attempt(
        factory,
        attempt_id=attempt_id,
        reservation_id=allocation_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        symbol=symbol,
        status="FILLED",
        exchange_order_id=f"ord-{attempt_id}",
    )
    async with factory() as session:
        await SqlAlchemyLedgerRepository(session).insert(
            LedgerEntry(
                id=uuid4(),
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                execution_attempt_id=attempt_id,
                exchange=exchange,
                venue=venue,
                settlement_currency=currency,
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                price=Decimal("1"),
                fee=Decimal("0"),
                fee_currency=currency,
                notional=quantity,
                exchange_order_id=f"ord-{attempt_id}",
                exchange_fill_id=f"fill-{attempt_id}",
                filled_at=NOW,
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()
    return allocation_id


async def set_strategy_enabled(
    factory: async_sessionmaker[AsyncSession], strategy_id: UUID, enabled: bool
) -> None:
    async with factory() as session:
        await session.execute(
            text("UPDATE strategies SET enabled = :enabled WHERE id = :id"),
            {"enabled": enabled, "id": strategy_id},
        )
        await session.commit()
