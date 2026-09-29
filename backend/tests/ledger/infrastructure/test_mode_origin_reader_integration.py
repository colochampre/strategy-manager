"""Decision 28 on real PostgreSQL: the read behind the ``DRY_RUN`` mode guard.

Seeded through the real, append-only ledger (``RecordFill``), because the parts
most likely to be wrong are the ones SQL does silently: which rows count as a
rehearsal fill, the sign of a sell, which fees reduce a base holding, and
whether a pool nobody trades any more is still looked at.

Placed beside the other ledger integration tests: it needs ``ledger_entries``
in the schema fixture, which the execution one does not create.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.domain.fill import (
    REHEARSAL_FILL_ID_PREFIX,
    REHEARSAL_ORDER_ID_PREFIX,
)
from strategy_manager.execution.infrastructure.mode_origin_reader import (
    SqlAlchemyModeOriginReader,
)
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

FILLED_AT = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


class Allocation:
    def __init__(self, strategy_id: UUID, allocation_id: UUID, attempt_id: UUID) -> None:
        self.strategy_id = strategy_id
        self.allocation_id = allocation_id
        self.attempt_id = attempt_id

    @property
    def strategy_name(self) -> str:
        return f"strategy-{self.strategy_id}"


async def _seed_allocation(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    exchange: str = "bybit",
    venue: str = "usdt-m",
    settlement_currency: str = "USDT",
) -> Allocation:
    strategy_id, signal_id = uuid4(), uuid4()
    allocation_id, attempt_id = uuid4(), uuid4()
    await seed_strategy(
        session_factory,
        strategy_id=strategy_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
    )
    await seed_signal(
        session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        session_factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
        status="FILLED",
    )
    await seed_execution_attempt(
        session_factory,
        attempt_id=attempt_id,
        reservation_id=allocation_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
        status="FILLED",
    )
    return Allocation(strategy_id, allocation_id, attempt_id)


async def _record(
    session_factory: async_sessionmaker[AsyncSession],
    allocation: Allocation,
    *,
    side: str,
    quantity: str,
    rehearsal: bool,
    symbol: str = "SOLUSDT.P",
    fee: str = "0",
    fee_currency: str = "USDT",
    exchange: str = "bybit",
    venue: str = "usdt-m",
    settlement_currency: str = "USDT",
    fill_id: str | None = None,
) -> None:
    price = Decimal("100")
    prefix = REHEARSAL_FILL_ID_PREFIX if rehearsal else "live-"
    async with session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            FillRecord(
                exchange=exchange,
                strategy_id=allocation.strategy_id,
                allocation_id=allocation.allocation_id,
                execution_attempt_id=allocation.attempt_id,
                venue=venue,
                settlement_currency=settlement_currency,
                symbol=symbol,
                side=side,
                quantity=Decimal(quantity),
                price=price,
                fee=Decimal(fee),
                fee_currency=fee_currency,
                notional=Decimal(quantity) * price,
                exchange_order_id=f"order-{uuid4()}",
                exchange_fill_id=fill_id or f"{prefix}{uuid4()}",
                filled_at=FILLED_AT,
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()


async def _open_allocations(session_factory: async_sessionmaker[AsyncSession]) -> list:  # type: ignore[type-arg]
    async with session_factory() as session:
        return list(await SqlAlchemyModeOriginReader(session).open_allocations())


async def _in_flight(session_factory: async_sessionmaker[AsyncSession]) -> list:  # type: ignore[type-arg]
    async with session_factory() as session:
        return list(await SqlAlchemyModeOriginReader(session).in_flight_attempts())


# --- open allocations: the origin of their fills ---------------------------


async def test_an_open_allocation_holding_a_rehearsal_fill_is_read_as_rehearsal(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation = await _seed_allocation(pg_session_factory)
    await _record(pg_session_factory, allocation, side="BUY", quantity="0.5", rehearsal=True)

    found = await _open_allocations(pg_session_factory)

    assert len(found) == 1
    assert found[0].allocation_id == allocation.allocation_id
    assert found[0].strategy_name == allocation.strategy_name
    assert (found[0].exchange, found[0].venue, found[0].settlement_currency) == (
        "bybit",
        "usdt-m",
        "USDT",
    )
    assert found[0].symbol == "SOLUSDT.P"
    assert found[0].holds_rehearsal_fill is True
    assert found[0].holds_live_fill is False


async def test_an_open_allocation_holding_a_live_fill_is_read_as_live(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation = await _seed_allocation(pg_session_factory)
    await _record(pg_session_factory, allocation, side="BUY", quantity="0.5", rehearsal=False)

    found = await _open_allocations(pg_session_factory)

    assert [(f.allocation_id, f.holds_rehearsal_fill, f.holds_live_fill) for f in found] == [
        (allocation.allocation_id, False, True)
    ]


async def test_the_marker_is_a_prefix_not_a_substring(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A live fill whose id merely CONTAINS the marker is still live. Reading
    it as rehearsal would let a live position through a ``DRY_RUN=true`` start."""
    allocation = await _seed_allocation(pg_session_factory)
    await _record(
        pg_session_factory,
        allocation,
        side="BUY",
        quantity="0.5",
        rehearsal=False,
        fill_id=f"venue-{REHEARSAL_FILL_ID_PREFIX}1",
    )

    found = await _open_allocations(pg_session_factory)

    assert [(f.holds_rehearsal_fill, f.holds_live_fill) for f in found] == [(False, True)]


