"""``SqlAlchemyStoppedPositionsReader`` against a real PostgreSQL database
(subscriber-safety SS.8b): every allocation of every user whose ledger net is not zero and
whose strategy is disabled or archived, and no other.

A symbol crossing a module boundary wears a different spelling on each side: the alert says
``SOLUSDT.P``, the venue and some fills say ``SOLUSDT``, Pionex says ``DOGEUSDT_PERP``. Here
an allocation opens under one spelling and is partly or wholly closed under another, which is
the case a per-symbol grouping gets wrong.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.ports import StoppedPosition
from strategy_manager.execution.infrastructure.stopped_positions_reader import (
    SqlAlchemyStoppedPositionsReader,
)
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from tests.execution.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)
from tests.owner import OWNER_ID, seed_other_user

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]

BYBIT = ("bybit", "usdt-m", "USDT")
PIONEX = ("pionex", "spot", "USDT")
T0 = datetime(2026, 11, 16, 9, 0, 0, tzinfo=UTC)


async def _strategy(
    factory: Factory, *, author: UUID = OWNER_ID, enabled: bool, archived: bool = False
) -> UUID:
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id, enabled=enabled, author_id=author)
    if archived:
        async with factory() as session:
            await session.execute(
                text("UPDATE strategies SET archived_at = now() WHERE id = :id"),
                {"id": strategy_id},
            )
            await session.commit()
    return strategy_id


async def _allocation(
    factory: Factory,
    user_id: UUID,
    strategy_id: UUID,
    fills: list[tuple[str, str, str, str, str]],
    market: tuple[str, str, str] = BYBIT,
) -> UUID:
    """A FILLED reservation of ``user_id`` with one ledger row per ``(side, symbol,
    quantity, fee, fee_currency)``, a minute apart in that order. The first is the opening."""
    exchange, venue, currency = market
    signal_id, allocation_id = uuid4(), uuid4()
    await seed_signal(
        factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"key-{signal_id}",
    )
    await seed_reservation(
        factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        status="FILLED",
        user_id=user_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
    )
    for index, (side, symbol, quantity, fee, fee_currency) in enumerate(fills):
        attempt_id = uuid4()
        await seed_execution_attempt(
            factory,
            attempt_id=attempt_id,
            reservation_id=allocation_id if index == 0 else None,
            closes_allocation_id=None if index == 0 else allocation_id,
            exchange=exchange,
            venue=venue,
            settlement_currency=currency,
            symbol=symbol,
            status="FILLED",
            user_id=user_id,
        )
        async with factory() as session:
            entry_id = uuid4()
            session.add(
                LedgerEntryRow(
                    id=entry_id,
                    user_id=user_id,
                    strategy_id=strategy_id,
                    allocation_id=allocation_id,
                    execution_attempt_id=attempt_id,
                    exchange=exchange,
                    venue=venue,
                    settlement_currency=currency,
                    symbol=symbol,
                    side=side,
                    quantity=Decimal(quantity),
                    price=Decimal("150"),
                    fee=Decimal(fee),
                    fee_currency=fee_currency,
                    notional=Decimal(quantity) * Decimal("150"),
                    exchange_order_id=f"order-{entry_id}",
                    exchange_fill_id=f"fill-{entry_id}",
                    filled_at=T0 + timedelta(minutes=index),
                    usd_rate_at_fill=Decimal("1"),
                )
            )
            await session.commit()
    return allocation_id


async def _stopped(factory: Factory) -> list[StoppedPosition]:
    async with factory() as session:
        found = await SqlAlchemyStoppedPositionsReader(session).stopped_positions()
    return sorted(found, key=lambda position: str(position.allocation_id))


async def test_it_lists_exactly_the_open_allocations_of_stopped_strategies_of_every_user(
    pg_session_factory: Factory,
) -> None:
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    disabled = await _strategy(pg_session_factory, enabled=False)
    archived = await _strategy(pg_session_factory, enabled=False, archived=True)
    running = await _strategy(pg_session_factory, enabled=True)
    other_disabled = await _strategy(pg_session_factory, author=other, enabled=False)

    # Opened as the alert says it, partly sold under the venue's bare name: 0.7 - 0.2.
    long_after_partial_close = await _allocation(
        pg_session_factory,
        OWNER_ID,
        disabled,
        [
            ("BUY", "SOLUSDT.P", "0.7", "0.0385", "USDT"),
            ("SELL", "SOLUSDT", "0.2", "0.0165", "USDT"),
        ],
    )
    # A short on an archived strategy.
    short = await _allocation(
        pg_session_factory, OWNER_ID, archived, [("SELL", "ETHUSDT", "0.3", "0.02", "USDT")]
    )
    # Netted to zero across two spellings: not a position any more.
    await _allocation(
        pg_session_factory,
        OWNER_ID,
        disabled,
        [
            ("BUY", "SOLUSDT.P", "1", "0.0825", "USDT"),
            ("SELL", "SOLUSDT", "1", "0.0825", "USDT"),
        ],
    )
    # An open one on a RUNNING strategy: the strategy's own signals close it.
    await _allocation(
        pg_session_factory, OWNER_ID, running, [("BUY", "SOLUSDT.P", "0.5", "0.0275", "USDT")]
    )
    # Another user's, on their own strategy, on another pool; the fee here is charged in the
    # base currency, so what arrived is 1 - 0.001.
    spot = await _allocation(
        pg_session_factory,
        other,
        other_disabled,
        [("BUY", "BTC_USDT", "1", "0.001", "BTC")],
        market=PIONEX,
    )

    found = await _stopped(pg_session_factory)

    assert found == sorted(
        [
            StoppedPosition(
                user_id=OWNER_ID,
                allocation_id=long_after_partial_close,
                strategy_id=disabled,
                exchange="bybit",
                venue="usdt-m",
                settlement_currency="USDT",
                symbol="SOLUSDT.P",
                net_base=Decimal("0.5"),
            ),
            StoppedPosition(
                user_id=OWNER_ID,
                allocation_id=short,
                strategy_id=archived,
                exchange="bybit",
                venue="usdt-m",
                settlement_currency="USDT",
                symbol="ETHUSDT",
                net_base=Decimal("-0.3"),
            ),
            StoppedPosition(
                user_id=other,
                allocation_id=spot,
                strategy_id=other_disabled,
                exchange="pionex",
                venue="spot",
                settlement_currency="USDT",
                symbol="BTC_USDT",
                net_base=Decimal("0.999"),
            ),
        ],
        key=lambda position: str(position.allocation_id),
    )


async def test_a_position_is_reported_under_the_spelling_it_opened_with(
    pg_session_factory: Factory,
) -> None:
    """The closing fill carries the venue's bare name and is the LATEST row, so a reader that
    takes any row's spelling would name ``SOLUSDT`` here. The opening's is ``SOLUSDT.P``."""
    disabled = await _strategy(pg_session_factory, enabled=False)
    await _allocation(
        pg_session_factory,
        OWNER_ID,
        disabled,
        [
            ("BUY", "SOLUSDT.P", "1", "0.0825", "USDT"),
            ("SELL", "SOLUSDT", "0.5", "0.04", "USDT"),
        ],
    )

    [position] = await _stopped(pg_session_factory)

    assert position.symbol == "SOLUSDT.P"
    assert position.net_base == Decimal("0.5")


async def test_nothing_is_listed_when_every_strategy_is_running(
    pg_session_factory: Factory,
) -> None:
    running = await _strategy(pg_session_factory, enabled=True)
    await _allocation(
        pg_session_factory, OWNER_ID, running, [("BUY", "SOLUSDT.P", "0.5", "0.0275", "USDT")]
    )

    assert await _stopped(pg_session_factory) == []


async def test_a_strategy_is_stopped_when_disabled_or_archived_and_not_when_running(
    pg_session_factory: Factory,
) -> None:
    disabled = await _strategy(pg_session_factory, enabled=False)
    archived = await _strategy(pg_session_factory, enabled=False, archived=True)
    running = await _strategy(pg_session_factory, enabled=True)

    async with pg_session_factory() as session:
        reader = SqlAlchemyStoppedPositionsReader(session)
        assert await reader.is_stopped(disabled) is True
        assert await reader.is_stopped(archived) is True
        assert await reader.is_stopped(running) is False
