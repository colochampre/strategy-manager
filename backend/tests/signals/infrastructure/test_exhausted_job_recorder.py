"""``ExhaustedJobSignalRecorder`` (decision 25, task 5c.6; tasks.md C.7), with
fakes: what a job that spent its last attempt writes to what it was working on, and
what it must never write.

A job that worked a DELIVERY ends that delivery; a fan-out (``signal.process``)
worked the SIGNAL itself and ends the signal's row. Each target reaches only its
own port.

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
    FailedJobTarget,
)
from tests.signals.fakes import RecordingSignalOutcomes


class _Reader:
    def __init__(self, target: FailedJobTarget | None) -> None:
        self._target = target
        self.seen: list[ClaimedJob] = []

    async def target_for(self, job: ClaimedJob) -> FailedJobTarget | None:
        self.seen.append(job)
        return self._target


def _job(kind: JobKind = JobKind.DELIVERY_PROCESS) -> ClaimedJob:
    return ClaimedJob(id=uuid4(), kind=kind, payload={"x": 1}, attempts=5, max_attempts=5)


def _recorder(
    delivery_id: UUID | None,
) -> tuple[
    ExhaustedJobSignalRecorder, RecordingSignalOutcomes, RecordingSignalOutcomes, _Reader
]:
    """A recorder whose job worked ``delivery_id`` (``None``: nothing)."""
    signal_outcomes = RecordingSignalOutcomes()
    delivery_outcomes = RecordingSignalOutcomes()
    target = None if delivery_id is None else FailedJobTarget(delivery_id=delivery_id)
    reader = _Reader(target)
    recorder = ExhaustedJobSignalRecorder(signal_outcomes, delivery_outcomes, reader)
    return recorder, signal_outcomes, delivery_outcomes, reader


@pytest.mark.parametrize(
    "kind",
    [JobKind.DELIVERY_PROCESS, JobKind.SIGNAL_OPEN_AFTER_CLOSE, JobKind.EXECUTION_SETTLE],
)
async def test_an_exhausted_job_rejects_its_delivery_with_the_last_error(
    kind: JobKind,
) -> None:
    delivery_id = uuid4()
    recorder, signal_outcomes, delivery_outcomes, reader = _recorder(delivery_id)
    job = _job(kind)

    await recorder.on_exhausted(job, "the venue timed out")

    assert reader.seen == [job]
    assert delivery_outcomes.unless_terminal_calls == [
        (delivery_id, SignalOutcome.rejected("JOB_FAILED", "the venue timed out"))
    ]
    assert signal_outcomes.calls == [] and signal_outcomes.unless_terminal_calls == []


async def test_an_exhausted_fan_out_rejects_its_signal_and_no_delivery() -> None:
    """``signal.process`` works the signal itself: no delivery exists to hold the
    outcome, so it lands on the signal's row (decision: strategy-level refusals)."""
    signal_id = uuid4()
    signal_outcomes = RecordingSignalOutcomes()
    delivery_outcomes = RecordingSignalOutcomes()
    recorder = ExhaustedJobSignalRecorder(
        signal_outcomes,
        delivery_outcomes,
        _Reader(FailedJobTarget(signal_id=signal_id)),
    )

    await recorder.on_exhausted(_job(JobKind.SIGNAL_PROCESS), "boom")

    assert signal_outcomes.unless_terminal_calls == [
        (signal_id, SignalOutcome.rejected("JOB_FAILED", "boom"))
    ]
    assert delivery_outcomes.calls == [] and delivery_outcomes.unless_terminal_calls == []


def test_a_target_names_exactly_one_of_a_delivery_or_a_signal() -> None:
    with pytest.raises(ValueError):
        FailedJobTarget()
    with pytest.raises(ValueError):
        FailedJobTarget(delivery_id=uuid4(), signal_id=uuid4())


async def test_the_silent_path_is_used_never_the_warning_one() -> None:
    """The delivery may already be decided; that is not a conflict."""
    recorder, _, delivery_outcomes, _ = _recorder(uuid4())

    await recorder.on_exhausted(_job(), "boom")

    assert delivery_outcomes.calls == []
    assert len(delivery_outcomes.unless_terminal_calls) == 1


async def test_a_job_with_no_target_writes_nothing() -> None:
    recorder, signal_outcomes, delivery_outcomes, _ = _recorder(None)

    await recorder.on_exhausted(_job(), "boom")

    for outcomes in (signal_outcomes, delivery_outcomes):
        assert outcomes.calls == [] and outcomes.unless_terminal_calls == []


async def test_the_detail_is_truncated_to_the_bound() -> None:
    recorder, _, outcomes, _ = _recorder(uuid4())

    await recorder.on_exhausted(_job(), "x" * (MAX_DETAIL_CHARS * 4))

    assert len(outcomes.unless_terminal_calls) == 1
    [(_, outcome)] = outcomes.unless_terminal_calls
    assert outcome.detail is not None
    assert len(outcome.detail) == MAX_DETAIL_CHARS
    assert outcome.detail.endswith("…")


async def test_a_message_within_the_bound_is_recorded_verbatim() -> None:
    recorder, _, outcomes, _ = _recorder(uuid4())
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
    recorder, _, outcomes, _ = _recorder(uuid4())

    await recorder.on_exhausted(_job(), leaky)

    assert len(outcomes.unless_terminal_calls) == 1
    [(_, outcome)] = outcomes.unless_terminal_calls
    assert outcome.detail is not None
    assert secret not in outcome.detail
    assert "REDACTED" in outcome.detail


async def test_the_detail_adds_nothing_to_the_error() -> None:
    """No job id, no payload, no attempt count: the panel shows the error and
    nothing the error did not already say."""
    recorder, _, outcomes, _ = _recorder(uuid4())
    job = _job()

    await recorder.on_exhausted(job, "boom")

    assert len(outcomes.unless_terminal_calls) == 1
    [(_, outcome)] = outcomes.unless_terminal_calls
    assert outcome.detail == "boom"
    assert str(job.id) not in (outcome.detail or "")


async def test_an_empty_error_still_ends_the_delivery() -> None:
    """``SignalOutcome.rejected`` needs a reason, not a detail, but an empty
    detail would be a blank panel cell: it is recorded as ``None``."""
    recorder, _, outcomes, _ = _recorder(uuid4())

    await recorder.on_exhausted(_job(), "")

    assert len(outcomes.unless_terminal_calls) == 1
    [(_, outcome)] = outcomes.unless_terminal_calls
    assert outcome.status.value == "REJECTED" and outcome.reason == "JOB_FAILED"
    assert outcome.detail is None
