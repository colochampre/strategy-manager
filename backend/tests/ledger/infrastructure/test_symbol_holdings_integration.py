"""Integration test: projecting one market's ledger rows -- across every
spelling it wears -- into one ``HeldAllocation`` per ``(strategy, allocation)``
still open on it [DB]. This is what the Existing-Position Guard (S2) and
orphan classification (S4) both read.

Runs against real PostgreSQL for the same reason
``test_symbol_positions_integration.py`` does: this is a SQL aggregate
(``GROUP BY`` + ``HAVING``), and the parts most likely to be wrong are the
parts SQL does silently -- which spelling a row was recorded under, and
whether merging spellings correctly nets an allocation to zero.

**Binding testing lesson**: a symbol has three spellings (TradingView
``STXUSDT.P``, venue bare ``STXUSDT``, Pionex ``STXUSDT_PERP``). Any test
comparing across a boundary here inserts under ONE spelling and queries
under a DIFFERENT one, or it proves nothing.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.signals.domain.holding import HeldAllocation
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

FILLED_AT = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
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
    symbol: str = "STXUSDT",
    side: str,
    quantity: str,
    fee: str = "0",
    fee_currency: str = "USDT",
) -> FillRecord:
    price = Decimal("2")
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


async def _read(
    session_factory: async_sessionmaker[AsyncSession], symbol: str
) -> list[HeldAllocation]:
    async with session_factory() as session:
        reader = ReadSymbolHoldings(SqlAlchemyLedgerRepository(session))
        return await reader.symbol_holdings(POOL, symbol)


async def test_a_holding_recorded_under_a_different_spelling_is_found(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Insert under Pionex's spelling, query under TradingView's -- they must
    be treated as the same market."""
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                symbol="STXUSDT_PERP",
                side="BUY",
                quantity="0.5",
            )
        )
        await session.commit()

    holdings = await _read(pg_session_factory, "STXUSDT.P")

    assert len(holdings) == 1
    assert holdings[0].strategy_id == strategy_id
    assert holdings[0].allocation_id == allocation_id
    assert holdings[0].net_base == Decimal("0.5")


async def test_two_strategies_holding_the_same_symbol_both_appear(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The Existing-Position Guard is per strategy, not per pool -- a
    different strategy's holding on the same symbol must not be merged into
    this one's."""
    strategy_a, allocation_a, attempt_a = await _seed_position(pg_session_factory)
    strategy_b, allocation_b, attempt_b = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        recorder = RecordFill(SqlAlchemyLedgerRepository(session))
        await recorder.record(
            _fill(
                strategy_id=strategy_a,
                allocation_id=allocation_a,
                attempt_id=attempt_a,
                side="BUY",
                quantity="0.5",
            )
        )
        await recorder.record(
            _fill(
                strategy_id=strategy_b,
                allocation_id=allocation_b,
                attempt_id=attempt_b,
                side="BUY",
                quantity="0.2",
            )
        )
        await session.commit()

    holdings = await _read(pg_session_factory, "STXUSDT")

    by_strategy = {h.strategy_id: h for h in holdings}
    assert len(holdings) == 2
    assert by_strategy[strategy_a].net_base == Decimal("0.5")
    assert by_strategy[strategy_b].net_base == Decimal("0.2")


async def test_opened_under_one_spelling_and_closed_under_another_nets_to_zero(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The trap a previous bug fell into (bug/reconciliation-symbol-spelling-
    mismatch): merging spellings before applying ``HAVING`` must exclude an
    allocation opened as ``STXUSDT.P`` and closed as ``STXUSDT`` -- grouping
    per spelling first would see two separate non-zero halves and never
    net them out."""
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
                symbol="STXUSDT.P",
                side="BUY",
                quantity="0.5",
            )
        )
        await recorder.record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=closing_attempt_id,
                symbol="STXUSDT",
                side="SELL",
                quantity="0.5",
            )
        )
        await session.commit()

    holdings = await _read(pg_session_factory, "STXUSDT_PERP")

    assert holdings == []


async def test_a_fee_paid_in_the_base_currency_reduces_the_net(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The ``base_currency_of`` fee rule -- the same ``ReadHeldBase`` and
    ``ClosePosition`` use, deliberately NOT ``net_positions_by_symbol``'s
    settlement-currency rule, because this number must equal what a close of
    this specific allocation would size against."""
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="BUY",
                quantity="0.5",
                fee="0.002",
                fee_currency="STX",
            )
        )
        await session.commit()

    holdings = await _read(pg_session_factory, "STXUSDT")

    assert holdings[0].net_base == Decimal("0.498")


async def test_a_fee_paid_in_the_settlement_currency_does_not_reduce_the_net(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="BUY",
                quantity="0.5",
                fee="0.05",
                fee_currency="USDT",
            )
        )
        await session.commit()

    holdings = await _read(pg_session_factory, "STXUSDT")

    assert holdings[0].net_base == Decimal("0.5")


async def test_the_spelling_comparison_is_case_insensitive(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                symbol="stxusdt_perp",
                side="BUY",
                quantity="0.5",
            )
        )
        await session.commit()

    holdings = await _read(pg_session_factory, "STXUSDT.P")

    assert len(holdings) == 1
    assert holdings[0].net_base == Decimal("0.5")


async def test_another_pool_is_never_counted(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        recorder = RecordFill(SqlAlchemyLedgerRepository(session))
        fill = _fill(
            strategy_id=strategy_id,
            allocation_id=allocation_id,
            attempt_id=attempt_id,
            side="BUY",
            quantity="0.5",
        )
        await recorder.record(fill)
        # Same symbol, a DIFFERENT pool -- must never be counted.
        await recorder.record(replace(fill, exchange="pionex", venue="spot"))
        await session.commit()

    holdings = await _read(pg_session_factory, "STXUSDT")

    assert len(holdings) == 1
    assert holdings[0].net_base == Decimal("0.5")


async def test_an_empty_pool_reads_no_holdings(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    holdings = await _read(pg_session_factory, "STXUSDT")

    assert holdings == []
