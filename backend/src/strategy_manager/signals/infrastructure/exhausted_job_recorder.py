"""``ExhaustedJobSignalRecorder``: ends a signal ``REJECTED`` ``JOB_FAILED``
when a job working on it spends its last attempt (decision 25, task 5c.6)."""

from typing import Protocol
from uuid import UUID

from strategy_manager.shared.application.job import ClaimedJob
from strategy_manager.shared.infrastructure.alert_redaction import redact
from strategy_manager.signals.application.ports import SignalOutcomePort
from strategy_manager.signals.domain.outcome import SignalOutcome

JOB_FAILED = "JOB_FAILED"
MAX_DETAIL_CHARS = 500


class FailedJobSignalReaderPort(Protocol):
    async def signal_for(self, job: ClaimedJob) -> UUID | None: ...


class ExhaustedJobSignalRecorder:
    def __init__(
        self, outcomes: SignalOutcomePort, signals: FailedJobSignalReaderPort
    ) -> None:
        self._outcomes = outcomes
        self._signals = signals

    async def on_exhausted(self, job: ClaimedJob, last_error: str) -> None:
        """Runs inside the transaction that marks ``job`` FAILED, on the
        queue's session, so the outcome commits with that status or not at
        all. ``record_unless_terminal``: the signal may already have ended
        (this job's sibling, an earlier abandonment) and that is not a
        conflict, so it must neither be overwritten nor warn -- and it is what
        makes "exactly once" hold when two jobs of one signal exhaust."""
        signal_id = await self._signals.signal_for(job)
        if signal_id is None:
            return
        await self._outcomes.record_unless_terminal(
            signal_id, SignalOutcome.rejected(JOB_FAILED, _panel_detail(last_error))
        )


def _panel_detail(last_error: str) -> str | None:
    """``jobs.last_error`` as PANEL-VISIBLE text: redacted (the same scrubber
    the alert channel uses -- a removal, never an addition), then bounded. Adds
    nothing to it: no job id, no payload, no attempt count."""
    detail = redact(last_error)
    if len(detail) > MAX_DETAIL_CHARS:
        detail = detail[: MAX_DETAIL_CHARS - 1] + "\u2026"
    return detail or None
