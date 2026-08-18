"""Real-time implementation of ``ClockPort``."""

from datetime import UTC, datetime


class SystemClock:
    """Wall-clock time. Tests use a fake/frozen clock instead."""

    def now(self) -> datetime:
        return datetime.now(UTC)
