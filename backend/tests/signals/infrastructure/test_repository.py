"""Integration test against a real PostgreSQL database (strategy_manager_test).

Covers spec: signal-ingress § Idempotent Signal Persistence — the DB-level
guarantee that ``ON CONFLICT DO NOTHING`` produces no second row. Also covers
spec: job-queue § Continuation Abandonment's "a newer signal has arrived"
case (design.md § S5, ``has_newer``).
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.signals.domain.signal import IdempotencyKey, WebhookSignal
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository

pytestmark = pytest.mark.integration


def _signal(
    strategy_id: object, idempotency_key: str, *, symbol: str = "BTCUSDT"
) -> WebhookSignal:
    return WebhookSignal(
        strategy_id=strategy_id,  # type: ignore[arg-type]
        idempotency_key=IdempotencyKey(idempotency_key),
        action="buy",
        contracts=Decimal("10"),
        position_size=Decimal("10"),
        price=Decimal("50000.5"),
        symbol=symbol,
        signal_type="a6a28229-9286-463f-99e8-5f48eb597d19",
        raw_payload={"symbol": symbol},
    )


async def _insert_committed(
    session_factory: async_sessionmaker[AsyncSession], signal: WebhookSignal
) -> None:
    async with session_factory() as session:
        await SqlAlchemySignalRepository(session).insert_or_get(signal)
        await session.commit()


async def test_on_conflict_do_nothing_insert_produces_no_second_row_on_duplicate_key(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    key = "k" * 20

    async with pg_session_factory() as session:
        repository = SqlAlchemySignalRepository(session)
        first = await repository.insert_or_get(_signal(strategy_id, key))
        await session.commit()

    async with pg_session_factory() as session:
        repository = SqlAlchemySignalRepository(session)
        second = await repository.insert_or_get(_signal(strategy_id, key))
        await session.commit()

    assert first.inserted is True
    assert second.inserted is False
    assert second.signal_id == first.signal_id

    async with pg_session_factory() as session:
        count = await session.execute(
            select(func.count())
            .select_from(SignalRow)
            .where(SignalRow.strategy_id == strategy_id, SignalRow.idempotency_key == key)
        )
        assert count.scalar_one() == 1


async def _seed_signal_row(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    strategy_id: object,
    symbol: str,
    received_at: datetime,
) -> None:
    """Inserts a ``SignalRow`` with an explicit ``received_at`` -- the
    repository's own ``insert_or_get`` never takes one (the DB assigns it via
    ``server_default``), so ``has_newer``'s ordering tests need this direct
    path for a deterministic boundary instead of racing the wall clock."""

    async with session_factory() as session:
        session.add(
            SignalRow(
                strategy_id=strategy_id,
                idempotency_key=f"k-{uuid4()}",
                raw_payload={"symbol": symbol},
                received_at=received_at,
                action="buy",
                contracts=Decimal("1"),
                position_size=Decimal("1"),
                price=Decimal("1"),
                symbol=symbol,
                signal_type=str(strategy_id),
            )
        )
        await session.commit()


T0 = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)


async def test_has_newer_true_for_a_later_signal_on_the_same_strategy_and_symbol(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await _seed_signal_row(
        pg_session_factory, strategy_id=strategy_id, symbol="ETHUSDT", received_at=T0
    )
    await _seed_signal_row(
        pg_session_factory,
        strategy_id=strategy_id,
        symbol="ETHUSDT",
        received_at=T0 + timedelta(minutes=1),
    )

    async with pg_session_factory() as session:
        found = await SqlAlchemySignalRepository(session).has_newer(strategy_id, "ETHUSDT", T0)

    assert found is True


async def test_has_newer_matches_a_newer_signal_recorded_under_a_different_spelling(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Binding testing lesson (S2a): a symbol has three spellings
    (``STXUSDT.P`` TradingView, ``STXUSDT`` venue, ``STXUSDT_PERP`` Pionex).
    Insert under one, query under another, or the test proves nothing."""

    strategy_id = uuid4()
    await _seed_signal_row(
        pg_session_factory, strategy_id=strategy_id, symbol="STXUSDT", received_at=T0
    )
    await _seed_signal_row(
        pg_session_factory,
        strategy_id=strategy_id,
        symbol="STXUSDT_PERP",
        received_at=T0 + timedelta(minutes=1),
    )

    async with pg_session_factory() as session:
        found = await SqlAlchemySignalRepository(session).has_newer(strategy_id, "STXUSDT.P", T0)

    assert found is True


async def test_has_newer_false_for_a_newer_signal_on_a_different_symbol(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    await _seed_signal_row(
        pg_session_factory, strategy_id=strategy_id, symbol="ETHUSDT", received_at=T0
    )
    await _seed_signal_row(
        pg_session_factory,
        strategy_id=strategy_id,
        symbol="SOLUSDT",
        received_at=T0 + timedelta(minutes=1),
    )

    async with pg_session_factory() as session:
        found = await SqlAlchemySignalRepository(session).has_newer(strategy_id, "ETHUSDT", T0)

    assert found is False


async def test_has_newer_false_for_another_strategys_newer_signal(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    other_strategy_id = uuid4()
    await _seed_signal_row(
        pg_session_factory, strategy_id=strategy_id, symbol="ETHUSDT", received_at=T0
    )
    await _seed_signal_row(
        pg_session_factory,
        strategy_id=other_strategy_id,
        symbol="ETHUSDT",
        received_at=T0 + timedelta(minutes=1),
    )

    async with pg_session_factory() as session:
        found = await SqlAlchemySignalRepository(session).has_newer(strategy_id, "ETHUSDT", T0)

    assert found is False


async def test_has_newer_false_for_an_equal_timestamp(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Strictly newer, not ``>=`` (owner decision, this unit): a signal
    recorded at the exact same instant as the one already being processed
    carries no new information, so it must not abandon the continuation."""

    strategy_id = uuid4()
    await _seed_signal_row(
        pg_session_factory, strategy_id=strategy_id, symbol="ETHUSDT", received_at=T0
    )

    async with pg_session_factory() as session:
        found = await SqlAlchemySignalRepository(session).has_newer(strategy_id, "ETHUSDT", T0)

    assert found is False
