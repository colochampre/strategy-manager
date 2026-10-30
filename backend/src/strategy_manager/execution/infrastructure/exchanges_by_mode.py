"""``ExchangesByMode``: the one place a mode becomes adapters (multi-user design
AD7, tasks.md E.3).

The brake is not consulted here. A delivery's mode is decided once, in the lock,
and recorded on its reservation; from then on an order, its settle and its close
follow that record, so a real position still closes for real under the brake
(decision 14). What runs here is the last line of defence for that rule: each
direction is refused, whatever the wiring handed over.

- ``LIVE`` with a fake would book a real position flat in the ledger while it
  stays open at the venue.
- ``SIMULATION`` with a live adapter would place a real order for a rehearsal.

Only ``LIVE`` opens anything: a simulated job decrypts no key and opens no socket.
"""

from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.application.ports import ExchangePort, ExchangeRegistryPort
from strategy_manager.execution.infrastructure.exchange_registry import VenueExchangeRegistry
from strategy_manager.execution.infrastructure.simulated_venues import SimulatedVenues
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.mode import Mode

LiveAdapters = Callable[
    [AsyncSession, UUID | None], AbstractAsyncContextManager[Sequence[ExchangePort]]
]
"""Every live adapter ``user_id`` holds a key for, closed with the context."""


def _registry(mode: Mode, adapters: Iterable[ExchangePort]) -> ExchangeRegistryPort:
    served = tuple(adapters)
    wrong = [
        type(adapter).__name__
        for adapter in served
        if adapter.is_live is not (mode is Mode.LIVE)
    ]
    if wrong:
        raise InvariantViolation(f"a {mode.value} job was handed {', '.join(wrong)}")
    return VenueExchangeRegistry(served)


class ExchangesByMode:
    def __init__(self, *, live: LiveAdapters, simulated: SimulatedVenues) -> None:
        self._live = live
        self._simulated = simulated

    @asynccontextmanager
    async def open(
        self, session: AsyncSession, user_id: UUID | None, mode: Mode
    ) -> AsyncIterator[ExchangeRegistryPort]:
        """``user_id`` is the job's owner. An owner that could not be resolved
        (``None``) gets an empty registry, so the job fails on the missing row,
        not on somebody else's account."""
        if mode is Mode.SIMULATION:
            yield _registry(
                mode, () if user_id is None else self._simulated.exchanges_of(user_id)
            )
            return
        async with self._live(session, user_id) as adapters:
            yield _registry(mode, adapters)
