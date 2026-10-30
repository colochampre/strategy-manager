"""A position opened BEFORE the upgrade is closed by the first close after it
(tasks.md C.6; production may hold an open position across the deploy).

Driven the way the deploy runs: a database at ``0031``, a position seeded as the old
system left it (a reservation with no ``delivery_id`` column yet), then
``alembic upgrade head``, whose 0032 backfill gives the reservation its delivery.
After that the new code fans a close signal out and works it: the author's
subscription must be found a holder and its delivery must close THAT reservation,
with the position held in the ledger under the venue's bare spelling of the symbol.

A sync test on purpose: the 0032 helpers run their own event loop to seed.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.execution.infrastructure.exchange_registry import VenueExchangeRegistry
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.main import _build_fan_out_signal, _build_process_delivery
from strategy_manager.reconciliation.infrastructure.venue_position_reader_registry import (
    VenuePositionReaderRegistry,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.models import JobRow
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow
from tests.execution.fakes import OneRegistry
from tests.migrations.test_0032_signal_deliveries import (
    _add_attempt,
    _add_pool,
    _add_reservation,
    _add_strategy,
    _add_user,
    _alembic_ok,
    _query,
    _scalar,
    _subscribe,
)
from tests.pg_head_schema import migrated_database
from tests.signals.fakes import in_both_modes
from tests.signals.infrastructure.test_delivery_flow_integration import _Reader

pytestmark = pytest.mark.integration

_NOW = datetime.now(UTC)
# Both alerts are spelled as TradingView spells them (the transition is classified
# over one exact spelling); the ledger holds the venue's bare name.
_OPENED_AS = "STXUSDT.P"
_CLOSED_AS = "STXUSDT.P"
_LEDGER = "STXUSDT"


def _insert_signal(
    url: str, strategy_id: UUID, *, symbol: str, size: str, received: datetime
) -> UUID:
    signal_id = uuid4()
    _query(
        url,
        "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, status, action, "
        "contracts, position_size, price, symbol, signal_type, received_at, decided_at) "
        "VALUES (:id, :s, :k, '{}'::jsonb, :status, 'buy', 1, :size, 2, :symbol, 'ENTRY', :at, "
        ":decided)",
        {
            "id": signal_id,
            "s": strategy_id,
            "k": str(uuid4()),
            # A terminal signal records when it was decided
            # (ck_signals_terminal_requires_decided_at).
            "status": "PROCESSED" if size != "0" else "ACCEPTED",
            "decided": received if size != "0" else None,
            "size": Decimal(size),
            "symbol": symbol,
            "at": received,
        },
    )
    return signal_id


def test_a_position_opened_before_the_upgrade_is_closed_by_the_first_close_after_it() -> None:
    with migrated_database("strategy_manager_test_pre_upgrade_close", "0031") as url:
        owner = _add_user(url, "owner@example.com")
        pool = _add_pool(url, owner)
        strategy = _add_strategy(url, owner, "legacy")
        _query(
            url,
            "UPDATE strategies SET allowed_pairs = ARRAY['STXUSDT'] WHERE id = :s",
            {"s": strategy},
        )
        subscription = _subscribe(url, owner, strategy, pool)
        _query(
            url,
            "UPDATE subscriptions SET created_at = :at WHERE id = :id",
            {"id": subscription, "at": _NOW - timedelta(days=3)},
        )
        opening = _insert_signal(
            url, strategy, symbol=_OPENED_AS, size="1", received=_NOW - timedelta(hours=2)
        )
        reservation = _add_reservation(url, owner, pool, strategy, opening)
        _query(
            url,
            "UPDATE reservations SET status = 'FILLED', terminal_at = now() WHERE id = :id",
            {"id": reservation},
        )
        attempt = _add_attempt(url, owner, reservation_id=reservation, signal_id=opening)
        _query(
            url,
            "INSERT INTO ledger_entries (id, user_id, strategy_id, allocation_id, "
            "execution_attempt_id, exchange, venue, settlement_currency, symbol, side, "
            "quantity, price, fee, fee_currency, notional, exchange_order_id, "
            "exchange_fill_id, filled_at, usd_rate_at_fill) VALUES (:id, :u, :s, :alloc, "
            ":att, 'binance', 'usdt-m', 'USDT', :symbol, 'BUY', 5, 2, 0, 'USDT', 10, "
            ":order, :fill, :at, 1)",
            {
                "id": uuid4(),
                "u": owner,
                "s": strategy,
                "alloc": reservation,
                "att": attempt,
                "symbol": _LEDGER,
                "order": f"order-{attempt}",
                "fill": f"fill-{attempt}",
                "at": _NOW - timedelta(hours=2),
            },
        )
        closing = _insert_signal(
            url, strategy, symbol=_CLOSED_AS, size="0", received=_NOW - timedelta(minutes=1)
        )

        _alembic_ok(url, "upgrade", "head")
        # The backfill gave the position's reservation its delivery.
        backfilled = _scalar(
            url, "SELECT delivery_id FROM reservations WHERE id = :r", {"r": reservation}
        )
        assert backfilled is not None

        venue = FakeExchangeAdapter(
            exchange="binance", fill_price=Decimal("2"), fee_rate=Decimal("0")
        )
        closes = asyncio.run(_close(url, owner, closing, venue))

    assert len(closes) == 1
    assert closes[0].closes_allocation_id == reservation
    assert closes[0].user_id == owner
    assert closes[0].exchange == "binance"


async def _close(
    url: str, owner: UUID, closing: UUID, venue: FakeExchangeAdapter
) -> list[ExecutionAttemptRow]:
    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            await _build_fan_out_signal(session, get_settings()).run(closing)
        async with factory() as session:
            deliveries = (
                (
                    await session.execute(
                        select(SignalDeliveryRow).where(SignalDeliveryRow.signal_id == closing)
                    )
                )
                .scalars()
                .all()
            )
            jobs = (
                (await session.execute(select(JobRow).where(JobRow.kind == "delivery.process")))
                .scalars()
                .all()
            )
        assert [d.user_id for d in deliveries] == [owner]
        (job,) = [j for j in jobs if UUID(str(j.payload["delivery_id"])) == deliveries[0].id]
        assert job.payload["halves"] == "close"

        pools = {
            (owner, ("binance", "usdt-m", "USDT")): PoolConfig(
                exchange=Exchange("binance"),
                venue=Venue("usdt-m"),
                settlement_currency=Currency("USDT"),
                user_id=owner,
                min_order_size=Decimal("1"),
            )
        }
        async with factory() as session:
            handler, _ = _build_process_delivery(
                session,
                pools,
                get_settings(),
                VenueExchangeRegistry([venue]),
                OneRegistry(VenueExchangeRegistry([venue])),
                in_both_modes(frozenset({("binance", "usdt-m")})),
                _Reader(Decimal("1000")),  # type: ignore[arg-type]
                VenuePositionReaderRegistry([]),
            )
            await handler.handle(deliveries[0].id, job.payload["halves"])
            await session.commit()
        async with factory() as session:
            return list(
                (
                    await session.execute(
                        select(ExecutionAttemptRow).where(
                            ExecutionAttemptRow.closes_allocation_id.is_not(None)
                        )
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()