async def test_an_allocation_holding_both_kinds_reads_as_both(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation = await _seed_allocation(pg_session_factory)
    await _record(pg_session_factory, allocation, side="BUY", quantity="1", rehearsal=False)
    await _record(pg_session_factory, allocation, side="SELL", quantity="0.4", rehearsal=True)

    found = await _open_allocations(pg_session_factory)

    assert [(f.holds_rehearsal_fill, f.holds_live_fill) for f in found] == [(True, True)]


# --- "open" is the ledger's rule --------------------------------------------


async def test_a_closed_rehearsal_allocation_is_not_read(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """6d.4: the AAVE and SFP round trips in production. Net base exactly
    zero, no live fill; they must never block a live start."""
    closed = await _seed_allocation(pg_session_factory)
    await _record(pg_session_factory, closed, side="BUY", quantity="0.5", rehearsal=True)
    await _record(pg_session_factory, closed, side="SELL", quantity="0.5", rehearsal=True)
    held = await _seed_allocation(pg_session_factory)
    await _record(pg_session_factory, held, side="BUY", quantity="0.5", rehearsal=True)

    found = await _open_allocations(pg_session_factory)

    assert [f.allocation_id for f in found] == [held.allocation_id]


async def test_an_open_and_a_close_under_two_spellings_are_one_closed_allocation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation = await _seed_allocation(pg_session_factory)
    await _record(
        pg_session_factory, allocation, side="BUY", quantity="0.5", rehearsal=True,
        symbol="SOLUSDT.P",
    )
    await _record(
        pg_session_factory, allocation, side="SELL", quantity="0.5", rehearsal=True,
        symbol="SOLUSDT",
    )

    assert await _open_allocations(pg_session_factory) == []


async def test_a_base_currency_fee_keeps_an_allocation_open_until_what_arrived_is_sold(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The base-fee rule, on real rows. Pionex spot took a BUY's fee in the
    base coin: 0.002 bought, 0.000002 kept, so a SELL of 0.002 leaves a
    remainder and the position is NOT flat."""
    pool = {"exchange": "pionex", "venue": "spot", "settlement_currency": "USDT"}
    short = await _seed_allocation(pg_session_factory, **pool)
    await _record(
        pg_session_factory, short, side="BUY", quantity="0.002", rehearsal=False,
        symbol="BTC_USDT", fee="0.000002", fee_currency="BTC", **pool,
    )
    await _record(
        pg_session_factory, short, side="SELL", quantity="0.002", rehearsal=False,
        symbol="BTC_USDT", **pool,
    )
    flat = await _seed_allocation(pg_session_factory, **pool)
    await _record(
        pg_session_factory, flat, side="BUY", quantity="0.002", rehearsal=False,
        symbol="BTC_USDT", fee="0.000002", fee_currency="BTC", **pool,
    )
    await _record(
        pg_session_factory, flat, side="SELL", quantity="0.001998", rehearsal=False,
        symbol="BTC_USDT", **pool,
    )

    found = await _open_allocations(pg_session_factory)

    assert [f.allocation_id for f in found] == [short.allocation_id]


async def test_a_fee_in_the_settlement_currency_does_not_leave_a_remainder(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation = await _seed_allocation(pg_session_factory)
    await _record(
        pg_session_factory, allocation, side="BUY", quantity="0.5", rehearsal=False,
        fee="0.03", fee_currency="USDT",
    )
    await _record(
        pg_session_factory, allocation, side="SELL", quantity="0.5", rehearsal=False,
        fee="0.03", fee_currency="USDT",
    )

    assert await _open_allocations(pg_session_factory) == []


# --- every pool, enabled or not ------------------------------------------------


async def test_a_pool_that_is_disabled_is_still_read(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A position stays open at the venue whether or not anyone still trades
    the pool it sits in."""
    allocation = await _seed_allocation(pg_session_factory)
    await _record(pg_session_factory, allocation, side="BUY", quantity="0.5", rehearsal=False)
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "UPDATE capital_pools SET enabled = false "
                "WHERE exchange = 'bybit' AND venue = 'usdt-m'"
            )
        )
        await session.commit()

    found = await _open_allocations(pg_session_factory)

    assert [f.allocation_id for f in found] == [allocation.allocation_id]


async def test_allocations_in_different_pools_are_all_read(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    futures = await _seed_allocation(pg_session_factory)
    await _record(pg_session_factory, futures, side="BUY", quantity="1", rehearsal=True)
    pool = {"exchange": "pionex", "venue": "coin-m", "settlement_currency": "BTC"}
    coin_m = await _seed_allocation(pg_session_factory, **pool)
    await _record(
        pg_session_factory, coin_m, side="BUY", quantity="1", rehearsal=False,
        symbol="ETH_BTC", fee_currency="BTC", **pool,
    )

    found = await _open_allocations(pg_session_factory)

    assert {(f.allocation_id, f.holds_rehearsal_fill) for f in found} == {
        (futures.allocation_id, True),
        (coin_m.allocation_id, False),
    }


async def test_an_empty_ledger_reads_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await _open_allocations(pg_session_factory) == []


# --- in-flight attempts ---------------------------------------------------------


async def _seed_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: str,
    exchange_order_id: str | None,
    closing: bool = False,
) -> tuple[Allocation, UUID]:
    allocation = await _seed_allocation(session_factory)
    attempt_id = uuid4()
    if closing:
        await seed_execution_attempt(
            session_factory,
            attempt_id=attempt_id,
            closes_allocation_id=allocation.allocation_id,
            status=status,
            exchange_order_id=exchange_order_id,
            symbol="ETHUSDT.P",
        )
    else:
        await _seed_open_attempt(
            session_factory, allocation, attempt_id, status, exchange_order_id
        )
    return allocation, attempt_id


async def _seed_open_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    allocation: Allocation,
    attempt_id: UUID,
    status: str,
    exchange_order_id: str | None,
) -> None:
    """A second reservation so the opening attempt has its own (one opening
    order per reservation)."""
    signal_id, reservation_id = uuid4(), uuid4()
    await seed_signal(
        session_factory,
        signal_id=signal_id,
        strategy_id=allocation.strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        session_factory,
        reservation_id=reservation_id,
        strategy_id=allocation.strategy_id,
        signal_id=signal_id,
    )
    await seed_execution_attempt(
        session_factory,
        attempt_id=attempt_id,
        reservation_id=reservation_id,
        status=status,
        exchange_order_id=exchange_order_id,
        symbol="ETHUSDT.P",
    )


