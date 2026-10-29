"""``ExhaustedJobSignalRecorder``: ends what a job was working on ``REJECTED``
``JOB_FAILED`` when it spends its last attempt (decision 25, task 5c.6; tasks.md
C.7).

What the job was working on is a DELIVERY for every kind that works one, and the
outcome lands on that delivery's row. An exhausted ``signal.process`` (the fan-out)
was working on the SIGNAL itself, which has no delivery to hold the outcome: it
lands on the signal's row, like every strategy-level refusal."""

import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from strategy_manager.shared.application.job import ClaimedJob
from strategy_manager.shared.infrastructure.alert_redaction import redact
from strategy_manager.signals.application.ports import DeliveryOutcomePort, SignalOutcomePort
from strategy_manager.signals.domain.outcome import SignalOutcome

logger = logging.getLogger(__name__)

JOB_FAILED = "JOB_FAILED"
MAX_DETAIL_CHARS = 500


@dataclass(frozen=True, slots=True)
class FailedJobTarget:
    """Exactly one of the two: the delivery the failed job was working on, or the
    signal whose fan-out it was."""

    delivery_id: UUID | None = None
    signal_id: UUID | None = None

    def __post_init__(self) -> None:
        if (self.delivery_id is None) == (self.signal_id is None):
            raise ValueError("a FailedJobTarget names exactly one of a delivery or a signal")


class FailedJobSignalReaderPort(Protocol):
    async def target_for(self, job: ClaimedJob) -> FailedJobTarget | None: ...


class ExhaustedJobSignalRecorder:
    def __init__(
        self,
        signal_outcomes: SignalOutcomePort,
        delivery_outcomes: DeliveryOutcomePort,
        targets: FailedJobSignalReaderPort,
    ) -> None:
        self._signal_outcomes = signal_outcomes
        self._delivery_outcomes = delivery_outcomes
        self._targets = targets

    async def on_exhausted(self, job: ClaimedJob, last_error: str) -> None:
        """Runs inside the transaction that marks ``job`` FAILED, on the
        queue's session, so the outcome commits with that status or not at
        all. ``record_unless_terminal``: the delivery (or signal) may already have
        ended (this job's sibling, an earlier abandonment) and that is not a
        conflict, so it must neither be overwritten nor warn -- and it is what
        makes "exactly once" hold when two jobs of one delivery exhaust."""
        target = await self._targets.target_for(job)
        if target is None:
            return
        outcome = SignalOutcome.rejected(JOB_FAILED, _panel_detail(last_error))
        if target.delivery_id is not None:
            await self._delivery_outcomes.record_unless_terminal(target.delivery_id, outcome)
            logger.info(
                "exhausted %s job %s: delivery %s ended REJECTED %s unless already decided",
                job.kind.value,
                job.id,
                target.delivery_id,
                JOB_FAILED,
            )
            return
        assert target.signal_id is not None  # __post_init__: exactly one is set
        await self._signal_outcomes.record_unless_terminal(target.signal_id, outcome)
        logger.info(
            "exhausted %s job %s: signal %s ended REJECTED %s unless already decided",
            job.kind.value,
            job.id,
            target.signal_id,
            JOB_FAILED,
        )


def _panel_detail(last_error: str) -> str | None:
    """``jobs.last_error`` as PANEL-VISIBLE text: redacted (the same scrubber
    the alert channel uses -- a removal, never an addition), then bounded. Adds
    nothing to it: no job id, no payload, no attempt count."""
    detail = redact(last_error)
    if len(detail) > MAX_DETAIL_CHARS:
        detail = detail[: MAX_DETAIL_CHARS - 1] + "…"
    return detail or None
