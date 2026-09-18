"""Integration test: projecting a WHOLE POOL's ledger rows into one
``LedgerPosition`` per symbol — the number ``ScanPools`` compares against the
venue's own report [DB].

Runs against real PostgreSQL for the same reason ``test_held_base_integration
.py`` does: this is a SQL aggregate (``GROUP BY`` + ``HAVING``), and the parts
most likely to be wrong are the parts SQL does silently -- which allocations
survive the ``HAVING <> 0`` filter, and which fee currency triggers the
subtraction.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.ledger.application.read_symbol_positions import ReadSymbolPositions
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.domain.positions import LedgerPosition
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

FILLED_AT = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
POOL = ("bybit", "usdt-m", "USDT")


async def _seed_position(
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
    symbol: str = "BTCUSDT",
    side: str,
    quantity: str,
    fee: str = "0",
    fee_currency: str = "USDT",
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
        fee=Decimal(fee),
        fee_currency=fee_currency,
        notional=Decimal(quantity) * price,
        exchange_order_id=f"EX-{uuid4()}",
        exchange_fill_id=f"F-{uuid4()}",
        filled_at=FILLED_AT,
        usd_rate_at_fill=Decimal("1"),
    )


async def _read(session_factory: async_sessionmaker[AsyncSession]) -> list[LedgerPosition]:
    async with session_factory() as session:
        reader = ReadSymbolPositions(SqlAlchemyLedgerRepository(session))
        return await reader.net_positions_by_symbol(POOL)


async def test_an_open_allocation_is_grouped_under_its_symbol(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                symbol="BTCUSDT",
                side="BUY",
                quantity="0.002",
            )
        )
        await session.commit()

    positions = await _read(pg_session_factory)

    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].net_base == Decimal("0.002")
    assert positions[0].allocation_ids == (allocation_id,)


async def test_a_fully_closed_allocation_vanishes_from_the_result(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The HAVING filter, proven: an allocation that nets to zero must not
    survive as an ``OpenAllocation`` carrying nothing, because ``classify()``
    reads an EMPTY tuple as "no allocation was ever open here"."""
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)
    closing_attempt_id = uuid4()
    await seed_execution_attempt(
        pg_session_factory, attempt_id=closing_attempt_id, closes_allocation_id=allocation_id
    )

    async with pg_session_factory() as session:
        recorder = RecordFill(SqlAlchemyLedgerRepository(session))
        await recorder.record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="BUY",
                quantity="0.002",
            )
        )
        await recorder.record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=closing_attempt_id,
                side="SELL",
                quantity="0.002",
            )
        )
        await session.commit()

    positions = await _read(pg_session_factory)

    assert positions == []


async def test_two_allocations_on_the_same_symbol_both_appear(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)
    _, other_allocation_id, other_attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        recorder = RecordFill(SqlAlchemyLedgerRepository(session))
        await recorder.record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="BUY",
                quantity="0.002",
            )
        )
        await recorder.record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=other_allocation_id,
                attempt_id=other_attempt_id,
                side="BUY",
                quantity="0.099",
            )
        )
        await session.commit()

    positions = await _read(pg_session_factory)

    assert len(positions) == 1
    assert positions[0].net_base == Decimal("0.101")
    assert set(positions[0].allocation_ids) == {allocation_id, other_allocation_id}


async def test_different_symbols_are_kept_separate(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)
    _, other_allocation_id, other_attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        recorder = RecordFill(SqlAlchemyLedgerRepository(session))
        await recorder.record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                symbol="BTCUSDT",
                side="BUY",
                quantity="0.002",
            )
        )
        await recorder.record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=other_allocation_id,
                attempt_id=other_attempt_id,
                symbol="ETHUSDT",
                side="SELL",
                quantity="1.5",
            )
        )
        await session.commit()

    positions = await _read(pg_session_factory)

    by_symbol = {p.symbol: p for p in positions}
    assert by_symbol["BTCUSDT"].net_base == Decimal("0.002")
    assert by_symbol["ETHUSDT"].net_base == Decimal("-1.5")


async def test_a_fee_paid_in_the_settlement_currency_does_not_reduce_the_base(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Design decision 4, provably a no-op on USDT-M: the fee is charged in
    the pool's OWN settlement currency, so it must not touch the base side."""
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="BUY",
                quantity="0.002",
                fee="0.05",
                fee_currency="USDT",
            )
        )
        await session.commit()

    positions = await _read(pg_session_factory)

    assert positions[0].net_base == Decimal("0.002")


async def test_a_fee_paid_off_the_settlement_currency_reduces_the_base(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Design decision 4's load-bearing case: a fee NOT in the settlement
    currency is charged in the base currency here, and must reduce it."""
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="BUY",
                quantity="0.002",
                fee="0.000002",
                fee_currency="BTC",
            )
        )
        await session.commit()

    positions = await _read(pg_session_factory)

    assert positions[0].net_base == Decimal("0.001998")


async def test_another_pool_is_never_counted(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_position(
        pg_session_factory
    )

    async with pg_session_factory() as session:
        recorder = RecordFill(SqlAlchemyLedgerRepository(session))
        fill = _fill(
            strategy_id=strategy_id,
            allocation_id=allocation_id,
            attempt_id=attempt_id,
            side="BUY",
            quantity="0.002",
        )
        # A pool that is NOT the one this test reads back.
        await recorder.record(replace(fill, exchange="pionex", venue="spot"))
        await session.commit()

    positions = await _read(pg_session_factory)

    assert positions == []


async def test_an_empty_pool_reads_no_symbols_at_all(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    positions = await _read(pg_session_factory)

    assert positions == []