async def test_a_submitted_attempt_with_a_fake_order_id_is_read_as_rehearsal(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    order_id = f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}"
    allocation, attempt_id = await _seed_attempt(
        pg_session_factory, status="SUBMITTED", exchange_order_id=order_id
    )

    found = await _in_flight(pg_session_factory)

    assert len(found) == 1
    assert found[0].attempt_id == attempt_id
    assert found[0].strategy_name == allocation.strategy_name
    assert (found[0].exchange, found[0].venue, found[0].settlement_currency) == (
        "bybit",
        "usdt-m",
        "USDT",
    )
    assert found[0].symbol == "ETHUSDT.P"
    assert found[0].exchange_order_id == order_id
    assert found[0].rehearsal is True


async def test_a_submitted_attempt_with_a_venue_order_id_is_read_as_live(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, attempt_id = await _seed_attempt(
        pg_session_factory,
        status="SUBMITTED",
        exchange_order_id="8f0c2a3e-6a51-4c1b-9d0a-2f7c1e5b7a10",
    )

    found = await _in_flight(pg_session_factory)

    assert [(f.attempt_id, f.rehearsal) for f in found] == [(attempt_id, False)]


async def test_a_closing_attempt_is_read_too_and_named_after_its_strategy(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation, attempt_id = await _seed_attempt(
        pg_session_factory,
        status="SUBMITTED",
        exchange_order_id="1234567890123",
        closing=True,
    )

    found = await _in_flight(pg_session_factory)

    assert [(f.attempt_id, f.strategy_name) for f in found] == [
        (attempt_id, allocation.strategy_name)
    ]


@pytest.mark.parametrize("status", ["FILLED", "FAILED", "ABORTED_EXPIRED"])
async def test_a_terminal_attempt_is_not_in_flight(
    pg_session_factory: async_sessionmaker[AsyncSession], status: str
) -> None:
    await _seed_attempt(
        pg_session_factory,
        status=status,
        exchange_order_id=f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}",
    )

    assert await _in_flight(pg_session_factory) == []


async def test_a_submitted_attempt_the_exchange_has_not_yet_named_is_not_read(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The gap, pinned. Until ``mark_placed`` there is no order id, so nothing
    in the row says which mode wrote it; the guard cannot judge it and does
    not pretend to."""
    await _seed_attempt(pg_session_factory, status="SUBMITTED", exchange_order_id=None)

    assert await _in_flight(pg_session_factory) == []
