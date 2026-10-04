"""Decision 25, tasks 5c.1-5c.3 on real PostgreSQL (design.md "Addendum: signal
outcomes" section B rows 16-17, section C): the outcome ``execution.settle``
records lands in the SAME commit as the fills or the release it is decided by,
or not at all -- and lands on the right signal.

The production ``SettleExecution`` runs on ONE real session with the production
outcome recorder and a commit that can be told to fail. A failing commit is
modelled the way the driver leaves it: rolled back, error raised. Each
atomicity scenario is asserted both ways (fault on the deciding commit: nothing
lands; no fault: everything lands, with the exact commit count), because the
second half is what catches an outcome moved onto a commit of its own -- a
fault on the first commit would roll back an outcome that had not been written
yet and still look atomic.

Three spellings of one market cross the module boundaries on purpose: the
TradingView ``STXUSDT.P`` reaches the venue-facing commands, the signal rows
keep Pionex's ``STXUSDT_PERP``, and the ledger holds the bare ``STXUSDT``.
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.allocation.infrastructure.reservation_gateway import (
    ReservationGatewayAdapter,
)
from strategy_manager.execution.application.close_position import CloseCommand, ClosePosition
from strategy_manager.execution.application.place_order import PlaceCommand, PlaceOrder
from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.application.settle_execution import SettleExecution
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.exchange_registry import VenueExchangeRegistry
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_held_base import ReadHeldBase
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.domain.money import Currency
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.usd_rate import FixedUsdRateProvider
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.order_outcome_recorder import (
    SignalOrderOutcomeRecorder,
)
from strategy_manager.signals.infrastructure.outcome_repository import (
    SqlAlchemySignalOutcomeAdapter,
)
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository
from strategy_manager.signals.infrastructure.settle_outcome_recorder import (
    SignalSettleOutcomeRecorder,
)
from tests.signals.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal_row,
    seed_strategy,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)
_TRADINGVIEW = "STXUSDT.P"
_PIONEX = "STXUSDT_PERP"
_VENUE_BARE = "STXUSDT"
_GUARD_LOGGER = "strategy_manager.signals.infrastructure.outcome_repository"


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


class _FaultyCommit:
    """Commits for real, except on the ``fail_on``-th call: there it rolls the
    session back and raises, which is what a failed COMMIT leaves behind."""

    def __init__(self, session: AsyncSession, fail_on: int | None) -> None:
        self._session = session
        self._fail_on = fail_on
        self.calls = 0

    async def commit(self) -> None:
        self.calls += 1
        if self.calls == self._fail_on:
            await self._session.rollback()
            raise RuntimeError("injected commit failure")
        await self._session.commit()


def _settle(
    session: AsyncSession, commit: _FaultyCommit, exchange: FakeExchangeAdapter
) -> SettleExecution:
    return SettleExecution(
        reservations=ReservationGatewayAdapter(SqlAlchemyReservationRepository(session)),
        exchanges=VenueExchangeRegistry([exchange]),
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        fill_recorder=RecordFill(SqlAlchemyLedgerRepository(session)),
        usd_rate_provider=FixedUsdRateProvider({Currency.USDT: Decimal("1")}),
        clock=_FixedClock(),
        commit=commit,
        outcomes=SignalSettleOutcomeRecorder(
            SqlAlchemySignalOutcomeAdapter(session, _FixedClock()),
            SqlAlchemySignalRepository(session),
        ),
    )


def _place_order(session: AsyncSession, exchange: FakeExchangeAdapter) -> PlaceOrder:
    return PlaceOrder(
        reservations=ReservationGatewayAdapter(SqlAlchemyReservationRepository(session)),
        exchanges=VenueExchangeRegistry([exchange]),
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        queue=PostgresJobQueue(session, clock=_FixedClock()),
        clock=_FixedClock(),
        commit=session,
        settle_delay_seconds=0.0,
        outcomes=SignalOrderOutcomeRecorder(
            SqlAlchemySignalOutcomeAdapter(session, _FixedClock())
        ),
    )


def _close_position(session: AsyncSession, exchange: FakeExchangeAdapter) -> ClosePosition:
    return ClosePosition(
        exchanges=VenueExchangeRegistry([exchange]),
        attempts=SqlAlchemyExecutionAttemptRepository(session),
        held=ReadHeldBase(SqlAlchemyLedgerRepository(session)),
        queue=PostgresJobQueue(session, clock=_FixedClock()),
        clock=_FixedClock(),
        commit=session,
        settle_delay_seconds=0.0,
        outcomes=SignalOrderOutcomeRecorder(
            SqlAlchemySignalOutcomeAdapter(session, _FixedClock())
        ),
    )


async def _signal(factory: async_sessionmaker[AsyncSession], signal_id: UUID) -> SignalRow:
    async with factory() as session:
        return (
            await session.execute(select(SignalRow).where(SignalRow.id == signal_id))
        ).scalar_one()


async def _reservation(
    factory: async_sessionmaker[AsyncSession], reservation_id: UUID
) -> ReservationRow:
    async with factory() as session:
        return (
            await session.execute(
                select(ReservationRow).where(ReservationRow.id == reservation_id)
            )
        ).scalar_one()


async def _attempts(factory: async_sessionmaker[AsyncSession]) -> list[ExecutionAttemptRow]:
    async with factory() as session:
        return list((await session.execute(select(ExecutionAttemptRow))).scalars())


async def _ledger_rows(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        return int(
            (await session.execute(select(func.count()).select_from(LedgerEntryRow))).scalar_one()
        )


async def _set_outcome(
    factory: async_sessionmaker[AsyncSession], signal_id: UUID, outcome: SignalOutcome
) -> None:
    async with factory() as session:
        await SqlAlchemySignalOutcomeAdapter(session, _FixedClock()).record(signal_id, outcome)
        await session.commit()


def _guard_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _GUARD_LOGGER]


async def _seed_open(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID, UUID]:
    """A strategy, the signal that wants to open, and its PENDING reservation.
    Returns (strategy_id, signal_id, reservation_id)."""
    strategy_id, signal_id, reservation_id = uuid4(), uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await seed_signal_row(
        factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"open-{signal_id}",
        symbol=_PIONEX,
    )
    await seed_reservation(
        factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        status="PENDING",
        expires_at=_NOW + timedelta(hours=1),
    )
    return strategy_id, signal_id, reservation_id


async def _place_open(
    factory: async_sessionmaker[AsyncSession],
    exchange: FakeExchangeAdapter,
    reservation_id: UUID,
) -> None:
    async with factory() as session:
        result = await _place_order(session, exchange).place(
            PlaceCommand(
                reservation_id=reservation_id,
                symbol=_TRADINGVIEW,
                side=OrderSide.BUY,
                price=Decimal("2"),
            )
        )
    assert result.status == "PLACED"


async def _seed_position(
    factory: async_sessionmaker[AsyncSession],
    *,
    closing_position_size: str,
    opening_position_size: str = "1",
) -> tuple[UUID, UUID, UUID, UUID]:
    """An open long of 1 STX under one allocation, opened by an OPENING signal
    that is already PROCESSED, and the NEW signal that asks to close it. The
    two signals' ``position_size`` decide the closing signal's kind: 1 -> 0 is
    a plain CLOSE, 1 -> -1 is a REVERSE. Returns (strategy_id, opening_signal,
    closing_signal, allocation_id)."""
    strategy_id, opening_signal_id, closing_signal_id = uuid4(), uuid4(), uuid4()
    allocation_id, opening_attempt_id = uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await seed_signal_row(
        factory,
        signal_id=opening_signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"opening-{opening_signal_id}",
        symbol=_PIONEX,
        position_size=Decimal(opening_position_size),
        received_at=_NOW - timedelta(hours=2),
    )
    await seed_signal_row(
        factory,
        signal_id=closing_signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"closing-{closing_signal_id}",
        symbol=_PIONEX,
        position_size=Decimal(closing_position_size),
        received_at=_NOW - timedelta(hours=1),
    )
    await seed_reservation(
        factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=opening_signal_id,
        status="FILLED",
    )
    await seed_execution_attempt(
        factory,
        attempt_id=opening_attempt_id,
        reservation_id=allocation_id,
        symbol=_VENUE_BARE,
        status="FILLED",
    )
    async with factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            FillRecord(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                execution_attempt_id=opening_attempt_id,
                exchange="bybit",
                venue="usdt-m",
                settlement_currency="USDT",
                symbol=_VENUE_BARE,
                side="BUY",
                quantity=Decimal("1"),
                price=Decimal("2"),
                fee=Decimal("0"),
                fee_currency="USDT",
                notional=Decimal("2"),
                exchange_order_id=f"opening-order-{opening_attempt_id}",
                exchange_fill_id=f"opening-fill-{opening_attempt_id}",
                filled_at=_NOW - timedelta(hours=1),
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()
    # The opening signal reached its final status long ago.
    await _set_outcome(factory, opening_signal_id, SignalOutcome.processed())
    return strategy_id, opening_signal_id, closing_signal_id, allocation_id


async def _place_close(
    factory: async_sessionmaker[AsyncSession],
    exchange: FakeExchangeAdapter,
    strategy_id: UUID,
    allocation_id: UUID,
    closing_signal_id: UUID,
) -> None:
    async with factory() as session:
        result = await _close_position(session, exchange).close(
            CloseCommand(
                allocation_id=allocation_id,
                strategy_id=strategy_id,
                exchange="bybit",
                venue="usdt-m",
                settlement_currency="USDT",
                symbol=_TRADINGVIEW,
                side=OrderSide.SELL,
                signal_id=closing_signal_id,
            )
        )
    assert result.status == "PLACED"


async def _closing_attempt(
    factory: async_sessionmaker[AsyncSession], allocation_id: UUID
) -> ExecutionAttemptRow:
    [attempt] = [
        a for a in await _attempts(factory) if a.closes_allocation_id == allocation_id
    ]
    return attempt


# ---- 5c.3: the link is written on the attempt insert ------------------------


async def test_placing_an_open_writes_the_signal_link_on_its_attempt(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, signal_id, reservation_id = await _seed_open(pg_session_factory)

    await _place_open(
        pg_session_factory,
        FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0")),
        reservation_id,
    )

    [attempt] = await _attempts(pg_session_factory)
    assert attempt.signal_id == signal_id


async def test_placing_a_close_writes_the_closing_signal_link_not_the_opening_one(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, opening_signal, closing_signal, allocation_id = await _seed_position(
        pg_session_factory, closing_position_size="0"
    )

    await _place_close(
        pg_session_factory,
        FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0")),
        strategy_id,
        allocation_id,
        closing_signal,
    )

    attempt = await _closing_attempt(pg_session_factory, allocation_id)
    assert attempt.signal_id == closing_signal
    assert attempt.signal_id != opening_signal


# ---- 5c.1: settle of an OPEN, FILLED ----------------------------------------


async def test_a_filled_open_processes_its_signal_in_the_commit_that_records_the_fills(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    exchange = FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))
    _, signal_id, reservation_id = await _seed_open(pg_session_factory)
    await _place_open(pg_session_factory, exchange, reservation_id)
    [attempt] = await _attempts(pg_session_factory)
    assert (await _signal(pg_session_factory, signal_id)).status == "PROCESSING"

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=None)
        result = await _settle(session, commit, exchange).settle(attempt.id)

    assert result.status == "FILLED"
    assert commit.calls == 1  # the outcome is NOT on a commit of its own
    signal = await _signal(pg_session_factory, signal_id)
    assert (signal.status, signal.outcome_reason, signal.decided_at) == (
        "PROCESSED",
        None,
        _NOW,
    )
    assert await _ledger_rows(pg_session_factory) == 1
    assert (await _reservation(pg_session_factory, reservation_id)).status == "FILLED"


async def test_a_failed_settle_commit_loses_the_fills_and_the_processed_status_together(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    exchange = FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))
    _, signal_id, reservation_id = await _seed_open(pg_session_factory)
    await _place_open(pg_session_factory, exchange, reservation_id)
    [attempt] = await _attempts(pg_session_factory)

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=1)
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await _settle(session, commit, exchange).settle(attempt.id)

    assert (await _signal(pg_session_factory, signal_id)).status == "PROCESSING"
    assert await _ledger_rows(pg_session_factory) == 0
    assert (await _reservation(pg_session_factory, reservation_id)).status == "SUBMITTED"


async def test_a_legacy_open_attempt_with_no_link_still_resolves_through_its_reservation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """5c.1: an open resolves its signal through ``reservation.signal_id``,
    so an attempt written before this PR (NULL link) still ends its signal."""
    exchange = FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))
    _, signal_id, reservation_id = await _seed_open(pg_session_factory)
    await _place_open(pg_session_factory, exchange, reservation_id)
    [attempt] = await _attempts(pg_session_factory)
    async with pg_session_factory() as session:
        row = await session.get(ExecutionAttemptRow, attempt.id)
        assert row is not None
        row.signal_id = None
        await session.commit()

    async with pg_session_factory() as session:
        await _settle(session, _FaultyCommit(session, fail_on=None), exchange).settle(attempt.id)

    assert (await _signal(pg_session_factory, signal_id)).status == "PROCESSED"


# ---- 5c.3: settle of a CLOSE, FILLED ----------------------------------------


async def test_a_filled_plain_close_processes_the_closing_signal_not_the_opening_one(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The opening signal is already PROCESSED. Had settle resolved the close
    through the OPENING reservation it would have hit the terminal guard (an
    identical repeat here, so silently) and left the CLOSING signal
    PROCESSING forever -- so this asserts the closing signal's own row."""
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    exchange = FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))
    strategy_id, opening_signal, closing_signal, allocation_id = await _seed_position(
        pg_session_factory, closing_position_size="0"
    )
    await _place_close(pg_session_factory, exchange, strategy_id, allocation_id, closing_signal)
    attempt = await _closing_attempt(pg_session_factory, allocation_id)
    assert (await _signal(pg_session_factory, closing_signal)).status == "PROCESSING"

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=None)
        result = await _settle(session, commit, exchange).settle(attempt.id)

    assert result.status == "FILLED"
    assert commit.calls == 1
    closing = await _signal(pg_session_factory, closing_signal)
    assert (closing.status, closing.decided_at) == ("PROCESSED", _NOW)
    assert _guard_records(caplog) == []
    assert await _ledger_rows(pg_session_factory) == 2  # the open, and the close


