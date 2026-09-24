"""Integration test: which of a candidate set of fill ids ``ledger_entries``
already holds [DB] -- design.md § 13, the lookup ``match_fills`` (Unit 4a's
domain) filters unrecorded fills against, keyed on ``(exchange, venue,
exchange_fill_id)`` and never symbol.

Runs against real PostgreSQL for the same reason
``test_symbol_positions_integration.py`` does: the composite key is exactly
what SQL enforces silently -- the wrong key (missing ``exchange``, or keyed
on symbol) would answer a plausible-looking but wrong set.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.ledger.application.read_recorded_fill_ids import ReadRecordedFillIds
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

FILLED_AT = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)


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
    exchange_fill_id: str,
    exchange: str = "bybit",
    venue: str = "usdt-m",
    symbol: str = "BTCUSDT",
) -> FillRecord:
    price = Decimal("50000")
    quantity = Decimal("0.002")
    return FillRecord(
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        execution_attempt_id=attempt_id,
        exchange=exchange,
        venue=venue,
        settlement_currency="USDT",
        symbol=symbol,
        side="BUY",
        quantity=quantity,
        price=price,
        fee=Decimal("0"),
        fee_currency="USDT",
        notional=quantity * price,
        exchange_order_id=f"EX-{uuid4()}",
        exchange_fill_id=exchange_fill_id,
        filled_at=FILLED_AT,
        usd_rate_at_fill=Decimal("1"),
    )


async def _recorded(
    session_factory: async_sessionmaker[AsyncSession],
    exchange: str,
    venue: str,
    candidates: list[str],
) -> frozenset[str]:
    async with session_factory() as session:
        reader = ReadRecordedFillIds(SqlAlchemyLedgerRepository(session))
        return await reader.recorded_fill_ids(exchange, venue, candidates)


async def test_a_recorded_fill_id_is_returned(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                exchange_fill_id="F-RECORDED",
            )
        )
        await session.commit()

    recorded = await _recorded(pg_session_factory, "bybit", "usdt-m", ["F-RECORDED"])

    assert recorded == frozenset({"F-RECORDED"})


async def test_an_unrecorded_fill_id_is_not_returned(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recorded = await _recorded(pg_session_factory, "bybit", "usdt-m", ["NEVER-RECORDED"])

    assert recorded == frozenset()


async def test_scoped_to_exchange_and_venue_never_symbol(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``ux_ledger_exchange_fill`` is ``(exchange, venue, exchange_fill_id)``
    -- the same id recorded under a DIFFERENT exchange must not be reported
    as recorded here, and the lookup takes no symbol parameter at all, so a
    fill recorded under one spelling is still found regardless of which
    spelling the caller happens to know (design.md § 13)."""
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                exchange_fill_id="F-1",
                exchange="bybit",
                venue="usdt-m",
                symbol="STXUSDT.P",
            )
        )
        await session.commit()

    same_id_other_exchange = await _recorded(pg_session_factory, "binance", "usdt-m", ["F-1"])
    assert same_id_other_exchange == frozenset()

    found_regardless_of_symbol = await _recorded(pg_session_factory, "bybit", "usdt-m", ["F-1"])
    assert found_regardless_of_symbol == frozenset({"F-1"})


async def test_a_mix_of_recorded_and_unrecorded_ids_returns_only_the_recorded_ones(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                exchange_fill_id="F-RECORDED",
            )
        )
        await session.commit()

    recorded = await _recorded(
        pg_session_factory, "bybit", "usdt-m", ["F-RECORDED", "F-NOT-RECORDED"]
    )

    assert recorded == frozenset({"F-RECORDED"})


async def test_an_empty_candidate_list_returns_an_empty_set(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recorded = await _recorded(pg_session_factory, "bybit", "usdt-m", [])

    assert recorded == frozenset()
