"""Decision 45, from the webhook to the ledger, through the production
composition root (design § K, tests 2 to 5 and 16; spec: trade-execution).

A POST to ``/webhook/tradingview`` stores the alert; the worker built by
``main.build_worker_runner`` runs ``signal.process`` and ``execution.settle``
through ``run_once``, on real PostgreSQL (ORM schema) with ``DRY_RUN`` on and no
credential (rule 1). The on-demand balance refresh finds no key, fails, and falls
back to the young snapshot the fixture seeds -- the path the design read from the
code and never ran; this file is where it is first proven.

Three spellings of one market cross the boundary on purpose: the alert says
``STXUSDT.P``, the strategy allows ``STXUSDT``, and a ledger row is asserted
through ``market_key(symbol) == "STXUSDT"``, never by comparing two spellings as
text.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager import main
from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.db_balance_source import DbBalanceSource
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.ledger.application.read_held_base import ReadHeldBase
from strategy_manager.ledger.application.read_symbol_positions import ReadSymbolPositions
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.derive_trade import derive_trade
from strategy_manager.performance.infrastructure.allocation_fills_source import (
    SqlAlchemyAllocationFillsSource,
)
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.signals.infrastructure.models import SignalRow
from tests.signals.infrastructure.test_no_fee_rate_pool_refused import (
    BINANCE_POOL,
    BYBIT_POOL,
    POOL_BALANCE,
    TRADINGVIEW_SYMBOL,
    seed_pool,
    seed_strategy_on,
)

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]

ALLOWED_IP = "52.89.214.238"
SECRET = "test-webhook-secret-9q"
FAKE_EXCHANGE_LOGGER = "strategy_manager.execution.infrastructure.fake_exchange"

OPEN_PRICE = "0.4512"
CLOSE_PRICE = "0.4633"
# 56.4% of the 1000 USDT snapshot: the granted capital of the design's figures.
ALLOCATION_PERCENT = Decimal("56.4")
BYBIT_RATE = Decimal("0.00055")
BINANCE_RATE = Decimal("0.0005")


@dataclass
class Stack:
    client: AsyncClient
    factory: Factory
    runner: object
    strategies: dict[str, UUID]
    sequence: int = 0

    async def alert(
        self,
        pool: PoolConfig,
        *,
        action: str,
        position_size: str,
        price: str,
    ) -> UUID:
        """POSTs one TradingView alert for the pool's strategy and returns the id
        of the signal the webhook stored."""
        self.sequence += 1
        body = {
            "data": {"action": action, "contracts": "10", "position_size": position_size},
            "price": price,
            "signal_param": "{}",
            "signal_type": str(self.strategies[pool.exchange.value]),
            "symbol": TRADINGVIEW_SYMBOL,
            "time": f"2026-10-04T10:{self.sequence:02d}:00Z",
        }
        response = await self.client.post(
            "/webhook/tradingview", params={"secret": SECRET}, json=body
        )
        assert response.status_code == 200, response.text
        return UUID(response.json()["signal_id"])

    async def drain(self) -> None:
        """Runs every job that is due, in order, until none is."""
        for _ in range(50):
            if not await self.runner.run_once():  # type: ignore[attr-defined]
                return
        raise AssertionError("the worker never ran out of due jobs")


@pytest.fixture
async def stack(
    pg_engine: AsyncEngine, pg_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Stack]:
    settings = get_settings()
    monkeypatch.setattr(settings, "dry_run", True)
    monkeypatch.setattr(settings, "webhook_secret", SECRET)
    monkeypatch.setattr(settings, "execution_settle_delay_seconds", 0.0)
    monkeypatch.setattr(main, "engine", pg_engine)

    strategies: dict[str, UUID] = {}
    for pool in (BYBIT_POOL, BINANCE_POOL):
        await seed_pool(pg_session_factory, pool)
        strategy_id = await seed_strategy_on(pg_session_factory, pool)
        async with pg_session_factory() as session:
            await session.execute(
                text("UPDATE strategies SET allocation_percent = :pct WHERE id = :id"),
                {"pct": ALLOCATION_PERCENT, "id": strategy_id},
            )
            await session.commit()
        strategies[pool.exchange.value] = strategy_id

    runner = main.build_worker_runner(
        [BYBIT_POOL, BINANCE_POOL], session_factory_override=pg_session_factory
    )

    app = main.create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    transport = ASGITransport(app=app, client=(ALLOWED_IP, 12345))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield Stack(client, pg_session_factory, runner, strategies)


async def _rows(factory: Factory, strategy_id: UUID) -> list[LedgerEntryRow]:
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(LedgerEntryRow)
                    .where(LedgerEntryRow.strategy_id == strategy_id)
                    .order_by(LedgerEntryRow.filled_at, LedgerEntryRow.created_at)
                )
            ).scalars()
        )


async def _signal_price(factory: Factory, signal_id: UUID) -> Decimal:
    async with factory() as session:
        return (
            await session.execute(select(SignalRow.price).where(SignalRow.id == signal_id))
        ).scalar_one()


async def _signal_of_allocation(factory: Factory, allocation_id: UUID) -> UUID:
    """The signal the allocation's reservation names."""
    async with factory() as session:
        return (
            await session.execute(
                select(ReservationRow.signal_id).where(ReservationRow.id == allocation_id)
            )
        ).scalar_one()


