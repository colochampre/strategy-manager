from datetime import UTC, datetime
from uuid import uuid4

from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind


def test_job_kind_values_match_the_job_handler_names() -> None:
    assert JobKind.SIGNAL_PROCESS == "signal.process"
    assert JobKind.RESERVATION_SWEEP == "reservation.sweep"
    assert JobKind.RECONCILIATION_SCAN == "reconciliation.scan"


def test_job_kind_open_after_close_matches_the_continuation_handler_name() -> None:
    """design.md § S5: the continuation that opens a signal's position only
    after every close it awaits has settled FILLED."""

    assert JobKind.SIGNAL_OPEN_AFTER_CLOSE == "signal.open_after_close"


def test_job_defaults_run_after_none_and_max_attempts_five() -> None:
    job = Job(kind=JobKind.SIGNAL_PROCESS, payload={"signal_id": "abc"})

    assert job.run_after is None
    assert job.max_attempts == 5
    assert job.dedupe_key is None


def test_job_accepts_explicit_scheduling_fields() -> None:
    run_after = datetime(2026, 1, 1, tzinfo=UTC)

    job = Job(
        kind=JobKind.RESERVATION_SWEEP,
        payload={},
        run_after=run_after,
        max_attempts=1,
        dedupe_key="sweep-once",
    )

    assert job.run_after == run_after
    assert job.max_attempts == 1
    assert job.dedupe_key == "sweep-once"


def test_claimed_job_carries_attempt_bookkeeping() -> None:
    job_id = uuid4()

    claimed = ClaimedJob(
        id=job_id,
        kind=JobKind.SIGNAL_PROCESS,
        payload={"signal_id": "abc"},
        attempts=1,
        max_attempts=5,
    )

    assert claimed.id == job_id
    assert claimed.kind is JobKind.SIGNAL_PROCESS
    assert claimed.payload == {"signal_id": "abc"}
    assert claimed.attempts == 1