async def test_a_failed_close_settle_commit_loses_the_fills_and_the_processed_status_together(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    exchange = FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))
    strategy_id, _, closing_signal, allocation_id = await _seed_position(
        pg_session_factory, closing_position_size="0"
    )
    await _place_close(pg_session_factory, exchange, strategy_id, allocation_id, closing_signal)
    attempt = await _closing_attempt(pg_session_factory, allocation_id)

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=1)
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await _settle(session, commit, exchange).settle(attempt.id)

    assert (await _signal(pg_session_factory, closing_signal)).status == "PROCESSING"
    assert await _ledger_rows(pg_session_factory) == 1  # only the seeded open


async def test_a_filled_reverse_close_leaves_the_signal_processing_and_writes_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Decision 26: 1 -> -1 is a REVERSE; its open half decides."""
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    exchange = FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))
    strategy_id, _, reverse_signal, allocation_id = await _seed_position(
        pg_session_factory, closing_position_size="-1"
    )
    await _place_close(pg_session_factory, exchange, strategy_id, allocation_id, reverse_signal)
    attempt = await _closing_attempt(pg_session_factory, allocation_id)

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=None)
        result = await _settle(session, commit, exchange).settle(attempt.id)

    assert result.status == "FILLED"
    signal = await _signal(pg_session_factory, reverse_signal)
    assert (signal.status, signal.outcome_reason, signal.decided_at) == (
        "PROCESSING",
        None,
        None,
    )
    assert _guard_records(caplog) == []
    assert await _ledger_rows(pg_session_factory) == 2  # the fills still landed


async def test_a_filled_close_of_a_spot_reverse_already_rejected_writes_nothing_and_never_warns(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Row 18: a spot REVERSE whose new side cannot be held is already
    REJECTED ``REVERSE_NEW_SIDE_UNHOLDABLE`` when its close fills. A PROCESSED
    written here would reach the terminal guard as a DIFFERING write and warn
    on every such trade."""
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    exchange = FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))
    strategy_id, _, reverse_signal, allocation_id = await _seed_position(
        pg_session_factory, closing_position_size="-1"
    )
    await _place_close(pg_session_factory, exchange, strategy_id, allocation_id, reverse_signal)
    attempt = await _closing_attempt(pg_session_factory, allocation_id)
    await _set_outcome(
        pg_session_factory,
        reverse_signal,
        SignalOutcome.rejected("REVERSE_NEW_SIDE_UNHOLDABLE", "the close was submitted"),
    )
    before = await _signal(pg_session_factory, reverse_signal)

    async with pg_session_factory() as session:
        await _settle(session, _FaultyCommit(session, fail_on=None), exchange).settle(attempt.id)

    after = await _signal(pg_session_factory, reverse_signal)
    assert (after.status, after.outcome_reason, after.outcome_detail, after.decided_at) == (
        before.status,
        before.outcome_reason,
        before.outcome_detail,
        before.decided_at,
    )
    assert after.status == "REJECTED"
    assert _guard_records(caplog) == []


