"""``SqlAlchemyDeliveryOutcomeAdapter`` on real PostgreSQL (tasks.md C.7, finding d;
design AD5): the outcome of a signal is per DELIVERY.

Two subscribers' deliveries of ONE signal reach their own terminal outcomes
independently; the terminal latch of ``SqlAlchemySignalOutcomeAdapter`` holds
unchanged, per delivery row; the row locked ``FOR UPDATE`` is the delivery's, never
the signal's; and the signal's own outcome columns are not written.
"""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow, SignalRow
from strategy_manager.signals.infrastructure.outcome_repository import (
    SqlAlchemyDeliveryOutcomeAdapter,
    SqlAlchemySignalOutcomeAdapter,
)
from tests.owner import ensure_delivery, seed_other_user
from tests.signals.infrastructure.conftest import seed_signal_row, seed_strategy

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)
_GUARD_LOGGER = "strategy_manager.signals.infrastructure.outcome_repository"


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


async def _two_deliveries(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID, UUID]:
    """One signal delivered to two different users. Returns (signal, first, second)."""
    strategy_id, signal_id = uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await seed_signal_row(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    async with factory() as session:
        other = await seed_other_user(session)
        first = await ensure_delivery(session, signal_id=signal_id, strategy_id=strategy_id)
        second = await ensure_delivery(
            session, signal_id=signal_id, strategy_id=strategy_id, user_id=other
        )
        await session.commit()
    return signal_id, first, second


async def _delivery(
    factory: async_sessionmaker[AsyncSession], delivery_id: UUID
) -> SignalDeliveryRow:
    async with factory() as session:
        return (
            await session.execute(
                select(SignalDeliveryRow).where(SignalDeliveryRow.id == delivery_id)
            )
        ).scalar_one()


async def _signal(factory: async_sessionmaker[AsyncSession], signal_id: UUID) -> SignalRow:
    async with factory() as session:
        return (
            await session.execute(select(SignalRow).where(SignalRow.id == signal_id))
        ).scalar_one()


async def _record(
    factory: async_sessionmaker[AsyncSession], delivery_id: UUID, outcome: SignalOutcome
) -> None:
    async with factory() as session:
        await SqlAlchemyDeliveryOutcomeAdapter(session, _FixedClock()).record(
            delivery_id, outcome
        )
        await session.commit()


async def test_two_deliveries_of_one_signal_record_their_outcomes_independently(
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    signal_id, first, second = await _two_deliveries(pg_session_factory)

    await _record(pg_session_factory, first, SignalOutcome.processed())
    await _record(
        pg_session_factory, second, SignalOutcome.rejected("PAIR_NOT_ALLOWED", "not listed")
    )

    one = await _delivery(pg_session_factory, first)
    two = await _delivery(pg_session_factory, second)
    assert (one.status, one.outcome_reason, one.decided_at) == ("PROCESSED", None, _NOW)
    assert (two.status, two.outcome_reason, two.outcome_detail) == (
        "REJECTED",
        "PAIR_NOT_ALLOWED",
        "not listed",
    )
    # The first one's terminal outcome neither blocked nor warned about the second.
    assert [r for r in caplog.records if r.name == _GUARD_LOGGER] == []
    # The signal's own columns were never written.
    signal = await _signal(pg_session_factory, signal_id)
    assert (signal.status, signal.outcome_reason, signal.outcome_detail, signal.decided_at) == (
        "ACCEPTED",
        None,
        None,
        None,
    )


async def test_a_terminal_delivery_is_never_overwritten_and_warns_naming_both_ids(
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    signal_id, first, second = await _two_deliveries(pg_session_factory)
    await _record(pg_session_factory, first, SignalOutcome.processed())

    await _record(pg_session_factory, first, SignalOutcome.rejected("LATE", "too late"))

    held = await _delivery(pg_session_factory, first)
    assert (held.status, held.outcome_reason) == ("PROCESSED", None)
    [record] = [r for r in caplog.records if r.name == _GUARD_LOGGER]
    assert str(first) in record.getMessage() and str(signal_id) in record.getMessage()
    assert str(second) not in record.getMessage()
    assert (await _delivery(pg_session_factory, second)).status == "ACCEPTED"


async def test_an_identical_repeat_on_a_terminal_delivery_is_silent(
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    _, first, _ = await _two_deliveries(pg_session_factory)
    await _record(pg_session_factory, first, SignalOutcome.processed())

    await _record(pg_session_factory, first, SignalOutcome.processed())

    assert [r for r in caplog.records if r.name == _GUARD_LOGGER] == []


async def test_record_unless_terminal_leaves_a_terminal_delivery_alone_silently(
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    _, first, second = await _two_deliveries(pg_session_factory)
    await _record(pg_session_factory, first, SignalOutcome.processed())

    async with pg_session_factory() as session:
        adapter = SqlAlchemyDeliveryOutcomeAdapter(session, _FixedClock())
        await adapter.record_unless_terminal(first, SignalOutcome.rejected("JOB_FAILED", "x"))
        await adapter.record_unless_terminal(second, SignalOutcome.rejected("JOB_FAILED", "x"))
        await session.commit()

    assert (await _delivery(pg_session_factory, first)).status == "PROCESSED"
    assert (await _delivery(pg_session_factory, second)).status == "REJECTED"
    assert [r for r in caplog.records if r.name == _GUARD_LOGGER] == []


async def test_an_unknown_delivery_is_loud(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        with pytest.raises(InvariantViolation, match="unknown delivery"):
            await SqlAlchemyDeliveryOutcomeAdapter(session, _FixedClock()).record(
                uuid4(), SignalOutcome.processed()
            )


async def test_the_adapter_never_commits_a_rollback_discards_the_write(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, first, _ = await _two_deliveries(pg_session_factory)

    async with pg_session_factory() as session:
        await SqlAlchemyDeliveryOutcomeAdapter(session, _FixedClock()).record(
            first, SignalOutcome.processed()
        )
        await session.rollback()

    assert (await _delivery(pg_session_factory, first)).status == "ACCEPTED"


async def test_writing_one_delivery_does_not_wait_for_a_writer_holding_another(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The lock is the DELIVERY's row: B holds the first delivery's row locked, and
    a write on the second delivery of the SAME signal completes at once (it would
    wait if the signal's row were the one locked)."""
    _, first, second = await _two_deliveries(pg_session_factory)

    async with pg_session_factory() as session_b, pg_session_factory() as session_a:
        await SqlAlchemyDeliveryOutcomeAdapter(session_b, _FixedClock()).record(
            first, SignalOutcome.processing()
        )

        async def _a_writes() -> None:
            await SqlAlchemyDeliveryOutcomeAdapter(session_a, _FixedClock()).record(
                second, SignalOutcome.processed()
            )
            await session_a.commit()

        await asyncio.wait_for(_a_writes(), timeout=5)
        await session_b.commit()

    assert (await _delivery(pg_session_factory, second)).status == "PROCESSED"
    assert (await _delivery(pg_session_factory, first)).status == "PROCESSING"


async def test_a_second_writer_on_the_same_delivery_waits_for_the_first(
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    """Lock-hold harness: B keeps its transaction open on the delivery row; A's
    write on the SAME delivery must wait (``not task.done()`` after a real delay),
    then finds the delivery terminal and refuses to overwrite it."""
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    _, first, _ = await _two_deliveries(pg_session_factory)

    async with pg_session_factory() as session_b, pg_session_factory() as session_a:
        await SqlAlchemyDeliveryOutcomeAdapter(session_b, _FixedClock()).record(
            first, SignalOutcome.processed()
        )

        async def _a_writes() -> None:
            await SqlAlchemyDeliveryOutcomeAdapter(session_a, _FixedClock()).record(
                first, SignalOutcome.rejected("LATE", "a waited")
            )
            await session_a.commit()

        task = asyncio.create_task(_a_writes())
        await asyncio.sleep(0.5)
        assert not task.done(), "the write must block on the delivery row B holds locked"

        await session_b.commit()
        await asyncio.wait_for(task, timeout=10)

    assert (await _delivery(pg_session_factory, first)).status == "PROCESSED"
    assert len([r for r in caplog.records if r.name == _GUARD_LOGGER]) == 1


async def test_the_signal_adapter_still_writes_only_the_signals_row(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The strategy-level refusals (a fan-out that reached no delivery) keep the
    signal's own row: the signal adapter writes it and no delivery."""
    signal_id, first, second = await _two_deliveries(pg_session_factory)

    async with pg_session_factory() as session:
        await SqlAlchemySignalOutcomeAdapter(session, _FixedClock()).record(
            signal_id, SignalOutcome.rejected("STRATEGY_ARCHIVED", "archived")
        )
        await session.commit()

    signal = await _signal(pg_session_factory, signal_id)
    assert (signal.status, signal.outcome_reason) == ("REJECTED", "STRATEGY_ARCHIVED")
    assert (await _delivery(pg_session_factory, first)).status == "ACCEPTED"
    assert (await _delivery(pg_session_factory, second)).status == "ACCEPTED"
