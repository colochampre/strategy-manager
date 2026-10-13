"""The cases the mode guard's own integration test seeds, as ONE shared helper
(design addendum "open positions", section L, T3; tasks.md op.1.26).

The guard's test file (``tests/ledger/infrastructure/test_mode_origin_reader_
integration.py``) is read-only and its helpers are private to it, so this module
seeds the same shapes on its own: a disabled pool, two pools, a base-currency
fee, two spellings of one market, a live fill id that only CONTAINS the
rehearsal marker, a closing attempt, a terminal attempt and an attempt with no
order id. Everything is written through the real, append-only ledger.

``seed_guard_cases`` returns the ids a test needs to look a case up.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.domain.fill import (
    REHEARSAL_FILL_ID_PREFIX,
    REHEARSAL_ORDER_ID_PREFIX,
)
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

FILLED_AT = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
PIONEX_SPOT = {"exchange": "pionex", "venue": "spot", "settlement_currency": "USDT"}
PIONEX_COIN_M_BTC = {"exchange": "pionex", "venue": "coin-m", "settlement_currency": "BTC"}
PIONEX_COIN_M_ETH = {"exchange": "pionex", "venue": "coin-m", "settlement_currency": "ETH"}


@dataclass(frozen=True, slots=True)
class Allocation:
    strategy_id: UUID
    allocation_id: UUID
    attempt_id: UUID


@dataclass(frozen=True, slots=True)
class GuardCases:
    """The ids of the cases. ``open_*`` are open allocations; ``closed_*`` are
    flat ones the guard does not read; ``orders_*`` are attempts."""

    open_rehearsal: UUID
    open_live: UUID
    open_mixed: UUID
    open_live_marker_in_id: UUID
    open_two_spellings: UUID
    open_disabled_pool: UUID
    open_coin_m_btc: UUID
    open_base_fee_short: UUID
    open_unresolved: UUID
    closed_two_spellings: UUID
    closed_rehearsal: UUID
    closed_base_fee_flat: UUID
    leveraged_allocation: UUID
    order_live: UUID
    order_rehearsal: UUID
    order_closing: UUID
    order_terminal: UUID
    order_without_id: UUID
    order_without_id_closing: UUID

    @property
    def open_ids(self) -> set[UUID]:
        return {
            self.open_rehearsal,
            self.open_live,
            self.open_mixed,
            self.open_live_marker_in_id,
            self.open_two_spellings,
            self.open_disabled_pool,
            self.open_coin_m_btc,
            self.open_base_fee_short,
            self.open_unresolved,
        }

    @property
    def in_flight_ids(self) -> set[UUID]:
        """What the guard's in-flight read answers: SUBMITTED with an order id."""
        return {self.order_live, self.order_rehearsal, self.order_closing}


async def seed_allocation(
    factory: async_sessionmaker[AsyncSession],
    *,
    exchange: str = "bybit",
    venue: str = "usdt-m",
    settlement_currency: str = "USDT",
    leverage: Decimal | None = None,
) -> Allocation:
    strategy_id, signal_id = uuid4(), uuid4()
    allocation_id, attempt_id = uuid4(), uuid4()
    await seed_strategy(
        factory,
        strategy_id=strategy_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
    )
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    await seed_reservation(
        factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
        status="FILLED",
    )
    await seed_execution_attempt(
        factory,
        attempt_id=attempt_id,
        reservation_id=allocation_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
        status="FILLED",
    )
    if leverage is not None:
        async with factory() as session:
            await session.execute(
                text("UPDATE execution_attempts SET leverage = :leverage WHERE id = :id"),
                {"leverage": leverage, "id": attempt_id},
            )
            await session.commit()
    return Allocation(strategy_id, allocation_id, attempt_id)