# ---- 5c.2: settle, NEVER_PLACED ---------------------------------------------


async def test_a_never_placed_open_rejects_its_signal_in_the_commit_that_releases_the_reservation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The attempt exists (SUBMITTED) but the exchange never saw the order."""
    _, signal_id, reservation_id = await _seed_open(pg_session_factory)
    attempt_id = uuid4()
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=attempt_id,
        reservation_id=reservation_id,
        symbol=_VENUE_BARE,
    )

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=None)
        result = await _settle(session, commit, FakeExchangeAdapter(
            exchange="bybit",
            fee_rate=Decimal("0"),
        )).settle(
            attempt_id
        )

    assert result.status == "NEVER_PLACED"
    assert commit.calls == 1
    signal = await _signal(pg_session_factory, signal_id)
    assert (signal.status, signal.outcome_reason, signal.decided_at) == (
        "REJECTED",
        "ORDER_NEVER_REACHED_EXCHANGE",
        _NOW,
    )
    assert signal.outcome_detail is not None
    assert str(attempt_id) in signal.outcome_detail
    assert "reservation released" in signal.outcome_detail
    assert (await _reservation(pg_session_factory, reservation_id)).status == "RELEASED"


async def test_a_failed_release_commit_loses_the_release_and_the_rejection_together(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, signal_id, reservation_id = await _seed_open(pg_session_factory)
    attempt_id = uuid4()
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=attempt_id,
        reservation_id=reservation_id,
        symbol=_VENUE_BARE,
    )

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=1)
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await _settle(
                session, commit, FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))
            ).settle(attempt_id)

    assert (await _signal(pg_session_factory, signal_id)).status == "ACCEPTED"
    assert (await _reservation(pg_session_factory, reservation_id)).status == "PENDING"
    [attempt] = await _attempts(pg_session_factory)
    assert attempt.status == "SUBMITTED"


async def test_a_never_placed_close_rejects_the_closing_signal_only(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The opening allocation stays FILLED (the position is still open); only
    the CLOSING signal ends, with the close's code -- including a REVERSE's,
    since nothing executed and no open half will follow."""
    strategy_id, opening_signal, reverse_signal, allocation_id = await _seed_position(
        pg_session_factory, closing_position_size="-1"
    )
    attempt_id = uuid4()
    async with pg_session_factory() as session:
        await SqlAlchemyExecutionAttemptRepository(session).insert(
            _submitted_close(attempt_id, allocation_id, reverse_signal)
        )
        await session.commit()

    async with pg_session_factory() as session:
        commit = _FaultyCommit(session, fail_on=None)
        result = await _settle(session, commit, FakeExchangeAdapter(
            exchange="bybit",
            fee_rate=Decimal("0"),
        )).settle(
            attempt_id
        )

    assert result.status == "NEVER_PLACED"
    assert commit.calls == 1
    signal = await _signal(pg_session_factory, reverse_signal)
    assert (signal.status, signal.outcome_reason) == (
        "REJECTED",
        "ORDER_NEVER_REACHED_EXCHANGE",
    )
    assert signal.outcome_detail is not None and "position remains open" in signal.outcome_detail
    opening = await _signal(pg_session_factory, opening_signal)
    assert opening.status == "PROCESSED"  # untouched
    assert (await _reservation(pg_session_factory, allocation_id)).status == "FILLED"


