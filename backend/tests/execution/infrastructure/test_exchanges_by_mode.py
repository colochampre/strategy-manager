"""``ExchangesByMode``: which adapters a job gets (multi-user design AD7, tasks.md
E.3).

This is the one place a mode becomes an adapter. ``LIVE`` must never reach a
fake: the ledger would read flat while the position stays open at the venue. And
``SIMULATION`` must never reach a live adapter: a rehearsal would place a real
order. Each direction is refused here, whatever the wiring handed over.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.application.ports import ExchangeError, ExchangePort
from strategy_manager.execution.infrastructure.exchanges_by_mode import ExchangesByMode
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.fake_venue_book import FakeVenueBook
from strategy_manager.execution.infrastructure.simulated_venues import SimulatedVenues
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.mode import Mode

SESSION = cast(AsyncSession, object())
USER = uuid4()


class LiveExchange:
    is_live = True
    exchange = "bybit"
    venues = frozenset({"usdt-m"})


class Live:
    """Stands in for the vault-backed builder: records who it was opened for and
    whether it was closed."""

    def __init__(self, *adapters: Any) -> None:
        self._adapters = adapters
        self.opened: list[UUID | None] = []
        self.closed = 0

    @asynccontextmanager
    async def __call__(
        self, session: AsyncSession, user_id: UUID | None
    ) -> AsyncIterator[Sequence[ExchangePort]]:
        self.opened.append(user_id)
        try:
            yield self._adapters
        finally:
            self.closed += 1


class LeakyVenues:
    """A simulated side that hands back a live adapter."""

    def exchanges_of(self, user_id: UUID) -> Sequence[Any]:
        return [LiveExchange()]


async def _no_ledger(user_id: UUID, pool: tuple[str, str, str]) -> Sequence[tuple[str, Decimal]]:
    return []


def _simulated() -> SimulatedVenues:
    def build(exchange: str, book: FakeVenueBook) -> FakeExchangeAdapter:
        return FakeExchangeAdapter(exchange=exchange, book=book, fee_rate=Decimal("0"))

    return SimulatedVenues(exchanges=("bybit",), build=build, ledger_reader=_no_ledger)


async def test_live_gets_the_users_live_adapters_and_closes_them_with_the_job() -> None:
    adapter = LiveExchange()
    live = Live(adapter)
    by_mode = ExchangesByMode(live=live, simulated=_simulated())

    async with by_mode.open(SESSION, USER, Mode.LIVE) as registry:
        assert registry.for_pool("bybit", "usdt-m") is adapter
        assert live.closed == 0

    assert live.opened == [USER]
    assert live.closed == 1


async def test_simulation_gets_that_users_fake_and_opens_nothing_live() -> None:
    live = Live(LiveExchange())
    simulated = _simulated()
    by_mode = ExchangesByMode(live=live, simulated=simulated)

    async with by_mode.open(SESSION, USER, Mode.SIMULATION) as registry:
        assert registry.for_pool("bybit", "usdt-m") is simulated.exchanges_of(USER)[0]

    assert live.opened == []


async def test_live_never_returns_a_fake() -> None:
    fake = FakeExchangeAdapter(exchange="bybit", fee_rate=Decimal("0"))
    by_mode = ExchangesByMode(live=Live(fake), simulated=_simulated())

    with pytest.raises(InvariantViolation):
        async with by_mode.open(SESSION, USER, Mode.LIVE):
            pytest.fail("a fake reached a live job")


async def test_simulation_never_returns_a_live_adapter() -> None:
    by_mode = ExchangesByMode(live=Live(), simulated=cast(SimulatedVenues, LeakyVenues()))

    with pytest.raises(InvariantViolation):
        async with by_mode.open(SESSION, USER, Mode.SIMULATION):
            pytest.fail("a live adapter reached a simulated job")


@pytest.mark.parametrize("mode", list(Mode))
async def test_an_unresolved_owner_gets_nobodys_adapters(mode: Mode) -> None:
    """The job then fails on the missing row, not on somebody else's account."""
    by_mode = ExchangesByMode(live=Live(), simulated=_simulated())

    async with by_mode.open(SESSION, None, mode) as registry:
        with pytest.raises(ExchangeError):
            registry.for_pool("bybit", "usdt-m")