async def record_fill(
    factory: async_sessionmaker[AsyncSession],
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
    async with factory() as session:
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


async def _seed_attempt(
    factory: async_sessionmaker[AsyncSession],
    *,
    status: str,
    exchange_order_id: str | None,
    closing: bool = False,
) -> tuple[Allocation, UUID]:
    """An attempt of a strategy that has its own allocation; a closing one points
    at that allocation, an opening one at a reservation of its own (one opening
    order per reservation)."""
    allocation = await seed_allocation(factory)
    attempt_id = uuid4()
    if closing:
        await seed_execution_attempt(
            factory,
            attempt_id=attempt_id,
            closes_allocation_id=allocation.allocation_id,
            status=status,
            exchange_order_id=exchange_order_id,
            symbol="ETHUSDT.P",
        )
        return allocation, attempt_id
    signal_id, reservation_id = uuid4(), uuid4()
    await seed_signal(
        factory,
        signal_id=signal_id,
        strategy_id=allocation.strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        factory,
        reservation_id=reservation_id,
        strategy_id=allocation.strategy_id,
        signal_id=signal_id,
    )
    await seed_execution_attempt(
        factory,
        attempt_id=attempt_id,
        reservation_id=reservation_id,
        status=status,
        exchange_order_id=exchange_order_id,
        symbol="ETHUSDT.P",
    )
    return allocation, attempt_id


async def seed_guard_cases(factory: async_sessionmaker[AsyncSession]) -> GuardCases:
    # open: rehearsal, live, and both
    rehearsal = await seed_allocation(factory)
    await record_fill(factory, rehearsal, side="BUY", quantity="0.5", rehearsal=True)
    live = await seed_allocation(factory, leverage=Decimal("2"))
    await record_fill(factory, live, side="BUY", quantity="0.5", rehearsal=False)
    mixed = await seed_allocation(factory)
    await record_fill(factory, mixed, side="BUY", quantity="1", rehearsal=False)
    await record_fill(factory, mixed, side="SELL", quantity="0.4", rehearsal=True)

    # a LIVE fill whose id merely contains the rehearsal marker is live
    marker = await seed_allocation(factory)
    await record_fill(
        factory, marker, side="BUY", quantity="0.5", rehearsal=False,
        fill_id=f"venue-{REHEARSAL_FILL_ID_PREFIX}1",
    )  # fmt: skip

    # two spellings of one market: opened as SOLUSDT.P, partly closed as SOLUSDT
    spellings_open = await seed_allocation(factory)
    await record_fill(
        factory, spellings_open, side="BUY", quantity="0.5", rehearsal=True, symbol="SOLUSDT.P"
    )
    await record_fill(
        factory, spellings_open, side="SELL", quantity="0.2", rehearsal=True, symbol="SOLUSDT"
    )
    spellings_closed = await seed_allocation(factory)
    await record_fill(
        factory, spellings_closed, side="BUY", quantity="0.5", rehearsal=True, symbol="SOLUSDT.P"
    )
    await record_fill(
        factory, spellings_closed, side="SELL", quantity="0.5", rehearsal=True, symbol="SOLUSDT"
    )
    closed_rehearsal = await seed_allocation(factory)
    await record_fill(factory, closed_rehearsal, side="BUY", quantity="0.5", rehearsal=True)
    await record_fill(factory, closed_rehearsal, side="SELL", quantity="0.5", rehearsal=True)

    # a disabled pool is still read
    disabled = await seed_allocation(factory, **PIONEX_COIN_M_ETH)
    await record_fill(
        factory, disabled, side="BUY", quantity="1", rehearsal=False,
        symbol="SOL_ETH", fee_currency="ETH", **PIONEX_COIN_M_ETH,
    )  # fmt: skip
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE capital_pools SET enabled = false "
                "WHERE exchange = 'pionex' AND venue = 'coin-m' AND settlement_currency = 'ETH'"
            )
        )
        await session.commit()

    # a market quoted in another currency than the pool's: the base cannot be told,
    # and the guard still counts the allocation as open
    unresolved = await seed_allocation(factory)
    await record_fill(
        factory, unresolved, side="BUY", quantity="0.5", rehearsal=False, symbol="SOLUSDC.P"
    )

    # a second pool
    coin_m = await seed_allocation(factory, **PIONEX_COIN_M_BTC)
    await record_fill(
        factory, coin_m, side="BUY", quantity="1", rehearsal=False,
        symbol="ETH_BTC", fee_currency="BTC", **PIONEX_COIN_M_BTC,
    )  # fmt: skip

    # a base-currency fee: the short one is open, the flat one is not
    short = await seed_allocation(factory, **PIONEX_SPOT)
    await record_fill(
        factory, short, side="BUY", quantity="0.002", rehearsal=False,
        symbol="BTC_USDT", fee="0.000002", fee_currency="BTC", **PIONEX_SPOT,
    )  # fmt: skip
    await record_fill(
        factory, short, side="SELL", quantity="0.002", rehearsal=False,
        symbol="BTC_USDT", **PIONEX_SPOT,
    )  # fmt: skip
    flat = await seed_allocation(factory, **PIONEX_SPOT)
    await record_fill(
        factory, flat, side="BUY", quantity="0.002", rehearsal=False,
        symbol="BTC_USDT", fee="0.000002", fee_currency="BTC", **PIONEX_SPOT,
    )  # fmt: skip
    await record_fill(
        factory, flat, side="SELL", quantity="0.001998", rehearsal=False,
        symbol="BTC_USDT", **PIONEX_SPOT,
    )  # fmt: skip

    # attempts
    _, order_live = await _seed_attempt(
        factory, status="SUBMITTED", exchange_order_id="8f0c2a3e-6a51-4c1b-9d0a-2f7c1e5b7a10"
    )
    _, order_rehearsal = await _seed_attempt(
        factory, status="SUBMITTED", exchange_order_id=f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}"
    )
    _, order_closing = await _seed_attempt(
        factory, status="SUBMITTED", exchange_order_id="1234567890123", closing=True
    )
    _, order_terminal = await _seed_attempt(
        factory, status="FILLED", exchange_order_id=f"{REHEARSAL_ORDER_ID_PREFIX}{uuid4()}"
    )
    _, order_without_id = await _seed_attempt(factory, status="SUBMITTED", exchange_order_id=None)
    _, order_without_id_closing = await _seed_attempt(
        factory, status="SUBMITTED", exchange_order_id=None, closing=True
    )

    return GuardCases(
        open_rehearsal=rehearsal.allocation_id,
        open_live=live.allocation_id,
        open_mixed=mixed.allocation_id,
        open_live_marker_in_id=marker.allocation_id,
        open_two_spellings=spellings_open.allocation_id,
        open_disabled_pool=disabled.allocation_id,
        open_coin_m_btc=coin_m.allocation_id,
        open_base_fee_short=short.allocation_id,
        open_unresolved=unresolved.allocation_id,
        closed_two_spellings=spellings_closed.allocation_id,
        closed_rehearsal=closed_rehearsal.allocation_id,
        closed_base_fee_flat=flat.allocation_id,
        leveraged_allocation=live.allocation_id,
        order_live=order_live,
        order_rehearsal=order_rehearsal,
        order_closing=order_closing,
        order_terminal=order_terminal,
        order_without_id=order_without_id,
        order_without_id_closing=order_without_id_closing,
    )