async def test_a_never_placed_close_with_no_link_rejects_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, opening_signal, closing_signal, allocation_id = await _seed_position(
        pg_session_factory, closing_position_size="0"
    )
    attempt_id = uuid4()
    async with pg_session_factory() as session:
        await SqlAlchemyExecutionAttemptRepository(session).insert(
            _submitted_close(attempt_id, allocation_id, None)
        )
        await session.commit()

    async with pg_session_factory() as session:
        result = await _settle(
            session,
            _FaultyCommit(session, fail_on=None),
            FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0")),
        ).settle(attempt_id)

    assert result.status == "NEVER_PLACED"
    assert (await _signal(pg_session_factory, closing_signal)).status == "ACCEPTED"
    assert (await _signal(pg_session_factory, opening_signal)).status == "PROCESSED"


def _submitted_close(attempt_id: UUID, allocation_id: UUID, signal_id: UUID | None):  # type: ignore[no-untyped-def]
    from strategy_manager.execution.domain.execution_attempt import (
        ExecutionAttempt,
        ExecutionOrigin,
        ExecutionStatus,
    )

    return ExecutionAttempt(
        id=attempt_id,
        reservation_id=None,
        closes_allocation_id=allocation_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=_VENUE_BARE,
        side=OrderSide.SELL,
        quantity=Decimal("1"),
        quote_amount=None,
        leverage=None,
        status=ExecutionStatus.SUBMITTED,
        origin=ExecutionOrigin.SYSTEM,
        client_order_id=f"client-{attempt_id}",
        signal_id=signal_id,
    )
