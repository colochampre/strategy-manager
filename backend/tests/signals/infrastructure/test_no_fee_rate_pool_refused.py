"""Decision 45 on real PostgreSQL, through the production composition root: an
exchange with no simulated taker fee rate is not served in dry run (spec:
trade-execution § "An Exchange With No Simulated Fee Rate Is Not Served In Dry
Run"; design § E, test 14).

``main.build_worker_runner`` and ``run_once`` are the real thing (the pattern of
``test_exhausted_jobs_wiring``). ``DRY_RUN`` is on and no credential exists
(rule 1): the on-demand balance refresh finds no key, fails, and falls back to
the young snapshot a test seeds, which is what the design's end-to-end test
needs too.

The helpers at the top are shared by the other worker-driven tests of this unit.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager import main
from strategy_manager.accounts.application.ports import PoolBalanceReading
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.balance_snapshot_repository import (
    SqlAlchemyBalanceSnapshotRepository,
)
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.signals.infrastructure.models import SignalRow
from tests.signals.infrastructure.conftest import seed_strategy

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]

POOL_BALANCE = Decimal("1000")
TRADINGVIEW_SYMBOL = "STXUSDT.P"
PAIR = "STXUSDT"


def pool_config(exchange: Exchange, venue: Venue) -> PoolConfig:
    return PoolConfig(
        exchange=exchange,
        venue=venue,
        settlement_currency=Currency.USDT,
        min_order_size=Decimal("5"),
    )


BYBIT_POOL = pool_config(Exchange.BYBIT, Venue.USDT_M)
BINANCE_POOL = pool_config(Exchange.BINANCE, Venue.USDT_M)
PIONEX_POOL = pool_config(Exchange.PIONEX, Venue.SPOT)


async def seed_pool(factory: Factory, pool: PoolConfig) -> None:
    """A capital pool row and a balance snapshot young enough for the refresh's
    fallback (no credential exists, so the on-demand read fails)."""
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO capital_pools (exchange, venue, settlement_currency, min_order_size)"
                " VALUES (:exchange, :venue, 'USDT', 5) ON CONFLICT DO NOTHING"
            ),
            {"exchange": pool.exchange.value, "venue": pool.venue.value},
        )
        await SqlAlchemyBalanceSnapshotRepository(session).upsert(
            [
                PoolBalanceReading(
                    exchange=pool.exchange.value,
                    venue=pool.venue.value,
                    settlement_currency="USDT",
                    total=POOL_BALANCE,
                    available=POOL_BALANCE,
                    observed_at=datetime.now(UTC),
                )
            ]
        )
        await session.commit()


async def seed_open_signal(
    factory: Factory, strategy_id: UUID, *, price: Decimal, symbol: str = TRADINGVIEW_SYMBOL
) -> UUID:
    """An opening signal and its ``signal.process`` job."""
    signal_id = uuid4()
    async with factory() as session:
        session.add(
            SignalRow(
                id=signal_id,
                strategy_id=strategy_id,
                idempotency_key=f"open-{signal_id}",
                raw_payload={},
                action="buy",
                contracts=Decimal("1"),
                position_size=Decimal("1"),
                price=price,
                symbol=symbol,
                signal_type=str(strategy_id),
            )
        )
        await session.flush()
        await PostgresJobQueue(session).enqueue(
            Job(kind=JobKind.SIGNAL_PROCESS, payload={"signal_id": str(signal_id)})
        )
        await session.commit()
    return signal_id


async def seed_strategy_on(factory: Factory, pool: PoolConfig) -> UUID:
    strategy_id = uuid4()
    await seed_strategy(
        factory,
        strategy_id=strategy_id,
        exchange=pool.exchange.value,
        venue=pool.venue.value,
        allowed_pairs=frozenset({PAIR}),
    )
    return strategy_id


def use_dry_run(monkeypatch: pytest.MonkeyPatch, pg_engine: AsyncEngine) -> None:
    monkeypatch.setattr(main, "engine", pg_engine)
    monkeypatch.setattr(get_settings(), "dry_run", True)


async def count(factory: Factory, model: type) -> int:
    async with factory() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def signal_row(factory: Factory, signal_id: UUID) -> SignalRow:
    async with factory() as session:
        return (
            await session.execute(select(SignalRow).where(SignalRow.id == signal_id))
        ).scalar_one()


async def test_a_signal_on_a_pool_of_an_exchange_without_a_rate_ends_rejected_untradable_pool_with_no_reservation_and_no_ledger_row(  # noqa: E501
    pg_engine: AsyncEngine,
    pg_session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    use_dry_run(monkeypatch, pg_engine)
    await seed_pool(pg_session_factory, PIONEX_POOL)
    strategy_id = await seed_strategy_on(pg_session_factory, PIONEX_POOL)
    signal_id = await seed_open_signal(pg_session_factory, strategy_id, price=Decimal("0.4512"))
    runner = main.build_worker_runner(
        [PIONEX_POOL], session_factory_override=pg_session_factory
    )
    caplog.set_level(logging.WARNING)

    assert await runner.run_once() is True

    signal = await signal_row(pg_session_factory, signal_id)
    assert (signal.status, signal.outcome_reason) == ("REJECTED", "UNTRADABLE_POOL")
    assert await count(pg_session_factory, ReservationRow) == 0
    assert await count(pg_session_factory, ExecutionAttemptRow) == 0
    assert await count(pg_session_factory, LedgerEntryRow) == 0
    refusals = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.getMessage().startswith("refusing signal for ")
    ]
    assert len(refusals) == 1
    assert "STXUSDT.P" in refusals[0].getMessage()
    assert "pionex/spot" in refusals[0].getMessage()
    assert str(strategy_id) in refusals[0].getMessage()


async def test_the_same_worker_still_fills_a_bybit_signal_and_a_binance_signal_each_on_its_own_simulated_exchange(  # noqa: E501
    pg_engine: AsyncEngine,
    pg_session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_dry_run(monkeypatch, pg_engine)
    built: list[FakeExchangeAdapter] = []

    class SpyFakeExchange(FakeExchangeAdapter):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            built.append(self)

    monkeypatch.setattr(main, "FakeExchangeAdapter", SpyFakeExchange)
    for pool in (BYBIT_POOL, BINANCE_POOL, PIONEX_POOL):
        await seed_pool(pg_session_factory, pool)
    bybit_strategy = await seed_strategy_on(pg_session_factory, BYBIT_POOL)
    binance_strategy = await seed_strategy_on(pg_session_factory, BINANCE_POOL)
    await seed_open_signal(pg_session_factory, bybit_strategy, price=Decimal("0.4512"))
    await seed_open_signal(pg_session_factory, binance_strategy, price=Decimal("0.4633"))
    runner = main.build_worker_runner(
        [BYBIT_POOL, BINANCE_POOL, PIONEX_POOL], session_factory_override=pg_session_factory
    )

    assert await runner.run_once() is True
    assert await runner.run_once() is True

    async with pg_session_factory() as session:
        attempts = list((await session.execute(select(ExecutionAttemptRow))).scalars())
    assert sorted(attempt.exchange for attempt in attempts) == ["binance", "bybit"]
    by_exchange = {fake.exchange: fake for fake in built}
    assert sorted(by_exchange) == ["binance", "bybit"]  # no simulated exchange for pionex
    for attempt in attempts:
        assert attempt.exchange_order_id is not None
        assert attempt.exchange_order_id.startswith("fake-order-")
        own = by_exchange[attempt.exchange]
        other = by_exchange["binance" if attempt.exchange == "bybit" else "bybit"]
        assert attempt.client_order_id in own._placed
        assert attempt.client_order_id not in other._placed
