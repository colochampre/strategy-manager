"""The mode a position runs in (multi-user design AD7, decisions 6, 7 and 14).

The mode belongs to the user, and ``.env``'s ``DRY_RUN`` is a brake over everyone:
a delivery opens ``LIVE`` only with the brake off and the user ``LIVE``. The result
is recorded on the reservation, which everything after the opening then follows.
"""

from enum import StrEnum


class Mode(StrEnum):
    """Mirrors the CHECKs on ``users.mode`` and ``reservations.mode`` (0035)."""

    LIVE = "LIVE"
    SIMULATION = "SIMULATION"


def effective_mode(*, brake: bool, user_mode: Mode) -> Mode:
    return Mode.SIMULATION if brake else user_mode
