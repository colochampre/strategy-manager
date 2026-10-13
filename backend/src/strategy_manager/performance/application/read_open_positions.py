"""``ReadOpenPositions``: every open position and every in-flight order of the
system (design addendum "open positions", decision 65, section C).

THIS IS A STUB (task op.1.7): it issues the first two reads of the sequence, the
in-flight read and then the open-allocations read, and answers an EMPTY
``OpenState``. It exists so that the invariant test (T1) can fail on an
assertion. The tasks that follow replace its body.
"""

from strategy_manager.performance.application.ports import (
    ConfirmedDisagreementSourcePort,
    OpenPositionFactsSourcePort,
    OpenStateSourcePort,
)
from strategy_manager.performance.domain.open_position import OpenState


class ReadOpenPositions:
    def __init__(
        self,
        state: OpenStateSourcePort,
        facts: OpenPositionFactsSourcePort,
        disagreements: ConfirmedDisagreementSourcePort,
    ) -> None:
        self._state = state
        self._facts = facts
        self._disagreements = disagreements

    async def read(self) -> OpenState:
        # Step 1, then step 2: in that order on purpose (section C).
        await self._state.in_flight_attempts()
        await self._state.open_allocations()
        return OpenState(positions=(), orders=())
