"""``ExhaustedJobSignalRecorder`` (decision 25, task 5c.6), with fakes: what a
job that spent its last attempt writes to its signal, and what it must never
write.

``jobs.last_error`` becomes PANEL-VISIBLE data here, so the detail is bounded
and redacted on the way in and gains nothing on the way (no job id, no payload).
"""

from uuid import UUID, uuid4

import pytest

from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.infrastructure.exhausted_job_recorder import (
    MAX_DETAIL_CHARS,
    ExhaustedJobSignalRecorder,
)
from tests.signals.fakes import RecordingSignalOutcomes


class _Reader:
    def __init__(self, signal_id: UUID | None) -> None:
        self._signal_id = signal_id
        self.seen: list[ClaimedJob] = []

    async def signal_for(self, job: ClaimedJob) -> UUID | None:
        self.seen.append(job)
        return self._signal_id


def _job(kind: JobKind = JobKind.SIGNAL_PROCESS) -> ClaimedJob:
    return ClaimedJob(id=uuid4(), kind=kind, payload={"x": 1}, attempts=5, max_attempts=5)


def _recorder(
    signal_id: UUID | None,
) -> tuple[ExhaustedJobSignalRecorder, RecordingSignalOutcomes, _Reader]:
    outcomes = RecordingSignalOutcomes()
    reader = _Reader(signal_id)
    return ExhaustedJobSignalRecorder(outcomes, reader), outcomes, reader


@pytest.mark.parametrize(
    "kind",
    [JobKind.SIGNAL_PROCESS, JobKind.SIGNAL_OPEN_AFTER_CLOSE, JobKind.EXECUTION_SETTLE],
)
async def test_an_exhausted_job_rejects_its_signal_with_the_last_error(kind: JobKind) -> None:
    signal_id = uuid4()
    recorder, outcomes, reader = _recorder(signal_id)
    job = _job(kind)

    await recorder.on_exhausted(job, "the venue timed out")

    assert reader.seen == [job]
    assert outcomes.unless_terminal_calls == [
        (signal_id, SignalOutcome.rejected("JOB_FAILED", "the venue timed out"))
    ]


async def test_the_silent_path_is_used_never_the_warning_one() -> None:
    """The signal may already be decided; that is not a conflict."""
    recorder, outcomes, _ = _recorder(uuid4())

    await recorder.on_exhausted(_job(), "boom")

    assert outcomes.calls == []
    assert len(outcomes.unless_terminal_calls) == 1


async def test_a_job_with_no_signal_writes_nothing() -> None:
    recorder, outcomes, _ = _recorder(None)

    await recorder.on_exhausted(_job(), "boom")

    assert outcomes.calls == [] and outcomes.unless_terminal_calls == []


async def test_the_detail_is_truncated_to_the_bound() -> None:
    recorder, outcomes, _ = _recorder(uuid4())

    await recorder.on_exhausted(_job(), "x" * (MAX_DETAIL_CHARS * 4))

    assert len(outcomes.unless_terminal_calls) == 1
    [(_, outcome)] = outcomes.unless_terminal_calls
    assert outcome.detail is not None
    assert len(outcome.detail) == MAX_DETAIL_CHARS
    assert outcome.detail.endswith("…")


async def test_a_message_within_the_bound_is_recorded_verbatim() -> None:
    recorder, outcomes, _ = _recorder(uuid4())
    message = "y" * MAX_DETAIL_CHARS

    await recorder.on_exhausted(_job(), message)

    assert len(outcomes.unless_terminal_calls) == 1
    [(_, outcome)] = outcomes.unless_terminal_calls
    assert outcome.detail == message


@pytest.mark.parametrize(
    ("leaky", "secret"),
    [
        ("connect failed for postgresql://app:hunter2@db.internal:5432/strategy", "hunter2"),
        ("GET /v5/order failed: api_key=AKIA123456 rejected", "AKIA123456"),
        ("signed call https://api.bybit.com/v5/order?api_key=K&sign=S1G failed", "S1G"),
    ],
    ids=["dsn", "named-secret", "signed-url-query"],
)
async def test_credentials_are_redacted_before_the_detail_reaches_the_panel(
    leaky: str, secret: str
) -> None:
    recorder, outcomes, _ = _recorder(uuid4())

    await recorder.on_exhausted(_job(), leaky)

    assert len(outcomes.unless_terminal_calls) == 1
    [(_, outcome)] = outcomes.unless_terminal_calls
    assert outcome.detail is not None
    assert secret not in outcome.detail
    assert "REDACTED" in outcome.detail


async def test_the_detail_adds_nothing_to_the_error() -> None:
    """No job id, no payload, no attempt count: the panel shows the error and
    nothing the error did not already say."""
    recorder, outcomes, _ = _recorder(uuid4())
    job = _job()

    await recorder.on_exhausted(job, "boom")

    assert len(outcomes.unless_terminal_calls) == 1
    [(_, outcome)] = outcomes.unless_terminal_calls
    assert outcome.detail == "boom"
    assert str(job.id) not in (outcome.detail or "")


async def test_an_empty_error_still_ends_the_signal() -> None:
    """``SignalOutcome.rejected`` needs a reason, not a detail, but an empty
    detail would be a blank panel cell: it is recorded as ``None``."""
    recorder, outcomes, _ = _recorder(uuid4())

    await recorder.on_exhausted(_job(), "")

    assert len(outcomes.unless_terminal_calls) == 1
    [(_, outcome)] = outcomes.unless_terminal_calls
    assert outcome.status.value == "REJECTED" and outcome.reason == "JOB_FAILED"
    assert outcome.detail is None
