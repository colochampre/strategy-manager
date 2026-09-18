"""``BinanceVenuePositionReader`` — a thin translation from Binance's own
``Position`` read model into the domain's ``VenuePosition``, plus the one
exception ``ScanPools`` is allowed to swallow per pool.
"""

from decimal import Decimal

import pytest

from strategy_manager.reconciliation.application.ports import VenuePositionReadError
from strategy_manager.reconciliation.domain.positions import VenuePosition
from strategy_manager.reconciliation.infrastructure.binance_venue_position_reader import (
    BinanceVenuePositionReader,
)
from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.read_client import Position

POOL = ("binance", "usdt-m", "USDT")


def _position(symbol: str = "BTCUSDT", signed_size: str = "0.5") -> Position:
    return Position(
        symbol=symbol,
        position_side="BOTH",
        signed_size=Decimal(signed_size),
        entry_price=Decimal("60000"),
        mark_price=Decimal("60100"),
        notional=Decimal("30050"),
        unrealized_profit=Decimal("50"),
        liquidation_price=Decimal("40000"),
    )


class FakeBinanceClient:
    def __init__(
        self, positions: list[Position] | None = None, raises: Exception | None = None
    ) -> None:
        self._positions = positions or []
        self._raises = raises
        self.calls = 0

    async def open_positions(self) -> list[Position]:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._positions


async def test_translates_a_long_position_to_a_positive_net_base() -> None:
    client = FakeBinanceClient([_position(symbol="BTCUSDT", signed_size="0.5")])
    reader = BinanceVenuePositionReader(client)  # type: ignore[arg-type]

    positions = await reader.open_positions(POOL)

    assert positions == [VenuePosition("BTCUSDT", Decimal("0.5"))]


async def test_translates_a_short_position_to_a_negative_net_base() -> None:
    client = FakeBinanceClient([_position(symbol="AAVEUSDT", signed_size="-0.1")])
    reader = BinanceVenuePositionReader(client)  # type: ignore[arg-type]

    positions = await reader.open_positions(POOL)

    assert positions == [VenuePosition("AAVEUSDT", Decimal("-0.1"))]


async def test_reads_every_open_symbol_in_one_call() -> None:
    client = FakeBinanceClient(
        [_position(symbol="BTCUSDT"), _position(symbol="ETHUSDT", signed_size="-1")]
    )
    reader = BinanceVenuePositionReader(client)  # type: ignore[arg-type]

    positions = await reader.open_positions(POOL)

    assert {p.symbol for p in positions} == {"BTCUSDT", "ETHUSDT"}
    assert client.calls == 1


async def test_a_client_failure_is_translated_to_venue_position_read_error() -> None:
    client = FakeBinanceClient(raises=BinanceApiError("signature invalid"))
    reader = BinanceVenuePositionReader(client)  # type: ignore[arg-type]

    with pytest.raises(VenuePositionReadError, match="signature invalid"):
        await reader.open_positions(POOL)


async def test_the_reader_declares_its_own_exchange_and_venues() -> None:
    reader = BinanceVenuePositionReader(FakeBinanceClient())  # type: ignore[arg-type]

    assert reader.exchange == "binance"
    assert reader.venues == frozenset({"usdt-m"})
