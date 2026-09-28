"""EnablementEvent, EnablementOrigin and ``uptime()`` -- the append-only
audit trail of a strategy's enabled/disabled transitions, and the pure
function that derives cumulative uptime from it (design.md § 9 "Enablement
event log and uptime"; spec: strategy-lifecycle § "Enable/Disable Event
Log", "Cumulative Uptime Is Derived, Never Stored As a Running Total";
tasks.md 2d.5/2d.7).

Written test-first in this unit (tasks.md 2d), driven by
``tests/strategies/domain/test_enablement.py``. ``strategy_enablement_events``
itself (the table, the append-only trigger, the BASELINE seeding) shipped
earlier in migration 0024 (unit 2a) -- this module is the pure reader of the
rows that migration and ``SqlAlchemyEnablementLog`` (unit 2d) write.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class EnablementOrigin(StrEnum):
    """Mirrors the ``strategy_enablement_events.origin`` CHECK constraint
    (migration 0024). ``BASELINE`` marks the one row the migration itself
    wrote for a strategy that was already enabled when it ran; every event
    written afterward by ``UpdateStrategy``/``RegisterStrategy`` is
    ``OBSERVED``."""

    OBSERVED = "OBSERVED"
    BASELINE = "BASELINE"


@dataclass(frozen=True, slots=True)
class EnablementEvent:
    """One row of ``strategy_enablement_events`` -- append-only, never
    updated or deleted (migration 0024's trigger enforces this at the DB
    layer too)."""

    strategy_id: UUID
    enabled: bool
    occurred_at: datetime
    origin: EnablementOrigin


@dataclass(frozen=True, slots=True)
class Uptime:
    """The result of summing a strategy's enabled intervals (spec:
    "Cumulative Uptime Is Derived, Never Stored"). ``baseline=True`` means
    the earliest known enable is a BASELINE row -- the UI renders that as
    "active >= X days, since at least <date>" rather than claiming an exact
    first activation the migration could not know."""

    seconds: float
    first_enabled_at: datetime | None
    baseline: bool


def uptime(events: Sequence[EnablementEvent], now: datetime) -> Uptime:
    """Sums the intervals between paired enable/disable events, including
    the still-open interval if the strategy is currently enabled.

    Events are sorted by ``occurred_at`` first, so callers may pass them in
    any order. A repeated same-state event (two ``enabled=True`` rows in a
    row, with no disable between them) is ignored defensively rather than
    treated as re-opening a new interval -- the spec's own wording
    ("ignores repeated same-state events").
    """
    ordered = sorted(events, key=lambda event: event.occurred_at)

    total_seconds = 0.0
    first_enabled_at: datetime | None = None
    baseline = False
    open_since: datetime | None = None
    last_state: bool | None = None

    for event in ordered:
        if last_state is not None and event.enabled == last_state:
            continue  # defensive: repeated same-state event, not a new interval
        last_state = event.enabled

        if event.enabled:
            if first_enabled_at is None:
                first_enabled_at = event.occurred_at
                baseline = event.origin == EnablementOrigin.BASELINE
            open_since = event.occurred_at
        elif open_since is not None:
            total_seconds += (event.occurred_at - open_since).total_seconds()
            open_since = None

    if open_since is not None:
        total_seconds += (now - open_since).total_seconds()

    return Uptime(seconds=total_seconds, first_enabled_at=first_enabled_at, baseline=baseline)
