"""Integration test: projecting one allocation's ledger rows into the base
currency it still holds — the number a close is sized from [DB].

This runs against real PostgreSQL because the projection is a SQL aggregate,
and the parts most likely to be wrong are the parts SQL does silently: the
sign of a sell, and which fees reduce a base holding. A unit test over a fake
would assert my own arithmetic back at me.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.ledger.application.read_held_base import ReadHeldBase
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

FILLED_AT = datetime(2026, 8, 21, 12, 0, 0, tzinfo=UTC)


async def _seed_position(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID, UUID]:
    """One strategy, one signal, one reservation, one opening attempt."""
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
    side: str,
    quantity: str,
    fee: str,
    fee_currency: str,
) -> FillRecord:
    price = Decimal("50000")
    return FillRecord(exchange="bybit", 
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        execution_attempt_id=attempt_id,
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="BTC_USDT",
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


async def test_a_base_currency_fee_reduces_what_can_be_sold(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The trap. If Pionex took its cut in BTC on a BTC_USDT buy, less BTC
    arrived than was bought, and selling the purchased quantity is an order the
    exchange rejects for insufficient balance."""
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="BUY",
                quantity="0.00200000",
                fee="0.00000200",
                fee_currency="BTC",
            )
        )
        await session.commit()

    async with pg_session_factory() as session:
        held = await ReadHeldBase(SqlAlchemyLedgerRepository(session)).net_base(
            allocation_id, "BTC"
        )

    assert held == Decimal("0.00199800")


async def test_a_quote_currency_fee_does_not_touch_the_base_holding(
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
                quantity="0.00200000",
                fee="0.05000000",
                fee_currency="USDT",
            )
        )
        await session.commit()

    async with pg_session_factory() as session:
        held = await ReadHeldBase(SqlAlchemyLedgerRepository(session)).net_base(
            allocation_id, "BTC"
        )

    assert held == Decimal("0.00200000")


async def test_a_market_order_filled_in_pieces_sums_to_the_whole_position(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """One ledger row per exchange fill is the whole reason this is a sum and
    not a lookup."""
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        recorder = RecordFill(SqlAlchemyLedgerRepository(session))
        for quantity in ("0.00100000", "0.00050000", "0.00025000"):
            await recorder.record(
                _fill(
                    strategy_id=strategy_id,
                    allocation_id=allocation_id,
                    attempt_id=attempt_id,
                    side="BUY",
                    quantity=quantity,
                    fee="0",
                    fee_currency="USDT",
                )
            )
        await session.commit()

    async with pg_session_factory() as session:
        held = await ReadHeldBase(SqlAlchemyLedgerRepository(session)).net_base(
            allocation_id, "BTC"
        )

    assert held == Decimal("0.00175000")


async def test_a_sell_already_recorded_is_subtracted(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Guards against double-selling a position whose close partly landed
    before this ran again."""
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)
    closing_attempt_id = uuid4()
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=closing_attempt_id,
        closes_allocation_id=allocation_id,
    )

    async with pg_session_factory() as session:
        recorder = RecordFill(SqlAlchemyLedgerRepository(session))
        await recorder.record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="BUY",
                quantity="0.00200000",
                fee="0",
                fee_currency="USDT",
            )
        )
        await recorder.record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=closing_attempt_id,
                side="SELL",
                quantity="0.00050000",
                fee="0",
                fee_currency="USDT",
            )
        )
        await session.commit()

    async with pg_session_factory() as session:
        held = await ReadHeldBase(SqlAlchemyLedgerRepository(session)).net_base(
            allocation_id, "BTC"
        )

    assert held == Decimal("0.00150000")


async def test_a_fully_closed_position_holds_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A second close signal for the same position must not size an order.
    ClosePosition reads zero here and refuses rather than selling again."""
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)
    closing_attempt_id = uuid4()
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=closing_attempt_id,
        closes_allocation_id=allocation_id,
    )

    async with pg_session_factory() as session:
        recorder = RecordFill(SqlAlchemyLedgerRepository(session))
        await recorder.record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="BUY",
                quantity="0.00200000",
                fee="0",
                fee_currency="USDT",
            )
        )
        await recorder.record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=closing_attempt_id,
                side="SELL",
                quantity="0.00200000",
                fee="0",
                fee_currency="USDT",
            )
        )
        await session.commit()

    async with pg_session_factory() as session:
        held = await ReadHeldBase(SqlAlchemyLedgerRepository(session)).net_base(
            allocation_id, "BTC"
        )

    assert held == Decimal("0")


async def test_another_allocations_rows_are_never_counted(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The reason this app exists: several strategies compete for one account,
    so two allocations can hold the same coin at the same time. Closing one
    must never size itself from the other's position."""
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
                quantity="0.00200000",
                fee="0",
                fee_currency="USDT",
            )
        )
        await recorder.record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=other_allocation_id,
                attempt_id=other_attempt_id,
                side="BUY",
                quantity="0.09900000",
                fee="0",
                fee_currency="USDT",
            )
        )
        await session.commit()

    async with pg_session_factory() as session:
        held = await ReadHeldBase(SqlAlchemyLedgerRepository(session)).net_base(
            allocation_id, "BTC"
        )

    assert held == Decimal("0.00200000")


async def test_an_allocation_with_no_rows_holds_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """COALESCE, not None. The opening fills may simply not have settled yet,
    and ClosePosition turns this into a retry."""
    _, allocation_id, _ = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        held = await ReadHeldBase(SqlAlchemyLedgerRepository(session)).net_base(
            allocation_id, "BTC"
        )

    assert held == Decimal("0")


async def test_a_short_reads_back_as_a_negative_position_not_as_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A futures short is opened by a SELL, so its net base quantity is
    negative. The projection used to clamp at zero, which reported every short
    as "nothing held": ``ClosePosition`` then raised ``NothingRecordedYet`` and
    retried forever while a real leveraged position stayed open at the venue.

    The fee is charged in USDT on a sell, so it does not touch the base side.
    """
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="SELL",
                quantity="0.00780000",
                fee="0.24960000",
                fee_currency="USDT",
            )
        )
        await session.commit()

    async with pg_session_factory() as session:
        held = await ReadHeldBase(SqlAlchemyLedgerRepository(session)).net_base(
            allocation_id, "BTC"
        )

    assert held == Decimal("-0.00780000")


async def test_a_short_bought_back_in_full_reads_back_flat(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The round trip a futures close performs: sell to open, buy the same
    quantity to flatten."""
    strategy_id, allocation_id, attempt_id = await _seed_position(pg_session_factory)

    async with pg_session_factory() as session:
        recorder = RecordFill(SqlAlchemyLedgerRepository(session))
        for side in ("SELL", "BUY"):
            await recorder.record(
                _fill(
                    strategy_id=strategy_id,
                    allocation_id=allocation_id,
                    attempt_id=attempt_id,
                    side=side,
                    quantity="0.00780000",
                    fee="0.24960000",
                    fee_currency="USDT",
                )
            )
        await session.commit()

    async with pg_session_factory() as session:
        held = await ReadHeldBase(SqlAlchemyLedgerRepository(session)).net_base(
            allocation_id, "BTC"
        )

    assert held == Decimal("0")
