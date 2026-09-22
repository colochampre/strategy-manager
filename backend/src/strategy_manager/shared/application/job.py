"""Job queue DTOs shared across every module.

``Job`` is what a producer enqueues. ``ClaimedJob`` is what
``JobQueuePort.claim()`` hands to the worker, carrying the DB-assigned id and
attempt bookkeeping needed to decide retry vs. terminal failure.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class JobKind(StrEnum):
    """Every job kind processed by the worker, across all slices."""

    SIGNAL_PROCESS = "signal.process"
    RESERVATION_SWEEP = "reservation.sweep"
    BALANCE_SYNC = "balance.sync"
    EXECUTION_SETTLE = "execution.settle"
    RECONCILIATION_SCAN = "reconciliation.scan"
    JOBS_PURGE = "jobs.purge"
    # The S5 continuation (design.md § S5): opens a signal's position only
    # after every close it awaits has settled FILLED. Not implemented by
    # this unit -- only the kind exists so ``enqueue_unique`` and the tests
    # around it have a real ``JobKind`` to enqueue.
    SIGNAL_OPEN_AFTER_CLOSE = "signal.open_after_close"
    # The periodic health check (``shared.application.watchdog``). A recurring
    # chain like the others, and deliberately so: it needs no scheduler, no
    # second process and no second thing that can die unnoticed. What it cannot
    # do is notice its OWN death -- see that module's docstring.
    WATCHDOG_CHECK = "watchdog.check"


@dataclass(frozen=True, slots=True)
class Job:
    """A unit of work to enqueue. ``run_after=None`` means "as soon as possible"."""

    kind: JobKind
    payload: dict[str, Any] = field(default_factory=dict)
    run_after: datetime | None = None
    max_attempts: int = 5
    dedupe_key: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    """A job claimed by a worker, with its current attempt count."""

    id: UUID
    kind: JobKind
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
