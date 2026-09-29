"""``ExhaustionObservingJobQueue``: the queue the WORKER claims through, which
tells an observer the moment a job spends its last attempt (decision 25,
design.md "Addendum: signal outcomes" § F, task 5c.6).

It exists because ``PostgresJobQueue.fail()`` is the one place that knows a job
just became ``FAILED`` and it must stay job-kind-agnostic: it has no
``signal_id`` in scope and must never learn what a ``signal.process`` job is.
So the observer receives the job opaquely and decides what it means.

**Why a subclass with a required observer, not an optional parameter on
``PostgresJobQueue``.** That class is built at dozens of enqueue-only sites
(the webhook router, every handler's own queue, most tests) where nothing can
exhaust. An optional observer defaulting to "nobody" would be a silent no-op on
exactly the queue where it matters, so the worker's queue is its own type:
forgetting the observer there is a ``TypeError`` at composition, not a silent
gap.

**Same transaction as ``FAILED``.** The observer runs between the status
``UPDATE`` and the ``commit()`` on the SAME session, so what it stages (a
signal's ``JOB_FAILED`` outcome) is durable together with the ``FAILED`` status
or not at all. A separate later write, or a recurring sweep, would leave a
window in which a job is ``FAILED`` and its signal still looks alive, and that
window is exactly the silence decision 25 exists to remove.

**A SAVEPOINT around the observer.** Its failure must not cost the job its
``FAILED`` status: ``run_once`` calls ``fail()`` from an ``except`` block, so an
exception escaping here would leave the job ``CLAIMED``, out of the retry chain
and never reported, and would escape ``run_forever`` too. The savepoint rolls
back only what the observer staged, and the failure is logged at ERROR with the
message redacted (that channel reaches a phone).
"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.application.job import ClaimedJob
from strategy_manager.shared.application.ports import ClockPort, ExhaustedJobObserverPort
from strategy_manager.shared.infrastructure.alert_redaction import redact
from strategy_manager.shared.infrastructure.job_queue import (
    DEFAULT_BACKOFF_BASE_SECONDS,
    DEFAULT_BACKOFF_MAX_SECONDS,
    PostgresJobQueue,
)

logger = logging.getLogger(__name__)


class ExhaustionObservingJobQueue(PostgresJobQueue):
    def __init__(
        self,
        session: AsyncSession,
        *,
        observer: ExhaustedJobObserverPort,
        clock: ClockPort | None = None,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS,
    ) -> None:
        super().__init__(
            session,
            clock=clock,
            backoff_base_seconds=backoff_base_seconds,
            backoff_max_seconds=backoff_max_seconds,
        )
        self._observer = observer

    async def fail(self, job_id: UUID, error: str) -> None:
        exhausted = await self._record_failure(job_id, error)
        if exhausted is not None:
            await self._observe(exhausted, error)
        await self._session.commit()

    async def _observe(self, job: ClaimedJob, error: str) -> None:
        try:
            async with self._session.begin_nested():
                await self._observer.on_exhausted(job, error)
        except Exception as exc:  # noqa: BLE001 - the observer must never cost the
            # job its FAILED status nor take the claim loop down with it
            #
            # ``str(exc)`` only, redacted, no traceback: this line reaches the
            # alert bridge, and a traceback out of this loop once printed a
            # database DSN.
            logger.error(
                "job %s (%s) is FAILED but its exhaustion observer could not record "
                "it, so whatever that job was for stays undecided: %s",
                job.id,
                job.kind.value,
                redact(str(exc)),
            )
