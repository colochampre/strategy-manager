"""Why a closed operation ended (panel-redesign RD.4a).

An operation's cause is the kind of its close safety event. An operation with
none was closed by its strategy's own signal. Pure: no framework, no I/O.
"""

from enum import StrEnum


class CloseCause(StrEnum):
    STOP_FIRED = "STOP_FIRED"
    STOP_FAILED_CLOSED = "STOP_FAILED_CLOSED"
    STRATEGY_STOPPED_CLOSED = "STRATEGY_STOPPED_CLOSED"
    MANUAL_CLOSE = "MANUAL_CLOSE"
    SIGNAL = "SIGNAL"


#: The safety-event kinds that close an operation. The kinds that refuse an
#: opening are not causes: they never belong to a closed operation.
CLOSE_EVENT_KINDS: tuple[str, ...] = tuple(
    cause.value for cause in CloseCause if cause is not CloseCause.SIGNAL
)


def close_cause_of(event_kind: str | None) -> CloseCause:
    """``SIGNAL`` when the operation has no close event. A kind that is not a
    close kind is a fault of the source, so it is refused and never read as one."""
    if event_kind is None:
        return CloseCause.SIGNAL
    if event_kind not in CLOSE_EVENT_KINDS:
        raise ValueError(f"{event_kind!r} is not a close event kind")
    return CloseCause(event_kind)
