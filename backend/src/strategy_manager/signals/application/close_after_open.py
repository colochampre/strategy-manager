"""``CloseAfterOpen``: a close whose opening is still in flight waits for it.

An opening's fills, its attempt's ``FILLED`` and its reservation's ``FILLED`` land
together, and an order the venue knows with no fills published yet is retried on the
job backoff, so an opening can stay ``SUBMITTED`` for minutes, well past its
reservation's TTL. A close arriving then has nothing to act on yet, and the fill that
lands later is a position the strategy has already left (multi-user tasks.md, G.6's
design).

So the delivery asks here before it closes, and while the opening is in flight it runs
again ``poll_interval_seconds`` later: the same ``delivery.process`` job, one poll on.
It reads the DATABASE only, and a wait spends no attempt of the job.

It mirrors ``OpenAfterClose`` the other way round, with two differences on purpose. A
newer signal does not end the wait, and neither does the signal's age: an opening is
an intention TradingView can replace, and the position a close closes is real whatever
came next. Only the opening's own bound ends it, and that bound has to outlast the
settle job (``close_after_open_timeout_seconds``).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from strategy_manager.execution.domain.execution_attempt import ExecutionStatus
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.application.ports import ClockPort, JobQueuePort
from strategy_manager.signals.application.fan_out_signal import DeliveryHalves


class CloseStep(StrEnum):
    """What a close does next about the opening it unwinds."""

    PROCEED = "PROCEED"
    WAIT = "WAIT"
    TIMED_OUT = "TIMED_OUT"
    NOTHING_OPENED = "NOTHING_OPENED"


@dataclass(frozen=True, slots=True)
class OpeningState:
    """The opening attempt of an allocation, and whether the ledger holds a row of
    that allocation."""

    status: ExecutionStatus
    created_at: datetime
    booked: bool


class OpeningStatePort(Protocol):
    async def opening_state(self, user_id: UUID, allocation_id: UUID) -> OpeningState | None:
        """``None`` when the allocation has no opening attempt."""
        ...


def next_close_step(state: OpeningState | None, now: datetime, timeout_seconds: float) -> CloseStep:
    """A row booked is a position, whatever the attempt says, and the attempt is read
    first, so a settle landing between the two reads shows here as a row booked.

    No attempt at all proceeds on purpose: a reservation that never reached the venue
    stays on ``NothingRecordedYet``'s retry, as it did before this existed."""
    if state is None or state.booked or state.status is ExecutionStatus.FILLED:
        return CloseStep.PROCEED
    if state.status is not ExecutionStatus.SUBMITTED:
        return CloseStep.NOTHING_OPENED
    if (now - state.created_at).total_seconds() < timeout_seconds:
        return CloseStep.WAIT
    return CloseStep.TIMED_OUT


class CloseAfterOpen:
    def __init__(
        self,
        openings: OpeningStatePort,
        queue: JobQueuePort,
        clock: ClockPort,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> None:
        self._openings = openings
        self._queue = queue
        self._clock = clock
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds

    async def step(self, user_id: UUID, allocation_id: UUID) -> CloseStep:
        state = await self._openings.opening_state(user_id, allocation_id)
        return next_close_step(state, self._clock.now(), self._timeout_seconds)

    async def seed(self, delivery_id: UUID, halves: DeliveryHalves, poll: int) -> None:
        """Enqueues poll ``poll`` of this delivery. Never commits: the caller's commit
        makes it durable. A run repeated after a crash finds its step already there,
        and the chain goes on from that one."""
        await self._queue.enqueue_unique(
            Job(
                kind=JobKind.DELIVERY_PROCESS,
                payload={
                    "delivery_id": str(delivery_id),
                    "halves": halves.value,
                    "poll": poll,
                },
                run_after=self._clock.now() + timedelta(seconds=self._poll_interval_seconds),
                dedupe_key=f"delivery:{delivery_id}:after-opening:{poll}",
            )
        )
