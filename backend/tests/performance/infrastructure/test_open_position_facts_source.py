"""Integration test: ``SqlAlchemyOpenPositionFactsSource``, the statements of the
open-positions read that the mode guard's reader does not make [DB] (design
addendum "open positions", section C, steps 3 and 4; tasks.md op.1.20).

Real PostgreSQL, seeded through the real tables and the production write path of
the ledger. What hides here is what SQL does silently: a group that merges two fee
currencies of different case, a join that drops an attempt whose parent is gone,
a leverage read from the CLOSING attempt of the same reservation.

Spellings of one market, deliberately different on each side of the boundary:
the ledger holds ``STXUSDT.P`` (TradingView's) and ``STXUSDT`` (the venue's) and,
for a rehearsal, ``STXUSDT_PERP`` (Pionex's); the source answers each AS STORED.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
from strategy_manager.performance.application.ports import SubmittedOrder
from strategy_manager.performance.domain.open_position import FillAggregate, PoolLabel
from strategy_manager.performance.infrastructure.open_position_facts_source import (
    SqlAlchemyOpenPositionFactsSource,
)
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from tests.performance.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
)
from tests.performance.infrastructure.test_allocation_fills_source import (
    BYBIT,
    _fill,
    _record,
    _seed_allocation,
)

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC)
PIONEX_COIN_M_BTC = PoolKey(Exchange.PIONEX, Venue.COIN_M, Currency.BTC)
BYBIT_LABEL = PoolLabel("bybit", "usdt-m", "USDT")
PIONEX_LABEL = PoolLabel("pionex", "coin-m", "BTC")


@contextmanager
def _captured_sql(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record_statement(conn: object, cursor: object, statement: str, *rest: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record_statement)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record_statement)


@dataclass(frozen=True, slots=True)
class FactsLedger:
    strategy_a: UUID
    strategy_b: UUID
    x: UUID  # A's allocation: FILLED, 2x, several groups
    y: UUID  # B's allocation: EXPIRED reservation, no leverage, B archived
    z: UUID  # an allocation nobody asks for
    open_live: UUID
    closing_x: UUID
    parentless: UUID
    open_archived: UUID
    open_other_pool: UUID
    filled_attempt: UUID


async def _sql(factory: async_sessionmaker[AsyncSession], statement: str, **params: object) -> None:
    async with factory() as session:
        await session.execute(text(statement), params)
        await session.commit()


async def _seed_opening_attempt(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    *,
    status: str = "SUBMITTED",
    order_id: str | None = None,
    symbol: str = "STXUSDT.P",
    attempt_pool: PoolKey = BYBIT,
) -> UUID:
    """A reservation of ``strategy_id`` (in the bybit pool) with its own opening
    attempt, written in ``attempt_pool`` (which differs from the reservation's in
    one case)."""
    signal_id, reservation_id, attempt_id = uuid4(), uuid4(), uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    await seed_reservation(
        factory, reservation_id=reservation_id, strategy_id=strategy_id, signal_id=signal_id
    )
    await seed_execution_attempt(
        factory,
        attempt_id=attempt_id,
        reservation_id=reservation_id,
        exchange=attempt_pool.exchange.value,
        venue=attempt_pool.venue.value,
        settlement_currency=attempt_pool.settlement_currency.value,
        symbol=symbol,
        status=status,
        exchange_order_id=order_id,
    )
    return attempt_id


@pytest.fixture
async def ledger(pg_session_factory: async_sessionmaker[AsyncSession]) -> FactsLedger:
    factory = pg_session_factory
    strategy_a, x, x_attempt = await _seed_allocation(factory)
    strategy_b, y, y_attempt = await _seed_allocation(factory)
    _, z, z_attempt = await _seed_allocation(factory)
    await _sql(
        factory,
        "UPDATE reservations SET status = 'FILLED', amount = 121.80 WHERE id = :id",
        id=x,
    )
    await _sql(factory, "UPDATE reservations SET status = 'EXPIRED' WHERE id = :id", id=y)
    await _sql(factory, "UPDATE strategies SET archived_at = now() WHERE id = :id", id=strategy_b)
    await _sql(factory, "UPDATE execution_attempts SET leverage = 2 WHERE id = :id", id=x_attempt)
    # The opening attempts of the three allocations were filled long ago.
    for attempt in (x_attempt, y_attempt, z_attempt):
        await _sql(
            factory, "UPDATE execution_attempts SET status = 'FILLED' WHERE id = :id", id=attempt
        )

    def fill(allocation: UUID, attempt: UUID, owner: UUID, side: str, **kwargs: object) -> object:
        return _fill(
            strategy_id=owner, allocation_id=allocation, attempt_id=attempt, side=side, **kwargs
        )

    await _record(
        factory,
        fill(x, x_attempt, strategy_a, "BUY", quantity="100", price="0.45",
             symbol="STXUSDT.P", fee="0.05", fee_currency="usdt", filled_at=T0),
        fill(x, x_attempt, strategy_a, "BUY", quantity="50", price="0.50",
             symbol="STXUSDT.P", fee="0.02", fee_currency="USDT",
             filled_at=T0 + timedelta(minutes=1)),
        fill(x, x_attempt, strategy_a, "SELL", quantity="30", price="0.55",
             symbol="STXUSDT", fee="0.01", fee_currency="USDT",
             filled_at=T0 + timedelta(minutes=2)),
        fill(x, x_attempt, strategy_a, "BUY", quantity="5", price="0.45",
             symbol="STXUSDT.P", fee="0.0001", fee_currency="STX",
             filled_at=T0 + timedelta(minutes=3)),
        fill(y, y_attempt, strategy_b, "SELL", quantity="7", price="1",
             symbol="STXUSDT_PERP", fill_id=f"{REHEARSAL_FILL_ID_PREFIX}{uuid4()}", filled_at=T0),
        fill(z, z_attempt, strategy_a, "BUY", quantity="3", price="2", symbol="STXUSDT.P"),
    )

    open_live = await _seed_opening_attempt(factory, strategy_a, order_id="ORD-1")
    open_archived = await _seed_opening_attempt(factory, strategy_b, symbol="STXUSDT_PERP")
    open_other_pool = await _seed_opening_attempt(
        factory, strategy_a, order_id="ORD-5", attempt_pool=PIONEX_COIN_M_BTC
    )
    filled_attempt = await _seed_opening_attempt(factory, strategy_a, status="FILLED")
    # A closing attempt of X, its own leverage 9: the position's leverage is the
    # OPENING attempt's.
    closing_x = uuid4()
    await seed_execution_attempt(
        factory, attempt_id=closing_x, closes_allocation_id=x, symbol="STXUSDT"
    )
    await _sql(factory, "UPDATE execution_attempts SET leverage = 9 WHERE id = :id", id=closing_x)
    # An attempt with neither parent: the LEFT joins must not drop it.
    parentless = uuid4()
    await seed_execution_attempt(factory, attempt_id=parentless, symbol="STXUSDT.P")

    return FactsLedger(
        strategy_a=strategy_a,
        strategy_b=strategy_b,
        x=x,
        y=y,
        z=z,
        open_live=open_live,
        closing_x=closing_x,
        parentless=parentless,
        open_archived=open_archived,
        open_other_pool=open_other_pool,
        filled_attempt=filled_attempt,
    )


def _shape(row: SubmittedOrder) -> tuple[object, ...]:
    return (
        row.opening,
        row.pool,
        row.symbol,
        row.exchange_order_id,
        row.strategy_id,
        row.strategy_name,
        row.strategy_archived,
        row.reservation_pool,
    )


async def test_the_fills_are_grouped_by_strategy_pool_symbol_side_and_upper_cased_fee_currency(
    pg_session_factory: async_sessionmaker[AsyncSession], ledger: FactsLedger
) -> None:
    async with pg_session_factory() as session:
        facts = await SqlAlchemyOpenPositionFactsSource(session).position_facts([ledger.x])

    assert set(facts) == {ledger.x}
    first = T0
    expected = {
        FillAggregate(
            allocation_id=ledger.x, strategy_id=ledger.strategy_a, exchange="bybit",
            venue="usdt-m", settlement_currency="USDT", symbol="STXUSDT.P", side="BUY",
            fee_currency="USDT", quantity=Decimal("150"), notional=Decimal("70"),
            fee=Decimal("0.07"), first_filled_at=first, fill_count=2,
        ),
        FillAggregate(
            allocation_id=ledger.x, strategy_id=ledger.strategy_a, exchange="bybit",
            venue="usdt-m", settlement_currency="USDT", symbol="STXUSDT", side="SELL",
            fee_currency="USDT", quantity=Decimal("30"), notional=Decimal("16.5"),
            fee=Decimal("0.01"), first_filled_at=T0 + timedelta(minutes=2), fill_count=1,
        ),
        FillAggregate(
            allocation_id=ledger.x, strategy_id=ledger.strategy_a, exchange="bybit",
            venue="usdt-m", settlement_currency="USDT", symbol="STXUSDT.P", side="BUY",
            fee_currency="STX", quantity=Decimal("5"), notional=Decimal("2.25"),
            fee=Decimal("0.0001"), first_filled_at=T0 + timedelta(minutes=3), fill_count=1,
        ),
    }
    assert set(facts[ledger.x].groups) == expected
    assert len(facts[ledger.x].groups) == 3, "a group was split or repeated"


async def test_the_reservation_part_is_the_grant_the_status_the_pool_and_the_opening_leverage(
    pg_session_factory: async_sessionmaker[AsyncSession], ledger: FactsLedger
) -> None:
    async with pg_session_factory() as session:
        facts = await SqlAlchemyOpenPositionFactsSource(session).position_facts(
            [ledger.x, ledger.y]
        )

    x, y = facts[ledger.x], facts[ledger.y]
    assert (x.strategy_id, x.strategy_name, x.strategy_archived) == (
        ledger.strategy_a, f"strategy-{ledger.strategy_a}", False
    )
    assert (x.margin_granted, x.reservation_status, x.reservation_pool) == (
        Decimal("121.80"), "FILLED", BYBIT_LABEL
    )
    # The closing attempt of the same reservation carries 9: it is not read.
    assert x.leverage == Decimal("2")
    assert (y.strategy_id, y.strategy_archived, y.reservation_status) == (
        ledger.strategy_b, True, "EXPIRED"
    )
    assert y.leverage is None, "a reservation with no recorded leverage reads null, never 1"
    assert {g.symbol for g in y.groups} == {"STXUSDT_PERP"}


async def test_an_allocation_that_was_not_asked_for_is_absent(
    pg_session_factory: async_sessionmaker[AsyncSession], ledger: FactsLedger
) -> None:
    async with pg_session_factory() as session:
        source = SqlAlchemyOpenPositionFactsSource(session)
        facts = await source.position_facts([ledger.y])
        unknown = await source.position_facts([uuid4()])

    assert set(facts) == {ledger.y}
    assert unknown == {}


async def test_the_fills_and_the_reservation_are_two_statements_whatever_the_ids(
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
    ledger: FactsLedger,
) -> None:
    async with pg_session_factory() as session:
        source = SqlAlchemyOpenPositionFactsSource(session)
        with _captured_sql(pg_engine) as one:
            await source.position_facts([ledger.x])
        with _captured_sql(pg_engine) as three:
            await source.position_facts([ledger.x, ledger.y, ledger.z])

    assert (len(one), len(three)) == (2, 2)


async def test_every_submitted_attempt_is_read_whatever_its_parents(
    pg_session_factory: async_sessionmaker[AsyncSession], ledger: FactsLedger
) -> None:
    async with pg_session_factory() as session:
        rows = await SqlAlchemyOpenPositionFactsSource(session).submitted_orders()

    by_attempt = {row.attempt_id: row for row in rows}
    assert len(rows) == len(by_attempt), "an attempt was read twice"
    assert set(by_attempt) == {
        ledger.open_live,
        ledger.closing_x,
        ledger.parentless,
        ledger.open_archived,
        ledger.open_other_pool,
    }, "the FILLED attempts are not read; every SUBMITTED one is, whatever its parents"

    assert _shape(by_attempt[ledger.open_live]) == (
        True, BYBIT_LABEL, "STXUSDT.P", "ORD-1", ledger.strategy_a,
        f"strategy-{ledger.strategy_a}", False, BYBIT_LABEL,
    )
    # A closing attempt: not opening, no order id yet, the strategy of the
    # reservation it closes.
    assert _shape(by_attempt[ledger.closing_x]) == (
        False, BYBIT_LABEL, "STXUSDT", None, ledger.strategy_a,
        f"strategy-{ledger.strategy_a}", False, BYBIT_LABEL,
    )
    assert by_attempt[ledger.open_archived].strategy_archived is True
    assert by_attempt[ledger.open_archived].symbol == "STXUSDT_PERP"
    # The attempt's own pool, and the reservation's, side by side.
    other = by_attempt[ledger.open_other_pool]
    assert (other.pool, other.reservation_pool) == (PIONEX_LABEL, BYBIT_LABEL)
    # No reservation at all: every parent column is null, the row stays.
    assert _shape(by_attempt[ledger.parentless]) == (
        False, BYBIT_LABEL, "STXUSDT.P", None, None, None, None, None,
    )
    for row in rows:
        assert row.created_at.tzinfo is not None


async def test_the_submitted_orders_are_one_statement(
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
    ledger: FactsLedger,
) -> None:
    async with pg_session_factory() as session:
        source = SqlAlchemyOpenPositionFactsSource(session)
        with _captured_sql(pg_engine) as statements:
            await source.submitted_orders()

    assert len(statements) == 1


async def test_the_fills_statement_does_not_test_the_rehearsal_prefix(
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
    ledger: FactsLedger,
) -> None:
    """The origin of a position is the guard's alone (design section C)."""
    async with pg_session_factory() as session:
        with _captured_sql(pg_engine) as statements:
            await SqlAlchemyOpenPositionFactsSource(session).position_facts([ledger.x])

    for statement in statements:
        assert REHEARSAL_FILL_ID_PREFIX not in statement
        assert "exchange_fill_id" not in statement.lower()
