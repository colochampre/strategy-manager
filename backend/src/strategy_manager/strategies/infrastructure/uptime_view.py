"""``UptimeView``: how long a strategy has taken signals, on the wire. Its own module
because three routers serve it (the author's strategies, the public list and a held
seat, tasks.md L.1), and the author's router imports the other two."""

from datetime import datetime

from pydantic import BaseModel

from strategy_manager.strategies.domain.enablement import Uptime


class UptimeView(BaseModel):
    """Mirrors ``enablement.Uptime`` (design.md § 9). ``baseline=True``
    means the earliest known enable is a BASELINE row written by migration
    0024 -- the true first-enabled date is unknown, and the panel renders
    "active >= X days" rather than claiming an exact one."""

    seconds: float
    first_enabled_at: datetime | None
    baseline: bool

    @classmethod
    def of(cls, value: Uptime) -> "UptimeView":
        return cls(
            seconds=value.seconds, first_enabled_at=value.first_enabled_at, baseline=value.baseline
        )
