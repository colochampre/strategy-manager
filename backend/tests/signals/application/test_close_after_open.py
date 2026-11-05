"""``CloseAfterOpen``: what a close does about the opening it unwinds (G.6's design)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from strategy_manager.execution.domain.execution_attempt import ExecutionStatus
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.config import Settings
from strategy_manager.signals.application.close_after_open import (
    CloseAfterOpen,
    CloseStep,
    OpeningState,
    next_close_step,
)
from strategy_manager.signals.application.fan_out_signal import DeliveryHalves

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
TIMEOUT = 600.0
POLL_INTERVAL = 5.0


def _opening(
    status: ExecutionStatus, *, age: float = 10.0, booked: bool = False
) -> OpeningState:
    return OpeningState(status=status, created_at=NOW - timedelta(seconds=age), booked=booked)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        # Nothing to wait for: the close goes on, and decides for itself.
        (None, CloseStep.PROCEED),
        (_opening(ExecutionStatus.FILLED), CloseStep.PROCEED),
        # The ledger is the fact: a row booked is a position, whatever the attempt says.
        (_opening(ExecutionStatus.SUBMITTED, booked=True), CloseStep.PROCEED),
        (_opening(ExecutionStatus.FAILED, booked=True), CloseStep.PROCEED),
        (_opening(ExecutionStatus.SUBMITTED), CloseStep.WAIT),
        (_opening(ExecutionStatus.SUBMITTED, age=TIMEOUT - 0.001), CloseStep.WAIT),
        (_opening(ExecutionStatus.SUBMITTED, age=TIMEOUT), CloseStep.TIMED_OUT),
        (_opening(ExecutionStatus.SUBMITTED, age=TIMEOUT + 1), CloseStep.TIMED_OUT),
        # A final attempt that booked nothing opened nothing, however old it is.
        (_opening(ExecutionStatus.FAILED), CloseStep.NOTHING_OPENED),
        (_opening(ExecutionStatus.FAILED, age=TIMEOUT + 1), CloseStep.NOTHING_OPENED),
        (_opening(ExecutionStatus.ABORTED_EXPIRED), CloseStep.NOTHING_OPENED),
    ],
)
def test_the_next_step_of_a_close(state: OpeningState | None, expected: CloseStep) -> None:
    assert next_close_step(state, NOW, TIMEOUT) is expected


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Queue:
    def __init__(self) -> None:
        self.jobs: list[Job] = []

    async def enqueue(self, job: Job) -> None:
        self.jobs.append(job)

    async def enqueue_unique(self, job: Job) -> tuple[object, bool]:
        self.jobs.append(job)
        return uuid4(), True


class _Openings:
    def __init__(self, state: OpeningState | None) -> None:
        self.state = state
        self.asked: list[tuple[object, object]] = []

    async def opening_state(self, user_id: object, allocation_id: object) -> OpeningState | None:
        self.asked.append((user_id, allocation_id))
        return self.state


def _use_case(state: OpeningState | None = None) -> tuple[CloseAfterOpen, _Queue, _Openings]:
    queue = _Queue()
    openings = _Openings(state)
    use_case = CloseAfterOpen(
        openings=openings,  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
        clock=_Clock(),
        timeout_seconds=TIMEOUT,
        poll_interval_seconds=POLL_INTERVAL,
    )
    return use_case, queue, openings


async def test_a_step_reads_this_users_allocation_at_the_clocks_now() -> None:
    user_id, allocation_id = uuid4(), uuid4()
    use_case, _, openings = _use_case(_opening(ExecutionStatus.SUBMITTED, age=TIMEOUT))

    assert await use_case.step(user_id, allocation_id) is CloseStep.TIMED_OUT
    assert openings.asked == [(user_id, allocation_id)]


async def test_a_step_is_bounded_by_the_timeout_it_was_given() -> None:
    use_case, _, _ = _use_case(_opening(ExecutionStatus.SUBMITTED, age=TIMEOUT - 1))

    assert await use_case.step(uuid4(), uuid4()) is CloseStep.WAIT


async def test_the_next_poll_is_the_same_delivery_one_interval_on() -> None:
    delivery_id = uuid4()
    use_case, queue, _ = _use_case()

    await use_case.seed(delivery_id, DeliveryHalves.BOTH, 3)

    assert queue.jobs == [
        Job(
            kind=JobKind.DELIVERY_PROCESS,
            payload={"delivery_id": str(delivery_id), "halves": "close_and_open", "poll": 3},
            run_after=NOW + timedelta(seconds=POLL_INTERVAL),
            dedupe_key=f"delivery:{delivery_id}:after-opening:3",
        )
    ]


def test_the_bound_outlasts_the_settle_job() -> None:
    """The close must not give up on an opening that is still going to fill: the
    settle job's last attempt runs after its first delay and every backoff wait."""
    fields = Settings.model_fields
    base = fields["job_retry_backoff_base_seconds"].default
    ceiling = fields["job_retry_backoff_max_seconds"].default
    attempts = Job(kind=JobKind.EXECUTION_SETTLE, payload={}).max_attempts
    waits = sum(min(base * 2**n, ceiling) for n in range(attempts - 1))
    settle_job = fields["execution_settle_delay_seconds"].default + waits

    assert settle_job == 452.0
    assert fields["close_after_open_timeout_seconds"].default > settle_job
