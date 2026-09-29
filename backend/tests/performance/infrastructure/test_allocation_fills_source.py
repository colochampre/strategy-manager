"""Integration test: ``SqlAlchemyAllocationFillsSource``, the one SQL aggregate
joining ``ledger_entries`` to ``reservations`` [DB] (design.md section 11;
tasks.md 3b.4).

Real PostgreSQL, seeded through the real tables and written through
``RecordFill`` (the production write path). The aggregate is where the
mistakes hide: which rows the ``NOT LIKE`` drops, what ``GROUP BY`` merges, and
which spelling a leg was recorded under.

**Binding testing lesson**: a symbol has three spellings (TradingView
``STXUSDT.P``, venue bare ``STXUSDT``, Pionex ``STXUSDT_PERP``). The legs of
one trade below are written under different spellings.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.performance.application.ports import PoolFills
from strategy_manager.performance.domain.derive_trade import derive_trades
from strategy_manager.performance.infrastructure.allocation_fills_source import (
    SqlAlchemyAllocationFillsSource,
)
from strategy_manager.shared.domain.money import Currency, Exchange, Venue

pytestmark = pytest.mark.integration

T0 = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
BYBIT = PoolKey(Exchange.BYBIT, Venue.USDT_M, Currency.USDT)
PIONEX = PoolKey(Exchange.PIONEX, Venue.SPOT, Currency.USDT)
# Same venue AND same settlement currency as BYBIT: only the exchange differs.
BINANCE = PoolKey(Exchange.BINANCE, Venue.USDT_M, Currency.USDT)


async def _seed_allocation(
    factory: async_sessionmaker[AsyncSession],
    *,
    pool: PoolKey = BYBIT,
    pool_total_at_open: str | None = "1000",
    strategy_id: UUID | None = None,
) -> tuple[UUID, UUID, UUID]:
    """Strategy + signal + reservation (the allocation) + its opening attempt.
    Returns ``(strategy_id, allocation_id, attempt_id)``. Pass ``strategy_id``
    of an already-seeded strategy to add one more allocation to it."""
    from tests.performance.infrastructure.conftest import (
        seed_execution_attempt,
        seed_reservation,
        seed_signal,
        seed_strategy,
    )

    signal_id = uuid4()
    allocation_id, attempt_id = uuid4(), uuid4()
    if strategy_id is None:
        strategy_id = uuid4()
        await seed_strategy(
            factory,
            strategy_id=strategy_id,
            exchange=pool.exchange.value,
            venue=pool.venue.value,
            settlement_currency=pool.settlement_currency.value,
        )
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    await seed_reservation(
        factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        exchange=pool.exchange.value,
        venue=pool.venue.value,
        settlement_currency=pool.settlement_currency.value,
    )
    if pool_total_at_open is not None:
        async with factory() as session:
            await session.execute(
                text("UPDATE reservations SET pool_total_at_open = :t WHERE id = :id"),
                {"t": Decimal(pool_total_at_open), "id": allocation_id},
            )
            await session.commit()
    await seed_execution_attempt(
        factory,
        attempt_id=attempt_id,
        reservation_id=allocation_id,
        exchange=pool.exchange.value,
        venue=pool.venue.value,
        settlement_currency=pool.settlement_currency.value,
    )
    return strategy_id, allocation_id, attempt_id


def _fill(
    *,
    strategy_id: UUID,
    allocation_id: UUID,
    attempt_id: UUID,
    side: str,
    quantity: str,
    price: str = "100",
    symbol: str = "SOLUSDT.P",
    fee: str = "0",
    fee_currency: str = "USDT",
    filled_at: datetime = T0,
    fill_id: str | None = None,
    pool: PoolKey = BYBIT,
) -> FillRecord:
    return FillRecord(
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        execution_attempt_id=attempt_id,
        exchange=pool.exchange.value,
        venue=pool.venue.value,
        settlement_currency=pool.settlement_currency.value,
        symbol=symbol,
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal(fee),
        fee_currency=fee_currency,
        notional=Decimal(quantity) * Decimal(price),
        exchange_order_id=f"EX-{uuid4()}",
        exchange_fill_id=fill_id if fill_id is not None else f"F-{uuid4()}",
        filled_at=filled_at,
        usd_rate_at_fill=Decimal("1"),
    )


async def _record(factory: async_sessionmaker[AsyncSession], *fills: FillRecord) -> None:
    async with factory() as session:
        recorder = RecordFill(SqlAlchemyLedgerRepository(session))
        for fill in fills:
            await recorder.record(fill)
        await session.commit()


async def _read(
    factory: async_sessionmaker[AsyncSession], pool: PoolKey = BYBIT
) -> PoolFills:
    async with factory() as session:
        return await SqlAlchemyAllocationFillsSource(session).pool_fills(pool)


async def test_source_excludes_fake_fill_prefix_rows(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A rehearsal allocation (DRY_RUN mints ``fake-fill-`` ids) and a real
    one sit in the same pool. Only the real one is returned, and the two
    rehearsal fills are counted rather than vanishing."""
    rehearsal_strategy, rehearsal_alloc, rehearsal_attempt = await _seed_allocation(
        pg_session_factory
    )
    real_strategy, real_alloc, real_attempt = await _seed_allocation(pg_session_factory)
    await _record(
        pg_session_factory,
        _fill(
            strategy_id=rehearsal_strategy,
            allocation_id=rehearsal_alloc,
            attempt_id=rehearsal_attempt,
            side="BUY",
            quantity="1",
            price="1",
            fill_id=f"{REHEARSAL_FILL_ID_PREFIX}{uuid4()}",
        ),
        _fill(
            strategy_id=rehearsal_strategy,
            allocation_id=rehearsal_alloc,
            attempt_id=rehearsal_attempt,
            side="SELL",
            quantity="1",
            price="1",
            fill_id=f"{REHEARSAL_FILL_ID_PREFIX}{uuid4()}",
        ),
        _fill(
            strategy_id=real_strategy,
            allocation_id=real_alloc,
            attempt_id=real_attempt,
            side="BUY",
            quantity="1",
            fill_id=str(uuid4()),
        ),
    )

    result = await _read(pg_session_factory)

    assert [g.allocation_id for g in result.groups] == [real_alloc]
    assert result.rehearsal_fill_count == 2