async def _round_trip(
    stack: Stack,
    pool: PoolConfig = BYBIT_POOL,
    *,
    open_price: str = OPEN_PRICE,
    close_price: str = CLOSE_PRICE,
) -> tuple[UUID, UUID, list[LedgerEntryRow]]:
    """Opens at one alert and closes at another. Returns the opening signal, the
    closing signal and the two ledger rows."""
    strategy_id = stack.strategies[pool.exchange.value]
    opening = await stack.alert(pool, action="buy", position_size="10", price=open_price)
    await stack.drain()
    closing = await stack.alert(pool, action="sell", position_size="0", price=close_price)
    await stack.drain()
    rows = await _rows(stack.factory, strategy_id)
    assert len(rows) == 2
    return opening, closing, rows


def _fee(quantity: Decimal, price: Decimal, rate: Decimal) -> Decimal:
    return (quantity * price * rate).quantize(Decimal("1e-18"))


async def test_the_opening_row_is_priced_at_the_stored_alert_price_exactly(
    stack: Stack,
) -> None:
    """A 19-place alert price is rounded to 18 ONCE, by the column at ingress;
    every later step carries that stored value."""
    strategy_id = stack.strategies["bybit"]
    signal_id = await stack.alert(
        BYBIT_POOL, action="buy", position_size="10", price="0.1234567890123456789"
    )
    await stack.drain()

    [row] = await _rows(stack.factory, strategy_id)
    stored = await _signal_price(stack.factory, signal_id)
    assert stored == Decimal("0.123456789012345679")
    assert await _signal_of_allocation(stack.factory, row.allocation_id) == signal_id
    assert row.price == stored == Decimal("0.123456789012345679")
    assert str(row.price) == "0.123456789012345679"
    assert market_key(row.symbol) == "STXUSDT"
    assert row.exchange_fill_id.startswith("fake-fill-")
    assert row.exchange_order_id.startswith("fake-order-")
    async with stack.factory() as session:
        [attempt] = (await session.execute(select(ExecutionAttemptRow))).scalars()
    assert attempt.exchange_order_id is not None
    assert attempt.exchange_order_id.startswith("fake-order-")


async def test_the_opening_row_carries_the_taker_fee_in_usdt(
    stack: Stack, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=FAKE_EXCHANGE_LOGGER)
    strategy_id = stack.strategies["bybit"]
    await stack.alert(BYBIT_POOL, action="buy", position_size="10", price=OPEN_PRICE)
    await stack.drain()

    [row] = await _rows(stack.factory, strategy_id)
    assert row.fee_currency == "USDT"
    assert row.fee > 0
    # quantity x price x 0.00055, quantised to 18 places. The stored quantity is
    # itself rounded to 18 places, so the recomputed fee can differ by 1e-18.
    assert abs(row.fee - _fee(row.quantity, row.price, BYBIT_RATE)) <= Decimal("1e-18")
    # The same fee is in the one INFO line the fill logged (Requirement 11).
    [line] = [r for r in caplog.records if r.name == FAKE_EXCHANGE_LOGGER]
    assert line.levelno == logging.INFO
    assert "bybit" in line.getMessage() and "STXUSDT.P" in line.getMessage()
    assert Decimal(str(line.args[5])) == row.fee  # type: ignore[index]


async def test_a_closing_alert_at_another_price_is_filled_at_that_alert_and_the_allocation_nets_to_zero(  # noqa: E501
    stack: Stack,
) -> None:
    _, closing, rows = await _round_trip(stack)

    opened, closed = rows
    assert opened.price == Decimal(OPEN_PRICE)
    assert closed.price == await _signal_price(stack.factory, closing) == Decimal(CLOSE_PRICE)
    assert closed.allocation_id == opened.allocation_id
    assert closed.fee_currency == "USDT"
    async with stack.factory() as session:
        net = await ReadHeldBase(SqlAlchemyLedgerRepository(session)).net_base(
            opened.allocation_id, "STX"
        )
    assert net == Decimal("0")


