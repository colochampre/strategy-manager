"""Decision 25, task 5b.9 on real PostgreSQL (design.md "Addendum: signal
outcomes" B, rows 19-20): a duplicate webhook delivery and an idempotent close
replay never change an outcome the signal already holds.

Each test starts from a signal that ALREADY holds a terminal outcome, replays
the step, and asserts status, reason, detail and ``decided_at`` are exactly as
they were. For the handler replays that alone is not enough proof: the
terminal-state guard would turn a stray, different write into a silent no-op
plus one WARNING, leaving the row untouched. So they also assert the guard
logged nothing, which is what distinguishes "no write attempted" from "a write
attempted and refused".
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.domain.execution_attempt import ExecutionStatus
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.models import JobRow
from strategy_manager.signals.application.ingest_signal import IngestCommand, IngestSignal
from strategy_manager.signals.application.process_signal import SignalContext
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.outcome_repository import (
    SqlAlchemySignalOutcomeAdapter,
)
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository
from tests.signals.application.test_process_signal import (
    FakeClosingAttemptsPort,
    SpyAdvisoryLock,
    SpyClosePosition,
    SpyPlaceOrder,
    _allocate_capital,
    _holdable_reverse_context,
    _process_signal_handler,
)
from tests.signals.application.test_process_signal_order_outcomes import (
    _existing_close,
    _spot_short_reverse_context,
)
from tests.signals.infrastructure.conftest import seed_signal_row, seed_strategy

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)
_GUARD_LOGGER = "strategy_manager.signals.infrastructure.outcome_repository"

Snapshot = tuple[str, str | None, str | None, datetime | None]


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


async def _snapshot(
    factory: async_sessionmaker[AsyncSession], signal_id: UUID
) -> Snapshot:
    async with factory() as session:
        row = (
            await session.execute(select(SignalRow).where(SignalRow.id == signal_id))
        ).scalar_one()
    return (row.status, row.outcome_reason, row.outcome_detail, row.decided_at)


async def _decide(
    factory: async_sessionmaker[AsyncSession], signal_id: UUID, outcome: SignalOutcome
) -> Snapshot:
    """Gives the signal a terminal outcome through the real adapter."""
    async with factory() as session:
        await SqlAlchemySignalOutcomeAdapter(session, _FixedClock()).record(signal_id, outcome)
        await session.commit()
    return await _snapshot(factory, signal_id)


async def _seed(
    factory: async_sessionmaker[AsyncSession], *, key: str, symbol: str = "STXUSDT_PERP"
) -> tuple[UUID, UUID]:
    strategy_id, signal_id = uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await seed_signal_row(
        factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=key,
        symbol=symbol,
    )
    return strategy_id, signal_id


def _guard_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _GUARD_LOGGER]


# ---- row 19: a duplicate webhook delivery ----------------------------------


@pytest.mark.parametrize(
    "outcome",
    [
        SignalOutcome.processed(),
        SignalOutcome.rejected("PAIR_NOT_ALLOWED", "refused at the first delivery"),
    ],
    ids=["processed", "rejected"],
)
async def test_a_duplicate_delivery_leaves_a_terminal_outcome_untouched(
    pg_session_factory: async_sessionmaker[AsyncSession], outcome: SignalOutcome
) -> None:
    strategy_id, signal_id = await _seed(pg_session_factory, key="delivery-1")
    before = await _decide(pg_session_factory, signal_id, outcome)
    assert before[0] == outcome.status.value  # the precondition is really terminal

    async with pg_session_factory() as session:
        result = await IngestSignal(
            repository=SqlAlchemySignalRepository(session),
            job_queue=PostgresJobQueue(session, clock=_FixedClock()),
            uow=session,
        ).ingest(
            IngestCommand(
                strategy_id=strategy_id,
                idempotency_key="delivery-1",  # the SAME key: TradingView re-sent it
                action="buy",
                contracts=Decimal("1"),
                position_size=Decimal("1"),
                price=Decimal("2"),
                symbol="STXUSDT.P",
                signal_type=str(strategy_id),
                raw_payload={"redelivered": True},
            )
        )

    assert result.duplicate is True
    assert result.signal_id == signal_id
    assert await _snapshot(pg_session_factory, signal_id) == before
    async with pg_session_factory() as session:
        # a duplicate enqueues nothing, so no second run can re-decide it
        assert (await session.execute(select(JobRow))).scalars().all() == []


# ---- row 20: an idempotent close replay ------------------------------------


async def test_an_idempotent_close_replay_leaves_a_terminal_outcome_untouched(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING")
    strategy_id, signal_id = await _seed(pg_session_factory, key="close-replay")
    before = await _decide(pg_session_factory, signal_id, SignalOutcome.processed())
    allocation_id = uuid4()
    context = SignalContext(
        strategy_id=strategy_id,
        symbol="STXUSDT.P",
        price=Decimal("2"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),  # long -> flat: a plain close
        prior_reservation_id=allocation_id,
        settlement_currency="USDT",
    )
    close_position = SpyClosePosition()

    async with pg_session_factory() as session:
        handler = _process_signal_handler(
            context=context,
            allocate_capital=_allocate_capital(SpyAdvisoryLock()),
            place_order=SpyPlaceOrder(),
            close_position=close_position,
            closing_attempts=FakeClosingAttemptsPort(
                latest=_existing_close(ExecutionStatus.FILLED, allocation_id)
            ),
            outcomes=SqlAlchemySignalOutcomeAdapter(session, _FixedClock()),  # type: ignore[arg-type]
            commit=session,
        )
        result = await handler.handle(signal_id)

    assert close_position.calls == []  # the replay really took the replay branch
    assert result.executed is True
    assert await _snapshot(pg_session_factory, signal_id) == before
    assert _guard_records(caplog) == []


async def test_a_failed_reverse_close_replay_keeps_the_closes_own_rejection(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The replay re-reports the failure the first attempt already recorded
    (design.md S6, "does NOT retry") and must not queue a second, different
    outcome behind the CLOSE's own code."""
    caplog.set_level("WARNING")
    strategy_id, signal_id = await _seed(pg_session_factory, key="reverse-replay")
    before = await _decide(
        pg_session_factory,
        signal_id,
        SignalOutcome.rejected("CLOSE_REJECTED_BY_VENUE", "close rejected by venue: ..."),
    )
    context = _holdable_reverse_context(symbol="STXUSDT.P")
    assert context.prior_reservation_id is not None
    close_position = SpyClosePosition()

    async with pg_session_factory() as session:
        handler = _process_signal_handler(
            context=context,
            allocate_capital=_allocate_capital(SpyAdvisoryLock()),
            place_order=SpyPlaceOrder(),
            close_position=close_position,
            closing_attempts=FakeClosingAttemptsPort(
                latest=_existing_close(ExecutionStatus.FAILED, context.prior_reservation_id)
            ),
            outcomes=SqlAlchemySignalOutcomeAdapter(session, _FixedClock()),  # type: ignore[arg-type]
            commit=session,
        )
        result = await handler.handle(signal_id)

    assert close_position.calls == []
    assert result.failed == "rejected by venue"
    assert await _snapshot(pg_session_factory, signal_id) == before
    assert _guard_records(caplog) == []


