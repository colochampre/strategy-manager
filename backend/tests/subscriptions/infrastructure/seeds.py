"""Rows the subscriptions integration tests start from, written raw.

A symbol crossing a module boundary wears a different spelling on each side: the
alert says ``STXUSDT.P``, the venue and the ledger say ``STXUSDT``.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)
from tests.owner import ensure_pool, seed_other_user

Factory = async_sessionmaker[AsyncSession]

MARKET = ("bybit", "usdt-m", "USDT")


async def strategy(factory: Factory, *, archived: bool = False) -> UUID:
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id, enabled=not archived)
    if archived:
        async with factory() as session:
            await session.execute(
                text("UPDATE strategies SET archived_at = now() WHERE id = :id"),
                {"id": strategy_id},
            )
            await session.commit()
    return strategy_id


async def user(factory: Factory, *, pool: bool = True) -> tuple[UUID, int | None]:
    """A fresh user and, unless ``pool`` is false, their own pool on ``MARKET``."""
    async with factory() as session:
        user_id = await seed_other_user(session)
        pool_id = await ensure_pool(session, MARKET, user_id=user_id) if pool else None
        await session.commit()
    return user_id, pool_id


async def subscription(
    factory: Factory,
    user_id: UUID,
    strategy_id: UUID,
    pool_id: int,
    *,
    status: str = "ACTIVE",
    share: str = "30",
    created_at: datetime | None = None,
) -> UUID:
    subscription_id = uuid4()
    async with factory() as session:
        row = SubscriptionRow(
            id=subscription_id,
            user_id=user_id,
            strategy_id=strategy_id,
            pool_id=pool_id,
            allocation_percent=Decimal(share),
            status=status,
        )
        if created_at is not None:
            # Otherwise the column's server default stamps it.
            row.created_at = created_at
        session.add(row)
        await session.commit()
    return subscription_id


async def open_allocation(
    factory: Factory, user_id: UUID, strategy_id: UUID, *, symbol: str = "STXUSDT"
) -> None:
    """A FILLED reservation and its BUY fill in the user's ledger: a position the
    strategy holds for that user. The alert's spelling is ``STXUSDT.P``; the
    ledger holds the venue's ``STXUSDT`` (``symbol``, when a test needs another
    market)."""
    signal_id, reservation_id, attempt_id = uuid4(), uuid4(), uuid4()
    exchange, venue, currency = MARKET
    await seed_signal(
        factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"key-{signal_id}",
    )
    await seed_reservation(
        factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        status="FILLED",
        user_id=user_id,
    )
    await seed_execution_attempt(
        factory, attempt_id=attempt_id, reservation_id=reservation_id, symbol=symbol
    )
    async with factory() as session:
        entry_id = uuid4()
        session.add(
            LedgerEntryRow(
                id=entry_id,
                user_id=user_id,
                strategy_id=strategy_id,
                allocation_id=reservation_id,
                execution_attempt_id=attempt_id,
                exchange=exchange,
                venue=venue,
                settlement_currency=currency,
                symbol=symbol,
                side="BUY",
                quantity=Decimal("1"),
                price=Decimal("1"),
                fee=Decimal("0"),
                fee_currency=currency,
                notional=Decimal("1"),
                exchange_order_id=f"order-{entry_id}",
                exchange_fill_id=f"fill-{entry_id}",
                filled_at=datetime.now(UTC),
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()


async def live_reservation(factory: Factory, user_id: UUID, strategy_id: UUID) -> None:
    """A PENDING reservation: capital held for an opening that has not filled yet."""
    signal_id = uuid4()
    await seed_signal(
        factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"key-{signal_id}",
    )
    await seed_reservation(
        factory,
        reservation_id=uuid4(),
        strategy_id=strategy_id,
        signal_id=signal_id,
        status="PENDING",
        user_id=user_id,
    )


async def rows(factory: Factory) -> list[tuple[Any, ...]]:
    """Every subscription row, whole, in a stable order: two snapshots are equal
    only when nothing in the table changed."""
    async with factory() as session:
        result = await session.execute(
            select(
                SubscriptionRow.id,
                SubscriptionRow.user_id,
                SubscriptionRow.strategy_id,
                SubscriptionRow.pool_id,
                SubscriptionRow.allocation_percent,
                SubscriptionRow.status,
                SubscriptionRow.left_at,
                SubscriptionRow.ended_at,
            ).order_by(SubscriptionRow.id)
        )
        return [tuple(row) for row in result.all()]


async def row_of(factory: Factory, subscription_id: UUID) -> SubscriptionRow:
    async with factory() as session:
        found = await session.get(SubscriptionRow, subscription_id)
        assert found is not None
        return found

