"""Integration tests against a real PostgreSQL database for
``SqlAlchemySignalOutcomeAdapter.record_unless_terminal`` (decision 25, PR 5c
unit G; design.md § E): the explicit, tested NON-WARNING path.

The terminal guard in ``record`` warns on a DIFFERENT second outcome, because
that is how a genuine conflict (two writers deciding one signal differently)
shows up. A continuation abandoning a signal that already ended, or a job
that exhausted its retries after the signal was decided, is not a conflict, it
is the ordinary case -- and routing it through ``record`` would put a WARNING
on every one, defeating the WARNING. So those writers use this method, and
``settle`` / ``signal.process`` keep ``record`` and keep warning; both sides
are asserted here.
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

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

_NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


def _adapter(session: AsyncSession) -> SqlAlchemySignalOutcomeAdapter:
    return SqlAlchemySignalOutcomeAdapter(session, _FixedClock())


async def _row(factory: async_sessionmaker[AsyncSession], signal_id: UUID) -> SignalRow:
    async with factory() as session:
        return (
            await session.execute(select(SignalRow).where(SignalRow.id == signal_id))
        ).scalar_one()


async def _seed(
    factory: async_sessionmaker[AsyncSession], key: str, held: SignalOutcome | None = None
) -> UUID:
    strategy_id, signal_id = uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await seed_signal_row(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=key
    )
    if held is not None:
        async with factory() as session:
            await _adapter(session).record(signal_id, held)
            await session.commit()
    return signal_id


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]


@pytest.mark.parametrize(
    "held",
    [
        SignalOutcome.processed(),
        SignalOutcome.rejected("CLOSE_REJECTED_BY_VENUE", "the close was refused"),
    ],
    ids=["processed", "rejected"],
)
async def test_a_terminal_signal_is_left_alone_without_a_warning(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
    held: SignalOutcome,
) -> None:
    signal_id = await _seed(pg_session_factory, "u1", held)

    async with pg_session_factory() as session:
        with caplog.at_level("WARNING"):
            await _adapter(session).record_unless_terminal(
                signal_id, SignalOutcome.rejected("AWAITED_CLOSE_FAILED", "later, differing")
            )
        await session.commit()

    assert _warnings(caplog) == []
    row = await _row(pg_session_factory, signal_id)
    assert (row.status, row.outcome_reason, row.outcome_detail) == (
        held.status.value,
        held.reason,
        held.detail,
    )


@pytest.mark.parametrize("interim", ["ACCEPTED", "PROCESSING"])
async def test_a_non_terminal_signal_is_written(
    pg_session_factory: async_sessionmaker[AsyncSession], interim: str
) -> None:
    held = SignalOutcome.processing() if interim == "PROCESSING" else None
    signal_id = await _seed(pg_session_factory, "u2", held)

    async with pg_session_factory() as session:
        await _adapter(session).record_unless_terminal(
            signal_id, SignalOutcome.rejected("SIGNAL_SUPERSEDED", "a newer signal")
        )
        await session.commit()

    row = await _row(pg_session_factory, signal_id)
    assert (row.status, row.outcome_reason, row.outcome_detail, row.decided_at) == (
        "REJECTED",
        "SIGNAL_SUPERSEDED",
        "a newer signal",
        _NOW,
    )


async def test_a_conflicting_record_still_warns_where_this_path_stayed_silent(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both sides on ONE terminal row: the silent path is a separate entry
    point, not a loophole in the guard."""
    signal_id = await _seed(
        pg_session_factory, "u3", SignalOutcome.rejected("CLOSE_DUST_NOT_CLOSABLE", "dust")
    )

    async with pg_session_factory() as session:
        adapter = _adapter(session)
        with caplog.at_level("WARNING"):
            await adapter.record_unless_terminal(
                signal_id, SignalOutcome.rejected("CONTINUATION_TIMED_OUT", "late")
            )
            assert _warnings(caplog) == []
            await adapter.record(signal_id, SignalOutcome.processed())
        await session.commit()

    assert len(_warnings(caplog)) == 1
    row = await _row(pg_session_factory, signal_id)
    assert (row.status, row.outcome_reason) == ("REJECTED", "CLOSE_DUST_NOT_CLOSABLE")


async def test_an_unknown_signal_raises(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        with pytest.raises(InvariantViolation):
            await _adapter(session).record_unless_terminal(uuid4(), SignalOutcome.processed())


async def test_it_waits_for_a_concurrent_writer_holding_the_signal_row(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Lock-hold harness: B has decided the signal and keeps its transaction
    open. A must WAIT (``not task.done()`` after a real delay) and, once B
    commits, find the signal terminal and stay silent -- so the read that
    decides "terminal or not" is the fresh, locked one."""
    signal_id = await _seed(pg_session_factory, "u4")

    async with pg_session_factory() as session_b, pg_session_factory() as session_a:
        await _adapter(session_b).record(
            signal_id, SignalOutcome.rejected("PAIR_NOT_ALLOWED", "b holds the lock")
        )

        async def _a_records() -> None:
            await _adapter(session_a).record_unless_terminal(
                signal_id, SignalOutcome.rejected("JOB_FAILED", "a waited")
            )
            await session_a.commit()

        with caplog.at_level("WARNING"):
            task = asyncio.create_task(_a_records())
            await asyncio.sleep(0.5)
            assert not task.done(), "A must block on the row B holds locked"

            await session_b.commit()
            await asyncio.wait_for(task, timeout=10)

    assert _warnings(caplog) == []
    row = await _row(pg_session_factory, signal_id)
    assert (row.status, row.outcome_reason) == ("REJECTED", "PAIR_NOT_ALLOWED")
