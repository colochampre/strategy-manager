"""``DeleteStrategy`` against real PostgreSQL migrated to ``head`` (design.md
addendum 9x, § A, § C, § D; tasks.md 9xc.4).

Runs on a database built with ``alembic upgrade head``, not on the ORM-built test
schema: ``fk_signals_strategy``, ``fk_booking_proposals_strategy`` and
``fk_strategy_enablement_events_strategy`` exist ONLY in the migrations, and so do
the append-only triggers. The backstop test below is decided by one of those
foreign keys, and on the ORM schema it would delete the row and pass for the wrong
reason.

The real repository, the real pool lock and the real history adapter are wired.
The head database is shared by the module's tests and cannot be emptied (the
ledger and the enablement log are append-only), so every test seeds ids of its own
and asserts only on them.

Spelling across the boundary: the signal is ``STXUSDT.P``, every venue-side row is
``STXUSDT`` and the strategy allows ``STXUSDT``.
"""

import logging
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository
from strategy_manager.strategies.application.delete_strategy import (
    DeleteStrategy,
    StrategyHasHistory,
)
from strategy_manager.strategies.application.ports import StrategyHistory
from strategy_manager.strategies.application.register_strategy import (
    RegisterCommand,
    RegisterStrategy,
)
from strategy_manager.strategies.domain.enablement import uptime
from strategy_manager.strategies.domain.strategy import FillMode
from strategy_manager.strategies.infrastructure.enablement_log import (
    SqlAlchemyEnablementLog,
    StrategyEnablementEventRow,
)
from strategy_manager.strategies.infrastructure.history_adapter import StrategyHistoryAdapter
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.pg_head_schema import migrated_head_database

pytestmark = pytest.mark.integration

LOGGER = "strategy_manager.strategies.application.delete_strategy"
_POOL = ("bybit", "usdt-m", "USDT")

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture(scope="module")
def head_database_url() -> Iterator[str]:
    with migrated_head_database("strategy_manager_test_delete_strategy") as url:
        yield url


@pytest.fixture
async def engine(head_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(head_database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO capital_pools (exchange, venue, settlement_currency, min_order_size) "
                "VALUES ('bybit', 'usdt-m', 'USDT', 5) ON CONFLICT DO NOTHING"
            )
        )
    yield engine
    await engine.dispose()


@pytest.fixture
def factory(engine: AsyncEngine) -> Factory:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class ZeroHistory:
    """A history that answers zero for everything: the count the database must
    still be able to overrule."""

    async def history(self, strategy_id: UUID) -> StrategyHistory:
        return StrategyHistory(0, 0, 0, 0, 0, 0)


def _real_history(session: AsyncSession) -> StrategyHistoryAdapter:
    return StrategyHistoryAdapter(
        signals=SqlAlchemySignalRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        ledger=SqlAlchemyLedgerRepository(session),
        proposals=SqlAlchemyBookingProposalRepository(session),
        enablement_log=SqlAlchemyEnablementLog(session),
    )


def _use_case(session: AsyncSession, history: object | None = None) -> DeleteStrategy:
    return DeleteStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        pool_lock=PoolLockAdapter(session),
        history=history if history is not None else _real_history(session),  # type: ignore[arg-type]
        enablement_log=SqlAlchemyEnablementLog(session),
        clock=_Clock(),  # type: ignore[arg-type]
        commit=session,  # type: ignore[arg-type]
    )


async def _seed(factory: Factory, *rows: object) -> None:
    async with factory() as session:
        session.add_all(rows)
        await session.commit()


def _strategy_row(strategy_id: UUID, *, archived: bool = False) -> StrategyRow:
    exchange, venue, currency = _POOL
    return StrategyRow(
        id=strategy_id,
        name=f"strategy-{strategy_id}",
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        enabled=False,
        fill_mode="PARTIAL",
        allowed_pairs=["STXUSDT"],
        archived_at=datetime.now(UTC) if archived else None,
    )


async def _strategy(factory: Factory, *, archived: bool = False) -> UUID:
    strategy_id = uuid4()
    await _seed(factory, _strategy_row(strategy_id, archived=archived))
    return strategy_id


async def _delete(factory: Factory, strategy_id: UUID, history: object | None = None) -> None:
    async with factory() as session:
        await _use_case(session, history).delete(strategy_id)


async def _refusal(factory: Factory, strategy_id: UUID, history: object | None = None) -> object:
    """What ``DeleteStrategy`` raised, so a wrong outcome (nothing raised, or a
    raw ``IntegrityError``) fails on an assertion about its TYPE."""
    async with factory() as session:
        try:
            await _use_case(session, history).delete(strategy_id)
        except Exception as error:  # noqa: BLE001 -- captured to assert on its type
            await session.rollback()
            return error
    return None