def _group(row: LedgerEntryRow, pool: PoolConfig) -> FillGroup:
    return FillGroup(
        allocation_id=row.allocation_id,
        strategy_id=row.strategy_id,
        exchange=row.exchange,
        venue=row.venue,
        settlement_currency=row.settlement_currency,
        symbol=row.symbol,
        side=row.side,
        fee_currency=row.fee_currency,
        quantity=row.quantity,
        notional=row.notional,
        fee=row.fee,
        first_filled_at=row.filled_at,
        last_filled_at=row.filled_at,
        pool_total_at_open=POOL_BALANCE,
    )


async def test_derive_trade_over_the_two_rows_is_complete_and_net_of_both_fees(
    stack: Stack,
) -> None:
    _, _, rows = await _round_trip(stack)

    opened, closed = rows
    assert opened.quantity == Decimal("1250")
    assert opened.notional == Decimal("564")
    assert opened.fee == Decimal("0.3102")
    assert closed.notional == Decimal("579.125")
    assert closed.fee == Decimal("0.31851875")
    trade = derive_trade([_group(opened, BYBIT_POOL), _group(closed, BYBIT_POOL)])
    assert trade is not None
    assert trade.fees_complete is True
    assert opened.fee + closed.fee == Decimal("0.62871875")
    assert trade.pnl == Decimal("14.49628125")  # 579.125 - 564 - 0.62871875


async def test_a_binance_pool_is_charged_0_0005_on_both_sides(stack: Stack) -> None:
    _, _, rows = await _round_trip(stack, BINANCE_POOL)

    opened, closed = rows
    assert (opened.exchange, closed.exchange) == ("binance", "binance")
    assert opened.fee == Decimal("0.282")
    assert closed.fee == Decimal("0.2895625")
    assert opened.fee_currency == closed.fee_currency == "USDT"


async def test_a_usdt_fee_moves_no_holding(stack: Stack) -> None:
    pool = (BYBIT_POOL.exchange.value, BYBIT_POOL.venue.value, "USDT")
    strategy_id = stack.strategies["bybit"]
    await stack.alert(BYBIT_POOL, action="buy", position_size="10", price=OPEN_PRICE)
    await stack.drain()
    [opened] = await _rows(stack.factory, strategy_id)

    async def holdings() -> tuple[Decimal, Decimal]:
        async with stack.factory() as session:
            allocation = await ReadHeldBase(SqlAlchemyLedgerRepository(session)).net_base(
                opened.allocation_id, "STX"
            )
            positions = await ReadSymbolPositions(
                SqlAlchemyLedgerRepository(session)
            ).net_positions_by_symbol(pool)
        # A fully closed allocation vanishes from the pool-wide read (it HAVING-drops
        # a net of exactly zero), so "flat" is the empty list.
        assert {market_key(position.symbol) for position in positions} <= {"STXUSDT"}
        return allocation, sum((position.net_base for position in positions), Decimal("0"))

    # After the open, with a non-zero fee in USDT on the row.
    assert opened.fee > 0
    assert await holdings() == (opened.quantity, opened.quantity)

    await stack.alert(BYBIT_POOL, action="sell", position_size="0", price=CLOSE_PRICE)
    await stack.drain()
    assert await holdings() == (Decimal("0"), Decimal("0"))


async def test_a_profitable_round_trip_moves_no_availability(stack: Stack) -> None:
    await _round_trip(stack)

    async with stack.factory() as session:
        funds = await PoolBalanceAdapter(
            {("bybit", "usdt-m", "USDT"): BYBIT_POOL},
            DbBalanceSource(session, SystemClock(), max_age_seconds=90.0),
        ).read("bybit", "usdt-m", "USDT")
        reservations = list((await session.execute(select(ReservationRow))).scalars())
    assert (funds.total, funds.available) == (POOL_BALANCE, POOL_BALANCE)
    # One reservation, the one the opening alert took: 564, FILLED. No price and
    # no fee created or changed any other.
    [reservation] = [r for r in reservations if r.exchange == "bybit"]
    assert reservation.amount == Decimal("564")
    assert reservation.status == "FILLED"


async def test_no_performance_total_counts_the_rehearsal_operation(stack: Stack) -> None:
    await _round_trip(stack)

    async with stack.factory() as session:
        fills = await SqlAlchemyAllocationFillsSource(session).pool_fills(
            PoolKey(Exchange.BYBIT, Venue.USDT_M, Currency.USDT)
        )
    assert fills.groups == ()
    assert fills.rehearsal_fill_count == 2
    assert fills.rehearsal_by_strategy == ((stack.strategies["bybit"], 2),)
