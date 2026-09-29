"""``SqlAlchemyFailedJobSignalReader``: resolves a job's payload to the signal
it was working on (decision 25, task 5c.6).

The queue stays job-kind-agnostic, so this is where the three kinds that can
decide a signal are named. Two carry the signal id directly. ``execution.settle``
carries an attempt id, and the attempt is resolved the way ``execution.settle``
itself resolves it: a CLOSE through ``execution_attempts.signal_id`` (its
``allocation_id`` is the OPENING allocation, so that reservation names the
opening signal), an OPEN through ``reservation.signal_id``.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.domain.errors import InvariantViolation


class SqlAlchemyFailedJobSignalReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def signal_for(self, job: ClaimedJob) -> UUID | None:
        """The signal ``job`` was working on, ``None`` when this kind decides
        no signal or the link is NULL (an orphan close, an attempt written
        before 5c). A payload that cannot be resolved RAISES rather than
        returning ``None``: the queue logs the error, and a FAILED job whose
        signal cannot be found must not be skipped quietly."""
        match job.kind:
            case JobKind.SIGNAL_PROCESS | JobKind.SIGNAL_OPEN_AFTER_CLOSE:
                return _uuid(job, "signal_id")
            case JobKind.EXECUTION_SETTLE:
                return await self._settle_signal(_uuid(job, "execution_attempt_id"))
            case _:
                return None

    async def _settle_signal(self, attempt_id: UUID) -> UUID | None:
        row = (
            await self._session.execute(
                select(
                    ExecutionAttemptRow.reservation_id,
                    ExecutionAttemptRow.closes_allocation_id,
                    ExecutionAttemptRow.signal_id,
                ).where(ExecutionAttemptRow.id == attempt_id)
            )
        ).one_or_none()
        if row is None:
            raise InvariantViolation(f"no execution attempt {attempt_id} for a FAILED settle job")
        if row.closes_allocation_id is not None:
            # A CLOSE: its allocation is the OPENING one, so the reservation
            # would name the opening signal. Only the attempt's own link is
            # the closing signal, and NULL means nothing to record.
            return row.signal_id  # type: ignore[no-any-return]
        signal_id = (
            await self._session.execute(
                select(ReservationRow.signal_id).where(ReservationRow.id == row.reservation_id)
            )
        ).scalar_one_or_none()
        if signal_id is None:
            raise InvariantViolation(
                f"no reservation {row.reservation_id} behind execution attempt {attempt_id}"
            )
        return signal_id


def _uuid(job: ClaimedJob, key: str) -> UUID:
    raw = job.payload.get(key)
    if raw is None:
        raise InvariantViolation(f"a FAILED {job.kind.value} job carries no {key}")
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise InvariantViolation(f"a FAILED {job.kind.value} job carries a bad {key}") from exc