async def _scalar(factory: Factory, sql: str, **params: object) -> object:
    async with factory() as session:
        return await session.scalar(text(sql), params)


async def _strategy_rows(factory: Factory, strategy_id: UUID) -> object:
    return await _scalar(factory, "SELECT count(*) FROM strategies WHERE id = :id", id=strategy_id)


async def _tables_with_a_strategy_id(factory: Factory) -> list[str]:
    async with factory() as session:
        rows = await session.execute(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'strategy_id' "
                "ORDER BY table_name"
            )
        )
        return [row.table_name for row in rows]


async def test_a_never_enabled_strategy_is_deleted_and_no_table_carries_its_id(
    factory: Factory,
) -> None:
    strategy_id = await _strategy(factory)

    await _delete(factory, strategy_id)

    tables = await _tables_with_a_strategy_id(factory)
    assert tables == [
        "booking_proposals",
        "ledger_entries",
        "reservations",
        "signals",
        "strategy_enablement_events",
    ]  # the five tables of design addendum 9x, § A
    for table in tables:
        count = await _scalar(
            factory, f"SELECT count(*) FROM {table} WHERE strategy_id = :id", id=strategy_id
        )
        assert count == 0, f"{table} still carries the deleted strategy's id"
    assert await _strategy_rows(factory, strategy_id) == 0


def _signal_of(strategy_id: UUID) -> SignalRow:
    return SignalRow(
        id=uuid4(),
        strategy_id=strategy_id,
        idempotency_key=f"key-{uuid4()}",
        raw_payload={},
        action="buy",
        contracts=Decimal("1"),
        position_size=Decimal("1"),
        price=Decimal("1"),
        symbol="STXUSDT.P",
        signal_type=str(strategy_id),
    )


