"""``SqlAlchemyFailedJobSignalReader``: resolves a job's payload to what it was
working on (decision 25, task 5c.6; tasks.md C.7), so an exhausted job records its
outcome there.

The queue stays job-kind-agnostic, so this is where the kinds that can decide an
outcome are named. ``signal.process`` is the fan-out, which works the SIGNAL itself
(no delivery exists to hold its outcome). Every other kind works a DELIVERY:
``delivery.process`` names it; ``signal.open_after_close`` names the signal and
works the delivery of the strategy's author (until C.8 moves it to the delivery
itself); ``execution.settle`` names an attempt, which carries the delivery that
placed it, for an open and a close alike.

**Global by design** (multi-user design AD8): the queue's failure hook has no
user context, and every row is followed by primary key from the attempt or
delivery the job itself names, never searched for, so no other user's row can
answer.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.infrastructure.exhausted_job_recorder import FailedJobTarget
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow, SignalRow
from strategy_manager.strategies.infrastructure.models import StrategyRow


class SqlAlchemyFailedJobSignalReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def target_for(self, job: ClaimedJob) -> FailedJobTarget | None:
        """What ``job`` was working on, ``None`` when this kind decides nothing or
        the link is NULL (an orphan close, an attempt written before 5c). A
        payload that cannot be resolved RAISES rather than returning ``None``: the
        queue logs the error, and a FAILED job whose delivery cannot be found must
        not be skipped quietly."""
        match job.kind:
            case JobKind.SIGNAL_PROCESS:
                return FailedJobTarget(signal_id=_uuid(job, "signal_id"))
            case JobKind.DELIVERY_PROCESS:
                return FailedJobTarget(
                    delivery_id=await self._existing_delivery(_uuid(job, "delivery_id"))
                )
            case JobKind.SIGNAL_OPEN_AFTER_CLOSE:
                return FailedJobTarget(
                    delivery_id=await self._author_delivery(_uuid(job, "signal_id"))
                )
            case JobKind.EXECUTION_SETTLE:
                delivery_id = await self._attempt_delivery(_uuid(job, "execution_attempt_id"))
                return None if delivery_id is None else FailedJobTarget(delivery_id=delivery_id)
            case _:
                return None

    async def _existing_delivery(self, delivery_id: UUID) -> UUID:
        found = (
            await self._session.execute(
                select(SignalDeliveryRow.id).where(SignalDeliveryRow.id == delivery_id)
            )
        ).scalar_one_or_none()
        if found is None:
            raise InvariantViolation(f"no delivery {delivery_id} for a FAILED delivery.process job")
        return delivery_id

    async def _author_delivery(self, signal_id: UUID) -> UUID:
        """The continuation opens for the strategy author's delivery (C.6), so that
        is the one its exhaustion ends."""
        found = (
            await self._session.execute(
                select(SignalDeliveryRow.id)
                .join(SignalRow, SignalRow.id == SignalDeliveryRow.signal_id)
                .join(StrategyRow, StrategyRow.id == SignalRow.strategy_id)
                .where(
                    SignalDeliveryRow.signal_id == signal_id,
                    SignalDeliveryRow.user_id == StrategyRow.author_id,
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise InvariantViolation(
                f"signal {signal_id} has no delivery for its strategy's author, for a "
                "FAILED signal.open_after_close job"
            )
        return found

    async def _attempt_delivery(self, attempt_id: UUID) -> UUID | None:
        row = (
            await self._session.execute(
                select(ExecutionAttemptRow.delivery_id).where(ExecutionAttemptRow.id == attempt_id)
            )
        ).one_or_none()
        if row is None:
            raise InvariantViolation(f"no execution attempt {attempt_id} for a FAILED settle job")
        return row.delivery_id  # type: ignore[no-any-return]


def _uuid(job: ClaimedJob, key: str) -> UUID:
    raw = job.payload.get(key)
    if raw is None:
        raise InvariantViolation(f"a FAILED {job.kind.value} job carries no {key}")
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise InvariantViolation(f"a FAILED {job.kind.value} job carries a bad {key}") from exc
