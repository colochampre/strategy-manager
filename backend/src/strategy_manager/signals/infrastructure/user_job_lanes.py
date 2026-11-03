"""The user a trading job belongs to, as SQL the claim can read (tasks.md G.7).

``job_owner`` resolves the same owners in Python, once a job is claimed, to choose
the key it trades with. The claim needs them before that, inside its own query, to
keep one user's jobs one at a time: a delivery and its continuation name their
delivery, a settle its attempt, and both rows carry the user. Reading it from those
rows rather than adding it to the payload covers the jobs already queued when this
was deployed.
"""

from typing import Any

from sqlalchemy import ColumnElement, cast, func, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.infrastructure.job_lanes import JobLanes
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow


def user_of_job(job: Any) -> ColumnElement[Any]:
    """NULL for a payload that names neither, such as a legacy continuation that
    carries only ``signal_id``: the claim then treats that job as a barrier."""
    of_delivery = (
        select(SignalDeliveryRow.user_id)
        .where(SignalDeliveryRow.id == cast(job.payload["delivery_id"].astext, PgUUID))
        .correlate(job)
        .scalar_subquery()
    )
    of_attempt = (
        select(ExecutionAttemptRow.user_id)
        .where(
            ExecutionAttemptRow.id == cast(job.payload["execution_attempt_id"].astext, PgUUID)
        )
        .correlate(job)
        .scalar_subquery()
    )
    return func.coalesce(of_delivery, of_attempt)


USER_JOB_LANES = JobLanes(
    kinds=frozenset(
        {JobKind.DELIVERY_PROCESS, JobKind.SIGNAL_OPEN_AFTER_CLOSE, JobKind.EXECUTION_SETTLE}
    ),
    owner_of=user_of_job,
)