async def test_a_strategy_enabled_and_disabled_once_is_deleted_with_its_events(
    factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    """Migration 0028: the events go with their strategy, through the real foreign
    key and the real append-only trigger. The first enable time and the uptime of
    the deleted strategy survive in the INFO line."""
    strategy_id = await _strategy(factory)
    enabled_at = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    await _seed(
        factory,
        *(
            StrategyEnablementEventRow(
                id=uuid4(),
                strategy_id=strategy_id,
                enabled=enabled,
                occurred_at=enabled_at + timedelta(minutes=minutes),
                origin="OBSERVED",
            )
            for enabled, minutes in ((True, 0), (False, 90))
        ),
    )

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        refusal = await _refusal(factory, strategy_id)

    assert refusal is None, repr(refusal)
    assert await _strategy_rows(factory, strategy_id) == 0
    assert (
        await _scalar(
            factory,
            "SELECT count(*) FROM strategy_enablement_events WHERE strategy_id = :id",
            id=strategy_id,
        )
        == 0
    )
    records = [record for record in caplog.records if record.name == LOGGER]
    assert [record.levelno for record in records] == [logging.INFO]
    message = records[0].getMessage()
    assert "enablement_events=2" in message
    assert f"first_enabled_at={enabled_at.isoformat()}" in message
    assert "uptime_seconds=5400" in message


def _ledger_entry_of(strategy_id: UUID, other: UUID) -> list[object]:
    """A ledger entry that belongs to ``strategy_id`` and hangs off a signal, a
    reservation and an attempt of ANOTHER strategy, so it is the only kind the
    strategy owns."""
    exchange, venue, currency = _POOL
    signal = SignalRow(
        id=uuid4(),
        strategy_id=other,
        idempotency_key=f"key-{uuid4()}",
        raw_payload={},
        action="buy",
        contracts=Decimal("1"),
        position_size=Decimal("1"),
        price=Decimal("1"),
        symbol="STXUSDT.P",
        signal_type=str(other),
    )
    reservation = ReservationRow(
        id=uuid4(),
        strategy_id=other,
        signal_id=signal.id,
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        amount=Decimal("10"),
        status="PENDING",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    attempt_id = uuid4()
    attempt = ExecutionAttemptRow(
        id=attempt_id,
        reservation_id=reservation.id,
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        symbol="STXUSDT",
        side="BUY",
        quantity=Decimal("1"),
        status="SUBMITTED",
        client_order_id=f"client-{attempt_id}",
    )
    entry_id = uuid4()
    entry = LedgerEntryRow(
        id=entry_id,
        strategy_id=strategy_id,
        allocation_id=reservation.id,
        execution_attempt_id=attempt_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        symbol="STXUSDT",
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("1"),
        fee=Decimal("0"),
        fee_currency=currency,
        notional=Decimal("1"),
        exchange_order_id=f"order-{entry_id}",
        exchange_fill_id=f"fill-{entry_id}",
        filled_at=datetime.now(UTC),
        usd_rate_at_fill=Decimal("1"),
    )
    return [signal, reservation, attempt, entry]


async def test_a_strategy_with_a_ledger_entry_is_refused_and_the_entry_is_byte_for_byte_unchanged(
    factory: Factory,
) -> None:
    strategy_id = await _strategy(factory)
    other = await _strategy(factory)
    signal, reservation, attempt, entry = _ledger_entry_of(strategy_id, other)
    await _seed(factory, signal)
    await _seed(factory, reservation)
    await _seed(factory, attempt)
    await _seed(factory, entry)
    entry_sql = "SELECT to_jsonb(l)::text FROM ledger_entries l WHERE strategy_id = :id"
    before = await _scalar(factory, entry_sql, id=strategy_id)
    assert before is not None

    refusal = await _refusal(factory, strategy_id)

    assert isinstance(refusal, StrategyHasHistory), repr(refusal)
    assert refusal.history.blocking() == {"ledger_entries": 1}
    assert refusal.constraint is None  # the count caught it, not the database
    assert await _scalar(factory, entry_sql, id=strategy_id) == before
    assert await _strategy_rows(factory, strategy_id) == 1


async def test_the_database_refuses_a_delete_the_count_wrongly_allowed(
    factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    """The history answers zero over a strategy that owns one signal. The
    ``NO ACTION`` foreign key still refuses, the use case reports it as
    ``StrategyHasHistory`` with one ERROR naming the constraint, and the session
    is usable after the caller's rollback.

    Re-pointed by migration 0028 (tasks.md 9xf.3): it used an enablement event, whose
    foreign key now cascades, so the backstop is shown on a key that is still
    ``NO ACTION``."""
    strategy_id = await _strategy(factory)
    await _seed(factory, _signal_of(strategy_id))

    async with factory() as session:
        with caplog.at_level(logging.DEBUG, logger=LOGGER):
            try:
                await _use_case(session, ZeroHistory()).delete(strategy_id)
            except Exception as error:  # noqa: BLE001 -- captured to assert on its type
                refusal: object = error
            else:
                refusal = None
        assert isinstance(refusal, StrategyHasHistory), repr(refusal)
        assert refusal.constraint == "fk_signals_strategy"

        await session.rollback()  # what the route does on every refusal

        # The same session is usable again, and nothing was removed.
        assert (
            await session.scalar(
                text("SELECT count(*) FROM strategies WHERE id = :id"), {"id": strategy_id}
            )
            == 1
        )
        assert (
            await session.scalar(
                text("SELECT count(*) FROM signals WHERE strategy_id = :id"),
                {"id": strategy_id},
            )
            == 1
        )

    records = [record for record in caplog.records if record.name == LOGGER]
    assert [record.levelno for record in records] == [logging.ERROR]
    assert "fk_signals_strategy" in records[0].getMessage()
    assert str(strategy_id) in records[0].getMessage()


class _Pools:
    async def enabled_pools(self) -> list[tuple[Exchange, Venue, Currency]]:
        return [(Exchange.BYBIT, Venue.USDT_M, Currency.USDT)]


class _Catalog:
    async def available_pairs(self, pool: tuple[str, str, str]) -> frozenset[str]:
        return frozenset({"STXUSDT"})


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


async def test_a_deleted_id_registers_again_with_no_event_and_zero_uptime(
    factory: Factory,
) -> None:
    strategy_id = await _strategy(factory)
    await _delete(factory, strategy_id)

    async with factory() as session:
        registered = await RegisterStrategy(
            repository=SqlAlchemyStrategyRepository(session),
            pools=_Pools(),  # type: ignore[arg-type]
            pairs=_Catalog(),
            commit=session,  # type: ignore[arg-type]
            enablement_log=SqlAlchemyEnablementLog(session),
            clock=_Clock(),  # type: ignore[arg-type]
        ).register(
            RegisterCommand(
                strategy_id=strategy_id,
                name="registered again",
                exchange=Exchange.BYBIT,
                venue=Venue.USDT_M,
                settlement_currency=Currency.USDT,
                fill_mode=FillMode.PARTIAL,
                allocation_percent=Decimal("100"),
                allowed_pairs=["STXUSDT"],
            )
        )

    assert registered.id == strategy_id
    async with factory() as session:
        events = await SqlAlchemyEnablementLog(session).list_for(strategy_id)
        history = await _real_history(session).history(strategy_id)
    assert events == []
    assert uptime(events, _Clock().now()).seconds == 0.0
    assert history.is_empty()
