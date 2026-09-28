"""Integration tests against a real PostgreSQL database (strategy_manager_test)
for ``SqlAlchemySignalOutcomeAdapter`` (decision 25, design.md "Addendum:
signal outcomes (decision 25)" § A, § D; tasks.md PR 5b, task 5b.3).

Covers the terminal-state guard (a differing second outcome for an
already-terminal signal is a no-op that logs exactly one WARNING; an
identical repeat is a silent no-op; ``PROCESSING`` over ``PROCESSING`` is
not a terminal write and always succeeds) and the same-commit rule (the
adapter never commits -- a caller's rollback discards the write).
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.outcome_repository import (
    SqlAlchemySignalOutcomeAdapter,
)
from tests.signals.infrastructure.conftest import seed_signal_row, seed_strategy

pytestmark = pytest.mark.integration


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


_NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)


async def _row(session_factory: async_sessionmaker[AsyncSession], signal_id: object) -> SignalRow:
    async with session_factory() as session:
        row = (
            await session.execute(select(SignalRow).where(SignalRow.id == signal_id))
        ).scalar_one()
        return row


async def test_record_processing_writes_status_with_no_decided_at(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    signal_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
        pg_session_factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key="k1"
    )

    async with pg_session_factory() as session:
        adapter = SqlAlchemySignalOutcomeAdapter(session, _FixedClock(_NOW))
        await adapter.record(signal_id, SignalOutcome.processing())
        await session.commit()

    row = await _row(pg_session_factory, signal_id)
    assert row.status == "PROCESSING"
    assert row.decided_at is None
    assert row.outcome_reason is None


async def test_record_processed_sets_decided_at(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    signal_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
        pg_session_factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key="k2"
    )

    async with pg_session_factory() as session:
        adapter = SqlAlchemySignalOutcomeAdapter(session, _FixedClock(_NOW))
        await adapter.record(signal_id, SignalOutcome.processed())
        await session.commit()

    row = await _row(pg_session_factory, signal_id)
    assert row.status == "PROCESSED"
    assert row.decided_at == _NOW


async def test_record_rejected_sets_reason_detail_and_decided_at(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    signal_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
        pg_session_factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key="k3"
    )

    async with pg_session_factory() as session:
        adapter = SqlAlchemySignalOutcomeAdapter(session, _FixedClock(_NOW))
        await adapter.record(
            signal_id, SignalOutcome.rejected("UNTRADABLE_POOL", "no key stored")
        )
        await session.commit()

    row = await _row(pg_session_factory, signal_id)
    assert row.status == "REJECTED"
    assert row.outcome_reason == "UNTRADABLE_POOL"
    assert row.outcome_detail == "no key stored"
    assert row.decided_at == _NOW


async def test_record_does_not_commit_a_rollback_discards_the_write(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The same-commit rule (design.md § C): the adapter stages the write on
    the caller's session and never commits it itself. A caller that rolls
    back (as any use case does on a failed downstream step) must lose the
    outcome write along with everything else in that unit of work."""
    strategy_id = uuid4()
    signal_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
        pg_session_factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key="k4"
    )

    async with pg_session_factory() as session:
        adapter = SqlAlchemySignalOutcomeAdapter(session, _FixedClock(_NOW))
        await adapter.record(signal_id, SignalOutcome.processed())
        await session.rollback()  # never committed

    row = await _row(pg_session_factory, signal_id)
    assert row.status == "ACCEPTED"
    assert row.decided_at is None


async def test_processing_over_processing_is_idempotent_and_succeeds(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    signal_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
        pg_session_factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key="k5"
    )

    async with pg_session_factory() as session:
        adapter = SqlAlchemySignalOutcomeAdapter(session, _FixedClock(_NOW))
        await adapter.record(signal_id, SignalOutcome.processing())
        await adapter.record(signal_id, SignalOutcome.processing())
        await session.commit()

    row = await _row(pg_session_factory, signal_id)
    assert row.status == "PROCESSING"


async def test_differing_second_outcome_for_terminal_signal_is_noop_and_logs_one_warning(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = uuid4()
    signal_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
        pg_session_factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key="k6"
    )

    async with pg_session_factory() as session:
        adapter = SqlAlchemySignalOutcomeAdapter(session, _FixedClock(_NOW))
        await adapter.record(signal_id, SignalOutcome.processed())
        await session.commit()

    async with pg_session_factory() as session:
        adapter = SqlAlchemySignalOutcomeAdapter(session, _FixedClock(_NOW))
        with caplog.at_level("WARNING"):
            await adapter.record(
                signal_id, SignalOutcome.rejected("UNTRADABLE_POOL", "refused later")
            )
        await session.commit()

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert str(signal_id) in message
    assert "PROCESSED" in message
    assert "REJECTED" in message

    row = await _row(pg_session_factory, signal_id)
    assert row.status == "PROCESSED"  # unchanged: the terminal write refused
    assert row.outcome_reason is None


async def test_identical_repeat_for_terminal_signal_is_silent_noop(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = uuid4()
    signal_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
        pg_session_factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key="k7"
    )
    outcome = SignalOutcome.rejected("UNTRADABLE_POOL", "no key stored")

    async with pg_session_factory() as session:
        adapter = SqlAlchemySignalOutcomeAdapter(session, _FixedClock(_NOW))
        await adapter.record(signal_id, outcome)
        await session.commit()

    async with pg_session_factory() as session:
        adapter = SqlAlchemySignalOutcomeAdapter(session, _FixedClock(_NOW))
        with caplog.at_level("WARNING"):
            await adapter.record(signal_id, outcome)  # identical repeat
        await session.commit()

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings == []

    row = await _row(pg_session_factory, signal_id)
    assert row.status == "REJECTED"
    assert row.outcome_reason == "UNTRADABLE_POOL"


async def test_record_against_unknown_signal_raises_invariant_violation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        adapter = SqlAlchemySignalOutcomeAdapter(session, _FixedClock(_NOW))
        with pytest.raises(InvariantViolation):
            await adapter.record(uuid4(), SignalOutcome.processed())
