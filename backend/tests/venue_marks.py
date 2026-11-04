"""The venue's mark price, for tests that run the simulated exchange the
production composition root builds (decision 35).

``main.build_worker_runner`` prices every simulated fill from the venue's public
market data. No test may reach a venue (rule 1), so ``tests/conftest.py`` routes
that read to ``NoVenue`` for every test, and a test that fills through the real
wiring installs ``VenueMarks`` with ``install``.
"""

from collections.abc import Mapping
from decimal import Decimal

import pytest

from strategy_manager import main
from strategy_manager.execution.infrastructure.venue_mark_prices import MarkPriceSource
from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.money import Exchange


class NoVenue:
    """What a test that did not install a price gets: a loud refusal, never a
    request to a real venue."""

    async def mark_price(self, symbol: str) -> Decimal:
        raise RuntimeError(
            f"a test asked a venue for the mark price of {symbol!r}; "
            "install tests.venue_marks.VenueMarks"
        )


class VenueMarks:
    """One settable mark price per exchange, and every symbol each was asked
    for. ``price`` is what every exchange answers unless ``by_exchange`` says
    otherwise."""

    def __init__(self, price: Decimal) -> None:
        self.price = price
        self.by_exchange: dict[str, Decimal] = {}
        self.asked: list[tuple[str, str]] = []

    def source(self, exchange: str) -> MarkPriceSource:
        marks = self

        class _Source:
            async def mark_price(self, symbol: str) -> Decimal:
                marks.asked.append((exchange, symbol))
                return marks.by_exchange.get(exchange, marks.price)

        return _Source()

    def sources(self) -> Mapping[str, MarkPriceSource]:
        return {exchange.value: self.source(exchange.value) for exchange in Exchange}


def refuse_every_venue(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_venue(settings: Settings) -> Mapping[str, MarkPriceSource]:
        return {exchange.value: NoVenue() for exchange in Exchange}

    monkeypatch.setattr(main, "public_mark_prices", no_venue)


def install(monkeypatch: pytest.MonkeyPatch, marks: VenueMarks) -> VenueMarks:
    """Routes the composition root's mark-price read to ``marks``. Call it
    before ``main.build_worker_runner``: the sources are taken when it runs."""

    def from_marks(settings: Settings) -> Mapping[str, MarkPriceSource]:
        return marks.sources()

    monkeypatch.setattr(main, "public_mark_prices", from_marks)
    return marks
