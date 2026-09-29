"""Decision 25, tasks 5c.4 and 5c.5 on real PostgreSQL: the continuation job
(``signal.open_after_close``) records its abandonments, and the open half it
runs through ``open_now`` records its outcome, both in that job's own commits.

The production composition root builds the handler
(``main._build_process_signal_handler``), so this proves the wiring as well as
the behaviour: a continuation built without the outcome port, or with the
warning path instead of the silent one, fails here. The handler's trailing
``session.commit()`` is replayed exactly as ``main.handle_signal_open_after_close``
does after ``poll`` -- it is the commit an abandonment rides.

Three spellings of one market cross the module boundaries on purpose: the
signals keep Pionex's ``STXUSDT_PERP``, the ledger and the opening attempt hold
the bare ``STXUSDT``, and the closing attempt keeps TradingView's
``STXUSDT.P``.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.ports import PoolBalanceReading
from strategy_manager.accounts.application.ports import PoolKey as AccountsPoolKey
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.infrastructure.exchange_registry import VenueExchangeRegistry
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.main import _build_process_signal_handler
from strategy_manager.reconciliation.infrastructure.venue_position_reader_registry import (
    VenuePositionReaderRegistry,
)
from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.outcome_repository import (
    SqlAlchemySignalOutcomeAdapter,
)
from tests.signals.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal_row,
    seed_strategy,
)

pytestmark = pytest.mark.integration

_POOL = ("bybit", "usdt-m", "USDT")
_PIONEX = "STXUSDT_PERP"
_TRADINGVIEW = "STXUSDT.P"
_VENUE_BARE = "STXUSDT"
_GUARD_LOGGER = "strategy_manager.signals.infrastructure.outcome_repository"


class _NowClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class _RichBalanceReader:
    """A venue that always reports plenty of free USDT."""

    async def read(self, pools: Sequence[AccountsPoolKey]) -> list[PoolBalanceReading]:
        now = datetime.now(UTC)
        return [
            PoolBalanceReading(
                exchange=pool[0],
                venue=pool[1],
                settlement_currency=pool[2],
                total=Decimal("1000"),
                available=Decimal("1000"),
                observed_at=now,
            )
            for pool in pools
        ]


async def _signal(factory: async_sessionmaker[AsyncSession], signal_id: UUID) -> SignalRow:
    async with factory() as session:
        return (
            await session.execute(select(SignalRow).where(SignalRow.id == signal_id))
        ).scalar_one()


async def _decide(
    factory: async_sessionmaker[AsyncSession], signal_id: UUID, outcome: SignalOutcome
) -> None:
    async with factory() as session:
        await SqlAlchemySignalOutcomeAdapter(session, _NowClock()).record(signal_id, outcome)
        await session.commit()


def _guard_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _GUARD_LOGGER]


class _Scenario:
    """A strategy that held a long, and the REVERSE signal that asked to flip
    it short. ``close_status`` is the status of the close the REVERSE placed
    (``None``: it never wrote an attempt, like a dust close)."""

    def __init__(
        self,
        strategy_id: UUID,
        opening_signal_id: UUID,
        reverse_signal_id: UUID,
        allocation_id: UUID,
    ) -> None:
        self.strategy_id = strategy_id
        self.opening_signal_id = opening_signal_id
        self.reverse_signal_id = reverse_signal_id
        self.allocation_id = allocation_id


async def _seed_reverse(
    factory: async_sessionmaker[AsyncSession],
    *,
    allowed_pairs: frozenset[str] | None,
    close_status: str | None,
    reverse_age: timedelta = timedelta(seconds=30),
) -> _Scenario:
    strategy_id, opening_signal, reverse_signal = uuid4(), uuid4(), uuid4()
    allocation_id, opening_attempt = uuid4(), uuid4()
    now = datetime.now(UTC)
    await seed_strategy(factory, strategy_id=strategy_id, allowed_pairs=allowed_pairs)
    await seed_signal_row(
        factory,
        signal_id=opening_signal,
        strategy_id=strategy_id,
        idempotency_key=f"opening-{opening_signal}",
        symbol=_PIONEX,
        position_size=Decimal("1"),
        received_at=now - timedelta(hours=3),
    )
    await seed_signal_row(
        factory,
        signal_id=reverse_signal,
        strategy_id=strategy_id,
        idempotency_key=f"reverse-{reverse_signal}",
        symbol=_PIONEX,
        position_size=Decimal("-1"),
        received_at=now - reverse_age,
    )
    await seed_reservation(
        factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=opening_signal,
        status="FILLED",
    )
    await seed_execution_attempt(
        factory,
        attempt_id=opening_attempt,
        reservation_id=allocation_id,
        symbol=_VENUE_BARE,
        status="FILLED",
    )
    async with factory() as session:
        recorder = RecordFill(SqlAlchemyLedgerRepository(session))
        await recorder.record(_fill(strategy_id, allocation_id, opening_attempt, "BUY", now))
        if close_status == "FILLED":
            close_attempt = uuid4()
            await session.commit()
            await seed_execution_attempt(
                factory,
                attempt_id=close_attempt,
                closes_allocation_id=allocation_id,
                symbol=_TRADINGVIEW,
                status="FILLED",
                signal_id=reverse_signal,
            )
            async with factory() as ledger_session:
                await RecordFill(SqlAlchemyLedgerRepository(ledger_session)).record(
                    _fill(strategy_id, allocation_id, close_attempt, "SELL", now)
                )
                await ledger_session.commit()
        else:
            await session.commit()
            if close_status is not None:
                await seed_execution_attempt(
                    factory,
                    attempt_id=uuid4(),
                    closes_allocation_id=allocation_id,
                    symbol=_TRADINGVIEW,
                    status=close_status,
                    signal_id=reverse_signal,
                )
    await _decide(factory, opening_signal, SignalOutcome.processed())
    return _Scenario(strategy_id, opening_signal, reverse_signal, allocation_id)


def _fill(
    strategy_id: UUID, allocation_id: UUID, attempt_id: UUID, side: str, at: datetime
) -> FillRecord:
    return FillRecord(
        strategy_id=strategy_id,
        allocation_id=allocation_id,
        execution_attempt_id=attempt_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=_VENUE_BARE,
        side=side,
        quantity=Decimal("1"),
        price=Decimal("2"),
        fee=Decimal("0"),
        fee_currency="USDT",
        notional=Decimal("2"),
        exchange_order_id=f"order-{attempt_id}",
        exchange_fill_id=f"fill-{attempt_id}",
        filled_at=at - timedelta(hours=1),
        usd_rate_at_fill=Decimal("1"),
    )


async def _run_continuation(
    factory: async_sessionmaker[AsyncSession], scenario: _Scenario, *, awaited: list[UUID]
) -> None:
    """One ``signal.open_after_close`` job exactly as the worker runs it: the
    production handler, ``poll``, then the handler's trailing commit."""
    settings = get_settings()
    exchange = FakeExchangeAdapter(exchange="bybit", fill_price=Decimal("2"))
    pools = {
        _POOL: PoolConfig(
            exchange=Exchange("bybit"),
            venue=Venue("usdt-m"),
            settlement_currency=Currency("USDT"),
            min_order_size=Decimal("1"),
        )
    }
    async with factory() as session:
        _, open_after_close = _build_process_signal_handler(
            session,
            pools,
            settings,
            VenueExchangeRegistry([exchange]),
            frozenset({("bybit", "usdt-m")}),
            _RichBalanceReader(),  # type: ignore[arg-type]
            VenuePositionReaderRegistry([]),
        )
        await open_after_close.poll(
            ClaimedJob(
                id=uuid4(),
                kind=JobKind.SIGNAL_OPEN_AFTER_CLOSE,
                payload={
                    "signal_id": str(scenario.reverse_signal_id),
                    "awaited_allocation_ids": [str(a) for a in awaited],
                    "poll": 0,
                },
                attempts=1,
                max_attempts=5,
            )
        )
        await session.commit()


