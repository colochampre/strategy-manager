"""``ReadOpenPositions``: every open position and every in-flight order of the
system (design addendum "open positions", decision 65, section C).

This is the STUB of task op.1.1: it issues the two reads of the sequence, the
in-flight read and then the open-allocations read, and answers what they say. It
exists so that the snapshot test (T6) can fail on an assertion. The full read
model replaces its body in the tasks that follow.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from strategy_manager.execution.domain.mode_origin import (
    InFlightAttemptOrigin,
    OpenAllocationOrigin,
)
from strategy_manager.performance.application.ports import OpenStateSourcePort


@dataclass(frozen=True, slots=True)
class OpenStateStub:
    in_flight: Sequence[InFlightAttemptOrigin]
    opened: Sequence[OpenAllocationOrigin]


class ReadOpenPositions:
    def __init__(self, state: OpenStateSourcePort) -> None:
        self._state = state

    async def read(self) -> OpenStateStub:
        # Step 1, then step 2: in that order on purpose (section C).
        in_flight = await self._state.in_flight_attempts()
        opened = await self._state.open_allocations()
        return OpenStateStub(in_flight=in_flight, opened=opened)