async def test_a_fill_id_merely_containing_the_prefix_is_not_a_rehearsal_fill(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The exclusion is a PREFIX match. A real id that merely CONTAINS
    ``fake-fill-`` further in is a real fill."""
    strategy_id, alloc, attempt = await _seed_allocation(pg_session_factory)
    await _record(
        pg_session_factory,
        _fill(
            strategy_id=strategy_id,
            allocation_id=alloc,
            attempt_id=attempt,
            side="BUY",
            quantity="3",
            fill_id=f"real-{REHEARSAL_FILL_ID_PREFIX}1",
        ),
    )

    result = await _read(pg_session_factory)

    assert len(result.groups) == 1
    assert result.groups[0].quantity == Decimal("3")
    assert result.rehearsal_fill_count == 0


async def test_source_groups_by_allocation_strategy_side_fee_currency(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Four fills of one allocation: two BUYs with USDT fees (merged into one
    group), a BUY with a BNB fee (its own group) and a SELL (its own). The
    open is spelled ``SOLUSDT.P`` and the close ``SOLUSDT``: the groups keep
    their own spelling, and folding them by allocation merges the pair."""
    strategy_id, alloc, attempt = await _seed_allocation(pg_session_factory)
    common = {"strategy_id": strategy_id, "allocation_id": alloc, "attempt_id": attempt}
    await _record(
        pg_session_factory,
        _fill(
            **common,
            side="BUY",
            quantity="1",
            price="100",
            fee="0.25",
            filled_at=T0,
        ),
        _fill(
            **common,
            side="BUY",
            quantity="2",
            price="101",
            fee="0.5",
            filled_at=T0 + timedelta(minutes=1),
        ),
        _fill(
            **common,
            side="BUY",
            quantity="1",
            price="102",
            fee="0.004",
            fee_currency="BNB",
            filled_at=T0 + timedelta(minutes=2),
        ),
        _fill(
            **common,
            side="SELL",
            quantity="4",
            price="110",
            symbol="SOLUSDT",
            fee="1",
            filled_at=T0 + timedelta(hours=1),
        ),
    )

    result = await _read(pg_session_factory)

    by_key = {(g.side, g.fee_currency): g for g in result.groups}
    assert set(by_key) == {("BUY", "USDT"), ("BUY", "BNB"), ("SELL", "USDT")}
    merged = by_key[("BUY", "USDT")]
    assert merged.quantity == Decimal("3")
    assert merged.notional == Decimal("302")
    assert merged.fee == Decimal("0.75")
    assert merged.first_filled_at == T0
    assert merged.last_filled_at == T0 + timedelta(minutes=1)
    assert by_key[("BUY", "BNB")].fee == Decimal("0.004")
    assert by_key[("SELL", "USDT")].symbol == "SOLUSDT"
    assert {g.strategy_id for g in result.groups} == {strategy_id}

    derived = derive_trades(result.groups)

    assert [t.pair for t in derived.closed] == ["SOLUSDT"]
    assert derived.closed[0].fees_complete is False
    # sold 440, bought 100 + 202 + 102 = 404; USDT fees 0.75 + 1
    assert derived.closed[0].pnl == Decimal("34.25")
    assert derived.closed[0].closed_at == T0 + timedelta(hours=1)


async def test_source_reads_pool_total_at_open_from_reservation_join(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Each allocation carries the capital ITS reservation recorded, and a
    pre-0026 reservation (NULL) comes through as ``None``, not as zero and not
    as a neighbour's value."""
    s1, a1, t1 = await _seed_allocation(pg_session_factory, pool_total_at_open="1000")
    s2, a2, t2 = await _seed_allocation(pg_session_factory, pool_total_at_open="1030.5")
    s3, a3, t3 = await _seed_allocation(pg_session_factory, pool_total_at_open=None)
    await _record(
        pg_session_factory,
        _fill(strategy_id=s1, allocation_id=a1, attempt_id=t1, side="BUY", quantity="1"),
        _fill(strategy_id=s2, allocation_id=a2, attempt_id=t2, side="BUY", quantity="1"),
        _fill(strategy_id=s3, allocation_id=a3, attempt_id=t3, side="BUY", quantity="1"),
    )

    result = await _read(pg_session_factory)

    totals = {g.allocation_id: g.pool_total_at_open for g in result.groups}
    assert totals == {a1: Decimal("1000"), a2: Decimal("1030.5"), a3: None}


async def test_source_returns_only_the_requested_pool(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Rule 7. Three pools that all settle in USDT: two on different venues, and
    a third that shares the venue AND the currency with the first and differs
    only by exchange. The read for one never sees another's fills, and its
    group carries its own pool identity."""
    bybit_strategy, bybit_alloc, bybit_attempt = await _seed_allocation(
        pg_session_factory, pool=BYBIT
    )
    pionex_strategy, pionex_alloc, pionex_attempt = await _seed_allocation(
        pg_session_factory, pool=PIONEX
    )
    await _record(
        pg_session_factory,
        _fill(
            strategy_id=bybit_strategy,
            allocation_id=bybit_alloc,
            attempt_id=bybit_attempt,
            side="BUY",
            quantity="1",
            pool=BYBIT,
        ),
        _fill(
            strategy_id=pionex_strategy,
            allocation_id=pionex_alloc,
            attempt_id=pionex_attempt,
            side="BUY",
            quantity="1",
            symbol="SOL_USDT",
            pool=PIONEX,
        ),
    )

    async with pg_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO capital_pools "
                "(exchange, venue, settlement_currency, min_order_size) "
                "VALUES ('binance', 'usdt-m', 'USDT', 5)"
            )
        )
        await session.commit()
    binance_strategy, binance_alloc, binance_attempt = await _seed_allocation(
        pg_session_factory, pool=BINANCE
    )
    await _record(
        pg_session_factory,
        _fill(
            strategy_id=binance_strategy,
            allocation_id=binance_alloc,
            attempt_id=binance_attempt,
            side="BUY",
            quantity="1",
            pool=BINANCE,
        ),
    )

    bybit = await _read(pg_session_factory, BYBIT)
    pionex = await _read(pg_session_factory, PIONEX)
    binance = await _read(pg_session_factory, BINANCE)

    assert [(g.allocation_id, g.exchange, g.venue) for g in bybit.groups] == [
        (bybit_alloc, "bybit", "usdt-m")
    ]
    assert [(g.allocation_id, g.exchange, g.venue) for g in pionex.groups] == [
        (pionex_alloc, "pionex", "spot")
    ]
    assert [(g.allocation_id, g.exchange) for g in binance.groups] == [
        (binance_alloc, "binance")
    ]


async def test_an_empty_pool_reads_as_no_groups_and_no_error(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    result = await _read(pg_session_factory)

    assert result.groups == ()
    assert result.rehearsal_fill_count == 0


async def test_source_counts_rehearsal_fills_per_strategy(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A strategy's report states ITS rehearsal fills, not the pool's: two
    strategies leave 2 and 1 rehearsal fills, and the pool total stays their
    sum. A live fill of either is not counted."""
    s1, a1, t1 = await _seed_allocation(pg_session_factory)
    s2, a2, t2 = await _seed_allocation(pg_session_factory)

    def rehearsal(strategy: UUID, alloc: UUID, attempt: UUID, side: str) -> FillRecord:
        return _fill(
            strategy_id=strategy,
            allocation_id=alloc,
            attempt_id=attempt,
            side=side,
            quantity="1",
            fill_id=f"{REHEARSAL_FILL_ID_PREFIX}{uuid4()}",
        )

    await _record(
        pg_session_factory,
        rehearsal(s1, a1, t1, "BUY"),
        rehearsal(s1, a1, t1, "SELL"),
        rehearsal(s2, a2, t2, "BUY"),
        _fill(strategy_id=s2, allocation_id=a2, attempt_id=t2, side="SELL", quantity="1"),
    )

    result = await _read(pg_session_factory)

    assert result.rehearsal_fill_count == 3
    assert result.rehearsal_for(s1) == 2
    assert result.rehearsal_for(s2) == 1
    assert result.rehearsal_for(uuid4()) == 0