# ---- 5c.5: the open half, through open_now, in the continuation's commits ----


async def test_a_reverse_whose_open_is_refused_after_its_close_filled_ends_rejected(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Decision 26: the close half executed, the open half is refused
    (``PAIR_NOT_ALLOWED``: this strategy lists no pair), so the signal ends
    REJECTED with the OPEN's code and a detail that says the close executed."""
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    scenario = await _seed_reverse(pg_session_factory, allowed_pairs=None, close_status="FILLED")
    await _decide(pg_session_factory, scenario.reverse_signal_id, SignalOutcome.processing())

    await _run_continuation(pg_session_factory, scenario, awaited=[scenario.allocation_id])

    signal = await _signal(pg_session_factory, scenario.reverse_signal_id)
    assert (signal.status, signal.outcome_reason) == ("REJECTED", "PAIR_NOT_ALLOWED")
    assert signal.decided_at is not None
    assert signal.outcome_detail is not None
    assert "close half of this REVERSE already executed" in signal.outcome_detail
    assert _guard_records(caplog) == []


async def test_a_reverse_whose_open_proceeds_ends_processing_in_the_continuations_commits(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The open is placed, so the signal is PROCESSING (never PROCESSED: its
    fate is settle's), and the new attempt is linked to the REVERSE signal."""
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    scenario = await _seed_reverse(
        pg_session_factory, allowed_pairs=frozenset({_VENUE_BARE}), close_status="FILLED"
    )
    # Left ACCEPTED on purpose: the PROCESSING below must be written by the
    # open half itself, not inherited from an earlier deferral.
    assert (await _signal(pg_session_factory, scenario.reverse_signal_id)).status == "ACCEPTED"

    await _run_continuation(pg_session_factory, scenario, awaited=[scenario.allocation_id])

    signal = await _signal(pg_session_factory, scenario.reverse_signal_id)
    assert (signal.status, signal.outcome_reason, signal.decided_at) == (
        "PROCESSING",
        None,
        None,
    )
    async with pg_session_factory() as session:
        reservations = (
            (
                await session.execute(
                    select(ReservationRow).where(
                        ReservationRow.signal_id == scenario.reverse_signal_id
                    )
                )
            )
            .scalars()
            .all()
        )
        attempts = (
            (
                await session.execute(
                    select(ExecutionAttemptRow).where(
                        ExecutionAttemptRow.signal_id == scenario.reverse_signal_id,
                        ExecutionAttemptRow.reservation_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(reservations) == 1 and reservations[0].status == "SUBMITTED"
    assert len(attempts) == 1 and attempts[0].reservation_id == reservations[0].id
    assert _guard_records(caplog) == []


# ---- 5c.4: abandonments, durable through the job's trailing commit ----------


async def test_an_awaited_close_that_failed_rejects_a_live_signal_durably(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await _seed_reverse(pg_session_factory, allowed_pairs=None, close_status="FAILED")
    await _decide(pg_session_factory, scenario.reverse_signal_id, SignalOutcome.processing())

    await _run_continuation(pg_session_factory, scenario, awaited=[scenario.allocation_id])

    signal = await _signal(pg_session_factory, scenario.reverse_signal_id)
    assert (signal.status, signal.outcome_reason) == ("REJECTED", "AWAITED_CLOSE_FAILED")
    assert signal.outcome_detail is not None and "an awaited close failed" in signal.outcome_detail
    assert signal.decided_at is not None


async def test_a_superseded_signal_is_rejected_durably(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await _seed_reverse(pg_session_factory, allowed_pairs=None, close_status="SUBMITTED")
    await _decide(pg_session_factory, scenario.reverse_signal_id, SignalOutcome.processing())
    await seed_signal_row(
        pg_session_factory,
        signal_id=uuid4(),
        strategy_id=scenario.strategy_id,
        idempotency_key="newer",
        symbol=_PIONEX,
        position_size=Decimal("0"),
        received_at=datetime.now(UTC) - timedelta(seconds=5),
    )

    await _run_continuation(pg_session_factory, scenario, awaited=[scenario.allocation_id])

    signal = await _signal(pg_session_factory, scenario.reverse_signal_id)
    assert (signal.status, signal.outcome_reason) == ("REJECTED", "SIGNAL_SUPERSEDED")


async def test_a_dust_reverse_times_out_without_a_warning_because_it_already_ended(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A dust close writes no attempt, so its seeded continuation waits for a
    close that will never exist and abandons on the age bound. The signal is
    ALREADY ``REJECTED`` ``CLOSE_DUST_NOT_CLOSABLE`` from ``signal.process``:
    the abandonment must leave it exactly so and stay silent."""
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    scenario = await _seed_reverse(
        pg_session_factory,
        allowed_pairs=None,
        close_status=None,
        reverse_age=timedelta(hours=1),
    )
    await _decide(
        pg_session_factory,
        scenario.reverse_signal_id,
        SignalOutcome.rejected("CLOSE_DUST_NOT_CLOSABLE", "dust no order can close"),
    )
    before = await _signal(pg_session_factory, scenario.reverse_signal_id)

    await _run_continuation(pg_session_factory, scenario, awaited=[scenario.allocation_id])

    after = await _signal(pg_session_factory, scenario.reverse_signal_id)
    assert (after.status, after.outcome_reason, after.outcome_detail, after.decided_at) == (
        before.status,
        before.outcome_reason,
        before.outcome_detail,
        before.decided_at,
    )
    assert after.outcome_reason == "CLOSE_DUST_NOT_CLOSABLE"
    assert _guard_records(caplog) == []


async def test_a_refused_close_reverse_abandons_as_close_failed_without_a_warning(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The other case named in the design: a REVERSE whose close was refused
    is ``REJECTED`` ``CLOSE_REJECTED_BY_VENUE``; its continuation later finds
    the FAILED close and abandons as ``AWAITED_CLOSE_FAILED``."""
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    scenario = await _seed_reverse(pg_session_factory, allowed_pairs=None, close_status="FAILED")
    await _decide(
        pg_session_factory,
        scenario.reverse_signal_id,
        SignalOutcome.rejected("CLOSE_REJECTED_BY_VENUE", "the venue refused the close"),
    )

    await _run_continuation(pg_session_factory, scenario, awaited=[scenario.allocation_id])

    signal = await _signal(pg_session_factory, scenario.reverse_signal_id)
    assert (signal.status, signal.outcome_reason) == ("REJECTED", "CLOSE_REJECTED_BY_VENUE")
    assert signal.outcome_detail == "the venue refused the close"
    assert _guard_records(caplog) == []


async def test_an_already_processed_signal_is_left_alone_by_an_abandonment_without_a_warning(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    scenario = await _seed_reverse(pg_session_factory, allowed_pairs=None, close_status="FAILED")
    await _decide(pg_session_factory, scenario.reverse_signal_id, SignalOutcome.processed())

    await _run_continuation(pg_session_factory, scenario, awaited=[scenario.allocation_id])

    signal = await _signal(pg_session_factory, scenario.reverse_signal_id)
    assert (signal.status, signal.outcome_reason) == ("PROCESSED", None)
    assert _guard_records(caplog) == []


async def test_a_deleted_signal_writes_nothing_and_raises_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario = await _seed_reverse(pg_session_factory, allowed_pairs=None, close_status="FAILED")
    scenario.reverse_signal_id = uuid4()  # a job whose signal no longer exists

    await _run_continuation(pg_session_factory, scenario, awaited=[scenario.allocation_id])
    # reaching here is the assertion: the abandonment logged and returned
