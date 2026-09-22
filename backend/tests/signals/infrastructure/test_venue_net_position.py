"""Unit tests: ``VenueNetPositionAdapter`` -- the Existing-Position Guard's
divergent-branch venue read (spec: capital-allocation § Orphan
Classification; design.md § S4). ANY failure or timeout must degrade to
``None`` (AMBIGUOUS to the caller), never raise.

Binding testing lesson (owner, 2026-09-21): the venue book and the query
symbol use DIFFERENT spellings on each side, exactly like the reconciliation
symbol-spelling bug this project already shipped once
(bug/reconciliation-symbol-spelling-mismatch).
"""

import asyncio
from decimal import Decimal

from strategy_manager.reconciliation.application.ports import VenuePositionReadError
from strategy_manager.reconciliation.domain.positions import VenuePosition
from strategy_manager.reconciliation.infrastructure.venue_position_reader_registry import (
    UnservedPoolError,
)
from strategy_manager.signals.infrastructure.venue_net_position import (
    VenueNetPositionAdapter,
)

POOL = ("bybit", "usdt-m", "USDT")


class FakeReader:
    def __init__(
        self,
        positions: list[VenuePosition] | None = None,
        raises: Exception | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self._positions = positions or []
        self._raises = raises
        self._delay_seconds = delay_seconds
        self.calls: list[tuple[str, str, str]] = []

    async def open_positions(self, pool: tuple[str, str, str]) -> list[VenuePosition]:
        self.calls.append(pool)
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        if self._raises is not None:
            raise self._raises
        return self._positions


class FakeRegistry:
    def __init__(self, reader: FakeReader | None = None, raises: Exception | None = None) -> None:
        self._reader = reader
        self._raises = raises
        self.calls: list[tuple[str, str]] = []

    def for_pool(self, exchange: str, venue: str) -> FakeReader:
        self.calls.append((exchange, venue))
        if self._raises is not None:
            raise self._raises
        assert self._reader is not None
        return self._reader


async def test_sums_the_venues_reported_net_for_the_matching_market() -> None:
    reader = FakeReader(positions=[VenuePosition("STXUSDT", Decimal("0.5"))])
    adapter = VenueNetPositionAdapter(FakeRegistry(reader))

    net = await adapter.net_position(POOL, "STXUSDT.P")

    assert net == Decimal("0.5")
    assert reader.calls == [POOL]


async def test_matches_the_venues_bare_spelling_against_the_signals_p_suffix() -> None:
    """The venue reports ``STXUSDT``; the signal that triggered the
    divergent branch carries TradingView's ``STXUSDT.P``. Raw string
    comparison would never match either side -- exactly the mismatch that
    already reached production once (reconciliation)."""
    reader = FakeReader(
        positions=[
            VenuePosition("STXUSDT", Decimal("1.25")),
            VenuePosition("ETHUSDT", Decimal("9")),
        ]
    )
    adapter = VenueNetPositionAdapter(FakeRegistry(reader))

    net = await adapter.net_position(POOL, "STXUSDT.P")

    assert net == Decimal("1.25")


async def test_an_unserved_pool_is_ambiguous_not_an_exception() -> None:
    registry = FakeRegistry(raises=UnservedPoolError("no reader for this pool"))
    adapter = VenueNetPositionAdapter(registry)

    net = await adapter.net_position(POOL, "ETHUSDT")

    assert net is None


async def test_a_venue_position_read_error_is_ambiguous_not_an_exception() -> None:
    reader = FakeReader(raises=VenuePositionReadError("rate limited"))
    adapter = VenueNetPositionAdapter(FakeRegistry(reader))

    net = await adapter.net_position(POOL, "ETHUSDT")

    assert net is None


async def test_a_hang_past_the_timeout_is_ambiguous_not_an_exception() -> None:
    """Real (unfrozen) ``asyncio.timeout`` -- the first use anywhere in this
    codebase was ``RefreshPoolBalance``'s own hang test (design.md § S3);
    this mirrors it for the venue-position read."""
    reader = FakeReader(positions=[VenuePosition("ETHUSDT", Decimal("1"))], delay_seconds=0.05)
    adapter = VenueNetPositionAdapter(FakeRegistry(reader), timeout_seconds=0.01)

    net = await adapter.net_position(POOL, "ETHUSDT")

    assert net is None


async def test_no_matching_market_sums_to_zero_not_none() -> None:
    """A flat venue (nothing open on this market) is a real, known answer --
    zero -- not a failed read. Only a raised exception or a timeout may
    produce ``None``."""
    reader = FakeReader(positions=[VenuePosition("BTCUSDT", Decimal("2"))])
    adapter = VenueNetPositionAdapter(FakeRegistry(reader))

    net = await adapter.net_position(POOL, "ETHUSDT")

    assert net == Decimal("0")