async def test_a_replayed_spot_short_reverse_repeats_its_outcome_silently(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Row 18 replayed: the redelivery finds its close already committed and
    stages the SAME REJECTED outcome, which the guard accepts as a silent
    identical repeat -- one row, unchanged, and no WARNING."""
    caplog.set_level("WARNING")
    strategy_id, signal_id = await _seed(pg_session_factory, key="spot-short")
    context = _spot_short_reverse_context()
    assert context.prior_reservation_id is not None

    async with pg_session_factory() as session:
        first = _process_signal_handler(
            context=context,
            allocate_capital=_allocate_capital(SpyAdvisoryLock()),
            place_order=SpyPlaceOrder(),
            close_position=SpyClosePosition(),
            outcomes=SqlAlchemySignalOutcomeAdapter(session, _FixedClock()),  # type: ignore[arg-type]
            commit=session,
        )
        await first.handle(signal_id)
    after_first = await _snapshot(pg_session_factory, signal_id)
    assert after_first[0] == "REJECTED"
    assert after_first[1] == "REVERSE_NEW_SIDE_UNHOLDABLE"

    replay_close = SpyClosePosition()
    async with pg_session_factory() as session:
        replay = _process_signal_handler(
            context=context,
            allocate_capital=_allocate_capital(SpyAdvisoryLock()),
            place_order=SpyPlaceOrder(),
            close_position=replay_close,
            closing_attempts=FakeClosingAttemptsPort(
                latest=_existing_close(ExecutionStatus.SUBMITTED, context.prior_reservation_id)
            ),
            outcomes=SqlAlchemySignalOutcomeAdapter(session, _FixedClock()),  # type: ignore[arg-type]
            commit=session,
        )
        await replay.handle(signal_id)

    assert replay_close.calls == []
    assert await _snapshot(pg_session_factory, signal_id) == after_first
    assert _guard_records(caplog) == []
