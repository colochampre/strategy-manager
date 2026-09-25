"""``uptime(events, now)`` -- the pure function that derives a strategy's
cumulative enabled time from its append-only event log (design.md § 9;
spec: strategy-lifecycle § "Cumulative Uptime Is Derived, Never Stored As a
Running Total"; tasks.md 2d.5).
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from strategy_manager.strategies.domain.enablement import (
    EnablementEvent,
    EnablementOrigin,
    uptime,
)

STRATEGY_ID = uuid4()
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _event(offset_days: float, enabled: bool, origin: EnablementOrigin) -> EnablementEvent:
    return EnablementEvent(
        strategy_id=STRATEGY_ID,
        enabled=enabled,
        occurred_at=T0 + timedelta(days=offset_days),
        origin=origin,
    )


def test_uptime_sums_closed_and_open_intervals() -> None:
    """spec scenario: "Uptime sums closed and open intervals" -- S1 was
    enabled for 3 days, disabled for 1 day, then re-enabled and has been
    enabled for 2 more days as of now. Total: 5 days, summed from the event
    log, with no stored total read."""
    events = [
        _event(0, True, EnablementOrigin.OBSERVED),  # enabled day 0
        _event(3, False, EnablementOrigin.OBSERVED),  # disabled day 3 (3 days open)
        _event(4, True, EnablementOrigin.OBSERVED),  # re-enabled day 4 (1 day closed)
        # still enabled; "now" is 2 days after the second enable
    ]
    now = T0 + timedelta(days=6)

    result = uptime(events, now)

    assert result.seconds == timedelta(days=5).total_seconds()
    assert result.first_enabled_at == T0
    assert result.baseline is False


def test_never_enabled_strategy_has_zero_uptime_no_activation_date() -> None:
    """spec scenario: "A strategy never enabled has zero uptime" -- S2 was
    created disabled and has never been enabled: zero uptime, no
    first-activation date shown."""
    result = uptime([], T0 + timedelta(days=10))

    assert result.seconds == 0
    assert result.first_enabled_at is None
    assert result.baseline is False


def test_uptime_ignores_repeated_same_state_events_defensively() -> None:
    """A repeated same-state event (two ``enabled=True`` rows with no
    disable between them) must not be treated as re-opening a new interval
    -- the spec's own wording ("ignores repeated same-state events")."""
    events = [
        _event(0, True, EnablementOrigin.OBSERVED),
        _event(1, True, EnablementOrigin.OBSERVED),  # defensive: repeated, ignored
        _event(3, False, EnablementOrigin.OBSERVED),
    ]
    now = T0 + timedelta(days=10)

    result = uptime(events, now)

    # If the repeated event were NOT ignored, it would restart the interval
    # at day 1, giving 2 days (day1->day3) instead of the correct 3 (day0->day3).
    assert result.seconds == timedelta(days=3).total_seconds()


def test_uptime_baseline_flag_renders_as_active_at_least_x_days() -> None:
    """design.md § 9: "``baseline=true`` means the first event is BASELINE,
    so the UI renders 'active >= X days, since at least <date>'." A strategy
    already enabled when migration 0024 ran has a BASELINE first event
    instead of an OBSERVED one -- the true first-enabled date is unknown,
    and ``baseline`` says so."""
    events = [
        _event(0, True, EnablementOrigin.BASELINE),  # written by the migration
    ]
    now = T0 + timedelta(days=7)

    result = uptime(events, now)

    assert result.baseline is True
    assert result.first_enabled_at == T0
    assert result.seconds == timedelta(days=7).total_seconds()
